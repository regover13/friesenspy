# FriesenKutter: Fracht zählen ohne Disconnect — Design

Datum: 2026-07-01 · Status: zur Umsetzung freigegeben · Scope: FriesenKutter (Bummel folgt separat)

## Context

FriesenKutter zählt Fracht bisher nur für **abgeschlossene** Flüge: `canonicalize_flights()`
verlangt `logoff_time IS NOT NULL` — ein Pilot, der am Ziel landet, aber verbunden bleibt (z. B.
um gleich den Rückflug anzutreten), wird bis zum Disconnect komplett ignoriert. Der Nutzer will
weder bei FriesenKutter noch beim FriesenFliegerBummel zum Disconnecten gezwungen sein: Fracht
soll zählen, sobald der Pilot **erkennbar am Boden am Ziel** ist.

Diese Spec deckt **nur FriesenKutter** ab. Der FriesenFliegerBummel bekommt denselben Baustein
später in einer eigenen Sitzung, weil seine Etappen-/Ranking-Wertung eigene Fragen aufwirft (siehe
Memory `project_bummel_live` — dort auch die verwandte, offene Lücke, dass eine Zwischenlandung
**ohne** Disconnect die Blockzeit-Berechnung verfälscht; separates Thema, nicht Teil dieser Spec).

Verworfen wurde die Idee, den Flug beim Antippen künstlich zu schließen und neu zu öffnen
(Etappen-Split): Das würde von der bestehenden Reconnect-Erkennung (`merge_fragmented_flights` /
`_segments_continuous`) automatisch wieder zusammengeklebt, da diese gezielt kurze Lücken mit
geografischer Kontinuität als Reconnect erkennt und vereint.

## Entscheidungen (bestätigt mit User)

- Gilt für **FriesenKutter**, Bummel ist explizit **nicht** Teil dieser Spec.
- „Am Boden" = **Groundspeed < 2 kt** — bewusst dieselbe Schwelle wie die bestehende
  Blockzeit-Erkennung (`_BLOCK_GS_KT`), nicht z. B. 20/40 kt.
- Radius um den Zielflugplatz: bestehende `_BUMMEL_AIRPORT_RADIUS_KM` (10 km) wiederverwendet.
- Sobald einmal erkannt, zählt die Fracht **dauerhaft** — unabhängig davon, was der Pilot danach
  tut (weiterfliegen, woanders disconnecten, gar nicht mehr disconnecten).
- Keine neue Poll-Schleife: die Prüfung läuft im bestehenden VATSIM-Poll-Takt mit, dort wo
  `live_positions` ohnehin jeden Zyklus aktualisiert wird.

## Architektur

### Neue Tabelle `transport_live_arrivals`

```sql
CREATE TABLE transport_live_arrivals (
    cid         INTEGER NOT NULL,
    logon_time  TEXT NOT NULL,
    event_id    INTEGER NOT NULL,
    arrived_at  TEXT NOT NULL,
    PRIMARY KEY (cid, logon_time, event_id)
);
```

`(cid, logon_time)` identifiziert die Flugsession eindeutig (wie schon `flight_key` beim
Spruch-Cache). Ein Latch — einmal geschrieben, bleibt der Eintrag für immer bestehen. Kein Bezug
zu `flights`/`canonicalize_flights`, daher keine Wechselwirkung mit Reconnect-Merge oder
StatSim-Dedup.

### Erkennung (Poller)

Im bestehenden VATSIM-Poll-Zyklus, an der Stelle, wo `live_positions` aktualisiert wird,
zusätzlich prüfen: für jeden FRS-Piloten mit **offenem** Flug (`logoff_time IS NULL`), dessen
aktuelle Position innerhalb 10 km um das `destination`-ICAO eines **gerade laufenden**
Kutter-Events (`dtstart ≤ now ≤ dtend`) liegt **und** `groundspeed < 2 kt` →
`INSERT OR IGNORE INTO transport_live_arrivals`.

### Auswertung (`compute_transport_progress`)

Die `loaded`-Bedingung wird vereinheitlicht:

```
loaded = (bisherige GPS-Endpositions-Prüfung bei Disconnect)
         OR (transport_live_arrivals-Eintrag für (cid, logon_time, event_id) existiert)
```

Zusätzlich werden **aktuell offene** FRS-Flüge (bisher komplett ignoriert) mit Start auf der
Streckenmenge in den Feed aufgenommen — Zuladung/Typ aus der laufenden `flights`-Zeile
(`aircraft_short`/`aircraft_icao`, identisch zum bestehenden Payload-Lookup), `loaded` = Latch
vorhanden. Eine Flugsession ist strukturell **entweder** offen **oder** geschlossen (nie beides
gleichzeitig) — dadurch ist eine Doppelzählung ausgeschlossen. Disconnectet der Pilot später,
wechselt der Flug beim nächsten Aufruf nahtlos in den bestehenden geschlossenen-Flüge-Pfad; der
Latch bleibt als Beleg bestehen, auch wenn die finale Position beim Disconnect ganz woanders liegt.

## Testplan

1. **Unit (rein):** Latch-Bedingung (Radius + Groundspeed) als eigene, testbare Funktion — Fälle:
   innerhalb Radius + langsam → True; innerhalb Radius + schnell (Überflug) → False; außerhalb
   Radius → False.
2. **DB-Roundtrip:** `INSERT OR IGNORE` idempotent bei wiederholtem Treffer; Latch bleibt nach
   Zustandswechsel offen→geschlossen erhalten.
3. **`compute_transport_progress`:** offener Flug mit Latch erscheint im Feed als beladen, ohne
   dass die zugehörige `flights`-Zeile ein `logoff_time` hat; nach simuliertem Disconnect fernab
   des Ziels bleibt die Fracht weiterhin gezählt (kein Rückgängigmachen).
4. **End-to-End (VPS):** FRS-Testflug zum Ziel, dort auf < 2 kt abbremsen, **nicht** disconnecten —
   Fracht muss binnen eines Poll-Zyklus (~15 s) im Events-Tab erscheinen; danach weiterfliegen und
   irgendwo anders disconnecten — Fracht bleibt gezählt.

## Out of Scope (bewusst)

- FriesenFliegerBummel-Anpassung (eigene Spec später).
- Die Zwischenlandungs-Blockzeit-Lücke bei durchgehend verbundenen Bummel-Flügen (siehe
  `project_bummel_live`-Memory) — unabhängiges Thema, nicht durch diese Spec gelöst.
- Mehrere gleichzeitige Ziele / bidirektionale Zählung (`destination`-Thema, separat geparkt).
