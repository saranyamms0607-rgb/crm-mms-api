"""
Cron entrypoints for django-crontab.

NOTE: Settings `CRONJOBS` currently references `crmapp.cron.send_followup_alerts`.
The actual implementation lives in `configurations.cron.send_followup_alerts`.
This wrapper keeps the settings stable and ensures the job runs.
"""

from configurations.cron import send_followup_alerts as _send_followup_alerts


def send_followup_alerts():
    return _send_followup_alerts()

