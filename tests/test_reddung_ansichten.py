# -*- coding: utf-8 -*-
"""Die Nutzeransichten der FriesenReddung (Spec 2026-09-23).

Reine Funktionen werden in node ausgefuehrt (herausgeschnitten aus index.html), alles andere
an Bezeichnern im Code geprueft -- nie an Kommentaren.
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
README = (WURZEL / "README.md").read_text(encoding="utf-8")
_NODE = shutil.which("node")


def _funktion(name: str) -> str:
    """Den Quelltext einer Funktion auf oberster Ebene -- bis zur ersten `}` in Spalte 0."""
    m = re.search(rf"^(async )?function {re.escape(name)}\(", INDEX, flags=re.M)
    assert m, f"function {name} fehlt"
    return INDEX[m.start():INDEX.index("\n}\n", m.start()) + 3]


def _ohne_kommentare(text: str) -> str:
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def _node(quelltext: str, ausdruck: str):
    skript = quelltext + "\nconsole.log(JSON.stringify(" + ausdruck + "));"
    erg = subprocess.run([_NODE, "-e", skript], capture_output=True, text=True, timeout=20)
    assert erg.returncode == 0, erg.stderr
    return json.loads(erg.stdout.strip().splitlines()[-1])


# --- Takt und Live-Block ------------------------------------------------------------------

def test_der_live_block_steht_ueber_bummel_und_kutter():
    """Eine laufende FriesenReddung ist die Lage mit der Uhr im Nacken."""
    live = INDEX[INDEX.index('<div id="tab-live"'):INDEX.index('<div id="tab-karte"')]
    assert live.index('id="reddung-banner"') < live.index('id="bummel-banner"')


def test_der_takt_laeuft_und_haelt_einen_aussetzer_aus():
    """Review-Fokus 5: Ist die Liste kurz nicht erreichbar, bleibt alles, wie es war --
    der Block darf nicht bei jedem Netzaussetzer verschwinden."""
    rumpf = _ohne_kommentare(_funktion("_reddungTakt"))
    assert "fetch('/api/reddung/events')" in rumpf
    fang = rumpf.index("catch")
    assert rumpf.index("return", fang) < rumpf.index("_reddungBannerZeigen()")
    assert "setInterval(_reddungTakt, 30000)" in INDEX
    assert "_reddungTakt();" in _funktion("alleDatenNeuLaden")


def test_die_zustaende_stehen_vor_dem_ersten_aufruf():
    """⚠ Ein `let` hinter seinem ersten Aufruf auf oberster Ebene legt die GANZE Seite lahm
    (TDZ) -- und `node --check` findet das nicht."""
    erster_aufruf = INDEX.index("setInterval(_reddungTakt, 30000)")
    assert INDEX.index("let _reddungListe") < erster_aufruf


def test_der_live_block_stapelt_mehrere_laufende():
    """Review-Fokus 2: Zwei gleichzeitig -- beide erscheinen, nicht nur die erste."""
    rumpf = _ohne_kommentare(_funktion("_reddungBannerZeigen"))
    assert ".map(_reddungBannerBlock).join('')" in rumpf


def test_der_live_block_liest_nur_die_liste():
    """Die Liste fuehrt keine Koordinate; das Raster gehoert der Karte."""
    for name in ("_reddungBannerZeigen", "_reddungBannerBlock", "_reddungMarkenHtml"):
        assert "/raster" not in _funktion(name), name


def test_die_readme_beschreibt_den_live_block():
    abschnitt = README[README.index("## 🚨 FriesenReddung"):README.index("## 🔧 Verwaltung")]
    assert "Noch nicht zu sehen" not in abschnitt, "die alte Ankuendigung muss weg"
    assert "**Was du davon siehst:**" in abschnitt
    liste = abschnitt[abschnitt.index("**Was du davon siehst:**"):]
    assert "**Live-Ansicht:**" in liste
