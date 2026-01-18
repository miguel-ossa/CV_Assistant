import os
from datetime import datetime
import smtplib
import ssl
from email.message import EmailMessage
import traceback
from config import EMAIL_ALERTS_ENABLED


def send_error_email(
    subject: str,
    error: Exception,
    context: dict | None = None
):
    if not EMAIL_ALERTS_ENABLED:
        # Fallback mínimo
        print(f"[ALERTA DESACTIVADA] {subject}: {error}")
        return
    try:
        msg = EmailMessage()
        msg["From"] = os.getenv("ALERT_EMAIL_FROM")
        msg["To"] = os.getenv("ALERT_EMAIL_TO")
        msg["Subject"] = subject

        body = f"""
    Error en CV Assistant

    Fecha: {datetime.utcnow().isoformat()} UTC
    Tipo: {type(error).__name__}

    Mensaje:
    {str(error)}

    Traceback:
    {traceback.format_exc()}
    """

        if context:
            body += f"\nContexto:\n{context}"

        msg.set_content(body)

        context_ssl = ssl.create_default_context()

        with smtplib.SMTP(
                os.getenv("SMTP_HOST"),
                int(os.getenv("SMTP_PORT")),
                timeout=10
        ) as server:
            server.starttls(context=context_ssl)
            server.login(
                os.getenv("SMTP_USER"),
                os.getenv("SMTP_PASSWORD")
            )
            server.send_message(msg)

    except Exception:
        # Nunca romper la app por alertas
        pass

def send_email(proposal: str):
    if not EMAIL_ALERTS_ENABLED:
        print("[EMAIL DESACTIVADO] Propuesta recibida:")
        print(proposal)
        return

    try:
        msg = EmailMessage()
        msg["From"] = os.getenv("ALERT_EMAIL_FROM")
        msg["To"] = os.getenv("ALERT_EMAIL_TO")
        msg["Subject"] = "Nueva propuesta recibida en CV_Assistant"

        body = f"""Fecha: {datetime.utcnow().isoformat()} UTC

Mensaje:
{proposal}
"""
        msg.set_content(body)

        context_ssl = ssl.create_default_context()

        with smtplib.SMTP(
            os.getenv("SMTP_HOST"),
            int(os.getenv("SMTP_PORT")),
            timeout=10
        ) as server:
            server.starttls(context=context_ssl)
            server.login(
                os.getenv("SMTP_USER"),
                os.getenv("SMTP_PASSWORD")
            )
            server.send_message(msg)

    except Exception:
        # Nunca romper la app por alertas
        print(f"Exception: {traceback.format_exc()}")

