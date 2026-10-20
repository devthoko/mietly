from apps.core.forms import StyledModelForm

from .models import Customer


class CustomerForm(StyledModelForm):
    class Meta:
        model = Customer
        fields = ["salutation", "first_name", "last_name", "email", "phone", "street", "zip_code", "city", "notes"]
        widgets = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs["autocomplete"] = "off"
        self.fields["notes"].widget.attrs["rows"] = 3

    def clean(self):
        data = super().clean()
        if not data.get("email") and not data.get("phone"):
            self.add_error("email", "Bitte mindestens E-Mail-Adresse oder Telefonnummer angeben.")
        return data
