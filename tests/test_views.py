"""Alle Seiten rendern fehlerfrei; Anmeldung und Rechte funktionieren."""

import pytest
from django.utils import timezone

from apps.billing import services as billing
from apps.documents import services as docs
from apps.orders import services
from tests.test_workflow import sign, to_paid_invoice


def test_login_required(client, db):
    r = client.get("/")
    assert r.status_code == 302 and "/anmelden/" in r["Location"]


def test_login_and_lockout(client, admin, settings):
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        client.post("/anmelden/", {"username": "admin", "password": "falsch"})
    r = client.post("/anmelden/", {"username": "admin", "password": "Sicheres-Test-Passwort-1"})
    assert "Zu viele Fehlversuche" in r.content.decode()


def test_login_success(client, admin):
    r = client.post("/anmelden/", {"username": "admin", "password": "Sicheres-Test-Passwort-1"})
    assert r.status_code == 302


def test_staff_cannot_open_admin_pages(client, staff):
    client.force_login(staff)
    for url in ["/einstellungen/benutzer/", "/einstellungen/email/", "/einstellungen/backups/", "/einstellungen/protokoll/"]:
        assert client.get(url).status_code == 403, url


def test_staff_cannot_change_settings(client, staff, company):
    client.force_login(staff)
    client.post("/einstellungen/", {"name": "Gehackt"})
    company.refresh_from_db()
    assert company.name != "Gehackt"


PAGES = [
    "/", "/kalender/", "/suche/", "/suche/?q=anna", "/profil/", "/kunden/", "/kunden/neu/", "/artikel/", "/artikel/neu/",
    "/pakete/", "/pakete/neu/", "/auftraege/", "/auftraege/?status=alle", "/auftraege/neu/", "/rechnungen/",
    "/rechnungen/zahlungen/", "/dokumente/", "/einstellungen/", "/einstellungen/steuer-bank/", "/einstellungen/regeln/",
    "/einstellungen/email/", "/einstellungen/webdav/", "/einstellungen/vorlagen/", "/einstellungen/vorlagen/contract/",
    "/einstellungen/vorlagen/mail_offer/", "/einstellungen/benutzer/", "/einstellungen/benutzer/neu/",
    "/einstellungen/protokoll/", "/einstellungen/backups/", "/einstellungen/info/",
]


@pytest.mark.parametrize("url", PAGES)
def test_pages_render(client, admin, order, url):
    client.force_login(admin)
    r = client.get(url)
    assert r.status_code == 200, url


def test_order_steps_render_through_workflow(client, admin, order, sig):
    client.force_login(admin)
    steps = ["customer", "event", "offer", "contract", "invoice", "packing", "handover", "return", "close"]

    def check():
        for s in steps:
            r = client.get(f"/auftraege/{order.pk}/?schritt={s}")
            assert r.status_code == 200, s

    check()
    to_paid_invoice(order, admin, sig)
    check()
    services.start_handover(order, admin)
    check()
    sign(services.create_handover_protocol(order, admin), admin, sig)
    services.complete_handover(order, admin)
    services.start_return(order, admin)
    check()
    services.complete_return(order, admin)
    check()
    services.settle(order, decisions={}, refund_method="transfer", user=admin)
    services.close_order(order, admin)
    check()
    for d in order.documents.all():
        assert client.get(f"/dokumente/{d.pk}/").status_code == 200
        assert client.get(f"/dokumente/{d.pk}/email/").status_code in (200, 302)
    for p in ["/", "/kalender/", "/rechnungen/", "/rechnungen/?export=csv", "/dokumente/", f"/kunden/{order.customer.pk}/",
              f"/artikel/{order.items.first().article.pk}/", f"/kunden/{order.customer.pk}/datenauskunft/"]:
        assert client.get(p).status_code == 200, p


def test_create_order_via_ui(client, admin, customer, company, articles):
    client.force_login(admin)
    r = client.post("/auftraege/neu/", {"kunde": customer.pk})
    assert r.status_code == 302
    from apps.orders.models import Order

    from datetime import timedelta

    order = Order.objects.latest("id")
    start = (timezone.localtime() + timedelta(days=5)).replace(hour=10, minute=0)
    end = start + timedelta(days=2)
    r = client.post(f"/auftraege/{order.pk}/event/", {
        "event_name": "Gartenfest", "event_date": (start + timedelta(days=1)).date().isoformat(), "event_location": "Garten",
        "fulfillment": "pickup", "delivery_address": "", "handover_at": start.strftime("%Y-%m-%dT%H:%M"),
        "return_at": end.strftime("%Y-%m-%dT%H:%M"), "customer_note": "", "notes": "",
    })
    assert r.status_code == 302 and "schritt=offer" in r["Location"]
    r = client.post(f"/auftraege/{order.pk}/positionen/neu/", {"article": articles["vase"].pk, "quantity": 4}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and "Glasvase" in r.content.decode()
    r = client.get(f"/auftraege/{order.pk}/positionen/suche/?q=vase")
    assert "verfügbar" in r.content.decode()
    client.post(f"/auftraege/{order.pk}/angebot/")
    assert order.documents.filter(kind="offer").exists()
    offer = order.documents.get(kind="offer")
    assert client.get(f"/dokumente/{offer.pk}/unterschreiben/").status_code == 200


def test_blocked_action_shows_message(client, admin, order):
    client.force_login(admin)
    r = client.post(f"/auftraege/{order.pk}/vertrag/", follow=True)
    assert "Angebot unterschrieben" in r.content.decode()


def test_template_versioning(client, admin, company):
    from apps.core.models import TextTemplate

    client.force_login(admin)
    v1 = TextTemplate.current("contract")
    client.post("/einstellungen/vorlagen/contract/", {"body": v1.body + "\n\n## § 11 Zusatz\nNeu."})
    assert TextTemplate.current("contract").version == v1.version + 1
    r = client.post("/einstellungen/vorlagen/contract/", {"body": "{{unbekannt.feld}}"})
    assert "Unbekannte Platzhalter" in r.content.decode()


def test_text_render_escapes_html():
    from apps.core.textrender import render_html

    html = render_html("## Titel\n**fett** <script>x</script> {{kunde.name}}", {"kunde.name": "<b>A</b>"})
    assert "<script>" not in html and "&lt;b&gt;" in html and "<strong>fett</strong>" in html


def test_backup_and_list(admin, order, settings):
    import shutil

    from apps.core import backup

    if not shutil.which("pg_dump"):
        pytest.skip("pg_dump nicht verfügbar")
    path = backup.create_backup("test")
    assert path.exists() and path.with_name(path.name + ".sha256").exists()
    assert backup.list_backups()[0]["reason"] == "test"


def test_offer_pdf_has_content(order, admin):
    doc = docs.create_offer(order, admin)
    data = doc.file.read()
    assert data.startswith(b"%PDF-") and len(data) > 5000


def test_customer_with_invoice_cannot_be_anonymized(order, admin, sig):
    from apps.customers import services as cs

    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)
    billing.issue_invoice(order, admin)
    with pytest.raises(cs.PrivacyError):
        cs.anonymize(order.customer, admin)


def test_numbers_not_localized_with_separators(client, admin, company):
    """Jahreszahlen und IDs dürfen nicht als „2.026“ ausgegeben werden (Links, Formularwerte)."""
    client.force_login(admin)
    html = client.get("/kalender/?jahr=2026&monat=10").content.decode()
    assert "jahr=2026" in html and "2.026" not in html


def test_mobile_navigation_present(client, admin, company):
    client.force_login(admin)
    html = client.get("/").content.decode()
    assert 'class="bottom-nav"' in html and "viewport-fit=cover" in html
