"""Ausschnitt der Events-Karte gegen Ausreisser (GitHub-Issue #18).

``renderEventsMap`` sammelt jeden Trackpunkt ein und ruft ``fitBounds``. Am 04.09.2026 zog ein
Leg aus Texas die Karte in den Nordatlantik::

    sued 32,582  nord 54,207  west -97,028  ost 10,703   ->  Mitte -43,1624

Weil die Karte ``minZoom: 6`` hat, kann sie nicht weit genug herauszoomen: Sie bleibt ueber
leerem Wasser stehen, die eigentlichen Spuren liegen ausserhalb des Bildes -- und wirken, als
fehlten sie. Die Ursache (Legs ausserhalb des Zeitfensters) ist mit 14.20.4 behoben; hier
stehen die beiden Schutzschichten darunter:

* **Datenvalidierung:** ein Punkt auf genau (0, 0) ist keine Position, sondern ein fehlender
  Wert. Der bisherige Filter liess ihn durch, weil ``pt.latitude != null`` bei ``0`` wahr ist.
* **Ehrlichkeit:** passt nach dem ``fitBounds`` nicht alles ins Bild, sagt die Karte das --
  statt still eine leere Wasserflaeche zu zeigen.

Bewusst NICHT gebaut: eine Heuristik, die "Ausreisser" errät und Punkte verwirft. Eine
schlecht gewaehlte Schwelle schnitte legitime Weitstrecken ab -- das waere selbst eine
Fehlerquelle, und zwar eine unsichtbare.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

_NODE = shutil.which("node")

_ANFANG = "function _gueltigerTrackpunkt("
_ENDE = "async function renderEventsMap("


def _hilfsquelltext() -> str:
    """Die beiden reinen Helfer aus index.html -- ohne Leaflet, ohne DOM."""
    assert _ANFANG in INDEX, f"{_ANFANG!r} fehlt in index.html"
    assert _SPUREN in INDEX, f"{_SPUREN!r} fehlt in index.html"
    start = INDEX.index(_ANFANG)
    return INDEX[start:INDEX.index(_ENDE, start)]


_SPUREN = "function _spurenAusserhalb("


def _node_lauf(treiber: str) -> None:
    if _NODE is None:
        pytest.skip("Node.js nicht verfuegbar")
    skript = _hilfsquelltext() + "\nconst assert = require('assert');\n" + treiber
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


class TestNullinselVerwerfen:
    def test_punkt_auf_null_null_zaehlt_nicht(self):
        """(0, 0) liegt im Golf von Guinea und ist in einem Nordsee-Track ein fehlender Wert."""
        _node_lauf("""
        assert.strictEqual(_gueltigerTrackpunkt({ latitude: 0, longitude: 0 }), false);
        assert.strictEqual(_gueltigerTrackpunkt({ latitude: '0', longitude: '0' }), false);
        console.log('OK');
        """)

    def test_echte_position_auf_dem_aequator_bleibt(self):
        """Nur der Doppel-Nullpunkt faellt raus -- eine einzelne 0 ist eine gueltige Koordinate."""
        _node_lauf("""
        assert.strictEqual(_gueltigerTrackpunkt({ latitude: 0, longitude: 8.5 }), true);
        assert.strictEqual(_gueltigerTrackpunkt({ latitude: 53.77, longitude: 0 }), true);
        assert.strictEqual(_gueltigerTrackpunkt({ latitude: 53.77, longitude: 7.91 }), true);
        console.log('OK');
        """)

    def test_fehlende_koordinaten_zaehlen_nicht(self):
        _node_lauf("""
        assert.strictEqual(_gueltigerTrackpunkt({ latitude: null, longitude: 7.9 }), false);
        assert.strictEqual(_gueltigerTrackpunkt({ latitude: 53.7 }), false);
        assert.strictEqual(_gueltigerTrackpunkt(null), false);
        console.log('OK');
        """)

    def test_renderEventsMap_benutzt_den_filter(self):
        """Der Filter muss an der Stelle stehen, die die Punkte fuer fitBounds sammelt --
        sonst ist die Funktion da, aber wirkungslos."""
        start = INDEX.index(_ENDE)
        rumpf = INDEX[start:INDEX.index("\nfunction resetEventFlights(", start)]
        assert "_gueltigerTrackpunkt" in rumpf
        assert "pt.latitude != null" not in rumpf, (
            "alter Filter steht noch da -- er laesst (0,0) durch"
        )

    def test_track_modal_verwirft_die_nullinsel_ebenfalls(self):
        """Dieselben Rohdaten, dieselbe Falle: ein (0,0)-Punkt spannt auch die Karte der
        Einzel-Track-Ansicht ueber den halben Globus. Der Helfer gehoert an beide Stellen."""
        start = INDEX.index("async function _loadAndDrawTrack(")
        rumpf = INDEX[start:INDEX.index("\nfunction ", start + 10)]
        assert "_gueltigerTrackpunkt" in rumpf
        assert "p.latitude != null" not in rumpf


class TestAusschnittSagtBescheid:
    def test_alles_im_bild_ist_kein_fall(self):
        _node_lauf("""
        const sichtbar = { sued: 53.0, nord: 55.0, west: 6.0, ost: 10.0 };
        assert.strictEqual(_spurenAusserhalb(sichtbar, [[53.8, 7.9], [54.2, 8.6]]), false);
        console.log('OK');
        """)

    def test_punkt_ausserhalb_wird_gemeldet(self):
        """Der Texas-Fall: fitBounds wollte hin, minZoom liess es nicht zu."""
        _node_lauf("""
        const sichtbar = { sued: 40.0, nord: 55.0, west: -20.0, ost: 12.0 };
        assert.strictEqual(_spurenAusserhalb(sichtbar, [[54.2, 8.6], [32.58, -97.03]]), true);
        console.log('OK');
        """)

    def test_ohne_punkte_kein_hinweis(self):
        _node_lauf("""
        const sichtbar = { sued: 53.0, nord: 55.0, west: 6.0, ost: 10.0 };
        assert.strictEqual(_spurenAusserhalb(sichtbar, []), false);
        console.log('OK');
        """)

    def test_hinweis_element_existiert_und_startet_versteckt(self):
        assert 'id="ev-map-hinweis"' in INDEX
        marke = INDEX.index('id="ev-map-hinweis"')
        umfeld = INDEX[marke - 200:marke + 200]
        assert "hidden" in umfeld, "der Hinweis muss verborgen starten"

    def test_renderEventsMap_wertet_den_ausschnitt_nach_fitbounds_aus(self):
        start = INDEX.index(_ENDE)
        rumpf = INDEX[start:INDEX.index("\nfunction resetEventFlights(", start)]
        assert rumpf.index("fitBounds") < rumpf.index("_spurenAusserhalb"), (
            "die Pruefung muss NACH dem fitBounds stehen -- vorher steht der Ausschnitt noch nicht"
        )
        assert "ev-map-hinweis" in rumpf
