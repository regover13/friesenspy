"""Integrationstests für die unauffällige Push-Diagnose (/admin/push-overview)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

import app.main as main
from app.auth import ADMIN_COOKIE, make_admin_token
from app.main import _SITE_ADMIN_COOKIE as SITE_COOKIE
from app.database import (
    get_connection,
    init_db,
    record_push_delivery,
    set_pilot_visibility,
    upsert_push_subscription,
)

SECRET = "s3cr3t"
PW = "test-admin-pw"
DIAG_PW = "diag-pw"
TOKEN = make_admin_token(SECRET, PW)


class FakeReq:
    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies if cookies is not None else {ADMIN_COOKIE: TOKEN}
        self.headers = headers or {}


@pytest.fixture
def db(tmp_path, monkeypatch, request):
    p = str(tmp_path / "t.db")
    init_db(p)
    diag_pw = getattr(request, "param", DIAG_PW)
    monkeypatch.setattr(
        main, "get_settings",
        lambda: SimpleNamespace(
            DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD=PW,
            PUSH_OVERVIEW_PASSWORD=diag_pw,
            VAPID_PRIVATE_KEY="vapid", VAPID_CONTACT_EMAIL="mailto:test",
        ),
    )
    return p


def _seed(db):
    conn = get_connection(db)
    conn.execute("INSERT OR IGNORE INTO pilots (cid,name,added_at) VALUES (?,?,?)",
                 (12345, "Anna", "2026-01-01T00:00:00Z"))
    # eingeloggtes Abo (Chrome/FCM), zugestellt
    upsert_push_subscription(conn, "https://fcm.googleapis.com/fcm/send/ABC", "p", "a",
                             pilot_filter=[12345], notify_prefiles=True, notify_ts=False,
                             notify_events=True, owner_cid=12345)
    # anonymes Abo (Firefox), fehlgeschlagen
    upsert_push_subscription(conn, "https://updates.push.services.mozilla.com/wpush/v2/XYZ", "p", "a",
                             pilot_filter=None, notify_prefiles=False, notify_ts=True,
                             notify_events=False, owner_cid=None)
    record_push_delivery(conn, ["https://fcm.googleapis.com/fcm/send/ABC"],
                         {"https://updates.push.services.mozilla.com/wpush/v2/XYZ": "403"})
    set_pilot_visibility(conn, 999, "nobody", None, None)
    conn.commit()
    conn.close()


def test_overview_ok(db):
    _seed(db)
    req = FakeReq(headers={"x-overview-pass": DIAG_PW})
    d = asyncio.run(main.admin_push_overview(req))

    t = d["totals"]
    assert t["abos"] == 2
    assert t["eingeloggt"] == 1 and t["anonym"] == 1
    assert t["personen"] == 1
    assert t["will_prefiles"] == 1 and t["will_ts"] == 1 and t["will_events"] == 1
    assert t["health_ok"] == 1 and t["health_fail"] == 1 and t["health_unknown"] == 0
    assert d["vapid_configured"] is True

    by_platform = {s["platform"]: s for s in d["subscriptions"]}
    chrome = by_platform["Chrome / Android"]
    assert chrome["owner_name"] == "Anna"
    assert chrome["pilot_filter"] == ["Anna"]  # CID→Name aufgelöst
    assert chrome["health"] == "ok"

    firefox = by_platform["Firefox"]
    assert firefox["owner_name"] is None       # anonym
    assert firefox["pilot_filter"] == []       # alle
    assert firefox["health"] == "fail" and firefox["last_status"] == "403"

    assert d["suppressed_pilots"][0]["who"] == "CID 999"
    assert d["suppressed_pilots"][0]["mode"] == "nobody"


def test_visibility_allowlist_resolved_to_names(db):
    """Erlaubte-Spalte: CIDs sind fuer Menschen unlesbar — es muessen Namen ankommen."""
    _seed(db)
    conn = get_connection(db)
    conn.execute("INSERT OR IGNORE INTO pilots (cid,name,added_at) VALUES (?,?,?)",
                 (67890, "Bernd", "2026-01-01T00:00:00Z"))
    set_pilot_visibility(conn, 4242, "allowlist", [12345, 67890], ["online", "ts"])
    conn.commit()
    conn.close()

    d = asyncio.run(main.admin_push_overview(FakeReq(headers={"x-overview-pass": DIAG_PW})))
    row = next(v for v in d["suppressed_pilots"] if v["cid"] == 4242)
    assert row["allowlist"] == ["Anna", "Bernd"]          # nicht [12345, 67890]
    assert row["services"] == ["Online", "TeamSpeak"]     # nicht '["online", "ts"]'


def test_visibility_nobody_has_empty_allowlist(db):
    """mode=nobody hat keine Allowlist — leere Liste, kein roher None-Durchgriff."""
    _seed(db)
    row = asyncio.run(main.admin_push_overview(
        FakeReq(headers={"x-overview-pass": DIAG_PW})))["suppressed_pilots"][0]
    assert row["allowlist"] == []
    assert row["services"] == ["Online", "Flugplan", "TeamSpeak"]


def test_overview_wrong_password(db):
    _seed(db)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(main.admin_push_overview(FakeReq(headers={"x-overview-pass": "falsch"})))
    assert ei.value.status_code == 401


def test_overview_missing_password_header(db):
    _seed(db)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(main.admin_push_overview(FakeReq()))
    assert ei.value.status_code == 401


def test_overview_requires_admin(db):
    _seed(db)
    # kein Admin-Cookie → 401, obwohl Diagnose-Passwort korrekt
    req = FakeReq(cookies={}, headers={"x-overview-pass": DIAG_PW})
    with pytest.raises(HTTPException) as ei:
        asyncio.run(main.admin_push_overview(req))
    assert ei.value.status_code == 401


@pytest.mark.parametrize("db", [""], indirect=True)
def test_overview_disabled_when_password_unset(db):
    """Leeres PUSH_OVERVIEW_PASSWORD → Feature existiert nicht (404)."""
    req = FakeReq(headers={"x-overview-pass": ""})
    with pytest.raises(HTTPException) as ei:
        asyncio.run(main.admin_push_overview(req))
    assert ei.value.status_code == 404


def test_page_served_when_configured(db):
    """Seite lädt mit dem site-weiten Admin-Cookie (path=/), das der Browser hierhin schickt."""
    resp = asyncio.run(main.admin_push_overview_page(FakeReq(cookies={SITE_COOKIE: TOKEN})))
    assert isinstance(resp, HTMLResponse)
    assert b"Diagnose-Passwort" in resp.body


def test_page_requires_admin(db):
    """Ohne Admin-Login gibt es nicht mal das Passwort-Formular zu sehen."""
    with pytest.raises(HTTPException) as ei:
        asyncio.run(main.admin_push_overview_page(FakeReq(cookies={})))
    assert ei.value.status_code == 401


def test_page_needs_site_cookie_not_api_cookie(db):
    """Regression: fs_admin liegt auf path=/api/admin und erreicht /admin/... nie.

    Die Seite darf sich deshalb NICHT auf require_admin verlassen — täte sie es, wäre sie für
    jeden echten Admin tot (401 trotz gültigem Login).
    """
    with pytest.raises(HTTPException):
        asyncio.run(main.admin_push_overview_page(FakeReq(cookies={ADMIN_COOKIE: TOKEN})))
    resp = asyncio.run(main.admin_push_overview_page(FakeReq(cookies={SITE_COOKIE: TOKEN})))
    assert isinstance(resp, HTMLResponse)


@pytest.mark.parametrize("db", [""], indirect=True)
def test_page_404_beats_admin_check_when_disabled(db):
    """Feature aus → 404 auch ohne Admin-Login (kein 401, das die URL verraten würde)."""
    with pytest.raises(HTTPException) as ei:
        asyncio.run(main.admin_push_overview_page(FakeReq(cookies={})))
    assert ei.value.status_code == 404


@pytest.mark.parametrize("db", [""], indirect=True)
def test_page_404_when_disabled(db):
    with pytest.raises(HTTPException) as ei:
        asyncio.run(main.admin_push_overview_page(FakeReq()))
    assert ei.value.status_code == 404
