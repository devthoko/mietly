from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.billing.models import Payment
from apps.core.forms import StyledForm, StyledModelForm

from .models import Damage, DepositTransaction, Order

DT_FORMAT = "%Y-%m-%dT%H:%M"


class DateTimeLocal(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format=DT_FORMAT, **kwargs)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class EventForm(StyledModelForm):
    class Meta:
        model = Order
        fields = ["event_name", "event_date", "event_location", "fulfillment", "delivery_address", "handover_at", "return_at", "customer_note", "notes"]
        widgets = {
            "event_date": DateInput(),
            "handover_at": DateTimeLocal(),
            "return_at": DateTimeLocal(),
            "fulfillment": forms.RadioSelect(),
            "delivery_address": forms.Textarea(attrs={"rows": 2}),
            "customer_note": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {"handover_at": "Übergabe / Abholung am", "return_at": "Rückgabe am"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ["event_name", "event_date", "handover_at", "return_at"]:
            self.fields[f].required = True
        self.fields["handover_at"].input_formats = [DT_FORMAT]
        self.fields["return_at"].input_formats = [DT_FORMAT]
        self.fields["event_name"].widget.attrs["placeholder"] = "z. B. Hochzeit Anna & Ben"

    def clean(self):
        data = super().clean()
        h, r, e = data.get("handover_at"), data.get("return_at"), data.get("event_date")
        if h and r and r <= h:
            self.add_error("return_at", "Die Rückgabe muss nach der Übergabe liegen.")
        if h and r and e:
            if not (timezone.localtime(h).date() <= e <= timezone.localtime(r).date()):
                self.add_error("event_date", "Das Eventdatum muss zwischen Übergabe und Rückgabe liegen.")
        if data.get("fulfillment") == Order.Fulfillment.DELIVERY and not (data.get("delivery_address") or "").strip():
            self.add_error("delivery_address", "Bitte die Lieferadresse angeben.")
        return data


class CustomItemForm(StyledForm):
    description = forms.CharField(label="Bezeichnung", max_length=200)
    detail = forms.CharField(label="Zusatzinfo", max_length=300, required=False)
    quantity = forms.IntegerField(label="Menge", min_value=1, max_value=9999, initial=1)
    unit_price = forms.DecimalField(label="Einzelpreis (brutto)", max_digits=10, decimal_places=2, min_value=Decimal("0"))
    vat_rate = forms.DecimalField(label="Steuersatz (%)", max_digits=4, decimal_places=1, required=False, help_text="Leer = Standard",
                                  min_value=Decimal("0"), max_value=Decimal("100"))


class DepositAmountForm(StyledForm):
    amount = forms.DecimalField(label="Kaution", max_digits=10, decimal_places=2, min_value=Decimal("0"))


class PaymentForm(StyledModelForm):
    class Meta:
        model = Payment
        fields = ["amount", "paid_on", "method", "reference", "note"]
        widgets = {"paid_on": DateInput()}


class DepositForm(StyledModelForm):
    class Meta:
        model = DepositTransaction
        fields = ["amount", "date", "method", "reason"]
        widgets = {"date": DateInput()}
        labels = {"reason": "Notiz"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].choices = [c for c in DepositTransaction.Method.choices if c[0] != "offset"]


class HandoverForm(StyledForm):
    performed_at = forms.DateTimeField(label="Zeitpunkt", widget=DateTimeLocal(), input_formats=[DT_FORMAT])
    recipient_name = forms.CharField(label="Entgegengenommen von", max_length=120)
    notes = forms.CharField(label="Bemerkungen", required=False, widget=forms.Textarea(attrs={"rows": 2}))


class ReturnForm(StyledForm):
    performed_at = forms.DateTimeField(label="Zeitpunkt", widget=DateTimeLocal(), input_formats=[DT_FORMAT])
    returned_by_name = forms.CharField(label="Zurückgegeben von", max_length=120, required=False)
    notes = forms.CharField(label="Bemerkungen", required=False, widget=forms.Textarea(attrs={"rows": 2}))


class DamageForm(StyledModelForm):
    class Meta:
        model = Damage
        fields = ["kind", "article", "quantity", "description", "amount", "write_off"]

    def __init__(self, *args, order=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.catalog.models import Article

        ids = [a.pk for a in order.article_quantities()] if order else []
        self.fields["article"].queryset = Article.objects.filter(pk__in=ids)
        self.fields["article"].required = False
        self.fields["article"].empty_label = "— kein bestimmter Artikel —"
        self.fields["write_off"].help_text = "Der Artikel ist nicht mehr vermietbar und wird aus dem Bestand gebucht."

    def clean(self):
        data = super().clean()
        if data.get("amount") is not None and data["amount"] < 0:
            self.add_error("amount", "Der Betrag darf nicht negativ sein.")
        if data.get("quantity") is not None and data["quantity"] < 1:
            self.add_error("quantity", "Die Menge muss mindestens 1 sein.")
        if data.get("write_off") and not data.get("article"):
            self.add_error("write_off", "Ausbuchen ist nur mit einem bestimmten Artikel möglich.")
        return data


class CancelForm(StyledForm):
    reason = forms.CharField(label="Grund der Stornierung", max_length=300)
    fee = forms.DecimalField(label="Stornogebühr (brutto)", max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False,
                             help_text="Optional, gemäß den vereinbarten Stornobedingungen")


class EmailForm(StyledForm):
    to = forms.EmailField(label="An")
    subject = forms.CharField(label="Betreff", max_length=300)
    body = forms.CharField(label="Nachricht", widget=forms.Textarea(attrs={"rows": 8}))


class SignForm(StyledForm):
    signer_name = forms.CharField(label="Name der unterzeichnenden Person", max_length=120)
    signature = forms.CharField(widget=forms.HiddenInput(), required=False)
    consent = forms.BooleanField(label="Ich habe das Dokument gelesen und bin mit dem Inhalt einverstanden.", required=True)


class UploadSignedForm(StyledForm):
    signer_name = forms.CharField(label="Unterschrieben von", max_length=120)
    file = forms.FileField(label="Unterschriebenes Dokument (PDF, JPG oder PNG)", widget=forms.ClearableFileInput(attrs={"accept": "application/pdf,image/jpeg,image/png"}))


class PhotoForm(StyledForm):
    caption = forms.CharField(label="Beschreibung", max_length=200, required=False)
