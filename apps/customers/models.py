from django.db import models
from django.urls import reverse


class Customer(models.Model):
    class Salutation(models.TextChoices):
        NONE = "", "—"
        MS = "Frau", "Frau"
        MR = "Herr", "Herr"
        DIV = "Divers", "Divers"

    number = models.CharField("Kundennummer", max_length=20, unique=True)
    salutation = models.CharField("Anrede", max_length=10, choices=Salutation.choices, blank=True)
    first_name = models.CharField("Vorname", max_length=80)
    last_name = models.CharField("Nachname", max_length=80)
    email = models.EmailField("E-Mail", blank=True)
    phone = models.CharField("Telefon", max_length=40, blank=True)
    street = models.CharField("Straße und Hausnummer", max_length=120, blank=True)
    zip_code = models.CharField("PLZ", max_length=10, blank=True)
    city = models.CharField("Ort", max_length=80, blank=True)
    notes = models.TextField("Interne Notizen", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    anonymized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = "Kunde"
        verbose_name_plural = "Kunden"
        indexes = [models.Index(fields=["last_name", "first_name"])]

    def __str__(self):
        return self.full_name

    def get_absolute_url(self):
        return reverse("customers:detail", args=[self.pk])

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def address_lines(self):
        return [line for line in [self.street, f"{self.zip_code} {self.city}".strip()] if line]

    @property
    def address_inline(self):
        return ", ".join(self.address_lines)

    @property
    def is_anonymized(self):
        return self.anonymized_at is not None
