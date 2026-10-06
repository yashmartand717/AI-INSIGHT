"""Optional Gmail SMTP configuration for the host Django settings module."""
import os
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email


def gmail_smtp_settings(environ=None):
    env = os.environ if environ is None else environ
    sender = env.get("GMAIL_SENDER_EMAIL", "").strip()
    password = env.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    try:
        validate_email(sender)
    except ValidationError:
        raise ImproperlyConfigured("Set a valid GMAIL_SENDER_EMAIL") from None
    if not password:
        raise ImproperlyConfigured("Set GMAIL_APP_PASSWORD for the sending account")
    return {
        "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "EMAIL_HOST": "smtp.gmail.com", "EMAIL_PORT": 587,
        "EMAIL_USE_TLS": True, "EMAIL_USE_SSL": False,
        "EMAIL_HOST_USER": sender, "EMAIL_HOST_PASSWORD": password,
        "DEFAULT_FROM_EMAIL": sender, "EMAIL_TIMEOUT": 30,
        "INSIGHTS_MESSAGE_ID_DOMAIN": sender.rsplit("@", 1)[1],
    }
