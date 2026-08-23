"""Karten-Ebene "Sichtflugkarte" im Quelltext.

Die Tests binden an Deklarationen und an die Funktion, die die Entscheidung trifft -- nicht
an das blosse Vorkommen einer Zeichenkette. Sonst bestuende ein Test auch dann, wenn der
Wert nur geloggt wird.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md
"""
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(
    encoding="utf-8"
)


def test_ebene_haengt_in_der_ebenen_auswahl():
    assert "liveOverlays['Sichtflugkarte']" in INDEX


def test_vorliebe_wird_vor_der_control_gesetzt():
    """Sonst sieht die Checkbox den Zustand nie (derselbe Fallstrick wie bei OpenAIP)."""
    assert INDEX.index("_addPreferredAipKarteLayer(liveMap") < INDEX.index("liveOverlays,")


def test_daten_kommen_vom_metadaten_endpunkt():
    assert "'/api/aip-charts'" in INDEX


def test_merker_laeuft_ueber_den_server_nicht_localstorage():
    """Im Kniebrett haelt kein Browser-Speicher ueber einen Sim-Neustart."""
    assert "_prefSchreib(_AIP_KARTE_PREF_KEY" in INDEX
    assert "localStorage.getItem('friesenspy_aipkarte')" not in INDEX


def test_geschaltet_wird_nach_dem_kartenfeld():
    """Nach den Blattgrenzen zu schalten hiesse: Overlay an, waehrend das Flugzeug noch unter
    der Kopfzeile steht -- das Blatt ist rund 1,8-mal so hoch wie das Kartenfeld."""
    start = INDEX.index("function _aipKarteImFeld(")
    block = INDEX[start:start + 900]
    for feld in ("feld_sued", "feld_nord", "feld_west", "feld_ost"):
        assert feld in block, feld
    assert "_AIP_KARTE_HYSTERESE" in block


def test_platziert_wird_nach_den_blattgrenzen():
    """Das Overlay selbst nimmt die BLATTgrenzen -- gezeigt wird ja das ganze Blatt."""
    start = INDEX.index("L.imageOverlay(")
    block = INDEX[start:start + 220]
    assert "k.sued" in block and "k.nord" in block
    assert "feld_" not in block


def test_hysterese_ist_vorhanden():
    assert "const _AIP_KARTE_HYSTERESE" in INDEX


def test_attribution_traegt_das_airac_datum():
    start = INDEX.index("function _aipKarteAttribution(")
    assert "airac" in INDEX[start:start + 300]


def test_nachfuehrung_haengt_im_navi_takt():
    """Dort wird die eigene Position ohnehin jede Sekunde ausgewertet."""
    start = INDEX.index("function _naviTakt(")
    assert "_aipKarteNachfuehren(" in INDEX[start:start + 4000]


def test_festnageln_ist_verdrahtet():
    """Nicht nur eine Variable anlegen -- sie muss die Automatik auch uebersteuern."""
    start = INDEX.index("function _aipKarteNachfuehren(")
    assert "_aipKarteFest" in INDEX[start:start + 1200]
