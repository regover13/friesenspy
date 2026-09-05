"""Lädt und parst den FriesenFlieger Google-Kalender (öffentlicher iCal-Feed)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

ICAL_URL = (
    "https://calendar.google.com/calendar/ical/"
    "34pf9n1hci61gfbovjmhsa5qjc%40group.calendar.google.com/public/basic.ics"
)

_ICAO_RE = re.compile(r"\b[A-Z]{4}\b")

# Wörter, die zwar auf die 4-Großbuchstaben-Regel passen, aber nie ein echter ICAO-Code sind
# — typischerweise ein Label/Präfix im Kalendertext (z. B. "ICAO: EDVE, EDBH" oder "Ziel:
# ICAO EDVE, EDBH"), das sonst fälschlich als eigener Streckenflugplatz mit in die Strecke
# aufgenommen würde (Live-Fund: mehrere "Montagsflüge"-Termine zeigten "ICAO,EDVE,EDBH" statt
# "EDVE,EDBH").
_ROUTE_STOPWORDS = {"ICAO"}

# Plausibilitäts-Obergrenze: eine Bummel-Strecke liegt real bei <200 nm, praktisch nie über
# 600 nm. Ein größerer Abstand zwischen zwei Streckenflugplätzen deutet auf einen falsch als
# ICAO erkannten Begriff (ein 4-Buchstaben-Wort, das anderswo ein echter Flughafen ist) →
# dann NICHT als Bummel aktivieren. 600 nm × 1.852 = 1111.2 km.
_MAX_BUMMEL_SPAN_KM = 600 * 1.852


def _route_is_plausible(route: list[str]) -> bool:
    """True, wenn alle auflösbaren Streckenflugplätze innerhalb von ~600 nm zueinander liegen.

    Nicht auflösbare ICAOs werden ignoriert (permissiv). Erst ein Paar jenseits der Grenze
    macht die Strecke unplausibel.
    """
    from app.geo import haversine, icao_to_coords  # lazy: vermeidet Import-Kosten/Zyklen

    coords = [c for c in (icao_to_coords(icao) for icao in route) if c is not None]
    for i in range(len(coords)):
        for j in range(i + 1, len(coords)):
            if haversine(coords[i][0], coords[i][1], coords[j][0], coords[j][1]) > _MAX_BUMMEL_SPAN_KM:
                return False
    return True


def _marker_place_ok(code: str, base: list[str]) -> bool:
    """#84: ein Fracht-Marker-Startplatz kommt nur in die Route, wenn er auflösbar ist UND innerhalb
    ``_MAX_BUMMEL_SPAN_KM`` zu jedem auflösbaren Basis-Platz liegt — Tippfehler-Schutz: ein ferner
    Falsch-ICAO wird verworfen (degradiert später nur seine Fracht-Zeile auf geteilt), statt die
    Route/das Event zu sprengen. Basis leer/nicht auflösbar → permissiv (True)."""
    from app.geo import haversine, icao_to_coords  # lazy
    c = icao_to_coords(code)
    if c is None:
        return False
    for b in base:
        bc = icao_to_coords(b)
        if bc and haversine(c[0], c[1], bc[0], bc[1]) > _MAX_BUMMEL_SPAN_KM:
            return False
    return True


# Optionale Startplatz-LISTE direkt am Marker (#84): ``Fracht EDDW, EDWG: …`` bindet die Fracht an
# {EDDW, EDWG}, ``Fracht: …`` bleibt geteilt. Gruppe 1 = ICAO-Liste (optional), Gruppe 2 = Frachtliste.
_CARGO_MARKER_RE = re.compile(
    r"fracht(?:\s+([A-Za-z]{4}(?:\s*,\s*[A-Za-z]{4})*))?\s*:\s*(.+)", re.IGNORECASE
)
_CARGO_ITEM_RE = re.compile(r"^([\d]+(?:[.,]\d+)?)\s*(?:kg\s+)?(.+)$", re.IGNORECASE)


def parse_cargo_lines(description: str) -> list[dict]:
    """Fracht-Zeilen aus der Kalender-Beschreibung lesen (Marker ``Fracht <ICAO>:``).

    Beispiel: ``"Fracht EDWG: 1000 Krabbenbrötchen, 500 Friesentee"`` →
    ``[{"name": "Krabbenbrötchen", "target_kg": 1000.0, "departure": "EDWG"},
       {"name": "Friesentee", "target_kg": 500.0, "departure": "EDWG"}]``.
    Entscheidung 6 (Task 11): der Marker braucht GENAU EINEN Startplatz. ``Fracht:`` ohne ICAO
    (früher „geteilt") und ``Fracht EDWG, EDWZ:`` (mehrere) werden ABGEWIESEN (leere Rückgabe).
    Nur die erste Zeile nach dem Marker wird gelesen. Frachtnamen werden beim Speichern gegen den
    Katalog abgeglichen (Emoji/Kappung); unbekannte Namen werden als Freitext übernommen.
    Mehrere Frachtarten werden durch ``", "`` (Komma+Leerzeichen) getrennt — ein Komma ohne
    Leerzeichen (z. B. ``"250,5"``) gilt als Dezimalkomma und trennt nicht.
    """
    if not description:
        return []
    out: list[dict] = []
    for m in _CARGO_MARKER_RE.finditer(description):
        # Startplatz am Marker — normalisiert (upper, dedup, sortiert).
        raw = m.group(1)
        dep = ",".join(sorted({c.strip().upper() for c in raw.split(",") if c.strip()})) if raw else None
        # Entscheidung 6 (Task 11): genau EIN Platz je Zeile. Ohne ICAO (früher „geteilter Topf")
        # oder mit mehreren wird die Zeile ABGEWIESEN, statt still eine ortlose Zeile anzulegen —
        # der Kalender-Sync meldet den Fehler dann am Event.
        if not dep or "," in dep:
            continue
        rest = m.group(2)                          # `.+` matcht bereits nur bis zum Zeilenende
        for chunk in re.split(r",\s+", rest):
            im = _CARGO_ITEM_RE.match(chunk.strip())
            if not im:
                continue
            try:
                kg = float(im.group(1).replace(",", "."))
            except ValueError:
                continue
            name = im.group(2).strip()
            if name and kg > 0:
                item = {"name": name, "target_kg": kg}
                if dep:
                    item["departure"] = dep
                out.append(item)
    return out


def parse_route(location: str, summary: str, description: str = "") -> tuple[str, bool, bool]:
    """Strecke + Bummel-/FriesenKutter-Flag aus einem Termin ableiten.

    Sammelt alle ICAO-Codes (vier Großbuchstaben) aus ``location``, dann ``summary``, dann
    ``description`` — Reihenfolge erhaltend und dedupliziert → CSV (z. B. ``"EDWF,EDWG,EDWR"``).
    Das Wort ``"ICAO"`` selbst wird ausgeschlossen (``_ROUTE_STOPWORDS``) — es matcht zwar die
    4-Großbuchstaben-Regel, ist aber kein echter Flugplatz, sondern typischerweise ein Label
    im Kalendertext (z. B. ``"ICAO: EDVE, EDBH"``).
    ``is_bummel`` ist True, wenn ``"bummel"`` (case-insensitiv) im Titel ODER in der Beschreibung
    steht UND die Strecke mindestens zwei Flugplätze hat. Analog ist ``is_transport`` True, wenn
    ``"friesenkutter"`` (der FriesenKutter-Marker) im Titel/Beschreibung steht — dann wird das
    Transportevent freigeschaltet. Die Beschreibung wird mit ausgewertet, damit ein Marker auch
    erkannt wird, wenn er nur dort steht.
    """
    # Basis-Route (#84): ICAOs aus location/summary/description OHNE die Fracht-Marker-Zeilen. Die
    # Plausibilität wird NUR hieraus berechnet — ein ferner Marker-Tippfehler darf das Event nicht
    # via Distanzprüfung deaktivieren (Fable-Fund).
    desc_for_route = _CARGO_MARKER_RE.sub("", description or "")
    base: list[str] = []
    for text in (location or "", summary or "", desc_for_route):
        for code in _ICAO_RE.findall(text):
            if code not in _ROUTE_STOPWORDS and code not in base:
                base.append(code)
    plausible = len(base) >= 2 and _route_is_plausible(base)
    # Gültige Fracht-Marker-Startplätze (#84) in die Route aufnehmen — nur auflösbar UND nah genug
    # (Tippfehler-Schutz). Einfügen VOR dem letzten Basis-Platz, damit _default_destination weiter
    # den mutmaßlichen Zielplatz am Routenende trifft.
    extra: list[str] = []
    for m in _CARGO_MARKER_RE.finditer(description or ""):
        for code in _ICAO_RE.findall(m.group(1) or ""):
            if code not in _ROUTE_STOPWORDS and code not in base and code not in extra \
                    and _marker_place_ok(code, base):
                extra.append(code)
    route = (base[:-1] + extra + base[-1:]) if (extra and base) else (base + extra)
    text_lc = (summary or "").lower() + "\n" + (description or "").lower()
    is_bummel = "bummel" in text_lc and plausible
    is_transport = "friesenkutter" in text_lc and plausible
    return ",".join(route), is_bummel, is_transport


async def fetch_and_parse_ical(client) -> list[dict]:
    """Holt den iCal-Feed und gibt Events als Dicts zurück (Netzwerk; Parsing in
    :func:`parse_ical_bytes`)."""
    resp = await client.get(ICAL_URL, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    return parse_ical_bytes(resp.content)


def parse_ical_bytes(content: bytes) -> list[dict]:
    """Parst rohe iCal-Bytes zu Event-Dicts (netzwerkfrei, testbar).

    Expandiert RRULE-Wiederholungen im Fenster 365 Tage zurück bis 90 Tage voraus.
    Extrahiert den ersten ICAO-Code aus LOCATION, sonst aus SUMMARY.

    #19 (05.09.2026): Hier wird **nichts mehr am Stichwort verworfen**. Bis dahin flog jeder
    Termin mit „kutter" im Text raus — auch dann, wenn niemand einen Kutter angelegt hatte, und
    der Abend war komplett unsichtbar. Ob ein Termin zu einem Event-Objekt gehört, steht seither
    in ``bummel_races.calendar_uid`` / ``transport_events.calendar_uid`` und wird im Admin von
    Hand ausgesprochen. Dass aus einem Termin trotzdem kein Kutter **entsteht** (Variante ①,
    20.07.2026), entscheidet der Poller in ``_sync_calendar``.
    """
    import recurring_ical_events  # lazy import
    from icalendar import Calendar  # lazy import

    cal = Calendar.from_ical(content)

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=365)
    window_end = now + timedelta(days=90)

    occurrences = recurring_ical_events.of(cal).between(window_start, window_end)

    events: list[dict] = []
    for comp in occurrences:
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
        if not isinstance(start_raw, datetime):
            continue
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
        description_raw = str(comp.get("DESCRIPTION") or "")
        route, is_bummel, is_transport = parse_route(location_raw, summary, description_raw)
        # location bleibt der erste ICAO (Rückwärtskompatibilität: Event-Suche-Prefill).
        icao = route.split(",")[0] if route else ""

        # Zusammengesetzter UID damit jede Wiederholung separat gespeichert wird
        dtstart_compact = start_dt.strftime("%Y%m%dT%H%M%SZ")
        synthetic_uid = f"{uid}_{dtstart_compact}"

        events.append({
            "uid": synthetic_uid,
            "summary": summary,
            "dtstart": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "dtend": end_str,
            "location": icao,
            "route": route,
            "is_bummel": 1 if is_bummel else 0,
            "is_transport": 1 if is_transport else 0,
            "cargo": parse_cargo_lines(description_raw) if is_transport else [],
        })

    return events
