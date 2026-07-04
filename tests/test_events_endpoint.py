"""Tests für /api/events (app/main.py) — Migration auf canonicalize_legs (#33).

Muster: TestClient(main.app) OHNE with-Block (kein lifespan/Poller-Start, s.
tests/test_transport.py TestKutterBadgeEndpoints), Fake-Settings via monkeypatch.
Seed-Helfer analog tests/test_canonicalize_legs.py (reale Plätze EDDK/EDDW).
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main
from app.database import ensure_pilot, get_connection, init_db, upsert_pilot

EDDK = (50.8659, 7.14274)
EDDW = (53.0475, 8.78667)


def _insert_flight(conn, **kw) -> int:
    ensure_pilot(conn, kw["cid"], f"Pilot {kw['cid']}")
    cols = [
        "cid", "callsign", "aircraft_short", "departure", "arrival", "logon_time",
        "logoff_time", "duration_min", "distance_nm", "route", "remarks",
        "cruise_altitude", "cruise_tas", "flight_rules", "aircraft_icao", "alternate",
        "deptime", "enroute_time", "fuel_time", "superseded_by", "block_min",
    ]
    defaults = {
        "aircraft_short": "C172", "departure": "", "arrival": "", "logoff_time": None,
        "duration_min": None, "distance_nm": 0, "route": "", "remarks": "",
        "cruise_altitude": "", "cruise_tas": "", "flight_rules": "", "aircraft_icao": "",
        "alternate": "", "deptime": "", "enroute_time": "", "fuel_time": "",
        "superseded_by": None, "block_min": None,
    }
    row = {**defaults, **kw}
    values = [row[c] for c in cols]
    cur = conn.execute(
        f"INSERT INTO flights ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        values,
    )
    return cur.lastrowid


def _insert_pos(conn, cid, ts, lat, lon, alt, gs, callsign="FRS") -> None:
    ensure_pilot(conn, cid, f"Pilot {cid}")
    conn.execute(
        "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,groundspeed,"
        "heading,ts) VALUES (?,?,?,?,?,?,0,?)",
        (cid, callsign, lat, lon, alt, gs, ts),
    )


def _seed_eddk_eddw_flight(conn, cid: int, callsign: str = "FRS30") -> None:
    """Realer EDDK→EDDW-Flug, 10:00–10:44 UTC (wie tests/test_canonicalize_legs.py)."""
    _insert_flight(
        conn, cid=cid, callsign=callsign, departure="EDDK", arrival="EDDW",
        logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
    )
    _insert_pos(conn, cid, "2026-07-02T10:00:00Z", *EDDK, 302, 0, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:01:00Z", *EDDK, 302, 10, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:03:00Z", *EDDK, 302, 12, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:05:00Z", *EDDK, 302, 15, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:06:00Z", *EDDK, 1200, 80, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:20:00Z", 52.0, 8.0, 5000, 120, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:38:00Z", 53.0, 8.7, 500, 60, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:40:00Z", *EDDW, 20, 0, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:44:00Z", *EDDW, 20, 0, callsign)


def _seed_eddk_landing_pause_continuation(conn, cid: int, callsign: str = "FRS31") -> None:
    """EDDK→EDDK (Platzrunde+echte Bodenpause) → EDDK→EDDW — muss als ZWEI GPS-Legs erkannt
    werden (die Pause ist zu lang für collapse_same_airport's Stop-and-Go-Dwell-Schwelle)."""
    _insert_flight(
        conn, cid=cid, callsign=callsign, departure="EDDK", arrival="EDDW",
        logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T11:00:00Z",
    )
    # Leg 1: Platzrunde EDDK -> EDDK
    _insert_pos(conn, cid, "2026-07-02T10:00:00Z", *EDDK, 302, 0, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:01:00Z", *EDDK, 302, 10, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:02:00Z", *EDDK, 1200, 80, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:05:00Z", *EDDK, 1000, 70, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:07:00Z", *EDDK, 350, 1, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:08:00Z", *EDDK, 302, 0, callsign)
    # Echte Bodenpause (41 min, > Dwell-Schwelle)
    _insert_pos(conn, cid, "2026-07-02T10:49:00Z", *EDDK, 302, 0, callsign)
    # Leg 2: EDDK -> EDDW
    _insert_pos(conn, cid, "2026-07-02T10:50:00Z", *EDDK, 1200, 80, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:55:00Z", 52.0, 8.0, 5000, 120, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:58:00Z", 53.0, 8.7, 500, 60, callsign)
    _insert_pos(conn, cid, "2026-07-02T11:00:00Z", *EDDW, 20, 0, callsign)


WINDOW = dict(start="2026-07-01T00:00:00Z", end="2026-07-03T00:00:00Z")


class TestEventsEndpoint:
    def _app(self, tmp_path, monkeypatch):
        p = str(tmp_path / "events.db")
        init_db(p)
        monkeypatch.setattr(
            main, "get_settings",
            lambda: SimpleNamespace(DB_PATH=p, CALLSIGN_PREFIX="FRS"),
        )
        return TestClient(main.app), p

    def test_gps_pilot_found_by_radius_gets_gps_split_legs(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        conn = get_connection(db)
        _seed_eddk_landing_pause_continuation(conn, cid=4401)
        conn.commit()
        conn.close()

        res = client.get("/api/events", params={"icao": "EDDK", "radius": 50, **WINDOW})
        assert res.status_code == 200
        data = res.json()
        assert len(data["pilots"]) == 1
        pilot = data["pilots"][0]
        assert pilot["cid"] == 4401
        # Landung+echte Pause+Weiterflug = zwei GPS-Legs, nicht ein Flug (Kernpunkt der Migration).
        assert len(pilot["flights"]) == 2
        legs = sorted(pilot["flights"], key=lambda f: f["logon_time"])
        assert legs[0]["gps_departure"] == "EDDK"
        assert legs[0]["gps_arrival"] == "EDDK"
        assert legs[1]["gps_departure"] == "EDDK"
        assert legs[1]["gps_arrival"] == "EDDW"
        # Neue Felder (statt der alten flachen departure/arrival) sind vorhanden.
        for leg in legs:
            assert "plan_departure" in leg
            assert "plan_arrival" in leg
            assert "connection_closed" in leg
            assert "aircraft" in leg
            assert "positions" not in leg  # nicht mehr embedded (#33)

    def test_statsim_only_pilot_without_position_history_still_found(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        conn = get_connection(db)
        upsert_pilot(conn, 4402, "StatSim Only")
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES "
            "(9001,4402,'FRS77','EDDK','EDDW','C172',"
            "'2026-07-02T09:00:00Z','2026-07-02T10:00:00Z',60,'x')",
        )
        conn.commit()
        conn.close()

        res = client.get("/api/events", params={"icao": "EDDK", "radius": 50, **WINDOW})
        assert res.status_code == 200
        data = res.json()
        assert len(data["pilots"]) == 1
        assert data["pilots"][0]["cid"] == 4402
        assert data["pilots"][0]["flights"][0]["source"] == "statsim"

    def test_foreign_callsign_flight_excluded_two_class_rule(self, tmp_path, monkeypatch):
        # 2-Klassen-Regel: ein StatSim-Flug mit fremdem Callsign eines bekannten Piloten
        # erscheint NICHT in der Event-Analyse (nur in der Piloten-Statistik, callsign_prefix="").
        client, db = self._app(tmp_path, monkeypatch)
        conn = get_connection(db)
        upsert_pilot(conn, 4403, "Mixed Pilot")
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES "
            "(9002,4403,'DLH123','EDDK','EDDW','A320',"
            "'2026-07-02T09:00:00Z','2026-07-02T10:00:00Z',60,'x')",
        )
        conn.commit()
        conn.close()

        res = client.get("/api/events", params={"icao": "EDDK", "radius": 50, **WINDOW})
        assert res.status_code == 200
        assert res.json()["pilots"] == []

    def test_global_search_finds_fs_pilot(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        conn = get_connection(db)
        _seed_eddk_eddw_flight(conn, cid=4404)
        conn.commit()
        conn.close()

        res = client.get("/api/events", params={"icao": "global", **WINDOW})
        assert res.status_code == 200
        data = res.json()
        assert any(p["cid"] == 4404 for p in data["pilots"])

    def test_no_hits_returns_empty_pilots(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        res = client.get("/api/events", params={"icao": "EDDK", "radius": 50, **WINDOW})
        assert res.status_code == 200
        assert res.json() == {"pilots": []}
