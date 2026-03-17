# views.py
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Count, Q
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from configurations.models import Lead ,STATUS_CHOICES
from Authentication.models import LoginUser
from django.utils import timezone
from datetime import timedelta, datetime
import csv
import json
from django.http import HttpResponse
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from .serializers import LeadReportSerializer

def apply_report_filters(queryset, request, include_unassigned=False, date_field='status_updated_at'):
    """
    Common helper to apply filters to Lead queryset
    """
    if not include_unassigned:
        queryset = queryset.exclude(status='unassigned')

    # Parameters
    status_filter = request.query_params.get('status') or request.query_params.get('disposition')
    asc_code = request.query_params.get('asc_code')
    asc_name = request.query_params.get('asc_name')
    location = request.query_params.get('location')
    date_from = request.query_params.get('start_date') or request.query_params.get('date_from')
    date_to = request.query_params.get('end_date') or request.query_params.get('date_to')

    if status_filter:
        queryset = queryset.filter(status__in=status_filter.split(','))
    
    if asc_code:
        queryset = queryset.filter(assigned_to__asc_code__in=asc_code.split(','))

    if asc_name:
        queryset = queryset.filter(assigned_to__asc_name__in=asc_name.split(','))

    if location:
        queryset = queryset.filter(assigned_to__asc_location__in=location.split(','))
        
    if date_from and date_to:
        filter_key = f"{date_field}__date__range"
        queryset = queryset.filter(**{filter_key: [date_from, date_to]})
    elif date_from:
        filter_key = f"{date_field}__date"
        queryset = queryset.filter(**{filter_key: date_from})
    elif date_to:
        filter_key = f"{date_field}__date"
        queryset = queryset.filter(**{filter_key: date_to})

    return queryset

def get_grouped_queryset(qs):
    # Helper for company-based grouping consistency
    from django.db.models import Q, Min
    with_company_reps = (
        qs.exclude(Q(lead_company__isnull=True) | Q(lead_company=""))
        .values('lead_company', 'status', 'assigned_to')
        .annotate(min_id=Min('id'))
        .values_list('min_id', flat=True)
    )
    without_company_ids = (
        qs.filter(Q(lead_company__isnull=True) | Q(lead_company=""))
        .values_list('id', flat=True)
    )
    return qs.filter(id__in=list(with_company_reps) + list(without_company_ids))

def get_filtered_agents(request):
    """
    Common helper to filter agents (LoginUser with role=AGENT)
    """
    agents = LoginUser.objects.filter(role__name='AGENT', is_active=True)
    
    asc_code = request.query_params.get('asc_code')
    asc_name = request.query_params.get('asc_name')
    location = request.query_params.get('location')
    
    if asc_code:
        agents = agents.filter(asc_code__in=asc_code.split(','))
    if asc_name:
        agents = agents.filter(asc_name__in=asc_name.split(','))
    if location:
        agents = agents.filter(asc_location__in=location.split(','))
        
    return agents

def format_lead_data(data_list):
    """ Helper to extract values from lead_emails/lead_phones JSON lists """
    if not data_list or not isinstance(data_list, list):
        return ""
    item = data_list[0]
    if isinstance(item, dict):
        return item.get('phone') or item.get('email') or item.get('value', str(item))
    return str(item)

class StandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

class ReportsOverviewAPIView(GenericAPIView):
    """
    API for Reports Overview tab
    """
    def get(self, request):
        # Base queryset for everything
        base_qs = Lead.objects.filter(is_active=True)
        
        # 1. NEW LEADS Acquired in the period (Based on created_at)
        new_leads_qs = apply_report_filters(base_qs, request, include_unassigned=True, date_field='created_at')
        grouped_new_leads = get_grouped_queryset(new_leads_qs)
        
        total_leads_added = grouped_new_leads.count()
        unassigned_leads_added = grouped_new_leads.filter(status='unassigned').count()
        
        # 2. STATUS ACTIONS handled in the period (Based on status_updated_at)
        # We use a separate filtered queryset for buckets
        activity_qs = apply_report_filters(base_qs, request, include_unassigned=True, date_field='status_updated_at')
        grouped_activity_qs = get_grouped_queryset(activity_qs)
        
        # Filtered activity (excluding unassigned)
        handled_qs = grouped_activity_qs.exclude(status='unassigned')
        
        response_data = {
            "summary": {
                "total_leads": total_leads_added, # Total newly added in period
                "unassigned": unassigned_leads_added, # Unassigned pool from new leads
                "total_assigned": handled_qs.count(), # Everything acted upon today
                "currently_assigned": handled_qs.filter(status='assigned').count(),
                "assigned": handled_qs.filter(status='assigned').count(),
                "second_attempt": handled_qs.filter(status='second-attempt').count(),
                "third_attempt": handled_qs.filter(status='third-attempt').count(),
                "completed": handled_qs.filter(status='completed').count(),
                "followup": handled_qs.filter(status='followup').count(),
                "deal_won": handled_qs.filter(status='deal-won').count(),
                "sale_lost": handled_qs.filter(status='sale-lost').count(),
                "invalid": handled_qs.filter(status='invalid').count(),
                "dnd": handled_qs.filter(status='dnd').count(),
                "prospect": handled_qs.filter(status='prospect').count(),
                "re_research": handled_qs.filter(status='re-research').count(),
            }
        }
        return Response(response_data, status=status.HTTP_200_OK)

class LeadReportsAPIView(ListAPIView):
    """
    API for Lead Reports tab with pagination
    """
    serializer_class = LeadReportSerializer
    pagination_class = StandardPagination
    
    def get_queryset(self):
        queryset = Lead.objects.filter(is_active=True).select_related('assigned_to')
        queryset = apply_report_filters(queryset, self.request)
        return queryset.order_by('-status_updated_at')
    
    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response.data['export_url'] = request.build_absolute_uri(
            f"{request.path}export/?{request.GET.urlencode()}"
        )
        
        agents = LoginUser.objects.filter(role__name='AGENT', is_active=True)
        response.data['filters'] = {
            'status_choices': [choice[0] for choice in STATUS_CHOICES if choice[0] != 'unassigned'],
            'asc_codes': agents.values_list('asc_code', flat=True).distinct(),
            'asc_names': agents.values_list('asc_name', flat=True).distinct(),
            'locations': agents.values_list('asc_location', flat=True).distinct()
        }
        return response

class AgentPerformanceAPIView(GenericAPIView):
    """
    API for Agent Performance tab with pagination
    """
    pagination_class = StandardPagination

    def get(self, request):
        agents = get_filtered_agents(request)
        
        # Apply pagination to the agents list
        page = self.paginate_queryset(agents)
        agent_performance = []
        
        # If pagination is active, use the page; otherwise use the full list
        target_list = page if page is not None else agents
        
        for agent in target_list:
            leads_qs = Lead.objects.filter(assigned_to=agent, is_active=True)
            leads_qs = apply_report_filters(leads_qs, request)
            
            total_assigned = leads_qs.count()
            followup = leads_qs.filter(status='followup').count()
            deal_won = leads_qs.filter(status='deal-won').count()
            sale_lost = leads_qs.filter(status='sale-lost').count()
            re_research = leads_qs.filter(status='re-research').count()
            
            # Use total_assigned for conversion rate if completed is removed
            conversion_rate = (deal_won / total_assigned * 100) if total_assigned > 0 else 0
            
            agent_performance.append({
                "agent_id": agent.id,
                "agent_name": agent.email.split('@')[0].title().replace('.', ' '),
                "asc_code": agent.asc_code,
                "asc_location": agent.asc_location,
                "assigned": total_assigned,
                "followup": followup,
                "deal_won": deal_won,
                "sale_lost": sale_lost,
                "re_research": re_research,
                "conversion_rate": f"{conversion_rate:.1f}%",
                "performance_score": self._calculate_performance_score(total_assigned, deal_won, sale_lost)
            })
        
        agent_performance.sort(key=lambda x: float(x['conversion_rate'].replace('%', '')), reverse=True)
        
        if page is not None:
            return self.get_paginated_response(agent_performance)

        response_data = {
            "agents": agent_performance,
            "summary": {
                "total_agents": len(agent_performance),
                "avg_conversion_rate": f"{sum(float(a['conversion_rate'].replace('%', '')) for a in agent_performance) / len(agent_performance) if agent_performance else 0:.1f}%",
                "top_performer": agent_performance[0]['agent_name'] if agent_performance else "N/A"
            }
        }
        return Response(response_data, status=status.HTTP_200_OK)
    
    def _calculate_performance_score(self, assigned, deal_won, deal_lost):
        if assigned == 0: return 1
        # Simple score based on win rate
        win_rate = deal_won / assigned * 100 if assigned > 0 else 0
        if win_rate >= 50: return 5
        elif win_rate >= 30: return 4
        elif win_rate >= 20: return 3
        elif win_rate >= 10: return 2
        return 1

class DispositionWiseAPIView(GenericAPIView):
    """
    API for Disposition Wise tab
    """
    def get(self, request):
        leads_qs = Lead.objects.filter(is_active=True)
        leads_qs = apply_report_filters(leads_qs, request)
        
        total_leads = leads_qs.count()
        disposition_data = []
        status_display_map = {
            "deal-won": "Deal Won", "sale-lost": "Sale Lost", "followup": "Call Back / Follow Up",
            "dnd": "DND", "prospect": "Prospect", "unassigned": "Unassigned",
            "assigned": "Assigned", "completed": "Completed", "re-research": "Re-Research"
        }
        
        for status_code, status_display in status_display_map.items():
            count = leads_qs.filter(status=status_code).count()
            if count > 0:
                percentage = (count / total_leads * 100) if total_leads > 0 else 0
                disposition_data.append({
                    "disposition": status_display, "count": count,
                    "percentage": f"{percentage:.1f}%",
                    "color": self._get_status_color(status_code),
                    "icon": self._get_status_icon(status_code)
                })
        
        disposition_data.sort(key=lambda x: x['count'], reverse=True)
        return Response({"dispositions": disposition_data, "total_leads": total_leads}, status=status.HTTP_200_OK)

    def _get_status_color(self, status_code):
        return {"deal-won": "#4CAF50", "sale-lost": "#F44336", "followup": "#FFC107", "dnd": "#9E9E9E", "prospect": "#2196F3", "unassigned": "#607D8B", "assigned": "#FF9800", "completed": "#3F51B5", "re-research": "#475569"}.get(status_code, "#9E9E9E")
    
    def _get_status_icon(self, status_code):
        return {"deal-won": "✅", "deal-lost": "❌", "followup": "📞", "dnd": "🚫", "prospect": "🌟", "unassigned": "⏳", "assigned": "👤", "completed": "🏁"}.get(status_code, "●")

class ASCWiseDetailedAPIView(GenericAPIView):
    """
    API for ASC Wise tab - Grouped by ASC Code and Location
    """
    pagination_class = StandardPagination

    def get(self, request):
        agents = get_filtered_agents(request)
        
        # Get unique ASC pairs (Code + Location) from filtered agents
        unique_ascs = agents.values('asc_code', 'asc_location').distinct().order_by('asc_code')
        
        # Apply pagination
        page = self.paginate_queryset(unique_ascs)
        asc_data = []
        
        target_list = page if page is not None else unique_ascs
        
        for asc_info in target_list:
            code = asc_info['asc_code']
            loc = asc_info['asc_location']
            
            # Find all agents belonging to this ASC group
            group_agents = LoginUser.objects.filter(
                asc_code=code, 
                asc_location=loc, 
                role__name='AGENT', 
                is_active=True
            )
            
            # Leads assigned to any agent in this group
            leads_qs = Lead.objects.filter(assigned_to__in=group_agents, is_active=True)
            leads_qs = apply_report_filters(leads_qs, request)
            
            # Calculate requested metrics
            total_assigned = leads_qs.count()
            followup = leads_qs.filter(status='followup').count()
            deal_won = leads_qs.filter(status='deal-won').count()
            deal_lost = leads_qs.filter(status='deal-lost').count()
            
            # Use first agent's ASC name as representative
            rep_name = group_agents.first().asc_name if group_agents.exists() else "N/A"
            
            asc_data.append({
                "asc_code": code,
                "asc_name": rep_name,
                "asc_location": loc,
                "total_assigned": total_assigned,
                "followup": followup,
                "deal_won": deal_won,
                "deal_lost": deal_lost,
            })
        
        if page is not None:
            return self.get_paginated_response(asc_data)
            
        return Response({"ascs": asc_data}, status=status.HTTP_200_OK)


class ExportReportsAPIView(APIView):
    """
    Enhanced export API for different report types
    """
    
    def get(self, request):
        report_type = request.query_params.get('type', 'leads')
        format_type = request.query_params.get('report_format') or request.query_params.get('format', 'csv')
        
        if report_type in ['leads', 'lead-reports', 'prospect-wise', 'followup-wise']:
            return self._export_leads_report(request, format_type)
        elif report_type in ['agents', 'agent-performance']:
            return self._export_agents_report(request, format_type)
        elif report_type in ['dispositions', 'disposition-wise']:
            return self._export_dispositions_report(request, format_type)
        elif report_type in ['ascs', 'asc-wise']:
            return self._export_ascs_report(request, format_type)
        
        return Response({"error": f"Invalid report type: {report_type}"}, status=400)
    
    def _export_leads_report(self, request, format_type):
        try:
            # Get filtered leads
            leads = Lead.objects.filter(is_active=True).select_related('assigned_to')
            
            # Apply filters
            filters = self._apply_lead_filters(leads, request)
            
            if format_type == 'csv':
                response = HttpResponse(content_type='text/csv')
                filename = f"leads_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                
                writer = csv.writer(response)
                writer.writerow([
                    'LEAD ID', 'NAME', 'EMAIL', 'PHONE', 'COMPANY',
                    'REGION', 'STATUS', 'ASC CODE', 'ASC LOCATION',
                    'ASSIGNED AGENT', 'LAST UPDATED', 'REMARKS'
                ])
                
                for lead in filters:
                    email = format_lead_data(lead.lead_emails)
                    phone = format_lead_data(lead.lead_phones)
                    asc_code = lead.assigned_to.asc_code if lead.assigned_to else ""
                    asc_location = lead.assigned_to.asc_location if lead.assigned_to else ""
                    agent_email = lead.assigned_to.email if lead.assigned_to else ""
                    
                    writer.writerow([
                        f"#{lead.id}",
                        lead.lead_name,
                        email,
                        phone,
                        lead.lead_company or "",
                        lead.lead_region or "",
                        lead.get_status_display(),
                        asc_code,
                        asc_location,
                        agent_email,
                        lead.status_updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                        lead.remarks or ""
                    ])
                
                return response
            else:
                # JSON export
                serializer = LeadReportSerializer(filters, many=True)
                response_data = {
                    "export_type": "leads",
                    "export_date": timezone.now().isoformat(),
                    "total_records": filters.count(),
                    "data": serializer.data
                }
                
                response = HttpResponse(
                    json.dumps(response_data, indent=2),
                    content_type='application/json'
                )
                filename = f"leads_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                return response
        except Exception as e:
            return Response({"error": str(e)}, status=500)
    
    def _apply_lead_filters(self, queryset, request):
        return apply_report_filters(queryset, request)

    def _export_agents_report(self, request, format_type):
        agents = get_filtered_agents(request)
        data = []
        for agent in agents:
            leads_qs = Lead.objects.filter(assigned_to=agent, is_active=True)
            leads_qs = apply_report_filters(leads_qs, request)
            total = leads_qs.count()
            followup = leads_qs.filter(status='followup').count()
            deal_won = leads_qs.filter(status='deal-won').count()
            deal_lost = leads_qs.filter(status='deal-lost').count()
            conversion = (deal_won / total * 100) if total > 0 else 0
            data.append([agent.asc_name, agent.asc_code, agent.asc_location, total, followup, deal_won, deal_lost, f"{conversion:.1f}%"])

        if format_type == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="agent_performance_{datetime.now().strftime("%Y%m%d")}.csv"'
            writer = csv.writer(response)
            writer.writerow(['Agent Name', 'ASC Code', 'Location', 'Assigned', 'Followup', 'Deal Won', 'Deal Lost', 'Conversion Rate'])
            writer.writerows(data)
            return response
        return Response({"agents": data})

    def _export_dispositions_report(self, request, format_type):
        leads_qs = Lead.objects.filter(is_active=True)
        leads_qs = apply_report_filters(leads_qs, request)
        total_leads = leads_qs.count()
        status_map = {"deal-won": "Interested", "deal-lost": "Not Interested", "followup": "Call Back", "dnd": "Wrong Number", "prospect": "Prospect", "unassigned": "Unassigned", "assigned": "Assigned", "completed": "Completed"}
        
        data = []
        for status_code, display in status_map.items():
            count = leads_qs.filter(status=status_code).count()
            if count > 0:
                percentage = (count / total_leads * 100) if total_leads > 0 else 0
                data.append([display, count, f"{percentage:.1f}%"])

        if format_type == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="disposition_report_{datetime.now().strftime("%Y%m%d")}.csv"'
            writer = csv.writer(response)
            writer.writerow(['Disposition', 'Count', 'Percentage'])
            writer.writerows(data)
            return response
        return Response({"dispositions": data})

    def _export_ascs_report(self, request, format_type):
        ascs = get_filtered_agents(request)
        unique_ascs = ascs.values('asc_code', 'asc_location').distinct().order_by('asc_code')
        data = []
        for asc_info in unique_ascs:
            code = asc_info['asc_code']
            loc = asc_info['asc_location']
            group_agents = LoginUser.objects.filter(asc_code=code, asc_location=loc, role__name='AGENT', is_active=True)
            leads_qs = Lead.objects.filter(assigned_to__in=group_agents, is_active=True)
            leads_qs = apply_report_filters(leads_qs, request)
            
            total = leads_qs.count()
            followup = leads_qs.filter(status='followup').count()
            won = leads_qs.filter(status='deal-won').count()
            lost = leads_qs.filter(status='deal-lost').count()
            name = group_agents.first().asc_name if group_agents.exists() else "N/A"
            
            data.append([code, name, loc, total, followup, won, lost])

        if format_type == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="asc_report_{datetime.now().strftime("%Y%m%d")}.csv"'
            writer = csv.writer(response)
            writer.writerow(['ASC Code', 'ASC Name', 'Location', 'Total Assigned', 'Followup', 'Deal Won', 'Deal Lost'])
            writer.writerows(data)
            return response
        return Response({"ascs": data})

class PrintReportAPIView(APIView):
    """
    API to return a printer-friendly HTML version of the report
    """
    def get(self, request):
        report_type = request.query_params.get('type', 'leads')
        
        # Standard Lead Report Printing logic
        if report_type in ['leads', 'lead-reports', 'prospect-wise', 'followup-wise']:
            leads = Lead.objects.filter(is_active=True).select_related('assigned_to')
            leads = apply_report_filters(leads, request)
            
            # Additional pre-filtering for specific status tabs
            if report_type == 'prospect-wise':
                leads = leads.filter(status='prospect')
            elif report_type == 'followup-wise':
                leads = leads.filter(status='followup')

            headers = ["ID", "Name", "Email", "Phone", "Status", "ASC"]
            rows = []
            for lead in leads:
                rows.append([
                    f"#{lead.id}",
                    lead.lead_name,
                    format_lead_data(lead.lead_emails),
                    format_lead_data(lead.lead_phones),
                    lead.get_status_display(),
                    f"{lead.assigned_to.asc_code} ({lead.assigned_to.asc_location})" if lead.assigned_to else "N/A"
                ])
            title = report_type.replace('-', ' ').title()
            return self._render_print_table(f"{title} Report", headers, rows)
        
        elif report_type in ['agents', 'agent-performance']:
            agents = get_filtered_agents(request)
            headers = ["Agent Name", "ASC Code", "Assigned", "Followup", "Won", "Lost", "Rate"]
            rows = []
            for agent in agents:
                leads_qs = Lead.objects.filter(assigned_to=agent, is_active=True)
                leads_qs = apply_report_filters(leads_qs, request)
                total = leads_qs.count()
                followup = leads_qs.filter(status='followup').count()
                won = leads_qs.filter(status='deal-won').count()
                lost = leads_qs.filter(status='deal-lost').count()
                rate = f"{(won/total*100) if total > 0 else 0:.1f}%"
                rows.append([agent.email.split('@')[0], agent.asc_code, total, followup, won, lost, rate])
            return self._render_print_table("Agent Performance Report", headers, rows)
        
        elif report_type in ['ascs', 'asc-wise']:
            ascs = get_filtered_agents(request)
            unique_ascs = ascs.values('asc_code', 'asc_location').distinct().order_by('asc_code')
            headers = ["ASC Code", "ASC Name", "Location", "Total Assigned", "Followup", "Deal Won", "Deal Lost"]
            rows = []
            for asc_info in unique_ascs:
                code = asc_info['asc_code']
                loc = asc_info['asc_location']
                group_agents = LoginUser.objects.filter(asc_code=code, asc_location=loc, role__name='AGENT', is_active=True)
                leads_qs = Lead.objects.filter(assigned_to__in=group_agents, is_active=True)
                leads_qs = apply_report_filters(leads_qs, request)
                
                total = leads_qs.count()
                followup = leads_qs.filter(status='followup').count()
                won = leads_qs.filter(status='deal-won').count()
                lost = leads_qs.filter(status='deal-lost').count()
                name = group_agents.first().asc_name if group_agents.exists() else "N/A"
                
                rows.append([code, name, loc, total, followup, won, lost])
            return self._render_print_table("ASC Wise Detailed Report", headers, rows)
        
        elif report_type in ['dispositions', 'disposition-wise']:
            leads_qs = Lead.objects.filter(is_active=True)
            leads_qs = apply_report_filters(leads_qs, request)
            total_leads = leads_qs.count()
            status_map = {
                "deal-won": "Interested", "deal-lost": "Not Interested", "followup": "Call Back", 
                "dnd": "Wrong Number", "prospect": "Prospect", "unassigned": "Unassigned", 
                "assigned": "Assigned", "completed": "Completed"
            }
            headers = ["Disposition", "Count", "Percentage"]
            rows = []
            for status_code, display in status_map.items():
                count = leads_qs.filter(status=status_code).count()
                if count > 0:
                    percentage = (count / total_leads * 100) if total_leads > 0 else 0
                    rows.append([display, count, f"{percentage:.1f}%"])
            
            # Sort by count descending
            rows.sort(key=lambda x: x[1], reverse=True)
            return self._render_print_table("Disposition Wise Report", headers, rows)
        
        return Response({"error": "Print not implemented for this tab"}, status=400)

    def _render_print_table(self, title, headers, rows):
        html = f"""
        <html>
        <head>
            <title>{title}</title>
            <style>
                body {{ font-family: sans-serif; padding: 30px; line-height: 1.6; color: #333; }}
                h1 {{ color: #7D2A1F; border-bottom: 3px solid #7D2A1F; padding-bottom: 10px; }}
                .meta {{ margin-bottom: 20px; font-size: 0.9em; color: #666; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
                th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #f8f8f8; font-weight: bold; text-transform: uppercase; font-size: 0.85em; letter-spacing: 1px; }}
                tr:nth-child(even) {{ background-color: #fafafa; }}
                @media print {{ 
                    .no-print {{ display: none; }}
                    body {{ 
                        padding: 1.5cm; 
                        margin: 0;
                        background: white;
                    }}
                    table {{ box-shadow: none; }}
                    @page {{ 
                        margin: 0; 
                        size: auto;
                    }}
                }}
            </style>
        </head>
        <body onload="window.print()">
            <div class="no-print" style="margin-bottom: 20px;">
                <button onclick="window.print()" style="padding: 10px 20px; background: #7D2A1F; color: white; border: none; border-radius: 5px; cursor: pointer;">
                    🖨️ Print Document
                </button>
            </div>
            <h1>{title}</h1>
            <div class="meta">
                Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br>
                Total Records: {len(rows)}
            </div>
            <table>
                <thead>
                    <tr>
                        {"".join(f"<th>{h}</th>" for h in headers)}
                    </tr>
                </thead>
                <tbody>
                    {"".join(f"<tr>{''.join(f'<td>{cell}</td>' for cell in row)}</tr>" for row in rows)}
                </tbody>
            </table>
        </body>
        </html>
        """
        return HttpResponse(html)
