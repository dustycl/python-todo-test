import logging
import threading

from flask import current_app, render_template
from flask_mail import Mail, Message

logger = logging.getLogger(__name__)

mail = Mail()


def init_app(app):
    """Initialize Flask-Mail with the app."""
    mail.init_app(app)


def send_welcome_email(email, first_name):
    """Send a welcome email to a newly registered user in a background thread.

    Runs asynchronously so SMTP latency or failures never block the request.
    """
    app = current_app._get_current_object()
    body = render_template("emails/welcome.txt", first_name=first_name)
    html = render_template("emails/welcome.html", first_name=first_name)

    def _send():
        with app.app_context():
            try:
                msg = Message(
                    subject="Welcome to Todo App!",
                    recipients=[email],
                )
                msg.body = body
                msg.html = html
                mail.send(msg)
                logger.info("Welcome email sent to %s", email)
            except Exception:
                logger.error("Failed to send welcome email to %s", email, exc_info=True)

    threading.Thread(target=_send, daemon=True).start()
