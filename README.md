# mietly

**Verwaltungssoftware für einen Event- und Dekorationsverleih** – vom ersten Angebot bis zur zurückgezahlten Kaution.

mietly läuft vollständig auf dem eigenen Ubuntu-Server (z. B. einer Proxmox-LXC) und wird im lokalen Netzwerk über den Browser bedient. Es gibt keine Cloud-Abhängigkeit, alle Geschäftsdaten bleiben auf dem eigenen Server.

---

## Inhalt

1. [Funktionen](#funktionen)
2. [Systemvoraussetzungen](#systemvoraussetzungen)
3. [Installation](#installation)
4. [Erste Schritte](#erste-schritte)
5. [Konfiguration](#konfiguration)
6. [Start und Stopp](#start-und-stopp)
7. [Updates](#updates)
8. [Backup](#backup)
9. [Wiederherstellung](#wiederherstellung)
10. [Fehlerbehebung](#fehlerbehebung)
11. [Aufbau und Verzeichnisse](#aufbau-und-verzeichnisse)
12. [Entwicklung](#entwicklung)
13. [Rechtliche Hinweise](#rechtliche-hinweise)

---

## Funktionen

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

---

## Systemvoraussetzungen

| | Minimum | Empfohlen |
|---|---|---|
| Betriebssystem | Ubuntu 26.04 LTS (x86_64) | Ubuntu 26.04 LTS |
| CPU | 1 Kern | 2–4 Kerne |
| Arbeitsspeicher | 1 GB | 2–4 GB |
| Speicherplatz | 5 GB | 30 GB (Fotos und Backups wachsen mit) |
| Netzwerk | Internetzugang während der Installation (Ubuntu-Paketquellen) | |

mietly installiert sich **nativ** – ohne Docker oder andere Container. Folgende Ubuntu-Pakete werden automatisch eingerichtet: PostgreSQL, nginx, Python 3 (venv), Pango (für PDFs), die Schriften EB Garamond und Source Sans 3, zstd sowie CUPS mit gängigen Druckertreibern (HPLIP, Gutenprint, brlaser). CUPS ist nur lokal erreichbar; der Dienstbenutzer `mietly` ist Mitglied der Gruppe `lpadmin`, um seine Druckerwarteschlange selbst einzurichten.

---

## Installation

### Mit einem Befehl (empfohlen)

Auf einem frischen Server mit Ubuntu 26.04 LTS:

```bash
curl -fsSL https://github.com/devthoko/mietly/releases/latest/download/install.sh | sudo bash
```

Eine bestimmte Version (z. B. für reproduzierbare Installationen):

```bash
curl -fsSL https://github.com/devthoko/mietly/releases/download/v1.0.12/install.sh | sudo bash
```

Das Skript lädt das Installationspaket der Version von GitHub, prüft dessen SHA-256-Prüfsumme und startet es. Derselbe Befehl aktualisiert eine bestehende Installation (mit automatischem Backup und Rücksprung bei Fehlern). Die Anwendung startet leer – ohne Kunden, Aufträge oder Beispieldaten.

### Mit der Installationsdatei (ohne Internet für mietly selbst)

1. Installationsdatei (aus den GitHub-Releases) auf den Server kopieren, z. B. vom eigenen Rechner aus:

   ```bash
   scp mietly-1.0.0.run root@SERVER:/root/
   ```

2. Auf dem Server **ein Befehl**:

   ```bash
   sudo bash mietly-1.0.0.run
   ```

Der Installer richtet Pakete, Sprache (de_DE.UTF-8), Zeitzone (Europe/Berlin), Systembenutzer, Datenbank, Konfiguration, HTTPS-Zertifikat, Dienste und das nächtliche Backup ein. Danach prüft er, ob mietly antwortet. Am Ende werden die Adresse und der Erstzugang angezeigt.

Die Prüfsumme der Installationsdatei lässt sich vorher kontrollieren:

```bash
sha256sum -c mietly-1.0.0.run.sha256
```

---

## Erste Schritte

1. Im Browser `https://<IP-des-Servers>` öffnen. Das Zertifikat ist selbstsigniert, deshalb fragt der Browser beim ersten Aufruf einmalig nach (siehe [Eigenes Zertifikat](#eigenes-zertifikat)).
2. Mit dem Benutzer **admin** anmelden. Das Passwort steht in `/root/mietly-erstzugang.txt`:

   ```bash
   sudo cat /root/mietly-erstzugang.txt
   ```

3. Unter **Profil** das Passwort ändern und die Datei danach löschen:

   ```bash
   sudo rm /root/mietly-erstzugang.txt
   ```

4. Unter **Einstellungen** nacheinander ausfüllen:
   * Geschäftsdaten und Logo
   * Steuer & Bank (Regelbesteuerung oder Kleinunternehmer)
   * Geschäftsregeln
   * E-Mail
   * Vorlagen prüfen
5. Unter **Einstellungen → Benutzer** Konten für Mitarbeiter anlegen.
6. Unter **Artikel** und **Pakete** das Sortiment erfassen. Danach kann der erste Auftrag beginnen.

Zum Ausprobieren lassen sich Beispieldaten anlegen (Artikel, Pakete, Kunden; nur solange noch keine Artikel existieren):

```bash
sudo mietly manage demo_data --ja
```

---

## Konfiguration

### In der Oberfläche (Einstellungen)

| Bereich | Inhalt |
|---|---|
| Geschäftsdaten | Name, Anschrift, Kontakt, Logo – erscheinen auf allen Dokumenten |
| Steuer & Bank | Steuernummer/USt-IdNr., Kleinunternehmerregelung, Steuersatz, Bankverbindung |
| Geschäftsregeln | Angebotsgültigkeit, Zahlungsziel, inklusive Miettage, Puffertage, Kaution vor Übergabe, Stornobedingungen, Lieferpauschale |
| Vorlagen | Mietvertrag, Mietbedingungen, Widerrufsbelehrung, Datenschutzhinweis, Dokument- und E-Mail-Texte (mit Platzhaltern und Versionsverlauf) |
| E-Mail | SMTP-Server, Absender, BCC, Anrede (förmlich oder persönlich), Testversand, Versandprotokoll |
| Drucker | Netzwerkdrucker per IP-Adresse einbinden: Modell und Treiber werden automatisch erkannt (treiberlos per IPP Everywhere/AirPrint, sonst HPLIP, Gutenprint oder brlaser), anschließend wird eine Testseite gedruckt. Danach haben alle Dokumente einen Knopf „Drucken“. |
| WebDAV / Nextcloud | optionale Synchronisierung von Dokumenten und verschlüsselten Backups |
| Benutzer | Administratoren und Mitarbeiter |
| Backups | Übersicht, manuelles Backup, Download |

### Auf dem Server: `/etc/mietly/mietly.env`

| Variable | Bedeutung |
|---|---|
| `MIETLY_SECRET_KEY` | geheimer Schlüssel für Sitzungen – nicht weitergeben |
| `MIETLY_ENCRYPTION_KEY` | verschlüsselt gespeicherte SMTP-/WebDAV-Passwörter – **nicht ändern**, sonst müssen diese neu eingegeben werden |
| `MIETLY_ALLOWED_HOSTS` | Adressen/Namen, unter denen mietly aufgerufen werden darf (kommagetrennt) |
| `MIETLY_CSRF_TRUSTED_ORIGINS` | dieselben Adressen mit `https://` davor |
| `MIETLY_DATA_DIR` | Geschäftsdateien (Standard `/var/lib/mietly`) |
| `MIETLY_BACKUP_DIR` | Backups (Standard `/var/backups/mietly`) |

**Neue IP-Adresse oder ein Hostname** (z. B. `mietly.fritz.box`):

1. Den Namen bzw. die Adresse in `MIETLY_ALLOWED_HOSTS` und – mit `https://` davor – in `MIETLY_CSRF_TRUSTED_ORIGINS` ergänzen.
2. mietly neu starten:

   ```bash
   sudo mietly restart
   ```

### Eigenes Zertifikat

Ein vorhandenes Zertifikat (z. B. von einer internen Zertifizierungsstelle) lässt sich verwenden:

1. Die Dateien unter `/etc/mietly/tls/mietly.crt` und `/etc/mietly/tls/mietly.key` ablegen. Der Schlüssel braucht die Gruppe `www-data` und die Rechte `0640`.
2. nginx neu laden:

   ```bash
   sudo systemctl reload nginx
   ```

Alternativ das selbstsignierte Zertifikat `/etc/mietly/tls/mietly.crt` auf den Arbeitsplatzrechnern als vertrauenswürdig importieren. Dann erscheint keine Warnung mehr.

---

## Start und Stopp

mietly läuft als systemd-Dienst und startet nach einem Neustart des Servers automatisch.

```bash
sudo mietly status        # Zustand von Anwendung, nginx, Datenbank, Backup-Timer, letztes Backup
sudo mietly start
sudo mietly stop
sudo mietly restart
sudo mietly logs          # letzte 200 Zeilen
sudo mietly logs -f       # live mitlesen
```

---

## Updates

Neue Versionen werden genauso installiert wie die erste:

```bash
sudo bash mietly-1.1.0.run
```

Der Installer erkennt die bestehende Installation und arbeitet diese Schritte ab:

1. **Vollbackup** des aktuellen Stands (`…-vor-update-1.1.0.tar.zst`)
2. Neue Version **neben** der alten installieren (`/opt/mietly/releases/1.1.0`)
3. Datenbank migrieren, auf die neue Version umschalten, Funktionsprüfung
4. Bei einem Fehler **automatisch zurück** zur alten Version, inklusive Wiederherstellung des Backups

Die drei neuesten Versionen bleiben erhalten. Manuell zurückkehren:

```bash
sudo mietly rollback
```

`rollback` aktiviert die vorherige Version und spielt das Backup vor dem letzten Update zurück. Daten, die seit dem Update erfasst wurden, gehen dabei verloren; der Befehl fragt deshalb vorher nach.

---

## Backup

* **Automatisch:** jede Nacht um 2:30 Uhr (systemd-Timer `mietly-backup.timer`)
* **Vor jedem Update** und **vor jeder Wiederherstellung**
* **Manuell:** in der Oberfläche unter Einstellungen → Backups oder mit:

  ```bash
  sudo mietly backup
  sudo mietly backups      # vorhandene Backups anzeigen
  ```

Ein Backup ist **eine Datei** `/var/backups/mietly/mietly-backup-JJJJ-MM-TT_HHMMSS.tar.zst` mit Prüfsummendatei (`.sha256`). Es enthält:

* die vollständige Datenbank (`pg_dump`)
* alle Dokumente, unterschriebenen Fassungen, Fotos und Logos
* die Konfiguration inkl. Schlüssel (`mietly.env`)

Aufbewahrt werden 14 tägliche, 8 wöchentliche und 12 monatliche Backups. Backups vor Updates bleiben 90 Tage erhalten.

> **Wichtig:** Ein Backup auf demselben Server schützt nicht vor einem Plattendefekt. Bewahren Sie regelmäßig Kopien **außerhalb** auf. Dafür gibt es drei Wege:
>
> * den Download unter Einstellungen → Backups
> * die WebDAV-/Nextcloud-Synchronisierung
> * ein Proxmox-Backup (`vzdump`) der ganzen LXC auf einen anderen Speicher
>
> Die Backup-Dateien enthalten den Verschlüsselungsschlüssel und sind deshalb nur für root bzw. den Dienstbenutzer lesbar. Behandeln Sie heruntergeladene Backups vertraulich.

**WebDAV-Backups** werden mit der in den Einstellungen hinterlegten Passphrase verschlüsselt. So entschlüsseln Sie eine Datei:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in DATEI.tar.zst.enc -out DATEI.tar.zst
```

---

## Wiederherstellung

```bash
sudo mietly restore /var/backups/mietly/mietly-backup-2026-10-19_023000.tar.zst
```

Der Befehl geht so vor:

1. Prüfsumme kontrollieren
2. Nachfragen
3. Den **aktuellen** Stand sichern
4. Datenbank und Dateien ersetzen, Schema prüfen, mietly neu starten

Der vorherige Dateistand bleibt zusätzlich unter `/var/lib/mietly/media.vor-wiederherstellung-…` liegen.

**Auf einem neuen Server** (z. B. nach einem Defekt):

1. mietly mit der Installationsdatei neu installieren.
2. Das Backup mit Konfiguration wiederherstellen:

   ```bash
   sudo mietly restore /pfad/zum/backup.tar.zst --mit-konfiguration
   ```

Mit `--mit-konfiguration` wird auch `mietly.env` übernommen, damit gespeicherte SMTP-/WebDAV-Passwörter wieder entschlüsselt werden können. Bei geänderter IP-Adresse danach `MIETLY_ALLOWED_HOSTS` anpassen.

---

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| Seite nicht erreichbar | `sudo mietly status`; prüfen, ob die Firewall Port 443 erlaubt (`sudo ufw status`) |
| „Bad Request (400)“ | Die aufgerufene Adresse fehlt in `MIETLY_ALLOWED_HOSTS` (siehe [Konfiguration](#konfiguration)) |
| „CSRF-Überprüfung fehlgeschlagen“ beim Absenden | Adresse mit `https://` in `MIETLY_CSRF_TRUSTED_ORIGINS` ergänzen, `sudo mietly restart` |
| Browser warnt vor dem Zertifikat | erwartet bei selbstsigniertem Zertifikat – einmalig bestätigen oder [eigenes Zertifikat](#eigenes-zertifikat) verwenden |
| E-Mails kommen nicht an | Einstellungen → E-Mail: Testversand und Versandprotokoll prüfen (Port 587 + STARTTLS bzw. 465 + SSL). Bei Störungen wird der Versand bis zu sechsmal über etwa drei Stunden wiederholt; danach zeigt der Auftrag „E-Mail nicht zugestellt“ mit „Erneut senden“. |
| Drucker wird nicht gefunden | Drucker einschalten und IP-Adresse prüfen (Konfigurationsseite des Druckers). Der Server muss den Drucker erreichen: `ping IP`. Viele Drucker brauchen „AirPrint“ bzw. „IPP“ im Netzwerkmenü. Druckaufträge: `lpstat -o mietly`, Protokoll: `journalctl -u cups` |
| Anmeldung gesperrt | Nach 5 Fehlversuchen wird 15 Minuten gesperrt. Ein Administrator kann das Passwort unter Einstellungen → Benutzer neu setzen. |
| Administrator-Passwort vergessen | `sudo mietly create-admin` legt ein weiteres Administratorkonto an |
| Backup fehlgeschlagen | Meldung unter Einstellungen → Backups, Details mit `sudo mietly logs`; freien Speicher prüfen (`df -h`) |
| Fehlermeldung in der Oberfläche | `sudo mietly logs` zeigt den Fehler; Installationsprotokoll: `/var/log/mietly-install.log` |
| Nach einem Update funktioniert etwas nicht | `sudo mietly rollback` |

Die Dienste lassen sich auch einzeln prüfen:

```bash
systemctl status mietly nginx postgresql
journalctl -u mietly -e
```

---

## Aufbau und Verzeichnisse

Quellcode, Konfiguration und Geschäftsdaten sind sauber getrennt:

| Pfad | Inhalt |
|---|---|
| `/opt/mietly/releases/<Version>/` | installierte Versionen (Code + Python-Umgebung), unveränderlich |
| `/opt/mietly/current` | Verweis auf die aktive Version |
| `/etc/mietly/mietly.env` | Konfiguration und Schlüssel |
| `/etc/mietly/tls/` | HTTPS-Zertifikat |
| PostgreSQL-Datenbank `mietly` | Geschäftsdaten |
| `/var/lib/mietly/media/` | Dokumente, unterschriebene Fassungen, Fotos, Logo |
| `/var/backups/mietly/` | Backups |
| `/usr/local/bin/mietly` | Verwaltungsbefehl |

**Technik:**

* Python 3 und Django 5.2 LTS
* PostgreSQL mit Unix-Socket und Peer-Authentifizierung (kein Datenbankpasswort)
* gunicorn hinter nginx mit HTTPS
* htmx für die Oberfläche
* WeasyPrint für die PDFs

Alle Schriften und Skripte werden lokal ausgeliefert, es gibt keine externen Abrufe.

**Sicherheit:**

* Passwörter mit Argon2
* Schutz vor dem Durchprobieren von Passwörtern
* Content-Security-Policy
* Geschützte Dateien nur nach Anmeldung
* Dienst ohne Root-Rechte mit systemd-Härtung
* Unveränderliches Aktivitätsprotokoll

---

## Entwicklung

Der Entwicklungsstand liegt auf dem Server unter `/srv/mietly-src`.

```bash
cd /srv/mietly-src
sudo bash tools/snapshot.sh "vor Änderung XY"   # Quellcode sichern (/var/backups/mietly-source)
sudo bash tools/run_tests.sh                     # automatisierte Tests
sudo bash tools/devserver.sh                     # Vorschau auf 127.0.0.1:8000 mit eigener Testdatenbank (mietly_dev)
sudo bash tools/build_release.sh                 # Installationspaket /root/mietly-releases/mietly-X.Y.Z.run
.venv/bin/python tools/build_assets.py           # Icon-Sprite aktualisieren (nach neuen Icons)
```

* Die Version steht in `mietly/version.py`.
* Vor größeren Änderungen und vor Datenbankmigrationen immer einen Snapshot anlegen.
* Ausgelieferte Versionen werden ausschließlich über das Installationspaket aktualisiert. Das legt automatisch ein Backup an.

### Version veröffentlichen

Der Quellcode liegt auf GitHub (devthoko/mietly). Eine neue Version entsteht über ein Tag:

1. Version in `mietly/version.py` erhöhen, Tests laufen lassen (`sudo bash tools/run_tests.sh`).
2. Committen, Tag `vX.Y.Z` setzen (muss zur Version passen) und beides pushen.
3. GitHub Actions (`.github/workflows/release.yml`) baut das Paket und legt das Release mit `install.sh`, `mietly-X.Y.Z.run` und der Prüfsumme an.

Die Tests decken unter anderem ab:

* alle verbindlichen Sperren (auch direkte Speicherversuche und Administratorrechte)
* die lückenlose Nummernvergabe
* Unveränderlichkeit und Storno von Rechnungen
* die Umsatzsteuerberechnung
* die Verfügbarkeitsprüfung
* den vollständigen Ablauf inkl. Schäden und Kaution
* das Rendern aller Seiten

---

## Rechtliche Hinweise

mietly unterstützt die Anforderungen an Rechnungen nach § 14 UStG, die Kleinunternehmerregelung nach § 19 UStG, die Unveränderlichkeit von Belegen (GoBD) und die Aufbewahrungsfristen (8 Jahre für Buchungsbelege, 6 Jahre für Geschäftsbriefe). Dazu kommen Datenauskunft und Anonymisierung nach DSGVO.

Die mitgelieferten Vorlagen sind ein sorgfältig formulierter Ausgangspunkt:

* Mietvertrag
* Mietbedingungen
* Widerrufsbelehrung
* Datenschutzhinweis

Sie ersetzen **keine rechtliche Beratung**. Bitte lassen Sie die Texte für Ihren Betrieb prüfen und unter Einstellungen → Vorlagen anpassen.

Digitale Unterschriften in mietly sind **einfache elektronische Signaturen**. Gespeichert werden:

* Name der unterzeichnenden Person
* Zeitpunkt
* Gerät
* Prüfsumme des Originals

Für Miet- und Angebotsverträge ohne gesetzliches Schriftformerfordernis ist das üblich und ausreichend.

---

*Verwendete freie Software: Django, PostgreSQL, nginx, gunicorn, htmx (BSD), WeasyPrint (BSD), Lucide Icons (ISC), Schriften EB Garamond und Source Sans 3 (SIL OFL).*
