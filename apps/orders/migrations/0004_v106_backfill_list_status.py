"""Kurzstatus („Wartet auf Unterschrift“ …) für bestehende Aufträge berechnen.

Nutzt bewusst die aktuelle Ablauflogik (apps.orders.workflow), da der Status
genau so berechnet werden soll wie im laufenden Betrieb. Schlägt das fehl,
bleibt das Feld leer – die Listen zeigen dann wie bisher den Schrittnamen,
und der Status wird bei der nächsten Änderung am Auftrag nachgetragen.
"""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)


def backfill(apps, schema_editor):
    try:
        from apps.orders import workflow
        from apps.orders.models import Order

        for order in Order.objects.filter(status="active"):
            workflow.refresh_stage(order)
    except Exception:  # noqa: BLE001 – nur eine Anzeigehilfe, darf das Update nicht verhindern
        logger.exception("Kurzstatus konnte nicht nachgetragen werden")


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0003_v106_list_status"),
        ("billing", "0002_initial"),
        ("documents", "0001_initial"),
        ("core", "0005_v105_printer"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
