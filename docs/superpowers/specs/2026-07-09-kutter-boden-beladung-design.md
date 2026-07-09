# FriesenKutter — GPS-only Boden-Beladung am Abholplatz (#5)

**Datum:** 2026-07-09
**Status:** abgenommen (Design), bereit für writing-plans
**Scope:** Paket C, Teil 1 (allein). #4 Milchmann-Tour ist ein eigener, späterer Design-Zyklus.

## Problem

Ein FriesenKutter-Pilot, der am **Abholplatz am Boden** steht (verbunden, noch nicht
abgehoben), erscheint in der Live-Kutter-Ansicht heute **gar nicht** — er wird erst
sichtbar, wenn der GPS-Leg-Detektor ein abgehobenes Leg erkennt („erst beim Start").

**Root Cause** (`app/database.py`, Offen-Flug-Zweig ~5297–5312): Für einen noch nicht
abgehobenen Piloten (`current_leg is None`) wird der Startplatz `dep` so aufgelöst:

```
dep = current_leg.departure            # None, solange nicht abgehoben
      or _nearest_airport(_first_pos)  # ERSTE Position der Verbindung, nicht die aktuelle
      or f.departure                   # gefilter Flugplan  ← Prinzipbruch
```

Beide Fallbacks sind unzuverlässig:
- `_first_pos` ist die **erste** Position der Verbindung. Begann die Verbindung woanders
  (Mehr-Leg-Verbindung ohne Disconnect), zeigt sie nicht den aktuellen Standplatz.
- Der **Flugplan** wird seit #23 (v8.0.0, GPS-only) bewusst nicht getraut. Ein stehen­
  gebliebener alter Plan (Live-Test 09.07.: `EDXP→EDWK`, während der Pilot real in
  Helgoland EDXH stand) liefert einen `dep`, der nicht als aktueller Abholplatz erkannt
  wird → der Pilot fällt durch `if dep not in route_set` und wird per `continue`
  übersprungen.

## Ziel

**GPS-only, ausschließlich die aktuelle Boden-Position zählt.** Ein verbundener
FRS-Pilot, der **am Boden** (`groundspeed < _BLOCK_GS_KT`) im Abhol-Radius eines
Streckenplatzes (≠ Ziel) steht, erscheint mit reservierter Fracht und Status
**„🅿️ lädt in <Platz>"** — unabhängig vom (auch veralteten) Flugplan und unabhängig
davon, wo die Verbindung begann.

## Nicht-Ziele (YAGNI)

- Keine Änderung der Leg-Erkennung, der Verlust-Logik oder der Lieferungs-Latches.
- Keine Milchmann-Akkumulation (#4).
- Kein neuer Trigger über den Flugplan (widerspräche GPS-only).

## Entwurf

### 1. Datenquelle: aktuelle Live-Position

Neuer kleiner Helfer in `app/database.py`:

```python
def _current_pos(conn, cid) -> tuple[float, float, float] | None:
    """(lat, lon, groundspeed) der AKTUELLEN Live-Position, oder None."""
```

Liest `SELECT latitude, longitude, groundspeed FROM live_positions WHERE cid = ?`.
`live_positions` ist dieselbe Quelle wie `check_live_arrival` /
`_returning_pilot_landed` — eine Zeile je aktuell verbundener CID.

### 2. `dep`-Auflösung im geparkten Fall (GPS-only)

Im Offen-Flug-Zweig (`compute_transport_progress`) wird die `dep`-Ableitung für den
**nicht abgehobenen** Piloten ersetzt:

```
dep = current_leg.departure                         # abgehoben → GPS-Leg-Start (unverändert)
      or _nearest_airport(coords_map, current_pos)  # am Boden → nächster Streckenplatz zur AKTUELLEN Position
# KEIN Flugplan-Fallback mehr
```

- `coords_map`/`radius` existieren in der Funktion bereits (`radius = _BUMMEL_AIRPORT_RADIUS_KM`).
- `current_pos` = `(lat, lon)` aus `_current_pos`; nur verwenden, wenn `groundspeed < _BLOCK_GS_KT`
  (am Boden). Ist der Pilot in der Luft, greift ohnehin `current_leg` (abgehobenes Leg).
- Löst nichts auf (nicht am Boden an einem Abholplatz) → wie bisher `continue` (unsichtbar).

Der bestehende `airborne = current_leg is not None` bleibt: geparkt → `airborne False`,
abgehoben → `True`. `in_air` (offene Reservierung Richtung Ziel) bleibt `True`, sodass
das Frontend den Piloten zeigt.

### 3. Frontend-Status

`app/static/index.html`, Live-Banner (`fetchKutterActive`) und Kutter-Detail: der
Status für den geparkten, reservierten Fall (`!f.loaded && !f.airborne`) wird von
`🅿️ am Start` auf **`🅿️ lädt in <dep>`** geändert (Ort = `f.dep`). Alle anderen
Status (`✅ angekommen`, `✈️ unterwegs`, `↩️ Rückflug`) unverändert. Die Strecke-Spalte
(Ladeplatz → Ziel) zeigt den Ort ohnehin bereits.

## Abgrenzung / Edge Cases

| Situation | Verhalten |
|---|---|
| Am Boden am Abholplatz (≠ Ziel) | **„🅿️ lädt in <Platz>"** + reservierte Fracht |
| Am Boden am **Ziel** | keine Beladung — Liefer-/Rückflug-Logik unverändert (`dep == dest` ausgeschlossen) |
| Am Boden **off-route** | `_nearest_airport` = None → nicht gezeigt (wie bisher) |
| In der Luft | `current_leg` greift → „✈️ unterwegs" (unverändert) |
| Noch keine `live_positions`-Zeile | nicht gezeigt, bis die erste Position eintrifft |
| Veralteter/fremder Flugplan | **irrelevant** — Plan wird nicht mehr gelesen |

## Testplan (`tests/test_transport.py`)

Mit synthetischen `live_positions` + offenen Flügen (`open_transport_flights`-Pfad):

1. **Geparkt am Abholplatz, kein/alter Plan → sichtbar als ladend.** Position am Boden
   im Radius von EDXH, Flugplan `dep=EDXP` (falsch/alt). Erwartung: Flug erscheint mit
   `dep == "EDXH"`, `airborne == False`, `reserved_kg > 0`. Beweist: Plan bestimmt `dep`
   nicht mehr; die Live-Position gewinnt.
2. **Geparkt am Ziel → nicht ladend.** Position am Boden im Radius von EDWG (= dest):
   nicht als ladend im Netzwerk (Rückflug-/Liefer-Pfad unberührt).
3. **Geparkt off-route → unsichtbar.** Position am Boden fernab jedes Streckenplatzes:
   kein Netzwerk-Eintrag.
4. **In der Luft über einem Abholplatz → unterwegs, nicht ladend.** `groundspeed`
   über `_BLOCK_GS_KT`: der Boden-Zweig greift nicht; `current_leg`/`airborne`-Pfad
   bleibt maßgeblich.
5. **Keine Live-Position → unsichtbar** (kein Crash bei `None`).

Frontend bleibt ohne JS-Testharness — manuelle Live-Prüfung nach Deploy (nächster
Kutter-Test: am Abholplatz parken, „🅿️ lädt in <Platz>" muss vor dem Start erscheinen).

## Betroffene Dateien

- `app/database.py` — `_current_pos`-Helfer; `dep`-Auflösung im geparkten Fall (GPS-only,
  Plan-Fallback streichen).
- `app/static/index.html` — Status-Text „🅿️ lädt in <dep>".
- `tests/test_transport.py` — 5 neue Unit-Tests (s. o.).
- `docs/api.md`, `docs/architecture.md` — Notiz „Boden-Beladung GPS-only".
- `app/CHANGELOG.json` — neuer Eintrag; Versionsbump.

## Versionierung

Neues Feature (nutzer-sichtbar) → **Minor-Bump** (v8.22.0), Git-Tag, Banner automatisch.
