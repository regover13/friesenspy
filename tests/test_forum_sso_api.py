"""Endpoint- + Gate-Tests für den Forum-SSO (Board-Login)."""
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import forum_sso, main
from app.auth import make_admin_token, make_confirm_token
from app.database import (
    close_flight, ensure_pilot, get_connection, init_db, open_flight, set_app_setting,
)

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
        USER_SESSION_MAX_AGE_SEC=3600, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main._reset_gate_cache()  # Task 4 stellt diesen Helfer bereit
    client = TestClient(main.app)
    return SimpleNamespace(client=client, db=p, settings=settings)


def _admin_cookie() -> dict:
    # Admin-Cookie + fern-gültiges Step-up-Token (POST /forum-login verlangt jetzt require_confirm).
    return {
        "fs_admin": make_admin_token(SECRET, PW),
        "fs_confirm": make_confirm_token(SECRET, PW, 9_999_999_999),
    }


def _admin_site_cookie() -> dict:
    # Break-glass-Cookie auf path=/ — das sendet ein echter Browser auch für "/".
    return {"fs_admin_site": make_admin_token(SECRET, PW)}


def _user_cookie(is_admin: bool = True) -> dict:
    # FriesenSpy-Session-Cookie (fs_user), wie es der Callback nach Forum-Login setzt.
    exp = time.time() + 3600
    return {"fs_user": forum_sso.make_user_token(SECRET, "Pilot", "1234567", is_admin, exp)}


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
    # /api/me spiegelt den Login nur bei AKTIVEM Board-Login:
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    me = env.client.get("/api/me")
    assert me.json() == {"logged_in": True, "board_login_active": True,
                         "name": "Tobias", "cid": "1401925", "is_admin": True}


def test_login_to_admin_roundtrip(env):
    # Voller Round-Trip: Login mit ?next=/admin merkt das Ziel, der Callback leitet dorthin.
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    login = env.client.get("/auth/forum/login?next=/admin", follow_redirects=False)
    assert login.status_code == 302 and "fs_sso_next" in login.cookies
    # state-Cookie stammt aus derselben Login-Antwort (im Client-Jar) — Callback nutzt es mit.
    state = env.client.cookies.get("fs_sso_state")
    tok = _mint_incoming({"sub": 74, "name": "Tobias", "cid": "1401925",
                          "is_admin": True, "iat": time.time(), "nonce": "rt-admin"})
    r = env.client.get(f"/auth/forum/callback?token={tok}&state={state}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/admin"


def test_callback_redirects_to_next(env):
    env.client.cookies.set("fs_sso_state", "st8")
    env.client.cookies.set("fs_sso_next", "/admin", path="/auth/forum")
    tok = _mint_incoming({"sub": 74, "name": "Tobias", "cid": "1401925",
                          "is_admin": True, "iat": time.time(), "nonce": "n-next"})
    r = env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/admin"


def test_callback_ignores_unsafe_next(env):
    # Open-Redirect-Versuch (protokoll-relative URL) → Fallback auf "/".
    env.client.cookies.set("fs_sso_state", "st8")
    env.client.cookies.set("fs_sso_next", "//evil.example.com", path="/auth/forum")
    tok = _mint_incoming({"sub": 74, "name": "T", "cid": "1", "is_admin": False,
                          "iat": time.time(), "nonce": "n-evil"})
    r = env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/"


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
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    env.client.cookies.set("fs_sso_state", "st8")
    tok = _mint_incoming({"sub": 1, "name": "x", "cid": "", "is_admin": False,
                          "iat": time.time(), "nonce": "n3"})
    env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    assert env.client.get("/api/me").json()["logged_in"] is True
    r = env.client.get("/auth/forum/logout", follow_redirects=False)
    assert r.status_code == 302
    assert env.client.get("/api/me").json()["logged_in"] is False


def test_me_false_when_board_login_off(env):
    # Altes fs_user-Cookie, aber Board-Login AUS → kein Name (logged_in false).
    env.client.cookies.update(_user_cookie(is_admin=False))
    main._reset_gate_cache()
    assert env.client.get("/api/me").json()["logged_in"] is False


def test_me_slides_session_cookie(env):
    # Sliding-Session: /api/me erneuert bei gültigem Login das fs_user-Cookie.
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    r = env.client.get("/api/me", cookies=_user_cookie(is_admin=True))
    assert r.json()["logged_in"] is True
    assert "fs_user" in r.cookies


def test_me_exposes_board_login_active(env):
    # Steuert den „mit Forum anmelden"-Link auf der Admin-Login-Seite (allowlisted, auch ohne Login).
    assert env.client.get("/api/me").json()["board_login_active"] is False
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    assert env.client.get("/api/me").json()["board_login_active"] is True


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


# --- Task 5: Subjekt-Sichtbarkeit + owner_cid --------------------------------

def _enable(env):
    """Board-Login scharfschalten (forum_login_enabled=1) + Gate-Cache leeren."""
    conn = get_connection(env.db)
    set_app_setting(conn, "forum_login_enabled", "1")
    conn.commit(); conn.close()
    main._reset_gate_cache()


def test_visibility_requires_login(env):
    _enable(env)
    # Anonym trotz aktivem Gate → 401 aus dem Endpoint (das Gate schützt /api/me/* NICHT).
    r = env.client.get("/api/me/visibility")
    assert r.status_code == 401


def test_visibility_default_everyone(env):
    _enable(env)
    r = env.client.get("/api/me/visibility", cookies=_user_cookie())
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "everyone" and body["allowlist"] == []
    assert set(body["services"]) == {"online", "prefile", "ts"}
    assert isinstance(body["pilots"], list)


def _ts(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def test_visibility_picker_limited_to_active_365_days(env):
    # Picker-Kandidaten müssen dieselbe 365-Tage-Grenze wie /api/stats einhalten: ein Pilot,
    # dessen letzter Flug > 365 Tage her ist, darf NICHT mehr im Sichtbarkeits-Picker stehen
    # (vorher tauchte so einer nur hier auf — der FRS1525-Bug).
    _enable(env)
    conn = get_connection(env.db)
    try:
        ensure_pilot(conn, 111, "Aktiver Pilot")
        ensure_pilot(conn, 222, "Inaktiver Pilot")
        conn.commit()
        # Aktiv: Flug vor 5 Tagen.
        fid_a = open_flight(conn, 111, "FRS111", "B738", "EDDH", "EDDF", _ts(60 * 24 * 5))
        conn.commit(); close_flight(conn, fid_a, _ts(60 * 24 * 5 - 60)); conn.commit()
        # Inaktiv: Flug vor ~400 Tagen (außerhalb der 365-Tage-Grenze).
        fid_i = open_flight(conn, 222, "FRS222", "C172", "EDHE", "EDXW", _ts(60 * 24 * 400))
        conn.commit(); close_flight(conn, fid_i, _ts(60 * 24 * 400 - 30)); conn.commit()
    finally:
        conn.close()
    pilots = env.client.get("/api/me/visibility", cookies=_user_cookie()).json()["pilots"]
    cids = {p["cid"] for p in pilots}
    assert 111 in cids          # aktiver Pilot bleibt wählbar
    assert 222 not in cids      # > 365 Tage inaktiv → nicht mehr im Picker


def test_visibility_services_roundtrip(env):
    _enable(env)
    env.client.post("/api/me/visibility", cookies=_user_cookie(),
                    json={"mode": "nobody", "services": ["ts", "online"]})
    got = env.client.get("/api/me/visibility", cookies=_user_cookie()).json()
    assert got["mode"] == "nobody" and set(got["services"]) == {"ts", "online"}


def test_visibility_set_and_read_allowlist(env):
    _enable(env)
    r = env.client.post("/api/me/visibility", cookies=_user_cookie(),
                        json={"mode": "allowlist", "allowlist": [111, 222]})
    assert r.status_code == 200
    got = env.client.get("/api/me/visibility", cookies=_user_cookie()).json()
    assert got["mode"] == "allowlist" and got["allowlist"] == [111, 222]


def test_visibility_invalid_mode_400(env):
    _enable(env)
    r = env.client.post("/api/me/visibility", cookies=_user_cookie(), json={"mode": "bogus"})
    assert r.status_code == 400


def test_visibility_allowlist_empty_allowed(env):
    _enable(env)
    r = env.client.post("/api/me/visibility", cookies=_user_cookie(),
                        json={"mode": "allowlist", "allowlist": []})
    assert r.status_code == 200
    assert env.client.get("/api/me/visibility", cookies=_user_cookie()).json()["allowlist"] == []


def test_visibility_allowlist_capped_at_500(env):
    _enable(env)
    env.client.post("/api/me/visibility", cookies=_user_cookie(),
                    json={"mode": "allowlist", "allowlist": list(range(600))})
    assert len(env.client.get("/api/me/visibility", cookies=_user_cookie()).json()["allowlist"]) == 500


def test_board_login_off_treated_as_logged_out(env):
    # Schalter AUS: gültiges fs_user-Cookie darf NICHT als eingeloggt zählen (F8).
    r = env.client.get("/api/me/visibility", cookies=_user_cookie())
    assert r.status_code == 401


def test_subscribe_sets_owner_from_cookie_ignores_body(env):
    _enable(env)
    r = env.client.post("/api/push/subscribe", cookies=_user_cookie(),
                        json={"endpoint": "ep", "p256dh": "p", "auth": "a", "owner_cid": 999})
    assert r.status_code == 200
    conn = get_connection(env.db)
    row = conn.execute("SELECT owner_cid FROM push_subscriptions WHERE endpoint=?", ("ep",)).fetchone()
    conn.close()
    assert row["owner_cid"] == 1234567          # aus dem Cookie, nicht 999 aus dem Body


def test_push_claim_logged_in_and_anonymous(env):
    # Anonym + Schalter AUS → No-op (skipped), kein Owner.
    conn = get_connection(env.db)
    conn.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at) "
                 "VALUES ('c1','p','a','2026-07-13T00:00:00Z')")
    conn.commit(); conn.close()
    r = env.client.post("/api/push/claim", json={"endpoint": "c1"})
    assert r.json()["status"] == "skipped"
    # Eingeloggt (Schalter AN) → Owner gesetzt.
    _enable(env)
    r = env.client.post("/api/push/claim", cookies=_user_cookie(), json={"endpoint": "c1"})
    assert r.json()["status"] == "ok"
    conn = get_connection(env.db)
    row = conn.execute("SELECT owner_cid FROM push_subscriptions WHERE endpoint='c1'").fetchone()
    conn.close()
    assert row["owner_cid"] == 1234567


# --- Task 6: Callback speichert Forum-Callsign(s) ---------------------------

def _forum_callsigns(env):
    conn = get_connection(env.db)
    rows = {r["callsign"]: r["cid"]
            for r in conn.execute("SELECT callsign, cid FROM forum_callsign").fetchall()}
    conn.close()
    return rows


def test_callback_writes_forum_callsign(env):
    env.client.cookies.set("fs_sso_state", "st8")
    tok = _mint_incoming({"sub": 1, "name": "T", "cid": "1602713", "is_admin": False,
                          "iat": time.time(), "nonce": "cs1", "cs": ["FRS49", "frs49n", ""]})
    r = env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    assert r.status_code == 302
    assert _forum_callsigns(env) == {"FRS49": 1602713, "FRS49N": 1602713}  # UPPER, leer verworfen


def test_callback_without_cs_no_rows(env):
    env.client.cookies.set("fs_sso_state", "st8")
    tok = _mint_incoming({"sub": 1, "name": "T", "cid": "1602713", "is_admin": False,
                          "iat": time.time(), "nonce": "cs2"})
    r = env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    assert r.status_code == 302 and _forum_callsigns(env) == {}


def test_callback_defective_cs_ignored(env):
    env.client.cookies.set("fs_sso_state", "st8")
    tok = _mint_incoming({"sub": 1, "name": "T", "cid": "999", "is_admin": False,
                          "iat": time.time(), "nonce": "cs3", "cs": [123, {"x": 1}, "FRS7"]})
    r = env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    assert r.status_code == 302 and list(_forum_callsigns(env)) == ["FRS7"]


def test_callback_self_cleanup_removes_stale(env):
    for nonce, cs in (("a", ["FRS49", "FRS49N"]), ("b", ["FRS49"])):
        env.client.cookies.set("fs_sso_state", "st8")
        tok = _mint_incoming({"sub": 1, "name": "T", "cid": "1602713", "is_admin": False,
                              "iat": time.time(), "nonce": nonce, "cs": cs})
        env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    assert list(_forum_callsigns(env)) == ["FRS49"]   # FRS49N bereinigt


def test_callback_empty_cs_removes_all_own_rows(env):
    # Erst ein Rufzeichen setzen, dann Login mit leerer cs-Liste → alle eigenen Zeilen weg (F4).
    for nonce, cs in (("f1", ["FRS5"]), ("f2", [])):
        env.client.cookies.set("fs_sso_state", "st8")
        tok = _mint_incoming({"sub": 1, "name": "T", "cid": "1602713", "is_admin": False,
                              "iat": time.time(), "nonce": nonce, "cs": cs})
        env.client.get(f"/auth/forum/callback?token={tok}&state=st8", follow_redirects=False)
    assert _forum_callsigns(env) == {}
