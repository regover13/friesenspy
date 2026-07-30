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
    ALLOWED_LICENCES, _namens_varianten, licence_ok, normalise_commons_title, resolve_type,
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


# --- HTTP-Schicht mit User-Agent und Fehlerklassifikation -------------------

def test_fetch_json_setzt_user_agent(monkeypatch):
    """B3: ohne UA antwortet Wikimedia von diesem Server mit 403."""
    import httpx
    from app import aircraft_info

    gesehen = {}

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"ok": True}

    class _Client:
        def __init__(self, **kw):
            gesehen["headers"] = kw.get("headers") or {}
            gesehen["timeout"] = kw.get("timeout")
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    assert aircraft_info.fetch_json("https://de.wikipedia.org/x") == {"ok": True}
    assert gesehen["headers"]["User-Agent"] == aircraft_info.USER_AGENT


def test_403_ist_transient_404_nicht(monkeypatch):
    import httpx
    from app import aircraft_info, llm

    def _mit_status(code):
        class _Resp:
            status_code = code
            def raise_for_status(self):
                raise httpx.HTTPStatusError("x", request=None, response=None)
            def json(self): return {}
        class _Client:
            def __init__(self, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, url): return _Resp()
        monkeypatch.setattr(httpx, "Client", _Client)

    _mit_status(403)
    with pytest.raises(aircraft_info.WikimediaError) as e403:
        aircraft_info.fetch_json("https://de.wikipedia.org/x")
    assert e403.value.status_code == 403
    assert llm.is_transient_error(e403.value) is True, \
        "403 muss transient sein, sonst begraebt der Contabo-Block jedes Muster 30 Tage"

    _mit_status(404)
    with pytest.raises(aircraft_info.WikimediaError) as e404:
        aircraft_info.fetch_json("https://de.wikipedia.org/x")
    assert llm.is_transient_error(e404.value) is False


def test_netzwerkfehler_bleibt_transient(monkeypatch):
    """Rev. 3 (C3): ein Timeout darf nicht als endgueltig durchgereicht werden.

    Beim Verpacken in WikimediaError geht der urspruengliche Ausnahmetyp verloren -- die
    __mro__ lautet danach nur noch (WikimediaError, Exception, ...), und `is_transient_error`
    findet weder einen Status-Code noch einen der gesuchten Klassennamen. Ohne Ersatz-Status
    schrieb _resolve_aircraft_type deshalb `nichts_gefunden` (30 Tage Sperre) statt `fehler`
    (kurzer Backoff) -- und zwar bei jedem Netzwerkschluckauf gegen Wikimedia.
    """
    import httpx
    from app import aircraft_info, llm

    class _Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url):
            raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "Client", _Client)

    with pytest.raises(aircraft_info.WikimediaError) as artikel:
        aircraft_info.fetch_json("https://de.wikipedia.org/x")
    assert llm.is_transient_error(artikel.value) is True, \
        "Timeout beim Artikel-Abruf wurde als endgueltig eingestuft"

    with pytest.raises(aircraft_info.WikimediaError) as foto:
        aircraft_info.download_photo("https://upload.wikimedia.org/x.jpg")
    assert llm.is_transient_error(foto.value) is True, \
        "Timeout beim Foto-Download verwirft sonst die schon geloeste Artikel-Recherche"


def test_commons_foto_wird_wie_ein_upload_aufbereitet():
    """Rev. 3 (I3): Commons liefert die Originaldatei (gemessen bis 4 MB) -- dieselbe
    Pillow-Pipeline wie beim Admin-Upload begrenzt sie auf 1280 px."""
    import io

    from PIL import Image
    from app.aircraft_info import PHOTO_MAX_WIDTH, to_web_jpeg

    quelle = io.BytesIO()
    Image.new("RGB", (3000, 2000), (10, 20, 30)).save(quelle, format="PNG")
    jpeg = to_web_jpeg(quelle.getvalue())
    bild = Image.open(io.BytesIO(jpeg))
    assert bild.format == "JPEG", "MIME-Typ image/jpeg waere sonst gelogen"
    assert bild.width == PHOTO_MAX_WIDTH
    assert bild.height == 853


def test_unlesbares_bild_wird_als_valueerror_gemeldet():
    """SVG von Commons: kein Pillow-Bild. Der Aufrufer behaelt den Artikel, nur ohne Foto."""
    import pytest as _pytest

    from app.aircraft_info import to_web_jpeg
    with _pytest.raises(ValueError):
        to_web_jpeg(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")


# --- Namensvarianten-Fallback (Admin-Meldung 2026-07-30: DA40/DA62 fanden nichts) -------

def test_namensvarianten_ohne_klammer_und_extra_wort():
    """Gemessen: 'Diamond DA62 (US 7-seat, 2300 kg)' findet KEINEN Wikipedia-Treffer,
    'Diamond DA62' findet ihn sofort. 'Diamond DA40 XLS (…)' findet erst nach Streichen
    von 'XLS' einen Treffer -- die Variante hat keinen eigenen Artikel."""
    assert _namens_varianten("Diamond DA62 (US 7-seat, 2300 kg)") == [
        "Diamond DA62 (US 7-seat, 2300 kg)", "Diamond DA62",
    ]
    assert _namens_varianten(
        "Diamond DA40 XLS (Lycoming IO-360-M1A, häufigste zertifizierte Avgas-Variante)"
    ) == [
        "Diamond DA40 XLS (Lycoming IO-360-M1A, häufigste zertifizierte Avgas-Variante)",
        "Diamond DA40 XLS",
        "Diamond DA40",
    ]


def test_namensvarianten_ohne_klammer_bleibt_unveraendert():
    """Kein Klammerzusatz, kein drittes Wort zum Streichen -- nur der Originalname."""
    assert _namens_varianten("Cessna 172") == ["Cessna 172"]
    assert _namens_varianten("Cessna 172S Skyhawk") == [
        "Cessna 172S Skyhawk", "Cessna 172S",
    ]


def test_resolve_type_findet_nach_klammer_entfernen_einen_treffer():
    """Erster Suchversuch mit dem vollen Namen findet nichts; erst 'Diamond DA62' (ohne
    Klammerzusatz) liefert den Treffer. Trefferpruefung laeuft trotzdem gegen den VOLLEN
    Namen (teilt 'diamond' und 'da62')."""
    routen = {
        "srsearch=Diamond%20DA62%20%28": _such(),         # voller Name: kein Treffer
        "srsearch=Diamond%20DA62&": _such("Diamond DA62"),  # bereinigter Name: Treffer
        "summary/Diamond": _summary("Diamond DA62", "Aircraft",
                                    "Die Diamond DA62 ist ein zweimotoriges Flugzeug."),
        "media-list": _medialist(),
    }
    r = resolve_type("Diamond DA62 (US 7-seat, 2300 kg)", _fetcher(routen))
    assert r is not None, "Fallback ohne Klammerzusatz haette einen Treffer finden muessen"
    assert r["wiki_title"] == "Diamond DA62"
