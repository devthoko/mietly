from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from .models import CompanySettings, User
from .textrender import unknown_placeholders


class StyledMixin:
    """Versieht alle Eingabefelder mit den Klassen des Designsystems."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, f in self.fields.items():
            w = f.widget
            if isinstance(w, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
                continue
            css = w.attrs.get("class", "")
            w.attrs["class"] = f"{css} input".strip()
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault("rows", 3)


class StyledForm(StyledMixin, forms.Form):
    pass


class StyledModelForm(StyledMixin, forms.ModelForm):
    pass


def check_amounts(form, data, money_fields=(), vat_fields=()):
    """Beträge dürfen nicht negativ sein, Steuersätze müssen zwischen 0 und 100 % liegen."""
    for name in money_fields:
        value = data.get(name)
        if value is not None and value < 0:
            form.add_error(name, "Der Betrag darf nicht negativ sein.")
    for name in vat_fields:
        value = data.get(name)
        if value is not None and not (0 <= value <= 100):
            form.add_error(name, "Der Steuersatz muss zwischen 0 und 100 % liegen.")
    return data


def validate_upload_size(f):
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    if f and f.size > limit:
        raise ValidationError(f"Die Datei ist zu groß (maximal {settings.MAX_UPLOAD_MB} MB).")


class LoginForm(StyledForm):
    username = forms.CharField(label="Benutzername", max_length=150, widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}))
    password = forms.CharField(label="Passwort", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class CompanyForm(StyledModelForm):
    class Meta:
        model = CompanySettings
        fields = ["name", "owner", "street", "zip_code", "city", "phone", "email", "website", "logo"]
        widgets = {"logo": forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,image/webp"})}

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and hasattr(logo, "content_type"):
            validate_upload_size(logo)
            from .images import process_image

            return process_image(logo, max_side=1200)
        return logo


class TaxBankForm(StyledModelForm):
    class Meta:
        model = CompanySettings
        fields = ["small_business", "default_vat_rate", "tax_number", "vat_id", "account_holder", "bank_name", "iban", "bic"]

    def clean_iban(self):
        iban = self.cleaned_data["iban"].replace(" ", "").replace("-", "").upper()
        if iban:
            if len(iban) < 15 or len(iban) > 34 or not iban[:2].isalpha() or not iban[2:4].isdigit() or not iban.isalnum() or not iban.isascii():
                raise ValidationError("Bitte eine gültige IBAN eingeben.")
            rearranged = iban[4:] + iban[:4]
            digits = "".join(str(int(c, 36)) for c in rearranged)
            if int(digits) % 97 != 1:
                raise ValidationError("Die Prüfziffer der IBAN stimmt nicht.")
        return iban

    def clean(self):
        data = check_amounts(self, super().clean(), vat_fields=["default_vat_rate"])
        if not data.get("small_business") and not (data.get("tax_number") or data.get("vat_id")):
            self.add_error("tax_number", "Für Rechnungen ist eine Steuernummer oder USt-IdNr. erforderlich (§ 14 UStG).")
        return data


class RulesForm(StyledModelForm):
    class Meta:
        model = CompanySettings
        fields = [
            "payment_due_days", "offer_valid_days", "included_rental_days", "buffer_days",
            "deposit_required_before_handover", "cancellation_terms", "delivery_fee",
        ]


class MailForm(StyledModelForm):
    smtp_password = forms.CharField(
        label="SMTP-Passwort", required=False, widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Leer lassen, um das gespeicherte Passwort beizubehalten.",
    )

    class Meta:
        model = CompanySettings
        fields = ["smtp_host", "smtp_port", "smtp_security", "smtp_user", "mail_from_email", "mail_from_name", "mail_bcc", "mail_greeting"]

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("smtp_password"):
            obj.smtp_password = self.cleaned_data["smtp_password"]
        if commit:
            obj.save()
        return obj


class WebdavForm(StyledModelForm):
    webdav_password = forms.CharField(
        label="Passwort (am besten ein App-Passwort)", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Leer lassen, um das gespeicherte Passwort beizubehalten. In Nextcloud am besten ein App-Passwort verwenden.",
    )
    backup_passphrase = forms.CharField(
        label="Kennwort für die Verschlüsselung", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Mindestens 12 Zeichen. Ohne dieses Kennwort lassen sich die Sicherungen in der Cloud nicht öffnen – bitte gut aufbewahren!",
    )

    class Meta:
        model = CompanySettings
        fields = ["webdav_enabled", "webdav_url", "webdav_user", "webdav_folder", "webdav_sync_documents", "webdav_sync_backups"]
        labels = {
            "webdav_enabled": "Cloud-Ablage einschalten",
            "webdav_url": "Adresse Ihrer Cloud (WebDAV)",
            "webdav_user": "Benutzername",
            "webdav_folder": "Ordner in der Cloud",
            "webdav_sync_documents": "Dokumente ablegen",
            "webdav_sync_backups": "Datensicherung verschlüsselt ablegen",
        }
        help_texts = {"webdav_url": "In Nextcloud: Einstellungen (unten links) → WebDAV, z. B. https://cloud.example.de/remote.php/dav/files/NAME/"}

    def clean(self):
        data = super().clean()
        passphrase = data.get("backup_passphrase")
        if passphrase and len(passphrase) < 12:
            self.add_error("backup_passphrase", "Die Passphrase muss mindestens 12 Zeichen lang sein.")
        if data.get("webdav_enabled"):
            if not data.get("webdav_url"):
                self.add_error("webdav_url", "Bitte die WebDAV-URL angeben.")
            if data.get("webdav_sync_backups") and not (passphrase or self.instance.backup_passphrase):
                self.add_error("backup_passphrase", "Für den Backup-Upload ist eine Passphrase erforderlich.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("webdav_password"):
            obj.webdav_password = self.cleaned_data["webdav_password"]
        if self.cleaned_data.get("backup_passphrase"):
            obj.backup_passphrase = self.cleaned_data["backup_passphrase"]
        if commit:
            obj.save()
        return obj


class TextTemplateForm(StyledForm):
    subject = forms.CharField(label="Betreff", max_length=200, required=False)
    body = forms.CharField(label="Text", widget=forms.Textarea(attrs={"class": "code", "rows": 22}))

    def __init__(self, *args, key=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not (key or "").startswith("mail_"):
            del self.fields["subject"]

    def clean(self):
        data = super().clean()
        unknown = unknown_placeholders((data.get("subject") or "") + (data.get("body") or ""))
        if unknown:
            raise ValidationError("Unbekannte Platzhalter: " + ", ".join("{{" + u + "}}" for u in unknown))
        return data


class UserForm(StyledModelForm):
    password1 = forms.CharField(label="Passwort", required=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Passwort wiederholen", required=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "role", "is_active"]
        labels = {"username": "Benutzername", "first_name": "Vorname", "last_name": "Nachname", "email": "E-Mail", "is_active": "Konto aktiv"}
        help_texts = {"username": "", "is_active": "Deaktivierte Benutzer können sich nicht mehr anmelden."}

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        if self.instance.pk is None:
            self.fields["password1"].required = True
            self.fields["password2"].required = True

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "Die Passwörter stimmen nicht überein.")
            else:
                try:
                    password_validation.validate_password(p1, self.instance)
                except ValidationError as e:
                    self.add_error("password1", e)
        if self.instance.pk and self.acting_user and self.instance.pk == self.acting_user.pk:
            if data.get("role") != User.Role.ADMIN or not data.get("is_active"):
                raise ValidationError("Sie können sich nicht selbst die Administratorrechte entziehen oder sich deaktivieren.")
        if self.instance.pk and self.instance.is_admin and (data.get("role") != User.Role.ADMIN or not data.get("is_active")):
            if not User.objects.filter(role=User.Role.ADMIN, is_active=True).exclude(pk=self.instance.pk).exists():
                raise ValidationError("Es muss mindestens ein aktiver Administrator bestehen bleiben.")
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class ProfileForm(StyledModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "ui_theme"]
        widgets = {"ui_theme": forms.RadioSelect()}
        labels = {"first_name": "Vorname", "last_name": "Nachname", "email": "E-Mail"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ui_theme"].required = False

    def clean_ui_theme(self):
        # Fehlt die Auswahl (z. B. ältere Formulare), bleibt die bisherige Gestaltung
        return self.cleaned_data.get("ui_theme") or self.instance.ui_theme


class PasswordChangeForm(StyledForm):
    old_password = forms.CharField(label="Aktuelles Passwort", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    new_password1 = forms.CharField(label="Neues Passwort", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    new_password2 = forms.CharField(label="Neues Passwort wiederholen", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        if not self.user.check_password(self.cleaned_data["old_password"]):
            raise ValidationError("Das aktuelle Passwort ist nicht korrekt.")
        return self.cleaned_data["old_password"]

    def clean(self):
        data = super().clean()
        if data.get("new_password1") != data.get("new_password2"):
            self.add_error("new_password2", "Die Passwörter stimmen nicht überein.")
        elif data.get("new_password1"):
            try:
                password_validation.validate_password(data["new_password1"], self.user)
            except ValidationError as e:
                self.add_error("new_password1", e)
        return data


class TestMailForm(StyledForm):
    to = forms.EmailField(label="Test-E-Mail senden an")
