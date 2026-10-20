from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class Order(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "In Bearbeitung"
        COMPLETED = "completed", "Abgeschlossen"
        CANCELLED = "cancelled", "Storniert"

    class Fulfillment(models.TextChoices):
        PICKUP = "pickup", "Abholung durch Kunde"
        DELIVERY = "delivery", "Lieferung"

    number = models.CharField("Auftragsnummer", max_length=20, unique=True)
    customer = models.ForeignKey("customers.Customer", verbose_name="Kunde", null=True, blank=True, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    stage = models.PositiveSmallIntegerField("Aktueller Schritt", default=1)
    # Kurzstatus für Listen („Wartet auf Unterschrift“ …), wird von workflow.refresh_stage gepflegt
    next_action = models.CharField(max_length=120, blank=True)
    next_tone = models.CharField(max_length=10, blank=True)

    event_name = models.CharField("Veranstaltung", max_length=120, blank=True)
    event_date = models.DateField("Datum der Veranstaltung", null=True, blank=True)
    event_location = models.CharField("Veranstaltungsort", max_length=200, blank=True)
    fulfillment = models.CharField("Übergabeart", max_length=10, choices=Fulfillment.choices, default=Fulfillment.PICKUP)
    delivery_address = models.TextField("Lieferadresse", blank=True)
    handover_at = models.DateTimeField("Übergabe / Abholung", null=True, blank=True)
    return_at = models.DateTimeField("Rückgabe", null=True, blank=True)
    deposit_amount = models.DecimalField("Vereinbarte Kaution", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    deposit_manual = models.BooleanField(default=False)
    notes = models.TextField("Interne Notizen", blank=True)
    customer_note = models.TextField("Hinweis für den Kunden (erscheint auf Dokumenten)", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField("Stornogrund", max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Auftrag"
        verbose_name_plural = "Aufträge"

    def __str__(self):
        return f"{self.number} {self.event_name}".strip()

    def get_absolute_url(self):
        return reverse("orders:detail", args=[self.pk])

    @property
    def title(self):
        return self.event_name or "Neuer Auftrag"

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    @property
    def return_overdue(self):
        return self.is_active and self.stage == 8 and self.return_at is not None and self.return_at < timezone.now()

    @property
    def stage_title(self):
        from .workflow import STEPS

        return next((title for n, _, title in STEPS if n == self.stage), "")

    @property
    def rental_days(self):
        if not (self.handover_at and self.return_at):
            return 0
        start = timezone.localtime(self.handover_at).date()
        end = timezone.localtime(self.return_at).date()
        return max(1, (end - start).days)

    def _item_rows(self):
        """Positionen des Auftrags – nutzt vorab geladene Daten (prefetch_related), sonst eine Abfrage."""
        cache = getattr(self, "_prefetched_objects_cache", {})
        if "items" in cache:
            return list(cache["items"])
        return list(self.items.select_related("article", "package").prefetch_related("package__items__article"))

    def has_rental_items(self):
        """Mindestens ein Mietgegenstand (die Lieferpauschale allein zählt nicht)."""
        if "items" in getattr(self, "_prefetched_objects_cache", {}):
            return any(i.kind != "delivery" for i in self._item_rows())
        return self.items.exclude(kind="delivery").exists()

    @property
    def total(self):
        return sum((i.total for i in self._item_rows()), Decimal("0.00"))

    @property
    def suggested_deposit(self):
        total = Decimal("0.00")
        for item in self._item_rows():
            if item.article_id:
                total += item.article.deposit_per_unit * item.quantity
            elif item.package_id:
                total += item.package.deposit * item.quantity
        return money(total)

    def article_quantities(self):
        """Benötigte Stückzahl je Artikel (Pakete werden aufgelöst)."""
        result = {}
        for item in self._item_rows():
            if item.article_id:
                result[item.article] = result.get(item.article, 0) + item.quantity
            elif item.package_id:
                for pi in item.package.items.all():
                    result[pi.article] = result.get(pi.article, 0) + pi.quantity * item.quantity
        return result


class OrderItem(models.Model):
    class Kind(models.TextChoices):
        ARTICLE = "article", "Artikel"
        PACKAGE = "package", "Paket"
        CUSTOM = "custom", "Individuelle Position"
        DELIVERY = "delivery", "Lieferpauschale"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    article = models.ForeignKey("catalog.Article", null=True, blank=True, on_delete=models.PROTECT, related_name="order_items")
    package = models.ForeignKey("catalog.Package", null=True, blank=True, on_delete=models.PROTECT, related_name="order_items")
    description = models.CharField("Bezeichnung", max_length=200)
    detail = models.CharField("Zusatzinfo", max_length=300, blank=True)
    quantity = models.PositiveIntegerField("Menge", default=1)
    unit_price = models.DecimalField("Einzelpreis (brutto)", max_digits=10, decimal_places=2)
    discount_percent = models.DecimalField("Rabatt (%)", max_digits=5, decimal_places=2, default=Decimal("0"))
    vat_rate = models.DecimalField("Steuersatz (%)", max_digits=4, decimal_places=1)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return self.description

    @property
    def total(self):
        gross = Decimal(self.quantity) * self.unit_price
        if self.discount_percent:
            gross = gross * (Decimal("100") - self.discount_percent) / Decimal("100")
        return money(gross)


class Handover(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "In Vorbereitung"
        COMPLETED = "completed", "Abgeschlossen"

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="handover")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    performed_at = models.DateTimeField("Zeitpunkt der Übergabe", default=timezone.now)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    recipient_name = models.CharField("Entgegengenommen von", max_length=120, blank=True)
    notes = models.TextField("Bemerkungen", blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        # Letzte Verteidigungslinie: Die geschäftlichen Sperren gelten auch
        # für jeden direkten Speicherversuch, unabhängig von Rolle oder Weg.
        if self.status == self.Status.COMPLETED:
            from .workflow import assert_handover_completable

            assert_handover_completable(self.order, handover=self)
        super().save(*args, **kwargs)

    @property
    def is_completed(self):
        return self.status == self.Status.COMPLETED


class Condition(models.TextChoices):
    GOOD = "good", "Einwandfrei"
    USED = "used", "Gebrauchsspuren"
    DAMAGED = "damaged", "Beschädigt"


class HandoverItem(models.Model):
    handover = models.ForeignKey(Handover, on_delete=models.CASCADE, related_name="items")
    article = models.ForeignKey("catalog.Article", on_delete=models.PROTECT, related_name="+")
    planned_qty = models.PositiveIntegerField("Geplant")
    quantity = models.PositiveIntegerField("Übergeben")
    condition = models.CharField("Zustand", max_length=10, choices=Condition.choices, default=Condition.GOOD)
    existing_damage = models.CharField("Vorhandene Schäden", max_length=300, blank=True)
    note = models.CharField("Bemerkung", max_length=300, blank=True)

    class Meta:
        ordering = ["article__name"]


class ReturnRecord(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "In Bearbeitung"
        COMPLETED = "completed", "Abgeschlossen"

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="return_record")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    performed_at = models.DateTimeField("Zeitpunkt der Rücknahme", default=timezone.now)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    returned_by_name = models.CharField("Zurückgegeben von", max_length=120, blank=True)
    notes = models.TextField("Bemerkungen", blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.status == self.Status.COMPLETED:
            handover = getattr(self.order, "handover", None)
            if handover is None or not handover.is_completed:
                from .workflow import WorkflowError

                raise WorkflowError("Die Rücknahme setzt eine abgeschlossene Übergabe voraus.")
        super().save(*args, **kwargs)

    @property
    def is_completed(self):
        return self.status == self.Status.COMPLETED


class ReturnItem(models.Model):
    return_record = models.ForeignKey(ReturnRecord, on_delete=models.CASCADE, related_name="items")
    article = models.ForeignKey("catalog.Article", on_delete=models.PROTECT, related_name="+")
    expected_qty = models.PositiveIntegerField("Erwartet")
    returned_qty = models.PositiveIntegerField("Zurück")
    damaged_qty = models.PositiveIntegerField("Davon beschädigt", default=0)
    condition = models.CharField("Zustand", max_length=10, choices=Condition.choices, default=Condition.GOOD)
    note = models.CharField("Bemerkung", max_length=300, blank=True)

    class Meta:
        ordering = ["article__name"]

    @property
    def missing_qty(self):
        return max(0, self.expected_qty - self.returned_qty)


class Damage(models.Model):
    class Kind(models.TextChoices):
        DAMAGED = "damaged", "Beschädigung"
        MISSING = "missing", "Fehlmenge"
        CLEANING = "cleaning", "Sonderreinigung"
        OTHER = "other", "Sonstige Zusatzkosten"

    class Settlement(models.TextChoices):
        OPEN = "open", "Offen"
        DEPOSIT = "deposit", "Mit Kaution verrechnet"
        INVOICE = "invoice", "Nachberechnet"
        WAIVED = "waived", "Erlassen / kulanz"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="damages")
    article = models.ForeignKey("catalog.Article", null=True, blank=True, on_delete=models.PROTECT, related_name="damages")
    kind = models.CharField("Art", max_length=10, choices=Kind.choices)
    quantity = models.PositiveIntegerField("Menge", default=1)
    description = models.CharField("Beschreibung", max_length=300)
    amount = models.DecimalField("Betrag (brutto)", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    settlement = models.CharField("Abrechnung", max_length=10, choices=Settlement.choices, default=Settlement.OPEN)
    write_off = models.BooleanField("Aus dem Bestand ausbuchen", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["created_at"]


def photo_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"orders/{instance.order.number}/fotos/{instance.stage}-{timezone.now():%Y%m%d-%H%M%S%f}.{ext}"


class Photo(models.Model):
    class Stage(models.TextChoices):
        HANDOVER = "handover", "Übergabe"
        RETURN = "return", "Rücknahme"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="photos")
    stage = models.CharField(max_length=10, choices=Stage.choices)
    article = models.ForeignKey("catalog.Article", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    image = models.ImageField(upload_to=photo_path)
    caption = models.CharField("Beschreibung", max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["created_at"]


class DepositTransaction(models.Model):
    class Kind(models.TextChoices):
        RECEIVED = "received", "Kaution erhalten"
        REFUNDED = "refunded", "Kaution zurückgezahlt"
        RETAINED = "retained", "Kaution einbehalten"

    class Method(models.TextChoices):
        CASH = "cash", "Bar"
        TRANSFER = "transfer", "Überweisung"
        CARD = "card", "EC-/Kartenzahlung"
        PAYPAL = "paypal", "PayPal"
        OFFSET = "offset", "Verrechnung"
        OTHER = "other", "Sonstige"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="deposit_transactions")
    kind = models.CharField("Vorgang", max_length=10, choices=Kind.choices)
    amount = models.DecimalField("Betrag", max_digits=10, decimal_places=2)
    date = models.DateField("Datum", default=timezone.localdate)
    method = models.CharField("Zahlungsart", max_length=10, choices=Method.choices, default=Method.CASH)
    reason = models.CharField("Begründung / Notiz", max_length=300, blank=True)
    damage = models.ForeignKey(Damage, null=True, blank=True, on_delete=models.SET_NULL, related_name="deposit_transactions")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["date", "created_at"]
