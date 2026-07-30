"""Endpunkte des Muster-Panels."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def _warte_bis(bedingung, timeout_s: float = 2.0, schritt_s: float = 0.02):
    """Auf den Hintergrund-Abruf (asyncio.create_task, W3) warten, statt ihn zu erraten.

    Der Endpunkt stoesst _resolve_aircraft_type bewusst fire-and-forget an (nie synchron im
    Klickpfad) -- TestClient wartet darauf NICHT automatisch mit. `bedingung` wird gepollt,
    bis sie wahr wird oder das Timeout reisst (dann bleibt die letzte Auswertung stehen, und
    der Test faellt mit einer aussagekraeftigen Meldung statt eines Hangs durch)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if bedingung():
            return
        time.sleep(schritt_s)
    assert bedingung(), f"Bedingung nach {timeout_s}s nicht erfuellt"


@pytest.fixture(autouse=True)
def _kein_echtes_netz(monkeypatch):
    """W3 loest den Hintergrund-Abruf fuer bekannte Codes bewusst aus (z. B. fuer C172, das
    ueber seed_curated_payloads() schon einen Namen hat) -- in Tests darf das trotzdem nie
    wirklich Wikipedia/Commons erreichen: das waere sowohl Testtempo- als auch ein Netiquette-
    Problem (dieselbe Absender-IP ist dort laut aircraft_info.py schon wegen "abuse" vorbelastet).
    resolve_type/resolve_title liefern hier synchron None -> _resolve_aircraft_type markiert
    'nichts_gefunden' in wenigen Millisekunden statt nach einem echten, mehrere hundert ms
    dauernden Roundtrip."""
    from app import aircraft_info
    monkeypatch.setattr(aircraft_info, "resolve_type", lambda name, fetch: None)
    monkeypatch.setattr(aircraft_info, "resolve_title", lambda lang, titel, fetch: None)


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DB_PATH", db)
    from app.config import get_settings
    get_settings.cache_clear()
    from app.database import init_db
    init_db(db)
    # Dieses Testmodul ist im Repo das einzige, das den vollen Lifespan ueber TestClient(app)
    # hochfaehrt (alle anderen Aircraft-Tests rufen Funktionen direkt auf). Der Start-Job
    # _warmup_flight_cache laeuft dabei "date"-getriggert quasi sofort in einem Hintergrund-
    # Thread und macht einen VOLLEN Rebuild von flight_cache aus canonicalize_legs() -- also
    # DELETE FROM flight_cache + Neuaufbau aus den kanonischen Tabellen. Die Fixtures hier
    # seifen flight_cache aber direkt per Raw-INSERT ein (bequem fuer den Test, aber nicht die
    # kanonische Quelle) -- ohne dieses Abschalten reisst der Warmup-Rebuild die frisch
    # eingefuegten Test-Zeilen mit Timing-Zufall wieder heraus (beobachtet: fluege 0/1/3 statt 4).
    # Fuer die hier getesteten Endpunkte ist der Warmup irrelevant, deshalb neutralisiert statt
    # per Wartezeit "gewonnen".
    from app.poller import VatsimPoller

    async def _kein_warmup(self):
        return None

    monkeypatch.setattr(VatsimPoller, "_warmup_flight_cache", _kein_warmup)
    monkeypatch.setattr(VatsimPoller, "_refresh_flight_cache", _kein_warmup)
    from app.main import app
    with TestClient(app) as c:
        c.db = db
        yield c
    get_settings.cache_clear()


def _flug(db, cid, code, ts="2026-07-01T10:00:00Z", callsign="FRS1"):
    from app.database import get_connection
    conn = get_connection(db)
    conn.execute(
        "INSERT INTO flight_cache (cid, callsign, aircraft, logon_time, duration_min, "
        "distance_nm) VALUES (?,?,?,?,60,100.0)", (cid, callsign, code, ts))
    conn.commit()
    conn.close()


def test_unbekanntes_kuerzel_liefert_200_und_echte_nullen(client):
    r = client.get("/api/aircraft/IMPU")
    assert r.status_code == 200
    d = r.json()
    assert d["code"] == "IMPU"
    assert d["friesen"]["fluege"] == 0
    assert d["name"] is None


def test_zahlen_und_top_piloten(client):
    for i in range(3):
        _flug(client.db, 10, "C172", f"2026-07-0{i+1}T10:00:00Z", callsign="FRS96")
    _flug(client.db, 11, "C172", "2026-07-05T10:00:00Z", callsign="FRS45")
    d = client.get("/api/aircraft/C172").json()
    assert d["friesen"]["fluege"] == 4
    assert d["top"][0]["cid"] == 10
    assert d["top"][0]["n"] == 3


def test_kutter_daten_und_hinweis_auf_eigene_zeile(client):
    """W5.3: P24 hat real eine eigene Zuladungszeile (381 kg), PA24 hat 381,5 kg."""
    from app.database import get_connection, set_aircraft_type_override, upsert_payload
    conn = get_connection(client.db)
    upsert_payload(conn, "PA24", mtow_kg=1315.0, empty_kg=780.0, fuel_kg=100.0,
                   fuel_full_kg=200.0, crew_kg=85.0, source="manual",
                   make_model="Piper PA-24-250 Comanche")
    upsert_payload(conn, "P24", mtow_kg=1315.0, empty_kg=780.0, fuel_kg=100.0,
                   fuel_full_kg=200.0, crew_kg=85.0, source="manual", make_model="")
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    conn.commit()
    conn.close()
    _flug(client.db, 1, "PA24")
    _flug(client.db, 2, "P24")
    d = client.get("/api/aircraft/P24").json()
    assert d["resolved_code"] == "PA24"
    assert d["friesen"]["fluege"] == 2
    assert d["friesen"]["alias_anteil"] == [{"code": "P24", "n": 1}]
    assert d["kutter"]["eigene_zeile_hinweis"] is not None, \
        "Widerspruch zur Frachtrechnung muss sichtbar sein"


def test_unbekannter_code_legt_keine_zeile_an(client):
    """W3: sonst ist der Endpunkt ein Verstaerker."""
    from app.database import get_connection
    for i in range(5):
        client.get(f"/api/aircraft/JUNK{i}")
    conn = get_connection(client.db)
    n = conn.execute("SELECT COUNT(*) AS n FROM aircraft_types").fetchone()["n"]
    conn.close()
    assert n == 0


def test_bekannter_code_darf_zeile_anlegen(client):
    from app.database import get_connection

    def _codes():
        conn = get_connection(client.db)
        try:
            return [r["type_code"] for r in
                    conn.execute("SELECT type_code FROM aircraft_types").fetchall()]
        finally:
            conn.close()

    _flug(client.db, 1, "C172")
    client.get("/api/aircraft/C172")
    # Die Zeile entsteht erst, wenn der fire-and-forget-Hintergrund-Abruf (W3) durchgelaufen
    # ist -- das ist per Design nicht synchron mit der Antwort des Endpunkts.
    _warte_bis(lambda: _codes() == ["C172"])
    assert _codes() == ["C172"]


def test_foto_blob_gewinnt_und_content_type_stimmt(client):
    from app.database import get_connection, upsert_aircraft_type_import
    _flug(client.db, 1, "C172")
    conn = get_connection(client.db)
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    conn.execute("UPDATE aircraft_types SET photo_blob=?, photo_override='blob' "
                 "WHERE type_code='C172'", (b"\xff\xd8\xffBLOB",))
    conn.commit()
    conn.close()
    r = client.get("/api/aircraft/C172/photo")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == b"\xff\xd8\xffBLOB"


def test_fehlende_fotodatei_gibt_404_und_setzt_zustand_zurueck(client):
    from app.database import (get_aircraft_type, get_connection, mark_aircraft_type_state,
                              upsert_aircraft_type_import)
    _flug(client.db, 1, "C172")
    conn = get_connection(client.db)
    upsert_aircraft_type_import(conn, "C172", photo_file="fehlt.jpg", now=T0)
    mark_aircraft_type_state(conn, "C172", "ok", T0)
    conn.commit()
    conn.close()
    assert client.get("/api/aircraft/C172/photo").status_code == 404
    conn = get_connection(client.db)
    assert get_aircraft_type(conn, "C172")["fetch_state"] == "neu"
    conn.close()


def test_photo_url_traegt_versionsparameter(client):
    """Anmerkung Rev. 2: sonst zeigen Browser nach einem Fotowechsel das alte Bild."""
    from app.database import get_connection, upsert_aircraft_type_import
    _flug(client.db, 1, "C172")
    conn = get_connection(client.db)
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    conn.commit()
    conn.close()
    d = client.get("/api/aircraft/C172").json()
    assert d["photo_url"] and "?v=" in d["photo_url"]


def test_kein_foto_liefert_photo_url_none(client):
    _flug(client.db, 1, "IMPU")
    assert client.get("/api/aircraft/IMPU").json()["photo_url"] is None
