# FriesenKutter — „Zeilen statt Strecke" (Redesign des Manifest-Editors)

**Status:** Design (2026-07-07, Rev. 2 nach Fable-5-Review). Reworkt das v8.13.0-Modell
(#15 Sub-Projekt B). Danach folgen als eigene Tasks #77 (ICAO-Validierung) und #78
(Frachtart-Picker) auf der neuen Editor-Struktur.

## Ziel

Das separate Feld **„Strecke"** im Kutter-Editor entfällt. Jede **Fracht-Zeile** trägt ihre eigenen
**Startplätze** (kommagetrennte ICAO-Liste). Der gültige Platz-Satz (Route) wird **automatisch
abgeleitet**. Ein Feld weniger, weniger verwirrend — bildet alle Fälle ab (dieselbe Ware von
mehreren Plätzen, gemischt, „geteilt" = alle Plätze auflisten).

**Nutzer-Entscheidungen 2026-07-07:**
- **KEINE** reinen Ausweichplätze/Waypoint-Zeilen ohne Ware (YAGNI).
- **Manifest ist Pflicht:** ein Kutter-Event MUSS mind. eine Fracht-Zeile mit mind. einem
  Startplatz haben. Der bisherige manifestlose reine kg-Zähler **entfällt** (bewusster Breaking
  Change — war nie gewollt).
- **Ziel ist Pflicht:** `destination` muss beim Anlegen/Speichern gesetzt sein (bisher optional mit
  „letzter Streckenplatz"-Default — dieser Default entfällt).

## Context — heutiges Modell (v8.13.0)

- `transport_events.route` (CSV aller gültigen Plätze) + `destination` + je `transport_cargo` eine
  **einzelne** `departure` (NULL = geteilt).
- `route_set` (aus `route`) treibt: Zähl-Filter (dep & arr in route_set, dep≠arr), Reservierung,
  Verlust-/Rückgabe-Klassifikation (returned = Landung an einem route-Wegpunkt), `transport_event_started`
  / `transport_anyone_in_progress`.
- `_fillable(flight, i)`: `departure IS NULL OR == flight.dep`; Latch-Fallback (geladener Flug ohne
  verwertbaren `dep`) füllt alle Zeilen.
- Kalender: `Fracht EDDW: …` bindet, `Fracht:` = geteilt; Marker-ICAOs werden aus der Routen-
  Sammlung **ausgeschlossen** (Entkontaminierung — sonst kippt ein ferner Tippfehler-ICAO via
  `_route_is_plausible` das ganze Event auf `is_transport=False`).

## Neues Autoren-Modell

- **Kein `Strecke`-Feld** im manuellen Editor. **`destination` bleibt** eigenes Feld, jetzt **Pflicht**.
- Jede Fracht-Zeile: **Ware + kg + Start-ICAO-Liste** (kommagetrennt, **≥1 Platz Pflicht**).
- **„Geteilt" = alle Plätze auflisten.** Im manuellen Editor gibt es **kein** NULL-„geteilt" mehr;
  NULL existiert nur noch (a) für migrierte Alt-Events und (b) für den Kalender-Marker `Fracht:`
  ohne ICAO (s. u.).
- Route wird **abgeleitet** (s. Route-Ableitung), nie manuell eingegeben.

## Datenmodell

- `transport_cargo.departure` wird von „einzelner ICAO" zu **kommagetrennter ICAO-Liste** (delimited
  String im vorhandenen Feld — kein neues Schema). Leer/NULL = geteilt (nur Alt-Events + Kalender-
  `Fracht:`).
- **Eigener Listen-Normalisierer** `_normalize_icao_list(raw) -> str|None`: splittet an Komma,
  trimmt/uppercased je Code, dedupliziert, **sortiert stabil**, gibt CSV oder None zurück. **NICHT**
  `normalize_type_code` verwenden — das schneidet an „/" ab und lässt Innen-Leerzeichen stehen, würde
  jede Multi-Platz-Zeile still auf NULL degradieren (Fable-Fund).
- `transport_events.route` **bleibt als Spalte** und ist weiterhin die Quelle für `route_set` — nur
  die **Befüllung** wird automatisiert. Damit bleibt Loss/Freeze/KPI/Filter-Code unverändert.

## Fracht-Zuordnung (`compute_transport_progress`)

`_fillable(flight, i)`:
- Latch-Fallback unverändert: geladener Flug ohne verwertbaren `dep` (leer/streckenfremd) → alle
  Zeilen.
- Sonst: `deps = split(departure[i])`; füllbar, wenn `deps` leer (Alt-/Kalender-„geteilt") **oder**
  `flight.dep in deps`.

`delivered[]`/`reserved_alloc[]` bleiben global je `position`; gilt für Liefer-, Reservierungs- UND
Verlust-Füllung.

## Route-Ableitung (`_derive_route`)

`_derive_route(conn, cargo, destination, existing_route) -> str`:
```
plätze = ⋃ split(departure) für alle Cargo-Zeilen mit gesetztem departure
if eine Cargo-Zeile hat leeres/NULL departure (geteilt):
    plätze |= split(existing_route)          # Alt-/geteilt-Plätze erhalten (Fable-Fund 4)
plätze |= {destination}
return sortierte, deduplizierte CSV(plätze)   # stabile Sortierung → kein Freeze-Churn
```
- **Stabile Sortierung ist Pflicht:** `upsert_calendar_transport_event` invalidiert den #66-Freeze
  per Routen-**String**-Vergleich; eine ungeordnete Set-CSV würde bei jedem Sync churnen und den
  Snapshot dauernd verwerfen.
- **Manifest-Pflicht** garantiert ≥1 Startplatz → Route ist nie nur `{destination}` → kein
  Regressions-Loch (Fable-Fund 1).
- **Alt-Event-Schutz:** solange eine geteilte (NULL) Zeile existiert, fließt die **bestehende Route**
  mit ein → ein Admin-Edit (auch nur Name/Datum) an einem geteilten Alt-Event **verliert seine Route
  nicht** (Fable-Fund 4). Neue Events (alle Zeilen mit Plätzen, keine NULL) brauchen die alte Route
  nicht.

Aufgerufen bei `create_transport_event`, `update_transport_event` (auch bei partiellen Updates
OHNE `cargo` — dann Manifest frisch aus der DB lesen, damit eine reine Ziel-Änderung die Route
korrekt neu bildet) und `upsert_calendar_transport_event`.

## Pflicht-Validierung (manueller Pfad)

`create_transport_event` / `update_transport_event` (bzw. der Admin-Endpoint) lehnen mit **400** ab:
- kein `destination`,
- kein Cargo bzw. keine Zeile mit ≥1 gültigem Startplatz,
- eine Start-Liste, die nach Normalisierung leer ist (**kein** stiller NULL-Fallback wie heute in
  `set_transport_cargo` 4188 — der bleibt nur für den Kalenderpfad),
- Startplatz **== destination** wird aus der Liste verworfen (ein am Ziel startender Flug ist per
  Rückflug-Filter nie füllbar); bleibt die Liste dadurch leer → 400.

`_default_destination`-Zirkularität ist damit tot: ohne Pflicht-Ziel kein Default auf den „letzten
Routenplatz" (der jetzt ein Ladeplatz wäre). `_UPDATABLE_TRANSPORT_FIELDS` **verliert `route`** —
ein gecachtes altes admin.html kann die abgeleitete Route nicht mehr überschreiben.

## Kalender

- `_CARGO_MARKER_RE` erweitern: der optionale ICAO wird zur **Liste** — `Fracht EDDW, EDWG: 500
  Äpfel` bindet an {EDDW, EDWG}. `parse_cargo_lines` liefert `departure` (CSV) oder lässt es weg
  (plain `Fracht:` = geteilt/NULL — bleibt für Kalender erlaubt, Rückwärtskompatibilität).
- **Tippfehler-Schutz bleibt in DIESEM Task** (nicht auf #77 vertagen — #77 prüft nur Existenz,
  nicht Distanz):
  - `_route_is_plausible` / die Basis-Route weiter **nur aus location/summary** berechnen (ohne
    Marker-ICAOs) — der Plausibilitäts-Check darf nicht durch einen Marker gekippt werden.
  - Marker-ICAOs **einzeln** in die Route aufnehmen, nur wenn **auflösbar** (`icao_to_coords`) UND
    innerhalb `_MAX_BUMMEL_SPAN_KM` zur Basis-Route/zum Ziel. Ein verworfener Marker **degradiert
    seine Zeile auf geteilt** (NULL) — kostet nie mehr als seine eigene Zeile, nie das Event.
- **Ziel-Default im Kalender** (`_default_destination`) aus der Route **ohne** Marker-Plätze
  berechnen — sonst würde ein hinten angehängter Cargo-Startplatz still zum Ziel.

## Admin-UI (`admin.html`)

- **Strecke-Feld entfernen** aus dem Event-Editor.
- Start-Feld je Fracht-Zeile auf **mehrere ICAOs** (kommagetrennt) erweitern (Platzhalter „Start
  ICAO(s), z. B. EDDW, EDWG").
- Beim Speichern **keine `route` mehr senden** — Backend leitet ab. Ziel-Feld als Pflicht markieren.
- Streckenfremd-Warnung entfällt; Ziel==Startplatz-Hinweis bleibt.

## Öffentliche Ansicht (`index.html`)

Die Balkengruppierung nach `c.departure` (index.html ~4677) bekommt jetzt CSV-Werte. Label je Gruppe
lesbar formatieren: „🛫 ab EDDW, EDWG". Sonst unverändert (eine Multi-Platz-Zeile ist eine Gruppe).

## Snapshot-Freeze

`_PROGRESS_SNAPSHOT_VERSION` „2"→**„3"** — `departure`-Semantik (jetzt Liste) ändert den Payload.
Alte Snapshots werden neu gerechnet (Versions-Gate).

## Migration (Alt-Events v8.13.0)

**Nutzer-Fakt 2026-07-07: alle bestehenden Events haben genau EINEN Start und EIN Ziel.** Damit ist
die Migration eindeutig — Alt-Events werden **aktiv ins neue Modell überführt** (einmaliger Backfill
in `init_db`, Muster wie bestehende Backfills, try/except):

- Cargo mit **NULL/leerem** `departure` → wird auf **die Startplätze des Events** gesetzt, d. h.
  `_normalize_icao_list(route DES EVENTS ohne destination)`. Bei einem Ein-Start-Event ist das genau
  der eine Startplatz. Danach hat die Zeile ein explizites `departure` — kein NULL mehr.
- Cargo mit **einzelner** `departure` → unverändert (einelementige Liste).
- `transport_events.route` von Alt-Events bleibt gespeichert (und stimmt nach dem Backfill exakt mit
  `_derive_route` überein).

**Folge:** Alt-Events sind danach **vollständig neues Modell** — im Editor sichtbar/editierbar, und
ein Admin-Edit leitet die Route korrekt aus den (jetzt expliziten) Startplätzen ab. Die fragile
„Route beim Bearbeiten erhalten"-Sonderlogik entfällt für den manuellen Pfad. Der `_derive_route`-
NULL-Zweig bleibt nur noch als **Sicherheitsnetz** für den Kalender-`Fracht:`-Pfad (der weiter NULL
erzeugen darf), greift bei echten (migrierten) Events aber nicht mehr.

## Non-Goals

- Reine Ausweichplätze (Zeile ohne Ware) — YAGNI.
- Manifestlose Events (reiner kg-Zähler) — bewusst entfernt.
- **Bummel** — behält sein eigenes `route`-Feld, unberührt.
- **#77 ICAO-Validierung** und **#78 Frachtart-Picker** — eigene Tasks danach.

## Betroffene Dateien

- `app/database.py` — `_fillable` (Liste), neuer `_derive_route` + `_normalize_icao_list`,
  `create_transport_event`/`update_transport_event` (Route ableiten statt entgegennehmen,
  Pflicht-Validierung, partielles Update liest Manifest), `set_transport_cargo` (departure als Liste
  normalisieren; `== destination` verwerfen; stiller NULL-Fallback nur noch für Kalender),
  `_resolve_cargo_against_catalog` (Liste durchreichen), `upsert_calendar_transport_event` (Route
  inkl. gefilterter Marker-Plätze, Ziel-Default ohne Marker), `_default_destination`-Nutzung im
  manuellen Pfad entfernen, `_UPDATABLE_TRANSPORT_FIELDS` ohne `route`, `_PROGRESS_SNAPSHOT_VERSION`
  „3", Migration.
- `app/calendar_sync.py` — `_CARGO_MARKER_RE` (ICAO-Liste), `parse_cargo_lines`, `parse_route`
  (Basis-Route ohne Marker für Plausibilität; Marker einzeln distanz-gefiltert beitragen).
- `app/main.py` — `admin_update_transport_event`/Create: keine `route` mehr entgegennehmen; Ziel +
  Manifest-Pflicht (400).
- `app/static/admin.html` — Strecke-Feld raus, Start-Feld multi-ICAO, Save ohne Route, Ziel Pflicht.
- `app/static/index.html` — Balken-Gruppenlabel für CSV-departure lesbar.
- Docs (README, api.md, architecture.md) + CHANGELOG (Minor, kein highlight) + Tag.

## Tests (TDD)

- `_normalize_icao_list`: `"eddw, edwg"` → `"EDDW,EDWG"` (sortiert, dedup); `"EDDW/EDWG"` sauber
  behandelt (nicht an „/" verstümmelt); leer → None.
- `_derive_route`: Vereinigung Cargo-Plätze + Ziel, **stabil sortiert**; Ziel==Startplatz verworfen;
  bei vorhandener NULL-Zeile bleibt die bestehende Route erhalten.
- `_fillable` bei Multi-Platz-Zeile: füllbar von jedem gelisteten Platz, nicht von anderen;
  Latch-Fallback unverändert.
- **Pflicht:** Create/Update ohne Ziel → 400; ohne Cargo/ohne gültigen Startplatz → 400; leere
  Start-Liste → 400 (kein stiller NULL).
- **Migration (Backfill):** Alt-Event mit NULL-Cargo + Route „EDWG,EDXH" (Ziel EDXH) → nach Backfill
  hat die Cargo-Zeile `departure = "EDWG"`; `_derive_route` liefert wieder „EDWG,EDXH"; eine reine
  Name-/Ziel-Änderung lässt die Route intakt (kein Kollaps auf `{Ziel}`).
- **Freeze-Stabilität:** zwei aufeinanderfolgende Kalender-Syncs erzeugen denselben Routen-String →
  Snapshot bleibt (kein Churn).
- **Kalender:** `Fracht EDDW, EDWG: …` bindet an beide; Marker-Plätze landen in der Route; ein
  ferner/unbekannter Marker-ICAO wird verworfen, degradiert nur seine Zeile, kippt das Event nicht
  (`is_transport` bleibt True); Ziel-Default ignoriert Marker-Plätze.
- Aggregat-Invariante `total_kg` unverändert; Snapshot-Bump verwirft Alt-Snapshot.

## Offene Entscheidungen — geklärt

1. **Manifest Pflicht** (Nutzer 2026-07-07) → manifestlose Events entfallen, Route nie nur `{Ziel}`.
2. **Ziel Pflicht** (Nutzer 2026-07-07) → `_default_destination`-Zirkularität aufgelöst.
3. **Route abgeleitet, Spalte behalten; delimited String; Kalender-Distanzfilter im selben Task** —
   nach Fable-Review festgelegt.
4. **Alt-Events aktiv migrieren** (statt „Route beim Edit erhalten") — möglich, weil alle Alt-Events
   genau einen Start + ein Ziel haben (Nutzer 2026-07-07); NULL-Cargo → Startplatz des Events.

## Stehende Regeln

- Version + Git-Tag; **kein** highlight (Feature). CHANGELOG mit deutschen „…"-Anführungszeichen.
- README + api.md + architecture.md mitpflegen; kein PR/Branch, direkt auf main, vor Push bestätigen.
- Kutter & Bummel symmetrisch (hier nur Kutter). Mobil-Scrollregeln beachten.
