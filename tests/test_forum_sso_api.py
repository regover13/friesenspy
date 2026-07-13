"""Endpoint- + Gate-Tests für den Forum-SSO (Board-Login)."""
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import forum_sso, main
from app.auth import make_admin_token
from app.database import get_connection, init_db, set_app_setting

SECRET = "s3cr3t-key"
SSO = "shared-forum-secret"
PW = "test-admin-pw"
CALLBACK = "https://friesenspy.devprops.de/auth/forum/callback"
FORUM_URL = "https://board.friesenflieger.de/sso.php"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    settings = SimpleNamespace(
        DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD=PW,
        SSO_SECRET=SSO, FORUM_SSO_URL=FORUM_URL, FORUM_SSO_CALLBACK=CALLBACK,
        USER_SESSION_MAX_AGE_SEC=3600,
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main._reset_gate_cache()  # Task 4 stellt diesen Helfer bereit
    client = TestClient(main.app)
    return SimpleNamespace(client=client, db=p, settings=settings)


def _admin_cookie() -> dict:
    return {"fs_admin": make_admin_token(SECRET, PW)}


def _admin_site_cookie() -> dict:
    # Break-glass-Cookie auf path=/ — das sendet ein echter Browser auch für "/".
    return {"fs_admin_site": make_admin_token(SECRET, PW)}


def _user_cookie(is_admin: bool = True) -> dict:
    # FriesenSpy-Session-Cookie (fs_user), wie es der Callback nach Forum-Login setzt.
    exp = time.time() + 3600
    return {"fs_user": forum_sso.make_user_token(SECRET, 9, "Pilot", "1234567", is_admin, exp)}


def _mint_incoming(claims: dict, secret: str = SSO) -> str:
    import base64
    import hashlib
    import hmac
    import json
    claims = {"typ": "sso", **claims}
    raw = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    p = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    sig = hmac.new(secret.encode(), p.encode(), hashlib.sha256).hexdigest()
    return p + "." + sig


# --- Task 2: Admin-Schalter -------------------------------------------------

def test_toggle_defaults_off_but_configured(env):
    r = env.client.get("/api/admin/forum-login", cookies=_admin_cookie())
    assert r.status_code == 200
    assert r.json() == {"enabled": False, "configured": True}


def test_toggle_requires_admin(env):
    assert env.client.get("/api/admin/forum-login").status_code == 401
    assert env.client.post("/api/admin/forum-login", json={"enabled": True}).status_code == 401


def test_toggle_can_be_enabled(env):
    r = env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    assert r.status_code == 200 and r.json()["enabled"] is True
    r2 = env.client.get("/api/admin/forum-login", cookies=_admin_cookie())
    assert r2.json()["enabled"] is True


def test_configured_false_without_secret(env):
    env.settings.SSO_SECRET = ""
    r = env.client.get("/api/admin/forum-login", cookies=_admin_cookie())
    assert r.json() == {"enabled": False, "configured": False}


# --- Task 3: Login/Callback/Logout/me --------------------------------------

def test_login_redirects_to_forum_when_active(env):
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    r = env.client.get("/auth/forum/login", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(FORUM_URL)
    assert "state=" in loc and "redirect=" in loc
    assert "fs_sso_state" in r.cookies


def test_callback_sets_user_cookie(env):
    env.client.cookies.set("fs_sso_state", "st8")
    tok = _mint_incoming({"sub": 74, "name": "Tobias", "cid": "1401925",
                          "is_admin": True, "iat": time.time(), "nonce": "n1"})
    r = env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert "fs_user" in r.cookies
    me = env.client.get("/api/me")
    assert me.json() == {"logged_in": True, "name": "Tobias", "cid": "1401925", "is_admin": True}


def test_callback_rejects_state_mismatch(env):
    env.client.cookies.set("fs_sso_state", "st8")
    tok = _mint_incoming({"iat": time.time(), "nonce": "n2", "sub": 1, "name": "x",
                          "cid": "", "is_admin": False})
    r = env.client.get(f"/auth/forum/callback?token={tok}&state=WRONG", follow_redirects=False)
    assert r.status_code == 400


def test_callback_rejects_bad_token(env):
    env.client.cookies.set("fs_sso_state", "st8")
    r = env.client.get("/auth/forum/callback?token=garbage&state=st8", follow_redirects=False)
    assert r.status_code == 401


def test_callback_rejects_replayed_nonce(env):
    env.client.cookies.set("fs_sso_state", "st8")
    tok = _mint_incoming({"sub": 74, "name": "T", "cid": "1", "is_admin": False,
                          "iat": time.time(), "nonce": "used-once"})
    ok = env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    assert ok.status_code == 302
    env.client.cookies.set("fs_sso_state", "st8")
    again = env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    assert again.status_code == 401


def test_logout_clears_user_cookie(env):
    env.client.cookies.set("fs_sso_state", "st8")
    tok = _mint_incoming({"sub": 1, "name": "x", "cid": "", "is_admin": False,
                          "iat": time.time(), "nonce": "n3"})
    env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    r = env.client.get("/auth/forum/logout", follow_redirects=False)
    assert r.status_code == 302
    assert env.client.get("/api/me").json()["logged_in"] is False


# --- Task 4: Gate-Middleware ------------------------------------------------

def _login(env, is_admin=False):
    env.client.cookies.set("fs_sso_state", "st8")
    tok = _mint_incoming({"sub": 9, "name": "Pilot", "cid": "1234567",
                          "is_admin": is_admin, "iat": time.time(), "nonce": f"g{time.time()}"})
    env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)


def test_gate_off_allows_public_access(env):
    r = env.client.get("/", follow_redirects=False)
    assert r.status_code == 200


def test_gate_on_redirects_html_to_login(env):
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    r = env.client.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/auth/forum/login"


def test_gate_on_returns_401_for_api(env):
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    r = env.client.get("/api/teamspeak", headers={"accept": "application/json"})
    assert r.status_code == 401


def test_gate_on_allows_logged_in_user(env):
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    _login(env)
    assert env.client.get("/", headers={"accept": "text/html"}, follow_redirects=False).status_code == 200


def test_gate_on_allows_break_glass_admin(env):
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    # nur das Break-glass-Cookie (path=/, so wie es ein Browser für "/" sendet), kein fs_user
    r = env.client.get("/", headers={"accept": "text/html"},
                       cookies=_admin_site_cookie(), follow_redirects=False)
    assert r.status_code == 200


def test_admin_login_sets_break_glass_site_cookie(env):
    r = env.client.post("/api/admin/login", json={"password": PW}, follow_redirects=False)
    assert r.status_code == 200
    assert "fs_admin_site" in r.cookies


def test_callback_non_ascii_state_returns_400_not_500(env):
    # Fable-Review F2: Non-ASCII-state → 400, nicht 500 (compare_digest auf Bytes).
    env.client.cookies.set("fs_sso_state", "st8")
    r = env.client.get("/auth/forum/callback?token=x&state=%C3%A4", follow_redirects=False)
    assert r.status_code == 400


def test_gate_always_allows_auth_and_legal_paths(env):
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    for path in ("/auth/forum/login", "/impressum", "/datenschutz", "/health"):
        assert env.client.get(path, follow_redirects=False).status_code in (200, 302)


def test_gate_on_allows_public_badges(env):
    # Forum-eingebettete Badge-PNGs bleiben bei aktivem Gate erreichbar (nicht vom Gate geblockt).
    # `/widget` ist über denselben Allowlist-Präfix-Mechanismus abgedeckt wie die anderen Pfade.
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    # Badge-Pfad erreicht die Route (404 mangels Event), wird NICHT vom Gate mit 401 geblockt.
    r = env.client.get("/api/transport/999999/badge/1.png", follow_redirects=False)
    assert r.status_code != 401


# --- Task 5: Frontend-Markup wird ausgeliefert ------------------------------

def test_index_serves_userbox_markup(env):
    r = env.client.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    assert "userBox" in r.text            # Name des eingeloggten Nutzers
    assert "/auth/forum/logout" not in r.text  # kein Abmelden-Button (Nutzer-Entscheidung)


def test_admin_page_serves_toggle_markup(env):
    r = env.client.get("/admin")
    assert r.status_code == 200
    assert "forumLoginToggle" in r.text


# --- Admin-Ablösung: Events-Gruppe = Admin, Passwort nur Fallback -----------

def test_admin_access_via_forum_events_admin(env):
    # Forum-Session mit is_admin (Events-Gruppe) → Admin-Panel ohne Passwort.
    r = env.client.get("/api/admin/me", cookies=_user_cookie(is_admin=True))
    assert r.status_code == 200 and r.json() == {"admin": True}


def test_forum_non_admin_denied_admin(env):
    # Forum-Session ohne is_admin → kein Admin-Zugang.
    r = env.client.get("/api/admin/me", cookies=_user_cookie(is_admin=False))
    assert r.status_code == 401


def test_password_admin_still_works_as_fallback(env):
    # Passwort-Cookie (Break-glass) funktioniert weiterhin.
    r = env.client.get("/api/admin/me", cookies=_admin_cookie())
    assert r.status_code == 200
