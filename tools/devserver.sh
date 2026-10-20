#!/bin/bash
# Entwicklungs-Vorschau mit eigener Datenbank (mietly_dev) und eigenem Datenordner –
# die Produktivdaten bleiben unberührt. Konfiguration: /etc/mietly/dev.env
#   sudo bash tools/devserver.sh                 # Vorschau auf 127.0.0.1:8000
#   sudo bash tools/devserver.sh migrate         # beliebiger Verwaltungsbefehl
cd "$(dirname "$0")/.."
[ $# -eq 0 ] && set -- runserver 127.0.0.1:8000
exec runuser -u mietly -- bash -c 'set -a; . /etc/mietly/mietly.env; . /etc/mietly/dev.env; set +a; exec .venv/bin/python manage.py "$@"' _ "$@"
