"""Rechnungen, Stornorechnungen, Nachberechnungen und Zahlungen."""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.models import CompanySettings
from apps.core.numbering import next_number
from apps.core.templatetags.ui import d, format_euro
from apps.orders import workflow
from apps.orders.workflow import WorkflowError

from .calc import money, totals
from .models import Invoice, InvoiceLine, Payment


def _service_period(order):
    if order.handover_at and order.return_at:
        a = timezone.localtime(order.handover_at).date()
        b = timezone.localtime(order.return_at).date()
        return f"{d(a)} – {d(b)}" if a != b else d(a)
    return d(timezone.localdate())


def _due_date(order, company):
    today = timezone.localdate()
    due = today + timedelta(days=company.payment_due_days)
    if order.handover_at:
        handover_day = timezone.localtime(order.handover_at).date()
        if handover_day > today:
            due = min(due, handover_day - timedelta(days=1))
        else:
            due = today
    return max(due, today)


def _create(order, kind, lines, user, cancels=None, due=None):
    company = CompanySettings.get()
    seq = "cancellation" if kind == Invoice.Kind.CANCELLATION else "invoice"
    t = totals([(l["total"], l["vat_rate"]) for l in lines], company.small_business)
    inv = Invoice.objects.create(
        order=order, kind=kind, number=next_number(seq), issue_date=timezone.localdate(),
        service_period=d(timezone.localdate()) if kind == Invoice.Kind.CANCELLATION_FEE else _service_period(order), due_date=due or _due_date(order, company),
        cancels=cancels, small_business=company.small_business,
        total_gross=t["gross"], total_net=t["net"], total_vat=t["vat"], vat_breakdown=t["breakdown"],
        created_by=user,
    )
    for pos, l in enumerate(lines, start=1):
        InvoiceLine.objects.create(
            invoice=inv, position=pos, description=l["description"], detail=l.get("detail", ""),
            quantity=l["quantity"], unit_price=l["unit_price"], discount_percent=l.get("discount", Decimal("0")),
            vat_rate=Decimal("0") if company.small_business else l["vat_rate"], total=l["total"],
        )
    from apps.documents.services import create_invoice_document

    create_invoice_document(inv, user)
    return inv


@transaction.atomic
def issue_invoice(order, user):
    workflow.assert_can_issue_invoice(order)
    lines = []
    for item in order.items.select_related("package").prefetch_related("package__items__article"):
        detail = item.detail
        if item.package_id:
            contents = ", ".join(f"{pi.quantity}× {pi.article.name}" for pi in item.package.items.all())
            detail = f"{detail}: {contents}" if detail else contents
        lines.append({
            "description": item.description, "detail": detail[:300], "quantity": Decimal(item.quantity),
            "unit_price": item.unit_price, "discount": item.discount_percent, "vat_rate": item.vat_rate, "total": item.total,
        })
    if not lines:
        raise WorkflowError("Der Auftrag enthält keine Positionen.")
    inv = _create(order, Invoice.Kind.INVOICE, lines, user)
    audit.log(user, "invoice", f"Rechnung {inv.number} über {format_euro(inv.total_gross)} erstellt", obj=inv, order=order)
    workflow.refresh_stage(order)
    return inv


@transaction.atomic
def cancel_invoice(invoice, user, reason):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    order = invoice.order
    if invoice.kind == Invoice.Kind.CANCELLATION:
        raise WorkflowError("Eine Stornorechnung kann nicht storniert werden.")
    if invoice.is_cancelled:
        raise WorkflowError("Diese Rechnung ist bereits storniert.")
    if invoice.kind == Invoice.Kind.INVOICE and workflow.handover_completed(order):
        raise WorkflowError("Nach erfolgter Übergabe kann die Mietrechnung nicht mehr storniert werden. Korrekturen bitte über eine Nachberechnung oder Erstattung.")
    if not (reason or "").strip():
        raise WorkflowError("Bitte einen Grund für die Stornierung angeben.")
    lines = []
    for l in invoice.lines.all():
        lines.append({
            "description": l.description, "detail": l.detail, "quantity": -l.quantity, "unit_price": l.unit_price,
            "discount": l.discount_percent, "vat_rate": l.vat_rate, "total": -l.total,
        })
    storno = _create(order, Invoice.Kind.CANCELLATION, lines, user, cancels=invoice, due=timezone.localdate())
    if invoice.document_id:
        invoice.document.status = "void"
        invoice.document.save(update_fields=["status"])
    audit.log(user, "invoice", f"Rechnung {invoice.number} storniert durch {storno.number}: {reason}", obj=storno, order=order)
    workflow.refresh_stage(order)
    return storno


@transaction.atomic
def issue_additional_invoice(order, user, lines, kind=Invoice.Kind.ADDITIONAL):
    if not lines:
        raise WorkflowError("Keine Positionen für die Nachberechnung.")
    inv = _create(order, kind, lines, user, due=timezone.localdate() + timedelta(days=CompanySettings.get().payment_due_days))
    audit.log(user, "invoice", f"{inv.get_kind_display()} {inv.number} über {format_euro(inv.total_gross)} erstellt", obj=inv, order=order)
    workflow.refresh_stage(order)
    return inv


@transaction.atomic
def record_payment(order, *, amount, paid_on, method, reference="", note="", user):
    amount = money(amount)
    if amount <= 0:
        raise WorkflowError("Der Betrag muss größer als 0 sein.")
    if paid_on > timezone.localdate():
        raise WorkflowError("Das Zahlungsdatum darf nicht in der Zukunft liegen.")
    if not workflow.active_invoices(order):
        raise WorkflowError("Zahlungen können erst nach dem Erstellen einer Rechnung erfasst werden.")
    balance = workflow.open_balance(order)
    if amount > balance:
        raise WorkflowError(f"Der Betrag übersteigt den offenen Rechnungsbetrag ({format_euro(balance)}).")
    invoice = next((inv for inv in workflow.active_invoices(order) if inv.kind != Invoice.Kind.CANCELLATION), None)
    p = Payment.objects.create(order=order, invoice=invoice, amount=amount, paid_on=paid_on, method=method,
                               reference=reference, note=note, created_by=user)
    audit.log(user, "payment", f"Zahlungseingang {format_euro(amount)} ({p.get_method_display()}) erfasst", obj=p, order=order)
    workflow.refresh_stage(order)
    return p


@transaction.atomic
def record_refund(order, *, amount, paid_on, method, reference="", note="", user):
    amount = money(amount)
    if amount <= 0:
        raise WorkflowError("Der Betrag muss größer als 0 sein.")
    credit = -workflow.open_balance(order)
    if amount > credit:
        raise WorkflowError(f"Es besteht nur ein Guthaben von {format_euro(max(credit, Decimal('0')))}.")
    p = Payment.objects.create(order=order, amount=-amount, paid_on=paid_on, method=method,
                               reference=reference, note=note or "Erstattung", created_by=user)
    audit.log(user, "payment", f"Erstattung {format_euro(amount)} ({p.get_method_display()}) erfasst", obj=p, order=order)
    workflow.refresh_stage(order)
    return p


@transaction.atomic
def delete_payment(payment, user, reason):
    order = payment.order
    if workflow.handover_completed(order):
        raise WorkflowError("Nach der Übergabe können Zahlungen nicht mehr gelöscht werden. Bitte eine Erstattung erfassen.")
    if not (reason or "").strip():
        raise WorkflowError("Bitte einen Grund angeben.")
    audit.log(user, "payment", f"Zahlung über {format_euro(payment.amount)} vom {d(payment.paid_on)} gelöscht: {reason}", order=order)
    payment.delete()
    workflow.refresh_stage(order)
