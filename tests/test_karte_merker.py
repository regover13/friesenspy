"""Karten-Merker im Cookie statt in localStorage (v13.6.0).

Hintergrund: Im MSFS-Kniebrett ueberlebt localStorage einen Sim-Neustart nicht verlaesslich.
Die Panel-Aufzeichnung ueber 40 Starts zeigt nicht nur verlorene, sondern auch VERALTETE Werte
(16.08.2026, 16:28 Uhr: `Light` von 14:59, obwohl um 15:21 `Satellit` gewaehlt war). Einen
alten Wert kann der Anwendungscode nicht erzeugen -- nur die Speicherschicht selbst.

Die Tests hier pruefen deshalb genau zwei Dinge: dass das Cookie die fuehrende Quelle ist
(sonst gewinnt der veraltete localStorage-Wert weiter), und dass ein beschaedigtes Cookie die
Karte nicht unbrauchbar macht.
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

_NODE = shutil.which("node")


def _merker_quelltext():
    """Vom Startausschnitt bis hinter _ausschnittBeobachten -- Speicher und Ausschnitt.

    Die Scheibe MUSS bei `const _KARTE_MITTE` beginnen: _ausschnittStart faellt darauf
    zurueck, und ohne die Konstante waere jeder Vorgabe-Test ein ReferenceError statt einer
    Aussage.
    """
    start = INDEX.index("const _KARTE_MITTE")
    ende = INDEX.index("function _ausschnittBeobachten(")
    return INDEX[start:INDEX.index("\n}", ende) + len("\n}")]


# Ein Cookie-Glas mit Browser-Verhalten: Schreiben legt EINEN Schluessel ab (die Attribute
# dahinter gehoeren nicht zum Wert), Lesen gibt alle als "k=v; k2=v2" zurueck. Ein naives
# `cookie: ''` haette hier genuegt, weil nur ein Cookie im Spiel ist -- dann pruefte der Test
# aber die Attrappe statt der Trennlogik in _prefCookieLesen.
_HARNESS = """
'use strict';
const assert = require('assert');

global._jar = {};
global.document = {
  get cookie() {
    return Object.keys(global._jar).map((k) => k + '=' + global._jar[k]).join('; ');
  },
  set cookie(zeile) {
    const erstes = String(zeile).split('; ')[0];
    const i = erstes.indexOf('=');
    global._jar[erstes.slice(0, i)] = erstes.slice(i + 1);
  },
};

global._lsSpeicher = {};
global.localStorage = {
  getItem: (k) => (k in global._lsSpeicher ? global._lsSpeicher[k] : null),
  setItem: (k, v) => { global._lsSpeicher[k] = String(v); },
  removeItem: (k) => { delete global._lsSpeicher[k]; },
};

// Werden nur im moveend-Handler gelesen.
global._naviSelbstBewegt = false;
global._naviZoomt = false;

function FakeMap(mitte, zoom) {
  this._mitte = mitte; this._zoom = zoom; this._h = {};
}
FakeMap.prototype.on = function (namen, fn) {
  String(namen).split(' ').forEach((n) => { (this._h[n] = this._h[n] || []).push(fn); });
};
FakeMap.prototype.feuern = function (n) { (this._h[n] || []).forEach((fn) => fn()); };
FakeMap.prototype.getCenter = function () {
  const m = this._mitte;
  return { lat: m[0], lng: m[1], wrap: function () { return this; } };
};
FakeMap.prototype.getZoom = function () { return this._zoom; };
global.FakeMap = FakeMap;
"""


def _node_lauf(treiber):
    if _NODE is None:
        pytest.skip("Node.js nicht verfuegbar")
    skript = _HARNESS + "\n" + _merker_quelltext() + "\n" + treiber
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:
        f.write(skript)
        pfad = f.name
    try:
        erg = subprocess.run([_NODE, pfad], capture_output=True, text=True, timeout=15)
    finally:
        Path(pfad).unlink(missing_ok=True)
    assert erg.returncode == 0 and "OK" in erg.stdout, (
        f"Node-Lauf fehlgeschlagen -- stdout={erg.stdout!r} stderr={erg.stderr!r}"
    )


# --------------------------------------------------------------------------------------
#  Der Speicher
# --------------------------------------------------------------------------------------

@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_geschriebener_merker_liegt_im_cookie_und_kommt_zurueck():
    _node_lauf("""
_prefSchreib('friesenspy_layer', 'topo');
assert.strictEqual(_prefLies('friesenspy_layer'), 'topo');
assert.ok('fs_karte' in global._jar, 'Merker landete nicht im Cookie');
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_cookie_schlaegt_veralteten_localstorage_wert():
    """Der eigentliche Fehler, gegen den diese Umstellung gebaut ist.

    Im Kniebrett lieferte localStorage einen Stand von vor zwei Stunden zurueck. Wuerde
    localStorage weiterhin zuerst gelesen, waere die Umstellung wirkungslos -- deshalb steht
    hier ein WIDERSPRUCH zwischen beiden Quellen, nicht nur ein fehlender Wert.
    """
    _node_lauf("""
_prefSchreib('friesenspy_layer', 'sat');       // aktuell, liegt im Cookie
global._lsSpeicher['friesenspy_layer'] = 'light';  // veralteter Stand, wie im Panel gesehen
_prefSpeicher = null;                          // naechster Seitenaufbau
assert.strictEqual(_prefLies('friesenspy_layer'), 'sat');
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_bisheriger_localstorage_wert_wird_einmalig_uebernommen():
    """Niemand darf beim Update seine Einstellungen verlieren."""
    _node_lauf("""
global._lsSpeicher['friesenspy_trackup'] = '1';   // Stand vor der Umstellung
assert.strictEqual(_prefLies('friesenspy_trackup'), '1');
assert.ok(global._jar.fs_karte.indexOf('friesenspy_trackup') !== -1,
          'Wert wurde gelesen, aber nicht ins Cookie uebernommen');
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_schreiben_fuellt_auch_localstorage():
    """Zweites Standbein: Sind Cookies abgeschaltet, traegt wenigstens localStorage."""
    _node_lauf("""
_prefSchreib('friesenspy_verkehr', '1');
assert.strictEqual(global._lsSpeicher['friesenspy_verkehr'], '1');
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_beschaedigtes_cookie_wirft_nicht():
    _node_lauf("""
global._jar.fs_karte = '%7Bkaputt';   // kein gueltiges JSON
_prefSpeicher = null;
assert.strictEqual(_prefLies('friesenspy_layer'), null);
_prefSchreib('friesenspy_layer', 'dark');
assert.strictEqual(_prefLies('friesenspy_layer'), 'dark');
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_mehrere_merker_teilen_sich_ein_cookie():
    """Neun Schluessel, ein Cookie -- und keiner ueberschreibt den anderen."""
    _node_lauf("""
_prefSchreib('friesenspy_layer', 'topo');
_prefSchreib('friesenspy_aip', '1');
_prefSchreib('friesenspy_movingmap', '1');
_prefSpeicher = null;
assert.strictEqual(_prefLies('friesenspy_layer'), 'topo');
assert.strictEqual(_prefLies('friesenspy_aip'), '1');
assert.strictEqual(_prefLies('friesenspy_movingmap'), '1');
assert.strictEqual(Object.keys(global._jar).length, 1);
console.log('OK');
""")


# --------------------------------------------------------------------------------------
#  Der Ausschnitt
# --------------------------------------------------------------------------------------

@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_ohne_gemerkten_ausschnitt_startet_die_karte_auf_edwg():
    _node_lauf("""
const s = _ausschnittStart();
assert.deepStrictEqual(s.center, _KARTE_MITTE);
assert.strictEqual(s.zoom, _KARTE_ZOOM);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_gemerkter_ausschnitt_wird_wiederhergestellt():
    _node_lauf("""
_prefSchreib('friesenspy_ausschnitt', '48.3538,11.7861,12');
_prefSpeicher = null;
const s = _ausschnittStart();
assert.deepStrictEqual(s.center, [48.3538, 11.7861]);
assert.strictEqual(s.zoom, 12);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
@pytest.mark.parametrize("wert", [
    "kaputt", "1,2", "abc,def,10", "91,0,10", "0,181,10", "", "53,8,",
])
def test_unbrauchbarer_ausschnitt_faellt_auf_die_vorgabe_zurueck(wert):
    """Ein NaN als Mittelpunkt laesst Leaflet beim ersten Zeichnen werfen -- der ganze
    Karten-Tab bliebe leer. Ein beschaedigtes Cookie darf die Karte nicht unbrauchbar machen."""
    _node_lauf(f"""
_prefSchreib('friesenspy_ausschnitt', {wert!r});
_prefSpeicher = null;
const s = _ausschnittStart();
assert.deepStrictEqual(s.center, _KARTE_MITTE, 'Vorgabe wurde nicht benutzt');
assert.strictEqual(s.zoom, _KARTE_ZOOM);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_zoom_wird_in_die_erlaubten_grenzen_gezogen():
    """minZoom der Live-Karte ist 6. Ein kleinerer Wert im Cookie wuerde Leaflet eine Stufe
    unterschieben, die die Karte gar nicht anbietet."""
    _node_lauf("""
_prefSchreib('friesenspy_ausschnitt', '53,8,2');
_prefSpeicher = null;
assert.strictEqual(_ausschnittStart().zoom, _KARTE_ZOOM_MIN);
_prefSchreib('friesenspy_ausschnitt', '53,8,25');
_prefSpeicher = null;
assert.strictEqual(_ausschnittStart().zoom, _KARTE_ZOOM_MAX);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_nachgefuehrte_bewegung_wird_nicht_gemerkt():
    """Bei eingeschalteter Moving Map zieht der Sekundentakt die Karte staendig auf das
    Flugzeug. Wuerde das mitgeschrieben, staende beim naechsten Start der Ort, an dem der
    letzte Flug endete -- und nicht der, den der Nutzer zuletzt angesehen hat."""
    _node_lauf("""
const map = new FakeMap([50, 10], 11);
_ausschnittBeobachten(map);
global._naviSelbstBewegt = true;
map.feuern('moveend');
setTimeout(() => {
  assert.strictEqual(_prefLies('friesenspy_ausschnitt'), null,
                     'Nachgefuehrte Bewegung wurde gemerkt');
  console.log('OK');
}, _AUSSCHNITT_RUHE_MS + 200);
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_schieben_schreibt_erst_nach_der_ruhezeit_und_nur_einmal():
    """Beim Schieben feuert moveend in Serie. Jeder Schreibvorgang setzt das GESAMTE Cookie
    neu -- deshalb wird gebuendelt."""
    _node_lauf("""
const map = new FakeMap([48.1, 11.6], 13);
_ausschnittBeobachten(map);
let schreibvorgaenge = 0;
const echt = _prefSchreib;
_prefSchreib = function (k, v) { if (k === 'friesenspy_ausschnitt') schreibvorgaenge++; echt(k, v); };

map.feuern('moveend'); map.feuern('moveend'); map.feuern('zoomend');
assert.strictEqual(schreibvorgaenge, 0, 'Es wurde sofort geschrieben statt gebuendelt');

setTimeout(() => {
  assert.strictEqual(schreibvorgaenge, 1, 'Erwartet genau ein Schreibvorgang');
  assert.strictEqual(_prefLies('friesenspy_ausschnitt'), '48.1000,11.6000,13');
  console.log('OK');
}, _AUSSCHNITT_RUHE_MS + 200);
""")


# --------------------------------------------------------------------------------------
#  Statische Pruefungen am Quelltext
# --------------------------------------------------------------------------------------

def test_kein_karten_merker_greift_noch_direkt_auf_localstorage():
    """Die Umstellung waere wertlos, wenn ein einzelner Merker weiter direkt liest -- genau er
    wuerde im Kniebrett wieder den veralteten Stand liefern.

    Geprueft wird an den Funktionsrumpfen, nicht per freier Textsuche: Die Kommentare in
    diesem Bereich nennen `localStorage` mehrfach, eine freie Suche faende sie statt des Codes.
    """
    namen = [
        "_saveLayerPref", "_loadLayerPref", "_saveAIPPref", "_loadAIPPref",
        "_savePlatzrundenPref", "_loadPlatzrundenPref", "_saveFsePref", "_loadFsePref",
        "_saveVerkehrPref", "_loadVerkehrPref", "_saveSchilderPref", "_loadSchilderPref",
        "_naviLies", "_naviMerke",
    ]
    for name in namen:
        stelle = INDEX.index(f"function {name}(")
        rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
        assert "localStorage." not in rumpf, f"{name} greift noch direkt auf localStorage zu"
        assert "_pref" in rumpf, f"{name} benutzt den gemeinsamen Speicher nicht"


def test_cookie_ueberlebt_die_sitzung():
    """Ohne max-age waere es ein Sitzungscookie -- und damit genauso fluechtig wie das, was
    ersetzt werden sollte. path=/ ist noetig, damit /panel und / dasselbe Cookie sehen."""
    stelle = INDEX.index("function _prefCookieSchreiben(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "max-age=" in rumpf
    assert "path=/" in rumpf
    assert re.search(r"_PREF_MAX_AGE\s*=\s*60 \* 60 \* 24 \* 365", INDEX), \
        "Haltbarkeit ist nicht mehr ein Jahr"


def test_karte_startet_auf_dem_gemerkten_ausschnitt():
    """Gegenprobe zur Verdrahtung: Der Aufbau muss _ausschnittStart benutzen, nicht weiter die
    Konstanten. Ohne diese Pruefung waere die gesamte Ausschnitt-Logik tot und alle Tests
    darueber trotzdem gruen."""
    stelle = INDEX.index("liveMap = L.map('leaflet-map'")
    rumpf = INDEX[stelle:INDEX.index("});", stelle)]
    assert "_start.center" in rumpf and "_start.zoom" in rumpf
    assert re.search(r"const _start = _ausschnittStart\(\);", INDEX)
    assert "_ausschnittBeobachten(liveMap);" in INDEX
