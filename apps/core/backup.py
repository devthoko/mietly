"""Backups: Datenbank, Dateien und Konfiguration in einem Archiv.

Ein Backup ist eine Datei  mietly-backup-JJJJ-MM-TT_HHMMSS[-anlass].tar.zst
mit folgendem Inhalt:
  database.dump      PostgreSQL-Dump (pg_dump, custom format)
  media/             alle Dokumente, Fotos, Uploads
  mietly.env         Konfiguration inkl. Schlüssel (nötig für verschlüsselte Zugangsdaten)
  manifest.json      Version, Zeitpunkt, Prüfsummen
Daneben liegt eine .sha256-Datei. Die Wiederherstellung erfolgt mit
`sudo mietly restore <datei>`.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

PREFIX = "mietly-backup-"
SUFFIX = ".tar.zst"
LOCK = ".backup.lock"
ERROR_FILE = ".last-error"
ENV_FILE = Path(os.environ.get("MIETLY_ENV_FILE", "/etc/mietly/mietly.env"))


class BackupError(Exception):
    pass


def backup_dir() -> Path:
    return Path(settings.BACKUP_DIR)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_running():
    lock = backup_dir() / LOCK
    if not lock.exists():
        return False
    # Verwaiste Sperren (älter als 2 Stunden) ignorieren
    age = datetime.now().timestamp() - lock.stat().st_mtime
    return age < 7200


def last_error():
    f = backup_dir() / ERROR_FILE
    return f.read_text(encoding="utf-8") if f.exists() else ""


def list_backups():
    d = backup_dir()
    if not d.exists():
        return []
    result = []
    for p in sorted(d.glob(f"{PREFIX}*{SUFFIX}"), reverse=True):
        stat = p.stat()
        checksum_file = p.with_name(p.name + ".sha256")
        parts = p.name[len(PREFIX):-len(SUFFIX)].split("-", 3)
        result.append({
            "name": p.name,
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
            "verified": checksum_file.exists(),
            "reason": parts[3] if len(parts) == 4 else "",
        })
    return result


def backup_path(name):
    if "/" in name or not (name.startswith(PREFIX) and name.endswith(SUFFIX)):
        return None
    p = backup_dir() / name
    return p if p.is_file() else None


def create_backup(reason: str = "") -> Path:
    """Erstellt synchron ein vollständiges Backup und gibt den Pfad zurück."""
    target_dir = backup_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    lock = target_dir / LOCK
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        if is_running():
            raise BackupError("Es läuft bereits ein Backup.")
        lock.unlink(missing_ok=True)
        return create_backup(reason)

    stamp = timezone.localtime().strftime("%Y-%m-%d_%H%M%S")
    safe_reason = "".join(c for c in reason.lower() if c.isalnum() or c == "-")[:30]
    name = f"{PREFIX}{stamp}{'-' + safe_reason if safe_reason else ''}{SUFFIX}"
    final = target_dir / name
    try:
        with tempfile.TemporaryDirectory(dir=target_dir, prefix=".tmp-") as tmp:
            tmp = Path(tmp)
            db = settings.DATABASES["default"]
            env = os.environ.copy()
            if db.get("PASSWORD"):
                env["PGPASSWORD"] = db["PASSWORD"]
            cmd = ["pg_dump", "--format=custom", "--no-owner", "--file", str(tmp / "database.dump")]
            if db.get("HOST"):
                cmd += ["--host", db["HOST"]]
            if db.get("PORT"):
                cmd += ["--port", str(db["PORT"])]
            if db.get("USER"):
                cmd += ["--username", db["USER"]]
            cmd.append(db["NAME"])
            run = subprocess.run(cmd, env=env, capture_output=True, text=True)
            if run.returncode != 0:
                raise BackupError(f"pg_dump fehlgeschlagen: {run.stderr.strip()}")

            members = ["database.dump"]
            if settings.MEDIA_ROOT.exists():
                os.symlink(settings.MEDIA_ROOT, tmp / "media")
                members.append("media")
            if ENV_FILE.exists() and os.access(ENV_FILE, os.R_OK):
                shutil.copy2(ENV_FILE, tmp / "mietly.env")
                os.chmod(tmp / "mietly.env", 0o600)
                members.append("mietly.env")

            manifest = {
                "version": settings.MIETLY_VERSION,
                "created": timezone.now().isoformat(),
                "reason": reason,
                "database_sha256": _sha256(tmp / "database.dump"),
                "media_files": sum(len(files) for _, _, files in os.walk(settings.MEDIA_ROOT)) if settings.MEDIA_ROOT.exists() else 0,
            }
            (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            members.append("manifest.json")

            partial = target_dir / f".{name}.partial"
            run = subprocess.run(
                ["tar", "--dereference", "--zstd", "-cf", str(partial), "-C", str(tmp), *members],
                capture_output=True, text=True,
            )
            if run.returncode != 0:
                partial.unlink(missing_ok=True)
                raise BackupError(f"Archiv konnte nicht erstellt werden: {run.stderr.strip()}")
            os.chmod(partial, 0o600)
            # Prüfen, ob das Archiv lesbar ist
            verify = subprocess.run(["tar", "--zstd", "-tf", str(partial)], capture_output=True, text=True)
            if verify.returncode != 0 or "database.dump" not in verify.stdout:
                partial.unlink(missing_ok=True)
                raise BackupError("Das erstellte Archiv ist nicht lesbar.")
            partial.rename(final)
        final.with_name(final.name + ".sha256").write_text(f"{_sha256(final)}  {final.name}\n", encoding="utf-8")
        (target_dir / ERROR_FILE).unlink(missing_ok=True)
        return final
    except Exception as exc:
        (target_dir / ERROR_FILE).write_text(f"{timezone.localtime():%d.%m.%Y %H:%M}: {exc}", encoding="utf-8")
        raise
    finally:
        lock.unlink(missing_ok=True)


def prune(daily=14, weekly=8, monthly=12):
    """Aufbewahrung: die letzten N täglichen, wöchentlichen und monatlichen Backups.
    Backups mit Anlass (z. B. vor Updates) werden 90 Tage aufbewahrt."""
    items = list_backups()
    keep = set()
    days, weeks, months = set(), set(), set()
    now = timezone.now()
    for b in items:  # neueste zuerst
        created = b["created"]
        if b["reason"]:
            if now - created < timedelta(days=90):
                keep.add(b["name"])
            continue
        d = created.date()
        w = d.isocalendar()[:2]
        m = (d.year, d.month)
        if len(days) < daily and d not in days:
            days.add(d)
            keep.add(b["name"])
        if len(weeks) < weekly and w not in weeks:
            weeks.add(w)
            keep.add(b["name"])
        if len(months) < monthly and m not in months:
            months.add(m)
            keep.add(b["name"])
    removed = []
    for b in items:
        if b["name"] not in keep:
            p = backup_dir() / b["name"]
            p.unlink(missing_ok=True)
            p.with_name(p.name + ".sha256").unlink(missing_ok=True)
            removed.append(b["name"])
    return removed


def start_backup_async():
    if is_running():
        raise BackupError("Es läuft bereits ein Backup.")
    manage = Path(settings.BASE_DIR) / "manage.py"
    subprocess.Popen(
        [sys.executable, str(manage), "backup", "--reason", "manuell"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        cwd=settings.BASE_DIR,
    )
