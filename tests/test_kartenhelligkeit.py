"""Kachel-Zielhelligkeit im Panel (Regler im Zahnrad-Menue).

Hintergrund: Der Helligkeitsregler des MSFS-EFB dimmt das ganze Tablet mit einem
einzigen Faktor. Er kann das VERHAELTNIS zwischen den sehr hellen Kartenkacheln und der
fast schwarzen Oberflaeche nicht veraendern -- und genau daran scheitert er: Nachts
begrenzt das Hellste im Bild (die Karte), tagsueber das Dunkelste (Schrift und Flaechen).
Es gibt keine Stellung, die beides erfuellt.

Gemessen am 19.09.2026 ueber vier Kacheln in Ostfriesland (Zoom 11), jeweils ueber
`--bg-body` gelegt -- mittlere Luma als Anteil von Weiss:

    CARTO light  89 %      Satellit   28 %      OFM (aero)  9 %
    OpenTopoMap  81 %      CARTO dark 11 %      Oberflaeche 3 %

Der Regler stellt deshalb nicht "wie stark wird gedimmt", sondern die ZIELHELLIGKEIT.
Jede Grundkarte bekommt den Faktor, der sie dorthin bringt. Das haelt die Bildhelligkeit
auch beim Kartenwechsel gleich -- heute springt sie von Satellit auf OpenTopoMap um das
Dreifache, was nachts blendet.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

_NODE = shutil.which("node")


def _schnitt(anfang: str, ende_marke: str) -> str:
    """Quelltextscheibe von ``anfang`` bis zum Ende der Funktion ``ende_marke``."""
    start = INDEX.index(anfang)
    ende = INDEX.index(ende_marke, start)
    return INDEX[start:INDEX.index("\n}", ende) + len("\n}")]


def _helligkeit_quelltext() -> str:
    """Die Merker-Schicht UND der Helligkeitsblock.

    Die Merker muessen mit: ``_kartenhelligkeitLesen`` liest ueber ``_prefLies``, und ein
    Test gegen eine Attrappe pruefte die Attrappe statt der Rueckfall-Logik.
    """
    merker = _schnitt("const _KARTE_MITTE", "function _ausschnittBeobachten(")
    # Ab `const _PANEL_MODUS`: _kartenhelligkeitAnwenden fragt danach, ob es ueberhaupt im
    # Panel laeuft. Eine Attrappe dafuer wuerde genau die Weiche verdecken, die entscheidet,
    # ob die Website angefasst wird.
    helligkeit = _schnitt("const _PANEL_MODUS", "function _kartenhelligkeitStufen(")
    return merker + "\n" + helligkeit


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
global.document.documentElement = { classList: { contains: () => false } };
// Kein Einstellungsmenue im Node-Lauf. _kartenhelligkeitAnwenden faellt ueber _PANEL_MODUS
// (oben auf "Website" gesetzt) von selbst raus, _kartenhelligkeitAnzeigen braucht das hier.
global.document.getElementById = () => null;
"""


def _node_lauf(treiber: str) -> None:
    if _NODE is None:
        pytest.skip("Node.js nicht verfuegbar")
    skript = _HARNESS + "\n" + _helligkeit_quelltext() + "\n" + treiber
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


knoten = pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")


# --------------------------------------------------------------------------------------
#  Der Faktor je Ebene
# --------------------------------------------------------------------------------------

@knoten
def test_helle_karte_landet_auf_dem_zielwert():
    """OpenTopoMap (81 %) muss bei Ziel 30 % auch wirklich bei 30 % ankommen."""
    _node_lauf("""
const ziel = 0.30;
const f = _kachelFaktor('topo', ziel);
assert.ok(Math.abs(_KACHEL_LUMA.topo * f - ziel) < 0.01,
  'topo landet bei ' + (_KACHEL_LUMA.topo * f) + ' statt ' + ziel);
console.log('OK');
""")


@knoten
def test_alle_grundkarten_landen_auf_demselben_zielwert():
    """Der Kern der Sache: EIN Regler, und der Kartenwechsel aendert die Helligkeit nicht."""
    _node_lauf("""
const ziel = 0.08;   // unter der dunkelsten Grundkarte, also fuer alle erreichbar
for (const ebene of Object.keys(_KACHEL_LUMA)) {
  const ist = _KACHEL_LUMA[ebene] * _kachelFaktor(ebene, ziel);
  assert.ok(Math.abs(ist - ziel) < 0.01, ebene + ' landet bei ' + ist + ' statt ' + ziel);
}
console.log('OK');
""")


@knoten
def test_dunkle_karte_wird_nicht_aufgehellt():
    """OFM liegt mit 9 % schon unter Ziel 30 % -- der Filter darf sie nicht hochziehen."""
    _node_lauf("""
assert.strictEqual(_kachelFaktor('ofm', 0.30), 1);
console.log('OK');
""")


@knoten
def test_unbekannte_ebene_bleibt_unveraendert():
    """Eine Ebene ohne Messwert wird nicht geraten, sondern in Ruhe gelassen."""
    _node_lauf("""
assert.strictEqual(_kachelFaktor('gibtsnicht', 0.30), 1);
console.log('OK');
""")


# --------------------------------------------------------------------------------------
#  Der Merker
# --------------------------------------------------------------------------------------

@knoten
def test_ohne_merker_ist_die_absenkung_aus():
    _node_lauf("""
assert.strictEqual(_kartenhelligkeitLesen(), _KARTENHELLIGKEIT_AUS);
console.log('OK');
""")


@knoten
@pytest.mark.parametrize("roh,erwartet", [("0.01", "_KARTENHELLIGKEIT_MIN"),
                                          ("5", "_KARTENHELLIGKEIT_AUS")])
def test_wert_wird_in_die_grenzen_gezogen(roh, erwartet):
    _node_lauf(f"""
_prefSchreib(_KARTENHELLIGKEIT_KEY, '{roh}');
assert.strictEqual(_kartenhelligkeitLesen(), {erwartet});
console.log('OK');
""")


@knoten
def test_beschaedigter_merker_faellt_auf_aus_zurueck():
    """Ein unlesbarer Wert darf die Karte nicht schwarz machen."""
    _node_lauf("""
_prefSchreib(_KARTENHELLIGKEIT_KEY, 'dunkel bitte');
assert.strictEqual(_kartenhelligkeitLesen(), _KARTENHELLIGKEIT_AUS);
console.log('OK');
""")


# --------------------------------------------------------------------------------------
#  Die erzeugten CSS-Regeln
# --------------------------------------------------------------------------------------

@knoten
def test_regeln_nennen_jede_grundkarte():
    _node_lauf("""
const css = _kachelRegeln(0.30);
for (const ebene of Object.keys(_KACHEL_LUMA)) {
  assert.ok(css.includes('kachel-' + ebene), 'Regel fehlt fuer ' + ebene);
}
console.log('OK');
""")


@knoten
def test_regeln_gelten_nur_im_panel():
    """Die Website bleibt unberuehrt -- jede Regel traegt html.vr-panel."""
    _node_lauf("""
const css = _kachelRegeln(0.30);
const zeilen = css.split('}').map((z) => z.trim()).filter((z) => z.length);
assert.ok(zeilen.length >= 5, 'zu wenige Regeln: ' + zeilen.length);
for (const z of zeilen) {
  assert.ok(z.startsWith('html.vr-panel'), 'Regel ohne Panel-Bindung: ' + z);
}
console.log('OK');
""")


# --------------------------------------------------------------------------------------
#  Bindung an den Code: eine neue Grundkarte darf nicht stillschweigend durchrutschen
# --------------------------------------------------------------------------------------

def _grundkarten_im_code() -> list[str]:
    """Die Schluessel aus ``_makeTileLayers`` -- an der Fabrik, nicht an einem Kommentar."""
    start = INDEX.index("function _makeTileLayers(")
    koerper = INDEX[start:INDEX.index("\n}", start)]
    return re.findall(r"^\s*(\w+):\s*L\.tileLayer\(", koerper, re.M)


def test_die_fabrik_liefert_ueberhaupt_grundkarten():
    """Negativprobe fuer die beiden Waechter darunter: findet der Ausdruck nichts,
    waeren sie beide gruen, ohne irgendetwas zu pruefen."""
    assert len(_grundkarten_im_code()) >= 5, _grundkarten_im_code()


def test_jede_grundkarte_hat_eine_gemessene_helligkeit():
    block = INDEX[INDEX.index("const _KACHEL_LUMA"):]
    gemessen = set(re.findall(r"(\w+):\s*0\.\d+", block[:block.index("}")]))
    fehlen = [e for e in _grundkarten_im_code() if e not in gemessen]
    assert not fehlen, f"Grundkarte(n) ohne Messwert in _KACHEL_LUMA: {fehlen}"


def _ebenen_ohne_klasse(koerper: str) -> list[str]:
    """Grundkarten, deren Eintrag nicht ``className: 'kachel-<name>'`` enthaelt.

    Bewusst am EINTRAG festgemacht, nicht an der Zeile: Wie die Optionen umbrochen sind,
    ist Formatierung und darf keinen Test brechen. Dass die Klasse zur richtigen Ebene
    gehoert, bleibt trotzdem geprueft -- der Eintrag reicht von einem Schluessel bis zum
    naechsten.
    """
    grenzen = [m.start() for m in re.finditer(r"^\s*\w+:\s*L\.tileLayer\(", koerper, re.M)]
    ohne = []
    for i, anfang in enumerate(grenzen):
        eintrag = koerper[anfang:grenzen[i + 1] if i + 1 < len(grenzen) else len(koerper)]
        name = re.match(r"\s*(\w+):", eintrag).group(1)
        if f"kachel-{name}" not in eintrag:
            ohne.append(name)
    return ohne


def test_jede_grundkarte_traegt_ihre_klasse():
    start = INDEX.index("function _makeTileLayers(")
    koerper = INDEX[start:INDEX.index("\n}", start)]
    ohne = _ebenen_ohne_klasse(koerper)
    assert not ohne, f"Grundkarte(n) ohne className 'kachel-<name>': {ohne}"


def test_der_klassen_waechter_schlaegt_bei_einer_falschen_zuordnung_an():
    """Negativprobe. Ein Waechter, von dem niemand weiss, ob er anschlaegt, ist keiner --
    hier traegt `topo` die Klasse von `sat`."""
    gebastelt = """
    topo: L.tileLayer(TILE_TOPO_URL, {
      className: 'kachel-sat', maxZoom: 17 }),
    sat: L.tileLayer(TILE_SAT_URL, {
      className: 'kachel-sat', maxZoom: 19 }),
"""
    assert _ebenen_ohne_klasse(gebastelt) == ["topo"]


# --------------------------------------------------------------------------------------
#  Die Stufennavigation der beiden Knoepfe
# --------------------------------------------------------------------------------------

@knoten
def test_erster_tipp_auf_dunkler_verlaesst_das_aus():
    _node_lauf("""
_kartenhelligkeitStufen(1);
assert.strictEqual(_kartenhelligkeitLesen(), _KARTENHELLIGKEIT_STUFEN[1]);
console.log('OK');
""")


@knoten
def test_dunkler_bleibt_an_der_untersten_stufe_stehen():
    """Kein Umschlagen nach hell -- sonst wird die Karte beim Weiterdruecken ploetzlich weiss."""
    _node_lauf("""
for (let i = 0; i < 20; i++) _kartenhelligkeitStufen(1);
assert.strictEqual(_kartenhelligkeitLesen(), _KARTENHELLIGKEIT_MIN);
console.log('OK');
""")


@knoten
def test_heller_bleibt_bei_aus_stehen():
    _node_lauf("""
_kartenhelligkeitSetzen(_KARTENHELLIGKEIT_MIN);
for (let i = 0; i < 20; i++) _kartenhelligkeitStufen(-1);
assert.strictEqual(_kartenhelligkeitLesen(), _KARTENHELLIGKEIT_AUS);
console.log('OK');
""")


@knoten
def test_jede_stufe_ist_einzeln_erreichbar():
    """Hin und zurueck muss dieselbe Leiter sein -- eine Nachbarsuche, die auf eine bereits
    besuchte Stufe zurueckfaellt, wuerde hier haengen bleiben."""
    _node_lauf("""
const runter = [];
for (let i = 0; i < _KARTENHELLIGKEIT_STUFEN.length - 1; i++) {
  _kartenhelligkeitStufen(1);
  runter.push(_kartenhelligkeitLesen());
}
assert.deepStrictEqual(runter, _KARTENHELLIGKEIT_STUFEN.slice(1));
console.log('OK');
""")


@knoten
def test_ein_krummer_gemerkter_wert_findet_die_naechste_stufe():
    """Aus einer aelteren Stufenleiter koennen Zwischenwerte im Merker stehen."""
    _node_lauf("""
_prefSchreib(_KARTENHELLIGKEIT_KEY, '0.44');   // dicht an Stufe 0.45
_kartenhelligkeitStufen(1);
assert.strictEqual(_kartenhelligkeitLesen(), 0.35);
console.log('OK');
""")


# --------------------------------------------------------------------------------------
#  Die Kartenblaetter (Sichtflug, Flugplatz, Rollkarte)
# --------------------------------------------------------------------------------------
# Sie liegen als L.imageOverlay auf der Karte, nicht als Kachelebene -- und sie sind mit
# 92-96 % Luma das Hellste ueberhaupt auf diesem Bildschirm, heller als jede Grundkarte
# (gemessen 19.09.2026 ueber je zwoelf abgelegte Blaetter, nur die deckenden Bildpunkte).
# Nutzerwunsch 19.09.2026: "die Karten-Overlay (flugplatz und Sichtflug) muessen mit
# gedimmt werden."

@knoten
def test_kartenblaetter_werden_mitgedimmt():
    _node_lauf("""
const ziel = 0.30;
for (const sorte of ['sichtflug', 'flugplatzkarte', 'rollkarte']) {
  const ist = _KACHEL_LUMA[sorte] * _kachelFaktor(sorte, ziel);
  assert.ok(Math.abs(ist - ziel) < 0.01, sorte + ' landet bei ' + ist + ' statt ' + ziel);
}
console.log('OK');
""")


@knoten
def test_regeln_treffen_auch_die_bildebenen():
    """Bei L.imageOverlay landet `className` am <img> selbst (leaflet-src.js:9530), bei
    L.tileLayer dagegen am Container (:11456). Eine Regel muss deshalb BEIDE Formen nennen."""
    _node_lauf("""
const css = _kachelRegeln(0.30);
assert.ok(css.includes('img.kachel-sichtflug'), 'Bildebene wird nicht getroffen');
assert.ok(css.includes('.kachel-topo img.leaflet-tile'), 'Kachelebene wird nicht getroffen');
console.log('OK');
""")


def _bildebenen_ohne_klasse() -> list[str]:
    """Aufrufe von ``L.imageOverlay``, die keinen Helligkeits-Griff mitgeben."""
    ohne = []
    for m in re.finditer(r"L\.imageOverlay\(", INDEX):
        # Bis zur schliessenden Klammer des Options-Objekts -- grosszuegig, aber begrenzt.
        stueck = INDEX[m.start():m.start() + 600]
        if "className: 'kachel-'" not in stueck:
            ohne.append(INDEX[max(0, m.start() - 60):m.start()].strip().splitlines()[-1])
    return ohne


def test_es_gibt_ueberhaupt_bildebenen():
    """Negativprobe fuer den Waechter darunter."""
    assert len(re.findall(r"L\.imageOverlay\(", INDEX)) >= 2


def test_jede_bildebene_traegt_ihren_helligkeits_griff():
    ohne = _bildebenen_ohne_klasse()
    assert not ohne, f"L.imageOverlay ohne className 'kachel-'+sorte: {ohne}"


def test_jede_kartenblatt_sorte_hat_einen_messwert():
    """Bindung ueber die Dateigrenze: Kommt serverseitig eine vierte Sorte dazu, faellt sie
    hier auf, statt still ungedimmt zu bleiben."""
    db = (Path(__file__).resolve().parents[1] / "app" / "database.py").read_text(encoding="utf-8")
    sorten = re.search(r"SORTEN_DFS\s*=\s*\(([^)]*)\)", db).group(1)
    sorten = re.findall(r'"([a-z]+)"', sorten)
    assert sorten, "SORTEN_DFS nicht gefunden"
    block = INDEX[INDEX.index("const _KACHEL_LUMA"):]
    gemessen = set(re.findall(r"(\w+):\s*0\.\d+", block[:block.index("}")]))
    fehlen = [s for s in sorten if s not in gemessen]
    assert not fehlen, f"Kartenblatt-Sorte(n) ohne Messwert in _KACHEL_LUMA: {fehlen}"
