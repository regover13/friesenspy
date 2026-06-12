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
    distance_nm   REAL DEFAULT 0,
    route         TEXT,
    remarks       TEXT,
    cruise_altitude TEXT,
    cruise_tas    TEXT,
    flight_rules  TEXT,
    aircraft_icao TEXT,
    alternate     TEXT,
    deptime       TEXT,
    enroute_time  TEXT,
    fuel_time     TEXT,
    superseded_by INTEGER,
    block_min     INTEGER
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
    "ALTER TABLE flights ADD COLUMN route TEXT",
    "ALTER TABLE flights ADD COLUMN remarks TEXT",
    "ALTER TABLE flights ADD COLUMN cruise_altitude TEXT",
    "ALTER TABLE flights ADD COLUMN cruise_tas TEXT",
    "ALTER TABLE flights ADD COLUMN flight_rules TEXT",
    "ALTER TABLE flights ADD COLUMN aircraft_icao TEXT",
    "ALTER TABLE flights ADD COLUMN alternate TEXT",
    "ALTER TABLE flights ADD COLUMN deptime TEXT",
    "ALTER TABLE flights ADD COLUMN enroute_time TEXT",
    "ALTER TABLE flights ADD COLUMN fuel_time TEXT",
    # superseded_by: NULL = aktiver Flug; sonst id des Behalt-Records (reversibler Dedup).
    "ALTER TABLE flights ADD COLUMN superseded_by INTEGER",
    # block_min: Bewegungszeit (erste bis letzte Bewegung) aus position_history.
    "ALTER TABLE flights ADD COLUMN block_min INTEGER",
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
        import logging as _log
        _logger = _log.getLogger(__name__)
        n = backfill_flight_distances(conn)
        if n:
            _logger.info("distance_nm für %d Flüge nachberechnet", n)
        b = backfill_block_minutes(conn)
        if b:
            _logger.info("block_min für %d Flüge nachberechnet", b)
        m = close_stale_flights(conn)
        if m:
            _logger.info("Zombie-Flüge geschlossen: %d", m)
        # Reihenfolge zwingend: erst konsolidieren (resettet superseded_by, markiert Duplikate,
        # korrigiert Zombie-Logoffs), DANN den partiellen Unique-Index anlegen.
        s = consolidate_flights(conn)
        conn.commit()
        if s:
            _logger.info("Flüge konsolidiert (superseded markiert): %d", s)
        # Strukturelle Dedup-Sperre: pro (cid, logon_time) nur EIN aktiver Flug.
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_flights_session "
                "ON flights(cid, logon_time) WHERE superseded_by IS NULL"
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            _logger.error("Partieller Unique-Index konnte nicht angelegt werden: %s", exc)
    finally:
        conn.close()


def get_connection(db_path: str) -> sqlite3.Connection:
    """Neue Verbindung mit WAL-Mode und row_factory=sqlite3.Row."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_pilot(conn: sqlite3.Connection, cid: int, name: str) -> bool:
    """Pilot in pilots-Tabelle eintragen falls noch nicht vorhanden. Gibt True zurück wenn neu."""
    conn.execute(
        "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (?, ?, ?)",
        (cid, name, _now_utc()),
    )
    return conn.execute("SELECT changes()").fetchone()[0] == 1


def open_flight(
    conn: sqlite3.Connection,
    cid: int,
    callsign: str,
    aircraft_short: str,
    departure: str,
    arrival: str,
    logon_time: str,
    *,
    route: str = "",
    remarks: str = "",
    cruise_altitude: str = "",
    cruise_tas: str = "",
    flight_rules: str = "",
    aircraft_icao: str = "",
    alternate: str = "",
    deptime: str = "",
    enroute_time: str = "",
    fuel_time: str = "",
) -> int:
    """Neuen Flug eröffnen, flight.id zurückgeben.

    Eine VATSIM-Verbindung ist eindeutig über (cid, logon_time) bestimmt. Der partielle
    Unique-Index idx_flights_session erzwingt pro (cid, logon_time) genau einen aktiven
    (superseded_by IS NULL) Flug. INSERT … ON CONFLICT DO NOTHING macht ein erneutes
    Öffnen derselben Verbindung (z. B. nach Container-Neustart) zum strukturellen No-Op;
    die bestehende id wird zurückgegeben.
    """
    conn.execute(
        """
        INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, logon_time,
                             route, remarks, cruise_altitude, cruise_tas, flight_rules, aircraft_icao,
                             alternate, deptime, enroute_time, fuel_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cid, logon_time) WHERE superseded_by IS NULL DO NOTHING
        """,
        (cid, callsign, aircraft_short, departure, arrival, logon_time,
         route, remarks, cruise_altitude, cruise_tas, flight_rules, aircraft_icao,
         alternate, deptime, enroute_time, fuel_time),
    )
    row = conn.execute(
        "SELECT id FROM flights WHERE cid = ? AND logon_time = ? AND superseded_by IS NULL",
        (cid, logon_time),
    ).fetchone()
    return row[0]  # type: ignore[return-value]


def close_stale_flights(conn: sqlite3.Connection, max_age_hours: int = 8) -> int:
    """Schließt offene Flüge (logoff_time IS NULL) die älter als max_age_hours sind.

    Nutzt den letzten position_history-Eintrag als logoff_time. Falls keine Positionen
    vorhanden sind (Test-Connect), wird logon_time als logoff_time gesetzt (duration=0).
    """
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    stale = conn.execute(
        "SELECT id, cid, logon_time FROM flights WHERE logoff_time IS NULL AND logon_time < ?",
        (cutoff,),
    ).fetchall()
    if not stale:
        return 0

    import logging as _log
    log = _log.getLogger(__name__)
    closed = 0
    for fid, cid, logon_time in stale:
        # Obere Schranke = Beginn der nächsten Session desselben Piloten (falls vorhanden),
        # damit der Logoff niemals Positionen eines späteren Fluges greift (Zombie-Inflation).
        next_logon = conn.execute(
            "SELECT MIN(logon_time) FROM flights "
            "WHERE cid = ? AND logon_time > ? AND superseded_by IS NULL",
            (cid, logon_time),
        ).fetchone()[0]
        upper = min(next_logon, cutoff) if next_logon else cutoff
        last_pos = conn.execute(
            "SELECT MAX(ts) FROM position_history WHERE cid = ? AND ts >= ? AND ts < ?",
            (cid, logon_time, upper),
        ).fetchone()[0]
        logoff_time = last_pos if last_pos else logon_time
        logon_dt = _parse_iso(logon_time)
        logoff_dt = _parse_iso(logoff_time)
        duration_min = max(0, int((logoff_dt - logon_dt).total_seconds() / 60))
        conn.execute(
            "UPDATE flights SET logoff_time = ?, duration_min = ? WHERE id = ?",
            (logoff_time, duration_min, fid),
        )
        log.info("Zombie-Flug id=%d (cid=%d) geschlossen: logoff=%s, dur=%d min", fid, cid, logoff_time, duration_min)
        closed += 1
    if closed:
        conn.commit()
    return closed


def backfill_flight_distances(conn: sqlite3.Connection) -> int:
    """Berechnet distance_nm für abgeschlossene Flüge nach, die noch 0 haben aber position_history besitzen."""
    from app.geo import haversine as _haversine
    # SELECT: [0]=id, [1]=cid, [2]=logon_time, [3]=logoff_time
    flights = conn.execute(
        "SELECT id, cid, logon_time, logoff_time FROM flights "
        "WHERE distance_nm = 0 AND logoff_time IS NOT NULL"
    ).fetchall()
    updated = 0
    for f in flights:
        fid, cid, logon_time, logoff_time = f[0], f[1], f[2], f[3]
        pos_rows = conn.execute(
            "SELECT latitude, longitude FROM position_history "
            "WHERE cid = ? AND ts >= ? AND ts <= ? AND latitude IS NOT NULL ORDER BY ts",
            (cid, logon_time, logoff_time),
        ).fetchall()
        if len(pos_rows) < 2:
            continue
        dist_km = 0.0
        for i in range(1, len(pos_rows)):
            p0, p1 = pos_rows[i - 1], pos_rows[i]
            if p0[0] and p0[1] and p1[0] and p1[1]:
                dist_km += _haversine(p0[0], p0[1], p1[0], p1[1])
        distance_nm = round(dist_km / 1.852)
        if distance_nm > 0:
            conn.execute("UPDATE flights SET distance_nm = ? WHERE id = ?", (distance_nm, fid))
            updated += 1
    if updated:
        conn.commit()
    return updated


def backfill_block_minutes(conn: sqlite3.Connection) -> int:
    """Berechnet block_min für abgeschlossene Flüge nach, die noch keins haben (NULL)."""
    flights = conn.execute(
        "SELECT id, cid, logon_time, logoff_time FROM flights "
        "WHERE block_min IS NULL AND logoff_time IS NOT NULL"
    ).fetchall()
    updated = 0
    for fid, cid, logon_time, logoff_time in flights:
        block_min = _block_minutes(conn, cid, logon_time, logoff_time)
        conn.execute("UPDATE flights SET block_min = ? WHERE id = ?", (block_min, fid))
        updated += 1
    if updated:
        conn.commit()
    return updated


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

    block_min = _block_minutes(conn, cid, logon_time, logoff_time)

    conn.execute(
        "UPDATE flights SET logoff_time = ?, duration_min = ?, distance_nm = ?, block_min = ? WHERE id = ?",
        (logoff_time, duration_min, distance_nm, block_min, flight_id),
    )


def _gps_distance_nm(
    conn: sqlite3.Connection, cid: int, logon_time: str, logoff_time: str
) -> int:
    """GPS-Distanz (nm) eines Fluges aus position_history (Haversine-Summe)."""
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
    return round(dist_km / 1.852)


# Groundspeed-Schwelle (kt), ab der ein Flugzeug als „in Bewegung" gilt (Block-Zeit).
_BLOCK_GS_KT = 2


def _block_minutes(
    conn: sqlite3.Connection, cid: int, logon_time: str, logoff_time: str
) -> int:
    """Block-/Bewegungszeit (Minuten): erste bis letzte Position mit groundspeed > _BLOCK_GS_KT
    innerhalb [logon, logoff]. Keine Bewegung → 0. Gate-to-gate inkl. Taxi."""
    rows = conn.execute(
        "SELECT MIN(ts), MAX(ts) FROM position_history "
        "WHERE cid = ? AND ts >= ? AND ts <= ? AND groundspeed > ?",
        (cid, logon_time, logoff_time, _BLOCK_GS_KT),
    ).fetchone()
    if not rows or not rows[0] or not rows[1]:
        return 0
    try:
        return max(0, int((_parse_iso(rows[1]) - _parse_iso(rows[0])).total_seconds() / 60))
    except Exception:
        return 0


def consolidate_flights(
    conn: sqlite3.Connection, *, statsim_correct: bool = True, shrink_margin_min: int = 10
) -> int:
    """Reversibler Cleanup von Duplikaten und Zombie-Logoffs.

    Schritte:
      A) Mehrere OFFENE Flüge je cid → nur die JÜNGSTE (aktuelle Live-Verbindung) offen lassen;
         ältere offene Flüge sind beendete Verbindungen (verpasster Disconnect, z. B. Reconnect
         über einen Neustart) → gedeckelt schließen (kein supersede).
      B) Exakte Duplikate (gleiche cid+logon_time) → besten behalten, Rest superseden.
      C) Zombie-Logoffs korrigieren: Logoff = letzte Position, gedeckelt auf die nächste
         Session — nur anwenden, wenn es die Dauer um ≥ shrink_margin_min verkürzt (nie verlängern).
      D) StatSim-Backstop: weiterhin grob unplausible FS-Dauern auf StatSim-Wert korrigieren.

    Reversibel: `UPDATE flights SET superseded_by = NULL`. Gibt Anzahl markierter Zeilen zurück.
    Committet NICHT selbst — der Aufrufer committet (ermöglicht Dry-Run via rollback).
    """
    # Selbst-korrigierend: bei jedem Lauf von vorn. Index droppen (sonst verbieten die
    # transienten Mehrfach-Aktiven den Reset) und superseded_by zurücksetzen. superseded_by
    # wird ausschließlich hier gesetzt → der Reset ist sicher. Index legt der Aufrufer neu an.
    conn.execute("DROP INDEX IF EXISTS idx_flights_session")
    conn.execute("UPDATE flights SET superseded_by = NULL")

    marked = 0

    # A) Mehrere offene Flüge je cid: nur die JÜNGSTE (= aktuelle, live Verbindung) offen lassen.
    # Ältere offene Flüge sind beendete Verbindungen (Disconnect verpasst — z. B. der Pilot hat
    # sich nach einem Container-Neustart neu verbunden, während die alte Session offen blieb).
    # Diese wie Zombies schließen: Logoff = letzte Position, gedeckelt auf die nächste Session.
    # KEIN supersede — der Read-Time-Merge fügt sie bei Bedarf wieder zu einem Flug zusammen.
    # Gleiche logon_time (echte Duplikate) bleibt Schritt B überlassen.
    open_by_cid: dict[int, list[tuple]] = {}
    for fid, cid, logon in conn.execute(
        "SELECT id, cid, logon_time FROM flights "
        "WHERE logoff_time IS NULL AND superseded_by IS NULL ORDER BY cid, logon_time"
    ).fetchall():
        open_by_cid.setdefault(cid, []).append((fid, logon))
    for cid, rows in open_by_cid.items():
        if len(rows) <= 1:
            continue
        latest_logon = rows[-1][1]  # rows sind nach logon_time aufsteigend sortiert
        for fid, logon in rows:
            if logon == latest_logon:
                continue  # jüngste Verbindung offen lassen (gleiche logon → Schritt B)
            next_logon = conn.execute(
                "SELECT MIN(logon_time) FROM flights "
                "WHERE cid=? AND logon_time>? AND superseded_by IS NULL",
                (cid, logon),
            ).fetchone()[0]
            if next_logon:
                last_pos = conn.execute(
                    "SELECT MAX(ts) FROM position_history WHERE cid=? AND ts>=? AND ts<?",
                    (cid, logon, next_logon),
                ).fetchone()[0]
            else:
                last_pos = conn.execute(
                    "SELECT MAX(ts) FROM position_history WHERE cid=? AND ts>=?",
                    (cid, logon),
                ).fetchone()[0]
            close_flight(conn, fid, last_pos or logon)

    # B) Exakte Duplikate (cid + logon_time)
    for cid, logon in conn.execute(
        "SELECT cid, logon_time FROM flights WHERE superseded_by IS NULL "
        "GROUP BY cid, logon_time HAVING COUNT(*) > 1"
    ).fetchall():
        # Keeper-Priorität: (1) Flug mit echtem Inhalt zuerst (Ghost mit gleicher logon_time
        # nicht behalten — sonst verschwindet der echte Flug, vgl. FRS123/09.06), (2) offener
        # (Live-)Flug zuerst, (3) niedrigste id. Die Dauer entscheidet NICHT (Zombies sind
        # aufgebläht) — Schritt C korrigiert den Logoff.
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM flights WHERE cid=? AND logon_time=? AND superseded_by IS NULL "
            "ORDER BY (distance_nm > 0.5 OR duration_min > 5) DESC, "
            "(logoff_time IS NULL) DESC, id ASC",
            (cid, logon),
        ).fetchall()]
        keep_id = ids[0]
        for fid in ids[1:]:
            conn.execute("UPDATE flights SET superseded_by = ? WHERE id = ?", (keep_id, fid))
            marked += 1

    # C) Zombie-Logoffs gedeckelt korrigieren
    for fid, cid, logon, logoff, dur in conn.execute(
        "SELECT id, cid, logon_time, logoff_time, duration_min FROM flights "
        "WHERE superseded_by IS NULL AND logoff_time IS NOT NULL"
    ).fetchall():
        next_logon = conn.execute(
            "SELECT MIN(logon_time) FROM flights "
            "WHERE cid=? AND logon_time>? AND superseded_by IS NULL",
            (cid, logon),
        ).fetchone()[0]
        if next_logon:
            last_pos = conn.execute(
                "SELECT MAX(ts) FROM position_history WHERE cid=? AND ts>=? AND ts<?",
                (cid, logon, next_logon),
            ).fetchone()[0]
        else:
            last_pos = conn.execute(
                "SELECT MAX(ts) FROM position_history WHERE cid=? AND ts>=? AND ts<=?",
                (cid, logon, logoff),
            ).fetchone()[0]
        if not last_pos:
            continue
        new_logoff = min(last_pos, logoff)
        new_dur = max(0, int((_parse_iso(new_logoff) - _parse_iso(logon)).total_seconds() / 60))
        if (dur or 0) - new_dur >= shrink_margin_min:
            new_dist = _gps_distance_nm(conn, cid, logon, new_logoff)
            conn.execute(
                "UPDATE flights SET logoff_time=?, duration_min=?, distance_nm=? WHERE id=?",
                (new_logoff, new_dur, new_dist, fid),
            )

    # D) StatSim-Backstop für weiterhin grob unplausible Dauern
    if statsim_correct:
        for fid, cid, logon, dur in conn.execute(
            "SELECT id, cid, logon_time, duration_min FROM flights "
            "WHERE superseded_by IS NULL AND logoff_time IS NOT NULL"
        ).fetchall():
            sc = conn.execute(
                "SELECT duration_min FROM statsim_cache "
                "WHERE cid=? AND duration_min IS NOT NULL "
                "AND substr(logon_time,1,16)=substr(?,1,16) LIMIT 1",
                (cid, logon),
            ).fetchone()
            if not sc or sc[0] is None:
                continue
            st_dur = sc[0]
            if st_dur > 0 and (dur or 0) > st_dur * 2 + 10:
                new_logoff = (_parse_iso(logon) + timedelta(minutes=st_dur)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                new_dist = _gps_distance_nm(conn, cid, logon, new_logoff)
                conn.execute(
                    "UPDATE flights SET logoff_time=?, duration_min=?, distance_nm=? WHERE id=?",
                    (new_logoff, st_dur, new_dist, fid),
                )

    return marked


def update_flight_plan(
    conn: sqlite3.Connection,
    flight_id: int,
    departure: str,
    arrival: str,
    *,
    route: str = "",
    remarks: str = "",
    cruise_altitude: str = "",
    cruise_tas: str = "",
    flight_rules: str = "",
    aircraft_icao: str = "",
    alternate: str = "",
    deptime: str = "",
    enroute_time: str = "",
    fuel_time: str = "",
) -> None:
    """Flugplan (DEP/ARR + erweiterte Felder) eines laufenden Fluges setzen."""
    conn.execute(
        """UPDATE flights SET departure=?, arrival=?,
                              route=?, remarks=?, cruise_altitude=?, cruise_tas=?,
                              flight_rules=?, aircraft_icao=?, alternate=?,
                              deptime=?, enroute_time=?, fuel_time=?
           WHERE id=?""",
        (departure, arrival, route, remarks, cruise_altitude, cruise_tas,
         flight_rules, aircraft_icao, alternate,
         deptime, enroute_time, fuel_time, flight_id),
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
    Callsign-Prefix begrenzt. Aggregiert über canonicalize_flights — dieselbe Wahrheit
    wie alle anderen Views (keine eigene Merge-/Dedup-Logik mehr).
    """
    prefix_pat = callsign_prefix + "%"
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    flights = canonicalize_flights(conn, callsign_prefix=callsign_prefix, start=start)

    agg: dict[int, dict] = {}
    for f in flights:
        cid = f["cid"]
        a = agg.setdefault(cid, {"fs": 0, "st": 0, "dur": 0, "last": None, "last_cs": ""})
        if f.get("source") == "statsim":
            a["st"] += 1
        else:
            a["fs"] += 1
        a["dur"] += f.get("duration_min") or 0
        lt = f.get("logon_time") or ""
        if lt and (a["last"] is None or lt > a["last"]):
            a["last"] = lt
            a["last_cs"] = f.get("callsign") or a["last_cs"]

    # Piloten mit (nur) laufendem offenen Flug ergänzen (erscheinen mit 0 abgeschlossenen Flügen).
    for row in conn.execute(
        "SELECT DISTINCT cid FROM flights WHERE logoff_time IS NULL AND superseded_by IS NULL "
        "AND callsign LIKE ? AND logon_time >= ?",
        (prefix_pat, start),
    ).fetchall():
        agg.setdefault(row[0], {"fs": 0, "st": 0, "dur": 0, "last": None, "last_cs": ""})

    result = []
    for cid, a in agg.items():
        name_row = conn.execute("SELECT name FROM pilots WHERE cid = ?", (cid,)).fetchone()
        name = name_row["name"] if name_row else ""
        live = conn.execute("SELECT callsign FROM live_positions WHERE cid = ?", (cid,)).fetchone()
        last_callsign = (live["callsign"] if live else None) or a["last_cs"] or ""
        result.append({
            "cid": cid,
            "name": name,
            "last_callsign": last_callsign,
            "fs_count": a["fs"],
            "st_count": a["st"],
            "flight_count": a["fs"] + a["st"],
            "total_duration_min": a["dur"],
            "last_flight": a["last"],
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
    today = date.today()
    start_date = today - timedelta(days=days)
    grouping = "day" if days <= 93 else "month"
    # Gleiches Zeitfenster wie get_stats (rollierend now−days), damit beide Views übereinstimmen.
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Eine Wahrheit: über canonicalize_flights aggregieren (kein eigener Merge-/Dedup-Code mehr).
    flights = canonicalize_flights(conn, callsign_prefix=callsign_prefix, start=start)

    def _period(lt: str) -> str:
        return lt[:10] if grouping == "day" else lt[:7]

    counts: dict[str, int] = {}
    durs: dict[str, int] = {}
    pilots_by_period: dict[str, set] = {}
    for f in flights:
        lt = f.get("logon_time") or ""
        if not lt:
            continue
        p = _period(lt)
        counts[p] = counts.get(p, 0) + 1
        durs[p] = durs.get(p, 0) + (f.get("duration_min") or 0)
        pilots_by_period.setdefault(p, set()).add(f["cid"])

    # Lücken füllen
    periods: list[str] = []
    if grouping == "day":
        cur = start_date
        while cur <= today:
            periods.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
    else:
        y, m = start_date.year, start_date.month
        while date(y, m, 1) <= today:
            periods.append(f"{y:04d}-{m:02d}")
            m += 1
            if m > 12:
                m = 1
                y += 1

    data = [
        {
            "period": p,
            "pilot_count": len(pilots_by_period.get(p, set())),
            "flight_count": counts.get(p, 0),
            "total_duration_min": durs.get(p, 0),
        }
        for p in periods
    ]
    return {"grouping": grouping, "data": data}


# Reconnect-Merge-Parameter (Teil 3): Gap-Fenster + Distanz-Budget.
_RECONNECT_GAP_SAME_FP_MIN = 30   # gleicher Flugplan trägt die Beweislast → großzügig
_RECONNECT_GAP_NO_FP_MIN = 15     # ein Segment ohne FP → enger + Geo-Budget
_MAX_GS_KT = 600.0                # Deckelung der plausiblen Geschwindigkeit
_BUDGET_MARGIN_NM = 10.0          # Toleranz auf das Distanz-Budget
_DIRECTION_TOLERANCE_KM = 20.0    # Toleranz der Richtungsprüfung (Fortschritt Richtung Ziel)


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


def _last_pos(
    conn: sqlite3.Connection, cid: int, logon: str, logoff: str
) -> tuple[float, float] | None:
    """Letzte GPS-Position eines Fluges aus position_history."""
    row = conn.execute(
        "SELECT latitude, longitude FROM position_history "
        "WHERE cid=? AND ts>=? AND ts<=? ORDER BY ts DESC LIMIT 1",
        (cid, logon, logoff),
    ).fetchone()
    return (row[0], row[1]) if row else None


def _segments_continuous(
    conn: sqlite3.Connection, earlier: dict, later: dict, gap_min: float
) -> bool:
    """True wenn 'later' geografisch plausibel an 'earlier' anschließt (Reconnect).

    Distanz-Budget: der Abstand zwischen der letzten Position von 'earlier' und der ersten
    Position von 'later' darf höchstens das in der Lücke zurücklegbare Budget betragen
    (gap × Vmax + Marge) — löst den Fall „Pilot 10 Min ohne Netz, Sim fliegt weiter".
    Richtung: 'later' soll nicht deutlich weiter vom Ziel entfernt sein als das Ende von
    'earlier'. Fallback True, wenn keine Positionsdaten vorhanden sind.
    """
    from app.geo import haversine, icao_to_coords
    cid = earlier.get("cid") or later.get("cid")
    if cid is None:
        return True
    last = _last_pos(conn, int(cid), earlier.get("logon_time") or "", earlier.get("logoff_time") or "")
    first = _first_pos(
        conn, int(cid), later.get("logon_time") or "",
        later.get("logoff_time") or "9999-12-31T23:59:59Z",
    )
    if last is None or first is None:
        return True  # keine Daten → permissiv (Flugplan/Window haben bereits gefiltert)
    gap_nm = haversine(last[0], last[1], first[0], first[1]) / 1.852
    budget_nm = (max(gap_min, 0.0) / 60.0) * _MAX_GS_KT + _BUDGET_MARGIN_NM
    if gap_nm > budget_nm:
        return False
    arr = later.get("arrival") or earlier.get("arrival") or ""
    arr_coords = icao_to_coords(arr) if arr else None
    if arr_coords is not None:
        d_last = haversine(last[0], last[1], arr_coords[0], arr_coords[1])
        d_first = haversine(first[0], first[1], arr_coords[0], arr_coords[1])
        if d_first > d_last + _DIRECTION_TOLERANCE_KM:
            return False  # 'later' weiter vom Ziel weg → kein Fortschritt → kein Reconnect
    return True


def merge_fragmented_flights(
    flights: list[dict],
    gap_minutes: int = 5,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """Merge consecutive same-callsign flights where one lacks a flight plan.

    Handles: pilot connects without FP (DEP/ARR empty), briefly disconnects,
    reconnects with FP. FriesenSpy records two entries; this merges them into one.
    Conditions: same callsign, exactly one has no DEP/ARR (or both same DEP+ARR),
    and gap within the per-case window (same-FP ≤ 30 min, no-FP ≤ 15 min). With conn:
    additional geo-continuity check (distance budget + direction) gegen das Nachbarsegment.
    `gap_minutes` ist nur noch eine untere Schranke/Fallback — die Obergrenze richtet sich
    nach Flugplan-Gleichheit (siehe _RECONNECT_GAP_*).
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
                close = False
                gap = None
                curr_loff = curr.get('logoff_time')
                if curr_loff:
                    try:
                        gap = (_parse_iso(nxt['logon_time']) - _parse_iso(curr_loff)).total_seconds() / 60
                    except Exception:
                        gap = None
                if gap is not None:
                    # Flugplan = Hauptsignal: gleicher FP → großzügiges Fenster; sonst enger.
                    window = _RECONNECT_GAP_SAME_FP_MIN if same_fp else _RECONNECT_GAP_NO_FP_MIN
                    close = -2 <= gap <= window
                    # Geo-Kontinuität (Distanz-Budget + Richtung) gegen das Nachbarsegment.
                    if close and conn is not None:
                        close = _segments_continuous(conn, curr, nxt, gap)
                if close:
                    fp = nxt if curr_no_fp else curr
                    merged = dict(fp)
                    merged['logon_time']   = min(t for t in [curr['logon_time'],  nxt['logon_time']]  if t)
                    # Wenn nxt noch aktiv ist (logoff_time = None), bleibt der Merge ebenfalls aktiv
                    _c_loff = curr.get('logoff_time')
                    _n_loff = nxt.get('logoff_time')
                    merged['logoff_time']  = max(_c_loff, _n_loff) if _c_loff and _n_loff else None
                    merged['duration_min'] = (curr.get('duration_min') or 0) + (nxt.get('duration_min') or 0)
                    merged['distance_nm']  = (curr.get('distance_nm')  or 0) + (nxt.get('distance_nm')  or 0)
                    merged['block_min']    = (curr.get('block_min')    or 0) + (nxt.get('block_min')    or 0)
                    result.append(merged)
                    i += 2
                    continue
        result.append(curr)
        i += 1
    return result


def _dedup_statsim_against_fs(
    fs_flights: list[dict], statsim_flights: list[dict]
) -> list[dict]:
    """StatSim-Flüge zurückgeben, die NICHT bereits durch einen FriesenSpy-Flug abgedeckt sind.

    Abgedeckt = (a) StatSim-Logon liegt innerhalb eines FS-Fensters [logon, logoff], oder
    (b) gleiche Strecke und FS-Logon bis 10 Min nach StatSim (Flugplanwechsel nach Connect).
    Eine Stelle für die Regel — von canonicalize_flights und den Endpoints gemeinsam genutzt.
    """
    def _to_dt(s: str | None) -> datetime | None:
        try:
            return datetime.fromisoformat((s or "")[:19].rstrip("Z") + "+00:00")
        except Exception:
            return None

    out: list[dict] = []
    for f in statsim_flights:
        lt = (f.get("logon_time") or "")[:16]
        st_dt = _to_dt(f.get("logon_time"))
        st_dep = f.get("departure") or ""
        st_arr = f.get("arrival") or ""
        covered = False
        for fs in fs_flights:
            if not (fs.get("logon_time") and fs.get("logoff_time")):
                continue
            if fs["logon_time"][:16] <= lt <= fs["logoff_time"][:16]:
                covered = True
                break
            if st_dep and st_arr and st_dep == (fs.get("departure") or "") and st_arr == (fs.get("arrival") or ""):
                fs_dt = _to_dt(fs["logon_time"])
                if st_dt and fs_dt and 0 <= (fs_dt - st_dt).total_seconds() <= 600:
                    covered = True
                    break
        if not covered:
            out.append(f)
    return out


def canonicalize_flights(
    conn: sqlite3.Connection,
    *,
    cids: list[int] | None = None,
    callsign_prefix: str = "FRS",
    start: str | None = None,
    end: str | None = None,
    include_statsim: bool = True,
) -> list[dict]:
    """Die EINZIGE Wahrheit für „echte Flüge": gemergt, dedupliziert, ghost-gefiltert.

    Liefert eine Liste von Flug-Dicts (absteigend nach logon_time) mit Feld `source`
    ('friesenspy' | 'statsim'). FriesenSpy-Flüge: nur aktive (superseded_by IS NULL),
    abgeschlossene; Fragmente/Reconnects via merge_fragmented_flights zusammengeführt;
    Test-Connects (≤0.5 nm und ≤5 min) verworfen. StatSim: nur Einträge, die NICHT bereits
    durch einen FriesenSpy-Flug abgedeckt sind.

    Alle Views (Statistik, Events, Piloten-Detail) nutzen diese Funktion → identische Zahlen.
    `start`/`end` filtern nach logon_time (ISO8601 UTC). `cids` schränkt auf Piloten ein.
    """
    prefix_pat = callsign_prefix + "%"

    fs_where = ["superseded_by IS NULL", "logoff_time IS NOT NULL", "callsign LIKE ?"]
    fs_params: list = [prefix_pat]
    if cids:
        fs_where.append("cid IN (%s)" % ",".join("?" * len(cids)))
        fs_params += list(cids)
    if start:
        fs_where.append("logon_time >= ?")
        fs_params.append(start)
    if end:
        fs_where.append("logon_time <= ?")
        fs_params.append(end)
    rows = conn.execute(
        "SELECT id, cid, callsign, aircraft_short AS aircraft, departure, arrival, "
        "logon_time, logoff_time, duration_min, distance_nm, block_min, route, remarks, "
        "cruise_altitude, cruise_tas, flight_rules, aircraft_icao, alternate, "
        "deptime, enroute_time, fuel_time FROM flights WHERE "
        + " AND ".join(fs_where) + " ORDER BY cid, logon_time",
        fs_params,
    ).fetchall()

    raw_by_cid: dict[int, list[dict]] = {}
    for r in rows:
        raw_by_cid.setdefault(r["cid"], []).append(dict(r))

    fs_by_cid: dict[int, list[dict]] = {}
    result: list[dict] = []
    for cid, flights in raw_by_cid.items():
        # Defensive Dedup gegen exakte (logon,dep,arr)-Wiederholungen (superseded greift bereits).
        seen: set[tuple] = set()
        dd: list[dict] = []
        for f in flights:
            k = (f.get("logon_time"), f.get("departure") or "", f.get("arrival") or "")
            if k not in seen:
                seen.add(k)
                dd.append(f)
        merged = merge_fragmented_flights(dd, conn=conn)
        merged = [
            f for f in merged
            if (f.get("distance_nm") or 0) > 0.5 or (f.get("duration_min") or 0) > 5
        ]
        fs_by_cid[cid] = merged
        for f in merged:
            result.append({"source": "friesenspy", **f})

    if include_statsim:
        sc_where = ["logon_time != ''", "logoff_time IS NOT NULL", "duration_min > 5", "callsign LIKE ?"]
        sc_params: list = [prefix_pat]
        if cids:
            sc_where.append("cid IN (%s)" % ",".join("?" * len(cids)))
            sc_params += list(cids)
        if start:
            sc_where.append("logon_time >= ?")
            sc_params.append(start)
        if end:
            sc_where.append("logon_time <= ?")
            sc_params.append(end)
        sc_rows = conn.execute(
            "SELECT statsim_id, cid, callsign, departure, arrival, aircraft, "
            "logon_time, logoff_time, duration_min FROM statsim_cache WHERE "
            + " AND ".join(sc_where) + " ORDER BY cid, logon_time",
            sc_params,
        ).fetchall()
        sc_by_cid: dict[int, list[dict]] = {}
        for r in sc_rows:
            sc_by_cid.setdefault(r["cid"], []).append(dict(r))
        for cid, st_flights in sc_by_cid.items():
            for f in _dedup_statsim_against_fs(fs_by_cid.get(cid, []), st_flights):
                result.append({"source": "statsim", "id": None, **f})

    result.sort(key=lambda x: x.get("logon_time") or "", reverse=True)
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
               departure, arrival, logon_time, logoff_time, duration_min, distance_nm, block_min,
               route, remarks, cruise_altitude, cruise_tas, flight_rules, aircraft_icao, alternate,
               deptime, enroute_time, fuel_time
        FROM flights
        WHERE cid = ?
          AND logoff_time IS NOT NULL
          AND superseded_by IS NULL
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


def get_calendar_events(conn: sqlite3.Connection, days_back: int = 365) -> list[dict]:
    """FriesenEvents der letzten N Tage, neueste zuerst."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT uid, summary, dtstart, dtend, location FROM calendar_events "
        "WHERE dtstart >= ? AND dtstart <= ? ORDER BY dtstart DESC",
        (cutoff, now_str),
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
