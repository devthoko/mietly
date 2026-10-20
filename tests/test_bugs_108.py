"""Fehler aus der Prüfung für 1.0.8."""

from decimal import Decimal

import pytest

from apps.core.models import CompanySettings, EmailLog
from apps.documents import services as docs
from apps.documents.models import Document
from apps.orders.models import OrderItem
from tests.conftest import make_order
from tests.test_workflow import sign


# --------------------------------------------------------------------------
# Absturz bei mehrzeiligen Texten (Paket, Artikel, Kunde, Protokolle)
# --------------------------------------------------------------------------

def test_package_and_customer_pages_with_text(client, admin, customer, articles):
    from apps.catalog.models import Package

    p = Package.objects.create(name="Tischdeko", price=Decimal("20"), description="Zeile 1\nZeile <2>")
    customer.notes = "Achtung\r\nHund im Garten"
    customer.save()
    articles["vase"].description = "Mundgeblasen\nca. 40 cm"
    articles["vase"].save()
    client.force_login(admin)
    r = client.get(p.get_absolute_url())
    assert r.status_code == 200 and "Zeile 1<br>Zeile &lt;2&gt;" in r.content.decode()
    assert client.get(customer.get_absolute_url()).status_code == 200
    assert client.get(articles["vase"].get_absolute_url()).status_code == 200


# --------------------------------------------------------------------------
# Belegnummern: keine Doppelvergabe mit Nummern aus der alten Zählweise
# --------------------------------------------------------------------------

def test_contract_number_does_not_collide_with_legacy_number(order, admin, customer, articles, sig):
    from apps.orders import services

    other = make_order(admin, customer)
    services.add_article(other, articles["vase"], 1, admin)
    suffix = order.number.split("-", 1)[1]
    # Altbestand: ein anderer Auftrag trägt bereits die Vertragsnummer, die dieser Auftrag erhalten würde
    legacy = docs.create_offer(other, admin)
    Document.objects.filter(pk=legacy.pk).update(kind="contract", number=f"MV-{suffix}")
    offer = docs.create_offer(order, admin)
    sign(offer, admin, sig)
    contract = docs.create_contract(order, admin)
    assert contract.number != f"MV-{suffix}"
    assert not Document.objects.filter(kind="contract", number=contract.number).exclude(order=order).exists()


# --------------------------------------------------------------------------
# Unsinnige Eingaben dürfen keinen Serverfehler auslösen
# --------------------------------------------------------------------------

@pytest.mark.parametrize("field,value", [("quantity", "99999999999"), ("unit_price", "123456789012"), ("unit_price", "NaN"), ("discount_percent", "Infinity")])
def test_item_update_rejects_out_of_range(client, order, admin, field, value):
    item = order.items.first()
    client.force_login(admin)
    data = {"quantity": item.quantity, "unit_price": str(item.unit_price), "discount_percent": "0", field: value}
    r = client.post(f"/auftraege/{order.pk}/positionen/{item.pk}/", data, HTTP_HX_REQUEST="true")
    assert r.status_code == 200
    item.refresh_from_db()
    assert item.quantity < 100000 and item.unit_price < Decimal("100000000")


def test_item_add_rejects_huge_quantity(client, order, admin, articles):
    client.force_login(admin)
    r = client.post(f"/auftraege/{order.pk}/positionen/neu/", {"article": articles["vase"].pk, "quantity": "99999999999"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200
    assert "Menge" in r.content.decode()


def test_custom_item_rejects_huge_quantity(client, order, admin):
    client.force_login(admin)
    r = client.post(f"/auftraege/{order.pk}/positionen/individuell/",
                    {"description": "Aufbau", "quantity": "99999999999", "unit_price": "10"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200
    assert not order.items.filter(kind=OrderItem.Kind.CUSTOM).exists()


# --------------------------------------------------------------------------
# Drucken und E-Mail
# --------------------------------------------------------------------------

def test_print_rejects_protocol_relative_redirect(client, order, admin, monkeypatch):
    from apps.core import printing

    offer = docs.create_offer(order, admin)
    c = CompanySettings.get()
    c.printer_ready = True
    c.save()
    monkeypatch.setattr(printing, "print_file", lambda *a, **k: "mietly-1")
    client.force_login(admin)
    r = client.post(f"/dokumente/{offer.pk}/drucken/", {"next": "//evil.example/x"})
    assert r.status_code == 302 and r.url.startswith("/auftraege/")


def test_print_button_in_htmx_partial_has_no_post_only_return_url(client, order, admin):
    docs.create_offer(order, admin)
    c = CompanySettings.get()
    c.printer_ready = True
    c.save()
    item = order.items.first()
    client.force_login(admin)
    r = client.post(f"/auftraege/{order.pk}/positionen/{item.pk}/",
                    {"quantity": item.quantity, "unit_price": str(item.unit_price), "discount_percent": "0"}, HTTP_HX_REQUEST="true")
    assert "/positionen/" not in r.content.decode().split('name="next"', 1)[-1].split(">", 1)[0]


def test_sent_mail_cannot_be_requeued(client, order, admin):
    log = EmailLog.objects.create(order=order, to="a@example.de", subject="x", body="y", status=EmailLog.Status.SENT)
    client.force_login(admin)
    client.post(f"/dokumente/email/{log.pk}/erneut/")
    log.refresh_from_db()
    assert log.status == EmailLog.Status.SENT


@pytest.mark.parametrize("value", ["abc", "0", "javascript:alert(1)"])
def test_print_with_odd_return_value(client, order, admin, value):
    offer = docs.create_offer(order, admin)
    client.force_login(admin)
    r = client.post(f"/dokumente/{offer.pk}/drucken/", {"next": value})
    assert r.status_code == 302 and r.url.startswith("/auftraege/")


@pytest.mark.parametrize("value", ["", "abc", "1e30", "<script>"])
def test_invalid_ids_give_404_not_500(client, order, admin, value):
    client.force_login(admin)
    assert client.post(f"/auftraege/{order.pk}/kunde/", {"customer": value}).status_code == 404
    assert client.post(f"/auftraege/{order.pk}/positionen/neu/", {"article": value or "x"}).status_code == 404
