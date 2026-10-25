
"""Doctor-only, hospital-scoped patient calling and consultation APIs."""

from datetime import timedelta
import json

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .views import require_staff
from .models import (
    StaffMembership,
    DoctorProfile,
    PatientQueueEntry,
    PatientVisit, NursingAssessment,
    PatientAttendance,
    AnnouncementEvent,
    Consultation,
    MedicineCatalogItem, Prescription, PrescriptionItem,
    TestCatalogItem, TestOrder, TestOrderItem, InvestigationBill, InvestigationBillLine,
    PatientMovementEvent, Department, InvestigationReport, TestResult,
)
from .queue_timeout import expire_unattended_calls


DOCTOR_KINDS = (
    PatientQueueEntry.Kind.DOCTOR_INITIAL,
    PatientQueueEntry.Kind.DOCTOR_RECALL,
)

CALL_WINDOW = timedelta(minutes=5)


# ============================================================
# 1. DOCTOR AUTHENTICATION AND HOSPITAL ACCESS
# ============================================================

def _doctor(request, slug):
    member = require_staff(request, slug)

    if not member:
        return (
            None,
            None,
            JsonResponse(
                {"detail": "Login and hospital 2FA required."},
                status=401,
            ),
        )

    if member.role != StaffMembership.Role.DOCTOR:
        return (
            None,
            None,
            JsonResponse(
                {"detail": "Doctor access required."},
                status=403,
            ),
        )

    doctor = (
        DoctorProfile.objects
        .select_related("membership")
        .filter(
            membership=member,
            membership__hospital__slug=slug,
            membership__is_active=True,
            membership__hospital__is_active=True,
        )
        .first()
    )

    if not doctor:
        return (
            None,
            None,
            JsonResponse(
                {"detail": "Doctor profile not configured."},
                status=403,
            ),
        )

    return member, doctor, None


# ============================================================
# 2. DOCTOR-SPECIFIC PATIENT QUEUE
# ============================================================

def _scope(doctor):
    """
    Return only patients:
    - Belonging to this hospital
    - Assigned to this doctor
    - In a doctor department
    - With a doctor queue entry
    """

    hospital_id = doctor.membership.hospital_id

    return PatientQueueEntry.objects.filter(
        visit__hospital_id=hospital_id,
        visit__assigned_doctor=doctor,
        kind__in=DOCTOR_KINDS,
        department__hospital_id=hospital_id,
        department__kind="DOCTOR",
    )


# ============================================================
# 3. SERIALIZE PATIENT QUEUE DATA
# ============================================================

def _serialize(entry):
    visit = entry.visit

    return {
        "id": entry.pk,
        "visit_id": visit.pk,
        "token": visit.queue_token or visit.visit_number,
        "patient_name": visit.patient.full_name,
        "patient_number": visit.patient.patient_number,
        "kind": entry.kind,
        "status": entry.status,
        "visit_state": visit.state,
        "queued_at": entry.queued_at.isoformat(),
        "called_at": (
            entry.called_at.isoformat()
            if entry.called_at
            else None
        ),
        "department": entry.department.name,
    }


# ============================================================
# 4. DOCTOR DASHBOARD — FOUR QUEUES
# ============================================================

@require_GET
def queue(request, slug):
    member, doctor, error = _doctor(request, slug)

    if error:
        return error

    # Expire unattended calls after five minutes.
    # Doctor calls become RECALL_PENDING.
    # Nursing calls follow their existing timeout rules.
    expire_unattended_calls(member.hospital)

    # Rolling 24-hour dashboard window. Historical records remain in the database.
    cutoff = timezone.now() - timedelta(hours=24)

    entries = (
        _scope(doctor)
        .filter(
            queued_at__gte=cutoff,
            visit__state__in=[
                PatientVisit.State.DOCTOR_WAIT,
                PatientVisit.State.DOCTOR_RECALL,
            ],
            status__in=[
                PatientQueueEntry.Status.WAITING,
                PatientQueueEntry.Status.CALLED,
                PatientQueueEntry.Status.RECALL_PENDING,
            ],
        )
        .select_related(
            "visit__patient",
            "department",
        )
        .order_by("queued_at", "pk")
    )

    data = {
        "waiting": [],
        "called": [],
        "recall": [],
        "review": [],
    }

    for entry in entries:

        # Patient missed a previous doctor call.
        if entry.status == PatientQueueEntry.Status.RECALL_PENDING:
            bucket = "recall"

        # Patient has been called and is within the call window.
        elif entry.status == PatientQueueEntry.Status.CALLED:
            bucket = "called"

        # Patient returned after investigations.
        # Reception must have confirmed the return.
        elif (
            entry.status == PatientQueueEntry.Status.WAITING
            and entry.kind == PatientQueueEntry.Kind.DOCTOR_RECALL
            and entry.visit.state == PatientVisit.State.DOCTOR_RECALL
        ):
            bucket = "review"

        # New patient waiting for initial doctor consultation.
        else:
            bucket = "waiting"

        data[bucket].append(_serialize(entry))

    return JsonResponse({
        **data,
        "doctor": (
            request.user.get_full_name()
            or request.user.username
        ),
        "room_number": doctor.room_number,
        "on_duty": doctor.on_duty,
    })


# ============================================================
# 5. LOCK PATIENT QUEUE ENTRY
# ============================================================

def _locked_entry(doctor, entry_id):
    """
    Lock the visit first, then the queue entry.
    This follows the existing Nursing lock ordering.
    """

    entry_ref = (
        _scope(doctor)
        .filter(pk=entry_id)
        .values("visit_id")
        .first()
    )

    if not entry_ref:
        return None

    PatientVisit.objects.select_for_update().get(
        pk=entry_ref["visit_id"]
    )

    return (
        _scope(doctor)
        .select_for_update()
        .select_related(
            "visit__patient",
            "department",
        )
        .filter(pk=entry_id)
        .first()
    )


# ============================================================
# 6. CALL OR RECALL PATIENT
# ============================================================

def _call(request, slug, entry_id, is_recall):
    member, doctor, error = _doctor(request, slug)

    if error:
        return error

    if not doctor.on_duty:
        return JsonResponse(
            {"detail": "Doctor must be on duty."},
            status=409,
        )

    if not (doctor.room_number or "").strip():
        return JsonResponse(
            {"detail": "Doctor room number is missing."},
            status=409,
        )

    with transaction.atomic():

        entry = _locked_entry(doctor, entry_id)

        if not entry:
            return JsonResponse(
                {
                    "detail": (
                        "Patient not found in your doctor queue."
                    )
                },
                status=404,
            )

        expected = (
            PatientQueueEntry.Status.RECALL_PENDING
            if is_recall
            else PatientQueueEntry.Status.WAITING
        )

        if entry.status != expected:
            return JsonResponse(
                {
                    "detail": (
                        "Queue status changed. Refresh the dashboard."
                    )
                },
                status=409,
            )

        if entry.visit.state not in (
            PatientVisit.State.DOCTOR_WAIT,
            PatientVisit.State.DOCTOR_RECALL,
        ):
            return JsonResponse(
                {
                    "detail": (
                        "Patient is not waiting for doctor."
                    )
                },
                status=409,
            )

        # Prevent duplicate physical attendance.
        if PatientAttendance.objects.filter(
            visit=entry.visit,
            released_at__isnull=True,
        ).exists():
            return JsonResponse(
                {
                    "detail": (
                        "Patient is already being attended."
                    )
                },
                status=409,
            )

        # Prevent the same patient being called elsewhere.
        if (
            PatientQueueEntry.objects
            .filter(
                visit=entry.visit,
                status=PatientQueueEntry.Status.CALLED,
            )
            .exclude(pk=entry.pk)
            .exists()
        ):
            return JsonResponse(
                {
                    "detail": (
                        "Patient already called elsewhere."
                    )
                },
                status=409,
            )

        token = (
            entry.visit.queue_token
            or entry.visit.visit_number
        )

        if not token:
            return JsonResponse(
                {"detail": "Missing queue token."},
                status=409,
            )

        now = timezone.now()

        entry.status = PatientQueueEntry.Status.CALLED
        entry.called_at = now

        entry.save(
            update_fields=[
                "status",
                "called_at",
            ]
        )

        # Create a new announcement for Central TV.
        AnnouncementEvent.objects.create(
            hospital=member.hospital,
            queue_entry=entry,
            called_by=member,
            token=token,
            department_name=entry.department.name,
            room_number=doctor.room_number,
            called_at=now,
        )

    return JsonResponse({
        "detail": "Patient announced on Central TV.",
        "entry_id": entry.pk,
        "called_at": now.isoformat(),
        "expires_at": (
            now + CALL_WINDOW
        ).isoformat(),
    })


# ============================================================
# 7. INITIAL CALL / REVIEW CALL
# ============================================================

@require_POST
def call_patient(request, slug, entry_id):
    """
    Used for:
    - Calling a new patient
    - Calling a patient waiting for post-test review
    """

    return _call(
        request,
        slug,
        entry_id,
        is_recall=False,
    )


# ============================================================
# 8. RECALL A PATIENT WHO MISSED THEIR CALL
# ============================================================

@require_POST
def recall_patient(request, slug, entry_id):
    """
    Manually recall a patient after the five-minute timeout.

    Creates a fresh Central TV announcement.
    """

    return _call(
        request,
        slug,
        entry_id,
        is_recall=True,
    )


# ============================================================
# 9. START DOCTOR CONSULTATION
# ============================================================

@require_POST
def start_consultation(request, slug, entry_id):
    member, doctor, error = _doctor(request, slug)

    if error:
        return error

    with transaction.atomic():

        entry = _locked_entry(doctor, entry_id)

        if not entry:
            return JsonResponse(
                {"detail": "Patient not found."},
                status=404,
            )

        if entry.status != PatientQueueEntry.Status.CALLED:
            return JsonResponse(
                {
                    "detail": (
                        "Call the patient before starting consultation."
                    )
                },
                status=409,
            )

        if entry.visit.state not in (
            PatientVisit.State.DOCTOR_WAIT,
            PatientVisit.State.DOCTOR_RECALL,
        ):
            return JsonResponse(
                {
                    "detail": (
                        "Patient is not ready for consultation."
                    )
                },
                status=409,
            )

        if PatientAttendance.objects.filter(
            visit=entry.visit,
            released_at__isnull=True,
        ).exists():
            return JsonResponse(
                {
                    "detail": (
                        "Patient is already being attended."
                    )
                },
                status=409,
            )

        if Consultation.objects.filter(
            visit=entry.visit,
            doctor=doctor,
            status=Consultation.Status.ACTIVE,
        ).exists():
            return JsonResponse(
                {
                    "detail": (
                        "An active consultation already exists."
                    )
                },
                status=409,
            )

        # Record the doctor physically attending the patient.
        attendance = PatientAttendance.objects.create(
            visit=entry.visit,
            department=entry.department,
            staff=member,
        )

        # Start a new consultation record.
        consultation = Consultation.objects.create(
            visit=entry.visit,
            doctor=doctor,
            status=Consultation.Status.ACTIVE,
        )

        # Complete the current queue entry.
        entry.status = PatientQueueEntry.Status.DONE
        entry.completed_at = timezone.now()

        entry.save(
            update_fields=[
                "status",
                "completed_at",
            ]
        )

        # Move the patient into active consultation.
        entry.visit.state = PatientVisit.State.DOCTOR_ACTIVE

        entry.visit.save(
            update_fields=["state"]
        )

    return JsonResponse({
        "detail": "Consultation started.",
        "consultation_id": consultation.pk,
        "attendance_id": attendance.pk,
        "visit_id": entry.visit_id,
    })


# ============================================================
# 10. ACTIVE CONSULTATIONS — RESUME EXISTING CONSULTATION
# ============================================================

@require_GET
def active_consultations(request, slug):
    """Return this doctor's active patients so a consultation can be resumed.

    The active consultation is intentionally not placed back in the waiting
    or called queues: its original queue entry is already DONE.
    """
    member, doctor, error = _doctor(request, slug)
    if error:
        return error

    cutoff = timezone.now() - timedelta(hours=24)
    consultations = (
        Consultation.objects.filter(
            started_at__gte=cutoff,
            doctor=doctor,
            visit__hospital_id=member.hospital_id,
            visit__assigned_doctor=doctor,
            visit__state=PatientVisit.State.DOCTOR_ACTIVE,
            status=Consultation.Status.ACTIVE,
        )
        .select_related("visit__patient")
        .order_by("started_at", "pk")
    )

    return JsonResponse({
        "consultations": [
            {
                "consultation_id": item.pk,
                "visit_id": item.visit_id,
                "token": item.visit.queue_token or item.visit.visit_number,
                "patient_name": item.visit.patient.full_name,
                "patient_number": item.visit.patient.patient_number,
                "started_at": item.started_at.isoformat(),
                "notes": _draft(item)["notes"],
                "diagnosis": item.diagnosis,
                "status": item.status,
            }
            for item in consultations
        ]
    })


# ============================================================
# 11. CONSULTATION EDITOR (TWO TABS, MULTIPLE ITEMS)
# ============================================================
# Until a dedicated draft model is introduced, an ACTIVE consultation's
# notes field stores a versioned JSON draft. On submission it becomes plain
# clinical notes again. Do not manually edit that field while ACTIVE.
_DRAFT_MARKER = "HOSPITALONE_DRAFT_V1:"
_MAX_ITEMS = 100


def _draft(consultation):
    raw = consultation.notes or ""
    if raw.startswith(_DRAFT_MARKER):
        try:
            data = json.loads(raw[len(_DRAFT_MARKER):])
            if isinstance(data, dict):
                return {
                    "notes": data.get("notes", ""),
                    "medicines": data.get("medicines", []),
                    "tests": data.get("tests", []),
                }
        except (ValueError, TypeError):
            pass
    return {"notes": raw, "medicines": [], "tests": []}


def _editor_data(consultation):
    draft = _draft(consultation)
    return {
        "consultation_id": consultation.pk,
        "visit_id": consultation.visit_id,
        "patient_name": consultation.visit.patient.full_name,
        "patient_number": consultation.visit.patient.patient_number,
        "token": consultation.visit.queue_token or consultation.visit.visit_number,
        "status": consultation.status,
        "visit_state": consultation.visit.state,
        "notes": draft["notes"],
        "diagnosis": consultation.diagnosis,
        "medicines": draft["medicines"],
        "tests": draft["tests"],
    }


def _consultation(doctor, consultation_id, lock=False):
    qs = Consultation.objects.filter(
        pk=consultation_id,
        doctor=doctor,
        visit__hospital_id=doctor.membership.hospital_id,
        visit__assigned_doctor=doctor,
    ).select_related("visit__patient")
    if lock:
        qs = qs.select_for_update()
    return qs.first()


def _json_body(request):
    try:
        if len(request.body) > 150000:
            raise ValueError("Request too large.")
        body = json.loads(request.body.decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object.")
        return body, None
    except (UnicodeError, ValueError) as exc:
        return None, JsonResponse({"detail": str(exc)}, status=400)


def _validated_draft(body, hospital_id):
    notes = body.get("notes", "")
    diagnosis = body.get("diagnosis", "")
    medicines = body.get("medicines", [])
    tests = body.get("tests", [])
    if not isinstance(notes, str) or len(notes) > 20000:
        raise ValueError("Notes must be text of at most 20,000 characters.")
    if not isinstance(diagnosis, str) or len(diagnosis) > 10000:
        raise ValueError("Diagnosis must be text of at most 10,000 characters.")
    if not isinstance(medicines, list) or not isinstance(tests, list):
        raise ValueError("Medicines and tests must be arrays.")
    if len(medicines) > _MAX_ITEMS or len(tests) > _MAX_ITEMS:
        raise ValueError("Too many items (maximum 100 per tab).")

    normalized_medicines = []
    for i, row in enumerate(medicines, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Medicine {i}: invalid item.")
        try:
            med_id = int(row.get("medicine_id"))
            quantity = int(row.get("quantity"))
        except (TypeError, ValueError):
            raise ValueError(f"Medicine {i}: medicine_id and quantity are required.")
        if quantity <= 0 or quantity > 100000:
            raise ValueError(f"Medicine {i}: quantity must be between 1 and 100000.")
        if not MedicineCatalogItem.objects.filter(pk=med_id, hospital_id=hospital_id, active=True).exists():
            raise ValueError(f"Medicine {i}: unknown or inactive medicine.")
        item = {"medicine_id": med_id, "quantity": quantity}
        for field, limit in (("dose", 100), ("route", 60), ("frequency", 100), ("duration", 100), ("instructions", 5000)):
            value = row.get(field, "")
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f"Medicine {i}: invalid {field}.")
            if field != "instructions" and not value.strip():
                raise ValueError(f"Medicine {i}: {field} is required.")
            item[field] = value.strip()
        normalized_medicines.append(item)

    normalized_tests = []
    seen = set()
    for i, row in enumerate(tests, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Test {i}: invalid item.")
        try:
            test_id = int(row.get("test_id"))
        except (TypeError, ValueError):
            raise ValueError(f"Test {i}: test_id is required.")
        if test_id in seen:
            raise ValueError(f"Test {i}: duplicate test selected.")
        seen.add(test_id)
        if not TestCatalogItem.objects.filter(
            pk=test_id, hospital_id=hospital_id, active=True,
            department__hospital_id=hospital_id, department__is_active=True,
        ).exists():
            raise ValueError(f"Test {i}: unknown or inactive test/department.")
        normalized_tests.append({"test_id": test_id})
    return {"notes": notes, "diagnosis": diagnosis, "medicines": normalized_medicines, "tests": normalized_tests}


@require_GET
def consultation_catalog(request, slug):
    member, doctor, error = _doctor(request, slug)
    if error:
        return error
    medicines = MedicineCatalogItem.objects.filter(hospital_id=member.hospital_id, active=True).order_by("name", "pk")
    tests = TestCatalogItem.objects.filter(hospital_id=member.hospital_id, active=True, department__is_active=True).select_related("department").order_by("name", "pk")
    return JsonResponse({
        "medicines": [{"id": x.pk, "code": x.code, "name": x.name} for x in medicines],
        "tests": [{"id": x.pk, "code": x.code, "name": x.name, "department": x.department.name} for x in tests],
    })


@require_GET
def consultation_detail(request, slug, consultation_id):
    member, doctor, error = _doctor(request, slug)
    if error:
        return error
    item = _consultation(doctor, consultation_id)
    if not item:
        return JsonResponse({"detail": "Consultation not found."}, status=404)
    result = _editor_data(item)
    # Read-only, hospital-scoped nursing history for this exact patient visit.
    # Never substitute missing readings with fabricated values.
    assessments = NursingAssessment.objects.filter(
        visit=item.visit, visit__hospital_id=member.hospital_id,
    ).select_related('nurse__user').order_by('-completed_at', '-pk')
    result['nursing_assessments'] = [
        {
            'id': a.pk,
            'nurse_name': a.nurse.user.get_full_name() or a.nurse.user.get_username(),
            'completed_at': a.completed_at.isoformat() if a.completed_at else None,
            'blood_pressure': a.blood_pressure or None,
            'pulse_bpm': a.pulse_bpm,
            'temperature_c': str(a.temperature_c) if a.temperature_c is not None else None,
            'height_cm': str(a.height_cm) if a.height_cm is not None else None,
            'weight_kg': str(a.weight_kg) if a.weight_kg is not None else None,
            'spo2_percent': a.spo2_percent,
            'respiratory_rate': a.respiratory_rate,
            'pain_score': a.pain_score,
            'notes': a.notes or '',
        } for a in assessments[:20]
    ]
    # Past visit context is read-only and restricted to the same hospital/patient.
    result['previous_visits'] = [
        {
            'visit_number': v.visit_number,
            'registered_at': v.registered_at.isoformat(),
            'state': v.state,
            'diagnoses': list(Consultation.objects.filter(visit=v).exclude(diagnosis='')
                              .values_list('diagnosis', flat=True)[:3]),
        }
        for v in PatientVisit.objects.filter(
            patient=item.visit.patient, hospital_id=member.hospital_id
        ).exclude(pk=item.visit_id).order_by('-registered_at')[:5]
    ]
    intake = getattr(item.visit.patient, "intake", None)
    result["patient_intake"] = {
        "allergies": (intake.allergies or "") if intake else "",
        "current_medications": (intake.current_medications or "") if intake else "",
        "medical_history": (intake.medical_history or "") if intake else "",
    }
    reports = (InvestigationReport.objects.filter(
        item__order__visit=item.visit,
        item__order__visit__hospital_id=member.hospital_id,
        item__status=TestOrderItem.Status.REPORT_READY,
        status__in=[InvestigationReport.Status.FINAL, InvestigationReport.Status.AMENDED],
        verified_at__isnull=False, verified_by__isnull=False,
    ).select_related("item__test__department", "template", "verified_by__user")
      .prefetch_related("values__field").order_by("item_id"))
    result["investigation_reports"] = [
        {"item_id": report.item_id, "test_name": report.item.test.name,
         "department": report.item.test.department.name if report.item.test.department_id else "",
         "format": report.template.format, "status": report.status,
         "verified_at": report.verified_at.isoformat(),
         "verified_by": report.verified_by.user.get_full_name() or report.verified_by.user.get_username(),
         "findings": report.findings or "", "impression": report.impression or "",
         "recommendations": report.recommendations or "",
         "values": [{"label": v.field.label, "section": v.field.section,
                     "value": v.value, "unit": v.field.unit,
                     "reference": v.field.reference_text, "flag": v.flag,
                     "comment": v.comment}
                    for v in sorted(report.values.all(), key=lambda v: (v.field.position, v.field_id))],
        } for report in reports
    ]
    result["prescriptions"] = [
        {"medicine_id": x.medicine_id, "medicine_name": x.medicine.name,
         "dose": x.dose, "route": x.route, "frequency": x.frequency,
         "duration": x.duration, "quantity": x.quantity, "instructions": x.instructions}
        for x in PrescriptionItem.objects.filter(prescription__consultation=item).select_related("medicine")
    ]
    result["ordered_tests"] = [
        {"test_id": x.test_id, "test_name": x.test.name, "status": x.status}
        for x in TestOrderItem.objects.filter(order__consultation=item).select_related("test")
    ]
    return JsonResponse(result)


@require_POST
def save_consultation(request, slug, consultation_id):
    member, doctor, error = _doctor(request, slug)
    if error:
        return error
    body, error = _json_body(request)
    if error:
        return error
    try:
        draft = _validated_draft(body, member.hospital_id)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    with transaction.atomic():
        item = _consultation(doctor, consultation_id, lock=True)
        if not item:
            return JsonResponse({"detail": "Consultation not found."}, status=404)
        if item.status != Consultation.Status.ACTIVE or item.visit.state != PatientVisit.State.DOCTOR_ACTIVE:
            return JsonResponse({"detail": "Consultation is no longer editable."}, status=409)
        item.notes = _DRAFT_MARKER + json.dumps({"notes": draft["notes"], "medicines": draft["medicines"], "tests": draft["tests"]})
        item.diagnosis = draft["diagnosis"]
        item.save(update_fields=["notes", "diagnosis"])
    return JsonResponse({"detail": "Draft saved.", "consultation": _editor_data(item)})


def _submit(request, slug, consultation_id, require_tests):
    member, doctor, error = _doctor(request, slug)
    if error:
        return error
    with transaction.atomic():
        # Lock visit before consultation, consistent with queue operations.
        ref = Consultation.objects.filter(pk=consultation_id, doctor=doctor, visit__hospital_id=member.hospital_id, visit__assigned_doctor=doctor).values("visit_id").first()
        if not ref:
            return JsonResponse({"detail": "Consultation not found."}, status=404)
        visit = PatientVisit.objects.select_for_update().get(pk=ref["visit_id"])
        item = _consultation(doctor, consultation_id, lock=True)
        if item.status != Consultation.Status.ACTIVE or visit.state != PatientVisit.State.DOCTOR_ACTIVE:
            return JsonResponse({"detail": "Consultation already submitted or not active."}, status=409)
        if request.body:
            body, error = _json_body(request)
            if error:
                return error
            try:
                draft = _validated_draft(body, member.hospital_id)
            except ValueError as exc:
                return JsonResponse({"detail": str(exc)}, status=400)
        else:
            old = _draft(item)
            try:
                draft = _validated_draft({**old, "diagnosis": item.diagnosis}, member.hospital_id)
            except ValueError as exc:
                return JsonResponse({"detail": str(exc)}, status=400)
        if require_tests and not draft["tests"]:
            return JsonResponse({"detail": "Select at least one investigation."}, status=400)
        if not require_tests and draft["tests"]:
            return JsonResponse({"detail": "Investigations selected. Use Send for Tests instead."}, status=409)
        attendance = PatientAttendance.objects.select_for_update().filter(visit=visit, staff=member, released_at__isnull=True).first()
        if not attendance:
            return JsonResponse({"detail": "Active doctor attendance not found."}, status=409)
        if Prescription.objects.filter(consultation=item).exists() or TestOrder.objects.filter(consultation=item).exists():
            return JsonResponse({"detail": "Orders already submitted for this consultation."}, status=409)
        pharmacy = None
        if not require_tests and draft["medicines"]:
            pharmacy = Department.objects.filter(hospital_id=member.hospital_id, kind=Department.Kind.PHARMACY, is_active=True).order_by("pk").first()
            if not pharmacy:
                return JsonResponse({"detail": "No active pharmacy department configured."}, status=409)
        if draft["medicines"]:
            prescription = Prescription.objects.create(visit=visit, consultation=item)
            PrescriptionItem.objects.bulk_create([
                PrescriptionItem(prescription=prescription, **row) for row in draft["medicines"]
            ])
        if require_tests:
            order = TestOrder.objects.create(visit=visit, consultation=item)
            test_objects = list(TestCatalogItem.objects.filter(pk__in=[x["test_id"] for x in draft["tests"]], hospital_id=member.hospital_id).select_related("department"))
            TestOrderItem.objects.bulk_create([
                TestOrderItem(order=order, test=test) for test in test_objects
            ])
            reception_department = Department.objects.filter(
                hospital_id=member.hospital_id, kind=Department.Kind.RECEPTION, is_active=True
            ).order_by('pk').first()
            if not reception_department:
                return JsonResponse({'detail': 'Configure an active Reception department before sending tests.'}, status=409)
            reception_entry = PatientQueueEntry.objects.create(
                visit=visit, department=reception_department,
                kind=PatientQueueEntry.Kind.RECEPTION_BILLING,
                status=PatientQueueEntry.Status.WAITING,
            )
            bill = InvestigationBill.objects.create(
                hospital=member.hospital, visit=visit, test_order=order,
                reception_queue_entry=reception_entry,
                bill_number=f'INV-{member.hospital_id}-{order.pk:08d}',
                currency='INR', status=InvestigationBill.Status.WAITING_RECEPTION,
            )
            total = 0
            for order_item in TestOrderItem.objects.filter(order=order).select_related('test__department'):
                test = order_item.test
                InvestigationBillLine.objects.create(
                    bill=bill, test_order_item=order_item, test_code=test.code,
                    test_name=test.name, department_name=test.department.name,
                    amount=test.price,
                )
                total += test.price
            bill.total_amount = total
            bill.save(update_fields=['total_amount'])
            new_state = PatientVisit.State.TEST_POOL
            item.status = Consultation.Status.RECALL
        elif draft["medicines"]:
            PatientQueueEntry.objects.create(visit=visit, department=pharmacy, kind=PatientQueueEntry.Kind.PHARMACY, status=PatientQueueEntry.Status.WAITING)
            new_state = PatientVisit.State.PHARMACY
            item.status = Consultation.Status.FINISHED
        else:
            new_state = PatientVisit.State.COMPLETE
            item.status = Consultation.Status.FINISHED
            visit.completed_at = timezone.now()
        item.notes = draft["notes"]
        item.diagnosis = draft["diagnosis"]
        item.ended_at = timezone.now()
        item.save(update_fields=["notes", "diagnosis", "status", "ended_at"])
        attendance.released_at = timezone.now()
        attendance.save(update_fields=["released_at"])
        old_state = visit.state
        visit.state = new_state
        visit.save(update_fields=["state", "completed_at"] if new_state == PatientVisit.State.COMPLETE else ["state"])
        PatientMovementEvent.objects.create(visit=visit, from_state=old_state, to_state=new_state, actor=member, reason="Doctor consultation submitted")
    return JsonResponse({"detail": "Consultation submitted.", "consultation_id": item.pk, "visit_state": new_state})


@require_POST
def send_for_tests(request, slug, consultation_id):
    return _submit(request, slug, consultation_id, require_tests=True)


@require_POST
def finish_consultation(request, slug, consultation_id):
    return _submit(request, slug, consultation_id, require_tests=False)


@require_GET
def consultation_report_pdf(request, slug, consultation_id, item_id):
    """Protected report download for the doctor assigned to this visit."""
    from pathlib import Path
    from django.conf import settings
    from django.http import FileResponse

    member, doctor, error = _doctor(request, slug)
    if error:
        return error
    consultation = _consultation(doctor, consultation_id)
    if not consultation:
        return JsonResponse({"detail": "Consultation not found."}, status=404)
    report = InvestigationReport.objects.filter(
        item_id=item_id, item__order__visit=consultation.visit,
        item__order__visit__hospital_id=member.hospital_id,
        item__status=TestOrderItem.Status.REPORT_READY,
        status__in=[InvestigationReport.Status.FINAL, InvestigationReport.Status.AMENDED],
        verified_by__isnull=False, verified_at__isnull=False,
    ).first()
    if not report:
        return JsonResponse({"detail": "Released report not found."}, status=404)
    stored = TestResult.objects.filter(item_id=item_id).first()
    key = stored.private_file_key if stored else ""
    if not key.startswith("investigation_pdfs/"):
        return JsonResponse({"detail": "Archived PDF not available."}, status=404)
    root = Path(getattr(settings, "HOSPITAL_PRIVATE_REPORT_ROOT",
                        Path(settings.BASE_DIR) / "private_reports")).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return JsonResponse({"detail": "Archived PDF not available."}, status=404)
    response = FileResponse(path.open("rb"), content_type="application/pdf",
                            as_attachment=False, filename=f"investigation-{item_id}.pdf")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
