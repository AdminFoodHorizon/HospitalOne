"""Seed departments and example staff for Sunrise and City Care hospitals.

Install: hospital_core/management/commands/seed_remaining_hospitals.py
Run: python manage.py seed_remaining_hospitals

Requires existing commands seed_hospital_departments and seed_hospital_staff.
This command does not create hospitals or patients. It prompts for each new
staff account password via the existing seed_hospital_staff command.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from hospital_core.models import Hospital

HOSPITAL_SLUGS = ("sunrise-hospital", "city-care-hospital")


class Command(BaseCommand):
    help = "Seed departments and example staff for the two remaining hospitals."

    def handle(self, *args, **options):
        hospitals = list(Hospital.objects.filter(slug__in=HOSPITAL_SLUGS))
        by_slug = {hospital.slug: hospital for hospital in hospitals}
        missing = [slug for slug in HOSPITAL_SLUGS if slug not in by_slug]
        if missing:
            raise CommandError("Hospital(s) not found: " + ", ".join(missing))
        inactive = [slug for slug in HOSPITAL_SLUGS if not by_slug[slug].is_active]
        if inactive:
            raise CommandError("Hospital(s) inactive: " + ", ".join(inactive))

        self.stdout.write("Seeding only Sunrise and City Care. Green Valley will not be changed.")
        self.stdout.write("New staff passwords will be requested privately, one account at a time.")
        self.stdout.write("Existing users and departments will be preserved.\n")

        for slug in HOSPITAL_SLUGS:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {by_slug[slug].name}: departments ==="))
            call_command("seed_hospital_departments", hospital=slug)
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {by_slug[slug].name}: staff ==="))
            call_command("seed_hospital_staff", hospital=slug)

        self.stdout.write(self.style.SUCCESS("\nFinished both hospitals."))
        self.stdout.write("Doctors start OFF DUTY. Example names are for development only.")
        self.stdout.write("Hospital-specific login permissions still require implementation/testing.")
