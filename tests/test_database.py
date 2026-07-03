"""Tests für app/database.py — alle Tests mit In-Memory-DB (:memory:)."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    audit_gps_vs_refile,
    canonicalize_flights,
    cleanup_old_history,
    count_uncached_statsim,
    get_uncached_statsim_ids,
    close_flight,
    consolidate_flights,
    ensure_pilot,
    get_all_position_history,
    get_connection,
    get_live_positions,
    get_pilot_flights_friesenspy,
    get_position_history,
    get_stats,
    get_statsim_flights_for_pilot,
    get_statsim_last_fetched,
    init_db,
    merge_fragmented_flights,
    open_flight,
    recompute_gps_legs,
    remove_live_position,
    save_position_history,
    upsert_live_position,
    upsert_statsim_flights,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    """In-Memory-Verbindung mit vollständig initialisierten Tabellen."""
    init_db(":memory:")          # Initialisierung auf Datei-Ebene testen wir separat
    conn = get_connection(":memory:")
    # Tabellen anlegen (get_connection macht kein init_db)
    from app.database import _DDL
    conn.executescript(_DDL)
    # Partieller Unique-Index (in init_db erst nach Konsolidierung angelegt; hier frische DB)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_flights_session "
        "ON flights(cid, logon_time) WHERE superseded_by IS NULL"
    )
    conn.commit()
    return conn


def _ts_offset(minutes: int = 0) -> str:
    """UTC-Timestamp mit optionalem Offset in Minuten."""
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts_days_ago(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_creates_all_tables(self, tmp_path):
        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        conn = sqlite3.connect(db_file)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert {"pilots", "flights", "live_positions", "position_history"} <= tables

    def test_creates_indices(self, tmp_path):
        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        conn = sqlite3.connect(db_file)
        indices = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        conn.close()
        assert "idx_ph_cid_ts" in indices
        assert "idx_ph_ts" in indices

    def test_idempotent(self, tmp_path):
        """Zweifaches Aufrufen von init_db wirft keinen Fehler."""
        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        init_db(db_file)  # should not raise

    def test_wal_mode_enabled(self, tmp_path):
        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        conn = sqlite3.connect(db_file)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------

class TestGetConnection:
    def test_returns_connection(self, tmp_path):
        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        conn = get_connection(db_file)
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_row_factory_is_set(self, tmp_path):
        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        conn = get_connection(db_file)
        assert conn.row_factory is sqlite3.Row
        conn.close()

    def test_wal_mode_on_connection(self, tmp_path):
        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        conn = get_connection(db_file)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"


# ---------------------------------------------------------------------------
# ensure_pilot
# ---------------------------------------------------------------------------

class TestEnsurePilot:
    def test_inserts_pilot(self):
        conn = _make_conn()
        ensure_pilot(conn, 1234567, "Max Muster")
        conn.commit()
        row = conn.execute("SELECT * FROM pilots WHERE cid = 1234567").fetchone()
        assert row is not None
        assert row["name"] == "Max Muster"
        conn.close()

    def test_insert_or_ignore_no_duplicate(self):
        conn = _make_conn()
        ensure_pilot(conn, 1234567, "Max Muster")
        ensure_pilot(conn, 1234567, "Changed Name")  # should be ignored
        conn.commit()
        rows = conn.execute("SELECT * FROM pilots WHERE cid = 1234567").fetchall()
        assert len(rows) == 1
        assert rows[0]["name"] == "Max Muster"  # original name kept
        conn.close()

    def test_multiple_pilots(self):
        conn = _make_conn()
        ensure_pilot(conn, 111, "Alice")
        ensure_pilot(conn, 222, "Bob")
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM pilots").fetchone()[0]
        assert count == 2
        conn.close()


# ---------------------------------------------------------------------------
# open_flight / close_flight
# ---------------------------------------------------------------------------

class TestFlightRoundtrip:
    def test_open_flight_returns_id(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test Pilot")
        flight_id = open_flight(conn, 1, "FRS001", "B738", "EDDH", "EDDF", _ts_offset())
        conn.commit()
        assert isinstance(flight_id, int)
        assert flight_id > 0
        conn.close()

    def test_close_flight_sets_logoff_and_duration(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test Pilot")
        logon = _ts_offset(-90)   # 90 minutes ago
        logoff = _ts_offset(0)    # now
        flight_id = open_flight(conn, 1, "FRS001", "B738", "EDDH", "EDDF", logon)
        conn.commit()
        close_flight(conn, flight_id, logoff)
        conn.commit()

        row = conn.execute("SELECT * FROM flights WHERE id = ?", (flight_id,)).fetchone()
        assert row["logoff_time"] == logoff
        # Duration should be ~90 min (allow ±1 min for rounding)
        assert 89 <= row["duration_min"] <= 91
        conn.close()

    def test_duration_min_calculated_correctly(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test Pilot")
        logon = "2025-01-01T10:00:00Z"
        logoff = "2025-01-01T11:30:00Z"  # exactly 90 minutes
        flight_id = open_flight(conn, 1, "FRS001", "B738", "EDDH", "EDDF", logon)
        conn.commit()
        close_flight(conn, flight_id, logoff)
        conn.commit()

        row = conn.execute("SELECT duration_min FROM flights WHERE id = ?", (flight_id,)).fetchone()
        assert row["duration_min"] == 90
        conn.close()

    def test_close_nonexistent_flight_does_not_raise(self):
        conn = _make_conn()
        close_flight(conn, 99999, _ts_offset())  # should not raise
        conn.close()

    def test_open_flight_reopens_closed_same_session(self):
        """Gleiche VATSIM-Verbindung (cid+logon_time), aber die Zeile wurde zwischenzeitlich
        geschlossen (Feed-Aussetzer): open_flight muss die Zeile RE-ÖFFNEN — die Verbindung
        lebt nachweislich noch. Sonst laufen alle Folgeflüge der Session ins Leere (A1)."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test Pilot")
        logon = "2026-07-01T17:04:16Z"
        fid = open_flight(conn, 1, "FRS61", "BN2P", "EDWG", "EDXH", logon)
        conn.commit()
        close_flight(conn, fid, "2026-07-01T17:32:16Z")  # Aussetzer-Close
        conn.commit()

        fid2 = open_flight(conn, 1, "FRS61", "BN2P", "EDWG", "EDXH", logon)
        conn.commit()
        assert fid2 == fid  # dieselbe Session, dieselbe Zeile
        row = conn.execute(
            "SELECT logoff_time, duration_min, distance_nm, block_min FROM flights WHERE id = ?",
            (fid,),
        ).fetchone()
        assert row["logoff_time"] is None       # wieder offen
        assert row["duration_min"] is None      # wird beim echten Close neu berechnet
        assert row["block_min"] is None
        conn.close()

    def test_logoff_time_null_before_close(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test Pilot")
        flight_id = open_flight(conn, 1, "FRS001", "B738", "EDDH", "EDDF", _ts_offset())
        conn.commit()
        row = conn.execute("SELECT logoff_time, duration_min FROM flights WHERE id = ?", (flight_id,)).fetchone()
        assert row["logoff_time"] is None
        assert row["duration_min"] is None
        conn.close()


# ---------------------------------------------------------------------------
# upsert_live_position / remove_live_position
# ---------------------------------------------------------------------------

class TestLivePosition:
    def _insert(self, conn, cid=1001, callsign="FRS001"):
        upsert_live_position(
            conn, cid, callsign, "B738", "EDDH", "EDDF",
            53.6, 9.98, 35000, 450, 180, _ts_offset(),
        )

    def test_upsert_inserts_new(self):
        conn = _make_conn()
        self._insert(conn)
        conn.commit()
        rows = get_live_positions(conn)
        assert len(rows) == 1
        assert rows[0]["cid"] == 1001
        conn.close()

    def test_upsert_replaces_existing(self):
        conn = _make_conn()
        self._insert(conn, cid=1001)
        conn.commit()
        # Update with different altitude
        upsert_live_position(
            conn, 1001, "FRS001", "B738", "EDDH", "EDDF",
            53.7, 9.99, 36000, 460, 185, _ts_offset(),
        )
        conn.commit()
        rows = get_live_positions(conn)
        assert len(rows) == 1
        assert rows[0]["altitude"] == 36000
        conn.close()

    def test_remove_live_position(self):
        conn = _make_conn()
        self._insert(conn, cid=1001)
        self._insert(conn, cid=1002, callsign="FFR002")
        conn.commit()
        remove_live_position(conn, 1001)
        conn.commit()
        rows = get_live_positions(conn)
        cids = [r["cid"] for r in rows]
        assert 1001 not in cids
        assert 1002 in cids
        conn.close()

    def test_remove_nonexistent_does_not_raise(self):
        conn = _make_conn()
        remove_live_position(conn, 99999)  # should not raise
        conn.close()

    def test_get_live_positions_empty(self):
        conn = _make_conn()
        rows = get_live_positions(conn)
        assert rows == []
        conn.close()

    def test_updated_at_is_set(self):
        conn = _make_conn()
        self._insert(conn)
        conn.commit()
        rows = get_live_positions(conn)
        assert rows[0]["updated_at"] is not None
        conn.close()


# ---------------------------------------------------------------------------
# save_position_history / get_position_history / get_all_position_history
# ---------------------------------------------------------------------------

class TestPositionHistory:
    def test_save_position_history(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test Pilot")
        conn.commit()
        save_position_history(conn, 1, "FRS001", 53.6, 9.98, 35000, 450, 180)
        conn.commit()
        rows = conn.execute("SELECT * FROM position_history WHERE cid = 1").fetchall()
        assert len(rows) == 1
        assert rows[0]["callsign"] == "FRS001"
        conn.close()

    def test_get_position_history_filters_by_cid(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Pilot A")
        ensure_pilot(conn, 2, "Pilot B")
        conn.commit()
        # Insert history at specific timestamps
        ts1 = "2025-06-01T10:00:00Z"
        ts2 = "2025-06-01T10:15:00Z"
        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, heading, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "FRS001", 53.0, 9.0, 35000, 450, 90, ts1),
        )
        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, heading, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (2, "FFR002", 54.0, 10.0, 36000, 460, 180, ts2),
        )
        conn.commit()

        hist = get_position_history(conn, 1, "2025-06-01T00:00:00Z", "2025-06-02T00:00:00Z")
        assert len(hist) == 1
        assert hist[0]["cid"] == 1
        conn.close()

    def test_get_all_position_history(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Pilot A")
        ensure_pilot(conn, 2, "Pilot B")
        conn.commit()
        ts1 = "2025-06-01T10:00:00Z"
        ts2 = "2025-06-01T10:15:00Z"
        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, heading, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "FRS001", 53.0, 9.0, 35000, 450, 90, ts1),
        )
        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, heading, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (2, "FFR002", 54.0, 10.0, 36000, 460, 180, ts2),
        )
        conn.commit()

        all_hist = get_all_position_history(conn, "2025-06-01T00:00:00Z", "2025-06-02T00:00:00Z")
        assert len(all_hist) == 2
        cids = {r["cid"] for r in all_hist}
        assert cids == {1, 2}
        conn.close()

    def test_get_all_position_history_time_filter(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Pilot A")
        conn.commit()
        ts_in = "2025-06-01T12:00:00Z"
        ts_out = "2025-05-31T12:00:00Z"
        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, heading, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "FRS001", 53.0, 9.0, 35000, 450, 90, ts_in),
        )
        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, heading, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "FRS001", 53.0, 9.0, 35000, 450, 90, ts_out),
        )
        conn.commit()

        result = get_all_position_history(conn, "2025-06-01T00:00:00Z", "2025-06-02T00:00:00Z")
        assert len(result) == 1
        assert result[0]["ts"] == ts_in
        conn.close()

    def test_get_position_history_empty(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test Pilot")
        conn.commit()
        result = get_position_history(conn, 1, "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z")
        assert result == []
        conn.close()


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_stats_single_pilot(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Heinz Friesen")
        conn.commit()

        # Two completed flights: 60 min + 90 min = 150 min = 2.5 h
        # Use recent timestamps (within the last 30 days) so the date filter matches
        logon1 = _ts_offset(-60 * 24 * 5)      # 5 days ago, flight start
        logoff1 = _ts_offset(-60 * 24 * 5 + 60)  # 5 days ago + 60 min
        logon2 = _ts_offset(-60 * 24 * 3)      # 3 days ago
        logoff2 = _ts_offset(-60 * 24 * 3 + 90)  # 3 days ago + 90 min

        fid1 = open_flight(conn, 1, "FRS001", "B738", "EDDH", "EDDF", logon1)
        conn.commit()
        close_flight(conn, fid1, logoff1)
        conn.commit()

        fid2 = open_flight(conn, 1, "FRS001", "B738", "EDDF", "EDDH", logon2)
        conn.commit()
        close_flight(conn, fid2, logoff2)
        conn.commit()

        stats = get_stats(conn, days=30)
        assert len(stats) == 1
        s = stats[0]
        assert s["cid"] == 1
        assert s["name"] == "Heinz Friesen"
        assert s["flight_count"] == 2
        assert "last_flight" in s
        assert s["last_flight"] is not None
        conn.close()

    def test_stats_multiple_pilots(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Alice")
        ensure_pilot(conn, 2, "Bob")
        conn.commit()

        # Alice: 60 min — use recent timestamps so date filter matches
        alice_logon = _ts_offset(-60 * 24 * 2)
        alice_logoff = _ts_offset(-60 * 24 * 2 + 60)
        fid = open_flight(conn, 1, "FRS001", "B738", "EDDH", "EDDF", alice_logon)
        conn.commit()
        close_flight(conn, fid, alice_logoff)
        conn.commit()

        # Bob: 30 min
        bob_logon = _ts_offset(-60 * 24 * 1)
        bob_logoff = _ts_offset(-60 * 24 * 1 + 30)
        fid2 = open_flight(conn, 2, "FRS002", "C172", "EDHE", "EDXW", bob_logon)
        conn.commit()
        close_flight(conn, fid2, bob_logoff)
        conn.commit()

        stats = get_stats(conn, days=30)
        assert len(stats) == 2
        by_cid = {s["cid"]: s for s in stats}
        assert by_cid[1]["last_flight"] is not None
        assert by_cid[1]["last_flight"].startswith("20")
        assert by_cid[2]["last_flight"] is not None
        assert by_cid[2]["last_flight"].startswith("20")
        conn.close()

    def test_stats_open_flights_excluded(self):
        """Noch offene Flüge (logoff_time IS NULL) dürfen nicht in die Statistik."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test Pilot")
        conn.commit()

        # Open flight — never closed
        open_flight(conn, 1, "FRS001", "B738", "EDDH", "EDDF", _ts_offset(-60))
        conn.commit()

        stats = get_stats(conn, days=365)
        assert len(stats) == 1
        assert stats[0]["flight_count"] == 0
        assert stats[0]["last_flight"] is None
        conn.close()

    def test_stats_no_pilots(self):
        conn = _make_conn()
        stats = get_stats(conn, days=30)
        assert stats == []
        conn.close()


# ---------------------------------------------------------------------------
# cleanup_old_history
# ---------------------------------------------------------------------------

class TestCleanupOldHistory:
    def test_deletes_old_entries(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test Pilot")
        conn.commit()

        # Insert one old entry (100 days ago) and one recent entry
        old_ts = _ts_days_ago(100)
        recent_ts = _ts_days_ago(5)

        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, heading, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "FRS001", 53.0, 9.0, 35000, 450, 90, old_ts),
        )
        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, heading, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "FRS001", 53.0, 9.0, 35000, 450, 90, recent_ts),
        )
        conn.commit()

        deleted = cleanup_old_history(conn, days=90)
        conn.commit()
        assert deleted == 1

        remaining = conn.execute("SELECT COUNT(*) FROM position_history").fetchone()[0]
        assert remaining == 1
        conn.close()

    def test_returns_count_of_deleted(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test Pilot")
        conn.commit()

        for i in range(3):
            old_ts = _ts_days_ago(100 + i)
            conn.execute(
                "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, heading, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (1, "FRS001", 53.0, 9.0, 35000, 450, 90, old_ts),
            )
        conn.commit()

        deleted = cleanup_old_history(conn, days=90)
        conn.commit()
        assert deleted == 3
        conn.close()

    def test_no_deletion_when_all_recent(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test Pilot")
        conn.commit()

        recent_ts = _ts_days_ago(10)
        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, heading, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "FRS001", 53.0, 9.0, 35000, 450, 90, recent_ts),
        )
        conn.commit()

        deleted = cleanup_old_history(conn, days=90)
        conn.commit()
        assert deleted == 0
        conn.close()


# ---------------------------------------------------------------------------
# statsim_cache
# ---------------------------------------------------------------------------

class TestStatSimCache:
    def test_upsert_and_get(self):
        conn = _make_conn()
        flights = [{
            "statsim_id": 1001, "cid": 9999, "callsign": "FRS99",
            "departure": "EDKB", "arrival": "EDDK", "aircraft": "PA24",
            "logon_time": _ts_offset(-60), "logoff_time": _ts_offset(-15),
            "duration_min": 45,
        }]
        upsert_statsim_flights(conn, flights)
        conn.commit()
        result = get_statsim_flights_for_pilot(conn, 9999, days=30)
        assert len(result) == 1
        assert result[0]["callsign"] == "FRS99"
        conn.close()

    def test_upsert_replace(self):
        conn = _make_conn()
        f = {"statsim_id": 1001, "cid": 9999, "callsign": "FRS99",
             "departure": "EDKB", "arrival": "EDDK", "aircraft": "PA24",
             "logon_time": _ts_offset(-60), "logoff_time": None, "duration_min": None}
        upsert_statsim_flights(conn, [f])
        conn.commit()
        upsert_statsim_flights(conn, [{**f, "duration_min": 30}])
        conn.commit()
        result = get_statsim_flights_for_pilot(conn, 9999, days=30)
        assert len(result) == 1
        assert result[0]["duration_min"] == 30
        conn.close()

    def test_last_fetched_none_when_empty(self):
        conn = _make_conn()
        result = get_statsim_last_fetched(conn, 9999)
        assert result is None
        conn.close()

    def test_pilot_friesenspy_flights(self):
        conn = _make_conn()
        ensure_pilot(conn, 1, "Test")
        conn.commit()
        fid = open_flight(conn, 1, "FRS01", "PA24", "EDKB", "EDDK", _ts_offset(-90))
        close_flight(conn, fid, _ts_offset(-45))
        conn.commit()
        result = get_pilot_flights_friesenspy(conn, 1, days=30)
        assert len(result) == 1
        assert result[0]["callsign"] == "FRS01"
        conn.close()


# ---------------------------------------------------------------------------
# merge_fragmented_flights
# ---------------------------------------------------------------------------

class TestMergeFragmentedFlights:
    def _flight(self, callsign, dep, arr, logon, logoff, duration):
        return {
            "callsign": callsign,
            "departure": dep,
            "arrival": arr,
            "logon_time": logon,
            "logoff_time": logoff,
            "duration_min": duration,
            "aircraft_short": "B738",
        }

    def test_merge_one_missing_fp(self):
        """Erster Flug ohne FP + zweiter mit FP innerhalb 5 Min → ein Flug."""
        f1 = self._flight("FRS153", "",     "",     "2026-06-06T08:00:00Z", "2026-06-06T08:02:00Z", 2)
        f2 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:04:00Z", "2026-06-06T08:55:00Z", 51)
        result = merge_fragmented_flights([f1, f2])
        assert len(result) == 1
        assert result[0]["departure"] == "EDDN"
        assert result[0]["arrival"] == "EDPH"
        assert result[0]["logon_time"] == "2026-06-06T08:00:00Z"
        assert result[0]["logoff_time"] == "2026-06-06T08:55:00Z"
        assert result[0]["duration_min"] == 53

    def test_merge_both_same_fp(self):
        """Beide Flüge mit gleicher Route (kurzer Disconnect) → ein Flug."""
        f1 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:00:00Z", "2026-06-06T08:06:00Z", 6)
        f2 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:09:00Z", "2026-06-06T08:55:00Z", 46)
        result = merge_fragmented_flights([f1, f2])
        assert len(result) == 1
        assert result[0]["departure"] == "EDDN"
        assert result[0]["arrival"] == "EDPH"
        assert result[0]["duration_min"] == 52

    def test_no_merge_different_route(self):
        """Zwei Flüge mit verschiedener Route → nicht mergen."""
        f1 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:00:00Z", "2026-06-06T08:49:00Z", 49)
        f2 = self._flight("FRS153", "EDPH", "EDDH", "2026-06-06T09:00:00Z", "2026-06-06T09:30:00Z", 30)
        result = merge_fragmented_flights([f1, f2])
        assert len(result) == 2

    def test_merge_same_fp_within_window(self):
        """Gleiche Route, 14-Min-Lücke (z.B. Netzausfall) → ein Flug (same-FP-Fenster 30 Min)."""
        f1 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:00:00Z", "2026-06-06T08:06:00Z", 6)
        f2 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:20:00Z", "2026-06-06T09:00:00Z", 40)
        result = merge_fragmented_flights([f1, f2])
        assert len(result) == 1
        assert result[0]["duration_min"] == 46

    def test_no_merge_gap_too_large(self):
        """Gleiche Route aber Gap > 30 Min → nicht mergen (außerhalb same-FP-Fenster)."""
        f1 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:00:00Z", "2026-06-06T08:06:00Z", 6)
        f2 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:40:00Z", "2026-06-06T09:20:00Z", 40)
        result = merge_fragmented_flights([f1, f2])
        assert len(result) == 2

    def test_no_merge_nofp_gap_over_window(self):
        """no-FP-Fragment + Folgeflug mit Gap > 15 Min → nicht mergen (no-FP-Fenster 15 Min)."""
        f1 = self._flight("FRS153", "", "", "2026-06-06T08:00:00Z", "2026-06-06T08:02:00Z", 2)
        f2 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:20:00Z", "2026-06-06T08:55:00Z", 35)
        result = merge_fragmented_flights([f1, f2])
        assert len(result) == 2

    def test_no_merge_different_callsign(self):
        """Verschiedene Callsigns → nicht mergen."""
        f1 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:00:00Z", "2026-06-06T08:04:00Z", 4)
        f2 = self._flight("FRS154", "EDDN", "EDPH", "2026-06-06T08:06:00Z", "2026-06-06T08:50:00Z", 44)
        result = merge_fragmented_flights([f1, f2])
        assert len(result) == 2

    def test_no_merge_return_flight_with_stale_fp(self):
        """Regression A3 (Ralf, Live-Test 2026-07-01): Hinflug EDWG→EDXH ist am Ziel GELANDET
        (letzte Position im Zielradius, am Boden); der Rückflug startet 16 min später mit
        stehengebliebenem Flugplan EDWG→EDXH ebenfalls in EDXH. Ein abgeflogener Flugplan
        darf nicht als Reconnect fortgesetzt werden → ZWEI Flüge."""
        conn = _make_conn()
        ensure_pilot(conn, 999, "Ralf")
        pos = [
            # Segment A (Hinflug): Start EDWG, Landung + Abstellen EDXH
            (53.78278, 7.91389, 0,  "2026-07-01T18:29:00Z"),
            (53.95000, 7.91400, 85, "2026-07-01T18:38:00Z"),
            (54.18500, 7.91580, 25, "2026-07-01T18:49:30Z"),
            (54.18528, 7.91583, 0,  "2026-07-01T18:50:20Z"),
            # Segment B (realer Rückflug): Start EDXH, Landung EDWG
            (54.18528, 7.91583, 0,  "2026-07-01T19:06:40Z"),
            (54.10000, 7.91500, 75, "2026-07-01T19:09:00Z"),
            (53.80000, 7.91400, 70, "2026-07-01T19:18:00Z"),
            (53.78278, 7.91389, 0,  "2026-07-01T19:20:00Z"),
        ]
        for lat, lon, gs, ts in pos:
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (999,'FRS102',?,?,1000,?,0,?)",
                (lat, lon, gs, ts),
            )
        conn.commit()
        f1 = dict(self._flight("FRS102", "EDWG", "EDXH",
                               "2026-07-01T18:28:32Z", "2026-07-01T18:50:24Z", 21), cid=999)
        f2 = dict(self._flight("FRS102", "EDWG", "EDXH",
                               "2026-07-01T19:06:26Z", "2026-07-01T19:20:20Z", 13), cid=999)
        result = merge_fragmented_flights([f1, f2], conn=conn)
        conn.close()
        assert len(result) == 2  # Hin- und Rückflug bleiben getrennt

    def test_merge_still_works_for_midflight_reconnect(self):
        """Gegentest zu A3: Disconnect MITTEN im Flug (letzte Position airborne, weit vor dem
        Ziel) + Reconnect mit gleichem FP → weiterhin EIN Flug (der eigentliche Merge-Zweck)."""
        conn = _make_conn()
        ensure_pilot(conn, 998, "Tester")
        pos = [
            # Segment A: Start EDWG, Abbruch airborne ~20 km vor EDXH
            (53.78278, 7.91389, 0,  "2026-07-01T18:00:30Z"),
            (53.99000, 7.91400, 85, "2026-07-01T18:09:30Z"),
            # Segment B: Wiedereinstieg kurz dahinter, Landung EDXH
            (54.01000, 7.91500, 85, "2026-07-01T18:14:30Z"),
            (54.18528, 7.91583, 0,  "2026-07-01T18:30:00Z"),
        ]
        for lat, lon, gs, ts in pos:
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (998,'FRS7',?,?,2000,?,0,?)",
                (lat, lon, gs, ts),
            )
        conn.commit()
        f1 = dict(self._flight("FRS7", "EDWG", "EDXH",
                               "2026-07-01T18:00:00Z", "2026-07-01T18:10:00Z", 10), cid=998)
        f2 = dict(self._flight("FRS7", "EDWG", "EDXH",
                               "2026-07-01T18:14:00Z", "2026-07-01T18:30:10Z", 16), cid=998)
        result = merge_fragmented_flights([f1, f2], conn=conn)
        conn.close()
        assert len(result) == 1  # echter Reconnect wird weiterhin gemergt

    def test_no_merge_after_landing_even_away_from_fp_arrival(self):
        """Regression Live-Test 2026-07-01, Teil 2 (Ralf, 286+287): der Rückflug mit stehen-
        gebliebenem FP EDWG→EDXH landet in EDWG — also am FP-START, nicht am FP-Ziel. Der
        nächste echte Flug (gleicher FP, 2 min später) schließt geografisch nahtlos an und
        fliegt Richtung Ziel → alle bisherigen Prüfungen passieren. Regel: ein Segment, das
        GEFLOGEN ist und am Boden endete, ist abgeschlossen — egal wo es gelandet ist."""
        conn = _make_conn()
        ensure_pilot(conn, 997, "Ralf")
        pos = [
            # Segment A (realer Rückflug EDXH→EDWG, FP stale EDWG→EDXH): Landung EDWG
            (54.18528, 7.91583, 0,  "2026-07-01T19:06:40Z"),
            (54.10000, 7.91500, 75, "2026-07-01T19:09:00Z"),
            (53.79000, 7.91400, 70, "2026-07-01T19:18:00Z"),
            (53.78278, 7.91389, 5,  "2026-07-01T19:19:50Z"),
            (53.78278, 7.91389, 0,  "2026-07-01T19:20:15Z"),
            # Segment B (echter nächster Hinflug EDWG→EDXH)
            (53.78278, 7.91389, 0,  "2026-07-01T19:22:40Z"),
            (53.80000, 7.91400, 70, "2026-07-01T19:25:00Z"),
            (54.10000, 7.91550, 80, "2026-07-01T19:33:00Z"),
            (54.18528, 7.91583, 0,  "2026-07-01T19:38:30Z"),
        ]
        for lat, lon, gs, ts in pos:
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (997,'FRS102',?,?,1000,?,0,?)",
                (lat, lon, gs, ts),
            )
        conn.commit()
        f1 = dict(self._flight("FRS102", "EDWG", "EDXH",
                               "2026-07-01T19:06:26Z", "2026-07-01T19:20:20Z", 13), cid=997)
        f2 = dict(self._flight("FRS102", "EDWG", "EDXH",
                               "2026-07-01T19:22:27Z", "2026-07-01T19:38:40Z", 16), cid=997)
        result = merge_fragmented_flights([f1, f2], conn=conn)
        conn.close()
        assert len(result) == 2  # Rückflug und nächster Hinflug bleiben getrennt

    def test_pure_ground_segment_still_merges(self):
        """Gegentest: ein Segment, das NIE geflogen ist (Gate-Reconnect vor dem Neu-Filen,
        alle Positionen ≤ Taxi-Tempo), merged weiterhin mit dem folgenden Flug."""
        conn = _make_conn()
        ensure_pilot(conn, 996, "Tester")
        pos = [
            # Segment A: steht am GAT in EDWG (nie geflogen)
            (53.78278, 7.91389, 0, "2026-07-01T08:00:30Z"),
            (53.78278, 7.91389, 0, "2026-07-01T08:02:00Z"),
            # Segment B: Flug EDWG→EDXH
            (53.78278, 7.91389, 8, "2026-07-01T08:05:30Z"),
            (54.18528, 7.91583, 0, "2026-07-01T08:30:00Z"),
        ]
        for lat, lon, gs, ts in pos:
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (996,'FRS5',?,?,10,?,0,?)",
                (lat, lon, gs, ts),
            )
        conn.commit()
        f1 = dict(self._flight("FRS5", "", "", "2026-07-01T08:00:00Z", "2026-07-01T08:02:30Z", 2), cid=996)
        f2 = dict(self._flight("FRS5", "EDWG", "EDXH", "2026-07-01T08:05:00Z", "2026-07-01T08:30:10Z", 25), cid=996)
        result = merge_fragmented_flights([f1, f2], conn=conn)
        conn.close()
        assert len(result) == 1  # Gate-Reconnect bleibt EIN Flug

    def test_ralf_full_day_yields_three_flights(self):
        """Integration (Live-Test 2026-07-01, Ralf cid 1470798): 282 (Hinflug), 286 (realer
        Rückflug mit stale FP), 287 (nächster Hinflug) → canonicalize_flights liefert DREI
        eigenständige Flüge."""
        conn = _make_conn()
        ensure_pilot(conn, 1470798, "Ralf")
        flights = [
            (282, "2026-07-01T18:28:32Z", "2026-07-01T18:50:24Z", 21),
            (286, "2026-07-01T19:06:26Z", "2026-07-01T19:20:20Z", 13),
            (287, "2026-07-01T19:22:27Z", "2026-07-01T19:38:40Z", 16),
        ]
        for fid, lo, lf, dur in flights:
            conn.execute(
                "INSERT INTO flights (id,cid,callsign,departure,arrival,logon_time,logoff_time,"
                "duration_min,distance_nm) VALUES (?,1470798,'FRS102','EDWG','EDXH',?,?,?,24)",
                (fid, lo, lf, dur),
            )
        pos = [
            # 282: EDWG → EDXH, Landung + Disconnect in EDXH
            (53.78278, 7.91389, 0,  "2026-07-01T18:29:00Z"),
            (53.95000, 7.91400, 85, "2026-07-01T18:38:00Z"),
            (54.18528, 7.91583, 0,  "2026-07-01T18:50:20Z"),
            # 286: realer Rückflug EDXH → EDWG
            (54.18528, 7.91583, 0,  "2026-07-01T19:06:40Z"),
            (54.10000, 7.91500, 75, "2026-07-01T19:09:00Z"),
            (53.78278, 7.91389, 0,  "2026-07-01T19:20:15Z"),
            # 287: nächster Hinflug EDWG → EDXH
            (53.78278, 7.91389, 0,  "2026-07-01T19:22:40Z"),
            (54.00000, 7.91500, 80, "2026-07-01T19:30:00Z"),
            (54.18528, 7.91583, 0,  "2026-07-01T19:38:30Z"),
        ]
        for lat, lon, gs, ts in pos:
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (1470798,'FRS102',?,?,1000,?,0,?)",
                (lat, lon, gs, ts),
            )
        conn.commit()
        result = canonicalize_flights(conn, cids=[1470798], include_statsim=False)
        conn.close()
        assert len(result) == 3  # Hinflug, Rückflug, Hinflug — nichts verschmolzen

    def test_no_merge_teleport_exceeds_budget(self):
        """Gleiche Route, kleine Lücke, aber Positionen ~1000 km auseinander → Distanz-Budget
        gesprengt → nicht mergen (mit conn/Positionsdaten)."""
        conn = _make_conn()
        ensure_pilot(conn, 999, "Tester")
        conn.execute(
            "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,groundspeed,heading,ts) "
            "VALUES (999,'FRS9',50.0,11.0,5000,200,90,'2026-06-06T08:05:00Z')"
        )
        conn.execute(
            "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,groundspeed,heading,ts) "
            "VALUES (999,'FRS9',60.0,11.0,5000,200,90,'2026-06-06T08:10:00Z')"
        )
        conn.commit()
        f1 = dict(self._flight("FRS9", "EDDN", "EDPH", "2026-06-06T08:00:00Z", "2026-06-06T08:06:00Z", 6), cid=999)
        f2 = dict(self._flight("FRS9", "EDDN", "EDPH", "2026-06-06T08:08:00Z", "2026-06-06T08:10:00Z", 2), cid=999)
        result = merge_fragmented_flights([f1, f2], conn=conn)
        conn.close()
        assert len(result) == 2


# ---------------------------------------------------------------------------
# consolidate_flights
# ---------------------------------------------------------------------------

class TestConsolidateFlights:
    def test_exact_duplicates_superseded(self):
        """Drei identische (cid+logon_time) Flüge → einer aktiv, zwei superseded."""
        conn = _make_conn()
        conn.execute("DROP INDEX IF EXISTS idx_flights_session")  # Dubletten erst möglich machen
        ensure_pilot(conn, 1, "P")
        for _ in range(3):
            conn.execute(
                "INSERT INTO flights (cid,callsign,departure,arrival,logon_time,logoff_time,"
                "duration_min,distance_nm) VALUES "
                "(1,'FRS1','EDDN','EDPH','2026-06-06T08:00:00Z','2026-06-06T09:00:00Z',60,100)"
            )
        conn.commit()
        marked = consolidate_flights(conn)
        active = conn.execute(
            "SELECT COUNT(*) FROM flights WHERE superseded_by IS NULL"
        ).fetchone()[0]
        conn.close()
        assert marked == 2
        assert active == 1

    def test_zombie_logoff_shrunk_to_last_position(self):
        """Aufgeblähter Logoff wird auf die letzte Position gekürzt."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "P")
        conn.execute(
            "INSERT INTO flights (id,cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm) VALUES "
            "(1,1,'FRS1','EDDN','EDPH','2026-06-06T08:00:00Z','2026-06-06T11:20:00Z',200,100)"
        )
        for ts in ("2026-06-06T08:05:00Z", "2026-06-06T08:40:00Z"):
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (1,'FRS1',50.0,11.0,5000,200,90,?)",
                (ts,),
            )
        conn.commit()
        consolidate_flights(conn)
        row = conn.execute("SELECT duration_min FROM flights WHERE id=1").fetchone()
        conn.close()
        assert row["duration_min"] == 40  # 08:00 → 08:40

    def test_multiple_open_keeps_latest_closes_older(self):
        """Mehrere offene Flüge je cid (verschiedene Verbindungen) → jüngster bleibt offen,
        ältere werden gedeckelt geschlossen (nicht superseded). Read-time-Merge fügt zusammen."""
        conn = _make_conn()
        conn.execute("DROP INDEX IF EXISTS idx_flights_session")
        ensure_pilot(conn, 1, "P")
        # Alte Session (08:00) + Reconnect (10:00), beide offen.
        conn.execute(
            "INSERT INTO flights (id,cid,callsign,departure,arrival,logon_time,logoff_time) "
            "VALUES (1,1,'FRS1','EDDH','EDDM','2026-06-06T08:00:00Z',NULL)"
        )
        conn.execute(
            "INSERT INTO flights (id,cid,callsign,departure,arrival,logon_time,logoff_time) "
            "VALUES (2,1,'FRS1','EDDH','EDDM','2026-06-06T10:00:00Z',NULL)"
        )
        # Positionen der alten Session bis 08:40 (danach disconnect-Lücke bis Reconnect 10:00)
        for ts in ("2026-06-06T08:05:00Z", "2026-06-06T08:40:00Z"):
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (1,'FRS1',50.0,11.0,5000,200,90,?)",
                (ts,),
            )
        conn.commit()
        consolidate_flights(conn)
        open_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM flights WHERE logoff_time IS NULL AND superseded_by IS NULL"
        ).fetchall()]
        old = conn.execute("SELECT logoff_time, superseded_by FROM flights WHERE id=1").fetchone()
        conn.close()
        assert open_ids == [2]                       # jüngster bleibt offen
        assert old["logoff_time"] == "2026-06-06T08:40:00Z"  # ältere gedeckelt geschlossen
        assert old["superseded_by"] is None          # nicht superseded

    def test_keeper_prefers_non_ghost(self):
        """Bei gleicher logon_time wird der echte Flug behalten, nicht der 0-Min-Ghost
        (Regression FRS123/09.06.)."""
        conn = _make_conn()
        conn.execute("DROP INDEX IF EXISTS idx_flights_session")
        ensure_pilot(conn, 1, "P")
        # Ghost zuerst (niedrigere id), dann echter Flug — gleiche logon_time.
        conn.execute(
            "INSERT INTO flights (cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm) VALUES "
            "(1,'FRS1','','','2026-06-06T06:00:00Z','2026-06-06T06:00:00Z',0,0)"
        )
        conn.execute(
            "INSERT INTO flights (cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm) VALUES "
            "(1,'FRS1','LDPV','LIPQ','2026-06-06T06:00:00Z','2026-06-06T07:30:00Z',90,200)"
        )
        conn.commit()
        consolidate_flights(conn)
        active = conn.execute(
            "SELECT departure, arrival FROM flights WHERE superseded_by IS NULL"
        ).fetchall()
        conn.close()
        assert len(active) == 1
        assert (active[0]["departure"], active[0]["arrival"]) == ("LDPV", "LIPQ")

    def test_zombie_shrink_recomputes_block_min(self):
        """Schritt C: wird der Logoff gekürzt, muss block_min mit dem NEUEN Fenster
        neu berechnet werden — sonst bleibt eine Blockzeit aus dem aufgeblähten Fenster
        stehen (Regression A2, Live-Test 2026-07-01)."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "P")
        # Aufgeblähter Flug: logoff 11:20 (dur 200), stale block über das große Fenster.
        conn.execute(
            "INSERT INTO flights (id,cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm,block_min) VALUES "
            "(1,1,'FRS1','EDDN','EDPH','2026-06-06T08:00:00Z','2026-06-06T11:20:00Z',200,100,190)"
        )
        # Bewegung nur 08:05–08:40 → korrektes Fenster endet 08:40, Block = 35.
        for ts in ("2026-06-06T08:05:00Z", "2026-06-06T08:40:00Z"):
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (1,'FRS1',50.0,11.0,5000,200,90,?)",
                (ts,),
            )
        conn.commit()
        consolidate_flights(conn)
        row = conn.execute("SELECT duration_min, block_min FROM flights WHERE id=1").fetchone()
        conn.close()
        assert row["duration_min"] == 40
        assert row["block_min"] == 35  # 08:05 → 08:40, NICHT die alten 190

    def test_statsim_correction_recomputes_block_min(self):
        """Schritt D: die StatSim-Korrektur setzte logoff/duration/distance neu, ließ aber
        block_min aus dem aufgeblähten Fenster stehen (Reiner id 277: duration 28,
        block 92 — unmöglich). block_min muss mit dem korrigierten Fenster neu berechnet werden."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "P")
        # Doppelt geschlossene Session: logoff 18:43 (99 min), block 92 über das große Fenster.
        conn.execute(
            "INSERT INTO flights (id,cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm,block_min) VALUES "
            "(1,1,'FRS61','EDWG','EDXH','2026-07-01T17:04:16Z','2026-07-01T18:43:44Z',99,100,92)"
        )
        # Bewegung des ECHTEN Fluges 17:05–17:30, danach (verwaister Folgeflug) 18:15–18:40.
        for ts in ("2026-07-01T17:05:00Z", "2026-07-01T17:30:00Z",
                   "2026-07-01T18:15:00Z", "2026-07-01T18:40:00Z"):
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (1,'FRS61',53.8,7.9,1000,80,90,?)",
                (ts,),
            )
        # StatSim kennt die echte Dauer der Session-Verbindung: 28 min.
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES "
            "(1,1,'FRS61','EDWG','EDXH','BN2P','2026-07-01T17:04:20Z',"
            "'2026-07-01T17:32:20Z',28,'2026-07-01T19:00:00Z')"
        )
        conn.commit()
        consolidate_flights(conn)
        row = conn.execute(
            "SELECT duration_min, block_min FROM flights WHERE id=1"
        ).fetchone()
        conn.close()
        assert row["duration_min"] == 28
        # Fenster [17:04:16, 17:32:16] → Bewegung 17:05–17:30 → 25 min, NICHT 92.
        assert row["block_min"] == 25

    def test_statsim_backstop_spares_legit_multileg_session(self):
        """Schritt D darf eine legitime Multi-Leg-Session (eine Verbindung, mehrere Flüge)
        nicht auf die Dauer des ERSTEN Beins schrumpfen: StatSim legt pro Flug eine Zeile
        mit der SESSION-Anmeldung als logon_time an (duration = arrived − loggedOn) — bei
        drei Beinen matchen also mehrere Zeilen dieselbe Minute. Maßgeblich ist die LÄNGSTE
        (späteste Landung), nicht ein LIMIT-1-Zufallstreffer."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "P")
        # Legitime Session: 17:04–18:43 (99 min), Blockzeit konsistent.
        conn.execute(
            "INSERT INTO flights (id,cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm,block_min) VALUES "
            "(1,1,'FRS61','EDWG','EDXH','2026-07-01T17:04:16Z','2026-07-01T18:43:44Z',99,80,60)"
        )
        # StatSim: zwei Flüge derselben Session — beide mit Session-logon 17:04.
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES "
            "(1,1,'FRS61','EDWG','EDXH','BN2P','2026-07-01T17:04:20Z',"
            "'2026-07-01T17:32:20Z',28,'2026-07-01T20:00:00Z')"
        )
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES "
            "(2,1,'FRS61','EDWG','EDXH','BN2P','2026-07-01T17:04:20Z',"
            "'2026-07-01T18:36:00Z',92,'2026-07-01T20:00:00Z')"
        )
        conn.commit()
        consolidate_flights(conn)
        row = conn.execute("SELECT duration_min FROM flights WHERE id=1").fetchone()
        conn.close()
        assert row["duration_min"] == 99  # 99 ≤ 2×92+10 → keine Korrektur

    def test_impossible_block_gt_duration_self_heals(self):
        """Selbstheilung: block_min > duration_min ist physikalisch unmöglich (Blockzeit liegt
        in [logon, logoff]) → consolidate rechnet block mit dem gespeicherten Fenster neu.
        Exakt der Zustand von Flug id 277 nach dem Live-Test (duration 28, block 92)."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "P")
        conn.execute(
            "INSERT INTO flights (id,cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm,block_min) VALUES "
            "(1,1,'FRS61','EDWG','EDXH','2026-07-01T17:04:16Z','2026-07-01T17:32:16Z',28,34,92)"
        )
        for ts in ("2026-07-01T17:05:00Z", "2026-07-01T17:30:00Z",
                   "2026-07-01T18:15:00Z", "2026-07-01T18:40:00Z"):
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (1,'FRS61',53.8,7.9,1000,80,90,?)",
                (ts,),
            )
        conn.commit()
        consolidate_flights(conn)
        row = conn.execute("SELECT duration_min, block_min FROM flights WHERE id=1").fetchone()
        conn.close()
        assert row["duration_min"] == 28   # unangetastet — Fenster war konsistent
        assert row["block_min"] == 25       # 17:05 → 17:30 im gespeicherten Fenster

    def test_consolidate_rerunnable(self):
        """Zweiter consolidate-Lauf ist idempotent (Reset + Neuberechnung)."""
        conn = _make_conn()
        conn.execute("DROP INDEX IF EXISTS idx_flights_session")
        ensure_pilot(conn, 1, "P")
        for _ in range(2):
            conn.execute(
                "INSERT INTO flights (cid,callsign,departure,arrival,logon_time,logoff_time,"
                "duration_min,distance_nm) VALUES "
                "(1,'FRS1','EDDN','EDPH','2026-06-06T08:00:00Z','2026-06-06T09:00:00Z',60,100)"
            )
        conn.commit()
        consolidate_flights(conn)
        n1 = conn.execute("SELECT COUNT(*) FROM flights WHERE superseded_by IS NOT NULL").fetchone()[0]
        consolidate_flights(conn)
        n2 = conn.execute("SELECT COUNT(*) FROM flights WHERE superseded_by IS NOT NULL").fetchone()[0]
        conn.close()
        assert n1 == 1 and n2 == 1


# ---------------------------------------------------------------------------
# last_known_aircraft — Typ-Fallback ohne Flugplan
# ---------------------------------------------------------------------------

class TestLastKnownAircraft:
    def test_returns_most_recent_type(self):
        from app.database import last_known_aircraft
        conn = _make_conn()
        ensure_pilot(conn, 5, "P")
        conn.execute(
            "INSERT INTO flights (cid,callsign,aircraft_short,aircraft_icao,logon_time,"
            "logoff_time) VALUES (5,'FRS5','C172','C172','2026-06-01T10:00:00Z','2026-06-01T11:00:00Z')"
        )
        conn.execute(
            "INSERT INTO flights (cid,callsign,aircraft_short,aircraft_icao,logon_time,"
            "logoff_time) VALUES (5,'FRS5','PZ04','PZ04','2026-06-20T10:00:00Z','2026-06-20T11:00:00Z')"
        )
        conn.execute(  # neuester Flug OHNE Typ (ohne Plan) zählt nicht
            "INSERT INTO flights (cid,callsign,aircraft_short,logon_time,logoff_time) "
            "VALUES (5,'FRS5','','2026-06-25T10:00:00Z','2026-06-25T11:00:00Z')"
        )
        conn.commit()
        assert last_known_aircraft(conn, 5) == ("PZ04", "PZ04")
        conn.close()

    def test_unknown_pilot_returns_empty(self):
        from app.database import last_known_aircraft
        conn = _make_conn()
        assert last_known_aircraft(conn, 999999) == ("", "")
        conn.close()


# ---------------------------------------------------------------------------
# Ghost-Filter: belegte Steh-Sessions sind keine Flüge
# ---------------------------------------------------------------------------

class TestGhostFilter:
    def test_standing_session_with_track_is_filtered(self):
        """Live-Test 2026-07-01 (Reiner, „Flug" 284): 14 min verbunden, Track vorhanden,
        aber NULL Bewegung (block 0, 0 nm) → kein Flug, egal wie lange die Session dauerte.
        Die alte Dauer-Ausnahme (> 5 min) ließ solche Steh-Sessions als Flüge durch."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "P")
        conn.execute(
            "INSERT INTO flights (cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm,block_min) VALUES "
            "(1,'FRS61','EDWG','EDXH','2026-07-01T18:43:47Z','2026-07-01T18:57:54Z',14,0,0)"
        )
        for ts in ("2026-07-01T18:44:00Z", "2026-07-01T18:50:00Z", "2026-07-01T18:57:54Z"):
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (1,'FRS61',54.185,7.916,10,0,0,?)",
                (ts,),
            )
        conn.commit()
        result = canonicalize_flights(conn, cids=[1], include_statsim=False)
        conn.close()
        assert result == []  # belegter Stillstand → kein Flug

    def test_old_flight_without_track_is_kept(self):
        """Altflug aus der Vor-GPS-Ära: Dauer > 5 min, aber weder Positionen noch Distanz/
        Block-Daten → bleibt erhalten (kein Beleg für Stillstand — im Zweifel echter Flug)."""
        conn = _make_conn()
        ensure_pilot(conn, 2, "Alt")
        conn.execute(
            "INSERT INTO flights (cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm,block_min) VALUES "
            "(2,'FRS9','EDDH','EDDF','2025-08-01T10:00:00Z','2025-08-01T10:45:00Z',45,0,NULL)"
        )
        conn.commit()
        result = canonicalize_flights(conn, cids=[2], include_statsim=False)
        conn.close()
        assert len(result) == 1  # Altdaten ohne Track bleiben

    def test_moved_flight_with_zero_distance_rounding_is_kept(self):
        """Session mit Track UND Bewegung (block > 0), aber gerundeter 0-nm-Distanz
        (z. B. Platzrunde/kurzes Rollen und zurück) → bleibt erhalten."""
        conn = _make_conn()
        ensure_pilot(conn, 3, "P")
        conn.execute(
            "INSERT INTO flights (cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm,block_min) VALUES "
            "(3,'FRS7','EDWG','EDWG','2026-07-01T10:00:00Z','2026-07-01T10:20:00Z',20,0,12)"
        )
        for ts, gs in (("2026-07-01T10:02:00Z", 15), ("2026-07-01T10:14:00Z", 20)):
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (3,'FRS7',53.783,7.914,10,?,0,?)",
                (gs, ts),
            )
        conn.commit()
        result = canonicalize_flights(conn, cids=[3], include_statsim=False)
        conn.close()
        assert len(result) == 1


# ---------------------------------------------------------------------------
# reconstruct_orphaned_flights — verwaiste Tracks wieder mit flights-Zeile versehen
# ---------------------------------------------------------------------------

class TestReconstructOrphanedFlights:
    """Reparatur des A1-Schadens (Live-Test 2026-07-01, Reiner cid 1031301): StatSim kennt
    einen Flug, position_history besitzt den bewegten GPS-Track, aber es existiert kein
    flights-Eintrag, der den Track „besitzt" → Eintrag aus den echten Belegen rekonstruieren."""

    CID = 1031301

    def _seed_reiner(self, conn):
        ensure_pilot(conn, self.CID, "Reiner")
        # Hinflug (nach StatSim-Korrektur): 17:04–17:32, geschlossen.
        conn.execute(
            "INSERT INTO flights (id,cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm,block_min) VALUES "
            "(277,?, 'FRS61','EDWG','EDXH','2026-07-01T17:04:16Z','2026-07-01T17:32:16Z',28,34,26)",
            (self.CID,),
        )
        # Steh-Session nach echtem Reconnect: 18:43:47–18:57:54, 0 nm.
        conn.execute(
            "INSERT INTO flights (id,cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm,block_min) VALUES "
            "(284,?, 'FRS61','EDWG','EDXH','2026-07-01T18:43:47Z','2026-07-01T18:57:54Z',14,0,0)",
            (self.CID,),
        )
        # StatSim in ECHTER API-Form (app/statsim.py): loggedOn = SESSION-Anmeldung — bei
        # mehreren Flügen einer Verbindung für ALLE gleich (17:04!); arrived = Landezeit;
        # duration = arrived − loggedOn (deshalb "92" beim zweiten Flug). Der Flugbeginn
        # steht NIRGENDS — Anker für die Rekonstruktion muss die Landezeit sein.
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES "
            "(90001,?,'FRS61','EDWG','EDXH','BN2P','2026-07-01T17:04:20Z',"
            "'2026-07-01T17:32:20Z',28,'2026-07-01T20:00:00Z')",
            (self.CID,),
        )
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES "
            "(90002,?,'FRS61','EDWG','EDXH','BN2P','2026-07-01T17:04:20Z',"
            "'2026-07-01T18:36:00Z',92,'2026-07-01T20:00:00Z')",
            (self.CID,),
        )
        # Verwaister Track: Bewegung zwischen den Sessions (Rückweg, Stand, zweiter Flug, Taxi).
        samples = [
            # Rückweg EDXH→EDWG (gehört NICHT zum zu rekonstruierenden Flug)
            ("2026-07-01T17:40:00Z", 54.10, 7.915, 80),
            ("2026-07-01T18:04:00Z", 53.79, 7.914, 60),
            # Stand in EDWG (belegt, > 10 min)
            ("2026-07-01T18:05:00Z", 53.78278, 7.91389, 0),
            ("2026-07-01T18:16:00Z", 53.78278, 7.91389, 0),
            # Zweiter Flug EDWG→EDXH: Taxi + Start 18:17:30, Reiseflug, Landung 18:36
            ("2026-07-01T18:17:30Z", 53.78278, 7.91389, 8),
            ("2026-07-01T18:20:00Z", 53.82, 7.914, 86),
            ("2026-07-01T18:30:00Z", 54.05, 7.915, 84),
            ("2026-07-01T18:36:00Z", 54.18, 7.9158, 40),
            # Taxi-in bis zum Disconnect ~18:43:44
            ("2026-07-01T18:40:00Z", 54.185, 7.9158, 10),
            ("2026-07-01T18:43:44Z", 54.18528, 7.91583, 3),
            # Neue Session (284): stationär
            ("2026-07-01T18:44:00Z", 54.18528, 7.91583, 0),
            ("2026-07-01T18:57:54Z", 54.18528, 7.91583, 0),
        ]
        for ts, lat, lon, gs in samples:
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (?,'FRS61',?,?,800,?,0,?)",
                (self.CID, lat, lon, gs, ts),
            )
        conn.commit()

    def test_reconstructs_missing_flight_from_track(self):
        from app.database import reconstruct_orphaned_flights
        conn = _make_conn()
        self._seed_reiner(conn)
        created = reconstruct_orphaned_flights(conn)
        rows = conn.execute(
            "SELECT * FROM flights WHERE cid=? AND superseded_by IS NULL ORDER BY logon_time",
            (self.CID,),
        ).fetchall()
        assert created == 1
        assert len(rows) == 3
        rec = rows[1]  # zwischen Hinflug und Steh-Session
        assert (rec["departure"], rec["arrival"]) == ("EDWG", "EDXH")
        # Fenster beginnt NACH der belegten Standphase (Rückweg gehört nicht dazu) und
        # kollidiert nicht mit 277/284.
        assert "2026-07-01T18:16:00Z" <= rec["logon_time"] <= "2026-07-01T18:18:00Z"
        assert "2026-07-01T18:36:00Z" <= rec["logoff_time"] < "2026-07-01T18:43:47Z"
        assert rec["distance_nm"] > 20          # echter GPS-Track EDWG→EDXH (~24 nm)
        assert 15 <= rec["block_min"] <= 30      # Bewegungszeit des Flugs, ohne Standphase
        conn.close()

    def test_idempotent_second_run_creates_nothing(self):
        from app.database import reconstruct_orphaned_flights
        conn = _make_conn()
        self._seed_reiner(conn)
        assert reconstruct_orphaned_flights(conn) == 1
        assert reconstruct_orphaned_flights(conn) == 0  # jetzt gedeckt → No-Op
        conn.close()

    def test_canonicalize_lists_reconstructed_flight_separately(self):
        """Nach der Reparatur: drei eigenständige Einträge — kein Merge mit dem Hinflug (Lücke
        > Fenster) und kein Merge mit der Steh-Session (Hinflug war am Ziel gelandet)."""
        from app.database import reconstruct_orphaned_flights
        conn = _make_conn()
        self._seed_reiner(conn)
        reconstruct_orphaned_flights(conn)
        flights = canonicalize_flights(conn, cids=[self.CID], include_statsim=True)
        fs = [f for f in flights if f["source"] == "friesenspy"]
        # Entscheidend: der rekonstruierte Flug ist eigenständig EDWG→EDXH; die Steh-
        # Session 284 fällt als belegter Stillstand aus der Flugliste.
        recs = [f for f in fs if f["logon_time"].startswith("2026-07-01T18:1")
                or f["logon_time"].startswith("2026-07-01T18:0")]
        assert len(recs) == 1
        assert (recs[0]["departure"], recs[0]["arrival"]) == ("EDWG", "EDXH")
        # Die Steh-Session 284 (14 min, 0 nm, Track belegt Stillstand) ist KEIN Flug mehr.
        assert not any(f["logon_time"].startswith("2026-07-01T18:43") for f in fs)
        # Der StatSim-Eintrag 18:18 ist jetzt gedeckt → taucht nicht doppelt auf.
        st_18 = [f for f in flights if f["source"] == "statsim"
                 and f["logon_time"].startswith("2026-07-01T18:18")]
        assert st_18 == []
        conn.close()

    def test_init_db_reconstruction_works_on_raw_connection(self, tmp_path):
        """Regression Prod-Crash 2026-07-01 (v7.3.1): init_db nutzt eine rohe sqlite3-Connection
        OHNE row_factory — die Rekonstruktion darf sich nicht auf benannten Zeilenzugriff
        verlassen, sonst crasht der App-Start (TypeError: tuple indices), sobald statsim_cache
        Daten enthält."""
        db = str(tmp_path / "t.db")
        init_db(db)
        conn = get_connection(db)
        try:
            self._seed_reiner(conn)
        finally:
            conn.close()
        init_db(db)  # darf nicht crashen und muss den Flug rekonstruieren
        conn = get_connection(db)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM flights WHERE cid=? AND superseded_by IS NULL",
                (self.CID,),
            ).fetchone()[0]
        finally:
            conn.close()
        assert n == 3

    def test_cids_filter_limits_scope(self):
        """Mit cids=[…] rekonstruiert die Funktion nur für diese Piloten — Basis für den
        Aufruf direkt nach einem StatSim-Refresh (kein Container-Neustart mehr nötig)."""
        from app.database import reconstruct_orphaned_flights
        conn = _make_conn()
        self._seed_reiner(conn)
        assert reconstruct_orphaned_flights(conn, cids=[999999]) == 0  # fremde cid → No-Op
        assert reconstruct_orphaned_flights(conn, cids=[self.CID]) == 1
        conn.close()

    def test_no_reconstruction_without_movement(self):
        """StatSim-Flug ohne bewegten Track (z. B. Historie vor FriesenSpy) → kein Eintrag."""
        from app.database import reconstruct_orphaned_flights
        conn = _make_conn()
        ensure_pilot(conn, 42, "Alt")
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES "
            "(80001,42,'FRS9','EDDH','EDDF','C172','2025-11-01T10:00:00Z',"
            "'2025-11-01T11:00:00Z',60,'2026-07-01T20:00:00Z')"
        )
        conn.commit()
        assert reconstruct_orphaned_flights(conn) == 0
        conn.close()

    def test_no_reconstruction_for_open_session(self):
        """Läuft gerade eine offene Session, die den StatSim-Flug enthält → kein Duplikat."""
        from app.database import reconstruct_orphaned_flights
        conn = _make_conn()
        ensure_pilot(conn, 43, "Live")
        conn.execute(
            "INSERT INTO flights (cid,callsign,departure,arrival,logon_time,logoff_time) "
            "VALUES (43,'FRS8','EDWG','EDXH','2026-07-01T18:00:00Z',NULL)"
        )
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES "
            "(80002,43,'FRS8','EDWG','EDXH','BN2P','2026-07-01T18:18:00Z',"
            "'2026-07-01T18:36:00Z',18,'2026-07-01T20:00:00Z')"
        )
        for ts, gs in (("2026-07-01T18:20:00Z", 80), ("2026-07-01T18:35:00Z", 70)):
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (43,'FRS8',53.9,7.914,900,?,0,?)",
                (gs, ts),
            )
        conn.commit()
        assert reconstruct_orphaned_flights(conn) == 0
        conn.close()


# ---------------------------------------------------------------------------
# Block-Zeit (Bewegungszeit)
# ---------------------------------------------------------------------------

class TestBlockMinutes:
    def test_close_flight_sets_block_min(self):
        """block_min = Spanne erster bis letzter Bewegung (groundspeed > Schwelle)."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "P")
        fid = open_flight(conn, 1, "FRS1", "B738", "EDDH", "EDDM", "2026-06-06T08:00:00Z")
        # 08:00 parkt (GS0), 08:05 rollt los, 08:45 letzte Bewegung, 08:55 wieder GS0
        for ts, gs in [
            ("2026-06-06T08:00:00Z", 0), ("2026-06-06T08:05:00Z", 150),
            ("2026-06-06T08:45:00Z", 150), ("2026-06-06T08:55:00Z", 0),
        ]:
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (1,'FRS1',50.0,11.0,1000,?,90,?)",
                (gs, ts),
            )
        conn.commit()
        close_flight(conn, fid, "2026-06-06T09:00:00Z")
        row = conn.execute("SELECT duration_min, block_min FROM flights WHERE id=?", (fid,)).fetchone()
        conn.close()
        assert row["duration_min"] == 60   # 08:00 → 09:00 (Online)
        assert row["block_min"] == 40       # 08:05 → 08:45 (Bewegung)

    def test_close_flight_block_zero_without_movement(self):
        """Reiner Stand (GS immer 0) → block_min = 0."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "P")
        fid = open_flight(conn, 1, "FRS1", "B738", "EDDH", "EDDM", "2026-06-06T08:00:00Z")
        for ts in ("2026-06-06T08:10:00Z", "2026-06-06T08:30:00Z"):
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (1,'FRS1',50.0,11.0,0,0,0,?)",
                (ts,),
            )
        conn.commit()
        close_flight(conn, fid, "2026-06-06T09:00:00Z")
        row = conn.execute("SELECT block_min FROM flights WHERE id=?", (fid,)).fetchone()
        conn.close()
        assert row["block_min"] == 0

    def test_block_excludes_long_stand_within_session(self):
        """A4: Zwischenlandung OHNE Disconnect — belegte Standphasen (zusammenhängend
        groundspeed ≤ Schwelle, ab Mindest-Standdauer) zählen NICHT als Blockzeit.
        Block = Summe der bewegten Abschnitte, nicht „erste bis letzte Bewegung"."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "P")
        fid = open_flight(conn, 1, "FRS1", "BN2P", "EDWG", "EDXH", "2026-06-06T07:55:00Z")
        samples = [
            # Leg 1: Taxi + Flug 08:00–08:30
            ("2026-06-06T08:00:00Z", 5), ("2026-06-06T08:05:00Z", 80),
            ("2026-06-06T08:25:00Z", 60), ("2026-06-06T08:30:00Z", 10),
            # Zwischenlandung: 43 min belegter Stillstand (Motor aus, Pause)
            ("2026-06-06T08:31:00Z", 0), ("2026-06-06T08:45:00Z", 0),
            ("2026-06-06T09:14:00Z", 0),
            # Leg 2: Taxi + Flug 09:15–09:30, danach geparkt
            ("2026-06-06T09:15:00Z", 8), ("2026-06-06T09:30:00Z", 90),
            ("2026-06-06T09:45:00Z", 0),
        ]
        for ts, gs in samples:
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (1,'FRS1',53.8,7.9,500,?,90,?)",
                (gs, ts),
            )
        conn.commit()
        close_flight(conn, fid, "2026-06-06T09:50:00Z")
        row = conn.execute("SELECT block_min FROM flights WHERE id=?", (fid,)).fetchone()
        conn.close()
        # Bewegt: 08:00–08:30 (30) + Ränder der Standphase (08:30–08:31, 09:14–09:15 = 2)
        # + 09:15–09:30 (15) = 47 min. NICHT 90 (erste bis letzte Bewegung).
        assert row["block_min"] == 47

    def test_block_keeps_short_stop(self):
        """Kurzer Halt (unter der Mindest-Standdauer, z. B. Rollhalt) bleibt gate-to-gate
        in der Blockzeit enthalten."""
        conn = _make_conn()
        ensure_pilot(conn, 1, "P")
        fid = open_flight(conn, 1, "FRS1", "BN2P", "EDWG", "EDXH", "2026-06-06T07:55:00Z")
        samples = [
            ("2026-06-06T08:00:00Z", 10), ("2026-06-06T08:20:00Z", 15),
            # 5 min Halt (Rollhalt) — unter der Schwelle → zählt mit
            ("2026-06-06T08:21:00Z", 0), ("2026-06-06T08:26:00Z", 0),
            ("2026-06-06T08:27:00Z", 60), ("2026-06-06T08:40:00Z", 70),
        ]
        for ts, gs in samples:
            conn.execute(
                "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
                "groundspeed,heading,ts) VALUES (1,'FRS1',53.8,7.9,500,?,90,?)",
                (gs, ts),
            )
        conn.commit()
        close_flight(conn, fid, "2026-06-06T08:45:00Z")
        row = conn.execute("SELECT block_min FROM flights WHERE id=?", (fid,)).fetchone()
        conn.close()
        assert row["block_min"] == 40  # 08:00 → 08:40 durchgehend gate-to-gate

    def test_merge_sums_block_min(self):
        """Gemergte Segmente summieren block_min."""
        f1 = {"callsign": "FRS1", "departure": "EDDN", "arrival": "EDPH",
              "logon_time": "2026-06-06T08:00:00Z", "logoff_time": "2026-06-06T08:30:00Z",
              "duration_min": 30, "block_min": 25}
        f2 = {"callsign": "FRS1", "departure": "EDDN", "arrival": "EDPH",
              "logon_time": "2026-06-06T08:33:00Z", "logoff_time": "2026-06-06T09:00:00Z",
              "duration_min": 27, "block_min": 20}
        res = merge_fragmented_flights([f1, f2])
        assert len(res) == 1
        assert res[0]["block_min"] == 45


# ---------------------------------------------------------------------------
# ts_consent + TS-Push-Subscriptions
# ---------------------------------------------------------------------------

class TestTsConsent:
    def test_get_missing_returns_none(self):
        from app.database import get_ts_consent
        conn = _make_conn()
        assert get_ts_consent(conn, "FRS1") is None

    def test_upsert_and_get(self):
        from app.database import get_ts_consent, upsert_ts_consent
        conn = _make_conn()
        upsert_ts_consent(conn, "FRS1", "allowlist", ["FRS2", "FRS3"])
        conn.commit()
        row = get_ts_consent(conn, "FRS1")
        assert row["frs"] == "FRS1"
        assert row["visibility"] == "allowlist"
        assert row["allowlist"] == ["FRS2", "FRS3"]

    def test_upsert_overwrites(self):
        from app.database import get_ts_consent, upsert_ts_consent
        conn = _make_conn()
        upsert_ts_consent(conn, "FRS1", "everyone", None)
        upsert_ts_consent(conn, "FRS1", "nobody", None)
        conn.commit()
        assert get_ts_consent(conn, "FRS1")["visibility"] == "nobody"


class TestCidForCallsign:
    def test_from_flights(self):
        from app.database import cid_for_callsign, open_flight, ensure_pilot
        conn = _make_conn()
        ensure_pilot(conn, 111, "Tobias")
        open_flight(conn, 111, "FRS49", "C172", "EDDW", "EDDH", _ts_offset(0))
        assert cid_for_callsign(conn, "FRS49") == 111
        assert cid_for_callsign(conn, "frs49") == 111  # case-insensitiv

    def test_unknown_returns_none(self):
        from app.database import cid_for_callsign
        conn = _make_conn()
        assert cid_for_callsign(conn, "FRS999") is None
        assert cid_for_callsign(conn, "") is None

    def test_live_position_preferred(self):
        from app.database import cid_for_callsign, open_flight, upsert_live_position, ensure_pilot
        conn = _make_conn()
        ensure_pilot(conn, 111, "Tobias")
        open_flight(conn, 111, "FRS49", "C172", "EDDW", "EDDH", _ts_offset(-10))
        upsert_live_position(conn, 222, "FRS49", "C172", "EDDW", "EDDH",
                             53.0, 8.0, 1000, 120, 90, _ts_offset(0))
        assert cid_for_callsign(conn, "FRS49") == 222


class TestGetTsPushSubscriptions:
    def _db(self, tmp_path):
        from app.database import init_db, get_connection
        db = str(tmp_path / "t.db"); init_db(db)
        return get_connection(db)

    def test_only_notify_ts(self, tmp_path):
        from app.database import upsert_push_subscription, get_ts_push_subscriptions
        conn = self._db(tmp_path)
        upsert_push_subscription(conn, "e1", "p", "a", notify_ts=True)
        upsert_push_subscription(conn, "e2", "p", "a", notify_ts=False)
        conn.commit()
        assert [s["endpoint"] for s in get_ts_push_subscriptions(conn, 111)] == ["e1"]
        conn.close()

    def test_pilot_filter_membership(self, tmp_path):
        from app.database import upsert_push_subscription, get_ts_push_subscriptions
        conn = self._db(tmp_path)
        upsert_push_subscription(conn, "all", "p", "a", notify_ts=True, pilot_filter=None)
        upsert_push_subscription(conn, "only111", "p", "a", notify_ts=True, pilot_filter=[111])
        upsert_push_subscription(conn, "only999", "p", "a", notify_ts=True, pilot_filter=[999])
        conn.commit()
        eps = {s["endpoint"] for s in get_ts_push_subscriptions(conn, 111)}
        assert eps == {"all", "only111"}
        conn.close()

    def test_unknown_cid_only_all(self, tmp_path):
        from app.database import upsert_push_subscription, get_ts_push_subscriptions
        conn = self._db(tmp_path)
        upsert_push_subscription(conn, "all", "p", "a", notify_ts=True, pilot_filter=None)
        upsert_push_subscription(conn, "only111", "p", "a", notify_ts=True, pilot_filter=[111])
        conn.commit()
        # cid None (reine TS-Leute) → nur pilot_filter NULL
        assert [s["endpoint"] for s in get_ts_push_subscriptions(conn, None)] == ["all"]
        conn.close()

    def test_migrations_idempotent(self, tmp_path):
        from app.database import init_db
        db = str(tmp_path / "t.db")
        init_db(db)
        init_db(db)  # zweiter Lauf darf nicht werfen


class TestUpsertPushSubscriptionCreatedAt:
    """created_at muss beim Re-Abo desselben Endpoints aktualisiert werden."""

    def test_resubscribe_updates_created_at_and_keys(self, tmp_path, monkeypatch):
        from app import database
        from app.database import init_db, get_connection, upsert_push_subscription
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)

        monkeypatch.setattr(database, "_now_utc", lambda: "2026-01-01T00:00:00Z")
        upsert_push_subscription(conn, "ep1", "p", "a")
        conn.commit()
        first = conn.execute(
            "SELECT created_at FROM push_subscriptions WHERE endpoint='ep1'"
        ).fetchone()[0]
        assert first == "2026-01-01T00:00:00Z"

        # Re-Abo desselben Endpoints zu späterem Zeitpunkt, neue Keys
        monkeypatch.setattr(database, "_now_utc", lambda: "2026-02-02T12:00:00Z")
        upsert_push_subscription(conn, "ep1", "p2", "a2")
        conn.commit()

        row = conn.execute(
            "SELECT created_at, p256dh, auth FROM push_subscriptions WHERE endpoint='ep1'"
        ).fetchone()
        assert row["created_at"] == "2026-02-02T12:00:00Z"   # aktualisiert
        assert row["p256dh"] == "p2" and row["auth"] == "a2"  # Keys aktualisiert
        # weiterhin nur eine Zeile (Upsert, kein Duplikat)
        assert conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 1
        conn.close()


# ---------------------------------------------------------------------------
# recompute_gps_legs — GPS-Leg-Schatten-Erfassung (Phase 1)
# ---------------------------------------------------------------------------

class TestGpsLegs:
    """Schatten-Erfassung: recompute_gps_legs schreibt Legs idempotent aus position_history.

    Nutzt echte deutsche Flugplätze (EDDK/EDDW/EDDH) mit ihren realen Koordinaten/Elevationen,
    damit geo.nearest_airport_icao_fast/airport_elevation_ft auflösen. Track: Vollstopp <2 kt am
    Ziel, gehalten > 180 s (Dwell), Abheben via AGL-Anstieg > 500 ft."""

    CID = 4242

    # Reale Koordinaten (aus airportsdata) — weit genug auseinander (~250 km / ~130 km).
    A = (50.8659, 7.14274)    # EDDK, elev 302 ft
    B = (53.0475, 8.78667)    # EDDW, elev 14 ft
    C = (53.6304, 9.98823)    # EDDH, elev 53 ft

    def _pos(self, conn, ts, lat, lon, alt, gs, callsign="FRS10"):
        conn.execute(
            "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,"
            "groundspeed,heading,ts) VALUES (?,?,?,?,?,?,0,?)",
            (self.CID, callsign, lat, lon, alt, gs, ts),
        )

    def _seed_leg_a_to_b(self, conn):
        """Vollständige Etappe EDDK → EDDW (Boden, Steigflug > 500 ft AGL, Landung + Dwell)."""
        self._pos(conn, "2026-07-02T10:00:00Z", *self.A, 302, 0)     # Boden EDDK
        self._pos(conn, "2026-07-02T10:01:00Z", *self.A, 302, 5)     # Boden EDDK
        self._pos(conn, "2026-07-02T10:02:00Z", *self.A, 1200, 80)   # Abheben (AGL 898 > 500)
        self._pos(conn, "2026-07-02T10:20:00Z", 52.0, 8.0, 5000, 120)  # Reiseflug
        self._pos(conn, "2026-07-02T10:38:00Z", 53.0, 8.7, 500, 60)   # Anflug EDDW
        self._pos(conn, "2026-07-02T10:40:00Z", *self.B, 20, 0)       # Touchdown EDDW (AGL 6)
        self._pos(conn, "2026-07-02T10:44:00Z", *self.B, 20, 0)       # 240 s Dwell > 180 → Ankunft

    def test_completed_leg_written_once(self):
        conn = _make_conn()
        ensure_pilot(conn, self.CID, "Tester")
        conn.execute(
            "INSERT INTO flights (cid,callsign,departure,arrival,logon_time,logoff_time,"
            "duration_min,distance_nm,block_min) VALUES "
            "(?,'FRS10','EDDK','EDDW','2026-07-02T09:58:00Z','2026-07-02T10:50:00Z',52,0,0)",
            (self.CID,),
        )
        self._seed_leg_a_to_b(conn)
        conn.commit()

        n = recompute_gps_legs(conn, self.CID)
        assert n == 1
        rows = conn.execute(
            "SELECT dep_icao, arr_icao, takeoff_ts, landing_ts, complete, distance_nm, "
            "duration_min, connection_logon, callsign FROM gps_legs WHERE cid=?",
            (self.CID,),
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        r = rows[0]
        assert r["dep_icao"] == "EDDK"
        assert r["arr_icao"] == "EDDW"
        assert r["complete"] == 1
        assert r["takeoff_ts"] == "2026-07-02T10:02:00Z"
        assert r["landing_ts"] == "2026-07-02T10:40:00Z"
        assert r["distance_nm"] > 0
        assert r["duration_min"] > 0
        assert r["connection_logon"] == "2026-07-02T09:58:00Z"
        assert r["callsign"] == "FRS10"

    def test_idempotent_recompute(self):
        conn = _make_conn()
        ensure_pilot(conn, self.CID, "Tester")
        self._seed_leg_a_to_b(conn)
        conn.commit()

        cols = "dep_icao, arr_icao, takeoff_ts, landing_ts, complete, distance_nm"

        n1 = recompute_gps_legs(conn, self.CID)
        first = conn.execute(
            f"SELECT {cols} FROM gps_legs WHERE cid=? ORDER BY takeoff_ts", (self.CID,)
        ).fetchall()

        n2 = recompute_gps_legs(conn, self.CID)
        second = conn.execute(
            f"SELECT {cols} FROM gps_legs WHERE cid=? ORDER BY takeoff_ts", (self.CID,)
        ).fetchall()
        conn.close()

        assert n1 == n2 == 1
        assert [dict(r) for r in first] == [dict(r) for r in second]

    def test_open_tail_mutates_closed_leg_immutable(self):
        conn = _make_conn()
        ensure_pilot(conn, self.CID, "Tester")
        # Leg 1: EDDK → EDDW komplett.
        self._seed_leg_a_to_b(conn)
        # Leg 2: erneutes Abheben ab EDDW, danach nur Reiseflug (keine Landung → offener Tail).
        self._pos(conn, "2026-07-02T10:50:00Z", *self.B, 800, 80)     # Abheben (AGL 780 > 500)
        self._pos(conn, "2026-07-02T11:00:00Z", 53.3, 9.3, 5000, 120)  # Reiseflug, noch in der Luft
        conn.commit()

        cols = "dep_icao, arr_icao, takeoff_ts, landing_ts, complete, distance_nm"
        n = recompute_gps_legs(conn, self.CID)
        assert n == 2
        legs = conn.execute(
            f"SELECT {cols} FROM gps_legs WHERE cid=? ORDER BY takeoff_ts", (self.CID,)
        ).fetchall()
        leg1_before = dict(legs[0])
        assert legs[0]["complete"] == 1 and legs[0]["arr_icao"] == "EDDW"
        assert legs[1]["complete"] == 0
        assert legs[1]["arr_icao"] is None
        assert legs[1]["landing_ts"] is None

        # Tail landet nun in EDDH und wird > 180 s gehalten → Leg 2 wird komplett.
        self._pos(conn, "2026-07-02T11:10:00Z", 53.6, 9.9, 400, 60)   # Anflug EDDH
        self._pos(conn, "2026-07-02T11:12:00Z", *self.C, 60, 0)       # Touchdown EDDH (AGL 7)
        self._pos(conn, "2026-07-02T11:16:00Z", *self.C, 60, 0)       # 240 s Dwell → Ankunft
        conn.commit()

        n2 = recompute_gps_legs(conn, self.CID)
        assert n2 == 2
        legs2 = conn.execute(
            f"SELECT {cols} FROM gps_legs WHERE cid=? ORDER BY takeoff_ts", (self.CID,)
        ).fetchall()
        conn.close()
        # Leg 1 inhaltlich unverändert.
        assert dict(legs2[0]) == leg1_before
        # Leg 2 nun abgeschlossen mit Ziel-ICAO.
        assert legs2[1]["complete"] == 1
        assert legs2[1]["arr_icao"] == "EDDH"
        assert legs2[1]["landing_ts"] == "2026-07-02T11:12:00Z"

    def test_empty_history_returns_zero(self):
        conn = _make_conn()
        ensure_pilot(conn, self.CID, "Tester")
        conn.commit()
        n = recompute_gps_legs(conn, self.CID)
        rows = conn.execute(
            "SELECT COUNT(*) FROM gps_legs WHERE cid=?", (self.CID,)
        ).fetchone()[0]
        conn.close()
        assert n == 0
        assert rows == 0


class TestStatsimGpsAudit:
    """Schatten-Interpretation von StatSim-Flügen: audit_gps_vs_refile rechnet die GPS-Legs
    on-demand aus statsim_position_history (in-memory, keine Speicherung) — zeigt, wie StatSim-
    Flüge unter GPS-only interpretiert würden. Reale Plätze EDDK→EDDW."""

    SID = 99001
    CID = 4243
    A = (50.8659, 7.14274)    # EDDK, elev 302
    B = (53.0475, 8.78667)    # EDDW, elev 14

    def _spos(self, conn, ts, lat, lon, alt, gs):
        conn.execute(
            "INSERT INTO statsim_position_history (statsim_id,latitude,longitude,altitude,"
            "groundspeed,heading,ts) VALUES (?,?,?,?,?,0,?)",
            (self.SID, lat, lon, alt, gs, ts),
        )

    def _seed(self, conn):
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES "
            "(?,?,'FRS10','EDDK','EDDW','C172','2026-07-02T09:58:00Z','2026-07-02T10:50:00Z',52,'x')",
            (self.SID, self.CID),
        )
        # Track: Boden EDDK → Steigflug (AGL > 500) → Reiseflug → Landung EDDW + Dwell > 180 s.
        self._spos(conn, "2026-07-02T10:00:00Z", *self.A, 302, 0)
        self._spos(conn, "2026-07-02T10:01:00Z", *self.A, 302, 5)
        self._spos(conn, "2026-07-02T10:02:00Z", *self.A, 1200, 80)
        self._spos(conn, "2026-07-02T10:20:00Z", 52.0, 8.0, 5000, 120)
        self._spos(conn, "2026-07-02T10:38:00Z", 53.0, 8.7, 500, 60)
        self._spos(conn, "2026-07-02T10:40:00Z", *self.B, 20, 0)
        self._spos(conn, "2026-07-02T10:44:00Z", *self.B, 20, 0)

    def test_statsim_leg_interpreted_in_audit(self):
        conn = _make_conn()
        self._seed(conn)
        conn.commit()
        res = audit_gps_vs_refile(
            conn, start="2026-07-01T00:00:00Z", end="2026-07-03T00:00:00Z",
            statsim_sample=10,
        )
        conn.close()
        assert "statsim" in res
        st = res["statsim"]
        assert st["sampled"] >= 1
        assert st["total"] >= 1
        flt = next(f for f in st["flights"] if f["statsim_id"] == self.SID)
        assert flt["n_legs"] == 1
        assert flt["legs"][0]["dep_icao"] == "EDDK"
        assert flt["legs"][0]["arr_icao"] == "EDDW"
        assert flt["classification"] == "match"

    def test_statsim_sample_zero_omits_section(self):
        conn = _make_conn()
        self._seed(conn)
        conn.commit()
        res = audit_gps_vs_refile(
            conn, start="2026-07-01T00:00:00Z", end="2026-07-03T00:00:00Z",
        )
        conn.close()
        assert "statsim" not in res


class TestStatsimBackfillSelection:
    """Auswahl der StatSim-Flüge, deren Track noch nicht lokal gecacht ist (für den Backfill)."""

    def _cache(self, conn, sid, cid, cs="FRS10", dur=60):
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
            "logon_time,logoff_time,duration_min,fetched_at) VALUES "
            "(?,?,?,'EDDK','EDDW','C172','2026-07-02T09:58:00Z','2026-07-02T10:50:00Z',?,'x')",
            (sid, cid, cs, dur),
        )

    def test_only_uncached_selected(self):
        conn = _make_conn()
        self._cache(conn, 501, 11)   # uncached
        self._cache(conn, 502, 11)   # cached (hat eine Position)
        self._cache(conn, 503, 12)   # uncached
        conn.execute(
            "INSERT INTO statsim_position_history (statsim_id,latitude,longitude,altitude,"
            "groundspeed,heading,ts) VALUES (502,50.0,8.0,300,0,0,'2026-07-02T10:00:00Z')"
        )
        conn.commit()
        ids = get_uncached_statsim_ids(conn, callsign_prefix="FRS", limit=10)
        remaining = count_uncached_statsim(conn, callsign_prefix="FRS")
        conn.close()
        assert set(ids) == {501, 503}
        assert remaining == 2

    def test_limit_and_filters(self):
        conn = _make_conn()
        self._cache(conn, 601, 11)             # uncached, ok
        self._cache(conn, 602, 11)             # uncached, ok
        self._cache(conn, 603, 11, dur=3)      # duration_min <= 5 → raus
        self._cache(conn, 604, 11, cs="XYZ99")  # falsches Präfix → raus
        conn.commit()
        ids = get_uncached_statsim_ids(conn, callsign_prefix="FRS", limit=1)
        remaining = count_uncached_statsim(conn, callsign_prefix="FRS")
        conn.close()
        assert len(ids) == 1              # Limit greift
        assert ids[0] in {601, 602}
        assert remaining == 2             # nur die zwei gültigen uncachten
