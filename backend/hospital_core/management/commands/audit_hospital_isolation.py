"""Read-only check for cross-hospital relationships in existing records."""
from django.core.management.base import BaseCommand
from django.db.models import F
from hospital_core.models import (PatientVisit, Consultation, PrescriptionItem,
    TestOrderItem, InvestigationReport, PharmacyDispense, NursingAssessment,
    PatientQueueEntry, PatientAttendance, TestCatalogItem)

CHECKS = (
    (PatientVisit, 'hospital_id', 'patient__hospital_id'),
    (PatientVisit, 'hospital_id', 'assigned_doctor__membership__hospital_id'),
    (Consultation, 'visit__hospital_id', 'doctor__membership__hospital_id'),
    (PrescriptionItem, 'prescription__visit__hospital_id', 'medicine__hospital_id'),
    (TestOrderItem, 'order__visit__hospital_id', 'test__hospital_id'),
    (InvestigationReport, 'item__order__visit__hospital_id', 'created_by__hospital_id'),
    (InvestigationReport, 'item__order__visit__hospital_id', 'template__hospital_id'),
    (PharmacyDispense, 'visit__hospital_id', 'pharmacist__hospital_id'),
    (NursingAssessment, 'visit__hospital_id', 'nurse__hospital_id'),
    (PatientQueueEntry, 'visit__hospital_id', 'department__hospital_id'),
    (PatientAttendance, 'visit__hospital_id', 'staff__hospital_id'),
    (TestCatalogItem, 'hospital_id', 'department__hospital_id'),
)

class Command(BaseCommand):
    help = 'Read-only HospitalOne hospital-isolation consistency audit'

    def handle(self, *args, **kwargs):
        total = 0
        for model, left, right in CHECKS:
            bad = model.objects.exclude(**{left: F(right)})
            count = bad.count()
            total += count
            self.stdout.write(f'{model.__name__}: {left} != {right}: {count} (example PKs: {list(bad.values_list("pk", flat=True)[:10])})')
        if total:
            self.stderr.write(self.style.ERROR(f'{total} cross-hospital inconsistencies. Do not deploy until reviewed.'))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS('No cross-hospital inconsistencies found in audited relationships.'))
