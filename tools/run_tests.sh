#!/bin/bash
# Führt die automatisierten Tests aus (als Datenbank-Superuser, damit eine Testdatenbank angelegt werden kann).
# Aufruf auf dem Server:  sudo bash tools/run_tests.sh [pytest-Optionen]
set -euo pipefail
cd "$(dirname "$0")/.."
TMP=$(mktemp -d /tmp/mietly-test.XXXXXX)
chown postgres "$TMP"
trap 'rm -rf "$TMP"' EXIT
exec runuser -u postgres -- env HOME="$TMP" MIETLY_TESTING=1 MIETLY_SECURE=0 \
    MIETLY_DATA_DIR="$TMP/data" MIETLY_BACKUP_DIR="$TMP/backups" \
    .venv/bin/pytest "$@"
