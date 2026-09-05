"""Statik-Tests der Admin-Oberfläche für #19 (Verknüpfung + Schutzmarken).

Für admin.html gibt es keine JS-Laufzeit im Test; geprüft wird deshalb am Quelltext — und zwar
an den IDs und Eigenschaftsnamen, die der Code wirklich benutzt, nicht an Kommentartexten.
"""
from __future__ import annotations

import re
from pathlib import Path

ADMIN = (Path(__file__).resolve().parent.parent / "app" / "static" / "admin.html").read_text(
    encoding="utf-8")
SKRIPT = "\n".join(re.findall(r"<script>(.*?)</script>", ADMIN, re.S))


def test_beide_formulare_haben_ein_terminfeld():
    assert 'id="nr-caluid"' in ADMIN          # Bummel anlegen
    assert 'id="ke-caluid"' in ADMIN          # Kutter anlegen/bearbeiten
    assert "edit-caluid-" in SKRIPT           # Bummel bearbeiten (gerendert)


def test_bearbeiten_sendet_auch_den_leeren_wert():
    """Die leere Auswahl LÖST die Verknüpfung — sie darf nicht wegoptimiert werden."""
    assert "body.calendar_uid = caluid.value || null" in SKRIPT
    assert "body.calendar_uid = keUid || null" in SKRIPT


def test_anlegen_sendet_den_gewaehlten_termin():
    assert "body.calendar_uid = nrUid" in SKRIPT
    assert "else if (keUid) body.calendar_uid = keUid" in SKRIPT


def test_marken_je_feld_fuer_beide_eventarten():
    for feld in ("name", "route", "dtstart", "dtend"):
        assert f"feldMarke(r, '{feld}')" in SKRIPT
    assert "ke-marke-" in ADMIN
    # destination steht bewusst nicht dabei — es kommt nie aus dem Kalender.
    assert "['name', 'dtstart', 'dtend'].forEach" in SKRIPT


def test_zurueckholen_ruft_den_kalenderstand_endpunkt():
    assert "/kalenderstand/" in SKRIPT
    assert 'data-action="kalenderstand"' in SKRIPT
    assert 'data-action="ke-kalenderstand"' in SKRIPT


def test_belegte_termine_werden_ausgegraut_statt_abgewiesen():
    """Sonst läuft der Bediener in den 409, den er nicht kommen sieht."""
    assert SKRIPT.count("t.claimed_by && t.uid !== ") == 3   # 3 Selects, gleiche Regel
    assert SKRIPT.count("disabled") >= 3
