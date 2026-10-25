
from django.core.management.base import BaseCommand

from hospital_core.queue_timeout import expire_unattended_calls


class Command(BaseCommand):
    help = (
        "Return unattended called patients "
        "to WAITING after five minutes."
    )

    def handle(self, *args, **options):
        count = expire_unattended_calls()

        self.stdout.write(
            self.style.SUCCESS(
                f"Expired called patients: {count}"
            )
        )
