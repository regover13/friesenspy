# SDD-Ledger — #23 GPS-only Phase 2 (Aktivierung, v8.0.0)

Plan: `docs/superpowers/plans/2026-07-03-gps-only-phase2-aktivierung.md`
Branch: `feat/gps-only-phase2`
BASE (main-Stand vor Task 1): `0bf6206fbc43d90d857f551250fbe9d5859290a6`
Controller: Opus 4.8 (1M). Implementer: Sonnet. Risiko-Reviews (Task 4, 10) + Abschluss: Fable 5.
Umfang dieses Laufs: **Task 1–6 bis zum GATE**, dann Stopp + lokale collapsed-Audit-Auswertung.

## Status
| Task | Beschreibung | Status |
|------|--------------|--------|
| 1 | detect_gps_legs: Touchdown-Finalisierung (kein LANDED/Dwell) + segment-Stempel | ✅ fb15bf4 (review clean, 634 passed) |
| 2 | collapse_same_airport | ✅ 7bee274 (review clean, 24 gps-Tests) |
| 3 | reine Block/Distanz-Helfer (_block_seconds_positions/_distance_nm_positions) | ✅ f751b9d (review clean, 648 Tests) |
| 4 | canonicalize_legs (formgleich, Fallbacks, per-Flug-Dedup) — Review: Fable 5 | offen |
| 5 | flight_cache (inkrementell) | offen |
| 6 | Audit auf collapsed-Sicht (recompute-Loop raus) → GATE | offen |
| 7–13 | Konsumenten/UI/Cleanup/v8.0.0 — erst NACH GATE-Freigabe | offen |

## Invarianten
- Tasks 1–6 sind wertungsneutral (Konsumenten unberührt); Wertung wechselt erst ab Task 7.
- Landung nur am DB-Platz; kein Dwell (Touchdown final); Runden-Merge erst im Collapse.
- block_min <= duration_min bleibt; _BLOCK_STAND_MIN_SEC bleibt.
- pytest tests/ grün halten (Baseline vor Task 1 unten).

## Log
- Branch feat/gps-only-phase2 von main (0bf6206fbc43d90d857f551250fbe9d5859290a6) angelegt. Ledger frisch (Phase-1-Ledger überschrieben).

- Task 1: complete (fb15bf4, review clean). Minor (final-review): (a) veraltete '# Dwell>180'-Kommentare in Alt-Tests; (b) _statsim_gps_interpretation zaehlt len(legs)>1 als 'zwischenlandung' bis Task 6 (wertungsneutral).
- Task 2 BASE = fb15bf450f0ab2da2f4a137e85b9f6cd371a2865

## RESUME-HINWEIS (vor /compact, 2026-07-03)
- Branch `feat/gps-only-phase2`. Task 1 ✅ (fb15bf4). **Task 2 (collapse_same_airport) läuft gerade als
  Hintergrund-Implementer** — auf dessen Abschluss-Notification warten, dann Review (Sonnet), dann weiter.
- SDD-Skripte: `C:/Users/Tobias/.claude/plugins/cache/claude-plugins-official/superpowers/6.1.1/skills/subagent-driven-development/scripts/` (task-brief, review-package).
- Modell-Matrix: Implementer = Sonnet; Task-Reviews = Sonnet, **AUSSER Task 4 (canonicalize_legs) & Task 10
  (Kutter-Reconcile) = Fable 5**; **finaler Whole-Branch-Review = Fable 5**. Controller = diese Opus-Session.
- Ablauf je Task: task-brief erzeugen → Implementer (Sonnet, liest Brief, TDD, 1 Commit, Report nach
  `.superpowers/sdd/task-N-report.md`) → review-package BASE..HEAD → Reviewer → Fixes bei Critical/Important
  → Ledger-Zeile „Task N: complete". BASE je Task = HEAD vor Dispatch (hier notieren).
- **STOPP nach Task 6** (Audit auf collapsed umgebaut) → GATE: collapsed-Audit LOKAL gegen Prod-Daten
  auswerten (KEIN Zwischen-Release, Nutzer-Entscheidung), Zahlenbericht an Nutzer, auf Freigabe warten.
  Tasks 7–13 (Konsumenten/UI/Cleanup/v8.0.0) erst nach GATE-Freigabe.
- Baseline vor Task 1: 632 passed. Plan: `docs/superpowers/plans/2026-07-03-gps-only-phase2-aktivierung.md`.

- Task 2: complete (7bee274, review clean). Minor (final-review): (c) max_altitude-Merge ueber unterschiedliche Hoehen ungetestet (Brief-Ursprung); (d) _close_ground hardcodet arr_source='gps' (ok fuer aktuellen Aufrufer).
- Task 3 BASE = 2f9d54ff478ff12b52ff062900ebb90178622ea1

- Task 3: complete (f751b9d, review clean). Minor (final-review): (e) haversine-Import bleibt funktionslokal (Bestandsmuster); (f) Doppel-Sort im _gps_distance_nm-Wrapper (SQL ORDER BY + sorted() in reiner Fn) — nötig für Eigenständigkeit, vernachlässigbar. Concern: (g) close_flight hat eigene Inline-Distanzberechnung, NICHT über _gps_distance_nm — für Task 4/Cleanup vormerken.
- Task 4 BASE = f751b9d654de6027fd6704d9dc03a62fa806e1b5

- Task 4: Review R1 (Fable 5) = Spec ❌ / Changes-Requested. Fix-Loop laeuft. Critical: end_ts/coverage offener Fluege laeuft ueber Folge-Sessions (Segment-Kappung noetig). Important: (1) arrival darf KEINEN Plan-Fallback haben; (2) Fallback-b braucht closed-only + Ghost-Regel; (3) Fenster-WHERE -> Overlap (Controller-Entscheid, GATE melden); (4) _positions_for_cid Callsign-Leak -> bei Prefix filtern. Minor: StatSim-coverage symmetrisch; merge_fragmented im Fallback (DEFER->final); connection_closed=False-Doku; callsign-Lookup; Test5 unused 'sec'. +4 Regressionstests gefordert.

- Task 4: complete (Original 97d8180 + Fix b85658a; Re-Review Fable 5 = Spec ✅ / Approved). Minor (final-review): (h) _GPS_LEG_GAP_MINUTES=30 dupliziert gap_minutes-Default nur per Kommentar (Drift-Risiko); (i) next_takeoff-Sicherheitsnetz nach Detektor-Invarianten unerreichbar, wuerde bei Feuern Metriken auf 0 kollabieren (bewusst redundant). Nits, kein Blocker.
- Task 5 BASE = b85658a2fe47a185865970ab55008ac1d162baee

- Task 5: complete (66f446b + Test-Verschaerfung 5c8372c; Review Sonnet = Spec ✅ / Testschaerfe nachgezogen, Round-Trip feldtreu, Inkrement-Grenze belegt). Note fuer Task 7: get_cached_flights(callsign_prefix='') liefert cache-bedingt nur FRS (rebuild hardcodet FRS) — global-Statistik ist ohnehin FRS-only, also harmlos; in Task 7 bestaetigen dass Statistik-Pfad FRS nutzt.
- Plan-Anpassung committet (Task 6 GATE=lokal, kein v7.9.5).
- Task 6 BASE = 9365f7e42e1b524ca87b344eb7747b71bf96c791

- Task 6: complete (6c57f66; Review Sonnet = Spec ✅ / Approved; Fallback-Ausschluss verifiziert). Audit nutzt jetzt collapsed canonicalize_legs; recompute-Loop+Import aus main.py raus; gps_legs-Tabelle bleibt (Task 12). 665 Tests gruen.

=== ⏸ GATE ERREICHT (nach Task 6) ===
Tasks 1-6 fertig. STOPP fuer lokale collapsed-Audit-Auswertung gegen Prod-Daten + Zahlenbericht an Nutzer.
OFFEN: Prod-DB-Zugang. SSH root@VPS wurde vom Safety-Klassifizierer blockiert (Nutzer-Freigabe noetig). Frage an Nutzer gestellt (SSH-Snapshot / lokaler Backup / HTTPS-Tracks). Tasks 7-13 erst nach GATE-Freigabe.

=== GATE-AUDIT (collapsed, Prod-Snapshot 2026-07-04, 365d) ===
FS-Connections=185: match=172 (93.0%), missing=13 (7.0%), extra=15, arr_divergence=13 (7.0%), incomplete_rate=4.76%, airborne_spawn=2.65%.
StatSim (500/1563 Stichprobe): match=443 (88.6%), zwischenlandung=33 (6.6%), incomplete=18 (3.6%), divergent=2 (0.4%), none=4 (0.8%) -> sauber=95.2% (vgl. Roh-Sicht frueher 95.8%).
-> Bericht an Nutzer vorgelegt; warte auf GATE-Freigabe fuer Tasks 7-13.

=== ✅ GATE FREIGEGEBEN (Nutzer, 2026-07-04) ===
Tasks 7-13 laufen. Task 7 BASE = 6c57f66436adb3deb2c6b93ba4bb58c7f0acf865
- Task 7: complete (a5d5a2c; Review Sonnet = Spec ✅ / Approved, keine Findings). Statistik liest jetzt get_cached_flights; In-Progress-Regel in beiden Funktionen.
- Task 8 BASE = a5d5a2cfdbab7b147ed223753e3ff51826aa4958
- Task 8: complete (6aaf995; Review Sonnet = Spec ✅ / Approved). Piloten-Detail liest canonicalize_legs, callsign_prefix='' bleibt.
- Task 9 BASE = 6aaf995977f90fe37dc9bbac2ea3160cd1114eee

=== NUTZER-ENTSCHEIDUNGEN (2026-07-04, waehrend Task 9/10) ===
1) ZEITMODELL vollstaendig korrigieren: Blockzeit = gate-to-gate INKL. Taxi (die GROESSERE, minus lange Stopps _BLOCK_STAND_MIN_SEC); Flugzeit = Abheben->Landung (die KLEINERE). Invariante kuenftig Flugzeit(duration_min) <= Blockzeit(block_min). Der Code fuehrte es INVERTIERT (block ⊂ duration, Self-Heal db:1228 'block>duration unmoeglich' + Tests test_canonicalize_legs:142,354). GPS-Blockfenster in _gps_flights_for_positions (db:2112) bis Rollbeginn/vorheriger Landung erweitern. Legacy flights-Tabellen-Self-Heal (db:1228) BLEIBT (eigene alte Spalten-Semantik).
2) RADIUS_km einstellbar fuer Bummel+Kutter: durch canonicalize_legs->detect_gps_legs reichen (Default _BUMMEL_AIRPORT_RADIUS_KM=10). nearest_airport_icao_fast nimmt den NAECHSTEN Platz (min-Distanz) -> Ueberlappung unkritisch fuer Landung-am-Feld; Admin-Hinweis beim Hochsetzen.
3) UI (Task 11): Flugzeit UND Blockzeit getrennt + korrekt benannt.
REIHENFOLGE: Task 4c (canonicalize_legs Korrektur, Fable) -> Task 9b (Bummel radius+cleanup) -> Task 10 (Kutter) -> Task 5/7-Tests nachziehen (im 4c-Lauf) -> Task 11 UI -> 12 Cleanup -> 13 v8.0.0.
Task 9 Review war Spec ✅ (2 Minor: toter _add_position, ungenutztes open_end) — in Task 9b mitnehmen.

=== RADIUS-ENTSCHEIDUNG (2026-07-04) ===
Per-Event-Radius fuer Bummel/Kutter FALLENGELASSEN (Nutzer). Stattdessen globalen Standard _BUMMEL_AIRPORT_RADIUS_KM von 10 -> 4 km reduzieren (datenbasiert: 99% echter Landungen <2 km, dann Luecke, nur 2 Fehltreffer bei ~9,5 km; 4 km = Puffer auch fuer grosse Flughaefen). Wirkt global (detect_gps_legs-Landung, check_live_arrival-Latch, Bummel/Kutter-Platzerkennung). Der radius_km-Param aus dem laufenden 4c-Task bleibt (harmloser interner Knopf, Default=Konstante) ODER wird im Review/Cleanup gestrichen. Task #28 obsolet.

- Task 4c: DONE (4cbc7e5, 673 grruen) — Blockzeit gate-to-gate inkl. Taxi (Fenster bis Rollbeginn/vorherige Landung), duration_min=Flugzeit, radius_km-Param durchgereicht, invertierte block<=duration-Assertions geflippt. Fable-Review laeuft. Concern (fuer Fable): pruefen ob wirklich keine GPS-track-abgeleitete Fremd-Assertion uebersehen wurde.
- UI-Audit erledigt -> .superpowers/sdd/task-11-ui-audit.md (Vorlage fuer Task 11).
- Task 4c: Review Fable = Spec ✅ / Approved. block_start-Walk bewiesen korrekt (keine Doppelzaehlung), Invarianten-Flip sauber. Important: prev_end-Schranke ungetestet (Zwei-Legs-Segment-Test nachziehen). Minor: Docstring-Invariante entschaerfen, radius_km is not None, Taxi-in-Attribution dokumentieren.
- Task 4d: DONE (960e8d7 Haertung + 893c8e5 4km-Radius; 674 gruen). prev_end-Schranke jetzt getestet (faellt ohne Schranke: 67 vs 27 min). 4km: nur test_transport EventRadius-Fixture 4->3.5km gerueckt. Review Sonnet laeuft.
- Task 4d: Review Sonnet = Spec ✅ / Approved. Backend-Wahrheit (Zeit+Radius) komplett. Naechster: Task 10 Kutter.
- Task 10 BASE = 893c8e5fa5f17af83b9b5c3d88748e0787c24aeb — Kutter GPS+Reconcile laeuft (Fable-Review geplant).

=== AUTONOMER ABSCHLUSS-AUFTRAG (Nutzer, 2026-07-04, Nacht) ===
Nutzer ist im Bett. Auftrag: ALLES allein fertigmachen, am Ende v8.0.0 DEPLOYEN, dann die LOKALE Maschine
selbst herunterfahren. Deploy ist AUTORISIERT, solange kein KRITISCHES, entscheidungsbeduerftiges Problem auftritt.
Nutzer fragt den Stand morgen ab.

REGELN fuer den Autopiloten:
- Bei Routine (Review-Fix-Loops, Testanpassungen, UI-Umsetzungsdetails): mit sinnvollem Default WEITERMACHEN, nicht fragen.
- NUR bei echtem kritischem Blocker (Design-Widerspruch zu einer Nutzer-Entscheidung, Wertungs-Semantik unklar,
  Health-Check nach Deploy rot & nicht selbst loesbar, irreversibles/aussenwirksames jenseits des autorisierten Deploys):
  STOPP, Stand prominent hier + in MEMORY.md notieren, Maschine NICHT herunterfahren (Nutzer soll morgen entscheiden).
- Wenn alles sauber durchlaeuft: deploy verifizieren (Health == 8.0.0), Tag v8.0.0, MEMORY.md updaten, DANN Maschine herunterfahren.

RESTLICHE SEQUENZ:
  Task 10 (Kutter) Review+Fix -> Task 9b (2 Bummel-Cleanups) -> #29 (Radius-Felder raus, Backend auf 4km-Konstante)
  -> #30 (flight_cache Warm-up beim Start + periodischer Refresh-Job; Voll-Rebuild ~5,5s gemessen)
  -> Task 11 UI (aus .superpowers/sdd/task-11-ui-audit.md) + #31 (Track bei id=None)
  -> Task 12 Cleanup (gps_legs-Tabelle+recompute weg; schlummernde radius-Spalten; ungenutzter radius_km-Param pruefen)
  -> Task 13: Docs (README/api.md/architecture.md), Changelog v8.0.0 (Major/highlight) + Version-Bump,
     FINALES Whole-Branch-Review (Fable), merge feat/gps-only-phase2 -> main, push (CI: Actions->GHCR->SSH),
     gh run watch, Health-Check friesenspy.devprops.de == 8.0.0, Tag v8.0.0.
  -> MEMORY.md: project_gps_leg_detection.md auf 'v8.0.0 live' aktualisieren.
  -> Maschine herunterfahren (Windows: shutdown /s /t 60).

WICHTIG beim Deploy: config.env NIE committen; nur main->CI deployt. Version in app/CHANGELOG.json oben.

=== ZUSATZ (Nutzer, 2026-07-04 Nacht): PHASE 2b MITMACHEN ===
1) 'nicht gewertet'-Badge in Piloten-Detail fuer Nicht-FRS-Callsigns (reine Anzeige) -> in Task 11.
2) Proaktives StatSim-Track-Nachladen: periodischer APScheduler-Job, holt kleine Batches von get_uncached_statsim_ids nach (gedrosselt, wie Backfill) -> Task #32, zusammen mit #30-Scheduler.
Beide aendern keine Wertungs-Semantik -> autonom machbar, kein Nutzer-Entscheid noetig.

=== DOCS-EMPHASE (Nutzer, 2026-07-04 Nacht) ===
Task 13 MUSS Docs GRUENDLICH mitziehen (stehende Regel 'Docs immer aktualisieren'):
- README.md: GPS-only-Modell, neue Flug-Felder, Flugzeit vs. Blockzeit (gate-to-gate), 4-km-Radius, kein per-Event-Radius mehr, Phase 2b (Badge + proaktives StatSim-Nachladen).
- docs/api.md: /api/pilots/{cid}/flights neue Felder (gps_departure/gps_arrival/plan_departure/plan_arrival/connection_closed), geaenderte Semantik duration_min=Flugzeit & block_min=Blockzeit, gps-leg-audit collapsed, flight_cache; Radius-Felder aus Admin-Endpoints entfernt.
- docs/architecture.md: canonicalize_legs als einzige Wahrheit (ersetzt Refile/Disconnect), detect_gps_legs+collapse_same_airport, flight_cache + Scheduler-Refresh, proaktiver StatSim-Track-Job, Block=gate-to-gate.
- CLAUDE.md pruefen (config.env-Doku: kein per-Event-Radius; ggf. Scheduler-Jobs erwaehnen).
- Changelog v8.0.0 (Major, highlight) mit den zentralen Nutzer-sichtbaren Aenderungen.
Docs-Update kann als eigener Subagent-Task laufen (liest den Diff main..HEAD), Review leicht.
- Task 10: DONE (f170f27, 677 gruen). Kutter auf canonicalize_legs + _latch_hits_flight + _connection_logon_for_leg-Loss-Reconcile + Rueckflug-Guard. Abweichung: detect_transport_losses gated auf CONNECTION-logoff (sonst 'sunk' nie erkennbar); _fp_only entfernt; _hi weggelassen. Fable-Review laeuft.
- Task 10 Review R1 (Fable) = Spec ❌ / Changes Requested. Fix-Loop laeuft. C1 Doppelzaehlung gelandet+verbunden; C2 Plan-Lieferung via Fallback ohne Flug; I1 sunk von spaeterem Latch verdeckt; I2 lost_kg-Mehrfach-Attach; M1 Zwischenland-Leg als 'stolen am Ziel'. sunk-Gating-Abweichung genehmigt.
- Task 10 Fix: DONE (46b7606, 683 gruen, +6 Regressionstests C1/C2/I1/I2). Deliveries brauchen GPS-Landung od. Latch (_add_delivered_flight-Helfer). Fable-Re-Review laeuft.
- Task 10: COMPLETE (Original f170f27 + Fix 46b7606 + Minor 72f4f7e; Re-Review Fable = Spec ✅ / Approved). Alle 4 Konsumenten (Statistik/Piloten/Bummel/Kutter) auf GPS-Wahrheit. Backend-Umbau fertig.
- Naechster: #29 (Radius-Felder raus) + Task 9b (Bummel-Test-Cleanup). BASE = 72f4f7e8c52ad447043e979216ed36934b348889
- #29+9b: DONE (ece6660 Radius-raus+Test-Cleanup + b79b3db Bummel-Straggler-Radius-Konsistenz; 682 gruen). Per-Event-Radius vollstaendig entfernt (UI+Backend), fester 4km. Review Sonnet laeuft.
- #29: Review Sonnet = Spec ✅ / Approved. Naechster: #30+#32 Scheduler-Jobs. BASE = b79b3db3446c1a7cb032274213ceefe0285e7ccf
- #30+#32: DONE (e3a23b6, 688 gruen). flight_cache Warm-up(to_thread)+5min-Refresh + StatSim-Fetch-Job(10min). Bug gefixt: sqlite Connection thread-gebunden -> _rebuild_flight_cache_sync oeffnet Conn im Worker-Thread. Review Sonnet laeuft.
- #30+#32: Review Sonnet = Spec ✅ / Approved (688 gruen, Thread-Bindung ok). Backend+Poller KOMPLETT.
- #31-BEFUND: index.html ruft KEINEN /track-Endpoint auf (kein Flug->Track-Klick) -> #31 weitgehend gegenstandslos, im UI-Task nur verifizieren. /api/flights/{id}/track braucht valide id (404 sonst).
- Naechster: Task 11 UI + 2b-Badge + #31-Check. BASE = e3a23b6ab6072392d79250c13eaf55f0e50334b9
- Task 11 (UI+2b+#31): DONE (7d040d8, 688 gruen, node --check valid). GPS-Route+Plan-Spalte, Flugzeit/Blockzeit-Labels, laeuft-Badge, nicht-gewertet-Badge, frontend-config callsign_prefix, #31 Track-Button disabled bei id=null. ABWEICHUNG: /api/events (Events-Such-Tabelle) NICHT auf canonicalize_legs migriert (Legacy dep/arr) -> eine Strecke-Spalte, logoff-basiertes Offen-Signal. Wertung selbst (Standings/Progress) korrekt migriert. Follow-up Task #33. Review Sonnet laeuft.
- Task 11: COMPLETE (7d040d8 + Minor-Fix 4bdff95, node --check OK; Review Sonnet = Spec ✅). Follow-up #33 (/api/events).
- Naechster: Task 12 Cleanup (recompute_gps_legs + gps_legs-Tabelle raus; radius_km-Param BLEIBT-getestet/harmlos; dormant radius-DB-Spalten BLEIBEN; Refile-Split/merge_fragmented BLEIBEN). BASE = 4bdff9505615f0358d12a6b47a59cc3ce1de422d
- Task 12: DONE (7171ffd, 684 gruen). recompute_gps_legs + gps_legs-Tabelle raus (grep+import verifiziert), 2 Doku-Stellen korrigiert. Kein separates Review -> finales Whole-Branch-Review (Task 13) deckt es ab.
=== ALLE TASKS 1-12 + Sub-Tasks FERTIG. Jetzt Task 13: Docs+Changelog v8.0.0+Final-Review+Deploy. ===
- Task 13 (Docs+Changelog v8.0.0) BASE = 7171ffdd737faca91ae31263f68ee92f664b64be. VERSION leitet aus CHANGELOG[0] (app/version.py) ab -> nur Top-Eintrag noetig.
- Task 13: DONE (e7f4ed4 Docs+Changelog v8.0.0, VERSION=8.0.0).
- FINALES Whole-Branch-Review (Fable) = GO-mit-Fixes. 3 Fixes -> bb90625: (1) statsim_id im Feld-Vertrag (Track-Button-Regression), (2) Events-Tab-Label 'Flugzeit'->'Online' (Legacy-Verbindungszeit), (3) rebuild_flight_cache compute-vor-DELETE. Alle Minors = spaeter. 687 gruen, verifiziert.
=== BRANCH MERGE-REIF. Jetzt: Merge->Push->CI-Deploy->Health==8.0.0->Tag v8.0.0->Memory->Shutdown. ===
