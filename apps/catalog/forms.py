from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory

from apps.core.forms import StyledForm, StyledModelForm, check_amounts, validate_upload_size
from apps.core.images import process_image

from .models import Article, Category, Package, PackageItem, StockMovement


class ArticleForm(StyledModelForm):
    initial_stock = forms.IntegerField(label="Anfangsbestand", min_value=0, initial=1, help_text="Anzahl der vorhandenen Exemplare")

    class Meta:
        model = Article
        fields = [
            "name", "category", "description", "image", "storage_location",
            "price", "extra_day_price", "replacement_value", "deposit_per_unit", "vat_rate", "active",
        ]
        widgets = {"image": forms.ClearableFileInput(attrs={"accept": "image/*"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields["initial_stock"]
        self.fields["category"].empty_label = "— ohne Kategorie —"
        self.fields["description"].widget.attrs["rows"] = 3

    def clean(self):
        return check_amounts(self, super().clean(),
                             money_fields=["price", "extra_day_price", "replacement_value", "deposit_per_unit"],
                             vat_fields=["vat_rate"])

    def clean_image(self):
        img = self.cleaned_data.get("image")
        if img and hasattr(img, "content_type"):
            validate_upload_size(img)
            return process_image(img)
        return img


class CategoryForm(StyledModelForm):
    class Meta:
        model = Category
        fields = ["name", "sort"]


class StockMovementForm(StyledModelForm):
    direction = forms.ChoiceField(label="Art", choices=[("in", "Zugang (+)"), ("out", "Abgang (−)")], initial="in")
    amount = forms.IntegerField(label="Menge", min_value=1)

    class Meta:
        model = StockMovement
        fields = ["reason", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].choices = [c for c in StockMovement.Reason.choices if c[0] != "initial"]

    def clean(self):
        data = super().clean()
        reason = data.get("reason")
        direction = data.get("direction")
        if reason == "purchase" and direction == "out":
            self.add_error("direction", "Ein Neukauf ist immer ein Zugang.")
        if reason in ("loss", "damage") and direction == "in":
            self.add_error("direction", "Verlust und Ausmusterung sind immer Abgänge.")
        return data


class PackageForm(StyledModelForm):
    class Meta:
        model = Package
        fields = ["name", "description", "price", "vat_rate", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].widget.attrs["rows"] = 3

    def clean(self):
        return check_amounts(self, super().clean(), money_fields=["price"], vat_fields=["vat_rate"])


class PackageItemForm(StyledModelForm):
    class Meta:
        model = PackageItem
        fields = ["article", "quantity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Aktive Artikel – plus der bereits gewählte, falls er inzwischen deaktiviert wurde
        qs = Article.objects.filter(active=True)
        if self.instance.pk and self.instance.article_id:
            qs = Article.objects.filter(Q(active=True) | Q(pk=self.instance.article_id))
        self.fields["article"].queryset = qs.order_by("name")
        self.fields["article"].empty_label = "— Artikel wählen —"
        self.fields["quantity"].widget.attrs["class"] += " qty-input"
        self.fields["quantity"].widget.attrs["min"] = 1


PackageItemFormSet = inlineformset_factory(
    Package, PackageItem, form=PackageItemForm, extra=3, can_delete=True, min_num=1, validate_min=True,
)


class ArticleFilterForm(StyledForm):
    q = forms.CharField(required=False)
    kategorie = forms.ModelChoiceField(queryset=Category.objects.all(), required=False, empty_label="Alle Kategorien")
