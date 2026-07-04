# SDD-Ledger — Fix v8.1.0 (GPS-Anzeige entkoppeln + Detektor-Korrekturen)

Branch: feat/gps-display-decouple  (Baseline: 687 tests grün)
Plan: C:\Users\Tobias\.claude\plans\spicy-splashing-newell.md

## Tasks
- [x] T1: collapse_same_airport — X->X nur Stop-and-Go absorbieren (a5b5708) [Fable clean]
- [x] T2: Takeoff-Trigger AGL>500 OR (gs>50 UND steigend) (2872504) [Fable clean]
- [x] Fable-Review-Nachbesserungen T1/T2 (M1/M3/M4 gefixt; I1 = Doku, Schwelle bewusst 300s)
- [x] T3: last_pos_ts-Feld (database.py) + cid-Track-Endpoint (main.py) — is_live/Ghost = Frontend
- [~] T4: /api/events -> canonicalize_legs (#33) — VERSCHOBEN auf v8.2.0 (Nutzer-Entscheidung:
      scoring-nah, kein Testnetz, groesser -> separat mit Charakterisierungs-Tests)
- [x] T5 (Piloten-Detail): renderFlightsList GPS-only entkoppelt (Track immer via last_pos_ts,
      laeuft via _isLiveLeg, Strecke neutral / Plan klickbar / Track klickbar, Ghost-Filter)
      -- Events-Tabelle Teil von v8.2.0.
- [x] T6: Changelog v8.1.0 + Docs (api.md/architecture.md) ; Deploy/Verify offen
- [x] SUMMEN-GATE (Snapshot v8.0.0 vs Branch): legs 1978->2031 (+53 Platzrunden-Splits),
      block -0.16%, dur +0.47% (genauerer frueher Takeoff), keine absurden Sprünge,
      dur>block-Verletzungen 4->2 (Fix-Ziel), Reiner 01.07 korrekt 2 Legs. SAUBER.

Design-Notiz: is_live + dur=0-Ghost-Filter sind FRONTEND-Sache (zeitabhaengig, aus last_pos_ts +
duration_min/distance_nm) — haelt canonicalize_legs deterministisch + cache-sicher.
Bekannter Minor (Fable M2, nicht gefixt): ground_ref min-verankert + AGL>100 ohne Mindeststeigrate
-> bei alt-Glitch/Hochgebirgsplatz + gs>50 theoretisch Ghost-Takeoff. Braucht Datenfehler; niedrige Prio.

## Log
