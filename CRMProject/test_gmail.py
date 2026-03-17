import smtplib
import ssl
import os
from dotenv import load_dotenv

load_dotenv('.env')

def test_gmail():
    host = 'smtp.gmail.com'
    port = 587
    user = 'contact.mediamaticstudio@gmail.com'
    password = 'ytdrevbodiddaayr'
    
    print(f"Connecting to {host}:{port} as {user}...")
    
    context = ssl.create_default_context()
    
    try:
        server = smtplib.SMTP(host, port)
        server.set_debuglevel(1)
        server.starttls(context=context)
        
        print(f"Attempting login for {user}...")
        server.login(user, password)
        
        print("Login to Gmail successful!")
        
        sender = user
        receiver = user
        msg = f"Subject: Gmail SMTP Test\n\nThis is a test from the CRM server using Gmail SMTP."
        
        print(f"Sending test mail to {receiver}...")
        server.sendmail(sender, [receiver], msg)
        print("Mail sent successfully!")
        
        server.quit()
    except Exception as e:
        print(f"Gmail SMTP Error: {e}")

if __name__ == '__main__':
    test_gmail()
