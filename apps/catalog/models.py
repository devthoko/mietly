from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone


class Category(models.Model):
    name = models.CharField("Name", max_length=80, unique=True)
    sort = models.PositiveSmallIntegerField("Reihenfolge", default=0)

    class Meta:
        ordering = ["sort", "name"]
        verbose_name = "Kategorie"
        verbose_name_plural = "Kategorien"

    def __str__(self):
        return self.name


def article_image_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"articles/{timezone.now():%Y%m}/{instance.number or 'neu'}-{timezone.now():%H%M%S}.{ext}"


class Article(models.Model):
    number = models.CharField("Artikelnummer", max_length=20, unique=True)
    name = models.CharField("Bezeichnung", max_length=120)
    category = models.ForeignKey(Category, verbose_name="Kategorie", null=True, blank=True, on_delete=models.SET_NULL, related_name="articles")
    description = models.TextField("Beschreibung", blank=True)
    image = models.ImageField("Foto", upload_to=article_image_path, blank=True)
    storage_location = models.CharField("Lagerort", max_length=80, blank=True)
    price = models.DecimalField("Mietpreis (brutto)", max_digits=10, decimal_places=2, help_text="Preis pro Mietzeitraum und Stück")
    extra_day_price = models.DecimalField(
        "Zusatztag (brutto)", max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Preis pro Stück für jeden Tag über die inklusiven Miettage hinaus",
    )
    replacement_value = models.DecimalField("Wiederbeschaffungswert", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    deposit_per_unit = models.DecimalField("Kaution pro Stück", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    vat_rate = models.DecimalField("Steuersatz (%)", max_digits=4, decimal_places=1, null=True, blank=True, help_text="Leer = Standard aus den Einstellungen")
    active = models.BooleanField("Aktiv (vermietbar)", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Artikel"
        verbose_name_plural = "Artikel"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("catalog:article_detail", args=[self.pk])

    @property
    def stock(self):
        """Aktueller Gesamtbestand aus allen Bestandsbewegungen."""
        if hasattr(self, "_stock"):
            return self._stock
        total = self.movements.aggregate(s=Sum("quantity"))["s"] or 0
        self._stock = total
        return total


class StockMovement(models.Model):
    class Reason(models.TextChoices):
        INITIAL = "initial", "Anfangsbestand"
        PURCHASE = "purchase", "Zugang / Neukauf"
        LOSS = "loss", "Verlust / Fehlmenge"
        DAMAGE = "damage", "Ausgemustert (Schaden)"
        CORRECTION = "correction", "Inventurkorrektur"

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="movements")
    quantity = models.IntegerField("Menge")
    reason = models.CharField("Grund", max_length=20, choices=Reason.choices)
    note = models.CharField("Notiz", max_length=200, blank=True)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_movements")
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at"]


class Package(models.Model):
    name = models.CharField("Bezeichnung", max_length=120)
    description = models.TextField("Beschreibung", blank=True)
    price = models.DecimalField(
        "Paketpreis (brutto)", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Leer = Summe der enthaltenen Artikel",
    )
    vat_rate = models.DecimalField("Steuersatz (%)", max_digits=4, decimal_places=1, null=True, blank=True, help_text="Leer = Standard aus den Einstellungen")
    active = models.BooleanField("Aktiv", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Paket"
        verbose_name_plural = "Pakete"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("catalog:package_detail", args=[self.pk])

    def _item_rows(self):
        """Paketinhalt – nutzt vorab geladene Daten (prefetch_related), sonst eine Abfrage."""
        cache = getattr(self, "_prefetched_objects_cache", {})
        if "items" in cache:
            return list(cache["items"])
        rows = getattr(self, "_item_rows_cache", None)
        if rows is None:
            rows = self._item_rows_cache = list(self.items.select_related("article"))
        return rows

    @property
    def items_price(self):
        return sum((i.article.price * i.quantity for i in self._item_rows()), Decimal("0.00"))

    @property
    def effective_price(self):
        return self.price if self.price is not None else self.items_price

    @property
    def savings(self):
        if self.price is None:
            return Decimal("0.00")
        return max(Decimal("0.00"), self.items_price - self.price)

    @property
    def extra_day_price(self):
        return sum((i.article.extra_day_price * i.quantity for i in self._item_rows()), Decimal("0.00"))

    @property
    def deposit(self):
        return sum((i.article.deposit_per_unit * i.quantity for i in self._item_rows()), Decimal("0.00"))


class PackageItem(models.Model):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="items")
    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name="package_items")
    quantity = models.PositiveIntegerField("Menge", default=1)

    class Meta:
        unique_together = [("package", "article")]
        ordering = ["article__name"]

    @property
    def line_total(self):
        return self.article.price * self.quantity
