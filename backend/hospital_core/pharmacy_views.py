"""Hospital-scoped dispensing. Prescribed items are immutable to pharmacists."""
import json
from decimal import Decimal
from django.db import transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from .models import (Hospital, StaffMembership, PatientVisit, PatientQueueEntry,
    PrescriptionItem, PharmacyDispense, PharmacyDispenseLine, DispenseRecord,
    PatientMovementEvent)
from .views import require_staff
from .models import ReceptionReportEmailReceipt
from .models import TestOrderItem, InvestigationReport


def _member(request, slug, reception=False):
    member = require_staff(request, slug)
    roles = (StaffMembership.Role.RECEPTION, StaffMembership.Role.ADMIN) if reception else (StaffMembership.Role.PHARMACY, StaffMembership.Role.ADMIN)
    return member if member and member.role in roles and member.hospital.is_active else None


def _err(message, code=400):
    return JsonResponse({'detail': message}, status=code)


def _hospital(member):
    h = member.hospital
    return {'name': h.name, 'logo': h.logo.url if h.logo else None,
            'address': ', '.join(filter(None, [h.address_line1, h.address_line2, h.city, h.state, h.postal_code, h.country])),
            'phone': h.phone, 'email': h.email, 'currency': h.billing_currency}


def _visit(v):
    return {'id': v.pk, 'visit_number': v.visit_number, 'queue_token': v.queue_token,
            'patient': {'name': v.patient.full_name, 'number': v.patient.patient_number},
            'doctor': v.assigned_doctor.membership.user.get_full_name() or v.assigned_doctor.membership.user.username,
            'state': v.state, 'registered_at': v.registered_at.isoformat()}


def _items(v):
    return list(PrescriptionItem.objects.filter(prescription__visit=v)
                .select_related('medicine').order_by('pk'))


def _bill(d):
    return {'id': d.pk, 'bill_number': d.bill_number, 'finalized_at': d.finalized_at.isoformat(),
            'currency': d.currency, 'total': str(d.total_amount),
            'lines': [{'item_id': x.prescription_item_id, 'medicine': x.medicine_name,
                       'code': x.medicine_code, 'prescribed_quantity': x.prescribed_quantity,
                       'quantity': x.dispensed_quantity, 'unit_price': str(x.unit_price),
                       'total': str(x.line_total), 'dose': x.dose, 'route': x.route,
                       'frequency': x.frequency, 'duration': x.duration, 'instructions': x.instructions}
                      for x in d.lines.all()]}


@require_GET
def queue(request, slug):
    member = _member(request, slug)
    if not member: return _err('Pharmacy staff authentication and 2FA required', 403)
    qs = (PatientVisit.objects.filter(hospital_id=member.hospital_id, state=PatientVisit.State.PHARMACY, pharmacy_dispense__isnull=True)
          .select_related('patient', 'assigned_doctor__membership__user').order_by('registered_at', 'pk')[:250])
    return JsonResponse({'hospital': _hospital(member), 'results': [_visit(v) for v in qs]})


@require_GET
def detail(request, slug, visit_id):
    member = _member(request, slug)
    if not member: return _err('Pharmacy staff authentication and 2FA required', 403)
    v = PatientVisit.objects.filter(pk=visit_id, hospital_id=member.hospital_id).select_related('patient', 'assigned_doctor__membership__user').first()
    if not v: return _err('Visit not found', 404)
    if v.state != PatientVisit.State.PHARMACY and not PharmacyDispense.objects.filter(visit=v).exists():
        return _err('Visit is not in pharmacy workflow', 409)
    items = _items(v)
    d = PharmacyDispense.objects.prefetch_related('lines').filter(visit=v).first()
    return JsonResponse({'hospital': _hospital(member), 'visit': _visit(v),
        'items': [{'id': i.pk, 'medicine': i.medicine.name, 'code': i.medicine.code,
                   'quantity': i.quantity, 'unit_price': str(i.medicine.unit_price) if i.medicine.unit_price is not None else None,
                   'dose': i.dose, 'route': i.route, 'frequency': i.frequency,
                   'duration': i.duration, 'instructions': i.instructions}
                  for i in items], 'bill': _bill(d) if d else None})


@require_POST
def finalize(request, slug, visit_id):
    member = _member(request, slug)
    if not member: return _err('Pharmacy staff authentication and 2FA required', 403)
    try:
        payload = json.loads(request.body or b'{}')
        quantities = payload['quantities']
        if not isinstance(quantities, dict): raise ValueError()
    except (ValueError, KeyError, TypeError):
        return _err('Send a quantities object keyed by prescription item ID')
    with transaction.atomic():
        v = (PatientVisit.objects.select_for_update(of=('self',)).filter(pk=visit_id, hospital_id=member.hospital_id).first())
        if not v: return _err('Visit not found', 404)
        if v.state != PatientVisit.State.PHARMACY: return _err('Visit is not awaiting pharmacy dispensing', 409)
        if PharmacyDispense.objects.filter(visit=v).exists(): return _err('Dispensing already finalized', 409)
        items = _items(v)
        if not items: return _err('No doctor prescription found', 409)
        expected = {str(i.pk) for i in items}
        if set(quantities) != expected: return _err('Quantities must cover exactly the prescribed medicines', 400)
        totals = []
        for item in items:
            qty = quantities[str(item.pk)]
            if type(qty) is not int or qty < 0 or qty > item.quantity:
                return _err(f'Invalid dispensed quantity for {item.medicine.name}. Allowed: 0–{item.quantity}')
            if item.medicine.hospital_id != member.hospital_id: return _err('Cross-hospital medicine detected', 409)
            if item.medicine.unit_price is None: return _err(f'Set hospital catalog price for {item.medicine.name} first', 409)
            totals.append((item, qty, item.medicine.unit_price * qty))
        d = PharmacyDispense.objects.create(visit=v, pharmacist=member,
             currency=member.hospital.billing_currency, total_amount=sum((t[2] for t in totals), Decimal('0.00')),
             bill_number=f'PH-{member.hospital_id}-{v.pk:08d}')
        for item, qty, total in totals:
            PharmacyDispenseLine.objects.create(dispense=d, prescription_item=item,
                medicine_code=item.medicine.code, medicine_name=item.medicine.name,
                prescribed_quantity=item.quantity, dispensed_quantity=qty,
                unit_price=item.medicine.unit_price, line_total=total,
                dose=item.dose, route=item.route, frequency=item.frequency,
                duration=item.duration, instructions=item.instructions)
            if qty: DispenseRecord.objects.create(item=item, pharmacist=member, quantity=qty)
        PatientQueueEntry.objects.filter(visit=v, kind=PatientQueueEntry.Kind.PHARMACY,
            status__in=[PatientQueueEntry.Status.WAITING, PatientQueueEntry.Status.CALLED, PatientQueueEntry.Status.RECALL_PENDING]).update(
            status=PatientQueueEntry.Status.DONE, completed_at=timezone.now())
        PatientMovementEvent.objects.create(visit=v, from_state=v.state, to_state=v.state,
            actor=member, reason='Pharmacy dispensing finalized; awaiting Reception discharge')
    return JsonResponse({'detail': 'Pharmacy dispensing finalized; Reception can now review discharge.', 'bill': _bill(PharmacyDispense.objects.prefetch_related('lines').get(pk=d.pk))})


@require_GET
def reception_queue(request, slug):
    member = _member(request, slug, reception=True)
    if not member: return _err('Reception staff authentication and 2FA required', 403)
    qs = (PatientVisit.objects.filter(hospital_id=member.hospital_id, state=PatientVisit.State.PHARMACY,
                                     pharmacy_dispense__isnull=False)
          .select_related('patient', 'assigned_doctor__membership__user', 'pharmacy_dispense')
          .order_by('pharmacy_dispense__finalized_at', 'pk')[:250])
    return JsonResponse({'hospital': _hospital(member), 'results': [_visit(v) for v in qs]})


def _full_summary(member, visit):
    """Hospital-isolated read-only clinical and dispensing summary."""
    from .models import (Consultation, TestOrderItem, InvestigationReport,
                         NursingAssessment, PatientMovementEvent, PrescriptionItem)
    from .patient_intake_models import PatientIntake
    intake = PatientIntake.objects.filter(patient=visit.patient).first()
    consultations = Consultation.objects.filter(visit=visit).select_related(
        'doctor__membership__user', 'doctor__membership__department').order_by('started_at', 'pk')
    investigations = TestOrderItem.objects.filter(order__visit=visit).select_related(
        'test', 'structured_report').order_by('pk')
    medications = PrescriptionItem.objects.filter(prescription__visit=visit).select_related(
        'medicine', 'prescription').order_by('pk')
    nursing = NursingAssessment.objects.filter(visit=visit).order_by('pk')
    movements = PatientMovementEvent.objects.filter(visit=visit).select_related('actor__user').order_by('created_at', 'pk')
    d = PharmacyDispense.objects.prefetch_related('lines').filter(visit=visit).first()
    reports = []
    for item in investigations:
        report = getattr(item, 'structured_report', None)
        released = bool(report and report.status in (InvestigationReport.Status.FINAL, InvestigationReport.Status.AMENDED)
                        and report.verified_at and report.verified_by_id)
        reports.append({'item_id': item.pk, 'test_name': item.test.name, 'status': item.status,
                        'ordered_at': item.order.ordered_at.isoformat(),
                        'performed_at': item.performed_at.isoformat() if item.performed_at else None,
                        'report_ready_at': item.report_ready_at.isoformat() if item.report_ready_at else None,
                        'released': released,
                         'email_accepted': bool(released and ReceptionReportEmailReceipt.objects.filter(hospital_id=member.hospital_id, item_id=item.pk, report_id=report.pk, report_verified_at=report.verified_at, recipient_email__iexact=(intake.email.strip() if intake else '')).exists()),
                        'findings': report.findings if released else None,
                        'impression': report.impression if released else None,
                        'recommendations': report.recommendations if released else None})
    return {
        'hospital': _hospital(member), 'visit': _visit(visit),
        'patient': {'id': visit.patient_id, 'number': visit.patient.patient_number,
                    'name': visit.patient.full_name,
                    'date_of_birth': visit.patient.date_of_birth.isoformat() if visit.patient.date_of_birth else None,
                    'phone': intake.phone if intake else '', 'email': intake.email if intake else '',
                    'sex': intake.sex if intake else '', 'address': intake.address if intake else '',
                    'allergies': intake.allergies if intake else '',
                    'current_medications': intake.current_medications if intake else '',
                    'medical_history': intake.medical_history if intake else ''},
        'consultations': [{'id': c.pk, 'doctor': c.doctor.membership.user.get_full_name() or c.doctor.membership.user.username,
                           'department': c.doctor.membership.department.name if c.doctor.membership.department_id else None,
                           'started_at': c.started_at.isoformat(), 'ended_at': c.ended_at.isoformat() if c.ended_at else None,
                           'diagnosis': c.diagnosis, 'notes': c.notes, 'status': c.status} for c in consultations],
        'nursing': [{'completed_at': n.completed_at.isoformat() if n.completed_at else None,
                     'blood_pressure': n.blood_pressure, 'pulse_bpm': n.pulse_bpm,
                     'temperature_c': str(n.temperature_c) if n.temperature_c is not None else None,
                     'spo2_percent': n.spo2_percent, 'respiratory_rate': n.respiratory_rate,
                     'height_cm': str(n.height_cm) if n.height_cm is not None else None,
                     'weight_kg': str(n.weight_kg) if n.weight_kg is not None else None,
                     'pain_score': n.pain_score, 'notes': n.notes} for n in nursing],
        'investigations': reports,
        'prescriptions': [{'medicine': i.medicine.name, 'code': i.medicine.code,
                           'prescribed_at': i.prescription.prescribed_at.isoformat(),
                           'dose': i.dose, 'route': i.route, 'frequency': i.frequency,
                           'duration': i.duration, 'quantity': i.quantity, 'instructions': i.instructions}
                          for i in medications],
        'bill': _bill(d) if d else None,
        'timeline': [{'at': m.created_at.isoformat(), 'from': m.from_state, 'to': m.to_state,
                      'reason': m.reason, 'actor': m.actor.user.get_full_name() or m.actor.user.username}
                     for m in movements],
        'completed_at': visit.completed_at.isoformat() if visit.completed_at else None,
    }


@require_GET
def reception_summary(request, slug, visit_id):
    member = _member(request, slug, reception=True)
    if not member: return _err('Reception staff authentication and 2FA required', 403)
    v = PatientVisit.objects.filter(pk=visit_id, hospital_id=member.hospital_id,
         pharmacy_dispense__isnull=False).select_related('patient', 'assigned_doctor__membership__user').first()
    if not v: return _err('Finalized pharmacy case not found', 404)
    return JsonResponse(_full_summary(member, v))


@require_GET
def reception_patient_history(request, slug):
    member = _member(request, slug, reception=True)
    if not member: return _err('Reception staff authentication and 2FA required', 403)
    from .models import Patient
    q = request.GET.get('q', '').strip()
    if len(q) < 2 or len(q) > 100: return _err('Enter 2 to 100 characters')
    from django.db.models import Q
    matches = (Patient.objects.filter(hospital_id=member.hospital_id)
               .filter(Q(patient_number__icontains=q) | Q(full_name__icontains=q) |
                       Q(intake__phone__icontains=q)).distinct().order_by('full_name', 'pk')[:30])
    return JsonResponse({'results': [{'id': p.pk, 'number': p.patient_number,
                                    'name': p.full_name} for p in matches]})


@require_GET
def reception_patient_visits(request, slug, patient_id):
    member = _member(request, slug, reception=True)
    if not member: return _err('Reception staff authentication and 2FA required', 403)
    from .models import Patient
    if not Patient.objects.filter(pk=patient_id, hospital_id=member.hospital_id).exists():
        return _err('Patient not found in this hospital', 404)
    visits = (PatientVisit.objects.filter(patient_id=patient_id, hospital_id=member.hospital_id)
              .select_related('patient', 'assigned_doctor__membership__user').order_by('-registered_at', '-pk')[:100])
    return JsonResponse({'results': [_visit(v) for v in visits]})


@require_GET
def reception_visit_history_detail(request, slug, visit_id):
    member = _member(request, slug, reception=True)
    if not member: return _err('Reception staff authentication and 2FA required', 403)
    visit = PatientVisit.objects.filter(pk=visit_id, hospital_id=member.hospital_id).select_related(
        'patient', 'assigned_doctor__membership__user').first()
    if not visit: return _err('Visit not found in this hospital', 404)
    return JsonResponse(_full_summary(member, visit))


@require_POST
def reception_finalize(request, slug, visit_id):
    member = _member(request, slug, reception=True)
    if not member: return _err('Reception staff authentication and 2FA required', 403)
    with transaction.atomic():
        v = PatientVisit.objects.select_for_update(of=('self',)).filter(pk=visit_id, hospital_id=member.hospital_id).first()
        if not v: return _err('Visit not found', 404)
        if v.state != PatientVisit.State.PHARMACY: return _err('Visit is not awaiting Reception finalization', 409)
        if not PharmacyDispense.objects.filter(visit=v).exists(): return _err('Pharmacy has not finalized dispensing', 409)
        # Server-side requirement: every released investigation report must have a
        # persisted Gmail-acceptance receipt for the current verified version and recipient.
        intake = getattr(v.patient, 'intake', None)
        recipient = (getattr(intake, 'email', '') or '').strip()
        required = (TestOrderItem.objects.filter(order__visit=v, test__hospital_id=member.hospital_id)
                    .exclude(status=TestOrderItem.Status.CANCELLED)
                    .select_related('structured_report'))
        for item in required:
            report = getattr(item, 'structured_report', None)
            if not report or report.status not in (InvestigationReport.Status.FINAL, InvestigationReport.Status.AMENDED) or not report.verified_at or not report.verified_by_id:
                return _err('All non-cancelled investigation reports must be verified before discharge.', 409)
            if not ReceptionReportEmailReceipt.objects.filter(
                hospital_id=member.hospital_id, visit_id=v.pk, item_id=item.pk,
                report_id=report.pk, report_verified_at=report.verified_at,
                recipient_email__iexact=recipient,
            ).exists():
                return _err(f'Email report for {item.test.name} before finalizing this visit.', 409)
        old = v.state
        v.state = PatientVisit.State.COMPLETE
        v.completed_at = timezone.now()
        v.save(update_fields=['state', 'completed_at'])
        PatientMovementEvent.objects.create(visit=v, from_state=old, to_state=v.state,
            actor=member, reason='Reception reviewed pharmacy bill and finalized patient visit')
    return JsonResponse({'detail': 'Patient visit finalized', 'visit_id': v.pk, 'state': v.state})


# Pharmacy call / recall - follows Doctor queue semantics.
from datetime import timedelta
from .models import Department, PatientAttendance, AnnouncementEvent
from .queue_timeout import expire_unattended_calls

def _pharmacy_queue_data(member):
    expire_unattended_calls(member.hospital)
    # Pharmacy-specific missed calls: after five minutes, enable Recall.
    cutoff=timezone.now()-timedelta(minutes=5)
    PatientQueueEntry.objects.filter(
        visit__hospital_id=member.hospital_id,
        department__hospital_id=member.hospital_id,
        department__kind=Department.Kind.PHARMACY,
        kind=PatientQueueEntry.Kind.PHARMACY,
        status=PatientQueueEntry.Status.CALLED,
        called_at__lte=cutoff,
        visit__state=PatientVisit.State.PHARMACY,
        visit__pharmacy_dispense__isnull=True,
    ).update(status=PatientQueueEntry.Status.RECALL_PENDING)
    entries=(PatientQueueEntry.objects.filter(visit__hospital_id=member.hospital_id,department__hospital_id=member.hospital_id,department__kind=Department.Kind.PHARMACY,kind=PatientQueueEntry.Kind.PHARMACY,visit__state=PatientVisit.State.PHARMACY,visit__pharmacy_dispense__isnull=True,status__in=[PatientQueueEntry.Status.WAITING,PatientQueueEntry.Status.CALLED,PatientQueueEntry.Status.RECALL_PENDING]).select_related('visit__patient','department').order_by('queued_at','pk')[:250])
    return [{'id':e.pk,'visit_id':e.visit_id,'status':e.status,'token':e.visit.queue_token or e.visit.visit_number,'patient_name':e.visit.patient.full_name,'patient_number':e.visit.patient.patient_number,'department':e.department.name,'room_number':e.department.room_number,'queued_at':e.queued_at.isoformat(),'called_at':e.called_at.isoformat() if e.called_at else None} for e in entries]

@require_GET
def pharmacy_call_queue(request,slug):
    member=_member(request,slug)
    if not member:return _err('Pharmacy staff login and 2FA required',403)
    return JsonResponse({'results':_pharmacy_queue_data(member)})

def _pharmacy_call(request,slug,entry_id,recall=False):
    member=_member(request,slug)
    if not member:return _err('Pharmacy staff login and 2FA required',403)
    with transaction.atomic():
        ref=PatientQueueEntry.objects.filter(pk=entry_id,visit__hospital_id=member.hospital_id,department__hospital_id=member.hospital_id,department__kind=Department.Kind.PHARMACY,kind=PatientQueueEntry.Kind.PHARMACY).values('visit_id').first()
        if not ref:return _err('Pharmacy queue entry not found',404)
        visit=PatientVisit.objects.select_for_update().get(pk=ref['visit_id'],hospital_id=member.hospital_id)
        entry=(PatientQueueEntry.objects.select_for_update().select_related('department').filter(pk=entry_id,visit=visit,department__hospital_id=member.hospital_id,department__kind=Department.Kind.PHARMACY,kind=PatientQueueEntry.Kind.PHARMACY).first())
        expected=PatientQueueEntry.Status.RECALL_PENDING if recall else PatientQueueEntry.Status.WAITING
        if not entry or entry.status!=expected:return _err('Queue status changed; refresh dashboard.',409)
        if visit.state!=PatientVisit.State.PHARMACY or PharmacyDispense.objects.filter(visit=visit).exists():return _err('Visit is not awaiting pharmacy dispensing.',409)
        room=(entry.department.room_number or '').strip()
        if not room:return _err('Configure the Pharmacy department room number first.',409)
        if PatientAttendance.objects.filter(visit=visit,released_at__isnull=True).exists():return _err('Patient is already being attended.',409)
        if PatientQueueEntry.objects.filter(visit=visit,status=PatientQueueEntry.Status.CALLED).exclude(pk=entry.pk).exists():return _err('Patient already called elsewhere.',409)
        token=visit.queue_token or visit.visit_number
        if not token:return _err('Missing queue token.',409)
        now=timezone.now();entry.status=PatientQueueEntry.Status.CALLED;entry.called_at=now;entry.save(update_fields=['status','called_at'])
        AnnouncementEvent.objects.create(hospital=member.hospital,queue_entry=entry,called_by=member,token=token,department_name=entry.department.name,room_number=room,called_at=now)
    return JsonResponse({'detail':'Patient announced on Central TV.','entry_id':entry.pk,'called_at':now.isoformat(),'expires_at':(now+timedelta(minutes=5)).isoformat()})

@require_POST
def pharmacy_call_patient(request,slug,entry_id):return _pharmacy_call(request,slug,entry_id,False)

@require_POST
def pharmacy_recall_patient(request,slug,entry_id):return _pharmacy_call(request,slug,entry_id,True)
