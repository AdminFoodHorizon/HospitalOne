
from django.contrib import admin
from django.apps import apps
from django.db import models as django_models

from . import models


# -------------------------------------------------------
# HospitalOne Django Admin Branding
# -------------------------------------------------------

admin.site.site_header = "HospitalOne | Platform Administration"
admin.site.site_title = "HospitalOne Admin"
admin.site.index_title = "HospitalOne Management"


# -------------------------------------------------------
# Custom Hospital Administration
# -------------------------------------------------------

@admin.register(models.Hospital)
class HospitalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "slug",
        "is_active",
    )

    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    ordering = ("name",)
    list_per_page = 25


# -------------------------------------------------------
# Custom Patient Administration
# -------------------------------------------------------

@admin.register(models.Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "patient_number",
        "full_name",
        "hospital",
        "created_at",
    )

    list_filter = ("hospital",)
    search_fields = (
        "patient_number",
        "full_name",
    )
    list_select_related = ("hospital",)
    ordering = ("-created_at",)
    list_per_page = 30


# -------------------------------------------------------
# Custom Staff Administration
# -------------------------------------------------------

@admin.register(models.StaffMembership)
class StaffMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "hospital",
        "role",
    )

    list_filter = (
        "hospital",
        "role",
    )

    search_fields = (
        "user__username",
        "user__email",
        "hospital__name",
    )

    list_select_related = ("user", "hospital")
    list_per_page = 30


# -------------------------------------------------------
# Hospital Gmail Administration
# -------------------------------------------------------

if hasattr(models, "HospitalEmailConfig"):

    @admin.register(models.HospitalEmailConfig)
    class HospitalEmailConfigAdmin(admin.ModelAdmin):

        list_display = (
            "hospital",
            "email_address",
            "is_enabled",
            "smtp_host",
            "smtp_port",
            "use_tls",
        )

        list_filter = (
            "is_enabled",
            "use_tls",
        )

        search_fields = (
            "hospital__name",
            "email_address",
        )

        list_select_related = ("hospital",)

        # Never expose the encrypted Gmail App Password
        # through the Django admin form.
        exclude = ("encrypted_app_password",)

        list_per_page = 25


# -------------------------------------------------------
# Automatically Register Remaining Models
# -------------------------------------------------------

hospital_app = apps.get_app_config("hospital_core")

for model in hospital_app.get_models():

    if model in admin.site._registry:
        continue

    # Skip proxy models if not needed.
    if model._meta.proxy:
        continue

    # Register additional database models.
    admin.site.register(model)


# -------------------------------------------------------
# Admin Pagination Defaults
# -------------------------------------------------------

admin.site.empty_value_display = "Not recorded"
