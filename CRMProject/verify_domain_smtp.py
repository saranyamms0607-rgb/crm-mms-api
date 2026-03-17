import smtplib
import ssl
import os
import socket
from dotenv import load_dotenv

load_dotenv('.env')

def verify_domain_smtp():
    # Settings from cPanel screenshot
    host = 'mail.mediamaticstudio.com'
    port = 465  # SSL port from screenshot
    user = 'saranya.s@mediamaticstudio.com'
    password = 'MOWIK@1029' # Previously seen in .env
    
    print(f"Checking DNS for {host}...")
    try:
        ip = socket.gethostbyname(host)
        print(f"Resolved {host} to {ip}")
    except Exception as e:
        print(f"DNS Resolution failed: {e}")
        return

    print(f"Connecting to {host}:{port} using SSL...")
    
    context = ssl.create_default_context()
    
    try:
        # For port 465, we use SMTP_SSL
        server = smtplib.SMTP_SSL(host, port, context=context, timeout=10)
        server.set_debuglevel(1)
        
        print(f"Attempting login for {user}...")
        server.login(user, password)
        
        print("Login successful!")
        
        sender = user
        receiver = 'contact.mediamaticstudio@gmail.com'
        msg = f"Subject: Domain SMTP Test\n\nThis is a test from the CRM server using the domain email {user} via {host}."
        
        print(f"Sending test mail to {receiver}...")
        server.sendmail(sender, [receiver], msg)
        print("Mail sent successfully!")
        
        server.quit()
    except Exception as e:
        print(f"Domain SMTP Error: {e}")
        print("\nTrying Port 587 with STARTTLS as fallback...")
        try:
            server = smtplib.SMTP(host, 587, timeout=10)
            server.set_debuglevel(1)
            server.starttls(context=context)
            server.login(user, password)
            print("Login successful on Port 587!")
            server.quit()
        except Exception as e2:
            print(f"Port 587 also failed: {e2}")

if __name__ == '__main__':
    verify_domain_smtp()
