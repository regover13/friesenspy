# -*- coding: utf-8 -*-
"""Kennzahlen der FriesenReddung in den Statistiken (Spec 2026-09-23, Abschnitt 7)."""
from __future__ import annotations

from pathlib import Path

from app.database import aggregate_reddung_kpis

INDEX = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")


def _stand(**extra):
    basis = {"je_pilot": [{"cid": 1, "zellen": 5}], "abgedeckt": 5, "kante_km": 1.0,
             "gefunden": None, "dauer_min": None}
    basis.update(extra)
    return basis


def test_leer():
    assert aggregate_reddung_kpis([]) == {"event_count": 0, "participations": 0,
                                          "gefunden_count": 0, "flaeche_km2": 0,
                                          "avg_rettung_min": None}


def test_ein_abend_ohne_fund():
    r = aggregate_reddung_kpis([_stand()])
    assert r["event_count"] == 1 and r["gefunden_count"] == 0 and r["avg_rettung_min"] is None


def test_teilnahmen_zaehlen_auch_piloten_ohne_eigene_zelle():
    """⚠ Wer nur Flaeche abflog, die ein anderer zuerst hatte, war trotzdem dabei."""
    r = aggregate_reddung_kpis([_stand(je_pilot=[{"cid": 1, "zellen": 5}, {"cid": 2, "zellen": 0}])])
    assert r["participations"] == 2


def test_flaeche_nimmt_die_kante_jedes_abends():
    # ⚠ Werte ohne halbe km²: Python rundet 12,5 auf 12 (Banker's Rounding).
    r = aggregate_reddung_kpis([_stand(abgedeckt=10, kante_km=1.0), _stand(abgedeckt=12, kante_km=0.5)])
    assert r["flaeche_km2"] == 13      # 10 · 1² + 12 · 0,5²


def test_rettungsdauer_nur_ueber_abende_mit_einlieferung():
    r = aggregate_reddung_kpis([_stand(gefunden={"cid": 1}, dauer_min=30),
                                _stand(gefunden={"cid": 1}, dauer_min=50),
                                _stand(gefunden={"cid": 1}, dauer_min=None)])
    assert r["gefunden_count"] == 3 and r["avg_rettung_min"] == 40.0


def test_ein_abend_ohne_teilnehmer_zaehlt_nicht():
    """Wie beim Kutter: leere Probe-Events verfaelschen die Anzahl nicht."""
    assert aggregate_reddung_kpis([_stand(je_pilot=[])])["event_count"] == 0


def test_die_statistik_zeigt_eine_reddung_zeile():
    stelle = INDEX.index("function renderSpecialEventStats(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "data.reddung" in rumpf and "'🚨 FriesenReddung'" in rumpf
    assert "'Ø Rettung'" in rumpf


def test_die_readme_nennt_die_kennzahlen():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    abschnitt = readme[readme.index("### 📊 Statistiken"):readme.index("### 🔍 Event-Suche")]
    assert "FriesenReddung" in abschnitt
