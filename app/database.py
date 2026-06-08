"""SQLite WAL-Mode Datenbank-Layer für FriesenSpy."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone


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
    duration_min  INTEGER,
    distance_nm   REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS calendar_events (
    uid      TEXT PRIMARY KEY,
    summary  TEXT,
    dtstart  TEXT,
    dtend    TEXT,
    location TEXT
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

CREATE TABLE IF NOT EXISTS statsim_position_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    statsim_id   INTEGER NOT NULL,
    latitude     REAL,
    longitude    REAL,
    altitude     INTEGER,
    groundspeed  INTEGER,
    heading      INTEGER,
    ts           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sph_statsim_id ON statsim_position_history(statsim_id);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint     TEXT UNIQUE NOT NULL,
    p256dh       TEXT NOT NULL,
    auth         TEXT NOT NULL,
    pilot_filter TEXT DEFAULT NULL,
    created_at   TEXT NOT NULL
);
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

_FLIGHTS_MIGRATIONS = [
    "ALTER TABLE flights ADD COLUMN distance_nm REAL DEFAULT 0",
]

_CALENDAR_MIGRATIONS = [
    # UIDs wurden auf zusammengesetztes Format umgestellt (uid_YYYYMMDDTHHMMSSZ).
    # Alte Einträge ohne dieses Suffix entfernen (idempotent).
    "DELETE FROM calendar_events WHERE uid NOT LIKE '%\\_2%T%Z' ESCAPE '\\'",
]

_PUSH_MIGRATIONS = [
    "ALTER TABLE push_subscriptions ADD COLUMN notify_prefiles INTEGER DEFAULT 0",
]

_PREFILE_SIGS_MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS prefile_sigs (
        cid       INTEGER PRIMARY KEY,
        deptime   TEXT,
        departure TEXT,
        arrival   TEXT,
        saved_at  TEXT
    )""",
]

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
        for stmt in _FLIGHTS_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        for stmt in _LIVE_POSITIONS_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # Spalte existiert bereits
        for stmt in _CALENDAR_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        for stmt in _PUSH_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        for stmt in _PREFILE_SIGS_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
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
    """Flug abschließen: logoff_time setzen, duration_min und distance_nm berechnen."""
    row = conn.execute(
        "SELECT cid, logon_time FROM flights WHERE id = ?", (flight_id,)
    ).fetchone()
    if row is None:
        return

    cid, logon_time = row[0], row[1]
    logon_dt = _parse_iso(logon_time)
    logoff_dt = _parse_iso(logoff_time)
    duration_min = max(0, int((logoff_dt - logon_dt).total_seconds() / 60))

    # GPS-Distanz aus position_history berechnen
    from app.geo import haversine as _haversine
    pos_rows = conn.execute(
        "SELECT latitude, longitude FROM position_history "
        "WHERE cid = ? AND ts >= ? AND ts <= ? AND latitude IS NOT NULL ORDER BY ts",
        (cid, logon_time, logoff_time),
    ).fetchall()
    dist_km = 0.0
    for i in range(1, len(pos_rows)):
        p0, p1 = pos_rows[i - 1], pos_rows[i]
        if p0[0] and p0[1] and p1[0] and p1[1]:
            dist_km += _haversine(p0[0], p0[1], p1[0], p1[1])
    distance_nm = round(dist_km / 1.852)

    conn.execute(
        "UPDATE flights SET logoff_time = ?, duration_min = ?, distance_nm = ? WHERE id = ?",
        (logoff_time, duration_min, distance_nm, flight_id),
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


def get_stats(
    conn: sqlite3.Connection, days: int = 30, callsign_prefix: str = "FRS"
) -> list[dict]:
    """Letzter Flug + Anzahl FRS*-Flüge pro Pilot (FriesenSpy + StatSim-Cache).

    Alle Werte werden auf den gewählten Zeitraum (days) und den konfigurierten
    Callsign-Prefix begrenzt. StatSim-Einträge ohne FRS*-Callsign werden nicht
    gezählt (Piloten fliegen auch in anderen VAs).
    """
    prefix_pat = callsign_prefix + "%"

    # Merge-Fragmente aus fs_count ausschließen (gleiche Logik wie get_stats_activity)
    nofp_ids = _nofp_fragment_ids(conn, days)
    _same_fp_excl_filt = (
        " AND NOT EXISTS ("
        "SELECT 1 FROM flights f2"
        " WHERE f2.cid=f_filt.cid AND f2.callsign=f_filt.callsign AND f2.duration_min>5"
        " AND CAST((JULIANDAY(f2.logon_time)-JULIANDAY(f_filt.logoff_time))*1440 AS INTEGER) BETWEEN -2 AND 5"
        " AND f_filt.departure!='' AND f2.departure=f_filt.departure AND f2.arrival=f_filt.arrival)"
    )
    _nofp_excl_filt = (
        f" AND f_filt.id NOT IN ({','.join(str(x) for x in nofp_ids)})" if nofp_ids else ""
    )
    _merge_excl_filt = _same_fp_excl_filt + _nofp_excl_filt

    rows = conn.execute(
        f"""
        SELECT
            p.cid,
            p.name,
            COALESCE(
                (SELECT lp.callsign FROM live_positions lp WHERE lp.cid = p.cid),
                (SELECT f2.callsign FROM flights f2 WHERE f2.cid = p.cid
                 ORDER BY f2.logon_time DESC LIMIT 1)
            ) AS last_callsign,
            COUNT(DISTINCT f_filt.id) AS fs_count,
            COUNT(DISTINCT CASE
              WHEN NOT EXISTS (
                SELECT 1 FROM flights fx
                WHERE fx.cid = p.cid
                  AND fx.logon_time >= datetime('now', ? || ' days')
                  AND fx.logoff_time IS NOT NULL
                  AND fx.duration_min > 5
                  AND substr(fx.logon_time, 1, 16) = substr(sc_filt.logon_time, 1, 16)
              ) THEN sc_filt.statsim_id
            END) AS st_count,
            MAX(f_filt.logon_time)             AS last_fs,
            MAX(CASE WHEN sc_filt.logon_time != '' THEN sc_filt.logon_time END) AS last_st,
            (SELECT COALESCE(SUM(duration_min), 0)
             FROM flights
             WHERE cid = p.cid
               AND logon_time >= datetime('now', ? || ' days')
               AND logoff_time IS NOT NULL
               AND duration_min > 5) AS fs_duration_min,
            (SELECT COALESCE(SUM(
               COALESCE(duration_min,
                 CASE WHEN logoff_time IS NOT NULL AND logoff_time != ''
                 THEN CAST((JULIANDAY(logoff_time) - JULIANDAY(logon_time)) * 1440 AS INTEGER)
                 END)), 0)
             FROM statsim_cache
             WHERE cid = p.cid
               AND logon_time >= datetime('now', ? || ' days')
               AND logon_time != ''
               AND callsign LIKE ?
               AND duration_min > 5)        AS st_duration_min
        FROM pilots p
        LEFT JOIN flights f_filt
               ON f_filt.cid = p.cid
              AND f_filt.callsign LIKE ?
              AND f_filt.logon_time >= datetime('now', ? || ' days')
              AND f_filt.logoff_time IS NOT NULL
              AND f_filt.duration_min > 5{_merge_excl_filt}
        LEFT JOIN statsim_cache sc_filt
               ON sc_filt.cid = p.cid
              AND sc_filt.logon_time >= datetime('now', ? || ' days')
              AND sc_filt.logon_time != ''
              AND sc_filt.callsign LIKE ?
              AND sc_filt.duration_min > 5
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
        (
            f"-{days}",    # st_count: fx.logon_time
            f"-{days}",    # fs_duration_min: logon_time
            f"-{days}",    # st_duration_min: logon_time
            prefix_pat,    # st_duration_min: callsign LIKE
            prefix_pat,    # f_filt join: callsign LIKE
            f"-{days}",    # f_filt join: logon_time
            f"-{days}",    # sc_filt join: logon_time
            prefix_pat,    # sc_filt join: callsign LIKE
            f"-{days}",    # WHERE EXISTS: logon_time
        ),
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
    return result


def get_stats_activity(
    conn: sqlite3.Connection, days: int = 30, callsign_prefix: str = "FRS"
) -> dict:
    """Flugaktivität über Zeit — für Liniendiagramm im Statistiken-Tab.

    Gruppierung: ≤93 Tage → täglich, >93 Tage → monatlich.
    Gibt alle Perioden mit Lücken gefüllt (0-Einträge) zurück.
    Felder pro Periode: pilot_count, flight_count, total_duration_min.
    """
    prefix_pat = callsign_prefix + "%"
    today = date.today()
    start = today - timedelta(days=days)

    if days <= 93:
        sql_fmt = "%Y-%m-%d"
        grouping = "day"
    else:
        sql_fmt = "%Y-%m"
        grouping = "month"

    # Früheres Fragment eines gemergten Fluges ausschließen (spiegelt merge_fragmented_flights):
    # gleicher Callsign + (gleicher nicht-leerer FP ODER aktueller ohne FP) + Nachfolger in 5 Min
    # Geo-geprüfte no-FP-Fragment-IDs (Python, weil SQL kein Haversine kann)
    nofp_ids = _nofp_fragment_ids(conn, days)
    # same-FP-Fragmente: in SQL erkennbar (gleicher nicht-leerer Flugplan, Lücke ≤ 5 Min)
    _same_fp_excl = (
        " AND NOT EXISTS ("
        "SELECT 1 FROM flights f2"
        " WHERE f2.cid=f.cid AND f2.callsign=f.callsign AND f2.duration_min>5"
        " AND CAST((JULIANDAY(f2.logon_time)-JULIANDAY(f.logoff_time))*1440 AS INTEGER) BETWEEN -2 AND 5"
        " AND f.departure!='' AND f2.departure=f.departure AND f2.arrival=f.arrival)"
    )
    # no-FP-Fragmente: via Python-IDs (inkl. Geo-Check)
    _nofp_excl = (
        f" AND f.id NOT IN ({','.join(str(x) for x in nofp_ids)})" if nofp_ids else ""
    )
    _merge_excl = _same_fp_excl + _nofp_excl
    # Fragment-Dauer-Bedingung für fs_dur: same-FP + geo-bestätigte no-FP-IDs
    _frag_cond = "(frag.departure!='' AND f.departure=frag.departure AND f.arrival=frag.arrival)"
    if nofp_ids:
        _frag_cond += f" OR frag.id IN ({','.join(str(x) for x in nofp_ids)})"

    # StatSim-Einträge deduplizieren gegen bereits in FriesenSpy vorhandene Flüge
    _dedup = (
        " AND NOT EXISTS ("
        "SELECT 1 FROM flights fx WHERE fx.cid = sc.cid"
        " AND fx.logoff_time IS NOT NULL AND fx.duration_min > 5"
        " AND substr(fx.logon_time,1,16)=substr(sc.logon_time,1,16))"
    )

    # Flugzahlen (Ghost ≤ 5 Min und Merge-Fragmente ausgeschlossen; StatSim dedupliziert)
    fs = {r[0]: r[1] for r in conn.execute(
        "SELECT strftime(?, f.logon_time), COUNT(*) FROM flights f "
        "WHERE f.logon_time >= datetime('now', ? || ' days') AND f.logoff_time IS NOT NULL "
        "AND f.duration_min > 5" + _merge_excl + " GROUP BY 1",
        (sql_fmt, f"-{days}"),
    ).fetchall()}
    st = {r[0]: r[1] for r in conn.execute(
        "SELECT strftime(?, sc.logon_time), COUNT(*) FROM statsim_cache sc "
        "WHERE sc.logon_time >= datetime('now', ? || ' days') AND sc.logon_time != '' "
        "AND sc.callsign LIKE ? AND sc.duration_min > 5" + _dedup + " GROUP BY 1",
        (sql_fmt, f"-{days}", prefix_pat),
    ).fetchall()}

    # Unique Piloten pro Periode (Ghost-Flüge und Fragmente ausgeschlossen)
    pilots_by_period: dict[str, set] = {}
    for p, cid in conn.execute(
        "SELECT strftime(?, f.logon_time), f.cid FROM flights f "
        "WHERE f.logon_time >= datetime('now', ? || ' days') AND f.logoff_time IS NOT NULL "
        "AND f.duration_min > 5" + _merge_excl,
        (sql_fmt, f"-{days}"),
    ).fetchall():
        pilots_by_period.setdefault(p, set()).add(cid)
    for p, cid in conn.execute(
        "SELECT strftime(?, sc.logon_time), sc.cid FROM statsim_cache sc "
        "WHERE sc.logon_time >= datetime('now', ? || ' days') AND sc.logon_time != '' "
        "AND sc.callsign LIKE ? AND sc.duration_min > 5" + _dedup,
        (sql_fmt, f"-{days}", prefix_pat),
    ).fetchall():
        pilots_by_period.setdefault(p, set()).add(cid)
    pilot_count = {k: len(v) for k, v in pilots_by_period.items()}

    # Flugdauer pro Periode: Hauptflug + Dauer gemergedter Fragmente (StatSim dedupliziert)
    fs_dur = {r[0]: (r[1] or 0) for r in conn.execute(
        "SELECT strftime(?, f.logon_time),"
        " SUM(f.duration_min + COALESCE(("
        "  SELECT SUM(frag.duration_min) FROM flights frag"
        "  WHERE frag.cid=f.cid AND frag.callsign=f.callsign"
        "  AND CAST((JULIANDAY(f.logon_time)-JULIANDAY(frag.logoff_time))*1440 AS INTEGER) BETWEEN -2 AND 5"
        f"  AND ({_frag_cond})"
        " ),0))"
        " FROM flights f WHERE f.logon_time >= datetime('now', ? || ' days')"
        " AND f.logoff_time IS NOT NULL AND f.duration_min > 5" + _merge_excl + " GROUP BY 1",
        (sql_fmt, f"-{days}"),
    ).fetchall()}
    st_dur = {r[0]: (r[1] or 0) for r in conn.execute(
        "SELECT strftime(?, sc.logon_time), SUM(COALESCE(sc.duration_min, "
        "CASE WHEN sc.logoff_time IS NOT NULL AND sc.logoff_time != '' "
        "THEN CAST((JULIANDAY(sc.logoff_time)-JULIANDAY(sc.logon_time))*1440 AS INTEGER) END)) "
        "FROM statsim_cache sc WHERE sc.logon_time >= datetime('now', ? || ' days') "
        "AND sc.logon_time != '' AND sc.callsign LIKE ? AND sc.duration_min > 5"
        + _dedup + " GROUP BY 1",
        (sql_fmt, f"-{days}", prefix_pat),
    ).fetchall()}

    # Lücken füllen
    periods: list[str] = []
    if grouping == "day":
        cur = start
        while cur <= today:
            periods.append(cur.strftime(sql_fmt))
            cur += timedelta(days=1)
    else:
        y, m = start.year, start.month
        while date(y, m, 1) <= today:
            periods.append(f"{y:04d}-{m:02d}")
            m += 1
            if m > 12:
                m = 1
                y += 1

    data = [
        {
            "period": p,
            "pilot_count": pilot_count.get(p, 0),
            "flight_count": (fs.get(p, 0) or 0) + (st.get(p, 0) or 0),
            "total_duration_min": (fs_dur.get(p, 0) or 0) + (st_dur.get(p, 0) or 0),
        }
        for p in periods
    ]
    return {"grouping": grouping, "data": data}


# Maximale Distanz (km) zwischen erster GPS-Position eines no-FP-Fragments
# und dem Abflughafen des Folgeflugs, damit ein Merge erlaubt ist.
_GEO_MERGE_KM = 10.0


def _first_pos(
    conn: sqlite3.Connection, cid: int, logon: str, logoff: str
) -> tuple[float, float] | None:
    """Erste GPS-Position eines Fluges aus position_history."""
    row = conn.execute(
        "SELECT latitude, longitude FROM position_history "
        "WHERE cid=? AND ts>=? AND ts<=? ORDER BY ts ASC LIMIT 1",
        (cid, logon, logoff),
    ).fetchone()
    return (row[0], row[1]) if row else None


def _nofp_geo_ok(
    conn: sqlite3.Connection, frag: dict, dep_icao: str
) -> bool:
    """True wenn die erste GPS-Position des no-FP-Fragments innerhalb _GEO_MERGE_KM
    vom Abflughafen des Folgeflugs liegt. Fallback True wenn keine Daten vorhanden."""
    from app.geo import haversine, icao_to_coords
    dep_coords = icao_to_coords(dep_icao)
    if dep_coords is None:
        return True
    cid = frag.get("cid")
    if cid is None:
        return True
    pos = _first_pos(conn, int(cid), frag.get("logon_time") or "", frag.get("logoff_time") or "")
    if pos is None:
        return True
    return haversine(pos[0], pos[1], dep_coords[0], dep_coords[1]) <= _GEO_MERGE_KM


def _nofp_fragment_ids(conn: sqlite3.Connection, days: int) -> set[int]:
    """IDs von no-FP-Flügen (duration > 5 Min) die als Merge-Fragmente gelten.

    Kriterien:
    - Leerer DEP+ARR, logoff_time gesetzt, duration_min > 5
    - Folgeflug desselben Callsigns mit FP innerhalb 5 Min
    - Erste GPS-Position innerhalb _GEO_MERGE_KM vom DEP des Folgeflugs
    """
    from app.geo import haversine, icao_to_coords
    rows = conn.execute(
        "SELECT f.id, f.cid, f.logon_time, f.logoff_time, f2.departure "
        "FROM flights f "
        "JOIN flights f2 ON f2.cid=f.cid AND f2.callsign=f.callsign "
        "  AND f2.duration_min>5 "
        "  AND CAST((JULIANDAY(f2.logon_time)-JULIANDAY(f.logoff_time))*1440 AS INTEGER) BETWEEN -2 AND 5 "
        "  AND (f2.departure!='' OR f2.arrival!='') "
        "WHERE f.departure='' AND f.arrival='' "
        "  AND f.duration_min>5 AND f.logoff_time IS NOT NULL "
        "  AND f.logon_time >= datetime('now', ? || ' days')",
        (f"-{days}",),
    ).fetchall()
    ids: set[int] = set()
    for fid, cid, logon, logoff, dep in rows:
        if not dep:
            ids.add(fid)
            continue
        dep_coords = icao_to_coords(dep)
        if dep_coords is None:
            ids.add(fid)
            continue
        pos = _first_pos(conn, cid, logon, logoff)
        if pos is None:
            ids.add(fid)
            continue
        if haversine(pos[0], pos[1], dep_coords[0], dep_coords[1]) <= _GEO_MERGE_KM:
            ids.add(fid)
    return ids


def merge_fragmented_flights(
    flights: list[dict],
    gap_minutes: int = 5,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """Merge consecutive same-callsign flights where one lacks a flight plan.

    Handles: pilot connects without FP (DEP/ARR empty), briefly disconnects,
    reconnects with FP. FriesenSpy records two entries; this merges them into one.
    Conditions: same callsign, exactly one has no DEP/ARR (or both same DEP+ARR),
    gap ≤ gap_minutes. With conn: no-FP merges additional geo-check via _nofp_geo_ok.
    """
    if len(flights) <= 1:
        return list(flights)

    ordered = sorted([dict(f) for f in flights], key=lambda f: f.get('logon_time') or '')
    result = []
    i = 0
    while i < len(ordered):
        curr = ordered[i]
        if i + 1 < len(ordered):
            nxt = ordered[i + 1]
            cs_match = (curr.get('callsign') or '') == (nxt.get('callsign') or '') != ''
            curr_no_fp = not (curr.get('departure') and curr.get('arrival'))
            nxt_no_fp  = not (nxt.get('departure')  and nxt.get('arrival'))
            same_fp = (
                bool(curr.get('departure'))
                and (curr.get('departure') or '') == (nxt.get('departure') or '')
                and (curr.get('arrival')   or '') == (nxt.get('arrival')   or '')
            )
            if cs_match and ((curr_no_fp ^ nxt_no_fp) or same_fp):
                try:
                    gap = (_parse_iso(nxt['logon_time']) - _parse_iso(curr['logoff_time'])).total_seconds() / 60
                    close = -2 <= gap <= gap_minutes
                except Exception:
                    close = False
                # Geo-Check für no-FP-Merges: erste GPS-Position des Fragments muss
                # in der Nähe des Abflughafens des Folgeflugs liegen.
                if close and conn is not None and (curr_no_fp ^ nxt_no_fp):
                    frag = curr if curr_no_fp else nxt
                    dep_icao = ((nxt if curr_no_fp else curr).get("departure") or "")
                    if dep_icao:
                        close = _nofp_geo_ok(conn, frag, dep_icao)
                if close:
                    fp = nxt if curr_no_fp else curr
                    merged = dict(fp)
                    merged['logon_time']   = min(t for t in [curr['logon_time'],  nxt['logon_time']]  if t)
                    merged['logoff_time']  = max(t for t in [curr.get('logoff_time', ''), nxt.get('logoff_time', '')] if t)
                    merged['duration_min'] = (curr.get('duration_min') or 0) + (nxt.get('duration_min') or 0)
                    result.append(merged)
                    i += 2
                    continue
        result.append(curr)
        i += 1
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


def save_statsim_positions(
    conn: sqlite3.Connection, statsim_id: int, positions: list[dict]
) -> None:
    """GPS-Track eines StatSim-Fluges lokal speichern (idempotent)."""
    if not positions:
        return
    exists = conn.execute(
        "SELECT 1 FROM statsim_position_history WHERE statsim_id = ? LIMIT 1",
        (statsim_id,),
    ).fetchone()
    if exists:
        return
    conn.executemany(
        """INSERT INTO statsim_position_history
           (statsim_id, latitude, longitude, altitude, groundspeed, heading, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                statsim_id,
                p.get("latitude"),
                p.get("longitude"),
                p.get("altitude"),
                p.get("groundspeed"),
                p.get("heading"),
                p.get("ts", ""),
            )
            for p in positions
        ],
    )


def get_statsim_positions(
    conn: sqlite3.Connection, statsim_id: int
) -> list[dict]:
    """Gecachten GPS-Track eines StatSim-Fluges zurückgeben."""
    rows = conn.execute(
        """SELECT latitude, longitude, altitude, groundspeed, heading, ts
           FROM statsim_position_history
           WHERE statsim_id = ?
           ORDER BY ts""",
        (statsim_id,),
    ).fetchall()
    return [dict(r) for r in rows]


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


# ---------------------------------------------------------------------------
# Push Subscriptions
# ---------------------------------------------------------------------------

def upsert_push_subscription(
    conn: sqlite3.Connection,
    endpoint: str,
    p256dh: str,
    auth: str,
    pilot_filter: list[int] | None = None,
    notify_prefiles: bool = True,
) -> None:
    """Browser-Push-Subscription speichern oder aktualisieren."""
    conn.execute(
        """INSERT INTO push_subscriptions (endpoint, p256dh, auth, pilot_filter, notify_prefiles, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(endpoint) DO UPDATE SET
               p256dh=excluded.p256dh,
               auth=excluded.auth,
               pilot_filter=excluded.pilot_filter,
               notify_prefiles=excluded.notify_prefiles""",
        (
            endpoint, p256dh, auth,
            json.dumps(pilot_filter) if pilot_filter is not None else None,
            1 if notify_prefiles else 0,
            _now_utc(),
        ),
    )


def delete_push_subscription(conn: sqlite3.Connection, endpoint: str) -> None:
    """Push-Subscription anhand des Endpoints löschen."""
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def upsert_calendar_events(conn: sqlite3.Connection, events: list[dict]) -> None:
    """FriesenEvents aus iCal-Feed in DB schreiben (INSERT OR REPLACE)."""
    for ev in events:
        conn.execute(
            "INSERT OR REPLACE INTO calendar_events (uid, summary, dtstart, dtend, location) "
            "VALUES (?, ?, ?, ?, ?)",
            (ev["uid"], ev["summary"], ev["dtstart"], ev["dtend"], ev["location"]),
        )


def get_calendar_events(conn: sqlite3.Connection, days_back: int = 365, days_ahead: int = 90) -> list[dict]:
    """FriesenEvents: vergangene N Tage + nächste M Tage, aufsteigend ab heute."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    future = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT uid, summary, dtstart, dtend, location FROM calendar_events "
        "WHERE dtstart >= ? AND dtstart <= ? "
        "ORDER BY ABS(julianday(dtstart) - julianday('now')) ASC",
        (cutoff, future),
    ).fetchall()
    return [dict(r) for r in rows]


def get_push_subscriptions_for_pilot(
    conn: sqlite3.Connection, cid: int
) -> list[dict]:
    """Alle Subscriptions die Notifications für diesen Piloten wollen.

    Gibt Subscriptions zurück wenn pilot_filter IS NULL (alle) oder cid in der Filter-Liste.
    """
    rows = conn.execute(
        "SELECT endpoint, p256dh, auth, pilot_filter, notify_prefiles FROM push_subscriptions"
    ).fetchall()
    result = []
    for row in rows:
        pf = row["pilot_filter"]
        if pf is None:
            result.append(dict(row))
        else:
            try:
                if cid in json.loads(pf):
                    result.append(dict(row))
            except (json.JSONDecodeError, TypeError):
                result.append(dict(row))
    return result


def get_push_subscriptions_for_prefile(
    conn: sqlite3.Connection, cid: int
) -> list[dict]:
    """Subscriptions die Prefile-Notifications für diesen Piloten wollen.

    Wie get_push_subscriptions_for_pilot, aber zusätzlich notify_prefiles = 1.
    """
    rows = conn.execute(
        "SELECT endpoint, p256dh, auth, pilot_filter, notify_prefiles "
        "FROM push_subscriptions WHERE notify_prefiles = 1"
    ).fetchall()
    result = []
    for row in rows:
        pf = row["pilot_filter"]
        if pf is None:
            result.append(dict(row))
        else:
            try:
                if cid in json.loads(pf):
                    result.append(dict(row))
            except (json.JSONDecodeError, TypeError):
                result.append(dict(row))
    return result


# ---------------------------------------------------------------------------
# Prefile Signatures (Persistenz für Neustart-Robustheit)
# ---------------------------------------------------------------------------

def load_prefile_sigs(conn: sqlite3.Connection) -> dict:
    """Gespeicherte Prefile-Signaturen laden (cid → (deptime, departure, arrival))."""
    rows = conn.execute(
        "SELECT cid, deptime, departure, arrival FROM prefile_sigs"
    ).fetchall()
    return {row["cid"]: (row["deptime"], row["departure"], row["arrival"]) for row in rows}


def save_prefile_sigs(conn: sqlite3.Connection, sigs: dict) -> None:
    """Aktuelle Prefile-Signaturen in die DB schreiben (DELETE+INSERT für Einfachheit)."""
    now = _now_utc()
    conn.execute("DELETE FROM prefile_sigs")
    for cid, (deptime, departure, arrival) in sigs.items():
        conn.execute(
            "INSERT INTO prefile_sigs (cid, deptime, departure, arrival, saved_at) VALUES (?, ?, ?, ?, ?)",
            (cid, deptime, departure, arrival, now),
        )
