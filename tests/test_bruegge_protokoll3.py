# -*- coding: utf-8 -*-
"""`/api/bruegge/melden` mit Protokoll 3: Kennung je Installation (#46, 26.09.2026).

Beschluss: docs/superpowers/specs/2026-09-26-bruegge-kennung-und-zuordnung-design.md.
Die Regeln selbst prüft tests/test_bruegge_bindung.py; hier geht es um den Weg durch den
Endpunkt: welche Brügge welchen Weg nimmt, was in der Antwort steht, was in der Datenbank.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

B, O = 53.78227, 7.92593


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import app.main as main
    from app import bruegge_bindung
    from app.database import init_db
    pfad = str(tmp_path / "t.db")
    init_db(pfad)
    settings = SimpleNamespace(
        DB_PATH=pfad, CALLSIGN_PREFIX="FRS", SECRET_KEY="test", ADMIN_PASSWORD="test",
        SSO_SECRET="", FORUM_SSO_URL="", FORUM_SSO_CALLBACK="",
        USER_SESSION_MAX_AGE_SEC=3600, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    if hasattr(main, "_reset_gate_cache"):
        main._reset_gate_cache()
    bruegge_bindung._SITZUNGEN.clear()
    bruegge_bindung.ABGELEHNT.clear()
    if hasattr(main.app.state, "poller"):
        del main.app.state._state["poller"]
    return SimpleNamespace(client=TestClient(main.app), db=pfad, main=main)


def _meldung(protokoll=3, kennung="", simulator="msfs2024", lat=B, lon=O, gs=0.0,
             boden=True):
    return {
        "protokoll": protokoll, "simulator": simulator, "bruegge_version": "1.18.0",
        "kennung": kennung,
        "lage": {"lat": lat, "lon": lon, "alt_msl_ft": 5.0, "alt_agl_ft": 0.0, "gs_kt": gs,
                 "kurs": 90.0, "vs_ft_min": 0.0, "am_boden": boden},
        "spur": [], "steht": [],
    }


def _verbindung(db, cid, cs, lat=B, lon=O, logon=None, forum=True):
    from app.database import get_connection
    jetzt = datetime.now(timezone.utc)
    c = get_connection(db)
    c.execute("INSERT OR REPLACE INTO live_positions (cid, callsign, latitude, longitude, "
              "altitude, groundspeed, heading, logon_time, updated_at) "
              "VALUES (?, ?, ?, ?, 5, 0, 90, ?, ?)",
              (cid, cs, lat, lon, _iso(logon or jetzt), _iso(jetzt)))
    if forum:
        c.execute("INSERT OR REPLACE INTO forum_callsign (callsign, cid, updated_at) "
                  "VALUES (?, ?, ?)", (cs, cid, _iso(jetzt)))
    c.commit()
    c.close()


def _zeile(db, kennung):
    from app.database import get_connection, bruegge_zuordnung_holen
    c = get_connection(db)
    try:
        return bruegge_zuordnung_holen(c, kennung)
    finally:
        c.close()


def _melden(env, **kw):
    r = env.client.post("/api/bruegge/melden", json=_meldung(**kw))
    assert r.status_code == 200, r.text
    return r.json()


# --- Protokoll und Kennung ---------------------------------------------------------------

def test_protokoll_3_wird_angenommen(env):
    assert env.main._BRUEGGE_PROTOKOLL == 3
    assert _melden(env)["protokoll"] == 3


def test_eine_neue_bruegge_bekommt_sofort_eine_frische_kennung(env):
    """Beim ERSTEN Kontakt, vor jeder Zuordnung -- und sie steht nicht in der Datenbank."""
    a = _melden(env)
    assert re.fullmatch(r"[0-9a-f]{16}", a["kennung"])
    assert _zeile(env.db, a["kennung"]) is None
    b = _melden(env, kennung=a["kennung"])
    assert "kennung" not in b, "eine vorhandene Kennung wird nie ersetzt"


def test_jede_neue_installation_bekommt_ihre_eigene(env):
    assert _melden(env)["kennung"] != _melden(env)["kennung"]


def test_nie_die_kennung_eines_piloten(env):
    """Genau so kam am 25.09. FRS111Ns Kennung zu FRS49."""
    _verbindung(env.db, 111, "FRS111N")
    from app.database import get_connection, bruegge_zuordnung_setzen
    c = get_connection(env.db)
    bruegge_zuordnung_setzen(c, "alt111alt111alt1", 111, "msfs2024", 2)
    c.commit()
    c.close()
    assert _melden(env)["kennung"] != "alt111alt111alt1"


# --- Die erste Zuordnung über den Endpunkt ---------------------------------------------------

def test_die_eigene_verbindung_nach_dem_start_bindet(env):
    k = _melden(env)["kennung"]
    _verbindung(env.db, 49, "FRS49", lat=B + 0.000004)
    _melden(env, kennung=k)
    z = _zeile(env.db, k)
    assert z is not None and int(z["cid"]) == 49 and z["protokoll"] == 3


def test_der_fall_vom_25_09_ueber_den_endpunkt(env):
    """Der Nachbar ist lange verbunden und steht 22 m daneben, der eigene Pilot noch nicht."""
    _verbindung(env.db, 111, "FRS111N", lat=B + 22 / 111320,
                logon=datetime.now(timezone.utc) - timedelta(hours=1))
    k = _melden(env)["kennung"]
    _melden(env, kennung=k)
    assert _zeile(env.db, k) is None


def test_ein_friese_unter_fremdem_rufzeichen_ist_kandidat(env):
    """Kandidaten über die CID, nicht über das Präfix: angemeldet im Forum, fliegt als DLH12."""
    from app.database import get_connection
    k = _melden(env)["kennung"]
    c = get_connection(env.db)
    c.execute("INSERT INTO forum_callsign (callsign, cid, updated_at) VALUES ('FRS77', 77, ?)",
              (_iso(datetime.now(timezone.utc)),))
    c.commit()
    c.close()
    import time as _t
    env.main.app.state.poller = SimpleNamespace(
        traffic_snapshot=[{"cid": 77, "cs": "DLH12", "lat": B, "lon": O, "alt": 5, "gs": 0,
                           "hdg": 90, "logon": _iso(datetime.now(timezone.utc))}],
        traffic_snapshot_ts=_t.time(),
        bruegge_position_merken=lambda *a, **kw: None,
    )
    try:
        _melden(env, kennung=k)
    finally:
        del env.main.app.state._state["poller"]
    z = _zeile(env.db, k)
    assert z is not None and int(z["cid"]) == 77


def test_ein_nicht_angemeldeter_frs_pilot_ist_kein_kandidat(env):
    k = _melden(env)["kennung"]
    _verbindung(env.db, 5, "FRS5", forum=False)
    _melden(env, kennung=k)
    assert _zeile(env.db, k) is None


# --- Wer welchen Weg nimmt -------------------------------------------------------------

def test_die_alte_msfs_bruegge_laeuft_bis_zum_stichtag_weiter(env):
    _verbindung(env.db, 49, "FRS49")
    a = _melden(env, protokoll=2)
    assert a["protokoll"] == 2


def test_nach_dem_stichtag_bekommt_die_alte_msfs_bruegge_426(env, monkeypatch):
    monkeypatch.setattr(env.main, "_BRUEGGE_P2_MSFS_BIS", "2000-01-01T00:00:00Z")
    r = env.client.post("/api/bruegge/melden", json=_meldung(protokoll=2))
    assert r.status_code == 426


def test_x_plane_mit_protokoll_2_laeuft_ueber_den_neuen_weg(env, monkeypatch):
    """X-Plane speichert seine Kennung seit jeher selbst -- kein Stichtag, neue Regeln."""
    monkeypatch.setattr(env.main, "_BRUEGGE_P2_MSFS_BIS", "2000-01-01T00:00:00Z")
    _verbindung(env.db, 111, "FRS111N", lat=B + 3 / 111320,
                logon=datetime.now(timezone.utc) - timedelta(hours=1))
    a = _melden(env, protokoll=2, simulator="xplane12", kennung="c0ffee00c0ffee00")
    assert "kennung" not in a
    assert _zeile(env.db, "c0ffee00c0ffee00") is None, "der früher verbundene Nachbar zählt nicht"


def test_eine_alte_bruegge_bekommt_keine_kennung_einer_neuen_installation(env):
    from app.database import get_connection, bruegge_zuordnung_setzen, bruegge_kennung_fuer
    c = get_connection(env.db)
    bruegge_zuordnung_setzen(c, "neu0neu0neu0neu0", 49, "msfs2024", 3)
    c.commit()
    assert bruegge_kennung_fuer(c, 49, "msfs2024") is None
    c.close()


def test_ab_protokoll_3_raeumt_eine_neue_bindung_nichts_weg(env):
    """These 9: ein Pilot, zwei Rechner, gleicher Simulator -- beide Bindungen bleiben."""
    from app.database import get_connection, bruegge_zuordnung_setzen
    c = get_connection(env.db)
    bruegge_zuordnung_setzen(c, "rechner1rechner1", 49, "msfs2024", 3)
    bruegge_zuordnung_setzen(c, "rechner2rechner2", 49, "msfs2024", 3)
    c.commit()
    n = c.execute("SELECT count(*) FROM bruegge_zuordnung WHERE cid = 49").fetchone()[0]
    c.close()
    assert n == 2


# --- Der Sekundenstrom -----------------------------------------------------------------

def test_der_strom_traegt_rufzeichen_und_bewaehrt(env):
    """Paket 1 wertet `bw` im Kniebrett schon als Anker aus (These 18)."""
    gemerkt = []
    env.main.app.state.poller = SimpleNamespace(
        traffic_snapshot=[], traffic_snapshot_ts=0.0,
        bruegge_position_merken=lambda cid, lage, **kw: gemerkt.append((cid, kw)),
    )
    try:
        k = _melden(env)["kennung"]
        _verbindung(env.db, 49, "FRS49")
        _melden(env, kennung=k)
    finally:
        del env.main.app.state._state["poller"]
    assert gemerkt and gemerkt[-1][0] == 49
    assert gemerkt[-1][1] == {"bewaehrt": False, "cs": "FRS49"}
