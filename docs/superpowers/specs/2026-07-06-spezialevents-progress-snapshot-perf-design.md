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
bleibt leer, `open_transport_flights`-Schleife nicht betreten). Wirkt nur im Freeze-Erstlauf
(Eager wie Lazy, s. §4); der Normalfall liest den Snapshot.

**Präzise Begründung (Fable-Review-Fund 8):** Ein summarized-Event hat _nicht_ zwingend
gar keine offene Verbindung mehr — `transport_anyone_in_progress` (`database.py:4731`)
überspringt Flüge mit Live-Ankunfts-Latch. Deren Fracht steckt aber bereits im geschlossenen
GPS-Leg (C1-Mechanik, `database.py:4864–4873`) → die **Tonnage bleibt korrekt** ohne den
Offen-Zweig. Der Offen-Zweig trägt bei einem abgeschlossenen Event nur noch die kosmetische
`in_air:true/airborne`-Zeile bei (Pilot „unterwegs"), die eingefroren für immer falsch stünde.
Deshalb ist `skip_open_probe` beim Freeze nicht nur billiger, sondern **richtiger**. Rest-Randfall
(Latch OHNE geschlossenes GPS-Leg, z. B. trackless) ist selten; er wird bewusst hingenommen
(dokumentiert unter „Nicht im Scope").

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

- **Kutter** (`/api/transport/events`, `/api/transport/event/{id}`, Badge-Endpoints
  `main.py:1735/1780`, **und** `GET /api/admin/transport/payloads` `main.py:1900` — der rechnet
  heute für `unmapped_types` jedes Event live durch, Fable-Fund 7): `finished = bool(ev["summarized_at"])`,
  `compute_fn = lambda: compute_transport_progress(conn, ev, now, callsign_prefix=prefix,
  skip_open_probe=finished)`.
- **Bummel** (`/api/bummel/races`, `/api/bummel/race/{id}`, Badge-Endpoints `main.py:1074/1125`):
  `finished = bool(race["revealed_at"]) and now >= (race["dtend"] or "")`,
  `compute_fn = lambda: _build_race_view(conn, race, now, force_reveal=False)`.
  **`now >= dtend` ist zwingend (Fable-Fund 2):** die Admin-Notfall-Enthüllung
  (`admin_reveal_race`, `main.py:1530`) setzt `revealed_at` bedingungslos auch VOR `dtend` —
  ein reines `bool(revealed_at)` fröre ein noch laufendes Rennen ein (spätere Legs/Teilnehmer
  fehlten dauerhaft). Der Auto-Reveal (`update_bummel_reveals`) ist ohnehin auf `dtend` gegated.

**Frische Überlagerung beim Snapshot-Read (zeitabhängige / nachlaufende Felder):**
- **Status** frisch aus `_race_status(race, now)` (Bummel) bzw. `_transport_status(ev, now)`
  (Kutter, falls dort verwendet) — nie der eingefrorene Text.
- **Bummel-Metadaten:** Der List-Endpoint nimmt `name/route/dtstart/dtend` weiterhin aus der
  **DB-Zeile `race`**, nicht aus dem eingefrorenen `view` (heute `view["name"]` etc.,
  `main.py:1002–1005`) — so friert nur das Rechenergebnis ein, nie die Metadaten (Kutter macht
  das via `_transport_event_meta(ev, …)` schon so). Fable-Fund 3.
- **KI-Sprüche (Kutter, Fable-Fund 1 — KRITISCH):** `summary_quip` (aus `ev`) und die Pro-Flug-
  `quip`-Felder (aus dem Quips-Store, `get_transport_quips`) werden beim Read **frisch
  überlagert**, gehören also NICHT zur eingefrorenen Identität. Grund: die Quips entstehen erst
  NACH dem `summarized`-Latch (Summary danach, Pro-Flug-Quips async, max. 8/Poll-Lauf) — ein zum
  Latch-Zeitpunkt geschriebener Snapshot hätte sie noch nicht. Siehe auch §4 (Poller darf die
  Quip-Erzeugung nicht abwürgen).

Der List-Endpoint pickt aus dem (frozen oder live) Dict wie bisher seine Teilmenge
(Kutter: Tonnage/Fortschritt; Bummel: `participant_count`/`status`).

**Konsistenz-Hinweis (Fable-Fund 7):** `get_progress_snapshot` parst pro Read **frisch** aus
`payload_json` (liefert nie ein geteiltes veränderliches Dict) — der Detail-Endpoint `pop`t
`unmapped_types`, das darf einen späteren Read nicht beeinflussen.

### 4. Eager-Freeze im Poller (nur Kutter — Optimierung)

Der Kutter-Poller hält beim Feierabend das frische `progress` bereits in der Hand. An der
Stelle, wo `set_transport_summarized` erfolgreich latcht (`poller.py:1250`), zusätzlich
`write_progress_snapshot(conn, "kutter", ev["id"], progress, now)` — spart den einmaligen
langsamen Lazy-Erstlauf.

**Eager == Lazy (Fable-Fund 8):** Damit der Eager-Snapshot identisch zum späteren Lazy-Recompute
(`skip_open_probe=True`) ist, VOR dem Schreiben im `progress` alle `flights`-Einträge
normalisieren: `in_air`/`airborne` → `False` (ein abgeschlossenes Event hat niemanden mehr
„unterwegs"). Die Tonnage bleibt unverändert.

**Poller-Gate (Fable-Fund 1 — Quips nicht abwürgen!):** Trägt ein Event `summarized_at`, werden
`detect_transport_losses` (schon gegated) **und** `compute_transport_progress` übersprungen — der
Endpoint bedient abgeschlossene Events aus dem Snapshot. **Aber:** die KI-Sprüche laufen NACH dem
Latch weiter (Summary + Pro-Flug-Quips, max. 8/Lauf). Das Gate darf sie nicht stoppen — solange
für das Event noch Quips fehlen, sammelt der Poller die offenen Quip-Jobs weiter, und zwar aus
der **`flights`-Liste des Snapshots** (billiger Read), NICHT über einen erneuten Live-Compute.
Erst wenn alle beladenen Flüge einen Quip haben, ist das Event für den Poller „ruhig". (Da die
Quips beim Endpoint-Read ohnehin frisch überlagert werden (§3), muss der Snapshot dafür nicht neu
geschrieben werden.)

Bummel wird **lazy-only** eingefroren (der Reveal-Poller `_check_bummel_reveals` baut die View
nicht selbst — die lebt in `main.py`). Ein enthülltes Rennen friert beim ersten Endpoint-Abruf
ein (ein langsamer Erstlauf, danach schnell). Bewusste Asymmetrie: reine Optimierung, keine
Korrektheitsfrage.

### 5. Invalidierung (Snapshot verwerfen)

Ein Snapshot muss weg, sobald sich seine Eingaben **bewusst** ändern (Daten-Edits/Overrides).
Nicht-bewusste Hintergrund-Änderungen bleiben eingefroren (§ „Nicht im Scope", Nutzer-Wahl).

**Kutter (`app/main.py`):**
- `admin_update_transport_event` (`main.py:1840`) → `delete_progress_snapshot(conn, "kutter",
  event_id)`. **Wichtig (Fable-Fund 5):** der Delete muss **unbedingt** feuern, auch wenn der
  Body leer ist / `fields` leer bleibt (heute überspringt `main.py:1859` bei leerem Body das
  Update). Damit ist ein „Event im Admin nur antippen + speichern" der bewusste **manuelle
  Neuberechnungs-Hebel** für ein abgeschlossenes Event (nächster Read friert frisch ein).
- `admin_delete_transport_event` (`main.py:1881`) → `delete_progress_snapshot` (Aufräumen).
- Globale Payload-Map / Default-kg (`/payloads`, `/default-payload`, `main.py:1916/1961`) wirken
  auf **alle** Kutter → `delete_progress_snapshots(conn, "kutter")` (automatisch; Bummel unberührt).
- **Kalender-Sync (Fable-Fund 3):** `upsert_calendar_transport_event` (`database.py:3935`) läuft
  bei jedem Sync (`ON CONFLICT … DO UPDATE`). NICHT pauschal invalidieren (löschte sonst bei
  jedem Sync alle Kalender-Event-Snapshots) — nur bei **tatsächlicher Wertänderung** von
  `route/dtstart/dtend/destination` vorher lesen + `delete_progress_snapshot` aufrufen.

**Bummel (`app/main.py`):**
- Override setzen/löschen (`/override`, `main.py:1597/1621`) → `delete_progress_snapshot("bummel", race_id)`.
- Rennen bearbeiten (`main.py:1500`) → `delete_progress_snapshot("bummel", race_id)` (ebenfalls
  unbedingt, als manueller Hebel); verstecken (`/hide`, `main.py:1561` — hebt Reveal auf) +
  löschen (`main.py:1518`) → `delete_progress_snapshot`.
- Reveal (`/reveal`, `main.py:1530`) braucht kein Delete (es gab noch keinen Snapshot; der
  nächste Read friert frisch ein — sofern `now >= dtend`, s. §3).
- **Kalender-Sync:** `upsert_calendar_bummel_race` (`database.py:3660`) analog Kutter — nur bei
  echter Wertänderung invalidieren.

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

- `list_transport_events(conn, *, since: str | None = None)` — mit `since`:
  `WHERE (dtend IS NULL OR dtend >= ?)` (NULL-Guard für Altbestände, Fable-Fund 9).
- `list_bummel_races(conn, *, since: str | None = None)` — analog `WHERE (dtend IS NULL OR dtend >= ?)`.
- Hinweis (Fable-Fund 9, geprüft): `update_bummel_reveals` iteriert intern seine EIGENE
  ungefilterte `list_bummel_races(conn)` (`database.py:3041`) und bleibt vom Endpoint-`since`
  unberührt — Reveal-Logik weiterhin korrekt.
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
  globale Neuberechnung ausschließlich über die Versions-Konstante `_PROGRESS_SNAPSHOT_VERSION`
  (§6), gezielte über Event-/Rennen-Bearbeitung (§5). **Kein Admin-Button, kein Recompute-Endpoint.**
- **Nach-Abschluss-Daten-Korrekturen bleiben eingefroren (Nutzer-Wahl 2026-07-06, Fable-Fund
  4+5):** Ein nachgetragener `custom_airports`-Eintrag (`main.py:1979`) und ein verspätet
  nachgeladener StatSim-Track (`poller.py:1083`) ändern ein bereits eingefrorenes Event
  **nicht** automatisch. Wer das doch will, tippt das Event im Admin an + speichert (§5,
  unbedingter Delete-Hook) → nächster Read rechnet frisch. Bewusst hingenommener Randfall, kein
  Auto-Invalidierungs-Code.
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
- `test_poller_writes_kutter_snapshot_on_summarize` (inkl. `in_air`/`airborne` im Snapshot auf
  `False` normalisiert — Fable 8).
- `test_poller_skips_compute_when_summarized` (kein `compute_transport_progress`-Aufruf mehr;
  Spy/Mock-Zähler).
- `test_poller_still_generates_quips_after_summarize` (Snapshot beim Latch OHNE Quips geschrieben;
  Folge-Poll erzeugt fehlende Pro-Flug-Quips weiter, obwohl compute gegated — Fable 1).

**`tests/test_admin_api.py` / `tests/test_main.py`:**
- `test_transport_events_uses_snapshot` (summarized-Event liefert Snapshot-Zahlen; `compute`
  nicht aufgerufen — Mock).
- `test_kutter_snapshot_overlays_fresh_quips` (nachträglich erzeugte `summary_quip`/Flug-`quip`
  erscheinen beim Read, obwohl nicht im Snapshot — Fable 1).
- `test_bummel_race_lazy_freezes_on_first_read` (erster Read eines enthüllten Rennens mit
  `now >= dtend` schreibt Snapshot; zweiter liest ihn, `compute_bummel_standings` nicht erneut).
- `test_bummel_force_reveal_before_dtend_not_frozen` (Force-Reveal vor `dtend` → `finished=False`,
  kein Snapshot, weiter live — Fable 2).
- `test_bummel_status_refreshed_from_snapshot` (Status frisch, nicht eingefroren).
- `test_bummel_metadata_from_db_row_not_snapshot` (Rennen nach Reveal umbenannt → Liste zeigt
  neuen Namen trotz altem Snapshot — Fable 3).
- `test_admin_update_kutter_clears_snapshot` (auch bei **leerem** Body — Fable 5) /
  `test_admin_bummel_override_clears_snapshot`.
- `test_admin_payload_change_clears_all_kutter_snapshots`.
- `test_calendar_sync_no_value_change_keeps_snapshot` / `test_calendar_sync_value_change_clears`
  (Fable 3).
- `test_kutter_badge_served_from_snapshot` (Badge rendert aus eingefrorenen `participants`/
  `losses`; nach Versions-Bump frisch — Fable 10d).
- `test_admin_payloads_unmapped_uses_snapshot` (kein Live-`compute` je Event mehr — Fable 7).

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
     Abruf; Bummel-Snapshot nach erstem Abruf eines enthüllten Rennens (mit `now >= dtend`).
   - **Versions-Bump** (`_PROGRESS_SNAPSHOT_VERSION` +1) + Deploy → Snapshots werden beim nächsten
     Abruf frisch geschrieben, `computed_at` neu; Zahlen identisch (bzw. nach Bugfix korrigiert).
   - **Event antippen + speichern** (auch ohne Feldänderung) verwirft dessen Snapshot → nächster
     Read rechnet frisch (manueller Hebel).
   - KI-Sprüche eines frisch abgeschlossenen Kutter-Events erscheinen vollständig, obwohl der
     Snapshot beim Latch (vor der Quip-Erzeugung) geschrieben wurde (Read-Overlay + Poller
     sammelt Quips weiter).
   - Ein künstlich >1 Jahr zurückdatiertes Event/Rennen erscheint nicht mehr im öffentlichen
     Listen-Endpoint, bleibt aber in der Admin-Liste.
