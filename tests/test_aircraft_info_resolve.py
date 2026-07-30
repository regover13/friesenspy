"""Namenshaertung und Trefferpruefung — mit den REAL gemessenen Faellen als Fixtures.

Rev.-2-Befund B2: die erste Fassung prueefte die Wortueberlappung nur gegen den Herstellerteil
und nur gegen den ERSTEN Suchtreffer. Gegen die echten make_model-Werte der Produktions-DB
gemessen, verwarf sie die halbe Hubschrauber-Flotte der Gruppe. Diese Fixtures sind die
Messwerte, keine Erfindungen.
"""
from __future__ import annotations

import pytest

from app.aircraft_info import (
    MAX_NAME_LEN,
    USER_AGENT,
    harden_name,
    looks_like_aircraft,
    title_matches_name,
)


# --- Namenshaertung ---------------------------------------------------------

def test_normaler_name_bleibt():
    assert harden_name("Cessna 172S Skyhawk") == "Cessna 172S Skyhawk"


def test_prosa_absatz_wird_verworfen():
    """MR20 traegt real einen 359-Zeichen-Absatz; er sprengt die Such-API
    (cirrussearch-query-too-long, Limit 300)."""
    prosa = "Die Mooney M20TN Acclaim ist ein einmotoriges " + ("x" * 360)
    assert harden_name(prosa) is None
    assert len(prosa) > MAX_NAME_LEN


def test_mehrzeiliges_wird_verworfen():
    assert harden_name("Cessna 172\nmit Zusatztext") is None


def test_leeres_und_none():
    assert harden_name(None) is None
    assert harden_name("   ") is None


def test_grenzfall_genau_max_len_bleibt():
    name = "C" * MAX_NAME_LEN
    assert harden_name(name) == name
    assert harden_name("C" * (MAX_NAME_LEN + 1)) is None


# --- Trefferpruefung: Wortueberlappung gegen den GANZEN Namen ---------------

@pytest.mark.parametrize("name,titel", [
    # Gemessene Faelle, die Rev. 1 verworfen haette:
    ("Airbus H145 (D3)", "MBB/Kawasaki BK 117"),          # EC45, 137 Fluege
    ("Aerostar 600", "Piper PA-60"),                       # AEST, 72 Fluege
    ("Aérospatiale/Airbus Helicopters AS365N3 Dauphin 2", "Eurocopter AS365 Dauphin"),
    ("Airbus H135", "Eurocopter EC 135"),
    # Unstrittige Faelle:
    ("Cessna 172S Skyhawk", "Cessna 172"),
    ("PZL-104 Wilga 35A", "PZL-104 Wilga"),
])
def test_treffer_wird_akzeptiert(name, titel):
    assert title_matches_name(titel, name) is True, f"{titel!r} zu {name!r} verworfen"


@pytest.mark.parametrize("name,titel", [
    ("Airbus H145 (D3)", "Polizeihubschrauberstaffel Bayern"),   # 1. de-Treffer, falsch
    ("Cessna 172S Skyhawk", "Continental Aerospace Technologies GmbH"),
    ("Impulse Impulse", "Impuls (Physik)"),
])
def test_fehltreffer_wird_verworfen(name, titel):
    assert title_matches_name(titel, name) is False, f"{titel!r} zu {name!r} akzeptiert"


def test_kurze_woerter_zaehlen_nicht_als_ueberlappung():
    """'de' in 'de Havilland' und 'TL' in 'TL Ultralight' sind < 3 Zeichen —
    daran scheiterte jede Erste-Wort-Heuristik."""
    assert title_matches_name("de Gaulle", "de Havilland Canada DHC-2 Beaver") is False
    assert title_matches_name("de Havilland Canada DHC-2", "de Havilland Canada DHC-2 Beaver") is True


# --- Luftfahrzeug-Erkennung -------------------------------------------------

def test_description_mit_stichwort():
    assert looks_like_aircraft("1955 touring aircraft family", None) is True
    assert looks_like_aircraft("Flugzeugtyp", None) is True
    assert looks_like_aircraft("Hubschraubertyp", None) is True


def test_description_leer_faellt_auf_extract_zurueck():
    """Gemessen: 'Piper PA-60' und 'Scheibe SF 25' haben KEINE Wikidata-Beschreibung.
    Rev. 1 haette sie allein deswegen verworfen."""
    assert looks_like_aircraft(None, "Die Piper PA-60 Aerostar ist ein zweimotoriges Flugzeug.") is True
    assert looks_like_aircraft("", "The Scheibe SF 25 is a German glider.") is True


def test_beides_leer_ist_kein_luftfahrzeug():
    assert looks_like_aircraft(None, None) is False


def test_thema_ohne_luftfahrzeug_wird_verworfen():
    assert looks_like_aircraft("International Labour Organization Convention", None) is False
    assert looks_like_aircraft("German municipality", "Eine Gemeinde im Landkreis.") is False


# --- User-Agent -------------------------------------------------------------

def test_user_agent_traegt_kontakt_und_version():
    """B3: ohne aussagekraeftigen UA antwortet Wikimedia von diesem Server mit 403
    ('Contabo networks are forbidden due to abuse'). Gemessen 2026-07-30 im Container."""
    assert "FriesenSpy/" in USER_AGENT
    assert "friesenspy.devprops.de" in USER_AGENT
    assert "@" in USER_AGENT, "Kontakt fehlt — Wikimedia-Nutzungsregeln verlangen ihn"
    assert "python" not in USER_AGENT.lower()
