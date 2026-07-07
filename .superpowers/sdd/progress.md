# SDD-Ledger — #64 Spezial-Events-KPIs im Statistiken-Tab

Plan: docs/superpowers/plans/2026-07-07-spezialevents-kpi-statistiken.md
Basis vor Task 1: fb2c419

- Task 1: complete (commit e7e4250, review clean — 2 reine Aggregatfunktionen + 4 Tests, 848 grün)
- Task 2: complete (commit cc52ffe, review clean — Endpoint + NULL-dtend-Guard + 2 Tests, 850 grün)
  - Minor (fürs finale Review, MUSS wegen Symmetrie): Bummel-Zweig nur indirekt (Null-Fall)
    getestet → im Whole-Branch-Review einen Bummel-Wiring-Test ergänzen (revealed_at+now>=dtend
    → korrekte race_count/participations/legs/avg).
- Task 3: complete (commits 5dc3dbe + Fix 237bf56, review clean — Panel + KPI-Render; Important-Fund
  (early-return-Kopplung) gefixt: fetchSpecialEventStats jetzt in fetchStats unabhängig, 850 grün)
- Task 4: complete (commit a8f40ae, JSON valide v8.11.0 — api.md + architecture.md + CHANGELOG)
- Bummel-Wiring-Test ergänzt (commit 2f2bd97, Symmetrie-Lücke geschlossen, 851 grün)
- Finales Whole-Branch-Review (fable): GO-MIT-ÄNDERUNGEN, keine KRITISCH.
  - WICHTIG-1 (Blau-Regel): Nutzer wählt neutral/weiß → .stats-kpi-value global auf --text-bright
    (beide Panels), HINWEIS-2 (Drill-Down-Panel folgt Zeitraum) mitgenommen (commit 97aa967).
  - HINWEIS-3/4 (nicht-enthülltes-Rennen-Test, Fehlerpfad-Panel) optional, bewusst offen gelassen.
- Alle Tasks + Fixes fertig, 851 grün. Offen: Tag v8.11.0 + Push (nach Nutzer-OK).
