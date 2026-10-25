"""Hospital-scoped Nursing queues, attendance, optional vitals and handoffs."""
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import (
    AnnouncementEvent,
    Department,
    NursingAssessment,
    PatientAttendance,
    PatientMovementEvent,
    PatientQueueEntry,
    PatientVisit,
    StaffMembership,
    TestOrderItem,
)
from .views import require_staff


def _nurse(request, slug):
    member = require_staff(request, slug)
    if member is None or member.role != StaffMembership.Role.NURSE:
        return None
    if not member.is_active or not member.hospital.is_active:
        return None
    if member.department_id and (
        member.department.hospital_id != member.hospital_id
        or member.department.kind != Department.Kind.NURSING
        or not member.department.is_active
    ):
        return None
    return member


def _error(message, status=400):
    return JsonResponse({'detail': message}, status=status)


def _json(request):
    try:
        body = json.loads(request.body or b'{}')
        return body if isinstance(body, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def _entry_data(entry):
    return {
        'queue_entry_id': entry.pk,
        'token': entry.visit.queue_token,
        'kind': entry.kind,
        'status': entry.status,
        'queued_at': entry.queued_at.isoformat(),
        'called_at': entry.called_at.isoformat() if entry.called_at else None,
        'department': entry.department.name,
        'room_number': entry.department.room_number,
        'visit_id': entry.visit_id,
        # Staff-only endpoint; never copy patient details to the public TV feed.
        'patient': {
            'patient_number': entry.visit.patient.patient_number,
            'full_name': entry.visit.patient.full_name,
        },
    }


def _assessment_data(a):
    return {
        'id': a.pk, 'visit_id': a.visit_id, 'nurse_id': a.nurse_id,
        'blood_pressure': a.blood_pressure, 'pulse_bpm': a.pulse_bpm,
        'temperature_c': str(a.temperature_c) if a.temperature_c is not None else None,
        'height_cm': str(a.height_cm) if a.height_cm is not None else None,
        'weight_kg': str(a.weight_kg) if a.weight_kg is not None else None,
        'spo2_percent': a.spo2_percent, 'respiratory_rate': a.respiratory_rate,
        'pain_score': a.pain_score, 'notes': a.notes,
        'completed_at': a.completed_at.isoformat() if a.completed_at else None,
    }


def _lock_entry(member, entry_id):
    candidate = PatientQueueEntry.objects.filter(
        pk=entry_id, visit__hospital_id=member.hospital_id,
        department__hospital_id=member.hospital_id,
        department__kind=Department.Kind.NURSING, department__is_active=True,
        kind=PatientQueueEntry.Kind.NURSING_INITIAL,
    ).values_list('visit_id', flat=True).first()
    if candidate is None:
        return None, None
    visit = PatientVisit.objects.select_for_update().get(pk=candidate, hospital_id=member.hospital_id)
    entry = PatientQueueEntry.objects.select_for_update().select_related(
        'visit__patient', 'department'
    ).get(pk=entry_id, visit_id=visit.pk)
    return visit, entry


def _expected_state(entry):
    return (PatientVisit.State.NURSING_INITIAL if entry.kind == PatientQueueEntry.Kind.NURSING_INITIAL
            else PatientVisit.State.NURSING_RETURN)


def _tests_ready(visit):
    items = TestOrderItem.objects.filter(order__visit=visit)
    return items.exists() and not items.exclude(status__in=[
        TestOrderItem.Status.REPORT_READY, TestOrderItem.Status.CANCELLED,
    ]).exists()


@require_GET
def waiting_queue(request, slug):
    member = _nurse(request, slug)
    if member is None:
        return _error('Nursing login and 2FA required', 403)
    qs = PatientQueueEntry.objects.select_related('visit__patient', 'department').filter(
        visit__hospital_id=member.hospital_id,
        department__hospital_id=member.hospital_id,
        department__kind=Department.Kind.NURSING,
        department__is_active=True,
        kind=PatientQueueEntry.Kind.NURSING_INITIAL,
        status__in=[PatientQueueEntry.Status.WAITING, PatientQueueEntry.Status.CALLED],
        visit__state=PatientVisit.State.NURSING_INITIAL,
        queued_at__gte=timezone.now() - timedelta(hours=24),
    ).order_by('queued_at', 'pk')[:200]
    return JsonResponse({'entries': [_entry_data(e) for e in qs]})


@require_POST
def call_patient(request, slug, entry_id):
    member = _nurse(request, slug)

    if member is None:
        return _error(
            'Nursing login and 2FA required',
            403,
        )

    if _json(request) is None:
        return _error('Expected a valid JSON object')

    with transaction.atomic():
        visit, entry = _lock_entry(member, entry_id)

        if entry is None:
            return _error(
                'Nursing queue entry not found in your hospital',
                404,
            )

        # Both a first call and a recall are allowed. Other states remain blocked.
        if entry.status not in (
            PatientQueueEntry.Status.WAITING,
            PatientQueueEntry.Status.CALLED,
        ):
            return _error(
                'Patient is no longer waiting or called; refresh the queue',
                409,
            )

        is_recall = entry.status == PatientQueueEntry.Status.CALLED

        if visit.state != _expected_state(entry):
            return _error(
                'Patient has moved to another workflow stage',
                409,
            )

        if (
            entry.kind == PatientQueueEntry.Kind.NURSING_RETURN
            and not _tests_ready(visit)
        ):
            return _error(
                'All required test results must be ready before Nursing return',
                409,
            )

        if PatientAttendance.objects.filter(
            visit=visit,
            released_at__isnull=True,
        ).exists():
            return _error(
                'Patient is already being attended',
                409,
            )

        if PatientQueueEntry.objects.filter(
            visit=visit,
            status=PatientQueueEntry.Status.CALLED,
        ).exclude(pk=entry.pk).exists():
            return _error(
                'Patient already has an active call',
                409,
            )

        room_number = (entry.department.room_number or '').strip()

        if not room_number:
            return _error(
                'Nursing Station room number is not configured',
                409,
            )

        if not visit.queue_token:
            return _error(
                'This visit has no announcement token',
                409,
            )

        now = timezone.now()

        # Preserve existing Nursing workflow.
        entry.status = PatientQueueEntry.Status.CALLED
        entry.called_at = now
        entry.save(update_fields=['status', 'called_at'])

        # New: record the announcement in the same transaction.
        AnnouncementEvent.objects.create(
            hospital=member.hospital,
            queue_entry=entry,
            called_by=member,
            token=visit.queue_token,
            department_name=entry.department.name,
            room_number=room_number,
            called_at=now,
        )

        # Preserve the response expected by NursingDashboard.js.
        return JsonResponse({
            'detail': 'Patient recalled' if is_recall else 'Patient called',
            'entry': _entry_data(entry),
        })


@require_POST
def start_assessment(request, slug, entry_id):
    member = _nurse(request, slug)
    if member is None:
        return _error('Nursing login and 2FA required', 403)
    if _json(request) is None:
        return _error('Expected a valid JSON object')
    with transaction.atomic():
        visit, entry = _lock_entry(member, entry_id)
        if entry is None:
            return _error('Nursing queue entry not found in your hospital', 404)
        if entry.status != PatientQueueEntry.Status.CALLED or visit.state != _expected_state(entry):
            return _error('Patient must be called and remain in Nursing', 409)
        if entry.kind == PatientQueueEntry.Kind.NURSING_RETURN and not _tests_ready(visit):
            return _error('Test results are not ready', 409)
        active = PatientAttendance.objects.select_for_update().filter(visit=visit, released_at__isnull=True).first()
        if active:
            return _error('Patient is already being attended', 409)
        attendance = PatientAttendance.objects.create(visit=visit, department=entry.department, staff=member)
        response = {'detail': 'Nursing attendance started', 'attendance_id': attendance.pk, 'entry': _entry_data(entry)}
        if entry.kind == PatientQueueEntry.Kind.NURSING_INITIAL:
            assessment = NursingAssessment.objects.create(visit=visit, nurse=member)
            response['assessment'] = _assessment_data(assessment)
        return JsonResponse(response)


_FIELDS = {
    'blood_pressure': 'text', 'notes': 'text',
    'pulse_bpm': 'int', 'spo2_percent': 'int', 'respiratory_rate': 'int', 'pain_score': 'int',
    'temperature_c': 'decimal', 'height_cm': 'decimal', 'weight_kg': 'decimal',
}


def _parse_fields(body):
    unknown = set(body) - set(_FIELDS)
    if unknown:
        raise ValueError('Unknown assessment fields: ' + ', '.join(sorted(unknown)))
    parsed = {}
    for field, kind in _FIELDS.items():
        if field not in body:
            continue
        value = body[field]
        if value is None or value == '':
            parsed[field] = '' if kind == 'text' else None
        elif kind == 'text':
            if not isinstance(value, str):
                raise ValueError(f'{field} must be text')
            parsed[field] = value.strip()
        elif kind == 'int':
            if isinstance(value, bool) or not str(value).isdigit():
                raise ValueError(f'{field} must be a whole number')
            parsed[field] = int(value)
        else:
            try:
                parsed[field] = Decimal(str(value))
                if not parsed[field].is_finite():
                    raise ValueError()
            except (InvalidOperation, ValueError):
                raise ValueError(f'{field} must be a valid number')
    return parsed


@require_POST
def save_assessment(request, slug, entry_id):
    member = _nurse(request, slug)
    if member is None:
        return _error('Nursing login and 2FA required', 403)
    body = _json(request)
    if body is None:
        return _error('Expected a valid JSON object')
    try:
        values = _parse_fields(body)
    except ValueError as exc:
        return _error(str(exc))
    with transaction.atomic():
        visit, entry = _lock_entry(member, entry_id)
        if entry is None:
            return _error('Nursing queue entry not found in your hospital', 404)
        if entry.kind != PatientQueueEntry.Kind.NURSING_INITIAL:
            return _error('Vitals draft is available for initial Nursing only', 409)
        if entry.status != PatientQueueEntry.Status.CALLED or visit.state != PatientVisit.State.NURSING_INITIAL:
            return _error('Patient is not in an active Nursing stage', 409)
        active = PatientAttendance.objects.filter(visit=visit, released_at__isnull=True, department=entry.department).first()
        if active is None or active.staff_id != member.pk:
            return _error('Start the assessment as the attending nurse first', 409)
        assessment = NursingAssessment.objects.select_for_update().filter(
            visit=visit, nurse=member, completed_at__isnull=True
        ).order_by('-pk').first()
        if assessment is None:
            return _error('No active assessment found', 409)
        for field, value in values.items():
            setattr(assessment, field, value)
        try:
            assessment.full_clean()
        except ValidationError as exc:
            return JsonResponse({'detail': 'Invalid assessment values', 'errors': exc.message_dict}, status=400)
        assessment.save()
        return JsonResponse({'detail': 'Draft saved', 'assessment': _assessment_data(assessment)})


@require_POST
def complete_nursing(request, slug, entry_id):
    member = _nurse(request, slug)
    if member is None:
        return _error('Nursing login and 2FA required', 403)
    body = _json(request)
    if body is None or body.get('confirm_complete') is not True:
        return _error('Explicit confirmation required: {"confirm_complete": true}')
    with transaction.atomic():
        visit, entry = _lock_entry(member, entry_id)
        if entry is None:
            return _error('Nursing queue entry not found in your hospital', 404)
        if entry.status != PatientQueueEntry.Status.CALLED or visit.state != _expected_state(entry):
            return _error('Patient is not in an active Nursing stage', 409)
        active = PatientAttendance.objects.select_for_update().filter(visit=visit, released_at__isnull=True).first()
        if active is None or active.department_id != entry.department_id or active.staff_id != member.pk:
            return _error('Only the attending nurse can complete this stage', 409)
        if entry.kind == PatientQueueEntry.Kind.NURSING_RETURN and not _tests_ready(visit):
            return _error('All required test results must be ready', 409)
        doctor_department = visit.assigned_doctor.membership.department
        if (doctor_department is None or doctor_department.hospital_id != member.hospital_id
                or doctor_department.kind != Department.Kind.DOCTOR or not doctor_department.is_active):
            return _error('Assigned doctor has no active doctor department configured', 409)
        is_initial = entry.kind == PatientQueueEntry.Kind.NURSING_INITIAL
        if is_initial:
            assessment = NursingAssessment.objects.select_for_update().filter(
                visit=visit, nurse=member, completed_at__isnull=True
            ).order_by('-pk').first()
            if assessment is None:
                return _error('Initial Nursing assessment not found', 409)
        next_kind = PatientQueueEntry.Kind.DOCTOR_INITIAL if is_initial else PatientQueueEntry.Kind.DOCTOR_RECALL
        if PatientQueueEntry.objects.filter(visit=visit, kind=next_kind, status__in=[
            PatientQueueEntry.Status.WAITING, PatientQueueEntry.Status.CALLED,
        ]).exists():
            return _error('Doctor queue entry already exists', 409)
        now = timezone.now()
        if is_initial:
            assessment.completed_at = now
            assessment.released_to_doctor_at = now
            assessment.save(update_fields=['completed_at', 'released_to_doctor_at'])
        active.released_at = now
        active.save(update_fields=['released_at'])
        entry.status = PatientQueueEntry.Status.DONE
        entry.completed_at = now
        entry.save(update_fields=['status', 'completed_at'])
        old_state = visit.state
        visit.state = PatientVisit.State.DOCTOR_WAIT if is_initial else PatientVisit.State.DOCTOR_RECALL
        visit.save(update_fields=['state'])
        next_entry = PatientQueueEntry.objects.create(
            visit=visit, department=doctor_department, kind=next_kind,
            status=PatientQueueEntry.Status.WAITING,
        )
        PatientMovementEvent.objects.create(
            visit=visit, from_state=old_state, to_state=visit.state, actor=member,
            reason='Initial Nursing completed' if is_initial else 'Patient return confirmed after tests',
        )
        return JsonResponse({
            'detail': 'Nursing completed; patient sent to assigned doctor',
            'visit_id': visit.pk, 'state': visit.state,
            'doctor_queue_entry_id': next_entry.pk,
        })
