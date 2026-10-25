"""HospitalOne hospital admin: additive, hospital-scoped, 2FA-protected APIs."""
import json
from decimal import Decimal, InvalidOperation
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError
from django.db.models import Q, Sum, Count
from datetime import timedelta
from django.utils.dateparse import parse_date
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from .views import require_staff
from .two_factor_service import verify_user_totp
from .two_factor_models import AuthenticationAuditLog
from .models import (StaffMembership, Department, Patient, PatientVisit, MedicineCatalogItem,
    TestCatalogItem, TestOrderItem, InvestigationReport, InvestigationBill, PharmacyDispense,
    PharmacyDispenseLine, AnnouncementEvent, HospitalDisplayDevice, HospitalDisplayPairingRequest)

def deny(): return JsonResponse({'detail':'Hospital administrator login and 2FA required.'},status=403)
def admin(request,slug):
    member=require_staff(request,slug)
    return member if member and member.role==StaffMembership.Role.ADMIN and request.user.is_active else None

def payload(request):
    if len(request.body)>8192: return None
    try:
        obj=json.loads(request.body or '{}')
        return obj if isinstance(obj,dict) else None
    except (ValueError,UnicodeDecodeError): return None

def bad(message,status=400): return JsonResponse({'detail':message},status=status)
def audit(request,member,event,details):
    AuthenticationAuditLog.objects.create(user=request.user,hospital=member.hospital,event=event,details=details)

def safe_price(raw):
    try:
        amount=Decimal(str(raw))
        if not amount.is_finite() or amount<0 or amount>Decimal('99999999.99') or amount.as_tuple().exponent < -2: return None
        return amount
    except (InvalidOperation,TypeError,ValueError): return None

@require_GET
def overview(request, slug):
    m = admin(request, slug)
    if not m: return deny()
    h = m.hospital
    now = timezone.now()
    since = now - timedelta(hours=24)
    start_day = timezone.localdate() - timedelta(days=6)
    visits = PatientVisit.objects.filter(hospital=h)
    recent = visits.filter(registered_at__gte=since, registered_at__lte=now)
    week = visits.filter(registered_at__date__gte=start_day, registered_at__lte=now)
    daily = {str(start_day + timedelta(days=i)): 0 for i in range(7)}
    for row in week.values('registered_at__date').annotate(n=Count('pk')):
        daily[str(row['registered_at__date'])] = row['n']
    meds = PharmacyDispenseLine.objects.filter(dispense__visit__hospital=h, dispense__finalized_at__gte=since)
    tests = TestOrderItem.objects.filter(order__visit__hospital=h, order__ordered_at__gte=since)
    staff = StaffMembership.objects.filter(hospital=h, is_active=True)
    return JsonResponse({
        'currency': h.billing_currency,
        'period': 'Last 24 hours',
        'visits_24h': recent.count(),
        'visits_7d': week.count(),
        'unique_patients_24h': recent.values('patient_id').distinct().count(),
        'medicines_dispensed_24h': meds.aggregate(v=Sum('dispensed_quantity'))['v'] or 0,
        'investigations_24h': tests.count(),
        'reports_final_24h': InvestigationReport.objects.filter(item__order__visit__hospital=h, status='FINAL', verified_at__gte=since).count(),
        'registered_doctors': staff.filter(role='DOCTOR').count(),
        'registered_nurses': staff.filter(role='NURSE').count(),
        'on_duty_available': False,
        'daily_visits': [{'day': day, 'visits': count} for day, count in daily.items()],
        'visit_states': list(recent.values('state').annotate(count=Count('pk')).order_by('state')),
    })

@require_GET
def finances(request, slug):
    m = admin(request, slug)
    if not m: return deny()
    since = timezone.now() - timedelta(hours=24)
    h = m.hospital
    pharmacy = PharmacyDispense.objects.filter(visit__hospital=h, finalized_at__gte=since)
    bills = InvestigationBill.objects.filter(hospital=h, created_at__gte=since).exclude(status='CANCELLED')
    return JsonResponse({
        'currency': h.billing_currency,
        'pharmacy_finalized_24h': str(pharmacy.aggregate(v=Sum('total_amount'))['v'] or 0),
        'investigation_billed_24h': str(bills.aggregate(v=Sum('total_amount'))['v'] or 0),
        'investigation_bill_count_24h': bills.count(),
        'note': 'Billed amounts are not proof of payment collection. Outstanding and refunded balances require payment reconciliation.',
    })

MED_FIELDS = {'generic_name':180,'brand_name':180,'strength':80,'dosage_form':50,'administration_route':50,'pack_description':100}
TEST_FIELDS = {'category':80,'specimen_type':80,'preparation_instructions':2000}
def catalog_metadata(data, kind):
    fields = MED_FIELDS if kind == 'medicines' else TEST_FIELDS
    result = {}
    for key, limit in fields.items():
        if key in data:
            value = data[key]
            if not isinstance(value, str) or len(value.strip()) > limit:
                raise ValueError('Invalid '+key)
            result[key] = value.strip()
    if kind == 'investigations' and 'turnaround_hours' in data:
        value = data['turnaround_hours']
        if value in ('', None): result['turnaround_hours'] = None
        elif type(value) is int and 0 <= value <= 8760: result['turnaround_hours'] = value
        else: raise ValueError('Invalid turnaround hours')
    return result

@require_POST
def catalog_create(request, slug, kind):
    m = admin(request, slug)
    if not m: return deny()
    if kind not in ('medicines', 'investigations'): return bad('Unknown catalog', 404)
    d = payload(request)
    if d is None: return bad('Invalid payload')
    code, name = d.get('code'), d.get('name')
    if not isinstance(code, str) or not code.strip() or len(code) > 40: return bad('Invalid code')
    if not isinstance(name, str) or not name.strip() or len(name) > 180: return bad('Invalid name')
    price = safe_price(d.get('price'))
    if price is None: return bad('Invalid price')
    if kind == 'medicines':
        model = MedicineCatalogItem
        try: kwargs = {'unit_price': price, **catalog_metadata(d, kind)}
        except ValueError as exc: return bad(str(exc))
    else:
        model = TestCatalogItem
        department = Department.objects.filter(pk=d.get('department_id'), hospital=m.hospital, is_active=True).first()
        if not department: return bad('Choose an active department in your hospital')
        try: kwargs = {'price': price, 'department': department, **catalog_metadata(d, kind)}
        except ValueError as exc: return bad(str(exc))
    try:
        with transaction.atomic():
            item = model.objects.create(hospital=m.hospital, code=code.strip(), name=name.strip(), active=True, **kwargs)
            audit(request, m, 'HOSPITAL_ADMIN_CATALOG_CREATED', {'kind': kind, 'item_id': item.pk})
    except ValueError as exc: return bad(str(exc))
    except IntegrityError: return bad('Catalog code already exists in this hospital', 409)
    return JsonResponse({'detail': 'Catalog item created.', 'id': item.pk}, status=201)

@require_GET
def archive(request, slug):
    m = admin(request, slug)
    if not m: return deny()
    kind = request.GET.get('kind', 'visits')
    query = request.GET.get('q', '').strip()[:80]
    start = parse_date(request.GET.get('from', '')) if request.GET.get('from') else None
    end = parse_date(request.GET.get('to', '')) if request.GET.get('to') else None
    if request.GET.get('from') and not start or request.GET.get('to') and not end: return bad('Invalid date format')
    if start and end and start > end: return bad('Start date must not exceed end date')
    if start and end and (end-start).days > 366: return bad('Select at most 366 days')
    if not start and not end:
        start = timezone.localdate() - timedelta(days=30)
    if kind == 'visits':
        qs = PatientVisit.objects.filter(hospital=m.hospital).select_related('patient').order_by('-registered_at')
        if start: qs = qs.filter(registered_at__date__gte=start)
        if end: qs = qs.filter(registered_at__date__lte=end)
        if query: qs = qs.filter(Q(patient__full_name__icontains=query)|Q(patient__patient_number__icontains=query)|Q(visit_number__icontains=query))
        items = [{'date': x.registered_at.isoformat(), 'patient': x.patient.full_name, 'name': x.visit_number, 'details': x.state, 'patient_id': x.patient_id} for x in qs[:200]]
    elif kind == 'medicines':
        qs = PharmacyDispenseLine.objects.filter(dispense__visit__hospital=m.hospital).select_related('dispense__visit__patient').order_by('-dispense__finalized_at')
        if start: qs = qs.filter(dispense__finalized_at__date__gte=start)
        if end: qs = qs.filter(dispense__finalized_at__date__lte=end)
        if query: qs = qs.filter(Q(medicine_name__icontains=query)|Q(dispense__visit__patient__full_name__icontains=query)|Q(dispense__bill_number__icontains=query))
        items = [{'date': x.dispense.finalized_at.isoformat(), 'patient': x.dispense.visit.patient.full_name, 'name': x.medicine_name, 'details': 'Quantity: '+str(x.dispensed_quantity)+' · '+x.dispense.bill_number} for x in qs[:200]]
    elif kind == 'investigations':
        qs = TestOrderItem.objects.filter(order__visit__hospital=m.hospital).select_related('test','order__visit__patient').order_by('-order__ordered_at')
        if start: qs = qs.filter(order__ordered_at__date__gte=start)
        if end: qs = qs.filter(order__ordered_at__date__lte=end)
        if query: qs = qs.filter(Q(test__name__icontains=query)|Q(order__visit__patient__full_name__icontains=query))
        items = [{'date': x.order.ordered_at.isoformat(), 'patient': x.order.visit.patient.full_name, 'name': x.test.name, 'details': x.status} for x in qs[:200]]
    elif kind == 'finances':
        qs = InvestigationBill.objects.filter(hospital=m.hospital).order_by('-created_at')
        if start: qs = qs.filter(created_at__date__gte=start)
        if end: qs = qs.filter(created_at__date__lte=end)
        if query: qs = qs.filter(Q(bill_number__icontains=query)|Q(visit__patient__full_name__icontains=query))
        qs = qs.select_related('visit__patient')
        items = [{'date': x.created_at.isoformat(), 'patient': x.visit.patient.full_name, 'name': x.bill_number or 'Investigation bill', 'details': str(x.total_amount)+' · '+x.status} for x in qs[:200]]
    else: return bad('Unknown record type', 404)
    return JsonResponse({'items': items, 'limit': 200, 'kind': kind})

@require_GET
def staff(request,slug):
    m=admin(request,slug)
    if not m:return deny()
    rows=StaffMembership.objects.filter(hospital=m.hospital).select_related('user','department').order_by('user__username','role')[:300]
    return JsonResponse({'items':[{'id':x.id,'username':x.user.username,'email':x.user.email,'role':x.role,'department_id':x.department_id,'department':x.department.name if x.department else '', 'active':x.is_active} for x in rows]})

@require_POST
def staff_create(request,slug):
    m=admin(request,slug)
    if not m:return deny()
    d=payload(request)
    if d is None:return bad('Invalid payload')
    username=d.get('username','').strip() if isinstance(d.get('username'),str) else ''
    password=d.get('password','')
    role=d.get('role')
    if not username or len(username)>150 or not isinstance(password,str) or role not in StaffMembership.Role.values or role=='ADMIN':return bad('Valid username, password and non-admin role required.')
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    try:validate_password(password)
    except ValidationError as e:return bad(' '.join(e.messages))
    department=None
    if d.get('department_id'):
        department=Department.objects.filter(pk=d['department_id'],hospital=m.hospital,is_active=True).first()
        if not department:return bad('Department not found in this hospital.')
    try:
        with transaction.atomic():
            user=get_user_model().objects.create_user(username=username,password=password,email=d.get('email',''))
            membership=StaffMembership.objects.create(user=user,hospital=m.hospital,role=role,department=department)
            audit(request,m,'HOSPITAL_ADMIN_STAFF_CREATED',{'membership_id':membership.id,'role':role})
    except IntegrityError:return bad('Username already exists.',409)
    return JsonResponse({'id':membership.id,'detail':'Staff created. They must complete 2FA enrollment at first login.'},status=201)

@require_POST
def staff_action(request,slug,membership_id):
    m=admin(request,slug)
    if not m:return deny()
    d=payload(request)
    if d is None:return bad('Invalid payload')
    target=StaffMembership.objects.select_related('user').filter(pk=membership_id,hospital=m.hospital).first()
    if not target:return bad('Staff not found.',404)
    if target.role=='ADMIN':return bad('Admin accounts cannot be modified through this endpoint.',403)
    action=d.get('action')
    if action=='status':
        if not isinstance(d.get('active'),bool):return bad('Boolean active required.')
        target.is_active=d['active'];target.save(update_fields=['is_active'])
    elif action=='password':
        code=d.get('totp_code','')
        if not isinstance(code,str) or not verify_user_totp(request.user,code):return bad('Fresh authenticator verification required.',403)
        password=d.get('password','')
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        try:validate_password(password,user=target.user)
        except (ValidationError,TypeError) as e:return bad(' '.join(e.messages) if isinstance(e,ValidationError) else 'Invalid password.')
        target.user.set_password(password);target.user.save(update_fields=['password'])
    elif action=='2fa_request':
        # Deliberately a request/audit only. Never disable another user's 2FA here.
        reason=d.get('reason','')
        if not isinstance(reason,str) or len(reason.strip())<10 or len(reason)>500:return bad('Reason must be 10–500 characters.')
        code=d.get('totp_code','')
        if not isinstance(code,str) or not verify_user_totp(request.user,code):return bad('Fresh authenticator verification required.',403)
    else:return bad('Unknown action.')
    audit(request,m,'HOSPITAL_ADMIN_STAFF_'+action.upper(),{'membership_id':target.pk,'reason':d.get('reason','') if action=='2fa_request' else ''})
    return JsonResponse({'detail':'2FA reset request recorded for security review; no credential was changed.' if action=='2fa_request' else 'Updated successfully.'})

@require_GET
def departments(request,slug):
    m=admin(request,slug)
    if not m:return deny()
    return JsonResponse({'items':list(Department.objects.filter(hospital=m.hospital).values('id','name','kind','room_number','is_active').order_by('name'))})

@require_POST
def department_create(request,slug):
    m=admin(request,slug)
    if not m:return deny()
    d=payload(request)
    name=str(d.get('name','')).strip()
    kind=str(d.get('kind','')).strip()
    room=str(d.get('room_number','')).strip()
    if not name or len(name)>120:return bad('Enter a valid department name.')
    if kind not in Department.Kind.values:return bad('Invalid department type.')
    if len(room)>30:return bad('Room number is too long.')
    if Department.objects.filter(hospital=m.hospital,name__iexact=name).exists():return bad('Department name already exists in this hospital.')
    from django.db import IntegrityError,transaction
    try:
        with transaction.atomic():
            item=Department.objects.create(hospital=m.hospital,name=name,kind=kind,room_number=room)
            audit(request,m,'HOSPITAL_ADMIN_DEPARTMENT_CREATED',{'department_id':item.pk})
    except IntegrityError:
        return bad('Department name already exists in this hospital.')
    return JsonResponse({'detail':'Department created.','id':item.pk},status=201)

@require_GET
def catalog(request,slug,kind):
    m=admin(request,slug)
    if not m:return deny()
    if kind=='medicines':
        items=MedicineCatalogItem.objects.filter(hospital=m.hospital).order_by('name')[:500]
        return JsonResponse({'items':[{'id':x.pk,'code':x.code,'name':x.name,'price':str(x.unit_price) if x.unit_price is not None else '', 'active':x.active, **{k:getattr(x,k) for k in MED_FIELDS}} for x in items]})
    if kind=='investigations':
        items=TestCatalogItem.objects.filter(hospital=m.hospital).select_related('department').order_by('name')[:500]
        return JsonResponse({'items':[{'id':x.pk,'code':x.code,'name':x.name,'price':str(x.price),'active':x.active,'department':x.department.name, **{k:getattr(x,k) for k in TEST_FIELDS}, 'turnaround_hours':x.turnaround_hours} for x in items]})
    return bad('Unknown catalog',404)

@require_POST
def catalog_update(request,slug,kind,item_id):
    m=admin(request,slug)
    if not m:return deny()
    model={'medicines':MedicineCatalogItem,'investigations':TestCatalogItem}.get(kind)
    if not model:return bad('Unknown catalog',404)
    d=payload(request)
    if d is None:return bad('Invalid payload')
    item=model.objects.filter(pk=item_id,hospital=m.hospital).first()
    if not item:return bad('Item not found',404)
    allowed={'price','active','name'} | (set(MED_FIELDS) if kind=='medicines' else set(TEST_FIELDS)|{'turnaround_hours'})
    if not d or set(d)-allowed:return bad('Only name, price and active may be edited.')
    if 'price' in d:
        value=safe_price(d['price'])
        if value is None:return bad('Price must be nonnegative with at most two decimals.')
        if kind=='medicines':item.unit_price=value
        else:item.price=value
    if 'name' in d:
        if not isinstance(d['name'],str) or not d['name'].strip() or len(d['name'])>180:return bad('Invalid name')
        item.name=d['name'].strip()
    if 'active' in d:
        if not isinstance(d['active'],bool):return bad('Invalid active value')
        item.active=d['active']
    try:
        for field, value in catalog_metadata(d, kind).items(): setattr(item, field, value)
    except ValueError as exc: return bad(str(exc))
    item.save()
    audit(request,m,'HOSPITAL_ADMIN_CATALOG_EDIT',{'kind':kind,'item_id':item.pk,'fields':list(d)})
    return JsonResponse({'detail':'Catalog item updated.'})

@require_GET
def patient_search(request,slug):
    m=admin(request,slug)
    if not m:return deny()
    q=request.GET.get('q','').strip()[:80]
    if len(q)<2:return JsonResponse({'items':[]})
    rows=Patient.objects.filter(hospital=m.hospital).filter(Q(full_name__icontains=q)|Q(patient_number__icontains=q)).order_by('full_name')[:50]
    return JsonResponse({'items':[{'id':x.pk,'number':x.patient_number,'name':x.full_name,'dob':x.date_of_birth.isoformat() if x.date_of_birth else None} for x in rows]})

@require_GET
def patient_detail(request,slug,patient_id):
    m=admin(request,slug)
    if not m:return deny()
    patient=Patient.objects.filter(pk=patient_id,hospital=m.hospital).first()
    if not patient:return bad('Patient not found.',404)
    visits=PatientVisit.objects.filter(patient=patient,hospital=m.hospital).order_by('-registered_at')[:100]
    reports=InvestigationReport.objects.filter(item__order__visit__patient=patient,item__order__visit__hospital=m.hospital,status='FINAL').select_related('item__test','item__order__visit').order_by('-verified_at')[:100]
    audit(request,m,'HOSPITAL_ADMIN_PATIENT_VIEW',{'patient_id':patient.pk})
    return JsonResponse({'patient':{'id':patient.pk,'name':patient.full_name,'number':patient.patient_number},
        'visits':[{'id':v.pk,'number':v.visit_number,'date':v.registered_at.isoformat(),'state':v.state} for v in visits],
        'reports':[{'id':r.pk,'item_id':r.item_id,'test':r.item.test.name,'visit':r.item.order.visit.visit_number,'verified_at':r.verified_at.isoformat() if r.verified_at else None} for r in reports]})

@require_GET
def history(request,slug,kind):
    m=admin(request,slug)
    if not m:return deny()
    if kind=='medicines':
        rows=PharmacyDispenseLine.objects.filter(dispense__visit__hospital=m.hospital).select_related('dispense__visit__patient').order_by('-dispense__finalized_at')[:150]
        return JsonResponse({'items':[{'date':x.dispense.finalized_at.isoformat(),'patient':x.dispense.visit.patient.full_name,'name':x.medicine_name,'quantity':x.dispensed_quantity,'bill':x.dispense.bill_number} for x in rows]})
    if kind=='investigations':
        rows=TestOrderItem.objects.filter(order__visit__hospital=m.hospital).select_related('test','order__visit__patient').order_by('-pk')[:150]
        return JsonResponse({'items':[{'date':x.order.ordered_at.isoformat(),'patient':x.order.visit.patient.full_name,'name':x.test.name,'status':x.status,'item_id':x.pk} for x in rows]})
    if kind=='announcements':
        rows=AnnouncementEvent.objects.filter(hospital=m.hospital, called_at__gte=timezone.now()-timedelta(hours=24)).order_by('-called_at')[:100]
        return JsonResponse({'items':[{'date':x.called_at.isoformat(),'token':x.token,'department':x.department_name,'room':x.room_number} for x in rows]})
    return bad('Unknown history',404)

@require_GET
def devices(request,slug):
    m=admin(request,slug)
    if not m:return deny()
    # No pairing secrets or device credentials returned.
    return JsonResponse({'count':HospitalDisplayDevice.objects.filter(hospital=m.hospital).count()})

@require_GET
def display_admin_status(request, slug):
    m = admin(request, slug)
    if not m: return deny()
    now = timezone.now()
    pending = HospitalDisplayPairingRequest.objects.filter(
        hospital=m.hospital,
        status=HospitalDisplayPairingRequest.Status.PENDING,
        expires_at__gt=now,
    ).order_by('-created_at')[:30]
    registered = HospitalDisplayDevice.objects.filter(hospital=m.hospital).order_by('name')[:100]
    recent_calls = AnnouncementEvent.objects.filter(
        hospital=m.hospital, called_at__gte=now-timedelta(hours=24)
    ).order_by('-called_at')[:100]
    return JsonResponse({
        'pending': [{'request_id':str(x.request_id), 'name':x.device_name,
                     'created_at':x.created_at.isoformat(), 'expires_at':x.expires_at.isoformat()}
                    for x in pending],
        'devices': [{'device_id':str(x.device_id), 'name':x.name,
                     'is_active':x.is_active,
                     'paired_at':x.paired_at.isoformat() if x.paired_at else None,
                     'credential_expires_at':x.credential_expires_at.isoformat() if x.credential_expires_at else None}
                    for x in registered],
        'items': [{'date':x.called_at.isoformat(), 'token':x.token,
                   'department':x.department_name, 'room':x.room_number}
                  for x in recent_calls],
    })
