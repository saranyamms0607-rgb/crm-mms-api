import smtplib
import ssl
import os
from dotenv import load_dotenv

load_dotenv('.env')

def test_brevo_2525():
    host = 'smtp-relay.brevo.com'
    port = 2525 # Non-standard SMTP port
    user = os.getenv('EMAIL_HOST_USER')
    password = os.getenv('EMAIL_HOST_PASSWORD')
    from_email = os.getenv('DEFAULT_FROM_EMAIL')

    print(f"Connecting to {host}:{port}...")
    try:
        server = smtplib.SMTP(host, port, timeout=10)
        server.set_debuglevel(1)
        server.starttls()
        server.login(user, password)
        print("Login to Brevo successful on Port 2525!")
        server.quit()
    except Exception as e:
        print(f"Error on Port 2525: {e}")

if __name__ == '__main__':
    test_brevo_2525()
