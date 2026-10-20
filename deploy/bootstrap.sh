#!/bin/bash
# =============================================================================
# mietly – Installation mit einem Befehl
#
#   curl -fsSL https://github.com/devthoko/mietly/releases/download/vX.Y.Z/install.sh | sudo bash
#   curl -fsSL https://github.com/devthoko/mietly/releases/latest/download/install.sh | sudo bash
#
# Lädt das Installationspaket dieser Version von GitHub, prüft die Prüfsumme
# und startet es. Funktioniert für Erstinstallation und Update gleichermaßen.
# =============================================================================
# Das ganze Skript steckt in einer Funktion: Bricht der Download per curl mitten
# ab, wird keine halbe Datei ausgeführt.
main() {
    set -euo pipefail
    local version="__MIETLY_VERSION__"
    local repo="${MIETLY_REPO:-devthoko/mietly}"
    local base="https://github.com/$repo/releases/download/v$version"
    local name="mietly-$version.run"

    local c_err=$'\e[31m' c_b=$'\e[1m' c_off=$'\e[0m'
    die() { echo "${c_err}FEHLER: $*${c_off}" >&2; exit 1; }

    echo "${c_b}mietly $version – Installation${c_off}"
    [ "$(id -u)" -eq 0 ] || die "Bitte mit sudo ausführen:  curl -fsSL $base/install.sh | sudo bash"

    # Gleiche Prüfungen wie im Installer – vor dem Download des großen Pakets
    local os_id os_version
    os_id=$(. /etc/os-release; echo "${ID:-}")
    os_version=$(. /etc/os-release; echo "${VERSION_ID:-0}")
    [ "$os_id" = "ubuntu" ] || die "mietly unterstützt Ubuntu (gefunden: $os_id)."
    dpkg --compare-versions "$os_version" ge "26.04" || die "Ubuntu 26.04 LTS oder neuer erforderlich (gefunden: $os_version)."
    [ "$(uname -m)" = "x86_64" ] || die "Nur x86_64 wird unterstützt."

    if ! command -v curl >/dev/null || ! command -v sha256sum >/dev/null; then
        apt-get update -q >/dev/null && apt-get install -y -q curl coreutils >/dev/null
    fi

    local tmp
    tmp=$(mktemp -d /var/tmp/mietly-download.XXXXXX)
    trap 'rm -rf "$tmp"' EXIT

    echo "Lade $name …"
    curl -fL --retry 3 --progress-bar -o "$tmp/$name" "$base/$name" || die "Download fehlgeschlagen: $base/$name"
    curl -fsSL --retry 3 -o "$tmp/$name.sha256" "$base/$name.sha256" || die "Prüfsumme konnte nicht geladen werden."
    ( cd "$tmp" && sha256sum -c --quiet "$name.sha256" ) || die "Prüfsumme stimmt nicht – Datei beschädigt oder verändert. Abbruch."
    echo "Prüfsumme in Ordnung."

    # Der Installer soll nicht vom Pipe-Eingang (diesem Skript) lesen
    if (exec </dev/tty) 2>/dev/null; then
        bash "$tmp/$name" "$@" </dev/tty
    else
        bash "$tmp/$name" "$@" </dev/null
    fi
}

main "$@"
