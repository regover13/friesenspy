"""#67: globale 365-Tage-Anzeige-/Eingabegrenze auf Statistik, Piloten und Events.

Reine Anzeige-/Eingabegrenze — nichts wird gelöscht. Der tägliche `position_history`-Cleanup
ist deaktiviert (poller.py), die Daten bleiben dauerhaft in der DB; sie werden ab
``_DATA_RETENTION_DAYS`` Tagen nur nicht mehr angezeigt/durchsuchbar.

Muster: reine Klemm-Helfer als Unit-Tests + endpoint-nahe Tests, die per monkeypatch die an die
DB-Schicht durchgereichten Zeitparameter abgreifen (deterministisch, kein Flight-Cache-Seed).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main
from app.database import _DATA_RETENTION_DAYS, init_db


def _days_ago(iso_z: str) -> float:
    """Wie viele Tage liegt ein ISO-Z-Zeitstempel vor jetzt."""
    dt = datetime.strptime(iso_z, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


# --------------------------------------------------------------------------
#  Reine Klemm-Helfer
# --------------------------------------------------------------------------

def test_clamp_days_caps_at_retention():
    assert main._clamp_retention_days(99999) == _DATA_RETENTION_DAYS
    assert main._clamp_retention_days(_DATA_RETENTION_DAYS + 1) == _DATA_RETENTION_DAYS


def test_clamp_days_passes_valid_window():
    assert main._clamp_retention_days(30) == 30
    assert main._clamp_retention_days(90) == 90
    assert main._clamp_retention_days(_DATA_RETENTION_DAYS) == _DATA_RETENTION_DAYS


def test_clamp_days_floors_at_one():
    assert main._clamp_retention_days(0) == 1
    assert main._clamp_retention_days(-10) == 1


def test_clamp_start_raises_old_start_to_floor():
    now = "2026-07-07T12:00:00Z"
    floor = main._retention_since(now)
    assert main._clamp_retention_start("2020-01-01T00:00:00Z", now) == floor


def test_clamp_start_keeps_recent_start():
    now = "2026-07-07T12:00:00Z"
    recent = "2026-06-01T00:00:00Z"  # innerhalb 365 Tage vor now
    assert main._clamp_retention_start(recent, now) == recent


def test_clamp_start_empty_defaults_to_floor():
    now = "2026-07-07T12:00:00Z"
    assert main._clamp_retention_start("", now) == main._retention_since(now)


# --------------------------------------------------------------------------
#  Endpoints wenden die Klemme an
# --------------------------------------------------------------------------

def _patch_settings(monkeypatch, tmp_path, **extra):
    db = str(tmp_path / "t.db")
    init_db(db)
    monkeypatch.setattr(
        main, "get_settings",
        lambda: SimpleNamespace(DB_PATH=db, CALLSIGN_PREFIX="FRS", **extra),
    )
    return db


def test_stats_endpoint_clamps_days(monkeypatch, tmp_path):
    captured = {}

    def fake_get_stats(conn, days, callsign_prefix):
        captured["days"] = days
        return []

    monkeypatch.setattr(main, "get_stats", fake_get_stats)
    _patch_settings(monkeypatch, tmp_path)
    client = TestClient(main.app)
    r = client.get("/api/stats", params={"days": 99999})
    assert r.status_code == 200
    assert captured["days"] == _DATA_RETENTION_DAYS


def test_stats_activity_endpoint_clamps_days(monkeypatch, tmp_path):
    captured = {}

    def fake_activity(conn, days, callsign_prefix):
        captured["days"] = days
        return {"periods": []}

    monkeypatch.setattr(main, "get_stats_activity", fake_activity)
    _patch_settings(monkeypatch, tmp_path)
    client = TestClient(main.app)
    r = client.get("/api/stats/activity", params={"days": 99999})
    assert r.status_code == 200
    assert captured["days"] == _DATA_RETENTION_DAYS


def test_pilot_flights_days0_uses_retention_window(monkeypatch, tmp_path):
    """`days=0` (Button „Alle Flüge laden (letztes Jahr)") zeigt jetzt genau 365 Tage,
    nicht mehr das alte ungekappte 99999-Tage-Fenster."""
    captured = {}

    def fake_canon(conn, cids, callsign_prefix, start):
        captured["start"] = start
        return {"pilots": []}

    monkeypatch.setattr(main, "canonicalize_legs", fake_canon)
    _patch_settings(monkeypatch, tmp_path, STATSIM_API_KEY="")
    client = TestClient(main.app)
    r = client.get("/api/pilots/12345/flights", params={"days": 0})
    assert r.status_code == 200
    assert 364 < _days_ago(captured["start"]) < 366


def test_pilot_flights_caps_large_days(monkeypatch, tmp_path):
    captured = {}

    def fake_canon(conn, cids, callsign_prefix, start):
        captured["start"] = start
        return {"pilots": []}

    monkeypatch.setattr(main, "canonicalize_legs", fake_canon)
    _patch_settings(monkeypatch, tmp_path, STATSIM_API_KEY="")
    client = TestClient(main.app)
    r = client.get("/api/pilots/12345/flights", params={"days": 99999})
    assert r.status_code == 200
    assert 364 < _days_ago(captured["start"]) < 366


def test_events_endpoint_clamps_start(monkeypatch, tmp_path):
    """Ein Events-Start älter als 365 Tage wird auf die Retention-Grenze angehoben, statt
    ungefiltert bis 2020 zurück abzufragen (Daten existieren, sind aber ausgeblendet)."""
    captured = {}

    def fake_gaph(conn, start, end):
        captured["start"] = start
        return []

    monkeypatch.setattr(main, "get_all_position_history", fake_gaph)
    _patch_settings(monkeypatch, tmp_path)
    client = TestClient(main.app)
    old_start = "2020-01-01T00:00:00Z"
    r = client.get("/api/events", params={
        "icao": "EDDK", "start": old_start, "end": "2026-07-07T00:00:00Z",
    })
    assert r.status_code == 200
    assert captured["start"] != old_start
    assert 364 < _days_ago(captured["start"]) < 366


def test_events_endpoint_keeps_recent_start(monkeypatch, tmp_path):
    """Ein Start innerhalb 365 Tage wird unverändert durchgereicht (kein unnötiges Anheben)."""
    captured = {}

    def fake_gaph(conn, start, end):
        captured["start"] = start
        return []

    monkeypatch.setattr(main, "get_all_position_history", fake_gaph)
    _patch_settings(monkeypatch, tmp_path)
    client = TestClient(main.app)
    now = main._now_iso()
    recent = main._retention_since(now)  # exakt an der Grenze → gilt als gültig (nicht älter)
    r = client.get("/api/events", params={"icao": "EDDK", "start": recent, "end": now})
    assert r.status_code == 200
    assert captured["start"] == recent
