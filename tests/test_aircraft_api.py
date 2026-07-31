"""Endpunkte des Muster-Panels."""
from __future__ import annotations

import io
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


def test_type_stats_endpoint_sortiert_und_ohne_hintergrund_abruf(client, monkeypatch):
    """Grundlage der Top-Muster-KPI: meistgeflogenes zuerst, kein Wikimedia-Seiteneffekt
    (anders als /api/aircraft/{code} loest dieser Endpunkt nie _resolve_aircraft_type aus)."""
    from app.poller import VatsimPoller
    aufgerufen = []
    monkeypatch.setattr(
        VatsimPoller, "_resolve_aircraft_type",
        lambda self, code: aufgerufen.append(code),
    )
    for i in range(2):
        _flug(client.db, i, "C172", f"2026-07-0{i+1}T10:00:00Z")
    _flug(client.db, 10, "PA24")
    d = client.get("/api/aircraft-types/stats").json()
    assert [r["code"] for r in d] == ["C172", "PA24"]
    assert d[0]["fluege"] == 2
    assert d[1]["fluege"] == 1
    assert aufgerufen == []


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


@pytest.fixture
def admin(client, monkeypatch):
    """Admin-Sitzung — require_admin/require_confirm werden überbrückt."""
    from app import main
    monkeypatch.setattr(main, "require_admin", lambda request: None)
    monkeypatch.setattr(main, "require_confirm", lambda request: None)
    return client


def _jpeg(breite=2000, hoehe=1200, mit_exif=True) -> bytes:
    """Testbild, optional mit echten GPS-EXIF-Daten (0x8825 = GPSInfo-Sub-IFD).

    Pillow >= 10 verlangt fuer 0x8825 ein echtes Sub-IFD (ueber ``get_ifd``), kein rohes
    Bytes-Objekt -- ein direktes ``exif[0x8825] = b"GPS"`` wirft beim Speichern
    ``AttributeError: 'Exif' object has no attribute 'fp'`` (gegen Pillow 12.3.0 verifiziert).
    Der Sub-IFD-Weg liefert dasselbe Testziel: ein Bild mit echten GPS-Koordinaten im EXIF.
    """
    from PIL import Image
    img = Image.new("RGB", (breite, hoehe), (10, 20, 30))
    buf = io.BytesIO()
    if mit_exif:
        exif = img.getexif()
        gps_ifd = exif.get_ifd(0x8825)  # GPSInfo — genau das, was nicht in die DB soll
        gps_ifd[1] = "N"                # GPSLatitudeRef
        gps_ifd[2] = (53.0, 30.0, 0.0)  # GPSLatitude
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def test_upload_wird_neu_kodiert_verkleinert_und_exif_frei(admin):
    from PIL import Image
    from app.database import get_aircraft_type, get_connection
    _flug(admin.db, 1, "C172")
    r = admin.post("/api/admin/aircraft-types/C172/photo",
                   files={"file": ("cockpit.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200
    conn = get_connection(admin.db)
    blob = conn.execute("SELECT photo_blob FROM aircraft_types WHERE type_code='C172'"
                        ).fetchone()["photo_blob"]
    assert get_aircraft_type(conn, "C172")["photo_kind"] == "blob"
    conn.close()
    img = Image.open(io.BytesIO(blob))
    assert img.width <= 1280
    assert not dict(img.getexif()), "EXIF nicht entfernt — GPS landet in der DB"


def test_kein_bild_wird_abgelehnt(admin):
    _flug(admin.db, 1, "C172")
    r = admin.post("/api/admin/aircraft-types/C172/photo",
                   files={"file": ("boese.jpg", b"<html>kein Bild</html>", "image/jpeg")})
    assert r.status_code == 400


def test_zu_gross_wird_abgelehnt(admin):
    _flug(admin.db, 1, "C172")
    r = admin.post("/api/admin/aircraft-types/C172/photo",
                   files={"file": ("gross.jpg", b"x" * (8 * 1024 * 1024 + 1), "image/jpeg")})
    assert r.status_code == 413


def test_dateiname_kommt_aus_dem_typcode(admin):
    """Pfad-Traversal ist keine Pruef-, sondern eine Unmoeglichkeitsfrage."""
    _flug(admin.db, 1, "C172")
    r = admin.post("/api/admin/aircraft-types/C172/photo",
                   files={"file": ("../../etc/passwd", _jpeg(100, 100), "image/jpeg")})
    assert r.status_code == 200
    from app.database import get_connection
    conn = get_connection(admin.db)
    row = conn.execute("SELECT photo_file, photo_override FROM aircraft_types "
                       "WHERE type_code='C172'").fetchone()
    conn.close()
    assert row["photo_override"] == "blob"
    assert row["photo_file"] is None or ".." not in (row["photo_file"] or "")


def test_override_setzen_und_leeren(admin):
    from app.database import get_aircraft_type, get_connection, upsert_aircraft_type_import
    conn = get_connection(admin.db)
    upsert_aircraft_type_import(conn, "C172", name="Cessna 172", now=T0)
    conn.commit()
    conn.close()
    admin.post("/api/admin/aircraft-types", json={"type_code": "C172", "name": "Unsere Rote"})
    conn = get_connection(admin.db)
    assert get_aircraft_type(conn, "C172")["name"] == "Unsere Rote"
    conn.close()
    admin.post("/api/admin/aircraft-types", json={"type_code": "C172", "name": ""})
    conn = get_connection(admin.db)
    assert get_aircraft_type(conn, "C172")["name"] == "Cessna 172"
    conn.close()


def test_ungueltiger_alias_wird_mit_400_abgelehnt(admin):
    r = admin.post("/api/admin/aircraft-types",
                   json={"type_code": "P24", "alias_of": "P24"})
    assert r.status_code == 400
    admin.post("/api/admin/aircraft-types", json={"type_code": "P24", "alias_of": "PA24"})
    r = admin.post("/api/admin/aircraft-types",
                   json={"type_code": "PA24", "alias_of": "X"})
    assert r.status_code == 400, "Kette in der anderen Reihenfolge wurde zugelassen"


def test_liste_zeigt_import_und_korrektur_getrennt(admin):
    from app.database import (get_connection, set_aircraft_type_override,
                              upsert_aircraft_type_import)
    conn = get_connection(admin.db)
    upsert_aircraft_type_import(conn, "C172", name="Cessna 172", now=T0)
    set_aircraft_type_override(conn, "C172", name="Unsere Rote", now=T0)
    conn.commit()
    conn.close()
    d = admin.get("/api/admin/aircraft-types").json()
    row = next(r for r in d["types"] if r["type_code"] == "C172")
    assert row["name"] == "Cessna 172"
    assert row["name_override"] == "Unsere Rote"
    assert "fetch_state" in row and "checked_at" in row and "attempts" in row


def test_liste_zeigt_auch_den_zuladungs_recherchezustand(admin):
    """Teil 8 hat absichtlich keine UI — sichtbar wird der Zustand hier."""
    from app.database import get_connection, mark_payload_research
    conn = get_connection(admin.db)
    mark_payload_research(conn, "AP32", "fehler", T0, last_error="Overloaded")
    conn.commit()
    conn.close()
    d = admin.get("/api/admin/aircraft-types").json()
    row = next(r for r in d["types"] if r["type_code"] == "AP32")
    assert row["payload_state"] == "fehler"
    assert row["payload_last_error"] == "Overloaded"


def test_liste_fasst_zuladung_und_recherche_ohne_types_zeile_zusammen(admin):
    """Rev. 3 (I1): der NORMALE Zustand direkt nach jeder Plan-A-Recherche.

    aircraft_payloads UND payload_research haben eine Zeile, aircraft_types noch nicht (bis der
    10-Minuten-Job nachzieht). Weil die payload_research-Seite nur gegen `t.type_code` jointe,
    fielen daraus ZWEI Zeilen fuer dasselbe Muster heraus -- eine mit den Zuladungsdaten, eine
    mit dem Recherche-Zustand.
    """
    from app.database import get_connection, mark_payload_research, upsert_payload
    conn = get_connection(admin.db)
    upsert_payload(conn, "AP32", mtow_kg=600.0, empty_kg=300.0, fuel_kg=50.0,
                   fuel_full_kg=60.0, crew_kg=85.0, source="llm",
                   make_model="Aquila A211")
    mark_payload_research(conn, "AP32", "ok", T0)
    conn.commit()
    conn.close()
    zeilen = [r for r in admin.get("/api/admin/aircraft-types").json()["types"]
              if r["type_code"] == "AP32"]
    assert len(zeilen) == 1, f"Muster doppelt in der Liste: {zeilen}"
    assert zeilen[0]["make_model"] == "Aquila A211"
    assert zeilen[0]["payload_state"] == "ok"


def test_liste_zeigt_auch_reine_flug_codes(admin):
    """Rev. 3 (I1): ein Code, der nur in flight_cache steht, hatte keine Basiszeile zum
    Anhaengen und erschien nie -- `f.code` im COALESCE war toter Code. Genau diese Muster sind
    aber die interessanten: geflogen, aber noch ohne jede Info."""
    _flug(admin.db, 1, "FK9")
    _flug(admin.db, 2, "FK9", "2026-07-02T10:00:00Z")
    zeilen = [r for r in admin.get("/api/admin/aircraft-types").json()["types"]
              if r["type_code"] == "FK9"]
    assert len(zeilen) == 1, f"Flug-only-Code fehlt oder ist doppelt: {zeilen}"
    assert zeilen[0]["fluege"] == 2
    assert zeilen[0]["fetch_state"] is None and zeilen[0]["payload_state"] is None
