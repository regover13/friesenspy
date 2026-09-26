# -*- coding: utf-8 -*-
"""Die Zuordnung Simulator ↔ VATSIM im Kniebrett, als VERHALTEN geprüft (#47, 26.09.2026).

Bis hierhin prüften die Tests zur Zuordnung nur, ob bestimmte Zeilen im Quelltext stehen. Hier
laufen die echten Funktionen aus `index.html` in Node, mit einer eingefrorenen Uhr, und jedes
Szenario ist ein Fall aus dem Betrieb oder aus der Besprechung vom 26.09.2026:

* These 14 — Reiner flog in den USA und stand trotzdem auf Engelhards Kniebrett.
* These 16 — ein Aussetzer der Sim-Liste löschte alle Zuordnungen.
* These 17 — die geparkte VJH3RX hielt das fliegende Flugzeug von FRS111N fest.
* These 18 — ein Friese, dessen eigenes Kniebrett meldet, ist ein sicherer Anker.

Beschluss: docs/superpowers/specs/2026-09-26-bruegge-kennung-und-zuordnung-design.md
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
INDEX = (WURZEL / "app" / "static" / "index.html").read_text(encoding="utf-8")
_NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not _NODE, reason="node fehlt")


def _funktion(name: str) -> str:
    m = re.search(rf"^(async )?function {re.escape(name)}\(", INDEX, flags=re.M)
    assert m, f"function {name} fehlt"
    return INDEX[m.start():INDEX.index("\n}\n", m.start()) + 3]


# Der Block mit Zustand und Konstanten der Zuordnung: von `_simVerkehr` bis vor
# `_verkehrZusammenfuehren`. So kommen neue Zustände automatisch mit, solange sie dort stehen.
_BLOCK = INDEX[INDEX.index("let _simVerkehr = null;"):INDEX.index("function _verkehrZusammenfuehren()")]

_FUNKTIONEN = [
    "_verkehrZusammenfuehren", "_verkehrKandidaten", "_paarungPlausibel", "_paarungMaxM",
    "_paarungMaxFt", "_simSinkrate", "_simHoehenSpurFortschreiben", "_vatsimFinden",
    "_friesenAlsKandidaten", "_jetztGerechnet", "_paarungenAufraeumen",
]

_STUBS = r"""
let _jetzt = 1000000000;
Date.now = () => _jetzt;
function _hav(a, b, c, d) {
  const R = 6371000, r = x => x * Math.PI / 180;
  const h = Math.sin(r(c - a) / 2) ** 2 + Math.cos(r(a)) * Math.cos(r(c)) * Math.sin(r(d - b) / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
const L = { latLng: (a, b) => ({ lat: a, lng: b, distanceTo(p) {
  const q = Array.isArray(p) ? { lat: p[0], lng: p[1] } : p;
  return _hav(this.lat, this.lng, q.lat, q.lng); } }) };
let liveData = [];
let _meineCid = null;
let _simPos = null;
const _positionsRoh = {};
const _SIM_POS_MAX_ALTER_MS = 10000;
function _kbVorratMerken() {}
function _zuordnungDiagnose() {}
// Szenario-Helfer: Positionen als Meter nach Norden/Osten von einem festen Punkt.
const B = 53.5, O = 8.0;
function nord(m) { return B + m / 111320; }
function ost(m) { return O + m / (111320 * Math.cos(B * Math.PI / 180)); }
function sim(liste) { _simVerkehr = { ts: _jetzt, liste: liste }; if (liste.length) _simVerkehrLetzteMitInhalt = _jetzt; }
function vat(liste) { _vatsimVerkehr = { gemessenTs: _jetzt, liste: liste }; }
function takt(sek) { _jetzt += (sek || 1) * 1000; return _verkehrZusammenfuehren(); }
function partner(id) { return _paarungen[id] ? _paarungen[id].cs : null; }
"""


def _lauf(szenario: str):
    quelle = "\n".join([_STUBS, _BLOCK] + [_funktion(n) for n in _FUNKTIONEN]
                       + [_funktion(n) for n in _extra()] + [szenario])
    erg = subprocess.run([_NODE, "-e", quelle], capture_output=True, text=True, timeout=30)
    assert erg.returncode == 0, erg.stderr
    return json.loads(erg.stdout.strip().splitlines()[-1])


def _extra():
    """Hilfsfunktionen, die die Umsetzung vom 26.09. dazubringt -- nur, wenn es sie gibt."""
    namen = ["_bewegungWiderspricht", "_simBewegungFortschreiben", "_ankerMerken",
             "_ankerZuordnen"]
    return [n for n in namen if re.search(rf"^function {n}\(", INDEX, flags=re.M)]


# --- These 14: der Ausschluss braucht eine Entfernungsgrenze -----------------------------

def test_ein_friese_in_den_usa_bekommt_kein_flugzeug_ueber_der_nordsee():
    """Engelhard hatte Reiner auf seinem Kniebrett, obwohl Reiner in den USA flog: Übrig waren
    genau ein Sim-Flugzeug und genau ein Friese -- und der Ausschluss prüfte keinen Abstand."""
    erg = _lauf("""
      liveData = [{ cid: 999, callsign: 'FRS999', latitude: 40.0, longitude: -75.0,
                    altitude: 2000, groundspeed: 110, aircraft: 'C172' }];
      vat([]);
      sim([{ id: 5, lat: nord(0), lon: ost(0), alt: 2000, hdg: 90, gs: 110, cs: '' }]);
      takt(1);
      console.log(JSON.stringify(partner(5)));
    """)
    assert erg is None


def test_der_ausschluss_ordnet_in_der_naehe_weiter_zu():
    """Wofür er gebaut ist, geht weiter: Zwei Flugzeuge, zwei Verbindungen. Das eine ist klar,
    das andere lag zwischen beiden -- nach dem ersten bleibt für das zweite nur eine übrig."""
    erg = _lauf("""
      vat([{ cs: 'XAA', lat: nord(0), lon: ost(0), alt: 500, hdg: 0, gs: 0 },
           { cs: 'XBB', lat: nord(250), lon: ost(0), alt: 500, hdg: 0, gs: 0 }]);
      sim([{ id: 2, lat: nord(100), lon: ost(0), alt: 500, hdg: 0, gs: 0, cs: '' },
           { id: 1, lat: nord(0), lon: ost(0), alt: 500, hdg: 0, gs: 0, cs: '' }]);
      takt(1);
      console.log(JSON.stringify([partner(1), partner(2)]));
    """)
    assert erg == ["XAA", "XBB"]


# --- These 16: Zuordnungen überstehen kurze Aussetzer ------------------------------------

_GEPAART = """
  vat([{ cs: 'XAA', lat: nord(0), lon: ost(0), alt: 500, hdg: 0, gs: 0 }]);
  sim([{ id: 1, lat: nord(0), lon: ost(0), alt: 500, hdg: 0, gs: 0, cs: '' },
       { id: 9, lat: nord(20000), lon: ost(0), alt: 3000, hdg: 0, gs: 120, cs: '' }]);
  takt(1);
"""


def test_eine_veraltete_sim_liste_loescht_keine_zuordnung():
    """Hängt der Simulator 10 s, galt die Liste als leer -- und alle Zuordnungen waren weg."""
    erg = _lauf(_GEPAART + """
      const vorher = partner(1);
      takt(15);                       // keine neue Liste: veraltet
      const waehrend = partner(1);
      sim([{ id: 1, lat: nord(0), lon: ost(0), alt: 500, hdg: 0, gs: 0, cs: '' }]);
      takt(1);
      console.log(JSON.stringify([vorher, waehrend, partner(1)]));
    """)
    assert erg == ["XAA", "XAA", "XAA"]


def test_ein_fehlendes_flugzeug_behaelt_seine_zuordnung_dreissig_sekunden():
    erg = _lauf(_GEPAART + """
      sim([{ id: 9, lat: nord(20000), lon: ost(0), alt: 3000, hdg: 0, gs: 120, cs: '' }]);
      takt(1);
      const kurz = partner(1);
      takt(20); sim(_simVerkehr.liste);
      const zwanzig = partner(1);
      takt(12); sim(_simVerkehr.liste); takt(1);
      console.log(JSON.stringify([kurz, zwanzig, partner(1)]));
    """)
    assert erg == ["XAA", "XAA", None]


def test_waehrend_der_frist_nimmt_kein_anderes_flugzeug_den_partner():
    erg = _lauf(_GEPAART + """
      // Flugzeug 1 fehlt, dafür steht Flugzeug 3 auf fast derselben Stelle.
      sim([{ id: 3, lat: nord(5), lon: ost(0), alt: 500, hdg: 0, gs: 0, cs: '' },
           { id: 9, lat: nord(20000), lon: ost(0), alt: 3000, hdg: 0, gs: 120, cs: '' }]);
      takt(1);
      console.log(JSON.stringify([partner(1), partner(3)]));
    """)
    assert erg == ["XAA", None]


# --- These 17: ein stehender Partner hält kein bewegtes Flugzeug -------------------------

def test_die_geparkte_verbindung_haelt_das_fliegende_flugzeug_nicht_fest():
    """VJH3RX stand auf VATSIM mit 0 kt, das Flugzeug im Simulator flog mit 119 kt. Die Grenze
    kam aus der Sim-Geschwindigkeit (über 5 km) -- also hielt die Zuordnung."""
    erg = _lauf("""
      vat([{ cs: 'VJH3RX', lat: nord(0), lon: ost(0), alt: 258, hdg: 0, gs: 0 }]);
      sim([{ id: 1, lat: nord(10), lon: ost(0), alt: 258, hdg: 0, gs: 0, cs: '' }]);
      takt(1);
      const anfangs = partner(1);
      let m = 10, alt = 258;
      for (let t = 0; t < 45; t++) {             // 45 s mit 119 kt (61 m/s) davon
        m += 61; alt += 12;
        sim([{ id: 1, lat: nord(m), lon: ost(0), alt: alt, hdg: 0, gs: 119, cs: '' }]);
        takt(1);
      }
      console.log(JSON.stringify([anfangs, partner(1)]));
    """)
    assert erg == ["VJH3RX", None]


def test_der_echte_partner_rollt_mit_und_bleibt():
    """Die Gegenprobe: Zeigt VATSIM die Bewegung binnen der Frist, bleibt die Zuordnung."""
    erg = _lauf("""
      vat([{ cs: 'XAA', lat: nord(0), lon: ost(0), alt: 258, hdg: 0, gs: 0 }]);
      sim([{ id: 1, lat: nord(0), lon: ost(0), alt: 258, hdg: 0, gs: 0, cs: '' }]);
      takt(1);
      let m = 0;
      for (let t = 0; t < 60; t++) {
        m += 8;                                  // rollt mit 15 kt
        sim([{ id: 1, lat: nord(m), lon: ost(0), alt: 258, hdg: 0, gs: 15, cs: '' }]);
        if (t === 25) vat([{ cs: 'XAA', lat: nord(m - 200), lon: ost(0), alt: 258, hdg: 0, gs: 15 }]);
        if (t > 25 && t % 15 === 0) vat([{ cs: 'XAA', lat: nord(m - 200), lon: ost(0), alt: 258, hdg: 0, gs: 15 }]);
        takt(1);
      }
      console.log(JSON.stringify(partner(1)));
    """)
    assert erg == "XAA"


def test_ein_laenger_bewegtes_flugzeug_bekommt_keine_stehende_verbindung():
    """Auch nicht bei der Erstzuordnung: Ein Flugzeug, das seit über 35 s fliegt, ist nicht die
    Verbindung, die auf VATSIM seit Minuten steht."""
    erg = _lauf("""
      vat([]);
      let m = 0;
      for (let t = 0; t < 40; t++) {
        m += 51;
        sim([{ id: 7, lat: nord(m), lon: ost(0), alt: 1500, hdg: 0, gs: 100, cs: '' }]);
        takt(1);
      }
      vat([{ cs: 'PARKT', lat: nord(m + 800), lon: ost(0), alt: 1400, hdg: 0, gs: 0 }]);
      m += 51;
      sim([{ id: 7, lat: nord(m), lon: ost(0), alt: 1500, hdg: 0, gs: 100, cs: '' }]);
      takt(1);
      console.log(JSON.stringify(partner(7)));
    """)
    assert erg is None


# --- These 18: der Login-Anker ------------------------------------------------------------

_ANKER = """
  liveData = [{ cid: 111, callsign: 'FRS111N', latitude: nord(-900), longitude: ost(0),
                altitude: 900, groundspeed: 90, aircraft: 'C172' }];
  vat([{ cs: 'VJH3RX', lat: nord(120), lon: ost(0), alt: 900, hdg: 0, gs: 0 }]);
"""


def test_ein_friese_mit_eigenem_kniebrett_ist_ein_sicherer_anker():
    """Sein Kniebrett meldet seine Sim-Position mit Login (`q: 'e'`). Das Sim-Flugzeug genau
    dort ist er -- auch wenn eine fremde Verbindung auf VATSIM näher zu stehen scheint."""
    erg = _lauf(_ANKER + """
      sim([{ id: 1, lat: nord(0), lon: ost(0), alt: 900, hdg: 0, gs: 90, cs: '' }]);
      _ankerMerken([{ cid: 111, lat: nord(0), lon: ost(0), alt: 900, gs: 90, q: 'e' }]);
      takt(1);
      console.log(JSON.stringify(partner(1)));
    """)
    assert erg == "FRS111N"


def test_der_anker_haengt_eine_falsche_zuordnung_um():
    erg = _lauf(_ANKER + """
      sim([{ id: 1, lat: nord(100), lon: ost(0), alt: 900, hdg: 0, gs: 0, cs: '' }]);
      takt(1);
      const vorher = partner(1);
      _ankerMerken([{ cid: 111, lat: nord(100), lon: ost(0), alt: 900, gs: 0, q: 'e' }]);
      takt(1);
      console.log(JSON.stringify([vorher, partner(1)]));
    """)
    assert erg == ["VJH3RX", "FRS111N"]


def test_eine_unbewaehrte_bruegge_ist_kein_anker():
    """`b` ohne die Angabe „bewährt“ ist eine Zuordnung des Servers über die Position -- nicht
    mehr als das, was das Kniebrett selbst kann."""
    erg = _lauf(_ANKER + """
      sim([{ id: 1, lat: nord(0), lon: ost(0), alt: 900, hdg: 0, gs: 90, cs: '' }]);
      _ankerMerken([{ cid: 111, lat: nord(0), lon: ost(0), alt: 900, gs: 90, q: 'b' }]);
      takt(1);
      const ohne = partner(1);
      console.log(JSON.stringify(ohne));
    """)
    assert erg != "FRS111N"


def test_ein_alter_anker_wirkt_nicht_mehr():
    erg = _lauf(_ANKER + """
      _ankerMerken([{ cid: 111, lat: nord(0), lon: ost(0), alt: 900, gs: 90, q: 'e' }]);
      takt(10);
      sim([{ id: 1, lat: nord(0), lon: ost(0), alt: 900, hdg: 0, gs: 90, cs: '' }]);
      takt(1);
      console.log(JSON.stringify(partner(1)));
    """)
    assert erg != "FRS111N"


def test_der_eigene_anker_zaehlt_nicht():
    erg = _lauf(_ANKER + """
      _meineCid = 111;
      sim([{ id: 1, lat: nord(0), lon: ost(0), alt: 900, hdg: 0, gs: 90, cs: '' }]);
      _ankerMerken([{ cid: 111, lat: nord(0), lon: ost(0), alt: 900, gs: 90, q: 'e' }]);
      takt(1);
      console.log(JSON.stringify(partner(1)));
    """)
    assert erg != "FRS111N"


def test_der_strom_wird_im_kniebrett_fuer_die_anker_gelesen():
    """Die Anzeige bleibt beim Sim-Matching (v14.45.0), die Anker kommen trotzdem an."""
    rumpf = _funktion("_brueggeStromEinarbeiten")
    i_anker = rumpf.index("_ankerMerken(")
    i_panel = rumpf.index("if (_PANEL_MODUS) return;")
    assert i_anker < i_panel


def test_ein_anker_ohne_eindeutiges_flugzeug_haelt_nicht_mehr():
    """Fable 12: Findet der Anker in diesem Takt kein klares Flugzeug mehr, darf er die
    Zuordnung nicht an Plausibilität und Bewegung vorbei festhalten."""
    erg = _lauf(_ANKER + """
      sim([{ id: 1, lat: nord(0), lon: ost(0), alt: 900, hdg: 0, gs: 90, cs: '' }]);
      _ankerMerken([{ cid: 111, lat: nord(0), lon: ost(0), alt: 900, gs: 90, q: 'e' }]);
      takt(1);
      const vorher = _paarungen[1] && _paarungen[1].anker;
      // Der Anker meldet jetzt weit weg -- kein Flugzeug passt mehr zu ihm.
      _ankerMerken([{ cid: 111, lat: nord(50000), lon: ost(0), alt: 900, gs: 90, q: 'e' }]);
      sim([{ id: 1, lat: nord(46), lon: ost(0), alt: 900, hdg: 0, gs: 90, cs: '' }]);
      takt(1);
      console.log(JSON.stringify([vorher != null, _paarungen[1] ? _paarungen[1].anker != null : null]));
    """)
    assert erg == [True, False]
