# Entwicklung

<sub>[← Zurück zur Übersicht](../README.md) · [Installation](installation.md) · [Betrieb](betrieb.md) · [Funktionen](funktionen.md) · [Entwicklung](entwicklung.md) · [Rechtliches](recht.md)</sub>

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

