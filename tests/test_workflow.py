"""Der vollständige Auftragsablauf und die verbindlichen geschäftlichen Sperren."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import Invoice
from apps.documents import services as docs
from apps.orders import services, workflow
from apps.orders.models import Handover, Order
from apps.orders.workflow import WorkflowError
from tests.conftest import make_order


def sign(doc, user, sig):
    return docs.sign_document(doc, signer_name="Anna Beispiel", signature_data_url=sig, user=user, ip="127.0.0.1")


def to_paid_invoice(order, admin, sig):
    offer = docs.create_offer(order, admin)
    sign(offer, admin, sig)
    contract = docs.create_contract(order, admin)
    sign(contract, admin, sig)
    inv = billing.issue_invoice(order, admin)
    billing.record_payment(order, amount=inv.total_gross, paid_on=timezone.localdate(), method="transfer", user=admin)
    services.record_deposit(order, amount=order.deposit_amount, date=timezone.localdate(), method="cash", reason="", user=admin)
    return inv


# --------------------------------------------------------------------------
# Sperre 1: Vertrag nur mit unterschriebenem Angebot
# --------------------------------------------------------------------------

def test_contract_requires_signed_offer(order, admin):
    with pytest.raises(WorkflowError):
        docs.create_contract(order, admin)
    docs.create_offer(order, admin)
    with pytest.raises(WorkflowError, match="Angebot unterschrieben"):
        docs.create_contract(order, admin)


def test_contract_possible_after_offer_upload(order, admin):
    from django.core.files.uploadedfile import SimpleUploadedFile

    offer = docs.create_offer(order, admin)
    upload = SimpleUploadedFile("unterschrieben.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    docs.upload_signed(offer, upload=upload, signer_name="Anna Beispiel", user=admin)
    assert docs.create_contract(order, admin).kind == "contract"


def test_upload_rejects_non_documents(order, admin):
    from django.core.exceptions import ValidationError
    from django.core.files.uploadedfile import SimpleUploadedFile

    offer = docs.create_offer(order, admin)
    with pytest.raises(ValidationError):
        docs.upload_signed(offer, upload=SimpleUploadedFile("x.exe", b"MZ\x90\x00", content_type="application/pdf"), signer_name="Anna", user=admin)


# --------------------------------------------------------------------------
# Sperre 2: Rechnung nur mit unterschriebenem Vertrag
# --------------------------------------------------------------------------

def test_invoice_requires_signed_contract(order, admin, sig):
    offer = docs.create_offer(order, admin)
    sign(offer, admin, sig)
    with pytest.raises(WorkflowError):
        billing.issue_invoice(order, admin)
    docs.create_contract(order, admin)
    with pytest.raises(WorkflowError, match="Mietvertrag unterschrieben"):
        billing.issue_invoice(order, admin)


# --------------------------------------------------------------------------
# Sperre 3: Übergabe nur bei vollständig bezahlter Rechnung – auch nicht für Admins
# --------------------------------------------------------------------------

def test_handover_blocked_until_fully_paid(order, admin, sig):
    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)
    inv = billing.issue_invoice(order, admin)
    services.record_deposit(order, amount=order.deposit_amount, date=timezone.localdate(), method="cash", reason="", user=admin)

    with pytest.raises(WorkflowError, match="nicht vollständig bezahlt"):
        services.start_handover(order, admin)

    billing.record_payment(order, amount=inv.total_gross - Decimal("0.01"), paid_on=timezone.localdate(), method="transfer", user=admin)
    with pytest.raises(WorkflowError, match="nicht vollständig bezahlt"):
        services.start_handover(order, admin)

    billing.record_payment(order, amount=Decimal("0.01"), paid_on=timezone.localdate(), method="cash", user=admin)
    assert services.start_handover(order, admin).pk


def test_handover_lock_cannot_be_bypassed_by_direct_save(order, admin, sig):
    """Auch ein direkter Speicherversuch am Modell (z. B. über die Shell) scheitert."""
    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)
    billing.issue_invoice(order, admin)
    h = Handover(order=order, status=Handover.Status.COMPLETED)
    with pytest.raises(WorkflowError):
        h.save()
    assert not Handover.objects.filter(order=order).exists()


def test_admin_role_has_no_bypass(order, admin, sig, client):
    """Ein Administrator kann die Übergabe über die Oberfläche nicht vor Bezahlung starten."""
    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)
    billing.issue_invoice(order, admin)
    client.force_login(admin)
    client.post(f"/auftraege/{order.pk}/uebergabe/start/")
    assert not Handover.objects.filter(order=order).exists()


def test_deposit_required_before_handover(order, admin, sig, company):
    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)
    inv = billing.issue_invoice(order, admin)
    billing.record_payment(order, amount=inv.total_gross, paid_on=timezone.localdate(), method="transfer", user=admin)
    with pytest.raises(WorkflowError, match="Kaution"):
        services.start_handover(order, admin)
    company.deposit_required_before_handover = False
    company.save()
    assert services.start_handover(order, admin)


# --------------------------------------------------------------------------
# Sperre 4: Übergabe nur mit unterschriebenem Protokoll abschließen
# --------------------------------------------------------------------------

def test_handover_completion_requires_signed_protocol(order, admin, sig):
    to_paid_invoice(order, admin, sig)
    services.start_handover(order, admin)
    with pytest.raises(WorkflowError, match="Übergabeprotokoll"):
        services.complete_handover(order, admin)
    protocol = services.create_handover_protocol(order, admin)
    with pytest.raises(WorkflowError, match="Übergabeprotokoll"):
        services.complete_handover(order, admin)
    sign(protocol, admin, sig)
    services.complete_handover(order, admin)
    assert workflow.handover_completed(order)


def test_changing_handover_after_signing_requires_new_signature(order, admin, sig):
    to_paid_invoice(order, admin, sig)
    services.start_handover(order, admin)
    sign(services.create_handover_protocol(order, admin), admin, sig)
    h = order.handover
    item = h.items.first()
    services.save_handover(order, {
        "performed_at": h.performed_at, "recipient_name": h.recipient_name, "notes": "geändert",
        "items": {item.pk: {"quantity": item.quantity - 1, "condition": "good", "existing_damage": "", "note": ""}},
    }, admin)
    with pytest.raises(WorkflowError):
        services.complete_handover(order, admin)


# --------------------------------------------------------------------------
# Kompletter Ablauf inkl. Schäden und Kaution
# --------------------------------------------------------------------------

def test_full_workflow_with_damage_and_deposit(order, admin, sig):
    from apps.catalog.models import Article

    assert workflow.compute(order).current.key == "offer"
    inv = to_paid_invoice(order, admin, sig)
    assert inv.number.startswith("RE-")
    assert workflow.compute(order).current.key == "packing"

    services.create_packing_list(order, admin)
    services.start_handover(order, admin)
    sign(services.create_handover_protocol(order, admin), admin, sig)
    services.complete_handover(order, admin)
    assert workflow.compute(order).current.key == "return"

    record = services.start_return(order, admin)
    vase_item = record.items.get(article__name="Glasvase hoch")
    services.save_return(order, {
        "performed_at": timezone.now(), "returned_by_name": "Anna", "notes": "",
        "items": {vase_item.pk: {"returned_qty": 9, "damaged_qty": 1, "condition": "damaged", "note": "Sprung"}},
    }, admin)
    assert order.damages.count() == 2  # 1 fehlt, 1 beschädigt
    services.complete_return(order, admin)
    # Fehlmenge wird aus dem Bestand gebucht
    assert Article.objects.get(name="Glasvase hoch").stock == 19

    with pytest.raises(WorkflowError):
        services.close_order(order, admin)

    held_before = workflow.deposit_state(order).held
    services.settle(order, decisions={d.pk: "deposit" for d in order.damages.all()}, refund_method="transfer", user=admin)
    dep = workflow.deposit_state(order)
    assert dep.retained == Decimal("50.00")
    assert dep.refunded == held_before - Decimal("50.00")
    assert dep.held == 0
    assert workflow.current_document(order, "deposit") is not None

    services.close_order(order, admin)
    order.refresh_from_db()
    assert order.status == Order.Status.COMPLETED


def test_damage_exceeding_deposit_creates_additional_invoice(order, admin, sig):
    to_paid_invoice(order, admin, sig)
    services.start_handover(order, admin)
    sign(services.create_handover_protocol(order, admin), admin, sig)
    services.complete_handover(order, admin)
    services.start_return(order, admin)
    arch = order.return_record.items.get(article__name="Traubogen Holz")
    services.save_return(order, {
        "performed_at": timezone.now(), "returned_by_name": "", "notes": "",
        "items": {arch.pk: {"returned_qty": 0, "damaged_qty": 0, "condition": "good", "note": ""}},
    }, admin)
    services.complete_return(order, admin)
    held = workflow.deposit_state(order).held
    services.settle(order, decisions={d.pk: "deposit" for d in order.damages.all()}, refund_method="cash", user=admin)
    extra = order.invoices.get(kind=Invoice.Kind.ADDITIONAL)
    assert extra.total_gross == Decimal("450.00") - held
    assert extra.lines.first().vat_rate == 0  # Schadensersatz nicht umsatzsteuerbar
    assert workflow.open_balance(order) == extra.total_gross
    with pytest.raises(WorkflowError):
        services.close_order(order, admin)
    billing.record_payment(order, amount=extra.total_gross, paid_on=timezone.localdate(), method="transfer", user=admin)
    services.close_order(order, admin)


# --------------------------------------------------------------------------
# Rechnungen: Nummernkreis, Unveränderlichkeit, Storno
# --------------------------------------------------------------------------

def test_invoice_immutable_and_cancellation(order, admin, sig):
    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)
    inv = billing.issue_invoice(order, admin)
    inv.total_gross = Decimal("1.00")
    with pytest.raises(ValueError):
        inv.save()
    inv.refresh_from_db()
    with pytest.raises(ValueError):
        inv.delete()
    with pytest.raises(WorkflowError):
        billing.issue_invoice(order, admin)  # nur eine gültige Rechnung
    storno = billing.cancel_invoice(inv, admin, "Positionen geändert")
    assert storno.number.startswith("SR-")
    assert storno.total_gross == -inv.total_gross
    assert workflow.main_invoice(order) is None
    inv2 = billing.issue_invoice(order, admin)
    assert int(inv2.number[-4:]) == int(inv.number[-4:]) + 1


def test_numbers_are_gapless_after_failed_transaction(order, admin, sig):
    from django.db import transaction

    from apps.core.numbering import next_number

    first = None
    with transaction.atomic():
        first = next_number("invoice")
    try:
        with transaction.atomic():
            next_number("invoice")
            raise RuntimeError("Abbruch")
    except RuntimeError:
        pass
    with transaction.atomic():
        second = next_number("invoice")
    assert int(second[-4:]) == int(first[-4:]) + 1


def test_vat_breakdown_gross_prices(order, admin, sig):
    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)
    inv = billing.issue_invoice(order, admin)
    # 10 × (4,50 + 0 Zusatztage) + 89,00 = 134,00 brutto bei 19 %
    assert inv.total_gross == Decimal("134.00")
    assert inv.total_net == Decimal("112.61")
    assert inv.total_vat == Decimal("21.39")


def test_small_business_has_no_vat(order, admin, sig, company):
    company.small_business = True
    company.save()
    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)
    inv = billing.issue_invoice(order, admin)
    assert inv.total_vat == 0 and inv.total_net == inv.total_gross


def test_payment_cannot_exceed_balance(order, admin, sig):
    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)
    inv = billing.issue_invoice(order, admin)
    with pytest.raises(WorkflowError):
        billing.record_payment(order, amount=inv.total_gross + 1, paid_on=timezone.localdate(), method="cash", user=admin)


# --------------------------------------------------------------------------
# Positionen, Versionen, Verfügbarkeit
# --------------------------------------------------------------------------

def test_items_locked_after_signed_offer_and_revision(order, admin, sig, articles):
    offer = docs.create_offer(order, admin)
    sign(offer, admin, sig)
    with pytest.raises(WorkflowError):
        services.add_article(order, articles["vase"], 1, admin)
    sign(docs.create_contract(order, admin), admin, sig)
    revised = docs.create_offer(order, admin)  # Überarbeitung
    assert revised.version == 2 and revised.number == offer.number
    offer.refresh_from_db()
    assert offer.status == "superseded"
    assert workflow.current_document(order, "contract") is None  # Vertrag muss neu unterschrieben werden
    services.add_article(order, articles["vase"], 1, admin)


def test_availability_prevents_overbooking(admin, customer, company, articles):
    first = make_order(admin, customer)
    services.add_article(first, articles["arch"], 1, admin)
    docs.create_offer(first, admin)
    second = make_order(admin, customer)
    services.add_article(second, articles["arch"], 1, admin)
    with pytest.raises(WorkflowError, match="Nicht genügend Bestand"):
        docs.create_offer(second, admin)
    # Ein Auftrag weit später ist möglich
    later = make_order(admin, customer, days_ahead=40)
    services.add_article(later, articles["arch"], 1, admin)
    assert docs.create_offer(later, admin)


def test_cancelled_order_frees_availability(admin, customer, company, articles):
    from tests.conftest import make_order

    first = make_order(admin, customer)
    services.add_article(first, articles["arch"], 1, admin)
    services.cancel_order(first, reason="Event abgesagt", fee=Decimal("0"), user=admin)
    second = make_order(admin, customer)
    services.add_article(second, articles["arch"], 1, admin)
    assert docs.create_offer(second, admin)


def test_cancel_order_with_invoice_creates_storno_and_fee(order, admin, sig):
    inv = to_paid_invoice(order, admin, sig)
    services.cancel_order(order, reason="Hochzeit verschoben", fee=Decimal("40.00"), user=admin)
    order.refresh_from_db()
    assert order.status == Order.Status.CANCELLED
    assert inv.is_cancelled
    assert workflow.invoiced_total(order) == Decimal("40.00")
    assert workflow.open_balance(order) == Decimal("40.00") - inv.total_gross


def test_signed_pdf_contains_hash_and_differs(order, admin, sig):
    offer = docs.create_offer(order, admin)
    signed = sign(offer, admin, sig)
    assert signed.signed_file and signed.signed_sha256 != signed.sha256
    assert signed.file.read()[:5] == b"%PDF-"
    with pytest.raises(WorkflowError):
        sign(signed, admin, sig)


def test_empty_signature_rejected(order, admin):
    from django.core.exceptions import ValidationError

    offer = docs.create_offer(order, admin)
    with pytest.raises(ValidationError):
        docs.sign_document(offer, signer_name="Anna", signature_data_url="", user=admin)


def test_item_change_invalidates_unsigned_offer(order, admin, sig, articles):
    offer = docs.create_offer(order, admin)
    services.add_article(order, articles["vase"], 1, admin)
    offer.refresh_from_db()
    assert offer.status == "superseded"
    with pytest.raises(WorkflowError):
        sign(offer, admin, sig)  # veraltetes Angebot kann nicht unterschrieben werden


def test_event_change_invalidates_signed_documents_until_invoice(order, admin, sig):
    from apps.orders.forms import EventForm

    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)

    def post(name):
        data = {
            "event_name": name, "event_date": order.event_date.isoformat(), "event_location": order.event_location,
            "fulfillment": order.fulfillment, "delivery_address": "",
            "handover_at": timezone.localtime(order.handover_at).strftime("%Y-%m-%dT%H:%M"),
            "return_at": timezone.localtime(order.return_at).strftime("%Y-%m-%dT%H:%M"), "customer_note": "", "notes": "",
        }
        form = EventForm(data, instance=Order.objects.get(pk=order.pk))
        assert form.is_valid(), form.errors
        services.save_event(Order.objects.get(pk=order.pk), form, admin)

    post("Hochzeit (umbenannt)")
    assert not workflow.is_signed(order, "offer") and not workflow.is_signed(order, "contract")
    sign(docs.create_offer(order, admin), admin, sig)
    sign(docs.create_contract(order, admin), admin, sig)
    billing.issue_invoice(order, admin)
    with pytest.raises(WorkflowError, match="Rechnung stornieren"):
        post("Noch einmal umbenannt")


def test_write_off_after_return_and_reversal(order, admin, sig, articles):
    from apps.catalog.models import Article

    to_paid_invoice(order, admin, sig)
    services.start_handover(order, admin)
    sign(services.create_handover_protocol(order, admin), admin, sig)
    services.complete_handover(order, admin)
    services.start_return(order, admin)
    services.complete_return(order, admin)
    stock = Article.objects.get(pk=articles["vase"].pk).stock
    dmg = services.add_damage(order, kind="damaged", article=articles["vase"], quantity=2, description="Bruch beim Transport",
                              amount=Decimal("50.00"), write_off=True, user=admin)
    assert Article.objects.get(pk=articles["vase"].pk).stock == stock - 2
    services.delete_damage(dmg, admin)
    assert Article.objects.get(pk=articles["vase"].pk).stock == stock
