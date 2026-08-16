# Koordination paralleler Sessions

Kurze Absprachen zwischen parallel arbeitenden Claude-Sessions am FriesenSpy-Repo.
Vor jedem Push: `git fetch` + Rebase auf `origin/main`; niemals fremde, uncommittete
Änderungen überschreiben. Einträge bitte oben anfügen (neueste zuerst).

---

## 2026-08-16 — Karten-Merker auf dem Server (v13.6.3)

**Betrifft `app/static/index.html`, `app/main.py`, `app/database.py`** — bitte beim Rebase
beachten, `index.html` wird gerade von zwei Seiten angefasst.

**Dieser Eintrag ersetzt einen frueheren.** Er beschrieb einen Cookie-Speicher (v13.6.0/13.6.2)
— der Weg ist **verworfen**. Wer ihn noch im Kopf hat: Es gibt kein `fs_karte` als Wahrheit
mehr, nur noch als lokalen Zwischenspeicher.

**Was gilt:** Alle Karten-Merker laufen ueber `_prefLies(key)` / `_prefSchreib(key, wert)`.
Fuehrende Quelle ist `GET/PUT /api/prefs?kontext=panel|web`, Tabelle `panel_prefs`
(cid + kontext). Die **Signaturen der bekannten Zugriffsfunktionen sind unveraendert**
(`_loadLayerPref`, `_loadAIPPref`, `_loadFsePref`, `_naviLies`, …) — wer sie aufruft, merkt
nichts. Nur wer `localStorage.getItem('friesenspy_…')` direkt liest, greift ins Leere.

**Warum:** Im Kniebrett haelt kein Browser-Speicher ueber einen Sim-Neustart — `localStorage`
faellt von 8 Schluesseln auf 0, ein Cookie ist fort. Zwei Anlaeufe sind daran gescheitert,
obwohl es in `panel_devices` und in der EFB-Shell seit dem 13.08. dokumentiert stand.
Ausfuehrlich in `docs/efb-panel-debugging.md` und `docs/architecture.md`.

**Drei Fallen, wenn ihr an dem Bereich arbeitet:**
- `initLiveMap` wartet mit `await _prefsPromise`, BEVOR die Karte gebaut wird. Ohne das
  springt die Basisebene um und der Ebenen-Haken steht falsch.
- `_prefServerPlanen` sendet nichts vor der Serverantwort (`if (!_prefVomServer) return;`).
  Im Kniebrett ist der lokale Stand beim Aufbau leer — ein Zuruecksenden ueberschriebe den
  gespeicherten Stand mit Leere.
- `_trackUp`/`_movingMap` werden beim LADEN des Skripts gelesen, also vor der Antwort. Sie
  werden in `_prefsPromise` nachgezogen, aber nur solange `_naviBeruehrt` false ist.

**Neu dazu:** `friesenspy_tab` und `friesenspy_vollbild` (Zustand des Kniebretts). Die Karte
startet deshalb **nicht mehr unbedingt ueber EDWG** und **nicht mehr unbedingt auf LIVE** —
beides ist jetzt Rueckfall. Zusicherungen dazu stehen in `tests/test_karte_merker.py`.

**Fuer Node-Tests:** Ein Quelltext-Ausschnitt, der `_loadFsePref` o. ae. enthaelt, braucht den
Speicher mit (`_pref_quelltext()` in `tests/test_fse.py`) und im Harness ein
`document.documentElement` sowie ein `fetch` — Muster in `tests/test_karte_merker.py`.
Suite nach dem Rebase auf 4fef390: **1786 gruen**.

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
