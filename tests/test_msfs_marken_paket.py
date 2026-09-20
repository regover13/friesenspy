# -*- coding: utf-8 -*-
"""Die MSFS-Marken der FriesenBrügge: Würfel, Lichtsäulen, Punktlicht (20.09.2026).

`friesenbruegge/msfs-rauch/marken_bauen.py` schreibt die Quellen für 7 Würfel, 7 Säulen und 1 Licht
(alles Titel `Frs…`, KEINE Texturen, in MSFS 2020 und 2024 dieselben Dateien). Die Säule ist seit dem
Flugtest vom 20.09.2026 ein Scheinwerferstrahl aus 25 gestapelten Segmenten mit je eigenem Material. Der Simulator ist von
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
import struct
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


@pytest.fixture(scope="module")
def mb():
    return _marken_bauen()


@pytest.fixture(scope="module")
def ausgabe(mb, tmp_path_factory):
    ziel = tmp_path_factory.mktemp("marken") / "FrsMarke"
    n = mb.marken_schreiben(ziel)
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


def test_die_saeule_ist_ein_stapel_aus_25_achteck_segmenten(mb, ausgabe):
    ziel, _ = ausgabe
    assert mb.SAEULE_SEGMENTE == 25
    for b in _titel(ziel, "FrsSaeule_"):
        g, prims = _prims(ziel, b)
        assert len(prims) == 25 and len(g["materials"]) == 25, "je Segment eine Primitive UND ein Material"
        assert [p["material"] for p in g["meshes"][0]["primitives"]] == list(range(25))
        for i, (ecken, *_r) in enumerate(prims):
            assert len(ecken) == 32, "ein Achteck ohne Deckel: acht Seiten zu vier Ecken"
            ys = [e[1] for e in ecken]
            # Die Segmente sind je 4 m hoch und stoßen lückenlos aneinander.
            assert min(ys) == pytest.approx(4.0 * i) and max(ys) == pytest.approx(4.0 * (i + 1))


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
    """Alpha fällt linear von 0,55 auf 0,02, das Eigenlicht mit (1 − t)^1,2; t = Höhe der Segmentmitte / 100 m."""
    ziel, _ = ausgabe
    for name, rgb in mb.SAEULEN_FARBEN.items():
        g = _gltf(ziel, f"saeule_{name}", f"FrsSaeule_{name.capitalize()}")
        lin = [_linear(k) for k in rgb]
        alphas, emis = [], []
        for i, m in enumerate(g["materials"]):
            t = (i + 0.5) / 25
            assert m["alphaMode"] == "BLEND" and m["doubleSided"] is True
            f = m["pbrMetallicRoughness"]["baseColorFactor"]
            assert f[:3] == pytest.approx(lin, abs=1e-5), "die Grundfarbe bleibt in jedem Segment dieselbe"
            assert f[3] == pytest.approx(0.55 + (0.02 - 0.55) * t, abs=1e-5)
            assert m["emissiveFactor"] == pytest.approx([k * (1 - t) ** 1.2 for k in lin], abs=1e-5)
            alphas.append(f[3])
            emis.append(m["emissiveFactor"][0])
        assert alphas == sorted(alphas, reverse=True) and len(set(alphas)) == 25, "Alpha fällt streng monoton"
        assert emis == sorted(emis, reverse=True) and len(set(emis)) == 25, "Eigenlicht fällt streng monoton"
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
    """Belegt an Asobos `Point.NNN` (Seilwinde `ESW_2B`): Knoten ohne Mesh, `cone_angle` 360, nur nachts."""
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
    assert licht["intensity"] == 8.0, "Nutzerwunsch nach dem 2020er Nachttest: etwas heller (vorher 5,0)"
    assert licht["flash_frequency"] == 0 and licht["rotation_speed"] == 0 and licht["has_simmetry"] is False
    assert "ASOBO_macro_light" in g["extensionsUsed"]
    assert "extensionsRequired" not in g, "Asobo verlangt die Erweiterung nicht (dort steht nur MSFT_texture_dds)"


def test_das_licht_haengt_wie_bei_asobo_unter_einem_knoten_light_und_hat_einen_unsichtbaren_traeger(ausgabe):
    ziel, _ = ausgabe
    g = _gltf(ziel, "licht_warm", "FrsLicht_Warm")
    nodes = g["nodes"]
    elternteil = [n for n in nodes if any(nodes[c].get("name") == "Point" for c in n.get("children", []))]
    assert len(elternteil) == 1 and elternteil[0]["name"] == "Light"
    traeger = [n for n in nodes if "mesh" in n]
    assert len(traeger) == 1
    assert "ASOBO_material_invisible" in g["materials"][0]["extensions"]
    ecken = _prims(ziel, next(b for b in _sim_cfg(ziel) if b["title"] == "FrsLicht_Warm"))[1][0][0]
    assert max(e[1] for e in ecken) <= 0.1, "winzig"
    # Beide Wurzelknoten stehen in der Szene, und `Point` liegt über dem Boden.
    assert set(g["scenes"][0]["nodes"]) == {0, 1}
    assert next(n for n in nodes if n.get("name") == "Point")["translation"][1] > 0


def test_nur_das_licht_hat_ein_lichtknoten(ausgabe):
    ziel, _ = ausgabe
    for b in _sim_cfg(ziel):
        text = json.dumps(_gltf(ziel, b["model"], b["title"]))
        assert ("ASOBO_macro_light" in text) == (b["title"] == "FrsLicht_Warm"), b["title"]


# ---- das Paket ---------------------------------------------------------------------------

def test_die_paketdefinition_nimmt_die_marken_als_dritte_gruppe_auf():
    text = (RAUCH / "PackageDefinitions" / "devprops-friesenrauch.xml").read_text(encoding="utf-8")
    assert 'AssetGroup Name="MarkenObjects"' in text
    assert "PackageSources\\SimObjects\\Misc\\FrsMarke\\" in text and "SimObjects\\Misc\\FrsMarke\\" in text
    # Rauch und Seehund bleiben, wie sie waren.
    assert 'Name="SimObjects"' in text and 'Name="SeehundObjects"' in text


def test_die_eingecheckten_quellen_sind_der_stand_des_generators(mb, ausgabe):
    """Wer den Generator ändert und `paket_bauen.py` nicht laufen lässt, checkt veraltete Quellen ein."""
    ziel, _ = ausgabe
    eingecheckt = RAUCH / "PackageSources" / "SimObjects" / "Misc" / "FrsMarke"
    assert eingecheckt.is_dir(), "python paket_bauen.py ausführen und die Quellen einchecken"
    dateien = sorted(p.relative_to(ziel).as_posix() for p in ziel.rglob("*") if p.is_file())
    assert dateien == sorted(p.relative_to(eingecheckt).as_posix() for p in eingecheckt.rglob("*") if p.is_file())
    for rel in dateien:
        assert (ziel / rel).read_bytes().replace(b"\r\n", b"\n") == (eingecheckt / rel).read_bytes().replace(b"\r\n", b"\n"), rel
