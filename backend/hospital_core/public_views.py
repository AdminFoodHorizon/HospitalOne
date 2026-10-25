from django.http import JsonResponse
from django.views.decorators.http import require_GET
from .models import Hospital


@require_GET
def hospital_public_info(request, slug):
    hospital = Hospital.objects.filter(slug=slug, is_active=True).first()
    if hospital is None:
        return JsonResponse({'detail': 'Hospital not found or unavailable.'}, status=404)

    address = ', '.join(filter(None, [
        hospital.address_line1, hospital.address_line2, hospital.city,
        hospital.state, hospital.postal_code, hospital.country,
    ]))

    # Optional fields are read only if they exist in your Hospital model.
    # This avoids forcing a database migration just to display the homepage.
    def optional_url(field):
        value = getattr(hospital, field, None)
        if not value:
            return ''
        try:
            return request.build_absolute_uri(value.url)
        except (AttributeError, ValueError):
            return str(value)

    return JsonResponse({
        'slug': hospital.slug,
        'name': hospital.name,
        'is_active': hospital.is_active,
        'branding': {
            'logo_url': optional_url('logo'),
            'banner_url': optional_url('banner'),
            'tagline': getattr(hospital, 'tagline', '') or '',
            'welcome_message': getattr(hospital, 'welcome_message', '') or '',
            'footer_description': getattr(hospital, 'footer_description', '') or '',
        },
        'contact': {
            'address': address,
            'phone': hospital.phone,
            'email': hospital.email,
            'website': hospital.website,
        },
    })
