"""Werte für die Platzhalter in Vorlagen."""

from decimal import Decimal

from django.utils import timezone

from apps.core.models import CompanySettings
from apps.core.templatetags.ui import d, dtlong, format_euro

ZERO = Decimal("0.00")


def greeting(customer, company=None):
    """Briefanrede ohne abschließendes Komma, je nach Einstellung förmlich oder persönlich."""
    company = company or CompanySettings.get()
    if customer is None:
        return "Guten Tag"
    if company.mail_greeting == "informal" and customer.first_name:
        return f"Hallo {customer.first_name}"
    if customer.salutation == "Frau":
        return f"Sehr geehrte Frau {customer.last_name}"
    if customer.salutation == "Herr":
        return f"Sehr geehrter Herr {customer.last_name}"
    return f"Guten Tag {customer.full_name}"


def contact_line(company):
    parts = []
    if company.phone:
        parts.append(f"Tel. {company.phone}")
    if company.email:
        parts.append(company.email)
    return " · ".join(parts)


def placeholder_context(order, **extra):
    company = CompanySettings.get()
    ctx = {
        "firma.name": company.name,
        "firma.adresse": ", ".join(p for p in [company.street, f"{company.zip_code} {company.city}".strip()] if p),
        "firma.inhaber": company.owner,
        "firma.telefon": company.phone,
        "firma.email": company.email,
        "firma.kontakt": contact_line(company),
        "stornobedingungen": company.cancellation_terms,
        "steuer.hinweis": " (gemäß § 19 UStG ohne Ausweis von Umsatzsteuer)" if company.small_business else " inklusive gesetzlicher Umsatzsteuer",
        "dokument.datum": d(timezone.localdate()),
    }
    if order is None:
        # Beispieldaten für die Vorschau im Vorlageneditor
        ctx.update({
            "kunde.name": "Anna Beispiel", "kunde.anrede": "Anna",
            "kunde.briefanrede": "Hallo Anna" if company.mail_greeting == "informal" else "Sehr geehrte Frau Beispiel",
            "kunde.adresse": "Musterweg 1, 12345 Musterstadt",
            "kunde.email": "anna@example.de", "kunde.telefon": "0151 2345678", "kunde.nummer": "K-00001",
            "auftrag.nummer": "AU-2026-0001", "auftrag.event": "Hochzeit Anna & Ben", "auftrag.eventdatum": "Sa, 12.09.2026",
            "auftrag.ort": "Gut Sonnenhof", "auftrag.art": "Lieferung", "auftrag.uebergabe": "Fr, 11.09.2026, 14:00 Uhr",
            "auftrag.rueckgabe": "Mo, 14.09.2026, 10:00 Uhr", "auftrag.summe": "1.240,00 €",
            "angebot.nummer": "AN-2026-0001", "angebot.gueltig_bis": "30.06.2026",
            "kaution.betrag": "300,00 €",
            "kaution.text": "Der Mieter leistet vor der Übergabe eine Kaution in Höhe von 300,00 €. Sie wird nach ordnungsgemäßer Rückgabe erstattet; berechtigte Forderungen aus Schäden oder Fehlmengen werden verrechnet.",
            "kaution.satz": " und die Kaution eingegangen ist",
            "dokument.nummer": "RE-2026-0001", "rechnung.betrag": "1.240,00 €", "rechnung.faellig": "04.09.2026",
            "rechnung.storniert": "RE-2026-0001",
            "zahlung.hinweis": "Bitte überweisen Sie den Betrag von 1.240,00 € bis zum 04.09.2026 unter Angabe der Rechnungsnummer RE-2026-0001.",
            "kaution.abrechnung": "Von Ihrer Kaution über 300,00 € haben wir 40,00 € für die im Rücknahmeprotokoll aufgeführten Schäden einbehalten. Den Restbetrag von 260,00 € zahlen wir Ihnen zurück.",
            "ruecknahme.ergebnis": "Alle Gegenstände wurden vollständig und ohne Beanstandung zurückgegeben.",
        })
        ctx.update(extra)
        return ctx

    c = order.customer
    deposit = order.deposit_amount
    if deposit > 0:
        deposit_text = (
            f"Der Mieter leistet vor der Übergabe eine Kaution in Höhe von {format_euro(deposit)}. "
            "Sie wird nach ordnungsgemäßer Rückgabe erstattet; berechtigte Forderungen aus Schäden "
            "oder Fehlmengen werden verrechnet. Über die Verrechnung erhält der Mieter eine Abrechnung."
        )
        deposit_clause = " und die Kaution eingegangen ist" if company.deposit_required_before_handover else ""
    else:
        deposit_text = "Eine Kaution ist nicht vereinbart."
        deposit_clause = ""
    ctx.update({
        "kunde.name": c.full_name if c else "",
        "kunde.anrede": c.first_name if c else "",
        "kunde.briefanrede": greeting(c, company),
        "kunde.adresse": c.address_inline if c else "",
        "kunde.email": c.email if c else "",
        "kunde.telefon": c.phone if c else "",
        "kunde.nummer": c.number if c else "",
        "auftrag.nummer": order.number,
        "auftrag.event": order.event_name,
        "auftrag.eventdatum": d(order.event_date),
        "auftrag.ort": order.event_location,
        "auftrag.art": order.get_fulfillment_display(),
        "auftrag.uebergabe": dtlong(order.handover_at),
        "auftrag.rueckgabe": dtlong(order.return_at),
        "auftrag.summe": format_euro(order.total),
        "kaution.betrag": format_euro(deposit),
        "kaution.text": deposit_text,
        "kaution.satz": deposit_clause,
        "zahlung.hinweis": "",
        "kaution.abrechnung": "",
        "ruecknahme.ergebnis": "",
        "rechnung.storniert": "",
    })
    from apps.orders.workflow import current_document, main_invoice

    offer = current_document(order, "offer")
    ctx["angebot.nummer"] = offer.number if offer else ""
    ctx["angebot.gueltig_bis"] = offer.data.get("valid_until", "") if offer else ""
    inv = main_invoice(order)
    if inv:
        ctx["rechnung.betrag"] = format_euro(inv.total_gross)
        ctx["rechnung.faellig"] = d(inv.due_date)
    ctx.update(extra)
    return ctx


# --------------------------------------------------------------------------
# Automatische Sätze für Rechnungen und E-Mails
# --------------------------------------------------------------------------

def payment_note(inv):
    """Was der Kunde zu dieser Rechnung tun muss – abhängig vom Saldo des Auftrags."""
    from apps.orders.workflow import open_balance, paid_total

    order = inv.order
    balance = open_balance(order)
    paid = paid_total(order)
    if inv.kind == "cancellation":
        if balance < 0:
            return f"Bereits geleistete Zahlungen werden verrechnet. Ihr Guthaben von {format_euro(-balance)} erstatten wir Ihnen in den nächsten Tagen."
        if balance > 0:
            return f"Nach Verrechnung mit Ihren Zahlungen ist noch ein Betrag von {format_euro(balance)} offen; dazu erhalten Sie eine gesonderte Rechnung."
        if paid > 0:
            return "Ihre bisherigen Zahlungen sind damit vollständig verrechnet."
        return "Es ist keine Zahlung erforderlich."
    if balance <= 0:
        if balance < 0:
            return (f"Der Betrag wird mit Ihren bisherigen Zahlungen verrechnet. "
                    f"Das verbleibende Guthaben von {format_euro(-balance)} erstatten wir Ihnen in den nächsten Tagen.")
        if paid > 0:
            return "Der Betrag ist mit Ihren bisherigen Zahlungen bereits vollständig verrechnet."
        return "Der Betrag ist bereits beglichen."
    amount = format_euro(balance)
    if balance == inv.total_gross:
        return f"Bitte überweisen Sie den Betrag von {amount} bis zum {d(inv.due_date)} unter Angabe der Rechnungsnummer {inv.number}."
    return (f"Nach Verrechnung mit Ihren bisherigen Zahlungen ist noch ein Betrag von {amount} offen. "
            f"Bitte überweisen Sie ihn bis zum {d(inv.due_date)} unter Angabe der Rechnungsnummer {inv.number}.")


def invoice_context(inv):
    return {
        "dokument.nummer": inv.number,
        "rechnung.betrag": format_euro(inv.total_gross),
        "rechnung.faellig": d(inv.due_date),
        "rechnung.storniert": inv.cancels.number if inv.cancels_id else "",
        "zahlung.hinweis": payment_note(inv),
    }


def followup_invoices(order):
    """Nachberechnungen, die noch wirksam sind (nicht storniert)."""
    return [inv for inv in order.invoices.filter(kind="additional").order_by("id") if inv.is_active]


def deposit_summary(order):
    """Ergebnis der Kautionsabrechnung in ganzen Sätzen."""
    from apps.orders.workflow import deposit_state, open_balance

    dep = deposit_state(order)
    sentences = []
    if dep.received > 0:
        if dep.retained > 0:
            sentences.append(
                f"Von Ihrer Kaution über {format_euro(dep.received)} haben wir {format_euro(dep.retained)} "
                f"für die im Rücknahmeprotokoll aufgeführten Schäden bzw. Fehlmengen einbehalten."
            )
            if dep.refunded > 0:
                sentences.append(f"Den Restbetrag von {format_euro(dep.refunded)} zahlen wir Ihnen zurück.")
            else:
                sentences.append("Die Kaution wurde damit vollständig verrechnet.")
        elif dep.refunded > 0:
            sentences.append(f"Ihre Kaution über {format_euro(dep.refunded)} zahlen wir Ihnen vollständig zurück.")
    for inv in followup_invoices(order):
        sentences.append(
            f"Die Kosten, die über die Kaution hinausgehen, stellen wir Ihnen mit der Rechnung {inv.number} "
            f"über {format_euro(inv.total_gross)} gesondert in Rechnung."
        )
    balance = open_balance(order)
    if balance > 0:
        sentences.append(f"Insgesamt ist noch ein Betrag von {format_euro(balance)} offen.")
    elif balance < 0:
        sentences.append(f"Ihr Guthaben von {format_euro(-balance)} erstatten wir Ihnen.")
    return " ".join(sentences)


def return_summary(order):
    damages = list(order.damages.select_related("article"))
    if not damages:
        return "Alle Gegenstände wurden vollständig und ohne Beanstandung zurückgegeben."
    lines = ["Dabei haben wir Folgendes festgestellt:"]
    for dm in damages:
        amount = f" ({format_euro(dm.amount)})" if dm.amount else ""
        lines.append(f"- {dm.description}{amount}")
    lines.append("Die Abrechnung erhalten Sie mit der Kautionsabrechnung.")
    return "\n".join(lines)


def mail_context(doc):
    """Platzhalter für die E-Mail zu einem Dokument."""
    order = doc.order
    extra = {"dokument.nummer": doc.number}
    inv = getattr(doc, "invoice", None) if doc.kind == "invoice" else None
    if inv is not None:
        extra.update(invoice_context(inv))
    if doc.kind == "return":
        extra["ruecknahme.ergebnis"] = return_summary(order)
    if doc.kind == "deposit":
        extra["kaution.abrechnung"] = deposit_summary(order)
    return placeholder_context(order, **extra)


def mail_template_key(doc):
    if doc.kind == "offer":
        return "mail_offer_signed" if doc.is_signed else "mail_offer"
    if doc.kind == "contract":
        return "mail_contract_signed" if doc.is_signed else "mail_contract"
    if doc.kind == "invoice":
        inv = getattr(doc, "invoice", None)
        kind = inv.kind if inv is not None else "invoice"
        return {"additional": "mail_additional", "fee": "mail_fee", "cancellation": "mail_cancellation"}.get(kind, "mail_invoice")
    return {"handover": "mail_handover", "return": "mail_return", "deposit": "mail_deposit"}.get(doc.kind)
