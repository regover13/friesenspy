"""Claude-API-Anbindung für FriesenSpy (aktuell: Zuladungs-Vorschlag pro Flugzeugtyp).

Bewusst schlank und mit Silent-Fail: Der Vorschlag ist Komfort im Admin, kein kritischer Pfad.
Ohne ``ANTHROPIC_API_KEY`` (oder ohne installiertes ``anthropic``-Paket) liefert das Modul einfach
``None`` — die Zuladungs-Tabelle bleibt manuell pflegbar. Der Key wird mit TSBot geteilt
(dieselbe Env-Variable ``ANTHROPIC_API_KEY``).

Phase 2 (geplant): lustige Flug-Kommentare über denselben Client.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Günstigstes Modell mit Structured Outputs — reicht für einen Spec-Lookup locker (~0,001 $/Call).
_MODEL = "claude-haiku-4-5"

# Kleine kuratierte Umschreibung gängiger ICAO-Typcodes → Klartext, damit der Prompt eindeutig ist.
# (Nur Prompt-Hilfe; das Modell kennt die Codes meist auch direkt.)
_TYPE_HINTS = {
    "C172": "Cessna 172", "C182": "Cessna 182", "C208": "Cessna 208 Caravan",
    "PA28": "Piper PA-28", "PA34": "Piper PA-34 Seneca", "BE58": "Beechcraft Baron 58",
    "BE36": "Beechcraft Bonanza 36", "PC12": "Pilatus PC-12", "DA40": "Diamond DA40",
    "DA42": "Diamond DA42", "TBM9": "Daher TBM 900", "SR22": "Cirrus SR22",
}


def is_configured() -> bool:
    """True, wenn ein Anthropic-Key konfiguriert ist (sonst ist der Vorschlag deaktiviert)."""
    from app.config import get_settings
    return bool(get_settings().ANTHROPIC_API_KEY.strip())


def suggest_aircraft_payload(type_code: str) -> dict | None:
    """Vorschlag für die Zuladungs-Komponenten eines Flugzeugtyps via Claude (Structured Output).

    Rückgabe (alles kg, im Admin editierbar) oder ``None`` bei fehlendem Key/Paket/Fehler::

        {"make_model", "mtow_kg", "empty_kg", "fuel_full_kg", "fuel_half_kg", "payload_kg"}

    ``payload_kg`` ist der Vorschlag bei **halbem** Tank: ``max(0, mtow − empty − fuel_full/2)``.
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
        from pydantic import BaseModel
    except ImportError:
        logger.warning("anthropic/pydantic nicht installiert — Zuladungs-Vorschlag nicht möglich")
        return None

    class AircraftSpec(BaseModel):
        make_model: str
        mtow_kg: float
        empty_kg: float
        fuel_full_kg: float

    hint = _TYPE_HINTS.get(code, "")
    prompt = (
        f"Gib typische reale Spezifikationen für den Flugzeugtyp mit ICAO-Code '{code}'"
        + (f" ({hint})" if hint else "")
        + ". Werte in Kilogramm: maximales Startgewicht (MTOW), Leergewicht (empty weight) und "
        "die maximale Treibstoffmenge bei vollen Tanks (fuel_full). Nutze allgemein bekannte "
        "Durchschnittswerte der gängigsten Variante."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.parse(
            model=_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            output_format=AircraftSpec,
        )
        if getattr(resp, "stop_reason", None) == "refusal":
            logger.warning("Claude hat den Zuladungs-Vorschlag für %s abgelehnt", code)
            return None
        spec = resp.parsed_output
    except Exception as exc:  # noqa: BLE001 — Komfortpfad, jeder Fehler → kein Vorschlag
        logger.warning("Zuladungs-Vorschlag für %s fehlgeschlagen: %s", code, exc)
        return None

    fuel_half = round(spec.fuel_full_kg / 2, 1)
    payload = max(0.0, spec.mtow_kg - spec.empty_kg - fuel_half)
    return {
        "make_model": spec.make_model,
        "mtow_kg": round(spec.mtow_kg, 1),
        "empty_kg": round(spec.empty_kg, 1),
        "fuel_full_kg": round(spec.fuel_full_kg, 1),
        "fuel_half_kg": fuel_half,
        "payload_kg": round(payload, 1),
    }
