"""Stage 5B1: structured investigation report retrieval and draft saving.

Additive endpoints: do not modify legacy investigation endpoints.
"""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .investigation_views import allowed, departments, entry_qs
from .models import (
    InvestigationBill, InvestigationReport, InvestigationReportField,
    InvestigationReportTemplate, InvestigationReportValue, TestOrderItem,TestResult,
)


def fail(message, status=400):
    return JsonResponse({"detail": message}, status=status)


def authorized_item(member, item_id, lock=False):
    qs = TestOrderItem.objects.filter(
        pk=item_id,
        order__visit__hospital_id=member.hospital_id,
        test__hospital_id=member.hospital_id,
        test__department_id__in=departments(member).values("pk"),
        order__investigation_bill__status=InvestigationBill.Status.RELEASED,
    ).select_related("test", "order__visit")
    if lock:
        qs = qs.select_for_update(of=("self",))
    return qs.first()


def choose_template(item):
    return (
        InvestigationReportTemplate.objects.filter(
            hospital_id=item.order.visit.hospital_id,
            test_id=item.test_id,
            is_active=True,
        )
        .order_by("-version", "-pk")
        .first()
    )


def payload_for(report, template):
    fields = list(template.fields.all())
    existing = {}
    if report:
        existing = {v.field_id: v for v in report.values.all()}
    return {
        "report_id": report.pk if report else None,
        "status": report.status if report else "NOT_STARTED",
        "template": {
            "id": template.pk, "name": template.name,
            "format": template.format, "version": template.version,
        },
        "fields": [
            {
                "id": f.pk, "key": f.key, "label": f.label,
                "section": f.section, "value_type": f.value_type,
                "unit": f.unit, "reference_text": f.reference_text,
                "choice_options": f.choice_options, "required": f.required,
                "value": existing[f.pk].value if f.pk in existing else None,
                "flag": existing[f.pk].flag if f.pk in existing else "",
                "comment": existing[f.pk].comment if f.pk in existing else "",
            }
            for f in fields
        ],
        "findings": report.findings if report else "",
        "impression": report.impression if report else "",
        "recommendations": report.recommendations if report else "",
    }


def parse_value(field, raw):
    if raw is None or raw == "":
        return None
    if field.value_type == InvestigationReportField.ValueType.NUMBER:
        if isinstance(raw, bool):
            raise ValueError("Expected a number")
        try:
            number = Decimal(str(raw))
            if not number.is_finite() or len(str(raw)) > 60:
                raise ValueError("Invalid numeric value")
            return str(number)
        except (InvalidOperation, ValueError):
            raise ValueError("Expected a valid number")
    if field.value_type == InvestigationReportField.ValueType.BOOLEAN:
        if not isinstance(raw, bool):
            raise ValueError("Expected true or false")
        return raw
    if field.value_type == InvestigationReportField.ValueType.CHOICE:
        if not isinstance(raw, str) or raw not in field.choice_options:
            raise ValueError("Select an allowed option")
        return raw
    if field.value_type == InvestigationReportField.ValueType.DATE:
        if not isinstance(raw, str):
            raise ValueError("Expected YYYY-MM-DD")
        try:
            date.fromisoformat(raw)
        except ValueError:
            raise ValueError("Expected a valid YYYY-MM-DD date")
        return raw
    if not isinstance(raw, str) or len(raw) > 20000:
        raise ValueError("Expected text (maximum 20,000 characters)")
    return raw


def validate_text(payload, key):
    value = payload.get(key, "")
    if not isinstance(value, str) or len(value) > 20000:
        raise ValueError(f"{key} must be text (maximum 20,000 characters)")
    return value


@require_GET
def report_detail(request, slug, item_id):
    member = allowed(request, slug)
    if not member:
        return fail("Investigation staff login and 2FA required.", 403)
    item = authorized_item(member, item_id)
    if not item:
        return fail("Released investigation not found.", 404)
    report = InvestigationReport.objects.filter(item=item).select_related("template").first()
    template = report.template if report else choose_template(item)
    if not template:
        return fail("No active report template configured for this test.", 404)
    return JsonResponse(payload_for(report, template))


@require_POST
def save_draft(request, slug, item_id):
    member = allowed(request, slug)
    if not member:
        return fail("Investigation staff login and 2FA required.", 403)
    try:
        body = json.loads(request.body or b"{}")
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object")
        findings = validate_text(body, "findings")
        impression = validate_text(body, "impression")
        recommendations = validate_text(body, "recommendations")
        submitted = body.get("values", {})
        if not isinstance(submitted, dict) or len(submitted) > 500:
            raise ValueError("values must be an object with at most 500 fields")
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        return fail(f"Invalid report: {exc}")

    with transaction.atomic():
        item = authorized_item(member, item_id, lock=True)
        if not item:
            return fail("Released investigation not found.", 404)
        if item.status not in (
            TestOrderItem.Status.IN_PROGRESS, TestOrderItem.Status.PERFORMED
        ):
            return fail("Start the investigation before saving a draft.", 409)
        entry = entry_qs(member).filter(
            visit_id=item.order.visit_id,
            department_id=item.test.department_id,
            status__in=["CALLED", "DONE", "WAITING"],
        ).first()
        if not entry:
            return fail("Investigation must be started before reporting.", 409)

        report = (
            InvestigationReport.objects.select_for_update()
            .filter(item=item).select_related("template").first()
        )
        if report and report.status not in (
            InvestigationReport.Status.DRAFT,
            InvestigationReport.Status.IN_REVIEW,
        ):
            return fail("Finalized reports cannot be edited as drafts.", 409)
        if report and report.status == InvestigationReport.Status.IN_REVIEW:
            return fail("Report is locked in its previous review state; use Complete Report to finalize.", 409)
        template = report.template if report else choose_template(item)
        if not template:
            return fail("No active report template configured for this test.", 409)
        fields = {f.key: f for f in template.fields.all()}
        if set(submitted) - set(fields):
            return fail("Report contains fields outside its template.")

        cleaned = {}
        try:
            for key, raw in submitted.items():
                field = fields[key]
                if not isinstance(raw, dict):
                    raise ValueError(f"{key}: expected an object")
                value = parse_value(field, raw.get("value"))
                flag = raw.get("flag", "")
                comment = raw.get("comment", "")
                if not isinstance(flag, str) or flag not in ("", "LOW", "HIGH", "NORMAL", "ABNORMAL", "CRITICAL"):
                    raise ValueError(f"{key}: invalid flag")
                if not isinstance(comment, str) or len(comment) > 2000:
                    raise ValueError(f"{key}: comment is too long")
                cleaned[key] = (value, flag, comment)
        except ValueError as exc:
            return fail(str(exc))

        if report is None:
            report = InvestigationReport.objects.create(
                item=item, template=template, created_by=member,
                findings=findings, impression=impression,
                recommendations=recommendations,
            )
        else:
            report.findings = findings
            report.impression = impression
            report.recommendations = recommendations
            report.save(update_fields=["findings", "impression", "recommendations", "updated_at"])

        for key, (value, flag, comment) in cleaned.items():
            InvestigationReportValue.objects.update_or_create(
                report=report, field=fields[key],
                defaults={"value": value, "flag": flag, "comment": comment},
            )
    return JsonResponse({"detail": "Draft saved. Press Complete Report to finalize and generate the PDF.",
                         "report_id": report.pk, "status": report.status})

@require_POST
def complete_report(request, slug, item_id):
    """Single-author completion: finalize results and generate private PDF atomically.

    No second-staff verification is required by this product workflow.
    The author remains accountable and finalized results are read-only.
    """
    member = allowed(request, slug)
    if not member:
        return fail('Investigation staff login and 2FA required.', 403)
    with transaction.atomic():
        item = authorized_item(member, item_id, lock=True)
        if not item:
            return fail('Investigation not found.', 404)
        if item.status != TestOrderItem.Status.PERFORMED:
            return fail('Release the patient after sample collection before completing the report.', 409)
        report = (InvestigationReport.objects.select_for_update()
                  .select_related('template', 'item__order__visit__patient', 'item__test')
                  .filter(item=item).first())
        if not report or report.status not in (
                InvestigationReport.Status.DRAFT, InvestigationReport.Status.IN_REVIEW):
            return fail('Save a report draft before completing it.', 409)
        values = {v.field_id: v.value for v in report.values.all()}
        missing = [field.label for field in report.template.fields.filter(required=True)
                   if values.get(field.pk) in (None, '')]
        if missing:
            return fail('Complete required fields: ' + ', '.join(missing[:12]), 409)
        if not report.findings.strip() and not report.impression.strip() and not any(
                value not in (None, '') for value in values.values()):
            return fail('Report is empty.', 409)
        now = timezone.now()
        report.status = InvestigationReport.Status.FINAL
        # Existing model fields reused for finalizer identity and completion time.
        # No second-person review is implied.
        report.verified_by = member
        report.verified_at = now
        report.save(update_fields=['status', 'verified_by', 'verified_at', 'updated_at'])
        # PDF files are not saved at finalization. The PDF endpoint renders
        # verified structured data on demand for authorized staff.
        lines = []
        for value in report.values.select_related('field').order_by('field__position', 'pk'):
            if value.value not in (None, ''):
                lines.append(f'{value.field.label}: {value.value} {value.field.unit}'.strip())
        lines += [x.strip() for x in (report.findings, report.impression, report.recommendations)
                  if x.strip()]
        result, _ = TestResult.objects.select_for_update().get_or_create(item=item)
        result.summary = '\n'.join(lines)
        result.private_file_key = ''
        result.verified_by = member
        result.verified_at = now
        result.save(update_fields=['summary', 'private_file_key', 'verified_by', 'verified_at'])
        item.status = TestOrderItem.Status.REPORT_READY
        item.report_ready_at = now
        item.save(update_fields=['status', 'report_ready_at'])
        # Do not change patient attendance, visit state or physical queue here.
        # Reception's existing all-reports-ready check controls return to doctor.
    return JsonResponse({'detail': 'Report completed. PDF available on demand.',
                         'status': 'FINAL', 'pdf_ready': True})


@require_POST
def submit_review(request, slug, item_id):
    """Backward-compatible old button URL: now completes without second verification."""
    return complete_report(request, slug, item_id)


@require_POST
def verify_release(request, slug, item_id):
    """Disable obsolete second-staff verification URL."""
    return fail('Second-person verification is no longer used. Complete Report instead.', 410)


@require_POST
def legacy_result_guard(request, slug, item_id):
    """Keep old text-only reports working, but prohibit bypass of structured review."""
    member = allowed(request, slug)
    if not member:
        return fail('Investigation staff login and 2FA required.', 403)
    item = authorized_item(member, item_id)
    if not item:
        return fail('Released investigation not found.', 404)
    if InvestigationReport.objects.filter(item=item).exists() or choose_template(item):
        return fail('Use structured reporting and Complete Report for this test.', 409)
    return fail('Legacy instant-finalization is disabled. Use Complete Report.', 409)


@require_GET
def download_pdf(request, slug, item_id):
    from io import BytesIO
    from django.http import FileResponse
    from .views import require_staff
    from .models import StaffMembership, PatientVisit
    from .investigation_pdf import render_final_pdf_bytes
    member = require_staff(request, slug)
    if not member:
        return fail('Staff login and 2FA required.', 403)
    item = (TestOrderItem.objects.filter(pk=item_id,
        order__visit__hospital_id=member.hospital_id,
        test__hospital_id=member.hospital_id)
        .select_related('order__visit', 'test').first())
    if not item:
        return fail('Investigation not found in this hospital.', 404)
    visit = item.order.visit
    if member.role == StaffMembership.Role.DOCTOR:
        from .models import DoctorProfile
        if not DoctorProfile.objects.filter(membership=member, pk=visit.assigned_doctor_id).exists():
            return fail('Report is not assigned to this doctor.', 403)
    elif member.role in (StaffMembership.Role.LAB,):
        if not departments(member).filter(pk=item.test.department_id).exists():
            return fail('Report belongs to another department.', 403)
    elif member.role not in (StaffMembership.Role.RECEPTION, StaffMembership.Role.ADMIN):
        return fail('Not authorized to view this report.', 403)
    report = InvestigationReport.objects.filter(item=item, status=InvestigationReport.Status.FINAL).first()
    if not report:
        return fail('Final completed report not found.', 404)
    try:
        content = render_final_pdf_bytes(report)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('On-demand PDF rendering failed')
        return fail('Could not render report.', 503)
    response = FileResponse(BytesIO(content), content_type='application/pdf',
                            as_attachment=False, filename=f'investigation-{item_id}.pdf')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
