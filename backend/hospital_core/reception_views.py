"""Hospital-scoped Reception API. Requires password + verified 2FA session."""
import json
import uuid
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Q, Count
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import Department, DoctorProfile, Hospital, Patient, PatientMovementEvent, PatientQueueEntry, PatientVisit, StaffMembership, PatientAttendance, TestOrderItem, InvestigationReport
from .patient_intake_models import PatientIntake
from .token_service import allocate_queue_token
from .views import require_staff


def error(message, status=400):
    return JsonResponse({'detail': message}, status=status)


def reception_member(request, slug):
    member = require_staff(request, slug)
    return member if member and member.role in (StaffMembership.Role.RECEPTION, StaffMembership.Role.ADMIN) else None


def decode_json(request):
    try:
        value = json.loads(request.body or b'{}')
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def doctor_json(profile):
    return {'id': profile.pk, 'name': profile.membership.user.get_full_name() or profile.membership.user.username,
            'department': profile.membership.department.name if profile.membership.department_id else None,
            'room_number': profile.room_number, 'on_duty': profile.on_duty,
            'waiting_count': getattr(profile, 'waiting_count', 0)}


def patient_json(patient):
    intake = getattr(patient, 'intake', None)
    return {'id': patient.pk, 'patient_number': patient.patient_number, 'full_name': patient.full_name,
            'date_of_birth': patient.date_of_birth.isoformat() if patient.date_of_birth else None,
            'sex': intake.sex if intake else '', 'phone': intake.phone if intake else '',
            'email': intake.email if intake else '', 'address': intake.address if intake else '',
            'emergency_contact_name': intake.emergency_contact_name if intake else '',
            'emergency_contact_phone': intake.emergency_contact_phone if intake else '',
            'allergies': intake.allergies if intake else '',
            'current_medications': intake.current_medications if intake else '',
            'medical_history': intake.medical_history if intake else ''}


def visit_json(visit):
    return {'id': visit.pk, 'visit_number': visit.visit_number, 'queue_token': visit.queue_token,
            'token_month': visit.token_month.isoformat() if visit.token_month else None,
            'registered_at': visit.registered_at.isoformat(), 'state': visit.state,
            'patient': {'id': visit.patient_id, 'patient_number': visit.patient.patient_number,
                        'full_name': visit.patient.full_name}, 'doctor': doctor_json(visit.assigned_doctor)}


def today_window():
    start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
    return start, start + timedelta(days=1)


@require_GET
def doctors(request, slug):
    member = reception_member(request, slug)
    if not member:
        return error('Reception authorization and 2FA required', 403)
    start, end = today_window()
    profiles = (DoctorProfile.objects.select_related('membership__user', 'membership__department')
                .filter(membership__hospital_id=member.hospital_id, membership__is_active=True,
                        membership__role=StaffMembership.Role.DOCTOR, on_duty=True,
                        membership__department__hospital_id=member.hospital_id,
                        membership__department__is_active=True)
                .annotate(waiting_count=Count('assigned_visits', filter=Q(
                    assigned_visits__registered_at__gte=start,
                    assigned_visits__registered_at__lt=end,
                    assigned_visits__state__in=[PatientVisit.State.NURSING_INITIAL,
                                                PatientVisit.State.DOCTOR_WAIT,
                                                PatientVisit.State.DOCTOR_RECALL]), distinct=True))
                .order_by('waiting_count', 'membership__user__username'))
    return JsonResponse({'doctors': [doctor_json(p) for p in profiles]})


@require_GET
def visits(request, slug):
    member = reception_member(request, slug)
    if not member:
        return error('Reception authorization and 2FA required', 403)
    start, end = today_window()
    qs = (PatientVisit.objects.select_related('patient', 'assigned_doctor__membership__user',
                                             'assigned_doctor__membership__department')
          .filter(hospital_id=member.hospital_id, registered_at__gte=start, registered_at__lt=end)
          .order_by('-registered_at', '-pk')[:200])
    return JsonResponse({'visits': [visit_json(v) for v in qs]})


@require_GET
def search_patients(request, slug):
    member = reception_member(request, slug)
    if not member:
        return error('Reception authorization and 2FA required', 403)
    query = request.GET.get('q', '').strip()
    if len(query) < 2 or len(query) > 100:
        return error('Search must contain 2 to 100 characters')
    matches = (Patient.objects.select_related('intake').filter(hospital_id=member.hospital_id)
               .filter(Q(patient_number__icontains=query) | Q(full_name__icontains=query) |
                       Q(intake__phone__icontains=query)).distinct().order_by('full_name', 'pk')[:20])
    return JsonResponse({'patients': [patient_json(p) for p in matches]})


def string_field(data, key, max_length, required=False):
    value = data.get(key, '')
    if not isinstance(value, str):
        raise ValueError(f'{key} must be text')
    value = value.strip()
    if len(value) > max_length or (required and not value):
        raise ValueError(f'{key} is required or exceeds {max_length} characters')
    return value


@require_POST
@transaction.atomic
def register_visit(request, slug):
    member = reception_member(request, slug)
    if not member:
        return error('Reception authorization and 2FA required', 403)
    data = decode_json(request)
    if data is None:
        return error('Expected a JSON object')
    doctor_id = data.get('doctor_id')
    if type(doctor_id) is not int or doctor_id <= 0:
        return error('Select a valid doctor_id')

    hospital = Hospital.objects.select_for_update().filter(pk=member.hospital_id, is_active=True).first()
    if not hospital:
        return error('Hospital is inactive', 403)
    doctor = (DoctorProfile.objects.select_related('membership__department', 'membership__user')
              .filter(pk=doctor_id, membership__hospital_id=hospital.pk,
                      membership__is_active=True, membership__role=StaffMembership.Role.DOCTOR,
                      membership__department__hospital_id=hospital.pk,
                      membership__department__is_active=True, on_duty=True).first())
    if not doctor:
        return error('Doctor is unavailable at this hospital')
    nursing = Department.objects.filter(hospital=hospital, kind=Department.Kind.NURSING,
                                        is_active=True).order_by('pk').first()
    if not nursing:
        return error('No active Nursing Station configured', 409)

    patient_id = data.get('patient_id')
    if patient_id is not None:
        if type(patient_id) is not int or patient_id <= 0:
            return error('Invalid patient_id')
        patient = Patient.objects.filter(pk=patient_id, hospital=hospital).first()
        if not patient:
            return error('Patient not found in this hospital', 404)
        # Do not silently overwrite existing medical or identity data during a return visit.
    else:
        try:
            name = string_field(data, 'full_name', 180, required=True)
            sex = string_field(data, 'sex', 30)
            phone = string_field(data, 'phone', 40)
            email = string_field(data, 'email', 254)
            address = string_field(data, 'address', 2000)
            emergency_name = string_field(data, 'emergency_contact_name', 180)
            emergency_phone = string_field(data, 'emergency_contact_phone', 40)
            allergies = string_field(data, 'allergies', 4000)
            medications = string_field(data, 'current_medications', 4000)
            history = string_field(data, 'medical_history', 8000)
        except ValueError as exc:
            return error(str(exc))
        dob = data.get('date_of_birth')
        if dob in ('', None):
            dob = None
        else:
            if not isinstance(dob, str):
                return error('date_of_birth must be YYYY-MM-DD')
            try:
                dob = datetime.strptime(dob, '%Y-%m-%d').date()
            except ValueError:
                return error('date_of_birth must be YYYY-MM-DD')
            if dob > timezone.localdate():
                return error('date_of_birth cannot be in the future')
        patient = Patient.objects.create(hospital=hospital,
                                         patient_number='P-' + uuid.uuid4().hex[:20].upper(),
                                         full_name=name, date_of_birth=dob)
        PatientIntake.objects.create(patient=patient, sex=sex, phone=phone, email=email,
                                     address=address, emergency_contact_name=emergency_name,
                                     emergency_contact_phone=emergency_phone, allergies=allergies,
                                     current_medications=medications, medical_history=history)

    # Do not accidentally create two active visits for the same patient.
    active = PatientVisit.objects.filter(hospital=hospital, patient=patient).exclude(
        state__in=[PatientVisit.State.COMPLETE, PatientVisit.State.CANCELLED]).first()
    if active:
        return error('This patient already has an active visit. Open the existing visit instead.', 409)

    token, month = allocate_queue_token(hospital)
    visit = PatientVisit.objects.create(hospital=hospital, patient=patient,
                                        visit_number='V-' + uuid.uuid4().hex.upper(),
                                        queue_token=token, token_month=month,
                                        assigned_doctor=doctor, state=PatientVisit.State.NURSING_INITIAL)
    PatientQueueEntry.objects.create(visit=visit, department=nursing,
                                     kind=PatientQueueEntry.Kind.NURSING_INITIAL,
                                     status=PatientQueueEntry.Status.WAITING)
    PatientMovementEvent.objects.create(visit=visit, from_state='',
                                        to_state=PatientVisit.State.NURSING_INITIAL,
                                        actor=member, reason='Reception registration')
    return JsonResponse({'detail': 'Visit registered', 'visit': visit_json(visit)}, status=201)


@require_POST
def confirm_return_for_review(request, slug, visit_id):
    """Reception confirms post-test return after all non-cancelled reports are ready."""
    member = reception_member(request, slug)
    if not member:
        return error('Reception authorization and 2FA required', 403)

    with transaction.atomic():
        visit = (PatientVisit.objects.select_for_update(of=('self',))
                 .filter(pk=visit_id, hospital_id=member.hospital_id,
                         hospital__is_active=True).first())
        if not visit:
            return error('Visit not found in this hospital', 404)
        if visit.state != PatientVisit.State.TEST_POOL:
            return error('Visit is not in the testing stage', 409)
        if PatientAttendance.objects.filter(visit=visit, released_at__isnull=True).exists():
            return error('Patient is still under active attendance', 409)

        tests = TestOrderItem.objects.filter(order__visit=visit).exclude(
            status=TestOrderItem.Status.CANCELLED
        )
        if not tests.exists():
            return error('No active test orders found', 409)
        if tests.exclude(status=TestOrderItem.Status.REPORT_READY).exists():
            return error('All non-cancelled test reports must be ready', 409)
        _, complete, reviewed = _report_status(visit)
        if not complete or not reviewed:
            return error('Reception must review all finalized reports before forwarding', 409)

        # Do not bypass unfinished laboratory or nursing queue work.
        if PatientQueueEntry.objects.filter(
            visit=visit,
            status__in=[PatientQueueEntry.Status.WAITING,
                        PatientQueueEntry.Status.CALLED,
                        PatientQueueEntry.Status.RECALL_PENDING],
        ).exists():
            return error('Another queue step is still pending', 409)

        doctor = visit.assigned_doctor
        membership = doctor.membership
        department = membership.department
        if (not membership.is_active or membership.role != StaffMembership.Role.DOCTOR
                or membership.hospital_id != member.hospital_id
                or department is None or department.hospital_id != member.hospital_id
                or department.kind != Department.Kind.DOCTOR or not department.is_active):
            return error('Assigned doctor department is unavailable', 409)

        entry = PatientQueueEntry.objects.create(
            visit=visit, department=department,
            kind=PatientQueueEntry.Kind.DOCTOR_RECALL,
            status=PatientQueueEntry.Status.WAITING,
        )
        previous_state = visit.state
        visit.state = PatientVisit.State.DOCTOR_RECALL
        visit.save(update_fields=['state'])
        PatientMovementEvent.objects.create(
            visit=visit, from_state=previous_state,
            to_state=PatientVisit.State.DOCTOR_RECALL,
            actor=member, reason='Reception confirmed return after tests',
        )
    return JsonResponse({
        'detail': 'Patient sent for doctor review',
        'visit_id': visit.pk, 'queue_entry_id': entry.pk,
        'state': visit.state,
    })


# Stage 6: Reception-only administrative report completion review.
# Movement events record reviews without changing clinical FINAL reports.
REPORTS_REVIEWED = 'Reception confirmed finalized investigation reports'


def _report_status(visit):
    items = list(TestOrderItem.objects.filter(order__visit=visit).exclude(
        status=TestOrderItem.Status.CANCELLED).select_related('test'))
    finalized = set(InvestigationReport.objects.filter(
        item_id__in=[item.pk for item in items], status=InvestigationReport.Status.FINAL
    ).values_list('item_id', flat=True))
    complete = bool(items) and all(
        item.status == TestOrderItem.Status.REPORT_READY and item.pk in finalized
        for item in items
    )
    latest = max((item.report_ready_at for item in items if item.report_ready_at), default=None)
    review = PatientMovementEvent.objects.filter(visit=visit, reason=REPORTS_REVIEWED).order_by('-created_at', '-pk').first()
    reviewed = bool(review and latest and review.created_at >= latest)
    return items, complete, reviewed


@require_GET
def completed_investigation_visits(request, slug):
    member = reception_member(request, slug)
    if not member:
        return error('Reception authorization and 2FA required', 403)
    # A visit may have been registered on an earlier day; completion is not
    # restricted to the day of registration. Keep the hospital and workflow scope.
    qs = (PatientVisit.objects.filter(hospital_id=member.hospital_id,
                                      state__in=[PatientVisit.State.TEST_POOL, PatientVisit.State.DOCTOR_RECALL])
          .select_related('patient', 'assigned_doctor__membership__user',
                          'assigned_doctor__membership__department')
          .order_by('registered_at', 'pk')[:300])
    rows = []
    for visit in qs:
        items, complete, reviewed = _report_status(visit)
        if not complete:
            continue
        rows.append({**visit_json(visit), 'patient': patient_json(visit.patient), 'report_count': len(items), 'reviewed': reviewed,
                     'forwarded': visit.state == PatientVisit.State.DOCTOR_RECALL,
                     'reports': [{'item_id': item.pk, 'test_name': item.test.name}
                                 for item in items]})
    return JsonResponse({'results': rows})


@require_POST
def review_investigation_reports(request, slug, visit_id):
    member = reception_member(request, slug)
    if not member:
        return error('Reception authorization and 2FA required', 403)
    with transaction.atomic():
        visit = PatientVisit.objects.select_for_update().filter(
            pk=visit_id, hospital_id=member.hospital_id,
            state=PatientVisit.State.TEST_POOL).first()
        if not visit:
            return error('Patient is not awaiting Reception review', 409)
        _, complete, reviewed = _report_status(visit)
        if not complete:
            return error('All non-cancelled reports must be finalized first', 409)
        if not reviewed:
            PatientMovementEvent.objects.create(
                visit=visit, from_state=visit.state, to_state=visit.state,
                actor=member, reason=REPORTS_REVIEWED)
    return JsonResponse({'detail': 'Report completeness reviewed', 'reviewed': True})


@require_POST
def reassign_doctor(request, slug, visit_id):
    member = reception_member(request, slug)
    if not member:
        return error('Reception authorization and 2FA required', 403)
    body = decode_json(request)
    if body is None:
        return error('Doctor and reason are required')
    try:
        doctor_id = int(body.get('doctor_id'))
    except (ValueError, TypeError):
        return error('Select a valid doctor')
    reason = str(body.get('reason') or '').strip()
    if len(reason) < 5 or len(reason) > 120:
        return error('Enter a reassignment reason (5–120 characters)')
    with transaction.atomic():
        visit = (PatientVisit.objects.select_for_update(of=('self',))
                 .filter(pk=visit_id, hospital_id=member.hospital_id).first())
        if not visit:
            return error('Visit not found', 404)
        if visit.state in [PatientVisit.State.COMPLETE, PatientVisit.State.CANCELLED, PatientVisit.State.DOCTOR_ACTIVE]:
            return error('Cannot reassign a completed, cancelled, or actively consulting visit', 409)
        doctor = DoctorProfile.objects.select_related('membership__department').filter(
            pk=doctor_id, membership__hospital_id=member.hospital_id,
            membership__is_active=True, membership__role=StaffMembership.Role.DOCTOR,
            membership__department__hospital_id=member.hospital_id,
            membership__department__kind=Department.Kind.DOCTOR,
            membership__department__is_active=True, on_duty=True).first()
        if not doctor:
            return error('New doctor must be on duty in this hospital', 409)
        if visit.assigned_doctor_id == doctor.pk:
            return JsonResponse({'detail': 'Doctor already assigned', 'visit': visit_json(visit)})
        # Move only uncalled doctor queue entries. Never interrupt a live call or consultation.
        active_doctor_entries = PatientQueueEntry.objects.select_for_update().filter(
            visit=visit, kind__in=[PatientQueueEntry.Kind.DOCTOR_INITIAL, PatientQueueEntry.Kind.DOCTOR_RECALL],
            status__in=[PatientQueueEntry.Status.CALLED, PatientQueueEntry.Status.RECALL_PENDING])
        if active_doctor_entries.exists():
            return error('Doctor call is active or pending recall; resolve it before reassignment', 409)
        old = visit.assigned_doctor_id
        PatientQueueEntry.objects.filter(
            visit=visit, kind__in=[PatientQueueEntry.Kind.DOCTOR_INITIAL, PatientQueueEntry.Kind.DOCTOR_RECALL],
            status=PatientQueueEntry.Status.WAITING).update(department=doctor.membership.department)
        visit.assigned_doctor = doctor
        visit.save(update_fields=['assigned_doctor'])
        PatientMovementEvent.objects.create(
            visit=visit, from_state=visit.state, to_state=visit.state, actor=member,
            reason=f'Doctor reassigned {old} -> {doctor.pk}: {reason}'[:240])
    return JsonResponse({'detail': 'Doctor changed successfully', 'visit': visit_json(visit)})
