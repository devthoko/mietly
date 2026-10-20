# Funktionen

<sub>[← Zurück zur Übersicht](../README.md) · [Installation](installation.md) · [Betrieb](betrieb.md) · [Funktionen](funktionen.md) · [Entwicklung](entwicklung.md) · [Rechtliches](recht.md)</sub>

**Auftragsakte mit neun Schritten.** Jeder Auftrag zeigt jederzeit an, in welchem Schritt er sich befindet, was erledigt ist, was fehlt und was als Nächstes zu tun ist:

| Schritt | Inhalt |
|---|---|
| 1. Kunde | bestehenden Privatkunden wählen oder neu anlegen |
| 2. Event | Veranstaltung, Ort, Abholung/Lieferung, Übergabe- und Rückgabetermin |
| 3. Angebot | Artikel, Pakete, individuelle Positionen; PDF, E-Mail, digitale Unterschrift oder Upload |
| 4. Mietvertrag | aus bearbeitbarer Vorlage erzeugt; PDF, digitale Unterschrift oder Upload |
| 5. Rechnung | fortlaufende Nummer, § 14 UStG, Zahlungseingänge inkl. Teilzahlungen, Storno |
| 6. Packliste | alle Artikel inkl. aufgelöster Pakete, Lagerort, Abhakfelder |
| 7. Übergabe | Mengen, Zustand, Vorschäden, Fotos, Übergabeprotokoll mit Unterschrift |
| 8. Rücknahme | Rückgabemengen, Beschädigungen, Fehlmengen, Fotos, Rücknahmeprotokoll |
| 9. Kaution & Abschluss | Schäden mit Kaution verrechnen oder nachberechnen, Rückzahlung, Abschluss |

**Verbindliche Sperren** – im Server abgesichert und für **alle** Rollen gültig, auch für Administratoren:

* Mietvertrag nur mit unterschriebenem Angebot
* Rechnung nur mit unterschriebenem Mietvertrag
* Übergabe nur bei vollständig bezahlter Rechnung
* Abschluss der Übergabe nur mit unterschriebenem Übergabeprotokoll

**Weitere Funktionen**

* Verfügbarkeitsprüfung je Artikel im Mietzeitraum inkl. Puffertagen für Reinigung (verhindert Überbuchungen)
* Artikelpakete mit eigenem Paketpreis, Zusatztagespreise, Kautionsvorschlag aus den Artikeln
* Bestandsführung mit Bewegungshistorie; Fehlmengen und Ausmusterungen werden automatisch gebucht
* Übersicht mit offenen Aufgaben, Übergaben/Rückgaben der nächsten Tage, offenen Forderungen und verwahrten Kautionen
* Kalender, Schnellsuche (Strg + K), Auftrag kopieren („wie letztes Jahr“), Stornierung mit Stornogebühr
* Unveränderliche, versionierte Dokumente mit SHA-256-Prüfsumme; geänderte Angebote erfordern eine neue Unterschrift
* Bearbeitbare, versionierte Vorlagen (Vertrag, Mietbedingungen, Widerrufsbelehrung, Dokument- und E-Mail-Texte)
* SMTP-E-Mail-Versand im Hintergrund mit automatischer Wiederholung bei Störungen (systemd-Timer `mietly-mail.timer`) und Versandprotokoll
* Optionale WebDAV-/Nextcloud-Synchronisierung (Dokumente und verschlüsselte Backups)
* Benutzerverwaltung (Administrator, Mitarbeiter), Aktivitätsprotokoll
* Datenschutz: Datenauskunft je Kunde, Anonymisierung nach Ablauf der Aufbewahrungsfristen
* Rechnungsexport als CSV für das Steuerbüro
* Hell- und Dunkelmodus, für Desktop, Tablet und Smartphone

