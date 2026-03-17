
from rest_framework import serializers
from configurations.models import Lead
from Authentication.models import LoginUser

class ASCDetailsSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = LoginUser
        fields = ['asc_code', 'asc_name', 'asc_location']
    
    def to_representation(self, instance):
        if instance:
            return f"{instance.asc_code} - {instance.asc_location}"
        return None

class LeadReportSerializer(serializers.ModelSerializer):
    lead_id = serializers.SerializerMethodField()
    email_contact = serializers.SerializerMethodField()
    asc_details = serializers.SerializerMethodField()
    assigned_to_email = serializers.CharField(source='assigned_to.email', read_only=True)
    
    class Meta:
        model = Lead
        fields = [
            'lead_id', 'email_contact', 'lead_name', 'lead_company',
            'asc_details', 'status', 'assigned_to_email'
        ]
    
    def get_lead_id(self, obj):
        return f"#{obj.id}"
    
    def get_email_contact(self, obj):
        email = obj.lead_emails[0] if obj.lead_emails else "No Email"
        phone = obj.lead_phones[0] if obj.lead_phones else "No Phone"
        return f"{email} | {phone}"
    
    def get_asc_details(self, obj):
        if obj.assigned_to:
            return f"{obj.assigned_to.asc_code} - {obj.assigned_to.asc_location}"
        return "Unassigned"