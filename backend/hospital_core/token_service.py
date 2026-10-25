"""Hospital-specific monthly public queue tokens.

Call allocate_queue_token(hospital) *inside the same transaction* that
creates PatientVisit, so an unsuccessful registration does not consume a token.
"""
import secrets
import string

from django.db import transaction
from django.utils import timezone

from .models import Hospital, HospitalMonthlyTokenCounter


def allocate_queue_token(hospital):
    """Return (token, month) for a hospital; e.g. ('K001', date(2026, 10, 1)).

    Must run within transaction.atomic() together with PatientVisit creation.
    PostgreSQL's hospital-row lock serializes first and later allocations for
    the same hospital, including when the counter row does not yet exist.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('allocate_queue_token must run inside transaction.atomic()')

    hospital_id = hospital.pk if isinstance(hospital, Hospital) else hospital
    locked_hospital = Hospital.objects.select_for_update().get(pk=hospital_id, is_active=True)
    today = timezone.localdate()
    month = today.replace(day=1)

    counter, _ = HospitalMonthlyTokenCounter.objects.get_or_create(
        hospital=locked_hospital,
        month=month,
        defaults={'prefix': secrets.choice(string.ascii_uppercase), 'last_number': 0},
    )
    # The hospital lock above serializes allocations, even on first use.
    counter.last_number += 1
    counter.save(update_fields=['last_number'])
    return f'{counter.prefix}{counter.last_number:03d}', month
