# FriesenKutter v7.5.0 — Design: Live-Teilnehmer + Fracht-Reservierung, Fracht-Verluste, Umkreis pro Event

Datum: 2026-07-02 · Status: vom Auftraggeber freigegeben (Brainstorming-Sitzung 02.07.)
Tasks: #8 (Reservierung + Teilnehmerliste), neu: Fracht-Verluste, #7 (radius_km pro Event)

## Kontext

Beim Live-Test am 01.07. fehlten zwei Dinge: (a) Man sieht nicht, wer gerade mit wie viel
Fracht unterwegs ist — die offene Zielmenge korrigiert sich erst bei Ankunft, obwohl die
Ladung ab Start faktisch „vergeben" ist. (b) Der Ankunfts-/Strecken-Radius ist fix 10 km
(`_BUMMEL_AIRPORT_RADIUS_KM`) — für kurze Strecken wie Wangerooge↔Harle (~10,5 km Luftlinie)
überlappen sich die Kreise. Im Brainstorming kam als drittes Element dazu: Fracht, die nie
ankommt, wird nicht still zurückgebucht, sondern geht **erzählbar verloren** (Kutter versunken /
geklaut) — Futter für die KI-Sprüche.

Nutzer-Entscheidungen:
- Reservierung als **helleres „unterwegs"-Segment im Ziel-Balken** + Text „offen: X kg, davon
  Y kg unterwegs".
- **Teilnehmerliste mit Summen** (alle Piloten des Abends, wie beim Bummel).
- Verluste: **Story + Statistik** — Menge zurück in „offen", Verlust wird verbucht/verspottet.
- „versunken" **immer in Verbindung mit dem Kutter** („🌊 Kutter versunken"), keine
  Land/Wasser-Erkennung (der Kutter kann überall versinken, notfalls im Watt).
- Rückkehr zum Abflugplatz = **ehrlich zurückgebracht** (kein Verlust, kein Spott).

## Teil A — Reservierung + Teilnehmerliste

### Backend: `compute_transport_progress` (app/database.py:2999–3192)

Offene Flüge Richtung Ziel sind seit v7.3.0 im Feed (`open_transport_flights`,
Zeilen 3077–3107; ohne Latch `tonnage_kg=0`). Neu:

1. **Feed-Eintrag** offener Flüge ohne Latch bekommt `reserved_kg = payload_map.get(type, default_kg)`
   und `in_air: true` (`tonnage_kg` bleibt 0 bis zum Latch — Fortschritt läuft nie rückwärts).
   Mit Latch wie bisher `loaded=true, tonnage_kg=payload`.
   - **Beginn der Reservierung:** sobald die Verbindung am Abflugplatz mit Ziel-Richtung als
     offener Flug sichtbar ist — bereits beim Rollen, nicht erst airborne. Jeder gestartete
     Pilot erscheint sofort MIT Ladung in Balken, Feed und Teilnehmerliste.
   - **Gewichts-Korrekturen wirken live:** Reservierung UND gelieferte Tonnage werden bei jeder
     Berechnung frisch aus `aircraft_payloads` gezogen (kein Snapshot) — eine Admin-Korrektur
     rechnet beim nächsten Refresh (≤25 s) alles neu, auch rückwirkend.
   - **Rückgabe:** kein DB-State — endet der offene Flug ohne Ziel-Ankunft, verschwindet die
     Reservierung beim nächsten Poll automatisch (und wird ggf. zum Verlust, s. Teil C);
     Karteileichen räumt der bestehende 8-h-`close_stale_flights` ab.
2. **Zweiter Füll-Pass** nach der Delivered-Co-Load-Füllung (Zeilen 3137–3150): reservierte
   Mengen werden mit derselben Logik (Manifest-Reihenfolge, `per_flight_max_kg`-Kappung) in die
   **Rest-Kapazität** verteilt → je Frachtart neues Feld `reserved_kg` in `cargo_out`, gesamt
   `reserved_total_kg` im Ergebnis.
3. **`participants`-Liste** (neu im Ergebnis): Aggregation über Feed + offene Rückflüge
   (`open_transport_flights` mit `dep == dest`, die der Feed-Filter überspringt — nur für den
   Status, keine Reservierung). Pro Pilot: `{cid, name, aircraft, flights, delivered_kg,
   reserved_kg, lost_kg, status}` mit `status ∈ {"flying"` (offen Richtung Ziel, reserviert),
   `"arrived"` (Latch/angekommen, noch verbunden), `"returning"` (offener Flug ab Ziel),
   `"done"` (nur abgeschlossene Flüge)`}`.

### API (app/main.py)

`GET /api/transport/event/{id}` liefert die neuen Felder automatisch mit (Response =
compute-Ergebnis); `_transport_event_meta` (Zeile 1482) zusätzlich `reserved_total_kg` für die
Events-Tab-Kacheln.

### Frontend: `_kutterDetailBody` (app/static/index.html:4304–4337)

1. **Balken**: je Frachtart-Segment zusätzlich zur soliden Füllung (`delivered`) ein
   helleres/gestreiftes Teilstück für `reserved_kg` (Breite `min(100−pct, reserved_pct)`),
   gleiche Farbe via `_kColor(i)` mit Opazität/Streifen-CSS. Legende: `geliefert/Ziel (+Y unterwegs)`.
2. **Header-Zeile** ergänzt: `… — offen: X kg, davon Y kg unterwegs ✈️` (+ `💀 X kg verloren`,
   wenn Verluste existieren).
3. **Teilnehmerliste** über dem Feed, Bummel-Optik (`renderBummelParticipants`, Zeilen 2765–2805
   als Vorlage): Spalten Pilot | Muster | Flüge | geliefert | Status (✈️ unterwegs mit X kg /
   ✅ angekommen / ↩️ Rückflug / 🌊/🏴‍☠️-Verluste / fertig). **In `.table-scroll`-Wrapper**
   (stehende Mobile-Regel aus CLAUDE.md).
4. Feed-Zeile offener Flüge: Fracht-Spalte zeigt `~X kg ✈️` (reserviert) statt „leer".

## Teil C — Fracht-Verluste (Story + Statistik)

Verlorene Fracht wird NICHT still zurückgebucht, sondern erzählt und verbucht; die Menge
wandert zurück in „offen" (Ziel bleibt fair erreichbar — keine Zielvergrößerung).

**Verlust-Taxonomie** — ausgewertet, wenn ein offener Flug mit Reservierung endet, ohne das
Ziel erreicht zu haben (kein Live-Latch, GPS-Ankunft ≠ destination):

| Ausgang | Status | Verlust? |
|---|---|---|
| Landung wieder am Abflugplatz | ↩️ zurückgebracht | nein — Fracht wieder am Kai, neutral im Feed |
| Landung an einem anderen Platz (≠ Ziel, ≠ Start) | 🏴‍☠️ geklaut | ja |
| Unterwegs verschwunden (Disconnect in der Luft / abseits jedes Platzes) | 🌊 **Kutter versunken** | ja |

**Formulierungs-Vorgabe:** „versunken" IMMER in Verbindung mit dem Kutter — Anzeige-Text
überall exakt „🌊 Kutter versunken" (Feed, Teilnehmerliste, Verlust-Bilanz), und der
KI-Kontext übergibt den Verlust als „Kutter versunken", damit die Sprüche den Kutter untergehen
lassen (nicht den Piloten).

**Mechanik:**
- **Erkennung im Poller** (`_check_transport_events` oder Close-Pfad): Flug war offener
  Richtung-Ziel-Flug mit Reservierung und wurde geschlossen ohne Ziel-Ankunft → Klassifikation
  per letzter GPS-Position (`_last_pos`/`_nearest_airport` mit Event-Radius: am Startplatz / an
  anderem Platz / nirgends) → Eintrag in neue Tabelle
  `transport_cargo_losses (event_id, cid, logon_time, kind ('stolen'|'sunk'|'returned'),
  type_code, lost_at, PRIMARY KEY(event_id, cid, logon_time))`.
  „returned" wird mitgespeichert (neutraler Feed-Status), zählt aber nicht als Verlust.
- **kg live gerechnet** (konsistent zur Gewichts-Korrektur-Regel): gespeichert wird der
  `type_code`, die kg kommen bei jeder Berechnung frisch aus `aircraft_payloads`.
- **Anzeige:** Feed-Zeile des verlorenen Flugs mit Status-Emoji + Text statt „zurück"; Header
  ergänzt „💀 X kg verloren"; Teilnehmerliste: Verlust-kg je Pilot; `compute_transport_progress`
  liefert `losses` (Liste) + `lost_total_kg`.
- **KI-Kontext:** `flight_quip_context`/`event_summary_context` bekommen die Verluste
  (Art + Frachtart + Pilot) — Spott ausdrücklich erwünscht; Feierabend-Bilanz nennt Verluste.
- **Kein Doppelzählen:** ein Flug ist entweder geliefert (Latch/Ankunft), zurückgebracht oder
  verloren; Reservierung existiert nur, solange der Flug offen ist.

## Teil B — Umkreis pro Event (radius_km)

Die Parameter existieren schon durchgängig (`check_live_arrival(radius_km=…)` db:2924,
`compute_transport_progress(radius_km=…)` db:3005, `transport_anyone_in_progress` analog) —
es fehlt nur die Quelle:

1. **Migration**: `ALTER TABLE transport_events ADD COLUMN radius_km REAL` in
   `_TRANSPORT_MIGRATIONS` (db:335, Muster vorhanden) + Spalte im `_DDL`-CREATE.
   `NULL` = Default 10 km.
2. **CRUD**: `radius_km` in POST create/edit (main.py:1544/1569; Validierung 0.5–50 km, sonst
   400) und in den GET-Ausgaben.
3. **Verdrahtung**: `active_transport_destinations` (db:2895) liefert `radius_km` mit;
   `check_live_arrival` nutzt den per-Event-Radius aus dem Event-Dict (statt einem globalen
   Parameter für alle Events); Poller-Aufrufe von `compute_transport_progress` /
   `transport_anyone_in_progress` übergeben `event["radius_km"]`.
4. **Admin-Formular** (admin.html:812–831): Zahlenfeld „Umkreis (km)" (`ke-radius`,
   Platzhalter „10"), in `keEdit`/Speichern (Zeile 2028) verdrahtet.
5. Kalender-Events (source='calendar') bekommen NULL → Default; Admin kann nachpflegen.

## Wiederverwendung

`open_transport_flights`, `transport_live_arrivals`, Co-Load-Füllalgorithmus,
`get_payload_map`/`transport_default_payload_kg`, `_last_pos`/`_nearest_airport`,
`renderBummelParticipants`-Optik, `.table-scroll`, `_TRANSPORT_MIGRATIONS`-Muster, `_kColor`.

## Tests (tests/test_transport.py, Muster: `_event`/`_add_open_flight`, Klassen ab Z. 312)

- Offener Flug Richtung Ziel ohne Latch → `reserved_kg` gesetzt, `tonnage_kg=0`,
  `cargo[].reserved_kg` + `reserved_total_kg` korrekt; mit `per_flight_max_kg`-Kappung.
- Reservierung übersteigt Rest-Bedarf → gekappt auf `target − delivered`.
- Latch wandelt Reservierung in `delivered` (kein Doppelzählen).
- `participants`: Statusermittlung für flying/arrived/returning/done; Rückflug (dep==dest)
  erscheint als Teilnehmer, reserviert nichts.
- Verluste: Klassifikation zurückgebracht/geklaut/versunken anhand letzter Position;
  Verlust-Menge zurück in „offen" (delivered unverändert, Reservierung weg); `lost_total_kg` +
  Teilnehmer-Verlust-kg korrekt; „returned" erzeugt keinen Verlust; Verlust-kg folgen einer
  Gewichts-Korrektur (type_code-basiert).
- `radius_km`: CRUD-Roundtrip, Validierung, `check_live_arrival` latcht mit 3-km-Event bei
  4 km Abstand NICHT (und mit Default 10 km schon) — Fixtures aus `TestCheckLiveArrival` (Z. 491).

## Verifikation (End-to-End)

1. `pytest tests/ -v` grün (Basis: 540).
2. Prod: Test-Event mit kleinem Radius anlegen; nächsten Live-Flug beobachten → Balken zeigt
   helles „unterwegs"-Segment ab dem Rollen, Teilnehmerliste führt den Piloten mit ✈️ und
   reservierten kg; nach Latch wird das Segment fest; Disconnect unterwegs → „🌊 Kutter
   versunken" im Feed + Verlust-Bilanz.
3. Deploy: Push auf main → Actions-Health-Check grün, `/api/frontend-config` → 7.5.0,
   Kutter-Ansicht auf dem Smartphone gegenprüfen (horizontales Scrollen der neuen Tabelle).

## Stehende Regeln

Changelog v7.5.0 (Minor) + Git-Tag; README/api.md/architecture.md aktualisieren;
datetime-local als UTC; Tabellen mobil scrollbar; keine Secrets in git.
