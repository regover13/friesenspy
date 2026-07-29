"""Integrationstests für die Admin-Bummel-Endpoints (Auth + Persistenz)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as main
from app.auth import ADMIN_COOKIE, CONFIRM_COOKIE, make_admin_token, make_confirm_token
from app.database import (
    create_transport_event,
    get_connection,
    get_progress_snapshot,
    init_db,
    upsert_bummel_override,
    upsert_push_subscription,
    write_progress_snapshot,
)

SECRET = "s3cr3t"
PW = "test-admin-pw"
TOKEN = make_admin_token(SECRET, PW)
# Fern-in-der-Zukunft gültiges Step-up-Token → Standard-Request ist „bereits bestätigt".
CONFIRM_TOKEN = make_confirm_token(SECRET, PW, 9_999_999_999)


class FakeReq:
    def __init__(self, cookies=None, body=None, headers=None):
        self.cookies = cookies if cookies is not None else {
            ADMIN_COOKIE: TOKEN, CONFIRM_COOKIE: CONFIRM_TOKEN,
        }
        self._body = body or {}
        self.headers = headers or {}

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
            STATSIM_API_KEY=None,
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


def test_upsert_payload_persists_make_model_and_fuel_full(db):
    asyncio.run(main.admin_upsert_payload(FakeReq(body={
        "type_code": "AEST", "mtow_kg": 2767, "empty_kg": 1700,
        "fuel_kg": 100, "fuel_full_kg": 200, "crew_kg": 85, "make_model": "Aerostar 600",
    })))
    res = asyncio.run(main.admin_transport_payloads(FakeReq()))
    row = next(p for p in res["payloads"] if p["type_code"] == "AEST")
    assert row["make_model"] == "Aerostar 600"
    assert abs(row["fuel_full_kg"] - 200) < 0.5
    assert abs(row["fuel_kg"] - 100) < 0.5
    assert row["source"] == "manual"


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


def test_badge_endpoint(db):
    now = datetime.now(timezone.utc)
    dtstart = _iso(now - timedelta(hours=5))
    rid = asyncio.run(main.admin_create_race(FakeReq(body={
        "route": "EDWF,EDWG,EDWR", "dtstart": dtstart, "dtend": _iso(now - timedelta(hours=1)),
    })))["id"]
    _seed_flights(db, dtstart)
    view = asyncio.run(main.get_bummel_race_endpoint(rid))   # vorbei → Auto-Reveal
    assert view["revealed"] is True
    winner = view["complete"][0]["cid"]
    other = view["complete"][1]["cid"]

    png_w = asyncio.run(main.get_bummel_badge(FakeReq(), rid, winner))
    assert png_w.media_type == "image/png" and png_w.body[:8] == b"\x89PNG\r\n\x1a\n"
    png_m = asyncio.run(main.get_bummel_badge(FakeReq(), rid, other))
    assert png_m.body[:8] == b"\x89PNG\r\n\x1a\n"
    # Beide rund, 256×256; Sieger hat helle Kuppel-Mitte, Medaille dunklen Navy-Kern
    from io import BytesIO
    from PIL import Image
    iw = Image.open(BytesIO(png_w.body)).convert("RGBA")
    im = Image.open(BytesIO(png_m.body)).convert("RGBA")
    assert iw.size == (256, 256) and im.size == (256, 256)
    assert iw.getpixel((0, 0))[3] == 0 and im.getpixel((0, 0))[3] == 0  # transparente Ecke (rund)
    # Mitte: Sieger hell (hohe Summe), Medaille dunkel (niedrige Summe)
    assert sum(iw.getpixel((128, 110))[:3]) > sum(im.getpixel((128, 110))[:3])
    assert png_w.body != png_m.body

    with pytest.raises(HTTPException) as e:
        asyncio.run(main.get_bummel_badge(FakeReq(), rid, 999999))
    assert e.value.status_code == 404


def test_badge_etag_revalidation(db):
    """Badge nutzt no-cache + ETag → bei Sieger-/Override-Änderung sofort frisch, sonst 304."""
    now = datetime.now(timezone.utc)
    dtstart = _iso(now - timedelta(hours=5))
    rid = asyncio.run(main.admin_create_race(FakeReq(body={
        "route": "EDWF,EDWG,EDWR", "dtstart": dtstart, "dtend": _iso(now - timedelta(hours=1)),
    })))["id"]
    _seed_flights(db, dtstart)
    cid = asyncio.run(main.get_bummel_race_endpoint(rid))["complete"][0]["cid"]

    resp = asyncio.run(main.get_bummel_badge(FakeReq(), rid, cid))
    etag = resp.headers.get("etag")
    assert etag and resp.headers.get("cache-control") == "no-cache"
    # Unveränderter ETag → 304 (kein erneuter Bild-Download)
    resp304 = asyncio.run(main.get_bummel_badge(FakeReq(headers={"if-none-match": etag}), rid, cid))
    assert resp304.status_code == 304


def test_badge_404_before_reveal(db):
    now = datetime.now(timezone.utc)
    dtstart = _iso(now - timedelta(hours=1))
    rid = asyncio.run(main.admin_create_race(FakeReq(body={
        "route": "EDWF,EDWG,EDWR", "dtstart": dtstart, "dtend": _iso(now + timedelta(hours=3)),
    })))["id"]
    _seed_flights(db, dtstart)
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.get_bummel_badge(FakeReq(), rid, 100))
    assert e.value.status_code == 404


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


# --- v6.4.0: Admin-Badge-Vorschau, Push test/broadcast, Piloten ---

def test_admin_badge_before_reveal(db):
    now = datetime.now(timezone.utc)
    dtstart = _iso(now - timedelta(hours=1))
    rid = asyncio.run(main.admin_create_race(FakeReq(body={
        "route": "EDWF,EDWG,EDWR", "dtstart": dtstart, "dtend": _iso(now + timedelta(hours=3)),
    })))["id"]
    _seed_flights(db, dtstart)
    # öffentlicher Endpoint: 404 vor Enthüllung
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.get_bummel_badge(FakeReq(), rid, 100))
    assert e.value.status_code == 404
    # Admin-Vorschau liefert trotzdem ein PNG
    resp = asyncio.run(main.admin_bummel_badge(FakeReq(), rid, 100))
    assert resp.media_type == "image/png" and resp.body[:8] == b"\x89PNG\r\n\x1a\n"


def test_admin_badge_requires_auth(db):
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.admin_bummel_badge(FakeReq(cookies={}), 1, 100))
    assert e.value.status_code == 401


def _capture_push(monkeypatch):
    """send_web_push durch eine erfassende Async-Fake ersetzen."""
    calls = []

    async def fake(vpk, vce, dbp, subs, payload, label="x"):
        calls.append({"subs": subs, "payload": payload, "label": label})

    monkeypatch.setattr(main, "send_web_push", fake)
    return calls


def test_push_test_only_one_endpoint(db, monkeypatch):
    calls = _capture_push(monkeypatch)
    conn = get_connection(db)
    upsert_push_subscription(conn, "my-ep", "p", "a")
    upsert_push_subscription(conn, "other-ep", "p", "a")
    conn.commit(); conn.close()
    res = asyncio.run(main.admin_push_test(FakeReq(body={"endpoint": "my-ep"})))
    assert res["sent"] == 1
    assert len(calls) == 1
    assert [s["endpoint"] for s in calls[0]["subs"]] == ["my-ep"]  # nur an mich


def test_push_test_uses_title_and_body(db, monkeypatch):
    calls = _capture_push(monkeypatch)
    conn = get_connection(db)
    upsert_push_subscription(conn, "my-ep", "p", "a")
    conn.commit(); conn.close()
    res = asyncio.run(main.admin_push_test(
        FakeReq(body={"endpoint": "my-ep", "title": "Hallo Friesen", "body": "Probe 123"})))
    assert res["sent"] == 1
    assert calls[0]["payload"]["title"] == "Hallo Friesen"
    assert calls[0]["payload"]["body"] == "Probe 123"


def test_push_test_falls_back_to_default_text(db, monkeypatch):
    calls = _capture_push(monkeypatch)
    conn = get_connection(db)
    upsert_push_subscription(conn, "my-ep", "p", "a")
    conn.commit(); conn.close()
    asyncio.run(main.admin_push_test(FakeReq(body={"endpoint": "my-ep"})))
    # Ohne Felder: nicht-leerer Standard-Testtext
    assert calls[0]["payload"]["title"].strip()
    assert calls[0]["payload"]["body"].strip()


def test_push_test_unknown_endpoint_404(db, monkeypatch):
    _capture_push(monkeypatch)
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.admin_push_test(FakeReq(body={"endpoint": "nope"})))
    assert e.value.status_code == 404


def test_broadcast_audience_selectable(db, monkeypatch):
    calls = _capture_push(monkeypatch)
    conn = get_connection(db)
    upsert_push_subscription(conn, "ev", "p", "a", notify_events=True)
    upsert_push_subscription(conn, "noev", "p", "a", notify_events=False)
    conn.commit(); conn.close()
    res_all = asyncio.run(main.admin_push_broadcast(FakeReq(body={"title": "T", "body": "B", "audience": "all"})))
    assert res_all["sent"] == 2
    res_ev = asyncio.run(main.admin_push_broadcast(FakeReq(body={"title": "T", "body": "B", "audience": "events"})))
    assert res_ev["sent"] == 1
    assert {s["endpoint"] for s in calls[1]["subs"]} == {"ev"}


def test_pilots_crud(db):
    asyncio.run(main.admin_upsert_pilot(FakeReq(body={"cid": 123, "name": "Tobias"})))
    pilots = asyncio.run(main.admin_list_pilots(FakeReq()))
    assert any(p["cid"] == 123 and p["name"] == "Tobias" for p in pilots)
    asyncio.run(main.admin_upsert_pilot(FakeReq(body={"cid": 123, "name": "Tobi"})))
    pilots = asyncio.run(main.admin_list_pilots(FakeReq()))
    assert [p for p in pilots if p["cid"] == 123][0]["name"] == "Tobi"
    asyncio.run(main.admin_delete_pilot(FakeReq(), 123))
    pilots = asyncio.run(main.admin_list_pilots(FakeReq()))
    assert all(p["cid"] != 123 for p in pilots)


def test_pilots_requires_auth(db):
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.admin_list_pilots(FakeReq(cookies={})))
    assert e.value.status_code == 401


def _mk_race(db, *, dtstart, dtend, uid="r1"):
    from app.database import list_bummel_races, upsert_calendar_bummel_race
    conn = get_connection(db)
    upsert_calendar_bummel_race(conn, {
        "uid": uid, "summary": "B", "route": "EDWF,EDWG,EDWR",
        "dtstart": dtstart, "dtend": dtend,
    })
    conn.commit()
    rid = list_bummel_races(conn)[0]["id"]
    conn.close()
    return rid


def test_hide_suppresses_expired_race_against_auto_reveal(db):
    # Abgelaufenes Rennen (dtend in ferner Vergangenheit, unabhängig von der Systemuhr).
    from app.database import get_bummel_race, update_bummel_reveals
    rid = _mk_race(db, dtstart="2020-01-01T18:00:00Z", dtend="2020-01-01T20:00:00Z")
    asyncio.run(main.admin_hide_race(FakeReq(), rid))
    conn = get_connection(db)
    assert get_bummel_race(conn, rid)["reveal_suppressed"] == 1
    update_bummel_reveals(conn, "2020-01-02T00:00:00Z")  # Job würde sonst sofort enthüllen
    assert get_bummel_race(conn, rid)["revealed_at"] is None  # bleibt verborgen
    conn.close()


def test_hide_running_race_does_not_suppress(db):
    # Laufendes Rennen (dtend in ferner Zukunft) → nur verbergen, KEIN Dauer-Suppress.
    from app.database import get_bummel_race
    rid = _mk_race(db, dtstart="2099-01-01T18:00:00Z", dtend="2099-01-01T20:00:00Z")
    asyncio.run(main.admin_hide_race(FakeReq(), rid))
    conn = get_connection(db)
    assert get_bummel_race(conn, rid)["reveal_suppressed"] == 0
    conn.close()


def test_reveal_clears_suppression(db):
    # Manuelles Enthüllen hebt ein vorheriges Verbergen wieder auf.
    from app.database import get_bummel_race
    rid = _mk_race(db, dtstart="2020-01-01T18:00:00Z", dtend="2020-01-01T20:00:00Z")
    asyncio.run(main.admin_hide_race(FakeReq(), rid))
    asyncio.run(main.admin_reveal_race(FakeReq(), rid))
    conn = get_connection(db)
    row = get_bummel_race(conn, rid)
    assert row["reveal_suppressed"] == 0 and row["revealed_at"] is not None
    conn.close()


# ---------------------------------------------------------------------------
# GPS-Leg-Audit (Phase 1, Schatten): GET /api/admin/gps-leg-audit
# ---------------------------------------------------------------------------

class TestGpsLegAudit:
    """Read-only Audit-Endpoint: Refile-Flüge vs. on-demand berechnete GPS-Legs.

    Reale deutsche Plätze (EDDK/EDDW/EDDH) mit echten Koordinaten/Elevationen, damit der
    Detektor (geo.nearest_airport_icao_fast/airport_elevation_ft) auflöst."""

    CID = 5151
    A = (50.8659, 7.14274)    # EDDK, elev 302 ft
    B = (53.0475, 8.78667)    # EDDW, elev 14 ft
    C = (53.6304, 9.98823)    # EDDH, elev 53 ft

    @staticmethod
    def _pilot(conn, cid, name="Tester"):
        conn.execute(
            "INSERT OR IGNORE INTO pilots (cid,name,added_at) VALUES (?,?,?)",
            (cid, name, "2026-01-01T00:00:00Z"),
        )

    @staticmethod
    def _flight(conn, cid, dep, arr, logon, logoff, dist=50.0, block=30):
        conn.execute(
            "INSERT INTO flights (cid,callsign,aircraft_short,departure,arrival,logon_time,"
            "logoff_time,duration_min,distance_nm,block_min) "
            "VALUES (?,?,'C172',?,?,?,?,?,?,?)",
            (cid, f"FRS{cid}", dep, arr, logon, logoff, block, dist, block),
        )

    def _pos(self, conn, cid, ts, lat, lon, alt, gs):
        conn.execute(
            "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
            "groundspeed,heading,ts) VALUES (?,?,?,?,?,?,0,?)",
            (cid, f"FRS{cid}", lat, lon, alt, gs, ts),
        )

    def _leg_a_to_b(self, conn, cid, base):
        """Sauberer Track EDDK → EDDW (Boden, Steigflug > 500 ft AGL, Landung + Dwell)."""
        self._pos(conn, cid, _iso(base + timedelta(minutes=0)), *self.A, 302, 0)
        self._pos(conn, cid, _iso(base + timedelta(minutes=1)), *self.A, 302, 5)
        self._pos(conn, cid, _iso(base + timedelta(minutes=2)), *self.A, 1200, 80)
        self._pos(conn, cid, _iso(base + timedelta(minutes=20)), 52.0, 8.0, 5000, 120)
        self._pos(conn, cid, _iso(base + timedelta(minutes=38)), 53.0, 8.7, 500, 60)
        self._pos(conn, cid, _iso(base + timedelta(minutes=40)), *self.B, 20, 0)
        self._pos(conn, cid, _iso(base + timedelta(minutes=44)), *self.B, 20, 0)

    def _leg_b_to_c(self, conn, cid, base):
        """Anschluss EDDW → EDDH (Zwischenlandung ohne Refile)."""
        self._pos(conn, cid, _iso(base + timedelta(minutes=50)), *self.B, 800, 80)
        self._pos(conn, cid, _iso(base + timedelta(minutes=60)), 53.3, 9.3, 5000, 120)
        self._pos(conn, cid, _iso(base + timedelta(minutes=70)), 53.6, 9.9, 400, 60)
        self._pos(conn, cid, _iso(base + timedelta(minutes=72)), *self.C, 60, 0)
        self._pos(conn, cid, _iso(base + timedelta(minutes=76)), *self.C, 60, 0)

    def _platzrunde_a(self, conn, cid, base):
        """Zwei Platzrunden am selben Platz EDDK (Touch-and-go, kein Dwell nötig) — muss zu
        EINEM collapsed Flug werden (Spec A), nicht zwei Roh-Legs."""
        self._pos(conn, cid, _iso(base + timedelta(minutes=0)), *self.A, 302, 0)
        self._pos(conn, cid, _iso(base + timedelta(minutes=1)), *self.A, 302, 5)
        self._pos(conn, cid, _iso(base + timedelta(minutes=2)), *self.A, 1200, 80)   # Abheben 1
        self._pos(conn, cid, _iso(base + timedelta(minutes=5)), *self.A, 1000, 70)   # Platzrunde
        self._pos(conn, cid, _iso(base + timedelta(minutes=7)), *self.A, 350, 1)     # Touchdown 1
        self._pos(conn, cid, _iso(base + timedelta(minutes=8)), *self.A, 302, 0)     # Boden
        self._pos(conn, cid, _iso(base + timedelta(minutes=9)), *self.A, 1200, 80)   # Abheben 2
        self._pos(conn, cid, _iso(base + timedelta(minutes=12)), *self.A, 1000, 70)  # Platzrunde
        self._pos(conn, cid, _iso(base + timedelta(minutes=14)), *self.A, 350, 1)    # Touchdown 2
        self._pos(conn, cid, _iso(base + timedelta(minutes=16)), *self.A, 302, 0)    # Boden bis Ende

    def test_requires_admin(self, db):
        with pytest.raises(HTTPException) as e:
            asyncio.run(main.admin_gps_leg_audit(FakeReq(cookies={})))
        assert e.value.status_code == 401

    def test_match_single_leg(self, db):
        now = datetime.now(timezone.utc)
        base = now - timedelta(hours=2)
        conn = get_connection(db)
        self._pilot(conn, self.CID)
        self._flight(
            conn, self.CID, "EDDK", "EDDW",
            _iso(base - timedelta(minutes=2)), _iso(base + timedelta(minutes=50)),
        )
        self._leg_a_to_b(conn, self.CID, base)
        conn.commit(); conn.close()

        res = asyncio.run(main.admin_gps_leg_audit(FakeReq()))
        assert isinstance(res, dict)
        assert set(res.keys()) == {"window", "summary", "flights"}
        s = res["summary"]
        assert s["flights"] == 1
        assert s["matches"] == 1
        assert s["missing_gps_legs"] == 0
        assert s["extra_gps_legs"] == 0
        fr = next(f for f in res["flights"] if f["cid"] == self.CID)
        assert fr["n_legs"] == 1
        assert fr["dep"] == "EDDK" and fr["arr"] == "EDDW"
        assert fr["arr_match"] is True
        assert fr["legs"][0]["dep_icao"] == "EDDK"
        assert fr["legs"][0]["arr_icao"] == "EDDW"

    def test_extra_leg_intra_connection(self, db):
        now = datetime.now(timezone.utc)
        base = now - timedelta(hours=3)
        conn = get_connection(db)
        self._pilot(conn, self.CID)
        # EINE Connection (kein Refile), aber Track A→B→C mit zwei Landungen.
        self._flight(
            conn, self.CID, "EDDK", "EDDH",
            _iso(base - timedelta(minutes=2)), _iso(base + timedelta(minutes=80)),
        )
        self._leg_a_to_b(conn, self.CID, base)
        self._leg_b_to_c(conn, self.CID, base)
        conn.commit(); conn.close()

        res = asyncio.run(main.admin_gps_leg_audit(FakeReq()))
        s = res["summary"]
        assert s["extra_gps_legs"] >= 1
        fr = next(f for f in res["flights"] if f["cid"] == self.CID)
        assert fr["n_legs"] == 2

    def test_platzrunde_collapses_to_one_match(self, db):
        """Zwei Touch-and-gos am selben Platz (Platzrunde) sind EIN collapsed Flug — kein
        `extra_gps_legs`, `n_legs` bleibt 1 (Task 6, #23: collapsed statt Roh-Legs)."""
        now = datetime.now(timezone.utc)
        base = now - timedelta(hours=2)
        conn = get_connection(db)
        self._pilot(conn, self.CID)
        self._flight(
            conn, self.CID, "EDDK", "EDDK",
            _iso(base - timedelta(minutes=2)), _iso(base + timedelta(minutes=20)),
        )
        self._platzrunde_a(conn, self.CID, base)
        conn.commit(); conn.close()

        res = asyncio.run(main.admin_gps_leg_audit(FakeReq()))
        s = res["summary"]
        assert s["matches"] == 1
        assert s["extra_gps_legs"] == 0
        fr = next(f for f in res["flights"] if f["cid"] == self.CID)
        assert fr["n_legs"] == 1
        assert fr["legs"][0]["dep_icao"] == "EDDK"
        assert fr["legs"][0]["arr_icao"] == "EDDK"
        assert fr["arr_match"] is True

    def test_missing_no_track(self, db):
        now = datetime.now(timezone.utc)
        base = now - timedelta(hours=2)
        conn = get_connection(db)
        self._pilot(conn, self.CID)
        # Connection ohne jegliche position_history → kein GPS-Leg.
        self._flight(
            conn, self.CID, "EDDK", "EDDW",
            _iso(base), _iso(base + timedelta(minutes=40)),
        )
        conn.commit(); conn.close()

        res = asyncio.run(main.admin_gps_leg_audit(FakeReq()))
        assert res["summary"]["missing_gps_legs"] >= 1
        fr = next(f for f in res["flights"] if f["cid"] == self.CID)
        assert fr["n_legs"] == 0
        assert fr["arr_match"] is None


# ---------------------------------------------------------------------------
# Piloten-Detail: GET /api/pilots/{cid}/flights liefert GPS-Flüge (#23, Task 8)
# ---------------------------------------------------------------------------

class TestPilotFlightsEndpoint:
    """Endpoint zeigt jetzt die kanonischen GPS-Flüge (inkl. Zwischenlandung) statt der
    Refile-Flüge — Fremd-Callsigns (StatSim, Nicht-FRS) bleiben wie bisher sichtbar."""

    CID = 6161
    A = (50.8659, 7.14274)    # EDDK, elev 302 ft
    B = (53.0475, 8.78667)    # EDDW, elev 14 ft
    C = (53.6304, 9.98823)    # EDDH, elev 53 ft

    @staticmethod
    def _pilot(conn, cid, name="Tester"):
        conn.execute(
            "INSERT OR IGNORE INTO pilots (cid,name,added_at) VALUES (?,?,?)",
            (cid, name, "2026-01-01T00:00:00Z"),
        )

    @staticmethod
    def _flight(conn, cid, dep, arr, logon, logoff, dist=210.0, block=80):
        conn.execute(
            "INSERT INTO flights (cid,callsign,aircraft_short,departure,arrival,logon_time,"
            "logoff_time,duration_min,distance_nm,block_min) "
            "VALUES (?,?,'C172',?,?,?,?,?,?,?)",
            (cid, f"FRS{cid}", dep, arr, logon, logoff, block, dist, block),
        )

    def _pos(self, conn, cid, ts, lat, lon, alt, gs):
        conn.execute(
            "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
            "groundspeed,heading,ts) VALUES (?,?,?,?,?,?,0,?)",
            (cid, f"FRS{cid}", lat, lon, alt, gs, ts),
        )

    def _leg_a_to_b(self, conn, cid, base):
        """Sauberer Track EDDK → EDDW (Boden, Steigflug > 500 ft AGL, Landung + Dwell)."""
        self._pos(conn, cid, _iso(base + timedelta(minutes=0)), *self.A, 302, 0)
        self._pos(conn, cid, _iso(base + timedelta(minutes=1)), *self.A, 302, 5)
        self._pos(conn, cid, _iso(base + timedelta(minutes=2)), *self.A, 1200, 80)
        self._pos(conn, cid, _iso(base + timedelta(minutes=20)), 52.0, 8.0, 5000, 120)
        self._pos(conn, cid, _iso(base + timedelta(minutes=38)), 53.0, 8.7, 500, 60)
        self._pos(conn, cid, _iso(base + timedelta(minutes=40)), *self.B, 20, 0)
        self._pos(conn, cid, _iso(base + timedelta(minutes=44)), *self.B, 20, 0)

    def _leg_b_to_c(self, conn, cid, base):
        """Anschluss EDDW → EDDH (Zwischenlandung ohne Refile)."""
        self._pos(conn, cid, _iso(base + timedelta(minutes=50)), *self.B, 800, 80)
        self._pos(conn, cid, _iso(base + timedelta(minutes=60)), 53.3, 9.3, 5000, 120)
        self._pos(conn, cid, _iso(base + timedelta(minutes=70)), 53.6, 9.9, 400, 60)
        self._pos(conn, cid, _iso(base + timedelta(minutes=72)), *self.C, 60, 0)
        self._pos(conn, cid, _iso(base + timedelta(minutes=76)), *self.C, 60, 0)

    def test_gps_legs_with_intermediate_landing(self, db):
        """Track A→B→C EINER Connection (kein Refile) ⇒ 2 Flug-Zeilen statt 1 Refile-Flug."""
        now = datetime.now(timezone.utc)
        base = now - timedelta(hours=3)
        conn = get_connection(db)
        self._pilot(conn, self.CID)
        self._flight(
            conn, self.CID, "EDDK", "EDDH",
            _iso(base - timedelta(minutes=2)), _iso(base + timedelta(minutes=80)),
        )
        self._leg_a_to_b(conn, self.CID, base)
        self._leg_b_to_c(conn, self.CID, base)
        conn.commit(); conn.close()

        resp = asyncio.run(main.get_pilot_flights(self.CID))
        assert resp.headers.get("x-statsim-status") == "no-key"
        body = json.loads(resp.body)

        own = [f for f in body if f["cid"] == self.CID and f["source"] == "friesenspy"]
        assert len(own) == 2  # Zwischenlandung → 2 Zeilen (nicht mehr 1 Refile-Flug)
        assert all("gps_departure" in f and "plan_departure" in f for f in own)

        legs = sorted(own, key=lambda f: f["logon_time"])
        assert legs[0]["gps_departure"] == "EDDK" and legs[0]["gps_arrival"] == "EDDW"
        assert legs[1]["gps_departure"] == "EDDW" and legs[1]["gps_arrival"] == "EDDH"

    def test_foreign_callsign_statsim_flight_stays_visible(self, db):
        """StatSim-Flug des Piloten unter einem Nicht-FRS-Callsign bleibt in der Antwort
        (callsign_prefix="" wie bisher — kein Filtern auf Friesen-Präfix im Detail)."""
        now = datetime.now(timezone.utc)
        base = now - timedelta(hours=3)
        conn = get_connection(db)
        self._pilot(conn, self.CID)
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (70011, self.CID, "DFGKC", "EDDK", "EDDW", "C172",
             _iso(base), _iso(base + timedelta(minutes=44)), 44, "x"),
        )
        conn.commit(); conn.close()

        resp = asyncio.run(main.get_pilot_flights(self.CID))
        body = json.loads(resp.body)
        assert any(f["callsign"] == "DFGKC" and f["source"] == "statsim" for f in body)


def _upsert_airport(body):
    """v8.6.2: admin_upsert_airport braucht jetzt background_tasks -- der teure
    flight_cache-Rebuild läuft nicht mehr blockierend im Request. Gibt (result, bg) zurück;
    bg.tasks() lässt sich für Tests, die den Hintergrund-Effekt prüfen wollen, explizit ausführen."""
    from starlette.background import BackgroundTasks
    bg = BackgroundTasks()
    res = asyncio.run(main.admin_upsert_airport(FakeReq(body=body), background_tasks=bg))
    return res, bg


def _delete_airport(icao):
    from starlette.background import BackgroundTasks
    bg = BackgroundTasks()
    res = asyncio.run(main.admin_delete_airport(icao, FakeReq(), background_tasks=bg))
    return res, bg


class TestAdminAirports:
    """#50: Admin-Endpoints für Ergänzungs-Flugplätze (custom_airports)."""

    @pytest.fixture(autouse=True)
    def _reset_geo_cache(self):
        from app import geo
        geo.set_custom_airports([])
        yield
        geo.set_custom_airports([])

    def test_airports_requires_admin(self, db):
        with pytest.raises(HTTPException) as e:
            asyncio.run(main.admin_get_airports(FakeReq(cookies={})))
        assert e.value.status_code == 401

    def test_airports_crud(self, db):
        res, _ = _upsert_airport({
            "icao": "zztest", "name": "Testplatz", "lat": 12.34, "lon": 56.78, "elevation_ft": 100,
        })
        assert res["status"] == "ok"

        listing = asyncio.run(main.admin_get_airports(FakeReq()))
        rows = {r["icao"]: r for r in listing["airports"]}
        assert "ZZTEST" in rows  # Code wird normalisiert (uppercase) gespeichert
        assert rows["ZZTEST"]["name"] == "Testplatz"
        assert rows["ZZTEST"]["lat"] == 12.34

        # Update (gleicher Code, neue Werte)
        _upsert_airport({
            "icao": "ZZTEST", "name": "Umbenannt", "lat": 12.34, "lon": 56.78, "elevation_ft": 200,
        })
        listing2 = asyncio.run(main.admin_get_airports(FakeReq()))
        rows2 = {r["icao"]: r for r in listing2["airports"]}
        assert rows2["ZZTEST"]["name"] == "Umbenannt"
        assert rows2["ZZTEST"]["elevation_ft"] == 200

        # Löschen
        _delete_airport("ZZTEST")
        listing3 = asyncio.run(main.admin_get_airports(FakeReq()))
        assert "ZZTEST" not in {r["icao"] for r in listing3["airports"]}

    def test_airports_post_stores_reason(self, db):
        """#78: der Grund wird durchgereicht und wieder ausgeliefert -- er speist im Admin
        das Autocomplete auf die bereits vergebenen Gründe."""
        _upsert_airport({
            "icao": "ZZREASON", "name": "Mit Grund", "lat": 1.0, "lon": 2.0,
            "elevation_ft": 50, "reason": "Fehlt in airportsdata",
        })
        listing = asyncio.run(main.admin_get_airports(FakeReq()))
        rows = {r["icao"]: r for r in listing["airports"]}
        assert rows["ZZREASON"]["reason"] == "Fehlt in airportsdata"

    def test_airports_post_without_reason_stays_null(self, db):
        """#78: ein fehlender Grund darf das Speichern NIE blockieren -- der Eintrag selbst
        ist die Funktion, der Grund nur Dokumentation."""
        res, _ = _upsert_airport({
            "icao": "ZZNOREASON", "name": "Ohne Grund", "lat": 3.0, "lon": 4.0,
            "elevation_ft": None,
        })
        assert res["status"] == "ok"
        listing = asyncio.run(main.admin_get_airports(FakeReq()))
        rows = {r["icao"]: r for r in listing["airports"]}
        assert rows["ZZNOREASON"]["reason"] is None

    def test_airports_rejects_known_airportsdata_code(self, db):
        """Plausiprüfung (Fund dieser Session): EDXU (Hüttenbusch) war fälschlich als
        "fehlend" vermutet worden, steckte aber schon in airportsdata — muss OHNE override
        abgelehnt werden (409: „Bestätigung nötig", nicht 400 „echter Fehler")."""
        with pytest.raises(HTTPException) as e:
            _upsert_airport({
                "icao": "EDXU", "name": "Huettenbusch", "lat": 53.287, "lon": 8.947, "elevation_ft": 10,
            })
        assert e.value.status_code == 409

    def test_airports_post_known_code_requires_override(self, db):
        """#56: mit ``override: true`` wird ein bereits in airportsdata bekannter Code
        (EBUL-Fall: falsche Koordinaten) trotzdem gespeichert und überschreibt damit den
        Standard-Wert."""
        from app import geo
        real_lat, real_lon = geo.icao_to_coords("EDXU")
        res, _ = _upsert_airport({
            "icao": "EDXU", "name": "Huettenbusch (korrigiert)",
            "lat": 53.30, "lon": 8.95, "elevation_ft": 12, "override": True,
        })
        assert res["status"] == "ok"
        assert geo.icao_to_coords("EDXU") == (53.30, 8.95)
        assert geo.icao_to_coords("EDXU") != (real_lat, real_lon)

    def test_airports_upsert_invalidates_geo_cache(self, db):
        """Der geo-Cache (für Erkennung/Anzeige) wird SOFORT synchron aktualisiert, auch wenn
        der teure flight_cache-Rebuild erst im Hintergrund läuft (v8.6.2)."""
        from app import geo
        assert geo.icao_to_coords("ZZCACHE") is None
        _upsert_airport({
            "icao": "ZZCACHE", "name": "Cache-Test", "lat": 5.0, "lon": 6.0, "elevation_ft": None,
        })
        assert geo.icao_to_coords("ZZCACHE") == (5.0, 6.0)  # sofort aktuell, ohne Neustart

        _delete_airport("ZZCACHE")
        assert geo.icao_to_coords("ZZCACHE") is None  # nach dem Löschen wieder leer

    def test_airports_upsert_schedules_background_flight_cache_rebuild(self, db, monkeypatch):
        """v8.6.2: der VOLLE Rebuild (nicht der inkrementelle 7-Tage-Refresh) läuft nicht mehr
        blockierend im Request, sondern als BackgroundTask NACH der Response -- sonst bleiben
        ältere, durch den neuen Platz betroffene Flüge kaputt, aber Admin-Speichern/-Löschen
        fühlt sich eingefroren an (Fund: mehrere Sekunden bei großem StatSim-Bestand)."""
        calls = []
        monkeypatch.setattr("app.main.rebuild_flight_cache", lambda conn, full=False: calls.append(full))
        res, bg = _upsert_airport({
            "icao": "ZZREBUILD", "name": "x", "lat": 1.0, "lon": 1.0, "elevation_ft": None,
        })
        assert res["status"] == "ok"
        assert calls == []  # noch NICHT gelaufen -- Response kam zurück, bevor der Rebuild startet
        asyncio.run(bg())   # simuliert das, was FastAPI nach dem Response-Send tut
        assert calls == [True]

    def test_airports_radius_only_override_reuses_known_airportsdata_coords(self, db):
        """#62: Grossflughafen-Fall (EHAM/Schiphol) -- lat/lon duerfen leer bleiben, wenn der
        Code schon in airportsdata bekannt ist. Die Koordinaten werden automatisch uebernommen,
        nur radius_km wird tatsaechlich neu gesetzt (reiner Radius-Override, keine Korrektur der
        an sich schon korrekten Koordinate)."""
        from app import geo
        real_lat, real_lon = geo.icao_to_coords("EHAM")
        res, _ = _upsert_airport({
            "icao": "EHAM", "name": "Schiphol", "lat": None, "lon": None,
            "elevation_ft": None, "radius_km": 8.0, "override": True,
        })
        assert res["status"] == "ok"
        assert geo.icao_to_coords("EHAM") == (real_lat, real_lon)

        listing = asyncio.run(main.admin_get_airports(FakeReq()))
        rows = {r["icao"]: r for r in listing["airports"]}
        assert rows["EHAM"]["lat"] == real_lat
        assert rows["EHAM"]["lon"] == real_lon
        assert rows["EHAM"]["radius_km"] == 8.0

    def test_airports_known_code_without_override_still_409_even_without_coords(self, db):
        """Die 409-Plausipruefung (#50) muss VOR der lat/lon-Autofuell-Logik (#62) greifen --
        sonst koennte ein Radius-Override versehentlich einen bekannten Code ohne bewusste
        Bestaetigung anlegen."""
        with pytest.raises(HTTPException) as e:
            _upsert_airport({
                "icao": "EHAM", "name": "Schiphol", "lat": None, "lon": None,
                "elevation_ft": None, "radius_km": 8.0,
            })
        assert e.value.status_code == 409

    def test_airports_missing_coords_and_unknown_code_requires_lat_lon(self, db):
        """Ein Code, der NIRGENDS bekannt ist (weder airportsdata noch custom_airports), kann
        nicht ohne Koordinaten angelegt werden -- 400, nicht stillschweigend None speichern."""
        with pytest.raises(HTTPException) as e:
            _upsert_airport({
                "icao": "ZZBRANDNEU", "name": "x", "lat": None, "lon": None, "elevation_ft": None,
            })
        assert e.value.status_code == 400

    def test_airports_placeholder_code_rejected_even_with_override(self, db):
        """v10.4.6 (Fable-Review): "_"-Codes sind airportsdata-interne Platzhalter. Als Custom-
        Eintrag angelegt, umgehen sie die Unterdrueckung in geo._shadowed_codes ueber den
        Override-Zweig und holen den _MLH-Bug zurueck. 400 (echter Fehler), nicht 409
        (bestaetigbar) -- es gibt keinen Fall, in dem das gewollt waere."""
        for body in (
            {"icao": "_MLH", "name": "Basel", "lat": 47.5896, "lon": 7.52991, "elevation_ft": 885.0},
            {"icao": "_MLH", "name": "Basel", "lat": 47.5896, "lon": 7.52991,
             "elevation_ft": 885.0, "override": True},
        ):
            with pytest.raises(HTTPException) as e:
                _upsert_airport(body)
            assert e.value.status_code == 400
            assert "Platzhalter" in e.value.detail

    def test_airports_radius_km_must_be_positive(self, db):
        with pytest.raises(HTTPException) as e:
            _upsert_airport({
                "icao": "ZZRADTEST", "name": "x", "lat": 1.0, "lon": 1.0,
                "elevation_ft": None, "radius_km": 0,
            })
        assert e.value.status_code == 400

    def test_airports_lat_lon_optional_on_update_keeps_existing_custom_coords(self, db):
        """Ein zweites Speichern desselben Codes darf lat/lon leer lassen und behaelt dann die
        beim ERSTEN Mal gesetzten (custom) Koordinaten -- nicht nur bei airportsdata-Codes."""
        _upsert_airport({
            "icao": "ZZKEEP", "name": "Erstanlage", "lat": 3.0, "lon": 4.0, "elevation_ft": 50,
        })
        res, _ = _upsert_airport({
            "icao": "ZZKEEP", "name": "Nur Radius geaendert", "lat": None, "lon": None,
            "elevation_ft": None, "radius_km": 6.0,
        })
        assert res["status"] == "ok"
        listing = asyncio.run(main.admin_get_airports(FakeReq()))
        rows = {r["icao"]: r for r in listing["airports"]}
        assert rows["ZZKEEP"]["lat"] == 3.0
        assert rows["ZZKEEP"]["lon"] == 4.0
        assert rows["ZZKEEP"]["radius_km"] == 6.0


class TestAdminDetectionGaps:
    """v8.6.0: Admin-Prüfliste für Erkennungslücken (GPS-Start/-Landung fehlt trotz Plan)."""

    def _recent(self, minutes_ago):
        from datetime import datetime, timedelta, timezone
        return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def test_requires_admin(self, db):
        with pytest.raises(HTTPException) as e:
            asyncio.run(main.admin_get_detection_gaps(FakeReq(cookies={})))
        assert e.value.status_code == 401

    def test_dismiss_roundtrip(self, db):
        from app.database import get_connection, ensure_pilot, open_flight, close_flight
        conn = get_connection(db)
        ensure_pilot(conn, 42, "Test Pilot")
        logon = self._recent(120)
        fid = open_flight(conn, 42, "FRS42", "C172", "EDST", "EDWQ", logon)
        conn.commit()
        close_flight(conn, fid, self._recent(90))
        conn.execute("UPDATE flights SET distance_nm=40.0, duration_min=30 WHERE id=?", (fid,))
        conn.commit()
        conn.close()

        listing = asyncio.run(main.admin_get_detection_gaps(FakeReq()))
        assert any(g["cid"] == 42 for g in listing["gaps"])

        res = asyncio.run(main.admin_dismiss_detection_gap(FakeReq(body={
            "cid": 42, "logon_time": logon,
        })))
        assert res["status"] == "ok"

        listing2 = asyncio.run(main.admin_get_detection_gaps(FakeReq()))
        assert not any(g["cid"] == 42 for g in listing2["gaps"])


# ---------------------------------------------------------------------------
# #66 Task 7: Snapshot-Invalidierung bei Admin-Edit/Payload/Override.
# ---------------------------------------------------------------------------

class TestSnapshotInvalidation:
    """Ein eingefrorener ``progress_snapshot`` (Kutter oder Bummel) muss verworfen werden,
    sobald die zugrunde liegenden Daten BEWUSST geändert werden — auch beim manuellen Neu-
    berechnungs-Hebel "Event/Rennen antippen + (leer) speichern"."""

    def _kutter_event(self, db):
        conn = get_connection(db)
        eid = create_transport_event(
            conn, name="Kutter", route="EDWG,EDXH", destination="EDXH",
            dtstart="2026-07-01T09:00:00Z", dtend="2026-07-01T23:00:00Z",
        )
        write_progress_snapshot(conn, "kutter", eid, {"total_kg": 42.0}, "2026-07-01T23:00:01Z")
        conn.commit()
        conn.close()
        return eid

    def test_admin_update_kutter_clears_snapshot(self, db):
        eid = self._kutter_event(db)
        conn = get_connection(db)
        assert get_progress_snapshot(conn, "kutter", eid) is not None
        conn.close()

        # LEERER Body — heute überspringt der `if fields:`-Guard das Update, der Snapshot-
        # Delete muss trotzdem feuern (manueller Neuberechnungs-Hebel).
        res = asyncio.run(main.admin_update_transport_event(FakeReq(body={}), eid))
        assert res["status"] == "ok"

        conn = get_connection(db)
        assert get_progress_snapshot(conn, "kutter", eid) is None
        conn.close()

    def test_admin_update_kutter_clears_snapshot_with_fields(self, db):
        eid = self._kutter_event(db)
        res = asyncio.run(main.admin_update_transport_event(FakeReq(body={"name": "Neuer Name"}), eid))
        assert res["status"] == "ok"
        conn = get_connection(db)
        assert get_progress_snapshot(conn, "kutter", eid) is None
        conn.close()

    def test_admin_delete_transport_event_clears_snapshot(self, db):
        eid = self._kutter_event(db)
        asyncio.run(main.admin_delete_transport_event(FakeReq(), eid))
        conn = get_connection(db)
        assert get_progress_snapshot(conn, "kutter", eid) is None
        conn.close()

    def test_admin_payload_change_clears_all_kutter_snapshots(self, db):
        conn = get_connection(db)
        e1 = create_transport_event(
            conn, name="A", route="EDWG,EDXH", destination="EDXH",
            dtstart="2026-07-01T09:00:00Z", dtend="2026-07-01T23:00:00Z",
        )
        e2 = create_transport_event(
            conn, name="B", route="EDWG,EDXH", destination="EDXH",
            dtstart="2026-07-02T09:00:00Z", dtend="2026-07-02T23:00:00Z",
        )
        write_progress_snapshot(conn, "kutter", e1, {"total_kg": 1.0}, "t")
        write_progress_snapshot(conn, "kutter", e2, {"total_kg": 2.0}, "t")
        conn.commit()
        conn.close()

        res = asyncio.run(main.admin_upsert_payload(FakeReq(body={"type_code": "C172", "payload_kg": 300})))
        assert res["status"] == "ok"

        conn = get_connection(db)
        assert get_progress_snapshot(conn, "kutter", e1) is None
        assert get_progress_snapshot(conn, "kutter", e2) is None
        conn.close()

    def test_admin_default_payload_change_clears_all_kutter_snapshots(self, db):
        conn = get_connection(db)
        eid = create_transport_event(
            conn, name="A", route="EDWG,EDXH", destination="EDXH",
            dtstart="2026-07-01T09:00:00Z", dtend="2026-07-01T23:00:00Z",
        )
        write_progress_snapshot(conn, "kutter", eid, {"total_kg": 1.0}, "t")
        conn.commit()
        conn.close()

        res = asyncio.run(main.admin_set_default_payload(FakeReq(body={"default_kg": 250})))
        assert res["status"] == "ok"

        conn = get_connection(db)
        assert get_progress_snapshot(conn, "kutter", eid) is None
        conn.close()

    def _bummel_race(self, db):
        now = datetime.now(timezone.utc)
        dtstart = _iso(now - timedelta(hours=5))
        dtend = _iso(now - timedelta(hours=1))
        res = asyncio.run(main.admin_create_race(FakeReq(body={
            "route": "EDWF,EDWG,EDWR", "dtstart": dtstart, "dtend": dtend,
        })))
        rid = res["id"]
        conn = get_connection(db)
        write_progress_snapshot(conn, "bummel", rid, {"complete": []}, "t")
        conn.commit()
        conn.close()
        return rid

    def test_admin_bummel_override_clears_snapshot(self, db):
        rid = self._bummel_race(db)
        asyncio.run(main.admin_set_override(FakeReq(body={"cid": 200, "action": "exclude"}), rid))
        conn = get_connection(db)
        assert get_progress_snapshot(conn, "bummel", rid) is None
        conn.close()

    def test_admin_bummel_override_delete_clears_snapshot(self, db):
        rid = self._bummel_race(db)
        conn = get_connection(db)
        upsert_bummel_override(conn, rid, 200, "exclude")
        conn.commit()
        conn.close()
        # Snapshot nach dem Setzen erneut einfrieren (der Test prüft gezielt den Delete-Hook).
        conn = get_connection(db)
        write_progress_snapshot(conn, "bummel", rid, {"complete": []}, "t")
        conn.commit()
        conn.close()

        asyncio.run(main.admin_delete_override(FakeReq(), rid, 200))

        conn = get_connection(db)
        assert get_progress_snapshot(conn, "bummel", rid) is None
        conn.close()

    def test_admin_bummel_edit_clears_snapshot_even_with_empty_body(self, db):
        rid = self._bummel_race(db)
        res = asyncio.run(main.admin_update_race(FakeReq(body={}), rid))
        assert res["status"] == "ok"
        conn = get_connection(db)
        assert get_progress_snapshot(conn, "bummel", rid) is None
        conn.close()

    def test_admin_bummel_hide_clears_snapshot(self, db):
        rid = self._bummel_race(db)
        asyncio.run(main.admin_hide_race(FakeReq(), rid))
        conn = get_connection(db)
        assert get_progress_snapshot(conn, "bummel", rid) is None
        conn.close()

    def test_admin_bummel_delete_clears_snapshot(self, db):
        rid = self._bummel_race(db)
        asyncio.run(main.admin_delete_race(FakeReq(), rid))
        conn = get_connection(db)
        assert get_progress_snapshot(conn, "bummel", rid) is None
        conn.close()
