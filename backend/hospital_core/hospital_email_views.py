"""Hospital Admin and 2FA-verified superuser hospital-email settings endpoints.

Existing hospital-scoped authentication is deliberately reused. Future platform
superadmin authentication should be implemented separately, not bypassed here.
"""
import json
import logging
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from .models import HospitalEmailConfig, StaffMembership
from .two_factor_models import AuthenticationAuditLog
from .two_factor_service import verify_user_totp
from .views import require_staff
from .hospital_email_service import encrypt_password, send_test_email

logger = logging.getLogger(__name__)


def _auth(request, slug):
    member = require_staff(request, slug)
    if not member or not member.hospital.is_active:
        return None
    if member.role != StaffMembership.Role.ADMIN and not request.user.is_superuser:
        return None
    return member


def _reply(message, status):
    return JsonResponse({'detail': message}, status=status)


def _serialize(config):
    if not config:
        return {'configured': False, 'is_enabled': False, 'has_password': False}
    return {
        'configured': True, 'email_address': config.email_address,
        'smtp_host': 'smtp.gmail.com', 'smtp_port': 587, 'use_tls': True,
        'is_enabled': config.is_enabled,
        'has_password': bool(config.encrypted_app_password),
        'last_tested_at': config.last_tested_at.isoformat() if config.last_tested_at else None,
    }


def _data(request):
    if len(request.body) > 4096:
        return None
    try:
        data = json.loads(request.body)
        return data if isinstance(data, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def _fresh_2fa(request, data):
    code = data.get('totp_code')
    return isinstance(code, str) and verify_user_totp(request.user, code)


def _audit(request, member, event, details):
    AuthenticationAuditLog.objects.create(
        user=request.user, hospital=member.hospital,
        event=event, details=details,
    )


@require_GET
def email_settings(request, slug):
    member = _auth(request, slug)
    if not member:
        return _reply('Forbidden', 403)
    config = HospitalEmailConfig.objects.filter(hospital=member.hospital).first()
    return JsonResponse(_serialize(config))


@require_POST
def save_email_settings(request, slug):
    member = _auth(request, slug)
    if not member:
        return _reply('Forbidden', 403)
    data = _data(request)
    if data is None or not _fresh_2fa(request, data):
        return _reply('Invalid request or fresh 2FA code', 400)
    if set(data) - {'email_address', 'app_password', 'is_enabled', 'totp_code'}:
        return _reply('Unexpected fields', 400)
    address = data.get('email_address')
    password = data.get('app_password')
    enabled = data.get('is_enabled', False)
    if not isinstance(address, str) or len(address) > 254:
        return _reply('Valid email_address required', 400)
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError
    try:
        validate_email(address)
    except ValidationError:
        return _reply('Invalid email address', 400)
    if not isinstance(enabled, bool) or (password is not None and (not isinstance(password, str) or len(password) > 200)):
        return _reply('Invalid configuration', 400)
    if not address.lower().endswith('@gmail.com'):
        return _reply('Only Gmail addresses are supported in this version', 400)
    with transaction.atomic():
        config, _ = HospitalEmailConfig.objects.select_for_update().get_or_create(
            hospital=member.hospital, defaults={'email_address': address}
        )
        address_changed = config.email_address.casefold() != address.casefold()
        config.email_address = address
        config.smtp_host = 'smtp.gmail.com'
        config.smtp_port = 587
        config.use_tls = True
        if password:
            config.encrypted_app_password = encrypt_password(password)
        if address_changed or password:
            config.last_tested_at = None
            config.is_enabled = False
        elif enabled and config.last_tested_at and config.encrypted_app_password:
            config.is_enabled = True
        else:
            config.is_enabled = False
        config.save()
        _audit(request, member, 'EMAIL_CONFIG_UPDATED', {'enabled': config.is_enabled})
    return JsonResponse(_serialize(config))


@require_POST
def test_email_settings(request, slug):
    member = _auth(request, slug)
    if not member:
        return _reply('Forbidden', 403)
    data = _data(request)
    if data is None or not _fresh_2fa(request, data):
        return _reply('Invalid request or fresh 2FA code', 400)
    key = f'hospital_email_test:{member.hospital_id}'
    if not cache.add(key, '1', timeout=60):
        return _reply('Wait 60 seconds before testing again', 429)
    config = HospitalEmailConfig.objects.filter(hospital=member.hospital).first()
    if not config or not config.encrypted_app_password:
        return _reply('Configure sender credentials first', 400)
    try:
        result = send_test_email(config)
    except Exception:
        logger.warning('Hospital sender test failed for hospital_id=%s', member.hospital_id)
        _audit(request, member, 'EMAIL_TEST_FAILED', {})
        return _reply('Email test failed. Check Gmail address and App Password.', 502)
    if result != 1:
        _audit(request, member, 'EMAIL_TEST_FAILED', {})
        return _reply('Gmail did not accept the test message', 502)
    config.last_tested_at = timezone.now()
    config.save(update_fields=['last_tested_at', 'updated_at'])
    _audit(request, member, 'EMAIL_TEST_SUCCESS', {})
    return JsonResponse({'detail': 'Test message accepted by Gmail'})
