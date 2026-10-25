"""Seed example departments for an EXISTING hospital.

Install as hospital_core/management/commands/seed_hospital_departments.py
Run: python manage.py seed_hospital_departments --hospital YOUR-HOSPITAL-SLUG
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from hospital_core.models import Department, Hospital


DEPARTMENTS = (
    ("Reception", Department.Kind.RECEPTION),
    ("Nursing Station", Department.Kind.NURSING),
    ("General Medicine", Department.Kind.DOCTOR),
    ("Cardiology", Department.Kind.DOCTOR),
    ("Orthopedics", Department.Kind.DOCTOR),
    ("Pediatrics", Department.Kind.DOCTOR),
    ("Blood Laboratory", Department.Kind.LAB),
    ("Radiology / X-ray", Department.Kind.RADIOLOGY),
    ("ECG", Department.Kind.ECG),
    ("Pharmacy", Department.Kind.PHARMACY),
)


class Command(BaseCommand):
    help = "Create standard departments for one existing hospital without overwriting records."

    def add_arguments(self, parser):
        parser.add_argument("--hospital", required=True, help="Existing hospital slug")

    @transaction.atomic
    def handle(self, *args, **options):
        slug = options["hospital"]
        try:
            hospital = Hospital.objects.get(slug=slug)
        except Hospital.DoesNotExist as exc:
            raise CommandError(
                f"Hospital with slug '{slug}' not found. "
                "Check Django Admin > Hospitals for the correct slug."
            ) from exc

        created_count = 0
        existing_count = 0
        for name, kind in DEPARTMENTS:
            department, created = Department.objects.get_or_create(
                hospital=hospital,
                name=name,
                defaults={"kind": kind, "is_active": True},
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"CREATED: {name} ({kind})"))
            else:
                existing_count += 1
                if department.kind != kind:
                    self.stdout.write(self.style.WARNING(
                        f"EXISTS: {name} — existing kind {department.kind}, "
                        f"example kind {kind}; left unchanged"
                    ))
                else:
                    self.stdout.write(f"EXISTS: {name} ({kind}); left unchanged")

        self.stdout.write(self.style.SUCCESS(
            f"Hospital: {hospital.name} | Created: {created_count} | "
            f"Already existed: {existing_count}"
        ))
        self.stdout.write("No patients, staff accounts, or doctor profiles were created.")
