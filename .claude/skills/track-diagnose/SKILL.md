---
name: track-diagnose
description: Use when working through the FriesenSpy Erkennungslücken list (/admin) or analyzing why a flight's departure/arrival airport was not recognized from GPS — triaging the whole list, diagnosing a single track where an airport seems missing or misplaced, or finding flights without a flight plan. Produces verdicts with evidence, never enters corrections.
---

# FriesenSpy — Track-Diagnose

## Überblick

Beantwortet: *Warum hängt dieser Flug an Platz X?* — für die ganze Liste oder einen Einzelfall.

**Erst triagieren, dann einzeln prüfen.** Die Lückenliste hatte am 2026-07-15 163 Fälle
(184 Enden, weil 29 Fälle beide Enden vermissen). **86,4 % davon sind rein mechanisch abzuhaken.**
Wer sie einzeln durchgeht, hört drei von vier Mal „Aufzeichnungslücke, nichts zu tun".

**Dieser Skill trägt nichts ein.** Er liefert Diagnose, Belege und ggf. einen konkreten
Vorschlag (ICAO, Koordinate, Radius, Grund). Das Eintragen macht der Nutzer über die Admin-UI —
jeder Write stößt einen vollen `rebuild_flight_cache` an, und genau die Fälle, die „klar"
aussahen, waren die falschen. Für die Triage gilt dasselbe: sie sortiert, sie entscheidet nicht.
Auch ein Sammelbefund „126× Fall E" wird vom Nutzer abgehakt.

**Nicht Teil dieses Skills:** das Vollaudit der gesamten Historie (Modus-Cluster über viele Flüge
je Platz). Andere Frage, andere Fallstricke.

## Die Asymmetrie — zuerst lesen

Ein **fehlender** Eintrag kostet eine unerkannte Strecke. Ein **falscher** Eintrag verschiebt
einen realen Flugplatz für *alle* Auswertungen (Statistik, Bummel, Kutter) — unbemerkt, weil
`icao_to_coords` brav weiter einen Treffer liefert. Die Fehler sind nicht gleich teuer.

**Im Zweifel wird nichts eingetragen.**

## Datenzugang (nur lesend)

```bash
ssh -i ~/.ssh/tsbot_server root@167.86.127.129 "sqlite3 -header -column /opt/friesenspy/data/friesenspy.db \"<SQL>\""
```

Stolpersteine:
- Der Host-Alias `friesenspy` **existiert nicht** — Verbindung über die IP.
- Key ist `~/.ssh/tsbot_server`, nicht der Default-Key.
- `flight_cache` hat **keine** Spalte `statsim_id`.
- Der API-Weg ist **kein** Ersatz: alle Endpoints verlangen Login, auch
  `/api/flights/statsim/{id}/track`.
- **Niemals schreiben.** Korrekturen laufen über die Admin-UI beim Nutzer.

## Ablauf A — Triage (die ganze Liste)

### A1. Export ziehen

Die Lückenliste **muss aus der App kommen**, nicht per SQL nachgebaut: `list_gps_detection_gaps`
ruft `canonicalize_legs` über die ganze Historie. Nachgebaut triagiert man eine andere Liste als
die, die im Admin steht.

```bash
ssh -i ~/.ssh/tsbot_server root@167.86.127.129 "docker exec friesenspy-friesenspy-1 python -c '
import json
from app import geo
from app.config import get_settings
from app.database import get_connection, list_gps_detection_gaps, list_custom_airports
conn = get_connection(get_settings().DB_PATH)
geo.set_custom_airports(list_custom_airports(conn))
out = []
for g in list_gps_detection_gaps(conn):
    sid = g.get("statsim_id")
    if not sid: continue
    rows = conn.execute("SELECT ts, latitude, longitude, altitude, groundspeed FROM statsim_position_history WHERE statsim_id=? ORDER BY ts", (sid,)).fetchall()
    if not rows: continue
    f, l = rows[0], rows[-1]
    out.append({"statsim_id": sid, "callsign": g["callsign"], "missing": g["missing"],
      "plan_departure": g["plan_departure"], "plan_arrival": g["plan_arrival"],
      "logon_time": g["logon_time"], "punkte": len(rows),
      "first": {"ts": f[0], "lat": f[1], "lon": f[2], "alt": f[3], "gs": f[4]},
      "last":  {"ts": l[0], "lat": l[1], "lon": l[2], "alt": l[3], "gs": l[4]}})
print(json.dumps(out))
'" > gaps.json
```

Dauert ~18 s, liefert ~75 KB für 163 Fälle.

> **`geo.set_custom_airports(...)` ist PFLICHT, nicht Deko.** `docker exec python -c` startet einen
> frischen Prozess; `geo._CUSTOM_AIRPORTS` wird sonst nie befüllt (das macht der Lifespan,
> `app/main.py:204`). Ohne die Zeile fehlen **sämtliche** Korrekturen: der erste Testlauf lieferte
> 199 statt 163 Fälle — 36 Phantom-Lücken an längst gefixten Plätzen (EDEN, EBBR, ELLX, EDDF).

> **Niemals die DB kopieren.** 42 MB mit Push-Subscriptions, Pilotennamen und Tokens; die Triage
> braucht davon nichts.

### A2. Triagieren

```bash
python -m scripts.triage_gaps gaps.json                 # Zusammenfassung + Kandidaten
python -m scripts.triage_gaps gaps.json --gruppe E      # eine Gruppe im Detail
```

### A3. Berichten

Trivialgruppen als **Sammelbefund** melden (nicht einzeln durchkauen), Kandidaten als Arbeitsvorrat
für Ablauf B. Stand 2026-07-15: 126× E, 19× zu dünn, 11× ZZZZ, 3× D — **25 Kandidaten**.

## Ablauf B — Einzelfall

### 1. Fall aufnehmen

Einstieg ist ein Kandidat aus der Triage oder eine Track-URL vom Nutzer:
`…/#tab=statistiken&track=<statsim_id>&src=statsim`.

```sql
SELECT * FROM statsim_cache WHERE statsim_id = <id>;
```

Liefert `departure`/`arrival` (das **Soll** aus dem Flugplan), `logon_time`, `duration_min`.

### 2. Track-Ränder ziehen

```sql
SELECT COUNT(*), MIN(ts), MAX(ts), MIN(altitude), MIN(groundspeed)
FROM statsim_position_history WHERE statsim_id = <id>;

SELECT ts, latitude, longitude, altitude, groundspeed
FROM statsim_position_history WHERE statsim_id = <id> ORDER BY ts LIMIT 10;

SELECT ts, latitude, longitude, altitude, groundspeed
FROM statsim_position_history WHERE statsim_id = <id> ORDER BY ts DESC LIMIT 10;
```

### 3. Aktuellen Custom-Stand prüfen

```sql
SELECT icao, lat, lon, elevation_ft, radius_km, reason FROM custom_airports ORDER BY icao;
```

Sonst schlägt man einen Eintrag vor, den es längst gibt.

### 4. Messen

```bash
python -m scripts.nearby_airports <lat> <lon> [--alt <ft MSL>] [--icao <Soll-Code>]
```

Das Werkzeug misst, es urteilt nicht. Es zeigt die nächsten Plätze laut **airportsdata** und
**OurAirports**, die Abweichung beider Quellen und — mit `--icao` — die Distanz zum Soll-Code,
jeweils gegen die importierten Detektor-Schwellen (4 km Radius, 1500 ft Spawn, 300 ft Boden).

### 5. Urteil nach der Prüfreihenfolge (unten) und Bericht an den Nutzer

## Prüfreihenfolge — nicht verhandelbar

**Schritt 0 — Gibt es an *diesem* Ende überhaupt einen Bodenpunkt?**
Je Ende, nicht je Track: Ein Track kann am Ziel sauber aufsetzen und am Start in der Luft
beginnen. Geprüft wird der Randpunkt, um den es geht.

**Höhe führt, Groundspeed hilft** — dieselbe Gewichtung wie im Detektor (`app/gps_legs.py:4`:
*„Höhe (AGL) ist das Leitsignal, Groundspeed nur sekundär — STOL/Heli fliegen langsam"*):

```
in_der_luft = (AGL > 300 ft)  ODER  (groundspeed >= 50 kt)
```

AGL gegen die Elevation des Soll-Platzes; fehlt der Code in beiden Quellen, gegen die des
nächstgelegenen. Beide Signale nötig, keines genügt: von 184 Enden erkennt **13 nur die Höhe**
(Groundspeed sagt fälschlich „Boden" — Wilga fliegt ~40 kt Reise), **5 nur die Groundspeed**.

Kein Bodenpunkt → **Fall E**, Ende.

**Vorgelagert: hat der Track überhaupt genug Punkte?** Unter 3 Samples ist kein Zustandswechsel
möglich und jede Aussage bedeutungslos — auch eine gemessene. Sechs von neun vermeintlichen
D-Befunden waren Ein-Punkt-Tracks.

> Beispiel EDDH (Track 28133172): erster Punkt 2209 ft, 217 kt, 15 km vom Platz — der VATSIM-
> Logon lag 9 Sekunden davor, der Pilot verband sich im Steigflug. Es gab nie einen Startpunkt;
> jede Radiusüberlegung war gegenstandslos.

**Schritt 1 — Wohin gehört der Bodenpunkt?**
Die Umkehrfrage: nicht „passt der Punkt zum Code", sondern „welcher Platz liegt am nächsten",
in **beiden** Quellen. Anderer Platz unter 1 km → **Fall D**, Ende.

> **Warum diese Reihenfolge zwingend ist — der EDHX-Beleg:** `EDHX` steht **nicht in
> airportsdata** und erfüllt damit *formal das Kriterium von Fall A*. Wer bei Schritt 2
> einsteigt, trägt einen Platz ein. Schritt 1 zeigt: der Bodenpunkt liegt 0,16 km von **EDXH**
> (Helgoland-Düne) — der Code war verdreht. `EDHX` existiert real, aber als *Bad Bramstedt
> Heliport*, 132,70 km entfernt. **Fall D schlägt Fall A**, immer.

**Schritt 2 — Erst jetzt der Code.** Siehe Fallliste.

**Merksatz:** Erst fragen, ob es einen Bodenpunkt gibt, dann wohin er gehört, und erst zuletzt,
was mit dem Code los ist.

## Die sechs Fälle

| Fall | Befund | Handlung |
|---|---|---|
| **A** | Code fehlt in airportsdata — **und Schritt 1 fand keinen anderen Platz** | Ergänzung, Grund `Fehlt in airportsdata` |
| **B** | Code steht drin (> 3 km weg), OurAirports liegt auf dem Punkt | Koordinaten-Override, Grund `airportsdata-Koordinate falsch` |
| **C** | Koordinate stimmt (AD deckt sich mit OA), echter Bodenpunkt trotzdem außerhalb 4 km | Radius-Override, Grund `Abhebepunkt außerhalb Standardradius` |
| **D** | Der Bodenpunkt gehört zu einem *anderen* Platz | **nichts eintragen** |
| **E** | An diesem Ende gibt es keinen Bodenpunkt | **nichts eintragen** |
| **F** | Quellen widersprechen sich, nicht auflösbar | **nichts eintragen**, Befund festhalten |

**Fall A hat zwei Zweige:**
- Echter ICAO-Code, den airportsdata nicht kennt → Ergänzung mit diesem Code.
- **Gar kein ICAO-Code** → Pseudo-Code nach dem etablierten Muster (`BZWIROS`, `ZZSALZ`,
  `EXHB`, `CML5`). Ein solcher Code ist **frei erfunden und muss vom Nutzer kommen** — nie
  selbst einen ausdenken. Der Grund bleibt `Fehlt in airportsdata` (kein eigener Grund für
  Platzhalter, siehe `docs/superpowers/specs/2026-07-15-flugplatz-grund-design.md`).

**Fall B — der Belgien-Fund:** airportsdata verortet belgische/luxemburgische Plätze
systematisch falsch (34 % der BE-Codes > 3 km, alle nach Südwesten verschoben; Deutschland:
1 von 452). „Nicht erkannt" ist dort meist „falsch verortet".

**Fall C braucht eine Plausibilitätsprüfung:** Ein Flugplatz misst selten mehr als sechs
Kilometer. Die Nachbarliste zeigt, welche Plätze ein größerer Radius mitverschluckt — das ist
der Preis des Overrides. Bestehende Radius-Overrides: `EDDF` und `EHAM`, je 10 km.

**Fall D fasst zwei Ursachen zusammen:** Flugplan-Tippfehler (EDHX → EDXH) und schlichte
Umplanung (ETUO: Pilot stand in Bad Gandersheim, 118 km vom Flugplan-Ziel). Die Unterscheidung
erklärt, ändert aber nichts: in beiden Fällen ist der Platz richtig verortet und der Flugplan
das Problem.

## Flüge ohne Flugplan

FriesenSpy ist seit #23 **GPS-only** — Flüge ohne Flugplan werden gewertet. Die
Erkennungslücken-Liste zeigt sie aber **nie**: `list_gps_detection_gaps`
(`app/database.py:4683`) verlangt `missing_dep = not gps_departure and plan_departure`. Ohne
Soll-Angabe fällt der Fall raus.

So findet man sie:

```sql
SELECT cid, callsign, aircraft, logon_time, logoff_time, duration_min, source,
       COALESCE(gps_departure,'-') AS gps_dep, COALESCE(gps_arrival,'-') AS gps_arr,
       COALESCE(plan_departure,'-') AS plan_dep, COALESCE(plan_arrival,'-') AS plan_arr
FROM flight_cache
WHERE ((gps_departure IS NULL OR gps_departure='') AND (plan_departure IS NULL OR plan_departure=''))
   OR ((gps_arrival IS NULL OR gps_arrival='') AND (plan_arrival IS NULL OR plan_arrival='') AND connection_closed=1)
ORDER BY logon_time;
```

Stand 2026-07-15: 2104 FRS-Legs, 101 sichtbare Lücken, **vier blinde Fälle**. Untergrenzwert —
`flight_cache` filtert auf `CALLSIGN_PREFIX`, die Lückenliste läuft über alle Callsigns.

Ohne Flugplan verschiebt sich zweierlei: **Fall D entfällt** (wo kein Soll ist, kann nichts
abweichen), und **Fall A wird zur Recherche** — kein Code sagt, wie der Platz heißt. Dann
bleiben OurAirports und Websuche.

## Regeln

- **Keine Zahl aus dem Gedächtnis.** Messen oder recherchieren, Quelle nennen. Der Nutzer hat
  das ausdrücklich eingefordert; ein aus dem Gedächtnis genannter Elevation-Wert war real
  falsch (64 statt 55 ft).
- **Nie einen Pseudo-Code erfinden.** Der kommt vom Nutzer.
- **Nie in die Produktions-DB schreiben.**
- Bei Massen-Einträgen (Nutzer): jeder Write stößt einen vollen `rebuild_flight_cache` an.
  Mehrere Writes in Folge → parallele Rebuilds, die sich überschreiben (Zeitstempel laufen
  rückwärts). Danach einen einzelnen Write nachschieben und den Rebuild abwarten, sonst misst
  man Zwischenzustände.

## Referenzfälle

| Fall | Punkt | Befund |
|---|---|---|
| EBKT | `50.82005 / 3.2163` | AD 37,20 km / OA 0,49 km → **B** |
| EDHX | `54.18665 / 7.91488` | AD fehlt, OA 132,70 km, EDXH 0,16 km → **D** |
| ETUO | `51.85449 / 10.02288` | AD 118,05 km, OA fehlt, EDVA 0,19 km → **D** |
| EDDH | `53.49527 / 10.00085`, 2209 ft | 15,05 km, AGL 2156 ft → **E** |
| LKLB | Track 28227871 | 101-min-Aufzeichnungslücke, beide Enden airborne → **E** |
| SLSM | — | AD näher als der Override → **F** |
