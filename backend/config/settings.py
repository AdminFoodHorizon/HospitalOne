
"""
Django settings for HospitalOne.

This file controls the main backend configuration:
- Security
- Database connection
- Installed applications
- Middleware
- Authentication
- Language and time zone
- Static files
- Email sending through Gmail

IMPORTANT:
Sensitive information such as database passwords, Django secret keys,
and Gmail App Passwords must be stored in the .env file, not here.
"""

# ============================================================
# 1. IMPORTS
# ============================================================

import os
from pathlib import Path
from dotenv import load_dotenv

# os:
# Reads environment variables such as DB_PASSWORD and EMAIL_HOST_USER.
#
# Path:
# Helps locate folders and files reliably on Mac, Linux and VPS.
#
# load_dotenv:
# Loads private configuration from backend/.env.


# ============================================================
# 2. PROJECT BASE DIRECTORY
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

# Example:
# HospitalManagement/
#     backend/                 <-- BASE_DIR
#         .env
#         manage.py
#         config/
#             settings.py

# Load the environment variables from backend/.env.
load_dotenv(BASE_DIR / ".env")

# Gmail settings below are read from this same .env file.


# ============================================================
# 3. DJANGO SECURITY
# ============================================================

# SECRET_KEY is used by Django to cryptographically sign
# sessions and other security-sensitive data.
#
# We use os.environ[] so Django refuses to start if it is missing.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# DEBUG=True is useful during local development.
# DEBUG must be False on a public production server.
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"

# ALLOWED_HOSTS determines which domain names can access Django.
#
# Example .env:
# DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,hospitalone.com
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1"
    ).split(",")
    if host.strip()
]


# ============================================================
# 4. POSTGRESQL DATABASE
# ============================================================

DATABASES = {
    "default": {
        # HospitalOne uses PostgreSQL instead of SQLite.
        "ENGINE": "django.db.backends.postgresql",

        # Database name.
        "NAME": os.environ["DB_NAME"],

        # PostgreSQL username.
        "USER": os.environ["DB_USER"],

        # PostgreSQL password.
        "PASSWORD": os.environ["DB_PASSWORD"],

        # Database server address.
        # 127.0.0.1 means PostgreSQL runs on this computer.
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),

        # PostgreSQL default port.
        "PORT": os.getenv("DB_PORT", "5432"),

        # Reuse a database connection for up to 60 seconds.
        # This can reduce repeated connection overhead.
        "CONN_MAX_AGE": 60,
    }
}


# ============================================================
# 5. INSTALLED APPLICATIONS
# ============================================================

INSTALLED_APPS = [
    # Django administration interface.
    "django.contrib.admin",

    # User accounts, groups and permissions.
    "django.contrib.auth",

    # Tracks Django models and their content types.
    "django.contrib.contenttypes",

    # Stores login sessions.
    "django.contrib.sessions",

    # Django's message framework.
    "django.contrib.messages",

    # Handles static files such as CSS and JavaScript.
    "django.contrib.staticfiles",

    # Your HospitalOne application.
    "hospital_core.apps.HospitalCoreConfig",
]


# ============================================================
# 6. MIDDLEWARE
# ============================================================

# Middleware processes incoming HTTP requests and outgoing
# HTTP responses.
#
# ORDER MATTERS: Keep these middleware components in
# their existing order.

MIDDLEWARE = [
    # Enables Django's HTTP security features.
    "django.middleware.security.SecurityMiddleware",

    # Reads and writes user session information.
    "django.contrib.sessions.middleware.SessionMiddleware",

    # Common HTTP handling, including URL normalization.
    "django.middleware.common.CommonMiddleware",

    # Protects against Cross-Site Request Forgery attacks.
    "django.middleware.csrf.CsrfViewMiddleware",

    # Associates requests with logged-in Django users.
    "django.contrib.auth.middleware.AuthenticationMiddleware",

    # Enables temporary success/error messages.
    "django.contrib.messages.middleware.MessageMiddleware",

    # Helps protect pages against clickjacking.
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ============================================================
# 7. ROOT URL CONFIGURATION
# ============================================================

# Django starts URL routing from config/urls.py.
ROOT_URLCONF = "config.urls"


# ============================================================
# 8. HTML TEMPLATE CONFIGURATION
# ============================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",

        # Additional template directories can be added here.
        "DIRS": [],

        # Find templates inside installed Django applications.
        "APP_DIRS": True,

        "OPTIONS": {
            "context_processors": [
                # Makes request information available to templates.
                "django.template.context_processors.request",

                # Makes authenticated user information available.
                "django.contrib.auth.context_processors.auth",

                # Makes Django messages available.
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ============================================================
# 9. WSGI APPLICATION
# ============================================================

# WSGI is an interface used by production servers such as
# Gunicorn to communicate with Django.
WSGI_APPLICATION = "config.wsgi.application"


# ============================================================
# 10. PASSWORD VALIDATION
# ============================================================

# These validators help reject weak passwords when Django's
# password-validation system is invoked.

AUTH_PASSWORD_VALIDATORS = [
    {
        # Rejects passwords too similar to user information.
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        # Requires a minimum password length.
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        # Rejects commonly used passwords.
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        # Rejects passwords consisting only of numbers.
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# ============================================================
# 11. LANGUAGE AND TIME ZONE
# ============================================================

# Default application language.
LANGUAGE_CODE = "en-us"

# Use UTC for timestamps in the database.
# The frontend can display dates in the hospital's local time.
TIME_ZONE = "UTC"

# Enable internationalization support.
USE_I18N = True

# Store and process timezone-aware date/time values.
USE_TZ = True


# ============================================================
# 12. STATIC FILES
# ============================================================

# URL prefix for Django static files.
STATIC_URL = "static/"


# ============================================================
# 13. HOSPITALONE EMAIL CONFIGURATION
# ============================================================

# Django provides several email backends.
#
# SMTPEmailBackend sends email through a real mail server.
# We use it to connect HospitalOne to Gmail.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


# Gmail SMTP server address.
EMAIL_HOST = os.getenv(
    "EMAIL_HOST",
    "smtp.gmail.com"
)


# Port 587 supports SMTP with STARTTLS encryption.
EMAIL_PORT = int(
    os.getenv("EMAIL_PORT", "587")
)


# STARTTLS encrypts the connection to Gmail.
EMAIL_USE_TLS = (
    os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
)


# Port 587 uses STARTTLS, not implicit SSL.
EMAIL_USE_SSL = False


# Gmail address used to authenticate with Gmail SMTP.
#
# Example:
# EMAIL_HOST_USER=hospitalone.testing@gmail.com
EMAIL_HOST_USER = os.getenv(
    "EMAIL_HOST_USER",
    ""
).strip()


# Google App Password for the sending Gmail account.
#
# IMPORTANT:
# Do not use your normal Google account password.
# Never put the App Password directly into this file.
EMAIL_HOST_PASSWORD = os.getenv(
    "EMAIL_HOST_PASSWORD",
    ""
)


# The sender address shown in outgoing emails.
#
# For initial testing, use the same Gmail address
# configured in EMAIL_HOST_USER.
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    EMAIL_HOST_USER
)


# Stop waiting after 20 seconds if Gmail does not respond.
# This prevents an email connection from hanging indefinitely.
EMAIL_TIMEOUT = 20


# ============================================================
# 14. HOSPITALONE EMAIL FEATURE FLAG
# ============================================================

# Keep patient email delivery disabled until:
# 1. Gmail SMTP has been tested.
# 2. Patient-specific permissions have been verified.
# 3. Secure medical document delivery is implemented.
#
# The email-sending endpoint must explicitly check this flag.
# Setting it here alone does not enforce the restriction.
HOSPITAL_EMAIL_ENABLED = (
    os.getenv("HOSPITAL_EMAIL_ENABLED", "False").lower() == "true"
)

HOSPITAL_EMAIL_ENCRYPTION_KEY = os.getenv(
    "HOSPITAL_EMAIL_ENCRYPTION_KEY", ""
)
