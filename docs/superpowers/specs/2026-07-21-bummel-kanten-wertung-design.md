# Bummel-Wertung: Kanten-basiert (Rundkurs-fähig)

**Datum:** 2026-07-21
**Status:** freigegeben (Design), Implementierung ausstehend

## Problem

Die Bummel-Wertung dedupliziert die Route zu einer Menge distinkter Plätze und wertet
„komplett = alle Plätze besucht" (`route_set.issubset(visited)`). Ein **Rundkurs**
`EDKB → EDKL → EDKF → EDKB` verliert dadurch seine Rückkehr: Der End-Platz EDKB ist mit dem
Start-Platz identisch, also gilt eine Tour schon ohne Rückflug als komplett. Wer bei EDKF aufhört
(2 Etappen) wird genauso als „komplett" gewertet wie wer den vollen Kreis fliegt (3 Etappen) — bei
unterschiedlicher Blockzeit. Für einen echten Rundkurs ist das falsch.

## Ziel

Ein **einheitliches** Wertungsmodell (kein Sonderfall Rund vs. offen), das den Rückweg als
Pflicht erfasst, „Richtung egal / Reihenfolge egal / Zwischenlandungen erlaubt" erhält und die
Zeitwertung unverändert lässt.

## Entscheidungen (Nutzer, 2026-07-21)

1. **Kanten-Modell** (nicht geordnete Wegpunkte): Die Route definiert aufeinanderfolgende
   Pflicht-Etappen; komplett = jede Etappe geflogen, Reihenfolge der Etappen egal.
2. **Weg erlaubt, ganze Tour zählt**: Eine Etappe A–B darf über Off-Route-Zwischenstopps
   erfüllt werden; die gewertete Zeit bleibt die ganze Tour-Spanne inkl. Umwege (wie heute).
3. **Keine Rücksicht auf bestehende Bummel** — waren nur Tests; die alte Knoten-Logik entfällt
   ersatzlos.
4. **`canonicalize_legs` bleibt die einzige Erfassungswahrheit** (GPS-korrigierte dep/arr pro
   Leg) — an der Detektion ändert sich nichts.

## Modell

### Begriffe

- `route_seq` — Route **saniert**, Reihenfolge und (nicht-aufeinanderfolgende) Wiederholung
  erhalten: jedes Element `strip().upper()`, leere raus, **aufeinanderfolgende Duplikate
  entfernt** (A2). `EDKB,EDKL,EDKF,EDKB` bleibt `["EDKB","EDKL","EDKF","EDKB"]` (erstes/letztes
  EDKB sind NICHT benachbart → Rundkurs erhalten); ein Tippfehler `EDKB,EDKB,EDKL` wird zu
  `["EDKB","EDKL"]` (verhindert eine unerfüllbare Selbstkante `(EDKB,EDKB)`). Diese sanierte
  Sequenz wird auch als `"route"` zurückgegeben.
- `required_edges` — ungerichtete **Multimenge** der Nachbarpaare von `route_seq`:
  `{ {EDKB,EDKL}:1, {EDKL,EDKF}:1, {EDKF,EDKB}:1 }`. Kante als `tuple(sorted((a,b)))`,
  Multiplizität via `Counter`. Nach der Sanierung ist keine Selbstkante mehr möglich.
- `route_set` — `set(route_seq)`, nur zum Erkennen, ob ein Landepunkt auf der Strecke liegt.

### Pro Pilot

Tour-Definition **unverändert**: Legs chronologisch (nach `logon_time`); `start_idx` = erstes Leg,
dessen `departure ∈ route_set`; `end_idx` = letztes Leg, dessen `arrival ∈ route_set`; ist eines
`None` oder `end_idx < start_idx` → keine Tour (übersprungen). `tour = legs[start_idx:end_idx+1]`.

1. **Zusammenhängende Segmente (A1 — wichtig).** Kanten dürfen NUR aus tatsächlich geflogenen,
   zusammenhängenden Leg-Ketten entstehen — sonst wird eine Track-/Session-Lücke zwischen
   `arrival` von Leg *i* und `departure` von Leg *i+1* zu einer nie geflogenen „Phantom-Kante"
   (Fable-Fund: umginge „Rückweg Pflicht"). Die Tour wird daher in zusammenhängende Segmente
   zerlegt; eine Kette bricht bei einer Lücke ODER an einem leeren Endpunkt (`""`, streng):
   ```
   segments = []; cur = []
   for leg in tour:                      # dep/arr bereits strip().upper()
       dep, arr = leg["departure"], leg["arrival"]
       if cur and cur[-1] == dep and dep:   # zusammenhängend UND kein leerer Bruch
           cur.append(arr)
       else:
           if cur: segments.append(cur)
           cur = [dep, arr]
   if cur: segments.append(cur)
   ```
   Leere Endpunkte (`""`) sind nie in `route_set` und brechen die Kette (streng): eine unbekannte
   Zwischenposition bildet keine Etappe. Off-Route-Stopps mit bekanntem ICAO bleiben Teil des
   Segments (werden bei der Projektion übersprungen → „Weg erlaubt").
2. **`achieved_edges`** — pro Segment auf `route_set` projizieren, aufeinanderfolgende Duplikate
   entfernen, dann Nachbarpaare als ungerichtete Kanten sammeln (über ALLE Segmente):
   ```
   achieved = Counter()
   for seg in segments:
       touch = dedup_consecutive([p for p in seg if p in route_set])
       for a, b in zip(touch, touch[1:]):
           achieved[tuple(sorted((a, b)))] += 1
   ```
   Nach `dedup_consecutive` unterscheiden sich benachbarte Plätze im Segment immer → keine
   Selbstkante.
3. **komplett ⇔** für jede Kante `e`: `achieved[e] >= required_edges[e]`
   (Multimengen-Enthaltung). Sonst unvollständig.
4. **`missing`** (Anzeige) — unerfüllte Pflicht-Etappen als Strings `"A ↔ B"`, mit Wiederholung
   je Fehlmenge: `(required_edges - achieved)` als `Counter`, jede Kante `max(0, req-ach)`-mal.
   **`visited`** (Anzeige) — erfüllte Pflicht-Etappen als `"A ↔ B"`, je Kante genau
   `min(achieved[e], required_edges[e])`-mal (B2 — damit `visited.length + missing.length` =
   Anzahl Pflicht-Etappen bleibt; das Frontend rechnet `total = visited.length + missing.length`).
5. **`total_min` / `total_sec`** — Summe der Blockzeiten der Tour-Legs. **Unverändert.**

### Wertung / Sieger

Unverändert: Sieger = kleinster `|total_min − average|` über alle **kompletten** Touren; Schnitt =
Mittel der `total_min` kompletter Touren; sekundengenaues Tie-Break wie bisher.

## Warum das die Vorgaben erfüllt

| Vorgabe | Mechanik |
|---|---|
| Richtung egal | Kanten ungerichtet (`tuple(sorted(...))`) |
| Reihenfolge egal | Multimengen-Enthaltung (Dreieck in beide Richtungen deckt dieselben Kanten) |
| Zwischenlandungen erlaubt | Projektion auf `route_set` überspringt Off-Route-Stopps; Zeit = ganze Spanne |
| Rückweg Pflicht | Wiederholung in `route_seq` erzeugt die zusätzliche Pflicht-Etappe `{EDKF,EDKB}` |
| Einheitlich, kein Sonderfall | Ein Kriterium für alle Bummel; `route_set.issubset` entfällt |

**Bewusste Konsequenz (B1):** Ein *anderer* Streckenplatz als Zwischenstopp mitten in einer Etappe
zerlegt diese. Wer in Etappe A–B am Streckenplatz C zwischenlandet, hat `A–C` + `C–B` geflogen,
nicht `A–B` → Etappe A–B unerfüllt. Streckenplätze sind also keine freien Umwege (nur Off-Route-
Plätze sind es). Beim symmetrischen Dreieck fällt das nicht auf (deckt dieselben Kanten), bei
offenen Routen/Vierecken schon. Gewollt und getestet (Testfall 9).

## Änderungen

- **`app/database.py` · `compute_bummel_standings`** — Herz der Änderung:
  - `route_order` bleibt für die Deduplizierung von `route_set` erhalten, aber die Rückgabe
    `"route"` liefert jetzt **`route_seq`** (roh, mit Wiederholung) für die Anzeige.
  - `required_edges` aus `route_seq` bilden.
  - Pro Pilot `route_touch_seq` → `achieved_edges`; `complete`-Kriterium = Multimengen-Enthaltung
    statt `route_set.issubset(visited)`.
  - `visited`/`missing` als Kanten-Strings statt Platz-Codes.
  - Helfer `dedup_consecutive`, `_edges_of(seq)` (Counter) lokal/rein.
- **`app/main.py` · `_build_race_view`** — nichts Zusätzliches nötig, wenn `compute_bummel_standings`
  bereits `route_seq` als `"route"` zurückgibt (die View übernimmt es aus `standings["route"]`).
  Prüfen, dass `_open_bummel_legs`/`route_set` weiter mit distinkten Plätzen arbeitet (tut es).
- **`app/static/index.html`** — Wording „Plätze"/„Flugplätze" → „Etappen": `renderBummelParticipants`
  (Status-Text „✓ alle Plätze" → „✓ alle Etappen" ~Z. 3125/3132; `total = visited.length +
  missing.length` bleibt korrekt dank B2) und der Hinweistext ~Z. 3250 („noch nicht alle
  **Flugplätze** besucht" → „… Etappen geflogen"). `route.join(' → ')` (Z. 3098/3171/3215) bleibt
  unverändert und zeigt durch `route_seq` automatisch den Rundkurs.
- **`app/static/admin.html`** (B3) — Spalten „Abgehakt"/„Fehlend" (~Z. 1892–1902) rendern
  `visited`/`missing` generisch als String-Join → degradieren sauber zu Kanten-Strings; ggf.
  Spalten-/Wording-Anpassung auf „Etappen", kein struktureller Umbau.
- **Eingefrorene Alt-Ansichten (B4):** Beendete Rennen kommen über `_frozen_or_compute`
  (`app/main.py:1169`) aus dem Snapshot — alte Snapshots bleiben Knoten-basiert (deduplizierte
  `route`, Platz-`visited`/`missing`). Das Frontend rendert beides (nur String-Joins). Konsistent
  mit Entscheidung 3 (keine Migration); kein Handlungsbedarf.

## Testfälle (TDD)

1. **Rundkurs komplett**: `route=[A,B,C,A]`, Pilot fliegt A→B→C→A → komplett, `missing=[]`.
2. **Rundkurs ohne Rückweg unvollständig**: Pilot A→B→C (Stopp) → unvollständig, `missing=["A ↔ C"]`
   (bzw. C↔A). Das ist der Kernfall gegen das alte Verhalten.
3. **Richtung egal**: Pilot A→C→B→A (Dreieck andersrum) → komplett (gleiche Kantenmenge).
4. **Weg erlaubt**: `route=[A,B]` (bzw. Etappe im größeren Kurs), Pilot A→X→B (X off-route) →
   die Etappe A–B gilt (X übersprungen); Zeit = Spanne inkl. A→X und X→B.
5. **Multiplizität (Out-and-back)**: `route=[A,B,A]` → `required={ {A,B}:2 }`. Pilot A→B→A → komplett;
   Pilot A→B (nur hin) → unvollständig (`{A,B}:1 < 2`).
6. **Offene Route unverändert sinnvoll**: `route=[A,B,C,D]`, Pilot A→B→C→D → komplett; Pilot, der
   B auslässt (A→C→D) → unvollständig (`{A,B}` und `{B,C}` fehlen).
7. **Zeit unverändert**: `total_min` = Summe Blockzeit der Tour-Legs (Regressions-Check gegen die
   bestehende Zeitberechnung — nur das Complete-Kriterium ändert sich, nicht die Zeit).
8. **Anzeige-Route roh**: `compute_bummel_standings(...)["route"] == ["A","B","C","A"]` (mit
   Wiederholung), nicht dedupliziert.
9. **Streckenplatz als Zwischenstopp (B1)**: `route=[A,B,C,D]`, Pilot A→C→B→C→D — die Etappe
   `A–B` wurde nie direkt geflogen → unvollständig (`missing` enthält `A ↔ B`).
10. **Phantom-Kante über Lücke (A1, Rundkurs)**: `route=[A,B,C,A]`, Pilot fliegt A→B, dann (Lücke:
    nächstes Leg startet bei C, nicht bei B) C→A. Zwei Segmente `[A,B]`,`[C,A]` → Kanten
    `{A,B},{C,A}` → `{B,C}` fehlt → **unvollständig** (nicht fälschlich komplett).
11. **Phantom-Kante über Lücke (A1, Out-and-back)**: `route=[A,B,A]` (`required={A,B}:2`), Pilot
    fliegt A→B, Lücke, erneut A→B (nie zurück). Zwei Segmente `[A,B]`,`[A,B]` → `{A,B}:2` →
    hier tatsächlich komplett? **Nein** — beide Segmente sind `A→B` (Hinflug), keiner `B→A`; die
    Kante `{A,B}` ist ungerichtet, Multiplizität 2 wird formal gedeckt. **Klärung im Test:** Das
    ungerichtete Kanten-Modell kann „zweimal hin" nicht von „hin und zurück" unterscheiden — für
    `[A,B,A]` ist das die akzeptierte Grenze des Modells (Nutzer-Entscheid Kanten/ungerichtet).
    Der Test hält dieses Verhalten bewusst fest; der praktisch relevante Rundkurs (Dreieck,
    Testfall 10) ist davon nicht betroffen.
12. **Randfälle (B5)**: `route_touch_seq`/Segment mit <2 Streckenplätzen → `achieved` leer →
    unvollständig; Ein-Platz-Route `[A]` → `required` leer → jede Tour vakuum-komplett (bewusst,
    wie heute faktisch).

Bestehende Tests in `tests/test_bummel*.py`, die die alte Knoten-Completion kodieren, werden auf die
neue Kanten-Semantik **aktualisiert** (nicht additiv gepatcht).

## Nicht im Scope

- Reihenfolge-erzwingende Wertung (geordnete Wegpunkte) — bewusst verworfen (Nutzer wählte Kanten).
- Änderungen an `canonicalize_legs`/Detektion.
- Migration/Neuberechnung bestehender (Test-)Bummel.
