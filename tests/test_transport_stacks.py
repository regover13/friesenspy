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


def test_s1_normalfall_landung_am_ziel_liefert():
    """S1: EDWG -> EDXH. Heute wie neu 800 kg."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDXH"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][DEST]["Fischbrötchen"] == 800.0
    assert _sum_onboard(r["onboard"]) == 0.0
    _assert_erhaltung(r)


def test_s2_milchmann_erste_ladung_bleibt_an_bord():
    """S2: EDWG -> EDWZ -> EDXH. HEUTE: 0 Fisch + 500 Tee (die erste Ladung verschwindet).
    Stapel-Modell: 800 Fisch + 200 Tee = 1000 (die Zuladung ist die Grenze)."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),                               # lädt 800 Fisch
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDWZ"),         # Ladeplatz: füllt auf
            _ev("takeoff", 1, "2026-07-01T09:40:00Z"),
            _ev("landing", 1, "2026-07-01T10:10:00Z", "EDXH"),         # liefert alles
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][DEST]["Fischbrötchen"] == 800.0
    assert r["stacks"][DEST]["Friesen Tee"] == 200.0     # nur 200 passten noch in die 1000 kg
    assert r["stacks"]["EDWZ"]["Friesen Tee"] == 300.0   # der Rest liegt weiter in EDWZ
    _assert_erhaltung(r)


def test_carried_liefert_die_bordladung_je_leg():
    """WURZEL des „leere Zwischenlegs"-Funds (Michael 19.07.): derive_stacks liefert je Abheben die
    Bordladung (`carried`, Schlüssel (cid, takeoff-ts)) — die Modell-Wahrheit „was trug er auf DIESEM
    Leg". Der Feed zeigt damit auch die durchgetragene Ware auf Zwischenlegs statt „leer".

    Milchmann EDWG -> EDWZ -> EDXH: Leg 1 trägt nur die EDWG-Ladung, Leg 2 zusätzlich den
    EDWZ-Nachschub. Ein wirklich leeres Leg hätte einen leeren Snapshot (bleibt „leer")."""
    to1 = "2026-07-01T09:05:00Z"
    to2 = "2026-07-01T09:40:00Z"
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),                        # lädt 800 Fisch
            _ev("takeoff", 1, to1),                             # Leg 1 hebt ab: 800 Fisch an Bord
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDWZ"),  # Ladeplatz: 200 Tee dazu
            _ev("takeoff", 1, to2),                             # Leg 2 hebt ab: 800 Fisch + 200 Tee
            _ev("landing", 1, "2026-07-01T10:10:00Z", "EDXH"),  # liefert alles
        ],
        destination=DEST, loading_airports=LOADING,
    )
    carried = r["carried"]
    assert carried[(1, to1)] == {"Fischbrötchen": 800.0}
    assert carried[(1, to2)] == {"Fischbrötchen": 800.0, "Friesen Tee": 200.0}
    _assert_erhaltung(r)


def test_carried_leeres_leg_bleibt_leer():
    """Gegenprobe: ein Leg ohne Ware an Bord (Leerflug/Rückflug) hat einen leeren Snapshot — der
    Feed zeigt weiter „leer", der Fix erfindet keine Ladung."""
    to = "2026-07-01T09:05:00Z"
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDDW"),   # fremder Platz: lädt nichts
            _ev("takeoff", 1, to),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDXH"),
        ],
        destination=DEST, loading_airports=LOADING,
    )
    assert r["carried"][(1, to)] == {}


def test_s3_zwischenlandung_am_fremden_platz_aendert_nichts():
    """S3: EDWG -> EDDW(fremd) -> EDXH. HEUTE ohne Latch 0 kg, mit Latch 1000 kg (Tee, der nie
    an Bord war). Stapel-Modell: 800 Fisch — EDDW hat keinen Stapel."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDDW"),   # fremd: nichts passiert
            _ev("takeoff", 1, "2026-07-01T09:40:00Z"),
            _ev("landing", 1, "2026-07-01T10:10:00Z", "EDXH"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][DEST]["Fischbrötchen"] == 800.0
    assert r["stacks"][DEST]["Friesen Tee"] == 0.0       # Tee war nie an Bord
    assert r["stacks"]["EDWZ"]["Friesen Tee"] == 500.0
    _assert_erhaltung(r)


def test_landung_am_ziel_liefert_sofort_ohne_disconnect():
    """Der Latch beantwortete 'hat er geliefert?' — das Modell weiß es beim Touchdown."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDXH"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][DEST]["Fischbrötchen"] == 800.0   # kein logout nötig
    assert r["position"][1] == "EDXH"                     # steht am Ziel, bleibt sichtbar


def test_s4_logout_am_zweiten_ladeplatz_gibt_dort_zurueck():
    """S4: EDWG -> EDWZ, Logout. HEUTE: 'returned' -> zurück in den EDWG-Topf.
    Nutzer 15.07.: 'Die Ware bleibt an dem Platz, an dem ausgeloggt wird!'"""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),                        # lädt 800 Fisch
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDWZ"),  # + 200 Tee (Kapazität 1000)
            _ev("logout", 1, "2026-07-01T09:35:00Z"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"]["EDWZ"]["Fischbrötchen"] == 800.0   # liegt jetzt in EDWZ, NICHT in EDWG
    assert r["stacks"]["EDWZ"]["Friesen Tee"] == 500.0      # 300 lagen noch da + 200 zurück
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 0.0
    _assert_erhaltung(r)


def test_s5_logout_am_fremden_platz_ist_diebstahl():
    """S5: EDWG -> EDDW(fremd), Logout. Er nimmt die Ware mit nach Hause."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDDW"),
            _ev("logout", 1, "2026-07-01T09:35:00Z"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][STOLEN]["Fischbrötchen"] == 800.0
    _assert_erhaltung(r)


def test_s8_logout_in_der_luft_versenkt():
    """S8 — der Nutzer-Fund vom 15.07. (Event #123, CID 1602713, flights.id 357/358).

    Der Pilot loggt kurz nach dem Start IN DER LUFT aus und Sekunden später am Platz wieder ein.
    Der GPS-Detektor macht daraus EIN Leg EDXH->EDXH mit sauberer Landung — der Logout ist für
    ihn unsichtbar. Eine Regel 'letzter Leg -> gps_arrival' ergäbe fälschlich 'zurück'.
    Hier fällt es von selbst richtig: takeoff hat position auf None gesetzt.
    """
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),                          # lädt 800 Fisch
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),            # position -> None
            _ev("logout", 1, "2026-07-01T09:07:00Z"),             # IN DER LUFT -> versenkt
            _ev("login", 1, "2026-07-01T09:08:00Z", "EDWG"),      # sofort wieder da, leer
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][SUNK]["Fischbrötchen"] == 800.0
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 0.0   # der Stapel ist leer, nichts nachzuladen
    assert _sum_onboard(r["onboard"]) == 0.0
    _assert_erhaltung(r)


def test_logout_am_ziel_verliert_nichts():
    """Bei der Landung wurde längst geliefert — der Logout findet einen leeren Flieger vor."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDXH"),
            _ev("logout", 1, "2026-07-01T09:35:00Z"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][DEST]["Fischbrötchen"] == 800.0
    assert r["stacks"][STOLEN]["Fischbrötchen"] == 0.0   # NICHT gestohlen
    assert r["stacks"][SUNK]["Fischbrötchen"] == 0.0


def test_logout_gibt_auch_frisch_geladenes_zurueck():
    """Entscheidung 4: 'Auch mit dem, was er eben erst geladen hat.'"""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[_ev("login", 1, T0, "EDWG"), _ev("logout", 1, "2026-07-01T09:01:00Z")],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 800.0
    _assert_erhaltung(r)


def test_zweiter_login_ohne_logout_verliert_keine_ware():
    """Fable-Review 16.07. — der Erhaltungssatz braecher sonst in einem REALEN Fall.

    Trigger: Ein ungracefuler Disconnect lässt die alte flights-Zeile offen (logoff_time NULL),
    der Reconnect erzeugt eine neue. close_stale_flights räumt erst nach 8 h auf (database.py:895).
    In diesem Fenster liefert der Adapter zwei login-Ereignisse OHNE logout dazwischen. Würde
    login die Bordladung einfach leeren, verschwänden 800 kg aus dem Universum — und weil dann
    Summe onboard == 0 gilt, könnte das Event mit der verschwundenen Ware sogar EINFRIEREN
    (transport_anyone_in_progress = False). Der Freeze ist endgültig.

    Der zweite Login verteilt die alte Ladung deshalb wie ein Logout: dieselbe Regel, derselbe
    Helfer (_drop_load) — kein Sonderfall.
    """
    r = derive_stacks(
        manifest=MANIFEST,
        events=[_ev("login", 1, T0, "EDWG"), _ev("login", 1, "2026-07-01T09:01:00Z", None)],
        destination=DEST, loading_airports=LOADING,
    )

    _assert_erhaltung(r)                                   # <- der eigentliche Test
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 800.0   # stand am Ladeplatz -> zurück


CAPPED = [
    {"name": "Fischbrötchen", "target_kg": 800.0, "departure": "EDWG", "per_flight_max_kg": 50.0},
    {"name": "Friesen Tee", "target_kg": 500.0, "departure": "EDWG", "per_flight_max_kg": None},
]


def test_kappung_begrenzt_was_an_bord_ist_nicht_den_ladevorgang():
    """Fable-Review: sonst wäre die Kappung durch mehrfaches Landen umgehbar (zehn Platzrunden
    = zehnmal die Kappungsmenge, alles in EINER Lieferung)."""
    r = derive_stacks(
        manifest=CAPPED,
        events=[
            _ev("login", 1, T0, "EDWG"),                          # nimmt 50 Fisch + 500 Tee
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:10:00Z", "EDWG"),    # Platzrunde: NICHT nochmal 50
            _ev("takeoff", 1, "2026-07-01T09:15:00Z"),
            _ev("landing", 1, "2026-07-01T09:20:00Z", "EDWG"),    # und nochmal nicht
        ],
        destination=DEST, loading_airports={"EDWG"},
    )

    assert r["onboard"][1]["Fischbrötchen"] == 50.0     # nicht 150
    assert r["onboard"][1]["Friesen Tee"] == 500.0
    _assert_erhaltung(r)


def test_kappung_spillt_in_die_naechste_frachtart():
    """Co-Load: was die Kappung übrig lässt, füllt die nächste Zeile (Bestandsverhalten)."""
    r = derive_stacks(manifest=CAPPED, events=[_ev("login", 1, T0, "EDWG", capacity_kg=200.0)],
                      destination=DEST, loading_airports={"EDWG"})

    assert r["onboard"][1]["Fischbrötchen"] == 50.0
    assert r["onboard"][1]["Friesen Tee"] == 150.0      # 200 kg Zuladung - 50 Fisch


def test_kappung_gilt_pro_name_ueber_zwei_ladeplaetze():
    """Nutzer-Beispiel 16.07.: Dieselbe Ware darf aus zwei Startplätzen kommen — aber die
    Bordladung dieses NAMENS darf die Kappung nie überschreiten. Kappung 100: In EDWG sind
    60 übrig und werden geladen; der Pilot fliegt nach EDDW weiter und lädt dort die restlichen
    40 nach (nicht mehr). Das ist schon heute richtig (Bordladung ist name-keyed) — dieser Test
    hält es fest, damit der #4-Fix es nicht bricht."""
    manifest = [
        {"name": "Sonnenschirme", "target_kg": 60.0, "departure": "EDWG", "per_flight_max_kg": 100.0},
        {"name": "Sonnenschirme", "target_kg": 200.0, "departure": "EDDW", "per_flight_max_kg": 100.0},
    ]
    r = derive_stacks(
        manifest=manifest,
        events=[
            _ev("login", 1, T0, "EDWG", capacity_kg=1000.0),            # lädt 60 (mehr ist nicht da)
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDDW"),          # lädt die restlichen 40 auf 100
            _ev("takeoff", 1, "2026-07-01T09:40:00Z"),
            _ev("landing", 1, "2026-07-01T10:10:00Z", "EDXH"),          # liefert 100
        ],
        destination=DEST, loading_airports={"EDWG", "EDDW"},
    )

    assert r["stacks"][DEST]["Sonnenschirme"] == 100.0       # 60 + 40, exakt die Kappung
    assert r["stacks"]["EDDW"]["Sonnenschirme"] == 160.0     # 200 - 40 bleibt liegen
    assert _sum_stacks(r["stacks"]) + _sum_onboard(r["onboard"]) == pytest.approx(260.0)


def test_ungleiche_kappung_pro_name_nimmt_die_strengste():
    """#4: Tragen zwei Zeilen desselben Namens UNTERSCHIEDLICHE Kappungen, gilt pro Name die
    STRENGSTE (kleinster Wert). Sonst nähme der Pilot am zweiten Platz gegen die lockerere
    Kappung nach und die Bordladung überschritte die strengere (100). Nutzer-Entscheidung 16.07.
    (1b): gleiche Ware aus zwei Quellen erlaubt, aber die Kappung gilt für den Namen insgesamt."""
    manifest = [
        {"name": "Sonnenschirme", "target_kg": 200.0, "departure": "EDWG", "per_flight_max_kg": 100.0},
        {"name": "Sonnenschirme", "target_kg": 200.0, "departure": "EDDW", "per_flight_max_kg": 500.0},
    ]
    r = derive_stacks(
        manifest=manifest,
        events=[
            _ev("login", 1, T0, "EDWG", capacity_kg=1000.0),            # lädt bis zur Kappung 100
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDDW"),          # DARF nichts nachladen
        ],
        destination=DEST, loading_airports={"EDWG", "EDDW"},
    )

    assert r["onboard"][1]["Sonnenschirme"] == 100.0         # strengste Kappung, NICHT 300
    assert _sum_stacks(r["stacks"]) + _sum_onboard(r["onboard"]) == pytest.approx(400.0)


def test_der_wartende_laedt_nach_wenn_ware_zurueckkommt():
    """Entscheidung 13: Steht jemand am leeren Stapel und ein anderer gibt dort zurück,
    lädt der Wartende — er steht ja am Platz, und Ware ist da."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),                              # nimmt alle 800
            _ev("login", 2, "2026-07-01T09:01:00Z", "EDWG"),          # steht am leeren Stapel
            _ev("logout", 1, "2026-07-01T09:02:00Z"),                 # gibt 800 zurück
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["onboard"][2]["Fischbrötchen"] == 800.0   # der Wartende hat nachgeladen
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 0.0
    _assert_erhaltung(r)


def test_von_zwei_wartenden_laedt_der_laenger_stehende():
    """Entscheidung 5, der einzige Fall, in dem die Ankunftsreihenfolge überhaupt befragt wird.

    Bei nur EINEM Wartenden ist die Sortierung wirkungslos: `_load_standing` läuft nach jedem
    Ereignis, der Erste hat den Stapel also leergeräumt, bevor der Zweite überhaupt einloggt.
    Erst wenn ZWEI am leeren Stapel stehen und Ware zurückkommt, entscheidet der Schlüssel,
    wer sie bekommt.

    Die später angekommene CID ist absichtlich die KLEINERE (3 vor 2): sonst wären Ankunfts-
    und CID-Reihenfolge identisch und ein `sorted(standing)` ohne `since` bliebe grün.
    """
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),                              # nimmt alle 800
            _ev("login", 3, "2026-07-01T09:01:00Z", "EDWG"),          # wartet, größere CID
            _ev("login", 2, "2026-07-01T09:02:00Z", "EDWG"),          # wartet, aber später da
            _ev("logout", 1, "2026-07-01T09:03:00Z"),                 # gibt 800 zurück
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["onboard"][3]["Fischbrötchen"] == 800.0   # stand länger da
    assert r["onboard"][2]["Fischbrötchen"] == 0.0     # kleinere CID, aber zu spät
    _assert_erhaltung(r)


def test_musterwechsel_am_boden_laedt_mit_der_neuen_kapazitaet():
    """Entscheidung 11: Am Boden wird umgeladen. Braucht keine eigene Regel — der Musterwechsel
    IST ein Logout (Ladung fällt ab) plus ein Login (lädt neu, mit neuer Kapazität)."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG", capacity_kg=1000.0),
            _ev("logout", 1, "2026-07-01T09:05:00Z"),                          # gibt 800 zurück
            _ev("login", 1, "2026-07-01T09:06:00Z", "EDWG", capacity_kg=250.0),  # kleineres Muster
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["onboard"][1]["Fischbrötchen"] == 250.0
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 550.0
    _assert_erhaltung(r)
