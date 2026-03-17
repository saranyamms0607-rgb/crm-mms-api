import os
from django.utils import timezone
from datetime import timedelta
import django

# configure settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CRMProject.settings')

django.setup()
from configurations.cron import send_followup_alerts
from Authentication.models import LoginUser, LoginRole
from configurations.models import Lead

# patch send_mail
import configurations.cron as cron

def fake_send_mail(subject, message, from_email, recipient_list, **kwargs):
    print('send_mail called:', subject, 'recipients=', recipient_list)
    return 1
cron.send_mail = fake_send_mail

# cleanup
LoginUser.objects.filter(email__icontains='testagent').delete()
LoginUser.objects.filter(email__icontains='testsup').delete()
LoginUser.objects.filter(email__icontains='testman').delete()

agent_role, _ = LoginRole.objects.get_or_create(name='AGENT')
sup_role, _ = LoginRole.objects.get_or_create(name='SUPERVISOR')
man_role, _ = LoginRole.objects.get_or_create(name='MANAGER')

agent = LoginUser.objects.create(email='testagent@example.com', asc_name='Agent1', asc_code='X123', role=agent_role)
sup = LoginUser.objects.create(email='testsup@example.com', asc_name='Sup1', asc_code='X123', role=sup_role)
man = LoginUser.objects.create(email='testman@example.com', asc_name='Man1', asc_code='X123', role=man_role)

lead = Lead.objects.create(lead_name='TestLead', status='assigned', assigned_to=agent, lead_phones=[{'phone':'12345','status':'followup','followup_date':(timezone.now()+timedelta(minutes=10)).isoformat()}])

print('--- initial call (expect agent only)')
send_followup_alerts()
lead.lead_phones[0]['followup_date']=(timezone.now()-timedelta(days=1, minutes=1)).isoformat()
lead.lead_phones[0]['reminder_count']=1
lead.save()
print('--- second reminder (expect agent+sup)')
send_followup_alerts()
lead.lead_phones[0]['followup_date']=(timezone.now()-timedelta(days=2, minutes=1)).isoformat()
lead.lead_phones[0]['reminder_count']=2
lead.save()
print('--- third reminder (expect agent+sup+man)')
send_followup_alerts()
