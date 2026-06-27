"""Integrationstests für die Admin-Bummel-Endpoints (Auth + Persistenz)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as main
from app.auth import ADMIN_COOKIE, make_admin_token
from app.database import get_connection, init_db

SECRET = "s3cr3t"
PW = "harle15"
TOKEN = make_admin_token(SECRET, PW)


class FakeReq:
    def __init__(self, cookies=None, body=None):
        self.cookies = cookies if cookies is not None else {ADMIN_COOKIE: TOKEN}
        self._body = body or {}

    async def json(self):
        return self._body


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    monkeypatch.setattr(
        main, "get_settings",
        lambda: SimpleNamespace(
            DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD=PW,
            VAPID_PRIVATE_KEY="vapid", VAPID_CONTACT_EMAIL="mailto:test",
        ),
    )
    return p


def _seed_flights(db, dtstart):
    """Zwei komplette Touren (Anna 60, Bert 100) im Renn-Fenster."""
    conn = get_connection(db)
    base = datetime.fromisoformat(dtstart.replace("Z", "+00:00"))

    def add(cid, name, dep, arr, block, t0):
        conn.execute("INSERT OR IGNORE INTO pilots (cid,name,added_at) VALUES (?,?,?)", (cid, name, dtstart))
        conn.execute(
            "INSERT INTO flights (cid,callsign,aircraft_short,departure,arrival,logon_time,logoff_time,duration_min,distance_nm,block_min) "
            "VALUES (?,?,'C172',?,?,?,?,?,50,?)",
            (cid, f"FRS{cid}", dep, arr, _iso(base + timedelta(minutes=t0)), _iso(base + timedelta(minutes=t0 + block)), block, block),
        )

    add(100, "Anna", "EDWF", "EDWG", 30, 1); add(100, "Anna", "EDWG", "EDWR", 30, 40)
    add(200, "Bert", "EDWF", "EDWG", 50, 1); add(200, "Bert", "EDWG", "EDWR", 50, 60)
    conn.commit(); conn.close()


def test_requires_admin(db):
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.admin_list_races(FakeReq(cookies={})))
    assert e.value.status_code == 401


def test_create_list_override_and_reveal(db):
    now = datetime.now(timezone.utc)
    dtstart = _iso(now - timedelta(hours=2))
    dtend = _iso(now + timedelta(hours=2))  # läuft noch → kein Auto-Reveal
    # Rennen anlegen
    res = asyncio.run(main.admin_create_race(FakeReq(body={
        "name": "Test-Bummel", "route": "EDWF,EDWG,EDWR", "dtstart": dtstart, "dtend": dtend,
    })))
    rid = res["id"]
    _seed_flights(db, dtstart)

    races = asyncio.run(main.admin_list_races(FakeReq()))
    assert any(r["id"] == rid and r["name"] == "Test-Bummel" for r in races)

    # Vorschau zeigt beide kompletten Touren (Admin sieht alles trotz laufend/unenthüllt)
    prev = asyncio.run(main.admin_preview_race(FakeReq(), rid))
    assert prev["revealed"] is True
    assert {e["cid"] for e in prev["complete"]} == {100, 200}

    # Bert ausschließen → Vorschau zeigt nur noch Anna
    asyncio.run(main.admin_set_override(FakeReq(body={"cid": 200, "action": "exclude"}), rid))
    prev2 = asyncio.run(main.admin_preview_race(FakeReq(), rid))
    assert {e["cid"] for e in prev2["complete"]} == {100}

    # Öffentliche Sicht vor Enthüllung: redigiert (keine Zeiten)
    pub = asyncio.run(main.get_bummel_race_endpoint(rid))
    assert pub["revealed"] is False and "complete" not in pub

    # Notfall-Enthüllung → öffentliche Sicht zeigt jetzt das (override-bereinigte) Ranking
    asyncio.run(main.admin_reveal_race(FakeReq(), rid))
    pub2 = asyncio.run(main.get_bummel_race_endpoint(rid))
    assert pub2["revealed"] is True
    assert {e["cid"] for e in pub2["complete"]} == {100}

    # Wieder verbergen
    asyncio.run(main.admin_hide_race(FakeReq(), rid))
    assert asyncio.run(main.get_bummel_race_endpoint(rid))["revealed"] is False


def test_admin_reveal_sends_push_once(db, monkeypatch):
    from app.database import upsert_push_subscription
    # Events-Abonnent anlegen (Empfänger)
    conn = get_connection(db)
    upsert_push_subscription(conn, "ep", "p", "a", notify_events=True)
    conn.commit(); conn.close()

    # send_web_push zählen (synchron beim Aufruf, unabhängig vom Task-Lauf)
    count = {"n": 0}
    async def _noop():
        return None
    def fake_send(*a, **k):
        count["n"] += 1
        return _noop()
    monkeypatch.setattr("app.poller.send_web_push", fake_send)

    now = datetime.now(timezone.utc)
    res = asyncio.run(main.admin_create_race(FakeReq(body={
        "route": "EDWF,EDWG,EDWR", "dtstart": _iso(now - timedelta(hours=2)),
        "dtend": _iso(now + timedelta(hours=2)),
    })))
    rid = res["id"]

    asyncio.run(main.admin_reveal_race(FakeReq(), rid))
    assert count["n"] == 1                      # erster Reveal → ein Push
    asyncio.run(main.admin_reveal_race(FakeReq(), rid))
    assert count["n"] == 1                      # erneuter Reveal → kein weiterer Push (latchend)


def test_races_list_includes_source(db):
    now = datetime.now(timezone.utc)
    asyncio.run(main.admin_create_race(FakeReq(body={
        "route": "EDWF,EDWG", "dtstart": _iso(now - timedelta(hours=1)), "dtend": _iso(now + timedelta(hours=1)),
    })))
    races = asyncio.run(main.get_bummel_races())
    assert races and races[0]["source"] == "manual"


def test_winner_override(db):
    now = datetime.now(timezone.utc)
    dtstart = _iso(now - timedelta(hours=2))
    res = asyncio.run(main.admin_create_race(FakeReq(body={
        "route": "EDWF,EDWG,EDWR", "dtstart": dtstart, "dtend": _iso(now - timedelta(hours=1)),
    })))
    rid = res["id"]
    _seed_flights(db, dtstart)
    # Bert (sonst nicht Sieger) zum Sieger erklären
    asyncio.run(main.admin_set_override(FakeReq(body={"cid": 200, "action": "winner"}), rid))
    prev = asyncio.run(main.admin_preview_race(FakeReq(), rid))
    assert prev["complete"][0]["cid"] == 200
    assert prev["complete"][0].get("forced_winner") is True
