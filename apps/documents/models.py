from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


def ascii_name(text):
    """Dateinamen ohne Umlaute und Leerzeichen – manche Mailprogramme kommen damit nicht zurecht."""
    for a, b in {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss", " ": "_"}.items():
        text = text.replace(a, b)
    return text


def document_path(instance, filename):
    return f"orders/{instance.order.number}/dokumente/{filename}"


def signature_path(instance, filename):
    return f"orders/{instance.order.number}/unterschriften/{filename}"


class Document(models.Model):
    """Ein erzeugtes Dokument. Ausgestellte Dokumente sind unveränderlich;
    Änderungen erzeugen eine neue Version, die alte bleibt in der Historie."""

    class Kind(models.TextChoices):
        OFFER = "offer", "Angebot"
        CONTRACT = "contract", "Mietvertrag"
        INVOICE = "invoice", "Rechnung"
        PACKING_LIST = "packing_list", "Packliste"
        HANDOVER = "handover", "Übergabeprotokoll"
        RETURN = "return", "Rücknahmeprotokoll"
        DEPOSIT = "deposit", "Kautionsabrechnung"

    class Status(models.TextChoices):
        ISSUED = "issued", "Erstellt"
        SIGNED = "signed", "Unterschrieben"
        SUPERSEDED = "superseded", "Ersetzt"
        VOID = "void", "Storniert"

    class SignatureMethod(models.TextChoices):
        DRAWN = "drawn", "Digital unterschrieben"
        UPLOAD = "upload", "Unterschriebenes Dokument hochgeladen"

    SIGNATURE_REQUIRED = {Kind.OFFER, Kind.CONTRACT, Kind.HANDOVER}

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="documents")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    number = models.CharField("Nummer", max_length=40)
    version = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ISSUED)
    title = models.CharField(max_length=200)

    file = models.FileField(upload_to=document_path)
    sha256 = models.CharField(max_length=64)
    data = models.JSONField("Eingefrorene Daten", default=dict)
    template_versions = models.JSONField(default=dict, blank=True)

    signature_method = models.CharField(max_length=10, choices=SignatureMethod.choices, blank=True)
    signer_name = models.CharField("Unterzeichnet von", max_length=120, blank=True)
    signature_image = models.FileField(upload_to=signature_path, blank=True)
    signed_file = models.FileField(upload_to=document_path, blank=True)
    signed_sha256 = models.CharField(max_length=64, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_ip = models.GenericIPAddressField(null=True, blank=True)
    signed_user_agent = models.CharField(max_length=300, blank=True)
    signed_recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    last_emailed_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Dokument"
        verbose_name_plural = "Dokumente"
        indexes = [models.Index(fields=["order", "kind", "status"])]

    def __str__(self):
        return self.display_name

    def get_absolute_url(self):
        return reverse("documents:download", args=[self.pk])

    @property
    def label(self):
        """Bezeichnung für Anzeige und E-Mail – bei Rechnungen die konkrete Art
        (Stornorechnung, Nachberechnung, Stornogebühr)."""
        if self.kind == self.Kind.INVOICE and self.title:
            return self.title
        return self.get_kind_display()

    @property
    def display_name(self):
        name = f"{self.label} {self.number}"
        if self.version > 1:
            name += f" (Version {self.version})"
        return name

    @property
    def requires_signature(self):
        return self.kind in self.SIGNATURE_REQUIRED

    @property
    def is_signed(self):
        return self.status == self.Status.SIGNED

    @property
    def is_current(self):
        return self.status in {self.Status.ISSUED, self.Status.SIGNED}

    @property
    def final_file(self):
        """Die maßgebliche Datei: unterschriebene Fassung, sonst das Original."""
        return self.signed_file if self.signed_file else self.file

    @property
    def final_filename(self):
        """Dateiname der maßgeblichen Fassung mit korrekter Endung (PDF oder Foto)."""
        if not self.signed_file:
            return self.filename
        ext = (self.signed_file.name.rsplit(".", 1)[-1] if "." in self.signed_file.name else "pdf").lower()
        return self.filename[:-4] + f"_unterschrieben.{ext}"

    @property
    def filename(self):
        v = f"_v{self.version}" if self.version > 1 else ""
        return f"{ascii_name(self.label)}_{self.number}{v}.pdf"
