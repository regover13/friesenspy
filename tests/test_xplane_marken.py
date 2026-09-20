# -*- coding: utf-8 -*-
"""Die X-Plane-Marken der FriesenBrügge: Würfel, Lichtsäulen, ein Licht (20.09.2026).

Nutzerwunsch: *„Würfel in den Friesenfarben. Säule in Weiß + Friesenfarben"*, *„Würfel ca. 3 m, Säule ca. 100 m hoch und
schmal"*, *„ein einfaches Licht"*. Eigene OBJ8-Dateien, erzeugt von `friesenbruegge/xplane/marken_bauen.py`.

⚠ **X-Plane wurde nicht gestartet.** Was hier gebunden ist, ist das, was sich ohne Simulator prüfen lässt: Format,
Zählungen, Maße, Farben, Flächenrichtung — und dass die Lichtzeilen die Parameterzahl haben, die `lights.txt` der
Installation verlangt. Ob es nachts leuchtet, sagt nur ein Flug.
"""
import importlib.util
import math
import re
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
XP = WURZEL / "friesenbruegge" / "xplane"
OBJEKTE = XP / "objekte"
LIGHTS_TXT = Path(r"D:\X-Plane 12\Resources\bitmaps\world\lites\lights.txt")


def _laden(pfad: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture(scope="module")
def marken():
    return _laden(XP / "marken_bauen.py", "xplane_marken_bauen")


@pytest.fixture(scope="module")
def farben():
    return _laden(XP / "rauch_bauen.py", "xplane_rauch_bauen_test").FARBEN


def _lesen(pfad: Path) -> dict:
    """Ein OBJ8 in seine Teile zerlegen: Kopf, Zählung, Eckpunkte, Indizes, TRIS, Attribute, Lichter."""
    zeilen = pfad.read_text(encoding="utf-8").splitlines()
    assert zeilen[:3] == ["I", "800", "OBJ"], f"{pfad.name}: Kopf"
    o = {"vt": [], "idx": [], "tris": None, "attr": {}, "lichter": [], "punkte": None, "textur": None}
    for z in zeilen[3:]:
        teile = z.split()
        if not teile or teile[0].startswith("#"):
            continue
        k = teile[0]
        if k == "TEXTURE":
            o["textur"] = teile[1] if len(teile) > 1 else ""
        elif k == "POINT_COUNTS":
            o["punkte"] = tuple(int(x) for x in teile[1:5])
        elif k == "VT":
            o["vt"].append(tuple(float(x) for x in teile[1:9]))
        elif k == "IDX10":
            o["idx"] += [int(x) for x in teile[1:11]]
        elif k == "IDX":
            o["idx"].append(int(teile[1]))
        elif k == "TRIS":
            o["tris"] = (int(teile[1]), int(teile[2]))
        elif k in ("ATTR_diffuse_rgb", "ATTR_emission_rgb"):
            o["attr"][k] = tuple(float(x) for x in teile[1:4])
        elif k == "LIGHT_PARAM":
            o["lichter"].append((teile[1], teile[2:]))
        elif k in ("ATTR_no_cull", "ATTR_LOD"):
            o["attr"][k] = teile[1:]
    return o


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _kreuz(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


WUERFEL = ["navy", "hellblau", "rot", "orange", "signalrot", "signalorange"]
SAEULEN = WUERFEL + ["weiss"]


# ---- die Dateimenge ---------------------------------------------------------------------

def test_es_gibt_sechs_wuerfel_sieben_saeulen_und_ein_licht():
    da = {p.name for p in OBJEKTE.iterdir()}
    for n in WUERFEL:
        assert f"wuerfel_{n}.obj" in da
    for n in SAEULEN:
        assert f"saeule_{n}.obj" in da
    assert "licht_warm.obj" in da and "marken.png" in da


def test_der_workflow_kopiert_den_ganzen_objekte_ordner():
    """Neue Dateien kommen so von allein ins Plugin — kein Namenskatalog, der nachgezogen werden müsste."""
    yml = (WURZEL / ".github" / "workflows" / "bruegge-xplane.yml").read_text(encoding="utf-8")
    assert "cp friesenbruegge/xplane/objekte/* FriesenBruegge/objekte/" in yml


def test_die_farben_sind_in_beiden_simulatoren_dieselben(marken, farben):
    msfs = _laden(WURZEL / "friesenbruegge" / "msfs-rauch" / "rauch_bauen.py", "msfs_rauch_bauen_test").FARBEN
    assert dict(msfs) == dict(farben) == dict(marken.FARBEN), "Friesenfarben: eine Quelle, drei Orte"
    assert set(farben) == set(WUERFEL)


# ---- Format aller Mesh-Dateien ---------------------------------------------------------

@pytest.mark.parametrize("name", [f"wuerfel_{n}" for n in WUERFEL] + [f"saeule_{n}" for n in SAEULEN])
def test_zaehlungen_und_indizes_stimmen(name):
    o = _lesen(OBJEKTE / f"{name}.obj")
    assert o["punkte"] == (len(o["vt"]), 0, 0, len(o["idx"])), "POINT_COUNTS = VT / 0 / 0 / IDX"
    assert o["tris"] == (0, len(o["idx"])) and len(o["idx"]) % 3 == 0
    assert all(0 <= i < len(o["vt"]) for i in o["idx"])


@pytest.mark.parametrize("name", [f"wuerfel_{n}" for n in WUERFEL] + [f"saeule_{n}" for n in SAEULEN])
def test_normalen_sind_normiert_und_die_flaechen_zeigen_nach_aussen(name):
    """Vorderseite = gegen den Uhrzeigersinn von außen gesehen: (v1−v0)×(v2−v0) muss zur Normalen zeigen."""
    o = _lesen(OBJEKTE / f"{name}.obj")
    for x in o["vt"]:
        assert math.sqrt(x[3] ** 2 + x[4] ** 2 + x[5] ** 2) == pytest.approx(1.0, abs=1e-3)
    for t in range(0, len(o["idx"]), 3):
        a, b, c = (o["vt"][i] for i in o["idx"][t:t + 3])
        kreuz = _kreuz(_sub(b[:3], a[:3]), _sub(c[:3], a[:3]))
        assert _dot(kreuz, a[3:6]) > 0, f"Dreieck {t // 3} zeigt nach innen"


# ---- Würfel ----------------------------------------------------------------------------

@pytest.mark.parametrize("n", WUERFEL)
def test_der_wuerfel_ist_drei_meter_und_steht_auf_dem_ursprung(n):
    o = _lesen(OBJEKTE / f"wuerfel_{n}.obj")
    xs, ys, zs = zip(*(v[:3] for v in o["vt"]))
    assert (min(xs), max(xs)) == (-1.5, 1.5) and (min(zs), max(zs)) == (-1.5, 1.5)
    assert (min(ys), max(ys)) == (0.0, 3.0), "Ursprung Mitte der Unterseite"
    assert (len(o["vt"]), len(o["idx"])) == (24, 36), "sechs Flächen mit eigenen Ecken, zwölf Dreiecke"
    assert o["textur"] == "", "massiver Würfel, keine Textur"


@pytest.mark.parametrize("n", WUERFEL)
def test_die_wuerfelfarbe_ist_die_friesenfarbe_mit_leichtem_leuchten(n, farben):
    o = _lesen(OBJEKTE / f"wuerfel_{n}.obj")
    soll = tuple(c / 255.0 for c in farben[n])
    assert o["attr"]["ATTR_diffuse_rgb"] == pytest.approx(soll, abs=1e-3)
    assert o["attr"]["ATTR_emission_rgb"] == pytest.approx(tuple(c * 0.35 for c in soll), abs=1e-3)


# ---- Säulen ----------------------------------------------------------------------------

@pytest.mark.parametrize("n", SAEULEN)
def test_die_saeule_ist_hundert_meter_hoch_und_achtzig_zentimeter_breit(n):
    o = _lesen(OBJEKTE / f"saeule_{n}.obj")
    ys = [v[1] for v in o["vt"]]
    assert (min(ys), max(ys)) == (0.0, 100.0)
    # Breite = Abstand zweier gegenüberliegender FLÄCHEN: jede Seitenfläche liegt 0,4 m von der Achse.
    seiten = [v for v in o["vt"] if abs(v[4]) < 1e-6]
    assert len(seiten) == 32, "acht Seitenflächen zu je vier Ecken"
    for v in seiten:
        assert _dot(v[:3], v[3:6]) == pytest.approx(0.4, abs=2e-3)
    assert (len(o["vt"]), len(o["idx"])) == (40, 66), "Achteck: 8 Seiten (16 Dreiecke) + Deckel (6)"


@pytest.mark.parametrize("n", SAEULEN)
def test_die_saeule_leuchtet_in_ihrer_farbe_und_ist_halbtransparent(n, marken, farben):
    o = _lesen(OBJEKTE / f"saeule_{n}.obj")
    farbe = (255, 255, 255) if n == "weiss" else farben[n]
    soll = tuple(c / 255.0 for c in farbe)
    assert o["attr"]["ATTR_diffuse_rgb"] == pytest.approx(soll, abs=1e-3)
    assert o["attr"]["ATTR_emission_rgb"] == pytest.approx(soll, abs=1e-3)
    assert o["textur"] == "marken.png", "die Textur trägt das Alpha — ohne sie wäre die Säule undurchsichtig"
    assert "ATTR_no_cull" in o["attr"], "dünn und halbtransparent: von innen wie von außen sichtbar"


def test_die_textur_hat_ein_halbes_alpha():
    from PIL import Image
    bild = Image.open(OBJEKTE / "marken.png")
    assert bild.size == (4, 4) and bild.mode == "RGBA"
    r, g, b, a = bild.getpixel((1, 1))
    assert (r, g, b) == (255, 255, 255) and 100 < a < 200


# ---- das Licht -------------------------------------------------------------------------

def test_das_licht_hat_glueh_punkt_und_lichtfleck_in_warmweiss():
    o = _lesen(OBJEKTE / "licht_warm.obj")
    assert o["punkte"] == (0, 0, 0, 0) and o["vt"] == [] and o["tris"] is None, "keine Geometrie"
    namen = [n for n, _ in o["lichter"]]
    assert namen == ["spot_params_bb_pm", "spot_params_sp_pm"]
    for _, p in o["lichter"]:
        assert (float(p[0]), float(p[1]), float(p[2])) == (0.0, 0.5, 0.0), "ca. 0,5 m über dem Ursprung"
        assert (float(p[3]), float(p[4]), float(p[5])) == (1.0, 0.84, 0.6), "warmweiß"


def test_die_parameterzahl_stimmt_mit_lights_txt_ueberein():
    """`LIGHT_PARAM_DEF` in Laminars `lights.txt` nennt je Vorlage, wie viele Werte hinter x y z folgen."""
    if LIGHTS_TXT.exists():
        text = LIGHTS_TXT.read_text(encoding="utf-8", errors="replace")
        soll = {m.group(1): int(m.group(2)) for m in
                re.finditer(r"^LIGHT_PARAM_DEF[ \t]+(\S+)[ \t]+(\d+)", text, re.M)}
    else:  # ohne X-Plane-Installation: der Stand vom 20.09.2026
        soll = {"spot_params_bb_pm": 8, "spot_params_sp_pm": 9}
    o = _lesen(OBJEKTE / "licht_warm.obj")
    for name, p in o["lichter"]:
        assert name in soll, f"{name}: keine Vorlage in lights.txt"
        assert len(p) - 3 == soll[name], f"{name}: {len(p) - 3} Werte statt {soll[name]}"


def test_das_licht_sieht_man_weit():
    o = _lesen(OBJEKTE / "licht_warm.obj")
    assert o["attr"]["ATTR_LOD"] == ["0", "10000"]


# ---- der Generator ---------------------------------------------------------------------

def test_die_dateien_im_repo_sind_die_des_generators(marken, tmp_path, monkeypatch):
    """Wer den Generator ändert, muss die Dateien neu erzeugen — sonst läuft das Plugin mit altem Stand."""
    monkeypatch.setattr(marken, "ZIEL", tmp_path)
    marken.main()
    erzeugt = {p.name for p in tmp_path.iterdir()}
    assert len(erzeugt) == 15
    for name in erzeugt:
        assert (tmp_path / name).read_bytes() == (OBJEKTE / name).read_bytes(), name
