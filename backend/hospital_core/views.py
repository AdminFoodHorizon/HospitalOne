"""Hospital staff authentication API: password, TOTP enrollment, recovery, logout.

Requires existing TwoFactorCredential, TwoFactorRecoveryCode, AuthenticationAuditLog,
and hospital_core.two_factor_service from the prior setup steps.
"""
import json
import secrets
import time

import pyotp
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import Hospital, StaffMembership
from .two_factor_models import (
    AuthenticationAuditLog, TwoFactorCredential, TwoFactorRecoveryCode,
)
from .two_factor_service import (
    encrypt_secret, decrypt_secret, generate_totp_secret,
    generate_enrollment_uri, verify_user_totp,
)

PREAUTH_KEY = 'hospital_auth_pending'
PREAUTH_SECONDS = 300
MAX_ATTEMPTS = 5


def reply(message, status=400, **extra):
    return JsonResponse({'detail': message, **extra}, status=status)


def body(request):
    try:
        data = json.loads(request.body or b'{}')
        return data if isinstance(data, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def audit(event, user=None, hospital=None, details=None):
    AuthenticationAuditLog.objects.create(
        event=event, user=user, hospital=hospital,
        details=details or {},
    )


def membership_for(user, slug):
    return (StaffMembership.objects.select_related('hospital', 'department')
            .filter(user=user, hospital__slug=slug,
                    hospital__is_active=True, is_active=True).first())


def pending(request):
    state = request.session.get(PREAUTH_KEY)
    if not isinstance(state, dict) or time.time() - state.get('at', 0) > PREAUTH_SECONDS:
        request.session.pop(PREAUTH_KEY, None)
        return None
    return state


def pending_membership(request, slug):
    state = pending(request)
    if not state or state.get('slug') != slug:
        return None, None
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.filter(pk=state['user_id'], is_active=True).first()
    return user, membership_for(user, slug) if user else None


def require_staff(request, slug):
    if not request.user.is_authenticated or not request.session.get('hospital_2fa_verified'):
        return None
    if request.session.get('hospital_2fa_slug') != slug:
        return None
    return membership_for(request.user, slug)


def fail_attempt(request, state):
    state['attempts'] = state.get('attempts', 0) + 1
    if state['attempts'] >= MAX_ATTEMPTS:
        request.session.pop(PREAUTH_KEY, None)
    else:
        request.session[PREAUTH_KEY] = state


@ensure_csrf_cookie
@require_GET
def csrf(request):
    return JsonResponse({'detail': 'CSRF cookie set'})


@require_POST
def password_login(request, slug):
    data = body(request)
    username, password = data.get('username', ''), data.get('password', '')
    if not isinstance(username, str) or not isinstance(password, str):
        return reply('Invalid credentials', 401)
    # Do not allow a password-authenticated session to bypass TOTP.
    logout(request)
    user = authenticate(request, username=username, password=password)
    member = membership_for(user, slug) if user and user.is_active else None
    if not member:
        audit(AuthenticationAuditLog.Event.LOGIN_FAILED)
        return reply('Invalid credentials or hospital membership', 401)
    request.session.cycle_key()
    request.session[PREAUTH_KEY] = {
        'user_id': user.pk, 'slug': slug, 'at': time.time(), 'attempts': 0,
    }
    credential = TwoFactorCredential.objects.filter(user=user).first()
    return JsonResponse({
        'detail': 'Second factor required',
        'next_step': 'verify' if credential and credential.is_enabled else 'enroll',
    })


@require_POST
def enroll_start(request, slug):
    user, member = pending_membership(request, slug)
    if not member:
        return reply('Password verification required', 401)
    credential, _ = TwoFactorCredential.objects.get_or_create(user=user)
    if credential.is_enabled:
        return reply('2FA already enabled', 409)
    secret = generate_totp_secret()
    credential.encrypted_secret = encrypt_secret(secret)
    credential.last_verified_step = None
    credential.save(update_fields=['encrypted_secret', 'last_verified_step', 'updated_at'])
    return JsonResponse({
        'detail': 'Scan this URI in your authenticator app, then confirm a code',
        'otpauth_uri': generate_enrollment_uri(user, secret),
    })


@require_POST
def enroll_confirm(request, slug):
    user, member = pending_membership(request, slug)
    if not member:
        return reply('Password verification required', 401)
    code = body(request).get('code')
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        return reply('Invalid verification code', 400)
    state = pending(request)
    with transaction.atomic():
        credential = (TwoFactorCredential.objects.select_for_update()
                      .filter(user=user, is_enabled=False).first())
        if not credential or not credential.encrypted_secret:
            return reply('Start enrollment first', 409)
        secret = decrypt_secret(credential.encrypted_secret)
        totp = pyotp.TOTP(secret)
        step = int(time.time()) // totp.interval
        matched = next((s for s in (step - 1, step, step + 1)
                        if pyotp.utils.strings_equal(totp.at(s * totp.interval), code)), None)
        if matched is None:
            fail_attempt(request, state)
            audit(AuthenticationAuditLog.Event.TWO_FACTOR_FAILED, user, member.hospital)
            return reply('Invalid verification code', 401)
        credential.is_enabled = True
        credential.confirmed_at = timezone.now()
        credential.last_verified_step = matched
        credential.save(update_fields=['is_enabled', 'confirmed_at', 'last_verified_step', 'updated_at'])
        # Issue recovery codes once, as plaintext only in this response.
        raw_codes = [secrets.token_hex(6) for _ in range(8)]
        TwoFactorRecoveryCode.objects.filter(credential=credential).delete()
        TwoFactorRecoveryCode.objects.bulk_create([
            TwoFactorRecoveryCode(credential=credential, code_hash=make_password(c))
            for c in raw_codes
        ])
    audit(AuthenticationAuditLog.Event.TWO_FACTOR_SETUP, user, member.hospital)
    # Do not log in automatically after enrollment: require a fresh login challenge.
    request.session.pop(PREAUTH_KEY, None)
    return JsonResponse({'detail': '2FA enabled. Save recovery codes securely and sign in again.',
                         'recovery_codes': raw_codes})


@require_POST
def verify_login(request, slug):
    user, member = pending_membership(request, slug)
    if not member:
        return reply('Password verification required', 401)
    state = pending(request)
    code = body(request).get('code')
    if not isinstance(code, str) or not verify_user_totp(user, code):
        fail_attempt(request, state)
        audit(AuthenticationAuditLog.Event.TWO_FACTOR_FAILED, user, member.hospital)
        return reply('Invalid or reused verification code', 401)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.session.pop(PREAUTH_KEY, None)
    request.session['hospital_2fa_verified'] = True
    request.session['hospital_2fa_slug'] = slug
    audit(AuthenticationAuditLog.Event.TWO_FACTOR_SUCCESS, user, member.hospital)
    audit(AuthenticationAuditLog.Event.LOGIN_SUCCESS, user, member.hospital)
    return JsonResponse({'detail': 'Login successful', 'role': member.role,
                         'hospital': member.hospital.name})


@require_POST
def recovery_login(request, slug):
    user, member = pending_membership(request, slug)
    if not member:
        return reply('Password verification required', 401)
    state = pending(request)
    code = body(request).get('recovery_code')
    if not isinstance(code, str) or len(code) > 100:
        return reply('Invalid recovery code', 400)
    with transaction.atomic():
        credential = TwoFactorCredential.objects.select_for_update().filter(
            user=user, is_enabled=True).first()
        matched = None
        if credential:
            for candidate in (TwoFactorRecoveryCode.objects.select_for_update()
                              .filter(credential=credential, used_at__isnull=True)):
                if check_password(code, candidate.code_hash):
                    matched = candidate
                    break
        if not matched:
            fail_attempt(request, state)
            audit(AuthenticationAuditLog.Event.TWO_FACTOR_FAILED, user, member.hospital)
            return reply('Invalid recovery code', 401)
        matched.used_at = timezone.now()
        matched.save(update_fields=['used_at'])
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.session.pop(PREAUTH_KEY, None)
    request.session['hospital_2fa_verified'] = True
    request.session['hospital_2fa_slug'] = slug
    audit(AuthenticationAuditLog.Event.RECOVERY_USED, user, member.hospital)
    return JsonResponse({'detail': 'Recovery login successful. Review your 2FA settings.',
                         'role': member.role})


@require_GET
def me(request, slug):
    member = require_staff(request, slug)
    if not member:
        return reply('Authentication and 2FA required', 401)
    return JsonResponse({'username': request.user.username, 'role': member.role,
                         'hospital': member.hospital.name,
                         'hospital_slug': slug,
                         'department': member.department.name if member.department else None})


@require_POST
def staff_logout(request, slug):
    member = require_staff(request, slug)
    if member:
        audit(AuthenticationAuditLog.Event.LOGOUT, request.user, member.hospital)
    logout(request)
    return JsonResponse({'detail': 'Logged out'})
