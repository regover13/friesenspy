"""on blocks / off blocks — wann endet das Blockfenster eines Legs?

Die Blockzeit laeuft von *off blocks* (Verlassen der Abstellposition) bis *on blocks*
(Erreichen der Abstellposition). Ein Halt unterwegs — Warten auf Freigabe, Standlaufprobe,
Warteschlange — ist NICHT on blocks und bleibt in der Blockzeit.

Welche Stillstandsphase das Abstellen ist, haengt davon ab, was danach passiert; die drei
Faelle stehen im Docstring von :func:`app.database._extend_block_end`.
"""
from __future__ import annotations

from app import geo
from app.database import _extend_block_end, _leg_block_seconds

EDWF = geo.icao_to_coords("EDWF")


def _pos(ts: str, gs: float, coord=EDWF) -> dict:
    return {"ts": f"2026-06-27T{ts}Z", "latitude": coord[0], "longitude": coord[1],
            "altitude": 20, "groundspeed": gs}


def _spur(*abschnitte) -> list[dict]:
    """(startminute, dauer_min, groundspeed) -> Positionsliste im 15-s-Takt."""
    out = []
    for start_min, dauer_min, gs in abschnitte:
        for i in range(int(dauer_min * 4)):
            t = start_min * 60 + i * 15
            out.append(_pos(f"{10 + t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}", gs))
    return out


class TestNaechsterStartFolgt:
    """Fall 1: Es folgt ein weiterer Start — die LAENGSTE Phase ist das Abstellen."""

    def test_laengste_phase_gewinnt_nicht_die_erste(self):
        # Landung 10:00, kurzer Halt (1 min), weiterrollen, dann 6 min abgestellt, dann Start.
        spur = _spur((0, 1, 0), (1, 1, 8), (2, 6, 0), (8, 1, 30))
        ende = _extend_block_end(spur, "2026-06-27T09:59:45Z", "2026-06-27T10:09:00Z")
        assert ende == "2026-06-27T10:02:00Z", ende

    def test_kurzer_halt_unterwegs_beendet_den_block_nicht(self):
        """Ein Halt VOR dem Abstellen darf on blocks nicht vorziehen."""
        spur = _spur((0, 2, 0), (2, 2, 10), (4, 9, 0))
        ende = _extend_block_end(spur, "2026-06-27T09:59:45Z", "2026-06-27T10:13:00Z")
        assert ende == "2026-06-27T10:04:00Z", ende


class TestAusgeloggt:
    """Fall 2: Der Track endet — Ausloggen ist das Ende, nichts abzuwarten."""

    def test_endet_im_stillstand_schneidet_die_pause_ab(self):
        spur = _spur((0, 3, 12), (3, 2, 0))          # rollt ein, steht 2 min, Ende
        ende = _extend_block_end(spur, "2026-06-27T09:59:45Z", None, track_beendet=True)
        assert ende == "2026-06-27T10:03:00Z", ende

    def test_ohne_zehn_minuten_zu_warten(self):
        """Zwei Minuten Stillstand genuegen, wenn danach ausgeloggt wird."""
        spur = _spur((0, 1, 12), (1, 2, 0))
        ende = _extend_block_end(spur, "2026-06-27T09:59:45Z", None, track_beendet=True)
        assert ende == "2026-06-27T10:01:00Z", ende

    def test_endet_in_bewegung_zaehlt_bis_zum_letzten_punkt(self):
        """Nach der Pause wurde noch gerollt (Hangar) — das bleibt Blockzeit."""
        spur = _spur((0, 2, 0), (2, 2, 10))
        ende = _extend_block_end(spur, "2026-06-27T09:59:45Z", None, track_beendet=True)
        assert ende == spur[-1]["ts"], ende


class TestStehtUndBleibtOnline:
    """Fall 3: Kein Start, kein Logout — erst die Schwelle belegt das Abstellen."""

    def test_unter_der_schwelle_laeuft_der_block_weiter(self):
        spur = _spur((0, 1, 12), (1, 5, 0))          # nur 5 min Stillstand
        ende = _extend_block_end(spur, "2026-06-27T09:59:45Z", None, track_beendet=False)
        assert ende == spur[-1]["ts"], ende

    def test_ab_zehn_minuten_gilt_die_phase(self):
        spur = _spur((0, 1, 12), (1, 11, 0))
        ende = _extend_block_end(spur, "2026-06-27T09:59:45Z", None, track_beendet=False)
        assert ende == "2026-06-27T10:01:00Z", ende


class TestZwischenhaltWirdNichtDoppeltGezaehlt:
    def test_standzeit_gehoert_keinem_leg(self):
        """Der reale Fall vom 07.09.2026 (Aach-Bummel, Zwischenstopp EDSR).

        Leg A endete frueher erst beim naechsten Abheben — damit steckte die Standzeit in A
        und das Anrollen zusaetzlich in B.
        """
        spur = _spur((0, 1, 0), (1, 5, 0), (6, 2, 25))   # steht 6 min, dann anrollen
        naechster_takeoff = "2026-06-27T10:08:00Z"
        ende_a = _extend_block_end(spur, "2026-06-27T09:59:45Z", naechster_takeoff)
        beginn_b = next(p["ts"] for p in spur if p["groundspeed"] > 2)
        assert ende_a <= beginn_b, (
            f"Leg A endet {ende_a}, Leg B beginnt {beginn_b} — das ueberlappt"
        )

    def test_kurzer_halt_wird_nicht_von_der_blockzeit_abgezogen(self):
        """Innerhalb eines Legs bleibt ein kurzer Halt Blockzeit (gate-to-gate)."""
        spur = _spur((0, 2, 20), (2, 2, 0), (4, 2, 20))
        sek = _leg_block_seconds(spur, spur[0]["ts"], spur[-1]["ts"])
        assert sek == (len(spur) - 1) * 15, sek   # volle Wanduhr, nichts abgezogen


class TestSekundenBleibenErhalten:
    """Die Blockzeit wird nicht auf ganze Minuten abgeschnitten.

    Frueher ging die Wertung ueber ``block_min * 60`` und verlor pro Leg bis zu 59 Sekunden.
    Am 07.09.2026 hatten dadurch zwei Piloten mit 109:30 und 109:45 beide exakt 108:00 und
    denselben Abstand zum Schnitt. Die Aufloesung bleibt das Poll-Raster des Feeds (15 s) —
    so genau wie die Positionsdaten, nicht genauer.
    """

    def test_blockzeit_behaelt_ihre_sekunden(self):
        spur = _spur((0, 45, 20))                    # 180 Punkte im 15-s-Takt = 44:45
        sek = _leg_block_seconds(spur, spur[0]["ts"], spur[-1]["ts"])
        assert sek == 2685, sek
        assert sek % 60 != 0, "krumme Werte muessen krumm bleiben"
        assert sek // 60 == 44 and sek - 44 * 60 == 45

    def test_wertung_nutzt_block_sec_nicht_block_min(self):
        """Verankert an der Implementierung: die Summe kommt aus ``block_sec``."""
        import inspect
        from app import database
        quelle = inspect.getsource(database.compute_bummel_standings)
        assert 'block_s = f.get("block_sec")' in quelle
        assert "minutes * 60" in quelle, "Rueckfall ohne Track muss erhalten bleiben"



class TestEinzelnerMesspunktIstKeinAbstellen:
    """Ein einzelnes ``gs=0``-Sample belegt keine Zeitspanne.

    Es kann ein kurzer Halt an der Haltelinie sein oder ein Ausreisser. Als on blocks zaehlt
    nur, was ueber mindestens zwei Punkte hinweg steht. Ohne diese Pruefung wurde im
    Turnaround ein einzelner Punkt zum „Abstellen" — Leg 1 endete zu spaet und der Kern-Test
    ``TestPrevEndBoundary`` brach (gefunden 08.09.2026).
    """

    def test_einzelpunkt_beendet_den_block_nicht(self):
        # rollt, EIN Sample mit gs=0, rollt weiter, dann Start -> kein on blocks
        spur = _spur((0, 1, 10)) + [_pos("10:01:00", 0)] + _spur((2, 1, 12))
        ende = _extend_block_end(spur, "2026-06-27T09:59:45Z", "2026-06-27T10:03:00Z")
        assert ende == "2026-06-27T09:59:45Z", ende   # Fallback: die Landung

    def test_zwei_punkte_zaehlen_schon(self):
        spur = _spur((0, 1, 10), (1, 1, 0), (2, 1, 12))
        ende = _extend_block_end(spur, "2026-06-27T09:59:45Z", "2026-06-27T10:04:00Z")
        assert ende == "2026-06-27T10:01:00Z", ende


class TestKeineDoppelzaehlungUeberLegGrenzen:
    """Das Einrollen des einen Legs darf nicht als „erste Bewegung" des naechsten gelten.

    ``taxi_start_ts`` eines Legs ist der Beginn der ON_GROUND-Phase — und die faengt mit dem
    AUFSETZEN des Vorgaengers an (bewusst so, s. Commit be772c7: „Turnaround gehoert zum
    Folge-Leg"). Hat der Vorgaenger danach ein echtes on blocks, wuerde sein Einrollen sonst
    in BEIDEN Blockzeiten stehen (gemessen 08.09.2026: 20 Uebergaenge, zusammen 17,6 min).
    """

    def _zwei_fluege(self) -> list[dict]:
        a, b, c = (geo.icao_to_coords(x) for x in ("EDWF", "EDWG", "EDWR"))
        plan = [
            (0.0, a, 20, 0), (1.0, a, 20, 25),
            (3.0, a, 1200, 85), (8.0, b, 3000, 110),
            (13.0, b, 400, 60), (14.0, b, 20, 0),       # Landung
            (15.0, b, 20, 12),                          # einrollen -> gehoert zu Leg 1
            # Pause unter _BLOCK_STAND_MIN_SEC: laenger wuerde sie abgezogen und die
            # Doppelzaehlung zufaellig ausgleichen — der Fehler waere unsichtbar.
            (16.0, b, 20, 0), (21.0, b, 20, 0),         # abgestellt (5 min)
            (22.0, b, 20, 15),                          # anrollen -> Leg 2
            (24.0, b, 1200, 85), (29.0, c, 3000, 110),
            (34.0, c, 400, 60), (35.0, c, 20, 0),
            (37.0, c, 20, 0), (49.0, c, 20, 0),
        ]
        out = []
        for minute, coord, alt, gs in plan:
            t = int(minute * 60)
            out.append({"ts": f"2026-06-27T10:{t // 60:02d}:{t % 60:02d}Z",
                        "latitude": coord[0], "longitude": coord[1],
                        "altitude": alt, "groundspeed": gs})
        return out

    def test_leg_zwei_beginnt_nicht_vor_leg_eins_ende(self):
        from app.database import _gps_flights_for_positions, _parse_iso
        fluege = _gps_flights_for_positions(
            self._zwei_fluege(), plan_rows=[], source="friesenspy", radius_km=10)
        assert len(fluege) >= 2, [f.get("departure") for f in fluege]
        a, b = fluege[0], fluege[1]
        beginn_b = _parse_iso(b["block_end"]).timestamp() - b["block_sec"]
        assert _parse_iso(a["block_end"]).timestamp() <= beginn_b, (
            f"Leg A endet {a['block_end']}, Leg B beginnt frueher — das Einrollen zaehlt doppelt"
        )
