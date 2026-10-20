"""Oberfläche: Kurzstatus in Listen, Kennzahlen in der Auftragsakte."""

import importlib
from datetime import timedelta

from django.utils import timezone

from apps.documents import services as docs
from apps.orders.models import Order
from tests.test_workflow import sign, to_paid_invoice


def test_list_shows_waiting_for_signature(client, order, admin):
    docs.create_offer(order, admin)
    order.refresh_from_db()
    assert (order.next_action, order.next_tone) == ("Wartet auf Unterschrift", "warning")
    client.force_login(admin)
    html = client.get("/auftraege/").content.decode()
    assert "Wartet auf Unterschrift" in html and "tone-warning" in html


def test_list_status_follows_workflow(order, admin, sig):
    offer = docs.create_offer(order, admin)
    sign(offer, admin, sig)
    contract = docs.create_contract(order, admin)
    sign(contract, admin, sig)
    from apps.billing import services as billing

    billing.issue_invoice(order, admin)
    order.refresh_from_db()
    assert order.next_action == "Wartet auf Zahlung"


def test_list_status_ready_for_handover(order, admin, sig):
    to_paid_invoice(order, admin, sig)
    order.refresh_from_db()
    assert order.next_action in ("Packliste erstellen", "Bereit zur Übergabe")


def test_return_overdue_flag(order):
    order.stage = 8
    order.return_at = timezone.now() - timedelta(days=1)
    assert order.return_overdue


def test_backfill_migration(order):
    Order.objects.filter(pk=order.pk).update(next_action="", next_tone="")
    mig = importlib.import_module("apps.orders.migrations.0004_v106_backfill_list_status")
    mig.backfill(None, None)
    order.refresh_from_db()
    assert order.next_action == "Angebot erstellen"


def test_quick_facts_on_order_page(client, order, admin):
    client.force_login(admin)
    html = client.get(order.get_absolute_url()).content.decode()
    assert 'class="quick-facts"' in html and "Summe" in html


def test_skip_link_present(client, admin):
    client.force_login(admin)
    html = client.get("/").content.decode()
    assert 'href="#inhalt"' in html and 'id="inhalt"' in html


def test_design_choice_in_profile(client, admin):
    client.force_login(admin)
    html = client.get("/").content.decode()
    assert 'class="ui-warm"' in html and "klar.css" not in html
    r = client.post("/profil/", {"p-first_name": "Ada", "p-last_name": "L", "p-email": "ada@example.de", "p-ui_theme": "klar", "save_profile": "1"})
    assert r.status_code == 302
    admin.refresh_from_db()
    assert admin.ui_theme == "klar"
    html = client.get("/").content.decode()
    assert 'class="ui-klar"' in html and "css/klar.css" in html


def test_design_choice_rejects_unknown_value(client, admin):
    client.force_login(admin)
    client.post("/profil/", {"p-first_name": "Ada", "p-last_name": "L", "p-email": "", "p-ui_theme": "neon", "save_profile": "1"})
    admin.refresh_from_db()
    assert admin.ui_theme == "warm"
