"""Seed demonstration medicine and investigation catalog entries for one hospital."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from hospital_core.models import Hospital, Department, MedicineCatalogItem, TestCatalogItem

MEDICINES = [
    ('MED001', 'Paracetamol'), ('MED002', 'Ibuprofen'),
    ('MED003', 'Amoxicillin'), ('MED004', 'Azithromycin'),
    ('MED005', 'Cetirizine'), ('MED006', 'Loratadine'),
    ('MED007', 'Omeprazole'), ('MED008', 'Pantoprazole'),
    ('MED009', 'Metformin'), ('MED010', 'Amlodipine'),
    ('MED011', 'Losartan'), ('MED012', 'Atorvastatin'),
    ('MED013', 'Salbutamol'), ('MED014', 'Ondansetron'),
    ('MED015', 'Oral Rehydration Salts'), ('MED016', 'Ferrous Sulfate'),
    ('MED017', 'Folic Acid'), ('MED018', 'Vitamin D3'),
    ('MED019', 'Doxycycline'), ('MED020', 'Clotrimazole'),
]
TESTS = [
    ('LAB001', 'Complete Blood Count (CBC)', 'LAB'),
    ('LAB002', 'Blood Glucose (Fasting)', 'LAB'),
    ('LAB003', 'HbA1c', 'LAB'),
    ('LAB004', 'Lipid Profile', 'LAB'),
    ('LAB005', 'Liver Function Tests', 'LAB'),
    ('LAB006', 'Renal Function Tests', 'LAB'),
    ('LAB007', 'Thyroid Stimulating Hormone (TSH)', 'LAB'),
    ('LAB008', 'Urine Routine Examination', 'LAB'),
    ('LAB009', 'C-Reactive Protein (CRP)', 'LAB'),
    ('LAB010', 'Serum Electrolytes', 'LAB'),
    ('LAB011', 'Blood Group and Rh Typing', 'LAB'),
    ('LAB012', 'Serum Ferritin', 'LAB'),
    ('RAD001', 'Chest X-ray', 'RADIOLOGY'),
    ('RAD002', 'Knee X-ray', 'RADIOLOGY'),
    ('RAD003', 'Abdominal Ultrasound', 'RADIOLOGY'),
    ('RAD004', 'Pelvic Ultrasound', 'RADIOLOGY'),
    ('ECG001', '12-Lead ECG', 'ECG'),
    ('ECG002', 'Resting ECG', 'ECG'),
]


def find_department(hospital, target):
    departments = list(Department.objects.filter(hospital=hospital))
    aliases = {
        'LAB': ('LAB', 'LABORATORY', 'PATHOLOGY'),
        'RADIOLOGY': ('RADIOLOGY', 'XRAY', 'X-RAY', 'IMAGING'),
        'ECG': ('ECG', 'CARDIOLOGY', 'EKG'),
    }
    matches = aliases[target]
    for department in departments:
        if str(getattr(department, 'kind', '')).upper() in matches:
            return department
    for department in departments:
        if any(alias in str(getattr(department, 'name', '')).upper() for alias in matches):
            return department
    return None


class Command(BaseCommand):
    help = 'Seed example medicines and investigations for a hospital (safe to rerun).'

    def add_arguments(self, parser):
        parser.add_argument('--hospital', required=True, help='Hospital slug, e.g. green-valley-hospital')
        parser.add_argument('--dry-run', action='store_true', help='Show changes without writing')

    def handle(self, *args, **options):
        slug = options['hospital']
        hospital = Hospital.objects.filter(slug=slug).first()
        if not hospital:
            raise CommandError(f'Hospital slug not found: {slug}')

        # Verify expected model fields before any writes.
        for model, required in (
            (MedicineCatalogItem, ('hospital', 'code', 'name', 'active')),
            (TestCatalogItem, ('hospital', 'code', 'name', 'active', 'department')),
        ):
            names = {field.name for field in model._meta.fields}
            missing = set(required) - names
            if missing:
                raise CommandError(f'{model.__name__} lacks expected fields: {sorted(missing)}')

        department_map = {key: find_department(hospital, key) for key in ('LAB', 'RADIOLOGY', 'ECG')}
        self.stdout.write(f'Hospital: {hospital.name} ({slug})')
        for key, dep in department_map.items():
            self.stdout.write(f'{key}: {dep.name if dep else "NOT FOUND — related tests will be skipped"}')
        created_meds = created_tests = existing_meds = existing_tests = skipped = 0
        with transaction.atomic():
            for code, name in MEDICINES:
                obj, created = MedicineCatalogItem.objects.get_or_create(
                    hospital=hospital, code=code, defaults={'name': name, 'active': True},
                )
                created_meds += int(created)
                existing_meds += int(not created)
            for code, name, kind in TESTS:
                dep = department_map[kind]
                if not dep:
                    skipped += 1
                    continue
                obj, created = TestCatalogItem.objects.get_or_create(
                    hospital=hospital, code=code,
                    defaults={'name': name, 'department': dep, 'active': True},
                )
                created_tests += int(created)
                existing_tests += int(not created)
            if options['dry_run']:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(
            f'Medicines: {created_meds} created, {existing_meds} already present. '
            f'Investigations: {created_tests} created, {existing_tests} already present, '
            f'{skipped} skipped (missing departments).'
        ))
        if options['dry_run']:
            self.stdout.write('DRY RUN: no database changes saved.')
        if skipped:
            self.stdout.write(self.style.WARNING('Create the missing hospital departments, then rerun this command.'))
        self.stdout.write('Existing catalog records were not overwritten or reactivated.')
