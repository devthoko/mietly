"""Geschäftsvorgänge rund um den Auftrag. Alle Sperren laufen über workflow.py."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import StockMovement
from apps.core import audit
from apps.core.models import CompanySettings
from apps.core.numbering import next_number
from apps.core.templatetags.ui import format_euro

from . import workflow
from .models import (
    Damage, DepositTransaction, Handover, HandoverItem, Order, OrderItem, ReturnItem, ReturnRecord, money,
)
from .workflow import WorkflowError


@transaction.atomic
def create_order(user, customer=None):
    order = Order.objects.create(number=next_number("order"), customer=customer, created_by=user)
    audit.log(user, "order", f"Auftrag {order.number} angelegt", obj=order, order=order)
    workflow.refresh_stage(order)
    return order


@transaction.atomic
def set_customer(order, customer, user):
    workflow.assert_active(order)
    if workflow.current_document(order, "offer") is not None:
        raise WorkflowError("Nach dem Erstellen des Angebots kann der Kunde nicht mehr gewechselt werden. Legen Sie bei Bedarf einen neuen Auftrag an.")
    order.customer = customer
    order.save(update_fields=["customer", "updated_at"])
    audit.log(user, "order", f"Kunde gesetzt: {customer.full_name}", obj=order, order=order)
    workflow.refresh_stage(order)


def _invalidate_documents(order, user, *, include_signed=False):
    """Angebot (und ggf. Vertrag) passen nach Änderungen nicht mehr zum Auftrag
    und dürfen daher nicht mehr unterschrieben werden – sie werden ersetzt."""
    from apps.documents.models import Document

    statuses = [Document.Status.ISSUED] + ([Document.Status.SIGNED] if include_signed else [])
    kinds = ["offer", "contract"] if include_signed else ["offer"]
    docs = order.documents.filter(kind__in=kinds, status__in=statuses)
    if docs.exists():
        names = ", ".join(d.display_name for d in docs)
        docs.update(status=Document.Status.SUPERSEDED)
        audit.log(user, "document", f"Durch Änderungen ungültig geworden: {names} – bitte neu erstellen", order=order)


# Felder, die in Angebot, Vertrag und Rechnung stehen
DOCUMENT_FIELDS = {"event_name", "event_date", "event_location", "fulfillment", "delivery_address", "handover_at", "return_at", "customer_note"}


@transaction.atomic
def save_event(order, form, user):
    workflow.assert_active(order)
    relevant = set(form.changed_data) & DOCUMENT_FIELDS
    if relevant:
        if workflow.handover_completed(order):
            raise WorkflowError("Nach der Übergabe können Eventdaten und Termine nicht mehr geändert werden.")
        if workflow.main_invoice(order) is not None:
            raise WorkflowError("Eventdaten und Termine sind Bestandteil von Vertrag und Rechnung. Bitte zuerst die Rechnung stornieren.")
    form.save()
    audit.log(user, "order", "Eventdaten gespeichert", obj=order, order=order)
    if relevant:
        # Termine und Ort stehen in Angebot und Vertrag – diese müssen neu erstellt werden.
        _invalidate_documents(order, user, include_signed=True)
    sync_delivery_fee(order, user)
    workflow.refresh_stage(order)


DELIVERY_LABEL = "Lieferung und Abholung"


def sync_delivery_fee(order, user):
    """Lieferpauschale aus den Einstellungen bei Lieferung ergänzen bzw. bei Abholung entfernen."""
    fee = CompanySettings.get().delivery_fee
    existing = order.items.filter(kind=OrderItem.Kind.DELIVERY).first()
    wanted = order.fulfillment == Order.Fulfillment.DELIVERY and fee > 0
    if wanted == (existing is not None):
        return
    try:
        workflow.assert_can_edit_items(order)
    except WorkflowError:
        return
    if wanted:
        OrderItem.objects.create(
            order=order, kind=OrderItem.Kind.DELIVERY, description=DELIVERY_LABEL, detail=order.event_location[:300],
            quantity=1, unit_price=money(fee), vat_rate=_vat(None), sort=10000,
        )
        audit.log(user, "order", f"Lieferpauschale {format_euro(fee)} ergänzt", obj=order, order=order)
    else:
        existing.delete()
        audit.log(user, "order", "Lieferpauschale entfernt (Abholung)", obj=order, order=order)
    _invalidate_documents(order, user)


@transaction.atomic
def delete_draft(order, user):
    """Leere Entwürfe (ohne Dokumente, Rechnungen und Zahlungen) dürfen gelöscht werden."""
    if not workflow.is_empty_draft(order):
        raise WorkflowError("Dieser Auftrag hat bereits Dokumente oder Zahlungen und kann nur storniert werden.")
    number = order.number
    audit.log(user, "order", f"Auftragsentwurf {number} gelöscht")
    order.items.all().delete()
    order.photos.all().delete()
    order.delete()
    return number


def _extra_days(order):
    company = CompanySettings.get()
    return max(0, order.rental_days - company.included_rental_days)


def _vat(obj_rate):
    company = CompanySettings.get()
    return obj_rate if obj_rate is not None else company.default_vat_rate


def article_price(order, article, extra_days=None):
    if extra_days is None:
        extra_days = _extra_days(order)
    return money(article.price + article.extra_day_price * extra_days)


def package_price(order, package, extra_days=None):
    if extra_days is None:
        extra_days = _extra_days(order)
    return money(package.effective_price + package.extra_day_price * extra_days)


def _detail_for(order, base_detail=""):
    extra = _extra_days(order)
    parts = [p for p in [base_detail] if p]
    if extra:
        parts.append(f"inkl. {extra} Zusatztag{'e' if extra > 1 else ''}")
    return " · ".join(parts)


MAX_QTY = 9999
MAX_PRICE = Decimal("99999.99")
MAX_LINE = Decimal("999999.99")


def _check_line(quantity, unit_price=None):
    """Plausible Grenzen – verhindert Überläufe in Rechnung und Datenbank."""
    if quantity < 1:
        raise WorkflowError("Die Menge muss mindestens 1 sein.")
    if quantity > MAX_QTY:
        raise WorkflowError(f"Die Menge ist zu groß (höchstens {MAX_QTY:,}).".replace(",", "."))
    if unit_price is not None:
        if not unit_price.is_finite() or unit_price < 0:
            raise WorkflowError("Der Preis darf nicht negativ sein.")
        if unit_price > MAX_PRICE:
            raise WorkflowError("Der Einzelpreis ist zu hoch (höchstens 99.999,99 €).")
        if unit_price * quantity > MAX_LINE:
            raise WorkflowError("Der Betrag dieser Position ist zu hoch (höchstens 999.999,99 €).")


@transaction.atomic
def add_article(order, article, quantity, user):
    workflow.assert_can_edit_items(order)
    existing = order.items.filter(kind=OrderItem.Kind.ARTICLE, article=article).first()
    if existing:
        _check_line(existing.quantity + quantity, existing.unit_price)
        existing.quantity += quantity
        existing.save(update_fields=["quantity"])
        item = existing
    else:
        _check_line(quantity, article_price(order, article))
        item = OrderItem.objects.create(
            order=order, kind=OrderItem.Kind.ARTICLE, article=article, description=article.name,
            detail=_detail_for(order), quantity=quantity, unit_price=article_price(order, article),
            vat_rate=_vat(article.vat_rate), sort=order.items.count(),
        )
    _invalidate_documents(order, user)
    _update_deposit_suggestion(order)
    workflow.refresh_stage(order)
    return item


@transaction.atomic
def add_package(order, package, quantity, user):
    workflow.assert_can_edit_items(order)
    existing = order.items.filter(kind=OrderItem.Kind.PACKAGE, package=package).first()
    if existing:
        _check_line(existing.quantity + quantity, existing.unit_price)
        existing.quantity += quantity
        existing.save(update_fields=["quantity"])
        item = existing
    else:
        _check_line(quantity, package_price(order, package))
        item = OrderItem.objects.create(
            order=order, kind=OrderItem.Kind.PACKAGE, package=package, description=package.name,
            detail=_detail_for(order, "Paket"), quantity=quantity, unit_price=package_price(order, package),
            vat_rate=_vat(package.vat_rate), sort=order.items.count(),
        )
    _invalidate_documents(order, user)
    _update_deposit_suggestion(order)
    workflow.refresh_stage(order)
    return item


@transaction.atomic
def add_custom(order, *, description, detail, quantity, unit_price, vat_rate, user):
    workflow.assert_can_edit_items(order)
    _check_line(quantity, unit_price)
    item = OrderItem.objects.create(
        order=order, kind=OrderItem.Kind.CUSTOM, description=description, detail=detail or "",
        quantity=quantity, unit_price=money(unit_price), vat_rate=_vat(vat_rate), sort=order.items.count(),
    )
    _invalidate_documents(order, user)
    workflow.refresh_stage(order)
    return item


@transaction.atomic
def update_item(item, *, quantity, unit_price, discount_percent, description=None, user=None):
    workflow.assert_can_edit_items(item.order)
    _check_line(quantity, unit_price)
    if not discount_percent.is_finite() or not (0 <= discount_percent <= 100):
        raise WorkflowError("Der Rabatt muss zwischen 0 und 100 % liegen.")
    item.quantity = quantity
    item.unit_price = money(unit_price)
    item.discount_percent = discount_percent
    if description:
        item.description = description[:200]
    item.save()
    _invalidate_documents(item.order, user)
    _update_deposit_suggestion(item.order)
    workflow.refresh_stage(item.order)


@transaction.atomic
def remove_item(item, user):
    order = item.order
    workflow.assert_can_edit_items(order)
    item.delete()
    _invalidate_documents(order, user)
    _update_deposit_suggestion(order)
    workflow.refresh_stage(order)


@transaction.atomic
def reprice(order, user):
    """Preise nach geänderter Mietdauer aus den aktuellen Artikelpreisen neu berechnen."""
    workflow.assert_can_edit_items(order)
    for item in order.items.select_related("article", "package"):
        if item.article_id:
            item.unit_price = article_price(order, item.article)
            item.detail = _detail_for(order)
        elif item.package_id:
            item.unit_price = package_price(order, item.package)
            item.detail = _detail_for(order, "Paket")
        else:
            continue
        item.save(update_fields=["unit_price", "detail"])
    _invalidate_documents(order, user)
    audit.log(user, "order", "Preise neu berechnet", obj=order, order=order)


def _update_deposit_suggestion(order):
    """Kautionsvorschlag folgt den Positionen, solange noch kein Angebot erstellt wurde
    und niemand den Betrag manuell geändert hat."""
    if workflow.current_document(order, "offer") is not None or order.deposit_manual:
        return
    order.deposit_amount = order.suggested_deposit
    order.save(update_fields=["deposit_amount"])


@transaction.atomic
def set_deposit(order, amount, user):
    workflow.assert_can_edit_items(order)
    amount = money(amount)
    if amount < 0:
        raise WorkflowError("Die Kaution darf nicht negativ sein.")
    order.deposit_amount = amount
    order.deposit_manual = True
    order.save(update_fields=["deposit_amount", "deposit_manual"])
    _invalidate_documents(order, user)
    audit.log(user, "deposit", f"Kaution auf {format_euro(order.deposit_amount)} festgelegt", obj=order, order=order)


# --------------------------------------------------------------------------
# Packliste & Übergabe
# --------------------------------------------------------------------------

def create_packing_list(order, user):
    from apps.documents import snapshots
    from apps.documents.services import create_simple

    workflow.assert_active(order)
    if not order.items.exists():
        raise WorkflowError("Der Auftrag enthält keine Positionen.")
    return create_simple(order, "packing_list", user, snapshots.packing_list)


@transaction.atomic
def start_handover(order, user):
    workflow.assert_handover_allowed(order)
    handover = getattr(order, "handover", None)
    if handover is None:
        handover = Handover.objects.create(order=order, performed_by=user, recipient_name=order.customer.full_name)
        for article, qty in sorted(order.article_quantities().items(), key=lambda x: x[0].name):
            HandoverItem.objects.create(handover=handover, article=article, planned_qty=qty, quantity=qty)
        if workflow.current_document(order, "packing_list") is None:
            create_packing_list(order, user)
        audit.log(user, "handover", "Übergabe begonnen", obj=handover, order=order)
    return handover


@transaction.atomic
def save_handover(order, data, user):
    """data: {'performed_at', 'recipient_name', 'notes', 'items': {item_id: {...}}}"""
    workflow.assert_handover_allowed(order)
    h = order.handover
    if h.is_completed:
        raise WorkflowError("Die Übergabe ist bereits abgeschlossen.")
    h.performed_at = data["performed_at"]
    h.recipient_name = data["recipient_name"]
    h.notes = data["notes"]
    h.performed_by = user
    h.save()
    for item in h.items.all():
        values = data["items"].get(item.pk)
        if not values:
            continue
        item.quantity = values["quantity"]
        item.condition = values["condition"]
        item.existing_damage = values["existing_damage"]
        item.note = values["note"]
        item.save()
    # Ein bereits erstelltes Protokoll passt nicht mehr zu den geänderten Angaben
    from apps.documents.models import Document

    doc = workflow.current_document(order, "handover")
    if doc is not None:
        doc.status = Document.Status.SUPERSEDED
        doc.save(update_fields=["status"])
    workflow.refresh_stage(order)


def create_handover_protocol(order, user):
    from apps.documents import snapshots
    from apps.documents.services import create_simple

    workflow.assert_handover_allowed(order)
    h = getattr(order, "handover", None)
    if h is None:
        raise WorkflowError("Bitte zuerst die Übergabe erfassen.")
    if h.is_completed:
        raise WorkflowError("Die Übergabe ist bereits abgeschlossen.")
    if not h.recipient_name.strip():
        raise WorkflowError("Bitte angeben, wer die Artikel entgegennimmt.")
    return create_simple(order, "handover", user, snapshots.handover)


@transaction.atomic
def complete_handover(order, user):
    h = getattr(order, "handover", None)
    if h is None:
        raise WorkflowError("Bitte zuerst die Übergabe erfassen.")
    workflow.assert_handover_completable(order, handover=h)
    h.status = Handover.Status.COMPLETED
    h.completed_at = timezone.now()
    h.save()  # Handover.save() prüft die Sperren ein weiteres Mal
    audit.log(user, "handover", "Übergabe abgeschlossen", obj=h, order=order)
    workflow.refresh_stage(order)
    return h


# --------------------------------------------------------------------------
# Rücknahme, Schäden, Kaution, Abschluss
# --------------------------------------------------------------------------

@transaction.atomic
def start_return(order, user):
    workflow.assert_can_start_return(order)
    record = getattr(order, "return_record", None)
    if record is None:
        record = ReturnRecord.objects.create(order=order, performed_by=user, returned_by_name=order.handover.recipient_name)
        for hi in order.handover.items.select_related("article"):
            if hi.quantity:
                ReturnItem.objects.create(return_record=record, article=hi.article, expected_qty=hi.quantity, returned_qty=hi.quantity)
        audit.log(user, "return", "Rücknahme begonnen", obj=record, order=order)
    return record


@transaction.atomic
def save_return(order, data, user):
    workflow.assert_can_start_return(order)
    r = order.return_record
    if r.is_completed:
        raise WorkflowError("Die Rücknahme ist bereits abgeschlossen.")
    r.performed_at = data["performed_at"]
    r.returned_by_name = data["returned_by_name"]
    r.notes = data["notes"]
    r.performed_by = user
    r.save()
    for item in r.items.select_related("article"):
        values = data["items"].get(item.pk)
        if not values:
            continue
        returned = min(values["returned_qty"], item.expected_qty)
        damaged = min(values["damaged_qty"], returned)
        item.returned_qty = returned
        item.damaged_qty = damaged
        item.condition = values["condition"] if not damaged else "damaged"
        item.note = values["note"]
        item.save()
    _sync_auto_damages(order, user)
    workflow.refresh_stage(order)


def _sync_auto_damages(order, user):
    """Fehlmengen und Beschädigungen aus der Rücknahme als Schadensposten führen.
    Automatisch erzeugte Posten werden aktualisiert, manuell angepasste Beträge bleiben erhalten."""
    r = order.return_record
    for item in r.items.select_related("article"):
        for kind, qty in (("missing", item.missing_qty), ("damaged", item.damaged_qty)):
            dmg = order.damages.filter(article=item.article, kind=kind, settlement="open").first()
            if qty <= 0:
                if dmg:
                    dmg.delete()
                continue
            if kind == "missing":
                description = f"{item.article.name}: {qty}× fehlt bei Rückgabe"
            else:
                description = f"{item.article.name}: {qty}× beschädigt zurückgegeben" + (f" – {item.note}" if item.note else "")
            if dmg is None:
                Damage.objects.create(
                    order=order, article=item.article, kind=kind, quantity=qty, description=description[:300],
                    amount=money(item.article.replacement_value * qty), write_off=(kind == "missing"), created_by=user,
                )
            elif dmg.quantity != qty:
                per_unit = dmg.amount / dmg.quantity if dmg.quantity else item.article.replacement_value
                dmg.quantity = qty
                dmg.amount = money(per_unit * qty)
                dmg.description = description[:300]
                dmg.save()


def _book_write_off(dmg, user, reverse=False):
    reason = StockMovement.Reason.LOSS if dmg.kind == "missing" else StockMovement.Reason.DAMAGE
    StockMovement.objects.create(
        article=dmg.article, quantity=dmg.quantity if reverse else -dmg.quantity,
        reason=StockMovement.Reason.CORRECTION if reverse else reason,
        note=("Ausbuchung zurückgenommen: " if reverse else "") + dmg.description[:170], order=dmg.order, created_by=user,
    )


@transaction.atomic
def add_damage(order, *, kind, article, quantity, description, amount, write_off, user):
    workflow.assert_can_start_return(order)
    if return_locked(order):
        raise WorkflowError("Die Schadensabrechnung ist bereits erfolgt.")
    dmg = Damage.objects.create(order=order, kind=kind, article=article, quantity=quantity, description=description,
                                amount=money(amount), write_off=bool(write_off and article), created_by=user)
    if dmg.write_off and workflow.return_completed(order):
        # Die Rücknahme ist schon gebucht – die Ausbuchung erfolgt deshalb sofort.
        _book_write_off(dmg, user)
    audit.log(user, "damage", f"{dmg.get_kind_display()} erfasst: {description} ({format_euro(dmg.amount)})", obj=dmg, order=order)
    return dmg


@transaction.atomic
def update_damage(dmg, *, amount, description, write_off, user):
    if dmg.settlement != Damage.Settlement.OPEN:
        raise WorkflowError("Bereits abgerechnete Posten können nicht mehr geändert werden.")
    dmg.amount = money(amount)
    dmg.description = description
    if not workflow.return_completed(dmg.order):
        # Nach abgeschlossener Rücknahme ist die Bestandsbuchung bereits erfolgt.
        dmg.write_off = bool(write_off and dmg.article_id)
    dmg.save()


@transaction.atomic
def delete_damage(dmg, user):
    if dmg.settlement != Damage.Settlement.OPEN:
        raise WorkflowError("Bereits abgerechnete Posten können nicht gelöscht werden.")
    if dmg.write_off and dmg.article_id and workflow.return_completed(dmg.order):
        _book_write_off(dmg, user, reverse=True)
    audit.log(user, "damage", f"Schadensposten entfernt: {dmg.description}", order=dmg.order)
    dmg.delete()


def return_locked(order):
    return order.damages.exclude(settlement=Damage.Settlement.OPEN).exists()


@transaction.atomic
def complete_return(order, user):
    from apps.documents import snapshots
    from apps.documents.services import create_simple

    workflow.assert_can_start_return(order)
    r = order.return_record
    if r.is_completed:
        raise WorkflowError("Die Rücknahme ist bereits abgeschlossen.")
    r.status = ReturnRecord.Status.COMPLETED
    r.completed_at = timezone.now()
    r.save()
    # Bestand: Fehlmengen und ausgemusterte Artikel ausbuchen
    for dmg in order.damages.filter(write_off=True, article__isnull=False):
        _book_write_off(dmg, user)
    create_simple(order, "return", user, snapshots.return_protocol)
    audit.log(user, "return", "Rücknahme abgeschlossen", obj=r, order=order)
    workflow.refresh_stage(order)
    return r


@transaction.atomic
def record_deposit(order, *, amount, date, method, reason, user):
    workflow.assert_active(order)
    amount = money(amount)
    if amount <= 0:
        raise WorkflowError("Der Betrag muss größer als 0 sein.")
    if order.deposit_amount <= 0:
        raise WorkflowError("Für diesen Auftrag ist keine Kaution vereinbart.")
    if workflow.handover_completed(order) and workflow.return_completed(order):
        raise WorkflowError("Nach der Rücknahme kann keine Kaution mehr vereinnahmt werden.")
    outstanding = workflow.deposit_state(order).outstanding
    if amount > outstanding:
        raise WorkflowError(f"Der Betrag übersteigt die noch offene Kaution ({format_euro(outstanding)}).")
    if date > timezone.localdate():
        raise WorkflowError("Das Datum darf nicht in der Zukunft liegen.")
    t = DepositTransaction.objects.create(order=order, kind="received", amount=amount, date=date, method=method, reason=reason, created_by=user)
    audit.log(user, "deposit", f"Kaution {format_euro(amount)} erhalten ({t.get_method_display()})", obj=t, order=order)
    workflow.refresh_stage(order)
    return t


@transaction.atomic
def settle(order, *, decisions, refund_method, user):
    """Schäden abrechnen und Kaution auszahlen.

    decisions: {damage_id: 'deposit' | 'invoice' | 'waived'}
    Ablauf: Beträge mit Kautionsverrechnung werden einbehalten (bis zur Höhe
    der verwahrten Kaution); übersteigende Beträge und Posten zur
    Nachberechnung werden in einer Rechnung gestellt; der Rest der Kaution
    wird als Rückzahlung erfasst.
    """
    from apps.billing.models import Invoice
    from apps.billing.services import issue_additional_invoice
    from apps.documents import snapshots
    from apps.documents.services import create_simple

    workflow.assert_active(order)
    if not workflow.return_completed(order):
        raise WorkflowError("Die Abrechnung ist erst nach abgeschlossener Rücknahme möglich.")
    company = CompanySettings.get()
    dep = workflow.deposit_state(order)
    held = dep.held
    today = timezone.localdate()
    invoice_lines = []

    for dmg in order.damages.filter(settlement=Damage.Settlement.OPEN).select_related("article"):
        choice = decisions.get(dmg.pk)
        if choice not in ("deposit", "invoice", "waived"):
            raise WorkflowError(f"Bitte für „{dmg.description}“ die Abrechnungsart wählen.")
        if dmg.amount <= 0:
            choice = "waived"
        if choice == "deposit" and held <= 0:
            choice = "invoice"
        # Schadensersatz für Beschädigung/Verlust ist nicht umsatzsteuerbar,
        # Zusatzleistungen (Sonderreinigung, Sonstiges) dagegen schon.
        vat = Decimal("0") if dmg.kind in ("damaged", "missing") else company.default_vat_rate
        if choice == "deposit":
            retain = min(held, dmg.amount)
            DepositTransaction.objects.create(order=order, kind="retained", amount=retain, date=today, method="offset",
                                              reason=dmg.description[:300], damage=dmg, created_by=user)
            held -= retain
            rest = dmg.amount - retain
            if rest > 0:
                invoice_lines.append({"description": dmg.description[:300], "detail": f"Restbetrag nach Verrechnung mit der Kaution ({format_euro(retain)})",
                                      "quantity": Decimal("1"), "unit_price": rest, "vat_rate": vat, "total": rest})
            dmg.settlement = Damage.Settlement.DEPOSIT
        elif choice == "invoice":
            invoice_lines.append({"description": dmg.description[:300], "detail": dmg.get_kind_display(), "quantity": Decimal("1"),
                                  "unit_price": dmg.amount, "vat_rate": vat, "total": dmg.amount})
            dmg.settlement = Damage.Settlement.INVOICE
        else:
            dmg.settlement = Damage.Settlement.WAIVED
        dmg.save(update_fields=["settlement"])

    if invoice_lines:
        issue_additional_invoice(order, user, invoice_lines, kind=Invoice.Kind.ADDITIONAL)
    if held > 0:
        DepositTransaction.objects.create(order=order, kind="refunded", amount=held, date=today, method=refund_method,
                                          reason="Rückzahlung der Kaution", created_by=user)
    if dep.received > 0:
        create_simple(order, "deposit", user, snapshots.deposit_statement)
    audit.log(user, "deposit", f"Kaution abgerechnet: einbehalten {format_euro(workflow.deposit_state(order).retained)}, zurückgezahlt {format_euro(held)}", order=order)
    workflow.refresh_stage(order)


@transaction.atomic
def refund_deposit_after_cancellation(order, *, method, user):
    if order.status != Order.Status.CANCELLED:
        raise WorkflowError("Nur bei stornierten Aufträgen möglich – sonst über die Kautionsabrechnung.")
    held = workflow.deposit_state(order).held
    if held <= 0:
        raise WorkflowError("Es ist keine Kaution mehr verwahrt.")
    DepositTransaction.objects.create(order=order, kind="refunded", amount=held, date=timezone.localdate(), method=method,
                                      reason="Rückzahlung nach Stornierung", created_by=user)
    audit.log(user, "deposit", f"Kaution {format_euro(held)} nach Stornierung zurückgezahlt", order=order)


@transaction.atomic
def close_order(order, user):
    workflow.assert_can_close(order)
    order.status = Order.Status.COMPLETED
    order.completed_at = timezone.now()
    order.save(update_fields=["status", "completed_at", "updated_at"])
    audit.log(user, "order", "Auftrag abgeschlossen", obj=order, order=order)
    workflow.refresh_stage(order)


@transaction.atomic
def cancel_order(order, *, reason, fee, user):
    from apps.billing.models import Invoice
    from apps.billing.services import cancel_invoice, issue_additional_invoice

    workflow.assert_active(order)
    if workflow.handover_completed(order):
        raise WorkflowError("Nach der Übergabe kann der Auftrag nicht mehr storniert werden.")
    if not reason.strip():
        raise WorkflowError("Bitte einen Stornogrund angeben.")
    inv = workflow.main_invoice(order)
    if inv is not None:
        cancel_invoice(inv, user, f"Auftrag storniert: {reason}")
    if fee and fee > 0:
        company = CompanySettings.get()
        issue_additional_invoice(order, user, [{
            "description": "Stornogebühr gemäß Mietvertrag", "detail": reason[:300], "quantity": Decimal("1"),
            "unit_price": money(fee), "vat_rate": company.default_vat_rate, "total": money(fee),
        }], kind=Invoice.Kind.CANCELLATION_FEE)
    from apps.documents.models import Document

    order.documents.filter(status=Document.Status.ISSUED, kind__in=["offer", "contract", "packing_list", "handover"]).update(status=Document.Status.VOID)
    order.status = Order.Status.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancel_reason = reason[:300]
    order.save(update_fields=["status", "cancelled_at", "cancel_reason", "updated_at"])
    audit.log(user, "order", f"Auftrag storniert: {reason}", obj=order, order=order)
