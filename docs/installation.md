# Installation & Updates

<sub>[← Zurück zur Übersicht](../README.md) · [Installation](installation.md) · [Betrieb](betrieb.md) · [Funktionen](funktionen.md) · [Entwicklung](entwicklung.md) · [Rechtliches](recht.md)</sub>

## Systemvoraussetzungen

| | Minimum | Empfohlen |
|---|---|---|
| Betriebssystem | Ubuntu 26.04 LTS (x86_64) | Ubuntu 26.04 LTS |
| CPU | 1 Kern | 2–4 Kerne |
| Arbeitsspeicher | 1 GB | 2–4 GB |
| Speicherplatz | 5 GB | 30 GB (Fotos und Backups wachsen mit) |
| Netzwerk | Internetzugang während der Installation (Ubuntu-Paketquellen) | |

mietly installiert sich **nativ** – ohne Docker oder andere Container. Folgende Ubuntu-Pakete werden automatisch eingerichtet: PostgreSQL, nginx, Python 3 (venv), Pango (für PDFs), die Schriften EB Garamond und Source Sans 3, zstd sowie CUPS mit gängigen Druckertreibern (HPLIP, Gutenprint, brlaser). CUPS ist nur lokal erreichbar; der Dienstbenutzer `mietly` ist Mitglied der Gruppe `lpadmin`, um seine Druckerwarteschlange selbst einzurichten.

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
   scp mietly-X.Y.Z.run root@SERVER:/root/
   ```

2. Auf dem Server **ein Befehl**:

   ```bash
   sudo bash mietly-X.Y.Z.run
   ```

Der Installer richtet Pakete, Sprache (de_DE.UTF-8), Zeitzone (Europe/Berlin), Systembenutzer, Datenbank, Konfiguration, HTTPS-Zertifikat, Dienste und das nächtliche Backup ein. Danach prüft er, ob mietly antwortet. Am Ende werden die Adresse und der Erstzugang angezeigt.

Die Prüfsumme der Installationsdatei lässt sich vorher kontrollieren:

```bash
sha256sum -c mietly-X.Y.Z.run.sha256
```

## Erste Schritte

1. Im Browser `https://<IP-des-Servers>` öffnen. Das Zertifikat ist selbstsigniert, deshalb fragt der Browser beim ersten Aufruf einmalig nach (siehe [Eigenes Zertifikat](betrieb.md#eigenes-zertifikat)).
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

## Updates

Neue Versionen werden genauso installiert wie die erste:

```bash
sudo bash mietly-X.Y.Z.run
```

Der Installer erkennt die bestehende Installation und arbeitet diese Schritte ab:

1. **Vollbackup** des aktuellen Stands (`…-vor-update-X.Y.Z.tar.zst`)
2. Neue Version **neben** der alten installieren (`/opt/mietly/releases/X.Y.Z`)
3. Datenbank migrieren, auf die neue Version umschalten, Funktionsprüfung
4. Bei einem Fehler **automatisch zurück** zur alten Version, inklusive Wiederherstellung des Backups

Die drei neuesten Versionen bleiben erhalten. Manuell zurückkehren:

```bash
sudo mietly rollback
```

`rollback` aktiviert die vorherige Version und spielt das Backup vor dem letzten Update zurück. Daten, die seit dem Update erfasst wurden, gehen dabei verloren; der Befehl fragt deshalb vorher nach.

Am einfachsten aktualisiert derselbe Einzeiler wie bei der Installation:

```bash
curl -fsSL https://github.com/devthoko/mietly/releases/latest/download/install.sh | sudo bash
```

## Umzug auf einen anderen Server

1. Auf dem alten Server ein frisches Backup erstellen: `sudo mietly backup`
2. Auf dem neuen Server mietly installieren (Einzeiler oben).
3. Backup und `.sha256`-Datei kopieren und einspielen:

   ```bash
   sudo mietly restore /root/mietly-backup-DATUM.tar.zst --mit-konfiguration
   ```

4. Neue Adresse in `/etc/mietly/mietly.env` bei `MIETLY_ALLOWED_HOSTS` und `MIETLY_CSRF_TRUSTED_ORIGINS` eintragen, dann `sudo mietly restart`.
5. Drucker unter **Einstellungen → Drucker** neu einrichten – die Druckerwarteschlange gehört zum Betriebssystem und ist nicht im Backup.
6. Alten Server stilllegen: `sudo mietly stop`
