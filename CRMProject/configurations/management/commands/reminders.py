from django.core.management.base import BaseCommand
from configurations.cron import send_followup_alerts
from CRMProject.db_router import set_db_for_request

class Command(BaseCommand):
    help = "Sends email reminders for upcoming followups, callbacks and interested leads (15 mins before scheduled time)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--database',
            default='default',
            help='The database to run the reminders for (e.g., default, domestic, international)'
        )

    def handle(self, *args, **options):
        db_alias = options['database']
        self.stdout.write(f"Checking for pending reminders on database '{db_alias}'...")
        
        # Set the database context for the router
        set_db_for_request(db_alias)
        
        send_followup_alerts()
        self.stdout.write(self.style.SUCCESS(f"Reminder check completed for '{db_alias}'."))
