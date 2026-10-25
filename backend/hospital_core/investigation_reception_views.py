"""Reception investigation price summary and routing; no payment processing."""
from datetime import timedelta
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from .models import (InvestigationBill, PatientVisit, PatientQueueEntry,
                     PatientAttendance, AnnouncementEvent, Department, PatientMovementEvent)
from .reception_views import reception_member


def _serialize(bill):
    visit = bill.visit
    return {
        'id': bill.pk, 'bill_number': bill.bill_number, 'status': bill.status,
        'created_at': bill.created_at.isoformat(), 'released_at': bill.released_at.isoformat() if bill.released_at else None,
        'currency': bill.currency, 'total_amount': str(bill.total_amount),
        'queue_entry_id': bill.reception_queue_entry_id,
        'queue_status': bill.reception_queue_entry.status if bill.reception_queue_entry_id else None,
        'called_at': bill.reception_queue_entry.called_at.isoformat() if bill.reception_queue_entry_id and bill.reception_queue_entry.called_at else None,
        'visit_id': visit.pk, 'token': visit.queue_token or visit.visit_number,
        'patient_name': visit.patient.full_name, 'patient_number': visit.patient.patient_number,
        'lines': [{'test_code': x.test_code, 'test_name': x.test_name, 'department_name': x.department_name, 'amount': str(x.amount)} for x in bill.lines.all()],
    }


def _bill(hospital_id, bill_id, lock=False):
    qs = InvestigationBill.objects.filter(pk=bill_id, hospital_id=hospital_id).select_related(
        'visit__patient', 'reception_queue_entry', 'hospital'
    ).prefetch_related('lines')
    return (qs.select_for_update(of=('self',)) if lock else qs).first()


@require_GET
def bills(request, slug):
    member = reception_member(request, slug)
    if not member: return JsonResponse({'detail': 'Reception login and 2FA required.'}, status=403)
    qs = InvestigationBill.objects.filter(hospital_id=member.hospital_id).select_related(
        'visit__patient', 'reception_queue_entry'
    ).prefetch_related('lines').order_by('-created_at', '-pk')[:150]
    return JsonResponse({'bills': [_serialize(x) for x in qs]})


@require_POST
def call(request, slug, bill_id):
    member = reception_member(request, slug)
    if not member: return JsonResponse({'detail': 'Reception login and 2FA required.'}, status=403)
    with transaction.atomic():
        ref = InvestigationBill.objects.filter(pk=bill_id, hospital_id=member.hospital_id).values('visit_id').first()
        if not ref: return JsonResponse({'detail': 'Bill not found.'}, status=404)
        PatientVisit.objects.select_for_update().get(pk=ref['visit_id'])
        bill = _bill(member.hospital_id, bill_id, True)
        entry = bill.reception_queue_entry
        if bill.status != InvestigationBill.Status.WAITING_RECEPTION or not entry:
            return JsonResponse({'detail': 'Bill is not awaiting Reception.'}, status=409)
        entry = PatientQueueEntry.objects.select_for_update().get(pk=entry.pk)
        if entry.status not in (PatientQueueEntry.Status.WAITING, PatientQueueEntry.Status.RECALL_PENDING):
            return JsonResponse({'detail': 'Patient is already called or processed.'}, status=409)
        if PatientAttendance.objects.filter(visit=bill.visit, released_at__isnull=True).exists():
            return JsonResponse({'detail': 'Patient is currently being attended.'}, status=409)
        if PatientQueueEntry.objects.filter(visit=bill.visit, status=PatientQueueEntry.Status.CALLED).exclude(pk=entry.pk).exists():
            return JsonResponse({'detail': 'Patient is called at another department.'}, status=409)
        now = timezone.now()
        entry.status = PatientQueueEntry.Status.CALLED; entry.called_at = now
        entry.save(update_fields=['status', 'called_at'])
        AnnouncementEvent.objects.create(
            hospital=member.hospital, queue_entry=entry, called_by=member,
            token=bill.visit.queue_token or bill.visit.visit_number,
            department_name=entry.department.name,
            room_number=entry.department.room_number or 'Reception', called_at=now,
        )
    return JsonResponse({'detail': 'Patient announced on Central TV.', 'called_at': now.isoformat()})


@require_POST
def recall_pending(request, slug, bill_id):
    member = reception_member(request, slug)
    if not member: return JsonResponse({'detail': 'Reception login and 2FA required.'}, status=403)
    with transaction.atomic():
        ref = InvestigationBill.objects.filter(pk=bill_id, hospital_id=member.hospital_id).values('visit_id').first()
        if not ref: return JsonResponse({'detail': 'Bill not found.'}, status=404)
        PatientVisit.objects.select_for_update().get(pk=ref['visit_id'])
        bill = _bill(member.hospital_id, bill_id, True)
        entry = bill.reception_queue_entry
        if bill.status != InvestigationBill.Status.WAITING_RECEPTION or not entry or entry.status != PatientQueueEntry.Status.CALLED:
            return JsonResponse({'detail': 'Patient must be called before moving to recall pending.'}, status=409)
        entry.status = PatientQueueEntry.Status.RECALL_PENDING
        entry.save(update_fields=['status'])
    return JsonResponse({'detail': 'Patient moved to Recall Pending.'})


@require_POST
def release(request, slug, bill_id):
    member = reception_member(request, slug)
    if not member: return JsonResponse({'detail': 'Reception login and 2FA required.'}, status=403)
    with transaction.atomic():
        ref = InvestigationBill.objects.filter(pk=bill_id, hospital_id=member.hospital_id).values('visit_id').first()
        if not ref: return JsonResponse({'detail': 'Bill not found.'}, status=404)
        visit = PatientVisit.objects.select_for_update().get(pk=ref['visit_id'])
        bill = _bill(member.hospital_id, bill_id, True)
        entry = bill.reception_queue_entry
        if bill.status != InvestigationBill.Status.WAITING_RECEPTION or not entry:
            return JsonResponse({'detail': 'Bill already released or cancelled.'}, status=409)
        if entry.status != PatientQueueEntry.Status.CALLED:
            return JsonResponse({'detail': 'Call the patient before sending to investigations.'}, status=409)
        if visit.state != PatientVisit.State.TEST_POOL:
            return JsonResponse({'detail': 'Visit is not in the investigation stage.'}, status=409)
        if PatientAttendance.objects.filter(visit=visit, released_at__isnull=True).exists():
            return JsonResponse({'detail': 'Patient is currently being attended.'}, status=409)
        items = list(bill.test_order.items.select_related('test__department'))
        if not items: return JsonResponse({'detail': 'No investigations on this bill.'}, status=409)
        departments = {x.test.department_id: x.test.department for x in items}
        if any(d.hospital_id != member.hospital_id or not d.is_active for d in departments.values()):
            return JsonResponse({'detail': 'One or more investigation departments are unavailable.'}, status=409)
        if PatientQueueEntry.objects.filter(visit=visit, kind=PatientQueueEntry.Kind.TEST).exclude(status=PatientQueueEntry.Status.CANCELLED).exists():
            return JsonResponse({'detail': 'Investigation queue entries already exist. Contact an administrator.'}, status=409)
        PatientQueueEntry.objects.bulk_create([
            PatientQueueEntry(visit=visit, department_id=dept_id,
                              kind=PatientQueueEntry.Kind.TEST, status=PatientQueueEntry.Status.WAITING)
            for dept_id in departments
        ])
        now = timezone.now()
        entry.status = PatientQueueEntry.Status.DONE; entry.completed_at = now
        entry.save(update_fields=['status', 'completed_at'])
        bill.status = InvestigationBill.Status.RELEASED; bill.released_at = now; bill.released_by = member
        bill.save(update_fields=['status', 'released_at', 'released_by'])
        PatientMovementEvent.objects.create(visit=visit, from_state=visit.state, to_state=visit.state,
                                             actor=member, reason='Reception released investigation queues')
    return JsonResponse({'detail': 'Patient sent to investigation departments.'})
