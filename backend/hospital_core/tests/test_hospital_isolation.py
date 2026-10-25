from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from hospital_core.hospital_isolation import validate_instance

class HospitalIsolationGuardTests(SimpleTestCase):
    def test_prescription_rejects_cross_hospital_medicine(self):
        from hospital_core.models import PrescriptionItem
        from hospital_core.models import Prescription, PatientVisit, MedicineCatalogItem
        visit = PatientVisit(hospital_id=1)
        prescription = Prescription(visit=visit)
        obj = PrescriptionItem(prescription=prescription, medicine=MedicineCatalogItem(hospital_id=2))
        with self.assertRaises(ValidationError):
            validate_instance(obj)

    def test_prescription_accepts_same_hospital(self):
        from hospital_core.models import PrescriptionItem
        from hospital_core.models import Prescription, PatientVisit, MedicineCatalogItem
        visit = PatientVisit(hospital_id=1)
        prescription = Prescription(visit=visit)
        obj = PrescriptionItem(prescription=prescription, medicine=MedicineCatalogItem(hospital_id=1))
        validate_instance(obj)
