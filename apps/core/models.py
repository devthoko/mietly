import contextvars
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from .crypto import decrypt, encrypt

# Betriebseinstellungen werden je Anfrage nur einmal gelesen (siehe RequestCacheMiddleware).
_settings_cache = contextvars.ContextVar("mietly_company_settings", default=None)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        STAFF = "staff", "Mitarbeiter"

    role = models.CharField("Rolle", max_length=10, choices=Role.choices, default=Role.STAFF)
    ui_theme = models.CharField(
        "Gestaltung", max_length=10, default="warm",
        choices=[("warm", "Warm – Leinen, Salbei, Serifenschrift"), ("klar", "Klar – hell, sachlich, Petrol")],
    )

    class Meta:
        verbose_name = "Benutzer"
        verbose_name_plural = "Benutzer"
        ordering = ["first_name", "last_name", "username"]

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        parts = [p for p in [self.first_name, self.last_name] if p]
        if parts:
            return "".join(p[0] for p in parts).upper()[:2]
        return self.username[:2].upper()


class CompanySettings(models.Model):
    """Einzige Zeile mit allen Betriebs- und Geschäftsdaten."""

    class SmtpSecurity(models.TextChoices):
        STARTTLS = "starttls", "STARTTLS (Port 587)"
        SSL = "ssl", "SSL/TLS (Port 465)"
        NONE = "none", "Keine Verschlüsselung"

    # Geschäftsdaten
    name = models.CharField("Firmenname", max_length=120, default="Mein Verleih")
    owner = models.CharField("Inhaber/in", max_length=120, blank=True)
    street = models.CharField("Straße und Hausnummer", max_length=120, blank=True)
    zip_code = models.CharField("PLZ", max_length=10, blank=True)
    city = models.CharField("Ort", max_length=80, blank=True)
    phone = models.CharField("Telefon", max_length=40, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    website = models.CharField("Website", max_length=120, blank=True)
    logo = models.ImageField("Logo", upload_to="company/", blank=True)

    # Steuern & Bank
    tax_number = models.CharField("Steuernummer", max_length=40, blank=True)
    vat_id = models.CharField("USt-IdNr.", max_length=20, blank=True)
    small_business = models.BooleanField(
        "Kleinunternehmer (§ 19 UStG)",
        default=False,
        help_text="Wenn aktiv, wird keine Umsatzsteuer ausgewiesen.",
    )
    default_vat_rate = models.DecimalField("Standard-Steuersatz (%)", max_digits=4, decimal_places=1, default=Decimal("19.0"))
    bank_name = models.CharField("Bank", max_length=80, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    bic = models.CharField("BIC", max_length=11, blank=True)
    account_holder = models.CharField("Kontoinhaber/in", max_length=120, blank=True)

    # Geschäftsregeln
    payment_due_days = models.PositiveSmallIntegerField(
        "Zahlungsziel (Tage nach Rechnung)", default=7,
        help_text="Die Rechnung muss spätestens vor der Übergabe vollständig bezahlt sein.",
    )
    offer_valid_days = models.PositiveSmallIntegerField("Angebot gültig (Tage)", default=14)
    included_rental_days = models.PositiveSmallIntegerField(
        "Im Mietpreis enthaltene Tage", default=3,
        help_text="Für jeden weiteren Tag wird der Zusatztagespreis des Artikels berechnet.",
    )
    buffer_days = models.PositiveSmallIntegerField(
        "Puffertage nach Rückgabe", default=1,
        help_text="Zeit für Reinigung und Prüfung, bevor ein Artikel wieder verfügbar ist.",
    )
    deposit_required_before_handover = models.BooleanField(
        "Kaution vor Übergabe erforderlich", default=True,
        help_text="Eine vereinbarte Kaution muss vor der Übergabe vollständig eingegangen sein.",
    )
    cancellation_terms = models.TextField(
        "Stornobedingungen (Kurzfassung)", blank=True,
        default="Bis 30 Tage vor dem Mietbeginn kostenfrei, bis 14 Tage vorher 50 %, danach 80 % des Mietpreises.",
    )
    delivery_fee = models.DecimalField(
        "Lieferpauschale (brutto)", max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Wird bei Lieferung automatisch als Position „Lieferung und Abholung“ ergänzt. 0 = keine Pauschale.",
    )
    mail_greeting = models.CharField(
        "Anrede in E-Mails", max_length=10, default="formal",
        choices=[("formal", "Förmlich – „Sehr geehrte Frau Weber,“"), ("informal", "Persönlich – „Hallo Anna,“")],
    )

    # E-Mail
    smtp_host = models.CharField("SMTP-Server", max_length=120, blank=True)
    smtp_port = models.PositiveIntegerField("SMTP-Port", default=587)
    smtp_security = models.CharField("Verschlüsselung", max_length=10, choices=SmtpSecurity.choices, default=SmtpSecurity.STARTTLS)
    smtp_user = models.CharField("SMTP-Benutzer", max_length=120, blank=True)
    smtp_password_enc = models.TextField(blank=True)
    mail_from_email = models.EmailField("Absender-Adresse", blank=True)
    mail_from_name = models.CharField("Absender-Name", max_length=120, blank=True)
    mail_bcc = models.EmailField("Kopie aller E-Mails an (BCC)", blank=True)

    # Drucker (CUPS-Warteschlange „mietly“)
    printer_host = models.CharField("IP-Adresse des Druckers", max_length=255, blank=True,
                                    help_text="z. B. 192.168.1.50 – der Drucker muss im selben Netzwerk erreichbar sein.")
    printer_model = models.CharField("Druckermodell", max_length=200, blank=True)
    printer_driver = models.CharField("Treiber", max_length=200, blank=True)
    printer_uri = models.CharField(max_length=300, blank=True)
    printer_ready = models.BooleanField(default=False)
    printer_last_test = models.DateTimeField(null=True, blank=True)
    printer_last_result = models.TextField(blank=True)

    # WebDAV / Nextcloud
    webdav_enabled = models.BooleanField("WebDAV-Synchronisierung aktiv", default=False)
    webdav_url = models.URLField(
        "WebDAV-URL", blank=True,
        help_text="z. B. https://cloud.example.de/remote.php/dav/files/BENUTZER/",
    )
    webdav_user = models.CharField("WebDAV-Benutzer", max_length=120, blank=True)
    webdav_password_enc = models.TextField(blank=True)
    webdav_folder = models.CharField("Zielordner", max_length=200, default="mietly")
    webdav_sync_documents = models.BooleanField("Dokumente synchronisieren", default=True)
    webdav_sync_backups = models.BooleanField("Backups hochladen (verschlüsselt)", default=True)
    backup_passphrase_enc = models.TextField(blank=True)
    webdav_last_sync = models.DateTimeField(null=True, blank=True)
    webdav_last_status = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Betriebseinstellungen"

    def __str__(self):
        return self.name

    @classmethod
    def get(cls):
        cache = _settings_cache.get()
        if cache is not None and "obj" in cache:
            return cache["obj"]
        obj = cls.objects.order_by("pk").first()
        if obj is None:
            try:
                with transaction.atomic():
                    obj, _ = cls.objects.get_or_create(pk=1)
            except IntegrityError:
                obj = cls.objects.get(pk=1)
        if cache is not None:
            cache["obj"] = obj
        return obj

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache = _settings_cache.get()
        if cache is not None:
            cache.pop("obj", None)

    @property
    def smtp_password(self):
        return decrypt(self.smtp_password_enc)

    @smtp_password.setter
    def smtp_password(self, value):
        self.smtp_password_enc = encrypt(value) if value else ""

    @property
    def webdav_password(self):
        return decrypt(self.webdav_password_enc)

    @webdav_password.setter
    def webdav_password(self, value):
        self.webdav_password_enc = encrypt(value) if value else ""

    @property
    def backup_passphrase(self):
        return decrypt(self.backup_passphrase_enc)

    @backup_passphrase.setter
    def backup_passphrase(self, value):
        self.backup_passphrase_enc = encrypt(value) if value else ""

    @property
    def mail_configured(self):
        return bool(self.smtp_host and self.mail_from_email)

    @property
    def address_line(self):
        parts = [self.name, self.street, f"{self.zip_code} {self.city}".strip()]
        return " · ".join(p for p in parts if p)

    @property
    def vat_rate(self):
        return Decimal("0") if self.small_business else self.default_vat_rate


class NumberSequence(models.Model):
    """Fortlaufende, lückenlose Nummernkreise pro Belegart und Jahr."""

    kind = models.CharField(max_length=20)
    year = models.PositiveSmallIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("kind", "year")]

    def __str__(self):
        return f"{self.kind} {self.year}: {self.last_number}"


class AuditLog(models.Model):
    """Unveränderliches Aktivitätsprotokoll (wer hat wann was getan)."""

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=60)
    message = models.CharField(max_length=500)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="activities")
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Aktivität"
        verbose_name_plural = "Aktivitäten"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Einträge im Aktivitätsprotokoll sind unveränderlich.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Einträge im Aktivitätsprotokoll können nicht gelöscht werden.")


class TextTemplate(models.Model):
    """Bearbeitbare, versionierte Textvorlagen (Vertrag, AGB, E-Mails …)."""

    class Key(models.TextChoices):
        CONTRACT = "contract", "Mietvertrag"
        TERMS = "terms", "Allgemeine Mietbedingungen"
        WITHDRAWAL = "withdrawal", "Widerrufsbelehrung"
        PRIVACY = "privacy", "Datenschutzhinweis"
        OFFER_INTRO = "offer_intro", "Angebot – Einleitung"
        OFFER_OUTRO = "offer_outro", "Angebot – Schlusstext"
        INVOICE_OUTRO = "invoice_outro", "Rechnung – Schlusstext"
        INVOICE_OUTRO_FOLLOWUP = "invoice_outro_followup", "Nachberechnung & Stornogebühr – Schlusstext"
        HANDOVER_CONFIRM = "handover_confirm", "Übergabeprotokoll – Bestätigungstext"
        MAIL_OFFER = "mail_offer", "E-Mail: Angebot"
        MAIL_OFFER_SIGNED = "mail_offer_signed", "E-Mail: Angebot (unterschrieben, zur Ablage)"
        MAIL_CONTRACT = "mail_contract", "E-Mail: Mietvertrag"
        MAIL_CONTRACT_SIGNED = "mail_contract_signed", "E-Mail: Mietvertrag (unterschrieben, zur Ablage)"
        MAIL_INVOICE = "mail_invoice", "E-Mail: Rechnung"
        MAIL_ADDITIONAL = "mail_additional", "E-Mail: Nachberechnung"
        MAIL_FEE = "mail_fee", "E-Mail: Stornogebühr"
        MAIL_CANCELLATION = "mail_cancellation", "E-Mail: Stornorechnung"
        MAIL_HANDOVER = "mail_handover", "E-Mail: Übergabeprotokoll"
        MAIL_RETURN = "mail_return", "E-Mail: Rücknahmeprotokoll"
        MAIL_DEPOSIT = "mail_deposit", "E-Mail: Kautionsabrechnung"

    key = models.CharField(max_length=30, choices=Key.choices)
    version = models.PositiveIntegerField()
    subject = models.CharField("Betreff", max_length=200, blank=True)
    body = models.TextField("Text")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        unique_together = [("key", "version")]
        ordering = ["key", "-version"]

    def __str__(self):
        return f"{self.get_key_display()} v{self.version}"

    @classmethod
    def current(cls, key):
        tpl = cls.objects.filter(key=key).order_by("-version").first()
        if tpl is None:
            from .defaults import DEFAULT_TEMPLATES

            subject, body = DEFAULT_TEMPLATES[key]
            try:
                with transaction.atomic():
                    tpl, _ = cls.objects.get_or_create(key=key, version=1, defaults={"subject": subject, "body": body})
            except IntegrityError:
                tpl = cls.objects.filter(key=key).order_by("-version").first()
        return tpl


class EmailLog(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Wird gesendet"
        SENT = "sent", "Gesendet"
        FAILED = "failed", "Fehlgeschlagen"

    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="emails")
    to = models.CharField(max_length=300)
    subject = models.CharField(max_length=300)
    body = models.TextField()
    attachments = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    error = models.TextField(blank=True)
    # Versand im Hintergrund mit automatischen Wiederholungen
    document_ids = models.JSONField(default=list, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class LoginAttempt(models.Model):
    """Zählt fehlgeschlagene Anmeldungen zum Schutz vor dem Durchprobieren von Passwörtern."""

    username = models.CharField(max_length=150, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
