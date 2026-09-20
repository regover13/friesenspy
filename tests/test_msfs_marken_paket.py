# -*- coding: utf-8 -*-
"""Die MSFS-Marken der FriesenBrügge: Würfel, Lichtsäulen, Punktlicht (20.09.2026).

`friesenbruegge/msfs-rauch/marken_bauen.py` schreibt die Quellen für 7 Würfel, 7 Säulen und 1 Licht
(alles Titel `Frs…`, KEINE Texturen, in MSFS 2020 und 2024 dieselben Dateien). Die Säule ist seit dem
Flugtest vom 20.09.2026 ein Scheinwerferstrahl aus 100 gestapelten Segmenten mit je eigenem Material. Der Simulator ist von
Python aus nicht erreichbar; gebunden wird hier, was sich an den Dateien prüfen lässt und beim
nächsten Umbau leise verschwinden könnte: der Titelsatz, die Dateiform, die Geometrie (Bounding
Box, Zählungen, Umlaufsinn), die Farben und die Form des Lichtknotens.

⚠ **Der Bau selbst ist ungeprüft** (`fspackagetool` läuft nicht in der CI, der Nutzer saß im Sim).
Was der Compiler und der Simulator aus diesen Dateien machen, klärt der Flugtest.

Gegengeprüft: Jede Zusicherung wird ohne die zugehörige Stelle im Generator rot.
"""
from __future__ import annotations

import importlib
import json
import math
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
RAUCH = WURZEL / "friesenbruegge" / "msfs-rauch"


def _marken_bauen():
    """`marken_bauen` laden, ohne dass sein `from rauch_bauen import FARBEN` die X-Plane-Datei gleichen Namens trifft."""
    gemerkt = {k: sys.modules.pop(k) for k in ("rauch_bauen", "marken_bauen") if k in sys.modules}
    sys.path.insert(0, str(RAUCH))
    try:
        return importlib.import_module("marken_bauen")
    finally:
        sys.path.remove(str(RAUCH))
        sys.modules.pop("rauch_bauen", None)
        sys.modules.pop("marken_bauen", None)
        sys.modules.update(gemerkt)


def _paket_bauen():
    """`paket_bauen` laden (es importiert `rauch_bauen` und `marken_bauen` aus msfs-rauch/)."""
    gemerkt = {k: sys.modules.pop(k) for k in ("rauch_bauen", "marken_bauen", "paket_bauen") if k in sys.modules}
    sys.path.insert(0, str(RAUCH))
    try:
        return importlib.import_module("paket_bauen")
    finally:
        sys.path.remove(str(RAUCH))
        for k in ("rauch_bauen", "marken_bauen", "paket_bauen"):
            sys.modules.pop(k, None)
        sys.modules.update(gemerkt)


@pytest.fixture(scope="module")
def mb():
    return _marken_bauen()


@pytest.fixture(scope="module")
def ausgabe(mb, tmp_path_factory):
    """Der ENDGÜLTIGE Stand: 15 Titel, Schalter `MIT_TESTTITELN` aus — egal, wie die Konstante steht."""
    ziel = tmp_path_factory.mktemp("marken") / "FrsMarke"
    n = mb.marken_schreiben(ziel, mit_testtiteln=False)
    return ziel, n


@pytest.fixture(scope="module")
def ausgabe_test(mb, tmp_path_factory):
    """Dasselbe mit den Testtiteln (Schalter an)."""
    ziel = tmp_path_factory.mktemp("marken_test") / "FrsMarke"
    n = mb.marken_schreiben(ziel, mit_testtiteln=True)
    return ziel, n


def _sim_cfg(ziel: Path) -> list[dict]:
    """Die `[fltsim.N]`-Blöcke der sim.cfg als Wörterbücher."""
    bloecke, akt = [], None
    for zeile in (ziel / "sim.cfg").read_text(encoding="utf-8").splitlines():
        z = zeile.strip()
        if z.startswith("[fltsim."):
            akt = {}
            bloecke.append(akt)
        elif z.startswith("["):
            akt = None
        elif akt is not None and "=" in z:
            k, _, v = z.partition("=")
            akt[k.strip()] = v.strip()
    return bloecke


def _gltf(ziel: Path, ordner: str, titel: str) -> dict:
    return json.loads((ziel / f"model.{ordner}" / f"{titel}.gltf").read_text(encoding="utf-8"))


# ---- der Titelsatz ----------------------------------------------------------------------

def test_es_sind_sieben_wuerfel_sieben_saeulen_und_ein_licht(mb, ausgabe):
    ziel, n = ausgabe
    titel = [b["title"] for b in _sim_cfg(ziel)]
    assert n == len(titel) == 15
    farben = list(mb.FARBEN) + ["weiss"]
    erwartet = ([f"FrsWuerfel_{f.capitalize()}" for f in farben]
                + [f"FrsSaeule_{f.capitalize()}" for f in farben] + ["FrsLicht_Warm"])
    assert titel == erwartet
    assert len(set(titel)) == len(titel), "jeder Titel genau einmal"


def test_die_farben_sind_die_friesenfarben_des_rauchs_und_scheinwerferweiss(mb):
    assert set(mb.FARBEN) == {"navy", "hellblau", "rot", "orange", "signalrot", "signalorange"}
    assert set(mb.WUERFEL_FARBEN) == set(mb.SAEULEN_FARBEN) == set(mb.FARBEN) | {"weiss"}
    for name, rgb in mb.FARBEN.items():
        assert mb.MARKEN_FARBEN[name] == rgb


def test_scheinwerferweiss_ist_eine_konstante_fuer_saeule_und_wuerfel(mb):
    """Nutzer, 20.09.2026: warmes, leicht gelbliches Weiß, sRGB (255, 240, 200) — kein Reinweiß."""
    assert mb.WEISS == (255, 240, 200)
    assert mb.WUERFEL_FARBEN["weiss"] == mb.SAEULEN_FARBEN["weiss"] == mb.WEISS


def test_sim_cfg_hat_die_kategorie_und_jeder_titel_seinen_ordner(ausgabe):
    ziel, _ = ausgabe
    text = (ziel / "sim.cfg").read_text(encoding="utf-8")
    assert "category=StaticObject" in text and "DistanceToNotAnimate" in text
    for b in _sim_cfg(ziel):
        assert b["texture"] == "", "keine Textur: die Zeile bleibt leer"
        assert (ziel / f"model.{b['model']}").is_dir(), b


# ---- die Dateien je Modell ---------------------------------------------------------------

def test_jedes_modell_hat_cfg_xml_gltf_und_bin_und_alles_ist_wohlgeformt(ausgabe):
    ziel, _ = ausgabe
    for b in _sim_cfg(ziel):
        d, t = ziel / f"model.{b['model']}", b["title"]
        assert (d / "model.CFG").read_text(encoding="utf-8").split("normal=")[1].strip() == f"{t}.xml"
        wurzel = ET.parse(d / f"{t}.xml").getroot()
        lod = wurzel.find("LODS").findall("LOD")
        assert len(lod) == 1 and lod[0].get("ModelFile") == f"{t}.gltf"
        assert lod[0].get("minSize") == "0", "nie wegen Bildschirmgröße ausblenden"
        assert wurzel.find("Behaviors") is None, "keine Behaviors: der Simulator schaltet das Licht selbst"
        json.loads((d / f"{t}.gltf").read_text(encoding="utf-8"))
        assert (d / f"{t}.bin").stat().st_size > 0


def test_keine_textur_und_kein_base64_nirgends(ausgabe):
    ziel, _ = ausgabe
    for b in _sim_cfg(ziel):
        g = _gltf(ziel, b["model"], b["title"])
        assert "textures" not in g and "images" not in g and "samplers" not in g
        text = json.dumps(g)
        assert "Texture" not in text and "data:" not in text
        assert [x["uri"] for x in g["buffers"]] == [f"{b['title']}.bin"], "eine echte .bin daneben"
    assert not list(ziel.rglob("*.png")) and not list(ziel.rglob("*.dds")) and not list(ziel.rglob("*.KTX2"))


# ---- die Geometrie -----------------------------------------------------------------------

def _prims(ziel, b):
    """(gltf, [(Ecken, Normalen, Indizes, Accessoren) je Primitive]) aus glTF + .bin."""
    g = _gltf(ziel, b["model"], b["title"])
    roh = (ziel / f"model.{b['model']}" / f"{b['title']}.bin").read_bytes()
    assert g["buffers"][0]["byteLength"] == len(roh), "die .bin ist so lang, wie das glTF sagt"
    raus = []
    for p in g["meshes"][0]["primitives"]:
        av = g["accessors"][p["attributes"]["POSITION"]]
        an = g["accessors"][p["attributes"]["NORMAL"]]
        ai = g["accessors"][p["indices"]]
        bv = g["bufferViews"]
        ecken = [struct.unpack_from("<fff", roh, bv[av["bufferView"]]["byteOffset"] + 12 * i) for i in range(av["count"])]
        norm = [struct.unpack_from("<fff", roh, bv[an["bufferView"]]["byteOffset"] + 12 * i) for i in range(an["count"])]
        idx = list(struct.unpack_from(f"<{ai['count']}H", roh, bv[ai["bufferView"]]["byteOffset"]))
        raus.append((ecken, norm, idx, (av, an, ai)))
    return g, raus


def _titel(ziel, praefix):
    return [b for b in _sim_cfg(ziel) if b["title"].startswith(praefix)]


def test_zaehlungen_bounding_box_und_puffergrenzen_stimmen(ausgabe):
    ziel, _ = ausgabe
    for b in _sim_cfg(ziel):
        g, prims = _prims(ziel, b)
        ende = 0
        for bv in g["bufferViews"]:
            assert bv["byteOffset"] >= ende, "BufferViews überlappen nicht"
            ende = bv["byteOffset"] + bv["byteLength"]
        assert ende <= g["buffers"][0]["byteLength"]
        for ecken, norm, idx, (av, an, ai) in prims:
            assert av["count"] == an["count"] == len(ecken) == len(norm)
            assert len(ecken) % 4 == 0 and len(idx) == len(ecken) // 4 * 6
            assert max(idx) == len(ecken) - 1 and min(idx) == 0
            for a_ in range(3):
                assert av["min"][a_] == pytest.approx(min(e[a_] for e in ecken), abs=1e-5)
                assert av["max"][a_] == pytest.approx(max(e[a_] for e in ecken), abs=1e-5)


def test_der_wuerfel_misst_drei_meter_und_steht_mit_der_unterseite_im_ursprung(ausgabe):
    ziel, _ = ausgabe
    wuerfel = _titel(ziel, "FrsWuerfel_")
    assert len(wuerfel) == 7
    for b in wuerfel:
        g, prims = _prims(ziel, b)
        assert len(prims) == 1, "ein Würfel ist EINE Primitive"
        ecken = prims[0][0]
        assert len(ecken) == 24, "vierundzwanzig Ecken: der Compiler rechnet keine Normalen selbst"
        assert min(e[1] for e in ecken) == 0.0 and max(e[1] for e in ecken) == pytest.approx(3.0)
        assert max(e[0] for e in ecken) == pytest.approx(1.5) and min(e[0] for e in ecken) == pytest.approx(-1.5)
        assert max(e[2] for e in ecken) == pytest.approx(1.5)


def test_die_saeule_ist_ein_stapel_aus_100_achteck_segmenten_zu_je_einem_meter(mb, ausgabe):
    """25 × 4 m zeigten in MSFS 2024 sichtbare waagerechte Stufen (Endabnahme 20.09.2026) — jetzt 100 × 1 m."""
    ziel, _ = ausgabe
    assert mb.SAEULE_SEGMENTE == 100
    for b in _titel(ziel, "FrsSaeule_"):
        g, prims = _prims(ziel, b)
        assert len(prims) == 100 and len(g["materials"]) == 100, "je Segment eine Primitive UND ein Material"
        assert [p["material"] for p in g["meshes"][0]["primitives"]] == list(range(100))
        for i, (ecken, *_r) in enumerate(prims):
            assert len(ecken) == 32, "ein Achteck ohne Deckel: acht Seiten zu vier Ecken"
            ys = [e[1] for e in ecken]
            # Die Segmente sind je 1 m hoch und stoßen lückenlos aneinander.
            assert min(ys) == pytest.approx(1.0 * i) and max(ys) == pytest.approx(1.0 * (i + 1))


def test_zaehlungen_und_groesse_der_100er_saeule_stimmen(ausgabe):
    """400 Accessoren und BufferViews (vier je Primitive), jede Bounding Box gehört zu ihrem Meter, die .bin ist
    100 × 1120 Byte lang, und die Säule bleibt unter 400 kB (gemessen: ~112 kB .bin + ~163 kB glTF)."""
    ziel, _ = ausgabe
    for b in _titel(ziel, "FrsSaeule_"):
        g, prims = _prims(ziel, b)
        assert len(g["accessors"]) == 400 and len(g["bufferViews"]) == 400
        assert g["buffers"][0]["byteLength"] == 100 * 1120 == 112000
        for i, (ecken, _n, idx, (av, an, ai)) in enumerate(prims):
            assert av["min"][1] == pytest.approx(float(i)) and av["max"][1] == pytest.approx(float(i + 1))
            r = 2.0 + i / 100.0
            assert av["max"][0] == pytest.approx(r + 0.01, abs=1e-5) and av["min"][0] == pytest.approx(-(r + 0.01), abs=1e-5)
            assert ai["count"] == 48 and av["count"] == 32, "acht Seiten: 8 × 4 Ecken, 8 × 6 Indizes"
        d = ziel / f"model.{b['model']}"
        groesse = sum(f.stat().st_size for f in d.iterdir())
        assert groesse < 400_000, (b["title"], groesse)


def test_die_saeule_ist_unten_vier_und_oben_sechs_meter_breit_und_hundert_hoch(ausgabe):
    ziel, _ = ausgabe
    for b in _titel(ziel, "FrsSaeule_"):
        g, prims = _prims(ziel, b)
        alle = [e for ecken, *_r in prims for e in ecken]
        assert min(e[1] for e in alle) == 0.0 and max(e[1] for e in alle) == pytest.approx(100.0)
        unten = [e for e in prims[0][0] if e[1] == 0.0]
        oben = [e for e in prims[-1][0] if e[1] == pytest.approx(100.0)]
        assert max(math.hypot(e[0], e[2]) for e in unten) == pytest.approx(2.0, abs=1e-5)    # 4 m über die Ecken
        assert max(math.hypot(e[0], e[2]) for e in oben) == pytest.approx(3.0, abs=1e-5)     # 6 m über die Ecken
        # Die Bounding Box der letzten Primitive gehört zur neuen Breite (±3 m), nicht zu den alten 0,4 m.
        av = prims[-1][3][0]
        assert av["max"][0] == pytest.approx(3.0, abs=1e-5) and av["min"][0] == pytest.approx(-3.0, abs=1e-5)
        # Der Radius wächst von Ring zu Ring.
        radien = [max(math.hypot(e[0], e[2]) for e in ecken) for ecken, *_r in prims]
        assert all(a < b_ for a, b_ in zip(radien, radien[1:]))


def test_umlaufsinn_und_normalen_passen_zusammen(ausgabe):
    """Die geometrische Normale jedes Dreiecks (Kreuzprodukt) zeigt in dieselbe Richtung wie die gespeicherte.

    Ein Würfel ist nicht `doubleSided`: Läuft ein Dreieck falsch herum, ist die Fläche von außen unsichtbar.
    """
    ziel, _ = ausgabe
    for b in _sim_cfg(ziel):
        if b["title"] == "FrsLicht_Warm":
            continue                                            # unsichtbarer Träger, Umlaufsinn egal
        g, prims = _prims(ziel, b)
        for ecken, norm, idx, _acc in prims:
            for k in range(0, len(idx), 3):
                p0, p1, p2 = (ecken[i] for i in idx[k:k + 3])
                u, v = [p1[i] - p0[i] for i in range(3)], [p2[i] - p0[i] for i in range(3)]
                n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                gespeichert = norm[idx[k]]
                assert sum(n[i] * gespeichert[i] for i in range(3)) > 0, (b["title"], k)
            for nx, ny, nz in norm:
                assert math.sqrt(nx * nx + ny * ny + nz * nz) == pytest.approx(1.0, abs=1e-4)


def test_die_normalen_der_saeule_kippen_leicht_nach_unten(ausgabe):
    """Die Säule wird nach oben breiter: Die Seitenflächen schauen minimal nach unten."""
    ziel, _ = ausgabe
    g, prims = _prims(ziel, _titel(ziel, "FrsSaeule_")[0])
    for _e, norm, *_r in prims:
        assert all(-0.05 < n[1] < 0.0 for n in norm), "leicht negativ, aber fast waagerecht"


# ---- die Farben --------------------------------------------------------------------------

def _linear(k):
    c = k / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def test_der_wuerfel_traegt_die_farbe_und_ein_wenig_eigenlicht(mb, ausgabe):
    """Alle sieben: die sechs Friesenfarben und Scheinwerferweiß."""
    ziel, _ = ausgabe
    for name, rgb in mb.WUERFEL_FARBEN.items():
        g = _gltf(ziel, f"wuerfel_{name}", f"FrsWuerfel_{name.capitalize()}")
        m = g["materials"][0]
        lin = [_linear(k) for k in rgb]
        assert m["pbrMetallicRoughness"]["baseColorFactor"][:3] == pytest.approx(lin, abs=1e-5)
        assert m["pbrMetallicRoughness"]["baseColorFactor"][3] == 1.0
        assert m["emissiveFactor"] == pytest.approx([0.35 * k for k in lin], abs=1e-5)
        assert m.get("alphaMode") in (None, "OPAQUE") and not m.get("doubleSided")


def test_der_weisse_wuerfel_hat_dieselbe_machart_wie_die_anderen(ausgabe):
    ziel, _ = ausgabe
    weiss = _gltf(ziel, "wuerfel_weiss", "FrsWuerfel_Weiss")["materials"][0]
    rot = _gltf(ziel, "wuerfel_rot", "FrsWuerfel_Rot")["materials"][0]
    lin = [_linear(k) for k in (255, 240, 200)]
    assert weiss["pbrMetallicRoughness"]["baseColorFactor"][:3] == pytest.approx(lin, abs=1e-5)
    assert weiss["emissiveFactor"] == pytest.approx([0.35 * k for k in lin], abs=1e-5), "gleicher Emissive-Anteil"
    assert weiss["pbrMetallicRoughness"]["baseColorFactor"][2] < 0.7, "warmes Weiß, kein Reinweiß"
    assert set(weiss) == set(rot) and weiss["pbrMetallicRoughness"].keys() == rot["pbrMetallicRoughness"].keys()


def test_die_saeule_ist_je_segment_abgestuft_halbtransparent_und_doppelseitig(mb, ausgabe):
    """Alpha fällt linear von 0,85 auf 0,02, das Eigenlicht mit (1 − t)^1,2; t = Höhe der Segmentmitte / 100 m."""
    ziel, _ = ausgabe
    for name, rgb in mb.SAEULEN_FARBEN.items():
        g = _gltf(ziel, f"saeule_{name}", f"FrsSaeule_{name.capitalize()}")
        lin = [_linear(k) for k in rgb]
        alphas, emis = [], []
        for i, m in enumerate(g["materials"]):
            t = (i + 0.5) / 100
            assert m["alphaMode"] == "BLEND" and m["doubleSided"] is True
            f = m["pbrMetallicRoughness"]["baseColorFactor"]
            assert f[:3] == pytest.approx(lin, abs=1e-5), "die Grundfarbe bleibt in jedem Segment dieselbe"
            assert f[3] == pytest.approx(0.85 + (0.02 - 0.85) * t, abs=1e-5)
            assert m["emissiveFactor"] == pytest.approx([k * (1 - t) ** 1.2 for k in lin], abs=1e-5)
            alphas.append(f[3])
            emis.append(m["emissiveFactor"][0])
        assert alphas == sorted(alphas, reverse=True) and len(set(alphas)) == 100, "Alpha fällt streng monoton"
        assert emis == sorted(emis, reverse=True) and len(set(emis)) == 100, "Eigenlicht fällt streng monoton"
        assert alphas[0] > 0.5 and alphas[-1] < 0.05, "unten deckend, oben praktisch ausgeblendet"
        assert emis[-1] < 0.02 * max(lin), "oben leuchtet fast nichts mehr"


def test_die_weisse_saeule_ist_scheinwerferweiss(ausgabe):
    ziel, _ = ausgabe
    g = _gltf(ziel, "saeule_weiss", "FrsSaeule_Weiss")
    lin = [_linear(k) for k in (255, 240, 200)]
    assert g["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"][:3] == pytest.approx(lin, abs=1e-5)
    assert lin[2] < lin[1] < lin[0] == pytest.approx(1.0), "gelblich: Blau am schwächsten"


# ---- das Punktlicht ----------------------------------------------------------------------

#: Die Felder aus `Schemas/ASOBO_macro_light/gltf.ASOBO_macro_light.schema.json` des 2020er SDK.
LICHT_FELDER = {"color", "intensity", "cone_angle", "has_simmetry", "flash_frequency", "flash_duration",
                "flash_phase", "rotation_speed", "day_night_cycle"}


def test_das_licht_hat_die_form_von_asobos_punktlichtern(ausgabe):
    """Belegt an Asobos `Point.NNN` (Seilwinde `ESW_2B`): Lichtknoten ohne Mesh, `cone_angle` 360, nur nachts."""
    ziel, _ = ausgabe
    g = _gltf(ziel, "licht_warm", "FrsLicht_Warm")
    lichter = [n for n in g["nodes"] if "ASOBO_macro_light" in n.get("extensions", {})]
    assert len(lichter) == 1
    n = lichter[0]
    assert "mesh" not in n, "ein Lichtknoten trägt kein Mesh"
    licht = n["extensions"]["ASOBO_macro_light"]
    assert set(licht) == LICHT_FELDER
    assert licht["cone_angle"] == 360, "Rundumstrahler"
    assert licht["day_night_cycle"] is True, "nur nachts"
    assert licht["color"] == pytest.approx([1.0, 0.84, 0.6])
    assert licht["intensity"] == 1600.0, "Testrunde 2: K400_I400 Luminanz 97, K400_I1600 176 (Runway-Feuer 144)"
    assert licht["flash_frequency"] == 0 and licht["rotation_speed"] == 0 and licht["has_simmetry"] is False
    assert "ASOBO_macro_light" in g["extensionsUsed"]
    assert "extensionsRequired" not in g, "Asobo verlangt die Erweiterung nicht (dort steht nur MSFT_texture_dds)"


def test_das_licht_haengt_wie_bei_asobo_unter_einem_wurzelknoten_light_der_selbst_das_kernmesh_traegt(ausgabe):
    """Asobos Seilwinde `ESW_2B`: Wurzelknoten `Light` MIT Mesh, darunter die Lichtknoten ohne Mesh."""
    ziel, _ = ausgabe
    g = _gltf(ziel, "licht_warm", "FrsLicht_Warm")
    nodes = g["nodes"]
    assert g["scenes"][0]["nodes"] == [0] and nodes[0]["name"] == "Light" and nodes[0]["children"] == [1]
    assert "mesh" in nodes[0], "der Wurzelknoten trägt den sichtbaren Leuchtkern"
    assert nodes[1]["name"] == "Point" and "mesh" not in nodes[1]
    assert len([n for n in nodes if "mesh" in n]) == 1
    assert "ASOBO_material_invisible" not in json.dumps(g), "der Träger ist kein unsichtbarer 5-cm-Würfel mehr"


def test_der_leuchtkern_ist_ein_warmweisser_02_meter_wuerfel_dessen_mitte_03_meter_ueber_dem_boden_liegt(mb, ausgabe):
    ziel, _ = ausgabe
    b = next(x for x in _sim_cfg(ziel) if x["title"] == "FrsLicht_Warm")
    g, prims = _prims(ziel, b)
    ecken = prims[0][0]
    assert len(prims) == 1 and len(ecken) == 24
    # Ursprung Mitte der Unterseite: y = 0 … 0,2, ±0,1 seitlich
    assert min(e[1] for e in ecken) == 0.0 and max(e[1] for e in ecken) == pytest.approx(0.2)
    assert max(e[0] for e in ecken) == pytest.approx(0.1) and min(e[2] for e in ecken) == pytest.approx(-0.1)
    # Der Wurzelknoten hebt ihn um 0,2 m, das Punktlicht sitzt 0,1 m darüber: Kernmitte und Licht auf 0,3 m.
    kern_y, licht_y = g["nodes"][0]["translation"][1], g["nodes"][1]["translation"][1]
    assert kern_y == pytest.approx(0.2) and kern_y + max(e[1] for e in ecken) / 2 == pytest.approx(0.3)
    assert kern_y + licht_y == pytest.approx(mb.LICHT_HOEHE) == pytest.approx(0.3)
    # Material: Warmweiß (1,0 / 0,84 / 0,6), emissiveFactor VOLL, deckend
    m = g["materials"][0]
    assert m["pbrMetallicRoughness"]["baseColorFactor"] == pytest.approx([1.0, 0.84, 0.6, 1.0])
    assert m["emissiveFactor"] == pytest.approx([1.0, 0.84, 0.6])
    assert m.get("alphaMode") in (None, "OPAQUE") and not m.get("doubleSided")


def test_der_leuchtkern_traegt_die_emissive_erweiterung_mit_dem_kern_multiplikator(mb, ausgabe):
    ziel, _ = ausgabe
    g = _gltf(ziel, "licht_warm", "FrsLicht_Warm")
    e = g["materials"][0]["extensions"]["ASOBO_material_emissive"]
    assert e == {"emissiveDayMultiplier": 1.0, "emissiveNightMultiplier": mb.LICHT_KERN_NACHT}
    assert mb.LICHT_KERN_NACHT == 400.0 and mb.LICHT_STAERKE == 1600.0
    assert "ASOBO_material_emissive" in g["extensionsUsed"] and "ASOBO_macro_light" in g["extensionsUsed"]
    assert "extensionsRequired" not in g


def test_nur_das_licht_hat_ein_lichtknoten(ausgabe):
    ziel, _ = ausgabe
    for b in _sim_cfg(ziel):
        text = json.dumps(_gltf(ziel, b["model"], b["title"]))
        assert ("ASOBO_macro_light" in text) == (b["title"] == "FrsLicht_Warm"), b["title"]


# ---- das Paket ---------------------------------------------------------------------------

def test_die_eingecheckten_quellen_sind_der_stand_des_generators(mb, tmp_path):
    """Wer den Generator ändert und `paket_bauen.py` nicht laufen lässt, checkt veraltete Quellen ein.

    Verglichen wird mit dem Ausgang bei der Vorgabe des Schalters (`MIT_TESTTITELN`): Läuft der
    Generator mit Schalter aus, verschwinden die Testordner auch aus den Quellen.
    """
    ziel = tmp_path / "FrsMarke"
    mb.marken_schreiben(ziel)
    eingecheckt = RAUCH / "PackageSources" / "SimObjects" / "Misc" / "FrsMarke"
    assert eingecheckt.is_dir(), "python paket_bauen.py ausführen und die Quellen einchecken"
    dateien = sorted(p.relative_to(ziel).as_posix() for p in ziel.rglob("*") if p.is_file())
    assert dateien == sorted(p.relative_to(eingecheckt).as_posix() for p in eingecheckt.rglob("*") if p.is_file())
    for rel in dateien:
        assert (ziel / rel).read_bytes().replace(b"\r\n", b"\n") == (eingecheckt / rel).read_bytes().replace(b"\r\n", b"\n"), rel


# ---- die Erweiterung ASOBO_material_emissive (MSFS 2024) --------------------------------

def _farbmaterialien(ziel, praefixe=("FrsWuerfel_", "FrsSaeule_")):
    for b in _sim_cfg(ziel):
        if b["title"].startswith(praefixe):
            g = _gltf(ziel, b["model"], b["title"])
            for m in g["materials"]:
                yield b["title"], g, m


def test_alle_wuerfel_und_saeulenmaterialien_tragen_die_emissive_erweiterung(mb, ausgabe):
    """`ASOBO_material_emissive` mit beiden Feldern an JEDEM Material; in `extensionsUsed`, nie in `extensionsRequired`.

    Der Nacht-Multiplikator ist der Regler für die Helligkeit in MSFS 2024 (dort rendert dasselbe Paket
    nachts etwa ein Fünftel bis ein Zehntel so hell wie in 2020). Beleg der Form: Asobos Bären-Beispiel im
    2024er SDK; das 2020er SDK kennt die Erweiterung nicht.
    """
    ziel, _ = ausgabe
    anzahl = 0
    for titel, g, m in _farbmaterialien(ziel):
        e = m["extensions"]["ASOBO_material_emissive"]
        assert set(e) == {"emissiveDayMultiplier", "emissiveNightMultiplier"}, titel
        assert e["emissiveDayMultiplier"] == 1.0 and e["emissiveNightMultiplier"] == mb.EMISSIVE_NACHT
        assert "ASOBO_material_emissive" in g["extensionsUsed"]
        assert "extensionsRequired" not in g
        anzahl += 1
    assert anzahl == 7 * 1 + 7 * 100, "sieben Würfelmaterialien und 7 × 100 Säulenmaterialien"
    assert mb.EMISSIVE_NACHT == 80.0 and mb.EMISSIVE_TAG == 1.0, "Endabnahme: 120 war fast zu hell, der 80er-Wert reicht"


def test_die_emissive_erweiterung_steht_an_wuerfeln_saeulen_und_dem_lichtkern_und_sonst_nirgends(mb, ausgabe):
    ziel, _ = ausgabe
    mit = {b["title"] for b in _sim_cfg(ziel)
           if any("ASOBO_material_emissive" in m.get("extensions", {})
                  for m in _gltf(ziel, b["model"], b["title"])["materials"])}
    assert mit == set(mb.alle_titel()), "alle 15: 7 Würfel, 7 Säulen und der Kern des Lichts"


# ---- die Testtitel (Schalter MIT_TESTTITELN) --------------------------------------------

ENDGUELTIG = 15
TESTTITEL = (["FrsTestWuerfel_M20", "FrsTestWuerfel_M40", "FrsTestWuerfel_M80", "FrsTestWuerfel_M160",
              "FrsTestSaeule_M20", "FrsTestSaeule_M40", "FrsTestSaeule_M80", "FrsTestSaeule_M160",
              "FrsTestLicht_K100_I100", "FrsTestLicht_K100_I400", "FrsTestLicht_K400_I400",
              "FrsTestLicht_K400_I1600"])


def test_ohne_testtitel_sind_es_genau_die_fuenfzehn_endgueltigen(mb, ausgabe):
    """Der endgültige Titelsatz, gebunden gegen den Generator mit Schalter AUS."""
    ziel, n = ausgabe
    titel = [b["title"] for b in _sim_cfg(ziel)]
    assert n == len(titel) == ENDGUELTIG and titel == mb.alle_titel()
    assert not [t for t in titel if "Test" in t]
    assert not list(ziel.glob("model.test_*")), "keine Testordner im Paket"


def test_mit_testtiteln_kommen_zwoelf_dazu_und_die_endgueltigen_bleiben_vorn(mb, ausgabe, ausgabe_test):
    ziel, n = ausgabe_test
    titel = [b["title"] for b in _sim_cfg(ziel)]
    assert n == len(titel) == ENDGUELTIG + len(TESTTITEL)
    assert titel[:ENDGUELTIG] == mb.alle_titel(), "die endgültigen zuerst, ihre fltsim-Nummern bleiben"
    assert titel[ENDGUELTIG:] == TESTTITEL
    assert [t for t, _o, _p in mb.testtitel()] == TESTTITEL
    assert len(set(titel)) == len(titel)


def test_die_dateien_der_endgueltigen_titel_haengen_nicht_am_schalter(ausgabe, ausgabe_test):
    aus, _ = ausgabe
    an, _ = ausgabe_test
    for b in _sim_cfg(aus):
        d = f"model.{b['model']}"
        for f in (aus / d).iterdir():
            assert f.read_bytes() == (an / d / f.name).read_bytes(), (b["title"], f.name)


def test_testwuerfel_sind_signalorange_mit_den_vier_nachtmultiplikatoren(mb, ausgabe_test):
    ziel, _ = ausgabe_test
    rgb = mb.FARBEN["signalorange"]
    lin = [_linear(k) for k in rgb]
    for m in (20, 40, 80, 160):
        b = next(x for x in _sim_cfg(ziel) if x["title"] == f"FrsTestWuerfel_M{m}")
        g = _gltf(ziel, b["model"], b["title"])
        mat = g["materials"][0]
        assert mat["pbrMetallicRoughness"]["baseColorFactor"][:3] == pytest.approx(lin, abs=1e-5)
        assert mat["emissiveFactor"] == pytest.approx([0.35 * k for k in lin], abs=1e-5), "sonst wie der echte Würfel"
        e = mat["extensions"]["ASOBO_material_emissive"]
        assert e == {"emissiveDayMultiplier": 1.0, "emissiveNightMultiplier": float(m)}
        _g, prims = _prims(ziel, b)
        assert max(v[1] for v in prims[0][0]) == pytest.approx(3.0), "3 m wie der echte"


def test_testsaeulen_sind_wie_die_echte_nur_mit_anderem_multiplikator_und_alpha_085(mb, ausgabe_test):
    ziel, _ = ausgabe_test
    lin = [_linear(k) for k in mb.FARBEN["signalorange"]]
    for mult in (20, 40, 80, 160):
        titel = f"FrsTestSaeule_M{mult}"
        b = next(x for x in _sim_cfg(ziel) if x["title"] == titel)
        g = _gltf(ziel, b["model"], titel)
        assert len(g["materials"]) == 100
        for i, m in enumerate(g["materials"]):
            t = (i + 0.5) / 100
            assert m["pbrMetallicRoughness"]["baseColorFactor"][:3] == pytest.approx(lin, abs=1e-5)
            assert m["pbrMetallicRoughness"]["baseColorFactor"][3] == pytest.approx(0.85 + (0.02 - 0.85) * t, abs=1e-5)
            assert m["emissiveFactor"] == pytest.approx([k * (1 - t) ** 1.2 for k in lin], abs=1e-5)
            assert m["extensions"]["ASOBO_material_emissive"]["emissiveNightMultiplier"] == float(mult)
        _g, prims = _prims(ziel, b)
        assert max(v[1] for pr in prims for v in pr[0]) == pytest.approx(100.0), "100 m wie die echte"


def test_die_alten_testtitel_der_ersten_runde_gibt_es_nicht_mehr(ausgabe_test):
    ziel, _ = ausgabe_test
    titel = {b["title"] for b in _sim_cfg(ziel)}
    for alt in ("FrsTestWuerfel_M1", "FrsTestWuerfel_M12", "FrsTestSaeule_M6_A85", "FrsTestSaeule_M12_A85",
                "FrsTestLicht_I8", "FrsTestLicht_I100"):
        assert alt not in titel, alt


def test_testlichter_tragen_kern_multiplikator_und_lichtstaerke(mb, ausgabe_test):
    """`FrsTestLicht_K<Kern>_I<Stärke>`: K = Nacht-Multiplikator des Leuchtkerns, I = Stärke des Macro-Lights."""
    ziel, _ = ausgabe_test
    for k, i in ((100, 100), (100, 400), (400, 400), (400, 1600)):
        b = next(x for x in _sim_cfg(ziel) if x["title"] == f"FrsTestLicht_K{k}_I{i}")
        g = _gltf(ziel, b["model"], b["title"])
        licht = next(n for n in g["nodes"] if "ASOBO_macro_light" in n.get("extensions", {}))["extensions"]["ASOBO_macro_light"]
        assert licht["intensity"] == float(i)
        assert licht["cone_angle"] == 360 and licht["day_night_cycle"] is True
        assert licht["color"] == pytest.approx([1.0, 0.84, 0.6])
        e = g["materials"][0]["extensions"]["ASOBO_material_emissive"]
        assert e == {"emissiveDayMultiplier": 1.0, "emissiveNightMultiplier": float(k)}
        # sonst genau wie das endgültige Licht: Kern 0,2 m, Wurzelknoten `Light` mit Kind `Point`
        assert g["nodes"][0]["name"] == "Light" and g["nodes"][1]["name"] == "Point"
        assert g["materials"][0]["emissiveFactor"] == pytest.approx([1.0, 0.84, 0.6])
        _g, prims = _prims(ziel, b)
        assert max(v[1] for v in prims[0][0]) == pytest.approx(0.2)


def test_der_schalter_aus_raeumt_die_testordner_weg(mb, tmp_path):
    ziel = tmp_path / "FrsMarke"
    mb.marken_schreiben(ziel, mit_testtiteln=True)
    assert len(list(ziel.glob("model.test_*"))) == 12
    mb.marken_schreiben(ziel, mit_testtiteln=False)
    assert not list(ziel.glob("model.test_*")), "sonst nähme der Paketbau sie als Beiwerk mit"
    assert len(_sim_cfg(ziel)) == 15 and len(list(ziel.glob("model.*"))) == 15


def test_bei_eingeschaltetem_schalter_verschwinden_die_testordner_einer_fruehreren_reihe(mb, tmp_path):
    """Testrunde 1 → 2: Ordner der alten Reihe blieben liegen, obwohl die sim.cfg sie nicht mehr nannte."""
    ziel = tmp_path / "FrsMarke"
    mb.marken_schreiben(ziel, mit_testtiteln=True)
    alt = ziel / "model.test_wuerfel_m1"
    alt.mkdir()
    (alt / "FrsTestWuerfel_M1.gltf").write_text("{}", encoding="utf-8")
    mb.marken_schreiben(ziel, mit_testtiteln=True)
    assert not alt.exists(), "der Ordner einer früheren Testreihe muss weg"
    assert len(list(ziel.glob("model.test_*"))) == 12, "die aktuelle Reihe bleibt vollständig"
    assert len(list(ziel.glob("model.*"))) == 15 + 12


def test_ein_schreibgeschuetzter_testordner_laesst_sich_trotzdem_wegraeumen(mb, tmp_path):
    """OneDrive: Der Ordner der vorigen Reihe war `ReadOnly` und verweigerte `rmdir`."""
    import os
    ziel = tmp_path / "FrsMarke"
    mb.marken_schreiben(ziel, mit_testtiteln=True)
    alt = ziel / "model.test_saeule_m1"
    alt.mkdir()
    orig = os.rmdir
    verweigert = []

    def strenger_rmdir(pfad, *a, **k):
        if os.fspath(pfad) == str(alt) and not verweigert:
            verweigert.append(1)
            raise PermissionError(13, "Zugriff verweigert")
        return orig(pfad, *a, **k)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "rmdir", strenger_rmdir)
        mb.marken_schreiben(ziel, mit_testtiteln=True)
    assert verweigert and not alt.exists()


# ---- die Marken sind ein eigenes Teilpaket, gebaut mit dem 2024er SDK (20.09.2026) ------
#
# Der 2020er Compiler ENTFERNT `ASOBO_material_emissive` aus dem kompilierten Material (Quelle:
# emissiveNightMultiplier 6.0; das fertige `FrsTestWuerfel_M6.gltf` hat nur `emissiveFactor`). Rauch und
# Seehund dürfen dagegen nicht mit dem 2024er SDK gebaut werden (KTX2-Texturen, Behavior-Vorlage laufen in
# MSFS 2020 nicht). Also: zwei SDKs, zwei Projektdateien, zwei Teilpaket-Gruppen, ein gemeinsames ZIP.

MSFS = WURZEL / "friesenbruegge" / "msfs"


def _text(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8").replace("\r\n", "\n")


def _gruppen(xml_pfad: Path) -> dict:
    wurzel = ET.parse(xml_pfad).getroot()
    return {g.get("Name"): {"typ": g.find("Type").text, "quelle": g.find("AssetDir").text,
                            "ziel": g.find("OutputDir").text} for g in wurzel.iter("AssetGroup")}


def test_die_marken_haben_ein_eigenes_teilpaket_devprops_friesenmarken():
    d = RAUCH / "PackageDefinitions" / "devprops-friesenmarken.xml"
    wurzel = ET.parse(d).getroot()
    assert wurzel.find("ItemSettings/Title").text == "friesenmarken"
    assert wurzel.find("ItemSettings/Creator").text == "devprops", "creator ist immer devprops"
    assert wurzel.find("ItemSettings/ContentType").text == "MISC"
    assert _gruppen(d) == {"MarkenObjects": {
        "typ": "SimObject",
        "quelle": "PackageSources\\SimObjects\\Misc\\FrsMarke\\",
        "ziel": "SimObjects\\Misc\\FrsMarke\\"}}


def test_der_rauchteil_enthaelt_keine_marken_mehr_aber_rauch_und_seehund_bleiben():
    d = RAUCH / "PackageDefinitions" / "devprops-friesenrauch.xml"
    text = _text(d)
    assert "MarkenObjects" not in text and "FrsMarke" not in text
    g = _gruppen(d)
    assert set(g) == {"SimObjects", "SeehundObjects"}
    assert g["SimObjects"]["ziel"] == "SimObjects\\Misc\\FrsRauch\\"
    assert g["SeehundObjects"]["ziel"] == "SimObjects\\Misc\\FrsSeehund\\"


def test_zwei_projektdateien_zwei_toolchains_getrennte_zwischenordner():
    def projekt(name):
        w = ET.parse(RAUCH / name).getroot()
        return (w.get("Name"), w.get("FolderName"), w.find("OutputDirectory").text,
                w.find("TemporaryOutputDirectory").text, [x.text for x in w.iter("Package")])
    marken = projekt("FriesenMarken.xml")
    rauch = projekt("FriesenRauch.xml")
    assert marken == ("FriesenMarken", "Packages", ".", "_PackageInt2024",
                      ["PackageDefinitions\\devprops-friesenmarken.xml"])
    assert rauch[0] == "FriesenRauch" and rauch[1] == "Packages" and rauch[3] == "_PackageInt"
    assert rauch[4] == ["PackageDefinitions\\devprops-friesenrauch-vfx.xml",
                        "PackageDefinitions\\devprops-friesenrauch-mat.xml",
                        "PackageDefinitions\\devprops-friesenrauch.xml"], "kein Markenteil im Rauchprojekt"
    assert marken[3] != rauch[3], "beide Toolchains legen Zwischenformate ab: nie derselbe Ordner"
    assert "_PackageInt2024/" in _text(RAUCH / ".gitignore")


def test_die_definitionen_im_repo_sind_der_stand_des_generators(tmp_path, monkeypatch):
    """`definitionen_schreiben()` in ein tmp-Verzeichnis: Byte für Byte dasselbe wie die eingecheckten Dateien."""
    pb = _paket_bauen()
    monkeypatch.setattr(pb, "HIER", tmp_path)
    monkeypatch.setattr(pb, "DEFINITIONEN", tmp_path / "PackageDefinitions")
    pb.definitionen_schreiben()
    erzeugt = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert erzeugt == ["FriesenMarken.xml", "FriesenRauch.xml",
                       "PackageDefinitions/devprops-friesenmarken.xml",
                       "PackageDefinitions/devprops-friesenrauch-mat.xml",
                       "PackageDefinitions/devprops-friesenrauch-vfx.xml",
                       "PackageDefinitions/devprops-friesenrauch.xml"]
    for rel in erzeugt:
        assert _text(tmp_path / rel) == _text(RAUCH / rel), rel


def _ps_code(text: str) -> str:
    """Ein PowerShell-Skript ohne Kommentarzeilen — die Kommentare nennen genau die Dinge, die der Code NICHT tun darf."""
    return "\n".join(z for z in text.split("\n") if not z.lstrip().startswith("#"))


def test_bauen_marken_ps1_baut_mit_dem_2024er_sdk():
    code = _ps_code(_text(RAUCH / "bauen_marken.ps1"))
    assert "MSFS2024_SDK" in code and "C:\\MSFS 2024 SDK" in code and "Tools\\bin\\fspackagetool.exe" in code
    assert "MSFS_SDK" not in code and "D:\\MSFS SDK" not in code, "kein 2020er SDK im Code"
    assert '& $w "FriesenMarken.xml"' in code and "FriesenRauch" not in code
    # mit `&` im Job, nicht mit Start-Process -NoNewWindow (14.09.2026: null Dateien)
    assert "Start-Job" in code and "-NoNewWindow" not in code


def test_bauen_marken_ps1_raeumt_die_vier_prozesse_des_2024er_baus_ab_auch_im_fehler_und_timeout_pfad():
    """Das Werkzeug zeigt den Xbox-Startbildschirm (`gamingservicesui`); er muss nach jedem Ausgang weg."""
    code = _ps_code(_text(RAUCH / "bauen_marken.ps1"))
    vier = "Get-Process fspackagetool, FlightSimulator2024, gamelaunchhelper, gamingservicesui"
    funktion = code.split("function Raeum-Auf {", 1)[1].split("\n}", 1)[0]
    assert vier in funktion, "die Aufräum-Funktion selbst nennt die vier Prozesse des 2024er Baus"
    assert "Stop-Process -Force" in funktion
    assert "FlightSimulator," not in funktion.replace("FlightSimulator2024", ""), "nie der Prozess des 2020er Simulators"
    # ⭐ PFLICHT: in einem `finally`, damit es auch bei Timeout, Fehler und Strg+C läuft
    assert "try {" in code and "\nfinally {" in code
    finally_block = code.split("\nfinally {", 1)[1].split("\n}", 1)[0]
    assert "Remove-Job $auftrag" in finally_block
    assert "Raeum-Auf" in [z.strip() for z in finally_block.split("\n")], "UNBEDINGT, nicht nur im Erfolgsfall"
    # Der Timeout-Pfad (`exit 1`) kommt NACH dem finally — die Prozesse sind da schon weg.
    assert code.index("\nfinally {") < code.index("exit 1")
    # und nach dem finally wird kontrolliert, ob noch etwas lebt
    assert vier in code.split("\nfinally {", 1)[1]


def test_bauen_marken_ps1_bricht_ab_wenn_ein_simulator_laeuft_und_raeumt_nur_das_eigene_weg():
    code = _ps_code(_text(RAUCH / "bauen_marken.ps1"))
    assert "Get-Process FlightSimulator, FlightSimulator2024" in code and "-not $Trotzdem" in code
    assert "Join-Path $hier 'Packages\\devprops-friesenmarken'" in code
    assert "(Join-Path $hier '_PackageInt2024')" in code and "'_PackageInt'" not in code, "nie der 2020er Zwischenordner"
    assert "devprops-friesenrauch" not in code, "das Rauchpaket bleibt unberührt"


def test_bauen_marken_ps1_wartet_mit_vollem_pfad_und_prueft_die_erweiterung_im_fertigen_gltf():
    code = _ps_code(_text(RAUCH / "bauen_marken.ps1"))
    # Ruhe-Erkennung mit vollem Pfad, kein Platzhalter (20.09.2026: acht Minuten vergeblich gewartet)
    assert ("Get-ChildItem -LiteralPath $paket -Recurse -File -ErrorAction SilentlyContinue |\n"
            "                   Where-Object { $_.LastWriteTime -gt $start }") in code
    assert '"$paket*"' not in code and "devprops-friesenmarken*" not in code
    # die Probe, wegen der es das Skript gibt: die Erweiterung steht im FERTIGEN glTF
    assert "-Pattern 'ASOBO_material_emissive' -Quiet" in code
    assert code.count("exit 2") == 2, "Exit 2 bei fehlender Erweiterung UND bei fehlenden Modellen"


def test_bauen_ps1_bleibt_beim_2020er_sdk_und_beim_rauchprojekt():
    ps = _text(RAUCH / "bauen.ps1")
    assert "$sdk2020" in ps and "$sdk2024" not in ps and "FriesenRauch.xml" in ps
    assert "FriesenMarken" not in ps and "friesenmarken" not in ps, "der Rauchbau fasst die Marken nicht an"


def test_paket_ps1_nimmt_vier_teile_auf_die_marken_zuletzt():
    ps = _text(MSFS / "paket.ps1")
    assert '$markenPaket = "devprops-friesenmarken"' in ps
    assert ('$rauchPakete = @("devprops-friesenrauch", "devprops-friesenrauch-mat",\n'
            '                 "devprops-friesenrauch-vfx", $markenPaket)') in ps, "vier Teile, die Marken zuletzt"
    # die Warnung nennt das richtige Bauskript
    assert '$bauSkript = if ($rp -eq $markenPaket) { "bauen_marken.ps1" } else { "bauen.ps1" }' in ps
    assert 'Write-Warning ("Teilpaket fehlt: $rp' in ps


def test_paket_ps1_raeumt_alte_marken_aus_dem_rauchteil_weg_bevor_die_neuen_kommen(mb):
    ps = _text(MSFS / "paket.ps1")
    kopie = ps.index("Get-ChildItem $pfad -Directory | Copy-Item -Destination $paket -Recurse -Force")
    weg = ps.index('$alteMarken = Join-Path $paket "SimObjects\\Misc\\FrsMarke"')
    assert kopie < weg, "erst kopieren, dann den alten Markenordner des Rauchteils wegräumen"
    block = ps[kopie:kopie + 900]
    assert "if ($rp -ne $markenPaket)" in block and "Remove-Item $alteMarken -Recurse -Force" in block
    # der Ordner, den der Markenteil liefert, stimmt mit dem des Generators überein
    assert mb.HERSTELLER_ORDNER == "FrsMarke"


def test_paket_ps1_kennt_den_neuen_teil_auch_beim_wegraeumen_alter_einzelordner_und_in_den_credits():
    ps = _text(MSFS / "paket.ps1")
    assert "$am.title -like 'friesenrauch*' -or $am.title -like 'friesenmarken*'" in ps
    assert ("Wuerfel, Lichtsaeulen, Punktlicht (FrsWuerfel_*, FrsSaeule_*, FrsLicht_Warm)\n"
            "    Eigenes Werk, devprops. Reine Farbmodelle ohne Textur") in ps


def test_die_liesmich_erklaert_zwei_sdks_und_warum():
    text = _text(RAUCH / "LIESMICH.md")
    assert "Zwei SDKs" in text and "bauen_marken.ps1" in text and "FriesenMarken.xml" in text
    assert "ASOBO_material_emissive" in text and "entfernt" in text and "2024er SDK" in text
    assert "Ungemessen" in text, "ob ein 2024-kompiliertes Modell in MSFS 2020 lädt, ist offen"
    # Nutzerkorrektur: der 2024er Bau zeigt den Xbox-Startbildschirm, und das Aufräumen ist Pflicht
    assert "Xbox-Startbildschirm" in text and "gamingservicesui" in text and "**Pflicht**" in text
    assert "finally" in text and "Timeout" in text


def test_bauen_marken_ps1_erklaert_startbildschirm_und_pflicht_im_kopf():
    ps = _text(RAUCH / "bauen_marken.ps1")
    assert "XBOX-STARTBILDSCHIRM" in ps and "PFLICHT, KEIN BEIWERK" in ps and "in einem\n# `finally`" in ps


@pytest.mark.skipif(not (shutil.which("pwsh") or shutil.which("powershell")), reason="kein PowerShell zum Parsen")
def test_die_powershell_skripte_sind_syntaktisch_gueltig():
    exe = shutil.which("pwsh") or shutil.which("powershell")
    for pfad in (RAUCH / "bauen_marken.ps1", RAUCH / "bauen.ps1", MSFS / "paket.ps1"):
        # Der Parser führt nichts aus; er liest nur.
        kommando = ("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("
                    f"'{pfad}',[ref]$t,[ref]$e);exit $e.Count")
        r = subprocess.run([exe, "-NoProfile", "-Command", kommando], capture_output=True, text=True)
        assert r.returncode == 0, (pfad.name, r.stdout, r.stderr)


def test_die_endgueltigen_vorgaben_und_der_schalter_stehen_wie_nach_testrunde_2(mb):
    """Gebunden an die Messung (Luminanz der hellsten Pixel, Runway-Feuer = 144): Würfel M80 142 / M160 173,
    Säulen 168 / 195, Licht K400_I400 97 / K400_I1600 176. Endgültig (nach der Endabnahme): 80, 0,85, 400, 1600,
    Testtitel AUS; 120 und 160 sind nur gemessen."""
    assert mb.EMISSIVE_NACHT == 80.0
    assert mb.SAEULE_ALPHA_UNTEN == 0.85
    assert mb.LICHT_KERN_NACHT == 400.0
    assert mb.LICHT_STAERKE == 1600.0
    assert mb.MIT_TESTTITELN is False, "im Repo und im Paket stehen die 15 endgültigen Titel, keine Testtitel"


def test_der_kopfkommentar_haelt_die_messwerte_der_testrunde_2_fest():
    text = _text(RAUCH / "marken_bauen.py")
    kopf = text.split('"""', 2)[1]
    assert "Testrunde 2" in kopf and "Runway-Feuer = 144" in kopf
    for zahl in ("85", "112", "142", "173", "111", "138", "168", "195", "K100_I100   38", "K400_I1600  176"):
        assert zahl in kopf, zahl
    assert "`EMISSIVE_NACHT` = 80" in kopf and "`LICHT_STAERKE` = 1600" in kopf
    assert "**80 ist gewählt**" in kopf and "Die Stufen 120 und 160 sind nur gemessen" in kopf
    assert "100 Segmente zu je 1 m" in kopf and "waagerechten Stufen sichtbar" in kopf
