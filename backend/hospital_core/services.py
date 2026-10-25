"""Atomic attendance primitives for PostgreSQL-backed patient movement.

All entry points must enforce authenticated staff roles, same-hospital scope,
valid queue state and allowed transitions before calling these primitives.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import PatientAttendance, PatientVisit


@transaction.atomic
def claim_patient(*, visit_id, department, staff):
    visit = PatientVisit.objects.select_for_update().get(pk=visit_id)
    if not visit.hospital.is_active or not staff.is_active:
        raise ValidationError('Hospital or staff membership is inactive.')
    if department.hospital_id != visit.hospital_id or staff.hospital_id != visit.hospital_id:
        raise ValidationError('Cross-hospital patient attendance is forbidden.')
    if visit.state in (PatientVisit.State.COMPLETE, PatientVisit.State.CANCELLED):
        raise ValidationError('Visit is closed.')
    if PatientAttendance.objects.filter(visit=visit, released_at__isnull=True).exists():
        raise ValidationError('Patient is already attending another department.')
    # The database partial unique constraint protects against competing callers.
    return PatientAttendance.objects.create(visit=visit, department=department, staff=staff)


@transaction.atomic
def release_patient(*, attendance_id, staff):
    attendance = PatientAttendance.objects.select_related('visit').select_for_update().get(pk=attendance_id)
    # Lock the parent visit too, serializing with concurrent claim requests.
    PatientVisit.objects.select_for_update().get(pk=attendance.visit_id)
    if staff.hospital_id != attendance.visit.hospital_id:
        raise ValidationError('Cross-hospital release forbidden.')
    if attendance.released_at is not None:
        raise ValidationError('Patient has already been released.')
    if attendance.staff_id != staff.pk:
        raise ValidationError('Only the claiming staff member may release this attendance.')
    attendance.released_at = timezone.now()
    attendance.save(update_fields=['released_at'])
    return attendance
