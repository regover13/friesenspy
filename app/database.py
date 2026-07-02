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

CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
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
    uid       TEXT PRIMARY KEY,
    summary   TEXT,
    dtstart   TEXT,
    dtend     TEXT,
    location  TEXT,
    route     TEXT,
    is_bummel INTEGER DEFAULT 0,
    is_transport INTEGER DEFAULT 0
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

CREATE TABLE IF NOT EXISTS ts_consent (
    frs        TEXT PRIMARY KEY,
    visibility TEXT DEFAULT 'everyone',
    allowlist  TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS bummel_races (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT,
    route          TEXT,                 -- CSV der Streckenflugplätze
    dtstart        TEXT,
    dtend          TEXT,                 -- effektiv (Mitternacht-Default bereits angewandt)
    radius_km      REAL DEFAULT 10,
    source         TEXT,                 -- 'calendar' | 'manual'
    calendar_uid   TEXT UNIQUE,          -- NULL für manuelle Rennen
    revealed_at    TEXT,                 -- gesetzt = Ergebnisse enthüllt (latchend)
    created_at     TEXT,
    push_enabled   INTEGER DEFAULT 1,    -- Push-Benachrichtigungen für dieses Rennen aktiv
    started_at     TEXT,                 -- Latch: gesetzt wenn erster Pilot losgeflogen ist
    reveal_suppressed INTEGER DEFAULT 0  -- 1 = manuell verborgen, übersteuert den Auto-Reveal
);

CREATE TABLE IF NOT EXISTS bummel_overrides (
    race_id          INTEGER,
    cid              INTEGER,
    action           TEXT,              -- 'exclude' | 'disqualify' | 'winner' | 'manual'
    manual_total_min INTEGER,           -- nur für action='manual'
    note             TEXT,
    updated_at       TEXT,
    PRIMARY KEY(race_id, cid)
);

CREATE TABLE IF NOT EXISTS event_reminders_sent (
    uid     TEXT PRIMARY KEY,           -- calendar_events.uid, für den die ~1h-Erinnerung lief
    sent_at TEXT
);

CREATE TABLE IF NOT EXISTS transport_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    route          TEXT NOT NULL,        -- CSV der Streckenflugplätze (wie bummel_races.route)
    destination    TEXT,                 -- Ziel-ICAO: nur Flüge HIERHIN laden Fracht (Rückflug leer)
    dtstart        TEXT NOT NULL,
    dtend          TEXT NOT NULL,        -- effektiv (Mitternacht-Default bereits angewandt)
    source         TEXT,                 -- 'calendar' | 'manual'
    calendar_uid   TEXT UNIQUE,          -- NULL für manuelle Events
    push_enabled   INTEGER DEFAULT 1,
    started_at     TEXT,                 -- Latch: erster qualifizierender Flug
    goal_reached_at TEXT,                -- Latch: Manifest voll
    summarized_at  TEXT,                 -- Latch: Abschluss-Push gesendet
    summary_quip   TEXT,                 -- lustige Tagesend-Zusammenfassung (KI, Phase 2)
    radius_km       REAL,                 -- Erkennungs-Umkreis km; NULL = Default 10
    created_at     TEXT
);

CREATE TABLE IF NOT EXISTS transport_cargo (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id  INTEGER NOT NULL,          -- REFERENCES transport_events(id)
    position  INTEGER NOT NULL,          -- Beladungsreihenfolge
    name      TEXT NOT NULL,             -- Frachtart, z. B. "Fischbrötchen"
    target_kg REAL NOT NULL,
    emoji     TEXT,                      -- Snapshot aus dem Katalog (für den Feed)
    per_flight_max_kg REAL               -- Obergrenze pro Flug (Co-Load); NULL = keine Kappung
);
CREATE INDEX IF NOT EXISTS idx_transport_cargo_event ON transport_cargo(event_id);

CREATE TABLE IF NOT EXISTS cargo_catalog (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    emoji             TEXT,
    per_flight_max_kg REAL,              -- NULL = keine Kappung
    position          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transport_quips (
    event_id   INTEGER NOT NULL,
    flight_key TEXT NOT NULL,            -- "{cid}:{logon_time}" (stabil)
    quip       TEXT,
    created_at TEXT,
    PRIMARY KEY(event_id, flight_key)
);

CREATE TABLE IF NOT EXISTS transport_live_arrivals (
    cid         INTEGER NOT NULL,
    logon_time  TEXT NOT NULL,
    event_id    INTEGER NOT NULL,
    arrived_at  TEXT NOT NULL,
    PRIMARY KEY (cid, logon_time, event_id)
);

CREATE TABLE IF NOT EXISTS transport_cargo_losses (
    event_id   INTEGER NOT NULL,          -- REFERENCES transport_events(id)
    cid        INTEGER NOT NULL,
    logon_time TEXT NOT NULL,             -- Session des verlorenen Flugs (flight_key = cid:logon)
    kind       TEXT NOT NULL,             -- 'returned' | 'stolen' | 'sunk'
    type_code  TEXT,                      -- Muster; kg werden IMMER live aus aircraft_payloads gerechnet
    callsign   TEXT,
    dep        TEXT,                      -- Abflugplatz (fürs Feed-Rendering)
    end_icao   TEXT,                      -- Landeplatz bei 'returned'/'stolen'; NULL bei 'sunk'
    lost_at    TEXT,
    PRIMARY KEY(event_id, cid, logon_time)
);

CREATE TABLE IF NOT EXISTS aircraft_payloads (
    type_code   TEXT PRIMARY KEY,        -- normalisiert (Uppercase, vor "/" gekürzt), z. B. "C172"
    mtow_kg     REAL,                    -- editierbar, aus Claude vorbefüllt
    empty_kg    REAL,
    fuel_kg     REAL,                    -- Tankinhalt (editierbar) — Default halber Tank
    crew_kg     REAL,                    -- Pilot/Crew (editierbar) — Default 85 kg, zählt nicht als Fracht
    payload_kg  REAL NOT NULL,           -- = max(0, mtow_kg − empty_kg − fuel_kg − crew_kg); direkt überschreibbar
    source      TEXT,                    -- 'manual' | 'llm' | 'default'
    make_model  TEXT,
    updated_at  TEXT
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


def _effective_dtend(dtstart: str, dtend: str | None) -> str:
    """Effektives Renn-Ende. Fehlt ``dtend`` → Mitternacht UTC am Ende des Starttags
    (00:00:00Z des Folgetags). Im Bummel-Kontext läuft alles in Zulu/UTC."""
    if dtend:
        return dtend
    day = _parse_iso(dtstart).date()
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1)
    return midnight.strftime("%Y-%m-%dT%H:%M:%SZ")


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
    # route: CSV aller ICAOs der Strecke; is_bummel: FriesenFliegerBummel erkannt.
    "ALTER TABLE calendar_events ADD COLUMN route TEXT",
    "ALTER TABLE calendar_events ADD COLUMN is_bummel INTEGER DEFAULT 0",
    # is_transport: FriesenKutter-Transportevent (Stichwort "friesenkutter") erkannt.
    "ALTER TABLE calendar_events ADD COLUMN is_transport INTEGER DEFAULT 0",
]

_PUSH_MIGRATIONS = [
    "ALTER TABLE push_subscriptions ADD COLUMN notify_prefiles INTEGER DEFAULT 0",
    "ALTER TABLE push_subscriptions ADD COLUMN notify_ts INTEGER DEFAULT 0",
    "ALTER TABLE push_subscriptions ADD COLUMN ts_self_frs TEXT",
    # notify_events: Erinnerung ~1h vor Events + Bummel-Start/Ergebnis-Pushs (Default aus).
    "ALTER TABLE push_subscriptions ADD COLUMN notify_events INTEGER DEFAULT 0",
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

_BUMMEL_MIGRATIONS = [
    "ALTER TABLE bummel_races ADD COLUMN push_enabled INTEGER DEFAULT 1",
    "ALTER TABLE bummel_races ADD COLUMN started_at TEXT",
    "ALTER TABLE bummel_races ADD COLUMN reveal_suppressed INTEGER DEFAULT 0",
    """CREATE TABLE IF NOT EXISTS bummel_overrides (
        race_id          INTEGER,
        cid              INTEGER,
        action           TEXT,
        manual_total_min INTEGER,
        note             TEXT,
        updated_at       TEXT,
        PRIMARY KEY(race_id, cid)
    )""",
]

_TRANSPORT_MIGRATIONS = [
    # destination: Ziel-ICAO — nur Flüge dorthin laden Fracht (Rückflug leer).
    "ALTER TABLE transport_events ADD COLUMN destination TEXT",
    # crew_kg: Pilot/Crew-Gewicht — zählt nicht als Fracht (payload = mtow − empty − fuel − crew).
    "ALTER TABLE aircraft_payloads ADD COLUMN crew_kg REAL",
    # Phase 2: Fracht-Manifest um Emoji + Co-Load-Kappung, Event um Tagesend-Spruch.
    "ALTER TABLE transport_cargo ADD COLUMN emoji TEXT",
    "ALTER TABLE transport_cargo ADD COLUMN per_flight_max_kg REAL",
    "ALTER TABLE transport_events ADD COLUMN summary_quip TEXT",
    # radius_km: Erkennungs-Umkreis pro Event, z. B. für kurze Strecken wie Wangerooge↔Harle.
    "ALTER TABLE transport_events ADD COLUMN radius_km REAL",
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
        for stmt in _BUMMEL_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        for stmt in _TRANSPORT_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        # Alt-Daten: Suffix stammte aus dem Admin-Vorschlag bis v7.3.x (idempotent).
        try:
            conn.execute(
                "UPDATE aircraft_payloads SET make_model = "
                "REPLACE(make_model, ' · volle Tanks, Pilot abgezogen', '') "
                "WHERE make_model LIKE '%volle Tanks%'"
            )
        except sqlite3.OperationalError:
            pass
        try:
            seed_cargo_catalog(conn)  # Frachtart-Katalog erstbefüllen (idempotent)
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
        # Verwaiste Tracks (A1-Schaden): StatSim-Flug ohne deckenden FS-Flug, aber mit
        # bewegtem GPS-Track → flights-Eintrag aus den echten Belegen rekonstruieren.
        # Defensive Kapselung: die Reparatur ist Komfort — ein Fehler hier darf den
        # App-Start niemals verhindern (Prod-Vorfall 2026-07-01).
        try:
            r = reconstruct_orphaned_flights(conn)
            conn.commit()
            if r:
                _logger.info("Verwaiste Tracks rekonstruiert: %d Flug/Flüge", r)
        except Exception:
            conn.rollback()
            _logger.exception("Track-Rekonstruktion fehlgeschlagen — Start ohne Reparatur")
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


# ---------------------------------------------------------------------------
# App-Settings (generisches Key/Value, z. B. Banner-Auswahl)
# ---------------------------------------------------------------------------

def get_app_setting(conn: sqlite3.Connection, key: str, default=None):
    """Wert einer App-Einstellung lesen; ``default`` falls nicht gesetzt."""
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row is not None else default


def set_app_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """App-Einstellung setzen/überschreiben (kein commit)."""
    conn.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, _now_utc()),
    )


# ---------------------------------------------------------------------------
# Piloten-Verwaltung (Admin)
# ---------------------------------------------------------------------------

def list_pilots(conn: sqlite3.Connection, callsign_prefix: str = "FRS") -> list[dict]:
    """Alle bekannten Piloten (cid, name, added_at, callsigns), nach Name sortiert.

    ``callsigns`` ist die sortierte Liste der distinct Callsigns mit dem Präfix
    ``callsign_prefix``, die diese CID in der ``flights``-Tabelle verwendet hat (leer, wenn keine).
    Macht sichtbar, wenn eine CID mehrere FRS-Tags nutzt.
    """
    rows = conn.execute(
        "SELECT p.cid, p.name, p.added_at, "
        "(SELECT GROUP_CONCAT(DISTINCT f.callsign) FROM flights f "
        " WHERE f.cid = p.cid AND f.callsign LIKE ?) AS callsigns "
        "FROM pilots p ORDER BY p.name COLLATE NOCASE, p.cid",
        (callsign_prefix + "%",),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        cs = d.pop("callsigns") or ""
        d["callsigns"] = sorted(c for c in cs.split(",") if c)
        result.append(d)
    return result


def upsert_pilot(conn: sqlite3.Connection, cid: int, name: str) -> None:
    """Pilot anlegen oder Namen aktualisieren (added_at bleibt beim Update erhalten)."""
    conn.execute(
        "INSERT INTO pilots (cid, name, added_at) VALUES (?, ?, ?) "
        "ON CONFLICT(cid) DO UPDATE SET name = excluded.name",
        (cid, name, _now_utc()),
    )


def delete_pilot(conn: sqlite3.Connection, cid: int) -> None:
    """Pilot aus der pilots-Tabelle entfernen."""
    conn.execute("DELETE FROM pilots WHERE cid = ?", (cid,))


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

    Ist die bestehende Zeile bereits GESCHLOSSEN (Feed-Aussetzer: eine Poll-Runde ohne den
    Piloten → close, nächste Runde wieder da), wird sie RE-GEÖFFNET — dieselbe logon_time
    beweist, dass die Verbindung nie abriss (ein echter Reconnect bekäme eine neue).
    duration/distance/block werden beim endgültigen Close ohnehin neu berechnet.
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
        "SELECT id, logoff_time FROM flights WHERE cid = ? AND logon_time = ? AND superseded_by IS NULL",
        (cid, logon_time),
    ).fetchone()
    if row[1] is not None:  # logoff_time gesetzt → Aussetzer-Close → Session re-öffnen
        conn.execute(
            "UPDATE flights SET logoff_time = NULL, duration_min = NULL, "
            "distance_nm = 0, block_min = NULL WHERE id = ?",
            (row[0],),
        )
    return row[0]  # type: ignore[return-value]


def last_known_aircraft(conn: sqlite3.Connection, cid: int) -> tuple[str, str]:
    """Zuletzt bekanntes Muster eines Piloten aus früheren Flügen: (aircraft_short, aircraft_icao).

    Fallback für Piloten OHNE Flugplan: der öffentliche VATSIM-Feed führt den Flugzeugtyp
    ausschließlich im ``flight_plan`` (C1-Analyse) — wie vatsim-radar erinnern wir uns
    deshalb an das zuletzt gefilte Muster desselben Piloten. ``("", "")`` wenn unbekannt.
    """
    row = conn.execute(
        "SELECT aircraft_short, aircraft_icao FROM flights "
        "WHERE cid = ? AND aircraft_short != '' ORDER BY logon_time DESC LIMIT 1",
        (cid,),
    ).fetchone()
    if row is None:
        return ("", "")
    return (row[0] or "", row[1] or "")


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

# Mindestdauer (Sekunden) einer BELEGTEN Standphase (zusammenhängend groundspeed ≤ _BLOCK_GS_KT
# zwischen zwei Bewegungen), ab der sie NICHT mehr als Blockzeit zählt — Zwischenlandung/
# Abstellen ohne Disconnect. Kürzere Stopps (Rollhalt, Warteschlange) bleiben gate-to-gate
# enthalten. Lücken OHNE Positionsdaten (Feed-Aussetzer) zählen weiterhin voll — abgezogen
# wird nur nachweislicher Stillstand.
_BLOCK_STAND_MIN_SEC = 600


def _block_minutes(
    conn: sqlite3.Connection, cid: int, logon_time: str, logoff_time: str
) -> int:
    """Block-/Bewegungszeit (Minuten): Summe der bewegten Abschnitte (groundspeed > _BLOCK_GS_KT)
    innerhalb [logon, logoff]; belegte Standphasen ≥ _BLOCK_STAND_MIN_SEC zählen nicht
    (Zwischenlandung ohne Disconnect). Keine Bewegung → 0. Gate-to-gate inkl. Taxi/kurzer Halte."""
    return _block_seconds(conn, cid, logon_time, logoff_time) // 60


def _block_seconds(
    conn: sqlite3.Connection, cid: int, logon_time: str, logoff_time: str
) -> int:
    """Block-/Bewegungszeit in SEKUNDEN (sekundengenaue Basis von _block_minutes).

    Summe der Abschnitte zwischen aufeinanderfolgenden bewegten Positionen; liegt zwischen
    zwei Bewegungen eine belegte Standphase ≥ _BLOCK_STAND_MIN_SEC (zusammenhängende Positionen
    mit groundspeed ≤ _BLOCK_GS_KT), wird deren Dauer abgezogen — so zählt die Bodenzeit einer
    Zwischenlandung ohne Disconnect nicht als Blockzeit (Bummel-Gerechtigkeit). Kurze Halte
    bleiben enthalten; Datenlücken ohne Stillstands-Beleg zählen voll. Wird auch für die
    Bummel-Wertung gebraucht (Abstand zum Schnitt sekundengenau). 0 ohne bewegte Position.
    """
    rows = conn.execute(
        "SELECT ts, groundspeed FROM position_history "
        "WHERE cid = ? AND ts >= ? AND ts <= ? ORDER BY ts",
        (cid, logon_time, logoff_time),
    ).fetchall()
    total = 0.0
    prev_move = None           # Zeitpunkt der letzten bewegten Position
    stand_first = stand_last = None  # belegter Stillstand seit prev_move
    for ts, gs in rows:
        if gs is None:
            continue  # kein Beleg — weder Bewegung noch Stillstand
        try:
            t = _parse_iso(ts)
        except Exception:
            continue
        if gs > _BLOCK_GS_KT:
            if prev_move is not None:
                gap = (t - prev_move).total_seconds()
                stand = (
                    (stand_last - stand_first).total_seconds()
                    if stand_first is not None else 0.0
                )
                total += gap - stand if stand >= _BLOCK_STAND_MIN_SEC else gap
            prev_move = t
            stand_first = stand_last = None
        elif prev_move is not None:
            if stand_first is None:
                stand_first = t
            stand_last = t
    return max(0, int(total))


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
      E) Selbstheilung: block_min > duration_min (unmöglich) → block mit dem gespeicherten
         Fenster neu berechnen. C und D rechnen block_min bei Fenster-Korrekturen stets mit.

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
            new_block = _block_minutes(conn, cid, logon, new_logoff)
            conn.execute(
                "UPDATE flights SET logoff_time=?, duration_min=?, distance_nm=?, block_min=? WHERE id=?",
                (new_logoff, new_dur, new_dist, new_block, fid),
            )

    # D) StatSim-Backstop für weiterhin grob unplausible Dauern
    if statsim_correct:
        for fid, cid, logon, dur in conn.execute(
            "SELECT id, cid, logon_time, duration_min FROM flights "
            "WHERE superseded_by IS NULL AND logoff_time IS NOT NULL"
        ).fetchall():
            # MAX statt LIMIT-1-Zufall: StatSim legt PRO FLUG eine Zeile mit der SESSION-
            # Anmeldung als logon_time an (duration = arrived − loggedOn) — bei Multi-Leg-
            # Sessions matchen mehrere Zeilen dieselbe Minute. Die längste (= späteste
            # Landung) ist die beste Untergrenze der Session-Dauer; die des ersten Beins
            # würde eine legitime Multi-Leg-Session fälschlich schrumpfen.
            sc = conn.execute(
                "SELECT MAX(duration_min) FROM statsim_cache "
                "WHERE cid=? AND duration_min IS NOT NULL "
                "AND substr(logon_time,1,16)=substr(?,1,16)",
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
                new_block = _block_minutes(conn, cid, logon, new_logoff)
                conn.execute(
                    "UPDATE flights SET logoff_time=?, duration_min=?, distance_nm=?, block_min=? WHERE id=?",
                    (new_logoff, st_dur, new_dist, new_block, fid),
                )

    # E) Selbstheilung unmöglicher Blockzeiten: block_min > duration_min kann nicht sein
    # (Blockzeit liegt in [logon, logoff]) — entsteht, wenn ein früherer Schritt/Codestand
    # logoff/duration korrigierte, ohne block mitzuziehen. Mit dem GESPEICHERTEN Fenster
    # neu berechnen.
    for fid, cid, logon, logoff in conn.execute(
        "SELECT id, cid, logon_time, logoff_time FROM flights "
        "WHERE superseded_by IS NULL AND logoff_time IS NOT NULL "
        "AND block_min IS NOT NULL AND duration_min IS NOT NULL AND block_min > duration_min"
    ).fetchall():
        conn.execute(
            "UPDATE flights SET block_min=? WHERE id=?",
            (_block_minutes(conn, cid, logon, logoff), fid),
        )

    return marked


# Track-Rekonstruktions-Parameter (siehe reconstruct_orphaned_flights):
_RECONSTRUCT_MARGIN_MIN = 10        # Taxi-in-Rand nach der StatSim-Landezeit
_RECONSTRUCT_COVER_MARGIN_MIN = 5   # Toleranz „Landung liegt in einem FS-Fenster" (gedeckt)
_RECONSTRUCT_STAND_SEC = 300        # belegte Standphase, die zwei Beine einer Session trennt
_RECONSTRUCT_MAX_LOOKBACK_H = 3     # Max-Rückblick vor der Landung ohne Session-Grenze


def reconstruct_orphaned_flights(
    conn: sqlite3.Connection, *, cids: list[int] | None = None
) -> int:
    """Verwaiste GPS-Tracks wieder mit einer flights-Zeile versehen (A1-Schadensreparatur).

    Fall (Live-Test 2026-07-01, Reiner cid 1031301): ein Feed-Aussetzer schloss die laufende
    Session; Folgeflüge derselben Verbindung liefen nur noch in position_history — StatSim
    kennt den Flug, FriesenSpy besitzt den Track, aber es existiert kein flights-Eintrag.

    Anker ist die LANDEZEIT (``logoff_time`` = StatSims ``arrived``): StatSims ``loggedOn``
    ist die SESSION-Anmeldung und bei mehreren Flügen einer Verbindung für alle gleich —
    als Flugbeginn unbrauchbar (der zweite Flug „18:18–18:36" steht im Cache als
    17:04→18:36). Kandidat ist jede StatSim-Landung mit Strecke, die in KEINEM aktiven
    FriesenSpy-Fenster (± _RECONSTRUCT_COVER_MARGIN_MIN) liegt. Der Flugbeginn wird aus dem
    Track abgeleitet: Rückwärtssuche von der Landung zur letzten belegten Standphase
    (≥ _RECONSTRUCT_STAND_SEC zusammenhängend ≤ _BLOCK_GS_KT) — dort begann der Flug; ohne
    Stand-Beleg ab der vorigen Session (gedeckelt auf _RECONSTRUCT_MAX_LOOKBACK_H). Das
    Fenster endet Landung + _RECONSTRUCT_MARGIN_MIN (Taxi-in), gedeckelt auf die nächste
    Session. Nur mit belegter Flugbewegung (≥ 2 Positionen ≥ 40 kt); Dauer/Distanz/Block
    kommen aus den echten Positionsdaten. Idempotent: einmal rekonstruiert deckt die neue
    Zeile die Landung. ``cids`` begrenzt den Lauf auf einzelne Piloten (Aufruf direkt nach
    einem StatSim-Refresh). Gibt die Anzahl neu angelegter Flüge zurück; committet NICHT.
    """
    import logging as _log
    log = _log.getLogger(__name__)
    created = 0
    # Eigener Cursor mit Row-Factory: init_db ruft mit einer ROHEN Connection (Tupel-Zeilen)
    # auf — benannter Zugriff muss unabhängig vom Aufrufer funktionieren.
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    st_where = (
        "logoff_time IS NOT NULL AND logoff_time != '' "
        "AND departure != '' AND arrival != ''"
    )
    st_params: list = []
    if cids:
        st_where += " AND cid IN (%s)" % ",".join("?" * len(cids))
        st_params = list(cids)
    st_rows = cur.execute(
        "SELECT cid, callsign, departure, arrival, aircraft, logon_time, logoff_time "
        "FROM statsim_cache WHERE " + st_where + " ORDER BY cid, logoff_time",
        st_params,
    ).fetchall()
    for st in st_rows:
        cid, arrived = st["cid"], st["logoff_time"]
        # Laufende Session, die diese Landung enthalten kann → Finger weg.
        open_row = conn.execute(
            "SELECT 1 FROM flights WHERE cid=? AND superseded_by IS NULL "
            "AND logoff_time IS NULL AND logon_time <= ? LIMIT 1",
            (cid, arrived),
        ).fetchone()
        if open_row:
            continue
        # Gedeckt: die Landung liegt (± Toleranz) in einem aktiven FS-Fenster. Die Toleranz
        # fängt den Normalfall ab, dass StatSims arrived Sekunden NACH dem FS-Logoff
        # (= letzte Position) liegt.
        fs = [dict(r) for r in cur.execute(
            "SELECT logon_time, logoff_time FROM flights "
            "WHERE cid=? AND superseded_by IS NULL AND logoff_time IS NOT NULL",
            (cid,),
        ).fetchall()]
        cover = _RECONSTRUCT_COVER_MARGIN_MIN / 60.0
        if any(
            _shift_iso(f["logon_time"], hours=-cover) <= arrived
            <= _shift_iso(f["logoff_time"], hours=cover)
            for f in fs
        ):
            continue
        # Fensterende: Landung + Taxi-Rand, gedeckelt auf die nächste Session.
        hi = _shift_iso(arrived, hours=_RECONSTRUCT_MARGIN_MIN / 60.0)
        next_logon = min((f["logon_time"] for f in fs if f["logon_time"] > arrived), default=None)
        if next_logon and next_logon < hi:
            hi = next_logon
        # Harte Untergrenze: Ende der vorigen Session, gedeckelt auf einen Max-Rückblick.
        lo = _shift_iso(arrived, hours=-_RECONSTRUCT_MAX_LOOKBACK_H)
        prev_logoff = max((f["logoff_time"] for f in fs if f["logoff_time"] <= arrived), default=None)
        if prev_logoff and prev_logoff > lo:
            lo = prev_logoff
        # Flugbeginn: Rückwärtssuche — die letzte belegte Standphase VOR der Landung trennt
        # diesen Flug vom vorherigen Bein derselben verwaisten Session.
        samples = conn.execute(
            "SELECT ts, groundspeed FROM position_history "
            "WHERE cid=? AND ts>? AND ts<? ORDER BY ts",
            (cid, lo, hi),
        ).fetchall()
        if not samples:
            continue
        cut = None
        stand_first = stand_last = None
        for ts, gs in samples:
            if gs is None:
                continue
            if gs > _BLOCK_GS_KT:
                if (
                    stand_first is not None and ts <= arrived
                    and (_parse_iso(stand_last) - _parse_iso(stand_first)).total_seconds()
                    >= _RECONSTRUCT_STAND_SEC
                ):
                    cut = ts
                stand_first = stand_last = None
            else:
                if stand_first is None:
                    stand_first = ts
                stand_last = ts
        start = cut or samples[0][0]
        # Beleg: das Fenster muss echte Flugbewegung zeigen (kein Taxi-/Steh-Ghost).
        airborne = conn.execute(
            "SELECT COUNT(*) FROM position_history "
            "WHERE cid=? AND ts>=? AND ts<? AND groundspeed >= 40",
            (cid, start, hi),
        ).fetchone()[0]
        if airborne < 2:
            continue
        bounds = conn.execute(
            "SELECT MIN(ts), MAX(ts) FROM position_history WHERE cid=? AND ts>=? AND ts<?",
            (cid, start, hi),
        ).fetchone()
        logon_rec, logoff_rec = bounds[0], bounds[1]
        if not logon_rec or not logoff_rec or logon_rec >= logoff_rec:
            continue
        clash = conn.execute(
            "SELECT 1 FROM flights WHERE cid=? AND logon_time=? AND superseded_by IS NULL",
            (cid, logon_rec),
        ).fetchone()
        if clash:
            continue
        duration = max(0, int((_parse_iso(logoff_rec) - _parse_iso(logon_rec)).total_seconds() / 60))
        distance = _gps_distance_nm(conn, cid, logon_rec, logoff_rec)
        block = _block_minutes(conn, cid, logon_rec, logoff_rec)
        conn.execute(
            "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, "
            "logon_time, logoff_time, duration_min, distance_nm, block_min) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, st["callsign"] or "", st["aircraft"] or "", st["departure"], st["arrival"],
             logon_rec, logoff_rec, duration, distance, block),
        )
        created += 1
        log.info(
            "Verwaister Track rekonstruiert: cid=%s %s %s→%s [%s, %s] %d nm",
            cid, st["callsign"], st["departure"], st["arrival"], logon_rec, logoff_rec, distance,
        )
    return created


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
# „Fertig gelandet": das frühere Segment ist nachweislich GEFLOGEN und endete AM BODEN →
# der Flug ist abgeschlossen, ein späteres Segment ist kein Reconnect dieses Fluges mehr —
# egal, WO gelandet wurde (deckt Landung am FP-Ziel UND den Rückflug mit stehengebliebenem
# FP ab, der wieder am FP-Start landet — Live-Test 2026-07-01, FRS102).
_LANDED_MAX_GS_KT = 40.0          # letzte Position darunter = ausgerollt/am Boden
_FLOWN_MIN_GS_KT = 60.0           # mind. eine Position darüber = Segment ist wirklich geflogen


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
    Fertig gelandet: ist 'earlier' nachweislich GEFLOGEN (Position ≥ _FLOWN_MIN_GS_KT) und
    endete AM BODEN (letzte Position ≤ _LANDED_MAX_GS_KT), ist der Flug abgeschlossen —
    'later' ist dann ein NEUER Flug, kein Reconnect. Gilt unabhängig vom Landeort: deckt die
    Landung am FP-Ziel ebenso ab wie den Rückflug mit stehengebliebenem FP, der wieder am
    FP-Start landet (dort griffe die Richtungsprüfung strukturell nie, weil der Folgeflug ja
    Richtung FP-Ziel „Fortschritt" macht). Reine Boden-Segmente (nie geflogen, z. B.
    Gate-Reconnect vor dem Neu-Filen) mergen weiterhin.
    Richtung: 'later' soll nicht deutlich weiter vom Ziel entfernt sein als das Ende von
    'earlier'. Fallback True, wenn keine Positionsdaten vorhanden sind.
    """
    from app.geo import haversine, icao_to_coords
    cid = earlier.get("cid") or later.get("cid")
    if cid is None:
        return True
    last_row = conn.execute(
        "SELECT latitude, longitude, groundspeed FROM position_history "
        "WHERE cid=? AND ts>=? AND ts<=? ORDER BY ts DESC LIMIT 1",
        (int(cid), earlier.get("logon_time") or "", earlier.get("logoff_time") or ""),
    ).fetchone()
    last = (last_row[0], last_row[1]) if last_row else None
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
    last_gs = last_row[2]
    if last_gs is not None and last_gs <= _LANDED_MAX_GS_KT:
        flew = conn.execute(
            "SELECT 1 FROM position_history "
            "WHERE cid=? AND ts>=? AND ts<=? AND groundspeed >= ? LIMIT 1",
            (int(cid), earlier.get("logon_time") or "", earlier.get("logoff_time") or "",
             _FLOWN_MIN_GS_KT),
        ).fetchone()
        if flew is not None:
            return False  # 'earlier' ist geflogen und gelandet → abgeschlossen → kein Reconnect
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
    Ghosts verworfen: Test-Connects (≤0.5 nm und ≤5 min) sowie belegte Steh-Sessions
    (keine Strecke, Blockzeit 0, Track vorhanden — verbunden rumstehen ist kein Flug;
    Altflüge ohne Positionsdaten bleiben). StatSim: nur Einträge, die NICHT bereits
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

        def _is_ghost(f: dict) -> bool:
            # Echte Strecke → Flug.
            if (f.get("distance_nm") or 0) > 0.5:
                return False
            # Kurz-Connect ohne Strecke → Test-Connect.
            if (f.get("duration_min") or 0) <= 5:
                return True
            # Länger verbunden, keine Strecke: eine Steh-Session ist KEIN Flug — aber nur
            # verwerfen, wenn der Track den Stillstand BELEGT (Positionen vorhanden,
            # Blockzeit 0). Altflüge ohne Positionsdaten bleiben (im Zweifel echter Flug).
            if (f.get("block_min") or 0) > 0:
                return False
            lo, lf = f.get("logon_time"), f.get("logoff_time")
            if not lo or not lf:
                return False
            has_pos = conn.execute(
                "SELECT 1 FROM position_history WHERE cid=? AND ts>=? AND ts<=? LIMIT 1",
                (cid, lo, lf),
            ).fetchone()
            return has_pos is not None

        merged = [f for f in merged if not _is_ghost(f)]
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


# Umkreis (km), in dem die erste/letzte GPS-Position einem Streckenflugplatz zugeordnet wird.
# Großzügig genug für Start/Landung (inkl. kurzem Endanflug bei Disconnect), aber klar unter
# dem typischen Abstand zwischen zwei Bummel-Flugplätzen — `_nearest_airport` nimmt ohnehin
# den nächstgelegenen, sodass eng beieinanderliegende Inselplätze korrekt getrennt werden.
_BUMMEL_AIRPORT_RADIUS_KM = 10.0

# Vorlauf (Stunden), mit dem Flüge VOR Event-Start geladen werden, damit Frühstarter erfasst
# werden (Flug beginnt vor dtstart, ist aber im Eventfenster noch unterwegs). Großzügig genug
# für jeden realistischen GA-Flug, begrenzt aber die geladene Datenmenge.
_BUMMEL_EARLY_START_LOOKBACK_H = 12


def _shift_iso(ts: str, *, hours: float) -> str:
    """ISO8601-Zeitstempel (…Z) um ``hours`` verschieben; bei Parse-Fehler unverändert zurück."""
    from datetime import datetime, timedelta
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return ts
    return (dt + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nearest_airport(
    coords_map: dict[str, tuple[float, float] | None],
    pos: tuple[float, float] | None,
    radius_km: float,
) -> str | None:
    """Nächstgelegener Flugplatz aus ``coords_map`` zu ``pos`` innerhalb ``radius_km`` — sonst None."""
    if pos is None:
        return None
    from app.geo import haversine
    best, best_km = None, radius_km
    for icao, c in coords_map.items():
        if c is None:
            continue
        d = haversine(pos[0], pos[1], c[0], c[1])
        if d <= best_km:
            best, best_km = icao, d
    return best


def _bummel_anyone_in_progress(
    conn: sqlite3.Connection,
    route_icaos: list[str],
    radius_km: float,
    *,
    started_before: str | None = None,
    callsign_prefix: str = "FRS",
) -> bool:
    """True, wenn gerade noch ein Teilnehmer auf der Tour unterwegs ist (Enthüllung verschieben).

    Ein „Nachzügler" = offener Flug (``logoff_time IS NULL``), dessen Start an einem
    Streckenflugplatz liegt (GPS-erste-Position im Umkreis, Fallback Flugplan-DEP). Mit
    ``started_before`` werden nur Flüge berücksichtigt, die vor diesem Zeitpunkt begonnen haben
    (Nachzügler aus dem Rennen, keine verspäteten Neu-Connects nach dtend).
    """
    from app.geo import icao_to_coords
    route_set = {(c or "").strip().upper() for c in route_icaos if c and c.strip()}
    coords_map = {icao: icao_to_coords(icao) for icao in route_set}
    rows = conn.execute(
        "SELECT cid, departure, logon_time FROM flights "
        "WHERE logoff_time IS NULL AND superseded_by IS NULL AND callsign LIKE ?",
        (callsign_prefix + "%",),
    ).fetchall()
    for r in rows:
        if started_before and (r["logon_time"] or "") > started_before:
            continue
        first = _first_pos(conn, int(r["cid"]), r["logon_time"] or "", "9999-12-31T23:59:59Z")
        dep = _nearest_airport(coords_map, first, radius_km) or (r["departure"] or "").strip().upper()
        if dep in route_set:
            return True
    return False


def update_bummel_reveals(
    conn: sqlite3.Connection, now: str, *, callsign_prefix: str = "FRS"
) -> list[int]:
    """Enthüllungs-Latch: enthüllt Rennen, deren dtend erreicht ist und bei denen niemand mehr
    unterwegs ist. Gibt die IDs der in diesem Lauf neu enthüllten Rennen zurück (für Push)."""
    revealed: list[int] = []
    for race in list_bummel_races(conn):
        if race["revealed_at"] or race.get("reveal_suppressed"):
            continue  # bereits enthüllt ODER vom Admin manuell verborgen → nicht (wieder) enthüllen
        dtend = race["dtend"] or ""
        if not dtend or now < dtend:
            continue
        route_icaos = [c for c in (race["route"] or "").split(",") if c.strip()]
        if _bummel_anyone_in_progress(
            conn, route_icaos, race["radius_km"] or _BUMMEL_AIRPORT_RADIUS_KM,
            started_before=dtend, callsign_prefix=callsign_prefix,
        ):
            continue
        set_bummel_revealed(conn, race["id"], now)
        revealed.append(race["id"])
    conn.commit()
    return revealed


def bummel_open_starters(
    conn: sqlite3.Connection,
    route_icaos: list[str],
    radius_km: float,
    *,
    callsign_prefix: str = "FRS",
) -> list[dict]:
    """Offene Flüge, deren Start an einem Streckenflugplatz liegt — je Eintrag {cid, callsign,
    moved}. ``moved`` = es gibt schon eine Position mit groundspeed > _BLOCK_GS_KT (Blockzeit
    hat begonnen)."""
    from app.geo import icao_to_coords
    route_set = {(c or "").strip().upper() for c in route_icaos if c and c.strip()}
    coords_map = {icao: icao_to_coords(icao) for icao in route_set}
    rows = conn.execute(
        "SELECT cid, callsign, departure, logon_time FROM flights "
        "WHERE logoff_time IS NULL AND superseded_by IS NULL AND callsign LIKE ?",
        (callsign_prefix + "%",),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        first = _first_pos(conn, int(r["cid"]), r["logon_time"] or "", "9999-12-31T23:59:59Z")
        dep = _nearest_airport(coords_map, first, radius_km) or (r["departure"] or "").strip().upper()
        if dep not in route_set:
            continue
        moved = conn.execute(
            "SELECT 1 FROM position_history WHERE cid = ? AND ts >= ? AND groundspeed > ? LIMIT 1",
            (r["cid"], r["logon_time"] or "", _BLOCK_GS_KT),
        ).fetchone()
        out.append({"cid": r["cid"], "callsign": r["callsign"] or "", "moved": moved is not None})
    return out


def update_bummel_starts(
    conn: sqlite3.Connection, now: str, *, callsign_prefix: str = "FRS"
) -> list[tuple[int, str]]:
    """Start-Latch: markiert ein laufendes Rennen als gestartet, sobald der erste Pilot Blockzeit
    erreicht (Bewegung an einem Streckenflugplatz). Gibt (race_id, callsign) der in diesem Lauf
    neu gestarteten Rennen zurück — für den „… hat den Bummel gestartet"-Push."""
    out: list[tuple[int, str]] = []
    for race in list_bummel_races(conn):
        if race["started_at"]:
            continue
        if now < (race["dtstart"] or ""):
            continue
        if (race["dtend"] or "") and now > race["dtend"]:
            continue
        route_icaos = [c for c in (race["route"] or "").split(",") if c.strip()]
        moved = [
            s for s in bummel_open_starters(
                conn, route_icaos, race["radius_km"] or _BUMMEL_AIRPORT_RADIUS_KM,
                callsign_prefix=callsign_prefix,
            )
            if s["moved"]
        ]
        if moved:
            set_bummel_started(conn, race["id"], now)
            out.append((race["id"], moved[0]["callsign"]))
    conn.commit()
    return out


def get_all_push_subscriptions(conn: sqlite3.Connection) -> list[dict]:
    """Alle Push-Subscriptions (für Broadcast-Benachrichtigungen wie Bummel-Start/-Enthüllung)."""
    rows = conn.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions").fetchall()
    return [dict(r) for r in rows]


def get_push_subscription_by_endpoint(conn: sqlite3.Connection, endpoint: str) -> dict | None:
    """Genau eine Subscription anhand ihres Endpoints (für Test-Push nur ans eigene Gerät)."""
    row = conn.execute(
        "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE endpoint = ?",
        (endpoint,),
    ).fetchone()
    return dict(row) if row is not None else None


def compute_bummel_standings(
    conn: sqlite3.Connection,
    route_icaos: list[str],
    start: str,
    end: str,
    *,
    cids: list[int] | None = None,
    radius_km: float | None = None,
) -> dict:
    """Wertung für einen FriesenFliegerBummel.

    Es gewinnt, wer mit der Summe seiner Gate-to-Gate-Blockzeiten am dichtesten an der
    Durchschnittszeit aller KOMPLETTEN Touren liegt. Eine Tour gilt als komplett, wenn der
    Pilot alle Flugplätze der Strecke besucht hat — Reihenfolge und Richtung egal (A→B = B→A,
    auch alternative Routings). Gewertete Zeit je Flug: ``block_min`` (Gate-to-Gate inkl. Taxi),
    Fallback ``duration_min`` (z. B. reine StatSim-Flüge).

    Track-/tour-basiert (Bummel = gemütlich): Die Tour eines Piloten reicht vom ersten Start an
    einem Streckenflugplatz bis zum letzten Ziel an einem Streckenflugplatz — **Zwischenlandungen
    dazwischen sind erlaubt** und brechen die Wertung nicht. Gewertet wird die Summe der reinen
    Block-Zeiten der Tour-Beine, d. h. die Bodenzeit der Zwischenstopps zählt NICHT mit.

    Frühstarter: Flüge, die VOR ``start`` begonnen haben, aber im Eventfenster noch unterwegs sind
    (``logoff_time >= start``), werden mit voller Blockzeit erfasst (Vorlauf
    ``_BUMMEL_EARLY_START_LOOKBACK_H``). ``radius_km`` steuert den Erfassungs-Umkreis um einen
    Streckenflugplatz (Default ``_BUMMEL_AIRPORT_RADIUS_KM``).

    Robust nach Wunsch: baut auf :func:`canonicalize_flights` auf (Reconnect-Fragmente gemergt,
    Ghosts gefiltert, dedupliziert). Unvollständige Touren werden NIE still verworfen, sondern
    separat mit ``visited``/``missing`` gelistet — sichtbares Kontrollnetz, falls ein geflogenes
    Bein wegen eines abweichenden Flugplans nicht matcht.

    Rückgabe::

        {
          "route": [ICAO, ...],                 # Reihenfolge wie im Termin, dedupliziert
          "complete": [ {cid, name, callsign, total_min, visited, missing, legs,
                         delta, rank}, ... ],   # aufsteigend nach delta
          "incomplete": [ {... ohne delta/rank} ],
          "average_min": float,                 # Schnitt über komplette Touren
          "count": int,                         # Anzahl kompletter Touren
        }
    """
    route_order: list[str] = []
    for code in route_icaos:
        c = (code or "").strip().upper()
        if c and c not in route_order:
            route_order.append(c)
    route_set = set(route_order)

    radius = radius_km or _BUMMEL_AIRPORT_RADIUS_KM

    # GPS-Anwesenheit: tatsächlichen Start/Ziel je Flug aus der ersten/letzten Position ableiten.
    # Macht die Wertung unabhängig vom gefilten Flugplan (Tippfehler) — der Flugplan dient nur
    # noch als Fallback, wenn kein GPS-Track existiert (z. B. reine StatSim-Flüge).
    from app.geo import icao_to_coords  # lazy: Import-Kosten/Zyklen vermeiden
    coords_map = {icao: icao_to_coords(icao) for icao in route_order}

    def _nearest_route_airport(pos: tuple[float, float] | None) -> str | None:
        return _nearest_airport(coords_map, pos, radius)

    # Frühstarter: mit Vorlauf laden, damit Flüge, die VOR dtstart begonnen haben, aber im
    # Eventfenster noch unterwegs sind, erfasst werden. canonicalize_flights filtert nach
    # logon_time; danach wird hier nach echter Überlappung (logoff_time >= start) gefiltert.
    load_start = _shift_iso(start, hours=-_BUMMEL_EARLY_START_LOOKBACK_H)
    flights = canonicalize_flights(conn, start=load_start, end=end, cids=cids)
    flights = [f for f in flights if (f.get("logoff_time") or "") >= start]

    # Beine je Pilot sammeln (Endpunkte GPS-korrigiert, sonst Flugplan). Beine außerhalb der
    # Strecke werden NICHT mehr sofort verworfen — sie können Zwischenstopps einer Tour sein.
    legs_by_cid: dict[int, list[dict]] = {}
    for f in flights:
        cid = f.get("cid")
        if cid is None:
            continue
        fp_dep = (f.get("departure") or "").strip().upper()
        fp_arr = (f.get("arrival") or "").strip().upper()
        lo = f.get("logon_time") or ""
        lf = f.get("logoff_time") or "9999-12-31T23:59:59Z"
        dep = _nearest_route_airport(_first_pos(conn, int(cid), lo, lf)) or fp_dep
        arr = _nearest_route_airport(_last_pos(conn, int(cid), lo, lf)) or fp_arr
        block = f.get("block_min")
        minutes = int(block) if block else int(f.get("duration_min") or 0)
        # Sekundengenaue Block-Zeit aus dem GPS-Track; Fallback Minuten*60 (StatSim / kein Track).
        secs = _block_seconds(conn, int(cid), lo, lf) or minutes * 60
        legs_by_cid.setdefault(cid, []).append({
            "departure": dep,
            "arrival": arr,
            "block_min": block,
            "minutes": minutes,
            "seconds": secs,
            "aircraft": f.get("aircraft") or "",
            "logon_time": f.get("logon_time") or "",
            "logoff_time": f.get("logoff_time"),
            "source": f.get("source"),
            "callsign": f.get("callsign") or "",
        })

    # Tour je Pilot: vom ersten Start an einem Streckenflugplatz bis zum letzten Ziel an einem
    # Streckenflugplatz (Beine zeitlich geordnet). Zwischenstopps dazwischen sind erlaubt; ihre
    # Bodenzeit fällt automatisch raus, da nur die Block-Zeit der Beine summiert wird.
    complete: list[dict] = []
    incomplete: list[dict] = []
    for cid, legs in legs_by_cid.items():
        legs.sort(key=lambda l: l["logon_time"])
        start_idx = next((i for i, l in enumerate(legs) if l["departure"] in route_set), None)
        end_idx = next(
            (i for i in range(len(legs) - 1, -1, -1) if legs[i]["arrival"] in route_set), None
        )
        if start_idx is None or end_idx is None or end_idx < start_idx:
            continue  # keine an der Strecke beginnende UND endende Tour
        tour = legs[start_idx:end_idx + 1]
        visited: set[str] = set()
        total = 0
        total_secs = 0
        for l in tour:
            total += l["minutes"]
            total_secs += l["seconds"]
            if l["departure"] in route_set:
                visited.add(l["departure"])
            if l["arrival"] in route_set:
                visited.add(l["arrival"])
        row = conn.execute("SELECT name FROM pilots WHERE cid = ?", (cid,)).fetchone()
        entry = {
            "cid": cid,
            "name": (row["name"] if row else "") or "",
            "callsign": tour[0]["callsign"],
            "total_min": total,
            "total_sec": total_secs,
            "legs": [{k: v for k, v in l.items() if k != "callsign"} for l in tour],
            "leg_count": len(tour),
            "aircraft": next((l["aircraft"] for l in tour if l["aircraft"]), ""),
            "visited": [c for c in route_order if c in visited],
            "missing": [c for c in route_order if c not in visited],
        }
        (complete if route_set.issubset(visited) else incomplete).append(entry)

    count = len(complete)
    average = (sum(e["total_min"] for e in complete) / count) if count else 0.0
    average_sec = (sum(e["total_sec"] for e in complete) / count) if count else 0.0
    for e in complete:
        e["delta"] = round(abs(e["total_min"] - average), 1)     # Minuten (Anzeige/Kompat)
        e["delta_sec"] = round(e["total_sec"] - average_sec)      # SIGNIERT, sekundengenau
    # Sekundengenaues Ranking: löst Gleichstände bei gleicher Minuten-Blockzeit auf.
    complete.sort(key=lambda e: (abs(e["delta_sec"]), e["total_sec"], e["cid"]))
    for rank, e in enumerate(complete, 1):
        e["rank"] = rank
    incomplete.sort(key=lambda e: e["cid"])

    return {
        "route": route_order,
        "complete": complete,
        "incomplete": incomplete,
        "average_min": round(average, 1),
        "average_sec": round(average_sec),
        "count": count,
        "participant_count": len(complete) + len(incomplete),
    }


# Felder, die in der öffentlichen Sicht eines Teilnehmers vor Enthüllung erlaubt sind.
# Bewusst OHNE total_min/total_sec/block_min/delta/delta_sec/rank/distance/logoff/duration —
# alles, woraus sich eine Zeit ableiten ließe, bleibt verborgen (Fairness).
def public_bummel_view(standings: dict, in_progress: list[dict], revealed: bool) -> dict:
    """Öffentliche Sicht auf ein Rennen.

    ``revealed`` → volle Standings (Ranking, Zeiten, Schnitt, Sieger).
    sonst → redigierte Teilnahme-Ansicht: nur Callsign/Name/Flugzeug/Fortschritt/Startzeit,
    KEINE Zeiten/Schnitt/Abstände/Ränge/nm. Die „unterwegs"-Liste (``in_progress``) enthält nur
    Start/Ziel/Startzeit (keine Block-Zeit) und ist daher auch live unbedenklich.
    """
    in_prog_cids = {p["cid"] for p in in_progress}
    base: dict = {
        "route": standings["route"],
        "revealed": revealed,
        "in_progress": in_progress,
        "participant_count": len(
            {e["cid"] for e in standings["complete"]}
            | {e["cid"] for e in standings["incomplete"]}
            | in_prog_cids
        ),
    }
    if revealed:
        base.update({
            "complete": standings["complete"],
            "incomplete": standings["incomplete"],
            "average_min": standings["average_min"],
            "count": standings["count"],
        })
        return base

    participants = []
    for e in standings["complete"] + standings["incomplete"]:
        started = min(
            (l["logon_time"] for l in e["legs"] if l.get("logon_time")), default=None
        )
        participants.append({
            "cid": e["cid"],
            "name": e["name"],
            "callsign": e["callsign"],
            "aircraft": e["aircraft"],
            "visited": e["visited"],
            "missing": e["missing"],
            "leg_count": e["leg_count"],
            "started": started,
            "in_progress": e["cid"] in in_prog_cids,
        })
    base["participants"] = participants
    return base


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
    notify_ts: bool = False,
    ts_self_frs: str | None = None,
    notify_events: bool = False,
) -> None:
    """Browser-Push-Subscription speichern oder aktualisieren."""
    conn.execute(
        """INSERT INTO push_subscriptions
               (endpoint, p256dh, auth, pilot_filter, notify_prefiles,
                notify_ts, ts_self_frs, notify_events, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(endpoint) DO UPDATE SET
               p256dh=excluded.p256dh,
               auth=excluded.auth,
               pilot_filter=excluded.pilot_filter,
               notify_prefiles=excluded.notify_prefiles,
               notify_ts=excluded.notify_ts,
               ts_self_frs=excluded.ts_self_frs,
               notify_events=excluded.notify_events,
               created_at=excluded.created_at""",
        (
            endpoint, p256dh, auth,
            json.dumps(pilot_filter) if pilot_filter is not None else None,
            1 if notify_prefiles else 0,
            1 if notify_ts else 0,
            ts_self_frs,
            1 if notify_events else 0,
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
            "INSERT OR REPLACE INTO calendar_events "
            "(uid, summary, dtstart, dtend, location, route, is_bummel, is_transport) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ev["uid"], ev["summary"], ev["dtstart"], ev["dtend"], ev["location"],
                ev.get("route") or "", 1 if ev.get("is_bummel") else 0,
                1 if ev.get("is_transport") else 0,
            ),
        )


def get_calendar_events(conn: sqlite3.Connection, days_back: int = 365) -> list[dict]:
    """FriesenEvents der letzten N Tage, neueste zuerst."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT uid, summary, dtstart, dtend, location, route, is_bummel, is_transport "
        "FROM calendar_events "
        "WHERE dtstart >= ? AND dtstart <= ? ORDER BY dtstart DESC",
        (cutoff, now_str),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Bummel-Rennen (persistent) — Kalender-synchronisiert oder manuell (Phase B)
# ---------------------------------------------------------------------------

def upsert_calendar_bummel_race(conn: sqlite3.Connection, ev: dict) -> None:
    """Ein erkanntes Bummel-Kalenderevent als persistentes Rennen anlegen/aktualisieren.

    Idempotent über ``calendar_uid``. ``dtend`` wird mit dem Mitternacht-Default aufgelöst.
    ``revealed_at`` bleibt beim Update unangetastet (latchend).
    """
    conn.execute(
        """INSERT INTO bummel_races
               (name, route, dtstart, dtend, radius_km, source, calendar_uid, revealed_at, created_at)
           VALUES (?, ?, ?, ?, ?, 'calendar', ?, NULL, ?)
           ON CONFLICT(calendar_uid) DO UPDATE SET
               name=excluded.name,
               route=excluded.route,
               dtstart=excluded.dtstart,
               dtend=excluded.dtend""",
        (
            ev.get("summary") or "",
            ev.get("route") or "",
            ev.get("dtstart") or "",
            _effective_dtend(ev.get("dtstart") or "", ev.get("dtend")),
            10,
            ev.get("uid"),
            _now_utc(),
        ),
    )


def list_bummel_races(conn: sqlite3.Connection) -> list[dict]:
    """Alle Rennen, neueste zuerst (nach dtstart)."""
    rows = conn.execute(
        "SELECT id, name, route, dtstart, dtend, radius_km, source, calendar_uid, "
        "revealed_at, created_at, push_enabled, started_at, reveal_suppressed "
        "FROM bummel_races ORDER BY dtstart DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_bummel_race(conn: sqlite3.Connection, race_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, name, route, dtstart, dtend, radius_km, source, calendar_uid, "
        "revealed_at, created_at, push_enabled, started_at, reveal_suppressed "
        "FROM bummel_races WHERE id = ?",
        (race_id,),
    ).fetchone()
    return dict(row) if row else None


def set_bummel_revealed(conn: sqlite3.Connection, race_id: int, ts: str) -> None:
    """Enthüllung latchen — nur setzen, wenn noch nicht enthüllt (idempotent)."""
    conn.execute(
        "UPDATE bummel_races SET revealed_at = ? WHERE id = ? AND revealed_at IS NULL",
        (ts, race_id),
    )


def force_bummel_revealed(conn: sqlite3.Connection, race_id: int, ts: str | None) -> None:
    """Admin-Override: Enthüllung erzwingen (ts gesetzt) ODER wieder verbergen (ts=None).
    Anders als set_bummel_revealed wird der Wert bedingungslos gesetzt."""
    conn.execute("UPDATE bummel_races SET revealed_at = ? WHERE id = ?", (ts, race_id))


def set_bummel_started(conn: sqlite3.Connection, race_id: int, ts: str) -> None:
    """started_at latchen — setzt nur wenn noch NULL (analogon zu set_bummel_revealed)."""
    conn.execute(
        "UPDATE bummel_races SET started_at = ? WHERE id = ? AND started_at IS NULL",
        (ts, race_id),
    )


def set_bummel_push_enabled(conn: sqlite3.Connection, race_id: int, enabled: bool) -> None:
    """Push-Benachrichtigungen für ein Rennen aktivieren oder deaktivieren."""
    conn.execute(
        "UPDATE bummel_races SET push_enabled = ? WHERE id = ?",
        (1 if enabled else 0, race_id),
    )


def set_bummel_reveal_suppressed(conn: sqlite3.Connection, race_id: int, suppressed: bool) -> None:
    """Manuelles Verbergen latchen: ``suppressed=True`` hält ein bereits abgelaufenes Rennen
    verborgen (übersteuert den Auto-Reveal in ``update_bummel_reveals``); ``False`` gibt es frei."""
    conn.execute(
        "UPDATE bummel_races SET reveal_suppressed = ? WHERE id = ?",
        (1 if suppressed else 0, race_id),
    )


# ---------------------------------------------------------------------------
# Manuelle Renn-CRUD
# ---------------------------------------------------------------------------

def create_bummel_race(
    conn: sqlite3.Connection,
    *,
    name: str,
    route: str,
    dtstart: str,
    dtend: str | None,
    radius_km: float = 10.0,
) -> int:
    """Manuelles Rennen anlegen. Gibt die neue id zurück."""
    effective_end = _effective_dtend(dtstart, dtend)
    cur = conn.execute(
        "INSERT INTO bummel_races "
        "(name, route, dtstart, dtend, radius_km, source, calendar_uid, revealed_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'manual', NULL, NULL, ?)",
        (name, route, dtstart, effective_end, radius_km, _now_utc()),
    )
    return cur.lastrowid  # type: ignore[return-value]


_UPDATABLE_RACE_FIELDS = {"name", "route", "dtstart", "dtend", "radius_km"}


def update_bummel_race(conn: sqlite3.Connection, race_id: int, **fields: object) -> None:
    """Aktualisiert nur übergebene Felder aus {name, route, dtstart, dtend, radius_km}.
    Wenn dtstart oder dtend geändert wird, wird dtend via _effective_dtend neu aufgelöst.
    Unbekannte Felder werden ignoriert.
    """
    valid = {k: v for k, v in fields.items() if k in _UPDATABLE_RACE_FIELDS}
    if not valid:
        return
    # dtend neu auflösen wenn dtstart oder dtend geändert wird
    if "dtstart" in valid or "dtend" in valid:
        current = get_bummel_race(conn, race_id)
        if current is None:
            return
        new_dtstart = str(valid.get("dtstart", current["dtstart"]))
        new_dtend = valid.get("dtend")  # None wenn nicht in fields
        valid["dtend"] = _effective_dtend(new_dtstart, new_dtend)  # type: ignore[arg-type]
    set_clause = ", ".join(f"{k} = ?" for k in valid)
    values = list(valid.values()) + [race_id]
    conn.execute(f"UPDATE bummel_races SET {set_clause} WHERE id = ?", values)


def delete_bummel_race(conn: sqlite3.Connection, race_id: int) -> None:
    """Löscht das Rennen und alle zugehörigen Overrides."""
    conn.execute("DELETE FROM bummel_overrides WHERE race_id = ?", (race_id,))
    conn.execute("DELETE FROM bummel_races WHERE id = ?", (race_id,))


# ---------------------------------------------------------------------------
# FriesenKutter — Transportflug-Events + Fracht-Manifest + Zuladungs-Tabelle
# ---------------------------------------------------------------------------

_TRANSPORT_DEFAULT_PAYLOAD_KEY = "transport_default_payload_kg"
_TRANSPORT_DEFAULT_PAYLOAD_FALLBACK = 150.0
# Standard-Pilotengewicht (kg): zählt bei der Zuladungs-Ableitung nicht als Fracht.
_CREW_KG_DEFAULT = 85.0


def normalize_type_code(code: str | None) -> str:
    """Flugzeugtyp auf einen Tabellen-Schlüssel normalisieren (Uppercase, vor '/' gekürzt)."""
    if not code:
        return ""
    return code.split("/")[0].strip().upper()


def transport_default_payload_kg(conn: sqlite3.Connection) -> float:
    """Globaler Fallback-Zuladungswert (kg) für noch nicht gepflegte Flugzeugtypen."""
    raw = get_app_setting(conn, _TRANSPORT_DEFAULT_PAYLOAD_KEY, None)
    try:
        return float(raw) if raw is not None else _TRANSPORT_DEFAULT_PAYLOAD_FALLBACK
    except (TypeError, ValueError):
        return _TRANSPORT_DEFAULT_PAYLOAD_FALLBACK


def get_payload_map(conn: sqlite3.Connection) -> dict[str, float]:
    """{type_code: payload_kg} über alle gepflegten Flugzeugtypen."""
    rows = conn.execute("SELECT type_code, payload_kg FROM aircraft_payloads").fetchall()
    return {r["type_code"]: (r["payload_kg"] or 0.0) for r in rows}


def list_aircraft_payloads(conn: sqlite3.Connection) -> list[dict]:
    """Alle Zuladungs-Zeilen (für die Admin-Tabelle), alphabetisch nach Typcode."""
    rows = conn.execute(
        "SELECT type_code, mtow_kg, empty_kg, fuel_kg, crew_kg, payload_kg, source, make_model, updated_at "
        "FROM aircraft_payloads ORDER BY type_code"
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_payload(
    conn: sqlite3.Connection,
    type_code: str,
    *,
    payload_kg: float | None = None,
    mtow_kg: float | None = None,
    empty_kg: float | None = None,
    fuel_kg: float | None = None,
    crew_kg: float | None = None,
    source: str = "manual",
    make_model: str | None = None,
) -> None:
    """Zuladung eines Flugzeugtyps setzen/aktualisieren.

    Ist ``payload_kg`` nicht direkt angegeben, wird es aus den Komponenten abgeleitet
    (``max(0, mtow − empty − fuel − crew)``) — der Pilot/die Crew zählt NICHT als Fracht.
    Ohne ``crew_kg`` wird das Standard-Pilotengewicht (:data:`_CREW_KG_DEFAULT`) angesetzt und
    gespeichert. Der Typcode wird normalisiert gespeichert.
    """
    code = normalize_type_code(type_code)
    if not code:
        return
    if crew_kg is None:
        crew_kg = _CREW_KG_DEFAULT
    if payload_kg is None:
        payload_kg = max(0.0, (mtow_kg or 0.0) - (empty_kg or 0.0) - (fuel_kg or 0.0) - (crew_kg or 0.0))
    conn.execute(
        """INSERT INTO aircraft_payloads
               (type_code, mtow_kg, empty_kg, fuel_kg, crew_kg, payload_kg, source, make_model, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(type_code) DO UPDATE SET
               mtow_kg=excluded.mtow_kg, empty_kg=excluded.empty_kg, fuel_kg=excluded.fuel_kg,
               crew_kg=excluded.crew_kg, payload_kg=excluded.payload_kg, source=excluded.source,
               make_model=excluded.make_model, updated_at=excluded.updated_at""",
        (code, mtow_kg, empty_kg, fuel_kg, crew_kg, payload_kg, source, make_model, _now_utc()),
    )


# --- Transport-Events (Kalender-synchronisiert oder manuell) ---------------

_TRANSPORT_EVENT_COLS = (
    "id, name, route, destination, dtstart, dtend, source, calendar_uid, push_enabled, "
    "started_at, goal_reached_at, summarized_at, summary_quip, radius_km, created_at"
)


def _default_destination(route: str) -> str:
    """Heuristik: Ziel = letzter Flugplatz der Strecken-CSV (bei 'Wangerooge–Helgoland' = Helgoland)."""
    parts = [normalize_type_code(c) for c in (route or "").split(",")]
    parts = [c for c in parts if c]
    return parts[-1] if parts else ""


def _resolve_cargo_against_catalog(conn: sqlite3.Connection, lines: list[dict]) -> list[dict]:
    """Aus dem Kalender geparste Fracht-Zeilen (nur name/target_kg) gegen den Katalog auflösen
    (Emoji + Obergrenze pro Flug ergänzen). Unbekannte Namen bleiben Freitext ohne Emoji/Kappung."""
    by_name = {c["name"].strip().lower(): c for c in list_cargo_catalog(conn)}
    out = []
    for line in lines:
        cat = by_name.get((line.get("name") or "").strip().lower())
        out.append({
            "name": line["name"],
            "target_kg": line["target_kg"],
            "emoji": cat["emoji"] if cat else None,
            "per_flight_max_kg": cat["per_flight_max_kg"] if cat else None,
        })
    return out


def upsert_calendar_transport_event(conn: sqlite3.Connection, ev: dict) -> None:
    """Ein erkanntes FriesenKutter-Kalenderevent als persistentes Transportevent anlegen/updaten.

    Idempotent über ``calendar_uid``. ``dtend`` mit Mitternacht-Default. Enthält die Beschreibung
    eine Fracht-Zeile (Marker ``Fracht: 1000 Krabbenbrötchen, 500 Friesentee``, geparst in
    ``calendar_sync.parse_cargo_lines``), wird daraus **einmalig** das Manifest befüllt (Namen
    gegen den Katalog abgeglichen) — nur solange noch **kein** Manifest existiert, damit spätere
    Admin-Bearbeitungen bei erneutem Sync nicht überschrieben werden.
    """
    route = ev.get("route") or ""
    conn.execute(
        """INSERT INTO transport_events
               (name, route, destination, dtstart, dtend, source, calendar_uid, created_at)
           VALUES (?, ?, ?, ?, ?, 'calendar', ?, ?)
           ON CONFLICT(calendar_uid) DO UPDATE SET
               name=excluded.name, route=excluded.route,
               dtstart=excluded.dtstart, dtend=excluded.dtend""",
        (
            ev.get("summary") or "",
            route,
            _default_destination(route),   # Ziel-Default; im Admin korrigierbar (Update lässt es unangetastet)
            ev.get("dtstart") or "",
            _effective_dtend(ev.get("dtstart") or "", ev.get("dtend")),
            ev.get("uid"),
            _now_utc(),
        ),
    )
    cargo_lines = ev.get("cargo") or []
    if cargo_lines:
        row = conn.execute(
            "SELECT id FROM transport_events WHERE calendar_uid = ?", (ev.get("uid"),)
        ).fetchone()
        if row and not get_transport_cargo(conn, row[0]):
            set_transport_cargo(conn, row[0], _resolve_cargo_against_catalog(conn, cargo_lines))


def list_transport_events(conn: sqlite3.Connection) -> list[dict]:
    """Alle Transport-Events (Kalender + manuell), neueste zuerst."""
    rows = conn.execute(
        f"SELECT {_TRANSPORT_EVENT_COLS} FROM transport_events ORDER BY dtstart DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_transport_event(conn: sqlite3.Connection, event_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {_TRANSPORT_EVENT_COLS} FROM transport_events WHERE id = ?", (event_id,)
    ).fetchone()
    return dict(row) if row else None


def create_transport_event(
    conn: sqlite3.Connection,
    *,
    name: str,
    route: str,
    dtstart: str,
    dtend: str | None,
    destination: str | None = None,
    cargo: list[dict] | None = None,
    radius_km: float | None = None,
) -> int:
    """Manuelles Transportevent anlegen (+ optionales Fracht-Manifest). Gibt die neue id zurück.
    Ohne ``destination`` wird der letzte Strecken-Flugplatz als Ziel angenommen.
    Ohne ``radius_km`` gilt beim Erkennungs-Umkreis der Default (``_BUMMEL_AIRPORT_RADIUS_KM``)."""
    dest = normalize_type_code(destination) or _default_destination(route)
    cur = conn.execute(
        "INSERT INTO transport_events "
        "(name, route, destination, dtstart, dtend, source, calendar_uid, radius_km, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'manual', NULL, ?, ?)",
        (name, route, dest, dtstart, _effective_dtend(dtstart, dtend), radius_km, _now_utc()),
    )
    event_id = int(cur.lastrowid)  # type: ignore[arg-type]
    if cargo:
        set_transport_cargo(conn, event_id, cargo)
    return event_id


_UPDATABLE_TRANSPORT_FIELDS = {"name", "route", "destination", "dtstart", "dtend", "radius_km"}


def update_transport_event(conn: sqlite3.Connection, event_id: int, **fields: object) -> None:
    """Aktualisiert {name, route, dtstart, dtend}. dtend wird bei Zeitänderung neu aufgelöst.
    ``cargo`` (falls übergeben) ersetzt das gesamte Manifest."""
    cargo = fields.pop("cargo", None)
    valid = {k: v for k, v in fields.items() if k in _UPDATABLE_TRANSPORT_FIELDS}
    if valid:
        if "dtstart" in valid or "dtend" in valid:
            current = get_transport_event(conn, event_id)
            if current is not None:
                new_start = str(valid.get("dtstart", current["dtstart"]))
                valid["dtend"] = _effective_dtend(new_start, valid.get("dtend"))  # type: ignore[arg-type]
        set_clause = ", ".join(f"{k} = ?" for k in valid)
        conn.execute(
            f"UPDATE transport_events SET {set_clause} WHERE id = ?",
            list(valid.values()) + [event_id],
        )
    if cargo is not None:
        set_transport_cargo(conn, event_id, cargo)  # type: ignore[arg-type]


def delete_transport_event(conn: sqlite3.Connection, event_id: int) -> None:
    """Event samt Fracht-Manifest löschen."""
    conn.execute("DELETE FROM transport_cargo WHERE event_id = ?", (event_id,))
    conn.execute("DELETE FROM transport_events WHERE id = ?", (event_id,))


def get_transport_cargo(conn: sqlite3.Connection, event_id: int) -> list[dict]:
    """Geordnetes Fracht-Manifest eines Events (inkl. Emoji + Co-Load-Kappung)."""
    rows = conn.execute(
        "SELECT id, position, name, target_kg, emoji, per_flight_max_kg FROM transport_cargo "
        "WHERE event_id = ? ORDER BY position, id",
        (event_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _opt_float(v) -> float | None:
    try:
        return float(v) if v is not None and str(v) != "" else None
    except (TypeError, ValueError):
        return None


def set_transport_cargo(conn: sqlite3.Connection, event_id: int, cargo: list[dict]) -> None:
    """Fracht-Manifest eines Events komplett ersetzen. Zeilen ohne Name/Menge werden ignoriert.
    Je Zeile optional ``emoji`` und ``per_flight_max_kg`` (Obergrenze pro Flug, Co-Load)."""
    conn.execute("DELETE FROM transport_cargo WHERE event_id = ?", (event_id,))
    pos = 0
    for line in cargo:
        name = (line.get("name") or "").strip()
        try:
            target = float(line.get("target_kg"))
        except (TypeError, ValueError):
            continue
        if not name or target <= 0:
            continue
        conn.execute(
            "INSERT INTO transport_cargo "
            "(event_id, position, name, target_kg, emoji, per_flight_max_kg) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, pos, name, target, (line.get("emoji") or None), _opt_float(line.get("per_flight_max_kg"))),
        )
        pos += 1


# --- Frachtart-Katalog (Stammdaten, wiederverwendbar über Events) ----------

_CARGO_SEED = [
    ("Krabbenbrötchen", "🦐", None), ("Friesentee", "🫖", None), ("Filmrollen", "🎞️", 100.0),
    ("Sonnenschirme", "⛱️", None), ("Strandkörbe", "🪑", None), ("Lebensmittel", "🧺", None),
    ("Baumaterial", "🧱", None), ("Material für Offshore-Anlagen", "⚙️", None),
    ("Heringe (für die Seehunde in EDWS)", "🐟", None), ("Passagiere", "🧳", None),
    ("Seehund-Heuler", "🦭", None), ("Deichschafe", "🐑", None),
    ("Rechtsdeichschaf", "🐑", None), ("Linksdeichschaf", "🐑", None),
    ("Kluntje", "🍬", None), ("Teesahne", "🥛", None), ("Köm & Bommerlunder", "🥃", None),
    ("Pharisäer", "☕", None), ("Reet fürs Reetdach", "🪵", None), ("Gummistiefel", "🥾", None),
    ("Rettungswesten", "🦺", None), ("Wattwürmer", "🪱", None), ("Rollmops & Matjes", "🐟", None),
    ("Butterkoken", "🍰", None), ("Grünkohl mit Pinkel", "🥬", None),
    ("Leuchtturm-Glühbirnen", "💡", None), ("Ostfriesenwitze-Bücher", "📚", None),
    ("Inselpost", "📦", None), ("Abgefüllte Nordseeluft", "💨", None), ("Strandspielzeug", "🏖️", None),
]


def list_cargo_catalog(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, emoji, per_flight_max_kg, position FROM cargo_catalog ORDER BY position, id"
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_cargo_catalog(conn: sqlite3.Connection, *, id: int | None = None, name: str,
                         emoji: str | None = None, per_flight_max_kg=None) -> None:
    name = (name or "").strip()
    if not name:
        return
    if id:
        conn.execute(
            "UPDATE cargo_catalog SET name=?, emoji=?, per_flight_max_kg=? WHERE id=?",
            (name, emoji or None, _opt_float(per_flight_max_kg), id),
        )
    else:
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM cargo_catalog").fetchone()[0]
        conn.execute(
            "INSERT INTO cargo_catalog (name, emoji, per_flight_max_kg, position) VALUES (?, ?, ?, ?)",
            (name, emoji or None, _opt_float(per_flight_max_kg), pos),
        )


def delete_cargo_catalog(conn: sqlite3.Connection, catalog_id: int) -> None:
    conn.execute("DELETE FROM cargo_catalog WHERE id = ?", (catalog_id,))


def seed_cargo_catalog(conn: sqlite3.Connection) -> int:
    """Katalog mit den Standard-Frachtarten befüllen — nur wenn er leer ist (idempotent)."""
    if conn.execute("SELECT COUNT(*) FROM cargo_catalog").fetchone()[0]:
        return 0
    for pos, (name, emoji, mx) in enumerate(_CARGO_SEED):
        conn.execute(
            "INSERT INTO cargo_catalog (name, emoji, per_flight_max_kg, position) VALUES (?, ?, ?, ?)",
            (name, emoji, mx, pos),
        )
    return len(_CARGO_SEED)


# --- Lustige KI-Sprüche (Phase 2): Cache je Flug + Tagesend-Zusammenfassung ---

def transport_quips_enabled(conn: sqlite3.Connection) -> bool:
    return str(get_app_setting(conn, "transport_quips_enabled", "0")) in ("1", "true", "True")


def get_transport_quips(conn: sqlite3.Connection, event_id: int) -> dict[str, str]:
    """{flight_key: quip} für ein Event."""
    rows = conn.execute(
        "SELECT flight_key, quip FROM transport_quips WHERE event_id = ?", (event_id,)
    ).fetchall()
    return {r["flight_key"]: r["quip"] for r in rows if r["quip"]}


def set_transport_quip(conn: sqlite3.Connection, event_id: int, flight_key: str, quip: str) -> None:
    conn.execute(
        "INSERT INTO transport_quips (event_id, flight_key, quip, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(event_id, flight_key) DO UPDATE SET quip=excluded.quip",
        (event_id, flight_key, quip, _now_utc()),
    )


def set_transport_summary_quip(conn: sqlite3.Connection, event_id: int, quip: str) -> None:
    conn.execute("UPDATE transport_events SET summary_quip = ? WHERE id = ?", (quip, event_id))


def flight_quip_context(flight: dict, progress: dict) -> dict:
    """Lokalen Kontext für einen Flug-Spruch aufbereiten (rein, testbar).

    ``flight`` ist ein Eintrag aus ``compute_transport_progress()['flights']``. Liefert Vorname,
    Anzahl bereits geflogener Frachtflüge heute (Fleiß), Tempo (kt), Umweg-Faktor (geflogene nm ÷
    Luftlinie) und die Fracht (mit Emoji)."""
    from app.geo import icao_to_coords, haversine  # lazy
    cid = flight.get("cid")
    name = (flight.get("name") or "").strip()
    vorname = name.split()[0] if name else (flight.get("callsign") or "")
    flights_tonight = sum(
        1 for f in progress.get("flights", []) if f.get("cid") == cid and f.get("loaded")
    )
    dist = float(flight.get("distance_nm") or 0)
    block = float(flight.get("block_min") or 0)
    speed_kt = round(dist / (block / 60.0)) if block > 0 and dist > 0 else None
    dep, arr = flight.get("dep"), flight.get("arr")
    detour_ratio = None
    dc, ac = icao_to_coords(dep or ""), icao_to_coords(arr or "")
    if dc and ac and dist > 0:
        direct_nm = haversine(dc[0], dc[1], ac[0], ac[1]) / 1.852
        if direct_nm > 1:
            detour_ratio = round(dist / direct_nm, 2)
    cargo = [
        f"{(c.get('emoji') or '').strip()} {c['name']} ({round(c['kg'])} kg)".strip()
        for c in (flight.get("cargo_lines") or [])
    ]
    loss_kind = flight.get("loss_kind")
    verlust = None
    if loss_kind == "sunk":
        verlust = f"Kutter versunken — {round(flight.get('lost_kg') or 0)} kg Fracht verloren"
    elif loss_kind == "stolen":
        verlust = (f"am falschen Ort gelandet ({flight.get('arr')}) — "
                   f"{round(flight.get('lost_kg') or 0)} kg Fracht geklaut")
    elif loss_kind == "returned":
        verlust = "umgedreht und Fracht heil zurückgebracht"
    return {
        "vorname": vorname,
        "callsign": flight.get("callsign"),
        "flights_tonight": flights_tonight,
        "aircraft": flight.get("aircraft"),
        "route": f"{dep}→{arr}",
        "tonnage_kg": round(flight.get("tonnage_kg") or 0),
        "cargo": cargo,
        "speed_kt": speed_kt,
        "detour_ratio": detour_ratio,
        "verlust": verlust,
    }


def event_summary_context(event: dict, progress: dict) -> dict:
    """Kontext für die lustige Tagesend-Zusammenfassung (rein, testbar)."""
    flights = [f for f in progress.get("flights", []) if f.get("loaded")]
    per_pilot: dict[str, int] = {}
    for f in flights:
        raw = (f.get("name") or f.get("callsign") or "?").strip()
        who = raw.split()[0] if raw else "?"
        per_pilot[who] = per_pilot.get(who, 0) + 1
    return {
        "name": event.get("name"),
        "total_kg": progress.get("total_kg"),
        "loaded_count": progress.get("loaded_count"),
        "cargo": [
            f"{(c.get('emoji') or '')} {c['name']} {round(c['delivered_kg'])}/{round(c['target_kg'])} kg".strip()
            for c in progress.get("cargo", [])
        ],
        "pilots": per_pilot,
        "route": " ↔ ".join(progress.get("route", [])),
        "destination": progress.get("destination"),
        "lost_total_kg": progress.get("lost_total_kg", 0.0),
        "verluste": [
            (f"{(l.get('name') or l.get('callsign') or '?').split()[0]}: "
             + ("Kutter versunken" if l.get("loss_kind") == "sunk"
                else "Fracht geklaut" if l.get("loss_kind") == "stolen"
                else "Fracht zurückgebracht")
             + f" ({round(l.get('lost_kg') or 0)} kg)")
            for l in progress.get("losses", [])
        ],
    }


def _set_transport_latch(conn: sqlite3.Connection, event_id: int, column: str, ts: str) -> bool:
    """Latch-Spalte setzen, nur wenn noch NULL. True, wenn in diesem Aufruf neu gesetzt."""
    cur = conn.execute(
        f"UPDATE transport_events SET {column} = ? WHERE id = ? AND {column} IS NULL",
        (ts, event_id),
    )
    return cur.rowcount > 0


def set_transport_started(conn: sqlite3.Connection, event_id: int, ts: str) -> bool:
    return _set_transport_latch(conn, event_id, "started_at", ts)


def set_transport_goal_reached(conn: sqlite3.Connection, event_id: int, ts: str) -> bool:
    return _set_transport_latch(conn, event_id, "goal_reached_at", ts)


def set_transport_summarized(conn: sqlite3.Connection, event_id: int, ts: str) -> bool:
    return _set_transport_latch(conn, event_id, "summarized_at", ts)


def set_transport_live_arrival(
    conn: sqlite3.Connection, cid: int, logon_time: str, event_id: int, arrived_at: str
) -> None:
    """Live-Ankunft dauerhaft latchen — einmal geschrieben, nie zurückgenommen."""
    conn.execute(
        "INSERT OR IGNORE INTO transport_live_arrivals (cid, logon_time, event_id, arrived_at) "
        "VALUES (?, ?, ?, ?)",
        (cid, logon_time, event_id, arrived_at),
    )


def get_transport_live_arrivals(conn: sqlite3.Connection, event_id: int) -> set[tuple[int, str]]:
    """{(cid, logon_time)} mit Live-Ankunfts-Latch für dieses Event."""
    rows = conn.execute(
        "SELECT cid, logon_time FROM transport_live_arrivals WHERE event_id = ?", (event_id,)
    ).fetchall()
    return {(r["cid"], r["logon_time"]) for r in rows}


def record_transport_loss(conn, event_id, cid, logon_time, kind, type_code,
                          callsign, dep, end_icao, lost_at) -> None:
    """Fracht-Verlust latchen (idempotent via PK). kind: 'returned'|'stolen'|'sunk'."""
    conn.execute(
        "INSERT OR IGNORE INTO transport_cargo_losses "
        "(event_id, cid, logon_time, kind, type_code, callsign, dep, end_icao, lost_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, cid, logon_time, kind, type_code, callsign, dep, end_icao, lost_at),
    )


def get_transport_losses(conn, event_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT event_id, cid, logon_time, kind, type_code, callsign, dep, end_icao, lost_at "
        "FROM transport_cargo_losses WHERE event_id = ? ORDER BY lost_at",
        (event_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def detect_transport_losses(conn, event: dict, *, callsign_prefix: str = "FRS") -> int:
    """Neue Fracht-Verluste eines Events erkennen und latchen (idempotent, Poll-Takt-tauglich).

    Kandidat = abgeschlossener Flug, der Richtung Ziel gestartet war (GPS-Erstposition auf der
    Strecke, Fallback Flugplan-DEP; dep ≠ destination), ohne Live-Ankunfts-Latch und ohne
    GPS-Ankunft am Ziel. Klassifikation per letzter Position:
    am Boden am Abflugplatz → 'returned' · am Boden an anderem Platz → 'stolen' ·
    sonst (in der Luft verschwunden / abseits jedes Platzes) → 'sunk' (Kutter versunken).
    """
    from app.geo import icao_to_coords, nearest_airport_icao
    dest = normalize_type_code(event.get("destination"))
    route_set = {c for c in (normalize_type_code(x) for x in (event.get("route") or "").split(",")) if c}
    if not dest or not route_set:
        return 0
    radius = event.get("radius_km") or _BUMMEL_AIRPORT_RADIUS_KM
    coords_map = {icao: icao_to_coords(icao) for icao in route_set}
    start = event.get("dtstart") or ""
    now = _now_utc()
    latched = get_transport_live_arrivals(conn, int(event["id"]))
    existing = {(l["cid"], l["logon_time"]) for l in get_transport_losses(conn, int(event["id"]))}
    load_start = _shift_iso(start, hours=-_BUMMEL_EARLY_START_LOOKBACK_H)
    new = 0
    # Obergrenze wie compute_transport_progress: Verluste dürfen nur innerhalb des
    # Event-Fensters entstehen. Ohne `end` wurde jeder spätere Streckenflug (auch Wochen nach
    # dtend, z. B. ein ganz anderes Event auf derselben Route) fälschlich als Verlust dieses
    # (längst abgeschlossenen) Events gelatcht — Alt-Events sammelten so fortlaufend
    # Fremd-Verluste, zusätzlich unbeschränkte Poller-Last.
    end = event.get("dtend") or now
    for f in canonicalize_flights(conn, start=load_start, end=end, callsign_prefix=callsign_prefix):
        cid, lo = f.get("cid"), f.get("logon_time") or ""
        lf = f.get("logoff_time") or ""
        if cid is None or not lf or lf < start:
            continue
        if (cid, lo) in latched or (cid, lo) in existing:
            continue
        dep = _nearest_airport(coords_map, _first_pos(conn, int(cid), lo, lf), radius) \
            or normalize_type_code(f.get("departure"))
        if dep not in route_set or dep == dest:
            continue  # war nie mit Fracht Richtung Ziel unterwegs
        arr = _nearest_airport(coords_map, _last_pos(conn, int(cid), lo, lf), radius)
        if arr == dest:
            continue  # GPS-Ankunft am Ziel → geliefert (compute zählt das als loaded)
        row = conn.execute(
            "SELECT latitude, longitude, groundspeed FROM position_history "
            "WHERE cid = ? AND ts >= ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            (cid, lo, lf),
        ).fetchone()
        if row is None:
            # Keine Position = keine Aussage: Flüge ohne jeden GPS-Track (z. B. StatSim-
            # rekonstruiert) nicht als Verlust werten — der Verlust-Override in
            # compute_transport_progress würde sonst echte StatSim-Lieferungen kippen.
            continue
        kind, end_icao = "sunk", None
        if row is not None and row["groundspeed"] is not None \
                and row["groundspeed"] <= _LANDED_MAX_GS_KT:
            end_icao = nearest_airport_icao(row["latitude"], row["longitude"], radius)
            if end_icao == dep:
                kind = "returned"
            elif end_icao:
                kind = "stolen"
        type_code = normalize_type_code(f.get("aircraft_icao")) or normalize_type_code(f.get("aircraft"))
        record_transport_loss(conn, int(event["id"]), int(cid), lo, kind, type_code,
                              f.get("callsign") or "", dep, end_icao, now)
        new += 1
    return new


def active_transport_destinations(conn: sqlite3.Connection, now: str) -> list[dict]:
    """Aktuell laufende FriesenKutter-Events (dtstart <= now <= dtend) mit gesetztem Ziel
    (inkl. ``radius_km`` — NULL, wenn das Event den Default-Umkreis nutzt)."""
    rows = conn.execute(
        "SELECT id, destination, radius_km FROM transport_events "
        "WHERE dtstart <= ? AND dtend >= ? AND destination IS NOT NULL AND destination != ''",
        (now, now),
    ).fetchall()
    return [{"id": r["id"], "destination": r["destination"], "radius_km": r["radius_km"]} for r in rows]


def open_transport_flights(conn: sqlite3.Connection, callsign_prefix: str = "FRS") -> list[dict]:
    """Aktuell offene (noch verbundene) FRS-Flüge — Basis für Live-Ankunft ohne Disconnect."""
    rows = conn.execute(
        "SELECT cid, callsign, aircraft_short AS aircraft, aircraft_icao, departure, arrival, logon_time "
        "FROM flights WHERE logoff_time IS NULL AND superseded_by IS NULL AND callsign LIKE ?",
        (callsign_prefix + "%",),
    ).fetchall()
    return [dict(r) for r in rows]


def check_live_arrival(
    conn: sqlite3.Connection,
    cid: int,
    logon_time: str,
    latitude: float,
    longitude: float,
    groundspeed: float,
    events: list[dict],
    *,
    radius_km: float | None = None,
) -> None:
    """Prüft eine aktuelle Live-Position gegen bereits geladene, laufende FriesenKutter-Ziele
    (``events``, aus :func:`active_transport_destinations`) und latcht einen Treffer dauerhaft
    (``transport_live_arrivals``) — 'am Boden' (``groundspeed < _BLOCK_GS_KT``) und im Umkreis
    (``radius_km``-Parameter > ``event["radius_km"]`` > ``_BUMMEL_AIRPORT_RADIUS_KM``) um
    ``destination``. Kein Rückgängigmachen; ``events`` wird NICHT selbst nachgeladen (Aufrufer
    lädt einmal pro Poll)."""
    if groundspeed is None or groundspeed >= _BLOCK_GS_KT:
        return
    from app.geo import haversine, icao_to_coords
    now = _now_utc()
    for ev in events:
        dest = normalize_type_code(ev.get("destination"))
        coords = icao_to_coords(dest) if dest else None
        if not coords:
            continue
        radius = radius_km or ev.get("radius_km") or _BUMMEL_AIRPORT_RADIUS_KM
        if haversine(latitude, longitude, coords[0], coords[1]) <= radius:
            set_transport_live_arrival(conn, cid, logon_time, ev["id"], now)


def transport_event_started(
    conn: sqlite3.Connection, event: dict, callsign_prefix: str = "FRS"
) -> bool:
    """True, sobald ein Friese von einem Streckenflugplatz abgeflogen ist — auch während der Flug
    noch offen ist (kein Disconnect). ``compute_transport_progress`` nimmt offene Flüge seit dem
    Live-Ankunfts-Latch zwar in den Feed auf, zählt sie dort aber erst mit Latch als beladen (ohne
    verlässliche GPS-Ankunft) — das darf den Start-Push nicht verzögern: der (Flugplan-)Abflugort
    genügt hierfür, ohne GPS-Korrektur."""
    route_set = {c for c in (normalize_type_code(x) for x in (event.get("route") or "").split(",")) if c}
    if not route_set:
        return False
    return any(
        normalize_type_code(f.get("departure")) in route_set
        for f in open_transport_flights(conn, callsign_prefix)
    )


def transport_anyone_in_progress(
    conn: sqlite3.Connection,
    event: dict,
    *,
    started_before: str | None = None,
    callsign_prefix: str = "FRS",
    radius_km: float | None = None,
) -> bool:
    """True, wenn für dieses FriesenKutter-Event noch ein Friese unterwegs ist — dann muss die
    Feierabend-Zusammenfassung warten (analog ``_bummel_anyone_in_progress`` beim Reveal).

    Ein „Nachzügler" = offener Flug (``logoff_time IS NULL``), dessen Start an einem
    Streckenflugplatz liegt (GPS-erste-Position im Umkreis, Fallback Flugplan-DEP) und der vor
    ``started_before`` (dtend) begonnen hat — verspätete Neu-Connects nach dtend zählen nicht.
    Flüge mit Live-Ankunfts-Latch (``transport_live_arrivals``) verzögern nicht: ihr Beitrag
    steht fest (Zuladung hängt nur am Muster; der Latch überdauert jeden späteren Disconnect).
    """
    from app.geo import icao_to_coords
    route_set = {c for c in (normalize_type_code(x) for x in (event.get("route") or "").split(",")) if c}
    if not route_set:
        return False
    coords_map = {icao: icao_to_coords(icao) for icao in route_set}
    radius = radius_km or event.get("radius_km") or _BUMMEL_AIRPORT_RADIUS_KM
    latched = get_transport_live_arrivals(conn, int(event["id"]))
    for f in open_transport_flights(conn, callsign_prefix):
        lo = f.get("logon_time") or ""
        if started_before and lo > started_before:
            continue
        if (f.get("cid"), lo) in latched:
            continue
        first = _first_pos(conn, int(f["cid"]), lo, "9999-12-31T23:59:59Z")
        dep = _nearest_airport(coords_map, first, radius) or normalize_type_code(f.get("departure"))
        if dep in route_set:
            return True
    return False


def compute_transport_progress(
    conn: sqlite3.Connection,
    event: dict,
    now: str,
    *,
    callsign_prefix: str = "FRS",
    radius_km: float | None = None,
) -> dict:
    """Live-Fortschritt eines FriesenKutter-Events.

    Feed-relevant sind FRS-Flüge, deren Start UND Ziel (GPS-korrigiert, Flugplan als Fallback) auf
    der Streckenmenge liegen (dep≠arr). **Fracht zählt nur in eine Richtung:** ein Flug ist
    ``loaded`` (trägt Zuladung), wenn er am ``destination`` ankommt **ODER** ein Live-Ankunfts-Latch
    (``transport_live_arrivals``, gesetzt vom Poller via ``check_live_arrival`` — Boden + Zielradius,
    auch ohne Disconnect) existiert; ein Latch hebt dabei auch den Strecken-Filter auf, sodass die
    Fracht selbst dann gezählt bleibt, wenn der Pilot später außerhalb der Strecke disconnectet.
    Zusätzlich werden aktuell **offene** (noch verbundene) Flüge mit Start auf der Strecke in den
    Feed aufgenommen (``open_transport_flights``) — beladen nur mit Latch, da eine verlässliche
    GPS-Ankunft erst nach Disconnect feststeht; ansonsten 0 kg, bis Latch oder Disconnect eintreten.
    Rückflüge zählen 0 kg, erscheinen aber als leere Flüge im Feed. Zuladung je beladenem Flug aus
    ``aircraft_payloads`` (Fallback: globaler Default). Das Fracht-Manifest wird nach Abflugzeit per
    Co-Load gefüllt (Obergrenze pro Flug, Rest fließt in die nächste Frachtart); jeder beladene Flug
    trägt seine Frachtart(en). Der zurückgegebene ``flights``-Feed ist absteigend (neueste oben).

    **Reservierung:** Sobald ein FRS-Pilot Richtung Ziel abhebt (``open_transport_flights``,
    Start auf der Strecke), reserviert er seine volle Zuladung im Manifest — noch ohne Latch,
    also vor jeder GPS-Bestätigung. Die Reservierung ist rein rechnerisch (kein DB-State, kein
    eigenes Feld in ``flights``): sie füllt einen von ``delivered`` getrennten Topf
    (``reserved_alloc``/``reserved_total_kg``), damit der gelieferte Fortschritt nie rückwärts
    läuft, und verschwindet mit dem Flug (Latch, Landung anderswo, Disconnect). Die kg werden
    dabei stets live aus ``aircraft_payloads`` (``payload_map``/``default_kg``) gelesen, nie
    gesnapshottet.
    """
    from app.geo import icao_to_coords  # lazy

    route_set = {c for c in (normalize_type_code(x) for x in (event.get("route") or "").split(",")) if c}
    coords_map = {icao: icao_to_coords(icao) for icao in route_set}
    radius = radius_km or event.get("radius_km") or _BUMMEL_AIRPORT_RADIUS_KM
    payload_map = get_payload_map(conn)
    default_kg = transport_default_payload_kg(conn)

    start = event.get("dtstart") or ""
    end = min(now, event.get("dtend") or now)
    load_start = _shift_iso(start, hours=-_BUMMEL_EARLY_START_LOOKBACK_H)
    flights = canonicalize_flights(conn, start=load_start, end=end, callsign_prefix=callsign_prefix)
    flights = [f for f in flights if (f.get("logoff_time") or "") >= start]

    dest = normalize_type_code(event.get("destination"))
    live_arrivals = get_transport_live_arrivals(conn, int(event["id"]))

    # Netzwerk-Flüge sammeln (dep & arr auf der Strecke, dep≠arr). „Beladen" = Ankunft am Ziel
    # ODER ein Live-Ankunfts-Latch existiert (Fracht ohne Disconnect erkannt) — ein Latch hebt
    # den Strecken-Filter auf, da die Fracht dann unabhängig vom finalen Disconnect-Ort zählt.
    network: list[dict] = []
    unmapped: set[str] = set()
    for f in flights:
        cid = f.get("cid")
        if cid is None:
            continue
        lo = f.get("logon_time") or ""
        lf = f.get("logoff_time") or "9999-12-31T23:59:59Z"
        dep = _nearest_airport(coords_map, _first_pos(conn, int(cid), lo, lf), radius) \
            or normalize_type_code(f.get("departure"))
        arr_gps = _nearest_airport(coords_map, _last_pos(conn, int(cid), lo, lf), radius)
        arr = arr_gps or normalize_type_code(f.get("arrival"))
        has_latch = (cid, lo) in live_arrivals
        if not has_latch and (dep not in route_set or arr not in route_set or dep == arr):
            continue
        loaded = bool(dest) and (arr == dest or has_latch)
        type_code = normalize_type_code(f.get("aircraft_icao")) or normalize_type_code(f.get("aircraft"))
        if loaded and type_code and type_code not in payload_map:
            unmapped.add(type_code)
        tonnage = round(payload_map.get(type_code, default_kg), 1) if loaded else 0.0
        network.append({
            "dep_time": lo,
            "cid": cid,
            "callsign": f.get("callsign") or "",
            "aircraft": f.get("aircraft") or type_code,
            "dep": dep,
            "arr": arr,
            "tonnage_kg": tonnage,
            "loaded": loaded,
            "in_air": False,
            "reserved_kg": 0.0,
            "flight_key": f"{cid}:{lo}",
            "distance_nm": f.get("distance_nm") or 0,
            "block_min": f.get("block_min") or f.get("duration_min") or 0,
            # Lieferung hängt NUR am Flugplan-Text (kein Latch, keine GPS-Ankunft am Ziel) —
            # ein GPS-belegter Verlust darf so eine Lieferung überstimmen (interne Markierung).
            "_fp_only": loaded and not has_latch and arr_gps != dest,
        })

    # Aktuell offene Flüge (noch verbunden) — bisher komplett ignoriert, da canonicalize_flights
    # logoff_time IS NOT NULL verlangt. Zählen ab dem Live-Ankunfts-Latch, ohne Disconnect.
    returning_cids: set[int] = set()
    returning_aircraft: dict[int, str] = {}  # Muster für Nur-Rückflug-Teilnehmer (nicht im Feed)
    for f in open_transport_flights(conn, callsign_prefix):
        cid = f.get("cid")
        if cid is None:
            continue
        lo = f.get("logon_time") or ""
        if lo < start:
            continue
        dep = _nearest_airport(coords_map, _first_pos(conn, int(cid), lo, now), radius) \
            or normalize_type_code(f.get("departure"))
        if dep not in route_set or dep == dest:
            if dep == dest:
                returning_cids.add(int(cid))
                returning_aircraft.setdefault(
                    int(cid),
                    (f.get("aircraft") or normalize_type_code(f.get("aircraft_icao")) or ""),
                )
            continue
        loaded = bool(dest) and (cid, lo) in live_arrivals
        type_code = normalize_type_code(f.get("aircraft_icao")) or normalize_type_code(f.get("aircraft"))
        if loaded and type_code and type_code not in payload_map:
            unmapped.add(type_code)
        tonnage = round(payload_map.get(type_code, default_kg), 1) if loaded else 0.0
        reserved = 0.0 if loaded else round(payload_map.get(type_code, default_kg), 1)
        if not loaded and type_code and type_code not in payload_map:
            unmapped.add(type_code)   # reservierte Typen dem Admin ebenfalls melden
        network.append({
            "dep_time": lo,
            "cid": cid,
            "callsign": f.get("callsign") or "",
            "aircraft": f.get("aircraft") or type_code,
            "dep": dep,
            "arr": dest,
            "tonnage_kg": tonnage,
            "loaded": loaded,
            "in_air": True,
            "reserved_kg": reserved,
            "flight_key": f"{cid}:{lo}",
            "distance_nm": 0,
            "block_min": 0,
        })

    # Fracht-Verluste anheften: Feed-Zeilen bekommen loss_kind; Verlust-Flüge, die der
    # Strecken-Filter oben verworfen hat (woanders gelandet, dep==arr), erscheinen als
    # eigener Eintrag. kg IMMER live aus aircraft_payloads (type_code, kein Snapshot).
    losses = get_transport_losses(conn, int(event["id"]))
    seen_keys = {q["flight_key"] for q in network}
    loss_by_key: dict[str, dict] = {f"{l['cid']}:{l['logon_time']}": l for l in losses}
    for q in network:
        l = loss_by_key.get(q["flight_key"])
        if not l:
            continue
        if q["loaded"] and q.get("_fp_only") and l["kind"] in ("stolen", "sunk"):
            # GPS-belegter Verlust überstimmt eine Lieferung, die NUR am Flugplan-Text hängt
            # (Live-Befund 02.07.: sonst versinkt nie, wer brav einen Plan zum Ziel aufgibt).
            # Latch-/GPS-Lieferungen bleiben unantastbar — die Verlust-Erkennung überspringt
            # sie bereits beim Erfassen.
            q["loaded"] = False
            q["tonnage_kg"] = 0.0
        if not q["loaded"]:
            q["loss_kind"] = l["kind"]
            q["lost_kg"] = round(payload_map.get(normalize_type_code(l.get("type_code")), default_kg), 1) \
                if l["kind"] in ("stolen", "sunk") else 0.0
    for key, l in loss_by_key.items():
        if key in seen_keys:
            continue
        tc = normalize_type_code(l.get("type_code"))
        lost = round(payload_map.get(tc, default_kg), 1) if l["kind"] in ("stolen", "sunk") else 0.0
        network.append({
            "dep_time": l["logon_time"], "cid": l["cid"], "callsign": l.get("callsign") or "",
            "aircraft": tc, "dep": l.get("dep") or "", "arr": l.get("end_icao") or "—",
            "tonnage_kg": 0.0, "loaded": False, "in_air": False, "reserved_kg": 0.0,
            "flight_key": key, "distance_nm": 0, "block_min": 0,
            "loss_kind": l["kind"], "lost_kg": lost,
        })

    network.sort(key=lambda x: x["dep_time"])  # aufsteigend für die Manifest-Füllung

    # Pilotennamen nachladen (eine Abfrage).
    cids = {q["cid"] for q in network} | returning_cids
    names: dict[int, str] = {}
    if cids:
        rows = conn.execute(
            "SELECT cid, name FROM pilots WHERE cid IN (%s)" % ",".join("?" * len(cids)),
            list(cids),
        ).fetchall()
        names = {r["cid"]: (r["name"] or "") for r in rows}

    cargo = get_transport_cargo(conn, int(event["id"]))
    cargo_targets = [c["target_kg"] for c in cargo]
    delivered = [0.0] * len(cargo)
    _INF = float("inf")

    # Co-Load-Füllung — NUR beladene Flüge. Jeder Flug verteilt seine Zuladung in Manifest-
    # Reihenfolge über die noch nicht vollen Frachtarten, je Frachtart gekappt durch
    # per_flight_max_kg (Obergrenze pro Flug); der Rest fließt in die nächste Frachtart (Co-Load).
    for q in network:
        q["name"] = names.get(q["cid"], "")
        if not q["loaded"]:
            q["cargo_name"] = None
            q["cargo_lines"] = []
            continue
        remaining = q["tonnage_kg"]
        contrib: dict[int, float] = {}
        for i, c in enumerate(cargo):
            if remaining <= 1e-9:
                break
            space = cargo_targets[i] - delivered[i]
            if space <= 1e-9:
                continue
            cap = c.get("per_flight_max_kg")
            cap = cap if (cap is not None and cap > 0) else _INF
            add = min(remaining, cap, space)
            if add <= 1e-9:
                continue
            delivered[i] += add
            remaining -= add
            contrib[i] = contrib.get(i, 0.0) + add
        ordered = sorted(contrib.items(), key=lambda kv: kv[1], reverse=True)
        q["cargo_lines"] = [
            {"name": cargo[i]["name"], "emoji": cargo[i].get("emoji"), "kg": round(kg, 1)}
            for i, kg in ordered
        ]
        q["cargo_name"] = cargo[ordered[0][0]]["name"] if ordered else None

    # Verlorene/zurückgebrachte Ladung aufschlüsseln (reine Anzeige, Nutzer-Wunsch 02.07.:
    # „x Krabbenbrötchen, x Schafe · Kutter versunken"): was hätte der Flug nach denselben
    # Co-Load-Regeln an Bord gehabt? Eigener Topf — ändert delivered/offen nicht.
    lost_alloc = [0.0] * len(cargo)
    for q in network:
        if not q.get("loss_kind"):
            continue
        carried = q.get("lost_kg") or 0.0
        if carried <= 1e-9:  # 'returned' trägt Ladung, verliert sie aber nicht (lost_kg=0)
            carried = round(payload_map.get(normalize_type_code(q.get("aircraft")), default_kg), 1)
        remaining = carried
        contrib = {}
        for i, c in enumerate(cargo):
            if remaining <= 1e-9:
                break
            space = cargo_targets[i] - delivered[i] - lost_alloc[i]
            if space <= 1e-9:
                continue
            cap = c.get("per_flight_max_kg")
            cap = cap if (cap is not None and cap > 0) else _INF
            add = min(remaining, cap, space)
            if add <= 1e-9:
                continue
            lost_alloc[i] += add
            remaining -= add
            contrib[i] = contrib.get(i, 0.0) + add
        ordered = sorted(contrib.items(), key=lambda kv: kv[1], reverse=True)
        q["cargo_lines"] = [
            {"name": cargo[i]["name"], "emoji": cargo[i].get("emoji"), "kg": round(kg, 1)}
            for i, kg in ordered
        ]
        q["cargo_name"] = cargo[ordered[0][0]]["name"] if ordered else None

    # Reservierungen (offene Flüge Richtung Ziel, noch ohne Latch) in die Rest-Kapazität
    # verteilen — gleiche Co-Load-Regeln, aber getrennt von `delivered`: der Fortschritt
    # läuft nie rückwärts, die Reservierung verschwindet mit dem Flug.
    reserved_alloc = [0.0] * len(cargo)
    for q in network:
        r = q.get("reserved_kg") or 0.0
        if q["loaded"] or r <= 1e-9:
            continue
        remaining = r
        for i, c in enumerate(cargo):
            if remaining <= 1e-9:
                break
            space = cargo_targets[i] - delivered[i] - reserved_alloc[i]
            if space <= 1e-9:
                continue
            cap = c.get("per_flight_max_kg")
            cap = cap if (cap is not None and cap > 0) else _INF
            add = min(remaining, cap, space)
            if add <= 1e-9:
                continue
            reserved_alloc[i] += add
            remaining -= add

    # Gecachte KI-Sprüche je Flug anhängen (Phase 2; None wenn deaktiviert/noch nicht erzeugt).
    quips = get_transport_quips(conn, int(event["id"]))
    for q in network:
        q["quip"] = quips.get(q["flight_key"])
        q.pop("_fp_only", None)  # interne Markierung nicht in die API-Antwort leaken

    total_kg = round(sum(q["tonnage_kg"] for q in network), 1)
    loaded_count = sum(1 for q in network if q["loaded"])

    # Pro Frachtart geliefert = tatsächlich zugeordnete Menge aus der Co-Load-Füllung.
    cargo_out: list[dict] = []
    for i, c in enumerate(cargo):
        cargo_out.append({
            "name": c["name"],
            "emoji": c.get("emoji"),
            "target_kg": c["target_kg"],
            "delivered_kg": round(delivered[i], 1),
            "reserved_kg": round(reserved_alloc[i], 1),
            "pct": round(100.0 * delivered[i] / c["target_kg"], 1) if c["target_kg"] > 0 else 0.0,
        })

    target_kg = round(sum(cargo_targets), 1) if cargo_targets else None
    progress_pct = round(100.0 * total_kg / target_kg, 1) if target_kg else None

    # Teilnehmerliste (Bummel-Analogie): eine Zeile pro Pilot mit Summen + Live-Status.
    parts: dict[int, dict] = {}
    for q in network:
        p = parts.setdefault(int(q["cid"]), {
            "cid": int(q["cid"]), "name": q.get("name") or "", "aircraft": q.get("aircraft") or "",
            "flights": 0, "delivered_kg": 0.0, "reserved_kg": 0.0, "lost_kg": 0.0, "status": "done",
        })
        p["flights"] += 1
        if q.get("aircraft"):
            p["aircraft"] = q["aircraft"]
        if q.get("name"):
            p["name"] = q["name"]
        p["delivered_kg"] += q["tonnage_kg"]
        p["lost_kg"] += q.get("lost_kg") or 0.0
        if q.get("in_air"):
            p["status"] = "arrived" if q["loaded"] else "flying"
            if not q["loaded"]:
                p["reserved_kg"] += q.get("reserved_kg") or 0.0
    for rc in returning_cids:
        if rc in parts and parts[rc]["status"] == "done":
            parts[rc]["status"] = "returning"
        elif rc not in parts:
            parts[rc] = {"cid": rc, "name": names.get(rc, ""),
                         "aircraft": returning_aircraft.get(rc, ""), "flights": 0,
                         "delivered_kg": 0.0, "reserved_kg": 0.0, "lost_kg": 0.0, "status": "returning"}
        if rc in parts and not parts[rc]["aircraft"]:
            parts[rc]["aircraft"] = returning_aircraft.get(rc, "")
    participants = sorted(parts.values(), key=lambda x: (-x["delivered_kg"], x["name"]))
    for p in participants:
        p["delivered_kg"] = round(p["delivered_kg"], 1)
        p["reserved_kg"] = round(p["reserved_kg"], 1)
        p["lost_kg"] = round(p["lost_kg"], 1)

    return {
        "route": sorted(route_set),
        "destination": dest,
        "flights": sorted(network, key=lambda x: x["dep_time"], reverse=True),  # neueste oben
        "cargo": cargo_out,
        "total_kg": total_kg,
        "flight_count": len(network),
        "loaded_count": loaded_count,
        "target_kg": target_kg,
        "progress_pct": progress_pct,
        "reserved_total_kg": round(sum(reserved_alloc), 1),
        "unmapped_types": sorted(unmapped),
        "summary_quip": event.get("summary_quip"),
        "losses": [q for q in network if q.get("loss_kind")],
        "lost_total_kg": round(sum(q.get("lost_kg") or 0.0 for q in network), 1),
        "participants": participants,
    }


# ---------------------------------------------------------------------------
# bummel_overrides CRUD
# ---------------------------------------------------------------------------

def upsert_bummel_override(
    conn: sqlite3.Connection,
    race_id: int,
    cid: int,
    action: str,
    manual_total_min: int | None = None,
    note: str | None = None,
) -> None:
    """Teilnehmer-Korrektur setzen oder aktualisieren. action ∈ 'exclude'|'disqualify'|'winner'|'manual'."""
    conn.execute(
        """INSERT INTO bummel_overrides (race_id, cid, action, manual_total_min, note, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(race_id, cid) DO UPDATE SET
               action=excluded.action,
               manual_total_min=excluded.manual_total_min,
               note=excluded.note,
               updated_at=excluded.updated_at""",
        (race_id, cid, action, manual_total_min, note, _now_utc()),
    )


def list_bummel_overrides(conn: sqlite3.Connection, race_id: int) -> list[dict]:
    """Alle Overrides für ein Rennen."""
    rows = conn.execute(
        "SELECT race_id, cid, action, manual_total_min, note, updated_at "
        "FROM bummel_overrides WHERE race_id = ?",
        (race_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_bummel_override(conn: sqlite3.Connection, race_id: int, cid: int) -> None:
    """Einen einzelnen Override löschen."""
    conn.execute(
        "DELETE FROM bummel_overrides WHERE race_id = ? AND cid = ?",
        (race_id, cid),
    )


# ---------------------------------------------------------------------------
# Override-Anwendung auf die Wertung (reine Funktion)
# ---------------------------------------------------------------------------

def apply_bummel_overrides(standings: dict, overrides: list[dict]) -> dict:
    """Override-Anwendung auf eine compute_bummel_standings-Wertung.

    Reine Funktion — das Eingabe-Dict wird nicht mutiert (tiefe Kopien).
    Gibt ein neues standings-Dict zurück mit ``disqualified``-Liste (evtl. leer).

    Reihenfolge der Schritte:
    1. exclude  → cid aus complete UND incomplete entfernen
    2. manual   → total_min setzen, aus incomplete nach complete verschieben
    3. disqualify → cid aus complete in disqualified schieben
    4. Schnitt, delta, rank neu berechnen
    5. winner   → cid an Position 0 (rank 1) zwingen, forced_winner=True
    6. participant_count = distinct cids in complete + incomplete + disqualified
    """
    import copy

    result = copy.deepcopy(standings)
    complete: list[dict] = result["complete"]
    incomplete: list[dict] = result["incomplete"]
    disqualified: list[dict] = []

    # Schritt 1: exclude
    exclude_cids = {ov["cid"] for ov in overrides if ov.get("action") == "exclude"}
    if exclude_cids:
        result["complete"] = [e for e in complete if e["cid"] not in exclude_cids]
        result["incomplete"] = [e for e in incomplete if e["cid"] not in exclude_cids]
        complete = result["complete"]
        incomplete = result["incomplete"]

    # Schritt 2: manual
    for ov in overrides:
        if ov.get("action") != "manual":
            continue
        cid = ov["cid"]
        mtm = ov.get("manual_total_min")
        if mtm is None:
            continue
        # Eintrag in complete oder incomplete suchen
        entry = next((e for e in complete if e["cid"] == cid), None)
        if entry is None:
            inc_entry = next((e for e in incomplete if e["cid"] == cid), None)
            if inc_entry is None:
                continue  # Kein Stub — überspringen
            incomplete.remove(inc_entry)
            complete.append(inc_entry)
            entry = inc_entry
        entry["total_min"] = mtm

    # Schritt 3: disqualify
    disqualify_cids = {ov["cid"] for ov in overrides if ov.get("action") == "disqualify"}
    if disqualify_cids:
        new_complete: list[dict] = []
        for e in complete:
            if e["cid"] in disqualify_cids:
                disqualified.append(e)
            else:
                new_complete.append(e)
        result["complete"] = new_complete
        complete = result["complete"]

    # Schritt 4: Schnitt, delta, rank neu berechnen
    if complete:
        avg = sum(e["total_min"] for e in complete) / len(complete)
        result["average_min"] = round(avg, 1)
    else:
        result["average_min"] = 0.0
    result["count"] = len(complete)

    for e in complete:
        e["delta"] = round(abs(e["total_min"] - result["average_min"]), 1)
    complete.sort(key=lambda e: (e["delta"], e["total_min"], e["cid"]))
    for rank, e in enumerate(complete, 1):
        e["rank"] = rank

    # Schritt 5: winner
    for ov in overrides:
        if ov.get("action") != "winner":
            continue
        winner_cid = ov["cid"]
        winner_idx = next((i for i, e in enumerate(complete) if e["cid"] == winner_cid), None)
        if winner_idx is None:
            continue
        winner_entry = complete.pop(winner_idx)
        winner_entry["forced_winner"] = True
        complete.insert(0, winner_entry)
        for rank, e in enumerate(complete, 1):
            e["rank"] = rank

    # Schritt 6: participant_count
    all_cids = (
        {e["cid"] for e in complete}
        | {e["cid"] for e in incomplete}
        | {e["cid"] for e in disqualified}
    )
    result["participant_count"] = len(all_cids)
    result["disqualified"] = disqualified

    return result


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


def get_push_subscriptions_for_events(conn: sqlite3.Connection) -> list[dict]:
    """Subscriptions mit aktiviertem Events-Abo (notify_events=1) — für Event-Erinnerungen und
    Bummel-Start/Ergebnis-Pushs. Kein pilot_filter (Events sind nicht pilotbezogen)."""
    rows = conn.execute(
        "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE notify_events = 1"
    ).fetchall()
    return [dict(r) for r in rows]


def events_due_for_reminder(
    conn: sqlite3.Connection, now: str, lead_min: int = 60
) -> list[dict]:
    """FriesenEvents, deren Erinnerung jetzt fällig ist: dtstart liegt im Fenster (now, now+lead_min]
    und es wurde noch keine Erinnerung verschickt (event_reminders_sent)."""
    until = (_parse_iso(now) + timedelta(minutes=lead_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT uid, summary, dtstart, dtend, location, route, is_bummel FROM calendar_events "
        "WHERE dtstart > ? AND dtstart <= ? "
        "AND uid NOT IN (SELECT uid FROM event_reminders_sent) "
        "ORDER BY dtstart",
        (now, until),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_event_reminded(conn: sqlite3.Connection, uid: str, ts: str) -> None:
    """Erinnerung für ein Event als verschickt markieren (Dedup, idempotent)."""
    conn.execute(
        "INSERT OR IGNORE INTO event_reminders_sent (uid, sent_at) VALUES (?, ?)",
        (uid, ts),
    )


def get_ts_consent(conn: sqlite3.Connection, frs: str) -> dict | None:
    """Einwilligungs-Eintrag für eine FRS-Nummer, oder None (= Default 'everyone').

    allowlist wird aus JSON zu einer Liste geparst (oder []).
    """
    row = conn.execute(
        "SELECT frs, visibility, allowlist, updated_at FROM ts_consent WHERE frs = ?",
        (frs,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["allowlist"] = json.loads(d["allowlist"]) if d["allowlist"] else []
    except (json.JSONDecodeError, TypeError):
        d["allowlist"] = []
    return d


def upsert_ts_consent(
    conn: sqlite3.Connection,
    frs: str,
    visibility: str,
    allowlist: list[str] | None = None,
) -> None:
    """Einwilligung pro FRS setzen. visibility ∈ {'everyone','nobody','allowlist'}."""
    conn.execute(
        """INSERT INTO ts_consent (frs, visibility, allowlist, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(frs) DO UPDATE SET
               visibility=excluded.visibility,
               allowlist=excluded.allowlist,
               updated_at=excluded.updated_at""",
        (
            frs, visibility,
            json.dumps(allowlist) if allowlist is not None else None,
            _now_utc(),
        ),
    )


def cid_for_callsign(conn: sqlite3.Connection, callsign: str) -> int | None:
    """CID zu einem FRS-/Callsign-String, oder None (nie auf VATSIM gesehen).

    Quelle in Reihenfolge: aktuelle live_positions, jüngster flights-Eintrag,
    statsim_cache. Vergleich case-insensitiv/getrimmt.
    """
    cs = (callsign or "").strip().upper()
    if not cs:
        return None
    for q in (
        "SELECT cid FROM live_positions WHERE UPPER(callsign) = ? LIMIT 1",
        "SELECT cid FROM flights WHERE UPPER(callsign) = ? ORDER BY logon_time DESC LIMIT 1",
        "SELECT cid FROM statsim_cache WHERE UPPER(callsign) = ? ORDER BY logon_time DESC LIMIT 1",
    ):
        row = conn.execute(q, (cs,)).fetchone()
        if row is not None and row[0] is not None:
            return int(row[0])
    return None


def get_ts_push_subscriptions(conn: sqlite3.Connection, cid: int | None) -> list[dict]:
    """TS-Opt-in-Subscriptions (notify_ts = 1), gefiltert über pilot_filter.

    pilot_filter NULL = alle; sonst nur wenn cid in der JSON-Liste. cid None
    (reine TS-Leute ohne CID) → nur die NULL-Filter-Subscriptions. Defektes
    pilot_filter-JSON wird (wie get_push_subscriptions_for_pilot) als "alle" gewertet.
    """
    rows = conn.execute(
        "SELECT endpoint, p256dh, auth, pilot_filter FROM push_subscriptions WHERE notify_ts = 1"
    ).fetchall()
    result = []
    for row in rows:
        pf = row["pilot_filter"]
        if pf is None:
            result.append({"endpoint": row["endpoint"], "p256dh": row["p256dh"], "auth": row["auth"]})
        elif cid is not None:
            try:
                if cid in json.loads(pf):
                    result.append({"endpoint": row["endpoint"], "p256dh": row["p256dh"], "auth": row["auth"]})
            except (json.JSONDecodeError, TypeError):
                result.append({"endpoint": row["endpoint"], "p256dh": row["p256dh"], "auth": row["auth"]})
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
