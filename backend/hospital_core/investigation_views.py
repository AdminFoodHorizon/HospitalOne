"""Hospital-scoped shared investigation queue and report workflow."""
import json
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from .views import require_staff
from .models import (
    StaffMembership, Department, PatientQueueEntry, PatientVisit, TestOrderItem,
    TestResult, AnnouncementEvent, InvestigationBill, PatientMovementEvent,
    PatientAttendance, InvestigationReport,
)

def allowed(request, slug):
    member = require_staff(request, slug)
    if not member:
        return None
    if member.role == StaffMembership.Role.ADMIN:
        return member
    if (member.role == StaffMembership.Role.LAB and member.department_id
            and member.department and member.department.is_active
            and member.department.kind in ('LAB', 'RADIOLOGY', 'ECG', 'OTHER')):
        return member
    return None

def departments(member):
    qs = Department.objects.filter(hospital_id=member.hospital_id, is_active=True).filter(
        kind__in=['LAB', 'RADIOLOGY', 'ECG', 'OTHER'])
    if member.role != StaffMembership.Role.ADMIN:
        qs = qs.filter(pk=member.department_id)
    return qs

def error(message, status=400):
    return JsonResponse({'detail': message}, status=status)

def entry_qs(member):
    return PatientQueueEntry.objects.filter(
        visit__hospital_id=member.hospital_id, department_id__in=departments(member).values('pk'),
        kind=PatientQueueEntry.Kind.TEST
    )

def item_qs(entry):
    # A queue entry is per visit and department. Only released bills qualify.
    return TestOrderItem.objects.filter(
        order__visit_id=entry.visit_id, test__department_id=entry.department_id,
        order__investigation_bill__status=InvestigationBill.Status.RELEASED
    ).select_related('test').order_by('id')

def serialize(entry):
    items = list(item_qs(entry))
    reports = {r.item_id: r.status for r in InvestigationReport.objects.filter(item_id__in=[i.pk for i in items])}
    active = PatientAttendance.objects.filter(visit_id=entry.visit_id, released_at__isnull=True).select_related('department').first()
    physical = ('ATTENDING' if active and active.department_id == entry.department_id else
                'BUSY_ELSEWHERE' if active else 'WAITING')
    return {
        'id': entry.pk, 'token': entry.visit.queue_token or '',
        'patient_name': entry.visit.patient.full_name,
        'department': entry.department.name, 'department_id': entry.department_id,
        'room_number': entry.department.room_number,
        'status': entry.status, 'queued_at': entry.queued_at.isoformat(),
        'physical_status': physical,
        'busy_department': active.department.name if active and physical == 'BUSY_ELSEWHERE' else '',
        'visit_state': entry.visit.state,
        'items': [{'id': item.pk, 'name': item.test.name, 'code': item.test.code,
                   'status': item.status, 'report_status': reports.get(item.pk, 'NOT_STARTED'),
                   'summary': getattr(item.result, 'summary', '')
                   if hasattr(item, 'result') else ''}
                  for item in items],
    }

@require_GET
def queue(request, slug):
    member = allowed(request, slug)
    if not member: return error('Investigation staff login and 2FA required.', 403)
    entries = (entry_qs(member).select_related('visit__patient', 'department')
               .exclude(status__in=['CANCELLED'])
               .order_by('-queued_at', '-pk')[:300])
    active = []
    for entry in entries:
        data = serialize(entry)
        items = data['items']
        # DONE means physical release, not necessarily that reports are final.
        # Keep report-pending work; remove only fully completed/cancelled rows.
        if items and all(i['status'] in ('REPORT_READY', 'CANCELLED') for i in items):
            continue
        if items and all(i['status'] == 'CANCELLED' for i in items):
            continue
        if not items and entry.status == 'DONE':
            continue
        active.append(data)
        if len(active) >= 150:
            break
    return JsonResponse({'departments': [{'id': d.pk, 'name': d.name} for d in departments(member)],
                         'entries': active})

def lock_entry(member, entry_id):
    # Lock only queue row, avoiding nullable outer join FOR UPDATE failures.
    return entry_qs(member).select_for_update(of=('self',)).filter(pk=entry_id).first()

@require_POST
def call(request, slug, entry_id):
    member = allowed(request, slug)
    if not member: return error('Investigation staff login and 2FA required.', 403)
    with transaction.atomic():
        entry = lock_entry(member, entry_id)
        if not entry: return error('Queue entry not found.', 404)
        # Serialize calls per visit so two departments cannot claim the same patient.
        PatientVisit.objects.select_for_update().get(pk=entry.visit_id)
        if entry.visit.state != PatientVisit.State.TEST_POOL:
            return error('Patient is not currently in the investigation stage.', 409)
        if PatientAttendance.objects.filter(visit_id=entry.visit_id, released_at__isnull=True).exists():
            return error('Patient is currently attending another department.', 409)
        if PatientQueueEntry.objects.filter(visit_id=entry.visit_id, kind=PatientQueueEntry.Kind.TEST,
                status='CALLED').exclude(pk=entry.pk).exists():
            return error('Patient is already called by another investigation department.', 409)
        if entry.status not in ('WAITING', 'RECALL_PENDING'):
            return error('Only waiting or recall-pending patients can be called.', 409)
        if not item_qs(entry).exclude(status__in=['REPORT_READY', 'CANCELLED']).exists():
            return error('No pending investigations for this department.', 409)
        if not entry.visit.queue_token:
            return error('Patient queue token is missing.', 409)
        entry.status = 'CALLED'
        entry.called_at = timezone.now()
        entry.save(update_fields=['status', 'called_at'])
        AnnouncementEvent.objects.create(
            hospital_id=member.hospital_id, queue_entry=entry, called_by=member,
            token=entry.visit.queue_token, department_name=entry.department.name,
            room_number=entry.department.room_number or '')
    return JsonResponse({'detail': 'Patient announced on Central TV.'})

@require_POST
def recall_pending(request, slug, entry_id):
    member = allowed(request, slug)
    if not member: return error('Investigation staff login and 2FA required.', 403)
    with transaction.atomic():
        entry = lock_entry(member, entry_id)
        if not entry: return error('Queue entry not found.', 404)
        if entry.status != 'CALLED': return error('Call the patient first.', 409)
        PatientVisit.objects.select_for_update().get(pk=entry.visit_id)
        if PatientAttendance.objects.filter(visit_id=entry.visit_id, department_id=entry.department_id,
                released_at__isnull=True).exists():
            return error('Complete testing and release the patient first.', 409)
        entry.status = 'RECALL_PENDING'
        entry.save(update_fields=['status'])
    return JsonResponse({'detail': 'Patient moved to recall pending.'})

@require_POST
def start(request, slug, entry_id):
    member = allowed(request, slug)
    if not member: return error('Investigation staff login and 2FA required.', 403)
    with transaction.atomic():
        entry = lock_entry(member, entry_id)
        if not entry: return error('Queue entry not found.', 404)
        PatientVisit.objects.select_for_update().get(pk=entry.visit_id)
        if entry.status != 'CALLED': return error('Call patient before starting investigations.', 409)
        if entry.visit.state != PatientVisit.State.TEST_POOL:
            return error('Patient is not currently in the investigation stage.', 409)
        if PatientAttendance.objects.filter(visit_id=entry.visit_id, released_at__isnull=True).exists():
            return error('Patient is already attending a department.', 409)
        items = list(item_qs(entry).select_for_update(of=('self',)))
        if not items: return error('No released tests for this department.', 409)
        # Supports legacy records where IN_PROGRESS was set by older code without attendance.
        if not any(item.status in ('WAITING', 'IN_PROGRESS') for item in items):
            return error('No tests requiring patient attendance.', 409)
        PatientAttendance.objects.create(visit=entry.visit, department=entry.department, staff=member)
        for item in items:
            if item.status == 'WAITING':
                item.status = 'IN_PROGRESS'
                item.save(update_fields=['status'])
    return JsonResponse({'detail': 'Investigation started.'})

@require_POST
def save_result(request, slug, item_id):
    """Do not permit the legacy endpoint to bypass review and verification."""
    member = allowed(request, slug)
    if not member:
        return error('Investigation staff login and 2FA required.', 403)
    return error('Use Enter Results, Save Draft and Complete Test for structured verification.', 409)


@require_POST
def release_patient(request, slug, entry_id):
    """Release physical attendance only; performed procedures remain report-pending."""
    member = allowed(request, slug)
    if not member:
        return error('Investigation staff login and 2FA required.', 403)
    with transaction.atomic():
        entry = lock_entry(member, entry_id)
        if not entry:
            return error('Queue entry not found.', 404)
        PatientVisit.objects.select_for_update().get(pk=entry.visit_id)
        attendance = (PatientAttendance.objects.select_for_update()
                      .filter(visit_id=entry.visit_id, department_id=entry.department_id,
                              released_at__isnull=True).first())
        if not attendance:
            return error('Press Start Test after the patient arrives before releasing.', 409)
        if entry.status != 'CALLED':
            return error('Patient is not in a called investigation session.', 409)
        items = list(item_qs(entry).select_for_update(of=('self',)))
        if not items or not any(i.status == 'IN_PROGRESS' for i in items):
            return error('No active tests to release.', 409)
        now = timezone.now()
        for item in items:
            if item.status == 'IN_PROGRESS':
                item.status = 'PERFORMED'
                item.performed_at = item.performed_at or now
                item.save(update_fields=['status', 'performed_at'])
        attendance.released_at = now
        attendance.save(update_fields=['released_at'])
        # This queue is physically finished. Its reports may still be pending.
        if any(i.status == 'WAITING' for i in items):
            entry.status = 'WAITING'
            entry.completed_at = None
        else:
            entry.status = 'DONE'
            entry.completed_at = now
        entry.save(update_fields=['status', 'completed_at'])
        PatientMovementEvent.objects.create(
            visit_id=entry.visit_id, from_state='TEST_ATTENDING', to_state='TEST_POOL',
            actor=member, reason=f'Released from investigation department {entry.department_id}; reports pending')
    return JsonResponse({'detail': 'Patient released and eligible for other pending departments. '
                                   'Reports are NOT completed.', 'patient_released': True})

# Backward-compatible route, but its semantics are patient release, not report completion.
complete_testing = release_patient


@require_GET
def completed_reports(request, slug):
    """Hospital and department-scoped finalized report archive, paginated."""
    from datetime import datetime, time
    from django.utils.dateparse import parse_date
    member = allowed(request, slug)
    if not member:
        return error('Investigation staff login and 2FA required.', 403)
    try:
        page = max(1, int(request.GET.get('page', '1')))
        if page > 100000: return error('Invalid page.', 400)
    except (ValueError, TypeError):
        return error('Invalid page.', 400)
    start_raw = request.GET.get('from', '').strip()
    end_raw = request.GET.get('to', '').strip()
    start = parse_date(start_raw) if start_raw else None
    end = parse_date(end_raw) if end_raw else None
    if (start_raw and start is None) or (end_raw and end is None):
        return error('Dates must use YYYY-MM-DD.', 400)
    if start and end and start > end:
        return error('From date must be before To date.', 400)
    qs = (InvestigationReport.objects.filter(
        item__order__visit__hospital_id=member.hospital_id,
        item__test__department_id__in=departments(member).values('pk'),
        status=InvestigationReport.Status.FINAL,
        item__status='REPORT_READY', verified_at__isnull=False,
    ).select_related('item__test__department', 'item__order__visit__patient', 'verified_by__user')
      .order_by('-verified_at', '-pk'))
    if start:
        qs = qs.filter(verified_at__date__gte=start)
    if end:
        qs = qs.filter(verified_at__date__lte=end)
    search = request.GET.get('q', '').strip()[:100]
    if search:
        qs = qs.filter(Q(item__order__visit__queue_token__icontains=search) |
                       Q(item__order__visit__patient__full_name__icontains=search) |
                       Q(item__test__name__icontains=search))
    total = qs.count()
    limit = 25
    rows = []
    for r in qs[(page-1)*limit:page*limit]:
        visit = r.item.order.visit
        rows.append({
            'report_id': r.pk, 'item_id': r.item_id,
            'token': visit.queue_token or '', 'patient_name': visit.patient.full_name,
            'department_id': r.item.test.department_id,
            'department': r.item.test.department.name,
            'test_name': r.item.test.name,
            'completed_at': r.verified_at.isoformat(),
            'pdf_url': f'/api/hospital/{slug}/investigations/items/{r.item_id}/structured-report/pdf/',
        })
    return JsonResponse({'results': rows, 'total': total, 'page': page,
                         'page_size': limit, 'has_next': page*limit < total})
