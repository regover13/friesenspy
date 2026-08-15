"""Platzrunden-Datensatz und -Ebene (v12.8.0)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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


def test_popup_verzweigt_auf_das_flag_nicht_auf_das_label():
    """hoehe_label lautet bei den 147 Platzhaltern 'keine Angabe (Annahme 1000 ft)'. Wer das
    Feld rendert, zeigt die erfundene Zahl doch an -- nur in Klammern. Deshalb muss das Popup
    auf hoehe_geschaetzt verzweigen und hoehe_label gar nicht erst anfassen."""
    stelle = INDEX.index("function _platzrundenPopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "hoehe_geschaetzt" in rumpf
    assert "hoehe_label" not in rumpf


def test_popup_zeigt_hoehe_auch_bei_strecken_mit_echter_hoehe():
    """Review-Fund (Minor): Der strecke-Zweig stand VOR dem Hoehenzweig und hat die Hoehe damit
    fuer alle vier An-/Abflugstrecken unterschlagen -- dabei tragen genau diese vier eine echte,
    geprueften Hoehe (EDQA 1700 ft, EDWP 1000 ft). Beide Aussagen muessen jetzt unabhaengig
    voneinander ausgeloest werden koennen, kein else-if, das den einen Zweig gegen den anderen
    ausschliesst."""
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    strecken = [f["properties"] for f in gj["features"] if f["properties"].get("typ") == "strecke"]
    assert len(strecken) == 4
    assert all(not p["hoehe_geschaetzt"] and p["hoehe_ft"] is not None for p in strecken), (
        "Testannahme veraltet: nicht mehr alle Strecken haben eine geprüfte Höhe -- Fix prüfen"
    )

    stelle = INDEX.index("function _platzrundenPopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "if (p.typ === 'strecke') zeilen.push" in rumpf, (
        "Die Strecken-Kennzeichnung darf keinen Hoehenzweig mehr ausschliessen (kein else-if)"
    )
    assert "hoeheEcht" in rumpf


def test_pr_info_klasse_existiert_im_stylesheet():
    """Review-Fund (Minor): <span class="pr-info"> verwies auf eine Klasse, die es im
    Stylesheet nicht gab."""
    assert ".pr-info {" in INDEX


def test_popup_schreibt_msl_auch_bei_unsicherem_bezug():
    """127 Eintraege tragen 'MSL?'. Gegen die Platzhoehe gerechnet liegen sie im selben Band
    wie die 138 expliziten MSL-Angaben (Median 895 vs. 864 ft ueber Grund) -- derselbe Bezug.
    Ein Fragezeichen im Cockpit hilft niemandem."""
    stelle = INDEX.index("function _platzrundenPopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "MSL?" not in rumpf


def test_zoom_wache_haengt_am_zoomend():
    """Weit herausgezoomt sind 412 Polygone kein Bild mehr, sondern Grauschleier. Ausblenden
    heisst hier: die Linien verschwinden, der Haken bleibt gesetzt -- sonst muesste der Nutzer
    die Ebene nach jedem Herauszoomen neu einschalten."""
    stelle = INDEX.index("function _platzrundenZoomWache(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "zoomend" in rumpf
    assert "_PLATZRUNDEN_MIN_ZOOM" in rumpf


_NODE = shutil.which("node") or shutil.which("nodejs")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_zoom_wache_greift_wenn_die_daten_nach_dem_einschalten_eintreffen():
    """Review-Fund (Important): _platzrundenGruppe war ein L.layerGroup() -- dessen addLayer()
    feuert in echtem Leaflet KEIN 'layeradd'-Ereignis, nur L.FeatureGroup tut das. Die Zoom-Wache
    haengt sich aber genau an dieses Ereignis, um frisch geladene Polygone sofort auf die
    aktuelle Zoomstufe zu bringen. Der reale Fehlerfall: Nutzer zoomt auf Stufe 7 heraus und
    hakt "Platzrunden" an -> die Daten laden nach -> alle 412 Polygone erscheinen mit voller
    Deckkraft, weil der Listener nie lief. Erst die naechste Zoomaenderung korrigiert es.

    Der vorhandene test_zoom_wache_haengt_am_zoomend prueft nur Zeichenketten im Quelltext und
    haette diesen Fehler prinzipiell nicht fangen koennen (das Review hat das zu Recht
    angemerkt) -- deshalb hier der extrahierte Quelltext wirklich in Node ausgefuehrt, mit einem
    Leaflet-Fake, der 'layeradd' bewusst nur auf FeatureGroup-artigen Objekten feuert (wie das
    echte Leaflet)."""
    # Der Viewport-Helfer steht VOR dem Platzrunden-Block und wird von der Wache gebraucht.
    start = INDEX.index("function _labelsImSichtbereich(")
    ende_start = INDEX.index("function _platzrundenZoomWache(")
    ende = INDEX.index("\n}", ende_start) + len("\n}")
    quelltext = INDEX[start:ende]

    harness = """
'use strict';
const assert = require('assert');

// Ein GeoJSON mit einem Feature reicht -- es geht nur darum, ob der ECHTE Ladepfad
// (_platzrundenLaden -> L.geoJSON(...).addTo(_platzrundenGruppe)) das 'layeradd'-Ereignis
// ausloest, das die Zoom-Wache braucht.
global.fetch = () => Promise.resolve({
  ok: true,
  json: () => Promise.resolve({ type: 'FeatureCollection', features: [
    { type: 'Feature', properties: { icao: 'EDXX' }, geometry: { type: 'Polygon', coordinates: [[[8,53],[8,54],[9,54],[8,53]]] } }
  ] }),
});

class FakeGroupBase {
  constructor(art) { this.art = art; this._layers = []; this._handlers = {}; }
  addLayer(l) { this._layers.push(l); return this; }
  addTo(ziel) { return this; }
  eachLayer(fn) { this._layers.slice().forEach(fn); return this; }
  getLayers() { return this._layers.slice(); }
  clearLayers() { this._layers = []; return this; }
  on(evt, fn) { (this._handlers[evt] = this._handlers[evt] || []).push(fn); return this; }
}
// addLayer() feuert hier bewusst NICHTS -- wie das echte L.LayerGroup. Wuerde die Produktion
// wieder auf L.layerGroup() zurueckfallen, bliebe der 'layeradd'-Handler unten stumm und der
// Test schlaegt fehl.
class FakeLayerGroup extends FakeGroupBase {}
// NUR FeatureGroup feuert 'layeradd' beim addLayer() -- wie im echten Leaflet.
class FakeFeatureGroup extends FakeGroupBase {
  addLayer(l) {
    super.addLayer(l);
    (this._handlers['layeradd'] || []).forEach(fn => fn({ layer: l }));
    return this;
  }
}
global.L = {
  layerGroup: () => new FakeLayerGroup('layerGroup'),
  featureGroup: () => new FakeFeatureGroup('featureGroup'),
  geoJSON: (gj, opts) => {
    // Ein Feature-Layer je Feature -- die Zoom-Wache iteriert seit der Fanglinie verschachtelt
    // (Gruppe -> GeoJSON-Layer -> Feature-Layer) und unterscheidet die Lagen an der CSS-Klasse.
    const stil = typeof opts.style === 'function' ? opts.style() : (opts.style || {});
    const feature = {
      options: { className: stil.className },
      _style: null,
      _tooltip: null,
      _tooltipOffen: false,
      setStyle(s) { this._style = s; },
      bindTooltip(txt, o) { this._tooltip = { txt, o }; return this; },
      getTooltip() { return this._tooltip; },
      openTooltip() { this._tooltipOffen = true; return this; },
      closeTooltip() { this._tooltipOffen = false; return this; },
      getLatLngs() { return [[{lat:53,lng:8},{lat:54,lng:8},{lat:54,lng:9}]]; },
      on() { return this; },
      bindPopup() { return this; },
    };
    if (opts.onEachFeature) opts.onEachFeature(gj.features[0], feature);
    return {
      _style: null,
      _layers: [feature],
      setStyle(s) { this._style = s; },
      eachLayer(fn) { this._layers.slice().forEach(fn); return this; },
      // Die Zoom-Wache nimmt die Pfade unterhalb der Schwelle aus der Karte und haengt sie
      // spaeter wieder ein -- dafuer braucht der Fake dieselben drei Methoden wie L.GeoJSON.
      getLayers() { return this._layers.slice(); },
      clearLayers() { this._layers = []; return this; },
      addLayer(l) { this._layers.push(l); return this; },
      addTo(gruppe) { gruppe.addLayer(this); return this; },
    };
  },
  latLng: (lat, lng) => ({ lat, lng }),
};

class FakeMap {
  constructor(zoom) { this._zoom = zoom; this._handlers = {}; }
  getZoom() { return this._zoom; }
  getBounds() { return { pad: () => ({ contains: () => true }) }; }
  on(evt, fn) { (this._handlers[evt] = this._handlers[evt] || []).push(fn); return this; }
}
"""

    treiber = """
// Zoomstufe UNTERHALB der Schwelle (_PLATZRUNDEN_MIN_ZOOM = 9) -- genau der Fehlerfall aus dem
// Review: Nutzer ist herausgezoomt, wenn die Ebene eingeschaltet und nachgeladen wird.
const map = new FakeMap(7);

// Reihenfolge wie im echten initLiveMap(): erst die Zoom-Wache registrieren (Karte existiert
// bereits beim App-Start), die Daten kommen erst spaeter durch das Einschalten der Checkbox.
_platzrundenZoomWache(map);

_platzrundenLaden().then(() => {
  setImmediate(() => {
    try {
      // Unterhalb der Schwelle nimmt die Wache die Pfade AUS der Karte, statt sie nur auf
      // Deckkraft 0 zu setzen -- ein unsichtbarer Pfad kostet Leaflet genauso viel wie ein
      // sichtbarer, und bei 824 Pfaden hing die Karte daran (Nutzer-Fund am laufenden Bild).
      assert.strictEqual(_platzrundenGruppe._layers.length, 2, 'erwartet werden Fanglinie und sichtbare Linie -- fetch-Mock kaputt?');
      const leer = _platzrundenGruppe._layers.every(g => g.getLayers().length === 0);
      assert.ok(leer, "die Pfade haetten unterhalb der Zoom-Schwelle aus der Karte genommen sein muessen (der urspruengliche Bug: sie blieben drin und wurden bei jeder Bewegung neu gerechnet)");
      // Und kein Hoehenschild darf gebunden sein.
      const geparkt = [];
      _platzrundenGruppe._layers.forEach(g => (g._pfadeAus || []).forEach(l => geparkt.push(l)));
      assert.ok(geparkt.length >= 1, 'die entnommenen Pfade muessen gemerkt sein, sonst kaemen sie nie zurueck');
      assert.ok(geparkt.every(l => !l.getTooltip()), 'unterhalb der Schwelle darf kein Hoehenschild gebunden sein');
      console.log('OK');
    } catch (err) {
      console.error(err && err.stack ? err.stack : String(err));
      process.exitCode = 1;
    }
  });
}).catch(err => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exitCode = 1;
});
"""

    skript = harness + "\n" + quelltext + "\n" + treiber
    ergebnis = subprocess.run(
        [_NODE, "-e", skript], capture_output=True, text=True, timeout=10
    )
    assert ergebnis.returncode == 0 and "OK" in ergebnis.stdout, (
        f"Node-Lauf fehlgeschlagen -- stdout={ergebnis.stdout!r} stderr={ergebnis.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Sichtbarkeit und Bedienbarkeit (v13.0.2)
# ---------------------------------------------------------------------------

def test_klickflaeche_ist_breiter_als_die_linie():
    """Bei einem Pfad ohne Fuellung ist ALLEIN der Strich die Trefferflaeche. Mit 1,5 px traf
    der Nutzer die Platzrunde am Desktop kaum und auf dem Tablet gar nicht -- deshalb liegt
    unter jeder sichtbaren Linie eine breite, praktisch unsichtbare Fanglinie."""
    fang = int(re.search(r"_PLATZRUNDEN_FANG_STAERKE = (\d+)", INDEX).group(1))
    linie = int(re.search(r"_PLATZRUNDEN_STAERKE = (\d+)", INDEX).group(1))
    assert fang >= 4 * linie, "die Fanglinie muss deutlich breiter sein als die sichtbare"


def test_fanglinie_ist_nicht_voellig_durchsichtig():
    """Ein SVG-Pfad mit opacity 0 wird von pointer-events nicht getroffen -- die Fanglinie
    braucht einen Wert knapp ueber null, sonst faengt sie nichts."""
    wert = float(re.search(r"_PLATZRUNDEN_FANG_OPACITY = ([\d.]+)", INDEX).group(1))
    assert 0 < wert <= 0.05


def test_hoehenschild_nur_bei_echten_hoehen():
    """147 der 412 Eintraege tragen einen Platzhalter statt einer Hoehe. Eine geratene Zahl
    gross auf der Karte waere schlimmer als das Popup, in dem wenigstens 'Hoehe nicht bekannt'
    steht."""
    stelle = INDEX.index("function _platzrundenHoehenLabel(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "hoehe_geschaetzt" in rumpf and "return" in rumpf


def test_hoehenschild_sitzt_auf_dem_gegenanflug():
    """Eine Platzrunde hat ZWEI lange Seiten: den Gegenanflug und die Seite ueber der Piste.
    Nur die laengste zu nehmen trifft mal die eine, mal die andere. Der Gegenanflug ist die
    lange Kante mit dem groessten Abstand zur Mitte -- die Piste liegt im Zentrum.

    Warum das zaehlt: Ein Schild mitten in der Runde, dort wo der Platz liegt, liest sich wie
    die PLATZhoehe statt der Platzrundenhoehe. Genau das hat der Nutzer beanstandet."""
    assert "_gegenanflugMitte(" in INDEX
    stelle = INDEX.index("function _platzrundenHoehenLabel(")
    assert "_gegenanflugMitte(" in INDEX[stelle:INDEX.index("\n}", stelle)]


def test_schilder_haben_eine_eigene_zoomschwelle():
    """Die Linien ergeben schon frueh ein Bild, 265 Zahlen dagegen waeren eine Wolke."""
    assert INDEX.count("_PLATZRUNDEN_LABEL_MIN_ZOOM =") == 1
    label = int(re.search(r"_PLATZRUNDEN_LABEL_MIN_ZOOM = (\d+)", INDEX).group(1))
    linien = int(re.search(r"_PLATZRUNDEN_MIN_ZOOM = (\d+)", INDEX).group(1))
    assert label > linien


def test_maus_macht_eine_zoomstufe_je_rastung():
    """Leaflets Standard sind 60 px je Stufe; viele Maeuse senden 100-120 px pro Rastung und
    springen deshalb zwei Stufen auf einmal. Vom Nutzer bestaetigt: von 12 landete das Rad
    direkt auf 14 -- uebersprungen wurde ausgerechnet die 13, auf der man die Platzrunde
    anschaut."""
    assert INDEX.count("_RAD_PX_JE_ZOOMSTUFE =") == 1
    px = int(re.search(r"_RAD_PX_JE_ZOOMSTUFE = (\d+)", INDEX).group(1))
    assert px >= 100
    # alle drei Karten, nicht nur die Live-Karte
    assert INDEX.count("wheelPxPerZoomLevel: _RAD_PX_JE_ZOOMSTUFE") == 3


def test_geojson_wird_als_geojson_ausgeliefert():
    """Ohne diese Registrierung liefert StaticFiles die Datei als application/octet-stream --
    und die gzip_types-Regel in nginx/friesenspy.devprops.de.conf listet application/geo+json.
    Der Typ kaeme also nie an, und ausgerechnet die groesste der drei Datendateien (209 KB)
    ginge unkomprimiert raus."""
    import mimetypes
    import app.main  # noqa: F401  -- der Import registriert den Typ
    assert mimetypes.guess_type("x.geojson")[0] == "application/geo+json"
