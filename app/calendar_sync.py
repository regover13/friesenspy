"""Lädt und parst den FriesenFlieger Google-Kalender (öffentlicher iCal-Feed)."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

ICAL_URL = (
    "https://calendar.google.com/calendar/ical/"
    "34pf9n1hci61gfbovjmhsa5qjc%40group.calendar.google.com/public/basic.ics"
)


async def fetch_and_parse_ical(client) -> list[dict]:
    """Holt den iCal-Feed und gibt Events als Dicts zurück.

    Überspringt Ganztags-Events (kein konkreter Zeitpunkt).
    Konvertiert alle Zeiten zu UTC.
    Extrahiert den ersten 4-buchstabigen ICAO-Code aus dem LOCATION-Feld.
    """
    from icalendar import Calendar  # lazy import — nur wenn gebraucht

    resp = await client.get(ICAL_URL, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    cal = Calendar.from_ical(resp.content)

    events: list[dict] = []
    for comp in cal.walk():
        if comp.name != "VEVENT":
            continue

        uid = str(comp.get("UID") or "")
        if not uid:
            continue

        summary = str(comp.get("SUMMARY") or "")
        dtstart_prop = comp.get("DTSTART")
        if not dtstart_prop:
            continue

        start_raw = dtstart_prop.dt
        # Ganztags-Events (date, nicht datetime) überspringen
        if isinstance(start_raw, date) and not isinstance(start_raw, datetime):
            continue

        # Zu UTC normalisieren
        if start_raw.tzinfo is None:
            start_dt = start_raw.replace(tzinfo=timezone.utc)
        else:
            start_dt = start_raw.astimezone(timezone.utc)

        end_str = ""
        dtend_prop = comp.get("DTEND")
        if dtend_prop:
            end_raw = dtend_prop.dt
            if isinstance(end_raw, datetime):
                if end_raw.tzinfo is None:
                    end_dt = end_raw.replace(tzinfo=timezone.utc)
                else:
                    end_dt = end_raw.astimezone(timezone.utc)
                end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        location_raw = str(comp.get("LOCATION") or "")
        icao_match = re.search(r'\b[A-Z]{4}\b', location_raw) or re.search(r'\b[A-Z]{4}\b', summary)
        icao = icao_match.group(0) if icao_match else ""

        events.append({
            "uid": uid,
            "summary": summary,
            "dtstart": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "dtend": end_str,
            "location": icao,
        })

    return events
