# FriesenReddung — Server und Admin: Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Eventtyp FriesenReddung läuft vollständig auf dem Server — Sektor, Havarist, Fund,
Aufnahme, Einlieferung, Fackeln — und ist im Admin bedienbar. Nichts davon ist auf der Website
oder im Kniebrett sichtbar.

**Architecture:** Die Rechnung kommt aus dem vorhandenen `app/abdeckung.py` (15.7.0) und wird
nicht neu geschnitten. Neu sind: ein reines Parametermodul `app/reddung.py` (Fundradius, Ziele,
Fenster — keine Datenbank), eine Tabelle `reddung_events` mit den Latches in `app/database.py`,
ein Poller-Job `_check_reddung`, die Auslieferung von Havarist und Fackel über `bruegge_soll`,
und ein Admin-Bereich.

**Tech Stack:** Python 3.12, FastAPI, SQLite (WAL), APScheduler, Vanilla-JS im Admin.
Tests mit pytest im eigenen venv: `/home/claude/.venv-friesenspy/bin/python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-09-20-friesenreddung-design.md` — der Plan argumentiert aus der
Spec; beides zusammen lesen.

## Global Constraints

- **Höhenschranke ist AGL über dem Havaristen**, Vorgabe **1000 ft**. Nie MSL.
- **Der Fundradius wird GERECHNET, nie eingestellt:** `korridor_km + kante_km / √2`.
  Bei 1,0/1,0 km sind das 1,71 km.
- **Zellkante und Korridor je 1,0 km**, Sektor **40 × 40 km** als Vorgabe.
- **Geschwindigkeitsfenster Suchen: 30–140 kt.** Fürs Aufnehmen muss `gs_min_kt` auf **0**.
- **Aufnehmen an Land benutzt die Landeregeln des Projekts, importiert:**
  `_GPS_BLOCK_GS_KT` (2 kt) und `_GPS_GROUND_AGL_FT` (300 ft) aus `app/gps_legs.py`.
  **Niemals abschreiben.** Ohne Landung gilt `< 30 kt`.
- **Die Koordinate des Havaristen geht an die FriesenBrügge und in den Admin — an keinen
  Endpunkt, den ein Browser eines Piloten erreicht.** Kein Rückgabewert einer Wertungsfunktion
  enthält `havarist_lat`/`havarist_lon`.
- **Zwei Haken, verschachtelt:** `aufnehmen_noetig` (Vorgabe 1) über `landung_noetig` (Vorgabe 1).
- **Aufnehmen darf irgendeiner**, nicht nur der Finder. Das Finden ist in allen Fällen gleich.
- **Kein Zufallspunkt.** Der Admin setzt den Ort von Hand und sieht ihn.
- **Changelog:** Jeder Eintrag `"highlight": false`. Version ist MINOR (kein Frontend außerhalb
  des Admin). Der erste Eintrag von `app/CHANGELOG.json` gibt die Nummer.
- **Vor jedem Push:** `git fetch` + Rebase auf `origin/main`, Eintrag in `COORDINATION.md`.
  Fremde uncommittete Änderungen im Arbeitsbaum niemals mitnehmen.
- **Die Tests laufen im eigenen venv.** `pytest` systemweit bricht mit fehlenden Modulen ab.

---

## Dateien

| Datei | Verantwortung |
|---|---|
| `app/reddung.py` (neu) | **Reine Parameterrechnung**: Fundradius, Zielliste, Fenster, Grundhöhe. Keine Datenbank, kein FastAPI. |
| `app/database.py` | Tabelle `reddung_events` in `_DDL`, CRUD, Latches, `compute_reddung_stand`, Spurenabruf, Spalte `bruegge_soll.simulator` |
| `app/poller.py` | Job `_check_reddung` — Latches, Fackeltausch, Push, Auflösung |
| `app/main.py` | `/api/admin/reddung/...`, Filter nach Simulator beim Melden |
| `app/static/admin.html` | Bereich „FriesenReddung" |
| `tests/test_reddung_parameter.py` (neu) | Task 1 |
| `tests/test_reddung_db.py` (neu) | Task 2, 3 |
| `tests/test_reddung_poller.py` (neu) | Task 5 |
| `tests/test_reddung_objekte.py` (neu) | Task 4, 6 |
| `tests/test_reddung_api.py` (neu) | Task 7 |

**Nach Aufgabe 6 ist der Eventtyp vollständig lauffähig** — bedienbar über die Datenbank. Aufgabe 7
und 8 setzen den Admin darauf. Das ist der natürliche Haltepunkt für eine Zwischenabnahme.

---

### Task 1: Parameter — Fundradius, Ziele, Fenster

**Files:**
- Create: `app/reddung.py`
- Test: `tests/test_reddung_parameter.py`

**Interfaces:**
- Consumes: `app.abdeckung.Fenster`, `app.abdeckung.Ziel`, `app.abdeckung.zellen_aus_box`,
  `app.gps_legs._GPS_BLOCK_GS_KT`, `app.gps_legs._GPS_GROUND_AGL_FT`
- Produces:
  - `fundradius_km(korridor_km: float, kante_km: float) -> float`
  - `zellen_fuer(ev: dict) -> list[Ziel]`
  - `havarist_ziel(ev: dict) -> Ziel | None` — Schlüssel immer `"havarist"`
  - `fenster_suchen(ev: dict) -> Fenster`
  - `fenster_aufnehmen(ev: dict) -> Fenster`
  - `grund_ft(ev: dict) -> float`
  - `hoehe_schranke_msl(ev: dict) -> float`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reddung_parameter.py
# -*- coding: utf-8 -*-
"""Die Parameter einer FriesenReddung -- reine Rechnung, keine Datenbank (20.09.2026).

Der wichtigste Test hier ist der erste: Der Fundradius wird GERECHNET. Wird er einstellbar,
luegt der Fortschrittsbalken -- eine abgedeckte Zelle heisst nur, dass ein Track im Korridor an
ihrem MITTELPUNKT vorbeilief, und ein Havarist in der Zellecke ist die halbe Zelldiagonale
weiter weg. Siehe Spec, Abschnitt 4.
"""
from __future__ import annotations

import math

import pytest

from app import reddung
from app.gps_legs import _GPS_BLOCK_GS_KT, _GPS_GROUND_AGL_FT

EV = {
    "sued": 53.54, "west": 6.95, "nord": 53.90, "ost": 7.55,
    "kante_km": 1.0, "korridor_km": 1.0,
    "hoehe_max_ft": 1000, "gs_max_kt": 140, "gs_min_kt": 30,
    "havarist_lat": 53.72, "havarist_lon": 7.25,
    "havarist_grund_ft": 20.0,
    "aufnehmen_noetig": 1, "landung_noetig": 1,
}


def test_der_fundradius_ist_korridor_plus_halbe_zelldiagonale():
    assert reddung.fundradius_km(1.0, 1.0) == pytest.approx(1.0 + math.sqrt(2) / 2, abs=1e-9)
    assert reddung.fundradius_km(1.0, 1.0) == pytest.approx(1.7071, abs=1e-4)


def test_volle_abdeckung_garantiert_den_fund():
    """Der Sinn der Rechnung: Jeder Punkt einer abgedeckten Zelle liegt im Fundradius.

    Schlimmster Fall ist die Ecke zwischen vier Zellen -- kante/sqrt(2) vom Mittelpunkt. Wer
    dort liegt und dessen Zelle abgedeckt ist, muss gefunden worden sein.
    """
    for kante in (0.5, 1.0, 2.0, 3.0):
        for korridor in (0.5, 1.0, 2.0):
            ecke = kante / math.sqrt(2)
            assert reddung.fundradius_km(korridor, kante) >= korridor + ecke - 1e-9


def test_strengere_werte_ziehen_den_fundradius_mit():
    """Wer strenger will, verkleinert BEIDE Werte -- das Verhaeltnis bleibt erhalten."""
    assert reddung.fundradius_km(0.6, 0.6) == pytest.approx(1.0243, abs=1e-4)


def test_havarist_ist_ein_gewoehnliches_ziel_mit_dem_schluessel_havarist():
    ziel = reddung.havarist_ziel(EV)
    assert ziel[0] == "havarist"
    assert ziel[1] == 53.72 and ziel[2] == 7.25
    assert ziel[3] == pytest.approx(1.7071, abs=1e-4)


def test_ohne_gesetzten_ort_gibt_es_kein_ziel():
    assert reddung.havarist_ziel({**EV, "havarist_lat": None}) is None


def test_die_zellen_kommen_aus_dem_sektor_und_tragen_den_korridor():
    zellen = reddung.zellen_fuer(EV)
    assert len(zellen) > 1000, "40 x 40 km bei 1-km-Kante"
    assert all(z[3] == 1.0 for z in zellen)
    assert len({z[0] for z in zellen}) == len(zellen)


def test_die_hoehenschranke_ist_agl_ueber_dem_havaristen():
    """1000 ft AGL bei 20 ft Gelaende heisst 1020 ft MSL -- gemessen wird gegen die
    MSL-Hoehe aus position_history."""
    assert reddung.hoehe_schranke_msl(EV) == pytest.approx(1020.0)
    assert reddung.fenster_suchen(EV).hoehe_max_ft == pytest.approx(1020.0)


def test_ohne_gemessene_grundhoehe_gilt_null():
    assert reddung.grund_ft({**EV, "havarist_grund_ft": None}) == 0.0
    assert reddung.hoehe_schranke_msl({**EV, "havarist_grund_ft": None}) == pytest.approx(1000.0)


def test_das_suchfenster_hat_eine_untergrenze():
    """Sonst deckt ein geparktes Flugzeug seine Zelle den ganzen Abend ab."""
    assert reddung.fenster_suchen(EV).gs_min_kt == 30


def test_das_aufnahmefenster_hat_KEINE_untergrenze():
    """Die Falle: Die Suchuntergrenze von 30 kt wuerde genau den Stillstand ausschliessen,
    der beim Aufnehmen gefragt ist."""
    assert reddung.fenster_aufnehmen(EV).gs_min_kt == 0


def test_aufnehmen_mit_landung_nimmt_die_landeregeln_des_projekts():
    f = reddung.fenster_aufnehmen(EV)
    assert f.gs_max_kt == _GPS_BLOCK_GS_KT
    assert f.hoehe_max_ft == pytest.approx(20.0 + _GPS_GROUND_AGL_FT)


def test_aufnehmen_ohne_landung_erlaubt_schwebeflug():
    f = reddung.fenster_aufnehmen({**EV, "landung_noetig": 0})
    assert f.gs_max_kt == reddung.SCHWEBE_GS_KT == 30
    assert f.hoehe_max_ft == pytest.approx(20.0 + _GPS_GROUND_AGL_FT)


def test_die_landeschwellen_werden_importiert_und_nicht_abgeschrieben():
    """Aendert jemand die Landeerkennung, muss die FriesenReddung mitziehen. Verankert am
    Quelltext, damit ein spaeteres Zurueckschreiben der Zahl auffaellt."""
    quelle = (__import__("pathlib").Path(reddung.__file__)).read_text(encoding="utf-8")
    assert "_GPS_BLOCK_GS_KT" in quelle and "_GPS_GROUND_AGL_FT" in quelle
    assert "from app.gps_legs import" in quelle or "from .gps_legs import" in quelle
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_parameter.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.reddung'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/reddung.py
# -*- coding: utf-8 -*-
"""Die Parameter einer FriesenReddung: Fundradius, Ziele, Fenster.

Reine Rechnung, keine Datenbank -- alles hier nimmt ein Event-Dict und gibt Zahlen oder Ziele
zurück. Die Abdeckung selbst rechnet ``app/abdeckung.py``; dieses Modul entscheidet nur, MIT
WELCHEN Werten sie gerechnet wird.

**Der Fundradius wird gerechnet, nicht eingestellt.** Eine abgedeckte Zelle heißt „ein Track
lief im Korridor an ihrem MITTELPUNKT vorbei"; ein Havarist in der Zellecke ist noch die halbe
Zelldiagonale weiter weg. Mit ``korridor + kante/√2`` gilt dagegen: jede abgedeckte Zelle
bedeutet „hier hätten wir ihn gesehen", und volle Abdeckung garantiert den Fund. Wäre der
Radius einstellbar, könnte der Admin einen Fortschrittsbalken erzeugen, der lügt.

**Die Höhenschranke ist AGL über dem Havaristen.** ``position_history.altitude`` ist MSL, also
wird die Grundhöhe der Unglücksstelle addiert. Woher die kommt (Messung der Brügge,
Admin-Eingabe, Platzhöhe) entscheidet ``app/database.py``; hier wird sie nur benutzt.
"""
from __future__ import annotations

import math

from app.abdeckung import Fenster, Ziel, zellen_aus_box
from app.gps_legs import _GPS_BLOCK_GS_KT, _GPS_GROUND_AGL_FT

#: Schlüssel des Havaristen in der Zielliste. Er ist ein gewöhnliches Ziel.
HAVARIST = "havarist"

#: Geschwindigkeit, unter der ein Schwebeflug gilt (Aufnehmen ohne Landung). Verlangt
#: praktisch einen Hubschrauber -- ein Flächenflugzeug kommt nicht darunter, ohne zu landen.
SCHWEBE_GS_KT = 30.0

_VORGABE_KANTE_KM = 1.0
_VORGABE_KORRIDOR_KM = 1.0
_VORGABE_HOEHE_FT = 1000.0
_VORGABE_GS_MAX_KT = 140.0
_VORGABE_GS_MIN_KT = 30.0


def _zahl(ev: dict, feld: str, vorgabe: float) -> float:
    wert = ev.get(feld)
    return float(wert) if wert is not None else float(vorgabe)


def fundradius_km(korridor_km: float, kante_km: float) -> float:
    """Korridor plus halbe Zelldiagonale -- s. Modulkopf."""
    return float(korridor_km) + float(kante_km) / math.sqrt(2.0)


def grund_ft(ev: dict) -> float:
    """Geländehöhe (MSL) an der Unglücksstelle; 0, solange nichts bekannt ist."""
    return _zahl(ev, "havarist_grund_ft", 0.0)


def hoehe_schranke_msl(ev: dict) -> float:
    """Die AGL-Schranke, auf MSL umgerechnet -- so kommt sie aus position_history."""
    return grund_ft(ev) + _zahl(ev, "hoehe_max_ft", _VORGABE_HOEHE_FT)


def zellen_fuer(ev: dict) -> list[Ziel]:
    return zellen_aus_box(
        float(ev["sued"]), float(ev["west"]), float(ev["nord"]), float(ev["ost"]),
        kante_km=_zahl(ev, "kante_km", _VORGABE_KANTE_KM),
        korridor_km=_zahl(ev, "korridor_km", _VORGABE_KORRIDOR_KM),
    )


def havarist_ziel(ev: dict) -> Ziel | None:
    lat, lon = ev.get("havarist_lat"), ev.get("havarist_lon")
    if lat is None or lon is None:
        return None
    radius = fundradius_km(_zahl(ev, "korridor_km", _VORGABE_KORRIDOR_KM),
                           _zahl(ev, "kante_km", _VORGABE_KANTE_KM))
    return (HAVARIST, float(lat), float(lon), radius)


def fenster_suchen(ev: dict) -> Fenster:
    return Fenster(
        hoehe_max_ft=hoehe_schranke_msl(ev),
        gs_max_kt=_zahl(ev, "gs_max_kt", _VORGABE_GS_MAX_KT),
        gs_min_kt=_zahl(ev, "gs_min_kt", _VORGABE_GS_MIN_KT),
    )


def fenster_aufnehmen(ev: dict) -> Fenster:
    """Fürs Aufnehmen: die Landeregeln des Projekts, und gs_min_kt MUSS 0 sein.

    ⚠ Die Untergrenze des Suchfensters (30 kt) würde hier genau den Stillstand ausschließen,
    der gefragt ist. Das ist der Fallstrick dieser Funktion.
    """
    mit_landung = bool(ev.get("landung_noetig", 1))
    return Fenster(
        hoehe_max_ft=grund_ft(ev) + _GPS_GROUND_AGL_FT,
        gs_max_kt=float(_GPS_BLOCK_GS_KT) if mit_landung else SCHWEBE_GS_KT,
        gs_min_kt=0.0,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_parameter.py -q`
Expected: PASS, 12 Tests

- [ ] **Step 5: Gegenprobe gegen entschärfte Fassungen**

Jeden dieser drei Eingriffe einzeln vornehmen, Tests laufen lassen (müssen ROT werden),
danach zurücknehmen:

1. `return float(korridor_km)` in `fundradius_km` — erwartet rot in
   `test_der_fundradius_ist_korridor_plus_halbe_zelldiagonale` und
   `test_volle_abdeckung_garantiert_den_fund`.
2. `gs_min_kt=_zahl(ev, "gs_min_kt", ...)` in `fenster_aufnehmen` — erwartet rot in
   `test_das_aufnahmefenster_hat_KEINE_untergrenze`.
3. `gs_max_kt=2.0` (Zahl statt Import) in `fenster_aufnehmen` — erwartet rot in
   `test_die_landeschwellen_werden_importiert_und_nicht_abgeschrieben`.

- [ ] **Step 6: Commit**

```bash
git add app/reddung.py tests/test_reddung_parameter.py
git commit -m "FriesenReddung: Parameter -- der Fundradius wird gerechnet, nicht eingestellt"
```

---

### Task 2: Tabelle und CRUD

**Files:**
- Modify: `app/database.py` — `_DDL` (neue Tabelle), neue Funktionen am Ende des Bummel-/
  Transport-Blocks
- Test: `tests/test_reddung_db.py`

**Interfaces:**
- Consumes: `get_connection`, `_now_utc`, `_effective_dtend`, `_row_to_dict` (alle in
  `app/database.py` vorhanden)
- Produces:
  - `create_reddung_event(conn, *, name, dtstart, dtend=None, sued, west, nord, ost, **felder) -> int`
  - `get_reddung_event(conn, event_id: int) -> dict | None`
  - `list_reddung_events(conn, *, since: str | None = None) -> list[dict]`
  - `update_reddung_event(conn, event_id: int, **felder) -> None`
  - `delete_reddung_event(conn, event_id: int) -> None`
  - `_set_reddung_latch(conn, event_id, spalte, ts, cid=None) -> bool`
  - `set_reddung_gefunden / _aufgenommen(conn, event_id, ts, cid) -> bool`
  - `set_reddung_eingeliefert(conn, event_id, ts, cid, icao) -> bool`
  - `clear_reddung_aufnahme(conn, event_id) -> None`
  - `set_reddung_aufgeloest(conn, event_id, ts) -> bool`
  - `reddung_grund_merken(conn, event_id, hoehe_ft, quelle) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reddung_db.py
# -*- coding: utf-8 -*-
"""Tabelle und Latches der FriesenReddung (20.09.2026)."""
from __future__ import annotations

import pytest

from app.database import (
    clear_reddung_aufnahme, create_reddung_event, delete_reddung_event, get_connection,
    get_reddung_event, init_db, list_reddung_events, set_reddung_aufgeloest,
    set_reddung_aufgenommen, set_reddung_eingeliefert, set_reddung_gefunden,
    reddung_grund_merken, update_reddung_event,
)

SEKTOR = dict(sued=53.54, west=6.95, nord=53.90, ost=7.55)


@pytest.fixture()
def conn(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    c = get_connection(p)
    yield c
    c.close()


def _ev(conn, **extra):
    return create_reddung_event(conn, name="Reddung Probe", dtstart="2026-09-25T17:00:00Z",
                                 **SEKTOR, **extra)


def test_anlegen_und_lesen(conn):
    eid = _ev(conn)
    ev = get_reddung_event(conn, eid)
    assert ev["name"] == "Reddung Probe"
    assert ev["sued"] == 53.54 and ev["ost"] == 7.55


def test_die_vorgaben_stehen_in_der_tabelle(conn):
    """Sie stehen in der DDL, damit eine von Hand angelegte Zeile brauchbar ist."""
    ev = get_reddung_event(conn, _ev(conn))
    assert ev["kante_km"] == 1.0 and ev["korridor_km"] == 1.0
    assert ev["hoehe_max_ft"] == 1000 and ev["gs_max_kt"] == 140 and ev["gs_min_kt"] == 30
    assert ev["aufnehmen_noetig"] == 1 and ev["landung_noetig"] == 1
    assert ev["aufnahme_verfaellt"] == 1
    assert ev["push_enabled"] == 1


def test_dtend_bekommt_den_mitternacht_standard(conn):
    ev = get_reddung_event(conn, _ev(conn))
    assert ev["dtend"] == "2026-09-26T00:00:00Z"


def test_aendern_und_loeschen(conn):
    eid = _ev(conn)
    update_reddung_event(conn, eid, havarist_lat=53.72, havarist_lon=7.25,
                          havarist_art="flugzeug_echo", landung_noetig=0)
    ev = get_reddung_event(conn, eid)
    assert ev["havarist_lat"] == 53.72 and ev["landung_noetig"] == 0
    delete_reddung_event(conn, eid)
    assert get_reddung_event(conn, eid) is None


def test_unbekanntes_feld_wird_abgewiesen(conn):
    """Sonst schreibt ein Tippfehler im Admin still ins Leere."""
    with pytest.raises(ValueError):
        update_reddung_event(conn, _ev(conn), havarost_lat=1.0)


def test_latches_setzen_nur_beim_ersten_mal(conn):
    eid = _ev(conn)
    assert set_reddung_gefunden(conn, eid, "2026-09-25T17:30:00Z", 111) is True
    assert set_reddung_gefunden(conn, eid, "2026-09-25T17:45:00Z", 222) is False
    ev = get_reddung_event(conn, eid)
    assert ev["gefunden_von"] == 111 and ev["gefunden_am"] == "2026-09-25T17:30:00Z"


def test_der_aufnehmende_muss_nicht_der_finder_sein(conn):
    eid = _ev(conn)
    set_reddung_gefunden(conn, eid, "2026-09-25T17:30:00Z", 111)
    assert set_reddung_aufgenommen(conn, eid, "2026-09-25T17:50:00Z", 222) is True
    assert get_reddung_event(conn, eid)["aufgenommen_von"] == 222


def test_einliefern_merkt_den_platz(conn):
    eid = _ev(conn)
    assert set_reddung_eingeliefert(conn, eid, "2026-09-25T18:20:00Z", 222, "EDWF") is True
    ev = get_reddung_event(conn, eid)
    assert ev["eingeliefert_icao"] == "EDWF" and ev["eingeliefert_von"] == 222


def test_aufnahme_zuruecknehmen_macht_den_latch_wieder_frei(conn):
    """Bricht der Aufnehmende ab, muss ein anderer uebernehmen koennen."""
    eid = _ev(conn)
    set_reddung_aufgenommen(conn, eid, "2026-09-25T17:50:00Z", 222)
    clear_reddung_aufnahme(conn, eid)
    ev = get_reddung_event(conn, eid)
    assert ev["aufgenommen_am"] is None and ev["aufgenommen_von"] is None
    assert set_reddung_aufgenommen(conn, eid, "2026-09-25T18:05:00Z", 333) is True


def test_grundhoehe_merken_und_ihre_herkunft(conn):
    eid = _ev(conn)
    assert reddung_grund_merken(conn, eid, 20.0, "gemessen") is True
    ev = get_reddung_event(conn, eid)
    assert ev["havarist_grund_ft"] == 20.0 and ev["havarist_grund_quelle"] == "gemessen"


def test_eine_messung_ueberschreibt_eine_schaetzung_aber_nicht_umgekehrt(conn):
    """Die Messung der Bruegge ist die beste Quelle. Eine spaetere Platzhoehe darf sie
    nicht verdraengen -- sonst kippt die Hoehenschranke mitten im Abend."""
    eid = _ev(conn)
    reddung_grund_merken(conn, eid, 45.0, "platz")
    assert reddung_grund_merken(conn, eid, 20.0, "gemessen") is True
    assert get_reddung_event(conn, eid)["havarist_grund_ft"] == 20.0
    assert reddung_grund_merken(conn, eid, 45.0, "platz") is False
    assert get_reddung_event(conn, eid)["havarist_grund_ft"] == 20.0


def test_auflösen_ist_ebenfalls_ein_latch(conn):
    eid = _ev(conn)
    assert set_reddung_aufgeloest(conn, eid, "2026-09-26T00:00:00Z") is True
    assert set_reddung_aufgeloest(conn, eid, "2026-09-26T00:05:00Z") is False


def test_liste_filtert_nach_zeit(conn):
    _ev(conn)
    assert len(list_reddung_events(conn)) == 1
    assert list_reddung_events(conn, since="2026-10-01T00:00:00Z") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_db.py -q`
Expected: FAIL — `ImportError: cannot import name 'create_reddung_event'`

- [ ] **Step 3: Write minimal implementation**

In `app/database.py`, in `_DDL` hinter `CREATE TABLE IF NOT EXISTS transport_cargo_losses (...)`
einfügen (die Kommentare gehören dazu — die Spalten `havarist_lat`/`havarist_lon` sind die
einzigen im Projekt, die eine geheim zu haltende Koordinate führen):

```sql
-- Eventtyp FriesenReddung (#21): Ein Havarist liegt irgendwo im Sektor, die Gruppe sucht ihn.
--
-- ⚠ `havarist_lat`/`havarist_lon` gehen an die FriesenBruegge (sie muss das Objekt
-- hinstellen) und in den Admin -- aber an KEINEN Endpunkt, den ein Browser eines Piloten
-- erreicht. Wer eine Wertungsfunktion schreibt, gibt sie nicht heraus; tests/test_reddung_db.py
-- und tests/test_reddung_api.py halten das fest.
--
-- Zwei verschachtelte Haken steuern den Zuschnitt des Abends:
--   aufnehmen_noetig = 0  -> der Fund ist der Schluss
--   aufnehmen_noetig = 1, landung_noetig = 1 -> Landung an der Unglueckstelle, dann einliefern
--   aufnehmen_noetig = 1, landung_noetig = 0 -> Schwebeflug (Hubschrauber), dann einliefern
CREATE TABLE IF NOT EXISTS reddung_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    dtstart         TEXT NOT NULL,
    dtend           TEXT NOT NULL,
    sued            REAL NOT NULL,
    west            REAL NOT NULL,
    nord            REAL NOT NULL,
    ost             REAL NOT NULL,
    kante_km        REAL DEFAULT 1.0,
    korridor_km     REAL DEFAULT 1.0,
    hoehe_max_ft    REAL DEFAULT 1000,      -- AGL UEBER DEM HAVARISTEN, nicht MSL
    gs_max_kt       REAL DEFAULT 140,
    gs_min_kt       REAL DEFAULT 30,
    havarist_lat    REAL,
    havarist_lon    REAL,
    havarist_art    TEXT,                   -- Art aus bruegge_art; NULL = 'flugzeug_echo'
    havarist_grund_ft REAL,                 -- Gelaendehoehe MSL an der Unglueckstelle
    havarist_grund_quelle TEXT,             -- 'gemessen' | 'admin' | 'platz'
    aufnehmen_noetig INTEGER DEFAULT 1,
    landung_noetig  INTEGER DEFAULT 1,
    aufnahme_verfaellt INTEGER DEFAULT 1,
    gefunden_am     TEXT,  gefunden_von     INTEGER,
    aufgenommen_am  TEXT,  aufgenommen_von  INTEGER,
    eingeliefert_am TEXT,  eingeliefert_von INTEGER,  eingeliefert_icao TEXT,
    aufgeloest_am   TEXT,
    source          TEXT,
    calendar_uid    TEXT UNIQUE,
    push_enabled    INTEGER DEFAULT 1,
    badge_name      TEXT,
    manual_fields   TEXT,
    created_at      TEXT
);
```

Und die Funktionen (ans Ende des Transport-Blocks, vor `aggregate_bummel_kpis`):

```python
# ---------------------------------------------------------------------------
# FriesenReddung (#21)
# ---------------------------------------------------------------------------

#: Felder, die `update_reddung_event` schreiben darf. Eine Positivliste, damit ein Tippfehler
#: im Admin einen Fehler auslöst statt still ins Leere zu schreiben.
_REDDUNG_FELDER = {
    "name", "dtstart", "dtend", "sued", "west", "nord", "ost", "kante_km", "korridor_km",
    "hoehe_max_ft", "gs_max_kt", "gs_min_kt", "havarist_lat", "havarist_lon", "havarist_art",
    "havarist_grund_ft", "havarist_grund_quelle", "aufnehmen_noetig", "landung_noetig",
    "aufnahme_verfaellt", "source", "calendar_uid", "push_enabled", "badge_name",
    "manual_fields",
}

#: Rangfolge der Quellen für `havarist_grund_ft` — eine Messung schlägt jede Schätzung.
_GRUND_RANG = {"platz": 1, "admin": 2, "gemessen": 3}


def create_reddung_event(conn: sqlite3.Connection, *, name: str, dtstart: str,
                          sued: float, west: float, nord: float, ost: float,
                          dtend: str | None = None, **felder) -> int:
    unbekannt = set(felder) - _REDDUNG_FELDER
    if unbekannt:
        raise ValueError(f"unbekannte Felder: {sorted(unbekannt)}")
    spalten = ["name", "dtstart", "dtend", "sued", "west", "nord", "ost", "created_at"]
    werte: list = [name, dtstart, _effective_dtend(dtstart, dtend),
                   float(sued), float(west), float(nord), float(ost), _now_utc()]
    for k, v in felder.items():
        spalten.append(k)
        werte.append(v)
    cur = conn.execute(
        f"INSERT INTO reddung_events ({', '.join(spalten)}) "
        f"VALUES ({', '.join('?' * len(spalten))})", werte)
    return int(cur.lastrowid)


def get_reddung_event(conn: sqlite3.Connection, event_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM reddung_events WHERE id = ?", (int(event_id),)).fetchone()
    return _row_to_dict(row) if row else None


def list_reddung_events(conn: sqlite3.Connection, *, since: str | None = None) -> list[dict]:
    if since:
        rows = conn.execute("SELECT * FROM reddung_events WHERE dtend >= ? ORDER BY dtstart DESC",
                            (since,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM reddung_events ORDER BY dtstart DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def update_reddung_event(conn: sqlite3.Connection, event_id: int, **felder) -> None:
    unbekannt = set(felder) - _REDDUNG_FELDER
    if unbekannt:
        raise ValueError(f"unbekannte Felder: {sorted(unbekannt)}")
    if not felder:
        return
    satz = ", ".join(f"{k} = ?" for k in felder)
    conn.execute(f"UPDATE reddung_events SET {satz} WHERE id = ?",
                 [*felder.values(), int(event_id)])


def delete_reddung_event(conn: sqlite3.Connection, event_id: int) -> None:
    conn.execute("DELETE FROM reddung_events WHERE id = ?", (int(event_id),))


def _set_reddung_latch(conn: sqlite3.Connection, event_id: int, spalte: str, ts: str,
                        cid: int | None = None, icao: str | None = None) -> bool:
    """Latch setzen, nur wenn noch NULL. True, wenn in diesem Aufruf neu gesetzt.

    Muster wie `_set_transport_latch`: Die Bedingung `IS NULL` im UPDATE macht das Setzen
    atomar -- zwei Poller-Takte gleichzeitig können nicht beide gewinnen.
    """
    spalten, werte = [f"{spalte}_am = ?"], [ts]
    if cid is not None:
        spalten.append(f"{spalte}_von = ?")
        werte.append(int(cid))
    if icao is not None:
        spalten.append(f"{spalte}_icao = ?")
        werte.append(icao)
    cur = conn.execute(
        f"UPDATE reddung_events SET {', '.join(spalten)} "
        f"WHERE id = ? AND {spalte}_am IS NULL", [*werte, int(event_id)])
    return (cur.rowcount or 0) > 0


def set_reddung_gefunden(conn, event_id: int, ts: str, cid: int) -> bool:
    return _set_reddung_latch(conn, event_id, "gefunden", ts, cid)


def set_reddung_aufgenommen(conn, event_id: int, ts: str, cid: int) -> bool:
    return _set_reddung_latch(conn, event_id, "aufgenommen", ts, cid)


def set_reddung_eingeliefert(conn, event_id: int, ts: str, cid: int, icao: str) -> bool:
    return _set_reddung_latch(conn, event_id, "eingeliefert", ts, cid, icao)


def set_reddung_aufgeloest(conn, event_id: int, ts: str) -> bool:
    cur = conn.execute("UPDATE reddung_events SET aufgeloest_am = ? "
                       "WHERE id = ? AND aufgeloest_am IS NULL", (ts, int(event_id)))
    return (cur.rowcount or 0) > 0


def clear_reddung_aufnahme(conn: sqlite3.Connection, event_id: int) -> None:
    """Die Aufnahme freigeben -- der Aufnehmende hat abgebrochen oder der Admin greift ein."""
    conn.execute("UPDATE reddung_events SET aufgenommen_am = NULL, aufgenommen_von = NULL "
                 "WHERE id = ?", (int(event_id),))


def reddung_grund_merken(conn: sqlite3.Connection, event_id: int, hoehe_ft: float,
                          quelle: str) -> bool:
    """Grundhöhe eintragen, wenn die Quelle mindestens so gut ist wie die vorhandene.

    ⚠ Eine Messung der Brügge darf nicht später von einer geschätzten Platzhöhe verdrängt
    werden -- sonst kippt die Höhenschranke mitten im Abend, und niemand versteht, warum ein
    Überflug plötzlich nicht mehr zählt.
    """
    ev = get_reddung_event(conn, event_id)
    if ev is None:
        return False
    alt = _GRUND_RANG.get(ev.get("havarist_grund_quelle") or "", 0)
    neu = _GRUND_RANG.get(quelle, 0)
    if ev.get("havarist_grund_ft") is not None and neu < alt:
        return False
    conn.execute("UPDATE reddung_events SET havarist_grund_ft = ?, havarist_grund_quelle = ? "
                 "WHERE id = ?", (float(hoehe_ft), quelle, int(event_id)))
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_db.py -q`
Expected: PASS, 13 Tests

- [ ] **Step 5: Gegenprobe**

1. In `_set_reddung_latch` das `AND {spalte}_am IS NULL` entfernen — erwartet rot in
   `test_latches_setzen_nur_beim_ersten_mal`.
2. In `reddung_grund_merken` den Rangvergleich entfernen — erwartet rot in
   `test_eine_messung_ueberschreibt_eine_schaetzung_aber_nicht_umgekehrt`.
3. In `update_reddung_event` die Positivliste nicht prüfen — erwartet rot in
   `test_unbekanntes_feld_wird_abgewiesen`.

- [ ] **Step 6: Commit**

```bash
git add app/database.py tests/test_reddung_db.py
git commit -m "FriesenReddung: Tabelle, CRUD und Latches"
```

---

### Task 3: Der Stand einer FriesenReddung — Abdeckung, Fund, Beiträge

**Files:**
- Modify: `app/database.py` — hinter den CRUD-Funktionen aus Task 2
- Test: `tests/test_reddung_db.py` (anfügen)

**Interfaces:**
- Consumes: `create_reddung_event`, `get_reddung_event` (Task 2);
  `app.reddung.zellen_fuer / havarist_ziel / fenster_suchen` (Task 1);
  `app.abdeckung.abdeckung`; `get_all_position_history` (vorhanden)
- Produces:
  - `reddung_spuren(conn, start: str, end: str, *, ab: str | None = None, callsign_prefix: str = "FRS") -> list[tuple[int, list]]`
  - `compute_reddung_stand(conn, ev: dict) -> dict` mit den Schlüsseln
    `id, name, anteil, zellen, abgedeckt, offen, je_pilot, gefunden, aufgenommen,
    eingeliefert, aufgeloest, sektor, fundradius_km, dauer_min`

- [ ] **Step 1: Write the failing test** (an `tests/test_reddung_db.py` anfügen)

```python
# --- Stand einer FriesenReddung -------------------------------------------------

import math

from app.database import compute_reddung_stand, reddung_spuren, upsert_pilot

LAT, LON = 53.72, 7.25
GRAD_KM_LAT = 1.0 / 111.32
GRAD_KM_LON = 1.0 / (111.32 * math.cos(math.radians(LAT)))


def _kleiner_sektor(conn, **extra):
    """4 x 4 km, damit die Tests wenige Zellen haben und lesbar bleiben."""
    return create_reddung_event(
        conn, name="Reddung Probe", dtstart="2026-09-25T17:00:00Z",
        dtend="2026-09-25T20:00:00Z",
        sued=LAT - 2 * GRAD_KM_LAT, west=LON - 2 * GRAD_KM_LON,
        nord=LAT + 2 * GRAD_KM_LAT, ost=LON + 2 * GRAD_KM_LON,
        havarist_lat=LAT, havarist_lon=LON, havarist_grund_ft=10.0, **extra)


def _spur(conn, cid, punkte):
    upsert_pilot(conn, {"cid": cid, "name": f"Pilot {cid}"})
    for lat, lon, ts in punkte:
        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, "
            "groundspeed, heading, ts) VALUES (?,?,?,?,?,?,?,?)",
            (cid, f"FRS{cid}", lat, lon, 900, 110, 90, ts))


def test_ohne_spuren_ist_nichts_abgedeckt(conn):
    ev = get_reddung_event(conn, _kleiner_sektor(conn))
    stand = compute_reddung_stand(conn, ev)
    assert stand["anteil"] == 0.0 and stand["abgedeckt"] == 0
    assert stand["zellen"] > 0 and stand["gefunden"] is None


def test_ein_ueberflug_deckt_zellen_ab_und_findet(conn):
    eid = _kleiner_sektor(conn)
    _spur(conn, 111, [
        (LAT, LON - 2 * GRAD_KM_LON, "2026-09-25T17:10:00Z"),
        (LAT, LON - 1 * GRAD_KM_LON, "2026-09-25T17:10:15Z"),
        (LAT, LON, "2026-09-25T17:10:30Z"),
        (LAT, LON + 1 * GRAD_KM_LON, "2026-09-25T17:10:45Z"),
    ])
    stand = compute_reddung_stand(conn, get_reddung_event(conn, eid))
    assert stand["abgedeckt"] > 0 and 0 < stand["anteil"] <= 1
    assert stand["gefunden"]["cid"] == 111
    assert stand["gefunden"]["name"] == "Pilot 111"
    assert stand["je_pilot"][0]["cid"] == 111 and stand["je_pilot"][0]["zellen"] > 0


def test_zu_hoch_findet_nicht(conn):
    """1000 ft AGL bei 10 ft Gelaende -- 2000 ft MSL ist darueber."""
    eid = _kleiner_sektor(conn)
    _spur(conn, 111, [(LAT, LON - GRAD_KM_LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON, "2026-09-25T17:10:15Z")])
    conn.execute("UPDATE position_history SET altitude = 2000 WHERE cid = 111")
    stand = compute_reddung_stand(conn, get_reddung_event(conn, eid))
    assert stand["gefunden"] is None and stand["abgedeckt"] == 0


def test_die_grundhoehe_verschiebt_die_schranke(conn):
    """Dieselbe Spur, dasselbe Flugzeug -- nur die Unglueckstelle liegt hoeher. Das ist der
    Kern der AGL-Umstellung: ueber einem Berg gilt eine andere MSL-Schranke."""
    eid = _kleiner_sektor(conn)
    _spur(conn, 111, [(LAT, LON - GRAD_KM_LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON, "2026-09-25T17:10:15Z")])
    conn.execute("UPDATE position_history SET altitude = 1800 WHERE cid = 111")
    assert compute_reddung_stand(conn, get_reddung_event(conn, eid))["gefunden"] is None
    update_reddung_event(conn, eid, havarist_grund_ft=1000.0)
    assert compute_reddung_stand(conn, get_reddung_event(conn, eid))["gefunden"] is not None


def test_der_stand_enthaelt_NIEMALS_die_koordinate_des_havaristen(conn):
    """⚠ Die Kernanforderung aus #21. Dieser Test ist der Riegel: Was hier durchkommt, geht
    spaeter in eine API-Antwort."""
    import json
    eid = _kleiner_sektor(conn)
    _spur(conn, 111, [(LAT, LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON + GRAD_KM_LON, "2026-09-25T17:10:15Z")])
    stand = compute_reddung_stand(conn, get_reddung_event(conn, eid))
    text = json.dumps(stand)
    for zahl in (f"{LAT:.4f}", f"{LON:.4f}"):
        assert zahl not in text, f"Koordinate {zahl} steht im Stand"
    assert "havarist_lat" not in text and "havarist_lon" not in text
    # Der Sektor dagegen IST oeffentlich -- ohne ihn weiss niemand, wo zu suchen ist.
    assert stand["sektor"]["sued"] < stand["sektor"]["nord"]


def test_die_dauer_zaehlt_vom_fund_bis_zur_einlieferung(conn):
    eid = _kleiner_sektor(conn)
    set_reddung_gefunden(conn, eid, "2026-09-25T17:30:00Z", 111)
    set_reddung_eingeliefert(conn, eid, "2026-09-25T18:12:00Z", 222, "EDWF")
    upsert_pilot(conn, {"cid": 222, "name": "Pilot 222"})
    stand = compute_reddung_stand(conn, get_reddung_event(conn, eid))
    assert stand["dauer_min"] == 42
    assert stand["eingeliefert"]["icao"] == "EDWF"


def test_spuren_beginnen_erst_ab_einem_zeitpunkt_wenn_verlangt(conn):
    """Fuers Aufnehmen zaehlen nur Punkte NACH dem Fund."""
    _spur(conn, 111, [(LAT, LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON, "2026-09-25T17:40:00Z")])
    alle = reddung_spuren(conn, "2026-09-25T17:00:00Z", "2026-09-25T20:00:00Z")
    danach = reddung_spuren(conn, "2026-09-25T17:00:00Z", "2026-09-25T20:00:00Z",
                             ab="2026-09-25T17:30:00Z")
    assert len(alle[0][1]) == 2 and len(danach[0][1]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_db.py -q`
Expected: FAIL — `ImportError: cannot import name 'compute_reddung_stand'`

- [ ] **Step 3: Write minimal implementation**

```python
def reddung_spuren(conn: sqlite3.Connection, start: str, end: str, *,
                    ab: str | None = None, callsign_prefix: str = "FRS") -> list[tuple[int, list]]:
    """Spuren für eine FriesenReddung, in der Form, die ``app/abdeckung.py`` erwartet.

    ``ab`` schneidet vorn ab -- fürs Aufnehmen zählen nur Punkte NACH dem Fund. Es wird hier
    und nicht beim Aufrufer gefiltert, damit niemand versehentlich den Überflug des Finders
    selbst als Aufnahme wertet.
    """
    von = max(start, ab) if ab else start
    rows = conn.execute(
        "SELECT cid, latitude, longitude, altitude, groundspeed, ts FROM position_history "
        "WHERE ts >= ? AND ts <= ? ORDER BY cid, ts", (von, end)).fetchall()
    je_cid: dict[int, list] = {}
    for cid, lat, lon, alt, gs, ts in rows:
        je_cid.setdefault(int(cid), []).append(
            (lat, lon, float(alt) if alt is not None else None,
             float(gs) if gs is not None else None, ts))
    return [(cid, punkte) for cid, punkte in je_cid.items()]


def compute_reddung_stand(conn: sqlite3.Connection, ev: dict) -> dict:
    """Der Stand einer FriesenReddung: Abdeckung, Beiträge, Latches.

    ⚠ **Gibt NIE die Koordinate des Havaristen heraus** (#21). Der Rückgabewert dieser Funktion
    geht in API-Antworten; `tests/test_reddung_db.py` hält es fest.
    """
    from app import reddung as rd
    from app.abdeckung import abdeckung

    zellen = sf.zellen_fuer(ev)
    spuren = reddung_spuren(conn, ev["dtstart"], ev["dtend"])
    erg = abdeckung(spuren, zellen, sf.fenster_suchen(ev))

    namen = {int(r[0]): r[1] for r in conn.execute("SELECT cid, name FROM pilots").fetchall()}
    je_pilot = sorted(
        ({"cid": cid, "name": namen.get(cid) or str(cid), "zellen": n}
         for cid, n in erg.je_pilot.items()),
        key=lambda p: (-p["zellen"], p["cid"]))

    def wer(spalte: str) -> dict | None:
        ts, cid = ev.get(f"{spalte}_am"), ev.get(f"{spalte}_von")
        if not ts:
            return None
        eintrag = {"cid": cid, "name": namen.get(cid) or str(cid), "ts": ts}
        if spalte == "eingeliefert":
            eintrag["icao"] = ev.get("eingeliefert_icao")
        return eintrag

    dauer = None
    if ev.get("gefunden_am") and ev.get("eingeliefert_am"):
        dauer = int(round(
            (_parse_iso(ev["eingeliefert_am"]) - _parse_iso(ev["gefunden_am"])).total_seconds() / 60))

    return {
        "id": ev["id"],
        "name": ev.get("name") or "FriesenReddung",
        "anteil": erg.anteil,
        "zellen": len(zellen),
        "abgedeckt": len(erg.treffer),
        "offen": len(erg.offen),
        "je_pilot": je_pilot,
        "gefunden": wer("gefunden"),
        "aufgenommen": wer("aufgenommen"),
        "eingeliefert": wer("eingeliefert"),
        "aufgeloest": bool(ev.get("aufgeloest_am")),
        "fundradius_km": round(sf.fundradius_km(
            float(ev.get("korridor_km") or 1.0), float(ev.get("kante_km") or 1.0)), 3),
        "sektor": {k: ev[k] for k in ("sued", "west", "nord", "ost")},
        "dauer_min": dauer,
    }
```

⚠ **Der Havarist steht NICHT in `zellen`.** Der Fund wird im Poller (Task 6) mit einem eigenen
Aufruf gegen `havarist_ziel(ev)` gerechnet und gelatcht; `compute_reddung_stand` liest ihn nur
aus der Tabelle. Sonst müsste diese Funktion die Koordinate anfassen, und der Riegel oben wäre
eine Frage der Sorgfalt statt eine Eigenschaft des Aufbaus.

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_db.py -q`
Expected: PASS, 20 Tests

- [ ] **Step 5: Gegenprobe**

1. In `compute_reddung_stand` `"havarist": sf.havarist_ziel(ev)` ins Rückgabe-Dict aufnehmen —
   erwartet rot in `test_der_stand_enthaelt_NIEMALS_die_koordinate_des_havaristen`.
2. `ab` in `reddung_spuren` ignorieren — erwartet rot in
   `test_spuren_beginnen_erst_ab_einem_zeitpunkt_wenn_verlangt`.
3. In `app/reddung.py` `hoehe_schranke_msl` auf `_zahl(ev, "hoehe_max_ft", 1000)` (ohne
   Grundhöhe) ändern — erwartet rot in `test_die_grundhoehe_verschiebt_die_schranke`.

- [ ] **Step 6: Commit**

```bash
git add app/database.py tests/test_reddung_db.py
git commit -m "FriesenReddung: Stand rechnen -- Abdeckung, Beitraege, Latches (ohne Koordinate)"
```

---

### Task 4: `bruegge_soll` lernt den Simulator

**Files:**
- Modify: `app/database.py` — `_DDL` (Spalte), neue Migrationsliste, `bruegge_soll_fuer`,
  `bruegge_soll_setzen`
- Modify: `app/main.py` — Aufruf von `bruegge_soll_fuer` im Melde-Endpunkt
- Test: `tests/test_reddung_objekte.py`

**Warum:** Keine Bootsart ist in allen drei Simulatoren aktiv (`boot_klein` fehlt in MSFS 2024,
`schiff_segel` in MSFS 2020). Ein Havarist mit einer solchen Art würde bei der Hälfte der Piloten
stumm nicht erscheinen. Die vier Flugzeugarten sind überall aktiv — für den Normalfall braucht es
das hier also nicht, aber ohne diese Spalte ist der Sonderfall unbaubar.

**Interfaces:**
- Produces:
  - `bruegge_soll_fuer(conn, cid: int, simulator: str | None = None) -> list[dict]` — zusätzlicher
    Parameter, Vorgabe `None` = wie bisher alles
  - `bruegge_soll_setzen(..., simulator: str | None = None)` — zusätzliches Schlüsselwort

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reddung_objekte.py
# -*- coding: utf-8 -*-
"""Havarist und Fackeln als Bruegge-Objekte (20.09.2026)."""
from __future__ import annotations

import pytest

from app.database import (
    bruegge_soll_fuer, bruegge_soll_setzen, get_connection, init_db,
)


@pytest.fixture()
def conn(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    c = get_connection(p)
    yield c
    c.close()


def test_ohne_simulator_gilt_ein_objekt_fuer_alle(conn):
    bruegge_soll_setzen(conn, "havarist-1", "flugzeug_echo", 53.7, 7.2)
    for sim in ("msfs2020", "msfs2024", "xplane12"):
        assert len(bruegge_soll_fuer(conn, 111, sim)) == 1


def test_mit_simulator_sieht_es_nur_dieser(conn):
    bruegge_soll_setzen(conn, "havarist-2020", "boot_klein", 53.7, 7.2, simulator="msfs2020")
    bruegge_soll_setzen(conn, "havarist-2024", "schiff_segel", 53.7, 7.2, simulator="msfs2024")
    ids_2020 = [o["id"] for o in bruegge_soll_fuer(conn, 111, "msfs2020")]
    ids_2024 = [o["id"] for o in bruegge_soll_fuer(conn, 111, "msfs2024")]
    assert ids_2020 == ["havarist-2020"] and ids_2024 == ["havarist-2024"]
    assert bruegge_soll_fuer(conn, 111, "xplane12") == []


def test_ohne_angabe_des_simulators_kommt_weiterhin_alles(conn):
    """Abwaertskompatibel: Wer den Parameter nicht angibt, bekommt wie bisher alles. Sonst
    verschwaenden aeltere Aufrufer still Objekte."""
    bruegge_soll_setzen(conn, "a", "flugzeug_echo", 53.7, 7.2, simulator="msfs2020")
    assert len(bruegge_soll_fuer(conn, 111)) == 1


def test_der_melde_endpunkt_filtert_nach_simulator():
    """Verankert am Quelltext: Wer den Parameter beim Aufruf wieder wegnimmt, liefert
    2020-Piloten Objekte aus, die sie nicht setzen koennen."""
    import pathlib
    quelle = pathlib.Path("app/main.py").read_text(encoding="utf-8")
    assert "bruegge_soll_fuer(conn, cid, simulator)" in quelle
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_objekte.py -q`
Expected: FAIL — `TypeError: bruegge_soll_fuer() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Write minimal implementation**

In `_DDL` bei `CREATE TABLE IF NOT EXISTS bruegge_soll` die Spalte ergänzen (mit Kommentar):

```sql
    -- Fuer WELCHEN Simulator gilt der Eintrag? NULL = fuer alle.
    --
    -- Gebraucht, weil eine Art nicht in jedem Simulator einen aktiven Titel hat: `boot_klein`
    -- fehlt in MSFS 2024, `schiff_segel` in MSFS 2020. Ohne diese Spalte erschiene ein solches
    -- Objekt bei der Haelfte der Piloten stumm nicht -- der Server schickt die Art, die Bruegge
    -- findet keinen Titel und schweigt. Mit ihr setzt der Server je Simulator eine passende Art.
    simulator     TEXT,
```

Dazu eine Migrationsliste neben den vorhandenen und ihre Anwendung in `init_db`:

```python
_BRUEGGE_SOLL_MIGRATIONS = [
    "ALTER TABLE bruegge_soll ADD COLUMN simulator TEXT",
]
```

```python
        for stmt in _BRUEGGE_SOLL_MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
```

`bruegge_soll_fuer` und `bruegge_soll_setzen` erweitern:

```python
def bruegge_soll_fuer(conn: sqlite3.Connection, cid: int,
                      simulator: str | None = None) -> list[dict]:
    """Was soll bei diesem Piloten stehen?

    Abgelaufene Eintraege fallen weg, ohne geloescht zu werden -- ein Event kann so vorbereitet
    und mit einem Zeitfenster versehen werden, ohne dass jemand hinterherraeumen muss.

    ``simulator`` filtert zusaetzlich: Ein Eintrag mit gesetztem ``simulator`` gilt nur dort.
    Ohne Angabe kommt alles -- abwaertskompatibel, damit ein aelterer Aufrufer nicht still
    Objekte verliert.
    """
    now = _now_utc()
    if simulator:
        rows = conn.execute(
            "SELECT id, art, lat, lon, kurs, erwartete_hoehe_ft, auf_boden FROM bruegge_soll "
            "WHERE (cid IS NULL OR cid = ?) AND (gilt_bis IS NULL OR gilt_bis > ?) "
            "  AND (simulator IS NULL OR simulator = ?) ORDER BY id",
            (int(cid), now, simulator)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, art, lat, lon, kurs, erwartete_hoehe_ft, auf_boden FROM bruegge_soll "
            "WHERE (cid IS NULL OR cid = ?) AND (gilt_bis IS NULL OR gilt_bis > ?) ORDER BY id",
            (int(cid), now)).fetchall()
    return [_row_to_dict(r) for r in rows]
```

In `bruegge_soll_setzen` das Schlüsselwort `simulator: str | None = None` ergänzen, in die
`INSERT`-Spaltenliste aufnehmen und im `ON CONFLICT`-Zweig mit
`simulator = excluded.simulator` nachziehen.

In `app/main.py` den Aufruf im Melde-Endpunkt ändern:

```python
        soll = bruegge_soll_fuer(conn, cid, simulator)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_objekte.py tests/test_bruegge_endpunkt.py -q`
Expected: PASS — beide Dateien, keine Regression im Melde-Endpunkt

- [ ] **Step 5: Commit**

```bash
git add app/database.py app/main.py tests/test_reddung_objekte.py
git commit -m "bruegge_soll kennt den Simulator -- eine Art, die dort keinen Titel hat, kommt gar nicht erst an"
```

---

### Task 5: Havarist und Fackeln als Brügge-Objekte

**Files:**
- Modify: `app/database.py` — `_DDL` (Spalte `bruegge_steht.hoehe_gemessen`), Migrationsliste,
  `bruegge_steht_melden`, neue Funktionen `reddung_objekte_abgleichen`, `reddung_grund_lernen`
- Modify: `app/main.py` — `hoehe_gemessen` aus der Meldung lesen
- Test: `tests/test_reddung_objekte.py` (anfügen)

**⚠ Zuerst ein Fund, der den Rest erst richtig macht:** `hoehe_gemessen` wird bisher **nirgends
gespeichert**. Das Protokoll definiert es (Abschnitt 1), die X-Plane-Brügge sendet es, und der
Server wirft es weg. Ohne die Spalte setzt eine ungemessene `0,0`-Meldung die Grundhöhe falsch —
und zwar so, dass es aussieht wie ein Wattobjekt auf Meereshöhe.

**Interfaces:**
- Consumes: `bruegge_soll_setzen` mit `simulator` (Task 4), `bruegge_titel_fuer` (vorhanden),
  `reddung_grund_merken` (Task 2), `app.reddung.HAVARIST`
- Produces:
  - `reddung_objekte_abgleichen(conn, ev: dict) -> list[str]` — die gesetzten Soll-IDs
  - `reddung_grund_lernen(conn, ev: dict) -> bool`
  - Konstanten `_REDDUNG_SIMULATOREN`, `_HAVARIST_VORGABE_ART`, `_HAVARIST_ERSATZ`,
    `_GRUND_MESS_MAX_KM`

- [ ] **Step 1: Write the failing test** (an `tests/test_reddung_objekte.py` anfügen)

```python
# --- Havarist, Fackeln, Grundhoehe ----------------------------------------

from app.database import (
    create_reddung_event, get_reddung_event, reddung_grund_lernen,
    reddung_objekte_abgleichen, set_reddung_aufgenommen, set_reddung_gefunden,
    set_reddung_aufgeloest, update_reddung_event,
)

SEKTOR = dict(sued=53.54, west=6.95, nord=53.90, ost=7.55)


def _art(conn, art, simulatoren, titel="T"):
    conn.execute("INSERT OR REPLACE INTO bruegge_art (art, bedeutung, status, angelegt_am) "
                 "VALUES (?,?,'aktiv','2026-09-20T00:00:00Z')", (art, art))
    for sim in simulatoren:
        conn.execute(
            "INSERT OR REPLACE INTO bruegge_katalog (simulator, titel, art, rang, status, quelle) "
            "VALUES (?,?,?,1,'aktiv','bord')", (sim, f"{titel}-{sim}", art))


def _ev(conn, **extra):
    eid = create_reddung_event(conn, name="Reddung Probe", dtstart="2026-09-25T17:00:00Z",
                               dtend="2026-09-25T22:00:00Z", **SEKTOR,
                               havarist_lat=53.72, havarist_lon=7.25, **extra)
    return get_reddung_event(conn, eid)


def test_eine_art_fuer_alle_simulatoren_gibt_eine_zeile(conn):
    """Der Normalfall -- flugzeug_echo laeuft ueberall."""
    _art(conn, "flugzeug_echo", ("msfs2020", "msfs2024", "xplane12"))
    ev = _ev(conn)
    ids = reddung_objekte_abgleichen(conn, ev)
    zeilen = conn.execute("SELECT id, art, simulator, auf_boden, gilt_bis FROM bruegge_soll "
                          "ORDER BY id").fetchall()
    assert len(zeilen) == 1 and zeilen[0][0] in ids
    assert zeilen[0][1] == "flugzeug_echo"
    assert zeilen[0][2] is None, "eine Art fuer alle braucht keinen Simulatorfilter"
    assert zeilen[0][3] == 1, "OnGround wie bei den Booten (15.6.1)"
    assert zeilen[0][4] == "2026-09-25T22:00:00Z", "laeuft mit dtend von selbst ab"


def test_eine_luckenhafte_art_wird_je_simulator_ersetzt(conn):
    """boot_klein gibt es in MSFS 2024 nicht -- dort muss eine andere Art einspringen,
    sonst erscheint bei der Haelfte der Piloten stumm nichts."""
    _art(conn, "boot_klein", ("msfs2020", "xplane12"))
    _art(conn, "schnellboot", ("msfs2024",))
    ev = _ev(conn, havarist_art="boot_klein")
    reddung_objekte_abgleichen(conn, ev)
    je_sim = dict(conn.execute(
        "SELECT simulator, art FROM bruegge_soll WHERE id LIKE '%havarist%'").fetchall())
    assert je_sim["msfs2024"] == "schnellboot"
    assert je_sim["msfs2020"] == "boot_klein" and je_sim["xplane12"] == "boot_klein"


def test_ohne_fund_gibt_es_keine_fackel(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    reddung_objekte_abgleichen(conn, _ev(conn))
    assert conn.execute("SELECT count(*) FROM bruegge_soll WHERE art LIKE 'rauch%'").fetchone()[0] == 0


def test_nach_dem_fund_steht_die_orange_fackel(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    _art(conn, "rauch_signalorange", ("msfs2024",))
    ev = _ev(conn)
    set_reddung_gefunden(conn, ev["id"], "2026-09-25T17:30:00Z", 111)
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    arten = [r[0] for r in conn.execute(
        "SELECT art FROM bruegge_soll WHERE art LIKE 'rauch%'").fetchall()]
    assert arten == ["rauch_signalorange"]


def test_nach_der_aufnahme_wechselt_die_fackel_auf_hellblau(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    _art(conn, "rauch_signalorange", ("msfs2024",))
    _art(conn, "rauch_hellblau", ("msfs2024",))
    ev = _ev(conn)
    set_reddung_gefunden(conn, ev["id"], "2026-09-25T17:30:00Z", 111)
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    set_reddung_aufgenommen(conn, ev["id"], "2026-09-25T17:50:00Z", 222)
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    arten = [r[0] for r in conn.execute(
        "SELECT art FROM bruegge_soll WHERE art LIKE 'rauch%'").fetchall()]
    assert arten == ["rauch_hellblau"], "orange darf nicht daneben stehenbleiben"


def test_endet_der_abend_mit_dem_fund_wird_die_fackel_gleich_hellblau(conn):
    """Orange heisst 'gefunden, noch nicht gerettet'. Ist nichts mehr zu tun, waere das
    eine falsche Auskunft an alle, die noch in der Luft sind."""
    _art(conn, "flugzeug_echo", ("msfs2024",))
    _art(conn, "rauch_hellblau", ("msfs2024",))
    ev = _ev(conn, aufnehmen_noetig=0)
    set_reddung_gefunden(conn, ev["id"], "2026-09-25T17:30:00Z", 111)
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    arten = [r[0] for r in conn.execute(
        "SELECT art FROM bruegge_soll WHERE art LIKE 'rauch%'").fetchall()]
    assert arten == ["rauch_hellblau"]


def test_nach_der_aufloesung_ist_alles_weg(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    ev = _ev(conn)
    reddung_objekte_abgleichen(conn, ev)
    set_reddung_aufgeloest(conn, ev["id"], "2026-09-25T22:00:00Z")
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    assert conn.execute("SELECT count(*) FROM bruegge_soll").fetchone()[0] == 0


def test_die_grundhoehe_kommt_aus_einer_gemessenen_meldung(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    ev = _ev(conn)
    ids = reddung_objekte_abgleichen(conn, ev)
    conn.execute("INSERT INTO bruegge_positions (cid, lat, lon, gemeldet_am, simulator) "
                 "VALUES (111, 53.73, 7.26, '2026-09-25T17:05:00Z', 'msfs2024')")
    conn.execute("INSERT INTO bruegge_steht (kennung, id, cid, zustand, hoehe_ft, "
                 "hoehe_gemessen, gemeldet_am) VALUES ('k1', ?, 111, 'steht', 20.0, 1, "
                 "'2026-09-25T17:05:00Z')", (ids[0],))
    assert reddung_grund_lernen(conn, get_reddung_event(conn, ev["id"])) is True
    ev2 = get_reddung_event(conn, ev["id"])
    assert ev2["havarist_grund_ft"] == 20.0 and ev2["havarist_grund_quelle"] == "gemessen"


def test_eine_UNGEMESSENE_meldung_setzt_nichts(conn):
    """⚠ Der X-Plane-Fall: Ohne geladenes Gelaende bekommt das Objekt Meereshoehe, und die
    Meldung sieht genau wie ein Wattobjekt auf 0,0 ft aus (PROTOKOLL, hoehe_gemessen)."""
    _art(conn, "flugzeug_echo", ("xplane12",))
    ev = _ev(conn)
    ids = reddung_objekte_abgleichen(conn, ev)
    conn.execute("INSERT INTO bruegge_positions (cid, lat, lon, gemeldet_am, simulator) "
                 "VALUES (111, 53.73, 7.26, '2026-09-25T17:05:00Z', 'xplane12')")
    conn.execute("INSERT INTO bruegge_steht (kennung, id, cid, zustand, hoehe_ft, "
                 "hoehe_gemessen, gemeldet_am) VALUES ('k1', ?, 111, 'steht', 0.0, 0, "
                 "'2026-09-25T17:05:00Z')", (ids[0],))
    assert reddung_grund_lernen(conn, get_reddung_event(conn, ev["id"])) is False
    assert get_reddung_event(conn, ev["id"])["havarist_grund_ft"] is None


def test_eine_meldung_von_weit_weg_setzt_nichts(conn):
    """⚠ Am Bodensee gemessen: 2.106 ft statt 1.297 ft bei 691 km Abstand -- aus der Ferne
    antwortet der Simulator aus einer groben Gelaendestufe, nicht aus geladenem Terrain."""
    _art(conn, "flugzeug_echo", ("msfs2024",))
    ev = _ev(conn)
    ids = reddung_objekte_abgleichen(conn, ev)
    conn.execute("INSERT INTO bruegge_positions (cid, lat, lon, gemeldet_am, simulator) "
                 "VALUES (111, 47.65, 9.18, '2026-09-25T17:05:00Z', 'msfs2024')")
    conn.execute("INSERT INTO bruegge_steht (kennung, id, cid, zustand, hoehe_ft, "
                 "hoehe_gemessen, gemeldet_am) VALUES ('k1', ?, 111, 'steht', 2106.5, 1, "
                 "'2026-09-25T17:05:00Z')", (ids[0],))
    assert reddung_grund_lernen(conn, get_reddung_event(conn, ev["id"])) is False


def test_die_meldung_traegt_hoehe_gemessen_in_die_tabelle():
    """Verankert am Quelltext: Ohne dieses Feld ist der X-Plane-Vorbehalt oben nicht pruefbar."""
    import pathlib
    assert "hoehe_gemessen" in pathlib.Path("app/main.py").read_text(encoding="utf-8")
    assert "hoehe_gemessen" in pathlib.Path("app/database.py").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_objekte.py -q`
Expected: FAIL — `ImportError: cannot import name 'reddung_objekte_abgleichen'`

- [ ] **Step 3: Write minimal implementation**

`bruegge_steht` in `_DDL` um die Spalte erweitern, mit Kommentar:

```sql
    -- Ob `hoehe_ft` eine MESSUNG ist. X-Plane probt das Gelaende selbst und bekommt ohne
    -- geladenes Terrain Meereshoehe -- die Meldung sieht dann genau wie ein Wattobjekt auf
    -- 0,0 ft aus (PROTOKOLL.md, Abschnitt 1). MSFS sendet das Feld nicht, dort gilt 1.
    -- NULL = alte Meldung, vor dieser Spalte.
    hoehe_gemessen INTEGER,
```

Migration + Anwendung in `init_db` wie in Task 4. In `bruegge_steht_melden` das Feld mitschreiben
(`hoehe_gemessen` aus dem Eintrag, Vorgabe `1`, wenn das Feld fehlt — so sendet MSFS es).
In `app/main.py` an der Stelle, die `hoehe_ft=_bruegge_zahl(eintrag.get("hoehe_ft"))` übergibt,
`hoehe_gemessen=eintrag.get("hoehe_gemessen")` ergänzen.

Dann die Objektverwaltung:

```python
#: Die drei Simulatoren, für die ein Havarist gesetzt werden kann.
_REDDUNG_SIMULATOREN = ("msfs2020", "msfs2024", "xplane12")

#: Vorgabe-Art des Havaristen. Ein Fliegerverein sucht Flieger, und `flugzeug_echo` ist die
#: einzige Kleinflugzeug-Art mit aktiven Titeln in ALLEN drei Simulatoren.
_HAVARIST_VORGABE_ART = "flugzeug_echo"

#: Ersatz je Art, wenn sie in einem Simulator keinen aktiven Titel hat. Ohne das erschiene das
#: Objekt bei einem Teil der Piloten stumm nicht.
_HAVARIST_ERSATZ = {
    "boot_klein": ("schiff_segel", "schnellboot", "boot_gross"),
    "boot_gross": ("schiff_segel", "schiff_tanker", "boot_klein"),
    "schiff_segel": ("boot_klein", "schnellboot", "boot_gross"),
    "schnellboot": ("boot_klein", "schiff_segel", "boot_gross"),
    "segelflugzeug": ("flugzeug_echo",),
    "flugzeug_klassik": ("flugzeug_echo",),
}

#: So weit darf der meldende Pilot höchstens weg sein, damit seine Höhenmeldung als Messung
#: gilt. Belegt sind brauchbare Werte bis 200 km; der erste falsche lag bei 691 km (Bodensee,
#: 2.106 statt 1.297 ft). Dazwischen ist eine Lücke — 200 km ist die belegte Grenze, nicht die
#: gemessene Kante.
_GRUND_MESS_MAX_KM = 200.0

#: Die Fackel steht NEBEN dem Havaristen, nicht in ihm — sonst steckt die Rauchsäule im Wrack.
_FACKEL_VERSATZ_GRAD = 0.0003    # ~33 m nach Norden


def _art_je_simulator(conn: sqlite3.Connection, art: str) -> dict[str, str | None]:
    """Welche Art ist in welchem Simulator setzbar? ``None`` = dort gibt es keine."""
    ergebnis: dict[str, str | None] = {}
    for sim in _REDDUNG_SIMULATOREN:
        vorhanden = bruegge_titel_fuer(conn, sim)
        if art in vorhanden:
            ergebnis[sim] = art
            continue
        ergebnis[sim] = next((e for e in _HAVARIST_ERSATZ.get(art, ()) if e in vorhanden), None)
    return ergebnis


def _soll_zeilen_setzen(conn: sqlite3.Connection, basis_id: str, art: str,
                        lat: float, lon: float, gilt_bis: str) -> list[str]:
    """Eine Zeile, wenn die Art überall geht — sonst eine je Simulator.

    Eine Zeile mit ``simulator = NULL`` ist der Normalfall und spart drei Einträge; die
    Aufspaltung entsteht nur bei einer lückenhaften Art.
    """
    je_sim = _art_je_simulator(conn, art)
    ids: list[str] = []
    if len(set(je_sim.values())) == 1 and art in set(je_sim.values()):
        bruegge_soll_setzen(conn, basis_id, art, lat, lon, auf_boden=True,
                            gilt_bis=gilt_bis, simulator=None)
        return [basis_id]
    for sim, gewaehlt in je_sim.items():
        sid = f"{basis_id}-{sim}"
        if gewaehlt is None:
            bruegge_soll_loeschen(conn, sid)
            continue
        bruegge_soll_setzen(conn, sid, gewaehlt, lat, lon, auf_boden=True,
                            gilt_bis=gilt_bis, simulator=sim)
        ids.append(sid)
    bruegge_soll_loeschen(conn, basis_id)
    return ids


def reddung_objekte_abgleichen(conn: sqlite3.Connection, ev: dict) -> list[str]:
    """Havarist und Fackel in ``bruegge_soll`` auf den Stand des Events bringen.

    Vollständiger Abgleich, kein Strom von Befehlen (PROTOKOLL.md, Abschnitt 2): Die Funktion
    darf in jedem Poller-Takt laufen und schreibt denselben Zustand.

    Die Fackel folgt den Latches — orange nach dem Fund, hellblau nach der Aufnahme, und gleich
    hellblau, wenn der Abend mit dem Fund endet.
    """
    basis = f"reddung-{ev['id']}"
    hav_id, fackel_id = f"{basis}-havarist", f"{basis}-fackel"
    alle_ids = [hav_id, fackel_id] + [f"{hav_id}-{s}" for s in _REDDUNG_SIMULATOREN] \
        + [f"{fackel_id}-{s}" for s in _REDDUNG_SIMULATOREN]

    if ev.get("aufgeloest_am") or ev.get("havarist_lat") is None:
        for sid in alle_ids:
            bruegge_soll_loeschen(conn, sid)
        return []

    lat, lon = float(ev["havarist_lat"]), float(ev["havarist_lon"])
    gilt_bis = ev["dtend"]
    ids = _soll_zeilen_setzen(conn, hav_id, ev.get("havarist_art") or _HAVARIST_VORGABE_ART,
                              lat, lon, gilt_bis)

    fackel = None
    if ev.get("aufgenommen_am") or (ev.get("gefunden_am") and not ev.get("aufnehmen_noetig")):
        fackel = "rauch_hellblau"
    elif ev.get("gefunden_am"):
        fackel = "rauch_signalorange"
    if fackel:
        ids += _soll_zeilen_setzen(conn, fackel_id, fackel,
                                   lat + _FACKEL_VERSATZ_GRAD, lon, gilt_bis)
    else:
        for sid in [fackel_id] + [f"{fackel_id}-{s}" for s in _REDDUNG_SIMULATOREN]:
            bruegge_soll_loeschen(conn, sid)
    return ids


def reddung_grund_lernen(conn: sqlite3.Connection, ev: dict) -> bool:
    """Die Geländehöhe an der Unglücksstelle aus einer Brügge-Rückmeldung lernen.

    Zwei Vorbehalte aus PROTOKOLL.md, und beide sind Fallstricke:

    * ``hoehe_gemessen = 0`` heißt „die Höhe ist geraten" (X-Plane ohne geladenes Gelände).
      Solche Meldungen sehen genau wie ein Wattobjekt auf 0,0 ft aus.
    * Aus der Ferne antwortet der Simulator aus einer groben Geländestufe — am Bodensee
      2.106 ft statt 1.297 ft bei 691 km. Deshalb muss der meldende Pilot nah sein.

    Geprüft wird gegen seine AKTUELLE Position aus ``bruegge_positions``: Die Brügge meldet im
    Sekundentakt, Meldung und Position liegen also Sekunden auseinander.
    """
    from app.geo import haversine
    basis = f"reddung-{ev['id']}-havarist"
    rows = conn.execute(
        "SELECT s.hoehe_ft, s.hoehe_gemessen, p.lat, p.lon FROM bruegge_steht s "
        "JOIN bruegge_positions p ON p.cid = s.cid "
        "WHERE s.zustand = 'steht' AND (s.id = ? OR s.id LIKE ?) AND s.hoehe_ft IS NOT NULL "
        "ORDER BY s.gemeldet_am DESC", (basis, basis + "-%")).fetchall()
    for hoehe, gemessen, plat, plon in rows:
        if gemessen == 0:
            continue
        if haversine(float(plat), float(plon),
                     float(ev["havarist_lat"]), float(ev["havarist_lon"])) > _GRUND_MESS_MAX_KM:
            continue
        return reddung_grund_merken(conn, ev["id"], float(hoehe), "gemessen")
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_objekte.py tests/test_bruegge_endpunkt.py tests/test_bruegge_festhalten.py -q`
Expected: PASS — keine Regression an den vorhandenen Brügge-Tests

- [ ] **Step 5: Gegenprobe**

1. `if gemessen == 0: continue` entfernen — erwartet rot in
   `test_eine_UNGEMESSENE_meldung_setzt_nichts`.
2. Die Abstandsprüfung entfernen — erwartet rot in
   `test_eine_meldung_von_weit_weg_setzt_nichts`.
3. Im Fackelzweig den `else`-Ast (Löschen) entfernen — erwartet rot in
   `test_nach_der_aufnahme_wechselt_die_fackel_auf_hellblau`
   (dann stehen orange **und** hellblau).

- [ ] **Step 6: Commit**

```bash
git add app/database.py app/main.py tests/test_reddung_objekte.py
git commit -m "FriesenReddung: Havarist und Fackeln als Bruegge-Objekte, Grundhoehe aus der Rueckmeldung"
```

---

### Task 6: Der Poller-Job

**Files:**
- Modify: `app/poller.py` — Job-Registrierung bei den anderen `interval`-Jobs, neue Methode
  `_check_reddung`
- Test: `tests/test_reddung_poller.py`

**Interfaces:**
- Consumes: alles aus Task 1–5, `canonicalize_legs`, `get_push_subscriptions_for_events`,
  `send_web_push`, `self.broadcast_notify`
- Produces: `Poller._check_reddung()` — die Methode wird im Test direkt aufgerufen

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reddung_poller.py
# -*- coding: utf-8 -*-
"""Der Poller-Job der FriesenReddung: Fund, Aufnahme, Einlieferung, Verfall (20.09.2026)."""
from __future__ import annotations

import asyncio
import math

import pytest

from app.database import (
    create_reddung_event, get_connection, get_reddung_event, init_db, upsert_pilot,
)
from app.poller import Poller

LAT, LON = 53.72, 7.25
G_LAT = 1.0 / 111.32
G_LON = 1.0 / (111.32 * math.cos(math.radians(LAT)))


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _event(pfad, **extra):
    c = get_connection(pfad)
    try:
        eid = create_reddung_event(
            c, name="Reddung Probe", dtstart="2026-09-25T17:00:00Z",
            dtend="2026-09-25T22:00:00Z",
            sued=LAT - 2 * G_LAT, west=LON - 2 * G_LON,
            nord=LAT + 2 * G_LAT, ost=LON + 2 * G_LON,
            havarist_lat=LAT, havarist_lon=LON, havarist_grund_ft=10.0, **extra)
        c.commit()
        return eid
    finally:
        c.close()


def _punkte(pfad, cid, punkte, alt=900, gs=110):
    c = get_connection(pfad)
    try:
        upsert_pilot(c, {"cid": cid, "name": f"Pilot {cid}"})
        for lat, lon, ts in punkte:
            c.execute("INSERT INTO position_history (cid, callsign, latitude, longitude, "
                      "altitude, groundspeed, heading, ts) VALUES (?,?,?,?,?,?,?,?)",
                      (cid, f"FRS{cid}", lat, lon, alt, gs, 90, ts))
        c.commit()
    finally:
        c.close()


def _lauf(pfad):
    # Der Konstruktor nimmt db_path als erstes Argument (app/poller.py:413). Der Scheduler
    # wird NICHT gestartet -- der Test ruft die Methode direkt, sonst laufen 20 fremde Jobs mit.
    p = Poller(pfad, callsign_prefix="FRS")
    asyncio.run(p._check_reddung())


def test_der_ueberflug_latcht_den_fund(db):
    eid = _event(db)
    _punkte(db, 111, [(LAT, LON - 2 * G_LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON, "2026-09-25T17:10:30Z")])
    _lauf(db)
    c = get_connection(db)
    try:
        ev = get_reddung_event(c, eid)
    finally:
        c.close()
    assert ev["gefunden_von"] == 111 and ev["gefunden_am"] == "2026-09-25T17:10:30Z"


def test_der_fund_wird_mit_dem_segmentENDE_gestempelt(db):
    """Der Augenblick, in dem der Ueberflug BEWIESEN ist -- nie ein fruehrerer."""
    eid = _event(db)
    _punkte(db, 111, [(LAT, LON - 2 * G_LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON, "2026-09-25T17:10:30Z")])
    _lauf(db)
    c = get_connection(db)
    try:
        assert get_reddung_event(c, eid)["gefunden_am"] == "2026-09-25T17:10:30Z"
    finally:
        c.close()


def test_der_ueberflug_des_finders_ist_nicht_gleich_die_aufnahme(db):
    """Sonst waere jeder Fund sofort eine Rettung."""
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, [(LAT, LON - 2 * G_LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON, "2026-09-25T17:10:30Z")], gs=25)
    _lauf(db)
    c = get_connection(db)
    try:
        ev = get_reddung_event(c, eid)
    finally:
        c.close()
    assert ev["gefunden_am"] is not None
    assert ev["aufgenommen_am"] is None


def test_ein_schwebeflug_nach_dem_fund_nimmt_auf(db):
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, [(LAT, LON - 2 * G_LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON, "2026-09-25T17:10:30Z")])
    _lauf(db)
    _punkte(db, 222, [(LAT, LON, "2026-09-25T17:40:00Z"),
                      (LAT, LON, "2026-09-25T17:40:15Z")], alt=200, gs=10)
    _lauf(db)
    c = get_connection(db)
    try:
        assert get_reddung_event(c, eid)["aufgenommen_von"] == 222
    finally:
        c.close()


def test_ein_schwebeflug_genuegt_NICHT_wenn_eine_landung_verlangt_ist(db):
    eid = _event(db, landung_noetig=1)
    _punkte(db, 111, [(LAT, LON - 2 * G_LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON, "2026-09-25T17:10:30Z")])
    _lauf(db)
    _punkte(db, 222, [(LAT, LON, "2026-09-25T17:40:00Z"),
                      (LAT, LON, "2026-09-25T17:40:15Z")], alt=200, gs=10)
    _lauf(db)
    c = get_connection(db)
    try:
        assert get_reddung_event(c, eid)["aufgenommen_am"] is None
    finally:
        c.close()


def test_ein_vollstopp_nimmt_auch_mit_verlangter_landung_auf(db):
    eid = _event(db, landung_noetig=1)
    _punkte(db, 111, [(LAT, LON - 2 * G_LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON, "2026-09-25T17:10:30Z")])
    _lauf(db)
    _punkte(db, 222, [(LAT, LON, "2026-09-25T17:40:00Z"),
                      (LAT, LON, "2026-09-25T17:40:15Z")], alt=30, gs=0)
    _lauf(db)
    c = get_connection(db)
    try:
        assert get_reddung_event(c, eid)["aufgenommen_von"] == 222
    finally:
        c.close()


def test_endet_der_abend_mit_dem_fund_wird_nichts_mehr_geprueft(db):
    eid = _event(db, aufnehmen_noetig=0)
    _punkte(db, 111, [(LAT, LON - 2 * G_LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON, "2026-09-25T17:10:30Z")])
    _lauf(db)
    _punkte(db, 222, [(LAT, LON, "2026-09-25T17:40:00Z"),
                      (LAT, LON, "2026-09-25T17:40:15Z")], alt=30, gs=0)
    _lauf(db)
    c = get_connection(db)
    try:
        ev = get_reddung_event(c, eid)
    finally:
        c.close()
    assert ev["gefunden_am"] is not None and ev["aufgenommen_am"] is None
    assert ev["aufgeloest_am"] is not None, "der Fund loest die Lage auf"


def test_bei_dtend_wird_aufgeloest_auch_ohne_fund(db):
    eid = _event(db)
    c = get_connection(db)
    try:
        c.execute("UPDATE reddung_events SET dtend = '2026-09-25T17:05:00Z' WHERE id = ?", (eid,))
        c.commit()
    finally:
        c.close()
    _lauf(db)
    c = get_connection(db)
    try:
        ev = get_reddung_event(c, eid)
    finally:
        c.close()
    assert ev["aufgeloest_am"] is not None and ev["gefunden_am"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_poller.py -q`
Expected: FAIL — `AttributeError: 'Poller' object has no attribute '_check_reddung'`

- [ ] **Step 3: Write minimal implementation**

Job registrieren, bei `transport_event_check`:

```python
        # FriesenReddung: Fund, Aufnahme, Einlieferung latchen und die Fackel tauschen
        self._scheduler.add_job(
            self._check_reddung,
            "interval",
            seconds=60,
            id="reddung_check",
        )
```

Und die Methode, nach `_check_transport_events`:

```python
    async def _check_reddung(self) -> None:
        """Periodisch: FriesenReddung latchen — Fund, Aufnahme, Einlieferung, Auflösung.

        Die vier Stufen sind Latches (``_set_reddung_latch``): Jede wird höchstens einmal
        gesetzt, und die Bedingung ``IS NULL`` im UPDATE macht das auch bei zwei gleichzeitigen
        Takten sicher.

        ⚠ **Die Reihenfolge ist keine Geschmacksfrage.** Der Fund muss vor der Aufnahme
        gelatcht sein, weil fürs Aufnehmen nur Spurenpunkte NACH ``gefunden_am`` zählen — sonst
        wäre der Überflug des Finders gleichzeitig die Rettung. Und der Objektabgleich läuft
        ZULETZT, damit die Fackel den Stand nach allen Latches zeigt.
        """
        try:
            from datetime import datetime, timedelta, timezone
            from app import reddung as rd
            from app.abdeckung import abdeckung
            from app.database import (
                canonicalize_legs, clear_reddung_aufnahme, get_push_subscriptions_for_events,
                get_reddung_event, list_reddung_events, reddung_grund_lernen,
                reddung_objekte_abgleichen, reddung_spuren, set_reddung_aufgeloest,
                set_reddung_aufgenommen, set_reddung_eingeliefert, set_reddung_gefunden,
            )

            now_dt = datetime.now(timezone.utc)
            now = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            conn = get_connection(self.db_path)
            pushes: list[dict] = []
            try:
                for ev in list_reddung_events(conn, since=None):
                    if now < (ev.get("dtstart") or "") or ev.get("aufgeloest_am"):
                        continue
                    name = ev.get("name") or "FriesenReddung"
                    push_on = bool(ev.get("push_enabled"))
                    ziel = rd.havarist_ziel(ev)
                    if ziel is None:
                        continue

                    # Die Grundhöhe zuerst — sie verschiebt die Höhenschranke aller folgenden
                    # Prüfungen. Wer sie danach lernt, wertet einen Takt mit der falschen.
                    if reddung_grund_lernen(conn, ev):
                        ev = get_reddung_event(conn, ev["id"])

                    # 1 — Fund
                    if not ev.get("gefunden_am"):
                        spuren = reddung_spuren(conn, ev["dtstart"], min(now, ev["dtend"]))
                        erg = abdeckung(spuren, [ziel], rd.fenster_suchen(ev))
                        t = erg.treffer.get(rd.HAVARIST)
                        if t and set_reddung_gefunden(conn, ev["id"], t.ts, t.cid):
                            ev = get_reddung_event(conn, ev["id"])
                            if push_on:
                                pushes.append({"title": name,
                                               "body": "Der Havarist ist gefunden! 🚨",
                                               "url": "/"})

                    # 2 — Aufnehmen (nur Punkte NACH dem Fund)
                    if ev.get("gefunden_am") and ev.get("aufnehmen_noetig") \
                            and not ev.get("aufgenommen_am"):
                        spuren = reddung_spuren(conn, ev["dtstart"], min(now, ev["dtend"]),
                                                ab=ev["gefunden_am"])
                        erg = abdeckung(spuren, [ziel], rd.fenster_aufnehmen(ev))
                        t = erg.treffer.get(rd.HAVARIST)
                        if t and set_reddung_aufgenommen(conn, ev["id"], t.ts, t.cid):
                            ev = get_reddung_event(conn, ev["id"])
                            if push_on:
                                pushes.append({"title": name,
                                               "body": "Aufgenommen — jetzt einliefern!",
                                               "url": "/"})

                    # 3 — Aufnahme verfallen lassen, wenn der Aufnehmende weg ist
                    if ev.get("aufgenommen_am") and not ev.get("eingeliefert_am") \
                            and ev.get("aufnahme_verfaellt"):
                        letzte = conn.execute(
                            "SELECT max(ts) FROM position_history WHERE cid = ?",
                            (ev["aufgenommen_von"],)).fetchone()[0]
                        grenze = (now_dt - timedelta(minutes=_REDDUNG_SCHONFRIST_MIN)) \
                            .strftime("%Y-%m-%dT%H:%M:%SZ")
                        if not letzte or letzte < grenze:
                            clear_reddung_aufnahme(conn, ev["id"])
                            ev = get_reddung_event(conn, ev["id"])
                            if push_on:
                                pushes.append({"title": name,
                                               "body": "Die Rettung ist wieder offen.",
                                               "url": "/"})

                    # 4 — Einliefern: erste Landung des Aufnehmenden nach der Aufnahme
                    if ev.get("aufgenommen_am") and not ev.get("eingeliefert_am"):
                        legs = canonicalize_legs(conn, start=ev["aufgenommen_am"], end=ev["dtend"],
                                                 cids=[ev["aufgenommen_von"]])
                        gelandet = [l for l in legs if (l.get("arrival") or "").strip()]
                        if gelandet:
                            leg = gelandet[0]
                            if set_reddung_eingeliefert(conn, ev["id"], leg.get("logoff_time") or now,
                                                        ev["aufgenommen_von"],
                                                        (leg.get("arrival") or "").upper()):
                                ev = get_reddung_event(conn, ev["id"])
                                if push_on:
                                    pushes.append({"title": name,
                                                   "body": f"Eingeliefert in {leg.get('arrival')} ✅",
                                                   "url": "/"})

                    # 5 — Auflösen: Ziel erreicht oder Zeit vorbei
                    fertig = bool(ev.get("eingeliefert_am")) or (
                        bool(ev.get("gefunden_am")) and not ev.get("aufnehmen_noetig"))
                    if fertig or now >= (ev.get("dtend") or ""):
                        if set_reddung_aufgeloest(conn, ev["id"], now):
                            ev = get_reddung_event(conn, ev["id"])
                            if push_on and not fertig:
                                pushes.append({"title": name,
                                               "body": "Vorbei — der Havarist blieb unentdeckt.",
                                               "url": "/"})

                    # 6 — Objekte ZULETZT: die Fackel zeigt den Stand nach allen Latches
                    reddung_objekte_abgleichen(conn, ev)
                subscriptions = get_push_subscriptions_for_events(conn) if pushes else []
                conn.commit()
            finally:
                conn.close()
            for payload in pushes:
                self.broadcast_notify("events", None, payload)
            if pushes and subscriptions and self.vapid_private_key:
                for payload in pushes:
                    asyncio.create_task(send_web_push(
                        self.vapid_private_key, self.vapid_contact_email, self.db_path,
                        subscriptions, payload, label="Reddung",
                    ))
        except Exception:
            logger.exception("Error in _check_reddung")
```

Dazu oben in `app/poller.py` bei den anderen Modulkonstanten:

```python
#: Schonfrist, bis die Aufnahme eines verschwundenen Piloten verfällt. Ein Absturz zum Desktop
#: mit Wiederanmeldung ist im Simulator Alltag — ohne sie reichte ein zweiminütiger Aussetzer
#: die Rettung an jemand anderen weiter. ⚠ Die Zahl ist GESCHÄTZT, nicht gemessen; nach dem
#: ersten Abend gegen `position_history` prüfen (Spec, offener Punkt 4).
_REDDUNG_SCHONFRIST_MIN = 10
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_poller.py -q`
Expected: PASS, 8 Tests

- [ ] **Step 5: Gegenprobe**

1. Im Aufnahme-Zweig `ab=ev["gefunden_am"]` entfernen — erwartet rot in
   `test_der_ueberflug_des_finders_ist_nicht_gleich_die_aufnahme`.
2. Den Objektabgleich (Schritt 6) VOR die Latches ziehen — erwartet rot in
   `tests/test_reddung_objekte.py::test_nach_dem_fund_steht_die_orange_fackel`, sobald der
   Poller-Test denselben Ablauf fährt. (Nur wenn dieser Test hier scheitert: Reihenfolge prüfen.)
3. `ev.get("aufnehmen_noetig")` im Aufnahme-Zweig entfernen — erwartet rot in
   `test_endet_der_abend_mit_dem_fund_wird_nichts_mehr_geprueft`.

- [ ] **Step 6: Commit**

```bash
git add app/poller.py tests/test_reddung_poller.py
git commit -m "FriesenReddung: Poller latcht Fund, Aufnahme, Einlieferung und Aufloesung"
```

---

### Task 7: Admin-Endpunkte

**Files:**
- Modify: `app/main.py` — Importe erweitern, sechs Endpunkte hinter den Transport-Endpunkten
- Test: `tests/test_reddung_api.py`

**Interfaces:**
- Consumes: `require_admin`, `_validate_event_times`, `get_settings`, alles aus Task 2/3/5
- Produces:
  - `GET /api/admin/reddung/events` → `{"events": [ {…ev, "stand": {…}} ]}`
  - `POST /api/admin/reddung/events` → `{"status": "ok", "id": int}`
  - `POST /api/admin/reddung/events/{event_id}` → `{"status": "ok"}`
  - `DELETE /api/admin/reddung/events/{event_id}` → `{"status": "ok"}`
  - `POST /api/admin/reddung/events/{event_id}/push` → `{"status": "ok", "push_enabled": bool}`
  - `POST /api/admin/reddung/events/{event_id}/aufnahme-freigeben` → `{"status": "ok"}`

**Kein öffentlicher Endpunkt in dieser Runde.** Karte und Kniebrett kommen später; bis dahin
gibt es nichts, was ein Pilot abfragen könnte, und damit auch keine neue Zeile in
`tests/test_api_schutz.py::BEWUSST_OFFEN`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reddung_api.py
# -*- coding: utf-8 -*-
"""Die Admin-Endpunkte der FriesenReddung (20.09.2026).

Der wichtigste Test ist der letzte: Die Koordinate des Havaristen steht im Admin (dort sitzt,
wer das Event macht) -- aber der Stand, der spaeter in eine Pilotenansicht wandert, enthaelt
sie nicht. Das ist die Kernanforderung aus #21.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ADMIN_PASSWORD", "geheim")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    from app.config import get_settings
    get_settings.cache_clear()
    import importlib
    from app import main as m
    importlib.reload(m)
    c = TestClient(m.app)
    c.post("/api/admin/login", json={"password": "geheim"})
    return c


SEKTOR = {"sued": 53.54, "west": 6.95, "nord": 53.90, "ost": 7.55}


def test_ohne_anmeldung_geht_nichts(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t2.db"))
    monkeypatch.setenv("ADMIN_PASSWORD", "geheim")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    from app.config import get_settings
    get_settings.cache_clear()
    import importlib
    from app import main as m
    importlib.reload(m)
    roh = TestClient(m.app)
    assert roh.get("/api/admin/reddung/events").status_code == 401


def test_anlegen_lesen_aendern_loeschen(client):
    r = client.post("/api/admin/reddung/events",
                    json={"name": "Reddung Probe", "dtstart": "2026-09-25T17:00:00Z", **SEKTOR})
    assert r.status_code == 200
    eid = r.json()["id"]
    liste = client.get("/api/admin/reddung/events").json()["events"]
    assert liste[0]["name"] == "Reddung Probe"
    assert liste[0]["stand"]["zellen"] > 0
    assert client.post(f"/api/admin/reddung/events/{eid}",
                       json={"havarist_lat": 53.72, "havarist_lon": 7.25,
                             "havarist_art": "flugzeug_echo"}).status_code == 200
    assert client.get("/api/admin/reddung/events").json()["events"][0]["havarist_lat"] == 53.72
    assert client.delete(f"/api/admin/reddung/events/{eid}").status_code == 200
    assert client.get("/api/admin/reddung/events").json()["events"] == []


def test_ein_sektor_ausserhalb_des_sektors_wird_abgewiesen(client):
    """Sued ueber Nord ergibt ein Rechteck mit negativer Hoehe -- das Raster waere leer."""
    r = client.post("/api/admin/reddung/events",
                    json={"name": "Kaputt", "dtstart": "2026-09-25T17:00:00Z",
                          "sued": 53.9, "west": 6.95, "nord": 53.54, "ost": 7.55})
    assert r.status_code == 400


def test_ein_riesiger_sektor_wird_abgewiesen(client):
    """Sonst legt ein Verrutschen auf der Karte ein Raster mit Millionen Zellen an und der
    Poller-Takt bleibt stehen."""
    r = client.post("/api/admin/reddung/events",
                    json={"name": "Zu gross", "dtstart": "2026-09-25T17:00:00Z",
                          "sued": 48.0, "west": 5.0, "nord": 55.0, "ost": 15.0})
    assert r.status_code == 400


def test_push_umschalten(client):
    eid = client.post("/api/admin/reddung/events",
                      json={"name": "P", "dtstart": "2026-09-25T17:00:00Z", **SEKTOR}).json()["id"]
    r = client.post(f"/api/admin/reddung/events/{eid}/push", json={"enabled": False})
    assert r.json()["push_enabled"] is False


def test_aufnahme_freigeben(client):
    """Der Knopf, den es unabhaengig von der Automatik geben muss."""
    from app.database import get_connection, set_reddung_aufgenommen
    from app.config import get_settings
    eid = client.post("/api/admin/reddung/events",
                      json={"name": "A", "dtstart": "2026-09-25T17:00:00Z", **SEKTOR}).json()["id"]
    c = get_connection(get_settings().DB_PATH)
    set_reddung_aufgenommen(c, eid, "2026-09-25T17:50:00Z", 222)
    c.commit(); c.close()
    assert client.post(f"/api/admin/reddung/events/{eid}/aufnahme-freigeben").status_code == 200
    ev = client.get("/api/admin/reddung/events").json()["events"][0]
    assert ev["aufgenommen_am"] is None


def test_der_stand_traegt_die_koordinate_nicht(client):
    """⚠ Im Admin-Event steht sie (dort sitzt der Veranstalter). Im `stand` nicht -- der ist
    die Vorlage fuer die spaetere Pilotenansicht."""
    import json
    eid = client.post("/api/admin/reddung/events",
                      json={"name": "V", "dtstart": "2026-09-25T17:00:00Z", **SEKTOR}).json()["id"]
    client.post(f"/api/admin/reddung/events/{eid}",
                json={"havarist_lat": 53.72, "havarist_lon": 7.25})
    ev = client.get("/api/admin/reddung/events").json()["events"][0]
    assert ev["havarist_lat"] == 53.72
    assert "53.72" not in json.dumps(ev["stand"]) and "7.25" not in json.dumps(ev["stand"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_api.py -q`
Expected: FAIL — 404 statt 200/401

- [ ] **Step 3: Write minimal implementation**

```python
#: Größter erlaubter Sektor. 40 x 40 km ist die Vorgabe; 200 km Kante sind 40.000 Zellen bei
#: 1-km-Raster und damit noch rechenbar. Ohne Grenze legt ein Verrutschen auf der Karte ein
#: Raster mit Millionen Zellen an, und der Poller-Takt bleibt stehen.
_REDDUNG_SEKTOR_MAX_KM = 200.0


def _validate_reddung_sektor(body: dict) -> str | None:
    from app.geo import haversine
    try:
        sued, west = float(body["sued"]), float(body["west"])
        nord, ost = float(body["nord"]), float(body["ost"])
    except (KeyError, TypeError, ValueError):
        return "Sektor unvollständig (sued/west/nord/ost)"
    if nord <= sued or ost <= west:
        return "Sektor verdreht: nord muss über sued und ost über west liegen"
    hoch = haversine(sued, west, nord, west)
    breit = haversine(sued, west, sued, ost)
    if max(hoch, breit) > _REDDUNG_SEKTOR_MAX_KM:
        return (f"Sektor zu groß ({hoch:.0f} x {breit:.0f} km) — höchstens "
                f"{_REDDUNG_SEKTOR_MAX_KM:.0f} km je Kante")
    return None


@app.get("/api/admin/reddung/events")
async def admin_reddung_events(request: Request):
    """Alle FriesenReddungen mit ihrem Stand. Die Koordinate des Havaristen steht dabei im
    Event selbst — hier sitzt, wer das Event macht —, aber NICHT im `stand`."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        events = []
        for ev in list_reddung_events(conn):
            events.append({**ev, "stand": compute_reddung_stand(conn, ev)})
        return {"events": events}
    finally:
        conn.close()


@app.post("/api/admin/reddung/events")
async def admin_create_reddung_event(request: Request):
    require_admin(request)
    body = await request.json()
    if not body.get("dtstart"):
        raise HTTPException(status_code=400, detail="dtstart erforderlich")
    terr = _validate_event_times(body.get("dtstart"), body.get("dtend"))
    if terr:
        raise HTTPException(status_code=400, detail=terr)
    serr = _validate_reddung_sektor(body)
    if serr:
        raise HTTPException(status_code=400, detail=serr)
    felder = {k: body[k] for k in (
        "kante_km", "korridor_km", "hoehe_max_ft", "gs_max_kt", "gs_min_kt",
        "havarist_lat", "havarist_lon", "havarist_art", "aufnehmen_noetig",
        "landung_noetig", "aufnahme_verfaellt", "badge_name") if k in body}
    conn = get_connection(get_settings().DB_PATH)
    try:
        eid = create_reddung_event(
            conn, name=body.get("name") or "FriesenReddung", dtstart=body["dtstart"],
            dtend=body.get("dtend") or None,
            sued=body["sued"], west=body["west"], nord=body["nord"], ost=body["ost"],
            source="manual", **felder)
        conn.commit()
        return {"status": "ok", "id": eid}
    finally:
        conn.close()


@app.post("/api/admin/reddung/events/{event_id}")
async def admin_update_reddung_event(request: Request, event_id: int):
    require_admin(request)
    body = await request.json()
    if {"sued", "west", "nord", "ost"} <= set(body):
        serr = _validate_reddung_sektor(body)
        if serr:
            raise HTTPException(status_code=400, detail=serr)
    conn = get_connection(get_settings().DB_PATH)
    try:
        if get_reddung_event(conn, event_id) is None:
            raise HTTPException(status_code=404, detail="unbekannt")
        try:
            update_reddung_event(conn, event_id, **body)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.delete("/api/admin/reddung/events/{event_id}")
async def admin_delete_reddung_event(request: Request, event_id: int):
    """Löscht das Event UND nimmt seine Objekte aus `bruegge_soll` — sonst stünde ein Wrack
    bis zum `gilt_bis` weiter im Simulator, zu dem es kein Event mehr gibt."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        ev = get_reddung_event(conn, event_id)
        if ev is None:
            raise HTTPException(status_code=404, detail="unbekannt")
        reddung_objekte_abgleichen(conn, {**ev, "aufgeloest_am": "geloescht"})
        delete_reddung_event(conn, event_id)
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.post("/api/admin/reddung/events/{event_id}/push")
async def admin_reddung_push(request: Request, event_id: int):
    require_admin(request)
    body = await request.json()
    an = bool(body.get("enabled"))
    conn = get_connection(get_settings().DB_PATH)
    try:
        update_reddung_event(conn, event_id, push_enabled=1 if an else 0)
        conn.commit()
        return {"status": "ok", "push_enabled": an}
    finally:
        conn.close()


@app.post("/api/admin/reddung/events/{event_id}/aufnahme-freigeben")
async def admin_reddung_aufnahme_freigeben(request: Request, event_id: int):
    """Die Aufnahme von Hand freigeben — der Knopf, den es unabhängig von der Automatik
    geben muss, weil die im Einzelfall falsch liegt."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        ev = get_reddung_event(conn, event_id)
        if ev is None:
            raise HTTPException(status_code=404, detail="unbekannt")
        clear_reddung_aufnahme(conn, event_id)
        reddung_objekte_abgleichen(conn, get_reddung_event(conn, event_id))
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()
```

Die neuen Namen in den `from app.database import (...)`-Block von `app/main.py` aufnehmen:
`clear_reddung_aufnahme, compute_reddung_stand, create_reddung_event, delete_reddung_event,
get_reddung_event, list_reddung_events, reddung_objekte_abgleichen, update_reddung_event`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_api.py tests/test_api_schutz.py -q`
Expected: PASS — auch der Riegel-Test bleibt grün, weil alle neuen Pfade `require_admin` tragen

- [ ] **Step 5: Gegenprobe**

1. `require_admin(request)` in `admin_reddung_events` entfernen — erwartet rot in
   `test_ohne_anmeldung_geht_nichts` **und** in
   `tests/test_api_schutz.py::test_jeder_gatefreie_endpunkt_hat_eine_pruefung_oder_einen_grund`.
2. `_validate_reddung_sektor` im Anlegen weglassen — erwartet rot in
   `test_ein_sektor_ausserhalb_des_sektors_wird_abgewiesen` und
   `test_ein_riesiger_sektor_wird_abgewiesen`.
3. Im Löschen den `reddung_objekte_abgleichen`-Aufruf weglassen — kein Test fängt das;
   **stattdessen** einen ergänzen, der nach dem Löschen `bruegge_soll` leer erwartet.

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_reddung_api.py
git commit -m "FriesenReddung: Admin-Endpunkte"
```

---

### Task 8: Admin-Oberfläche, Doku, Changelog

**Files:**
- Modify: `app/static/admin.html` — Chip in der `typ-nav`, Panel `typ-reddung`, Formular, Liste
- Modify: `docs/architecture.md` — Abschnitt zur Tabelle und zum Job
- Modify: `COORDINATION.md` — Eintrag oben
- Modify: `app/CHANGELOG.json` — ein Eintrag, `"highlight": false`
- Test: `tests/test_reddung_api.py` (Quelltext-Wachen anfügen)

**Die `typ-nav` ist schon vorbereitet.** In `app/static/admin.html` steht bei den Chips ein
Kommentar: *„Kieker, Suchflug, Deichkontrolle und Baake kommen mit ihrem Typ dazu. Ein Chip ohne
Inhalt dahinter ist eine Einladung ins Leere."* Dort kommt der neue Chip hin — und der Kommentar
nennt „Suchflug", was nach der Umbenennung „FriesenReddung" heißen muss.

**Keine README-Änderung in dieser Runde, und das ist eine Entscheidung:** Die README ist das
Handbuch der **Mitglieder**. Sichtbar ist bisher nur der Admin-Bereich; der Absatz entsteht mit
der Karten- und Kniebrett-Ansicht, zusammen mit dem Hilfetext hinter dem `?`.

- [ ] **Step 1: Write the failing test** (an `tests/test_reddung_api.py` anfügen)

```python
# --- Admin-Oberflaeche (Quelltext-Wachen) ---------------------------------

import pathlib

ADMIN = pathlib.Path("app/static/admin.html")


def test_der_chip_fuer_die_reddung_steht_in_der_typ_leiste():
    q = ADMIN.read_text(encoding="utf-8")
    assert 'data-typ="reddung"' in q
    assert 'id="typ-reddung"' in q


def test_der_alte_arbeitstitel_steht_nicht_mehr_im_admin():
    assert "Suchflug" not in ADMIN.read_text(encoding="utf-8")


def test_neben_dem_landehaken_steht_was_er_bedeutet():
    """Sonst legt jemand ein Event an, das nur Hubschrauberpiloten abschliessen koennen,
    ohne es zu wissen (Spec, Abschnitt 4)."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "Hubschrauber" in q and "Wasserflugzeug" in q
    assert "Vollstopp" in q


def test_der_fundradius_wird_angezeigt_und_nicht_eingegeben():
    """Er ist gerechnet. Ein Eingabefeld dafuer waere der Weg zum luegenden Balken."""
    q = ADMIN.read_text(encoding="utf-8")
    assert 'id="reddung-fundradius"' in q
    assert 'name="fundradius' not in q and 'id="reddung-fundradius-input"' not in q


def test_die_herkunft_der_grundhoehe_steht_neben_der_zahl():
    assert "grund_quelle" in ADMIN.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_api.py -q`
Expected: FAIL — `assert 'data-typ="reddung"' in q`

- [ ] **Step 3: Write minimal implementation**

Chip ergänzen und den Kommentar berichtigen:

```html
          <!-- Die zweite Ebene: ein Chip je Event-Typ. Bummel, Kutter und FriesenReddung sind
               da; Kieker, Deichkontrolle und Baake kommen mit ihrem Typ dazu.
               Ein Chip ohne Inhalt dahinter ist eine Einladung ins Leere. -->
          <div class="typ-nav">
            <button class="typ-btn active" data-typ="bummel">🏁 Bummel</button>
            <button class="typ-btn" data-typ="kutter">🦐 Kutter</button>
            <button class="typ-btn" data-typ="reddung">🚨 Reddung</button>
          </div>
```

Panel hinter `typ-kutter` einfügen. Aufbau, in dieser Reihenfolge:

1. **Formular** — Name, Zeitfenster, Sektor (vier Felder plus Knopf „auf der Karte setzen"),
   Zellkante, Korridor, Höhenschranke (in **ft AGL**, mit dem Zusatz „über dem Havaristen"),
   Geschwindigkeitsfenster, Art des Havaristen (Auswahl aus `/api/admin/bruegge/arten`),
   Lage des Havaristen (zwei Felder plus Kartenklick), die drei Haken.
2. **Der gerechnete Fundradius** als reine Anzeige:
   `<span id="reddung-fundradius"></span>` — bei jeder Änderung von Kante oder Korridor neu
   gerechnet: `(korridor + kante / Math.SQRT2).toFixed(2)`.
3. **Die erwartete Suchdauer** daneben: `sektorFlaeche / (piloten * 2 * korridor * 204)` Stunden
   bei 110 kt — mit `piloten = 5` als Annahme und einem Hinweis, dass es eine Schätzung ist.
4. **Liste der Events** mit Abdeckungsbalken (Muster: der gruppierte Balken des Kutters), den
   drei Latches mit Namen und Zeit, der Grundhöhe **samt `grund_quelle`**, und den Knöpfen
   „Aufnahme freigeben", „Push aus/an", „Löschen".

Die Texte neben den Haken wörtlich aus der Spec:

```html
<label><input type="checkbox" id="reddung-aufnehmen-noetig" checked> Aufnehmen nötig</label>
<div class="hint">Ist der Haken aus, endet der Abend mit dem Fund — keine Aufnahme, keine
  Einlieferung.</div>

<label><input type="checkbox" id="reddung-landung-noetig" checked> Landung zur Rettung nötig</label>
<div class="hint" id="reddung-landung-hint">Aufnehmen verlangt eine Landung an der
  Unglücksstelle (Vollstopp unter 300 ft AGL) — sieh nach, ob dort jemand landen kann.</div>
```

Und der Hinweis wechselt mit dem Haken:

```javascript
// Ohne diesen Text legt jemand ein Event an, das nur Hubschrauberpiloten abschliessen
// koennen, ohne es zu wissen (Spec, Abschnitt 4).
const _REDDUNG_HINT_LANDUNG = 'Aufnehmen verlangt eine Landung an der Unglücksstelle '
  + '(Vollstopp unter 300 ft AGL) — sieh nach, ob dort jemand landen kann.';
const _REDDUNG_HINT_SCHWEBE = 'Aufnehmen per Schwebeflug, unter 30 kt über der Unglücksstelle. '
  + 'Das verlangt einen Hubschrauber oder ein Wasserflugzeug.';
function _reddungHinweise() {
  const auf = document.getElementById('reddung-aufnehmen-noetig');
  const lnd = document.getElementById('reddung-landung-noetig');
  lnd.disabled = !auf.checked;          // der aeussere Haken sperrt den inneren
  document.getElementById('reddung-landung-hint').textContent =
    lnd.checked ? _REDDUNG_HINT_LANDUNG : _REDDUNG_HINT_SCHWEBE;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_api.py tests/test_admin_ui_static.py tests/test_admin_tabs.py -q`
Expected: PASS — auch die vorhandenen Admin-Wachen bleiben grün

- [ ] **Step 5: Doku und Changelog**

`docs/architecture.md`: Abschnitt bei den anderen Tabellen und beim Poller — Tabelle
`reddung_events`, der Job `_check_reddung`, die vier Stufen, und der Satz, dass
`havarist_lat/lon` nur an die Brügge und in den Admin gehen.

`COORDINATION.md` oben:

```markdown
## 2026-09-20 (abends) — FriesenReddung: Server und Admin

**Angefasst:** `app/reddung.py` (neu), `app/database.py` (Tabelle `reddung_events`, Spalten
`bruegge_soll.simulator` und `bruegge_steht.hoehe_gemessen`), `app/poller.py` (`_check_reddung`),
`app/main.py`, `app/static/admin.html`, vier neue Testdateien.

**Wer hier weiterbaut, sollte drei Dinge wissen:**

1. ⚠ **Der Fundradius wird GERECHNET** (`korridor + kante/√2`). Macht ihn jemand einstellbar,
   lügt der Fortschrittsbalken: Eine abgedeckte Zelle heißt nur, dass ein Track im Korridor an
   ihrem MITTELPUNKT vorbeilief.
2. ⚠ **Die Höhenschranke ist AGL über dem Havaristen**, und die Grundhöhe lernt der Server aus
   `bruegge_steht.hoehe_ft` — aber nur mit `hoehe_gemessen != 0` und nur von einem Piloten
   näher als 200 km. Beide Vorbehalte stehen in `friesenbruegge/PROTOKOLL.md`.
3. ⚠ **`compute_reddung_stand` gibt NIE eine Koordinate heraus.** Zwei Tests halten das fest.

**Neu und für andere Eventtypen nutzbar:** `bruegge_soll.simulator` (NULL = für alle) — eine Art
ohne aktiven Titel in einem Simulator erscheint dort sonst stumm nicht.
```

`app/CHANGELOG.json`: ein Eintrag, Nummer aus dem ersten Eintrag um eine MINOR erhöhen,
`"highlight": false`. Vorschlag für den Text:

```json
{
  "version": "<nächste MINOR>",
  "date": "<heute>",
  "highlight": false,
  "title": "FriesenReddung — der neue Eventtyp steht auf dem Server",
  "items": [
    "🚨 Die **FriesenReddung** (Reddung ist Platt für Rettung) ist der Eventtyp, der die Umfrage im Forum gewonnen hat: Irgendwo im Suchgebiet liegt eine abgestürzte Maschine, die Gruppe teilt sich auf und sucht sie. Wer tief und langsam darüber hinwegfliegt, hat sie für alle gefunden — dann steht eine orange Rauchfackel daneben, und es muss jemand hin und den Piloten aufnehmen. Gewertet wird die abgesuchte Fläche der ganzen Gruppe, nicht nur der Fund: Wer eine Fläche abfliegt und nichts findet, hat das Gebiet für alle verkleinert. **Angelegt werden kann sie noch nicht von euch, und zu sehen ist sie noch nicht** — Karte und Kniebrett kommen als nächstes."
  ]
}
```

- [ ] **Step 6: Volle Suite, Rebase, Commit, Push**

```bash
/home/claude/.venv-friesenspy/bin/python -m pytest -q          # muss vollständig grün sein
git fetch origin && git status -sb                             # fremde Arbeit im Baum? nicht mitnehmen
git add app/ docs/ COORDINATION.md tests/
git commit -m "FriesenReddung: Admin-Oberflaeche, Doku, Changelog"
```

---

## Selbstdurchsicht (nach dem Schreiben des Plans erledigt)

**Spec-Abdeckung** — jeder Abschnitt der Spec hat eine Aufgabe:

| Spec | Aufgabe |
|---|---|
| 1 Ablauf, vier Stufen | 6 |
| 1 Abend endet mit dem Fund | 2 (Feld), 5 (Fackel), 6 (Latch) |
| 1 Abbruch des Aufnehmenden | 2 (Feld), 6 (Verfall), 7 (Knopf) |
| 2 Flugzeug als Vorgabe, Art je Simulator | 4, 5 |
| 3 Wertung: Gruppe + Beitrag je Pilot | 3 |
| 4 Zahlen, gerechneter Fundradius | 1 |
| 4 Höhenschranke AGL, Grundhöhe lernen | 1, 2, 5 |
| 4 Aufnehmen mit den Landeregeln | 1, 6 |
| 5 Verdeckung | 3, 7 (je ein Test) |
| 6 Datenmodell | 2 |
| 7 Wo die Prüfung läuft | 6 |
| 8 Was der Admin bedient | 7, 8 |
| 9 Abhängigkeiten | Task 5 (Ersatzarten); die MSFS-2020-Fackeln bleiben **offen**, s. unten |
| 10 Offene Punkte | keine Aufgabe — absichtlich |

**Eine Lücke, die stehenbleibt:** Die Fackeln sind für MSFS 2020 nicht im Katalog (Issue #43).
Der Plan baut nichts dagegen — ein MSFS-2020-Pilot sieht bis zu jenem Prüflauf keine Fackel.
Das ist kein Fehler des Plans, sondern eine Abhängigkeit, und sie gehört in den Changelog-Text
nur dann, wenn sie bis zum Release nicht behoben ist.

**Platzhalter:** keine. Jeder Schritt trägt Code oder einen Befehl.

**Typen quer durch die Aufgaben geprüft:** `Ziel` ist überall `(str, float, float, float)`;
`Fenster` wird nur über `app.reddung`-Funktionen gebaut, nie von Hand; `abdeckung()` liefert
`Abdeckung` mit `treffer[schluessel].cid/.ts`; die Latch-Setzer heißen durchgehend
`set_reddung_<stufe>` und geben `bool`. `HAVARIST` ist die einzige Zeichenkette, mit der der
Havarist adressiert wird.
