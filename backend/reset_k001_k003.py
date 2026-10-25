"""LOCAL TEST DATA ONLY. Preview first; set APPLY=True after reviewing output."""
from django.db import transaction
from django.utils import timezone
from hospital_core.models import (
    PatientVisit, PatientQueueEntry, PatientAttendance, TestOrderItem,
    TestResult, InvestigationReport, InvestigationReportValue,
    InvestigationReportRevision, InvestigationBill,
)

HOSPITAL = 'green-valley-hospital'
TARGETS = {1: 'K001', 3: 'K003'}
APPLY = False  # CHANGE TO True ONLY AFTER CHECKING THE PREVIEW

with transaction.atomic():
    visits = list(PatientVisit.objects.select_for_update().filter(
        hospital__slug=HOSPITAL, pk__in=TARGETS).order_by('pk'))
    assert len(visits) == len(TARGETS), 'Expected exactly two visits; no changes made.'
    for v in visits:
        assert v.queue_token == TARGETS[v.pk], 'Token mismatch; no changes made.'

    items = TestOrderItem.objects.select_for_update().filter(order__visit__in=visits)
    reports = InvestigationReport.objects.select_for_update().filter(item__in=items)
    final_reports = list(reports.exclude(status='DRAFT').values_list('pk', 'status'))
    existing_results = TestResult.objects.filter(item__in=items).count()
    print('Hospital:', HOSPITAL, 'Visits:', [(v.pk, v.queue_token) for v in visits])
    print('Investigation items:', list(items.values_list('pk', 'status')))
    print('Structured reports:', list(reports.values_list('pk', 'status')))
    print('Legacy test results:', existing_results)
    print('Investigation queue entries:', list(PatientQueueEntry.objects.filter(
        visit__in=visits, kind='TEST').values_list('pk', 'status')))
    print('Active attendance:', list(PatientAttendance.objects.filter(
        visit__in=visits, released_at__isnull=True).values_list('pk', 'department_id')))
    print('Investigation bills:', list(InvestigationBill.objects.filter(
        visit__in=visits).values_list('pk', 'status')))

    if final_reports or existing_results:
        raise RuntimeError('A report was finalized or legacy results exist. Refusing to reset clinical results: %s' % final_reports)

    if not APPLY:
        print('\nDRY RUN ONLY. No changes made. To reset, set APPLY=True in the script and rerun.')
    else:
        # Remove only unfinished draft reports and their dependent values/revisions.
        InvestigationReportValue.objects.filter(report__in=reports).delete()
        InvestigationReportRevision.objects.filter(report__in=reports).delete()
        reports.delete()
        items.update(status='WAITING', performed_at=None, report_ready_at=None)
        PatientQueueEntry.objects.filter(visit__in=visits, kind='TEST').update(
            status='WAITING', called_at=None, completed_at=None)
        # Do not rewrite historical attendance or patient movement events.
        # Only release active attendance belonging to investigation departments.
        active = PatientAttendance.objects.select_for_update().filter(
            visit__in=visits, released_at__isnull=True)
        if active.exclude(department__kind__in=['LAB','RADIOLOGY','ECG','OTHER']).exists():
            raise RuntimeError('Patient currently attending non-investigation department. Rolled back.')
        active.update(released_at=timezone.now())
        print('RESET COMPLETE: investigation tests and queues waiting. Original billing, nursing, doctor and patient details retained.')
