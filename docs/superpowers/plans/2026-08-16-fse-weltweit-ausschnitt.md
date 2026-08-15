# FSE weltweit über Ausschnitt-Endpunkte — Implementierungsplan

> **Für agentische Arbeiter:** ERFORDERLICHE UNTER-SKILL: `superpowers:subagent-driven-development`
> (empfohlen) oder `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe umzusetzen.
> Die Schritte nutzen Checkbox-Syntax (`- [ ]`) zur Nachverfolgung.

**Ziel:** Die FSE-Ebenen zeigen den weltweiten Bestand (23.780 Plätze), laden dabei aber weniger
als heute mit Europa — der Browser bekommt nur den sichtbaren Ausschnitt, gedeckelt nach
Zeichenlast.

**Architektur:** Ein neues Servermodul hält beide Weltdateien im Speicher (Zonen vorserialisiert)
und liefert über zwei Endpunkte den Ausschnitt um einen Punkt. Das Frontend ruft nicht bei jeder
Kartenbewegung ab, sondern nach zurückgelegter Strecke, und gleicht die gezeichneten Objekte gegen
die Antwort ab, statt neu zu zeichnen.

**Tech-Stack:** FastAPI (Python 3.11), Vanilla JS + Leaflet 1.9, pytest, Node für Frontend-Tests.

**Spec:** `docs/superpowers/specs/2026-08-16-fse-weltweit-ausschnitt-design.md`

## Global Constraints

- **Der OpenAIP-Key aus `/opt/friesenspy/config.env` gehört nie ins Repo und nie in eine Ausgabe.**
- `app/static/index.html` wird **parallel von einer anderen Sitzung bearbeitet.** Vor jeder
  Änderung `git pull --ff-only`; nur die FSE-Blöcke anfassen, keine Umformatierungen anderswo.
- Bezeichner und Kommentare auf Deutsch, wie im Bestand. Kommentare erklären **warum**, nicht was.
- Deckelwerte exakt: `_FSE_MAX_PUNKTE_PLAETZE = 250`, `_FSE_MAX_PUNKTE_ZONEN = 900`,
  `_FSE_MAX_KM = 250`, `_FSE_MIN_ZOOM = 6`, `_FSE_RAND = 1.25`, `_FSE_NACHLADEN_ANTEIL = 0.25`.
- Der Zonen-Deckel sortiert nach **Abstand des Ausschnitts zur Zonen-Bbox**, nie nach der
  Entfernung zum Flugplatz. (Ozean-Zellen: p99 1.348 km, max 14.127 km Diagonale.)
- Die Endpunkte kommen **nicht** in `_GATE_ALLOW_PREFIXES` — sie verhalten sich wie `/api/traffic`.
- Der Canvas-Renderer `_fseRenderer()` bleibt bestehen und wird nicht ausgebaut.
- Jede Aufgabe endet mit grünem `pytest` und einem Commit.

---

## Dateiübersicht

| Datei | Verantwortung | Aufgabe |
|---|---|---|
| `app/fse.py` (neu) | Weltdaten halten, Ausschnitt filtern, deckeln | 1 |
| `app/main.py` | `lifespan`-Ladeschritt, zwei Endpunkte | 2 |
| `app/static/index.html` | Abruf über Strecke, Abgleich, Diagnose | 3, 4 |
| `tests/test_fse.py` | Server- und Frontend-Tests | 1–5 |
| `README.md`, `docs/*` | Doku nachziehen | 5 |

---

### Task 1: Servermodul `app/fse.py`

**Files:**
- Create: `app/fse.py`
- Test: `tests/test_fse.py` (anfügen)

**Interfaces:**
- Consumes: nichts (reines Modul, keine App-Abhängigkeit)
- Produces:
  - `class FseBestand` mit `plaetze: dict[str, dict]`, `zonen_json: dict[str, str]`,
    `zonen_bbox: dict[str, tuple[float, float, float, float]]`,
    `zonen_punkte: dict[str, int]`
  - `def laden(verzeichnis: Path) -> FseBestand`
  - `def plaetze_im_umkreis(bestand, lat, lon, r_km) -> tuple[dict[str, dict], bool]`
  - `def zonen_im_umkreis(bestand, lat, lon, r_km) -> tuple[list[str], bool]`
    (Liste von ICAOs in Ausgabereihenfolge; das JSON baut Task 2)
  - Konstanten `MAX_PUNKTE_PLAETZE = 250`, `MAX_PUNKTE_ZONEN = 900`, `MAX_KM = 250`

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

An `tests/test_fse.py` anfügen (die Importe `json`, `Path` stehen dort schon):

```python
# ---------------------------------------------------------------------------
# Servermodul app/fse.py — Ausschnitt-Auslieferung (Spec 2026-08-16)
# ---------------------------------------------------------------------------

from app import fse as fse_modul  # noqa: E402

WELT = Path(__file__).resolve().parents[1] / "app" / "data" / "fse"


@pytest.fixture(scope="module")
def bestand():
    return fse_modul.laden(WELT)


def test_laden_liest_beide_weltdateien(bestand):
    assert len(bestand.plaetze) == 23780
    assert len(bestand.zonen_json) == 23780
    assert len(bestand.zonen_bbox) == 23780


def test_zonen_werden_vorserialisiert_gehalten(bestand):
    """Als Python-Objekte kosten beide Dateien 42 MB, die Zonen als fertige JSON-Strings 5 MB
    (gemessen 16.08.2026, Container liegt bei 141 MB). Die Vorserialisierung ist der Grund,
    warum die Antwort per Zeichenketten-Verkettung entsteht — wer hier Listen ablegt, macht
    beides zunichte."""
    probe = bestand.zonen_json["EDWG"]
    assert isinstance(probe, str)
    assert json.loads(probe)[0]           # gültiges JSON, nichtleer
    assert " " not in probe               # kompakt geschrieben


def test_plaetze_im_umkreis_liefert_nur_nahes(bestand):
    treffer, gekappt = fse_modul.plaetze_im_umkreis(bestand, 53.7872, 7.91583, 51)
    assert "EDWG" in treffer
    assert not gekappt
    assert "KJFK" not in treffer
    assert len(treffer) == 14


def test_plaetze_deckel_greift_und_meldet_sich(bestand):
    """New York z9 (123 km): 271 Plätze im Ausschnitt, 250 dürfen raus."""
    treffer, gekappt = fse_modul.plaetze_im_umkreis(bestand, 40.7, -74.0, 123)
    assert len(treffer) == fse_modul.MAX_PUNKTE_PLAETZE
    assert gekappt


def test_zonen_deckel_rechnet_in_punkten_nicht_in_stueck(bestand):
    """Eine Zone kostet ihre Eckenzahl (Mittel 7, max 21), ein Platz genau 1. Bei New York z9
    stehen 2.166 Punkte an, 900 dürfen raus — ein Stückzahl-Deckel würde die falsche Ebene
    schonen (die Zonen stellen dort 88 % der Zeichenlast)."""
    icaos, gekappt = fse_modul.zonen_im_umkreis(bestand, 40.7, -74.0, 123)
    punkte = sum(bestand.zonen_punkte[i] for i in icaos)
    assert punkte <= fse_modul.MAX_PUNKTE_ZONEN
    assert punkte > fse_modul.MAX_PUNKTE_ZONEN - 21   # bis dicht an die Grenze gefüllt
    assert gekappt


def test_ozeanzelle_kommt_mit_egal_wie_gross_sie_ist(bestand):
    """Der Kern der Sortierentscheidung: Voronoi-Zellen über dem Atlantik haben bis zu
    14.127 km Diagonale, ihr Flugplatz liegt womöglich 600 km vom Ausschnitt entfernt. Wer
    nach Flugplatzentfernung sortiert, wirft genau die Zelle weg, in der man steht."""
    icaos, gekappt = fse_modul.zonen_im_umkreis(bestand, 40.0, -40.0, 123)
    assert icaos, "keine Zone mitten im Nordatlantik — die Grosszelle fehlt"
    assert not gekappt
    umschliessend = [
        i for i in icaos
        if bestand.zonen_bbox[i][0] <= 40.0 <= bestand.zonen_bbox[i][1]
        and bestand.zonen_bbox[i][2] <= -40.0 <= bestand.zonen_bbox[i][3]
    ]
    assert umschliessend, "die umschliessende Zelle ist nicht dabei"


def test_ozeanzelle_ueberlebt_auch_einen_vollen_deckel(bestand):
    """Gegenprobe zur Sortierung an einem Ort, wo der Deckel wirklich greift: Auch in New York
    muss die Zelle, die den Ausschnitt umschliesst, unter den ausgelieferten sein — sie hat
    Abstand 0 und steht damit ganz vorn."""
    icaos, gekappt = fse_modul.zonen_im_umkreis(bestand, 40.7, -74.0, 123)
    assert gekappt
    umschliessend = [
        i for i in icaos
        if bestand.zonen_bbox[i][0] <= 40.7 <= bestand.zonen_bbox[i][1]
        and bestand.zonen_bbox[i][2] <= -74.0 <= bestand.zonen_bbox[i][3]
    ]
    assert umschliessend


def test_leerer_ausschnitt_ist_kein_fehler(bestand):
    treffer, gekappt = fse_modul.plaetze_im_umkreis(bestand, 40.0, -40.0, 123)
    assert treffer == {} and not gekappt
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_fse.py -k "bestand or umkreis or ozean or vorserialisiert" -v`
Erwartet: FAIL mit `ModuleNotFoundError: No module named 'app.fse'`

- [ ] **Schritt 3: `app/fse.py` schreiben**

```python
"""FSE-Weltbestand: im Speicher halten und den Kartenausschnitt daraus schneiden.

Warum ein eigenes Modul und keine zwei Funktionen in main.py: Der Bestand ist Zustand mit
eigener Lebensdauer (einmal beim Start gelesen, danach nur gelesen), und die Filterlogik ist
die einzige Stelle im Projekt mit Geometrie-Entscheidungen, die man gegen Messwerte pruefen
will. Beides gehoert nicht zwischen die Endpunkt-Definitionen.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

# Deckel in PUNKTEN, nicht in Stueck: Ein Platz ist ein CircleMarker mit 1 Punkt, eine Zone ein
# Polygon mit im Mittel 7 (max 21). Bei New York z8 stellen die Zonen damit 88 % der
# Zeichenlast -- ein Stueckzahl-Deckel wuerde beide gleich behandeln und die falsche Ebene
# schonen. Die Werte sind gegen Coherent GT gewaehlt (s. main.py: "ab ein paar hundert
# Elementen zaeh") und stehen zur Korrektur, sobald die Panel-Selbstdiagnose Canvas misst.
MAX_PUNKTE_PLAETZE = 250
MAX_PUNKTE_ZONEN = 900
# Obergrenze fuer den angefragten Radius, gespiegelt aus /api/traffic.
MAX_KM = 250

_ERD_KM_JE_GRAD = 111.32


@dataclass
class FseBestand:
    plaetze: dict[str, dict] = field(default_factory=dict)
    # Zonen liegen als FERTIGE JSON-Zeichenketten vor, nicht als Listen: als Python-Objekte
    # kosten beide Dateien 42 MB, so 5 MB (gemessen 16.08.2026 bei 141 MB Containerbedarf).
    # Die Antwort entsteht dadurch per Verkettung statt per Serialisierung je Anfrage.
    zonen_json: dict[str, str] = field(default_factory=dict)
    zonen_bbox: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    zonen_punkte: dict[str, int] = field(default_factory=dict)


def laden(verzeichnis: Path) -> FseBestand:
    plaetze = json.loads((verzeichnis / "fse_airports_world.json").read_text(encoding="utf-8"))
    rohzonen = json.loads((verzeichnis / "fse_zones_world.json").read_text(encoding="utf-8"))
    b = FseBestand(plaetze=plaetze)
    for icao, punkte in rohzonen.items():
        b.zonen_json[icao] = json.dumps(punkte, separators=(",", ":"))
        b.zonen_punkte[icao] = len(punkte)
        breiten = [p[0] for p in punkte]
        laengen = [p[1] for p in punkte]
        b.zonen_bbox[icao] = (min(breiten), max(breiten), min(laengen), max(laengen))
    return b


def _rechteck(lat: float, lon: float, r_km: float) -> tuple[float, float, float, float]:
    """Der Ausschnitt als Bbox. cos(lat) wird nach unten gekappt, sonst wird das Rechteck an
    den Polen unendlich breit."""
    dlat = r_km / _ERD_KM_JE_GRAD
    dlon = r_km / (_ERD_KM_JE_GRAD * max(0.05, math.cos(math.radians(lat))))
    return (lat - dlat, lat + dlat, lon - dlon, lon + dlon)


def _entfernung_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Aequirektangulaere Naeherung. Auf 250 km liegt ihr Fehler unter einem Promille, und
    gebraucht wird sie nur zum Sortieren und Kappen -- Haversine waere hier Rechenzeit ohne
    Wirkung."""
    dlat = (lat2 - lat1) * _ERD_KM_JE_GRAD
    dlon = (lon2 - lon1) * _ERD_KM_JE_GRAD * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def plaetze_im_umkreis(
    bestand: FseBestand, lat: float, lon: float, r_km: float
) -> tuple[dict[str, dict], bool]:
    r_km = min(r_km, MAX_KM)
    la0, la1, lo0, lo1 = _rechteck(lat, lon, r_km)
    nah: list[tuple[float, str]] = []
    for icao, a in bestand.plaetze.items():
        if la0 <= a["lat"] <= la1 and lo0 <= a["lon"] <= lo1:
            nah.append((_entfernung_km(lat, lon, a["lat"], a["lon"]), icao))
    gekappt = len(nah) > MAX_PUNKTE_PLAETZE
    if gekappt:
        nah.sort()
        nah = nah[:MAX_PUNKTE_PLAETZE]
    return {icao: bestand.plaetze[icao] for _, icao in nah}, gekappt


def _bbox_abstand_km(
    bbox: tuple[float, float, float, float], lat: float, lon: float, r_km: float
) -> float:
    """Abstand des ANGEFRAGTEN AUSSCHNITTS zur Zonen-Bbox, nicht zum Flugplatz der Zone.

    Das ist die tragende Entscheidung dieses Moduls: Voronoi-Zellen ueber dem Ozean haben bis
    zu 14.127 km Diagonale (p99: 1.348 km), ihr Flugplatz kann Hunderte Kilometer ausserhalb
    des Bildes liegen. Nach Flugplatzentfernung sortiert fiele ausgerechnet die Zelle als
    Erstes aus dem Deckel, in der man gerade steht. Was den Ausschnitt umschliesst oder
    schneidet, hat hier Abstand 0 und steht damit ganz vorn.
    """
    la0, la1, lo0, lo1 = _rechteck(lat, lon, r_km)
    dlat = max(bbox[0] - la1, la0 - bbox[1], 0.0)
    dlon = max(bbox[2] - lo1, lo0 - bbox[3], 0.0)
    return math.hypot(
        dlat * _ERD_KM_JE_GRAD,
        dlon * _ERD_KM_JE_GRAD * math.cos(math.radians(lat)),
    )


def zonen_im_umkreis(
    bestand: FseBestand, lat: float, lon: float, r_km: float
) -> tuple[list[str], bool]:
    r_km = min(r_km, MAX_KM)
    la0, la1, lo0, lo1 = _rechteck(lat, lon, r_km)
    treffer: list[tuple[float, str]] = []
    for icao, bb in bestand.zonen_bbox.items():
        # Reiner Bbox-Schnitt, kein exakter Polygontest: gemessen liefert er bei Wangerooge
        # 90 von 90 und bei New York 389 von 389 identisch, im Nordatlantik eine Zone weniger.
        # Der Test kostet CPU je Anfrage und spart eine Zone.
        if bb[1] < la0 or bb[0] > la1 or bb[3] < lo0 or bb[2] > lo1:
            continue
        treffer.append((_bbox_abstand_km(bb, lat, lon, r_km), icao))
    treffer.sort()
    ausgabe: list[str] = []
    punkte = 0
    gekappt = False
    for _, icao in treffer:
        kosten = bestand.zonen_punkte[icao]
        if punkte + kosten > MAX_PUNKTE_ZONEN:
            gekappt = True
            # Nicht abbrechen: Eine grosse Zelle mitten in der Liste darf nicht alle
            # kleineren dahinter mitreissen. Das Budget wird weiter aufgefuellt.
            continue
        ausgabe.append(icao)
        punkte += kosten
    return ausgabe, gekappt
```

- [ ] **Schritt 4: Test laufen lassen, Erfolg bestätigen**

Run: `python -m pytest tests/test_fse.py -v`
Erwartet: PASS (auch die bestehenden Tests bleiben grün — Task 5 räumt sie auf, nicht diese)

- [ ] **Schritt 5: Commit**

```bash
git add app/fse.py tests/test_fse.py
git commit -m "FSE-Weltbestand: Modul zum Halten und Ausschneiden"
```

---

### Task 2: Die zwei Endpunkte

**Files:**
- Modify: `app/main.py` (`lifespan` ab Zeile 210; neue Endpunkte in der Nähe von `/api/traffic`, Zeile 673)
- Test: `tests/test_fse.py` (anfügen)

**Interfaces:**
- Consumes: `app.fse.laden`, `plaetze_im_umkreis`, `zonen_im_umkreis`, `MAX_KM` aus Task 1
- Produces:
  - `app.state.fse: FseBestand`
  - `GET /api/fse/airports?lat=&lon=&r=` → `{"plaetze": {...}, "gekappt": bool}`
  - `GET /api/fse/zones?lat=&lon=&r=` → `{"zonen": {...}, "gekappt": bool}`

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

An `tests/test_fse.py` anfügen:

```python
from fastapi.testclient import TestClient  # noqa: E402


def test_endpunkt_plaetze_liefert_den_ausschnitt(client: TestClient):
    r = client.get("/api/fse/airports", params={"lat": 53.7872, "lon": 7.91583, "r": 51})
    assert r.status_code == 200
    d = r.json()
    assert "EDWG" in d["plaetze"]
    assert d["gekappt"] is False
    assert d["plaetze"]["EDWG"]["name"]


def test_endpunkt_zonen_liefert_gueltiges_json(client: TestClient):
    """Die Antwort entsteht aus vorserialisierten Stuecken per Zeichenketten-Verkettung —
    genau dort entstehen kaputte Kommata. Deshalb wird hier geparst, nicht nur der Status
    geprueft."""
    r = client.get("/api/fse/zones", params={"lat": 53.7872, "lon": 7.91583, "r": 51})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    d = r.json()
    assert "EDWG" in d["zonen"]
    assert isinstance(d["zonen"]["EDWG"][0], list)
    assert len(d["zonen"]["EDWG"][0]) == 2


def test_endpunkt_zonen_bleibt_gueltig_wenn_nur_eine_zone_kommt(client: TestClient):
    """Ein-Element-Fall der Verkettung: hier faellt ein Trennzeichen zu viel oder zu wenig auf."""
    r = client.get("/api/fse/zones", params={"lat": 40.0, "lon": -40.0, "r": 123})
    assert r.status_code == 200
    d = r.json()
    assert len(d["zonen"]) >= 1


def test_endpunkt_zonen_bleibt_gueltig_wenn_gar_nichts_kommt(client: TestClient):
    r = client.get("/api/fse/zones", params={"lat": -75.0, "lon": 0.0, "r": 5})
    assert r.status_code == 200
    assert r.json()["zonen"] == {}


def test_endpunkte_weisen_unsinnige_parameter_ab(client: TestClient):
    for params in ({"lat": 91, "lon": 0, "r": 10},
                   {"lat": 0, "lon": 181, "r": 10},
                   {"lat": 0, "lon": 0, "r": 0},
                   {"lat": 0, "lon": 0, "r": 251}):
        assert client.get("/api/fse/airports", params=params).status_code == 422
        assert client.get("/api/fse/zones", params=params).status_code == 422


def test_endpunkt_meldet_die_kappung(client: TestClient):
    r = client.get("/api/fse/airports", params={"lat": 40.7, "lon": -74.0, "r": 123})
    d = r.json()
    assert d["gekappt"] is True
    assert len(d["plaetze"]) == 250


def test_fse_endpunkte_stehen_nicht_im_gate_allowlist():
    """Wie /api/traffic: kein Sonderweg an der Anmeldung vorbei."""
    quelle = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    stelle = quelle.index("_GATE_ALLOW_PREFIXES")
    block = quelle[stelle:quelle.index("\n\n", stelle)]
    assert "/api/fse" not in block
```

> **Hinweis für den Umsetzenden:** Ob es die Fixture `client` in `tests/conftest.py` schon gibt,
> vor dem Schreiben prüfen (`grep -n "def client" tests/conftest.py`). Falls ja, diese benutzen.
> Falls nein, eine modulweite Fixture in `tests/test_fse.py` anlegen:
> ```python
> @pytest.fixture(scope="module")
> def client():
>     from app.main import app
>     with TestClient(app) as c:
>         yield c
> ```
> Der `with`-Block ist Pflicht — nur er löst `lifespan` aus, und ohne den ist `app.state.fse` leer.

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_fse.py -k endpunkt -v`
Erwartet: FAIL mit 404 auf `/api/fse/airports`

- [ ] **Schritt 3a: Ladeschritt in `lifespan` (`app/main.py`, nach `geo.set_custom_airports(...)`)**

```python
    # FSE-Weltbestand einmal beim Start lesen (23.780 Plaetze + Zonen). Danach nur noch
    # gelesen, deshalb ohne Sperre. Der Pfad ist relativ zum Arbeitsverzeichnis, so wie der
    # StaticFiles-Mount weiter unten -- im Container ist das /opt/friesenspy.
    app.state.fse = fse.laden(Path("app/data/fse"))
    _logger.info("FSE-Bestand geladen: %d Plaetze", len(app.state.fse.plaetze))
```

Dazu oben `from app import fse` und `from pathlib import Path` ergänzen (prüfen, ob `Path`
schon importiert ist).

- [ ] **Schritt 3b: Die Endpunkte (`app/main.py`, direkt nach `get_traffic`)**

```python
@app.get("/api/fse/airports")
async def get_fse_airports(
    request: Request,
    lat: float = Query(..., ge=-90, le=90, description="Bezugspunkt, i. d. R. die Kartenmitte"),
    lon: float = Query(..., ge=-180, le=180),
    r: float = Query(50.0, ge=1, le=fse.MAX_KM, description="Radius in km"),
):
    """FSE-Plaetze im Kartenausschnitt.

    Getrennt von den Zonen, weil beide Ebenen einzeln schaltbar sind: Wer nur die
    Landeflaechen anhat, soll die Plaetze nicht mitladen. (Der Vorgaenger `_fseLaden` holte
    immer beide Dateien, unabhaengig davon, welcher Haken gesetzt war.)

    ``gekappt`` meldet, dass der Deckel gegriffen hat und der Nutzer eine Scheibe statt des
    vollen Rechtecks sieht -- dieselbe Entscheidung wie beim Verkehr, aus demselben Grund.

    Kein Sonderweg bei der Anmeldung: verhaelt sich wie ``/api/traffic`` und gehoert NICHT in
    ``_GATE_ALLOW_PREFIXES``.
    """
    bestand = request.app.state.fse
    plaetze, gekappt = fse.plaetze_im_umkreis(bestand, lat, lon, r)
    return {"plaetze": plaetze, "gekappt": gekappt}


@app.get("/api/fse/zones")
async def get_fse_zones(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    r: float = Query(50.0, ge=1, le=fse.MAX_KM, description="Radius in km"),
):
    """FSE-Landeflaechen im Kartenausschnitt.

    Die Antwort wird aus den vorserialisierten Stuecken ZUSAMMENGESETZT statt serialisiert --
    sonst waere die Vorserialisierung im Modul wirkungslos und der Server baute je Anfrage
    dieselben Listen wieder auf, die er beim Start bewusst nicht behalten hat.
    """
    bestand = request.app.state.fse
    icaos, gekappt = fse.zonen_im_umkreis(bestand, lat, lon, r)
    teile = ",".join(
        json.dumps(icao) + ":" + bestand.zonen_json[icao] for icao in icaos
    )
    rumpf = '{"zonen":{' + teile + '},"gekappt":' + ("true" if gekappt else "false") + "}"
    return Response(content=rumpf, media_type="application/json")
```

`Response` aus `fastapi` und `json` müssen importiert sein — vor dem Schreiben prüfen.

- [ ] **Schritt 4: Test laufen lassen, Erfolg bestätigen**

Run: `python -m pytest tests/test_fse.py -v`
Erwartet: PASS

- [ ] **Schritt 5: Commit**

```bash
git add app/main.py tests/test_fse.py
git commit -m "Zwei Endpunkte fuer den FSE-Kartenausschnitt"
```

---

### Task 3: Frontend — Abruf über Strecke, Abgleich statt Neuzeichnen

**Files:**
- Modify: `app/static/index.html` (FSE-Block ab Zeile ~4080)
- Test: `tests/test_fse.py` (anfügen, Node-Muster wie `test_addPreferredFseLayer_...`)

**Interfaces:**
- Consumes: `/api/fse/airports`, `/api/fse/zones` aus Task 2
- Produces: `_fseAbrufen(map)`, `_fseAbgleichen(gruppe, tabelle, neu, bauen)`,
  `_fsePlaetzeTabelle`, `_fseZonenTabelle`

**Achtung:** Diese Datei wird parallel bearbeitet. Vor dem Start `git pull --ff-only`.

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

```python
def test_frontend_ruft_nicht_bei_jeder_bewegung_ab():
    """Kernkorrektur gegenueber der Uebergabeskizze: `moveend` mit `!_naviSelbstBewegt` (so
    macht es der Verkehr, index.html:4570) waere hier ein Fehler. Bei eingeschalteter Moving
    Map bewegt die Karte sich SELBST, die Wache greift also immer -- und anders als der
    Verkehr hat die FSE-Ebene keinen Takt als zweite Quelle. Sie wuerde im Kniebrett waehrend
    des ganzen Fluges nie nachladen.

    Der Auslöser ist deshalb die zurueckgelegte Strecke. Hier in Node geprueft, weil ein
    String-Test die Bedingung nicht auswerten kann."""
    start = INDEX.index("const _FSE_RAND")
    ende_start = INDEX.index("function _fseAbgleichen(")
    ende = INDEX.index("\n}", ende_start) + len("\n}")
    quelltext = INDEX[start:ende]
    # Harness stellt fetch, L und eine bewegliche Karte bereit; Treiber prueft:
    #  - z5 (< _FSE_MIN_ZOOM): kein fetch
    #  - z10, erster Aufruf: fetch
    #  - Mitte um 0,1 * r verschoben: KEIN zweiter fetch
    #  - Mitte um 0,3 * r verschoben: zweiter fetch
    #  - Zoomwechsel ohne Bewegung: fetch
    ...


def test_frontend_zeichnet_unveraenderte_plaetze_nicht_neu():
    """Der Abgleich ist der Grund, warum die permanenten ICAO-Beschriftungen beim Fliegen
    nicht flackern: Ein ICAO, der in zwei aufeinanderfolgenden Antworten steht, muss
    UNANGETASTET bleiben -- nicht entfernt und neu gezeichnet."""
    ...


def test_frontend_entfernt_was_aus_dem_ausschnitt_faellt():
    ...


def test_frontend_holt_mit_rand():
    """Abgerufen wird 1,25 x Sichtradius. Der Rand deckt genau die Strecke ab, die bis zum
    naechsten Abruf (ein Viertel Radius) zurueckgelegt wird -- ohne ihn haette der sichtbare
    Bereich in Flugrichtung ein Loch."""
    assert re.search(r"_FSE_RAND\s*=\s*1\.25", INDEX)
    assert re.search(r"_FSE_NACHLADEN_ANTEIL\s*=\s*0\.25", INDEX)
```

> **Hinweis:** Die drei mit `...` markierten Tests sind nach dem Muster von
> `test_addPreferredFseLayer_haengt_beide_gruppen_ein_und_zwingt_zonen_nach_hinten`
> (`tests/test_fse.py:167`) auszuformulieren: Quelltext per `INDEX.index(...)` ausschneiden,
> Leaflet-/fetch-Attrappe als `harness` davorsetzen, Treiber dahinter, mit `subprocess.run([_NODE, "-e", skript])`
> ausführen und auf `"OK" in stdout` prüfen. Die Attrappe muss `fetch` mitzählen (Aufrufliste
> mit URL) und `map.getCenter()`/`map.getZoom()`/`map.getBounds()` beweglich halten.

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_fse.py -k frontend -v`
Erwartet: FAIL — `_FSE_RAND` steht nicht in `index.html`

- [ ] **Schritt 3: Den FSE-Block umbauen**

Ersetzen: die beiden `_FSE_*_URL`-Konstanten, `_fseGeladen` und `_fseLaden`.

```js
// Nicht mehr zwei statische Dateien, sondern der Ausschnitt: Der Weltbestand (23.780 Plaetze)
// liegt im Server, der Browser bekommt nur, was im Bild ist -- gedeckelt nach Zeichenlast,
// nicht nach Stueckzahl (s. app/fse.py und die Spec vom 16.08.2026).
const _FSE_PLAETZE_API = '/api/fse/airports';
const _FSE_ZONEN_API   = '/api/fse/zones';
// Darunter macht die serverseitige Kappung von r auf 250 km aus jeder Antwort einen Punkt in
// der Mitte einer Kontinentansicht -- eine Anfrage ohne Aussage. Kein Dichteregler: die
// Dichte regelt das Punktebudget im Server, und zwar ortsabhaengig.
const _FSE_MIN_ZOOM = 6;
// Abgerufen wird mehr, als zu sehen ist. Der Rand deckt genau die Strecke ab, die bis zum
// naechsten Abruf zurueckgelegt wird -- sonst hat der sichtbare Bereich in Flugrichtung ein
// Loch, das erst der uebernaechste Abruf schliesst.
const _FSE_RAND = 1.25;
// Ausgeloest wird NICHT bei jeder Kartenbewegung. Der naheliegende Weg -- moveend mit
// !_naviSelbstBewegt, so wie der Verkehr es macht -- waere hier ein Fehler: Bei
// eingeschalteter Moving Map bewegt die Karte sich selbst, die Wache greift also immer. Der
// Verkehr uebersteht das, weil sein 15-Sekunden-Takt als zweite Quelle laeuft; diese Ebene
// hat keinen Takt (die Daten aendern sich nie) und wuerde im Kniebrett waehrend des ganzen
// Fluges nicht ein einziges Mal nachladen.
const _FSE_NACHLADEN_ANTEIL = 0.25;

// ICAO -> gezeichnetes Objekt, je Ebene. Grundlage des Abgleichs: Was in zwei
// aufeinanderfolgenden Antworten steht, bleibt unangetastet -- sonst flackern die permanenten
// ICAO-Beschriftungen bei jedem Nachladen im Flug.
const _fsePlaetzeTabelle = new Map();
const _fseZonenTabelle   = new Map();
let _fseLetzteMitte = null;
let _fseLetzterZoom = null;
let _fseLetzterRadius = 0;

// Radius so, dass der sichtbare Ausschnitt abgedeckt ist: Mitte bis Ecke, mal Rand.
function _fseRadiusKm(map) {
  const km = map.getCenter().distanceTo(map.getBounds().getNorthEast()) / 1000;
  return Math.max(1, Math.min(250, Math.round(km * _FSE_RAND)));
}

function _fseAbgleichen(gruppe, tabelle, neu, bauen) {
  for (const schluessel in neu) {
    if (tabelle.has(schluessel)) continue;
    const l = bauen(schluessel, neu[schluessel]);
    tabelle.set(schluessel, l);
    l.addTo(gruppe);
  }
  for (const schluessel of Array.from(tabelle.keys())) {
    if (schluessel in neu) continue;
    gruppe.removeLayer(tabelle.get(schluessel));
    tabelle.delete(schluessel);
  }
}

function _fseLeeren() {
  _fsePlaetzeGruppe.clearLayers(); _fsePlaetzeTabelle.clear();
  _fseZonenGruppe.clearLayers();   _fseZonenTabelle.clear();
  _fseLetzteMitte = null; _fseLetzterZoom = null;
}

function _fseAbrufen(map) {
  const plaetzeAn = map.hasLayer(_fsePlaetzeGruppe);
  const zonenAn   = map.hasLayer(_fseZonenGruppe);
  if (!plaetzeAn && !zonenAn) return;
  // Ein Abruf auf einer verdeckten Karte ist Arbeit ohne Wirkung (derselbe Grund wie beim
  // Verkehr, s. _verkehrAbrufen).
  if (!_istSichtbar(map.getContainer())) return;
  if (map.getZoom() < _FSE_MIN_ZOOM) { _fseLeeren(); return; }

  const mitte = map.getCenter();
  const radius = _fseRadiusKm(map);
  const zoom = map.getZoom();
  if (_fseLetzteMitte && zoom === _fseLetzterZoom) {
    const gewandert = mitte.distanceTo(_fseLetzteMitte) / 1000;
    if (gewandert < _fseLetzterRadius * _FSE_NACHLADEN_ANTEIL) return;
  }
  _fseLetzteMitte = mitte; _fseLetzterZoom = zoom; _fseLetzterRadius = radius;

  const frage = '?lat=' + mitte.lat.toFixed(4) + '&lon=' + mitte.lng.toFixed(4) + '&r=' + radius;
  // Zonen ZUERST anfordern: Beim allerersten Zeichnen ergibt sich die Stapelung
  // Kulisse-unter-Markern aus der Reihenfolge im overlayPane (s. den langen Kommentar am
  // frueheren _fseLaden -- bringToBack() auf einer leeren Gruppe war ein No-Op).
  if (zonenAn) {
    fetch(_FSE_ZONEN_API + frage)
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d) _fseAbgleichen(_fseZonenGruppe, _fseZonenTabelle, d.zonen, _fseZoneBauen); })
      .catch(() => {});   // Netz weg (im Kniebrett keine Seltenheit): beim naechsten Zug wieder
  }
  if (plaetzeAn) {
    fetch(_FSE_PLAETZE_API + frage)
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d) _fseAbgleichen(_fsePlaetzeGruppe, _fsePlaetzeTabelle, d.plaetze, _fsePlatzBauen); })
      .catch(() => {});
  }
}
```

`_fseZonenZeichnen` und `_fsePlaetzeZeichnen` werden zu Bau-Funktionen für **ein** Objekt
umgestellt (der Rumpf bleibt inhaltlich gleich, nur die Schleife fällt weg und `addTo` entfällt
— das macht `_fseAbgleichen`):

```js
function _fseZoneBauen(icao, punkte) {
  return L.polyline(punkte, {
    weight: 1, color: '#888', opacity: 0.5, interactive: false, fill: false,
    renderer: _fseRenderer(),
  });
}

function _fsePlatzBauen(icao, a) {
  const m = L.circleMarker([a.lat, a.lon], {
    radius: 5, weight: 6, opacity: 0.2, color: '#d8a45e', fillColor: '#d8a45e', fillOpacity: 0.85,
    renderer: _fseRenderer(),
  });
  m._icao = icao;
  return m.bindPopup(_fsePopup(icao, a));
}
```

In `_addPreferredFseLayer` jedes `_fseLaden()` durch `_fseAbrufen(map)` ersetzen, und bei
`overlayremove` die jeweilige Tabelle leeren:

```js
    if (e.layer === _fsePlaetzeGruppe) {
      _saveFsePref(_FSE_PLAETZE_PREF_KEY, false); _fseAttributionAus(map);
      _fsePlaetzeGruppe.clearLayers(); _fsePlaetzeTabelle.clear();
    }
```
(analog für die Zonen). Zusätzlich einmal registrieren:

```js
  map.on('moveend zoomend', () => _fseAbrufen(map));
```

Die Wache prüft selbst, ob genug Strecke liegt — deshalb ohne `_naviSelbstBewegt` und ohne
Drossel-Timer.

- [ ] **Schritt 4: Test laufen lassen, Erfolg bestätigen**

Run: `python -m pytest tests/test_fse.py -v`
Erwartet: PASS

- [ ] **Schritt 5: Commit**

```bash
git add app/static/index.html tests/test_fse.py
git commit -m "FSE-Ebenen holen den Ausschnitt statt der ganzen Datei"
```

---

### Task 4: Canvas in der Panel-Selbstdiagnose

**Files:**
- Modify: `app/static/index.html` (Diagnoseblock, `probeSprites` bei Zeile ~408)
- Test: `tests/test_fse.py` (anfügen)

**Interfaces:**
- Consumes: nichts
- Produces: Feld `canvas` im Diagnosebericht mit `{kontext: bool, zeichnet: bool}`

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

```python
def test_diagnose_misst_canvas():
    """docs/efb-panel-debugging.md: 'Ein in Chrome geprueftes Fix ist nicht verifiziert,
    solange er nicht im Panel gemessen wurde.' Der Canvas-Renderer der FSE-Ebenen laeuft seit
    dem 15.08.2026 produktiv und ist in Coherent GT nie gemessen worden -- die Selbstdiagnose
    prueft CSS, Glyphen, Sprites und Kacheln, aber kein Canvas.

    Gemessen wird der INHALT, nicht der Rahmen: Ein <canvas> existiert immer und hat immer
    Masse. Genau daran war die fruehere Sprite-Messung gescheitert (sie mass die Groesse des
    <svg> statt der Zeichnung, s. den Kommentar bei probeSprites)."""
    assert "base.canvas = probeCanvas()" in INDEX
    stelle = INDEX.index("function probeCanvas(")
    rumpf = INDEX[stelle:INDEX.index("\n      }", stelle)]
    assert "getContext" in rumpf
    assert "getImageData" in rumpf, "ohne Pixelpruefung misst der Test nur den Rahmen"
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_fse.py -k diagnose -v`
Erwartet: FAIL mit `ValueError: substring not found`

- [ ] **Schritt 3: `probeCanvas` schreiben und einhängen**

Neben `probeSprites` einfügen:

```js
      // Der Canvas-Renderer traegt beide FSE-Ebenen und die Platzrunden. Ob Coherent GT
      // wirklich zeichnet, ist nie gemessen worden -- und die Lehre aus probeSprites lautet,
      // den INHALT zu pruefen und nicht den Rahmen: Ein <canvas> hat seine Masse immer, auch
      // wenn nichts darin ankommt.
      function probeCanvas() {
        var c = document.createElement('canvas');
        c.width = 8; c.height = 8;
        var ctx = c.getContext && c.getContext('2d');
        if (!ctx) return { kontext: false, zeichnet: false };
        ctx.fillStyle = '#ff0000';
        ctx.fillRect(1, 1, 6, 6);
        var gesetzt = false;
        try {
          var d = ctx.getImageData(4, 4, 1, 1).data;
          gesetzt = d[0] > 200 && d[3] > 200;
        } catch (err) {
          return { kontext: true, zeichnet: false, fehler: String(err) };
        }
        return { kontext: true, zeichnet: gesetzt };
      }
```

Und in den Bericht (neben den anderen `try`-Zeilen):

```js
        try { base.canvas = probeCanvas(); } catch (err) { base.canvas = { error: String(err) }; }
```

- [ ] **Schritt 4: Test laufen lassen, Erfolg bestätigen**

Run: `python -m pytest tests/test_fse.py -v`
Erwartet: PASS

- [ ] **Schritt 5: Commit**

```bash
git add app/static/index.html tests/test_fse.py
git commit -m "Panel-Selbstdiagnose misst, ob Canvas in Coherent GT zeichnet"
```

---

### Task 5: Aufräumen und Doku

**Files:**
- Delete: `app/static/data/fse_airports_eu.json`, `app/static/data/fse_zones_eu.json`,
  `scripts/fse_zuschnitt.py`
- Modify: `tests/test_fse.py` (die Tests gegen die gelöschten Dateien), `README.md`,
  `docs/api.md`, `docs/architecture.md`, `docs/fse-daten-weltweit.md`, `app/CHANGELOG.json`

- [ ] **Schritt 1: Die Tests gegen die gelöschten Dateien entfernen oder umhängen**

Betroffen sind (aktuelle Zeilennummern, vor dem Ändern gegenprüfen):
`test_dateien_liegen_im_repo` (16), `test_europa_zuschnitt_ist_klein_genug` (20),
`test_plaetze_liegen_in_europa` (27), `test_msfs_feld_ist_bereinigt` (35),
`test_die_inseln_sind_dabei` (45), `test_belag_stimmt_gegen_echte_plaetze` (76),
`test_fse_daten_werden_lazy_geholt` (116).

Regel: Was die **Daten** prüft (`msfs`-Feld, Inseln, Belag), auf die Weltdateien umhängen und
behalten — das sind echte Datenprüfungen. Was den **Europa-Zuschnitt** prüft
(`test_europa_zuschnitt_ist_klein_genug`, `test_plaetze_liegen_in_europa`), ersatzlos löschen.
`test_fse_daten_werden_lazy_geholt` prüft auf `_fseLaden` und wird durch die Tests aus Task 3
ersetzt.

- [ ] **Schritt 2: Test laufen lassen**

Run: `python -m pytest tests/test_fse.py -v`
Erwartet: PASS, kein Test verweist mehr auf `app/static/data/fse_*_eu.json`

- [ ] **Schritt 3: Dateien löschen**

```bash
git rm app/static/data/fse_airports_eu.json app/static/data/fse_zones_eu.json scripts/fse_zuschnitt.py
```

- [ ] **Schritt 4: Doku nachziehen**

- `README.md`: „rund 2 300 europäischen Plätzen" → „23.780 Plätzen weltweit"; ergänzen, dass
  nur der Kartenausschnitt geladen wird
- `docs/api.md`: die zwei Endpunkte mit Parametern, Antwortform und dem Hinweis auf `gekappt`
- `docs/architecture.md`: `app/fse.py`, die Speicherhaltung (42 MB → 5 MB durch
  Vorserialisierung), die Deckelwerte
- `docs/fse-daten-weltweit.md`: Abschnitt „Was noch fehlt" durch einen Verweis auf die Spec und
  „umgesetzt am 16.08.2026" ersetzen; der Rest des Dokuments bleibt
- `app/CHANGELOG.json`: neuer Eintrag

- [ ] **Schritt 5: Voller Testlauf und Commit**

Run: `python -m pytest -q`
Erwartet: alle Tests grün

```bash
git add -A
git commit -m "FSE-Europadateien und Zuschnitt-Skript raus, Doku auf weltweit"
```

---

## Selbstprüfung des Plans

**Spec-Abdeckung:** §2 Bezugspunkt → Task 3 (`_fseRadiusKm` aus `map.getCenter()`). §3
Punktebudget → Task 1. §4 Servermodul → Task 1. §5 Endpunkte → Task 2. §6 Frontend → Task 3.
§7 Canvas-Diagnose → Task 4. §8 Aufräumen → Task 5. §9 Tests → verteilt über 1–4. §10
Verworfenes → als Kommentare in `app/fse.py` und `index.html` festgehalten, damit niemand die
Wege noch einmal geht.

**Platzhalter:** Die drei mit `...` markierten Node-Tests in Task 3 sind bewusst als Muster
plus Prüfliste beschrieben statt ausgeschrieben — das Harness-Gerüst ist 120 Zeilen und steht
wörtlich in `tests/test_fse.py:167`. Der Umsetzende bekommt Fundstelle, Prüfpunkte und
Ausführungsmuster; alles andere wäre Abschrift.

**Typkonsistenz:** `zonen_im_umkreis` gibt eine **Liste von ICAOs** zurück (nicht das JSON) —
Task 2 baut daraus die Antwort und braucht dafür `bestand.zonen_json`. `plaetze_im_umkreis`
gibt dagegen ein fertiges **Dict** zurück, weil dort nicht vorserialisiert wird. Diese
Asymmetrie ist beabsichtigt und in beiden Signaturen sichtbar.

**Bekannte Bruchstelle:** Task 3 ändert `app/static/index.html`, das eine andere Sitzung
parallel bearbeitet. Vor Task 3 zwingend `git pull --ff-only`.
