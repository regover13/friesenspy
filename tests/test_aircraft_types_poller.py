# tests/test_aircraft_types_poller.py
"""Auffuellen von aircraft_types laeuft ausserhalb des Klickpfads, serialisiert, gedeckelt."""
from __future__ import annotations

import asyncio
import io
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database import (
    get_aircraft_type, get_connection, init_db, mark_aircraft_type_state,
    upsert_aircraft_type_import, upsert_payload,
)

T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _poller(db_path, tmp_path):
    from app.poller import VatsimPoller
    p = VatsimPoller(db_path=db_path, callsign_prefix="FRS")
    p._photo_dir = Path(tmp_path) / "fotos"
    return p


def _flug(db_path, cid, code, ts="2026-07-01T10:00:00Z"):
    c = get_connection(db_path)
    c.execute("INSERT INTO flight_cache (cid, callsign, aircraft, logon_time) VALUES (?,?,?,?)",
              (cid, "FRS1", code, ts))
    c.commit()
    c.close()


def _bild(breite=3000, hoehe=2000) -> bytes:
    """Ein echtes JPEG in Commons-Originalgroesse (dort gemessen bis 4 MB)."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (breite, hoehe), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def _name_hinterlegen(db_path, code, make_model):
    """make_model in aircraft_payloads → _muster_name findet einen Namen."""
    c = get_connection(db_path)
    upsert_payload(c, code, mtow_kg=1157.0, empty_kg=767.0, fuel_kg=100.0,
                   fuel_full_kg=200.0, crew_kg=85.0, source="curated",
                   make_model=make_model)
    c.commit()
    c.close()


@pytest.mark.asyncio
async def test_name_kommt_aus_payloads_und_foto_landet_als_datei(db, tmp_path, monkeypatch):
    c = get_connection(db)
    upsert_payload(c, "C172", mtow_kg=1157.0, empty_kg=767.0, fuel_kg=100.0,
                   fuel_full_kg=200.0, crew_kg=85.0, source="curated",
                   make_model="Cessna 172S Skyhawk")
    c.commit()
    c.close()
    _flug(db, 1, "C172")
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)

    from app import aircraft_info
    gefragt = {}

    # Bewusst als def statt als `setdefault(...) or {...}`-Lambda: setdefault liefert den
    # (wahren) Namen zurueck, `or` kaeme dann nie beim Dict an und die Attrappe lieferte einen
    # String statt eines Ergebnisses.
    def _fake_resolve(name, fetch):
        gefragt["name"] = name
        return {
            "wiki_lang": "de", "wiki_title": "Cessna 172", "extract": "Die Cessna 172 …",
            "photo_commons_title": "File:x.jpg", "photo_url": "https://upload/x.jpg",
            "photo_licence": "CC BY-SA 3.0", "photo_artist": "Fotograf",
            "photo_source_url": "https://commons/File:x.jpg",
        }

    monkeypatch.setattr(aircraft_info, "resolve_type", _fake_resolve)
    monkeypatch.setattr(aircraft_info, "download_photo", lambda url, **kw: _bild(3000, 2000))

    await p._resolve_aircraft_type("C172")

    assert gefragt["name"] == "Cessna 172S Skyhawk"
    row = get_aircraft_type(get_connection(db), "C172")
    assert row["fetch_state"] == "ok"
    assert row["wiki_title"] == "Cessna 172"
    assert row["photo_kind"] == "file"
    # Rev. 3 (I3): Commons liefert das Original (bis 4 MB). Auf dem Volume und auf dem
    # Mobilgeraet darf nur noch die aufbereitete Fassung landen -- dieselbe Pillow-Pipeline
    # wie beim Admin-Upload (max. 1280 px, JPEG, kein EXIF).
    from PIL import Image
    bild = Image.open(io.BytesIO((p._photo_dir / row["photo_file"]).read_bytes()))
    assert bild.format == "JPEG"
    assert bild.width == 1280, "Commons-Original wurde unverkleinert gespeichert"


@pytest.mark.asyncio
async def test_unlesbares_commons_bild_kostet_nur_das_foto(db, tmp_path, monkeypatch):
    """Ein SVG von Commons ist kein Pillow-Bild -- der Artikeltext bleibt trotzdem."""
    from app import aircraft_info
    _name_hinterlegen(db, "C208", "Cessna 208B Grand Caravan")
    _flug(db, 1, "C208")
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    monkeypatch.setattr(aircraft_info, "resolve_type", lambda name, fetch: {
        "wiki_lang": "de", "wiki_title": "Cessna 208", "extract": "Text",
        "photo_commons_title": "File:x.svg", "photo_url": "https://upload/x.svg",
        "photo_licence": "CC BY-SA 3.0", "photo_artist": None, "photo_source_url": None,
    })
    monkeypatch.setattr(aircraft_info, "download_photo", lambda url, **kw: b"<svg/>")
    await p._resolve_aircraft_type("C208")
    row = get_aircraft_type(get_connection(db), "C208")
    assert row["fetch_state"] == "ok"
    assert row["extract"] == "Text"
    assert not row["photo_file"]


@pytest.mark.asyncio
async def test_403_wird_fehler_nicht_nichts_gefunden(db, tmp_path, monkeypatch):
    _flug(db, 1, "C172")
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    from app import aircraft_info

    def _boom(name, fetch):
        raise aircraft_info.WikimediaError("Contabo forbidden", 403)

    monkeypatch.setattr(aircraft_info, "resolve_type", _boom)
    await p._resolve_aircraft_type("C172")
    row = get_aircraft_type(get_connection(db), "C172")
    assert row["fetch_state"] == "fehler", "403 wurde als endgueltig behandelt"
    assert row["attempts"] == 1


@pytest.mark.asyncio
async def test_kein_treffer_wird_nichts_gefunden(db, tmp_path, monkeypatch):
    _flug(db, 1, "IMPU")
    _name_hinterlegen(db, "IMPU", "Impuls")   # Name da, die Suche findet nur nichts
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    from app import aircraft_info
    monkeypatch.setattr(aircraft_info, "resolve_type", lambda name, fetch: None)
    await p._resolve_aircraft_type("IMPU")
    assert get_aircraft_type(get_connection(db), "IMPU")["fetch_state"] == "nichts_gefunden"


@pytest.mark.asyncio
async def test_import_zertritt_die_korrektur_nicht(db, tmp_path, monkeypatch):
    from app.database import set_aircraft_type_override
    _flug(db, 1, "C172")
    c = get_connection(db)
    set_aircraft_type_override(c, "C172", name="Unsere Rote", now=T0)
    c.commit()
    c.close()
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    from app import aircraft_info
    monkeypatch.setattr(aircraft_info, "resolve_type", lambda name, fetch: {
        "wiki_lang": "de", "wiki_title": "Cessna 172", "extract": "Text",
        "photo_commons_title": None, "photo_url": None, "photo_licence": None,
        "photo_artist": None, "photo_source_url": None,
    })
    await p._resolve_aircraft_type("C172")
    assert get_aircraft_type(get_connection(db), "C172")["name"] == "Unsere Rote"


@pytest.mark.asyncio
async def test_admin_lemma_umgeht_die_suche(db, tmp_path, monkeypatch):
    from app.database import set_aircraft_type_override
    _flug(db, 1, "AS65")
    c = get_connection(db)
    set_aircraft_type_override(c, "AS65", wiki_title="Eurocopter AS365", now=T0)
    c.commit()
    c.close()
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    from app import aircraft_info
    monkeypatch.setattr(aircraft_info, "resolve_type",
                        lambda name, fetch: pytest.fail("Suche darf nicht laufen"))
    geholt = {}

    def _fake_title(lang, titel, fetch):
        geholt["titel"] = titel
        return {
            "wiki_lang": lang, "wiki_title": titel, "extract": "Der AS365 …",
            "photo_commons_title": None, "photo_url": None, "photo_licence": None,
            "photo_artist": None, "photo_source_url": None,
        }

    monkeypatch.setattr(aircraft_info, "resolve_title", _fake_title)
    await p._resolve_aircraft_type("AS65")
    assert geholt["titel"] == "Eurocopter AS365"
    row = get_aircraft_type(get_connection(db), "AS65")
    assert row["fetch_state"] == "ok"
    assert row["wiki_title"] == "Eurocopter AS365"


@pytest.mark.asyncio
async def test_fehlende_fotodatei_setzt_ok_zurueck(db, tmp_path, monkeypatch):
    """W2: 'ok' heisst nicht 'nie wieder'. rm -rf des Cache ist eine legitime Reparatur."""
    _flug(db, 1, "C172")
    c = get_connection(db)
    upsert_aircraft_type_import(c, "C172", photo_file="C172.jpg", now=T0)
    mark_aircraft_type_state(c, "C172", "ok", T0)
    c.commit()
    c.close()
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._requeue_missing_photos()
    assert get_aircraft_type(get_connection(db), "C172")["fetch_state"] == "neu"


@pytest.mark.asyncio
async def test_nachlese_deckel_und_serialisierung(db, tmp_path, monkeypatch):
    for i, code in enumerate(["C172"] * 3 + ["PA24"] * 2 + ["C208", "EC45", "DA40",
                                                            "AEST", "P28S", "FK9"]):
        _flug(db, i, code)
        # Namen explizit hinterlegen: die kuratierten Zuladungen tragen nicht fuer jedes
        # Kuerzel ein make_model, und ohne Namen liefe ein Kandidat in den Kurzschluss
        # "nichts zu suchen" — der Deckel waere dann nicht mehr messbar.
        _name_hinterlegen(db, code, f"Muster {code}")
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    from app import aircraft_info
    reihenfolge = []
    monkeypatch.setattr(aircraft_info, "resolve_type",
                        lambda name, fetch: reihenfolge.append(name) or None)
    await p._resolve_due_aircraft_types()
    assert len(reihenfolge) == p._AIRCRAFT_INFO_LIMIT


def test_jobs_registriert(db, tmp_path):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    p = _poller(db, tmp_path)
    p._scheduler = AsyncIOScheduler()
    p._register_jobs()
    ids = {j.id for j in p._scheduler.get_jobs()}
    assert {"aircraft_info_initial", "aircraft_info_retry"} <= ids


# --- In-Flight-Guard (Lehre aus Plan A / AP32) ------------------------------

@pytest.mark.asyncio
async def test_zweiter_lauf_waehrend_laufender_aufloesung_wird_unterdrueckt(
    db, tmp_path, monkeypatch
):
    """Derselbe Bugtyp wie AP32 in Plan A, hier mit Wikimedia statt der LLM-API.

    Zwei Auslöser können sich überschneiden, und der DB-Zustand (aircraft_types.fetch_state)
    entsteht erst NACH der HTTP-Auflösung:

    1. Der Live-Auslöser im Poll-Durchlauf hängt an den `new_codes` aus Plan A. Deren Kriterium
       ist der Zustand in `payload_research`, NICHT in `aircraft_types` — solange die
       LLM-Recherche eines Musters läuft oder im Backoff hängt, bleibt der Code über viele
       Polls (alle 15 s) in `new_codes` und stiesse jedes Mal ein neues
       `_resolve_aircraft_type` an.
    2. Der 10-Minuten-Job wählt nach `aircraft_types.fetch_state` — ein Code, dessen
       Live-Auflösung gerade läuft, steht dort noch auf 'neu' und gilt weiter als fällig.

    Ohne Guard liefen mehrere parallele Requests gegen Wikipedia/Commons, von einer IP, die dort
    ohnehin vorbelastet ist. Der Test hält die erste Auflösung im Thread fest und beweist, dass
    weder weitere Live-Aufrufe noch die Nachlese einen zweiten HTTP-Aufruf auslösen.
    """
    _name_hinterlegen(db, "C172", "Cessna 172S Skyhawk")
    _flug(db, 1, "C172")
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)

    from app import aircraft_info
    starts: list[str] = []
    laeuft = threading.Event()      # erste Auflösung hängt jetzt wirklich im Thread
    freigabe = threading.Event()    # ... bis der Test sie freigibt

    def _haengt(name, fetch):
        starts.append(name)
        laeuft.set()
        assert freigabe.wait(timeout=10), "Freigabe kam nie an"
        return None                 # -> nichts_gefunden

    monkeypatch.setattr(aircraft_info, "resolve_type", _haengt)

    erste = asyncio.create_task(p._resolve_aircraft_type("C172"))
    for _ in range(1000):           # auf den echten Start warten, nicht auf eine Schätzung
        if laeuft.is_set():
            break
        await asyncio.sleep(0.01)
    assert laeuft.is_set(), "erste Auflösung kam nicht in den Thread"

    # Risikostelle 1: weitere Poll-Durchläufe, sequenziell und echt nebenläufig.
    await p._resolve_aircraft_type("C172")
    await asyncio.gather(*(p._resolve_aircraft_type("C172") for _ in range(2)))
    # Risikostelle 2: der 10-Minuten-Job trifft mitten in die laufende Live-Auflösung.
    await p._resolve_due_aircraft_types()
    assert starts == ["Cessna 172S Skyhawk"], \
        f"parallele Auflösung für dasselbe Muster gestartet: {starts}"

    freigabe.set()
    await erste
    assert starts == ["Cessna 172S Skyhawk"]
    assert not p._aircraft_info_inflight, "In-Flight-Eintrag blieb haengen"
    assert get_aircraft_type(get_connection(db), "C172")["fetch_state"] == "nichts_gefunden"

    # Das Set ist KEIN Gedaechtnis: nach Ablauf der Sperre geht es normal weiter.
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(days=31))
    monkeypatch.setattr(aircraft_info, "resolve_type",
                        lambda name, fetch: starts.append(name) or None)
    await p._resolve_aircraft_type("C172")
    assert len(starts) == 2, "In-Flight-Set blockiert den faelligen Retry"


@pytest.mark.asyncio
async def test_inflight_eintrag_verschwindet_auf_jedem_rueckgabepfad(db, tmp_path, monkeypatch):
    """Bliebe ein Code nach einem Kurzschluss oder Fehler im Set haengen, waere das Muster fuer
    die restliche Prozesslaufzeit dauerhaft gesperrt — schlimmer als der Bug, den der Guard
    behebt."""
    from app import aircraft_info
    from app.database import set_aircraft_type_override
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)

    # 1. Alias-Kurzschluss (kein HTTP)
    c = get_connection(db)
    set_aircraft_type_override(c, "C72R", alias_of="C172", now=T0)
    c.commit()
    c.close()
    await p._resolve_aircraft_type("C72R")
    assert not p._aircraft_info_inflight

    # 2. kein Name verfuegbar -> Rueckkehr ohne HTTP (und seit Rev. 3 auch ohne Zustand,
    #    solange die Zuladungs-Recherche noch offen ist)
    await p._resolve_aircraft_type("IMPU")
    assert not p._aircraft_info_inflight

    # 3. transienter Fehler (403) und 4. unerwarteter Fehler — je eigener Code, sonst greift
    #    beim zweiten Durchgang der Backoff des ersten.
    for code, fehler in (("PA24", aircraft_info.WikimediaError("Contabo forbidden", 403)),
                         ("DA40", RuntimeError("unerwartet"))):
        _name_hinterlegen(db, code, f"Muster {code}")

        def _boom(name, fetch, _f=fehler):
            raise _f

        monkeypatch.setattr(aircraft_info, "resolve_type", _boom)
        await p._resolve_aircraft_type(code)
        assert not p._aircraft_info_inflight

    # 5. Erfolg
    _name_hinterlegen(db, "C208", "Cessna 208B Grand Caravan")
    monkeypatch.setattr(aircraft_info, "resolve_type", lambda name, fetch: {
        "wiki_lang": "de", "wiki_title": "Cessna 208", "extract": "Text",
        "photo_commons_title": None, "photo_url": None, "photo_licence": None,
        "photo_artist": None, "photo_source_url": None,
    })
    await p._resolve_aircraft_type("C208")
    assert not p._aircraft_info_inflight
    assert get_aircraft_type(get_connection(db), "C208")["fetch_state"] == "ok"


@pytest.mark.asyncio
async def test_live_ausloeser_wiederholt_die_aufloesung_nicht_bei_jedem_poll(
    db, tmp_path, monkeypatch
):
    """Der In-Flight-Guard deckt nur GLEICHZEITIGE Läufe ab, nicht die Wiederholung.

    Der Live-Auslöser hängt an `new_codes`, deren Kriterium der Zustand in `payload_research`
    ist. Ohne ANTHROPIC_API_KEY (ein unterstützter Zustand) läuft dort nie eine Recherche,
    `payload_research` bleibt für immer leer — der Code steht bei JEDEM Poll (alle 15 s) wieder
    in `new_codes`. Ohne Fälligkeitsprüfung in _resolve_aircraft_type liefe damit für jedes
    fliegende Muster alle 15 s eine komplette Wikipedia-Suche samt Foto-Download.
    """
    _name_hinterlegen(db, "C172", "Cessna 172S Skyhawk")
    _flug(db, 1, "C172")
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    from app import aircraft_info
    starts: list[str] = []

    def _fake(name, fetch):
        starts.append(name)
        return {
            "wiki_lang": "de", "wiki_title": "Cessna 172", "extract": "Text",
            "photo_commons_title": None, "photo_url": None, "photo_licence": None,
            "photo_artist": None, "photo_source_url": None,
        }

    monkeypatch.setattr(aircraft_info, "resolve_type", _fake)
    for _ in range(4):                       # vier Poll-Durchläufe hintereinander
        await p._resolve_aircraft_type("C172")
    assert starts == ["Cessna 172S Skyhawk"], f"Auflösung lief mehrfach: {starts}"

    # Und das Gegenstück: 'nichts_gefunden' sperrt 30 Tage, danach ist es wieder fällig.
    _name_hinterlegen(db, "PA24", "Piper PA-24 Comanche")
    treffer: list[str] = []
    monkeypatch.setattr(aircraft_info, "resolve_type",
                        lambda name, fetch: treffer.append(name) or None)
    await p._resolve_aircraft_type("PA24")
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(days=7))
    await p._resolve_aircraft_type("PA24")
    assert len(treffer) == 1, "30-Tage-Sperre wurde ignoriert"
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(days=31))
    await p._resolve_aircraft_type("PA24")
    assert len(treffer) == 2, "nach Ablauf der Sperre muss es wieder losgehen"


@pytest.mark.asyncio
async def test_nachlese_uebersteht_fehler_eines_einzelnen_kandidaten(db, tmp_path, monkeypatch):
    """`except Exception` um die GESAMTE Schleife isoliert nicht je Kandidat: ein DB-Fehler beim
    Schreiben des Ergebnisses fuer den ersten Code brach ohne lokale Absicherung die ganze
    Nachlese ab, die uebrigen fielen aus."""
    for i, code in enumerate(["C172", "PA24", "DA40"]):
        _flug(db, i, code)
        _name_hinterlegen(db, code, f"Muster {code}")
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)

    from app import aircraft_info, database
    gesehen: list[str] = []
    monkeypatch.setattr(aircraft_info, "resolve_type",
                        lambda name, fetch: gesehen.append(name) or None)
    original = database.mark_aircraft_type_state

    def _boom_bei_c172(conn, code, state, now, last_error=None):
        if code == "C172":
            raise RuntimeError("database is locked")
        return original(conn, code, state, now, last_error=last_error)

    monkeypatch.setattr(database, "mark_aircraft_type_state", _boom_bei_c172)
    await p._resolve_due_aircraft_types()
    assert set(gesehen) == {"Muster C172", "Muster PA24", "Muster DA40"}, \
        "ein Fehler bei EINEM Kandidaten darf die uebrigen nicht verhindern"
    assert not p._aircraft_info_inflight


@pytest.mark.asyncio
async def test_neues_muster_wird_nicht_sofort_30_tage_gesperrt(db, tmp_path, monkeypatch):
    """Rev. 3 (C2): „Name noch nicht da" ist kein „nichts gefunden".

    Der Live-Ausloeser startet fuer dieselben `new_codes` BEIDE Recherchen gleichzeitig --
    und `new_codes` enthaelt per Konstruktion nur Codes OHNE aircraft_payloads-Zeile. Der
    Name, den `_muster_name` braucht, entsteht aber erst durch die Zuladungs-Recherche
    (30-300 s). `_resolve_aircraft_type` ist Millisekunden spaeter hier und faende praktisch
    IMMER keinen Namen: ohne Unterscheidung schriebe es sofort 'nichts_gefunden' und damit
    30 Tage Sperre -- fuer jedes neu gesehene Muster, noch bevor der Name da sein KANN.
    """
    from app import aircraft_info
    from app.database import get_payload_research, mark_payload_research
    _flug(db, 1, "NEU1")
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    gesucht: list[str] = []
    monkeypatch.setattr(aircraft_info, "resolve_type",
                        lambda name, fetch: gesucht.append(name) or None)

    # 1. Live-Ausloeser: Zuladungs-Recherche laeuft gerade erst an, payload_research ist leer.
    await p._resolve_aircraft_type("NEU1")
    assert gesucht == [], "ohne Namen darf keine Wikipedia-Suche laufen"
    zeile = get_aircraft_type(get_connection(db), "NEU1")
    assert zeile is None or zeile["fetch_state"] != "nichts_gefunden", \
        "vorlaeufiger Zustand wurde als Endergebnis gespeichert (30-Tage-Sperre)"

    # 2. Auch ein laufender Backoff der Zuladungs-Recherche ist kein Endzustand.
    c = get_connection(db)
    mark_payload_research(c, "NEU1", "fehler", T0, last_error="Overloaded")
    c.commit()
    c.close()
    await p._resolve_aircraft_type("NEU1")
    zeile = get_aircraft_type(get_connection(db), "NEU1")
    assert zeile is None or zeile["fetch_state"] != "nichts_gefunden"

    # 3. Zehn Minuten spaeter ist die Zuladungs-Recherche durch und hat den Namen geliefert --
    #    das Muster muss JETZT Kandidat sein und ganz normal aufgeloest werden.
    _name_hinterlegen(db, "NEU1", "Cessna 172S Skyhawk")
    c = get_connection(db)
    mark_payload_research(c, "NEU1", "ok", T0)
    c.commit()
    c.close()
    assert get_payload_research(get_connection(db), "NEU1")["state"] == "ok"
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(minutes=10))
    await p._resolve_aircraft_type("NEU1")
    assert gesucht == ["Cessna 172S Skyhawk"], \
        "nach dem Eintreffen des Namens muss die Aufloesung starten"
    assert get_aircraft_type(get_connection(db), "NEU1")["fetch_state"] == "nichts_gefunden"


@pytest.mark.asyncio
async def test_endgueltig_ohne_namen_wird_weiterhin_gesperrt(db, tmp_path, monkeypatch):
    """Gegenprobe zu C2: hat die Zuladungs-Recherche wirklich nichts gefunden, gibt es auch
    nie einen Namen -- dann ist 'nichts_gefunden' das richtige, endgueltige Ergebnis (sonst
    bliebe der Code fuer immer Kandidat und belegte jeden Nachlese-Lauf)."""
    from app.database import mark_payload_research
    _flug(db, 1, "ZZ99")
    c = get_connection(db)
    mark_payload_research(c, "ZZ99", "nichts_gefunden", T0)
    c.commit()
    c.close()
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._resolve_aircraft_type("ZZ99")
    assert get_aircraft_type(get_connection(db), "ZZ99")["fetch_state"] == "nichts_gefunden"


@pytest.mark.asyncio
async def test_zuladungszeile_ohne_payload_research_wird_trotzdem_abgeschlossen(
    db, tmp_path, monkeypatch
):
    """Realer Fund (MR20, 2026-07-26): eine manuell/per Admin-Knopf gespeicherte
    aircraft_payloads-Zeile geht NIE durch _auto_research_payload (dessen eigener
    "inzwischen (manuell) gepflegt"-Kurzschluss greift ab der ersten Zeile) -- payload_research
    bekommt fuer sie deshalb NIE einen Endzustand. War make_model dazu unbrauchbar (hier: ein
    Prosa-Absatz, den harden_name() verwirft, wie MR20s echter 1063-Zeichen-Wert), blieb das
    Muster ohne den hat_zuladungszeile-Fallback fuer immer 'offen' -- jeder Nachlese-Lauf griff
    es erneut auf, ohne je 'nichts_gefunden' zu erreichen."""
    from app import aircraft_info
    from app.database import get_payload_research
    _flug(db, 1, "MR20")
    _name_hinterlegen(db, "MR20", "M" * 200)  # zu lang fuer harden_name (MAX_NAME_LEN=80)
    assert get_payload_research(get_connection(db), "MR20") is None, \
        "Testaufbau: payload_research darf hier KEINE Zeile haben (der reale Fehlerfall)"
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    gesucht: list[str] = []
    monkeypatch.setattr(aircraft_info, "resolve_type",
                        lambda name, fetch: gesucht.append(name) or None)
    await p._resolve_aircraft_type("MR20")
    assert gesucht == [], "der zu lange Name darf nie an die Suche gehen"
    zeile = get_aircraft_type(get_connection(db), "MR20")
    assert zeile is not None and zeile["fetch_state"] == "nichts_gefunden", \
        "ohne payload_research-Endzustand, aber MIT aircraft_payloads-Zeile muss die " \
        "Aufloesung trotzdem abschliessen, statt fuer immer 'offen' zu bleiben"


@pytest.mark.asyncio
async def test_admin_lemma_gilt_auch_ohne_namen(db, tmp_path, monkeypatch):
    """Ein gesetztes Lemma ist eine menschliche Entscheidung -- es braucht keinen Namen und
    darf von der C2-Pruefung nicht mit blockiert werden."""
    from app import aircraft_info
    from app.database import set_aircraft_type_override
    _flug(db, 1, "LEMM")
    c = get_connection(db)
    set_aircraft_type_override(c, "LEMM", wiki_title="Cessna 172", now=T0)
    c.commit()
    c.close()
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    gesehen: list[str] = []
    monkeypatch.setattr(aircraft_info, "resolve_title",
                        lambda lang, titel, fetch: gesehen.append(titel) or {
                            "wiki_lang": lang, "wiki_title": titel, "extract": "Text",
                            "photo_commons_title": None, "photo_url": None,
                            "photo_licence": None, "photo_artist": None,
                            "photo_source_url": None,
                        })
    await p._resolve_aircraft_type("LEMM")
    assert gesehen == ["Cessna 172"]
    assert get_aircraft_type(get_connection(db), "LEMM")["fetch_state"] == "ok"
