"""FSE-Ebenen (v12.9.0)."""
import json
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
AIRPORTS = STATIC / "data" / "fse_airports_eu.json"
ZONES = STATIC / "data" / "fse_zones_eu.json"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_dateien_liegen_im_repo():
    assert AIRPORTS.exists() and ZONES.exists()


def test_europa_zuschnitt_ist_klein_genug():
    """Weltweit waeren es 17 MB. Der Europa-Ausschnitt muss unter 1 MB roh bleiben, sonst ist
    das Lazy Load die Wartezeit nicht wert."""
    assert AIRPORTS.stat().st_size < 1_000_000
    assert ZONES.stat().st_size < 1_000_000


def test_plaetze_liegen_in_europa():
    ap = json.loads(AIRPORTS.read_text(encoding="utf-8"))
    assert 2000 < len(ap) < 3000
    for icao, a in ap.items():
        assert 35 <= a["lat"] <= 72, icao
        assert -25 <= a["lon"] <= 45, icao


def test_msfs_feld_ist_bereinigt():
    """Im Rohdatensatz steht bei Plaetzen ohne MSFS-Entsprechung [None] -- eine nichtleere
    Liste mit einem None darin. Wer darauf mit truthiness prueft, haelt sie faelschlich fuer
    vorhanden (der Fehler ist bei der Auswertung schon einmal passiert)."""
    ap = json.loads(AIRPORTS.read_text(encoding="utf-8"))
    for icao, a in ap.items():
        assert isinstance(a["msfs"], list)
        assert all(x for x in a["msfs"]), f"None in msfs bei {icao}"


def test_die_inseln_sind_dabei():
    ap = json.loads(AIRPORTS.read_text(encoding="utf-8"))
    for icao in ("EDWG", "EDWY", "EDWJ", "EDWL", "EDWR", "EDWZ"):
        assert icao in ap, icao
    assert "EHOW" in ap["EDWE"]["msfs"], "Emden heisst in MSFS auch EHOW"


def test_fse_ebenen_stehen_in_der_auswahl():
    assert "liveOverlays['FSE-Plätze']" in INDEX
    assert "liveOverlays['FSE-Landeflächen']" in INDEX


def test_fse_wird_vor_der_layers_control_registriert():
    vorher = INDEX.index("_addPreferredFseLayer(liveMap")
    control = INDEX.index("liveOverlays,")
    assert vorher < control


def test_zonen_fangen_keine_klicks():
    """Die Zellen liegen flaechendeckend ueber der Karte. Waeren sie klickbar, kaeme man an
    keinen Marker und an kein Platzrunden-Popup mehr heran."""
    stelle = INDEX.index("function _fseZonenZeichnen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "interactive: false" in rumpf
    assert "fill: false" in rumpf


def test_fse_daten_werden_lazy_geholt():
    assert INDEX.count("/static/data/fse_airports_eu.json") == 1
    assert INDEX.count("/static/data/fse_zones_eu.json") == 1
    stelle = INDEX.index("function _fseLaden(")
    assert "_fseGeladen" in INDEX[stelle:stelle + 900]


def test_popup_nennt_die_msfs_entsprechung():
    """Bei 35,6 % aller Plaetze heisst der Platz im Simulator anders, bei 9,7 % gibt es ihn
    dort gar nicht. Diese Frage stellt man am konkreten Platz -- deshalb ins Popup."""
    stelle = INDEX.index("function _fsePopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "In MSFS als" in rumpf
    assert "In MSFS nicht vorhanden" in rumpf


def test_popup_meldet_gleiche_icaos_nicht_als_alternative():
    """Bei 54,7 % der Plaetze ist der MSFS-Code derselbe. 'In MSFS als: EDWG' unter der
    Ueberschrift EDWG waere Rauschen."""
    stelle = INDEX.index("function _fsePopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "!== icao" in rumpf or "!= icao" in rumpf
