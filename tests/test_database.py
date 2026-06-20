"""Tests für app/database.py — alle Tests mit In-Memory-DB (:memory:)."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    canonicalize_flights,
    cleanup_old_history,
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
