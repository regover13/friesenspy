"""Regressionstests für das Messwerkzeug der Track-Diagnose.

Alle Erwartungswerte wurden am 2026-07-15 gemessen (Produktions-DB + airportsdata +
OurAirports-Vollabzug). Weicht ein Wert ab, ist das ein Befund — kein Grund, die Zahl
anzupassen. Siehe docs/superpowers/specs/2026-07-15-track-diagnose-design.md
"""
from pathlib import Path

import pytest

from scripts.nearby_airports import airportsdata_refs, find_code, load_ourairports, measure

FIXTURE = Path(__file__).parent / "fixtures" / "ourairports_mini.csv"

# Referenzpunkte, gemessen am 2026-07-15 aus statsim_position_history (alle groundspeed 0):
EDHX_PUNKT = (54.18665, 7.91488)    # Track 29258369, 7 ft   — Helgoland-Düne
ETUO_PUNKT = (51.85449, 10.02288)   # Track 23066993, 779 ft — Bad Gandersheim
EBKT_PUNKT = (50.82005, 3.2163)     # Track 28531653, 71 ft  — Kortrijk-Wevelgem


def test_fixture_laedt_alle_fuenf_plaetze():
    refs = load_ourairports(FIXTURE)
    assert len(refs) == 5


def test_code_mit_leerem_icao_feld_wird_ueber_gps_code_gefunden():
    """EDHX und EBMO haben in OurAirports ein leeres icao_code-Feld — wer nur darauf
    schaut, verliert sie. Genau dieser Fall ist der EDHX-Beleg der Spec."""
    refs = load_ourairports(FIXTURE)

    edhx = find_code("EDHX", refs)
    assert edhx is not None
    assert edhx.name == "Bad Bramstedt Heliport"
    assert edhx.lat == pytest.approx(53.9428)
    assert edhx.elevation_ft == pytest.approx(118.0)

    assert find_code("EBMO", refs) is not None


def test_code_suche_ist_case_insensitiv_und_meldet_fehlende_codes():
    refs = load_ourairports(FIXTURE)
    assert find_code("ebkt", refs) is not None
    assert find_code("ETUO", refs) is None       # ETUO steht NICHT in OurAirports


@pytest.fixture(scope="module")
def ad_refs():
    return airportsdata_refs()


@pytest.fixture(scope="module")
def oa_refs():
    return load_ourairports(FIXTURE)


def test_edhx_fall_d_schlaegt_fall_a(ad_refs, oa_refs):
    """EDHX fehlt in airportsdata und erfüllt damit FORMAL das Kriterium von Fall A
    („Code fehlt → Ergänzung"). Der Bodenpunkt liegt aber 0,16 km von EDXH — der Pilot
    hatte den Code verdreht. Deshalb kommt Schritt 1 (wohin gehört der Punkt?) vor
    Schritt 2 (was ist mit dem Code?). Dieser Test IST diese Regel."""
    m = measure(*EDHX_PUNKT, icao="EDHX", ad_refs=ad_refs, oa_refs=oa_refs)

    assert m.ad_target is None                                    # nicht in airportsdata
    assert m.oa_target is not None
    assert m.oa_target.distance_km == pytest.approx(132.70, abs=0.05)
    assert m.ad_nearest[0].ref.code == "EDXH"
    assert m.ad_nearest[0].distance_km == pytest.approx(0.16, abs=0.02)


def test_etuo_soll_code_nur_in_airportsdata(ad_refs, oa_refs):
    """Spiegelbild zu EDHX: ETUO steht in airportsdata, aber NICHT in OurAirports.
    Beide Blöcke müssen unabhängig „fehlt" melden können."""
    m = measure(*ETUO_PUNKT, icao="ETUO", ad_refs=ad_refs, oa_refs=oa_refs)

    assert m.ad_target is not None
    assert m.ad_target.distance_km == pytest.approx(118.05, abs=0.05)
    assert m.oa_target is None
    assert m.ad_nearest[0].ref.code == "EDVA"
    assert m.ad_nearest[0].distance_km == pytest.approx(0.19, abs=0.02)


def test_ebkt_quellen_weichen_um_37_km_ab(ad_refs, oa_refs):
    """Der Belgien-Fund. Wichtig ist die zweite Hälfte: der nächste airportsdata-Platz
    ist EBMO in 6,06 km — über der 1-km-Schwelle von Schritt 1. Wäre er näher, wäre
    der Fund fälschlich als Fall D abgetan worden."""
    m = measure(*EBKT_PUNKT, icao="EBKT", ad_refs=ad_refs, oa_refs=oa_refs)

    assert m.ad_target.distance_km == pytest.approx(37.20, abs=0.05)
    assert m.oa_target.distance_km == pytest.approx(0.49, abs=0.02)
    assert m.source_delta_km["EBKT"] == pytest.approx(37.00, abs=0.05)
    assert m.ad_nearest[0].ref.code == "EBMO"
    assert m.ad_nearest[0].distance_km == pytest.approx(6.06, abs=0.05)


def test_agl_wird_nur_mit_alt_und_bekannter_elevation_gerechnet(ad_refs, oa_refs):
    ohne = measure(*EBKT_PUNKT, icao="EBKT", ad_refs=ad_refs, oa_refs=oa_refs)
    assert ohne.ad_nearest[0].agl_ft is None

    # EBMO liegt laut airportsdata auf 66 ft (gemessen 2026-07-15 — nicht aus OurAirports
    # übernehmen, die Quellen können bei der Elevation auseinanderlaufen).
    mit = measure(*EBKT_PUNKT, alt_ft=71, icao="EBKT", ad_refs=ad_refs, oa_refs=oa_refs)
    assert mit.ad_nearest[0].ref.code == "EBMO"
    assert mit.ad_nearest[0].agl_ft == pytest.approx(5, abs=1)


from app.database import _BUMMEL_AIRPORT_RADIUS_KM
from app.gps_legs import _GPS_SPAWN_MAX_AGL_FT
from scripts.nearby_airports import format_report

# Track 28133172 (FRS96, TBM9, EDDH->EDDM): erster Punkt, bereits airborne mit 217 kt.
EDDH_PUNKT = (53.49527, 10.00085)


def test_eddh_spawn_in_der_luft_reisst_beide_schwellen(ad_refs, oa_refs):
    """Der Punkt liegt 15,05 km von EDDH und 2156 ft über Platzhöhe. Ein Radius-Override
    wuerde NICHT helfen: die Spawn-Rettung (#49) verlangt zusaetzlich < 1500 ft AGL.
    Beide Schwellen werden importiert — aendert jemand sie, wird dieser Test rot, statt
    dass der Skill still falsch wird."""
    m = measure(*EDDH_PUNKT, alt_ft=2209, icao="EDDH", ad_refs=ad_refs, oa_refs=oa_refs)

    assert m.ad_target.distance_km == pytest.approx(15.05, abs=0.05)
    assert m.ad_target.distance_km > _BUMMEL_AIRPORT_RADIUS_KM
    assert m.ad_target.agl_ft == pytest.approx(2156, abs=1)
    assert m.ad_target.agl_ft > _GPS_SPAWN_MAX_AGL_FT

    report = format_report(m)
    assert "außerhalb" in report
    assert "überschritten" in report


def test_report_meldet_fehlenden_code_statt_zu_verschweigen(ad_refs, oa_refs):
    report = format_report(measure(*EDHX_PUNKT, icao="EDHX", ad_refs=ad_refs, oa_refs=oa_refs))
    assert "nicht vorhanden" in report
    assert "EDXH" in report
