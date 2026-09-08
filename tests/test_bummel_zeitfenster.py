"""Zeitfenster-Anzeige eines Bummels (index.html, reine Helfer — ohne DOM).

Der Nutzer will auf einen Blick sehen, wann das Rennen SCHLIESST: Nach ``dtend`` wird ein neu
begonnener Flug nicht mehr gewertet (Gegenprobe dazu in test_bummel.py).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

_NODE = shutil.which("node")

_ANFANG = "function _bummelTagUndZeit("
_ENDE = "function renderBummelParticipants("


def _hilfsquelltext() -> str:
    """Die drei reinen Helfer aus index.html — ohne Leaflet, ohne DOM."""
    assert _ANFANG in INDEX, f"{_ANFANG!r} fehlt in index.html"
    assert "function _bummelZeitfenster(" in INDEX, "_bummelZeitfenster fehlt in index.html"
    start = INDEX.index(_ANFANG)
    return INDEX[start:INDEX.index(_ENDE, start)]


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


class TestZeitfenster:
    def test_gleicher_tag_nennt_das_datum_einmal(self):
        """Der Regelfall (Aach-Bummel 07.09.): ein Abend, zwei Uhrzeiten."""
        _node_lauf("""
        assert.strictEqual(
          _bummelZeitfenster('2026-09-07T18:00:00Z', '2026-09-07T20:00:00Z'),
          '07.09. 18:00z – 20:00z');
        console.log('OK');
        """)

    def test_ueber_mitternacht_nennt_beide_daten(self):
        """Fehlt im Kalender ein Ende, steht dtend auf Mitternacht des FOLGETAGS. Ohne das
        zweite Datum laese sich '18:00z – 00:00z' wie ein Fenster in die Vergangenheit."""
        _node_lauf("""
        assert.strictEqual(
          _bummelZeitfenster('2026-09-07T18:00:00Z', '2026-09-08T00:00:00Z'),
          '07.09. 18:00z – 08.09. 00:00z');
        console.log('OK');
        """)

    def test_einzelne_zeitpunkte_und_leer(self):
        _node_lauf("""
        assert.strictEqual(_bummelZeitfenster('2026-09-07T18:00:00Z', null), '07.09. 18:00z');
        assert.strictEqual(_bummelZeitfenster(null, '2026-09-07T20:00:00Z'), '07.09. 20:00z');
        assert.strictEqual(_bummelZeitfenster(null, null), '');
        assert.strictEqual(_bummelZeitfenster('', ''), '');
        console.log('OK');
        """)


class TestAnzeige:
    def test_zeitfenster_steht_in_der_teilnehmeransicht(self):
        start = INDEX.index("function renderBummelParticipants(")
        rumpf = INDEX[start:INDEX.index("\nfunction ", start + 10)]
        assert "_bummelZeitfenster(view.dtstart, view.dtend)" in rumpf
        assert "Zeitfenster:" in rumpf

    def test_laufendes_rennen_nennt_sein_ende(self):
        """„Rennen laeuft" ohne Endzeit beantwortet die Frage nicht, wann geschlossen wird."""
        start = INDEX.index("function renderBummelParticipants(")
        rumpf = INDEX[start:INDEX.index("\nfunction ", start + 10)]
        assert "Rennen läuft${view.dtend ? ' bis ' + _bummelNurZeit(view.dtend) : ''}" in rumpf
        assert "wer später startet, wird nicht mehr gewertet" in rumpf

    def test_landezeit_bleibt_bis_zur_enthuellung_verborgen(self):
        """Fairness: Die Teilnehmer-Tabelle zeigt nur die Startzeit, keine Landezeit."""
        start = INDEX.index("function renderBummelParticipants(")
        rumpf = INDEX[start:INDEX.index("\nfunction ", start + 10)]
        assert "<th>Start (UTC)</th>" in rumpf
        assert "Ende (UTC)" not in rumpf, "Landezeit gehoert nicht in die verdeckte Ansicht"
        assert "p.ended" not in rumpf


class TestWartestandAnzeige:
    """Nach Renn-Ende soll dastehen, WORAN der Abschluss haengt — nicht nur „warten auf
    Nachzuegler". Die Auskunft kommt aus `bummel_wartestand`, derselben Quelle, die auch die
    Enthuellung prueft."""

    def _rumpf(self) -> str:
        start = INDEX.index("function renderBummelParticipants(")
        return INDEX[start:INDEX.index("\nfunction ", start + 10)]

    def test_nennt_wer_noch_fliegt(self):
        rumpf = self._rumpf()
        assert "Abschluss wartet auf " in rumpf
        assert "_fliegen.join(', ')" in rumpf

    def test_trennt_unterwegs_von_nicht_gestartet(self):
        """Wer nie abgehoben ist, haelt den Abschluss auf, ist aber kein Nachzuegler."""
        rumpf = self._rumpf()
        assert "unterwegs: " in rumpf
        assert "nicht gestartet: " in rumpf
        assert "_w.nie_gestartet" in rumpf

    def test_nennt_den_zeitpunkt_der_erfassung(self):
        rumpf = self._rumpf()
        assert "Abschluss wartet bis Logout oder " in rumpf
        assert "zur Erfassung der Blockzeiten" in rumpf
        assert "_w.stabil_ab.slice(11, 19)" in rumpf, "hh:mm:ss, nicht nur hh:mm"

    def test_speist_sich_aus_dem_wartestand(self):
        rumpf = self._rumpf()
        assert "view.wartestand" in rumpf
        assert "warten auf Nachzügler" not in rumpf, "der unbestimmte Text ist ersetzt"
