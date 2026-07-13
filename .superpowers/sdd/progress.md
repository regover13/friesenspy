# SDD-Ledger — Kuratierter Flugzeug-Spec-Datensatz (v8.17.0)

Plan: docs/superpowers/plans/2026-07-09-aircraft-specs-dataset.md
Spec: docs/superpowers/specs/2026-07-09-aircraft-specs-dataset-design.md
Basis vor Task 1: 5809617

Ausführungsreihenfolge (Abhängigkeit: Validierungstest braucht Loader):
Task 2 (Loader+Seed) → Research (parallel) + Task 1 (JSON+Validierung, Human-Gate) → Task 3 (Admin-UI) → Task 4 (Docs/Version) → Whole-Branch-Review

- Task 2: complete (commit 5273879, 5 Seeding-Tests + Regression 207 grün, Review CLEAN — Spec ✅ / Qualität Approved)
  - Minor (fürs finale Review): (a) DDL-Kommentar app/database.py:250 nennt 'curated' nicht → in Task 4 Docs nachziehen; (b) Seeding dupliziert Spalten-Mapping via rohem INSERT statt upsert_payload (bewusst, INSERT OR IGNORE nötig).
- Research (~106 Specs): complete — 5 Chunks gemerged → scratchpad/aircraft_specs.final.json, 106 Einträge, 0 Plausibilitäts-Warnungen, 6 low + 43 med Konfidenz. Scope: nichts entfernt (nur echte IFR-Airliner wären raus, sind aber nicht dabei; DC3/JU52 bleiben). Offen: A320(M)+Transall als spätere Ergänzung möglich.
- FSEconomy-Abgleich: FSE-Configs (kg-Gewichte, Gallonen-Tanks) gegen Datensatz gematcht. 57 verifizierte Treffer → FSE-Werte übernommen (sim-authentisch), Rest = Recherche. A320 auf NUTZER-Wunsch zurück auf Recherche (78000/42400/19000, NICHT FSE). Finaler Datensatz: scratchpad/aircraft_specs.final.json, 108 Einträge, 0 Warnungen.
- Task 2b (NEUE Nutzer-Anforderung): fuel_full_kg-Spalte (max. Tank) + fuel_kg=Hälfte + Backfill fuel_full=fuel_kg*2. Plan ergänzt. Implementer läuft. Basis: 5273879.
- A320 auf NUTZER-Wunsch KOMPLETT entfernt (Airliner) — 107 Einträge, Transall (C160) bleibt.
- A400M Atlas (ICAO A400) wird ergänzt = der gemeinte "Transall-Nachfolger" (Nutzer meinte nicht A320/A300, sondern A400M). Research läuft (chunkG). Danach 108 Einträge.
- Task 2b: complete (commit fb79696, 902 grün, Review CLEAN — Spec ✅ / Qualität Approved, Spaltenausrichtung 10/10 geprüft).
  - WICHTIG für Task 3: admin_upsert_payload (main.py:2167) muss fuel_full_kg aus dem Body an upsert_payload weiterreichen (Reviewer-Hinweis).
- Task 2c: Poller fuel_full_kg — Implementer läuft (Basis fb79696).
- A400M gemergt → Datensatz FINAL: scratchpad/aircraft_specs.final.json, 108 Einträge, 0 Plausibilitäts-Fehler.
- Task 1: complete (commit ee229fa, 108er-Datensatz eingebacken + Validierung, 130 grün).
- Task 2c: complete (commit fab6ae2, Poller schreibt fuel_full_kg mit).
- Task 3: complete (commit dac9eec, Admin-UI: Namensfeld + Max-Tank-Feld + Auto-Halbierung + main.py-Weiterleitung + Tabelle; 907 grün). Poller-Tests von PZ04→ZZ01 umgestellt (PZ04 jetzt vorbefüllt). Review läuft.
- Task 3: Review CLEAN (Spec ✅ / Qualität Approved, JS-Konsistenz geprüft).
- Task 4: complete (commit fca42a0, CHANGELOG v8.17.0 + api.md + architecture.md + README + DDL-Kommentar 'curated'; 907 grün).
- ALLE TASKS FERTIG. Commits 5273879..fca42a0.
- Finales Whole-Branch-Review (Opus): GO, keine Critical/Important. 2 Minor by-design:
  - M1: INSERT OR IGNORE ersetzt bestehende source='llm'-Zeilen (geflogene Typen) NICHT durch kuratierte Werte → beim User offen gestellt.
  - M2: reiner API-Call nur mit fuel_full_kg ohne fuel_kg → fuel_kg=None (über UI unerreichbar).
- M1 umgesetzt (commit 8bcaa51): Seeding hebt llm/default-Zeilen auf kuratierte Werte, manual bleibt; +Test, 908 grün.
- FERTIG & DEPLOYED: Tag v8.17.0 gepusht (8bcaa51), main gepusht (2ca6134..8bcaa51). GitHub Actions → GHCR → VPS läuft.
- Task 3: offen
- Task 4: offen
