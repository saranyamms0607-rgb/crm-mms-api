import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

class BrevoEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, 'EMAIL_HOST_PASSWORD', None)
        self.api_url = "https://api.brevo.com/v3/smtp/email"

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        
        count = 0
        for message in email_messages:
            if self._send(message):
                count += 1
        return count

    def _send(self, message):
        if not self.api_key:
            return False

        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Format recipients
        to_list = [{"email": addr} for addr in message.to]
        
        payload = {
            "sender": {"email": settings.DEFAULT_FROM_EMAIL},
            "to": to_list,
            "subject": message.subject,
        }

        # Handle HTML or Text content
        if getattr(message, 'content_subtype', None) == 'html':
            payload["htmlContent"] = message.body
        else:
            payload["textContent"] = message.body

        try:
            response = requests.post(self.api_url, headers=headers, json=payload)
            if response.status_code in [200, 201]:
                return True
            else:
                print(f"Brevo API Error: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            if not self.fail_silently:
                raise e
            return False
