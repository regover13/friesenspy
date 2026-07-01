# Koordination paralleler Sessions

Kurze Absprachen zwischen parallel arbeitenden Claude-Sessions am FriesenSpy-Repo.
Vor jedem Push: `git fetch` + Rebase auf `origin/main`; niemals fremde, uncommittete
Änderungen überschreiben. Einträge bitte oben anfügen (neueste zuerst).

---

## 2026-07-01 — Fable-Session: Analyse-Auftrag Flug-Tracking (docs/fable-analyse-auftrag.md)

**Branch:** `claude/fable-analyse-auftrag-3hgk13` (Releases werden zusätzlich auf `main` gepusht/deployed).

**Bearbeitete Bereiche — bitte parallele Änderungen kurz absprechen:**
- `app/database.py`: `open_flight` (Session-Reopen bei Feed-Aussetzer), `consolidate_flights`
  (Block-Neuberechnung in C/D + neuer Schritt E), `_segments_continuous` (Abgeflogen-Regel),
  `_block_minutes`/`_block_seconds` (Summe bewegter Abschnitte, Standphasen ≥ 10 min raus),
  neu: `reconstruct_orphaned_flights` (läuft in `init_db`).
- `app/poller.py`: `_check_transport_events` (Feierabend wartet auf Nachzügler — Gruppe B, folgt).
- `app/llm.py`: `_QUIP_SYSTEM` (verständliches Hochdeutsch — Gruppe B, folgt).
- Releases: v7.3.1 (Gruppe A), v7.3.2 (Gruppe B, folgt).

**Nicht angefasst** (Produktentscheidungen, siehe Auftrag): #7, #8, #15, #16, #18.
