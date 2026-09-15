"""Türkis im Kniebrett: was das Sim-Matching auf der Karte sichtbar macht.

Bis zum 15.09.2026 stand Türkis für genau eine Sache — „die FriesenBrügge dieses Piloten
meldet gerade". Im Kniebrett kam diese Farbe deshalb nie vor: Der Brügge-Strom erreicht das
Panel gar nicht (s. `_brueggeStromEinarbeiten`), dort trägt das Sim-Matching. Ausgerechnet
die genaueste Anzeige der ganzen App sah damit aus wie die ungenaueste.

Die Aussage der Farbe ist jetzt dieselbe wie vorher — „sekundengenau, und es steht fest, wer
das ist" —, nur der Weg dorthin ist einer von zweien. Geprüft wird beides getrennt:

* `_punktIstSekundengenau` — wann gilt ein Friese als sekundengenau
* `makeAircraftIcon` — was daraus am Symbol wird, und zwar für Friesen ANDERS als für
  Fremdverkehr: dort wechselt nur der Saum, weil die Fläche die Zugehörigkeit trägt
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


def _ausschnitt(anfang: str, ende_nach: str) -> str:
    """Ein Stück Quelltext von `anfang` bis zum Ende der Funktion, die `ende_nach` beginnt."""
    start = INDEX.index(anfang)
    ende = INDEX.index(ende_nach)
    return INDEX[start:INDEX.index("\n}", ende) + len("\n}")]


_HARNESS = """
'use strict';
const assert = require('assert');

// Leaflet gibt es hier nicht -- gebraucht wird nur, was divIcon zurueckgibt.
global.L = { divIcon: function (o) { return o; } };

// Was der Ausschnitt von aussen braucht. Beide Ablagen sind im Original weiter oben zuhause.
global._brueggeWerte = Object.create(null);
global._friesenSimWerte = Object.create(null);
global._simVerkehrFrischWert = true;
global._eigenes = null;
function _brueggeFrisch(cs) {
  const b = global._brueggeWerte[cs];
  return !!(b && (Date.now() - b.ts) < 10000);
}
function _simVerkehrFrisch() { return global._simVerkehrFrischWert; }
// Im Original prueft es `_simPosFrisch()` gleich mit -- die Frist steckt also schon drin.
function _istEigenesFlugzeug(cs) { return global._eigenes === cs; }

__QUELLTEXT__

__PRUEFUNG__
console.log('OK');
"""


def _node(pruefung: str) -> str:
    if not _NODE:
        pytest.skip("node nicht vorhanden")
    quelltext = (_ausschnitt("function _punktIstSekundengenau(",
                             "function _punktIstSekundengenau(")
                 + "\n\n"
                 + "const _FLUGZEUG_PX = 26;\n"
                 + "const _FLUGZEUG_PFAD = 'x';\n"
                 + "const _FLUGZEUG_PX_FREMD = 18;\n"
                 + "const _FLUGZEUG_PFAD_FREMD = 'y';\n\n"
                 + _ausschnitt("function makeAircraftIcon(", "function makeAircraftIcon("))
    quelle = _HARNESS.replace("__QUELLTEXT__", quelltext).replace("__PRUEFUNG__", pruefung)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(quelle)
        name = f.name
    lauf = subprocess.run([_NODE, name], capture_output=True, text=True, timeout=30)
    assert lauf.returncode == 0, lauf.stdout + lauf.stderr
    return lauf.stdout


# ---------------------------------------------------------------------------
# Wann ist ein Friese sekundengenau?
# ---------------------------------------------------------------------------

def test_ohne_quelle_ist_nichts_sekundengenau():
    _node("assert.strictEqual(_punktIstSekundengenau('FRS49'), false);")


def test_die_bruegge_genuegt_weiterhin():
    """Der Weg der Website — er darf durch den neuen zweiten nicht verlorengehen."""
    _node("""
      global._brueggeWerte['FRS49'] = { ts: Date.now() };
      assert.strictEqual(_punktIstSekundengenau('FRS49'), true);
    """)


def test_die_sim_zuordnung_genuegt_auch():
    """Der Weg des Kniebretts. `_friesenSimWerte` wird ausschliesslich fuer einen
    ZUGEORDNETEN Friesen geschrieben (s. `_verkehrZusammenfuehren`, Schritt 4) -- sein
    Vorhandensein IST die Zuordnung."""
    _node("""
      global._friesenSimWerte['FRS49'] = { alt: 1500, gs: 92 };
      assert.strictEqual(_punktIstSekundengenau('FRS49'), true);
    """)


def test_reisst_die_bruecke_zum_simulator_ab_faellt_die_farbe_zurueck():
    """Der Fall, den `_paarungenAufraeumen` nicht abfangen kann: Meldet der Simulator gar
    nichts mehr, raeumt auch niemand mehr auf. Ohne die Frist bliebe das Symbol tuerkis und
    behauptete eine Genauigkeit, die es nicht mehr gibt."""
    _node("""
      global._friesenSimWerte['FRS49'] = { alt: 1500, gs: 92 };
      global._simVerkehrFrischWert = false;
      assert.strictEqual(_punktIstSekundengenau('FRS49'), false);
    """)


def test_das_eigene_flugzeug_ist_immer_sekundengenau():
    """Es braucht keine Zuordnung: Seine Position kommt aus `_simPos`, also direkt aus dem
    Simulator. Genauer kennt die Karte kein Flugzeug -- und trotzdem blieb es bis zum
    15.09.2026 blau, waehrend jeder zugeordnete Nachbar tuerkis wurde."""
    _node("""
      global._eigenes = 'FRS49';
      assert.strictEqual(_punktIstSekundengenau('FRS49'), true);
      assert.strictEqual(_punktIstSekundengenau('FRS12'), false);
    """)


def test_eine_alte_bruegge_meldung_traegt_nicht_mehr():
    _node("""
      global._brueggeWerte['FRS49'] = { ts: Date.now() - 20000 };
      global._simVerkehrFrischWert = false;
      assert.strictEqual(_punktIstSekundengenau('FRS49'), false);
    """)


# ---------------------------------------------------------------------------
# Was am Symbol daraus wird
# ---------------------------------------------------------------------------

def _klasse(html: str) -> str:
    treffer = re.search(r'class="([^"]*)"', html)
    assert treffer, html
    return treffer.group(1)


def test_ein_friese_ohne_zuordnung_bleibt_blau():
    aus = _node("console.log(makeAircraftIcon(0, false, false).html);")
    assert "aircraft-marker-bruegge" not in aus
    assert "aircraft-marker-fremd" not in aus


def test_ein_zugeordneter_friese_wird_tuerkis():
    aus = _node("console.log(makeAircraftIcon(0, false, true).html);")
    assert "aircraft-marker-bruegge" in aus


def test_fremdverkehr_ohne_zuordnung_behaelt_den_weissen_saum():
    aus = _node("console.log(makeAircraftIcon(0, true, false).html);")
    assert "aircraft-marker-fremd" in aus
    assert "aircraft-marker-fremd-sim" not in aus


def test_zugeordneter_fremdverkehr_bekommt_den_tuerkisen_saum():
    aus = _node("console.log(makeAircraftIcon(0, true, true).html);")
    assert "aircraft-marker-fremd" in aus
    assert "aircraft-marker-fremd-sim" in aus


def test_fremdverkehr_wird_nie_tuerkis_eingefaerbt():
    """Die FLAECHE bleibt dunkel, auch bei Zuordnung. Faerbte man sie, saehe ein fremdes
    Flugzeug aus wie ein Friese -- und die Farbe truege zwei Bedeutungen zugleich."""
    aus = _node("console.log(makeAircraftIcon(0, true, true).html);")
    assert "aircraft-marker-bruegge" not in aus


def test_die_silhouette_haengt_nicht_an_der_zuordnung():
    """Form und Groesse unterscheiden Friese von Fremdverkehr. Daran darf die Quelle nichts
    aendern -- sonst wechselt ein Flugzeug mitten im Flug seinen Typ."""
    _node("""
      const a = makeAircraftIcon(0, true, false), b = makeAircraftIcon(0, true, true);
      assert.deepStrictEqual(a.iconSize, b.iconSize);
      assert.ok(b.html.indexOf(_FLUGZEUG_PFAD_FREMD) >= 0);
      const c = makeAircraftIcon(0, false, true);
      assert.ok(c.html.indexOf(_FLUGZEUG_PFAD) >= 0);
    """)


# ---------------------------------------------------------------------------
# Zusicherungen am Quelltext -- die Stellen, an denen ein Rueckschritt still waere
# ---------------------------------------------------------------------------

def test_die_zuordnung_wird_am_eintrag_festgehalten():
    """Nur in `_verkehrZusammenfuehren` sind Sim-Eintrag und VATSIM-Partner zugleich bekannt.
    Aus `_key` allein ist es spaeter nicht mehr abzulesen: Ein reiner VATSIM-Eintrag traegt
    dort denselben Wert."""
    block = INDEX[INDEX.index("function _verkehrZusammenfuehren("):]
    block = block[:block.index("\n}\n")]
    assert "_zugeordnet = true" in block


def _eigen_zweige():
    """Der Rumpf von `_eigenesFlugzeugZeichnen`, getrennt in den Online- und den
    Offline-Teil. Die Grenze ist der Kommentar, der den zweiten einleitet."""
    block = INDEX[INDEX.index("function _eigenesFlugzeugZeichnen("):]
    block = block[:block.index("\n}\n")]
    grenze = "// Offline (oder noch nicht im VATSIM-Strom): eigener Marker."
    assert grenze in block, "Grenze zwischen den beiden Zweigen nicht gefunden"
    i = block.index(grenze)
    return block[:i], block[i:]


def test_online_ist_das_eigene_flugzeug_tuerkis():
    """Beide Hälften der Farbaussage treffen zu: Der Punkt kommt aus dem Simulator, und dass
    dieser Marker überhaupt existiert, heißt, dass VATSIM den Piloten kennt.

    `_punktIstSekundengenau` allein genügt hier nicht: `updateMap` legt den Marker an, bevor
    der Simulator sich meldet, und rührt ihn danach nicht mehr an (`!demSim`). Die Farbe muss
    also aus `_eigenesFlugzeugZeichnen` kommen — und der Merker MIT in die Bedingung, sonst
    bliebe ein geradeaus fliegendes Flugzeug blau.
    """
    online, _ = _eigen_zweige()
    assert "makeAircraftIcon(hdg, false, true)" in online
    assert "_fsGenau !== true" in online


def test_offline_bleibt_das_eigene_flugzeug_blau():
    """Der eine Fall, in dem die beiden Hälften auseinanderfallen (Nutzer-Wahl 15.09.2026).

    Türkis sagt „sekundengenau" UND „es steht fest, wer das ist". Ohne VATSIM gibt es keinen
    Eintrag in `liveData`, kein Rufzeichen, keine Identität — das Symbol heißt wörtlich „DEIN
    FLUGZEUG" und sonst nichts. Ein türkiser Punkt neben türkisen Nachbarn behauptete eine
    Zuordnung, die es nicht gibt.
    """
    _, offline = _eigen_zweige()
    assert "makeAircraftIcon(hdg)" in offline
    assert "makeAircraftIcon(hdg, false, true)" not in offline


def test_offline_greift_die_regel_von_selbst_nicht():
    """Der dritte Weg in `_punktIstSekundengenau` hängt an `_meinCallsign()`, und das kommt
    über `_meinLiveEintrag()` aus `liveData`. Wer nicht auf VATSIM steht, steht dort nicht —
    es braucht also keine zweite Bedingung, die den Offline-Fall ausschließt.

    Gebunden, weil die Kette lang und der Zusammenhang nicht offensichtlich ist: Zöge jemand
    `_meinCallsign()` auf eine andere Quelle um, fiele das hier auf und nicht erst im Flug.
    """
    block = INDEX[INDEX.index("function _meinLiveEintrag("):]
    block = block[:block.index("\n}")]
    assert "liveData" in block
    assert "_meineCid == null" in block


def test_der_saum_wechselt_auch_ohne_kursaenderung():
    """Ein Flugzeug, das nur VATSIM kennt, behaelt beim spaeteren Auftauchen im Simulator
    seinen Schluessel. Derselbe Marker wechselt also die Zuordnung, ohne dass sich der Kurs
    ruehren muss -- ohne den Merker in der Bedingung bliebe der Saum weiss."""
    block = INDEX[INDEX.index("function _verkehrZeichnen("):]
    block = block[:block.index("\n}\n")]
    assert "_fsZugeordnet !== zugeordnet" in block
    assert "makeAircraftIcon(hdg, true, zugeordnet)" in block


def test_der_tuerkise_saum_ist_im_stylesheet_erklaert():
    assert ".aircraft-marker-fremd-sim" in INDEX
    farbe = re.search(r"\.aircraft-marker-fremd-sim\s*\{[^}]*drop-shadow\([^)]*"
                      r"rgba\((\d+),(\d+),(\d+)", INDEX)
    assert farbe, "kein Saum-Farbwert gefunden"
    r, g, b = (int(farbe.group(i)) for i in (1, 2, 3))
    # Tuerkis heisst hier: Gruen und Blau deutlich ueber Rot, und beide nah beieinander.
    assert g > r + 60 and b > r + 60, (r, g, b)
    assert abs(g - b) < 40, (r, g, b)
    # Und hell genug, um seinen Zweck zu erfuellen: das dunkle Symbol von einer dunklen
    # Karte abzuheben. Der weisse Vorgaenger lag bei 255.
    assert g > 200 and b > 200, (r, g, b)


def test_die_saum_regel_steht_hinter_der_des_fremdverkehrs():
    """Gleiche Spezifitaet, also entscheidet die Reihenfolge. Stuende sie davor, gewaenne der
    weisse Saum aus `.aircraft-marker-fremd` und die Aenderung waere wirkungslos -- ohne dass
    irgendwo ein Fehler erschiene."""
    assert INDEX.index(".aircraft-marker-fremd-sim {") > INDEX.index(".aircraft-marker-fremd {")


def test_das_kniebrett_hat_seine_eigene_legendenzeile():
    """Die Zeile der Website erklaert die FriesenBruegge und verlinkt sie; im Kniebrett ist
    sie ausgeblendet, weil der Link dort ins Leere fuehrt. Ohne eine eigene Zeile stuende die
    Farbe dort voellig unerklaert."""
    assert "karten-legende-sim" in INDEX
    assert "html.vr-panel .karten-legende > li.karten-legende-sim { display: flex; }" in INDEX
    assert "html.vr-panel .karten-legende-bruegge { display: none; }" in INDEX
