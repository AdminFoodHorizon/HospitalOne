import hashlib
import hmac
import json
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from .display_security import generate_display_credential, hash_display_credential
from .models import (
    AnnouncementEvent, Hospital, HospitalDisplayDevice,
    HospitalDisplayPairingRequest, StaffMembership,
)
from .two_factor_service import verify_user_totp
from .views import require_staff

logger = logging.getLogger(__name__)
DEVICE_COOKIE = 'hospital_display_device'
SESSION_COOKIE = 'hospital_display_session'
COOKIE_AGE = 7 * 24 * 3600


def respond(data, status=200):
    response = JsonResponse(data, status=status)
    response['Cache-Control'] = 'no-store'
    return response


def payload(request):
    try:
        value = json.loads(request.body or b'{}')
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def cookie_path(slug):
    return f'/api/hospital/{slug}/announcement/display/'


def authorized_device(request, slug):
    device_id = request.COOKIES.get(DEVICE_COOKIE)
    secret = request.COOKIES.get(SESSION_COOKIE)
    if not device_id or not secret or len(secret) > 256:
        return None
    try:
        device = HospitalDisplayDevice.objects.select_related('hospital').get(
            device_id=device_id, hospital__slug=slug,
            hospital__is_active=True, is_active=True,
        )
    except (HospitalDisplayDevice.DoesNotExist, ValueError, TypeError):
        return None
    if not device.credential_hash or (
        device.credential_expires_at and device.credential_expires_at <= timezone.now()
    ):
        return None
    if not hmac.compare_digest(device.credential_hash, digest(secret)):
        return None
    return device


@csrf_protect
@require_POST
def request_display_pairing(request, slug):
    data = payload(request)
    if data is None:
        return respond({'detail': 'Invalid JSON'}, 400)
    name = data.get('device_name', 'Central Announcement TV')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        return respond({'detail': 'Invalid device name'}, 400)
    hospital = Hospital.objects.filter(slug=slug, is_active=True).first()
    if not hospital:
        return respond({'detail': 'Hospital unavailable'}, 404)
    now = timezone.now()
    # Defense in depth, not a replacement for IP/user rate limiting at the proxy.
    pending = HospitalDisplayPairingRequest.objects.filter(
        hospital=hospital,
        status=HospitalDisplayPairingRequest.Status.PENDING,
        expires_at__gt=now,
    ).count()
    if pending >= 5:
        return respond({'detail': 'Too many pending requests'}, 429)
    code = f'{secrets.randbelow(1000000):06d}'
    secret = secrets.token_urlsafe(32)
    pairing = HospitalDisplayPairingRequest.objects.create(
        hospital=hospital,
        device_name=name.strip(),
        pairing_code_hash=digest(code),
        pairing_secret_hash=digest(secret),
        expires_at=now + timedelta(minutes=5),
    )
    return respond({
        'request_id': str(pairing.request_id),
        'pairing_code': code,
        'pairing_secret': secret,
        'expires_at': pairing.expires_at.isoformat(),
    })


@csrf_protect
@require_POST
def approve_display_pairing(request, slug):
    member = require_staff(request, slug)
    if not member or member.role != StaffMembership.Role.ADMIN:
        return respond({'detail': 'Hospital administrator login and 2FA required'}, 403)
    data = payload(request)
    if data is None:
        return respond({'detail': 'Invalid JSON'}, 400)
    code, totp = data.get('pairing_code'), data.get('totp_code')
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        return respond({'detail': 'Invalid pairing code'}, 400)
    if not isinstance(totp, str) or not verify_user_totp(request.user, totp):
        logger.warning('Display pairing fresh 2FA rejected: hospital=%s user=%s', slug, request.user.pk)
        return respond({'detail': 'Invalid or reused authenticator code'}, 403)
    now = timezone.now()
    # Lock hospital row to serialize approvals for this hospital.
    with transaction.atomic():
        Hospital.objects.select_for_update().get(pk=member.hospital_id)
        candidates = HospitalDisplayPairingRequest.objects.select_for_update().filter(
            hospital_id=member.hospital_id,
            status=HospitalDisplayPairingRequest.Status.PENDING,
            expires_at__gt=now,
        )
        pairing = next((p for p in candidates if hmac.compare_digest(p.pairing_code_hash, digest(code))), None)
        if pairing is None:
            logger.warning('Display pairing code rejected: hospital=%s user=%s', slug, request.user.pk)
            return respond({'detail': 'Pairing code not found or expired'}, 404)
        pairing.status = HospitalDisplayPairingRequest.Status.APPROVED
        pairing.approved_by = member
        pairing.approved_at = now
        pairing.save(update_fields=['status', 'approved_by', 'approved_at'])
    logger.warning('Display pairing approved: hospital=%s user=%s request=%s', slug, request.user.pk, pairing.request_id)
    return respond({'detail': 'TV approved. Complete pairing on the TV.'})


@csrf_protect
@require_POST
def claim_display_pairing(request, slug):
    data = payload(request)
    if data is None:
        return respond({'detail': 'Invalid JSON'}, 400)
    request_id, secret = data.get('request_id'), data.get('pairing_secret')
    if not isinstance(secret, str) or len(secret) > 256:
        return respond({'detail': 'Invalid pairing request'}, 403)
    now = timezone.now()
    with transaction.atomic():
        try:
            pairing = HospitalDisplayPairingRequest.objects.select_for_update().select_related('hospital').get(
                request_id=request_id, hospital__slug=slug, hospital__is_active=True,
            )
        except (HospitalDisplayPairingRequest.DoesNotExist, ValueError, TypeError):
            return respond({'detail': 'Invalid pairing request'}, 403)
        if not pairing.pairing_secret_hash or not hmac.compare_digest(pairing.pairing_secret_hash, digest(secret)):
            return respond({'detail': 'Invalid pairing request'}, 403)
        if pairing.expires_at <= now:
            return respond({'detail': 'Pairing expired'}, 410)
        if pairing.status == HospitalDisplayPairingRequest.Status.PENDING:
            return respond({'status': 'PENDING'}, 202)
        if pairing.status != HospitalDisplayPairingRequest.Status.APPROVED:
            return respond({'detail': 'Pairing already used'}, 409)
        # A unique name identifies the hospital's central TV; re-pairing revokes old credentials.
        device, _ = HospitalDisplayDevice.objects.select_for_update().get_or_create(
            hospital=pairing.hospital, name=pairing.device_name,
        )
        session_secret = generate_display_credential()
        device.credential_hash = hash_display_credential(session_secret)
        device.is_active = True
        device.paired_at = now
        device.credential_expires_at = now + timedelta(days=7)
        device.save(update_fields=['credential_hash', 'is_active', 'paired_at', 'credential_expires_at'])
        pairing.status = HospitalDisplayPairingRequest.Status.CONSUMED
        pairing.device = device
        pairing.pairing_secret_hash = ''
        pairing.save(update_fields=['status', 'device', 'pairing_secret_hash'])
    response = respond({'status': 'PAIRED', 'hospital': pairing.hospital.name, 'device_name': device.name})
    options = dict(httponly=True, secure=not settings.DEBUG, samesite='Strict', max_age=COOKIE_AGE, path=cookie_path(slug))
    response.set_cookie(DEVICE_COOKIE, str(device.device_id), **options)
    response.set_cookie(SESSION_COOKIE, session_secret, **options)
    logger.warning('Display paired: hospital=%s device=%s', slug, device.device_id)
    return response



@require_GET
def display_announcements(request, slug):
    """
    Return up to 8 currently active patient calls.

    A call is active only when:
    - The TV is authorized for this hospital.
    - The queue entry is still CALLED.
    - The call is less than 5 minutes old.

    Historical AnnouncementEvent records are preserved.
    """

    device = authorized_device(request, slug)

    if not device:
        return respond({
            'detail': 'TV not paired, expired or revoked'
        }, 403)

    now = timezone.now()
    cutoff = now - timedelta(minutes=5)

    events = (
        AnnouncementEvent.objects
        .select_related('queue_entry')
        .filter(
            hospital_id=device.hospital_id,
            queue_entry__status='CALLED',
            queue_entry__called_at__isnull=False,
            queue_entry__called_at__gt=cutoff,
        )
        .order_by('-id')
    )

    entries = []
    seen_queue_entries = set()

    for event in events:
        queue_entry = event.queue_entry

        # Only show the announcement belonging
        # to the current call, not an older recall.
        if event.called_at < queue_entry.called_at:
            continue

        if queue_entry.pk in seen_queue_entries:
            continue

        seen_queue_entries.add(queue_entry.pk)

        deadline = queue_entry.called_at + timedelta(
            minutes=5
        )

        remaining_seconds = max(
            0,
            int((deadline - now).total_seconds())
        )

        entries.append({
            'event_id': event.pk,
            'token': event.token,
            'department': event.department_name,
            'room_number': event.room_number,
            'called_at': queue_entry.called_at.isoformat(),
            'expires_at': deadline.isoformat(),
            'remaining_seconds': remaining_seconds,
        })

        if len(entries) >= 8:
            break

    return respond({
        'hospital': device.hospital.name,
        'device_name': device.name,
        'server_time': now.isoformat(),
        'entries': entries,
    })



@csrf_protect
@require_POST
def revoke_display(request, slug):
    member = require_staff(request, slug)
    if not member or member.role != StaffMembership.Role.ADMIN:
        return respond({'detail': 'Administrator login and 2FA required'}, 403)
    data = payload(request)
    if data is None or not isinstance(data.get('device_id'), str):
        return respond({'detail': 'device_id required'}, 400)
    if not isinstance(data.get('totp_code'), str) or not verify_user_totp(request.user, data['totp_code']):
        return respond({'detail': 'Fresh authenticator code required'}, 403)
    count = HospitalDisplayDevice.objects.filter(
        hospital_id=member.hospital_id, device_id=data['device_id'],
    ).update(is_active=False, credential_hash='')
    if not count:
        return respond({'detail': 'Device not found'}, 404)
    logger.warning('Display revoked: hospital=%s device=%s user=%s', slug, data['device_id'], request.user.pk)
    return respond({'detail': 'Display revoked'})
