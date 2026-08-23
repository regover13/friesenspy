# AIP-Sichtflugkarten als Karten-Overlay — Implementierungsplan

> **Für agentische Bearbeiter:** ERFORDERLICHE SUB-SKILL: `superpowers:subagent-driven-development`
> (empfohlen) oder `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe umzusetzen.
> Die Schritte tragen Kästchen (`- [ ]`) zur Nachverfolgung.

**Ziel:** Die amtliche DFS-Sichtflugkarte eines Flugplatzes liegt georeferenziert und
halbtransparent über der Leaflet-Karte, das eigene Flugzeug bewegt sich darauf — in der
Weboberfläche und im MSFS-Kniebrett.

**Architektur:** Ein neues Servermodul holt die Kartenblätter von `aip.dfs.de`, bestimmt aus
Kartenrahmen, Gradnetz-Ticks und den gelesenen Grad-Zahlen die WGS84-Grenzen und legt sie ab.
Vier voneinander unabhängige Prüfungen entscheiden, ob eine Passung gilt. Das Frontend blendet
das Blatt als `L.imageOverlay` ein, sobald die eigene Position im Kartenfeld liegt.

**Tech-Stack:** Python 3.11, FastAPI, SQLite (WAL), Pillow (bereits vorhanden), APScheduler,
Leaflet, Vanilla JS.

**Spec:** [`docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md`](../specs/2026-08-23-aip-karten-overlay-design.md)
(Fassung 2 nach Gutachten — die Prüfkette in Abschnitt 3.1 ist der Kern und nicht verhandelbar)

## Globale Vorgaben

- **Keine neue Abhängigkeit.** Pillow, httpx, airportsdata, APScheduler sind vorhanden.
- **Echte Namen des Projekts** — hier gab es in Fassung 1 drei Fehlgriffe:
  `init_db(db_path: str)` (nicht eine Verbindung), `get_connection(db_path: str)`
  (es gibt **kein** `get_conn`), `settings.DB_PATH` (es gibt **kein** `settings.DATEN_PFAD`;
  Verzeichnisse bildet man als `Path(settings.DB_PATH).parent / …`, so wie `main.py:393`).
- **Es gibt kein `tests/conftest.py`.** Fixtures werden je Testdatei angelegt, DB über
  `tmp_path` wie in `tests/test_admin_db.py:21-24`.
- **Verbindungen:** `conn = get_connection(...)` / `try` / `finally: conn.close()`.
  `with conn` ist in sqlite3 eine **Transaktion**, kein Close.
- **Deutsche Bezeichner und Kommentare** im neuen Modul, wie in `app/vrp.py`.
- **`"highlight": false`** in jedem neuen Changelog-Eintrag. Ohne Ausnahme.
- **Kein `localStorage`** im Frontend — Merker über `_prefLies` / `_prefSchreib`.
- **Eine Karte, die eine Prüfung nicht besteht, wird nicht angezeigt.**
- Tests: `pytest tests/ -v`. Frontend-Tests binden an Deklarationen, nicht an Kommentare.

## Dateien

| Datei | Verantwortung |
|---|---|
| `app/aip_charts.py` (neu) | Abruf, Bildanalyse, Passung, Prüfkette — ohne DB- und FastAPI-Bezug |
| `app/database.py` | Tabelle `aip_charts`, Lese-/Schreibfunktionen |
| `app/main.py` | zwei öffentliche Endpoints, zwei Admin-Endpoints |
| `app/poller.py` | wöchentlicher Auffrischjob (in `asyncio.to_thread`) |
| `app/static/index.html` | Karten-Ebene „Sichtflugkarte" |
| `app/static/admin.html` | Liste und Handpassung, **inklusive Leaflet-Einbindung** |
| `scripts/aip_schablonen.py` (neu) | einmalig: Ziffern-Schablonen gewinnen |
| `scripts/aip_bestand.py` (neu) | Erstbefüllung über alle 446 Karten |
| `tests/fixtures/aip/` | **liegt bereits vor**: `blatt_bauen.py`, `messwerte.json`, `README.md` |
| `tests/test_aip_charts.py` (neu) | Bildanalyse, Prüfkette |
| `tests/test_aip_api.py` (neu) | Endpoints |
| `tests/test_aip_ui.py` (neu) | Quelltext-Tests für Ebene und Admin |

---

## Task 1: Tabelle `aip_charts` und Zugriffsfunktionen

**Dateien:**
- Ändern: `app/database.py` (Schema bei `airport_links`, Funktionen bei `upsert_airport_link`)
- Test: `tests/test_aip_charts.py` (neu)

**Schnittstellen:**
- Liefert: `upsert_aip_chart(conn, icao, **felder) -> str`,
  `get_aip_charts(conn, nur_gepasst=True) -> list[dict]`,
  `get_aip_chart(conn, icao) -> dict | None`,
  `delete_aip_chart(conn, icao) -> int`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_aip_charts.py
"""AIP-Sichtflugkarten: Ablage, Bildanalyse, Pruefkette.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md
"""
from __future__ import annotations

import pytest

from app.database import (
    delete_aip_chart, get_aip_chart, get_aip_charts, get_connection, init_db, upsert_aip_chart,
)

BOUNDS = dict(nord=54.24, sued=54.19, west=9.55, ost=9.65,
              feld_nord=54.235, feld_sued=54.195, feld_west=9.56, feld_ost=9.64)
GEO = dict(rahmen_px="132,180,817,865", tick_px_lat=219.0, tick_px_lon=128.4)


@pytest.fixture()
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)                       # nimmt einen PFAD, keine Verbindung
    c = get_connection(db)
    yield c
    c.close()


def test_karte_anlegen_und_lesen(conn):
    upsert_aip_chart(conn, "edxr", bild_hash="abc", **BOUNDS, **GEO,
                     quelle="auto", airac="2026AUG20", status="gepasst")
    k = get_aip_chart(conn, "EDXR")
    assert k["icao"] == "EDXR"                       # normalisiert
    assert k["nord"] == pytest.approx(54.24)
    assert k["feld_nord"] == pytest.approx(54.235)   # Feld liegt INNERHALB des Blatts
    assert k["quelle"] == "auto"


def test_ungepasste_karten_bleiben_aus_der_liste(conn):
    upsert_aip_chart(conn, "EDXR", bild_hash="a", **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="gepasst")
    upsert_aip_chart(conn, "EDWJ", bild_hash="b", **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="ungepasst")
    assert [k["icao"] for k in get_aip_charts(conn)] == ["EDXR"]
    assert len(get_aip_charts(conn, nur_gepasst=False)) == 2


def test_handpassung_ueberschreibt_und_bleibt_erkennbar(conn):
    upsert_aip_chart(conn, "EDWJ", bild_hash="a", **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="ungepasst")
    upsert_aip_chart(conn, "EDWJ", bild_hash="a", **{**BOUNDS, "nord": 55.0}, **GEO,
                     quelle="hand", airac="x", status="gepasst")
    k = get_aip_chart(conn, "EDWJ")
    assert k["quelle"] == "hand" and k["nord"] == pytest.approx(55.0)


def test_verwaiste_karte_laesst_sich_entfernen(conn):
    """Verschwindet der Eintrag aus airport_links, darf die Karte nicht im Umlauf bleiben."""
    upsert_aip_chart(conn, "EDWJ", bild_hash="a", **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="gepasst")
    assert delete_aip_chart(conn, "EDWJ") == 1
    assert get_aip_chart(conn, "EDWJ") is None


def test_fehlendes_pflichtfeld_wird_abgewiesen(conn):
    with pytest.raises(ValueError):
        upsert_aip_chart(conn, "EDXR", bild_hash="a")
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag prüfen**

Aufruf: `pytest tests/test_aip_charts.py -v`
Erwartet: `ImportError: cannot import name 'upsert_aip_chart'`

- [ ] **Schritt 3: Schema und Funktionen ergänzen**

In `app/database.py` hinter der Tabelle `airport_links`:

```sql
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
    quelle        TEXT NOT NULL,        -- 'auto' oder 'hand'
    airac         TEXT NOT NULL,
    status        TEXT NOT NULL,        -- 'gepasst' oder 'ungepasst'
    geprueft_am   TEXT
);
```

```python
_AIP_FELDER = ("bild_hash", "nord", "sued", "west", "ost",
               "feld_nord", "feld_sued", "feld_west", "feld_ost",
               "rahmen_px", "tick_px_lat", "tick_px_lon", "quelle", "airac", "status")
_AIP_SPALTEN = ("icao", *_AIP_FELDER, "geprueft_am")


def upsert_aip_chart(conn: sqlite3.Connection, icao: str, **felder) -> str:
    """Kartenpassung setzen/aktualisieren. Alle Felder aus _AIP_FELDER sind Pflicht."""
    code = (icao or "").strip().upper()
    fehlt = [f for f in _AIP_FELDER if f not in felder]
    if fehlt:
        raise ValueError(f"Pflichtfelder fehlen: {', '.join(fehlt)}")
    platz = ", ".join("?" * len(_AIP_SPALTEN))
    setzen = ", ".join(f"{f}=excluded.{f}" for f in (*_AIP_FELDER, "geprueft_am"))
    conn.execute(
        f"""INSERT INTO aip_charts ({', '.join(_AIP_SPALTEN)}) VALUES ({platz})
            ON CONFLICT(icao) DO UPDATE SET {setzen}""",
        (code, *(felder[f] for f in _AIP_FELDER), _now_utc()),
    )
    return code


def get_aip_charts(conn: sqlite3.Connection, nur_gepasst: bool = True) -> list[dict]:
    """Alle Karten, standardmaessig nur die gepassten -- eine falsch liegende Karte ist
    schlimmer als gar keine, deshalb ist das die Vorgabe."""
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
    """Karte entfernen. Noetig, wenn ihr Eintrag aus airport_links verschwindet."""
    code = (icao or "").strip().upper()
    return conn.execute("DELETE FROM aip_charts WHERE icao = ?", (code,)).rowcount
```

- [ ] **Schritt 4: Tests laufen lassen**

Aufruf: `pytest tests/test_aip_charts.py -v` → 5 bestanden

- [ ] **Schritt 5: Committen**

```bash
git add app/database.py tests/test_aip_charts.py
git commit -m "AIP-Karten: Tabelle aip_charts mit Blatt- und Feldgrenzen"
```

---

## Task 2: Blatt beschaffen — Meta-Refresh und Kapitelseiten

**Dateien:**
- Anlegen: `app/aip_charts.py`
- Test: `tests/test_aip_charts.py` (anfügen)

**Schnittstellen:**
- Liefert: `airac_url(html, basis) -> str | None`, `airac_kennung(url) -> str | None`,
  `bild_aus_html(html) -> bytes | None`, `kapitelseiten(html, basis) -> list[str]`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_aip_charts.py -- anfuegen
import base64

from app import aip_charts

BASIS = "https://aip.dfs.de/BasicVFR/pages/P0016F.html"
# kleinstes gueltiges PNG (1x1)
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_meta_refresh_wird_aufgeloest():
    html = ('<html><head><meta http-equiv="Refresh" '
            'content="0; url=../2026AUG20/pages/ABC.html" /></head></html>')
    assert aip_charts.airac_url(html, BASIS) == \
        "https://aip.dfs.de/BasicVFR/2026AUG20/pages/ABC.html"


def test_ohne_meta_refresh_kein_ziel():
    assert aip_charts.airac_url("<html></html>", BASIS) is None


def test_airac_kennung_steht_im_pfad():
    assert aip_charts.airac_kennung(
        "https://aip.dfs.de/BasicVFR/2026AUG20/pages/ABC.html") == "2026AUG20"
    assert aip_charts.airac_kennung(BASIS) is None


def test_bild_wird_aus_dem_data_uri_geholt():
    b64 = base64.b64encode(PNG_1X1).decode()
    html = f'<img id="imgAIP" class="pageImage" src="data:image/png;base64,{b64}"/>'
    roh = aip_charts.bild_aus_html(html)
    assert roh is not None
    assert roh.startswith(b"\x89PNG\r\n\x1a\n")     # echte Magic, keine Zeichenkette


def test_seite_ohne_bild_liefert_none():
    assert aip_charts.bild_aus_html("<html><img src='logo.png'></html>") is None


def test_kapitelseiten_ohne_doppelte():
    html = ('<a href="../pages/AAA.html">1</a>'
            '<a href="../pages/BBB.html">2</a>'
            '<a href="../pages/AAA.html">nochmal</a>')
    seiten = aip_charts.kapitelseiten(
        html, "https://aip.dfs.de/BasicVFR/2026AUG20/chapter/c.html")
    assert seiten == ["https://aip.dfs.de/BasicVFR/2026AUG20/pages/AAA.html",
                      "https://aip.dfs.de/BasicVFR/2026AUG20/pages/BBB.html"]
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag prüfen**

Aufruf: `pytest tests/test_aip_charts.py -k "refresh or airac or bild or kapitel" -v`
Erwartet: `ModuleNotFoundError: No module named 'app.aip_charts'`

- [ ] **Schritt 3: Modul anlegen**

```python
"""AIP-Sichtflugkarten: Blatt holen, Gradnetz vermessen, Passung rechnen und pruefen.

Eigenes Modul aus demselben Grund wie ``app/vrp.py``: Der Bestand ist Zustand mit eigener
Lebensdauer, und die Geometrie ist die Sorte Rechnung, die man gegen Messwerte pruefen will.
Deshalb enthaelt dieses Modul weder Datenbank- noch FastAPI-Bezuege.

**Die Blaetter sind keine PDFs.** Ein Eintrag aus ``airport_links`` wie
``aip.dfs.de/BasicVFR/pages/P0016F.html`` ist eine Weiterleitungsseite mit
``<meta http-equiv="Refresh">``; ein HTTP-Redirect findet NICHT statt. Wer ``curl -L``
benutzt, bekommt die Weiterleitungsseite zurueck und haelt sie fuer die Karte. Die Karte
steckt als PNG in einem ``data:``-URI im HTML der Zielseite.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md
"""
from __future__ import annotations

import base64
import logging
import math
import re
import urllib.parse
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_META_REFRESH = re.compile(r'http-equiv=.?Refresh.?[^>]*url=([^"\'>\s]+)', re.I)
_IMG_AIP = re.compile(r'id="imgAIP"[^>]*src="data:image/png;base64,([^"]+)"')
_SEITE = re.compile(r'href="(\.\./pages/[0-9A-Fa-f]+\.html)"')
_AIRAC = re.compile(r'/BasicVFR/(\d{4}[A-Z]{3}\d{2})/')


def airac_url(html: str, basis: str) -> str | None:
    """Ziel des Meta-Refresh, absolut gemacht. None, wenn die Seite keines traegt."""
    m = _META_REFRESH.search(html)
    return urllib.parse.urljoin(basis, m.group(1).strip()) if m else None


def airac_kennung(url: str) -> str | None:
    """Die Ausgabe aus dem Pfad, z. B. '2026AUG20'."""
    m = _AIRAC.search(url)
    return m.group(1) if m else None


def bild_aus_html(html: str) -> bytes | None:
    """Das Kartenblatt aus dem data:-URI. None, wenn die Seite keines enthaelt."""
    m = _IMG_AIP.search(html)
    return base64.b64decode(m.group(1)) if m else None


def kapitelseiten(html: str, basis: str) -> list[str]:
    """Alle Seiten des Platz-Kapitels, doppelte entfernt, Reihenfolge erhalten.

    Noetig, weil der gespeicherte Link nicht immer auf die Karte zeigt: Bei EDAZ oeffnet er
    die Textseite "VFR-Flugverfahren", die Sichtflugkarte ist die vierte Seite desselben
    Kapitels. 28 von 446 Karten liegen so.
    """
    gesehen: dict[str, None] = {}
    for treffer in _SEITE.findall(html):
        gesehen.setdefault(urllib.parse.urljoin(basis, treffer), None)
    return list(gesehen)
```

- [ ] **Schritt 4: Tests laufen lassen** → alle bestanden

- [ ] **Schritt 5: Committen**

```bash
git add app/aip_charts.py tests/test_aip_charts.py
git commit -m "AIP-Karten: Blatt aus Meta-Refresh und data:-URI holen"
```

---

## Task 3: Kartenrahmen und Gradnetz vermessen

**Dateien:**
- Ändern: `app/aip_charts.py`
- Test: `tests/test_aip_charts.py` (anfügen) — nutzt `tests/fixtures/aip/blatt_bauen.py`,
  das **bereits vorliegt**

**Schnittstellen:**
- Liefert: `@dataclass Rahmen(links, oben, rechts, unten, band_links, band_oben)`,
  `rahmen_finden(im) -> Rahmen | None`,
  `raster(pos, mind_belegung=0.75) -> tuple[float | None, int, float | None]`
  (Abstand, Trefferzahl, **Anker**),
  `raster_treffer(pos, d, anker) -> list[float]`,
  `tick_positionen(im, rahmen) -> tuple[list[float], list[float]]`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_aip_charts.py -- anfuegen
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "aip"))
from blatt_bauen import blatt_bauen  # noqa: E402


def test_rahmen_wird_im_standardlayout_gefunden():
    r = aip_charts.rahmen_finden(blatt_bauen())
    assert r is not None
    assert (round(r.links), round(r.oben), round(r.rechts), round(r.unten)) == (132, 180, 817, 865)


def test_rahmen_auch_bei_gekreuzter_linie():
    """Die vertikale 'Berichtigung:'-Beschriftung unterbricht die linke Rahmenlinie; sie ist
    dann nur zu 88 Prozent durchgehend. Deshalb zaehlt der Anteil, nicht der laengste Lauf."""
    r = aip_charts.rahmen_finden(blatt_bauen(rahmen_kreuzen=True))
    assert r is not None and round(r.links) == 132


def test_rahmen_nicht_die_kopfzeilenlinie():
    """Layout-Trennlinien von Kopf- und Fusszeile bilden auf manchen Blaettern selbst ein
    Paar im Doppelrahmen-Abstand. Die naive Wahl (aeusserstes Paar) lieferte dann
    (132, 136, 817, 909) statt (132, 180, 817, 865) -- gemessen am 23.08.2026."""
    r = aip_charts.rahmen_finden(blatt_bauen(kopf_fuss_linien=True))
    assert r is not None
    assert (round(r.links), round(r.oben), round(r.rechts), round(r.unten)) == \
        (132, 180, 817, 865)


def test_rahmen_auch_wenn_alles_zusammenkommt():
    r = aip_charts.rahmen_finden(
        blatt_bauen(kopf_fuss_linien=True, stoerstriche=True, rahmen_kreuzen=True))
    assert r is not None and (round(r.oben), round(r.unten)) == (180, 865)


def test_raster_verwirft_stoerstriche():
    """Gutachten 23.08.2026: Ein feineres Raster hat immer mindestens so viele Treffer.
    Ohne Belegungspruefung lieferte diese Eingabe 16,67 statt 50."""
    d, n = aip_charts.raster([100.0, 150.0, 200.0, 217.0, 250.0])
    assert d == pytest.approx(50.0)
    assert n == 4


def test_raster_unterteilt_den_abstand_nicht():
    """Ein zu feines Raster passt immer, und die Achsen-Vielfachen wuerden es zudecken.
    Bei EDAB kam so ein Drittel des echten Abstands heraus, bei 0,006 Grad Probenfehler."""
    assert aip_charts.raster([0.0, 60.0, 120.0])[0] == pytest.approx(60.0)


def test_raster_vertraegt_luecken():
    """Fehlt ein Tick, bleibt das Raster gueltig -- die Vielfachen decken die Luecke ab."""
    assert aip_charts.raster([151.0, 289.0, 566.0, 704.0])[0] == pytest.approx(138.3, abs=0.5)


def test_raster_treffer_filtert_ausreisser():
    """Nur die Positionen auf dem Raster taugen als Stuetzstelle fuers Zahlenlesen."""
    d, _n, anker = aip_charts.raster([100.0, 150.0, 200.0, 217.0, 250.0])
    assert aip_charts.raster_treffer([100.0, 150.0, 200.0, 217.0, 250.0], d, anker) == \
        [100.0, 150.0, 200.0, 250.0]


def test_stoerstrich_ganz_vorn_kippt_die_stuetzstellen_nicht():
    """Ohne mitgelieferten Anker nimmt raster_treffer pos[0] -- ist das der Stoerstrich,
    ueberlebt genau er, und beschriftung_lesen liefert eine leere Liste (Gutachten
    23.08.2026, Befund B1)."""
    ticks = [172.0, 196.0, 324.0, 453.0, 581.0, 709.0]
    d, _n, anker = aip_charts.raster(ticks)
    assert aip_charts.raster_treffer(ticks, d, anker) == [196.0, 324.0, 453.0, 581.0, 709.0]


def test_ticks_liefern_die_gebauten_abstaende():
    im = blatt_bauen(tick_lat_px=219.0, tick_lon_px=128.4)
    ty, tx = aip_charts.tick_positionen(im, aip_charts.rahmen_finden(im))
    assert aip_charts.raster(ty)[0] == pytest.approx(219.0, abs=1.0)
    assert aip_charts.raster(tx)[0] == pytest.approx(128.4, abs=1.0)


def test_ticks_auch_bei_hindernissymbolen_im_randband():
    """Fall EDCQ: Windraeder ragen ins obere Band."""
    im = blatt_bauen(stoerstriche=True, tick_lon_px=128.4)
    _ty, tx = aip_charts.tick_positionen(im, aip_charts.rahmen_finden(im))
    assert aip_charts.raster(tx)[0] == pytest.approx(128.4, abs=1.0)


def test_feines_gitter_wird_nicht_verworfen():
    """Eine Obergrenze von 30 Ticks warf Querformat-Karten hinaus (EDAB 31, EDWE 39)."""
    im = blatt_bauen(tick_lat_px=54.78, tick_lon_px=32.1)
    ty, _tx = aip_charts.tick_positionen(im, aip_charts.rahmen_finden(im))
    assert len(ty) > 10
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag prüfen**

Aufruf: `pytest tests/test_aip_charts.py -k "rahmen or raster or ticks or gitter" -v`
Erwartet: `AttributeError: module 'app.aip_charts' has no attribute 'rahmen_finden'`

- [ ] **Schritt 3: Vermessung umsetzen**

```python
@dataclass(frozen=True)
class Rahmen:
    """Inneres Kartenfeld plus die beiden Randbaender, in denen die Ticks stehen."""
    links: float
    oben: float
    rechts: float
    unten: float
    band_links: float   # aeussere senkrechte Rahmenlinie
    band_oben: float    # aeussere waagerechte Rahmenlinie


# Der Doppelrahmen liegt rund 24 Pixel auseinander.
_PAAR_MIN, _PAAR_MAX = 15, 35
_FELD_MIN = 200
# Streng zuerst. Bei EDBY lieferte erst die strengste Schwelle den richtigen Abstand;
# die lockere holte zwei Stoerstriche herein und drueckte 219 auf 28,7.
_SCHWELLEN = (0.65, 0.55, 0.45, 0.35)


def _anteile(px, breite: int, hoehe: int, achse: str, von: int, bis: int) -> list[float]:
    """Anteil dunkler Pixel je Zeile bzw. Spalte.

    Nicht der laengste durchgehende Lauf: Die linke Rahmenlinie wird oft von der vertikalen
    "Berichtigung:"-Beschriftung gekreuzt und ist dann nur zu 88 Prozent durchgehend --
    rechts, wo kein Text kreuzt, sind es 100.

    Zu beachten (Gutachten 23.08.2026): Gemessen wird ueber ``von..bis``, nicht zwingend
    ueber das ganze Blatt. Die obere Rahmenlinie reicht nur ueber rund 78 Prozent der
    Blattbreite; sinkt die Schwellenleiter zu tief, greifen sonst die Trennlinien der Kopf-
    und Fusszeile, die weiter aussen liegen. Der Test
    ``test_rahmen_nicht_die_kopfzeilenlinie`` deckt genau diesen Fall ab.
    """
    n = hoehe if achse == "h" else breite
    spanne = max(1, bis - von)
    return [
        sum(1 for j in range(von, bis)
            if (px[j, i] if achse == "h" else px[i, j]) < 128) / spanne
        for i in range(n)
    ]


def _linien(werte: list[float], schwelle: float) -> list[float]:
    treffer = [i for i, v in enumerate(werte) if v >= schwelle]
    gruppen: list[list[int]] = []
    for t in treffer:
        if gruppen and t - gruppen[-1][-1] <= 2:
            gruppen[-1].append(t)
        else:
            gruppen.append([t])
    return [sum(g) / len(g) for g in gruppen]


def _paare(linien: list[float]) -> list[tuple[float, float]]:
    """Alle Linienpaare im Doppelrahmen-Abstand."""
    return [(a, b) for a, b in zip(linien, linien[1:]) if _PAAR_MIN <= b - a <= _PAAR_MAX]


def _traegt_gradnetz(px, fest_von: float, fest_bis: float,
                     von: float, bis: float, achse: str) -> bool:
    """Steht in diesem Randband ein gleichmaessiges Gradnetz?"""
    for sw in _TICK_SCHWELLEN:
        t = _striche(px, fest_von, fest_bis, von, bis, achse, sw)
        if 2 <= len(t) <= _TICK_MAX and raster(t)[0]:
            return True
    return False


def rahmen_finden(im) -> Rahmen | None:
    """Doppelrahmen des Kartenfelds. None, wenn das Blatt keines traegt (Textseite).

    Gesucht wird das **engste** Paar-Rechteck, dessen beide Randbaender ein Gradnetz tragen
    -- nicht das aeusserste. Denn auf manchen Blaettern bilden die Layout-Trennlinien von
    Kopf- und Fusszeile selbst ein Paar im Doppelrahmen-Abstand und wuerden dann gewinnen.
    Gemessen am 23.08.2026 gegen ein Testblatt mit solchen Linien: Die aeusserste Wahl
    lieferte (132, 136, 817, 909) statt (132, 180, 817, 865).

    Der Kartenrahmen ist durch sein Gradnetz definiert, nicht durch seine Lage -- deshalb
    entscheidet das Band, nicht der Rand.
    """
    breite, hoehe = im.size
    px = im.load()
    waagerecht = _anteile(px, breite, hoehe, "h", 0, breite)
    for sh in _SCHWELLEN:
        hp = _paare(_linien(waagerecht, sh))
        kombis = sorted(
            ((unten_i - oben_i, (oben_a, oben_i), (unten_i, unten_a))
             for (oben_a, oben_i) in hp for (unten_i, unten_a) in hp
             if unten_i - oben_i >= _FELD_MIN),
            key=lambda k: k[0])
        for _h, (oben_a, oben_i), (unten_i, _ua) in kombis:
            senkrecht = _anteile(px, breite, hoehe, "v", int(oben_i), int(unten_i))
            for sv in _SCHWELLEN:
                vp = _paare(_linien(senkrecht, sv))
                vkombis = sorted(
                    ((rechts_i - links_i, (links_a, links_i), (rechts_i, rechts_a))
                     for (links_a, links_i) in vp for (rechts_i, rechts_a) in vp
                     if rechts_i - links_i >= _FELD_MIN),
                    key=lambda k: k[0])
                for _b, (links_a, links_i), (rechts_i, _ra) in vkombis:
                    if (_traegt_gradnetz(px, links_a + 2, links_i - 2,
                                         oben_i + 2, unten_i - 2, "y")
                            and _traegt_gradnetz(px, oben_a + 2, oben_i - 2,
                                                 links_i + 2, rechts_i - 2, "x")):
                        return Rahmen(links=links_i, oben=oben_i,
                                      rechts=rechts_i, unten=unten_i,
                                      band_links=links_a, band_oben=oben_a)
    return None


def raster(pos: list[float],
           mind_belegung: float = 0.75) -> tuple[float | None, int, float | None]:
    """Bestes Raster in den Kandidatenpositionen: (Abstand, Trefferzahl, Anker).

    **Der Anker gehoert mit ins Ergebnis.** Ohne ihn nimmt ``raster_treffer`` die erste
    Position als Bezug -- ist das ausgerechnet ein Stoerstrich, ueberlebt nur er, und das
    Zahlenlesen bekommt keine Stuetzstelle (Gutachten 23.08.2026, Befund B1).

    In das Randband ragen Hindernissymbole hinein -- bei EDCQ Windraeder -- und werden als
    Tick gelesen. Wer verlangt, dass ALLE Positionen gleichmaessig liegen, scheitert an einem
    einzigen Stoerstrich; gesucht wird deshalb die groesste Teilmenge auf einem Raster.

    Entscheidend ist die **Belegung**: Ein feineres Raster hat immer mindestens so viele
    Treffer, laesst aber Plaetze leer. Ohne diese Pruefung lieferte
    ``raster([100, 150, 200, 217, 250])`` den Wert 16,67 statt 50 (Gutachten 23.08.2026) --
    genau der stille Fehler, den die Spec in Abschnitt 3.2 beschreibt.

    Der Startabstand wird NICHT unterteilt; Luecken deckt das Raster ueber seine Vielfachen ab.
    """
    if len(pos) < 2:
        return None, 0, None
    bestes = None
    for i in range(len(pos)):
        for j in range(i + 1, len(pos)):
            d = pos[j] - pos[i]
            if d < 12:
                continue
            treffer = raster_treffer(pos, d, pos[i])
            if len(treffer) < 2:
                continue
            ks = [round((q - pos[i]) / d) for q in treffer]
            spanne = max(ks) - min(ks)
            if spanne == 0 or len(treffer) / (spanne + 1) < mind_belegung:
                continue
            fein = (max(treffer) - min(treffer)) / spanne
            guete = (len(treffer), fein)
            if bestes is None or guete > bestes[0]:
                bestes = (guete, fein, len(treffer), min(treffer))
    return (bestes[1], bestes[2], bestes[3]) if bestes else (None, 0, None)


def raster_treffer(pos: list[float], d: float, anker: float) -> list[float]:
    """Die Positionen, die auf dem Raster (anker + k*d) liegen. Alles andere ist Stoerstrich.

    Wird auch beim Zahlenlesen gebraucht: Ein Windradstrich mit einer Zahl daneben darf keine
    Stuetzstelle werden.
    """
    if not pos or not d:
        return []
    return [q for q in pos
            if abs((q - anker) / d - round((q - anker) / d)) * d <= 2.0]


_TICK_SCHWELLEN = (0.95, 0.85, 0.7, 0.55)
# raster() prueft alle Positionspaare, ist also quadratisch in der Tickzahl. Bei feinem
# Gitter (bis zu 100 Ticks) sind das 10 000 Kandidaten je Achse und Schwelle -- im Messlauf
# ueber 446 Blaetter deutlich spuerbar. Falls der Erstlauf zu lange braucht: erst die
# Kandidaten auf die haeufigsten Abstaende eindampfen, nicht die Belegungspruefung opfern.
# Grosszuegig: ueber die Gueltigkeit entscheidet die Gleichmaessigkeit in raster(), nicht die
# Anzahl. Eine Grenze von 30 warf Querformat-Karten hinaus (EDAB 31 Ticks, EDWE 39).
_TICK_MAX = 100


def _striche(px, fest_von: float, fest_bis: float, von: float, bis: float,
             achse: str, schwelle: float) -> list[float]:
    spanne = int(fest_bis) - int(fest_von)
    if spanne < 5:
        return []
    treffer = []
    for v in range(int(von), int(bis)):
        n = sum(1 for f in range(int(fest_von), int(fest_bis))
                if (px[f, v] if achse == "y" else px[v, f]) < 128)
        if n >= schwelle * spanne:
            treffer.append(v)
    gruppen: list[list[int]] = []
    for t in treffer:
        if gruppen and t - gruppen[-1][-1] <= 3:
            gruppen[-1].append(t)
        else:
            gruppen.append([t])
    return [sum(g) / len(g) for g in gruppen]


def tick_positionen(im, rahmen: Rahmen | None) -> tuple[list[float], list[float]]:
    """Tickpositionen in den Randbaendern: (senkrecht/Breite, waagerecht/Laenge).

    Genommen wird die ERSTE Schwelle, die ein gueltiges Raster ergibt -- bewusst nicht die
    beste aus allen Kombinationen. Wuerde man 4x4 Schwellenkombinationen gegen die Gegenprobe
    optimieren, stiege deren Zufallstrefferquote von 1,45 auf rund 21 Prozent (Spec 3.2).
    """
    if rahmen is None:
        return [], []
    px = im.load()
    ty: list[float] = []
    tx: list[float] = []
    for sw in _TICK_SCHWELLEN:
        k = _striche(px, rahmen.band_links + 2, rahmen.links - 2,
                     rahmen.oben + 2, rahmen.unten - 2, "y", sw)
        if 2 <= len(k) <= _TICK_MAX and raster(k)[0]:
            ty = k
            break
    for sw in _TICK_SCHWELLEN:
        k = _striche(px, rahmen.band_oben + 2, rahmen.oben - 2,
                     rahmen.links + 2, rahmen.rechts - 2, "x", sw)
        if 2 <= len(k) <= _TICK_MAX and raster(k)[0]:
            tx = k
            break
    return ty, tx
```

- [ ] **Schritt 4: Alle Tests laufen lassen**

Aufruf: `pytest tests/test_aip_charts.py -v`

Der Schalter `kopf_fuss_linien` liegt in `blatt_bauen.py` **bereits vor** und zeichnet die
Layoutlinien bewusst als *Paar* im Doppelrahmen-Abstand — eine Einzellinie wäre kein
ernsthafter Test, weil sie gar kein Paar bildet. Gegen die naive Fassung (äußerstes Paar)
schlägt dieser Test nachweislich fehl; gegen die Fassung oben (engstes Rechteck mit Gradnetz)
besteht er, ebenso wie die Kombination aller Störfälle. Am 23.08.2026 an allen sechs
Varianten gemessen.

- [ ] **Schritt 5: Committen**

```bash
git add app/aip_charts.py tests/test_aip_charts.py tests/fixtures/aip/blatt_bauen.py
git commit -m "AIP-Karten: Kartenrahmen und Gradnetz vermessen"
```

---

## Task 4: Grad-Zahlen lesen

**Dateien:**
- Anlegen: `scripts/aip_schablonen.py`
- Ändern: `app/aip_charts.py`
- Test: `tests/test_aip_charts.py` (anfügen)

**Schnittstellen:**
- Braucht: `Rahmen`, `raster`, `raster_treffer` aus Task 3
- Liefert: `zeichen_im_band(im, rahmen, tick, achse) -> tuple[list, list]` (oben/unten bzw.
  links/rechts der Marke), `ziffer_erkennen(bitmap) -> int | None`,
  `zahl_lesen(zeichen) -> int | None`,
  `beschriftung_lesen(im, rahmen, ticks, achse) -> list[tuple[float, float]]`

**Das ist der unsichere Teil.** Die Ziffernformen sind stabil (die „1" kam über 55 Blätter
38-mal bitidentisch vor), aber nicht bitgleich. **Und die Segmentierung ist noch nicht
zuverlässig:** In einer Stichprobe über 120 Blätter standen neben sauberen Zeichen auch 2×2-
und 2×1-Bruchstücke, einzelne Muster hatten mitten im Zeichen eine leere Zeile. Wenn dieser
Task mehr Aufwand verlangt als geplant, ist das der erwartete Ort dafür.

**Wichtig: beide Achsen.** Die Breitenangaben stehen im **linken** Band über und unter dem
Tickstrich, die Längenangaben im **oberen** Band links und rechts davon. Fassung 1 dieses
Plans hatte nur das linke Band — damit fehlte die Hälfte der Georeferenzierung.

- [ ] **Schritt 1: Schablonen einmalig gewinnen**

```python
#!/usr/bin/env python3
"""Einmaliges Hilfsskript: Ziffern-Schablonen aus AIP-Blaettern gewinnen.

Aufruf:  python scripts/aip_schablonen.py <verzeichnis-mit-png>
Ausgabe: die haeufigsten Zeichenmuster als ASCII, absteigend nach Haeufigkeit.
Die Zuordnung Muster -> Ziffer traegt ein Mensch in app/aip_charts._SCHABLONEN ein; sie
laesst sich nicht erraten, nur ansehen.

Bruchstuecke (2x2, 2x1) und Muster mit leeren Zeilen in der Mitte sind ein Zeichen dafuer,
dass die Segmentierung noch nicht sitzt -- dann ist zuerst zeichen_im_band() zu verbessern,
nicht die Schablonenliste zu verlaengern.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.aip_charts import rahmen_finden, tick_positionen, zeichen_im_band  # noqa: E402


def main(verzeichnis: str) -> None:
    zaehler: collections.Counter = collections.Counter()
    muster: dict[str, tuple] = {}
    for pfad in sorted(Path(verzeichnis).glob("*.png")):
        im = Image.open(pfad).convert("L")
        r = rahmen_finden(im)
        if r is None:
            continue
        ty, tx = tick_positionen(im, r)
        for tick in ty:
            for gruppe in zeichen_im_band(im, r, tick, "y"):
                for bm in gruppe:
                    s = "/".join("".join(str(v) for v in z) for z in bm)
                    zaehler[s] += 1
                    muster.setdefault(s, bm)
    for s, n in zaehler.most_common(30):
        bm = muster[s]
        print(f"--- {n}x  {len(bm[0])}x{len(bm)} ---")
        for z in bm:
            print("   " + "".join("#" if v else "." for v in z))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/aiplauf/png")
```

- [ ] **Schritt 2: Fehlschlagenden Test schreiben**

```python
# tests/test_aip_charts.py -- anfuegen
from blatt_bauen import ZIFFERN  # noqa: E402


def _bitmap(ziffer: str) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(1 if z == "#" else 0 for z in zeile) for zeile in ZIFFERN[ziffer])


def test_jede_ziffer_der_pruefschrift_wird_erkannt():
    for z in "0123456789":
        assert aip_charts.ziffer_erkennen(_bitmap(z)) == int(z), f"Ziffer {z}"


def test_ein_pixel_hoeher_wird_noch_erkannt():
    """Die Schwellwertbildung an den Raendern erzeugt Hoehenunterschiede von einem Pixel --
    daran scheitert ein Hash-Vergleich, der Schablonenvergleich darf es nicht."""
    bm = _bitmap("5")
    assert aip_charts.ziffer_erkennen(bm + (bm[-1],)) == 5


def test_unlesbares_zeichen_liefert_none():
    """Lieber keine Zahl als eine falsche: Eine falsche Minute verschiebt um 1,85 km."""
    assert aip_charts.ziffer_erkennen(((1, 0, 1), (0, 1, 0), (1, 0, 1))) is None


def test_breite_wird_aus_dem_linken_band_gelesen():
    im = blatt_bauen(breite_links=(54, 14), tick_lat_px=219.0)
    r = aip_charts.rahmen_finden(im)
    ty, _tx = aip_charts.tick_positionen(im, r)
    paare = aip_charts.beschriftung_lesen(im, r, ty, "y")
    assert len(paare) >= 3
    # nach Sueden abnehmend: 54 Grad 14', 13', 12'
    assert [round(g, 4) for _p, g in paare[:3]] == [54.2333, 54.2167, 54.2]


def test_laenge_wird_aus_dem_oberen_band_gelesen():
    """Fassung 1 dieses Plans las nur das linke Band -- damit fehlte die halbe Passung."""
    im = blatt_bauen(laenge_oben=(9, 36), tick_lon_px=128.4)
    r = aip_charts.rahmen_finden(im)
    _ty, tx = aip_charts.tick_positionen(im, r)
    paare = aip_charts.beschriftung_lesen(im, r, tx, "x")
    assert len(paare) >= 3
    assert [round(g, 4) for _p, g in paare[:3]] == [9.6, 9.6167, 9.6333]
```

- [ ] **Schritt 3: Test laufen lassen, Fehlschlag prüfen**

Aufruf: `pytest tests/test_aip_charts.py -k "ziffer or band or breite or laenge" -v`
Erwartet: `AttributeError: … has no attribute 'ziffer_erkennen'`

- [ ] **Schritt 4: Lesen umsetzen**

```python
# Aus den Blaettern gewonnen (scripts/aip_schablonen.py), Zuordnung von Hand geprueft.
# Die Muster stammen aus der gerenderten DFS-Schrift; bitgleich sind sie NICHT, deshalb
# vergleicht ziffer_erkennen() mit Toleranz. Die Pruefschrift der Tests
# (tests/fixtures/aip/blatt_bauen.py) ist eine andere -- sie prueft das Verfahren, nicht
# diese Tabelle. Beide Saetze muessen hier stehen.
# MEHRERE Muster je Ziffer: Die DFS-Schrift und die Pruefschrift der Tests sind
# verschieden breit (DFS-"1" ist 3 Pixel breit, die Pruefschrift 5), und ziffer_erkennen()
# vergleicht nur bei gleicher Breite. Mit einem Muster je Ziffer koennten beide nicht
# nebeneinander stehen (Gutachten 23.08.2026, Befund B3).
_SCHABLONEN: dict[int, list[tuple[str, ...]]] = {
    1: [("..#", "###", "..#", "..#", "..#", "..#", "..#", "..#", "..#")],
    # Die uebrigen DFS-Muster traegt der Bearbeiter aus der Ausgabe von
    # scripts/aip_schablonen.py ein. Die zehn Muster der Pruefschrift kommen aus
    # tests/fixtures/aip/blatt_bauen.ZIFFERN und werden beim Import angehaengt -- so bleibt
    # die Pruefschrift dort, wo sie hingehoert, und wandert nicht in den Produktionscode.
}
# Ueber diesem Anteil abweichender Pixel gilt ein Zeichen als unlesbar.
_ZIFFER_MAX_ABWEICHUNG = 0.15


def _auf_hoehe(bm: tuple[tuple[int, ...], ...], hoehe: int) -> tuple[tuple[int, ...], ...]:
    """Bitmap auf eine Zielhoehe bringen, Zeilen proportional abgetastet."""
    if not bm or hoehe < 1:
        return bm
    return tuple(bm[min(len(bm) - 1, int(i * len(bm) / hoehe))] for i in range(hoehe))


def ziffer_erkennen(bitmap: tuple[tuple[int, ...], ...]) -> int | None:
    """Ziffer per Schablonenvergleich. None, wenn keine gut genug passt."""
    if not bitmap or not bitmap[0]:
        return None
    bester: tuple[float, int] | None = None
    for ziffer, muster_liste in _SCHABLONEN.items():
        for muster in muster_liste:
            schablone = tuple(tuple(1 if z == "#" else 0 for z in zeile) for zeile in muster)
            if len(schablone[0]) != len(bitmap[0]):
                continue
            angepasst = _auf_hoehe(bitmap, len(schablone))
            falsch = sum(a != b for za, zs in zip(angepasst, schablone)
                         for a, b in zip(za, zs))
            anteil = falsch / (len(schablone) * len(schablone[0]))
            if bester is None or anteil < bester[0]:
                bester = (anteil, ziffer)
    if bester is None or bester[0] > _ZIFFER_MAX_ABWEICHUNG:
        return None
    return bester[1]


def zahl_lesen(zeichen: list) -> int | None:
    """Ziffernfolge zu einer Zahl. None, sobald ein Zeichen unlesbar ist."""
    if not zeichen:
        return None
    wert = 0
    for bm in zeichen:
        z = ziffer_erkennen(bm)
        if z is None:
            return None
        wert = wert * 10 + z
    return wert


def _zeichen_zerlegen(px, x0: int, x1: int, y0: int, y1: int) -> list:
    """Einzelzeichen in einem Rechteck, von links nach rechts."""
    spalten = [x for x in range(x0, x1) if any(px[x, y] < 128 for y in range(y0, y1))]
    gruppen: list[list[int]] = []
    for x in spalten:
        if gruppen and x - gruppen[-1][-1] <= 1:
            gruppen[-1].append(x)
        else:
            gruppen.append([x])
    out = []
    for g in gruppen:
        if not (2 <= len(g) <= 12):
            continue
        ys = [y for y in range(y0, y1) if any(px[x, y] < 128 for x in g)]
        if not ys or len(ys) > 14:
            continue
        out.append(tuple(
            tuple(1 if px[x, y] < 128 else 0 for x in g)
            for y in range(min(ys), max(ys) + 1)
        ))
    return out


def zeichen_im_band(im, rahmen: Rahmen, tick: float, achse: str,
                    tick_abstand: float | None = None) -> tuple[list, list]:
    """Die beiden Zeichengruppen an einer Tickmarke: (Grad, Minute).

    Bei der Breite (``achse='y'``) steht der Gradwert im linken Band UEBER dem Strich, die
    Minute darunter. Bei der Laenge (``achse='x'``) steht beides im oberen Band, links und
    rechts des Strichs.
    """
    px = im.load()
    # Das Suchfenster richtet sich nach dem Tickabstand, nicht nach einer festen Zahl. Mit
    # starren 20 Pixeln griffen benachbarte Beschriftungen ineinander, sobald das Gitter fein
    # wird: bei dx = 34 waren von 20 Ticks nur 6 lesbar, bei 32 keiner mehr -- und 25 der 446
    # Karten haben einen Abstand unter 40 Pixeln (Gutachten 23.08.2026, Befund B5).
    grenze = 20 if tick_abstand is None else max(4, int(tick_abstand / 2) - 1)
    if achse == "y":
        x0, x1 = int(rahmen.band_links) + 1, int(rahmen.links)
        hoch = min(grenze, 14)
        oben = _zeichen_zerlegen(px, x0, x1, max(0, int(tick) - hoch), int(tick) - 1)
        unten = _zeichen_zerlegen(px, x0, x1, int(tick) + 1,
                                  min(im.size[1], int(tick) + hoch))
        return oben, unten
    y0, y1 = int(rahmen.band_oben) + 1, int(rahmen.oben)
    links = _zeichen_zerlegen(px, max(0, int(tick) - grenze), int(tick) - 1, y0, y1)
    rechts = _zeichen_zerlegen(px, int(tick) + 1,
                               min(im.size[0], int(tick) + grenze), y0, y1)
    return links, rechts


def beschriftung_lesen(im, rahmen: Rahmen, ticks: list[float],
                       achse: str) -> list[tuple[float, float]]:
    """Paare (Pixelposition, Winkel in Grad) fuer jeden beschrifteten Tick.

    Nur Ticks, die auf dem Raster liegen, kommen infrage -- ein Hindernissymbol mit einer Zahl
    daneben darf keine Stuetzstelle werden. Ticks mit unlesbarer Zahl fallen heraus.
    """
    d, _anzahl, anker = raster(ticks)
    echte = raster_treffer(ticks, d, anker) if d else ticks
    paare: list[tuple[float, float]] = []
    for t in echte:
        a, b = zeichen_im_band(im, rahmen, t, achse, d)
        grad, minute = zahl_lesen(a), zahl_lesen(b)
        if grad is None or minute is None or not (0 <= minute < 60):
            continue
        paare.append((t, grad + minute / 60.0))
    return paare
```

- [ ] **Schritt 5: Tests laufen lassen und committen**

```bash
git add app/aip_charts.py scripts/aip_schablonen.py tests/test_aip_charts.py
git commit -m "AIP-Karten: Grad-Zahlen beider Achsen per Schablonenvergleich lesen"
```

---

## Task 5: Passung rechnen — die Prüfkette

**Dateien:**
- Ändern: `app/aip_charts.py`
- Test: `tests/test_aip_charts.py` (anfügen)

**Schnittstellen:**
- Liefert: `@dataclass Passung(nord, sued, west, ost, feld_nord, feld_sued, feld_west,
  feld_ost, rahmen_px, tick_px_lat, tick_px_lon)`,
  `ausgleichsgerade(paare) -> tuple[float, float, float] | None` (Steigung, Achsenabschnitt,
  größtes Residuum), `passung_rechnen(im, arp_lat, arp_lon) -> Passung | None`

**Hier lag der Konstruktionsfehler der ersten Fassung.** Die cos-Probe prüft nur das
*Verhältnis* der Tick-Abstände; die Grenzen entstehen aus den *gelesenen Zahlen*. Eine falsch
gelesene Minute lässt das Verhältnis unverändert — die Probe war blind gegen genau den Fehler,
für den sie gebaut war. Es braucht alle vier Prüfungen aus Spec 3.1.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_aip_charts.py -- anfuegen

def test_ausgleichsgerade_meldet_das_groesste_residuum():
    m, b, res = aip_charts.ausgleichsgerade([(0.0, 0.0), (10.0, 1.0), (20.0, 2.0)])
    assert m == pytest.approx(0.1) and b == pytest.approx(0.0) and res < 1e-9


def test_verfaelschte_stuetzstelle_faellt_auf():
    """Ein um eine Bogenminute falsch gelesener Wert erzeugt ein riesiges Residuum -- das
    ist die Pruefung, gegen die die cos-Probe blind ist."""
    gut = [(0.0, 54.0), (219.0, 54.0 - 1 / 60), (438.0, 54.0 - 2 / 60)]
    schlecht = [(0.0, 54.0), (219.0, 54.0 - 2 / 60), (438.0, 54.0 - 2 / 60)]
    assert aip_charts.ausgleichsgerade(gut)[2] < 1e-9
    assert aip_charts.ausgleichsgerade(schlecht)[2] > 1e-4


def test_passung_deckt_das_ganze_blatt_ab():
    """Die Blattgrenzen liegen AUSSERHALB des Kartenfelds -- das Blatt wird ungeschnitten
    ausgeliefert, damit Kopfzeile und Frequenzen lesbar bleiben."""
    im = blatt_bauen(breite_links=(54, 14), laenge_oben=(9, 36))
    p = aip_charts.passung_rechnen(im, arp_lat=54.21, arp_lon=9.62)
    assert p is not None
    assert p.nord > p.feld_nord and p.sued < p.feld_sued
    assert p.west < p.feld_west and p.ost > p.feld_ost


def test_platz_ausserhalb_des_kartenfelds_wird_verworfen():
    """Nicht nur 'irgendwo auf dem Blatt': Das Blatt ist rund 10 km hoch, eine Verschiebung
    um 5 km haette den schwaecheren Test bestanden (Gutachten 23.08.2026)."""
    im = blatt_bauen(breite_links=(54, 14), laenge_oben=(9, 36))
    assert aip_charts.passung_rechnen(im, arp_lat=54.30, arp_lon=9.62) is None


def test_karte_ohne_rahmen_liefert_keine_passung():
    from PIL import Image
    assert aip_charts.passung_rechnen(Image.new("L", (875, 1240), 255), 54.0, 9.0) is None


def test_cos_probe_verwirft_falsche_breite():
    """EDWT lag mit 4,14 Grad daneben und wurde verworfen."""
    im = blatt_bauen(breite_links=(54, 14), laenge_oben=(9, 36))
    assert aip_charts.passung_rechnen(im, arp_lat=48.0, arp_lon=9.62) is None
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag prüfen**

Aufruf: `pytest tests/test_aip_charts.py -k "ausgleich or passung or platz or cos" -v`

- [ ] **Schritt 3: Umsetzen**

```python
@dataclass(frozen=True)
class Passung:
    nord: float
    sued: float
    west: float
    ost: float
    feld_nord: float
    feld_sued: float
    feld_west: float
    feld_ost: float
    rahmen_px: str          # "links,oben,rechts,unten"
    tick_px_lat: float
    tick_px_lon: float


# Breitenabweichung, ab der die cos-Probe durchfaellt. Ueber 356 gemessene Karten lag der
# Fehler im Median bei 0,085 Grad, der 90-Prozent-Wert bei 0,167, das Maximum bei 0,354 --
# die Toleranz ist also in-sample gewaehlt, mit 13 Prozent Luft.
GEGENPROBE_TOLERANZ = 0.4
# Deutschland liegt zwischen 47,3 und 55,0 Grad. Ein Verhaeltnis ausserhalb dieses Bandes
# ist Unsinn und wird frueh verworfen -- das kostet nichts und nimmt der Suche Freiheit.
_V_MIN, _V_MAX = 0.57, 0.68
# Bei 22 von 356 Karten tragen die Achsen verschiedene Tick-Einheiten. Jeder Kandidat mehr
# hebt die Zufallstrefferquote um rund einen halben Prozentpunkt (Spec 3.2).
_ACHSEN_VIELFACHE = (1.0, 2.0, 0.5)
# Mindestens so viele lesbare Stuetzstellen je Achse. Bei zweien gibt es keine Residuen und
# damit keine Pruefung.
_MIND_STUETZSTELLEN = 3
# Groesstes zulaessiges Residuum in Pixeln. Ein Ziffernfehler von einer Bogenminute erzeugt
# bei 219 px je Minute rund 146 px -- die Schwelle ist also sehr scharf.
_MAX_RESIDUUM_PX = 2.0


def ausgleichsgerade(paare: list[tuple[float, float]]
                     ) -> tuple[float, float, float] | None:
    """Gerade Grad = m*Pixel + b ueber ALLE Stuetzstellen, dazu das groesste Residuum.

    Nur die erste und letzte Stuetzstelle zu nehmen, waere billiger und deutlich schlechter:
    Ein einzelner Ziffernfehler bliebe dann unbemerkt und wuerde bei der Verlaengerung auf
    das ganze Blatt noch verstaerkt.
    """
    n = len(paare)
    if n < 2:
        return None
    sx = sum(p for p, _ in paare)
    sy = sum(g for _, g in paare)
    sxx = sum(p * p for p, _ in paare)
    sxy = sum(p * g for p, g in paare)
    nenner = n * sxx - sx * sx
    if abs(nenner) < 1e-12:
        return None
    m = (n * sxy - sx * sy) / nenner
    b = (sy - m * sx) / n
    res = max(abs(g - (m * p + b)) for p, g in paare)
    return m, b, res


def passung_rechnen(im, arp_lat: float, arp_lon: float) -> Passung | None:
    """WGS84-Grenzen von Blatt und Kartenfeld. None, sobald eine Pruefung durchfaellt."""
    rahmen = rahmen_finden(im)
    if rahmen is None:
        return None
    ty, tx = tick_positionen(im, rahmen)
    dy, _ny, _ay = raster(ty)
    dx, _nx, _ax = raster(tx)
    if not dy or not dx:
        return None

    # (1) cos-Probe -- Vorpruefung der Skala.
    bester = None
    for k in _ACHSEN_VIELFACHE:
        v = (dx * k) / dy
        if not (_V_MIN < v < _V_MAX):
            continue
        fehler = abs(math.degrees(math.acos(v)) - arp_lat)
        if bester is None or fehler < bester:
            bester = fehler
    if bester is None or bester > GEGENPROBE_TOLERANZ:
        logger.info("AIP: cos-Probe nicht bestanden")
        return None

    lat_paare = beschriftung_lesen(im, rahmen, ty, "y")
    lon_paare = beschriftung_lesen(im, rahmen, tx, "x")
    if len(lat_paare) < _MIND_STUETZSTELLEN or len(lon_paare) < _MIND_STUETZSTELLEN:
        logger.info("AIP: zu wenige lesbare Stuetzstellen (%d/%d)",
                    len(lat_paare), len(lon_paare))
        return None

    lat_g = ausgleichsgerade(lat_paare)
    lon_g = ausgleichsgerade(lon_paare)
    if lat_g is None or lon_g is None:
        return None
    m_lat, b_lat, res_lat = lat_g
    m_lon, b_lon, res_lon = lon_g

    if abs(m_lat) < 1e-12 or abs(m_lon) < 1e-12:
        return None

    # (2) Passt die aus den ZAHLEN gewonnene Skala zum gemessenen Rasterabstand? Ein Tick
    # ist eine ganze Bogenminute (oder ein Vielfaches davon); 1/(60*|m|) ist also der
    # Pixelabstand, den die gelesenen Werte behaupten. Weicht er vom gemessenen ab, ist
    # eine der beiden Groessen falsch. Ohne diese Pruefung waeren es nur drei Stufen
    # statt der vier, die die Spec zusagt (Gutachten 23.08.2026, Befund B9).
    for m, d in ((m_lat, dy), (m_lon, dx)):
        behauptet = 1.0 / (60.0 * abs(m))
        vielfaches = round(d / behauptet) if behauptet > 0 else 0
        if vielfaches < 1 or abs(d - vielfaches * behauptet) > _MAX_RESIDUUM_PX:
            logger.info("AIP: gelesene Skala passt nicht zum Rasterabstand")
            return None

    # (3) Residuen, in Pixel umgerechnet -- ein einzelner Ziffernfehler faellt hier auf.
    if res_lat / abs(m_lat) > _MAX_RESIDUUM_PX or res_lon / abs(m_lon) > _MAX_RESIDUUM_PX:
        logger.info("AIP: Stuetzstellen nicht auf einer Geraden -- Zahl falsch gelesen?")
        return None

    # Genordet heisst: nach unten nimmt die Breite AB, nach rechts die Laenge ZU. Trifft das
    # nicht zu, ist etwas grundlegend falsch gelesen. Das still zu normalisieren wuerde das
    # Blatt gespiegelt auflegen, ohne dass ein Test anschlaegt (Befund B10).
    if m_lat > 0 or m_lon < 0:
        logger.info("AIP: Blatt scheint nicht genordet -- verworfen")
        return None

    breite_px, hoehe_px = im.size
    nord, sued = m_lat * 0 + b_lat, m_lat * hoehe_px + b_lat
    west, ost = m_lon * 0 + b_lon, m_lon * breite_px + b_lon
    feld_nord, feld_sued = m_lat * rahmen.oben + b_lat, m_lat * rahmen.unten + b_lat
    feld_west, feld_ost = m_lon * rahmen.links + b_lon, m_lon * rahmen.rechts + b_lon
    # (4) Lagetest gegen das KARTENFELD, nicht gegen das Blatt.
    if not (feld_sued < arp_lat < feld_nord and feld_west < arp_lon < feld_ost):
        logger.info("AIP: Flugplatz liegt nicht im Kartenfeld")
        return None

    return Passung(
        nord=nord, sued=sued, west=west, ost=ost,
        feld_nord=feld_nord, feld_sued=feld_sued, feld_west=feld_west, feld_ost=feld_ost,
        rahmen_px=f"{rahmen.links:.1f},{rahmen.oben:.1f},{rahmen.rechts:.1f},{rahmen.unten:.1f}",
        tick_px_lat=dy, tick_px_lon=dx,
    )
```

- [ ] **Schritt 4: Tests laufen lassen und committen**

```bash
git add app/aip_charts.py tests/test_aip_charts.py
git commit -m "AIP-Karten: Passung ueber Ausgleichsgerade mit vierstufiger Pruefkette"
```

---

## Task 6: Erstbefüllung, Auffrischung, Betrieb

**Dateien:**
- Anlegen: `scripts/aip_bestand.py`
- Ändern: `app/aip_charts.py`, `app/poller.py`
- Test: `tests/test_aip_charts.py` (anfügen)

**Schnittstellen:**
- Liefert: `geometrie_gleich(alt: dict, neu: Passung) -> bool`,
  `blatt_schreiben(pfad, roh) -> None`, Job `aip_auffrischen`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_aip_charts.py -- anfuegen

def _passung(**abw):
    grund = dict(nord=1.0, sued=0.0, west=0.0, ost=1.0, feld_nord=0.9, feld_sued=0.1,
                 feld_west=0.1, feld_ost=0.9, rahmen_px="132.0,180.0,817.0,865.0",
                 tick_px_lat=219.0, tick_px_lon=128.4)
    return aip_charts.Passung(**{**grund, **abw})


def test_gleiche_geometrie_erhaelt_die_handpassung():
    alt = {"rahmen_px": "132.0,180.0,817.0,865.0", "tick_px_lat": 219.0, "tick_px_lon": 128.4}
    assert aip_charts.geometrie_gleich(alt, _passung()) is True


def test_verschobener_rahmen_erzwingt_neue_passung():
    alt = {"rahmen_px": "132.0,180.0,817.0,900.0", "tick_px_lat": 219.0, "tick_px_lon": 128.4}
    assert aip_charts.geometrie_gleich(alt, _passung()) is False


def test_rasterabstand_wird_schaerfer_geprueft_als_der_rahmen():
    """2 px auf 219 sind 0,9 Prozent, ueber dphi/dv also rund 0,5 Grad Breite -- mehr als die
    Toleranz der cos-Probe. Fuer Rasterabstaende gelten deshalb 0,5 px."""
    alt = {"rahmen_px": "132.0,180.0,817.0,865.0", "tick_px_lat": 220.5, "tick_px_lon": 128.4}
    assert aip_charts.geometrie_gleich(alt, _passung()) is False


def test_blatt_wird_atomar_geschrieben(tmp_path):
    """Sonst liefert FileResponse mitten im Austausch ein abgeschnittenes PNG aus."""
    ziel = tmp_path / "aip" / "EDXR.png"
    aip_charts.blatt_schreiben(ziel, PNG_1X1)
    assert ziel.read_bytes() == PNG_1X1
    assert not list(ziel.parent.glob("*.tmp"))     # kein Rest
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag prüfen**

Aufruf: `pytest tests/test_aip_charts.py -k "geometrie or raster_ab or atomar" -v`

- [ ] **Schritt 3: Umsetzen**

```python
# app/aip_charts.py -- anfuegen
import os
from pathlib import Path

_TOLERANZ_RAHMEN_PX = 2.0
# Schaerfer als beim Rahmen: 2 px auf 219 sind 0,9 Prozent und entsprechen ueber
# dphi/dv = 1/sin(phi) rund 0,5 Grad Breite -- mehr als die cos-Probe zulaesst.
_TOLERANZ_RASTER_PX = 0.5


def geometrie_gleich(alt: dict, neu: "Passung") -> bool:
    """Traegt das neue Blatt denselben Ausschnitt wie das alte?"""
    try:
        a = [float(v) for v in str(alt["rahmen_px"]).split(",")]
        b = [float(v) for v in neu.rahmen_px.split(",")]
        lat_alt, lon_alt = float(alt["tick_px_lat"]), float(alt["tick_px_lon"])
    except (KeyError, TypeError, ValueError):
        return False
    if len(a) != 4 or len(b) != 4:
        return False
    if any(abs(x - y) > _TOLERANZ_RAHMEN_PX for x, y in zip(a, b)):
        return False
    return (abs(lat_alt - neu.tick_px_lat) <= _TOLERANZ_RASTER_PX
            and abs(lon_alt - neu.tick_px_lon) <= _TOLERANZ_RASTER_PX)


def blatt_schreiben(pfad, roh: bytes) -> None:
    """Blatt atomar ablegen: erst daneben, dann umbenennen."""
    ziel = Path(pfad)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_suffix(ziel.suffix + ".tmp")
    tmp.write_bytes(roh)
    os.replace(tmp, ziel)
```

`scripts/aip_bestand.py` geht alle Einträge aus `airport_links` durch: Blatt holen (Task 2),
bei fehlendem Rahmen die Kapitelseiten durchprobieren, Passung rechnen (Task 5),
Platzkoordinate aus `airportsdata` und ersatzweise aus der OpenAIP-Airports-API
(`settings.OPENAIP_API_KEY`, Header `x-openaip-api-key` — derselbe Schlüssel wie in
`app/vrp.py`), Ergebnis über `upsert_aip_chart` ablegen, Blatt mit `blatt_schreiben` nach
`Path(get_settings().DB_PATH).parent / "aip" / f"{icao}.png"`. Zwischen zwei Abrufen 0,4 Sekunden
Pause.

**Drei Regeln, die der Batchlauf und der Job gemeinsam einhalten:**

1. **Ein fehlgeschlagener Abruf ändert nichts.** Netzfehler oder leere Antwort lassen Zeile und
   Blatt unangetastet und setzen eine gute Karte insbesondere nicht auf `ungepasst`.
2. **Verwaiste Karten werden abgeräumt:** Was nicht mehr in `airport_links` steht, verliert
   Zeile (`delete_aip_chart`) und Blatt.
3. **Am Ende steht die Quote im Log**, dazu die Liste der ungepassten Karten.

Im `poller.py` ein wöchentlicher Job — **beides gehört dazu**: die synchrone Arbeitsfunktion
`_aip_auffrischen_sync(db_path) -> int` (sie tut, was `scripts/aip_bestand.py` tut, nur ohne
Ausgabe) **und** die Registrierung beim Scheduler, nach dem Muster der übrigen Jobs:
`self._scheduler.add_job(self.aip_auffrischen, "interval", weeks=1, id="aip_auffrischen")`.

```python
async def aip_auffrischen(self) -> None:
    """Blaetter neu holen; Arbeit faellt nur an, wenn sich ein bild_hash geaendert hat.

    Ueber to_thread, weil die Bildanalyse reines Python ueber jedes Pixel ist: rund 0,5 s je
    Blatt allein fuer die Rahmensuche, bei 446 Blaettern ueber vier Minuten, dazu die Abrufe.
    Beim AIRAC-Wechsel aendern sich alle Hashes -- auf dem Event-Loop stuenden derweil SSE,
    der 15-Sekunden-Poller und jede Anfrage. Dasselbe Muster wie beim flight_cache-Rebuild.
    """
    n = await asyncio.to_thread(self._aip_auffrischen_sync, self.db_path)
    logger.info("AIP-Karten aufgefrischt: %d geaendert", n)
```

- [ ] **Schritt 4: Erstbefüllung laufen lassen**

Aufruf: `python scripts/aip_bestand.py`
Erwartet: Quote nahe **91,9 %** (410 von 446 in der Messung vom 23.08.2026, siehe
`tests/fixtures/aip/messwerte.json`), dazu die Liste der ungepassten Karten.

**Weicht die Quote deutlich ab, erst melden, nicht weiterbauen.** Die 91,9 % sind die
Geometrie-Quote; mit dem Zahlenlesen kann sie niedriger ausfallen — das ist der erwartete
Fall und genau die Zahl, die vor der Handarbeit auf den Tisch gehört.

- [ ] **Schritt 5: Committen**

```bash
git add app/aip_charts.py app/poller.py scripts/aip_bestand.py tests/test_aip_charts.py
git commit -m "AIP-Karten: Erstbefuellung, woechentliche Auffrischung, atomare Ablage"
```

---

## Task 7: Endpoints

**Dateien:**
- Ändern: `app/main.py`
- Test: `tests/test_aip_api.py` (neu)

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_aip_api.py
"""Endpoints der AIP-Kartenebene.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.database import init_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Eigene Datenbank je Test.

    OHNE diese Umlenkung zeigt ``get_settings().DB_PATH`` auf
    ``/opt/friesenspy/data/friesenspy.db`` -- in der CI fehlt sie, **auf dem VPS ist es die
    laufende Produktionsdatenbank** (Gutachten 23.08.2026, Befund B2). Muster wie in
    ``tests/test_panel_diag.py``.
    """
    db = str(tmp_path / "t.db")
    init_db(db)
    (tmp_path / "aip").mkdir()
    s = Settings(SECRET_KEY="test", DB_PATH=db)
    monkeypatch.setattr(main, "get_settings", lambda: s)
    return TestClient(main.app)


def test_liste_liefert_blatt_und_feldgrenzen(client):
    r = client.get("/api/aip-charts")
    assert r.status_code == 200
    for k in r.json()["charts"]:
        assert set(k) >= {"icao", "nord", "sued", "west", "ost",
                          "feld_nord", "feld_sued", "feld_west", "feld_ost", "bild", "airac"}
        assert "rahmen_px" not in k        # Innereien gehoeren nicht in den Browser


def test_unbekannte_karte_ist_404(client):
    assert client.get("/aip-chart/XXXX.png").status_code == 404


def test_ungueltiger_code_ist_404_und_kein_pfaddurchgriff(client):
    assert client.get("/aip-chart/..%2F..%2Fetc%2Fpasswd.png").status_code == 404


def test_blatt_wird_nicht_oeffentlich_zwischengespeichert(client):
    """Die Datei ist lizenzgeschuetzt und liegt hinter dem Login -- 'public' erlaubte jedem
    Zwischen-Cache das Ausliefern ohne Anmeldung."""
    r = client.get("/aip-chart/XXXX.png")
    assert "public" not in r.headers.get("cache-control", "")
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag prüfen** — 404 auf `/api/aip-charts`

- [ ] **Schritt 3: Endpoints ergänzen**

Zuerst `import re` am Kopf von `app/main.py` sicherstellen — es gibt dort bisher nur ein
lokales `import re as _re` in einer Funktion.

```python
@app.get("/api/aip-charts")
async def aip_charts_liste():
    """Metadaten der gepassten Sichtflugkarten. Einmal beim Einschalten der Ebene geladen --
    dasselbe Muster wie bei Meldepunkten und Platzrunden."""
    einst = get_settings()          # app.main hat KEIN Modul-`settings`; jede Funktion
    conn = get_connection(einst.DB_PATH)   # holt sich die Einstellungen selbst (main.py:215 ff.)
    try:
        karten = get_aip_charts(conn)
    finally:
        conn.close()
    return {"charts": [
        {"icao": k["icao"],
         "nord": k["nord"], "sued": k["sued"], "west": k["west"], "ost": k["ost"],
         "feld_nord": k["feld_nord"], "feld_sued": k["feld_sued"],
         "feld_west": k["feld_west"], "feld_ost": k["feld_ost"],
         "airac": k["airac"],
         "bild": f"/aip-chart/{k['icao']}.png?h={k['bild_hash'][:12]}"}
        for k in karten
    ]}


@app.get("/aip-chart/{icao}.png", include_in_schema=False)
async def aip_chart_bild(icao: str):
    """Das ungeschnittene Blatt.

    Cache-Control ist bewusst `private`: Der Endpunkt liegt hinter dem forum_login_gate, und
    genau diese Beschraenkung traegt das rechtliche Argument (Spec, Abschnitt 9). `public`
    erlaubte jedem Zwischen-Cache -- nginx, CDN, Firmenproxy -- das Ausliefern ohne Anmeldung.
    """
    code = (icao or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4}", code):
        raise HTTPException(status_code=404, detail="unbekannt")
    pfad = Path(get_settings().DB_PATH).parent / "aip" / f"{code}.png"
    if not pfad.is_file():
        raise HTTPException(status_code=404, detail="unbekannt")
    return FileResponse(pfad, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=2592000, immutable"})
```

- [ ] **Schritt 4: Tests laufen lassen und committen**

```bash
git add app/main.py tests/test_aip_api.py
git commit -m "AIP-Karten: Endpoints fuer Liste und Blatt"
```

---

## Task 8: Karten-Ebene „Sichtflugkarte"

**Dateien:**
- Ändern: `app/static/index.html`
- Test: `tests/test_aip_ui.py` (neu)

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_aip_ui.py
"""Karten-Ebene "Sichtflugkarte" im Quelltext.

Die Tests binden an Deklarationen, nicht an Kommentare -- eine freie Zeichenkettensuche
faende sonst den Kommentar statt der Sache.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md
"""
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(
    encoding="utf-8"
)


def test_ebene_haengt_in_der_ebenen_auswahl():
    assert "liveOverlays['Sichtflugkarte']" in INDEX


def test_vorliebe_wird_vor_der_control_gesetzt():
    """Sonst sieht die Checkbox den Zustand nie (derselbe Fallstrick wie bei OpenAIP)."""
    assert INDEX.index("_addPreferredAipKarteLayer(liveMap") < INDEX.index("liveOverlays,")


def test_daten_kommen_vom_metadaten_endpunkt():
    assert "'/api/aip-charts'" in INDEX


def test_merker_laeuft_ueber_den_server_nicht_localstorage():
    """Im Kniebrett haelt kein Browser-Speicher ueber einen Sim-Neustart."""
    assert "_prefSchreib(_AIP_KARTE_PREF_KEY" in INDEX
    assert "localStorage.getItem('friesenspy_aipkarte')" not in INDEX


def test_geschaltet_wird_nach_dem_kartenfeld():
    """Nach den Blattgrenzen zu schalten hiesse: Overlay an, waehrend das Flugzeug unter der
    Kopfzeile steht -- das Blatt ist rund 1,8-mal so hoch wie das Kartenfeld.

    Geprueft wird die Funktion, die die Entscheidung trifft, nicht das blosse Vorkommen der
    Zeichenkette: 'feld_sued' im Quelltext bestuende auch, wenn nur geloggt wird
    (Gutachten 23.08.2026, Befund B13).
    """
    start = INDEX.index("function _aipKarteImFeld(")
    block = INDEX[start:start + 700]
    assert "feld_sued" in block and "feld_nord" in block
    assert "feld_west" in block and "feld_ost" in block
    assert "_AIP_KARTE_HYSTERESE" in block


def test_platziert_wird_nach_den_blattgrenzen():
    """Und das Overlay selbst nimmt die BLATTgrenzen -- gezeigt wird ja das ganze Blatt."""
    start = INDEX.index("L.imageOverlay(")
    block = INDEX[start:start + 200]
    assert "k.sued" in block and "k.nord" in block
    assert "feld_" not in block


def test_hysterese_ist_vorhanden():
    assert "const _AIP_KARTE_HYSTERESE" in INDEX


def test_attribution_traegt_das_airac_datum():
    assert "_aipKarteAttribution" in INDEX
```

- [ ] **Schritt 2: Test laufen lassen** — alle acht schlagen fehl

- [ ] **Schritt 3: Ebene umsetzen**

```javascript
// ==========================================================================
//  SICHTFLUGKARTE ALS OVERLAY
// ==========================================================================
// Das ungeschnittene DFS-Blatt liegt georeferenziert ueber der Karte. Zwei Rechtecke, die
// nicht zu verwechseln sind: PLATZIERT wird nach den Blattgrenzen (nord/sued/west/ost) --
// gezeigt wird ja das ganze Blatt. GESCHALTET wird nach dem Kartenfeld (feld_*), denn das
// Blatt ist rund 1,8-mal so hoch; nach ihm zu schalten hiesse, das Overlay erscheint,
// waehrend das Flugzeug noch unter der Kopfzeile steht (Spec, Abschnitt 6).
const _AIP_KARTE_API = '/api/aip-charts';
const _AIP_KARTE_PREF_KEY = 'friesenspy_aipkarte';
// Rand, innerhalb dessen ein sichtbares Overlay sichtbar BLEIBT. Ohne Hysterese schaltet es
// am Rand bei jedem Positionsupdate um.
const _AIP_KARTE_HYSTERESE = 0.02;   // Grad, rund 2 km

const _aipKartenGruppe = L.layerGroup();
let _aipKarten = null;        // Metadaten, einmal geladen
let _aipKarteAktiv = null;    // ICAO des eingeblendeten Blatts
let _aipKarteFest = null;     // vom Nutzer festgenagelt

function _saveAipKartePref(an) { _prefSchreib(_AIP_KARTE_PREF_KEY, an ? '1' : '0'); }
function _loadAipKartePref()   { return _prefLies(_AIP_KARTE_PREF_KEY) === '1'; }

// Die Quellenangabe traegt das AIRAC-Datum des gezeigten Blatts, nicht bloss den Namen --
// eine Karte ohne Ausgabedatum ist im Flug wertlos (Spec, Abschnitt 6).
function _aipKarteAttribution(k) {
  return '&copy; DFS Deutsche Flugsicherung GmbH, AIRAC ' + k.airac;
}
```

Dazu: Metadaten beim ersten Einschalten laden, `_aipKarteNachfuehren()` dort aufrufen, wo die
Moving Map die Position auswertet, das Overlay mit
`L.imageOverlay(k.bild, [[k.sued, k.west], [k.nord, k.ost]], {opacity: …, attribution:
_aipKarteAttribution(k)})` einhängen, und `_addPreferredAipKarteLayer(liveMap)` **vor** dem
Bau von `L.control.layers(...)` aufrufen.

**Zur Deckkraft:** Der Kommentar bei `_AIP_DECKKRAFT` hält fest, dass die Deckkraft-Spur beim
Flackern im Kniebrett **falsch** war — zwei Messreihen wurden zurückgebaut, die Ursache ist
Fremd-CSS bei `.leaflet-container img.leaflet-tile`. Die Frage ist erledigt und wird nicht
wieder aufgemacht.

- [ ] **Schritt 4: Tests laufen lassen und committen**

```bash
git add app/static/index.html tests/test_aip_ui.py
git commit -m "AIP-Karten: Ebene Sichtflugkarte, geschaltet nach dem Kartenfeld"
```

---

## Task 9: Admin — Leaflet, Liste, Handpassung

**Dateien:**
- Ändern: `app/static/admin.html`, `app/main.py`
- Test: `tests/test_aip_ui.py`, `tests/test_aip_api.py` (anfügen)

**`admin.html` enthält bisher kein Leaflet** — kein Script-Tag, kein CSS, kein `L.map`.
Kartenbibliothek, Container und Basiskacheln kommen mit diesem Task dazu; das ist der
Aufwandsschwerpunkt, nicht ein Nebenschritt.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_aip_ui.py -- anfuegen
ADMIN = (Path(__file__).resolve().parents[1] / "app" / "static" / "admin.html").read_text(
    encoding="utf-8"
)


def test_admin_bindet_leaflet_ein():
    """Vorher enthielt admin.html keinerlei Leaflet."""
    assert "leaflet" in ADMIN.lower()


def test_kartenliste_ist_horizontal_scrollbar():
    """UI-Regel aus CLAUDE.md: breite Tabellen gehoeren in .table-wrap."""
    start = ADMIN.index('id="aip-charts"')
    assert "table-wrap" in ADMIN[max(0, start - 400):start + 400]


def test_vorschau_zeigt_das_blatt_ueber_der_karte():
    assert "L.imageOverlay(" in ADMIN
```

```python
# tests/test_aip_api.py -- anfuegen
def test_handpassung_braucht_anmeldung(client):
    r = client.post("/api/admin/aip-charts/EDWJ", json={
        "links_px": 132, "oben_px": 180, "rechts_px": 817, "unten_px": 865,
        # feld_* -- die geklickten RAHMENecken, nicht die Blattgrenzen. Dieselben vier Namen
        # fuer beides waren die Verwechslung hinter dem 45-Prozent-Fehler (Befund B11).
        "feld_nord": 54.0, "feld_sued": 53.9, "feld_west": 7.0, "feld_ost": 7.1,
    })
    assert r.status_code in (401, 403)
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag prüfen**

- [ ] **Schritt 3: Umsetzen**

Admin-Abschnitt mit Liste (ICAO, Status, Quelle, AIRAC) in einem `.table-wrap`. Beim Passen
wird das Blatt gezeigt, man klickt zwei gegenüberliegende **Rahmenecken** und trägt die
zugehörigen Gradwerte ein.

**Der Endpoint rechnet daraus dasselbe wie die Automatik.** Er nimmt die vier Pixelwerte und
die vier Gradwerte der Rahmenecken und **verlängert die lineare Abbildung auf die
Blattkanten** — erst das ergibt `nord/sued/west/ost`; die Feldgrenzen sind unmittelbar die
eingetragenen Werte. Die geklickten Rahmenwerte direkt als Blattgrenzen abzulegen wäre falsch:
Beim Standardblatt würde ein 875×1240-Bild in einen 685×685-Rahmen gequetscht, rund 45 %
Maßstabsfehler senkrecht — ausgerechnet bei den Karten, denen man am meisten vertraut.

Der Body trägt die Rahmenecken bewusst als `feld_nord`/`feld_sued`/`feld_west`/`feld_ost` —
**nicht** als `nord`/`sued`/`west`/`ost`. Dieselben vier Namen für Rahmenecken und
Blattgrenzen zu verwenden war genau die Verwechslung hinter dem 45-%-Maßstabsfehler; sie darf
nicht im Drahtformat weiterleben.

Der Endpoint prüft `feld_sued < feld_nord`, `feld_west < feld_ost` und dass die Pixelwerte im
Blatt liegen; sonst 400. Er **liest die Bestandszeile und mischt** — `upsert_aip_chart` verlangt alle Pflichtfelder.
Existiert keine Zeile (Blatt nie geladen), antwortet er mit 409 statt 500.

**Vorschau vor dem Speichern:** das Blatt als `L.imageOverlay` über einer echten Karte, mit
Deckkraftregler.

- [ ] **Schritt 4: Tests laufen lassen und committen**

```bash
git add app/static/admin.html app/main.py tests/test_aip_api.py tests/test_aip_ui.py
git commit -m "AIP-Karten: Handpassung im Admin mit Extrapolation und Vorschau"
```

---

## Task 10: Changelog

- [ ] **Schritt 1: Eintrag anlegen**

Erster Eintrag in `app/CHANGELOG.json`, Versionsnummer nach dem Muster des Projekts (MINOR).
**`"highlight": false`** — ohne Ausnahme; die rote Marke vergibt allein der Nutzer.

- [ ] **Schritt 2: Vollständiger Testlauf**

Aufruf: `pytest tests/ -v` → alle bestanden

- [ ] **Schritt 3: Committen**

```bash
git add app/CHANGELOG.json
git commit -m "Changelog: Sichtflugkarten als Karten-Overlay"
```

---

## Selbstdurchsicht

**Abdeckung der Spec:** Abschnitt 1–2 (Befund) → Task 2, 3. Abschnitt 3.1 (Prüfkette, vier
Stufen) → Task 5, jede Stufe mit eigenem Test. Abschnitt 3.2 (Freiheitsgrade) → Task 3
(`raster` ohne Unterteilung, Belegungsprüfung) und Task 5 (Vielfache begrenzt, Wächter auf
deutsche Breiten). Abschnitt 3.3 (Störstriche, Schwellen, Anteil) → Task 3. Abschnitt 3.4
(Ziffern) → Task 4. Abschnitt 4 (Modul, Tabelle) → Task 1, 5. Abschnitt 4.2 (AIRAC) und 4.3
(Betrieb) → Task 6. Abschnitt 5 (API) → Task 7. Abschnitt 6 (Frontend) → Task 8. Abschnitt 7
(Admin, Extrapolation) → Task 9. Abschnitt 9 (Recht) → Task 7 (`private`) und Task 8
(Attribution). Abschnitt 10 (Tests) → über alle Tasks.

**Was gegenüber Fassung 1 dieses Plans repariert wurde** (Gutachten vom 23.08.2026): die
Prüfkette statt einer blinden Probe; die Längengrad-Achse, die schlicht fehlte; `raster()`
mit Belegungsprüfung; die echten API-Namen; die Extrapolation im Handpfad; Feldgrenzen in
Tabelle und Frontend; `asyncio.to_thread`; `Cache-Control: private`; `import re`;
`get_connection` mit `try/finally`; Leaflet im Admin; atomares Schreiben; verwaiste Karten.

**Bekannte Lücke:** Die Ziffern-Schablonen für die DFS-Schrift stehen nicht ausgeschrieben —
nur die „1". Sie lassen sich nicht aus dem Kopf schreiben, nur aus den Blättern gewinnen;
deshalb ist das Gewinnen als Schritt 1 von Task 4 mit lauffähigem Skript ausgeführt. Die
Prüfschrift der Tests ist davon unabhängig und vollständig.

**Offen bis zur Umsetzung:** die echte Automatik-Quote nach dem Erstlauf (Task 6, Schritt 4).

## Kleinere Punkte aus dem zweiten Gutachten

Bewusst nicht einzeln ausgeführt, aber bei der Umsetzung abzuarbeiten:

- **`_TOLERANZ_RASTER_PX = 0,5` liegt an der Messgrenze.** Tickpositionen sind ganzzahlig; ein
  mit 128,4 gebautes Gitter misst sich als 128,25. Ein falsches „abweichend" verwirft nach
  Spec 4.2 eine Handpassung — beim ersten AIRAC-Wechsel prüfen, ob der Wert trägt.
- **Die Admin-Endpoints brauchen `conn.commit()`** — die Repo-Konvention überlässt das dem
  Aufrufer (auch `upsert_airport_link` committet nicht selbst).
- **Die drei Betriebsregeln aus Task 6** (fehlgeschlagener Abruf ändert nichts, verwaiste
  Karten abräumen, Quote ins Log) sind Prosa und brauchen je einen Test; Spec 10 sagt sie zu.
- **Der EDBY-Kommentar** steht an `_SCHWELLEN` (Rahmen), gehört aber an `_TICK_SCHWELLEN`.
- **`test_ticks_auch_bei_hindernissymbolen_im_randband` ist zu schwach:** Die Störstriche des
  Generators decken 18 von 20 Zeilen und werden schon von Schwelle 0,95 aussortiert, das
  Raster sieht sie nie. Der Störstrich gehört kürzer gezeichnet, damit der Test etwas prüft.
- **`messwerte.json` ist am 23.08.2026 nachgebessert worden** (fünf Karten standen auf
  „gepasst" mit Fehlern über der Toleranz, weil Messwerte der Hauptseite mit dem Status der
  Kapitelseite gemischt waren). Wer die Referenzquote heranzieht, liest zuerst den Kopf der
  Datei.
