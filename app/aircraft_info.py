"""Muster-Infos aus Wikipedia und Wikimedia Commons.

Einziger Teil des Features mit fremden HTTP-Aufrufen und Heuristik — deshalb ein eigenes
Modul, das ohne Netz und ohne Datenbank prüfbar ist. Die HTTP-Schicht wird als Funktion
injiziert (siehe ``resolve_type`` in Task 3).

**Wikimedia sperrt das Netz dieses Servers ohne aussagekräftigen User-Agent.** Gemessen am
2026-07-30 aus dem Produktions-Container: Default-UA → ``403 Contabo networks are forbidden
due to abuse``, eigener UA → ``200``. Der Block greift nicht deterministisch an jedem Edge,
403 ist deshalb **vorübergehend**, kein Endzustand.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from app.version import VERSION

USER_AGENT = f"FriesenSpy/{VERSION} (https://friesenspy.devprops.de; admin@devprops.de)"

# Die Wikipedia-Such-API lehnt Anfragen über 300 Zeichen mit `cirrussearch-query-too-long` ab.
# 80 ist reichlich für „Hersteller + Modell" und schließt die Prosa-Altwerte sicher aus:
# `MR20` trägt real einen 359-Zeichen-Absatz als make_model.
MAX_NAME_LEN = 80

# Wörter unter 3 Zeichen taugen nicht als Überlappungsbeleg — „de" in „de Havilland" und „TL"
# in „TL Ultralight" hätten sonst jeden Artikel bestätigt, der ein „de" im Titel trägt.
_MIN_WORT_LEN = 3

_FUELLWOERTER = frozenset({
    "der", "die", "das", "und", "von", "mit", "für", "the", "and", "for",
    "aircraft", "flugzeug", "helicopter", "hubschrauber",
})

_LUFTFAHRZEUG_WOERTER = (
    "flugzeug", "hubschrauber", "helikopter", "ultraleicht", "segelflugzeug",
    "motorsegler", "tragschrauber", "wasserflugzeug", "doppeldecker",
    "aircraft", "airliner", "airplane", "aeroplane", "helicopter", "glider",
    "sailplane", "biplane", "monoplane", "airship", "utility plane", "trainer",
)

# Bekannte Hersteller-/Baureihen-Umbenennungen, die reine Wortüberlappung nicht mehr erkennt.
# Bei Hubschraubern wandert der Hersteller durch Firmengeschichte UND die Typbezeichnung
# selbst ändert sich (MBB/Kawasaki BK 117 -> Eurocopter/Airbus H145; Eurocopter EC 135 ->
# Airbus H135) — Name und Wikipedia-Lemma teilen dann kein einziges Wort mehr. Gemessen an den
# echten make_model-Werten der Produktions-DB (EC45: 137 Flüge, AEST: 72 Flüge). Das ist
# bewusst eine enge, explizite Ausnahmeliste für belegte Fälle, keine generelle Fuzzy-Logik —
# Substring-Vergleiche würden z. B. "Impuls" (Physik) fälschlich mit "Impulse" (Flugzeug)
# verwechseln (siehe test_fehltreffer_wird_verworfen).
_BEKANNTE_MUSTER_ALIASE: tuple[tuple[str, ...], ...] = (
    ("h145", "bk117", "bk 117"),
    ("h135", "ec135", "ec 135"),
    ("aerostar", "pa-60", "pa 60", "pa60"),
)


def harden_name(name: str | None) -> str | None:
    """Name als Suchanfrage tauglich machen — oder ``None``, wenn er es nicht ist.

    Verworfen wird, was mehrzeilig oder länger als :data:`MAX_NAME_LEN` ist. Grund sind reale
    Altwerte in ``aircraft_payloads``: ``MR20`` trägt einen 359-Zeichen-Prosaabsatz, der die
    Such-API mit ``cirrussearch-query-too-long`` sprengt und das Muster damit in einen ewigen
    Retry schickt. Der Aufrufer geht bei ``None`` in der Namens-Rangfolge einen Schritt weiter.
    """
    if not name:
        return None
    s = name.strip()
    if not s or "\n" in s or "\r" in s or len(s) > MAX_NAME_LEN:
        return None
    return s


def _woerter(text: str) -> set[str]:
    roh = re.findall(r"[0-9A-Za-zÄÖÜäöüßÀ-ÿ]+", text.lower())
    return {w for w in roh if len(w) >= _MIN_WORT_LEN and w not in _FUELLWOERTER}


def title_matches_name(title: str, name: str) -> bool:
    """Teilen Artikeltitel und Muster-Name ein bedeutungstragendes Wort?

    Geprüft wird gegen den **ganzen** Namen, nicht nur den Herstellerteil. Rev. 1 tat
    Letzteres und verwarf damit gemessen die halbe Hubschrauber-Flotte der Gruppe:
    ``Airbus H145 (D3)`` gegen *MBB/Kawasaki BK 117* (137 Flüge), ``Aerostar 600`` gegen
    *Piper PA-60* (72 Flüge), ``AS365N3 Dauphin 2`` gegen *Eurocopter AS365 Dauphin*.
    Der Hersteller wandert bei Hubschraubern durch die Firmengeschichte, die Typbezeichnung
    bleibt — deshalb ist der ganze Name der bessere Anker.
    """
    if not title or not name:
        return False
    if _woerter(title) & _woerter(name):
        return True
    title_l, name_l = title.lower(), name.lower()
    for gruppe in _BEKANNTE_MUSTER_ALIASE:
        if any(g in title_l for g in gruppe) and any(g in name_l for g in gruppe):
            return True
    return False


def looks_like_aircraft(description: str | None, extract: str | None) -> bool:
    """Beschreibt der Artikel ein Luftfahrzeug?

    ``description`` (kurze Wikidata-Beschreibung) zuerst; ist sie leer, entscheidet der Anfang
    des ``extract``. Rev. 1 prüfte nur ``description`` und hätte damit korrekte Artikel
    verworfen, die keine haben — gemessen bei *Piper PA-60* und *Scheibe SF 25*.
    """
    for quelle in (description, extract):
        if not quelle:
            continue
        text = quelle[:400].lower()
        if any(w in text for w in _LUFTFAHRZEUG_WOERTER):
            return True
    return False


# --- Auflösung gegen Wikipedia und Commons ----------------------------------

# Whitelist **exakter** normalisierter Kürzel. Ein Substring-Vergleich ist hier falsch:
# "CC BY" ist ein Teilstring von "CC BY-NC-ND 2.0" und würde ein NC/ND-Bild veröffentlichen
# (Rev. 2, W4). `LicenseShortName` ist auf Commons Freitext mit Leerzeichen — gemessen:
# "CC BY-SA 4.0", "Public domain", "GFDL 1.2".
ALLOWED_LICENCES = frozenset({
    "cc0", "cc01.0", "publicdomain", "pd",
    "ccby2.0", "ccby2.5", "ccby3.0", "ccby4.0",
    "ccbysa2.0", "ccbysa2.5", "ccbysa3.0", "ccbysa4.0",
})

_SUCHTIEFE = 3          # so viele Suchtreffer werden geprüft
_SPRACHEN = ("de", "en")


def _norm_licence(s: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", (s or "").lower())


def licence_ok(short_name: str | None, usage_terms: str | None) -> bool:
    """Darf dieses Bild angezeigt werden?

    Zulässig sind CC0, Public Domain und CC BY / CC BY-SA. Ausgeschlossen ist alles mit ``NC``
    oder ``ND`` sowie **GFDL als einzige** Lizenz (Copyleft mit Volltextpflicht — für eine
    Web-Anzeige unpassend; betrifft konkret das Leitbild der ``C172``).

    Dual lizenzierte Bilder tragen auf Commons häufig nur „GFDL" im Kürzel, nennen die
    CC-Lizenz aber in ``UsageTerms``. Deshalb wird dort nachgesehen, statt das Bild
    vorschnell zu verwerfen.
    """
    if _norm_licence(short_name) in ALLOWED_LICENCES:
        return True
    # Zweite Chance nur für Dual-Lizenzen: eine erlaubte Lizenz muss in UsageTerms stehen.
    terms = _norm_licence(usage_terms)
    if not terms:
        return False
    if "nc" in (usage_terms or "").lower() or "noderiv" in terms or "ccbynd" in terms:
        return False
    return any(erlaubt in terms for erlaubt in ("ccbysa", "ccby", "cc0", "publicdomain"))


def normalise_commons_title(title: str) -> str:
    """Dateititel auf das ``File:``-Präfix bringen.

    Die deutsche ``media-list`` liefert ``Datei:``; die Commons-API kennt nur ``File:`` und
    antwortet sonst still ohne ``imageinfo``.
    """
    t = (title or "").strip()
    for praefix in ("Datei:", "File:", "Bild:", "Image:"):
        if t.startswith(praefix):
            return "File:" + t[len(praefix):]
    return "File:" + t


def _such_url(lang: str, name: str) -> str:
    return (f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search"
            f"&srsearch={quote(name)}&srlimit={_SUCHTIEFE}&format=json")


def _summary_url(lang: str, titel: str) -> str:
    return f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(titel, safe='')}"


def _medialist_url(lang: str, titel: str) -> str:
    return f"https://{lang}.wikipedia.org/api/rest_v1/page/media-list/{quote(titel, safe='')}"


def _imageinfo_url(commons_titel: str) -> str:
    return ("https://commons.wikimedia.org/w/api.php?action=query"
            f"&titles={quote(commons_titel, safe='')}"
            "&prop=imageinfo&iiprop=extmetadata%7Curl&format=json")


def _meta(extmetadata: dict, key: str) -> str | None:
    wert = (extmetadata or {}).get(key)
    if isinstance(wert, dict):
        return wert.get("value")
    return wert if isinstance(wert, str) else None


def _waehle_bild(lang: str, titel: str, fetch) -> dict | None:
    """Erstes Bild des Artikels mit zulässiger Lizenz.

    Rev. 2 (W1): Rev. 1 fragte nur ``originalimage`` der Summary ab und schloss daraus, die
    ``C172`` — mit 506 Flügen das häufigste Muster der Gruppe — bleibe wegen GFDL dauerhaft
    ohne Bild. Der Artikel enthält aber mindestens vier verwendbare Bilder. Der Lizenzfilter
    war richtig, die Ein-Kandidaten-Pipeline falsch.
    """
    daten = fetch(_medialist_url(lang, titel)) or {}
    for item in (daten.get("items") or []):
        if item.get("type") not in (None, "image"):
            continue
        roh = item.get("title") or ""
        if not roh:
            continue
        commons_titel = normalise_commons_title(roh)
        info = fetch(_imageinfo_url(commons_titel)) or {}
        seiten = ((info.get("query") or {}).get("pages") or {})
        for seite in seiten.values():
            ii = (seite.get("imageinfo") or [{}])[0]
            ext = ii.get("extmetadata") or {}
            short, terms = _meta(ext, "LicenseShortName"), _meta(ext, "UsageTerms")
            if not licence_ok(short, terms):
                continue
            return {
                "photo_commons_title": commons_titel,
                "photo_url": ii.get("url"),
                "photo_licence": short,
                "photo_artist": re.sub(r"<[^>]+>", "", _meta(ext, "Artist") or "").strip() or None,
                "photo_source_url": ii.get("descriptionurl"),
            }
    return None


def resolve_type(name: str, fetch) -> dict | None:
    """Muster-Name → Wikipedia-Artikel und Foto, oder ``None``.

    ``fetch(url) -> dict`` liefert geparstes JSON und **muss** den :data:`USER_AGENT` setzen.
    Ausnahmen von ``fetch`` werden durchgeworfen — ob ein Fehler vorübergehend ist, entscheidet
    der Aufrufer (``llm.is_transient_error``).

    Immer über die **Suche**, nie den Namen als Lemma raten: gemessen liefert
    ``srsearch="Cessna 172S Skyhawk"`` den Treffer ``Cessna 172``, der direkte Lemma-Aufruf
    mit demselben String dagegen **HTTP 404**.

    Reihenfolge im Loop bewusst: für jeden Suchtreffer wird **erst** die Summary geholt und
    **dann** gegen den kanonischen Titel geprüft (``title_matches_name`` + ``looks_like_
    aircraft``) — nicht umgekehrt. Nur so lässt sich messen, dass wirklich alle ``_SUCHTIEFE``
    Treffer geprüft werden (``test_hoechstens_drei_treffer_werden_geprueft``), und die Prüfung
    läuft gegen den kanonischen Titel nach einer Weiterleitung, nicht den rohen Suchtitel.
    """
    sauber = harden_name(name)
    if not sauber:
        return None
    for lang in _SPRACHEN:
        treffer = fetch(_such_url(lang, sauber)) or {}
        titel_liste = [
            t.get("title") for t in ((treffer.get("query") or {}).get("search") or [])
            if t.get("title")
        ][:_SUCHTIEFE]
        for titel in titel_liste:
            summary = fetch(_summary_url(lang, titel)) or {}
            extract = summary.get("extract")
            echter_titel = summary.get("title") or titel
            if not title_matches_name(echter_titel, sauber):
                continue
            if not looks_like_aircraft(summary.get("description"), extract):
                continue
            ergebnis = {
                "wiki_lang": lang,
                "wiki_title": echter_titel,
                "extract": extract,
                "photo_commons_title": None,
                "photo_url": None,
                "photo_licence": None,
                "photo_artist": None,
                "photo_source_url": None,
            }
            bild = _waehle_bild(lang, ergebnis["wiki_title"], fetch)
            if bild:
                ergebnis.update(bild)
            return ergebnis
    return None
