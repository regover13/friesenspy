"""Admin-Authentifizierung für FriesenSpy — signiertes Cookie via SECRET_KEY.

Kein Server-Session-Store: Das Cookie enthält einen HMAC-SHA256 über das Admin-Passwort,
signiert mit ``SECRET_KEY``. Eine Passwort- oder Key-Änderung invalidiert alte Cookies
automatisch. Reine Standardbibliothek, keine zusätzliche Abhängigkeit.
"""
from __future__ import annotations

import hashlib
import hmac

ADMIN_COOKIE = "fs_admin"


def make_admin_token(secret_key: str, password: str) -> str:
    """Deterministisches Admin-Token (HMAC über das Passwort, signiert mit SECRET_KEY)."""
    msg = ("fs-admin:" + (password or "")).encode("utf-8")
    return hmac.new((secret_key or "").encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_admin_token(token: str, secret_key: str, password: str) -> bool:
    """True, wenn ``token`` zum aktuellen Passwort/Key passt. Leeres Passwort → nie gültig
    (Admin nicht konfiguriert)."""
    if not password or not token:
        return False
    return hmac.compare_digest(token, make_admin_token(secret_key, password))


def check_password(candidate: str, password: str) -> bool:
    """Konstantzeit-Vergleich des eingegebenen Passworts. Leeres Soll-Passwort → nie erlaubt."""
    if not password:
        return False
    return hmac.compare_digest(candidate or "", password)
