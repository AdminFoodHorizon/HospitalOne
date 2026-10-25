"""Email verified investigation PDFs directly using hospital-configured Gmail SMTP."""
import json
import logging
from django.core.mail import EmailMessage, get_connection
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from .hospital_email_service import decrypt_password
from .investigation_pdf import render_final_pdf_bytes
from .models import HospitalEmailConfig, InvestigationReport, StaffMembership, TestOrderItem, PatientVisit
from .models import ReceptionReportEmailReceipt
from .views import require_staff

logger = logging.getLogger(__name__)
MAX_PDF_BYTES = 15 * 1024 * 1024

@require_POST
def send_reception_report_pdf(request, slug, item_id):
    member = require_staff(request, slug)
    if not member or not member.hospital.is_active or member.role not in (StaffMembership.Role.RECEPTION, StaffMembership.Role.ADMIN):
        return JsonResponse({'detail': 'Reception/Admin login and verified 2FA required.'}, status=403)
    try:
        payload = json.loads(request.body or b'{}')
        if not isinstance(payload, dict):
            raise ValueError()
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'detail': 'Invalid JSON request.'}, status=400)
    if payload.get('confirm_recipient') is not True:
        return JsonResponse({'detail': 'Confirm the registered patient email before sending.'}, status=400)

    item = (TestOrderItem.objects.filter(pk=item_id, order__visit__hospital_id=member.hospital_id,
             test__hospital_id=member.hospital_id)
            .select_related('order__visit__patient__intake', 'test', 'structured_report').first())
    if not item:
        return JsonResponse({'detail': 'Investigation not found.'}, status=404)
    visit = item.order.visit
    if visit.state != PatientVisit.State.PHARMACY:
        return JsonResponse({'detail': 'Visit is not awaiting Reception discharge.'}, status=409)
    if item.status == TestOrderItem.Status.CANCELLED:
        return JsonResponse({'detail': 'Cancelled tests cannot be emailed.'}, status=409)
    report = getattr(item, 'structured_report', None)
    if not report or report.status not in (InvestigationReport.Status.FINAL, InvestigationReport.Status.AMENDED) or not report.verified_at or not report.verified_by_id:
        return JsonResponse({'detail': 'Only verified and released investigation reports can be emailed.'}, status=409)
    recipient = (getattr(getattr(visit.patient, 'intake', None), 'email', '') or '').strip()
    try:
        validate_email(recipient)
    except ValidationError:
        return JsonResponse({'detail': 'The patient has no valid registered email address.'}, status=400)
    if payload.get('recipient') != recipient:
        return JsonResponse({'detail': 'Registered patient email changed. Refresh before sending.'}, status=409)

    receipt_filter = dict(hospital_id=member.hospital_id, visit_id=visit.pk, item_id=item.pk,
                          report_id=report.pk, report_verified_at=report.verified_at,
                          recipient_email__iexact=recipient)
    if ReceptionReportEmailReceipt.objects.filter(**receipt_filter).exists():
        return JsonResponse({'detail': 'This verified report version was already accepted by Gmail for this address.', 'email_accepted': True})

    config = HospitalEmailConfig.objects.filter(hospital_id=member.hospital_id, is_enabled=True).first()
    if not config or not config.encrypted_app_password:
        return JsonResponse({'detail': 'Hospital Gmail is not enabled or configured.'}, status=503)
    if config.smtp_host != 'smtp.gmail.com' or config.smtp_port != 587 or not config.use_tls:
        return JsonResponse({'detail': 'Hospital Gmail SMTP settings are invalid.'}, status=503)
    try:
        pdf = render_final_pdf_bytes(report)
        if not isinstance(pdf, bytes) or not pdf.startswith(b'%PDF-'):
            raise ValueError('Invalid generated PDF')
        if len(pdf) > MAX_PDF_BYTES:
            return JsonResponse({'detail': 'Report exceeds the 15 MB email attachment limit.'}, status=413)
        connection = get_connection(backend='django.core.mail.backends.smtp.EmailBackend',
                                    host='smtp.gmail.com', port=587, use_tls=True, use_ssl=False,
                                    username=config.email_address,
                                    password=decrypt_password(config.encrypted_app_password), timeout=20)
        message = EmailMessage(subject=f'Investigation report from {member.hospital.name}',
            body=(f'Your finalized investigation report is attached.\n\n'
                  f'This email was sent by {member.hospital.name}. '
                  'If you were not expecting it, please contact the hospital.\n'),
            from_email=config.email_address, to=[recipient], connection=connection)
        message.attach(f'investigation-report-{item_id}.pdf', pdf, 'application/pdf')
        if message.send(fail_silently=False) != 1:
            raise RuntimeError('SMTP did not accept the email')
    except Exception:
        logger.exception('Report email failed: hospital=%s item=%s actor=%s', member.hospital_id, item_id, member.pk)
        return JsonResponse({'detail': 'Gmail could not accept the report. Check server logs.'}, status=502)

    # Record acceptance after SMTP success. If the report/recipient changed during
    # sending, the receipt is for the prior version and cannot authorize discharge.
    try:
        with transaction.atomic():
            ReceptionReportEmailReceipt.objects.create(hospital_id=member.hospital_id,
                visit_id=visit.pk, item_id=item.pk, report_id=report.pk,
                report_verified_at=report.verified_at, recipient_email=recipient, sent_by_id=member.pk)
    except Exception:
        logger.exception('SMTP accepted report but receipt persistence failed: hospital=%s item=%s', member.hospital_id, item_id)
        return JsonResponse({'detail': 'Gmail accepted the email, but the audit record could not be saved. Contact an administrator before retrying.', 'email_accepted': False}, status=503)
    logger.info('Report email accepted: hospital=%s item=%s actor=%s', member.hospital_id, item_id, member.pk)
    return JsonResponse({'detail': 'Gmail accepted the PDF attachment. Delivery is not guaranteed.', 'email_accepted': True})
