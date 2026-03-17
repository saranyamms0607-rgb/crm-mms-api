
import csv
import re
from django.http import HttpResponse
from rest_framework.generics import GenericAPIView
from .models import Lead
import io
import json
import openpyxl
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import AllowAny
from Authentication.models import LoginUser,LoginRole
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from crmapp.pagination import LeadPagination
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from django.db.models import Q
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from crmapp.views import calculate_lead_status
from crmapp.views import CONNECT_STATUSES, NON_CONNECT_STATUSES, VOICEMAIL_LIKE_STATUSES
from datetime import datetime

class LeadCSVExportView(GenericAPIView):
    """
    GET → Export leads as CSV
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        filename = request.GET.get("filename", "leads")

        # Sanitize filename (important for security)
        filename = re.sub(r'[^a-zA-Z0-9_-]', '', filename)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="{filename}.csv"'
        )

        writer = csv.writer(response)

        # CSV Header
        writer.writerow([
            "id",
            "lead_name",
            "lead_email",
            "lead_phone",
            "lead_company",
            "lead_region",
            "lead_address",
            # "status",
        ])

        for lead in Lead.objects.all():
            writer.writerow([
                lead.id,
                lead.lead_name,
                lead.lead_email,
                lead.lead_phone,
                lead.lead_company,
                lead.lead_region,
                lead.lead_address,
                # lead.status,
            ])

        return response


def normalize_list(value):
        """
        Converts:
        'a,b'                     -> ['a','b']
        '["a","b"]'               -> ['a','b']
        '["a"]'                   -> ['a']
        'a'                       -> ['a']
        None / ''                 -> []
        """
        if not value:
            return []

        value = value.strip()

        # JSON array string
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = json.loads(value)
                return [str(v).strip() for v in parsed if str(v).strip()]
            except json.JSONDecodeError:
                pass

        # Comma separated
        return [v.strip() for v in value.split(",") if v.strip()]

class LeadCSVImportView(GenericAPIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    """
    POST → Import leads from CSV
    """
    
    def post(self, request):
        file = request.FILES.get("file")

        if not file:
            return Response(
                {"status": "error", "message": "File required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        file_name = file.name.lower()
        rows = []

        if file_name.endswith(".csv"):
            try:
                # Try UTF-8 first
                try:
                    decoded_file = file.read().decode("utf-8")
                except UnicodeDecodeError:
                    # Fallback to latin-1 (common for Excel CSVs on Windows)
                    file.seek(0)
                    decoded_file = file.read().decode("latin-1")
                
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string)
                rows = list(reader)
            except Exception as e:
                return Response({"status": "error", "message": f"Error reading CSV: {str(e)}"}, status=400)

        elif file_name.endswith(".xlsx"):
            try:
                workbook = openpyxl.load_workbook(file, data_only=True)
                sheet = workbook.active
                
                # Get headers from first row
                headers = [cell.value for cell in sheet[1]]
                
                # Iterate data rows
                for row_data in sheet.iter_rows(min_row=2, values_only=True):
                    if not any(row_data): continue # skip empty rows
                    rows.append(dict(zip(headers, row_data)))
            except Exception as e:
                return Response({"status": "error", "message": f"Error reading Excel: {str(e)}"}, status=400)
        else:
            return Response(
                {"status": "error", "message": "Invalid file format. Upload CSV or XLSX"},
                status=status.HTTP_400_BAD_REQUEST
            )

        created, skipped = 0, 0
        skip_reasons = {"missing_data": 0, "duplicates": 0}
        print("HEADERS:", rows[0].keys())

        for row in rows:
           # ---------------- NORMALIZE HEADERS ----------------
            # row = {str(k).strip().lower(): v for k, v in row.items()}
            def clean_key(k):
                return str(k).replace("\ufeff", "").strip().lower().replace(" ", "_")

            row = {clean_key(k): v for k, v in row.items()}

            # ---------------- NAME ----------------
            first_name = str(row.get("first_name") or "").strip()
            last_name = str(row.get("last_name") or "").strip()
            name = f"{first_name} {last_name}".strip()

            # ---------------- BASIC FIELDS ----------------
            company = str(row.get("company_name") or "").strip()
         
            website = str(row.get("website") or "").strip()
            designation = str(row.get("designation") or "").strip()
            region = str(row.get("city") or row.get("country") or "").strip()

            # ---------------- EMAILS (MERGE MULTIPLE) ----------------
            email_fields = [
                row.get("business_email"),
                row.get("personal_email"),
                row.get("person_personal_email"),
            ]

            email_list = []
            for e in email_fields:
                if e:
                    email_list.extend(normalize_list(str(e)))

            emails = [
                {"type": "email", "email": str(email).strip()}
                for email in email_list if str(email).strip()
            ]

            # ---------------- PHONES (MERGE MULTIPLE) ----------------
            phone_fields = [
                row.get("contacnumber"),
                row.get("person_phone"),
                row.get("company_phones"),
            ]

            phone_list = []
            for p in phone_fields:
                if p:
                    phone_list.extend(normalize_list(str(p)))

            # CLEAN + DUPLICATE CHECK
            phones = []
            is_duplicate = False

            for phone in phone_list:
                clean_phone = re.sub(r'[^0-9+]', '', str(phone))
                if not clean_phone:
                    continue

                if Lead.objects.filter(lead_phones__contains=[{"phone": clean_phone}]).exists():
                    is_duplicate = True
                    break

                phones.append({
                    "type": "mobile",
                    "phone": clean_phone,
                    "status": "assigned",
                    "call_count": 0
                })

            # ---------------- SKIP CONDITIONS ----------------
            if not name or not phones:
                skipped += 1
                skip_reasons["missing_data"] += 1
                continue

            if is_duplicate:
                skipped += 1
                skip_reasons["duplicates"] += 1
                continue

            # ---------------- LINKS ----------------
            other_links = {}

            if row.get("linkedin_url"):
                other_links["linkedin"] = row.get("linkedin_url")

            if row.get("person_linkedin_url"):
                other_links["person_linkedin"] = row.get("person_linkedin_url")

            if website:
                other_links["website"] = website

            # ---------------- OTHER DETAILS ----------------
            known_fields = {
                "first_name", "last_name", "company_name", "company",
                "website", "designation", "business_email", "personal_email",
                "person_personal_email", "contacnumber", "person_phone",
                "company_phones", "city", "country",
                "linkedin_url", "person_linkedin_url"
            }

            other_info = {}

            for key, value in row.items():
                if key not in known_fields and value not in [None, ""]:
                    other_info[key] = value

            # ---------------- CREATE LEAD ----------------
            Lead.objects.create(
                lead_name=name,
                lead_phones=phones,
                lead_emails=emails,
                lead_company=company,
                lead_website=website,
                lead_designation=designation,
                lead_region=region,
                other_links=other_links,
                other_lead_info=other_info,
                status="unassigned"
            )

            created += 1

        return Response(
            {
                "status": "success",
                "message": f"Import completed: {created} created, {skipped} skipped.",
                "details": {
                    "created": created,
                    "skipped_total": skipped,
                    "reason_missing_name_or_phone": skip_reasons["missing_data"],
                    "reason_duplicate_phone_number": skip_reasons["duplicates"]
                }
            },
            status=status.HTTP_201_CREATED
        )


@method_decorator(never_cache, name='dispatch')
class LoginUserListView(GenericAPIView):
    pagination_class = LeadPagination 

    

    def get(self, request, pk=None):
        try:
            if pk:
                user = get_object_or_404(LoginUser, pk=pk)
                return Response({
                    "status": "success",
                    "data": {
                        "id": user.id,
                        "email": user.email,
                        "phone_no": user.phone_no,
                        "name": user.asc_name,
                        "code": user.asc_code,
                        "location": user.asc_location,
                        "role": user.role.id,
                        "is_active": user.is_active,
                    }
                })

            users = LoginUser.objects.filter(is_active=True).exclude(role__name="SUPERADMIN")
            
            # If the requester is an ADMIN, they should not see other ADMINs
            logged_in_role = request.GET.get("logged_in_role", "").upper()
            if logged_in_role == "ADMIN":
                users = users.exclude(role__name="ADMIN")

            #  FIELD FILTERS
            if request.GET.get("email"):
                users = users.filter(email__icontains=request.GET["email"])

            asc_names = request.GET.getlist("asc_name")
            if asc_names:
                users = users.filter(asc_name__in=asc_names)

            asc_codes = request.GET.getlist("asc_code")
            if asc_codes:
                users = users.filter(asc_code__in=asc_codes)

            asc_locations = request.GET.getlist("asc_location")
            if asc_locations:
                users = users.filter(asc_location__in=asc_locations)


            roles = request.GET.getlist("role")
            if roles:
                users = users.filter(role__name__in=roles)


            #  DATE FILTERS
            start_date = request.GET.get("start_date")
            end_date = request.GET.get("end_date")

            if start_date and end_date:
                # If BOTH are provided, filter by range
                users = users.filter(
                    created_at__date__range=[start_date, end_date]
                )
            elif start_date:
                # If ONLY start_date is provided, filter by that specific date
                date_obj = parse_date(start_date)
                if date_obj:
                    users = users.filter(created_at__date=date_obj)
            elif end_date:
                # If ONLY end_date is provided, filter everything up to that date
                date_obj = parse_date(end_date)
                if date_obj:
                    users = users.filter(created_at__date__lte=date_obj)

            users = users.order_by("-id")

            try:
                page = self.paginate_queryset(users)
            except Exception:
                # Defensive: invalid or out-of-range pagination params (page, page_size)
                # Return empty paginated response instead of 404 or 500 to keep frontend stable.
                paginator = self.pagination_class()
                total_count = users.count()
                page_size = paginator.get_page_size(request) or paginator.page_size
                total_pages = max(1, (total_count + page_size - 1) // page_size)
                current_page = min(int(request.GET.get(paginator.page_query_param, 1)), total_pages)

                return Response({
                    "status": "success",
                    "count": total_count,
                    "total_pages": total_pages,
                    "current_page": current_page,
                    "next": None,
                    "previous": None,
                    "message": "Users fetched successfully",
                    "data": [],
                })

            if page is not None:
                data = [{
                    "id": u.id,
                    "email": u.email,
                    "phone_no": u.phone_no,
                    "asc_name": u.asc_name,
                    "asc_code": u.asc_code,
                    "asc_location": u.asc_location,
                    "role": u.role.name,
                    "is_active": u.is_active,
                    "created_at": u.created_at,
                } for u in page]

                return self.get_paginated_response({
                    "message": "Users fetched successfully",
                    "data": data
                })

        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=500)

   

    def post(self, request):
        try:
            data = request.data

            required_fields = ["email", "password", "asc_name", "asc_code", "asc_location", "role"]
            missing_fields = [field for field in required_fields if not data.get(field)]

            if missing_fields:
                return Response(
                    {
                        "status": "error",
                        "message": f"Missing required fields: {', '.join(missing_fields)}",
                        "data": []
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

       
            role_value = data.get("role")
            
            if role_value:
                if str(role_value).isdigit():
                    # role is an ID
                    role = get_object_or_404(LoginRole, id=int(role_value))
                else:
                    # role is a name like "SUPERADMIN"
                    role = get_object_or_404(LoginRole, name=role_value)


            if not role:
                return Response(
                    {
                        "status": "error",
                        "message": f"Invalid role: {role}",
                        "data": []
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            user = LoginUser.objects.create(
                email=data.get("email"),
                phone_no=data.get("phone_no"),
                asc_name=data.get("asc_name"),
                asc_code=data.get("asc_code"),
                asc_location=data.get("asc_location"),
                password=make_password(data.get("password")),
                role=role,
                is_active=data.get("is_active", True),
                is_staff=data.get("is_staff", False),
            )
            
            
            return Response(
                {
                    "status": "success",
                    "message": "User created successfully",
                    "data": {
                        "id": user.id,
                        "email": user.email,
                        "role": user.role.name
                    }
                },
                status=status.HTTP_201_CREATED
            )

        except IntegrityError:
            return Response(
                {
                    "status": "error",
                    "message": "User with this email already exists",
                    "data": []
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            return Response(
                {
                    "status": "error",
                    "message": "Something went wrong",
                    "error": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        

    def put(self, request, pk):
        try:
            user = get_object_or_404(LoginUser, pk=pk)
            data = request.data

            user.email = data.get("email", user.email)
            user.phone_no = data.get("phone_no", user.phone_no)
            user.asc_name = data.get("asc_name", user.asc_name)
            user.asc_code = data.get("asc_code", user.asc_code)
            user.asc_location = data.get("asc_location", user.asc_location)
            user.is_active = data.get("is_active", user.is_active)

            role_value = data.get("role")

            if role_value:
                if str(role_value).isdigit():
                    # role is an ID
                    user.role = get_object_or_404(LoginRole, id=int(role_value))
                else:
                    # role is a name like "SUPERADMIN"
                    user.role = get_object_or_404(LoginRole, name=role_value)


            if data.get("password"):
                user.password = make_password(data.get("password"))

            user.save()

            return Response({
                "status": "success",
                "message": "User updated successfully",
                "data": {
                    "id": user.id,
                    "email": user.email,
                    "role": user.role.name
                }
            }, status=status.HTTP_200_OK)

        except LoginRole.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Invalid role selected",
                "data": []
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                "status": "error",
                "message": "Failed to update user",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        try:
            user = get_object_or_404(LoginUser, pk=pk)
            user.is_active = False
            user.save()

            return Response({
                "status": "success",
                "message": "User deleted successfully",
                "data": []
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "status": "error",
                "message": "Failed to delete user",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class ASCFilterListView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logged_in_role = request.GET.get("logged_in_role", "").upper()
        
        # Base queryset for filter options: active users, excluding SUPERADMIN
        base_qs = LoginUser.objects.filter(is_active=True).exclude(role__name="SUPERADMIN")
        
        # If logged in as ADMIN, also exclude other ADMINs from filter options
        if logged_in_role == "ADMIN":
            base_qs = base_qs.exclude(role__name="ADMIN")

        asc_names = (
            base_qs
            .exclude(asc_name__isnull=True)
            .exclude(asc_name__exact="")
            .values_list("asc_name", flat=True)
            .distinct()
        )

        asc_codes = (
            base_qs
            .exclude(asc_code__isnull=True)
            .exclude(asc_code__exact="")
            .values_list("asc_code", flat=True)
            .distinct()
        )

        asc_locations = (
            base_qs
            .exclude(asc_location__isnull=True)
            .exclude(asc_location__exact="")
            .values_list("asc_location", flat=True)
            .distinct()
        )

        return Response({
            "status": "success",
            "data": {
                "asc_names": sorted(asc_names),
                "asc_codes": sorted(asc_codes),
                "asc_locations": sorted(asc_locations),
            }
        })


@method_decorator(never_cache, name='dispatch')
class AgentCSVUpdateView(GenericAPIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):

        assigned_to_id = request.data.get("assigned_to")
        file = request.FILES.get("file")

        if not assigned_to_id:
            return Response({"status": "error", "message": "assigned_to required"}, status=400)

        try:
            assigned_user = LoginUser.objects.get(id=int(assigned_to_id), is_active=True)
        except LoginUser.DoesNotExist:
            return Response({"status": "error", "message": "Invalid agent"}, status=404)

        if not file:
            return Response({"status": "error", "message": "File required"}, status=400)

        # ---------- READ CSV ----------
        try:
            decoded = file.read().decode("utf-8", errors="ignore")
            rows = list(csv.DictReader(io.StringIO(decoded)))
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=400)

        created = 0
        updated = 0
        skipped = 0
        errors = 0
        duplicate_rows = []
        duplicate_count = 0
        seen_phones = set()

        # ---------------- STATUS MAPPING ----------------
        def map_status(val):
            if not val:
                return None

            s = str(val).strip().lower()

            mapping = {
                # Converted
                "sale won": "converted",
                "converted - sale": "converted",
                "converted - payment pending": "converted",
                "convert/ sale": "converted",

                # Not interested / Sale lost
                "sale lost": "sale-lost",
                "not interested": "not-interested",

                # Interested / Prospect
                "interested": "interested",
                "prospect": "prospect",

                # Followup
                "long follow up": "followup",
                "follow up": "followup",
                "email request": "followup",
                "call back": "callback",

                # DND
                "do not call - dnd": "dnd",
                "dnd": "dnd",

                # Re-research
                "wrong number": "wrong-number",
                "invalid #": "invalid",
                "fax tone": "fax-tone",
                "not in service": "not-in-service",

                # Invalid
                "duplicate": "duplicate",
                "call blocked as spam": "invalid",

                # No response types
                "no response": "unanswered",
                "switched off": "unanswered",
                "not accepting call": "not-accepting",
                "unanswered": "unanswered",
                "call cannot be completed": "call-failed",
                "receptionist/ operator": "receptionist",
                "voice mail": "general-voicemail",
                "language barrier": "language-barrier",
                "hung up": "hung-up",
                "disconnected number": "disconnected",
            }

            return mapping.get(s, s)

        # -------- STATUS PRIORITY --------
        def get_priority_status(row):

            fields = [
                "Disposition",
                "FINAL STATUS",
                "Call 3 Dispo",
                "Call 2 Dispo",
                "Call 1 Dispo"
            ]

            for f in fields:
                if row.get(f):
                    return map_status(row.get(f))

            return None

        # -------- CALL COUNT --------
        def get_call_count(row):
            count = 0
            if row.get("Call 1"):
                count += 1
            if row.get("Call 2"):
                count += 1
            if row.get("Call 3"):
                count += 1
            return count

        # -------- ATTEMPT BUCKET --------
        def get_attempt_bucket(call_count):
            if call_count == 1:
                return "second-attempt"
            elif call_count == 2:
                return "third-attempt"
            elif call_count >= 3:
                return "completed"
            return "assigned"

        # -------- PROCESS --------
        for row in rows:
            try:
                phone_raw = row.get("Mobile No.") or row.get("Phone")
                if not phone_raw:
                    skipped += 1
                    continue

                phone = re.sub(r'[^0-9+]', '', str(phone_raw))

                if not phone:
                    skipped += 1
                    continue

                # CSV duplicate detection
                if phone in seen_phones:
                    duplicate_count += 1
                    duplicate_rows.append(row)
                    continue
                seen_phones.add(phone)

                lead = Lead.objects.filter(
                    lead_phones__icontains=f'"{phone}"',
                    is_active=True
                ).first()

                call_count = get_call_count(row)
                status_val = get_priority_status(row)

                name = row.get("Full Name") or "Unknown"
                company = row.get("Company")
                designation = row.get("Designation")
                email_raw = row.get("Email") or row.get("Emails") or row.get("business_email")
                website_raw = row.get("Website") or row.get("Lead Website") or row.get("website")

                email = str(email_raw).strip() if email_raw else None
                website = str(website_raw).strip() if website_raw else None

                # ---------- CREATE NEW ----------
                if not lead:
                    phone_entry = {
                        "type": "mobile",
                        "phone": phone,
                        "status": status_val or "assigned",
                        "call_count": call_count
                    }

                    lead_status = None

                    if status_val in ["callback", "followup","Callback-Voicemail"]:
                        lead_status = "followup"
                    elif status_val in ["interested", "prospect"]:
                        lead_status = "prospect"
                    elif status_val == "dnd":
                        lead_status = "dnd"
                    elif status_val in ["invalid", "wrong-number", "not-in-service", "fax-tone"]:
                        lead_status = "re-research"
                    elif status_val == "converted":
                        lead_status = "converted"
                    elif status_val == "sale-lost":
                        lead_status = "sale-lost"
                    elif status_val == "not-interested":
                        lead_status = "sale-lost"
                    else:
                        lead_status = get_attempt_bucket(call_count)

                    tracking = {}
                    if lead_status in ["second-attempt", "third-attempt", "completed"]:
                        tracking["voicemail_count"] = call_count

                    Lead.objects.create(
                        lead_name=name,
                        lead_company=company,
                        lead_designation=designation,
                        lead_emails=[{"type": "office", "email": email}] if email else [],
                        lead_website=website,
                        lead_phones=[phone_entry],
                        status=lead_status,
                        status_tracking=tracking,
                        assigned_to=assigned_user
                    )

                    created += 1
                    continue

                # ---------- UPDATE EXISTING ----------
                phones = lead.lead_phones or []

                for p in phones:
                    if str(p.get("phone")) == phone:
                        if status_val:
                            p["status"] = status_val
                        p["call_count"] = call_count
                        break

                # Lead status decision
                if status_val in ["callback", "followup"]:
                    lead.status = "followup"
                elif status_val in ["interested", "prospect"]:
                    lead.status = "prospect"
                elif status_val == "dnd":
                    lead.status = "dnd"
                elif status_val in ["invalid", "wrong-number", "not-in-service", "fax-tone"]:
                    lead.status = "re-research"
                elif status_val == "converted":
                    lead.status = "converted"
                elif status_val == "sale-lost":
                    lead.status = "sale-lost"
                elif status_val == "not-interested":
                    lead.status = "sale-lost"
                else:
                    lead.status = get_attempt_bucket(call_count)

                # Update tracking if needed
                tracking = lead.status_tracking or {}
                if lead.status in ["second-attempt", "third-attempt", "completed"]:
                    tracking["voicemail_count"] = max(tracking.get("voicemail_count", 0), call_count)
                lead.status_tracking = tracking

                # Update email/website if missing
                if email and not lead.lead_emails:
                    lead.lead_emails = [{"type": "office", "email": email}]
                if website and not lead.lead_website:
                    lead.lead_website = website

                lead.assigned_to = assigned_user
                lead.lead_phones = phones
                lead.status_updated_at = timezone.now()
                lead.save()

                updated += 1

            except Exception:
                errors += 1
                continue

        return Response({
            "status": "success",
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "duplicate_count": duplicate_count,
            "duplicate_rows": duplicate_rows
        })

