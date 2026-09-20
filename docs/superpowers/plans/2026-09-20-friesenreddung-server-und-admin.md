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
