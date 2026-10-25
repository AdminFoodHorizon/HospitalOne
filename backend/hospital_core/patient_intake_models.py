from django.db import models


class PatientIntake(models.Model):
    """Private intake information, separate from the public queue token."""
    patient = models.OneToOneField('hospital_core.Patient', on_delete=models.PROTECT, related_name='intake')
    sex = models.CharField(max_length=30, blank=True)
    phone = models.CharField(max_length=40, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=180, blank=True)
    emergency_contact_phone = models.CharField(max_length=40, blank=True)
    allergies = models.TextField(blank=True)
    current_medications = models.TextField(blank=True)
    medical_history = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
