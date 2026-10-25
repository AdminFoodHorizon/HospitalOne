"""Read-only hospital queue board API (staff-authenticated initial version)."""
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.utils import timezone
from .models import PatientQueueEntry, StaffMembership
from .views import require_staff

# Public-safe statuses only; do not expose names or patient identifiers.
PUBLIC_STATUS = {
    PatientQueueEntry.Status.WAITING: 'WAITING',
    PatientQueueEntry.Status.CALLED: 'CALLED',
    PatientQueueEntry.Status.DONE: 'COMPLETED',
}

@require_GET
def queue_board(request, slug):
    member = require_staff(request, slug)
    if member is None:
        return JsonResponse({'detail': 'Hospital staff login and 2FA required'}, status=403)
    # Active entries only; bounded response and hospital-scoped query.
    entries = (PatientQueueEntry.objects
               .select_related('visit', 'department')
               .filter(visit__hospital_id=member.hospital_id,
                       department__hospital_id=member.hospital_id,
                       visit__hospital__is_active=True,
                       status__in=[PatientQueueEntry.Status.WAITING, PatientQueueEntry.Status.CALLED])
               .order_by('queued_at', 'pk')[:150])
    rows = []
    for entry in entries:
        if not entry.visit.queue_token:
            continue
        rows.append({
            'token': entry.visit.queue_token,
            'department': entry.department.name,
            'status': PUBLIC_STATUS[entry.status],
            'queued_at': entry.queued_at.isoformat(),
            'called_at': entry.called_at.isoformat() if entry.called_at else None,
        })
    return JsonResponse({
        'hospital': member.hospital.name,
        'as_of': timezone.now().isoformat(),
        'entries': rows,
    })
