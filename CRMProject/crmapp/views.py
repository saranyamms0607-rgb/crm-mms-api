import json
import re
from django.http import HttpResponse
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from .pagination import LeadPagination
from rest_framework_simplejwt.authentication import JWTAuthentication
from Authentication.models import LoginUser
from django.db.models import Q, Value, CharField, Count, F, Min, Max
from django.utils import timezone
from django.utils.timezone import now
from datetime import timedelta
from django.utils.dateparse import parse_datetime, parse_date
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from django.db.models.functions import Replace, Cast
from configurations.models import Lead
from rest_framework import status
from rest_framework import status as sts
VOICEMAIL_LIKE_STATUSES = {
                "voicemail",
                "direct-voicemail",
                "general-voicemail",
                "fax-tone",
                "disconnected",
                "receptionist",
                "unanswered",
                "call-failed",
                "spam-blocked",
                "not-accepting",
                "hung-up",
            }
CONNECT_STATUSES = {
            "email-request",
            "not-interested",
            "callback",
            "interested",
            "language-barrier",
            "hung-up",
            "followup",
            "wrong-number",
            "converted",
        }

NON_CONNECT_STATUSES = {
            "fax-tone",
            "voicemail",
            "direct-voicemail",
            "general-voicemail",
            "not-in-service",
            "disconnected",
            "receptionist",
            "unanswered",
            "call-failed",
            "spam-blocked",
            "not-accepting",
            "dnd",
            "duplicate",
            "invalid",
        }
INVALID_STATUSES = { "duplicate", "disconnected"}
RE_RESEARCH_STATUSES = {"not-in-service", "invalid", "wrong-number", "fax-tone"}

# ================= UTILITY FUNCTIONS =================

def normalize_lead_items(items, item_type):
    """Normalize legacy string-based data or list-based data into the expected object format."""
    result = []
    for item in items or []:
        if isinstance(item, str):
            if item_type == 'email':
                result.append({"type": "office", "email": item})
            else:
                result.append({"type": "mobile", "phone": item, "status": "assigned", "call_count": 0})
        elif isinstance(item, list) and len(item) >= 1:
            # Handle [phone, status] legacy format
            val = item[0]
            if item_type == 'email':
                result.append({"type": "office", "email": val})
            else:
                stat = item[1] if len(item) > 1 else "assigned"
                result.append({"type": "mobile", "phone": val, "status": stat, "call_count": 0})
        elif isinstance(item, dict):
            # Ensure required keys exist for phones
            if item_type == 'phone':
                item.setdefault("status", "assigned")
                item.setdefault("call_count", 0)
            result.append(item)
    return result

def calculate_lead_status(phones, current_status, tracking, general_remarks=""):
    """
    Centralized status transition logic.
    Returns: (new_status, updated_tracking, error_message)
    """
    phone_statuses = [p.get("status") for p in phones if p.get("status")]
    new_status = current_status
    error_msg = None

    # 1. High Priority Statuses
    if any(p.get("status") == "dnd" for p in phones):
        new_status = "dnd"
    elif any(p.get("status") == "interested" for p in phones):
        new_status = "prospect"
    elif any(p.get("status") == "email-request" for p in phones):
        new_status = "followup"
    elif any(p.get("status") in RE_RESEARCH_STATUSES for p in phones):
        new_status = "re-research"
    elif any(p.get("status") == "not-interested" for p in phones):
        new_status = "sale-lost"
    elif any(p.get("status") == "converted" for p in phones):
        new_status = "deal-won"
    elif all(p.get("status") in INVALID_STATUSES for p in phones):
        new_status = "invalid"    
    elif "callback" in phone_statuses or "followup" in phone_statuses:
        new_status = "followup"
    elif "prospect" in phone_statuses:
        new_status = "prospect"
    
    # 2. Attempt Transition Logic (Voicemail/No-Connect cases)
    elif all(
        p.get("status") in VOICEMAIL_LIKE_STATUSES or 
        p.get("status") in INVALID_STATUSES or 
        p.get("status") in {"email-request", "hung-up", "language-barrier"}
        for p in phones
    ):
        voicemail_count = tracking.get("voicemail_count", 0)
        
        # Fallback for inconsistent state (e.g. from CSV import)
        if voicemail_count == 0:
            if current_status == "second-attempt":
                voicemail_count = 1
            elif current_status == "third-attempt":
                voicemail_count = 2
            elif current_status == "completed":
                voicemail_count = 3

        voicemail_tracking = tracking.get("voicemail") or []
        
        # 12-hour enforcement
        if voicemail_tracking:
            last_entry = voicemail_tracking[-1]
            dt_str = last_entry.get("datetime") or last_entry.get("date")
            if dt_str:
                last_time = parse_datetime(dt_str)
                if last_time:
                    if timezone.is_naive(last_time):
                        last_time = timezone.make_aware(last_time)
                    if (timezone.now() - last_time) < timedelta(hours=12):
                        return new_status, tracking, "You can update this status again on the next day."

        # Increment attempts
        if voicemail_count == 0:
            new_status = "second-attempt"
        elif voicemail_count == 1:
            new_status = "third-attempt"
        else:
            new_status = "completed"

        tracking.setdefault("voicemail", [])
        tracking["voicemail"].append({
            "datetime": timezone.now().isoformat(),
            "remarks": general_remarks or "Voicemail-like status update"
        })
        tracking["voicemail_count"] = voicemail_count + 1

    # 3. Track History
    for phone in phones:
        st = phone.get("status")
        if not st or st in VOICEMAIL_LIKE_STATUSES: continue
        
        tracking.setdefault(st, [])
        if not isinstance(tracking[st], list): tracking[st] = []
        tracking[st].append({
            "datetime": timezone.now().isoformat(),
            "remarks": phone.get("remarks", "")
        })

    tracking.setdefault("lead_status", [])
    tracking["lead_status"].append({
        "status": new_status,
        "datetime": timezone.now().isoformat(),
        "remarks": general_remarks
    })

    return new_status, tracking, None
@method_decorator(never_cache, name='dispatch')
class LeadDetailView(GenericAPIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = LeadPagination

    def get(self, request, pk=None):
        user_email = request.user.email
        user = LoginUser.objects.get(email=user_email)
        role = user.role.name

        

        if pk:
            # GET single lead
            try:
                lead = Lead.objects.select_related("assigned_to").only(
                    "id",
                    "lead_name",
                    "lead_emails",
                    "lead_phones",
                    "lead_company",
                    "lead_region",
                    "lead_website",
                    "lead_designation",
                    "lead_address",
                    "status","remarks",
                    "assigned_to__asc_name",
                ).get(id=pk, is_active=True)
                # Optimization: Combined exclusion and value list
                company_lead_ids = list(
                    Lead.objects.filter(
                        is_active=True,
                        lead_company=lead.lead_company,
                        status=lead.status
                    )
                    .exclude(id=lead.id)
                    .order_by("id")
                    .values_list("id", flat=True)
                )

                # --- DUPLICATE PHONE CHECK ---
                duplicate_records = []
                # 1. Check for other leads IN DATABASE with same phone number
                phones_data = lead.lead_phones or []
                for p in phones_data:
                    phone_no = p.get("phone") if isinstance(p, dict) else p
                    if not phone_no: continue
                    
                    dupes = Lead.objects.filter(
                        is_active=True,
                        lead_phones__contains=[{"phone": str(phone_no)}]
                    ).exclude(id=lead.id).only("id", "lead_name", "lead_designation")
                    
                    for d in dupes:
                        rec = {
                            "id": d.id,
                            "name": d.lead_name,
                            "designation": d.lead_designation,
                            "type": "database"
                        }
                        if not any(r.get("id") == d.id for r in duplicate_records):
                            duplicate_records.append(rec)
                
                # 2. Add duplicates SKIPPED DURING IMPORT (from JSON field)
                import_dupes = lead.duplicate_leads or []
                main_name = lead.lead_name.strip().lower()

                for idup in import_dupes:
                    dup_name = idup.get("name", "").strip()
                    # Skip if the duplicate name is exactly the same as main lead name
                    if dup_name.lower() == main_name:
                        continue
                        
                    rec = {
                        "name": dup_name,
                        "designation": idup.get("designation"),
                        "phone": idup.get("clean_phone"),
                        "type": "import_skipped"
                    }
                    duplicate_records.append(rec)
                # -----------------------------

                data = {
                    "id": lead.id,
                    "lead_name": lead.lead_name,
                    "lead_company": lead.lead_company,
                    "lead_region": lead.lead_region,
                    "lead_website": lead.lead_website,
                    "lead_designation": lead.lead_designation,
                    "lead_address": lead.lead_address,
                    "lead_emails": normalize_lead_items(lead.lead_emails, 'email'),
                    "lead_phones": normalize_lead_items(lead.lead_phones, 'phone'),
                    "remarks": lead.remarks,
                    "status": lead.status,
                    "assigned_to": lead.assigned_to.asc_name if lead.assigned_to else None,
                }
                CALL_STATUS_FLOW = [
                    ("voicemail", "No Contact"),
                    ("callback", "Callback Requested"),
                    ("interested", "Interested"),
                    ("prospect", "Prospect"),
                    ("not-interested", "Not Interested"),
                    ("dnd", "DND"),
                ]

                tracking_data = []

                stored = lead.status_tracking or {}


                for key, label in CALL_STATUS_FLOW:
                    entries = stored.get(key, [])

                    if isinstance(entries, dict):
                        entries = [entries]

                    latest = entries[-1] if entries else {}

                    tracking_data.append({
                        "status": key,
                        "label": label,
                        "date": latest.get("datetime"),
                        "remarks": latest.get("remarks"),
                        "history": entries
                    })


                return Response(
                    {"status": "success",  "message": "Lead retrieved successfully",
                     "data": data,"tracking":tracking_data,
                     "related_leads": company_lead_ids,
                     "duplicate_records": duplicate_records},
                    status=status.HTTP_200_OK
                )

            except Lead.DoesNotExist:
                return Response(
                    {"error": "Lead not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        status_filter = request.GET.get("status")
        search = request.GET.get("search")
        name = request.GET.get("name")
        company = request.GET.get("company")
        designation = request.GET.get("designation")
        today = request.GET.get("today")
        today_date = timezone.now().date()
        filter_date = request.GET.get("date")
        from_date = request.GET.get("from")
        to_date = request.GET.get("to")
        phone_status_filter = request.GET.get("phone_status")

        if role == "AGENT":

            leads = Lead.objects.filter(
                assigned_to=user,
                is_active=True
            )
        else:
            leads = Lead.objects.filter(is_active=True)

        if filter_date or (from_date and to_date):
            filtered_ids = []

            for lead in leads:
                tracking = lead.status_tracking or {}

                for status_key, entries in tracking.items():

                    if isinstance(entries, dict):
                        entries = [entries]

                    for entry in entries:
                        dt_str = entry.get("datetime")
                        entry_status = entry.get("status", status_key)

                        if not dt_str:
                            continue

                        dt = parse_datetime(dt_str)
                        if not dt:
                            continue

                        entry_date = dt.date()

                        # Apply status filter if provided
                        if status_filter and entry_status != status_filter:
                            continue

                        # Single date filter
                        if filter_date and str(entry_date) == filter_date:
                            filtered_ids.append(lead.id)
                            break

                        # Date range filter
                        if from_date and to_date:
                            if from_date <= str(entry_date) <= to_date:
                                filtered_ids.append(lead.id)
                                break

                    else:
                        continue
                    break

            leads = leads.filter(id__in=filtered_ids)

        

        if status_filter:
            
            leads = leads.filter(status=status_filter)
        if search:
            # 1. Normalize search input for phone matching
            search_normalized = re.sub(r'[^0-9]', '', search)

            # 2. Base filters (Name, Company, Designation)
            search_query = Q(lead_name__icontains=search) | \
                           Q(lead_company__icontains=search) | \
                           Q(lead_designation__icontains=search)

            # 3. Add Phone search ONLY if there are digits in the search term
            if search_normalized:
                leads = leads.annotate(
                    phones_text=Cast('lead_phones', CharField()),
                ).annotate(
                    phones_clean=Replace(
                        Replace(
                            Replace(
                                Replace(
                                    Replace(
                                        Replace(
                                            Replace(
                                                'phones_text',
                                                Value('-'), Value('')
                                            ),
                                            Value('('), Value('')
                                        ),
                                        Value(')'), Value('')
                                    ),
                                    Value(' '), Value('')
                                ),
                                Value('"'), Value('')
                            ),
                            Value('['), Value('')
                        ),
                        Value(']'), Value('')
                    )
                )
                search_query |= Q(phones_clean__icontains=search_normalized)

            leads = leads.filter(search_query)

        if name:
            leads = leads.filter(lead_name__icontains=name)

        if company:
            leads = leads.filter(lead_company__icontains=company)

        if designation:
            leads = leads.filter(lead_designation__icontains=designation)
        
        if phone_status_filter:
            # Filter for leads where at least one phone has the target status
            # Using __icontains on the JSON field as a robust fallback for partial list matching
            leads = leads.filter(lead_phones__icontains=f'"status": "{phone_status_filter}"')

        if today=="true" and status_filter == "followup":
            today_filtered_leads = []

            for lead in leads:
                phones = lead.lead_phones or []
                match_today = False

                for phone in phones:
                    followup_dt = phone.get("followup_date")
                    status_val = phone.get("status")

                    if not followup_dt or status_val not in ("callback", "followup"):
                        continue

                    try:
                        if isinstance(followup_dt, str):
                            dt = parse_datetime(followup_dt)
                        else:
                            dt = followup_dt

                        if dt and dt.date() == today_date:
                            match_today = True
                            break

                    except Exception:
                        continue

                if match_today:
                    today_filtered_leads.append(lead.id)

            today_ids = today_filtered_leads
            leads = leads.filter(id__in=today_ids)


        # --- Grouping Logic Start ---
        # We want to show one lead per (Company, Status, AssignedTo) to avoid duplicates.
        # However, for leads without a company name, we show all of them individually.

        # 1. Identify representative IDs for leads with a company
        with_company_reps = (
            leads.exclude(Q(lead_company__isnull=True) | Q(lead_company=""))
            .values('lead_company', 'status', 'assigned_to')
            .annotate(max_id=Max('id'))
            .values_list('max_id', flat=True)
        )

        # 2. Identify IDs for leads without a company
        without_company_ids = (
            leads.filter(Q(lead_company__isnull=True) | Q(lead_company=""))
            .values_list('id', flat=True)
        )

        # 3. Apply the filtered IDs back to the EXISTING leads QuerySet
        # This ensures search filters, is_active, and assigned_to constraints are preserved.
        combined_ids = list(with_company_reps) + list(without_company_ids)
        leads = leads.filter(id__in=combined_ids)
        # --- Grouping Logic End ---


        leads = leads.order_by("-status_updated_at", "id").select_related(
            "assigned_to"
        ).only(
            "id",
            "lead_name",
            "lead_emails",
            "lead_phones",
            "lead_company",
            "lead_region",
            "lead_website",
            "lead_designation",
            "lead_address",
            "status",
            "remarks",
            "assigned_to__asc_name",
        )
        

       

        #  PAGINATION STARTS HERE
        paginator = self.pagination_class()
        try:
            page = paginator.paginate_queryset(leads, request)
        except Exception as e:
            # If the requested page is out of range, DRF raises NotFound which becomes 404.
            # Instead of propagating 404 to the frontend, return an empty paginated response.
            from rest_framework import status as _sts

            total_count = leads.count()
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
                "message": "Lead fetched successfully",
                "data": [],
                "assigned_to": {"user_id": user.id}
            }, status=_sts.HTTP_200_OK)

        data = [
            {
                "id": lead.id,
                "lead_name": lead.lead_name,
                "lead_emails": lead.lead_emails,
                "lead_phones": lead.lead_phones,
                "lead_company": lead.lead_company,
                "lead_region": lead.lead_region,
                "lead_website": lead.lead_website,
                "lead_designation": lead.lead_designation,
                "lead_address": lead.lead_address,
                "status": lead.status,
                "remarks": lead.remarks,
                "status_updated_at": lead.status_updated_at,
                "assigned_to": (
                    f"{lead.assigned_to.asc_name} "
                    if lead.assigned_to else None
                ),
            }
            for lead in page
        ]

        return paginator.get_paginated_response({
            "status":"success",
            "message": "Lead fetched successfully",
            "data": data,
            "assigned_to": {
                "user_id": user.id
            }
        })



    def post(self, request):
        lead_id = request.data.get("lead_id")
        lead_ids = request.data.get("lead_ids")  
        agent_id = request.data.get("agent_id")

        if not agent_id or (not lead_id and not lead_ids):
            return Response(
                {
                    "status": "Fail",
                    "message": "agent_id and lead_id or lead_ids are required"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            agent = LoginUser.objects.get(
                id=agent_id,
                is_active=True,
                role__name="AGENT"
            )

            #  BULK ASSIGN
            if lead_ids:
                leads = Lead.objects.filter(
                    id__in=lead_ids,
                    is_active=True
                )

                if not leads.exists():
                    return Response(
                        {
                            "status": "Fail",
                            "message": "No valid leads found"
                        },
                        status=status.HTTP_404_NOT_FOUND
                    )

                # 🔥 IMPORTANT FIX (evaluate queryset first)
                companies = list(
                    leads.values_list("lead_company", flat=True)
                )

                # 🔥 Now safe to update
                all_company_leads = Lead.objects.filter(
                    lead_company__in=companies,
                    is_active=True
                )

                count = all_company_leads.count()

                all_company_leads.update(
                    assigned_to=agent,
                    status="assigned",
                    assigned_at=timezone.now(),
                    status_updated_at=timezone.now()
                )

                return Response(
                    {
                        "status": "success",
                        "message": f"{count} leads assigned successfully"
                    },
                    status=status.HTTP_200_OK
                )

            # SINGLE ASSIGN (OLD FLOW)
            lead = Lead.objects.get(id=lead_id, is_active=True)

            company = lead.lead_company  #  evaluate first

            Lead.objects.filter(
                lead_company=company,
                is_active=True
            ).update(
                assigned_to=agent,
                status="assigned",
                assigned_at=timezone.now(),
                status_updated_at=timezone.now()
            )



            return Response(
                {
                    "status": "success",
                    "message": "Lead assigned successfully"
                },
                status=status.HTTP_200_OK
            )

        except Lead.DoesNotExist:
            return Response(
                 {
                    "status": "Fail",
                    "message": "Lead not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )

        except LoginUser.DoesNotExist:
            return Response(
                {
                    "status": "Fail",
                    "message": "Invalid agent"
                },
                status=status.HTTP_400_BAD_REQUEST
            )
    
        
    def put(self, request, pk=None):
        try:
            lead = Lead.objects.get(id=pk, is_active=True)
            if lead.status == 'unassigned':
                return Response(
                    {"error": "Cannot update unassigned lead. Please assign it first."},
                    status=sts.HTTP_400_BAD_REQUEST
                )
        except Lead.DoesNotExist:
            return Response(
                {"error": "Lead not found"},
                status=sts.HTTP_404_NOT_FOUND
            )
           
        # ===== STORE OLD PHONE DATA (FOR CALL COUNT) =====
        old_phones = lead.lead_phones or []

        # Normalize old phones into list of dicts
        normalized_old_phones = []
        for p in old_phones:
            if isinstance(p, dict) and p.get("phone"):
                normalized_old_phones.append(p)
            elif isinstance(p, str):
                normalized_old_phones.append({"phone": p, "status": "assigned", "call_count": 0})
            elif isinstance(p, list) and len(p) >= 2:
                # Legacy format: [phone, status]
                normalized_old_phones.append({"phone": p[0], "status": p[1], "call_count": 0})
        old_phone_map = {p["phone"]: p for p in normalized_old_phones}

        # ================= RAW DATA =================
        raw_emails = request.data.get("lead_emails")
        raw_phones = request.data.get("lead_phones")
        raw_address = request.data.get("lead_address")
        general_remarks = request.data.get("remarks", "")

        # ================= SAVE RAW AS-IS =================
        if raw_emails is not None:
            lead.lead_emails = raw_emails

        if raw_phones is not None:
            lead.lead_phones = raw_phones

        if raw_address is not None:
            lead.lead_address = raw_address

        phones = raw_phones or []

        # Normalize incoming phones as well
        normalized_phones = []
        for p in phones:
            if isinstance(p, dict) and p.get("phone"):
                normalized_phones.append(p)
            elif isinstance(p, str):
                normalized_phones.append({"phone": p, "status": "assigned", "call_count": 0})
            elif isinstance(p, list) and len(p) >= 2:
                normalized_phones.append({"phone": p[0], "status": p[1], "call_count": 0})
        phones = normalized_phones

        phones = normalize_lead_items(phones, 'phone')

        # ================= VALIDATION & CALL COUNT =================
        for phone in phones:
            phone_no = phone.get("phone")
            new_p_status = phone.get("status")

            if not phone_no or not new_p_status:
                continue

            # Increment call attempts for REAL calls
            if new_p_status not in VOICEMAIL_LIKE_STATUSES and new_p_status != "email-request":
                old_p = old_phone_map.get(phone_no, {})
                old_p_status = old_p.get("status")
                if old_p_status != new_p_status:
                    phone["call_count"] = old_p.get("call_count", 0) + 1
                else:
                    phone["call_count"] = old_p.get("call_count", 0)

        lead.remarks = general_remarks

        # ================= CALCULATE STATUS & TRACKING =================
        tracking = lead.status_tracking or {}
        new_status, tracking, error = calculate_lead_status(
            phones, lead.status, tracking, general_remarks
        )

        if error:
            return Response({"status": "Fail", "message": error}, status=sts.HTTP_400_BAD_REQUEST)

        # ================= SAVE =================
        lead.lead_emails = raw_emails if raw_emails is not None else lead.lead_emails
        lead.lead_phones = phones
        lead.lead_address = raw_address if raw_address is not None else lead.lead_address
        lead.lead_website = request.data.get("lead_website", lead.lead_website)
        lead.lead_designation = request.data.get("lead_designation", lead.lead_designation)
        lead.status = new_status
        lead.status_tracking = tracking
        lead.status_updated_at = timezone.now()

        # --- UPDATE DUPLICATE LEADS FIELD ---
        duplicate_records = []
        for p in phones:
            phone_no = p.get("phone")
            if not phone_no: continue
            
            dupes = Lead.objects.filter(
                is_active=True,
                lead_phones__contains=[{"phone": str(phone_no)}]
            ).exclude(id=lead.id).only("id", "lead_name", "lead_designation")
            
            for d in dupes:
                rec = {
                    "id": d.id,
                    "name": d.lead_name,
                    "designation": d.lead_designation
                }
                if rec not in duplicate_records:
                    duplicate_records.append(rec)
        lead.duplicate_leads = duplicate_records
        # ------------------------------------

        lead.save()

        return HttpResponse(
            json.dumps({
                "status": "success",
                "message": "Lead updated successfully",
                "lead_status": new_status,
                "tracking": tracking
            }),
            content_type="application/json",
            status=sts.HTTP_200_OK
        ) 
          

@method_decorator(never_cache, name='dispatch')
class LeadGetView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    def post(self, request):
        user = request.user
        from datetime import timedelta
        from django.utils import timezone

        # 1 Check limit: 50 leads per 12 hours
        twelve_hours_ago = timezone.now() - timedelta(hours=12)
        pulled_count = Lead.objects.filter(
            assigned_to=user,
            assigned_at__gte=twelve_hours_ago
        ).count()

        if pulled_count >= 50:
            return Response({
                "already_assigned": False,
                "status": "Fail",
                "message": "You have finished your limit of 50 leads per 12 hours. Please try again later."
            }, status=status.HTTP_200_OK)

        # 2 Check if user already has assigned lead
        existing_lead = Lead.objects.filter(
            assigned_to=user,
            status="assigned",
            is_active=True
        ).first()

        if existing_lead:
            return Response({
                "already_assigned": True,
                 "status":"Fail",
                 "message":"You already have an active lead"
            }, status=status.HTTP_200_OK)

        # 3 Get new unassigned lead
        lead = Lead.objects.filter(
            status="unassigned",
            is_active=True
        ).first()

        if not lead:
            return Response(
                {
                    "already_assigned": False,
                    "status": "Fail",
                    "message": "No leads available at the moment"
                },
                status=status.HTTP_200_OK
            )


        # 4 Assign lead
        lead.status = "assigned"
        lead.assigned_to = user
        lead.assigned_at = timezone.now()
        lead.save()
        return Response({
            "already_assigned": False,
            "status":"success",
            "message": "Leads assigned successfully"
            
        }, status=status.HTTP_200_OK)
    


from datetime import datetime


@method_decorator(never_cache, name='dispatch')
class LeadCountView(GenericAPIView):
    permission_classes = [IsAuthenticated]


    def get(self, request):
        user = request.user
        role = getattr(getattr(user, "role", None), "name", "")
        filter_date = request.GET.get("date")
        from_date = request.GET.get("from")
        to_date = request.GET.get("to")

        # Role-aware scoping (match dashboard behavior)
        leads = Lead.objects.filter(is_active=True)
        if role in ["ADMIN", "SUPERVISOR"]:
            leads = leads.filter(assigned_to__asc_code=getattr(user, "asc_code", None))
        else:
            leads = leads.filter(assigned_to=user)
        leads = leads.only("id", "lead_phones", "status_tracking", "status")

        # Optimization: Pre-parse filter dates
        target_d = datetime.strptime(filter_date, "%Y-%m-%d").date() if filter_date else None
        range_start = datetime.strptime(from_date, "%Y-%m-%d").date() if from_date and to_date else None
        range_end = datetime.strptime(to_date, "%Y-%m-%d").date() if from_date and to_date else None

        total_calls = 0
        total_connects = 0
        total_non_connects = 0
        total_non_valid = 0
        total_followups = 0
        total_leads = 0
        total_prospects = 0
        total_sales = 0

        for lead in leads:
            tracking = lead.status_tracking or {}
            lead_had_activity = False
            
            # Action-based counting from tracking history
            for key, entries in tracking.items():
                if key in ["voicemail_count", "lead_status"]: continue # Use specific action keys
                
                # Normalize entries format
                if isinstance(entries, dict): entries = [entries]
                if not isinstance(entries, list): continue
                
                for entry in entries:
                    dt_s = entry.get("datetime") or entry.get("date")
                    if not dt_s: continue
                    
                    # Date matching
                    edt = parse_datetime(dt_s)
                    edate = edt.date() if edt else parse_date(dt_s)
                    if not edate: continue
                    
                    matches = False
                    if target_d and edate == target_d: matches = True
                    elif range_start and range_start <= edate <= range_end: matches = True
                    
                    if matches:
                        lead_had_activity = True
                        
                        # Categorize the action
                        if key in CONNECT_STATUSES:
                            total_connects += 1
                            total_calls += 1
                        elif key in NON_CONNECT_STATUSES or key == "voicemail":
                            total_non_connects += 1
                            total_calls += 1
                        
                        if key in INVALID_STATUSES:
                            total_non_valid += 1
                        
                        if key in ["followup", "callback"]:
                            total_followups += 1
                        
                        if key == "interested" or key == "prospect":
                            total_prospects += 1
                        if key == "converted" or key == "deal-won":
                            total_sales += 1

            # Fallback for Aggregate "No-Connect" attempts (recorded via lead_status transitions)
            # This handles cases where no individual phone status was updated but lead moved attempts
            if not lead_had_activity:
                ls_entries = tracking.get("lead_status", [])
                if isinstance(ls_entries, dict): ls_entries = [ls_entries]
                for entry in ls_entries:
                    dt_s = entry.get("datetime")
                    if not dt_s: continue
                    edt = parse_datetime(dt_s)
                    if not edt or not ( (target_d and edt.date() == target_d) or (range_start and range_start <= edt.date() <= range_end) ):
                        continue
                    
                    lead_had_activity = True
                    # If it was a save but didn't hit the specific keys above, count it as a call if it's an attempt bucket
                    st = entry.get("status")
                    if st in ["second-attempt", "third-attempt", "completed"]:
                        total_calls += 1
                        total_non_connects += 1
                    elif st in ["followup", "prospect", "deal-won"]:
                        # Usually covered by keys above, but just in case
                        pass 

            if lead_had_activity:
                total_leads += 1

        # Response construction
        return Response({
            "status": "success",
            "total_leads": total_leads,
            "total_calls": total_calls,
            "total_connects": total_connects,
            "total_non_connects": total_non_connects,
            "total_non_valid": total_non_valid,
            "total_followups": total_followups,
            "total_prospects": total_prospects,
            "total_sales": total_sales,
            "total_sale_value": 0,
        }, status=sts.HTTP_200_OK)




class LeadCreateView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            data = request.data
            user = request.user  # Logged-in user
            role = user.role.name if user.role else ""

            if role in ["ADMIN", "SUPERADMIN"]:
                lead_status = "unassigned"
                assigned_to = None
            else:
                existing_lead = Lead.objects.filter(
                        assigned_to=user,
                        status="assigned",
                        is_active=True
                    ).first()

                if existing_lead:
                    return Response({
                        "already_assigned": True,
                        "status":"Fail",
                        "message":"You already have an active lead"
                    }, status=status.HTTP_200_OK)
                
                lead_status = data.get("status", "assigned")
                assigned_to = user

            lead = Lead.objects.create(
                lead_name=data.get("lead_name"),
                lead_emails=data.get("lead_emails", []),
                lead_phones=data.get("lead_phones", []),
                lead_company=data.get("lead_company"),
                lead_region=data.get("lead_region"),
                lead_website=data.get("lead_website"),
                lead_designation=data.get("lead_designation"),
                lead_address=data.get("lead_address", {}),
                status=lead_status,
                remarks=data.get("remarks"),
                assigned_to=assigned_to,
                assigned_at=timezone.now() if assigned_to else None,
            )

            return Response(
                {
                    "status": "success",
                    "message": "Lead created successfully",
                    "lead_id": lead.id,
                    "assigned_to": user.asc_name
                },
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            return Response(
                {
                    "status": "error",
                    "message": str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )
