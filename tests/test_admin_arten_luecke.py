# -*- coding: utf-8 -*-
"""Filter „Lücke in: …“ über der ARTEN-Tabelle im Admin (20.09.2026).

Nutzerfrage: *„wie kann ich hier filtern, welcher Art noch Zuordnungen fehlen?"* Der Picker bei
„Objekte anfordern" kennt nur das Gegenteil (Arten, die ÜBERALL gehen); die Tabelle unten zeigte
die Zustände je Simulator (✓ ? ✕), aber ohne jede Möglichkeit, danach zu suchen.

Die Auswahl ist reine Logik und läuft hier unter Node — ausgeführt, nicht nur gelesen.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ADMIN = (Path(__file__).resolve().parents[1] / "app" / "static" / "admin.html").read_text(
    encoding="utf-8")
_NODE = shutil.which("node")


def _quelle() -> str:
    start = ADMIN.index("function bgArtHatLuecke(")
    ende = ADMIN.index("/** Was im Filter über der Tabelle angehakt ist. */")
    return ADMIN[start:ende]


def _art(name, m20, m24, xp, status="aktiv"):
    return {"art": name, "art_status": status,
            "zustand": {"msfs2020": m20, "msfs2024": m24, "xplane12": xp}}


ARTEN = [
    _art("voll", "kann", "kann", "kann"),
    _art("nur_20_fehlt", "kann_nicht", "kann", "kann"),
    _art("nur_xp_fehlt", "kann", "kann", "kann_nicht"),
    _art("xp_ungeprueft", "kann", "kann", "ungeprueft"),
    _art("beide_fehlen", "kann_nicht", "kann", "kann_nicht"),
    _art("abgeschaltet", "kann_nicht", "kann_nicht", "kann_nicht", status="aus"),
]


def _lauf(sims, auch=False, aus=False, arten=None) -> list[str]:
    js = """
'use strict';
%s
const arten = %s;
console.log(JSON.stringify(bgArtenGefiltert(arten, %s, %s, %s).map(a => a.art)));
""" % (_quelle(), json.dumps(ARTEN if arten is None else arten), json.dumps(sims),
       json.dumps(auch), json.dumps(aus))
    p = subprocess.run([_NODE, "-e", js], capture_output=True, text=True, timeout=20)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not _NODE, reason="node fehlt")
class TestLueckenAuswahl:
    def test_ohne_haken_steht_alles_da(self):
        assert _lauf([]) == [a["art"] for a in ARTEN], \
            "ohne Haken ist der Filter aus -- auch die abgeschalteten bleiben sichtbar"

    def test_ein_simulator_zeigt_nur_seine_luecken(self):
        assert _lauf(["msfs2020"]) == ["nur_20_fehlt", "beide_fehlen"]
        assert _lauf(["xplane12"]) == ["nur_xp_fehlt", "beide_fehlen"]

    def test_mehrere_haken_sind_eine_vereinigung(self):
        """Wer eine Lücke sucht, will jede Art, der IRGENDWO etwas fehlt -- nicht nur die,
        der es in allen angehakten Simulatoren fehlt (das wäre der Picker mit umgedrehtem Vorzeichen)."""
        assert _lauf(["msfs2020", "xplane12"]) == ["nur_20_fehlt", "nur_xp_fehlt", "beide_fehlen"]

    def test_ungeprueft_ist_standardmaessig_keine_luecke(self):
        """„Zuordnung fehlt" heißt: kein Titel oder alle durchgefallen. Ein noch nicht
        belegter Titel ist zugeordnet."""
        assert "xp_ungeprueft" not in _lauf(["xplane12"])
        assert "xp_ungeprueft" in _lauf(["xplane12"], auch=True)

    def test_abgeschaltete_erscheinen_nur_auf_wunsch(self):
        assert "abgeschaltet" not in _lauf(["msfs2020", "msfs2024", "xplane12"])
        assert "abgeschaltet" in _lauf(["msfs2020", "msfs2024", "xplane12"], aus=True)

    def test_ohne_zustand_ist_es_eine_luecke(self):
        """Der Server liefert den Zustand fertig -- fehlt er, wurde etwas nicht berechnet. Das
        als „geht" zu lesen wäre die gefährliche Richtung."""
        assert _lauf(["msfs2020"], arten=[{"art": "x", "art_status": "aktiv"}]) == ["x"]


class TestEinbau:
    def test_der_filter_steht_ueber_der_arten_tabelle(self):
        kopf = ADMIN.index('id="bg-a-luecke"')
        tabelle = ADMIN.index('<tbody id="bg-arten">')
        assert kopf < tabelle
        for sim in ("msfs2020", "msfs2024", "xplane12"):
            assert f'data-luecke="{sim}"' in ADMIN
        assert 'id="bg-a-luecke-was"' in ADMIN and 'id="bg-a-luecke-aus"' in ADMIN

    def test_die_tabelle_zeichnet_die_gefilterte_liste_und_der_filter_ist_verdrahtet(self):
        z = ADMIN.index("function bgArtenZeichnen()")
        koerper = ADMIN[z:ADMIN.index("function bgArtZeile(", z)]
        assert "bgArtenGefiltert(_bgArtenAlle" in koerper
        assert "zeigen.map(bgArtZeile)" in koerper and "_bgArtenAlle.map(bgArtZeile)" not in koerper
        assert "bgLueckeBedienung();" in ADMIN
