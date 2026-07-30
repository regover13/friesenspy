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
