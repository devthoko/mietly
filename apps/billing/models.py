from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Invoice(models.Model):
    """Rechnung nach § 14 UStG. Nach dem Ausstellen unveränderlich (GoBD);
    Korrekturen erfolgen ausschließlich über eine Stornorechnung."""

    class Kind(models.TextChoices):
        INVOICE = "invoice", "Rechnung"
        ADDITIONAL = "additional", "Nachberechnung"
        CANCELLATION_FEE = "fee", "Stornogebühr"
        CANCELLATION = "cancellation", "Stornorechnung"

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="invoices")
    document = models.OneToOneField("documents.Document", null=True, blank=True, on_delete=models.PROTECT, related_name="invoice")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.INVOICE)
    number = models.CharField("Rechnungsnummer", max_length=20, unique=True)
    issue_date = models.DateField("Rechnungsdatum", default=timezone.localdate)
    service_period = models.CharField("Leistungszeitraum", max_length=100)
    due_date = models.DateField("Fällig am")
    cancels = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="cancelled_by")
    small_business = models.BooleanField(default=False)
    total_gross = models.DecimalField(max_digits=10, decimal_places=2)
    total_net = models.DecimalField(max_digits=10, decimal_places=2)
    total_vat = models.DecimalField(max_digits=10, decimal_places=2)
    vat_breakdown = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["issue_date", "id"]
        verbose_name = "Rechnung"
        verbose_name_plural = "Rechnungen"

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if self.pk and Invoice.objects.filter(pk=self.pk).exists():
            original = Invoice.objects.get(pk=self.pk)
            locked = ["number", "issue_date", "total_gross", "total_net", "total_vat", "kind", "order_id", "cancels_id"]
            if any(getattr(original, f) != getattr(self, f) for f in locked):
                raise ValueError("Ausgestellte Rechnungen sind unveränderlich. Bitte eine Stornorechnung erstellen.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Rechnungen können nicht gelöscht werden (GoBD). Bitte eine Stornorechnung erstellen.")

    @property
    def is_cancelled(self):
        return hasattr(self, "cancelled_by") and self.cancelled_by is not None

    @property
    def is_active(self):
        """Wirksame Forderung: weder storniert noch selbst eine Stornorechnung."""
        return self.kind != self.Kind.CANCELLATION and not self.is_cancelled


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveSmallIntegerField()
    description = models.CharField(max_length=300)
    detail = models.CharField(max_length=300, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    vat_rate = models.DecimalField(max_digits=4, decimal_places=1)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["position"]


class Payment(models.Model):
    """Zahlungseingang (positiv) oder Rückerstattung (negativ) zu einem Auftrag."""

    class Method(models.TextChoices):
        TRANSFER = "transfer", "Überweisung"
        CASH = "cash", "Bar"
        CARD = "card", "EC-/Kartenzahlung"
        PAYPAL = "paypal", "PayPal"
        OTHER = "other", "Sonstige"

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payments")
    invoice = models.ForeignKey(Invoice, null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField("Betrag", max_digits=10, decimal_places=2)
    paid_on = models.DateField("Zahlungsdatum", default=timezone.localdate)
    method = models.CharField("Zahlungsart", max_length=10, choices=Method.choices, default=Method.TRANSFER)
    reference = models.CharField("Referenz / Verwendungszweck", max_length=200, blank=True)
    note = models.CharField("Notiz", max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["paid_on", "created_at"]
        verbose_name = "Zahlung"
        verbose_name_plural = "Zahlungen"

    @property
    def is_refund(self):
        return self.amount < 0


def order_paid_total(order) -> Decimal:
    return order.payments.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
