"""FSE-Ebenen (v12.9.0)."""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
# Der Europa-Zuschnitt ist am 16.08.2026 entfallen: Es gibt nur noch den Weltbestand, und der
# liegt unter app/data/ statt app/static/ -- was unter static/ liegt, wird als Ganzes
# ausgeliefert, und genau das soll hier nicht passieren.
AIRPORTS = Path(__file__).resolve().parents[1] / "app" / "data" / "fse" / "fse_airports_world.json"
ZONES = Path(__file__).resolve().parents[1] / "app" / "data" / "fse" / "fse_zones_world.json"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_dateien_liegen_im_repo():
    assert AIRPORTS.exists() and ZONES.exists()


def test_weltbestand_ist_vollstaendig():
    """Kein Zuschnitt mehr -- die Begrenzung passiert am Endpunkt, nicht am Datensatz."""
    ap = json.loads(AIRPORTS.read_text(encoding="utf-8"))
    assert len(ap) == 23780
    assert "KJFK" in ap and "NZWN" in ap and "EDWG" in ap


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
// NUR setzen, wenn die Scheibe die echte Funktion nicht mitbringt. Funktionsdeklarationen
// werden hochgezogen, existieren hier also bereits -- eine bedingungslose Zuweisung wuerde die
// echte Funktion ueberschreiben, und ein Test, der genau sie prueft, saehe die leere Attrappe
// (eigener Fehler, gefunden beim Aufwand-Test 16.08.2026).
if (typeof _labelsImSichtbereich === 'undefined') global._labelsImSichtbereich = () => {};

// Antworten je Endpunkt, vom Treiber umsetzbar. WICHTIG: mit r.ok und mit der Huelle
// {plaetze:...} bzw. {zonen:...} -- ohne beides liefe `r.ok ? r.json() : null` bzw. `d.plaetze`
// ins Leere, und die Tests waeren gruen, ohne etwas zu pruefen.
global._antwortPlaetze = { EDXX: { lat: 53, lon: 8, name: 'Test', msfs: ['EDXX'] } };
global._antwortZonen   = { EDXX: [[53, 8], [54, 8]] };
global._fetchLog = [];
// Vom Treiber steuerbar: _fetchOk=false erzwingt den 422/401-Fall, _fetchVerzoegerung haelt
// die Antwort um n Makrotasks zurueck (fuer den Ueberhol-Test).
global._fetchOk = true;
global._fetchVerzoegerung = 0;
global.fetch = (url) => {
  global._fetchLog.push(String(url));
  const zonen = String(url).indexOf('/zones') !== -1;
  // Nutzlast JETZT festhalten, nicht erst beim Aufloesen: Sonst liest eine zurueckgehaltene
  // Antwort den inzwischen geaenderten Zustand, und ein Ueberhol-Test kann gar nichts messen
  // (eigener Fehler, gefunden per Mutationsprobe 16.08.2026).
  const nutzlast = zonen ? { zonen: global._antwortZonen, gekappt: false }
                         : { plaetze: global._antwortPlaetze, gekappt: false };
  const antwort = { ok: global._fetchOk, json: () => Promise.resolve(nutzlast) };
  const halten = global._fetchVerzoegerung;
  if (!halten) return Promise.resolve(antwort);
  return new Promise((fertig) => {
    let n = halten;
    const takt = () => (--n <= 0 ? fertig(antwort) : setImmediate(takt));
    setImmediate(takt);
  });
};

// Mitgeloggte Reihenfolge, in der Zonen- bzw. Plaetze-Layer eingehaengt werden, und wann
// bringToBack() dazwischen lief.
global._reihenfolge = [];
global._besuche = 0;   // Layer-Besuche in eachLayer -- misst den Aufwand der Label-Logik

class FakeLayer {
  constructor(art) { this.art = art; this._tip = null; this._offen = false; }
  bindPopup() { return this; }
  // Vollstaendige Tooltip-Attrappe: _labelsImSichtbereich bindet erst im Bild und loest
  // danach wieder -- ohne getTooltip() kann der Aufwand-Test das nicht nachvollziehen.
  bindTooltip(text) { this._tip = { text: text }; return this; }
  unbindTooltip() { this._tip = null; this._offen = false; return this; }
  getTooltip() { return this._tip; }
  openTooltip() { this._offen = true; }
  closeTooltip() { this._offen = false; }
  isTooltipOpen() { return this._offen; }
  getLatLng() { return _ll(53, 8); }
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
  eachLayer(fn) { global._besuche += this._layers.length; this._layers.forEach(fn); return this; }
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
    // Wie L.LatLng.wrap(): zieht die Laenge auf [-180, 180], laesst die Breite in Ruhe.
    wrap: () => _ll(lat, ((lng + 180) % 360 + 360) % 360 - 180),
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
  getBounds() { return { getNorthEast: () => _ll(this._mitte.lat + 0.25, this._mitte.lng + 0.5),
                         pad: () => ({ contains: () => true }) }; }
  hasLayer(l) { return this._ebenen.has(l); }
  getContainer() { return {}; }
  feuern(evt) { (this._handlers[evt] || []).forEach(fn => fn()); }
  zieheNach(lat, lng) { this._mitte = _ll(lat, lng); this.feuern('moveend'); }
  setzeZoom(z) { this._zoom = z; this.feuern('zoomend'); }
}
"""


def _node_starten(skript, timeout):
    """Skript ueber eine DATEI an node geben, nicht ueber ``-e``.

    Windows begrenzt die gesamte Kommandozeile auf 32 767 Zeichen. Der Quelltextausschnitt
    aus index.html liegt knapp darunter -- als am 16.08.2026 zwanzig Zeilen im Verkehrsteil
    dazukamen, kippte er darueber, und der Test starb mit ``[WinError 206] Der Dateiname oder
    die Erweiterung ist zu lang``. Das sah aus wie ein kaputter Test, war aber nur eine zu
    lange Kommandozeile: eine Grenze, die mit jedem Wachstum der Datei naeher rueckt und mit
    dem Geprueften nichts zu tun hat. Ueber eine Datei gibt es sie nicht.
    """
    with tempfile.TemporaryDirectory() as ordner:
        pfad = Path(ordner) / "lauf.js"
        pfad.write_text(skript, encoding="utf-8")
        return subprocess.run([_NODE, str(pfad)], capture_output=True, text=True,
                              timeout=timeout)


def _node_lauf(treiber, quelltext=None):
    skript = _FSE_HARNESS + "\n" + (quelltext or _fse_quelltext()) + "\n" + treiber
    ergebnis = _node_starten(skript, 15)
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


def _platz_stil():
    """Radius, Strichbreite und Farben des FSE-Platzmarkers aus index.html."""
    stelle = INDEX.index("function _fsePlatzBauen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    zahl = lambda name: float(re.search(rf"{name}:\s*([\d.]+)", rumpf).group(1))
    farbe = lambda name: re.search(rf"{name}:\s*'#([0-9a-fA-F]{{6}})'", rumpf).group(1)
    return zahl("radius"), zahl("weight"), farbe("color"), farbe("fillColor")


def test_klickflaeche_ist_kein_miniradius_mehr():
    """Nutzer-Fund: radius 3 war zugleich die Trefferflaeche -- am Desktop knapp, auf dem
    Tablet nicht zu treffen.

    Geprueft wird die ABGELEITETE Groesse `radius + weight/2`, nicht Radius und Strichbreite
    einzeln. Die frueher hier stehenden Einzelschwellen (`weight >= 4`) waren an einen
    bestimmten Kniff gebunden -- einen breiten, fast durchsichtigen Halo -- und schlugen fehl,
    als der Halo einem schmalen, deckenden Saum wich, obwohl die Trefferflaeche praktisch
    gleich blieb. Ein Test soll die Eigenschaft festhalten, nicht ihre damalige Umsetzung."""
    radius, weight, _, _ = _platz_stil()
    treffer = radius + weight / 2
    assert treffer >= 7, f"Trefferflaeche nur {treffer} px -- auf dem Tablet zu klein"


def test_platzmarker_hat_einen_gegenlaeufigen_saum():
    """Nutzer-Fund am laufenden Bild (16.08.2026): Der Punkt war einfarbig sandgelb, Rand wie
    Fuellung. Auf der dunklen Karte steht er gut, auf der hellen CARTO-Karte sauft er ab.

    Dieselbe Lehre wie bei den Flugzeugsymbolen, wo sie schon einmal teuer gelernt wurde: Ein
    heller Saum ist auf hellem Grund per Definition unsichtbar. Der Saum muss GEGENLAEUFIG zur
    Fuellung sein und deckend -- ein breiter Strich bei niedriger Deckkraft faerbt den Punkt
    nur ein, statt ihm eine Kante zu geben."""
    radius, weight, rand, fuellung = _platz_stil()
    assert rand != fuellung, "Rand und Fuellung sind gleich -- das ist kein Saum"

    hell = lambda h: _kontrast(tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)), (0xFF, 0xFF, 0xFF))
    assert hell(rand) > hell(fuellung), (
        f"Der Saum (#{rand}) ist heller als die Fuellung (#{fuellung}) -- auf heller Karte "
        "ist genau das unsichtbar")
    assert _kontrast(tuple(int(rand[i:i + 2], 16) for i in (0, 2, 4)),
                     (0xF8, 0xF9, 0xFA)) >= 4.5, "Saum hebt sich nicht von der hellen Karte ab"

    stelle = INDEX.index("function _fsePlatzBauen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    deckkraft = float(re.search(r"\bopacity:\s*([\d.]+)", rumpf).group(1))
    assert deckkraft >= 0.9, f"Saum mit Deckkraft {deckkraft} faerbt den Punkt, statt ihn zu umranden"


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
    ergebnis = _node_starten(skript, 10)
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

    # Und zwar die NAECHSTEN 250. Ohne diese Pruefung bleibt der Test gruen, wenn man
    # nah.sort() entfernt -- dann reichen die gelieferten Plaetze bis 210 km statt 145 km,
    # und 83 der 250 sind andere als die naechstgelegenen (Review-Fund 16.08.2026).
    def abstand(icao):
        a = bestand.plaetze[icao]
        return fse_modul._entfernung_km(KJFK[0], KJFK[1], a["lat"], a["lon"])

    la0, la1, lo0, lo1 = fse_modul._rechteck(*KJFK, 150)
    im_fenster = {i for i, a in bestand.plaetze.items()
                  if la0 <= a["lat"] <= la1 and lo0 <= a["lon"] <= lo1}
    verworfen = im_fenster - set(treffer)
    assert verworfen
    assert max(map(abstand, treffer)) <= min(map(abstand, verworfen)), (
        "ein verworfener Platz liegt naeher als ein gelieferter -- der Deckel schneidet "
        "nicht nach Entfernung")


def test_zonen_deckel_rechnet_in_punkten_nicht_in_stueck(bestand):
    """Eine Zone kostet ihre Eckenzahl (Mittel 7, max 21), ein Platz genau 1. Bei New York
    150 km stehen 2.719 Punkte an, 900 duerfen raus -- ein Stueckzahl-Deckel wuerde die
    falsche Ebene schonen (die Zonen stellen dort 88 % der Zeichenlast)."""
    treffer, gekappt = fse_modul.zonen_im_umkreis(bestand, *KJFK, 150)
    punkte = sum(len(p) for p in treffer.values())
    assert punkte <= fse_modul.MAX_PUNKTE_ZONEN
    assert punkte > fse_modul.MAX_PUNKTE_ZONEN - 21   # bis dicht an die Grenze gefuellt
    assert gekappt


def _kunstbestand(zonen_spec):
    """FseBestand aus (icao, eckenzahl, lon_versatz) — der Versatz staffelt den Abstand zum
    Bezugspunkt (0, 0) und damit die Reihenfolge im Deckel."""
    b = fse_modul.FseBestand()
    for icao, ecken, versatz in zonen_spec:
        punkte = [[0.0 + i * 0.001, versatz + i * 0.001] for i in range(ecken)]
        b.zonen[icao] = punkte
        breiten = [p[0] for p in punkte]; laengen = [p[1] for p in punkte]
        b.zonen_bbox[icao] = (min(breiten) - 0.5, max(breiten) + 0.5,
                              min(laengen) - 0.5, max(laengen) + 0.5)
    return b


def test_deckelschleife_ueberspringt_statt_abzubrechen():
    """Eine Zone, die nicht mehr ins Budget passt, wird UEBERSPRUNGEN. Braeche die Schleife
    stattdessen ab, risse eine einzelne grosse Zelle mitten in der Liste alles Kleinere
    dahinter mit -- und das Budget bliebe ungenutzt.

    Bewusst synthetisch: Am naechstliegenden Messpunkt in den Echtdaten (KJFK r=150) fuellen
    skip und break identisch 899 von 900 Punkten. Er kann die beiden Semantiken gar nicht
    unterscheiden, und der frueher hier stehende Test war deshalb gruen, egal was der Code
    tat (Review-Fund 16.08.2026)."""
    b = _kunstbestand([("GROSS", 890, 0.0), ("PASSTNICHT", 21, 1.0), ("KLEIN", 5, 2.0)])
    treffer, gekappt = fse_modul.zonen_im_umkreis(b, 0.0, 0.0, 250)

    assert gekappt
    assert "GROSS" in treffer
    assert "PASSTNICHT" not in treffer, "890 + 21 > 900 -- die Zone darf nicht mitkommen"
    assert "KLEIN" in treffer, (
        "die Schleife bricht ab, statt zu ueberspringen: KLEIN haette mit 890 + 5 = 895 "
        "bequem ins Budget gepasst")
    assert sum(len(p) for p in treffer.values()) == 895


def test_ozeanzelle_kommt_mit_egal_wie_gross_sie_ist(bestand):
    """Ueber dem offenen Ozean steht eine einzelne grosse Voronoi-Zelle; sie muss ankommen,
    obwohl ihr Flugplatz Hunderte Kilometer entfernt liegen kann.

    Anmerkung zur Reichweite dieses Tests (Review 16.08.2026): Er faengt die
    RECHTECK-Variante, nicht die Flugplatz-Variante. Letztere ist auf echten Daten gar nicht
    unterscheidbar, weil die umschliessende Zelle per Voronoi-Definition dem naechsten
    Flugplatz gehoert -- s. test_bbox_abstand_misst_vom_punkt."""
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


def test_diagnose_misst_das_zeichnen_und_nicht_das_zuruecklesen():
    """Zweite Fassung dieser Sonde, nach einer Messung aus dem Kniebrett (16.08.2026).

    Die erste las die gezeichneten Pixel per getImageData zurueck und meldete viermal
    `zeichnet: false` -- mit dem Fehler "NotSupportedError (DOM Exception 9)". Das war ein
    FALSCHER Alarm: Coherent GT unterstuetzt allein das Zurueck-LESEN nicht. Leaflets
    Canvas-Renderer liest nie zurueck, er zeichnet ausschliesslich. Die Sonde mass also eine
    Faehigkeit, die das Feature nicht braucht -- derselbe Fehler wie einst bei probeSprites,
    wo der Rahmen statt des Inhalts gemessen wurde.

    Gefordert ist jetzt: Das Zeichnen wird ausgefuehrt und GEMESSEN, und ein fehlgeschlagenes
    Zurueck-Lesen darf das Ergebnis nicht mehr auf `zeichnet: false` ziehen."""
    assert "base.canvas = probeCanvas()" in INDEX
    stelle = INDEX.index("function probeCanvas(")
    rumpf = INDEX[stelle:INDEX.index("\n      }", stelle)]

    assert "getContext" in rumpf
    assert ".arc(" in rumpf and ".stroke(" in rumpf, "die Sonde zeichnet gar nichts"
    assert "performance" in rumpf and "ms" in rumpf, (
        "die Sonde misst keine Dauer -- genau daran haengt, ob die Deckelwerte tragen")

    # Der Rueckleseversuch darf nur noch ein Nebenbefund sein: NACH der Messung, und er darf
    # `zeichnet` nicht mehr beruehren.
    assert "rueckLesbar" in rumpf, "der Rueckleseversuch sollte als eigener Befund bleiben"
    # An der AUFRUFSTELLE verankert, nicht frei gesucht: Der erklaerende Kommentar der Sonde
    # nennt getImageData selbst, und ein freier Vergleich fand prompt ihn statt des Aufrufs.
    # Dritter Fall dieser Art in dieser Datei -- Zeichenkettentests ueber Quelltext muessen
    # sich an Code binden, nie an Prosa.
    assert rumpf.index("zeichnet = true") < rumpf.index("ctx.getImageData("), (
        "getImageData steht vor der Zeichenmessung -- ein nicht unterstuetztes Zuruecklesen "
        "wuerde wieder als 'zeichnet nicht' gemeldet")

    # Gemessen wird die Menge, die eine volle FSE-Ebene ausmacht.
    assert "250" in rumpf, "die Sonde zeichnet nicht die gedeckelte Platzzahl"

def test_unveraenderte_zonen_werden_nicht_kopiert(bestand):
    """21 MB haengen an dieser Zeile. Ein bedingungsloser Neubau in _auf_einen_zweig erzeugt
    23.780 frische Listenstrukturen, waehrend die Rohdaten noch leben -- und den Verschnitt
    gibt der Allokator nicht ans Betriebssystem zurueck. Gemessen (VmRSS nach gc.collect und
    malloc_trim, Python 3.12): 70,7 MB bedingungslos, 49,8 MB mit Wiederverwendung.

    Geprueft wird die IDENTITAET, nicht die Gleichheit: Eine Kopie waere gleich und der Test
    bliebe gruen, waehrend der Speicher wieder da waere."""
    roh = json.loads((WELT / "fse_zones_world.json").read_text(encoding="utf-8"))
    unveraendert = [k for k in bestand.zonen if bestand.zonen[k] == roh[k]]
    assert len(unveraendert) == 23778, "die Zweig-Korrektur hat mehr als die zwei Polzellen angefasst"
    for icao in ("EDWG", "KJFK", "NFNA"):
        assert fse_modul._auf_einen_zweig(roh[icao]) is roh[icao], (
            f"{icao} wurde neu gebaut, obwohl sich nichts aendert -- das kostet 21 MB")


def test_zweig_korrektur_greift_bei_gemischten_zweigen():
    """Auf dem heutigen Bestand aendert _auf_einen_zweig nur die zwei Polzellen, die danach
    ohnehin verworfen werden -- sie ist also reine Vorsorge fuer kuenftige Daten. Genau
    deshalb braucht sie einen eigenen Test: Gegen den echten Datensatz bliebe auch eine
    Identitaetsfunktion gruen (Review-Fund 16.08.2026)."""
    # Ein Polygon knapp beiderseits der Datumsgrenze, in verschiedenen Zweigen notiert.
    gemischt = [[10.0, 179.0], [11.0, -179.0], [12.0, 179.5]]
    assert max(p[1] for p in gemischt) - min(p[1] for p in gemischt) == 358.5
    assert _polzelle_roh(gemischt), "ungezogen sieht das Polygon wie eine Polzelle aus"

    gezogen = fse_modul._auf_einen_zweig(gemischt)
    assert gezogen is not gemischt
    laengen = [p[1] for p in gezogen]
    assert laengen[1] == 181.0, "-179 gehoert auf den Zweig von 179, also nach +181"
    assert max(laengen) - min(laengen) <= 2.0, f"nicht auf einen Zweig gezogen: {laengen}"
    assert [p[0] for p in gezogen] == [10.0, 11.0, 12.0], "Breiten wurden veraendert"
    assert not fse_modul._polzelle(gezogen), "gezogen darf es keine Polzelle mehr sein"


def _polzelle_roh(punkte):
    laengen = [p[1] for p in punkte]
    return max(laengen) - min(laengen) > 180.0


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_frontend_zieht_die_laenge_auf_die_datumsgrenze():
    """Review-Fund: Leaflet laesst die Laenge beim Ziehen ueber die Datumsgrenze ueber den Rand
    hinauslaufen (-185 westlich von Fidschi, 368 nach einer Weltumrundung). Der Server
    validiert lon in [-180, 180] und antwortet mit 422 -- die Ebene blieb still leer, und weil
    die Streckensperre schon fortgeschrieben war, auch dauerhaft."""
    treiber = """
const map = new FakeMap(10);
_fsePlaetzeGruppe.addTo(map);

map._mitte = _ll(-17.75, -185.0);      // westlich der Grenze, ausserhalb des gueltigen Bereichs
_fseAbrufen(map);
const url = global._fetchLog[global._fetchLog.length - 1];
const lon = parseFloat(new URL('http://x' + url.slice(url.indexOf('?'))).searchParams.get('lon'));
assert.ok(lon >= -180 && lon <= 180, 'lon=' + lon + ' liegt ausserhalb [-180, 180] -- der Server antwortet 422');
assert.ok(Math.abs(lon - 175.0) < 0.01, 'erwartet 175 (= -185 + 360), war ' + lon);

// Und nach einer Weltumrundung nach Osten.
_fseLetzteMitte = null;
map._mitte = _ll(53.0, 368.0);
_fseAbrufen(map);
const url2 = global._fetchLog[global._fetchLog.length - 1];
const lon2 = parseFloat(new URL('http://x' + url2.slice(url2.indexOf('?'))).searchParams.get('lon'));
assert.ok(Math.abs(lon2 - 8.0) < 0.01, 'erwartet 8 (= 368 - 360), war ' + lon2);

console.log('OK');
"""
    _node_lauf(treiber)


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_frontend_versucht_es_nach_einem_fehlschlag_wieder():
    """Review-Fund: Die Streckenmarke wird VOR dem fetch fortgeschrieben. Schlaegt er fehl
    (Netz weg, oder 401 nach Cookie-Ablauf), blockte die Sperre jeden Folgeversuch, bis
    0,2 x r geflogen sind -- bei 250 km Radius gut zehn Minuten leere Ebene. Der Verkehr
    uebersteht das, weil sein 15-Sekunden-Takt es nachholt; diese Ebene hat keinen."""
    treiber = """
const map = new FakeMap(10);
_fsePlaetzeGruppe.addTo(map);

global._fetchOk = false;               // Server antwortet 422/401
_fseAbrufen(map);
setImmediate(() => {
  try {
    assert.strictEqual(global._fetchLog.length, 1);
    assert.strictEqual(_fsePlaetzeTabelle.size, 0, 'trotz Fehlschlag wurde gezeichnet');

    // Ohne Bewegung erneut anstossen -- muss es wieder versuchen.
    global._fetchOk = true;
    _fseAbrufen(map);
    setImmediate(() => {
      try {
        assert.strictEqual(global._fetchLog.length, 2,
          'nach dem Fehlschlag blockt die Streckensperre den zweiten Versuch');
        assert.strictEqual(_fsePlaetzeTabelle.size, 1, 'der zweite Versuch hat nichts gezeichnet');
        console.log('OK');
      } catch (e) { console.error(e.stack || String(e)); process.exitCode = 1; }
    });
  } catch (err) { console.error(err && err.stack ? err.stack : String(err)); process.exitCode = 1; }
});
"""
    _node_lauf(treiber)


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_frontend_verwirft_ueberholte_antworten():
    """Review-Fund: Jede Antwort gilt als vollstaendige Wahrheit fuer den Ausschnitt. Kommen
    zwei Abrufe in umgekehrter Reihenfolge an, entfernt die aeltere die gerade gezeichneten
    Objekte wieder und zeichnet den alten Ausschnitt -- und weil danach erst wieder Bewegung
    noetig ist, bleibt der falsche Stand stehen."""
    treiber = """
const map = new FakeMap(10);
_fsePlaetzeGruppe.addTo(map);

// Erster Abruf: Antwort wird lange zurueckgehalten.
global._antwortPlaetze = { ALT: { lat: 53, lon: 8, name: 'Alt', msfs: ['ALT'] } };
global._fetchVerzoegerung = 8;
_fseAbrufen(map);

// Zweiter Abruf, weit genug entfernt, Antwort kommt sofort.
global._antwortPlaetze = { NEU: { lat: 53.3, lon: 8, name: 'Neu', msfs: ['NEU'] } };
global._fetchVerzoegerung = 0;
map._mitte = _ll(53.3, 8.0);
_fseAbrufen(map);

// Lange genug warten, dass auch die zurueckgehaltene erste Antwort durch ist.
let n = 20;
const warten = () => (--n > 0 ? setImmediate(warten) : pruefen());
function pruefen() {
  try {
    assert.strictEqual(global._fetchLog.length, 2, 'es liefen nicht zwei Abrufe');
    assert.ok(_fsePlaetzeTabelle.has('NEU'), 'der neue Stand fehlt');
    assert.ok(!_fsePlaetzeTabelle.has('ALT'),
      'die ueberholte Antwort wurde angewandt -- die Karte zeigt den alten Ausschnitt');
    console.log('OK');
  } catch (e) { console.error(e.stack || String(e)); process.exitCode = 1; }
}
setImmediate(warten);
"""
    _node_lauf(treiber)


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_frontend_haengt_wirklich_an_moveend_und_zoomend():
    """Review-Fund: Alle uebrigen Node-Treiber rufen _fseAbrufen direkt auf. Damit war die
    EINE Zeile, die das Nachladen im Flug ueberhaupt ausloest, ungetestet -- man haette sie
    entfernen koennen und die Suite waere gruen geblieben, waehrend das Kernfeature tot ist.
    Dieser Treiber geht deshalb ausschliesslich ueber die Kartenereignisse."""
    treiber = """
localStorage.setItem(_FSE_PLAETZE_PREF_KEY, '1');
const map = new FakeMap(10);
_addPreferredFseLayer(map);

setImmediate(() => {
  try {
    const nachStart = global._fetchLog.length;
    assert.ok(nachStart >= 1, 'schon der Startabruf blieb aus');

    // Weit genug ziehen -- NUR ueber das Ereignis, nicht ueber einen Direktaufruf.
    map.zieheNach(53.3, 8.0);
    assert.ok(global._fetchLog.length > nachStart,
      'moveend loest keinen Abruf aus -- die Ebene laedt im Flug nie nach');

    const nachZug = global._fetchLog.length;
    map.setzeZoom(11);
    assert.ok(global._fetchLog.length > nachZug, 'zoomend loest keinen Abruf aus');

    console.log('OK');
  } catch (err) { console.error(err && err.stack ? err.stack : String(err)); process.exitCode = 1; }
});
"""
    _node_lauf(treiber)


def test_bbox_abstand_misst_vom_punkt():
    """Direkttest der Sortier-Funktion, weil die Echtdaten sie nicht pruefen koennen.

    Gegen das Ausschnitts-RECHTECK haette jede schneidende Zone Abstand 0 (bei New York
    389 Stueck) und der Deckel entschiede alphabetisch. Vom Punkt aus hat nur die
    umschliessende 0."""
    cos0 = 1.0
    umschliessend = (-1.0, 1.0, -1.0, 1.0)
    daneben = (-1.0, 1.0, 2.0, 3.0)
    assert fse_modul._bbox_abstand_km(umschliessend, 0.0, 0.0, cos0) == 0.0
    assert fse_modul._bbox_abstand_km(daneben, 0.0, 0.0, cos0) > 200
    # Eine riesige Bbox, deren Mitte weit weg liegt, umschliesst den Punkt trotzdem -> 0.
    riesig = (-60.0, 60.0, -170.0, 5.0)
    assert fse_modul._bbox_abstand_km(riesig, 0.0, 0.0, cos0) == 0.0


def test_grosse_nachbarzelle_ueberlebt_den_deckel():
    """Der eigentliche Grund fuer den Bbox-Abstand — und der Fall, den der echte Datensatz
    nicht hergibt (Review-Fund 16.08.2026): Eine grosse NACHBARzelle, die den Ausschnitt
    schneidet, deren Flugplatz aber weit ausserhalb liegt, muss vor einer kleinen ferneren
    Zelle kommen. Nach Flugplatzentfernung sortiert waere es umgekehrt, und die graue Kulisse
    bekaeme genau dort Loecher, wo sie am wenigsten Konkurrenz hat.

    Dass die UMSCHLIESSENDE Zelle nicht herausfaellt, ist dagegen keine Leistung der
    Sortierung: Sie gehoert per Voronoi-Definition dem naechsten Flugplatz und stuende auch
    nach Flugplatzentfernung vorn (an 131 von 131 geprueften Punkten bestaetigt)."""
    b = fse_modul.FseBestand()
    # Kleine Zelle direkt am Bezugspunkt.
    b.zonen["NAH"] = [[0.0, 0.0], [0.1, 0.0], [0.1, 0.1]]
    b.zonen_bbox["NAH"] = (-0.2, 0.2, -0.2, 0.2)
    # Grosse Nachbarzelle: schneidet den Ausschnitt knapp, reicht aber bis weit nach Osten.
    b.zonen["NACHBAR"] = [[0.0, 1.0], [1.0, 20.0], [-1.0, 20.0]]
    b.zonen_bbox["NACHBAR"] = (-1.0, 1.0, 0.5, 20.0)
    # Kleine Zelle, weiter weg als der Rand der Nachbarzelle, aber naeher als deren Flugplatz.
    b.zonen["FERN"] = [[0.0, 1.6], [0.1, 1.6], [0.1, 1.7]]
    b.zonen_bbox["FERN"] = (-0.1, 0.1, 1.55, 1.75)

    reihenfolge = sorted(
        b.zonen_bbox,
        key=lambda i: fse_modul._bbox_abstand_km(b.zonen_bbox[i], 0.0, 0.0, 1.0),
    )
    assert reihenfolge == ["NAH", "NACHBAR", "FERN"], (
        f"Reihenfolge {reihenfolge} -- die grosse Nachbarzelle muss vor die kleine fernere, "
        "sonst reisst die Kulisse auf")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_label_logik_laeuft_einmal_je_nachladen_nicht_je_marker():
    """Nutzer-Fund am laufenden Bild (16.08.2026): Auf Zoom 6 ruckelte das Schieben, obwohl der
    Server in 41 ms antwortet. Ursache war die Label-Wache: Sie hing an 'layeradd', und der
    Abgleich haengt die Marker EINZELN ein -- also lief die Logik bei jedem eintreffenden
    Marker ueber die ganze, dabei wachsende Gruppe. Gemessen: 31.375 Layer-Besuche fuer 250
    Marker, quadratisch.

    Zwei Verbesserungen, hier getrennt geprueft:
      1. OBERHALB der Label-Schwelle laeuft die Logik einmal je Nachladen statt je Marker.
         Bei Zoom 6 waere das nicht messbar -- dort greift schon (2).
      2. UNTERHALB der Schwelle laeuft sie gar nicht, solange nichts gebunden ist. Auf Zoom 6
         ist jeder Durchlauf ohnehin umsonst, dort erscheint keine einzige Beschriftung.
    """
    start = INDEX.index("function _labelsImSichtbereich(")
    ende_start = INDEX.index("function _fseAttributionAus(")
    quelltext = INDEX[start:INDEX.index("\n}", ende_start) + len("\n}")]

    treiber = """
const plaetze = {};
for (let i = 0; i < 250; i++) plaetze['P' + i] = { lat: 53 + i * 0.001, lon: 8, name: 'x', msfs: [] };

// (1) Oberhalb der Schwelle: der Aufwand muss LINEAR sein.
const map = new FakeMap(12);
_fsePlaetzeGruppe.addTo(map);
_fsePlaetzeZoomWache(map);
global._antwortPlaetze = plaetze;
global._besuche = 0;
_fseAbrufen(map);

setImmediate(() => {
  try {
    assert.strictEqual(_fsePlaetzeTabelle.size, 250, 'nicht alle Marker angekommen');
    assert.ok(global._besuche <= 500,
      global._besuche + ' Layer-Besuche fuer 250 Marker -- die Label-Logik laeuft wieder je '
      + 'Marker statt je Nachladen (quadratisch waeren 31.375)');
    const beispiel = _fsePlaetzeTabelle.get('P0');
    assert.ok(beispiel.getTooltip(),
      'oberhalb der Schwelle fehlt die Beschriftung -- der Aufruf nach dem Abgleich fehlt');

    // (2) Unterhalb der Schwelle: gar kein Durchlauf, sobald nichts gebunden ist.
    map._zoom = 6;
    _fsePlaetzeLabelsAnpassen();            // loest die vorhandenen Beschriftungen
    global._besuche = 0;
    _fsePlaetzeLabelsAnpassen();            // jetzt ist nichts mehr gebunden
    assert.strictEqual(global._besuche, 0,
      'unterhalb der Label-Schwelle laeuft die Schleife trotzdem ueber alle Marker');

    console.log('OK');
  } catch (err) { console.error(err && err.stack ? err.stack : String(err)); process.exitCode = 1; }
});
"""
    _node_lauf(treiber, quelltext)


def _kontrast(vordergrund, hintergrund):
    """Kontrastverhaeltnis nach WCAG. 4,5:1 ist die uebliche Lesbarkeitsschwelle."""
    def kanal(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    def leuchtdichte(c):
        r, g, b = (kanal(x) for x in c)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    a, b = leuchtdichte(vordergrund), leuchtdichte(hintergrund)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# CARTO dark_all und light_all -- die beiden Basiskarten aus TILE_DARK_URL / TILE_LIGHT_URL.
KARTE_DUNKEL = (0x0E, 0x11, 0x16)
KARTE_HELL = (0xF8, 0xF9, 0xFA)


def test_platz_beschriftung_ist_auf_heller_UND_dunkler_karte_lesbar():
    """Nutzer-Fund am laufenden Bild (16.08.2026, Screenshot aus Florida): Die ICAO-Codes waren
    auf der hellen CARTO-Karte nicht zu entziffern. Sie fehlten nicht -- das Plaettchen war
    halbdurchsichtiges Fast-Schwarz (Alpha 0,5), ueber hellem Grund also ein grauer Schleier,
    und der blaugraue Text stand Grau auf Grau. Gerechneter Kontrast damals: 1,3:1.

    Ein halbdurchsichtiges Plaettchen uebernimmt die Farbe der Karte darunter. Es muss deckend
    genug sein, um seinen Hintergrund selbst zu tragen -- so macht es das Hoehenlabel der
    Platzrunden seit jeher (rgba(255,255,255,0.92))."""
    start = INDEX.index(".fse-platz-label {")
    regel = INDEX[start:INDEX.index("}", start)]
    # An `background:` verankert, nicht frei gesucht: Der erklaerende Kommentar in der Regel
    # nennt selbst eine rgba-Farbe (die des Platzrunden-Labels), und ein freier Regex las
    # prompt die statt der Deklaration -- der Test mass damit etwas, das gar nicht gilt.
    m = re.search(r"background:\s*rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", regel)
    assert m, "keine rgba-Hintergrundangabe in .fse-platz-label"
    grund = (int(m[1]), int(m[2]), int(m[3]))
    alpha = float(m[4])

    farbe = re.search(r"--text-label:\s*#([0-9a-fA-F]{6})", INDEX)
    assert farbe, "--text-label nicht gefunden"
    text = tuple(int(farbe[1][i:i + 2], 16) for i in (0, 2, 4))

    for name, karte in (("dunklen", KARTE_DUNKEL), ("hellen", KARTE_HELL)):
        plaettchen = tuple(round(g * alpha + k * (1 - alpha)) for g, k in zip(grund, karte))
        k = _kontrast(text, plaettchen)
        assert k >= 4.5, (
            f"Auf der {name} Karte hat die Platz-Beschriftung nur Kontrast {k:.1f}:1 "
            f"(das Plaettchen wird #{plaettchen[0]:02x}{plaettchen[1]:02x}{plaettchen[2]:02x})")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_letzter_abruf_wird_fuer_die_diagnose_festgehalten():
    """Nutzer-Fund 16.08.2026: Im EFB-Panel sass der FSE-Schwarm rund 390 km neben der
    Kartenmitte, auf dem Desktop im selben Stand exakt mittig. Aus einem Bildschirmfoto ist
    nicht zu entscheiden, welche von zwei Ursachen vorliegt -- eine Anfrage mit falscher Mitte
    oder eine alte Antwort, die stehen blieb. Beides sieht auf der Karte identisch aus.

    Deshalb haelt _fseAbrufen fest, WOMIT der letzte Abruf lief. Zusammen mit der Kartenmitte
    im selben Diagnosesatz beantwortet die Differenz die Frage in einer Zeile."""
    treiber = """
const map = new FakeMap(10);
_fsePlaetzeGruppe.addTo(map);
map._mitte = _ll(48.1372, 11.5756);        // Muenchen
_fseAbrufen(map);

setImmediate(() => {
  try {
    assert.ok(_fseLetzteAnfrage, 'kein Abruf aufgezeichnet');
    assert.ok(Math.abs(_fseLetzteAnfrage.lat - 48.1372) < 0.001,
      'aufgezeichnete Breite passt nicht zur Kartenmitte: ' + _fseLetzteAnfrage.lat);
    assert.ok(Math.abs(_fseLetzteAnfrage.lon - 11.5756) < 0.001,
      'aufgezeichnete Laenge passt nicht zur Kartenmitte: ' + _fseLetzteAnfrage.lon);
    assert.strictEqual(_fseLetzteAnfrage.zoom, 10);
    assert.ok(_fseLetzteAnfrage.r > 0, 'kein Radius aufgezeichnet');
    assert.strictEqual(_fseLetzteAnfrage.plaetze, _fsePlaetzeTabelle.size,
      'die Trefferzahl im Bericht passt nicht zu dem, was auf der Karte liegt');

    // Und der springende Punkt: Bewegt sich die Karte OHNE Abruf, muss der Bericht die ALTE
    // Mitte zeigen -- daran erkennt man den stehengebliebenen Zustand.
    map._mitte = _ll(50.0, 8.0);
    assert.ok(Math.abs(_fseLetzteAnfrage.lat - 48.1372) < 0.001,
      'der Bericht folgt der Karte, statt den letzten Abruf zu zeigen -- dann kann er die '
      + 'beiden Ursachen nicht mehr trennen');
    console.log('OK');
  } catch (err) { console.error(err && err.stack ? err.stack : String(err)); process.exitCode = 1; }
});
"""
    _node_lauf(treiber)


def test_groessenaenderung_wird_an_leaflet_gemeldet():
    """Nutzer-Fund 16.08.2026: Beim Abdocken und Maximieren des EFB sass der FSE-Schwarm bis zu
    480 km neben der Kartenmitte -- Kacheln, Flugzeuge und Platzrunden dagegen richtig.

    Ein Versatz, der AUSSCHLIESSLICH eine Renderer-Art trifft, kann nur aus deren Geometrie
    kommen: Die FSE-Ebenen sind die einzigen auf dem geteilten Canvas, und dessen Zeichenflaeche
    liegt auf der Containergroesse vom Zeitpunkt des Einhaengens. Waechst der Container, ohne
    dass Leaflet es erfaehrt, bleibt sie liegen -- und alles darauf erscheint nach oben links
    versetzt.

    invalidateSize() hing bis dahin nur am Vollbild-Knopf und am Tab-Wechsel. Ein abgedocktes
    Fenster, das jemand maximiert, ist beides nicht."""
    assert "function _groessenWache(" in INDEX
    stelle = INDEX.index("function _groessenWache(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "ResizeObserver" in rumpf
    assert "invalidateSize" in rumpf
    # Eine verdeckte Karte meldet 0x0 -- darauf invalidateSize() zu rufen setzt sie auf null.
    assert "clientWidth === 0" in rumpf, "kein Schutz gegen den verdeckten Tab (0x0)"
    # Beim Maximieren feuert der Beobachter mehrfach je Bild.
    assert "requestAnimationFrame" in rumpf, "ungebuendelt -- feuert mehrfach je Bild"
    # Und sie muss tatsaechlich an der Live-Karte haengen, nicht nur definiert sein.
    assert "_groessenWache(liveMap" in INDEX
