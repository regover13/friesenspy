"""Telegram-Alert-System für FriesenSpy — Benachrichtigungen wenn Friesen online gehen."""
from __future__ import annotations

import html
import logging

import httpx

logger = logging.getLogger(__name__)


def format_online_message(
    pilot_name: str,
    callsign: str,
    departure: str,
    arrival: str,
) -> str:
    """
    Formatiert eine Telegram-Nachricht wenn ein Friese online geht.

    Args:
        pilot_name: Name des Piloten (str)
        callsign: Flugzeug-Callsign (str)
        departure: Abflugflughafen ICAO-Code (str, kann leer sein)
        arrival: Zielflughafen ICAO-Code (str, kann leer sein)

    Returns:
        Formatierte Nachricht für Telegram.
        Beispiel-Output:
        "✈️ FRS001 ist jetzt online!\nPilot: Max Mustermann\nRoute: EDDH → EDDF"

        Falls departure oder arrival leer: Route-Zeile angepasst oder weggelassen.
    """
    lines = [
        f"✈️ {html.escape(callsign)} ist jetzt online!",
        f"Pilot: {html.escape(pilot_name)}",
    ]

    # Route-Zeile nur hinzufügen falls mindestens ein Flughafen angegeben
    if departure or arrival:
        dep_display = html.escape(departure) if departure else "?"
        arr_display = html.escape(arrival) if arrival else "?"
        lines.append(f"Route: {dep_display} → {arr_display}")

    return "\n".join(lines)


async def send_telegram_alert(
    message: str,
    token: str,
    chat_id: str,
    client: httpx.AsyncClient,
) -> None:
    """
    Sendet eine Nachricht an Telegram via httpx.post.

    Args:
        message: Die zu sendende Nachricht (str)
        token: Telegram Bot-Token (str)
        chat_id: Telegram Chat-ID (str)
        client: httpx.AsyncClient für die HTTP-Anfrage

    Returns:
        None

    Notes:
        - Silent fail wenn token oder chat_id leer/None: einfach return ohne Exception
        - HTTP-Fehler werden geloggt (logging.warning) aber NICHT weitergeworfen
        - URL: https://api.telegram.org/bot{token}/sendMessage
        - Payload: {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    """
    # Silent fail wenn Token nicht konfiguriert
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = await client.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        # Nur Exception-Typ loggen — die URL enthält den Bot-Token
        logger.warning("Failed to send Telegram alert: %s", type(e).__name__)
