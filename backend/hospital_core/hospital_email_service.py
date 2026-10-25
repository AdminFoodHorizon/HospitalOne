"""Hospital-specific Gmail SMTP; credentials never leave the server."""
import os
from cryptography.fernet import Fernet
from django.core.mail import EmailMessage, get_connection
from django.core.exceptions import ImproperlyConfigured


def _cipher():
    key = os.getenv('HOSPITAL_EMAIL_ENCRYPTION_KEY', '')
    if not key:
        raise ImproperlyConfigured('HOSPITAL_EMAIL_ENCRYPTION_KEY is missing')
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured('Invalid HOSPITAL_EMAIL_ENCRYPTION_KEY') from exc


def encrypt_password(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('A nonempty app password is required')
    return _cipher().encrypt(value.replace(' ', '').encode()).decode()


def decrypt_password(value):
    return _cipher().decrypt(value.encode()).decode()


def send_test_email(config):
    # Restrict host/port to prevent SSRF and unapproved outbound SMTP destinations.
    if config.smtp_host != 'smtp.gmail.com' or config.smtp_port != 587 or not config.use_tls:
        raise ValueError('Only Gmail SMTP with TLS on port 587 is supported')
    connection = get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host='smtp.gmail.com', port=587, use_tls=True, use_ssl=False,
        username=config.email_address,
        password=decrypt_password(config.encrypted_app_password),
        timeout=20,
    )
    return EmailMessage(
        subject='HospitalOne sender verification',
        body='Your HospitalOne hospital email sender configuration has been tested.',
        from_email=config.email_address,
        to=[config.email_address],
        connection=connection,
    ).send(fail_silently=False)
