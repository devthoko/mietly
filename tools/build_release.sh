#!/bin/bash
# Baut das Installations- und Updatepaket  mietly-X.Y.Z.run
# Es enthält den Quellcode und alle Python-Pakete (Installation ohne PyPI-Zugriff).
#
# Aufruf auf dem Entwicklungsserver:  sudo bash tools/build_release.sh [Zielordner]
# In der CI (GitHub Actions):         SKIP_TESTS=1 PYTHON=python3 bash tools/build_release.sh dist
#
# Zusätzlich entsteht install.sh – das Startskript für die Installation mit einem Befehl
# (curl … /install.sh | sudo bash), das genau dieses Paket lädt und prüft.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=$(pwd)
PYTHON=${PYTHON:-.venv/bin/python}
# Die Pakete werden für die Python-Version des Zielsystems geladen (Ubuntu 26.04: Python 3.14),
# unabhängig davon, mit welchem Python gebaut wird.
TARGET_PY=${TARGET_PY:-3.14}
VERSION=$("$PYTHON" -c "import sys; sys.path.insert(0, '.'); from mietly.version import VERSION; print(VERSION)")
OUT=${1:-/root/mietly-releases}
NAME="mietly-$VERSION"
mkdir -p "$OUT"
BUILD=$(mktemp -d /var/tmp/mietly-build.XXXXXX)
trap 'rm -rf "$BUILD"' EXIT

echo "==> Shell-Skripte prüfen"
for f in deploy/mietly deploy/install.sh deploy/bootstrap.sh tools/*.sh; do bash -n "$f" || { echo "Syntaxfehler in $f"; exit 1; }; done

if [ "${SKIP_TESTS:-0}" = "1" ]; then
    echo "==> Tests übersprungen (SKIP_TESTS=1 – laufen vor dem Taggen auf dem Entwicklungsserver)"
else
    echo "==> Tests"
    bash tools/run_tests.sh -q >/dev/null || { echo "Tests fehlgeschlagen – kein Paket erstellt."; exit 1; }
    echo "    alle Tests bestanden"
fi

echo "==> Quellcode"
mkdir -p "$BUILD/$NAME"
tar --exclude=./.venv --exclude=./staticfiles --exclude='__pycache__' --exclude='*.pyc' \
    --exclude=./var --exclude=./tools/vendor --exclude=./.git --exclude=./.github --exclude=./dist -cf - . | tar -C "$BUILD/$NAME" -xf -
echo "$VERSION" > "$BUILD/$NAME/VERSION"
cp deploy/install.sh "$BUILD/$NAME/install.sh"

echo "==> Python-Pakete"
py_tag="cp${TARGET_PY/./}"
platforms=""
for p in manylinux2014_x86_64 manylinux_2_17_x86_64 manylinux_2_27_x86_64 manylinux_2_28_x86_64 manylinux_2_31_x86_64 manylinux_2_34_x86_64 manylinux_2_35_x86_64 manylinux_2_39_x86_64; do
    platforms="$platforms --platform $p"
done
# shellcheck disable=SC2086
"$PYTHON" -m pip download -q --only-binary=:all: --python-version "$TARGET_PY" --implementation cp --abi "$py_tag" --abi abi3 --abi none \
    $platforms --platform any -r requirements.txt -d "$BUILD/$NAME/wheels"
ls "$BUILD/$NAME/wheels" | wc -l | xargs echo "    Pakete:"

echo "==> Paket schreiben"
tar -C "$BUILD" -czf "$BUILD/payload.tar.gz" "$NAME"
RUN="$OUT/$NAME.run"
cat > "$RUN" <<'HEADER'
#!/bin/bash
# mietly – Installations- und Updatepaket
# Aufruf:  sudo bash DIESE-DATEI.run
set -e
if [ "$(id -u)" -ne 0 ]; then echo "Bitte mit sudo ausführen: sudo bash $0"; exit 1; fi
TMP=$(mktemp -d /var/tmp/mietly-install.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
LINE=$(awk '/^__MIETLY_ARCHIVE__$/ { print NR + 1; exit 0 }' "$0")
tail -n +"$LINE" "$0" | tar -xz -C "$TMP"
bash "$TMP"/mietly-*/install.sh "$@"
exit $?
__MIETLY_ARCHIVE__
HEADER
cat "$BUILD/payload.tar.gz" >> "$RUN"
chmod 755 "$RUN"
( cd "$OUT" && sha256sum "$NAME.run" > "$NAME.run.sha256" )
sed "s/__MIETLY_VERSION__/$VERSION/" deploy/bootstrap.sh > "$OUT/install.sh"
chmod 755 "$OUT/install.sh"
echo "Fertig: $RUN ($(du -h "$RUN" | cut -f1))"
