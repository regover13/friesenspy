"""Der Gleit-Takt: Flugzeugsymbole laufen, statt im Sekundenraster zu springen.

Die Fortrechnung aus Kurs und Fahrt (`_jetztGerechnet`) gab es lange — ausgewertet wurde
sie aber nur von `_naviTakt`, und der läuft einmal pro Sekunde. Das Symbol stand dadurch
eine Sekunde still und sprang dann um den ganzen zurückgelegten Weg: bei Zoom 14 und 120 kt
rund 11 Pixel, beim Hineinzoomen ein Vielfaches davon. Die Brügge meldet zwar sekundengenau,
sichtbar war davon nur ein feinerer Sprung.

Geprüft wird deshalb nicht die Rechnung (die ist alt und stimmte), sondern **wie oft sie auf
die Karte kommt** — und vor allem, was im feinen Takt NICHT passieren darf: kein `setIcon`,
kein Label, kein Anfassen der Karte selbst. Genau daran hing die Entscheidung gegen
`requestAnimationFrame` aus der Flackersuche v12.5.2.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

INDEX = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(
    encoding="utf-8")

_NODE = shutil.which("node")


def _funktion(name: str) -> str:
    """Eine benannte Funktion aus dem Quelltext schneiden.

    An den Namen gebunden, nicht an eine Zeilennummer: Der Ausschnitt muss mitwandern, wenn
    jemand darüber etwas einfügt. Findet sich die Funktion nicht, ist das ein Fehlschlag und
    keine übersprungene Prüfung — sonst würde eine umbenannte Funktion den Test stillschweigend
    entwerten.
    """
    kopf = "\nfunction %s(" % name
    assert kopf in INDEX, "Funktion %s() gibt es nicht (mehr)" % name
    start = INDEX.index(kopf) + 1
    ende = INDEX.index("\n}", start) + len("\n}")
    return INDEX[start:ende]


# ---------------------------------------------------------------------------
# Der Takt selbst
# ---------------------------------------------------------------------------

def test_es_gibt_einen_takt_feiner_als_eine_sekunde():
    """Ohne ihn bleibt es beim Sekundenraster, egal wie genau die Rechnung ist."""
    treffer = re.search(r"_GLEIT_TAKT_MS\s*=\s*(\d+)", INDEX)
    assert treffer, "keine Konstante _GLEIT_TAKT_MS"
    ms = int(treffer.group(1))
    assert 0 < ms < 1000, "der Gleit-Takt ist nicht feiner als der Sekundentakt"
    # Und er ist kein Einzelbild-Takt: Die Flackersuche v12.5.2 hat gezeigt, was eine
    # Schleife in JEDEM Bild in Coherent GT anrichtet. 16 ms wären genau das zu Fuss.
    assert ms >= 50, "so fein ist es eine rAF-Schleife mit anderem Namen"


def test_der_takt_laeuft_auch_wirklich():
    assert re.search(r"setInterval\(\s*_markerGleiten\s*,\s*_GLEIT_TAKT_MS\s*\)", INDEX), \
        "_markerGleiten wird nirgends im Gleit-Takt aufgerufen"


def test_der_feine_takt_fasst_nur_positionen_an():
    """Die eine Regel, an der alles hängt.

    `setIcon` ersetzt das DOM-Element des Markers vollständig, `setTooltipContent` schreibt
    HTML, `setView` zeichnet die halbe Karte neu — zehnmal pro Sekunde ist jedes davon genau
    die Dauerlast, die v12.5.2 sichtbar gemacht hat. Im feinen Takt gehört ausschliesslich
    `setLatLng` hinein; alles andere bleibt im Sekundentakt.
    """
    quelle = _funktion("_markerGleiten")
    for verboten in ("setIcon", "setTooltip", "setView", "setBearing", "innerHTML"):
        assert verboten not in quelle, \
            "%s() darf im Gleit-Takt nicht vorkommen" % verboten


# ---------------------------------------------------------------------------
# Verhalten, in Node gemessen
# ---------------------------------------------------------------------------

_HARNESS = """
'use strict';
const assert = require('assert');

// Die Uhr steuerbar machen: Der Test prueft die Bewegung, nicht die Geduld.
let _jetzt = 1000000;
Date.now = () => _jetzt;

class MarkerStub {
  constructor() { this.pos = null; this.iconAufrufe = 0; }
  setLatLng(p) { this.pos = [p[0], p[1]]; }
  setIcon() { this.iconAufrufe++; }
}

global.liveMap = { getContainer: () => ({}) };
global.mapMarkers = {};
global._verkehrMarker = {};
global._verkehrRoh = {};
global._positionsRoh = {};
global._simPos = null;
global._movingMap = false;
global._kartenSichtbar = true;
global._eigenerSimMarker = null;
global._meineCid = null;
global._SIM_POS_MAX_ALTER_MS = 10000;
global._eigenes = null;
function _istEigenesFlugzeug(cs) { return global._eigenes === cs; }
function _simPosFrisch() { return !!(_simPos && (Date.now() - _simPos.ts) < 10000); }
function _meinCallsign() { return global._eigenes; }

__QUELLTEXT__

__PRUEFUNG__
console.log('OK');
"""


def _node(pruefung: str, *funktionen: str) -> str:
    if not _NODE:
        pytest.skip("node nicht vorhanden")
    # `_simPosJetzt` und `_jetztGerechnet` immer mit: `_markerGleiten` ruft beide auf, und
    # eine fehlende Deklaration waere ein ReferenceError statt einer Aussage.
    namen = ["_jetztGerechnet", "_simPosJetzt"] + [n for n in funktionen
                                                   if n not in ("_jetztGerechnet", "_simPosJetzt")]
    quelltext = "\n\n".join(_funktion(n) for n in namen)
    quelle = _HARNESS.replace("__QUELLTEXT__", quelltext).replace("__PRUEFUNG__", pruefung)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(quelle)
        name = f.name
    lauf = subprocess.run([_NODE, name], capture_output=True, text=True, timeout=30)
    assert lauf.returncode == 0, lauf.stdout + lauf.stderr
    return lauf.stdout


def test_zwischen_zwei_sekunden_bewegt_sich_das_symbol_mehrfach():
    """Der eigentliche Fund: Bei 600 kt nach Norden liegen zwischen zwei Sekunden gut
    300 Meter. Bisher kamen sie als EIN Sprung auf die Karte."""
    _node("""
      global.mapMarkers = { 'FRS49': new MarkerStub() };
      global._positionsRoh = { 'FRS49': { lat: 53.0, lon: 8.0, hdg: 0, gs: 600, ts: _jetzt } };

      _jetzt += 100; _markerGleiten();
      const a = mapMarkers['FRS49'].pos[0];
      _jetzt += 100; _markerGleiten();
      const b = mapMarkers['FRS49'].pos[0];
      _jetzt += 100; _markerGleiten();
      const c = mapMarkers['FRS49'].pos[0];

      assert.ok(a > 53.0, 'nach 100 ms noch nicht bewegt');
      assert.ok(b > a && c > b, 'die Bewegung laeuft nicht weiter');
      // Gleichmaessig, nicht schubweise: gleiche Zeit, gleicher Weg.
      const s1 = b - a, s2 = c - b;
      assert.ok(Math.abs(s1 - s2) < s1 * 0.01, 'die Schritte sind ungleich lang');
    """, "_jetztGerechnet", "_markerGleiten")


def test_der_feine_takt_ruehrt_das_symbol_selbst_nicht_an():
    """Kurs, Farbe und Schild bleiben Sache des Sekundentakts — sonst baut der Gleit-Takt
    zehnmal pro Sekunde ein DOM-Element neu auf."""
    _node("""
      global.mapMarkers = { 'FRS49': new MarkerStub() };
      global._positionsRoh = { 'FRS49': { lat: 53.0, lon: 8.0, hdg: 90, gs: 120, ts: _jetzt } };
      for (let i = 0; i < 10; i++) { _jetzt += 100; _markerGleiten(); }
      assert.strictEqual(mapMarkers['FRS49'].iconAufrufe, 0, 'setIcon im Gleit-Takt');
    """, "_jetztGerechnet", "_markerGleiten")


def test_ohne_rohwert_bleibt_der_marker_stehen():
    """Dieselbe Regel wie im Sekundentakt: lieber stehen bleiben als auf eine geratene
    Position springen."""
    _node("""
      global.mapMarkers = { 'FRS49': new MarkerStub() };
      global._positionsRoh = {};
      _jetzt += 100; _markerGleiten();
      assert.strictEqual(mapMarkers['FRS49'].pos, null);
    """, "_jetztGerechnet", "_markerGleiten")


def test_fremdverkehr_gleitet_mit():
    """Er hat eine eigene Quelle, aber dasselbe Problem — und lief bisher im selben Raster."""
    _node("""
      global._verkehrMarker = { 'DLH400': new MarkerStub() };
      global._verkehrRoh = { 'DLH400': { lat: 53.0, lon: 8.0, hdg: 0, gs: 400, ts: _jetzt } };
      _jetzt += 100; _markerGleiten();
      assert.ok(_verkehrMarker['DLH400'].pos[0] > 53.0, 'Fremdverkehr steht still');
    """, "_jetztGerechnet", "_markerGleiten")


def test_das_eigene_flugzeug_gleitet_ebenfalls():
    """Im Kniebrett das wichtigste Symbol überhaupt. Es kommt aus `_simPos` und wurde bisher
    gar nicht fortgerechnet — die EFB-Shell meldet höchstens im Sekundentakt (Herzschlag alle
    2 s), es sprang also genauso wie alle anderen."""
    _node("""
      global._eigenes = 'FRS49';
      global.mapMarkers = { 'FRS49': new MarkerStub() };
      global._simPos = { lat: 53.0, lon: 8.0, hdg: 0, gs: 300, ts: _jetzt };
      global._meineCid = 4711;
      _jetzt += 100; _markerGleiten();
      assert.ok(mapMarkers['FRS49'].pos, 'das eigene Flugzeug wurde nicht bewegt');
      assert.ok(mapMarkers['FRS49'].pos[0] > 53.0, 'das eigene Flugzeug steht still');
    """, "_jetztGerechnet", "_simPosJetzt", "_markerGleiten")


def test_bei_moving_map_gleitet_das_eigene_flugzeug_nicht():
    """Der Sonderfall, der sonst schlechter aussähe als vorher: Bei Moving Map ist der eigene
    Flieger der Fixpunkt in der Kartenmitte, und die Karte zieht nur im Sekundentakt nach
    (`setView` zehnmal pro Sekunde wäre genau die Last, die hier vermieden wird). Würde das
    Symbol dazwischen weitergleiten, kröche es aus der Mitte heraus und spränge jede Sekunde
    zurück."""
    _node("""
      global._eigenes = 'FRS49';
      global._movingMap = true;
      global.mapMarkers = { 'FRS49': new MarkerStub() };
      global._simPos = { lat: 53.0, lon: 8.0, hdg: 0, gs: 300, ts: _jetzt };
      global._meineCid = 4711;
      _jetzt += 100; _markerGleiten();
      assert.strictEqual(mapMarkers['FRS49'].pos, null, 'bei Moving Map doch bewegt');
    """, "_jetztGerechnet", "_simPosJetzt", "_markerGleiten")


def test_auf_verdeckter_karte_laeuft_nichts():
    """Zehnmal pro Sekunde auf einer Karte zu rechnen, die niemand sieht, ist Arbeit ohne
    Wirkung — dieselbe Überlegung wie in `_naviTakt` und `updateMap`."""
    _node("""
      global._kartenSichtbar = false;
      global.mapMarkers = { 'FRS49': new MarkerStub() };
      global._positionsRoh = { 'FRS49': { lat: 53.0, lon: 8.0, hdg: 0, gs: 600, ts: _jetzt } };
      _jetzt += 100; _markerGleiten();
      assert.strictEqual(mapMarkers['FRS49'].pos, null, 'auf verdeckter Karte gerechnet');
    """, "_jetztGerechnet", "_markerGleiten")
