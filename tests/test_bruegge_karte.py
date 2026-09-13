"""Der Sekundentakt der FriesenBrügge auf der Website-Karte.

Bisher bewegten sich fremde Friesen im VATSIM-Takt: alle 15 Sekunden ein gemessener Punkt,
dazwischen aus Kurs und Fahrt fortgerechnet. Wer eine Brügge fliegt, meldet dem Server aber
jede Sekunde seine echte Position — diese Meldungen landeten in der Datenbank und gingen von
dort nicht weiter.

Geprüft wird beides: der Weg vom Endpunkt in den Sekundenstrom (Python) und das, was die
Karte daraus macht (Node). Die Trennlinie liegt bewusst beim JSON: Ein Feldname, der auf
einer Seite umbenannt wird, fällt hier auf und nicht erst, wenn jemand fliegt.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

INDEX = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(
    encoding="utf-8")

_NODE = shutil.which("node")


# ---------------------------------------------------------------------------
# Server: vom Endpunkt in den Strom
# ---------------------------------------------------------------------------

def _poller():
    from app.poller import VatsimPoller
    return VatsimPoller(db_path=":memory:")


def _lage(lat=53.5, lon=8.1, **mehr):
    lage = {"lat": lat, "lon": lon, "alt_msl_ft": 1500.4, "alt_agl_ft": 1480.0,
            "gs_kt": 92.6, "kurs": 271.44, "vs_ft_min": 0.0, "am_boden": False}
    lage.update(mehr)
    return lage


def test_gemerkte_position_geht_als_strom_hinaus():
    p = _poller()
    q = p.subscribe_sse()
    p.bruegge_position_merken(1234567, _lage())
    p.bruegge_strom_senden()

    msg = q.get_nowait()
    assert msg["type"] == "bruegge"
    assert len(msg["data"]) == 1
    e = msg["data"][0]
    assert e["cid"] == 1234567
    assert e["lat"] == 53.5 and e["lon"] == 8.1
    # Gerundet, aber nicht verfälscht: Zehntelgrad ist feiner, als ein 18-Pixel-Symbol zeigt.
    assert e["hdg"] == 271.4
    assert e["alt"] == 1500
    assert e["gnd"] is False
    # Die interne Empfangszeit gehört NICHT in den Strom: Sie ist eine monotone Zahl ohne
    # Bezug zur Uhr des Empfängers und wäre dort nur irreführend.
    assert "ts" not in e


def test_ohne_meldung_geht_gar_nichts_hinaus():
    """Fliegt niemand mit Brügge, bleibt der Kanal still — kein leeres Paket im Leerlauf."""
    p = _poller()
    q = p.subscribe_sse()
    p.bruegge_strom_senden()
    assert q.empty()


def test_alte_meldung_faellt_aus_dem_strom(monkeypatch):
    import app.poller as poller_modul

    p = _poller()
    q = p.subscribe_sse()
    p.bruegge_position_merken(1234567, _lage())
    # Die Uhr vorstellen, statt zu warten: Der Test prüft die Frist, nicht die Geduld.
    echte_zeit = poller_modul.time.monotonic
    monkeypatch.setattr(poller_modul.time, "monotonic",
                        lambda: echte_zeit() + p.BRUEGGE_FRIST_S + 1)
    p.bruegge_strom_senden()
    assert q.empty()
    # ... und der Eintrag ist weg, nicht nur übersprungen. Sonst wüchse der Speicher mit
    # jeder cid, die je gemeldet hat.
    assert not p._bruegge_live


def test_der_strom_ist_kein_scheduler_job():
    """Er war es am 13.09.2026 für eine Stunde, und das Containerprotokoll hat es sofort
    gezeigt: APScheduler schreibt je Ausführung zwei INFO-Zeilen — bei Sekundentakt
    **172 800 am Tag**, im Leerlauf wie unter Last. Wer den Strom wieder als Job registriert,
    verschüttet damit jede Fehlersuche im selben Protokoll."""
    p = _poller()
    aufgezeichnet = []

    class _Stub:
        def add_job(self, fn, *a, **kw):
            aufgezeichnet.append((getattr(fn, "__name__", str(fn)), kw.get("id"),
                                  kw.get("seconds")))

    p._scheduler = _Stub()
    p._register_jobs()
    assert aufgezeichnet, "keine Jobs registriert -- der Test prüft dann nichts"
    assert not [j for j in aufgezeichnet if j[0] == "bruegge_strom_senden"]
    # Und allgemeiner: gar kein Sekundenjob. Ein anderer Name hätte dieselbe Wirkung.
    assert not [j for j in aufgezeichnet if j[2] == 1]


def test_die_schleife_ueberlebt_eine_ausnahme():
    """Der Strom ist der einzige Weg, auf dem eine Brügge-Position die Karte erreicht. Bricht
    er still ab, sieht das von außen genauso aus wie „niemand fliegt"."""
    import asyncio

    p = _poller()
    laeufe = []

    def _senden():
        laeufe.append(1)
        if len(laeufe) == 1:
            raise RuntimeError("ein schlechter Durchgang")
        if len(laeufe) >= 3:
            raise asyncio.CancelledError

    p.bruegge_strom_senden = _senden

    async def _lauf():
        # Ohne echtes Warten: Der Test prüft die Beharrlichkeit, nicht die Uhr.
        urspruenglich = asyncio.sleep
        async def _kurz(_s):
            await urspruenglich(0)
        asyncio.sleep = _kurz
        try:
            with pytest.raises(asyncio.CancelledError):
                await p._bruegge_strom_schleife()
        finally:
            asyncio.sleep = urspruenglich

    asyncio.run(_lauf())
    assert len(laeufe) == 3, "nach der Ausnahme wurde nicht weitergesendet"


def test_meldung_ohne_koordinaten_wird_nicht_gemerkt():
    p = _poller()
    p.bruegge_position_merken(1234567, {"gs_kt": 0.0})
    assert not p._bruegge_live


def test_endpunkt_legt_die_position_in_den_strom(tmp_path, monkeypatch):
    """Der Weg, der in der Praxis zählt: eine echte Meldung durch `/api/bruegge/melden`."""
    from fastapi.testclient import TestClient
    import app.main as main
    from app.database import get_connection, init_db, _now_utc

    pfad = str(tmp_path / "t.db")
    init_db(pfad)
    settings = SimpleNamespace(
        DB_PATH=pfad, CALLSIGN_PREFIX="FRS", SECRET_KEY="test-nur-fuer-diesen-lauf",
        ADMIN_PASSWORD="test", SSO_SECRET="", FORUM_SSO_URL="", FORUM_SSO_CALLBACK="",
        USER_SESSION_MAX_AGE_SEC=3600, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    if hasattr(main, "_reset_gate_cache"):
        main._reset_gate_cache()

    # Ein Friese in der Luft, an dem sich die Meldung festmachen kann -- nach demselben
    # Muster wie in test_bruegge_endpunkt.py. Ohne den Forum-Login wird die Meldung
    # abgewiesen, und der Test prüfte dann den Ablehnungsweg statt des Stroms.
    conn = get_connection(pfad)
    conn.execute(
        "INSERT OR REPLACE INTO live_positions "
        "(cid, callsign, latitude, longitude, altitude, groundspeed, heading, updated_at) "
        "VALUES (?, ?, ?, ?, 1500, 92, 271, ?)",
        (1234567, "FRS49", 53.5, 8.1, _now_utc()),
    )
    conn.execute(
        "INSERT OR REPLACE INTO forum_callsign (callsign, cid, updated_at) VALUES (?, ?, ?)",
        ("FRS49", 1234567, _now_utc()),
    )
    conn.commit()
    conn.close()

    p = _poller()
    main.app.state.poller = p
    try:
        klient = TestClient(main.app)
        antwort = klient.post("/api/bruegge/melden", json={
            "protokoll": 1, "simulator": "xplane12", "bruegge_version": "1.1.0",
            "kennung": "a3f9c1e0b2d48576", "kann": [], "lage": _lage(),
            "spur": [], "steht": [],
        })
        assert antwort.status_code == 200
        assert 1234567 in p._bruegge_live
    finally:
        del main.app.state.poller


# ---------------------------------------------------------------------------
# Karte: was der Strom dort bewirkt
# ---------------------------------------------------------------------------

def _karten_quelltext():
    """Vom Rohwert-Speicher bis hinter `_brueggeStromEinarbeiten`.

    Muss bei `const _positionsRoh` beginnen: Der Empfänger schreibt genau dorthin, und ohne
    die Deklaration wäre jede Zusicherung ein ReferenceError statt einer Aussage.
    """
    start = INDEX.index("const _positionsRoh = {};")
    ende = INDEX.index("function _brueggeStromEinarbeiten(")
    return INDEX[start:INDEX.index("\n}", ende) + len("\n}")]


_HARNESS = """
'use strict';
const assert = require('assert');

// Was der Ausschnitt von aussen braucht: die Liste der Friesen (cid -> Rufzeichen) und die
// Frage nach dem eigenen Flugzeug. Beide sind im Original woanders zuhause.
global.liveData = [];
global._eigenes = null;
function _istEigenesFlugzeug(cs) { return global._eigenes === cs; }

__QUELLTEXT__

__PRUEFUNG__
console.log('OK');
"""


def _node(pruefung: str) -> str:
    if not _NODE:
        pytest.skip("node nicht vorhanden")
    quelle = _HARNESS.replace("__QUELLTEXT__", _karten_quelltext()) \
                     .replace("__PRUEFUNG__", pruefung)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(quelle)
        name = f.name
    lauf = subprocess.run([_NODE, name], capture_output=True, text=True, timeout=30)
    assert lauf.returncode == 0, lauf.stdout + lauf.stderr
    return lauf.stdout


def test_strom_schreibt_in_die_tabelle_die_der_takt_liest():
    """Der Kern: kein zweiter Zeichenweg, sondern ein besserer Wert in `_positionsRoh`."""
    _node("""
      global.liveData = [{ cid: 1234567, callsign: 'FRS49' }];
      _brueggeStromEinarbeiten([{ cid: 1234567, lat: 53.5, lon: 8.1, hdg: 271.4,
                                  gs: 92.6, alt: 1500, agl: 1480, gnd: false }]);
      assert.ok(_positionsRoh['FRS49'], 'Rohwert fehlt');
      assert.strictEqual(_positionsRoh['FRS49'].lat, 53.5);
      assert.strictEqual(_positionsRoh['FRS49'].hdg, 271.4);
      assert.strictEqual(_brueggeWerte['FRS49'].alt, 1500);
      assert.strictEqual(_brueggeFrisch('FRS49'), true);
    """)


def test_unbekannte_cid_wird_uebergangen():
    """Wer nicht in liveData steht, hat keinen Marker — und darf keinen Rohwert bekommen."""
    _node("""
      global.liveData = [{ cid: 1234567, callsign: 'FRS49' }];
      _brueggeStromEinarbeiten([{ cid: 9999999, lat: 53.5, lon: 8.1 }]);
      assert.deepStrictEqual(Object.keys(_positionsRoh), []);
      assert.deepStrictEqual(Object.keys(_brueggeWerte), []);
    """)


def test_das_eigene_flugzeug_kommt_nicht_aus_der_bruegge():
    """Es wird an genau einer Stelle gesetzt (`_eigenesFlugzeugZeichnen`) — ein zweiter
    Schreiber daneben war schon einmal als Zurückspringen sichtbar."""
    _node("""
      global.liveData = [{ cid: 1234567, callsign: 'FRS49' }];
      global._eigenes = 'FRS49';
      _brueggeStromEinarbeiten([{ cid: 1234567, lat: 53.5, lon: 8.1 }]);
      assert.deepStrictEqual(Object.keys(_positionsRoh), []);
    """)


def test_ohne_meldung_gilt_die_bruegge_nicht():
    _node("""
      assert.strictEqual(_brueggeFrisch('FRS49'), false);
    """)


def test_alte_meldung_faellt_von_selbst_zurueck():
    """Der Strom meldet nicht, dass er endet — wer den Simulator schliesst, hört auf zu
    senden. Die Karte muss den Rückfall auf VATSIM also selbst entscheiden."""
    _node("""
      global.liveData = [{ cid: 1234567, callsign: 'FRS49' }];
      _brueggeStromEinarbeiten([{ cid: 1234567, lat: 53.5, lon: 8.1 }]);
      _brueggeWerte['FRS49'].ts = Date.now() - _BRUEGGE_FRIST_MS - 1;
      assert.strictEqual(_brueggeFrisch('FRS49'), false);
    """)


# ---------------------------------------------------------------------------
# Zusicherungen am Quelltext -- die Stellen, an denen ein Rückschritt still wäre
# ---------------------------------------------------------------------------

def test_vatsim_ueberschreibt_die_bruegge_nicht():
    """`_markerGehoertDemSim` ist die Sperre, die den 15-Sekunden-Abruf vom frischen Punkt
    fernhält. Fehlt die Brügge dort, springt das Symbol im VATSIM-Takt zurück."""
    block = INDEX[INDEX.index("function _markerGehoertDemSim("):]
    block = block[:block.index("\n}")]
    assert "_brueggeFrisch(callsign)" in block


def test_die_farbe_wechselt_im_sekundentakt():
    """Sie muss auch beim ZURÜCK-Wechsel greifen: Endet der Strom, rührt `updateMap` das
    Symbol unter Umständen nie wieder an."""
    block = INDEX[INDEX.index("function _naviTakt("):]
    block = block[:block.index("\n// 2b.") if "\n// 2b." in block else len(block)]
    assert "_fsBruegge" in block


def test_die_bruegge_farbe_ist_im_stylesheet_erklaert():
    assert ".aircraft-marker-bruegge" in INDEX
    # Gleiche Farbe am Symbol und im Popup -- sonst liest sich beides wie zwei Aussagen.
    farben = re.findall(r"\.aircraft-marker-bruegge\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", INDEX)
    popup = re.findall(r"\.popup-bruegge\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", INDEX)
    assert farben and popup and farben[0].lower() == popup[0].lower()
