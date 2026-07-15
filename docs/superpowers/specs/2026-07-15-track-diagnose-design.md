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

**Nur Einzelfall-Diagnose.** Ein Track rein, ein begründetes Urteil raus. Das Vollaudit der
gesamten Historie (Modus-Cluster über viele Flüge je Platz) ist ausdrücklich **nicht** Teil dieses
Skills — es ist eine andere Frage mit anderen Fallstricken und wurde einmalig gebraucht.

**Der Skill endet beim Urteil.** Er liefert Diagnose, Belege und ggf. einen konkreten
Eintragsvorschlag (ICAO, Koordinate, Radius, Grund), trägt aber **nichts ein**. Das Eintragen
bleibt beim Nutzer über die Admin-UI. Begründung: Genau die Fälle, die „klar" aussahen (EDHX,
ETUO), waren die falschen — und jeder Write stößt einen vollen `rebuild_flight_cache` an.

## Artefakte

| Datei | Zweck |
|---|---|
| `.claude/skills/track-diagnose/SKILL.md` | Ablauf, fertige SQL-Abfragen, Fallunterscheidung |
| `scripts/nearby_airports.py` | Messwerkzeug (rein, offline, kein DB-Zugriff) |
| `tests/test_nearby_airports.py` | Regressionstests aus den realen Fällen |
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

**Zwei Einstiege:**

1. **Aus der Erkennungslücken-Liste** — der Normalfall. Jede Zeile ist bereits eine Soll/Ist-
   Gegenüberstellung: `plan_departure` gesetzt, `gps_departure` leer.
2. **Blinde Fälle ohne Flugplan** — siehe unten.

Der Skill zieht Trackpunkte und `statsim_cache`-Metadaten (departure, arrival, logon/logoff) per
SQL, bestimmt die Randpunkte und ruft dann das Werkzeug mit Punkt + Soll-Code auf. Bei
`missing: "both"` zwei Läufe: Startpunkt gegen `plan_departure`, Endpunkt gegen `plan_arrival`.

### Blinde Fälle ohne Flugplan

`list_gps_detection_gaps` (`app/database.py:4683`) meldet einen Fall nur, wenn eine Soll-Angabe
existiert: `missing_dep = not gps_departure and plan_departure`. **Ein Flug ohne Flugplan, dessen
Start nicht erkannt wird, ist für die Liste unsichtbar.** Da FriesenSpy seit #23 GPS-only ist,
werden solche Flüge trotzdem gewertet — nur geprüft werden sie nie.

Gemessen (2026-07-15): 2104 FRS-Legs, 101 sichtbare Lücken, **vier blinde Fälle** — u. a. FRS145
(08.06., 25 Minuten, weder Start noch Ziel irgendwo vermerkt). Untergrenzwert: `flight_cache`
filtert auf `CALLSIGN_PREFIX`, die Lückenliste läuft über alle Callsigns.

Der Skill enthält die SQL-Abfrage, die diese Fälle findet. Die App wird **nicht** umgebaut — bei
vier Fällen wäre das ein eigenes Feature mit eigenem Design, kein Nebenprodukt.

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

## Offene Punkte (nicht blockierend)

- Der airportsdata-Belgienfehler ist **upstream nicht gemeldet**. Eigenes Thema.
- Legs über Track-Lücken zusammenführen (LKLB-Muster) — echte Design-Entscheidung mit Risiko: eine
  reale Zwischenlandung darf nie verschluckt werden. Eigenes Thema.
