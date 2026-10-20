"""Verfügbarkeitsprüfung.

Ein Auftrag belegt seine Artikel vom Übergabetag bis zum Rückgabetag
zuzüglich der Puffertage (Reinigung/Prüfung). Nach einer abgeschlossenen
Rücknahme endet die Belegung am tatsächlichen Rückgabetag.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import Article


def _local_date(dt):
    return timezone.localtime(dt).date()


def occupation(order, buffer_days):
    """(start, end) inklusive, oder None, wenn der Auftrag keine Termine hat."""
    if not (order.handover_at and order.return_at):
        return None
    start = _local_date(order.handover_at)
    end = _local_date(order.return_at)
    record = getattr(order, "return_record", None)
    if record is not None and record.is_completed and record.completed_at:
        end = min(end, _local_date(record.completed_at))
    return start, end + timedelta(days=buffer_days)


def _buffer_days():
    from apps.core.models import CompanySettings

    return CompanySettings.get().buffer_days


def _stock_map(article_ids):
    rows = Article.objects.filter(pk__in=article_ids).annotate(s=Sum("movements__quantity")).values_list("pk", "s")
    return {pk: (s or 0) for pk, s in rows}


def _overlapping_orders(start: date, end: date, exclude_pk=None):
    from .models import Order

    qs = (
        Order.objects.exclude(status=Order.Status.CANCELLED)
        .filter(handover_at__isnull=False, return_at__isnull=False)
        .filter(handover_at__date__lte=end + timedelta(days=1), return_at__date__gte=start - timedelta(days=60))
        .select_related("return_record")
        .prefetch_related("items__article", "items__package__items__article")
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs


def reserved_per_day(article_ids, start: date, end: date, exclude_pk=None, buffer_days=None):
    """{article_id: {date: menge}} für alle anderen Aufträge im Zeitraum."""
    if buffer_days is None:
        buffer_days = _buffer_days()
    result = defaultdict(lambda: defaultdict(int))
    wanted = set(article_ids)
    for other in _overlapping_orders(start, end, exclude_pk):
        occ = occupation(other, buffer_days)
        if occ is None:
            continue
        o_start, o_end = max(occ[0], start), min(occ[1], end)
        if o_start > o_end:
            continue
        for article, qty in other.article_quantities().items():
            if article.pk not in wanted:
                continue
            day = o_start
            while day <= o_end:
                result[article.pk][day] += qty
                day += timedelta(days=1)
    return result


@dataclass
class Availability:
    article: Article
    stock: int
    reserved_peak: int
    required: int

    @property
    def available(self):
        return max(0, self.stock - self.reserved_peak)

    @property
    def missing(self):
        return max(0, self.required - self.available)

    @property
    def ok(self):
        return self.missing == 0


def check_order(order):
    """Verfügbarkeit aller Artikel des Auftrags im Mietzeitraum."""
    buffer_days = _buffer_days()
    occ = occupation(order, buffer_days)
    needed = order.article_quantities()
    if not needed:
        return []
    stocks = _stock_map([a.pk for a in needed])
    if occ is None:
        return [Availability(a, stocks.get(a.pk, 0), 0, q) for a, q in needed.items()]
    reserved = reserved_per_day([a.pk for a in needed], occ[0], occ[1], exclude_pk=order.pk, buffer_days=buffer_days)
    result = []
    for article, qty in sorted(needed.items(), key=lambda x: x[0].name):
        peak = max(reserved.get(article.pk, {}).values(), default=0)
        result.append(Availability(article, stocks.get(article.pk, 0), peak, qty))
    return result


def shortages(order):
    return [a for a in check_order(order) if not a.ok]


def available_quantity(article, order):
    """Freie Menge eines Artikels im Zeitraum des Auftrags (ohne den Auftrag selbst)."""
    buffer_days = _buffer_days()
    stock = _stock_map([article.pk]).get(article.pk, 0)
    occ = occupation(order, buffer_days)
    if occ is None:
        return stock
    reserved = reserved_per_day([article.pk], occ[0], occ[1], exclude_pk=order.pk, buffer_days=buffer_days)
    peak = max(reserved.get(article.pk, {}).values(), default=0)
    return max(0, stock - peak)


def package_available(package, order):
    """Wie oft ein Paket im Zeitraum des Auftrags vollständig verfügbar ist."""
    items = [pi for pi in package.items.select_related("article") if pi.quantity > 0]
    if not items:
        return 0
    buffer_days = _buffer_days()
    ids = [pi.article_id for pi in items]
    stock = _stock_map(ids)
    occ = occupation(order, buffer_days)
    reserved = reserved_per_day(ids, occ[0], occ[1], exclude_pk=order.pk, buffer_days=buffer_days) if occ else {}
    counts = []
    for pi in items:
        peak = max(reserved.get(pi.article_id, {}).values(), default=0)
        counts.append(max(0, stock.get(pi.article_id, 0) - peak) // pi.quantity)
    return min(counts)


def available_map(article_ids, order):
    """Freie Menge vieler Artikel im Zeitraum des Auftrags – in einem Durchgang
    (für die Artikelsuche, statt für jeden Treffer einzeln zu rechnen)."""
    ids = list(set(article_ids))
    if not ids:
        return {}
    buffer_days = _buffer_days()
    stock = _stock_map(ids)
    occ = occupation(order, buffer_days)
    reserved = reserved_per_day(ids, occ[0], occ[1], exclude_pk=order.pk, buffer_days=buffer_days) if occ else {}
    return {pk: max(0, stock.get(pk, 0) - max(reserved.get(pk, {}).values(), default=0)) for pk in ids}


def package_available_from(package, free):
    """Wie oft ein Paket vollständig verfügbar ist – aus einer available_map."""
    counts = [free.get(pi.article_id, 0) // pi.quantity for pi in package.items.all() if pi.quantity > 0]
    return min(counts) if counts else 0
