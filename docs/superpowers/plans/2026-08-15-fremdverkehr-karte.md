# Fremdverkehr auf der Karte — Implementierungsplan

> **Für agentische Bearbeitung:** ERFORDERLICHE SUB-SKILL: `superpowers:subagent-driven-development`
> (empfohlen) oder `superpowers:executing-plans`. Schritte sind als Checkboxen (`- [ ]`) geführt.

**Ziel:** Fremder VATSIM-Verkehr erscheint gleitend auf der Live-Karte — als abschaltbare
Ebene neben OpenAIP, mit Muster, Höhe und Geschwindigkeit am Symbol.

**Architektur:** Der Poller behält den ohnehin geholten VATSIM-Feed als Momentaufnahme im
Speicher; ein neuer Endpunkt `/api/traffic` schneidet daraus den Umkreis der Kartenmitte
heraus. Das Frontend hält die Rohwerte getrennt von den gezeichneten Positionen und bewegt
die Marker ausschließlich im vorhandenen Sekundentakt.

**Tech-Stack:** Python 3.11 / FastAPI / httpx, Leaflet + leaflet-rotate im Frontend,
TypeScript im MSFS-Kniebrett-Paket.

**Spec:** `docs/superpowers/specs/2026-08-15-fremdverkehr-karte-design.md`

## Globale Vorgaben

- **Sprachgrenze im Kniebrett: ES2017.** Coherent GT wirft bei `?.`, `??`, Spread und
  `flatMap` einen Parse-Fehler, der das **gesamte** betroffene `<script>` lahmlegt — das
  steht so als Kommentar in `index.html` (Zeilen 20-24 und 3486). Alles bis ES2017 ist in
  Ordnung: `const`/`let`, Pfeilfunktionen, Template-Literale, `padStart`, `Object.entries`
  — Letzteres benutzt `updateMap` selbst und läuft nachweislich im Panel. **Nicht** die
  Verbotsliste über ES2017 hinaus verschärfen; `padStart` steht 15-mal im Code.
- **Kein SVG-`<use>` ohne `xlink:href`-Zwilling.** In Chrome 49 kennt `<use>` nur
  `xlink:href`; ein Symbol mit ausschließlich `href` ist im Kniebrett unsichtbar.
- **`highlight` in `app/CHANGELOG.json` bleibt `false`.** Das setzt ausschließlich der Nutzer.
- **Kein PR-Umweg**, direkt auf `main` committen. **Vor `git push origin main` fragen.**
- **Keine Shell-Heredocs zum Schreiben von Dateien** — Write/Edit benutzen.
- Doku wird mit dem Code geändert, nicht danach (Task 5).
- Alle Bezeichner, Kommentare und Texte auf Deutsch, wie im übrigen Projekt.

## Reihenfolge und Parallelität

Zeitsparend, ohne an der Qualität zu drehen:

```
Task 1 (Server) ─► Task 2 (Label) ─► Task 3 (Ebene) ─► Task 4 (Sonde) ─► Task 6 (EDWG) ─► Task 5 (Release)
```

**Nichts läuft parallel.** Der erste Entwurf dieses Plans behauptete, Task 1 und Task 4
seien unabhängig — sie sind es nicht: Task 4 ändert die Empfangsseite in
`app/static/index.html` (Schritt 4) und committet sie. Damit fassen **Tasks 2, 3, 4 und 6**
dieselbe 9200-Zeilen-Datei an, und alle vier hängen zusätzlich Tests an
`tests/test_vr_panel.py` an. Parallele Bearbeitung erzeugt dort genau die Konflikte, die
das Aufteilen sparen sollte.

Einzig Task 1 berührt keine der beiden Dateien und könnte vorgezogen oder nebenher laufen;
Task 3 braucht seinen Endpunkt aber ohnehin zum Nachmessen im Browser, deshalb steht er
vorn. Die Zeitersparnis liegt hier nicht in der Parallelität, sondern darin, dass jede Task
mit fertigem Code und fertigen Tests beschrieben ist.

## Dateien

| Datei | Zuständigkeit | Task |
|---|---|---|
| `app/vatsim.py` | neue reine Funktion `snapshot_other_traffic` | 1 |
| `app/poller.py` | Momentaufnahme im Speicher halten | 1 |
| `app/main.py` | Endpunkt `GET /api/traffic` | 1 |
| `tests/test_traffic_api.py` | neu — Momentaufnahme, Filter, Deckel, Grenzfälle | 1 |
| `app/static/index.html` | Label-Funktion + Label an den Friesen | 2 |
| `app/static/index.html` | Verkehrs-Ebene, Abruf, Fortrechnung, Marker | 3 |
| `app/static/index.html` | Live-Karte öffnet über EDWG | 6 |
| `tests/test_vr_panel.py` | statische Prüfungen ergänzen | 2, 3, 4 |
| `msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx` | Messsonde | 4 |
| `app/static/index.html` | Empfangsseite der Sonde | 4 |
| `msfs-panel/PackageSources/FriesenSpy/manifest.json` | Paketversion 1.3.0 | 4 |
| `README.md`, `docs/api.md`, `docs/architecture.md`, `docs/efb-panel-debugging.md` | Doku | 5 |
| `app/CHANGELOG.json` | Release-Eintrag | 5 |

---

## Task 1: Server — Momentaufnahme und `/api/traffic`

**Dateien:**
- Ändern: `app/vatsim.py` (ans Dateiende), `app/poller.py`, `app/main.py`
- Test: `tests/test_traffic_api.py` (neu)

**Schnittstellen:**
- Liefert: `snapshot_other_traffic(callsign_prefix: str, vatsim_data: dict) -> list[dict]`;
  `VatsimPoller._traffic_snapshot: list[dict]`, `._traffic_snapshot_ts: float`;
  `GET /api/traffic?lat&lon&r` → `{"age": float|None, "traffic": [...]}`
- Nutzt: `app.geo.haversine`, `settings.CALLSIGN_PREFIX`

- [ ] **Schritt 1: Fehlschlagenden Test für die reine Filterfunktion schreiben**

Neue Datei `tests/test_traffic_api.py`:

```python
"""Tests für den Fremdverkehr auf der Karte (/api/traffic).

Der Fremdverkehr wird bewusst NICHT in der Datenbank gehalten: Er ist reine Anzeige,
niemand wertet ihn aus, und eine Historie über ~1000 Flugzeuge im 15-Sekunden-Takt wäre
in Tagen größer als alles andere in dieser Datenbank zusammen.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.vatsim import snapshot_other_traffic


def _pilot(callsign, lat, lon, **kw):
    p = {
        "cid": kw.get("cid", 1),
        "callsign": callsign,
        "latitude": lat,
        "longitude": lon,
        "altitude": kw.get("altitude", 3000),
        "groundspeed": kw.get("groundspeed", 120),
        "heading": kw.get("heading", 90),
    }
    if "aircraft_short" in kw:
        p["flight_plan"] = {
            "aircraft_short": kw["aircraft_short"],
            "departure": kw.get("departure", "EDDH"),
            "arrival": kw.get("arrival", "EDDF"),
        }
    return p


def test_friesen_fallen_aus_dem_fremdverkehr_heraus():
    daten = {"pilots": [_pilot("FRS001", 53.5, 8.0), _pilot("DLH4AB", 53.6, 8.1)]}
    roh = snapshot_other_traffic("FRS", daten)
    assert [e["cs"] for e in roh] == ["DLH4AB"]


def test_eintraege_ohne_koordinate_fallen_heraus():
    daten = {"pilots": [
        _pilot("AAA1", None, 8.0),
        _pilot("BBB2", 53.5, None),
        _pilot("CCC3", 0, 0),        # 0/0 ist der Nullmeridian-Platzhalter, kein Flugzeug
        _pilot("DDD4", 53.5, 8.0),
    ]}
    assert [e["cs"] for e in snapshot_other_traffic("FRS", daten)] == ["DDD4"]


def test_muster_ohne_flugplan_bleibt_leer():
    daten = {"pilots": [_pilot("AAA1", 53.5, 8.0)]}
    assert snapshot_other_traffic("FRS", daten)[0]["ac"] == ""


def test_muster_kommt_aus_dem_flugplan():
    daten = {"pilots": [_pilot("AAA1", 53.5, 8.0, aircraft_short="C172")]}
    e = snapshot_other_traffic("FRS", daten)[0]
    assert e["ac"] == "C172" and e["dep"] == "EDDH" and e["arr"] == "EDDF"


def test_kaputte_eingaben_werfen_nicht():
    assert snapshot_other_traffic("FRS", {}) == []
    assert snapshot_other_traffic("FRS", {"pilots": None}) == []
    assert snapshot_other_traffic("FRS", {"pilots": ["kein dict"]}) == []
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

```
python -m pytest tests/test_traffic_api.py -q
```
Erwartet: `ImportError: cannot import name 'snapshot_other_traffic'`

- [ ] **Schritt 3: `snapshot_other_traffic` in `app/vatsim.py` ergänzen**

Ans Dateiende:

```python
def snapshot_other_traffic(callsign_prefix: str, vatsim_data: dict) -> list[dict]:
    """Alle NICHT-Friesen als schlanke Karten-Einträge für /api/traffic.

    Bewusst kurze Feldnamen: Dieselbe Antwort geht über die Netzwerkverbindung des
    Simulators ins Kniebrett, und bei 60 Flugzeugen sparen die kurzen Namen rund ein
    Drittel der Nutzlast.

    Ausgeschlossen wird allein über das Callsign-Präfix -- ein per Admin-Checkbox auf
    "inaktiv" gesetzter Pilot fällt damit aus BEIDEN Listen heraus (er ist kein Friese
    mehr und wird auch nicht als Fremdverkehr nachgereicht). Das ist die Absicht der
    Checkbox.

    Args:
        callsign_prefix: Präfix der eigenen Leute, z. B. 'FRS'.
        vatsim_data: Rohantwort der VATSIM-API.

    Returns:
        Liste von Dicts mit cs/lat/lon/alt/gs/hdg/ac/dep/arr. Leer bei kaputter Eingabe.
    """
    pilots = vatsim_data.get("pilots") if isinstance(vatsim_data, dict) else None
    if not isinstance(pilots, list):
        return []

    prefix = (callsign_prefix or "").upper()
    out: list[dict] = []
    for p in pilots:
        if not isinstance(p, dict):
            continue
        cs = str(p.get("callsign") or "")
        if not cs or (prefix and cs.upper().startswith(prefix)):
            continue
        lat, lon = p.get("latitude"), p.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        # 0/0 ist im Feed der Platzhalter für "noch keine Position" -- ein echtes
        # Flugzeug im Golf von Guinea wäre der Preis dafür, und den zahlen wir gern.
        if lat == 0.0 and lon == 0.0:
            continue
        fp = p.get("flight_plan")
        fp = fp if isinstance(fp, dict) else {}

        def _zahl(wert) -> int:
            try:
                return int(float(wert))
            except (TypeError, ValueError):
                return 0

        out.append({
            # cid nur, um den Anfragenden selbst aussortieren zu koennen (s. /api/traffic).
            # Sie geht nicht an den Client -- der braucht sie nicht.
            "cid": p.get("cid"),
            "cs": cs,
            "lat": lat,
            "lon": lon,
            "alt": _zahl(p.get("altitude")),
            "gs": _zahl(p.get("groundspeed")),
            "hdg": _zahl(p.get("heading")),
            "ac": str(fp.get("aircraft_short") or ""),
            "dep": str(fp.get("departure") or ""),
            "arr": str(fp.get("arrival") or ""),
        })
    return out
```

- [ ] **Schritt 4: Test laufen lassen, grün bestätigen**

```
python -m pytest tests/test_traffic_api.py -q
```
Erwartet: 5 passed

- [ ] **Schritt 5: Commit**

```bash
git add app/vatsim.py tests/test_traffic_api.py
git commit -m "Fremdverkehr: Momentaufnahme aus dem VATSIM-Feed"
```

- [ ] **Schritt 6: Fehlschlagende Tests für den Endpunkt ergänzen**

An `tests/test_traffic_api.py` anhängen:

```python
@pytest.fixture()
def klient():
    """TestClient mit einer Poller-Attrappe, die eine Momentaufnahme bereithält.

    Kein get_settings-Patch: Der Endpunkt liest keine Einstellungen -- die Friesen sind
    schon in der Momentaufnahme aussortiert. Der vorherige Zustand von app.state wird
    wiederhergestellt, weil main.app modulweit geteilt ist und andere Testdateien direkt
    (ohne getattr) auf app.state.poller zugreifen.
    """
    # Bezugspunkt Bremen 53.05/8.79. Distanzen mit app.geo.haversine nachgerechnet:
    #   NAH1  53.63/9.99  -> 102,5 km
    #   FERN1 51.30/8.79  -> 194,6 km   (muss UNTER dem Maximum 250 km liegen, sonst
    #                                    kann der Sortier-Test gar nicht gruen werden)
    poller = SimpleNamespace(
        traffic_snapshot=[
            {"cs": "NAH1", "lat": 53.63, "lon": 9.99, "alt": 3000, "gs": 120,
             "hdg": 90, "ac": "C172", "dep": "", "arr": ""},
            {"cs": "FERN1", "lat": 51.30, "lon": 8.79, "alt": 35000, "gs": 450,
             "hdg": 180, "ac": "A320", "dep": "", "arr": ""},
        ],
        traffic_snapshot_ts=time.time(),
    )
    vorher = getattr(main.app.state, "poller", None)
    main.app.state.poller = poller
    yield SimpleNamespace(client=TestClient(main.app), poller=poller)
    main.app.state.poller = vorher


def test_radius_schneidet_das_ferne_flugzeug_weg(klient):
    """150 km liegt zwischen den beiden (102,5 und 194,6 km)."""
    r = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79, "r": 150})
    assert r.status_code == 200
    assert [e["cs"] for e in r.json()["traffic"]] == ["NAH1"]


def test_grosser_radius_nimmt_beide_und_sortiert_nach_naehe(klient):
    r = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79, "r": 250})
    assert [e["cs"] for e in r.json()["traffic"]] == ["NAH1", "FERN1"]


def test_deckel_bei_sechzig_flugzeugen(klient):
    klient.poller.traffic_snapshot = [
        {"cs": "X%03d" % i, "lat": 53.05 + i * 0.001, "lon": 8.79, "alt": 1000,
         "gs": 100, "hdg": 0, "ac": "", "dep": "", "arr": ""}
        for i in range(100)
    ]
    r = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79, "r": 250})
    daten = r.json()["traffic"]
    assert len(daten) == 60
    assert daten[0]["cs"] == "X000"      # das nächste gewinnt, nicht das erste im Feed


def test_alter_wird_mitgeliefert(klient):
    klient.poller.traffic_snapshot_ts = time.time() - 7
    r = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79})
    assert 6.0 <= r.json()["age"] <= 8.5


def test_veraltete_momentaufnahme_liefert_leer_statt_falsch(klient):
    klient.poller.traffic_snapshot_ts = time.time() - 500
    d = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79}).json()
    assert d == {"age": None, "traffic": []}


def test_ohne_poller_keine_fehlermeldung(klient):
    main.app.state.poller = None
    d = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79}).json()
    assert d == {"age": None, "traffic": []}


@pytest.mark.parametrize("params", [
    {"lat": 91, "lon": 8.79},
    {"lat": 53.05, "lon": 181},
    {"lat": 53.05, "lon": 8.79, "r": 0},
    {"lat": 53.05, "lon": 8.79, "r": 999},
    {"lon": 8.79},
])
def test_unsinnige_parameter_werden_abgewiesen(klient, params):
    assert klient.client.get("/api/traffic", params=params).status_code == 422
```

Und der Test, der als einziger die beiden Zeilen im Poller abdeckt — ohne ihn prüfen alle
anderen nur eine Attrappe:

```python
@pytest.mark.asyncio
async def test_poll_zyklus_fuellt_die_momentaufnahme(tmp_path, monkeypatch):
    """Die zwei Zeilen in _poll_once sind die einzige Stelle, an der Funktion und Poller
    zusammenkommen -- und die wahrscheinlichste für einen stillen Ausfall (falsche
    Einrichtung im grossen try, Attribut nie gesetzt, import vergessen)."""
    from app.database import init_db
    from app.poller import VatsimPoller

    db = str(tmp_path / "t.db")
    init_db(db)
    poller = VatsimPoller(db_path=db, callsign_prefix="FRS")

    async def gefaelschter_feed(_client):
        return {"pilots": [
            {"cid": 1, "callsign": "FRS001", "latitude": 53.5, "longitude": 8.0,
             "altitude": 2000, "groundspeed": 100, "heading": 0},
            {"cid": 2, "callsign": "DLH4AB", "latitude": 53.6, "longitude": 8.1,
             "altitude": 30000, "groundspeed": 440, "heading": 270},
        ]}

    monkeypatch.setattr("app.poller.fetch_vatsim_data", gefaelschter_feed)
    poller._http_client = object()          # nur die assert-Wache in _poll_once bedienen
    await poller._poll_once()

    assert [e["cs"] for e in poller.traffic_snapshot] == ["DLH4AB"]
    assert poller.traffic_snapshot_ts > 0
```

**Beim Umsetzen prüfen:** Ob `VatsimPoller` mit diesen zwei Argumenten baubar ist und ob
`_poll_once` mit der Attrappe bis zum Ende läuft — notfalls den Konstruktor-Aufruf an
`create_poller`/den vorhandenen Poller-Test in `tests/test_poller.py` angleichen und nur
den Teil bis zur Momentaufnahme prüfen. Der Test darf **nicht** wegfallen; er ist der
einzige, der diese Stelle berührt.

- [ ] **Schritt 7: Tests laufen lassen, Fehlschlag bestätigen**

```
python -m pytest tests/test_traffic_api.py -q
```
Erwartet: die neuen Tests scheitern mit 404 bzw. `AttributeError`.

- [ ] **Schritt 8: Poller die Momentaufnahme führen lassen**

In `app/poller.py`, im Konstruktor direkt hinter `self._active_flights` (~Zeile 383):

```python
        # Momentaufnahme des GESAMTEN Feeds für die Verkehrsanzeige (/api/traffic).
        # Nur im Speicher: Fremdverkehr wird nicht historisiert (s. Spec, Abschnitt 1.1).
        # Öffentlich benannt (kein Unterstrich) wie last_prefiles und ts_clients -- alles,
        # was die API aus dem Poller liest, ist in diesem Projekt öffentlich.
        self.traffic_snapshot: list[dict] = []
        self.traffic_snapshot_ts: float = 0.0
```

Import ergänzen (die Zeile `from app.vatsim import ...` ~47):

```python
from app.vatsim import (
    fetch_vatsim_data, filter_friesen_pilots, pilot_to_position, snapshot_other_traffic,
)
```

In `_poll_once`, direkt hinter `vatsim_data = await fetch_vatsim_data(self._http_client)`:

```python
            # Vor jeder weiteren Verarbeitung: Der Feed ist hier vollständig in der Hand,
            # später nicht mehr. Kostet einen Durchlauf über ~1000 Einträge alle 15 s.
            self.traffic_snapshot = snapshot_other_traffic(self.callsign_prefix, vatsim_data)
            self.traffic_snapshot_ts = time.time()
```

**`import time` fehlt in `app/poller.py`** (dort steht nur `datetime`) — bei den übrigen
Standardbibliotheks-Importen ergänzen. Ohne das wirft der erste Poll-Zyklus, und weil er in
einem großen `try` mit `logging.exception` sitzt, sieht man davon nur eine Logzeile.

- [ ] **Schritt 9: Endpunkt in `app/main.py` ergänzen**

`Query` zum FastAPI-Import (Zeile 19) hinzufügen:

```python
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, Request, UploadFile
```

Konstanten zu den übrigen Modulkonstanten:

```python
# Höchstzahl gleichzeitig ausgelieferter Fremdflugzeuge. Der Deckel schützt nicht den
# Server (die Rechnung ist trivial), sondern die Karte: Jeder Marker ist im Kniebrett
# DOM in Coherent GT, und dort wird es ab ein paar hundert Elementen zäh.
_TRAFFIC_MAX = 60
# Ab wann eine Momentaufnahme nicht mehr gezeigt wird: drei verpasste Poll-Zyklen bei
# VATSIM_POLL_INTERVAL = 15 s. Dann steht der Poller, und eine leere Karte ist ehrlicher
# als Positionen von vor einer Minute.
_TRAFFIC_MAX_AGE_SEC = 45.0
```

Endpunkt direkt hinter `/api/live` (~Zeile 655):

```python
@app.get("/api/traffic")
async def get_traffic(
    request: Request,
    lat: float = Query(..., ge=-90, le=90, description="Bezugspunkt, i. d. R. die Kartenmitte"),
    lon: float = Query(..., ge=-180, le=180),
    r: float = Query(100.0, ge=1, le=250, description="Radius in km"),
):
    """Fremder VATSIM-Verkehr im Umkreis eines Punktes -- ohne die eigenen Leute.

    Die Friesen kommen über ``/api/live`` und SSE; sie hier noch einmal mitzuliefern hieße,
    sie doppelt auf der Karte zu haben. Gefiltert wird schon in der Momentaufnahme
    (s. ``snapshot_other_traffic``).

    Kein Sonderweg bei der Anmeldung: verhält sich wie ``/api/live``, steht also bei
    aktivem Forum-Gate ebenfalls dahinter und gehört NICHT in ``_GATE_ALLOW_PREFIXES``.

    ``age`` ist das Alter der Momentaufnahme in Sekunden -- gerechnet ab dem Abruf durch
    den Poller, NICHT ab dem Messzeitpunkt bei VATSIM (den trüge ``last_updated`` je Pilot).
    Das Frontend datiert seine Fortrechnung damit zurück und läuft dadurch deutlich weniger
    hinterher, aber nicht gar nicht.
    """
    poller = getattr(request.app.state, "poller", None)
    schnappschuss = getattr(poller, "traffic_snapshot", None) or []
    stand = getattr(poller, "traffic_snapshot_ts", 0.0) or 0.0
    alter = time.time() - stand
    if not schnappschuss or stand <= 0 or alter > _TRAFFIC_MAX_AGE_SEC:
        return {"age": None, "traffic": []}

    # Den Anfragenden selbst nie als Fremdverkehr ausliefern. Fliegt er ausnahmsweise ohne
    # FRS-Callsign, faellt er nicht durch das Praefix-Sieb und bekaeme einen grauen Marker
    # an seiner VATSIM-Position -- direkt neben seinem eigenen, vom Simulator gesteuerten.
    # Clientseitig ist das nicht zu loesen: Dort ist nur bekannt, wer in liveData steht,
    # und das sind ausschliesslich die Friesen.
    eigene_cid = _current_cid(request, get_settings())

    nah: list[tuple[float, dict]] = []
    for e in schnappschuss:
        if eigene_cid is not None and e.get("cid") == eigene_cid:
            continue
        d = geo.haversine(lat, lon, e["lat"], e["lon"])
        if d <= r:
            nah.append((d, e))
    nah.sort(key=lambda paar: paar[0])
    # cid bleibt serverseitig -- der Client braucht sie nicht.
    return {
        "age": round(alter, 1),
        "traffic": [{k: v for k, v in e.items() if k != "cid"} for _, e in nah[:_TRAFFIC_MAX]],
    }
```

- [ ] **Schritt 10: Tests laufen lassen, grün bestätigen**

```
python -m pytest tests/test_traffic_api.py tests/test_poller.py tests/test_vatsim.py -q
```
Erwartet: alles passed.

- [ ] **Schritt 11: Commit**

```bash
git add app/poller.py app/main.py tests/test_traffic_api.py
git commit -m "Fremdverkehr: Endpunkt /api/traffic mit Umkreis und Deckel"
```

---

## Task 2: Label an den Markern

**Dateien:**
- Ändern: `app/static/index.html`
- Test: `tests/test_vr_panel.py`

**Schnittstellen:**
- Liefert: `_labelHoehe(altFt) -> string`, `_verkehrLabel(p, istFriese) -> string`,
  Konstante `_LABEL_FL_AB_FT`
- Nutzt: `escHtml`, `mapMarkers`, `updateMap`

**Kontext:** Die Marker haben heute **kein** dauerhaftes Label, nur ein Popup. Das Label
ist also für die Friesen genauso neu wie für den Fremdverkehr. Diese Task baut die Funktion
und hängt sie an die Friesen; Task 3 benutzt dieselbe Funktion für den Fremdverkehr.

- [ ] **Schritt 1: Fehlschlagende statische Prüfungen ergänzen**

An `tests/test_vr_panel.py` anhängen. **Der HTML-Quelltext liegt dort bereits als
Modulkonstante `INDEX` vor** (Zeile 21, `(STATIC / "index.html").read_text(...)`) — keine
Fixture anlegen, `INDEX` direkt benutzen:

```python
def test_label_hat_genau_eine_hoehen_funktion():
    """Eine Regel, eine Funktion.

    Eine zweite Fassung für den Fremdverkehr wäre die eigentliche Gefahr: Zwei
    Formatierungen derselben Höhe laufen früher oder später auseinander, und der Fehler
    fällt erst im Cockpit auf.
    """
    assert INDEX.count("function _labelHoehe(") == 1
    assert INDEX.count("function _verkehrLabel(") == 1


def test_label_grenze_steht_bei_zehntausend():
    assert "_LABEL_FL_AB_FT = 10000" in INDEX


def test_label_zeigt_callsign_bei_tief_oder_friese():
    """Die Regel ist ein ODER -- nur eine der beiden Bedingungen wäre ein halbes Feature."""
    stelle = INDEX.index("function _verkehrLabel(")
    rumpf = INDEX[stelle:stelle + 1200]
    assert "istFriese ||" in rumpf and "_LABEL_FL_AB_FT" in rumpf


def test_friesen_marker_tragen_das_label():
    """Das Label ist fuer die Friesen genauso neu wie fuer den Fremdverkehr."""
    assert "_verkehrLabel(p, true)" in INDEX
    assert "className: 'traffic-label'" in INDEX
```

**Kein Test auf `padStart`.** Die Methode ist ES2017 und steht bereits 15-mal in der
Datei — ein solcher Test wäre von Anfang an rot und verleitete dazu, funktionierenden
Code „zu reparieren". Wenn eine Sprachgrenze geprüft werden soll, dann die echte:
`assert "?." not in ...` und `"??" not in ...` — und das ist eine eigene Aufgabe, nicht
Teil dieses Plans.

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

```
python -m pytest tests/test_vr_panel.py -q -k label
```
Erwartet: 4 failed.

- [ ] **Schritt 3: Label-Funktionen einsetzen**

In `app/static/index.html` direkt vor `function makeAircraftIcon(` (~Zeile 7318):

```js
// --------------------------------------------------------------------------
//  Label am Flugzeug: MUSTER HÖHE GS, darüber der Callsign -- wenn er zählt
// --------------------------------------------------------------------------
// Die Regel ist eine Höhen-Regel, keine Friesen-Regel: Der Callsign steht am Symbol, wenn
// das Flugzeug TIEF fliegt oder wenn es ein Friese ist. Was tief fliegt, ist in der
// eigenen Naehe -- da will man wissen, wer es ist. Was oben drueberzieht, ist
// Linienverkehr; Muster, Level und Speed genuegen. Bei dreissig Fliegern im Bild ist jede
// eingesparte Zeile ein Stueck Lesbarkeit.
const _LABEL_FL_AB_FT = 10000;

// Genau 10 000 zaehlt als oben (FL100). Unterhalb der Grenze reine Fusszahl ohne Einheit.
// Kein padStart: Coherent GT ist Chrome 49, dort gibt es die Methode nicht -- und sie
// waere hier ohnehin ueberfluessig, weil ab 10 000 ft die Flugflaeche immer dreistellig ist.
function _labelHoehe(altFt) {
  const alt = Math.round(Number(altFt) || 0);
  if (alt >= _LABEL_FL_AB_FT) return 'FL' + Math.round(alt / 100);
  return String(alt);
}

// Nimmt beide Datenformen entgegen: die kurzen Feldnamen aus /api/traffic (cs/ac/alt/gs)
// und die langen der Friesen-Positionen (callsign/aircraft/altitude/groundspeed). Eine
// Funktion statt zweier -- s. Kommentar oben.
function _verkehrLabel(p, istFriese) {
  const alt    = Math.round(Number(p.alt != null ? p.alt : p.altitude) || 0);
  const gs     = Math.round(Number(p.gs  != null ? p.gs  : p.groundspeed) || 0);
  const muster = String(p.ac || p.aircraft || '').trim() || '?';
  const daten  = escHtml(muster) + ' ' + _labelHoehe(alt) + ' ' + gs;
  if (istFriese || alt < _LABEL_FL_AB_FT) {
    const cs = escHtml(String(p.cs || p.callsign || '').toUpperCase());
    return '<span class="lbl-cs">' + cs + '</span><span class="lbl-dat">' + daten + '</span>';
  }
  return '<span class="lbl-dat">' + daten + '</span>';
}
```

- [ ] **Schritt 4: Stil für das Label ergänzen**

Zu den übrigen Karten-Regeln im `<style>`-Block (in der Nähe von `.aircraft-marker`):

```css
    /* Das Label sitzt als Leaflet-Tooltip unter dem Symbol -- bewusst NICHT im Marker-Icon:
       Der Marker wird bei Track-up mitgedreht (rotateWithView), ein Label darin staende
       dann auf dem Kopf. */
    .traffic-label {
      background: rgba(4,8,15,0.72);
      border: none;
      box-shadow: none;
      color: #cfd8e3;
      font-family: var(--mono, monospace);
      font-size: 10px;
      line-height: 1.15;
      padding: 1px 3px;
      white-space: nowrap;
      text-align: center;
    }
    .traffic-label::before { display: none; }   /* Leaflets Sprechblasen-Zipfel */
    /* NICHT blau: Blau (#2d9cdb) ist in diesem Projekt Klickbarem vorbehalten (CLAUDE.md,
       stehende UI-Regeln). Ein Tooltip ist per Default nicht anklickbar -- der Callsign
       hebt sich deshalb ueber Helligkeit und Fettung ab, nicht ueber die Farbe. */
    .traffic-label .lbl-cs  { display: block; color: #eef2f7; font-weight: 700; }
    .traffic-label .lbl-dat { display: block; }
```

- [ ] **Schritt 5: Label an die Friesen-Marker hängen**

In `updateMap`, im `else`-Zweig direkt nach `.bindPopup(buildPopupHtml(p), …)`:

```js
        .bindTooltip(_verkehrLabel(p, true),
                     { permanent: true, direction: 'bottom', offset: [0, 4],
                       className: 'traffic-label', opacity: 1 })
```

Und im `if (vorhanden)`-Zweig, direkt neben `vorhanden.setPopupContent(...)`:

```js
      // Nur schreiben, wenn sich der Text wirklich geaendert hat: setTooltipContent
      // ersetzt das DOM-Element, und updateMap laeuft auf DREI Wegen (SSE, 10-Sekunden-
      // Neuzeichnen, 15-Sekunden-Abruf). Genau dieses unnoetige Neuaufbauen war schon
      // einmal als Aufblitzen im Kniebrett sichtbar.
      const beschriftung = _verkehrLabel(p, true);
      if (vorhanden._fsLabel !== beschriftung) {
        vorhanden.setTooltipContent(beschriftung);
        vorhanden._fsLabel = beschriftung;
      }
```

Im `else`-Zweig nach dem Anlegen: `marker._fsLabel = _verkehrLabel(p, true);`

- [ ] **Schritt 6: Tests laufen lassen, grün bestätigen**

```
python -m pytest tests/test_vr_panel.py -q
```
Erwartet: alles passed.

- [ ] **Schritt 7: Im Browser bestätigen — Label bei Track-up aufrecht**

Die Frage ist **im Quelltext des Plugins bereits geklärt** (s. Spec 3.3): `leaflet-rotate`
legt `tooltipPane` in den **nicht** drehenden Pane, überschreibt `L.Tooltip._updatePosition`
für die gedrehte Karte, und `rotateWithView` wirkt nur auf `marker._icon`. Das Label steht
aufrecht; ein Fallback mit zweitem Marker ist nicht nötig.

Also nur bestätigen: Live-Karte öffnen, Kompass einschalten, hinsehen. Wenn doch gemessen
werden soll:

```js
const r = document.querySelector('.traffic-label').getBoundingClientRect();
console.log(liveMap.getBearing(), r.width, r.height);
```

Bei aufrechtem Label bleiben Breite und Höhe über verschiedene Bearings konstant.
**Nicht `getScreenCTM()` benutzen** — das ist eine SVG-Methode, der Tooltip ist ein `div`,
der Aufruf wirft schlicht.

- [ ] **Schritt 8: Label-Grenzfälle im Browser prüfen**

In der Konsole:

```js
[[0,false],[9999,false],[10000,false],[10499,false],[10500,false],[35000,true]]
  .forEach(([alt, fr]) => console.log(alt, fr,
    _verkehrLabel({cs:'D-EXYZ', ac:'C172', alt: alt, gs: 105}, fr)));
```

Erwartet: `0`, `9999` und `10000`→`FL100` mit Callsign bzw. ohne (ab 10 000 ohne, außer
`istFriese`), `10499`→`FL105`, `10500`→`FL105`, `35000` mit `istFriese` **mit** Callsign.

- [ ] **Schritt 9: Commit**

```bash
git add app/static/index.html tests/test_vr_panel.py
git commit -m "Karte: Label mit Muster, Hoehe und Geschwindigkeit an den Markern"
```

---

## Task 3: Die Verkehrs-Ebene

**Dateien:**
- Ändern: `app/static/index.html`
- Test: `tests/test_vr_panel.py`

**Schnittstellen:**
- Nutzt: `_verkehrLabel` (Task 2), `_jetztGerechnet`, `_naviTakt`, `makeAircraftIcon`,
  `GET /api/traffic` (Task 1)
- Liefert: `_verkehrRoh`, `_verkehrGruppe`, `_setupVerkehrPref`, `_addPreferredVerkehrLayer`

- [ ] **Schritt 1: Fehlschlagende statische Prüfungen ergänzen**

```python
def test_verkehr_layer_kommt_vor_der_ebenen_auswahl():
    """Die OpenAIP-Falle: Ein nach dem Bau der Control hinzugefügter Layer feuert keines
    der Ereignisse, auf die die Control lauscht -- der Haken zeigt dann dauerhaft den
    falschen Zustand. Steht so schon als Kommentar bei _addPreferredAIPLayer.

    ACHTUNG beim Aendern: INDEX.index(sub, start) liefert per Definition immer einen Wert
    >= start -- ein "assert vorher < INDEX.index('L.control.layers(', vorher)" kann gar
    nicht fehlschlagen. Die Control MUSS unabhaengig gefunden werden, ueber ihren
    eindeutigen Nachbarn (es gibt drei L.control.layers-Aufrufe in der Datei).
    """
    vorher = INDEX.index("_addPreferredVerkehrLayer(liveMap")
    control = INDEX.index("liveOverlays,")
    assert vorher < control


def test_verkehr_popup_nimmt_dieselbe_hoehen_regel():
    """Sonst steht am Symbol FL120 und einen Klick daneben 12.000 ft: das vorhandene
    fmtAlt schreibt Flugflaechen erst ab 18 000 ft."""
    stelle = INDEX.index("function _verkehrPopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_labelHoehe(" in rumpf
    assert "fmtAlt(" not in rumpf


def test_eigener_abruf_loest_keinen_neuen_abruf_aus():
    """_naviTakt ruft bei eingeschalteter Moving Map jede Sekunde setView auf, und das
    feuert moveend. Ohne die Wache liefe der Verkehrs-Abruf alle 3 Sekunden statt alle 15
    -- dauerhaft, ausgerechnet ueber die Netzwerkverbindung des Simulators."""
    stelle = INDEX.index("map.on('moveend'")
    assert "_naviSelbstBewegt" in INDEX[stelle:stelle + 200]


def test_verkehr_ruht_auf_verdeckter_karte():
    """updateMap und _naviTakt brechen auf einer verdeckten Karte ab -- der Abruf muss das
    auch, sonst laufen die Rohwerte weiter, waehrend der Takt die Marker nicht bewegt, und
    beim Zurueckwechseln springen sie."""
    stelle = INDEX.index("function _verkehrAbrufen(")
    assert "_istSichtbar(" in INDEX[stelle:stelle + 600]


def test_nur_der_takt_bewegt_den_fremdverkehr():
    """Eine bewegte Anzeige braucht genau eine Stelle, die sie bewegt -- sonst springt sie
    zurueck. Derselbe Fehler kostete bei den Friesen drei Anläufe."""
    assert INDEX.count("_verkehrMarker[cs].setLatLng(") == 1


def test_verkehr_zeitstempel_nur_bei_neuen_werten():
    stelle = INDEX.index("function _verkehrUebernehmen(")
    rumpf = INDEX[stelle:stelle + 2000]
    assert "alt.lat !== e.lat" in rumpf and "alt.lon !== e.lon" in rumpf


def test_verkehr_hat_eine_einzige_zoom_schwelle():
    """Der Wert steht genau einmal als Zahl -- eine zweite Stelle daneben waere die
    Sorte Fehler, die man erst im Cockpit bemerkt."""
    assert INDEX.count("_VERKEHR_MIN_ZOOM") >= 2
    assert INDEX.count("_VERKEHR_MIN_ZOOM =") == 1


def test_verkehr_datiert_die_fortrechnung_zurueck():
    stelle = INDEX.index("function _verkehrUebernehmen(")
    assert "Date.now() - Math.round(ageSek * 1000)" in INDEX[stelle:stelle + 1200]
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

```
python -m pytest tests/test_vr_panel.py -q -k "verkehr or eigener_abruf"
```
Erwartet: 8 failed.

- [ ] **Schritt 3: Zustand und Voreinstellung anlegen**

Direkt hinter dem AIP-Block (~Zeile 3666, nach `_addPreferredAIPLayer`):

```js
// --------------------------------------------------------------------------
//  Fremdverkehr als Karten-Ebene
// --------------------------------------------------------------------------
// Bedient wird er wie OpenAIP: ein Haken in der Ebenen-Auswahl, kein eigener Knopf. Die
// Karte hat im Cockpit ohnehin wenig Platz, und eine Ebene ist genau das, was er ist.
//
// Geschaltet wird AUSSCHLIESSLICH der Fremdverkehr. Die Friesen sind der Kern der Anwendung
// und kommen ueber einen anderen Weg (SSE / /api/live) -- sie bleiben immer sichtbar.
const _VERKEHR_PREF_KEY = 'friesenspy_verkehr';
// Unterhalb dieser Zoomstufe wird nicht abgefragt und nichts gezeichnet. 7 ist die Stufe,
// mit der die Live-Karte oeffnet (minZoom ist 6): Laege die Schwelle darueber, schaltete
// man die Ebene ein und es passierte sichtbar nichts.
// Vom Nutzer am laufenden Bild geprueft und bestaetigt (15.08.2026). Steht genau einmal
// hier und nirgends sonst als Zahl.
const _VERKEHR_MIN_ZOOM = 7;
const _VERKEHR_TAKT_MS  = 15000;   // wie der VATSIM-Poll -- oefter gaebe es nichts Neues
const _VERKEHR_MAX_KM   = 250;     // serverseitige Obergrenze, hier gespiegelt
const _VERKEHR_DROSSEL_MS = 3000;  // gegen Dauerziehen an der Karte

const _verkehrRoh    = {};   // callsign -> {lat, lon, hdg, gs, ts} -- gemeldete Rohwerte
const _verkehrMarker = {};   // callsign -> L.Marker
let _verkehrGruppe   = null;
let _verkehrTimer    = null;
let _verkehrLetzterAbruf = 0;
let _verkehrNachholer = null;   // Drossel-Nachhol-Termin, s. _verkehrAbrufen
const _verkehrFehlt  = {};      // callsign -> wie oft in Folge nicht gemeldet (Hysterese)

function _saveVerkehrPref(an) { try { localStorage.setItem(_VERKEHR_PREF_KEY, an ? '1' : '0'); } catch (e) {} }
function _loadVerkehrPref() { try { return localStorage.getItem(_VERKEHR_PREF_KEY) === '1'; } catch (e) { return false; } }

function _makeVerkehrLayer() { return L.layerGroup(); }

// Wie bei OpenAIP: NUR die Listener anmelden, den Layer NICHT hinzufuegen.
function _setupVerkehrPref(map, gruppe) {
  if (!gruppe) return;
  map.on('overlayadd',    (e) => { if (e.layer === gruppe) { _saveVerkehrPref(true);  _verkehrStarten(map); } });
  map.on('overlayremove', (e) => { if (e.layer === gruppe) { _saveVerkehrPref(false); _verkehrStoppen(); } });
  // Die Wache ist hier NICHT optional: Bei eingeschalteter Moving Map ruft _naviTakt jede
  // Sekunde setView auf, und Leaflet feuert danach moveend. Ohne sie liefe der Abruf
  // dauerhaft im Drossel-Takt (alle 3 s statt alle 15 s) -- ausgerechnet ueber die
  // Netzwerkverbindung des Simulators, wo die Spec mit 5 KB je 15 s rechnet. setView ist
  // synchron und der Merker steht waehrenddessen (s. _naviTakt), die Wache greift also.
  map.on('moveend', () => { if (!_naviSelbstBewegt) _verkehrAbrufen(map); });
}

// Und wie bei OpenAIP: VOR dem Bau der Layers-Control -- sonst zeigt der Haken dauerhaft
// den falschen Zustand (s. Kommentar bei _addPreferredAIPLayer).
function _addPreferredVerkehrLayer(map, gruppe) {
  if (gruppe && _loadVerkehrPref()) gruppe.addTo(map);
}
```

- [ ] **Schritt 4: Abruf und Übernahme schreiben**

Direkt darunter:

```js
function _verkehrStarten(map) {
  if (_verkehrTimer) return;
  _verkehrAbrufen(map);
  _verkehrTimer = setInterval(() => _verkehrAbrufen(map), _VERKEHR_TAKT_MS);
}

function _verkehrStoppen() {
  if (_verkehrTimer) { clearInterval(_verkehrTimer); _verkehrTimer = null; }
  if (_verkehrNachholer) { clearTimeout(_verkehrNachholer); _verkehrNachholer = null; }
  _verkehrLeeren();
}

function _verkehrLeeren() {
  for (const cs in _verkehrMarker) {
    if (_verkehrGruppe) _verkehrGruppe.removeLayer(_verkehrMarker[cs]);
    delete _verkehrMarker[cs];
  }
  for (const cs in _verkehrRoh) delete _verkehrRoh[cs];
  for (const cs in _verkehrFehlt) delete _verkehrFehlt[cs];
}

// Radius so, dass der sichtbare Ausschnitt abgedeckt ist: Mitte bis Ecke. Gekappt auf die
// serverseitige Obergrenze -- daraus wird bei weit herausgezoomter Karte ein Kreis in der
// Mitte statt eines vollen Bildes, und das ist die richtige Entscheidung: Was am Rand von
// halb Europa fliegt, ist keine Information mehr.
function _verkehrRadiusKm(map) {
  const km = map.getCenter().distanceTo(map.getBounds().getNorthEast()) / 1000;
  return Math.max(1, Math.min(_VERKEHR_MAX_KM, Math.round(km)));
}

function _verkehrAbrufen(map) {
  if (!map || !_verkehrGruppe || !map.hasLayer(_verkehrGruppe)) return;
  // Auf einer verdeckten Karte ist der Abruf Arbeit ohne Wirkung -- und schlimmer als
  // nutzlos: Die Rohwerte liefen weiter, waehrend der Takt (der ebenfalls abbricht) die
  // Marker nicht bewegt. Beim Zurueckwechseln saehe man sie springen.
  if (!_istSichtbar(map.getContainer())) return;
  if (map.getZoom() < _VERKEHR_MIN_ZOOM) { _verkehrLeeren(); return; }
  const jetzt = Date.now();
  // Drossel mit Nachhol-Termin: Verwerfen allein hiesse, dass nach einem Zug an der Karte
  // der neue Ausschnitt bis zu 15 Sekunden ohne Verkehr bleibt.
  if (jetzt - _verkehrLetzterAbruf < _VERKEHR_DROSSEL_MS) {
    if (!_verkehrNachholer) {
      _verkehrNachholer = setTimeout(() => {
        _verkehrNachholer = null;
        _verkehrAbrufen(map);
      }, _VERKEHR_DROSSEL_MS - (jetzt - _verkehrLetzterAbruf));
    }
    return;
  }
  _verkehrLetzterAbruf = jetzt;

  const c = map.getCenter();
  fetch('/api/traffic?lat=' + c.lat.toFixed(4) + '&lon=' + c.lng.toFixed(4)
        + '&r=' + _verkehrRadiusKm(map))
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => { if (d) _verkehrUebernehmen(d.traffic || [], Number(d.age) || 0); })
    // Netz weg (im Kniebrett keine Seltenheit): stillschweigend beim naechsten Takt wieder.
    .catch(() => {});
}

function _verkehrUebernehmen(liste, ageSek) {
  if (!_verkehrGruppe) return;
  // Die Fortrechnung muss dort beginnen, wo VATSIM gemessen hat, nicht dort, wo die
  // Antwort ankam -- sonst laeuft die Anzeige systematisch um das Alter hinterher.
  const gemessenTs = Date.now() - Math.round(ageSek * 1000);
  const gesehen = Object.create(null);

  for (let i = 0; i < liste.length; i++) {
    const e  = liste[i];
    const cs = e && e.cs;
    if (!cs) continue;
    // Das eigene Flugzeug ist hier nicht auszufiltern -- das erledigt der Server ueber die
    // CID (s. Task 1, Schritt 9). Clientseitig ginge es nicht: _meinCallsign() liest aus
    // liveData, und dort stehen nur FRS-Piloten -- also gerade nicht der Fall, um den es
    // geht (eigener Flug ohne FRS-Callsign).
    gesehen[cs] = true;
    delete _verkehrFehlt[cs];

    // Zeitstempel NUR bei wirklich neuen Koordinaten -- sonst faengt die Fortrechnung bei
    // jedem Abruf von vorn an und der Marker springt zurueck. Genau dieser Fehler kostete
    // bei den Friesen drei Anlaeufe (s. Kommentar in updateMap).
    const alt = _verkehrRoh[cs];
    if (!alt || alt.lat !== e.lat || alt.lon !== e.lon) {
      _verkehrRoh[cs] = { lat: e.lat, lon: e.lon,
                          hdg: Number(e.hdg) || 0, gs: Number(e.gs) || 0, ts: gemessenTs };
    }

    const hdg = Math.round(Number(e.hdg) || 0);
    const beschriftung = _verkehrLabel(e, false);
    const vorhanden = _verkehrMarker[cs];
    if (vorhanden) {
      if (vorhanden._fsHeading !== hdg) {
        vorhanden.setIcon(makeAircraftIcon(hdg, true));
        vorhanden._fsHeading = hdg;
      }
      if (vorhanden._fsLabel !== beschriftung) {
        vorhanden.setTooltipContent(beschriftung);
        vorhanden._fsLabel = beschriftung;
      }
      // Auch hier nur bei echter Aenderung -- 60 Popups bei jedem Abruf neu zu bauen ist
      // dieselbe unnoetige Arbeit, die beim Tooltip zwei Zeilen darueber vermieden wird.
      const popup = _verkehrPopup(e);
      if (vorhanden._fsPopup !== popup) {
        vorhanden.setPopupContent(popup);
        vorhanden._fsPopup = popup;
      }
    } else {
      const m = L.marker([e.lat, e.lon], { icon: makeAircraftIcon(hdg, true), rotateWithView: true })
        .bindPopup(_verkehrPopup(e), { maxWidth: 220 })
        .bindTooltip(beschriftung, { permanent: true, direction: 'bottom', offset: [0, 2],
                                     className: 'traffic-label', opacity: 1 })
        .addTo(_verkehrGruppe);
      m._fsHeading = hdg;
      m._fsLabel = beschriftung;
      m._fsPopup = _verkehrPopup(e);
      _verkehrMarker[cs] = m;
    }
  }

  // Wer nicht mehr gemeldet wird, verschwindet -- sonst rechnet der Takt eine Position
  // endlos weiter, deren Flugzeug laengst ausser Reichweite ist.
  //
  // Aber erst beim ZWEITEN Fehlen: Der Server kappt hart bei 60 nach Entfernung, ohne
  // Hysterese. Ein Flugzeug auf Rang 60/61 wechselt zwischen zwei Abrufen hin und her,
  // und jedes Loeschen samt Neuanlegen ist im Kniebrett als Aufblitzen sichtbar (derselbe
  // Fund, der schon setIcon aus dem Takt genommen hat).
  for (const cs in _verkehrMarker) {
    if (gesehen[cs]) continue;
    _verkehrFehlt[cs] = (_verkehrFehlt[cs] || 0) + 1;
    if (_verkehrFehlt[cs] < 2) continue;
    _verkehrGruppe.removeLayer(_verkehrMarker[cs]);
    delete _verkehrMarker[cs];
    delete _verkehrRoh[cs];
    delete _verkehrFehlt[cs];
  }
}

// Die Hoehe kommt aus _labelHoehe, NICHT aus dem vorhandenen fmtAlt: Das schreibt
// Flugflaechen erst ab 18 000 ft. Am Symbol staende dann FL120 und einen Klick daneben
// 12.000 ft -- genau die zweite Wahrheit, die _labelHoehe verhindern soll.
function _verkehrPopup(e) {
  const route = (e.dep || e.arr) ? fmtRouteHtml(e.dep, e.arr) : '—';
  return '<div class="popup-callsign">' + escHtml(String(e.cs || '').toUpperCase()) + '</div>'
       + '<div class="popup-row">Muster: <span>' + acLink(e.ac || '') + '</span></div>'
       + '<div class="popup-row">Flugplan: <span>' + route + '</span></div>'
       + '<div class="popup-row">Höhe: <span>' + _labelHoehe(e.alt) + '</span></div>'
       + '<div class="popup-row">GS: <span>' + fmtGS(e.gs) + '</span></div>';
}
```

- [ ] **Schritt 5: `makeAircraftIcon` um die kleine, graue Fassung erweitern**

Signatur zu `makeAircraftIcon(heading, fremd)` ändern; die vorhandenen Aufrufe ohne
zweiten Parameter behalten damit ihr Verhalten:

```js
const _FLUGZEUG_PX_FREMD = 18;

function makeAircraftIcon(heading, fremd) {
  const hdg = Number(heading) || 0;
  const px = fremd ? _FLUGZEUG_PX_FREMD : _FLUGZEUG_PX;
  const mitte = px / 2;
  const klasse = fremd ? 'aircraft-marker aircraft-marker-fremd' : 'aircraft-marker';
  return L.divIcon({
    className: '',
    html: `<div class="${klasse}" style="transform: rotate(${hdg}deg);">
      <svg width="${px}" height="${px}" viewBox="0 0 24 24" fill="currentColor">
        <path d="${_FLUGZEUG_PFAD}"/>
      </svg>
    </div>`,
    iconSize:   [px, px],
    iconAnchor: [mitte, mitte],
    popupAnchor:[0, -mitte - 2],
  });
}
```

Dazu im Stylesheet neben `.aircraft-marker`:

```css
    /* Fremdverkehr ist Kulisse, die Friesen sind die Aussage -- deshalb kleiner und grau. */
    .aircraft-marker-fremd { color: #8a97a8; }
```

- [ ] **Schritt 6: In den Sekundentakt einhängen**

In `_naviTakt`, direkt hinter der bestehenden Schleife über `mapMarkers` (Abschnitt „2.")
und **vor** `_eigenesFlugzeugZeichnen()`:

```js
  // 2b. Fremdverkehr -- gleiche Rechnung, eigene Datenquelle. Auch hier gilt: Bewegt wird
  //     NUR hier. Steht der Rohwert nicht (mehr) da, bleibt der Marker stehen, statt auf
  //     eine geratene Position zu springen.
  for (const cs in _verkehrMarker) {
    const roh = _verkehrRoh[cs];
    if (!roh) continue;
    const p = _jetztGerechnet(roh);
    _verkehrMarker[cs].setLatLng([p.lat, p.lon]);
  }
```

- [ ] **Schritt 7: Ebene in die Live-Karte einhängen**

In der Karteninitialisierung (~Zeile 7276), zwischen `_addPreferredAIPLayer` und
`L.control.layers(`:

```js
  _verkehrGruppe = _makeVerkehrLayer();
  _addPreferredVerkehrLayer(liveMap, _verkehrGruppe);
```

Die Overlay-Liste der Control erweitern:

```js
  const liveOverlays = {};
  if (liveAIP) liveOverlays['OpenAIP'] = liveAIP;
  liveOverlays['Verkehr'] = _verkehrGruppe;
  L.control.layers(
    { 'OpenFlightMap': liveLayers.ofm, 'OpenTopo': liveLayers.topo, 'Satellit': liveLayers.sat, 'Light': liveLayers.light, 'Dark': liveLayers.dark },
    liveOverlays,
    { position: 'topright', collapsed: true }
  ).addTo(liveMap);
  _setupAIPPref(liveMap, liveAIP);
  _setupVerkehrPref(liveMap, _verkehrGruppe);
  if (liveMap.hasLayer(_verkehrGruppe)) _verkehrStarten(liveMap);
```

- [ ] **Schritt 8: Tests laufen lassen, grün bestätigen**

```
python -m pytest tests/ -q
```
Erwartet: die vorhandenen ~1513 Tests plus die neuen, alles passed.

- [ ] **Schritt 9: Im Browser messen**

Server lokal starten, Live-Karte öffnen. Nachweisen:

1. Der Haken „Verkehr" in der Ebenen-Auswahl zeigt nach Neuladen denselben Zustand wie
   vorher (das ist die OpenAIP-Falle — sie ist hier der wahrscheinlichste Fehler).
2. Eingeschaltet erscheinen graue Flugzeuge mit Label.
3. Auf `_VERKEHR_MIN_ZOOM - 1` herauszoomen: die Marker verschwinden, im Netzwerk-Tab
   kommen keine Abrufe mehr.
4. Eine Minute zusehen: Die Marker **gleiten** und springen nicht alle 15 Sekunden zurück.
5. Ausschalten: Marker weg, Abrufe hören auf.

- [ ] **Schritt 10: Commit**

```bash
git add app/static/index.html tests/test_vr_panel.py
git commit -m "Karte: Fremdverkehr als abschaltbare Ebene, gleitend"
```

---

## Task 4: Messsonde im Kniebrett (parallel zu Task 1)

**Dateien:**
- Ändern: `msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx`,
  `msfs-panel/PackageSources/FriesenSpy/manifest.json`
- Test: `tests/test_vr_panel.py`

**Zweck:** Die Machbarkeitsfrage für Teilprojekt 2 beantworten, ohne dass der Nutzer etwas
tun muss: Gibt `Coherent.call('GET_AIR_TRAFFIC')` den von vPilot injizierten Verkehr heraus?
DevSupport 4993 sagt nein (von Asobo bestätigt, für in der Luft erzeugte AI-Objekte — genau
so injiziert vPilot), ist für MSFS 2024 aber nicht bestätigt.

- [ ] **Schritt 1: Fehlschlagende statische Prüfungen ergänzen**

Neben der vorhandenen Modulkonstante `INDEX` (Zeile 22) eine zweite anlegen. **Nicht
bedingungslos lesen** — fehlt `msfs-panel/` in irgendeiner Umgebung, bricht sonst das
Sammeln der ganzen Datei ab, nicht nur dieser drei Tests:

```python
_TSX_PFAD = (Path(__file__).resolve().parents[1] / "msfs-panel" / "PackageSources"
             / "FriesenSpy" / "src" / "FriesenSpy.tsx")
PANEL_TSX = _TSX_PFAD.read_text(encoding="utf-8") if _TSX_PFAD.exists() else ""

ohne_panel = pytest.mark.skipif(not _TSX_PFAD.exists(), reason="msfs-panel nicht vorhanden")


def _sonde_rumpf() -> str:
    """Der Methodenrumpf bis zur schliessenden Klammer.

    Feste Zeichenfenster (…[stelle:stelle+1800]) sind hier die falsche Wahl: Zwei
    zusaetzliche Kommentarzeilen -- bei diesem Kommentarstil normal -- kippen den Test,
    ohne dass sich am Verhalten etwas aendert.
    """
    stelle = PANEL_TSX.index("private async sondeMessen")
    return PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]


@ohne_panel
def test_sonde_ist_selbstbegrenzt():
    """Eine Sonde, die im Dauerbetrieb laeuft, ist eine Wanze. Drei Messpunkte, dann Ruhe."""
    assert PANEL_TSX.count("_SONDE_ZEITPUNKTE = [20000, 120000, 300000]") == 1
    assert "clearTimeout" in PANEL_TSX


@ohne_panel
def test_sonde_kann_den_panel_start_nicht_zerreissen():
    """Eine unbeantwortete Frage ist besser als ein abstuerzendes Kniebrett."""
    rumpf = _sonde_rumpf()
    assert "try {" in rumpf and "catch" in rumpf


@ohne_panel
def test_sonde_meldet_keine_fremden_positionen():
    """Gemessen wird, OB und WAS der Sim herausgibt -- nicht, wo jemand fliegt."""
    assert "Object.keys(t[0])" in _sonde_rumpf()


@ohne_panel
def test_sonde_meldung_traegt_die_quelle():
    """Ohne quelle='friesenspy-shell' verwirft der Empfaenger in index.html die Nachricht
    in seiner ersten Zeile -- die Sonde waere toter Code."""
    assert 'quelle: "friesenspy-shell", art: "panel-diag"' in PANEL_TSX


def test_sonde_wird_mit_zwei_argumenten_gemeldet():
    """window._panelDiag(kind, data). Mit einem Argument landete der ganze Befund im Feld
    kind und der Datensatz kind='traffic-sonde' entstuende nie."""
    assert "window._panelDiag('traffic-sonde', d.befund)" in INDEX
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

```
python -m pytest tests/test_vr_panel.py -q -k sonde
```
Erwartet: 5 failed.

- [ ] **Schritt 3: Sonde in `FriesenSpy.tsx` einsetzen**

Bei den übrigen Modulkonstanten:

```tsx
// Messsonde fuer den spaeteren Sim-Verkehr (Teilprojekt 2). Die Frage: Gibt der Simulator
// den von vPilot injizierten Verkehr ueber den JS-Weg heraus? DevSupport 4993 sagt nein --
// in der Luft erzeugte AI-Objekte tauchen dort nicht auf, und genau so injiziert vPilot.
// Fuer MSFS 2024 ist das nicht bestaetigt, und die Antwort entscheidet, ob ein C++-Modul
// noetig wird. Also einmal messen, statt weiter zu vermuten.
//
// Drei Zeitpunkte, weil beim ersten oft noch nichts injiziert ist: gerade gestartet, im
// Steigflug, unterwegs. Danach ist Schluss -- eine Sonde im Dauerbetrieb waere eine Wanze.
const _SONDE_ZEITPUNKTE = [20000, 120000, 300000];
```

Und die Messung selbst — **als Methoden der Klasse `FriesenSpyView`**, nicht als
Modulfunktionen: `rahmenRef` ist ein privates Klassenfeld und außerhalb der Klasse gar
nicht sichtbar. Der Zugriff geht über `this.rahmenRef.instance` (eine `NodeReference` aus
`FSComponent.createRef`) — **nicht** `.current`, das ist React-Syntax und ein
TypeScript-Fehler:

```tsx
  private async sondeMessen(nummer: number): Promise<void> {
  // Kein `kind` im Befund -- das setzt die Empfangsseite als erstes Argument von
  // window._panelDiag('traffic-sonde', befund).
  const befund: Record<string, unknown> = { messpunkt: nummer };
  try {
    const c: any = (globalThis as any).Coherent;
    befund.coherentDa = !!(c && typeof c.call === 'function');
    if (!befund.coherentDa) return sondeMelden(befund, rahmen);

    // In MSFS 2020 war das die Vorbedingung dafuer, dass der Aufruf ueberhaupt etwas
    // lieferte. Ob sie in 2024 noch gilt, weiss niemand -- also einmal mit und einmal ohne.
    try {
      const rvl: any = (globalThis as any).RegisterViewListener;
      if (typeof rvl === 'function') {
        const l = rvl('JS_LISTENER_MAPS');
        if (l && typeof l.trigger === 'function') l.trigger('JS_BIND_BINGMAP', 'FS_SONDE', true);
        befund.viewListener = 'angemeldet';
      } else {
        befund.viewListener = 'unbekannt';
      }
    } catch (e: any) {
      befund.viewListener = 'fehler: ' + String(e && e.message ? e.message : e);
    }

    const t: any = await c.call('GET_AIR_TRAFFIC');
    befund.typ = Object.prototype.toString.call(t);
    befund.anzahl = Array.isArray(t) ? t.length : null;
    // Nur die FELDNAMEN des ersten Eintrags, keine Positionen: Die Frage ist, OB und WAS
    // der Sim herausgibt, nicht wo jemand fliegt.
    befund.felder = Array.isArray(t) && t.length ? Object.keys(t[0]) : [];
  } catch (e: any) {
    befund.fehler = String(e && e.message ? e.message : e);
  }
  this.sondeMelden(befund);
}

  private sondeMelden(befund: Record<string, unknown>): void {
    try {
      const ziel = this.rahmenRef.instance ? this.rahmenRef.instance.contentWindow : null;
      // `quelle` ist PFLICHT: Der Empfaenger in index.html verwirft jede Nachricht ohne
      // `quelle === "friesenspy-shell"` in der ersten Zeile. Alle vier bestehenden
      // Meldungen (pong, position, notify-ok, notify-fehler) setzen sie.
      if (ziel) ziel.postMessage({ quelle: "friesenspy-shell", art: "panel-diag", befund }, "*");
    } catch (e) { /* Meldung verloren -- schlimmer waere ein Absturz */ }
  }
```

Auslösen in `onAfterRender` (dort steht bereits der `message`-Listener), und die Termine in
`destroy()` wieder abräumen — konsequent zum Rest der Datei:

```tsx
  private sondeTermine: ReturnType<typeof setTimeout>[] = [];

  public onAfterRender(node: VNode): void {
    super.onAfterRender(node);
    window.addEventListener("message", this.onNachricht);
    this.sondeTermine = _SONDE_ZEITPUNKTE.map((ms, i) =>
      setTimeout(() => { void this.sondeMessen(i + 1); }, ms));
  }

  public destroy(): void {
    window.removeEventListener("message", this.onNachricht);
    this.sondeTermine.forEach((t) => clearTimeout(t));
    super.destroy();
  }
```

- [ ] **Schritt 4: Empfangsseite in `app/static/index.html` ergänzen**

Im vorhandenen `message`-Listener in `_initPanelShellKanal` (dort, wo die Eigenposition
ankommt), hinter der `quelle`-Wache einen Zweig ergänzen:

```js
    if (d.art === 'panel-diag' && d.befund && typeof window._panelDiag === 'function') {
      // ZWEI Argumente: window._panelDiag(kind, data). Mit nur einem landete das ganze
      // Objekt im Feld `kind`, der Server schneidet es auf 40 Zeichen ab, und der
      // versprochene Datensatz kind="traffic-sonde" entstuende nie.
      window._panelDiag('traffic-sonde', d.befund);
      return;
    }
```

- [ ] **Schritt 5: Paketversion auf 1.3.0 setzen**

In `msfs-panel/PackageSources/FriesenSpy/manifest.json`: `"package_version": "1.3.0"`.

- [ ] **Schritt 6: Paket bauen und Tests laufen lassen**

```
python -m pytest tests/test_vr_panel.py -q
powershell -File msfs-panel\build-package.ps1
```

- [ ] **Schritt 7: Commit**

```bash
git add msfs-panel app/static/index.html tests/test_vr_panel.py
git commit -m "Kniebrett 1.3.0: Messsonde fuer den Sim-Verkehr"
```

---

## Task 6: Live-Karte öffnet über EDWG

**Dateien:**
- Ändern: `app/static/index.html`
- Test: `tests/test_vr_panel.py`

**Kontext:** Die Live-Karte öffnet heute auf `[54.5, 8.5]` — das liegt in der Nordsee
westlich von Sylt, rund 130 km vom Vereinsgebiet entfernt. Sie soll über **EDWG
(Wangerooge, 53.78278 / 7.91389)** aufgehen. Zoomstufe bleibt 7 (Nutzer-Entscheidung
15.08.2026).

**Nur die Live-Karte.** Die Track- und Event-Karten richten sich nach dem, was sie zeigen —
sie auf EDWG zu zwingen wäre falsch.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_live_karte_oeffnet_ueber_edwg():
    """EDWG ist der Heimatplatz -- eine Karte, die in der offenen Nordsee aufgeht, kostet
    bei jedem Oeffnen zwei Handgriffe."""
    assert "_KARTE_MITTE = [53.78278, 7.91389]" in INDEX
    assert "center:    [54.5, 8.5]" not in INDEX
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

```
python -m pytest tests/test_vr_panel.py -q -k edwg
```
Erwartet: 1 failed.

- [ ] **Schritt 3: Startpunkt als benannte Konstante setzen**

Zu den übrigen Kartenkonstanten (in der Nähe von `_KARTE_EINBLENDEN`, ~Zeile 3640):

```js
// Startpunkt der Live-Karte: EDWG (Wangerooge), der Heimatplatz. Vorher stand hier ein
// Punkt in der offenen Nordsee, rund 130 km westlich -- jedes Oeffnen begann mit Schieben.
// Als Konstante, damit Startpunkt und Zoomstufe an einer Stelle stehen und nicht mitten
// in der Karteninitialisierung.
const _KARTE_MITTE = [53.78278, 7.91389];
const _KARTE_ZOOM  = 7;
```

In der Initialisierung der Live-Karte (~Zeile 7258):

```js
    center:    _KARTE_MITTE,
    zoom:      _KARTE_ZOOM,
```

- [ ] **Schritt 4: Tests laufen lassen, grün bestätigen**

```
python -m pytest tests/test_vr_panel.py -q
```

- [ ] **Schritt 5: Im Browser prüfen**

Karte neu laden: Wangerooge liegt in der Mitte, die ostfriesischen Inseln sind im Bild.

- [ ] **Schritt 6: Commit**

```bash
git add app/static/index.html tests/test_vr_panel.py
git commit -m "Karte oeffnet ueber EDWG statt in der offenen Nordsee"
```

---

## Task 5: Doku, Changelog, Release

**Dateien:**
- Ändern: `README.md`, `docs/api.md`, `docs/architecture.md`,
  `docs/efb-panel-debugging.md`, `app/CHANGELOG.json`

- [ ] **Schritt 1: `docs/api.md` — `GET /api/traffic` dokumentieren**

Parameter mit ihren Grenzen (`lat` −90…90, `lon` −180…180, `r` 1…250 km, Vorgabe 100),
das Antwortformat mit `age`, die Deckel (60 Flugzeuge, 120 s), und den Hinweis, dass die
eigenen Leute **nicht** enthalten sind, weil sie über `/api/live` und SSE kommen.

- [ ] **Schritt 2: `docs/architecture.md` — Abschnitt ergänzen**

Unter der Poller-Beschreibung: die Momentaufnahme im Speicher (und warum **nicht** in der
Datenbank), die Trennung „Rohwert (`_verkehrRoh`) / gezeichnete Position (Marker)", die
Rückdatierung über `age`, und die Naht zu Teilprojekt 2 — dass der zeichnende Teil seinen
Zulieferer nicht kennt und deshalb später ohne Änderung aus dem Sim gespeist werden kann.

- [ ] **Schritt 3: `docs/efb-panel-debugging.md` — `traffic-sonde` beschreiben**

Der neue `panel_diag`-Typ, seine Felder (`messpunkt`, `coherentDa`, `viewListener`, `typ`,
`anzahl`, `felder`, `fehler`) und wie das Ergebnis zu lesen ist: `anzahl > 0` mit
plausiblen Feldnamen heißt, Teilprojekt 2 kommt ohne WASM aus; `0` oder `null` bei
verbundenem vPilot bestätigt DevSupport 4993 und damit den WASM-Weg.

- [ ] **Schritt 4: `README.md` — Kartenabschnitt**

Zwei, drei Sätze: die Ebene „Verkehr", was sie zeigt, dass sie nur den Fremdverkehr
schaltet und dass die Positionen zwischen den 15-Sekunden-Meldungen fortgerechnet werden.

- [ ] **Schritt 5: `app/CHANGELOG.json` — Eintrag ganz vorne**

**Achtung, zwei Fallen, die hier schon zugeschlagen haben:**
- Kein gerades `"` innerhalb eines Strings — es beendet den String und zerlegt die ganze
  Datei (typografische Anführungszeichen `„…"` benutzen).
- Nicht bearbeiten, während `pytest` läuft — `test_version.py` liest die Datei und schlägt
  sonst scheinbar grundlos fehl.

```json
  {
    "version": "12.7.0",
    "date": "2026-08-15",
    "highlight": false,
    "title": "Fremder Verkehr auf der Karte",
    "items": [
      "✈️ Neue Ebene „Verkehr“ in der Ebenen-Auswahl: Sie zeigt anderen VATSIM-Verkehr im Kartenausschnitt — nicht nur die Friesen. Die Positionen werden zwischen den Meldungen fortgerechnet, die Flugzeuge gleiten also, statt alle 15 Sekunden zu springen. Der Haken schaltet ausschließlich den Fremdverkehr; die Friesen bleiben immer sichtbar.",
      "🏷️ Die Flugzeuge tragen jetzt Muster, Höhe und Geschwindigkeit direkt am Symbol. Wer tief fliegt, zeigt zusätzlich sein Rufzeichen — bei den Friesen steht es immer da. Über 10 000 Fuß wird die Höhe als Flugfläche geschrieben.",
      "🏠 Die Karte geht jetzt über Wangerooge auf statt in der offenen Nordsee."
    ]
  },
```

- [ ] **Schritt 6: Vollständigen Testlauf**

```
python -m pytest tests/ -q
```
Erwartet: alles passed, keine Sammelfehler aus der CHANGELOG-Datei.

- [ ] **Schritt 7: Commit**

```bash
git add README.md docs app/CHANGELOG.json
git commit -m "V12.7.0: Fremder Verkehr auf der Karte"
```

- [ ] **Schritt 8: Vor dem Push fragen**

**Nicht ohne Rückfrage pushen.** Dem Nutzer melden: was drin ist, welche Version, und dass
das Kniebrett-Paket 1.3.0 einen **Sim-Neustart** braucht, damit die Messsonde läuft.

Für die Website gilt: Der Knopf „Neue Version — neu laden" erscheint **bis zu eine Minute**
nach dem Deploy, unten links. Das Tablet zuzuklappen und wieder aufzumachen bewirkt nichts —
diesen Zusatz in Anleitungen und Forumsbeiträgen weglassen.
