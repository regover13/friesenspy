"""Claude-API-Anbindung für FriesenSpy (aktuell: Zuladungs-Vorschlag pro Flugzeugtyp).

Der Vorschlag **recherchiert per Web-Search** (serverseitiges Anthropic-Tool) die realen,
dokumentierten Herstellerangaben und liefert sie als Structured Output. Modell: Claude Sonnet 5.

Bewusst mit Silent-Fail: der Vorschlag ist Komfort im Admin, kein kritischer Pfad. Ohne
``ANTHROPIC_API_KEY`` (mit TSBot geteilt) oder ohne ``anthropic``-Paket → ``None``; die
Zuladungs-Tabelle bleibt manuell pflegbar.

Phase 2 (geplant): lustige Flug-Kommentare über denselben Client.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Vom Nutzer gewählt: Sonnet 5 (recherchiert genauer als Haiku, unterstützt Web-Search-Dynamic-Filtering).
_MODEL = "claude-sonnet-5"
# Standard-Pilotengewicht (kg) — zählt nicht als Fracht (Wert = database._CREW_KG_DEFAULT).
_CREW_KG = 85.0
# Serverseitiges Web-Search-Tool (kein Beta-Header nötig); max_uses begrenzt die Kosten.
_WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}
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

# Kleine kuratierte Umschreibung gängiger ICAO-Typcodes → Klartext, damit der Prompt eindeutig ist.
_TYPE_HINTS = {
    "C172": "Cessna 172", "C182": "Cessna 182", "C208": "Cessna 208 Caravan",
    "PA28": "Piper PA-28", "PA24": "Piper PA-24 Comanche", "PA34": "Piper PA-34 Seneca",
    "BE58": "Beechcraft Baron 58", "BE36": "Beechcraft Bonanza 36", "PC12": "Pilatus PC-12",
    "DA40": "Diamond DA40", "DA42": "Diamond DA42", "TBM9": "Daher TBM 900", "SR22": "Cirrus SR22",
}


def is_configured() -> bool:
    """True, wenn ein Anthropic-Key konfiguriert ist (sonst ist der Vorschlag deaktiviert)."""
    from app.config import get_settings
    return bool(get_settings().ANTHROPIC_API_KEY.strip())


def _build_result(make_model: str, mtow_kg: float, empty_kg: float, fuel_full_kg: float,
                  crew_kg: float = _CREW_KG) -> dict:
    """Aus den recherchierten Rohwerten das Ergebnis-Dict bauen (reine, testbare Rechnung).

    Zuladung = ``max(0, MTOW − Leergewicht − volle Tanks − Crew)`` — Pilot zählt nicht als Fracht.
    """
    payload = max(0.0, mtow_kg - empty_kg - fuel_full_kg - crew_kg)
    return {
        "make_model": make_model,
        "mtow_kg": round(mtow_kg, 1),
        "empty_kg": round(empty_kg, 1),
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
    """Vorschlag für die Zuladungs-Komponenten eines Flugzeugtyps — per Web-Recherche (Claude Sonnet 5).

    Rückgabe (kg, im Admin editierbar) oder ``None`` bei fehlendem Key/Paket/Fehler::

        {"make_model", "mtow_kg", "empty_kg", "fuel_full_kg", "crew_kg", "payload_kg"}

    ``payload_kg`` = ``max(0, mtow − empty − fuel_full − crew)`` (volle Tanks, Pilot abgezogen).
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
        f"Recherchiere im Web die realen, dokumentierten Herstellerangaben für den Flugzeugtyp "
        f"mit ICAO-Code '{code}'"
        + (f" ({hint})" if hint else "")
        + ". Nutze offizielle Quellen (Flughandbuch/POH, Type Certificate Data Sheet, "
        "Hersteller-Datenblatt) der gängigsten zertifizierten Variante. Gib in Kilogramm: MTOW, "
        "Standard-Leergewicht (empty weight) und die nutzbare Treibstoffmenge bei VOLLEN Tanks "
        "(usable fuel). Schätze NICHT großzügig, runde nicht auf, erfinde keine Zahlen — nimm die "
        "dokumentierten Werte; im Zweifel den konservativen (niedrigeren) realistischen Wert. "
        "Antworte am Ende ausschließlich mit dem geforderten JSON."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        messages = [{"role": "user", "content": prompt}]
        resp = None
        for _ in range(6):  # Server-Tool-Loop: bei pause_turn erneut senden, bis Claude fertig ist
            resp = client.messages.create(
                model=_MODEL,
                max_tokens=6000,
                tools=[_WEB_SEARCH_TOOL],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _SPEC_SCHEMA}},
                messages=messages,
            )
            if resp.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": resp.content})
        if resp is None or resp.stop_reason == "refusal":
            logger.warning("Zuladungs-Vorschlag für %s abgelehnt/leer", code)
            return None
        spec = _extract_spec(resp)
    except Exception as exc:  # noqa: BLE001 — Komfortpfad, jeder Fehler → kein Vorschlag
        logger.warning("Zuladungs-Vorschlag für %s fehlgeschlagen: %s", code, exc)
        return None

    if not spec:
        logger.warning("Zuladungs-Vorschlag für %s: kein JSON erhalten", code)
        return None
    try:
        return _build_result(
            str(spec.get("make_model") or code),
            float(spec["mtow_kg"]), float(spec["empty_kg"]), float(spec["fuel_full_kg"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Zuladungs-Vorschlag für %s: unvollständige Werte (%s)", code, exc)
        return None


# ---------------------------------------------------------------------------
# Lustige KI-Sprüche (Phase 2) — Claude Sonnet 5, kein Web-Search
# ---------------------------------------------------------------------------

_QUIP_SYSTEM = (
    "Du bist der spitzbübische Bordfunker der virtuellen Airline FriesenFlieger. Du schreibst "
    "kurze, trockene, herzliche Sprüche im ostfriesischen/norddeutschen Humor (gern mit "
    "plattdeutschem Anklang wie 'Moin'). Nutze NUR die gelieferten Fakten, erfinde keine dazu. "
    "Keine Hashtags, keine Anführungszeichen."
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
    lines = [
        f"Pilot-Vorname: {c.get('vorname') or '?'}",
        f"Frachtflug heute Nr.: {c.get('flights_tonight')} (Fleiß)",
        f"Muster: {c.get('aircraft') or '?'}",
        f"Strecke: {c.get('route') or '?'}",
        f"Fracht: {', '.join(c.get('cargo') or []) or '—'}",
        f"Zuladung: {c.get('tonnage_kg')} kg",
    ]
    if c.get("speed_kt"):
        lines.append(f"Tempo: {c['speed_kt']} kt")
    if c.get("detour_ratio"):
        extra = " (fliegt Umwege!)" if c["detour_ratio"] >= 1.3 else ""
        lines.append(f"Umweg-Faktor: {c['detour_ratio']}x Luftlinie{extra}")
    user = (
        "Schreibe EINEN lustigen Einzeiler (genau ein Satz) zu diesem Frachtflug. Nutze die Fakten "
        "als Ideen-Pool, aber greif NICHT bei jedem Flug alle auf — meistens reicht EIN Aspekt "
        "(oder auch mal keiner, nur die Fracht/den Namen), sonst klingen alle Sprüche gleich "
        "aufgezählt. Variation ist wichtiger als Vollständigkeit. Fakten:\n- "
        + "\n- ".join(lines)
    )
    return _chat(_QUIP_SYSTEM, user, 200)


def event_summary(context: dict) -> str | None:
    """Eine launige Tagesend-Zusammenfassung eines FriesenKutter-Events erzeugen."""
    c = context or {}
    pilots = ", ".join(f"{k}: {v}" for k, v in (c.get("pilots") or {}).items()) or "—"
    lines = [
        f"Event: {c.get('name') or '?'}",
        f"Strecke: {c.get('route') or '?'} (Ziel {c.get('destination') or '?'})",
        f"Gesamt bewegt: {c.get('total_kg')} kg in {c.get('loaded_count')} Frachtflügen",
        f"Fracht: {', '.join(c.get('cargo') or []) or '—'}",
        f"Piloten (Flüge): {pilots}",
    ]
    user = (
        "Schreibe eine kurze, launige Tagesend-Zusammenfassung (1–2 Sätze) für die "
        "Friesen — wie viel Fracht zusammen bewegt wurde, mit einem Augenzwinkern. Fakten:\n- "
        + "\n- ".join(lines)
    )
    return _chat(_QUIP_SYSTEM, user, 400)
