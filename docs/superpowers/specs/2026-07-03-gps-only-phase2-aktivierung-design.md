# GPS-only aktivieren (Phase 2) — Design-Spec

> Freigegebenes Design (Brainstorming, 2026-07-03). Aktiviert die im Schatten validierte
> GPS-Flugerkennung als **einzige Wahrheit** für Statistik, Piloten-Detail, Bummel und Kutter.
> Ersetzt/aktualisiert den Phase-2-Teil von `docs/superpowers/plans/2026-07-02-gps-leg-detection.md`.

## Ziel

Flüge, Ziele und Blockzeiten kommen **rein aus GPS** (Position → Landung am Platz), nicht mehr aus
Refile-Split oder Disconnect. Der Flugplan liefert nur noch Labels (Route/Remarks/Callsign/Muster).
StatSim wird gleichberechtigt einbezogen und füllt Lücken der FriesenSpy-Erfassung.

## Kern-Entscheidungen (Nutzer, 2026-07-03)

1. **Ein „Flug", eine Einheit.** Keine Trennung Flug/Etappe — alles heißt Flug.
2. **Ein Flug geht von einem Platz zum nächsten *anderen* Platz.** Trenner ist eine **echte Landung =
   Vollstopp (`gs < 2 kt`) an einem Platz, dessen ICAO sich vom *letzten Boden-Platz* unterscheidet**
   (im 10-km-Umkreis eines DB-Platzes; sonst keine Landung — Außenlandungs-Regel aus Phase 1). Das *ist*
   zugleich die Definition einer echten Zwischenlandung. **Keinen** neuen Flug erzeugen nur: (a)
   **wiederholte Vollstopps am *selben* Platz** (Platzrunden/Taxi-back — am Start, an einem Zwischenstopp
   oder am Ziel) → kollabieren zu einem Wegpunkt; und (b) **Touch-and-Gos** (nie `gs < 2` → gar keine
   Landung). Ein Vollstopp an einem **neuen** Platz trennt **immer** — auch wenn dort zusätzlich Runden
   gedreht werden.
3. **On-demand statt Speicher.** Flüge sind eine reine Sicht auf die Positionshistorie, bei Bedarf
   berechnet. Kein `gps_legs`-Table, kein Delete, keine `statsim_id`-Spalte.
4. **Friese = bekannter cid** (je als FRS* geflogen / in der Piloten-Liste). Dessen StatSim-Flüge zählen,
   auch unter Fremd-Callsign. FriesenSpy gewinnt bei Überlappung, StatSim füllt Lücken.
5. **Offener Flug** (Start real, keine Landung erkannt): zählt als Flug mit Ziel „offen" — **keine
   erfundene Ankunft**. Bummel-Tour bleibt unvollständig, Kutter keine Lieferung.
6. **Rückwirkend alles neu.** Bei Bummel/Kutter gab es bisher nur Tests → keine eingefrorenen Sieger.

## A — Flug-Modell: Runden-Collapse

**Was zählt als Landung (= Wegpunkt):** `detect_gps_legs` (bestehend, unverändert) erzeugt einen Roh-Leg
nur bei einem **Vollstopp** (`gs < 2 kt`) an einem DB-Platz. Ein **Touch-and-Go** (nie `gs < 2`) taucht
gar nicht auf. Eine Landung wird zudem erst **endgültig**, wenn danach **nicht binnen `_GPS_ARRIVAL_DWELL`
(180 s)** wieder abgehoben wird — ein schneller Turnaround (< 180 s) gilt als Stop-and-Go derselben
Session (kein Wegpunkt); ein echter Zwischenstopp (Tanken/Pause, > 180 s) an einem *anderen* Platz **ist**
die Zwischenlandung. So wird sie bestimmt: Vollstopp > 180 s an einem Platz ≠ letzter Boden-Platz.
Schwelle justierbar, falls sehr kurze echte Stopps auch zählen sollen.

`detect_gps_legs` liefert pro Verbindung eine Liste von Roh-Legs (Abheben → Vollstopp-Landung). Ein
**Nachschritt** `collapse_same_airport(legs)` fasst zusammen:

- Bilde die Platz-Zeitachse `[dep₀, arr₀, arr₁, …]` (Legs sind kontig: `legᵢ.dep == legᵢ₋₁.arr`).
- Ziehe **aufeinanderfolgende gleiche Plätze** zusammen → Folge distinkter Plätze `[D₀, D₁, …]`.
- Jeder Wechsel `Dᵢ → Dᵢ₊₁` = **ein Flug**: `takeoff_ts` = erstes Abheben aus dem `Dᵢ`-Cluster,
  `landing_ts` = Landung bei `Dᵢ₊₁`. Nur ein distinkter Platz + gelandet → `D₀→D₀`; endet in der Luft →
  `Dlast→offen`.

Beispiele (verifiziert gewünscht):

| Verlauf | Ergebnis |
|---|---|
| EDDK-Runden (Vollstopp) → EDDW | **EDDK→EDDW** (1 Flug) |
| EDDK → EDDW mit Runden vor Landung | **EDDK→EDDW** |
| EDDK-Runden → EDDW-Runden | **EDDK→EDDW** |
| reine EDDK-Runden | **EDDK→EDDK** |
| EDPS → **Vollstopp(-Runden) an EDNX** → EDMA | **EDPS→EDNX**, **EDNX→EDMA** (2 Flüge — EDNX ist echte Zwischenlandung) |
| EDPS → **Touch-and-Go an EDNX** (kein Vollstopp) → EDMA | **EDPS→EDMA** (1 Flug — keine Landung an EDNX) |

`block_sec`/`duration_min`/`distance_nm` je Flug über das Fenster `[takeoff_ts, landing_ts]` (bestehende
Helfer `_block_seconds`/`_gps_distance_nm`); Runden-Bodenzeit innerhalb des Fensters ist vernachlässigbar
und wird bewusst nicht herausgerechnet. „Anzahl Flüge" = Anzahl so gebildeter Flüge.

## B — Quellen: FriesenSpy + StatSim, on-demand

`canonicalize_legs(conn, *, cids, start, end, callsign_prefix)` berechnet die Flüge **bei jedem Aufruf**:

1. **Friesen-cids bestimmen:** cids, die je als `FRS*` erfasst wurden bzw. in der Piloten-Liste stehen
   (self-maintaining; kein manuelles Listen). Nur diese werden gewertet — auch ihre Fremd-Callsign-Flüge.
2. **FriesenSpy-Flüge:** je cid `position_history` im Fenster range-scannen → `detect_gps_legs`
   → `collapse_same_airport`.
3. **StatSim-Flüge:** je StatSim-Flug des cid `statsim_position_history` → `detect_gps_legs`
   → `collapse_same_airport`. Fehlt der Track (nicht gebackfillt), **Fallback** auf den
   `statsim_cache`-Flugplan-Datensatz (dep/arr/`duration_min`), damit nie ein StatSim-Flug verschwindet.
4. **Dedup / Vorrang:** derselbe reale Flug kann in beiden Quellen liegen (gleicher VATSIM-cid). Bei
   **cid + Zeitüberlappung gewinnt FriesenSpy**; StatSim wird nur genommen, wenn FriesenSpy in dem Fenster
   nichts hat (down oder Fremd-Callsign). Hebt das bestehende `_dedup_statsim_against_fs` auf Flug-Ebene.

**Kein Persistenz-Zustand:** Quelle der Wahrheit ist die Positionshistorie (persistent, WAL). Neustart/
Absturz verliert nichts — der nächste Aufruf rechnet identisch neu; kein halb-geschriebener Zustand.

## C — Adapter `canonicalize_legs` (formgleich)

Liefert **exakt die Dict-Form** von `canonicalize_flights` → alle Konsumenten bleiben unverändert:

- `departure = dep_icao`, `arrival = arr_icao` (leer = offen), `logon_time = takeoff_ts`,
  `logoff_time = landing_ts`, `block_min = block_sec // 60`, `duration_min`, `distance_nm`, `source`.
- `route`/`remarks`/`callsign`/`aircraft` vom überlappenden `flights`- bzw. `statsim_cache`-Record
  (Flugplan = nur Label), verknüpft über den Verbindungs-Logon.
- **Optionaler Cache nur für die globale Statistik** (alle Piloten/ganze Historie ~1–3 s): kurzer
  In-Memory-Cache mit TTL; nach Neustart kalt → eine langsamere Statistik-Seite, dann warm. Event-
  scoped Aufrufe (Bummel/Kutter/Piloten-Detail) brauchen keinen Cache.

## D — Konsumenten-Verhalten

Umstellung von `canonicalize_flights` auf `canonicalize_legs` in dieser Reihenfolge (je Vorher/Nachher-
Zahlvergleich):

1. **Statistik** (`get_stats`, `get_stats_activity`): Anzahl Flüge = Anzahl Flüge (Runden absorbiert);
   Distanz/Dauer aus dem echten Track. Lokalflug `A→A` zählt als ein Flug mit realer geflogener Distanz.
2. **Piloten-Detail** (`/api/pilots/{cid}/flights`): zeigt die GPS-Flüge inkl. Zwischenlandungen.
3. **Bummel** (`compute_bummel_standings`): Blockzeit-Summe je Tour aus den Flug-Blöcken; Zwischen-Boden-
   zeit exkludiert (behebt Bug #17 zentral). Offener Flug → Tour unvollständig (Kontroll-Liste, nicht
   gewertet). Die bereits vorhandene GPS-Endpunkt-Korrektur entfällt (die Flüge liefern dep/arr direkt).
4. **Kutter** (`compute_transport_progress`): Lieferung, wenn ein Flug **am Ziel** landet; offen/anderswo
   = keine Lieferung. Live-Latch (`transport_live_arrivals`) bleibt für Ankunft-ohne-Disconnect.

**Wegfall nach der Umstellung:** Refile-Leg-Split (poller.py), die je Konsument verstreute dep/arr-
Korrektur, die `_BLOCK_STAND_MIN_SEC`-Heuristik — die Flüge liefern das jetzt zentral. Der Phase-1-
`gps_legs`-Table + `recompute_gps_legs` werden überflüssig (nur das Audit nutzte sie; es rechnet ohnehin
on-demand). Sie werden entfernt oder als reines Debug-Artefakt belassen — im Plan entscheiden.

## E — Bleibt persistent (unabhängig von on-demand)

- **`position_history` / `statsim_position_history`** — Quelle der Wahrheit (Poller schreibt 15 s;
  StatSim per Backfill). Poller-Rehydration beim Start bleibt.
- **Kutter-Live-Latch** `transport_live_arrivals` — nicht aus Positionen ableitbar (live vor Disconnect).
- **`flights`** — Verbindungs-/Flugplan-Datensätze (Labels, Kutter-Reconcile).

## F — Laufender StatSim-Lückenfüller

Über den historischen Backfill hinaus: Wenn zu einem StatSim-Flug eines Friesen-cid **kein** FriesenSpy-
Flug existiert (FriesenSpy down ODER Fremd-Callsign), wird sein Track sichergestellt (via bestehendem
Backfill/Fetch-Cache), damit `canonicalize_legs` die Flüge on-demand bilden kann. Trigger = genau die
StatSim-Flüge, die die Dedup als „nicht durch FriesenSpy gedeckt" durchlässt.

## Aktivierung & Verifikation

- **Rückwirkend alles neu** (nur Tests bisher). Schrittweise Umstellung mit Vorher/Nachher-Zahlvergleich
  je Konsument.
- **Bummel-E2E „Frode":** landet am Ziel, bleibt verbunden → erscheint mit korrekter Blockzeit (Flug-
  Fenster), OHNE Disconnect.
- Release **v7.10.0** (Wertungsänderung → Minor/highlight). Docs (README, api.md, architecture.md),
  Deploy Push→Actions→GHCR→SSH + Health-Check, Tag.

## Fehlerbehandlung

- Keine Positionen für einen cid → keine Flüge (kein Fehler).
- StatSim ohne Track → Flugplan-Fallback (`statsim_cache`), Flug bleibt gelistet.
- Spawn-in-der-Luft (`dep = None`) → Ziel bekannt, dep-Label aus Flugplan; ohne Flugplan bleibt dep leer.
- Off-Airport-Landung / kein Platz im Umkreis → **keine** Landung (Absturz-Ambiguität, unverändert aus
  Phase 1) → Flug bleibt offen.

## Testing

- **`collapse_same_airport`** (rein, TDD): alle Tabellen-Beispiele oben (Runden am Start/Ziel/beides,
  reine Runden, Zwischenlandung mit/ohne Runden, offener Schluss).
- **`canonicalize_legs`**: Feld-für-Feld-Parität mit `canonicalize_flights`; StatSim-Fallback ohne Track;
  Dedup FriesenSpy-gewinnt bei Überlappung; Friese-per-cid inkl. Fremd-Callsign.
- **Konsumenten**: `get_stats`/Bummel/Kutter mit Flügen; Bummel-„Frode"-E2E; Vorher/Nachher-Zahlvergleich
  vor der Umstellung je Konsument.

## Abgrenzung / YAGNI

- Kein `gps_legs`-Speicher, keine Migration, kein Delete-Scoping (durch on-demand entfallen).
- Kein manuelles Friesen-cid-Listing (self-maintaining über bekannte cids).
- Kein Einfrieren alter Events (nur Tests bisher).
