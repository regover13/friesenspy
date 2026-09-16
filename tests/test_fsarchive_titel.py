# -*- coding: utf-8 -*-
"""Ein Titel endet am Anführungszeichen, nicht am Zeilenende (16.09.2026).

**Im Katalog aufgefallen**, beim Durchsehen der Fehlschläge nach dem vollständigen Prüflauf:
Vier Titel scheiterten mit ``EXCEPTION_22`` und sahen schon im Admin falsch aus —

    "Boat01 Modular Bottom Livery" ; Variation name
    "Fishing Boat White Modular" ; Variation name

Anführungszeichen und Kommentar standen mit im Namen. Der Simulator kennt so einen Container
natürlich nicht; die Fehlschläge waren echt, aber der Titel war nie einer.

**Zwei Regexe für dieselbe Sache, und einer war falsch.** ``katalog_sammeln.TITEL`` liest
korrekt bis zum schließenden Anführungszeichen; ``fsarchive.titel_aus`` hatte einen eigenen,
der bis zum Zeilenende nahm und danach nur die äußeren Anführungszeichen abstreifte:

    r"(?im)^\\s*title\\s*=\\s*(.+?)\\s*$"   ->  'Boat01 Modular Bottom Livery" ; Variation name'

Betroffen ist ausschließlich ``quelle='streamed'`` — nur dort läuft der Archivleser.

⚠ Die Lehre steht im Kern der Sache: Wer dasselbe zweimal parst, parst es irgendwann
verschieden. ``fsarchive`` nimmt jetzt denselben Ausdruck wie der Sammellauf.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "friesenbruegge"))
import fsarchive  # noqa: E402
import katalog_sammeln as ks  # noqa: E402


ZEILEN = [
    # (Zeile in der cfg, was als Titel herauskommen muss)
    ('title = "Boat01 Modular Bottom Livery" ; Variation name', "Boat01 Modular Bottom Livery"),
    ('Title="Boat01 White Modular" ; Variation name', "Boat01 White Modular"),
    ('title = "Mi-2 [passenger]" ; Variation name', "Mi-2 [passenger]"),
    ("title=Boat01", "Boat01"),
    ("title = A2A Piper PA-24-250 Comanche", "A2A Piper PA-24-250 Comanche"),
    ('  title  =  "SEAT_Mi2_Pax"  ', "SEAT_Mi2_Pax"),
]


@pytest.mark.parametrize("zeile,soll", ZEILEN)
def test_der_sammellauf_liest_richtig(zeile, soll):
    """Die Vorlage — sie war nie falsch und bleibt der Maßstab."""
    assert ks.TITEL.findall(zeile) == [soll]


@pytest.mark.parametrize("zeile,soll", ZEILEN)
def test_der_archivleser_liest_genauso(zeile, soll):
    """⚠ Der eigentliche Test: Beide müssen dasselbe liefern, sonst driften sie wieder."""
    assert fsarchive.TITEL.findall(zeile) == [soll]


def test_es_ist_derselbe_ausdruck():
    """Nicht „gleich aussehend", sondern DERSELBE — sonst ist es eine Frage der Zeit.

    Ein zweiter Ausdruck, der heute dasselbe tut, tut es nach dem nächsten Sonderfall
    nicht mehr. Genau so ist dieser Fehler entstanden.
    """
    assert fsarchive.TITEL is ks.TITEL or fsarchive.TITEL.pattern == ks.TITEL.pattern


def test_ein_kommentar_ohne_anfuehrungszeichen_bleibt_draussen():
    """`title = Boot ; das ist ein Boot` -- der Strichpunkt beendet den Wert.

    ⚠ Der Ausdruck liefert hier `'Boot '` MIT Leerzeichen; abgeschnitten wird es erst von
    `strip()` in `titel_aus`. Die erste Fassung dieses Tests prüfte den Regex allein und war
    deshalb rot, obwohl nie ein falscher Titel herauskam — geprüft gehört das Ergebnis, nicht
    der Zwischenschritt.
    """
    roh = fsarchive.TITEL.findall("title = Boot ; das ist ein Boot")
    assert [t.strip() for t in roh] == ["Boot"]
