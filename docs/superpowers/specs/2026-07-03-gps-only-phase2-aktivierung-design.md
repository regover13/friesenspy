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
2. **Ein Flug geht von einem Boden-Platz zum nächsten *anderen* Boden-Platz.** Man bildet die Folge der
   Boden-Plätze (jeder Vollstopp `gs < 2 kt` an einem DB-Platz im 10-km-Umkreis; sonst keine Landung —
   Außenlandungs-Regel aus Phase 1) und zieht **direkt aufeinanderfolgende Wiederholungen *desselben*
   Platzes zu einem zusammen**. Jeder **Wechsel** zum nächsten Platz = ein Flug. Daraus folgt:
   - **Platzrunden** (mehrfach am selben Platz landen) zählen als **eine** Landung dort und fügen **keinen
     Extra-Flug** hinzu — aber **jeder neue Platz trennt** und ist eine echte (Zwischen-)Landung.
   - **Touch-and-Gos** (nie `gs < 2`) sind gar keine Landung.
   - Beispiele: `EDDK`-Runden → EDDW = **EDDK→EDDW** (Runden am Startplatz verschmelzen); `A → B`-Runden
     `→ C` = **A→B, B→C** (B ist ein neuer Platz = echte Landung); reine `EDDK`-Runden = **EDDK→EDDK**.
3. **On-demand statt Speicher.** Flüge sind eine reine Sicht auf die Positionshistorie, bei Bedarf
   berechnet. Kein `gps_legs`-Table, kein Delete, keine `statsim_id`-Spalte.
4. **Zwei Klassen von Flügen.** **Gewertet** (Statistik-KPI, Bummel, Kutter): **nur `FRS*`-Callsign** —
   wie heute (FriesenSpy-Live + StatSim mit FRS-Callsign); FriesenSpy gewinnt bei cid+Zeit-Überlappung,
   StatSim füllt Lücken. **Nur Anzeige:** **Fremd-Callsign-Flüge** eines Friesen-cid (nur in StatSim,
   z. B. „DFGKC") erscheinen **ausschließlich in der Piloten-Detailansicht**, als **„nicht gewertet"
   markiert** (neues Anzeige-Feature) — NICHT in KPI/Bummel/Kutter. Die **Flugerkennung greift bei beiden**
   (Aufteilung in Flüge/Zwischenlandungen).
5. **Offener Flug** (Start real, keine Landung erkannt): zählt als Flug mit Ziel „offen" — **keine
   erfundene Ankunft**. Bummel-Tour bleibt unvollständig, Kutter keine Lieferung.
6. **Rückwirkend alles neu.** Bei Bummel/Kutter gab es bisher nur Tests → keine eingefrorenen Sieger.

## A — Flug-Modell: Runden-Collapse

**Was zählt als Landung (= Wegpunkt):** ein **Vollstopp** (`gs < 2 kt`) an einem DB-Platz (10-km-Umkreis,
AGL-Guard). Ein **Touch-and-Go** (nie `gs < 2`) taucht gar nicht auf. Eine Landung ist **sofort**
endgültig — **kein 180-s-Dwell mehr** (`_GPS_ARRIVAL_DWELL` entfällt): wiederholte Landungen am *selben*
Platz (Platzrunden, egal wie kurz der Taxi-back) fängt der `collapse_same_airport`-Schritt; ein Vollstopp
an einem *neuen* Platz ist immer eine echte Zwischenlandung. `detect_gps_legs` wird dafür minimal
angepasst (Dwell-Finalisierung raus; Landung finalisiert sofort, nächstes Abheben = neuer Roh-Leg).

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

## B — Quellen & zwei Klassen: FriesenSpy + StatSim, on-demand

**Gewertete Flüge** (`canonicalize_legs`, formgleich zu `canonicalize_flights`) — nur **`FRS*`-Callsign**,
bei jedem Aufruf frisch:

1. **FriesenSpy-Flüge:** je cid `position_history` im Fenster range-scannen → `detect_gps_legs`
   → `collapse_same_airport`.
2. **StatSim-Flüge mit `FRS`-Callsign:** je Flug `statsim_position_history` → dito. Fehlt der Track,
   **Fallback** auf den `statsim_cache`-Flugplan (dep/arr/`duration_min`), damit nie ein Flug verschwindet.
3. **Dedup / Vorrang:** gleicher realer Flug in beiden Quellen (gleicher VATSIM-cid). Bei **cid +
   Zeitüberlappung gewinnt FriesenSpy**; StatSim nur, wenn FriesenSpy im Fenster nichts hat (down). Hebt
   das bestehende `_dedup_statsim_against_fs` auf Flug-Ebene.

**Nur-Anzeige-Flüge (Fremd-Callsign)** — StatSim-Flüge eines **Friesen-cid** mit **Nicht-`FRS`-Callsign**:
separat geliefert (eigener Adapter/Flag `scored=False`), **ausschließlich für die Piloten-Detailansicht**,
nie in KPI/Bummel/Kutter. `detect_gps_legs` + `collapse_same_airport` greifen identisch (Aufteilung/
Zwischenlandungen sichtbar). **Friesen-cid** (self-maintaining): cids, die je als `FRS*` erfasst wurden /
in der Piloten-Liste stehen — nur deren Fremd-Callsign-Flüge werden überhaupt angezeigt.

**Track-Beschaffung (Pflicht):** Für **jeden StatSim-only-Flug** (FRS-Callsign wenn FriesenSpy down
*und* Fremd-Callsign) wird der GPS-Track **direkt** von der StatSim-API geladen und in
`statsim_position_history` **gespeichert** — sonst greift die Flugerkennung nicht. Gespeichert wird nur der
**Track** (Quelldaten); die Flüge/Legs bleiben **on-demand** berechnet.

**Kein Persistenz-Zustand für Flüge:** Quelle der Wahrheit ist die Positionshistorie (persistent, WAL).
Neustart/Absturz verliert nichts — der nächste Aufruf rechnet identisch neu; kein halb-geschriebener Zustand.

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

1. **Statistik-KPI** (`get_stats`, `get_stats_activity`, Bestenlisten): **nur gewertete Flüge (`FRS*`)**.
   Anzahl Flüge = Anzahl Flüge (Runden absorbiert); Distanz/Dauer aus dem echten Track. Lokalflug `A→A`
   zählt als ein Flug mit realer geflogener Distanz. Fremd-Callsign-Flüge fließen **nicht** ein.
2. **Piloten-Detail** (`/api/pilots/{cid}/flights`): zeigt die gewerteten GPS-Flüge inkl. Zwischenlandungen
   **und zusätzlich** die **Fremd-Callsign-Flüge** desselben cid, klar als **„nicht gewertet"** markiert
   (neues Anzeige-Feature; `scored`-Flag). Beide mit Flugerkennung/Aufteilung.
3. **Bummel** (`compute_bummel_standings`): Blockzeit-Summe je Tour aus den Flug-Blöcken; Zwischen-Boden-
   zeit exkludiert (behebt Bug #17 zentral). Offener Flug → Tour unvollständig (Kontroll-Liste, nicht
   gewertet). Die bereits vorhandene GPS-Endpunkt-Korrektur entfällt (die Flüge liefern dep/arr direkt).
4. **Kutter** (`compute_transport_progress`): Lieferung, wenn ein Flug **am Ziel** landet; offen/anderswo
   = keine Lieferung. Live-Latch (`transport_live_arrivals`) bleibt für Ankunft-ohne-Disconnect.

**Wegfall nach der Umstellung:** Der **Refile-Leg-Split** trennt keine Flüge mehr (GPS tut das) — die
refilte Flugplan-**Zeile bleibt** aber als Label-Zeitachse erhalten (Abschnitt G). Ebenso weg: die je
Konsument verstreute dep/arr-Korrektur und die `_BLOCK_STAND_MIN_SEC`-Heuristik — die Flüge liefern das
jetzt zentral. Der Phase-1-
`gps_legs`-Table + `recompute_gps_legs` werden überflüssig (nur das Audit nutzte sie; es rechnet ohnehin
on-demand). Sie werden entfernt oder als reines Debug-Artefakt belassen — im Plan entscheiden.

## E — Bleibt persistent (unabhängig von on-demand)

- **`position_history` / `statsim_position_history`** — Quelle der Wahrheit (Poller schreibt 15 s;
  StatSim per Backfill). Poller-Rehydration beim Start bleibt.
- **Kutter-Live-Latch** `transport_live_arrivals` — nicht aus Positionen ableitbar (live vor Disconnect).
- **`flights`** — Verbindungs-/Flugplan-Datensätze (Labels, Kutter-Reconcile).

## F — Laufende Track-Beschaffung für StatSim-only-Flüge

Über den historischen Backfill hinaus wird der GPS-Track **jedes StatSim-only-Flugs** (eines Friesen-cid,
für den es **keinen** FriesenSpy-Flug gibt — FriesenSpy down ODER Fremd-Callsign) **proaktiv/direkt** von
der StatSim-API geladen und in `statsim_position_history` gespeichert, sobald der Flug importiert wird
(nicht erst beim Track-Ansehen). Nur so greift die Flugerkennung für diese Flüge. Zwei Verwendungen:
- **FRS-Callsign, FriesenSpy down** → **gewertet** (füllt die Erfassungslücke; KPI/Bummel/Kutter).
- **Fremd-Callsign** → **nur Anzeige** im Piloten-Detail („nicht gewertet"), aber mit Aufteilung.

Mechanik: der bestehende Backfill-Endpoint + die per-Pilot-StatSim-Fetch-Logik stellen den Track sicher
(gedrosselt, idempotent). Die Legs bleiben on-demand.

## G — Flugplan-Zuordnung & Anzeige

**Anzeige — GPS *und* Plan nebeneinander.** Jede Listenzeile = ein GPS-Flug (Bein):
- **GPS-Start→Ziel** = die klickbare Route-Zelle (blau), Klick → Track **genau dieses Beins**
  (`[takeoff_ts, landing_ts]`). **Immer vorhanden** (aus dem Track) — die Anzeige hängt nicht mehr am Plan.
- **Flugplan-Start→Ziel** daneben als Kontext; `—`, wenn kein passender Plan. Route/Remarks/Muster als
  Label vom zugeordneten Plan (**StatSim liefert nur Muster + Start→Ziel, keine Route/Remarks**).

**Zuordnung Plan → Bein — Startplatz-primär (zeit-robust):**
1. **Startplatz-Match (primär):** der Flugplan der Verbindung, dessen *gefilter Startplatz* == GPS-
   Startplatz des Beins. Robust gegen **späten/vergessenen Refile**: ein erst in der Luft aufgegebener
   B→C-Plan sagt trotzdem „Start B" → matcht das B→C-Bein, unabhängig vom Zeitpunkt.
2. **Zeit-Fallback:** kein Startplatz-Match → zeitlich nächster Plan der Verbindung.
3. **Kein Match / kein Plan → `—`.** Z. B. VFR ohne Plan; oder nur *ein* Plan A→C gefiled, GPS macht
   A→B→C → das B→C-Bein bekommt `—` (kein erzwungenes Fehl-Label; der Pilot hat B→C nie gefiled).

**Datenbasis:** die Folge der `flights`/Prefile-Datensätze je Verbindung (jeder Refile = eigener
Zeitstempel + gefilter dep/arr) bleibt als **Flugplan-Zeitachse** erhalten — nicht mehr als Leg-Grenze,
nur fürs Labeln. StatSim liefert dep/arr/Muster aus `statsim_cache`.

**Nur Label, nie Wertung:** Die Zuordnung beeinflusst ausschließlich die Anzeige. KPI/Bummel/Kutter
laufen rein über GPS — eine gelegentliche Fehl-/`—`-Zuordnung des Plan-Labels kostet nie Punkte.

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
- **Disconnect + Reconnect:** eine Positions-Lücke im Track. `detect_gps_legs` trennt bei **Lücke > 30 min**
  (`gap_minutes`, justierbar) in getrennte Flüge; eine Lücke **≤ 30 min** wird überbrückt = derselbe Flug
  fortgesetzt. Landet der Pilot vor dem Disconnect an einem Platz und kommt später wieder, ist die Landung
  ohnehin ein echter Wegpunkt (Trennung deckt sich mit der Realität). Reconnect **in der Luft** binnen
  30 min → ein durchgehender Flug; nach > 30 min → 1. Segment endet „offen", 2. beginnt als Spawn-in-Luft.
- **Absturz *abseits* eines Platzes** (`gs → 0`, kein DB-Platz im Umkreis) → **keine** Landung (per GPS
  nicht von Pause/Slew/Außenlandung unterscheidbar) → Flug bleibt **offen** (Ziel „offen", nicht als Ankunft
  gewertet). **Absturz *an/nahe* einem Platz** ist per GPS **nicht** von einer normalen Landung zu trennen
  (`gs → 0` am Platz) → wird als Ankunft dort gezählt (ehrliche GPS-Grenze).

## Testing

- **`collapse_same_airport`** (rein, TDD): alle Tabellen-Beispiele oben (Runden am Start/Ziel/beides,
  reine Runden, Zwischenlandung mit/ohne Runden, offener Schluss).
- **`canonicalize_legs`**: Feld-für-Feld-Parität mit `canonicalize_flights`; nur `FRS`-Callsign gewertet;
  StatSim-Fallback ohne Track; Dedup FriesenSpy-gewinnt bei Überlappung.
- **Zwei-Klassen-Trennung**: Fremd-Callsign-Flug eines Friesen-cid erscheint im Piloten-Detail mit
  `scored=False`, aber **nicht** in KPI/Bummel/Kutter (je ein Test pro Konsument, dass er ausgeschlossen ist).
- **Flugplan-Zuordnung**: Startplatz-Match; **spät/in-der-Luft aufgegebener Refile** landet am richtigen
  Bein; ein Plan A→C + GPS A→B→C → B→C-Bein zeigt `—`; VFR ohne Plan → `—`; StatSim → dep/arr/Muster gesetzt.
- **Konsumenten**: `get_stats`/Bummel/Kutter mit Flügen; Bummel-„Frode"-E2E; Vorher/Nachher-Zahlvergleich
  vor der Umstellung je Konsument.

## Abgrenzung / YAGNI

- Kein `gps_legs`-Speicher, keine Migration, kein Delete-Scoping (durch on-demand entfallen). Gespeichert
  wird nur der **Track** (`statsim_position_history`), nicht die Flüge.
- **Fremd-Callsign-Flüge werden nicht gewertet** (nur Anzeige) — kein Poller-Umbau, kein cid-basiertes
  Live-Tracking. Live-Erfassung bleibt `FRS*`-gefiltert wie heute.
- Kein manuelles Friesen-cid-Listing (self-maintaining über bekannte cids).
- Kein Einfrieren alter Events (nur Tests bisher).
