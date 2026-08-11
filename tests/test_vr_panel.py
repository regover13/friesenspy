"""Tests für den VR-Panel-Modus (/panel) — Web-Vorbereitung für ein separat gebautes
MSFS-2024-EFB-Panel (s. docs/superpowers/specs/2026-08-11-vr-panel-modus-design.md).

Für Vanilla-JS/CSS gibt es in diesem Projekt keinen Testläufer -- die Skalierungs-Tests
greifen deshalb wie tests/test_aircraft_ui_static.py auf den Quelltext zu.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import app.main as main

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_panel_liefert_dieselbe_datei_wie_index():
    """/panel MUSS exakt dieselbe Response wie / liefern -- keine zweite HTML-Datei, keine
    Duplikation (s. Global Constraints)."""
    index_resp = asyncio.run(main.index())
    panel_resp = asyncio.run(main.panel())
    assert panel_resp.path == index_resp.path
    assert dict(panel_resp.headers) == dict(index_resp.headers)


def test_vr_panel_klasse_wird_bei_panel_pfad_und_query_gesetzt():
    """Beide Aktivierungswege müssen im Quelltext stehen -- /panel (Task 1) UND ?vr=1
    (Design-Entscheidung: gleichwertiger Trigger auch ohne Pfadwechsel)."""
    assert "location.pathname === '/panel'" in INDEX
    assert "qs.get('vr') === '1'" in INDEX
    assert "classList.add('vr-panel')" in INDEX


def test_vr_panel_css_skaliert_alles_gemeinsam():
    """zoom (nicht nur font-size!) -- Innenabstände/Buttons sind im Rest der Seite
    überwiegend feste px-Werte, s. Design-Doku 'Warum eine reine Schriftgrößen-Anpassung
    nicht reicht'."""
    assert re.search(r"html\.vr-panel\s*\{[^}]*zoom:\s*1\.35", INDEX)
    assert re.search(r"html\.vr-panel body\s*\{[^}]*font-weight:\s*400", INDEX)
