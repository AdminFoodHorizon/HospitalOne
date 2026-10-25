
"""Hospital-scoped announcement event feed.

Staff-authenticated development version.
Dedicated TV authentication is required before public deployment.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import AnnouncementEvent
from .views import require_staff


MAX_DISPLAY_ENTRIES = 50


@require_GET
def called_queue(request, slug):
    member = require_staff(request, slug)

    if member is None:
        return JsonResponse(
            {
                "detail": "Hospital staff login and 2FA required"
            },
            status=403,
        )

    events = (
        AnnouncementEvent.objects
        .filter(
            hospital_id=member.hospital_id,
            hospital__is_active=True,
        )
        .order_by("-id")[:MAX_DISPLAY_ENTRIES]
    )

    entries = [
        {
            "event_id": event.id,
            "token": event.token,
            "department": event.department_name,
            "room_number": event.room_number,
            "called_at": event.called_at.isoformat(),
        }
        for event in events
    ]

    return JsonResponse(
        {
            "hospital": member.hospital.name,
            "entries": entries,
        }
    )
