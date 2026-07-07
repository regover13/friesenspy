# FriesenKutter — Fracht je Startplatz (Sub-Projekt B, Option A)

**Status:** Design (2026-07-07). Sub-Projekt B von #15. Baut auf Sub-Projekt A (v8.12.1,
Fracht-Zustandsmaschine Bug X + Y) auf.

## Ziel

Ein FriesenKutter-Event soll **verschiedene Waren je Startplatz** transportieren können: wer in
EDDW startet, lädt z. B. Äpfel; wer in EDWG startet, lädt Birnen — alle liefern zum **einen**
Ziel. Die Frachtart eines Flugs steht dann durch den **Startort** fest, nicht mehr durch die
Abflugreihenfolge im gemeinsamen Topf.

**Option A (gewählt):** Jeder Startplatz hat ein **eigenes Manifest** (kann mehrere Frachtarten
mit Mengen enthalten, wie das heutige Manifest — nur pro Startplatz). A ist ein Superset von „genau
eine Ware je Startplatz" und nutzt die bestehende Co-Load-Verteilung je Startplatz weiter, kostet
also kaum mehr als die einfachere Variante.

## Context — heutiges Modell

- Ein Event hat **ein** `destination` (Ziel-ICAO) und eine `route` (CSV der Wegpunkte).
- `transport_cargo` ist **ein** flaches Manifest je Event (Zeilen mit `position`, `name`,
  `target_kg`, `emoji`, `per_flight_max_kg`).
- `compute_transport_progress` füllt dieses eine Manifest nach **Abflugreihenfolge** per Co-Load:
  jeder beladene Flug verteilt seine Zuladung in Manifest-Reihenfolge über die noch nicht vollen
  Frachtarten (Kappung je Flug via `per_flight_max_kg`, Rest in die nächste Art). Delivered/
  reserved sind pro Frachtart-Position geführte Arrays. Die Frachtart eines Flugs hängt NICHT vom
  Startort ab.

## Kernänderung — Fracht an den Startplatz binden

### Datenmodell

`transport_cargo` bekommt eine neue **nullable** Spalte `departure TEXT` (Startplatz-ICAO,
normalisiert). Migration über `_TRANSPORT_MIGRATIONS` (`ALTER TABLE transport_cargo ADD COLUMN
departure TEXT` — SQLite-sicher, Default NULL).

**NULL-Semantik (rückwärtskompatibel):**
- `departure IS NULL` = **geteilt** (Legacy): die Frachtart steht Flügen von JEDEM Startplatz zur
  Verfügung — exakt das heutige Verhalten.
- `departure = 'EDDW'` = an diesen Startplatz **gebunden**: nur Flüge, die in EDDW starten, laden
  diese Frachtart.

`get_transport_cargo`/`set_transport_cargo` tragen `departure` mit (Zeilen ohne → NULL).

### Fracht-Zuordnung (`compute_transport_progress`)

Die Manifest-Füllung bleibt Co-Load, wird aber **je Flug auf die zu seinem Startplatz passenden
Frachtart-Zeilen beschränkt**. Für einen Flug mit GPS-Startplatz `X` (`dep` aus
`canonicalize_legs`) sind die füllbaren Zeilen:

> `departure IS NULL` **ODER** `departure == X`

in `position`-Reihenfolge; die Co-Load-Kappung/-Verteilung läuft nur über diese Teilmenge (Rest
fließt in die nächste **passende** Zeile). `delivered[]`/`reserved_alloc[]` bleiben global (je
`position` indiziert) — der einzige Unterschied ist, dass die Füllschleife eines Flugs nicht
passende Zeilen **überspringt** statt sie zu füllen. Die Indizes verschiedener Startplätze sind
disjunkt (gebundene Zeilen werden nur von Flügen ihres Startplatzes beschrieben) → keine
Interferenz über die globalen Arrays; die Netto-Invariante (#63, `total_kg == Σ delivered`) bleibt.

**Fallback bei unbekanntem/streckenfremdem Startplatz (KRITISCH — Latch-Fall):** Ein
Live-Ankunfts-Latch hebt den Strecken-Filter auf (`compute_transport_progress`, ~Zeile 4978) — ein
**geladener** Flug (`loaded=True`) kann dann einen `dep` haben, der **leer** ist (Airborne-Spawn
ohne GPS-Startpunkt, trackless/StatSim via `_flightrow_as_flight`) oder **außerhalb der Route**
liegt. Ohne Sonderregel matcht so ein Flug nur NULL-Zeilen → bei einem rein startplatz-gebundenen
Manifest liefert eine **echte, gelatchte Ankunft still 0 kg** (genau der Fall, für den der Latch
gebaut wurde). **Regel:** Ist bei `loaded=True` der `dep` leer **oder** nicht in `route_set`
(kein verwertbarer Startplatz), füllt der Flug **alle** Manifest-Zeilen (Degradation auf das
heutige Gesamt-Topf-Verhalten) — nie stille 0 kg. Nur Flüge mit gültigem Route-Startplatz werden
auf ihre Startplatz-Teilmenge beschränkt. Für offene Flüge/Reservierungen und Verluste ist `dep`
stets in `route_set` (Offen-Zweig/`detect_transport_losses` verlangen das) — dort greift der
Fallback nie.

Konsequenzen (gewollt):
- Legacy-Event (alle Zeilen NULL): jeder Flug füllt alle Zeilen → **unverändert** gemeinsamer
  Topf.
- Reines Startplatz-Event: ein Flug aus EDDW füllt nur EDDWs Zeilen (+ evtl. geteilte NULL-Zeilen);
  ein Flug aus EDWG füllt nur EDWGs Zeilen. Kein Verschieben der Sorte zwischen Startplätzen.
- Startplatz ohne eigenes Manifest (und ohne NULL-Zeilen): Flug lädt nichts → 0-kg-Flug im Feed.

Reservierung, Verlust (`stolen`/`sunk`) und Rückgabe (`returned`) tragen die Zuordnung
automatisch mit: sie nutzen dieselbe Co-Load-Füllung über die startplatz-gefilterte Teilmenge,
also reserviert ein Flug in **sein** Startplatz-Manifest, und eine Rückgabe/ein Verlust gibt genau
diese Zeilen wieder frei.

### Fortschritt / Anzeige

- Der `cargo`-Response trägt je Frachtart zusätzlich `departure` (NULL = geteilt). `delivered_kg`/
  `reserved_kg` je Zeile bleiben wie heute (je `position`).
- **Frontend:** die Balken werden **nach Startplatz gruppiert** (ein Block je Startplatz mit dessen
  Frachtarten; geteilte NULL-Zeilen in einem eigenen „alle Startplätze"-Block). Der Gesamt-
  Fortschritt (`total_kg`/`target_kg`) bleibt die Summe über alle Zeilen — unverändert aggregiert,
  nur feiner dargestellt. Gilt für Live-Tab-Block UND Events-Ansicht (CLAUDE.md-Mobilregel:
  scrollbare Tabellen bleiben scrollbar).

### Kalender-Syntax

`parse_cargo_lines` wird erweitert, um einen **optionalen Startplatz** je Fracht-Zeile zu erkennen:

- Bisher (bleibt gültig, = geteilt/NULL): `Fracht: 1000 Krabbenbrötchen, 500 Friesentee`
- Neu (je Startplatz, je eigene Zeile): `Fracht EDDW: 500 Äpfel, 200 Nüsse` und `Fracht EDWG: 300
  Birnen`

Ein `Fracht <ICAO>:`-Marker bindet alle Frachtarten dieser Zeile an `<ICAO>`; ein reines
`Fracht:` bleibt geteilt (NULL). Mehrere Marker in einer Beschreibung werden alle gelesen.
Rückgabe von `parse_cargo_lines`: Liste von `{name, target_kg, departure?}`.

**Umbau (größer als „nur erweitern"):**
- `_CARGO_MARKER_RE` (`app/calendar_sync.py:44`, heute `fracht\s*:`) muss den optionalen ICAO
  aufnehmen (`fracht(?:\s+([A-Z]{4}))?\s*:`) und `search()` → `finditer()` werden (mehrere Marker,
  je Marker die erste Folgezeile). Die „nur erste Zeile"-Logik gilt dann **pro Marker**.
- **Routen-Kontamination (KRITISCH):** `parse_route` (`app/calendar_sync.py:93–97`) sammelt JEDES
  4-Großbuchstaben-Wort aus der Beschreibung in die `route`-CSV. Ein `Fracht EDXX:`-Marker landet
  damit **selbst in der Route** — die geplante Validierung „Startort muss in der Route liegen" wäre
  dann trivially wahr (**zahnlos**), und ein weit entfernter Tippfehler-ICAO kann `_route_is_plausible`
  (`:28`) kippen und **das ganze Event als Nicht-Kutter deaktivieren** (`:99–101`). **Fix:** die
  `Fracht <ICAO>:`-Marker-Zeilen VOR der Routen-Sammlung maskieren (oder die Marker-ICAOs explizit
  aus der Sammlung ausschließen), und die Startort-Validierung gegen die so **bereinigte** Route
  laufen lassen. Ein streckenfremder Fracht-Startort wird verworfen (Zeile ignoriert), nicht als
  totes Manifest angelegt — Prüfung in `upsert_calendar_transport_event` (`:3982`).

### Admin-UI + Validierung (auch Backend)

Der Manifest-Editor (`app/static/admin.html`) bekommt je Fracht-Zeile ein **Startplatz-Feld**
(Dropdown/Freitext-ICAO, leer = geteilt). Zeilen werden nach Startplatz gruppiert dargestellt.
`per_flight_max_kg` bleibt sichtbar (v8.6.x). Keine neue Endpoint-Signatur nötig — das bestehende
Cargo-Array trägt einfach `departure` je Zeile.

**Validierung nicht nur beim Kalender-Speichern, sondern auch auf dem Admin-Pfad**
(`set_transport_cargo` → `create_transport_event` `:4065`, `admin_update_transport_event`
`app/main.py:2004`), sonst kommt ungeprüfter Freitext durch:
- `departure` je Zeile `normalize_type_code`-normalisieren (Freitext „eddw " → `EDDW`).
- Startort muss in der (bereinigten) `route` liegen — sonst NULL (geteilt) oder Ablehnung.
- **`departure == destination` ablehnen:** ein am Ziel startender Flug ist per `dep == dest`-
  Rückflug-Filter (`:5073`) NIE füllbar — eine solche Zeile wäre tot und blockiert `goal_reached_at`
  für immer (`poller.py`), das Event würde nie „voll".
- **Routen-Änderung nach Manifest-Anlage:** entfernt der Admin später einen Startplatz aus der
  Route, bleiben dessen gebundene Zeilen als tote Last stehen (Ziel nie erreichbar). Admin-UI warnt
  beim Speichern, wenn gebundene Startplätze nicht (mehr) in der Route sind.

### Freeze / KPIs / Badge

- **Snapshot-Freeze (#66) — Version-Bump nötig (Projektkonvention `database.py:3856`):** der
  `cargo`-Payload bekommt das neue Feld `departure` → Formatänderung. `_PROGRESS_SNAPSHOT_VERSION`
  wird von „1" auf „2" erhöht, damit alte eingefrorene Snapshots (ohne `departure`) nicht ans neue,
  gruppierende Frontend geliefert werden — `get_progress_snapshot` filtert nach `code_version`
  (`:5803`), der Lazy-Recompute im Endpoint (`main.py:~1791`, auch nach `dtend` korrekt via
  `skip_open_probe`) baut sie neu. Die Invalidierung bei Manifest-/Startplatz-Änderung greift wie
  gehabt (Admin-Save löscht den Snapshot `main.py:2027`; Kalender-Sync gezielt `database.py:4021`).
- **KPIs (#64)** und **Badge (#18)** rechnen auf `total_kg`/`delivered`/`losses` (Aggregat) — die
  bleiben summenidentisch, also keine Logikänderung; höchstens optionale Startplatz-Aufschlüsselung
  später (Non-Goal hier). **`goal_reached`-Push** feuert erst, wenn ALLE Startplatz-Manifeste voll
  sind (Aggregat-Semantik — bewusst so, wird getestet).

## Rückwärtskompatibilität

- Migration setzt `departure = NULL` für alle Bestandszeilen → alle bestehenden Events verhalten
  sich **exakt wie heute** (gemeinsamer Topf).
- Kein Bruch an `set_transport_cargo`/`get_transport_cargo` (neues Feld optional).

## Non-Goals

- **Mehrere Ziele** (die ursprünglich diskutierte Richtung) — verworfen zugunsten dieses Ansatzes.
- **Stufe 3** (Fracht/Startplatz/**Pilot** — an eine vorab definierte CID gebunden) — spätere,
  optionale Ausbaustufe.
- **Bidirektionale Zählung** (Rückflug lädt auch) — weiterhin zweitrangig zurückgestellt.
- Startplatz-Aufschlüsselung in Badge/KPIs — Aggregat bleibt, feinere Aufschlüsselung später.

## Betroffene Dateien

- `app/database.py` — Migration (`_TRANSPORT_MIGRATIONS`), `get/set_transport_cargo`
  (inkl. `departure`-Normalisierung + Validierung), `_resolve_cargo_against_catalog` (Startort
  durchreichen), `compute_transport_progress` (startplatz-gefilterte Co-Load + Latch-Fallback in
  Liefer- UND Reservierungs-/Verlust-Füllung), `upsert_calendar_transport_event` (Startort-
  Validierung gegen bereinigte `route`), `create_transport_event` (Admin-Validierung),
  **`_PROGRESS_SNAPSHOT_VERSION` „1"→„2"** (`:3858`).
- `app/calendar_sync.py` — `parse_cargo_lines` + `_CARGO_MARKER_RE` (Regex-Umbau, `finditer`),
  `parse_route` (Fracht-Marker-ICAOs von der Routen-Sammlung ausschließen).
- `app/main.py` — `admin_update_transport_event` (`:2004`, `departure`-Validierung; Snapshot-
  Invalidierung besteht bereits `:2027`).
- `app/static/admin.html` — Manifest-Editor mit Startplatz-Feld + Gruppierung + Warnung bei
  streckenfremdem gebundenem Startplatz.
- `app/static/index.html` — Fortschrittsbalken nach Startplatz gruppiert (Live-Tab + Events).
- Docs: `README.md`, `docs/api.md` (cargo-Feld `departure`, Kalender-Syntax), `docs/architecture.md`
  (Co-Load je Startplatz), `app/CHANGELOG.json` + Git-Tag (Minor — neues Feature, **kein**
  highlight).

## Tests (TDD)

- **Datenmodell:** `set/get_transport_cargo` roundtrip mit `departure`; Migration lässt
  Bestandszeilen NULL.
- **Co-Load je Startplatz:** ein Flug aus EDDW füllt nur EDDW-Zeilen; ein Flug aus EDWG nur
  EDWG-Zeilen; keine Sorte wandert zwischen Startplätzen. Co-Load-Spill nur in die nächste
  passende (gleicher Startplatz) Frachtart.
- **Geteilt (NULL):** Legacy-Event (alle NULL) verhält sich exakt wie heute (Regressionstest gegen
  bestehendes Verhalten). Gemischt (NULL + startplatz-gebunden): ein Flug füllt NULL + eigene
  Zeilen.
- **Reservierung/Verlust/Rückgabe** respektieren die Startplatz-Zuordnung (reserviert/verliert nur
  die eigenen Zeilen).
- **Startplatz ohne Manifest:** Flug lädt 0 kg (leerer Flug), kein Fehler.
- **Latch-Fallback (kritisch):** gelatchte Lieferung mit `dep=""`/streckenfremd bei rein
  gebundenem Manifest → füllt ALLE Zeilen (nicht still 0 kg).
- **`departure == destination`:** Zeile wird abgelehnt/nicht angelegt (tote Zeile, `goal_reached`
  nie erreichbar).
- **Kalender-Parsing:** `Fracht EDDW: …` bindet an EDDW; `Fracht: …` bleibt geteilt; mehrere
  `Fracht <ICAO>:`-Marker werden alle gelesen; Startort außer der `route` wird verworfen.
- **Routen-Kontamination:** ein Tippfehler-ICAO im `Fracht <ICAO>:`-Marker wandert NICHT in die
  Route und kippt via `_route_is_plausible` NICHT das Event (Integrationstest gegen `parse_route`).
- **Gemischtes Manifest, NULL-Zeile auf Position 0:** wird von allen Startplätzen in
  Abflugreihenfolge zuerst gefüllt (Konkurrenz — gewollt, aber belegt).
- **Verlust-Feed-Fallback-Zeile** (`loss_by_conn`, nicht im normalen Feed) mit gebundenem Manifest:
  Bordladungs-Aufschlüsselung nur aus den eigenen Zeilen.
- **Admin-Freitext:** `"eddw "` → `EDDW` (normalisiert), streckenfremd → abgelehnt/NULL.
- **Snapshot:** alter Snapshot ohne `departure` wird durch den Version-Bump verworfen; der
  Lazy-Recompute liefert identische Aggregatwerte.
- **`goal_reached` erst bei ALLEN vollen Startplatz-Manifesten** (Aggregat-Semantik bestätigen).
- **Aggregat-Invariante:** `total_kg`/`target_kg` = Summe über alle Zeilen (unverändert).
- **Legacy-Regression:** Event mit ausschließlich NULL-Zeilen verhält sich exakt wie vor dem Feature.

## Bereits entschieden (nach Fable-5-Review eingearbeitet)

- **Latch-Fallback:** geladener Flug ohne verwertbaren `dep` (leer/streckenfremd) füllt ALLE
  Zeilen (nie stille 0 kg). *(war die wichtigste ungestellte Frage — jetzt geklärt)*
- **`_PROGRESS_SNAPSHOT_VERSION` „1"→„2"** (Formatänderung `cargo`-Payload, Projektkonvention).
- **Admin-Validierung** von `departure` (Normalisierung, Route-Prüfung, `== destination` ablehnen).
- **Kalender-Marker-ICAOs** aus der Routen-Sammlung ausschließen (sonst zahnlose Validierung /
  Event-Deaktivierung).

## Offene Entscheidungen — zur Freigabe im Spec-Review

1. **Kalender-Syntax:** `Fracht EDDW: 500 Äpfel` (Startort direkt am Marker) — Fable bestätigt
   das als tragfähig; das Alternativformat (`Fracht: EDDW 500 Äpfel; …`) bräuchte einen zweiten
   Parser und kollidiert mit dem „führende Zahl"-Regex. **Empfehlung: `Fracht <ICAO>:`.** Passt?
2. **Anzeige:** Fortschritt als **ein Block je Startplatz** (Startplatz-Überschrift + dessen
   Frachtart-Balken). Reicht das, oder willst du zusätzlich einen Gesamt-Balken „alle Startplätze
   zusammen" darüber?
3. **Gemischt erlaubt?** Ein Event darf geteilte (NULL) UND startplatz-gebundene Frachtarten
   mischen (Fill-Regel `NULL OR ==X`). **Empfehlung: erlauben** (strikt entweder-oder spart laut
   Review nichts, kostet nur Flexibilität). Einverstanden?
4. **Tote gebundene Zeilen** (Startplatz später aus der Route entfernt): Admin-UI **warnt**, blockt
   aber nicht. Reicht Warnen, oder soll das hart abgelehnt werden?

## Stehende Regeln (Projekt)

- Version erhöhen (`app/CHANGELOG.json` oben) + Git-Tag `vX.Y.Z`; **kein** highlight (Feature, kein
  Major). CHANGELOG mit deutschen „…"-Anführungszeichen.
- README + `docs/api.md` + `docs/architecture.md` mitpflegen.
- Kein PR/Branch — direkt auf `main`, vor `git push origin main` kurz bestätigen lassen.
- Kutter & Bummel symmetrisch behandeln (hier nur Kutter betroffen, kein Framing-Problem).
- Mobil-Scrollregeln für neue/gruppierte Tabellen einhalten (CLAUDE.md).
