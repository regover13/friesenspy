"""Hinweis auf ein veraltetes Kniebrett-Paket (v13.6.4).

Die Seite kommt vom Server und ist immer aktuell -- die Hülle im Community-Ordner nicht. Bis
hierher liess sich von aussen überhaupt nicht erkennen, welches Paket dort liegt; ein
veraltetes fiel erst auf, wenn etwas fehlte (in 1.5.0/1.6.0 blieb der Verkehr aus dem
Simulator lautlos aus -- niemand konnte das sehen).

Seit Paket 2.0.0 schickt die Hülle ihre Version im ``pong``. Ein älteres Paket schickt das
Feld gar nicht: Sein FEHLEN ist die Aussage „älter als 2.0.0", kein Fehlerfall. Genau diese
Auslegung prüfen die Tests hier -- sie ist der Kern des Verfahrens.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
INDEX = (WURZEL / "app" / "static" / "index.html").read_text(encoding="utf-8")
SHELL = (WURZEL / "msfs-panel" / "PackageSources" / "FriesenSpy" / "src"
         / "FriesenSpy.tsx").read_text(encoding="utf-8")
MANIFEST = json.loads(
    (WURZEL / "msfs-panel" / "PackageSources" / "FriesenSpy" / "manifest.json")
    .read_text(encoding="utf-8")
)

_NODE = shutil.which("node")


def _versionsvergleich_quelltext():
    """Die Konstante gehoert mit in die Scheibe -- _paketVeraltet liest sie."""
    konst = re.search(r"const _PAKET_ERSTE_MELDENDE = '[^']+';", INDEX)
    assert konst, "_PAKET_ERSTE_MELDENDE fehlt"
    start = INDEX.index("function _versionKleiner(")
    ende = INDEX.index("function _paketHinweisPruefen(")
    return konst.group(0) + "\n" + INDEX[start:ende]


def _node_lauf(treiber):
    if _NODE is None:
        pytest.skip("Node.js nicht verfuegbar")
    skript = ("'use strict';\nconst assert = require('assert');\n"
              + _versionsvergleich_quelltext() + "\n" + treiber)
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


# ---------------------------------------------------------------------------------------
#  Die Hülle meldet ihre Version
# ---------------------------------------------------------------------------------------

def test_shell_meldet_ihre_version_im_pong():
    """Ohne dieses Feld gibt es überhaupt keine Grundlage für den Hinweis."""
    stelle = SHELL.index('if (d.art === "ping")')
    rumpf = SHELL[stelle:stelle + 600]
    assert "paketVersion: PAKET_VERSION" in rumpf


def test_paketversion_stimmt_mit_dem_manifest_ueberein():
    """Der Wert steht doppelt -- im Manifest (für MSFS) und im Quelltext (zur Laufzeit
    lesbar). Laufen beide auseinander, meldet ein aktuelles Paket eine falsche Version und
    der Hinweis erscheint bei Leuten, die längst aktualisiert haben."""
    m = re.search(r'const PAKET_VERSION = "([^"]+)";', SHELL)
    assert m, "PAKET_VERSION fehlt im Quelltext der Hülle"
    assert m.group(1) == MANIFEST["package_version"], (
        f"Quelltext sagt {m.group(1)}, Manifest sagt {MANIFEST['package_version']}"
    )


def test_manifest_ist_mindestens_die_erste_meldende_fassung():
    """Vor 2.0.0 gab es das Feld nicht -- ein Manifest darunter wäre in sich widersprüchlich.

    2.0.0 ist die erste Fassung, die tatsächlich ausgeliefert wurde und ihre Version meldet.
    Ein meldendes Paket UNTERHALB dieser Schwelle würde die Schweigebedingung aushebeln:
    Alle Nichtmelder gälten dann fälschlich als aktuell. (Eine 1.10.0 war gebaut, aber nie
    veröffentlicht -- die Nummer sprang auf 2.0.0.)
    """
    teile = [int(x) for x in MANIFEST["package_version"].split(".")]
    assert teile >= [2, 0, 0], MANIFEST["package_version"]


# ---------------------------------------------------------------------------------------
#  Der Versionsvergleich
# ---------------------------------------------------------------------------------------

@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_zahlenvergleich_statt_zeichenkettenvergleich():
    """Der eigentliche Fallstrick: Als Zeichenkette ist '1.10.0' KLEINER als '1.9.0'. Ein
    naiver Vergleich hielte das neuere Paket für das ältere und meldete sich nie wieder."""
    _node_lauf("""
assert.strictEqual(_versionKleiner('1.9.0', '1.10.0'), true,  '1.9.0 < 1.10.0');
assert.strictEqual(_versionKleiner('1.10.0', '1.9.0'), false, '1.10.0 nicht < 1.9.0');
assert.strictEqual(_versionKleiner('1.10.0', '1.10.0'), false, 'gleich ist nicht kleiner');
assert.strictEqual(_versionKleiner('1.9', '1.9.1'), true, 'fehlende Stelle zaehlt als 0');
assert.strictEqual(_versionKleiner('2.0.0', '1.99.99'), false);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_fehlende_version_gilt_als_veraltet():
    """Der Kern des Verfahrens: Ein Paket vor 2.0.0 schickt gar nichts. Würde `null` als
    „unbekannt, also in Ruhe lassen" ausgelegt, sähe genau die Zielgruppe den Hinweis nie."""
    _node_lauf("""
assert.strictEqual(_paketVeraltet(null, '2.0.0'), true, 'keine Meldung = altes Paket');
assert.strictEqual(_paketVeraltet('2.0.0', '2.0.0'), false);
assert.strictEqual(_paketVeraltet('1.9.0', '2.0.0'), true);
// Ohne Vergleichswert vom Server gibt es keine Aussage -- lieber schweigen als raten.
assert.strictEqual(_paketVeraltet(null, null), false);
assert.strictEqual(_paketVeraltet('1.2.0', null), false);
console.log('OK');
""")


@pytest.mark.skipif(_NODE is None, reason="Node.js nicht verfuegbar")
def test_schweigt_solange_noch_kein_meldendes_paket_ausgeliefert_wird():
    """Der Fall vom 16.08.2026: Im Repo stand die neue Fassung bereits, ausgeliefert war 1.9.0
    (das Paket wird von Hand hinterlegt, nicht vom Deploy gebaut).

    Dann meldet auch das AKTUELLE Paket keine Version -- eine fehlende Meldung sagt also
    nichts. Ohne diese Bedingung forderte der Hinweis Leute auf, auf genau die Fassung zu
    wechseln, die sie bereits installiert haben.
    """
    _node_lauf("""
assert.strictEqual(_paketVeraltet(null, '1.9.0'), false, 'darf noch nicht meckern');
assert.strictEqual(_paketVeraltet(null, '2.0.0'), true, 'ab der meldenden Fassung schon');
assert.strictEqual(_paketVeraltet(null, '2.1.0'), true);
// Wer meldet, wird immer verglichen -- unabhaengig davon, was ausgeliefert wird.
assert.strictEqual(_paketVeraltet('2.0.0', '1.9.0'), false);
console.log('OK');
""")


# ---------------------------------------------------------------------------------------
#  Die Anzeige
# ---------------------------------------------------------------------------------------

def test_hinweis_ist_kein_glocken_ereignis():
    """Bewusste Entscheidung: Die Glocke bleibt dem vorbehalten, was andere Leute tun. Eine
    Software-Meldung dazwischen verbrauchte die Aufmerksamkeit, die dort gebraucht wird."""
    stelle = INDEX.index("function _paketHinweisPruefen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_panelDiag" not in rumpf
    assert "notify" not in rumpf.lower()
    assert "panel-paket-hinweis" in rumpf


def test_wegklicken_wird_je_fassung_gemerkt():
    """Ohne den Merker stünde der Hinweis nach JEDEM Sim-Neustart erneut da -- genau der
    Einwand, der gegen die Glocke sprach. Er liegt beim Server, weil im Kniebrett kein
    Browser-Speicher einen Neustart übersteht (s. docs/efb-panel-debugging.md)."""
    stelle = INDEX.index("function _paketHinweisWeg(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_prefSchreib(_PAKET_HINWEIS_KEY, _paketAktuell)" in rumpf

    stelle = INDEX.index("function _paketHinweisPruefen(")
    pruef = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_prefLies(_PAKET_HINWEIS_KEY) === _paketAktuell" in pruef, \
        "Der Merker wird geschrieben, aber nie gelesen"


def test_entscheidung_faellt_erst_nach_den_merkern():
    """Sonst blitzt der Hinweis bei jedem Start kurz auf, bevor klar ist, dass er für diese
    Fassung längst weggeklickt wurde."""
    stelle = INDEX.index("function _paketHinweisPruefen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_prefsPromise.then(" in rumpf
    assert rumpf.index("_prefsPromise.then(") < rumpf.index("_prefLies(_PAKET_HINWEIS_KEY)")


def test_schonfrist_gegen_den_wettlauf():
    """Antwortet /api/efb-package vor dem pong, sähe ein topaktuelles Paket kurz wie ein
    veraltetes aus."""
    stelle = INDEX.index("fetch('/api/efb-package')")
    rumpf = INDEX[stelle:stelle + 500]
    assert "setTimeout(_paketHinweisPruefen, _PAKET_WARTEN_MS)" in rumpf
    assert "_paketHinweisPruefen();" not in rumpf, "sofortige Entscheidung erzeugt den Wettlauf"
    m = re.search(r"const _PAKET_WARTEN_MS = (\d+);", INDEX)
    assert m and int(m.group(1)) >= 2000, "Schonfrist zu kurz fuer den Handshake"


def test_kein_mal_zeichen_im_kniebrett():
    """Coherent GT hat für UI-Zeichen keinen Font-Fallback -- ein `×` wäre dort ein leeres
    Kästchen (s. docs/efb-panel-debugging.md). Geprüft wird am Markup des Knopfes, nicht per
    freier Suche: Das Zeichen steht anderswo im Dokument berechtigterweise in Prosa."""
    stelle = INDEX.index('<button type="button" onclick="_paketHinweisWeg()"')
    knopf = INDEX[stelle:INDEX.index("</button>", stelle)]
    assert "&times;" not in knopf and "×" not in knopf, knopf
    assert 'href="#icon-x"' in knopf and 'xlink:href="#icon-x"' in knopf, \
        "href allein zeichnet im Panel nichts"


def test_adresse_steht_als_text_nicht_als_link():
    """Im Tablet lässt sich nichts herunterladen -- die Adresse muss man am PC eintippen.
    Ein Klick-Ziel wäre ein leeres Versprechen."""
    stelle = INDEX.index("function _paketHinweisPruefen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "friesenspy.devprops.de/efb" in rumpf
    assert "<a " not in rumpf and "window.open" not in rumpf


def test_hinweis_verdeckt_den_neue_version_knopf_nicht():
    """Beides kann gleichzeitig zutreffen -- ein frischer Deploy und ein altes Paket."""
    def unten(klasse):
        stelle = INDEX.index("." + klasse + " {")
        block = INDEX[stelle:INDEX.index("}", stelle)]
        return int(re.search(r"bottom:\s*(\d+)px", block).group(1))
    assert unten("panel-paket-hinweis") > unten("panel-update-hint")


# ---------------------------------------------------------------------------------------
#  Der Server kennt die Paketfassung je Gerät (/api/admin/panel-devices)
# ---------------------------------------------------------------------------------------

def test_shell_meldet_die_version_beim_anmelden():
    """Ohne den Parameter erführe der Server nie, was installiert ist -- der ``pong`` geht nur
    an die Seite, nicht an uns."""
    stelle = SHELL.index("function buildPanelUrl(")
    rumpf = SHELL[stelle:SHELL.index("\n}", stelle)]
    assert '"&paket=" + encodeURIComponent(PAKET_VERSION)' in rumpf


def test_beide_seiten_nennen_dieselbe_erste_meldende_fassung():
    """Die Konstante steht zwangsläufig doppelt (JavaScript und Python). Laufen beide
    auseinander, widersprechen sich Kniebrett-Hinweis und Admin-Übersicht."""
    haupt = (WURZEL / "app" / "main.py").read_text(encoding="utf-8")
    js = re.search(r"const _PAKET_ERSTE_MELDENDE = '([^']+)';", INDEX)
    py = re.search(r'_PAKET_ERSTE_MELDENDE = "([^"]+)"', haupt)
    assert js and py, "Konstante fehlt auf einer Seite"
    assert js.group(1) == py.group(1), f"JS sagt {js.group(1)}, Python sagt {py.group(1)}"


# ---------------------------------------------------------------------------------------
#  Sperre für Pakete vor 2.0.0 (Nutzerentscheidung 03.09.2026)
# ---------------------------------------------------------------------------------------
def _sperr_block() -> str:
    stelle = INDEX.index("function _paketSperrePruefen()")
    return INDEX[stelle:INDEX.index("\n}", stelle)]


def test_die_sperre_greift_nur_bei_nachgewiesen_altem_paket():
    """Erst ab 2.0.0 legt das Paket eine Geräte-ID an; ohne sie überlebt die Anmeldung keinen
    Simulator-Neustart. Von fünf Kniebrett-Nutzern hatten drei keine Bindung.

    ENTSCHEIDEND ist, wogegen die Bedingung abgrenzt: Antwortet die Hülle GAR NICHT, sieht
    das identisch aus, hat aber eine andere Ursache (klemmender Handshake). Dann darf NICHT
    gesperrt werden -- ein Fehlalarm nimmt jemandem das ganze Kniebrett, nicht nur eine
    Funktion."""
    block = _sperr_block()
    assert "if (_panelShellDa !== true) return;" in block, \
        "ohne Antwort der Huelle gibt es keine Aussage -- dann keine Sperre"
    assert "if (_paketVersion) return;" in block, \
        "wer eine Version meldet, hat mindestens 2.0.0"
    assert "vr-panel" in block, "auf der Website darf die Sperre nie greifen"


def test_die_sperre_haengt_nicht_am_server_abruf():
    """Sie braucht die aktuelle Fassung vom Server nicht, nur die Antwort der Hülle. Hinge
    sie am Abruf, bliebe sie aus, wenn der Server einmal nicht antwortet -- und ein altes
    Paket liefe weiter."""
    wecker = INDEX.index("setTimeout(_paketSperrePruefen, _PAKET_WARTEN_MS);")
    # Der Abruf endet mit seinem .catch(); der Wecker muss DANACH stehen, also ausserhalb.
    abruf_ende = INDEX.index("}).catch(function () {});")
    horcher = INDEX.index("window.addEventListener('message', (e) => {")
    assert abruf_ende < wecker < horcher, \
        "der Wecker darf nicht im .then() des Server-Abrufs haengen"


def test_die_sperre_ist_auf_der_website_abgeschaltet():
    """`.panel-paket-sperre` ohne vr-panel steht auf display:none -- am Schreibtisch gibt es
    kein Paket, das veraltet sein könnte."""
    assert ".panel-paket-sperre { display: none; }" in INDEX
    assert "html.vr-panel .panel-paket-sperre.an { display: block; }" in INDEX


def test_die_sperre_nennt_die_adresse_als_text():
    """Im Panel gibt es kein zweites Fenster, das ein Link öffnen könnte (deshalb ist
    `target=_blank` dort überall ausgeblendet). Die Adresse muss also lesbar dastehen, damit
    man sie am PC eintippen kann."""
    stelle = INDEX.index('id="panel-paket-sperre"')
    block = INDEX[stelle:INDEX.index("</div>", stelle)]
    assert "friesenspy.devprops.de/efb" in block
    assert "<a " not in block, "kein Verweis -- im Kniebrett fuehrt er ins Leere"


def test_die_sperre_laesst_sich_nicht_wegklicken():
    """Der wegklickbare Hinweis unten links gibt es weiterhin für neuere Pakete. Die Sperre
    ist bewusst keiner: Genau das Wegklicken hat den Zustand jahrelang erhalten."""
    stelle = INDEX.index('id="panel-paket-sperre"')
    block = INDEX[stelle:INDEX.index("</div>", stelle)]
    assert "onclick" not in block and "<button" not in block
    # Umgekehrt muss der schwächere Hinweis verschwinden, wenn die Sperre greift.
    assert "hinweis.hidden = true;" in _sperr_block()
