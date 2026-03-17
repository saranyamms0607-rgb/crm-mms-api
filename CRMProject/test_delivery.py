import os
import django
from django.core.mail import send_mail

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CRMProject.settings')
django.setup()

def test_email():
    try:
        subject = 'Domain SMTP Test via Django'
        message = 'This is a test to verify if the domain email (mail.mediamaticstudio.com) works through Django settings.'
        from_email = os.getenv('EMAIL_HOST_USER')
        recipient_list = ['saranya.s@mediamaticstudio.com', 'contact.mediamaticstudio@gmail.com']
        
        print(f"Attempting to send email from {from_email} to {recipient_list}...")
        send_mail(subject, message, from_email, recipient_list, fail_silently=False)
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error sending email: {e}")

if __name__ == '__main__':
    test_email()
