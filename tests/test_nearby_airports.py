"""Regressionstests für das Messwerkzeug der Track-Diagnose.

Alle Erwartungswerte wurden am 2026-07-15 gemessen (Produktions-DB + airportsdata +
OurAirports-Vollabzug). Weicht ein Wert ab, ist das ein Befund — kein Grund, die Zahl
anzupassen. Siehe docs/superpowers/specs/2026-07-15-track-diagnose-design.md
"""
from pathlib import Path

import pytest

from scripts.nearby_airports import find_code, load_ourairports

FIXTURE = Path(__file__).parent / "fixtures" / "ourairports_mini.csv"


def test_fixture_lädt_alle_fünf_plätze():
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
