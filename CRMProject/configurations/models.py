from django.db import models
from django.utils import timezone
from Authentication.models import LoginUser


STATUS_CHOICES = [
        ("unassigned", "Unassigned"),
        ("assigned", "Assigned"),
        ("second-attempt", "Second Attempt"),
        ("third-attempt", "Third Attempt"),
        ("completed", "Completed"),
        ("followup", "Follow Up"),
        ("deal-won", "Deal Won"),
        ("sale-lost", "Sale Lost"),
        ("dnd", "Do Not Disturb"),
        ("prospect", "Prospect"),
        ("re-research", "Re-Research"),
    ]


class Lead(models.Model):
    lead_name = models.CharField( max_length=150)

    lead_emails = models.JSONField(blank=True,null=True,default=list)

    lead_phones = models.JSONField( blank=True, null=True, default=list)

    lead_company = models.CharField(max_length=150,blank=True, null=True)

    lead_region = models.CharField(max_length=100,blank=True, null=True)
    lead_website = models.URLField(max_length=255, blank=True, null=True)
    other_lead_info = models.JSONField(blank=True, null=True, default=dict)
    other_links = models.JSONField(blank=True, null=True, default=dict)
    lead_designation = models.CharField(max_length=150, blank=True, null=True)


    lead_address = models.JSONField( blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="unassigned"
    )
    status_tracking = models.JSONField(
        default=dict,
        blank=True
    )
    created_at = models.DateTimeField(default=timezone.now)
    status_updated_at = models.DateTimeField(auto_now=True)
    remarks = models.TextField(blank=True, null=True)
    duplicate_leads = models.JSONField(default=list, blank=True)
    assigned_to = models.ForeignKey(LoginUser,on_delete=models.SET_NULL,null=True,blank=True, related_name="assigned_leads", limit_choices_to={"role__name": "AGENT"})
    assigned_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)


    def __str__(self):
        return f"{self.lead_name} - {self.lead_company} - {self.lead_designation}"

