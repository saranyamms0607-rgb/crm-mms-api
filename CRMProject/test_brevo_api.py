import requests
import os
from dotenv import load_dotenv

load_dotenv('.env')

def test_brevo_api_direct():
    # Fetching values directly from env to verify what's being passed
    api_key = os.getenv('EMAIL_HOST_PASSWORD', '').strip()
    from_email = os.getenv('DEFAULT_FROM_EMAIL', 'saranya.s@mediamaticstudio.com').strip()
    
    print(f"Testing Brevo API...")
    print(f"From Email: {from_email}")
    print(f"Key Length: {len(api_key)}")
    print(f"Key starts with: {api_key[:10]}...")

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    payload = {
        "sender": {"email": from_email},
        "to": [{"email": "contact.mediamaticstudio@gmail.com"}],
        "subject": "Brevo API Final Verification",
        "htmlContent": "<strong>API SUCCESS!</strong> If you receive this, the server is finally communicating via API."
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code in [200, 201]:
            print("\n✅ API works! We should switch to this method.")
        else:
            print("\n❌ API failed. Check if the key is a v3 API key.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    test_brevo_api_direct()
