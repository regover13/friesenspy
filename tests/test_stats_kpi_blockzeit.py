"""Test für die neue KPI-Karte "Blockzeit" im Statistik-Tab (renderStatsSummary).

Für Vanilla-JS gibt es in diesem Projekt keinen Testläufer -- dieser Test greift deshalb
wie tests/test_aircraft_ui_static.py auf den Quelltext zu.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_blockzeit_kpi_karte_steht_neben_flugstunden():
    """Neue KPI-Karte "Blockzeit", direkt nach der bestehenden "Flugstunden"-Karte, aus
    totalBlockMin (Summe von total_block_min über alle Piloten) berechnet."""
    summary_fn = re.search(
        r"function renderStatsSummary\(stats, days\) \{.*?\n\}", INDEX, re.S,
    )
    assert summary_fn, "renderStatsSummary nicht gefunden"
    body = summary_fn.group(0)

    assert re.search(
        r"stats\.reduce\(\(s, p\) => s \+ \(p\.total_block_min \|\| 0\), 0\)", body,
    ), "totalBlockMin wird nicht aus total_block_min aggregiert"

    flugstunden_idx = body.index('<span class="stats-kpi-label">Flugstunden</span>')
    blockzeit_idx = body.index('<span class="stats-kpi-label">Blockzeit</span>')
    assert blockzeit_idx > flugstunden_idx, \
        "Blockzeit-Karte muss nach der Flugstunden-Karte stehen"
    # Zwischen den beiden Karten darf keine dritte KPI-Karte liegen -- "neben Flugstunden".
    between = body[flugstunden_idx:blockzeit_idx]
    assert between.count("stats-kpi-card") <= 1
