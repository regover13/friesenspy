# -*- coding: utf-8 -*-
"""Das Kniebrett darf sich nicht auf ``globalThis`` verlassen (Live-Fund 24.09.2026).

**Der Fall:** Reiner (CID 1031301) installierte das Kniebrett 2.3.0, meldete sich im Forum an
-- und landete direkt auf der Karte, ohne die Frage „Kniebrett dauerhaft anmelden?". Beim
nächsten Start begann alles von vorn. Das Paket hatte seinen Grund selbst gemeldet
(``panel_diag``, Art ``geraet-ohne-bindung``):

    DataStore nicht verfuegbar: ReferenceError: Can't find variable: globalThis

Sein Coherent GT (``AppleWebKit/604.1.38``, WebKit auf dem Stand von Safari 11) kennt
``globalThis`` nicht. ``makeDeviceId`` griff darüber auf ``crypto`` zu, warf, und
``buildPanelUrl`` fiel auf ``/panel`` ohne Geräte-ID zurück -- ohne ID gibt es keine
Bestätigungsseite und keine Bindung. Dieselbe Meldung kam am 23.09.2026 von CID 859467.
Bei beiden fehlte zugleich die Position aus dem Simulator: Auch die hing an ``globalThis``.

Wer das Kniebrett schon gebunden hatte, merkte nichts: Eine vorhandene Kennung kommt aus
``DataStore.get`` zurück, ``makeDeviceId`` läuft gar nicht erst. Getroffen hat es also genau
die Neuen -- und genau die sieht man nicht, weil sie nie in ``panel_devices`` auftauchen.

⚠ Die Meldung sagt „DataStore nicht verfuegbar", und das war irreführend: Der Datenspeicher
ging, es warf ``makeDeviceId`` im selben ``try``. Das SDK selbst enthält kein ``globalThis``
(geprüft an ``microsoft-msfs-sdk-2.1.1.tgz``).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
SHELL = (WURZEL / "msfs-panel" / "PackageSources" / "FriesenSpy" / "src"
         / "FriesenSpy.tsx").read_text(encoding="utf-8")
_NODE = shutil.which("node")


def _ohne_kommentare(text: str) -> str:
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def _rumpf_globales_objekt() -> str:
    """Der Rumpf von ``globalesObjekt`` -- der EINZIGE Ort, der ``globalThis`` nennen darf."""
    start = SHELL.index("function globalesObjekt(")
    ende = SHELL.index("\n}\n", start) + 3
    return SHELL[start:ende]


def _ausdruck_globales_objekt() -> str:
    """Der Auswahl-Ausdruck aus ``globalesObjekt`` als reines JavaScript."""
    m = re.search(r"const g: unknown =\s*(.*?);", _rumpf_globales_objekt(), flags=re.S)
    assert m, "globalesObjekt waehlt sein Objekt nicht mehr ueber `const g: unknown = ...;`"
    return m.group(1)


def test_globalthis_steht_nur_in_globales_objekt():
    """Jeder andere Zugriff wirft auf einem Coherent GT ohne ``globalThis`` -- und zwar
    genau dort, wo man es nicht sieht: im Simulator eines anderen."""
    ohne = SHELL.replace(_rumpf_globales_objekt(), "")
    treffer = [z.strip() for z in _ohne_kommentare(ohne).splitlines() if "globalThis" in z]
    assert not treffer, f"globalThis ausserhalb von globalesObjekt: {treffer}"


def test_globales_objekt_fragt_globalthis_nur_ueber_typeof():
    """``typeof`` wirft bei einem unbekannten Namen nicht, ein Zugriff schon."""
    ausdruck = _ausdruck_globales_objekt()
    assert "typeof globalThis" in ausdruck
    # Das zweite Vorkommen ist die Rueckgabe NACH der Pruefung -- mehr darf es nicht sein.
    assert ausdruck.count("globalThis") == 2, ausdruck


def _auswerten(vorbereitung: str) -> dict:
    """Den Ausdruck in einem frischen Kontext auswerten, in dem ``globalThis`` fehlt --
    so, wie Reiners Coherent GT es tut."""
    skript = f"""
const vm = require("vm");
const ctx = vm.createContext({{}});
vm.runInContext({json.dumps(vorbereitung)}, ctx);
let raus;
try {{
  const g = vm.runInContext("(" + {json.dumps(_ausdruck_globales_objekt())} + ")", ctx);
  raus = {{ ok: true, marke: g && g.marke, crypto: !!(g && g.crypto) }};
}} catch (e) {{
  raus = {{ ok: false, fehler: e.constructor.name + ": " + e.message }};
}}
console.log(JSON.stringify(raus));
"""
    erg = subprocess.run([_NODE, "-e", skript], capture_output=True, text=True, timeout=20)
    assert erg.returncode == 0, erg.stderr
    return json.loads(erg.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_ohne_globalthis_kommt_window_zurueck():
    """Der eigentliche Fall. Rote Gegenprobe: Mit dem alten ``globalThis.crypto`` wirft
    derselbe Kontext ``ReferenceError: globalThis is not defined``."""
    erg = _auswerten("delete globalThis.globalThis;"
                     "var window = { marke: 'window', crypto: { getRandomValues: function(){} } };")
    assert erg == {"ok": True, "marke": "window", "crypto": True}, erg


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_ohne_globalthis_und_window_wirft_nichts():
    """Fehlt beides, bleibt die Kennung leer und das Paket meldet es -- aber es wirft nicht."""
    erg = _auswerten("delete globalThis.globalThis;")
    assert erg["ok"] is True, erg


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_mit_globalthis_bleibt_alles_wie_es_war():
    erg = _auswerten("globalThis.marke = 'global'; globalThis.crypto = {};")
    assert erg == {"ok": True, "marke": "global", "crypto": True}, erg
