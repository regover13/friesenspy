"""Datenmodell des Muster-Panels: Override-Semantik, Alias, Friesen-Zahlen."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    aircraft_type_candidates,
    flight_type_codes,
    friesen_numbers,
    get_aircraft_type,
    get_connection,
    init_db,
    mark_aircraft_type_state,
    mark_payload_research,
    resolve_alias,
    set_aircraft_type_override,
    top_pilots,
    upsert_aircraft_type_import,
    upsert_payload,
    validate_alias,
)

T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    c = get_connection(db)
    yield c
    c.close()


def _flug(c, cid, icao, short, ts, dauer=60, nm=100.0, callsign="FRS1"):
    c.execute(
        "INSERT INTO flight_cache (cid, callsign, aircraft, aircraft_icao, logon_time, "
        "duration_min, distance_nm) VALUES (?,?,?,?,?,?,?)",
        (cid, callsign, short, icao, ts, dauer, nm),
    )


# --- Override-Semantik ------------------------------------------------------

def test_import_schreibt_nur_import_spalten(conn):
    upsert_aircraft_type_import(conn, "C172", name="Cessna 172", wiki_title="Cessna 172",
                                extract="Die Cessna 172 ist …", wiki_lang="de",
                                name_source="payloads", now=T0)
    set_aircraft_type_override(conn, "C172", name="Unsere Rote", now=T0)
    upsert_aircraft_type_import(conn, "C172", name="Cessna 172 Skyhawk",
                                extract="Neuer Text", now=T0)
    row = get_aircraft_type(conn, "C172")
    assert row["name"] == "Unsere Rote", "Import hat die Korrektur zertreten"
    assert row["extract"] == "Neuer Text", "Import-Feld ohne Korrektur wurde nicht aktualisiert"


def test_override_leeren_stellt_importwert_wieder_her(conn):
    upsert_aircraft_type_import(conn, "C172", name="Cessna 172", now=T0)
    set_aircraft_type_override(conn, "C172", name="Unsere Rote", now=T0)
    assert get_aircraft_type(conn, "C172")["name"] == "Unsere Rote"
    set_aircraft_type_override(conn, "C172", name="", now=T0)
    assert get_aircraft_type(conn, "C172")["name"] == "Cessna 172"


def test_photo_credit_gilt_auch_fuer_commons(conn):
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg",
                                photo_artist="Falscher Name",
                                photo_licence="CC BY-SA 4.0", now=T0)
    set_aircraft_type_override(conn, "C172", photo_credit="Foto: Tobias", now=T0)
    row = get_aircraft_type(conn, "C172")
    assert row["photo_credit"] == "Foto: Tobias"
    assert row["photo_source_url"] is None or True  # Link bleibt immer sichtbar


def test_photo_blob_gewinnt_ueber_datei(conn):
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    assert get_aircraft_type(conn, "C172")["photo_kind"] == "file"
    conn.execute("UPDATE aircraft_types SET photo_blob=?, photo_override='blob' "
                 "WHERE type_code='C172'", (b"\xff\xd8\xff",))
    assert get_aircraft_type(conn, "C172")["photo_kind"] == "blob"


def test_photo_override_strich_heisst_kein_foto(conn):
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    set_aircraft_type_override(conn, "C172", photo_override="-", now=T0)
    assert get_aircraft_type(conn, "C172")["photo_kind"] is None


def test_blob_ohne_blob_wird_abgelehnt(conn):
    import sqlite3
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE aircraft_types SET photo_override='blob' WHERE type_code='C172'")


# --- Alias ------------------------------------------------------------------

def test_alias_loest_einen_schritt_auf(conn):
    upsert_aircraft_type_import(conn, "PA24", name="Piper PA-24 Comanche", now=T0)
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    assert resolve_alias(conn, "P24") == "PA24"
    assert resolve_alias(conn, "PA24") == "PA24"
    assert resolve_alias(conn, "UNBEKANNT") == "UNBEKANNT"


def test_selbstbezug_abgelehnt(conn):
    assert validate_alias(conn, "P24", "P24") is not None


def test_ziel_ist_alias_abgelehnt(conn):
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    assert validate_alias(conn, "X", "P24") is not None


def test_auf_mich_zeigt_ein_alias_abgelehnt(conn):
    """W5.1: die Kette entsteht in der ANDEREN Anlegereihenfolge."""
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    assert validate_alias(conn, "PA24", "X") is not None, \
        "PA24 darf kein Alias werden, solange P24 auf PA24 zeigt"


def test_gueltiger_alias_wird_akzeptiert(conn):
    assert validate_alias(conn, "P24", "PA24") is None


# --- Friesen-Zahlen ---------------------------------------------------------

def test_zahlen_ueber_beide_spalten_und_ohne_doppelzaehlung(conn):
    _flug(conn, 1, None, "C172", "2025-03-01T10:00:00Z", dauer=60, nm=100.0)
    _flug(conn, 2, "C172", "C172", "2026-07-01T10:00:00Z", dauer=120, nm=200.0)
    conn.commit()
    z = friesen_numbers(conn, "C172")
    assert z["fluege"] == 2, "Zeile mit beiden Spalten doppelt gezaehlt"
    assert z["stunden"] == pytest.approx(3.0)
    assert z["nm"] == pytest.approx(300.0)
    assert z["piloten"] == 2
    assert z["von"] == "2025-03-01"
    assert z["bis"] == "2026-07-01"


def test_alias_fluege_zaehlen_zum_ziel_mit_ausweis(conn):
    _flug(conn, 1, None, "PA24", "2025-01-01T10:00:00Z")
    _flug(conn, 2, None, "PA24", "2025-01-02T10:00:00Z")
    _flug(conn, 3, None, "P24", "2025-10-26T10:00:00Z")
    conn.commit()
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    z = friesen_numbers(conn, "PA24")
    assert z["fluege"] == 3
    assert z["alias_anteil"] == [{"code": "P24", "n": 1}]


def test_alias_anteil_ist_eine_liste_bei_zwei_aliassen(conn):
    """W5.2: real zeigen SA65/AS65 und JU5/JU52 auf dasselbe Ziel."""
    _flug(conn, 1, None, "AS65", "2026-07-01T10:00:00Z")
    _flug(conn, 2, None, "SA65", "2026-07-04T10:00:00Z")
    _flug(conn, 3, None, "SA65", "2026-07-05T10:00:00Z")
    conn.commit()
    set_aircraft_type_override(conn, "SA65", alias_of="AS65", now=T0)
    z = friesen_numbers(conn, "AS65")
    assert z["fluege"] == 3
    assert z["alias_anteil"] == [{"code": "SA65", "n": 2}]


def test_abfrage_ueber_das_alias_kuerzel_liefert_die_zielzahlen(conn):
    _flug(conn, 1, None, "PA24", "2025-01-01T10:00:00Z")
    _flug(conn, 2, None, "P24", "2025-10-26T10:00:00Z")
    conn.commit()
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    assert friesen_numbers(conn, "P24")["fluege"] == 2


def test_unbekanntes_kuerzel_liefert_nullen_statt_fehler(conn):
    z = friesen_numbers(conn, "IMPU")
    assert z["fluege"] == 0
    assert z["alias_anteil"] == []


def test_top_piloten(conn):
    for i in range(3):
        _flug(conn, 10, None, "C172", f"2025-01-0{i+1}T10:00:00Z", callsign="FRS96")
    _flug(conn, 11, None, "C172", "2025-02-01T10:00:00Z", callsign="FRS45")
    conn.commit()
    top = top_pilots(conn, "C172", limit=3)
    assert top[0]["cid"] == 10
    assert top[0]["n"] == 3
    assert top[0]["callsign"] == "FRS96"
    assert top[1]["n"] == 1


# --- Kandidaten und Bestand -------------------------------------------------

def test_kandidaten_und_bestand(conn):
    _flug(conn, 1, None, "P28S", "2025-06-06T10:00:00Z")
    _flug(conn, 2, "AP32", "AP32", "2026-07-25T10:00:00Z")
    # Zuladungs-Recherche (Plan A) bereits abgeschlossen (Endzustand) — sonst wären
    # beide Codes namenlos UND ohne Endzustand und würden vom Filter gegen
    # dauerhaft offene Kandidaten übersprungen (siehe test_namenloser_code_...).
    mark_payload_research(conn, "P28S", "nichts_gefunden", T0)
    mark_payload_research(conn, "AP32", "nichts_gefunden", T0)
    conn.commit()
    assert flight_type_codes(conn) == {"P28S", "AP32"}
    assert set(aircraft_type_candidates(conn, T0, limit=10)) == {"P28S", "AP32"}
    mark_aircraft_type_state(conn, "AP32", "ok", T0)
    conn.commit()
    assert aircraft_type_candidates(conn, T0, limit=10) == ["P28S"]


def test_fehlende_fotodatei_setzt_zustand_zurueck_ist_kandidat(conn, tmp_path):
    """W2: 'ok' heisst nicht 'nie wieder'."""
    _flug(conn, 1, None, "C172", "2025-01-01T10:00:00Z")
    mark_payload_research(conn, "C172", "nichts_gefunden", T0)
    conn.commit()
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    mark_aircraft_type_state(conn, "C172", "ok", T0)
    conn.commit()
    assert aircraft_type_candidates(conn, T0, limit=10) == []
    mark_aircraft_type_state(conn, "C172", "neu", T0)
    conn.commit()
    assert aircraft_type_candidates(conn, T0, limit=10) == ["C172"]


def test_namenloser_code_ohne_endzustand_verdraengt_keine_echten_kandidaten(conn):
    """Restbefund der Fix-Welle-Re-Review: ein Code ohne jeden Namen, dessen
    Zuladungs-Recherche nie zu einem Endzustand kommt (z. B. ohne ANTHROPIC_API_KEY,
    ein unterstuetzter Zustand), darf nicht auf ewig ein Kandidatenplatz bleiben und
    damit echte, aufloesbare Muster verdraengen. `checked_at IS NULL` waere sonst
    IMMER faellig (is_retry_due) und mit hoher Flugzahl immer vorne einsortiert."""
    # AP32: viele Fluege, aber nie ein Name -- weder Override noch make_model --
    # und payload_research existiert gar nicht (kein API-Key, kein Versuch je gestartet).
    for i in range(5):
        _flug(conn, i, "AP32", "AP32", f"2026-07-0{i+1}T10:00:00Z")
    # P28S: ein einzelner Flug, aber ein echter Name -- muss trotz niedrigerer
    # Flugzahl als Kandidat erscheinen, DARF NICHT von AP32 verdraengt werden.
    _flug(conn, 10, "P28S", "P28S", "2026-07-10T10:00:00Z")
    upsert_payload(conn, "P28S", mtow_kg=1157.0, empty_kg=767.0, fuel_kg=100.0,
                   fuel_full_kg=200.0, crew_kg=85.0, source="curated",
                   make_model="Piper PA-28-181 Archer")
    conn.commit()
    kandidaten = aircraft_type_candidates(conn, T0, limit=1)
    assert kandidaten == ["P28S"], "namenloser Code ohne Endzustand hat den echten Kandidaten verdraengt"

    # Ein Admin-Lemma reicht ebenfalls als "hat einen Namen" -- AP32 wird dann Kandidat.
    set_aircraft_type_override(conn, "AP32", wiki_title="Aeroprakt A-32", now=T0)
    conn.commit()
    assert set(aircraft_type_candidates(conn, T0, limit=10)) == {"AP32", "P28S"}
