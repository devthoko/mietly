#!/bin/bash
# Sichert den Entwicklungs-Quellcode (Ersatz für eine Versionsverwaltung).
# Vor jeder größeren Änderung oder Migration ausführen:
#   sudo bash tools/snapshot.sh "kurze Beschreibung"
# Snapshots liegen unter /var/backups/mietly-source/ (die letzten 60 bleiben erhalten).
set -euo pipefail
cd "$(dirname "$0")/.."
DEST=/var/backups/mietly-source
install -d -m 0700 "$DEST"
label=$(echo "${1:-snapshot}" | tr -cs '[:alnum:]-' '-' | sed 's/-*$//' | cut -c1-40)
file="$DEST/src-$(date +%Y%m%d-%H%M%S)-$label.tar.zst"
tar --exclude=./.venv --exclude=./staticfiles --exclude='__pycache__' --zstd -cf "$file" .
sha256sum "$file" > "$file.sha256"
ls -1t "$DEST"/src-*.tar.zst | tail -n +61 | while read -r old; do rm -f "$old" "$old.sha256"; done
echo "$file ($(du -h "$file" | cut -f1))"
