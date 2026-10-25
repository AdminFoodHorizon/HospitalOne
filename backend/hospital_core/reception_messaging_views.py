"""Email one exact hospital visit summary PDF to the patient's registered email."""
import json
import logging
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage, get_connection
from django.core.validators import validate_email
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .hospital_email_service import decrypt_password
from .models import HospitalEmailConfig, PatientVisit, StaffMembership
from .views import require_staff
from .pharmacy_views import _full_summary
from .visit_summary_pdf import render_visit_summary_pdf

log=logging.getLogger(__name__)

@require_POST
def report_delivery(request,slug):
    member=require_staff(request,slug)
    if not member or not member.hospital.is_active or member.role not in (
        StaffMembership.Role.RECEPTION,StaffMembership.Role.PHARMACY,StaffMembership.Role.ADMIN):
        return JsonResponse({'detail':'Authorized hospital staff with verified 2FA required.'},status=403)
    try:
        data=json.loads(request.body or b'{}')
        if not isinstance(data,dict) or data.get('channel')!='email': raise ValueError()
        visit_id=int(data['visit_id'])
        if visit_id<=0: raise ValueError()
    except (ValueError,TypeError,KeyError):
        return JsonResponse({'detail':'A selected visit_id and channel=email are required.'},status=400)
    visit=(PatientVisit.objects.filter(pk=visit_id,hospital_id=member.hospital_id)
           .select_related('patient__intake','assigned_doctor__membership__user').first())
    if not visit: return JsonResponse({'detail':'Visit not found in this hospital.'},status=404)
    if data.get('patient_id') is not None and str(data['patient_id'])!=str(visit.patient_id):
        return JsonResponse({'detail':'Patient and visit mismatch.'},status=400)
    if member.role==StaffMembership.Role.PHARMACY:
        from .models import PharmacyDispense
        if not PharmacyDispense.objects.filter(visit=visit).exists():
            return JsonResponse({'detail':'Dispensing must be finalized before pharmacy email.'},status=409)
    intake=getattr(visit.patient,'intake',None)
    recipient=(getattr(intake,'email','') or '').strip()
    try: validate_email(recipient)
    except ValidationError: return JsonResponse({'detail':'Patient has no valid registered email address.'},status=400)
    if data.get('recipient') is not None and data['recipient']!=recipient:
        return JsonResponse({'detail':'Recipient must match the registered patient email.'},status=409)
    config=HospitalEmailConfig.objects.filter(hospital_id=member.hospital_id,is_enabled=True).first()
    if not config or not config.encrypted_app_password:
        return JsonResponse({'detail':'Hospital Gmail is not enabled or configured.'},status=503)
    if config.smtp_host!='smtp.gmail.com' or config.smtp_port!=587 or not config.use_tls:
        return JsonResponse({'detail':'Hospital Gmail SMTP settings are invalid.'},status=503)
    try:
        summary=_full_summary(member,visit)
        summary["_hospital_id"]=member.hospital_id
        summary["_visit_id"]=visit.pk
        pdf=render_visit_summary_pdf(summary)
    except Exception:
        log.exception('Visit summary PDF generation failed: hospital=%s visit=%s',member.hospital_id,visit.pk)
        return JsonResponse({'detail':'Could not generate the visit summary PDF. Check server logs.'},status=500)
    try:
        connection=get_connection(backend='django.core.mail.backends.smtp.EmailBackend',host='smtp.gmail.com',port=587,use_tls=True,use_ssl=False,username=config.email_address,password=decrypt_password(config.encrypted_app_password),timeout=20)
        message=EmailMessage(subject=f'Patient Visit Summary - {member.hospital.name}',body=f'Please find attached your patient visit summary for visit {visit.visit_number}.\n\n{member.hospital.name}\n',from_email=config.email_address,to=[recipient],connection=connection)
        message.attach(f'visit-summary-{visit.pk}.pdf',pdf,'application/pdf')
        if message.send(fail_silently=False)!=1: raise RuntimeError('SMTP did not accept message')
    except Exception:
        log.exception('Summary email failed: hospital=%s visit=%s staff=%s',member.hospital_id,visit.pk,member.pk)
        return JsonResponse({'detail':'Gmail did not accept the PDF email. Check server logs.'},status=502)
    log.info('Summary PDF email accepted: hospital=%s visit=%s staff=%s',member.hospital_id,visit.pk,member.pk)
    return JsonResponse({'detail':'Gmail accepted the complete visit summary PDF. Delivery is not guaranteed.'})
