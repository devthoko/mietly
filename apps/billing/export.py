"""Monatsexport für das Steuerbüro.

Ein ZIP-Archiv je Monat mit
  * allen Rechnungs-PDFs (Rechnung, Nachberechnung, Stornogebühr, Stornorechnung),
  * dem Rechnungsausgangsbuch (CSV, mit Aufschlüsselung je Steuersatz),
  * allen Zahlungseingängen und Erstattungen (CSV),
  * allen Kautionsbewegungen (CSV) – Kautionen sind kein Umsatz, einbehaltene
    Beträge aber als Schadensersatz relevant,
  * einer Zusammenfassung zum Lesen (TXT).

Die CSV-Dateien nutzen Semikolon, Komma als Dezimaltrennzeichen und UTF-8 mit
BOM – so öffnen Excel und LibreOffice sie direkt richtig.
"""

import calendar
import csv
import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core.models import CompanySettings
from apps.orders.models import DepositTransaction

from .models import Invoice, Payment

ZERO = Decimal("0.00")
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _cell(value):
    """Schutz vor Formel-Injection beim Öffnen in Excel/LibreOffice."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _num(value):
    return f"{Decimal(value):.2f}".replace(".", ",")


def _rate_label(rate):
    rate = Decimal(rate)
    return format(rate.normalize(), "f").replace(".", ",") + " %"  # 19.0 → „19 %“, 7.5 → „7,5 %“


def _csv_bytes(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(header)
    for row in rows:
        w.writerow(row)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def month_range(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def available_months(limit=36):
    """Monate mit Belegen oder Zahlungen, neueste zuerst (für die Auswahl)."""
    months = set()
    for d in Invoice.objects.dates("issue_date", "month"):
        months.add((d.year, d.month))
    for d in Payment.objects.dates("paid_on", "month"):
        months.add((d.year, d.month))
    for d in DepositTransaction.objects.dates("date", "month"):
        months.add((d.year, d.month))
    today = timezone.localdate()
    months.add((today.year, today.month))
    prev = today.replace(day=1) - timedelta(days=1)
    months.add((prev.year, prev.month))  # Vormonat ist der übliche Exportmonat
    return [{"value": f"{y}-{m:02d}", "label": f"{MONTHS[m - 1]} {y}"} for y, m in sorted(months, reverse=True)[:limit]]


def build_month_export(year, month):
    """Gibt (Dateiname, ZIP-Bytes, Kennzahlen) zurück."""
    start, end = month_range(year, month)
    company = CompanySettings.get()
    folder = f"mietly-export-{year}-{month:02d}"
    label = f"{MONTHS[month - 1]} {year}"

    invoices = list(
        Invoice.objects.filter(issue_date__range=(start, end))
        .select_related("order", "order__customer", "document", "cancels", "cancelled_by")
        .order_by("issue_date", "number")
    )
    payments = list(
        Payment.objects.filter(paid_on__range=(start, end))
        .select_related("order", "order__customer", "invoice").order_by("paid_on", "id")
    )
    deposits = list(
        DepositTransaction.objects.filter(date__range=(start, end))
        .select_related("order", "order__customer").order_by("date", "id")
    )

    # Steuersätze, die in diesem Monat vorkommen (höchster zuerst)
    rates = sorted({Decimal(b["rate"]) for inv in invoices for b in (inv.vat_breakdown or [])}, reverse=True)

    # ---------- Rechnungsausgangsbuch ----------
    header = ["Rechnungsnummer", "Art", "Rechnungsdatum", "Leistungszeitraum", "Fällig am", "Kundennummer", "Kunde",
              "Auftrag", "Veranstaltung", "Bezug (storniert Rechnung)", "Storniert durch"]
    for r in rates:
        header += [f"Netto {_rate_label(r)}", f"USt {_rate_label(r)}"]
    header += ["Netto gesamt", "USt gesamt", "Brutto gesamt", "Kleinunternehmer (§ 19 UStG)", "PDF-Datei"]
    sums = {"net": ZERO, "vat": ZERO, "gross": ZERO}
    per_rate = {r: {"net": ZERO, "vat": ZERO, "gross": ZERO} for r in rates}
    rows = []
    pdfs = []
    for inv in invoices:
        c = inv.order.customer
        breakdown = {Decimal(b["rate"]): b for b in (inv.vat_breakdown or [])}
        pdf_name = ""
        if inv.document_id and inv.document.file:
            pdf_name = inv.document.filename
            pdfs.append((pdf_name, inv.document.file))
        row = [
            inv.number, inv.get_kind_display(), inv.issue_date.strftime("%d.%m.%Y"), _cell(inv.service_period),
            inv.due_date.strftime("%d.%m.%Y"), c.number if c else "", _cell(c.full_name if c else ""),
            inv.order.number, _cell(inv.order.event_name), inv.cancels.number if inv.cancels_id else "",
            inv.cancelled_by.number if inv.is_cancelled else "",
        ]
        for r in rates:
            b = breakdown.get(r)
            row += [_num(b["net"]) if b else "", _num(b["vat"]) if b else ""]
            if b:
                per_rate[r]["net"] += Decimal(b["net"])
                per_rate[r]["vat"] += Decimal(b["vat"])
                per_rate[r]["gross"] += Decimal(b["gross"])
        row += [_num(inv.total_net), _num(inv.total_vat), _num(inv.total_gross), "ja" if inv.small_business else "nein",
                f"Rechnungen/{pdf_name}" if pdf_name else "fehlt"]
        rows.append(row)
        sums["net"] += inv.total_net
        sums["vat"] += inv.total_vat
        sums["gross"] += inv.total_gross

    invoice_csv = _csv_bytes(header, rows)

    # ---------- Zahlungen ----------
    pay_rows = []
    received = refunded = ZERO
    for p in payments:
        c = p.order.customer
        if p.amount >= 0:
            received += p.amount
        else:
            refunded += -p.amount
        pay_rows.append([
            p.paid_on.strftime("%d.%m.%Y"), "Erstattung" if p.amount < 0 else "Zahlungseingang", _num(p.amount),
            p.get_method_display(), p.invoice.number if p.invoice_id else "", p.order.number,
            c.number if c else "", _cell(c.full_name if c else ""), _cell(p.reference), _cell(p.note),
        ])
    payment_csv = _csv_bytes(
        ["Datum", "Vorgang", "Betrag", "Zahlungsart", "Rechnung", "Auftrag", "Kundennummer", "Kunde", "Referenz", "Notiz"], pay_rows
    )

    # ---------- Kautionen ----------
    dep_rows = []
    dep_sums = {"received": ZERO, "retained": ZERO, "refunded": ZERO}
    for t in deposits:
        c = t.order.customer
        dep_sums[t.kind] = dep_sums.get(t.kind, ZERO) + t.amount
        dep_rows.append([
            t.date.strftime("%d.%m.%Y"), t.get_kind_display(), _num(t.amount), t.get_method_display(), t.order.number,
            c.number if c else "", _cell(c.full_name if c else ""), _cell(t.reason),
        ])
    deposit_csv = _csv_bytes(["Datum", "Vorgang", "Betrag", "Zahlungsart", "Auftrag", "Kundennummer", "Kunde", "Begründung"], dep_rows)

    # ---------- Zusammenfassung ----------
    def eur(v):
        return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    by_kind = {}
    for inv in invoices:
        by_kind.setdefault(inv.get_kind_display(), [0, ZERO])
        by_kind[inv.get_kind_display()][0] += 1
        by_kind[inv.get_kind_display()][1] += inv.total_gross

    lines = [
        f"mietly – Monatsexport {label}",
        "=" * 40,
        "",
        f"Betrieb:        {company.name}",
        f"Anschrift:      {company.address_line}",
        f"Steuernummer:   {company.tax_number or '—'}",
        f"USt-IdNr.:      {company.vat_id or '—'}",
        f"Besteuerung:    {'Kleinunternehmer nach § 19 UStG' if company.small_business else 'Regelbesteuerung'}",
        f"Zeitraum:       {start:%d.%m.%Y} – {end:%d.%m.%Y}",
        f"Erstellt am:    {timezone.localtime():%d.%m.%Y, %H:%M} Uhr",
        "",
        "RECHNUNGEN",
        "----------",
        f"Anzahl:         {len(invoices)}",
    ]
    for kind, (n, total) in by_kind.items():
        lines.append(f"  {kind + ':':<22}{n:>3}   {eur(total):>14}")
    lines += ["", f"{'Netto gesamt:':<24}{eur(sums['net']):>16}", f"{'Umsatzsteuer gesamt:':<24}{eur(sums['vat']):>16}",
              f"{'Brutto gesamt:':<24}{eur(sums['gross']):>16}", ""]
    if rates:
        lines.append("Aufschlüsselung nach Steuersatz (Stornorechnungen sind als negative Beträge enthalten):")
        for r in rates:
            v = per_rate[r]
            note = "  (nicht steuerbarer Schadensersatz bzw. steuerfrei)" if r == 0 and not company.small_business else ""
            lines.append(f"  {_rate_label(r):>6}:  Netto {eur(v['net']):>14}   USt {eur(v['vat']):>12}   Brutto {eur(v['gross']):>14}{note}")
        lines.append("")
    lines += [
        "ZAHLUNGEN",
        "---------",
        f"{'Zahlungseingänge:':<24}{eur(received):>16}",
        f"{'Erstattungen:':<24}{eur(refunded):>16}",
        f"{'Saldo:':<24}{eur(received - refunded):>16}",
        "",
        "KAUTIONEN (kein Umsatz)",
        "-----------------------",
        f"{'Erhalten:':<24}{eur(dep_sums['received']):>16}",
        f"{'Einbehalten:':<24}{eur(dep_sums['retained']):>16}   (für Schäden/Fehlmengen verrechnet)",
        f"{'Zurückgezahlt:':<24}{eur(dep_sums['refunded']):>16}",
        "",
        "INHALT",
        "------",
        "Rechnungsausgangsbuch.csv   alle Rechnungen des Monats mit Steueraufschlüsselung",
        "Zahlungen.csv               Zahlungseingänge und Erstattungen (nach Zahlungsdatum)",
        "Kautionen.csv               Kautionen: erhalten, einbehalten, zurückgezahlt",
        "Rechnungen/                 die Rechnungen als PDF (unveränderte Originale)",
        "",
        "Rechnungen sind nach dem Rechnungsdatum, Zahlungen nach dem Zahlungsdatum dem Monat zugeordnet.",
    ]
    summary = ("\r\n".join(lines) + "\r\n").encode("utf-8")

    # ---------- ZIP ----------
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{folder}/Zusammenfassung.txt", summary)
        z.writestr(f"{folder}/Rechnungsausgangsbuch.csv", invoice_csv)
        z.writestr(f"{folder}/Zahlungen.csv", payment_csv)
        z.writestr(f"{folder}/Kautionen.csv", deposit_csv)
        for name, f in pdfs:
            with f.open("rb") as fh:
                z.writestr(f"{folder}/Rechnungen/{name}", fh.read())
    stats = {"invoices": len(invoices), "payments": len(payments), "deposits": len(deposits), "gross": sums["gross"]}
    return f"{folder}.zip", out.getvalue(), stats
