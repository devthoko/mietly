# Betrieb

<sub>[← Zurück zur Übersicht](../README.md) · [Installation](installation.md) · [Betrieb](betrieb.md) · [Funktionen](funktionen.md) · [Entwicklung](entwicklung.md) · [Rechtliches](recht.md)</sub>

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

## Konfiguration

### In der Oberfläche (Einstellungen)

| Bereich | Inhalt |
|---|---|
| Geschäftsdaten | Name, Anschrift, Kontakt, Logo – erscheinen auf allen Dokumenten |
| Steuer & Bank | Steuernummer/USt-IdNr., Kleinunternehmerregelung, Steuersatz, Bankverbindung |
| Geschäftsregeln | Angebotsgültigkeit, Zahlungsziel, inklusive Miettage, Puffertage, Kaution vor Übergabe, Stornobedingungen, Lieferpauschale |
| Vorlagen | Mietvertrag, Mietbedingungen, Widerrufsbelehrung, Datenschutzhinweis, Dokument- und E-Mail-Texte (mit Platzhaltern und Versionsverlauf) |
| E-Mail | SMTP-Server, Absender, BCC, Anrede (förmlich oder persönlich), Testversand, Versandprotokoll |
| Drucker | Netzwerkdrucker per IP-Adresse einbinden: Modell und Treiber werden automatisch erkannt (treiberlos per IPP Everywhere/AirPrint, sonst HPLIP, Gutenprint oder brlaser), anschließend wird eine Testseite gedruckt. Danach haben alle Dokumente einen Knopf „Drucken“. Gedruckt wird immer in Schwarz-Weiß. |
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

