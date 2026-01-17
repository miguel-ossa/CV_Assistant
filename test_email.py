import os
import smtplib
import ssl
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv(override=True)

def send_test_email():
    msg = EmailMessage()
    msg["From"] = os.getenv("ALERT_EMAIL_FROM")
    msg["To"] = os.getenv("ALERT_EMAIL_TO")
    msg["Subject"] = "SMTP test OK"
    msg.set_content("Si lees esto, el envío SMTP funciona correctamente.")

    context = ssl.create_default_context()

    with smtplib.SMTP(
        os.getenv("SMTP_HOST"),
        int(os.getenv("SMTP_PORT")),
        timeout=10
    ) as server:
        server.starttls(context=context)
        server.login(
            os.getenv("SMTP_USER"),
            os.getenv("SMTP_PASSWORD")
        )
        server.send_message(msg)

    print("Email enviado correctamente")

if __name__ == "__main__":
    send_test_email()
