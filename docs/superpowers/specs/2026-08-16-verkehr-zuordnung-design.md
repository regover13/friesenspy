# Zuordnung von Sim-Verkehr und VATSIM — Design

**Stand:** 16.08.2026 · **Betrifft:** nur das Kniebrett (EFB-Panel) · **Vorgänger:**
`2026-08-15-sim-verkehr-design.md`

## Warum

Seit v13.2.0 führt die Karte im Kniebrett zwei Quellen zusammen: Der Simulator liefert die
Bewegung (jede Sekunde gemessen), VATSIM die Identität (Rufzeichen, Muster, Flugplan) — der
Simulator liefert `name` und `plane_model_icao` leer, das ist gemessen und deckt sich mit
[DevSupport 13002](https://devsupport.flightsimulator.com/t/js-npcplane-parameter-name-always-empty-msfs2020-2024/13002).

Die Zuordnung geschieht heute **in jedem Takt neu**, allein über Position und Höhe. Das
funktioniert nicht:

| Beobachtung | Ursache |
|---|---|
| Zwei Schilder an einem Airliner (16.08., VR-Flug) | Verglichen wurde gegen die gemeldete statt die fortgerechnete Position (behoben in v13.3.1) |
| Label trennt und fällt zusammen, im Sekundentakt (16.08.) | Sinkendes Flugzeug: Sim `FL131`, VATSIM `FL147` — 1600 ft Differenz bei 1500 ft Schranke. Der Grenzfall flackert |

**Die gemeinsame Ursache ist die Latenz.** Eine VATSIM-Position durchläuft Piloten-Client,
VATSIM-Netz und unseren Poller; sie hinkt bis zu einer Minute hinterher — der Abruftakt von
15 s sagt darüber nichts. Bei 440 kt sind das über 10 km; bei 2000 ft/min Sinkrate 1600 ft.
Positions- und Höhenvergleich sind damit beide latenzbehaftet.

**Schranken zu justieren führt in die Irre.** Zu jedem Wert gibt es einen Grenzfall, und dort
flackert es. Der Fehler liegt nicht in der Größe der Schranke, sondern darin, die Frage
überhaupt jede Sekunde neu zu stellen.

## Entscheidungen des Nutzers (16.08.2026)

Diese sind gesetzt und stehen nicht mehr zur Diskussion:

1. **Position schlägt Identität.** „Es ist wichtiger zu wissen, wo sich ein anderes Flugzeug
   aktuell aufhält, als zu wissen wer oder was es ist." Im Zweifel gilt die Sim-Position, auch
   ohne Rufzeichen.
2. **Bei Mehrdeutigkeit nicht raten, sondern weglassen.** Kein Rufzeichen ist besser als ein
   falsches — erst recht an einem Flugzeug in der eigenen Platzrunde.
3. **Zuordnung festhalten**, statt sie in jedem Takt neu zu suchen.
4. **Kein `?` mehr** am Symbol, wo das Muster fehlt (umgesetzt in v13.3.2).
5. **Nur das Kniebrett.** Auf der Webseite gibt es keinen Sim-Verkehr, also kein Matching und
   kein Problem.

## Der Kern: früh zuordnen, nicht ständig

Der entscheidende Einwand kam vom Nutzer: **Wir starten nicht in der Platzrunde.** Ein Flug
beginnt mit dem Einloggen, dann Rollen, dann Start — und diese Phasen liefern viel bessere
Gelegenheiten als die Platzrunde selbst:

- **Piloten erscheinen nacheinander.** Ein neues Objekt im Simulator und ein neues Callsign
  bei VATSIM, mit dem erwarteten Zeitversatz — das ist ein starkes Signal.
- **Am Boden ist die Latenz fast harmlos.** 20 kt × 45 s = 460 m, statt 10 km beim Airliner.
  Die Positionspaarung ist dort auf ein paar hundert Meter genau.
- **Bewegungsbeginn ist ein Ereignis, kein Zustand.** Rollt im Simulator genau ein Flugzeug an
  und vierzig Sekunden später bei VATSIM genau eines, ist die Zuordnung sicher — unabhängig
  von der Entfernung der Symbole. Dasselbe gilt fürs Abheben.
- **Anflug von außen**: ein einzelnes Flugzeug, das sich nähert, ist ohnehin eindeutig.

**Bis die Platzrunde kommt, steht die Zuordnung längst.** Dort wird sie nur noch gehalten,
nicht gesucht. Damit verschwindet der schwierigste Fall aus der Problemstellung.

## Verfahren

1. **Zuordnung suchen**, solange ein Sim-Eintrag keine hat — aber sie nur **übernehmen, wenn
   sie eindeutig ist**: genau ein Kandidat innerhalb der Schranken. Zwei Kandidaten heißen:
   nicht zuordnen, später erneut versuchen.
2. **Zuordnung halten**, sobald sie steht — geschlüsselt über die `uId`. Kein Neuvergleich pro
   Takt, kein Flackern, kein Kippen an einer Grenze.
3. **Zuordnung lösen**, wenn eine Quelle das Flugzeug nicht mehr meldet oder der Abstand
   **dauerhaft** unplausibel wird (nicht bei einem einzelnen Ausreißer — sonst ist das
   Flackern zurück).
4. **Ohne Zuordnung**: Sim-Symbol zeigen, ohne Rufzeichen und ohne Muster.

### Friesen und Fremdverkehr sind verschiedene Situationen

Nicht in der Darstellung — die ist längst getrennt (blau/grau, andere Silhouette) —, sondern
im Verfahren:

| | Friesen | Fremdverkehr |
|---|---|---|
| Vergleichsdaten | `liveData`, mit Callsign und Position | `/api/traffic` |
| Anzahl | wenige | viele |
| Typische Lage | dicht beieinander, langsam, am selben Platz | einzeln, schnell |
| Zuordnung | schwierig, Datenlage gut | leichter, Datenlage schlechter |

**Für die Friesen ist die Lösung besser als bei Fremdverkehr:** Steht die Zuordnung, wird der
**vorhandene Friesen-Marker auf die Sim-Position gesetzt**. Er behält sein Callsign *und*
bekommt die genaue Position. Kein zweites Symbol, kein Verzicht auf die Identität.

> ⚠️ Ohne diesen Schritt steht am FriesenFlieger-Freitag **jeder Friese doppelt** auf der
> Karte: einmal blau mit Callsign aus `liveData`, einmal grau und namenlos aus dem Simulator.
> `/api/traffic` liefert die Friesen bewusst nicht mit (`app/main.py`, Präfix-Filter), also
> findet ihre Sim-Meldung dort nie einen Partner. Das ist strukturell und passiert bei jedem
> gemeinsamen Flug.

## Offene Punkte — vor der Umsetzung zu klären

### 1. Überlebt die `uId` eine Sitzung?

**Vermutung: nein.** Sie ist eine Laufzeit-Objekt-ID, die der Simulator beim Erzeugen vergibt;
Asobos Traffic-Manager benutzt sie als Schlüssel *innerhalb* einer Sitzung. Freigewordene IDs
können wiederverwendet werden — eine dauerhaft gespeicherte Zuordnung „uId = FRS49" würde dann
irgendwann ein falsches Callsign an ein fremdes Flugzeug hängen.

Der Nutzer hatte auf eine sitzungsübergreifende Speicherung gehofft („irgendwann kennen wir
alle Friesen"). **Das trägt nicht**, solange nicht gemessen ist.

**Messung:** Die `uId`s zweier Sitzungen desselben Flugzeugs vergleichen — eine Zeile in der
Panel-Diagnose. Zwei Flüge, dann ist es entschieden. Bis dahin gilt die Zuordnung **nur
innerhalb der Sitzung**, was ausreicht: Nötig ist sie ohnehin nur einmal pro Flug.

### 2. Wie groß ist die Latenz wirklich?

Heute steht „bis zu einer Minute" — geschätzt, nicht gemessen. Zwei unabhängige Messwege:

- **Eigenes Flugzeug**: Es steht in beiden Quellen und ist eindeutig identifiziert. Der Abstand
  zwischen Sim-Position und fortgerechneter VATSIM-Position *ist* der Fehler.
- **Höhendifferenz im Steig-/Sinkflug**: geteilt durch die Sinkrate ergibt die Latenz. Die
  Beobachtung vom 16.08. (1600 ft bei ~2000 ft/min) ergibt rund 48 s.

Steht die Konstante, lassen sich Position **und Höhe** fortrechnen statt großzügig zu
schranken.

### 3. Schranken

Erst festlegen, wenn Punkt 2 gemessen ist. Grundsatz: Sie sollen die Zuordnung **ermöglichen**,
nicht sie tragen — getragen wird sie von Eindeutigkeit und vom Festhalten.

## Was ausdrücklich nicht gemacht wird

- **Kein Kursvergleich.** Der gemeldete Kurs ist genauso alt wie die Position. In der
  Platzrunde ist er nach 40 s womöglich der exakte Gegenkurs — ein Kursvergleich würde die
  richtige Zuordnung dann aktiv ablehnen (Nutzer-Einwand, und er ist zwingend).
- **Kein WASM-Modul.** Little Navmap kommt an die Rufzeichen, weil es SimConnect benutzt — dort
  tragen die von vPilot mit `SimConnect_AICreateNonATCAircraft` erzeugten Objekte ihre
  `ATC ID`. Über den JS-Weg ist das nicht zu bekommen: Asobos gesamter ausgelieferter Code
  kennt genau **einen** traffic-bezogenen Aufruf (`GET_AIR_TRAFFIC`), keine AI-SimVars, keine
  Abfrage über die `uId` (durchsucht am 16.08.2026). Ein WASM-Modul wäre ein anderes Kaliber:
  eigene Toolchain, eigener Build, im Fehlerfall keine Diagnose über den Panel-Kanal.
- **Keine sitzungsübergreifende Speicherung**, bis Punkt 1 gemessen ist.

## Akzeptanzkriterien

1. Ein sinkender Airliner behält sein Schild — kein Trennen und Zusammenfallen im Sekundentakt.
2. Am FriesenFlieger-Freitag steht **kein Friese doppelt** auf der Karte.
3. Fliegen fünf Friesen dieselbe Platzrunde, trägt jedes Symbol entweder das **richtige**
   Callsign oder gar keines — nie ein falsches.
4. Ein Flugzeug, das der Simulator kennt, erscheint immer, auch ohne Zuordnung.
5. Ein Flugzeug, das nur VATSIM kennt, erscheint weiterhin (vPilot spawnt nicht jede Maschine).
6. Auf der Webseite ändert sich nichts.
