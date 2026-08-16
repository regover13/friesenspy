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

- **Im Stand ist die Latenz gegenstandslos.** Das ist der beste Moment überhaupt, besser als
  Rollen: Bei Geschwindigkeit null ist eine vierzig Sekunden alte Position **exakt richtig**.
  Die Zuordnung gelingt dort auf Meter statt auf Kilometer. Und da die meisten nach dem
  Einloggen minutenlang stehen, entsteht hier der Großteil aller Zuordnungen — allein über die
  Position, ohne jedes weitere Merkmal.
- **Piloten erscheinen nacheinander.** Ein neues Objekt im Simulator und ein neues Callsign
  bei VATSIM, mit dem erwarteten Zeitversatz — ein starkes Signal.
- **Am Boden ist die Latenz auch in Bewegung harmlos.** 20 kt × 45 s = 460 m, statt 10 km beim
  Airliner.
- **Bewegungsbeginn ist ein Ereignis, kein Zustand.** Rollt im Simulator genau ein Flugzeug an
  und vierzig Sekunden später bei VATSIM genau eines, ist die Zuordnung sicher — unabhängig
  von der Entfernung der Symbole. Dasselbe gilt fürs Abheben.
- **Anflug von außen**: Wer den Start nicht mitbekommen hat (zu weit weg), begegnet der
  Maschine später allein im Reiseflug — dort ist sie ohnehin eindeutig.

**Bis die Platzrunde kommt, steht die Zuordnung längst.** Dort wird sie nur noch gehalten,
nicht gesucht. Damit verschwindet der schwierigste Fall aus der Problemstellung.

### Ausschluss ist das zweite Eindeutigkeitskriterium

Eindeutigkeit entsteht nicht nur aus Nähe, sondern auch daraus, dass **nichts anderes übrig
bleibt**. Bleibt nach allen bereits getroffenen Zuordnungen genau ein unzugeordnetes
Sim-Objekt und genau ein unzugeordneter VATSIM-Eintrag im Gebiet, gehören sie zusammen — ohne
jeden Positionsvergleich.

Das trägt sogar den Fall, der vorher als unlösbar galt (Nutzer, 16.08.2026): *Loggt sich der
fünfte mitten in der Platzrunde ein, sind die anderen vier längst bekannt — dann ist auch
Nummer fünf klar.* Die Reihenfolge der Zuordnungen arbeitet also für uns: Jede getroffene
Zuordnung macht die nächste leichter.

**Konsequenz für die Umsetzung:** Erst alle sicheren Zuordnungen über Nähe treffen, dann
prüfen, ob auf beiden Seiten genau einer übrig ist. Nicht umgekehrt, und nicht in einem
Durchgang vermischt.

## Verfahren

1. **Zuordnung suchen**, solange ein Sim-Eintrag keine hat — aber sie nur **übernehmen, wenn
   sie eindeutig ist**: genau ein Kandidat innerhalb der Schranken. Zwei Kandidaten heißen:
   nicht zuordnen, später erneut versuchen. Danach der Ausschluss: bleibt beidseitig genau
   einer übrig, gehören sie zusammen.
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

## Gemessen am 16.08.2026 — die Zahlen stehen

### Latenz: 29 Sekunden

| | |
|---|---|
| Median | **28,9 s** |
| Spanne | 27,2 – 30,5 s |
| Proben | 12, alle mit Kursabweichung ≤ 9° |

Gemessen am eigenen Flugzeug (`_latenzProbeNehmen`): Abstand zwischen Sim-Position und
gemeldeter VATSIM-Position, geteilt durch die eigene Geschwindigkeit. Belastbar ist die
Messung, weil der Abstand **mit der Geschwindigkeit mitwächst** — 1494 m bei 97 kt, 1714 m bei
113 kt; nachgerechnet ergibt 113 kt × 29 s = 1685 m.

> Ein erster Versuch lieferte 29,3 s bei einer Spanne von 24,8–39,7 s — **zufällig fast
> derselbe Wert, aber wertlos**: Der Messflug war eine Platzrunde, und dort misst der Abstand
> die Sehne statt der Strecke. Er blieb bei 1,2–1,4 km, obwohl die Geschwindigkeit zwischen 60
> und 96 kt schwankte. Seitdem zählen nur Proben mit stabilem Kurs (`_LATENZ_MAX_KURSDIFF`).
> **Lehre:** Ein plausibler Wert ist noch kein gemessener. Erst das erwartete *Verhalten* der
> Messgröße — hier das Mitwachsen mit der Geschwindigkeit — macht sie belastbar.

Damit ist die frühere Annahme „bis zu einer Minute" **halbiert**.

### Die `uId` überlebt keine Sitzung — belegt

| | Anzahl | Wertebereich |
|---|---|---|
| Sitzung 1 (16:37) | 14 | 169,5 – 170,5 Mio |
| Sitzung 2 (17:15, nach Neustart) | 20 | 102,5 – 106,3 Mio |
| **Gemeinsam** | **0** | — |

Keine einzige Übereinstimmung, die Bereiche liegen komplett auseinander, und innerhalb einer
Sitzung stehen die Werte in exakten Schritten von 16384 — ein Handle-Muster. **Eine
sitzungsübergreifende Speicherung ist damit ausgeschlossen.** Sie wäre nicht nur nutzlos,
sondern gefährlich: Eine wiederverwendete ID hängte ein falsches Rufzeichen an ein fremdes
Flugzeug und verletzte damit das oberste Akzeptanzkriterium.

Die Zuordnung gilt also **für die laufende Sitzung**. Das reicht — nötig ist sie ohnehin nur
einmal pro Flug.

### Zwei Nebenbefunde

- **vPilot spawnt fast alles**: Sim 14 zu VATSIM 14, und Sim 20 zu VATSIM 21. Der fehlende
  A320 vom 15.08. war die Ausnahme, nicht die Regel.
- **Der Sim-Horizont reicht mindestens 68 km** — kein Engpass.
- **`__Type` ist `JS_NPCPlane`** für jedes fremde Flugzeug, `name` und `plane_model_icao` sind
  leer. Keine Unterscheidung zwischen KI-Verkehr und vPilot, keine Identität. Damit ist
  endgültig belegt: Rufzeichen und Muster können nur von VATSIM kommen.

## Zwei Schranken, zwei Aufgaben — nicht eine

Das ist die zentrale Einsicht aus der Diskussion (Nutzer, 16.08.2026), und sie räumt mit der
bisherigen Herangehensweise auf: Es gibt **keine** Schranke, die beides leisten muss.

### A) Erstzuordnung — hier trägt die Eindeutigkeit, nicht die Enge

Ist genau ein Kandidat da, ist er es — ob er 2 oder 7 km entfernt liegt, ändert daran nichts.
Eine enge Schranke erhöht die Sicherheit **nicht**, sie verhindert nur, dass der Partner
überhaupt gefunden wird. Sie darf also großzügig sein; getragen wird die Entscheidung vom
„genau einer" und vom Ausschlussverfahren.

Die Höhe ist hier entsprechend unkritisch — sie muss die Zuordnung nicht tragen.

### B) Lösen — hier wird gerechnet, nicht geschrankt

**Nach dem Merken kann Flackern nur noch an einer einzigen Stelle entstehen: beim Lösen.**
Deshalb ist das die Schranke, auf die es ankommt — und sie lässt sich ausrechnen, statt sie zu
raten:

```
erwarteter Abstand   = GS  × 29 s        (aus den Sim-Werten, live)
erwartete Höhendiff. = VS  × 29 s        (VS aus den Sim-Höhen ableitbar)
```

Geprüft wird nicht „ist die Abweichung kleiner als X", sondern **„passt die Abweichung zu dem,
was dieses Flugzeug gerade tut"**. Ein sinkender Airliner mit 1600 ft Differenz ist damit
unauffällig — genau das kommt heraus, wenn man seine Sinkrate mit 29 Sekunden multipliziert.
Es gibt keinen Grenzfall mehr, an dem etwas kippen kann.

**Und gelöst wird erst nach mehrfachem Verstoß in Folge**, nicht beim ersten Ausreißer. Sonst
ist das Flackern durch die Hintertür zurück.

## Offene Punkte

Die beiden ursprünglich offenen Fragen — Lebensdauer der `uId` und Größe der Latenz — sind am
16.08.2026 **gemessen und beantwortet** (s. oben). Was bleibt, ist Feinarbeit an der
Umsetzung:

### 1. Wie oft muss eine Zuordnung verletzt werden, bevor sie fällt?

Ein einzelner Ausreißer darf sie nicht lösen, sonst ist das Flackern zurück. Ein zu träges
Lösen hält dagegen eine falsche Zuordnung zu lange. Vorschlag zum Ausprobieren: drei bis fünf
Takte in Folge deutlich außerhalb der Erwartung. Im Flug zu beobachten, nicht am Schreibtisch
zu entscheiden.

### 2. Wie viel Toleranz um die berechnete Erwartung?

`GS × 29 s` ist der Sollwert, nicht die Grenze — Wind, Kurven und die Streuung der Latenz
(±1,5 s gemessen) kommen dazu. Ein Faktor auf den Erwartungswert ist vermutlich robuster als
ein fester Zuschlag, weil er mit der Geschwindigkeit mitwächst.

### 3. Vertikalgeschwindigkeit aus den Sim-Höhen

Für die erwartete Höhendifferenz nötig. Aus zwei aufeinanderfolgenden Sim-Meldungen ableitbar
(1 Hz), muss aber geglättet werden — dieselbe Aufgabe, die das Panel beim Ground Speed schon
löst (`verkehrGsAbleiten`, exponentiell mit der Zeitkonstante des SDK). Dort abschauen, nicht
neu erfinden.

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
- **Keine sitzungsübergreifende Speicherung.** Gemessen und erledigt: Die `uId` überlebt keinen
  Neustart (0 von 14 bzw. 20 Kennungen stimmten überein).
- **Keine feste Höhenschranke als Zuordnungskriterium.** Sie muss die Erstzuordnung nicht
  tragen, und beim Lösen wird gerechnet statt geschrankt.

## Akzeptanzkriterien

1. Ein sinkender Airliner behält sein Schild — kein Trennen und Zusammenfallen im Sekundentakt.
2. Am FriesenFlieger-Freitag steht **kein Friese doppelt** auf der Karte.
3. **Jedes Symbol trägt überall — nicht nur in der Platzrunde — entweder das richtige Callsign
   und/oder Muster oder gar keines. Nie falsche.** (Nutzer-Formulierung, 16.08.2026.)

   Das ist das oberste Kriterium und weiter gefasst als „Callsign in der Platzrunde": Es
   umfasst **alle** Identitätsangaben und gilt in **jeder** Fluglage. Eine falsche Angabe ist
   schlimmer als gar keine, weil man ihr ansieht, dass sie da ist — einer Lücke sieht man an,
   dass etwas fehlt.
4. Ein Flugzeug, das der Simulator kennt, erscheint immer, auch ohne Zuordnung.
5. Ein Flugzeug, das nur VATSIM kennt, erscheint weiterhin (vPilot spawnt nicht jede Maschine).
6. Auf der Webseite ändert sich nichts.
