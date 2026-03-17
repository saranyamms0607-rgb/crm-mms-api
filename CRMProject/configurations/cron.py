from django.utils import timezone
from django.core.mail import send_mail
from datetime import timedelta
from .models import Lead
from django.conf import settings
from Authentication.models import LoginUser
import os

def send_followup_alerts():
    now = timezone.now()

    leads = Lead.objects.filter(is_active=True)

    for lead in leads:
        phones = lead.lead_phones or []
        changes_made = False

        # Debug print
        if any(p.get("status") in ["callback", "interested", "followup"] for p in phones):
             print(f"Checking reminders for lead: {lead.id} ({lead.lead_name})")


        for phone in phones:
            followup = phone.get("followup_date")
            status = phone.get("status")

            # skip invalid
            if not followup:
                continue

            # only alert for these statuses
            if status not in ["callback", "interested", "followup"]:
                continue

            from django.utils.dateparse import parse_datetime

            try:
                followup_dt = parse_datetime(followup)
                if not followup_dt:
                    continue
                if not timezone.is_aware(followup_dt):
                    followup_dt = timezone.make_aware(followup_dt)
            except Exception:
                continue

            # compute how many days overdue (negative if in future)
            delta = now - followup_dt
            days_over = delta.days

            # initialize tracking fields
            reminder_count = phone.get("reminder_count", 0)
            # determine which reminder should fire next
            to_send = False
            recipients = []
            subject = None
            message = None

            # First reminder: 15 minutes before or missed (if not sent yet and less than 1 day overdue)
            if days_over < 1 and reminder_count == 0:
                threshold = followup_dt - timedelta(minutes=15)
                is_time = now >= threshold
                print(f"  Phone: {phone.get('phone')}, status: {status}, followup: {followup_dt}, now: {now}, threshold: {threshold}, time_match: {is_time}")
                if is_time:
                    to_send = True

                reminder_count = 1
                subject = "Follow-up Reminder (15 mins)"
                # only agent
                try:
                    if getattr(lead, "assigned_to", None) and getattr(lead.assigned_to, "email", None):
                        recipients.append(lead.assigned_to.email)
                except Exception:
                    pass

            # Second reminder: 1 day overdue and first reminder already sent
            elif days_over >= 1 and reminder_count == 1:
                to_send = True
                reminder_count = 2
                subject = "Follow-up Overdue (1 day)"
                # agent + supervisors
                try:
                    if getattr(lead, "assigned_to", None) and getattr(lead.assigned_to, "email", None):
                        recipients.append(lead.assigned_to.email)
                except Exception:
                    pass
                try:
                    asc_code = getattr(lead.assigned_to, "asc_code", None) if getattr(lead, "assigned_to", None) else None
                    if asc_code:
                        sup_qs = LoginUser.objects.filter(asc_code=asc_code, role__name__iexact="SUPERVISOR", is_active=True)
                        recipients.extend([u.email for u in sup_qs if u.email])
                except Exception:
                    pass

            # Third reminder: 2+ days overdue and second reminder sent
            elif days_over >= 2 and reminder_count == 2:
                to_send = True
                reminder_count = 3
                subject = "Follow-up Overdue (2 days)"
                # agent + supervisors + managers
                try:
                    if getattr(lead, "assigned_to", None) and getattr(lead.assigned_to, "email", None):
                        recipients.append(lead.assigned_to.email)
                except Exception:
                    pass
                try:
                    asc_code = getattr(lead.assigned_to, "asc_code", None) if getattr(lead, "assigned_to", None) else None
                    if asc_code:
                        sup_qs = LoginUser.objects.filter(asc_code=asc_code, role__name__iexact="SUPERVISOR", is_active=True)
                        recipients.extend([u.email for u in sup_qs if u.email])
                        man_qs = LoginUser.objects.filter(asc_code=asc_code, role__name__iexact="MANAGER", is_active=True)
                        recipients.extend([u.email for u in man_qs if u.email])
                except Exception:
                    pass

            # remove duplicates and empties
            recipients = list(dict.fromkeys([r for r in recipients if r]))
            
            if to_send:
                print(f"  to_send: {to_send}, recipients: {recipients}")

            if to_send and recipients:

                # Build body with appropriate warning level
                agent_info = "None"
                try:
                    if getattr(lead, "assigned_to", None):
                        a = lead.assigned_to
                        agent_info = f"{getattr(a, 'asc_name', a.email)} <{getattr(a, 'email', '')}>"
                except Exception:
                    pass

                supervisor_info = "None"
                manager_info = "None"
                try:
                    if asc_code:= (getattr(lead.assigned_to, 'asc_code', None) if getattr(lead, 'assigned_to', None) else None):
                        sup_qs = LoginUser.objects.filter(asc_code=asc_code, role__name__iexact="SUPERVISOR", is_active=True)
                        supervisor_info = ", ".join([f"{u.asc_name} <{u.email}>" for u in sup_qs if u.email]) or "None"
                        man_qs = LoginUser.objects.filter(asc_code=asc_code, role__name__iexact="MANAGER", is_active=True)
                        manager_info = ", ".join([f"{u.asc_name} <{u.email}>" for u in man_qs if u.email]) or "None"
                except Exception:
                    pass

                warning = ""
                if reminder_count == 2:
                    warning = "\n\n*** SECOND REMINDER: follow-up is overdue by at least 1 day ***"
                elif reminder_count == 3:
                    warning = "\n\n*** THIRD REMINDER: follow-up overdue by 2+ days - manager notified ***"

                message = f"""
{warning}

Lead Name: {lead.lead_name}
Agent: {agent_info}
Supervisors: {supervisor_info}
Managers: {manager_info}
Phone: {phone.get('phone')}
Status: {status}
Remarks: {phone.get('remarks', '')}

Follow-up Time: {followup_dt.strftime('%d %b %Y %I:%M %p')}
"""

                try:
                    send_mail(
                        subject=subject,
                        message=message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=recipients,
                        fail_silently=False,
                    )
                    print(f"  Successfully sent mail to {recipients}")
                    changes_made = True
                    phone["reminder_count"] = reminder_count
                    phone["last_reminder"] = now.isoformat()
                except Exception as e:
                    print(f"  ERROR sending mail to {recipients}: {e}")
                    # if sending fails, don't increment count
                    pass


                # append log
                try:
                    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'server_log.txt')
                    if not os.path.exists(log_path):
                        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'server_log.txt')
                    with open(log_path, 'a', encoding='utf-8') as lf:
                        lf.write(f"{timezone.now().isoformat()} SENT reminder{reminder_count} lead={lead.id} phone={phone.get('phone')} recipients={recipients}\n")
                except Exception:
                    pass

        if changes_made:
            lead.save()
