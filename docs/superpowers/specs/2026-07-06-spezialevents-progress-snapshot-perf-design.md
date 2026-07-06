# Spezial-Events (Kutter + Bummel): Fortschritt einfrieren + Retention (Perf) — Design

**Datum:** 2026-07-06 · **Task:** #66 (+ Companion #67 Retention) · **Typ:** Perf/Architektur

## Problem (mit Evidenz belegt)

Zwei Listen-Endpoints rechnen bei **jedem** Request **jedes** Event/Rennen live neu
(`canonicalize_legs`), ungecached, in einer Schleife — Kosten wachsen **linear mit der
Menge**:

| Endpoint | Live gemessen (Prod) | Einträge | Cache? |
|---|---|---|---|
| `/api/transport/events` | ~2,2–2,6 s | 3 Events | nein |
| `/api/bummel/races` | ~1,2–1,4 s | 1 Rennen | nein |
| `/api/stats` (Vergleich) | 1,09 → 0,09 s | — | **ja (`flight_cache`)** |

Kutter (`compute_transport_progress`) ruft `canonicalize_legs` sogar **2×** pro Event (der
zweite Aufruf `open_legs_probe`, `database.py:4798`, hat `end=now` → für ein 5 Tage altes Event
ein **täglich wachsendes** Positions-Fenster über alle FRS-Piloten). Bummel
(`compute_bummel_standings` via `_build_race_view`, `main.py:971`) ruft es 1× pro Rennen.

Rahmenbedingungen des Nutzers (Klärung 2026-07-06):
- Es wird **zweistellige** Event-/Rennen-Zahlen geben (ein Jahr Daten, wöchentliche Nutzung).
- **Nichts löschen**, aber „nach einem Jahr nichts mehr anzeigen".
- „Ein **abgeschlossenes** Event soll sich nicht mehr ändern" (nur durch bewusste Bugfixes/Changes).
- Die **Übersicht soll pro Event eine Kennzahl behalten** (Kutter: Tonnage/Fortschritt; Bummel:
  Teilnehmerzahl/Status) — deshalb kann die Liste nicht auf reine Metadaten reduziert werden.

## Kern-Einsicht

Ein Spezial-Event ist nur **kurz live** (begrenztes Zeitfenster), danach für immer fertig. Die
Übersicht braucht pro Event eine berechnete Kennzahl. Also:
- **Aktive Events** (im Normalfall **höchstens eines** — Events werden nacheinander terminiert;
  Überlappung nur beim Testen, z. B. Test-Bummel auf einem Montagsflug): live rechnen — bei ≤1
  quasi gratis, auch bei 2–3 billig. Das Design **hängt nicht** von „genau eins" ab (es rechnet
  schlicht alle gerade aktiven), bleibt also bei Test-Überlappung korrekt.
- **Abgeschlossene Events** (sammeln sich an): Kennzahl ist **konstant** → **einmal speichern
  statt ewig neu rechnen**. Das ist ein **Snapshot**, geschrieben beim Abschluss.

Kein Live-materialisierter Cache (wie `flight_cache`): der würde abgeschlossene Events nach
jedem Deploy still neu schreiben (verletzt „friert ein") und sein Rechenaufwand wüchse mit der
Gesamt-Zahl. Snapshot friert ein und rechnet nur einmal.

„Warum Kutter UND Bummel, aber nicht FFFreitag?" — **Bummel ist ein eigenes Spezial-Event wie
Kutter** (Tabelle `bummel_races`, eigene Wertung, frei terminierbar). FFFreitag/Wunschradio
sind **reguläre** Kalender-Termine über `/api/events` (Einzel-Abruf auf Klick, **O(1)**,
skaliert nicht mit der Datenmenge) → kein Einfrieren nötig. Betroffen sind genau die zwei
Spezial-Events mit **Scoreboard-Schleife** in der Liste.

„Abschluss" pro Typ:
- **Kutter**: `transport_events.summarized_at` gesetzt (Feierabend-Latch — `transport_anyone_in_progress`
  war nachweislich `False`).
- **Bummel**: `bummel_races.revealed_at` gesetzt (Enthüllung — Wertung/Zeiten stehen final).

## Architektur

### 1. Gemeinsame Snapshot-Tabelle

Neue Tabelle in `_DDL` (`app/database.py`):

```sql
CREATE TABLE IF NOT EXISTS progress_snapshot (
    kind         TEXT NOT NULL,        -- 'kutter' | 'bummel'
    ref_id       INTEGER NOT NULL,     -- transport_events.id bzw. bummel_races.id
    code_version TEXT NOT NULL,        -- _PROGRESS_SNAPSHOT_VERSION zum Zeitpunkt des Einfrierens
    computed_at  TEXT NOT NULL,        -- wann eingefroren (Diagnose/Anzeige)
    payload_json TEXT NOT NULL,        -- eingefrorenes Rechenergebnis als JSON
    PRIMARY KEY (kind, ref_id)
);
```

Modul-Konstante `_PROGRESS_SNAPSHOT_VERSION = "1"` in `database.py`. **Bei jeder Änderung, die
das Rechenergebnis von `compute_transport_progress` oder `compute_bummel_standings`/
`_build_race_view` beeinflusst, wird diese Konstante im selben Commit erhöht** — dadurch werden
alle bestehenden Snapshots automatisch als veraltet erkannt und beim nächsten Abruf frisch neu
eingefroren (die globale „Neu berechnung" ohne Knopf, ohne manuellen Schritt).

**Helfer (`app/database.py`):**
- `get_progress_snapshot(conn, kind, ref_id) -> dict | None` — liefert das deserialisierte
  Payload-Dict **nur**, wenn `code_version == _PROGRESS_SNAPSHOT_VERSION`; sonst `None`
  (versionsveralteter Eintrag wird ignoriert und beim nächsten `write` via PK überschrieben).
- `write_progress_snapshot(conn, kind, ref_id, payload, computed_at)` — `INSERT OR REPLACE`
  mit `code_version = _PROGRESS_SNAPSHOT_VERSION`, `json.dumps(payload)`. Vor dem Dump aus jedem
  `flights`-Eintrag ein evtl. vorhandenes internes `_conn_logon` poppen (Sicherung;
  `compute_transport_progress` entfernt es bereits).
- `delete_progress_snapshot(conn, kind, ref_id)` — gezielte Invalidierung (ein Event/Rennen).
- `delete_progress_snapshots(conn, kind)` — alle eines Typs (globale **Daten**-Änderung, z. B.
  Zuladungs-Map).

### 2. `compute_transport_progress`: `open_legs_probe` bei Abschluss überspringen

Neuer Parameter `skip_open_probe: bool = False`. Ist er `True` (Aufrufer setzt ihn bei
Events mit `summarized_at`), werden der zweite `canonicalize_legs`-Aufruf (`open_legs_probe`,
`database.py:4798`) **und** der gesamte Offen-Flug-Zweig übersprungen (`current_leg_by_cid`
bleibt leer, `open_transport_flights`-Schleife nicht betreten). Sicher, weil ein summarized-Event
per Definition kein offenes qualifizierendes Leg mehr hat. Wirkt nur im Lazy-Freeze-Erstlauf
(s. u.); der Normalfall liest den Snapshot.

### 3. Universeller Zugriff: „eingefroren oder rechnen" (`app/main.py`)

Ein gemeinsamer Helfer kapselt die Lazy-Freeze-Logik für beide Typen:

```
_frozen_or_compute(conn, kind, ref_id, *, finished, compute_fn, now) -> dict:
    if finished:
        snap = get_progress_snapshot(conn, kind, ref_id)
        if snap is not None:
            return snap
        result = compute_fn()                       # Lazy-Freeze: einmal rechnen …
        write_progress_snapshot(conn, kind, ref_id, result, now)  # … und einfrieren
        conn.commit()
        return result
    return compute_fn()                             # aktiv → live
```

- **Kutter** (`/api/transport/events`, `/api/transport/event/{id}`, Badge-Endpoints):
  `finished = bool(ev["summarized_at"])`,
  `compute_fn = lambda: compute_transport_progress(conn, ev, now, callsign_prefix=prefix,
  skip_open_probe=finished)`.
- **Bummel** (`/api/bummel/races`, `/api/bummel/race/{id}`, Badge-Endpoints):
  `finished = bool(race["revealed_at"])`,
  `compute_fn = lambda: _build_race_view(conn, race, now, force_reveal=False)`.
  Beim Lesen eines Bummel-Snapshots das zeitabhängige Feld `status` frisch überschreiben
  (`_race_status(race, now)`), damit ein enthülltes Rennen nicht mit eingefrorenem Status-Text
  hängt. (Kutter: analog `_transport_status` frisch, falls dort verwendet.)

Der List-Endpoint pickt aus dem (frozen oder live) Dict wie bisher seine Teilmenge
(Kutter: Tonnage/Fortschritt; Bummel: `participant_count`/`status`).

### 4. Eager-Freeze im Poller (nur Kutter — Optimierung)

Der Kutter-Poller hält beim Feierabend das frische `progress` bereits in der Hand. An der
Stelle, wo `set_transport_summarized` erfolgreich latcht (`poller.py:1250`), zusätzlich
`write_progress_snapshot(conn, "kutter", ev["id"], progress, now)` — spart den einmaligen
langsamen Lazy-Erstlauf. **Poller-Gate**: trägt ein Event `summarized_at`, `detect_transport_losses`
(schon gegated) **und** `compute_transport_progress` überspringen — der Endpoint bedient
abgeschlossene Events aus dem Snapshot.

Bummel wird **lazy-only** eingefroren (der Reveal-Poller `_check_bummel_reveals` baut die View
nicht selbst — die lebt in `main.py`). Ein enthülltes Rennen friert beim ersten Endpoint-Abruf
ein (ein langsamer Erstlauf, danach schnell). Bewusste Asymmetrie: reine Optimierung, keine
Korrektheitsfrage.

### 5. Invalidierung (Snapshot verwerfen)

Ein Snapshot muss weg, sobald sich seine Eingaben ändern:

**Kutter (`app/main.py`):**
- `admin_update_transport_event` (`main.py:1840`) nach `update_transport_event` →
  `delete_progress_snapshot(conn, "kutter", event_id)`.
- `admin_delete_transport_event` (`main.py:1881`) → `delete_progress_snapshot` (Aufräumen).
- Manifest/Zuladung: Event-`cargo` (Teil von `admin_update_transport_event`) → das eine Event
  ist über den Delete oben ohnehin schon abgedeckt. Globale Payload-Map / Default-kg
  (`/payloads`, `/default-payload`, `main.py:1916/1961`) wirken auf **alle** Kutter →
  `delete_progress_snapshots(conn, "kutter")` (automatisch im Endpoint; Bummel unberührt).

**Bummel (`app/main.py`):**
- Override setzen/löschen (`/override`, `main.py:1597/1621`) → `delete_progress_snapshot("bummel", race_id)`.
- Rennen bearbeiten (`main.py:1500`), verstecken (`/hide`, `main.py:1561` — hebt Reveal auf),
  löschen (`main.py:1518`) → `delete_progress_snapshot("bummel", race_id)`.
- Reveal (`/reveal`, `main.py:1530`) braucht kein Delete (es gab noch keinen Snapshot; der
  nächste Read friert frisch ein).

### 6. Globale Neuberechnung — ohne Button, via Versions-Konstante

**Kein Admin-Button, kein Recompute-Endpoint, keine Frontend-Änderung.** Der einzige
verbleibende Bedarf ist „Rechen-Code grundsätzlich geändert → alle eingefrorenen Zahlen sind
veraltet". Das erledigt die Konstante `_PROGRESS_SNAPSHOT_VERSION` (Punkt 1): wer den Rechen-Code
ändert, erhöht sie im selben Commit; alle alten Snapshots gelten dann als veraltet
(`get_progress_snapshot` liefert `None`) und werden beim nächsten Abruf frisch neu eingefroren.
Das ist die bewusste, deklarierte „globale Neuberechnung" — an genau der Stelle, an der die
Änderung passiert, statt als vergessbarer manueller Klick nach dem Deploy.

Nutzer-Klärung 2026-07-06: den globalen Button bewusst weggelassen. Gezielte Korrekturen laufen
über die Bearbeitung des einzelnen Events (Punkt 5); grundsätzliche Änderungen über die
Versions-Konstante, die der Entwickler (bzw. Claude beim Umsetzen des Fixes) mit-erhöht.

### 7. Retention (Teil der GLOBALEN 365-Tage-Grenze, #67)

Die 365-Tage-Grenze gilt **global für alle Daten** (Klärung 2026-07-06); Anzeige-Grenze
(nichts löschen). Geteilte Konstante `_DATA_RETENTION_DAYS = 365` in `database.py`. **Hier**
angewandt auf die beiden Spezial-Event-Listen; die breite Anwendung (Statistik/Piloten) läuft
in **#67**.

- `list_transport_events(conn, *, since: str | None = None)` — mit `since`: `WHERE dtend >= ?`.
- `list_bummel_races(conn, *, since: str | None = None)` — analog `WHERE dtend >= ?`.
- **Öffentliche Endpoints** (`/api/transport/events`, `/api/bummel/races`) übergeben
  `since = now − _DATA_RETENTION_DAYS Tage`.
- **Poller** übergibt `since=None` (Retention ist Anzeige-, keine Verarbeitungsgrenze;
  Alt-Events sind ohnehin per Gate/Snapshot billig).
- **Admin-Listen** übergeben `since=None` (Admin sieht + pflegt alles).

## Synergie mit #64

#64 (KPI-Kennzahlen Frachtflüge unter „Statistiken": Gesamt-Tonnage, Verluste) aggregiert über
Kutter-Events. Mit den Snapshots wird die Aggregation abgeschlossener Events **billig** (nur
JSON-Reads). #66 legt die Grundlage; #64 bleibt eigener Task.

## Nicht im Scope (YAGNI)

- Kein `flight_cache`-artiger Voll-Materialisierungs-Job (bewusst verworfen).
- Keine Änderung an der GPS-Leg-Erkennung (`_gps_flights_for_positions`) oder an der Wertung
  selbst (`compute_bummel_standings`, `compute_transport_progress`-Semantik).
- Keine automatische Snapshot-Invalidierung bei Deploy/Code-Änderung — bewusst „friert ein";
  Korrektur nur über den globalen Button oder gezielte Bearbeitung.
- Retention für Statistik/Piloten → #67.

## Tests

**`tests/test_database.py`:**
- `test_progress_snapshot_roundtrip` (write/get/delete, beide `kind`).
- `test_snapshot_ignored_when_version_stale` (`get` liefert `None`, wenn `code_version` ≠
  aktuelle Konstante).
- `test_delete_progress_snapshots_by_kind` (löscht nur den einen `kind`).
- `test_write_snapshot_strips_conn_logon`.
- `test_compute_skip_open_probe_omits_open_branch` (mit Flag verschwindet ein offener
  Strecken-Flug aus dem Kutter-Feed; ohne Flag da).
- `test_list_transport_events_retention` / `test_list_bummel_races_retention` (`since` filtert
  `dtend < since`; ohne `since` alle).

**`tests/test_poller.py`:**
- `test_poller_writes_kutter_snapshot_on_summarize`.
- `test_poller_skips_compute_when_summarized` (kein `compute_transport_progress`-Aufruf mehr;
  Spy/Mock-Zähler).

**`tests/test_admin_api.py` / `tests/test_main.py`:**
- `test_transport_events_uses_snapshot` (summarized-Event liefert Snapshot-Zahlen; `compute`
  nicht aufgerufen — Mock).
- `test_bummel_race_lazy_freezes_on_first_read` (erster Read eines enthüllten Rennens schreibt
  Snapshot; zweiter liest ihn, `compute_bummel_standings` nicht erneut aufgerufen).
- `test_bummel_status_refreshed_from_snapshot` (Status stammt frisch, nicht eingefroren).
- `test_admin_update_kutter_clears_snapshot` / `test_admin_bummel_override_clears_snapshot`.
- `test_admin_payload_change_clears_all_kutter_snapshots`.

## Doku / Version (stehende Regeln)

- `app/CHANGELOG.json`: neuer Top-Eintrag **ohne** highlight (kein Major). Deutsche
  typografische Anführungszeichen („ ") — ASCII-`"` bricht das JSON. Items: abgeschlossene
  Kutter- **und** Bummel-Events eingefroren (Perf), Retention 1 Jahr.
- Git-Tag `vX.Y.Z` (Minor). VOR `git push origin main` Nutzer-Bestätigung (Memory-Regel).
- `docs/architecture.md`: Tabelle `progress_snapshot` (+ `code_version`/`_PROGRESS_SNAPSHOT_VERSION`),
  Freeze-Fluss (Poller-Eager Kutter / Endpoint-Lazy beide, versions-gefilterter Read,
  Invalidierung bei Bearbeitung/Payload), Retention.
- `docs/api.md`: Retention-Hinweis bei den beiden Listen-Endpoints (kein neuer Endpoint).
- `README.md`: kurzer Hinweis auf eingefrorene abgeschlossene Spezial-Events, falls betroffen.

## Verifikation

1. `pytest tests/ -v` komplett grün.
2. Nach Deploy:
   - `/api/transport/events` und `/api/bummel/races` messen: deutlich unter den alten Werten
     und **nicht** mit dem Alter/der Zahl abgeschlossener Einträge wachsend.
   - Kutter-Snapshots der Bestands-Events existieren nach ≤60 s (Poller-Eager) bzw. beim ersten
     Abruf; Bummel-Snapshot nach erstem Abruf eines enthüllten Rennens.
   - Globaler Button „Neu berechnen" leert die Tabelle; Zahlen danach identisch (bzw. nach
     zwischenzeitlichem Bugfix korrigiert), `computed_at` frisch.
   - Ein künstlich >1 Jahr zurückdatiertes Event/Rennen erscheint nicht mehr im öffentlichen
     Listen-Endpoint, bleibt aber in der Admin-Liste.
