"""Platzrunden-Datensatz und -Ebene (v12.8.0)."""
import json
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
GEOJSON = STATIC / "data" / "platzrunden_de.geojson"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_datensatz_liegt_im_repo():
    assert GEOJSON.exists(), "app/static/data/platzrunden_de.geojson fehlt"


def test_datensatz_hat_die_erwarteten_features():
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 412


def test_geschaetzte_hoehen_tragen_keine_zahl():
    """Die 147 Platzhalter stehen im Rohdatensatz als '0 ft / GND' und tragen im KML pauschal
    305 m = 1000 ft. Diese Zahl ist erfunden. Sie darf nicht als hoehe_ft durchkommen, sonst
    landet sie ueber irgendeinen Renderpfad doch im Popup."""
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    geschaetzt = [f for f in gj["features"] if f["properties"]["hoehe_geschaetzt"]]
    assert len(geschaetzt) == 147
    assert all(f["properties"]["hoehe_ft"] is None for f in geschaetzt)


def test_echte_hoehen_haben_alle_einen_wert():
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    echt = [f for f in gj["features"] if not f["properties"]["hoehe_geschaetzt"]]
    assert len(echt) == 265
    assert all(isinstance(f["properties"]["hoehe_ft"], int) for f in echt)


def test_polygonringe_sind_geschlossen():
    """Leaflet zeichnet auch offene Ringe, schliesst sie aber optisch selbst -- ein offener
    Ring faellt deshalb erst auf, wenn jemand die Geometrie weiterverarbeitet."""
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    for f in gj["features"]:
        if f["geometry"]["type"] == "Polygon":
            ring = f["geometry"]["coordinates"][0]
            assert ring[0] == ring[-1], f"offener Ring bei {f['properties']['icao']}"


def test_korrigierte_icaos_sind_drin():
    """Vier ICAO-Codes waren im Rohdatensatz falsch zugeordnet (Geometrie richtig, Verknuepfung
    falsch). Die Korrektur ist in den Daten, nicht im Frontend -- also hier pruefen."""
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    korrigiert = {f["properties"]["icao"]: f["properties"].get("icao_original")
                  for f in gj["features"] if f["properties"].get("icao_original")}
    assert korrigiert == {"EDLH": "EDFJ", "EDBM": "EDBC", "EDFS": "EDQT", "EDRZ": "EDRP"}


def test_ebene_wird_vor_der_layers_control_registriert():
    """Die OpenAIP-Falle, dritte Auflage: Ein nach dem Bau der Control hinzugefuegter Layer
    feuert keines der Ereignisse, auf die sie lauscht -- der Haken zeigt dann dauerhaft den
    falschen Zustand. Die Control unabhaengig ueber ihren eindeutigen Nachbarn finden, nicht
    ueber INDEX.index(sub, start): das liefert per Definition immer einen Wert >= start und
    koennte gar nicht fehlschlagen."""
    vorher = INDEX.index("_addPreferredPlatzrundenLayer(liveMap")
    control = INDEX.index("liveOverlays,")
    assert vorher < control


def test_ebene_steht_in_der_ebenen_auswahl():
    assert "liveOverlays['Platzrunden']" in INDEX


def test_datensatz_wird_erst_beim_einschalten_geholt():
    """28 KB gzip rechtfertigen keinen Abruf beim Seitenaufbau -- die meisten Besucher
    schalten die Ebene nie ein."""
    stelle = INDEX.index("function _platzrundenLaden(")
    assert "fetch(" in INDEX[stelle:stelle + 800]
    # der fetch darf nirgends beim Aufbau stehen, nur in dieser Funktion
    assert INDEX.count("/static/data/platzrunden_de.geojson") == 1


def test_datensatz_wird_nur_einmal_geholt():
    """Ein- und Ausschalten der Ebene darf den Abruf nicht wiederholen."""
    stelle = INDEX.index("function _platzrundenLaden(")
    rumpf = INDEX[stelle:stelle + 800]
    assert "_platzrundenGeladen" in rumpf


def test_zoom_schwelle_steht_genau_einmal():
    assert INDEX.count("_PLATZRUNDEN_MIN_ZOOM =") == 1
    assert INDEX.count("_PLATZRUNDEN_MIN_ZOOM") >= 2


def test_popup_verzweigt_auf_das_flag_nicht_auf_das_label():
    """hoehe_label lautet bei den 147 Platzhaltern 'keine Angabe (Annahme 1000 ft)'. Wer das
    Feld rendert, zeigt die erfundene Zahl doch an -- nur in Klammern. Deshalb muss das Popup
    auf hoehe_geschaetzt verzweigen und hoehe_label gar nicht erst anfassen."""
    stelle = INDEX.index("function _platzrundenPopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "hoehe_geschaetzt" in rumpf
    assert "hoehe_label" not in rumpf


def test_popup_schreibt_msl_auch_bei_unsicherem_bezug():
    """127 Eintraege tragen 'MSL?'. Gegen die Platzhoehe gerechnet liegen sie im selben Band
    wie die 138 expliziten MSL-Angaben (Median 895 vs. 864 ft ueber Grund) -- derselbe Bezug.
    Ein Fragezeichen im Cockpit hilft niemandem."""
    stelle = INDEX.index("function _platzrundenPopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "MSL?" not in rumpf


def test_zoom_wache_haengt_am_zoomend():
    """Weit herausgezoomt sind 412 Polygone kein Bild mehr, sondern Grauschleier. Ausblenden
    heisst hier: die Linien verschwinden, der Haken bleibt gesetzt -- sonst muesste der Nutzer
    die Ebene nach jedem Herauszoomen neu einschalten."""
    stelle = INDEX.index("function _platzrundenZoomWache(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "zoomend" in rumpf
    assert "_PLATZRUNDEN_MIN_ZOOM" in rumpf
