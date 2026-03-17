from django.shortcuts import render
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from Authentication.models import LoginUser
from django.db.models import Q, Min
from rest_framework.response import Response
from django.utils.timezone import now
from datetime import datetime, timedelta

from configurations.models import Lead ,STATUS_CHOICES

class LeadAnalyticsAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # -----------------------
        # 1. DATE FILTERS
        # -----------------------
        today = now().date()
        start_date = request.GET.get("start_date", today)
        end_date = request.GET.get("end_date", today)
        period = request.GET.get("period", "daily")

        start_date = datetime.strptime(str(start_date), "%Y-%m-%d").date()
        end_date = datetime.strptime(str(end_date), "%Y-%m-%d").date()

        # -----------------------
        # -----------------------
        # 2. UTILITIES
        # -----------------------
        def get_grouped_queryset(qs):
            # Representative leads with company
            with_company_reps = (
                qs.exclude(Q(lead_company__isnull=True) | Q(lead_company=""))
                .values('lead_company', 'status', 'assigned_to')
                .annotate(min_id=Min('id'))
                .values_list('min_id', flat=True)
            )
            # Leads without company
            without_company_ids = (
                qs.filter(Q(lead_company__isnull=True) | Q(lead_company=""))
                .values_list('id', flat=True)
            )
            return qs.filter(id__in=list(with_company_reps) + list(without_company_ids))

        # -----------------------
        # 3. BASE QUERYSETS
        # -----------------------
        
        # Acquisition: Leads created in this period (New leads added)
        creation_qs = Lead.objects.filter(
            created_at__date__range=[start_date, end_date],
            is_active=True
        )
        
        # Activity: Leads acted upon in this period (Status changes, follow-ups, etc.)
        activity_qs = Lead.objects.filter(
            status_updated_at__date__range=[start_date, end_date],
            is_active=True
        )

        # -----------------------
        # 4. SUMMARY CALCULATIONS
        # -----------------------
        
        # Total Newly Acquired Leads (Grouped by Company)
        total_leads_in_period = get_grouped_queryset(creation_qs).count()

        # -----------------------
        # 5. ROLE-BASED FILTERING (Based on Activity)
        # -----------------------
        role = user.role.name if user.role else None

        if role == "SUPERADMIN":
            active_filtered_leads = activity_qs
        elif role in ["ADMIN", "SUPERVISOR"]:
            active_filtered_leads = activity_qs.filter(assigned_to__asc_code=user.asc_code)
        elif role == "AGENT":
            active_filtered_leads = activity_qs.filter(assigned_to=user)
        else:
            active_filtered_leads = activity_qs.none()


        grouped_active_leads = get_grouped_queryset(active_filtered_leads)

        total_assigned = grouped_active_leads.exclude(status='unassigned').count()
        deal_won = grouped_active_leads.filter(status="deal-won").count()
        follow_up = grouped_active_leads.filter(status="followup").count()
        prospect = grouped_active_leads.filter(status="prospect").count()

        # -----------------------
        # 5. BUCKET COUNTS
        # -----------------------
        bucket_counts = {
            status: grouped_active_leads.filter(status=status).count()
            for status, _ in STATUS_CHOICES if status != 'unassigned'
        }

        # -----------------------
        # 6. STATUS TRACKING COUNTS
        # -----------------------
        status_tracking_summary = {
            "prospect": 0,
            "voicemail": 0,
            "lead_status": 0,
            "second_attempt": 0,
            "voicemail_count": 0
        }

        # Lifetime total (Grouped by Company)
        total_leads_lifetime = get_grouped_queryset(Lead.objects.filter(is_active=True)).count()

        for lead in active_filtered_leads:
            tracking = lead.status_tracking or {}

            # Count prospect entries
            status_tracking_summary["prospect"] += len(tracking.get("prospect", []))

            # Count voicemail entries
            status_tracking_summary["voicemail"] += len(tracking.get("voicemail", []))

            # Count lead_status entries
            status_tracking_summary["lead_status"] += len(tracking.get("lead_status", []))

            # Count second-attempt entries
            if tracking.get("second-attempt"):
                status_tracking_summary["second_attempt"] += 1

            # Sum voicemail_count
            status_tracking_summary["voicemail_count"] += tracking.get("voicemail_count", 0)

        # -----------------------
        # 7. TREND DATA
        # -----------------------
        trends = []

        # -----------------------
        # 7. TREND DATA (Specific Requirements)
        # -----------------------
        trends = []

        if period == "daily":
            days = (end_date - start_date).days + 1
            for i in range(days):
                day = start_date + timedelta(days=i)
                trends.append({
                    "date": day.strftime("%Y-%m-%d"),
                    "count": get_grouped_queryset(active_filtered_leads.filter(status_updated_at__date=day)).count()
                })

        elif period == "weekly":
            # Show "1st Week", "2nd Week", etc. in 7-day cycles starting from the 1st
            month = start_date.month
            year = start_date.year
            
            # Start of the month
            curr_start = datetime(year, month, 1).date()
            # End of the month
            import calendar
            _, last_day_num = calendar.monthrange(year, month)
            month_end = datetime(year, month, last_day_num).date()
            
            week_num = 1
            while curr_start <= month_end:
                curr_end = curr_start + timedelta(days=6)
                if curr_end > month_end:
                    curr_end = month_end
                
                count = Lead.objects.filter(
                    status_updated_at__date__range=[curr_start, curr_end],
                    is_active=True
                )
                
                # Apply same role filtering
                if role == "ADMIN" or role == "SUPERVISOR":
                    count = count.filter(assigned_to__asc_code=user.asc_code)
                elif role == "AGENT":
                    count = count.filter(assigned_to=user)
                
                def get_ordinal(n):
                    if 11 <= (n % 100) <= 13: return "th"
                    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")

                trends.append({
                    "date": f"{week_num}{get_ordinal(week_num)} Week",
                    "count": get_grouped_queryset(count).count()
                })
                
                curr_start = curr_start + timedelta(days=7)
                week_num += 1

        elif period == "yearly":
            # Show years from 2025 to current year
            this_year = now().year
            for y in range(2025, this_year + 1):
                count = Lead.objects.filter(
                    status_updated_at__year=y,
                    is_active=True
                )
                
                if role == "ADMIN" or role == "SUPERVISOR":
                    count = count.filter(assigned_to__asc_code=user.asc_code)
                elif role == "AGENT":
                    count = count.filter(assigned_to=user)

                trends.append({
                    "date": str(y),
                    "count": get_grouped_queryset(count).count()
                })

        # -----------------------
        # 8. RESPONSE
        # -----------------------
        return Response({
            "status": "success",
            "message": "Data fetched successfully",
            "data": {
                "filters": {
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                    "period": period
                },
                "summary": {
                    "total_leads": total_leads_in_period,
                    "total_leads_lifetime": total_leads_lifetime,
                    "total_assigned": total_assigned,
                    "deal_won": deal_won,
                    "follow_up": follow_up,
                    "prospect": prospect
                },
                "bucket_counts": bucket_counts,
                "status_tracking_summary": status_tracking_summary,
                "trends": trends
            }
        })
