"""Platzhalter und einfache Textauszeichnung für bearbeitbare Vorlagen.

Bewusst kein vollwertiger Template-Mechanismus: Vorlagen können nur die
freigegebenen Platzhalter verwenden und kein HTML einschleusen.

Auszeichnung:
  ## Überschrift
  - Aufzählungspunkt
  **fett**
  Leerzeile = neuer Absatz
"""

import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_]+(?:\.[a-z_]+)?)\s*\}\}")

PLACEHOLDERS = {
    "firma.name": "Firmenname",
    "firma.adresse": "Anschrift des Betriebs",
    "firma.inhaber": "Inhaber/in",
    "firma.telefon": "Telefon",
    "firma.email": "E-Mail",
    "firma.kontakt": "Kontaktzeile (Tel. und E-Mail)",
    "kunde.name": "Vollständiger Name des Kunden",
    "kunde.anrede": "Vorname des Kunden",
    "kunde.briefanrede": "Briefanrede (z. B. „Sehr geehrte Frau Weber“ oder „Hallo Anna“, je nach Einstellung)",
    "kunde.adresse": "Anschrift des Kunden",
    "kunde.email": "E-Mail des Kunden",
    "kunde.telefon": "Telefon des Kunden",
    "kunde.nummer": "Kundennummer",
    "auftrag.nummer": "Auftragsnummer",
    "auftrag.event": "Name der Veranstaltung",
    "auftrag.eventdatum": "Datum der Veranstaltung",
    "auftrag.ort": "Veranstaltungsort",
    "auftrag.art": "Abholung oder Lieferung",
    "auftrag.uebergabe": "Übergabetermin",
    "auftrag.rueckgabe": "Rückgabetermin",
    "auftrag.summe": "Gesamtbetrag (brutto)",
    "angebot.nummer": "Angebotsnummer",
    "angebot.gueltig_bis": "Angebot gültig bis",
    "kaution.betrag": "Kautionsbetrag",
    "kaution.text": "Kautionsregelung (automatischer Satz)",
    "kaution.satz": "Zusatz „und die Kaution eingegangen ist“",
    "dokument.nummer": "Nummer des Dokuments",
    "dokument.datum": "Datum des Dokuments",
    "rechnung.betrag": "Rechnungsbetrag",
    "rechnung.faellig": "Zahlungsziel",
    "rechnung.storniert": "Nummer der stornierten Rechnung",
    "zahlung.hinweis": "Zahlungshinweis (automatisch: Zahlungsaufforderung, Verrechnung oder Erstattung)",
    "kaution.abrechnung": "Ergebnis der Kautionsabrechnung (automatisch, mit Beträgen)",
    "ruecknahme.ergebnis": "Ergebnis der Rücknahme (automatisch: vollständig oder festgestellte Schäden)",
    "steuer.hinweis": "Steuerhinweis (inkl. MwSt. / § 19 UStG)",
    "stornobedingungen": "Stornobedingungen aus den Einstellungen",
}


def render_placeholders(text: str, context: dict) -> str:
    def repl(match):
        key = match.group(1)
        if key in context:
            return str(context[key])
        return match.group(0)

    return PLACEHOLDER_RE.sub(repl, text or "")


def unknown_placeholders(text: str):
    return sorted({m.group(1) for m in PLACEHOLDER_RE.finditer(text or "") if m.group(1) not in PLACEHOLDERS})


def _inline(text: str) -> str:
    text = escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def to_html(text: str) -> str:
    """Wandelt die einfache Auszeichnung in sicheres HTML um."""
    out = []
    paragraph = []
    in_list = False

    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + "<br>".join(_inline(line) for line in paragraph) + "</p>")
            paragraph = []

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph()
            close_list()
            continue
        if line.startswith("## "):
            flush_paragraph()
            close_list()
            out.append(f"<h3>{_inline(line[3:].strip())}</h3>")
        elif line.startswith("# "):
            flush_paragraph()
            close_list()
            out.append(f"<h2>{_inline(line[2:].strip())}</h2>")
        elif line.lstrip().startswith("- "):
            flush_paragraph()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line.lstrip()[2:].strip())}</li>")
        else:
            close_list()
            paragraph.append(line)
    flush_paragraph()
    close_list()
    return mark_safe("\n".join(out))


def render_html(text: str, context: dict) -> str:
    return to_html(render_placeholders(text, context))
