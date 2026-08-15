# Platzrunden auf der Karte — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deutsche Platzrunden mit Höhenangabe als eigene Karten-Ebene, dazu die FSE-Flugplätze mit ihren MSFS-Entsprechungen.

**Architecture:** Zwei statische GeoJSON/JSON-Dateien unter `app/static/data/`, die beim Einschalten der jeweiligen Ebene per `fetch` geholt werden. Kein Endpunkt, keine Datenbank, kein Poller — die Daten ändern sich im Jahresmaßstab. Jede Ebene folgt exakt dem Muster der Verkehrs-Ebene aus v12.7.0: Gruppe anlegen, Präferenz in `localStorage`, Registrierung **vor** dem Bau der Layers-Control.

**Tech Stack:** Vanilla JS, Leaflet, FastAPI `StaticFiles` (`/static` → `app/static`), pytest

**Spec:** `docs/superpowers/specs/2026-08-15-platzrunden-karte-design.md`

## Global Constraints

- **Teil 1 der Spec ist erledigt** (V12.7.1, `OFM_NATIVE_MAX_ZOOM = 12`). Dieser Plan setzt Teil 2 und Teil 3 um.
- **Branch:** Die gesamte Arbeit läuft auf `platzrunden-karte`, nicht auf `main` — eine zweite Session arbeitet parallel am WASM-Verkehr. Vor jedem Commit `git pull --rebase origin main`.
- **Nicht anfassen:** der Verkehrs-Block in `app/static/index.html` (`_verkehrRoh`, `_verkehrAbrufen`, `_verkehrUebernehmen`, alles zwischen `const _VERKEHR_TAKT_MS` und `_verkehrRadiusKm`). Das ist der Arbeitsbereich der anderen Session.
- **Kein Wert doppelt:** Zoom-Schwellen und Pfade stehen genau einmal als Konstante (`test_verkehr_hat_eine_einzige_zoom_schwelle` prüft das Muster für den Verkehr; für die neuen Ebenen gilt dasselbe).
- **Höhen-Regel, ausnahmslos:** Bei `hoehe_geschaetzt: true` erscheint **keine Zahl**. Das Feld `hoehe_label` enthält dann den Text „keine Angabe (Annahme 1000 ft)" — es darf **nie** ungeprüft gerendert werden.
- **Kommentarstil:** Deutsche Kommentare, die das *Warum* erklären, wie im Rest der Datei. Private Funktionen mit `_`-Präfix.
- **Tests:** `.venv/bin/python -m pytest tests/ -q` (Vollauf ~140 s). Frontend-Verhalten wird über den Text von `index.html` geprüft — Muster siehe `tests/test_vr_panel.py`, Abschnitt „Verkehrs-Ebene (v12.7.0)".

---

### Task 0: Branch anlegen

**Files:** keine

- [ ] **Schritt 1: Aktuellen Stand holen und abzweigen**

```bash
cd ~/projects/friesenspy
git checkout main && git pull --ff-only
git checkout -b platzrunden-karte
git branch --show-current   # erwartet: platzrunden-karte
```

---

### Task 1: Datensatz ins Repo

**Files:**
- Create: `app/static/data/platzrunden_de.geojson`
- Test: `tests/test_platzrunden.py`

**Interfaces:**
- Produces: die Datei unter `/static/data/platzrunden_de.geojson`, 412 Features mit den Feldern `icao`, `name`, `typ`, `bahn`, `hoehe_ft`, `hoehe_bezug`, `hoehe_label`, `hoehe_geschaetzt`, `info`, `quelle`

- [ ] **Schritt 1: Failing test schreiben**

```python
"""Platzrunden-Datensatz und -Ebene (v12.8.0)."""
import json
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
GEOJSON = STATIC / "data" / "platzrunden_de.geojson"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_datensatz_liegt_im_repo():
    assert GEOJSON.exists(), "app/static/data/platzrunden_de.geojson fehlt"


def test_datensatz_hat_die_erwarteten_features():
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 412


def test_geschaetzte_hoehen_tragen_keine_zahl():
    """Die 147 Platzhalter stehen im Rohdatensatz als '0 ft / GND' und tragen im KML pauschal
    305 m = 1000 ft. Diese Zahl ist erfunden. Sie darf nicht als hoehe_ft durchkommen, sonst
    landet sie ueber irgendeinen Renderpfad doch im Popup."""
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    geschaetzt = [f for f in gj["features"] if f["properties"]["hoehe_geschaetzt"]]
    assert len(geschaetzt) == 147
    assert all(f["properties"]["hoehe_ft"] is None for f in geschaetzt)


def test_echte_hoehen_haben_alle_einen_wert():
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    echt = [f for f in gj["features"] if not f["properties"]["hoehe_geschaetzt"]]
    assert len(echt) == 265
    assert all(isinstance(f["properties"]["hoehe_ft"], int) for f in echt)


def test_polygonringe_sind_geschlossen():
    """Leaflet zeichnet auch offene Ringe, schliesst sie aber optisch selbst -- ein offener
    Ring faellt deshalb erst auf, wenn jemand die Geometrie weiterverarbeitet."""
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    for f in gj["features"]:
        if f["geometry"]["type"] == "Polygon":
            ring = f["geometry"]["coordinates"][0]
            assert ring[0] == ring[-1], f"offener Ring bei {f['properties']['icao']}"


def test_korrigierte_icaos_sind_drin():
    """Vier ICAO-Codes waren im Rohdatensatz falsch zugeordnet (Geometrie richtig, Verknuepfung
    falsch). Die Korrektur ist in den Daten, nicht im Frontend -- also hier pruefen."""
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    korrigiert = {f["properties"]["icao"]: f["properties"].get("icao_original")
                  for f in gj["features"] if f["properties"].get("icao_original")}
    assert korrigiert == {"EDLH": "EDFJ", "EDBM": "EDBC", "EDFS": "EDQT", "EDRZ": "EDRP"}
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_platzrunden.py -q`
Expected: FAIL — „app/static/data/platzrunden_de.geojson fehlt"

- [ ] **Schritt 3: Datei ablegen**

```bash
mkdir -p app/static/data
cp ~/projects/platzrunden-recherche/platzrunden_de_korrigiert.geojson \
   app/static/data/platzrunden_de.geojson
```

- [ ] **Schritt 4: Tests laufen lassen**

Run: `.venv/bin/python -m pytest tests/test_platzrunden.py -q`
Expected: PASS (6 Tests)

- [ ] **Schritt 5: Commit**

```bash
git add app/static/data/platzrunden_de.geojson tests/test_platzrunden.py
git commit -m "Platzrunden: geprüfter Datensatz ins Repo

412 Features, 385 Plätze, 28,3 KB gzip. Vier ICAO-Zuordnungen korrigiert,
147 Platzhalter-Höhen als hoehe_geschaetzt markiert und ohne Zahl.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Die Ebene — Gerüst, Lazy Load, Registrierung

**Files:**
- Modify: `app/static/index.html` (neuer Block direkt **vor** `// ===` des Verkehrs-Blocks, und Registrierung bei `liveOverlays`)
- Test: `tests/test_platzrunden.py`

**Interfaces:**
- Consumes: `/static/data/platzrunden_de.geojson` aus Task 1
- Produces: `_platzrundenGruppe` (L.layerGroup), `_platzrundenLaden()`, `_addPreferredPlatzrundenLayer(map, gruppe)`, `_savePlatzrundenPref(an)`, `_loadPlatzrundenPref()`, Konstante `_PLATZRUNDEN_MIN_ZOOM`

- [ ] **Schritt 1: Failing tests schreiben (an `tests/test_platzrunden.py` anhängen)**

```python
def test_ebene_wird_vor_der_layers_control_registriert():
    """Die OpenAIP-Falle, dritte Auflage: Ein nach dem Bau der Control hinzugefuegter Layer
    feuert keines der Ereignisse, auf die sie lauscht -- der Haken zeigt dann dauerhaft den
    falschen Zustand. Die Control unabhaengig ueber ihren eindeutigen Nachbarn finden, nicht
    ueber INDEX.index(sub, start): das liefert per Definition immer einen Wert >= start und
    koennte gar nicht fehlschlagen."""
    vorher = INDEX.index("_addPreferredPlatzrundenLayer(liveMap")
    control = INDEX.index("liveOverlays,")
    assert vorher < control


def test_ebene_steht_in_der_ebenen_auswahl():
    assert "liveOverlays['Platzrunden']" in INDEX


def test_datensatz_wird_erst_beim_einschalten_geholt():
    """28 KB gzip rechtfertigen keinen Abruf beim Seitenaufbau -- die meisten Besucher
    schalten die Ebene nie ein."""
    stelle = INDEX.index("function _platzrundenLaden(")
    assert "fetch(" in INDEX[stelle:stelle + 800]
    # der fetch darf nirgends beim Aufbau stehen, nur in dieser Funktion
    assert INDEX.count("/static/data/platzrunden_de.geojson") == 1


def test_datensatz_wird_nur_einmal_geholt():
    """Ein- und Ausschalten der Ebene darf den Abruf nicht wiederholen."""
    stelle = INDEX.index("function _platzrundenLaden(")
    rumpf = INDEX[stelle:stelle + 800]
    assert "_platzrundenGeladen" in rumpf


def test_zoom_schwelle_steht_genau_einmal():
    assert INDEX.count("_PLATZRUNDEN_MIN_ZOOM =") == 1
    assert INDEX.count("_PLATZRUNDEN_MIN_ZOOM") >= 2
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_platzrunden.py -q`
Expected: FAIL — `ValueError: substring not found` bei `_addPreferredPlatzrundenLayer`

- [ ] **Schritt 3: Den Block einfügen**

Einfügen in `app/static/index.html` **unmittelbar vor** dem Kommentarblock, der den Verkehrs-Teil einleitet (die Zeile mit `const _VERKEHR_TAKT_MS`; davor steht ein `// ===`-Kasten — der neue Block kommt vor diesen Kasten):

```js
// ==========================================================================
//  PLATZRUNDEN
// ==========================================================================
// Warum eine eigene Ebene, wo die Luftfahrtkarte sie doch zeichnet: OFM hat sie nur auf
// Zoom 12, darueber schaltet der Auto-Switch auf Satellit (s. OFM_NATIVE_MAX_ZOOM). Topo,
// CARTO und Satellit tragen ueberhaupt keine Luftfahrtdaten. Beim Anflug zoomt man aber
// weiter hinein -- genau dann verschwaende die Runde wieder. Diese Ebene liegt ueber jeder
// Karte und auf jeder Stufe, und sie traegt die Hoehe, die OFM nirgends hinschreibt.
const _PLATZRUNDEN_URL      = '/static/data/platzrunden_de.geojson';
const _PLATZRUNDEN_MIN_ZOOM = 9;   // darunter sind 412 Polygone nur noch Rauschen
const _PLATZRUNDEN_PREF_KEY = 'friesenspy_platzrunden';

const _platzrundenGruppe = L.layerGroup();
let   _platzrundenGeladen = false;   // Abruf genau einmal, nicht bei jedem Einschalten

function _savePlatzrundenPref(an) {
  try { localStorage.setItem(_PLATZRUNDEN_PREF_KEY, an ? '1' : '0'); } catch (e) {}
}
function _loadPlatzrundenPref() {
  try { return localStorage.getItem(_PLATZRUNDEN_PREF_KEY) === '1'; } catch (e) { return false; }
}

function _platzrundenStil() {
  return { color: '#8ab4d8', weight: 1.5, opacity: 0.9, fill: false };
}

function _platzrundenLaden() {
  if (_platzrundenGeladen) return Promise.resolve();
  _platzrundenGeladen = true;
  return fetch(_PLATZRUNDEN_URL)
    .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
    .then(gj => {
      L.geoJSON(gj, {
        style: _platzrundenStil,
        onEachFeature: (f, layer) => { layer.bindPopup(_platzrundenPopup(f.properties)); }
      }).addTo(_platzrundenGruppe);
    })
    .catch(e => {
      // Beim naechsten Einschalten neu versuchen -- ein einmaliger Netzfehler soll die
      // Ebene nicht dauerhaft leer lassen.
      _platzrundenGeladen = false;
      console.warn('Platzrunden konnten nicht geladen werden:', e);
    });
}

// Wie bei OpenAIP und Verkehr: VOR dem Bau der Layers-Control aufrufen -- sonst zeigt der
// Haken dauerhaft den falschen Zustand.
function _addPreferredPlatzrundenLayer(map, gruppe) {
  map.on('overlayadd', (e) => {
    if (e.layer === gruppe) { _savePlatzrundenPref(true); _platzrundenLaden(); }
  });
  map.on('overlayremove', (e) => {
    if (e.layer === gruppe) { _savePlatzrundenPref(false); }
  });
  if (gruppe && _loadPlatzrundenPref()) { gruppe.addTo(map); _platzrundenLaden(); }
}
```

- [ ] **Schritt 4: Registrierung eintragen**

In `app/static/index.html` bei `const liveOverlays = {};` (Nähe Zeile 7622) die Ebene ergänzen und den Aufruf **vor** dem Control-Bau setzen:

```js
  const liveOverlays = {};
  if (liveAIP) liveOverlays['OpenAIP'] = liveAIP;
  liveOverlays['Verkehr'] = _verkehrGruppe;
  liveOverlays['Platzrunden'] = _platzrundenGruppe;
  _addPreferredPlatzrundenLayer(liveMap, _platzrundenGruppe);
```

- [ ] **Schritt 5: Tests laufen lassen**

Run: `.venv/bin/python -m pytest tests/test_platzrunden.py -q`
Expected: PASS bis auf `test_zoom_schwelle_steht_genau_einmal` (die zweite Verwendung kommt in Task 4) — dieser eine Test darf hier noch rot sein.

- [ ] **Schritt 6: Commit**

```bash
git add app/static/index.html tests/test_platzrunden.py
git commit -m "Platzrunden: eigene Ebene, beim Einschalten geladen

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Das Popup mit der Höhe

**Files:**
- Modify: `app/static/index.html` (Funktion `_platzrundenPopup` in den Block aus Task 2)
- Test: `tests/test_platzrunden.py`

**Interfaces:**
- Consumes: `_platzrundenLaden()` ruft `_platzrundenPopup(props)` auf (Task 2, `onEachFeature`)
- Produces: `_platzrundenPopup(props) -> string`

- [ ] **Schritt 1: Failing tests schreiben**

```python
def test_popup_verzweigt_auf_das_flag_nicht_auf_das_label():
    """hoehe_label lautet bei den 147 Platzhaltern 'keine Angabe (Annahme 1000 ft)'. Wer das
    Feld rendert, zeigt die erfundene Zahl doch an -- nur in Klammern. Deshalb muss das Popup
    auf hoehe_geschaetzt verzweigen und hoehe_label gar nicht erst anfassen."""
    stelle = INDEX.index("function _platzrundenPopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "hoehe_geschaetzt" in rumpf
    assert "hoehe_label" not in rumpf


def test_popup_schreibt_msl_auch_bei_unsicherem_bezug():
    """127 Eintraege tragen 'MSL?'. Gegen die Platzhoehe gerechnet liegen sie im selben Band
    wie die 138 expliziten MSL-Angaben (Median 895 vs. 864 ft ueber Grund) -- derselbe Bezug.
    Ein Fragezeichen im Cockpit hilft niemandem."""
    stelle = INDEX.index("function _platzrundenPopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "MSL?" not in rumpf
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_platzrunden.py -k popup -q`
Expected: FAIL — `ValueError: substring not found`

- [ ] **Schritt 3: Funktion einfügen (in den Block aus Task 2, vor `_platzrundenLaden`)**

```js
// Die Hoehe ist der Grund fuer diese Ebene -- aber nur, wenn sie echt ist. 147 der 412
// Eintraege tragen im Rohdatensatz einen Platzhalter (pauschal 1000 ft); der steht als
// hoehe_geschaetzt: true und hoehe_ft: null. hoehe_label wird hier bewusst NICHT benutzt:
// es enthaelt bei diesen Eintraegen den Text "keine Angabe (Annahme 1000 ft)" und wuerde
// die erfundene Zahl doch anzeigen.
function _platzrundenPopup(p) {
  const kopf = (p.icao ? '<b>' + p.icao + '</b> ' : '') + (p.name || '');
  const zeilen = [kopf];
  if (p.bahn) zeilen.push('Bahn ' + p.bahn);
  if (p.typ === 'strecke') {
    zeilen.push('An-/Abflugstrecke');
  } else if (p.hoehe_geschaetzt || p.hoehe_ft === null) {
    zeilen.push('Höhe nicht bekannt');
  } else {
    // "MSL?" steht fuer Eintraege ohne ausgeschriebenen Bezug. Gegen die Platzhoehe
    // gerechnet liegen sie im selben Band wie die expliziten MSL-Angaben -- also MSL.
    zeilen.push('Platzrunde ' + p.hoehe_ft + ' ft MSL');
  }
  if (p.info) zeilen.push('<span class="pr-info">' + p.info + '</span>');
  return zeilen.join('<br>');
}
```

- [ ] **Schritt 4: Tests laufen lassen**

Run: `.venv/bin/python -m pytest tests/test_platzrunden.py -k popup -q`
Expected: PASS (2 Tests)

- [ ] **Schritt 5: Commit**

```bash
git add app/static/index.html tests/test_platzrunden.py
git commit -m "Platzrunden: Popup mit Höhe, Platzhalter ohne Zahl

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Zoom-Schwelle

**Files:**
- Modify: `app/static/index.html` (Block aus Task 2 + Aufruf beim Karten-Setup)
- Test: `tests/test_platzrunden.py`

**Interfaces:**
- Consumes: `_platzrundenGruppe`, `_PLATZRUNDEN_MIN_ZOOM` aus Task 2
- Produces: `_platzrundenZoomWache(map)`

- [ ] **Schritt 1: Failing test schreiben**

```python
def test_zoom_wache_haengt_am_zoomend():
    """Weit herausgezoomt sind 412 Polygone kein Bild mehr, sondern Grauschleier. Ausblenden
    heisst hier: die Linien verschwinden, der Haken bleibt gesetzt -- sonst muesste der Nutzer
    die Ebene nach jedem Herauszoomen neu einschalten."""
    stelle = INDEX.index("function _platzrundenZoomWache(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "zoomend" in rumpf
    assert "_PLATZRUNDEN_MIN_ZOOM" in rumpf
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_platzrunden.py -k zoom -q`
Expected: FAIL — `ValueError: substring not found`

- [ ] **Schritt 3: Wache einfügen (in den Block aus Task 2, nach `_addPreferredPlatzrundenLayer`)**

```js
// Ausblenden ueber die Deckkraft statt ueber removeLayer: Die Ebene bleibt in der Auswahl
// angehakt, der Nutzer muss sie nach dem Herauszoomen nicht neu einschalten.
function _platzrundenZoomWache(map) {
  const anpassen = () => {
    const sichtbar = map.getZoom() >= _PLATZRUNDEN_MIN_ZOOM;
    _platzrundenGruppe.eachLayer(l => {
      if (l.setStyle) l.setStyle({ opacity: sichtbar ? 0.9 : 0 });
    });
  };
  map.on('zoomend', anpassen);
  _platzrundenGruppe.on('layeradd', anpassen);
  anpassen();
}
```

- [ ] **Schritt 4: Aufruf ergänzen**

Direkt nach `_addPreferredPlatzrundenLayer(liveMap, _platzrundenGruppe);` aus Task 2:

```js
  _platzrundenZoomWache(liveMap);
```

- [ ] **Schritt 5: Volle Testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, alle bisherigen Tests bleiben grün (Vollauf ~140 s)

- [ ] **Schritt 6: Changelog + Commit**

Neuer Eintrag **ganz vorne** in `app/CHANGELOG.json`:

```json
  {
    "version": "12.8.0",
    "date": "2026-08-15",
    "highlight": false,
    "title": "Platzrunden mit Höhe auf jeder Karte",
    "items": [
      "🛬 Neue Ebene „Platzrunden“ in der Ebenen-Auswahl: 412 deutsche Platzrunden, sichtbar über jeder Kartensorte und auf jeder Zoomstufe — anders als bei der Luftfahrtkarte, die sie nur auf einer einzigen Stufe zeichnet und darüber auf Satellit umschaltet. Ein Klick auf die Runde zeigt Platz, Bahn und Platzrundenhöhe.",
      "📏 Wo die Höhe nicht bekannt ist, steht „Höhe nicht bekannt“ — und keine geratene Zahl. Bei 147 der Runden fehlt sie in der Quelle; eine erfundene Höhe im Cockpit wäre schlimmer als gar keine.",
      "🔍 Weit herausgezoomt bleiben die Runden aus — dort wären es 412 Vierecke ohne Aussage. Der Haken bleibt dabei gesetzt."
    ]
  },
```

```bash
git add app/static/index.html app/CHANGELOG.json tests/test_platzrunden.py
git commit -m "V12.8.0: Platzrunden mit Höhe auf jeder Karte

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: FSE-Daten zuschneiden

**Files:**
- Create: `scripts/fse_zuschnitt.py`
- Create: `app/static/data/fse_airports_eu.json`
- Create: `app/static/data/fse_zones_eu.json`
- Test: `tests/test_fse.py`

**Interfaces:**
- Produces: `fse_airports_eu.json` als `{icao: {lat, lon, name, msfs, rwy, surface, elev}}`, `fse_zones_eu.json` als `{icao: [[lat, lon], …]}`

- [ ] **Schritt 1: Failing test schreiben**

```python
"""FSE-Ebenen (v12.9.0)."""
import json
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
AIRPORTS = STATIC / "data" / "fse_airports_eu.json"
ZONES = STATIC / "data" / "fse_zones_eu.json"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_dateien_liegen_im_repo():
    assert AIRPORTS.exists() and ZONES.exists()


def test_europa_zuschnitt_ist_klein_genug():
    """Weltweit waeren es 17 MB. Der Europa-Ausschnitt muss unter 1 MB roh bleiben, sonst ist
    das Lazy Load die Wartezeit nicht wert."""
    assert AIRPORTS.stat().st_size < 1_000_000
    assert ZONES.stat().st_size < 1_000_000


def test_plaetze_liegen_in_europa():
    ap = json.loads(AIRPORTS.read_text(encoding="utf-8"))
    assert 2000 < len(ap) < 3000
    for icao, a in ap.items():
        assert 35 <= a["lat"] <= 72, icao
        assert -25 <= a["lon"] <= 45, icao


def test_msfs_feld_ist_bereinigt():
    """Im Rohdatensatz steht bei Plaetzen ohne MSFS-Entsprechung [None] -- eine nichtleere
    Liste mit einem None darin. Wer darauf mit truthiness prueft, haelt sie faelschlich fuer
    vorhanden (der Fehler ist bei der Auswertung schon einmal passiert)."""
    ap = json.loads(AIRPORTS.read_text(encoding="utf-8"))
    for icao, a in ap.items():
        assert isinstance(a["msfs"], list)
        assert all(x for x in a["msfs"]), f"None in msfs bei {icao}"


def test_die_inseln_sind_dabei():
    ap = json.loads(AIRPORTS.read_text(encoding="utf-8"))
    for icao in ("EDWG", "EDWY", "EDWJ", "EDWL", "EDWR", "EDWZ"):
        assert icao in ap, icao
    assert "EHOW" in ap["EDWE"]["msfs"], "Emden heisst in MSFS auch EHOW"
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_fse.py -q`
Expected: FAIL — Dateien fehlen

- [ ] **Schritt 3: Zuschnitt-Skript schreiben**

```python
#!/usr/bin/env python3
"""Schneidet die FSE-Planner-Daten auf Europa zu.

Quelle: https://github.com/piero-la-lune/FSE-Planner (MIT). Weltweit sind es 17 MB --
9,5 MB Flugplaetze und 7,5 MB Zonen. Fuer FriesenSpy reicht Europa, und von den Feldern
brauchen wir nur einen Bruchteil.

Aufruf:  python3 scripts/fse_zuschnitt.py /pfad/zum/FSE-Planner-klon
"""
import json
import sys
from pathlib import Path

# Europa grosszuegig: Island bis Ural, Kanaren bis Nordkap
LAT = (35.0, 72.0)
LON = (-25.0, 45.0)
ZIEL = Path(__file__).resolve().parents[1] / "app" / "static" / "data"


def echte_msfs(eintrag):
    """Im Rohdatensatz steht [None] bei Plaetzen ohne MSFS-Entsprechung -- eine nichtleere
    Liste, die bei einer truthiness-Pruefung faelschlich als 'vorhanden' durchgeht."""
    return [x for x in (eintrag.get("msfs") or []) if x]


def main(klon):
    klon = Path(klon)
    plaetze = json.loads((klon / "src" / "data" / "icaodata.json").read_text(encoding="utf-8"))
    zonen = json.loads((klon / "public" / "data" / "zones.json").read_text(encoding="utf-8"))

    drin = {k: v for k, v in plaetze.items()
            if LAT[0] <= v["lat"] <= LAT[1] and LON[0] <= v["lon"] <= LON[1]}
    schlank = {k: {"lat": v["lat"], "lon": v["lon"], "name": v["name"],
                   "msfs": echte_msfs(v), "rwy": v["runway"], "surface": v["surface"],
                   "elev": v["elev"]}
               for k, v in drin.items()}
    zs = {k: zonen[k] for k in drin if k in zonen}

    ZIEL.mkdir(parents=True, exist_ok=True)
    (ZIEL / "fse_airports_eu.json").write_text(
        json.dumps(schlank, separators=(",", ":")), encoding="utf-8")
    (ZIEL / "fse_zones_eu.json").write_text(
        json.dumps(zs, separators=(",", ":")), encoding="utf-8")
    print(f"{len(schlank)} Plaetze, {len(zs)} Zonen geschrieben")


if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Schritt 4: Skript ausführen**

```bash
mkdir -p scripts
git clone --depth 1 https://github.com/piero-la-lune/FSE-Planner.git /tmp/FSE-Planner
.venv/bin/python scripts/fse_zuschnitt.py /tmp/FSE-Planner
# erwartet: "2335 Plaetze, 2335 Zonen geschrieben"
```

- [ ] **Schritt 5: Tests laufen lassen**

Run: `.venv/bin/python -m pytest tests/test_fse.py -q`
Expected: PASS (5 Tests)

- [ ] **Schritt 6: Commit**

```bash
git add scripts/fse_zuschnitt.py app/static/data/fse_airports_eu.json \
        app/static/data/fse_zones_eu.json tests/test_fse.py
git commit -m "FSE: Europa-Zuschnitt der Flugplatz- und Zonendaten

Aus FSE-Planner (MIT). Weltweit 17 MB, Europa-Ausschnitt rund 600 KB roh.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: FSE-Ebenen

**Files:**
- Modify: `app/static/index.html` (neuer Block nach dem Platzrunden-Block, Registrierung bei `liveOverlays`)
- Test: `tests/test_fse.py`

**Interfaces:**
- Consumes: `fse_airports_eu.json`, `fse_zones_eu.json` aus Task 5
- Produces: `_fsePlaetzeGruppe`, `_fseZonenGruppe`, `_fseLaden()`, `_addPreferredFseLayer(map)`, `_fsePopup(icao, a)`

- [ ] **Schritt 1: Failing tests schreiben**

```python
def test_fse_ebenen_stehen_in_der_auswahl():
    assert "liveOverlays['FSE-Plätze']" in INDEX
    assert "liveOverlays['FSE-Landeflächen']" in INDEX


def test_fse_wird_vor_der_layers_control_registriert():
    vorher = INDEX.index("_addPreferredFseLayer(liveMap")
    control = INDEX.index("liveOverlays,")
    assert vorher < control


def test_zonen_fangen_keine_klicks():
    """Die Zellen liegen flaechendeckend ueber der Karte. Waeren sie klickbar, kaeme man an
    keinen Marker und an kein Platzrunden-Popup mehr heran."""
    stelle = INDEX.index("function _fseZonenZeichnen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "interactive: false" in rumpf
    assert "fill: false" in rumpf


def test_fse_daten_werden_lazy_geholt():
    assert INDEX.count("/static/data/fse_airports_eu.json") == 1
    assert INDEX.count("/static/data/fse_zones_eu.json") == 1
    stelle = INDEX.index("function _fseLaden(")
    assert "_fseGeladen" in INDEX[stelle:stelle + 900]
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_fse.py -k fse -q`
Expected: FAIL — `ValueError: substring not found`

- [ ] **Schritt 3: Block einfügen (nach dem Platzrunden-Block)**

```js
// ==========================================================================
//  FSE-PLAETZE UND LANDEFLAECHEN
// ==========================================================================
// Daten aus dem FSE-Planner (MIT, github.com/piero-la-lune/FSE-Planner), auf Europa
// zugeschnitten (s. scripts/fse_zuschnitt.py). Die Landeflaeche ist das Gebiet, dessen
// Landungen FSEconomy diesem Platz zurechnet -- eine Voronoi-Zelle. Sie liegt als reine
// Linie unter allem anderen und faengt keine Klicks: sonst kaeme man an keinen Marker mehr.
const _FSE_PLAETZE_URL = '/static/data/fse_airports_eu.json';
const _FSE_ZONEN_URL   = '/static/data/fse_zones_eu.json';
const _FSE_PREF_KEY    = 'friesenspy_fse';

const _fsePlaetzeGruppe = L.layerGroup();
const _fseZonenGruppe   = L.layerGroup();
let   _fseGeladen = false;

function _saveFsePref(an) {
  try { localStorage.setItem(_FSE_PREF_KEY, an ? '1' : '0'); } catch (e) {}
}
function _loadFsePref() {
  try { return localStorage.getItem(_FSE_PREF_KEY) === '1'; } catch (e) { return false; }
}

function _fseZonenZeichnen(zonen) {
  for (const icao in zonen) {
    L.polyline(zonen[icao], {
      weight: 1, color: '#888', opacity: 0.5, interactive: false, fill: false
    }).addTo(_fseZonenGruppe);
  }
}

function _fsePlaetzeZeichnen(plaetze) {
  for (const icao in plaetze) {
    const a = plaetze[icao];
    L.circleMarker([a.lat, a.lon], {
      radius: 3, weight: 1, color: '#d8a45e', fillColor: '#d8a45e', fillOpacity: 0.7
    }).bindPopup(_fsePopup(icao, a)).addTo(_fsePlaetzeGruppe);
  }
}

function _fseLaden() {
  if (_fseGeladen) return Promise.resolve();
  _fseGeladen = true;
  return Promise.all([
    fetch(_FSE_PLAETZE_URL).then(r => r.json()),
    fetch(_FSE_ZONEN_URL).then(r => r.json())
  ]).then(([plaetze, zonen]) => {
    _fsePlaetzeZeichnen(plaetze);
    _fseZonenZeichnen(zonen);
  }).catch(e => {
    _fseGeladen = false;
    console.warn('FSE-Daten konnten nicht geladen werden:', e);
  });
}

function _addPreferredFseLayer(map) {
  const meine = (l) => l === _fsePlaetzeGruppe || l === _fseZonenGruppe;
  map.on('overlayadd',    (e) => { if (meine(e.layer)) { _saveFsePref(true);  _fseLaden(); } });
  map.on('overlayremove', (e) => { if (meine(e.layer)) { _saveFsePref(false); } });
  if (_loadFsePref()) { _fsePlaetzeGruppe.addTo(map); _fseLaden(); }
}
```

- [ ] **Schritt 4: Registrierung eintragen**

Bei `liveOverlays` ergänzen — die Zonen vor den Plätzen, damit sie darunter liegen:

```js
  liveOverlays['FSE-Landeflächen'] = _fseZonenGruppe;
  liveOverlays['FSE-Plätze'] = _fsePlaetzeGruppe;
  _addPreferredFseLayer(liveMap);
```

- [ ] **Schritt 5: Tests laufen lassen**

Run: `.venv/bin/python -m pytest tests/test_fse.py -q`
Expected: PASS bis auf die Popup-Tests aus Task 7

- [ ] **Schritt 6: Commit**

```bash
git add app/static/index.html tests/test_fse.py
git commit -m "FSE: Plätze und Landeflächen als eigene Ebenen

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: MSFS-Entsprechung im Popup

**Files:**
- Modify: `app/static/index.html` (Funktion `_fsePopup` in den Block aus Task 6)
- Test: `tests/test_fse.py`

**Interfaces:**
- Consumes: `_fsePlaetzeZeichnen` ruft `_fsePopup(icao, a)` auf (Task 6)
- Produces: `_fsePopup(icao, a) -> string`

- [ ] **Schritt 1: Failing tests schreiben**

```python
def test_popup_nennt_die_msfs_entsprechung():
    """Bei 35,6 % aller Plaetze heisst der Platz im Simulator anders, bei 9,7 % gibt es ihn
    dort gar nicht. Diese Frage stellt man am konkreten Platz -- deshalb ins Popup."""
    stelle = INDEX.index("function _fsePopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "In MSFS als" in rumpf
    assert "In MSFS nicht vorhanden" in rumpf


def test_popup_meldet_gleiche_icaos_nicht_als_alternative():
    """Bei 54,7 % der Plaetze ist der MSFS-Code derselbe. 'In MSFS als: EDWG' unter der
    Ueberschrift EDWG waere Rauschen."""
    stelle = INDEX.index("function _fsePopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "!== icao" in rumpf or "!= icao" in rumpf
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_fse.py -k popup -q`
Expected: FAIL — `ValueError: substring not found`

- [ ] **Schritt 3: Funktion einfügen (vor `_fsePlaetzeZeichnen`)**

```js
// Die MSFS-Entsprechung ist der eigentliche Gewinn dieses Datensatzes: Bei gut einem Drittel
// aller Plaetze heisst der Platz im Simulator anders, bei einem Zehntel gibt es ihn dort gar
// nicht. Ist der Code derselbe (gut die Haelfte), bleibt die Zeile weg -- sie waere Rauschen.
const _FSE_BELAG = { 0: 'unbekannt', 1: 'Asphalt', 2: 'Beton', 3: 'Gras', 4: 'Sand',
                     5: 'Wasser', 6: 'Erde', 7: 'Schnee' };

function _fsePopup(icao, a) {
  const zeilen = ['<b>' + icao + '</b> ' + (a.name || '')];
  const belag = _FSE_BELAG[a.surface] || '';
  if (a.rwy) zeilen.push('Bahn ' + a.rwy + ' ft' + (belag ? ' ' + belag : ''));
  if (a.elev !== undefined) zeilen.push(a.elev + ' ft');
  const andere = (a.msfs || []).filter(m => m !== icao);
  if (!a.msfs || !a.msfs.length) {
    zeilen.push('<i>In MSFS nicht vorhanden</i>');
  } else if (andere.length) {
    zeilen.push('In MSFS als: ' + andere.join(', '));
  }
  return zeilen.join('<br>');
}
```

- [ ] **Schritt 4: Volle Testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, alles grün

- [ ] **Schritt 5: Changelog + Commit**

Neuer Eintrag **ganz vorne** in `app/CHANGELOG.json`:

```json
  {
    "version": "12.9.0",
    "date": "2026-08-15",
    "highlight": false,
    "title": "FSE-Plätze und ihre MSFS-Namen",
    "items": [
      "🛩️ Zwei neue Ebenen aus den FSEconomy-Daten: „FSE-Plätze“ zeigt rund 2 300 europäische Plätze mit Bahnlänge, Belag und Höhe, „FSE-Landeflächen“ die Gebiete, deren Landungen FSEconomy dem jeweiligen Platz zurechnet.",
      "🔤 Wichtiger als beides: Das Popup nennt den Namen, unter dem der Platz im Simulator zu finden ist. Bei gut einem Drittel aller Plätze weicht er ab, bei einem Zehntel gibt es den Platz in MSFS gar nicht — beides stand bisher nirgends."
    ]
  },
```

```bash
git add app/static/index.html app/CHANGELOG.json tests/test_fse.py
git commit -m "V12.9.0: FSE-Plätze und ihre MSFS-Namen

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Zusammenführen

**Files:** keine

- [ ] **Schritt 1: Auf den aktuellen main-Stand rebasen**

```bash
git fetch origin
git rebase origin/main
```

Bei Konflikt: Der Verkehrs-Block gehört der anderen Session — deren Fassung übernehmen und die eigenen Blöcke danebenlegen.

- [ ] **Schritt 2: Volle Testsuite nach dem Rebase**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Schritt 3: Im Browser prüfen (die Abnahmekriterien der Spec)**

Alle zehn Punkte aus Abschnitt 10 der Spec durchgehen, insbesondere:
- Ebene „Platzrunden" schalten, Seite neu laden — Haken steht noch richtig
- Bei Satellit und Zoom 14 über EDWY: Runde sichtbar, Popup zeigt „700 ft MSL"
- Eine Runde ohne Höhe zeigt „Höhe nicht bekannt", keine Zahl
- Unter Zoom 9 verschwinden die Runden, der Haken bleibt
- FSE-Popup an Emden zeigt „In MSFS als: EHOW"

- [ ] **Schritt 4: Mergen**

```bash
git checkout main && git pull --ff-only
git merge --no-ff platzrunden-karte
git push
```

---

## Self-Review

**Spec-Abdeckung:** Teil 1 (Abschnitt 2 der Spec) ist als V12.7.1 erledigt, deshalb kein Task. Teil 2 (Abschnitt 3) → Tasks 1–4. Teil 3 (Abschnitt 6) → Tasks 5–7. Abschnitt 7 (Meldepunkte, VFR-Routen) ist bewusst ohne Task. Die Abnahmekriterien aus Abschnitt 10 sind in Task 8 Schritt 3 aufgeführt.

**Typkonsistenz:** `_platzrundenPopup(props)` wird in Task 2 (`onEachFeature`) aufgerufen und in Task 3 definiert — dieselbe Signatur. `_fsePopup(icao, a)` wird in Task 6 (`_fsePlaetzeZeichnen`) aufgerufen und in Task 7 definiert. `_PLATZRUNDEN_MIN_ZOOM` wird in Task 2 gesetzt und in Task 4 verwendet; deshalb ist `test_zoom_schwelle_steht_genau_einmal` in Task 2 Schritt 5 ausdrücklich noch rot.

**Bekannte Lücke:** Der Test `test_die_inseln_sind_dabei` prüft Borkum (`EDWR`) im FSE-Datensatz — dort ist der Platz vorhanden. In den **Platzrunden** fehlt Borkum weiterhin (Spec Abschnitt 9); das ist kein Fehler dieses Plans, sondern eine Lücke der Datenquelle.
