"""Versuchszustand der Zuladungs-Recherche liegt in der DB, nicht im Prozessgedaechtnis.

Rev.-2-Befund (B4): ein Backoff ohne Ausfuehrer ist kein Retry. Und der Zustand darf einen
Prozess-Neustart ueberleben, sonst ist die Reparatur nur eine andere Form derselben Luecke.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    get_connection,
    get_payload_research,
    init_db,
    is_retry_due,
    mark_payload_research,
    next_retry_delay_s,
    payload_research_candidates,
    upsert_payload,
)

T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    c = get_connection(db)
    yield c
    c.close()


def _flug(c, cid, code_icao, code_short, ts):
    c.execute(
        "INSERT INTO flight_cache (cid, callsign, aircraft, aircraft_icao, logon_time) "
        "VALUES (?,?,?,?,?)",
        (cid, "FRS1", code_short, code_icao, ts),
    )


def test_backoff_staffel():
    assert next_retry_delay_s(1) == 300      # 5 min
    assert next_retry_delay_s(2) == 1800     # 30 min
    assert next_retry_delay_s(3) == 14400    # 4 h
    assert next_retry_delay_s(4) == 86400    # taeglich
    assert next_retry_delay_s(99) == 86400


def test_retry_erst_nach_ablauf_faellig():
    """Der Kern von B4: bei t0+2min NICHT, bei t0+6min DOCH."""
    ts = T0.isoformat().replace("+00:00", "Z")
    assert is_retry_due("fehler", 1, ts, T0 + timedelta(minutes=2)) is False
    assert is_retry_due("fehler", 1, ts, T0 + timedelta(minutes=6)) is True


def test_ok_ist_nie_faellig_nichts_gefunden_nach_30_tagen():
    ts = T0.isoformat().replace("+00:00", "Z")
    assert is_retry_due("ok", 0, ts, T0 + timedelta(days=999)) is False
    assert is_retry_due("nichts_gefunden", 0, ts, T0 + timedelta(days=29)) is False
    assert is_retry_due("nichts_gefunden", 0, ts, T0 + timedelta(days=31)) is True


def test_neu_und_unbekannt_sind_sofort_faellig():
    assert is_retry_due("neu", 0, None, T0) is True


def test_fehler_erhoeht_attempts_erfolg_setzt_zurueck(conn):
    mark_payload_research(conn, "AP32", "fehler", T0, last_error="Overloaded")
    assert get_payload_research(conn, "AP32")["attempts"] == 1
    mark_payload_research(conn, "AP32", "fehler", T0, last_error="Overloaded")
    row = get_payload_research(conn, "AP32")
    assert row["attempts"] == 2
    assert row["state"] == "fehler"
    assert row["last_error"] == "Overloaded"
    mark_payload_research(conn, "AP32", "ok", T0)
    row = get_payload_research(conn, "AP32")
    assert row["attempts"] == 0
    assert row["state"] == "ok"


def test_schluessel_wird_normalisiert(conn):
    mark_payload_research(conn, "ap32/l-sdgy", "fehler", T0)
    assert get_payload_research(conn, "AP32") is not None


def test_zustand_ueberlebt_neue_verbindung(tmp_path):
    """Genau das, was das In-Memory-Set nicht konnte."""
    db = str(tmp_path / "p.db")
    init_db(db)
    c1 = get_connection(db)
    mark_payload_research(c1, "AP32", "fehler", T0, last_error="Overloaded")
    c1.commit()
    c1.close()
    c2 = get_connection(db)
    assert get_payload_research(c2, "AP32")["attempts"] == 1
    c2.close()


def test_kandidaten_kommen_aus_dem_flugbestand_beide_spalten(conn):
    """B1: aircraft_icao ist erst seit 2026-06-09 gefuellt. Altfluege stehen nur in aircraft."""
    _flug(conn, 1, None, "P28S", "2025-06-06T10:00:00Z")   # nur Anzeige-Spalte
    _flug(conn, 2, "AP32", "AP32", "2026-07-25T10:00:00Z") # beide
    _flug(conn, 3, "", "FK9", "2026-04-13T10:00:00Z")      # icao leer, nicht NULL
    conn.commit()
    assert set(payload_research_candidates(conn, T0, limit=10)) == {"P28S", "AP32", "FK9"}


def test_kandidat_faellt_weg_wenn_eintrag_existiert(conn):
    _flug(conn, 1, "AP32", "AP32", "2026-07-25T10:00:00Z")
    upsert_payload(conn, "AP32", mtow_kg=600.0, empty_kg=350.0, fuel_kg=40.0,
                   fuel_full_kg=80.0, crew_kg=85.0, source="llm", make_model="Aeroprakt A-32")
    conn.commit()
    assert payload_research_candidates(conn, T0, limit=10) == []


def test_kandidat_zaehlt_jeden_flug_nur_einmal(conn):
    """Nie per OR addieren: eine Zeile mit beiden Spalten ist EIN Flug."""
    _flug(conn, 1, "AP32", "AP32", "2026-07-25T10:00:00Z")
    _flug(conn, 2, None, "P28S", "2025-06-06T10:00:00Z")
    _flug(conn, 3, None, "P28S", "2025-06-07T10:00:00Z")
    conn.commit()
    # P28S (2 Fluege) vor AP32 (1 Flug)
    assert payload_research_candidates(conn, T0, limit=10) == ["P28S", "AP32"]


def test_nicht_faellige_kandidaten_fehlen(conn):
    _flug(conn, 1, "AP32", "AP32", "2026-07-25T10:00:00Z")
    conn.commit()
    mark_payload_research(conn, "AP32", "fehler", T0, last_error="Overloaded")
    conn.commit()
    assert payload_research_candidates(conn, T0 + timedelta(minutes=2), limit=10) == []
    assert payload_research_candidates(conn, T0 + timedelta(minutes=6), limit=10) == ["AP32"]


def test_limit_greift(conn):
    for i, code in enumerate(["P28S", "AP32", "FK9"]):
        _flug(conn, i, code, code, "2026-07-25T10:00:00Z")
    conn.commit()
    assert len(payload_research_candidates(conn, T0, limit=2)) == 2


def test_gepolsterter_typcode_matcht_normalize_type_code(conn):
    """FLIGHT_TYPE_CODE_SQL muss normalize_type_code() gleichziehen (Whitespace).

    normalize_type_code() trimmt (``.strip()``); ohne trim() im SQL-Pendant wuerde ein
    gepolsterter aircraft-Wert nie zu seinem eigenen payload_research/aircraft_payloads-
    Eintrag joinen und ewig als 'neu' erscheinen."""
    from app.database import normalize_type_code

    _flug(conn, 1, None, " AP32 ", "2026-07-25T10:00:00Z")
    conn.commit()
    kandidaten = payload_research_candidates(conn, T0, limit=10)
    assert kandidaten == [normalize_type_code(" AP32 ")] == ["AP32"]

    # Mit vorhandenem payload_research-Eintrag fuer "AP32" darf der gepolsterte Flug
    # NICHT mehr als eigener, ungematchter Kandidat auftauchen.
    mark_payload_research(conn, "AP32", "ok", T0)
    conn.commit()
    assert payload_research_candidates(conn, T0, limit=10) == []

    # Ebenso mit einem aircraft_payloads-Eintrag fuer "AP32".
    _flug(conn, 2, None, "AP32 ", "2026-07-25T10:00:00Z")
    conn.commit()
    upsert_payload(conn, "AP32", mtow_kg=600.0, empty_kg=350.0, fuel_kg=40.0,
                   fuel_full_kg=80.0, crew_kg=85.0, source="llm", make_model="Aeroprakt A-32")
    conn.commit()
    assert payload_research_candidates(conn, T0, limit=10) == []


def test_leerzeichen_vor_dem_slash_matcht_normalize_type_code(conn):
    """Whole-Branch-Befund 3: das aeussere trim() fasst nur den Rand, nicht das Segment.

    "AP32 /L-SDGY" (Leerzeichen unmittelbar vor dem inneren '/', KEIN Randpadding) ergibt in
    Python "AP32", im SQL aber "AP32 " -- eine so gepolsterte Zeile joint nie auf ihre
    aircraft_payloads/payload_research-Zeile, bleibt dauerhaft Kandidat und belegt bei jedem
    Nachlese-Lauf einen der 5 Slots, ohne je fertig zu werden."""
    from app.database import normalize_type_code

    _flug(conn, 1, None, "AP32 /L-SDGY", "2026-07-25T10:00:00Z")
    conn.commit()
    assert payload_research_candidates(conn, T0, limit=10) == \
        [normalize_type_code("AP32 /L-SDGY")] == ["AP32"]

    # Ein Zustand fuer "AP32" muss diese Zeile stilllegen (sonst: ewiger Kandidat).
    mark_payload_research(conn, "AP32", "ok", T0)
    conn.commit()
    assert payload_research_candidates(conn, T0, limit=10) == []

    # Ebenso ein aircraft_payloads-Eintrag -- und auch mit Rand- UND Innenpadding zugleich.
    _flug(conn, 2, None, "  AP32  /  L-SDGY ", "2026-07-25T10:00:00Z")
    conn.commit()
    upsert_payload(conn, "AP32", mtow_kg=600.0, empty_kg=350.0, fuel_kg=40.0,
                   fuel_full_kg=80.0, crew_kg=85.0, source="llm", make_model="Aeroprakt A-32")
    conn.commit()
    assert payload_research_candidates(conn, T0, limit=10) == []
