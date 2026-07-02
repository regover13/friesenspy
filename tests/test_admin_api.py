"""Integrationstests für die Admin-Bummel-Endpoints (Auth + Persistenz)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as main
from app.auth import ADMIN_COOKIE, make_admin_token
from app.database import get_connection, init_db, upsert_push_subscription

SECRET = "s3cr3t"
PW = "harle15"
TOKEN = make_admin_token(SECRET, PW)


class FakeReq:
    def __init__(self, cookies=None, body=None, headers=None):
        self.cookies = cookies if cookies is not None else {ADMIN_COOKIE: TOKEN}
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
