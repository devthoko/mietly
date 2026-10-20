"""Optionale Einweg-Synchronisierung zu einem WebDAV-Server (z. B. Nextcloud).

* Dokumente werden als PDF in  <Zielordner>/dokumente/<Jahr>/<Auftrag>/  abgelegt.
* Backups werden vor dem Upload mit der hinterlegten Passphrase verschlüsselt
  (OpenSSL AES-256, PBKDF2) und in  <Zielordner>/backups/  abgelegt.
  Entschlüsseln:  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in DATEI.enc -out DATEI
Die Geschäftsdaten bleiben maßgeblich auf dem eigenen Server.
"""

import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import requests
from django.utils import timezone

from . import backup

REMOTE_BACKUPS_KEEP = 14
UPLOADED_LIST = ".webdav-uploaded"


class WebdavError(Exception):
    pass


class Client:
    def __init__(self, company):
        if not company.webdav_url:
            raise WebdavError("Es ist keine WebDAV-URL hinterlegt.")
        self.base = company.webdav_url.rstrip("/") + "/"
        self.folder = company.webdav_folder.strip("/")
        self.session = requests.Session()
        self.session.auth = (company.webdav_user, company.webdav_password)
        self.session.headers["User-Agent"] = "mietly"

    def url(self, path):
        parts = [p for p in f"{self.folder}/{path}".split("/") if p]
        return self.base + "/".join(quote(p) for p in parts)

    def request(self, method, path, **kwargs):
        try:
            r = self.session.request(method, self.url(path), timeout=60, **kwargs)
        except requests.RequestException as e:
            raise WebdavError(f"Verbindung fehlgeschlagen: {e}")
        if r.status_code in (401, 403):
            raise WebdavError("Anmeldung am WebDAV-Server fehlgeschlagen (Benutzer/Passwort prüfen).")
        return r

    def ensure_dir(self, path):
        current = ""
        for part in [p for p in path.split("/") if p]:
            current = f"{current}/{part}"
            r = self.request("PROPFIND", current, headers={"Depth": "0"})
            if r.status_code == 404:
                r = self.request("MKCOL", current)
                if r.status_code not in (201, 405):
                    raise WebdavError(f"Ordner {current} konnte nicht angelegt werden (HTTP {r.status_code}).")
            elif r.status_code >= 400:
                raise WebdavError(f"Ordner {current} nicht erreichbar (HTTP {r.status_code}).")

    def put(self, path, file_path):
        with open(file_path, "rb") as f:
            r = self.request("PUT", path, data=f)
        if r.status_code not in (200, 201, 204):
            raise WebdavError(f"Upload von {path} fehlgeschlagen (HTTP {r.status_code}).")

    def list(self, path):
        r = self.request("PROPFIND", path, headers={"Depth": "1"})
        if r.status_code == 404:
            return []
        if r.status_code != 207:
            raise WebdavError(f"Ordnerinhalt nicht lesbar (HTTP {r.status_code}).")
        names = []
        root = ET.fromstring(r.content)
        for href in root.iter("{DAV:}href"):
            name = unquote(urlparse(href.text).path.rstrip("/").rsplit("/", 1)[-1])
            names.append(name)
        return names[1:]

    def delete(self, path):
        self.request("DELETE", path)


def test_connection(company):
    client = Client(company)
    r = client.session.request("PROPFIND", client.base, headers={"Depth": "0"}, timeout=20)
    if r.status_code in (401, 403):
        raise WebdavError("Anmeldung am WebDAV-Server fehlgeschlagen (Benutzer/Passwort prüfen).")
    if r.status_code != 207:
        raise WebdavError(f"Der Server antwortet nicht wie ein WebDAV-Server (HTTP {r.status_code}).")
    client.ensure_dir("")


def _sync_documents(client):
    from django.db.models import F, Q

    from apps.documents.models import Document

    docs = Document.objects.filter(Q(synced_at__isnull=True) | Q(signed_at__gt=F("synced_at"))).select_related("order")
    count = 0
    for doc in docs:
        year = timezone.localtime(doc.created_at).year
        folder = f"dokumente/{year}/{doc.order.number}"
        client.ensure_dir(folder)
        client.put(f"{folder}/{doc.filename}", doc.file.path)
        if doc.signed_file:
            ext = Path(doc.signed_file.name).suffix or ".pdf"
            client.put(f"{folder}/{doc.filename.rsplit('.', 1)[0]}_unterschrieben{ext}", doc.signed_file.path)
        Document.objects.filter(pk=doc.pk).update(synced_at=timezone.now())
        count += 1
    return count


def _sync_backups(client, passphrase):
    items = backup.list_backups()
    if not items:
        return 0
    marker = backup.backup_dir() / UPLOADED_LIST
    uploaded = set(marker.read_text().split()) if marker.exists() else set()
    latest = items[0]["name"]
    count = 0
    if latest not in uploaded:
        client.ensure_dir("backups")
        with tempfile.TemporaryDirectory(dir=backup.backup_dir(), prefix=".tmp-") as tmp:
            enc = Path(tmp) / (latest + ".enc")
            env = os.environ.copy()
            env["MIETLY_BACKUP_PASS"] = passphrase
            run = subprocess.run(
                ["openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2", "-iter", "600000",
                 "-in", str(backup.backup_dir() / latest), "-out", str(enc), "-pass", "env:MIETLY_BACKUP_PASS"],
                env=env, capture_output=True, text=True,
            )
            if run.returncode != 0:
                raise WebdavError(f"Verschlüsselung fehlgeschlagen: {run.stderr.strip()}")
            client.put(f"backups/{enc.name}", enc)
        uploaded.add(latest)
        marker.write_text("\n".join(sorted(uploaded)))
        count = 1
    remote = sorted(n for n in client.list("backups") if n.startswith(backup.PREFIX) and n.endswith(".enc"))
    for old in remote[:-REMOTE_BACKUPS_KEEP]:
        client.delete(f"backups/{old}")
    return count


def sync_now(company):
    if not company.webdav_enabled:
        raise WebdavError("Die WebDAV-Synchronisierung ist nicht aktiviert.")
    client = Client(company)
    parts = []
    try:
        client.ensure_dir("")
        if company.webdav_sync_documents:
            parts.append(f"{_sync_documents(client)} Dokumente")
        if company.webdav_sync_backups:
            if not company.backup_passphrase:
                raise WebdavError("Für den Backup-Upload fehlt die Passphrase.")
            parts.append(f"{_sync_backups(client, company.backup_passphrase)} Backup")
        status = "OK: " + ", ".join(parts) if parts else "OK"
    except WebdavError as e:
        status = f"Fehler: {e}"
        type(company).objects.filter(pk=company.pk).update(webdav_last_sync=timezone.now(), webdav_last_status=status)
        raise
    type(company).objects.filter(pk=company.pk).update(webdav_last_sync=timezone.now(), webdav_last_status=status)
    return ", ".join(parts) + " übertragen"
