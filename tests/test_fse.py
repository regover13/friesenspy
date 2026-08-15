"""FSE-Ebenen (v12.9.0)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

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


def test_fse_ebenen_haben_getrennte_praeferenz_schluessel():
    """Fix nach Review-Fund: Ein gemeinsamer Schluessel fuer zwei unabhaengige Checkboxen
    wuerde beim Aus-/Einschalten der einen Ebene den gespeicherten Zustand der anderen
    ueberschreiben."""
    assert "_FSE_PLAETZE_PREF_KEY" in INDEX
    assert "_FSE_ZONEN_PREF_KEY" in INDEX
    assert "'friesenspy_fse_plaetze'" in INDEX
    assert "'friesenspy_fse_zonen'" in INDEX


_NODE = shutil.which("node") or shutil.which("nodejs")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_addPreferredFseLayer_haengt_beide_gruppen_ein_und_zwingt_zonen_nach_hinten():
    """Fix nach Review-Fund (Critical): _addPreferredFseLayer haengte beim Laden nur die
    Plaetze-Gruppe ein (`_fsePlaetzeGruppe.addTo(map)`) -- die Zonen-Gruppe wurde NIRGENDS
    `.addTo(map)` gerufen. Zwei Folgen: Die Checkbox "FSE-Landeflaechen" zeigte nach einem
    Reload den falschen Zustand, und ohne bringToBack() haette ein spaeteres manuelles
    Zuschalten die Landeflaechen ueber die Plaetze-Marker gelegt (beide Layer teilen sich den
    overlayPane, Stapelung folgt dem addTo-Zeitpunkt, nicht der Reihenfolge in liveOverlays).

    Ein reiner String-Test auf INDEX kann das prinzipiell nicht fangen (das hat das Review zu
    Recht angemerkt) -- deshalb hier der extrahierte Quelltext wirklich in Node ausgefuehrt,
    mit einem Leaflet-Fake, der bringToBack() bewusst nur auf FeatureGroup-artigen Objekten
    kennt (wie das echte Leaflet: das schlichte LayerGroup, das die Zonen-Gruppe vorher war,
    hat diese Methode gar nicht)."""
    start = INDEX.index("const _FSE_PLAETZE_URL")
    ende_start = INDEX.index("function _addPreferredFseLayer(")
    ende = INDEX.index("\n}", ende_start) + len("\n}")
    quelltext = INDEX[start:ende]

    harness = """
'use strict';
const assert = require('assert');

global.localStorage = (() => {
  const speicher = {};
  return {
    getItem: (k) => (k in speicher ? speicher[k] : null),
    setItem: (k, v) => { speicher[k] = String(v); },
    removeItem: (k) => { delete speicher[k]; },
  };
})();

global.fetch = () => Promise.resolve({ json: () => Promise.resolve({}) });

class FakeLayerGroup {
  constructor(art) { this.art = art; this.addToCalls = []; this._layers = []; }
  addTo(map) { this.addToCalls.push(map); return this; }
  addLayer(l) { this._layers.push(l); return this; }
  eachLayer(fn) { this._layers.forEach(fn); return this; }
  bindPopup() { return this; }
}
// bringToBack existiert in echtem Leaflet NUR auf FeatureGroup (ueber deren invoke()),
// NICHT auf dem schlichten LayerGroup -- absichtlich nachgebildet, damit der Test auch
// einen Rueckfall auf L.layerGroup() fuer die Zonen-Gruppe faengt.
class FakeFeatureGroup extends FakeLayerGroup {
  constructor() { super('featureGroup'); this.bringToBackCalls = 0; }
  bringToBack() { this.bringToBackCalls++; return this; }
}
global.L = {
  layerGroup: () => new FakeLayerGroup('layerGroup'),
  featureGroup: () => new FakeFeatureGroup(),
  polyline: () => new FakeLayerGroup('polyline'),
  circleMarker: () => new FakeLayerGroup('circleMarker'),
};

class FakeMap {
  constructor() { this._handlers = {}; }
  on(event, handler) { (this._handlers[event] = this._handlers[event] || []).push(handler); return this; }
}
"""

    treiber = """
localStorage.setItem(_FSE_PLAETZE_PREF_KEY, '1');
localStorage.setItem(_FSE_ZONEN_PREF_KEY, '1');

const map = new FakeMap();
_addPreferredFseLayer(map);

assert.strictEqual(_fsePlaetzeGruppe.addToCalls.length, 1, 'Plaetze-Gruppe wurde nicht eingehaengt');
assert.strictEqual(_fseZonenGruppe.addToCalls.length, 1, 'Zonen-Gruppe wurde nicht eingehaengt (der urspruengliche Bug)');
assert.ok(_fseZonenGruppe.bringToBackCalls >= 1, 'bringToBack() wurde nicht auf der Zonen-Gruppe aufgerufen');

console.log('OK');
"""

    skript = harness + "\n" + quelltext + "\n" + treiber
    ergebnis = subprocess.run(
        [_NODE, "-e", skript], capture_output=True, text=True, timeout=10
    )
    assert ergebnis.returncode == 0 and "OK" in ergebnis.stdout, (
        f"Node-Lauf fehlgeschlagen -- stdout={ergebnis.stdout!r} stderr={ergebnis.stderr!r}"
    )
