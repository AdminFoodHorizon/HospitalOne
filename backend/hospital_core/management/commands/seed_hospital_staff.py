"""Create example hospital staff accounts interactively, without sample patients.

Install in hospital_core/management/commands/seed_hospital_staff.py
Run: python manage.py seed_hospital_staff --hospital green-valley-hospital
"""
from getpass import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from hospital_core.models import Department, DoctorProfile, Hospital, StaffMembership


STAFF = [
    # username suffix, role, department, first name, last name, room
    ('admin', 'ADMIN', None, 'Hospital', 'Administrator', ''),
    ('reception', 'RECEPTION', 'Reception', 'Asha', 'Reception', ''),
    ('nurse', 'NURSE', 'Nursing Station', 'Meera', 'Nurse', ''),
    ('doctor_general', 'DOCTOR', 'General Medicine', 'Arun', 'Physician', 'G-101'),
    ('doctor_cardiology', 'DOCTOR', 'Cardiology', 'Sara', 'Cardiologist', 'C-201'),
    ('lab_blood', 'LAB', 'Blood Laboratory', 'Ravi', 'Lab', ''),
    ('lab_xray', 'LAB', 'Radiology / X-ray', 'Nina', 'Radiology', ''),
    ('lab_ecg', 'LAB', 'ECG', 'Dev', 'ECG', ''),
    ('pharmacy', 'PHARMACY', 'Pharmacy', 'Priya', 'Pharmacist', ''),
]


class Command(BaseCommand):
    help = 'Interactively create example staff for one hospital; never creates patients.'

    def add_arguments(self, parser):
        parser.add_argument('--hospital', required=True, help='Existing hospital slug')

    def handle(self, *args, **options):
        try:
            hospital = Hospital.objects.get(slug=options['hospital'], is_active=True)
        except Hospital.DoesNotExist as exc:
            raise CommandError('Active hospital not found.') from exc

        User = get_user_model()
        if User.USERNAME_FIELD != 'username':
            raise CommandError('This command expects Django default username authentication.')

        departments = {d.name: d for d in Department.objects.filter(hospital=hospital, is_active=True)}
        missing = sorted({d for _, _, d, _, _, _ in STAFF if d and d not in departments})
        if missing:
            raise CommandError('Missing departments: ' + ', '.join(missing))

        prefix = hospital.slug.replace('-', '_')
        created = skipped = 0
        self.stdout.write(f'Hospital: {hospital.name}')
        self.stdout.write('Passwords are entered privately and are not saved in this file.')
        self.stdout.write('Existing usernames will be skipped; their passwords will NOT change.')

        for suffix, role, dept_name, first, last, room in STAFF:
            username = f'{prefix}_{suffix}'
            if User.objects.filter(username=username).exists():
                existing = User.objects.get(username=username)
                if not StaffMembership.objects.filter(user=existing, hospital=hospital, role=role).exists():
                    raise CommandError(f'Username {username} exists without expected membership. Resolve manually; no changes made to this account.')
                self.stdout.write(f'SKIPPED: {username} (already exists)')
                skipped += 1
                continue

            while True:
                password = getpass(f'Password for {username} (minimum 12 characters): ')
                if len(password) < 12:
                    self.stderr.write('Password must contain at least 12 characters.')
                    continue
                confirm = getpass('Confirm password: ')
                if password != confirm:
                    self.stderr.write('Passwords do not match. Try again.')
                    continue
                break

            with transaction.atomic():
                user = User.objects.create_user(username=username, password=password, first_name=first, last_name=last)
                user.is_staff = False
                user.is_superuser = False
                user.save(update_fields=['is_staff', 'is_superuser'])
                membership = StaffMembership(
                    user=user, hospital=hospital, role=role,
                    department=departments.get(dept_name), is_active=True,
                )
                membership.full_clean()
                membership.save()
                if role == 'DOCTOR':
                    profile = DoctorProfile(membership=membership, room_number=room, on_duty=False)
                    profile.full_clean()
                    profile.save()
            self.stdout.write(self.style.SUCCESS(f'CREATED: {username} ({role})'))
            created += 1

        self.stdout.write(self.style.SUCCESS(f'Finished. Created: {created}; already existed: {skipped}.'))
        self.stdout.write('Doctor accounts start OFF DUTY. Do not use fictional staff identities in production.')
        self.stdout.write('Accounts exist, but hospital login APIs and permissions still need implementation.')
