from django.contrib import admin
from .models import Lead

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    search_fields = ('lead_name', 'lead_emails', 'lead_company', 'status')
    list_filter = ('status', 'assigned_to')
    list_display = ('lead_name', 'lead_company', 'status', 'assigned_to')