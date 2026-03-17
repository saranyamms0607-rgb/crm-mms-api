import smtplib
import ssl
import os
from dotenv import load_dotenv

load_dotenv('.env')

def diagnostic_smtp():
    host = os.getenv('EMAIL_HOST')
    port = int(os.getenv('EMAIL_PORT', 587))
    user = os.getenv('EMAIL_HOST_USER')
    password = os.getenv('EMAIL_HOST_PASSWORD')
    from_email = os.getenv('DEFAULT_FROM_EMAIL')

    print(f"--- DIAGNOSTIC START ---")
    print(f"Connecting to: {host}:{port}")
    print(f"User check: {user}")
    print(f"Password length: {len(password) if password else 0}")
    
    context = ssl.create_default_context()
    
    try:
        server = smtplib.SMTP(host, port, timeout=15)
        server.set_debuglevel(1)
        server.starttls(context=context)
        
        print(f"\nAttempting LOGIN...")
        server.login(user, password)
        print("\nSUCCESS: Login successful!")
        
        # If login works, try to send a test mail
        msg = f"Subject: Server Diagnostic Test\nFrom: {from_email}\nTo: contact.mediamaticstudio@gmail.com\n\nDiagnostic test from server."
        server.sendmail(from_email, ['contact.mediamaticstudio@gmail.com'], msg)
        print("SUCCESS: Test email sent!")
        
        server.quit()
    except Exception as e:
        print(f"\nFAILED: {e}")
    print(f"--- DIAGNOSTIC END ---")

if __name__ == '__main__':
    diagnostic_smtp()
