"""Mitgelieferte E-Mail-Vorlagen auf die Texte von 1.0.4 heben.

Neu: Briefanrede je nach Einstellung, „Tel.“ in der Signatur, automatische
Angaben zu Rücknahme und Kautionsabrechnung. Es werden nur Vorlagen
aktualisiert, die noch exakt dem bisherigen Standardtext entsprechen – selbst
angepasste Vorlagen bleiben unverändert. Die neue Fassung wird als neue
Version gespeichert, die alte bleibt in der Historie.
"""

from django.db import migrations

OLD_SIGNATURE = "\n\nViele Grüße\n{{firma.name}}\n{{firma.telefon}}"

OLD = {
    "mail_offer": (
        "Ihr Angebot {{dokument.nummer}} – {{auftrag.event}}",
        "Hallo {{kunde.anrede}},\n\nanbei erhalten Sie unser Angebot für Ihre Veranstaltung „{{auftrag.event}}“ am {{auftrag.eventdatum}}.\nBitte senden Sie uns das Angebot unterschrieben zurück oder unterschreiben Sie es bei uns vor Ort."
        + OLD_SIGNATURE,
    ),
    "mail_contract": (
        "Ihr Mietvertrag {{dokument.nummer}} – {{auftrag.event}}",
        "Hallo {{kunde.anrede}},\n\nanbei erhalten Sie den Mietvertrag für Ihre Veranstaltung „{{auftrag.event}}“. Bitte senden Sie uns den Vertrag unterschrieben zurück."
        + OLD_SIGNATURE,
    ),
    "mail_invoice": (
        "Ihre Rechnung {{dokument.nummer}} – {{auftrag.event}}",
        "Hallo {{kunde.anrede}},\n\nanbei erhalten Sie die Rechnung {{dokument.nummer}} über {{rechnung.betrag}}. Bitte zahlen Sie den Betrag bis zum {{rechnung.faellig}}. Die Übergabe erfolgt nach vollständigem Zahlungseingang."
        + OLD_SIGNATURE,
    ),
    "mail_handover": (
        "Übergabeprotokoll – {{auftrag.event}}",
        "Hallo {{kunde.anrede}},\n\nanbei erhalten Sie das unterschriebene Übergabeprotokoll. Wir wünschen Ihnen eine wunderschöne Veranstaltung!"
        + OLD_SIGNATURE,
    ),
    "mail_return": (
        "Rücknahmeprotokoll – {{auftrag.event}}",
        "Hallo {{kunde.anrede}},\n\nvielen Dank für die Rückgabe. Anbei erhalten Sie das Rücknahmeprotokoll."
        + OLD_SIGNATURE,
    ),
    "mail_deposit": (
        "Kautionsabrechnung – {{auftrag.event}}",
        "Hallo {{kunde.anrede}},\n\nanbei erhalten Sie die Abrechnung Ihrer Kaution."
        + OLD_SIGNATURE,
    ),
}

# Stand 1.0.4 (bewusst hier festgehalten, damit spätere Textänderungen diese Migration nicht verändern)
SIGNATURE = "\n\nViele Grüße\n{{firma.name}}\n{{firma.kontakt}}"
NEW = {
    "mail_offer": (
        "Ihr Angebot {{dokument.nummer}} – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie unser Angebot für Ihre Veranstaltung „{{auftrag.event}}“ am {{auftrag.eventdatum}}.\nBitte senden Sie uns das Angebot unterschrieben zurück oder unterschreiben Sie es bei uns vor Ort."
        + SIGNATURE,
    ),
    "mail_contract": (
        "Ihr Mietvertrag {{dokument.nummer}} – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie den Mietvertrag für Ihre Veranstaltung „{{auftrag.event}}“. Bitte senden Sie uns den Vertrag unterschrieben zurück."
        + SIGNATURE,
    ),
    "mail_invoice": (
        "Ihre Rechnung {{dokument.nummer}} – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie die Rechnung {{dokument.nummer}} über {{rechnung.betrag}}. Bitte zahlen Sie den Betrag bis zum {{rechnung.faellig}}. Die Übergabe erfolgt nach vollständigem Zahlungseingang."
        + SIGNATURE,
    ),
    "mail_handover": (
        "Übergabeprotokoll – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie das unterschriebene Übergabeprotokoll. Wir wünschen Ihnen eine wunderschöne Veranstaltung!"
        + SIGNATURE,
    ),
    "mail_return": (
        "Rücknahmeprotokoll – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nvielen Dank für die Rückgabe. Anbei erhalten Sie das Rücknahmeprotokoll.\n\n{{ruecknahme.ergebnis}}"
        + SIGNATURE,
    ),
    "mail_deposit": (
        "Kautionsabrechnung – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie die Abrechnung Ihrer Kaution.\n\n{{kaution.abrechnung}}"
        + SIGNATURE,
    ),
}


def upgrade(apps, schema_editor):
    TextTemplate = apps.get_model("core", "TextTemplate")
    for key, (old_subject, old_body) in OLD.items():
        current = TextTemplate.objects.filter(key=key).order_by("-version").first()
        if current is None:
            continue  # noch nie verwendet – es gilt automatisch der neue Standardtext
        if current.subject.strip() != old_subject or current.body.replace("\r\n", "\n").strip() != old_body.strip():
            continue  # selbst angepasst – nicht anfassen
        subject, body = NEW[key]
        TextTemplate.objects.create(key=key, version=current.version + 1, subject=subject, body=body)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_v104_settings_mailqueue"),
    ]

    operations = [
        migrations.RunPython(upgrade, migrations.RunPython.noop),
    ]
