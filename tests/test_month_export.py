"""Monatsexport für das Steuerbüro."""

import csv
import io
import zipfile
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.billing.export import build_month_export
from apps.billing.models import Invoice
from apps.core.models import AuditLog
from apps.orders import services
from tests.test_workflow import to_paid_invoice


def _zip(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    return z, {n.split("/", 1)[1]: n for n in z.namelist()}


def _rows(z, path):
    text = z.read(path).decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text), delimiter=";"))


def test_export_contains_invoices_payments_deposits_and_pdfs(order, admin, sig):
    inv = to_paid_invoice(order, admin, sig)
    services.cancel_order(order, reason="abgesagt", fee=Decimal("40"), user=admin)
    today = timezone.localdate()
    name, data, stats = build_month_export(today.year, today.month)
    assert name == f"mietly-export-{today:%Y-%m}.zip"
    z, files = _zip(data)
    assert {"Zusammenfassung.txt", "Rechnungsausgangsbuch.csv", "Zahlungen.csv", "Kautionen.csv"} <= set(files)

    invoices = Invoice.objects.filter(order=order)
    assert stats["invoices"] == invoices.count() == 3  # Rechnung, Stornorechnung, Stornogebühr
    pdfs = [k for k in files if k.startswith("Rechnungen/")]
    assert len(pdfs) == 3 and all(z.read(files[p]).startswith(b"%PDF") for p in pdfs)

    rows = _rows(z, files["Rechnungsausgangsbuch.csv"])
    header, body = rows[0], rows[1:]
    assert header[0] == "Rechnungsnummer" and "USt 19 %" in header
    numbers = {r[0] for r in body}
    assert inv.number in numbers and len(body) == 3
    storno = next(r for r in body if r[1] == "Stornorechnung")
    assert storno[header.index("Bezug (storniert Rechnung)")] == inv.number
    assert storno[header.index("Brutto gesamt")].startswith("-")
    # Summe aller Bruttobeträge = Stornogebühr (Rechnung und Storno heben sich auf)
    total = sum(Decimal(r[header.index("Brutto gesamt")].replace(",", ".")) for r in body)
    assert total == Decimal("40.00")

    pay = _rows(z, files["Zahlungen.csv"])
    assert pay[1][1] == "Zahlungseingang" and pay[1][2] == f"{inv.total_gross:.2f}".replace(".", ",")
    dep = _rows(z, files["Kautionen.csv"])
    assert dep[1][1] and len(dep) >= 2

    summary = z.read(files["Zusammenfassung.txt"]).decode("utf-8")
    assert "Monatsexport" in summary and "Anzahl:         3" in summary and "40,00 €" in summary


def test_export_respects_month_boundaries(order, admin, sig):
    inv = to_paid_invoice(order, admin, sig)
    last_month = timezone.localdate().replace(day=1) - timedelta(days=1)
    Invoice.objects.filter(pk=inv.pk).update(issue_date=last_month)
    today = timezone.localdate()
    _, data, stats = build_month_export(today.year, today.month)
    assert stats["invoices"] == 0
    _, data, stats = build_month_export(last_month.year, last_month.month)
    assert stats["invoices"] == 1


def test_export_protects_against_formula_injection(order, admin, sig, customer):
    customer.last_name = "=HYPERLINK(\"x\")"
    customer.save()
    to_paid_invoice(order, admin, sig)
    today = timezone.localdate()
    _, data, _ = build_month_export(today.year, today.month)
    z, files = _zip(data)
    rows = _rows(z, files["Rechnungsausgangsbuch.csv"])
    kunde = rows[1][rows[0].index("Kunde")]
    assert not kunde.startswith("=")


def test_export_view_admin_only_and_logged(client, order, admin, staff, sig):
    to_paid_invoice(order, admin, sig)
    month = timezone.localdate().strftime("%Y-%m")
    client.force_login(staff)
    assert client.get(f"/rechnungen/monatsexport/?monat={month}").status_code == 403
    client.force_login(admin)
    r = client.get(f"/rechnungen/monatsexport/?monat={month}")
    assert r.status_code == 200 and r["Content-Type"] == "application/zip"
    assert "attachment" in r["Content-Disposition"]
    assert AuditLog.objects.filter(action="export").exists()
    html = client.get("/rechnungen/").content.decode()
    assert "Monatsexport fürs Steuerbüro" in html


def test_export_view_rejects_invalid_month(client, admin):
    client.force_login(admin)
    for value in ["", "2026-13", "abc", "1999-01"]:
        r = client.get(f"/rechnungen/monatsexport/?monat={value}")
        assert r.status_code == 302


def test_empty_month_gives_valid_archive(db, company):
    _, data, stats = build_month_export(2026, 1)
    z, files = _zip(data)
    assert stats["invoices"] == 0 and "Zusammenfassung.txt" in files
