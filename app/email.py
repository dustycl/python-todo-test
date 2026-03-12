import logging

from flask import render_template
from flask_mail import Mail, Message

logger = logging.getLogger(__name__)

mail = Mail()


def init_app(app):
    """Initialize Flask-Mail with the app."""
    mail.init_app(app)


def send_welcome_email(email, first_name):
    """Send a welcome email to a newly registered user.

    Failures are logged but do not raise, so registration is never blocked.
    """
    try:
        msg = Message(
            subject="Welcome to Todo App!",
            recipients=[email],
        )
        msg.body = render_template("emails/welcome.txt", first_name=first_name)
        msg.html = render_template("emails/welcome.html", first_name=first_name)
        mail.send(msg)
        logger.info("Welcome email sent to %s", email)
    except Exception:
        logger.error("Failed to send welcome email to %s", email, exc_info=True)
