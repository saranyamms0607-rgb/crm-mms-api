import os
import django
from django.core.mail import send_mail
from django.conf import settings

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CRMProject.settings')
django.setup()

def test_brevo_django():
    try:
        subject = 'Brevo CRM Integration Test'
        message = 'Testing Brevo SMTP relay through Django settings.'
        # Brevo requires the 'from' email to be a verified sender
        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = ['contact.mediamaticstudio@gmail.com', 'saranya.s@mediamaticstudio.com']
        
        print(f"SMTP Host: {settings.EMAIL_HOST}")
        print(f"From Email: {from_email}")
        print(f"To: {recipient_list}")
        
        send_mail(subject, message, from_email, recipient_list, fail_silently=False)
        print("Django send_mail says: SUCCESS")
    except Exception as e:
        print(f"Django send_mail ERROR: {e}")

if __name__ == '__main__':
    test_brevo_django()
