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
| 2 | collapse_same_airport | ⏳ in Arbeit |
| 3 | reine Block/Distanz-Helfer (_block_seconds_positions/_distance_nm_positions) | offen |
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
