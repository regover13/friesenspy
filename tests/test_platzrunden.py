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
