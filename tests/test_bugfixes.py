"""Regressionstests für behobene Fehler (Version 1.0.2)."""


import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.billing import services as billing
from apps.documents import services as docs
from apps.orders import services, workflow
from apps.orders.workflow import WorkflowError
from tests.test_workflow import sign, to_paid_invoice


def test_iban_with_special_characters_is_validation_error_not_crash(company):
    from apps.core.forms import TaxBankForm

    data = {"small_business": False, "default_vat_rate": "19", "tax_number": "1", "vat_id": "", "account_holder": "",
            "bank_name": "", "bic": ""}
    for iban in ["DE89-3704-0044-0532-0130-00", "DE89 3704 0044 0532 0130 0!", "DÉ89370400440532013000"]:
        form = TaxBankForm({**data, "iban": iban}, instance=company)
        form.is_valid()  # darf nicht abstürzen
    assert TaxBankForm({**data, "iban": "DE89-3704-0044-0532-0130-00"}, instance=company).is_valid()
    assert not TaxBankForm({**data, "iban": "DE89 3704 0044 0532 0130 0!"}, instance=company).is_valid()


def test_negative_prices_and_invalid_vat_rejected(company):
    from apps.catalog.forms import ArticleForm, PackageForm
    from apps.core.forms import TaxBankForm

    base = {"name": "Vase", "price": "5", "extra_day_price": "0", "replacement_value": "10", "deposit_per_unit": "0",
            "vat_rate": "", "active": "on", "initial_stock": "1"}
    assert ArticleForm(base).is_valid()
    assert not ArticleForm({**base, "price": "-1"}).is_valid()
    assert not ArticleForm({**base, "deposit_per_unit": "-5"}).is_valid()
    assert not ArticleForm({**base, "vat_rate": "190"}).is_valid()
    assert not PackageForm({"name": "P", "price": "-10", "active": "on"}).is_valid()
    tax = {"small_business": False, "default_vat_rate": "-7", "tax_number": "1", "iban": ""}
    assert not TaxBankForm(tax, instance=company).is_valid()


def test_damage_form_rejects_negative_amount_and_zero_quantity(order):
    from apps.orders.forms import DamageForm

    ok = {"kind": "other", "article": "", "quantity": "1", "description": "Reinigung", "amount": "20"}
    assert DamageForm(ok, order=order).is_valid()
    assert not DamageForm({**ok, "amount": "-20"}, order=order).is_valid()
    assert not DamageForm({**ok, "quantity": "0"}, order=order).is_valid()
    assert not DamageForm({**ok, "write_off": "on"}, order=order).is_valid()  # ausbuchen ohne Artikel


def test_package_with_deactivated_article_still_editable(articles):
    from apps.catalog.forms import PackageItemForm
    from apps.catalog.models import Package, PackageItem

    p = Package.objects.create(name="Set")
    item = PackageItem.objects.create(package=p, article=articles["vase"], quantity=2)
    articles["vase"].active = False
    articles["vase"].save()
    form = PackageItemForm({"article": articles["vase"].pk, "quantity": 2}, instance=item)
    assert form.is_valid(), form.errors


def test_article_delete_with_protocol_reference_deactivates(client, admin, order, sig, articles):
    to_paid_invoice(order, admin, sig)
    services.start_handover(order, admin)  # Übergabeposten verweisen auf den Artikel
    order.items.all().delete()  # Auftragsposition entfernt – nur noch das Protokoll verweist darauf
    client.force_login(admin)
    r = client.post(f"/artikel/{articles['arch'].pk}/loeschen/")
    assert r.status_code == 302
    articles["arch"].refresh_from_db()
    assert articles["arch"].active is False


def test_profile_save_does_not_validate_password_form(client, admin):
    client.force_login(admin)
    r = client.post("/profil/", {"p-first_name": "Ada", "p-last_name": "L", "p-email": "ada@example.de", "save_profile": "1"})
    assert r.status_code == 302
    admin.refresh_from_db()
    assert admin.last_name == "L"


def test_uploaded_photo_signature_keeps_image_extension(order, admin):
    from apps.documents.models import Document

    offer = docs.create_offer(order, admin)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    docs.upload_signed(offer, upload=SimpleUploadedFile("foto.png", png), signer_name="Anna Beispiel", user=admin)
    offer = Document.objects.get(pk=offer.pk)
    assert offer.final_filename.endswith("_unterschrieben.png")
    assert offer.filename.endswith(".pdf")


def test_pdf_survives_missing_image(order, admin, articles):
    import os

    from apps.core.images import process_image

    from io import BytesIO
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (40, 40), "red").save(buf, "JPEG")
    articles["vase"].image = process_image(SimpleUploadedFile("v.jpg", buf.getvalue(), content_type="image/jpeg"))
    articles["vase"].save()
    os.remove(articles["vase"].image.path)  # Bilddatei fehlt
    doc = services.create_packing_list(order, admin)
    assert doc.file.read()[:5] == b"%PDF-"


def test_invoice_requires_mandatory_data(order, admin, sig, company):
    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)
    order.customer.street = ""
    order.customer.save()
    with pytest.raises(WorkflowError, match="Anschrift des Kunden"):
        billing.issue_invoice(order, admin)
    order.customer.street = "Musterweg 1"
    order.customer.save()
    company.tax_number = ""
    company.vat_id = ""
    company.save()
    with pytest.raises(WorkflowError, match="Steuernummer"):
        billing.issue_invoice(order, admin)


def test_deposit_cannot_exceed_agreed_amount(order, admin):
    with pytest.raises(WorkflowError, match="übersteigt"):
        services.record_deposit(order, amount=order.deposit_amount + 1, date=timezone.localdate(), method="cash", reason="", user=admin)
    services.record_deposit(order, amount=order.deposit_amount, date=timezone.localdate(), method="cash", reason="", user=admin)
    assert workflow.deposit_state(order).outstanding == 0


def test_csv_export_neutralizes_formulas(client, admin, order, sig):
    order.customer.first_name = "=HYPERLINK(\"x\")"
    order.customer.save()
    to_paid_invoice(order, admin, sig)
    client.force_login(admin)
    csv = client.get("/rechnungen/?export=csv").content.decode("utf-8-sig")
    assert "'=HYPERLINK" in csv and ';=HYPERLINK' not in csv and ';"=HYPERLINK' not in csv


def test_sign_page_for_superseded_document_redirects(client, admin, order, articles):
    offer = docs.create_offer(order, admin)
    services.add_article(order, articles["vase"], 1, admin)  # Angebot wird ersetzt
    client.force_login(admin)
    r = client.get(f"/dokumente/{offer.pk}/unterschreiben/")
    assert r.status_code == 302


def test_workflow_dates_in_local_time(order, admin, sig):
    """Ein Abschluss kurz vor Mitternacht (Ortszeit) erscheint mit dem richtigen Datum."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    to_paid_invoice(order, admin, sig)
    services.start_handover(order, admin)
    sign(services.create_handover_protocol(order, admin), admin, sig)
    services.complete_handover(order, admin)
    late = datetime(2026, 10, 20, 23, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    type(order.handover).objects.filter(pk=order.handover.pk).update(completed_at=late)
    order.refresh_from_db()
    state = workflow.compute(order)
    assert next(s for s in state.steps if s.key == "handover").summary == "am 20.10.2026"


def test_numbering_creates_sequence_once(db):
    from django.db import transaction

    from apps.core.models import NumberSequence
    from apps.core.numbering import next_number

    with transaction.atomic():
        a = next_number("offer")
        b = next_number("offer")
    assert a != b and NumberSequence.objects.filter(kind="offer").count() == 1


def test_old_login_attempts_are_pruned(client, db):
    from datetime import timedelta

    from apps.core.models import LoginAttempt

    old = LoginAttempt.objects.create(username="x")
    LoginAttempt.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=3))
    client.post("/anmelden/", {"username": "y", "password": "falsch"})
    assert not LoginAttempt.objects.filter(pk=old.pk).exists()


def test_invoice_list_pages_and_totals(client, admin, order, sig):
    to_paid_invoice(order, admin, sig)
    client.force_login(admin)
    html = client.get("/rechnungen/").content.decode()
    assert "Bezahlt" in html and "134,00" in html
    html = client.get("/rechnungen/?status=offen").content.decode()
    assert "Keine Rechnungen" in html


def test_unknown_host_shows_helpful_message(client, settings, db):
    settings.ALLOWED_HOSTS = ["localhost"]
    r = client.get("/anmelden/", HTTP_HOST="mietly.example")
    assert r.status_code == 400 and "MIETLY_ALLOWED_HOSTS" in r.content.decode()
