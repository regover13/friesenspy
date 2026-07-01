# Analyse-Auftrag für Claude Fable 5 — FriesenSpy Flug-Tracking & FriesenKutter

**Zweck:** Sorgfältige Root-Cause-Analyse mehrerer beim Live-Test am 2026-07-01 aufgetretener
Bugs, plus zwei kleine klar umrissene Fixes. Diese Themen brauchen **keine Produkt-Entscheidung**
des Auftraggebers — sie sind reine Code-Diagnose bzw. eindeutig spezifizierte Änderungen.

## Leitplanken (WICHTIG — bitte strikt einhalten)

Du darfst die Bugs **direkt beheben, committen, auf `main` pushen und deployen** (der
Auftraggeber hat das ausdrücklich freigegeben). Aber sorgfältig und mit diesen Regeln:

1. **Root Cause zuerst, dann fixen — kein Blind-Patch.** Es geht um die zentrale Flug-State-
   Machine, die *alle* Ansichten speist (`canonicalize_flights` ist laut eigenem Docstring
   „die EINZIGE Wahrheit für echte Flüge"). Ein vorschneller Fix kann Statistik, Bummel und
   Kutter gleichzeitig verfälschen. Erst die Ursache mit `datei:zeile`-Belegen sicher belegen,
   dann fixen. Für jeden Bug einen **kurzen Root-Cause-Absatz im Commit-Body** festhalten.
2. **TDD:** je Fix zuerst einen fehlschlagenden Test (der den Bug reproduziert), dann den Fix.
   Die **gesamte** Suite muss grün bleiben: `python -m pytest -q` (aktueller Stand: 490 Tests).
3. **Versionierung ist Pflicht bei jedem Release** (stehende Projektregel): `app/CHANGELOG.json`
   oben einen neuen Eintrag ergänzen (Struktur: `version`, `date`, `title`, `items`-Array) +
   passenden Git-Tag `vX.Y.Z`. Schema: Bugfix = Patch (x.y.**Z**), Feature = Minor (x.**Y**.0),
   großer Wurf = Major. Das Feld `"highlight": true` **nur** für Major-Releases setzen (nie für
   Bugfixes/Minor). Aktuelle Top-Version steht in `app/CHANGELOG.json` — davon hochzählen.
4. **Docs immer mitpflegen** (stehende Projektregel): bei Verhaltensänderungen `README.md`,
   `docs/api.md`, `docs/architecture.md` und betroffene Docstrings aktualisieren.
5. **Vor jedem Push `git fetch` + rebase auf `origin/main`** — es arbeiten **weitere Sessions
   am selben Repo** (siehe `COORDINATION.md` im Repo-Root: dort Absprachen mitlesen und, falls
   du etwas hinterlassen willst, eintragen). Niemals fremde, uncommittete Änderungen im
   Arbeitsverzeichnis überschreiben.
6. **Deploy:** Push auf `main` triggert automatisch GitHub Actions → GHCR → VPS-Deploy. Nach
   **jedem** Deploy verifizieren: `gh run watch <id> --exit-status`, dann Health prüfen
   (`ssh -i ~/.ssh/tsbot_server root@167.86.127.129 'curl -s http://127.0.0.1:8091/health'` →
   erwartet `{"status":"ok"}`). Deploye in **sinnvollen Einheiten** (z. B. je Bug oder je
   zusammengehörige Bug-Gruppe ein Commit/Deploy), nicht alles in einem Riesen-Commit.
7. **Commit-Konvention:** deutsche, aussagekräftige Messages; am Ende die im Repo übliche
   `Co-Authored-By`-Zeile beibehalten (an bestehenden Commits orientieren, `git log` ansehen).

## Projektkontext

FriesenSpy = VATSIM-Live-Tracker (Python 3.11 / FastAPI / SQLite WAL / APScheduler). Callsign-
Prefix `FRS`. Relevante Dateien:

- `app/poller.py` — `VatsimPoller._poll_once` (State-Machine: newly_online / still_online /
  went_offline, alle 15 s), `open_flight`/`close_flight`-Aufrufe, Flugplan-Änderungserkennung.
- `app/database.py` — `canonicalize_flights` (Merge + Dedup + Ghost-Filter, „einzige Wahrheit"),
  `merge_fragmented_flights` + `_segments_continuous` (Reconnect-Zusammenführung),
  `_block_minutes`/`_block_seconds` (Blockzeit), `close_flight` (setzt logoff/duration/distance/
  block), `compute_bummel_standings`, `compute_transport_progress`.
- Konstanten: `_BLOCK_GS_KT = 2` (Groundspeed-Schwelle „in Bewegung"),
  `_RECONNECT_GAP_SAME_FP_MIN` / `_RECONNECT_GAP_NO_FP_MIN` (Merge-Fenster),
  `_BUMMEL_AIRPORT_RADIUS_KM = 10`.
- Tabellen: `flights` (cid, callsign, departure, arrival, logon_time, logoff_time, duration_min,
  distance_nm, block_min, superseded_by …), `position_history` (cid, ts, latitude, longitude,
  altitude, groundspeed …), `statsim_cache`, `transport_events`, `transport_live_arrivals`.

**Zugriff auf echte Daten (falls SSH verfügbar):** VPS `root@167.86.127.129`, Key
`~/.ssh/tsbot_server`, DB unter `/opt/friesenspy/data/friesenspy.db`. **Nur read-only** öffnen:
`sqlite3 "file:/opt/friesenspy/data/friesenspy.db?mode=ro"` bzw. per Container
`cd /opt/friesenspy && docker compose exec -T friesenspy python3 -c "..."`. Falls kein SSH:
die unten eingebetteten Beobachtungsdaten reichen für die Code-Analyse aus.

---

## Gruppe A — Datenintegritäts-Bugs (analysieren, fixen, deployen)

> Die vier Bugs in dieser Gruppe hängen alle am selben Codebereich (Flug-State-Machine,
> Merge, Blockzeit) und sollten **zusammen** analysiert werden — vermutlich teils gemeinsame
> Wurzel (`position_history`-Kontamination über Session-Grenzen + Merge-Vertrauen in stale
> Flugpläne). #9 und #10 betreffen beide denselben Piloten (Reiner) und sind wahrscheinlich
> zwei Symptome derselben Ursache.

### A1 — Realer Flug fehlt komplett; vmtl. fälschlich geschlossen (Task #10)

**Pilot:** Reiner, cid `1031301`, FRS61. **Beobachtung (Live-Test 2026-07-01):**
- Rohe `flights`: nur **zwei** Einträge — id 277 (`EDWG→EDXH`, 17:04:16–17:32:16 UTC, 28 min,
  34 nm, echter Hinflug) und id 284 (18:43:47–18:57:54, **0 nm**, GPS stationär in EDXH — er
  stand nur da, kein echter Flug).
- **Dazwischen fehlt ein realer Flug:** laut StatSim.net flog er `EDWG→EDXH` von **18:18–18:36**,
  der in FriesenSpys `flights`-Tabelle **komplett fehlt**.
- `position_history` für cid 1031301 zeigt **durchgehende Bewegung** (bis 86 kt) zwischen 17:32
  und 18:44 — er war also online und flog, aber es existiert kein `flights`-Eintrag dafür.

**Verdacht:** kurzer VATSIM-Feed-Aussetzer (eine Poll-Runde ohne diesen Piloten in den Daten) →
`went_offline` greift fälschlich → `close_flight` auf die laufende Session; beim Wiederauftauchen
wird der reale Folgeflug nicht sauber als neuer `flights`-Eintrag geöffnet (nur `position_history`
läuft weiter). **Zu prüfen:** `_poll_once`-Logik für `went_offline`/`newly_online`, insbesondere
Verhalten bei einmaligem Verschwinden eines Piloten aus dem VATSIM-Feed und Wiederauftauchen mit
gleicher `logon_time` (`open_flight` hat `ON CONFLICT(cid, logon_time) DO NOTHING` — greift der
ins Leere, wenn die Session zwischenzeitlich geschlossen wurde?).

### A2 — `block_min` > `duration_min` (unmöglich) (Task #9)

**Beobachtung:** Flug id 277 (Reiner, s. o.) hat gespeichert `duration_min = 28`, aber
`block_min = 92`. Blockzeit (Bewegung gate-to-gate innerhalb `[logon, logoff]`) kann **nie**
größer als die Online-Dauer sein — 92 > 28 ist unmöglich. `_block_minutes` fragt eigentlich nur
`WHERE cid=? AND ts>=logon_time AND ts<=logoff_time AND groundspeed>_BLOCK_GS_KT` (MIN..MAX ts),
also auf `[17:04, 17:32]` begrenzt → max. 28. **Wie kann 92 herauskommen?** Vermutlich wurde
`block_min` zu einem Zeitpunkt berechnet, als der Flug ein *anderes* (späteres) `logoff_time`
hatte, oder die `position_history` enthält Zeitstempel, die fälschlich diesem Flug zugeordnet
wurden (Überlappung mit dem fehlenden Flug aus A1). **Sehr wahrscheinlich dieselbe Wurzel wie
A1** — bitte gemeinsam betrachten. Prüfen: wann/wie oft wird `block_min` (re)berechnet, und mit
welchem `logon/logoff`-Fenster?

### A3 — Hin- + Rückflug fälschlich zu einem gemergt (Task #12)

**Pilot:** Ralf, cid `1470798`, FRS102. **Beobachtung:**
- Rohe `flights`: id 282 (`EDWG→EDXH`, 18:28:32–18:50:24, echter Hinflug, Disconnect in EDXH ✓),
  id 286 (Flugplan `EDWG→EDXH`, aber **real der Rückflug EDXH→EDWG** — Pilot hatte vergessen sich
  einzuloggen, in der Luft nachgeholt, **alter Flugplan blieb stehen**; 19:06:26–19:20:20),
  id 287 (nächster Hinflug 19:22:27–19:38:40).
- `canonicalize_flights` führt **282 + 286 fälschlich zu EINEM** Flug zusammen (18:28–19:20).
  Grund: beide haben denselben (stale) Flugplan `EDWG→EDXH` (`same_fp`) und die Lücke (~16 min,
  18:50→19:06) liegt unter `_RECONNECT_GAP_SAME_FP_MIN`. Der `_segments_continuous`-Geo-Check hat
  den Merge **nicht** verhindert.
- **Folge:** der echte Rückflug geht verloren; im Kutter-Feed erscheint ein sinnloser
  `EDWG→EDWG`-Flug (GPS-Start Wangerooge, GPS-Ende nach dem Rückflug wieder Wangerooge) und fällt
  aus der Wertung (`dep == arr`).

**Erwartung:** Hinflug und Rückflug müssen **zwei getrennte** Flüge bleiben. **Fix-Richtung:** der
Merge vertraut dem stalen Flugplan zu sehr. `_segments_continuous` (bzw. die Merge-Bedingung)
schärfen, sodass zwei Segmente mit gleichem FP **nicht** verschmelzen, wenn die GPS-Richtung zeigt,
dass Segment B in **Gegenrichtung** (zurück) fliegt — z. B.: letzte Position von A ≈ FP-Ziel und
erste Position von B ≈ FP-Ziel, aber B bewegt sich vom FP-Ziel **weg** Richtung FP-Start. Achtung:
`_segments_continuous` prüft bereits eine Richtungs-Heuristik gegen `arrival` — genau nachvollziehen,
warum sie hier nicht griff (vmtl. weil `arr` = stale FP-Ziel EDXH ist, und B startet ja *in* EDXH,
also „am Ziel" → fälschlich als Fortschritt gewertet).

### A4 — Bummel-Blockzeit bei Zwischenlandung ohne Disconnect verfälscht (Task #17)

**Symptom (Code-Analyse, kein Live-Vorfall nötig):** Die Regel „Zwischenlandungen zählen nicht in
die Blockzeit" (`compute_bummel_standings`) funktioniert nur, wenn der Pilot bei der Zwischenlandung
**disconnectet und neu connectet** (zwei `flights`-Zeilen — die Standzeit dazwischen wird nie
erfasst). Bleibt er **durchgehend verbunden** (eine Session), rechnet `_block_minutes`
(`MIN(ts)..MAX(ts)` mit `groundspeed > _BLOCK_GS_KT`) die Standzeit **fälschlich mit ein** — es ist
nur „erste bis letzte Bewegung", **keine Summe echter Bewegungsabschnitte**. **Fix-Richtung:**
`_block_minutes`/`_block_seconds` so umbauen, dass sie die Summe der bewegten Intervalle bilden und
längere stehende Phasen (zusammenhängende Lücken mit `groundspeed <= _BLOCK_GS_KT` mitten im Flug,
oberhalb einer sinnvollen Mindest-Standdauer) herausrechnen. Betrifft die Bummel-Wertung
(Gerechtigkeit). Verwandt mit A2.

**Deliverable Gruppe A:** je Bug (A1–A4) die bestätigte/​widerlegte Ursache mit `datei:zeile`-
Belegen, ein **umgesetzter Fix** (TDD, gesamte Suite grün) und eine Einschätzung, welche Bugs eine
gemeinsame Wurzel haben (Ein-Fix-mehrere-Symptome bevorzugen). Fixes committen, mit
Versionierung/Changelog + Docs, auf `main` pushen und deployen (Health nach jedem Deploy prüfen).

---

## Gruppe B — Kleine, klar spezifizierte Fixes (umsetzen, pushen, deployen)

### B1 — Feierabend-Zusammenfassung feuert zu früh (Task #13)

**Bug:** In `app/poller.py`, `_check_transport_events` (~Zeile 1028): der Feierabend-Latch feuert
die Tagesend-Zusammenfassung + `set_transport_summarized` **sofort** bei `now >= dtend`, **ohne** zu
prüfen, ob noch ein Pilot auf der Strecke unterwegs ist. Dadurch entsteht die Zusammenfassung mit
einem **noch nicht finalen** Ergebnis (ein noch fliegender Flug zählt noch, sein Beitrag ändert sich
aber) → falsches Endergebnis. **Vorlage existiert bereits:** der Bummel-Reveal löst exakt dasselbe
Problem — `update_bummel_reveals` wartet via `_bummel_anyone_in_progress(conn, route, radius,
started_before=dtend)`, bis kein Nachzügler mehr unterwegs ist. **Umsetzung:** analoge
„noch-jemand-unterwegs?"-Prüfung für Transport-Events bauen (offener FRS-Flug, dessen Start vor
`dtend` lag und der noch nicht am Ziel/gelandet ist) und den `summarized`-Latch — samt Push-Text
und KI-`event_summary` — erst setzen/erzeugen, wenn niemand mehr fliegt. TDD.

### B2 — KI-Sprüche verständlich halten, keine obskuren Platt-Wörter (Task #14)

**Bug:** Die KI-Sprüche (`flight_quip` + `event_summary` in `app/llm.py`, System-Prompt
`_QUIP_SYSTEM`) übertreiben teils den plattdeutschen Anklang und werfen obskure Vokabeln ein
(Live-Test: die Tagesend-Zusammenfassung enthielt „frünnen" = Platt für „Freunde"). **Fix:** den
Prompt so schärfen, dass die Sprüche in **verständlichem Hochdeutsch mit nur ganz leichtem**
norddeutschen Einschlag bleiben — ein „Moin" als Einstieg ist ok, aber **keine ganzen
Platt-Wörter/Sätze**, die man übersetzen müsste. Einzeiler-Änderung im Prompt; danach idealerweise
ein kurzer Live-Gegentest (falls `ANTHROPIC_API_KEY` verfügbar) mit ein paar Beispiel-Kontexten, um
zu bestätigen, dass die Sprüche verständlich bleiben und weiterhin variieren.

---

## Gruppe C — Machbarkeits-Analyse (nur Recherche, kein Code)

### C1 — Aircraft-Typ auch ohne Flugplan erkennen? (Task #11)

Aktuell zieht `app/vatsim.py` (`pilot_to_position`) den Flugzeugtyp (`aircraft` / `aircraft_icao`)
**ausschließlich** aus dem VATSIM-Flugplan (`fp.get(...)`); ohne eingereichten Flugplan ist das Feld
leer. Für FriesenKutter heißt das: Zuladung/Typ-Erkennung funktioniert bei Piloten ohne Flugplan
gar nicht (leerer type_code → stiller globaler Default, taucht nicht mal als „unmapped" auf).
**Kernfrage der Analyse:** Bietet der **öffentliche VATSIM-Datenfeed**
(`https://data.vatsim.net/v3/vatsim-data.json`) überhaupt **irgendein** Feld für den Flugzeugtyp
**außerhalb** des `flight_plan`-Objekts (auf Piloten-Ebene)? Rohstruktur eines `pilots[]`-Eintrags
prüfen. **Wenn nein** → das ist eine echte VATSIM-Datenlimitierung, kein FriesenSpy-Bug; dann
Lösungsoptionen skizzieren (z. B. StatSim-Abgleich, oder Hinweis an Piloten „Flugplan nötig"), aber
**nicht** implementieren. **Wenn ja** → dokumentieren, welches Feld, und einen minimalen Fix-Vorschlag
für `pilot_to_position` skizzieren. Reiner Recherchebericht.

---

## Bewusst NICHT Teil dieses Auftrags (brauchen Entscheidung des Auftraggebers)

Diese Themen **nicht** anfassen — sie erfordern Produkt-/Design-Entscheidungen:
- **#7** Radius pro FriesenKutter-Event konfigurierbar (UI/Default-Entscheidung).
- **#8** Reservierte Menge live + „wer fliegt gerade wie viel"-Teilnehmerliste (Anzeige-Design).
- **#15** Mehrere Ziele gleichzeitig **oder** bidirektionale Zählung (drei Varianten, offene
  Grundsatzentscheidung).
- **#16** Bummel: Etappe/Ankunft zählen ohne Disconnect (eigene Design-Runde nötig, Wertungslogik).
- **#18** Forum-Abschluss-Badge für FriesenKutter (Design).

Falls dir bei der Analyse etwas **außerhalb** dieser Liste auffällt, das ein echter Bug ist: im
Bericht vermerken, aber nicht eigenmächtig umbauen.

---

## Abschluss / Rückgabe

Liefere am Ende:
1. **Umgesetzte Fixes** (Gruppe A + B) — committet, mit Tests grün, Versionierung/Changelog + Docs
   gepflegt, auf `main` gepusht und deployed (jeder Deploy per Health-Check verifiziert).
2. **Analyse-/Abschlussbericht** als Markdown — pro Thema Root Cause (`datei:zeile`), was gefixt
   wurde, Risiko/Wechselwirkungen; für Gruppe C (Machbarkeit) den Recherchebefund.
3. Eine **Priorisierungs-/Wurzel-Übersicht**: welcher Bug war am gefährlichsten für die
   Datenqualität, und welche teilten sich eine gemeinsame Ursache (Ein-Fix-mehrere-Symptome).
