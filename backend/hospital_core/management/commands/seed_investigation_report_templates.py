"""Seed editable, non-clinically-validated reporting form layouts for existing tests."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from hospital_core.models import Hospital, TestCatalogItem, InvestigationReportTemplate, InvestigationReportField


def field(key, label, kind='TEXT', section='', unit='', required=False):
    return dict(key=key, label=label, value_type=kind, section=section, unit=unit, required=required)


CBC = [field('hemoglobin', 'Hemoglobin', 'NUMBER', 'Hematology', 'g/dL'),
       field('wbc', 'White blood cells', 'NUMBER', 'Hematology', '10^3/uL'),
       field('rbc', 'Red blood cells', 'NUMBER', 'Hematology', '10^6/uL'),
       field('hematocrit', 'Hematocrit', 'NUMBER', 'Hematology', '%'),
       field('mcv', 'MCV', 'NUMBER', 'Red cell indices', 'fL'),
       field('mch', 'MCH', 'NUMBER', 'Red cell indices', 'pg'),
       field('mchc', 'MCHC', 'NUMBER', 'Red cell indices', 'g/dL'),
       field('rdw', 'RDW', 'NUMBER', 'Red cell indices', '%'),
       field('platelets', 'Platelets', 'NUMBER', 'Hematology', '10^3/uL'),
       field('neutrophils', 'Neutrophils', 'NUMBER', 'Differential', '%'),
       field('lymphocytes', 'Lymphocytes', 'NUMBER', 'Differential', '%'),
       field('monocytes', 'Monocytes', 'NUMBER', 'Differential', '%'),
       field('eosinophils', 'Eosinophils', 'NUMBER', 'Differential', '%'),
       field('basophils', 'Basophils', 'NUMBER', 'Differential', '%')]

USG = [field('liver', 'Liver findings', 'LONG_TEXT', 'Upper abdomen'),
       field('gallbladder', 'Gallbladder findings', 'LONG_TEXT', 'Upper abdomen'),
       field('pancreas', 'Pancreas findings', 'LONG_TEXT', 'Upper abdomen'),
       field('spleen', 'Spleen findings', 'LONG_TEXT', 'Upper abdomen'),
       field('right_kidney', 'Right kidney', 'LONG_TEXT', 'Urinary tract'),
       field('left_kidney', 'Left kidney', 'LONG_TEXT', 'Urinary tract'),
       field('urinary_bladder', 'Urinary bladder', 'LONG_TEXT', 'Urinary tract'),
       field('additional_findings', 'Additional findings', 'LONG_TEXT', 'Other')]

ECG = [field('heart_rate', 'Heart rate', 'NUMBER', 'Measurements', 'bpm'),
       field('pr_interval', 'PR interval', 'NUMBER', 'Measurements', 'ms'),
       field('qrs_duration', 'QRS duration', 'NUMBER', 'Measurements', 'ms'),
       field('qtc', 'QTc', 'NUMBER', 'Measurements', 'ms'),
       field('rhythm', 'Rhythm', 'TEXT', 'Interpretation'),
       field('axis', 'Electrical axis', 'TEXT', 'Interpretation'),
       field('st_t_changes', 'ST-T observations', 'LONG_TEXT', 'Interpretation')]

ECHO = [field('ef', 'Ejection fraction', 'NUMBER', 'Measurements', '%'),
        field('lv', 'Left ventricle findings', 'LONG_TEXT', 'Chambers'),
        field('rv', 'Right ventricle findings', 'LONG_TEXT', 'Chambers'),
        field('valves', 'Valve findings', 'LONG_TEXT', 'Valves'),
        field('pericardium', 'Pericardium', 'LONG_TEXT', 'Other')]

IMAGING = [field('technique', 'Technique / view', 'TEXT', 'Examination'),
           field('region', 'Anatomical region', 'TEXT', 'Examination'),
           field('observations', 'Detailed observations', 'LONG_TEXT', 'Findings')]

LAB = [field('result', 'Result', 'TEXT', 'Test results'),
       field('method', 'Method / specimen', 'TEXT', 'Test details')]

URINE = [field('appearance', 'Appearance', 'TEXT', 'Physical'),
         field('ph', 'pH', 'NUMBER', 'Chemical'),
         field('protein', 'Protein', 'TEXT', 'Chemical'),
         field('glucose', 'Glucose', 'TEXT', 'Chemical'),
         field('rbc', 'RBC', 'TEXT', 'Microscopy'),
         field('wbc', 'WBC', 'TEXT', 'Microscopy')]

PROCEDURE = [field('procedure', 'Procedure details', 'LONG_TEXT', 'Procedure'),
             field('observations', 'Observations', 'LONG_TEXT', 'Findings')]


def select(test):
    n = (test.name + ' ' + test.code).lower()
    k = test.department.kind
    if any(x in n for x in ('complete blood count', 'cbc', 'full blood count', 'fbc', 'hemogram')):
        return 'LAB_PANEL', CBC
    if 'urine' in n or 'urinalysis' in n:
        return 'LAB_PANEL', URINE
    if any(x in n for x in ('ultrasound', 'sonography', 'usg', 'doppler')):
        return 'IMAGING', USG
    if 'echo' in n or 'echocardiog' in n:
        return 'CARDIAC', ECHO
    if 'ecg' in n or 'ekg' in n or k == 'ECG':
        return 'CARDIAC', ECG
    if any(x in n for x in ('x-ray', 'xray', 'radiograph', 'ct ', 'mri', 'scan')) or k == 'RADIOLOGY':
        return 'IMAGING', IMAGING
    if k == 'LAB':
        return 'LAB_PANEL', LAB
    return 'PROCEDURE', PROCEDURE


class Command(BaseCommand):
    help = 'Create draft investigation report templates for existing hospital tests (no clinical reference ranges).'

    def add_arguments(self, parser):
        parser.add_argument('--hospital', required=True, help='Existing hospital slug')

    @transaction.atomic
    def handle(self, *args, **opts):
        hospital = Hospital.objects.filter(slug=opts['hospital']).first()
        if not hospital:
            raise CommandError('Hospital slug not found.')
        created = skipped = 0
        for test in TestCatalogItem.objects.filter(hospital=hospital, active=True).select_related('department'):
            if InvestigationReportTemplate.objects.filter(test=test).exists():
                skipped += 1
                continue
            format_name, fields = select(test)
            template = InvestigationReportTemplate.objects.create(
                hospital=hospital, test=test, name=test.name, format=format_name,
                version=1, is_active=True,
            )
            for pos, spec in enumerate(fields, 1):
                InvestigationReportField.objects.create(template=template, position=pos, **spec)
            created += 1
        self.stdout.write(self.style.SUCCESS(
            f'Created {created} templates; skipped {skipped} existing tests. '
            'All reference ranges intentionally blank; clinical review required.'
        ))
