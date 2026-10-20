"""Korrekturen aus dem Anwendertest (Version 1.0.4)."""

from decimal import Decimal

import pytest
from django.core import mail as djmail
from django.utils import timezone

from apps.core.models import CompanySettings, EmailLog, TextTemplate
from apps.core.textrender import render_placeholders
from apps.documents import services as docs
from apps.documents.context import greeting, mail_context, mail_template_key
from apps.orders import services, workflow
from apps.orders.models import Order, OrderItem
from apps.orders.workflow import WorkflowError
from tests.conftest import make_order
from tests.test_workflow import sign, to_paid_invoice


def _mail(doc):
    key = mail_template_key(doc)
    tpl = TextTemplate.current(key)
    ctx = mail_context(doc)
    return key, render_placeholders(tpl.subject, ctx), render_placeholders(tpl.body, ctx)


def _cancel_with_fee(order, admin, sig, fee="40.00"):
    to_paid_invoice(order, admin, sig)
    services.cancel_order(order, reason="Feier abgesagt", fee=Decimal(fee), user=admin)
    order.refresh_from_db()
    storno = order.invoices.get(kind="cancellation")
    fee_inv = order.invoices.get(kind="fee")
    return storno, fee_inv


# --------------------------------------------------------------------------
# A – Texte, Mails und PDFs
# --------------------------------------------------------------------------

def test_cancellation_and_fee_have_own_texts(order, admin, sig):
    storno, fee_inv = _cancel_with_fee(order, admin, sig)
    key, subject, body = _mail(storno.document)
    assert key == "mail_cancellation"
    assert subject.startswith("Stornorechnung SR-")
    assert "Übergabe" not in body and "Bitte zahlen" not in body
    assert storno.cancels.number in body

    key, subject, body = _mail(fee_inv.document)
    assert key == "mail_fee"
    assert subject.startswith("Stornogebühr ")
    assert "Übergabe" not in body
    # Kunde hat bereits bezahlt: Gebühr wird verrechnet, Rest erstattet
    assert "verrechnet" in body and "erstatten" in body


def test_followup_invoice_pdf_text_without_handover_sentence(order, admin, sig):
    _, fee_inv = _cancel_with_fee(order, admin, sig)
    data = fee_inv.document.data
    assert data["title"] == "Stornogebühr"
    assert "Übergabe" not in data["outro"]
    assert data["period_label"] == "Leistungsdatum"
    assert fee_inv.service_period == timezone.localdate().strftime("%d.%m.%Y")


def test_document_labels_and_ascii_filenames(order, admin, sig):
    storno, fee_inv = _cancel_with_fee(order, admin, sig)
    assert storno.document.display_name.startswith("Stornorechnung ")
    assert fee_inv.document.display_name.startswith("Stornogebühr ")
    assert fee_inv.document.filename.startswith("Stornogebuehr_")
    for doc in order.documents.all():
        assert doc.filename.isascii() and doc.final_filename.isascii()


def test_pdf_minus_sign_replaced(monkeypatch):
    from apps.documents import pdf

    captured = {}

    class FakeHTML:
        def __init__(self, string, **kwargs):
            captured["html"] = string

        def write_pdf(self):
            return b"%PDF-"

    monkeypatch.setattr(pdf, "HTML", FakeHTML)
    monkeypatch.setattr(pdf, "render_to_string", lambda *a, **k: "Betrag −107,00 €")
    pdf.render_pdf("invoice", {})
    assert "−" not in captured["html"] and "–107,00" in captured["html"]


def test_greeting_formal_and_informal(company, customer):
    customer.salutation = "Frau"
    assert greeting(customer, company) == "Sehr geehrte Frau Beispiel"
    customer.salutation = ""
    assert greeting(customer, company) == "Guten Tag Anna Beispiel"
    company.mail_greeting = "informal"
    assert greeting(customer, company) == "Hallo Anna"


def test_signature_contains_tel(order, admin):
    company = CompanySettings.get()
    company.phone = "0351 123456"
    company.save()
    offer = docs.create_offer(order, admin)
    _, _, body = _mail(offer)
    assert "Tel. 0351 123456" in body
    assert body.startswith("Guten Tag Anna Beispiel,")


def test_signed_offer_mail_does_not_ask_for_signature(order, admin, sig):
    offer = docs.create_offer(order, admin)
    sign(offer, admin, sig)
    offer.refresh_from_db()
    key, _, body = _mail(offer)
    assert key == "mail_offer_signed"
    assert "unterschrieben zurück" not in body


def _through_return(order, admin, sig, missing=1):
    to_paid_invoice(order, admin, sig)
    services.start_handover(order, admin)
    doc = services.create_handover_protocol(order, admin)
    sign(doc, admin, sig)
    services.complete_handover(order, admin)
    services.start_return(order, admin)
    r = order.return_record
    items = {}
    for item in r.items.all():
        items[item.pk] = {"returned_qty": item.expected_qty - (missing if item.article.name == "Traubogen Holz" else 0),
                          "damaged_qty": 0, "condition": "good", "note": ""}
    services.save_return(order, {"performed_at": timezone.now(), "returned_by_name": "Anna", "notes": "", "items": items}, admin)
    services.complete_return(order, admin)
    return order


def test_return_and_deposit_mails_mention_damages_and_followup(order, admin, sig):
    _through_return(order, admin, sig)
    return_doc = workflow.current_document(order, "return")
    _, _, body = _mail(return_doc)
    assert "Traubogen Holz" in body and "fehlt" in body

    # Fehlender Traubogen (450 €) übersteigt die Kaution (150 €) → Nachberechnung
    decisions = {d.pk: "deposit" for d in order.damages.all()}
    services.settle(order, decisions=decisions, refund_method="transfer", user=admin)
    followup = order.invoices.get(kind="additional")
    deposit_doc = workflow.current_document(order, "deposit")
    _, _, body = _mail(deposit_doc)
    assert followup.number in body and "einbehalten" in body
    assert deposit_doc.data["followups"][0]["number"] == followup.number
    assert deposit_doc.data["open_balance"]
    # Nachberechnung: eigene Bezeichnung und Mail
    key, subject, _ = _mail(followup.document)
    assert key == "mail_additional" and subject.startswith("Nachberechnung")


def test_template_upgrade_migration_only_touches_unchanged_defaults(db):
    import importlib

    from django.apps import apps as django_apps

    mig = importlib.import_module("apps.core.migrations.0004_v104_template_texts")
    TextTemplate.objects.create(key="mail_offer", version=1, subject=mig.OLD["mail_offer"][0], body=mig.OLD["mail_offer"][1])
    TextTemplate.objects.create(key="mail_invoice", version=1, subject="Eigener Betreff", body="Hallo {{kunde.anrede}}, eigener Text")
    mig.upgrade(django_apps, None)
    assert TextTemplate.current("mail_offer").version == 2
    assert TextTemplate.current("mail_offer").body.startswith("{{kunde.briefanrede}},")
    assert TextTemplate.current("mail_invoice").version == 1


def test_new_default_templates_match_migration():
    import importlib

    from apps.core.defaults import DEFAULT_TEMPLATES

    mig = importlib.import_module("apps.core.migrations.0004_v104_template_texts")
    for key, value in mig.NEW.items():
        assert DEFAULT_TEMPLATES[key] == value


# --------------------------------------------------------------------------
# B – Ablauf und Logik
# --------------------------------------------------------------------------

def test_dashboard_lists_refund_for_cancelled_order(client, order, admin, sig):
    to_paid_invoice(order, admin, sig)
    services.cancel_order(order, reason="abgesagt", fee=Decimal("0"), user=admin)
    client.force_login(admin)
    r = client.get("/")
    assert "Erstattung fällig" in r.content.decode()


def test_close_action_names_open_payment(order, admin, sig):
    _through_return(order, admin, sig)
    services.settle(order, decisions={d.pk: "deposit" for d in order.damages.all()}, refund_method="transfer", user=admin)
    title, hint = workflow.close_action(order)
    assert title == "Zahlung abwarten"
    assert "Nachberechnung" in hint


def test_invoice_data_warning_on_offer_step(client, order, admin):
    company = CompanySettings.get()
    company.tax_number = ""
    company.save()
    client.force_login(admin)
    r = client.get(f"/auftraege/{order.pk}/?schritt=offer")
    assert "Für die spätere Rechnung fehlen noch Angaben" in r.content.decode()


def test_empty_draft_can_be_deleted(client, admin, customer, company):
    order = services.create_order(admin, customer)
    client.force_login(admin)
    page = client.get(order.get_absolute_url()).content.decode()
    assert "Entwurf löschen" in page and "Kopieren" not in page and "Stornieren" not in page
    r = client.post(f"/auftraege/{order.pk}/loeschen/")
    assert r.status_code == 302
    assert not Order.objects.filter(pk=order.pk).exists()


def test_order_with_documents_cannot_be_deleted(order, admin):
    docs.create_offer(order, admin)
    with pytest.raises(WorkflowError):
        services.delete_draft(order, admin)


def test_delivery_fee_added_and_removed(order, admin):
    from apps.orders.forms import EventForm

    company = CompanySettings.get()
    company.delivery_fee = Decimal("35.00")
    company.save()

    def save(fulfillment):
        data = {
            "event_name": order.event_name, "event_date": order.event_date.isoformat(), "event_location": order.event_location,
            "fulfillment": fulfillment, "delivery_address": "Gut Sonnenhof, 12345 Musterstadt",
            "handover_at": timezone.localtime(order.handover_at).strftime("%Y-%m-%dT%H:%M"),
            "return_at": timezone.localtime(order.return_at).strftime("%Y-%m-%dT%H:%M"),
        }
        form = EventForm(data, instance=order)
        assert form.is_valid(), form.errors
        services.save_event(order, form, admin)

    save("delivery")
    item = order.items.get(kind=OrderItem.Kind.DELIVERY)
    assert item.unit_price == Decimal("35.00")
    save("pickup")
    assert not order.items.filter(kind=OrderItem.Kind.DELIVERY).exists()


def test_event_form_error_redirects_to_get(client, order, admin):
    client.force_login(admin)
    r = client.post(f"/auftraege/{order.pk}/event/", {"event_name": "", "fulfillment": "pickup"})
    assert r.status_code == 302 and r.url.endswith("?schritt=event")
    page = client.get(r.url).content.decode()
    assert "Bitte die markierten Angaben prüfen" in page


def test_item_change_updates_next_step_out_of_band(client, admin, customer, company, articles):
    order = make_order(admin, customer)
    client.force_login(admin)
    r = client.post(f"/auftraege/{order.pk}/positionen/neu/", {"article": articles["vase"].pk, "quantity": 2}, HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert 'id="next-card" hx-swap-oob="true"' in html
    assert "Angebot erstellen" in html
    assert 'id="stepper"' in html


def test_next_card_offers_sign_and_mail(client, order, admin):
    offer = docs.create_offer(order, admin)
    client.force_login(admin)
    html = client.get(order.get_absolute_url()).content.decode()
    assert f"/dokumente/{offer.pk}/unterschreiben/" in html
    assert f"/dokumente/{offer.pk}/email/" in html


def test_create_offer_redirects_to_offer_card(client, order, admin):
    client.force_login(admin)
    r = client.post(f"/auftraege/{order.pk}/angebot/")
    assert r.status_code == 302 and r.url.endswith("#angebot")


def test_package_availability(order, articles):
    from apps.catalog.models import Package, PackageItem
    from apps.orders.availability import package_available

    p = Package.objects.create(name="Tischdeko", price=Decimal("20"))
    PackageItem.objects.create(package=p, article=articles["vase"], quantity=4)
    other = make_order(order.created_by, order.customer)
    # 20 Vasen im Bestand, 10 im ersten Auftrag → 10 frei → 2 Pakete
    assert package_available(p, other) == 2


def test_document_numbers_follow_order_number(order, admin, sig):
    offer = docs.create_offer(order, admin)
    suffix = order.number.split("-", 1)[1]
    assert offer.number == f"AN-{suffix}"
    sign(offer, admin, sig)
    assert docs.create_contract(order, admin).number == f"MV-{suffix}"


# --------------------------------------------------------------------------
# E-Mail-Versand im Hintergrund mit Wiederholung
# --------------------------------------------------------------------------

@pytest.fixture
def mailserver(company, monkeypatch, settings):
    from django.core.mail.backends.locmem import EmailBackend

    from apps.core import mail

    settings.MAIL_ASYNC = False
    company.smtp_host = "smtp.example.de"
    company.mail_from_email = "info@example.de"
    company.save()
    state = {"fail": 0}

    class Flaky(EmailBackend):
        def send_messages(self, messages):
            if state["fail"] > 0:
                state["fail"] -= 1
                raise TimeoutError("timed out")
            return super().send_messages(messages)

    monkeypatch.setattr(mail, "_backend", lambda c: Flaky())
    return state


def test_mail_is_queued_and_retried(order, admin, mailserver):
    from apps.core import mail

    offer = docs.create_offer(order, admin)
    mailserver["fail"] = 1
    log = mail.queue_mail(to="anna@example.de", subject="Angebot", body="Text", documents=[offer], user=admin, order=order)
    assert log.status == EmailLog.Status.QUEUED
    log = mail.deliver(log.pk)
    assert log.status == EmailLog.Status.QUEUED and log.attempts == 1 and "timed out" in log.error
    EmailLog.objects.filter(pk=log.pk).update(next_attempt_at=timezone.now())
    assert mail.retry_due() == 1
    log.refresh_from_db()
    assert log.status == EmailLog.Status.SENT
    assert len(djmail.outbox) == 1
    assert djmail.outbox[0].attachments[0][0] == offer.filename
    offer.refresh_from_db()
    assert offer.last_emailed_at is not None


def test_mail_gives_up_after_max_attempts(order, admin, mailserver):
    from apps.core import mail

    mailserver["fail"] = 99
    log = mail.queue_mail(to="anna@example.de", subject="x", body="y", user=admin, order=order)
    for _ in range(mail.MAX_ATTEMPTS):
        EmailLog.objects.filter(pk=log.pk).update(next_attempt_at=timezone.now())
        mail.deliver(log.pk)
    log.refresh_from_db()
    assert log.status == EmailLog.Status.FAILED
    mail.requeue(log)
    log.refresh_from_db()
    assert log.status == EmailLog.Status.QUEUED and log.attempts == 0


def test_email_view_queues_and_returns_immediately(client, order, admin, mailserver):
    offer = docs.create_offer(order, admin)
    client.force_login(admin)
    r = client.post(f"/dokumente/{offer.pk}/email/", {"to": "anna@example.de", "subject": "Angebot", "body": "Hallo"})
    assert r.status_code == 302
    assert EmailLog.objects.get().status == EmailLog.Status.QUEUED
