"""Unit-Tests der Forum-SSO-Token-Primitiven (kein FastAPI, kein DB)."""
import base64
import hashlib
import hmac
import json

from app import forum_sso

SSO = "shared-forum-secret"
KEY = "friesenspy-secret-key"


def _incoming(claims: dict, secret: str = SSO, typ: str | None = "sso") -> str:
    """Mint ein eingehendes Bridge-Token genau so, wie sso.php es baut.

    ``typ`` wird per Default als ``"sso"`` gesetzt (kann für Negativtests überschrieben/entfernt
    werden, indem ``typ=None`` übergeben wird)."""
    if typ is not None:
        claims = {"typ": typ, **claims}
    raw = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    p = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    sig = hmac.new(secret.encode(), p.encode(), hashlib.sha256).hexdigest()
    return p + "." + sig


def test_verify_sso_token_accepts_fresh():
    tok = _incoming({"sub": 74, "name": "Tobias", "cid": "1401925",
                     "is_admin": True, "iat": 990, "nonce": "abc"})
    claims = forum_sso.verify_sso_token(tok, SSO, now=1000.0)
    assert claims is not None
    assert claims["cid"] == "1401925"
    assert claims["is_admin"] is True
    assert claims["nonce"] == "abc"


def test_verify_sso_token_rejects_bad_signature():
    tok = _incoming({"iat": 1000, "nonce": "x"}, secret="wrong-secret")
    assert forum_sso.verify_sso_token(tok, SSO, now=1000.0) is None


def test_verify_sso_token_rejects_stale():
    tok = _incoming({"iat": 900, "nonce": "x"})  # 100 s alt > 60 s
    assert forum_sso.verify_sso_token(tok, SSO, now=1000.0) is None


def test_verify_sso_token_requires_nonce():
    tok = _incoming({"iat": 1000})
    assert forum_sso.verify_sso_token(tok, SSO, now=1000.0) is None


def test_verify_sso_token_rejects_garbage():
    assert forum_sso.verify_sso_token("not-a-token", SSO, now=1000.0) is None
    assert forum_sso.verify_sso_token("", SSO, now=1000.0) is None


def test_user_token_roundtrip():
    tok = forum_sso.make_user_token(KEY, 74, "Tobias", "1401925", True, exp=2000.0)
    claims = forum_sso.verify_user_token(tok, KEY, now=1999.0)
    assert claims is not None
    assert claims["sub"] == 74
    assert claims["cid"] == "1401925"
    assert claims["is_admin"] is True


def test_user_token_expired():
    tok = forum_sso.make_user_token(KEY, 74, "T", "1", False, exp=1000.0)
    assert forum_sso.verify_user_token(tok, KEY, now=1000.0) is None


def test_user_token_wrong_key():
    tok = forum_sso.make_user_token(KEY, 74, "T", "1", False, exp=5000.0)
    assert forum_sso.verify_user_token(tok, "other-key", now=1000.0) is None


# --- Härtung (Fable-Review F1–F4) ------------------------------------------

def test_verify_sso_token_non_ascii_returns_none_not_crash():
    # F1: Nicht-ASCII darf NICHT crashen, sondern sauber None liefern.
    assert forum_sso.verify_sso_token("ä.deadbeef", SSO, now=1000.0) is None
    assert forum_sso.verify_sso_token("eyJ9.ä", SSO, now=1000.0) is None


def test_verify_sso_token_rejects_oversized():
    # F5: übergroße Eingabe wird ohne Verarbeitung abgelehnt.
    assert forum_sso.verify_sso_token("a" * 5000 + ".x", SSO, now=1000.0) is None


def test_verify_sso_token_rejects_nan_iat():
    # F2: NaN als iat darf die Frischeprüfung nicht aushebeln.
    import base64
    import hashlib
    import hmac
    raw = b'{"typ":"sso","iat":NaN,"nonce":"abc"}'  # NaN ist Nicht-Standard-JSON
    p = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    sig = hmac.new(SSO.encode(), p.encode(), hashlib.sha256).hexdigest()
    assert forum_sso.verify_sso_token(p + "." + sig, SSO, now=1000.0) is None


def test_verify_sso_token_requires_typ_sso():
    # F3: ein Token ohne typ (oder mit falschem typ) gilt NICHT als SSO-Token.
    tok = _incoming({"iat": 1000, "nonce": "abc"}, typ=None)
    assert forum_sso.verify_sso_token(tok, SSO, now=1000.0) is None
    tok2 = _incoming({"iat": 1000, "nonce": "abc"}, typ="user")
    assert forum_sso.verify_sso_token(tok2, SSO, now=1000.0) is None


def test_user_token_not_accepted_as_sso_even_with_same_secret():
    # F3-Kern: User-Token (typ=user) darf bei GLEICHEM Secret nicht als SSO-Token durchgehen.
    tok = forum_sso.make_user_token(SSO, 1, "x", "1", True, exp=1e12)
    assert forum_sso.verify_sso_token(tok, SSO, now=1000.0) is None


def test_sso_token_not_accepted_as_user_even_with_same_secret():
    tok = _incoming({"iat": 1000, "nonce": "abc", "exp": 1e12}, secret=KEY)
    assert forum_sso.verify_user_token(tok, KEY, now=1000.0) is None


def test_verify_sso_token_rejects_non_string_nonce():
    # F4: nonce muss ein nicht-leerer String sein (nicht bool/int).
    assert forum_sso.verify_sso_token(_incoming({"iat": 1000, "nonce": True}), SSO, now=1000.0) is None
    assert forum_sso.verify_sso_token(_incoming({"iat": 1000, "nonce": 1}), SSO, now=1000.0) is None
    assert forum_sso.verify_sso_token(_incoming({"iat": 1000, "nonce": ""}), SSO, now=1000.0) is None
