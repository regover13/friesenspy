# FriesenKutter: Ladung als Bestand („Stapel-Modell") — Design

Datum: 2026-07-15 · Status: zur Umsetzung freigegeben · Scope: FriesenKutter (Bummel nicht betroffen)

Vorgänger: `2026-07-01-kutter-live-ankunft-design.md` (führte den Latch ein) und acht weitere
Kutter-Specs bis `2026-07-09-kutter-verlust-kern-design.md`. Diese Spec **ersetzt deren Kern-Mechanik**,
nicht ihre fachlichen Ziele.

Analyse und Messungen: Artifact „FriesenKutter — Ladung & Status" (2026-07-15).
Ist-Aufnahme des Status: Artifact „FriesenKutter — Statusführung" (2026-07-10).

## Context

Der Kutter entstand am **1. Juli**. Die GPS-only-Umstellung (v8.0.0, `canonicalize_legs` als einzige
Wahrheit) kam am **3./4. Juli**. Der Kutter kompensiert daher ein Problem, das drei Tage später an
der Wurzel gelöst wurde — die Begründung steht wörtlich im Code (`database.py:5423`):

> „Aktuell offene Flüge (noch verbunden) — bisher komplett ignoriert, da **canonicalize_flights**
> `logoff_time IS NOT NULL` verlangt."

`canonicalize_legs` verlangt das ausdrücklich **nicht** (`database.py:2539`) und erkennt die Landung
sofort am Touchdown. Der Ankunfts-Latch (`transport_live_arrivals`) beantwortet seither eine Frage,
die der Detektor selbst beantwortet.

**Gemessen (Produktionsbestand):** 22 von 23 Latches decken sich mit einer Landung, die der Detektor
ohnehin kennt — 14 davon auf die Sekunde genau (dasselbe `gs<2`-Sample). Gerettet hat der Latch
**0×**, falsch gelatcht **1×** (Z1: CID 1470798 galt am 12.07. um 11:40:10 als „in EDWG angekommen"
— vier Minuten *bevor* er losflog). Er wurde in neun Tagen fünfmal geflickt (#6, #22, #62/#65/#66,
v8.25.0, v8.25.1).

**Der eigentliche Fehler ist tiefer.** Das Modell kennt keine Ladung: Es rät die Fracht aus dem
Startplatz des **letzten Flugbeins** (`normalize_type_code(f.get("departure"))`, `database.py:5385`). Gemessen mit
echten Tracks (Manifest: Fischbrötchen 800 kg ab EDWG, Tee 500 kg ab EDWZ, Ziel EDXH, Zuladung 1000):

| Szenario | heute | richtig |
|---|---|---|
| EDWG → EDXH | 800 Fisch ✓ | 800 |
| EDWG → EDWZ → EDXH (**Milchmann**) | **0 Fisch**, 500 Tee | 800 Fisch + 200 Tee |
| EDWG → EDDW *(fremd)* → EDXH, ohne Latch | **0 kg** | 800 Fisch |
| dasselbe **mit** Latch (= echter Betrieb) | **1000 kg** (Tee war nie an Bord) | 800 Fisch |
| EDWG → EDWZ, Logout | `returned` → zurück in den **EDWG**-Topf | Ware liegt in EDWZ |

**Wer über einen fremden Platz zwischenlandet, bekommt 1000 kg. Wer regelkonform über den zweiten
Ladeplatz fliegt, bekommt 500.** Weniger Information ergibt mehr Fracht — das ist keine Zeile, die
falsch ist, sondern die Logik.

## Entscheidungen (bestätigt mit User, 2026-07-15)

1. **Ladung ist ein Bestand mit einem Ort**, kein Attribut eines Flugbeins.
2. **Die Landung lädt und liefert. Der Logout stiehlt, gibt zurück und versenkt.** Begründung des
   Nutzers: Wer ausloggt, beendet seine Tour — was dann an Bord ist, bleibt liegen, wo er ist.
   **Das gilt auch beim unfreiwilligen Verbindungsabbruch** („Ja. Ist halt so.", Nutzer 15.07.):
   Ein Netzausfall in der Luft ist im Track nicht von einem bewussten Ausstieg zu unterscheiden —
   wer die Verbindung verliert, verliert die Ladung. Bewusst anders als die Flugerkennung, die
   kurze Abbrüche gerade *nicht* bestraft (`gap_minutes = 30`, Distanz-Budget).
3. **Ein leerer Stapel ist immer noch ein Stapel.** Ein Ladeplatz bleibt Ladeplatz; der Stapel wird
   nie gelöscht, nur leer. Ein Stapel ist ein *Ort*, kein Inhalt.
4. **Am Boden wird geladen — an jedem Ladeplatz, ob erster oder dritter.** Beim Logout geht alles
   zurück in den Stapel des *aktuellen* Platzes, auch frisch Geladenes. Keine Sonderbehandlung.
5. **Wer zuerst kommt, lädt zuerst.** Der Zweite hat Pech und fliegt leer. Kein Teilen, keine Quote.
6. **Eine Manifest-Zeile = ein Stapel = genau ein Platz.** Das `departure`-Feld braucht eine
   **Plausibilitätsprüfung (genau ein ICAO)** und eine Beschreibung, die das sagt. CSV-Liste und
   „geteilter Topf" (`departure IS NULL`) entfallen.
7. **Die Ladereihenfolge ist die Manifest-Reihenfolge im Admin** (`position`), oben zuerst.
8. **Ohne GPS-Track keine Lieferung.** Bewusst akzeptiert (real nie eingetreten, 0 von 23).
9. **Abgeschlossene Events werden migriert, nicht eingefroren** — Belege unter „Migration".
10. **Das Event endet erst, wenn alle Ware einen End-Stapel gefunden hat** (geliefert, zurück,
    gestohlen, versenkt). Ein Pilotenstapel > 0 verhindert das Ende. Damit entfällt die
    Streckenprüfung im Feierabend-Kriterium — s. „Wann das Event endet".
11. **Musterwechsel:** am Boden wird umgeladen (Ladung fällt ab wie beim Logout, dann neu laden mit
    der neuen Kapazität); in der Luft wird er ignoriert.
12. **Verschwinden Positionen (365-Tage-Cleanup), verschwinden die Events desselben Zeitraums mit** —
    vollständig, aus allen Sichten. Kein Event überlebt seine Rohdaten. (Der Job ist heute
    deaktiviert; die Regel gilt für jede Reaktivierung.)

Unverändert (berechtigte Domänen-Komplexität): Zuladung je Muster (`aircraft_payloads`),
Pro-Flug-Kappung `per_flight_max_kg` (#63), Frachtart-Katalog, KI-Sprüche, Push, Badge,
GPS-only-Wahrheit (#23), „Target bleibt Maßstab".

## Architektur

### Der Bestand ist eine Ableitung, kein Speicher

**Keine neuen Tabellen.** `compute_transport_progress` rechnet heute schon bei jedem Aufruf
on-demand; die Stapel entstehen als Zwischenergebnis dieser Rechnung aus:

- **Manifest** (`transport_cargo`) → Anfangsbestand je Ladeplatz
- **Legs** (`canonicalize_legs`, im Event-Fenster) → Bewegungen
- **Zuladungen** (`aircraft_payloads`) → Kapazität je Flug

Das erfüllt zugleich die bestehende Anforderung *„Gewichtskorrekturen wirken live, nie
gesnapshottet"* (Spec 09.07.): Eine Korrektur ändert die nächste Rechnung, kein Backfill nötig.
Ein gespeicherter Bestand wäre ein Snapshot und würde ihr widersprechen.

```
stapel:    {ort: {frachtart: kg}}     # initial = Manifest; Ziel/gestohlen/versenkt sind auch Stapel
ladung:    {cid: {frachtart: kg}}     # bleibt an Bord über Zwischenlandungen
```

**Erhaltungssatz:** `Σ Stapel + Σ Ladung == Σ Manifest` — immer (mit Float-Toleranz; Zuladungen sind auf 0,1 kg gerundet, exakte Gleichheit ist nicht testbar). Ware entsteht nicht und verschwindet
nicht. Der Balken *kann* nicht lügen; #63 („Balken lügt nicht") wird von einer Zusicherung zu
Arithmetik. Dieser Satz ist als Test zu prüfen.

### Die Ereignisse

Der Flieger trägt selbst einen **Stapel** — einen, der eine Position hat (ein Platz oder
„unterwegs"). Ware wechselt nur zwischen Stapeln; sie entsteht und verschwindet nie.

Alle Ereignisse werden **chronologisch** in einer Reihe abgearbeitet — Landungen/Abflüge tragen die
GPS-Zeit des Detektors, Logins/Logouts die Session-Zeit aus `flights`. Beide sind UTC und damit
total geordnet. **Bei gleichem Zeitstempel gilt der Logout zuerst** (er beendet die Tour; eine
Landung im selben Moment kann nichts mehr abliefern).

**Laden ist ein Zustand, kein Ereignis:**

| Zustand / Ereignis | Wirkung |
|---|---|
| **Am Boden an einem Ladeplatz** | **lädt** — egal, wie er dorthin kam (gelandet *oder* gerade eingeloggt) |
| **Abflug** | lädt **nicht** — nur die Position des Flieger-Stapels wechselt auf *unterwegs* |
| **Landung am Ziel** | **liefern**: gesamter Flieger-Stapel → Ziel-Stapel, sofort (kein Disconnect nötig) |
| **Landung am fremden Platz** | nichts — Ladung bleibt an Bord |
| **Logout am Ladeplatz** | **zurück**: gesamter Flieger-Stapel → Stapel dieses Platzes |
| **Logout am fremden Platz** | **gestohlen** |
| **Logout in der Luft** | **versenkt** |
| **Logout am Ziel** | nichts — bei der Landung längst geliefert |

**Wer am Ladeplatz landet, lädt. Punkt.** Keine Absichtsprüfung, keine Ausstiegsbedingung. Fliegt er
danach beladen zu einem fremden Platz und loggt dort aus, ist das **Diebstahl** — er nimmt die Ware
ja mit nach Hause. Ein Sonderfall wäre eine Heuristik, und Heuristiken sind genau das, was hier
abgebaut wird.

*Das ist kein neues Verhalten:* Schon heute reserviert ein am Ladeplatz **geparkter** Pilot seine
volle Zuladung, ohne je abgehoben zu sein (Boden-Beladung #5/v8.25; Beleg:
`test_open_flight_on_ground_is_not_airborne`, `tests/test_transport.py:1031` — `reserved_kg == 292.0`).
Neu ist nur, dass aus der flüchtigen Reservierung eine echte Ladung wird, die man auch verlieren kann.

**Der Abflug lädt nie.** Das ist keine Implementierungswahl, sondern Teil des Modells: „beim Abheben
laden" ist **nicht** bilanzgleich und wäre falsch.

**Musterwechsel** (Nutzer-Entscheidung 15.07.) braucht keine eigene Regel:

- **Am Boden:** Es wird **umgeladen** — die Ladung fällt ab wie beim Logout (Ladeplatz → zurück in
  den Stapel; fremder Platz → gestohlen). Steht er an einem Ladeplatz, füllt er sofort wieder auf
  (Laden ist ein Zustand) — dann mit der Kapazität des **neuen** Musters. Eine Kapazitätsprüfung
  „schrumpft die Ladung?" gibt es damit nicht.
- **In der Luft: ignoriert.** Die Ladung bleibt unverändert, auch wenn das neue Muster weniger
  trüge. Bewusst einfach gehalten — der Fall ist selten und richtet keinen Schaden an (die Ware ist
  bereits vom Stapel genommen, der Erhaltungssatz bleibt intakt).

*Beleg (Fable-Review):* Stapel 800, zwei Flieger à 1000 kg. A landet 18:00, B landet 18:05, B hebt
18:10 ab, A loggt 18:20 am Ladeplatz aus. **Laden am Platz:** A lädt 800 (kam zuerst — Entscheidung
5), B lädt 0, A gibt beim Logout alles zurück → **0 kg geliefert**. **Laden beim Abheben:** B lädt
800 → **800 kg geliefert**. Die Bilanz selbst kippt, und nur die erste Variante erfüllt Entscheidung
5 („wer zuerst *kommt*").

**`per_flight_max_kg` begrenzt, was ein Flieger von einer Frachtart AN BORD hat** — nicht, was er je
Ladevorgang aufnimmt. Sonst wäre die Kappung durch mehrfaches Landen am selben Platz umgehbar (zehn
Platzrunden = zehnmal die Kappungsmenge, alles in einer Lieferung; Fable-Review). Formal:
`nimm = min(Stapel, freie Kapazität, per_flight_max_kg − bereits_an_Bord[frachtart])`.

**Der Logout ist ein Ereignis der VATSIM-Session (`flights.logoff_time`), nicht des Tracks.** Das ist
der entscheidende Punkt: Der GPS-Detektor kennt **keine Verbindungsgrenzen**. Er segmentiert erst bei
Lücken > 30 min — ein Aus- und Wiedereinloggen binnen Sekunden ist für ihn unsichtbar, der Track läuft
durch.

**Logout-Ort — Regel:**

- Fällt der `logoff_time` in ein **laufendes** Leg (`takeoff_ts ≤ logoff_time ≤ landing_ts`), war der
  Pilot **in der Luft** → *versenkt*.
- Sonst stand er am Boden: Ort = `gps_arrival` des letzten abgeschlossenen Legs davor (bzw.
  `gps_departure`, wenn er nie abgehoben ist).

**Belegter Gegenfall (Nutzer-Fund 15.07., Event #123, CID 1602713 / FRS49, `flights.id` 357/358):**

```
Leg des Detektors:  EDXH → EDXH,  takeoff 18:10:11 ... landing 18:16:41
Session 357:        18:08:15 → Logout 18:13:11      <-- mitten im Leg, in der Luft
Session 358:        Login 18:16:05 → 18:18:27       <-- Leg laeuft noch bis 18:16:41
```

Der Pilot loggte sich kurz nach dem Start **in der Luft** aus und Sekunden später am Platz wieder ein.
Der Detektor macht daraus **ein** Leg `EDXH → EDXH` mit sauberer Landung. Eine Regel „letzter Leg →
`gps_arrival`" ergäbe hier fälschlich *zurück*; korrekt ist *versenkt* — was die heutige Wertung
bereits liefert (`kind=sunk`, logon 18:08:15). Nachgestellt und bestätigt (Szenario S8).

Die heutige **Eigenprüfung der Position** in `detect_transport_losses` (eigener
`nearest_airport`-Aufruf mit `_LANDED_MAX_GS_KT` = 40 kt, ohne AGL-Guard) entfällt trotzdem — die
Regel oben braucht sie nicht und ist genauer. Das löst zugleich **A10** (Großplatz > 4 km vom ARP →
fälschlich „sunk"). Der **Session-Bezug** dagegen bleibt und ist unverzichtbar.

### Wann das Event endet (Nutzer-Entscheidung 15.07.)

**Das Event darf erst eingefroren werden, wenn alle Ware einen End-Stapel gefunden hat** — geliefert,
zurück, gestohlen oder versenkt. Formal: **`Σ Flieger-Stapel == 0`**. Ein Pilotenstapel > 0
verhindert das Ende.

Damit **entfällt die Streckenprüfung** aus dem Feierabend-Kriterium. Heute fragt
`transport_anyone_in_progress` (`database.py:5241`): „gibt es einen offenen Flug, der auf der Strecke
gestartet ist?" — ein **Proxy** für „trägt vermutlich noch Ware", der beste, den ein Modell ohne
Ladungsbegriff hatte. Das Stapel-Modell kennt die Antwort direkt: Es zählt nur, ob jemand Ware trägt.
Kein „gestartet wo", keine Route, kein „offener Flug".

Nebeneffekt (gewollt): Ein **leerer** Pilot hält den Feierabend nicht mehr auf — er transportiert ja
nichts. Wer Ware trägt, hält auf, bis sie liegt.

Das löst zugleich den `dtend`-Fall: Erreicht das Fenster sein Ende, während jemand mit Ladung
unterwegs ist, wird **nicht** eingefroren — das Event wartet, bis die Ware angekommen oder verloren
ist. Es kann daher keinen eingefrorenen Zustand geben, in dem `geliefert + verloren + Reststapel <
Manifest` ist; der Erhaltungssatz ist zugleich die Abschlussbedingung.

**Sicherung gegen ewiges Offenbleiben:** `close_stale_flights` (`database.py:895`, 8 h) schließt
hängende Sessions und setzt `logoff_time` auf die letzte Position. Die Ware eines Piloten, der nie
sauber ausloggt, fällt damit spätestens nach 8 h in einen End-Stapel.

### Der Live-Status = Ort × Ladung

Keine eigene Wahrheit mehr, kein Ziel unterstellt (der Flugplan bleibt draußen, #23):

| Ort | An Bord | Status |
|---|---|---|
| Boden, Ladeplatz | egal | `🅿️ lädt in EDWG` |
| Luft | > 0 kg | `✈️ unterwegs · 800 kg` |
| Luft | 0 kg | `✈️ noch dabei` |
| Boden, fremder Platz | > 0 kg | `⏸ steht in EDDW · 800 kg` |
| Boden, fremder Platz | 0 kg | nicht in der Liste |
| Ziel | — | gezählt, fällt aus der Liste |

- **`arrived` entfällt ersatzlos.** Im sauberen Pfad ~0 s sichtbar (Latch und Leg-Schließung fallen
  ins selbe `gs<2`-Sample; gemessen 14/22 deckungsgleich). Eine Lieferung ist eine Tatsache im
  Balken, kein Zustand.
- **`returning` → `noch dabei`.** Der Name war eine Unterstellung über die Richtung. Die
  **Funktion** bleibt und ist die eigentliche Anforderung: *man sieht, wer noch mitmacht.* Damit
  entfällt auch **Z2** (feuerte für Positionierungsflüge).
- **`⏸ steht in …` ist neu.** Wer mit Ware zwischenlandet, ist heute unsichtbar, obwohl er Teil des
  Abends ist.
- **`unterwegs` wird ehrlich:** heißt „trägt Ware", nicht „fliegt vermutlich zum Ziel" — mit Menge.

### Was ersatzlos wegfällt

| | Warum |
|---|---|
| `transport_live_arrivals` (Tabelle), `check_live_arrival`, `set_/get_transport_live_arrival(s)`, `_latch_hits_flight`, `_LATCH_SLACK_SEC` | „Hat er geliefert?" wird nie mehr gefragt |
| Der `check_live_arrival`-Aufruf im Poller (`poller.py:870`) | — |
| Die Reservierung als eigener Mechanismus (`reserved_alloc`, `reserved_total_kg`, Kappung „auf offenen Bedarf") | Wer lädt, nimmt die Ware **vom Stapel** — das *ist* die Reservierung |
| Der Latch-Fallback „unbekanntes `dep` füllt alle Zeilen" | Erzeugte Ware, die nie an Bord war (S3b) |
| Die Verlust-**Klassifikation** aus der letzten Position | `returned/stolen/sunk` sind die drei Orte, an die die Ladung beim Logout wandert |
| Der „geteilte Topf" (`departure IS NULL`) und die CSV-Liste | Entscheidung 6 |

**By design unmöglich:** A3, Z1, A8, A11, Z2, A2, A4, A10 sowie #7 (Doppelvergabe derselben
Kapazität) und #8 (verlorene Ware im Pool) — beide folgen direkt aus dem Erhaltungssatz.

`detect_transport_losses` bleibt als **Funktion** (Verluste sind echt und brauchen das
Verbindungsende), verliert aber ihre Latch-Kopplung (`database.py:5064`, `5094`) und ihre
Eigenprüfung der Position. **Achtung:** Die Notiz vom 13.07. behauptete „Verlust-Logik bleibt
unverändert" — das ist nachweislich falsch und war ihr größter blinder Fleck.

### Plausibilitätsprüfung am `departure`-Feld (Entscheidung 6)

- **Regel:** genau ein gültiges ICAO, ≠ Ziel, und das Feld ist **Pflicht**.
  *Nicht* „muss in der abgeleiteten Route liegen" — die Route wird aus eben diesen Startplätzen
  abgeleitet (`_derive_route`, `database.py:4445`), die Bedingung könnte nie fehlschlagen und prüft
  nichts (Fable-Review).
- **`departure IS NULL` entfällt als Bedeutung** („geteilter Topf"). Der Code-Pfad existiert
  weiterhin für den Kalender (`Fracht: <Name> <kg>` ohne ICAO, `database.py:4448`): Solche Zeilen
  werden künftig **abgewiesen** — der Kalender-Sync meldet den Fehler am Event, statt still eine
  Zeile ohne Ort anzulegen. Ebenso `departure == Ziel`, das heute still zu NULL normalisiert wird.
- **Wo:** `set_transport_cargo` (Server, verbindlich), Admin-UI (Feld-Beschreibung + Inline-Fehler),
  Kalender-Parser (`Fracht <ICAO>: …` — Mehrfach-ICAO wird abgewiesen, nicht still geteilt).
- **Fehlertext:** sagt, was zu tun ist — „Jede Frachtart liegt an genau einem Platz. Für dieselbe
  Ware an mehreren Plätzen leg mehrere Zeilen an."
- **Bestand:** 16 von 17 Zeilen tragen bereits genau einen Platz; `departure IS NULL` kommt **kein
  einziges Mal** vor. Einzige CSV-Zeile: Event #123 („Multi-Kutter-Test", Krabbenbrötchen ab
  `EDWL,EDXH,EDXP`) — ein Testlauf, darf abweichen oder gelöscht werden.

## Migration

Alle vier Kutter sind abgeschlossen und tragen einen eingefrorenen `progress_snapshot` (v3). Sie
wurden mit einem Prototyp des Stapel-Modells **nachgerechnet**:

| Event | ALT (Snapshot) | NEU (Stapel) | |
|---|---:|---:|---|
| #1 FriesenKutter-Test Wangerooge | 1610 kg | **1610 kg** | identisch, Position für Position |
| #81 Strandkörbe und Sonnenschirme | 1120 kg | **1120 kg** | identisch |
| #136 Großauftrag für Wooge | 1090 kg | **1090 kg** | identisch, alle fünf Frachtarten |
| #123 Multi-Kutter-Test | 618 kg | 417 kg | Testlauf; Abweichung = die CSV-Zeile |

**Vorgehen:** `_PROGRESS_SNAPSHOT_VERSION` erhöhen (3 → 4), neu rechnen. **Kein Auftau-Schutz, kein
Einfrieren.** Die drei echten Abende bleiben aufs Gramm gleich, obwohl das Modell völlig anders
rechnet — der stärkste Beleg, dass hier nichts erfunden wird.

Damit ist auch ein **bestehender Widerspruch** entschärft: `POST /api/admin/transport/default-payload`
und die Muster-Zuladung löschen *alle* Kutter-Snapshots (`delete_progress_snapshots`, `main.py:2941`,
`2977`) — eine einzige Zuladungs-Korrektur taut jedes abgeschlossene Event auf. Solange die
Nachrechnung dieselben Zahlen liefert, ist das harmlos. Ohne diese Prüfung wäre es ein Zeitzünder
gewesen.

`transport_live_arrivals` wird **nicht gelöscht**, nur nicht mehr gelesen (kein DROP in dieser
Änderung; die Tabelle ist der Beleg für die Migration und stört nicht).

### Der 365-Tage-Cleanup (Nutzer-Entscheidung 15.07.)

Das Modell rechnet aus den GPS-Tracks. Fällt `position_history` weg, rechnet sich jedes Alt-Event auf
0 kg herunter — und **jede** Zuladungs-Korrektur invalidiert alle Snapshots (`main.py:2941`, `2977`),
auch in zwei Jahren noch. Heute ist das kein Problem: Der Cleanup-Job ist **deaktiviert**
(`poller.py:424`: „Cleanup deaktiviert — position_history wird dauerhaft behalten"); der
Fable-Befund „Alt-Events zerfallen" trifft den Ist-Zustand nicht.

**Regel für den Fall, dass er je aktiviert wird:** Werden Positionen älter als 365 Tage gelöscht,
werden die **Events desselben Zeitraums mitgelöscht** — vollständig und aus allen Sichten
(Live-Tab, Events-Tab, Admin, Snapshot, Badges). Kein Event überlebt seine Rohdaten. Dann gibt es
nichts, das sich neu berechnen könnte, und die Frage nach einem Auftau-Schutz stellt sich nicht.

Das gilt für **jede künftige Reaktivierung** von `_daily_cleanup` (`poller.py:1493`) und gehört
als Bedingung an den Job, nicht in eine Fußnote.

## Tests

**Neu (der Kern):**
- Erhaltungssatz: `Σ Stapel + Σ Ladung == Σ Manifest` nach jedem Ereignis — über alle Szenarien.
- Die sechs Szenarien S1–S6 aus dem Artifact mit echten Tracks (Milchmann, Zwischenlandung fremd,
  Logout am Ladeplatz/fremd/in der Luft), plus S7 (auffüllen → Logout → alles zurück, Bilanz 1300).
- Regressionswerte der Migration: #1 = 1610, #81 = 1120, #136 = 1090 (siehe oben).
- Plausibilitätsprüfung: Mehrfach-ICAO wird abgewiesen (Server + Kalender-Parser).
- „Zweiter hat Pech": Stapel 800, zwei Flieger à 1000 → 800 / 0.

**Zu löschen** (testen entfallene Bausteine): `test_set_and_get_roundtrip` (L579),
`test_insert_or_ignore_is_idempotent` (L586), `test_get_scoped_to_event` (L594), `TestCheckLiveArrival`
(5 Tests, L670–705), `TestLatchHitsFlight` (9 Tests, L723–761),
`test_check_live_arrival_uses_global_radius_regardless_of_event_radius` (L951).

**Umzubauen** (nutzen den Latch als Fixture statt eines Tracks): der Helper `_add_delivered_flight`
(L104) und die ~15 Tests, die ihn verwenden, brauchen echte GPS-Tracks. Ebenso
`test_open_flight_with_latch_counts_immediately` (L776), `test_open_flight_participates_in_coload_fill`
(L850), `test_latch_converts_reservation_to_delivered` (L1117).

**Bewusst zu streichen** (Anforderung entfällt, Entscheidung 8):
`test_latch_persists_after_disconnect_without_known_arrival` (L814) — Lieferung ohne jede Position.

**Anzupassen:** `test_arrived_status_with_latch` (L2133) → Status entfällt;
`test_returning_pilot_still_shown_while_still_airborne` (L2118) und `test_statuses_and_sums` (L2068)
→ `returning` heißt jetzt `noch dabei` und bleibt sichtbar.

**Zu prüfen (echte Verhaltensänderung, kein reiner Testumbau):** `test_latched_flight_does_not_delay`
(L880) — der Latch signalisiert `transport_anyone_in_progress`, dass eine noch offene Verbindung
fertig ist. Neu: „unterwegs" = trägt Ware; wer geliefert hat, trägt nichts mehr und verzögert den
Feierabend nicht. Muss explizit getestet werden.

## Offen

Fachlich ist alles entschieden. Ein Punkt folgt aus „Laden ist ein Zustand" und ist hier so
festgeschrieben, aber nie ausdrücklich bestätigt worden:

- **Der Wartende lädt nach.** Steht jemand an einem leeren Stapel und ein anderer gibt dort beim
  Logout Ware zurück, lädt der Wartende — er steht ja am Platz, und Ware ist da. Technisch: Nach
  jedem Ereignis, das einen Stapel auffüllt, laden alle, die dort stehen, in Ankunftsreihenfolge
  (Entscheidung 5). Dieselbe Mechanik trägt den Musterwechsel am Boden.

Implementierungsseitig offen (gehört in den Plan, nicht hierher): die künftige Rolle von
`transport_losses` als Tabelle (Quelle vs. reiner Quip-/Push-Latch — sonst entstehen wieder zwei
Klassifikations-Wahrheiten), und der Feld-Vertrag zum Frontend (`reserved_kg`, `in_air`, `airborne`,
`status === 'returning'` in `index.html`) beim Wechsel auf Snapshot-Version 4.

## Risiken

- **Der Umbau ist ein Big Bang.** Der Latch kann nicht halb weg sein: `compute_transport_progress`
  (636 Zeilen, 5278–5913) und `detect_transport_losses` (103 Zeilen, 5038–5140) hängen beide an ihm. Der Plan muss den
  Kern in einem Zug ersetzen und darf sich auf die Regressionswerte der Migration stützen.
- **Zwei Definitionen derselben Schwelle** bleiben bestehen und sollten in dieser Änderung
  zusammengeführt werden: `_BLOCK_GS_KT` (`database.py:1070`) und `_GPS_BLOCK_GS_KT`
  (`gps_legs.py:19`), beide `2`. `_LANDED_MAX_GS_KT` (40 kt) entfällt mit der Eigenprüfung.
- **Der Feed** (`flights`-Liste) zeigt heute auch Rückflüge als „leer" — Anforderung aus dem Konzept
  vom 01.07. („5 Flüge, 3 mit Fracht"). Das Stapel-Modell ändert daran nichts, der Plan darf es
  aber nicht verlieren.
- **`skip_open_probe` (#66)** und die Snapshot-Mechanik für abgeschlossene Events bleiben; der
  Offen-Zweig wird durch „Ort × Ladung" ersetzt, nicht entfernt.
