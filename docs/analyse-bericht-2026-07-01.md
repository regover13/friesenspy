# Abschlussbericht: Flug-Tracking-Bugs vom Live-Test 2026-07-01

**Auftrag:** `docs/fable-analyse-auftrag.md` · **Session:** Fable, Branch `claude/fable-analyse-auftrag-3hgk13`
**Ergebnis:** Alle Fixes der Gruppen A und B sind umgesetzt (TDD), deployed und per Health-Check
verifiziert. Releases: **v7.3.1**, **v7.3.2** (inkl. Hotfix, s. Vorfall unten), **v7.3.3**.
Testsuite: 490 → **514 Tests, grün**.

---

## Gruppe A — Datenintegritäts-Bugs

### A1 — Realer Flug fehlt komplett (Task #10, Reiner cid 1031301)

**Root Cause (bestätigt):** Zwei Zahnräder griffen ineinander:

1. `app/poller.py:771-784` (`_poll_once`, Zweig `went_offline`): Fehlt ein Pilot **eine einzige
   Poll-Runde** im VATSIM-Feed (Feed-Glitch), wird sein Flug sofort per `close_flight`
   geschlossen — es gibt keine Karenz.
2. `app/database.py` (`open_flight`, vor dem Fix Zeilen 555–559): Beim Wiederauftauchen mit
   **derselben `logon_time`** lief der `INSERT … ON CONFLICT(cid, logon_time) DO NOTHING` ins
   Leere und der folgende `SELECT` gab die **bereits geschlossene** Zeile zurück — ohne sie zu
   re-öffnen. `_active_flights` zeigte fortan auf eine geschlossene Zeile.

Folge im Live-Test: Flug 277 wurde um 17:32:16 glitch-geschlossen; die Session lief real bis
18:43 weiter (position_history: ~265 bewegte Zeilen, bis 86 kt), aber **kein** `flights`-Eintrag
besaß den Track mehr → der reale Flug 18:18–18:36 (EDWG→EDXH, StatSim-belegt) verschwand mitsamt
Anzeige. Erst der echte Reconnect um 18:43:47 erzeugte wieder eine (Steh-)Zeile 284.

**Fix:** `app/database.py:576` — `open_flight` **re-öffnet** die Zeile, wenn sie zu derselben
Verbindung gehört, aber geschlossen ist (`logoff_time = NULL`; duration/distance/block werden
beim echten Close neu berechnet). Dieselbe `logon_time` beweist, dass die Verbindung nie abriss
(ein echter Reconnect bekommt von VATSIM eine neue). Wirkt auch über Container-Neustarts.

**Alt-Daten-Reparatur (Kür):** `app/database.py:961` — `reconstruct_orphaned_flights` läuft bei
jedem Start (`init_db`) und rekonstruiert Flüge, die StatSim kennt, für die aber kein aktiver
`flights`-Eintrag existiert, sofern der eigene GPS-Track im Fenster (StatSim-Zeiten ± 10 min
Taxi-Rand, gedeckelt auf Nachbar-Sessions) **nachweislich Flugbewegung** zeigt. Dauer, Distanz
und Blockzeit kommen aus den echten Positionsdaten. Idempotent; kollidiert nicht mit 277/284
(die Fertig-gelandet-Regel verhindert den Merge mit der Steh-Session; Lücke zu 277 > Merge-Fenster).
→ Voraussetzung ist, dass der lokale `statsim_cache` den Flug kennt. Seit v7.3.4 läuft die
Rekonstruktion deshalb zusätzlich **direkt nach jedem StatSim-Refresh** (cid-gefiltert) — z. B.
beim Öffnen der Piloten-Flugliste im Statistiken-Tab, die im Hintergrund StatSim aktualisiert.
Ein Container-Neustart ist nicht mehr nötig: Drill-down öffnen, kurz warten, neu laden.

**Nachfix v7.3.5 (nach Praxis-Gegenprüfung „StatSim aktualisiert, kein neuer Flug"):** Die
erste Fassung ankerte an StatSims `logon_time` — aber StatSims `loggedOn` ist die
**Session-Anmeldung** und bei mehreren Flügen einer Verbindung für alle gleich
(`app/statsim.py`, Mapping `loggedOn/arrived`; `duration = arrived − loggedOn` — daher stammt
übrigens auch die „92" als StatSim-Dauer des zweiten Flugs: 17:04→18:36). Reiners fehlender
Flug stand also als „17:04→18:36" im Cache, seine Anmeldezeit lag im Fenster von Flug 277 →
„gedeckt" → übersprungen. Jetzt ankert die Rekonstruktion an der **Landezeit** und bestimmt den
Flugbeginn per Rückwärtssuche im Track (letzte belegte Standphase ≥ 5 min). Dieselbe
StatSim-Eigenschaft hätte künftig auch `consolidate_flights` Schritt D gefährlich gemacht
(Multi-Leg-Session auf die Dauer des ersten Beins geschrumpft, LIMIT-1-Zufall) — jetzt zählt
das `MAX(duration_min)` aller Zeilen derselben Anmelde-Minute (eigener Regressionstest).
**Bitte gegenprüfen** (ich habe aus dieser Umgebung keinen Zugriff auf VPS/Domain):
`ssh root@167.86.127.129 'curl -s http://127.0.0.1:8091/api/pilots/1031301/flights?days=7'`
— erwartet: eigenständiger EDWG→EDXH-Flug ~18:16–18:43 UTC mit ~24 nm und GPS-Track.

### A2 — `block_min` 92 > `duration_min` 28 (Task #9, Flug 277)

**Root Cause (bestätigt, gleiche Wurzel wie A1):** Die Kette:
1. Glitch-Close 17:32:16 → Flug 277 geschlossen (28 min, block 28).
2. A1-Mechanik: Session lief gegen die geschlossene Zeile weiter.
3. Echter Disconnect ~18:43 → `went_offline` rief `close_flight(277, last_pos≈18:43:44)` **erneut**
   auf → `logoff=18:43`, `duration=99`, `block=92` (erste Bewegung 17:04 → letzte 18:36).
4. `consolidate_flights` Schritt D (StatSim-Backstop, `app/database.py`, vor dem Fix UPDATE ohne
   `block_min`) korrigierte beim nächsten Start `logoff/duration/distance` zurück auf 17:32:16/28/34 —
   **ließ aber `block_min = 92` stehen**. Exakt der beobachtete unmögliche Zustand.

**Fix:** Schritte **C und D** von `consolidate_flights` berechnen `block_min` bei jeder
Fenster-Korrektur mit; neuer Schritt **E** (`app/database.py:939`) heilt bestehende unmögliche
Werte (`block_min > duration_min`) bei jedem Start selbst — Flug 277 wurde damit beim Deploy
automatisch auf den korrekten Wert (~26) repariert.

### A3 — Hin- + Rückflug fälschlich gemergt (Task #12, Ralf cid 1470798)

**Root Cause (bestätigt):** `app/database.py` `_segments_continuous` (vor dem Fix Zeilen
1176–1182): Die Richtungsprüfung vergleicht die Distanz zum **Flugplan-Ziel** (`d_first >
d_last + 20 km` → kein Merge). Ralfs Rückflug behielt den stalen Plan `EDWG→EDXH` und startete
**in EDXH — also „am Ziel"**: `d_first ≈ d_last ≈ 0` → die Prüfung griff strukturell nie.
Gap 282→286 (16 min) lag unter dem Same-FP-Fenster (30 min), Distanz-Budget trivially erfüllt
(beide Positionen am selben Platz) → Merge. Folge: der echte Rückflug verschwand, im Kutter-Feed
stand ein `EDWG→EDWG`-Flug (GPS-Start und -Ende Wangerooge), der aus der Wertung fiel.

**Fix (v7.3.1, „Abgeflogen-Regel"):** endete das frühere Segment gelandet am FP-Ziel, ist der
Flugplan erfüllt; ein späteres Segment ist ein neuer Flug. Echte Mid-Flight-Reconnects mergen
unverändert (Gegentest).

**Nachfix (v7.3.4, nach Praxis-Gegenprüfung des Auftraggebers):** Die FP-Ziel-Regel löste nur
das Paar 282+286. Das Paar **286+287** verschmolz weiterhin: der Rückflug (stale FP EDWG→EDXH)
landet am FP-**Start** EDWG — dort greift keine Ziel-Radius-Prüfung, und der nächste echte
Hinflug macht „Fortschritt Richtung Ziel", passiert also auch die Richtungsprüfung. Die Regel
wurde deshalb verallgemeinert („Fertig-gelandet-Regel", `app/database.py`): ein Segment, das
nachweislich **geflogen** ist (Position ≥ 60 kt `_FLOWN_MIN_GS_KT`) und **am Boden endete**
(letzte Position ≤ 40 kt `_LANDED_MAX_GS_KT`), ist abgeschlossen — egal wo es gelandet ist.
Reine Boden-Segmente (Gate-Reconnect vor dem Neu-Filen) mergen weiterhin (Gegentest), ebenso
Mid-Air-Reconnects. Integrationstest: Ralfs kompletter Abend (282/286/287) → drei Flüge.

**Wechselwirkung (gewollt):** Landet ein Pilot, disconnectet auf der Rollbahn und reconnectet zum
Taxi-in, wird das Taxi-Segment nicht mehr in den Flug gemergt; es fällt als Ghost (≤ 0,5 nm/
≤ 5 min) aus der Anzeige. Wenige Minuten Taxi-Blockzeit gehen dabei verloren — bewusst in Kauf
genommen, Korrektheit vor Vollständigkeit.

### A4 — Blockzeit zählt Standzeit bei Zwischenlandung mit (Task #17)

**Root Cause (bestätigt):** `app/database.py` `_block_minutes`/`_block_seconds` (vor dem Fix
Zeilen 715–751): `MIN(ts)..MAX(ts)` über bewegte Positionen = „erste bis letzte Bewegung" —
keine Summe. Wer bei einer Zwischenlandung verbunden blieb, bekam die komplette Standzeit als
Blockzeit angerechnet (Bummel-Ungerechtigkeit gegenüber Disconnect-Piloten).

**Fix:** `app/database.py:745-812` — Blockzeit = **Summe der bewegten Abschnitte**; **belegte**
Standphasen (zusammenhängende Positionen ≤ 2 kt zwischen zwei Bewegungen) ab
`_BLOCK_STAND_MIN_SEC` = 10 min (`app/database.py:742`) werden abgezogen. Kurze Halte (Rollhalt,
Warteschlange) zählen weiter; **Datenlücken ohne Stillstands-Beleg zählen voll** — ein
Feed-Aussetzer im Reiseflug kostet keine Blockzeit. Gilt automatisch auch für die sekundengenaue
Bummel-Wertung (`compute_bummel_standings` nutzt `_block_seconds`).

---

## Zwischenfall beim Deploy von v7.3.1 (transparent berichtet)

Der Deploy-Workflow prüfte bislang **nicht**, ob die App nach `docker compose up -d` wirklich
antwortet. Ich habe deshalb einen Health-Check in den Deploy-Schritt aufgenommen
(`.github/workflows/deploy.yml`: bis zu 60 s auf `{"status":"ok"}` pollen, sonst Fehlschlag +
Container-Logs). **Der erste Lauf dieses Checks entdeckte, dass v7.3.1 in Produktion beim Start
crashte** — der vorherige Run hatte fälschlich Erfolg gemeldet.

**Root Cause des Crashs:** `init_db` verwendet eine rohe sqlite3-Connection ohne `row_factory`;
das neue `reconstruct_orphaned_flights` griff benannt (`st["cid"]`) auf Zeilen zu →
`TypeError: tuple indices must be integers or slices, not str` → App-Start brach ab, sobald
`statsim_cache` Daten enthält (in den Tests leer, in Produktion voll — deshalb blieb es der
Suite verborgen). **Fix (v7.3.2, ~8 min später live):** eigener Cursor mit `sqlite3.Row` in der
Funktion + defensive Kapselung in `init_db` (ein Fehler der Reparatur kann den Start nie mehr
verhindern) + Regressionstest, der `init_db` auf einer Datei-DB mit StatSim-Daten fährt.
Deploy v7.3.2: „Health OK (Versuch 1)". Ausfallfenster Produktion: ca. 20:56–21:02 UTC.

---

## Gruppe B — Kleine Fixes

### B1 — Feierabend-Zusammenfassung feuerte zu früh (Task #13)

**Root Cause:** `app/poller.py` `_check_transport_events` (vor dem Fix ~Zeile 1028): der Latch
`summarized_at` wurde sofort bei `now >= dtend` gesetzt — Zusammenfassung + Push + KI-Text
entstanden, während Nachzügler noch flogen (nicht finales Ergebnis).

**Fix:** `app/database.py:2855` — `transport_anyone_in_progress` (Analogie zum Bummel-Reveal,
`_bummel_anyone_in_progress`): offener FRS-Flug mit Start auf der Strecke (GPS-erste-Position im
Radius, Fallback Flugplan-DEP), **vor `dtend` begonnen** → Feierabend wird verschoben
(`app/poller.py:1029-1036`). Flüge mit Live-Ankunfts-Latch verzögern **nicht** — ihr Beitrag
steht fest (Zuladung hängt nur am Muster, der Latch überdauert jeden späteren Disconnect).
Verspätete Neu-Connects nach `dtend` blockieren nicht.

### B2 — KI-Sprüche mit obskuren Platt-Wörtern (Task #14)

**Root Cause:** `app/llm.py:158` `_QUIP_SYSTEM` bot Platt aktiv als Stilmittel an („mal mit
plattdeutschem Anklang, z.B. 'Moin', 'dat', 'nich'") — das Modell eskalierte bis „frünnen".

**Fix:** Prompt verlangt klares, sofort verständliches **Hochdeutsch** mit nur ganz leichtem
norddeutschen Einschlag („Moin" als Einstieg ok) und verbietet Platt-Wörter/Sätze explizit
(Negativ-Beispiele: „frünnen", „dat", „nich", „lütt"). Variations-Anweisungen bleiben erhalten;
Guard-Tests sichern die Anforderungen. **Offen:** Live-Gegentest mit echten Kontexten war hier
nicht möglich (kein `ANTHROPIC_API_KEY` in dieser Umgebung) — bitte die nächsten erzeugten
Sprüche kurz ansehen.

---

## Gruppe C — Machbarkeit: Aircraft-Typ ohne Flugplan (Task #11)

**Befund: Es ist eine echte VATSIM-Datenlimitierung, kein FriesenSpy-Bug.**

Der öffentliche v3-Datenfeed (`https://data.vatsim.net/v3/vatsim-data.json`) führt auf
**Piloten-Ebene** (Top-Level eines `pilots[]`-Eintrags) ausschließlich: `cid`, `name`,
`callsign`, `server`, `pilot_rating`, `military_rating`, `latitude`, `longitude`, `altitude`,
`groundspeed`, `transponder`, `heading`, `qnh_i_hg`, `qnh_mb`, `flight_plan`, `logon_time`,
`last_updated`. **Alle Typ-Felder (`aircraft`, `aircraft_faa`, `aircraft_short`) liegen nur im
verschachtelten `flight_plan`-Objekt** — ohne eingereichten Flugplan ist `flight_plan: null`
und es existiert **kein** Typ-Feld. (Quellen: offizielle Data-API-Doku
[vatsim.dev](https://vatsim.dev/api/data-api/get-network-data/); deckungsgleich mit den
Fixtures in `tests/test_vatsim.py`. Hinweis: der direkte Live-Abruf des Feeds war aus dieser
Sandbox durch die Netzwerk-Policy geblockt — die Struktur ist über Doku + Repo-Fixtures
zweifach belegt.)

**Lösungsoptionen (nicht implementiert, nur skizziert):**
1. **Prefile-Fallback (minimal-invasiv):** `vatsim_data["prefiles"]` enthält je `cid` einen
   vollständigen `flight_plan` inkl. Typ. Hat ein verbundener Pilot keinen FP, könnte
   `_poll_once` den Typ aus seinem Prefile ziehen (Map `cid → prefile` existiert dort bereits).
   Deckt den Fall „eingereicht, aber nicht verknüpft" — nicht den Fall „nie eingereicht".
2. **StatSim-Abgleich:** `statsim_cache.aircraft` nach Flugende nachtragen (rückwirkend fürs
   Manifest; für den Live-Feed zu spät).
3. **UI-Hinweis:** Piloten ohne FP im Kutter-Feed sichtbar als „Typ unbekannt — Flugplan
   einreichen!" markieren, statt still den globalen Default zu nehmen (aktuell taucht ein leerer
   `type_code` nicht mal unter `unmapped_types` auf — `app/vatsim.py:75-82`,
   `app/database.py` `compute_transport_progress`).
   → Empfehlung: 1 + 3 kombinieren, wenn gewünscht.

---

## Priorisierungs- und Wurzel-Übersicht

**Gefährlichkeit für die Datenqualität (absteigend):**

1. **A1 (Feed-Aussetzer zerstört Session)** — gefährlichster Bug: löscht real geflogene Flüge
   unbemerkt aus allen Ansichten (Statistik, Bummel, Kutter) und triggert A2 gleich mit. Ein
   einziger VATSIM-Glitch genügte.
2. **A3 (Stale-FP-Merge)** — verschluckt echte Rückflüge und produziert absurde
   `EDWG→EDWG`-Einträge im Kutter-Feed; trifft genau das Nutzungsmuster der Gruppe
   (Inselhüpfen mit stehengebliebenem Plan).
3. **A4 (Blockzeit mit Standzeit)** — verzerrt die Bummel-Wertung systematisch zugunsten von
   Piloten, die verbunden bleiben; kein Datenverlust, aber Fairness-Problem.
4. **A2 (block > duration)** — sichtbares Symptom, aber Folgefehler von A1 + fehlender
   Block-Neuberechnung in `consolidate_flights`.
5. **B1/B2** — funktional klar umrissen, kein Datenverlust.

**Gemeinsame Wurzeln (Ein-Fix-mehrere-Symptome):**
- **A1 und A2 teilen dieselbe Wurzel** (Glitch-Close + blindes Wiederverwenden der geschlossenen
  Zeile). Der `open_flight`-Reopen behebt beide Entstehungsketten; Schritt E räumt Altschäden ab.
- **A3 und A4 sind eigenständig**, hängen aber am selben Grundmuster: *zu viel Vertrauen in den
  Flugplan, zu wenig in die GPS-Belege*. Beide Fixes verschieben die Beweislast auf die
  Positionsdaten — dieselbe Stoßrichtung wie der unten notierte Diskussionspunkt.

---

## Notierter Diskussionspunkt (nicht umgesetzt — Entscheidung nötig)

**Flugerfassung ganz ohne Flugpläne — rein GPS-basiert?** (vom Auftraggeber am 01.07.
eingebracht): Flüge nur anhand von Landungen/Starts auf Flugplätzen erkennen (Position, Höhe,
Geschwindigkeit), Flugpläne höchstens als Anzeige-Metadatum.
*Dafür spricht:* A1/A3/A4 waren alle Flugplan-Vertrauens-Probleme; GPS-Erfassung würde Merge-
Heuristiken und FP-Änderungs-Erkennung stark vereinfachen; Bummel/Kutter arbeiten heute schon
GPS-korrigiert. *Dagegen/zu klären:* Session-Grenzen (VATSIM-Verbindung) bleiben als
Duplikat-Schutz nötig; Definition „Landung" (Touch-and-Go? Durchstarten?); StatSim-Abgleich und
Altdaten-Kompatibilität; Live-Anzeige von DEP/ARR vor dem Start braucht weiterhin den FP.
→ Eigene Design-Runde mit dem Auftraggeber (verwandt mit #16, das ausdrücklich ausgeklammert ist).

## Offene Punkte / Übergaben

1. **Git-Tags:** `v7.3.1`–`v7.3.3` sind lokal in der Session gesetzt, aber der Git-Proxy dieser
   Remote-Umgebung **verweigert Tag-Pushes** (nur Branch-Refs). Bitte einmal lokal nachziehen:
   `git fetch && git tag -a v7.3.1 d633428 -m v7.3.1 && git tag -a v7.3.2 75091f0 -m v7.3.2 && git tag -a v7.3.3 653fd72 -m v7.3.3 && git push origin --tags`
2. **Reiner-Rekonstruktion in Prod gegenprüfen** (Kommando oben unter A1).
3. **B2-Sprüche live ansehen** (kein API-Key in der Sandbox).
4. Diskussionstermine: GPS-only-Erfassung (oben) sowie die ausgeklammerten #7/#8/#15/#16/#18.
