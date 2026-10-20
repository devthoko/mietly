"""Betragsberechnung für Endpreise (brutto) mit Ausweis der enthaltenen Umsatzsteuer."""

from collections import OrderedDict
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def money(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def totals(lines, small_business=False):
    """lines: Iterable von (gross_total, vat_rate). Gibt Summen und Aufschlüsselung zurück.

    Die Steuer wird je Steuersatz aus der Bruttosumme herausgerechnet
    (USt = Brutto − Brutto / (1 + Satz)), wie bei Endpreisen üblich.
    """
    groups = OrderedDict()
    gross_total = Decimal("0.00")
    for gross, rate in lines:
        gross = money(gross)
        gross_total += gross
        rate = Decimal("0") if small_business else Decimal(rate)
        groups[rate] = groups.get(rate, Decimal("0.00")) + gross
    breakdown = []
    vat_total = Decimal("0.00")
    for rate, gross in sorted(groups.items(), key=lambda x: -x[0]):
        if rate:
            net = money(gross / (Decimal("1") + rate / Decimal("100")))
            vat = gross - net
        else:
            net, vat = gross, Decimal("0.00")
        vat_total += vat
        breakdown.append({"rate": str(rate), "gross": str(gross), "net": str(net), "vat": str(vat)})
    return {
        "gross": gross_total,
        "vat": vat_total,
        "net": gross_total - vat_total,
        "breakdown": breakdown,
    }
