"""SQLite WAL-Mode Datenbank-Layer für FriesenSpy."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS pilots (
    cid       INTEGER PRIMARY KEY,
    name      TEXT,
    added_at  TEXT
);

CREATE TABLE IF NOT EXISTS flights (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cid           INTEGER REFERENCES pilots(cid),
    callsign      TEXT,
    aircraft_short TEXT,
    departure     TEXT,
    arrival       TEXT,
    logon_time    TEXT,
    logoff_time   TEXT,
    duration_min  INTEGER
);

CREATE TABLE IF NOT EXISTS live_positions (
    cid          INTEGER PRIMARY KEY,
    callsign     TEXT,
    aircraft     TEXT,
    departure    TEXT,
    arrival      TEXT,
    latitude     REAL,
    longitude    REAL,
    altitude     INTEGER,
    groundspeed  INTEGER,
    heading      INTEGER,
    logon_time   TEXT,
    updated_at   TEXT,
    flight_rules TEXT,
    aircraft_icao TEXT,
    alternate    TEXT,
    deptime      TEXT,
    cruise_tas   TEXT,
    enroute_time TEXT,
    fuel_time    TEXT,
    route        TEXT,
    remarks      TEXT
);

CREATE TABLE IF NOT EXISTS position_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cid         INTEGER NOT NULL REFERENCES pilots(cid),
    callsign    TEXT,
    latitude    REAL,
    longitude   REAL,
    altitude    INTEGER,
    groundspeed INTEGER,
    heading     INTEGER,
    ts          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ph_cid_ts ON position_history(cid, ts);
CREATE INDEX IF NOT EXISTS idx_ph_ts     ON position_history(ts);
CREATE INDEX IF NOT EXISTS idx_flights_cid ON flights(cid);

CREATE TABLE IF NOT EXISTS statsim_cache (
    statsim_id   INTEGER PRIMARY KEY,
    cid          INTEGER NOT NULL,
    callsign     TEXT,
    departure    TEXT,
    arrival      TEXT,
    aircraft     TEXT,
    logon_time   TEXT,
    logoff_time  TEXT,
    duration_min INTEGER,
    fetched_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sc_cid ON statsim_cache(cid);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    """Return current UTC time as ISO8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO8601 UTC string (with or without trailing Z) to datetime."""
    ts = ts.rstrip("Z")
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_LIVE_POSITIONS_MIGRATIONS = [
    "ALTER TABLE live_positions ADD COLUMN flight_rules TEXT",
    "ALTER TABLE live_positions ADD COLUMN aircraft_icao TEXT",
    "ALTER TABLE live_positions ADD COLUMN alternate TEXT",
    "ALTER TABLE live_positions ADD COLUMN deptime TEXT",
    "ALTER TABLE live_positions ADD COLUMN cruise_tas TEXT",
    "ALTER TABLE live_positions ADD COLUMN enroute_time TEXT",
    "ALTER TABLE live_positions ADD COLUMN fuel_time TEXT",
    "ALTER TABLE live_positions ADD COLUMN route TEXT",
    "ALTER TABLE live_positions ADD COLUMN remarks TEXT",
]


def init_db(db_path: str) -> None:
    """Datenbank initialisieren: WAL-Mode setzen, Tabellen/Indizes anlegen (IF NOT EXISTS)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_DDL)
        # Migration: neue Spalten hinzufügen falls noch nicht vorhanden
        for stmt in _LIVE_POSITIONS_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # Spalte existiert bereits
        conn.commit()
    finally:
        conn.close()


def get_connection(db_path: str) -> sqlite3.Connection:
    """Neue Verbindung mit WAL-Mode und row_factory=sqlite3.Row."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_pilot(conn: sqlite3.Connection, cid: int, name: str) -> None:
    """Pilot in pilots-Tabelle eintragen falls noch nicht vorhanden (INSERT OR IGNORE)."""
    conn.execute(
        "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (?, ?, ?)",
        (cid, name, _now_utc()),
    )


def open_flight(
    conn: sqlite3.Connection,
    cid: int,
    callsign: str,
    aircraft_short: str,
    departure: str,
    arrival: str,
    logon_time: str,
) -> int:
    """Neuen Flug eröffnen, flight.id zurückgeben."""
    cur = conn.execute(
        """
        INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, logon_time)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (cid, callsign, aircraft_short, departure, arrival, logon_time),
    )
    return cur.lastrowid  # type: ignore[return-value]


def close_flight(conn: sqlite3.Connection, flight_id: int, logoff_time: str) -> None:
    """Flug abschließen: logoff_time setzen, duration_min berechnen."""
    row = conn.execute(
        "SELECT logon_time FROM flights WHERE id = ?", (flight_id,)
    ).fetchone()
    if row is None:
        return

    logon_dt = _parse_iso(row[0])
    logoff_dt = _parse_iso(logoff_time)
    duration_min = max(0, int((logoff_dt - logon_dt).total_seconds() / 60))

    conn.execute(
        "UPDATE flights SET logoff_time = ?, duration_min = ? WHERE id = ?",
        (logoff_time, duration_min, flight_id),
    )


def upsert_live_position(
    conn: sqlite3.Connection,
    cid: int,
    callsign: str,
    aircraft: str,
    departure: str,
    arrival: str,
    latitude: float,
    longitude: float,
    altitude: int,
    groundspeed: int,
    heading: int,
    logon_time: str,
    flight_rules: str = "",
    aircraft_icao: str = "",
    alternate: str = "",
    deptime: str = "",
    cruise_tas: str = "",
    enroute_time: str = "",
    fuel_time: str = "",
    route: str = "",
    remarks: str = "",
) -> None:
    """Live-Position aktualisieren (INSERT OR REPLACE), updated_at = jetzt."""
    conn.execute(
        """
        INSERT OR REPLACE INTO live_positions
            (cid, callsign, aircraft, departure, arrival,
             latitude, longitude, altitude, groundspeed, heading,
             logon_time, updated_at,
             flight_rules, aircraft_icao, alternate, deptime, cruise_tas,
             enroute_time, fuel_time, route, remarks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cid, callsign, aircraft, departure, arrival,
            latitude, longitude, altitude, groundspeed, heading,
            logon_time, _now_utc(),
            flight_rules, aircraft_icao, alternate, deptime, cruise_tas,
            enroute_time, fuel_time, route, remarks,
        ),
    )


def remove_live_position(conn: sqlite3.Connection, cid: int) -> None:
    """Pilot aus live_positions entfernen (offline gegangen)."""
    conn.execute("DELETE FROM live_positions WHERE cid = ?", (cid,))


def save_position_history(
    conn: sqlite3.Connection,
    cid: int,
    callsign: str,
    latitude: float,
    longitude: float,
    altitude: int,
    groundspeed: int,
    heading: int,
) -> None:
    """Positions-Snapshot speichern, ts = jetzt UTC."""
    conn.execute(
        """
        INSERT INTO position_history
            (cid, callsign, latitude, longitude, altitude, groundspeed, heading, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cid, callsign, latitude, longitude, altitude, groundspeed, heading, _now_utc()),
    )


def get_live_positions(conn: sqlite3.Connection) -> list[dict]:
    """Alle aktuellen Live-Positionen als Liste von Dicts."""
    rows = conn.execute(
        "SELECT lp.*, p.name FROM live_positions lp LEFT JOIN pilots p ON lp.cid = p.cid"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_stats(conn: sqlite3.Connection, days: int = 30) -> list[dict]:
    """Letzter Flug + Anzahl Flüge pro Pilot (FriesenSpy + StatSim-Cache).

    Alle Werte (Sichtbarkeit, Fluganzahl, Dauer) werden auf den gewählten
    Zeitraum (days) begrenzt.
    """
    rows = conn.execute(
        """
        SELECT
            p.cid,
            p.name,
            COALESCE(
                (SELECT lp.callsign FROM live_positions lp WHERE lp.cid = p.cid),
                (SELECT f2.callsign FROM flights f2 WHERE f2.cid = p.cid
                 ORDER BY f2.logon_time DESC LIMIT 1)
            ) AS last_callsign,
            COUNT(DISTINCT f_all.id)          AS fs_count,
            COUNT(DISTINCT sc_all.statsim_id) AS st_count,
            MAX(f_filt.logon_time)            AS last_fs,
            MAX(CASE WHEN sc_filt.logon_time != '' THEN sc_filt.logon_time END) AS last_st,
            (SELECT COALESCE(SUM(duration_min), 0)
             FROM flights
             WHERE cid = p.cid
               AND logon_time >= datetime('now', ? || ' days')
               AND logoff_time IS NOT NULL) AS fs_duration_min,
            (SELECT COALESCE(SUM(duration_min), 0)
             FROM statsim_cache
             WHERE cid = p.cid
               AND logon_time >= datetime('now', ? || ' days')
               AND logon_time != '')        AS st_duration_min
        FROM pilots p
        LEFT JOIN flights f_filt
               ON f_filt.cid = p.cid
              AND f_filt.logon_time >= datetime('now', ? || ' days')
              AND f_filt.logoff_time IS NOT NULL
        LEFT JOIN statsim_cache sc_filt
               ON sc_filt.cid = p.cid
              AND sc_filt.logon_time >= datetime('now', ? || ' days')
              AND sc_filt.logon_time != ''
        LEFT JOIN flights f_all
               ON f_all.cid = p.cid
              AND f_all.logon_time >= datetime('now', ? || ' days')
              AND f_all.logoff_time IS NOT NULL
        LEFT JOIN statsim_cache sc_all
               ON sc_all.cid = p.cid
              AND sc_all.logon_time >= datetime('now', ? || ' days')
              AND sc_all.logon_time != ''
        WHERE f_filt.id IS NOT NULL
           OR sc_filt.statsim_id IS NOT NULL
           OR EXISTS (
               SELECT 1 FROM flights fo
               WHERE fo.cid = p.cid
                 AND fo.logon_time >= datetime('now', ? || ' days')
                 AND fo.logoff_time IS NULL
           )
        GROUP BY p.cid, p.name
        """,
        (f"-{days}",) * 7,
    ).fetchall()
    result = []
    for r in rows:
        last_flight = max(filter(None, [r["last_fs"], r["last_st"]]), default=None)
        result.append({
            "cid": r["cid"],
            "name": r["name"],
            "last_callsign": r["last_callsign"] or "",
            "fs_count": r["fs_count"],
            "st_count": r["st_count"],
            "flight_count": r["fs_count"] + r["st_count"],
            "total_duration_min": (r["fs_duration_min"] or 0) + (r["st_duration_min"] or 0),
            "last_flight": last_flight,
        })
    result.sort(key=lambda x: x["last_flight"] or "", reverse=True)
    return result


def get_live_flight_track(conn: sqlite3.Connection, cid: int) -> list[dict]:
    """Positions-Track des aktuell laufenden Fluges (logoff_time IS NULL)."""
    flight = conn.execute(
        "SELECT logon_time FROM flights WHERE cid = ? AND logoff_time IS NULL"
        " ORDER BY logon_time DESC LIMIT 1",
        (cid,),
    ).fetchone()
    if not flight:
        return []
    rows = conn.execute(
        """SELECT latitude, longitude, altitude, groundspeed, heading, ts
           FROM position_history
           WHERE cid = ? AND ts >= ?
           ORDER BY ts""",
        (cid, flight["logon_time"]),
    ).fetchall()
    return [dict(r) for r in rows]


def cleanup_old_history(conn: sqlite3.Connection, days: int = 90) -> int:
    """position_history-Einträge älter als N Tage löschen. Gibt Anzahl gelöschter Zeilen zurück."""
    cur = conn.execute(
        "DELETE FROM position_history WHERE ts < datetime('now', ? || ' days')",
        (f"-{days}",),
    )
    return cur.rowcount


def get_position_history(
    conn: sqlite3.Connection, cid: int, start_ts: str, end_ts: str
) -> list[dict]:
    """Positionshistorie für einen Piloten in einem Zeitfenster (ISO8601 UTC Strings)."""
    rows = conn.execute(
        """
        SELECT * FROM position_history
        WHERE cid = ? AND ts >= ? AND ts <= ?
        ORDER BY ts
        """,
        (cid, start_ts, end_ts),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_all_position_history(
    conn: sqlite3.Connection, start_ts: str, end_ts: str
) -> list[dict]:
    """Positionshistorie aller Piloten in einem Zeitfenster (für Event-Filter)."""
    rows = conn.execute(
        """
        SELECT * FROM position_history
        WHERE ts >= ? AND ts <= ?
        ORDER BY ts
        """,
        (start_ts, end_ts),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def upsert_statsim_flights(conn: sqlite3.Connection, flights: list[dict]) -> None:
    """StatSim-Flüge in Cache schreiben (INSERT OR REPLACE)."""
    now = _now_utc()
    for f in flights:
        conn.execute(
            """
            INSERT OR REPLACE INTO statsim_cache
                (statsim_id, cid, callsign, departure, arrival, aircraft,
                 logon_time, logoff_time, duration_min, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f.get("statsim_id"), f.get("cid"), f.get("callsign", ""),
                f.get("departure", ""), f.get("arrival", ""), f.get("aircraft", ""),
                f.get("logon_time", ""), f.get("logoff_time"),
                f.get("duration_min"), now,
            ),
        )


def get_statsim_flights_for_pilot(
    conn: sqlite3.Connection, cid: int, days: int = 90
) -> list[dict]:
    """Gecachte StatSim-Flüge für einen Piloten."""
    rows = conn.execute(
        """
        SELECT * FROM statsim_cache
        WHERE cid = ?
          AND (logon_time >= datetime('now', ? || ' days') OR logon_time = '')
        ORDER BY logon_time DESC
        """,
        (cid, f"-{days}"),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_statsim_last_fetched(conn: sqlite3.Connection, cid: int) -> str | None:
    """Gibt fetched_at des neuesten Cache-Eintrags zurück, oder None."""
    row = conn.execute(
        "SELECT MAX(fetched_at) AS ft FROM statsim_cache WHERE cid = ?",
        (cid,),
    ).fetchone()
    return row["ft"] if row else None


def get_pilot_flights_friesenspy(
    conn: sqlite3.Connection, cid: int, days: int = 90
) -> list[dict]:
    """FriesenSpy-eigene Flüge für einen Piloten (nur abgeschlossene)."""
    rows = conn.execute(
        """
        SELECT id, cid, callsign, aircraft_short AS aircraft,
               departure, arrival, logon_time, logoff_time, duration_min
        FROM flights
        WHERE cid = ?
          AND logoff_time IS NOT NULL
          AND logon_time >= datetime('now', ? || ' days')
        ORDER BY logon_time DESC
        """,
        (cid, f"-{days}"),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]
