#!/bin/bash
# =============================================================================
# mietly – Installation und Update für Ubuntu (nativ, ohne Container)
#
#   Erstinstallation:  sudo bash mietly-X.Y.Z.run
#   Update:            sudo bash mietly-X.Y.Z.run      (erkennt eine bestehende Installation)
#
# Ablauf bei einem Update:
#   1. Vollbackup des aktuellen Stands
#   2. Neue Version neben der alten installieren
#   3. Datenbank migrieren, auf neue Version umschalten, Funktionsprüfung
#   4. Bei einem Fehler automatisch zurück auf die alte Version inkl. Backup
# =============================================================================
set -euo pipefail

SRC_DIR=$(cd "$(dirname "$0")" && pwd)
VERSION=$(cat "$SRC_DIR/VERSION")
APP_ROOT=/opt/mietly
RELEASES=$APP_ROOT/releases
CURRENT=$APP_ROOT/current
ETC=/etc/mietly
ENV_FILE=$ETC/mietly.env
DATA=/var/lib/mietly
BACKUPS=/var/backups/mietly
LOG=/var/log/mietly-install.log
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "----- $(date '+%d.%m.%Y %H:%M:%S') mietly $VERSION -----"

c_ok=$'\e[32m'; c_err=$'\e[31m'; c_b=$'\e[1m'; c_off=$'\e[0m'
step() { echo; echo "${c_b}==> $*${c_off}"; }
die()  { echo "${c_err}FEHLER: $*${c_off}" >&2; echo "Details: $LOG" >&2; exit 1; }

as_mietly() {
    # Befehl als Dienstbenutzer mit geladener Konfiguration ausführen
    runuser -u mietly -- bash -c 'set -a; . /etc/mietly/mietly.env; set +a; exec "$@"' _ "$@"
}

health_check() {
    for _ in $(seq 1 30); do
        if curl -fsk -o /dev/null --max-time 3 https://127.0.0.1/healthz; then return 0; fi
        sleep 1
    done
    return 1
}

# -----------------------------------------------------------------------------
step "Voraussetzungen prüfen"
[ "$(id -u)" -eq 0 ] || die "Bitte mit sudo ausführen."
OS_ID=$(. /etc/os-release; echo "${ID:-}")
OS_VERSION=$(. /etc/os-release; echo "${VERSION_ID:-0}")
[ "$OS_ID" = "ubuntu" ] || die "mietly unterstützt Ubuntu (gefunden: $OS_ID)."
dpkg --compare-versions "$OS_VERSION" ge "26.04" || die "Ubuntu 26.04 LTS oder neuer erforderlich (gefunden: $OS_VERSION) – die mitgelieferten Python-Pakete sind für Python 3.14 gebaut."
[ "$(uname -m)" = "x86_64" ] || die "Nur x86_64 wird unterstützt."
avail_mb=$(df -Pm /opt | awk 'NR==2 {print $4}')
[ "$avail_mb" -gt 1500 ] || die "Zu wenig freier Speicher unter /opt (${avail_mb} MB, benötigt mindestens 1,5 GB)."

MODE=install
OLD_TARGET=""
OLD_VERSION=""
if [ -e "$CURRENT" ] && [ -f "$ENV_FILE" ]; then
    MODE=update
    OLD_TARGET=$(readlink -f "$CURRENT")
    OLD_VERSION=$(cat "$CURRENT/VERSION" 2>/dev/null || echo "Entwicklungsstand")
    echo "Bestehende Installation gefunden: $OLD_VERSION → Update auf $VERSION"
    if [ "$OLD_VERSION" = "$VERSION" ] && [ $FORCE -eq 0 ]; then
        die "Version $VERSION ist bereits installiert (erneut installieren mit: --force)."
    fi
else
    echo "Neuinstallation von mietly $VERSION"
fi

# -----------------------------------------------------------------------------
step "Systempakete installieren"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q --no-install-recommends \
    postgresql nginx python3 python3-venv openssl curl zstd tar locales tzdata \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-ebgaramond fonts-adobe-sourcesans3 fontconfig \
    cups cups-client cups-filters cups-ipp-utils hplip printer-driver-gutenprint printer-driver-brlaser >/dev/null
echo "Pakete sind installiert."

# -----------------------------------------------------------------------------
step "Sprache und Zeitzone"
if ! locale -a 2>/dev/null | grep -qi '^de_DE\.utf8$'; then
    sed -i 's/^# *de_DE.UTF-8 UTF-8/de_DE.UTF-8 UTF-8/' /etc/locale.gen
    grep -q '^de_DE.UTF-8 UTF-8' /etc/locale.gen || echo "de_DE.UTF-8 UTF-8" >> /etc/locale.gen
    locale-gen >/dev/null
    systemctl restart postgresql
fi
if [ "$MODE" = install ]; then
    tz=$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo UTC)
    if [ "$tz" = "Etc/UTC" ] || [ "$tz" = "UTC" ]; then
        timedatectl set-timezone Europe/Berlin 2>/dev/null || ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime
        echo "Europe/Berlin" > /etc/timezone
        echo "Zeitzone auf Europe/Berlin gesetzt."
    fi
fi

# -----------------------------------------------------------------------------
step "Benutzer und Verzeichnisse"
id mietly >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin mietly
usermod -aG mietly www-data
# Drucker: mietly darf seine eigene CUPS-Warteschlange einrichten (CUPS lauscht nur lokal)
usermod -aG lpadmin mietly
install -d -o root -g root -m 0755 "$APP_ROOT" "$RELEASES"
install -d -o root -g mietly -m 0750 "$ETC"
install -d -o mietly -g mietly -m 0750 "$DATA" "$DATA/media"
install -d -o mietly -g mietly -m 0750 "$BACKUPS"

# -----------------------------------------------------------------------------
step "Datenbank"
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='mietly'" | grep -q 1; then
    runuser -u postgres -- createuser mietly
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='mietly'" | grep -q 1; then
    runuser -u postgres -- createdb -O mietly -E UTF8 --template=template0 \
        --locale=de_DE.UTF-8 --locale-provider=icu --icu-locale=de-DE mietly
    echo "Datenbank angelegt."
else
    echo "Datenbank vorhanden."
fi

# -----------------------------------------------------------------------------
step "Konfiguration"
if [ ! -f "$ENV_FILE" ]; then
    hosts="localhost,127.0.0.1,$(hostname)"
    origins=""
    for ip in $(hostname -I); do
        case "$ip" in *:*) continue ;; esac
        hosts="$hosts,$ip"
        origins="${origins:+$origins,}https://$ip"
    done
    origins="${origins:+$origins,}https://$(hostname)"
    secret=$(openssl rand -base64 48 | tr -d '\n/+=')
    enc=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')
    cat > "$ENV_FILE" <<EOF
# mietly – Konfiguration (wird von systemd und dem Befehl "mietly" geladen)
# ACHTUNG: Enthält geheime Schlüssel. Ohne MIETLY_ENCRYPTION_KEY lassen sich
# gespeicherte Zugangsdaten (SMTP/WebDAV) nicht mehr entschlüsseln.
MIETLY_SECRET_KEY=$secret
MIETLY_ENCRYPTION_KEY=$enc
# Adressen, unter denen mietly erreichbar ist (kommagetrennt)
MIETLY_ALLOWED_HOSTS=$hosts
MIETLY_CSRF_TRUSTED_ORIGINS=$origins
MIETLY_DATA_DIR=$DATA
MIETLY_BACKUP_DIR=$BACKUPS
MIETLY_DB_NAME=mietly
MIETLY_USE_X_ACCEL=1
MIETLY_DEBUG=0
EOF
    echo "Konfiguration erstellt: $ENV_FILE"
fi
chown root:mietly "$ENV_FILE"
chmod 0640 "$ENV_FILE"

install -d -o root -g www-data -m 0750 "$ETC/tls"
if [ ! -f "$ETC/tls/mietly.crt" ]; then
    san="DNS:$(hostname),DNS:localhost,IP:127.0.0.1"
    for ip in $(hostname -I); do case "$ip" in *:*) ;; *) san="$san,IP:$ip" ;; esac; done
    openssl req -x509 -newkey rsa:3072 -sha256 -days 3650 -nodes \
        -keyout "$ETC/tls/mietly.key" -out "$ETC/tls/mietly.crt" \
        -subj "/CN=$(hostname)/O=mietly" -addext "subjectAltName=$san" 2>/dev/null
    chgrp www-data "$ETC/tls/mietly.key"
    chmod 0640 "$ETC/tls/mietly.key"
    echo "Selbstsigniertes Zertifikat erstellt (10 Jahre gültig)."
fi

# -----------------------------------------------------------------------------
BACKUP_FILE=""
if [ "$MODE" = update ]; then
    step "Backup vor dem Update"
    BACKUP_FILE=$(as_mietly "$CURRENT/.venv/bin/python" "$CURRENT/manage.py" backup --reason "vor-update-$VERSION" | tail -1) \
        || die "Das Backup ist fehlgeschlagen – Update abgebrochen, es wurde nichts verändert."
    [ -f "$BACKUP_FILE" ] || die "Backup-Datei nicht gefunden – Update abgebrochen."
    echo "Backup: $BACKUP_FILE"
fi

# -----------------------------------------------------------------------------
step "Version $VERSION installieren"
TARGET="$RELEASES/$VERSION"
if [ -e "$TARGET" ]; then
    if [ "$(readlink -f "$TARGET")" = "$OLD_TARGET" ]; then
        TARGET="$RELEASES/$VERSION-$(date +%Y%m%d%H%M%S)"
    else
        rm -rf "$TARGET"
    fi
fi
mkdir -p "$TARGET"
tar -C "$SRC_DIR" --exclude=./wheels --exclude=./install.sh -cf - . | tar -C "$TARGET" --no-same-owner -xf -
python3 -m venv "$TARGET/.venv"
"$TARGET/.venv/bin/pip" install -q --no-index --find-links "$SRC_DIR/wheels" -r "$TARGET/requirements.txt"
# Statische Dateien mit Inhalts-Hash im Namen (sicheres Caching nach Updates)
( cd "$TARGET" && set -a && . "$ENV_FILE" && set +a && "$TARGET/.venv/bin/python" manage.py collectstatic --noinput --clear -v0 )
# Vorkomprimierte Fassungen für nginx (gzip_static) – spart die Komprimierung bei jedem Abruf
find "$TARGET/staticfiles" -type f \( -name "*.css" -o -name "*.js" -o -name "*.svg" -o -name "*.json" \) -size +512c -exec gzip -k -9 -n -f {} +
find "$TARGET" -path "$TARGET/.venv" -prune -o -type d -exec chmod 755 {} + -o -type f -exec chmod 644 {} +
chmod 755 "$TARGET/deploy/mietly" "$TARGET/deploy/install.sh" 2>/dev/null || true
chown -R root:root "$TARGET"
echo "Installiert nach $TARGET"

rollback() {
    echo "${c_err}Fehler beim Update – stelle den vorherigen Stand wieder her …${c_off}"
    systemctl stop mietly || true
    ln -sfn "$OLD_TARGET" "$CURRENT.new" && mv -T "$CURRENT.new" "$CURRENT"
    install -m 0755 "$OLD_TARGET/deploy/mietly" /usr/local/bin/mietly 2>/dev/null || true
    if [ -n "$BACKUP_FILE" ]; then
        /usr/local/bin/mietly restore "$BACKUP_FILE" --ja || true
    fi
    systemctl start mietly || true
    die "Das Update auf $VERSION ist fehlgeschlagen. Version $OLD_VERSION ist wieder aktiv."
}

# -----------------------------------------------------------------------------
step "Datenbank aktualisieren"
[ "$MODE" = update ] && systemctl stop mietly
if ! ( cd "$TARGET" && as_mietly "$TARGET/.venv/bin/python" "$TARGET/manage.py" migrate --noinput ); then
    [ "$MODE" = update ] && rollback
    die "Die Datenbankmigration ist fehlgeschlagen."
fi
( cd "$TARGET" && as_mietly "$TARGET/.venv/bin/python" "$TARGET/manage.py" check --deploy --fail-level ERROR >/dev/null 2>&1 ) \
    || { [ "$MODE" = update ] && rollback; die "Die Konfigurationsprüfung ist fehlgeschlagen."; }

# -----------------------------------------------------------------------------
step "Dienste einrichten"
ln -sfn "$TARGET" "$CURRENT.new" && mv -T "$CURRENT.new" "$CURRENT"
install -m 0644 "$TARGET"/deploy/systemd/mietly.service "$TARGET"/deploy/systemd/mietly-backup.service \
    "$TARGET"/deploy/systemd/mietly-backup.timer "$TARGET"/deploy/systemd/mietly-mail.service \
    "$TARGET"/deploy/systemd/mietly-mail.timer /etc/systemd/system/
install -m 0755 "$TARGET/deploy/mietly" /usr/local/bin/mietly
install -m 0644 "$TARGET/deploy/nginx/mietly.conf" /etc/nginx/sites-available/mietly.conf
ln -sfn /etc/nginx/sites-available/mietly.conf /etc/nginx/sites-enabled/mietly.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t >/dev/null 2>&1 || { [ "$MODE" = update ] && rollback; die "Die nginx-Konfiguration ist ungültig (nginx -t)."; }
systemctl daemon-reload
systemctl enable -q mietly.service mietly-backup.timer mietly-mail.timer nginx postgresql
systemctl restart mietly
systemctl start mietly-backup.timer mietly-mail.timer
systemctl reload nginx || systemctl restart nginx

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null
fi

# -----------------------------------------------------------------------------
step "Funktionsprüfung"
if health_check; then
    echo "${c_ok}mietly antwortet.${c_off}"
else
    [ "$MODE" = update ] && rollback
    die "mietly antwortet nicht. Protokoll: sudo mietly logs"
fi

# -----------------------------------------------------------------------------
FIRST_LOGIN=""
if [ "$(as_mietly "$CURRENT/.venv/bin/python" "$CURRENT/manage.py" shell -c 'from apps.core.models import User; print(User.objects.filter(is_active=True).count())' 2>/dev/null | tail -1)" = "0" ]; then
    step "Ersten Administrator anlegen"
    pw=$(openssl rand -base64 18 | tr -d '\n/+=' | cut -c1-16)
    as_mietly env MIETLY_ADMIN_PW="$pw" "$CURRENT/.venv/bin/python" "$CURRENT/manage.py" \
        create_admin --username admin --first-name Inhaber --password-env MIETLY_ADMIN_PW >/dev/null
    umask 077
    printf "mietly – Erstzugang\nBenutzer: admin\nPasswort: %s\n\nBitte nach der ersten Anmeldung unter „Profil“ ändern und diese Datei löschen.\n" "$pw" > /root/mietly-erstzugang.txt
    FIRST_LOGIN=1
fi

# Alte Versionen aufräumen (die drei neuesten bleiben für ein Rollback erhalten)
ls -1dt "$RELEASES"/*/ 2>/dev/null | sed 's#/$##' | tail -n +4 | while read -r old; do
    [ "$old" = "$(readlink -f "$CURRENT")" ] || [ "$old" = "$OLD_TARGET" ] || rm -rf "$old"
done

# -----------------------------------------------------------------------------
echo
echo "${c_ok}${c_b}mietly $VERSION ist bereit.${c_off}"
for ip in $(hostname -I); do case "$ip" in *:*) ;; *) echo "  Adresse:  https://$ip" ;; esac; done
echo "  Verwaltung: sudo mietly status | logs | backup | restore | update | rollback"
if [ -n "$FIRST_LOGIN" ]; then
    echo "  Erstzugang: Benutzer „admin“, Passwort in /root/mietly-erstzugang.txt"
fi
if [ "$MODE" = update ]; then
    echo "  Update von $OLD_VERSION abgeschlossen. Backup davor: $BACKUP_FILE"
fi
echo "  Hinweis: Das Zertifikat ist selbstsigniert – der Browser fragt beim ersten Aufruf einmalig nach."
