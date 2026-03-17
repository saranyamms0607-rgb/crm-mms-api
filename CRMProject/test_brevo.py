import smtplib
import ssl
import os
from dotenv import load_dotenv

# Re-loading .env to ensure we have the latest
load_dotenv('.env')

def test_brevo_smtp():
    host = os.getenv('EMAIL_HOST', '').strip()
    # Handle potential spaces if os.getenv didn't strip them
    if '=' in host: host = host.split('=')[-1].strip()
    
    port = 587
    user = os.getenv('EMAIL_HOST_USER', '').strip()
    if '=' in user: user = user.split('=')[-1].strip()
    
    password = os.getenv('EMAIL_HOST_PASSWORD', '').strip()
    if '=' in password: password = password.split('=')[-1].strip()
    
    from_email = os.getenv('DEFAULT_FROM_EMAIL', '').strip()
    if '=' in from_email: from_email = from_email.split('=')[-1].strip()
    
    print(f"Connecting to {host}:{port}...")
    print(f"User: {user}")
    print(f"From: {from_email}")
    
    context = ssl.create_default_context()
    
    try:
        server = smtplib.SMTP(host, port, timeout=10)
        server.set_debuglevel(1)
        server.starttls(context=context)
        
        print(f"Attempting login...")
        server.login(user, password)
        print("Login to Brevo successful!")
        
        # Test 1: Send to self
        recipient = 'contact.mediamaticstudio@gmail.com'
        msg = f"Subject: Brevo SMTP Test\n\nThis is a test from the CRM server using Brevo SMTP Relay. Sender: {from_email}"
        
        print(f"Sending test mail to {recipient}...")
        # Most relays require the 'From' header to match the envelope sender or be verified
        full_msg = f"From: {from_email}\nTo: {recipient}\n{msg}"
        
        server.sendmail(from_email, [recipient], full_msg)
        print("Mail sent successfully!")
        
        server.quit()
    except Exception as e:
        print(f"Brevo SMTP Error: {e}")

if __name__ == '__main__':
    test_brevo_smtp()
