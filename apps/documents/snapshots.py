"""Eingefrorene Dokumentdaten.

Jedes Dokument wird aus einem unveränderlichen Datensatz (JSON) erzeugt, der
beim Erstellen festgehalten wird. Spätere Änderungen an Kunde, Artikel oder
Vorlagen verändern bereits erstellte Dokumente daher nicht; auch die
unterschriebene Fassung entsteht aus genau diesen Daten.
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.billing.calc import totals
from apps.core.models import CompanySettings, TextTemplate
from apps.core.templatetags.ui import d, dtlong, format_euro, percent, qty
from apps.core.textrender import render_html

from .context import followup_invoices, invoice_context, payment_note, placeholder_context


def _company():
    c = CompanySettings.get()
    return {
        "name": c.name,
        "owner": c.owner,
        "street": c.street,
        "city_line": f"{c.zip_code} {c.city}".strip(),
        "phone": c.phone,
        "email": c.email,
        "website": c.website,
        "logo": c.logo.path if c.logo else "",
        "tax_number": c.tax_number,
        "vat_id": c.vat_id,
        "bank_name": c.bank_name,
        "iban": " ".join(c.iban[i:i + 4] for i in range(0, len(c.iban), 4)) if c.iban else "",
        "bic": c.bic,
        "account_holder": c.account_holder or c.name,
        "small_business": c.small_business,
        "address_line": c.address_line,
    }


def _customer(order):
    c = order.customer
    return {
        "number": c.number,
        "name": c.full_name,
        "salutation": c.salutation,
        "lines": c.address_lines,
        "email": c.email,
        "phone": c.phone,
    }


def _order(order):
    return {
        "number": order.number,
        "event": order.event_name,
        "event_date": d(order.event_date),
        "location": order.event_location,
        "fulfillment": order.get_fulfillment_display(),
        "delivery": order.fulfillment == order.Fulfillment.DELIVERY,
        "delivery_address": order.delivery_address,
        "handover": dtlong(order.handover_at),
        "return": dtlong(order.return_at),
        "rental_days": order.rental_days,
        "customer_note": order.customer_note,
        "deposit": format_euro(order.deposit_amount) if order.deposit_amount else "",
    }


def _items(order):
    company = CompanySettings.get()
    rows = []
    pos = 0
    for item in order.items.select_related("article", "package").prefetch_related("package__items__article"):
        pos += 1
        contents = []
        if item.package_id:
            contents = [f"{pi.quantity}× {pi.article.name}" for pi in item.package.items.all()]
        rows.append({
            "pos": pos,
            "description": item.description,
            "detail": item.detail,
            "contents": contents,
            "quantity": item.quantity,
            "unit_price": format_euro(item.unit_price),
            "discount": percent(item.discount_percent) if item.discount_percent else "",
            "vat_rate": "0" if company.small_business else str(item.vat_rate),
            "total": format_euro(item.total),
            "_total": str(item.total),
        })
    return rows


def _totals(pairs, small_business):
    t = totals(pairs, small_business)
    return {
        "gross": format_euro(t["gross"]),
        "net": format_euro(t["net"]),
        "vat": format_euro(t["vat"]),
        "breakdown": [
            {"rate": percent(Decimal(b["rate"])), "net": format_euro(Decimal(b["net"])), "vat": format_euro(Decimal(b["vat"])), "gross": format_euro(Decimal(b["gross"]))}
            for b in t["breakdown"] if Decimal(b["rate"]) > 0
        ],
        "_gross": str(t["gross"]),
    }


def _text(key, ctx, versions):
    tpl = TextTemplate.current(key)
    versions[key] = tpl.version
    return str(render_html(tpl.body, ctx))


def base(order, kind_title, number, version=1):
    return {
        "title": kind_title,
        "number": number,
        "version": version,
        "date": d(timezone.localdate()),
        "company": _company(),
        "customer": _customer(order),
        "order": _order(order),
    }


def offer(order, number, version):
    company = CompanySettings.get()
    versions = {}
    valid_until = d(timezone.localdate() + timedelta(days=company.offer_valid_days))
    ctx = placeholder_context(order, **{"dokument.nummer": number, "angebot.nummer": number, "angebot.gueltig_bis": valid_until})
    data = base(order, "Angebot", number, version)
    items = order.items.all()
    data.update({
        "items": _items(order),
        "totals": _totals([(i.total, i.vat_rate) for i in items], company.small_business),
        "valid_until": valid_until,
        "intro": _text("offer_intro", ctx, versions),
        "outro": _text("offer_outro", ctx, versions),
        "terms": _text("terms", ctx, versions),
        "signature_label": "Angebot angenommen – Unterschrift Mieter/in",
    })
    return data, versions


def contract(order, number, version):
    company = CompanySettings.get()
    versions = {}
    ctx = placeholder_context(order, **{"dokument.nummer": number})
    data = base(order, "Mietvertrag", number, version)
    items = list(order.items.all())
    replacement = []
    for article, count in sorted(order.article_quantities().items(), key=lambda x: x[0].name):
        replacement.append({"name": article.name, "quantity": count, "value": format_euro(article.replacement_value)})
    data.update({
        "items": _items(order),
        "totals": _totals([(i.total, i.vat_rate) for i in items], company.small_business),
        "contract": _text("contract", ctx, versions),
        "terms": _text("terms", ctx, versions),
        "withdrawal": _text("withdrawal", ctx, versions),
        "privacy": _text("privacy", ctx, versions),
        "replacement": replacement,
        "signature_label": "Unterschrift Mieter/in",
    })
    return data, versions


INVOICE_TITLES = {"invoice": "Rechnung", "additional": "Nachberechnung", "fee": "Stornogebühr", "cancellation": "Stornorechnung"}


def _invoice_outro(inv, ctx, versions):
    if inv.kind == "cancellation":
        return ""
    if inv.kind == "invoice":
        return _text("invoice_outro", ctx, versions)
    # Nachberechnung und Stornogebühr: keine Übergabe mehr, Zahlungen werden verrechnet
    return _text("invoice_outro_followup", ctx, versions)


def invoice(inv):
    order = inv.order
    versions = {}
    data = base(order, INVOICE_TITLES[inv.kind], inv.number)
    ctx = placeholder_context(order, **invoice_context(inv))
    data["date"] = d(inv.issue_date)
    lines = []
    for line in inv.lines.all():
        lines.append({
            "pos": line.position, "description": line.description, "detail": line.detail,
            "quantity": qty(line.quantity), "unit_price": format_euro(line.unit_price),
            "discount": percent(line.discount_percent) if line.discount_percent else "",
            "vat_rate": str(line.vat_rate), "total": format_euro(line.total), "contents": [],
        })
    data.update({
        "kind": inv.kind,
        "items": lines,
        "totals": _totals([(l.total, l.vat_rate) for l in inv.lines.all()], inv.small_business),
        "service_period": inv.service_period,
        "due_date": d(inv.due_date),
        "cancels": inv.cancels.number if inv.cancels_id else "",
        "cancels_date": d(inv.cancels.issue_date) if inv.cancels_id else "",
        "outro": _invoice_outro(inv, ctx, versions),
        "period_label": "Leistungsdatum" if inv.kind == "fee" else "Leistungszeitraum",
        "payment_note": payment_note(inv) if inv.kind == "cancellation" else "",
        "small_business": inv.small_business,
        "has_tax_free_damages": any(l.vat_rate == 0 for l in inv.lines.all()) and not inv.small_business,
    })
    return data, versions


def packing_list(order, number, version):
    data = base(order, "Packliste", number, version)
    groups = {}
    for article, count in order.article_quantities().items():
        cat = article.category.name if article.category else "Ohne Kategorie"
        groups.setdefault(cat, []).append({
            "number": article.number, "name": article.name, "quantity": count,
            "location": article.storage_location, "image": article.image.path if article.image else "",
        })
    data["groups"] = [{"name": k, "items": sorted(v, key=lambda x: x["name"])} for k, v in sorted(groups.items())]
    data["packages"] = [
        {"name": i.package.name, "quantity": i.quantity, "contents": [f"{pi.quantity * i.quantity}× {pi.article.name}" for pi in i.package.items.all()]}
        for i in order.items.filter(package__isnull=False).select_related("package").prefetch_related("package__items__article")
    ]
    data["total_pieces"] = sum(qty for qty in order.article_quantities().values())
    return data, {}


def _photos(order, stage):
    return [{"path": p.image.path, "caption": p.caption, "article": p.article.name if p.article else ""} for p in order.photos.filter(stage=stage)]


def handover(order, number, version):
    versions = {}
    ctx = placeholder_context(order)
    h = order.handover
    data = base(order, "Übergabeprotokoll", number, version)
    data.update({
        "performed_at": dtlong(h.performed_at),
        "performed_by": h.performed_by.display_name if h.performed_by else "",
        "recipient": h.recipient_name,
        "notes": h.notes,
        "items": [
            {"name": i.article.name, "number": i.article.number, "planned": i.planned_qty, "quantity": i.quantity,
             "condition": i.get_condition_display(), "damage": i.existing_damage, "note": i.note, "deviation": i.quantity != i.planned_qty}
            for i in h.items.select_related("article")
        ],
        "photos": _photos(order, "handover"),
        "confirm": _text("handover_confirm", ctx, versions),
        "signature_label": "Erhalten – Unterschrift Mieter/in",
    })
    return data, versions


def return_protocol(order, number, version):
    r = order.return_record
    data = base(order, "Rücknahmeprotokoll", number, version)
    data.update({
        "performed_at": dtlong(r.performed_at),
        "performed_by": r.performed_by.display_name if r.performed_by else "",
        "returned_by": r.returned_by_name,
        "notes": r.notes,
        "items": [
            {"name": i.article.name, "number": i.article.number, "expected": i.expected_qty, "returned": i.returned_qty,
             "damaged": i.damaged_qty, "missing": i.missing_qty, "condition": i.get_condition_display(), "note": i.note}
            for i in r.items.select_related("article")
        ],
        "damages": [
            {"kind": dm.get_kind_display(), "article": dm.article.name if dm.article else "", "quantity": dm.quantity,
             "description": dm.description, "amount": format_euro(dm.amount)}
            for dm in order.damages.select_related("article")
        ],
        "damages_total": format_euro(sum((dm.amount for dm in order.damages.all()), Decimal("0"))),
        "photos": _photos(order, "return"),
    })
    return data, {}


def deposit_statement(order, number, version):
    from apps.orders.workflow import deposit_state, open_balance

    from .context import deposit_summary

    dep = deposit_state(order)
    data = base(order, "Kautionsabrechnung", number, version)
    data.update({
        "agreed": format_euro(dep.agreed),
        "received": format_euro(dep.received),
        "retained": format_euro(dep.retained),
        "refunded": format_euro(dep.refunded),
        "transactions": [
            {"date": d(t.date), "kind": t.get_kind_display(), "amount": format_euro(t.amount), "method": t.get_method_display(), "reason": t.reason}
            for t in order.deposit_transactions.all()
        ],
        "followups": [
            {"number": inv.number, "title": inv.get_kind_display(), "amount": format_euro(inv.total_gross), "due": d(inv.due_date)}
            for inv in followup_invoices(order)
        ],
        "open_balance": format_euro(open_balance(order)) if open_balance(order) > 0 else "",
        "summary": deposit_summary(order),
    })
    return data, {}
