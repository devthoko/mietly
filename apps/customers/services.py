"""Datenschutzfunktionen: Auskunft (Art. 15 DSGVO) und Anonymisierung (Art. 17 DSGVO).

Rechnungen und Buchungsbelege sind 8 Jahre, Geschäftsbriefe (Angebote,
Verträge) 6 Jahre aufzubewahren (§ 147 AO, § 257 HGB). Solange solche
Fristen laufen, wird ein Kunde nicht gelöscht; danach kann er anonymisiert
werden. Die Dokumente selbst bleiben bis zum Fristablauf unverändert.
"""

from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.core import audit

RETENTION_YEARS_INVOICES = 8
RETENTION_YEARS_LETTERS = 6


class PrivacyError(Exception):
    pass


def retention_until(customer):
    """Ende der Aufbewahrungsfrist (31.12. des letzten Jahres) oder None."""
    from apps.billing.models import Invoice
    from apps.documents.models import Document

    ends = []
    last_invoice = Invoice.objects.filter(order__customer=customer).order_by("-issue_date").first()
    if last_invoice:
        ends.append(date(last_invoice.issue_date.year + RETENTION_YEARS_INVOICES, 12, 31))
    last_doc = Document.objects.filter(order__customer=customer, kind__in=["offer", "contract"]).order_by("-created_at").first()
    if last_doc:
        ends.append(date(timezone.localtime(last_doc.created_at).year + RETENTION_YEARS_LETTERS, 12, 31))
    return max(ends) if ends else None


def can_delete(customer):
    return not customer.orders.exists()


def export_data(customer):
    """Alle zu einem Kunden gespeicherten Daten als strukturierte Auskunft."""
    orders = []
    for o in customer.orders.all().prefetch_related("items", "documents", "payments"):
        orders.append({
            "auftrag": o.number,
            "veranstaltung": o.event_name,
            "datum": o.event_date.isoformat() if o.event_date else None,
            "ort": o.event_location,
            "lieferadresse": o.delivery_address,
            "status": o.get_status_display(),
            "positionen": [{"bezeichnung": i.description, "menge": i.quantity, "preis": str(i.unit_price)} for i in o.items.all()],
            "dokumente": [{"art": d.get_kind_display(), "nummer": d.number, "erstellt": d.created_at.isoformat(), "unterschrieben_von": d.signer_name} for d in o.documents.all()],
            "zahlungen": [{"betrag": str(p.amount), "datum": p.paid_on.isoformat(), "art": p.get_method_display()} for p in o.payments.all()],
        })
    until = retention_until(customer)
    return {
        "erstellt": timezone.now().isoformat(),
        "kunde": {
            "kundennummer": customer.number,
            "anrede": customer.salutation,
            "vorname": customer.first_name,
            "nachname": customer.last_name,
            "email": customer.email,
            "telefon": customer.phone,
            "strasse": customer.street,
            "plz": customer.zip_code,
            "ort": customer.city,
            "notizen": customer.notes,
            "angelegt": customer.created_at.isoformat(),
        },
        "auftraege": orders,
        "aufbewahrung_bis": until.isoformat() if until else None,
    }


@transaction.atomic
def anonymize(customer, user):
    until = retention_until(customer)
    if until and until >= timezone.localdate():
        raise PrivacyError(f"Gesetzliche Aufbewahrungsfristen laufen noch bis {until:%d.%m.%Y}. Eine Anonymisierung ist erst danach möglich.")
    if customer.orders.filter(status="active").exists():
        raise PrivacyError("Der Kunde hat noch laufende Aufträge.")
    number = customer.number
    customer.salutation = ""
    customer.first_name = "Anonymisiert"
    customer.last_name = number
    customer.email = ""
    customer.phone = ""
    customer.street = ""
    customer.zip_code = ""
    customer.city = ""
    customer.notes = ""
    customer.anonymized_at = timezone.now()
    customer.save()
    customer.orders.update(delivery_address="", notes="", customer_note="", event_location="")
    audit.log(user, "privacy", f"Kunde {number} anonymisiert", obj=customer)
