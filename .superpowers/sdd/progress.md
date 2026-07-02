# SDD-Ledger — #23 GPS-Leg-Erkennung, Phase 1 (v7.9.0)

Plan: `docs/superpowers/plans/2026-07-02-gps-leg-detection.md`
Branch: `claude/gps-leg-detection-phase-1-3gkrg3`
Modus: Schatten-Erfassung — **rein additiv, NULL Wertungsänderung**. Push erst nach Task 4, dann GATE.

## Status

| Task | Beschreibung | Status |
|------|--------------|--------|
| 1 | `detect_gps_legs` (reine Funktion) + Airport-Grid-Index (`nearest_airport_icao_fast`) | ✅ 264d6d1 (619 passed) |
| 2 | Tabelle `gps_legs` + `recompute_gps_legs` (idempotent) | ✅ 4f78d50 (623 passed) |
| 3 | Read-only Audit `audit_gps_vs_refile` + `GET /api/admin/gps-leg-audit` | ⬜ offen |
| 4 | Docs/Changelog v7.9.0 + Push + CI + Prod-Health + Tag | ⬜ offen |

## Invarianten (dürfen NIE verletzt werden)
- Live-Pfad / `flights` / State-Machine (poller.py) unangetastet.
- Keine bestehende Wertung (Statistik/Bummel/Kutter) ändert ihr Ergebnis.
- Höhe (AGL > 500 ft) ist Leitsignal fürs Abheben; Groundspeed nur sekundär (`_GPS_FLYING_GS_KT=50`, NICHT 60).
- Landung nur an DB-Platz (<2 kt + AGL-Guard + 10 km); kein Platz → keine Landung (Absturz-Schutz).
- `pytest tests/ -v` bleibt grün (Baseline: 599 passed).

## Log
- Setup: Deps installiert (http-ece manuell, cryptography aktualisiert), Baseline grün (599). Ledger + Plan angelegt.
