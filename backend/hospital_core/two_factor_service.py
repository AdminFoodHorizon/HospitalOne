
import os
import time

import pyotp
from cryptography.fernet import Fernet
from django.db import transaction
from dotenv import load_dotenv

from .two_factor_models import TwoFactorCredential


load_dotenv()


def get_cipher():
    key = os.environ.get("TWO_FACTOR_ENCRYPTION_KEY")

    if not key:
        raise RuntimeError(
            "TWO_FACTOR_ENCRYPTION_KEY is missing."
        )

    return Fernet(key.encode("utf-8"))


def encrypt_secret(secret):
    return get_cipher().encrypt(
        secret.encode("utf-8")
    ).decode("utf-8")


def decrypt_secret(encrypted_secret):
    return get_cipher().decrypt(
        encrypted_secret.encode("utf-8")
    ).decode("utf-8")


def generate_totp_secret():
    return pyotp.random_base32()


def generate_enrollment_uri(user, secret):
    return pyotp.TOTP(secret).provisioning_uri(
        name=user.username,
        issuer_name="Hospital Management"
    )


def verify_totp_secret(secret, code):
    """
    Check whether a TOTP code is valid.

    This function is intended for initial enrollment.
    It does not implement replay protection.
    """
    if not isinstance(code, str):
        return False

    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return False

    return pyotp.TOTP(secret).verify(
        code,
        valid_window=1
    )


@transaction.atomic
def verify_user_totp(user, code):
    """
    Verify a user's enabled TOTP credential.

    Uses a database row lock to prevent concurrent
    requests from accepting the same time step.
    """
    if not isinstance(code, str):
        return False

    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return False

    try:
        credential = (
            TwoFactorCredential.objects
            .select_for_update()
            .get(user=user, is_enabled=True)
        )
    except TwoFactorCredential.DoesNotExist:
        return False

    if not credential.encrypted_secret:
        return False

    secret = decrypt_secret(
        credential.encrypted_secret
    )

    totp = pyotp.TOTP(secret)
    current_step = int(time.time()) // totp.interval

    for step in (
        current_step - 1,
        current_step,
        current_step + 1,
    ):
        if (
            credential.last_verified_step is not None
            and step <= credential.last_verified_step
        ):
            continue

        expected_code = totp.at(
            step * totp.interval
        )

        if pyotp.utils.strings_equal(
            expected_code,
            code
        ):
            credential.last_verified_step = step
            credential.save(
                update_fields=[
                    "last_verified_step",
                    "updated_at",
                ]
            )
            return True

    return False
