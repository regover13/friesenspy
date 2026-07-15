"""Triage-Tests: sechs echte Fälle aus dem Export vom 2026-07-15, einer je Gruppe.

Jeder Test sichert eine Regel ab, die beim Entwurf real falsch war. Siehe
docs/superpowers/specs/2026-07-15-track-diagnose-design.md
"""
import json
from pathlib import Path

import pytest

from scripts.nearby_airports import airportsdata_refs, load_ourairports
from scripts.triage_gaps import (
    GRUPPE_ANDERER,
    GRUPPE_DUENN,
    GRUPPE_KANDIDAT,
    GRUPPE_LUFT,
    GRUPPE_ZZZZ,
    enden_aus_export,
    triagiere,
)

FIXTURE = Path(__file__).parent / "fixtures" / "gaps_mini.json"
OA_FIXTURE = Path(__file__).parent / "fixtures" / "ourairports_mini.csv"


@pytest.fixture(scope="module")
def faelle():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ad():
    return airportsdata_refs()


@pytest.fixture(scope="module")
def oa():
    return load_ourairports(OA_FIXTURE)


def _gruppe(faelle, ad, oa, statsim_id, seite):
    for ende in enden_aus_export(faelle):
        if ende.statsim_id == statsim_id and ende.seite == seite:
            return triagiere(ende, ad, oa).gruppe
    raise AssertionError("Ende %s/%s nicht im Export" % (statsim_id, seite))


def test_both_erzeugt_zwei_enden(faelle):
    enden = [e for e in enden_aus_export(faelle) if e.statsim_id == 25216444]
    assert sorted(e.seite for e in enden) == ["arrival", "departure"]
    # 29 der 163 Fälle vermissen beide Enden; eines kann trivial sein, das andere nicht.
    assert len(enden_aus_export(faelle)) == 10   # 6 Fälle, 4 davon "both"


def test_ein_punkt_track_schlaegt_nachbarschaft(faelle, ad, oa):
    """27831625 hat EINEN Trackpunkt, und EDNR liegt 0,06 km daneben. Ohne die
    Punktzahl-Prüfung wäre das ein Fall-D-Befund — formal richtig gemessen und
    trotzdem Unsinn. Sechs der ursprünglich neun D-Befunde waren solche Tracks."""
    assert _gruppe(faelle, ad, oa, 27831625, "departure") == GRUPPE_DUENN


def test_zzzz_schlaegt_luft(faelle, ad, oa):
    """27404430 ist mit gs 147 auch in der Luft. ZZZZ ist die stärkere Aussage:
    es gibt keinen Platz zu finden."""
    assert _gruppe(faelle, ad, oa, 27404430, "departure") == GRUPPE_ZZZZ


def test_eddh_spawn_in_der_luft(faelle, ad, oa):
    assert _gruppe(faelle, ad, oa, 28133172, "departure") == GRUPPE_LUFT


def test_stol_langsam_aber_hoch_ist_nicht_am_boden(faelle, ad, oa):
    """FRS125 ab ETNJ: gs 22 — nach einer groundspeed-zentrierten Regel ein Bodenpunkt.
    Die Höhe sagt 4401 ft. Höhe ist das Leitsignal (app/gps_legs.py:4), sonst werden
    STOL-Flüge (Wilga, ~40 kt Reise) systematisch fehlklassifiziert. Gemessen: 13 der
    184 Enden erkennt nur die Höhe."""
    assert _gruppe(faelle, ad, oa, 25216444, "departure") == GRUPPE_LUFT


def test_punkt_an_anderem_platz(faelle, ad, oa):
    assert _gruppe(faelle, ad, oa, 26626195, "departure") == GRUPPE_ANDERER


def test_bodenpunkt_ohne_nachbarn_bleibt_kandidat(faelle, ad, oa):
    """RCLM: Bodenpunkt, nächster bekannter Platz 302 km weit. Genau so ein Fall
    braucht ein Urteil — er darf NICHT wegtriagiert werden."""
    assert _gruppe(faelle, ad, oa, 28099919, "departure") == GRUPPE_KANDIDAT
