"""Mitgelieferte Standardvorlagen.

Alle Texte sind in den Einstellungen unter „Vorlagen“ anpassbar. Die Vorlagen
sind ein sorgfältig formulierter Ausgangspunkt, ersetzen aber keine
rechtliche Prüfung für den konkreten Betrieb.
"""

CONTRACT = """## § 1 Vertragsgegenstand
{{firma.name}} (nachfolgend „Vermieter“) vermietet an {{kunde.name}} (nachfolgend „Mieter“) die in der Anlage „Mietgegenstände“ aufgeführten Gegenstände für die Veranstaltung „{{auftrag.event}}“ am {{auftrag.eventdatum}}. Grundlage ist das vom Mieter unterschriebene Angebot {{angebot.nummer}}.

## § 2 Mietzeit, Übergabe und Rückgabe
Die Mietzeit beginnt mit der Übergabe am {{auftrag.uebergabe}} und endet mit der Rückgabe am {{auftrag.rueckgabe}}. Art der Übergabe: {{auftrag.art}}.
Die Übergabe erfolgt erst, wenn die Rechnung vollständig bezahlt ist{{kaution.satz}}. Bei der Übergabe wird ein Übergabeprotokoll erstellt, das Anzahl und Zustand der Gegenstände festhält und von beiden Seiten unterschrieben wird.
Wird die Rückgabe ohne vorherige Absprache überschritten, kann der Vermieter für jeden weiteren Tag den vereinbarten Zusatztagespreis verlangen.

## § 3 Mietpreis und Zahlung
Der Mietpreis beträgt {{auftrag.summe}} (Endpreis). Er wird mit Erhalt der Rechnung fällig und ist spätestens vor der Übergabe vollständig zu zahlen.

## § 4 Kaution
{{kaution.text}}

## § 5 Pflichten des Mieters
Der Mieter behandelt die Mietgegenstände pfleglich und verwendet sie nur bestimmungsgemäß. Eine Weitervermietung oder Überlassung an Dritte außerhalb der genannten Veranstaltung ist nicht gestattet. Kerzen und offenes Feuer dürfen nur in den dafür vorgesehenen Haltern und unter Aufsicht verwendet werden. Die Gegenstände sind besenrein und ohne grobe Verschmutzung zurückzugeben; die übliche Reinigung ist im Mietpreis enthalten.

## § 6 Schäden und Verlust
Der Mieter haftet für Beschädigungen und den Verlust der Mietgegenstände während der Mietzeit, soweit er diese zu vertreten hat. Normale Gebrauchsspuren gehen nicht zu Lasten des Mieters. Für nicht zurückgegebene oder irreparabel beschädigte Gegenstände wird höchstens der in der Anlage genannte Wiederbeschaffungswert berechnet. Dem Mieter bleibt der Nachweis gestattet, dass kein oder ein geringerer Schaden entstanden ist.
Schäden sind dem Vermieter unverzüglich mitzuteilen.

## § 7 Stornierung
{{stornobedingungen}}
Dem Mieter bleibt der Nachweis gestattet, dass dem Vermieter kein oder ein wesentlich geringerer Schaden entstanden ist.

## § 8 Haftung des Vermieters
Der Vermieter haftet unbeschränkt für Vorsatz und grobe Fahrlässigkeit sowie für Schäden aus der Verletzung des Lebens, des Körpers oder der Gesundheit. Im Übrigen haftet er nur bei Verletzung wesentlicher Vertragspflichten, begrenzt auf den vertragstypischen, vorhersehbaren Schaden.

## § 9 Datenschutz
Der Vermieter verarbeitet die personenbezogenen Daten des Mieters ausschließlich zur Durchführung dieses Vertrags und zur Erfüllung gesetzlicher Aufbewahrungspflichten (Art. 6 Abs. 1 lit. b und c DSGVO).

## § 10 Schlussbestimmungen
Änderungen und Ergänzungen dieses Vertrags bedürfen der Textform. Sollte eine Bestimmung unwirksam sein, bleibt die Wirksamkeit der übrigen Bestimmungen unberührt. Es gilt das Recht der Bundesrepublik Deutschland.
"""

TERMS = """## Allgemeine Mietbedingungen
- Alle Preise sind Endpreise{{steuer.hinweis}}.
- Die Mietgegenstände bleiben Eigentum des Vermieters.
- Der Mieter prüft die Gegenstände bei der Übergabe und meldet erkennbare Mängel sofort; sie werden im Übergabeprotokoll festgehalten.
- Bei Lieferung muss der Lieferort zum vereinbarten Zeitpunkt zugänglich sein. Wartezeiten, die der Mieter zu vertreten hat, können gesondert berechnet werden.
"""

WITHDRAWAL = """## Widerrufsbelehrung
Wird der Vertrag ausschließlich über Fernkommunikationsmittel (z. B. E-Mail, Telefon) oder außerhalb der Geschäftsräume geschlossen, kann dem Mieter ein gesetzliches Widerrufsrecht zustehen. Bitte prüfen Sie diese Vorlage und ergänzen Sie hier die für Ihren Betrieb gültige Widerrufsbelehrung samt Muster-Widerrufsformular.
"""

PRIVACY = """Ihre Daten verarbeiten wir ausschließlich zur Abwicklung Ihres Auftrags und zur Erfüllung gesetzlicher Aufbewahrungspflichten. Verantwortlich: {{firma.name}}, {{firma.adresse}}. Sie haben das Recht auf Auskunft, Berichtigung, Löschung im Rahmen der gesetzlichen Fristen sowie auf Beschwerde bei einer Aufsichtsbehörde."""

OFFER_INTRO = """Vielen Dank für Ihre Anfrage. Gerne bieten wir Ihnen für Ihre Veranstaltung „{{auftrag.event}}“ am {{auftrag.eventdatum}} folgende Mietgegenstände an:"""

OFFER_OUTRO = """Dieses Angebot ist bis zum {{angebot.gueltig_bis}} gültig. Mit Ihrer Unterschrift nehmen Sie das Angebot verbindlich an; anschließend erhalten Sie den Mietvertrag. Wir freuen uns auf Ihre Veranstaltung!"""

INVOICE_OUTRO = """Bitte überweisen Sie den Betrag bis zum {{rechnung.faellig}} unter Angabe der Rechnungsnummer {{dokument.nummer}}. Die Übergabe der Mietgegenstände erfolgt nach vollständigem Zahlungseingang."""

# Für Nachberechnung und Stornogebühr: keine Übergabe mehr, ggf. Verrechnung mit Zahlungen
INVOICE_OUTRO_FOLLOWUP = """{{zahlung.hinweis}}"""

HANDOVER_CONFIRM = """Der Mieter bestätigt, die oben aufgeführten Gegenstände in der angegebenen Anzahl und im beschriebenen Zustand erhalten zu haben. Bereits vorhandene Schäden sind vermerkt."""

MAIL_SIGNATURE = """

Viele Grüße
{{firma.name}}
{{firma.kontakt}}"""

DEFAULT_TEMPLATES = {
    "contract": ("Mietvertrag", CONTRACT),
    "terms": ("Allgemeine Mietbedingungen", TERMS),
    "withdrawal": ("Widerrufsbelehrung", WITHDRAWAL),
    "privacy": ("Datenschutzhinweis", PRIVACY),
    "offer_intro": ("", OFFER_INTRO),
    "offer_outro": ("", OFFER_OUTRO),
    "invoice_outro": ("", INVOICE_OUTRO),
    "invoice_outro_followup": ("", INVOICE_OUTRO_FOLLOWUP),
    "handover_confirm": ("", HANDOVER_CONFIRM),
    "mail_offer": (
        "Ihr Angebot {{dokument.nummer}} – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie unser Angebot für Ihre Veranstaltung „{{auftrag.event}}“ am {{auftrag.eventdatum}}.\nBitte senden Sie uns das Angebot unterschrieben zurück oder unterschreiben Sie es bei uns vor Ort."
        + MAIL_SIGNATURE,
    ),
    "mail_offer_signed": (
        "Ihr unterschriebenes Angebot {{dokument.nummer}} – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nvielen Dank für Ihre Zusage! Anbei erhalten Sie das unterschriebene Angebot für Ihre Unterlagen. Den Mietvertrag senden wir Ihnen in Kürze zu."
        + MAIL_SIGNATURE,
    ),
    "mail_contract": (
        "Ihr Mietvertrag {{dokument.nummer}} – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie den Mietvertrag für Ihre Veranstaltung „{{auftrag.event}}“. Bitte senden Sie uns den Vertrag unterschrieben zurück."
        + MAIL_SIGNATURE,
    ),
    "mail_contract_signed": (
        "Ihr unterschriebener Mietvertrag {{dokument.nummer}} – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie Ihre Ausfertigung des unterschriebenen Mietvertrags für Ihre Unterlagen. Die Rechnung erhalten Sie gesondert."
        + MAIL_SIGNATURE,
    ),
    "mail_invoice": (
        "Ihre Rechnung {{dokument.nummer}} – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie die Rechnung {{dokument.nummer}} über {{rechnung.betrag}}. Bitte zahlen Sie den Betrag bis zum {{rechnung.faellig}}. Die Übergabe erfolgt nach vollständigem Zahlungseingang."
        + MAIL_SIGNATURE,
    ),
    "mail_additional": (
        "Nachberechnung {{dokument.nummer}} – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nnach der Rückgabe der Mietgegenstände stellen wir Ihnen mit der beigefügten Rechnung {{dokument.nummer}} {{rechnung.betrag}} in Rechnung. Die einzelnen Posten finden Sie im Rücknahmeprotokoll und in der Kautionsabrechnung.\n\n{{zahlung.hinweis}}"
        + MAIL_SIGNATURE,
    ),
    "mail_fee": (
        "Stornogebühr {{dokument.nummer}} – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nwie besprochen haben wir Ihren Auftrag für „{{auftrag.event}}“ storniert. Gemäß den vereinbarten Stornobedingungen berechnen wir eine Stornogebühr von {{rechnung.betrag}}; die Rechnung {{dokument.nummer}} finden Sie im Anhang.\n\n{{zahlung.hinweis}}"
        + MAIL_SIGNATURE,
    ),
    "mail_cancellation": (
        "Stornorechnung {{dokument.nummer}} – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie die Stornorechnung {{dokument.nummer}}. Sie hebt die Rechnung {{rechnung.storniert}} vollständig auf.\n\n{{zahlung.hinweis}}"
        + MAIL_SIGNATURE,
    ),
    "mail_handover": (
        "Übergabeprotokoll – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie das unterschriebene Übergabeprotokoll. Wir wünschen Ihnen eine wunderschöne Veranstaltung!"
        + MAIL_SIGNATURE,
    ),
    "mail_return": (
        "Rücknahmeprotokoll – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nvielen Dank für die Rückgabe. Anbei erhalten Sie das Rücknahmeprotokoll.\n\n{{ruecknahme.ergebnis}}"
        + MAIL_SIGNATURE,
    ),
    "mail_deposit": (
        "Kautionsabrechnung – {{auftrag.event}}",
        "{{kunde.briefanrede}},\n\nanbei erhalten Sie die Abrechnung Ihrer Kaution.\n\n{{kaution.abrechnung}}"
        + MAIL_SIGNATURE,
    ),
}
