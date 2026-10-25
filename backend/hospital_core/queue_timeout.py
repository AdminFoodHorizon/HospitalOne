"""Expire unanswered calls without changing patients already under active care."""
from datetime import timedelta
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from .models import PatientQueueEntry, PatientAttendance

CALL_TIMEOUT = timedelta(minutes=5)
DOCTOR_KINDS = (
    PatientQueueEntry.Kind.DOCTOR_INITIAL,
    PatientQueueEntry.Kind.DOCTOR_RECALL,
)


def expire_unattended_calls(hospital=None):
    cutoff = timezone.now() - CALL_TIMEOUT
    active_attendance = PatientAttendance.objects.filter(
        visit_id=OuterRef('visit_id'), released_at__isnull=True
    )
    with transaction.atomic():
        queryset = PatientQueueEntry.objects.filter(
            status=PatientQueueEntry.Status.CALLED,
            called_at__isnull=False,
            called_at__lte=cutoff,
        ).annotate(_attended=Exists(active_attendance)).filter(_attended=False)
        if hospital is not None:
            queryset = queryset.filter(visit__hospital=hospital)
        doctors = queryset.filter(kind__in=DOCTOR_KINDS).update(
            status=PatientQueueEntry.Status.RECALL_PENDING,
            called_at=None,
        )
        nursing_and_other = queryset.exclude(kind__in=DOCTOR_KINDS).update(
            status=PatientQueueEntry.Status.WAITING,
            called_at=None,
        )
    return doctors + nursing_and_other
