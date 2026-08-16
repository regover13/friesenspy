"""FSE-Ebenen (v12.9.0)."""
import json
import re
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


def _fse_belag_tabelle():
    """Liest die _FSE_BELAG-Tabelle aus dem Quelltext von index.html -- nicht nachbauen,
    sondern denselben Text pruefen, der auch im Browser laeuft."""
    start = INDEX.index("const _FSE_BELAG = {")
    ende = INDEX.index("};", start)
    rumpf = INDEX[start:ende]
    paare = re.findall(r"(\d+):\s*'([^']+)'", rumpf)
    assert paare, "Konnte _FSE_BELAG nicht aus index.html lesen"
    return {int(code): text for code, text in paare}


def test_belag_tabelle_stimmt_mit_fse_planner_ueberein():
    """Review-Fund (Critical): Die Tabelle war ab Code 3 falsch und liess Code 8 aus. Massgeblich
    ist airportSurface() in FSE-Planner (src/util/utility.js, identisch in SurfacePicker.js):
    1 Asphalt, 2 Concrete, 3 Dirt, 4 Grass, 5 Gravel, 6 Helipad, 7 Snow, 8 Water."""
    belag = _fse_belag_tabelle()
    erwartet = {
        1: "Asphalt", 2: "Beton", 3: "Erde", 4: "Gras",
        5: "Kies", 6: "Hubschrauberplatz", 7: "Schnee", 8: "Wasser",
    }
    for code, text in erwartet.items():
        assert belag.get(code) == text, f"Code {code}: erwartet {text!r}, war {belag.get(code)!r}"


def test_belag_stimmt_gegen_echte_plaetze():
    """EGHP Popham ist ein bekannter Grasplatz, EGPR Barra ein bekannter Dirt-Platz (die Landung
    faellt buchstaeblich auf den Strand). Vor dem Fix zeigte EGHP faelschlich 'Sand' (surface 4
    landete auf dem alten Tabelleneintrag fuer 'Sand') und EGEP Papa Westray (Kies) 'Wasser'."""
    ap = json.loads(AIRPORTS.read_text(encoding="utf-8"))
    belag = _fse_belag_tabelle()

    eghp = ap["EGHP"]
    assert eghp["surface"] == 4
    assert belag[eghp["surface"]] == "Gras"

    egpr = ap["EGPR"]
    assert egpr["surface"] == 3
    assert belag[egpr["surface"]] == "Erde"

    egep = ap["EGEP"]
    assert egep["surface"] == 5
    assert belag[egep["surface"]] == "Kies"


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
    stelle = INDEX.index("function _fseZoneBauen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "interactive: false" in rumpf
    assert "fill: false" in rumpf


def test_fse_daten_kommen_aus_dem_ausschnitt_endpunkt():
    """Loest den frueheren Lazy-Load-Test ab: Es gibt keine statischen Europadateien mehr, und
    kein Einmal-Flag. Geholt wird bei jeder nennenswerten Kartenbewegung der Ausschnitt."""
    assert "/static/data/fse_airports_eu.json" not in INDEX
    assert "/static/data/fse_zones_eu.json" not in INDEX
    assert "_fseGeladen" not in INDEX
    assert "'/api/fse/airports'" in INDEX
    assert "'/api/fse/zones'" in INDEX


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


def test_attribution_nennt_fse_planner():
    """Review-Fund (Important): Die MIT-Lizenz verlangt einen Hinweis auf FSE-Planner. Vorher
    stand er nur in einem Quelltext-Kommentar -- fuer niemanden sichtbar. Muss jetzt tatsaechlich
    am Leaflet-Attribution-Control landen (addAttribution/removeAttribution), nicht nur als
    Text irgendwo im Code stehen."""
    assert "github.com/piero-la-lune/FSE-Planner" in INDEX
    assert "attributionControl.addAttribution" in INDEX
    assert "attributionControl.removeAttribution" in INDEX
    stelle = INDEX.index("function _addPreferredFseLayer(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_fseAttributionAn(map)" in rumpf


_NODE = shutil.which("node") or shutil.which("nodejs")


def _fse_quelltext():
    """Der FSE-Block von den Konstanten bis hinter _fseAttributionAus.

    Die Scheibe MUSS _fseAbrufen enthalten -- endete sie bei _fseAbgleichen, waere die
    Funktion gar nicht geladen und jeder Test darueber gruen, ohne etwas zu pruefen.
    """
    start = INDEX.index("const _FSE_PLAETZE_API")
    ende_start = INDEX.index("function _fseAttributionAus(")
    return INDEX[start:INDEX.index("\n}", ende_start) + len("\n}")]


_FSE_HARNESS = """
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

// Stehen im Quelltext VOR dem FSE-Block und sind hier nur Beiwerk.
global._istSichtbar = () => true;
global._labelsImSichtbereich = () => {};

// Antworten je Endpunkt, vom Treiber umsetzbar. WICHTIG: mit r.ok und mit der Huelle
// {plaetze:...} bzw. {zonen:...} -- ohne beides liefe `r.ok ? r.json() : null` bzw. `d.plaetze`
// ins Leere, und die Tests waeren gruen, ohne etwas zu pruefen.
global._antwortPlaetze = { EDXX: { lat: 53, lon: 8, name: 'Test', msfs: ['EDXX'] } };
global._antwortZonen   = { EDXX: [[53, 8], [54, 8]] };
global._fetchLog = [];
global.fetch = (url) => {
  global._fetchLog.push(String(url));
  const zonen = String(url).indexOf('/zones') !== -1;
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(
      zonen ? { zonen: global._antwortZonen, gekappt: false }
            : { plaetze: global._antwortPlaetze, gekappt: false }),
  });
};

// Mitgeloggte Reihenfolge, in der Zonen- bzw. Plaetze-Layer eingehaengt werden, und wann
// bringToBack() dazwischen lief.
global._reihenfolge = [];

class FakeLayer {
  constructor(art) { this.art = art; }
  bindPopup() { return this; }
  bindTooltip() { return this; }
  unbindTooltip() { return this; }
  addTo(gruppe) { gruppe.addLayer(this); return this; }
}

class FakeLayerGroup {
  constructor(art) { this.art = art; this.addToCalls = []; this._layers = []; this._handlers = {}; }
  addTo(ziel) { this.addToCalls.push(ziel); ziel._ebenen.add(this); return this; }
  addLayer(l) {
    this._layers.push(l);
    global._reihenfolge.push(l.art === 'polyline' ? 'zone' : 'platz');
    (this._handlers['layeradd'] || []).forEach(fn => fn({ layer: l }));
    return this;
  }
  removeLayer(l) {
    const i = this._layers.indexOf(l);
    if (i !== -1) this._layers.splice(i, 1);
    global._reihenfolge.push('weg');
    return this;
  }
  clearLayers() { this._layers.length = 0; return this; }
  eachLayer(fn) { this._layers.forEach(fn); return this; }
  on(evt, fn) { (this._handlers[evt] = this._handlers[evt] || []).push(fn); return this; }
}
// bringToBack existiert in echtem Leaflet NUR auf FeatureGroup (ueber deren invoke()), NICHT
// auf dem schlichten LayerGroup -- absichtlich nachgebildet, damit ein Rueckfall auffaellt.
class FakeFeatureGroup extends FakeLayerGroup {
  constructor() { super('featureGroup'); this.bringToBackCalls = 0; }
  bringToBack() { this.bringToBackCalls++; global._reihenfolge.push('nachHinten'); return this; }
}

function _ll(lat, lng) {
  return {
    lat: lat, lng: lng,
    // Grob, aber fuer die Streckensperre genau genug: 1 Grad Breite = 111,32 km.
    distanceTo: (a) => Math.hypot((a.lat - lat) * 111320, (a.lng - lng) * 111320 * Math.cos(lat * Math.PI / 180)),
  };
}

global.L = {
  canvas: () => ({}),
  layerGroup: () => new FakeLayerGroup('layerGroup'),
  featureGroup: () => new FakeFeatureGroup(),
  polyline: () => new FakeLayer('polyline'),
  circleMarker: () => new FakeLayer('circleMarker'),
};

class FakeAttributionControl {
  constructor() { this.calls = []; }
  addAttribution(text) { this.calls.push({ art: 'add', text }); }
  removeAttribution(text) { this.calls.push({ art: 'remove', text }); }
}

class FakeMap {
  constructor(zoom) {
    this._zoom = zoom === undefined ? 10 : zoom;
    this._mitte = _ll(53.0, 8.0);
    this._handlers = {};
    this._ebenen = new Set();
    this.attributionControl = new FakeAttributionControl();
  }
  on(event, handler) {
    // Leaflet nimmt mehrere Ereignisse durch Leerzeichen getrennt entgegen.
    String(event).split(' ').forEach(e => (this._handlers[e] = this._handlers[e] || []).push(handler));
    return this;
  }
  getZoom() { return this._zoom; }
  getCenter() { return this._mitte; }
  // Ecke rund 40 km von der Mitte -- mal _FSE_RAND ergibt einen glatten Abrufradius.
  getBounds() { return { getNorthEast: () => _ll(this._mitte.lat + 0.25, this._mitte.lng + 0.5) }; }
  hasLayer(l) { return this._ebenen.has(l); }
  getContainer() { return {}; }
  feuern(evt) { (this._handlers[evt] || []).forEach(fn => fn()); }
  zieheNach(lat, lng) { this._mitte = _ll(lat, lng); this.feuern('moveend'); }
  setzeZoom(z) { this._zoom = z; this.feuern('zoomend'); }
}
"""


def _node_lauf(treiber, quelltext=None):
    skript = _FSE_HARNESS + "\n" + (quelltext or _fse_quelltext()) + "\n" + treiber
    ergebnis = subprocess.run([_NODE, "-e", skript], capture_output=True, text=True, timeout=15)
    assert ergebnis.returncode == 0 and "OK" in ergebnis.stdout, (
        f"Node-Lauf fehlgeschlagen -- stdout={ergebnis.stdout!r} stderr={ergebnis.stderr!r}"
    )


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_addPreferredFseLayer_haengt_beide_gruppen_ein_und_ruft_einmal_ab():
    """Fix nach Review-Fund (Critical, urspruenglich): _addPreferredFseLayer haengte beim Laden
    nur die Plaetze-Gruppe ein -- die Zonen-Gruppe wurde nirgends `.addTo(map)` gerufen.

    Seit der Umstellung auf den Ausschnitt kommt ein zweiter Fehler derselben Stelle hinzu:
    Wuerde je Zweig ein eigenes _fseAbrufen laufen, saehe der erste die zweite Gruppe noch
    nicht (hasLayer false), und der zweite liefe in die Streckensperre -- die Plaetze blieben
    nach jedem Seitenaufruf leer. Deshalb wird hier geprueft, dass GENAU EIN Abrufpaar
    ausgeht und beide Ebenen etwas bekommen."""
    treiber = """
localStorage.setItem(_FSE_PLAETZE_PREF_KEY, '1');
localStorage.setItem(_FSE_ZONEN_PREF_KEY, '1');

const map = new FakeMap(10);
_addPreferredFseLayer(map);

setImmediate(() => {
  try {
    assert.strictEqual(_fsePlaetzeGruppe.addToCalls.length, 1, 'Plaetze-Gruppe wurde nicht eingehaengt');
    assert.strictEqual(_fseZonenGruppe.addToCalls.length, 1, 'Zonen-Gruppe wurde nicht eingehaengt');

    const zonenAbrufe   = global._fetchLog.filter(u => u.indexOf('/zones') !== -1);
    const plaetzeAbrufe = global._fetchLog.filter(u => u.indexOf('/airports') !== -1);
    assert.strictEqual(zonenAbrufe.length, 1, 'Zonen wurden ' + zonenAbrufe.length + '-mal abgerufen, erwartet genau 1');
    assert.strictEqual(plaetzeAbrufe.length, 1,
      'Plaetze wurden ' + plaetzeAbrufe.length + '-mal abgerufen -- 0 heisst, die Streckensperre hat den zweiten Zweig weggeblockt');

    assert.strictEqual(_fseZonenTabelle.size, 1, 'keine Zone gezeichnet');
    assert.strictEqual(_fsePlaetzeTabelle.size, 1, 'kein Platz gezeichnet');

    const attributionCalls = map.attributionControl.calls.filter(c => c.art === 'add');
    assert.ok(attributionCalls.length >= 1, 'FSE-Planner-Attribution wurde beim Einhaengen nicht hinzugefuegt');
    assert.ok(attributionCalls.every(c => c.text === _FSE_ATTR), 'Attribution enthaelt nicht den erwarteten Hinweis');

    console.log('OK');
  } catch (err) { console.error(err && err.stack ? err.stack : String(err)); process.exitCode = 1; }
});
"""
    _node_lauf(treiber)


def test_klickflaeche_ist_kein_miniradius_mehr():
    """Nutzer-Fund: radius: 3 war bei SVG-Paths auch die Trefferflaeche -- drei Pixel sind am
    Desktop knapp und auf dem Tablet praktisch nicht zu treffen. Der Fix legt einen weichen Halo
    (hoeheres weight, niedrige opacity) um den sichtbaren Punkt; hier wird geprueft, dass Radius
    und Strichbreite nicht wieder auf die alten Mini-Werte zurueckfallen."""
    stelle = INDEX.index("function _fsePlatzBauen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    radius = re.search(r"radius:\s*(\d+)", rumpf)
    weight = re.search(r"weight:\s*(\d+)", rumpf)
    assert radius and int(radius.group(1)) >= 5, "Radius wieder auf Mini-Groesse zurueckgefallen"
    assert weight and int(weight.group(1)) >= 4, (
        "Strichbreite zu duenn, um die Trefferflaeche spuerbar zu vergroessern"
    )


def test_fse_plaetze_gruppe_ist_featuregroup():
    """Wie bei _platzrundenGruppe (s. dortiger Kommentar): Nur L.featureGroup().addLayer() feuert
    'layeradd'. Die Label-Zoom-Wache haengt sich daran, um Marker, die erst NACH dem Einschalten
    nachladen, sofort auf die aktuelle Zoomstufe zu bringen. Ein Rueckfall auf L.layerGroup()
    waere ein stiller Bug: Tooltips blieben bis zur naechsten Zoomaenderung falsch (un)sichtbar."""
    assert "const _fsePlaetzeGruppe = L.featureGroup();" in INDEX


def test_label_zoom_schwelle_steht_genau_einmal():
    assert INDEX.count("_FSE_PLAETZE_LABEL_MIN_ZOOM =") == 1
    assert INDEX.count("_FSE_PLAETZE_LABEL_MIN_ZOOM") >= 2


def test_label_klasse_ist_dezent_ohne_rahmen():
    """Die FSE-Plaetze sind Kulisse, keine Aussage -- die Beschriftung soll das nicht
    konterkarieren: kein Rahmen, gedeckte statt grelle Farbe."""
    stelle = INDEX.index(".fse-platz-label {")
    rumpf = INDEX[stelle:INDEX.index("}", stelle)]
    assert "border: none" in rumpf


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_labels_folgen_der_zoom_schwelle():
    """Unterhalb von _FSE_PLAETZE_LABEL_MIN_ZOOM duerfen die Tooltips nicht offen sein (sonst
    liegen bei 2.335 Plaetzen hunderte Beschriftungen uebereinander), oberhalb schon. Wie beim
    Platzrunden-Pendant (test_zoom_wache_greift_wenn_die_daten_nach_dem_einschalten_eintreffen)
    deckt ein reiner Stringtest den eigentlichen Fehlerfall nicht ab: erst der extrahierte
    Quelltext, wirklich in Node ausgefuehrt, zeigt, ob ein nach dem Einschalten der Wache
    nachgeladener Marker (der reale Ablauf: Checkbox an -> fetch() laeuft -> _fsePlaetzeZeichnen)
    seinen Tooltip korrekt nach der aktuellen Zoomstufe setzt."""
    # Der Viewport-Helfer steht vor dem FSE-Block und wird von der Label-Wache gebraucht.
    start = INDEX.index("function _labelsImSichtbereich(")
    ende_start = INDEX.index("function _fsePlaetzeZoomWache(")
    ende = INDEX.index("\n}", ende_start) + len("\n}")
    quelltext = INDEX[start:ende]

    harness = """
'use strict';
const assert = require('assert');

class FakeGroupBase {
  constructor(art) { this.art = art; this._layers = []; this._handlers = {}; }
  addLayer(l) { this._layers.push(l); return this; }
  addTo(ziel) { return this; }
  eachLayer(fn) { this._layers.forEach(fn); return this; }
  on(evt, fn) { (this._handlers[evt] = this._handlers[evt] || []).push(fn); return this; }
}
// Wie beim Platzrunden-Test: 'layeradd' feuert nur auf FeatureGroup-artigen Objekten, wie im
// echten Leaflet -- ein Rueckfall auf L.layerGroup() in der Produktion wuerde diesen Test reissen.
class FakeFeatureGroup extends FakeGroupBase {
  addLayer(l) {
    super.addLayer(l);
    (this._handlers['layeradd'] || []).forEach(fn => fn({ layer: l }));
    return this;
  }
}

// Minimaler Marker-Fake: haelt fest, ob ein permanenter Tooltip gebunden und geoeffnet ist --
// genau das Verhalten, an dem _fsePlaetzeZoomWache dreht.
class FakeCircleMarker {
  constructor(ll) { this._ll = ll; this._tooltipBound = false; this._tooltipOpen = false; }
  bindPopup() { return this; }
  // Seit dem Viewport-Umbau wird ein Label erst im Bild GEBUNDEN und danach wieder GELOEST --
  // 2.335 dauerhaft gebundene Tooltips waren die Ursache der haengenden Karte.
  bindTooltip() { this._tooltipBound = true; return this; }
  unbindTooltip() { this._tooltipBound = false; this._tooltipOpen = false; return this; }
  addTo(gruppe) { gruppe.addLayer(this); return this; }
  getLatLng() { return this._ll; }
  getTooltip() { return this._tooltipBound ? {} : null; }
  isTooltipOpen() { return this._tooltipOpen; }
  openTooltip() { this._tooltipOpen = true; }
  closeTooltip() { this._tooltipOpen = false; }
}

global.L = {
  // Seit dem Canvas-Umbau reicht die Produktion einen Renderer durch -- der Fake muss ihn
  // liefern, auch wenn er hier wirkungslos ist.
  canvas: () => ({}),
  featureGroup: () => new FakeFeatureGroup('featureGroup'),
  circleMarker: (ll) => new FakeCircleMarker(ll),
};

class FakeMap {
  constructor(zoom) { this._zoom = zoom; this._handlers = {}; }
  getZoom() { return this._zoom; }
  // Der Testplatz liegt immer im Bild -- geprueft wird hier die Zoom-Schwelle, nicht der
  // Ausschnitt.
  getBounds() { return { pad: () => ({ contains: () => true }) }; }
  on(evt, fn) { (this._handlers[evt] = this._handlers[evt] || []).push(fn); return this; }
  setZoomUndFeuern(zoom) {
    this._zoom = zoom;
    (this._handlers['zoomend'] || []).forEach(fn => fn());
  }
}
"""

    treiber = """
try {
  // Zoomstufe klar UNTERHALB der Schwelle -- die Wache haengt schon, BEVOR der Platz eintrifft
  // (der reale Ablauf: Checkbox an -> Wache registriert -> fetch() laeuft nach).
  const map = new FakeMap(0);
  _fsePlaetzeZoomWache(map);

  // Spiegelt, was _fseAbgleichen tut: bauen, dann einhaengen.
  _fsePlatzBauen('EDXX', { lat: 53, lon: 8, name: 'Test', msfs: ['EDXX'] }).addTo(_fsePlaetzeGruppe);

  assert.strictEqual(_fsePlaetzeGruppe._layers.length, 1, 'kein Marker eingehaengt');
  const marker = _fsePlaetzeGruppe._layers[0];
  assert.strictEqual(marker.isTooltipOpen(), false,
    'Tooltip war unterhalb der Zoom-Schwelle offen -- layeradd hat anpassen() nicht ausgeloest');

  // Klar OBERHALB der Schwelle: zoomend muss den Tooltip oeffnen.
  map.setZoomUndFeuern(20);
  assert.strictEqual(marker.isTooltipOpen(), true,
    'Tooltip blieb oberhalb der Zoom-Schwelle zu');

  // Und zurueck unterhalb: zoomend muss ihn wieder schliessen.
  map.setZoomUndFeuern(0);
  assert.strictEqual(marker.isTooltipOpen(), false,
    'Tooltip schloss beim Zurueckzoomen unter die Schwelle nicht wieder');

  console.log('OK');
} catch (err) {
  console.error(err && err.stack ? err.stack : String(err));
  process.exitCode = 1;
}
"""

    skript = harness + "\n" + quelltext + "\n" + treiber
    ergebnis = subprocess.run(
        [_NODE, "-e", skript], capture_output=True, text=True, timeout=10
    )
    assert ergebnis.returncode == 0 and "OK" in ergebnis.stdout, (
        f"Node-Lauf fehlgeschlagen -- stdout={ergebnis.stdout!r} stderr={ergebnis.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Servermodul app/fse.py — Ausschnitt-Auslieferung (Spec 2026-08-16)
# ---------------------------------------------------------------------------

from app import fse as fse_modul  # noqa: E402

WELT = Path(__file__).resolve().parents[1] / "app" / "data" / "fse"

# Messpunkte (16.08.2026 gegen die echten Weltdateien nachgerechnet). Die Radien sind die
# Halbdiagonalen eines 900x700-Panels auf der jeweiligen BREITE -- dieselbe Zoomstufe deckt
# auf 40,7 N mehr Kilometer ab als auf 53,8 N. Ein gemeinsamer Kilometerwert fuer beide Orte
# waere falsch (der Fehler stand in der ersten Fassung des Plans).
EDWG = (53.7872, 7.91583)
KJFK = (40.7, -74.0)
ATLANTIK = (40.0, -40.0)


@pytest.fixture(scope="module")
def bestand():
    return fse_modul.laden(WELT)


def _umschliessende(bestand, treffer, lat, lon):
    return [
        i for i in treffer
        if bestand.zonen_bbox[i][0] <= lat <= bestand.zonen_bbox[i][1]
        and bestand.zonen_bbox[i][2] <= lon <= bestand.zonen_bbox[i][3]
    ]


def test_laden_liest_beide_weltdateien(bestand):
    assert len(bestand.plaetze) == 23780
    # 23.778, nicht 23.780: die zwei Pol-umschliessenden Zellen werden verworfen
    # (s. test_polzellen_werden_gar_nicht_erst_ausgeliefert).
    assert len(bestand.zonen) == 23778
    assert len(bestand.zonen_bbox) == 23778


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


def test_polzellen_werden_gar_nicht_erst_ausgeliefert():
    """CYLT (Alert) und NZPG (McMurdo) umschliessen je einen Pol: Ihre Ecken laufen einmal ganz
    um die Erde. So ein Ring hat in Laenge/Breite keine nahtfreie Darstellung -- Leaflet zieht
    daraus ein Band quer ueber die Karte, und zwar bei JEDER Abfrage in ihrem Breitenband,
    weil ihre Bbox fast den ganzen Laengenbereich abdeckt. Eine Zweig-Korrektur reicht nicht:
    bei CYLT bringt sie die Spanne nur von 342 auf 234 Grad."""
    b = fse_modul.laden(WELT)
    assert "CYLT" not in b.zonen
    assert "NZPG" not in b.zonen
    assert len(b.zonen) == 23778


def test_zweig_korrektur_laesst_die_heilen_zonen_in_ruhe():
    """34 der 36 Zonen jenseits +-180 sind DURCHGEHEND (NFNA 175,98 -> 181,65) und zeichnen
    sich ueber die Datumsgrenze korrekt. Pauschales Normalisieren auf +-180 machte aus genau
    diesen 34 die Baender, die hier beseitigt werden sollen."""
    b = fse_modul.laden(WELT)
    roh = json.loads((WELT / "fse_zones_world.json").read_text(encoding="utf-8"))
    assert b.zonen["NFNA"] == roh["NFNA"], "eine heile Zone wurde faelschlich veraendert"
    assert max(p[1] for p in b.zonen["NFNA"]) > 180
    jenseits = [k for k, v in roh.items() if any(p[1] > 180 or p[1] < -180 for p in v)]
    assert len(jenseits) == 36
    assert sum(1 for k in jenseits if k in b.zonen) == 34


def test_die_zelle_in_der_man_steht_kommt_zuerst(bestand):
    """Gemessen wird vom Bezugspunkt, nicht vom Ausschnitts-Rechteck. Gegen das Rechteck haette
    jede schneidende Zone Abstand 0 -- bei New York 389 Stueck -- und der Deckel entschiede
    zwischen ihnen alphabetisch. Die umschliessende Zelle flog dabei heraus."""
    treffer, gekappt = fse_modul.zonen_im_umkreis(bestand, *KJFK, 150)
    assert gekappt
    assert _umschliessende(bestand, treffer, *KJFK)


# ---------------------------------------------------------------------------
# Die zwei Endpunkte
# ---------------------------------------------------------------------------

import inspect  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import main as main_modul  # noqa: E402


@pytest.fixture()
def klient(bestand, tmp_path, monkeypatch):
    """TestClient OHNE ``with`` — der Lifespan darf hier nicht laufen.

    Er liest ``SECRET_KEY`` (das hat keinen Default und steht nur in config.env), ruft
    ``init_db`` auf dem PRODUKTIONSPFAD /opt/friesenspy/data/friesenspy.db und startet den
    VATSIM-Poller gegen die echte API. Das Hausmuster dagegen steht in
    tests/test_traffic_api.py:79: Settings per monkeypatch ersetzen und den Zustand direkt an
    app.state haengen.

    ``bestand`` kommt aus der Fixture weiter oben — so werden die 6 MB einmal je Modul
    gelesen statt einmal je Test.
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
    Threadpool -- ein ``async def`` hier waere eine stille Bremse fuer die ganze Anwendung."""
    for name in ("get_fse_airports", "get_fse_zones"):
        fn = getattr(main_modul, name)
        assert not inspect.iscoroutinefunction(fn), f"{name} ist async def"


def test_fse_endpunkte_stehen_nicht_im_gate_allowlist():
    """Wie /api/traffic: kein Sonderweg an der Anmeldung vorbei."""
    quelle = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    stelle = quelle.index("_GATE_ALLOW_PREFIXES")
    assert "/api/fse" not in quelle[stelle:quelle.index("\n\n", stelle)]


def test_bestand_wird_beim_start_geladen():
    """Der Ladeschritt gehoert HINTER den try/finally-Block um die DB-Verbindung -- 0,8 s
    JSON-Parsen mit offen gehaltener Verbindung waere unnoetig."""
    quelle = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    rumpf = quelle[quelle.index("async def lifespan("):quelle.index("\n    yield")]
    assert "app.state.fse = fse.laden(" in rumpf
    assert rumpf.index("conn.close()") < rumpf.index("app.state.fse = fse.laden(")


# ---------------------------------------------------------------------------
# Frontend: Abruf ueber Strecke, Abgleich statt Neuzeichnen
# ---------------------------------------------------------------------------


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


def test_frontend_haengt_nicht_an_naviSelbstBewegt():
    """Der Verkehr filtert moveend ueber !_naviSelbstBewegt (index.html:4570). Fuer die
    FSE-Ebene waere das ein Fehler: Bei eingeschalteter Moving Map bewegt die Karte sich
    selbst, die Wache griffe also immer -- und anders als der Verkehr hat diese Ebene keinen
    Takt als zweite Quelle. Sie wuerde im Kniebrett waehrend des ganzen Fluges nie nachladen."""
    stelle = INDEX.index("function _addPreferredFseLayer(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_fseAbrufen(map)" in rumpf
    assert "_naviSelbstBewegt" not in rumpf


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_frontend_ruft_nicht_bei_jeder_bewegung_ab():
    """Kern der Streckensperre. Der Abrufradius ergibt sich in der Attrappe zu 54 km, die
    Schwelle liegt damit bei 10,8 km:
      - Zoom 5 (unter _FSE_MIN_ZOOM): gar kein Abruf
      - erster Abruf auf Zoom 10:     geht raus
      - 5,6 km gewandert:             KEIN weiterer
      - 22,3 km gewandert:            weiterer
      - Zoomwechsel ohne Bewegung:    weiterer
    """
    treiber = """
const map = new FakeMap(5);
_fsePlaetzeGruppe.addTo(map);

_fseAbrufen(map);
assert.strictEqual(global._fetchLog.length, 0, 'unterhalb _FSE_MIN_ZOOM wurde abgerufen');

map._zoom = 10;
_fseAbrufen(map);
assert.strictEqual(global._fetchLog.length, 1, 'der erste Abruf blieb aus');

map._mitte = _ll(53.05, 8.0);          // rund 5,6 km -- unter der Schwelle
_fseAbrufen(map);
assert.strictEqual(global._fetchLog.length, 1, 'nach 5,6 km wurde erneut abgerufen -- die Sperre greift nicht');

map._mitte = _ll(53.2, 8.0);           // rund 22,3 km -- ueber der Schwelle
_fseAbrufen(map);
assert.strictEqual(global._fetchLog.length, 2, 'nach 22,3 km wurde NICHT nachgeladen');

map._zoom = 11;
_fseAbrufen(map);
assert.strictEqual(global._fetchLog.length, 3, 'ein Zoomwechsel muss immer ausloesen');

console.log('OK');
"""
    _node_lauf(treiber)


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_frontend_holt_beim_einschalten_sofort():
    """Ohne Ruecksetzen von _fseLetzteMitte blockt die Streckensperre den Abruf, der auf
    'overlayadd' folgt -- die frisch zugeschaltete Ebene bliebe leer, bis der Nutzer ein
    Fuenftel Radius fliegt."""
    treiber = """
const map = new FakeMap(10);
_addPreferredFseLayer(map);                 // beide Praeferenzen aus -> nichts eingehaengt
assert.strictEqual(global._fetchLog.length, 0);

// Zonen von Hand einschalten und das Ereignis feuern, wie die Layers-Control es tut.
_fseZonenGruppe.addTo(map);
(map._handlers['overlayadd'] || []).forEach(fn => fn({ layer: _fseZonenGruppe }));

setImmediate(() => {
  try {
    assert.strictEqual(global._fetchLog.filter(u => u.indexOf('/zones') !== -1).length, 1,
      'Einschalten hat keinen Abruf ausgeloest');
    assert.strictEqual(_fseZonenTabelle.size, 1, 'nach dem Einschalten ist die Ebene leer');

    // Jetzt die Plaetze dazu -- OHNE dass die Karte sich bewegt hat.
    _fsePlaetzeGruppe.addTo(map);
    (map._handlers['overlayadd'] || []).forEach(fn => fn({ layer: _fsePlaetzeGruppe }));
    setImmediate(() => {
      try {
        assert.strictEqual(global._fetchLog.filter(u => u.indexOf('/airports') !== -1).length, 1,
          'die zweite Ebene wurde von der Streckensperre weggeblockt');
        assert.strictEqual(_fsePlaetzeTabelle.size, 1);
        console.log('OK');
      } catch (e) { console.error(e.stack || String(e)); process.exitCode = 1; }
    });
  } catch (err) { console.error(err && err.stack ? err.stack : String(err)); process.exitCode = 1; }
});
"""
    _node_lauf(treiber)


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_frontend_gleicht_ab_statt_neu_zu_zeichnen():
    """Der Abgleich ist der Grund, warum die permanenten ICAO-Beschriftungen beim Fliegen
    nicht flackern: Ein ICAO, der in zwei aufeinanderfolgenden Antworten steht, muss
    UNANGETASTET bleiben -- nicht entfernt und neu gezeichnet. Was wegfaellt, muss dagegen
    wirklich aus der Karte verschwinden, sonst waechst sie im Flug endlos."""
    treiber = """
const map = new FakeMap(10);
_fsePlaetzeGruppe.addTo(map);

global._antwortPlaetze = {
  AAAA: { lat: 53, lon: 8, name: 'Bleibt', msfs: ['AAAA'] },
  BBBB: { lat: 53.1, lon: 8.1, name: 'Faellt weg', msfs: ['BBBB'] },
};
_fseAbrufen(map);

setImmediate(() => {
  try {
    assert.strictEqual(_fsePlaetzeTabelle.size, 2);
    const bleibt = _fsePlaetzeTabelle.get('AAAA');

    // Zweite Antwort: AAAA bleibt, BBBB faellt weg, CCCC kommt dazu.
    global._antwortPlaetze = {
      AAAA: { lat: 53, lon: 8, name: 'Bleibt', msfs: ['AAAA'] },
      CCCC: { lat: 53.2, lon: 8.2, name: 'Neu', msfs: ['CCCC'] },
    };
    map._mitte = _ll(53.3, 8.0);      // weit genug fuer einen neuen Abruf
    _fseAbrufen(map);

    setImmediate(() => {
      try {
        assert.strictEqual(_fsePlaetzeTabelle.size, 2, 'Tabelle nach dem Abgleich falsch gross');
        assert.ok(_fsePlaetzeTabelle.has('CCCC'), 'der neue Platz fehlt');
        assert.ok(!_fsePlaetzeTabelle.has('BBBB'), 'der weggefallene Platz liegt noch in der Karte');
        assert.strictEqual(_fsePlaetzeTabelle.get('AAAA'), bleibt,
          'AAAA wurde neu gezeichnet, obwohl er in beiden Antworten steht -- genau das laesst die Beschriftungen flackern');
        assert.strictEqual(_fsePlaetzeGruppe._layers.length, 2, 'die Gruppe waechst statt abzugleichen');
        console.log('OK');
      } catch (e) { console.error(e.stack || String(e)); process.exitCode = 1; }
    });
  } catch (err) { console.error(err && err.stack ? err.stack : String(err)); process.exitCode = 1; }
});
"""
    _node_lauf(treiber)


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_frontend_zwingt_die_zonen_nach_jedem_nachladen_nach_hinten():
    """Beide Ebenen teilen sich EINEN Canvas-Renderer (index.html, _fseRenderer) -- massgeblich
    ist die Zeichenreihenfolge im Canvas, nicht der overlayPane. Zwei unabhaengige fetch ordnen
    sich nicht, und jedes Nachladen haengt neue Zonen ans ENDE der Zeichenliste, also ueber die
    vorhandenen Platzmarker. Ohne bringToBack() NACH JEDEM Zonen-Abgleich liegt die graue
    Kulisse nach ein paar Minuten Flug obenauf."""
    treiber = """
const map = new FakeMap(10);
_fseZonenGruppe.addTo(map);
_fsePlaetzeGruppe.addTo(map);

_fseAbrufen(map);
setImmediate(() => {
  try {
    const ersteRunde = _fseZonenGruppe.bringToBackCalls;
    assert.ok(ersteRunde >= 1, 'bringToBack() lief beim ersten Zeichnen nicht');

    // Zweite Runde mit einer ANDEREN Zone, damit wirklich neu eingehaengt wird.
    global._antwortZonen = { EDYY: [[55, 9], [56, 9]] };
    map._mitte = _ll(53.3, 8.0);
    _fseAbrufen(map);
    setImmediate(() => {
      try {
        assert.ok(_fseZonenGruppe.bringToBackCalls > ersteRunde,
          'bringToBack() lief nur beim Einschalten -- die Kulisse wandert beim Nachladen ueber die Marker');
        // Und zwar NACH dem Einhaengen, nicht davor: auf einer leeren Gruppe waere es ein No-Op.
        const letztesEinhaengen = global._reihenfolge.lastIndexOf('zone');
        const letztesNachHinten = global._reihenfolge.lastIndexOf('nachHinten');
        assert.ok(letztesNachHinten > letztesEinhaengen,
          'bringToBack() lief VOR dem Einhaengen der neuen Zonen -- auf der noch leeren Gruppe ein No-Op');
        console.log('OK');
      } catch (e) { console.error(e.stack || String(e)); process.exitCode = 1; }
    });
  } catch (err) { console.error(err && err.stack ? err.stack : String(err)); process.exitCode = 1; }
});
"""
    _node_lauf(treiber)
