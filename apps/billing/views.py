import csv
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone


from .models import Invoice, Payment


def invoice_list(request):
    from django.db.models import DecimalField, OuterRef, Subquery, Value
    from django.db.models.functions import Coalesce

    # Zahlungsstand je Auftrag per Unterabfrage statt mehrerer Abfragen pro Zeile
    dec = DecimalField(max_digits=12, decimal_places=2)
    paid_sq = Payment.objects.filter(order=OuterRef("order")).order_by().values("order").annotate(s=Sum("amount")).values("s")
    inv_sq = (Invoice.objects.filter(order=OuterRef("order"), cancelled_by__isnull=True).exclude(kind=Invoice.Kind.CANCELLATION)
              .order_by().values("order").annotate(s=Sum("total_gross")).values("s"))
    qs = (Invoice.objects.select_related("order", "order__customer", "document", "cancels", "cancelled_by")
          .annotate(_order_paid=Coalesce(Subquery(paid_sq, output_field=dec), Value(Decimal("0"))),
                    _order_invoiced=Coalesce(Subquery(inv_sq, output_field=dec), Value(Decimal("0")))))
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    year = request.GET.get("jahr", "")
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(order__number__icontains=q) | Q(order__customer__last_name__icontains=q) | Q(order__event_name__icontains=q))
    if year.isdigit():
        qs = qs.filter(issue_date__year=int(year))
    qs = qs.order_by("-issue_date", "-id")

    def row(inv):
        paid = None
        if inv.kind == Invoice.Kind.INVOICE and inv.is_active:
            paid = inv._order_paid >= inv.total_gross
        elif inv.is_active:
            paid = inv._order_invoiced - inv._order_paid <= 0
        return {"inv": inv, "paid": paid}

    export = request.GET.get("export") == "csv"
    if status == "offen" or export:
        # Status wird für alle Rechnungen benötigt (Filter bzw. Export)
        rows = [row(inv) for inv in qs]
        if status == "offen":
            rows = [r for r in rows if r["inv"].is_active and r["paid"] is False]
        if export:
            return _csv(rows)
        page = Paginator(rows, 50).get_page(request.GET.get("seite"))
        totals = {
            "gross": sum((r["inv"].total_gross for r in rows), Decimal("0")),
            "vat": sum((r["inv"].total_vat for r in rows), Decimal("0")),
        }
    else:
        # Nur die angezeigte Seite einzeln auswerten, Summen direkt in der Datenbank
        page = Paginator(qs, 50).get_page(request.GET.get("seite"))
        page.object_list = [row(inv) for inv in page.object_list]
        agg = qs.aggregate(gross=Sum("total_gross"), vat=Sum("total_vat"))
        totals = {"gross": agg["gross"] or Decimal("0"), "vat": agg["vat"] or Decimal("0")}
    years = sorted({d.year for d in Invoice.objects.dates("issue_date", "year")}, reverse=True)
    from datetime import timedelta

    from .export import available_months

    last_month = (timezone.localdate().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    return render(request, "billing/list.html", {"page": page, "q": q, "status": status, "year": year, "years": years, "totals": totals, "export_months": available_months(), "default_month": last_month})


def _cell(value):
    """Schutz vor Formel-Injection beim Öffnen in Excel/LibreOffice."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _csv(rows):
    """Export für die Buchhaltung bzw. das Steuerbüro."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="rechnungen.csv"'
    response.write("﻿")
    w = csv.writer(response, delimiter=";")
    w.writerow(["Rechnungsnummer", "Art", "Datum", "Auftrag", "Kunde", "Netto", "USt", "Brutto", "Storniert durch", "Bezahlt"])
    for r in rows:
        inv = r["inv"]
        fmt = lambda v: f"{v:.2f}".replace(".", ",")  # noqa: E731
        w.writerow([
            inv.number, inv.get_kind_display(), inv.issue_date.strftime("%d.%m.%Y"), inv.order.number,
            _cell(inv.order.customer.full_name if inv.order.customer else ""), fmt(inv.total_net), fmt(inv.total_vat), fmt(inv.total_gross),
            inv.cancelled_by.number if inv.is_cancelled else "", {True: "ja", False: "nein", None: ""}[r["paid"]],
        ])
    return response


def payment_list(request):
    qs = Payment.objects.select_related("order", "order__customer", "created_by").order_by("-paid_on", "-id")
    page = Paginator(qs, 50).get_page(request.GET.get("seite"))
    return render(request, "billing/payments.html", {"page": page})


def month_export(request):
    """ZIP-Archiv eines Monats für das Steuerbüro (nur Administratoren)."""
    import re

    from django.core.exceptions import PermissionDenied

    from apps.core import audit

    from .export import build_month_export

    if not request.user.is_admin:
        raise PermissionDenied("Der Monatsexport ist Administratoren vorbehalten.")
    value = request.GET.get("monat", "")
    m = re.fullmatch(r"(20\d{2})-(0[1-9]|1[0-2])", value)
    if not m:
        from django.contrib import messages
        from django.shortcuts import redirect

        messages.error(request, "Bitte einen Monat auswählen.")
        return redirect("billing:list")
    name, data, stats = build_month_export(int(m.group(1)), int(m.group(2)))
    audit.log(request.user, "export", f"Monatsexport {value} erstellt ({stats['invoices']} Rechnungen, {stats['payments']} Zahlungen)")
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    response["Cache-Control"] = "no-store"
    return response
