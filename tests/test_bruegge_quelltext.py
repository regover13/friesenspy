"""Prueft den C++-Quelltext der Bruegge auf die Fallstricke aus
`docs/superpowers/specs/2026-09-13-bruegge-posix-design.md`.

Fuer C++ gibt es hier keine Testsuite, und jeder dieser Funde ist "eine Zeile fehlt" --
genau das laesst sich als Text pruefen. Kommentare werden vorher entfernt: Sonst findet
die Suche die Erklaerung statt der Anweisung.
"""
import re
from pathlib import Path

BRUEGGE = Path(__file__).resolve().parent.parent / "friesenbruegge"


def quelltext(name: str) -> str:
    """Dateiinhalt ohne // - und /* */ - Kommentare."""
    roh = (BRUEGGE / name).read_text(encoding="utf-8")
    ohne_block = re.sub(r"/\*.*?\*/", " ", roh, flags=re.S)
    return re.sub(r"//[^\n]*", "", ohne_block)


def test_native_paths_ist_eingeschaltet():
    """Ohne diese Zeile liefert XPLMGetSystemPath auf macOS HFS-Pfade mit Doppelpunkten.
    Dann findet die Bruegge ihre .url-Datei nie -- der Pruefserver-Weg waere auf dem Mac tot."""
    q = quelltext("xplane/bruegge.cpp")
    assert 'XPLMEnableFeature("XPLM_USE_NATIVE_PATHS", 1)' in q


def test_native_paths_steht_vor_jedem_pfadzugriff():
    """Die Reihenfolge ist der ganze Punkt: nach dem ersten fopen waere die Zeile wirkungslos.

    Gesucht wird NUR innerhalb von XPluginStart. Ueber die ganze Datei gesucht, faende
    `q.index("ziel_laden()")` die Funktionsdefinition weiter oben statt des Aufrufs --
    der Test waere dann dauerhaft rot, ohne dass etwas kaputt waere."""
    q = quelltext("xplane/bruegge.cpp")
    block = q[q.index("PLUGIN_API int XPluginStart"):]
    feature = block.index('XPLMEnableFeature("XPLM_USE_NATIVE_PATHS"')
    for aufruf in ("ziel_laden()", "kennung_laden_oder_erzeugen()"):
        assert feature < block.index(aufruf), f"{aufruf} laeuft vor XPLMEnableFeature"


def test_json_h_rechnet_ohne_locale():
    """%f und strtod fragen LC_NUMERIC. Ein deutscher Pilot meldete sonst 52,123 --
    und laese aus der Antwort des Servers "53.5" eine 53. Gemessen am 13.09.2026."""
    q = quelltext("json.h")
    assert "strtod" not in q
    assert '"%.*f"' not in q
