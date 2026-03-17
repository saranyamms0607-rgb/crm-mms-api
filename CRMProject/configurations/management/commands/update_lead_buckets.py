from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from configurations.models import Lead
from crmapp.views import VOICEMAIL_LIKE_STATUSES

class Command(BaseCommand):
    help = "Auto-update lead buckets based on phone status and last contact"

    def handle(self, *args, **kwargs):
        now = timezone.now()
        leads = Lead.objects.filter(is_active=True, status__in=["assigned", "second-attempt", "third-attempt"])

        for lead in leads:
            if not lead.status_updated_at:
                continue

            elapsed = now - lead.status_updated_at
            phones = lead.lead_phones or []

            statuses = [p.get("status") for p in phones]

            # Priority-based rules
            if "dnd" in statuses:
                lead.status = "dnd"
            elif "not-interested" in statuses:
                lead.status = "sale-lost"
            elif "interested" in statuses or "prospect" in statuses:
                lead.status = "prospect"
            elif "callback" in statuses or "followup" in statuses:
                lead.status = "followup"
            elif all(s in VOICEMAIL_LIKE_STATUSES for s in statuses):
                # Increment attempts based on elapsed time (24h rule)
                tracking = lead.status_tracking or {}
                voicemail_count = tracking.get("voicemail_count", 0)

                # Fallback for missing tracking
                if voicemail_count == 0:
                    if lead.status == "second-attempt": voicemail_count = 1
                    elif lead.status == "third-attempt": voicemail_count = 2

                if elapsed >= timedelta(hours=24):
                    if voicemail_count == 0:
                        lead.status = "second-attempt"
                        tracking["voicemail_count"] = 1
                    elif voicemail_count == 1:
                        lead.status = "third-attempt"
                        tracking["voicemail_count"] = 2
                    elif voicemail_count >= 2:
                        lead.status = "completed"
                        tracking["voicemail_count"] = 3
                    
                    lead.status_tracking = tracking
                    lead.status_updated_at = now

            lead.save()
            self.stdout.write(f"Lead {lead.id} updated to {lead.status}")
