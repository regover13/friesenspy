# Ergebnis des Probeflugs

**Gemessen:** 11.09.2026 am Simulator-Rechner
**Simulator:** MSFS 2024 (`Microsoft.Limitless` 1.8.16.0), laufend seit 07:46:48
**Antwort auf `UEBERGABE.md`**

---

## 1. Die Antwort

**Ja.** `SimConnect_AICreateSimulatedObject` setzt ein mitgeliefertes Boot im laufenden Flug
an eine frei gewählte Koordinate, es wird **vollständig gezeichnet** und es **bleibt liegen** —
ohne Drift, ohne dass die KI-Engine es abräumt.

**Mit einer Einschränkung, die den Zuschnitt des Pakets bestimmt:**

> **Das Objekt lebt nur, solange die SimConnect-Verbindung offen ist.**
> Nach `SimConnect_Close` ist die Objekt-ID sofort `UNRECOGNIZED_ID`.

Ein Spawner, der kurz läuft, seine Objekte setzt und sich beendet, hinterlässt **nichts**. Er
muss durchlaufen, solange jemand die Objekte sehen soll. Das ist keine Absage — es heißt nur,
dass der Kieker-Spawner ein mitlaufender Begleitprozess wird, kein Einmal-Aufruf.

**Zweifach belegt, und das war nötig.** `EXCEPTION 3 — UNRECOGNIZED_ID` allein hätte zweierlei
heißen können: das Objekt ist weg, *oder* es existiert weiter und ist einem neuen Client nur
nicht unter derselben ID bekannt. Der Unterschied entscheidet über den Zuschnitt des Pakets,
also wurde er nachgesehen: Nach dem Ende beider Prozesse waren **Kutter und Kreuzfahrtschiff
sichtbar verschwunden**, an einer Stelle, an der sie Minuten zuvor noch auf Screenshots lagen.
Es ist die erste Lesart.

### Was belegt ist und wodurch

| Frage | Antwort | Beleg |
|---|---|---|
| Wird der Aufruf angenommen? | ja | Objekt-IDs 50937856 / 103202816 / 103202817, keine Exception |
| Wird wirklich etwas gezeichnet? | **ja** | Screenshot 08:15:06, Boot in voller Textur mit Schatten |
| Ist das Gesehene auch unseres? | **ja** | Gegenprobe: `CruiseShip01` erscheint auf Zuruf 150 m daneben |
| Bleibt es liegen? | **ja** | 180 Lagemeldungen über 180 s, Koordinate auf 5 Nachkommastellen unverändert |
| Liegt es auf der Oberfläche? | ja, `OnGround=1` genügt | Land 2,4 ft, Wasser 0,0 ft — der Sim setzt selbst auf |
| Schwimmt es richtig? | **ja** | Screenshot 08:36:07 — Kutter auf der Wasserlinie, mit Schatten im Wasser |
| Überlebt es die Verbindung? | **nein** | `EXCEPTION 3` — **und beide Schiffe waren nach Prozessende sichtbar weg** |
| Gibt es eine Entfernungsgrenze? | **nein, beim Anlegen nicht** | bis 10.000 km angenommen, s. Abschnitt „Reality Bubble" |

## 2. Rohe Ausgabe

### Lauf 1 — ohne geladenen Flug (Vorprobe)

Die eigene Position kam als `0.00000 / 90.00032` zurück — der Platzhalter des Hauptmenüs.
**Bemerkenswert: der Aufruf funktionierte trotzdem**, der Sim legte auch ohne geladenen Flug
ein Objekt an.

```
SimConnect.dll: C:\MSFS 2024 SDK\SimConnect SDK\lib\SimConnect.dll
SimConnect_Open: verbunden.
  Flugzeug steht bei -0.00000 / 90.00032, 221 ft.
  Ziel 200 m oestlich davon: -0.00000 / 90.00212
AICreateSimulatedObject: titel="Boat01" bei -0.0000/90.0021, 0 ft, OnGround=1 ...
Warte 10 s auf die Antwort des Simulators ...

  ERFOLG: Objekt-ID 50937856 (Anfrage 4711).
  t=+   0.3s  -0.00000 / 90.00212     17.3 ft   (Objekt 50937856 lebt)
  t=+  11.3s  -0.00000 / 90.00212     17.3 ft   (Objekt 50937856 lebt)
  DURCHGEHEND DA: 20 Lagemeldungen ueber 20s, bis zum Schluss.
  Verbindung geschlossen.

  Nachprobe: neu verbinden und dieselbe Objekt-ID abfragen ...
  WEG: EXCEPTION 3 -- UNRECOGNIZED_ID
  Das Objekt lebte nur, solange die Verbindung offen war.
```

### Lauf 2 — Flug geladen, Wangerooge EDWG, Boot an Land

```
SimConnect.dll: C:\MSFS 2024 SDK\SimConnect SDK\lib\SimConnect.dll
SimConnect_Open: verbunden.
  Flugzeug steht bei 53.78073 / 7.91414, 4 ft.
  Ziel 200 m oestlich davon: 53.78073 / 7.91718
AICreateSimulatedObject: titel="Boat01" bei 53.7807/7.9172, 0 ft, OnGround=1 ...
Warte 10 s auf die Antwort des Simulators ...

  ERFOLG: Objekt-ID 103202816 (Anfrage 4711).
  Der Simulator hat das Objekt angelegt.

  t=+   0.6s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+  10.6s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+  20.6s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+  31.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+  42.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+  52.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+  63.6s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+  74.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+  85.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+  95.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+ 105.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+ 116.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+ 126.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+ 136.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+ 147.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+ 157.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+ 168.5s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)
  t=+ 178.6s  53.78073 / 7.91718      2.4 ft   (Objekt 103202816 lebt)

  DURCHGEHEND DA: 180 Lagemeldungen ueber 180s, bis zum Schluss.
  Verbindung geschlossen.

  Nachprobe: neu verbinden und dieselbe Objekt-ID abfragen ...
  WEG: EXCEPTION 3 -- UNRECOGNIZED_ID
  Das Objekt lebte nur, solange die Verbindung offen war.
```

**Sichtbestätigung:** Screenshot vom 11.09.2026, 08:15:06 — ein weiß-blaues Motorboot mit
Aufbau und Reling, voll texturiert, korrekt beleuchtet und mit Schattenwurf, im Gras auf
Wangerooge. Kein Platzhalter, kein fehlendes Modell.

### Lauf 3 — dasselbe auf dem Wasser, 1,6 km nördlich EDWG

```
AICreateSimulatedObject: titel="FishingBoat" bei 53.7955/7.9142, 0 ft, OnGround=1 ...
  ERFOLG: Objekt-ID 103202817 (Anfrage 4711).
  t=+   0.3s  53.79550 / 7.91420      0.0 ft   (Objekt 103202817 lebt)
  ... unveraendert ...
  t=+ 111.4s  53.79550 / 7.91420      0.0 ft   (Objekt 103202817 lebt)
  DURCHGEHEND DA: 120 Lagemeldungen ueber 120s, bis zum Schluss.
```

Land 2,4 ft, Wasser 0,0 ft — bei identischem Aufruf. `OnGround=1` genügt, die Höhe muss nicht
berechnet werden.

**Sichtbestätigung:** Screenshot 08:36:07 — ein Fischkutter liegt auf der Wasserlinie, mit
Schattenwurf ins Wasser. Nicht darüber schwebend, nicht versunken.

### Gegenprobe — ist das überhaupt unser Objekt?

Der Nutzer hat zu Recht eingewandt, dass MSFS 2024 **eigenen Schiffsverkehr** hat; auf dem
Screenshot segelt im Hintergrund ein Boot, das niemand gesetzt hat. Ein Kutter in der Nordsee
beweist also erst einmal gar nichts.

Gegenprobe: Bei laufendem Kutter ein **`CruiseShip01` 150 m westlich daneben** gesetzt
(`53.79550 / 7.91192`, Objekt-ID 103907331).

```
  ERFOLG: Objekt-ID 103907331 (Anfrage 4711).
  t=+   1.0s  53.79550 / 7.91192      0.2 ft   (Objekt 103907331 lebt)
  t=+  12.0s  53.79550 / 7.91192     -0.0 ft   (Objekt 103907331 lebt)
```

Screenshot 08:37:39 zeigt beide nebeneinander: ein Kreuzfahrtschiff und daneben der Kutter,
beide mit Spiegelung auf der Wasseroberfläche. Ein Kreuzfahrtschiff, das auf Zuruf an einer
vorher genannten Koordinate erscheint, ist kein Zufallsverkehr.

**Damit ist belegt, was eine Objekt-ID allein nie belegt hätte:** Der Simulator führt das
Objekt nicht nur im Register, er zeichnet es auch.

## Die Reality Bubble — es gibt keine Entfernungsgrenze beim Anlegen

Erwartet war eine Grenze, jenseits derer `EXCEPTION 33 — OBJECT_OUTSIDE_REALITY_BUBBLE` kommt.
**Sie wurde nicht gefunden.** Elf Läufe, jeweils östlich des Flugzeugs auf Wangerooge:

| Abstand | Ergebnis | gemeldete Höhe |
|---|---|---|
| 200 m | angenommen | 2,4 ft |
| 1 km | angenommen | 3,5 ft |
| 5 km | angenommen | 0,1 ft |
| 10 km | angenommen | −0,1 ft |
| 25 km | angenommen | 1,2 ft |
| 50 km | angenommen | 28,4 ft |
| 100 km | angenommen | 7,1 ft |
| 200 km | angenommen | 139,8 ft |
| 500 km | angenommen | — |
| 1.000 km | angenommen | — |
| 3.000 km | angenommen | — |
| 10.000 km | angenommen | — |

Keine einzige Exception. Aufschlussreich sind die **Höhen**: Sie folgen dem Gelände — Watt bei
5 und 10 km auf Meereshöhe, 28,4 ft im Binnenland bei 50 km, 139,8 ft bei 200 km (Mecklenburger
Seenplatte). Der Simulator konsultiert also echtes, vermessenes Terrain, auch 200 km entfernt.

**Was das NICHT beweist:** Eine Lagemeldung sagt, dass das Objekt existiert und auf welcher
Höhe es sitzt — nicht, dass es gezeichnet wird. Ein Objekt 10.000 km entfernt ist mit Sicherheit
nicht gerendert. Die Sichtbarkeit ist ausschließlich im Nahbereich belegt (200 m an Land,
1,6 km auf dem Wasser, beides per Screenshot).

**Die offene Frage lautet damit präziser als vorher:** Wird ein weit entfernt angelegtes Objekt
gezeichnet, wenn der Pilot später hinkommt? Das braucht einen Flug oder einen Slew über größere
Distanz und ist hier nicht gemessen worden. Für den Kieker ist sie nicht blockierend — ein
mitlaufender Spawner kann nachsetzen, sobald der Pilot näher kommt.

## 3. Die Container-Titel, die funktioniert haben

**`Boat01`** und **`FishingBoat`** — beide ohne Umweg angenommen.

Titel zu raten ist nicht nötig, sie stehen im Klartext auf der Platte. **Aber nicht dort, wo
die Übergabe sie vermutet:** MSFS 2024 legt `sim.cfg` nicht als Datei ab, sondern packt die
Pakete in `content\minimal.fsarchive`. Das Archiv ist **unverschlüsselt** — sein Kopf sagt
wörtlich `{"encryptionSetup":{"scheme":"no…` — und die Titel stehen als lesbarer Text darin.
Eine Dateisuche nach `sim.cfg` findet in MSFS 2024 **nichts**.

Aus `fs20-asobo-simobjects-boats` (mitgeliefert, gestreamt):

```
Boat01  Boat02  CargoContainer01  CargoGas01  CargoOil01  CargoShip01
CruiseShip01  CruiseShip02  FishingBoat  FishingShip02  FishingShip03
PlatformSupply  Yacht01  Yacht02  Yacht03
```

Dazu aus `fs20-asobo-simobjects-boats-modular`: `ASOBO_Boat01`, `ASOBO_FishingBoat`.

**Nicht eingeplant, aber vorhanden:** Im Community-Ordner liegt `aerosoft-landmarks-north-sea`
mit einem ganzen Satz Nordsee-Schiffe — Trawler, Schlepper in drei Farben, Bagger,
`Wind_Farm_Servicer`, Tanker, Plattformen. Jeweils zusätzlich als `_Static`-Variante. Für
einen ostfriesischen Eventtyp sind das die passenderen Modelle als ein Freizeitboot. Sie
kommen allerdings aus einem gekauften Addon, das nicht jedes Mitglied hat.

**Ebenfalls gefunden, für später:** MSFS 2024 bringt **41 Tier-Pakete** mit
(`fs24-microsoft-simobjects-animals-*`: Hirsch, Kuh, Schaf, Ziege, Wolf, Fuchs …). **Eine
Robbe ist nicht darunter** — die nächstliegenden Kandidaten sind Landtiere. Das ist für den
Kieker insofern interessant, als es zeigt: Asobo liefert zählbare Tiere als SimObjects aus,
die Gattung ist also vorgesehen. Ein eigenes Robbenmodell bleibt trotzdem eigene Arbeit.

## 4. Was am Skript geändert werden musste

Die Erstfassung vom Server war nicht lauffähig im Sinne von „misst das Richtige". Fünf
Änderungen, drei davon zwingend:

### a) Die Verbindung wurde zu früh geschlossen — **das Skript räumte weg, was zu sehen sein sollte**

`probe()` rief `SimConnect_Close` unmittelbar nach der Objekt-ID. SimConnect entfernt dabei
die vom Client erzeugten AI-Objekte. Der Probeflug hätte also mit „ERFOLG: Objekt-ID …"
geendet, und beim Hinsehen wäre nichts da gewesen — mit dem Schluss „angelegt, aber nicht
gezeichnet", der falsch gewesen wäre. Jetzt bleibt die Verbindung `--halten` Sekunden offen
(Vorgabe 180).

### b) Die Exception-Nummern ab 12 waren falsch

Am SDK-Header nachgezählt (`C:\MSFS 2024 SDK\SimConnect SDK\include\SimConnect.h`, Zeile 158 ff.):

| Skript sagte | ist tatsächlich | richtig wäre |
|---|---|---|
| 12 = ILLEGAL_OPERATION | 12 = TOO_MANY_REQUESTS | ILLEGAL_OPERATION = 25 |
| 28 = OBJECT_CONTAINER | 28 = DEFINITION_ERROR | OBJECT_CONTAINER = 34 |
| 29 = OBJECT_AI | 29 = DUPLICATE_ID | OBJECT_AI = 35 |
| 30 = OBJECT_ATC | 30 = DATUM_ID | OBJECT_ATC = 36 |
| 31 = OBJECT_SCHEDULE | 31 = OUT_OF_BOUNDS | OBJECT_SCHEDULE = 37 |

0 bis 7 stimmten, `NAME_UNRECOGNIZED = 7` also auch. Ein Fehlschlag wäre trotzdem falsch
benannt worden. Die Tabelle ist jetzt vollständig (0–44).

**Der wichtigste Neuzugang ist die 33 — `OBJECT_OUTSIDE_REALITY_BUBBLE`.** Die stand in der
Stolperstein-Tabelle der Übergabe gar nicht, ist aber der wahrscheinlichste Fehlschlag: ein
Objekt zu weit vom Flugzeug weg wird abgelehnt. Die Kachelotplate als Standardziel hätte
genau das ausgelöst, sobald der geladene Flug nicht zufällig dort steht.

### c) Die Titelsuche fand in MSFS 2024 nichts

Sie lief mit `rglob` über ganze Laufwerke und suchte `sim.cfg` — Minuten Laufzeit, und in
MSFS 2024 null Treffer (s. Abschnitt 3). Jetzt liest sie die Paketpfade aus `UserCfg.opt` und
durchsucht zusätzlich die `.fsarchive`-Dateien nach Klartext. Laufzeit unter einer Minute,
Treffer in beiden Simulatoren.

### d) Die DLL-Reihenfolge nahm gegen MSFS 2024 die 2020er DLL

Auf diesem Rechner zeigt `MSFS_SDK` auf `D:\MSFS SDK` (2020) und `MSFS2024_SDK` auf
`C:\MSFS 2024 SDK`. Die Kandidatenliste probierte `MSFS_SDK` zuerst. Getauscht.

Gegenprobe zur DLL-Warnung in der Übergabe: **beide** SDK-DLLs exportieren
`SimConnect_AICreateSimulatedObject` (geprüft per `ctypes.WinDLL(...)` + `hasattr`, nicht
geraten). Ein `SimConnect_AICreateSimulatedObject_EX1` mit zusätzlichem Livery-Parameter gibt
es auch — für später, falls Farbvarianten gebraucht werden.

### e) Zwei Messhilfen dazugebaut

- **`--neben-mir <meter>`** — liest die eigene Flugzeugposition (`SIMCONNECT_OBJECT_ID_USER`)
  und setzt das Objekt so viele Meter östlich daneben. Schließt Exception 33 aus und macht das
  Hinsehen trivial.
- **Lagemeldung im Sekundentakt** (`RequestDataOnSimObject` auf die vergebene Objekt-ID,
  `PERIOD_SECOND`). Das ist der eigentliche Messwert: Eine Objekt-ID sagt nur, dass der Auftrag
  angenommen wurde. Ob dort etwas *steht* und ob es *bleibt*, zeigt erst die Position Sekunde
  für Sekunde — inklusive Höhe, die „auf dem Wasser" von „im Wasser" unterscheidet.
- **`--ohne-nachprobe`** schaltet die Prüfung ab, ob das Objekt das Schließen überlebt.

Was **nicht** geändert werden musste: `SIMCONNECT_DATA_INITPOSITION` (6 Doubles, 2 DWORDs) war
richtig, ebenso `RECV_ID` 1/2/12 und die Signatur von `AICreateSimulatedObject`. Die als
„ungeprüft" markierten Werte sind jetzt am Header gegengezählt und stimmten.

## 5. Wie lange blieb das Objekt?

180 s (Lauf 2) und 120 s (Lauf 3) — jeweils bis zum Schluss, die Läufe endeten von selbst,
nicht das Objekt. Keine einzige fehlende Lagemeldung, keine Positionsänderung in der fünften
Nachkommastelle, keine Höhenänderung. Es gibt **kein** Aufräumen durch die KI-Engine zu
beobachten.

**Zu Rucklern liegt keine Messung vor** — der Pilot hat nichts gemeldet, und ein einzelnes
Objekt ist auch nicht der Fall, an dem sich das zeigen würde. Die Frage stellt sich erst bei
vielen Objekten, und die ist laut Übergabe ausdrücklich noch nicht dran.

### Nachgemessen am 11.09. spätabends: 240 s, zweimal, MSFS 2024

Anlass war ein Lauf, der bei t=+45 s verstummte und danach 375 s schwieg. Er hatte **keine
Kontrolle** — es war nicht zu unterscheiden, ob der Simulator das Objekt weggeräumt hatte oder
ob schlicht die Verbindung tot war. Genau diese Lücke hatte auch der untaugliche
Chiemsee-Versuch weiter unten.

**Deshalb hat der Probeflug jetzt eine Kontrollspur:** Die eigene Lage wird parallel zur
Objektlage abonniert (`REQ_KONTROLLE`, `PERIOD_SECOND`). Schweigt das Objekt, während die
Kontrolle weiterläuft, war es das Objekt. Schweigen beide, meldet das Skript
`MESSUNG UNGUELTIG` statt eines Befunds.

| | Ziel | Entfernung Flieger | Dauer | Ergebnis |
|---|---|---|---|---|
| Lauf A | Bodensee 47.645/9.500 | **691,3 km** | 240 s | 240 Meldungen, durchgehend |
| Lauf B | 500 m östlich des Flugzeugs | **0,5 km** | 240 s | 240 Meldungen, durchgehend |

**Beide Male exakt 240 Meldungen in 240 s** — `PERIOD_SECOND` liefert zuverlässig im
Sekundentakt, ohne eine einzige Lücke. Das ist zugleich der Beleg dafür, dass der 1-s-Regeltakt
des Protokolls auf der Simulator-Seite überhaupt bedienbar ist.

**Das Verstummen bei t=+45 s ist damit nicht reproduzierbar.** Die naheliegende Erklärung ist,
dass der Simulator in jenem Lauf beendet wurde — er war danach nachweislich zu. Ein
`RECV_QUIT` kam zwar nicht an, aber ein hart beendeter Sim schickt keins mehr.

⚠ **Daraus folgt nicht, dass Objekte immer stehen bleiben.** In MSFS 2020 verlief derselbe
Aufruf zweimal verschieden (einmal nach einer Sekunde fort, einmal 600 s stabil) — der
Protokollzustand `verschwunden` bleibt begründet. Er ist nach dieser Messung nur kein
**Regelfall** in MSFS 2024.

### ⚠ Aus der Ferne ist die gemeldete Höhe unbrauchbar

Der wichtigere Befund steckt im Vergleich der beiden Läufe:

| | Lauf A (691 km) | am selben Ort aus der Nähe |
|---|---|---|
| `CruiseShip01` am Bodensee | **2106,5 ft** | 1297,2 ft |

**Das sind 810 ft Unterschied an derselben Koordinate.** Der Seespiegel liegt bei 1296 ft; 2106
ft entspricht 642 m und gehört zu keinem Punkt des Sees. Der Simulator antwortet aus der
Entfernung offenbar aus einer groben Geländestufe, nicht aus dem geladenen Terrain.

Das ergänzt die Tabelle unter „Die Reality Bubble": Dort folgten die Höhen dem Gelände bis
200 km (139,8 ft Mecklenburger Seenplatte), und ab 500 km stand `—`, weil nicht gemessen wurde.
**Jetzt ist gemessen, und der Wert ist da — aber falsch.**

**Folge für das Protokoll:** `steht[].hoehe_ft` ist nur verlässlich, wenn der Pilot in der Nähe
ist. Der Server darf aus einer Höhenmeldung aus großer Entfernung **nicht** schließen, dass
eine Stelle tauglich oder untauglich ist — er würde brauchbare Stellen aussortieren und
untaugliche behalten.

### Objekte überleben die Verbindung nicht — erneut bestätigt

Beide Nachproben: `EXCEPTION 3 — UNRECOGNIZED_ID`. Ein Prozess, der setzt und sich beendet,
hinterlässt nichts. Die Brügge muss durchlaufen.

## 6. Schritt 4 — läuft so etwas unbemerkt mit?

Beantwortet, und zwar **ohne einen Eintrag anzulegen**: Was die Übergabe mit einem Testeintrag
messen wollte, lässt sich an den vorhandenen Addons ablesen.

1. **Gibt es `exe.xml` in MSFS 2024 noch?** Ja, unter
   `%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\exe.xml`, mit
   **sieben** Einträgen: ActiveSky (2×), Fenix A320, Aerosoft VDGS Driver, FSRealistic,
   Flow Pro, FlowShare. Der Weg ist nicht nur vorhanden, er ist in Gebrauch.
2. **Startet ein Eintrag wirklich mit?** Ja. `ActiveSkyUtils` und `FlowShare` haben Startzeit
   **07:49:17**, der Simulator **07:46:48** — der Sim hat sie gestartet.
3. **Sieht der Pilot etwas davon?** Kein Fenster: beide Prozesse haben einen leeren
   `MainWindowTitle`, es blitzt also keine Konsole auf. **Offen bleibt die SmartScreen-Frage**
   — ActiveSky und Flow sind signierte Installationen, eine selbstgebaute unsignierte Datei
   ist ein anderer Fall. Das lässt sich erst mit einer echten Testdatei beantworten und wurde
   bewusst nicht gemacht: `exe.xml` startet Programme bei jedem Simulatorstart, und dort sollte
   nichts stehen bleiben, das nicht bewusst dort hingehört.

**In `exe.xml` wurde nichts geändert.**

## Wie viele Objekte verträgt der Simulator? (Spec 13.4, Frage 3)

Gemessen mit `--anzahl`, Boote als quadratisches Raster neben dem Flugzeug. Zwei Größen: ob
der Simulator sie **annimmt** (`EXCEPTION 11 = TOO_MANY_OBJECTS` wäre die harte Grenze) und ob
er **gesund bleibt** — jedes Objekt meldet seine Lage im Sekundentakt, erwartet werden also
so viele Meldungen je Sekunde, wie Objekte stehen.

| Objekte | angelegt | Meldungsrate | Exceptions |
|---:|---|---|---|
| 25 | 25 von 25 | 100 % | keine |
| 100 | 100 von 100 | 100 % | keine |
| 400 | 400 von 400 | 100 % (43.200 Meldungen in 120 s) | keine |

**Keine Grenze gefunden.** Der Kieker bräuchte realistisch 10 bis 50 Objekte — 400 sind weit
jenseits des Bedarfs. `AICreateSimulatedObject` ist **asynchron**: 400 Aufträge sind in unter
10 ms abgesetzt, die Objekt-IDs trudeln danach über etwa 15 Sekunden ein. Wer auf jede Antwort
einzeln wartet, misst seine eigene Wartepause.

**Ein Aussetzer ist aufgetreten und bleibt ungeklärt:** Im 400er-Lauf fiel die Rate bei
`t=+35s` auf 14,6 % und erholte sich danach auf 100 %. Ein Einzelereignis, in den kleineren
Läufen nicht zu sehen. Ob Simulator, Nachladevorgang oder Kamerabewegung — mit diesem Aufbau
nicht auseinanderzuhalten.

**Was diese Zahlen nicht sind: eine Bildrate.** SimConnect gibt keine her. Die Meldungsrate
zeigt, ob der Simulator die Objekte weiterführt, nicht ob es flüssig aussieht. Deshalb hat der
Pilot bei stehenden 400 Booten hingesehen — sein Urteil: **kein Ruckeln.** Damit ist die Frage
beantwortet, und zwar deutlich oberhalb dessen, was der Kieker je braucht.

Der Aussetzer oben bleibt davon unberührt und ungeklärt: Er war in der Meldungsrate sichtbar,
im Bild offenbar nicht.

### Ein Messfehler im eigenen Aufbau, der fast als Sim-Befund durchgegangen wäre

Der erste 25er-Lauf meldete **8 % der erwarteten Rate** — das sah nach einem überlasteten
Simulator aus. Die Ursache lag im Probe-Skript: `_lage_abonnieren` hängte je Objekt drei
Variablen an **dieselbe** Datendefinition, die hatte nach 25 Objekten also 75 Einträge statt
drei. Bei einem einzelnen Objekt fällt das nie auf.

Behoben, indem Definition und Anfrage getrennt wurden (`_lage_definition` läuft genau einmal je
Verbindung — dafür ist eine `DefineID` da). Gleicher Anlass, zweiter Fund: Die gemessenen
„302 ms je Aufruf" waren die eigene Wartepause von 80 ms je Objekt, nicht der Simulator. Nach
der Reparatur: 100 % Rate, 0 ms je Aufruf.

Die Lehre ist dieselbe wie beim ursprünglichen Skript, das die Verbindung zu früh schloss:
**Ein Messaufbau, der beim Einzelfall funktioniert, kann bei der Menge etwas ganz anderes
messen.** Wer die 8 % geglaubt hätte, hätte den Kieker auf „höchstens eine Handvoll Objekte"
zugeschnitten.

## ✅ GELÖST: WASM kann die eigene Position lesen — es war eine ID-Kollision

**Die Frage blockierte den Auslieferungsweg.** Ein Modul, das seine Lage nicht liest, kann sie
weder melden noch prüfen, ob ein gesetztes Objekt noch steht — damit wäre WASM für die Brügge
erledigt gewesen und nur der Weg über eine externe EXE geblieben (mit Installer und
SmartScreen-Warnung).

**Die Ursache stand die ganze Zeit im eigenen Quelltext:**

```c
#define CD_DEF    1     // ClientDataDefinition -- der Rueckkanal
    DEF_LAGE   = 1,     // DataDefinition -- die Lageabfrage
```

`SimConnect_AddToClientDataDefinition` und `SimConnect_AddToDataDefinition` nehmen **beide**
eine `SIMCONNECT_DATA_DEFINITION_ID`. Es ist ein gemeinsamer Nummernraum. ID 1 war als
ClientData-Definition belegt; die spätere Benutzung als Datendefinition endete mit
`EXCEPTION 3 — UNRECOGNIZED_ID`.

**Warum es im externen Probeflug nie auffiel:** Der legt gar kein ClientData an. Dort ist ID 1
frei, und dieselbe Zeile funktioniert. Der Fehler entsteht erst, wenn beides im selben Client
lebt — und das ist im WASM-Modul zwangsläufig so, weil ClientData dort der einzige
funktionierende Rückkanal ist (`fprintf` erreicht die Konsole nicht, `fsNetworkHttpRequestGet`
kein 127.0.0.1).

**Nach dem Auseinanderziehen (`DEF_LAGE = 10`, `REQ_LAGE = 20`), gemessen auf Wangerooge:**

```
AddToDataDefinition: S_OK    RequestDataOnSimObject: S_OK
*** LAGE GELESEN: 441 Meldungen, zuletzt 53.78226 / 7.92593 ***
Schritt 8: *** OBJEKT ANGELEGT ***   Objekt-ID: 2949120
```

441 Lagemeldungen im Sekundentakt, die Position deckt sich auf fünf Nachkommastellen mit dem
Standplatz des Flugzeugs. Das Objekt wurde **an der gelesenen Lage** gesetzt, nicht an der
fest einprogrammierten Rückfall-Koordinate — der Weg ist also vollständig durchlaufen.

**Damit bleibt WASM als Auslieferungsweg im Rennen.** Was dafür spricht: ein Verzeichnis im
Community-Ordner statt eines Installers, keine SmartScreen-Warnung, kein zweiter Prozess.
Was weiter dagegen steht: Die Network-API nimmt nur HTTPS, `OnGround=1` wirkt nicht (s. unten),
und für X-Plane ist es ohnehin ein anderer Weg.

### ⚠ Offen geblieben: das Boot des Moduls war nach wenigen Minuten fort

Unmittelbar danach gemessen, mit Kontrolle:

| | Objekt-ID | von der Zählung gefunden? |
|---|---|---|
| extern gesetzt, 300 m entfernt | 101171200 | **ja** — 6,7 ft, korrekte Lage |
| vom WASM-Modul gesetzt | 2949120 | **nein** |

**Die Kontrollzeile trägt den Beweis:** `RequestDataOnSimObjectType` findet extern gesetzte
Boote zuverlässig. Dass es das Modul-Boot nicht findet, liegt also nicht an der Methode.

**Was daraus NICHT folgt:** wann es verschwand und warum. Das Modul meldet die Objekt-ID in
den Statusbereich, abonniert danach aber **nicht** die Lage des gesetzten Objekts — es weiß
selbst nicht, ob sein Boot noch steht. Zwischen dem Setzen (Sekunde 1 nach dem Laden) und der
Zählung lagen mehrere Minuten.

**Auffällig ist die Objekt-ID:** 2949120 gegenüber 100777984 und 101171200 bei externen
Läufen. WASM-Objekte scheinen in einem anderen Nummernbereich zu liegen; ob das etwas
bedeutet, ist nicht untersucht.

**Die nächste Messung dazu** wäre ein Modul, das die Lage seines eigenen Objekts abonniert und
in den Statusbereich schreibt — dieselbe Kontrolle, die der externe Probeflug seit heute hat.
Das ist ein Umbau plus Sim-Neustart und war heute nicht mehr dran.

## WASM: Ja — ein Modul im Simulator kann es auch

**Spec 13.4, Frage 1 ist beantwortet.** Ein WASM-Modul im Community-Ordner startet mit dem
Simulator, öffnet SimConnect und setzt Objekte:

```
WASM: Module modul.wasm initialized.
[modul.wasm] [FriesenBruegge] module_init = 0
[modul.wasm] [FriesenBruegge] open_hr = 0             SimConnect offen
[modul.wasm] [FriesenBruegge] datadef_hr = 0
[modul.wasm] [FriesenBruegge] open_bestaetigt = 1     der Simulator antwortet
[modul.wasm] [FriesenBruegge] create_aufgerufen = 0
[modul.wasm] [FriesenBruegge] ERFOLG_objekt_id = 16384
```

Das Boot war im Bild (Screenshot 12:50:56). Damit könnte die MSFS-Seite der Brügge ein reines
Community-Paket werden: ein Ordner zum Hineinkopieren, kein Eintrag in `exe.xml`, keine
unsignierte EXE, kein SmartScreen-Dialog.

### Vier Anläufe, und der Grund war jedes Mal unsichtbar

Die ersten vier Starts endeten mit **nichts** — kein Objekt, keine Meldung, keine Fehlerzeile.
Von außen ist ein Modul, das die Validierung nicht besteht, von einem Modul, das nichts tut,
nicht zu unterscheiden. Erst die **DevMode-Konsole** zeigte den Grund, und es waren zwei:

| Meldung in der Konsole | Ursache | Abhilfe |
|---|---|---|
| `ERR_UNKNOWN_BLANK_IMPORT: __stack_chk_fail not found` | `clang-cl` schaltet den Buffer Security Check wie MSVC **standardmäßig ein**; die MSFS-WASM-Laufzeit kennt `__stack_chk_fail` nicht | `/GS-` und `-fno-stack-protector` |
| `Error getting indirect function table` | Ein Callback (`SimConnect_CallDispatch`) ist ein Funktionszeiger, und der wird über die indirect function table aufgelöst | `--export-table`, dazu `--growable-table` |

Beides sind **Voreinstellungen, die man nie gesetzt hat** und deshalb nicht sucht. Beide stehen
jetzt mitsamt ihrer Fehlermeldung als Kommentar in `bauen.ps1`.

### Drei eigene Fehldiagnosen, bevor die Konsole befragt wurde

Erwähnenswert, weil jede plausibel klang und jede Zeit gekostet hat:

1. **„Das Manifest ist zu knapp."** Falsch — `spad-bridge-module` läuft auf demselben Rechner
   mit einem genauso knappen.
2. **„Das Paket wird nicht geladen."** Falsch — es stand die ganze Zeit als
   `active="Activated"` in der Paketliste. Ich hatte in die falsche `Content.xml` gesehen: Die
   unter `LocalCache/` stammt vom Juli 2025, die maßgebliche liegt unter `LocalCache/hrsgrlw/`.
3. **„Es fehlt `_EX1`."** Falsch als Ursache, richtig als Hinweis: Der Vergleich mit
   `p42-util-gofish` — einem Addon, das selbst Objekte setzt — brachte die Bestätigung, dass
   beides aus WASM geht. Der Wechsel auf `_EX1` behob den Fehler aber nicht.

**Die Lehre:** Wo ein Simulator schweigt, hilft kein weiteres Raten von außen. Die Konsole hätte
am Anfang stehen müssen, nicht nach vier Starts.

### Was in WASM anders ist als im externen Programm

| | extern | WASM |
|---|---|---|
| Objekt setzen | ✅ | ✅ |
| `AICreateSimulatedObject` ohne Suffix | ✅ | nur `_EX1` belegt |
| **`OnGround=1` setzt auf den Boden** | ✅ 2,0 ft | ❌ **das Boot schwebte** |
| HTTP an `127.0.0.1` | — | ❌ nichts kam an |

**Das Schweben ist ein WASM-Effekt, nicht ein `_EX1`-Effekt.** Gegenprobe extern, beide
Fassungen, gleicher Flug: alte Fassung 2,0 ft, `_EX1` 3,6 ft — beide sauber am Boden.

### Ausgemessen: `OnGround` ist der Übeltäter, `Altitude` ist unschuldig

Vier Varianten in einem Lauf gesetzt, von außen nachgemessen:

| `OnGround` | `Altitude` gesetzt | **gemessen** |
|---|---|---|
| 1 | 0 ft | **49,0 ft** |
| 0 | 0 ft | **0,0 ft** |
| 0 | 500 ft | **500,0 ft** |
| 1 | 500 ft | **49,2 ft** |

**`Altitude` kommt unverändert an** — 0 bleibt 0, 500 bleibt 500,0. Ein Struct- oder
ABI-Problem scheidet damit aus, ebenso ein Feldversatz (die Koordinaten stimmten ohnehin auf
fünf Nachkommastellen).

**`OnGround=1` setzt aus WASM heraus nicht auf**, unabhängig vom Höhenwert — die Zeilen 1
und 4 landen beide auf demselben falschen Wert. Extern bewirkt dasselbe Flag zuverlässig das
Aufsetzen auf Gelände oder Wasser. In WASM ist es unbrauchbar.

#### ⚠ Eine zweite Messung schien das zu widerlegen — sie war selbst falsch

**Am selben Abend, nach einem Sim-Neustart, kamen für dieselben vier Varianten
216,2 / 0,0 / 500,0 / 212,8 ft heraus.** Daraus wurde hier kurzzeitig geschlossen, der
`OnGround`-Wert sei nicht einmal reproduzierbar. **Das war ein Trugschluss, und er hätte eine
Umsetzung in die Irre geführt.**

**Die Boote standen gar nicht auf Wangerooge.** Eine direkte Abfrage der Objekt-ID zeigte:

```
Frage Objekt 2949120 ...
  t=+  0.3s  -0.00000 / 90.00763    212.8 ft   9488390 m vom Flugzeug
```

**0° / 90°, im Indischen Ozean.** Das ist der Nullpunkt, den SimConnect liefert, solange kein
Flug geladen ist — und genau davor warnt ein Kommentar zwei Funktionen weiter oben. Das
umgebaute Modul setzte bei der **ersten** Lagemeldung, und die kam, bevor die Welt fertig
geladen war.

**Drei Beobachtungen passten dazu, und alle drei waren richtig:**

| Beobachtung | warum sie stimmte |
|---|---|
| Statusbereich meldete `53.78226 / 7.92593` | das war die **zuletzt gelesene** Lage, nicht die, mit der gesetzt wurde |
| `--boote-zaehlen` fand nichts im Umkreis von 3 km | die Boote standen 9488 km entfernt |
| Modul meldete „alle vier leben" | sie lebten — nur woanders |

**Die 216 ft sind damit dieselbe Sorte Phantomwert wie am Bodensee aus 691 km Entfernung:**
grobes Gelände an einem Ort, den der Simulator nicht geladen hat. Der Lauf mit 49 ft benutzte
die fest einprogrammierte Wangerooge-Koordinate und ist der **einzige gültige**.

**Behoben:** Das Modul verwirft Lagemeldungen mit 0/90 und setzt frühestens in Sekunde 5.
Beide Bedingungen sind nötig — die Wartezeit deckt den Regelfall, die Prüfung den Fall, dass
das Laden länger dauert. Zusätzlich meldet es jetzt die Koordinate, **mit der gesetzt wurde**,
getrennt von der zuletzt gelesenen; ohne diese Trennung war der Fehler von außen unsichtbar.

⚠ **Damit steht die OnGround-Frage wieder offen.** Gültig ist nur die Erstmessung
(49,0 / 0,0 / 500,0 / 49,2 ft auf Wangerooge): `OnGround=0` trifft die angegebene Höhe exakt,
`OnGround=1` setzt nicht auf. Ob der Wert bei `OnGround=1` über Läufe hinweg konstant ist,
ist **nicht** gemessen — die Wiederholung, die es zeigen sollte, ist die hier beschriebene
Fehlmessung.

#### Die Abhilfe

`OnGround=0` mit `Altitude=0` ergibt **0,0 ft, also exakt Meereshöhe** — für Boote im
Wattenmeer genau richtig, ohne jede Rechnung.

**Für Objekte über Land** kann die Brügge die Geländehöhe selbst ausrechnen, aus zwei Werten,
die sie ohnehin liest:

```
Geländehöhe  =  PLANE ALTITUDE  −  PLANE ALT ABOVE GROUND
```

⚠ **Die Grenze:** Das ist die Geländehöhe **unter dem Flugzeug**, nicht am Zielort. Für ein
Objekt wenige hundert Meter daneben taugt sie, für eines 5 km weiter nicht. Für den Kieker an
den Friesischen Inseln fällt das kaum ins Gewicht; in den Alpen wäre es eine andere Rechnung.
Der X-Plane-Adapter hat das Problem nicht — er fragt `XPLMProbeTerrainXYZ` und bekommt die
Höhe am Zielort selbst.

**Der HTTP-Rückkanal blieb stumm**, obwohl dieselben Meldungen per `fprintf` in der Konsole
standen. `fsNetworkHttpRequestGet` erreichte kein `127.0.0.1`. Das ist **kein** Beweis, dass
WASM nicht ins Netz darf — GoFish und Flow nutzen die Funktion nachweislich erfolgreich, aber
gegen *externe* Server (`http response received: 200` steht im selben Log). Für die Brügge, die
`friesenspy.devprops.de` fragt, ist der lokale Fall ohnehin nicht der Anwendungsfall.

### WASM in MSFS 2020: nicht belegt — und ein Modul reicht ohnehin nicht für beide

**Schon ohne Simulator gemessen:** Das 2020er SDK kennt `AICreateSimulatedObject_EX1`
**nicht** — die Funktion steht nicht in seinem `SimConnect.h`. Ein Modul, das sie importiert,
scheitert dort am unauflösbaren Import, genau wie zuvor an `__stack_chk_fail`.

Also eine eigene Fassung, gegen das 2020er SDK gebaut, mit der alten Funktion ohne Suffix.
Ergebnis in MSFS 2020:

```
WASM: Compiled module modul.wasm in 1 seconds
WASM: Module modul.wasm loaded...
WASM: Module modul.wasm initialized.
```

Geladen, übersetzt, initialisiert — **aber kein Objekt** (von außen mit `--boote-zaehlen`
gegengeprüft: kein einziges Boot im Umkreis von 5 km). Und **keine einzige `[modul.wasm]`-Zeile**,
obwohl dieselben `fprintf`-Aufrufe in MSFS 2024 nach jedem Schritt eine lieferten. MSFS 2020
leitet WASM-`stderr` offenbar nicht in die Konsole — damit fehlt genau das Werkzeug, das die
2024er Diagnose überhaupt erst möglich gemacht hat.

**Nicht belegt heißt hier nicht „geht nicht".** Es heißt: Ohne Log ist die Ursache von außen
nicht zu bestimmen, und die Suche hätte dieselbe Form wie in 2024 — Start für Start, nur blind.

### Korrektur: Ein gemeinsames Modul ist doch baubar

Hier stand zwischenzeitlich, der WASM-Weg brauche **zwei Module**, weil `_EX1` in MSFS 2020
fehlt. **Das war falsch**, und der Nutzer hat es zu Recht bezweifelt („wieso kann man kein WASM
für beide bauen?").

Die Fassung **ohne** Suffix steht in **beiden** SDKs — und sie ist aus WASM erreichbar. Am
11.09.2026 in MSFS 2024 gemessen: vier Boote, Höhen identisch zum `_EX1`-Lauf
(49,0 / 0,0 / 500,0 / 49,2 ft). Auch das `OnGround`-Verhalten hängt also nicht an der
Funktionswahl.

**Der Fehlschluss war derselbe wie mehrfach an diesem Tag:** Aus *„GoFish benutzt `_EX1`"* wurde
*„die andere geht nicht"*. Der Quelltext benutzt jetzt die alte Fassung als Normalfall;
`-NutzeEx1` schaltet auf `_EX1` um, falls später Liveries gebraucht werden, die nur sie kann.

**Was in 2020 fehlte, war nicht die Funktion, sondern die Sicht** — allerdings anders, als hier
zwischenzeitlich stand. Das Modul schreibt seinen Fortschritt jetzt zusätzlich in einen
**ClientData**-Bereich, den ein externes Programm mitliest (`kieker_probe.py --status`); SPAD.neXt
macht es auf demselben Rechner genauso. Dieser Rückkanal ist unabhängig von Konsole und Netz und
hat die Sache entschieden.

> **Korrektur:** Hier stand, MSFS 2020 leite WASM-`stderr` nicht in die Konsole. **Das ist
> falsch.** Die Meldungen kommen dort sehr wohl an — nur **ohne** das `[modul.wasm]`-Präfix, das
> MSFS 2024 voranstellt. Gesucht wurde nach genau diesem Präfix, und aus dem Nichtfinden wurde
> ein Befund gemacht. Der erste 2020-Fehlschlag erklärt sich damit vermutlich auch: Der
> Log-Ausschnitt endete bei `initialized`, die Zeilen danach waren nicht mit dabei.

### ✅ Und damit läuft WASM auch in MSFS 2020

Mit dem Rückkanal war es sofort sichtbar:

```
Schritt 8: *** OBJEKT ANGELEGT ***   Objekt-ID: 4
```

Gegenprobe von außen: **vier Boote**, 107 bis 463 m entfernt, Objekt-IDs 1 bis 4. Und in der
Konsole die ganze Kette:

```
[FriesenBruegge] module_init = 0
[FriesenBruegge] open_hr = 0
[FriesenBruegge] create_aufgerufen = 0
[FriesenBruegge] ERFOLG_objekt_id = 1 … 4
Loading: 'vfs://asobo-simobjects-boats/SimObjects/Boats/Boat01/model/Boat01.gltf'
```

**Ein gemeinsames Modul bedient damit beide Simulatoren** — gebaut mit der alten
`AICreateSimulatedObject`, je einmal gegen das passende SDK übersetzt. Damit ist der WASM-Weg
für MSFS vollständig: ein Quelltext, zwei Builds, zwei Ordner zum Hineinkopieren.

### Die Höhe verhält sich in beiden Simulatoren verschieden — eine Einstellung passt trotzdem

| Variante | MSFS 2024 | MSFS 2020 |
|---|---|---|
| `OnGround=1`, `Alt=0` | 49,0 ft | 0,0 ft |
| **`OnGround=0`, `Alt=0`** | **0,0 ft** | **0,0 ft** |
| `OnGround=0`, `Alt=500` | 500,0 ft | 0,0 ft |
| `OnGround=1`, `Alt=500` | 49,2 ft | 0,0 ft |

**MSFS 2020 ignoriert die Höhe vollständig** und setzt alles auf Meereshöhe — auch die 500 ft.
MSFS 2024 nimmt sie ernst, verunglückt aber bei `OnGround=1` auf konstant 49 ft.

**Die Schnittmenge ist `OnGround=0` mit `Altitude=0`:** beide Simulatoren setzen dann auf
0,0 ft, also exakt Meereshöhe.

### ⚠ Und genau deshalb sind Objekte über Land unsichtbar

Das klang nach der bequemen Lösung — ist es aber nur auf **Wasser**. Am Boden auf Wangerooge
nachgemessen:

```
Flugzeug steht bei 53.78691 / 7.90998, 10.0 ft   <- Gelaendehoehe, rund 3 m ueber MSL
alle gesetzten Objekte:                  0.0 ft   <- Meereshoehe
```

**Die Objekte sitzen drei Meter unter dem Platz.** Zwei Beobachtungen belegen es unabhängig:

| Objekt | Höhe des Modells | sichtbar? |
|---|---|---|
| `Boat01` | ~2,5 m | **nein** — vollständig im Boden |
| `CruiseShip01` | ~50 m | **ja** — ragt 47 m heraus |

Beide standen auf derselben Koordinate und derselben gemeldeten Höhe. Der Pilot sah nur das
Schiff, und das erklärt auch, warum die vier WASM-Boote trotz gültiger Objekt-IDs nirgends zu
finden waren.

### ✅ Aufgelöst: Es liegt an der Objektart, nicht an der Höhe

Hier stand zwischenzeitlich, in MSFS 2020 lasse sich die Höhe „überhaupt nicht steuern". **Das
war zu weit verallgemeinert** — es gilt nur für **Boote**. Gemessen, alle am selben Ort, bei
einer Geländehöhe von rund 5 ft:

| Titel | Kategorie | gemessene Höhe |
|---|---|---|
| `Boat01` | **Boat** | **0,0 ft** — Meereshöhe |
| `Windsock` | StaticObject | 4,6 ft |
| `BlackBear` | **Animal** | 5,0 ft |
| `Windmill` | StaticObject | 5,8 ft |
| `ASO_Ambulance_Japan` | GroundVehicle | 5,6 ft |

**Alles außer Booten landet auf Geländehöhe.** MSFS 2020 zwingt Boote auf die Meereshöhe —
deshalb versanken die vier `Boat01` drei Meter tief im Platz, während das Kreuzfahrtschiff an
derselben Stelle sichtbar blieb: Es ist hoch genug, um herauszuragen.

Damit ist auch klar, warum `Altitude` und `SetDataOnSimObject` wirkungslos schienen — beides
wurde ausschließlich an Booten erprobt.

**Für den Kieker heißt das:** Objekte an Land sind kein Problem, man darf nur keine Boote
nehmen. Und MSFS 2020 bringt dafür genau das mit, was der Eventtyp ursprünglich mit Robben
vorhatte:

```
asobo-simobjects-animals    BlackBear, AfricanElephant, AfricanGiraffe, Hippo, …
                            Flamingo, Goose  (FlyingAnimal, ungeprüft)
asobo-simobjects-landmarks  Windsock, Windmill, VfxSpawner
asobo-simobjects-misc       Flaggen, Marshaller_Stick, Optical_Landing_System
asobo-simobjects-vehicles   Ambulanz, Gepäckwagen, Tankwagen, Caddy, …
```

Eine Robbe ist nicht dabei — aber die **Gattung `Animal` existiert, funktioniert und wird
gezeichnet**: Vier Elefanten und vier Giraffen, unmittelbar neben einer Windmühle gesetzt, waren
im Bild. Damit ist der Ersatz für die ursprüngliche Robben-Idee nicht nur vorhanden, sondern
erprobt.

**Dabei zum dritten Mal an diesem Tag dieselbe Falle:** Ein erster Versuch mit Elefanten in
150 m und 230 m Entfernung wurde nicht gefunden — 6 von 6 angelegt, zehn Minuten lang 100 %
Meldungsrate, und trotzdem „ich sehe keine Elefanten". Erst 20 m neben einem hohen, bereits
sichtbaren Objekt waren sie da. Die Regel von heute Vormittag gilt unverändert und ist offenbar
schwer einzuhalten: **groß, nah und lange — und am besten neben etwas, das man schon sieht.**

### ✅ Am Bodensee entschieden: in **MSFS 2020** ist die Kategorie `Boat` kaputt

> **Simulator: MSFS 2020.** Diese Angabe fehlte hier bis zum 11.09.2026 abends und wurde vom
> Nutzer nachgetragen — sie ist entscheidend, denn **in MSFS 2024 gilt der Befund nicht**
> (s. den Kasten unter der Tabelle).

Die Frage kam vom Nutzer: Was wird aus einem Boot auf einem Bergsee? Vor Ort gemessen, Flug auf
**EDNY Friedrichshafen** (Platz 1348,9 ft), Objekte 2,5 km südlich mitten auf den See gesetzt.
Der Bodensee liegt auf 395 m ≈ **1296 ft**:

| Titel | Kategorie | gemessene Höhe |
|---|---|---|
| `CruiseShip01` | **Boat** | **0,0 ft** — 395 m unter dem See |
| `Windmill` | StaticObject | **1297,0 ft** ✅ |
| `BlackBear` | Animal | **1297,0 ft** ✅ |
| `ASO_Ambulance_Japan` | GroundVehicle | **1297,0 ft** ✅ |

**Alles außer Booten findet die Oberfläche — auch auf einem Binnensee.** Die „Geländehöhe", auf
die `OnGround=1` diese Objekte setzt, ist über Wasser der Wasserspiegel. In MSFS 2020 ignoriert
die Kategorie `Boat` das und nimmt stur die Meereshöhe.

| **MSFS 2020** | Land | Nordsee | Binnensee |
|---|---|---|---|
| `Boat` | ✗ versinkt | ✓ — aber nur, weil MSL dort die Oberfläche *ist* | ✗ 395 m zu tief |
| `StaticObject`, `Animal`, `GroundVehicle` | ✓ | ✓ | ✓ |

### ⚠ In MSFS 2024 gilt das **nicht** — dort finden auch Boote die Oberfläche

**Der Unterschied ist in denselben Protokollen belegt, an derselben Stelle, mit demselben
Modell.** Wangerooge, Geländehöhe rund drei Meter:

| Simulator | `Boat01` gemeldet | im Bild |
|---|---|---|
| **MSFS 2024** | **2,4 ft** | **ja** — Motorboot im Gras, Screenshot 08:15:06 |
| **MSFS 2020** | **0,0 ft** (Flugzeug daneben: 10,0 ft) | **nein** — drei Meter unter dem Platz |

Dazu die Reality-Bubble-Läufe in MSFS 2024: dasselbe Boot meldete 28,4 ft bei 50 km Entfernung
und 139,8 ft bei 200 km — **geländefolgend**, nicht auf 0 festgenagelt.

| **MSFS 2024** | Land | Nordsee | Binnensee |
|---|---|---|---|
| `Boat` | ✓ gemessen | ✓ | **✓ gemessen** |
| `StaticObject`, `Animal`, `GroundVehicle` | ✓ | ✓ | ✓ gemessen |

#### ✅ Die letzte offene Zelle ist geschlossen (11.09.2026 abends)

Derselbe Flug, derselbe Platz, dieselbe Koordinate wie beim 2020er Lauf — **EDNY
Friedrichshafen, Objekte auf 47.6450 / 9.5000**, 3,0 km in Richtung 196° draußen auf dem See:

```
Windmill      (StaticObject)   1297,1 ft     <- Kontrolle: der Sim KENNT den Seespiegel
CruiseShip01  (Boat)           1297,2 ft     <- in MSFS 2020: 0,0 ft
Boat01        (Boat)           1297,1 ft
```

**Die Windmühle ist die entscheidende Zeile.** Sie beweist, dass das Gelände geladen war und
der Simulator die Seehöhe kannte — dieselbe Stelle, dieselbe Sitzung. Genau diese Kontrolle
fehlte beim Chiemsee-Versuch, dessen 0,0 ft deshalb nichts aussagten.

**Sichtbestätigt:** Der Pilot hat das Kreuzfahrtschiff auf dem See gesehen.

**Damit steht der Unterschied zwischen den Simulatoren fest** — gemessen, nicht hergeleitet:

| | MSFS 2020 | MSFS 2024 |
|---|---|---|
| `Boat` über Land (Wangerooge, Gelände ~3 m) | **0,0 ft** — versunken, unsichtbar | **2,4 ft** — im Gras, im Bild |
| `Boat` auf dem Bodensee (Spiegel 1296 ft) | **0,0 ft** — 395 m zu tief | **1297,2 ft** — schwimmt |
| Kontrollobjekte an derselben Stelle | 1297,0 ft | 1297,1 ft |

**In MSFS 2024 verhält sich `Boat` wie jede andere Kategorie.** Die Einschränkung gilt allein
für MSFS 2020 — und damit für den Simulator, den laut Nutzer nur **wenige** aus der Gruppe
fliegen.

**Das ist ein bekannter Fehler, nicht unser Aufbau.** Im MSFS-DevSupport steht er seit dem
11.05.2022 als *„SimConnect injected Boat underwater"*: Boote spawnen an den **Great Lakes**
unter Wasser, während eine Cessna mit Schwimmern bei identischen Parametern korrekt aufsetzt.
**Bis heute keine Antwort von Asobo**, Status offen; zuletzt fragte der Melder im Juni 2023.
Der dort genannte Workaround ist ein eigenes SimObject mit Flugzeug-Kategorie — mit dem
Nachteil, dass Schiffe dann als Flugzeuge gezählt werden.
<https://devsupport.flightsimulator.com/t/simconnect-injected-boat-underwater/4226>

**Folge für die Brügge: in MSFS 2020 keine `Boat`-SimObjects über Land oder Binnengewässern.**
Auf der Nordsee sind sie dort brauchbar, weil MSL die Oberfläche ist. **In MSFS 2024 gilt die
Einschränkung nicht** — dort verhält sich `Boat` wie jede andere Kategorie. Die Gattungstabelle
des Protokolls führt den `Grund` deshalb **je Simulator**, nicht gemeinsam.

> **Zum Weg hierher:** Diese Aussage stand schon einmal hier — gestützt allein auf eine Probe
> am Chiemsee aus 800 km Entfernung, wo kein Gelände geladen war. Der Nutzer hat sie bezweifelt,
> sie wurde zurückgenommen, und dann vor Ort richtig gemessen. Das Ergebnis ist dasselbe, der
> Unterschied ist, dass es jetzt trägt.

Für MSFS 2024 gilt das nicht: Dort kommt `Altitude` an, die Brügge müsste nur die Geländehöhe
kennen (s. den Kasten oben). Die hat FriesenSpy nicht (Spec 4.2) — dieselbe Einschränkung, die auch den
X-Plane-Adapter trifft, der deshalb `XPLMProbeTerrainXYZ` fragt.

| | MSFS 2020 | MSFS 2024 |
|---|---|---|
| extern über `exe.xml` | ✅ ein Programm für beide | ✅ |
| WASM-Modul | ✅ ein Quelltext, zwei Builds | ✅ |

### ⚠ In MSFS 2020 bleibt ein Objekt nicht zuverlässig

Zweimal derselbe Aufruf, dieselbe Koordinate, dasselbe Modell — zwei verschiedene Ergebnisse:

| Lauf | Objekt-ID | Lagemeldungen | Beobachtung |
|---|---|---|---|
| 1 | 496 | **keine einzige** | „kurz aufgetaucht und wieder verschwunden — insgesamt eine Sekunde" |
| 2 | 506 | laufen stabil | steht und bleibt |

**Das ist nicht deterministisch**, und es war nur zu sehen, weil der erste Versuch schiefging.
Ein frisch gesetztes Objekt kann sofort wieder abgeräumt werden, ohne Exception, ohne Meldung —
der Aufruf meldet `ERFOLG` und eine Objekt-ID wie immer.

**Folge für die Brügge:** Sie darf sich nicht darauf verlassen, dass ein gesetztes Objekt auch
bleibt. Nach dem Setzen gehört eine Lagemeldung abonniert (`RequestDataOnSimObject`,
`PERIOD_SECOND`); bleibt sie aus, ist das Objekt weg und muss neu gesetzt werden. Das
Probe-Skript macht genau das ohnehin — deshalb fiel es überhaupt auf.

Die Ursache ist **nicht gemessen**. Denkbar ist ein Wettlauf beim Laden der Szenerie; der erste
Versuch lief kurz nach dem Flugstart.

## Was daraus für den Kieker folgt

Die Entscheidungsfrage ist positiv beantwortet — das Tor ist offen. Drei Dinge sind dabei
herausgekommen, die den Zuschnitt betreffen und vor dem Weiterbauen bedacht sein wollen:

1. **Der Spawner muss mitlaufen.** Objekte sterben mit der Verbindung. Das spricht für genau
   das, was Schritt 4 erwogen hat: ein Begleitprozess, der über `exe.xml` mitstartet — und der
   dann auch gleich die Position ans FriesenSpy melden kann (Issue #23), ohne dass das
   EFB-Panel offen sein muss.
2. **Die Reality Bubble begrenzt das Anlegen nicht.** Bis 10.000 km wurde jedes Objekt
   angenommen, mit geländerichtiger Höhe. Der Spawner darf also getrost eine ganze Kollektion
   über Ostfriesland verteilen, statt der Position hinterherzulaufen. **Offen bleibt nur, ob
   ein weit entfernt gesetztes Objekt beim Hinkommen auch gezeichnet wird** — Sichtbarkeit ist
   nur im Nahbereich belegt. Das ist die nächste Messung, und sie braucht einen echten Flug.
3. **Höhe muss nicht gerechnet werden.** `OnGround=1` setzt sauber auf Gelände wie auf Wasser.

## Was ausdrücklich nicht gemacht wurde

Kein Paket, keine `manifest.json`, kein WASM, keine Änderung an `app/` oder der Datenbank,
kein Robbenmodell, kein Eintrag in `exe.xml`, keine Messung, wie viele Objekte der Sim
verträgt. Und nicht gepusht — nur lokal committet, weil ein Deploy den Container neu startet
und offene Kniebretter abreißt.
