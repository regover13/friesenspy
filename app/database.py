"""SQLite WAL-Mode Datenbank-Layer für FriesenSpy."""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Reine Zustandsmaschine ohne DB-Abhaengigkeit (importiert nichts aus app.*) -> kein Zyklus,
# darf auf Modulebene stehen. compute_transport_progress + transport_anyone_in_progress nutzen sie.
from app.transport_stacks import derive_stacks, STOLEN, SUNK

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS pilots (
    cid       INTEGER PRIMARY KEY,
    name      TEXT,
    added_at  TEXT,
    -- Admin-Checkbox „Aktiv": 0 schließt die CID überall aus (Live-Erkennung UND Statistik).
    -- Steht bewusst AUCH hier und nicht nur in _PILOTS_MIGRATIONS: Frisch angelegte
    -- Datenbanken (u. a. in Tests) bekamen die Spalte sonst nie, und jede Auswertung, die
    -- gesperrte CIDs herausfiltert, lief ins Leere.
    active    INTEGER NOT NULL DEFAULT 1
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
    -- ACHTUNG: "zuletzt berührt", NICHT "erstmals geholt". Der StatSim-Abruf holt immer das
    -- ganze Fenster (31 Tage bzw. 365 bei Vollabruf) und schreibt per INSERT OR REPLACE JEDE
    -- Zeile neu, auch die unveränderten -- fetched_at springt dabei auf jetzt (upsert_statsim_
    -- flights). Ein Flug von vor drei Wochen kann also ein fetched_at von heute tragen.
    -- Taugt deshalb NICHT für "seit wann kennen wir diesen Flug?" und nicht als Beleg dafür,
    -- dass ein Flug neu dazugekommen ist (2026-08-05 genau so fehlgedeutet: 10 gleichzeitig
    -- aktualisierte Zeilen sahen aus wie 10 neue Flüge). Wofür es taugt: Cache-Alter je Pilot
    -- (get_statsim_last_fetched -> 24-h-Cooldown in main.py).
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

-- Hinweis: 'ts_consent' (Phase 1) ist ersatzlos entfallen — 'pilot_visibility' hat es abgelöst
-- (Subjekt-Sichtbarkeit). Bestehende DBs behalten ihre Tabelle unangetastet; sie wird von
-- keinem Code mehr gelesen oder geschrieben. Neue DBs legen sie nicht mehr an.

CREATE TABLE IF NOT EXISTS pilot_visibility (
    cid        INTEGER PRIMARY KEY,
    mode       TEXT NOT NULL DEFAULT 'everyone',   -- 'everyone' | 'allowlist' | 'nobody'
    allowlist  TEXT,                               -- JSON-Liste erlaubter CIDs (nur bei 'allowlist')
    services   TEXT,                               -- JSON-Liste betroffener Services; NULL = alle
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS forum_callsign (
    callsign   TEXT PRIMARY KEY,                   -- UPPER, getrimmt (z. B. 'FRS49N')
    cid        INTEGER NOT NULL,
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
    reveal_suppressed INTEGER DEFAULT 0, -- 1 = manuell verborgen, übersteuert den Auto-Reveal
    manual_fields  TEXT,                 -- #19: CSV der im Admin von Hand gesetzten Felder
    badge_name     TEXT                  -- Kurzname fuers Badge-PNG; leer = name
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
    created_at     TEXT,
    manual_fields  TEXT,                 -- #19: CSV der im Admin von Hand gesetzten Felder
    badge_name     TEXT                  -- Kurzname fuers Badge-PNG; leer = name
);

CREATE TABLE IF NOT EXISTS transport_cargo (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id  INTEGER NOT NULL,          -- REFERENCES transport_events(id)
    position  INTEGER NOT NULL,          -- Beladungsreihenfolge
    name      TEXT NOT NULL,             -- Frachtart, z. B. "Fischbrötchen"
    target_kg REAL NOT NULL,
    emoji     TEXT,                      -- Snapshot aus dem Katalog (für den Feed)
    per_flight_max_kg REAL,              -- Obergrenze pro Flug (Co-Load); NULL = keine Kappung
    departure TEXT,                      -- #15 Sub-Projekt B: gebundener Startplatz-ICAO; NULL = geteilt
    added_at  TEXT                       -- ISO-UTC: wann die Zeile ins Manifest kam; NULL = "schon immer da"
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
    fuel_full_kg REAL,                   -- max. Tankinhalt (volle Tanks); fuel_kg = Hälfte davon
    crew_kg     REAL,                    -- Pilot/Crew (editierbar) — Default 85 kg, zählt nicht als Fracht
    payload_kg  REAL NOT NULL,           -- = max(0, mtow_kg − empty_kg − fuel_kg − crew_kg); direkt überschreibbar
    source      TEXT,                    -- 'manual' | 'llm' | 'curated' | 'default'
    make_model  TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS payload_research (
    type_code   TEXT PRIMARY KEY,   -- normalize_type_code()
    state       TEXT NOT NULL,      -- 'ok' | 'nichts_gefunden' | 'fehler'
    attempts    INTEGER NOT NULL DEFAULT 0,
    checked_at  TEXT,
    last_error  TEXT
);

CREATE TABLE IF NOT EXISTS aircraft_types (
    type_code           TEXT PRIMARY KEY,   -- normalize_type_code()
    alias_of            TEXT,               -- Tippfehler-Kürzel → echtes Muster (ein Schritt)

    -- importiert: NUR der Import schreibt diese Spalten
    name                TEXT,
    name_source         TEXT,               -- 'payloads' | 'llm'
    wiki_lang           TEXT,               -- 'de' | 'en'
    wiki_title          TEXT,
    extract             TEXT,
    photo_file          TEXT,
    photo_licence       TEXT,
    photo_artist        TEXT,
    photo_source_url    TEXT,

    -- Korrektur: NUR der Admin schreibt diese Spalten
    name_override       TEXT,
    extract_override    TEXT,
    wiki_title_override TEXT,
    photo_override      TEXT,               -- NULL | '-' (kein Foto) | 'blob' (Upload)
    photo_blob          BLOB,
    photo_credit        TEXT,

    -- Zustand
    fetch_state         TEXT,               -- 'neu' | 'ok' | 'nichts_gefunden' | 'fehler'
    attempts            INTEGER NOT NULL DEFAULT 0,
    checked_at          TEXT,
    last_error          TEXT,
    updated_at          TEXT,

    CHECK (photo_override IS NULL OR photo_override IN ('-', 'blob')),
    CHECK (photo_override <> 'blob' OR photo_blob IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS custom_airports (
    icao          TEXT PRIMARY KEY,     -- ICAO ODER Platzhalter-Code (z. B. "ZZSALZ", kein echter ICAO)
    name          TEXT,                 -- reine Anzeige, keine Funktionswirkung
    lat           REAL NOT NULL,
    lon           REAL NOT NULL,
    elevation_ft  REAL,                 -- NULL wenn unbekannt (macht Rettung/Spawn-Guard konservativ)
    radius_km     REAL,                 -- NULL = Standard-Suchradius (Großflughafen-Override, #62)
    reason        TEXT,                 -- WARUM ergänzt/überschrieben (#78); NULL erlaubt, nie Pflicht
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS airport_links (
    icao          TEXT PRIMARY KEY,     -- ICAO-Code (Großbuchstaben)
    aip_url       TEXT NOT NULL,        -- Link zur amtlichen DFS-AIP-VFR-Flugplatzkarte (aip.dfs.de)
    updated_at    TEXT
);

-- STILLGELEGT seit 31.08.2026: abgeloest von aip_charts_dfs. Die Tabelle bleibt stehen,
-- bis der neue Stand geprueft ist (Spec 3.1) -- sie traegt 446 Zeilen, darunter 171
-- Handpassungen, aus denen die Migration liest.
CREATE TABLE IF NOT EXISTS aip_charts (
    icao          TEXT PRIMARY KEY,     -- ICAO-Code (Grossbuchstaben)
    bild_hash     TEXT NOT NULL,        -- SHA-256 des Originalblatts, erkennt den AIRAC-Wechsel
    nord          REAL NOT NULL,        -- Grenzen des GANZEN Blatts: danach wird platziert
    sued          REAL NOT NULL,
    west          REAL NOT NULL,
    ost           REAL NOT NULL,
    feld_nord     REAL NOT NULL,        -- Grenzen des KARTENFELDS: danach schaltet die
    feld_sued     REAL NOT NULL,        -- Automatik, und der Lagetest prueft dagegen.
    feld_west     REAL NOT NULL,        -- Das Blatt ist rund 1,8x so hoch wie das Feld.
    feld_ost      REAL NOT NULL,
    rahmen_px     TEXT NOT NULL,        -- "links,oben,rechts,unten" fuer den Geometrievergleich
    tick_px_lat   REAL NOT NULL,
    tick_px_lon   REAL NOT NULL,
    seite_url     TEXT NOT NULL DEFAULT '',  -- gewaehlte Kapitelseite; Teil der Handkorrektur
    quelle        TEXT NOT NULL,        -- 'auto' oder 'hand'
    airac         TEXT NOT NULL,
    status        TEXT NOT NULL,        -- 'gepasst' oder 'ungepasst'
    geprueft_am   TEXT
);

-- Flugplatzkarten (Aerodrome Chart / Ground Movement Chart).
--
-- STILLGELEGT seit 31.08.2026: abgeloest von aip_charts_dfs. Die Tabelle bleibt stehen,
-- bis der neue Stand geprueft ist (Spec 3.1) -- sie traegt 110 Zeilen, aus denen die
-- Migration liest.
--
-- Eigene Tabelle, nicht eine Erweiterung von aip_charts: Die Felder sind zu verschieden.
-- Eine Flugplatzkarte hat keinen Rahmen, keine Ticks und keine Gradnetz-Beschriftung,
-- dafuer einen Drehwinkel, einen Massstab, eine Sorte und einen Restfehler. Zusammengelegt
-- waere die Haelfte jeder Zeile leer.
CREATE TABLE IF NOT EXISTS aip_ground_charts (
    icao          TEXT PRIMARY KEY,
    sorte         TEXT NOT NULL,        -- 'rollkarte' oder 'flugplatzkarte'
    seite_url     TEXT NOT NULL DEFAULT '',
    quell_hash    TEXT NOT NULL,        -- SHA-256 des ROHblatts: DAS ist der
                                        -- Aenderungsdetektor.
    bild_hash     TEXT NOT NULL,        -- SHA-256 des genordeten Blatts, nur fuer die URL.
                                        -- NIE als Aenderungsdetektor: Er haengt am
                                        -- Resampling des Drehens, ein Pillow-Update
                                        -- aenderte ihn ohne jede inhaltliche Aenderung.
    nord          REAL NOT NULL,        -- Grenzen des GENORDETEN Blatts
    sued          REAL NOT NULL,
    west          REAL NOT NULL,
    ost           REAL NOT NULL,
    feld_nord     REAL NOT NULL,        -- Huelle der Bahnen plus Saum: danach schaltet die
    feld_sued     REAL NOT NULL,        -- Automatik. NICHT die Blattgrenzen -- nach dem
    feld_west     REAL NOT NULL,        -- Drehen zeigt das Blatt viel freie Flaeche.
    feld_ost      REAL NOT NULL,
    drehung       REAL NOT NULL,        -- Grad, im Uhrzeigersinn gegen Nord
    mps           REAL NOT NULL,        -- Meter je Pixel im ROHblatt
    rest_max      REAL NOT NULL,        -- groesster Restfehler in Metern
    bahnen        INTEGER NOT NULL,     -- Zahl der zur Passung verwendeten Bahnen
    quelle        TEXT NOT NULL,        -- 'auto' oder 'hand' -- 'hand' ist eine SPERRE
    airac         TEXT NOT NULL,
    status        TEXT NOT NULL,        -- 'gepasst', 'ungepasst' oder 'verwaist'
    geprueft_am   TEXT
);

-- Beide Kartentypen in EINER Tabelle -- Nachfolgerin von aip_charts und aip_ground_charts.
--
-- Der Schluessel ist zweiteilig, weil ein Platz eine Sichtflugkarte UND eine Flugplatzkarte
-- haben kann: Gemessen am 31.08.2026 trifft das auf ALLE 110 Plaetze mit Flugplatzkarte zu.
-- Mit icao allein kollidierten genau diese 110 Zeilen.
--
-- Es gibt keine Automatik mehr (Nutzerentscheidung 31.08.2026). Eine Passung entsteht
-- ausschliesslich aus zwei geklickten Punkten mit Koordinaten; der Wochenlauf vergleicht
-- nur noch Hashes. Wer hier Rahmenerkennung oder Ziffernlesen zurueckbaut, baut etwas
-- zurueck, das bewusst entfernt wurde.
CREATE TABLE IF NOT EXISTS aip_charts_dfs (
    icao          TEXT NOT NULL,
    sorte         TEXT NOT NULL,              -- 'sichtflug'|'flugplatzkarte'|'rollkarte'
    -- Die SEITENNUMMER im Kapitel, NICHT die URL: die enthaelt den AIRAC
    -- (https://aip.dfs.de/BasicVFR/2026AUG20/pages/8E6E....html) und liefert nach dem
    -- naechsten Zyklus 404 -- fuer ALLE Zeilen gleichzeitig, und zwar genau dann, wenn
    -- sich Blaetter tatsaechlich aendern koennten. Der dauerhafte Bezeichner ist
    -- airport_links.aip_url (ohne AIRAC, Meta-Refresh); der Job loest daraus frisch auf.
    seite_nr      INTEGER,
    -- SHA-256 der DFS-ROHbytes, ueber die zuletzt jemand geurteilt hat. NICHT der Hash der
    -- Datei auf der Platte: nach einem 'verwerfen' fallen die beiden auseinander. Hiess
    -- bis 31.08.2026 quell_hash -- der Name log ab genau diesem Punkt.
    gesehener_hash TEXT NOT NULL DEFAULT '',
    bild_hash     TEXT NOT NULL DEFAULT '',   -- des ABGELEGTEN Blatts, nur Cache-Schluessel
    nord          REAL NOT NULL DEFAULT 0,    -- Grenzen des ganzen Blatts: danach platziert
    sued          REAL NOT NULL DEFAULT 0,
    west          REAL NOT NULL DEFAULT 0,
    ost           REAL NOT NULL DEFAULT 0,
    feld_nord     REAL NOT NULL DEFAULT 0,    -- Grenzen des KARTENFELDS: danach schaltet
    feld_sued     REAL NOT NULL DEFAULT 0,    -- die Ebene. NICHT die Blattgrenzen -- diese
    feld_west     REAL NOT NULL DEFAULT 0,    -- Verwechslung war der 45-Prozent-Fehler.
    feld_ost      REAL NOT NULL DEFAULT 0,
    drehung       REAL NOT NULL DEFAULT 0,    -- Grad, im Uhrzeigersinn gegen Nord
    mps           REAL NOT NULL DEFAULT 0,    -- Meter je Pixel im Rohblatt
    -- Die beiden geklickten Passpunkte. Bei den Sichtflugkarten aus rahmen_px gewonnen:
    -- Die Spalte war dort das Klickprotokoll, keine Innerei der Automatik.
    p1_x REAL, p1_y REAL, p1_lat REAL, p1_lon REAL,
    p2_x REAL, p2_y REAL, p2_lat REAL, p2_lon REAL,
    -- gepasst|auto|offen|nicht_gefunden|pruefen|verwaist. 'pruefen' OHNE Umlaut: der Wert
    -- wird in Python, SQL, JavaScript und Testliteralen verglichen.
    status        TEXT NOT NULL,
    status_vorher TEXT,                       -- woher 'pruefen' kam; 'verwerfen' stellt es
                                              -- zurueck. Nur 'gepasst' oder 'auto': eine
                                              -- Karte ohne Passung geht nie nach 'pruefen'.
    airac         TEXT NOT NULL DEFAULT '',
    geprueft_am   TEXT,
    PRIMARY KEY (icao, sorte)
);

-- Wann ein wiederkehrender Job zuletzt wirklich gearbeitet hat.
--
-- APScheduler haelt seine Jobs im MemoryJobStore: Jeder Containerstart meldet sie neu an,
-- und "interval, weeks=1" plant den ersten Lauf eine Woche SPAETER. Der AIP-Auffrischlauf
-- hat deshalb von seiner Einfuehrung bis zum 31.08.2026 kein einziges Mal gearbeitet.
--
-- Ein fester next_run_time kurz nach dem Start behebt das, macht daraus aber einen
-- Deploy-Job: Der Lauf holt ueber 1000 Seiten von aip.dfs.de, und an einem Tag mit zwoelf
-- Deploys waeren das zwoelf Vollcrawls. Erst dieser Merker macht "woechentlich" wirklich
-- woechentlich, unabhaengig davon, wie oft der Container neu startet.
CREATE TABLE IF NOT EXISTS job_laeufe (
    name          TEXT PRIMARY KEY,
    zuletzt       TEXT NOT NULL
);

-- STILLGELEGT seit 31.08.2026. Vorschlaege waren Automatikfunde zu handgepassten Karten,
-- die NICHT eingespielt, sondern zur Pruefung vorgelegt wurden. Ohne Automatik gibt es
-- nichts vorzuschlagen; an ihre Stelle tritt der Status 'pruefen' in aip_charts_dfs.
--
-- Ihr Grabstein-Gedanke lebt dort weiter: Auch "verwerfen" zieht den gesehener_hash nach.
-- Sonst faende der naechste Wochenlauf denselben abweichenden Hash und legte die Zeile
-- sofort wieder vor -- die Liste waere nach dem ersten Verwerfen dauerhaft unaufraeumbar.
--
-- Die Tabelle bleibt stehen, bis der neue Stand geprueft ist (Spec 3.1). Ein DROP waere
-- der einzige Weg, sie loszuwerden, und ist eine eigene, bewusste Entscheidung.
CREATE TABLE IF NOT EXISTS aip_chart_vorschlaege (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    art           TEXT NOT NULL,        -- 'sichtflug' oder 'ground'
    icao          TEXT NOT NULL,
    quell_hash    TEXT NOT NULL,        -- welches Rohblatt der Vorschlag betrifft
    passung       TEXT NOT NULL,        -- JSON; die Form haengt an 'art'
    grund         TEXT NOT NULL,
    zustand       TEXT NOT NULL,        -- 'offen' oder 'verworfen'
    gefunden_am   TEXT NOT NULL,
    UNIQUE(art, icao, quell_hash)
);

CREATE TABLE IF NOT EXISTS flight_cache (
    cache_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    id                INTEGER,              -- Flugplan-/Connection-id aus canonicalize_legs (kann NULL sein)
    cid               INTEGER,
    callsign          TEXT,
    aircraft          TEXT,
    departure         TEXT,
    arrival           TEXT,
    logon_time        TEXT NOT NULL,        -- takeoff_ts, immer gesetzt
    logoff_time       TEXT,                 -- landing_ts, NULL bei offenem Flug
    duration_min      INTEGER,
    distance_nm       REAL,
    block_min         INTEGER,
    route             TEXT,
    remarks           TEXT,
    cruise_altitude   TEXT,
    cruise_tas        TEXT,
    flight_rules      TEXT,
    aircraft_icao     TEXT,
    alternate         TEXT,
    deptime           TEXT,
    enroute_time      TEXT,
    fuel_time         TEXT,
    source            TEXT,
    gps_departure     TEXT,
    gps_arrival       TEXT,
    plan_departure    TEXT,
    plan_arrival      TEXT,
    connection_closed INTEGER,              -- 0/1
    computed_at       TEXT,
    UNIQUE(cid, logon_time)
);
CREATE INDEX IF NOT EXISTS idx_flight_cache_logon ON flight_cache(logon_time);

CREATE TABLE IF NOT EXISTS gps_detection_dismissals (
    cid           INTEGER NOT NULL,
    logon_time    TEXT NOT NULL,
    dismissed_at  TEXT,
    PRIMARY KEY (cid, logon_time)
);

CREATE TABLE IF NOT EXISTS progress_snapshot (
    kind         TEXT NOT NULL,
    ref_id       INTEGER NOT NULL,
    code_version TEXT NOT NULL,
    computed_at  TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id)
);

-- Selbstdiagnose des MSFS-EFB-Panels: Die Rendering-Engine dort (Coherent GT) laesst sich
-- praktisch nicht von aussen untersuchen -- der SDK-Debugger stuerzt ab, und jede Frage
-- ("rendert Zeichen X?", "kennt die Engine max-content?") kostete bisher eine Rueckfrage an
-- den Nutzer am Sim. Stattdessen meldet das Panel seine Fehler und Messwerte selbst hierher;
-- auswertbar per Admin-Ansicht oder direkt per sqlite3 auf dem VPS. Bewusst schemalos
-- (payload_json), weil sich die Messfragen mit jedem Fund aendern.
CREATE TABLE IF NOT EXISTS panel_diag (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    app_version  TEXT,
    user_agent   TEXT,
    cid          INTEGER,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_panel_diag_created ON panel_diag(created_at DESC);

-- Geraete-Bindung fuers MSFS-EFB-Panel: Coherent GT haelt Cookies offenbar nur im Speicher,
-- weshalb die Anmeldung jeden Sim-Neustart verlor -- fuer den Nutzer unzumutbar. Das
-- EFB-Paket legt stattdessen eine Zufalls-Geraete-ID in MSFS' plattenpersistentem Speicher
-- ab (DataStore -> SetStoredData); nach EINER erfolgreichen Forum-Anmeldung wird sie hier an
-- die CID gebunden und der Panel-Aufruf kann sich damit ausweisen.
--
-- WICHTIG: device_id ist ein Zugangsschluessel -- wer ihn hat, ist als dieser Nutzer
-- angemeldet. Er verlaesst die lokale MSFS-Installation nicht, und jede Bindung ist im
-- Admin einzeln widerrufbar (bewusste Entscheidung gegen ein Ablaufdatum, damit genau das
-- Problem "staendig neu anmelden" nicht durch die Hintertuer zurueckkommt).
CREATE TABLE IF NOT EXISTS panel_devices (
    device_id    TEXT PRIMARY KEY,
    cid          INTEGER NOT NULL,
    name         TEXT,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT,
    -- Welche Paketfassung im Community-Ordner liegt (ab Paket 2.0.0 beim Anmelden gemeldet).
    -- NULL heisst "aelter als 2.0.0 oder seither nicht gestartet", nicht "unbekannt".
    paket_version TEXT
);

-- Karten-Merker (Basiskarte, Ebenen, Track-up, Moving Map, zuletzt betrachteter Ausschnitt).
--
-- Sie liegen hier und NICHT im Browser, weil im Kniebrett kein Browser-Speicher haelt: Beim
-- Sim-Start ist der gesamte Bereich leer -- gemessen am 16.08.2026, `localStorage` faellt von
-- 8 Schluesseln auf 0, das Merker-Cookie ist fort. Zwei Anlaeufe ueber localStorage bzw. ein
-- Cookie sind daran gescheitert; es steht schon zwei Tabellen weiter oben, warum (s.
-- panel_devices). Was dort ueberlebt, ist allein die Geraete-ID in MSFS' eigener Ablage --
-- genau der Weg, den auch Avionik-Erweiterungen wie das GTN 750 gehen.
--
-- Schluessel ist CID + Kontext, nicht die Geraete-ID: Die Seite kennt ihre Geraete-ID
-- bewusst nicht (sie ist ein Zugangsschluessel und bleibt aus der Adresse heraus, s.
-- /auth/device). Der Kontext trennt Kniebrett und Website, damit die Karteneinstellung am
-- Schreibtisch nicht die im Cockpit umstellt.
--
-- Schemalos als JSON, aus demselben Grund wie panel_diag: Welche Merker es gibt, aendert sich
-- mit jeder Ebene, die dazukommt. Die Groessengrenzen stehen an der API (s. main.py).
CREATE TABLE IF NOT EXISTS panel_prefs (
    cid        INTEGER NOT NULL,
    kontext    TEXT NOT NULL,
    prefs_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (cid, kontext)
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
    # owner_cid: Besitzer-CID des Abos (aus dem Forum-Login) — für die Subjekt-Allowlist.
    "ALTER TABLE push_subscriptions ADD COLUMN owner_cid INTEGER DEFAULT NULL",
    # Zustellungs-Diagnose (Push-Overview): Ergebnis des jeweils letzten echten Versands.
    # last_ok_at = letzter erfolgreicher Handshake mit dem Push-Dienst (kein Beweis, dass der
    # Nutzer die Meldung gesehen hat — das kann Web-Push nicht zurückmelden). last_fail_at/
    # last_status = letzter fehlgeschlagener Versand + HTTP-Code (410 löscht das Abo ohnehin).
    "ALTER TABLE push_subscriptions ADD COLUMN last_ok_at TEXT",
    "ALTER TABLE push_subscriptions ADD COLUMN last_fail_at TEXT",
    "ALTER TABLE push_subscriptions ADD COLUMN last_status TEXT",
]

_AIP_CHARTS_MIGRATIONS = [
    # seite_url: WELCHE Kapitelseite gilt. Nachgetragen am 31.08.2026.
    #
    # Die Seitenwahl ist Teil der Handkorrektur und ging bis dahin spurlos verloren. Bei
    # EDDK enthaelt das Kapitel sechs Seiten, und die automatisch gewaehlte war die falsche
    # (Nutzer, 24.08.2026); der Admin konnte sie festlegen, aber aip_charts merkte es sich
    # nicht. Der naechste Auffrischlauf rief blatt_beschaffen(url, ...), und die nimmt
    # wieder "die erste Seite, deren Passung durchgeht" -- also erneut die falsche.
    #
    # Das Tueckische daran: Es geschieht, OHNE dass quelle je auf 'hand' steht. Die Sperre
    # in upsert_aip_chart sieht davon nichts. Eine Handkorrektur kann also auch ohne jedes
    # Ueberschreiben verlorengehen.
    "ALTER TABLE aip_charts ADD COLUMN seite_url TEXT NOT NULL DEFAULT ''",
]

_PANEL_DIAG_MIGRATIONS = [
    # cid: WER hat gemeldet. Nachgetragen am 30.08.2026, weil eine Auswertung ohne sie nicht
    # moeglich war: Am selben Vormittag flogen zwei Mitglieder gemeinsam in South Dakota,
    # beide mit offenem Kniebrett. Ihre Meldungen landeten ununterscheidbar in derselben
    # Tabelle -- gleicher User-Agent (CoherentGT), gleiche App-Version, teils gleiche
    # Fenstergroesse. Zwei Meldungen im Abstand EINER Sekunde zeigten widerspruechliche
    # Ebenen-Zustaende, was wie ein Fehler aussah und keiner war: Es waren schlicht zwei
    # Leute. Ohne diese Spalte ist jede Messung mehrdeutig, sobald mehr als einer fliegt.
    #
    # Best effort und bewusst NULLABLE: Der Endpunkt verlangt keine Anmeldung (s. dortiger
    # Docstring) -- gerade die Faelle, in denen die Anmeldung scheitert, sollen meldbar
    # bleiben. Steht kein Sitzungs-Cookie an, bleibt die Spalte leer.
    "ALTER TABLE panel_diag ADD COLUMN cid INTEGER",
]

_VISIBILITY_MIGRATIONS = [
    # services: JSON-Liste der Services, für die die Sichtbarkeits-Einschränkung gilt
    # (NULL = alle — Backward-Compat für Zeilen vor dieser Spalte).
    "ALTER TABLE pilot_visibility ADD COLUMN services TEXT",
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
    # #19: welche Felder ein Mensch im Admin gesetzt hat — der Kalender-Sync
    # laesst genau diese in Ruhe (Regel 2, Variante "je Feld").
    "ALTER TABLE bummel_races ADD COLUMN manual_fields TEXT",
    # Der Event-Name sprengt die runde Grafik ("Montagsfluege in Deutschland - Aach-Bummel").
    # Leer = weiter der Event-Name, damit eine spaetere Umbenennung im Badge ankommt.
    "ALTER TABLE bummel_races ADD COLUMN badge_name TEXT",
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
    # #19: siehe bummel_races.manual_fields.
    "ALTER TABLE transport_events ADD COLUMN manual_fields TEXT",
    # badge_name: siehe bummel_races.
    "ALTER TABLE transport_events ADD COLUMN badge_name TEXT",
    # destination: Ziel-ICAO — nur Flüge dorthin laden Fracht (Rückflug leer).
    "ALTER TABLE transport_events ADD COLUMN destination TEXT",
    # crew_kg: Pilot/Crew-Gewicht — zählt nicht als Fracht (payload = mtow − empty − fuel − crew).
    "ALTER TABLE aircraft_payloads ADD COLUMN crew_kg REAL",
    # fuel_full_kg: max. Tankinhalt (volle Tanks); fuel_kg bleibt das Rechenfeld (Hälfte davon).
    "ALTER TABLE aircraft_payloads ADD COLUMN fuel_full_kg REAL",
    # Phase 2: Fracht-Manifest um Emoji + Co-Load-Kappung, Event um Tagesend-Spruch.
    "ALTER TABLE transport_cargo ADD COLUMN emoji TEXT",
    "ALTER TABLE transport_cargo ADD COLUMN per_flight_max_kg REAL",
    "ALTER TABLE transport_events ADD COLUMN summary_quip TEXT",
    # radius_km: Erkennungs-Umkreis pro Event, z. B. für kurze Strecken wie Wangerooge↔Harle.
    "ALTER TABLE transport_events ADD COLUMN radius_km REAL",
    # departure (#15 Sub-Projekt B): Startplatz-ICAO, an den diese Frachtart gebunden ist.
    # NULL = geteilt (jeder Startplatz lädt sie — Legacy-Verhalten).
    "ALTER TABLE transport_cargo ADD COLUMN departure TEXT",
    # added_at (20.07.2026): wann diese Zeile ins Manifest kam. Ware ist erst AB DANN ladbar — sonst
    # lud eine mid-event dazugekommene Zeile rückwirkend auf frühere Bodenkontakte. NULL = Alt-Daten
    # ("schon immer da"), derive_stacks behandelt das als von Anfang an vorhanden.
    "ALTER TABLE transport_cargo ADD COLUMN added_at TEXT",
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

_PILOTS_MIGRATIONS = [
    # Pilot von der Friesen-Erkennung ausschließen, obwohl das Callsign den Präfix trägt
    # (z. B. Gast-CID auf einem FRS-Tag bei PC-21-Flügen). Default 1: Bestandspiloten bleiben
    # aktiv, das Ausschließen ist ein bewusster Admin-Opt-out, kein Opt-in.
    "ALTER TABLE pilots ADD COLUMN active INTEGER NOT NULL DEFAULT 1",
]

_PANEL_DEVICES_MIGRATIONS = [
    # Welche Paketfassung im Community-Ordner liegt. Gemeldet beim Anmelden über
    # /auth/device (ab Paket 2.0.0) -- vorher war von außen überhaupt nicht erkennbar, was
    # dort installiert ist. NULL heißt deshalb nicht "unbekannt", sondern "älter als 2.0.0"
    # bzw. "seit der Umstellung nicht mehr gestartet".
    "ALTER TABLE panel_devices ADD COLUMN paket_version TEXT",
]

_CUSTOM_AIRPORTS_MIGRATIONS = [
    # #62: Radius-Override für Großflughäfen (z. B. EHAM) -- der Abhebe-/Aufsetzpunkt kann
    # weiter vom airportsdata-Referenzpunkt entfernt liegen als der globale Standardradius.
    "ALTER TABLE custom_airports ADD COLUMN radius_km REAL",
    # #78: Grund der Ergänzung/Überschreibung -- dokumentiert, WARUM ein Eintrag existiert.
    "ALTER TABLE custom_airports ADD COLUMN reason TEXT",
]

# #78: die drei Standard-Gründe. Bewusst Freitext in der DB (kein Enum/CHECK): neue Gründe
# sollen durch Benutzung entstehen können, das Admin-UI schlägt die vorhandenen nur vor.
REASON_MISSING = "Fehlt in airportsdata"
REASON_WRONG_COORDS = "airportsdata-Koordinate falsch"
REASON_RADIUS = "Abhebepunkt außerhalb Standardradius"

# Ab dieser Abweichung gilt eine Custom-Koordinate als bewusst korrigiert (statt unverändert
# von airportsdata übernommen). Keine Grauzone in der Praxis: EHAM (reiner Radius-Override)
# liegt bei 0,00 km, der nächstkleinere echte Korrekturfall (EBUL) bei 15,0 km.
_REASON_COORD_DELTA_KM = 1.0


def _derive_custom_airport_reason(icao: str, lat: float, lon: float) -> str:
    """Grund eines Ergänzungs-Flugplatzes AUS DEN DATEN ableiten (#78).

    Bewusst datengetrieben statt über eine gepflegte Code-Liste: so ist die Zuordnung auch
    für Einträge korrekt, die es beim Schreiben dieses Codes noch gar nicht gab.

    - Code fehlt in airportsdata            -> Ergänzung
    - Koordinate weicht > 1 km ab           -> airportsdata steht am falschen Ort
    - Koordinate praktisch unverändert      -> nur radius_km gesetzt (Großflughafen-Fall)
    """
    from app.geo import airportsdata_coords, haversine  # lokal wie überall in dieser Datei

    ad = airportsdata_coords(icao)
    if ad is None:
        return REASON_MISSING
    if haversine(lat, lon, ad[0], ad[1]) > _REASON_COORD_DELTA_KM:
        return REASON_WRONG_COORDS
    return REASON_RADIUS


def migrate_custom_airport_reasons(conn: sqlite3.Connection) -> int:
    """Bestandseinträge ohne Grund nachträglich beschriften (#78, idempotent).

    Fasst NUR Zeilen mit ``reason IS NULL`` an -- ein vom Admin gepflegter Text überlebt
    daher jeden weiteren ``init_db``-Lauf. Gibt die Anzahl beschrifteter Zeilen zurück.
    """
    rows = conn.execute(
        "SELECT icao, lat, lon FROM custom_airports WHERE reason IS NULL"
    ).fetchall()
    n = 0
    for row in rows:
        icao, lat, lon = row[0], row[1], row[2]
        conn.execute(
            "UPDATE custom_airports SET reason = ? WHERE icao = ? AND reason IS NULL",
            (_derive_custom_airport_reason(icao, lat, lon), icao),
        )
        n += 1
    return n


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
        for stmt in _PANEL_DIAG_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        for stmt in _AIP_CHARTS_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        for stmt in _VISIBILITY_MIGRATIONS:
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
        for stmt in _CUSTOM_AIRPORTS_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        for stmt in _PILOTS_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        for stmt in _PANEL_DEVICES_MIGRATIONS:
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
        # #84: Alt-Events (v8.13.0) ins „Zeilen-statt-Strecke"-Modell überführen — jede geteilte
        # (NULL) Fracht-Zeile bekommt die Startplätze IHRES Events (Route ohne Ziel) eingetragen.
        # Alle Alt-Events haben genau einen Start + ein Ziel (Nutzer-Fakt 2026-07-07), die Zuordnung
        # ist eindeutig. Idempotent-äquivalent: „alle Nicht-Ziel-Route-Plätze" ist funktional
        # dasselbe wie geteilt (ein Flug-dep liegt ohnehin in route_set).
        try:
            _rows = conn.execute(
                "SELECT DISTINCT e.id, e.route, e.destination FROM transport_events e "
                "JOIN transport_cargo c ON c.event_id = e.id "
                "WHERE c.departure IS NULL OR c.departure = ''"
            ).fetchall()
            # Positionale Indizes (0=id, 1=route, 2=destination): die init_db-Verbindung liefert
            # Tupel, keine sqlite3.Row — `_r["route"]` würde crashen (Live-Fund v8.14.0).
            for _r in _rows:
                _deps = _normalize_icao_list(_r[1], exclude=_r[2])
                if _deps:
                    conn.execute(
                        "UPDATE transport_cargo SET departure = ? WHERE event_id = ? "
                        "AND (departure IS NULL OR departure = '')",
                        (_deps, _r[0]),
                    )
        except Exception:
            # Eine Migration darf den App-Start NIEMALS verhindern (nur diesen Backfill überspringen).
            pass
        # Alt-Daten (v8.8.1): inf/nan aus fehlerhaften KI-Zuladungs-Vorschlägen (Phantom-Typcode
        # wie Buchstabendreher AS65→SA65) bereinigen — nicht-endliche Werte → NULL, sonst sprengt
        # ein einziger die Zuladungs-Liste beim JSON-Encoding. SQLite kann inf nicht per SQL
        # filtern, daher in Python. payload_kg ist NOT NULL → dort 0.0 (sicherer Fallback: „keine
        # Zuladung", bis der Admin die Zeile neu speichert) statt NULL. Idempotent.
        try:
            _pl_cols = ("mtow_kg", "empty_kg", "fuel_kg", "crew_kg", "payload_kg")
            for _row in conn.execute(
                "SELECT rowid, " + ", ".join(_pl_cols) + " FROM aircraft_payloads"
            ).fetchall():
                _vals = tuple(_row)
                _bad = [_pl_cols[i] for i, v in enumerate(_vals[1:])
                        if isinstance(v, float) and not math.isfinite(v)]
                if _bad:
                    _sets = ", ".join(f"{c}={'0.0' if c == 'payload_kg' else 'NULL'}" for c in _bad)
                    conn.execute(
                        f"UPDATE aircraft_payloads SET {_sets} WHERE rowid=?", (_vals[0],)
                    )
        except sqlite3.OperationalError:
            pass
        try:
            seed_cargo_catalog(conn)  # Frachtart-Katalog erstbefüllen (idempotent)
        except sqlite3.OperationalError:
            pass
        try:
            ensure_generic_heringe(conn)  # 20.07.2026: generische "Heringe" in Bestands-DBs nachrüsten
        except sqlite3.OperationalError:
            pass
        try:
            seed_custom_airports(conn)  # Ergänzungs-Flugplätze erstbefüllen (idempotent, #50)
        except sqlite3.OperationalError:
            pass
        try:
            seed_airport_links(conn)  # AIP-VFR-Links erstbefüllen (idempotent)
        except sqlite3.OperationalError:
            pass
        try:
            migrate_custom_airport_reasons(conn)  # #78: Bestandseinträge nachbeschriften
        except sqlite3.OperationalError:
            pass
        # Alt-Daten: statsim_cache.aircraft vor #44 (v8.3.0) unnormalisiert gespeichert
        # (Composite-String wie "A320/M-SDE3FGHIRWY/LB1" statt kurzem ICAO-Typ "A320").
        # Der Ingestion-Fix (app/statsim.py:_normalize_flight) heilt nur Zeilen, die
        # tatsächlich neu geschrieben werden (Hintergrund-Refresh trifft nur die letzten
        # 31 Tage bzw. bei explizitem Voll-Reload) — ältere Flüge blieben sonst dauerhaft
        # unnormalisiert stehen. Einmalige, idempotente Nachnormalisierung aller Bestandszeilen
        # (WHERE-Klausel greift nach dem ersten Lauf nicht mehr).
        try:
            conn.execute(
                "UPDATE statsim_cache SET aircraft = substr(aircraft, 1, instr(aircraft, '/') - 1) "
                "WHERE aircraft LIKE '%/%'"
            )
        except sqlite3.OperationalError:
            pass
        # Alt-Daten: flights.aircraft_short/aircraft_icao vor #51 (v8.5.0) unnormalisiert
        # gespeichert — der VATSIM-Feed liefert das Feld manchmal schon als Composite-String
        # ("AS65/L-SDGY/S" statt "AS65"). Der Ingestion-Fix (app/poller.py) heilt nur künftig
        # neu geschriebene Zeilen; einmalige, idempotente Nachnormalisierung der Bestandszeilen
        # (analog zur statsim_cache-Migration oben, WHERE greift nach dem ersten Lauf nicht mehr).
        try:
            conn.execute(
                "UPDATE flights SET aircraft_short = substr(aircraft_short, 1, instr(aircraft_short, '/') - 1) "
                "WHERE aircraft_short LIKE '%/%'"
            )
            conn.execute(
                "UPDATE flights SET aircraft_icao = substr(aircraft_icao, 1, instr(aircraft_icao, '/') - 1) "
                "WHERE aircraft_icao LIKE '%/%'"
            )
        except sqlite3.OperationalError:
            pass
        # #54: update_flight_plan() hat aircraft_short vor diesem Fix nie mitgeschrieben — ein
        # OHNE Typ eröffnetes Leg, dessen Flugplan (aircraft_icao) später eintraf, blieb
        # aircraft_short dauerhaft leer. Die icao-Spalte stammt aus DERSELBEN Plan-Zeile (kein
        # zeitlich blinder Fremdwert wie beim #52-Fehlertyp) — einmaliger, idempotenter Backfill
        # (WHERE greift nach dem ersten Lauf nicht mehr).
        try:
            rows = conn.execute(
                "SELECT id, aircraft_icao FROM flights "
                "WHERE (aircraft_short IS NULL OR aircraft_short = '') "
                "AND aircraft_icao IS NOT NULL AND aircraft_icao != ''"
            ).fetchall()
            for row in rows:
                normalized = normalize_type_code(row[1])
                if normalized:
                    conn.execute(
                        "UPDATE flights SET aircraft_short = ? WHERE id = ?",
                        (normalized, row[0]),
                    )
        except sqlite3.OperationalError:
            pass
        # Alt-Daten: fuel_full_kg gab es vor v8.17.0 nicht — fuel_kg war bislang schon der
        # halbe Tank, also fuel_full_kg = fuel_kg * 2 (idempotent, WHERE greift nach dem
        # ersten Lauf nicht mehr).
        try:
            conn.execute(
                "UPDATE aircraft_payloads SET fuel_full_kg = fuel_kg * 2 "
                "WHERE fuel_full_kg IS NULL AND fuel_kg IS NOT NULL"
            )
        except sqlite3.OperationalError:
            pass
        # Kuratierte Flugzeug-Specs vorbefüllen (idempotent, überschreibt nie manuelle Zeilen).
        try:
            seed_curated_payloads(conn)
        except Exception:  # noqa: BLE001 — Seeding ist Komfort, nie den Start blockieren
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
        # AIP-Karten: aip_charts + aip_ground_charts -> aip_charts_dfs.
        #
        # EIGENER Block mit sqlite3.Error, NICHT OperationalError. Das Muster der
        # Spaltenmigrationen oben faengt nur OperationalError -- richtig fuer
        # "ALTER TABLE ... ADD COLUMN", das bei vorhandener Spalte genau den wirft. Ein
        # INSERT in eine Tabelle mit Primaerschluessel wirft dagegen IntegrityError, und
        # die ist KEIN OperationalError: init_db braeche ab, die App startete nicht.
        #
        # Ein Fehlschlag darf den Dienststart nicht verhindern. Die alten Tabellen stehen
        # noch, der Merker bleibt ungesetzt -- der naechste Start versucht es erneut.
        try:
            _uebernommen = migration_charts_dfs(conn)
            conn.commit()
            if _uebernommen:
                _logger.info("aip_charts_dfs: %d Zeilen uebernommen", _uebernommen)
        except sqlite3.Error:
            conn.rollback()
            _logger.exception("aip_charts_dfs: Migration fehlgeschlagen, Start ohne sie")
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
    """Neue Verbindung mit WAL-Mode, busy_timeout und row_factory=sqlite3.Row."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Wartezeit auf eine fremde Schreibsperre (GitHub-Issue #14). Ohne das PRAGMA gilt
    # Pythons Vorgabe von 5 Sekunden, und die war am 04.09.2026 der Verstaerker gleich
    # zweier Vorfaelle: Ein Job hielt die Sperre laenger, alle anderen Schreiber brachen mit
    # "database is locked" ab statt zu warten -- ``PUT /api/prefs`` schlug als HTTP 500 bei
    # echten Nutzern durch, und weil FastAPI sync-Endpunkte im Threadpool faehrt, sassen die
    # Threads ihre 5 s ab und stauten alles dahinter.
    #
    # 15 Sekunden = die Taktzeit des Pollers. Wer einen ganzen Poll-Zyklus lang nicht an die
    # Datenbank kommt, hat kein Gedraenge mehr, sondern eine haengende Transaktion -- die
    # soll als Fehler sichtbar werden statt beliebig lange zu warten.
    #
    # Das ist das Netz, NICHT die Loesung: Eine Transaktion, die einen Netzabruf umspannt,
    # gehoert aufgetrennt (s. #15 und die Regel in CLAUDE.md). Ein grosszuegiger Timeout
    # macht daraus nur eine laengere Verzoegerung.
    conn.execute("PRAGMA busy_timeout=15000")
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
# Panel-Selbstdiagnose (MSFS-EFB)
# ---------------------------------------------------------------------------

# Obergrenze: Die Diagnose ist ein Werkzeug für die Fehlersuche, kein Langzeitarchiv --
# ohne Deckel würde ein Panel in einer Fehlerschleife die DB vollschreiben.
PANEL_DIAG_KEEP = 500


def insert_panel_diag(
    conn: sqlite3.Connection,
    kind: str,
    payload_json: str,
    app_version: str | None = None,
    user_agent: str | None = None,
    cid: int | None = None,
) -> None:
    """Einen Diagnose-Datensatz aus dem EFB-Panel ablegen (kein commit).

    ``cid`` ist best effort und darf ``None`` sein -- s. ``_PANEL_DIAG_MIGRATIONS``.

    Beschneidet anschließend auf die neuesten ``PANEL_DIAG_KEEP`` Einträge.
    """
    conn.execute(
        "INSERT INTO panel_diag (created_at, kind, app_version, user_agent, cid, payload_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_now_utc(), kind, app_version, user_agent, cid, payload_json),
    )
    conn.execute(
        "DELETE FROM panel_diag WHERE id NOT IN ("
        "  SELECT id FROM panel_diag ORDER BY id DESC LIMIT ?"
        ")",
        (PANEL_DIAG_KEEP,),
    )


def list_panel_diag(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Neueste Diagnose-Datensätze (neueste zuerst)."""
    rows = conn.execute(
        "SELECT id, created_at, kind, app_version, user_agent, cid, payload_json "
        "FROM panel_diag ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def clear_panel_diag(conn: sqlite3.Connection) -> None:
    """Alle Diagnose-Datensätze löschen (kein commit) -- für einen sauberen Messlauf."""
    conn.execute("DELETE FROM panel_diag")


# ---------------------------------------------------------------------------
# Geräte-Bindung fürs EFB-Panel (persistente Anmeldung)
# ---------------------------------------------------------------------------

# Untergrenze für die Geräte-ID. Sie ist ein Zugangsschlüssel, deshalb wird eine zu kurze
# (und damit ratbare) ID gar nicht erst angenommen -- die ID entsteht im EFB-Paket, also
# außerhalb unserer Kontrolle, und muss hier geprüft werden.
PANEL_DEVICE_MIN_LEN = 32


def get_panel_device(conn: sqlite3.Connection, device_id: str) -> dict | None:
    """Gebundenes Gerät nachschlagen; ``None``, wenn unbekannt oder widerrufen."""
    if not device_id or len(device_id) < PANEL_DEVICE_MIN_LEN:
        return None
    row = conn.execute(
        "SELECT device_id, cid, name, created_at, last_seen_at, paket_version "
        "FROM panel_devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    return dict(row) if row else None


def bind_panel_device(conn: sqlite3.Connection, device_id: str, cid: int, name: str | None) -> bool:
    """Gerät an eine CID binden (kein commit). ``False``, wenn die Bindung abzulehnen ist.

    Abgelehnt wird eine unbrauchbar kurze ID -- und, sicherheitsrelevant, eine ID, die bereits
    an eine ANDERE CID gebunden ist. Ein stilles Überschreiben wäre ein Übernahme-Weg: Wer eine
    fremde Geräte-ID kennt, könnte sie sonst auf sich selbst umbiegen. Wechselt der Simulator
    tatsächlich den Besitzer, hebt ein Widerruf im Admin die alte Bindung auf.
    """
    if not device_id or len(device_id) < PANEL_DEVICE_MIN_LEN:
        return False
    vorhanden = get_panel_device(conn, device_id)
    if vorhanden and int(vorhanden["cid"]) != int(cid):
        return False
    now = _now_utc()
    conn.execute(
        "INSERT INTO panel_devices (device_id, cid, name, created_at, last_seen_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(device_id) DO UPDATE SET name = excluded.name, "
        "last_seen_at = excluded.last_seen_at",
        (device_id, int(cid), name, now, now),
    )
    return True


def touch_panel_device(conn: sqlite3.Connection, device_id: str,
                       paket_version: str | None = None) -> None:
    """Letzte Nutzung festhalten (kein commit) -- damit im Admin sichtbar ist, was noch aktiv
    ist und was gefahrlos widerrufen werden kann.

    ``paket_version`` wird nur geschrieben, wenn sie mitkommt. Ein Paket vor 2.0.0 meldet
    nichts; ein ``NULL`` daraufhin zu ÜBERSCHREIBEN wäre falsch -- der zuletzt bekannte Wert
    ist die bessere Auskunft als „keine Angabe", solange niemand nachweislich zurückrüstet.
    """
    if paket_version:
        conn.execute(
            "UPDATE panel_devices SET last_seen_at = ?, paket_version = ? WHERE device_id = ?",
            (_now_utc(), paket_version, device_id),
        )
        return
    conn.execute(
        "UPDATE panel_devices SET last_seen_at = ? WHERE device_id = ?", (_now_utc(), device_id)
    )


def get_panel_prefs(conn: sqlite3.Connection, cid: int, kontext: str) -> dict:
    """Karten-Merker eines Nutzers in einem Kontext. Leeres Dict, wenn nichts gespeichert ist.

    Unlesbares JSON wird wie „nichts gespeichert" behandelt: Ein beschädigter Eintrag darf
    nicht dazu führen, dass die Karte gar nicht erst aufgeht.
    """
    row = conn.execute(
        "SELECT prefs_json FROM panel_prefs WHERE cid = ? AND kontext = ?",
        (int(cid), str(kontext)),
    ).fetchone()
    if not row:
        return {}
    try:
        werte = json.loads(row["prefs_json"])
    except (ValueError, TypeError):
        return {}
    return werte if isinstance(werte, dict) else {}


def set_panel_prefs(conn: sqlite3.Connection, cid: int, kontext: str, prefs: dict) -> None:
    """Karten-Merker ersetzen (kein commit). Die Grenzen prüft der Endpunkt, s. main.py."""
    conn.execute(
        "INSERT INTO panel_prefs (cid, kontext, prefs_json, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(cid, kontext) DO UPDATE SET prefs_json = excluded.prefs_json, "
        "updated_at = excluded.updated_at",
        (int(cid), str(kontext), json.dumps(prefs, ensure_ascii=False), _now_utc()),
    )


def list_panel_devices(conn: sqlite3.Connection) -> list[dict]:
    """Alle gebundenen Geräte (neueste zuerst) -- für die Admin-Übersicht."""
    rows = conn.execute(
        "SELECT device_id, cid, name, created_at, last_seen_at, paket_version "
        "FROM panel_devices ORDER BY COALESCE(last_seen_at, created_at) DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def revoke_panel_device(conn: sqlite3.Connection, device_id: str) -> None:
    """Geräte-Bindung aufheben (kein commit). Das Panel verlangt danach wieder eine
    Anmeldung."""
    conn.execute("DELETE FROM panel_devices WHERE device_id = ?", (device_id,))


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
        "SELECT p.cid, p.name, p.added_at, p.active, "
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
        d["active"] = bool(d["active"])
        result.append(d)
    return result


def upsert_pilot(conn: sqlite3.Connection, cid: int, name: str, active: bool = True) -> None:
    """Pilot anlegen oder Namen/Aktiv-Status aktualisieren (added_at bleibt beim Update erhalten)."""
    conn.execute(
        "INSERT INTO pilots (cid, name, added_at, active) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(cid) DO UPDATE SET name = excluded.name, active = excluded.active",
        (cid, name, _now_utc(), int(active)),
    )


def get_inactive_cids(conn: sqlite3.Connection) -> set[int]:
    """CIDs, die per Admin-Checkbox gesperrt wurden -- überall ausgeschlossen.

    Trotz FRS-Callsign-Präfix gelten diese CIDs NICHT als Friesen (z. B. eine Gast-CID, die
    für PC-21-Flüge einen FRS-Tag nutzt). Wirkt an zwei Stellen: vor jedem Poll gegen den
    Live-VATSIM-Feed (``filter_friesen_pilots()``) und beim Laden gespeicherter Flüge
    (``_drop_inactive()``), damit gesperrte CIDs auch rückwirkend aus Statistik, Piloten,
    Bummel und Kutter verschwinden.

    Fehlt die Spalte ``active``, wird eine leere Menge geliefert statt eine Ausnahme zu
    werfen. Grund: Seit dem Einsatz in ``_drop_inactive`` hängt JEDE Auswertung an dieser
    Abfrage -- eine Datenbank ohne die Spalte (etwa frisch angelegt oder nicht migriert)
    würde sonst sämtliche Statistiken lahmlegen statt nur die Sperre zu ignorieren. Ein
    Fehler an dieser Stelle darf höchstens die Sperre kosten, nie die ganze Auswertung.
    """
    try:
        rows = conn.execute("SELECT cid FROM pilots WHERE active = 0").fetchall()
    except sqlite3.OperationalError:
        return set()
    return {r[0] for r in rows}


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


def _distance_nm_positions(
    positions: list[dict], start_ts: str, end_ts: str
) -> int:
    """GPS-Distanz (nm) aus einer bereits geladenen Positionsliste (Haversine-Summe).

    Reine Funktion — arbeitet auf einer Liste von Dicts mit den Keys
    ``latitude, longitude, groundspeed, ts`` (Reihenfolge wird intern nach ``ts``
    sortiert; das Fenster wird intern auf ``start_ts <= ts <= end_ts`` gefiltert,
    damit dieselbe Semantik wie das bisherige SQL-``WHERE`` reproduziert wird).
    Quelle unabhängig von ``position_history``/cid — so auch für StatSim-Tracks
    (``statsim_position_history``) nutzbar.
    """
    from app.geo import haversine as _haversine
    window = sorted(
        (p for p in positions if start_ts <= p["ts"] <= end_ts),
        key=lambda p: p["ts"],
    )
    dist_km = 0.0
    for i in range(1, len(window)):
        p0, p1 = window[i - 1], window[i]
        if p0["latitude"] and p0["longitude"] and p1["latitude"] and p1["longitude"]:
            dist_km += _haversine(
                p0["latitude"], p0["longitude"], p1["latitude"], p1["longitude"]
            )
    return round(dist_km / 1.852)


def _gps_distance_nm(
    conn: sqlite3.Connection, cid: int, logon_time: str, logoff_time: str
) -> int:
    """GPS-Distanz (nm) eines Fluges aus position_history (dünner SQL-Wrapper)."""
    pos_rows = conn.execute(
        "SELECT latitude, longitude, ts FROM position_history "
        "WHERE cid = ? AND ts >= ? AND ts <= ? AND latitude IS NOT NULL ORDER BY ts",
        (cid, logon_time, logoff_time),
    ).fetchall()
    positions = [
        {"latitude": r[0], "longitude": r[1], "groundspeed": None, "ts": r[2]}
        for r in pos_rows
    ]
    return _distance_nm_positions(positions, logon_time, logoff_time)


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


def _block_seconds_positions(
    positions: list[dict], start_ts: str, end_ts: str
) -> int:
    """Block-/Bewegungszeit in SEKUNDEN aus einer bereits geladenen Positionsliste.

    Reine Funktion — arbeitet auf einer Liste von Dicts mit den Keys
    ``latitude, longitude, groundspeed, ts`` (wird intern nach ``ts`` sortiert; das
    Fenster wird intern auf ``start_ts <= ts <= end_ts`` gefiltert, damit dieselbe
    Semantik wie das bisherige SQL-``WHERE`` reproduziert wird). Quelle unabhängig
    von ``position_history``/cid — so auch für StatSim-Tracks
    (``statsim_position_history``) nutzbar.

    Summe der Abschnitte zwischen aufeinanderfolgenden bewegten Positionen; liegt zwischen
    zwei Bewegungen eine belegte Standphase ≥ _BLOCK_STAND_MIN_SEC (zusammenhängende Positionen
    mit groundspeed ≤ _BLOCK_GS_KT), wird deren Dauer abgezogen — so zählt die Bodenzeit einer
    Zwischenlandung ohne Disconnect nicht als Blockzeit (Bummel-Gerechtigkeit). Kurze Halte
    bleiben enthalten; Datenlücken ohne Stillstands-Beleg zählen voll. Wird auch für die
    Bummel-Wertung gebraucht (Abstand zum Schnitt sekundengenau). 0 ohne bewegte Position.
    """
    window = sorted(
        (p for p in positions if start_ts <= p["ts"] <= end_ts),
        key=lambda p: p["ts"],
    )
    total = 0.0
    prev_move = None           # Zeitpunkt der letzten bewegten Position
    stand_first = stand_last = None  # belegter Stillstand seit prev_move
    for p in window:
        ts, gs = p["ts"], p["groundspeed"]
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


def _block_seconds(
    conn: sqlite3.Connection, cid: int, logon_time: str, logoff_time: str
) -> int:
    """Block-/Bewegungszeit in SEKUNDEN (sekundengenaue Basis von _block_minutes).

    Dünner SQL-Wrapper: lädt die Positionen von ``position_history`` und delegiert
    an :func:`_block_seconds_positions`.
    """
    rows = conn.execute(
        "SELECT ts, groundspeed FROM position_history "
        "WHERE cid = ? AND ts >= ? AND ts <= ? ORDER BY ts",
        (cid, logon_time, logoff_time),
    ).fetchall()
    positions = [
        {"latitude": None, "longitude": None, "groundspeed": r[1], "ts": r[0]}
        for r in rows
    ]
    return _block_seconds_positions(positions, logon_time, logoff_time)


# ---------------------------------------------------------------------------
# Leg-Metriken (Blockzeit-Anblock, Fix "fix/blockzeit-anblock"): _block_seconds_positions
# oben bleibt die SESSION-Blockzeit (flights.block_min über [logon, logoff], block <=
# duration, drei Fremdnutzer — s. Kommentar dort). Die beiden folgenden Funktionen sind
# NEU und ausschließlich für die LEG-Metriken in _gps_flights_for_positions gedacht: dort
# gilt die UMGEKEHRTE Relation (duration_min <= block_min, Flugzeit ist Teilmenge der
# Blockzeit), weil block_min dort gate-to-gate inkl. Taxi zählt, duration_min dagegen nur
# die reine Luftzeit.
# ---------------------------------------------------------------------------

def _leg_block_seconds(positions: list[dict], start_ts: str, end_ts: str) -> int:
    """Leg-Blockzeit (Sekunden) als WANDUHR: ``end_ts - start_ts`` MINUS der Summe aller
    „Abstell-Standphasen" im Fenster.

    Anders als :func:`_block_seconds_positions` (die BEWEGTE Abschnitte aufsummiert) zählt
    diese Funktion erst alles zwischen ``start_ts`` und ``end_ts`` als Blockzeit und zieht
    dann NUR nachweislich geparkte Standphasen wieder ab — Rollhalte, Warteschlangen und
    sonstige kurze Unterbrechungen bleiben so automatisch gate-to-gate enthalten, ohne dass
    dafür (wie bei der session-basierten Funktion) explizit „bewegte Abschnitte" aufsummiert
    werden müssten.

    Eine „Abstell-Standphase" ist ein maximaler zusammenhängender Lauf von Samples mit
    ``groundspeed <= _BLOCK_GS_KT`` (Samples mit ``groundspeed=None`` sind kein Beleg — sie
    brechen den Lauf NICHT und verlängern ihn auch NICHT, sie werden schlicht übersprungen),
    der ALLE drei Bedingungen erfüllt:
      a) Dauer (letztes minus erstes Sample des Laufs) >= ``_BLOCK_STAND_MIN_SEC``,
      b) die ERSTE Position des Laufs liegt <= ``_BUMMEL_AIRPORT_RADIUS_KM`` von einem
         Flugplatz (``geo.nearest_airport_icao_fast`` liefert nicht ``None``) — NUR ein
         Abstellen AN EINEM FLUGPLATZ beendet die Blockzeit,
      c) der Lauf liegt vollständig in ``[start_ts, end_ts]`` (durch die Fensterung der
         Positionsliste hier strukturell immer erfüllt, wird der Vollständigkeit halber
         mitgeführt).
    Eine Standphase IM GELÄNDE (kein Flugplatz im Umkreis) ist dagegen eine Außenlandung —
    die Maschine läuft weiter, die Blockzeit läuft mit (ausdrückliche Nutzerentscheidung,
    keine Obergrenze). Nur (a) UND (b) zusammen disqualifizieren eine Standphase.

    Ohne Positionen im Fenster gibt es keinen Beleg für irgendeinen Stillstand — nichts wird
    abgezogen, es zählt die volle Wanduhr ``end_ts - start_ts`` (NICHT 0).
    """
    from app import geo

    window = sorted(
        (p for p in positions if start_ts <= p["ts"] <= end_ts),
        key=lambda p: p["ts"],
    )
    try:
        total = (_parse_iso(end_ts) - _parse_iso(start_ts)).total_seconds()
    except Exception:
        return 0

    run_first: str | None = None   # ts des ersten Samples des laufenden gs<=Schwelle-Laufs
    run_last: str | None = None    # ts des letzten Samples desselben Laufs
    run_pos: tuple | None = None   # (lat, lon) des ERSTEN Samples des Laufs (Kriterium b)

    def _maybe_subtract() -> None:
        nonlocal total
        if run_first is None or run_last is None:
            return
        dur = (_parse_iso(run_last) - _parse_iso(run_first)).total_seconds()
        if dur < _BLOCK_STAND_MIN_SEC:
            return
        if not run_pos or run_pos[0] is None or run_pos[1] is None:
            return
        if geo.nearest_airport_icao_fast(run_pos[0], run_pos[1], _BUMMEL_AIRPORT_RADIUS_KM) is None:
            return
        total -= dur

    for p in window:
        gs = p.get("groundspeed")
        if gs is None:
            continue  # kein Beleg — weder Lauf-Ende noch Lauf-Fortsetzung
        if gs <= _BLOCK_GS_KT:
            if run_first is None:
                run_first = p["ts"]
                run_pos = (p.get("latitude"), p.get("longitude"))
            run_last = p["ts"]
        else:
            _maybe_subtract()
            run_first = run_last = None
            run_pos = None
    _maybe_subtract()
    return max(0, int(total))


# Bodenphasen-Erkennung Paket 2 (_air_seconds): bewusst POSITION statt Groundspeed als
# Kriterium (anders als _leg_block_seconds oben) — Grund war Flug 632 (Hubschrauber):
# Schweberoll-Blips von 7/13 kt zerhackten eine 26-minütige Bodenzeit in viele Kurz-Läufe,
# weil sie über der _BLOCK_GS_KT-Schwelle (2 kt) lagen, obwohl die Maschine effektiv am
# Fleck stand. Ein exakt stehender Schwebeflug gilt damit ausdrücklich als „Boden" — der
# großzügige Radius ist unkritisch, weil die Regel NUR zwischen Abheben und Landung greift.
_AIR_GROUND_RADIUS_M = 200      # Positions-Radius um die ERSTE Position eines Laufs
_AIR_GROUND_MAX_GAP_SEC = 300   # größere Sample-Lücke bricht den Lauf (kein Beleg → nichts abziehen)
_AIR_GROUND_MIN_SEC = 120       # Mindestdauer, ab der eine Bodenphase abgezogen wird


def _air_seconds(positions: list[dict], takeoff_ts: str, landing_ts: str) -> int:
    """Reine Flugzeit (Sekunden) OHNE Bodenzeit: ``landing_ts - takeoff_ts`` MINUS der Summe
    aller „Bodenphasen" im Fenster ``[takeoff_ts, landing_ts]``.

    Eine „Bodenphase" ist ein maximaler zusammenhängender Lauf von Samples, bei dem
      a) jede Position des Laufs <= ``_AIR_GROUND_RADIUS_M`` von der ERSTEN Position des
         Laufs entfernt ist (``geo.haversine`` liefert km, hier in Meter umgerechnet),
      b) zwischen zwei aufeinanderfolgenden Samples des Laufs höchstens
         ``_AIR_GROUND_MAX_GAP_SEC`` liegen (eine größere Lücke ist kein Beleg für
         Stillstand und bricht den Lauf, statt ihn zu überbrücken),
      c) die Gesamtdauer des Laufs >= ``_AIR_GROUND_MIN_SEC`` ist.
    Fehlt bei einem Sample die Position (``latitude``/``longitude`` ``None``), ist auch das
    kein Beleg — der laufende Lauf wird geschlossen (ggf. abgezogen) und NICHT fortgesetzt,
    analog zur „ohne Belege wird nichts abgezogen"-Regel der Kriterien selbst.

    Kriterium ist bewusst die POSITION, nicht der Groundspeed (anders als
    :func:`_leg_block_seconds`) — Groundspeed kann mitten im Flug durch Datenlücken oder
    (bei manchen Quellen) fehlende Telemetrie unbrauchbar sein, während echte Bewegung sich
    in der Position ohnehin zeigt. Ohne Positionen im Fenster wird nichts abgezogen — es
    zählt die volle Wanduhr ``landing_ts - takeoff_ts`` (NICHT 0).
    """
    from app import geo

    window = sorted(
        (p for p in positions if takeoff_ts <= p["ts"] <= landing_ts),
        key=lambda p: p["ts"],
    )
    try:
        total = (_parse_iso(landing_ts) - _parse_iso(takeoff_ts)).total_seconds()
    except Exception:
        return 0

    run: list[dict] = []

    def _close_run() -> None:
        nonlocal total
        if not run:
            return
        dur = (_parse_iso(run[-1]["ts"]) - _parse_iso(run[0]["ts"])).total_seconds()
        if dur >= _AIR_GROUND_MIN_SEC:
            total -= dur

    for p in window:
        lat, lon = p.get("latitude"), p.get("longitude")
        if lat is None or lon is None:
            _close_run()
            run.clear()
            continue
        if run:
            gap = (_parse_iso(p["ts"]) - _parse_iso(run[-1]["ts"])).total_seconds()
            first = run[0]
            dist_m = geo.haversine(first["latitude"], first["longitude"], lat, lon) * 1000.0
            if gap > _AIR_GROUND_MAX_GAP_SEC or dist_m > _AIR_GROUND_RADIUS_M:
                _close_run()
                run.clear()
        run.append(p)
    _close_run()
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
            # Landung) ist die beste Untergrenze der Session-Dauer; die des ersten Legs
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
_RECONSTRUCT_STAND_SEC = 300        # belegte Standphase, die zwei Legs einer Session trennt
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
        # diesen Flug vom vorherigen Leg derselben verwaisten Session.
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
    aircraft_short: str = "",
    alternate: str = "",
    deptime: str = "",
    enroute_time: str = "",
    fuel_time: str = "",
) -> None:
    """Flugplan (DEP/ARR + erweiterte Felder) eines laufenden Fluges setzen.

    #54: aircraft_short wird nur bei nicht-leerem neuen Wert überschrieben (COALESCE/NULLIF) —
    ein Plan-Update ohne bekannten Typ (leerer String) darf einen bereits bekannten Typ nicht
    löschen. Vorher wurde aircraft_short hier nie angefasst, sodass ein OHNE Typ eröffnetes Leg
    (open_flight mit leerem aircraft_short) den Typ nie nachtragen konnte, selbst wenn ein
    späterer Plan (aircraft_icao) ihn kannte.
    """
    conn.execute(
        """UPDATE flights SET departure=?, arrival=?,
                              route=?, remarks=?, cruise_altitude=?, cruise_tas=?,
                              flight_rules=?, aircraft_icao=?,
                              aircraft_short=COALESCE(NULLIF(?, ''), aircraft_short),
                              alternate=?,
                              deptime=?, enroute_time=?, fuel_time=?
           WHERE id=?""",
        (departure, arrival, route, remarks, cruise_altitude, cruise_tas,
         flight_rules, aircraft_icao, aircraft_short, alternate,
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
    Callsign-Prefix begrenzt. Aggregiert über get_cached_flights (GPS-Wahrheit,
    canonicalize_legs materialisiert) — dieselbe Wahrheit wie alle anderen Views unter
    GPS-only Phase 2 (#23). Ein Flug, der GERADE fliegt (kein Landepunkt erkannt UND die
    Connection noch offen), wird NICHT gezählt — er ist noch nicht gewertet.
    """
    prefix_pat = callsign_prefix + "%"
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    flights = get_cached_flights(conn, start=start, callsign_prefix=callsign_prefix)

    agg: dict[int, dict] = {}
    for f in flights:
        if f.get("logoff_time") is None and not f.get("connection_closed"):
            continue  # in-progress: kein Landepunkt, Connection offen — noch nicht gewertet
        cid = f["cid"]
        a = agg.setdefault(cid, {"fs": 0, "st": 0, "dur": 0, "block": 0, "last": None, "last_cs": ""})
        if f.get("source") == "statsim":
            a["st"] += 1
        else:
            a["fs"] += 1
        a["dur"] += f.get("duration_min") or 0
        a["block"] += f.get("block_min") or 0
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
        agg.setdefault(row[0], {"fs": 0, "st": 0, "dur": 0, "block": 0, "last": None, "last_cs": ""})

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
            "total_block_min": a["block"],
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

    # Eine Wahrheit: über get_cached_flights aggregieren (GPS-Wahrheit, kein eigener
    # Merge-/Dedup-Code mehr). In-progress-Flüge (kein Landepunkt, Connection offen) werden
    # wie in get_stats nicht gezählt — noch nicht gewertet.
    flights = get_cached_flights(conn, start=start, callsign_prefix=callsign_prefix)

    def _period(lt: str) -> str:
        return lt[:10] if grouping == "day" else lt[:7]

    counts: dict[str, int] = {}
    durs: dict[str, int] = {}
    pilots_by_period: dict[str, set] = {}
    for f in flights:
        if f.get("logoff_time") is None and not f.get("connection_closed"):
            continue  # in-progress: kein Landepunkt, Connection offen — noch nicht gewertet
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


def _statsim_rows_continuous(
    row_a: dict, row_b: dict, positions_a: list[dict], positions_b: list[dict]
) -> bool:
    """StatSim-Pendant zu :func:`_segments_continuous`: True wenn ``row_b`` GPS-technisch
    nahtlos an ``row_a`` anschließt — StatSim hat dann einen echten durchgehenden Flug
    MITTEN IN DER LUFT in zwei ``statsim_id``s zerschnitten (Live-Fund 2026-07-06, KNF04WC
    CYYR→KCAR→KOWD: StatSim wies eine 45-Minuten-Lücke zwischen den offiziellen logon_time/
    logoff_time-Feldern aus, während die echten Positionen nur 60 Sekunden auseinanderlagen
    — die Aufzeichnung lief über den Start in KCAR hinweg einfach in der zweiten ID weiter).

    Nutzt DIESELBEN Zeit-/Distanz-/Richtungs-Regeln und -Konstanten wie der FriesenSpy-
    Reconnect (``_segments_continuous``) — nur auf ``statsim_position_history`` statt
    ``position_history``, mit bereits geladenen Positionslisten statt eigener SQL-Abfrage, und
    mit den ECHTEN Positions-Zeitstempeln als Lückenmaß (die ``logon_time``/``logoff_time``-
    Felder von ``statsim_cache`` sind dafür nachweislich unzuverlässig, s. o.).

    EIN Unterschied zum FS-Reconnect: statt der einseitigen „Fertig gelandet"-Sperre gilt hier
    ein SYMMETRISCHES Airborne-Kriterium — BEIDE Seiten der Naht müssen nachweislich in der
    Luft sein (A endet mit ≥ ``_FLOWN_MIN_GS_KT``, B beginnt mit ≥ ``_FLOWN_MIN_GS_KT``). Bei
    einem echten Mid-Air-Split fliegt das Flugzeug über die id-Grenze hinweg weiter (im Fund:
    A 236 kt → B 241 kt). Ein SEPARATER neuer Flug B würde dagegen typischerweise am Boden
    beginnen (Taxi/Startlauf, niedrige gs) → dann NICHT mergen. Anders als der FS-Reconnect
    (durchgehende VATSIM-Verbindung, lückenlose Position) sitzt die StatSim-Naht per Definition
    zwischen zwei GETRENNTEN Aufzeichnungen — „beide Seiten airborne" ist dort das ehrlichere
    Kriterium und schließt zugleich die „Track A brach vor der Landung ab, B ist ein anderer
    Flug"-Fehlmerge aus, OHNE das großzügige Zeit-/Distanzfenster (15/30 min) einzuengen.
    """
    from app.geo import haversine, icao_to_coords

    if not positions_a or not positions_b:
        return False
    last, first = positions_a[-1], positions_b[0]
    try:
        gap_min = (_parse_iso(first["ts"]) - _parse_iso(last["ts"])).total_seconds() / 60.0
    except Exception:
        return False
    if gap_min < 0:
        return False
    # Beide Seiten der Naht müssen airborne sein (s. Docstring). Deckt zugleich A's Landungs-
    # sperre ab: liegt A's letzte gs ≥ 60, kann A nicht am Boden geendet haben.
    if (last.get("groundspeed") or 0) < _FLOWN_MIN_GS_KT:
        return False
    if (first.get("groundspeed") or 0) < _FLOWN_MIN_GS_KT:
        return False
    same_fp = (
        bool(row_a.get("departure"))
        and (row_a.get("departure") or "") == (row_b.get("departure") or "")
        and (row_a.get("arrival") or "") == (row_b.get("arrival") or "")
    )
    window = _RECONNECT_GAP_SAME_FP_MIN if same_fp else _RECONNECT_GAP_NO_FP_MIN
    if gap_min > window:
        return False
    gap_nm = haversine(last["latitude"], last["longitude"], first["latitude"], first["longitude"]) / 1.852
    budget_nm = (max(gap_min, 0.0) / 60.0) * _MAX_GS_KT + _BUDGET_MARGIN_NM
    if gap_nm > budget_nm:
        return False
    arr = row_b.get("arrival") or row_a.get("arrival") or ""
    arr_coords = icao_to_coords(arr) if arr else None
    if arr_coords is not None:
        d_last = haversine(last["latitude"], last["longitude"], arr_coords[0], arr_coords[1])
        d_first = haversine(first["latitude"], first["longitude"], arr_coords[0], arr_coords[1])
        if d_first > d_last + _DIRECTION_TOLERANCE_KM:
            return False  # 'row_b' weiter vom Ziel weg → kein Fortschritt → kein Reconnect
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


def _is_ghost_row(conn: sqlite3.Connection, cid: int, f: dict) -> bool:
    """Ghost-Erkennung für eine Connection-/Flug-Zeile (geteilt zwischen
    :func:`canonicalize_flights` und dem Fallback-Pfad von :func:`canonicalize_legs`).

    Echte Strecke (`distance_nm > 0.5`) → kein Ghost — ABER nur, wenn ein vorhandener Track
    diese Strecke auch durch echte Bewegung deckt (s. u.). Kurz-Connect ohne Strecke
    (`duration_min <= 5`) → Test-Connect (Ghost). Länger verbunden, keine Strecke: eine
    Steh-Session ist KEIN Flug — aber nur verwerfen, wenn der Track den Stillstand BELEGT
    (Positionen im Connection-Fenster vorhanden, Blockzeit 0). Altflüge ohne Positionsdaten
    bleiben (im Zweifel echter Flug).

    Deckungs-Prüfung bei `distance_nm > 0.5` (Ghost-Filter Paket 3): reine Haversine-Distanz
    ist noch kein Flugbeweis — ein Slew/Umsetzen am Boden erzeugt genauso eine Strecke ohne
    jede Bewegung (realer Fall FRS145, 08.06.2026: 101 Samples mit groundspeed 0, ~1 nm
    „Strecke" durch GPS-Rauschen/Teleport). Sind für diese Zeile Positionen vorhanden, muss
    daher zusätzlich mindestens EIN echter Bewegungsnachweis vorliegen: >= 2 Positionen mit
    groundspeed >= 40 im Fenster `[logon_time, logoff_time]` — dasselbe Kriterium, das
    :func:`reconstruct_orphaned_flights` bereits verwendet (dort :1510-1516). Ohne
    Positionsdaten (Altflüge) bleibt das bisherige, großzügige Verhalten (im Zweifel echter
    Flug) — die neue Schranke greift NUR, wenn Positionen vorhanden sind, aber keine echte
    Bewegung zeigen.
    """
    lo, lf = f.get("logon_time"), f.get("logoff_time")
    if (f.get("distance_nm") or 0) > 0.5:
        if lo and lf:
            has_pos = conn.execute(
                "SELECT 1 FROM position_history WHERE cid=? AND ts>=? AND ts<=? LIMIT 1",
                (cid, lo, lf),
            ).fetchone()
            if has_pos is not None:
                airborne = conn.execute(
                    "SELECT COUNT(*) FROM position_history "
                    "WHERE cid=? AND ts>=? AND ts<=? AND groundspeed >= 40",
                    (cid, lo, lf),
                ).fetchone()[0]
                if airborne < 2:
                    return True
        return False
    if (f.get("duration_min") or 0) <= 5:
        return True
    if (f.get("block_min") or 0) > 0:
        return False
    if not lo or not lf:
        return False
    has_pos = conn.execute(
        "SELECT 1 FROM position_history WHERE cid=? AND ts>=? AND ts<=? LIMIT 1",
        (cid, lo, lf),
    ).fetchone()
    return has_pos is not None


def _drop_inactive(conn: sqlite3.Connection, flights: list[dict]) -> list[dict]:
    """Flüge gesperrter CIDs entfernen (Admin-Checkbox „Aktiv" in der Piloten-Pflegeliste).

    Warum hier und nicht in jeder Auswertung einzeln: ``canonicalize_flights`` und
    ``canonicalize_legs`` sind die beiden einzigen Tore, durch die Flüge überhaupt in
    Statistik, Piloten-Ansicht, Bummel und Kutter gelangen. Ein Filter je Auswertung wäre ein
    Pflaster -- man übersieht zwangsläufig eine, und dann taucht ein gesperrter Pilot doch
    wieder irgendwo auf.

    Vorgeschichte (Live-Fund 13.08.2026): Die Sperre wirkte zunächst NUR im Live-Abgleich
    (``poller`` → ``filter_friesen_pilots``). Das verhindert zwar neue Aufzeichnungen, ließ
    aber alle bereits gespeicherten Flüge in der Statistik stehen -- der Nutzer sperrte vier
    IDs und sah sie unverändert weiter. Erwartet ist: gesperrt heißt überall weg, auch
    rückwirkend. Die Flüge bleiben dabei in der Datenbank (nichts wird gelöscht); wird die
    Sperre aufgehoben, zählen sie wieder mit.
    """
    if not flights:
        return flights
    gesperrt = get_inactive_cids(conn)
    if not gesperrt:
        return flights
    return [f for f in flights if f.get("cid") not in gesperrt]


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
        merged = [f for f in merged if not _is_ghost_row(conn, cid, f)]
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
    return _drop_inactive(conn, result)


_PLAN_ROWS_LOOKBACK_H = 12  # muss zum Positions-Lookback unten passen (siehe Docstring)


def _positions_for_cid(
    conn: sqlite3.Connection,
    cid: int,
    start: str | None,
    end: str | None,
    callsign_prefix: str = "FRS",
) -> list[dict]:
    """Positionen eines Piloten für :func:`canonicalize_legs` laden.

    Lookback: ab ``start - 12h`` (statt exakt ``start``), damit ein Leg, das die
    ``start``-Grenze schneidet, nicht als Spawn-Artefakt in der Luft beginnt — der Detektor
    bekommt genug Vorlauf, um den echten (früheren) Startplatz zu sehen. ``end`` grenzt die
    Positionsladung bewusst NICHT ein: ein Leg, das kurz nach ``end`` landet, soll nicht
    künstlich als offen erscheinen. Die eigentliche Fenster-Filterung (Überlappung mit
    ``[start, end]``) passiert auf Flug-Ebene in :func:`canonicalize_legs`.

    ``callsign_prefix``: eine cid kann unter FRS- UND Nicht-FRS-Callsign geflogen sein
    (``position_history`` führt ``callsign`` je Zeile). Bei gesetztem Prefix werden nur
    Positionen mit passendem Callsign geladen, damit fremde Legs derselben cid nicht in die
    FRS-gefilterte Antwort lecken. ``callsign_prefix=""`` liefert alle Positionen der cid
    (Piloten-Detail sieht alles).
    """
    sql = (
        "SELECT latitude, longitude, altitude, groundspeed, ts, callsign "
        "FROM position_history WHERE cid = ?"
    )
    params: list = [cid]
    if start:
        lookback = (_parse_iso(start) - timedelta(hours=_PLAN_ROWS_LOOKBACK_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
        sql += " AND ts >= ?"
        params.append(lookback)
    if callsign_prefix:
        sql += " AND callsign LIKE ?"
        params.append(callsign_prefix + "%")
    sql += " ORDER BY ts"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _flightplan_asof(plan_rows: list[dict], ts: str) -> dict | None:
    """Ordnet einem Zeitpunkt (i. d. R. das Ende/die Landung eines GPS-Legs, ``end_ts``) den
    zu diesem Moment zuletzt gefileten Flugplan zu (Nutzer-Entscheidung 2026-07-05, ersetzt
    das bisherige Startplatz-Matching komplett).

    Regel: die ``flights``-Zeile mit dem größten ``logon_time <= ts`` gewinnt — unabhängig
    davon, ob deren Start/Ziel zum GPS-Start/Ziel des Legs passt. Ein während des Fluges neu
    gefileter Plan gilt ab sofort und wandert in jedes folgende Leg mit, bis der nächste
    Refile ihn ersetzt (Realitäts-Abbild: ein vergessener Refile bleibt sichtbar bestehen).
    Filed ein Pilot den nächsten Plan bereits VOR der eigenen Landung, erscheint das bewusst
    als sichtbarer Mismatch (kein Schutz eingebaut — klarer Pilotenfehler, Nutzer-Entscheidung).

    Eine Zeile OHNE jegliche Angabe (Startplatz UND Ziel leer — reiner Connect ohne je
    gefileten Plan) zählt NICHT als Treffer → ``None`` (Anzeige ``—``), sonst entstünde am
    Beginn jeder neuen Verbindung fälschlich eine „leere" Zuordnung statt ``—``.

    Kein Tie-Breaker nötig: ``(cid, logon_time)`` ist durch den partiellen Unique-Index
    ``idx_flights_session`` bereits eindeutig.

    Zeitvergleich bewusst über :func:`_parse_iso` (datetime), NICHT über String-Vergleich:
    manche ``logon_time``-Werte tragen Mikrosekunden (Refile-Split, ``app/poller.py``,
    ``"%Y-%m-%dT%H:%M:%S.%fZ"``), andere nur Sekunden (VATSIM-Feed-Werte) — lexikographischer
    String-Vergleich sortiert z. B. ``"...10:25:00.500000Z"`` fälschlich VOR ``"...10:25:00Z"``
    (weil ``.`` < ``Z`` in ASCII), obwohl 10:25:00.5 real SPÄTER liegt als 10:25:00.
    """
    ts_dt = _parse_iso(ts)
    candidates = []
    for r in plan_rows:
        lt = r.get("logon_time")
        if not lt:
            continue
        try:
            if _parse_iso(lt) <= ts_dt:
                candidates.append(r)
        except Exception:
            continue
    if not candidates:
        return None
    best = max(candidates, key=lambda r: _parse_iso(r["logon_time"]))
    if not (best.get("departure") or "").strip() and not (best.get("arrival") or "").strip():
        return None
    return best


def _statsim_plan(row: dict) -> dict:
    """Pseudo-Flugplan-Dict aus einer ``statsim_cache``-Zeile für :func:`_flightplan_asof`
    (``id=None`` — StatSim liefert keine erweiterten Flugplan-Labels)."""
    return {
        "id": None,
        "statsim_id": row.get("statsim_id"),
        "cid": row.get("cid"),
        "callsign": row.get("callsign"),
        "departure": row.get("departure"),
        "arrival": row.get("arrival"),
        "aircraft": row.get("aircraft"),
        "logon_time": row.get("logon_time"),
        "logoff_time": row.get("logoff_time"),
        "route": None,
        "remarks": None,
        "cruise_altitude": None,
        "cruise_tas": None,
        "flight_rules": None,
        "aircraft_icao": None,
        "alternate": None,
        "deptime": None,
        "enroute_time": None,
        "fuel_time": None,
    }


_GPS_LEG_GAP_MINUTES = 30  # muss zum gap_minutes-Default von detect_gps_legs passen
# Live-Guard für die Landungs-Rettung (#53): ein FriesenSpy-Leg, dessen letzter Punkt jünger als
# dieses Fenster ist, gilt als (noch) live und wird NICHT gerettet — sonst würde ein gerade
# laufender Anflug fälschlich als abgeschlossen gewertet. Deckt sich mit dem Live-Fenster im
# Frontend (``_LIVE_MAX_AGE_MS``, app/static/index.html). StatSim-Aufzeichnungen sind IMMER
# beendet (kein "live"-Konzept) und werden ohne dieses Fenster gerettet.
_GPS_RESCUE_LIVE_WINDOW_MIN = 15


def _extend_block_end(positions: list[dict], end_ts: str, cap_ts: str | None) -> str:
    """Blockfenster-ENDE über die Landung hinaus verlängern, wenn danach noch gerollt wird
    (Einrollen zum Abstellplatz — gemessen: 109 von 465 Landungen rollen nach dem erkannten
    Stillstand weiter, Median 2 min, nie mehr als 10 min. Keine feste Obergrenze hier: die
    beiden strukturellen Deckel unten reichen).

    Sucht in den Samples NACH ``end_ts`` (gedeckelt auf ``cap_ts`` — Exklusivgrenze, typisch
    der Abhebe-Zeitpunkt des chronologisch nächsten Flugs) die ERSTE qualifizierende
    Abstell-Standphase (dieselben Kriterien a+b wie in :func:`_leg_block_seconds`:
    >= _BLOCK_STAND_MIN_SEC UND an einem Flugplatz) und liefert deren BEGINN — nicht den
    letzten Zeitpunkt mit ``groundspeed > _BLOCK_GS_KT`` davor (Live-Fund 2026-08-11, cid
    1602713, Flug 666: letztes bewegtes Sample 18:03:30Z bei gs=11, tatsächlicher Stillstand
    18:03:45Z — 15 s / ~53 m Rollstrecke fehlten im Track, weil die alte Fassung genau EINEN
    Sample-Takt vor dem Stillstand abschnitt). ``stand_cap`` ist der früheste Zeitpunkt, zu
    dem die Maschine NACHWEISLICH schon steht — der letzte bewegte Sample davor liegt per
    Definition VOR dem wahren Stillstand, ``stand_cap`` liegt (spätestens im selben Sample)
    DANACH; als Obergrenze für die Anzeige ist das die genauere Wahl.

    Ab ``stand_cap`` ist die Maschine nachweislich geparkt — jede spätere Bewegung (z. B.
    Pushback für den NÄCHSTEN Flug) gehört nicht mehr hierher.

    OHNE qualifizierende Standphase (Suche läuft ohne 600-s-Stand aus — Datenende, Disconnect,
    oder von ``cap_ts``/der Zeitlücken-Schranke beschnitten, bevor 600 s zusammenkommen) ist
    das Ergebnis der LETZTE verfügbare Sample-Zeitpunkt (``tail[-1]``) — NICHT mehr der letzte
    Zeitpunkt mit ``groundspeed > _BLOCK_GS_KT`` (zweiter Live-Fund 2026-08-11, cid 1602713,
    Flug 666: die Aufzeichnung endet bereits 4,5 min nach dem Stillstand — 18:03:45Z bis
    18:08:15Z, keine 10 min —, der alte Fallback sprang deshalb auf 18:03:30Z zurück, den
    letzten BEWEGTEN Sample, und ignorierte damit sogar die 4,5 min direkt belegte Standzeit
    danach). Ein kurzer, noch nicht qualifizierender Stand VOR dem Datenende zählt nach
    demselben Prinzip wie ein kurzer Rollhalt in der Blockzeit selbst (< ``_BLOCK_STAND_MIN_SEC``
    bleibt enthalten) — die letzte verfügbare Position ist immer die beste Schätzung dafür,
    wie weit diese Leg-eigene Aktivität (Rollen ODER kurzes, noch unbewiesenes Stehen)
    nachweislich reicht.

    Zusätzlich wird die Suche selbst an einer Zeitlücke > ``_GPS_LEG_GAP_MINUTES`` beendet
    (dieselbe Schwelle wie beim offenen-Leg-Fensterende oben) — sonst könnte bei fehlendem
    ``cap_ts`` (letzter Flug seines Segments) ein VÖLLIG anderes, viel späteres Segment
    (z. B. die nächste Session Stunden danach) fälschlich mit hineingezogen werden.

    Ohne jede Position danach bleibt es bei ``end_ts``.
    """
    from app import geo

    candidates = sorted(
        (p for p in positions if p["ts"] > end_ts and (cap_ts is None or p["ts"] < cap_ts)),
        key=lambda p: p["ts"],
    )
    tail: list[dict] = []
    prev_ts = end_ts
    for p in candidates:
        gap_min = (_parse_iso(p["ts"]) - _parse_iso(prev_ts)).total_seconds() / 60.0
        if gap_min > _GPS_LEG_GAP_MINUTES:
            break
        tail.append(p)
        prev_ts = p["ts"]
    if not tail:
        return end_ts

    # Deckel (i): Beginn der ersten qualifizierenden Abstell-Standphase in `tail` finden.
    stand_cap: str | None = None
    run_first = run_last = None
    run_pos = None
    for p in tail:
        gs = p.get("groundspeed")
        if gs is None:
            continue
        if gs <= _BLOCK_GS_KT:
            if run_first is None:
                run_first = p["ts"]
                run_pos = (p.get("latitude"), p.get("longitude"))
            run_last = p["ts"]
        else:
            if run_first is not None and run_last is not None:
                dur = (_parse_iso(run_last) - _parse_iso(run_first)).total_seconds()
                if (
                    dur >= _BLOCK_STAND_MIN_SEC and run_pos and run_pos[0] is not None
                    and geo.nearest_airport_icao_fast(
                        run_pos[0], run_pos[1], _BUMMEL_AIRPORT_RADIUS_KM
                    ) is not None
                ):
                    stand_cap = run_first
                    break
            run_first = run_last = None
            run_pos = None
    if stand_cap is None and run_first is not None and run_last is not None:
        dur = (_parse_iso(run_last) - _parse_iso(run_first)).total_seconds()
        if (
            dur >= _BLOCK_STAND_MIN_SEC and run_pos and run_pos[0] is not None
            and geo.nearest_airport_icao_fast(
                run_pos[0], run_pos[1], _BUMMEL_AIRPORT_RADIUS_KM
            ) is not None
        ):
            stand_cap = run_first

    if stand_cap is not None:
        return stand_cap

    return tail[-1]["ts"]


def _gps_flights_for_positions(
    positions: list[dict], *, plan_rows: list[dict], source: str, radius_km: float | None = None
) -> list[dict]:
    """GPS-Flüge (Task-1/2-Detektor + Collapse) über eine ÜBERGEBENE Positionsliste in
    kanonische Flug-Dicts übersetzen — Metriken via Task-3-Helfer auf denselben Positionen
    (``_block_seconds_positions`` / ``_distance_nm_positions``), damit die Funktion für
    ``position_history`` (FriesenSpy) UND ``statsim_position_history``-Tracks (StatSim)
    gleichermaßen funktioniert.

    ``plan_rows``: Kandidaten-Flugpläne/Connections (``flights``-Zeilen bzw.
    :func:`_statsim_plan`-Pseudo-Zeilen) für :func:`_flightplan_asof`. Trägt KEIN ``cid`` —
    der Aufrufer kennt es aus dem Iterationskontext und setzt es. Enthält einen internen
    Schlüssel ``_coverage_end`` (letzter belegter ts — für den Pro-Flug-Dedup in
    :func:`canonicalize_legs`); der Aufrufer entfernt ihn vor der Rückgabe.

    ``radius_km``: Erkennungs-Umkreis für ``detect_gps_legs`` (Platz-Zuordnung Start/Ziel).
    ``None`` → Default ``_BUMMEL_AIRPORT_RADIUS_KM`` (4 km, unverändertes Verhalten).

    Zwei Metriken je Flug (KORREKTUR #23 Phase 2, seit „Blockzeit-Anblock" auf Leg-eigene
    Helfer umgestellt): ``block_min`` = Blockzeit als WANDUHR über ``[block_from,
    block_end]`` MINUS belegter Abstell-Standphasen an einem Flugplatz (s.
    :func:`_leg_block_seconds`) — ``block_from`` beginnt an der ERSTEN nachweisbaren
    Bewegung (nicht erst am rohen Rollbeginn ``block_start``, s. u.), ``block_end`` reicht
    ggf. über die Landung hinaus bis zum Ende des Einrollens (s.
    :func:`_extend_block_end`). ``duration_min`` = reine Flugzeit ``[takeoff_ts, end_ts]``
    MINUS positionsbasierter Bodenphasen (s. :func:`_air_seconds`, ersetzt die frühere
    reine Wanduhr-Differenz — Außenlandungen mit Standzeit MITTEN im Flug zählten sonst
    fälschlich als Flugzeit mit).

    GARANTIE: ``duration_min <= block_min``, immer — ``[takeoff_ts, end_ts]`` liegt
    innerhalb ``[block_from, block_end]``, und jede Standphase, die die Blockzeit abzieht
    UND im Flugfenster liegt, erfüllt wegen des STRENGEREN Block-Kriteriums (>=
    ``_BLOCK_STAND_MIN_SEC`` UND an einem Flugplatz) automatisch auch das lockerere
    Flugzeit-Kriterium (>= ``_AIR_GROUND_MIN_SEC``, überall) — Flugzeit zieht also nie
    weniger ab, als Blockzeit es innerhalb desselben Fensters tut. Zusätzlich zu dieser
    strukturellen Herleitung wird ``block_min`` unten hart auf ``duration_min`` gefloort
    (``max(block_min, duration_min)``) — ein Sicherheitsnetz für den Fall, dass eine Quelle
    Groundspeed durchgehend fehlerhaft als 0 statt ``None`` meldet (z. B.
    ``statsim.py`` `p.get("speed", 0)`): dann kann ``_leg_block_seconds`` einen einzigen,
    das GESAMTE Fenster überspannenden Fehl-Lauf sehen (Start nahe einem Flugplatz ist bei
    einem Abflug strukturell IMMER gegeben) und 0 liefern, obwohl echte Positionsbewegung
    (das Kriterium von ``_air_seconds``) eine positive Flugzeit belegt — ohne den Floor
    wäre die Garantie in genau diesem Randfall verletzt.
    """
    from app import geo
    from app.gps_legs import detect_gps_legs, collapse_same_airport

    # #53: StatSim-Aufzeichnungen sind immer beendet -> immer retten (rescue_before=None).
    # FriesenSpy-Tracks können live sein -> nur retten, wenn der letzte Punkt außerhalb des
    # Live-Fensters liegt (sonst würde ein laufender Anflug fälschlich geschlossen).
    rescue_before = None if source == "statsim" else (
        datetime.now(timezone.utc) - timedelta(minutes=_GPS_RESCUE_LIVE_WINDOW_MIN)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    legs = detect_gps_legs(
        positions,
        nearest_airport=geo.nearest_airport_icao_fast,
        airport_elev_ft=geo.airport_elevation_ft,
        radius_km=radius_km if radius_km is not None else _BUMMEL_AIRPORT_RADIUS_KM,
        rescue_before=rescue_before,
    )
    gps_flights = collapse_same_airport(legs)
    if not gps_flights:
        return []

    all_ts = sorted(p["ts"] for p in positions if p.get("ts"))
    callsign_by_ts = {p["ts"]: p.get("callsign") for p in positions if p.get("callsign")}

    out: list[dict] = []
    for i, gf in enumerate(gps_flights):
        takeoff_ts = gf.get("takeoff_ts")
        landing_ts = gf.get("landing_ts")
        # Abhebe-ts des chronologisch nächsten Flugs (``gps_flights`` ist chronologisch
        # geordnet) — Deckel sowohl für das offene-Leg-Fensterende unten als auch für die
        # Blockfenster-Verlängerung nach der Landung (s. ``_extend_block_end``).
        next_takeoff = gps_flights[i + 1].get("takeoff_ts") if i + 1 < len(gps_flights) else None
        if landing_ts:
            end_ts = landing_ts
        else:
            # Offener/unvollständiger Flug: struktureller Vertrag von _detect_segment — ein
            # incomplete Leg entsteht AUSSCHLIESSLICH am Segment-Ende (Sample-Schleife endet
            # noch airborne). Ein solcher offener Flug ist also IMMER der letzte Flug seines
            # Zeit-Segments; ein evtl. Folgeflug gehört zwingend zum NÄCHSTEN Segment (Gap
            # > 30 min, derselbe Schwellwert wie detect_gps_legs). Fenster-Ende daher: letzter
            # belegter ts ab Takeoff, gekappt VOR der ersten Zeitlücke > 30 min danach (=
            # Segment-Ende) — sonst würde ein Absturz→Reconnect-Segment (neuer Flug nach der
            # Lücke) fälschlich in die Metriken dieses offenen Flugs mit hineingezählt (inkl.
            # Haversine-Sprung Crash→Respawn UND der reinen Zeitlücke selbst in duration_min).
            # Zusätzlich (redundante zweite Absicherung) am Takeoff des chronologisch nächsten
            # Flugs gekappt, falls vorhanden (``gps_flights`` ist chronologisch geordnet).
            tail = [t for t in all_ts if t >= takeoff_ts]
            end_ts = tail[0] if tail else takeoff_ts
            for prev_ts, cur_ts in zip(tail, tail[1:]):
                gap_min = (_parse_iso(cur_ts) - _parse_iso(prev_ts)).total_seconds() / 60.0
                if gap_min > _GPS_LEG_GAP_MINUTES:
                    break
                end_ts = cur_ts
            if next_takeoff is not None and end_ts >= next_takeoff:
                end_ts = takeoff_ts  # Sicherheitsnetz; strukturell sollte dieser Zweig nie greifen

        # Block-Fenster nach vorn bis zum Rollbeginn (gate-to-gate inkl. Taxi). Der Rollbeginn
        # wird NICHT hier rekonstruiert, sondern kommt aus ``detect_gps_legs`` — dieselbe
        # Zustandsmaschine, die auch den Startplatz bestimmt hat (``taxi_start_ts`` = Beginn der
        # Boden-Phase an genau diesem Platz). Damit passen Strecke und Track-Fenster per
        # Konstruktion zusammen: eine Rollphase an einem anderen Platz (Reconnect) oder vor der
        # Landung des Vorflugs kann strukturell nicht hineinlaufen. Fehlt der Wert (Spawn in der
        # Luft), beginnt das Fenster am Abheben. ACHTUNG: ``block_start`` bleibt dieser rohe
        # Rollbeginn — er ist ein EIGENER Vertrag (Track-Untergrenze fürs Frontend, #62, s.
        # Kommentar am Feld unten) und wird NICHT angetastet. Für die Blockzeit-BERECHNUNG
        # selbst wird stattdessen ``block_from`` benutzt (s. u.).
        block_start = gf.get("taxi_start_ts") or takeoff_ts

        # Blockfenster-ANFANG (``block_from``): die ERSTE nachweisbare Bewegung (groundspeed
        # > _BLOCK_GS_KT) zwischen dem rohen Rollbeginn und dem (noch unverlängerten)
        # Flugfenster-Ende — nicht ``block_start`` selbst. Grund: der Abhebe-Trigger in
        # ``detect_gps_legs`` ist höhenbasiert und funktioniert auch OHNE Groundspeed-Signal
        # (gps_legs.py:215-224). Ohne dieses ``min(...)`` würde ``block_start`` (der reine
        # „am Boden erkannt"-Zeitpunkt, ohne Bewegungsnachweis) unverändert als Fensteranfang
        # dienen — bei einer Quelle mit fehlendem/konstant 0 gemeldetem Speed (StatSim:
        # ``statsim.py:127`` `p.get("speed", 0)`) liefert das im Extremfall ``block_min`` nahe
        # 0 trotz voller Flugzeit (s. GARANTIE-Kommentar am Funktionskopf, dort auch der
        # Floor, der das strukturell absichert). Wird keine Bewegung gefunden, gilt
        # ``takeoff_ts`` (frühestens dort ist die Bewegung durch das Abheben selbst belegt).
        moves_in_window = [
            p["ts"] for p in positions
            if block_start <= p["ts"] <= end_ts and (p.get("groundspeed") or 0) > _BLOCK_GS_KT
        ]
        block_from = min(min(moves_in_window), takeoff_ts) if moves_in_window else takeoff_ts

        # Blockfenster-ENDE (``block_end``): normalerweise ``end_ts`` — zusätzlich über die
        # Landung hinaus verlängert, wenn danach noch eingerollt wird (s. ``_extend_block_end``).
        # Nur bei einer ECHTEN Landung sinnvoll (offene Legs haben nichts zum „Einrollen").
        block_end = _extend_block_end(positions, end_ts, next_takeoff) if landing_ts else end_ts

        block_min = _leg_block_seconds(positions, block_from, block_end) // 60
        distance_nm = _distance_nm_positions(positions, takeoff_ts, end_ts)
        duration_min = _air_seconds(positions, takeoff_ts, end_ts) // 60
        # Sicherheitsnetz für die GARANTIE duration_min <= block_min (Herleitung + der eine
        # bekannte Randfall, in dem sie allein nicht reicht: s. Docstring am Funktionskopf).
        block_min = max(block_min, duration_min)

        plan = _flightplan_asof(plan_rows, end_ts)
        gps_dep = gf.get("dep_icao")
        gps_arr = gf.get("arr_icao")
        plan_dep = plan.get("departure") if plan else None
        plan_arr = plan.get("arrival") if plan else None
        departure = gps_dep or plan_dep
        # Kein Plan-Fallback für arrival: ein abgestürzter/offener Flug soll NICHT das
        # geplante Ziel als arrival zeigen (sähe sonst wie gelandet aus, Bummel-/
        # Kutter-Zielwertung). leer/None = offen.
        arrival = gps_arr

        if source == "friesenspy":
            connection_closed = bool(plan.get("logoff_time")) if plan else False
        else:
            connection_closed = True

        callsign = (plan.get("callsign") if plan else None) or callsign_by_ts.get(takeoff_ts)

        out.append({
            "id": plan.get("id") if plan else None,
            "statsim_id": plan.get("statsim_id") if plan else None,
            "cid": plan.get("cid") if plan else None,
            "callsign": callsign,
            "aircraft": plan.get("aircraft") if plan else None,
            "departure": departure,
            "arrival": arrival,
            "gps_departure": gps_dep,
            "gps_arrival": gps_arr,
            "plan_departure": plan_dep,
            "plan_arrival": plan_arr,
            "logon_time": takeoff_ts,
            "logoff_time": landing_ts,
            # block_start = Rollbeginn (``taxi_start_ts`` aus detect_gps_legs, s. oben). Dient dem
            # Frontend als Track-Untergrenze (#62), damit Taxi-out + Startlauf sichtbar sind —
            # takeoff_ts (Abheben) schnitt sie bisher ab. Nur relevant für die gefensterten
            # FriesenSpy-Track-Endpoints; der StatSim-Track lädt ohnehin ungefenstert.
            "block_start": block_start,
            # block_end = Blockfenster-Ende (s. ``_extend_block_end``) — normalerweise
            # ``end_ts`` (Landung bzw. bisheriges Tracking-Ende bei offenem Leg), bei
            # nachgewiesenem Einrollen zum Abstellplatz bis zum letzten Rollsample verlängert.
            "block_end": block_end,
            "duration_min": duration_min,
            "distance_nm": distance_nm,
            "block_min": block_min,
            "route": (plan.get("route") if plan else None) or "",
            "remarks": (plan.get("remarks") if plan else None) or "",
            "cruise_altitude": plan.get("cruise_altitude") if plan else None,
            "cruise_tas": plan.get("cruise_tas") if plan else None,
            "flight_rules": plan.get("flight_rules") if plan else None,
            "aircraft_icao": plan.get("aircraft_icao") if plan else None,
            "alternate": plan.get("alternate") if plan else None,
            "deptime": plan.get("deptime") if plan else None,
            "enroute_time": plan.get("enroute_time") if plan else None,
            "fuel_time": plan.get("fuel_time") if plan else None,
            "connection_closed": connection_closed,
            "source": source,
            "_coverage_end": end_ts,
        })
    return out


def _flightrow_as_flight(row: dict, source: str) -> dict:
    """Fallback-Flug direkt aus einer ``flights``-/``statsim_cache``-Zeile OHNE GPS-Track.

    GPS unbekannt (``gps_departure``/``gps_arrival`` = ``None``); ``departure``/``arrival``
    kommen aus dem Flugplan der Zeile selbst. ``connection_closed``: FriesenSpy = ``logoff_time``
    der Zeile gesetzt; StatSim = immer ``True`` (Spec — StatSim-Sessions werden grundsätzlich
    erst abgeschlossen erfasst).
    """
    if source == "statsim":
        return {
            "id": None,
            "statsim_id": row.get("statsim_id"),
            "cid": row.get("cid"),
            "callsign": row.get("callsign"),
            "aircraft": row.get("aircraft"),
            "departure": row.get("departure"),
            "arrival": row.get("arrival"),
            "gps_departure": None,
            "gps_arrival": None,
            "plan_departure": row.get("departure"),
            "plan_arrival": row.get("arrival"),
            "logon_time": row.get("logon_time"),
            "logoff_time": row.get("logoff_time"),
            "duration_min": row.get("duration_min"),
            "distance_nm": None,
            "block_min": None,
            "route": "",
            "remarks": "",
            "cruise_altitude": None,
            "cruise_tas": None,
            "flight_rules": None,
            "aircraft_icao": None,
            "alternate": None,
            "deptime": None,
            "enroute_time": None,
            "fuel_time": None,
            "connection_closed": True,
            "source": source,
            "last_pos_ts": row.get("logoff_time"),
        }

    return {
        "id": row.get("id"),
        "statsim_id": None,
        "cid": row.get("cid"),
        "callsign": row.get("callsign"),
        "aircraft": row.get("aircraft"),
        "departure": row.get("departure"),
        "arrival": row.get("arrival"),
        "gps_departure": None,
        "gps_arrival": None,
        "plan_departure": row.get("departure"),
        "plan_arrival": row.get("arrival"),
        "logon_time": row.get("logon_time"),
        "logoff_time": row.get("logoff_time"),
        "duration_min": row.get("duration_min"),
        "distance_nm": row.get("distance_nm"),
        "block_min": row.get("block_min"),
        "route": row.get("route"),
        "remarks": row.get("remarks"),
        "cruise_altitude": row.get("cruise_altitude"),
        "cruise_tas": row.get("cruise_tas"),
        "flight_rules": row.get("flight_rules"),
        "aircraft_icao": row.get("aircraft_icao"),
        "alternate": row.get("alternate"),
        "deptime": row.get("deptime"),
        "enroute_time": row.get("enroute_time"),
        "fuel_time": row.get("fuel_time"),
        "connection_closed": row.get("logoff_time") is not None,
        "source": source,
        "last_pos_ts": row.get("logoff_time"),
    }


def _overlaps_any(
    intervals: list[tuple], lo: str | None, hi: str | None
) -> bool:
    """True, wenn ``[lo, hi]`` eines der ``intervals`` (Liste von ``(start, end)``-Tupeln)
    überlappt (lexikographischer ISO8601-UTC-Vergleich). ``None``-Ende — bei ``hi`` UND
    innerhalb von ``intervals`` — bedeutet ein offenes Ende (∞)."""
    if lo is None:
        return False
    _INF = "9999-12-31T23:59:59Z"
    hi_eff = hi or _INF
    for a, b in intervals:
        if a is None:
            continue
        b_eff = b or _INF
        if a <= hi_eff and lo <= b_eff:
            return True
    return False


def canonicalize_legs(
    conn: sqlite3.Connection,
    *,
    cids: list[int] | None = None,
    start: str | None = None,
    end: str | None = None,
    callsign_prefix: str = "FRS",
    radius_km: float | None = None,
) -> list[dict]:
    """GPS-Pendant zu :func:`canonicalize_flights` — künftig die EINZIGE Wahrheit unter
    GPS-only Phase 2 (#23). Formgleich: jedes Flug-Dict trägt mindestens dieselben Keys wie
    ``canonicalize_flights`` PLUS ``gps_departure``, ``gps_arrival``, ``plan_departure``,
    ``plan_arrival``, ``connection_closed``.

    Ablauf: Fenster-Lookback (Positionen ab ``start - 12h``, gegen Spawn-Artefakte an der
    Fensterkante) → je Pilot/StatSim-Flug Detektor + Collapse über die ECHTEN Positionen →
    Flugplan-Zuordnung (zeitbasiert — zuletzt gefilter Plan zum Landungs-/Leg-Ende, Spec G
    aktualisiert 2026-07-05) → Fallback auf die reine Connection-/
    StatSim-Zeile, wenn kein Track vorliegt (bzw. kein Leg erkannt wurde) → Ergebnis auf
    Überlappung mit ``[start, end]`` gefiltert → StatSim-Flüge, die einen FriesenSpy-Flug
    DESSELBEN cid überlappen, werden verworfen (PRO FLUG, nicht pro Session — Teil-
    Überlappung, z. B. nach einem FS-Absturz, lässt den unüberdeckten StatSim-Rest überleben)
    → Sortierung ``logon_time`` absteigend.

    ``callsign_prefix=""`` liefert alle Callsigns (für die Piloten-Detail-Ansicht).

    ``radius_km``: Erkennungs-Umkreis für die Platz-Zuordnung (Start/Ziel) im GPS-Leg-
    Detektor, an ``_gps_flights_for_positions``/``detect_gps_legs`` durchgereicht (FriesenSpy-
    UND StatSim-Zweig gleichermaßen). ``None`` (Default) → ``_BUMMEL_AIRPORT_RADIUS_KM``
    (4 km) — unverändertes Verhalten für die globale Statistik/den Cache.

    Hinweis ``connection_closed``: NICHT als „Flug nicht beendet" lesen. Ein gelandeter
    GPS-Flug ohne Plan-Match liefert konservativ ``connection_closed=False`` (kein Beweis
    für ein Connection-Ende vorhanden) — ob der FLUG selbst beendet ist, entscheidet allein
    ``arrival``/``gps_arrival``/``logoff_time``, nicht dieses Feld.
    """
    prefix_pat = callsign_prefix + "%"
    # Plan-Kandidaten (fs_where/sc_where) bekommen an BEIDEN Rändern denselben Puffer
    # (_PLAN_ROWS_LOOKBACK_H) wie die GPS-Positionen (_positions_for_cid) — die eigentliche
    # Leg-Auswahl passiert erst auf Flug-Ebene (_in_window). Ohne den Puffer fällt ein
    # Flugplan aus den Kandidaten, obwohl das zugehörige GPS-Leg im Ergebnis erscheint:
    #   - start-Seite (Live-Fund 2026-07-05, FRS61 ETHB→ETHS, Landung ~15:12): eine Connection,
    #     deren logoff_time knapp VOR `start` liegt, verschwand aus den Kandidaten → leeres
    #     Flugplan-Feld + falscher Aircraft-Fallback.
    #   - end-Seite (Live-Fund 2026-07-05, FRS119N LOWZ→LIME): ein Refile mit Startplatz-Wechsel
    #     WÄHREND eines noch im Fenster gestarteten Legs erzeugt eine flights-Zeile, deren
    #     logon_time (Poller-Erkennungszeit) NACH `end` liegt → das Leg bekam fälschlich den
    #     alten Plan/Muster (zwei verschiedene "Wahrheiten" zwischen Statistik und Events).
    plan_lookback_start = (
        _shift_iso(start, hours=-_PLAN_ROWS_LOOKBACK_H) if start else None
    )
    plan_lookahead_end = (
        _shift_iso(end, hours=_PLAN_ROWS_LOOKBACK_H) if end else None
    )

    # --- FriesenSpy: Connections im Fenster → cid-Menge -------------------------------
    # Bewusst OHNE "logoff_time IS NOT NULL" (anders als canonicalize_flights): unter
    # GPS-only ist die Connection nicht mehr die Wahrheit für "abgeschlossen" — das
    # übernimmt connection_closed, das auch für noch offene Connections False liefert.
    # Overlap-WHERE (Controller-Entscheidung, Brief war intern widersprüchlich): eine Zeile
    # zählt, wenn sie NICHT vor `start` endet UND NICHT nach `end` beginnt — so werden auch
    # Sessions gefangen, die vor `start` einloggen und über die Grenze fliegen (genau wofür
    # der 12h-Lookback gedacht ist).
    fs_where = ["superseded_by IS NULL", "callsign LIKE ?"]
    fs_params: list = [prefix_pat]
    if cids:
        fs_where.append("cid IN (%s)" % ",".join("?" * len(cids)))
        fs_params += list(cids)
    if plan_lookback_start:
        fs_where.append("(logoff_time IS NULL OR logoff_time >= ?)")
        fs_params.append(plan_lookback_start)
    if plan_lookahead_end:
        fs_where.append("logon_time <= ?")
        fs_params.append(plan_lookahead_end)
    fs_rows = [
        dict(r)
        for r in conn.execute(
            "SELECT id, cid, callsign, aircraft_short AS aircraft, departure, arrival, "
            "logon_time, logoff_time, duration_min, distance_nm, block_min, route, remarks, "
            "cruise_altitude, cruise_tas, flight_rules, aircraft_icao, alternate, "
            "deptime, enroute_time, fuel_time FROM flights WHERE "
            + " AND ".join(fs_where)
            + " ORDER BY cid, logon_time",
            fs_params,
        ).fetchall()
    ]
    fs_by_cid: dict[int, list[dict]] = {}
    for r in fs_rows:
        fs_by_cid.setdefault(r["cid"], []).append(r)

    def _in_window(f: dict) -> bool:
        takeoff = f.get("logon_time")
        if takeoff is None:
            return False
        if end and takeoff > end:
            return False
        # Ohne erkannte Landung zaehlt die LETZTE POSITION als Ende. Sonst faellt die
        # Pruefung bei `logoff_time is None` ersatzlos aus, und ein laengst beendetes Leg
        # gilt als "im Fenster" -- der GPS-Track bricht ja nur ab, das Leg endet trotzdem.
        # Live-Fund 04.09.2026: FRS61 flog vormittags in Texas (letzte Position 09:51:30Z,
        # keine Landung erkannt) und abends beim Ausmotten-Event mit. Im Eventfenster ab
        # 17:00Z tauchte das Dallas-Leg mit auf; die Events-Karte spannte per fitBounds von
        # Dallas bis Wangerooge und stand mitten im Atlantik.
        landing = f.get("logoff_time") or f.get("last_pos_ts")
        if start and landing is not None and landing < start:
            return False
        return True

    fs_flights: list[dict] = []
    fs_intervals_by_cid: dict[int, list[tuple]] = {}

    for cid, rows in fs_by_cid.items():
        positions = _positions_for_cid(conn, cid, start, end, callsign_prefix=callsign_prefix)
        gps_flights = _gps_flights_for_positions(
            positions, plan_rows=rows, source="friesenspy", radius_km=radius_km
        )
        if gps_flights:
            for f in gps_flights:
                f["cid"] = cid
                # #52: kein Vermutungs-Fallback mehr — ohne Plan-Match (GPS-only-Leg) bleibt
                # f["aircraft"] ehrlich None, statt einen (ggf. zeitlich falschen) Typ aus
                # früheren Flügen des Piloten zu erraten.
                coverage_end = f.pop("_coverage_end", None)
                # last_pos_ts = Zeit der letzten belegten Position dieses Legs (statisch,
                # NICHT „now"). Frontend leitet daraus „läuft" (offen UND frisch) ab und nutzt
                # es als Track-Obergrenze offener Legs (#v8.1.0).
                f["last_pos_ts"] = coverage_end or f.get("logoff_time")
                fs_flights.append(f)
                fs_intervals_by_cid.setdefault(cid, []).append(
                    (f.get("logon_time"), coverage_end or f.get("logoff_time"))
                )
        else:
            # Keine GPS-Flüge trotz Zeilen → nur GESCHLOSSENE, nicht-ghost Zeilen als eigenen
            # Flug übernehmen. Eine offene Fallback-Zeile würde sonst ein (logon, ∞)-Dedup-
            # Intervall erzeugen, das ALLE späteren StatSim-Flüge der cid unterdrückt; Test-
            # Connects/belegte Steh-Sessions sind ohnehin kein Flug (Ghost-Regel wie
            # canonicalize_flights). Offene/Ghost-Zeilen bleiben Teil von `rows` (plan_rows
            # für _flightplan_asof im GPS-Zweig), fließen hier nur nicht als eigener Flug.
            for row in rows:
                if row.get("logoff_time") is None:
                    continue
                if _is_ghost_row(conn, cid, row):
                    continue
                f = _flightrow_as_flight(row, "friesenspy")
                fs_flights.append(f)
                fs_intervals_by_cid.setdefault(cid, []).append(
                    (f.get("logon_time"), f.get("logoff_time"))
                )

    fs_flights = [f for f in fs_flights if _in_window(f)]
    result: list[dict] = list(fs_flights)

    # --- StatSim ------------------------------------------------------------------------
    sc_where = [
        "logon_time != ''", "logoff_time IS NOT NULL", "duration_min > 5", "callsign LIKE ?",
    ]
    sc_params: list = [prefix_pat]
    if cids:
        sc_where.append("cid IN (%s)" % ",".join("?" * len(cids)))
        sc_params += list(cids)
    if plan_lookback_start:
        # Overlap-WHERE analog FS (StatSim hat logoff_time immer gesetzt — die
        # IS-NULL-Klausel greift dort nie, ist aber harmlos). Derselbe Puffer an BEIDEN
        # Rändern wie bei fs_where — jede statsim_cache-Zeile ist ihr eigener Plan
        # (_statsim_plan), eine knapp vor `start` bzw. knapp nach `end` liegende Session soll
        # ebenfalls nicht herausfallen (die Leg-Auswahl erledigt _in_window).
        sc_where.append("(logoff_time IS NULL OR logoff_time >= ?)")
        sc_params.append(plan_lookback_start)
    if plan_lookahead_end:
        sc_where.append("logon_time <= ?")
        sc_params.append(plan_lookahead_end)
    sc_rows = [
        dict(r)
        for r in conn.execute(
            "SELECT statsim_id, cid, callsign, departure, arrival, aircraft, "
            "logon_time, logoff_time, duration_min FROM statsim_cache WHERE "
            + " AND ".join(sc_where)
            + " ORDER BY cid, logon_time",
            sc_params,
        ).fetchall()
    ]

    # StatSim schneidet einen echten durchgehenden Flug manchmal MITTEN IN DER LUFT in zwei
    # statsim_ids (Live-Fund 2026-07-06, KNF04WC CYYR→KCAR→KOWD — s. _statsim_rows_continuous).
    # Verarbeitet man jede id isoliert, entsteht dabei ein Geister-Leg ("KCAR → —", gestartet
    # aber nie gelandet, weil die Positionsdaten dieser id vor der Landung enden). Deshalb
    # werden zeitlich benachbarte Zeilen DESSELBEN Piloten erst zu Clustern zusammengefasst
    # (dieselben Reconnect-Regeln wie bei FriesenSpy-Verbindungsabbrüchen), bevor der
    # Detektor läuft — Positionen werden aneinandergehängt, alle betroffenen Flugpläne
    # gemeinsam als plan_rows übergeben (_flightplan_asof ordnet dann jedem erkannten Leg
    # automatisch den zeitlich richtigen Plan zu, genau wie beim FriesenSpy-Zweig).
    sc_by_cid: dict[int, list[dict]] = {}
    for row in sc_rows:
        sc_by_cid.setdefault(row["cid"], []).append(row)

    st_flights: list[dict] = []
    for cid, rows in sc_by_cid.items():
        row_positions = [get_statsim_positions(conn, r["statsim_id"]) for r in rows]
        clusters: list[list[int]] = []
        current = [0]
        for i in range(1, len(rows)):
            if _statsim_rows_continuous(rows[i - 1], rows[i], row_positions[i - 1], row_positions[i]):
                current.append(i)
            else:
                clusters.append(current)
                current = [i]
        clusters.append(current)

        for idx_list in clusters:
            cluster_rows = [rows[i] for i in idx_list]
            cluster_positions = [p for i in idx_list for p in row_positions[i]]
            plan_rows = [_statsim_plan(r) for r in cluster_rows]
            gps_flights = _gps_flights_for_positions(
                cluster_positions, plan_rows=plan_rows, source="statsim", radius_km=radius_km
            )
            if gps_flights:
                for f in gps_flights:
                    f["cid"] = cid
                    if not f.get("aircraft"):
                        # Kein Plan-Match (GPS-only-Leg): die erste Zeile des Clusters kennt
                        # den Typ bereits (row.aircraft) -> kein Vermutungs-Fallback nötig (#52).
                        f["aircraft"] = cluster_rows[0].get("aircraft") or None
                    if not f.get("callsign"):
                        # Kein Plan-Match (z. B. Spawn-in-der-Luft, dep_icao unbekannt) UND
                        # statsim_position_history hat KEINE callsign-Spalte (anders als
                        # position_history bei FriesenSpy) -> callsign_by_ts liefert für StatSim
                        # nie einen Treffer. Ohne diesen Fallback bliebe die Zeile callsign-los,
                        # obwohl die statsim_cache-Zeile ihn längst kennt (row.callsign).
                        f["callsign"] = cluster_rows[0].get("callsign") or None
                    # _coverage_end bleibt vorerst im Dict (symmetrisch zur FS-Seite, FIX 6) —
                    # wird erst kurz vor der Rückgabe für die Dedup-Obergrenze genutzt und dann
                    # entfernt. Sonst bekäme ein offener StatSim-GPS-Flug hi=∞ und würde von
                    # jedem späteren FS-Flug fälschlich als "überdeckt" gewertet.
                    st_flights.append(f)
            else:
                for row in cluster_rows:
                    st_flights.append(_flightrow_as_flight(row, "statsim"))

    st_flights = [f for f in st_flights if _in_window(f)]

    for f in st_flights:
        intervals = fs_intervals_by_cid.get(f.get("cid"), [])
        coverage_end = f.pop("_coverage_end", None)
        hi = coverage_end or f.get("logoff_time")
        f["last_pos_ts"] = coverage_end or f.get("logoff_time")
        if _overlaps_any(intervals, f.get("logon_time"), hi):
            continue
        result.append(f)

    result.sort(key=lambda x: x.get("logon_time") or "", reverse=True)
    return _drop_inactive(conn, result)


def audit_gps_vs_refile(
    conn: sqlite3.Connection,
    *,
    cids: list[int] | None = None,
    start: str | None = None,
    end: str | None = None,
    callsign_prefix: str = "FRS",
    statsim_sample: int = 0,
) -> dict:
    """Vergleicht die heutigen Refile-Flüge (:func:`canonicalize_flights`) mit der collapsed
    GPS-Sicht aus :func:`canonicalize_legs` — REIN LESEND, ändert nichts (GPS-only Phase 2,
    #23, Task 6). Ein Platzrunden-Track (mehrere Landungen am SELBEN Platz) zählt dabei als
    EIN GPS-Flug, nicht als N Roh-Legs — das übernimmt ``collapse_same_airport`` bereits
    innerhalb von ``canonicalize_legs``.

    ``statsim_sample`` > 0 hängt zusätzlich eine ``statsim``-Sektion an: die GPS-Leg-Interpretation
    der jüngsten bis zu ``statsim_sample`` StatSim-Flüge im Fenster, **on-demand aus
    ``statsim_position_history`` gerechnet (in-memory, NICHTS gespeichert)** — zeigt, wie StatSim-
    Flüge unter GPS-only aussähen. ``detect_gps_legs`` + ``collapse_same_airport`` bleiben
    unverändert; nur die Datenquelle ist die StatSim-Positionstabelle.

    Je FriesenSpy-Connection (StatSim hat keine ``position_history`` → keine GPS-Sicht, aus den
    Match-Nennern ausgeschlossen) werden die überlappenden ``canonicalize_legs``-Flüge desselben
    ``cid`` gesucht, deren ``logon_time`` (= Takeoff) im Connection-Fenster
    ``[logon_time, logoff_time]`` liegt (``logoff_time`` None → offenes Fenster). Aus der GPS-Sicht
    werden dabei NUR echte Track-Treffer herangezogen — ``canonicalize_legs`` liefert für
    Connections OHNE jeglichen Track einen Fallback-Flug (Spiegel der Connection selbst, damit die
    Live-Ansicht auch ohne Track etwas anzuzeigen hat); dieser Fallback ist strukturell eindeutig
    erkennbar (``gps_arrival`` leer UND ``logoff_time`` gesetzt — ein echter Track hat bei leerem
    ``gps_arrival`` IMMER ein offenes ``logoff_time``, vgl. ``collapse_same_airport``) und zählt
    hier NICHT als Treffer, sonst würde jede trackfreie Connection sich selbst „matchen". Klassi-
    fikation:

    - 0 überlappende (echte) GPS-Flüge → ``missing`` (Track fehlt / Detektor-Miss).
    - ≥ 1 → ``match``; das ERSTE ist primär, jedes weitere ist ein ``extra`` Flug
      (Intra-Connection-Zwischenlandung an einem ANDEREN Platz ohne Refile — der eigentliche
      Mehrwert; eine reine Platzrunde erzeugt dank Collapse KEINEN ``extra``).
    - ``arr_divergence``: der letzte überlappende GPS-Flug hat ein nicht-leeres
      ``gps_arrival``/``arrival``, das (case-insensitiv) vom ``arrival`` der Connection abweicht
      (nur wenn ``arrival`` gesetzt).

    Aggregat über ALLE echten GPS-Flüge im Fenster (nicht nur die zugeordneten):
    ``incomplete_rate`` (Anteil ohne Landung, ``gps_arrival`` leer) und ``airborne_spawn_rate``
    (Anteil ``gps_departure IS NULL``).

    Gibt ein JSON-serialisierbares Dict zurück (Struktur unverändert ggü. der Roh-Leg-Sicht).
    """
    flights = canonicalize_flights(
        conn, cids=cids, callsign_prefix=callsign_prefix, start=start, end=end
    )
    fs_flights = [f for f in flights if f.get("source") == "friesenspy"]
    statsim_count = sum(1 for f in flights if f.get("source") == "statsim")

    # Collapsed GPS-Sicht im Fenster (Task 4). Fallback-Flüge (kein Track, Spiegel der
    # Connection) strukturell ausschließen: ein echter Track hat bei leerem gps_arrival
    # IMMER logoff_time=None (offener Leg-Tail), ein Fallback dagegen NIE (er wird nur für
    # geschlossene Connections gebaut) — s. Docstring oben.
    gps_flights_raw = canonicalize_legs(
        conn, cids=cids, start=start, end=end, callsign_prefix=callsign_prefix
    )
    gps_view = [
        gf for gf in gps_flights_raw
        if gf.get("source") == "friesenspy"
        and not (gf.get("gps_arrival") is None and gf.get("logoff_time") is not None)
    ]

    gps_by_cid: dict[int, list[dict]] = {}
    for gf in gps_view:
        gps_by_cid.setdefault(gf.get("cid"), []).append(gf)
    for cid_key in gps_by_cid:
        gps_by_cid[cid_key].sort(key=lambda x: x.get("logon_time") or "")

    total_legs = len(gps_view)
    incomplete = sum(1 for gf in gps_view if not gf.get("gps_arrival"))
    airborne_spawn = sum(1 for gf in gps_view if gf.get("gps_departure") is None)
    incomplete_rate = round(incomplete / total_legs, 4) if total_legs else 0.0
    airborne_spawn_rate = round(airborne_spawn / total_legs, 4) if total_legs else 0.0

    matches = 0
    missing = 0
    extra_total = 0
    arr_divergence = 0
    flight_reports: list[dict] = []

    for f in fs_flights:
        cid = f.get("cid")
        logon = f.get("logon_time")
        logoff = f.get("logoff_time")
        arr = (f.get("arrival") or "").strip()

        overlapping = []
        for gf in gps_by_cid.get(cid, []):
            t = gf.get("logon_time")
            if t is None or logon is None:
                continue
            if t < logon:
                continue
            if logoff is not None and t > logoff:
                continue
            overlapping.append(gf)

        n_legs = len(overlapping)
        if n_legs >= 1:
            matches += 1
        else:
            missing += 1
        extra_total += max(0, n_legs - 1)

        # arr_match / arr_divergence gegen den LETZTEN überlappenden GPS-Flug.
        arr_match: bool | None = None
        if n_legs >= 1 and arr:
            last = overlapping[-1]
            last_arr = (last.get("gps_arrival") or last.get("arrival") or "").strip()
            if last_arr:
                arr_match = last_arr.upper() == arr.upper()
                if not arr_match:
                    arr_divergence += 1

        flight_reports.append({
            "cid": cid,
            "callsign": f.get("callsign"),
            "logon_time": logon,
            "logoff_time": logoff,
            "dep": f.get("departure"),
            "arr": f.get("arrival"),
            "n_legs": n_legs,
            "arr_match": arr_match,
            "legs": [
                {
                    "dep_icao": gf.get("gps_departure"),
                    "arr_icao": gf.get("gps_arrival"),
                    "takeoff_ts": gf.get("logon_time"),
                    "landing_ts": gf.get("logoff_time"),
                    "complete": bool(gf.get("gps_arrival")),
                }
                for gf in overlapping
            ],
        })

    result = {
        "window": {"start": start, "end": end},
        "summary": {
            "flights": len(fs_flights),
            "statsim_flights": statsim_count,
            "gps_legs": total_legs,
            "matches": matches,
            "missing_gps_legs": missing,
            "extra_gps_legs": extra_total,
            "arr_divergence": arr_divergence,
            "incomplete_rate": incomplete_rate,
            "airborne_spawn_rate": airborne_spawn_rate,
        },
        "flights": flight_reports,
    }
    if statsim_sample > 0:
        result["statsim"] = _statsim_gps_interpretation(
            conn, cids=cids, start=start, end=end,
            callsign_prefix=callsign_prefix, limit=statsim_sample,
        )
    return result


def _statsim_gps_interpretation(
    conn: sqlite3.Connection,
    *,
    cids: list[int] | None,
    start: str | None,
    end: str | None,
    callsign_prefix: str,
    limit: int,
) -> dict:
    """GPS-Leg-Interpretation der jüngsten StatSim-Flüge im Fenster — on-demand, in-memory
    (NICHT gespeichert). ``detect_gps_legs`` + ``collapse_same_airport`` laufen über
    ``statsim_position_history`` (Task 6, #23: collapsed statt Roh-Legs — eine Platzrunde am
    selben Platz ist EIN Flug, keine ``zwischenlandung``).

    Klassifikation je Flug: ``match`` (1 kompletter collapsed Flug, Ziel == Flugplan),
    ``divergent`` (1 kompletter collapsed Flug, anderes Ziel), ``zwischenlandung`` (> 1
    collapsed Flug — echte Landung an einem ANDEREN Platz), ``incomplete`` (Flug ohne Landung)
    oder ``none`` (kein Flug / kein Track). Rückgabe enthält Stichprobengröße, Gesamtzahl
    passender StatSim-Flüge und die Einzel-Interpretationen.
    """
    from app.gps_legs import detect_gps_legs, collapse_same_airport
    from app import geo

    where = ["logon_time != ''", "logoff_time IS NOT NULL", "duration_min > 5", "callsign LIKE ?"]
    params: list = [f"{callsign_prefix}%"]
    if cids:
        where.append("cid IN (%s)" % ",".join("?" * len(cids)))
        params += list(cids)
    if start:
        where.append("logon_time >= ?")
        params.append(start)
    if end:
        where.append("logon_time <= ?")
        params.append(end)
    where_sql = " AND ".join(where)

    total = conn.execute(
        "SELECT COUNT(*) FROM statsim_cache WHERE " + where_sql, params
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT statsim_id, cid, callsign, departure, arrival FROM statsim_cache WHERE "
        + where_sql + " ORDER BY logon_time DESC LIMIT ?",
        params + [int(limit)],
    ).fetchall()

    counts = {"match": 0, "divergent": 0, "zwischenlandung": 0, "incomplete": 0, "none": 0}
    flights: list[dict] = []
    for r in rows:
        positions = get_statsim_positions(conn, r["statsim_id"])
        raw_legs = detect_gps_legs(
            positions,
            nearest_airport=geo.nearest_airport_icao_fast,
            airport_elev_ft=geo.airport_elevation_ft,
            radius_km=_BUMMEL_AIRPORT_RADIUS_KM,
        )
        legs = collapse_same_airport(raw_legs)
        plan_arr = (r["arrival"] or "").strip().upper()
        if not legs:
            cls = "none"
        elif len(legs) > 1:
            cls = "zwischenlandung"
        else:
            leg = legs[0]
            if not leg.get("complete") or not leg.get("arr_icao"):
                cls = "incomplete"
            else:
                la = (leg["arr_icao"] or "").strip().upper()
                cls = "match" if (plan_arr and la == plan_arr) else "divergent"
        counts[cls] += 1
        flights.append({
            "statsim_id": r["statsim_id"],
            "cid": r["cid"],
            "callsign": r["callsign"],
            "dep": r["departure"],
            "arr": r["arrival"],
            "n_legs": len(legs),
            "classification": cls,
            "legs": [
                {"dep_icao": l.get("dep_icao"), "arr_icao": l.get("arr_icao"),
                 "complete": bool(l.get("complete"))}
                for l in legs
            ],
        })

    return {"sampled": len(rows), "total": total, "summary": counts, "flights": flights}


# ---------------------------------------------------------------------------
# flight_cache — materialisierte canonicalize_legs()-Ergebnisse (GPS-only Phase 2, #23)
# ---------------------------------------------------------------------------
#
# Nur die GLOBALE Statistik (alle Piloten, großes Fenster) nutzt diesen Cache — dort wäre
# canonicalize_legs() live zu teuer. Bummel/Kutter/Piloten-Detail (kleine cid-Mengen) rufen
# canonicalize_legs() weiterhin direkt.

_FLIGHT_CACHE_COLUMNS = [
    "id", "cid", "callsign", "aircraft", "departure", "arrival", "logon_time", "logoff_time",
    "duration_min", "distance_nm", "block_min", "route", "remarks", "cruise_altitude",
    "cruise_tas", "flight_rules", "aircraft_icao", "alternate", "deptime", "enroute_time",
    "fuel_time", "source", "gps_departure", "gps_arrival", "plan_departure", "plan_arrival",
    "connection_closed",
]

# Inkrementelles Fenster: nur Flüge der letzten N Tage werden bei full=False neu berechnet;
# ältere, abgeschlossene Flüge bleiben im Cache unangetastet.
_FLIGHT_CACHE_INCREMENTAL_DAYS = 7

# Refresh-Schwelle (Sekunden): ist der Cache älter, löst get_cached_flights() einen
# inkrementellen Refresh aus.
_FLIGHT_CACHE_MAX_AGE_SEC = 600


def _write_flight_cache_rows(
    conn: sqlite3.Connection, flights: list[dict], computed_at: str
) -> None:
    """Flug-Dicts (Feld-Vertrag von :func:`canonicalize_legs`) nach ``flight_cache`` schreiben.

    ``INSERT OR REPLACE`` gegen ``UNIQUE(cid, logon_time)`` — ein erneuter Lauf über dieselben
    Flüge erzeugt keine Dubletten (Idempotenz)."""
    cols = _FLIGHT_CACHE_COLUMNS + ["computed_at"]
    sql = (
        f"INSERT OR REPLACE INTO flight_cache ({','.join(cols)}) VALUES "
        f"({','.join(':' + c for c in cols)})"
    )
    for f in flights:
        row = {c: f.get(c) for c in _FLIGHT_CACHE_COLUMNS}
        row["connection_closed"] = 1 if row.get("connection_closed") else 0
        row["computed_at"] = computed_at
        conn.execute(sql, row)


def rebuild_flight_cache(conn: sqlite3.Connection, *, full: bool = False) -> int:
    """Materialisiert :func:`canonicalize_legs`-Ergebnisse in ``flight_cache``.

    ``full=True`` ODER der Cache ist leer: kompletter Rebuild — ``flight_cache`` wird geleert
    und mit ALLEN Flügen aus ``canonicalize_legs(conn)`` (kein Fenster, Default-Präfix "FRS")
    neu befüllt.

    ``full=False``: inkrementell — nur Flüge mit ``logon_time >= now - _FLIGHT_CACHE_INCREMENTAL_DAYS
    Tage`` werden im Cache gelöscht und aus ``canonicalize_legs(conn, start=…)`` neu geschrieben;
    ältere, bereits abgeschlossene Flüge bleiben unangetastet.

    Gibt die Anzahl der in diesem Lauf geschriebenen Zeilen zurück.
    """
    is_empty = conn.execute("SELECT COUNT(*) FROM flight_cache").fetchone()[0] == 0
    computed_at = _now_utc()

    # Erst rechnen (canonicalize_legs, ~5,5 s bei großem Bestand), DANN DELETE+INSERT — die
    # Schreib-Transaktion (und damit der Write-Lock) soll nur die kurze DB-Schreibphase
    # umfassen, nicht die gesamte Berechnung (Deploy-Risiko "database is locked"). Semantisch
    # identisch zu "DELETE zuerst": derselbe canonicalize_legs-Snapshot landet im Cache.
    if full or is_empty:
        flights = canonicalize_legs(conn)
        conn.execute("DELETE FROM flight_cache")
    else:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=_FLIGHT_CACHE_INCREMENTAL_DAYS)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        flights = canonicalize_legs(conn, start=cutoff)
        conn.execute("DELETE FROM flight_cache WHERE logon_time >= ?", (cutoff,))

    _write_flight_cache_rows(conn, flights, computed_at)
    conn.commit()
    return len(flights)


def get_cached_flights(
    conn: sqlite3.Connection,
    *,
    start: str | None = None,
    end: str | None = None,
    callsign_prefix: str = "FRS",
) -> list[dict]:
    """Liest Flüge aus ``flight_cache`` (Feld-Vertrag identisch zu :func:`canonicalize_legs`).

    Refresh-Regel: ist der Cache leer, wird zuerst ein Voll-Rebuild ausgelöst; ist er nicht
    leer, aber der jüngste ``computed_at``-Wert älter als ``_FLIGHT_CACHE_MAX_AGE_SEC``, ein
    inkrementeller Refresh. Der Cache selbst wird IMMER mit dem Default-Präfix "FRS" materialisiert
    — ``callsign_prefix``/``start``/``end`` filtern hier nur die AUSGABE.
    """
    is_empty = conn.execute("SELECT COUNT(*) FROM flight_cache").fetchone()[0] == 0
    if is_empty:
        rebuild_flight_cache(conn, full=True)
    else:
        max_computed = conn.execute(
            "SELECT MAX(computed_at) FROM flight_cache"
        ).fetchone()[0]
        if max_computed is None:
            rebuild_flight_cache(conn, full=True)
        else:
            age_sec = (datetime.now(timezone.utc) - _parse_iso(max_computed)).total_seconds()
            if age_sec > _FLIGHT_CACHE_MAX_AGE_SEC:
                rebuild_flight_cache(conn, full=False)

    where = ["callsign LIKE ?"]
    params: list = [callsign_prefix + "%"]
    if start:
        where.append("logon_time >= ?")
        params.append(start)
    if end:
        where.append("logon_time <= ?")
        params.append(end)

    rows = conn.execute(
        f"SELECT {','.join(_FLIGHT_CACHE_COLUMNS)} FROM flight_cache WHERE "
        + " AND ".join(where)
        + " ORDER BY logon_time DESC",
        params,
    ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["connection_closed"] = bool(d["connection_closed"])
        result.append(d)
    return result


# Umkreis (km), in dem die erste/letzte GPS-Position einem Streckenflugplatz zugeordnet wird.
# Großzügig genug für Start/Landung (inkl. kurzem Endanflug bei Disconnect), aber klar unter
# dem typischen Abstand zwischen zwei Bummel-Flugplätzen — `_nearest_airport` nimmt ohnehin
# den nächstgelegenen, sodass eng beieinanderliegende Inselplätze korrekt getrennt werden.
_BUMMEL_AIRPORT_RADIUS_KM = 4.0

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
            conn, route_icaos, _BUMMEL_AIRPORT_RADIUS_KM,
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
                conn, route_icaos, _BUMMEL_AIRPORT_RADIUS_KM,
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


def record_push_delivery(
    conn: sqlite3.Connection,
    ok_endpoints: list[str],
    fail_endpoints: dict[str, str] | None = None,
) -> None:
    """Ergebnis des letzten Versands je Endpoint festhalten (Push-Diagnose).

    ``ok_endpoints`` → last_ok_at = jetzt. ``fail_endpoints`` → {endpoint: status} setzt
    last_fail_at = jetzt und last_status. Gebündelter Einzel-Write auf dem Fire-and-forget-Pfad;
    Fehler beim Schreiben werden vom Aufrufer geschluckt (Diagnose ist nie kritisch).
    """
    now = _now_utc()
    for ep in ok_endpoints:
        conn.execute(
            "UPDATE push_subscriptions SET last_ok_at = ? WHERE endpoint = ?", (now, ep)
        )
    for ep, status in (fail_endpoints or {}).items():
        conn.execute(
            "UPDATE push_subscriptions SET last_fail_at = ?, last_status = ? WHERE endpoint = ?",
            (now, str(status)[:40], ep),
        )


def get_push_overview(conn: sqlite3.Connection) -> list[dict]:
    """Alle Abos mit ihrer Auswahl + Zustellungs-Diagnose (für die Admin-Push-Übersicht)."""
    rows = conn.execute(
        "SELECT endpoint, owner_cid, pilot_filter, notify_prefiles, notify_ts, "
        "notify_events, created_at, last_ok_at, last_fail_at, last_status "
        "FROM push_subscriptions ORDER BY created_at"
    ).fetchall()
    return [dict(r) for r in rows]


def list_visibility_restrictions(conn: sqlite3.Connection) -> list[dict]:
    """Piloten, die sich (teilweise) unsichtbar geschaltet haben (mode <> 'everyone')."""
    rows = conn.execute(
        "SELECT cid, mode, allowlist, services, updated_at FROM pilot_visibility "
        "WHERE mode <> 'everyone' ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def _bummel_edge_label(edge: tuple[str, str]) -> str:
    """Anzeige einer ungerichteten Etappe: „A ↔ B" (edge ist bereits sortiert)."""
    return f"{edge[0]} ↔ {edge[1]}"


def _route_touch_edges(segment: list[str], route_set: set[str]) -> Counter:
    """Kanten-Multimenge EINER zusammenhängenden Leg-Kette: auf Streckenplätze projizieren,
    aufeinanderfolgende Duplikate entfernen, benachbarte Plätze als ungerichtete Kanten zählen.
    Off-Route-Plätze werden übersprungen (Etappe A–B gilt auch über Off-Route-Zwischenstopp)."""
    touch: list[str] = []
    for p in segment:
        if p in route_set and (not touch or touch[-1] != p):
            touch.append(p)
    return Counter(tuple(sorted((a, b))) for a, b in zip(touch, touch[1:]))


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
    Block-Zeiten der Tour-Legs, d. h. die Bodenzeit der Zwischenstopps zählt NICHT mit.

    Frühstarter: Flüge, die VOR ``start`` begonnen haben, aber im Eventfenster noch unterwegs sind
    (``logoff_time >= start``), werden mit voller Blockzeit erfasst (Vorlauf
    ``_BUMMEL_EARLY_START_LOOKBACK_H``). ``radius_km`` wird nur noch entgegengenommen
    (Abwärtskompatibilität der Signatur) — die Endpunkt-Erkennung liegt seit GPS-only Phase 2
    (#23) vollständig bei :func:`canonicalize_legs` (fester Radius ``_BUMMEL_AIRPORT_RADIUS_KM``
    im Leg-Detektor selbst), das Argument hat hier keine Wirkung mehr.

    GPS-only (#23): baut auf :func:`canonicalize_legs` auf — die Landung wird direkt am
    tatsächlichen GPS-Track erkannt (kein Warten auf Disconnect/Refile mehr nötig), Reconnect-
    Fragmente/Ghosts sind bereits auf Ebene der Positions-Detektion bereinigt. Unvollständige
    Touren werden NIE still verworfen, sondern separat mit ``visited``/``missing`` gelistet —
    sichtbares Kontrollnetz, falls ein geflogenes Leg wegen eines abweichenden Flugplans nicht
    matcht.

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
    # route_seq: Route saniert — strip/upper, leere raus, AUFEINANDERFOLGENDE Duplikate raus
    # (Reihenfolge + nicht-benachbarte Wiederholung bleiben, damit ein Rundkurs A,B,C,A erhalten
    # bleibt). Verhindert eine unerfüllbare Selbstkante (A2). route_set = distinkte Plätze, nur
    # für den Zugehörigkeitstest „Landepunkt liegt auf der Strecke".
    route_seq: list[str] = []
    for code in route_icaos:
        c = (code or "").strip().upper()
        if c and (not route_seq or route_seq[-1] != c):
            route_seq.append(c)
    route_set = set(route_seq)
    # Pflicht-Etappen = ungerichtete Kanten-Multimenge der Nachbarpaare. Der Rückweg eines
    # Rundkurses (letztes Paar) ist so eine eigene Pflicht-Etappe. Kante = sortiertes Tupel.
    required_edges: Counter = Counter(
        tuple(sorted((a, b))) for a, b in zip(route_seq, route_seq[1:])
    )

    # radius_km bleibt als Parameter erhalten (main.py._build_race_view reicht weiterhin
    # race["radius_km"] durch) — wirkt aber nicht mehr auf die Endpunkt-Zuordnung. Die GPS-
    # Erkennung von Start/Ziel liegt seit GPS-only Phase 2 (#23) vollständig bei
    # canonicalize_legs (fester Radius _BUMMEL_AIRPORT_RADIUS_KM im Leg-Detektor selbst).

    # Frühstarter: mit Vorlauf laden, damit Flüge, die VOR dtstart begonnen haben, aber im
    # Eventfenster noch unterwegs sind, erfasst werden. canonicalize_legs filtert nach
    # logon_time; danach wird hier nach echter Überlappung (logoff_time >= start) gefiltert.
    load_start = _shift_iso(start, hours=-_BUMMEL_EARLY_START_LOOKBACK_H)
    flights = canonicalize_legs(conn, start=load_start, end=end, cids=cids)
    flights = [f for f in flights if (f.get("logoff_time") or "") >= start]

    # Legs je Pilot sammeln (Endpunkte bereits GPS-korrigiert durch canonicalize_legs, sonst
    # Flugplan-Fallback). Legs außerhalb der Strecke werden NICHT mehr sofort verworfen — sie
    # können Zwischenstopps einer Tour sein.
    legs_by_cid: dict[int, list[dict]] = {}
    for f in flights:
        cid = f.get("cid")
        if cid is None:
            continue
        dep = (f.get("departure") or "").strip().upper()
        arr = (f.get("arrival") or "").strip().upper()
        block = f.get("block_min")
        minutes = int(block) if block else int(f.get("duration_min") or 0)
        # Block-Zeit aus block_min (canonicalize_legs hat sie bereits pro Leg aus der
        # richtigen Positionsquelle — position_history für FS, statsim_position_history für
        # StatSim — gerechnet, offene Legs korrekt gekappt). Minutengenau statt wie zuvor
        # sekundengenau (der alte cid-gebundene _block_seconds las NUR position_history und
        # war für StatSim/offene Legs falsch) — akzeptierter Genauigkeitsverlust.
        secs = minutes * 60
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
    # Streckenflugplatz (Legs zeitlich geordnet). Zwischenstopps dazwischen sind erlaubt; ihre
    # Bodenzeit fällt automatisch raus, da nur die Block-Zeit der Legs summiert wird.
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
        total = 0
        total_secs = 0
        for l in tour:
            total += l["minutes"]
            total_secs += l["seconds"]
        # achieved_edges: geflogene Etappen — Kanten NUR aus zusammenhängenden Leg-Ketten. Eine
        # Lücke (arr von Leg i ≠ dep von Leg i+1) oder ein leerer Endpunkt bricht die Kette, damit
        # keine Phantom-Kante über nie geflogene Strecken entsteht (A1). Off-Route-Zwischenstopps
        # bleiben Teil des Segments (werden bei der Projektion übersprungen → „Weg erlaubt").
        achieved_edges: Counter = Counter()
        segment: list[str] = []
        for l in tour:
            dep, arr = l["departure"], l["arrival"]
            if segment and segment[-1] == dep and dep:
                segment.append(arr)
            else:
                achieved_edges.update(_route_touch_edges(segment, route_set))
                segment = [dep, arr]
        achieved_edges.update(_route_touch_edges(segment, route_set))

        # komplett ⇔ jede Pflicht-Etappe (mit Multiplizität) gedeckt. Counter-Subtraktion lässt
        # nur die Fehlmengen (> 0) stehen; leer ⇒ alle Etappen geflogen.
        missing_ctr = required_edges - achieved_edges
        visited_edges = []
        for e, n in required_edges.items():
            visited_edges += [_bummel_edge_label(e)] * min(achieved_edges[e], n)
        missing_edges = []
        for e, n in missing_ctr.items():
            missing_edges += [_bummel_edge_label(e)] * n
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
            "visited": visited_edges,
            "missing": missing_edges,
        }
        (complete if not missing_ctr else incomplete).append(entry)

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
        "route": route_seq,
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
    # Fairness: NEUTRAL sortieren (Callsign, dann cid). `standings["complete"]` ist rang-sortiert
    # (Nähe zum Schnitt) — reichte man diese Ordnung durch, ließe sich die Platzierung aus der
    # Reihenfolge ablesen, obwohl Zeiten/Delta/Rang redigiert sind. Die Ordnung darf kein
    # Ranking-Signal tragen; enthüllt bleibt die Rang-Sortierung (anderer Zweig oben).
    participants.sort(key=lambda p: ((p["callsign"] or "").upper(), p["cid"]))
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


_STATSIM_UNCACHED_WHERE = (
    "logon_time != '' AND logoff_time IS NOT NULL AND duration_min > 5 "
    "AND callsign LIKE ? "
    "AND statsim_id NOT IN (SELECT DISTINCT statsim_id FROM statsim_position_history)"
)


def get_uncached_statsim_ids(
    conn: sqlite3.Connection, *, callsign_prefix: str = "FRS", limit: int = 50,
    oldest_first: bool = False,
) -> list[int]:
    """StatSim-Flug-IDs, deren GPS-Track noch NICHT lokal gecacht ist.

    Für den Track-Backfill (#23 Task 5b): dieselben Filter wie ``canonicalize_flights``
    (gültiger Zeitraum, Dauer > 5 min, FRS-Präfix). „Uncached" = keine Zeile in
    ``statsim_position_history``.

    ``oldest_first`` (v8.6.1, #61-Fund): Standard ist „jüngste zuerst" (``ORDER BY
    logon_time DESC``) — bei laufend neu importiertem StatSim-Bestand verhungert damit aber
    der alte Backlog auf ewig: solange fast immer ein JÜNGERER ungecachter Flug existiert,
    kommt ein Flug von vor Monaten nie an die Reihe (Fund: Flüge aus 01/2025 nach über einem
    Monat immer noch ohne Track). ``oldest_first=True`` kehrt die Sortierung um, damit der
    Aufrufer (``_fetch_statsim_tracks``) beide Enden bedienen kann.
    """
    order = "ASC" if oldest_first else "DESC"
    rows = conn.execute(
        "SELECT statsim_id FROM statsim_cache WHERE " + _STATSIM_UNCACHED_WHERE
        + f" ORDER BY logon_time {order} LIMIT ?",
        (f"{callsign_prefix}%", int(limit)),
    ).fetchall()
    return [r[0] for r in rows]


def count_uncached_statsim(
    conn: sqlite3.Connection, *, callsign_prefix: str = "FRS"
) -> int:
    """Anzahl StatSim-Flüge ohne gecachten Track (Rest-Zähler für den Backfill-Fortschritt)."""
    return conn.execute(
        "SELECT COUNT(*) FROM statsim_cache WHERE " + _STATSIM_UNCACHED_WHERE,
        (f"{callsign_prefix}%",),
    ).fetchone()[0]


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
    notify_events: bool = False,
    owner_cid: int | None = None,
) -> None:
    """Browser-Push-Subscription speichern oder aktualisieren.

    ``owner_cid`` (aus dem Forum-Login) wird beim Konflikt nur überschrieben, wenn er nicht NULL
    ist (``COALESCE``) — ein anonymer Re-Subscribe (ausgeloggt) löscht einen gesetzten Besitzer
    NICHT aus (Backfill-Robustheit); ein eingeloggter Re-Subscribe überschreibt (last-login-wins).

    Die Spalte ``ts_self_frs`` wird nicht mehr beschrieben (Selbst-Ausschluss läuft über
    ``pilot_filter``); sie bleibt in bestehenden DBs als NULL stehen.
    """
    conn.execute(
        """INSERT INTO push_subscriptions
               (endpoint, p256dh, auth, pilot_filter, notify_prefiles,
                notify_ts, notify_events, owner_cid, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(endpoint) DO UPDATE SET
               p256dh=excluded.p256dh,
               auth=excluded.auth,
               pilot_filter=excluded.pilot_filter,
               notify_prefiles=excluded.notify_prefiles,
               notify_ts=excluded.notify_ts,
               notify_events=excluded.notify_events,
               owner_cid=COALESCE(excluded.owner_cid, push_subscriptions.owner_cid),
               created_at=excluded.created_at""",
        (
            endpoint, p256dh, auth,
            json.dumps(pilot_filter) if pilot_filter is not None else None,
            1 if notify_prefiles else 0,
            1 if notify_ts else 0,
            1 if notify_events else 0,
            owner_cid,
            _now_utc(),
        ),
    )


def set_push_subscription_owner(conn: sqlite3.Connection, endpoint: str, owner_cid: int) -> None:
    """Owner-CID eines bestehenden Abos setzen (Backfill nach Login, last-login-wins)."""
    conn.execute("UPDATE push_subscriptions SET owner_cid = ? WHERE endpoint = ?",
                 (int(owner_cid), endpoint))


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


def delete_stale_calendar_events(conn: sqlite3.Connection, active_uids: list[str]) -> int:
    """Entfernt Kalender-Events im Sync-Fenster (365 Tage zurück, 90 Tage voraus — muss zum
    Fenster in ``calendar_sync.fetch_and_parse_ical`` passen), die im aktuellen Sync-Lauf nicht
    mehr geliefert wurden (z. B. im Google-Kalender gelöscht/storniert). ``upsert_calendar_events``
    kennt nur INSERT OR REPLACE — ohne diesen Sweep bleiben gelöschte Termine für immer sichtbar
    (#38, z. B. das "Wunschradio"-Event). Persistente Bummel-/Kutter-Events (``bummel_races``,
    ``transport_events``) sind bewusst nicht betroffen — die bleiben, einmal erkannt, unabhängig
    vom Kalenderstand bestehen."""
    if not active_uids:
        return 0
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    window_end = (now + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    placeholders = ",".join("?" * len(active_uids))
    cur = conn.execute(
        f"DELETE FROM calendar_events WHERE dtstart >= ? AND dtstart <= ? "
        f"AND uid NOT IN ({placeholders})",
        (window_start, window_end, *active_uids),
    )
    return cur.rowcount


def get_calendar_events(conn: sqlite3.Connection, days_back: int = 365) -> list[dict]:
    """FriesenEvents der letzten N Tage, neueste zuerst.

    #19: Termine, an denen ein Event-Objekt hängt (``calendar_uid``), bleiben draußen — in der
    Liste steht dann das Objekt selbst, mit den im Admin gepflegten Werten. Vorher zeigte die
    Oberfläche für einen Kalender-Bummel den Termin und damit die Kalenderstrecke, auch wenn
    im Admin längst eine korrigierte stand.
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT uid, summary, dtstart, dtend, location, route, is_bummel, is_transport "
        "FROM calendar_events "
        "WHERE dtstart >= ? AND dtstart <= ? "
        "AND uid NOT IN (SELECT calendar_uid FROM bummel_races WHERE calendar_uid IS NOT NULL) "
        "AND uid NOT IN (SELECT calendar_uid FROM transport_events WHERE calendar_uid IS NOT NULL) "
        "ORDER BY dtstart DESC",
        (cutoff, now_str),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Bummel-Rennen (persistent) — Kalender-synchronisiert oder manuell (Phase B)
# ---------------------------------------------------------------------------

# --- #19: Schutzmarken je Feld ---------------------------------------------
# Ein Kalendertermin darf ein Event-Objekt anlegen und aktuell halten. Sobald ein Mensch im
# Admin ein Feld ändert, gehört dieses Feld ihm: Der nächste Sync (alle 6 h) lässt es stehen.
# Bewusst je FELD und nicht je Objekt (Entscheidung 05.09.2026) — wer die Strecke korrigiert,
# will nicht gleichzeitig eine spätere Terminverschiebung im Kalender verpassen.
_MANUAL_TABLES = {"bummel_races", "transport_events"}


def manual_fields_of(row) -> set[str]:
    """Die von Hand gesetzten Feldnamen einer Objektzeile. Leer = nichts angefasst."""
    raw = (dict(row).get("manual_fields") or "") if row is not None else ""
    return {f for f in (part.strip() for part in raw.split(",")) if f}


def mark_manual_fields(conn: sqlite3.Connection, table: str, obj_id: int,
                       fields: set[str]) -> None:
    """Feldnamen als „von Hand gesetzt" vormerken (additiv, idempotent).

    ``table`` geht in den SQL-Text und kommt deshalb ausschließlich aus ``_MANUAL_TABLES``.
    """
    if table not in _MANUAL_TABLES or not fields:
        return
    row = conn.execute(
        f"SELECT manual_fields FROM {table} WHERE id = ?", (obj_id,)).fetchone()
    if row is None:
        return
    merged = sorted(manual_fields_of(row) | {str(f) for f in fields})
    conn.execute(f"UPDATE {table} SET manual_fields = ? WHERE id = ?",
                 (",".join(merged), obj_id))


def clear_manual_field(conn: sqlite3.Connection, table: str, obj_id: int, field: str) -> None:
    """Schutz für genau ein Feld aufheben — der Kalender darf es wieder setzen."""
    if table not in _MANUAL_TABLES:
        return
    row = conn.execute(
        f"SELECT manual_fields FROM {table} WHERE id = ?", (obj_id,)).fetchone()
    if row is None:
        return
    rest = sorted(manual_fields_of(row) - {field})
    conn.execute(f"UPDATE {table} SET manual_fields = ? WHERE id = ?",
                 (",".join(rest) or None, obj_id))


def claimed_calendar_uids(conn: sqlite3.Connection) -> set[str]:
    """Alle Kalender-UIDs, an denen ein Event-Objekt hängt (Bummel oder Kutter).

    #19 Regel 3: Diese Termine erscheinen nicht mehr separat in der Events-Liste und lösen
    keine generische Erinnerung aus — beides erledigt jetzt das Objekt.
    """
    rows = conn.execute(
        "SELECT calendar_uid FROM bummel_races WHERE calendar_uid IS NOT NULL "
        "UNION SELECT calendar_uid FROM transport_events WHERE calendar_uid IS NOT NULL"
    ).fetchall()
    return {r["calendar_uid"] for r in rows if r["calendar_uid"]}



def upsert_calendar_bummel_race(conn: sqlite3.Connection, ev: dict) -> None:
    """Ein erkanntes Bummel-Kalenderevent als persistentes Rennen anlegen/aktualisieren.

    Idempotent über ``calendar_uid``. ``dtend`` wird mit dem Mitternacht-Default aufgelöst.
    ``revealed_at`` bleibt beim Update unangetastet (latchend).

    #66 Task 7: Läuft bei JEDEM Kalender-Sync — ein eingefrorener ``progress_snapshot`` darf
    deshalb NICHT pauschal verworfen werden. Vor dem Upsert wird die vorhandene Zeile (falls es
    schon eine gibt) gelesen; ändert sich ``route``/``dtstart``/``dtend`` durch den Upsert
    TATSÄCHLICH, wird gezielt der Snapshot dieses Rennens gelöscht.
    """
    uid = ev.get("uid")
    before = conn.execute(
        "SELECT id, name, route, dtstart, dtend, manual_fields FROM bummel_races "
        "WHERE calendar_uid = ?",
        (uid,),
    ).fetchone()
    # #19 Regel 2: Felder, die im Admin von Hand gesetzt wurden, gehören dem Menschen — der
    # Sync trägt für sie den Bestandswert erneut ein statt den Kalenderstand.
    protected = manual_fields_of(before) if before else set()
    name = before["name"] if "name" in protected else (ev.get("summary") or "")
    route = before["route"] if "route" in protected else (ev.get("route") or "")
    dtstart = before["dtstart"] if "dtstart" in protected else (ev.get("dtstart") or "")
    # Der Mitternacht-Default rechnet vom EFFEKTIVEN Start — sonst wandert ein offenes Ende auf
    # den Kalendertag zurück, obwohl der Start von Hand auf einen anderen Tag gelegt wurde.
    dtend = (before["dtend"] if "dtend" in protected
             else _effective_dtend(dtstart, ev.get("dtend")))
    conn.execute(
        """INSERT INTO bummel_races
               (name, route, dtstart, dtend, radius_km, source, calendar_uid, revealed_at, created_at)
           VALUES (?, ?, ?, ?, ?, 'calendar', ?, NULL, ?)
           ON CONFLICT(calendar_uid) DO UPDATE SET
               name=excluded.name,
               route=excluded.route,
               dtstart=excluded.dtstart,
               dtend=excluded.dtend""",
        (name, route, dtstart, dtend, 10, uid, _now_utc()),
    )
    if before:
        after = conn.execute(
            "SELECT route, dtstart, dtend FROM bummel_races WHERE id = ?",
            (before["id"],),
        ).fetchone()
        if (
            after["route"] != before["route"]
            or after["dtstart"] != before["dtstart"]
            or after["dtend"] != before["dtend"]
        ):
            delete_progress_snapshot(conn, "bummel", before["id"])


def list_bummel_races(conn: sqlite3.Connection, *, since: str | None = None) -> list[dict]:
    """Alle Rennen, neueste zuerst (nach dtstart). ``since`` (optional, nur Anzeige-Retention):
    blendet Rennen aus, deren ``dtend`` davor liegt (NULL-Guard: offene Rennen bleiben sichtbar)."""
    where, params = [], []
    if since:
        where.append("(dtend IS NULL OR dtend >= ?)")
        params.append(since)
    sql = (
        "SELECT id, name, route, dtstart, dtend, radius_km, source, calendar_uid, "
        "revealed_at, created_at, push_enabled, started_at, reveal_suppressed, manual_fields, "
        "badge_name "
        "FROM bummel_races"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY dtstart DESC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_bummel_race(conn: sqlite3.Connection, race_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, name, route, dtstart, dtend, radius_km, source, calendar_uid, "
        "revealed_at, created_at, push_enabled, started_at, reveal_suppressed, manual_fields, "
        "badge_name "
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


def set_transport_push_enabled(conn: sqlite3.Connection, event_id: int, enabled: bool) -> None:
    """Push-Benachrichtigungen für ein Transport-Event aktivieren oder deaktivieren."""
    conn.execute(
        "UPDATE transport_events SET push_enabled = ? WHERE id = ?",
        (1 if enabled else 0, event_id),
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


# calendar_uid ist seit #19 im Admin setzbar: die Verknüpfung Termin↔Objekt wird
# ausgesprochen, nicht aus Datum und Stichwort erraten.
_UPDATABLE_RACE_FIELDS = {"name", "route", "dtstart", "dtend", "radius_km", "calendar_uid",
                          "badge_name"}


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

# Bei JEDER Rechen-Ergebnis-Änderung von compute_transport_progress / compute_bummel_standings /
# _build_race_view im selben Commit erhöhen → invalidiert alle Snapshots (progress_snapshot).
_PROGRESS_SNAPSHOT_VERSION = "11"  # "11": Zwischenlegs eines Milchmanns zeigen die GETRAGENE
#      Ladung (carried_at, Bordladung beim Abheben) statt „leer" — der Feed nutzt die Modell-
#      Wahrheit je Leg, nicht nur delivered_by. Reine Anzeige, Stapel/Bilanz unverändert.
#      "10": Am-Platz-Rückgabe (Ladeplatz == Abfallort, kein Trage-
#      Flug) ist eine STILLE Stapel-Buchung — keine Feed-Zeile, kein Flugzähler (kein Leg = kein
#      Flug). Klau/Versenken/geflogene Rückgabe bleiben sichtbar.
#      "9": Am-Platz-Rückgabe (Ladeplatz == Abfallort) = eigenes
#      „EDWY→EDWY"-Ereignis statt auf den leeren Anflug-Leg gemalt; participants[].contributed
#      (Ware wirklich bewegt) fürs Badge/die Bilanz.
#      "8": WURZEL-Fix — der laufende Flug holt seine Fracht aus der
#      Bordladung (`onboard`) DIREKT auf die echte GPS-Leg-Zeile (dep=GPS-Start, arr=Ziel,
#      reserved=Bordladung), statt aus `delivered_by` (vor der Landung leer). Die separate
#      Reservierungs-Zeile bleibt nur noch für „beladen am Boden, nicht abgehoben" (kein Leg).
#      "7": (Zwischenschritt) leere Leg-Zeile des laufenden Flugs unterdrückt + Reservierungs-Start
#      aus last_ground — durch "8" ersetzt (Bordladung auf der Leg-Zeile, keine Unterdrückung).
#      "6": participants[].online (momentane Präsenz vs. Dauer-
#      Sperrklinke `visible`) — der Live-Block zeigt ausgeloggte Leer-Piloten nicht mehr als „dabei".
#      "5": on_stack_kg je Frachtzeile (Bestand am Ladeplatz) +
#      Verlust-/Rueckgabe-Zeile traegt den Ort als dep. Bump erzwingt Neuberechnung eingefrorener
#      Snapshots, sonst fehlt beiden abgeschlossenen Events das neue Feld (Anzeige "noch 0").
#      "4": Stapel-Modell — Ladung ist ein Bestand mit einem Ort
                                  # (Entscheidung 9: kein Auftau-Schutz, Version hoch + neu rechnen)

# Reine Anzeige-Retention (öffentliche Listen-Endpoints): Events/Rennen älter als das werden
# ausgeblendet, nicht gelöscht. Nutzung erst in späteren Tasks (#66); hier nur die Konstante.
_DATA_RETENTION_DAYS = 365


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


# Backoff der Recherche-Wiederholung. Bewusst grob gestaffelt: ein überlasteter Anbieter ist
# meist in Minuten wieder da, ein dauerhaft fehlschlagendes Muster soll aber nicht stündlich
# Geld kosten (~4 ct je Recherche, docs/architecture.md).
_RETRY_STAFFEL_S = (300, 1800, 14400)      # 5 min, 30 min, 4 h
_RETRY_MAX_S = 86400                        # danach täglich
_NICHTS_GEFUNDEN_ERNEUT_S = 30 * 86400      # inhaltlich erledigt: nach 30 Tagen erneut


def next_retry_delay_s(attempts: int) -> int:
    """Abstand bis zum nächsten Versuch, nach ``attempts`` Fehlschlägen (in Sekunden)."""
    if attempts <= 0:
        return 0
    if attempts <= len(_RETRY_STAFFEL_S):
        return _RETRY_STAFFEL_S[attempts - 1]
    return _RETRY_MAX_S


def _parse_iso_utc(ts: str | None) -> datetime | None:
    """ISO-8601 mit 'Z' oder Offset zu einem aware datetime; None bei Unbrauchbarem."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_retry_due(state: str, attempts: int, checked_at: str | None, now: datetime) -> bool:
    """Ist ein erneuter Versuch fällig?

    ``ok`` nie. ``nichts_gefunden`` nach 30 Tagen (die Welt kann sich geändert haben, das
    Muster aber nicht stündlich). ``fehler`` nach der Backoff-Staffel — ein transienter
    Fehler ist KEIN Endzustand (AP32-Fall). Unbekannter Zustand oder unlesbares
    ``checked_at``: sofort fällig, im Zweifel lieber einmal zu viel versuchen.
    """
    if state == "ok":
        return False
    seit = _parse_iso_utc(checked_at)
    if seit is None:
        return True
    if state == "nichts_gefunden":
        wartezeit = _NICHTS_GEFUNDEN_ERNEUT_S
    elif state == "fehler":
        wartezeit = next_retry_delay_s(attempts)
    else:
        return True
    return (now - seit).total_seconds() >= wartezeit


def get_payload_research(conn: sqlite3.Connection, type_code: str) -> dict | None:
    """Versuchszustand eines Typcodes oder ``None``, wenn nie versucht wurde."""
    code = normalize_type_code(type_code)
    if not code:
        return None
    row = conn.execute(
        "SELECT state, attempts, checked_at, last_error FROM payload_research WHERE type_code = ?",
        (code,),
    ).fetchone()
    return dict(row) if row is not None else None


def mark_payload_research(
    conn: sqlite3.Connection,
    type_code: str,
    state: str,
    now: datetime,
    last_error: str | None = None,
) -> None:
    """Versuchszustand festschreiben. ``attempts`` zählt NUR Fehlschläge."""
    code = normalize_type_code(type_code)
    if not code:
        return
    ts = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if state == "fehler":
        conn.execute(
            """INSERT INTO payload_research (type_code, state, attempts, checked_at, last_error)
               VALUES (?, 'fehler', 1, ?, ?)
               ON CONFLICT(type_code) DO UPDATE SET
                   state='fehler',
                   attempts = payload_research.attempts + 1,
                   checked_at = excluded.checked_at,
                   last_error = excluded.last_error""",
            (code, ts, last_error),
        )
        return
    conn.execute(
        """INSERT INTO payload_research (type_code, state, attempts, checked_at, last_error)
           VALUES (?, ?, 0, ?, ?)
           ON CONFLICT(type_code) DO UPDATE SET
               state = excluded.state,
               attempts = 0,
               checked_at = excluded.checked_at,
               last_error = excluded.last_error""",
        (code, state, ts, last_error),
    )


# Maßgebliche Spalte für den Flugbestand (Rev.-2-Befund B1): `aircraft_icao` existiert erst
# seit 2026-06-09 und ist nur in 357 von 2256 Zeilen gefüllt — angezeigt und angeklickt wird
# `aircraft` (2232 Zeilen). COALESCE liefert GENAU EINEN Wert je Flug; die beiden Spalten
# dürfen nie per OR addiert werden (Doppelzählung). Bei 358 Zeilen sind beide gefüllt, in 357
# stimmen sie überein.
# SQL-Pendant zu normalize_type_code(): vor dem '/' abschneiden, trimmen, Uppercase.
# ZWEI trim() sind noetig, sie decken verschiedene Faelle ab:
#   - das aeussere trim() um COALESCE(...) den Randpadding-Fall (" AP32 ")
#   - das trim() um substr(...) das Leerzeichen unmittelbar VOR einem inneren '/'
#     ("AP32 /L-SDGY" -> ohne dieses trim bliebe "AP32 " uebrig).
# Python macht beides in einem Schritt (``code.split("/")[0].strip()``); weicht das SQL ab,
# joint die betroffene Zeile nie auf ihre aircraft_payloads/payload_research-Zeile und bleibt
# ewig Kandidat -- sie belegt dann bei jedem Nachlese-Lauf einen der Slots.
FLIGHT_TYPE_CODE_SQL = """
    upper(trim(substr(
        trim(COALESCE(NULLIF(aircraft_icao, ''), aircraft)), 1,
        CASE WHEN instr(trim(COALESCE(NULLIF(aircraft_icao, ''), aircraft)), '/') > 0
             THEN instr(trim(COALESCE(NULLIF(aircraft_icao, ''), aircraft)), '/') - 1
             ELSE length(trim(COALESCE(NULLIF(aircraft_icao, ''), aircraft))) END)))
"""


def payload_research_candidates(
    conn: sqlite3.Connection, now: datetime, limit: int
) -> list[str]:
    """Typcodes aus dem Flugbestand ohne Zuladungseintrag, deren Versuch fällig ist.

    Nach Flugzahl absteigend — was oft geflogen wird, zuerst. Die Fälligkeit wird in Python
    entschieden (``is_retry_due``), damit die Backoff-Regel an einer Stelle steht.
    """
    rows = conn.execute(
        f"""SELECT {FLIGHT_TYPE_CODE_SQL} AS code, COUNT(*) AS n,
                   r.state AS state, r.attempts AS attempts, r.checked_at AS checked_at
              FROM flight_cache f
              LEFT JOIN aircraft_payloads p ON p.type_code = {FLIGHT_TYPE_CODE_SQL}
              LEFT JOIN payload_research  r ON r.type_code = {FLIGHT_TYPE_CODE_SQL}
             WHERE COALESCE(NULLIF(aircraft_icao, ''), aircraft) IS NOT NULL
               AND COALESCE(NULLIF(aircraft_icao, ''), aircraft) != ''
               AND p.type_code IS NULL
             GROUP BY code
             ORDER BY n DESC, code ASC"""
    ).fetchall()
    faellig = [
        r["code"] for r in rows
        if r["code"] and is_retry_due(r["state"] or "neu", r["attempts"] or 0,
                                     r["checked_at"], now)
    ]
    return faellig[:limit]


# ---------------------------------------------------------------------------
# Muster-Infos (aircraft_types) — Anzeige = COALESCE(<feld>_override, <feld>)
# ---------------------------------------------------------------------------

_AT_OVERRIDE_FELDER = ("name", "extract", "wiki_title")


def _ts(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_aircraft_type(conn: sqlite3.Connection, code: str, now: datetime) -> None:
    conn.execute(
        "INSERT INTO aircraft_types (type_code, fetch_state, updated_at) "
        "VALUES (?, 'neu', ?) ON CONFLICT(type_code) DO NOTHING",
        (code, _ts(now)),
    )


def get_aircraft_type(conn: sqlite3.Connection, type_code: str) -> dict | None:
    """Zeile mit aufgelösten Anzeigewerten, oder ``None``.

    ``photo_kind``: ``'blob'`` (Upload gewinnt immer), ``'file'`` (Commons-Cache) oder ``None``
    (``photo_override='-'`` oder gar kein Bild).
    """
    code = normalize_type_code(type_code)
    if not code:
        return None
    row = conn.execute("SELECT * FROM aircraft_types WHERE type_code = ?", (code,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    out = {
        "type_code": d["type_code"],
        "alias_of": d["alias_of"],
        "wiki_lang": d["wiki_lang"],
        "photo_licence": d["photo_licence"],
        "photo_artist": d["photo_artist"],
        "photo_source_url": d["photo_source_url"],
        "photo_credit": d["photo_credit"],
        "fetch_state": d["fetch_state"],
        "attempts": d["attempts"],
        "checked_at": d["checked_at"],
        "updated_at": d["updated_at"],
    }
    for feld in _AT_OVERRIDE_FELDER:
        out[feld] = d[f"{feld}_override"] if d[f"{feld}_override"] else d[feld]
    if d["photo_override"] == "-":
        out["photo_kind"] = None
    elif d["photo_override"] == "blob" and d["photo_blob"] is not None:
        out["photo_kind"] = "blob"
    elif d["photo_file"]:
        out["photo_kind"] = "file"
    else:
        out["photo_kind"] = None
    out["photo_file"] = d["photo_file"]
    return out


def upsert_aircraft_type_import(
    conn: sqlite3.Connection, type_code: str, *, now: datetime, **felder
) -> None:
    """Import-Spalten schreiben. Kennt die Korrektur-Spalten NICHT — deshalb kann ein Import
    eine Korrektur strukturell nicht zertreten (nicht bloß per Konvention).

    Nur übergebene Felder werden geschrieben; ``None`` heißt „nicht anfassen".
    """
    erlaubt = {"name", "name_source", "wiki_lang", "wiki_title", "extract",
               "photo_file", "photo_licence", "photo_artist", "photo_source_url"}
    code = normalize_type_code(type_code)
    if not code:
        return
    _ensure_aircraft_type(conn, code, now)
    setze = {k: v for k, v in felder.items() if k in erlaubt and v is not None}
    if not setze:
        conn.execute("UPDATE aircraft_types SET updated_at=? WHERE type_code=?",
                     (_ts(now), code))
        return
    sets = ", ".join(f"{k} = ?" for k in setze)
    conn.execute(
        f"UPDATE aircraft_types SET {sets}, updated_at = ? WHERE type_code = ?",
        (*setze.values(), _ts(now), code),
    )


def set_aircraft_type_override(
    conn: sqlite3.Connection, type_code: str, *, now: datetime, **felder
) -> None:
    """Korrektur-Spalten schreiben. Ein **Leerstring** löscht die Korrektur (→ Importwert gilt).

    Erlaubt: ``name``, ``extract``, ``wiki_title`` (→ ``*_override``), ``photo_override``,
    ``photo_credit``, ``alias_of``.
    """
    code = normalize_type_code(type_code)
    if not code:
        return
    _ensure_aircraft_type(conn, code, now)
    setze: dict[str, object] = {}
    for feld in _AT_OVERRIDE_FELDER:
        if feld in felder:
            setze[f"{feld}_override"] = felder[feld] or None
    for feld in ("photo_override", "photo_credit", "alias_of"):
        if feld in felder:
            wert = felder[feld]
            if feld == "alias_of" and wert:
                wert = normalize_type_code(str(wert))
            setze[feld] = wert or None
    if not setze:
        return
    sets = ", ".join(f"{k} = ?" for k in setze)
    conn.execute(
        f"UPDATE aircraft_types SET {sets}, updated_at = ? WHERE type_code = ?",
        (*setze.values(), _ts(now), code),
    )


def mark_aircraft_type_state(
    conn: sqlite3.Connection, type_code: str, state: str, now: datetime,
    last_error: str | None = None,
) -> None:
    """Auflösungs-Zustand festschreiben. ``attempts`` zählt nur ``fehler``."""
    code = normalize_type_code(type_code)
    if not code:
        return
    _ensure_aircraft_type(conn, code, now)
    if state == "fehler":
        conn.execute(
            "UPDATE aircraft_types SET fetch_state='fehler', attempts = attempts + 1, "
            "checked_at = ?, last_error = ?, updated_at = ? WHERE type_code = ?",
            (_ts(now), last_error, _ts(now), code),
        )
        return
    conn.execute(
        "UPDATE aircraft_types SET fetch_state = ?, attempts = 0, checked_at = ?, "
        "last_error = ?, updated_at = ? WHERE type_code = ?",
        (state, _ts(now), last_error, _ts(now), code),
    )


def resolve_alias(conn: sqlite3.Connection, type_code: str) -> str:
    """Alias **einen** Schritt auflösen. Ketten werden nicht verfolgt (siehe validate_alias)."""
    code = normalize_type_code(type_code)
    if not code:
        return ""
    row = conn.execute(
        "SELECT alias_of FROM aircraft_types WHERE type_code = ?", (code,)
    ).fetchone()
    ziel = normalize_type_code(row["alias_of"]) if row and row["alias_of"] else ""
    return ziel or code


def validate_alias(conn: sqlite3.Connection, type_code: str, target: str) -> str | None:
    """Fehlermeldung, wenn ``type_code → target`` unzulässig wäre, sonst ``None``.

    Drei Ablehnungsgründe. Der dritte ist der aus Rev. 2 (W5.1): ohne ihn entsteht eine Kette
    in der anderen Anlegereihenfolge — erst ``P24 → PA24`` (erlaubt), dann ``PA24 → X``
    (scheinbar erlaubt), und die Ein-Schritt-Auflösung von ``P24`` landet auf einer Alias-Zeile
    ohne eigene Daten.
    """
    code, ziel = normalize_type_code(type_code), normalize_type_code(target)
    if not code or not ziel:
        return "Kürzel und Ziel müssen gesetzt sein."
    if code == ziel:
        return f"{code} kann nicht auf sich selbst zeigen."
    row = conn.execute(
        "SELECT alias_of FROM aircraft_types WHERE type_code = ?", (ziel,)
    ).fetchone()
    if row is not None and row["alias_of"]:
        return (f"{ziel} ist selbst ein Alias (→ {row['alias_of']}). "
                "Zeige direkt auf das echte Muster.")
    zeigt_auf_mich = conn.execute(
        "SELECT type_code FROM aircraft_types WHERE alias_of = ? LIMIT 1", (code,)
    ).fetchone()
    if zeigt_auf_mich is not None:
        return (f"{zeigt_auf_mich['type_code']} zeigt bereits auf {code} — "
                f"{code} kann deshalb kein Alias werden (das ergäbe eine Kette).")
    return None


def _alias_codes(conn: sqlite3.Connection, ziel: str) -> list[str]:
    rows = conn.execute(
        "SELECT type_code FROM aircraft_types WHERE alias_of = ? ORDER BY type_code", (ziel,)
    ).fetchall()
    return [r["type_code"] for r in rows]


def friesen_numbers(conn: sqlite3.Connection, type_code: str) -> dict:
    """Kernzahlen der Gruppe für ein Muster, inklusive der Flüge seiner Aliasse.

    ``alias_anteil`` ist eine **Liste**: es können mehrere Aliasse auf dasselbe Ziel zeigen
    (real: ``SA65``/``AS65`` und ``JU5``/``JU52``). Damit die angezeigte Zahl nachvollziehbar
    bleibt, weist das Panel sie einzeln aus.
    """
    ziel = resolve_alias(conn, type_code)
    leer = {"fluege": 0, "stunden": 0.0, "nm": 0.0, "piloten": 0,
            "von": None, "bis": None, "alias_anteil": []}
    if not ziel:
        return leer
    codes = [ziel, *_alias_codes(conn, ziel)]
    platz = ",".join("?" * len(codes))
    row = conn.execute(
        f"""SELECT COUNT(*) AS fluege,
                   COALESCE(SUM(duration_min), 0) / 60.0 AS stunden,
                   COALESCE(SUM(distance_nm), 0) AS nm,
                   COUNT(DISTINCT cid) AS piloten,
                   MIN(substr(logon_time, 1, 10)) AS von,
                   MAX(substr(logon_time, 1, 10)) AS bis
              FROM flight_cache
             WHERE {FLIGHT_TYPE_CODE_SQL} IN ({platz})""",
        codes,
    ).fetchone()
    if row is None or not row["fluege"]:
        return leer
    anteil = []
    for a in _alias_codes(conn, ziel):
        n = conn.execute(
            f"SELECT COUNT(*) AS n FROM flight_cache WHERE {FLIGHT_TYPE_CODE_SQL} = ?", (a,)
        ).fetchone()["n"]
        if n:
            anteil.append({"code": a, "n": n})
    return {
        "fluege": row["fluege"],
        "stunden": round(row["stunden"], 1),
        "nm": round(row["nm"], 0),
        "piloten": row["piloten"],
        "von": row["von"],
        "bis": row["bis"],
        "alias_anteil": anteil,
    }


def top_pilots(conn: sqlite3.Connection, type_code: str, limit: int = 3) -> list[dict]:
    """Wer das Muster am häufigsten geflogen hat (inkl. Alias-Flüge)."""
    ziel = resolve_alias(conn, type_code)
    if not ziel:
        return []
    codes = [ziel, *_alias_codes(conn, ziel)]
    platz = ",".join("?" * len(codes))
    rows = conn.execute(
        f"""SELECT f.cid AS cid, COUNT(*) AS n,
                   MAX(f.callsign) AS callsign,
                   (SELECT p.name FROM pilots p WHERE p.cid = f.cid) AS name
              FROM flight_cache f
             WHERE {FLIGHT_TYPE_CODE_SQL} IN ({platz})
             GROUP BY f.cid
             ORDER BY n DESC, f.cid ASC
             LIMIT ?""",
        (*codes, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def flight_type_codes(conn: sqlite3.Connection) -> set[str]:
    """Alle Typcodes aus dem Flugbestand — Grundlage der Klick-Eingrenzung (W3)."""
    rows = conn.execute(
        f"""SELECT DISTINCT {FLIGHT_TYPE_CODE_SQL} AS code FROM flight_cache
             WHERE COALESCE(NULLIF(aircraft_icao, ''), aircraft) IS NOT NULL
               AND COALESCE(NULLIF(aircraft_icao, ''), aircraft) != ''"""
    ).fetchall()
    return {r["code"] for r in rows if r["code"]}


def all_type_stats_for_days(conn: sqlite3.Connection, days: int) -> list[dict]:
    """Friesen-Zahlen jedes im gewaehlten Zeitraum geflogenen Musters, meistgeflogenes
    zuerst -- gemeinsame Grundlage der Top-Muster-KPI-Kachel (nimmt Zeile 0) UND der vollen
    Musterliste im Statistiken-Tab. Beide teilen sich denselben Zeitraum-Filter wie die
    uebrigen Kacheln der Reihe (get_stats(..., days=...)) -- ein Muster, das nur VOR dem
    gewaehlten Fenster geflogen wurde, taucht hier nicht auf.

    Aliase zaehlen auf ihr Ziel (wie friesen_numbers()), inklusive korrekter Piloten-
    Deduplizierung: ein Pilot, der im Fenster sowohl unter dem Alias- als auch dem
    Ziel-Kuerzel flog, zaehlt einmal -- deshalb Aggregation ueber Einzelzeilen (mit cid),
    nicht ueber ein GROUP BY COUNT(DISTINCT cid) je Rohcode (das wuerde bei einem
    Alias-Wechsel innerhalb des Fensters denselben Piloten zweimal zaehlen).

    flight_cache ist bereits auf CALLSIGN_PREFIX beschraenkt (rebuild_flight_cache() baut es
    ausschliesslich aus canonicalize_legs() mit dem konfigurierten Praefix) -- kein eigener
    Callsign-Filter noetig, wie auch bei friesen_numbers() schon nicht. In-progress-Fluege
    werden NICHT ausgeschlossen -- konsistent mit dem Rest der Muster-Zahlenfamilie
    (friesen_numbers, flight_type_codes), nicht mit get_stats() (das fuer Piloten-Kennzahlen
    einen strengeren Abschluss-Begriff verwendet).
    """
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        f"""SELECT {FLIGHT_TYPE_CODE_SQL} AS code, cid,
                   COALESCE(duration_min, 0) AS duration_min,
                   COALESCE(distance_nm, 0) AS distance_nm
              FROM flight_cache
             WHERE logon_time >= ?
               AND COALESCE(NULLIF(aircraft_icao, ''), aircraft) IS NOT NULL
               AND COALESCE(NULLIF(aircraft_icao, ''), aircraft) != ''""",
        (start,),
    ).fetchall()
    agg: dict[str, dict] = {}
    for r in rows:
        if not r["code"]:
            continue
        ziel = resolve_alias(conn, r["code"])
        if not ziel:
            continue
        a = agg.setdefault(ziel, {"fluege": 0, "min": 0, "nm": 0.0, "piloten": set()})
        a["fluege"] += 1
        a["min"] += r["duration_min"]
        a["nm"] += r["distance_nm"]
        a["piloten"].add(r["cid"])
    out = []
    for ziel, a in agg.items():
        typ = get_aircraft_type(conn, ziel) or {}
        out.append({
            "code": ziel,
            "name": typ.get("name"),
            "fluege": a["fluege"],
            "stunden": round(a["min"] / 60.0, 1),
            "nm": round(a["nm"], 0),
            "piloten": len(a["piloten"]),
        })
    out.sort(key=lambda r: (-r["fluege"], r["code"]))
    return out


def aircraft_type_candidates(
    conn: sqlite3.Connection, now: datetime, limit: int
) -> list[str]:
    """Typcodes aus dem Flugbestand, deren Auflösung fällig ist — häufigste zuerst.

    Ein Code ohne jeden Namen (kein Admin-Lemma, kein ``name_override``, kein
    ``aircraft_payloads.make_model``) UND ohne Endzustand der Zuladungs-Recherche
    (``payload_research.state`` weder ``'ok'`` noch ``'nichts_gefunden'``) wird
    übersprungen — für ihn würde ``_resolve_aircraft_type`` ohnehin nichts schreiben
    (siehe dortige Begründung). Ohne diesen Filter bleibt so ein Code für immer ein
    Kandidat (``checked_at IS NULL`` → immer fällig) und kann bei einem realistischen
    Flugbestand ab Rang ~8 alle dahinter liegenden, echt auflösbaren Muster dauerhaft
    aus der Nachlese verdrängen — konkret der Fall ohne ``ANTHROPIC_API_KEY`` (ein
    unterstützter Zustand) oder bei einer manuell gepflegten Zuladungszeile ohne
    ``make_model``.
    """
    rows = conn.execute(
        f"""SELECT {FLIGHT_TYPE_CODE_SQL} AS code, COUNT(*) AS n,
                   t.fetch_state AS state, t.attempts AS attempts, t.checked_at AS checked_at,
                   t.alias_of AS alias_of, t.wiki_title_override AS wiki_title_override,
                   t.name_override AS name_override, p.make_model AS make_model,
                   r.state AS payload_state
              FROM flight_cache f
              LEFT JOIN aircraft_types t ON t.type_code = {FLIGHT_TYPE_CODE_SQL}
              LEFT JOIN aircraft_payloads p ON p.type_code = {FLIGHT_TYPE_CODE_SQL}
              LEFT JOIN payload_research  r ON r.type_code = {FLIGHT_TYPE_CODE_SQL}
             WHERE COALESCE(NULLIF(aircraft_icao, ''), aircraft) IS NOT NULL
               AND COALESCE(NULLIF(aircraft_icao, ''), aircraft) != ''
             GROUP BY code
             ORDER BY n DESC, code ASC"""
    ).fetchall()
    faellig = []
    for r in rows:
        if not r["code"] or r["alias_of"]:
            continue
        if not is_retry_due(r["state"] or "neu", r["attempts"] or 0, r["checked_at"], now):
            continue
        hat_namen = r["wiki_title_override"] or r["name_override"] or r["make_model"]
        zuladung_offen = (r["payload_state"] or "") not in ("ok", "nichts_gefunden")
        if not hat_namen and zuladung_offen:
            continue
        faellig.append(r["code"])
    return faellig[:limit]


def _finite_or_none(v):
    """``inf``/``nan`` → ``None`` (JSON-sicher), sonst unverändert. Härtung gegen kaputte
    KI-Zuladungswerte: ``json.loads`` akzeptiert ``Infinity``/``NaN``, und ein einziger solcher
    Wert in ``aircraft_payloads`` sprengte sonst die ganze Zuladungs-Liste beim Response-Encoding
    (500, „Lade Zuladungen…" hängt) — v8.8.1."""
    return None if isinstance(v, float) and not math.isfinite(v) else v


def list_aircraft_payloads(conn: sqlite3.Connection) -> list[dict]:
    """Alle Zuladungs-Zeilen (für die Admin-Tabelle), alphabetisch nach Typcode.

    Nicht-endliche Werte (inf/nan) werden defensiv zu ``None`` — so kann kein einzelner kaputter
    Datensatz die JSON-Serialisierung der ganzen Liste zum Absturz bringen (v8.8.1)."""
    rows = conn.execute(
        "SELECT type_code, mtow_kg, empty_kg, fuel_kg, fuel_full_kg, crew_kg, payload_kg, source, "
        "make_model, updated_at FROM aircraft_payloads ORDER BY type_code"
    ).fetchall()
    return [{k: _finite_or_none(v) for k, v in dict(r).items()} for r in rows]


_CURATED_SPECS_PATH = Path(__file__).parent / "data" / "aircraft_specs.json"


def load_curated_specs() -> dict[str, dict]:
    """Kuratierte Flugzeug-Specs aus dem Repo laden.

    Rückgabe: ``{type_code: {"make_model", "mtow_kg", "empty_kg", "fuel_full_kg"}}``.
    Bei fehlender/kaputter Datei ``{}`` (Silent-Fail — Seeding ist Komfort, kein kritischer Pfad).
    """
    try:
        with open(_CURATED_SPECS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def seed_curated_payloads(conn: sqlite3.Connection) -> int:
    """Kuratierte Flugzeugtypen in ``aircraft_payloads`` einpflegen (idempotent).

    Fehlende Typen werden eingefügt; bestehende **automatisch recherchierte** Zeilen
    (``source`` ``'llm'``/``'default'``/``NULL``) werden mit den kuratierten Werten
    ÜBERSCHRIEBEN (Max-Tank nachtragen + Tankfüllung korrigieren). ``source='manual'``
    (Handpflege) und bereits ``'curated'`` bleiben unangetastet — dadurch idempotent und
    verlustfrei. Werte über ``llm._build_result`` (halber Tank, Crew 85).
    Rückgabe: Anzahl eingefügter/aktualisierter Zeilen.
    """
    from app.llm import _build_result  # lazy: reine Rechnung, vermeidet Modul-Kopplung
    written = 0
    for raw_code, spec in load_curated_specs().items():
        code = normalize_type_code(raw_code)
        if not code or not isinstance(spec, dict):
            continue
        try:
            mtow, empty, fuel_full = (
                float(spec["mtow_kg"]), float(spec["empty_kg"]), float(spec["fuel_full_kg"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) and v > 0 for v in (mtow, empty, fuel_full)):
            continue
        r = _build_result(str(spec.get("make_model") or code), mtow, empty, fuel_full)
        cur = conn.execute(
            """INSERT INTO aircraft_payloads
                   (type_code, mtow_kg, empty_kg, fuel_kg, fuel_full_kg, crew_kg, payload_kg, source, make_model, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'curated', ?, ?)
               ON CONFLICT(type_code) DO UPDATE SET
                   mtow_kg=excluded.mtow_kg, empty_kg=excluded.empty_kg, fuel_kg=excluded.fuel_kg,
                   fuel_full_kg=excluded.fuel_full_kg, crew_kg=excluded.crew_kg,
                   payload_kg=excluded.payload_kg, source='curated', make_model=excluded.make_model,
                   updated_at=excluded.updated_at
               WHERE aircraft_payloads.source IS NULL
                  OR aircraft_payloads.source IN ('llm', 'default')""",
            (code, r["mtow_kg"], r["empty_kg"], r["fuel_kg"], r["fuel_full_kg"], r["crew_kg"],
             r["payload_kg"], r["make_model"], _now_utc()),
        )
        written += cur.rowcount
    return written


def upsert_payload(
    conn: sqlite3.Connection,
    type_code: str,
    *,
    payload_kg: float | None = None,
    mtow_kg: float | None = None,
    empty_kg: float | None = None,
    fuel_kg: float | None = None,
    fuel_full_kg: float | None = None,
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
    # Nicht-endliche Werte (inf/nan) nie speichern — sonst sprengt ein einziger die Zuladungs-
    # Liste beim JSON-Encoding (v8.8.1, Härtung an der Eingangsseite).
    mtow_kg, empty_kg, fuel_kg, fuel_full_kg, crew_kg, payload_kg = (
        _finite_or_none(mtow_kg), _finite_or_none(empty_kg), _finite_or_none(fuel_kg),
        _finite_or_none(fuel_full_kg), _finite_or_none(crew_kg), _finite_or_none(payload_kg),
    )
    if crew_kg is None:
        crew_kg = _CREW_KG_DEFAULT
    if payload_kg is None:
        payload_kg = max(0.0, (mtow_kg or 0.0) - (empty_kg or 0.0) - (fuel_kg or 0.0) - (crew_kg or 0.0))
    conn.execute(
        """INSERT INTO aircraft_payloads
               (type_code, mtow_kg, empty_kg, fuel_kg, fuel_full_kg, crew_kg, payload_kg, source, make_model, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(type_code) DO UPDATE SET
               mtow_kg=excluded.mtow_kg, empty_kg=excluded.empty_kg, fuel_kg=excluded.fuel_kg,
               fuel_full_kg=excluded.fuel_full_kg, crew_kg=excluded.crew_kg, payload_kg=excluded.payload_kg,
               source=excluded.source, make_model=excluded.make_model, updated_at=excluded.updated_at""",
        (code, mtow_kg, empty_kg, fuel_kg, fuel_full_kg, crew_kg, payload_kg, source, make_model, _now_utc()),
    )


# --- Transport-Events (Kalender-synchronisiert oder manuell) ---------------

_TRANSPORT_EVENT_COLS = (
    "id, name, route, destination, dtstart, dtend, source, calendar_uid, push_enabled, "
    "started_at, goal_reached_at, summarized_at, summary_quip, radius_km, created_at, "
    "manual_fields, badge_name"
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
            "departure": line.get("departure"),  # #15 Sub-Projekt B: Startplatz-Bindung durchreichen
        })
    return out


def upsert_calendar_transport_event(conn: sqlite3.Connection, ev: dict) -> None:
    """Ein erkanntes FriesenKutter-Kalenderevent als persistentes Transportevent anlegen/updaten.

    Idempotent über ``calendar_uid``. ``dtend`` mit Mitternacht-Default. Enthält die Beschreibung
    eine Fracht-Zeile (Marker ``Fracht: 1000 Krabbenbrötchen, 500 Friesentee``, geparst in
    ``calendar_sync.parse_cargo_lines``), wird daraus **einmalig** das Manifest befüllt (Namen
    gegen den Katalog abgeglichen) — nur solange noch **kein** Manifest existiert, damit spätere
    Admin-Bearbeitungen bei erneutem Sync nicht überschrieben werden.

    #66 Task 7: Läuft bei JEDEM Kalender-Sync — ein eingefrorener ``progress_snapshot`` darf
    deshalb NICHT pauschal verworfen werden. Vor dem Upsert wird die vorhandene Zeile (falls es
    schon eine gibt) gelesen; ändert sich ``route``/``dtstart``/``dtend``/``destination`` durch
    den Upsert TATSÄCHLICH, wird gezielt der Snapshot dieses Events gelöscht. ``destination`` wird
    vom ``ON CONFLICT``-Zweig bewusst nicht überschrieben (Admin-Korrektur bleibt erhalten) — der
    Vergleich deckt trotzdem ab, falls sich das künftig ändert.
    """
    route = ev.get("route") or ""
    uid = ev.get("uid")
    before = conn.execute(
        "SELECT id, name, route, dtstart, dtend, destination, manual_fields "
        "FROM transport_events WHERE calendar_uid = ?",
        (uid,),
    ).fetchone()
    # #19 Regel 2 — wie in upsert_calendar_bummel_race: von Hand gesetzte Felder bleiben stehen.
    protected = manual_fields_of(before) if before else set()
    ev_name = before["name"] if "name" in protected else (ev.get("summary") or "")
    ev_route = before["route"] if "route" in protected else route
    ev_dtstart = before["dtstart"] if "dtstart" in protected else (ev.get("dtstart") or "")
    ev_dtend = (before["dtend"] if "dtend" in protected
                else _effective_dtend(ev_dtstart, ev.get("dtend")))
    conn.execute(
        """INSERT INTO transport_events
               (name, route, destination, dtstart, dtend, source, calendar_uid, created_at)
           VALUES (?, ?, ?, ?, ?, 'calendar', ?, ?)
           ON CONFLICT(calendar_uid) DO UPDATE SET
               name=excluded.name, route=excluded.route,
               dtstart=excluded.dtstart, dtend=excluded.dtend""",
        (
            ev_name,
            ev_route,
            _default_destination(route),   # Ziel-Default; im Admin korrigierbar (Update lässt es unangetastet)
            ev_dtstart,
            ev_dtend,
            uid,
            _now_utc(),
        ),
    )
    if before:
        after = conn.execute(
            "SELECT route, dtstart, dtend, destination FROM transport_events WHERE id = ?",
            (before["id"],),
        ).fetchone()
        if (
            after["route"] != before["route"]
            or after["dtstart"] != before["dtstart"]
            or after["dtend"] != before["dtend"]
            or after["destination"] != before["destination"]
        ):
            delete_progress_snapshot(conn, "kutter", before["id"])
    cargo_lines = ev.get("cargo") or []
    if cargo_lines:
        row = conn.execute(
            "SELECT id, destination FROM transport_events WHERE calendar_uid = ?", (ev.get("uid"),)
        ).fetchone()
        if row and not get_transport_cargo(conn, row[0]):
            resolved = _resolve_cargo_against_catalog(conn, cargo_lines)
            # Entscheidung 6 (Task 11): jede Zeile braucht GENAU EINEN Startplatz ≠ Ziel, der auf
            # der (distanz-gefilterten) Route liegt. Ein von `parse_route` verworfener Marker-ICAO
            # (Tippfehler/fern) oder das Ziel selbst macht die Zeile ortlos — sie wird VERWORFEN
            # (früher: auf „geteilt"/NULL degradiert; den geteilten Topf gibt es nicht mehr, und
            # set_transport_cargo würde eine ortlose Zeile jetzt mit ValueError ablehnen).
            route_places = {c.strip().upper() for c in (route or "").split(",") if c.strip()}
            dest_up = (row["destination"] or "").strip().upper()
            kept_lines = []
            for line in resolved:
                dep = (line.get("departure") or "").strip().upper()
                if dep and dep in route_places and dep != dest_up:
                    line["departure"] = dep
                    kept_lines.append(line)
            set_transport_cargo(conn, row[0], kept_lines, destination=row["destination"])


def list_transport_events(conn: sqlite3.Connection, *, since: str | None = None) -> list[dict]:
    """Alle Transport-Events (Kalender + manuell), neueste zuerst. ``since`` (optional, nur
    Anzeige-Retention): blendet Events aus, deren ``dtend`` davor liegt (NULL-Guard: Events
    ohne dtend bleiben sichtbar)."""
    where, params = [], []
    if since:
        where.append("(dtend IS NULL OR dtend >= ?)")
        params.append(since)
    sql = f"SELECT {_TRANSPORT_EVENT_COLS} FROM transport_events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY dtstart DESC"
    rows = conn.execute(sql, params).fetchall()
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
    route: str | None = None,
    dtstart: str,
    dtend: str | None,
    destination: str | None = None,
    cargo: list[dict] | None = None,
    radius_km: float | None = None,
) -> int:
    """Manuelles Transportevent anlegen (+ Fracht-Manifest). Gibt die neue id zurück.
    #84: ``route`` wird i. d. R. NICHT mehr übergeben, sondern aus den Startplätzen der Fracht-
    Zeilen + ``destination`` abgeleitet (``_derive_route``); wird ``route`` explizit gesetzt (Tests /
    Altpfade), bleibt sie erhalten. Ohne ``destination`` gilt weiter der letzte Strecken-Flugplatz
    als Default (Altpfad); der Admin-Endpoint macht ``destination`` zur Pflicht."""
    dest = normalize_type_code(destination) or _default_destination(route)
    if not route:
        route = _derive_route(cargo, dest)
    cur = conn.execute(
        "INSERT INTO transport_events "
        "(name, route, destination, dtstart, dtend, source, calendar_uid, radius_km, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'manual', NULL, ?, ?)",
        (name, route, dest, dtstart, _effective_dtend(dtstart, dtend), radius_km, _now_utc()),
    )
    event_id = int(cur.lastrowid)  # type: ignore[arg-type]
    if cargo:
        # Erstanlage: das ganze Manifest gilt als „vom Event-Start an vorhanden" (added_at = dtstart).
        set_transport_cargo(conn, event_id, cargo, destination=dest, default_added_at=dtstart)
    return event_id


# #84: `route` NICHT mehr direkt setzbar — sie wird aus dem Manifest abgeleitet (sonst könnte ein
# gecachtes altes admin.html die abgeleitete Route überschreiben).
# calendar_uid: siehe _UPDATABLE_RACE_FIELDS (#19).
_UPDATABLE_TRANSPORT_FIELDS = {"name", "destination", "dtstart", "dtend", "radius_km",
                               "calendar_uid", "badge_name"}


def update_transport_event(conn: sqlite3.Connection, event_id: int, **fields: object) -> None:
    """Aktualisiert {name, destination, dtstart, dtend}. dtend wird bei Zeitänderung neu aufgelöst.
    ``cargo`` (falls übergeben) ersetzt das gesamte Manifest. #84: die ``route`` wird danach IMMER
    frisch aus dem aktuellen Manifest + Ziel abgeleitet (auch bei reiner Name-/Ziel-Änderung)."""
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
    ev_now = get_transport_event(conn, event_id)
    dest = ev_now.get("destination") if ev_now else None
    if cargo is not None:
        # Bearbeiten mitten im Event: NEUE Frachtzeilen kamen JETZT dazu (bestehende behalten ihr
        # added_at) → sie laden nicht rückwirkend auf schon abgeflogene Piloten.
        set_transport_cargo(conn, event_id, cargo, destination=dest,  # type: ignore[arg-type]
                            default_added_at=_now_utc())
    # Route immer aus dem aktuellen Manifest + Ziel neu ableiten (#84); existing_route als
    # Sicherheitsnetz, falls noch eine geteilte (NULL) Zeile existiert (Kalender-Fracht:).
    if ev_now:
        cur_cargo = get_transport_cargo(conn, event_id)
        conn.execute(
            "UPDATE transport_events SET route = ? WHERE id = ?",
            (_derive_route(cur_cargo, dest, existing_route=ev_now.get("route")), event_id),
        )


def delete_transport_event(conn: sqlite3.Connection, event_id: int) -> None:
    """Event samt Fracht-Manifest löschen."""
    conn.execute("DELETE FROM transport_cargo WHERE event_id = ?", (event_id,))
    conn.execute("DELETE FROM transport_events WHERE id = ?", (event_id,))


def get_transport_cargo(conn: sqlite3.Connection, event_id: int) -> list[dict]:
    """Geordnetes Fracht-Manifest eines Events (inkl. Emoji + Co-Load-Kappung)."""
    rows = conn.execute(
        "SELECT id, position, name, target_kg, emoji, per_flight_max_kg, departure, added_at "
        "FROM transport_cargo WHERE event_id = ? ORDER BY position, id",
        (event_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _opt_float(v) -> float | None:
    try:
        return float(v) if v is not None and str(v) != "" else None
    except (TypeError, ValueError):
        return None


def _normalize_icao_list(raw, *, exclude: str | None = None) -> str | None:
    """Kommagetrennte ICAO-Liste normalisieren (#84): je Code trimmen + uppercasen, deduplizieren,
    STABIL sortieren, als CSV zurückgeben (oder ``None`` wenn leer). Akzeptiert String oder Liste.
    Bewusst NICHT ``normalize_type_code`` — das schneidet an ``/`` ab und ließe Innen-Leerzeichen
    stehen, würde eine Multi-Platz-Liste also still verstümmeln. ``exclude`` (z. B. das Ziel) wird
    entfernt (ein am Ziel startender Flug ist per Rückflug-Filter nie füllbar)."""
    if raw is None:
        return None
    # Trennung an Komma, Semikolon UND Leerzeichen — der Startort darf mit jedem Trenner getippt
    # werden (Nutzer-Wunsch: „space statt/oder komma"). Ohne `re` (nicht importiert): Trenner erst
    # auf Komma vereinheitlichen, dann splitten.
    parts = raw if isinstance(raw, (list, tuple, set)) else (
        str(raw).replace(";", ",").replace(" ", ",").replace("\t", ",").split(",")
    )
    ex = (exclude or "").strip().upper()
    out: list[str] = []
    for p in parts:
        code = str(p).strip().upper()
        if code and code != ex and code not in out:
            out.append(code)
    return ",".join(sorted(out)) if out else None


def _derive_route(cargo: list[dict] | None, destination: str | None,
                  existing_route: str | None = None) -> str:
    """Route (#84) aus den Startplätzen aller Fracht-Zeilen + Ziel ableiten → stabil sortierte CSV
    (stabile Sortierung: sonst churnte der #66-Freeze-Vergleich per Routen-String). Zeilen ohne
    ``departure`` (geteilt — nur Kalender-``Fracht:`` bzw. nicht-migrierte Alt-Events) tragen nichts
    bei; existiert eine solche Zeile, fließt als Sicherheitsnetz die ``existing_route`` mit ein,
    damit ein Edit an einem geteilten Event seine Route nicht verliert."""
    dest = (destination or "").strip().upper()
    places: list[str] = []
    has_shared = False
    for line in (cargo or []):
        dep = _normalize_icao_list(line.get("departure"), exclude=dest)
        if dep:
            for c in dep.split(","):
                if c not in places:
                    places.append(c)
        else:
            has_shared = True
    if has_shared and existing_route:
        for c in (existing_route or "").split(","):
            c = c.strip().upper()
            if c and c != dest and c not in places:
                places.append(c)
    if dest and dest not in places:
        places.append(dest)
    return ",".join(sorted(places))


def set_transport_cargo(
    conn: sqlite3.Connection,
    event_id: int,
    cargo: list[dict],
    *,
    destination: str | None = None,
    default_added_at: str | None = None,
) -> None:
    """Fracht-Manifest eines Events komplett ersetzen. Zeilen ohne Name/Menge werden ignoriert.
    Je Zeile optional ``emoji``, ``per_flight_max_kg`` (Co-Load-Kappung) und PFLICHT ``departure``:
    GENAU EIN Startplatz ≠ Ziel (Entscheidung 6 — eine Zeile = ein Stapel = ein Platz). ``departure``
    wird via :func:`_normalize_icao_list` normalisiert (``destination`` entfernt); fehlt der Platz
    oder sind es mehrere, wird ``ValueError`` geworfen (der geteilte Topf/CSV-Liste entfällt)."""
    # added_at (20.07.2026): jede Zeile trägt, seit wann sie im Manifest ist — Ware ist erst AB DANN
    # ladbar (derive_stacks). BESTEHENDE Zeilen (Match über name+departure) behalten ihr added_at über
    # das Ersetzen hinweg; NEUE Zeilen bekommen ``default_added_at`` (Erstanlage: Event-Start;
    # Mid-Event-Edit: jetzt). So schlägt ein Nachtrag NICHT rückwirkend auf schon abgeflogene Piloten.
    prev_added = {((r["name"] or "").strip().lower(), (r["departure"] or "")): r["added_at"]
                  for r in conn.execute(
                      "SELECT name, departure, added_at FROM transport_cargo WHERE event_id = ?",
                      (event_id,)).fetchall()}
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
        # Entscheidung 6 (Spec 2026-07-15): eine Zeile = ein Stapel = GENAU ein Platz. Verbindlich
        # serverseitig (der Admin-Endpoint ist nicht der einzige Aufrufer) — der "geteilte Topf"
        # (departure NULL) und die CSV-Liste entfallen.
        dep = _normalize_icao_list(line.get("departure"), exclude=destination)
        if not dep or "," in dep:
            raise ValueError(
                f"Frachtart „{name}“: Jede Frachtart liegt an genau einem Platz. "
                "Für dieselbe Ware an mehreren Plätzen leg mehrere Zeilen an."
            )
        added = prev_added.get((name.lower(), dep), default_added_at)
        conn.execute(
            "INSERT INTO transport_cargo "
            "(event_id, position, name, target_kg, emoji, per_flight_max_kg, departure, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, pos, name, target, (line.get("emoji") or None),
             _opt_float(line.get("per_flight_max_kg")), dep, added),
        )
        pos += 1


# --- Frachtart-Katalog (Stammdaten, wiederverwendbar über Events) ----------

_CARGO_SEED = [
    ("Krabbenbrötchen", "🦐", None), ("Friesentee", "🫖", None), ("Filmrollen", "🎞️", 100.0),
    ("Sonnenschirme", "⛱️", None), ("Strandkörbe", "🪑", None), ("Lebensmittel", "🧺", None),
    ("Baumaterial", "🧱", None), ("Material für Offshore-Anlagen", "⚙️", None),
    ("Heringe", "🐟", None),
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


def ensure_generic_heringe(conn: sqlite3.Connection) -> bool:
    """Idempotenter Nachtrag des generischen ``Heringe``-Katalogeintrags (🐟, keine Kappung).

    20.07.2026: Der Bestand kannte nur ``Heringe (für die Seehunde in EDWS)``. Fracht schlicht
    „Heringe" (z. B. nach Wooge) matchte den Katalog daher nicht → kein Emoji. Für neu geseedete
    DBs steht der Eintrag bereits in ``_CARGO_SEED``; diese Funktion rüstet ihn in **bestehenden**
    (bereits geseedeten) DBs nach. Gibt True zurück, wenn eingefügt wurde."""
    if conn.execute("SELECT 1 FROM cargo_catalog WHERE name = 'Heringe'").fetchone():
        return False
    pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM cargo_catalog").fetchone()[0]
    conn.execute(
        "INSERT INTO cargo_catalog (name, emoji, per_flight_max_kg, position) VALUES (?, ?, ?, ?)",
        ("Heringe", "🐟", None, pos),
    )
    return True


# Reale, wiederholt angeflogene Plätze, die in ``airportsdata`` fehlen (Live-Funde 2026-07-05,
# #50) — Segelfluggelände/UL-Felder ohne offizielle ICAO-Kennung bekommen einen Platzhalter-Code
# (ZZSALZ). elevation_ft=None wo unbekannt (macht Spawn-Guard/#49 permissiv, Rettung/#53 konservativ).
_CUSTOM_AIRPORTS_SEED: list[tuple[str, str, float, float, float | None]] = [
    ("EDHD", "Eichsfeld Airfield", 51.409, 10.150, 1200.0),
    ("LIVD", "Dobbiaco/Toblach", 46.727, 12.237, 3940.0),
    ("EDLQ", "Beelen", 51.931, 8.085, 200.0),
    ("EXHB", "UL-Flugfeld Gössenheim", 50.028, 9.771, 745.0),
    ("ZZSALZ", "Segelfluggelände Salzwedel/Klein Gartz", 52.828, 11.316, 112.0),
    ("CML5", "Region Thunder Bay, Ontario", 48.291, -89.543, 1118.0),
    # #55/#57/#58/#59 (v8.6.0): Live-Track-Analyse Session 2026-07-05.
    ("EDST", "Flugplatz Hahnweide", 48.6319, 9.4306, 1155.0),
    ("EDWD", "Lemwerder", 53.1432, 8.6234, 19.0),
    ("EDDX", "Bad Zwischenahn-Rostrup", 53.2103, 7.9888, 27.0),
    ("LOJB", "Hospital Bludenz", 47.1594, 9.8212, 1974.0),
    # EBUL (#56) bewusst NICHT im Seed: es überschreibt einen airportsdata-Eintrag mit
    # falschen Koordinaten (Override) -- das soll eine bewusste Admin-Handlung bleiben,
    # nicht automatisch bei jeder frischen Installation passieren.
]


def seed_custom_airports(conn: sqlite3.Connection) -> int:
    """Ergänzungs-Flugplätze erstbefüllen — NUR wenn die Tabelle leer ist (idempotent), damit
    spätere Admin-Änderungen/-Löschungen nie durch einen Neustart überschrieben werden."""
    if conn.execute("SELECT COUNT(*) FROM custom_airports").fetchone()[0]:
        return 0
    now = _now_utc()
    for icao, name, lat, lon, elev in _CUSTOM_AIRPORTS_SEED:
        conn.execute(
            "INSERT INTO custom_airports (icao, name, lat, lon, elevation_ft, reason, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            # Alle Seed-Plätze fehlen in airportsdata -- das ist ihre Existenzberechtigung (#50).
            (icao, name, lat, lon, elev, REASON_MISSING, now),
        )
    return len(_CUSTOM_AIRPORTS_SEED)


def list_custom_airports(conn: sqlite3.Connection) -> list[dict]:
    """Alle Ergänzungs-Flugplätze (für die Admin-Tabelle), alphabetisch nach ICAO/Code."""
    rows = conn.execute(
        "SELECT icao, name, lat, lon, elevation_ft, radius_km, reason, updated_at "
        "FROM custom_airports ORDER BY icao"
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_custom_airport(
    conn: sqlite3.Connection,
    icao: str,
    *,
    name: str | None,
    lat: float,
    lon: float,
    elevation_ft: float | None,
    radius_km: float | None = None,
    reason: str | None = None,
) -> str:
    """Ergänzungs-Flugplatz setzen/aktualisieren. Code wird normalisiert gespeichert (Uppercase,
    getrimmt) — beliebige Länge, kein echter ICAO-Code erforderlich (z. B. "ZZSALZ").

    ``radius_km`` (#62): NULL = Standard-Suchradius der aufrufenden Funktion (z. B.
    ``_BUMMEL_AIRPORT_RADIUS_KM``). Gesetzt überschreibt es NUR den Suchradius für diesen
    Code (z. B. Großflughäfen wie EHAM, deren Abhebepunkt weiter als der Standardradius vom
    Referenzpunkt entfernt liegen kann) -- unabhängig davon, ob lat/lon selbst korrekt/neu
    sind oder unverändert von airportsdata übernommen wurden.

    ``reason`` (#78): freier Grundtext, NULL erlaubt -- reine Dokumentation, nie Pflicht (der
    Eintrag selbst ist die Funktion, ein fehlender Grund darf nichts blockieren).
    """
    code = (icao or "").strip().upper()
    if not code:
        raise ValueError("icao darf nicht leer sein")
    conn.execute(
        """INSERT INTO custom_airports
               (icao, name, lat, lon, elevation_ft, radius_km, reason, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(icao) DO UPDATE SET
               name=excluded.name, lat=excluded.lat, lon=excluded.lon,
               elevation_ft=excluded.elevation_ft, radius_km=excluded.radius_km,
               reason=excluded.reason, updated_at=excluded.updated_at""",
        (code, name, lat, lon, elevation_ft, radius_km, (reason or None), _now_utc()),
    )
    return code


def delete_custom_airport(conn: sqlite3.Connection, icao: str) -> int:
    """Löscht einen Ergänzungs-Flugplatz. Gibt 1 zurück wenn eine Zeile gelöscht wurde, sonst 0."""
    code = (icao or "").strip().upper()
    cur = conn.execute("DELETE FROM custom_airports WHERE icao = ?", (code,))
    return cur.rowcount


# --- Flugplatz-Links (v.., AIP-VFR): rein informativ, keine Wirkung auf Flug-Erkennung/-Cache
# (deshalb kein background_tasks.add_task nötig -- anders als bei custom_airports).

_AIRPORT_LINKS_SEED: dict[str, str] = {
    "EDAB": "https://aip.dfs.de/BasicVFR/pages/P001A7.html",
    "EDAC": "https://aip.dfs.de/BasicVFR/pages/P00342.html",
    "EDAD": "https://aip.dfs.de/BasicVFR/pages/P0020B.html",
    "EDAE": "https://aip.dfs.de/BasicVFR/pages/P00235.html",
    "EDAG": "https://aip.dfs.de/BasicVFR/pages/P00290.html",
    "EDAH": "https://aip.dfs.de/BasicVFR/pages/P002BE.html",
    "EDAJ": "https://aip.dfs.de/BasicVFR/pages/P00276.html",
    "EDAK": "https://aip.dfs.de/BasicVFR/pages/P0028E.html",
    "EDAM": "https://aip.dfs.de/BasicVFR/pages/P0037A.html",
    "EDAN": "https://aip.dfs.de/BasicVFR/pages/P003B1.html",
    "EDAO": "https://aip.dfs.de/BasicVFR/pages/P003BF.html",
    "EDAP": "https://aip.dfs.de/BasicVFR/pages/P003A5.html",
    "EDAQ": "https://aip.dfs.de/BasicVFR/pages/P0029C.html",
    "EDAR": "https://aip.dfs.de/BasicVFR/pages/P0040A.html",
    "EDAS": "https://aip.dfs.de/BasicVFR/pages/P00F5C.html",
    "EDAT": "https://aip.dfs.de/BasicVFR/pages/P0039D.html",
    "EDAU": "https://aip.dfs.de/BasicVFR/pages/P00426.html",
    "EDAV": "https://aip.dfs.de/BasicVFR/pages/P0022A.html",
    "EDAW": "https://aip.dfs.de/BasicVFR/pages/P0042A.html",
    "EDAX": "https://aip.dfs.de/BasicVFR/pages/P00416.html",
    "EDAY": "https://aip.dfs.de/BasicVFR/pages/P00495.html",
    "EDAZ": "https://aip.dfs.de/BasicVFR/pages/P0369F.html",
    "EDBA": "https://aip.dfs.de/BasicVFR/pages/P0016F.html",
    "EDBC": "https://aip.dfs.de/BasicVFR/pages/P0035D.html",
    "EDBE": "https://aip.dfs.de/BasicVFR/pages/P001DE.html",
    "EDBF": "https://aip.dfs.de/BasicVFR/pages/P0043A.html",
    "EDBG": "https://aip.dfs.de/BasicVFR/pages/P001F3.html",
    "EDBH": "https://aip.dfs.de/BasicVFR/pages/P001A2.html",
    "EDBI": "https://aip.dfs.de/BasicVFR/pages/P00502.html",
    "EDBJ": "https://aip.dfs.de/BasicVFR/pages/P002ED.html",
    "EDBK": "https://aip.dfs.de/BasicVFR/pages/P00321.html",
    "EDBL": "https://aip.dfs.de/BasicVFR/pages/P00336.html",
    "EDBM": "https://aip.dfs.de/BasicVFR/pages/P0035A.html",
    "EDBN": "https://aip.dfs.de/BasicVFR/pages/P0039F.html",
    "EDBO": "https://aip.dfs.de/BasicVFR/pages/P003E0.html",
    "EDBP": "https://aip.dfs.de/BasicVFR/pages/P00406.html",
    "EDBQ": "https://aip.dfs.de/BasicVFR/pages/P001EF.html",
    "EDBR": "https://aip.dfs.de/BasicVFR/pages/P00432.html",
    "EDBS": "https://aip.dfs.de/BasicVFR/pages/P00478.html",
    "EDBT": "https://aip.dfs.de/BasicVFR/pages/P0015D.html",
    "EDBU": "https://aip.dfs.de/BasicVFR/pages/P00410.html",
    "EDBV": "https://aip.dfs.de/BasicVFR/pages/P00490.html",
    "EDBW": "https://aip.dfs.de/BasicVFR/pages/P004DE.html",
    "EDBX": "https://aip.dfs.de/BasicVFR/pages/P00284.html",
    "EDBY": "https://aip.dfs.de/BasicVFR/pages/P00452.html",
    "EDBZ": "https://aip.dfs.de/BasicVFR/pages/P00463.html",
    "EDCA": "https://aip.dfs.de/BasicVFR/pages/P00165.html",
    "EDCB": "https://aip.dfs.de/BasicVFR/pages/P0019C.html",
    "EDCE": "https://aip.dfs.de/BasicVFR/pages/P0022F.html",
    "EDCG": "https://aip.dfs.de/BasicVFR/pages/P00438.html",
    "EDCH": "https://aip.dfs.de/BasicVFR/pages/P00480.html",
    "EDCI": "https://aip.dfs.de/BasicVFR/pages/P0030D.html",
    "EDCJ": "https://aip.dfs.de/BasicVFR/pages/P001F9.html",
    "EDCL": "https://aip.dfs.de/BasicVFR/pages/P0030B.html",
    "EDCM": "https://aip.dfs.de/BasicVFR/pages/P002F3.html",
    "EDCO": "https://aip.dfs.de/BasicVFR/pages/P003D4.html",
    "EDCP": "https://aip.dfs.de/BasicVFR/pages/P003FA.html",
    "EDCQ": "https://aip.dfs.de/BasicVFR/pages/P00173.html",
    "EDCR": "https://aip.dfs.de/BasicVFR/pages/P00422.html",
    "EDCS": "https://aip.dfs.de/BasicVFR/pages/P00442.html",
    "EDCT": "https://aip.dfs.de/BasicVFR/pages/P004A4.html",
    "EDCU": "https://aip.dfs.de/BasicVFR/pages/P0029A.html",
    "EDCV": "https://aip.dfs.de/BasicVFR/pages/P003F6.html",
    "EDCW": "https://aip.dfs.de/BasicVFR/pages/P004F1.html",
    "EDCX": "https://aip.dfs.de/BasicVFR/pages/P00412.html",
    "EDCY": "https://aip.dfs.de/BasicVFR/pages/P0047E.html",
    "EDDB": "https://aip.dfs.de/BasicVFR/pages/P001B3.html",
    "EDDC": "https://aip.dfs.de/BasicVFR/pages/P00222.html",
    "EDDE": "https://aip.dfs.de/BasicVFR/pages/P00240.html",
    "EDDF": "https://aip.dfs.de/BasicVFR/pages/P0025C.html",
    "EDDG": "https://aip.dfs.de/BasicVFR/pages/P00394.html",
    "EDDH": "https://aip.dfs.de/BasicVFR/pages/P0029E.html",
    "EDDK": "https://aip.dfs.de/BasicVFR/pages/P00311.html",
    "EDDL": "https://aip.dfs.de/BasicVFR/pages/P00225.html",
    "EDDM": "https://aip.dfs.de/BasicVFR/pages/P0038D.html",
    "EDDN": "https://aip.dfs.de/BasicVFR/pages/P003CD.html",
    "EDDP": "https://aip.dfs.de/BasicVFR/pages/P00344.html",
    "EDDR": "https://aip.dfs.de/BasicVFR/pages/P00E84.html",
    "EDDS": "https://aip.dfs.de/BasicVFR/pages/P00497.html",
    "EDDV": "https://aip.dfs.de/BasicVFR/pages/P002AC.html",
    "EDDW": "https://aip.dfs.de/BasicVFR/pages/P001E4.html",
    "EDEB": "https://aip.dfs.de/BasicVFR/pages/P00190.html",
    "EDEG": "https://aip.dfs.de/BasicVFR/pages/P00286.html",
    "EDEH": "https://aip.dfs.de/BasicVFR/pages/P002C1.html",
    "EDEL": "https://aip.dfs.de/BasicVFR/pages/P00330.html",
    "EDEM": "https://aip.dfs.de/BasicVFR/pages/P00387.html",
    "EDEN": "https://aip.dfs.de/BasicVFR/pages/P0018C.html",
    "EDEP": "https://aip.dfs.de/BasicVFR/pages/P002BC.html",
    "EDEQ": "https://aip.dfs.de/BasicVFR/pages/P0038B.html",
    "EDER": "https://aip.dfs.de/BasicVFR/pages/P004D0.html",
    "EDEW": "https://aip.dfs.de/BasicVFR/pages/P004CA.html",
    "EDFA": "https://aip.dfs.de/BasicVFR/pages/P00169.html",
    "EDFB": "https://aip.dfs.de/BasicVFR/pages/P0041A.html",
    "EDFC": "https://aip.dfs.de/BasicVFR/pages/P00171.html",
    "EDFD": "https://aip.dfs.de/BasicVFR/pages/P00194.html",
    "EDFE": "https://aip.dfs.de/BasicVFR/pages/P0024D.html",
    "EDFG": "https://aip.dfs.de/BasicVFR/pages/P00274.html",
    "EDFH": "https://aip.dfs.de/BasicVFR/pages/P00257.html",
    "EDFI": "https://aip.dfs.de/BasicVFR/pages/P002CF.html",
    "EDFJ": "https://aip.dfs.de/BasicVFR/pages/P00327.html",
    "EDFK": "https://aip.dfs.de/BasicVFR/pages/P0018E.html",
    "EDFL": "https://aip.dfs.de/BasicVFR/pages/P0027E.html",
    "EDFM": "https://aip.dfs.de/BasicVFR/pages/P00363.html",
    "EDFN": "https://aip.dfs.de/BasicVFR/pages/P00369.html",
    "EDFO": "https://aip.dfs.de/BasicVFR/pages/P0037F.html",
    "EDFP": "https://aip.dfs.de/BasicVFR/pages/P003D6.html",
    "EDFQ": "https://aip.dfs.de/BasicVFR/pages/P0015A.html",
    "EDFR": "https://aip.dfs.de/BasicVFR/pages/P00430.html",
    "EDFS": "https://aip.dfs.de/BasicVFR/pages/P00467.html",
    "EDFT": "https://aip.dfs.de/BasicVFR/pages/P0033C.html",
    "EDFU": "https://aip.dfs.de/BasicVFR/pages/P0035F.html",
    "EDFV": "https://aip.dfs.de/BasicVFR/pages/P004F5.html",
    "EDFW": "https://aip.dfs.de/BasicVFR/pages/P004F7.html",
    "EDFX": "https://aip.dfs.de/BasicVFR/pages/P002D1.html",
    "EDFY": "https://aip.dfs.de/BasicVFR/pages/P00239.html",
    "EDFZ": "https://aip.dfs.de/BasicVFR/pages/P00361.html",
    "EDGA": "https://aip.dfs.de/BasicVFR/pages/P00156.html",
    "EDGB": "https://aip.dfs.de/BasicVFR/pages/P001E2.html",
    "EDGE": "https://aip.dfs.de/BasicVFR/pages/P00233.html",
    "EDGF": "https://aip.dfs.de/BasicVFR/pages/P0026A.html",
    "EDGH": "https://aip.dfs.de/BasicVFR/pages/P002C7.html",
    "EDGI": "https://aip.dfs.de/BasicVFR/pages/P002E7.html",
    "EDGK": "https://aip.dfs.de/BasicVFR/pages/P00319.html",
    "EDGL": "https://aip.dfs.de/BasicVFR/pages/P0060B.html",
    "EDGM": "https://aip.dfs.de/BasicVFR/pages/P00385.html",
    "EDGO": "https://aip.dfs.de/BasicVFR/pages/P0064E.html",
    "EDGP": "https://aip.dfs.de/BasicVFR/pages/P003E8.html",
    "EDGQ": "https://aip.dfs.de/BasicVFR/pages/P0044A.html",
    "EDGR": "https://aip.dfs.de/BasicVFR/pages/P00280.html",
    "EDGS": "https://aip.dfs.de/BasicVFR/pages/P00471.html",
    "EDGT": "https://aip.dfs.de/BasicVFR/pages/P001DC.html",
    "EDGU": "https://aip.dfs.de/BasicVFR/pages/P004BA.html",
    "EDGW": "https://aip.dfs.de/BasicVFR/pages/P004F3.html",
    "EDGX": "https://aip.dfs.de/BasicVFR/pages/P004C8.html",
    "EDGY": "https://aip.dfs.de/BasicVFR/pages/P011A1.html",
    "EDGZ": "https://aip.dfs.de/BasicVFR/pages/P004D6.html",
    "EDHB": "https://aip.dfs.de/BasicVFR/pages/P00292.html",
    "EDHC": "https://aip.dfs.de/BasicVFR/pages/P00354.html",
    "EDHD": "https://aip.dfs.de/BasicVFR/pages/P002B8.html",
    "EDHE": "https://aip.dfs.de/BasicVFR/pages/P004B8.html",
    "EDHF": "https://aip.dfs.de/BasicVFR/pages/P002EB.html",
    "EDHG": "https://aip.dfs.de/BasicVFR/pages/P00356.html",
    "EDHI": "https://aip.dfs.de/BasicVFR/pages/P002A6.html",
    "EDHK": "https://aip.dfs.de/BasicVFR/pages/P00304.html",
    "EDHL": "https://aip.dfs.de/BasicVFR/pages/P00352.html",
    "EDHM": "https://aip.dfs.de/BasicVFR/pages/P002B1.html",
    "EDHN": "https://aip.dfs.de/BasicVFR/pages/P003AD.html",
    "EDHO": "https://aip.dfs.de/BasicVFR/pages/P00154.html",
    "EDHS": "https://aip.dfs.de/BasicVFR/pages/P00482.html",
    "EDHU": "https://aip.dfs.de/BasicVFR/pages/P00338.html",
    "EDHW": "https://aip.dfs.de/BasicVFR/pages/P004C6.html",
    "EDHY": "https://aip.dfs.de/BasicVFR/pages/P04792.html",
    "EDJA": "https://aip.dfs.de/BasicVFR/pages/P00372.html",
    "EDJG": "https://aip.dfs.de/BasicVFR/pages/P00F4B.html",
    "EDKA": "https://aip.dfs.de/BasicVFR/pages/P0014E.html",
    "EDKB": "https://aip.dfs.de/BasicVFR/pages/P001D0.html",
    "EDKD": "https://aip.dfs.de/BasicVFR/pages/P00161.html",
    "EDKF": "https://aip.dfs.de/BasicVFR/pages/P001B1.html",
    "EDKH": "https://aip.dfs.de/BasicVFR/pages/P002DD.html",
    "EDKI": "https://aip.dfs.de/BasicVFR/pages/P001BA.html",
    "EDKL": "https://aip.dfs.de/BasicVFR/pages/P0034A.html",
    "EDKM": "https://aip.dfs.de/BasicVFR/pages/P0037C.html",
    "EDKN": "https://aip.dfs.de/BasicVFR/pages/P004EF.html",
    "EDKO": "https://aip.dfs.de/BasicVFR/pages/P001ED.html",
    "EDKP": "https://aip.dfs.de/BasicVFR/pages/P0040C.html",
    "EDKR": "https://aip.dfs.de/BasicVFR/pages/P0044E.html",
    "EDKU": "https://aip.dfs.de/BasicVFR/pages/P00175.html",
    "EDKV": "https://aip.dfs.de/BasicVFR/pages/P00205.html",
    "EDKW": "https://aip.dfs.de/BasicVFR/pages/P004DC.html",
    "EDKZ": "https://aip.dfs.de/BasicVFR/pages/P0036E.html",
    "EDLA": "https://aip.dfs.de/BasicVFR/pages/P0016D.html",
    "EDLB": "https://aip.dfs.de/BasicVFR/pages/P001D6.html",
    "EDLC": "https://aip.dfs.de/BasicVFR/pages/P002F5.html",
    "EDLD": "https://aip.dfs.de/BasicVFR/pages/P00217.html",
    "EDLE": "https://aip.dfs.de/BasicVFR/pages/P00243.html",
    "EDLF": "https://aip.dfs.de/BasicVFR/pages/P0028A.html",
    "EDLG": "https://aip.dfs.de/BasicVFR/pages/P00282.html",
    "EDLH": "https://aip.dfs.de/BasicVFR/pages/P002AA.html",
    "EDLI": "https://aip.dfs.de/BasicVFR/pages/P001BE.html",
    "EDLJ": "https://aip.dfs.de/BasicVFR/pages/P0020D.html",
    "EDLK": "https://aip.dfs.de/BasicVFR/pages/P0031B.html",
    "EDLM": "https://aip.dfs.de/BasicVFR/pages/P0036B.html",
    "EDLN": "https://aip.dfs.de/BasicVFR/pages/P00383.html",
    "EDLO": "https://aip.dfs.de/BasicVFR/pages/P003E2.html",
    "EDLP": "https://aip.dfs.de/BasicVFR/pages/P003F4.html",
    "EDLR": "https://aip.dfs.de/BasicVFR/pages/P003F2.html",
    "EDLS": "https://aip.dfs.de/BasicVFR/pages/P00484.html",
    "EDLT": "https://aip.dfs.de/BasicVFR/pages/P00397.html",
    "EDLV": "https://aip.dfs.de/BasicVFR/pages/P003B3.html",
    "EDLW": "https://aip.dfs.de/BasicVFR/pages/P00220.html",
    "EDLX": "https://aip.dfs.de/BasicVFR/pages/P004E2.html",
    "EDLY": "https://aip.dfs.de/BasicVFR/pages/P001D8.html",
    "EDLZ": "https://aip.dfs.de/BasicVFR/pages/P00476.html",
    "EDMA": "https://aip.dfs.de/BasicVFR/pages/P00179.html",
    "EDMB": "https://aip.dfs.de/BasicVFR/pages/P001BC.html",
    "EDMC": "https://aip.dfs.de/BasicVFR/pages/P001C6.html",
    "EDMD": "https://aip.dfs.de/BasicVFR/pages/P00203.html",
    "EDME": "https://aip.dfs.de/BasicVFR/pages/P0022C.html",
    "EDMF": "https://aip.dfs.de/BasicVFR/pages/P0026E.html",
    "EDMG": "https://aip.dfs.de/BasicVFR/pages/P00298.html",
    "EDMH": "https://aip.dfs.de/BasicVFR/pages/P00296.html",
    "EDMI": "https://aip.dfs.de/BasicVFR/pages/P002E5.html",
    "EDMJ": "https://aip.dfs.de/BasicVFR/pages/P002EF.html",
    "EDMK": "https://aip.dfs.de/BasicVFR/pages/P00302.html",
    "EDML": "https://aip.dfs.de/BasicVFR/pages/P0032E.html",
    "EDMN": "https://aip.dfs.de/BasicVFR/pages/P00381.html",
    "EDMO": "https://aip.dfs.de/BasicVFR/pages/P003D8.html",
    "EDMP": "https://aip.dfs.de/BasicVFR/pages/P004C0.html",
    "EDMQ": "https://aip.dfs.de/BasicVFR/pages/P0021C.html",
    "EDMR": "https://aip.dfs.de/BasicVFR/pages/P0065A.html",
    "EDMS": "https://aip.dfs.de/BasicVFR/pages/P00492.html",
    "EDMT": "https://aip.dfs.de/BasicVFR/pages/P004A2.html",
    "EDMU": "https://aip.dfs.de/BasicVFR/pages/P00294.html",
    "EDMV": "https://aip.dfs.de/BasicVFR/pages/P004C2.html",
    "EDMW": "https://aip.dfs.de/BasicVFR/pages/P00209.html",
    "EDMY": "https://aip.dfs.de/BasicVFR/pages/P00389.html",
    "EDMZ": "https://aip.dfs.de/BasicVFR/pages/P05F64.html",
    "EDNA": "https://aip.dfs.de/BasicVFR/pages/P00163.html",
    "EDNB": "https://aip.dfs.de/BasicVFR/pages/P0016B.html",
    "EDNC": "https://aip.dfs.de/BasicVFR/pages/P001AD.html",
    "EDND": "https://aip.dfs.de/BasicVFR/pages/P00215.html",
    "EDNE": "https://aip.dfs.de/BasicVFR/pages/P0023E.html",
    "EDNF": "https://aip.dfs.de/BasicVFR/pages/P00F65.html",
    "EDNG": "https://aip.dfs.de/BasicVFR/pages/P0027C.html",
    "EDNH": "https://aip.dfs.de/BasicVFR/pages/P0019A.html",
    "EDNI": "https://aip.dfs.de/BasicVFR/pages/P001AF.html",
    "EDNJ": "https://aip.dfs.de/BasicVFR/pages/P003A1.html",
    "EDNK": "https://aip.dfs.de/BasicVFR/pages/P00307.html",
    "EDNL": "https://aip.dfs.de/BasicVFR/pages/P00348.html",
    "EDNO": "https://aip.dfs.de/BasicVFR/pages/P003C9.html",
    "EDNP": "https://aip.dfs.de/BasicVFR/pages/P00402.html",
    "EDNQ": "https://aip.dfs.de/BasicVFR/pages/P001D4.html",
    "EDNR": "https://aip.dfs.de/BasicVFR/pages/P00418.html",
    "EDNS": "https://aip.dfs.de/BasicVFR/pages/P0045F.html",
    "EDNT": "https://aip.dfs.de/BasicVFR/pages/P004B0.html",
    "EDNU": "https://aip.dfs.de/BasicVFR/pages/P004AA.html",
    "EDNV": "https://aip.dfs.de/BasicVFR/pages/P004C4.html",
    "EDNW": "https://aip.dfs.de/BasicVFR/pages/P004D8.html",
    "EDNX": "https://aip.dfs.de/BasicVFR/pages/P003DC.html",
    "EDNY": "https://aip.dfs.de/BasicVFR/pages/P00263.html",
    "EDNZ": "https://aip.dfs.de/BasicVFR/pages/P004FB.html",
    "EDOA": "https://aip.dfs.de/BasicVFR/pages/P00177.html",
    "EDOB": "https://aip.dfs.de/BasicVFR/pages/P00180.html",
    "EDOC": "https://aip.dfs.de/BasicVFR/pages/P00272.html",
    "EDOD": "https://aip.dfs.de/BasicVFR/pages/P0041C.html",
    "EDOE": "https://aip.dfs.de/BasicVFR/pages/P001CC.html",
    "EDOF": "https://aip.dfs.de/BasicVFR/pages/P00188.html",
    "EDOH": "https://aip.dfs.de/BasicVFR/pages/P00334.html",
    "EDOI": "https://aip.dfs.de/BasicVFR/pages/P001C0.html",
    "EDOJ": "https://aip.dfs.de/BasicVFR/pages/P00358.html",
    "EDOK": "https://aip.dfs.de/BasicVFR/pages/P00436.html",
    "EDOL": "https://aip.dfs.de/BasicVFR/pages/P003EC.html",
    "EDOM": "https://aip.dfs.de/BasicVFR/pages/P00309.html",
    "EDON": "https://aip.dfs.de/BasicVFR/pages/P003A3.html",
    "EDOQ": "https://aip.dfs.de/BasicVFR/pages/P003EA.html",
    "EDOR": "https://aip.dfs.de/BasicVFR/pages/P0048C.html",
    "EDOS": "https://aip.dfs.de/BasicVFR/pages/P00400.html",
    "EDOT": "https://aip.dfs.de/BasicVFR/pages/P00E87.html",
    "EDOU": "https://aip.dfs.de/BasicVFR/pages/P004D4.html",
    "EDOV": "https://aip.dfs.de/BasicVFR/pages/P00488.html",
    "EDOW": "https://aip.dfs.de/BasicVFR/pages/P004CE.html",
    "EDOX": "https://aip.dfs.de/BasicVFR/pages/P00420.html",
    "EDOY": "https://aip.dfs.de/BasicVFR/pages/P0052B.html",
    "EDOZ": "https://aip.dfs.de/BasicVFR/pages/P00456.html",
    "EDPA": "https://aip.dfs.de/BasicVFR/pages/P00150.html",
    "EDPB": "https://aip.dfs.de/BasicVFR/pages/P00182.html",
    "EDPC": "https://aip.dfs.de/BasicVFR/pages/P00FC6.html",
    "EDPD": "https://aip.dfs.de/BasicVFR/pages/P00213.html",
    "EDPE": "https://aip.dfs.de/BasicVFR/pages/P00231.html",
    "EDPF": "https://aip.dfs.de/BasicVFR/pages/P00461.html",
    "EDPG": "https://aip.dfs.de/BasicVFR/pages/P0028C.html",
    "EDPH": "https://aip.dfs.de/BasicVFR/pages/P0045A.html",
    "EDPI": "https://aip.dfs.de/BasicVFR/pages/P00F58.html",
    "EDPJ": "https://aip.dfs.de/BasicVFR/pages/P0032C.html",
    "EDPK": "https://aip.dfs.de/BasicVFR/pages/P00454.html",
    "EDPM": "https://aip.dfs.de/BasicVFR/pages/P0021E.html",
    "EDPO": "https://aip.dfs.de/BasicVFR/pages/P003AB.html",
    "EDPQ": "https://aip.dfs.de/BasicVFR/pages/P00450.html",
    "EDPR": "https://aip.dfs.de/BasicVFR/pages/P00571.html",
    "EDPS": "https://aip.dfs.de/BasicVFR/pages/P0047A.html",
    "EDPT": "https://aip.dfs.de/BasicVFR/pages/P00278.html",
    "EDPU": "https://aip.dfs.de/BasicVFR/pages/P001A5.html",
    "EDPW": "https://aip.dfs.de/BasicVFR/pages/P004A8.html",
    "EDPY": "https://aip.dfs.de/BasicVFR/pages/P00237.html",
    "EDQA": "https://aip.dfs.de/BasicVFR/pages/P00FBA.html",
    "EDQB": "https://aip.dfs.de/BasicVFR/pages/P03C3F.html",
    "EDQC": "https://aip.dfs.de/BasicVFR/pages/P001FB.html",
    "EDQD": "https://aip.dfs.de/BasicVFR/pages/P001AA.html",
    "EDQE": "https://aip.dfs.de/BasicVFR/pages/P001F5.html",
    "EDQF": "https://aip.dfs.de/BasicVFR/pages/P00167.html",
    "EDQG": "https://aip.dfs.de/BasicVFR/pages/P0027A.html",
    "EDQH": "https://aip.dfs.de/BasicVFR/pages/P002C5.html",
    "EDQI": "https://aip.dfs.de/BasicVFR/pages/P0033A.html",
    "EDQK": "https://aip.dfs.de/BasicVFR/pages/P0031F.html",
    "EDQL": "https://aip.dfs.de/BasicVFR/pages/P0034C.html",
    "EDQM": "https://aip.dfs.de/BasicVFR/pages/P002D9.html",
    "EDQN": "https://aip.dfs.de/BasicVFR/pages/P003AF.html",
    "EDQO": "https://aip.dfs.de/BasicVFR/pages/P003F0.html",
    "EDQP": "https://aip.dfs.de/BasicVFR/pages/P0042C.html",
    "EDQR": "https://aip.dfs.de/BasicVFR/pages/P00228.html",
    "EDQS": "https://aip.dfs.de/BasicVFR/pages/P0049E.html",
    "EDQT": "https://aip.dfs.de/BasicVFR/pages/P002B4.html",
    "EDQW": "https://aip.dfs.de/BasicVFR/pages/P004D2.html",
    "EDQX": "https://aip.dfs.de/BasicVFR/pages/P002C9.html",
    "EDQZ": "https://aip.dfs.de/BasicVFR/pages/P003FC.html",
    "EDRA": "https://aip.dfs.de/BasicVFR/pages/P00192.html",
    "EDRB": "https://aip.dfs.de/BasicVFR/pages/P001C4.html",
    "EDRC": "https://aip.dfs.de/BasicVFR/pages/P04DFC.html",
    "EDRD": "https://aip.dfs.de/BasicVFR/pages/P003A9.html",
    "EDRE": "https://aip.dfs.de/BasicVFR/pages/P00EAE.html",
    "EDRF": "https://aip.dfs.de/BasicVFR/pages/P00184.html",
    "EDRG": "https://aip.dfs.de/BasicVFR/pages/P002E3.html",
    "EDRH": "https://aip.dfs.de/BasicVFR/pages/P002DB.html",
    "EDRI": "https://aip.dfs.de/BasicVFR/pages/P0034E.html",
    "EDRJ": "https://aip.dfs.de/BasicVFR/pages/P00440.html",
    "EDRK": "https://aip.dfs.de/BasicVFR/pages/P0030F.html",
    "EDRL": "https://aip.dfs.de/BasicVFR/pages/P00325.html",
    "EDRM": "https://aip.dfs.de/BasicVFR/pages/P004AE.html",
    "EDRN": "https://aip.dfs.de/BasicVFR/pages/P0039B.html",
    "EDRO": "https://aip.dfs.de/BasicVFR/pages/P00465.html",
    "EDRP": "https://aip.dfs.de/BasicVFR/pages/P00408.html",
    "EDRQ": "https://aip.dfs.de/BasicVFR/pages/P04847.html",
    "EDRS": "https://aip.dfs.de/BasicVFR/pages/P00196.html",
    "EDRT": "https://aip.dfs.de/BasicVFR/pages/P004B2.html",
    "EDRV": "https://aip.dfs.de/BasicVFR/pages/P004E0.html",
    "EDRW": "https://aip.dfs.de/BasicVFR/pages/P00211.html",
    "EDRY": "https://aip.dfs.de/BasicVFR/pages/P0047C.html",
    "EDRZ": "https://aip.dfs.de/BasicVFR/pages/P004FF.html",
    "EDSA": "https://aip.dfs.de/BasicVFR/pages/P00158.html",
    "EDSB": "https://aip.dfs.de/BasicVFR/pages/P002F9.html",
    "EDSD": "https://aip.dfs.de/BasicVFR/pages/P0627E.html",
    "EDSE": "https://aip.dfs.de/BasicVFR/pages/P00F49.html",
    "EDSG": "https://aip.dfs.de/BasicVFR/pages/P00288.html",
    "EDSH": "https://aip.dfs.de/BasicVFR/pages/P0017E.html",
    "EDSI": "https://aip.dfs.de/BasicVFR/pages/P001C2.html",
    "EDSK": "https://aip.dfs.de/BasicVFR/pages/P00300.html",
    "EDSL": "https://aip.dfs.de/BasicVFR/pages/P001CA.html",
    "EDSM": "https://aip.dfs.de/BasicVFR/pages/P06062.html",
    "EDSN": "https://aip.dfs.de/BasicVFR/pages/P003A7.html",
    "EDSO": "https://aip.dfs.de/BasicVFR/pages/P00FD5.html",
    "EDSR": "https://aip.dfs.de/BasicVFR/pages/P00414.html",
    "EDST": "https://aip.dfs.de/BasicVFR/pages/P00EC4.html",
    "EDSV": "https://aip.dfs.de/BasicVFR/pages/P00FC8.html",
    "EDSW": "https://aip.dfs.de/BasicVFR/pages/P0015F.html",
    "EDSZ": "https://aip.dfs.de/BasicVFR/pages/P00434.html",
    "EDTA": "https://aip.dfs.de/BasicVFR/pages/P065DA.html",
    "EDTB": "https://aip.dfs.de/BasicVFR/pages/P00186.html",
    "EDTC": "https://aip.dfs.de/BasicVFR/pages/P001F1.html",
    "EDTD": "https://aip.dfs.de/BasicVFR/pages/P00219.html",
    "EDTE": "https://aip.dfs.de/BasicVFR/pages/P01118.html",
    "EDTF": "https://aip.dfs.de/BasicVFR/pages/P00261.html",
    "EDTG": "https://aip.dfs.de/BasicVFR/pages/P001EB.html",
    "EDTH": "https://aip.dfs.de/BasicVFR/pages/P002CB.html",
    "EDTK": "https://aip.dfs.de/BasicVFR/pages/P00EE0.html",
    "EDTL": "https://aip.dfs.de/BasicVFR/pages/P00329.html",
    "EDTM": "https://aip.dfs.de/BasicVFR/pages/P00375.html",
    "EDTN": "https://aip.dfs.de/BasicVFR/pages/P00399.html",
    "EDTO": "https://aip.dfs.de/BasicVFR/pages/P003E4.html",
    "EDTP": "https://aip.dfs.de/BasicVFR/pages/P00404.html",
    "EDTQ": "https://aip.dfs.de/BasicVFR/pages/P003F8.html",
    "EDTR": "https://aip.dfs.de/BasicVFR/pages/P002C3.html",
    "EDTS": "https://aip.dfs.de/BasicVFR/pages/P00469.html",
    "EDTU": "https://aip.dfs.de/BasicVFR/pages/P00448.html",
    "EDTW": "https://aip.dfs.de/BasicVFR/pages/P004ED.html",
    "EDTX": "https://aip.dfs.de/BasicVFR/pages/P064AD.html",
    "EDTY": "https://aip.dfs.de/BasicVFR/pages/P0045C.html",
    "EDTZ": "https://aip.dfs.de/BasicVFR/pages/P00317.html",
    "EDUA": "https://aip.dfs.de/BasicVFR/pages/P00486.html",
    "EDUF": "https://aip.dfs.de/BasicVFR/pages/P00247.html",
    "EDUO": "https://aip.dfs.de/BasicVFR/pages/P003DA.html",
    "EDUP": "https://aip.dfs.de/BasicVFR/pages/P05E15.html",
    "EDUW": "https://aip.dfs.de/BasicVFR/pages/P004B4.html",
    "EDUY": "https://aip.dfs.de/BasicVFR/pages/P004DA.html",
    "EDUZ": "https://aip.dfs.de/BasicVFR/pages/P004FD.html",
    "EDVA": "https://aip.dfs.de/BasicVFR/pages/P0018A.html",
    "EDVC": "https://aip.dfs.de/BasicVFR/pages/P001F7.html",
    "EDVE": "https://aip.dfs.de/BasicVFR/pages/P001E0.html",
    "EDVF": "https://aip.dfs.de/BasicVFR/pages/P001C8.html",
    "EDVG": "https://aip.dfs.de/BasicVFR/pages/P00378.html",
    "EDVH": "https://aip.dfs.de/BasicVFR/pages/P002D3.html",
    "EDVI": "https://aip.dfs.de/BasicVFR/pages/P002D7.html",
    "EDVJ": "https://aip.dfs.de/BasicVFR/pages/P00446.html",
    "EDVK": "https://aip.dfs.de/BasicVFR/pages/P002FE.html",
    "EDVL": "https://aip.dfs.de/BasicVFR/pages/P002D5.html",
    "EDVM": "https://aip.dfs.de/BasicVFR/pages/P002CD.html",
    "EDVN": "https://aip.dfs.de/BasicVFR/pages/P003CB.html",
    "EDVP": "https://aip.dfs.de/BasicVFR/pages/P0113E.html",
    "EDVQ": "https://aip.dfs.de/BasicVFR/pages/P00F35.html",
    "EDVR": "https://aip.dfs.de/BasicVFR/pages/P00428.html",
    "EDVT": "https://aip.dfs.de/BasicVFR/pages/P00EC6.html",
    "EDVU": "https://aip.dfs.de/BasicVFR/pages/P004B6.html",
    "EDVW": "https://aip.dfs.de/BasicVFR/pages/P0497B.html",
    "EDVX": "https://aip.dfs.de/BasicVFR/pages/P01050.html",
    "EDVY": "https://aip.dfs.de/BasicVFR/pages/P0040E.html",
    "EDVZ": "https://aip.dfs.de/BasicVFR/pages/P05EE4.html",
    "EDWC": "https://aip.dfs.de/BasicVFR/pages/P00207.html",
    "EDWE": "https://aip.dfs.de/BasicVFR/pages/P0023B.html",
    "EDWF": "https://aip.dfs.de/BasicVFR/pages/P00340.html",
    "EDWG": "https://aip.dfs.de/BasicVFR/pages/P004CC.html",
    "EDWH": "https://aip.dfs.de/BasicVFR/pages/P003E6.html",
    "EDWI": "https://aip.dfs.de/BasicVFR/pages/P004EA.html",
    "EDWJ": "https://aip.dfs.de/BasicVFR/pages/P002F1.html",
    "EDWK": "https://aip.dfs.de/BasicVFR/pages/P002F7.html",
    "EDWL": "https://aip.dfs.de/BasicVFR/pages/P00332.html",
    "EDWM": "https://aip.dfs.de/BasicVFR/pages/P004E4.html",
    "EDWN": "https://aip.dfs.de/BasicVFR/pages/P003C6.html",
    "EDWO": "https://aip.dfs.de/BasicVFR/pages/P003EE.html",
    "EDWP": "https://aip.dfs.de/BasicVFR/pages/P004E8.html",
    "EDWQ": "https://aip.dfs.de/BasicVFR/pages/P00270.html",
    "EDWR": "https://aip.dfs.de/BasicVFR/pages/P001DA.html",
    "EDWS": "https://aip.dfs.de/BasicVFR/pages/P003BB.html",
    "EDWT": "https://aip.dfs.de/BasicVFR/pages/P00ED1.html",
    "EDWU": "https://aip.dfs.de/BasicVFR/pages/P004BC.html",
    "EDWV": "https://aip.dfs.de/BasicVFR/pages/P004BE.html",
    "EDWX": "https://aip.dfs.de/BasicVFR/pages/P004E6.html",
    "EDWY": "https://aip.dfs.de/BasicVFR/pages/P003BD.html",
    "EDWZ": "https://aip.dfs.de/BasicVFR/pages/P0019E.html",
    "EDXA": "https://aip.dfs.de/BasicVFR/pages/P00152.html",
    "EDXB": "https://aip.dfs.de/BasicVFR/pages/P002B6.html",
    "EDXC": "https://aip.dfs.de/BasicVFR/pages/P0044C.html",
    "EDXD": "https://aip.dfs.de/BasicVFR/pages/P001CE.html",
    "EDXE": "https://aip.dfs.de/BasicVFR/pages/P00424.html",
    "EDXF": "https://aip.dfs.de/BasicVFR/pages/P0024B.html",
    "EDXG": "https://aip.dfs.de/BasicVFR/pages/P00370.html",
    "EDXH": "https://aip.dfs.de/BasicVFR/pages/P002BA.html",
    "EDXI": "https://aip.dfs.de/BasicVFR/pages/P003B7.html",
    "EDXJ": "https://aip.dfs.de/BasicVFR/pages/P002DF.html",
    "EDXK": "https://aip.dfs.de/BasicVFR/pages/P0033E.html",
    "EDXL": "https://aip.dfs.de/BasicVFR/pages/P001A0.html",
    "EDXM": "https://aip.dfs.de/BasicVFR/pages/P0048A.html",
    "EDXN": "https://aip.dfs.de/BasicVFR/pages/P003C4.html",
    "EDXO": "https://aip.dfs.de/BasicVFR/pages/P0048E.html",
    "EDXP": "https://aip.dfs.de/BasicVFR/pages/P002AF.html",
    "EDXQ": "https://aip.dfs.de/BasicVFR/pages/P0042E.html",
    "EDXR": "https://aip.dfs.de/BasicVFR/pages/P0041E.html",
    "EDXT": "https://aip.dfs.de/BasicVFR/pages/P00474.html",
    "EDXU": "https://aip.dfs.de/BasicVFR/pages/P002E1.html",
    "EDXW": "https://aip.dfs.de/BasicVFR/pages/P004A0.html",
    "EDXY": "https://aip.dfs.de/BasicVFR/pages/P004F9.html",
    "EDXZ": "https://aip.dfs.de/BasicVFR/pages/P0031D.html",
    "ETHF": "https://aip.dfs.de/BasicVFR/pages/P00268.html",
    "ETHN": "https://aip.dfs.de/BasicVFR/pages/P003B5.html",
    "ETMN": "https://aip.dfs.de/BasicVFR/pages/P003C1.html",
    "ETND": "https://aip.dfs.de/BasicVFR/pages/P0020F.html",
    "ETNL": "https://aip.dfs.de/BasicVFR/pages/P00323.html",
    "ETSI": "https://aip.dfs.de/BasicVFR/pages/P002E9.html",
}


def seed_airport_links(conn: sqlite3.Connection) -> int:
    """AIP-VFR-Links erstbefuellen -- NUR wenn die Tabelle leer ist (idempotent), damit
    spaetere Admin-Aenderungen/-Loeschungen nie durch einen Neustart ueberschrieben werden.
    Quelle: amtliche DFS-AIP-VFR (lokale AIPBrowserDE-App), 446 Flugplaetze, Stand 2026-06-25."""
    if conn.execute("SELECT COUNT(*) FROM airport_links").fetchone()[0]:
        return 0
    now = _now_utc()
    for icao, url in _AIRPORT_LINKS_SEED.items():
        conn.execute(
            "INSERT INTO airport_links (icao, aip_url, updated_at) VALUES (?, ?, ?)",
            (icao, url, now),
        )
    return len(_AIRPORT_LINKS_SEED)

def list_airport_links(conn: sqlite3.Connection) -> list[dict]:
    """Alle Flugplatz-Links (für die Admin-Tabelle), alphabetisch nach ICAO."""
    rows = conn.execute(
        "SELECT icao, aip_url, updated_at FROM airport_links ORDER BY icao"
    ).fetchall()
    return [dict(r) for r in rows]


def get_airport_links(conn: sqlite3.Connection) -> dict[str, str]:
    """ICAO -> AIP-URL, für die öffentliche Anzeige im Frontend."""
    rows = conn.execute("SELECT icao, aip_url FROM airport_links").fetchall()
    return {r[0]: r[1] for r in rows}


def upsert_airport_link(conn: sqlite3.Connection, icao: str, aip_url: str) -> str:
    """Flugplatz-Link setzen/aktualisieren. Code wird normalisiert gespeichert (Uppercase, getrimmt)."""
    code = (icao or "").strip().upper()
    conn.execute(
        """INSERT INTO airport_links (icao, aip_url, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(icao) DO UPDATE SET
               aip_url=excluded.aip_url, updated_at=excluded.updated_at""",
        (code, aip_url.strip(), _now_utc()),
    )
    return code


def delete_airport_link(conn: sqlite3.Connection, icao: str) -> int:
    """Löscht einen Flugplatz-Link. Gibt 1 zurück wenn eine Zeile gelöscht wurde, sonst 0."""
    code = (icao or "").strip().upper()
    cur = conn.execute("DELETE FROM airport_links WHERE icao = ?", (code,))
    return cur.rowcount


# --- Admin-Prüfliste "Erkennungslücken" (v8.6.0): Flüge, deren GPS-Start oder -Landung
# trotz bekanntem Flugplan fehlt -- typischerweise ein Hinweis auf einen fehlenden
# custom_airports-Eintrag (Fund-Muster dieser Session: EDST/EDWD/EDDX/LOJB). Live berechnet
# über canonicalize_legs (kein eigener Cache), damit ein neu ergänzter Flugplatz sofort aus
# der Liste verschwindet. "Geprüft" markiert Einzelfälle dauerhaft als kein Datenfehler
# (Absturz, Recording-Lücke) -- gilt NUR für diesen einen Flug (Schlüssel cid+logon_time).


# =========================================================================== AIP Charts DFS
# Beide Kartentypen in einer Tabelle. Ab hier gibt es keine Automatik mehr: Eine Passung
# entsteht ausschliesslich aus zwei geklickten Punkten (app/ground_charts.handpassung).

# 'pruefen' OHNE Umlaut: der Wert wird in Python, SQL, JavaScript und Testliteralen
# verglichen -- ein Umlaut darin ist eine Fehlerquelle ohne Gegenwert.
STATUS_DFS = ("gepasst", "auto", "offen", "nicht_gefunden", "pruefen", "verwaist")
SORTEN_DFS = ("sichtflug", "flugplatzkarte", "rollkarte")

_DFS_SPALTEN = ("icao", "sorte", "seite_nr", "gesehener_hash", "bild_hash",
                "nord", "sued", "west", "ost",
                "feld_nord", "feld_sued", "feld_west", "feld_ost",
                "drehung", "mps",
                "p1_x", "p1_y", "p1_lat", "p1_lon",
                "p2_x", "p2_y", "p2_lat", "p2_lon",
                "status", "status_vorher", "airac", "geprueft_am")

# Die Lagefelder. Wer eines davon anfasst, passt -- und braucht bei einer gepassten Karte
# die ausdrueckliche Ansage. Wer nur Status, gesehener_hash oder seite_nr setzt, nicht:
# Der Wochenlauf soll melden koennen, ohne die Passung anzuruehren.
_DFS_LAGE = ("nord", "sued", "west", "ost",
             "feld_nord", "feld_sued", "feld_west", "feld_ost", "drehung", "mps",
             "p1_x", "p1_y", "p1_lat", "p1_lon", "p2_x", "p2_y", "p2_lat", "p2_lon")


class PassungGesperrt(Exception):
    """Eine vom Nutzer gepasste Karte sollte stillschweigend ueberschrieben werden.

    Nachfolgerin von ``HandpassungGesperrt``; das Praedikat wechselt von ``quelle='hand'``
    auf ``status='gepasst'``.

    **Die Sperre bleibt auch nach dem Rueckbau noetig.** Sie richtete sich gegen einen Job,
    der Passungen rechnen konnte -- den gibt es nicht mehr. Aber der Seitenwaehler bleibt,
    und der schreibt bei gescheiterter Passung alle Lagefelder auf 0. Nach dem Rueckbau ist
    die Passung dort IMMER None, der nullende Zweig waere also der einzige. Am 25.08.2026
    hat genau das EDAZ auf 0/0/0/0 gesetzt.
    """


def _dfs_zeilen(conn: sqlite3.Connection, sql: str, *args):
    """Abfrage mit eigenem Cursor und row_factory -- unabhaengig von der Verbindung.

    ``init_db`` oeffnet mit ``sqlite3.connect()``, OHNE row_factory: Dort liefert eine
    Abfrage Tupel, und ein Namenszugriff wie ``r["icao"]`` wirft TypeError. Genau daran ist
    v8.14.0 schon einmal gescheitert (s. den Kommentar bei der transport_cargo-Migration
    weiter unten). Ein eigener Cursor loest es, ohne die Verbindung des Aufrufers zu
    veraendern -- ``conn.row_factory`` zu setzen und zurueckzustellen waere ein Nebeneffekt
    auf fremdem Zustand.
    """
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    return cur.execute(sql, args).fetchall()


def _punkte_aus_rahmen(rahmen_px, r):
    """Die beiden geklickten Rahmenecken aus dem Bestand zurueckgewinnen.

    ``rahmen_px`` ist bei den Sichtflugkarten das Klickprotokoll: vier Zahlen
    ``p1_x,p1_y,p2_x,p2_y``, und ``feld_nord/feld_west`` bzw. ``feld_sued/feld_ost`` sind
    deren Koordinaten -- links-oben ist (Nord, West), rechts-unten ist (Sued, Ost).

    Alle 446 Bestandszeilen sind wohlgeformt (gemessen 31.08.2026); der Ausfallweg ist
    trotzdem noetig, damit eine einzige unlesbare Zeile nicht die anderen 445 liegen laesst.

    Rueckgabe: acht Werte in der Reihenfolge von _DFS_SPALTEN, oder achtmal None.
    """
    try:
        x1, y1, x2, y2 = (float(t) for t in (rahmen_px or "").split(","))
    except (ValueError, AttributeError):
        return (None,) * 8
    return (x1, y1, r["feld_nord"], r["feld_west"],
            x2, y2, r["feld_sued"], r["feld_ost"])


def migration_charts_dfs(conn: sqlite3.Connection) -> int:
    """Bestand aus aip_charts und aip_ground_charts nach aip_charts_dfs uebernehmen.

    **Laeuft genau einmal.** ``init_db`` wird bei jedem Containerstart aufgerufen; eine
    Migration, die dabei erneut liefe, wuerde Nutzerarbeit zuruecksetzen. Drei Riegel:

    1. Merker in ``job_laeufe`` -- steht er, passiert nichts.
    2. ``ON CONFLICT DO NOTHING`` -- auch wenn jemand den Merker loescht, wird keine
       bearbeitete Zeile ueberschrieben.
    3. Der Aufrufer faengt ``sqlite3.Error``, nicht ``OperationalError``: Ein INSERT in
       eine Tabelle mit Primaerschluessel wirft ``IntegrityError``, und die ist KEIN
       OperationalError -- ``init_db`` braeche ab, die App startete nicht.

    Die alten Tabellen bleiben stehen. Erst wenn der neue Stand geprueft ist, darf jemand
    sie loeschen -- bis dahin ist die Migration nach Loeschen des Merkers wiederholbar.

    Rueckgabe: Zahl der uebernommenen Zeilen, 0 wenn schon gelaufen.
    """
    if _dfs_zeilen(conn, "SELECT 1 FROM job_laeufe WHERE name = 'migration_charts_dfs'"):
        return 0

    platzhalter = ", ".join("?" * len(_DFS_SPALTEN))
    einfuegen = (f"INSERT INTO aip_charts_dfs ({', '.join(_DFS_SPALTEN)}) "
                 f"VALUES ({platzhalter}) ON CONFLICT(icao, sorte) DO NOTHING")
    n = 0

    # --- Sichtflugkarten -----------------------------------------------------------
    # quelle='hand' heisst "vom Nutzer gesetzt" -> gepasst.
    # quelle='auto' heisst "gerechnet, ungeprueft" -> auto.
    for r in _dfs_zeilen(conn, """SELECT icao, rahmen_px, bild_hash, nord, sued, west, ost,
                                        feld_nord, feld_sued, feld_west, feld_ost,
                                        quelle, airac, status, geprueft_am
                                 FROM aip_charts"""):
        # 'verwaist' bleibt 'verwaist': Der Link ist verschwunden, die Passung nicht. Sie
        # kehrt zurueck, sobald der Link wieder auftaucht -- ein AIRAC-Wechsel benennt
        # Kapitelseiten um. Wer sie hier auf 'gepasst' hebt, verliert die Information.
        if r["status"] == "verwaist":
            status = "verwaist"
        else:
            status = "gepasst" if r["quelle"] == "hand" else "auto"
        # seite_nr bleibt None und gesehener_hash leer: seite_url ist im Bestand in ALLEN
        # 446 Zeilen leer, und den Rohbytes-Hash haben wir nicht -- bild_hash wird NACH dem
        # Drehen gebildet (app/main.py) und stimmt bei den sieben quer gedruckten Blaettern
        # nicht. Beides traegt der erste Joblauf nach; leerer Hash heisst dort "noch nie
        # gesehen: eintragen, nicht melden".
        conn.execute(einfuegen,
                     (r["icao"], "sichtflug", None, "", r["bild_hash"] or "",
                      r["nord"], r["sued"], r["west"], r["ost"],
                      r["feld_nord"], r["feld_sued"], r["feld_west"], r["feld_ost"],
                      0.0, 0.0, *_punkte_aus_rahmen(r["rahmen_px"], r),
                      status, None, r["airac"] or "", r["geprueft_am"]))
        n += 1

    # --- Flugplatz- und Rollkarten -------------------------------------------------
    # ALLE bestehenden Passungen stammen von Claude, nicht vom Nutzer -- sie fallen deshalb
    # auf 'auto' zurueck, nicht auf 'gepasst'.
    #
    # Die Klickpunkte sind hier UNRETTBAR: Sie wurden nie abgelegt. p1_*/p2_* bleiben leer;
    # wer nachjustieren will, klickt neu. Das ist der einzige echte Verlust der Migration.
    #
    # Der Hash dagegen wandert MIT: aip_ground_charts.quell_hash ist der echte
    # Rohbytes-Hash (scripts/ground_chart_bestand.py hasht ``roh``, vor jedem Drehen), alle
    # 110 Zeilen tragen 64 Zeichen. Diese Karten haben ab dem ersten Tag eine gueltige
    # Aenderungserkennung -- anders als die 446 Sichtflugzeilen oben.
    for r in _dfs_zeilen(conn, """SELECT icao, sorte, quell_hash, bild_hash,
                                        nord, sued, west, ost,
                                        feld_nord, feld_sued, feld_west, feld_ost,
                                        drehung, mps, airac, status, geprueft_am
                                 FROM aip_ground_charts"""):
        status = "auto" if r["status"] == "gepasst" else "offen"
        conn.execute(einfuegen,
                     (r["icao"], r["sorte"], None, r["quell_hash"] or "",
                      r["bild_hash"] or "",
                      r["nord"], r["sued"], r["west"], r["ost"],
                      r["feld_nord"], r["feld_sued"], r["feld_west"], r["feld_ost"],
                      r["drehung"], r["mps"], None, None, None, None, None, None, None,
                      None, status, None, r["airac"] or "", r["geprueft_am"]))
        n += 1

    if n:
        # Merker NUR bei tatsaechlich uebernommenen Zeilen. Auf einer frischen Datenbank
        # laeuft init_db, bevor irgendetwas in den alten Tabellen steht -- der Merker waere
        # dann gesetzt und die Migration verbraucht, ohne je gearbeitet zu haben. Ist
        # nichts zu tun, kostet ein erneuter Lauf zwei Abfragen auf leere Tabellen.
        conn.execute("INSERT INTO job_laeufe (name, zuletzt) VALUES (?, ?)",
                     ("migration_charts_dfs", _now_utc()))
    return n


def upsert_chart_dfs(conn: sqlite3.Connection, icao: str, sorte: str,
                     hand_ueberschreiben: bool = False, **felder) -> None:
    """Karte setzen. ``status`` ist Pflicht und muss aus STATUS_DFS stammen.

    Nur die MITGEGEBENEN Felder werden nachgezogen. Ein Aufruf, der bloss den Status
    aendert -- etwa der Wochenlauf mit ``status='pruefen'`` --, darf die Passung nicht auf
    Null zuruecksetzen.

    Die Sperre (s. ``PassungGesperrt``) greift nur, wenn ein LAGEfeld mitkommt.
    """
    code = (icao or "").strip().upper()
    if sorte not in SORTEN_DFS:
        raise ValueError(f"unbekannte Sorte: {sorte!r}")
    if felder.get("status") not in STATUS_DFS:
        raise ValueError(f"unbekannter Status: {felder.get('status')!r}")
    unbekannt = set(felder) - set(_DFS_SPALTEN)
    if unbekannt:
        # Ein Tippfehler im Feldnamen fiele sonst still unter den Tisch -- der Aufrufer
        # glaubte zu schreiben, und nichts geschieht.
        raise ValueError(f"unbekannte Felder: {sorted(unbekannt)}")
    if not hand_ueberschreiben and any(f in felder for f in _DFS_LAGE):
        alt = _dfs_zeilen(
            conn, "SELECT status FROM aip_charts_dfs WHERE icao = ? AND sorte = ?",
            code, sorte)
        if alt and alt[0]["status"] == "gepasst":
            raise PassungGesperrt(
                f"{code}/{sorte} ist vom Nutzer gepasst -- hand_ueberschreiben noetig")

    setzbar = [f for f in _DFS_SPALTEN
               if f not in ("icao", "sorte", "geprueft_am") and f in felder]
    spalten = ("icao", "sorte", *setzbar, "geprueft_am")
    nachziehen = ", ".join(f"{f}=excluded.{f}" for f in (*setzbar, "geprueft_am"))
    conn.execute(
        f"INSERT INTO aip_charts_dfs ({', '.join(spalten)}) "
        f"VALUES ({', '.join('?' * len(spalten))}) "
        f"ON CONFLICT(icao, sorte) DO UPDATE SET {nachziehen}",
        (code, sorte, *(felder[f] for f in setzbar), _now_utc()))


def get_charts_dfs(conn: sqlite3.Connection, status=None, sorte=None) -> list[dict]:
    """Karten lesen, wahlweise gefiltert. ``status`` und ``sorte`` sind Listen."""
    bedingungen, args = [], []
    for spalte, werte in (("status", status), ("sorte", sorte)):
        if werte:
            bedingungen.append(f"{spalte} IN ({', '.join('?' * len(werte))})")
            args.extend(werte)
    wo = (" WHERE " + " AND ".join(bedingungen)) if bedingungen else ""
    return [dict(r) for r in _dfs_zeilen(
        conn, f"SELECT * FROM aip_charts_dfs{wo} ORDER BY icao, sorte", *args)]


def get_chart_dfs(conn: sqlite3.Connection, icao: str, sorte: str) -> dict | None:
    r = _dfs_zeilen(conn, "SELECT * FROM aip_charts_dfs WHERE icao = ? AND sorte = ?",
                    (icao or "").strip().upper(), sorte)
    return dict(r[0]) if r else None


def delete_chart_dfs(conn: sqlite3.Connection, icao: str, sorte: str) -> int:
    cur = conn.execute("DELETE FROM aip_charts_dfs WHERE icao = ? AND sorte = ?",
                       ((icao or "").strip().upper(), sorte))
    return cur.rowcount


_AIP_FELDER = ("bild_hash", "nord", "sued", "west", "ost",
               "feld_nord", "feld_sued", "feld_west", "feld_ost",
               "rahmen_px", "tick_px_lat", "tick_px_lon", "quelle", "airac", "status")
# seite_url steht bewusst NICHT in _AIP_FELDER: Das machte sie zum Pflichtfeld fuer alle
# sieben Schreibpfade, von denen sechs sie gar nicht kennen. Sie wird optional
# durchgereicht und faellt sonst auf den bestehenden Wert zurueck -- ein Auffrischlauf,
# der sie nicht mitgibt, darf eine gesetzte Wahl nicht loeschen.
_AIP_OPTIONAL = ("seite_url",)
_AIP_SPALTEN = ("icao", *_AIP_FELDER, *_AIP_OPTIONAL, "geprueft_am")


class HandpassungGesperrt(Exception):
    """Versuch, eine von Hand gesetzte Passung automatisch zu ueberschreiben.

    Die Sperre sitzt in ``upsert_aip_chart`` und nicht bei den Aufrufern, weil es sieben
    Schreibpfade auf ``aip_charts`` gibt (Stand 30.08.2026): drei in
    scripts/aip_bestand.py, zwei in app/main.py, einer in scripts/aip_handpassung.py, dazu
    delete_aip_chart. Zwei davon haben Handpassungen ueberschrieben, ein dritter war beim
    Entwurf der Spec nicht einmal bekannt. Eine Pruefung an jeder Aufrufstelle waere beim
    naechsten neuen Pfad wieder unvollstaendig.
    """


def upsert_aip_chart(conn: sqlite3.Connection, icao: str, *,
                     hand_ueberschreiben: bool = False, **felder) -> str:
    """Kartenpassung setzen/aktualisieren. Alle Felder aus _AIP_FELDER sind Pflicht.

    Zwei Rechtecke, die nicht zu verwechseln sind: ``nord/sued/west/ost`` sind die Grenzen
    des GANZEN Blatts -- danach wird das Overlay platziert. ``feld_*`` sind die Grenzen des
    Kartenfelds -- danach schaltet die Automatik, und dagegen prueft der Lagetest.

    **Gesperrt ist genau ein Fall: ein Schreibversuch mit quelle='auto' auf eine bestehende
    Zeile mit quelle='hand'.** Nicht "keine Handzeile ueberschreiben" -- das braeche drei
    berechtigte Pfade: ``_handblatt_auffrischen`` (zieht das Bild nach, hand ueber hand),
    ``admin_set_aip_chart`` und ``scripts/aip_handpassung.py`` (ein Mensch korrigiert seine
    eigene Passung, so wie der Nutzer es am 30.08.2026 bei EDDL tun musste).

    ``hand_ueberschreiben=True`` ist ausschliesslich fuer die Uebernahme eines Vorschlags
    durch den Admin gedacht. Kein automatischer Pfad setzt es.

    Der ``status`` spielt bewusst KEINE Rolle: Der Seitenwaehler erzeugte bis 30.08.2026
    Zeilen mit quelle='hand' und status='ungepasst'. An den status gebunden fielen genau
    die durch die Sperre.

    Grundlage ist die Festlegung des Nutzers vom 30.08.2026: "Eine manuell durchgefuehrte
    Korrektur darf nicht einfach ueberschrieben werden! Wenn es eine neue Version gibt,
    kann diese zur Pruefung angezeigt werden. Aber keinesfalls erneut verzerrt werden!"
    """
    code = (icao or "").strip().upper()
    fehlt = [f for f in _AIP_FELDER if f not in felder]
    if fehlt:
        raise ValueError(f"Pflichtfelder fehlen: {', '.join(fehlt)}")
    _handpassung_pruefen(conn, "aip_charts", code, felder, hand_ueberschreiben)
    # Optionale Felder nur nachziehen, wenn sie mitgegeben wurden. Ein Auffrischlauf kennt
    # seite_url nicht und darf eine vom Admin gesetzte Wahl nicht auf '' zuruecksetzen --
    # das waere derselbe stille Verlust, gegen den die Spalte eingefuehrt wurde.
    mitgegeben = [f for f in _AIP_OPTIONAL if f in felder]
    platz = ", ".join("?" * len(_AIP_SPALTEN))
    setzen = ", ".join(f"{f}=excluded.{f}"
                       for f in (*_AIP_FELDER, *mitgegeben, "geprueft_am"))
    conn.execute(
        f"""INSERT INTO aip_charts ({', '.join(_AIP_SPALTEN)}) VALUES ({platz})
            ON CONFLICT(icao) DO UPDATE SET {setzen}""",
        (code, *(felder[f] for f in _AIP_FELDER),
         *(felder.get(f, "") for f in _AIP_OPTIONAL), _now_utc()),
    )
    return code


def get_aip_charts(conn: sqlite3.Connection, nur_gepasst: bool = True) -> list[dict]:
    """Alle Karten, standardmaessig nur die gepassten.

    Die Vorgabe ist Absicht: Eine Karte, die falsch liegt, ist schlimmer als gar keine.
    """
    wo = "WHERE status = 'gepasst'" if nur_gepasst else ""
    rows = conn.execute(
        f"SELECT {', '.join(_AIP_SPALTEN)} FROM aip_charts {wo} ORDER BY icao"
    ).fetchall()
    return [dict(zip(_AIP_SPALTEN, r)) for r in rows]


def get_aip_chart(conn: sqlite3.Connection, icao: str) -> dict | None:
    code = (icao or "").strip().upper()
    r = conn.execute(
        f"SELECT {', '.join(_AIP_SPALTEN)} FROM aip_charts WHERE icao = ?", (code,)
    ).fetchone()
    return dict(zip(_AIP_SPALTEN, r)) if r else None


def delete_aip_chart(conn: sqlite3.Connection, icao: str) -> int:
    """Karte entfernen. Noetig, wenn ihr Eintrag aus airport_links verschwindet -- sonst
    bliebe eine Karte im Umlauf, die der Admin bewusst geloescht hat.

    **Nur fuer Automatikkarten.** Eine Handpassung wird stattdessen ueber ``verwaisen()``
    aus der Anzeige genommen; siehe dort. Die Sperre in ``upsert_aip_chart`` greift hier
    nicht -- sie sitzt im Schreibpfad, nicht im Loeschpfad.
    """
    code = (icao or "").strip().upper()
    return conn.execute("DELETE FROM aip_charts WHERE icao = ?", (code,)).rowcount


def job_faellig(conn: sqlite3.Connection, name: str, abstand_s: float) -> bool:
    """Ist dieser Job wieder dran?

    ``True``, wenn er noch nie gelaufen ist oder der letzte Lauf laenger als ``abstand_s``
    zurueckliegt. Siehe die Tabelle ``job_laeufe`` fuer den Grund.
    """
    zeile = conn.execute(
        "SELECT zuletzt FROM job_laeufe WHERE name = ?", (name,)).fetchone()
    if zeile is None:
        return True
    try:
        zuletzt = datetime.fromisoformat(str(zeile["zuletzt"]).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    if zuletzt.tzinfo is None:
        zuletzt = zuletzt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - zuletzt).total_seconds() >= abstand_s


def job_erledigt(conn: sqlite3.Connection, name: str) -> None:
    """Lauf vermerken. Erst danach ist der Job fuer ``abstand_s`` wieder ruhig."""
    conn.execute(
        """INSERT INTO job_laeufe (name, zuletzt) VALUES (?, ?)
           ON CONFLICT(name) DO UPDATE SET zuletzt = excluded.zuletzt""",
        (name, _now_utc()))


_GROUND_FELDER = ("sorte", "quell_hash", "bild_hash", "nord", "sued", "west", "ost",
                  "feld_nord", "feld_sued", "feld_west", "feld_ost",
                  "drehung", "mps", "rest_max", "bahnen", "quelle", "airac", "status")
_GROUND_OPTIONAL = ("seite_url",)
_GROUND_SPALTEN = ("icao", *_GROUND_FELDER, *_GROUND_OPTIONAL, "geprueft_am")


def _handpassung_pruefen(conn: sqlite3.Connection, tabelle: str, code: str,
                         felder: dict, hand_ueberschreiben: bool) -> None:
    """Die Sperre aus Abschnitt 7 der Spec -- fuer beide Kartentabellen dieselbe.

    Gesperrt ist genau ein Fall: ein Schreibversuch mit quelle='auto' auf eine bestehende
    Zeile mit quelle='hand'. Zwei Fassungen davon wuerden auseinanderlaufen; die
    Flugplatzkarten sind genauso schutzwuerdig wie die Sichtflugkarten.
    """
    if hand_ueberschreiben or felder.get("quelle") == "hand":
        return
    alt = conn.execute(
        f"SELECT quelle FROM {tabelle} WHERE icao = ?", (code,)).fetchone()
    if alt is not None and alt["quelle"] == "hand":
        raise HandpassungGesperrt(
            f"{code}: Handpassung wird nicht automatisch ueberschrieben")


def upsert_ground_chart(conn: sqlite3.Connection, icao: str, *,
                        hand_ueberschreiben: bool = False, **felder) -> str:
    """Flugplatzkarten-Passung setzen. Dieselbe Sperre wie bei den Sichtflugkarten."""
    code = (icao or "").strip().upper()
    fehlt = [f for f in _GROUND_FELDER if f not in felder]
    if fehlt:
        raise ValueError(f"Pflichtfelder fehlen: {', '.join(fehlt)}")
    _handpassung_pruefen(conn, "aip_ground_charts", code, felder, hand_ueberschreiben)
    mitgegeben = [f for f in _GROUND_OPTIONAL if f in felder]
    platz = ", ".join("?" * len(_GROUND_SPALTEN))
    setzen = ", ".join(f"{f}=excluded.{f}"
                       for f in (*_GROUND_FELDER, *mitgegeben, "geprueft_am"))
    conn.execute(
        f"""INSERT INTO aip_ground_charts ({', '.join(_GROUND_SPALTEN)}) VALUES ({platz})
            ON CONFLICT(icao) DO UPDATE SET {setzen}""",
        (code, *(felder[f] for f in _GROUND_FELDER),
         *(felder.get(f, "") for f in _GROUND_OPTIONAL), _now_utc()),
    )
    return code


def get_ground_charts(conn: sqlite3.Connection, nur_gepasst: bool = True) -> list[dict]:
    """Alle Flugplatzkarten, standardmaessig nur die gepassten.

    Die Vorgabe ist dieselbe wie bei den Sichtflugkarten und aus demselben Grund: Eine
    falsch liegende Karte ist schlimmer als gar keine -- beim Rollen wird sie geglaubt.
    """
    wo = "WHERE status = 'gepasst'" if nur_gepasst else ""
    rows = conn.execute(
        f"SELECT {', '.join(_GROUND_SPALTEN)} FROM aip_ground_charts {wo} ORDER BY icao"
    ).fetchall()
    return [dict(zip(_GROUND_SPALTEN, r)) for r in rows]


def get_ground_chart(conn: sqlite3.Connection, icao: str) -> dict | None:
    code = (icao or "").strip().upper()
    r = conn.execute(
        f"SELECT {', '.join(_GROUND_SPALTEN)} FROM aip_ground_charts WHERE icao = ?",
        (code,)).fetchone()
    return dict(zip(_GROUND_SPALTEN, r)) if r else None


def delete_ground_chart(conn: sqlite3.Connection, icao: str) -> int:
    """Nur fuer Automatikkarten. Eine Handpassung wird ueber verwaisen_ground() aus der
    Anzeige genommen -- dieselbe Unterscheidung wie bei den Sichtflugkarten."""
    code = (icao or "").strip().upper()
    return conn.execute(
        "DELETE FROM aip_ground_charts WHERE icao = ?", (code,)).rowcount


def verwaisen_ground(conn: sqlite3.Connection, icao: str) -> int:
    code = (icao or "").strip().upper()
    return conn.execute(
        "UPDATE aip_ground_charts SET status = 'verwaist' WHERE icao = ?",
        (code,)).rowcount


def verwaisen(conn: sqlite3.Connection, icao: str) -> int:
    """Karte aus der Anzeige nehmen, ohne sie zu verlieren.

    Fuer handgepasste Karten, deren Eintrag aus ``airport_links`` verschwunden ist. Eine
    Automatikkarte ist in Minuten neu gerechnet und wird geloescht; eine Handpassung ist
    Arbeit eines Menschen und bleibt erhalten. ``get_aip_charts()`` filtert auf
    ``status='gepasst'`` und laesst sie damit von allein aus der Liste.

    Taucht der Link wieder auf -- ein AIRAC-Wechsel benennt Kapitelseiten um --, genuegt ein
    erneutes Setzen mit ``status='gepasst'``, um sie zurueckzuholen. Das Blatt bleibt
    liegen: 1,4 MB sind billiger als eine verlorene Handpassung.
    """
    code = (icao or "").strip().upper()
    return conn.execute(
        "UPDATE aip_charts SET status = 'verwaist' WHERE icao = ?", (code,)).rowcount

def list_gps_detection_gaps(conn: sqlite3.Connection) -> list[dict]:
    """Flüge mit fehlendem GPS-Start ODER fehlender GPS-Landung trotz bekanntem Flugplan-Wert,
    ohne bereits als "geprüft" markierte Fälle. Neueste zuerst, auf 200 Zeilen gekappt."""
    now = _now_utc()
    flights = canonicalize_legs(conn, start="2000-01-01T00:00:00Z", end=now, callsign_prefix="")
    dismissed = {
        (r[0], r[1])
        for r in conn.execute("SELECT cid, logon_time FROM gps_detection_dismissals").fetchall()
    }
    pilot_names = {
        r[0]: r[1] for r in conn.execute("SELECT cid, name FROM pilots").fetchall()
    }

    gaps: list[dict] = []
    for f in flights:
        cid = f.get("cid")
        logon_time = f.get("logon_time")
        if cid is None or logon_time is None or (cid, logon_time) in dismissed:
            continue
        missing_dep = not f.get("gps_departure") and f.get("plan_departure")
        missing_arr = (
            not f.get("gps_arrival") and f.get("connection_closed") and f.get("plan_arrival")
        )
        if not missing_dep and not missing_arr:
            continue
        missing = "both" if (missing_dep and missing_arr) else ("departure" if missing_dep else "arrival")
        gaps.append({
            "cid": cid,
            "logon_time": logon_time,
            "pilot_name": pilot_names.get(cid),
            "callsign": f.get("callsign"),
            "aircraft": f.get("aircraft"),
            "plan_departure": f.get("plan_departure"),
            "plan_arrival": f.get("plan_arrival"),
            "gps_departure": f.get("gps_departure"),
            "gps_arrival": f.get("gps_arrival"),
            "missing": missing,
            "source": f.get("source"),
            "id": f.get("id"),
            "statsim_id": f.get("statsim_id"),
            "duration_min": f.get("duration_min"),
        })

    gaps.sort(key=lambda g: g["logon_time"], reverse=True)
    return gaps[:200]


def dismiss_gps_detection_gap(conn: sqlite3.Connection, cid: int, logon_time: str) -> None:
    """Markiert einen Flug dauerhaft als "kein Datenfehler" -- taucht in der Prüfliste nicht
    mehr auf, auch wenn seine GPS-Lücke bestehen bleibt. Gilt NUR für diesen einen Flug."""
    conn.execute(
        "INSERT INTO gps_detection_dismissals (cid, logon_time, dismissed_at) VALUES (?, ?, ?) "
        "ON CONFLICT(cid, logon_time) DO UPDATE SET dismissed_at=excluded.dismissed_at",
        (cid, logon_time, _now_utc()),
    )


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


def clear_transport_quips(conn: sqlite3.Connection, event_id: int) -> int:
    """Alle Flug-Sprüche eines Events löschen (und den Tagesend-Spruch zurücksetzen), damit der
    Poller sie beim nächsten Durchlauf neu generiert (Bedingung dort: ``not f.get('quip')``).
    Gebraucht, wenn sich die Spruch-Logik ändert und bereits gecachte Sprüche veraltet sind
    (z. B. #67-Folgefund: Liefer-Spruch für einen geklauten Flug). Gibt die Anzahl gelöschter
    Flug-Sprüche zurück."""
    n = conn.execute("DELETE FROM transport_quips WHERE event_id = ?", (event_id,)).rowcount
    conn.execute("UPDATE transport_events SET summary_quip = NULL WHERE id = ?", (event_id,))
    return n


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
    cargo_lines = flight.get("cargo_lines") or []
    cargo = [
        f"{(c.get('emoji') or '').strip()} {c['name']} ({round(c['kg'])} kg)".strip()
        for c in cargo_lines
    ]
    # #67 (Live-Fund 06.07.): "Zuladung" aus der Summe der Bordladung (cargo_lines) ableiten,
    # NICHT aus tonnage_kg direkt — bei einem Verlust (versunken/geklaut) ist tonnage_kg IMMER
    # 0 (nichts wurde netto geliefert), obwohl cargo_lines weiterhin zeigt, was tatsächlich an
    # Bord war. Beides gleichzeitig an die KI zu geben ("220 kg Fracht ... Zuladung: 0 kg")
    # erzeugte widersprüchliche Sprüche. Für normale Lieferungen ist die Summe ohnehin identisch
    # mit tonnage_kg (beide stammen aus derselben Co-Load-Verteilung) — kein Verhaltensunterschied.
    onboard_kg = round(sum(c.get("kg") or 0 for c in cargo_lines))
    loss_kind = flight.get("loss_kind")
    verlust = None
    relay = None
    if loss_kind == "sunk":
        verlust = f"Kutter versunken — {round(flight.get('lost_kg') or 0)} kg Fracht verloren"
    elif loss_kind == "stolen":
        verlust = (f"am falschen Ort gelandet ({flight.get('arr')}) — "
                   f"{round(flight.get('lost_kg') or 0)} kg Fracht geklaut")
    elif loss_kind == "returned":
        # v10.2.1-Umbenennung (Live-Fund 21.07.): eine „returned"-Bewegung ist KEIN
        # schiefgegangener Flug, sondern eine Staffel-Übergabe — die Ware wird an einem
        # Ladeplatz abgeladen und liegt dort zum Weitertragen bereit. NICHT über den
        # verlust-/„GING SCHIEF"-Zweig (sonst textete die KI „unentschlossen/umgedreht").
        relay = "an einem Ladeplatz abgeladen (nicht bis zum Ziel) — liegt dort zum Weitertragen bereit"
    return {
        "vorname": vorname,
        "callsign": flight.get("callsign"),
        "flights_tonight": flights_tonight,
        "aircraft": flight.get("aircraft"),
        "route": f"{dep}→{arr}",
        "tonnage_kg": onboard_kg,
        "cargo": cargo,
        "speed_kt": speed_kt,
        "detour_ratio": detour_ratio,
        "verlust": verlust,
        "relay": relay,
    }


def event_summary_context(event: dict, progress: dict) -> dict:
    """Kontext für die lustige Tagesend-Zusammenfassung (rein, testbar)."""
    flights = [f for f in progress.get("flights", []) if f.get("loaded")]

    def _label(name: object, callsign: object) -> str:
        # Anzeige-Name: VORNAME + Callsign, nie Nachname. Das Callsign macht eindeutig — zwei
        # Piloten mit gleichem Vornamen (zwei „Michael") lassen sich am Vornamen allein NICHT
        # auseinanderhalten. Ohne Callsign (Altbestand/Testdaten) bleibt der Vorname allein.
        raw = ((str(name) if name else "") or (str(callsign) if callsign else "") or "?").strip()
        who = raw.split()[0] if raw else "?"
        cs = str(callsign).strip() if callsign else ""
        return f"{who} ({cs})" if cs else who

    # Nach CALLSIGN aggregieren, NICHT nach Vorname: sonst verschmelzen zwei „Michael" zu EINER
    # Zeile mit summierten Flügen — dann fällt einer aus der Zusammenfassung und die Flugzahl
    # stimmt nicht (Fund 19.07.). Das Callsign ist der eindeutige Schlüssel.
    _agg: dict[str, dict] = {}
    for f in flights:
        cs = (f.get("callsign") or "").strip()
        key = cs or _label(f.get("name"), f.get("callsign"))
        ent = _agg.setdefault(key, {"label": _label(f.get("name"), f.get("callsign")), "n": 0})
        ent["n"] += 1
    # ALLE Piloten, mit ihrer Fuhrenzahl. Gezaehlt wird `loaded`, also die Ablieferung am Ziel:
    # Wer ueber einen Zwischenplatz faehrt, macht mehrere FLUEGE, bringt aber EINE Fuhre.
    # Weggelassen wird nur die ZAHL bei einer einzelnen Fuhre (s. llm.event_summary) -- der
    # Text las sich sonst als "X mit 1 Flug, Y mit 1 Flug, ...", neunmal dieselbe Angabe.
    # Der Pilot selbst wird immer genannt (Nutzerkorrektur 04.09.2026: ein Zwischenstand
    # dieser Aenderung hatte die Einzelfahrer ganz aus dem Text geworfen, sodass nur noch
    # Verluste uebrig blieben).
    per_pilot = {e["label"]: e["n"] for e in _agg.values()}
    return {
        "name": event.get("name"),
        "total_kg": progress.get("total_kg"),
        "loaded_count": progress.get("loaded_count"),
        "cargo": [
            f"{(c.get('emoji') or '')} {c['name']} {round(c['delivered_kg'])}/{round(c['target_kg'])} kg".strip()
            for c in progress.get("cargo", [])
        ],
        "pilots": per_pilot,
        # KEINE Routen-Kette mehr (irreführend, #12/Live-Fund 09.07.): die aneinandergereihten
        # Streckenplätze — inkl. Ziel — verleiteten die KI zu „auf der Runde A-B-C-D", obwohl es keine
        # geflogene Runde ist. Stattdessen Ziel als Anker + Abholplätze (Route ohne Ziel) getrennt.
        "destination": progress.get("destination"),
        "pickups": [p for p in progress.get("route", []) if p != progress.get("destination")],
        "lost_total_kg": progress.get("lost_total_kg", 0.0),
        # Nur ECHTE Verluste (versunken/geklaut). Eine „returned"-Bewegung ist kg-neutral und
        # kein Verlust — sie käme sonst als „MUSST du als Verlust nennen" bei der KI an und
        # würde als Missgeschick getextet (Live-Fund 21.07., #238/#239: „unentschlossen …
        # zurückgebracht"). Stattdessen als Staffel-Übergabe getrennt (siehe `abgeladen`).
        "verluste": [
            (f"{_label(l.get('name'), l.get('callsign'))}: "
             # AKTIV formulieren. "Fracht geklaut" laesst offen, WER geklaut hat, und die KI
             # machte daraus ein Missgeschick mit unbekanntem Dieb ("wurde erleichtert --
             # irgendwer hatte wohl Appetit", Nutzerfund 04.09.2026). `stolen` entsteht aber in
             # _drop_load genau dann, wenn der Pilot mit Ware an einem Platz landet, der weder
             # Ziel noch Ladeplatz ist: Er hat sie mitgenommen und dort behalten. Beim Versinken
             # ist er dagegen NICHT der Taeter -- deshalb bleibt der Zweig unveraendert.
             + ("Kutter versunken" if l.get("loss_kind") == "sunk"
                else "hat die Fracht selbst geklaut")
             + f" ({round(l.get('lost_kg') or 0)} kg)")
            for l in progress.get("losses", [])
            if l.get("loss_kind") in ("sunk", "stolen")
        ],
        # KEIN „abgeladen"-Feld mehr (Nutzerentscheidung 04.09.2026). Eine „returned"-Bewegung
        # entsteht auch dann, wenn ein Pilot am Ladeplatz nur seinen Flugplan neu einloggt: Beim
        # Logout faellt die Ladung ab (_drop_load), beim naechsten Login nimmt _load_standing sie
        # sofort wieder auf. Der Tagestext feierte das als „Staffeluebergabe nach Lehrbuch",
        # obwohl netto nichts geschehen war (FRS61 mit 11 s, FRS96 mit 17 s Sessionluecke am
        # 04.09.2026). Aus dem Bericht liesse sich beides nicht unterscheiden — dafuer braeuchte
        # es die Bewegungen aus derive_stacks, die hier nicht vorliegen. Deshalb gar nicht mehr
        # erwaehnen; am Modell aendert das nichts, die Ware bleibt korrekt verbucht.
    }


def aggregate_kutter_kpis(progresses: list[dict]) -> dict:
    """Aggregiert fertige compute_transport_progress-/Snapshot-Dicts abgeschlossener Kutter-Events
    zu KPI-Summen. Rein (keine DB). Nur Events mit flight_count>0 zählen (leere Test-Events
    verfälschen die Anzahl nicht). `returned`-Verluste sind kg-neutral und werden nicht als
    Verlust gezählt (aber ihre Flug-Zeile steckt in flight_count)."""
    event_count = participations = flights = 0
    delivered_kg = sunk_kg = stolen_kg = 0.0
    sunk_count = stolen_count = 0
    for p in progresses:
        if (p.get("flight_count") or 0) <= 0:
            continue
        event_count += 1
        participations += len(p.get("participants", []))
        flights += p.get("flight_count") or 0
        delivered_kg += p.get("total_kg") or 0.0
        for l in p.get("losses", []):
            kg = l.get("lost_kg") or 0.0
            if l.get("loss_kind") == "sunk":
                sunk_kg += kg
                sunk_count += 1
            elif l.get("loss_kind") == "stolen":
                stolen_kg += kg
                stolen_count += 1
    return {
        "event_count": event_count,
        "participations": participations,
        "flights": flights,
        "delivered_kg": round(delivered_kg, 1),
        "sunk_kg": round(sunk_kg, 1), "sunk_count": sunk_count,
        "stolen_kg": round(stolen_kg, 1), "stolen_count": stolen_count,
    }


def aggregate_bummel_kpis(views: list[dict]) -> dict:
    """Aggregiert fertige _bummel_view-/Snapshot-Dicts abgeschlossener (enthüllter) Rennen zu
    KPI-Summen. Rein (keine DB). Nur Rennen mit participant_count>0 zählen. „Flüge" = gewertete
    Tour-Legs (Σ leg_count über complete+incomplete). „Ø Absoluter Durchschnitt" = Mittel der
    average_min NUR über Rennen mit count>0 (average_min ist bei 0 Touren 0.0, nicht None)."""
    race_count = participations = legs = 0
    avg_values: list[float] = []
    for v in views:
        if (v.get("participant_count") or 0) <= 0:
            continue
        race_count += 1
        participations += v.get("participant_count") or 0
        for e in list(v.get("complete", [])) + list(v.get("incomplete", [])):
            legs += e.get("leg_count", len(e.get("legs", []) or []))
        if (v.get("count") or 0) > 0:
            avg_values.append(v.get("average_min") or 0.0)
    return {
        "race_count": race_count,
        "participations": participations,
        "legs": legs,
        "avg_absolute_min": round(sum(avg_values) / len(avg_values), 1) if avg_values else None,
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


def clear_transport_summarized(conn: sqlite3.Connection, event_id: int) -> None:
    """``summarized_at`` zurücksetzen → das Event gilt wieder als NICHT abgeschlossen und wird live
    gerechnet (Auftauen). Gegenstück zum Einfrieren; nötig, wenn ein Event versehentlich/zu früh
    eingefroren wurde (z. B. dtend-Tippfehler in der Vergangenheit) und beim Bearbeiten wieder
    live werden soll — Snapshot-Löschung allein reicht nicht, weil ``finished`` an diesem Latch hängt."""
    conn.execute("UPDATE transport_events SET summarized_at = NULL WHERE id = ?", (event_id,))


def open_transport_flights(conn: sqlite3.Connection, callsign_prefix: str = "FRS") -> list[dict]:
    """Aktuell offene (noch verbundene) FRS-Flüge — Basis für Live-Ankunft ohne Disconnect."""
    rows = conn.execute(
        "SELECT cid, callsign, aircraft_short AS aircraft, aircraft_icao, departure, arrival, logon_time "
        "FROM flights WHERE logoff_time IS NULL AND superseded_by IS NULL AND callsign LIKE ?",
        (callsign_prefix + "%",),
    ).fetchall()
    return [dict(r) for r in rows]


def _current_pos(conn: sqlite3.Connection, cid: int) -> tuple[float, float, float] | None:
    """(lat, lon, groundspeed) der AKTUELLEN Live-Position (live_positions), oder None.

    Quelle der GPS-only Boden-Beladung (#5): eine Zeile je aktuell verbundener CID, vom Poller
    jede Runde aktualisiert. Fehlt sie (Pilot gerade offline / erste Runde) oder fehlen die
    Koordinaten, gilt None (Aufrufer fällt dann auf _first_pos/Flugplan zurück)."""
    row = conn.execute(
        "SELECT latitude, longitude, groundspeed FROM live_positions WHERE cid = ?", (cid,)
    ).fetchone()
    if not row or row["latitude"] is None or row["longitude"] is None:
        return None
    return (row["latitude"], row["longitude"], row["groundspeed"])


def transport_event_started(
    conn: sqlite3.Connection, event: dict, callsign_prefix: str = "FRS"
) -> bool:
    """True, sobald ein Friese von einem Streckenflugplatz abgeflogen ist — auch während der Flug
    noch offen ist (kein Disconnect). Der Start-Push darf nicht auf die GPS-Ankunft warten: der
    (Flugplan-)Abflugort an einem Streckenplatz genügt hierfür. (Der Feed selbst rechnet seit dem
    Stapel-Modell rein GPS-basiert — diese Frühabfrage bleibt bewusst flugplan-tolerant.)"""
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
    """True, wenn noch jemand Ware dieses Events trägt — dann muss der Feierabend warten.

    Entscheidung 10 (Spec): Das Event endet erst, wenn alle Ware einen End-Stapel gefunden hat
    (geliefert, zurück, gestohlen, versenkt). Formal ``Summe Flieger-Stapel == 0``.

    Damit entfällt die frühere Streckenprüfung ("gibt es einen offenen Flug, der auf der
    Strecke gestartet ist?") — sie war ein PROXY für "trägt vermutlich noch Ware", der beste,
    den ein Modell ohne Ladungsbegriff hatte. Ein LEERER Pilot hält jetzt nichts mehr auf; ein
    beladener sehr wohl, auch über ``dtend`` hinaus (dann wartet das Event auf seine Ware).

    ``started_before``/``radius_km`` bleiben für die Signatur-Verträglichkeit erhalten und
    werden nicht mehr ausgewertet: Wer Ware trägt, zählt — unabhängig davon, wann er einloggte.
    """
    inp = _stack_inputs(conn, event, _now_utc(), callsign_prefix=callsign_prefix)
    if not inp["destination"]:
        return False
    r = derive_stacks(manifest=inp["manifest"], events=inp["events"],
                      destination=inp["destination"], loading_airports=inp["loading_airports"])
    return any(sum(load.values()) > 0.01 for load in r["onboard"].values())


# Reihenfolge bei gleichem Zeitstempel. Der Logout zuerst (er beendet die Tour — eine Landung im
# selben Moment kann nichts mehr abliefern, Spec). `landing` vor `takeoff`, damit ein Stop-and-Go
# im selben Sample nicht verdreht wird.
_STACK_EVENT_PRIO = {"logout": 0, "login": 1, "landing": 2, "takeoff": 3}


def _sort_stack_events(events: list[dict]) -> list[dict]:
    """Ereignisse chronologisch ordnen; bei gleichem ts entscheidet _STACK_EVENT_PRIO."""
    return sorted(events, key=lambda e: (e["ts"], _STACK_EVENT_PRIO.get(e["kind"], 9), e["cid"]))


# Refile-Splits erkennen: Der Poller schließt eine laufende Verbindung und öffnet sofort eine
# neue, sobald der Flugplan mit GEAENDERTEM Abflugplatz refiled wird (poller.py:832-852). Beide
# Zeilen gehören zu EINER VATSIM-Verbindung — der "Logout" dazwischen ist keiner. Zwei Sekunden
# reichen als Grenze: der Split passiert im selben Poll-Takt (close/open unmittelbar nacheinander),
# ein echter Reconnect braucht länger. Belegter Gegenfall S8 (flights.id 357/358): 2:54 min.
_SESSION_GAP_SEC = 2


def _transport_sessions(conn: sqlite3.Connection, start: str, end: str,
                        callsign_prefix: str) -> list[dict]:
    """VATSIM-Verbindungen, die das Event-Fenster berühren (offene wie geschlossene).

    Der Logout ist ein Ereignis der VERBINDUNG, nicht des Tracks (Spec) — der GPS-Detektor kennt
    keine Verbindungsgrenzen und segmentiert erst bei Lücken > 30 min.

    **Achtung, Refile-Split (Fable-Review 16.07.):** Eine `flights`-Zeile ist KEINE Verbindung.
    Der Poller splittet bei einem Refile mit geändertem Abflugplatz (close_flight + open_flight,
    poller.py:832) — wer unterwegs den Rückflug filed, hätte sonst ein logoff_time IN DER LUFT
    und seine Fracht würde durch eine reine Flugplan-Aenderung versenkt (#23-Verstoß). Solche
    Zeilen werden hier wieder zu einer Verbindung VERKETTET.

    ``logon_time <= end`` begrenzt die TEILNAHME (wer nach dtend einloggt, macht nicht mehr mit);
    die LEGS laufen bewusst bis ``now`` weiter (s. _stack_inputs) — sonst könnte die Ware eines
    kurz vor dtend gestarteten Fluges nie ankommen.

    Jede zurückgegebene Session trägt ``next_logon`` = Start der NÄCHSTEN Verbindung desselben cid
    (auch einer nach dtend eingeloggten, die selbst nicht teilnimmt) oder ``None``. Das ist die
    Obergrenze für die Leg-Zuordnung einer OFFENEN (stale) Session: dort hat sie real geendet.
    Ohne diese Grenze zöge eine stale-offene Zeile ein Leg der Folge-Verbindung an sich und
    zählte dessen Fracht nach Eventende mit (Whole-Branch-Review #1). Deshalb wird die Liste OHNE
    ``logon <= end`` geholt (auch spätere Verbindungen für ``next_logon`) und erst am Ende auf die
    Teilnehmer gefiltert.
    """
    rows = conn.execute(
        "SELECT cid, callsign, aircraft_short AS aircraft, aircraft_icao, logon_time, logoff_time "
        "FROM flights WHERE superseded_by IS NULL AND callsign LIKE ? "
        "AND (logoff_time IS NULL OR logoff_time >= ?) "
        "ORDER BY cid, logon_time",
        (callsign_prefix + "%", start),
    ).fetchall()

    merged: list[dict] = []
    for r in (dict(x) for x in rows):
        prev = merged[-1] if merged else None
        if (prev is not None and prev["cid"] == r["cid"] and prev.get("logoff_time")
                and _gap_seconds(prev["logoff_time"], r["logon_time"]) <= _SESSION_GAP_SEC):
            # Refile-Split: dieselbe Verbindung läuft weiter. Das Ende der neuen Zeile gilt,
            # das Muster ebenso (der Pilot kann beim Refile den Typ gewechselt haben).
            prev["logoff_time"] = r.get("logoff_time")
            prev["aircraft"] = r.get("aircraft") or prev.get("aircraft")
            prev["aircraft_icao"] = r.get("aircraft_icao") or prev.get("aircraft_icao")
            continue
        merged.append(r)
    merged.sort(key=lambda s: (s["logon_time"], s["cid"]))
    # next_logon je Session (aus der VOLLEN Liste, vor dem Teilnehmer-Filter berechnet).
    for i, s in enumerate(merged):
        s["next_logon"] = next((t["logon_time"] for t in merged[i + 1:] if t["cid"] == s["cid"]), None)
    # TEILNAHME: nur Verbindungen, die spätestens bei window_end (= end) eingeloggt haben.
    return [s for s in merged if (s["logon_time"] or "") <= end]


def _gap_seconds(a: str, b: str) -> float:
    """Sekunden zwischen zwei ISO-Zeitstempeln (b - a); inf bei unlesbaren Werten."""
    try:
        return (_parse_iso(b) - _parse_iso(a)).total_seconds()
    except (ValueError, AttributeError, TypeError):
        return float("inf")


def _covered_by_session(sessions: list[dict], cid: int, takeoff: str | None) -> bool:
    """Deckt eine echte VATSIM-Verbindung dieses Leg ab? (StatSim-Doppelzählung verhindern.)

    canonicalize_legs verwirft StatSim-Legs, die einen FriesenSpy-Flug DESSELBEN cid überlappen,
    bereits selbst (database.py:2499 ff.) — aber nur PRO FLUG, ein unüberdeckter Rest überlebt
    bewusst (z. B. nach einem FS-Absturz). Dieser Test hält die Ereignis-Erzeugung dazu konsistent.
    """
    if not takeoff:
        return False
    for s in sessions:
        if int(s["cid"]) != cid:
            continue
        if (s.get("logon_time") or "") <= takeoff <= (s.get("logoff_time") or "9999"):
            return True
    return False


def _stack_inputs(conn: sqlite3.Connection, event: dict, now: str, *,
                  callsign_prefix: str = "FRS") -> dict:
    """Die Eingänge für :func:`app.transport_stacks.derive_stacks` aus der DB holen.

    Liefert ``{manifest, events, loading_airports, destination, legs_by_cid, sessions}``.
    Reine Uebersetzung — die Regeln stehen in transport_stacks.py, hier wird nur gelesen und
    sortiert. ``legs_by_cid``/``sessions`` reicht der Feed-Bau (compute_transport_progress)
    weiter, damit canonicalize_legs nur EINMAL läuft.
    """
    from app.geo import icao_to_coords

    dest = normalize_type_code(event.get("destination"))
    route_set = {c for c in (normalize_type_code(x) for x in (event.get("route") or "").split(",")) if c}
    loading = route_set - {dest}
    coords_map = {icao: icao_to_coords(icao) for icao in route_set}
    radius = _BUMMEL_AIRPORT_RADIUS_KM
    payload_map = get_payload_map(conn)
    default_kg = transport_default_payload_kg(conn)

    manifest = [
        {"name": c["name"], "target_kg": float(c["target_kg"] or 0.0),
         "departure": (c.get("departure") or "").upper(),
         "per_flight_max_kg": c.get("per_flight_max_kg"),
         "emoji": c.get("emoji"),
         "added_at": c.get("added_at")}   # ab wann ladbar (derive_stacks) — sonst rückwirkendes Nachladen
        for c in get_transport_cargo(conn, int(event["id"]))
    ]

    start = event.get("dtstart") or ""
    window_end = min(now, event.get("dtend") or now)   # begrenzt die TEILNAHME (Sessions)
    load_start = _shift_iso(start, hours=-_BUMMEL_EARLY_START_LOOKBACK_H)

    # LEGS laufen bis `now`, NICHT bis dtend: canonicalize_legs filtert takeoff > end
    # (database.py:2573) — mit dtend als Grenze könnte die Ware eines kurz vor Schluss
    # gestarteten Fluges nie ankommen (Entscheidung 10 verspricht das Gegenteil). Der Altcode
    # löste dasselbe mit einem ZWEITEN canonicalize_legs-Aufruf (database.py:5344); hier
    # reicht einer.
    legs = canonicalize_legs(conn, start=load_start, end=now, callsign_prefix=callsign_prefix)
    legs = [g for g in legs if (g.get("logoff_time") or now) >= start]   # nichts vor dem Fenster
    legs_by_cid: dict[int, list[dict]] = {}
    for leg in legs:
        if leg.get("cid") is None:
            continue
        legs_by_cid.setdefault(int(leg["cid"]), []).append(leg)
    for rows in legs_by_cid.values():
        rows.sort(key=lambda x: x.get("logon_time") or "")

    sessions = _transport_sessions(conn, start, window_end, callsign_prefix)
    out: list[dict] = []
    for s in sessions:
        cid = int(s["cid"])
        lo = s.get("logon_time") or ""
        lf = s.get("logoff_time")
        type_code = normalize_type_code(s.get("aircraft_icao")) or normalize_type_code(s.get("aircraft"))
        cap = round(payload_map.get(type_code, default_kg), 1)

        # Obergrenze der Session für die Leg-/Positions-Zuordnung: geschlossen → ihr logoff;
        # OFFEN → Start der nächsten Verbindung (next_logon, s. _transport_sessions), sonst now.
        # Eine stale-offene Zeile zöge sonst ein Leg der Folge-Verbindung an sich und zählte
        # dessen Fracht nach Eventende mit (Whole-Branch-Review #1). Ein Leg, das NACH dtend
        # abhebt, aber noch zu DIESER (vor dtend eingeloggten) Verbindung gehört, bleibt drin
        # (Entscheidung 10) — die Grenze ist die Folge-Verbindung, nicht dtend.
        nl = s.get("next_logon")
        sess_end = lf if lf else (nl or now)
        # Legs DIESER Session: Takeoff liegt in [logon, sess_end].
        own = [g for g in legs_by_cid.get(cid, [])
               if lo <= (g.get("logon_time") or "") <= sess_end]

        # NUR echte GPS-Legs sind Flüge (#23). canonicalize_legs hat einen Fallback ohne GPS
        # (_flightrow_as_flight, database.py:2614-2623): erkennt der Detektor für eine cid im
        # ganzen Fenster kein Leg, wird jede geschlossene Nicht-Ghost-`flights`-Zeile zum "Leg"
        # — mit dem Connection-Login als logon_time und dem Connection-Logout als logoff_time.
        # Daraus takeoff/landing zu bauen hieße, Flugereignisse aus einer Flugplan-Zeile zu
        # ERFINDEN. Merkmal ist `block_start`: _gps_flights_for_positions setzt es bei jedem
        # erkannten Leg (database.py:2368), _flightrow_as_flight nie — und weitere Leg-Quellen
        # hat canonicalize_legs nicht. (`gps_departure is None and gps_arrival is None` wäre
        # UNSCHARF: ein echtes Leg darf beide None haben, wenn Start und Landung außerhalb
        # jedes bekannten Platz-Radius liegen — nearest_airport gibt dann None, gps_legs.py:195
        # und :158.)
        real = [g for g in own if "block_start" in g]

        # --- Login-Ort (GPS-only, kein Flugplan-Fallback) ---
        airport = None
        if real and real[0].get("gps_departure"):
            # 1. Das erste Leg kennt seinen eigenen Startplatz — gilt auch, wenn der Pilot beim
            #    ersten Poll schon rollte (gs > 2). Eine reine gs<2-Prüfung würde ihn hier
            #    fälschlich als "nicht am Platz" werten und seine Fracht still verlieren.
            #    Ohne gps_departure (Spawn abseits jedes Platzes, Fallback-Leg) gilt Regel 2 —
            #    sonst stürbe die Boden-Beladung (#5, v8.22.0) hier still.
            airport = normalize_type_code(real[0].get("gps_departure")) or None
        else:
            # 2. Er steht nur da (kein Leg): aktuelle Live-Position, sonst die erste der Session.
            #    Am Boden = gs < _BLOCK_GS_KT — exakt die heutige Boden-Beladung (#5, v8.22.0).
            #    Die Live-Position gilt nur für die WIRKLICH offene (letzte) Session — hat sie eine
            #    Folge-Verbindung (nl), ist sie stale und die Live-Position gehört schon der
            #    nächsten Verbindung; dann zählt nur die Position bis sess_end (Review #1).
            gpos = _current_pos(conn, cid) if (lf is None and not nl) else None
            if gpos and gpos[2] is not None and gpos[2] < _BLOCK_GS_KT:
                airport = _nearest_airport(coords_map, (gpos[0], gpos[1]), radius)
            else:
                row = conn.execute(
                    "SELECT latitude, longitude, groundspeed FROM position_history "
                    "WHERE cid=? AND ts>=? AND ts<=? ORDER BY ts ASC LIMIT 1",
                    (cid, lo, sess_end),
                ).fetchone()
                if row is not None and row["groundspeed"] is not None \
                        and row["groundspeed"] < _BLOCK_GS_KT:
                    airport = _nearest_airport(coords_map, (row["latitude"], row["longitude"]), radius)
        if airport not in route_set:
            airport = None      # kein teilnehmender Platz -> in der Luft/anderswo eingeloggt

        out.append({"ts": lo, "kind": "login", "cid": cid, "airport": airport, "capacity_kg": cap})
        for g in real:
            out.append({"ts": g["logon_time"], "kind": "takeoff", "cid": cid,
                        "airport": None, "capacity_kg": cap})
            if g.get("logoff_time"):     # abgeschlossenes Leg = Landung erkannt
                out.append({"ts": g["logoff_time"], "kind": "landing", "cid": cid,
                            "airport": normalize_type_code(g.get("gps_arrival")) or None,
                            "capacity_kg": cap})
        # Effektives Session-Ende für den Logout: geschlossen -> ihr logoff; stale-OFFEN (hat eine
        # Folge-Verbindung, next_logon) -> deren Login. Dort war der Pilot NACHWEISLICH weg und
        # wieder da; die Bordladung fällt real an dieser Stelle ab (derive_stacks lässt sie sonst
        # erst beim Folge-Login abfallen, _drop_load auf login). OHNE synthetischen Logout hätte
        # die stale-offene Verbindung keinen logout_ts, und der Feed fände die Verlust-Bewegung
        # nicht (sie stünde am Folge-Login-ts) -> die Verlust-Zeile fiele still aus losses[] und
        # participants.lost_kg, obwohl lost_total_kg stimmt (Whole-Branch-Review #2). Die WIRKLICH
        # offene letzte Verbindung (kein next_logon) bleibt ohne Logout — der Pilot fliegt noch.
        lf_eff = lf or nl
        if lf_eff:
            # Der Logout darf NIE vor oder auf der eigenen Landung liegen: bei gleichem ts gewinnt
            # laut _STACK_EVENT_PRIO der Logout, fände position=None vor (der takeoff hat sie
            # geleert) und würde die Ladung VERSENKEN statt sie abzuliefern.
            # Warum kollidieren beide auf einer Sekunde? poller.py:891 schließt den Flug mit
            # `close_flight(conn, id, last_pos)`, wobei last_pos = MAX(ts) aus position_history —
            # logoff_time IST also das letzte GPS-Sample, keine eigene Uhr. Wer landet, bis zum
            # Stillstand ausrollt und dann im selben Poll-Takt (15 s) die Verbindung verliert, hat
            # logoff_time == landing_ts EXAKT. Das ist NICHT der Normalfall (normal rollt man ans
            # Gate und loggt viel später aus, logoff_time liegt dann weit nach der Landung) —
            # es ist der seltene TOUCHDOWN-DISCONNECT AM ZIEL. Belegt an echten Daten (16.07.,
            # Migration gegen Prod-Kopie): FRS49 in Event #1 landet sauber in EDXH und verliert im
            # Stillstand-Takt die Verbindung; MIT diesem +1s liefert er 316 kg, OHNE ihn werden alle
            # 316 kg versenkt. Deshalb: eine Sekunde nach der Landung, synthetisch.
            # NUR Landungen, die auf oder VOR dem Logout liegen, können überhaupt eine
            # Poll-Takt-Kollision sein. `own` begrenzt nur logon_time (s. o.), nicht
            # logoff_time: ein Leg, das INNERHALB der Session abhebt und erst NACH ihrem
            # Logout landet (S8 — Logout in der Luft, Re-Login nach 2:54 min, der Detektor
            # sieht ein durchgehendes Leg), stünde sonst hier als "letzte Landung" und schöbe
            # den Logout weit nach vorn, aus der Session heraus. Der Pilot verschwände dann
            # mitten in Session 2 aus `position` und lieferte 0 kg.
            ts_logout = lf_eff
            letzte_landung = max((g["logoff_time"] for g in real
                                  if g.get("logoff_time")
                                  and _parse_iso(g["logoff_time"]) <= _parse_iso(lf_eff)),
                                 default=None)
            if letzte_landung and _parse_iso(ts_logout) <= _parse_iso(letzte_landung):
                ts_logout = (_parse_iso(letzte_landung) + timedelta(seconds=1)
                             ).strftime("%Y-%m-%dT%H:%M:%SZ")
            # Der EFFEKTIVE Logout-Zeitstempel (nach dem +1s-Shift) an der Session vermerken.
            # derive_stacks stempelt die Verlust-Bewegung (returned/stolen/sunk) mit GENAU diesem
            # ts; der Feed-Bau in compute_transport_progress muss danach suchen — nicht nach
            # `logoff_time`, das beim Touchdown-Disconnect um 1 s daneben liegt (dann fiele die
            # Verlust-Zeile still aus dem Feed, obwohl die Stapel-Zahlen stimmen).
            s["logout_ts"] = ts_logout
            out.append({"ts": ts_logout, "kind": "logout", "cid": cid,
                        "airport": None, "capacity_kg": cap})

    # --- StatSim-Legs: Backfill bei Poller-/VPS-Ausfall (Nutzer-Entscheidung 16.07.) ---
    # Sie haben KEINE flights-Zeile (eigene Tabellen, database.py:107-130) und würden sonst
    # still 0 kg liefern, obwohl sie heute mitzählen. Behandlung: wie ein normaler Flug — der
    # Flug ist vorbei, also gehört ein Logout am Landeort dazu.
    session_cids = {int(s["cid"]) for s in sessions}
    statsim_sessions: list[dict] = []
    for cid, rows in legs_by_cid.items():
        for g in rows:
            # `block_start` auch hier: eine statsim_cache-Zeile mit duration_min > 5, aber ohne
            # verwertbaren Track, fällt in canonicalize_legs ebenfalls auf _flightrow_as_flight
            # zurück (database.py:2711) — und die statsim_id allein trennt das NICHT ab, denn
            # der Fallback setzt sie sehr wohl (:2401), nur block_start nicht. Ohne diese
            # Prüfung entstünden hier takeoff (Connection-Login) und landing
            # (Connection-Logout) aus einer reinen Flugplan-Zeile — derselbe #23-Verstoß wie
            # in der Sessions-Schleife oben.
            if not g.get("statsim_id") or "block_start" not in g:
                continue
            if cid in session_cids and _covered_by_session(sessions, cid, g.get("logon_time")):
                continue     # eine echte Verbindung deckt dieses Leg ab -> kein Doppel
            type_code = normalize_type_code(g.get("aircraft_icao")) or normalize_type_code(g.get("aircraft"))
            cap = round(payload_map.get(type_code, default_kg), 1)
            dep = normalize_type_code(g.get("gps_departure")) or None
            out.append({"ts": g["logon_time"], "kind": "login", "cid": cid,
                        "airport": dep if dep in route_set else None, "capacity_kg": cap})
            out.append({"ts": g["logon_time"], "kind": "takeoff", "cid": cid,
                        "airport": None, "capacity_kg": cap})
            logout_ts = None
            if g.get("logoff_time"):
                arr = normalize_type_code(g.get("gps_arrival")) or None
                out.append({"ts": g["logoff_time"], "kind": "landing", "cid": cid,
                            "airport": arr, "capacity_kg": cap})
                # Der Logout MUSS nach der Landung liegen: bei gleichem ts gewinnt laut
                # _STACK_EVENT_PRIO der Logout — er fände dann position=None vor und würde die
                # Ladung VERSENKEN statt sie abzuliefern. Eine Sekunde später, synthetisch.
                logout_ts = (_parse_iso(g["logoff_time"]) + timedelta(seconds=1)
                             ).strftime("%Y-%m-%dT%H:%M:%SZ")
                out.append({"ts": logout_ts, "kind": "logout", "cid": cid,
                            "airport": None, "capacity_kg": cap})
            # Pseudo-Session je StatSim-Leg (Whole-Branch-Review #3): Feed + Teilnehmer werden aus
            # `sessions` gebaut; ohne einen Session-Eintrag fiele der StatSim-Pilot aus flights[]
            # und participants[], obwohl seine Lieferung in total_kg zählt. `statsim_only` markiert
            # ihn als NICHT-live (Backfill, keine VATSIM-Verbindung im Poller) — der Live-Block
            # bleibt so FriesenSpy-only (index.html, fetchKutterActive filtert danach). Angehängt
            # NACH `session_cids`/der Sessions-Schleife: die Event-Erzeugung oben läuft nur über die
            # echten Sessions, hier werden die Ereignisse direkt erzeugt (kein Doppel).
            statsim_sessions.append({
                "cid": cid, "callsign": g.get("callsign") or f"{callsign_prefix}{cid}",
                "aircraft": g.get("aircraft"), "aircraft_icao": g.get("aircraft_icao"),
                "logon_time": g.get("logon_time"), "logoff_time": g.get("logoff_time"),
                "next_logon": None, "logout_ts": logout_ts, "statsim_only": True,
            })

    return {
        "manifest": manifest,
        "events": _sort_stack_events(out),
        "loading_airports": loading,
        "destination": dest,
        "legs_by_cid": legs_by_cid,
        "sessions": sessions + statsim_sessions,
    }


def compute_transport_progress(
    conn: sqlite3.Connection,
    event: dict,
    now: str,
    *,
    callsign_prefix: str = "FRS",
    radius_km: float | None = None,
    skip_open_probe: bool = False,
) -> dict:
    """Live-Fortschritt eines FriesenKutter-Events — Stapel-Modell (Spec 2026-07-15).

    Ladung ist ein BESTAND mit einem Ort, kein Attribut eines Legs: Das Manifest liegt als
    Stapel an seinen Ladeplätzen; wer am Boden an einem Ladeplatz steht, lädt; wer am Ziel
    landet, liefert; wer ausloggt, gibt zurück / bestiehlt / versenkt. Die Regeln stehen
    vollständig in :mod:`app.transport_stacks`, die DB-Uebersetzung in :func:`_stack_inputs` —
    diese Funktion formt nur noch das Ergebnis in den API-Vertrag.

    **Erhaltungssatz:** Summe Stapel + Summe Ladung == Summe Manifest. Ware entsteht nicht und
    verschwindet nicht; ``total_kg`` kann den Balken daher nicht überzeichnen (#63).

    ``radius_km`` und ``skip_open_probe`` werden nur noch für die Signatur-Verträglichkeit
    angenommen und **ignoriert**:

    * ``radius_km`` — der Anwesenheitsradius ist seit #23 global (``_BUMMEL_AIRPORT_RADIUS_KM``).
    * ``skip_open_probe`` (#66) hatte zwei Gründe, beide entfallen. (1) Kosten: Es sparte den
      ZWEITEN ``canonicalize_legs``-Aufruf — hier läuft nur einer. (2) Richtigkeit: Es verhinderte,
      dass der Freeze eine ``in_air``-Zeile für immer als "unterwegs" einfriert. Das kann nicht
      mehr passieren, weil das Modell es selbst ausschließt: Eingefroren wird erst, wenn niemand
      mehr Ware trägt (Entscheidung 10, :func:`transport_anyone_in_progress`) — und eine
      ``in_air``-Zeile entsteht nur MIT Ware an Bord. Es gibt also nichts wegzufiltern.

    (Ein Filter wäre hier sogar schädlich gewesen: pro CID statt pro Session gefiltert, hätte
    er dem Piloten, der eben geliefert hat und noch online am Ziel parkt, seine ganze Tonnage aus
    dem Snapshot gelöscht — Fable-Review 16.07.)
    """
    inp = _stack_inputs(conn, event, now, callsign_prefix=callsign_prefix)
    manifest, dest = inp["manifest"], inp["destination"]
    route_set = {c for c in (normalize_type_code(x) for x in (event.get("route") or "").split(",")) if c}
    payload_map = get_payload_map(conn)
    default_kg = transport_default_payload_kg(conn)
    if not dest:
        # Ohne Ziel gibt es keinen Ziel-Stapel — und eine Landung mit unerkanntem Platz
        # (airport=None) würde sonst `airport == destination` erfüllen und ins Nichts liefern.
        return _empty_transport_progress(event, route_set, manifest)

    r = derive_stacks(manifest=manifest, events=inp["events"], destination=dest,
                      loading_airports=inp["loading_airports"])
    stacks, onboard = r["stacks"], r["onboard"]
    carried_at = r["carried"]   # Bordladung je Abheben (cid, logon_time) — für die Zwischenleg-Anzeige

    # --- Bewegungen je Leg/Session zuordnen (Feed) ---
    delivered_by: dict[tuple[int, str], list[dict]] = {}
    loss_by: dict[tuple[int, str], list[dict]] = {}
    for m in r["movements"]:
        key = (m["cid"], m["ts"])
        if m["kind"] == "deliver":
            delivered_by.setdefault(key, []).append(m)
        elif m["kind"] in ("returned", "stolen", "sunk"):
            loss_by.setdefault(key, []).append(m)

    emoji_of = {c["name"]: c.get("emoji") for c in manifest}

    # Herkunfts-Ladeplatz je Frachtart (Manifest-`departure`). Ware entsteht nur an ihrem
    # Ladeplatz — das ist der echte Start einer verlorenen/zurückgebrachten Ware. Gleicher Name an
    # mehreren Plätzen → uneindeutig (None). Damit trennen wir „geflogen" (Ladeplatz ≠ Abfallort)
    # von „am Platz geladen und zurück" (Ladeplatz == Abfallort, Phantom, nie transportiert).
    _deps_by_name: dict[str, set] = {}
    for c in manifest:
        d = (c.get("departure") or "").upper()
        if d:
            _deps_by_name.setdefault(c["name"], set()).add(d)
    cargo_departure = {n: (next(iter(ds)) if len(ds) == 1 else None) for n, ds in _deps_by_name.items()}

    def _loss_origin(ms: list[dict]) -> str | None:
        ds = {cargo_departure.get(m["name"]) for m in ms}
        ds.discard(None)
        return next(iter(ds)) if len(ds) == 1 else None

    # cids, deren Ware wirklich GEFLOGEN ist (geliefert/getragen/geklaut/versenkt/an anderem Platz
    # zurückgegeben) — der `contributed`-Marker fürs Badge. Eine reine Am-Platz-Rückgabe zählt NICHT.
    flew_cargo_cids: set[int] = set()

    def _lines(ms: list[dict]) -> list[dict]:
        agg: dict[str, float] = {}
        for m in ms:
            agg[m["name"]] = agg.get(m["name"], 0.0) + m["kg"]
        return [{"name": n, "emoji": emoji_of.get(n), "kg": round(kg, 1)}
                for n, kg in sorted(agg.items(), key=lambda kv: kv[1], reverse=True)]

    names = {}
    cids = {int(s["cid"]) for s in inp["sessions"]}
    if cids:
        rows = conn.execute(
            "SELECT cid, name FROM pilots WHERE cid IN (%s)" % ",".join("?" * len(cids)),
            list(cids),
        ).fetchall()
        names = {r["cid"]: (r["name"] or "") for r in rows}

    unmapped: set[str] = set()
    network: list[dict] = []
    for s in inp["sessions"]:
        cid = int(s["cid"])
        type_code = normalize_type_code(s.get("aircraft_icao")) or normalize_type_code(s.get("aircraft"))
        if type_code and type_code not in payload_map:
            unmapped.add(type_code)
        cap = round(payload_map.get(type_code, default_kg), 1)
        # NUR echte GPS-Legs (block_start gesetzt) gehören in den Feed — ein Fallback-Leg
        # (_flightrow_as_flight, kein block_start) ist eine reine Flugplan-Zeile ohne Track und
        # damit kein Kutter-Flug (#23). Der Feed ist der DRITTE canonicalize_legs-Konsument nach
        # _stack_inputs' Sessions- und StatSim-Block; alle drei erkennen das Fehlen von block_start
        # selbst (canonicalize_legs markiert seine Fallback-Legs nicht).
        # Obergrenze = Sessionende (offen → Start der Folge-Verbindung, sonst now) — dieselbe
        # Deckelung wie in _stack_inputs (Review-Fund #1): sonst zeigt der Feed einen Phantom-Flug
        # einer stale-offenen Session, dessen Leg zur Folge-Verbindung nach Eventende gehört.
        _lo = s.get("logon_time") or ""
        _lf = s.get("logoff_time")
        _sess_end = _lf if _lf else (s.get("next_logon") or now)
        own = [g for g in inp["legs_by_cid"].get(cid, [])
               if "block_start" in g
               and _lo <= (g.get("logon_time") or "") <= _sess_end]

        # `own` enthält auch den LAUFENDEN (noch offenen) Flug dieser wirklich offenen Verbindung.
        # WURZEL des V10-Funds: Die Fracht einer Leg-Zeile kam aus `delivered_by` (Lieferungen) —
        # und Lieferungen entstehen ERST bei der Landung. Ein noch fliegender Flug hatte also 0 →
        # „leer", obwohl er im Stapel-Modell die Ware TRÄGT. Deshalb bekommt der laufende beladene
        # Flug seine Fracht DIREKT aus der Bordladung (`onboard`, die Modell-Wahrheit) auf die echte
        # Leg-Zeile (dep = GPS-Start, arr = Ziel, reserved = Bordladung) — keine leere Zeile, keine
        # separate Reservierungs-Zeile. Gelandet zeigt die Zeile weiter das Gelieferte; LEER fliegend
        # ihre normale Strecke. Ein Flug = eine Zeile, eine Wahrheit.
        _open_sess = (not _lf) and (not s.get("next_logon")) and (not s.get("statsim_only"))
        _aboard_now = round(sum((onboard.get(cid) or {}).values()), 1) if _open_sess else 0.0
        _has_open_leg = any(not g.get("logoff_time") for g in own)

        for g in own:
            dep = normalize_type_code(g.get("gps_departure"))
            arr = normalize_type_code(g.get("gps_arrival"))
            if _open_sess and not g.get("logoff_time") and _aboard_now > 0.01:
                # Laufender beladener Flug: die BORDLADUNG ist die Fracht dieser Zeile (nicht das
                # noch nicht Gelieferte). Start = echter GPS-Start; fehlt er (Spawn abseits), der
                # letzte Bodenkontakt (GPS-Faktum, kein Flugplan-Vertrauen, #23). Ziel = Event-Ziel.
                load = onboard.get(cid) or {}
                where = r["position"].get(cid)
                network.append({
                    "dep_time": g.get("logon_time") or "", "cid": cid,
                    "callsign": g.get("callsign") or s.get("callsign") or "",
                    "name": names.get(cid, ""), "aircraft": s.get("aircraft") or type_code,
                    "dep": dep or r["last_ground"].get(cid) or "", "arr": dest,
                    "tonnage_kg": 0.0, "onboard_kg": _aboard_now,
                    "loaded": False,
                    "cargo_lines": [{"name": n, "emoji": emoji_of.get(n), "kg": round(kg, 1)}
                                    for n, kg in load.items() if kg > 0.01],
                    "cargo_name": max(load, key=load.get),
                    "in_air": True, "airborne": where is None,
                    "reserved_kg": _aboard_now, "onboard_reserved_kg": cap,
                    "flight_key": f"{cid}:{g.get('logon_time') or ''}",
                    "distance_nm": g.get("distance_nm") or 0,
                    "block_min": g.get("block_min") or g.get("duration_min") or 0,
                })
                continue
            # Bordladung DIESES Legs = Modell-Wahrheit aus dem Stapel-Replay: `ladung {cid: {…}}`,
            # die „an Bord bleibt" (Spec 2026-07-15). `carried_at` ist der Snapshot beim Abheben und
            # damit die EINZIGE Frachtquelle je Leg — zwischen Start und Landung lädt ein Leg nichts
            # nach. Der Feed zeigt schlicht, was das Flugzeug auf diesem Leg trug — egal ob am Ende
            # geliefert. `delivered_by` sagt nur noch, OB am Ziel geliefert wurde (dort geht der ganze
            # Flieger-Stapel rüber = genau diese Bordladung), es ist KEINE zweite Frachtquelle.
            # (Früher primär `delivered_by` + `carried_at` nur als Fallback `if tonnage<=0` — ein
            # Sonderfall über sechs Felder verstreut; ein Zwischenleg erschien „leer". Fund Michael 19.07.)
            onboard_here = carried_at.get((cid, g.get("logon_time") or "")) or {}
            cargo_lines = _lines([{"name": n, "kg": kg} for n, kg in onboard_here.items() if kg > 0.01])
            onboard_kg = round(sum(kg for kg in onboard_here.values() if kg > 0.01), 1)
            delivered = bool(delivered_by.get((cid, g.get("logoff_time") or "")))  # am Ziel gelandet
            # Feed-Filter = reine SICHTBARKEIT (ersetzt den alten Streckenfilter, der BEIDE
            # Enden auf der Route verlangte und deshalb vom Latch aufgehoben werden musste).
            if not (dep in route_set or arr in route_set or onboard_kg > 0):
                continue
            row = {
                "dep_time": g.get("logon_time") or "", "cid": cid,
                "callsign": g.get("callsign") or s.get("callsign") or "",
                "name": names.get(cid, ""), "aircraft": s.get("aircraft") or type_code,
                "dep": dep, "arr": arr,
                # In die Teilnehmer-Bilanz (delivered_kg) zählt nur Geliefertes; Getragenes zählt 0.
                "tonnage_kg": onboard_kg if delivered else 0.0, "onboard_kg": onboard_kg,
                "loaded": delivered,
                "cargo_lines": cargo_lines,
                "cargo_name": cargo_lines[0]["name"] if cargo_lines else None,
                "in_air": False, "airborne": False,
                # Getragenes Zwischenleg: die Bordladung ist „schwebend" (noch nicht geliefert).
                "reserved_kg": onboard_kg if not delivered else 0.0,
                "onboard_reserved_kg": cap if (not delivered and onboard_kg > 0.0) else 0.0,
                "carried_through": (not delivered) and onboard_kg > 0.0,
                "flight_key": f"{cid}:{g.get('logon_time') or ''}",
                "distance_nm": g.get("distance_nm") or 0,
                "block_min": g.get("block_min") or g.get("duration_min") or 0,
            }
            network.append(row)

        # Verlust-Zeile (Logout mit Ware an Bord). Sie gehört an das LETZTE Leg DIESER Session —
        # `next(reversed(network) if cid == …)` wäre falsch: es fischt quer über Sessions und
        # könnte eine bereits mit einem Verlust behaftete Zeile überschreiben (aus zwei
        # Rückgaben würde eine, Fable-Review 16.07.).
        # Verlust am effektiven Logout-ts suchen (nach dem +1s-Shift, den _stack_inputs an der
        # Session vermerkt) — beim Touchdown-Disconnect liegt er 1 s hinter `logoff_time`.
        ls = loss_by.get((cid, s.get("logout_ts") or s.get("logoff_time") or ""), [])
        if ls:
            kind = ls[0]["kind"]
            lost = round(sum(m["kg"] for m in ls), 1) if kind in ("stolen", "sunk") else 0.0
            origin = _loss_origin(ls)             # Herkunfts-Ladeplatz der Ware (Manifest)
            drop = ls[0].get("airport")           # Ort der Rückgabe/des Verlusts (None = in der Luft)
            own_keys = {f"{cid}:{g.get('logon_time') or ''}" for g in own}
            target = next((q for q in reversed(network)
                           if q["flight_key"] in own_keys and not q["loaded"]
                           and not q.get("loss_kind")), None)
            # Trug DIESER Leg die Ware wirklich? Zwei Bedingungen, beide nötig:
            # (1) Das Leg hob mit Ladung an Bord ab (`onboard_kg > 0`, der `carried_at`-Snapshot beim
            #     Takeoff). Ein LEER abgehobenes Leg hat nie etwas getragen — die Ware wurde erst NACH
            #     der Landung geladen und am selben Platz zurückgegeben (Touchdown-Disconnect): reine
            #     Am-Platz-Rückgabe, gehört an KEIN Leg. Das ist der harte physische Diskriminator und
            #     greift auch, wenn die Herkunft mehrdeutig ist (namensgleiche Ware an zwei Plätzen →
            #     `origin` None, #238-Live-Fund 20.07.: das leere Anflug-Leg bekam sonst die Rückgabe).
            # (2) Startete der Leg an IHREM Ladeplatz (leg.dep == origin) — dann ist sie geflogen (auch
            #     der Rundflug EDWG→…→EDWG!). Bei mehrdeutiger Herkunft (origin None) trägt (1) allein.
            # Klau/Versenken sind IMMER geflogen und bleiben an ihrem Leg.
            carried_return = (kind == "returned" and target is not None
                              and target.get("onboard_kg", 0.0) > 0.01
                              and (origin is None or target.get("dep") == origin))
            flew = kind in ("stolen", "sunk") or carried_return
            attach = target if flew else None
            if flew:
                flew_cargo_cids.add(cid)          # geflogen → zählt fürs Badge (`contributed`)
            if attach is not None:
                attach["loss_kind"], attach["lost_kg"] = kind, lost
                attach["cargo_lines"] = _lines(ls)
                attach["cargo_name"] = attach["cargo_lines"][0]["name"]
            elif kind in ("stolen", "sunk"):
                # Klau/Versenken OHNE passenden Leg: echter kg-Verlust, MUSS sichtbar bleiben —
                # als eigene Zeile (Start = Herkunfts-Ladeplatz, sonst der Ort; in der Luft „—").
                network.append({
                    "dep_time": s.get("logon_time") or "", "cid": cid,
                    "callsign": s.get("callsign") or "", "name": names.get(cid, ""),
                    "aircraft": s.get("aircraft") or type_code,
                    "dep": origin or drop or "", "arr": drop or "—",
                    "tonnage_kg": 0.0, "loaded": False, "in_air": False, "airborne": False,
                    "reserved_kg": 0.0, "cargo_lines": _lines(ls),
                    "cargo_name": _lines(ls)[0]["name"],
                    "flight_key": f"{cid}:{s.get('logon_time') or ''}",
                    "distance_nm": 0, "block_min": 0, "loss_kind": kind, "lost_kg": lost,
                })
            # else: reine Am-Platz-Rückgabe (Ladeplatz == Abfallort, kein Trage-Flug) = STILLE
            # Stapel-Buchung. Das ist KEIN Leg, KEIN Flug → keine Feed-Zeile, kein Flugzähler-Eintrag
            # (Nutzer-Prinzip: als Flug zählt NUR, was canonicalize_legs als echtes Leg erfasst). Der
            # Erhaltungssatz hält trotzdem — derive_stacks legt die Ware sowieso auf den Stapel zurück,
            # unabhängig von der Anzeige.

        # Beladen am Boden, aber NOCH NICHT abgehoben (kein offener Leg): dieser Fall hat keine
        # GPS-Leg-Zeile, deshalb zeigt ihn diese synthetische Zeile. Der laufende beladene Flug MIT
        # Leg trägt seine Bordladung dagegen schon auf der Leg-Zeile oben (`_aboard_now`-Zweig) —
        # deshalb `not _has_open_leg`, sonst wäre er wieder doppelt. NUR die WIRKLICH offene letzte
        # Verbindung (kein next_logon) darf diese Zeile bekommen — eine stale-offene Verbindung
        # (Folge-Login vorhanden) hat real geendet, ihre Ladung ist bereits am synthetischen Logout
        # abgefallen. `onboard` ist zudem cid-keyed (der Endzustand): OHNE die next_logon-Sperre läse
        # die stale-offene Zeile die Bordladung der FOLGE-Verbindung und erfände einen Phantom-Flug.
        load = onboard.get(cid) or {}
        aboard = round(sum(load.values()), 1)
        if not s.get("logoff_time") and not s.get("next_logon") \
                and not s.get("statsim_only") and aboard > 0.0 and not _has_open_leg:
            # Am Boden ist `where` gesetzt (der Ladeplatz); last_ground als Rückfall (GPS-Faktum,
            # kein Flugplan-Vertrauen, #23). Ziel = Event-Ziel → z. B. „EDWZ → EDWS".
            where = r["position"].get(cid)
            network.append({
                "dep_time": s.get("logon_time") or "", "cid": cid,
                "callsign": s.get("callsign") or "", "name": names.get(cid, ""),
                "aircraft": s.get("aircraft") or type_code,
                "dep": where or r["last_ground"].get(cid) or "", "arr": dest,
                "tonnage_kg": 0.0, "loaded": False,
                "in_air": True, "airborne": where is None,
                "reserved_kg": aboard, "onboard_reserved_kg": cap,
                "cargo_lines": [{"name": n, "emoji": emoji_of.get(n), "kg": round(kg, 1)}
                                for n, kg in load.items() if kg > 0.01],
                "cargo_name": max(load, key=load.get) if aboard > 0 else None,
                "flight_key": f"{cid}:{s.get('logon_time') or ''}",
                "distance_nm": 0, "block_min": 0,
            })

    quips = get_transport_quips(conn, int(event["id"]))
    for q in network:
        q["quip"] = quips.get(q["flight_key"])

    # --- Zahlen: direkt aus den Stapeln ---
    cargo_out: list[dict] = []
    for c in manifest:
        n = c["name"]
        delivered = stacks[dest].get(n, 0.0)
        lost = stacks[STOLEN].get(n, 0.0) + stacks[SUNK].get(n, 0.0)
        reserved = sum(l.get(n, 0.0) for l in onboard.values())
        # on_stack_kg: was von DIESER Zeile noch am Startplatz liegt (Rest-Stapel). Das ist die
        # EINZIGE pro-Platz bekannte Zahl bei mehreren Zeilen desselben Namens — geliefert/verloren
        # gibt es nur als Name-Gesamt (die Ware verliert beim Laden ihre Herkunft). Damit kann die
        # Detailansicht ehrlich "noch am Platz / abgeholt" je Platz zeigen (Nutzer-Entscheidung:
        # zusammenfassen statt Herkunft mitzuführen).
        on_stack = stacks.get(c.get("departure") or "", {}).get(n, 0.0)
        cargo_out.append({
            "name": n, "emoji": c.get("emoji"), "target_kg": c["target_kg"],
            "delivered_kg": round(delivered, 1), "reserved_kg": round(reserved, 1),
            "lost_kg": round(lost, 1), "on_stack_kg": round(on_stack, 1),
            "pct": round(100.0 * delivered / c["target_kg"], 1) if c["target_kg"] > 0 else 0.0,
            "per_flight_max_kg": c.get("per_flight_max_kg"),
            "departure": c.get("departure"),
        })

    total_kg = round(sum(stacks[dest].values()), 1)
    lost_total = round(sum(stacks[STOLEN].values()) + sum(stacks[SUNK].values()), 1)
    reserved_total = round(sum(sum(l.values()) for l in onboard.values()), 1)
    target_kg = round(sum(c["target_kg"] for c in manifest), 1) if manifest else None

    # --- Teilnehmer + Sichtbarkeit (Entscheidung 14) ---
    # WICHTIG: parts entsteht aus den SESSIONS, nicht aus dem Feed. Ein Pilot ohne Feed-Zeile ist
    # trotzdem Teilnehmer — der Wartende am leeren Stapel (Entscheidung 13) und der Pilot, der
    # leer am Ziel parkt (Spec-Statustabelle: `🅿️ steht in EDXH · 0 kg`), haben beide kein Leg
    # und keine Ladung. Aus dem Feed gebaut wären sie unsichtbar, obwohl die Sichtbarkeits-
    # formel sie einschließt (Fable-Review 16.07.).
    visible_places = set(inp["loading_airports"]) | {dest}
    parts: dict[int, dict] = {}
    for s in inp["sessions"]:
        cid = int(s["cid"])
        p = parts.setdefault(cid, {
            "cid": cid, "name": names.get(cid, ""), "callsign": s.get("callsign") or "",
            "aircraft": normalize_type_code(s.get("aircraft") or s.get("aircraft_icao") or ""),
            "flights": 0, "delivered_kg": 0.0, "reserved_kg": 0.0, "lost_kg": 0.0,
            "status": "done", "statsim_only": True, "online": False,
        })
        # statsim_only nur, wenn ALLE Verbindungen dieses cid StatSim-Backfill sind — deckt eine
        # echte VATSIM-Verbindung ihn (irgendwo) ab, ist er live und gehört in den Live-Block (#3).
        if not s.get("statsim_only"):
            p["statsim_only"] = False
        # online = mindestens eine ECHT offene Session dieses Piloten: kein logoff_time UND keine
        # Folge-Verbindung (next_logon) — exakt das Kriterium, mit dem _stack_inputs (lf_eff =
        # lf or nl) den wirklich noch verbundenen Piloten von einer stale-offenen Zeile trennt.
        # StatSim-Backfill (keine Live-Verbindung) zählt nie als online. `visible` bleibt die
        # DAUERHAFTE Teilnahme-Sperrklinke (einmal am Ladeplatz → für immer im Event); `online`
        # ist die MOMENTANE Präsenz, damit der Live-Block „aktive Piloten" einen fertig
        # ausgeloggten Leer-Piloten nicht ewig als „dabei" führt (er bleibt in Feed/Bilanz/Badge).
        if not s.get("logoff_time") and not s.get("next_logon") and not s.get("statsim_only"):
            p["online"] = True
    for q in network:
        p = parts.setdefault(int(q["cid"]), {
            "cid": int(q["cid"]), "name": q.get("name") or "", "callsign": q.get("callsign") or "",
            "aircraft": normalize_type_code(q.get("aircraft") or ""), "flights": 0,
            "statsim_only": False, "online": False,
            "delivered_kg": 0.0, "reserved_kg": 0.0, "lost_kg": 0.0, "status": "done",
        })
        p["flights"] += 1
        p["delivered_kg"] += q["tonnage_kg"]
        p["lost_kg"] += q.get("lost_kg") or 0.0
        # reserved_kg NICHT hier aufsummieren — es kommt unten direkt aus der Bordladung
        # (eine Wahrheit, nicht zwei: die Feed-Zeile ist nur eine Sicht auf denselben Stapel).
    for cid, p in parts.items():
        load = onboard.get(cid) or {}
        aboard = sum(load.values())
        where = r["position"].get(cid)
        # sichtbar = letzter Bodenkontakt an einem teilnehmenden Platz ODER Ladung > 0
        # (Entscheidung 14). Kostet kein Feld: beide Werte führt das Modell ohnehin — die
        # Ladung IST der Flieger-Stapel, der letzte Bodenkontakt IST der Logout-Ort.
        p["visible"] = (r["last_ground"].get(cid) in visible_places) or aboard > 0.01
        p["place"] = where          # None = unterwegs; sonst das ICAO, an dem er steht
        # Letzter Landeplatz = Start der Strecke im Live-Block. Anders als `place` bleibt er im
        # Flug erhalten (Start bekannt, auch unterwegs) und wechselt bei jeder Zwischenlandung —
        # teilnehmend oder fremd (gps_arrival). Das Ziel kennt der Feed nur MIT Ware an Bord
        # (kein Flugplan-Vertrauen, #23); die Anzeige-Regel dazu steckt im Frontend.
        p["last_ground"] = r["last_ground"].get(cid)
        # Der Status ist eine grobe Kategorie für die API; die ANZEIGE leitet das Frontend aus
        # place + reserved_kg ab (Ort x Ladung, Spec). Werte ehrlich statt `arrived`/`returning`:
        if aboard > 0.01:
            p["status"] = "flying" if where is None else "loaded"
        elif where is None:
            p["status"] = "dabei"                       # leer in der Luft — macht noch mit
        elif where in inp["loading_airports"]:
            p["status"] = "loading"                     # steht am Stapel
        else:
            p["status"] = "standing"                    # Ziel oder fremder Platz
        # Was er trägt — der Live-Block zeigt es je Pilot (index.html, fetchKutterActive).
        p["cargo_lines"] = [{"name": n, "emoji": emoji_of.get(n), "kg": round(kg, 1)}
                            for n, kg in load.items() if kg > 0.01]
        p["reserved_kg"] = round(aboard, 1)   # die Bordladung IST die Reservierung
        for k in ("delivered_kg", "lost_kg"):
            p[k] = round(p[k], 1)
        # contributed = hat Ware WIRKLICH bewegt (geliefert / trägt gerade / unterwegs verloren /
        # von Platz zu Platz gebracht) → zählt fürs Badge und die Feierabend-Bilanz. Eine reine
        # Am-Platz-Rückgabe (geladen und am selben Fleck zurück, nie geflogen), reines Warten am
        # Stapel oder ein Leerflug zählt NICHT. Die Live-Sichtbarkeit (`visible`/`online`) bleibt
        # unberührt — der Wartende (Entscheidung 13) zeigt sich live weiter, kriegt nur kein Badge.
        p["contributed"] = (p["delivered_kg"] > 0.0 or p["reserved_kg"] > 0.0
                            or p["lost_kg"] > 0.0 or cid in flew_cargo_cids)

    return {
        "route": sorted(route_set),
        "destination": dest,
        "flights": sorted(network, key=lambda x: x["dep_time"], reverse=True),
        "cargo": cargo_out,
        "total_kg": total_kg,
        "flight_count": len(network),
        "loaded_count": sum(1 for q in network if q["loaded"]),
        "target_kg": target_kg,
        "progress_pct": round(100.0 * total_kg / target_kg, 1) if target_kg else None,
        "reserved_total_kg": reserved_total,
        # #2 (20.07.2026): der ECHTE Stapel je Ladeplatz (name → kg), ohne Ziel + virtuelle Plätze
        # (\x00…). Zeigt auch relayte/zurückgebrachte Ware an Plätzen OHNE eigene Manifest-Zeile —
        # sonst ist sie in der „Je Abholplatz"-Sicht (gruppiert nach Manifest-Herkunft) unsichtbar.
        "place_stacks": {
            place: {n: round(kg, 1) for n, kg in s.items() if kg > 0.01}
            for place, s in stacks.items()
            if place != dest and not str(place).startswith("\x00")
            and any(kg > 0.01 for kg in s.values())
        },
        "unmapped_types": sorted(unmapped),
        "summary_quip": event.get("summary_quip"),
        "losses": [q for q in network if q.get("loss_kind")],
        "lost_total_kg": lost_total,
        "participants": sorted(parts.values(), key=lambda x: (-x["delivered_kg"], x["name"])),
    }


def _empty_transport_progress(event: dict, route_set: set[str], manifest: list[dict]) -> dict:
    """Leerer Fortschritt für ein Event ohne Ziel — es kann keine Lieferung geben."""
    return {
        "route": sorted(route_set), "destination": None, "flights": [],
        "cargo": [{"name": c["name"], "emoji": c.get("emoji"), "target_kg": c["target_kg"],
                   "delivered_kg": 0.0, "reserved_kg": 0.0, "lost_kg": 0.0, "pct": 0.0,
                   "on_stack_kg": round(c["target_kg"], 1),   # ohne Ziel liegt alles noch am Platz
                   "per_flight_max_kg": c.get("per_flight_max_kg"),
                   "departure": c.get("departure")} for c in manifest],
        "total_kg": 0.0, "flight_count": 0, "loaded_count": 0,
        "target_kg": round(sum(c["target_kg"] for c in manifest), 1) if manifest else None,
        "progress_pct": None, "reserved_total_kg": 0.0, "unmapped_types": [], "place_stacks": {},
        "summary_quip": event.get("summary_quip"), "losses": [], "lost_total_kg": 0.0,
        "participants": [],
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
        "SELECT endpoint, p256dh, auth, pilot_filter, notify_prefiles, owner_cid "
        "FROM push_subscriptions"
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
        "SELECT endpoint, p256dh, auth, pilot_filter, notify_prefiles, owner_cid "
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
    """Generische FriesenEvents, deren Erinnerung jetzt fällig ist: dtstart liegt im Fenster
    (now, now+lead_min] und es wurde noch keine Erinnerung verschickt (event_reminders_sent).
    Ausgeschlossen sind Termine, an denen ein Event-Objekt HÄNGT (``calendar_uid``) -- die
    erinnert bummel_races_due_for_reminder / transport_events_due_for_reminder, sonst gäbe es
    einen Doppel-Push.

    #19 (05.09.2026): Vorher hingen der Ausschluss an den Flags ``is_bummel``/``is_transport``.
    Das ging schief, sobald es zum Termin gar kein Objekt gab: Ein Kutter-Abend, den niemand im
    Admin angelegt hatte, fiel still durch — kein Objekt, das erinnert, und der Termin selbst
    ausgeschlossen. Maßgeblich ist jetzt die ausgesprochene Verknüpfung."""
    until = (_parse_iso(now) + timedelta(minutes=lead_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT uid, summary, dtstart, dtend, location, route, is_bummel FROM calendar_events "
        "WHERE dtstart > ? AND dtstart <= ? "
        "AND uid NOT IN (SELECT calendar_uid FROM bummel_races WHERE calendar_uid IS NOT NULL) "
        "AND uid NOT IN (SELECT calendar_uid FROM transport_events WHERE calendar_uid IS NOT NULL) "
        "AND uid NOT IN (SELECT uid FROM event_reminders_sent) "
        "ORDER BY dtstart",
        (now, until),
    ).fetchall()
    return [dict(r) for r in rows]


def bummel_races_due_for_reminder(
    conn: sqlite3.Connection, now: str, lead_min: int = 60
) -> list[dict]:
    """Bummel-Rennen (manuell + Kalender) mit dtstart in (now, now+lead_min], push_enabled=1,
    noch nicht erinnert (synthetischer Dedup-Key 'bummel:{id}' in event_reminders_sent)."""
    until = (_parse_iso(now) + timedelta(minutes=lead_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT id, name, dtstart FROM bummel_races "
        "WHERE dtstart > ? AND dtstart <= ? AND push_enabled = 1 "
        "AND ('bummel:' || id) NOT IN (SELECT uid FROM event_reminders_sent) "
        "ORDER BY dtstart",
        (now, until),
    ).fetchall()
    return [dict(r) for r in rows]


def transport_events_due_for_reminder(
    conn: sqlite3.Connection, now: str, lead_min: int = 60
) -> list[dict]:
    """Kutter-Events (manuell + Kalender) mit dtstart in (now, now+lead_min], push_enabled=1,
    noch nicht erinnert (synthetischer Dedup-Key 'kutter:{id}' in event_reminders_sent)."""
    until = (_parse_iso(now) + timedelta(minutes=lead_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT id, name, dtstart FROM transport_events "
        "WHERE dtstart > ? AND dtstart <= ? AND push_enabled = 1 "
        "AND ('kutter:' || id) NOT IN (SELECT uid FROM event_reminders_sent) "
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


# ---------------------------------------------------------------------------
# Subjekt-Sichtbarkeit (pilot_visibility) — „wer darf über mich benachrichtigt werden?"
# ---------------------------------------------------------------------------

# Services, für die eine Sichtbarkeits-Einschränkung gelten kann (Online/Flugplan/TeamSpeak).
VISIBILITY_SERVICES = ("online", "prefile", "ts")


def get_pilot_visibility(conn: sqlite3.Connection, cid: int) -> dict | None:
    """Subjekt-Sichtbarkeit einer CID, oder None (= Default 'everyone').

    Rückgabe: ``{"mode": str, "allowlist": list[int], "services": list[str]}``. Defektes
    allowlist-JSON → ``[]``. ``services`` = für welche Services die Einschränkung gilt; Spalte
    NULL (Alt-Zeile) → alle drei (Backward-Compat).
    """
    row = conn.execute(
        "SELECT mode, allowlist, services FROM pilot_visibility WHERE cid = ?", (cid,)
    ).fetchone()
    if row is None:
        return None
    try:
        allow = json.loads(row["allowlist"]) if row["allowlist"] else []
    except (json.JSONDecodeError, TypeError):
        allow = []
    raw_svc = row["services"]
    if raw_svc is None:
        services = list(VISIBILITY_SERVICES)          # NULL = gilt für alle
    else:
        try:
            services = [str(s) for s in json.loads(raw_svc) if s in VISIBILITY_SERVICES]
        except (json.JSONDecodeError, TypeError):
            services = list(VISIBILITY_SERVICES)
    return {"mode": row["mode"], "allowlist": [int(x) for x in allow], "services": services}


def set_pilot_visibility(conn: sqlite3.Connection, cid: int, mode: str,
                         allowlist: list[int] | None = None,
                         services: list[str] | None = None) -> None:
    """Sichtbarkeit setzen. ``mode`` ∈ {'everyone','allowlist','nobody'}.

    Bei ``everyone`` werden allowlist und services genullt (keine Einschränkung). Bei
    ``nobody``/``allowlist`` legt ``services`` fest, für welche Services die Einschränkung gilt
    (``None`` = alle). Eine leere allowlist bei ``allowlist`` ist erlaubt (= effektiv niemand).
    """
    if mode not in ("everyone", "allowlist", "nobody"):
        raise ValueError(f"invalid visibility mode: {mode}")
    stored_allow = (json.dumps([int(x) for x in allowlist])
                    if (mode == "allowlist" and allowlist) else None)
    if mode == "everyone":
        stored_svc = None
    else:
        svc = list(VISIBILITY_SERVICES) if services is None else \
            [s for s in services if s in VISIBILITY_SERVICES]
        stored_svc = json.dumps(svc)                  # auch "[]" explizit speichern (= keiner)
    conn.execute(
        """INSERT INTO pilot_visibility (cid, mode, allowlist, services, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(cid) DO UPDATE SET
               mode=excluded.mode, allowlist=excluded.allowlist,
               services=excluded.services, updated_at=excluded.updated_at""",
        (cid, mode, stored_allow, stored_svc, _now_utc()),
    )


def visible_recipients(conn: sqlite3.Connection, subject_cid: int | None,
                       recipients: list[dict], service: str | None = None) -> list[dict]:
    """Filtert Empfänger nach der Subjekt-Sichtbarkeit von ``subject_cid`` für einen ``service``.

    ``recipients``: dicts mit mind. ``owner_cid``. Regeln: ``subject_cid`` None oder Modus
    ``everyone`` (bzw. kein Eintrag) → unverändert; gilt die Einschränkung nicht für diesen
    ``service`` → unverändert; ``nobody`` → ``[]``; ``allowlist`` → nur Empfänger, deren
    ``owner_cid`` in der Liste steht (``owner_cid`` None nie). ``service=None`` → Service-Filter
    übersprungen (Einschränkung gilt).
    """
    if subject_cid is None:
        return recipients
    vis = get_pilot_visibility(conn, subject_cid)
    if not vis or vis["mode"] == "everyone":
        return recipients
    if service is not None and service not in vis["services"]:
        return recipients                             # dieser Service ist ausgenommen → alle
    if vis["mode"] == "nobody":
        return []
    allow = set(vis["allowlist"])
    return [r for r in recipients if r.get("owner_cid") in allow]


def is_visible_to(conn: sqlite3.Connection, subject_cid: int | None,
                  viewer_cid: int | None, service: str | None = None) -> bool:
    """Darf ``viewer_cid`` über ``subject_cid`` benachrichtigt werden?

    Einzelfall-Variante von :func:`visible_recipients` — sie ruft diese auf, statt die Regeln
    ein zweites Mal auszulegen. Gebraucht für den SSE-Strom, der pro VERBINDUNG entscheidet
    (ein Zuschauer) statt pro Empfängerliste.

    ``subject_cid`` None → immer sichtbar (Meldung ohne Person, z. B. Event-Erinnerung).
    ``viewer_cid`` None → nie sichtbar (nicht angemeldet, also kein Empfänger).
    """
    if subject_cid is None:
        return True
    if viewer_cid is None:
        return False
    return bool(visible_recipients(conn, subject_cid, [{"owner_cid": viewer_cid}], service))


# ---------------------------------------------------------------------------
# Forum-Callsign-Map (autoritatives Callsign→CID aus dem Forum-Login)
# ---------------------------------------------------------------------------

def upsert_forum_callsign(conn: sqlite3.Connection, callsign: str, cid: int) -> None:
    """Autoritatives Callsign→CID aus dem Forum. UPPER/trim.

    Kollision (Callsign wechselt den Owner) wird geloggt; last-write-wins (Callsigns sind im
    Forum je Mitglied eindeutig).
    """
    cs = (callsign or "").strip().upper()
    if not cs:
        return
    prev = conn.execute("SELECT cid FROM forum_callsign WHERE callsign = ?", (cs,)).fetchone()
    if prev is not None and int(prev["cid"]) != int(cid):
        logger.warning("forum_callsign-Kollision: %s war CID %s, jetzt CID %s",
                       cs, prev["cid"], cid)
    conn.execute(
        """INSERT INTO forum_callsign (callsign, cid, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(callsign) DO UPDATE SET cid=excluded.cid, updated_at=excluded.updated_at""",
        (cs, int(cid), _now_utc()),
    )


def cid_for_callsign_authoritative(conn: sqlite3.Connection, callsign: str) -> int | None:
    """Zuerst die autoritative Forum-Map, sonst Fallback auf cid_for_callsign
    (live_positions/flights/statsim)."""
    cs = (callsign or "").strip().upper()
    if not cs:
        return None
    row = conn.execute("SELECT cid FROM forum_callsign WHERE callsign = ?", (cs,)).fetchone()
    if row is not None:
        return int(row["cid"])
    return cid_for_callsign(conn, cs)


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
        "SELECT endpoint, p256dh, auth, pilot_filter, owner_cid "
        "FROM push_subscriptions WHERE notify_ts = 1"
    ).fetchall()

    def _rec(row):
        return {"endpoint": row["endpoint"], "p256dh": row["p256dh"],
                "auth": row["auth"], "owner_cid": row["owner_cid"]}

    result = []
    for row in rows:
        pf = row["pilot_filter"]
        if pf is None:
            result.append(_rec(row))
        elif cid is not None:
            try:
                if cid in json.loads(pf):
                    result.append(_rec(row))
            except (json.JSONDecodeError, TypeError):
                result.append(_rec(row))
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


# ---------------------------------------------------------------------------
# Progress-Snapshot (eingefrorener Fortschritt abgeschlossener Spezial-Events —
# Kutter & Bummel gleichrangig, #66)
# ---------------------------------------------------------------------------

def get_progress_snapshot(conn: sqlite3.Connection, kind: str, ref_id: int) -> dict | None:
    """Eingefrorenes Payload lesen — nur bei passender ``_PROGRESS_SNAPSHOT_VERSION``.

    Wird pro Aufruf frisch aus ``payload_json`` geparst (nie ein geteiltes, veränderliches
    Dict), damit Aufrufer das Ergebnis gefahrlos mutieren können."""
    row = conn.execute(
        "SELECT payload_json FROM progress_snapshot WHERE kind=? AND ref_id=? AND code_version=?",
        (kind, ref_id, _PROGRESS_SNAPSHOT_VERSION),
    ).fetchone()
    return json.loads(row[0]) if row else None


def write_progress_snapshot(
    conn: sqlite3.Connection, kind: str, ref_id: int, payload: dict, computed_at: str
) -> None:
    """Fortschritt einfrieren (INSERT OR REPLACE, stampt die aktuelle Code-Version).

    Achtung: mutiert ``payload`` (poppt die interne Markierung ``_conn_logon`` aus jedem
    Flights-Eintrag) — Aufrufer, die das Dict danach noch weiterverwenden, müssen vorher
    selbst kopieren."""
    for f in payload.get("flights", []) or []:
        if isinstance(f, dict):
            f.pop("_conn_logon", None)  # interne Markierung nie einfrieren (Sicherung)
    conn.execute(
        "INSERT OR REPLACE INTO progress_snapshot (kind, ref_id, code_version, computed_at, payload_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (kind, ref_id, _PROGRESS_SNAPSHOT_VERSION, computed_at, json.dumps(payload)),
    )


def delete_progress_snapshot(conn: sqlite3.Connection, kind: str, ref_id: int) -> None:
    """Einzelnen Snapshot verwerfen (z. B. bei Admin-Korrektur an einem abgeschlossenen Event)."""
    conn.execute("DELETE FROM progress_snapshot WHERE kind=? AND ref_id=?", (kind, ref_id))


def delete_progress_snapshots(conn: sqlite3.Connection, kind: str) -> int:
    """Alle Snapshots einer Art verwerfen (z. B. globale Zuladungs-Änderung). Liefert die
    Anzahl gelöschter Zeilen."""
    cur = conn.execute("DELETE FROM progress_snapshot WHERE kind=?", (kind,))
    return cur.rowcount
