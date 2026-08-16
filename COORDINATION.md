# Koordination paralleler Sessions

Kurze Absprachen zwischen parallel arbeitenden Claude-Sessions am FriesenSpy-Repo.
Vor jedem Push: `git fetch` + Rebase auf `origin/main`; niemals fremde, uncommittete
Änderungen überschreiben. Einträge bitte oben anfügen (neueste zuerst).

---

## 2026-08-16 — Karten-Merker ins Cookie (v13.6.0)

**Betrifft `app/static/index.html`** — bitte beim Rebase beachten, die Datei wird gerade
von zwei Seiten angefasst (parallel: Radar-Label-Zuordnung / Sim-Verkehr).

**Was sich geaendert hat:** Alle neun Karten-Merker lesen und schreiben nicht mehr direkt
ueber `localStorage`, sondern ueber `_prefLies(key)` / `_prefSchreib(key, wert)`. Darunter
liegt ein Cookie `fs_karte`. Die **Signaturen der bekannten Zugriffsfunktionen sind
unveraendert** (`_loadLayerPref`, `_loadAIPPref`, `_loadFsePref`, `_naviLies`, …) — wer sie
aufruft, merkt nichts. Nur wer `localStorage.getItem('friesenspy_…')` **direkt** schreibt,
greift ins Leere.

**Grund:** Im Kniebrett ueberlebt `localStorage` keinen Sim-Neustart. Beleg ist ein
Panel-Start, der einen zwei Stunden alten Wert zurueckbekam — das kann kein Anwendungsfehler
sein. Ausfuehrlich in `docs/efb-panel-debugging.md` und `docs/architecture.md`.

**Neu:** `_ausschnittStart()` / `_ausschnittBeobachten(map)` merken Mitte und Zoom der
Live-Karte. Die Karte startet deshalb **nicht mehr unbedingt ueber EDWG** — das ist jetzt der
Rueckfall. Wer sich in einem Test auf `center: _KARTE_MITTE` verlassen hat: Die Zusicherung
steht jetzt in `test_live_karte_oeffnet_ueber_edwg` am Rumpf von `_ausschnittStart`.

**Fuer Node-Tests wichtig:** Ein Quelltext-Ausschnitt, der `_loadFsePref` o. ae. enthaelt,
braucht jetzt auch den Speicher — sonst `_prefLies is not defined`. Muster steht in
`tests/test_fse.py` (`_pref_quelltext()`) und `tests/test_karte_merker.py` (Cookie-Glas als
Attrappe). Suite nach dem Rebase auf 8a7f5dc: **1744 gruen**.

---

## 2026-07-01 — Fable-Session: Analyse-Auftrag Flug-Tracking (docs/fable-analyse-auftrag.md)

**Branch:** `claude/fable-analyse-auftrag-3hgk13` (Releases werden zusätzlich auf `main` gepusht/deployed).

**Status: abgeschlossen.** Ergebnisse in `docs/analyse-bericht-2026-07-01.md`.

**Bearbeitete Bereiche — bitte parallele Änderungen kurz absprechen:**
- `app/database.py`: `open_flight` (Session-Reopen bei Feed-Aussetzer), `consolidate_flights`
  (Block-Neuberechnung in C/D + neuer Schritt E), `_segments_continuous` (Abgeflogen-Regel),
  `_block_minutes`/`_block_seconds` (Summe bewegter Abschnitte, Standphasen ≥ 10 min raus),
  neu: `reconstruct_orphaned_flights` + `transport_anyone_in_progress`.
- `app/poller.py`: `_check_transport_events` (Feierabend wartet auf Nachzügler).
- `app/llm.py`: `_QUIP_SYSTEM` (verständliches Hochdeutsch).
- `.github/workflows/deploy.yml`: Deploy verifiziert jetzt selbst den Health-Endpoint
  (Fehlschlag + Container-Logs, wenn die App nicht antwortet).
- Releases: v7.3.1 (Gruppe A), v7.3.2 (Hotfix Startcrash + B1), v7.3.3 (B2), v7.3.4–v7.3.6
  (Nachfixes Merge/Rekonstruktion/Ghost-Filter nach Praxis-Gegenprüfung), v7.3.7–v7.3.10
  (Zuladungs-Recherche: Zeitbudget + Typ-Hinweise), v7.4.0 (halbe Tanks, Auto-Recherche,
  Typ ohne Flugplan, Mobile-Scroll-Standard → stehende Regel in CLAUDE.md). Suite: 537 grün.
  Details + offene Punkte: docs/analyse-bericht-2026-07-01.md.

**Achtung für andere Sessions:**
- Der Git-Proxy der Remote-Umgebung **verweigert Tag-Pushes** — Tags v7.3.1–v7.3.3 müssen
  lokal nachgezogen werden (Kommandos im Abschlussbericht).
- `init_db` läuft mit ROHER sqlite3-Connection (ohne row_factory) — Funktionen, die dort
  aufgerufen werden, dürfen sich nicht auf benannten Zeilenzugriff verlassen (Prod-Crash
  v7.3.1, behoben in v7.3.2).

**Nicht angefasst** (Produktentscheidungen, siehe Auftrag): #7, #8, #15, #16, #18. Neuer
Diskussionspunkt notiert: Flugerfassung rein GPS-basiert (siehe Bericht).
