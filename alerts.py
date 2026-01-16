from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import os
import traceback
from datetime import datetime

def send_error_email(
    subject: str,
    error: Exception,
    context: dict | None = None
):
    try:
        html = f"""
        <h3>Error en CV Assistant</h3>
        <p><b>Fecha:</b> {datetime.utcnow().isoformat()} UTC</p>
        <p><b>Tipo:</b> {type(error).__name__}</p>
        <p><b>Mensaje:</b></p>
        <pre>{str(error)}</pre>
        <p><b>Traceback:</b></p>
        <pre>{traceback.format_exc()}</pre>
        """

        if context:
            html += "<p><b>Contexto:</b></p><pre>" + str(context) + "</pre>"

        message = Mail(
            from_email="miguel.ossa@proton.me",
            to_emails=["miguel.ossa@proton.me"],
            subject=subject,
            html_content=html
        )

        sg = SendGridAPIClient(os.environ.get("SENDGRID_API_KEY"))
        sg.send(message)

    except Exception:
        # Nunca permitas que el sistema de alertas rompa la app
        pass
