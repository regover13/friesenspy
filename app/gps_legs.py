"""Reiner, DB-freier GPS-Leg-Detektor für FriesenSpy.

Erkennt Flug-Etappen (Legs) allein aus einer ts-sortierten Positionsliste je Pilot —
ohne Flugplan, ohne Disconnect. Höhe (AGL) ist das Leitsignal, Groundspeed nur sekundär
(STOL/Heli fliegen langsam). Landung wird NUR an einem Flugplatz gewertet.

Die Airport-Auflösung wird injiziert (``nearest_airport`` / ``airport_elev_ft``), damit die
Funktion rein und testbar bleibt.
"""
from __future__ import annotations

from datetime import datetime

# Neue Schwellen (Design (A)). Höhe (AGL) ist das Leitsignal, Groundspeed sekundär.
_GPS_FLYING_GS_KT = 50       # sekundärer Abhebe-Helfer (nur wenn Höhe fehlt); NICHT 60
_GPS_GROUND_AGL_FT = 300     # AGL-Obergrenze für „am Boden" beim Landungs-Guard
_GPS_AIR_AGL_FT = 500        # AGL-Anstieg über Boden = abgehoben (Leitsignal)
_GPS_CLIMB_MIN_AGL_FT = 100  # Mindest-AGL für den sekundären „schnell + steigend"-Abhebe-Trigger
_GPS_BLOCK_GS_KT = 2         # Vollstopp-Schwelle (Touchdown-Kandidat)
# Spawn in der Luft (#49): manche StatSim-Aufzeichnungen beginnen erst im Climb-out direkt über
# dem Abflugplatz (kein Boden-Sample vorhanden). Liegt der erste Punkt im Platz-Umkreis UND
# darunter, gilt der Platz als Startplatz — PERMISSIV bei unbekannter Elevation (bewusst anders
# als der Landungs-Guard/#53, der dort konservativ NICHT rettet: ein zu spät bemerkter Startplatz
# ist harmlos falsch-positiv, eine zu Unrecht "gerettete" Landung wäre es nicht).
_GPS_SPAWN_MAX_AGL_FT = 1500
# Eine Landung am SELBEN Platz (X→X) wird nur dann als Zwischenlandung in den laufenden Flug
# absorbiert (Stop-and-Go / Platzrunde), wenn der nächste Start binnen dieser Zeit folgt.
# Sonst: Flug als X→X abschließen, ab dem nächsten Start ein neuer Flug.
# BEWUSST KLEIN gehalten (kein größeres „Backtrack"-Budget): Wird ein X→X absorbiert, zählt die
# Bodenzeit zwischen Landung und nächstem Start in ``duration_min`` als Flugzeit mit — genau der
# Fehler, den v8.1.0 behebt (Reiner 41 min). Die beiden Fehlerrichtungen sind asymmetrisch: zu
# klein → ein langer Taxi-Back wird in zwei Platzrunden-Flüge getrennt (kosmetisch); zu groß →
# echte Pause wird als Flugzeit verschluckt (Korrektheitsfehler). Darum lieber knapp. Gemessen
# wird Vollstopp → Takeoff-TRIGGER des nächsten Legs (nicht das Losrollen); die Trigger-Latenz
# zehrt einen Teil des Budgets auf, das ist als konservativ gewollt.
_GPS_STOP_AND_GO_MAX_SEC = 300


def _parse_ts(ts: str) -> datetime:
    """ISO8601-UTC-String (…Z) → datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _update_max(cur: int | None, alt: int | None) -> int | None:
    """Max-Höhe über den Leg fortschreiben (None-tolerant)."""
    if alt is None:
        return cur
    if cur is None:
        return alt
    return max(cur, alt)


def _split_on_gaps(positions: list[dict], gap_minutes: int) -> list[list[dict]]:
    """Zeitlich sortieren und an Lücken > ``gap_minutes`` in Segmente teilen."""
    if not positions:
        return []
    ordered = sorted(positions, key=lambda p: p.get("ts", ""))
    segments: list[list[dict]] = []
    current: list[dict] = [ordered[0]]
    for pos in ordered[1:]:
        try:
            dt_prev = _parse_ts(current[-1]["ts"])
            dt_curr = _parse_ts(pos["ts"])
            if (dt_curr - dt_prev).total_seconds() / 60 > gap_minutes:
                segments.append(current)
                current = []
        except Exception:
            pass
        current.append(pos)
    if current:
        segments.append(current)
    return segments


def detect_gps_legs(
    positions: list[dict],
    *,
    nearest_airport,      # callable(lat, lon, max_km) -> icao str | None
    airport_elev_ft,      # callable(icao) -> elevation ft (float) | None
    radius_km: float = 10.0,
    gap_minutes: int = 30,
    rescue_before: str | None = None,
) -> list[dict]:
    """Erkennt Flug-Etappen aus GPS-Positionen (rein, DB-frei).

    ``positions``: Liste von Dicts mit ``ts`` (ISO8601-UTC), ``latitude``, ``longitude``,
    ``altitude`` (ft MSL, ggf. None), ``groundspeed`` (kt, ggf. None). Wird intern sortiert.

    Zustandsmaschine ON_GROUND → AIRBORNE → ON_GROUND. Die Landung wird SOFORT am Touchdown-
    Sample finalisiert (kein Dwell/LANDED-Zwischenzustand mehr) — jedes erneute Abheben ist
    ein neuer Roh-Leg über die normale, verankerte ON_GROUND-Erkennung. Jeder Leg ist ein
    Dict mit den Keys ``dep_icao, arr_icao, takeoff_ts, landing_ts, complete, dep_source,
    arr_source, max_altitude`` plus ``segment`` (0-basierter Index des Zeit-Segments, das
    ``detect_gps_legs`` nach Gaps > ``gap_minutes`` bildet). Rückgabe: Legs in chronologischer
    Reihenfolge.

    ``rescue_before`` (#53): ISO8601-UTC-String oder ``None``. Endet ein Segment airborne (Track
    riss ab, KEINE Landung unter der ``_GPS_BLOCK_GS_KT``-Schwelle gefunden), wird das Leg trotzdem
    als gelandet gewertet, wenn der letzte Punkt im Platz-Umkreis UND unter ``_GPS_GROUND_AGL_FT``
    liegt — sofern die Rettung zeitlich erlaubt ist: ``None`` erlaubt sie immer (StatSim-
    Aufzeichnungsende ist immer ein echtes Ende), ein Timestamp erlaubt sie nur, wenn der letzte
    Sample ÄLTER ist (Live-Guard — ein gerade laufender Anflug darf nicht fälschlich geschlossen
    werden). ISO-Strings sind lexikografisch vergleichbar, ein einfacher String-Vergleich pro
    Segment genügt (frühere Segmente enden ohnehin >``gap_minutes`` vor jedem folgenden).
    """
    legs: list[dict] = []
    # Segmentierung nach Zeitlücken implementiert die Gap-Regeln direkt: ein Segment-Ende
    # ist zugleich ein Gap-Ende (offen airborne → incomplete; tentativ gelandet → complete).
    for seg_index, segment in enumerate(_split_on_gaps(positions, gap_minutes)):
        seg_legs = _detect_segment(
            segment, nearest_airport, airport_elev_ft, radius_km, rescue_before=rescue_before
        )
        for leg in seg_legs:
            leg["segment"] = seg_index
        legs.extend(seg_legs)
    return legs


def _detect_segment(
    samples: list[dict],
    nearest_airport,
    airport_elev_ft,
    radius_km: float,
    *,
    rescue_before: str | None = None,
) -> list[dict]:
    """Zustandsmaschine für ein einzelnes (lückenfreies) Segment."""
    if not samples:
        return []

    legs: list[dict] = []

    state = "INIT"
    ground_ref_ft: int | None = None   # Höhe am letzten Boden-Sample (Takeoff-Referenz)
    prev_alt: int | None = None        # Höhe des Vor-Samples am Boden (für „steigend"-Prüfung)
    dep_icao: str | None = None
    dep_source: str | None = None
    takeoff_ts: str | None = None
    max_alt: int | None = None
    land_ts: str | None = None
    land_arr: str | None = None
    # Beginn der AKTUELLEN Boden-/Rollphase und der Platz, an dem sie läuft. Die Phase startet
    # neu, sobald der Detektor am Boden einen ANDEREN Platz erkennt (Reconnect/Platzwechsel) —
    # damit ist der Rollbeginn an denselben Nachweis gebunden wie der Startplatz selbst.
    ground_since_ts: str | None = None
    ground_icao: str | None = None
    taxi_start_ts: str | None = None   # Rollbeginn des laufenden Legs (beim Abheben eingefroren)

    def emit_complete() -> None:
        legs.append({
            "dep_icao": dep_icao,
            "arr_icao": land_arr,
            "takeoff_ts": takeoff_ts,
            "taxi_start_ts": taxi_start_ts,
            "landing_ts": land_ts,
            "complete": True,
            "dep_source": dep_source,
            "arr_source": "gps",
            "max_altitude": max_alt,
        })

    def emit_incomplete() -> None:
        legs.append({
            "dep_icao": dep_icao,
            "arr_icao": None,
            "takeoff_ts": takeoff_ts,
            "taxi_start_ts": taxi_start_ts,
            "landing_ts": None,
            "complete": False,
            "dep_source": dep_source,
            "arr_source": None,
            "max_altitude": max_alt,
        })

    for s in samples:
        ts = s.get("ts")
        lat = s.get("latitude")
        lon = s.get("longitude")
        alt = s.get("altitude")
        gs = s.get("groundspeed")

        if state == "INIT":
            if gs is not None and gs >= _GPS_FLYING_GS_KT:
                # Spawn-in-der-Luft: keine Boden-Referenz. Trotzdem NICHT bedingungslos dep=None
                # (#49) — liegt der erste Punkt im Platz-Umkreis (typisch: StatSim-Aufzeichnung
                # beginnt erst im Climb-out direkt über dem Abflugplatz), zählt dieser Platz als
                # Startplatz. Permissiv bei unbekannter Elevation (Kommentar bei der Konstante).
                state = "AIRBORNE"
                ap = nearest_airport(lat, lon, radius_km)
                dep_ok = False
                if ap is not None:
                    elev = airport_elev_ft(ap)
                    dep_ok = alt is None or elev is None or (alt - elev) < _GPS_SPAWN_MAX_AGL_FT
                dep_icao = ap if dep_ok else None
                dep_source = "gps" if dep_ok else None
                takeoff_ts = ts
                taxi_start_ts = None   # Spawn in der Luft: es gab keine Rollphase
                max_alt = _update_max(None, alt)
            else:
                state = "ON_GROUND"
                ground_ref_ft = alt
                prev_alt = alt   # Boden-Referenz seeden, damit der gs+steigend-Trigger schon
                                 # ab dem nächsten Sample greifen kann (M1)
                dep_icao = nearest_airport(lat, lon, radius_km)
                dep_source = "gps" if dep_icao else None
                ground_since_ts = ts
                ground_icao = dep_icao
            continue

        if state == "ON_GROUND":
            # Abheben prüfen: HÖHE ist das Leitsignal (STOL/Heli fliegen langsam), Groundspeed
            # nur als sekundärer Trigger UND nur mit Steig-Nachweis (sonst würde ein Startlauf/
            # abgebrochener Start bei gs>50 fälschlich als Abheben zählen — Geisterflug).
            took_off = False
            if alt is not None and ground_ref_ft is not None:
                agl = alt - ground_ref_ft
                climbing = (
                    agl > _GPS_CLIMB_MIN_AGL_FT
                    and prev_alt is not None and alt > prev_alt
                )
                took_off = (
                    agl > _GPS_AIR_AGL_FT
                    or (gs is not None and gs > _GPS_FLYING_GS_KT and climbing)
                )
            else:
                # Höhe nicht verfügbar → Groundspeed als sekundärer Helfer.
                took_off = gs is not None and gs > _GPS_FLYING_GS_KT

            if took_off:
                state = "AIRBORNE"
                takeoff_ts = ts
                # dep_icao/dep_source stammen aus dem Boden-Cluster (bereits getrackt).
                taxi_start_ts = ground_since_ts
                max_alt = _update_max(None, alt)
                prev_alt = None
            else:
                # Weiter am Boden: dep-Kandidat aktualisieren. Die Boden-Referenz bleibt auf
                # der Feldhöhe verankert (Minimum) — sie darf NICHT mit dem Steigflug mit-
                # klettern, sonst bleibt (alt − ground_ref_ft) immer nur ein Sample-Schritt
                # und ein normal steigendes Flugzeug (~200 ft/Sample) überschreitet die
                # 500-ft-Schwelle nie → es würde nie ein Abheben erkannt.
                if alt is not None:
                    ground_ref_ft = alt if ground_ref_ft is None else min(ground_ref_ft, alt)
                dep_icao = nearest_airport(lat, lon, radius_km)
                dep_source = "gps" if dep_icao else None
                # Steht das Flugzeug plötzlich an einem ANDEREN Platz, war das kein Rollen,
                # sondern ein Reconnect — die Rollphase beginnt dort neu. Nur zwischen zwei
                # ERKANNTEN Plätzen umschalten: ein einzelnes Sample ohne Platz im Umkreis
                # (weite Vorfelder) darf die laufende Rollphase nicht zerschneiden.
                if dep_icao is not None:
                    if ground_icao is not None and dep_icao != ground_icao:
                        ground_since_ts = ts
                    ground_icao = dep_icao
                if ground_since_ts is None:
                    ground_since_ts = ts
                prev_alt = alt   # Höhe dieses Boden-Samples für die nächste „steigend"-Prüfung
            continue

        if state == "AIRBORNE":
            max_alt = _update_max(max_alt, alt)
            # Touchdown-Kandidat: Vollstopp + Platz im Umkreis + AGL-Guard.
            if gs is not None and gs < _GPS_BLOCK_GS_KT:
                ap = nearest_airport(lat, lon, radius_km)
                if ap is not None:
                    agl_ok = True
                    elev = airport_elev_ft(ap)
                    if alt is not None and elev is not None:
                        agl_ok = (alt - elev) < _GPS_GROUND_AGL_FT
                    if agl_ok:
                        # Landung SOFORT endgültig (kein Dwell/LANDED): emit + zurück ON_GROUND.
                        land_ts = ts
                        land_arr = ap
                        emit_complete()
                        state = "ON_GROUND"
                        ground_ref_ft = alt
                        prev_alt = alt
                        dep_icao = ap
                        dep_source = "gps"
                        takeoff_ts = None
                        # Neue Rollphase ab dem Aufsetzer: der Turnaround gehört zum FOLGE-Leg,
                        # die Rollphase davor ist mit diesem Leg abgeschlossen.
                        ground_since_ts = ts
                        ground_icao = ap
                        taxi_start_ts = None
                        max_alt = None
                        land_ts = None
                        land_arr = None
            # Kein Platz / AGL-Guard verletzt → bleibt AIRBORNE (Absturz/Hover nie als Landung).
            continue

    # Segment-Ende (= Ende oder Gap): offene Zustände finalisieren.
    if state == "AIRBORNE":
        # Landungs-Rettung (#53): Track riss ab, BEVOR die reguläre gs<2-Touchdown-Erkennung
        # greifen konnte — z. B. StatSim-Aufzeichnungsende oder FriesenSpy-Disconnect kurz vor
        # dem Vollstopp. War der letzte Punkt trotzdem tief über einem Platz, ist der Flug dort
        # nachweislich beendet (Absturz vs. sauberer Aufsetzer ist aus GPS nicht unterscheidbar,
        # aber für die Zwecke hier irrelevant — "an diesem Platz beendet" stimmt so oder so).
        # KONSERVATIV bei unbekannter Elevation/Höhe: keine Rettung (bewusst anders als der
        # Spawn-Guard/#49, s. Kommentar dort).
        rescued = False
        last = samples[-1]
        last_ts = last.get("ts")
        rescue_allowed = rescue_before is None or (last_ts is not None and last_ts < rescue_before)
        if rescue_allowed:
            last_lat, last_lon, last_alt = last.get("latitude"), last.get("longitude"), last.get("altitude")
            ap = nearest_airport(last_lat, last_lon, radius_km) if last_lat is not None and last_lon is not None else None
            if ap is not None:
                elev = airport_elev_ft(ap)
                if elev is not None and last_alt is not None and (last_alt - elev) < _GPS_GROUND_AGL_FT:
                    land_ts = last_ts
                    land_arr = ap
                    emit_complete()
                    rescued = True
        if not rescued:
            # Rein in der Luft beendet → unvollständiger Leg (Disconnect mid-air).
            emit_incomplete()
    # ON_GROUND/INIT: nie abgehoben → kein Leg (Ghost strukturell gefiltert).

    return legs


def collapse_same_airport(legs: list[dict]) -> list[dict]:
    """Verschmilzt aufeinanderfolgende Roh-Legs am SELBEN Platz zu Flügen (Spec A).
    Ein Flug = Abheben an X → Landung am nächsten ANDEREN Platz (oder offen). Wiederholte
    Landungen am selben Platz zählen als EINE Landung, ABER nur solange der nächste Start binnen
    ``_GPS_STOP_AND_GO_MAX_SEC`` folgt (Stop-and-Go); nach einer längeren Bodenpause wird der Flug
    als X→X abgeschlossen und ab dem nächsten Start beginnt ein neuer Flug. Segment-Wechsel
    trennt immer."""
    flights: list[dict] = []
    cur: dict | None = None
    cur_seg: int | None = None
    pending_same_landing: str | None = None  # letzte Same-Airport-Landung (falls Flug am Boden endet)

    for i, leg in enumerate(legs):
        seg = leg.get("segment", 0)
        if cur is not None and seg != cur_seg:
            _close_ground(flights, cur, pending_same_landing)
            cur = None
            pending_same_landing = None
        if cur is None:
            cur = {
                "dep_icao": leg.get("dep_icao"),
                "dep_source": leg.get("dep_source"),
                "takeoff_ts": leg.get("takeoff_ts"),
                # Rollbeginn des ERSTEN Legs der Gruppe — bei Stop-and-Go ist das der Rollbeginn
                # des zusammengefassten Fluges (analog takeoff_ts).
                "taxi_start_ts": leg.get("taxi_start_ts"),
                "max_altitude": leg.get("max_altitude"),
            }
            cur_seg = seg
            pending_same_landing = None
        else:
            cur["max_altitude"] = _update_max(cur["max_altitude"], leg.get("max_altitude"))

        arr = leg.get("arr_icao")
        if not leg.get("complete") or arr is None:
            flights.append({**cur, "arr_icao": None, "landing_ts": None,
                            "complete": False, "arr_source": None})
            cur = None
            pending_same_landing = None
            continue
        if arr == cur["dep_icao"]:
            # Platzrunde/X→X: nur absorbieren (Stop-and-Go), wenn der nächste Leg desselben
            # Segments kurz nach dieser Landung startet. Sonst = echte Bodenpause → Flug hier
            # als X→X abschließen und ab dem nächsten Start neu beginnen (#v8.1.0).
            nxt = legs[i + 1] if i + 1 < len(legs) else None
            same_seg_next = nxt is not None and nxt.get("segment", 0) == cur_seg
            if same_seg_next and _within_stop_and_go(leg.get("landing_ts"), nxt.get("takeoff_ts")):
                pending_same_landing = leg.get("landing_ts")   # Stop-and-Go → absorbieren
                continue
            flights.append({**cur, "arr_icao": cur["dep_icao"], "landing_ts": leg.get("landing_ts"),
                            "complete": True, "arr_source": "gps"})
            cur = None
            pending_same_landing = None
            continue
        flights.append({**cur, "arr_icao": arr, "landing_ts": leg.get("landing_ts"),
                        "complete": True, "arr_source": leg.get("arr_source")})
        cur = None
        pending_same_landing = None

    if cur is not None:
        _close_ground(flights, cur, pending_same_landing)
    return flights


def _within_stop_and_go(landing_ts: str | None, takeoff_ts: str | None) -> bool:
    """True, wenn zwischen einer X→X-Landung und dem nächsten Start ≤ ``_GPS_STOP_AND_GO_MAX_SEC``
    liegen (= Stop-and-Go, absorbieren). Fehlende/nicht parsbare Zeitstempel → True (konservativ
    absorbieren, unverändertes Alt-Verhalten für degenerierte Eingaben)."""
    if not landing_ts or not takeoff_ts:
        return True
    try:
        gap = (_parse_ts(takeoff_ts) - _parse_ts(landing_ts)).total_seconds()
    except Exception:
        return True
    return gap <= _GPS_STOP_AND_GO_MAX_SEC


def _close_ground(flights: list[dict], cur: dict, pending_same_landing: str | None) -> None:
    if pending_same_landing is not None:
        flights.append({**cur, "arr_icao": cur["dep_icao"], "landing_ts": pending_same_landing,
                        "complete": True, "arr_source": "gps"})
    else:
        flights.append({**cur, "arr_icao": None, "landing_ts": None,
                        "complete": False, "arr_source": None})
