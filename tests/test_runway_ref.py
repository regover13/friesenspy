"""Bahnschwellen als Referenz fuer die Flugplatzkarten-Passung.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md, Abschnitt 5.1
"""
from __future__ import annotations

import math

import pytest

from app import runway_ref

# Die ECHTEN EDDL-Zeilen aus runways.csv (Stand 30.08.2026), dazu eine geschlossene und
# eine koordinatenlose Zeile zum Pruefen der Filter. Selbst getippte Koordinaten taugen
# nicht: Auf vier Nachkommastellen gerundet ergaben sie 3223 m statt 3000 und einen um
# 3 Grad falschen Kurs -- der Test haette dann eine Geometrie geprueft, die es nicht gibt.
CSV = """id,airport_ref,airport_ident,length_ft,width_ft,surface,lighted,closed,le_ident,le_latitude_deg,le_longitude_deg,le_elevation_ft,le_heading_degT,le_displaced_threshold_ft,he_ident,he_latitude_deg,he_longitude_deg,he_elevation_ft,he_heading_degT,he_displaced_threshold_ft
236212,2217,EDDL,8858,148,CON,1,0,05L,51.28369903564453,6.748720169067383,116,53,984,23R,51.29840087890625,6.7796502113342285,124,233,984
236211,2217,EDDL,9842,148,CON,1,0,05R,51.279598236083984,6.751989841461182,121,53,984,23L,51.2958984375,6.786220073699951,138,233,984
3,1,EDDL,3000,100,ASP,1,1,09,51.2800,6.7600,147,90,0,27,51.2800,6.7700,147,270,0
4,1,EDXX,3000,100,ASP,1,0,09,,,,,,27,,,,,
"""


@pytest.fixture()
def csv_datei(tmp_path):
    p = tmp_path / "runways.csv"
    p.write_text(CSV, encoding="utf-8")
    return p


def test_zwei_bahnen_mit_laenge_und_kurs(csv_datei):
    b = {x.name: x for x in runway_ref.bahnen("EDDL", csv_datei)}
    # Nach Namen, nicht nach Position: Die Reihenfolge in runways.csv ist nichts, worauf
    # sich jemand verlassen sollte -- sie hat schon zwischen zwei Ausgaben gewechselt.
    assert set(b) == {"05R/23L", "05L/23R"}
    assert b["05R/23L"].laenge == pytest.approx(2997, abs=30)   # laut CSV 9843 ft
    assert b["05L/23R"].laenge == pytest.approx(2700, abs=30)   # laut CSV 8858 ft
    assert b["05R/23L"].kurs == pytest.approx(52.8, abs=0.5)    # Karte sagt 053 Grad


def test_geschlossene_bahn_faellt_weg(csv_datei):
    assert all(x.name != "09/27" for x in runway_ref.bahnen("EDDL", csv_datei))


def test_bahn_ohne_schwellenkoordinaten_faellt_weg(csv_datei):
    """Ohne beide Schwellen ist die Zeile als Passreferenz wertlos."""
    assert runway_ref.bahnen("EDXX", csv_datei) == []


def test_unbekannter_platz_gibt_leere_liste(csv_datei):
    assert runway_ref.bahnen("EDZZ", csv_datei) == []


def test_meridiangrad_ist_nicht_der_aequatorwert():
    """Der Prototyp rechnete mit 110540 -- dem Aequatorwert.

    Bei 47,5 bis 55 Grad Nord betraegt der Meridiangrad 111 181 bis 111 324 m. Der Fehler
    von 0,58 bis 0,70 Prozent erzeugt zusammen mit dem Laengengrad-Fehler eine Anisotropie,
    die eine Aehnlichkeitstransformation nicht absorbieren kann -- bis zu 5 m auf einem
    grossflaechigen Platz, ein Drittel der 15-m-Schranke.
    """
    for lat, soll in ((47.5, 111181), (51.3, 111254), (55.0, 111324)):
        _, breite = runway_ref.meter_je_grad(lat)
        assert breite == pytest.approx(soll, abs=3)
        assert abs(breite - 110540) > 600


def test_laengengrad_schrumpft_mit_der_breite():
    l50, _ = runway_ref.meter_je_grad(50.0)
    l55, _ = runway_ref.meter_je_grad(55.0)
    assert l55 < l50
    assert l50 == pytest.approx(111320 * math.cos(math.radians(50.0)), rel=0.002)


def test_abstand_ist_symmetrisch_und_richtig_orientiert():
    a, b = (51.28, 6.75), (51.29, 6.77)
    ost, nord = runway_ref.meter(a, b)
    assert ost > 0 and nord > 0                      # b liegt nordoestlich von a
    ost2, nord2 = runway_ref.meter(b, a)
    assert ost2 == pytest.approx(-ost) and nord2 == pytest.approx(-nord)


def test_netzfehler_entwertet_die_vorhandene_datei_nicht(tmp_path):
    """Dieselbe Regel wie beim Blattabruf: Ein Netzfehler entwertet keinen Bestand."""
    ziel = tmp_path / "runways.csv"
    ziel.write_text(CSV, encoding="utf-8")
    import os
    import time as _t
    os.utime(ziel, (0, 0))                           # kuenstlich veraltet

    def kaputt(url):
        raise RuntimeError("Netz weg")

    assert runway_ref.datei_holen(ziel, kaputt) == ziel
    assert ziel.read_text(encoding="utf-8") == CSV


def test_ohne_datei_und_ohne_netz_wird_der_fehler_gemeldet(tmp_path):
    """Stillschweigend eine leere Referenz zu liefern waere schlimmer: Die Passung liefe
    dann gegen null Bahnen und meldete nur "keine verwertbare Zuordnung"."""
    def kaputt(url):
        raise RuntimeError("Netz weg")

    with pytest.raises(RuntimeError):
        runway_ref.datei_holen(tmp_path / "fehlt.csv", kaputt)


def test_frische_datei_wird_nicht_neu_geholt(tmp_path):
    ziel = tmp_path / "runways.csv"
    ziel.write_text(CSV, encoding="utf-8")
    gerufen = []

    def zaehl(url):
        gerufen.append(url)
        return "x"

    runway_ref.datei_holen(ziel, zaehl)
    assert gerufen == []
