from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
import uuid
from django.db.models import Q
from django.utils import timezone
from .two_factor_models import (
    TwoFactorCredential,
    TwoFactorRecoveryCode,
    AuthenticationAuditLog,
)



class HospitalIsolationMixin(models.Model):
    """Reject cross-hospital relationships during ordinary ORM saves.

    Bulk operations bypass save(); API queries must remain hospital-scoped.
    """
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        from .hospital_isolation import validate_instance
        validate_instance(self)
        return super().save(*args, **kwargs)


class Hospital(models.Model):
    name = models.CharField(max_length=180)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)

    # Hospital address
    address_line1 = models.CharField(
        max_length=255, blank=True, default=""
    )
    address_line2 = models.CharField(
        max_length=255, blank=True, default=""
    )
    city = models.CharField(
        max_length=100, blank=True, default=""
    )
    state = models.CharField(
        max_length=100, blank=True, default=""
    )
    postal_code = models.CharField(
        max_length=20, blank=True, default=""
    )
    country = models.CharField(
        max_length=100, blank=True, default=""
    )

    # Contact information
    phone = models.CharField(
        max_length=30, blank=True, default=""
    )
    email = models.EmailField(
        blank=True, default=""
    )
    website = models.URLField(
        blank=True, default=""
    )

    # Homepage branding
    logo = models.ImageField(
        upload_to="hospital_branding/logos/",
        blank=True,
        null=True,
    )

    banner = models.ImageField(
        upload_to="hospital_branding/banners/",
        blank=True,
        null=True,
    )

    billing_currency = models.CharField(max_length=3, default='INR', help_text='ISO 4217 currency code for this hospital')

    tagline = models.CharField(
        max_length=180,
        blank=True,
        default="",
    )

    welcome_message = models.TextField(
        blank=True,
        default="",
    )

    footer_description = models.TextField(
        blank=True,
        default="",
    )

    def __str__(self):
        return self.name



class Department(models.Model):
    class Kind(models.TextChoices):
        RECEPTION = 'RECEPTION', 'Reception'
        NURSING = 'NURSING', 'Nursing'
        DOCTOR = 'DOCTOR', 'Doctor'
        LAB = 'LAB', 'Laboratory'
        RADIOLOGY = 'RADIOLOGY', 'Radiology'
        ECG = 'ECG', 'ECG'
        PHARMACY = 'PHARMACY', 'Pharmacy'
        OTHER = 'OTHER', 'Other'

    hospital = models.ForeignKey(Hospital, on_delete=models.PROTECT, related_name='departments')
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    is_active = models.BooleanField(default=True)
    room_number = models.CharField(
    max_length=30,
    blank=True,
    default="",
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=['hospital', 'name'], name='unique_department_name_per_hospital')]

    def __str__(self):
        return f'{self.hospital.slug}: {self.name}'


class StaffMembership(HospitalIsolationMixin, models.Model):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Hospital admin'
        RECEPTION = 'RECEPTION', 'Reception'
        NURSE = 'NURSE', 'Nurse'
        DOCTOR = 'DOCTOR', 'Doctor'
        LAB = 'LAB', 'Laboratory'
        PHARMACY = 'PHARMACY', 'Pharmacy'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='hospital_memberships')
    hospital = models.ForeignKey(Hospital, on_delete=models.PROTECT, related_name='staff_memberships')
    role = models.CharField(max_length=16, choices=Role.choices)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'hospital', 'role'], name='unique_staff_role_per_hospital')]

    def clean(self):
        if self.department_id and self.department.hospital_id != self.hospital_id:
            raise ValidationError('Staff department must belong to the same hospital.')

    def __str__(self):
        return f'{self.user_id} / {self.hospital.slug} / {self.role}'


class DoctorProfile(HospitalIsolationMixin, models.Model):
    membership = models.OneToOneField(StaffMembership, on_delete=models.PROTECT, related_name='doctor_profile')
    room_number = models.CharField(max_length=30, blank=True)
    on_duty = models.BooleanField(default=False)

    def clean(self):
        if self.membership_id and self.membership.role != StaffMembership.Role.DOCTOR:
            raise ValidationError('Doctor profile requires a doctor membership.')

    @property
    def hospital_id(self):
        return self.membership.hospital_id


class Patient(models.Model):
    hospital = models.ForeignKey(Hospital, on_delete=models.PROTECT, related_name='patients')
    patient_number = models.CharField(max_length=32)
    full_name = models.CharField(max_length=180)
    date_of_birth = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['hospital', 'patient_number'], name='unique_patient_number_per_hospital')]

    def __str__(self):
        return f'{self.patient_number} - {self.full_name}'


class PatientVisit(HospitalIsolationMixin, models.Model):
    class State(models.TextChoices):
        NURSING_INITIAL = 'NURSING_INITIAL', 'Initial nursing'
        DOCTOR_WAIT = 'DOCTOR_WAIT', 'Waiting for doctor'
        DOCTOR_ACTIVE = 'DOCTOR_ACTIVE', 'With doctor'
        TEST_POOL = 'TEST_POOL', 'Tests in progress'
        NURSING_RETURN = 'NURSING_RETURN', 'Return to nursing'
        DOCTOR_RECALL = 'DOCTOR_RECALL', 'Doctor recall queue'
        PHARMACY = 'PHARMACY', 'Pharmacy'
        COMPLETE = 'COMPLETE', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    hospital = models.ForeignKey(Hospital, on_delete=models.PROTECT, related_name='visits')
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='visits')
    visit_number = models.CharField(max_length=36)
    # Public-facing token; nullable to preserve existing visits.
    queue_token = models.CharField(max_length=24, null=True, blank=True)
    token_month = models.DateField(null=True, blank=True)
    registered_at = models.DateTimeField(default=timezone.now, db_index=True)
    assigned_doctor = models.ForeignKey(DoctorProfile, on_delete=models.PROTECT, related_name='assigned_visits')
    state = models.CharField(max_length=20, choices=State.choices, default=State.NURSING_INITIAL, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['hospital', 'visit_number'], name='unique_visit_number_per_hospital'),
            models.UniqueConstraint(fields=['hospital', 'token_month', 'queue_token'], name='unique_monthly_token_per_hospital'),
        ]
        indexes = [models.Index(fields=['hospital', 'assigned_doctor', 'state', 'registered_at'], name='doctor_queue_lookup_idx')]

    def clean(self):
        if self.patient_id and self.patient.hospital_id != self.hospital_id:
            raise ValidationError('Patient and visit must belong to the same hospital.')
        if self.assigned_doctor_id and self.assigned_doctor.membership.hospital_id != self.hospital_id:
            raise ValidationError('Assigned doctor must belong to the same hospital.')


class NursingAssessment(HospitalIsolationMixin, models.Model):
    visit = models.ForeignKey(PatientVisit, on_delete=models.PROTECT, related_name='nursing_assessments')
    nurse = models.ForeignKey(StaffMembership, on_delete=models.PROTECT)
    blood_pressure = models.CharField(max_length=20, blank=True)
    pulse_bpm = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)

    # Optional current-condition measurements. Empty readings remain NULL.
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    spo2_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    pain_score = models.PositiveSmallIntegerField(null=True, blank=True)

    notes = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    released_to_doctor_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        if self.nurse_id and (self.nurse.role != StaffMembership.Role.NURSE or self.nurse.hospital_id != self.visit.hospital_id):
            raise ValidationError('Nursing assessment requires a nurse from the visit hospital.')

        # These checks also apply when data is entered through the Django admin.
        ranges = {
            'height_cm': (20, 250),
            'weight_kg': (0.1, 500),
            'spo2_percent': (0, 100),
            'respiratory_rate': (0, 100),
            'pain_score': (0, 10),
        }
        errors = {}
        for field, (minimum, maximum) in ranges.items():
            value = getattr(self, field)
            if value is not None and not (minimum <= value <= maximum):
                errors[field] = f'Enter a value between {minimum} and {maximum}.'
        if errors:
            raise ValidationError(errors)


class PatientQueueEntry(HospitalIsolationMixin, models.Model):
    class Kind(models.TextChoices):
        NURSING_INITIAL = 'NURSING_INITIAL', 'Initial nursing'
        DOCTOR_INITIAL = 'DOCTOR_INITIAL', 'Doctor initial'
        TEST = 'TEST', 'Test department'
        RECEPTION_BILLING = 'RECEPTION_BILLING', 'Reception investigation billing'
        NURSING_RETURN = 'NURSING_RETURN', 'Return nursing'
        DOCTOR_RECALL = 'DOCTOR_RECALL', 'Doctor recall'
        PHARMACY = 'PHARMACY', 'Pharmacy'

    class Status(models.TextChoices):
        WAITING = 'WAITING', 'Waiting'
        CALLED = 'CALLED', 'Called'
        RECALL_PENDING = "RECALL_PENDING", "Waiting for Recall"
        DONE = 'DONE', 'Done'
        CANCELLED = 'CANCELLED', 'Cancelled'

    visit = models.ForeignKey(PatientVisit, on_delete=models.PROTECT, related_name='queue_entries')
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.WAITING)
    queued_at = models.DateTimeField(default=timezone.now, db_index=True)
    called_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['department', 'status', 'queued_at'], name='dept_queue_lookup_idx')]

    def clean(self):
        if self.department_id and self.visit_id and self.department.hospital_id != self.visit.hospital_id:
            raise ValidationError('Queue department must belong to visit hospital.')


class PatientAttendance(HospitalIsolationMixin, models.Model):
    """A single active physical attendance per visit; multiple historical rows allowed."""
    visit = models.ForeignKey(PatientVisit, on_delete=models.PROTECT, related_name='attendance_records')
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    staff = models.ForeignKey(StaffMembership, on_delete=models.PROTECT)
    started_at = models.DateTimeField(default=timezone.now)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['visit'], condition=Q(released_at__isnull=True), name='one_active_attendance_per_visit')]

    def clean(self):
        if self.visit_id and self.department_id and self.department.hospital_id != self.visit.hospital_id:
            raise ValidationError('Attendance department must match visit hospital.')
        if self.visit_id and self.staff_id and self.staff.hospital_id != self.visit.hospital_id:
            raise ValidationError('Attendance staff must match visit hospital.')


class PatientMovementEvent(HospitalIsolationMixin, models.Model):
    visit = models.ForeignKey(PatientVisit, on_delete=models.PROTECT, related_name='movement_events')
    from_state = models.CharField(max_length=24, blank=True)
    to_state = models.CharField(max_length=24)
    actor = models.ForeignKey(StaffMembership, on_delete=models.PROTECT)
    reason = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['created_at', 'pk']


class Consultation(HospitalIsolationMixin, models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        RECALL = 'RECALL', 'Recall pending'
        FINISHED = 'FINISHED', 'Finished'

    visit = models.ForeignKey(PatientVisit, on_delete=models.PROTECT, related_name='consultations')
    doctor = models.ForeignKey(DoctorProfile, on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    diagnosis = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)


class TestCatalogItem(HospitalIsolationMixin, models.Model):
    hospital = models.ForeignKey(Hospital, on_delete=models.PROTECT)
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=180)
    active = models.BooleanField(default=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    category = models.CharField(max_length=80, blank=True, default='')
    specimen_type = models.CharField(max_length=80, blank=True, default='')
    preparation_instructions = models.TextField(blank=True, default='')
    turnaround_hours = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['hospital', 'code'], name='unique_test_code_per_hospital')]

    def clean(self):
        if self.department_id and self.department.hospital_id != self.hospital_id:
            raise ValidationError('Test department must belong to same hospital.')


class TestOrder(HospitalIsolationMixin, models.Model):
    visit = models.ForeignKey(PatientVisit, on_delete=models.PROTECT, related_name='test_orders')
    consultation = models.ForeignKey(Consultation, on_delete=models.PROTECT, related_name='test_orders')
    ordered_at = models.DateTimeField(default=timezone.now)


class TestOrderItem(HospitalIsolationMixin, models.Model):
    class Status(models.TextChoices):
        WAITING = 'WAITING', 'Waiting'
        IN_PROGRESS = 'IN_PROGRESS', 'In progress'
        PERFORMED = 'PERFORMED', 'Performed, report pending'
        REPORT_READY = 'REPORT_READY', 'Report ready'
        CANCELLED = 'CANCELLED', 'Cancelled'

    order = models.ForeignKey(TestOrder, on_delete=models.PROTECT, related_name='items')
    test = models.ForeignKey(TestCatalogItem, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.WAITING)
    performed_at = models.DateTimeField(null=True, blank=True)
    report_ready_at = models.DateTimeField(null=True, blank=True)


class TestResult(HospitalIsolationMixin, models.Model):
    item = models.OneToOneField(TestOrderItem, on_delete=models.PROTECT, related_name='result')
    summary = models.TextField(blank=True)
    # A reference to a protected NAS file; not a publicly accessible URL.
    private_file_key = models.CharField(max_length=255, blank=True)
    verified_by = models.ForeignKey(StaffMembership, null=True, blank=True, on_delete=models.PROTECT)
    verified_at = models.DateTimeField(null=True, blank=True)


class MedicineCatalogItem(models.Model):
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text='Hospital-specific price; required before dispensing')
    hospital = models.ForeignKey(Hospital, on_delete=models.PROTECT)
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=180)
    active = models.BooleanField(default=True)
    generic_name = models.CharField(max_length=180, blank=True, default='')
    brand_name = models.CharField(max_length=180, blank=True, default='')
    strength = models.CharField(max_length=80, blank=True, default='')
    dosage_form = models.CharField(max_length=50, blank=True, default='')
    administration_route = models.CharField(max_length=50, blank=True, default='')
    pack_description = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['hospital', 'code'], name='unique_medicine_code_per_hospital')]


class Prescription(HospitalIsolationMixin, models.Model):
    visit = models.ForeignKey(PatientVisit, on_delete=models.PROTECT, related_name='prescriptions')
    consultation = models.ForeignKey(Consultation, on_delete=models.PROTECT, related_name='prescriptions')
    prescribed_at = models.DateTimeField(default=timezone.now)


class PrescriptionItem(HospitalIsolationMixin, models.Model):
    prescription = models.ForeignKey(Prescription, on_delete=models.PROTECT, related_name='items')
    medicine = models.ForeignKey(MedicineCatalogItem, on_delete=models.PROTECT)
    dose = models.CharField(max_length=100)
    route = models.CharField(max_length=60)
    frequency = models.CharField(max_length=100)
    duration = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField()
    instructions = models.TextField(blank=True)


class DispenseRecord(HospitalIsolationMixin, models.Model):
    item = models.ForeignKey(PrescriptionItem, on_delete=models.PROTECT, related_name='dispensings')
    pharmacist = models.ForeignKey(StaffMembership, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    dispensed_at = models.DateTimeField(default=timezone.now)


class PharmacyDispense(HospitalIsolationMixin, models.Model):
    class Status(models.TextChoices):
        FINAL = 'FINAL', 'Finalized'
    visit = models.OneToOneField(PatientVisit, on_delete=models.PROTECT, related_name='pharmacy_dispense')
    pharmacist = models.ForeignKey(StaffMembership, on_delete=models.PROTECT)
    finalized_at = models.DateTimeField(default=timezone.now)
    currency = models.CharField(max_length=3)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.FINAL)
    bill_number = models.CharField(max_length=70, unique=True)


class PharmacyDispenseLine(HospitalIsolationMixin, models.Model):
    dispense = models.ForeignKey(PharmacyDispense, on_delete=models.PROTECT, related_name='lines')
    prescription_item = models.OneToOneField(PrescriptionItem, on_delete=models.PROTECT)
    medicine_code = models.CharField(max_length=40)
    medicine_name = models.CharField(max_length=180)
    prescribed_quantity = models.PositiveIntegerField()
    dispensed_quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)
    dose = models.CharField(max_length=100)
    route = models.CharField(max_length=60)
    frequency = models.CharField(max_length=100)
    duration = models.CharField(max_length=100)
    instructions = models.TextField(blank=True)


class HospitalMonthlyTokenCounter(models.Model):
    """One atomic counter per hospital and calendar month."""
    hospital = models.ForeignKey(Hospital, on_delete=models.PROTECT, related_name='monthly_token_counters')
    month = models.DateField(help_text='First calendar day of the month, in hospital local time')
    prefix = models.CharField(max_length=1)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['hospital', 'month'], name='unique_hospital_token_month'),
        ]

    def clean(self):
        if self.month and self.month.day != 1:
            raise ValidationError('Counter month must be the first day of the month.')
        if self.prefix and (len(self.prefix) != 1 or not self.prefix.isascii() or not self.prefix.isalpha() or not self.prefix.isupper()):
            raise ValidationError('Prefix must be one uppercase A-Z letter.')


class AnnouncementEvent(models.Model):
    """
    One event for each successful patient call.

    Stores only public-safe announcement information.
    """

    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.PROTECT,
        related_name="announcement_events",
    )

    queue_entry = models.ForeignKey(
        PatientQueueEntry,
        on_delete=models.PROTECT,
        related_name="announcement_events",
    )

    called_by = models.ForeignKey(
        StaffMembership,
        on_delete=models.PROTECT,
        related_name="announcement_events",
    )

    token = models.CharField(max_length=24)

    department_name = models.CharField(max_length=120)

    room_number = models.CharField(max_length=30)

    called_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(
                fields=["hospital", "-id"],
                name="announcement_hospital_idx",
            ),
        ]

    def __str__(self):
        return f"{self.hospital.slug} / {self.token} / {self.department_name}"



class HospitalDisplayDevice(models.Model):
    """
    A hospital-authorized announcement display device.

    Pairing credentials will be handled separately.
    Never store plaintext device credentials here.
    """

    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.PROTECT,
        related_name="display_devices",
    )

    name = models.CharField(
        max_length=120,
    )

    device_id = models.UUIDField(
        unique=True,
        editable=False,
        default=uuid.uuid4,
    )

    credential_hash = models.CharField(
        max_length=128,
        blank=True,
        default="",
    )

    is_active = models.BooleanField(
        default=False,
    )

    paired_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    credential_expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    last_seen_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        default=timezone.now,
    )

    class Meta:
        ordering = ["hospital_id", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["hospital", "name"],
                name="unique_display_name_per_hospital",
            ),
        ]

    def __str__(self):
        return f"{self.hospital.slug} / {self.name}"


class HospitalDisplayPairingRequest(models.Model):
    """
    Temporary pairing request initiated by a hospital TV.

    The TV generates a pairing request.
    An authorized administrator approves it.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        EXPIRED = "EXPIRED", "Expired"
        CONSUMED = "CONSUMED", "Consumed"

    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.PROTECT,
        related_name="display_pairing_requests",
    )

    request_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    pairing_code_hash = models.CharField(
        max_length=64,
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )

    device_name = models.CharField(
        max_length=120,
        default="Central Announcement TV",
    )

    created_at = models.DateTimeField(
        default=timezone.now,
    )

    expires_at = models.DateTimeField()

    approved_by = models.ForeignKey(
        StaffMembership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_display_pairings",
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    device = models.ForeignKey(
        HospitalDisplayDevice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pairing_requests",
    )

    pairing_secret_hash = models.CharField(
    max_length=64,
    blank=True,
    default="",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["hospital", "status"],
                name="display_pairing_status_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.hospital.slug} / "
            f"{self.device_name} / "
            f"{self.status}"
        )


# ============================================================
# INVESTIGATION BILLING (NO PAYMENTS ARE HANDLED BY THIS APP)
# ============================================================

class InvestigationBill(HospitalIsolationMixin, models.Model):
    """A printable price summary and reception routing checkpoint per test order."""

    class Status(models.TextChoices):
        WAITING_RECEPTION = 'WAITING_RECEPTION', 'Waiting at reception'
        RELEASED = 'RELEASED', 'Sent to investigations'
        CANCELLED = 'CANCELLED', 'Cancelled'

    hospital = models.ForeignKey(Hospital, on_delete=models.PROTECT, related_name='investigation_bills')
    visit = models.ForeignKey(PatientVisit, on_delete=models.PROTECT, related_name='investigation_bills')
    test_order = models.OneToOneField(TestOrder, on_delete=models.PROTECT, related_name='investigation_bill')
    reception_queue_entry = models.OneToOneField(
        PatientQueueEntry, null=True, blank=True, on_delete=models.PROTECT,
        related_name='investigation_bill',
    )
    bill_number = models.CharField(max_length=40, null=True, blank=True)
    currency = models.CharField(max_length=3, default='INR')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.WAITING_RECEPTION, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        StaffMembership, null=True, blank=True, on_delete=models.PROTECT,
        related_name='released_investigation_bills',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['hospital', 'bill_number'], name='unique_invest_bill_no_per_hosp'),
        ]
        indexes = [
            models.Index(fields=['hospital', 'status', 'created_at'], name='invest_bill_lookup_idx'),
        ]

    def clean(self):
        errors = {}
        if self.visit_id and self.hospital_id != self.visit.hospital_id:
            errors['visit'] = 'Visit must belong to the bill hospital.'
        if self.test_order_id and self.visit_id and self.test_order.visit_id != self.visit_id:
            errors['test_order'] = 'Test order must belong to this visit.'
        if self.reception_queue_entry_id and self.visit_id:
            entry = self.reception_queue_entry
            if entry.visit_id != self.visit_id or entry.kind != PatientQueueEntry.Kind.RECEPTION_BILLING:
                errors['reception_queue_entry'] = 'Expected reception billing queue for this visit.'
            elif entry.department.hospital_id != self.hospital_id or entry.department.kind != Department.Kind.RECEPTION:
                errors['reception_queue_entry'] = 'Reception queue must belong to this hospital.'
        if self.released_by_id and self.released_by.hospital_id != self.hospital_id:
            errors['released_by'] = 'Releasing staff must belong to the hospital.'
        if self.total_amount < 0:
            errors['total_amount'] = 'Bill total cannot be negative.'
        if errors:
            raise ValidationError(errors)


class InvestigationBillLine(HospitalIsolationMixin, models.Model):
    """Price snapshot: later catalog price changes do not alter old bills."""
    bill = models.ForeignKey(InvestigationBill, on_delete=models.PROTECT, related_name='lines')
    test_order_item = models.OneToOneField(
        TestOrderItem, on_delete=models.PROTECT, related_name='investigation_bill_line',
        null=True, blank=True,
    )
    test_code = models.CharField(max_length=40,default="")
    test_name = models.CharField(max_length=180, default="")
    department_name = models.CharField(max_length=120,default="")
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    def clean(self):
        errors = {}
        if self.bill_id and self.test_order_item_id and self.test_order_item.order_id != self.bill.test_order_id:
            errors['test_order_item'] = 'Investigation must belong to the bill test order.'
        if self.amount < 0:
            errors['amount'] = 'Investigation amount cannot be negative.'
        if errors:
            raise ValidationError(errors)

# ============================================================
# STAGE 5A: CONFIGURABLE INVESTIGATION REPORT STRUCTURE
# Additive models; existing TestResult and queues remain intact.
# ============================================================

class InvestigationReportTemplate(HospitalIsolationMixin, models.Model):
    class Format(models.TextChoices):
        LAB_PANEL = 'LAB_PANEL', 'Laboratory panel'
        IMAGING = 'IMAGING', 'Imaging (X-ray, CT, MRI, ultrasound)'
        CARDIAC = 'CARDIAC', 'Cardiac (ECG, Echo)'
        PROCEDURE = 'PROCEDURE', 'Other procedure'

    hospital = models.ForeignKey(Hospital, on_delete=models.PROTECT, related_name='report_templates')
    test = models.ForeignKey(TestCatalogItem, on_delete=models.PROTECT, related_name='report_templates')
    name = models.CharField(max_length=180)
    format = models.CharField(max_length=20, choices=Format.choices)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['test', 'version'], name='unique_report_template_version')]

    def clean(self):
        if self.test_id and self.hospital_id != self.test.hospital_id:
            raise ValidationError({'test': 'Report template and test must belong to the same hospital.'})

    def __str__(self):
        return f'{self.name} v{self.version}'


class InvestigationReportField(models.Model):
    class ValueType(models.TextChoices):
        NUMBER = 'NUMBER', 'Number'
        TEXT = 'TEXT', 'Text'
        LONG_TEXT = 'LONG_TEXT', 'Long text'
        CHOICE = 'CHOICE', 'Choice'
        BOOLEAN = 'BOOLEAN', 'Yes/No'
        DATE = 'DATE', 'Date'

    template = models.ForeignKey(InvestigationReportTemplate, on_delete=models.PROTECT, related_name='fields')
    key = models.SlugField(max_length=80)
    label = models.CharField(max_length=180)
    section = models.CharField(max_length=120, blank=True)
    value_type = models.CharField(max_length=16, choices=ValueType.choices)
    unit = models.CharField(max_length=40, blank=True)
    # Optional defaults only. Clinically approved reference intervals may depend
    # on age, sex, methodology and instrument; do not use these for automatic
    # clinical interpretation without an approved range-selection policy.
    reference_text = models.CharField(max_length=180, blank=True)
    choice_options = models.JSONField(default=list, blank=True)
    required = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'pk']
        constraints = [models.UniqueConstraint(fields=['template', 'key'], name='unique_report_field_key')]

    def clean(self):
        if self.value_type == self.ValueType.CHOICE and (not isinstance(self.choice_options, list) or not all(isinstance(x, str) for x in self.choice_options)):
            raise ValidationError({'choice_options': 'Choice fields require a list of text options.'})


class InvestigationReport(HospitalIsolationMixin, models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        IN_REVIEW = 'IN_REVIEW', 'Awaiting verification'
        FINAL = 'FINAL', 'Final'
        AMENDED = 'AMENDED', 'Amended'

    item = models.OneToOneField(TestOrderItem, on_delete=models.PROTECT, related_name='structured_report')
    template = models.ForeignKey(InvestigationReportTemplate, on_delete=models.PROTECT, related_name='reports')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    findings = models.TextField(blank=True)
    impression = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    created_by = models.ForeignKey(StaffMembership, on_delete=models.PROTECT, related_name='created_investigation_reports')
    verified_by = models.ForeignKey(StaffMembership, null=True, blank=True, on_delete=models.PROTECT, related_name='verified_investigation_reports')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)

    def clean(self):
        errors = {}
        if self.item_id and self.template_id and self.template.test_id != self.item.test_id:
            errors['template'] = 'Template must match the ordered test.'
        if self.created_by_id and self.item_id and self.created_by.hospital_id != self.item.order.visit.hospital_id:
            errors['created_by'] = 'Author must belong to the patient hospital.'
        if self.verified_by_id and self.item_id and self.verified_by.hospital_id != self.item.order.visit.hospital_id:
            errors['verified_by'] = 'Verifier must belong to the patient hospital.'
        if self.status in (self.Status.FINAL, self.Status.AMENDED) and (not self.verified_by_id or not self.verified_at):
            errors['status'] = 'Final reports require a verifier and verification timestamp.'
        if errors:
            raise ValidationError(errors)


class InvestigationReportValue(HospitalIsolationMixin, models.Model):
    report = models.ForeignKey(InvestigationReport, on_delete=models.PROTECT, related_name='values')
    field = models.ForeignKey(InvestigationReportField, on_delete=models.PROTECT, related_name='entered_values')
    value = models.JSONField(null=True, blank=True)
    # A flag is a verified report attribute, not a diagnosis.
    flag = models.CharField(max_length=24, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['report', 'field'], name='unique_report_field_value')]

    def clean(self):
        if self.report_id and self.field_id and self.field.template_id != self.report.template_id:
            raise ValidationError({'field': 'Result field must belong to the report template.'})


class InvestigationReportRevision(HospitalIsolationMixin, models.Model):
    """Immutable-by-application snapshot, recorded before report amendment.

    Application code must create revisions transactionally and enforce that
    finalized reports are not edited in place. Database model alone does not
    implement tamper-proof audit logging.
    """
    report = models.ForeignKey(InvestigationReport, on_delete=models.PROTECT, related_name='revisions')
    revision = models.PositiveIntegerField()
    snapshot = models.JSONField()
    changed_by = models.ForeignKey(StaffMembership, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['report', 'revision'], name='unique_report_revision')]


class HospitalEmailConfig(models.Model):
    """
    One email configuration per hospital.

    Gmail App Passwords must be encrypted before saving.
    Never store plaintext passwords in this model.
    """

    hospital = models.OneToOneField(
        "hospital_core.Hospital",
        on_delete=models.PROTECT,
        related_name="email_config",
    )

    email_address = models.EmailField(
        max_length=254,
    )

    encrypted_app_password = models.TextField(
        blank=True,
        default="",
    )

    smtp_host = models.CharField(
        max_length=255,
        default="smtp.gmail.com",
    )

    smtp_port = models.PositiveIntegerField(
        default=587,
    )

    use_tls = models.BooleanField(
        default=True,
    )

    is_enabled = models.BooleanField(
        default=False,
    )

    last_tested_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        default=timezone.now,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return f"Email configuration for hospital {self.hospital_id}"


class ReceptionReportEmailReceipt(models.Model):
    hospital = models.ForeignKey('hospital_core.Hospital', on_delete=models.PROTECT)
    visit = models.ForeignKey('hospital_core.PatientVisit', on_delete=models.PROTECT)
    item = models.ForeignKey('hospital_core.TestOrderItem', on_delete=models.PROTECT)
    report = models.ForeignKey('hospital_core.InvestigationReport', on_delete=models.PROTECT)
    report_verified_at = models.DateTimeField()
    recipient_email = models.EmailField()
    accepted_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey('hospital_core.StaffMembership', on_delete=models.PROTECT)

    class Meta:
        indexes = [models.Index(fields=['hospital', 'visit', 'item'], name='reception_email_visit_idx')]


