
import hashlib
import hmac
import secrets

from django.utils import timezone

from .models import HospitalDisplayDevice


def generate_display_credential():
    """
    Generate a cryptographically secure TV credential.

    The plaintext credential must only be shown during
    authorized pairing, never stored in the database.
    """
    return secrets.token_urlsafe(48)


def hash_display_credential(credential):
    """
    Store only the SHA-256 hash of the random credential.
    """
    return hashlib.sha256(
        credential.encode("utf-8")
    ).hexdigest()


def authenticate_display_device(device_id, credential):
    """
    Verify the device identifier and secret credential.

    Return the authorized device, or None.
    """

    if not device_id or not credential:
        return None

    if not isinstance(credential, str):
        return None

    if len(credential) > 256:
        return None

    try:
        device = (
            HospitalDisplayDevice.objects
            .select_related("hospital")
            .get(
                device_id=device_id,
                is_active=True,
                hospital__is_active=True,
            )
        )
    except (
        HospitalDisplayDevice.DoesNotExist,
        ValueError,
        TypeError,
    ):
        return None

    if not device.credential_hash:
        return None

    if (
        device.credential_expires_at is not None
        and device.credential_expires_at <= timezone.now()
    ):
        return None

    supplied_hash = hash_display_credential(credential)

    if not hmac.compare_digest(
        supplied_hash,
        device.credential_hash,
    ):
        return None

    return device
