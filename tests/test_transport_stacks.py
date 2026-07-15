"""Tests der Stapel-Ableitung — reine Funktion, keine DB, keine GPS-Tracks.

Die Fälle folgen den Szenarien aus scripts/kutter_ladung_szenarien.py (S1-S8), hier aber ohne
Track-Erzeugung: geprüft wird nur, was die Zustandsmaschine aus Ereignissen macht.
"""
import pytest

from app.transport_stacks import derive_stacks, STOLEN, SUNK

# Manifest wie in den Szenarien: zwei Ladeplätze, verschiedene Fracht, Ziel EDXH.
MANIFEST = [
    {"name": "Fischbrötchen", "target_kg": 800.0, "departure": "EDWG", "per_flight_max_kg": None},
    {"name": "Friesen Tee", "target_kg": 500.0, "departure": "EDWZ", "per_flight_max_kg": None},
]
DEST = "EDXH"
LOADING = {"EDWG", "EDWZ"}
T0 = "2026-07-01T09:00:00Z"


def _ev(kind, cid, ts, airport=None, capacity_kg=1000.0):
    return {"ts": ts, "kind": kind, "cid": cid, "airport": airport, "capacity_kg": capacity_kg}


def _sum_stacks(stacks):
    return sum(sum(inner.values()) for inner in stacks.values())


def _sum_onboard(onboard):
    return sum(sum(inner.values()) for inner in onboard.values())


def _assert_erhaltung(r, total=1300.0):
    """Der Erhaltungssatz: Summe Stapel + Summe Ladung == Summe Manifest. Immer."""
    assert _sum_stacks(r["stacks"]) + _sum_onboard(r["onboard"]) == pytest.approx(total)


def test_ohne_ereignisse_liegt_das_manifest_auf_seinen_stapeln():
    r = derive_stacks(manifest=MANIFEST, events=[], destination=DEST, loading_airports=LOADING)

    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 800.0
    assert r["stacks"]["EDWZ"]["Friesen Tee"] == 500.0
    assert _sum_onboard(r["onboard"]) == 0.0
    _assert_erhaltung(r)


def test_ein_leerer_stapel_ist_immer_noch_ein_stapel():
    """Entscheidung 3: Ein Ladeplatz ohne Ware bleibt ein Ort, kein fehlender Schlüssel."""
    manifest = [{"name": "Nichts", "target_kg": 0.0, "departure": "EDWG", "per_flight_max_kg": None}]
    r = derive_stacks(manifest=manifest, events=[], destination=DEST, loading_airports={"EDWG", "EDWZ"})

    assert "EDWZ" in r["stacks"]          # Ladeplatz ohne eigene Manifest-Zeile
    assert r["stacks"]["EDWG"]["Nichts"] == 0.0


def test_ziel_gestohlen_versenkt_sind_auch_stapel():
    r = derive_stacks(manifest=MANIFEST, events=[], destination=DEST, loading_airports=LOADING)

    assert DEST in r["stacks"] and STOLEN in r["stacks"] and SUNK in r["stacks"]
    assert _sum_stacks({k: v for k, v in r["stacks"].items() if k in (DEST, STOLEN, SUNK)}) == 0.0
