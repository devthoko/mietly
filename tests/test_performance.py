"""Schnelle Berechnungen müssen dieselben Ergebnisse liefern wie die ausführlichen."""

from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.billing import services as billing
from apps.documents import services as docs
from apps.orders import availability, services, workflow
from apps.orders.models import Order
from tests.conftest import make_order
from tests.test_workflow import sign, to_paid_invoice


def test_with_money_matches_workflow(order, admin, sig, customer, articles):
    to_paid_invoice(order, admin, sig)
    services.cancel_order(order, reason="abgesagt", fee=Decimal("30"), user=admin)
    other = make_order(admin, customer)
    services.add_article(other, articles["vase"], 2, admin)
    for o in workflow.with_money(Order.objects.filter(pk__in=[order.pk, other.pk])):
        balance, held = workflow.money_of(o)
        assert balance == workflow.open_balance(o)
        assert held == workflow.deposit_state(o).held


def test_dashboard_query_count_does_not_grow_with_orders(client, admin, customer, articles, company):
    client.force_login(admin)
    for _ in range(3):
        o = make_order(admin, customer)
        services.add_article(o, articles["vase"], 1, admin)
    client.get("/")
    with CaptureQueriesContext(connection) as few:
        client.get("/")
    for _ in range(10):
        o = make_order(admin, customer)
        services.add_article(o, articles["vase"], 1, admin)
    with CaptureQueriesContext(connection) as many:
        client.get("/")
    assert len(many) <= len(few) + 2


def test_dashboard_lists_signature_and_payment(client, order, admin, sig):
    offer = docs.create_offer(order, admin)
    client.force_login(admin)
    html = client.get("/").content.decode()
    assert "Angebot wartet auf Unterschrift" in html and offer.number in html
    sign(offer, admin, sig)
    contract = docs.create_contract(order, admin)
    sign(contract, admin, sig)
    billing.issue_invoice(order, admin)
    html = client.get("/").content.decode()
    assert "Zahlung offen" in html


def test_invoice_list_paid_state(client, order, admin, sig):
    inv = to_paid_invoice(order, admin, sig)
    client.force_login(admin)
    assert inv.number not in client.get("/rechnungen/?status=offen").content.decode()
    assert inv.number in client.get("/rechnungen/").content.decode()


def test_available_map_matches_single_calculation(order, admin, customer, articles):
    other = make_order(admin, customer)
    free = availability.available_map([a.pk for a in articles.values()], other)
    for a in articles.values():
        assert free[a.pk] == availability.available_quantity(a, other)


def test_order_page_query_count_bounded(client, order, admin):
    client.force_login(admin)
    with CaptureQueriesContext(connection) as q:
        assert client.get(order.get_absolute_url() + "?schritt=offer").status_code == 200
    assert len(q) <= 40


def test_session_is_not_written_on_every_request(client, admin):
    client.force_login(admin)
    client.get("/")
    with CaptureQueriesContext(connection) as q:
        client.get("/kunden/")
    assert not any(x["sql"].startswith('UPDATE "django_session"') for x in q.captured_queries)


def test_speculation_rules(client, admin):
    client.force_login(admin)
    r = client.get("/")
    assert r["Speculation-Rules"] == '"/speculation-rules.json"'
    assert "no-store" not in r["Cache-Control"]
    rules = client.get("/speculation-rules.json")
    assert rules["Content-Type"] == "application/speculationrules+json"
    assert "/abmelden*" in rules.content.decode()


def test_company_settings_cached_per_request_but_fresh_after_save(company):
    from apps.core.models import CompanySettings, _settings_cache

    token = _settings_cache.set({})
    try:
        a = CompanySettings.get()
        with CaptureQueriesContext(connection) as q:
            CompanySettings.get()
        assert len(q) == 0
        a.name = "Neu"
        a.save()
        assert CompanySettings.get().name == "Neu"
    finally:
        _settings_cache.reset(token)
