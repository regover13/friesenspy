# FriesenKutter-Fortschritt: Snapshot-Einfrieren + Retention (Perf) — Design

**Datum:** 2026-07-06 · **Task:** #66 · **Typ:** Perf/Architektur (kein reiner Patch)

## Problem (mit Evidenz belegt)

`/api/transport/events` misst live auf Prod **konstant ~2,2–2,6 s** (dreimal gemessen,
identisch → **kein Caching**), bei nur **3 Events**. Zum Vergleich liefert `/api/stats`
1,09 s → 0,09 s (dort greift `flight_cache`). Der Transport-Pfad hat kein Äquivalent.

Zwei sich verstärkende Ursachen:

1. **Zweiter `canonicalize_legs`-Aufruf mit unbegrenzt wachsendem Fenster.**
   `compute_transport_progress` ruft `canonicalize_legs` zweimal:
   - `database.py:4788` — `end=min(now, dtend)` → auf das Event-Fenster begrenzt (günstig).
   - `database.py:4798` (`open_legs_probe`) — `end=now`. Für ein 5 Tage altes Event scannt das
     die Positionen **aller FRS-Piloten über 5 Tage**, und dieser Aufwand **wächst mit jedem
     Tag**, den das Event altert. Erklärt „wird mit der Zeit langsamer".

2. **Abgeschlossene Events werden trotzdem voll gerechnet — überall:**
   - `/api/transport/events` (`main.py:1660`) hat **keinen** `summarized_at`-Filter → jedes
     abgeschlossene Event wird bei jedem Tab-Öffnen 2× komplett gerechnet.
   - Der Poller `_check_transport_events` (`poller.py:1226`, alle **60 s**) ruft
     `compute_transport_progress` **bedingungslos** für jedes gestartete Event auf; nur
     `detect_transport_losses` ist per `not summarized_at` gegated. Das Ergebnis
     abgeschlossener Events wird danach verworfen (reine Verschwendung).

Skaliert **linear mit der Event-Zahl**. Rahmenbedingung des Nutzers: es wird zweistellige
Event-Zahlen geben (ein Jahr Daten), nichts wird gelöscht, aber „nach einem Jahr nichts mehr
anzeigen"; außerdem: „ein abgeschlossenes Event soll sich nicht mehr ändern".

## Warum Snapshot statt Live-Cache (Nutzer-Klärung 2026-07-06)

Der Nutzer will explizit, dass ein abgeschlossenes Event **eingefroren** bleibt und nur durch
bewusste Changes/Bugfixes neu gerechnet wird. Das ist genau die Semantik eines **Snapshots**,
der beim Feierabend (`summarized_at`) einmal geschrieben wird — nicht die eines Lazy-Cache, der
nach jedem Deploy still neu materialisieren würde. Die einzige Live-Alternative (periodisch
neu materialisierter Cache wie `flight_cache`) wurde bewusst verworfen: sie erfüllt „friert
ein" nicht und ihr Hintergrund-Rechenaufwand wächst mit der Gesamt-Event-Zahl.

## Architektur

### 1. Snapshot-Tabelle (neue Wahrheit für abgeschlossene Events)

Neue Tabelle in `_DDL` (`app/database.py`):

```sql
CREATE TABLE IF NOT EXISTS transport_progress_snapshot (
    event_id     INTEGER PRIMARY KEY,   -- 1:1 zum Event (ON DELETE via Event-Löschung mitgeführt)
    computed_at  TEXT NOT NULL,         -- wann eingefroren (Diagnose/Anzeige)
    progress_json TEXT NOT NULL         -- vollständiges compute_transport_progress-Dict als JSON
);
```

Eigene Tabelle statt Spalte in `transport_events`: hält den JSON-Blob aus jeder
`list_transport_events`-Query heraus (die Liste lädt ihn nur gezielt per Event).

**Helfer (`app/database.py`):**
- `get_transport_snapshot(conn, event_id) -> dict | None` — deserialisiertes progress-Dict
  oder `None`.
- `write_transport_snapshot(conn, event_id, progress, computed_at)` — `INSERT OR REPLACE`,
  `progress` via `json.dumps` (Dict ist bereits JSON-serialisierbar; `_conn_logon` wird von
  `compute_transport_progress` vor der Rückgabe entfernt — vor dem Dump als Sicherung erneut
  aus jedem `flights`-Eintrag poppen, falls künftig doch drin).
- `delete_transport_snapshot(conn, event_id)` — für „Neu berechnen" + Event-Bearbeitung/-Löschung.

### 2. `compute_transport_progress`: `open_legs_probe` bei summarized überspringen

Wenn das Event bereits `summarized_at` trägt (final, `transport_anyone_in_progress` war
nachweislich `False` → kein offenes qualifizierendes Leg mehr möglich), den zweiten
`canonicalize_legs`-Aufruf (`open_legs_probe`) **und** den Offen-Flug-Zweig überspringen.
`current_leg_by_cid` bleibt leer, `open_transport_flights`-Schleife wird nicht betreten.

Neuer Parameter: `compute_transport_progress(..., skip_open_probe: bool = False)`. Aufrufer,
die ein Event mit `summarized_at` haben, setzen `skip_open_probe=True`. (Für aktive Events ist
das Fenster ohnehin auf `now ≈ dtend` begrenzt — kein wachsendes Fenster mehr, sobald
abgeschlossene Events per Snapshot bedient werden.)

Diese Optimierung wirkt nur im Fallback-Pfad (summarized-Event ohne Snapshot, z. B. Alt-Event
oder direkt nach „Neu berechnen"). Der Normalfall bedient summarized-Events aus dem Snapshot
und ruft `compute` gar nicht.

### 3. Poller (`_check_transport_events`) — Gate + Snapshot-Write

Der Loop bleibt strukturell gleich, aber:

- **Gate**: Trägt ein Event `summarized_at` **und** existiert ein Snapshot →
  `compute_transport_progress` (und `detect_transport_losses`, schon gegated) überspringen.
  Nichts weiter zu tun (alle Latches längst gesetzt).
- **Snapshot-Write beim Feierabend**: An der Stelle, wo `set_transport_summarized` erfolgreich
  latcht (`poller.py:1250`), ist `progress` bereits berechnet → sofort
  `write_transport_snapshot(conn, ev["id"], progress, now)`. Ein Aufruf, deterministisch.
- **Heil-Pfad für summarized-ohne-Snapshot** (Alt-Events vor diesem Feature; direkt nach „Neu
  berechnen"): Trägt ein Event `summarized_at`, aber **keinen** Snapshot → einmal
  `compute_transport_progress(..., skip_open_probe=True)` rechnen, `write_transport_snapshot`,
  fertig (kein Push/keine Latch-Änderung — die sind schon final).

Damit gilt invariant: **jedes summarized-Event hat nach spätestens einem Poll-Zyklus (≤60 s)
einen Snapshot** und wird danach nie wieder gerechnet.

### 4. Endpoints (`app/main.py`)

Neuer Helfer `_transport_progress_view(conn, ev, now, prefix) -> dict`:
- Trägt `ev["summarized_at"]` → `get_transport_snapshot`; bei Treffer diesen zurückgeben.
- Sonst live `compute_transport_progress(conn, ev, now, callsign_prefix=prefix,
  skip_open_probe=bool(ev.get("summarized_at")))`.

`/api/transport/events` und `/api/transport/event/{event_id}` nutzen beide diesen Helfer statt
direkt `compute_transport_progress`. (Badge-Endpoints `main.py:1735/1780` ebenfalls, da sie
`_kutter_badge_data` aus demselben progress-Dict speisen — konsistente Zahlen.)

### 5. Retention (Teil der GLOBALEN 365-Tage-Grenze)

**Nutzer-Klärung 2026-07-06:** Die 365-Tage-Grenze gilt **global für alle Daten** (Kutter,
Bummel, Statistik, Piloten …), nicht nur für Kutter-Events. Sie ist eine **Anzeige**-Grenze
(nichts wird gelöscht), umgesetzt über eine geteilte Konstante `_DATA_RETENTION_DAYS = 365`
in `database.py`. Die Anwendung auf Bummel/Statistik/Piloten läuft in einem **eigenen
Companion-Task** (technisch unabhängig vom Kutter-Snapshot); hier wird nur der Kutter-Teil
umgesetzt und die geteilte Konstante angelegt.

Signatur erweitern: `list_transport_events(conn, *, since: str | None = None)`. Mit `since`
wird `WHERE dtend >= ?` ergänzt.

- **API** (`/api/transport/events`) übergibt `since = now − _DATA_RETENTION_DAYS Tage`.
- **Poller** übergibt `since=None` (unverändertes Verhalten; Alt-Events sind ohnehin
  summarized+snapshottet und werden per Gate übersprungen — kein Grund, sie aus dem Loop zu
  verlieren, falls doch mal ein Snapshot fehlt und geheilt werden muss). Bewusste Entscheidung:
  Retention ist eine **Anzeige**-Grenze, keine Verarbeitungsgrenze.
- **Admin-Liste** (`/api/admin/transport/events`, `main.py:1800`): `since=None` (Admin sieht
  alles, auch >1 Jahr — zum Pflegen/Neu-Berechnen).

### 6. Admin „🔄 Neu berechnen"

Neuer Endpoint `POST /api/admin/transport/events/{event_id}/recompute` (require_admin):
- `delete_transport_snapshot(conn, event_id)`.
- Sofort `compute_transport_progress(conn, ev, now, prefix,
  skip_open_probe=bool(ev.get("summarized_at")))` rechnen und
  `write_transport_snapshot(...)` — synchron, damit der Admin sofort frische Zahlen sieht
  (statt bis zu 60 s auf den Poller zu warten).
- Rückgabe: `{"status": "ok", "computed_at": now}`.

**Snapshot auch bei Event-Bearbeitung verwerfen:** In `admin_update_transport_event`
(`main.py:1840`) nach `update_transport_event` → `delete_transport_snapshot(conn, event_id)`.
So zeigt ein bearbeitetes abgeschlossenes Event nicht dauerhaft veraltete Zahlen; der
Heil-Pfad im Poller (≤60 s) oder ein manuelles „Neu berechnen" schreibt frisch.
Bei `admin_delete_transport_event` (`main.py:1881`) ebenfalls `delete_transport_snapshot`
(Aufräumen; harmlos, da PK verwaist sonst nur Speicher belegt).

**Frontend (`app/static/admin.html`):** Bei abgeschlossenen (summarized) Events in der
Event-Liste einen Button „🔄 Neu berechnen" → `POST …/recompute` → kurze Bestätigung,
Liste neu laden. (Mobil-Regeln der CLAUDE.md beachten, falls in einer Tabelle.)

## Synergie mit #64

#64 (KPI-Kennzahlen für Frachtflüge unter „Statistiken": Gesamt-Tonnage, Verluste) aggregiert
über Events. Mit den Snapshots wird diese Aggregation für abgeschlossene Events **billig**
(nur JSON-Reads, kein `canonicalize_legs`). #66 legt also die Grundlage für ein performantes
#64. #64 bleibt aber ein eigener Task (eigene Spec/Plan).

## Nicht im Scope (YAGNI)

- Kein globaler `flight_cache`-artiger Voll-Materialisierungs-Job (bewusst verworfen, s. o.).
- Keine Änderung an der GPS-Leg-Erkennung selbst (`_gps_flights_for_positions`).
- Kein automatischer Snapshot-Invalidierung bei Deploy/Code-Änderung — bewusst: „friert ein",
  Korrektur nur über „Neu berechnen" (Nutzer-Wunsch).

## Tests

**`tests/test_database.py`:**
- `test_transport_snapshot_roundtrip` — write/get/delete.
- `test_write_snapshot_strips_conn_logon` — `_conn_logon` landet nie im JSON.
- `test_compute_skip_open_probe_omits_open_branch` — mit `skip_open_probe=True` erscheint ein
  aktuell offener Strecken-Flug NICHT im Feed (Offen-Zweig übersprungen), ohne Flag schon.
- `test_list_transport_events_retention` — `since` filtert Events mit `dtend < since` aus,
  ohne `since` erscheinen alle.

**`tests/test_poller.py`** (bzw. bestehende Transport-Poller-Tests erweitern):
- `test_poller_writes_snapshot_on_summarize` — nach dem Feierabend-Latch existiert ein
  Snapshot mit den finalen Zahlen.
- `test_poller_skips_compute_when_summarized_with_snapshot` — `compute_transport_progress`
  wird für ein summarized-Event mit Snapshot nicht mehr aufgerufen (Spy/Mock-Zähler).
- `test_poller_heals_summarized_without_snapshot` — summarized-Event ohne Snapshot bekommt beim
  nächsten Poll einen geschrieben.

**`tests/test_admin_api.py` / `tests/test_main.py`:**
- `test_transport_events_uses_snapshot` — summarized-Event: Endpoint liefert Snapshot-Zahlen,
  `compute_transport_progress` wird nicht aufgerufen (Mock).
- `test_admin_recompute_rewrites_snapshot` — POST recompute verwirft + schreibt neu, Rückgabe ok.
- `test_admin_update_event_clears_snapshot` — nach Bearbeitung ist der Snapshot weg.
- `test_admin_recompute_requires_admin`.

## Doku / Version (stehende Regeln)

- `app/CHANGELOG.json`: neuer Top-Eintrag **ohne** highlight (kein Major). Deutsche
  typografische Anführungszeichen („ ") — ASCII-`"` bricht das JSON. Items: Snapshot-Einfrieren
  abgeschlossener Kutter-Events (Perf), Retention 1 Jahr, Admin „Neu berechnen".
- Git-Tag `vX.Y.Z` (Minor). VOR `git push origin main` Nutzer-Bestätigung (Memory-Regel).
- `docs/architecture.md`: neue Tabelle `transport_progress_snapshot`, Snapshot-Fluss
  (Poller-Write, Endpoint-Read, Heil-Pfad), Retention, neuer Admin-Endpoint.
- `docs/api.md`: `POST /api/admin/transport/events/{id}/recompute`; `/api/transport/events`
  Retention-Hinweis (nur letztes Jahr).
- `README.md`: kurzer Hinweis auf eingefrorene abgeschlossene Events, falls betroffen.

## Verifikation

1. `pytest tests/ -v` komplett grün.
2. Nach Deploy:
   - `/api/transport/events` messen: sollte deutlich unter dem alten ~2,5 s liegen und
     **nicht** mit dem Alter der abgeschlossenen Events wachsen.
   - Snapshot für die abgeschlossenen Bestands-Events existiert nach ≤60 s (Heil-Pfad).
   - Admin „Neu berechnen" an einem abgeschlossenen Event → Zahlen identisch (oder nach
     zwischenzeitlichem Bugfix korrigiert), Snapshot `computed_at` frisch.
   - Retention: ein künstlich >1 Jahr zurückdatiertes Event erscheint nicht mehr in
     `/api/transport/events`, aber weiter in der Admin-Liste.
