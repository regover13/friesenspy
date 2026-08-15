"""Tests für den Fremdverkehr auf der Karte (/api/traffic).

Der Fremdverkehr wird bewusst NICHT in der Datenbank gehalten: Er ist reine Anzeige,
niemand wertet ihn aus, und eine Historie über ~1000 Flugzeuge im 15-Sekunden-Takt wäre in
Tagen größer als alles andere in dieser Datenbank zusammen. Der Poller hält deshalb nur
eine Momentaufnahme im Speicher, die dieser Endpunkt auf den Umkreis der Kartenmitte
zuschneidet.

Siehe docs/superpowers/specs/2026-08-15-fremdverkehr-karte-design.md.
"""
from __future__ import annotations

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
