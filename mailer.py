from logging import Logger
import sendgrid
import os
from dotenv import load_dotenv
from sendgrid.helpers.mail import Mail

class Mailer:
    def __init__(self):
        load_dotenv(dotenv_path=".env.local")
        
        sendgrid_api_key = os.getenv('SENDGRID_API_KEY')
        if (sendgrid_api_key == None):
            raise ValueError("Sengrid API key not configured")
        else:
            self.sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)
        
        from_email = os.getenv('SENDGRID_SENDER_EMAIL')
        if (from_email == None):
            raise ValueError("Sengrid sender email not configured")
        else:
            self.from_email = from_email

        to_emails  = os.getenv('SENDGRID_RECIPIENT_EMAILS')
        if (to_emails == None):
            raise ValueError("Sengrid recipient emails not configured")
        else:
            self.to_emails  = to_emails.split(",")

    def send_email(self, subject: str, content: str, logger: Logger):
        logger.info(f"Sending email to {self.to_emails} with subject {subject}")

        mail = Mail(self.from_email, self.to_emails, subject, content)

        # Get a JSON-ready representation of the Mail object
        mail_json = mail.get()

        # Send an HTTP POST request to /mail/send
        response = self.sg.client.mail.send.post(request_body=mail_json)

        if (response.status_code < 300):
            logger.info(f"Email sent. Status code: {str(response.status_code)}")
        else:
            logger.error(f"Failed to send email. Status code: {str(response.status_code)}")
