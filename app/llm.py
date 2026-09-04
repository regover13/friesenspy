"""Claude-API-Anbindung für FriesenSpy (aktuell: Zuladungs-Vorschlag pro Flugzeugtyp).

Der Vorschlag **recherchiert per Web-Search** (serverseitiges Anthropic-Tool) die realen,
dokumentierten Herstellerangaben und liefert sie als Structured Output. Modell: Haiku 4.5
(Spec-Lookup); die KI-Sprüche laufen auf Sonnet 5.

Bewusst mit Silent-Fail: der Vorschlag ist Komfort im Admin, kein kritischer Pfad. Ohne
``ANTHROPIC_API_KEY`` (mit TSBot geteilt) oder ohne ``anthropic``-Paket → ``None``; die
Zuladungs-Tabelle bleibt manuell pflegbar.

Phase 2 (geplant): lustige Flug-Kommentare über denselben Client.
"""
from __future__ import annotations

import json
import logging
import math

from app.aircraft_info import harden_name

logger = logging.getLogger(__name__)

# Spec-Lookup auf Haiku 4.5 (Nutzer-Entscheidung 2026-07-02: ~4 ct statt ~7 ct pro Recherche;
# Live-Probe: 18,5 s, korrektes Wilga-Ergebnis). Achtung: Haiku 4.5 lehnt den effort-Parameter
# mit 400 ab — output_config nur mit format befüllen. Die KI-Sprüche bleiben auf Sonnet 5
# (kontextreicher Humor, siehe flight_quip/event_summary).
_SUGGEST_MODEL = "claude-haiku-4-5"
# Standard-Pilotengewicht (kg) — zählt nicht als Fracht (Wert = database._CREW_KG_DEFAULT).
_CREW_KG = 85.0
# Serverseitiges Web-Search-Tool, BEWUSST die Basis-Variante 20250305: das neuere
# web_search_20260209 (Dynamic Filtering) erlaubt dem Modell code_execution-Runden über den
# Suchergebnissen — Live-Messung 2026-07-02: EIN PZ04-Request drehte >9 min in Code-Runden
# à 30–95 s und kam nie zurück; max_uses deckelt nur Suchen, nicht diese Code-Runden.
# Basis-Tool, gleicher Prompt: 16 s, 1 Suche, ~0,07 $ — und korrektes Ergebnis.
_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}


class TransientResearchError(Exception):
    """Die Recherche scheiterte an einem vorübergehenden Zustand, nicht am Muster.

    Auslöser: API überladen (529), Rate-Limit (429), Timeout, Verbindungsabbruch, 5xx.
    Der Aufrufer MUSS das von "keine Daten gefunden" (``None``) unterscheiden und es später
    erneut versuchen — sonst passiert genau der AP32-Fall vom 2026-07-30: ein einzelnes
    ``overloaded_error`` hat das Muster zwei Monate aus der Tabelle gehalten.
    """


# 408 Request Timeout, 429 Rate Limit, 529 Overloaded (Anthropic) + alle 5xx gelten als
# vorübergehend. Alles andere im 4xx-Bereich ist endgültig: erneutes Fragen ändert nichts.
#
# 403 gehört ausdrücklich dazu — nicht wegen Anthropic, sondern wegen Wikimedia: das
# Contabo-Netz dieses Servers ist dort geblockt, und der Block greift NICHT deterministisch
# (gemessen 2026-07-30 im Container: derselbe User-Agent einmal 403, Minuten später 200). Als
# endgültig gewertet würde er jedes Muster 30 Tage als „nichts gefunden" begraben. Der
# Klassifikator wird von Plan B für genau diesen Fall mitbenutzt.
_TRANSIENT_STATUS = frozenset({403, 408, 429, 529})


def is_transient_error(exc: BaseException) -> bool:
    """True, wenn ``exc`` ein vorübergehender Fehler ist (erneut versuchen lohnt).

    Arbeitet bewusst ohne Import von ``anthropic``: geprüft wird ein vorhandenes
    ``status_code``-Attribut sowie die Namen der anthropic-Verbindungs-/Timeout-Klassen.
    Damit ist der Klassifikator auch für HTTP-Fehler anderer Quellen brauchbar
    (Wikimedia: 403 durch den Contabo-Netzblock ist ausdrücklich vorübergehend).
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status >= 500 or status in _TRANSIENT_STATUS
    # Verbindungs- und Timeout-Fehler tragen keinen Status-Code. endswith() statt exaktem
    # Namensvergleich, damit das auch fuer private Test-Doubles greift (siehe
    # tests/test_llm_transient.py: `_APITimeoutError` statt `APITimeoutError`) und nicht nur
    # fuer die echten anthropic-Klassennamen.
    return any(
        name.endswith(("APIConnectionError", "APITimeoutError", "TimeoutError", "ConnectionError"))
        for name in (c.__name__ for c in type(exc).__mro__)
    )


_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "make_model": {"type": "string"},
        "mtow_kg": {"type": "number"},
        "empty_kg": {"type": "number"},
        "fuel_full_kg": {"type": "number"},
    },
    "required": ["make_model", "mtow_kg", "empty_kg", "fuel_full_kg"],
    "additionalProperties": False,
}

# Kleine kuratierte Umschreibung gängiger ICAO-Typcodes → Klartext, damit der Prompt eindeutig
# ist. Ohne Hinweis muss das Modell den Code erst per Web-Suche identifizieren — bei obskuren
# Codes (Live-Befund: 'AS65') dauert das lange und endet öfter ohne Ergebnis.
_TYPE_HINTS = {
    "C172": "Cessna 172", "C182": "Cessna 182", "C208": "Cessna 208 Caravan",
    "C152": "Cessna 152",
    "PA28": "Piper PA-28", "PA24": "Piper PA-24 Comanche", "PA34": "Piper PA-34 Seneca",
    "PA18": "Piper PA-18 Super Cub",
    "BE58": "Beechcraft Baron 58", "BE36": "Beechcraft Bonanza 36", "PC12": "Pilatus PC-12",
    "DA40": "Diamond DA40", "DA42": "Diamond DA42", "DA62": "Diamond DA62",
    "TBM9": "Daher TBM 900", "SR22": "Cirrus SR22", "SR20": "Cirrus SR20",
    "BN2P": "Britten-Norman BN-2 Islander (Kolben)",
    "BN2T": "Britten-Norman BN-2T Turbine Islander",
    "DHC6": "De Havilland Canada DHC-6 Twin Otter",
    "DR40": "Robin DR400", "AQUI": "Aquila A210", "C42": "Comco Ikarus C42",
    "PZ04": "PZL-104 Wilga",
    "DO27": "Dornier Do 27", "DO28": "Dornier Do 28 Skyservant",
    "C170": "Cessna 170", "C180": "Cessna 180", "C185": "Cessna 185",
    "C206": "Cessna 206 Stationair", "C210": "Cessna 210",
    "PA32": "Piper PA-32 Cherokee Six/Saratoga", "PA44": "Piper PA-44 Seminole",
    "DA20": "Diamond DA20 Katana", "DV20": "Diamond DV20 Katana",
    "BE33": "Beechcraft Bonanza/Debonair 33", "BE35": "Beechcraft Bonanza 35",
    "M20P": "Mooney M20 (Kolbenvarianten)", "G115": "Grob G 115",
    "J3": "Piper J-3 Cub", "AN2": "Antonov An-2",
    "SF25": "Scheibe SF-25 Falke (Motorsegler)",
    # MSFS-Standardflotte + gängige GA-Addons
    "SF50": "Cirrus SF50 Vision Jet",
    "BE20": "Beechcraft King Air 200", "B350": "Beechcraft King Air 350",
    "BE9L": "Beechcraft King Air C90",
    "C310": "Cessna 310", "C414": "Cessna 414 Chancellor",
    "C25C": "Cessna Citation CJ4", "C700": "Cessna Citation Longitude",
    "DHC2": "De Havilland Canada DHC-2 Beaver",
    "DHC3": "De Havilland Canada DHC-3 Otter",
    "KODI": "Daher/Quest Kodiak 100", "PC6T": "Pilatus PC-6 Turbo Porter",
    "DC3": "Douglas DC-3", "JU52": "Junkers Ju 52/3m",
    "ICON": "ICON A5", "VL3": "Aveko/JMB VL-3", "E300": "Extra 300/330",
    # weitere MSFS-Standard-/Addon-Muster (Quelle: msfsaddons-Liste des Auftraggebers)
    "PTS1": "Pitts Special S-1", "PTS2": "Pitts Special S-2",
    "C140": "Cessna 140", "C162": "Cessna 162 Skycatcher", "C207": "Cessna 207",
    "C337": "Cessna 337 Skymaster", "COL4": "Cessna 400 Corvalis/TTx",
    "DA50": "Diamond DA50", "FDCT": "Flight Design CT-Serie",
    "GA8": "GippsAero GA8 Airvan", "HUSK": "Aviat A-1 Husky",
    "XCUB": "CubCrafters XCub/NX Cub", "PA30": "Piper PA-30 Twin Comanche",
    "BE18": "Beechcraft Model 18", "AT8T": "Air Tractor AT-802",
    "G21": "Grumman G-21 Goose", "TIGM": "De Havilland DH.82 Tiger Moth",
    "ST75": "Boeing-Stearman Model 75", "YK52": "Jakowlew Jak-52",
    "P51": "North American P-51 Mustang", "SPIT": "Supermarine Spitfire",
    # Hubschrauber (ICAO-Typendesignatoren)
    "AS65": "Aérospatiale/Airbus AS365 Dauphin (Hubschrauber)",
    "AS50": "Airbus H125/AS350 Écureuil (Hubschrauber)",
    "EC35": "Airbus H135/EC135 (Hubschrauber)",
    "EC45": "Airbus H145/EC145 (Hubschrauber)",
    "B06": "Bell 206 JetRanger (Hubschrauber)",
    "B212": "Bell 212 (Hubschrauber)", "B222": "Bell 222 (Hubschrauber)",
    "B407": "Bell 407 (Hubschrauber)",
    "B47G": "Bell 47G (Hubschrauber)", "B47J": "Bell 47J Ranger (Hubschrauber)",
    "UH1": "Bell UH-1 Iroquois / Huey (Hubschrauber)",
    "LAMA": "Aérospatiale SA-315B Lama (Hubschrauber)",
    "ALO3": "Aérospatiale Alouette III (Hubschrauber)",
    "H160": "Airbus H160 (Hubschrauber)",
    "EC30": "Airbus H130/EC130 (Hubschrauber)",
    "EC25": "Airbus H225/EC225 Super Puma (Hubschrauber)",
    "B105": "MBB Bo 105 (Hubschrauber)",
    "G2CA": "Guimbal Cabri G2 (Hubschrauber)",
    "H269": "Schweizer 269/300 (Hubschrauber)",
    "H47": "Boeing CH-47 Chinook (Hubschrauber)",
    "H60": "Sikorsky UH-60 Black Hawk (Hubschrauber)",
    "S64": "Sikorsky/Erickson S-64 Skycrane (Hubschrauber)",
    "R22": "Robinson R22 (Hubschrauber)", "R44": "Robinson R44 (Hubschrauber)",
    "R66": "Robinson R66 (Hubschrauber)",
    "S76": "Sikorsky S-76 (Hubschrauber)",
}

# Recherche-Grenzen: großzügig (Web-Suche über seltene Muster darf dauern), aber ENDLICH —
# ohne eigenen Timeout galt der SDK-Default (10 min) JE Aufruf, bei bis zu 6 Fortsetzungs-
# runden drehte der Admin-Knopf im schlimmsten Fall eine Stunde.
_SUGGEST_REQUEST_TIMEOUT_S = 120.0   # je API-Aufruf
_SUGGEST_TOTAL_BUDGET_S = 300.0      # gesamte Recherche inkl. Fortsetzungsrunden


def is_configured() -> bool:
    """True, wenn ein Anthropic-Key konfiguriert ist (sonst ist der Vorschlag deaktiviert)."""
    from app.config import get_settings
    return bool(get_settings().ANTHROPIC_API_KEY.strip())


def _build_result(make_model: str, mtow_kg: float, empty_kg: float, fuel_full_kg: float,
                  crew_kg: float = _CREW_KG) -> dict:
    """Aus den recherchierten Rohwerten das Ergebnis-Dict bauen (reine, testbare Rechnung).

    Default-Betankung ist der HALBE Tank (Insel-Hopping): Zuladung =
    ``max(0, MTOW − Leergewicht − fuel_full/2 − Crew)`` — Pilot zählt nicht als Fracht.
    ``fuel_full_kg`` bleibt das Maximum (volle Tanks) fürs Label im Admin.
    """
    fuel_kg = fuel_full_kg / 2.0
    payload = max(0.0, mtow_kg - empty_kg - fuel_kg - crew_kg)
    return {
        "make_model": make_model,
        "mtow_kg": round(mtow_kg, 1),
        "empty_kg": round(empty_kg, 1),
        "fuel_kg": round(fuel_kg, 1),
        "fuel_full_kg": round(fuel_full_kg, 1),
        "crew_kg": crew_kg,
        "payload_kg": round(payload, 1),
    }


def _extract_spec(resp) -> dict | None:
    """Das JSON-Spec aus den Text-Blöcken der Antwort ziehen (letztes valides zuerst)."""
    for block in reversed(getattr(resp, "content", []) or []):
        if getattr(block, "type", None) == "text":
            try:
                data = json.loads(block.text)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and "mtow_kg" in data:
                return data
    return None


def suggest_aircraft_payload(type_code: str) -> dict | None:
    """Vorschlag für die Zuladungs-Komponenten eines Flugzeugtyps — per Web-Recherche (Haiku 4.5).

    Rückgabe (kg, im Admin editierbar) oder ``None``::

        {"make_model", "mtow_kg", "empty_kg", "fuel_kg", "fuel_full_kg", "crew_kg", "payload_kg"}

    Vertrag der beiden Fehlausgänge — der Aufrufer MUSS sie unterscheiden:

    - ``None`` = **keine Daten**: kein Key, kein ``anthropic``-Paket, leerer Typcode oder eine
      Antwort ohne verwertbares Spec. Aussage über das Muster, darf gespeichert werden.
    - ``TransientResearchError`` = **vorübergehend gescheitert** (Überlastung, Rate-Limit,
      Timeout, Verbindungsfehler): keine Aussage über das Muster, erneut versuchen. Früher kam
      auch hier ``None`` zurück — der Aufrufer merkte sich den Fehlschlag dauerhaft als
      „nichts gefunden" (AP32-Fall 2026-07-30).

    Default-Betankung = halber Tank: ``fuel_kg = fuel_full_kg / 2`` (Vorbefüllung im Admin),
    ``fuel_full_kg`` = Maximum (volle Tanks) fürs Label. ``payload_kg`` =
    ``max(0, mtow − empty − fuel_kg − crew)`` (Pilot abgezogen).
    """
    code = (type_code or "").strip().upper()
    if not code:
        return None
    from app.config import get_settings
    api_key = get_settings().ANTHROPIC_API_KEY.strip()
    if not api_key:
        logger.info("ANTHROPIC_API_KEY nicht gesetzt — Zuladungs-Vorschlag deaktiviert")
        return None
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic nicht installiert — Zuladungs-Vorschlag nicht möglich")
        return None

    hint = _TYPE_HINTS.get(code, "")
    prompt = (
        f"Recherchiere im Web die realen, dokumentierten Herstellerangaben für den "
        f"Luftfahrzeugtyp (Flugzeug oder Hubschrauber) mit ICAO-Typendesignator '{code}'"
        + (f" ({hint})" if hint else "")
        + ". Identifiziere zuerst eindeutig, welches Muster sich hinter dem Designator verbirgt, "
        "und nimm dessen gängigste zertifizierte Variante. Nutze offizielle Quellen "
        "(Flughandbuch/POH, Type Certificate Data Sheet, Hersteller-Datenblatt). Gib in "
        "Kilogramm: MTOW, Standard-Leergewicht (empty weight) und die nutzbare Treibstoffmenge "
        "bei VOLLEN Tanks (usable fuel). Schätze NICHT großzügig, runde nicht auf, erfinde keine "
        "Zahlen — nimm die dokumentierten Werte; im Zweifel den konservativen (niedrigeren) "
        "realistischen Wert. Antworte am Ende ausschließlich mit dem geforderten JSON."
    )

    try:
        import time as _time
        # Streaming + max_retries=0: ein Nicht-Streaming-Call, der den Client-Timeout reißt,
        # wird vom SDK still 2× wiederholt und JEDER abgebrochene Versuch serverseitig zu Ende
        # gerechnet und berechnet (Live-Befund 2026-07-02: Dreifach-Billing pro Klick).
        client = anthropic.Anthropic(
            api_key=api_key, timeout=_SUGGEST_REQUEST_TIMEOUT_S, max_retries=0
        )
        messages = [{"role": "user", "content": prompt}]
        deadline = _time.monotonic() + _SUGGEST_TOTAL_BUDGET_S
        resp = None
        for _ in range(6):  # Server-Tool-Loop: bei pause_turn erneut senden, bis Claude fertig ist
            with client.messages.stream(
                model=_SUGGEST_MODEL,
                max_tokens=6000,
                tools=[_WEB_SEARCH_TOOL],
                output_config={"format": {"type": "json_schema", "schema": _SPEC_SCHEMA}},
                messages=messages,
            ) as stream:
                resp = stream.get_final_message()
            if resp.stop_reason != "pause_turn":
                break
            if _time.monotonic() >= deadline:
                logger.warning("Zuladungs-Vorschlag für %s: Zeitbudget erschöpft", code)
                raise TransientResearchError(f"Zeitbudget erschöpft für {code}")
            messages.append({"role": "assistant", "content": resp.content})
        if resp is None or resp.stop_reason == "refusal":
            logger.warning("Zuladungs-Vorschlag für %s abgelehnt/leer", code)
            return None
        spec = _extract_spec(resp)
    except TransientResearchError:
        raise
    except Exception as exc:  # noqa: BLE001 — Komfortpfad, jeder Fehler → kein Vorschlag
        if is_transient_error(exc):
            # NICHT als "keine Daten" behandeln: der Aufrufer soll es erneut versuchen.
            logger.warning("Zuladungs-Vorschlag für %s vorübergehend gescheitert: %s", code, exc)
            raise TransientResearchError(str(exc)) from exc
        logger.warning("Zuladungs-Vorschlag für %s fehlgeschlagen: %s", code, exc)
        return None

    if not spec:
        logger.warning(
            "Zuladungs-Vorschlag für %s: kein JSON erhalten (stop_reason=%s)",
            code, getattr(resp, "stop_reason", None),
        )
        return None
    try:
        mtow, empty, fuel_full = (
            float(spec["mtow_kg"]), float(spec["empty_kg"]), float(spec["fuel_full_kg"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Zuladungs-Vorschlag für %s: unvollständige Werte (%s)", code, exc)
        return None
    # json.loads akzeptiert Infinity/NaN als Erweiterung und float() lässt sie durch — ein
    # Phantom-Typcode (z. B. Buchstabendreher AS65→SA65) liefert dann inf/nan, was später die
    # ganze Zuladungs-Liste beim JSON-Encoding sprengt. Nur endliche, positive Werte akzeptieren.
    if not all(math.isfinite(v) and v > 0 for v in (mtow, empty, fuel_full)):
        logger.warning(
            "Zuladungs-Vorschlag für %s: unplausible Werte (mtow=%s empty=%s fuel=%s)",
            code, mtow, empty, fuel_full,
        )
        return None
    # Die Schema-Vorgabe für make_model ist nur {"type": "string"} -- ohne Laengengrenze.
    # Live-Befund MR20: bei mehreren M20-Varianten ohne eindeutigen Favoriten schrieb das
    # Modell seine Unsicherheit als 1063-Zeichen-Prosaabsatz IN dieses Feld statt eines
    # Namens (die Zahlen selbst waren brauchbar, nur make_model nicht). harden_name() (siehe
    # dort) verwirft genau das schon beim LESEN in _muster_name() -- hier auf der SCHREIBSEITE
    # dieselbe Haertung, sonst landet der Prosa-Absatz erst in aircraft_payloads (persistiert,
    # im Admin sichtbar als "Vorschlag") und blockiert von dort aus jede erneute Recherche
    # (_auto_research_payload ueberspringt Codes mit bestehender Zeile), ohne dass
    # payload_research je einen Endzustand bekommt -- ein Muster bliebe damit dauerhaft
    # Kandidat in der Nachlese, ohne je einen Namen zu zeigen.
    make_model = harden_name(spec.get("make_model")) or code
    return _build_result(make_model, mtow, empty, fuel_full)


# ---------------------------------------------------------------------------
# Lustige KI-Sprüche (Phase 2) — Claude Sonnet 5, kein Web-Search
# ---------------------------------------------------------------------------

_QUIP_SYSTEM = (
    "Du bist der spitzbübische Bordfunker der virtuellen Airline FriesenFlieger. Du schreibst "
    "kurze, trockene, herzliche Sprüche mit norddeutschem Humor — in klarem, für alle sofort "
    "verständlichem Hochdeutsch. Ein ganz leichter norddeutscher Einschlag ist gut (ein 'Moin' "
    "als Einstieg ist ok), aber KEINE plattdeutschen Wörter oder Sätze, die man übersetzen "
    "müsste (nichts wie 'frünnen', 'dat', 'nich', 'lütt'). Wechsle den Einstieg ab (direkt mit "
    "dem Namen, einer Frage, einer Beobachtung, einem Ausruf) und variiere den Satzbau von "
    "Spruch zu Spruch — 'Moin' ist nur eine von vielen Optionen, keine Standardformel. Nutze "
    "NUR die gelieferten Fakten, erfinde keine dazu. Keine Hashtags, keine Anführungszeichen. "
    "Steht im Kontext ein 'verlust': mach dich gutmütig darüber lustig. Ein versunkener Kutter "
    "heißt IMMER 'Kutter versunken' — nie der Pilot, immer der Kutter geht unter."
)


def _chat(system: str, user: str, max_tokens: int) -> str | None:
    """Ein einfacher Sonnet-5-Aufruf ohne Tools (Denken aus, effort low) — Silent-Fail."""
    from app.config import get_settings
    api_key = get_settings().ANTHROPIC_API_KEY.strip()
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=max_tokens,
            thinking={"type": "disabled"},
            output_config={"effort": "low"},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if getattr(resp, "stop_reason", None) == "refusal":
            return None
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        text = " ".join(t.strip() for t in parts if t).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 — Komfortpfad
        logger.warning("Spruch-Generierung fehlgeschlagen: %s", exc)
        return None


def flight_quip(context: dict) -> str | None:
    """Einen lustigen Einzeiler zu einem Frachtflug erzeugen (mit Piloten-Kontext)."""
    c = context or {}
    verlust = c.get("verlust")
    relay = c.get("relay")
    lines = [
        f"Pilot-Vorname: {c.get('vorname') or '?'}",
        f"Frachtflüge heute gesamt über ALLE Frachtarten: {c.get('flights_tonight')} "
        f"(reiner Fleiß-Indikator — NICHT die Anzahl für DIESE Fracht oder DIESE Strecke!)",
        f"Muster: {c.get('aircraft') or '?'}",
        f"Strecke: {c.get('route') or '?'}",
        f"Fracht an Bord: {', '.join(c.get('cargo') or []) or '—'}",
        f"Zuladung: {c.get('tonnage_kg')} kg",
    ]
    if c.get("speed_kt"):
        lines.append(f"Tempo: {c['speed_kt']} kt")
    if c.get("detour_ratio"):
        extra = " (fliegt Umwege!)" if c["detour_ratio"] >= 1.3 else ""
        lines.append(f"Umweg-Faktor: {c['detour_ratio']}x Luftlinie{extra}")
    if verlust:
        # #67-Folgefund (Live 06.07.): der Kontext liefert `verlust` (versunken/geklaut),
        # aber der Prompt griff ihn nie auf → die KI textete einen normalen Liefer-Spruch für
        # einen SCHIEFGEGANGENEN Flug ("hat 160 kg geladen …" obwohl geklaut). Bei gesetztem
        # Verlust MUSS der Spruch das aufgreifen und darf NICHT nach Auslieferung klingen.
        # (Eine „returned"-Bewegung ist KEIN Verlust — die läuft über `relay`, s. u.)
        lines.append(f"WICHTIG — DIESER FLUG GING SCHIEF: {verlust}")
        user = (
            "Schreibe EINEN frechen, spitzbübischen Einzeiler (genau ein Satz) zu diesem "
            "SCHIEFGEGANGENEN Frachtflug. Die Fracht kam NICHT ordentlich an (s. 'WICHTIG') — nimm "
            "den Piloten dafür augenzwinkernd auf die Schippe, statt es nur nüchtern zu berichten. "
            "Bei GEKLAUT: tu, als hätte sich der Pilot als Spitzbub / Seeräuber die Ladung selbst "
            "unter den Nagel gerissen (Kaperfahrt, krumme Tour, ab damit ins Versteck) — frech und "
            "anklagend-augenzwinkernd, aber herzlich, nie wirklich beleidigend. Bei VERSUNKEN: der "
            "KUTTER ist mitsamt Ladung in der Nordsee abgesoffen (IMMER der Kutter, NIE der Pilot!) — "
            "mal konkret aus, was jetzt am Meeresgrund los ist: Fische, Krabben oder Seehunde freuen "
            "sich über die Fracht, Neptun/der Klabautermann kriegt seinen Anteil, die Ladung dümpelt "
            "in der Nordsee — nimm dabei die KONKRETE Fracht aufs Korn (z. B. Strandkörbe, auf denen "
            "jetzt die Fische Urlaub machen). Gutmütig-schadenfroh. "
            "Ein deftiger, spitzbübischer Nordtonfall passt hier "
            "gut (Wörter wie 'Spitzbov', 'Kaperfahrt', 'Deern/Jung' sind ok) — aber weiter für alle "
            "sofort verständlich, KEINE Wörter, die man übersetzen müsste. Der Spruch darf AUF KEINEN "
            "FALL nach ordentlicher Auslieferung klingen (kein 'bringt … ans Ziel', kein 'liefert … "
            "aus'). ERFINDE KEINE Zahlen/Zählungen, die nicht in den Fakten stehen (kein 'zum x-ten "
            "Mal'; 'Frachtflüge heute gesamt' zählt ALLE Frachtarten, nicht diese eine). "
            "Fang NICHT immer mit 'Moin' an. Fakten:\n- "
            + "\n- ".join(lines)
        )
    elif relay:
        # v10.2.1-Umbenennung (Live-Fund 21.07.): eine „returned"-Bewegung ist eine
        # Staffel-Übergabe („am Ladeplatz abgeladen"), KEIN schiefgegangener Flug. Nicht als
        # Kneifen/Umdrehen framen — das las sich als „unentschlossen".
        lines.append(f"HINWEIS — STAFFEL-ÜBERGABE (KEIN Verlust): {relay}")
        user = (
            "Schreibe EINEN lockeren, herzlichen Einzeiler (genau ein Satz) zu diesem Flug. Der "
            "Pilot hat die Fracht NICHT bis zum Ziel gebracht, sondern an einem Ladeplatz abgeladen "
            "(s. 'HINWEIS') — dort liegt sie zum Weitertragen bereit, ein anderer bringt sie weiter. "
            "Das ist eine Staffel-Übergabe, KEIN Missgeschick und KEIN Verlust: nichts ging verloren, "
            "nichts sank, nichts wurde geklaut. Neck ihn höchstens ganz milde dafür, dass er die "
            "letzte Etappe einem Kollegen überlässt — aber wohlwollend, nie als Kneifen, Rückzug "
            "oder Unentschlossenheit. Lass es NICHT nach ordentlicher Auslieferung ans Ziel klingen. "
            "ERFINDE KEINE Zahlen/Zählungen, die nicht in den Fakten stehen. Fang NICHT immer mit "
            "'Moin' an. Fakten:\n- "
            + "\n- ".join(lines)
        )
    else:
        user = (
            "Schreibe EINEN lustigen Einzeiler (genau ein Satz) zu diesem Frachtflug. Nutze die Fakten "
            "als Ideen-Pool, aber greif NICHT bei jedem Flug alle auf — meistens reicht EIN Aspekt "
            "(oder auch mal keiner, nur die Fracht/den Namen), sonst klingen alle Sprüche gleich "
            "aufgezählt. WECHSLE DEN AUFHÄNGER bewusst durch — nimm mal das Flugzeugmuster (eine kleine "
            "Cessna, ein zäher Zweimot, was der Flieger so hermacht), mal die Fracht selbst und wofür "
            "sie ist (Heringe für die Seehunde, Inselpost für die Insulaner, Filmrollen für den "
            "Filmabend, Baumaterial für den Deich…), mal den Zielort, mal den Piloten-Namen, mal die "
            "schiere Menge. TEMPO und UMWEG sind NUR ZWEI von vielen Aspekten — nutze sie SELTEN und "
            "nicht als Standard (nicht jeder Spruch braucht Knoten oder Luftlinie). "
            "ERFINDE KEINE ZAHLEN oder Zählungen, die nicht in den Fakten stehen — insbesondere NICHT "
            "'zum zweiten/dritten/x-ten Mal DIESE Fracht/Strecke' (die 'Frachtflüge heute gesamt' zählt "
            "ALLE Frachtarten zusammen, nicht diese eine). "
            "Fang NICHT immer mit 'Moin' an — wechsle den Einstieg ab (Name zuerst, eine Frage, ein "
            "Ausruf, mittendrin einsteigen, o.ä.). Variation (bei Aufhänger UND Einstieg) ist wichtiger "
            "als Vollständigkeit. Fakten:\n- "
            + "\n- ".join(lines)
        )
    return _chat(_QUIP_SYSTEM, user, 200)


def event_summary(context: dict) -> str | None:
    """Eine launige Tagesend-Zusammenfassung eines FriesenKutter-Events erzeugen."""
    c = context or {}
    pilots = ", ".join(f"{k}: {v}" for k, v in (c.get("pilots") or {}).items()) or "—"
    lines = [
        f"Event: {c.get('name') or '?'}",
        f"Ziel (dorthin geht ALLE Fracht): {c.get('destination') or '?'}",
        f"Abholplätze (Fracht wird dort geladen): {', '.join(c.get('pickups') or []) or '—'}",
        f"Gesamt bewegt: {c.get('total_kg')} kg in {c.get('loaded_count')} Fuhren",
        f"Fracht: {', '.join(c.get('cargo') or []) or '—'}",
        f"Piloten mit mehreren Fuhren: {pilots}",
    ]
    verluste = c.get("verluste") or []
    if verluste:
        lines.append(f"Verluste unterwegs ({round(c.get('lost_total_kg') or 0)} kg): " + "; ".join(verluste))
    else:
        lines.append("Verluste: keine — alles kam heil an")
    user = (
        "Schreibe eine kurze, launige Tagesend-Zusammenfassung für die "
        "Friesen — wie viel Fracht zusammen bewegt wurde, mit einem Augenzwinkern. "
        "Eine FUHRE ist eine am Ziel abgelieferte Ladung — NICHT ein Flug. Wer über einen "
        "Zwischenplatz fuhr, brauchte dafür mehrere Flüge und lieferte trotzdem nur eine Fuhre "
        "ab. Schreibe deshalb IMMER »Fuhre(n)« und NIEMALS »Flug/Flüge« für diese Zahlen. "
        "Nenne JEDEN Piloten aus »Piloten mit mehreren Fuhren« genau so, wie er dort steht — mit "
        "Vorname UND Callsign in Klammern — und mit seiner GENAUEN Fuhrenzahl. Lass keinen weg, "
        "fasse keine zwei zusammen und erfinde weder Vornamen noch Nachnamen noch Zahlen. "
        "Dort stehen nur Piloten mit MINDESTENS ZWEI Fuhren; wer eine einzelne gebracht hat, "
        "wird bewusst nicht aufgezählt. Zähle deshalb NIEMANDEN auf, der dort nicht steht, und "
        "schreibe zu niemandem »mit 1 Fuhre«. Steht dort »—«, nenne gar keine Namen und "
        "erwähne die Piloten nur als Gruppe. "
        "Die Abholplätze sind KEINE geflogene Route oder Rundstrecke — jeder Kutter fliegt von genau "
        "EINEM Abholplatz zum Ziel. Stelle es NIEMALS als Runde/Streckenkette dar (kein »auf der Runde "
        "A-B-C-D«) und reihe die Plätze nicht mit Pfeilen/Bindestrichen aneinander. "
        "WICHTIG: Wenn es Verluste gab, MUSST du sie erwähnen (wer, versunken/geklaut, wie viel) "
        "und darfst NICHT behaupten, alles sei heil angekommen oder niemand habe etwas verloren — "
        "das wäre ein Widerspruch zu den Fakten. "
        "Bei »hat die Fracht selbst geklaut« ist der genannte Pilot der TÄTER: Er ist mit der "
        "Ladung an einem fremden Platz gelandet und hat sie dort behalten. Schreibe ihn NIEMALS "
        "als Opfer — kein »ihm wurde abgenommen«, kein »wurde erleichtert«, kein unbekannter "
        "Dieb und kein »irgendwer«. Beim Versinken ist er dagegen KEIN Täter, dort ist der "
        "Kutter schlicht abgesoffen. "
        "Erwähne NICHT, dass jemand Fracht an einem Ladeplatz abgesetzt, abgeladen, zwischen- "
        "gelagert oder weitergereicht habe — solche Zwischenschritte stehen bewusst nicht in den "
        "Fakten und dürfen auch nicht erfunden werden. Fakten:\n- "
        + "\n- ".join(lines)
    )
    return _chat(_QUIP_SYSTEM, user, 800)
