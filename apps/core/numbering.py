"""Lückenlose, fortlaufende Nummernkreise.

Die Nummer wird innerhalb der laufenden Transaktion mit einer Zeilensperre
(SELECT … FOR UPDATE) vergeben. Wird die Transaktion zurückgerollt, wird auch
die Nummer nicht verbraucht – so entstehen keine Lücken.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import NumberSequence

PREFIXES = {
    "order": "AU",
    "offer": "AN",
    "contract": "MV",
    "invoice": "RE",
    "cancellation": "SR",
    "customer": "K",
    "article": "A",
}

YEARLY = {"order", "offer", "contract", "invoice", "cancellation"}


def next_number(kind: str) -> str:
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Nummernvergabe nur innerhalb einer Transaktion.")
    year = timezone.localdate().year if kind in YEARLY else 0
    try:
        # Eigener Savepoint: legt ein paralleler Vorgang den Nummernkreis gleichzeitig an,
        # wird der vorhandene Datensatz anschließend gesperrt und verwendet.
        with transaction.atomic():
            NumberSequence.objects.get_or_create(kind=kind, year=year)
    except IntegrityError:
        pass
    seq = NumberSequence.objects.select_for_update().get(kind=kind, year=year)
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    prefix = PREFIXES[kind]
    if kind in YEARLY:
        return f"{prefix}-{year}-{seq.last_number:04d}"
    return f"{prefix}-{seq.last_number:05d}"
