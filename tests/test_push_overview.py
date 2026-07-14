"""Integrationstests für die unauffällige Push-Diagnose (/admin/push-overview)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

import app.main as main
from app.auth import ADMIN_COOKIE, make_admin_token
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
                             notify_events=True, ts_self_frs="FRS01", owner_cid=12345)
    # anonymes Abo (Firefox), fehlgeschlagen
    upsert_push_subscription(conn, "https://updates.push.services.mozilla.com/wpush/v2/XYZ", "p", "a",
                             pilot_filter=None, notify_prefiles=False, notify_ts=True,
                             notify_events=False, ts_self_frs=None, owner_cid=None)
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
    resp = asyncio.run(main.admin_push_overview_page(FakeReq()))
    assert isinstance(resp, HTMLResponse)
    assert b"Diagnose-Passwort" in resp.body


@pytest.mark.parametrize("db", [""], indirect=True)
def test_page_404_when_disabled(db):
    with pytest.raises(HTTPException) as ei:
        asyncio.run(main.admin_push_overview_page(FakeReq()))
    assert ei.value.status_code == 404
