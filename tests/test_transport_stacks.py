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


def test_login_am_ladeplatz_laedt_sofort():
    """Entscheidung 4: Am Boden wird geladen — auch ohne je gelandet zu sein.

    Kein neues Verhalten: schon heute reserviert ein am Ladeplatz geparkter Pilot seine volle
    Zuladung (tests/test_transport.py::test_open_flight_on_ground_is_not_airborne, reserved_kg
    == 292.0). Neu ist nur, dass aus der flüchtigen Reservierung eine echte Ladung wird.
    """
    r = derive_stacks(manifest=MANIFEST, events=[_ev("login", 1, T0, "EDWG")],
                      destination=DEST, loading_airports=LOADING)

    assert r["onboard"][1]["Fischbrötchen"] == 800.0
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 0.0
    _assert_erhaltung(r)


def test_abflug_laedt_nie_nur_die_position_wechselt():
    """Spec: 'Der Abflug lädt nie' — 'beim Abheben laden' ist NICHT bilanzgleich."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[_ev("login", 1, T0, "EDWG"), _ev("takeoff", 1, "2026-07-01T09:05:00Z")],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["position"][1] is None                      # unterwegs
    assert r["onboard"][1]["Fischbrötchen"] == 800.0    # beim Login geladen, nicht beim Abflug
    _assert_erhaltung(r)


def test_wer_am_fremden_platz_einloggt_laedt_nichts():
    r = derive_stacks(manifest=MANIFEST, events=[_ev("login", 1, T0, "EDDW")],
                      destination=DEST, loading_airports=LOADING)

    assert _sum_onboard(r["onboard"]) == 0.0
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 800.0


def test_wer_in_der_luft_einloggt_laedt_nichts():
    r = derive_stacks(manifest=MANIFEST, events=[_ev("login", 1, T0, None)],
                      destination=DEST, loading_airports=LOADING)

    assert r["position"][1] is None
    assert _sum_onboard(r["onboard"]) == 0.0


def test_wer_zuerst_kommt_laedt_zuerst_der_zweite_hat_pech():
    """Entscheidung 5: Kein Teilen, keine Quote."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[_ev("login", 1, T0, "EDWG"), _ev("login", 2, "2026-07-01T09:01:00Z", "EDWG")],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["onboard"][1]["Fischbrötchen"] == 800.0
    assert r["onboard"][2]["Fischbrötchen"] == 0.0
    _assert_erhaltung(r)
