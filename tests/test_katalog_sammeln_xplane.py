# -*- coding: utf-8 -*-
"""Der X-Plane-Sammellauf nimmt ALLES auf, nicht nur eine Auswahl (20.09.2026).

Nutzer: *„Ich meine auch übersehene Objekte!"* — nach dem Abgleich Platte gegen Katalog: 5 076 von
7 995 Standardobjekten standen nicht im Katalog, dazu alle offiziellen Pakete unter `Custom Scenery`
(16 „X-Plane Landmarks", 6 „X-Plane Airports": Brandenburger Tor, Fernsehturm, Eiffelturm …). Die
Regel „nur was als einzelnes Objekt Sinn ergibt" (14.09.2026) hatte sie draußen gelassen, ohne dass
je einer nachgesehen hätte, was darunter liegt.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "friesenbruegge"))
import katalog_sammeln as ks  # noqa: E402


def _obj(wurzel: Path, rel: str) -> None:
    p = wurzel / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("A\n800\nOBJ\n", encoding="utf-8")


def _baum(tmp_path: Path) -> Path:
    w = tmp_path / "X-Plane 12"
    ds = "Resources/default scenery/"
    _obj(w, ds + "sim objects/dynamic/deer_buck.obj")                        # Zweig `sim objects`
    _obj(w, ds + "airport scenery/1000_Landmarks/Eiffel_Tower.obj")          # neuer Zweig
    _obj(w, ds + "900 roads/trains/F_boxcar_b_13.33.obj")                    # neuer Zweig
    _obj(w, ds + "1000 autogen/EU/industrial/shed_1.obj")                    # nur ueber den Rest
    _obj(w, ds + "900 europe objects/in_irr_120_120a1.obj")                  # nur ueber den Rest
    _obj(w, ds + "1000 world terrain/terrain_fx/x.obj")                      # Rest, kurzer Pfad
    _obj(w, "Custom Scenery/X-Plane Landmarks - Berlin and Frankfurt/objects/Brandenburg_Gate.obj")
    _obj(w, "Custom Scenery/X-Plane Airports - EGPR Barra/objects/Hangar.obj")
    _obj(w, "Custom Scenery/Aerosoft Fremdpaket/objects/Nicht_Meins.obj")    # fremdes Paket: bleibt draussen
    return w


def test_der_rest_der_standardobjekte_kommt_mit(tmp_path):
    titel = {e["titel"]: e for e in ks.sammle_xplane(_baum(tmp_path))}
    assert "Resources/default scenery/1000 autogen/EU/industrial/shed_1.obj" in titel, \
        "was bisher draußen war, gehört jetzt in den Katalog"
    assert "Resources/default scenery/900 europe objects/in_irr_120_120a1.obj" in titel
    e = titel["Resources/default scenery/1000 autogen/EU/industrial/shed_1.obj"]
    assert e["kategorie"] == "1000 autogen/EU" and e["quelle"] == "bord" and e["simulator"] == "xplane12"


def test_neue_zweige_tragen_eine_lesbare_kategorie(tmp_path):
    titel = {e["titel"]: e for e in ks.sammle_xplane(_baum(tmp_path))}
    assert titel["Resources/default scenery/airport scenery/1000_Landmarks/Eiffel_Tower.obj"]["kategorie"] == "landmarks"
    assert titel["Resources/default scenery/900 roads/trains/F_boxcar_b_13.33.obj"]["kategorie"] == "trains"
    assert titel["Resources/default scenery/sim objects/dynamic/deer_buck.obj"]["kategorie"] == "dynamic"


def test_die_offiziellen_custom_scenery_pakete_sind_drin_fremde_nicht(tmp_path):
    titel = {e["titel"]: e for e in ks.sammle_xplane(_baum(tmp_path))}
    tor = titel["Custom Scenery/X-Plane Landmarks - Berlin and Frankfurt/objects/Brandenburg_Gate.obj"]
    assert tor["kategorie"] == "landmarks" and tor["paket"] == "X-Plane Landmarks - Berlin and Frankfurt"
    hangar = titel["Custom Scenery/X-Plane Airports - EGPR Barra/objects/Hangar.obj"]
    assert hangar["kategorie"] == "airports_custom"
    assert not any("Fremdpaket" in t for t in titel), \
        "nur die offiziellen Laminar-Pakete; alles andere unter Custom Scenery ist Fremdware"


def test_kein_titel_kommt_doppelt_vor(tmp_path):
    liste = ks.sammle_xplane(_baum(tmp_path))
    titel = [e["titel"] for e in liste]
    assert len(titel) == len(set(titel)), "Zweige überlappen -- ein Objekt darf nur einmal aufgenommen werden"


def test_ohne_custom_scenery_ordner_bricht_nichts(tmp_path):
    w = tmp_path / "X-Plane 12"
    _obj(w, "Resources/default scenery/sim objects/dynamic/deer_buck.obj")
    assert len(ks.sammle_xplane(w)) == 1
