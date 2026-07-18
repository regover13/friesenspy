# FriesenKutter — Fracht-Zustandsmaschine geradeziehen (Bug X + Y)

**Status:** Design (2026-07-07). Sub-Projekt A von #15. Sub-Projekt B („mehrere Ziele",
gemeinsamer Topf) baut darauf auf und bekommt einen eigenen Spec/Plan-Zyklus.

## Ziel

Zwei Fehler in der Fracht-Zustandsmaschine des FriesenKutter beheben, sodass die Regeln
„Lieferung / Rückgabe / Verlust / unterwegs" dem gedachten Modell entsprechen — als sauberes
Fundament, bevor „mehrere Ziele" die Regeln verallgemeinert.

## Context — heutiges Modell (unverändert gültig)

- Ein Transport-Event hat **eine** `route` (CSV der Strecken-Wegpunkte) und **ein** `destination`
  (Ziel-ICAO, muss selbst in `route` liegen; ohne Angabe = letzter Streckenplatz).
- Fracht wird am Startplatz **verladen**, am Ziel **entladen/geliefert** (dort zählt sie).
- Ein Flug ist `loaded` (liefert), wenn er per GPS am `destination` landet **oder** ein
  Live-Ankunfts-Latch (`transport_live_arrivals`) existiert.
- Das Fracht-Manifest (`transport_cargo`) ist **ein gemeinsamer Topf**; die Zuteilung wird bei
  **jedem Poll live** gerechnet, nach **Abflugreihenfolge**, in zwei getrennten Töpfen:
  `delivered` (belegt Manifest-Plätze zuerst, von vorne) und `reserved` (offene Flüge Richtung
  Ziel, bekommen nur den Rest).
- Endgültige Zuteilung = Abflugreihenfolge; die reservierte Vorschau ist volatil (verschiebt
  sich, wenn vorne jemand liefert, ausloggt oder verloren geht). Das ist **gewollt** und bleibt.

## Bug X — Rückgabe nur am Abflugplatz (zu eng)

### Symptom

Loggt ein Pilot mit Fracht Richtung Ziel an einem **Strecken-Wegpunkt aus, der nicht der
Abflugplatz ist** (z. B. EDWG bei Strecke EDDW–EDWG–EDWY, Ziel EDWY), wird das heute als
**`stolen` (geklaut)** gewertet — obwohl der Kutter sicher an einem Netz-Wegpunkt steht. Fachlich
müsste das **`returned` (zurückgegeben, kg-neutral)** sein.

### Root Cause

`detect_transport_losses` (`app/database.py`) klassifiziert die letzte Position vor dem
Verbindungsende:

```python
if end_icao == dep:
    kind = "returned"
elif end_icao == dest:
    continue           # geliefert
elif end_icao:
    kind = "stolen"
```

`returned` ist an den **Abflugplatz** (`dep`) gebunden, nicht an die Streckenmenge.

### Fix

`route_set` ist in `detect_transport_losses` bereits berechnet. Klassifikation umstellen:

```python
if end_icao == dest:
    continue           # geliefert (kein Verlust)
elif end_icao in route_set:   # JEDER Strecken-Wegpunkt (inkl. dep) = zurückgegeben
    kind = "returned"
elif end_icao:
    kind = "stolen"    # Platz außerhalb der Strecke
# sonst (kein Platz in Reichweite / in der Luft) bleibt kind = "sunk"
```

Neue Wahrheitstabelle:

| Endposition (letzte, am Boden, vor Verbindungsende) | `kind` |
|---|---|
| am Ziel (`dest`) | — (geliefert, kein Verlust) |
| an einem Strecken-Wegpunkt (`route_set`, inkl. `dep`, ≠ `dest`) | `returned` (kg-neutral) |
| an einem Platz außerhalb der Strecke | `stolen` |
| kein Platz in Reichweite / in der Luft verschwunden | `sunk` |

`dep` bleibt korrekt `returned` (ist Teil von `route_set`; der frühere `dep`-Sonderfall wird
davon abgedeckt). `returned` ist wie bisher kg-neutral (kein Verlust in der Bilanz), die Fracht
steht dem Topf durch den Wegfall des aktiven Flugs ohnehin wieder zur Verfügung.

## Bug Y — Zwischenlandung erzeugt Phantom-Leerflug

### Symptom

Ein durchgehender Flug mit **Zwischenlandung an einem Wegpunkt** (kein Logout), z. B.
EDDW→EDWG→EDWY, wird von der GPS-Erkennung in zwei Legs geschnitten. Das Leg EDDW→EDWG
erscheint heute als **eigener 0-kg-„Leerflug"** im Feed, und der noch verbundene, am Wegpunkt
geparkte Pilot wird als **„am Start"** angezeigt — obwohl er mitten auf der Reise ist. Es müsste
**eine** Reise „unterwegs" bis EDWY sein.

### Root Cause

`compute_transport_progress` (`app/database.py`) stellt den Feed aus zwei Quellen zusammen:
- geschlossene Legs aus `canonicalize_legs` (jedes Zwischenlande-Leg ist eine eigene Zeile;
  nicht am Ziel gelandet → `loaded=False`, 0 kg),
- offene Verbindungen aus `open_transport_flights` (Reservierung; ein am Wegpunkt geparkter
  Pilot hat `airborne=False`, was das Frontend als „am Start" rendert — `#62`).

Beide beziehen sich auf **dieselbe** offene Verbindung (gleicher `_conn_logon`), erscheinen aber
als getrennte Zeilen.

### Fix — reiner Anzeige-Filter (Fracht-Mathematik unberührt)

Der Eingriff erfolgt in `compute_transport_progress`, **nach** dem Anheften der Verluste
(loss-attach) und **vor** `network.sort(...)` / der Manifest-Füllung. Weil die zu unterdrückenden
Zeilen `loaded=False` sind (0 kg → kein Beitrag zu `delivered`) und geschlossen sind (kein
`onboard_reserved_kg` → kein Beitrag zu `reserved`), ändert das Entfernen aus `network` **weder
`delivered[]` noch `reserved_alloc[]`** — die ausgewiesene Gesamt-Tonnage (`total_kg`) und alle
Fortschritts-/Verlustzahlen bleiben identisch. Das ist eine Invariante und wird getestet.

**Y1 — Phantom-Zwischen-Legs unterdrücken.** Eine geschlossene Feed-Zeile wird entfernt, wenn
alle gelten:
- `loaded` ist False, **und**
- sie trägt **kein** `loss_kind` (ist nicht der Verlust-Träger ihrer Verbindung), **und**
- `dep` ≠ `destination` — ein Leg, das **am Ziel gestartet** ist, ist ein leerer **Rückflug**
  (0 kg) und bleibt **immer** sichtbar (Nutzer-Definition 2026-07-07), **und**
- dieselbe Verbindung (`_conn_logon`) ist im Feed bereits durch eine **behaltene** Zeile
  vertreten — entweder eine **Lieferung** (`loaded=True`) derselben Verbindung **oder** eine
  **offene Reservierung** derselben Verbindung (noch verbunden).

Damit bleibt pro Verbindung genau die *eine* aussagekräftige Zeile plus jeder echte Rückflug:
Lieferung, offene Reise, Verlust — und ein Rückflug (`dep == dest`) als eigene 0-kg-Zeile.

**Rückflug bleibt sichtbar — auch im selben Connection-Umlauf.** Liefert ein Pilot EDDW→EDWY und
fliegt **ohne Logout** zurück (EDWY→EDDW in derselben Verbindung), so trägt das Rückflug-Leg
zwar eine behaltene Geschwister-Zeile (die Lieferung), wird aber wegen `dep == dest` **nicht**
unterdrückt. Ebenso bleibt ein eigenständiger Rückflug (eigene Verbindung, keine Reservierung,
keine Lieferung) sichtbar.

**Y2 — „am Start" → „unterwegs".** Ein an einem Wegpunkt geparkter Pilot, dessen offene
Verbindung **schon mindestens ein Strecken-Leg abgeschlossen** hat (erkennbar an einem
unterdrückten Zwischen-Leg desselben `_conn_logon`), wird als **„unterwegs"** dargestellt, nie
als „am Start". Anzeige ohne Stopp-Detail (Nutzer-Entscheidung 2026-07-07): schlicht
„unterwegs", **kein** „Stopp EDWG".

### Verifikation am Referenz-Szenario

Strecke EDDW–EDWG–EDWY, Ziel EDWY. Abflug 1→2→3. Manifest Äpfel→Birnen→Bananen→Nüsse.
Nr. 2 airborne direkt Richtung EDWY; Nr. 1 und Nr. 3 mit Zwischenstopp EDWG (eingeloggt):

- **Nr. 2:** eine Zeile „unterwegs", 3 Birnen.
- **Nr. 1:** eine Zeile „unterwegs", 2 Äpfel + 1 Birne — **kein** Phantom-Leerflug EDDW→EDWG.
- **Nr. 3:** eine Zeile „unterwegs", 3 Bananen — **kein** Phantom-Leerflug.
- Fracht-Zuteilung unverändert korrekt (Abflugreihenfolge, `total_kg` gleich).

Loggt Nr. 1 in EDWG aus (Bug X): `returned`, 2 Äpfel + 1 Birne zurück in den Topf; beim nächsten
Live-Takt rutschen Nr. 2/3/4 eine Sorte nach vorne (2 Äpfel+1 Birne / 3 Birnen / 3 Bananen).

## Non-Goals (bewusst ausgeschlossen)

- **Mehrere Ziele** (gemeinsamer Topf, Stufe 1) — Sub-Projekt B, eigener Spec.
- **Feste Frachtzuteilung** (Stufe 2/3: Fracht/Ziel bzw. Fracht/Ziel/Pilot), gegen das
  Live-Verschieben der Sorte — spätere Stufe.
- **Bidirektionale Zählung** (Rückflug lädt auch) — vom Nutzer als zweitrangig zurückgestellt.
- Änderungen an Manifest-Füllung, Reservierungs- oder Verlust-**Bilanz** (nur Klassifikation X +
  Anzeige Y).

## Betroffene Dateien

- `app/database.py` — `detect_transport_losses` (Bug X), `compute_transport_progress`
  (Bug Y, Anzeige-Filter + Unterwegs-Kennzeichnung).
- `app/static/index.html` — nur falls die „unterwegs"-Kennzeichnung ein Frontend-Feld braucht
  (abhängig davon, ob Y2 ein bestehendes Feld wiederverwendet oder ein neues setzt).
- Tests: `tests/test_database.py` (bzw. bestehende Kutter-Testdatei).
- Docs: `docs/architecture.md`, `docs/api.md` (falls Feld-/Verhaltensänderung), `README.md`,
  `app/CHANGELOG.json` + Git-Tag (Patch/Minor — Bugfix, **kein** highlight).

## Tests (TDD)

**Bug X** (`detect_transport_losses`):
- `returned` bei Logout an einem Wegpunkt ≠ Abflugplatz (EDWG): war `stolen`, ist jetzt
  `returned`.
- `returned` am Abflugplatz bleibt `returned` (Regression).
- `stolen` an einem Platz außerhalb der Strecke bleibt `stolen`.
- `sunk` bei Verschwinden in der Luft bleibt `sunk`.
- Landung am Ziel bleibt Lieferung (kein Loss).

**Bug Y** (`compute_transport_progress`):
- Zwischenlandung an Wegpunkt (Verbindung offen): **kein** Phantom-Leerflug im Feed; Pilot
  genau **eine** „unterwegs"-Zeile mit reservierter Ladung; als „unterwegs", nicht „am Start".
- Durchgehende Lieferung mit Zwischenstopp (EDDW→EDWG→EDWY, gelandet): nur die Lieferzeile,
  kein Zwischen-Leg.
- **Invariante:** `total_kg` / `delivered` / Verlustzahlen sind vor und nach dem Filter
  identisch (Anzeige-only).
- Eigenständiger Rückflug (keine Geschwister-Zeile) bleibt sichtbar (kein versehentliches
  Ausblenden).
- Rückflug im selben Umlauf: Lieferung EDDW→EDWY + Rückflug EDWY→EDDW ohne Logout — die
  Rückflug-Zeile (`dep == dest`) bleibt trotz behaltener Lieferungs-Geschwisterzeile sichtbar.
- Verlust-Träger-Zeile einer geschlossenen Verbindung wird nicht unterdrückt.

## Stehende Regeln (Projekt)

- Version erhöhen (`app/CHANGELOG.json` oben) + Git-Tag `vX.Y.Z`; **kein** highlight (Bugfix).
  CHANGELOG mit deutschen „…"-Anführungszeichen.
- README + `docs/api.md` + `docs/architecture.md` mitpflegen.
- Kein PR/Branch — direkt auf `main`, vor `git push origin main` kurz bestätigen lassen.
- Kutter & Bummel symmetrisch behandeln (hier nur Kutter betroffen, kein Framing-Problem).
