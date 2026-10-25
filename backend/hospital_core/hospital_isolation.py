"""HospitalOne cross-hospital relationship guard. No URL or API changes.

Runs on normal model.save()/objects.create(). Bulk operations bypass it.
Never use a numeric record ID as authorization: views must scope to staff hospital.
"""
from django.core.exceptions import ValidationError

RULES = {'StaffMembership': [('hospital_id', 'department.hospital_id')], 'DoctorProfile': [('membership.role', 'DOCTOR')], 'PatientVisit': [('hospital_id', 'patient.hospital_id'), ('hospital_id', 'assigned_doctor.membership.hospital_id')], 'NursingAssessment': [('visit.hospital_id', 'nurse.hospital_id'), ('nurse.role', 'NURSE')], 'PatientQueueEntry': [('visit.hospital_id', 'department.hospital_id')], 'PatientAttendance': [('visit.hospital_id', 'department.hospital_id'), ('visit.hospital_id', 'staff.hospital_id')], 'PatientMovementEvent': [('visit.hospital_id', 'actor.hospital_id')], 'Consultation': [('visit.hospital_id', 'doctor.membership.hospital_id')], 'TestCatalogItem': [('hospital_id', 'department.hospital_id')], 'TestOrder': [('visit_id', 'consultation.visit_id')], 'TestOrderItem': [('order.visit.hospital_id', 'test.hospital_id')], 'TestResult': [('item.order.visit.hospital_id', 'verified_by.hospital_id')], 'Prescription': [('visit_id', 'consultation.visit_id')], 'PrescriptionItem': [('prescription.visit.hospital_id', 'medicine.hospital_id')], 'DispenseRecord': [('item.prescription.visit.hospital_id', 'pharmacist.hospital_id')], 'PharmacyDispense': [('visit.hospital_id', 'pharmacist.hospital_id')], 'PharmacyDispenseLine': [('dispense.visit_id', 'prescription_item.prescription.visit_id')], 'InvestigationBill': [('hospital_id', 'visit.hospital_id'), ('visit_id', 'test_order.visit_id'), ('hospital_id', 'released_by.hospital_id'), ('visit_id', 'reception_queue_entry.visit_id')], 'InvestigationBillLine': [('bill.test_order_id', 'test_order_item.order_id')], 'InvestigationReportTemplate': [('hospital_id', 'test.hospital_id')], 'InvestigationReport': [('item.test_id', 'template.test_id'), ('item.order.visit.hospital_id', 'created_by.hospital_id'), ('item.order.visit.hospital_id', 'verified_by.hospital_id')], 'InvestigationReportValue': [('report.template_id', 'field.template_id')], 'InvestigationReportRevision': [('report.item.order.visit.hospital_id', 'changed_by.hospital_id')]}


def _resolve(obj, path):
    current = obj
    for name in path.split('.'):
        if current is None:
            return None
        current = getattr(current, name)
    return current


def validate_instance(instance):
    for left, right in RULES.get(type(instance).__name__, ()):
        # Optional relations are allowed to be NULL; required fields are checked by Django/DB.
        lhs = _resolve(instance, left)
        rhs = _resolve(instance, right) if '.' in right else right
        if lhs is not None and rhs is not None and lhs != rhs:
            raise ValidationError({"__all__": [
                f"Hospital isolation violation: {type(instance).__name__} ({left} != {right})."
            ]})
