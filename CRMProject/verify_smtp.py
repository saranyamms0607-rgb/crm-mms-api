import smtplib
import ssl
import os
from dotenv import load_dotenv

load_dotenv('.env')

def verify_smtp():
    host = os.getenv('EMAIL_HOST')
    port = int(os.getenv('EMAIL_PORT', 465))
    user = os.getenv('EMAIL_HOST_USER')
    password = os.getenv('EMAIL_HOST_PASSWORD')
    
    print(f"Connecting to {host}:{port} as {user}...")
    
    context = ssl.create_default_context()
    
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, context=context)
        else:
            server = smtplib.SMTP(host, port)
            server.starttls(context=context)
            
        print("Connection established. Sending HELO...")
        server.set_debuglevel(1)
        server.ehlo()
        
        print(f"Attempting login for {user}...")
        server.login(user, password)
        
        print("Login successful!")
        
        # Try to send a simple mail to a different address to see if it delivers
        sender = user
        receiver = 'mediamaticstudio@gmail.com' # Try a gmail address for verification if possible
        msg = f"Subject: SMTP Test\n\nThis is a test from the CRM server to verify delivery to external mailboxes."
        
        print(f"Sending test mail to {receiver}...")
        server.sendmail(sender, receiver, msg)
        print("Mail sent successfully!")
        
        server.quit()
    except Exception as e:
        print(f"SMTP Error: {e}")

if __name__ == '__main__':
    verify_smtp()
