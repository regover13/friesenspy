"""Waechter gegen eine README, die dem Code hinterherlaeuft.

Die README ist das Handbuch der App. Sie stand am 05.09.2026 rund neun Monate still,
waehrend das Kniebrett (v12.0.0, ein Major-Release), vier Karten-Ebenen und das
Muster-Fenster dazukamen -- gemerkt hat es niemand, weil nichts es merken konnte.

Diese Tests pruefen genau die Eigenschaften, bei denen ein Rueckstand *maschinell*
feststellbar ist. Sie ersetzen nicht das Mitschreiben beim Bauen (CLAUDE.md,
"Handbuch"), sie fangen nur den Teil, der sich zaehlen laesst.

**Jede Wache wird selbst geprueft**: zu jedem Positivtest gegen die echte README gibt
es einen Negativtest mit einer kuenstlich geluecktenen Fassung. Eine Wache, von der
niemand weiss, ob sie ueberhaupt anschlaegt, ist keine.
"""
from __future__ import annotations

import pathlib

import pytest

from tests.readme_wachen import (
    ebenen_im_frontend,
    fehlende_ebenen,
    fehlende_einstellungen,
    tabs_im_frontend,
    zahlwort_der_tab_ueberschrift,
)


ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_html() -> str:
    return (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def config_py() -> str:
    return (ROOT / "app" / "config.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- Ebenen
class TestKartenEbenen:
    def test_jede_ebene_der_karte_steht_in_der_readme(self, readme, index_html):
        assert fehlende_ebenen(readme, index_html) == []

    def test_die_wache_schlaegt_an_wenn_eine_ebene_fehlt(self, readme, index_html):
        ohne = readme.replace("Meldepunkte", "…")
        assert "Meldepunkte" in fehlende_ebenen(ohne, index_html)

    def test_findet_die_ebenen_ueberhaupt(self, index_html):
        ebenen = ebenen_im_frontend(index_html)
        assert len(ebenen) >= 8 and "Sichtflugkarte" in ebenen


# --------------------------------------------------------------------- Einstellungen
class TestKonfiguration:
    def test_jede_einstellung_steht_in_der_readme(self, readme, config_py):
        assert fehlende_einstellungen(readme, config_py) == []

    def test_die_wache_schlaegt_an_wenn_eine_einstellung_fehlt(self, readme, config_py):
        ohne = readme.replace("CALLSIGN_PREFIX", "…")
        assert "CALLSIGN_PREFIX" in fehlende_einstellungen(ohne, config_py)


# ----------------------------------------------------------------------------- Tabs
class TestTabZahl:
    def test_die_ueberschrift_nennt_so_viele_tabs_wie_es_gibt(self, readme, index_html):
        assert zahlwort_der_tab_ueberschrift(readme) == len(tabs_im_frontend(index_html))

    def test_die_wache_schlaegt_an_wenn_ein_tab_dazukommt(self, readme, index_html):
        fuenf = index_html + '\n<button data-tab="wetter">Wetter</button>\n'
        assert zahlwort_der_tab_ueberschrift(readme) != len(tabs_im_frontend(fuenf))
