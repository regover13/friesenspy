# Spezial-Events-KPIs im Statistiken-Tab — Design (#64)

**Datum:** 2026-07-07 · **Status:** Design (abgenommen im Brainstorming) · **Release:** v8.11.0 (Minor, kein highlight)

## Ziel

Im Statistiken-Tab (`app/static/index.html`) eine **eigene, optisch abgetrennte Sektion
„Spezial-Events"** ergänzen, die aggregierte Kennzahlen für **beide** Spezial-Events —
**FriesenKutter** (Fracht) und **FriesenFliegerBummel** — gleichrangig zeigt. Reagiert auf den
bestehenden Zeitraum-Wähler (30/90/365 Tage).

**Stehende Regel (Memory `feedback_spezialevents_symmetric`):** Kutter und Bummel werden
gleichrangig behandelt, nie kutterlastig. Beide Untergruppen haben dieselbe Kachel-Grammatik
(Eventart · Teilnahmen · Flüge · …), nur die eventspezifischen Kacheln unterscheiden sich.

## Datengrundlage & Abgrenzung

Nur **abgeschlossene** Spezial-Events fließen ein (finale, stabile Bilanz). Grund: Verluste und
Wertung stehen erst am Ende fest; laufende Events würden zappeln.

- **Kutter abgeschlossen:** `transport_events.summarized_at IS NOT NULL` **und** `dtend >= since`.
- **Bummel abgeschlossen:** `bummel_races.revealed_at IS NOT NULL` **und** `now >= dtend` **und**
  `dtend >= since` (das strengere „finished"-Kriterium, für das ein eingefrorener
  `progress_snapshot` existiert).
- `since = now − days` (aus dem Zeitraum-Wähler; Muster `_retention_since`, `app/main.py`).

Beide Event-Typen werden ohnehin aus dem eingefrorenen Snapshot (#66) bedient — die Aggregation
liest die **fertigen** Progress-/View-Dicts (`_kutter_progress` / `_bummel_view`) und summiert nur.
**Kein** erneutes `canonicalize_legs`/Track-Rechnen.

**Nur Events mit echter Aktivität zählen** (verhindert, dass leere Test-Events die Anzahl
verfälschen): Kutter nur mit `flight_count > 0`, Bummel nur mit `participant_count > 0`.

## Kacheln (Reihenfolge exakt)

Die **erste Kachel jeder Zeile ist die Eventart** — Label = Eventname, Wert = Anzahl
abgeschlossener Events dieser Art. Sie ersetzt eine separate Untergruppen-Überschrift.

### 🦐 FriesenKutter *(6 Kacheln)*

| # | Label | Wert | Quelle (pro Event → Σ) |
|---|-------|------|------------------------|
| 1 | **FriesenKutter** | Anzahl Events | `1` je Event mit `flight_count>0` |
| 2 | **Teilnahmen** | Piloten | `len(participants)` |
| 3 | **Flüge** | alle Flüge (inkl. zurück/versunken/geklaut) | `flight_count` (= `len(network)`) |
| 4 | **Tonnage** | t geliefert | `total_kg` / 1000 |
| 5 | **Versunken** | t · *N Kutter* | Σ `lost_kg` bzw. Anzahl, `loss_kind=="sunk"` |
| 6 | **Geklaut** | t · *N Ladungen* | Σ `lost_kg` bzw. Anzahl, `loss_kind=="stolen"` |

`returned` (zurückgebracht) ist **kein** Verlust (Ware heil, 0 kg) → taucht nirgends auf, ist aber
in „Flüge" (Kachel 3) mitgezählt.

### 🛩 FriesenFliegerBummel *(4 Kacheln)*

| # | Label | Wert | Quelle (pro Rennen → Σ) |
|---|-------|------|-------------------------|
| 1 | **FriesenBummel** | Anzahl Rennen | `1` je Rennen mit `participant_count>0` |
| 2 | **Teilnahmen** | Piloten | `participant_count` |
| 3 | **Flüge** | Legs | Σ `leg_count` über `complete`+`incomplete` |
| 4 | **Ø Absoluter Durchschnitt** | Ø min | Mittel der `average_min` über gewertete Rennen (`count>0`) |

„Absoluter Durchschnitt" ist die Bummel-Terminologie für die Zeit, an der sich der Sieger
orientiert (`average_min` je Rennen). Kachel 4 = arithmetisches Mittel dieser Renn-Durchschnitte.

## Backend

### `app/database.py` — zwei reine, testbare Aggregatfunktionen

```python
def aggregate_kutter_kpis(progresses: list[dict]) -> dict:
    """Aggregiert eine Liste von compute_transport_progress-/Snapshot-Dicts (nur
    abgeschlossene, aktive Events mit flight_count>0). Rein, keine DB."""
    # event_count, participations, flights, delivered_kg,
    # sunk_kg, sunk_count, stolen_kg, stolen_count

def aggregate_bummel_kpis(views: list[dict]) -> dict:
    """Aggregiert eine Liste von _bummel_view-/Snapshot-Dicts (nur enthüllte Rennen mit
    participant_count>0). Rein, keine DB."""
    # race_count, participations, legs, avg_absolute_min (None wenn kein gewertetes Rennen)
```

Verlust-Aufschlüsselung: aus `progress["losses"]` (Liste mit `loss_kind` ∈ sunk/stolen/returned,
`lost_kg`). `sunk_kg = Σ lost_kg where loss_kind=="sunk"`, `sunk_count = count(...)`; stolen analog.
`returned` wird ignoriert.

### `app/main.py` — ein Endpoint

```
GET /api/stats/special-events?days=30|90|365   (öffentlich, kein Admin)
→ { "kutter": {event_count, participations, flights, delivered_kg,
               sunk_kg, sunk_count, stolen_kg, stolen_count},
    "bummel": {race_count, participations, legs, avg_absolute_min} }
```

- `days` validieren (Whitelist `{30,90,365}`, Default 30 — wie `/api/stats`).
- Kutter: `list_transport_events(conn)` → filter `summarized_at` & `dtend>=since`, je Event
  `_kutter_progress(conn, ev, now, prefix)`, nur `flight_count>0` behalten → `aggregate_kutter_kpis`.
- Bummel: `list_bummel_races(conn)` → filter `revealed_at` & `now>=dtend` & `dtend>=since`, je
  Rennen `_bummel_view(conn, race, now)`, nur `participant_count>0` → `aggregate_bummel_kpis`.

## Frontend (`app/static/index.html`)

Neues Panel **„Spezial-Events"** unter den bestehenden Flug-Statistiken, optisch klar getrennt
(eigene Panel-Umrandung/Überschrift). Zwei Zeilen à `.stats-kpi-row` (bestehende Kachel-Klassen
`.stats-kpi-card` / `-value` / `-label` / `-note`).

- `fetchSpecialEventStats(days)` ruft `GET /api/stats/special-events?days=` und rendert beide
  Zeilen. In `renderStatsTable()`/beim `days`-Wechsel mitgeladen.
- **UI-Standards (CLAUDE.md):** keine Kachel klickbar → alle Werte neutral (kein Blau; Blau ist
  Klickbarem vorbehalten). `.stats-kpi-row` ist Flex-Wrap → Kacheln brechen mobil um, **kein**
  horizontaler Scroll nötig (keine breite Tabelle).
- **Leerlogik:** Untergruppe mit `event_count==0`/`race_count==0` wird ausgeblendet; sind **beide**
  leer, verschwindet die ganze Sektion (kein leerer Block).
- Einheiten/Format: Tonnage/Verluste in **t** (kg/1000, 1 Nachkommastelle); Verlust-Kacheln mit
  Anzahl als `.stats-kpi-note` („*3 Kutter*" / „*2 Ladungen*"); Ø Absoluter Durchschnitt als
  `h:mm` wenn ≥ 60 min, sonst „*N* min". `null` avg → Kachel zeigt „—".

## Tests

- `tests/test_database.py`:
  - `test_aggregate_kutter_kpis_sums_and_splits_losses` (Tonnage/Flüge/Teilnahmen korrekt;
    sunk/stolen getrennt; `returned` ignoriert, aber in `flights` enthalten).
  - `test_aggregate_kutter_kpis_empty_is_zero`.
  - `test_aggregate_bummel_kpis_sums_legs_and_avg` (participations/legs/avg korrekt).
  - `test_aggregate_bummel_kpis_avg_none_without_scored_race`.
- `tests/test_stats_api.py` (bzw. passende Datei):
  - `test_special_events_only_finished_in_window` (Event außerhalb `since`, laufendes/nicht-
    enthülltes Rennen und leeres Event zählen **nicht**).
  - `test_special_events_shape` (Antwort-Struktur `{kutter, bummel}` mit allen Feldern).
- Frontend: manueller Sicht-Check nach Deploy (Kacheln erscheinen, mobil umbrechend, keine
  Klickfarbe, leere Sektion verschwindet).

## Version / Docs (stehende Regeln)

- `app/CHANGELOG.json`: **v8.11.0** oben, **ohne** highlight, Item: „Neue Spezial-Events-Kennzahlen
  (FriesenKutter + FriesenFliegerBummel) im Statistiken-Tab".
- Git-Tag `v8.11.0`; vor `git push origin main` kurze Nutzer-Bestätigung.
- `docs/api.md`: neuer Abschnitt `GET /api/stats/special-events`.
- `docs/architecture.md`: Aggregatfunktionen + Datenquelle (Snapshot-Reuse) dokumentieren.

## Bewusst NICHT im Scope

- Keine pro-Pilot-Detailansicht / Bestenliste (Top-Pilot abgewählt).
- Keine laufenden Events in den KPIs (nur abgeschlossene).
- Kein eigener KPI-Cache (`kind='kutter_kpi'`) — die Aggregation ist über die vorhandenen
  Snapshots billig genug; erst bei Bedarf nachrüsten.
