"""Forum-SSO (Board-Login) für FriesenSpy — Token-Primitiven.

Zwei getrennte Token, beide im Format ``base64url(payload).hmac_sha256_hex`` und mit einem
festen Typ-Feld ``typ`` (``"sso"`` bzw. ``"user"``), das die beiden Sorten strikt trennt —
auch dann, wenn versehentlich dasselbe Secret für beide konfiguriert würde:

- Das *eingehende* SSO-Token (``typ="sso"``) von der Forum-Bridge ``sso.php``, signiert mit dem
  GETEILTEN ``SSO_SECRET``. Kurzlebig (``iat``-Frische ≤ 60 s), trägt einen Einmal-``nonce``
  (Replay-Schutz/Nonce-Verbrauch liegt beim Aufrufer).
- Das *eigene* FriesenSpy-Session-Cookie (``typ="user"``) nach erfolgreichem Login, signiert mit
  ``SECRET_KEY`` (analog :mod:`app.auth`), mit Ablaufzeitpunkt ``exp``.

Reine Standardbibliothek, keine zusätzliche Abhängigkeit.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import time

USER_COOKIE = "fs_user"
SSO_TOKEN_MAX_AGE_SEC = 60  # Frische des eingehenden Bridge-Tokens
_MAX_TOKEN_LEN = 4096       # obere Schranke gegen übergroße Eingaben (DoS-Hebel)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload_b64: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"),
                    hashlib.sha256).hexdigest()


def _reject_nonfinite(_value):
    """``json.loads``-Hook: NaN/Infinity/-Infinity sind kein gültiges JSON hier → ablehnen."""
    raise ValueError("non-finite number not allowed")


def _encode(claims: dict, secret: str) -> str:
    payload_b64 = _b64url_encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return payload_b64 + "." + _sign(payload_b64, secret)


def _decode(token: str, secret: str) -> dict | None:
    # F1/F5-Härtung: nur ASCII (sonst wirft encode/compare_digest), begrenzte Länge, genau ein Punkt.
    if (not token or not secret or len(token) > _MAX_TOKEN_LEN
            or not token.isascii() or token.count(".") != 1):
        return None
    payload_b64, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(payload_b64, secret)):
        return None
    try:
        data = json.loads(_b64url_decode(payload_b64), parse_constant=_reject_nonfinite)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _finite_number(value) -> bool:
    """True nur für echte, endliche Zahlen (bool ist KEINE gültige Zahl hier)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def verify_sso_token(token: str, sso_secret: str, now: float | None = None) -> dict | None:
    """Eingehendes Bridge-Token prüfen: Signatur (``SSO_SECRET``) + ``typ`` + ``iat``-Frische + ``nonce``.

    Gibt die Claims (``typ``, ``sub``, ``name``, ``cid``, ``is_admin``, ``iat``, ``nonce``)
    zurück oder ``None``. Der Nonce-Replay-Schutz (Einmal-Verbrauch) passiert im Aufrufer.
    """
    claims = _decode(token, sso_secret)
    if claims is None or claims.get("typ") != "sso":
        return None
    iat = claims.get("iat")
    if not _finite_number(iat):
        return None
    now = time.time() if now is None else now
    if iat > now + 5 or now - iat > SSO_TOKEN_MAX_AGE_SEC:
        return None
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        return None
    return claims


def make_user_token(secret_key: str, name: str, cid: str, is_admin: bool,
                    exp: float) -> str:
    """Eigenes FriesenSpy-Session-Cookie (``typ="user"``, signiert mit ``SECRET_KEY``), Ablauf ``exp``.

    Die interne Forum-User-ID (``sub`` des eingehenden SSO-Tokens) wird bewusst NICHT ins Cookie
    übernommen — sie wurde nirgends ausgewertet (Berechtigung läuft über ``cid``/``is_admin``),
    also Datenminimierung (Art. 5 Abs. 1 c DSGVO)."""
    return _encode({"typ": "user", "name": name, "cid": cid,
                    "is_admin": bool(is_admin), "exp": int(exp)}, secret_key)


def verify_user_token(token: str, secret_key: str, now: float | None = None) -> dict | None:
    """FriesenSpy-Session-Cookie prüfen: Signatur (``SECRET_KEY``) + ``typ`` + ``exp``. Claims oder ``None``."""
    claims = _decode(token, secret_key)
    if claims is None or claims.get("typ") != "user":
        return None
    exp = claims.get("exp")
    if not _finite_number(exp):
        return None
    now = time.time() if now is None else now
    if now >= exp:
        return None
    return claims
