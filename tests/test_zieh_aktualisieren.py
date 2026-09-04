"""Herunterziehen zum Aktualisieren in der installierten App (04.09.2026).

In der vom Home-Bildschirm gestarteten PWA gibt es Safaris eingebautes Nachladen nicht --
Apple blendet mit der Adressleiste auch die Geste aus. Die Seite bringt sie deshalb selbst
mit, uebernommen aus der Beezy-PWA.

Geprueft wird hier vor allem, wann die Geste NICHT ausloest. Ein Pull-to-Refresh, der auf der
Karte mitfeuert, ist schlimmer als gar keiner: Der Karten-Tab steht immer ganz oben, jedes
Verschieben des Ausschnitts nach Sueden waere ein Zug nach unten am Seitenanfang.
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


def _gesten_quelltext():
    """Von der Schwelle bis hinter _ziehAktualisierenBinden.

    Die Scheibe MUSS bei `const _ZIEH_SCHWELLE` beginnen -- die Konstante entscheidet, ab
    wann losgelassen ausloest, und ohne sie waere jeder Schwellentest ein ReferenceError
    statt einer Aussage.
    """
    start = INDEX.index("const _ZIEH_SCHWELLE")
    ende = INDEX.index("function _ziehAktualisierenBinden(")
    return INDEX[start:INDEX.index("\n}", ende) + len("\n}")]


# Ein DOM, das genau die drei Dinge kann, an denen die Geste haengt: Ereignisse einsammeln,
# einen Knoten anlegen und einen Elternbaum anbieten. Absichtlich kein jsdom -- die Geste
# liest nur `scrollTop`, `classList` und `parentElement`, und ein echtes DOM verdeckte mit
# seinem Eigenleben, welche dieser drei Angaben der Code wirklich auswertet.
_HARNESS = """
'use strict';
const assert = require('assert');

function FakeEl(klassen, scrollTop) {
  this._klassen = klassen || [];
  this.scrollTop = scrollTop || 0;
  this.parentElement = null;
  this.hidden = false;
  this.className = '';
  this.dataset = {};
  this.style = {};
  const selbst = this;
  this.classList = {
    contains: (k) => selbst._klassen.indexOf(k) !== -1,
    add: (k) => { if (selbst._klassen.indexOf(k) === -1) selbst._klassen.push(k); },
  };
}
// Kette vom aeussersten zum innersten Element, gibt das innerste (= Beruehrungsziel) zurueck.
global.kette = function (...knoten) {
  for (let i = 1; i < knoten.length; i++) knoten[i].parentElement = knoten[i - 1];
  return knoten[knoten.length - 1];
};
global.FakeEl = FakeEl;

global._handler = {};
global._angehaengt = [];
global._modalOffen = false;
global._panel = false;

const body = new FakeEl([], 0);
global.document = {
  body: body,
  documentElement: { classList: { contains: (k) => k === 'vr-panel' && global._panel } },
  activeElement: null,
  addEventListener: (name, fn) => { (global._handler[name] = global._handler[name] || []).push(fn); },
  createElement: () => new FakeEl([], 0),
  // Der Selektor selbst wird nicht ausgewertet -- geprueft wird, DASS bei offenem Modal
  // etwas gefunden wird. Welche Klassen ein offenes Modal traegt, sichert der Test
  // test_modal_selektor_trifft_die_echten_modale gegen das Markup ab.
  querySelector: () => (global._modalOffen ? {} : null),
};
document.body.appendChild = (el) => { global._angehaengt.push(el); return el; };

global.window = { scrollY: 0, navigator: { standalone: true } };
global.scrollY = 0;   // die Geste liest `window.scrollY`; hier ist window ein eigenes Objekt

global._isStandalone = () => true;

// Was beim Ausloesen passieren soll, ist NICHT Gegenstand dieser Tests -- hier zaehlt nur,
// ob es passiert. Die Verdrahtung mit der echten Funktion prueft
// test_geste_ruft_die_gemeinsame_aktualisierung auf dem Quelltext.
global._laeufe = 0;
global._loesen = null;
global.alleDatenNeuLaden = () => {
  global._laeufe++;
  return new Promise((ok) => { global._loesen = ok; });
};

// Eine Beruehrungsfolge abspielen. `wege` sind Pixel relativ zum Startpunkt.
global.zieh = function (ziel, wege, opt) {
  opt = opt || {};
  const finger = opt.finger || 1;
  const touches = (y) => {
    const liste = [{ clientY: y }];
    for (let i = 1; i < finger; i++) liste.push({ clientY: y });
    return liste;
  };
  (global._handler.touchstart || []).forEach((fn) => fn({ target: ziel, touches: touches(100) }));
  wege.forEach((w) => {
    (global._handler.touchmove || []).forEach((fn) => fn({ target: ziel, touches: touches(100 + w) }));
  });
  if (opt.abbruch) {
    (global._handler.touchcancel || []).forEach((fn) => fn({}));
  } else {
    (global._handler.touchend || []).forEach((fn) => fn({}));
  }
};
global.balken = () => global._angehaengt[0];
"""


def _node_lauf(treiber):
    if _NODE is None:
        pytest.skip("Node.js nicht verfuegbar")
    skript = _HARNESS + "\n" + _gesten_quelltext() + "\n" + treiber
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
#  Sie loest aus -- und zwar erst ab der Schwelle
# --------------------------------------------------------------------------------------

@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_zug_ueber_die_schwelle_holt_die_daten():
    _node_lauf("""
_ziehAktualisierenBinden();
zieh(new FakeEl(['flight-row'], 0), [20, 50, _ZIEH_SCHWELLE + 5]);
assert.strictEqual(global._laeufe, 1, 'Zug ueber die Schwelle hat nichts geholt');
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_kurzer_zug_loest_nicht_aus():
    """Sonst reicht das Antippen einer Zeile am Seitenanfang."""
    _node_lauf("""
_ziehAktualisierenBinden();
zieh(new FakeEl([], 0), [10, _ZIEH_SCHWELLE - 1]);
assert.strictEqual(global._laeufe, 0);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_zug_nach_oben_loest_nicht_aus():
    _node_lauf("""
_ziehAktualisierenBinden();
zieh(new FakeEl([], 0), [-40, -120]);
assert.strictEqual(global._laeufe, 0);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_zwei_finger_sind_ein_zoom():
    _node_lauf("""
_ziehAktualisierenBinden();
zieh(new FakeEl([], 0), [_ZIEH_SCHWELLE + 40], { finger: 2 });
assert.strictEqual(global._laeufe, 0);
console.log('OK');
""")


# --------------------------------------------------------------------------------------
#  Wo sie schweigen muss
# --------------------------------------------------------------------------------------

@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_auf_der_karte_bleibt_ziehen_ein_verschieben():
    """Der wichtigste Fall.

    Der Karten-Tab steht immer ganz oben (`scrollY === 0`), die Karte fuellt fast den
    ganzen Bildschirm, und den Ausschnitt nach Sueden zu schieben ist dort die haeufigste
    Geste ueberhaupt. Ohne die Ausnahme aktualisierte jedes zweite Verschieben die App.
    """
    _node_lauf("""
_ziehAktualisierenBinden();
const ziel = kette(new FakeEl(['leaflet-container'], 0), new FakeEl(['leaflet-marker-icon'], 0));
zieh(ziel, [_ZIEH_SCHWELLE + 60]);
assert.strictEqual(global._laeufe, 0, 'Kartenverschiebung hat die App aktualisiert');
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_nicht_ganz_oben_kein_zug():
    _node_lauf("""
_ziehAktualisierenBinden();
global.window.scrollY = 240;
zieh(new FakeEl([], 0), [_ZIEH_SCHWELLE + 60]);
assert.strictEqual(global._laeufe, 0);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_innerer_scrollbereich_gewinnt():
    """`.scroll-list`/`.table-scroll` scrollen selbst -- dort gehoert der Finger der Liste.

    Der Beweis haengt an `scrollTop` des VORFAHREN, nicht des Ziels: Angefasst wird eine
    Tabellenzeile, gescrollt hat der Kasten darum.
    """
    _node_lauf("""
_ziehAktualisierenBinden();
const ziel = kette(new FakeEl(['scroll-list'], 180), new FakeEl(['row'], 0));
zieh(ziel, [_ZIEH_SCHWELLE + 60]);
assert.strictEqual(global._laeufe, 0);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_offenes_modal_sperrt():
    """Hinter einem Modal neu zu zeichnen sieht niemand -- und die Liste darunter springt."""
    _node_lauf("""
_ziehAktualisierenBinden();
global._modalOffen = true;
zieh(new FakeEl([], 0), [_ZIEH_SCHWELLE + 60]);
assert.strictEqual(global._laeufe, 0);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_waehrend_des_tippens_kein_zug():
    _node_lauf("""
_ziehAktualisierenBinden();
global.document.activeElement = { tagName: 'INPUT' };
zieh(new FakeEl([], 0), [_ZIEH_SCHWELLE + 60]);
assert.strictEqual(global._laeufe, 0);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_im_browsertab_wird_gar_nichts_gebunden():
    """Dort macht Safari das selbst -- zwei Gesten uebereinander waeren schlechter als eine."""
    _node_lauf("""
global._isStandalone = () => false;
_ziehAktualisierenBinden();
assert.strictEqual(global._angehaengt.length, 0, 'Balken haengt im Browsertab');
assert.strictEqual(Object.keys(global._handler).length, 0, 'Handler im Browsertab gebunden');
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_im_kniebrett_wird_gar_nichts_gebunden():
    """Coherent GT hat weder Adressleiste noch Finger -- und meldet auf `display-mode`
    nichts Verlaessliches. Deshalb steht die Panel-Wache VOR der Standalone-Frage."""
    _node_lauf("""
global._panel = true;
global._isStandalone = () => { throw new Error('darf im Panel gar nicht gefragt werden'); };
_ziehAktualisierenBinden();
assert.strictEqual(global._angehaengt.length, 0);
console.log('OK');
""")


# --------------------------------------------------------------------------------------
#  Der Balken
# --------------------------------------------------------------------------------------

@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_balken_waechst_mit_und_meldet_bereitschaft():
    _node_lauf("""
_ziehAktualisierenBinden();
const ziel = new FakeEl([], 0);
(global._handler.touchstart || []).forEach((fn) => fn({ target: ziel, touches: [{ clientY: 100 }] }));
(global._handler.touchmove || []).forEach((fn) => fn({ target: ziel, touches: [{ clientY: 135 }] }));
assert.strictEqual(balken().hidden, false, 'Balken bleibt beim Ziehen unsichtbar');
assert.strictEqual(balken().dataset.bereit, '0', 'halber Weg gilt schon als bereit');
assert.ok(/scaleX\\(0\\.5\\)/.test(balken().style.transform), balken().style.transform);
(global._handler.touchmove || []).forEach((fn) => fn({ target: ziel, touches: [{ clientY: 300 }] }));
assert.strictEqual(balken().dataset.bereit, '1');
assert.ok(/scaleX\\(1\\)/.test(balken().style.transform), 'Balken waechst ueber die volle Breite hinaus');
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_balken_bleibt_stehen_bis_die_daten_da_sind():
    """Die einzige Rueckmeldung, die die Geste hat.

    Verschwaende der Balken beim Loslassen, waere bei unveraenderter Fluglage ueberhaupt
    nichts zu sehen -- und der Nutzer zoege ein zweites Mal.
    """
    _node_lauf("""
_ziehAktualisierenBinden();
zieh(new FakeEl([], 0), [_ZIEH_SCHWELLE + 20]);
assert.strictEqual(balken().hidden, false, 'Balken schon weg, bevor die Daten da sind');
global._loesen();
setTimeout(() => {
  assert.strictEqual(balken().hidden, true, 'Balken bleibt nach dem Laden stehen');
  assert.strictEqual(balken().dataset.bereit, '0');
  console.log('OK');
}, 0);
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_waehrend_des_ladens_kein_zweiter_zug():
    _node_lauf("""
_ziehAktualisierenBinden();
const ziel = new FakeEl([], 0);
zieh(ziel, [_ZIEH_SCHWELLE + 20]);
zieh(ziel, [_ZIEH_SCHWELLE + 20]);
assert.strictEqual(global._laeufe, 1, 'zweiter Zug lief los, obwohl der erste noch holt');
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_abgebrochener_zug_laesst_keinen_balken_stehen():
    """Ein Anruf oder eine Systemgeste beendet die Beruehrung mit `touchcancel`; ein
    `touchend` kommt dann nie. Ohne die Behandlung blieb ein Strich am oberen Rand."""
    _node_lauf("""
_ziehAktualisierenBinden();
zieh(new FakeEl([], 0), [_ZIEH_SCHWELLE + 20], { abbruch: true });
assert.strictEqual(global._laeufe, 0, 'abgebrochener Zug hat trotzdem geholt');
assert.strictEqual(balken().hidden, true, 'Balken steht nach dem Abbruch noch');
console.log('OK');
""")


# --------------------------------------------------------------------------------------
#  Verankerung im echten Quelltext (was der Node-Harness per Attrappe ersetzt)
# --------------------------------------------------------------------------------------

def test_geste_ruft_die_gemeinsame_aktualisierung():
    """Im Harness ist `alleDatenNeuLaden` eine Attrappe -- hier steht, dass es sie gibt und
    dass beide Ausloeser (Vordergrund, Zug) denselben Weg nehmen."""
    assert "async function alleDatenNeuLaden()" in INDEX
    assert INDEX.count("alleDatenNeuLaden()") >= 3   # Deklaration + visibilitychange + Geste
    # rindex: der erste visibilitychange-Listener gehoert der Panel-Update-Wache.
    sicht = INDEX[INDEX.rindex("document.addEventListener('visibilitychange', () => {"):]
    assert "alleDatenNeuLaden();" in sicht[:300], "Vordergrund-Rueckkehr nimmt einen eigenen Weg"


def test_aktualisierung_holt_alle_sichtbaren_bereiche():
    """Was beim Ziehen NICHT mitkommt, steht danach veraltet da.

    Gebunden an die Aufrufe im Rumpf, nicht an einen Kommentar: Prefiles und TeamSpeak
    stehen auf dem Live-Tab unter der Flugliste und pollen sonst nur alle 60 bzw. 30 s.
    """
    start = INDEX.index("async function alleDatenNeuLaden()")
    rumpf = INDEX[start:INDEX.index("\n}", start)]
    for aufruf in ("refreshLiveData()", "connectSSE()", "fetchBummelActive()",
                   "fetchKutterActive()", "fetchAndRenderPrefiles()", "fetchAndRenderTeamspeak()"):
        assert aufruf in rumpf, f"{aufruf} fehlt in alleDatenNeuLaden"


def test_modal_selektor_trifft_die_echten_modale():
    """Der Selektor aus `_ziehErlaubt` gegen das Markup gehalten.

    Er ist die einzige Stelle, an der die Geste von Klassennamen abhaengt, die woanders
    vergeben werden -- eine Umbenennung im Markup wuerde sie sonst stumm entschaerfen.
    """
    start = INDEX.index("function _ziehErlaubt(")
    rumpf = INDEX[start:INDEX.index("\n}", start)]
    assert ".fp-modal-overlay:not(.hidden)" in rumpf
    assert ".modal.open" in rumpf
    # Beide Bauformen kommen im Markup wirklich vor.
    assert re.search(r'<div id="[a-z-]+" class="fp-modal-overlay hidden">', INDEX)
    assert re.search(r'<div id="[a-z-]+" class="modal">', INDEX)
    assert ".modal.open {" in INDEX


def test_balken_hat_seine_stilregeln():
    """Ohne `.zieh-balken[hidden]` bliebe ein Strich am oberen Rand jeder Ansicht stehen."""
    assert ".zieh-balken {" in INDEX
    assert ".zieh-balken[hidden] { display: none; }" in INDEX
    assert '.zieh-balken[data-bereit="1"]' in INDEX


def test_geste_wird_nach_dem_parsen_gebunden():
    """Sie haengt einen Knoten an `document.body` -- ein Aufruf auf Modulebene faende ihn
    im Inline-Skript noch nicht."""
    assert "_ziehAktualisierenBinden();" in INDEX
    kopf = INDEX[:INDEX.index("_ziehAktualisierenBinden();")]
    assert kopf.rindex("document.addEventListener('DOMContentLoaded'") > kopf.rindex("</style>")
