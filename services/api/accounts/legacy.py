"""Legacy profile and credential models, kept only until their data is migrated.

Everything in this module is superseded. ``providers.ProviderProfile`` replaces
``UserDetails`` and ``BarberDetails``, ``providers.Service`` replaces
``ServicesDetails``, and ``User.role`` plus ``User.is_verified`` replace the
``is_barber`` flag and the ``Emails`` table.

They are not deleted here because their tables hold production data. The
sequence is:

1. ``accounts/0005_migrate_legacy_profiles`` copies every row into the new models
2. ``accounts/0006_remove_legacy_profiles`` drops these models

Do not add fields to anything in this file. Do not use it in new code.
"""

from __future__ import annotations

from django.contrib.gis.db import models
from django.core.exceptions import ValidationError

from accounts.models import User

SERVICE_CHOICES = (
    ("barbershop", "barbershop"),
    ("hair_salon", "hair_salon"),
    ("beauty_salon", "beauty_salon"),
    ("full_service_salon", "full_service_salon"),
    ("other", "other"),
)

BUSINESS_CHOICES = (
    ("individual", "individual"),
    ("partnership", "partnership"),
    ("proprietorship", "proprietorship"),
    ("not_yet_registered", "not_yet_registered"),
)

ACCOUNT_CHOICES = (
    ("savings", "savings"),
    ("current", "current"),
)


def unique_validator(id):
    """Reject a second profile row for the same account.

    A database-level ``OneToOneField`` already prevents this, so the validator
    only ever fires during a manual ``full_clean()``.
    """
    if BarberDetails.objects.filter(id=id).exists() or UserDetails.objects.filter(id=id).exists():
        raise ValidationError("details already added. Please try logging out and logging back in.")


class Emails(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    email = models.EmailField()

    def __str__(self):
        return f"Email {self.email} verified for the user {self.user}"


class SignUpCodes(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=15)

    def __str__(self):
        return f"{self.code} created for user {self.user}"


class PasswordCodes(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=15)

    def __str__(self):
        return f"{self.code} created for user {self.user}"


class UserDetails(models.Model):
    id = models.OneToOneField(
        User, on_delete=models.CASCADE, primary_key=True, validators=[unique_validator]
    )
    image = models.ImageField(upload_to="image/")
    coords = models.PointField(null=False, blank=False, srid=4326, verbose_name="coords")
    location = models.CharField(max_length=1000)
    about = models.TextField(null=False, blank=True)
    contact = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"User details for the user {self.id} added"


class BarberDetails(models.Model):
    id = models.OneToOneField(
        User, on_delete=models.CASCADE, primary_key=True, validators=[unique_validator]
    )
    image = models.ImageField(upload_to="image/")
    coords = models.PointField(null=False, blank=False, srid=4326, verbose_name="coords")
    service_type = models.CharField(max_length=60, blank=False, null=False, choices=SERVICE_CHOICES)
    location = models.CharField(max_length=1000)
    about = models.TextField(null=False, blank=True)
    contact = models.CharField(max_length=200, blank=True)
    employee_count = models.PositiveIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self):
        return f"Barber details for the user {self.id} added"


class BankDetails(models.Model):
    """Provider payout account.

    Superseded by ``providers.ProviderPayout``, which encrypts the account
    number and masks it in every response. The columns here are plaintext.
    """

    id = models.OneToOneField(BarberDetails, on_delete=models.CASCADE, primary_key=True)
    business_name = models.CharField(max_length=100, blank=False, null=False)
    business_type = models.CharField(
        max_length=100, blank=False, null=False, choices=BUSINESS_CHOICES
    )
    beneficiary_name = models.CharField(max_length=60, null=False, blank=False)
    account_number = models.PositiveBigIntegerField(null=False, blank=False)
    ifsc_code = models.CharField(max_length=20, blank=False, null=False)
    account_type = models.CharField(max_length=60, blank=True, null=True, choices=ACCOUNT_CHOICES)
    account_id = models.CharField(max_length=60, null=False, blank=False)
    destination = models.CharField(max_length=60, null=False, blank=False)

    def __str__(self):
        return (
            f"Account with account_id {self.account_id} and "
            f"beneficiary name {self.beneficiary_name} created"
        )


class ServicesDetails(models.Model):
    service_provider = models.ForeignKey(BarberDetails, on_delete=models.CASCADE)
    service = models.CharField(max_length=100, blank=False, null=False)
    cost = models.PositiveIntegerField(blank=False, null=False)

    def __str__(self):
        return f"service '{self.service}' with cost {self.cost} added"
