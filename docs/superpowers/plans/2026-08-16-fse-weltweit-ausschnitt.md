# FSE weltweit über Ausschnitt-Endpunkte — Implementierungsplan

> **Für agentische Arbeiter:** ERFORDERLICHE UNTER-SKILL: `superpowers:subagent-driven-development`
> (empfohlen) oder `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe umzusetzen.
> Die Schritte nutzen Checkbox-Syntax (`- [ ]`) zur Nachverfolgung.

**Goal:** Die FSE-Ebenen zeigen den weltweiten Bestand (23.780 Plätze), laden dabei aber weniger
als heute mit Europa — der Browser bekommt nur den sichtbaren Ausschnitt, gedeckelt nach
Zeichenlast.

**Architecture:** Ein neues Servermodul hält beide Weltdateien im Speicher und liefert über zwei
Endpunkte den Ausschnitt um einen Punkt. Das Frontend ruft nicht bei jeder Kartenbewegung ab,
sondern nach zurückgelegter Strecke, und gleicht die gezeichneten Objekte gegen die Antwort ab,
statt neu zu zeichnen.

**Tech Stack:** FastAPI (Python 3.11), Vanilla JS + Leaflet 1.9.4, pytest, Node für Frontend-Tests.

**Spec:** `docs/superpowers/specs/2026-08-16-fse-weltweit-ausschnitt-design.md`

## Global Constraints

- **Der OpenAIP-Key aus `/opt/friesenspy/config.env` gehört nie ins Repo und nie in eine Ausgabe.**
- `app/static/index.html` wird **parallel von einer anderen Sitzung bearbeitet.** Vor jeder
  Änderung `git pull --ff-only`; nur die FSE-Blöcke anfassen, keine Umformatierungen anderswo.
- Bezeichner und Kommentare auf Deutsch, wie im Bestand. Kommentare erklären **warum**, nicht was.
- Exakte Werte: `MAX_PUNKTE_PLAETZE = 250`, `MAX_PUNKTE_ZONEN = 900`, `MAX_KM = 250` (in
  `app/fse.py`); `_FSE_MAX_KM = 250`, `_FSE_MIN_ZOOM = 6`, `_FSE_RAND = 1.25`,
  `_FSE_NACHLADEN_ANTEIL = 0.2` (in `index.html`).
- Der Zonen-Deckel sortiert nach **Abstand des Ausschnitts zur Zonen-Bbox**, nie nach der
  Entfernung zum Flugplatz.
- **Keine Vorserialisierung der Zonen** und **kein handgebauter JSON-Rumpf** — beides wurde
  gemessen verworfen (Spec §4). Antworten sind gewöhnliche Dicts.
- **Längen werden nicht pauschal auf ±180 normalisiert.** Nur die Zweig-Korrektur je Polygon
  (Spec §4) — pauschales Normalisieren machte aus 34 heilen Zonen Bänder.
- Beide Endpunkte sind `def`, **nicht** `async def` (10–14 ms je Anfragepaar blockierten sonst
  den Event-Loop samt `/api/sse`).
- Die Endpunkte kommen **nicht** in `_GATE_ALLOW_PREFIXES`.
- Der Canvas-Renderer `_fseRenderer()` bleibt bestehen und wird nicht ausgebaut.
- Jede Aufgabe endet mit **vollständig grünem** `python -m pytest tests/test_fse.py` und einem Commit.

---

## Dateiübersicht

| Datei | Verantwortung | Aufgabe |
|---|---|---|
| `app/fse.py` (neu) | Weltdaten halten, Ausschnitt filtern, deckeln | 1 |
| `app/main.py` | `lifespan`-Ladeschritt, zwei Endpunkte | 2 |
| `app/static/index.html` | Abruf über Strecke, Abgleich, Diagnose | 3, 4 |
| `tests/test_fse.py` | Server- und Frontend-Tests | 1–5 |
| `README.md`, `docs/*`, `app/CHANGELOG.json` | Doku nachziehen | 5 |

---

### Task 1: Servermodul `app/fse.py`

**Files:**
- Create: `app/fse.py`
- Test: `tests/test_fse.py` (anfügen)

**Interfaces:**
- Consumes: nichts (reines Modul, keine App-Abhängigkeit)
- Produces:
  - `class FseBestand` mit `plaetze: dict[str, dict]`, `zonen: dict[str, list]`,
    `zonen_bbox: dict[str, tuple[float, float, float, float]]`
  - `def laden(verzeichnis: Path) -> FseBestand`
  - `def plaetze_im_umkreis(bestand, lat, lon, r_km) -> tuple[dict[str, dict], bool]`
  - `def zonen_im_umkreis(bestand, lat, lon, r_km) -> tuple[dict[str, list], bool]`
  - Konstanten `MAX_PUNKTE_PLAETZE = 250`, `MAX_PUNKTE_ZONEN = 900`, `MAX_KM = 250`

**Beide Filter geben fertige Dicts zurück.** Die Asymmetrie des Vorentwurfs (Zonen als
ICAO-Liste) entfiel mit der Vorserialisierung.

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

An `tests/test_fse.py` anfügen (`json`, `Path`, `pytest` stehen dort schon):

```python
# ---------------------------------------------------------------------------
# Servermodul app/fse.py — Ausschnitt-Auslieferung (Spec 2026-08-16)
# ---------------------------------------------------------------------------

from app import fse as fse_modul  # noqa: E402

WELT = Path(__file__).resolve().parents[1] / "app" / "data" / "fse"

# Messpunkte (16.08.2026 gegen die echten Weltdateien nachgerechnet). Die Radien sind die
# Halbdiagonalen eines 900x700-Panels auf der jeweiligen BREITE -- dieselbe Zoomstufe deckt
# auf 40,7 N mehr Kilometer ab als auf 53,8 N. Ein gemeinsamer Kilometerwert fuer beide Orte
# waere falsch (der Fehler stand in der ersten Fassung dieses Plans).
EDWG = (53.7872, 7.91583)
KJFK = (40.7, -74.0)
ATLANTIK = (40.0, -40.0)


@pytest.fixture(scope="module")
def bestand():
    return fse_modul.laden(WELT)


def test_laden_liest_beide_weltdateien(bestand):
    assert len(bestand.plaetze) == 23780
    assert len(bestand.zonen) == 23780
    assert len(bestand.zonen_bbox) == 23780


def test_plaetze_im_umkreis_liefert_nur_nahes(bestand):
    """Wangerooge z10 = 51 km auf 53,8 N."""
    treffer, gekappt = fse_modul.plaetze_im_umkreis(bestand, *EDWG, 51)
    assert "EDWG" in treffer
    assert "KJFK" not in treffer
    assert len(treffer) == 14
    assert not gekappt


def test_plaetze_deckel_greift_und_meldet_sich(bestand):
    """New York bei 150 km: 359 Plaetze im Ausschnitt, 250 duerfen raus. Bewusst ein Radius
    weit weg von jeder Deckelgrenze -- ein knapper Wert machte den Test zum Wackelkandidaten."""
    treffer, gekappt = fse_modul.plaetze_im_umkreis(bestand, *KJFK, 150)
    assert len(treffer) == fse_modul.MAX_PUNKTE_PLAETZE
    assert gekappt


def test_zonen_deckel_rechnet_in_punkten_nicht_in_stueck(bestand):
    """Eine Zone kostet ihre Eckenzahl (Mittel 7, max 21), ein Platz genau 1. Bei New York
    150 km stehen 2.719 Punkte an, 900 duerfen raus -- ein Stueckzahl-Deckel wuerde die
    falsche Ebene schonen (die Zonen stellen dort 88 % der Zeichenlast)."""
    treffer, gekappt = fse_modul.zonen_im_umkreis(bestand, *KJFK, 150)
    punkte = sum(len(p) for p in treffer.values())
    assert punkte <= fse_modul.MAX_PUNKTE_ZONEN
    assert punkte > fse_modul.MAX_PUNKTE_ZONEN - 21   # bis dicht an die Grenze gefuellt
    assert gekappt


def test_grosse_zone_reisst_kleinere_dahinter_nicht_mit(bestand):
    """Die Deckelschleife ueberspringt eine Zone, die nicht mehr passt, statt abzubrechen --
    sonst kappte eine 21-Punkte-Zelle in der Mitte der Liste alles Kleinere dahinter mit."""
    treffer, _ = fse_modul.zonen_im_umkreis(bestand, *KJFK, 150)
    rest = fse_modul.MAX_PUNKTE_ZONEN - sum(len(p) for p in treffer.values())
    assert rest < 4, f"{rest} Punkte Budget verschenkt -- die Schleife bricht ab statt zu ueberspringen"


def test_ozeanzelle_kommt_mit_egal_wie_gross_sie_ist(bestand):
    """Der Kern der Sortierentscheidung: Voronoi-Zellen ueber dem Atlantik haben bis zu
    14.127 km Diagonale (NZPG), ihr Flugplatz liegt womoeglich Hunderte Kilometer vom
    Ausschnitt entfernt. Wer nach Flugplatzentfernung sortiert, wirft genau die Zelle weg,
    in der man steht."""
    treffer, gekappt = fse_modul.zonen_im_umkreis(bestand, *ATLANTIK, 150)
    assert len(treffer) == 3
    assert sum(len(p) for p in treffer.values()) == 26
    assert not gekappt
    assert _umschliessende(bestand, treffer, *ATLANTIK), "die umschliessende Zelle fehlt"


def test_ozeanzelle_ueberlebt_auch_einen_vollen_deckel(bestand):
    """Gegenprobe an einem Ort, wo der Deckel wirklich greift: Auch in New York muss die
    Zelle, die den Ausschnitt umschliesst, ausgeliefert werden -- sie hat Abstand 0 und steht
    damit ganz vorn."""
    treffer, gekappt = fse_modul.zonen_im_umkreis(bestand, *KJFK, 150)
    assert gekappt
    assert _umschliessende(bestand, treffer, *KJFK)


def _umschliessende(bestand, treffer, lat, lon):
    return [
        i for i in treffer
        if bestand.zonen_bbox[i][0] <= lat <= bestand.zonen_bbox[i][1]
        and bestand.zonen_bbox[i][2] <= lon <= bestand.zonen_bbox[i][3]
    ]


def test_leerer_ausschnitt_ist_kein_fehler(bestand):
    """Ein plaetzeleerer Ausschnitt existiert (Nordatlantik). Ein ZONENleerer vermutlich
    nirgends -- die Voronoi-Zellen ueberdecken die Erde lueckenlos, auch die Antarktis."""
    treffer, gekappt = fse_modul.plaetze_im_umkreis(bestand, *ATLANTIK, 150)
    assert treffer == {} and not gekappt


def test_radius_wird_serverseitig_gedeckelt(bestand):
    """Wer r=5000 anfragt, bekommt den 250-km-Ausschnitt, nicht den halben Planeten."""
    weit, _ = fse_modul.plaetze_im_umkreis(bestand, *EDWG, 5000)
    genau, _ = fse_modul.plaetze_im_umkreis(bestand, *EDWG, fse_modul.MAX_KM)
    assert weit.keys() == genau.keys()


def test_zweig_korrektur_trifft_genau_die_zwei_baender(bestand):
    """36 Zonen tragen Laengen jenseits +-180. 34 davon sind DURCHGEHEND (NFNA 175,98 ->
    181,65) und zeichnen sich ueber die Grenze korrekt -- sie duerfen nicht angefasst werden.
    Echte Baender ziehen nur CYLT (342 Grad Spanne) und NZPG (295 Grad): ihre Ecken liegen in
    verschiedenen Zweigen. Pauschales Normalisieren auf +-180 machte aus den 34 heilen Zonen
    genau die Baender, die hier beseitigt werden sollen."""
    for icao in ("CYLT", "NZPG"):
        laengen = [p[1] for p in bestand.zonen[icao]]
        assert max(laengen) - min(laengen) <= 180, f"{icao} spannt noch immer ueber die Grenze"
    roh = json.loads((WELT / "fse_zones_world.json").read_text(encoding="utf-8"))
    assert bestand.zonen["NFNA"] == roh["NFNA"], "eine heile Zone wurde faelschlich veraendert"
    assert max(p[1] for p in bestand.zonen["NFNA"]) > 180
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_fse.py -k "bestand or umkreis or ozean or zweig or deckel" -v`
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
# Polygon mit im Mittel 7 (max 21). Bei New York stellen die Zonen damit 88 % der Zeichenlast
# -- ein Stueckzahl-Deckel wuerde beide gleich behandeln und die falsche Ebene schonen. Die
# Werte sind gegen Coherent GT gewaehlt (s. main.py: "ab ein paar hundert Elementen zaeh") und
# stehen zur Korrektur, sobald die Panel-Selbstdiagnose Canvas misst.
MAX_PUNKTE_PLAETZE = 250
MAX_PUNKTE_ZONEN = 900
# Obergrenze fuer den angefragten Radius, gespiegelt aus /api/traffic.
MAX_KM = 250

_ERD_KM_JE_GRAD = 111.32

# Rechteck des angefragten Ausschnitts: (lat_min, lat_max, lon_min, lon_max).
Rechteck = tuple[float, float, float, float]


@dataclass
class FseBestand:
    plaetze: dict[str, dict] = field(default_factory=dict)
    # Schlichte Punktlisten. Sie vorserialisiert zu halten war erwogen und gemessen verworfen:
    # json.load baut die Listen ohnehin, bevor irgendetwas daraus abgeleitet werden kann -- die
    # Zeichenketten kaemen obendrauf, und der freigegebene Listenspeicher geht nicht ans
    # Betriebssystem zurueck. Gemessen 55,3 statt 50,8 MB, also 4,5 MB TEURER (Spec §4).
    zonen: dict[str, list] = field(default_factory=dict)
    zonen_bbox: dict[str, Rechteck] = field(default_factory=dict)


def _auf_einen_zweig(punkte: list) -> list:
    """Alle Ecken auf den Laengen-Zweig der ERSTEN Ecke ziehen.

    36 Zonen tragen Laengen jenseits +-180. 34 davon sind durchgehend (NFNA 175,98 -> 181,65)
    und zeichnen sich ueber die Datumsgrenze korrekt -- sie muessen unangetastet bleiben.
    Pauschales Normalisieren auf +-180 machte aus jeder von ihnen ein Band quer ueber die
    Karte, also genau den Fehler, der hier behoben werden soll.

    Echte Baender ziehen nur CYLT (342 Grad Spanne) und NZPG (295 Grad): dort liegen die Ecken
    in VERSCHIEDENEN Zweigen. Diese Umrechnung trifft nachweislich genau diese zwei.
    """
    basis = punkte[0][1]
    return [[p[0], p[1] - 360.0 * round((p[1] - basis) / 360.0)] for p in punkte]


def laden(verzeichnis: Path) -> FseBestand:
    plaetze = json.loads((verzeichnis / "fse_airports_world.json").read_text(encoding="utf-8"))
    rohzonen = json.loads((verzeichnis / "fse_zones_world.json").read_text(encoding="utf-8"))
    b = FseBestand(plaetze=plaetze)
    for icao, roh in rohzonen.items():
        punkte = _auf_einen_zweig(roh)
        b.zonen[icao] = punkte
        breiten = [p[0] for p in punkte]
        laengen = [p[1] for p in punkte]
        b.zonen_bbox[icao] = (min(breiten), max(breiten), min(laengen), max(laengen))
    return b


def _rechteck(lat: float, lon: float, r_km: float) -> Rechteck:
    """Der Ausschnitt als Bbox. cos(lat) wird nach unten gekappt, sonst wird das Rechteck an
    den Polen unendlich breit.

    Rechnet NICHT ueber die Datumsgrenze -- bekannter Rest, s. Spec §10 (14 von 23.780
    Plaetzen, Fiji/Neuseeland/Marshallinseln/Aleuten).
    """
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


def _bbox_abstand_km(bbox: Rechteck, ausschnitt: Rechteck, cos_lat: float) -> float:
    """Abstand des ANGEFRAGTEN AUSSCHNITTS zur Zonen-Bbox, nicht zum Flugplatz der Zone.

    Das ist die tragende Entscheidung dieses Moduls: Voronoi-Zellen ueber dem Ozean haben bis
    zu 14.127 km Diagonale (p99: 1.348 km), ihr Flugplatz kann Hunderte Kilometer ausserhalb
    des Bildes liegen. Nach Flugplatzentfernung sortiert fiele ausgerechnet die Zelle als
    Erstes aus dem Deckel, in der man gerade steht. Was den Ausschnitt umschliesst oder
    schneidet, hat hier Abstand 0 und steht damit ganz vorn.

    Ausschnitt und cos(lat) kommen von aussen: sie sind ueber die ganze Anfrage konstant, und
    sie je Zone neu zu berechnen (23.780-mal cos/radians) hat in der Messung fast die Haelfte
    der Anfragezeit gekostet.
    """
    la0, la1, lo0, lo1 = ausschnitt
    dlat = max(bbox[0] - la1, la0 - bbox[1], 0.0)
    dlon = max(bbox[2] - lo1, lo0 - bbox[3], 0.0)
    return math.hypot(dlat * _ERD_KM_JE_GRAD, dlon * _ERD_KM_JE_GRAD * cos_lat)


def zonen_im_umkreis(
    bestand: FseBestand, lat: float, lon: float, r_km: float
) -> tuple[dict[str, list], bool]:
    r_km = min(r_km, MAX_KM)
    ausschnitt = _rechteck(lat, lon, r_km)
    la0, la1, lo0, lo1 = ausschnitt
    cos_lat = math.cos(math.radians(lat))
    treffer: list[tuple[float, str]] = []
    for icao, bb in bestand.zonen_bbox.items():
        # Reiner Bbox-Schnitt, kein exakter Polygontest: gemessen liefert er bei Wangerooge
        # 90 von 90 und bei New York 389 von 389 identisch, im Nordatlantik eine Zone weniger.
        if bb[1] < la0 or bb[0] > la1 or bb[3] < lo0 or bb[2] > lo1:
            continue
        treffer.append((_bbox_abstand_km(bb, ausschnitt, cos_lat), icao))
    treffer.sort()
    ausgabe: dict[str, list] = {}
    punkte = 0
    gekappt = False
    for _, icao in treffer:
        kosten = len(bestand.zonen[icao])
        if punkte + kosten > MAX_PUNKTE_ZONEN:
            gekappt = True
            # Nicht abbrechen, sondern ueberspringen: Eine 21-Punkte-Zelle mitten in der Liste
            # duerfte sonst alles Kleinere dahinter mitreissen und Budget verschenken.
            continue
        ausgabe[icao] = bestand.zonen[icao]
        punkte += kosten
    return ausgabe, gekappt
```

- [ ] **Schritt 4: Test laufen lassen, Erfolg bestätigen**

Run: `python -m pytest tests/test_fse.py -v`
Erwartet: PASS, auch die 21 bestehenden Tests

- [ ] **Schritt 5: Commit**

```bash
git add app/fse.py tests/test_fse.py
git commit -m "FSE-Weltbestand: Modul zum Halten und Ausschneiden"
```

---

### Task 2: Die zwei Endpunkte

**Files:**
- Modify: `app/main.py` (`lifespan` ab Zeile 209; Endpunkte nach `get_traffic`, Zeile 673 ff.)
- Test: `tests/test_fse.py` (anfügen)

**Interfaces:**
- Consumes: `app.fse.laden`, `plaetze_im_umkreis`, `zonen_im_umkreis`, `MAX_KM` aus Task 1
- Produces:
  - `app.state.fse: FseBestand`
  - `GET /api/fse/airports?lat=&lon=&r=` → `{"plaetze": {...}, "gekappt": bool}`
  - `GET /api/fse/zones?lat=&lon=&r=` → `{"zonen": {...}, "gekappt": bool}`

**`Response`, `json`, `Path`, `Query`, `Request` sind in `app/main.py` bereits importiert** —
kein Nachtrag nötig.

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

```python
from types import SimpleNamespace  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import main as main_modul  # noqa: E402


@pytest.fixture()
def klient(bestand, tmp_path, monkeypatch):
    """TestClient OHNE `with` — der Lifespan darf hier nicht laufen.

    Er liest `SECRET_KEY` (das hat keinen Default und steht nur in config.env), ruft `init_db`
    auf dem PRODUKTIONSPFAD /opt/friesenspy/data/friesenspy.db und startet den VATSIM-Poller
    gegen die echte API. Das Hausmuster dagegen steht in tests/test_traffic_api.py:79: Settings
    per monkeypatch ersetzen und den Zustand direkt an app.state haengen.

    `bestand` kommt aus der Fixture von Task 1 — so werden die 6 MB einmal je Modul gelesen
    statt einmal je Test.
    """
    einstellungen = SimpleNamespace(DB_PATH=str(tmp_path / "t.db"), CALLSIGN_PREFIX="FRS",
                                    SECRET_KEY="s3cr3t", SSO_SECRET="", FORUM_SSO_URL="")
    monkeypatch.setattr(main_modul, "get_settings", lambda: einstellungen)
    main_modul._reset_gate_cache()
    vorher = getattr(main_modul.app.state, "fse", None)
    main_modul.app.state.fse = bestand
    yield TestClient(main_modul.app)
    main_modul.app.state.fse = vorher


def test_endpunkt_plaetze_liefert_den_ausschnitt(klient):
    r = klient.get("/api/fse/airports", params={"lat": 53.7872, "lon": 7.91583, "r": 51})
    assert r.status_code == 200
    d = r.json()
    assert "EDWG" in d["plaetze"]
    assert d["plaetze"]["EDWG"]["name"]
    assert d["gekappt"] is False


def test_endpunkt_zonen_liefert_punktlisten(klient):
    r = klient.get("/api/fse/zones", params={"lat": 53.7872, "lon": 7.91583, "r": 51})
    assert r.status_code == 200
    d = r.json()
    assert "EDWG" in d["zonen"]
    assert len(d["zonen"]["EDWG"][0]) == 2      # [lat, lon]


def test_endpunkte_weisen_unsinnige_parameter_ab(klient):
    for params in ({"lat": 91, "lon": 0, "r": 10},
                   {"lat": 0, "lon": 181, "r": 10},
                   {"lat": 0, "lon": 0, "r": 0},
                   {"lat": 0, "lon": 0, "r": 251}):
        assert klient.get("/api/fse/airports", params=params).status_code == 422
        assert klient.get("/api/fse/zones", params=params).status_code == 422


def test_endpunkt_meldet_die_kappung(klient):
    d = klient.get("/api/fse/airports", params={"lat": 40.7, "lon": -74.0, "r": 150}).json()
    assert d["gekappt"] is True
    assert len(d["plaetze"]) == 250


def test_endpunkte_blockieren_den_event_loop_nicht():
    """10-14 ms je Anfragepaar sind fuer einen Threadpool unauffaellig und fuer den Event-Loop
    viel: dort haengt auch /api/sse daran. FastAPI schickt NUR sync-Funktionen in den
    Threadpool -- ein `async def` hier waere eine stille Bremse fuer die ganze Anwendung."""
    import inspect
    for name in ("get_fse_airports", "get_fse_zones"):
        fn = getattr(main_modul, name)
        assert not inspect.iscoroutinefunction(fn), f"{name} ist async def"


def test_fse_endpunkte_stehen_nicht_im_gate_allowlist():
    """Wie /api/traffic: kein Sonderweg an der Anmeldung vorbei."""
    quelle = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    stelle = quelle.index("_GATE_ALLOW_PREFIXES")
    assert "/api/fse" not in quelle[stelle:quelle.index("\n\n", stelle)]
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_fse.py -k endpunkt -v`
Erwartet: FAIL — 404 auf `/api/fse/airports`, `AttributeError` auf `get_fse_airports`

- [ ] **Schritt 3a: Ladeschritt in `lifespan`**

**Hinter** den `try:`/`finally:`-Block um die DB-Verbindung (`main.py:218-222`) setzen, nicht
hinein — 0,8 s JSON-Parsen mit offen gehaltener Verbindung wäre unnötig:

```python
    # FSE-Weltbestand einmal beim Start lesen (23.780 Plaetze + Zonen, rund 51 MB). Danach nur
    # noch gelesen, deshalb ohne Sperre. Der Pfad ist relativ zum Arbeitsverzeichnis, so wie
    # der StaticFiles-Mount weiter unten -- im Container ist das /opt/friesenspy.
    app.state.fse = fse.laden(Path("app/data/fse"))
    _logger.info("FSE-Bestand geladen: %d Plaetze", len(app.state.fse.plaetze))
```

Oben `from app import fse` ergänzen.

- [ ] **Schritt 3b: Die Endpunkte, direkt nach `get_traffic`**

```python
def get_fse_airports(
    request: Request,
    lat: float = Query(..., ge=-90, le=90, description="Bezugspunkt, i. d. R. die Kartenmitte"),
    lon: float = Query(..., ge=-180, le=180),
    r: float = Query(50.0, ge=1, le=fse.MAX_KM, description="Radius in km"),
):
    """FSE-Plaetze im Kartenausschnitt.

    Getrennt von den Zonen, weil beide Ebenen einzeln schaltbar sind: Wer nur die
    Landeflaechen anhat, soll die Plaetze nicht mitladen. (Der Vorgaenger `_fseLaden` holte
    immer beide Dateien, unabhaengig davon, welcher Haken gesetzt war.)

    `gekappt` meldet, dass der Deckel gegriffen hat und der Nutzer eine Scheibe statt des
    vollen Rechtecks sieht -- dieselbe Entscheidung wie beim Verkehr, aus demselben Grund.

    BEWUSST `def` und nicht `async def`: Der Filter laeuft linear ueber 23.780 Eintraege und
    kostet ein paar Millisekunden. In einer Koroutine blockierte das den Event-Loop und damit
    auch /api/sse; als synchrone Funktion landet sie im Threadpool.

    Kein Sonderweg bei der Anmeldung: verhaelt sich wie `/api/traffic` und gehoert NICHT in
    `_GATE_ALLOW_PREFIXES`.
    """
    plaetze, gekappt = fse.plaetze_im_umkreis(request.app.state.fse, lat, lon, r)
    return {"plaetze": plaetze, "gekappt": gekappt}


def get_fse_zones(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    r: float = Query(50.0, ge=1, le=fse.MAX_KM, description="Radius in km"),
):
    """FSE-Landeflaechen im Kartenausschnitt. Gedeckelt in Punkten, nicht in Stueck -- eine
    Zone kostet das Siebenfache eines Platzes (s. app/fse.py). `def` aus demselben Grund wie
    oben."""
    zonen, gekappt = fse.zonen_im_umkreis(request.app.state.fse, lat, lon, r)
    return {"zonen": zonen, "gekappt": gekappt}


app.get("/api/fse/airports")(get_fse_airports)
app.get("/api/fse/zones")(get_fse_zones)
```

> Die Registrierung steht getrennt, damit `test_endpunkte_blockieren_den_event_loop_nicht`
> die Funktion über `getattr(main_modul, name)` erreicht. Mit `@app.get(...)` direkt am
> `def` ginge das auch — dann muss der Test stattdessen über `app.routes` gehen. Beide Wege
> sind zulässig; wer den Dekorator vorzieht, passt den Test entsprechend an.

- [ ] **Schritt 4: Test laufen lassen**

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
- Modify: `tests/test_fse.py` — **vier bestehende Tests brechen durch diese Aufgabe und werden
  hier mitgezogen, nicht in Task 5**

**Interfaces:**
- Consumes: `/api/fse/airports`, `/api/fse/zones` aus Task 2
- Produces: `_fseAbrufen(map)`, `_fseAbgleichen(...)`, `_fseLeeren()`, `_fseZoneBauen`,
  `_fsePlatzBauen`, `_fsePlaetzeTabelle`, `_fseZonenTabelle`

**Achtung:** Diese Datei wird parallel bearbeitet. Vor dem Start `git pull --ff-only`.

**Diese vier bestehenden Tests brechen und müssen in dieser Aufgabe angepasst werden:**

| Test | Stelle | warum |
|---|---|---|
| `test_zonen_fangen_keine_klicks` | `tests/test_fse.py:107` | sucht `function _fseZonenZeichnen(` → jetzt `_fseZoneBauen` |
| `test_klickflaeche_ist_kein_miniradius_mehr` | `tests/test_fse.py:309` | sucht `function _fsePlaetzeZeichnen(` → jetzt `_fsePlatzBauen` |
| `test_addPreferredFseLayer_haengt_beide_gruppen_ein…` | `tests/test_fse.py:167` | Node-Harness braucht `fetch`-Attrappe mit `r.ok` und `{plaetze:…}`/`{zonen:…}`-Hülle, dazu `getCenter`/`getBounds`/`getZoom`/`hasLayer`/`getContainer` an der FakeMap und `_istSichtbar` |
| `test_labels_folgen_der_zoom_schwelle` | `tests/test_fse.py:346` | Treiber ruft `_fsePlaetzeZeichnen({…})` → `_fsePlatzBauen` + `addTo` |

- [ ] **Schritt 1: Die neuen Tests schreiben**

```python
def test_frontend_konstanten_stehen_wie_spezifiziert():
    assert re.search(r"_FSE_RAND\s*=\s*1\.25", INDEX)
    # 0.2, nicht 0.25: der Anteil rechnet gegen den ABGERUFENEN Radius (1,25 R), und
    # 0,2 x 1,25 R ergibt genau die Reserve von 0,25 R, die der Rand bereitstellt. Mit 0,25
    # bliebe zwischen 0,25 R und 0,3125 R Fahrtstrecke ein Streifen am vorderen Bildrand ohne
    # Daten -- genau das Loch, das der Rand verhindern soll.
    assert re.search(r"_FSE_NACHLADEN_ANTEIL\s*=\s*0\.2\b", INDEX)
    assert re.search(r"_FSE_MIN_ZOOM\s*=\s*6", INDEX)
    assert re.search(r"_FSE_MAX_KM\s*=\s*250", INDEX), \
        "der Serverdeckel gehoert gespiegelt, nicht als Literal in _fseRadiusKm"


def test_frontend_ruft_nicht_bei_jeder_bewegung_ab():
    """Kernkorrektur gegenueber der Uebergabeskizze: `moveend` mit `!_naviSelbstBewegt` (so
    macht es der Verkehr, index.html:4570) waere hier ein Fehler. Bei eingeschalteter Moving
    Map bewegt die Karte sich SELBST, die Wache greift also immer -- und anders als der
    Verkehr hat die FSE-Ebene keinen Takt als zweite Quelle. Sie wuerde im Kniebrett waehrend
    des ganzen Fluges nie nachladen.

    Geprueft wird in Node, weil ein String-Test die Bedingung nicht auswerten kann:
      - Zoom 5 (< _FSE_MIN_ZOOM): kein fetch
      - Zoom 10, erster Aufruf:   fetch
      - Mitte um 0,1 x r verschoben: KEIN zweiter fetch
      - Mitte um 0,3 x r verschoben: zweiter fetch
      - Zoomwechsel ohne Bewegung:   fetch
    """
    ...


def test_frontend_holt_beim_einschalten_sofort():
    """Ohne Ruecksetzen von _fseLetzteMitte blockt die Streckensperre den Abruf, der auf
    `overlayadd` folgt -- und beim Start ruft _addPreferredFseLayer zweimal auf, wobei die
    Plaetze-Gruppe im ersten Durchgang noch gar nicht an der Karte haengt. Folge waere: beide
    Haken gesetzt, Plaetze-Ebene bleibt nach jedem Seitenaufruf leer, bis der Nutzer ein
    Viertel Radius fliegt."""
    ...


def test_frontend_zeichnet_unveraenderte_plaetze_nicht_neu():
    """Der Abgleich ist der Grund, warum die permanenten ICAO-Beschriftungen beim Fliegen
    nicht flackern: Ein ICAO, der in zwei aufeinanderfolgenden Antworten steht, muss
    UNANGETASTET bleiben -- nicht entfernt und neu gezeichnet."""
    ...


def test_frontend_entfernt_was_aus_dem_ausschnitt_faellt():
    ...


def test_frontend_zwingt_die_zonen_nach_jedem_nachladen_nach_hinten():
    """Beide Ebenen teilen sich EINEN Canvas-Renderer (index.html:4127) -- massgeblich ist die
    Zeichenreihenfolge im Canvas, nicht der overlayPane. Zwei unabhaengige fetch ordnen sich
    nicht, und die Zonen-Antwort ist die groessere (900 Punkte gegen 250 Plaetze), kommt also
    typischerweise spaeter. Schlimmer: Jedes Nachladen haengt neue Zonen ans ENDE der
    Zeichenliste. Ohne bringToBack() nach jedem Zonen-Abgleich liegt die graue Kulisse nach
    ein paar Minuten Flug ueber den Platzmarkern."""
    ...
```

> **Hinweis für den Umsetzenden:** Die mit `...` markierten Tests folgen dem Muster von
> `test_addPreferredFseLayer_haengt_beide_gruppen_ein_und_zwingt_zonen_nach_hinten`
> (`tests/test_fse.py:167`): Quelltext per `INDEX.index(...)` ausschneiden, Leaflet-Attrappe
> als `harness` davor, Treiber dahinter, `subprocess.run([_NODE, "-e", skript])`, auf
> `"OK" in stdout` prüfen.
>
> **Die Scheibe muss `_fseAbrufen` enthalten** — von `const _FSE_PLAETZE_API` bis hinter
> `_fseAbrufen`, nicht bis `_fseAbgleichen` (dort steht die Funktion noch gar nicht).
> `_istSichtbar`, `_fseZoneBauen`, `_fsePlatzBauen` und `_fseLeeren` müssen mit ausgeschnitten
> oder als Attrappe ins Harness, sonst wirft der Treiber. Die `fetch`-Attrappe muss `r.ok`
> liefern und die Hülle `{plaetze: {...}}` bzw. `{zonen: {...}}` — ohne beides greift
> `r.ok ? r.json() : null` bzw. `d.plaetze` ins Leere und der Test ist grün, ohne etwas zu
> prüfen.

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
// Darunter macht die serverseitige Kappung von r aus jeder Antwort einen Punkt in der Mitte
// einer Kontinentansicht -- eine Anfrage ohne Aussage. Kein Dichteregler: die Dichte regelt
// das Punktebudget im Server, und zwar ortsabhaengig.
const _FSE_MIN_ZOOM = 6;
// Serverseitige Obergrenze, hier gespiegelt (wie _VERKEHR_MAX_KM).
const _FSE_MAX_KM = 250;
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
//
// 0,2 und nicht 0,25, weil gegen den ABGERUFENEN Radius gerechnet wird: 0,2 x 1,25 R ist
// genau die Reserve von 0,25 R, die der Rand bereitstellt.
const _FSE_NACHLADEN_ANTEIL = 0.2;

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
  return Math.max(1, Math.min(_FSE_MAX_KM, Math.round(km * _FSE_RAND)));
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

// Auch die Streckenmarke zuruecksetzen: Sonst blockt die Sperre den naechsten Abruf, obwohl
// die Karte gerade geleert wurde.
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
  if (zonenAn) {
    fetch(_FSE_ZONEN_API + frage)
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (!d) return;
        _fseAbgleichen(_fseZonenGruppe, _fseZonenTabelle, d.zonen, _fseZoneBauen);
        // Nach JEDEM Abgleich, nicht nur beim Einschalten: Beide Ebenen teilen sich einen
        // Canvas-Renderer, und jedes Nachladen haengt die neuen Zonen ans Ende der
        // Zeichenliste -- also ueber die bereits vorhandenen Platzmarker. Ohne diese Zeile
        // liegt die graue Kulisse nach ein paar Minuten Flug obenauf.
        _fseZonenGruppe.bringToBack();
      })
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
(Rumpf inhaltlich gleich, Schleife und `addTo` fallen weg — das macht `_fseAbgleichen`):

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

In `_addPreferredFseLayer` jedes `_fseLaden()` durch `_fseAbrufen(map)` ersetzen — und in
**allen vier** Zweigen die Streckenmarke zurücksetzen:

```js
  map.on('overlayadd', (e) => {
    if (e.layer === _fsePlaetzeGruppe) {
      _saveFsePref(_FSE_PLAETZE_PREF_KEY, true);
      // Ohne diese Zeile blockt die Streckensperre den Abruf, der auf das Einschalten folgt:
      // beim Start laeuft _fseAbrufen zweimal, und im zweiten Durchgang ist nichts gewandert.
      _fseLetzteMitte = null;
      _fseAbrufen(map); _fseAttributionAn(map);
    }
    if (e.layer === _fseZonenGruppe) {
      _saveFsePref(_FSE_ZONEN_PREF_KEY, true);
      _fseLetzteMitte = null;
      _fseAbrufen(map); _fseAttributionAn(map);
    }
  });
  map.on('overlayremove', (e) => {
    if (e.layer === _fsePlaetzeGruppe) {
      _saveFsePref(_FSE_PLAETZE_PREF_KEY, false); _fseAttributionAus(map);
      _fsePlaetzeGruppe.clearLayers(); _fsePlaetzeTabelle.clear(); _fseLetzteMitte = null;
    }
    if (e.layer === _fseZonenGruppe) {
      _saveFsePref(_FSE_ZONEN_PREF_KEY, false); _fseAttributionAus(map);
      _fseZonenGruppe.clearLayers(); _fseZonenTabelle.clear(); _fseLetzteMitte = null;
    }
  });
```

Die beiden Startzweige (`if (_loadFsePref(...))`) bekommen dieselbe Behandlung. Zusätzlich
einmal registrieren:

```js
  map.on('moveend zoomend', () => _fseAbrufen(map));
```

Ohne `_naviSelbstBewegt` und ohne Drossel-Timer — die Streckenprüfung in `_fseAbrufen` tut beides.

- [ ] **Schritt 4: Die vier gebrochenen Tests anpassen**

Siehe Tabelle oben. `test_zonen_fangen_keine_klicks` und
`test_klickflaeche_ist_kein_miniradius_mehr` brauchen nur den neuen Funktionsnamen; die beiden
Node-Tests brauchen die erweiterte Attrappe.

- [ ] **Schritt 5: Test laufen lassen**

Run: `python -m pytest tests/test_fse.py -v`
Erwartet: PASS, **alle** Tests

- [ ] **Schritt 6: Commit**

```bash
git add app/static/index.html tests/test_fse.py
git commit -m "FSE-Ebenen holen den Ausschnitt statt der ganzen Datei"
```

---

### Task 4: Canvas in der Panel-Selbstdiagnose

**Files:**
- Modify: `app/static/index.html` (Diagnoseblock bei `probeSprites`, Zeile ~408)
- Test: `tests/test_fse.py` (anfügen)

**Interfaces:**
- Consumes: nichts. **Diese Aufgabe hängt an keiner anderen** und könnte auch zuerst laufen.
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

Neben `probeSprites` einfügen (6 Leerzeichen Einrückung, wie die Nachbarn):

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

Und in den Bericht, neben den anderen `try`-Zeilen:

```js
        try { base.canvas = probeCanvas(); } catch (err) { base.canvas = { error: String(err) }; }
```

- [ ] **Schritt 4: Test laufen lassen**

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
- Modify: `tests/test_fse.py`, `README.md`, `docs/api.md`, `docs/architecture.md`,
  `docs/fse-daten-weltweit.md`, `app/CHANGELOG.json`

- [ ] **Schritt 1: Die datei- und datenbezogenen Tests umhängen oder entfernen**

Betroffen (Zeilennummern vor dem Ändern gegenprüfen — Tasks 1–4 haben die Datei verlängert):

| Test | Behandlung |
|---|---|
| `test_dateien_liegen_im_repo` (16) | auf die Weltdateien umhängen |
| `test_europa_zuschnitt_ist_klein_genug` (20) | **löschen** — es gibt keinen Zuschnitt mehr |
| `test_plaetze_liegen_in_europa` (27) | **löschen** |
| `test_msfs_feld_ist_bereinigt` (35) | umhängen — echte Datenprüfung, gilt weltweit |
| `test_die_inseln_sind_dabei` (45) | umhängen |
| `test_belag_stimmt_gegen_echte_plaetze` (76) | umhängen |
| `test_fse_daten_werden_lazy_geholt` (116) | **löschen** — durch die Tests aus Task 3 ersetzt |

Die vier Frontend-Tests aus Task 3 sind hier **nicht** noch einmal zu behandeln.

- [ ] **Schritt 2: Test laufen lassen**

Run: `python -m pytest tests/test_fse.py -v`
Erwartet: PASS, kein Test verweist mehr auf `app/static/data/fse_*_eu.json`

- [ ] **Schritt 3: Dateien löschen**

```bash
git rm app/static/data/fse_airports_eu.json app/static/data/fse_zones_eu.json scripts/fse_zuschnitt.py
```

Gegenprobe, dass nichts anderes darauf zeigt:

```bash
grep -rn "fse_airports_eu\|fse_zones_eu\|fse_zuschnitt" --exclude-dir=.git .
```

- [ ] **Schritt 4: Doku nachziehen**

- `docs/api.md`: die zwei Endpunkte mit Parametern, Antwortform und `gekappt`
- `docs/architecture.md`: `app/fse.py`, der Speicherbedarf (~51 MB, Container 141 → ~192),
  die Deckelwerte, die Zweig-Korrektur
- `docs/fse-daten-weltweit.md`: Abschnitt „Was noch fehlt" durch einen Verweis auf die Spec und
  „umgesetzt am 16.08.2026" ersetzen; der Rest bleibt
- `README.md`: prüfen, ob die FSE-Ebenen dort beschrieben sind, und auf „weltweit, nur der
  sichtbare Ausschnitt wird geladen" bringen. **Die Wendung „rund 2 300 europäischen Plätzen"
  steht nicht im README, sondern in `app/CHANGELOG.json` als historischer Release-Eintrag —
  der bleibt unangetastet.**
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
Punktebudget → Task 1. §4 Servermodul samt Zweig-Korrektur → Task 1. §5 Endpunkte → Task 2.
§6 Frontend → Task 3. §7 Canvas-Diagnose → Task 4. §8 Aufräumen → Task 5. §9 Tests → verteilt
über 1–4. §10 Verworfenes → als Kommentare in `app/fse.py` und `index.html` festgehalten.

**Platzhalter:** Die sechs mit `...` markierten Node-Tests in Task 3 sind als Muster plus
Prüfliste beschrieben statt ausgeschrieben — das Harness-Gerüst ist 120 Zeilen und steht
wörtlich in `tests/test_fse.py:167`. Der Umsetzende bekommt Fundstelle, Prüfpunkte,
Ausführungsmuster und die drei Fallstricke der Attrappe (`r.ok`, Antworthülle, FakeMap-Methoden).

**Typkonsistenz:** `plaetze_im_umkreis` und `zonen_im_umkreis` geben beide ein Dict plus
`gekappt` zurück — die Asymmetrie des Vorentwurfs entfiel mit der Vorserialisierung.
`_fseAbgleichen` erwartet in `neu` genau diese Dicts.

**Reihenfolge:** Task 1 ist unabhängig, Task 2 baut auf Task 1, Task 3 auf Task 2, Task 4 auf
nichts. Task 5 Schritt 1 (Tests umhängen) steht vor Schritt 3 (Dateien löschen). Der Baum ist
nach jedem Commit grün — die vier Tests, die Task 3 bricht, werden **in Task 3** mitgezogen.

**Bekannte Bruchstelle:** Task 3 ändert `app/static/index.html`, das eine andere Sitzung
parallel bearbeitet. Vor Task 3 zwingend `git pull --ff-only`.
