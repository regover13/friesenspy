# Skill „track-diagnose" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Skill, der die Erkennungslücken-Liste abarbeitbar macht: erst Triage über alle Fälle (74,5 % sind mechanisch abzuhaken), dann Einzeldiagnose der übrigen — mit einem Messwerkzeug für die Zahlen und einer festen Prüfreihenfolge für die Deutung.

**Architecture:** Strikte Trennung von Messung und Urteil. `scripts/nearby_airports.py` ist rein, offline und ohne DB-Zugriff: Punkt rein, Messwerte raus (nächste Plätze laut airportsdata und OurAirports, Quellen-Abweichung, Distanz zum Soll-Code). `scripts/triage_gaps.py` legt eine Schleife darum: JSON-Export rein, gruppierte Befunde raus — es implementiert Schritt 0 und Schritt 1 der Prüfreihenfolge, die reine Messungen sind. Schritt 2 braucht Kontext und bleibt beim Assistenten; die Fallunterscheidung steht als Prosa in `.claude/skills/track-diagnose/SKILL.md`. Detektor-Schwellen werden aus `app/gps_legs.py` und `app/database.py` **importiert**, nie abgeschrieben — so wird ein Test rot, statt dass der Skill still veraltet.

**Tech Stack:** Python 3.11, `airportsdata`, `httpx` (nur für den OurAirports-Download), `pytest`, stdlib `csv`/`argparse`/`dataclasses`.

**Spec:** `docs/superpowers/specs/2026-07-15-track-diagnose-design.md`

## Global Constraints

- **Keine Zahl aus dem Gedächtnis.** Alle Erwartungswerte in diesem Plan wurden am 2026-07-15 aus der Produktions-DB und den beiden Referenzquellen gemessen. Werte niemals „anpassen", damit ein Test grün wird — abweichende Messung heißt: Ursache klären.
- **Das Werkzeug fällt kein Urteil.** Es meldet „außerhalb", nie „also Radius-Override". Keine Empfehlungslogik in `scripts/nearby_airports.py`.
- **Das Werkzeug bleibt rein:** kein DB-Zugriff, kein SSH, keine `custom_airports`. Einzige Netz-Nutzung ist der OurAirports-Download in Task 4.
- **Referenzquelle ist `airportsdata.load("ICAO")` direkt** — die Rohquelle kennt per Definition keine `custom_airports` und liefert als einzige auch Name und Elevation. Bewusst **nicht** `app.geo.icao_to_coords()`: das bezieht `custom_airports` ein und drückt jeden Override-Vergleich auf 0 km. Aus `app.geo` kommt nur `haversine`.
- **OurAirports-Codes über `ident`, `icao_code` UND `gps_code` matchen.** `EDHX` und `EBMO` haben ein leeres `icao_code`-Feld; wer nur darauf schaut, verliert reale Plätze.
- **Ein Code kann in einer Quelle fehlen und in der anderen stehen** (`EDHX` nur OurAirports, `ETUO` nur airportsdata). Beide Blöcke melden unabhängig „nicht vorhanden", ohne dass der andere ausfällt.
- **Kein Versionssprung, kein Git-Tag, kein `app/CHANGELOG.json`-Eintrag.** Ausnahme von der stehenden Versionierungsregel, mit dem Nutzer abgestimmt: es ändert sich nichts am ausgelieferten Verhalten, `scripts/` und `.claude/skills/` landen in keinem Container. Ebenso **keine** Ergänzung in `docs/api.md` / `docs/architecture.md` — kein Endpoint, keine Architekturänderung.
- **Sprache:** Code-Kommentare, Docstrings und SKILL.md auf Deutsch, mit korrekten Umlauten. Commit-Messages ohne Umlaute (Repo-Konvention: `ae/oe/ue`).
- **TDD:** Test schreiben, RED verifizieren, minimal implementieren, GREEN verifizieren, committen.

## File Structure

| Datei | Verantwortung |
|---|---|
| `scripts/nearby_airports.py` | Messwerkzeug: Referenzquellen laden, Distanzen messen, Report rendern. |
| `scripts/triage_gaps.py` | Batch: JSON-Export → Schritt 0/1 je Ende → gruppierte Befunde. Nutzt `measure()`. |
| `tests/fixtures/ourairports_mini.csv` | Fünf echte OurAirports-Zeilen (EBKT, EBMO, EDHX, EDVA, EDXH) — macht die Tests netzfrei. |
| `tests/fixtures/gaps_mini.json` | Fünf echte Lückenfälle, je einer pro Triage-Gruppe. |
| `tests/test_nearby_airports.py` | Regressionstests aus den vier realen Fällen. |
| `tests/test_triage_gaps.py` | Gruppierungstests gegen die JSON-Fixture. |
| `.claude/skills/track-diagnose/SKILL.md` | Ablauf, Export-Snippet, SQL, Fallunterscheidung. Kein Code. |
| `.gitignore` | Ergänzung: `scripts/.cache/` |
| `README.md:75` | Korrektur der Falschaussage zur Koordinatenherkunft. |

`scripts/` ist als Namespace-Package importierbar (verifiziert) — **kein `__init__.py` nötig**.

Innerhalb von `nearby_airports.py` gibt es drei Schichten, die nicht vermischt werden: **Laden** (`load_ourairports`, `airportsdata_refs`), **Messen** (`nearest`, `find_code`, `measure`), **Darstellen** (`format_report`, `main`). Getestet wird die Messschicht.

---

### Task 1: Datenmodell, OurAirports-Parser und Code-Suche

**Files:**
- Create: `scripts/nearby_airports.py`
- Create: `tests/fixtures/ourairports_mini.csv`
- Create: `tests/test_nearby_airports.py`

**Interfaces:**
- Consumes: nichts (erster Task)
- Produces:
  - `AirportRef` (frozen dataclass): `code: str`, `name: str`, `lat: float`, `lon: float`, `elevation_ft: float | None`, `codes: frozenset[str]`
  - `parse_ourairports(rows: Iterable[dict]) -> list[AirportRef]`
  - `load_ourairports(path: Path | str | None = None) -> list[AirportRef]`
  - `find_code(code: str, refs: Sequence[AirportRef]) -> AirportRef | None`

- [ ] **Step 1: Fixture anlegen**

Fünf echte Zeilen aus dem OurAirports-Vollabzug (2026-07-15). **Nicht nachbauen, exakt so übernehmen** — insbesondere die leeren `icao_code`-Felder bei `EDHX` und `EBMO` sind der Kern von Task 1.

Create `tests/fixtures/ourairports_mini.csv`:

```csv
"id","ident","type","name","latitude_deg","longitude_deg","elevation_ft","continent","iso_country","iso_region","municipality","scheduled_service","icao_code","iata_code","gps_code","local_code","home_link","wikipedia_link","keywords"
"2161","EBKT","medium_airport","Kortrijk-Wevelgem International Airport","50.818878","3.209551","55","EU","BE","BE-VWV","Wevelgem","no","EBKT","KJK","EBKT","","http://www.kortrijkairport.be","https://en.wikipedia.org/wiki/Flanders_International_Airport","Kortrijk, Courtrai"
"29042","EBMO","small_airport","Moorsele Airfield","50.851285","3.147669","66","EU","BE","BE-VWV","Wevelgem","no","","","EBMO","","","https://en.wikipedia.org/wiki/Moorsele_Airfield",""
"308606","EDHX","heliport","Bad Bramstedt Heliport","53.9428","9.9055","118","EU","DE","DE-SH","Bad Bramstedt","no","","","EDHX","","","",""
"28511","EDVA","small_airport","Bad Gandersheim Airfield","51.854168","10.025556","791","EU","DE","DE-NI","Bad Gandersheim","no","EDVA","","EDVA","","","https://en.wikipedia.org/wiki/Bad_Gandersheim_Aerodrome","Gandersheim-Seesen"
"28591","EDXH","small_airport","Helgoland-Düne Airport","54.18528","7.915833","8","EU","DE","DE-SH","Helgoland","yes","EDXH","HGL","EDXH","","https://www.flugplatz-helgoland.de/","https://en.wikipedia.org/wiki/Heligoland_Airport",""
```

- [ ] **Step 2: Failing Test schreiben**

Create `tests/test_nearby_airports.py`:

```python
"""Regressionstests für das Messwerkzeug der Track-Diagnose.

Alle Erwartungswerte wurden am 2026-07-15 gemessen (Produktions-DB + airportsdata +
OurAirports-Vollabzug). Weicht ein Wert ab, ist das ein Befund — kein Grund, die Zahl
anzupassen. Siehe docs/superpowers/specs/2026-07-15-track-diagnose-design.md
"""
from pathlib import Path

import pytest

from scripts.nearby_airports import find_code, load_ourairports

FIXTURE = Path(__file__).parent / "fixtures" / "ourairports_mini.csv"


def test_fixture_laedt_alle_fuenf_plaetze():
    refs = load_ourairports(FIXTURE)
    assert len(refs) == 5


def test_code_mit_leerem_icao_feld_wird_ueber_gps_code_gefunden():
    """EDHX und EBMO haben in OurAirports ein leeres icao_code-Feld — wer nur darauf
    schaut, verliert sie. Genau dieser Fall ist der EDHX-Beleg der Spec."""
    refs = load_ourairports(FIXTURE)

    edhx = find_code("EDHX", refs)
    assert edhx is not None
    assert edhx.name == "Bad Bramstedt Heliport"
    assert edhx.lat == pytest.approx(53.9428)
    assert edhx.elevation_ft == pytest.approx(118.0)

    assert find_code("EBMO", refs) is not None


def test_code_suche_ist_case_insensitiv_und_meldet_fehlende_codes():
    refs = load_ourairports(FIXTURE)
    assert find_code("ebkt", refs) is not None
    assert find_code("ETUO", refs) is None       # ETUO steht NICHT in OurAirports
```

- [ ] **Step 3: RED verifizieren**

Run: `python -m pytest tests/test_nearby_airports.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.nearby_airports'`

- [ ] **Step 4: Minimal implementieren**

Create `scripts/nearby_airports.py`:

```python
"""Messwerkzeug für die Track-Diagnose (Skill ``track-diagnose``).

Punkt rein, Messwerte raus: nächste Flugplätze laut airportsdata und OurAirports,
Abweichung beider Quellen, Distanz zum Soll-Code aus dem Flugplan.

**Dieses Werkzeug fällt kein Urteil.** Es meldet „außerhalb", nicht „also Radius-Override".
Die Fallunterscheidung steht in ``.claude/skills/track-diagnose/SKILL.md``.

Rein und offline: kein DB-Zugriff, kein SSH, keine ``custom_airports``.
"""
from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AirportRef:
    """Ein Flugplatz aus einer Referenzquelle.

    ``code`` ist der Anzeige-Code. ``codes`` enthält ALLE Codes, unter denen der Platz
    auffindbar ist — bei OurAirports sind das ``ident``, ``icao_code`` und ``gps_code``,
    die auseinanderfallen können (EDHX/EBMO haben ein leeres ``icao_code``).
    """

    code: str
    name: str
    lat: float
    lon: float
    elevation_ft: float | None
    codes: frozenset[str]


def parse_ourairports(rows: Iterable[dict]) -> list[AirportRef]:
    """OurAirports-CSV-Zeilen (DictReader) → AirportRef-Liste.

    Zeilen ohne brauchbare Koordinate oder ganz ohne Code werden übersprungen.
    """
    refs: list[AirportRef] = []
    for row in rows:
        try:
            lat = float(row["latitude_deg"])
            lon = float(row["longitude_deg"])
        except (KeyError, TypeError, ValueError):
            continue
        codes = {
            str(row.get(field) or "").strip().upper()
            for field in ("ident", "icao_code", "gps_code")
        }
        codes.discard("")
        if not codes:
            continue
        try:
            elevation_ft: float | None = float(row["elevation_ft"])
        except (KeyError, TypeError, ValueError):
            elevation_ft = None
        refs.append(
            AirportRef(
                code=str(row.get("ident") or "").strip().upper(),
                name=str(row.get("name") or "").strip(),
                lat=lat,
                lon=lon,
                elevation_ft=elevation_ft,
                codes=frozenset(codes),
            )
        )
    return refs


def load_ourairports(path: Path | str | None = None) -> list[AirportRef]:
    """OurAirports laden. ``path`` gesetzt → genau diese Datei (Tests: Fixture, kein Netz)."""
    if path is None:
        raise NotImplementedError("Cache/Download folgt in Task 4")
    with open(path, encoding="utf-8", newline="") as handle:
        return parse_ourairports(csv.DictReader(handle))


def find_code(code: str, refs: Sequence[AirportRef]) -> AirportRef | None:
    """Platz per Code suchen (case-insensitiv, über alle Alias-Codes). None = nicht vorhanden."""
    want = (code or "").strip().upper()
    if not want:
        return None
    for ref in refs:
        if want in ref.codes:
            return ref
    return None
```

- [ ] **Step 5: GREEN verifizieren**

Run: `python -m pytest tests/test_nearby_airports.py -v`
Expected: PASS (3 Tests). Ausgabe pristine — keine Warnings.

- [ ] **Step 6: Commit**

```bash
git add scripts/nearby_airports.py tests/fixtures/ourairports_mini.csv tests/test_nearby_airports.py
git commit -m "feat: Messwerkzeug track-diagnose — OurAirports-Parser mit Alias-Codes

EDHX und EBMO haben in OurAirports ein leeres icao_code-Feld; Codes werden
deshalb ueber ident/icao_code/gps_code gematcht."
```

---

### Task 2: airportsdata-Quelle, Nachbarschaftssuche und Messung

**Files:**
- Modify: `scripts/nearby_airports.py`
- Modify: `tests/test_nearby_airports.py`

**Interfaces:**
- Consumes: `AirportRef`, `load_ourairports`, `find_code` (Task 1)
- Produces:
  - `airportsdata_refs() -> list[AirportRef]`
  - `nearest(lat, lon, refs, limit=5) -> list[Hit]`
  - `Hit` (frozen dataclass): `ref: AirportRef`, `distance_km: float`, `agl_ft: float | None`
  - `Measurement` (frozen dataclass): `lat`, `lon`, `alt_ft`, `icao`, `ad_nearest: list[Hit]`, `oa_nearest: list[Hit]`, `ad_target: Hit | None`, `oa_target: Hit | None`, `source_delta_km: dict[str, float]`, `oa_available: bool`
  - `measure(lat, lon, *, alt_ft=None, icao=None, ad_refs=None, oa_refs=None) -> Measurement`

- [ ] **Step 1: Failing Tests schreiben**

Append to `tests/test_nearby_airports.py`:

```python
from scripts.nearby_airports import airportsdata_refs, measure

# Referenzpunkte, gemessen am 2026-07-15 aus statsim_position_history (alle groundspeed 0):
EDHX_PUNKT = (54.18665, 7.91488)    # Track 29258369, 7 ft   — Helgoland-Düne
ETUO_PUNKT = (51.85449, 10.02288)   # Track 23066993, 779 ft — Bad Gandersheim
EBKT_PUNKT = (50.82005, 3.2163)     # Track 28531653, 71 ft  — Kortrijk-Wevelgem


@pytest.fixture(scope="module")
def ad_refs():
    return airportsdata_refs()


@pytest.fixture(scope="module")
def oa_refs():
    return load_ourairports(FIXTURE)


def test_edhx_fall_d_schlaegt_fall_a(ad_refs, oa_refs):
    """EDHX fehlt in airportsdata und erfüllt damit FORMAL das Kriterium von Fall A
    („Code fehlt → Ergänzung"). Der Bodenpunkt liegt aber 0,16 km von EDXH — der Pilot
    hatte den Code verdreht. Deshalb kommt Schritt 1 (wohin gehört der Punkt?) vor
    Schritt 2 (was ist mit dem Code?). Dieser Test IST diese Regel."""
    m = measure(*EDHX_PUNKT, icao="EDHX", ad_refs=ad_refs, oa_refs=oa_refs)

    assert m.ad_target is None                                    # nicht in airportsdata
    assert m.oa_target is not None
    assert m.oa_target.distance_km == pytest.approx(132.70, abs=0.05)
    assert m.ad_nearest[0].ref.code == "EDXH"
    assert m.ad_nearest[0].distance_km == pytest.approx(0.16, abs=0.02)


def test_etuo_soll_code_nur_in_airportsdata(ad_refs, oa_refs):
    """Spiegelbild zu EDHX: ETUO steht in airportsdata, aber NICHT in OurAirports.
    Beide Blöcke müssen unabhängig „fehlt" melden können."""
    m = measure(*ETUO_PUNKT, icao="ETUO", ad_refs=ad_refs, oa_refs=oa_refs)

    assert m.ad_target is not None
    assert m.ad_target.distance_km == pytest.approx(118.05, abs=0.05)
    assert m.oa_target is None
    assert m.ad_nearest[0].ref.code == "EDVA"
    assert m.ad_nearest[0].distance_km == pytest.approx(0.19, abs=0.02)


def test_ebkt_quellen_weichen_um_37_km_ab(ad_refs, oa_refs):
    """Der Belgien-Fund. Wichtig ist die zweite Hälfte: der nächste airportsdata-Platz
    ist EBMO in 6,06 km — über der 1-km-Schwelle von Schritt 1. Wäre er näher, wäre
    der Fund fälschlich als Fall D abgetan worden."""
    m = measure(*EBKT_PUNKT, icao="EBKT", ad_refs=ad_refs, oa_refs=oa_refs)

    assert m.ad_target.distance_km == pytest.approx(37.20, abs=0.05)
    assert m.oa_target.distance_km == pytest.approx(0.49, abs=0.02)
    assert m.source_delta_km["EBKT"] == pytest.approx(37.00, abs=0.05)
    assert m.ad_nearest[0].ref.code == "EBMO"
    assert m.ad_nearest[0].distance_km == pytest.approx(6.06, abs=0.05)


def test_agl_wird_nur_mit_alt_und_bekannter_elevation_gerechnet(ad_refs, oa_refs):
    ohne = measure(*EBKT_PUNKT, icao="EBKT", ad_refs=ad_refs, oa_refs=oa_refs)
    assert ohne.ad_nearest[0].agl_ft is None

    # EBMO liegt laut airportsdata auf 66 ft (gemessen 2026-07-15 — nicht aus OurAirports
    # übernehmen, die Quellen können bei der Elevation auseinanderlaufen).
    mit = measure(*EBKT_PUNKT, alt_ft=71, icao="EBKT", ad_refs=ad_refs, oa_refs=oa_refs)
    assert mit.ad_nearest[0].ref.code == "EBMO"
    assert mit.ad_nearest[0].agl_ft == pytest.approx(5, abs=1)
```

- [ ] **Step 2: RED verifizieren**

Run: `python -m pytest tests/test_nearby_airports.py -v`
Expected: FAIL — `ImportError: cannot import name 'airportsdata_refs'`

- [ ] **Step 3: Implementieren**

Add to `scripts/nearby_airports.py` (Imports oben ergaenzen, Rest anhaengen):

```python
import airportsdata

from app.geo import haversine
```

```python
@dataclass(frozen=True)
class Hit:
    """Ein Platz mit gemessener Distanz zum untersuchten Punkt."""

    ref: AirportRef
    distance_km: float
    agl_ft: float | None


@dataclass(frozen=True)
class Measurement:
    """Reines Messergebnis — enthält bewusst KEINE Bewertung und keine Empfehlung.

    ``ad_target``/``oa_target`` sind ``None``, wenn der Soll-Code in der jeweiligen Quelle
    fehlt. Das ist Alltag, kein Fehler: EDHX steht nur in OurAirports, ETUO nur in
    airportsdata.
    """

    lat: float
    lon: float
    alt_ft: float | None
    icao: str | None
    ad_nearest: list[Hit]
    oa_nearest: list[Hit]
    ad_target: Hit | None
    oa_target: Hit | None
    source_delta_km: dict[str, float]
    oa_available: bool


def airportsdata_refs() -> list[AirportRef]:
    """Alle Plätze aus ``airportsdata``.

    Bewusst die Rohquelle: sie kennt keine ``custom_airports``. Über ``icao_to_coords()`` zu
    gehen wäre ein Fehler — das bezieht Overrides ein und macht jeden Vergleich „weicht der
    Override ab?" zu 0 km.
    """
    return [
        AirportRef(
            code=code,
            name=str(entry.get("name") or ""),
            lat=entry["lat"],
            lon=entry["lon"],
            elevation_ft=entry.get("elevation"),
            codes=frozenset({code}),
        )
        for code, entry in airportsdata.load("ICAO").items()
    ]


def _hit(lat: float, lon: float, alt_ft: float | None, ref: AirportRef) -> Hit:
    agl = None
    if alt_ft is not None and ref.elevation_ft is not None:
        agl = alt_ft - ref.elevation_ft
    return Hit(ref=ref, distance_km=haversine(lat, lon, ref.lat, ref.lon), agl_ft=agl)


def nearest(
    lat: float,
    lon: float,
    refs: Sequence[AirportRef],
    *,
    alt_ft: float | None = None,
    limit: int = 5,
) -> list[Hit]:
    """Die ``limit`` nächsten Plätze, aufsteigend nach Distanz. DIE Umkehrfrage."""
    hits = [_hit(lat, lon, alt_ft, ref) for ref in refs]
    hits.sort(key=lambda h: h.distance_km)
    return hits[:limit]


def measure(
    lat: float,
    lon: float,
    *,
    alt_ft: float | None = None,
    icao: str | None = None,
    ad_refs: Sequence[AirportRef] | None = None,
    oa_refs: Sequence[AirportRef] | None = None,
) -> Measurement:
    """Punkt gegen beide Referenzquellen messen. Ohne ``ad_refs``/``oa_refs`` werden sie geladen."""
    ad = list(ad_refs) if ad_refs is not None else airportsdata_refs()
    oa = list(oa_refs) if oa_refs is not None else load_ourairports()

    # Soll-Code in BEIDEN Quellen unabhängig suchen: ein Code kann in einer fehlen und in der
    # anderen stehen (EDHX nur OurAirports, ETUO nur airportsdata). None heisst „diese Quelle
    # kennt ihn nicht" — kein Fehler, sondern selbst ein Befund.
    ad_target = oa_target = None
    if icao:
        found_ad = find_code(icao, ad)
        if found_ad is not None:
            ad_target = _hit(lat, lon, alt_ft, found_ad)
        found_oa = find_code(icao, oa)
        if found_oa is not None:
            oa_target = _hit(lat, lon, alt_ft, found_oa)

    # Quellen-Abweichung für alle Codes, die in dieser Messung vorkommen.
    codes = {h.ref.code for h in nearest(lat, lon, ad, limit=5)}
    codes |= {h.ref.code for h in nearest(lat, lon, oa, limit=5)}
    if icao:
        codes.add(icao.strip().upper())
    delta: dict[str, float] = {}
    for code in codes:
        in_ad = find_code(code, ad)
        in_oa = find_code(code, oa)
        if in_ad is not None and in_oa is not None:
            delta[code] = haversine(in_ad.lat, in_ad.lon, in_oa.lat, in_oa.lon)

    return Measurement(
        lat=lat,
        lon=lon,
        alt_ft=alt_ft,
        icao=(icao or "").strip().upper() or None,
        ad_nearest=nearest(lat, lon, ad, alt_ft=alt_ft),
        oa_nearest=nearest(lat, lon, oa, alt_ft=alt_ft),
        ad_target=ad_target,
        oa_target=oa_target,
        source_delta_km=delta,
        oa_available=bool(oa),
    )
```

- [ ] **Step 4: GREEN verifizieren**

Run: `python -m pytest tests/test_nearby_airports.py -v`
Expected: PASS (7 Tests).

Weicht ein Distanzwert ab: **nicht die Zahl anpassen.** Die Werte sind gemessen; eine Abweichung heißt, dass sich `airportsdata` geändert hat oder die Rechnung falsch ist. Ursache klären, Nutzer informieren.

- [ ] **Step 5: Volle Suite**

Run: `python -m pytest tests/ -q`
Expected: 1047 bestehende + 7 neue = 1054 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/nearby_airports.py tests/test_nearby_airports.py
git commit -m "feat: Messwerkzeug track-diagnose — Nachbarschaftssuche und Messung

Kern ist die Umkehrfrage „welcher Platz liegt am naechsten?". Regressionstests
aus den realen Faellen EDHX (Fall D schlaegt Fall A), ETUO und EBKT."
```

---

### Task 3: Schwellen-Import, Report und CLI

**Files:**
- Modify: `scripts/nearby_airports.py`
- Modify: `tests/test_nearby_airports.py`

**Interfaces:**
- Consumes: `Measurement`, `measure`, `airportsdata_refs`, `load_ourairports` (Task 2)
- Produces:
  - `format_report(m: Measurement) -> str`
  - `main(argv: Sequence[str] | None = None) -> int`

- [ ] **Step 1: Failing Test schreiben**

Append to `tests/test_nearby_airports.py`:

```python
from app.database import _BUMMEL_AIRPORT_RADIUS_KM
from app.gps_legs import _GPS_SPAWN_MAX_AGL_FT
from scripts.nearby_airports import format_report

# Track 28133172 (FRS96, TBM9, EDDH->EDDM): erster Punkt, bereits airborne mit 217 kt.
EDDH_PUNKT = (53.49527, 10.00085)


def test_eddh_spawn_in_der_luft_reisst_beide_schwellen(ad_refs, oa_refs):
    """Der Punkt liegt 15,05 km von EDDH und 2156 ft über Platzhöhe. Ein Radius-Override
    würde NICHT helfen: die Spawn-Rettung (#49) verlangt zusätzlich < 1500 ft AGL.
    Beide Schwellen werden importiert — ändert jemand sie, wird dieser Test rot, statt
    dass der Skill still falsch wird."""
    m = measure(*EDDH_PUNKT, alt_ft=2209, icao="EDDH", ad_refs=ad_refs, oa_refs=oa_refs)

    assert m.ad_target.distance_km == pytest.approx(15.05, abs=0.05)
    assert m.ad_target.distance_km > _BUMMEL_AIRPORT_RADIUS_KM
    assert m.ad_target.agl_ft == pytest.approx(2156, abs=1)
    assert m.ad_target.agl_ft > _GPS_SPAWN_MAX_AGL_FT

    report = format_report(m)
    assert "außerhalb" in report
    assert "überschritten" in report


def test_report_meldet_fehlenden_code_statt_zu_verschweigen(ad_refs, oa_refs):
    report = format_report(measure(*EDHX_PUNKT, icao="EDHX", ad_refs=ad_refs, oa_refs=oa_refs))
    assert "nicht vorhanden" in report
    assert "EDXH" in report
```

- [ ] **Step 2: RED verifizieren**

Run: `python -m pytest tests/test_nearby_airports.py -v`
Expected: FAIL — `ImportError: cannot import name 'format_report'`

- [ ] **Step 3: Implementieren**

Add to `scripts/nearby_airports.py` (Imports oben ergaenzen):

```python
import argparse
import sys

from app.database import _BUMMEL_AIRPORT_RADIUS_KM
from app.gps_legs import _GPS_GROUND_AGL_FT, _GPS_SPAWN_MAX_AGL_FT
```

```python
def _threshold_notes(hit: Hit) -> list[str]:
    """Messwert gegen Detektor-Schwelle stellen — beschreibend, NICHT bewertend.

    Die Schwellen werden importiert, nie abgeschrieben: ändert jemand den Detektor,
    ändert sich diese Ausgabe mit.
    """
    notes = []
    inside = hit.distance_km <= _BUMMEL_AIRPORT_RADIUS_KM
    notes.append(
        "Standardradius %.1f km — %s" % (_BUMMEL_AIRPORT_RADIUS_KM, "innerhalb" if inside else "außerhalb")
    )
    if hit.agl_ft is not None:
        notes.append(
            "Spawn-Grenze %d ft — %s"
            % (_GPS_SPAWN_MAX_AGL_FT, "darunter" if hit.agl_ft < _GPS_SPAWN_MAX_AGL_FT else "überschritten")
        )
        notes.append(
            "Bodengrenze %d ft — %s"
            % (_GPS_GROUND_AGL_FT, "darunter" if hit.agl_ft < _GPS_GROUND_AGL_FT else "darüber")
        )
    return notes


def _format_hits(hits: Sequence[Hit]) -> list[str]:
    lines = []
    for hit in hits:
        agl = "  AGL %6.0f ft" % hit.agl_ft if hit.agl_ft is not None else " " * 14
        lines.append(
            "  %-8s %9.2f km%s   elev %6s ft   %s"
            % (hit.ref.code, hit.distance_km, agl, _fmt_elev(hit.ref.elevation_ft), hit.ref.name[:38])
        )
    return lines


def _fmt_elev(value: float | None) -> str:
    return "?" if value is None else "%.0f" % value


def format_report(m: Measurement) -> str:
    """Messergebnis als Text. Reine Darstellung — kein Urteil, keine Empfehlung."""
    out: list[str] = []
    alt = "" if m.alt_ft is None else "  (alt %.0f ft MSL)" % m.alt_ft
    out.append("Punkt: %.5f, %.5f%s" % (m.lat, m.lon, alt))

    if m.icao:
        out.append("")
        out.append("Soll-Code laut Flugplan: %s" % m.icao)
        for label, hit in (("airportsdata", m.ad_target), ("OurAirports", m.oa_target)):
            if hit is None:
                out.append("  %-13s in dieser Quelle nicht vorhanden" % label)
                continue
            out.append("  %-13s %9.2f km   %s" % (label, hit.distance_km, hit.ref.name[:40]))
            for note in _threshold_notes(hit):
                out.append("  %-13s   (%s)" % ("", note))

    out.append("")
    out.append("Nächste Plätze laut airportsdata:")
    out.extend(_format_hits(m.ad_nearest))

    out.append("")
    if not m.oa_available:
        out.append("Nächste Plätze laut OurAirports: -- nicht geladen (kein Netz/Cache)")
    else:
        out.append("Nächste Plätze laut OurAirports:")
        out.extend(_format_hits(m.oa_nearest))

    if m.source_delta_km:
        out.append("")
        out.append("Abweichung airportsdata <-> OurAirports:")
        for code, delta in sorted(m.source_delta_km.items(), key=lambda kv: -kv[1]):
            out.append("  %-8s %9.2f km" % (code, delta))

    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Messwerkzeug für die Track-Diagnose — misst, urteilt nicht.",
    )
    parser.add_argument("lat", type=float)
    parser.add_argument("lon", type=float)
    parser.add_argument("--alt", type=float, default=None, help="Höhe in ft MSL (für AGL)")
    parser.add_argument("--icao", default=None, help="Soll-Code aus dem Flugplan")
    args = parser.parse_args(argv)

    print(format_report(measure(args.lat, args.lon, alt_ft=args.alt, icao=args.icao)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: GREEN verifizieren**

Run: `python -m pytest tests/test_nearby_airports.py -v`
Expected: PASS (9 Tests).

- [ ] **Step 5: Volle Suite**

Run: `python -m pytest tests/ -q`
Expected: 1056 passed (1047 bestehende + 9 neue).

Die CLI ist bis Task 4 **noch nicht lauffähig**: `load_ourairports()` ohne Pfad wirft bis dahin `NotImplementedError`. Das ist beabsichtigt — der reale Lauf steht in Task 4, Step 4.

- [ ] **Step 6: Commit**

```bash
git add scripts/nearby_airports.py tests/test_nearby_airports.py
git commit -m "feat: Messwerkzeug track-diagnose — Report und CLI

Schwellen werden aus app/gps_legs.py und app/database.py importiert, nie
abgeschrieben: der EDDH-Test wird rot, wenn jemand den Detektor aendert."
```

---

### Task 4: OurAirports-Cache und Download

**Files:**
- Modify: `scripts/nearby_airports.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `load_ourairports` (Task 1), `main` (Task 3)
- Produces: `load_ourairports()` funktioniert ohne Pfad-Argument (Cache + Download)

Kein automatisierter Test: Der Pfad hängt am Netz und am Dateisystem. Der Wert liegt in der manuellen Verifikation (Step 4/5). Die Kernlogik (Parsen, Suchen, Messen) ist über den injizierbaren Pfad bereits in Task 1–3 abgedeckt — genau dafür ist er da.

- [ ] **Step 1: `.gitignore` ergänzen**

Modify `.gitignore` — nach dem Block `# Claude Code Worktrees` anhängen:

```gitignore

# OurAirports-Abzug für scripts/nearby_airports.py (12 MB, jederzeit neu ladbar)
scripts/.cache/
```

- [ ] **Step 2: Cache implementieren**

Replace `load_ourairports` in `scripts/nearby_airports.py`:

```python
OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "ourairports.csv"
CACHE_MAX_AGE_DAYS = 30


def _cached_ourairports() -> Path | None:
    """Pfad zum OurAirports-Abzug; laedt ihn bei Bedarf. ``None`` = nicht verfuegbar.

    Ohne Netz wird ein vorhandener (auch alter) Cache weiterverwendet — ein veralteter
    Abzug ist brauchbarer als gar keine Gegenprobe, solange wir es sagen.
    """
    if CACHE_PATH.exists():
        age_days = (time.time() - CACHE_PATH.stat().st_mtime) / 86400.0
        if age_days < CACHE_MAX_AGE_DAYS:
            return CACHE_PATH
    try:
        import httpx

        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        response = httpx.get(OURAIRPORTS_URL, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
        CACHE_PATH.write_bytes(response.content)
        return CACHE_PATH
    except Exception as exc:  # Netz weg, DNS, 404 — kein Grund, die Analyse abzubrechen
        if CACHE_PATH.exists():
            print("  ! OurAirports-Update fehlgeschlagen (%s) — nutze alten Cache" % exc, file=sys.stderr)
            return CACHE_PATH
        print("  ! OurAirports nicht verfuegbar (%s) — nur airportsdata" % exc, file=sys.stderr)
        return None


def load_ourairports(path: Path | str | None = None) -> list[AirportRef]:
    """OurAirports laden. ``path`` gesetzt → genau diese Datei (Tests: Fixture, kein Netz).

    Ohne ``path``: Cache unter ``scripts/.cache/``, bei Bedarf frisch geladen. Ist die
    Quelle nicht verfuegbar, kommt eine LEERE Liste zurück — das Werkzeug arbeitet dann
    nur mit airportsdata weiter und sagt das im Report (``oa_available``).
    """
    source = Path(path) if path is not None else _cached_ourairports()
    if source is None:
        return []
    with open(source, encoding="utf-8", newline="") as handle:
        return parse_ourairports(csv.DictReader(handle))
```

Import oben ergänzen:

```python
import time
```

- [ ] **Step 3: Tests bleiben grün**

Run: `python -m pytest tests/test_nearby_airports.py -v`
Expected: PASS (9 Tests) — die Fixture-Tests übergeben weiterhin einen Pfad, das Netz wird nicht berührt.

- [ ] **Step 4: Download real verifizieren**

Run: `python scripts/nearby_airports.py 53.49527 10.00085 --alt 2209 --icao EDDH`
Expected: Erster Lauf lädt ~12 MB nach `scripts/.cache/ourairports.csv`. Report zeigt EDDH 15.05 km / „außerhalb" / AGL 2156 ft / „überschritten".

Run: `git status --short`
Expected: `scripts/.cache/` taucht **nicht** auf.

- [ ] **Step 5: Die drei anderen Referenzfälle real gegenprüfen**

```bash
python scripts/nearby_airports.py 54.18665 7.91488 --icao EDHX
python scripts/nearby_airports.py 51.85449 10.02288 --icao ETUO
python scripts/nearby_airports.py 50.82005 3.2163  --icao EBKT
```

Expected (gemessen 2026-07-15):
- EDHX: airportsdata „nicht vorhanden", OurAirports 132,70 km, nächster Platz EDXH 0,16 km
- ETUO: airportsdata 118,05 km, OurAirports „nicht vorhanden", nächster Platz EDVA 0,19 km
- EBKT: airportsdata 37,20 km, OurAirports 0,49 km, Abweichung EBKT 37,00 km

- [ ] **Step 6: Commit**

```bash
git add scripts/nearby_airports.py .gitignore
git commit -m "feat: Messwerkzeug track-diagnose — OurAirports-Cache

Abzug wird nach scripts/.cache/ geladen (30 Tage gueltig, gitignored). Ohne Netz
faellt das Werkzeug auf airportsdata zurueck, statt abzubrechen."
```

---

### Task 5: Triage über die Lückenliste

**Files:**
- Create: `scripts/triage_gaps.py`
- Create: `tests/fixtures/gaps_mini.json`
- Create: `tests/test_triage_gaps.py`

**Interfaces:**
- Consumes: `measure`, `nearest`, `find_code`, `airportsdata_refs`, `load_ourairports`, `AirportRef`, `Hit` (Tasks 1–4)
- Produces:
  - `Ende` (frozen dataclass): `statsim_id: int`, `callsign: str`, `seite: str`, `soll: str | None`, `punkt: dict`, `punkte: int`
  - `enden_aus_export(faelle: Sequence[dict]) -> list[Ende]`
  - `Befund` (frozen dataclass): `ende: Ende`, `gruppe: str`, `begruendung: str`
  - `triagiere(ende: Ende, ad_refs, oa_refs) -> Befund`
  - `main(argv: Sequence[str] | None = None) -> int`

Gruppen-Konstanten: `GRUPPE_DUENN = "Zu dünn"`, `GRUPPE_ZZZZ = "ZZZZ"`, `GRUPPE_LUFT = "E"`, `GRUPPE_ANDERER = "D"`, `GRUPPE_KANDIDAT = "Kandidat"`.

- [ ] **Step 1: Fixture anlegen**

Sechs **echte** Fälle aus dem Export vom 2026-07-15, einer je Gruppe. Exakt übernehmen.

Create `tests/fixtures/gaps_mini.json`:

```json
[
 {"statsim_id": 27831625, "callsign": "FRS96", "missing": "both",
  "plan_departure": "EDDM", "plan_arrival": "EDNR",
  "logon_time": "2026-03-31T18:34:07Z", "punkte": 1,
  "first": {"ts": "2026-03-31T19:31:00+00:00", "lat": 49.14175, "lon": 12.08123, "alt": 1263, "gs": 0},
  "last":  {"ts": "2026-03-31T19:31:00+00:00", "lat": 49.14175, "lon": 12.08123, "alt": 1263, "gs": 0}},
 {"statsim_id": 27404430, "callsign": "FRS116", "missing": "departure",
  "plan_departure": "ZZZZ", "plan_arrival": "EDAC",
  "logon_time": "2026-03-06T19:50:59+00:00", "punkte": 138,
  "first": {"ts": "2026-03-06T19:50:59+00:00", "lat": 51.13781, "lon": 13.00038, "alt": 1681, "gs": 147},
  "last":  {"ts": "2026-03-06T20:25:29+00:00", "lat": 50.97776, "lon": 12.5079, "alt": 641, "gs": 0}},
 {"statsim_id": 28133172, "callsign": "FRS96", "missing": "departure",
  "plan_departure": "EDDH", "plan_arrival": "EDDM",
  "logon_time": "2026-04-18T14:10:09+00:00", "punkte": 329,
  "first": {"ts": "2026-04-18T14:10:09+00:00", "lat": 53.49527, "lon": 10.00085, "alt": 2209, "gs": 217},
  "last":  {"ts": "2026-04-18T15:35:24+00:00", "lat": 48.35364, "lon": 11.80488, "alt": 1480, "gs": 0}},
 {"statsim_id": 26626195, "callsign": "FRS119N", "missing": "both",
  "plan_departure": "EDLJ", "plan_arrival": "EDLI",
  "logon_time": "2026-01-20T19:08:27Z", "punkte": 6,
  "first": {"ts": "2026-01-20T20:43:32+00:00", "lat": 51.96475, "lon": 8.54481, "alt": 455, "gs": 28},
  "last":  {"ts": "2026-01-20T20:54:18+00:00", "lat": 51.96554, "lon": 8.54987, "alt": 467, "gs": 0}},
 {"statsim_id": 28099919, "callsign": "FRS177", "missing": "both",
  "plan_departure": "RCLM", "plan_arrival": "VHHX",
  "logon_time": "2026-04-16T14:32:24+00:00", "punkte": 303,
  "first": {"ts": "2026-04-16T14:30:24+00:00", "lat": 20.70407, "lon": 116.72727, "alt": 9, "gs": 0},
  "last":  {"ts": "2026-04-16T15:48:54+00:00", "lat": 22.32407, "lon": 114.19682, "alt": 33, "gs": 0}},
 {"statsim_id": 25216444, "callsign": "FRS125", "missing": "both",
  "plan_departure": "ETNJ", "plan_arrival": "EDWI",
  "logon_time": "2025-10-28T20:11:31+00:00", "punkte": 18,
  "first": {"ts": "2025-10-28T20:10:31+00:00", "lat": 53.40635, "lon": 7.90957, "alt": 4401, "gs": 22},
  "last":  {"ts": "2025-10-28T20:19:27+00:00", "lat": 53.42051, "lon": 7.912, "alt": 143, "gs": 68}}
]
```

- [ ] **Step 2: Failing Tests schreiben**

Create `tests/test_triage_gaps.py`:

```python
"""Triage-Tests: sechs echte Fälle aus dem Export vom 2026-07-15, einer je Gruppe.

Jeder Test sichert eine Regel ab, die beim Entwurf real falsch war. Siehe
docs/superpowers/specs/2026-07-15-track-diagnose-design.md
"""
import json
from pathlib import Path

import pytest

from scripts.nearby_airports import airportsdata_refs, load_ourairports
from scripts.triage_gaps import (
    GRUPPE_ANDERER,
    GRUPPE_DUENN,
    GRUPPE_KANDIDAT,
    GRUPPE_LUFT,
    GRUPPE_ZZZZ,
    enden_aus_export,
    triagiere,
)

FIXTURE = Path(__file__).parent / "fixtures" / "gaps_mini.json"
OA_FIXTURE = Path(__file__).parent / "fixtures" / "ourairports_mini.csv"


@pytest.fixture(scope="module")
def faelle():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ad():
    return airportsdata_refs()


@pytest.fixture(scope="module")
def oa():
    return load_ourairports(OA_FIXTURE)


def _gruppe(faelle, ad, oa, statsim_id, seite):
    for ende in enden_aus_export(faelle):
        if ende.statsim_id == statsim_id and ende.seite == seite:
            return triagiere(ende, ad, oa).gruppe
    raise AssertionError("Ende %s/%s nicht im Export" % (statsim_id, seite))


def test_both_erzeugt_zwei_enden(faelle):
    enden = [e for e in enden_aus_export(faelle) if e.statsim_id == 25216444]
    assert sorted(e.seite for e in enden) == ["arrival", "departure"]
    # 29 der 163 Fälle vermissen beide Enden; eines kann trivial sein, das andere nicht.
    assert len(enden_aus_export(faelle)) == 10   # 6 Fälle, 4 davon "both"


def test_ein_punkt_track_schlaegt_nachbarschaft(faelle, ad, oa):
    """27831625 hat EINEN Trackpunkt, und EDNR liegt 0,06 km daneben. Ohne die
    Punktzahl-Prüfung wäre das ein Fall-D-Befund — formal richtig gemessen und
    trotzdem Unsinn. Sechs der urspruenglich neun D-Befunde waren solche Tracks."""
    assert _gruppe(faelle, ad, oa, 27831625, "departure") == GRUPPE_DUENN


def test_zzzz_schlaegt_luft(faelle, ad, oa):
    """27404430 ist mit gs 147 auch in der Luft. ZZZZ ist die staerkere Aussage:
    es gibt keinen Platz zu finden."""
    assert _gruppe(faelle, ad, oa, 27404430, "departure") == GRUPPE_ZZZZ


def test_eddh_spawn_in_der_luft(faelle, ad, oa):
    assert _gruppe(faelle, ad, oa, 28133172, "departure") == GRUPPE_LUFT


def test_stol_langsam_aber_hoch_ist_nicht_am_boden(faelle, ad, oa):
    """FRS125 ab ETNJ: gs 22 — nach einer groundspeed-zentrierten Regel ein Bodenpunkt.
    Die Höhe sagt 4401 ft. Höhe ist das Leitsignal (app/gps_legs.py:4), sonst werden
    STOL-Flüge (Wilga, ~40 kt Reise) systematisch fehlklassifiziert. Gemessen: 13 der
    184 Enden erkennt nur die Höhe."""
    assert _gruppe(faelle, ad, oa, 25216444, "departure") == GRUPPE_LUFT


def test_punkt_an_anderem_platz(faelle, ad, oa):
    assert _gruppe(faelle, ad, oa, 26626195, "departure") == GRUPPE_ANDERER


def test_bodenpunkt_ohne_nachbarn_bleibt_kandidat(faelle, ad, oa):
    """RCLM: Bodenpunkt, nächster bekannter Platz 302 km weit. Genau so ein Fall
    braucht ein Urteil — er darf NICHT wegtriagiert werden."""
    assert _gruppe(faelle, ad, oa, 28099919, "departure") == GRUPPE_KANDIDAT
```

- [ ] **Step 3: RED verifizieren**

Run: `python -m pytest tests/test_triage_gaps.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.triage_gaps'`

- [ ] **Step 4: Implementieren**

Create `scripts/triage_gaps.py`:

```python
"""Triage der Erkennungsluecken-Liste (Skill ``track-diagnose``).

Liest den JSON-Export (siehe SKILL.md), misst je Fall das fragliche Ende und gruppiert nach
Schritt 0 und Schritt 1 der Pruefreihenfolge — beides reine Messungen. Schritt 2 braucht
Kontext und bleibt beim Assistenten.

**Sortiert, entscheidet aber nichts.** Auch ein Sammelbefund „128x Fall E" wird vom Nutzer
abgehakt, nicht von hier.

Rein: JSON rein, Gruppen raus. Kein DB-Zugriff, kein SSH.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.gps_legs import _GPS_FLYING_GS_KT, _GPS_GROUND_AGL_FT
from scripts.nearby_airports import (
    AirportRef,
    airportsdata_refs,
    find_code,
    load_ourairports,
    nearest,
)

GRUPPE_DUENN = "Zu dünn"
GRUPPE_ZZZZ = "ZZZZ"
GRUPPE_LUFT = "E"
GRUPPE_ANDERER = "D"
GRUPPE_KANDIDAT = "Kandidat"

# Der Detektor braucht mindestens einen Zustandswechsel (ON_GROUND -> AIRBORNE -> ON_GROUND).
# Bei weniger Samples ist jede Aussage über Start/Landung bedeutungslos.
MIN_TRACKPUNKTE = 3
# Flugplan-Platzhalter für „kein ICAO" — kein Platz, also nichts zu finden.
PLATZHALTER_CODE = "ZZZZ"
# Ab hier gilt ein Nachbarplatz als „der Punkt gehört dorthin" (Schritt 1).
NACHBAR_MAX_KM = 1.0


@dataclass(frozen=True)
class Ende:
    """Ein zu prüfendes Ende eines Falls. ``missing: "both"`` ergibt zwei davon."""

    statsim_id: int
    callsign: str
    seite: str            # "departure" | "arrival"
    soll: str | None
    punkt: dict
    punkte: int


@dataclass(frozen=True)
class Befund:
    ende: Ende
    gruppe: str
    begruendung: str


def enden_aus_export(faelle: Sequence[dict]) -> list[Ende]:
    """JSON-Export → zu prüfende Enden. ``both`` ergibt zwei (Start und Ziel)."""
    enden: list[Ende] = []
    for fall in faelle:
        missing = fall.get("missing")
        for seite, punkt_key, soll_key in (
            ("departure", "first", "plan_departure"),
            ("arrival", "last", "plan_arrival"),
        ):
            if missing not in (seite, "both"):
                continue
            enden.append(
                Ende(
                    statsim_id=fall["statsim_id"],
                    callsign=fall.get("callsign") or "",
                    seite=seite,
                    soll=(fall.get(soll_key) or None),
                    punkt=fall[punkt_key],
                    punkte=int(fall.get("punkte") or 0),
                )
            )
    return enden


def _in_der_luft(punkt: dict, basis: AirportRef | None) -> tuple[bool, str]:
    """Höhe fuehrt, Groundspeed hilft — wie im Detektor (app/gps_legs.py:4).

    Groundspeed allein genuegt NICHT: STOL/Heli fliegen langsam (Wilga ~40 kt Reise), eine
    gs-zentrierte Regel wertet sie als Bodenpunkt. Gemessen an 184 Enden: 13 erkennt nur die
    Höhe, 5 nur die Groundspeed — beide Signale sind noetig.
    """
    alt = punkt.get("alt")
    gs = punkt.get("gs") or 0
    if alt is not None and basis is not None and basis.elevation_ft is not None:
        agl = alt - basis.elevation_ft
        if agl > _GPS_GROUND_AGL_FT:
            return True, "AGL %.0f ft (> %d)" % (agl, _GPS_GROUND_AGL_FT)
    if gs >= _GPS_FLYING_GS_KT:
        return True, "gs %d kt (>= %d)" % (gs, _GPS_FLYING_GS_KT)
    return False, ""


def triagiere(
    ende: Ende,
    ad_refs: Sequence[AirportRef],
    oa_refs: Sequence[AirportRef],
) -> Befund:
    """Schritt 0 und Schritt 1 der Pruefreihenfolge. Erste greifende Gruppe gewinnt."""
    if ende.punkte < MIN_TRACKPUNKTE:
        return Befund(ende, GRUPPE_DUENN, "Track hat nur %d Punkt(e)" % ende.punkte)

    if (ende.soll or "").upper() == PLATZHALTER_CODE:
        return Befund(ende, GRUPPE_ZZZZ, "Flugplan-Platzhalter — kein Platz")

    # AGL-Basis: bevorzugt der Soll-Platz, sonst der naechstgelegene (bei fehlendem Code).
    lat, lon = ende.punkt["lat"], ende.punkt["lon"]
    nachbarn = nearest(lat, lon, ad_refs, limit=1)
    basis = find_code(ende.soll or "", ad_refs) or find_code(ende.soll or "", oa_refs)
    if basis is None and nachbarn:
        basis = nachbarn[0].ref

    luft, warum = _in_der_luft(ende.punkt, basis)
    if luft:
        return Befund(ende, GRUPPE_LUFT, "kein Bodenpunkt: %s" % warum)

    if nachbarn:
        hit = nachbarn[0]
        if hit.ref.code != (ende.soll or "").upper() and hit.distance_km < NACHBAR_MAX_KM:
            return Befund(
                ende, GRUPPE_ANDERER,
                "Punkt liegt %.2f km an %s (Soll: %s)" % (hit.distance_km, hit.ref.code, ende.soll),
            )
        return Befund(ende, GRUPPE_KANDIDAT, "nächster Platz: %s %.2f km" % (hit.ref.code, hit.distance_km))
    return Befund(ende, GRUPPE_KANDIDAT, "kein Platz in Reichweite")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Triage der Erkennungsluecken — sortiert, urteilt nicht.")
    parser.add_argument("export", type=Path, help="gaps.json (siehe SKILL.md)")
    parser.add_argument("--gruppe", default=None, help="nur diese Gruppe ausgeben")
    args = parser.parse_args(argv)

    faelle = json.loads(args.export.read_text(encoding="utf-8"))
    ad, oa = airportsdata_refs(), load_ourairports()
    befunde = [triagiere(e, ad, oa) for e in enden_aus_export(faelle)]

    zaehler = Counter(b.gruppe for b in befunde)
    print("%d Enden aus %d Fällen\n" % (len(befunde), len(faelle)))
    for gruppe, anzahl in zaehler.most_common():
        print("  %-10s %4d  (%4.1f%%)" % (gruppe, anzahl, 100.0 * anzahl / len(befunde)))
    mechanisch = len(befunde) - zaehler[GRUPPE_KANDIDAT]
    print("\n  mechanisch abgehakt: %d von %d" % (mechanisch, len(befunde)))

    zeigen = args.gruppe or GRUPPE_KANDIDAT
    print("\n--- %s ---" % zeigen)
    for b in befunde:
        if b.gruppe != zeigen:
            continue
        print("  %-9s %-8s %-9s soll=%-6s  %s"
              % (b.ende.statsim_id, b.ende.callsign, b.ende.seite, b.ende.soll or "-", b.begruendung))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: GREEN verifizieren**

Run: `python -m pytest tests/test_triage_gaps.py -v`
Expected: PASS (7 Tests).

- [ ] **Step 6: Volle Suite**

Run: `python -m pytest tests/ -q`
Expected: 1063 passed (1047 bestehende + 9 aus Task 1–3 + 7 neue).

- [ ] **Step 7: Commit**

```bash
git add scripts/triage_gaps.py tests/fixtures/gaps_mini.json tests/test_triage_gaps.py
git commit -m "feat: Triage der Erkennungsluecken-Liste

Misst Schritt 0/1 der Pruefreihenfolge ueber alle Faelle und gruppiert. Gemessen
am Stand 2026-07-15: 87,5 Prozent der 184 Enden sind mechanisch abzuhaken, 23
brauchen ein Urteil.

Zwei Regeln, die beim Entwurf real falsch waren und jetzt Tests haben:
- Punktzahl vor Nachbarschaft (6 von 9 D-Befunden waren Ein-Punkt-Tracks)
- Hoehe vor Groundspeed (13 Enden waeren als Bodenpunkt fehlklassifiziert;
  STOL fliegt langsam)"
```

---

### Task 6: SKILL.md und README-Korrektur

**Files:**
- Create: `.claude/skills/track-diagnose/SKILL.md`
- Modify: `README.md:75`

**Interfaces:**
- Consumes: `scripts/nearby_airports.py` (Tasks 1–4)
- Produces: nichts (Endpunkt)

- [ ] **Step 1: SKILL.md schreiben**

Create `.claude/skills/track-diagnose/SKILL.md`:

````markdown
---
name: track-diagnose
description: Use when working through the FriesenSpy Erkennungslücken list (/admin) or analyzing why a flight's departure/arrival airport was not recognized from GPS — triaging the whole list, diagnosing a single track where an airport seems missing or misplaced, or finding flights without a flight plan. Produces verdicts with evidence, never enters corrections.
---

# FriesenSpy — Track-Diagnose

## Überblick

Beantwortet: *Warum hängt dieser Flug an Platz X?* — für die ganze Liste oder einen Einzelfall.

**Erst triagieren, dann einzeln prüfen.** Die Lückenliste hatte am 2026-07-15 163 Fälle
(184 Enden, weil 29 Fälle beide Enden vermissen). **87,5 % davon sind rein mechanisch abzuhaken.**
Wer sie einzeln durchgeht, hört drei von vier Mal „Aufzeichnungslücke, nichts zu tun".

**Dieser Skill trägt nichts ein.** Er liefert Diagnose, Belege und ggf. einen konkreten
Vorschlag (ICAO, Koordinate, Radius, Grund). Das Eintragen macht der Nutzer über die Admin-UI —
jeder Write stößt einen vollen `rebuild_flight_cache` an, und genau die Fälle, die „klar"
aussahen, waren die falschen. Für die Triage gilt dasselbe: sie sortiert, sie entscheidet nicht.
Auch ein Sammelbefund „128× Fall E" wird vom Nutzer abgehakt.

**Nicht Teil dieses Skills:** das Vollaudit der gesamten Historie (Modus-Cluster über viele Flüge
je Platz). Andere Frage, andere Fallstricke.

## Die Asymmetrie — zuerst lesen

Ein **fehlender** Eintrag kostet eine unerkannte Strecke. Ein **falscher** Eintrag verschiebt
einen realen Flugplatz für *alle* Auswertungen (Statistik, Bummel, Kutter) — unbemerkt, weil
`icao_to_coords` brav weiter einen Treffer liefert. Die Fehler sind nicht gleich teuer.

**Im Zweifel wird nichts eingetragen.**

## Datenzugang (nur lesend)

```bash
ssh -i ~/.ssh/tsbot_server root@167.86.127.129 "sqlite3 -header -column /opt/friesenspy/data/friesenspy.db \"<SQL>\""
```

Stolpersteine:
- Der Host-Alias `friesenspy` **existiert nicht** — Verbindung über die IP.
- Key ist `~/.ssh/tsbot_server`, nicht der Default-Key.
- `flight_cache` hat **keine** Spalte `statsim_id`.
- Der API-Weg ist **kein** Ersatz: alle Endpoints verlangen Login, auch
  `/api/flights/statsim/{id}/track`.
- **Niemals schreiben.** Korrekturen laufen über die Admin-UI beim Nutzer.

## Ablauf A — Triage (die ganze Liste)

### A1. Export ziehen

Die Lückenliste **muss aus der App kommen**, nicht per SQL nachgebaut: `list_gps_detection_gaps`
ruft `canonicalize_legs` über die ganze Historie. Nachgebaut triagiert man eine andere Liste als
die, die im Admin steht.

```bash
ssh -i ~/.ssh/tsbot_server root@167.86.127.129 "docker exec friesenspy-friesenspy-1 python -c '
import json
from app import geo
from app.config import get_settings
from app.database import get_connection, list_gps_detection_gaps, list_custom_airports
conn = get_connection(get_settings().DB_PATH)
geo.set_custom_airports(list_custom_airports(conn))
out = []
for g in list_gps_detection_gaps(conn):
    sid = g.get("statsim_id")
    if not sid: continue
    rows = conn.execute("SELECT ts, latitude, longitude, altitude, groundspeed FROM statsim_position_history WHERE statsim_id=? ORDER BY ts", (sid,)).fetchall()
    if not rows: continue
    f, l = rows[0], rows[-1]
    out.append({"statsim_id": sid, "callsign": g["callsign"], "missing": g["missing"],
      "plan_departure": g["plan_departure"], "plan_arrival": g["plan_arrival"],
      "logon_time": g["logon_time"], "punkte": len(rows),
      "first": {"ts": f[0], "lat": f[1], "lon": f[2], "alt": f[3], "gs": f[4]},
      "last":  {"ts": l[0], "lat": l[1], "lon": l[2], "alt": l[3], "gs": l[4]}})
print(json.dumps(out))
'" > gaps.json
```

Dauert ~18 s, liefert ~75 KB für 163 Fälle.

> **`geo.set_custom_airports(...)` ist PFLICHT, nicht Deko.** `docker exec python -c` startet einen
> frischen Prozess; `geo._CUSTOM_AIRPORTS` wird sonst nie befüllt (das macht der Lifespan,
> `app/main.py:204`). Ohne die Zeile fehlen **sämtliche** Korrekturen: der erste Testlauf lieferte
> 199 statt 163 Fälle — 36 Phantom-Lücken an längst gefixten Plätzen (EDEN, EBBR, ELLX, EDDF).

> **Niemals die DB kopieren.** 42 MB mit Push-Subscriptions, Pilotennamen und Tokens; die Triage
> braucht davon nichts.

### A2. Triagieren

```bash
python scripts/triage_gaps.py gaps.json                 # Zusammenfassung + Kandidaten
python scripts/triage_gaps.py gaps.json --gruppe E      # eine Gruppe im Detail
```

### A3. Berichten

Trivialgruppen als **Sammelbefund** melden (nicht einzeln durchkauen), Kandidaten als Arbeitsvorrat
für Ablauf B. Stand 2026-07-15: 128× E, 19× zu dünn, 11× ZZZZ, 3× D — **23 Kandidaten**.

## Ablauf B — Einzelfall

### 1. Fall aufnehmen

Einstieg ist ein Kandidat aus der Triage oder eine Track-URL vom Nutzer:
`…/#tab=statistiken&track=<statsim_id>&src=statsim`.

```sql
SELECT * FROM statsim_cache WHERE statsim_id = <id>;
```

Liefert `departure`/`arrival` (das **Soll** aus dem Flugplan), `logon_time`, `duration_min`.

### 2. Track-Ränder ziehen

```sql
SELECT COUNT(*), MIN(ts), MAX(ts), MIN(altitude), MIN(groundspeed)
FROM statsim_position_history WHERE statsim_id = <id>;

SELECT ts, latitude, longitude, altitude, groundspeed
FROM statsim_position_history WHERE statsim_id = <id> ORDER BY ts LIMIT 10;

SELECT ts, latitude, longitude, altitude, groundspeed
FROM statsim_position_history WHERE statsim_id = <id> ORDER BY ts DESC LIMIT 10;
```

### 3. Aktuellen Custom-Stand prüfen

```sql
SELECT icao, lat, lon, elevation_ft, radius_km, reason FROM custom_airports ORDER BY icao;
```

Sonst schlägt man einen Eintrag vor, den es längst gibt.

### 4. Messen

```bash
python scripts/nearby_airports.py <lat> <lon> [--alt <ft MSL>] [--icao <Soll-Code>]
```

Das Werkzeug misst, es urteilt nicht. Es zeigt die nächsten Plätze laut **airportsdata** und
**OurAirports**, die Abweichung beider Quellen und — mit `--icao` — die Distanz zum Soll-Code,
jeweils gegen die importierten Detektor-Schwellen (4 km Radius, 1500 ft Spawn, 300 ft Boden).

### 5. Urteil nach der Prüfreihenfolge (unten) und Bericht an den Nutzer

## Prüfreihenfolge — nicht verhandelbar

**Schritt 0 — Gibt es an *diesem* Ende überhaupt einen Bodenpunkt?**
Je Ende, nicht je Track: Ein Track kann am Ziel sauber aufsetzen und am Start in der Luft
beginnen. Geprüft wird der Randpunkt, um den es geht.

**Höhe führt, Groundspeed hilft** — dieselbe Gewichtung wie im Detektor (`app/gps_legs.py:4`:
*„Höhe (AGL) ist das Leitsignal, Groundspeed nur sekundär — STOL/Heli fliegen langsam"*):

```
in_der_luft = (AGL > 300 ft)  ODER  (groundspeed >= 50 kt)
```

AGL gegen die Elevation des Soll-Platzes; fehlt der Code in beiden Quellen, gegen die des
nächstgelegenen. Beide Signale nötig, keines genügt: von 184 Enden erkennt **13 nur die Höhe**
(Groundspeed sagt fälschlich „Boden" — Wilga fliegt ~40 kt Reise), **5 nur die Groundspeed**.

Kein Bodenpunkt → **Fall E**, Ende.

**Vorgelagert: hat der Track überhaupt genug Punkte?** Unter 3 Samples ist kein Zustandswechsel
möglich und jede Aussage bedeutungslos — auch eine gemessene. Sechs von neun vermeintlichen
D-Befunden waren Ein-Punkt-Tracks.

> Beispiel EDDH (Track 28133172): erster Punkt 2209 ft, 217 kt, 15 km vom Platz — der VATSIM-
> Logon lag 9 Sekunden davor, der Pilot verband sich im Steigflug. Es gab nie einen Startpunkt;
> jede Radiusüberlegung war gegenstandslos.

**Schritt 1 — Wohin gehört der Bodenpunkt?**
Die Umkehrfrage: nicht „passt der Punkt zum Code", sondern „welcher Platz liegt am nächsten",
in **beiden** Quellen. Anderer Platz unter 1 km → **Fall D**, Ende.

> **Warum diese Reihenfolge zwingend ist — der EDHX-Beleg:** `EDHX` steht **nicht in
> airportsdata** und erfüllt damit *formal das Kriterium von Fall A*. Wer bei Schritt 2
> einsteigt, trägt einen Platz ein. Schritt 1 zeigt: der Bodenpunkt liegt 0,16 km von **EDXH**
> (Helgoland-Düne) — der Code war verdreht. `EDHX` existiert real, aber als *Bad Bramstedt
> Heliport*, 132,70 km entfernt. **Fall D schlägt Fall A**, immer.

**Schritt 2 — Erst jetzt der Code.** Siehe Fallliste.

**Merksatz:** Erst fragen, ob es einen Bodenpunkt gibt, dann wohin er gehört, und erst zuletzt,
was mit dem Code los ist.

## Die sechs Fälle

| Fall | Befund | Handlung |
|---|---|---|
| **A** | Code fehlt in airportsdata — **und Schritt 1 fand keinen anderen Platz** | Ergänzung, Grund `Fehlt in airportsdata` |
| **B** | Code steht drin (> 3 km weg), OurAirports liegt auf dem Punkt | Koordinaten-Override, Grund `airportsdata-Koordinate falsch` |
| **C** | Koordinate stimmt (AD deckt sich mit OA), echter Bodenpunkt trotzdem außerhalb 4 km | Radius-Override, Grund `Abhebepunkt außerhalb Standardradius` |
| **D** | Der Bodenpunkt gehört zu einem *anderen* Platz | **nichts eintragen** |
| **E** | An diesem Ende gibt es keinen Bodenpunkt | **nichts eintragen** |
| **F** | Quellen widersprechen sich, nicht auflösbar | **nichts eintragen**, Befund festhalten |

**Fall A hat zwei Zweige:**
- Echter ICAO-Code, den airportsdata nicht kennt → Ergänzung mit diesem Code.
- **Gar kein ICAO-Code** → Pseudo-Code nach dem etablierten Muster (`BZWIROS`, `ZZSALZ`,
  `EXHB`, `CML5`). Ein solcher Code ist **frei erfunden und muss vom Nutzer kommen** — nie
  selbst einen ausdenken. Der Grund bleibt `Fehlt in airportsdata` (kein eigener Grund für
  Platzhalter, siehe `docs/superpowers/specs/2026-07-15-flugplatz-grund-design.md`).

**Fall B — der Belgien-Fund:** airportsdata verortet belgische/luxemburgische Plätze
systematisch falsch (34 % der BE-Codes > 3 km, alle nach Südwesten verschoben; Deutschland:
1 von 452). „Nicht erkannt" ist dort meist „falsch verortet".

**Fall C braucht eine Plausibilitätsprüfung:** Ein Flugplatz misst selten mehr als sechs
Kilometer. Die Nachbarliste zeigt, welche Plätze ein größerer Radius mitverschluckt — das ist
der Preis des Overrides. Bestehende Radius-Overrides: `EDDF` und `EHAM`, je 10 km.

**Fall D fasst zwei Ursachen zusammen:** Flugplan-Tippfehler (EDHX → EDXH) und schlichte
Umplanung (ETUO: Pilot stand in Bad Gandersheim, 118 km vom Flugplan-Ziel). Die Unterscheidung
erklärt, ändert aber nichts: in beiden Fällen ist der Platz richtig verortet und der Flugplan
das Problem.

## Flüge ohne Flugplan

FriesenSpy ist seit #23 **GPS-only** — Flüge ohne Flugplan werden gewertet. Die
Erkennungslücken-Liste zeigt sie aber **nie**: `list_gps_detection_gaps`
(`app/database.py:4683`) verlangt `missing_dep = not gps_departure and plan_departure`. Ohne
Soll-Angabe fällt der Fall raus.

So findet man sie:

```sql
SELECT cid, callsign, aircraft, logon_time, logoff_time, duration_min, source,
       COALESCE(gps_departure,'-') AS gps_dep, COALESCE(gps_arrival,'-') AS gps_arr,
       COALESCE(plan_departure,'-') AS plan_dep, COALESCE(plan_arrival,'-') AS plan_arr
FROM flight_cache
WHERE ((gps_departure IS NULL OR gps_departure='') AND (plan_departure IS NULL OR plan_departure=''))
   OR ((gps_arrival IS NULL OR gps_arrival='') AND (plan_arrival IS NULL OR plan_arrival='') AND connection_closed=1)
ORDER BY logon_time;
```

Stand 2026-07-15: 2104 FRS-Legs, 101 sichtbare Lücken, **vier blinde Fälle**. Untergrenzwert —
`flight_cache` filtert auf `CALLSIGN_PREFIX`, die Lückenliste läuft über alle Callsigns.

Ohne Flugplan verschiebt sich zweierlei: **Fall D entfällt** (wo kein Soll ist, kann nichts
abweichen), und **Fall A wird zur Recherche** — kein Code sagt, wie der Platz heißt. Dann
bleiben OurAirports und Websuche.

## Regeln

- **Keine Zahl aus dem Gedächtnis.** Messen oder recherchieren, Quelle nennen. Der Nutzer hat
  das ausdrücklich eingefordert; ein aus dem Gedächtnis genannter Elevation-Wert war real
  falsch (64 statt 55 ft).
- **Nie einen Pseudo-Code erfinden.** Der kommt vom Nutzer.
- **Nie in die Produktions-DB schreiben.**
- Bei Massen-Einträgen (Nutzer): jeder Write stößt einen vollen `rebuild_flight_cache` an.
  Mehrere Writes in Folge → parallele Rebuilds, die sich überschreiben (Zeitstempel laufen
  rückwärts). Danach einen einzelnen Write nachschieben und den Rebuild abwarten, sonst misst
  man Zwischenzustände.

## Referenzfälle

| Fall | Punkt | Befund |
|---|---|---|
| EBKT | `50.82005 / 3.2163` | AD 37,20 km / OA 0,49 km → **B** |
| EDHX | `54.18665 / 7.91488` | AD fehlt, OA 132,70 km, EDXH 0,16 km → **D** |
| ETUO | `51.85449 / 10.02288` | AD 118,05 km, OA fehlt, EDVA 0,19 km → **D** |
| EDDH | `53.49527 / 10.00085`, 2209 ft | 15,05 km, AGL 2156 ft → **E** |
| LKLB | Track 28227871 | 101-min-Aufzeichnungslücke, beide Enden airborne → **E** |
| SLSM | — | AD näher als der Override → **F** |
````

- [ ] **Step 2: README korrigieren**

`README.md:75` behauptet, die airportsdata-Koordinaten stammten aus OurAirports. Der Belgien-Fund widerlegt das: 848 von 24.253 gemeinsamen Codes weichen um mehr als 3 km ab (3,5 %; Belgien 34 %).

Alt:

```markdown
**Woher kommen die Airport-Koordinaten?** Der Geo-Check nutzt das Python-Package [`airportsdata`](https://github.com/mborsetti/airportsdata), das eine vollständige ICAO-Datenbank eingebettet enthält — inklusive aller deutschen Sonderlandeplätze und Kleinflugplätze (z.B. EDKB, EDKV, EDRV). Die Koordinaten stammen aus der [OurAirports](https://ourairports.com)-Datenbank. Es findet kein API-Call statt — die Abfrage ist offline und instant.
```

Neu:

```markdown
**Woher kommen die Airport-Koordinaten?** Der Geo-Check nutzt das Python-Package [`airportsdata`](https://github.com/mborsetti/airportsdata), das eine vollständige ICAO-Datenbank eingebettet enthält — inklusive aller deutschen Sonderlandeplätze und Kleinflugplätze (z.B. EDKB, EDKV, EDRV). Es findet kein API-Call statt — die Abfrage ist offline und instant.

> **Die Koordinaten sind nicht durchweg korrekt.** `airportsdata` nennt [OurAirports](https://ourairports.com) als Quelle, deckt sich aber nachweislich nicht damit: Bei 848 von 24.253 gemeinsamen Codes liegen beide Datenbanken mehr als 3 km auseinander (3,5 %). Belgien ist mit 34 % der Plätze der schlimmste Fall in Europa (EBBR 42 km, EBKT 37 km, ELLX 29 km — alle nach Südwesten verschoben), Deutschland mit 1 von 452 der beste. Bekannte Fehler werden über `custom_airports` überschrieben (siehe #56/#62); zur Diagnose einzelner Fälle gibt es den Skill `track-diagnose`.
```

- [ ] **Step 3: Volle Suite**

Run: `python -m pytest tests/ -q`
Expected: 1063 passed (1047 bestehende + 16 neue).

- [ ] **Step 4: Skill-Verfügbarkeit prüfen**

Run: `ls -la .claude/skills/track-diagnose/SKILL.md && git check-ignore .claude/skills/track-diagnose/SKILL.md; echo "ignored=$?"`
Expected: Datei existiert, `ignored=1` (**nicht** ignoriert — `.gitignore` schließt nur `.claude/worktrees/` aus).

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/track-diagnose/SKILL.md README.md
git commit -m "feat: Skill track-diagnose + README-Korrektur zur Koordinatenherkunft

Schreibt die Pruefreihenfolge fest (Bodenpunkt -> wohin gehoert er -> Code) und
die sechs Faelle. README behauptete, airportsdata-Koordinaten stammten aus
OurAirports — der Belgien-Fund widerlegt das (848 von 24253 Codes > 3 km)."
```

---

## Verifikation zum Schluss

- [ ] `python -m pytest tests/ -q` → 1063 passed
- [ ] `python scripts/nearby_airports.py 53.49527 10.00085 --alt 2209 --icao EDDH` → 15.05 km, „außerhalb", AGL 2156 ft, „überschritten"
- [ ] Echter Triage-Lauf: Export ziehen (siehe SKILL.md), dann `python scripts/triage_gaps.py gaps.json` → Größenordnung 184 Enden aus 163 Fällen, ~23 Kandidaten. **Weicht das stark ab, ist das ein Befund, kein Grund zum Nachjustieren** — die Liste ändert sich mit jedem Flug, aber ein Sprung von 23 auf 100 Kandidaten hieße, dass eine Gruppenregel nicht greift.
- [ ] `git status --short` → keine ungewollten Dateien; `scripts/.cache/` fehlt (ignoriert)
- [ ] **Nicht** getan: kein Version-Bump, kein Tag, kein Changelog, keine Änderung an `docs/api.md` / `docs/architecture.md`
- [ ] **Nicht** angefasst: die vier unversionierten Nutzer-Dateien (`friesenkutter-*.html`, `docs/superpowers/{plans,specs}/2026-07-13-subjekt-sichtbarkeit*`)
