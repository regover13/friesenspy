"""Triage-Tests: sechs echte Fälle aus dem Export vom 2026-07-15, einer je Gruppe, plus
Regressionstests aus dem finalen Code-Review (ETUO-Basiswahl, mehrdeutige statsim_id,
SKILL.md-Zahlenabgleich).

Jeder Test sichert eine Regel ab, die beim Entwurf oder beim Review real falsch war. Siehe
docs/superpowers/specs/2026-07-15-track-diagnose-design.md
"""
import json
from pathlib import Path

import pytest

from app.database import _BUMMEL_AIRPORT_RADIUS_KM
from app.gps_legs import _GPS_FLYING_GS_KT, _GPS_GROUND_AGL_FT, _GPS_SPAWN_MAX_AGL_FT
from scripts.nearby_airports import airportsdata_refs, load_ourairports
from scripts.triage_gaps import (
    Ende,
    GRUPPE_ANDERER,
    GRUPPE_DUENN,
    GRUPPE_KANDIDAT,
    GRUPPE_LUFT,
    GRUPPE_MEHRDEUTIG,
    GRUPPE_ZZZZ,
    enden_aus_export,
    triagiere,
)

FIXTURE = Path(__file__).parent / "fixtures" / "gaps_mini.json"
OA_FIXTURE = Path(__file__).parent / "fixtures" / "ourairports_mini.csv"
SKILL_MD = Path(__file__).parent.parent / ".claude" / "skills" / "track-diagnose" / "SKILL.md"


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
    # 21 der 163 Fälle vermissen beide Enden; eines kann trivial sein, das andere nicht.
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


def test_bodenpunkt_am_falschen_platz_wird_nicht_als_luft_wegtriagiert(ad, oa):
    """ETUO (Track 23066993): Flugzeug steht mit gs 0 in Bad Gandersheim (EDVA, 791 ft),
    der Flugplan sagt Gütersloh (ETUO, 236 ft, 118 km weg). Rechnet man AGL gegen den
    Soll-Platz, ergibt das 543 ft Scheinhöhe und der Fall landet in der Trivialgruppe E —
    ein echter Kandidat wäre still verschwunden. Die Elevation muss vom Platz AM PUNKT
    kommen, wie im Detektor (app/gps_legs.py:183)."""
    ende = Ende(statsim_id=23066993, callsign="FRS131", seite="departure", soll="ETUO",
                punkt={"lat": 51.85449, "lon": 10.02288, "alt": 779, "gs": 0}, punkte=100)
    assert triagiere(ende, ad, oa).gruppe == GRUPPE_ANDERER


def test_mehrere_legs_teilen_sich_eine_statsim_id_werden_nicht_gemessen(ad, oa):
    """Eine Session kann mehrere Legs erzeugen (detect_gps_legs teilt an Zeitlücken > 30 min,
    app/gps_legs.py:53), und alle Legs erben dieselbe statsim_id. Der Export liefert dann zwei
    Fälle mit identischer ID — misst man sie trotzdem, wird das zweite Leg mit dem Randpunkt
    des ersten gemessen (Fehlrichtung, die teuer sein kann). Beide betroffenen Enden müssen
    als Mehrdeutig aussortiert werden, VOR jeder anderen Prüfung."""
    faelle = [
        {"statsim_id": 99000111, "callsign": "FRS200", "missing": "departure",
         "plan_departure": "EDDH", "plan_arrival": "EDDM", "punkte": 50,
         "first": {"lat": 53.5, "lon": 10.0, "alt": 100, "gs": 0},
         "last": {"lat": 53.5, "lon": 10.0, "alt": 100, "gs": 0}},
        {"statsim_id": 99000111, "callsign": "FRS200", "missing": "arrival",
         "plan_departure": "EDDM", "plan_arrival": "EDDH", "punkte": 50,
         "first": {"lat": 48.3, "lon": 11.8, "alt": 1480, "gs": 0},
         "last": {"lat": 48.3, "lon": 11.8, "alt": 1480, "gs": 0}},
    ]
    enden = enden_aus_export(faelle)
    assert len(enden) == 2
    for ende in enden:
        assert ende.mehrdeutig is True
        assert triagiere(ende, ad, oa).gruppe == GRUPPE_MEHRDEUTIG


def test_skill_md_zahlen_stimmen_mit_den_detektor_konstanten():
    """Die SKILL.md schreibt die Schwellen im Fließtext aus. Ändert jemand den Detektor,
    muss die Anleitung mitgezogen werden — sonst analysiert der nächste Leser nach
    veralteten Zahlen. Genau dieser Test macht den Schwellen-Import wirksam; die
    übrigen Assertions importieren beide Seiten und bewegen sich mit."""
    inhalt = SKILL_MD.read_text(encoding="utf-8")
    assert (
        "(%d km Radius, %d ft Spawn, %d ft Boden)"
        % (int(_BUMMEL_AIRPORT_RADIUS_KM), _GPS_SPAWN_MAX_AGL_FT, _GPS_GROUND_AGL_FT)
    ) in inhalt
    assert (
        "in_der_luft = (AGL > %d ft)  ODER  (groundspeed >= %d kt)"
        % (_GPS_GROUND_AGL_FT, _GPS_FLYING_GS_KT)
    ) in inhalt
