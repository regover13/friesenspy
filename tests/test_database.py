"""Tests für app/database.py — alle Tests mit In-Memory-DB (:memory:)."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    cleanup_old_history,
    close_flight,
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

    def test_no_merge_gap_too_large(self):
        """Gleiche Route aber Gap > 5 Min → nicht mergen."""
        f1 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:00:00Z", "2026-06-06T08:06:00Z", 6)
        f2 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:20:00Z", "2026-06-06T09:00:00Z", 40)
        result = merge_fragmented_flights([f1, f2])
        assert len(result) == 2

    def test_no_merge_different_callsign(self):
        """Verschiedene Callsigns → nicht mergen."""
        f1 = self._flight("FRS153", "EDDN", "EDPH", "2026-06-06T08:00:00Z", "2026-06-06T08:04:00Z", 4)
        f2 = self._flight("FRS154", "EDDN", "EDPH", "2026-06-06T08:06:00Z", "2026-06-06T08:50:00Z", 44)
        result = merge_fragmented_flights([f1, f2])
        assert len(result) == 2
