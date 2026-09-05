"""Statik-Test der Events-Liste in index.html (#19).

Die Liste stellt sich im Browser zusammen: Kalendertermine aus ``/api/calendar/events`` plus die
Event-Objekte aus ``/api/bummel/races`` und ``/api/transport/events``. Seit #19 liefert der
Server einen Termin nicht mehr mit, sobald ein Objekt an ihm hängt — die Objektliste darf
deshalb NICHT mehr auf ``source === 'manual'`` filtern, sonst verschwindet ein Kalender-Bummel
komplett. Geprüft wird am Quelltext, weil es für diesen Teil keine JS-Laufzeit im Test gibt.
"""
from __future__ import annotations

from pathlib import Path

INDEX = (Path(__file__).resolve().parent.parent / "app" / "static" / "index.html").read_text(
    encoding="utf-8")


def test_objektliste_filtert_nicht_mehr_nach_source():
    assert "filter(r => r.source === 'manual')" not in INDEX
    assert "filter(k => k.source === 'manual')" not in INDEX


def test_manuell_hinweis_haengt_an_source():
    """Der Zusatz „(manuell)" in der Liste muss an der Herkunft hängen, nicht daran, über
    welchen Weg die Zeile hereinkam — sonst trüge künftig jedes Objekt das Etikett."""
    assert "_manual: r.source === 'manual'" in INDEX
    assert "_manual: k.source === 'manual'" in INDEX


def test_beide_objektarten_landen_in_derselben_liste():
    assert "objectEvents = objectEvents.concat(" in INDEX
    assert "const combined = [...calEvents, ...objectEvents]" in INDEX
