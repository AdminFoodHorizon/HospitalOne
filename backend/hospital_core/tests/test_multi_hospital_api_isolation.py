"""Integration tests for slug-scoped HospitalOne API isolation.

Run: python manage.py test hospital_core.test_multi_hospital_api_isolation
Uses Django's disposable test database; does not alter production records.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from hospital_core.models import Hospital, StaffMembership, Patient, PatientVisit, DoctorProfile


class TwoHospitalIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Hospital.objects.create(name='Isolation Test Hospital A', slug='isolation-test-a')
        cls.b = Hospital.objects.create(name='Isolation Test Hospital B', slug='isolation-test-b')
        User = get_user_model()
        cls.reception_a = User.objects.create_user(username='isolation_reception_a', password='test-only-strong-pass')
        cls.reception_b = User.objects.create_user(username='isolation_reception_b', password='test-only-strong-pass')
        cls.pharmacist_a = User.objects.create_user(username='isolation_pharmacy_a', password='test-only-strong-pass')
        cls.pharmacist_b = User.objects.create_user(username='isolation_pharmacy_b', password='test-only-strong-pass')
        cls.doctor_user_a = User.objects.create_user(username='isolation_doctor_a', password='test-only-strong-pass')
        cls.doctor_user_b = User.objects.create_user(username='isolation_doctor_b', password='test-only-strong-pass')
        for hospital, reception, pharmacy, doctor_user in (
            (cls.a, cls.reception_a, cls.pharmacist_a, cls.doctor_user_a),
            (cls.b, cls.reception_b, cls.pharmacist_b, cls.doctor_user_b),
        ):
            StaffMembership.objects.create(user=reception, hospital=hospital, role=StaffMembership.Role.RECEPTION)
            StaffMembership.objects.create(user=pharmacy, hospital=hospital, role=StaffMembership.Role.PHARMACY)
            membership = StaffMembership.objects.create(user=doctor_user, hospital=hospital, role=StaffMembership.Role.DOCTOR)
            doctor = DoctorProfile.objects.create(membership=membership, on_duty=True)
            patient = Patient.objects.create(hospital=hospital, patient_number=f'PAT-{hospital.slug}', full_name=f'Patient {hospital.slug}')
            PatientVisit.objects.create(hospital=hospital, patient=patient, assigned_doctor=doctor,
                                        visit_number=f'VIS-{hospital.slug}', state=PatientVisit.State.PHARMACY)
        cls.patient_a = Patient.objects.get(hospital=cls.a)
        cls.patient_b = Patient.objects.get(hospital=cls.b)
        cls.visit_a = PatientVisit.objects.get(hospital=cls.a)
        cls.visit_b = PatientVisit.objects.get(hospital=cls.b)

    def authenticate(self, user, hospital):
        self.client.force_login(user)
        session = self.client.session
        session['hospital_2fa_verified'] = True
        session['hospital_2fa_slug'] = hospital.slug
        session.save()

    def url(self, hospital, path):
        return f'/api/hospital/{hospital.slug}/{path}'

    def test_reception_history_search_only_returns_own_hospital(self):
        self.authenticate(self.reception_a, self.a)
        response = self.client.get(self.url(self.a, 'reception/patient-history/'), {'q': 'Patient'})
        self.assertEqual(response.status_code, 200, response.content)
        results = response.json()['results']
        self.assertEqual({p['number'] for p in results}, {self.patient_a.patient_number})

    def test_reception_history_rejects_other_hospital_patient(self):
        self.authenticate(self.reception_a, self.a)
        response = self.client.get(self.url(self.a, f'reception/patient-history/{self.patient_b.pk}/visits/'))
        self.assertEqual(response.status_code, 404, response.content)

    def test_reception_visit_detail_rejects_other_hospital_visit(self):
        self.authenticate(self.reception_a, self.a)
        response = self.client.get(self.url(self.a, f'reception/visit-history/{self.visit_b.pk}/'))
        self.assertEqual(response.status_code, 404, response.content)

    def test_pharmacy_visit_detail_rejects_other_hospital_visit(self):
        self.authenticate(self.pharmacist_a, self.a)
        response = self.client.get(self.url(self.a, f'pharmacy/visits/{self.visit_b.pk}/'))
        self.assertEqual(response.status_code, 404, response.content)

    def test_pharmacy_queue_excludes_other_hospital_visit(self):
        self.authenticate(self.pharmacist_a, self.a)
        response = self.client.get(self.url(self.a, 'pharmacy/queue/'))
        self.assertEqual(response.status_code, 200, response.content)
        ids = {entry['id'] for entry in response.json()['results']}
        self.assertIn(self.visit_a.pk, ids)
        self.assertNotIn(self.visit_b.pk, ids)

    def test_slug_switch_is_forbidden_even_with_valid_2fa(self):
        self.authenticate(self.reception_a, self.a)
        response = self.client.get(self.url(self.b, 'reception/patient-history/'), {'q': 'Patient'})
        self.assertEqual(response.status_code, 403, response.content)

    def test_reception_cannot_read_pharmacy_queue(self):
        self.authenticate(self.reception_a, self.a)
        response = self.client.get(self.url(self.a, 'pharmacy/queue/'))
        self.assertEqual(response.status_code, 403, response.content)

    def test_pharmacy_cannot_read_patient_history(self):
        self.authenticate(self.pharmacist_a, self.a)
        response = self.client.get(self.url(self.a, 'reception/patient-history/'), {'q': 'Patient'})
        self.assertEqual(response.status_code, 403, response.content)

    def test_unverified_2fa_cannot_read_patient_history(self):
        self.client.force_login(self.reception_a)
        response = self.client.get(self.url(self.a, 'reception/patient-history/'), {'q': 'Patient'})
        self.assertEqual(response.status_code, 403, response.content)

    def test_cross_hospital_pharmacy_finalize_cannot_write(self):
        self.authenticate(self.pharmacist_a, self.a)
        response = self.client.post(self.url(self.a, f'pharmacy/visits/{self.visit_b.pk}/finalize/'),
                                    data='{"quantities":{}}', content_type='application/json')
        self.assertEqual(response.status_code, 404, response.content)
        self.visit_b.refresh_from_db()
        self.assertEqual(self.visit_b.state, PatientVisit.State.PHARMACY)

    def test_cross_hospital_reception_finalize_cannot_write(self):
        self.authenticate(self.reception_a, self.a)
        response = self.client.post(self.url(self.a, f'reception/pharmacy-completed/{self.visit_b.pk}/finalize/'),
                                    data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 404, response.content)
        self.visit_b.refresh_from_db()
        self.assertEqual(self.visit_b.state, PatientVisit.State.PHARMACY)
