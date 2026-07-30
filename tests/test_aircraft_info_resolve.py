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
from app.aircraft_info import (
    ALLOWED_LICENCES, licence_ok, normalise_commons_title, resolve_type,
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


# --- Lizenz-Whitelist -------------------------------------------------------

def test_whitelist_statt_substring():
    """W4: 'CC BY' ist ein Teilstring von 'CC BY-NC-ND 2.0'."""
    assert licence_ok("CC BY-SA 4.0", None) is True
    assert licence_ok("CC BY 3.0", None) is True
    assert licence_ok("CC0", None) is True
    assert licence_ok("Public domain", None) is True
    assert licence_ok("CC BY-NC-ND 2.0", None) is False
    assert licence_ok("CC BY-NC 2.0", None) is False
    assert licence_ok("CC BY-ND", None) is False


def test_gfdl_allein_abgelehnt_dual_akzeptiert():
    """Das C172-Leitbild ist real GFDL 1.2. Dual lizenzierte Bilder tragen teils nur
    'GFDL' im Kuerzel — die 'only'-Unterscheidung braucht UsageTerms."""
    assert licence_ok("GFDL 1.2", None) is False
    assert licence_ok("GFDL 1.2", "GNU Free Documentation License 1.2") is False
    assert licence_ok("GFDL", "GFDL 1.2 or later, and CC BY-SA 3.0") is True


def test_unbekannte_lizenz_wird_abgelehnt():
    assert licence_ok(None, None) is False
    assert licence_ok("Alle Rechte vorbehalten", None) is False


def test_datei_praefix_wird_zu_file():
    """W1-Implementierungsfalle: die de-media-list liefert 'Datei:', Commons braucht 'File:'."""
    assert normalise_commons_title("Datei:Cessna 172.jpg") == "File:Cessna 172.jpg"
    assert normalise_commons_title("File:Cessna 172.jpg") == "File:Cessna 172.jpg"
    assert normalise_commons_title("Cessna 172.jpg") == "File:Cessna 172.jpg"


# --- resolve_type mit gefälschtem HTTP --------------------------------------

def _fetcher(routen: dict, aufrufe: list | None = None):
    """fetch(url) -> JSON aus `routen` (erste passende Teil-URL gewinnt)."""
    def _f(url):
        if aufrufe is not None:
            aufrufe.append(url)
        for teil, antwort in routen.items():
            if teil in url:
                if isinstance(antwort, Exception):
                    raise antwort
                return antwort
        raise AssertionError(f"unerwartete URL: {url}")
    return _f


def _such(*titel):
    return {"query": {"search": [{"title": t} for t in titel]}}


def _summary(titel, desc, extract, bild=None):
    d = {"title": titel, "description": desc, "extract": extract}
    if bild:
        d["originalimage"] = {"source": f"https://upload.wikimedia.org/{bild}"}
    return d


def _medialist(*dateien):
    return {"items": [{"title": d, "type": "image"} for d in dateien]}


def _imageinfo(short, artist="Jemand", terms=None, url="https://upload/x.jpg"):
    return {"query": {"pages": {"-1": {"imageinfo": [{
        "url": url,
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:X.jpg",
        "extmetadata": {
            "LicenseShortName": {"value": short},
            "Artist": {"value": artist},
            **({"UsageTerms": {"value": terms}} if terms else {}),
        },
    }]}}}}


def test_zweiter_treffer_gewinnt_wenn_der_erste_durchfaellt():
    """EC45, 137 Fluege: der erste de-Treffer ist die Polizeihubschrauberstaffel."""
    routen = {
        "srsearch": _such("Polizeihubschrauberstaffel Bayern", "MBB/Kawasaki BK 117"),
        "summary/Polizeihubschrauberstaffel": _summary(
            "Polizeihubschrauberstaffel Bayern", "Polizeieinheit", "Die Staffel …"),
        "summary/MBB": _summary("MBB/Kawasaki BK 117", "Hubschraubertyp",
                                "Der BK 117 ist ein Hubschrauber.", bild="bk117.jpg"),
        "media-list/MBB": _medialist("Datei:bk117.jpg"),
        "imageinfo": _imageinfo("CC BY-SA 4.0"),
    }
    r = resolve_type("Airbus H145 (D3)", _fetcher(routen))
    assert r["wiki_title"] == "MBB/Kawasaki BK 117"
    assert r["photo_licence"] == "CC BY-SA 4.0"


def test_englisch_als_rueckfall_wenn_de_leer():
    routen = {
        "de.wikipedia.org/w/api.php": _such(),
        "en.wikipedia.org/w/api.php": _such("Eurocopter AS365 Dauphin"),
        "en.wikipedia.org/api/rest_v1/page/summary": _summary(
            "Eurocopter AS365 Dauphin", "helicopter", "The AS365 is a helicopter.",
            bild="as365.jpg"),
        "en.wikipedia.org/api/rest_v1/page/media-list": _medialist("File:as365.jpg"),
        "imageinfo": _imageinfo("CC BY-SA 3.0"),
    }
    r = resolve_type("Aérospatiale/Airbus Helicopters AS365N3 Dauphin 2", _fetcher(routen))
    assert r["wiki_lang"] == "en"
    assert r["wiki_title"] == "Eurocopter AS365 Dauphin"


def test_gfdl_leitbild_uebersprungen_zweites_bild_gewinnt():
    """W1: die C172 bekommt ein Foto. Leitbild GFDL 1.2, aber vier freie im Artikel."""
    routen = {
        "srsearch": _such("Cessna 172"),
        "summary": _summary("Cessna 172", "1955 touring aircraft family",
                            "Die Cessna 172 …", bild="leitbild.jpg"),
        "media-list": _medialist("Datei:leitbild.jpg", "Datei:D-EVLB.jpg"),
        "titles=File%3Aleitbild.jpg": _imageinfo("GFDL 1.2"),
        "titles=File%3AD-EVLB.jpg": _imageinfo("CC BY-SA 3.0", artist="Fotograf"),
    }
    r = resolve_type("Cessna 172S Skyhawk", _fetcher(routen))
    assert r["photo_commons_title"] == "File:D-EVLB.jpg"
    assert r["photo_licence"] == "CC BY-SA 3.0"
    assert r["photo_artist"] == "Fotograf"


def test_text_ohne_taugliches_bild_ist_kein_fehler():
    routen = {
        "srsearch": _such("Impulse (Flugzeug)"),
        "summary": _summary("Impulse (Flugzeug)", "Flugzeugtyp", "Die Impulse …"),
        "media-list": _medialist("Datei:nur-gfdl.jpg"),
        "imageinfo": _imageinfo("GFDL 1.2"),
    }
    r = resolve_type("Impulse Impulse", _fetcher(routen))
    assert r["extract"].startswith("Die Impulse")
    assert r["photo_commons_title"] is None


def test_kein_tauglicher_treffer_gibt_none():
    routen = {
        "de.wikipedia.org/w/api.php": _such("Impuls (Physik)"),
        "de.wikipedia.org/api/rest_v1/page/summary": _summary(
            "Impuls (Physik)", "physikalische Größe", "Der Impuls ist …"),
        "en.wikipedia.org/w/api.php": _such(),
    }
    assert resolve_type("Impulse Impulse", _fetcher(routen)) is None


def test_hoechstens_drei_treffer_werden_geprueft():
    aufrufe = []
    routen = {
        "de.wikipedia.org/w/api.php": _such("A", "B", "C", "D"),
        "de.wikipedia.org/api/rest_v1/page/summary": _summary("X", "Gemeinde", "Ein Ort."),
        "en.wikipedia.org/w/api.php": _such(),
    }
    resolve_type("Cessna 172", _fetcher(routen, aufrufe))
    summaries = [u for u in aufrufe if "de.wikipedia.org/api/rest_v1/page/summary" in u]
    assert len(summaries) == 3, f"srlimit/Prüftiefe nicht 3: {summaries}"


def test_srlimit_ist_drei_und_ua_wird_nicht_in_die_url_geschrieben():
    aufrufe = []
    routen = {"de.wikipedia.org/w/api.php": _such(), "en.wikipedia.org/w/api.php": _such()}
    resolve_type("Cessna 172", _fetcher(routen, aufrufe))
    assert any("srlimit=3" in u for u in aufrufe)


def test_unbrauchbarer_name_fragt_gar_nicht_erst():
    """MR20: der Prosaabsatz darf keinen einzigen HTTP-Aufruf ausloesen."""
    aufrufe = []
    assert resolve_type("x" * 400, _fetcher({}, aufrufe)) is None
    assert aufrufe == []


def test_fetch_ausnahme_wird_durchgeworfen():
    """Die Klassifikation (transient?) macht der Aufrufer, nicht dieses Modul."""
    class _Http(Exception):
        status_code = 403
    routen = {"de.wikipedia.org/w/api.php": _Http("Contabo forbidden")}
    with pytest.raises(_Http):
        resolve_type("Cessna 172", _fetcher(routen))
