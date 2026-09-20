# -*- coding: utf-8 -*-
"""Die X-Plane-Marken der FriesenBrügge: Würfel, Lichtsäulen, ein Licht (20.09.2026).

Nutzerwunsch: *„Würfel in den Friesenfarben. Säule in Weiß + Friesenfarben"*, *„Würfel ca. 3 m"*, *„ein einfaches
Licht"*. Die Säule ist ein **Scheinwerferstrahl**: 100 m, Achteck unten 4 m / oben 6 m, Deckkraft 0,55 → 0,02
(Albedo-Textur, `v` = Höhe) und Leuchten `(1 − t)^1,2` (LIT-Textur). Das Weiß ist warm (`WEISS` = 255/240/200), es gibt
sieben Würfel und sieben Säulen. Eigene OBJ8-Dateien, erzeugt von `friesenbruegge/xplane/marken_bauen.py`.

⭐ **Die Nachthelligkeit kommt aus der LIT-Textur, nicht aus `ATTR_emission_rgb`, und NICHT aus `GLOBAL_luminance`.**
Der erste Flug (20.09.2026, nachts) zeigte die Marken „viel zu dunkel"; die OBJ8-Spezifikation führt
`ATTR_emission_rgb` als „[deprecated]", das Leuchten steckt in `TEXTURE_LIT`. Die Würfel hatten außerdem keine
Albedo-Textur und waren bei Tag fast schwarz. Die Testleiter im X-Plane-Flug (nachts) hat gemessen:

| Stufe (Signalorange)                 | Luminanz | Aufhellung neben der Säule |
|--------------------------------------|----------|----------------------------|
| `Lstd` — ohne `GLOBAL_luminance`     | 125      | 49                         |
| `L2500` (überbelichtet, gelb-weiß)   | ~250     | 73                         |
| `L40000` (überbelichtet, gelb-weiß)  | ~250     | 220                        |
| Bezug: Runway-Feuer ~144–153, Hintergrund 24                                  |

Deshalb stehen Würfel und Säulen **ohne** `GLOBAL_luminance`, das Licht auf 4500 cd (Laminars Randfeuer) mit 9000 cd im
Lichtfleck. Die Testleiter ist abgeschaltet (`MIT_TESTOBJEKTEN = False`); ihre Erzeugung ist hier weiter gebunden.

⚠ **X-Plane wurde nicht gestartet.** Was hier gebunden ist, ist das, was sich ohne Simulator prüfen lässt: Format,
Zählungen, Maße, Farben, Flächenrichtung, Texturen — und dass die Lichtzeilen die Parameterzahl haben, die `lights.txt`
der Installation verlangt. Ob es nachts leuchtet, sagt nur ein Flug.
"""
import hashlib
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
    o = {"vt": [], "idx": [], "tris": None, "abschnitte": [], "attr": {}, "lichter": [], "punkte": None,
         "textur": None, "lit": None, "nits": None, "zeilen": zeilen}
    for z in zeilen[3:]:
        teile = z.split()
        if not teile or teile[0].startswith("#"):
            continue
        k = teile[0]
        if k == "TEXTURE":
            o["textur"] = teile[1] if len(teile) > 1 else ""
        elif k == "TEXTURE_LIT":
            o["lit"] = teile[1]
        elif k == "GLOBAL_luminance":
            o["nits"] = int(teile[1])
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
            o["abschnitte"].append((int(teile[1]), int(teile[2]), None))
        elif k == "ATTR_diffuse_rgb":
            o["attr"][k] = tuple(float(x) for x in teile[1:4])
        elif k == "LIGHT_PARAM":
            o["lichter"].append((teile[1], teile[2:]))
        elif k in ("ATTR_no_cull", "ATTR_blend", "ATTR_LOD", "ATTR_emission_rgb"):
            o["attr"][k] = teile[1:]
    return o


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _kreuz(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


FRIESEN = ["navy", "hellblau", "rot", "orange", "signalrot", "signalorange"]
WUERFEL = FRIESEN + ["weiss"]
SAEULEN = FRIESEN + ["weiss"]
WEISS = (255, 240, 200)                 # „Scheinwerferweiß" — identisch zur MSFS-Seite
ALLE_OBJ = [f"wuerfel_{n}" for n in WUERFEL] + [f"saeule_{n}" for n in SAEULEN]


def _farbe(n, farben):
    return WEISS if n == "weiss" else farben[n]


def _lit(farbe):
    """Leuchtfarbe: Farbton der Friesenfarbe, größter Kanal auf 255 gezogen (Gegenstück zu `lit_farbe`)."""
    m = max(farbe)
    return tuple(round(c * 255.0 / m) for c in farbe)


def _bild(name: str):
    from PIL import Image
    return Image.open(OBJEKTE / name)


# ---- die Dateimenge ---------------------------------------------------------------------

def test_es_gibt_sieben_wuerfel_sieben_saeulen_und_ein_licht():
    da = {p.name for p in OBJEKTE.iterdir()}
    for n in WUERFEL:
        assert f"wuerfel_{n}.obj" in da
    for n in SAEULEN:
        assert f"saeule_{n}.obj" in da
    assert "licht_warm.obj" in da
    eigene = {n for n in da if n.endswith(".obj") and n.split("_")[0] in ("wuerfel", "saeule", "licht")}
    assert len(eigene) == 15, "7 Würfel + 7 Säulen + 1 Licht"


def test_jede_textur_die_ein_objekt_nennt_liegt_daneben():
    """Ein Objekt ohne seine Textur zeichnet X-Plane weiß oder gar nicht — und niemand merkt es beim Bau."""
    for p in sorted(OBJEKTE.glob("*.obj")):
        if p.name.split("_")[0] not in ("wuerfel", "saeule", "licht", "test"):
            continue
        o = _lesen(p)
        for tex in (o["textur"], o["lit"]):
            if tex:
                assert (OBJEKTE / tex).exists(), f"{p.name}: {tex} fehlt"


def test_der_workflow_kopiert_den_ganzen_objekte_ordner():
    """Neue Dateien (auch die PNG) kommen so von allein ins Plugin — kein Namenskatalog, der nachgezogen werden müsste."""
    yml = (WURZEL / ".github" / "workflows" / "bruegge-xplane.yml").read_text(encoding="utf-8")
    assert "cp friesenbruegge/xplane/objekte/* FriesenBruegge/objekte/" in yml


def test_die_farben_sind_in_beiden_simulatoren_dieselben(marken, farben):
    msfs = _laden(WURZEL / "friesenbruegge" / "msfs-rauch" / "rauch_bauen.py", "msfs_rauch_bauen_test").FARBEN
    assert dict(msfs) == dict(farben) == dict(marken.FARBEN), "Friesenfarben: eine Quelle, drei Orte"
    assert set(farben) == set(FRIESEN)


def test_das_scheinwerferweiss_ist_eine_konstante_fuer_saeule_und_wuerfel(marken):
    """Warmes, leicht gelbliches Weiß (255, 240, 200) — die Farbe muss zwischen MSFS und X-Plane gleich bleiben."""
    assert marken.WEISS == WEISS
    assert marken.SAEULEN["weiss"] == WEISS and marken.WUERFEL["weiss"] == WEISS


# ---- Format aller Mesh-Dateien ---------------------------------------------------------

@pytest.mark.parametrize("name", ALLE_OBJ)
def test_zaehlungen_und_indizes_stimmen(name):
    o = _lesen(OBJEKTE / f"{name}.obj")
    assert o["punkte"] == (len(o["vt"]), 0, 0, len(o["idx"])), "POINT_COUNTS = VT / 0 / 0 / IDX"
    assert len(o["idx"]) % 3 == 0 and all(0 <= i < len(o["vt"]) for i in o["idx"])
    nächster = 0
    for start, anzahl, _ in o["abschnitte"]:
        assert start == nächster and anzahl % 3 == 0
        nächster += anzahl
    assert nächster == len(o["idx"]), "die TRIS-Abschnitte decken alle Indizes lückenlos ab"


@pytest.mark.parametrize("name", ALLE_OBJ)
def test_normalen_sind_normiert_und_die_flaechen_zeigen_nach_aussen(name):
    """Vorderseite = gegen den Uhrzeigersinn von außen gesehen: (v1−v0)×(v2−v0) muss zur Normalen zeigen."""
    o = _lesen(OBJEKTE / f"{name}.obj")
    for x in o["vt"]:
        assert math.sqrt(x[3] ** 2 + x[4] ** 2 + x[5] ** 2) == pytest.approx(1.0, abs=1e-3)
    for t in range(0, len(o["idx"]), 3):
        a, b, c = (o["vt"][i] for i in o["idx"][t:t + 3])
        kreuz = _kreuz(_sub(b[:3], a[:3]), _sub(c[:3], a[:3]))
        assert _dot(kreuz, a[3:6]) > 0, f"Dreieck {t // 3} zeigt nach innen"


@pytest.mark.parametrize("name", ALLE_OBJ + ["licht_warm"])
def test_kein_veraltetes_emissiv_mehr(name):
    """`ATTR_emission_rgb` ist in X-Plane 12 „[deprecated]" (OBJ8-Spezifikation) — die Nacht kommt aus TEXTURE_LIT."""
    assert "ATTR_emission_rgb" not in _lesen(OBJEKTE / f"{name}.obj")["attr"]


# ---- Würfel ----------------------------------------------------------------------------

@pytest.mark.parametrize("n", WUERFEL)
def test_der_wuerfel_ist_drei_meter_und_steht_auf_dem_ursprung(n):
    o = _lesen(OBJEKTE / f"wuerfel_{n}.obj")
    xs, ys, zs = zip(*(v[:3] for v in o["vt"]))
    assert (min(xs), max(xs)) == (-1.5, 1.5) and (min(zs), max(zs)) == (-1.5, 1.5)
    assert (min(ys), max(ys)) == (0.0, 3.0), "Ursprung Mitte der Unterseite"
    assert (len(o["vt"]), len(o["idx"])) == (24, 36), "sechs Flächen mit eigenen Ecken, zwölf Dreiecke"


@pytest.mark.parametrize("n", WUERFEL)
def test_der_wuerfel_hat_eine_albedo_und_eine_leuchtfarbe(n, farben):
    """Bei Tag: weiße Albedo × ATTR_diffuse_rgb (wie die Säulen, dort im Flug in Ordnung). Bei Nacht: TEXTURE_LIT."""
    o = _lesen(OBJEKTE / f"wuerfel_{n}.obj")
    farbe = _farbe(n, farben)
    assert o["textur"] == "marken_weiss.png", "ohne Textur war der Würfel bei Tag fast schwarz"
    assert o["attr"]["ATTR_diffuse_rgb"] == pytest.approx(tuple(c / 255.0 for c in farbe), abs=1e-3)
    assert o["lit"] == f"wuerfel_{n}_LIT.png"
    assert o["nits"] is None and "GLOBAL_luminance" not in "\n".join(o["zeilen"]), \
        "gemessen: jede Stufe ab 2500 Nits überbelichtet, ohne die Zeile stimmt die Farbe"
    bild = _bild(o["lit"])
    assert bild.size == (4, 4) and bild.mode == "RGB"
    assert bild.getpixel((1, 1)) == _lit(farbe), "Farbton der Friesenfarbe, voll hell"


def test_die_albedo_der_wuerfel_ist_opak_weiss():
    bild = _bild("marken_weiss.png")
    assert bild.size == (4, 4) and bild.mode == "RGB"
    assert all(bild.getpixel((x, y)) == (255, 255, 255) for x in range(4) for y in range(4))


def test_die_wuerfelgeometrie_ist_unveraendert():
    """Der Koordinator: „Die Würfel sind gut und bleiben UNVERÄNDERT" — Eckpunkte und Indizes des Flugtest-Stands."""
    def geo(n):
        zeilen = _lesen(OBJEKTE / f"wuerfel_{n}.obj")["zeilen"]
        return hashlib.sha256("\n".join(z for z in zeilen if z.startswith(("VT", "IDX"))).encode()).hexdigest()[:16]
    assert {geo(n) for n in WUERFEL} == {"73f8424c26802bc0"}, "alle sieben teilen dieselbe Geometrie"


# ---- Säulen ----------------------------------------------------------------------------

def _seite(o):
    """Die Ecken der Seitenflächen (ohne Deckel) samt waagerechter Flächennormale."""
    for v in o["vt"]:
        if abs(v[4] - 1.0) < 1e-6:
            continue                                            # Deckel
        yield v, (v[3], 0.0, v[5])


@pytest.mark.parametrize("n", SAEULEN)
def test_die_saeule_ist_hundert_meter_hoch_und_weitet_von_vier_auf_sechs_meter_auf(n):
    """Breite = Abstand gegenüberliegender FLÄCHEN: jede Seitenfläche liegt 2 m (unten) bis 3 m (oben) von der Achse."""
    o = _lesen(OBJEKTE / f"saeule_{n}.obj")
    ys = [v[1] for v in o["vt"]]
    assert (min(ys), max(ys)) == (0.0, 100.0)
    seiten = list(_seite(o))
    assert len(seiten) == 8 * 4, "acht Seitenflächen zu je vier Ecken — ein einziger Körper"
    abstaende = []
    for v, nh in seiten:
        betrag = math.hypot(nh[0], nh[2])
        abstand = _dot(v[:3], (nh[0] / betrag, 0.0, nh[2] / betrag))
        assert abstand == pytest.approx(2.0 + v[1] / 100.0, abs=2e-3), "linear von 2 m auf 3 m"
        abstaende.append((v[1], abstand))
    assert max(a for y, a in abstaende if y == 0.0) == pytest.approx(2.0, abs=1e-3)
    assert min(a for y, a in abstaende if y == 100.0) == pytest.approx(3.0, abs=1e-3)
    assert (len(o["vt"]), len(o["idx"])) == (40, 66), "8 Seiten (16 Dreiecke) + Deckel (6)"


@pytest.mark.parametrize("n", SAEULEN)
def test_die_v_koordinate_laeuft_mit_der_hoehe(n):
    """Nur so können die Texturen (Alpha und LIT) nach oben ausblenden."""
    o = _lesen(OBJEKTE / f"saeule_{n}.obj")
    for v in o["vt"]:
        assert v[6] == pytest.approx(0.5) and v[7] == pytest.approx(v[1] / 100.0, abs=1e-4)


@pytest.mark.parametrize("n", SAEULEN)
def test_die_saeule_hat_albedo_diffuse_und_lit_textur(n, farben):
    o = _lesen(OBJEKTE / f"saeule_{n}.obj")
    farbe = _farbe(n, farben)
    assert o["textur"] == "marken.png", "die Albedo trägt den Alpha-Verlauf"
    assert o["attr"]["ATTR_diffuse_rgb"] == pytest.approx(tuple(c / 255.0 for c in farbe), abs=1e-3)
    assert o["lit"] == f"saeule_{n}_LIT.png"
    assert o["nits"] is None and "GLOBAL_luminance" not in "\n".join(o["zeilen"]), \
        "gemessen: jede Stufe ab 2500 Nits überbelichtet, ohne die Zeile stimmt die Farbe"
    assert "ATTR_no_cull" in o["attr"] and "ATTR_blend" in o["attr"], "halbtransparent, von innen wie außen sichtbar"
    assert len(o["abschnitte"]) == 1, "ein Körper, ein TRIS — der Verlauf steckt in der Textur"


@pytest.mark.parametrize("n", SAEULEN)
def test_das_leuchten_der_saeule_faellt_in_der_lit_textur_von_unten_nach_oben(n, farben):
    """(1 − t)^1,2 in die LIT-Textur gebacken: unten volle Leuchtfarbe, oben null, dazwischen streng fallend."""
    bild = _bild(f"saeule_{n}_LIT.png")
    assert bild.size == (4, 256) and bild.mode == "RGB"
    farbe = _lit(_farbe(n, farben))
    zeilen = [bild.getpixel((1, y)) for y in range(256)]                   # von oben nach unten
    assert zeilen[-1] == farbe and zeilen[0] == (0, 0, 0)
    hell = [max(z) for z in zeilen]
    assert all(a <= b for a, b in zip(hell, hell[1:])), "nach oben nie heller"
    for y in (64, 128, 192):
        t = (255 - y) / 255.0
        assert zeilen[y] == tuple(round(c * (1.0 - t) ** 1.2) for c in farbe), f"Zeile {y}"


def test_die_albedo_textur_hat_den_senkrechten_alpha_verlauf():
    """Unten 0,55, oben 0,02, dazwischen stetig fallend; die letzte Bildzeile ist v = 0 (OBJ8: Ursprung unten links)."""
    bild = _bild("marken.png")
    assert bild.size == (4, 256) and bild.mode == "RGBA"
    alpha = [bild.getpixel((1, y))[3] for y in range(256)]              # von oben nach unten
    assert alpha[-1] == round(0.55 * 255) and alpha[0] == round(0.02 * 255)
    assert all(a <= b for a, b in zip(alpha, alpha[1:])), "nach oben nie heller"
    assert all(bild.getpixel((x, 100)) == bild.getpixel((0, 100)) for x in range(4)), "waagerecht gleichmäßig"
    assert bild.getpixel((1, 100))[:3] == (255, 255, 255), "die Farbe kommt aus ATTR_diffuse_rgb"


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
    for datei in ["licht_warm"]:
        for name, p in _lesen(OBJEKTE / f"{datei}.obj")["lichter"]:
            assert name in soll, f"{name}: keine Vorlage in lights.txt"
            assert len(p) - 3 == soll[name], f"{datei}/{name}: {len(p) - 3} Werte statt {soll[name]}"


def test_das_licht_hat_die_staerke_von_laminars_pistenrandfeuer():
    """Maßstab: `edge_w` in `lights.txt` (Zeile 572) hat 4500 cd. Nachtprüfung des Nutzers: „höchstens das zweitdunkelste"
    der Lichtleiter (2000 / **4500** / 8000 / 32000 / 128000) — also 4500 cd im Glühpunkt und 9000 cd im Lichtfleck."""
    o = _lesen(OBJEKTE / "licht_warm.obj")
    bb, sp = (p for _, p in o["lichter"])
    assert bb[6] == "4500cd" and sp[7] == "9000cd"
    if LIGHTS_TXT.exists():
        assert re.search(r"^BILLBOARD_HW[ \t]+edge_w[ \t].*\b4500cd", LIGHTS_TXT.read_text(encoding="utf-8", errors="replace"), re.M)


def test_das_licht_sieht_man_weit():
    o = _lesen(OBJEKTE / "licht_warm.obj")
    assert o["attr"]["ATTR_LOD"] == ["0", "10000"]


# ---- die Testleiter (abgeschaltet, aber erzeugbar) ---------------------------------------

LEITER_NITS = ["L2500", "L5000", "L10000", "L20000", "L40000", "Lstd"]
LEITER_CD = [2000, 4500, 8000, 32000, 128000]


@pytest.fixture()
def leiter(marken, tmp_path, monkeypatch):
    """Die Testleiter in ein Wegwerf-Verzeichnis erzeugen — sie liegt nicht mehr im Repo."""
    monkeypatch.setattr(marken, "ZIEL", tmp_path)
    monkeypatch.setattr(marken, "MIT_TESTOBJEKTEN", True)
    marken.main()
    return tmp_path


def test_die_testleiter_ist_abgeschaltet_und_im_repo_gelöscht(marken):
    """`MIT_TESTOBJEKTEN = False`: keine test_*-Dateien im Repo (und damit keine im Plugin)."""
    assert marken.MIT_TESTOBJEKTEN is False
    assert list(OBJEKTE.glob("test_*.obj")) == []


def test_die_testleiter_ist_vollstaendig(leiter):
    da = {p.name for p in leiter.glob("test_*.obj")}
    soll = {f"test_wuerfel_{k}.obj" for k in LEITER_NITS} | {f"test_saeule_{k}.obj" for k in LEITER_NITS}         | {f"test_licht_L{cd}.obj" for cd in LEITER_CD}
    assert da == soll


@pytest.mark.parametrize("art", ["wuerfel", "saeule"])
def test_die_leiter_stuft_nur_die_nits_ab_und_nimmt_die_signalorange_texturen(art, leiter):
    """Alles außer `GLOBAL_luminance` ist dasselbe wie beim echten Signalorange-Objekt — sonst misst die Leiter etwas anderes."""
    echt = _lesen(leiter / f"{art}_signalorange.obj")
    for k in LEITER_NITS:
        o = _lesen(leiter / f"test_{art}_{k}.obj")
        assert o["nits"] == (None if k == "Lstd" else int(k[1:]))
        assert (o["textur"], o["lit"]) == (echt["textur"], echt["lit"])
        assert o["vt"] == echt["vt"] and o["idx"] == echt["idx"]
        assert o["attr"] == echt["attr"]
    assert echt["lit"] == f"{art}_signalorange_LIT.png"
    assert _lesen(leiter / f"test_{art}_Lstd.obj")["nits"] == echt["nits"] is None,         "die gemessen richtige Stufe ist die Endfassung"


def test_die_lichtleiter_stuft_die_candela_ab_und_der_fleck_bleibt_doppelt(leiter):
    for cd in LEITER_CD:
        bb, sp = (p for _, p in _lesen(leiter / f"test_licht_L{cd}.obj")["lichter"])
        assert bb[6] == f"{cd}cd" and sp[7] == f"{2 * cd}cd"


def test_die_testleiter_verschwindet_mit_einem_schalter(marken, tmp_path, monkeypatch):
    """`MIT_TESTOBJEKTEN = False`: keine test_*-Dateien mehr, und vorhandene werden gelöscht."""
    monkeypatch.setattr(marken, "ZIEL", tmp_path)
    monkeypatch.setattr(marken, "MIT_TESTOBJEKTEN", True)
    marken.main()
    assert len(list(tmp_path.glob("test_*.obj"))) == 17
    monkeypatch.setattr(marken, "MIT_TESTOBJEKTEN", False)
    marken.main()
    assert list(tmp_path.glob("test_*.obj")) == []
    assert (tmp_path / "wuerfel_navy.obj").exists() and (tmp_path / "licht_warm.obj").exists()


def test_die_endwerte_sind_die_gemessen_richtigen(marken):
    """Nachtprüfung: ohne `GLOBAL_luminance` Luminanz 125 (Runway-Feuer ~150), ab 2500 Nits überbelichtet; Licht 4500 cd."""
    assert marken.WUERFEL_NITS is None and marken.SAEULE_NITS is None
    assert marken.LICHT_CD == 4500 and marken.LICHTFLECK_CD == 9000
    assert marken.TEST_NITS == (2500, 5000, 10000, 20000, 40000) and marken.TEST_CD == tuple(LEITER_CD)


def test_die_messung_steht_im_kopfkommentar_des_generators(marken):
    doc = marken.__doc__
    for muster in (r"`Lstd`.*\|\s*\*\*125\*\*", r"\*\*49\*\*", r"L2500.*73", r"L40000.*220", r"144–153", "Hintergrund"):
        assert re.search(muster, doc), f"Messwert fehlt im Kopfkommentar: {muster}"


# ---- der Generator ---------------------------------------------------------------------

def test_die_dateien_im_repo_sind_die_des_generators(marken, tmp_path, monkeypatch):
    """Wer den Generator ändert, muss die Dateien neu erzeugen — sonst läuft das Plugin mit altem Stand."""
    monkeypatch.setattr(marken, "ZIEL", tmp_path)
    marken.main()
    erzeugt = {p.name for p in tmp_path.iterdir()}
    assert len(erzeugt) == 15 + 16, "15 Objekte + 16 Texturen, ohne Testobjekte"
    for name in erzeugt:
        assert (tmp_path / name).read_bytes() == (OBJEKTE / name).read_bytes(), name
