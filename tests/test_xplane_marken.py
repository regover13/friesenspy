# -*- coding: utf-8 -*-
"""Die X-Plane-Marken der FriesenBrügge: Würfel, Lichtsäulen, ein Licht (20.09.2026).

Nutzerwunsch: *„Würfel in den Friesenfarben. Säule in Weiß + Friesenfarben"*, *„Würfel ca. 3 m"*, *„ein einfaches
Licht"*. Nach dem MSFS-Flugtest ist die Säule ein **Scheinwerferstrahl**: 100 m, Achteck unten 4 m / oben 6 m, Deckkraft
0,55 → 0,02 (Textur, `v` = Höhe) und Leuchten `(1 − t)^1,2` in 20 gestapelten Abschnitten. Das Weiß ist warm
(`WEISS` = 255/240/200), es gibt sieben Würfel und sieben Säulen. Eigene OBJ8-Dateien, erzeugt von
`friesenbruegge/xplane/marken_bauen.py`.

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
    o = {"vt": [], "idx": [], "tris": None, "abschnitte": [], "attr": {}, "lichter": [], "punkte": None,
         "textur": None}
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
            # Was für DIESEN Abschnitt gilt: der zuletzt gesetzte Emissivwert (Attribute wirken auf das folgende TRIS).
            o["abschnitte"].append((int(teile[1]), int(teile[2]), o["attr"].get("ATTR_emission_rgb")))
        elif k in ("ATTR_diffuse_rgb", "ATTR_emission_rgb"):
            o["attr"][k] = tuple(float(x) for x in teile[1:4])
        elif k == "LIGHT_PARAM":
            o["lichter"].append((teile[1], teile[2:]))
        elif k in ("ATTR_no_cull", "ATTR_blend", "ATTR_LOD"):
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


def _farbe(n, farben):
    return WEISS if n == "weiss" else farben[n]


def _tris_gesamt(o):
    return sum(a[1] for a in o["abschnitte"])


# ---- die Dateimenge ---------------------------------------------------------------------

def test_es_gibt_sieben_wuerfel_sieben_saeulen_und_ein_licht():
    da = {p.name for p in OBJEKTE.iterdir()}
    for n in WUERFEL:
        assert f"wuerfel_{n}.obj" in da
    for n in SAEULEN:
        assert f"saeule_{n}.obj" in da
    assert "licht_warm.obj" in da and "marken.png" in da
    eigene = {n for n in da if n.endswith(".obj") and n.split("_")[0] in ("wuerfel", "saeule", "licht")}
    assert len(eigene) == 15, "7 Würfel + 7 Säulen + 1 Licht"


def test_der_workflow_kopiert_den_ganzen_objekte_ordner():
    """Neue Dateien kommen so von allein ins Plugin — kein Namenskatalog, der nachgezogen werden müsste."""
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

@pytest.mark.parametrize("name", [f"wuerfel_{n}" for n in WUERFEL] + [f"saeule_{n}" for n in SAEULEN])
def test_zaehlungen_und_indizes_stimmen(name):
    o = _lesen(OBJEKTE / f"{name}.obj")
    assert o["punkte"] == (len(o["vt"]), 0, 0, len(o["idx"])), "POINT_COUNTS = VT / 0 / 0 / IDX"
    assert len(o["idx"]) % 3 == 0 and all(0 <= i < len(o["vt"]) for i in o["idx"])
    # Die TRIS-Abschnitte schließen lückenlos aneinander und decken alle Indizes ab.
    nächster = 0
    for start, anzahl, _ in o["abschnitte"]:
        assert start == nächster and anzahl % 3 == 0
        nächster += anzahl
    assert nächster == len(o["idx"])


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
    soll = tuple(c / 255.0 for c in _farbe(n, farben))
    assert o["attr"]["ATTR_diffuse_rgb"] == pytest.approx(soll, abs=1e-3)
    assert o["attr"]["ATTR_emission_rgb"] == pytest.approx(tuple(c * 0.35 for c in soll), abs=1e-3)


def test_die_sechs_friesenwuerfel_sind_unveraendert():
    """Der Koordinator, 20.09.2026: „Die Würfel sind gut und bleiben UNVERÄNDERT" — Prüfsumme des Stands vom Flugtest."""
    import hashlib
    erwartet = {"navy": "469987de4544278a", "hellblau": "c94e836ae4c4531b", "rot": "25d99db8608fe673",
                "orange": "6cd77388e35d1f6e", "signalrot": "1083ae8f7fe4dd4d", "signalorange": "180812c58f23f173"}
    for n, h in erwartet.items():
        assert hashlib.sha256((OBJEKTE / f"wuerfel_{n}.obj").read_bytes()).hexdigest()[:16] == h, n


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
    assert len(seiten) == 20 * 8 * 4, "zwanzig Abschnitte, acht Seiten, vier Ecken"
    for v, nh in seiten:
        betrag = math.hypot(nh[0], nh[2])
        abstand = _dot(v[:3], (nh[0] / betrag, 0.0, nh[2] / betrag))
        assert abstand == pytest.approx(2.0 + v[1] / 100.0, abs=2e-3), "linear von 2 m auf 3 m"
    unten = [a for v, nh in seiten if v[1] == 0.0 for a in [_dot(v[:3], (nh[0] / math.hypot(nh[0], nh[2]), 0.0, nh[2] / math.hypot(nh[0], nh[2])))]]
    oben = [a for v, nh in seiten if v[1] == 100.0 for a in [_dot(v[:3], (nh[0] / math.hypot(nh[0], nh[2]), 0.0, nh[2] / math.hypot(nh[0], nh[2])))]]
    assert unten and oben and max(unten) == pytest.approx(2.0, abs=1e-3) and min(oben) == pytest.approx(3.0, abs=1e-3)
    assert len(o["vt"]) == 648 and len(o["idx"]) == 978, "20×8×2 Dreiecke + Deckel (6)"


@pytest.mark.parametrize("n", SAEULEN)
def test_die_v_koordinate_laeuft_mit_der_hoehe(n):
    """Nur so kann der senkrechte Alpha-Verlauf der Textur nach oben ausblenden."""
    o = _lesen(OBJEKTE / f"saeule_{n}.obj")
    for v in o["vt"]:
        assert v[6] == pytest.approx(0.5) and v[7] == pytest.approx(v[1] / 100.0, abs=1e-4)


@pytest.mark.parametrize("n", SAEULEN)
def test_das_leuchten_faellt_von_abschnitt_zu_abschnitt_bis_null(n, farben):
    """Zwanzig Abschnitte mit (1 − t)^1,2, t = Höhe der Mitte; dazu der Deckel bei t = 1 ohne Leuchten."""
    o = _lesen(OBJEKTE / f"saeule_{n}.obj")
    soll = tuple(c / 255.0 for c in _farbe(n, farben))
    assert len(o["abschnitte"]) == 21
    faktoren = []
    for k, (start, anzahl, em) in enumerate(o["abschnitte"]):
        t = 1.0 if k == 20 else (k + 0.5) / 20.0
        erwartet = (1.0 - t) ** 1.2
        assert em == pytest.approx(tuple(c * erwartet for c in soll), abs=2e-4), f"Abschnitt {k}"
        faktoren.append(erwartet)
    assert all(a > b for a, b in zip(faktoren, faktoren[1:])), "streng monoton fallend"
    assert faktoren[0] > 0.95 and faktoren[-1] == 0.0
    assert o["attr"]["ATTR_diffuse_rgb"] == pytest.approx(soll, abs=1e-3)


@pytest.mark.parametrize("n", SAEULEN)
def test_die_saeule_blendet_und_ist_von_innen_wie_aussen_sichtbar(n):
    o = _lesen(OBJEKTE / f"saeule_{n}.obj")
    assert o["textur"] == "marken.png", "die Textur trägt den Alpha-Verlauf"
    assert "ATTR_no_cull" in o["attr"] and "ATTR_blend" in o["attr"]


def test_die_textur_hat_den_senkrechten_alpha_verlauf():
    """Unten 0,55, oben 0,02, dazwischen stetig fallend; die letzte Bildzeile ist v = 0 (OBJ8: Ursprung unten links)."""
    from PIL import Image
    bild = Image.open(OBJEKTE / "marken.png")
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
    o = _lesen(OBJEKTE / "licht_warm.obj")
    for name, p in o["lichter"]:
        assert name in soll, f"{name}: keine Vorlage in lights.txt"
        assert len(p) - 3 == soll[name], f"{name}: {len(p) - 3} Werte statt {soll[name]}"


def test_das_licht_ist_um_das_1_6fache_heller():
    """Nach dem 2020er Nachttest: MSFS-Stärke 5,0 → 8,0 (×1,6), hier 500 → 800 und 1000 → 1600 cd (ungemessen)."""
    o = _lesen(OBJEKTE / "licht_warm.obj")
    bb, sp = (p for _, p in o["lichter"])
    assert bb[6] == "800cd" and sp[7] == "1600cd"


def test_das_licht_sieht_man_weit():
    o = _lesen(OBJEKTE / "licht_warm.obj")
    assert o["attr"]["ATTR_LOD"] == ["0", "10000"]


# ---- der Generator ---------------------------------------------------------------------

def test_die_dateien_im_repo_sind_die_des_generators(marken, tmp_path, monkeypatch):
    """Wer den Generator ändert, muss die Dateien neu erzeugen — sonst läuft das Plugin mit altem Stand."""
    monkeypatch.setattr(marken, "ZIEL", tmp_path)
    marken.main()
    erzeugt = {p.name for p in tmp_path.iterdir()}
    assert len(erzeugt) == 16, "15 Objekte + marken.png"
    for name in erzeugt:
        assert (tmp_path / name).read_bytes() == (OBJEKTE / name).read_bytes(), name
