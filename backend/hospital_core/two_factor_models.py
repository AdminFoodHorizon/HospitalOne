
from django.conf import settings
from django.db import models
from django.utils import timezone


class TwoFactorCredential(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="two_factor_credential",
    )
    encrypted_secret = models.TextField(blank=True, default="")
    is_enabled = models.BooleanField(default=False)
    last_verified_step = models.BigIntegerField(
        null=True,
        blank=True,
        default=None,
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"2FA credential: {self.user.username}"


class TwoFactorRecoveryCode(models.Model):
    credential = models.ForeignKey(
        TwoFactorCredential,
        on_delete=models.CASCADE,
        related_name="recovery_codes",
    )
    code_hash = models.CharField(max_length=255)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    

    def __str__(self):
        return f"Recovery code for {self.credential.user.username}"

    @property
    def is_used(self):
        return self.used_at is not None


class AuthenticationAuditLog(models.Model):
    class Event(models.TextChoices):
        LOGIN_SUCCESS = "LOGIN_SUCCESS", "Login success"
        LOGIN_FAILED = "LOGIN_FAILED", "Login failed"
        TWO_FACTOR_SETUP = "TWO_FACTOR_SETUP", "2FA setup"
        TWO_FACTOR_SUCCESS = "TWO_FACTOR_SUCCESS", "2FA success"
        TWO_FACTOR_FAILED = "TWO_FACTOR_FAILED", "2FA failed"
        RECOVERY_USED = "RECOVERY_USED", "Recovery code used"
        TWO_FACTOR_RESET = "TWO_FACTOR_RESET", "2FA reset"
        LOGOUT = "LOGOUT", "Logout"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authentication_audit_logs",
    )
    hospital = models.ForeignKey(
        "hospital_core.Hospital",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    event = models.CharField(max_length=40, choices=Event.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event} at {self.created_at}"
