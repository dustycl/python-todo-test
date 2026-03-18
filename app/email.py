import logging
import threading

import resend
from flask import current_app, render_template

logger = logging.getLogger(__name__)


def init_app(app):
    """Configure Resend with the API key from app config."""
    resend.api_key = app.config["RESEND_API_KEY"]


def send_welcome_email(email, first_name):
    """Send a welcome email to a newly registered user in a background thread.

    Runs asynchronously so API latency or failures never block the request.
    """
    app = current_app._get_current_object()
    body = render_template("emails/welcome.txt", first_name=first_name)
    html = render_template("emails/welcome.html", first_name=first_name)

    def _send():
        with app.app_context():
            try:
                resend.Emails.send({
                    "from": app.config["MAIL_DEFAULT_SENDER"],
                    "to": email,
                    "subject": "Welcome to Todo App!",
                    "text": body,
                    "html": html,
                })
                logger.info("Welcome email sent to %s", email)
            except Exception:
                logger.error("Failed to send welcome email to %s", email, exc_info=True)

    threading.Thread(target=_send, daemon=True).start()
