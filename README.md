> [!NOTE]
> ### Ein paar ehrliche Worte vorab
>
> mietly ist für meine Mama entstanden. Sie möchte sich mit einem Verleih selbstständig machen – und Computer sind, sagen wir mal, nicht so ganz ihre Welt. Ich wollte nicht, dass sie sich zwischen Tabellen, Vorlagen, E-Mails und Zetteln verliert, sondern dass sie jeden Morgen einfach sieht, was als Nächstes dran ist. Also habe ich den ganzen Weg in eine einzige Anwendung gepackt: vom ersten Angebot bis zu dem Moment, in dem die Kaution zurück beim Kunden ist. Damit sie den Kopf frei hat für das, was ihr wirklich Spaß macht – ihre Kundinnen und Kunden und deren Feiern.
>
> Und weil Ehrlichkeit dazugehört: **Den Code habe nicht ich geschrieben, sondern zu 100 % eine KI.** Mit Sicherheitskonzepten in Software kenne ich mich gut aus und weiß, worauf es dabei ankommt. Das Programmieren selbst ist aber einfach nicht meins. Neben einem 40-Stunden-Job habe ich weder die Zeit, so eine Anwendung allein zu bauen, noch, das Programmieren nebenher richtig zu lernen. Die KI hat es mir möglich gemacht, trotzdem etwas Brauchbares für meine Mama auf die Beine zu stellen – und darüber bin ich froh.
>
> Genau deshalb bitte ich dich aber auch um Vorsicht: **Stell mietly nicht offen ins Internet.** Betreibe es im eigenen Netzwerk, und wenn du von unterwegs darauf zugreifen möchtest, dann über ein VPN. Auch wenn beim Bauen auf Sicherheit geachtet wurde: So weit, dass ich Kundendaten ungeschützt im Internet anvertrauen würde, traue ich der KI nicht.
>
> Wenn du mietly selbst ausprobierst: Schön, dass du hier bist! Das hier ist ein Familienprojekt und kein Produkt einer Softwarefirma. Wenn dir etwas auffällt – ein Fehler, eine Idee oder einfach ein Gedanke –, freue ich mich über eine Nachricht. 💛

<div align="center">

<img src="docs/assets/logo.svg" width="88" alt="mietly">

# mietly

**Die Verwaltung für Event- und Dekorationsverleihe.**<br>
Vom ersten Angebot bis zur zurückgezahlten Kaution – auf deinem eigenen Server.

[![Release](https://img.shields.io/github/v/release/devthoko/mietly?label=Version&color=5f7a5b)](https://github.com/devthoko/mietly/releases/latest)
![Ubuntu 26.04](https://img.shields.io/badge/Ubuntu-26.04_LTS-E95420?logo=ubuntu&logoColor=white)
![Django 5.2 LTS](https://img.shields.io/badge/Django-5.2_LTS-0C4B33?logo=django&logoColor=white)
![Self-hosted](https://img.shields.io/badge/self--hosted-ohne_Cloud-b97a6c)
![Kein Docker](https://img.shields.io/badge/nativ-kein_Docker-6c7f99)

[Installation](#-installation) · [Funktionen](#-was-mietly-kann) · [Ablauf](#-der-weg-eines-auftrags) · [Betrieb](#-betrieb) · [Dokumentation](#-dokumentation)

</div>

---

## 🚀 Installation

Ein Befehl auf einem frischen **Ubuntu 26.04 LTS** Server:

```bash
curl -fsSL https://github.com/devthoko/mietly/releases/latest/download/install.sh | sudo bash
```

Danach `https://<IP-des-Servers>` im Browser öffnen und mit dem angezeigten Erstzugang anmelden.

> [!TIP]
> Derselbe Befehl **aktualisiert** eine bestehende Installation – mit Backup vorab und automatischem Rücksprung, falls etwas schiefgeht.

<details>
<summary>Was der Installer einrichtet</summary>

<br>

PostgreSQL · nginx mit HTTPS · Systemdienst · nächtliches Backup · E-Mail-Wiederholung · Druckdienst (CUPS) · deutsche Sprache und Zeitzone.
Die Anwendung startet **leer** – ohne Kunden, Aufträge oder Beispieldaten. Das Paket wird vor dem Start per SHA-256 geprüft.

Weitere Wege (Installationsdatei, feste Version, Umzug): [docs/installation.md](docs/installation.md)

</details>

---

## ✨ Was mietly kann

<table>
<tr>
<td width="50%" valign="top">

### 🗂️ Auftragsakte in 9 Schritten
Jeder Auftrag zeigt, wo er steht, was fehlt und was als Nächstes zu tun ist – mit direktem Knopf zur nächsten Aktion.

</td>
<td width="50%" valign="top">

### ✍️ Unterschrift auf dem Tablet
Angebot, Vertrag und Übergabeprotokoll direkt digital unterschreiben – oder das unterschriebene PDF hochladen.

</td>
</tr>
<tr>
<td valign="top">

### 📦 Keine Doppelbuchungen
Verfügbarkeit je Artikel und Paket im Mietzeitraum, inklusive Puffertagen für die Reinigung.

</td>
<td valign="top">

### 🧾 Saubere Rechnungen
Lückenlose Nummern, § 14 UStG, Kleinunternehmerregelung, Storno- und Nachberechnung, unveränderlich nach GoBD.

</td>
</tr>
<tr>
<td valign="top">

### 💶 Kaution im Griff
Schäden und Fehlmengen mit der Kaution verrechnen oder nachberechnen – mit fertiger Abrechnung für den Kunden.

</td>
<td valign="top">

### 📨 Mail & Druck
PDFs per E-Mail mit automatischer Wiederholung bei Störungen. Netzwerkdrucker per IP – Treiber kommt automatisch.

</td>
</tr>
<tr>
<td valign="top">

### 📱 Desktop, Tablet, Handy
Zwei Gestaltungen (warm oder klar), Hell- und Dunkelmodus, große Touch-Flächen für das Lager.

</td>
<td valign="top">

### 🔐 Deine Daten bleiben bei dir
Läuft im eigenen Netz, ohne Cloud. Tägliche Backups, Wiederherstellung mit einem Befehl, optional verschlüsselt in die Nextcloud.

</td>
</tr>
</table>

→ Alle Funktionen im Detail: [docs/funktionen.md](docs/funktionen.md)

---

## 🧭 Der Weg eines Auftrags

<p align="center"><img src="docs/assets/ablauf.svg" width="820" alt="Der Weg eines Auftrags: Kunde, Event, Angebot – Mietvertrag, Rechnung, Packliste – Übergabe, Rücknahme, Kaution und Abschluss"></p>

Vier Regeln sind **fest eingebaut** und gelten für alle – auch für Administratoren:

| 🔒 | Erst wenn … | … geht es weiter mit |
|---|---|---|
| 1 | das Angebot unterschrieben ist | dem Mietvertrag |
| 2 | der Mietvertrag unterschrieben ist | der Rechnung |
| 3 | die Rechnung vollständig bezahlt ist | der Übergabe |
| 4 | das Übergabeprotokoll unterschrieben ist | dem Abschluss der Übergabe |

---

## 🛠️ Betrieb

| Aufgabe | Befehl |
|---|---|
| Zustand prüfen | `sudo mietly status` |
| Backup jetzt | `sudo mietly backup` |
| Backup einspielen | `sudo mietly restore <datei>` |
| Update | Installations-Einzeiler erneut ausführen |
| Zurück zur Vorversion | `sudo mietly rollback` |
| Protokoll ansehen | `sudo mietly logs -f` |

Backups laufen jede Nacht automatisch (14 tägliche, 8 wöchentliche, 12 monatliche).
Details zu Konfiguration, Zertifikat, Backup und Fehlerbehebung: [docs/betrieb.md](docs/betrieb.md)

---

## 📚 Dokumentation

| | |
|---|---|
| 📥 [Installation & Updates](docs/installation.md) | Voraussetzungen, Erstzugang, Updates, Umzug |
| 🛠️ [Betrieb](docs/betrieb.md) | Konfiguration, Backup, Wiederherstellung, Fehlerbehebung |
| ✨ [Funktionen](docs/funktionen.md) | Alles, was mietly kann |
| 👩‍💻 [Entwicklung](docs/entwicklung.md) | Tests, Vorschau, Version veröffentlichen |
| ⚖️ [Rechtliches](docs/recht.md) | Rechnungen, GoBD, DSGVO, digitale Unterschrift |

---

<div align="center">
<sub>

**Technik:** Python · Django 5.2 LTS · PostgreSQL · nginx · htmx · WeasyPrint<br>
Alle Schriften und Skripte werden lokal ausgeliefert – keine externen Abrufe. · [Lizenzen der Fremdbestandteile](licenses/README.md)

</sub>
</div>
