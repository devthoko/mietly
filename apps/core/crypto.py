"""Verschlüsselung gespeicherter Zugangsdaten (SMTP, WebDAV, Backup-Passphrase)."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    key = settings.ENCRYPTION_KEY
    if not key:
        # Nur Entwicklung/Tests: Schlüssel aus SECRET_KEY ableiten.
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""
