# GPS-only aktivieren (Phase 2) — Design-Spec

> Freigegebenes Design (Brainstorming 2026-07-03) **+ eingearbeitetes Review** (Fable5, 2026-07-03).
> Aktiviert die im Schatten validierte GPS-Flugerkennung als **einzige Wahrheit** für Statistik,
> Piloten-Detail, Bummel und Kutter. Ersetzt/aktualisiert den Phase-2-Teil von
> `docs/superpowers/plans/2026-07-02-gps-leg-detection.md`.
>
> **Review-Einarbeitung:** (a) Blockzeit behält Stand-Ausschluss (Widerspruch zu #17 behoben);
> (b) symmetrischer `flights`-Fallback für track-lose Connections; (c) Kutter-Latch/Loss-Reconcile;
> (d) Audit auf collapsed/no-180s + on-demand **plus persistenter Ergebnis-Cache**; (e) Fremd-Callsign-
> Anzeige und (f) proaktiver Per-Import-Fetch → **Phase 2b**; (g) stille Semantik-Änderungen benannt.

## Ziel

Flüge, Ziele und Blockzeiten kommen **rein aus GPS** (Position → Landung am Platz), nicht mehr aus
Refile-Split oder Disconnect. Der Flugplan liefert nur noch Labels (Route/Remarks/Callsign/Muster).
StatSim wird gleichberechtigt einbezogen und füllt Lücken der FriesenSpy-Erfassung.

## Kern-Entscheidungen (Nutzer, 2026-07-03; Review eingearbeitet)

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
3. **On-demand-Berechnung + persistenter Ergebnis-Cache.** Quelle der Wahrheit sind die **Positionen**;
   Flüge werden bei Bedarf daraus berechnet (`detect_gps_legs` + Collapse). Für die **globale Statistik**
   und eine **stabile, prüfbare Sicht** (Audit/GATE) werden die fertigen (collapsed) Flüge **materialisiert
   zwischengespeichert** und **inkrementell nachgezogen** — kein Roh-`gps_legs`-Leg-Table mehr, aber auch
   kein reines on-demand über die unbegrenzt wachsende `position_history` (siehe C/Performance).
4. **Gewertet = nur `FRS*`-Callsign** (wie heute): FriesenSpy-Live + StatSim mit FRS-Callsign; FriesenSpy
   gewinnt bei cid+Zeit-Überlappung, StatSim füllt Lücken. Fremd-Callsign-Flüge werden in Phase 2 **wie
   heute nicht einbezogen**; die optionale **Nur-Anzeige** im Piloten-Detail ist **Phase 2b** (siehe unten).
5. **Offener Flug** (Start real, keine Landung erkannt): zählt als Flug mit Ziel „offen" — **keine
   erfundene Ankunft** — **aber erst, wenn die Verbindung beendet ist** (nicht live während des laufenden
   Fluges, sonst hüpft die KPI live). Bummel-Tour bleibt unvollständig, Kutter keine Lieferung.
6. **Rückwirkend alles neu.** Bei Bummel/Kutter gab es bisher nur Tests → keine eingefrorenen Sieger. Die
   **Statistik-Historie** bleibt trotzdem vollständig: Connections/StatSim-Flüge **ohne verwertbaren Track**
   werden per Flugplan-Fallback (Punkt b) übernommen, verschwinden also nicht.

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

**Blockzeit/Dauer je Flug (Review a — Widerspruch zu #17 behoben):**
- `duration_min` = `landing_ts − takeoff_ts` (bewusste Semantik-Änderung, siehe unten).
- `block_sec` über das collapsed Fenster **mit Stand-Ausschluss** — die Stand-Heuristik `_BLOCK_STAND_MIN_SEC`
  **bleibt** (entgegen der ersten Fassung). Sonst würde `collapse_same_airport` einen langen Bodenstand am
  *selben* Platz (z. B. Vormittags-Runden in A, 3 h Mittagspause am Boden in A, nachmittags Flug nach B ⇒
  ein Flug `A→B`) voll in die Blockzeit rechnen — genau **Bug #17 durch die Hintertür**. Mit Stand-Ausschluss
  zählen kurze Bewegungen/Taxi, lange Bodenstände werden herausgerechnet → gate-to-gate bleibt korrekt,
  auch bei Same-Airport-Stopps.

## B — Quellen & Wertungsklasse: FriesenSpy + StatSim

`canonicalize_legs(conn, *, cids, start, end, callsign_prefix)` liefert die **gewerteten** Flüge
(nur `FRS*`-Callsign), formgleich zu `canonicalize_flights`:

1. **FriesenSpy-Flüge:** je cid `position_history` im Fenster range-scannen → `detect_gps_legs`
   → `collapse_same_airport`.
2. **StatSim-Flüge mit `FRS`-Callsign:** je Flug `statsim_position_history` → dito.
3. **Fallback ohne verwertbaren Track (Review b — symmetrisch!):**
   - **StatSim ohne Track** → `statsim_cache`-Flugplan (dep/arr/`duration_min`).
   - **FriesenSpy-Connection ohne verwertbaren Track** (Poller-Downtime mitten im Flug, Track-Lücke > 30 min,
     frühe Flüge vor der Positionserfassung) → die **`flights`-Zeile** wird als Flug übernommen
     (dep/arr/`duration_min` aus dem Flugplan). So **verschwindet kein Alt-/Downtime-Flug** aus KPI/Detail
     — der heutige Ghost-Schutz von `canonicalize_flights` bleibt erhalten.
4. **Dedup / Vorrang:** gleicher realer Flug in beiden Quellen (gleicher VATSIM-cid). Bei **cid +
   Zeitüberlappung gewinnt FriesenSpy**; StatSim nur, wenn FriesenSpy im Fenster nichts hat (down). Hebt
   das bestehende `_dedup_statsim_against_fs` auf Flug-Ebene. **Teil-Überlappung** (FriesenSpy deckt nur
   einen Teil der StatSim-Session) darf den nicht gedeckten StatSim-Teil **nicht** verlieren (Testfall).

**Track-Beschaffung:** Für StatSim-only-Flüge (FriesenSpy down) muss der GPS-Track in
`statsim_position_history` vorliegen; das leistet der **bestehende Bulk-Backfill-Endpoint** (v7.9.3/7.9.4,
gedrosselt/resumebar), in Phase 2 periodisch angestoßen. Der **proaktive Fetch je Import** ist **Phase 2b**.

**Persistenz:** Quelle der Wahrheit sind die Positionen; die berechneten Flüge werden für die globale
Statistik/Audit **materialisiert gecacht** (Kern-Entscheidung 3) — Neustart verliert nur den Cache
(wird neu aufgebaut), nie Quelldaten.

## C — Adapter `canonicalize_legs` (formgleich) + Ergebnis-Cache

Liefert **exakt die Dict-Form** von `canonicalize_flights` → alle Konsumenten bleiben unverändert:

- `departure = dep_icao`, `arrival = arr_icao` (leer = offen), `logon_time = takeoff_ts`,
  `logoff_time = landing_ts`, `block_min = block_sec // 60`, `duration_min`, `distance_nm`, `source`.
- `route`/`remarks`/`callsign`/`aircraft` vom zugeordneten Flugplan (Abschnitt G).
- **Persistenter Ergebnis-Cache (Review d/Performance):** `position_history` wächst unbegrenzt
  (`daily_cleanup` ist aus). Reines on-demand über die *ganze* Historie würde jedes Jahr langsamer, ein
  In-Memory-TTL-Cache hilft nur bei Wiederholung, nicht beim Kaltstart. Daher werden die fertigen
  (collapsed) Flüge in einer **materialisierten Tabelle** gehalten und **inkrementell** aktualisiert
  (nur neue/offene Verbindungen neu rechnen; abgeschlossene stabil). Event-scoped Aufrufe
  (Bummel/Kutter/Piloten-Detail) können weiter direkt on-demand rechnen (wenige cids/Zeitfenster).

## D — Konsumenten-Verhalten

Umstellung von `canonicalize_flights` auf `canonicalize_legs` in dieser Reihenfolge (je Vorher/Nachher-
Zahlvergleich):

1. **Statistik-KPI** (`get_stats`, `get_stats_activity`, Bestenlisten): **nur gewertete Flüge (`FRS*`)**.
   Anzahl Flüge = Anzahl Flüge (Runden absorbiert); Distanz/Dauer aus dem echten Track. Lokalflug `A→A`
   zählt als ein Flug. Offene Flüge zählen erst bei **beendeter Verbindung** (Kern 5).
2. **Piloten-Detail** (`/api/pilots/{cid}/flights`): zeigt die gewerteten GPS-Flüge inkl. Zwischenlandungen.
   (Die zusätzliche **Fremd-Callsign-Anzeige** „nicht gewertet" ist **Phase 2b**.)
3. **Bummel** (`compute_bummel_standings`): Blockzeit-Summe je Tour aus den Flug-Blöcken **mit Stand-
   Ausschluss** (Abschnitt A) — behebt Bug #17 zentral, auch bei Same-Airport-Stopps. Offener Flug → Tour
   unvollständig (Kontroll-Liste, nicht gewertet). Die verstreute GPS-Endpunkt-Korrektur entfällt (die
   Flüge liefern dep/arr direkt).
4. **Kutter** (`compute_transport_progress`): Lieferung, wenn ein Flug **mit Start UND Ziel auf der Strecke**
   (`dep ≠ arr`) am `destination` landet — die heutige Strecken-Bedingung **bleibt** (sonst würde ein
   Zubringer/Spawn neben dem Ziel liefern). **Latch/Loss-Reconcile (Review c):** `transport_live_arrivals`
   **und** `transport_cargo_losses` sind auf `(cid, logon_time = Verbindungs-Logon)` gekeyt, `canonicalize_legs`
   setzt aber `logon_time = takeoff_ts`. Beide Latches werden dem GPS-Flug per **cid + Zeitfenster-Überlappung**
   zugeordnet (Verbindungs-Logon ↔ überlappender GPS-Flug), sonst gehen live gelatchte Ankünfte/Verluste
   verloren.

**Wegfall nach der Umstellung:** Der **Refile-Leg-Split** trennt keine Flüge mehr (GPS tut das) — die
refilte Flugplan-**Zeile bleibt** als Label-Zeitachse (Abschnitt G). Ebenso weg: die je Konsument
verstreute dep/arr-Korrektur. **`_BLOCK_STAND_MIN_SEC` bleibt** (Korrektur ggü. erster Fassung, Review a).
Der Phase-1-`gps_legs`-Table + `recompute_gps_legs` werden durch die **materialisierte Flug-Sicht** (C)
ersetzt; der **Audit-Endpoint** wird entsprechend umgebaut (siehe GATE).

## E — Bleibt persistent

- **`position_history` / `statsim_position_history`** — Quelle der Wahrheit (Poller 15 s; StatSim-Backfill).
- **Kutter-Latches** `transport_live_arrivals`, `transport_cargo_losses` — nicht aus Positionen ableitbar.
- **`flights`** — Verbindungs-/Flugplan-Datensätze (Labels, Fallback b, Latch-Reconcile c).
- **Materialisierte Flug-Sicht (Cache)** — abgeleitet, jederzeit aus den Positionen neu baubar.

## F — StatSim-Track-Beschaffung (Bulk)

Für StatSim-only-Flüge (FriesenSpy down, FRS-Callsign) muss der Track lokal vorliegen. Das leistet der
bestehende **Bulk-Backfill** (`POST /api/admin/statsim-backfill`, gedrosselt, resumebar, Hintergrund-Modus)
— in Phase 2 periodisch/als Job angestoßen. Legs bleiben abgeleitet. *(Proaktiver Fetch je Import → Phase 2b.)*

## G — Flugplan-Zuordnung & Anzeige

**Anzeige — GPS *und* Plan nebeneinander.** Jede Listenzeile = ein GPS-Flug (Bein):
- **GPS-Start→Ziel** = die klickbare Route-Zelle (blau), Klick → Track **genau dieses Beins**
  (`[takeoff_ts, landing_ts]`). **Immer vorhanden** (aus dem Track) — die Anzeige hängt nicht mehr am Plan.
- **Flugplan-Start→Ziel** daneben als Kontext; `—`, wenn kein passender Plan. Route/Remarks/Muster als
  Label vom zugeordneten Plan (**StatSim liefert nur Muster + Start→Ziel, keine Route/Remarks**).

**Zuordnung Plan → Bein — zeitbasiert (Nutzer-Entscheidung 2026-07-05, ersetzt die ursprüngliche
Startplatz-primäre Regel):**
1. **Zuletzt gefilter Plan zum Landungszeitpunkt (primär und einzige Regel):** bei Landung eines
   GPS-Beins (bzw. am geschätzten Ende `end_ts` eines noch offenen Beins) zählt die `flights`-Zeile
   mit dem größten `logon_time <= end_ts` — unabhängig davon, ob deren gefilter Start/Ziel zum
   GPS-Start/Ziel dieses Beins passt. Der Plan bleibt gültig, bis ein späteres Filing (spätere Zeile)
   ihn ablöst. Beispiel (der ursprüngliche FRS96-Bugreport-Fall): nur *ein* Plan A→C gefiled, GPS
   macht A→B→C (Zwischenlandung ohne Refile) → BEIDE Beine (A→B und B→C) bekommen denselben Plan A→C
   zugeordnet, statt dass das B→C-Bein leer bleibt.
2. **Kein Tie-Breaker nötig:** `(cid, logon_time)` ist durch den partiellen Unique-Index
   `idx_flights_session` bereits eindeutig — zwei Zeilen derselben cid können nie dasselbe
   `logon_time` tragen.
3. **Kein Match / kein Plan → `—`.** Das gilt (a) wenn zum Landungszeitpunkt noch KEIN Plan gefiled
   war (`end_ts` liegt vor der ersten Zeile), und (b) wenn die zeitlich letzte Zeile ein reiner
   Connect ohne jemals gefileten Plan ist (`departure` UND `arrival` beide leer) — ein solcher Connect
   zählt bewusst NICHT als Treffer, sonst entstünde am Beginn jeder neuen Verbindung fälschlich eine
   „leere" Zuordnung statt `—`.
4. **Bewusst akzeptierter Sonderfall (kein Schutz eingebaut):** filed ein Pilot den nächsten Plan
   bereits, BEVOR er im aktuellen Ziel gelandet ist (Start-Wechsel-Refile mitten im Flug), bekommt
   das noch nicht gelandete aktuelle Bein bereits den NEUEN Plan zugeordnet — sichtbar als Mismatch
   zwischen `plan_departure` und `gps_departure`. Das ist ein klarer Pilotenfehler und darf laut
   Entscheidung vom 2026-07-05 ausdrücklich sichtbar sein; die rechtzeitige Nachmeldung eines
   vergessenen Refiles ist dagegen der Normalfall, den die Regel abbildet.

**Datenbasis:** die Folge der `flights`/Prefile-Datensätze je Verbindung (jeder Refile = eigener
Zeitstempel + gefilter dep/arr) bildet bereits eine natürliche, chronologisch sortierte
**Flugplan-Zeitachse** (SQL liefert sie via `ORDER BY cid, logon_time`) — genau diese Zeitachse ist
jetzt die alleinige Grundlage der Zuordnung (nicht mehr Startplatz-Vergleich). StatSim liefert
dep/arr/Muster aus `statsim_cache` (dort immer genau eine Zeile je Session, kein Refile-Verlauf).

**Nur Label, nie Wertung:** Die Zuordnung beeinflusst ausschließlich die Anzeige.

## Bewusste Semantik-Änderungen (Review g)

- **`duration_min`: online (logon→logoff) → takeoff→landing.** Die Stunden-KPI **schrumpft rückwirkend**
  (Taxi-/Standzeit raus). Inhaltlich sinnvoller („echte Flugzeit"), aber bewusst so entschieden.
- **Offene Flüge zählen mit** (heute filtert `logoff_time IS NOT NULL` sie weg) — **aber nur bei beendeter
  Verbindung** (Kern 5), damit die KPI-Zahl nicht live während eines Fluges hüpft. „Frode" (gelandet) ist
  ohnehin complete.
- **`block_sec` behält den Stand-Ausschluss** (gate-to-gate inkl. Taxi, ohne lange Stände) — siehe A.

## Aktivierung & Verifikation

- **GATE-Erweiterung (Review d — PFLICHT vor Aktivierung):** Das Audit muss die **collapsed + no-180s**-Sicht
  zeigen (also genau das Aktivierungsverhalten), nicht mehr die Roh-Legs. Der Audit-Endpoint wird von
  `recompute_gps_legs` + Tabelle auf die neue materialisierte/`canonicalize_legs`-Sicht umgebaut. Erst
  danach validiert das GATE, was tatsächlich aktiviert wird (die bisherigen Roh-Leg-Zahlen — inkl. der
  „95,8 % sauber"-Stichprobe — gelten nur für die Roh-Sicht und sind neu zu ziehen).
- **Rückwirkend alles neu**; schrittweise Umstellung mit Vorher/Nachher-Zahlvergleich je Konsument.
- **Bummel-E2E „Frode":** landet am Ziel, bleibt verbunden → erscheint mit korrekter Blockzeit ohne Disconnect.
- Release **v8.0.0** (Major/highlight — Kern-Wahrheit ändert sich, Historie rückwirkend neu). Docs
  (README, api.md, architecture.md), Deploy
  Push→Actions→GHCR→SSH + Health-Check, Tag.

## Nicht in Phase 2 — Folgeschritt (Phase 2b)

Damit Phase 2 schlank **„nur GPS für FRS"** bleibt (Review e/f):
- **Fremd-Callsign-Anzeige** im Piloten-Detail: neue Anzeige-Klasse `scored=False`, Friesen-cid-Erkennung,
  UI-Kennzeichnung „nicht gewertet". Berührt die Wertung nicht (Fremd-Callsign bleibt in Phase 2 einfach
  ausgeschlossen wie heute).
- **Proaktive StatSim-Track-Beschaffung je Import** (Automatik). Für „FRS-Callsign, FS down" reicht in
  Phase 2 der periodische Bulk-Backfill.

## Fehlerbehandlung

- Keine Positionen für einen cid → keine GPS-Flüge; `flights`-Fallback (b) greift für gelistete Connections.
- Spawn-in-der-Luft (`dep = None`) → Ziel bekannt, dep-Label aus Flugplan; ohne Flugplan bleibt dep leer.
- **Disconnect + Reconnect:** Positions-Lücke. `detect_gps_legs` trennt bei **Lücke > 30 min**
  (`gap_minutes`, justierbar); Lücke **≤ 30 min** wird überbrückt = ein Flug. Landung vor dem Disconnect =
  echter Wegpunkt (Trennung deckt sich mit der Realität). Reconnect **in der Luft** binnen 30 min → ein
  durchgehender Flug; nach > 30 min → 1. Segment „offen", 2. beginnt als Spawn-in-Luft.
- **Absturz *abseits* eines Platzes** (`gs → 0`, kein DB-Platz im Umkreis) → **keine** Landung → Flug bleibt
  **offen** (nicht als Ankunft gewertet). **Absturz *an/nahe* einem Platz** ist per GPS nicht von einer
  Landung zu trennen → wird als Ankunft gezählt (ehrliche GPS-Grenze).

## Testing

- **`collapse_same_airport`** (rein, TDD): alle Tabellen-Beispiele (Runden am Start/Ziel/beides, reine
  Runden, Zwischenlandung mit/ohne Runden, offener Schluss); no-180s (sofortige Finalisierung).
- **Blockzeit (Review a):** collapsed Flug mit langem Same-Airport-Stand → Stand wird **ausgeschlossen**
  (`block_sec` enthält die 3-h-Pause NICHT); `block_min ≤ duration_min` bleibt gewahrt.
- **`flights`-Fallback (Review b):** FriesenSpy-Connection ohne Track → erscheint als Flug (dep/arr aus Plan);
  StatSim ohne Track → dito.
- **Kutter-Latch-Reconcile (Review c):** live gelatchte Ankunft/Verlust (Key = Verbindungs-Logon) wird dem
  GPS-Flug (`takeoff_ts`) korrekt zugeordnet; ohne Reconcile ginge sie verloren.
- **`canonicalize_legs`**: Feld-für-Feld-Parität mit `canonicalize_flights`; nur `FRS` gewertet; Dedup
  FriesenSpy-gewinnt bei Überlappung; **Teil-Überlappung** verliert den ungedeckten StatSim-Teil nicht.
- **Flugplan-Zuordnung (zeitbasiert, Update 2026-07-05)**: zuletzt gefilter Plan zum Landungs-/
  Beinende gewinnt; ein Plan A→C + GPS A→B→C → BEIDE Beine bekommen A→C (FRS96-Bugfix); zwei echte
  Refiles (Start-Wechsel) → jedes Bein bekommt exklusiv seinen eigenen Plan; verfrühtes Refile vor
  der eigenen Landung → sichtbar als Mismatch (kein Schutz, akzeptiertes Verhalten); reiner Connect
  ohne Plan → `—`; Landung vor der ersten Filing → `—`.
- **Konsumenten**: `get_stats`/Bummel/Kutter mit Flügen; Bummel-„Frode"-E2E; Vorher/Nachher-Zahlvergleich
  je Konsument; offener Flug zählt erst bei beendeter Verbindung.

## Abgrenzung / YAGNI

- **Kein Roh-`gps_legs`-Leg-Table**, kein Delete-Scoping (Phase-1-`recompute` wird durch die materialisierte
  Flug-Sicht ersetzt). Reines on-demand über die ganze Historie ist aus Performance-Gründen **nicht**
  ausreichend — daher der inkrementelle Ergebnis-Cache.
- **Fremd-Callsign-Anzeige und proaktiver Per-Import-Fetch → Phase 2b**, nicht Phase 2.
- Kein manuelles Friesen-cid-Listing (self-maintaining über bekannte cids).
- Kein Einfrieren alter Events (nur Tests bisher); Statistik-Historie via Fallback (b) erhalten.
