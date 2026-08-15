"""Tests für den Fremdverkehr auf der Karte (/api/traffic).

Der Fremdverkehr wird bewusst NICHT in der Datenbank gehalten: Er ist reine Anzeige,
niemand wertet ihn aus, und eine Historie über ~1000 Flugzeuge im 15-Sekunden-Takt wäre in
Tagen größer als alles andere in dieser Datenbank zusammen. Der Poller hält deshalb nur
eine Momentaufnahme im Speicher, die dieser Endpunkt auf den Umkreis der Kartenmitte
zuschneidet.

Siehe docs/superpowers/specs/2026-08-15-fremdverkehr-karte-design.md.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.database import init_db
from app.vatsim import snapshot_other_traffic


def _pilot(callsign, lat, lon, **kw):
    p = {
        "cid": kw.get("cid", 1),
        "callsign": callsign,
        "latitude": lat,
        "longitude": lon,
        "altitude": kw.get("altitude", 3000),
        "groundspeed": kw.get("groundspeed", 120),
        "heading": kw.get("heading", 90),
    }
    if "aircraft_short" in kw:
        p["flight_plan"] = {
            "aircraft_short": kw["aircraft_short"],
            "departure": kw.get("departure", "EDDH"),
            "arrival": kw.get("arrival", "EDDF"),
        }
    return p


def test_friesen_fallen_aus_dem_fremdverkehr_heraus():
    daten = {"pilots": [_pilot("FRS001", 53.5, 8.0), _pilot("DLH4AB", 53.6, 8.1)]}
    roh = snapshot_other_traffic("FRS", daten)
    assert [e["cs"] for e in roh] == ["DLH4AB"]


def test_eintraege_ohne_koordinate_fallen_heraus():
    daten = {"pilots": [
        _pilot("AAA1", None, 8.0),
        _pilot("BBB2", 53.5, None),
        _pilot("CCC3", 0, 0),        # 0/0 ist der Platzhalter des Feeds, kein Flugzeug
        _pilot("DDD4", 53.5, 8.0),
    ]}
    assert [e["cs"] for e in snapshot_other_traffic("FRS", daten)] == ["DDD4"]


def test_muster_ohne_flugplan_bleibt_leer():
    daten = {"pilots": [_pilot("AAA1", 53.5, 8.0)]}
    assert snapshot_other_traffic("FRS", daten)[0]["ac"] == ""


def test_muster_kommt_aus_dem_flugplan():
    daten = {"pilots": [_pilot("AAA1", 53.5, 8.0, aircraft_short="C172")]}
    e = snapshot_other_traffic("FRS", daten)[0]
    assert e["ac"] == "C172" and e["dep"] == "EDDH" and e["arr"] == "EDDF"


def test_kaputte_eingaben_werfen_nicht():
    assert snapshot_other_traffic("FRS", {}) == []
    assert snapshot_other_traffic("FRS", {"pilots": None}) == []
    assert snapshot_other_traffic("FRS", {"pilots": ["kein dict"]}) == []


# ---------------------------------------------------------------------------
# Der Endpunkt
# ---------------------------------------------------------------------------

@pytest.fixture()
def klient(tmp_path, monkeypatch):
    """TestClient mit einer Poller-Attrappe, die eine Momentaufnahme bereithält.

    ``get_settings`` wird gepatcht, weil der Endpunkt über ``_current_cid`` den
    Anmeldezustand prüft (um den Anfragenden selbst auszufiltern) -- ohne Patch liefe das
    gegen die echte Konfiguration.

    Der vorherige Zustand von ``app.state`` wird wiederhergestellt: ``main.app`` ist
    modulweit geteilt, und andere Testdateien greifen direkt (ohne ``getattr``) darauf zu.
    """
    p = str(tmp_path / "t.db")
    init_db(p)
    settings = SimpleNamespace(DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY="s3cr3t",
                               SSO_SECRET="", FORUM_SSO_URL="")
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main._reset_gate_cache()

    # Bezugspunkt Bremen 53.05/8.79. Distanzen mit app.geo.haversine nachgerechnet:
    #   NAH1  53.63/9.99  -> 102,5 km
    #   FERN1 51.30/8.79  -> 194,6 km   (muss UNTER dem Maximum 250 km liegen, sonst
    #                                    kann der Sortier-Test gar nicht gruen werden)
    poller = SimpleNamespace(
        traffic_snapshot=[
            {"cid": 111, "cs": "NAH1", "lat": 53.63, "lon": 9.99, "alt": 3000, "gs": 120,
             "hdg": 90, "ac": "C172", "dep": "", "arr": ""},
            {"cid": 222, "cs": "FERN1", "lat": 51.30, "lon": 8.79, "alt": 35000, "gs": 450,
             "hdg": 180, "ac": "A320", "dep": "", "arr": ""},
        ],
        traffic_snapshot_ts=time.time(),
    )
    vorher = getattr(main.app.state, "poller", None)
    main.app.state.poller = poller
    yield SimpleNamespace(client=TestClient(main.app), poller=poller)
    main.app.state.poller = vorher


def test_radius_schneidet_das_ferne_flugzeug_weg(klient):
    """150 km liegt zwischen den beiden (102,5 und 194,6 km)."""
    r = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79, "r": 150})
    assert r.status_code == 200
    assert [e["cs"] for e in r.json()["traffic"]] == ["NAH1"]


def test_grosser_radius_nimmt_beide_und_sortiert_nach_naehe(klient):
    r = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79, "r": 250})
    assert [e["cs"] for e in r.json()["traffic"]] == ["NAH1", "FERN1"]


def test_cid_geht_nicht_an_den_client(klient):
    """Sie dient nur dem Aussortieren des Anfragenden -- der Client braucht sie nicht."""
    r = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79})
    assert all("cid" not in e for e in r.json()["traffic"])


def test_deckel_bei_sechzig_flugzeugen(klient):
    klient.poller.traffic_snapshot = [
        {"cid": i, "cs": "X%03d" % i, "lat": 53.05 + i * 0.001, "lon": 8.79, "alt": 1000,
         "gs": 100, "hdg": 0, "ac": "", "dep": "", "arr": ""}
        for i in range(100)
    ]
    r = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79, "r": 250})
    daten = r.json()["traffic"]
    assert len(daten) == 60
    assert daten[0]["cs"] == "X000"      # das naechste gewinnt, nicht das erste im Feed


def test_alter_wird_mitgeliefert(klient):
    klient.poller.traffic_snapshot_ts = time.time() - 7
    r = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79})
    assert 6.0 <= r.json()["age"] <= 8.5


def test_veraltete_momentaufnahme_liefert_leer_statt_falsch(klient):
    klient.poller.traffic_snapshot_ts = time.time() - 500
    d = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79}).json()
    assert d == {"age": None, "traffic": []}


def test_ohne_poller_keine_fehlermeldung(klient):
    main.app.state.poller = None
    d = klient.client.get("/api/traffic", params={"lat": 53.05, "lon": 8.79}).json()
    assert d == {"age": None, "traffic": []}


@pytest.mark.parametrize("params", [
    {"lat": 91, "lon": 8.79},
    {"lat": 53.05, "lon": 181},
    {"lat": 53.05, "lon": 8.79, "r": 0},
    {"lat": 53.05, "lon": 8.79, "r": 999},
    {"lon": 8.79},
])
def test_unsinnige_parameter_werden_abgewiesen(klient, params):
    assert klient.client.get("/api/traffic", params=params).status_code == 422


@pytest.mark.asyncio
async def test_poll_zyklus_fuellt_die_momentaufnahme(tmp_path, monkeypatch):
    """Die zwei Zeilen in _poll_once sind die einzige Stelle, an der Funktion und Poller
    zusammenkommen -- und die wahrscheinlichste für einen stillen Ausfall (falsche
    Einrückung im großen try, Attribut nie gesetzt, import vergessen). Ohne diesen Test
    prüfen alle anderen nur eine Attrappe."""
    from app.poller import VatsimPoller

    db = str(tmp_path / "t.db")
    init_db(db)
    poller = VatsimPoller(db_path=db, callsign_prefix="FRS")

    async def gefaelschter_feed(_client):
        return {"pilots": [
            {"cid": 1, "callsign": "FRS001", "latitude": 53.5, "longitude": 8.0,
             "altitude": 2000, "groundspeed": 100, "heading": 0},
            {"cid": 2, "callsign": "DLH4AB", "latitude": 53.6, "longitude": 8.1,
             "altitude": 30000, "groundspeed": 440, "heading": 270},
        ]}

    monkeypatch.setattr("app.poller.fetch_vatsim_data", gefaelschter_feed)
    poller._http_client = object()          # nur die assert-Wache in _poll_once bedienen
    await poller._poll_once()

    assert [e["cs"] for e in poller.traffic_snapshot] == ["DLH4AB"]
    assert poller.traffic_snapshot_ts > 0
