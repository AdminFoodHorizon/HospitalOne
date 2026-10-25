from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from hospital_core.models import Hospital, StaffMembership, HospitalEmailConfig
from hospital_core.hospital_email_views import email_settings, save_email_settings


class HospitalEmailPermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.hospital_a = Hospital.objects.create(name='Hospital A', slug='hospital-a')
        self.hospital_b = Hospital.objects.create(name='Hospital B', slug='hospital-b')
        self.user = get_user_model().objects.create_user(username='email-admin-test', password='test-password')
        StaffMembership.objects.create(user=self.user, hospital=self.hospital_a, role=StaffMembership.Role.ADMIN)
        HospitalEmailConfig.objects.create(hospital=self.hospital_a, email_address='a@gmail.com')
        HospitalEmailConfig.objects.create(hospital=self.hospital_b, email_address='b@gmail.com')

    def request(self, path, method='get', payload=None):
        import json
        if method == 'post':
            req = self.factory.post(path, data=json.dumps(payload or {}), content_type='application/json')
        else:
            req = self.factory.get(path)
        req.user = self.user
        SessionMiddleware(lambda request: None).process_request(req)
        req.session['hospital_2fa_verified'] = True
        req.session['hospital_2fa_slug'] = 'hospital-a'
        return req

    def test_own_hospital_settings_do_not_expose_secret(self):
        req = self.request('/api/hospital/hospital-a/email/settings/')
        response = email_settings(req, 'hospital-a')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'encrypted_app_password', response.content)
        self.assertNotIn(b'app_password', response.content)

    def test_cross_hospital_read_forbidden(self):
        req = self.request('/api/hospital/hospital-b/email/settings/')
        self.assertEqual(email_settings(req, 'hospital-b').status_code, 403)

    def test_cross_hospital_write_forbidden(self):
        req = self.request('/api/hospital/hospital-b/email/settings/', 'post', {'email_address': 'x@gmail.com'})
        self.assertEqual(save_email_settings(req, 'hospital-b').status_code, 403)

    def test_reception_cannot_manage_settings(self):
        membership = StaffMembership.objects.get(user=self.user, hospital=self.hospital_a)
        membership.role = StaffMembership.Role.RECEPTION
        membership.save()
        req = self.request('/api/hospital/hospital-a/email/settings/')
        self.assertEqual(email_settings(req, 'hospital-a').status_code, 403)

    @patch('hospital_core.hospital_email_views.verify_user_totp', return_value=False)
    def test_write_requires_fresh_2fa(self, mock_verify):
        req = self.request('/api/hospital/hospital-a/email/settings/', 'post', {
            'email_address': 'new@gmail.com', 'totp_code': '000000'
        })
        self.assertEqual(save_email_settings(req, 'hospital-a').status_code, 400)
        self.assertEqual(HospitalEmailConfig.objects.get(hospital=self.hospital_a).email_address, 'a@gmail.com')
