# Skill „track-diagnose" — Einzelfall-Analyse von Erkennungslücken

**Datum:** 2026-07-15
**Status:** abgenommen (Nutzer, 2026-07-15)

## Problem

Beim Abarbeiten der Erkennungslücken-Liste (`/admin`, `list_gps_detection_gaps`) stellt sich immer
dieselbe Frage: *Warum hängt dieser Flug an Platz X?* Die Analyse dahinter wurde am 2026-07-15
viermal gefahren (EBKT, ELLX, LKLB, EDDH) — jedes Mal mit derselben Mechanik, jedes Mal ad hoc neu
zusammengesucht. Das kostet nicht nur Zeit, es ist auch fehleranfällig:

- Beim Vollaudit entstand ein **Mittelwert-Bug** (naiver Zentroid statt Modus-Cluster), der vier
  Falschbefunde produzierte (LIDT, CJV8, EKVG, KMKC).
- Bei **EDHX** und **ETUO** wäre fast ein realer Flugplatz verschoben worden, weil die Umkehrfrage
  („welcher Platz liegt dem Punkt am nächsten?") beinahe übersprungen wurde.
- Bei **EDDH** wurde als Erstes über den Suchradius nachgedacht, obwohl es gar keinen Bodenpunkt
  gab — die Radiusfrage war von vornherein gegenstandslos.

Alle drei Fehler haben dieselbe Ursache: Die Reihenfolge der Prüfung und die Trennung zwischen
*Messung* und *Deutung* waren nirgends festgeschrieben.

## Abgrenzung

**Triage zuerst, dann Einzelfall — ein Ablauf, nicht zwei.** Die Erkennungslücken-Liste hat
163 offene Fälle (184 Enden, da 29 Fälle beide Enden vermissen). Sie einzeln durchzugehen wäre
Verschwendung: **74,5 % sind rein mechanisch abzuhaken** (gemessen 2026-07-15, siehe unten). Der
Batch misst Schritt 0 und Schritt 1 über alle Fälle und sortiert die trivialen aus; übrig bleiben
die echten Fragen, die einzeln beurteilt werden.

Das funktioniert, weil **Schritt 0 und Schritt 1 reine Messungen sind** — „gibt es an diesem Ende
einen Bodenpunkt?" und „welcher Platz liegt am nächsten?" brauchen keinen Kontext. Erst Schritt 2
braucht Urteilskraft. Die Prüfreihenfolge ist damit zugleich die Triage-Logik; der Batch fällt
fast umsonst ab.

| Triage-Befund (184 Enden) | Anzahl | Anteil |
|---|---|---|
| **E** — kein Bodenpunkt (Track beginnt/endet in der Luft) | 128 | 69,6 % |
| **Kandidat** — braucht Urteil | **23** | **12,5 %** |
| **Zu dünn** — Track hat < 3 Punkte | 19 | 10,3 % |
| **ZZZZ** — Flugplan-Platzhalter, kein Platz | 11 | 6,0 % |
| **D** — Punkt liegt an einem anderen Platz | 3 | 1,6 % |

**87,5 % mechanisch abgehakt, 23 echte Fragen.** Die Kandidaten zeigen keine Häufung — also kein
zweiter Belgien-Fall in Sicht.

**Der Skill endet beim Urteil.** Er liefert Diagnose, Belege und ggf. einen konkreten
Eintragsvorschlag (ICAO, Koordinate, Radius, Grund), trägt aber **nichts ein** — das bleibt beim
Nutzer über die Admin-UI. Begründung: Genau die Fälle, die „klar" aussahen (EDHX, ETUO), waren die
falschen, und jeder Write stößt einen vollen `rebuild_flight_cache` an. Für die Triage gilt
dasselbe: sie sortiert nach Messkriterien, sie entscheidet nichts.

**Nicht Teil dieses Skills:** das Vollaudit der gesamten Historie (Modus-Cluster über viele Flüge
je Platz). Andere Frage, andere Fallstricke, einmalig gebraucht.

## Artefakte

| Datei | Zweck |
|---|---|
| `.claude/skills/track-diagnose/SKILL.md` | Ablauf, Export-Snippet, SQL, Fallunterscheidung |
| `scripts/nearby_airports.py` | Messwerkzeug (rein, offline, kein DB-Zugriff) |
| `scripts/triage_gaps.py` | Batch: liest den JSON-Export, misst Schritt 0/1, gruppiert |
| `tests/test_nearby_airports.py` | Regressionstests aus den realen Fällen |
| `tests/test_triage_gaps.py` | Triage-Tests gegen eine JSON-Fixture |
| `README.md` (Korrektur) | Falschaussage zur Koordinatenherkunft richtigstellen |

Der Skill liegt **im Repo**, nicht user-global: er kennt Tabellennamen, Detektor-Schwellen und die
Custom-Airports-Logik. Ändert sich `app/gps_legs.py`, muss der Skill im selben Commit mitgezogen
werden — user-global könnte er still veralten, ohne dass es im Review auffällt.

Das Werkzeug liegt in `scripts/` (neben `consolidate_flights.py`) statt im Skill-Ordner, damit es
von `tests/` aus normal importierbar ist.

## Datenzugang

**SSH + sqlite3, ausschließlich lesend.** Der Skill schreibt nie in die Produktions-DB.

```bash
ssh -i ~/.ssh/tsbot_server root@167.86.127.129 "sqlite3 /opt/friesenspy/data/friesenspy.db '...'"
```

Stolpersteine, die in den Skill gehören, weil sie real Zeit gekostet haben:

- Der SSH-Host-Alias `friesenspy` **existiert nicht** — Verbindung geht über die IP.
- Der Key ist `~/.ssh/tsbot_server` (nicht der Default-Key).
- `flight_cache` hat **keine** Spalte `statsim_id`.
- Der API-Weg (`/api/flights/statsim/{id}/track`) ist **kein** Ersatz: die Endpoints verlangen
  Login (globale Middleware), auch die vermeintlich öffentlichen.

### Export für die Triage (`docker exec`)

Die Lückenliste **muss aus der App kommen**, nicht per SQL nachgebaut: `list_gps_detection_gaps`
ruft `canonicalize_legs` über die gesamte Historie — in SQL nachgebildet triagierte man eine
andere Liste als die, die im Admin steht. Der Container hat die Funktion; abgerufen wird nur das
Ergebnis:

```bash
ssh -i ~/.ssh/tsbot_server root@167.86.127.129 \
  "docker exec friesenspy-friesenspy-1 python -c '<Export-Snippet>'" > gaps.json
```

Gemessen: ~18 s Laufzeit, **75 KB JSON** für 163 Fälle. Bewusst **kein** Abzug der DB (42 MB, mit
Push-Subscriptions, Pilotennamen, Tokens) — für eine Triage von Positionsrändern wird davon
nichts gebraucht.

> **Fallstrick, der real zugeschlagen hat:** `docker exec python -c` startet einen **frischen
> Prozess**. `geo._CUSTOM_AIRPORTS` wird aber erst beim App-Start über `set_custom_airports()`
> befüllt (`app/main.py:204`) — im Ad-hoc-Prozess ist der Cache **leer**, und sämtliche
> `custom_airports`-Korrekturen existieren nicht. Der erste Testlauf lieferte deshalb 199 statt
> 163 Fälle: **36 Phantom-Lücken** an längst korrigierten Plätzen (EDEN, EBBR, ELLX, EDDF, EDHD,
> EDST). Das Export-Snippet **muss** darum mit
> `geo.set_custom_airports(list_custom_airports(conn))` beginnen.

## Das Messwerkzeug (`scripts/nearby_airports.py`)

**Schnittstelle:**

```bash
python scripts/nearby_airports.py <lat> <lon> [--alt <ft MSL>] [--icao <Soll-Code>]
```

**Ausgabe, drei Blöcke:**

1. **Nächste Plätze laut airportsdata** — Distanz, Elevation, AGL (wenn `--alt` gesetzt)
2. **Nächste Plätze laut OurAirports** — dieselben Spalten, unabhängige Quelle
3. **Abweichung airportsdata ↔ OurAirports** für die beteiligten Codes — der Block, der einen
   Belgien-Fall (Fall B) sofort sichtbar macht

Mit `--icao` zusätzlich die gezielte Soll-Prüfung: Distanz des Punktes zum Flugplan-Code, in
beiden Quellen. Die Gegenüberstellung von Soll-Distanz und Nächster-Platz-Distanz **ist** der
Fall-D-Nachweis (EDHX: 132,70 km zum Soll laut OurAirports gegen 0,16 km zu EDXH).

**Ein Code kann in einer Quelle fehlen und in der anderen stehen** — das ist kein Sonderfall,
sondern Alltag: `EDHX` steht nur in OurAirports, `ETUO` nur in airportsdata. Beide Blöcke müssen
deshalb unabhängig „nicht vorhanden" melden können, ohne dass der andere Block ausfällt.

**OurAirports-Codes werden über `ident`, `icao_code` *und* `gps_code` gematcht.** Verlässt man
sich auf `icao_code`, verschwinden reale Plätze: `EDHX` (Bad Bramstedt Heliport) und `EBMO`
(Moorsele) stehen unter `ident`, ihr `icao_code`-Feld ist leer.

**Schwellen werden aus `app/gps_legs.py` importiert, nie abgeschrieben** — `_GPS_SPAWN_MAX_AGL_FT`
(1500), `_GPS_GROUND_AGL_FT` (300) — ebenso `_BUMMEL_AIRPORT_RADIUS_KM` (4,0) aus
`app/database.py`. Das Werkzeug stellt Messwert und Schwelle nebeneinander:

```
EDDH   15.05 km   (Standardradius 4.0 km — außerhalb)
       AGL 2156 ft (Spawn-Grenze 1500 ft — überschritten)
```

**Das Werkzeug fällt kein Urteil.** Es sagt „außerhalb", nicht „also Radius-Override".

**Quellen:**

- airportsdata über `airportsdata.load("ICAO")` — die Rohquelle, per Definition ohne
  `custom_airports`, und die einzige, die auch Name und Elevation liefert (die das Werkzeug für
  die Nachbarliste und AGL braucht). Bewusst **nicht** `app.geo.icao_to_coords()`: das bezieht
  `custom_airports` ein und drückt jeden Override-Vergleich auf 0 km (#78-Fund).
  `app.geo.airportsdata_coords()` (v9.5.0) wäre semantisch dasselbe, liefert aber nur `(lat, lon)`
  — es zusätzlich aufzurufen prüfte dieselbe Eigenschaft zweimal und verschleierte, dass die
  Rohquelle bereits die Garantie ist. Aus `app.geo` kommt nur `haversine`.
  Das Werkzeug misst gegen die Referenzquellen; den Custom-Stand zeigt der Ablauf separat.
- OurAirports als unabhängige Gegenprobe, Vollabzug von
  `https://davidmegginson.github.io/ourairports-data/airports.csv` (~12 MB), gecacht nach
  `scripts/.cache/ourairports.csv` (in `.gitignore`), mit Altersprüfung. Ohne Netz arbeitet das
  Werkzeug nur mit airportsdata weiter **und sagt das dazu**, statt abzubrechen.
- Der OurAirports-Loader ist injizierbar (Pfad-Parameter), damit Tests ohne Netz laufen.

## Ablauf

### A — Triage (die Liste)

1. Export ziehen (`docker exec`, siehe oben) → `gaps.json`
2. `python scripts/triage_gaps.py gaps.json` → gruppierte Befunde
3. Trivialgruppen (E, ZZZZ) dem Nutzer als Sammelbefund melden — nicht einzeln durchkauen
4. Kandidatenliste als Arbeitsvorrat für B

`triage_gaps.py` ist dünn: Es liest den JSON-Export, wählt je Fall das fragliche Ende
(`missing: "departure"` → erster Punkt, `"arrival"` → letzter, `"both"` → beide, ergibt zwei
Enden) und ruft `measure()` aus `nearby_airports.py`. Die Gruppierung ist Schritt 0 und Schritt 1
der Prüfreihenfolge, sonst nichts:

Die Gruppen werden **in dieser Reihenfolge** geprüft; die erste, die greift, gewinnt:

| # | Gruppe | Kriterium (rein mechanisch) |
|---|---|---|
| 1 | **Zu dünn** | Track hat < 3 Punkte — der Detektor braucht mindestens einen Zustandswechsel (ON_GROUND → AIRBORNE → ON_GROUND); bei einem einzigen Sample ist jede weitere Aussage bedeutungslos |
| 2 | **ZZZZ** | Soll-Code ist `ZZZZ` — Flugplan-Platzhalter, es gibt keinen Platz zu finden |
| 3 | **E** | Randpunkt ist in der Luft (Kriterium unten) |
| 4 | **D** | nächster Platz ≠ Soll-Code und unter 1 km |
| 5 | **Kandidat** | alles übrige — braucht Schritt 2 und damit ein Urteil |

**Reihenfolge 1 vor 4 ist nicht kosmetisch:** Sechs der ursprünglich neun D-Befunde waren
Ein-Punkt-Tracks. Fall 27831625 (FRS96, ein einziges Sample) hätte als „Punkt gehört zu EDNR,
0,06 km" gemeldet werden müssen — formal korrekt gemessen und trotzdem Unsinn.

**„In der Luft" (Gruppe E) — Höhe führt, Groundspeed hilft:**

```
in_der_luft = (AGL > _GPS_GROUND_AGL_FT)  ODER  (groundspeed >= _GPS_FLYING_GS_KT)
```

AGL wird gegen die Elevation des Soll-Platzes gerechnet; fehlt der Code in beiden Quellen, gegen
die des nächstgelegenen Platzes. Beide Signale sind nötig und keines genügt allein — gemessen an
den 184 Enden: **13 Enden erkennt nur die Höhe** (Groundspeed sagt fälschlich „Boden"), **5 nur
die Groundspeed**.

Das ist dieselbe Gewichtung wie im Detektor (`app/gps_legs.py:4`: *„Höhe (AGL) ist das Leitsignal,
Groundspeed nur sekundär — STOL/Heli fliegen langsam"*). Ein erster Entwurf dieser Triage nahm
Groundspeed als Leitsignal und hätte FRS125 ab ETNJ mit `gs 22` als Bodenpunkt gewertet — bei
4401 ft. Wilga-Reisegeschwindigkeit liegt bei rund 40 kt; eine gs-zentrierte Regel klassifiziert
STOL-Flüge systematisch falsch.

Kein DB-Zugriff: JSON rein, Gruppen raus. Damit genauso testbar wie das Messwerkzeug.

### B — Einzelfall (ein Kandidat)

Einstieg ist entweder ein Kandidat aus A oder eine Track-URL vom Nutzer
(`…&track=<statsim_id>&src=statsim`).

Der Skill zieht Trackpunkte und `statsim_cache`-Metadaten (departure, arrival, logon/logoff) per
SQL, prüft den aktuellen `custom_airports`-Stand, bestimmt die Randpunkte und ruft dann das
Werkzeug mit Punkt + Soll-Code auf. Bei `missing: "both"` zwei Läufe: Startpunkt gegen
`plan_departure`, Endpunkt gegen `plan_arrival`. Dann die Prüfreihenfolge.

### C — Blinde Fälle ohne Flugplan

Eigener Einstieg, weil weder die Liste noch die Triage sie zeigt.

`list_gps_detection_gaps` (`app/database.py:4683`) meldet einen Fall nur, wenn eine Soll-Angabe
existiert: `missing_dep = not gps_departure and plan_departure`. **Ein Flug ohne Flugplan, dessen
Start nicht erkannt wird, ist für die Liste unsichtbar.** Da FriesenSpy seit #23 GPS-only ist,
werden solche Flüge trotzdem gewertet — nur geprüft werden sie nie.

Gemessen (2026-07-15) über `flight_cache` (FRS-Callsigns): 2104 Legs, **vier blinde Fälle** —
u. a. FRS145 (08.06., 25 Minuten, weder Start noch Ziel irgendwo vermerkt). Untergrenzwert:
`flight_cache` filtert auf `CALLSIGN_PREFIX`, die Lückenliste läuft über alle Callsigns.

Der Skill enthält die SQL-Abfrage, die diese Fälle findet. Die App wird **nicht** umgebaut — bei
vier Fällen wäre das ein eigenes Feature mit eigenem Design, kein Nebenprodukt.

> **Zwei Zahlen, die nicht verwechselt werden dürfen:** `flight_cache` hat 2104 Legs, aber nur
> FRS-Callsigns; die Erkennungslücken-Liste läuft über **alle** Callsigns und ist bei 200 Zeilen
> gekappt (`gaps[:200]`, `app/database.py:4708`). Die 163 offenen Fälle stammen aus der Liste, die
> vier blinden Fälle aus `flight_cache` — sie sind nicht Teil derselben Grundgesamtheit. Wegen der
> Kappung ist auch 163 möglicherweise nicht alles.

Ohne Flugplan verschiebt sich die Analyse zweifach: **Fall D entfällt** (wo kein Soll ist, kann
nichts abweichen), und **Fall A wird zur Recherche** — der Bodenpunkt liegt irgendwo, kein Platz in
Reichweite, und kein Code sagt, wie er heißt. Dann bleiben OurAirports und Websuche.

## Fallunterscheidung

### Die Asymmetrie (steht im Skill ganz oben)

Ein **fehlender** Eintrag kostet eine unerkannte Strecke. Ein **falscher** Eintrag verschiebt einen
realen Flugplatz für *alle* Auswertungen (Statistik, Bummel, Kutter) — unbemerkt, weil
`icao_to_coords` brav weiter einen Treffer liefert. Die Fehler sind nicht gleich teuer.
**Im Zweifel wird nichts eingetragen.**

### Reihenfolge der Prüfung

Wichtiger als die Fallliste selbst — hier lagen die realen Fehler:

**Schritt 0 — Gibt es an *diesem* Ende überhaupt einen Bodenpunkt?** Die Frage gilt je Ende, nicht
je Track: Der EDDH-Fall *hat* einen sauberen Bodenpunkt — am Ziel EDDM, nicht am Start. Geprüft
wird der Randpunkt des Segments, um den es geht (erster Punkt bei fehlendem Start, letzter bei
fehlendem Ziel).

Bodenkontakt zeigt sich primär an der **Groundspeed** (`_GPS_BLOCK_GS_KT`, 2 kt = Vollstopp) und an
einer über mehrere Samples **konstanten Höhe** (= Platzelevation). Bewusst nicht primär an AGL:
Höhe über Grund setzt eine bekannte Platz-Elevation voraus — die es bei einem fehlenden oder
falsch verorteten Platz gerade nicht gibt. Erst wenn ein Soll-Code vorliegt, kommt
`_GPS_GROUND_AGL_FT` (300 ft) als Gegenprobe dazu.

Kein Bodenpunkt → **Fall E**, Ende.
*(EDDH-Lehre: erst zuletzt gefragt, deshalb überhaupt über den Radius nachgedacht.)*

**Schritt 1 — Wohin gehört der Bodenpunkt?** Die Umkehrfrage: nicht „passt der Punkt zum Code",
sondern „welcher Platz liegt am nächsten", in beiden Quellen. Anderer Platz unter 1 km →
**Fall D**, Ende. *(Rettete EDHX und ETUO.)*

> **Warum diese Reihenfolge nicht verhandelbar ist — der EDHX-Beleg:** `EDHX` steht **nicht in
> airportsdata** und erfüllt damit *formal das Kriterium von Fall A* („Code fehlt → Ergänzung").
> Wer bei Schritt 2 einsteigt, trägt einen Platz ein. Schritt 1 zeigt: der Bodenpunkt liegt
> 0,16 km von **EDXH** (Helgoland-Düne) — der Pilot hatte den Code verdreht. `EDHX` existiert
> real, aber als *Bad Bramstedt Heliport*, 132,70 km entfernt (nur in OurAirports, dort ohne
> `icao_code`). **Fall D schlägt Fall A**, immer.

**Schritt 2 — Erst jetzt der Code.** Fehlt er in airportsdata → **A**. Steht er drin, liegt aber
über 3 km weg, während OurAirports auf dem Punkt sitzt → **B**. Deckt airportsdata sich mit
OurAirports und der Punkt liegt trotzdem draußen → **C**. Ist airportsdata ohnehin näher, als ein
Override es wäre → **F**. *(EBKT-Lehre: dort wurde bei Schritt 2 eingestiegen — mit Glück.)*

Merksatz für den Skill: **Erst fragen, ob es einen Bodenpunkt gibt, dann wohin er gehört, und erst
zuletzt, was mit dem Code los ist.**

### Die sechs Fälle

| Fall | Befund | Handlung | Referenz |
|---|---|---|---|
| **A** | Code steht nicht in airportsdata — **und Schritt 1 hat keinen anderen Platz gefunden** | Ergänzung, Grund `Fehlt in airportsdata` | EDEN, EDWT |
| **B** | Code steht drin, aber weit weg; OurAirports liegt auf dem Punkt | Koordinaten-Override, Grund `airportsdata-Koordinate falsch` | EBKT, EBBR, ELLX |
| **C** | Koordinate stimmt (AD deckt sich mit OA), echter Bodenpunkt trotzdem außerhalb 4 km | Radius-Override, Grund `Abhebepunkt außerhalb Standardradius` | EDDF, EHAM |
| **D** | Der Bodenpunkt gehört zu einem *anderen* Platz | nichts eintragen | EDHX, ETUO |
| **E** | An diesem Ende gibt es gar keinen Bodenpunkt | nichts eintragen | EDDH, LKLB |
| **F** | Quellen widersprechen sich, nicht auflösbar | nichts eintragen, Befund festhalten | SLSM |

**Fall A hat zwei Zweige:**

- Platz hat einen echten ICAO-Code, den airportsdata nicht kennt → Ergänzung mit diesem Code.
- Platz hat **gar keinen** ICAO-Code → Pseudo-Code nach dem etablierten Muster (`BZWIROS`,
  `ZZSALZ`, `EXHB`, `CML5`). Ein solcher Code ist **frei erfunden und muss vom Nutzer kommen**,
  nicht vom Assistenten.

  *Konsistenz mit `2026-07-15-flugplatz-grund-design.md`:* Dort wurde bewusst **kein** eigener
  Grund für Platzhalter-Codes eingeführt („verwässert die Vorschlagsliste"). Der Pseudo-Code-Zweig
  ist eine Handlungsvariante, keine Grund-Variante — der Grund bleibt `Fehlt in airportsdata`.

**Fall D fasst zwei Ursachen zusammen:** Flugplan-Tippfehler (EDHX, Punkt 0,2 km neben EDXH) und
schlichte Umplanung (ETUO, Pilot stand in Bad Gandersheim). Die Unterscheidung ist erklärend, nicht
handlungsleitend — in beiden Fällen ist der Platz richtig verortet und der Flugplan das Problem.

**Fall C braucht eine Plausibilitätsprüfung:** Ein Flugplatz misst selten mehr als sechs Kilometer.
Die Nachbarliste des Werkzeugs zeigt, welche Plätze ein größerer Radius mitverschluckt — das ist
der eigentliche Preis eines Radius-Overrides.

## Tests

`tests/test_nearby_airports.py`, Regressionsfälle aus realen Punkten (nicht aus erfundenen Zahlen —
so dokumentieren sie zugleich, wogegen das Werkzeug schützt):

Alle Werte am 2026-07-15 aus der Produktions-DB und den beiden Referenzquellen **gemessen**, nicht
geschätzt:

| Punkt (aus `statsim_position_history`) | Erwartung | Deckt ab |
|---|---|---|
| **EDHX** `54.18665 / 7.91488` (Track 29258369, gs 0, 7 ft) | `--icao EDHX`: in airportsdata **nicht vorhanden**, in OurAirports 132,70 km; nächster Platz **EDXH 0,16 km** | Fall D schlägt Fall A |
| **ETUO** `51.85449 / 10.02288` (Track 23066993, gs 0, 779 ft) | `--icao ETUO`: airportsdata 118,05 km, in OurAirports **nicht vorhanden**; nächster Platz **EDVA 0,19 km** | Fall D, einseitige Quelle |
| **EDDH** `53.49527 / 10.00085 --alt 2209` (Track 28133172, gs 217) | EDDH **15,05 km** (> 4,0 km) **und** AGL **2156 ft** (> 1500 ft) | Fall E, Schwellen-Import |
| **EBKT** `50.82005 / 3.2163` (Track 28531653, gs 0, 71 ft) | airportsdata 37,20 km, OurAirports 0,49 km, **Delta AD↔OA 37,00 km**; nächster AD-Platz ist EBMO 6,06 km | Fall B |

Der EBKT-Test hält zusätzlich fest, dass Schritt 1 hier **nicht** greift: EBMO liegt 6,06 km weg,
über der 1-km-Schwelle — sonst wäre der Belgien-Fund fälschlich als Fall D abgetan worden.

Der OurAirports-Loader bekommt in Tests eine kleine Fixture-CSV — kein Netz, kein 12-MB-Download.

**`tests/test_triage_gaps.py`** gegen `tests/fixtures/gaps_mini.json` — sechs **echte** Fälle aus
dem Export vom 2026-07-15, einer je Gruppe:

| `statsim_id` | Fall | Erwartung |
|---|---|---|
| 27831625 | FRS96, **1 Punkt**, Soll EDDM | **Zu dünn** — *obwohl* EDNR nur 0,06 km entfernt liegt. Der Test beweist, dass die Punktzahl vor der Nachbarschaft geprüft wird. |
| 27404430 | FRS116, Soll `ZZZZ`, gs 147 | **ZZZZ** — *obwohl* der Punkt auch in der Luft ist. Beweist Reihenfolge 2 vor 3. |
| 28133172 | FRS96, EDDH, 2209 ft / 217 kt | **E** — der Fall, der diesen Skill ausgelöst hat |
| 26626195 | FRS119N, Soll EDLJ, Punkt 0,03 km an EDLI | **D** |
| 28099919 | FRS177, Soll RCLM, Bodenpunkt, nächster Platz 302 km | **Kandidat** |
| 25216444 | FRS125, `missing: "both"`, gs 22 bei **4401 ft** | zwei Enden; das Start-Ende ist **E** — der STOL-Test: mit Groundspeed als Leitsignal wäre es fälschlich ein Bodenpunkt |

Die Fixture ist 2,6 KB groß und enthält nur Callsigns und Positionen — keine Pilotennamen.

Der `both`-Test ist doppelt wertvoll: 29 der 163 Fälle vermissen beide Enden, und ein Ende kann
trivial sein, während das andere ein Kandidat ist.

Der EDDH-Test hängt an den importierten Konstanten: Ändert jemand `_GPS_SPAWN_MAX_AGL_FT`, ohne an
den Skill zu denken, wird der Test **rot**, statt dass der Skill still falsch wird. Das ist die
Absicherung dafür, dass ein Skill Wissen über Code enthält.

Vorgehen nach TDD: Test schreiben, RED verifizieren, dann implementieren.

## README-Korrektur

`README.md:75` behauptet, die airportsdata-Koordinaten stammten aus der OurAirports-Datenbank. Der
Belgien-Fund widerlegt das: airportsdata und OurAirports weichen bei 848 von 24.253 gemeinsamen
Codes um mehr als 3 km ab (3,5 %; Belgien 34 %). Der Satz wird richtiggestellt — airportsdata
nennt OurAirports als Quelle, deckt sich aber nachweislich nicht damit.

## Bewusst nicht Teil dieser Arbeit

- **Kein Versionssprung, kein Tag, kein Changelog-Eintrag.** Am ausgelieferten Verhalten ändert
  sich nichts; `scripts/` und `.claude/skills/` landen in keinem Container. Ein Nutzer-Banner wäre
  Rauschen. (Ausnahme von der stehenden Versionierungsregel, mit dem Nutzer abgestimmt.)
- **Keine Ergänzung in `docs/api.md` / `docs/architecture.md`** — kein Endpoint, keine
  Architekturänderung.
- **Kein Umbau der Erkennungslücken-Liste** für flugplanlose Fälle (vier Stück; eigenes Design,
  falls es je gebraucht wird).
- **Kein Vollaudit-Werkzeug** (Modus-Cluster) — andere Frage, andere Fallstricke.
- **Kein automatisches Eintragen**, auch nicht für „klare" Fälle.
- **Kein Abzug der Produktions-DB.** Der Export liefert 75 KB statt 42 MB; ein Vollabzug zöge
  Push-Subscriptions, Pilotennamen und Tokens auf lokale Platten, ohne dass die Triage davon
  irgendetwas braucht.
- **Kein Dismiss/Schreiben aus der Triage.** Auch ein Sammelbefund „115× Fall E" wird vom Nutzer
  abgehakt, nicht vom Skill.

## Offene Punkte (nicht blockierend)

- Der airportsdata-Belgienfehler ist **upstream nicht gemeldet**. Eigenes Thema.
- Legs über Track-Lücken zusammenführen (LKLB-Muster) — echte Design-Entscheidung mit Risiko: eine
  reale Zwischenlandung darf nie verschluckt werden. Eigenes Thema.
- **Die Lückenliste ist bei 200 Zeilen gekappt** (`app/database.py:4708`). Beim Testlauf lagen
  200 Zeilen an — es könnten also mehr offene Fälle existieren, als die Liste zeigt. Ob die
  Kappung stört, zeigt sich erst, wenn die 47 Kandidaten abgearbeitet sind.
- **115 Fälle „Track beginnt in der Luft" sind ein eigener Befund.** Sie sind keine Datenfehler,
  aber 62,5 % der Liste. Ob man sie dauerhaft anders behandelt (z. B. gar nicht erst als Lücke
  melden, wenn der Randpunkt airborne ist), ist eine Produktentscheidung — nicht Teil dieses
  Skills, aber einen eigenen Gedanken wert.
