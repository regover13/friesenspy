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

### Was belegt ist und wodurch

| Frage | Antwort | Beleg |
|---|---|---|
| Wird der Aufruf angenommen? | ja | Objekt-IDs 50937856 / 103202816 / 103202817, keine Exception |
| Wird wirklich etwas gezeichnet? | **ja** | Screenshot 08:15:06, Boot in voller Textur mit Schatten |
| Bleibt es liegen? | **ja** | 180 Lagemeldungen über 180 s, Koordinate auf 5 Nachkommastellen unverändert |
| Liegt es auf der Oberfläche? | ja, `OnGround=1` genügt | Land 2,4 ft, Wasser 0,0 ft — der Sim setzt selbst auf |
| Überlebt es die Verbindung? | **nein** | Nachprobe: `EXCEPTION 3 — UNRECOGNIZED_ID` |

Die Sichtprüfung **auf dem Wasser** steht noch aus (Lauf 3 lief ohne Screenshot ab); die
Lagemeldung sagt 0,0 ft, was die richtige Höhe ist, aber ein Bild ist es nicht.

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

## Was daraus für den Kieker folgt

Die Entscheidungsfrage ist positiv beantwortet — das Tor ist offen. Drei Dinge sind dabei
herausgekommen, die den Zuschnitt betreffen und vor dem Weiterbauen bedacht sein wollen:

1. **Der Spawner muss mitlaufen.** Objekte sterben mit der Verbindung. Das spricht für genau
   das, was Schritt 4 erwogen hat: ein Begleitprozess, der über `exe.xml` mitstartet — und der
   dann auch gleich die Position ans FriesenSpy melden kann (Issue #23), ohne dass das
   EFB-Panel offen sein muss.
2. **Die Reality Bubble begrenzt, wo gesetzt werden kann.** Objekte entstehen in der Nähe des
   Flugzeugs, nicht irgendwo auf der Welt. Der Spawner muss also der Position folgen und
   nachsetzen, statt einmalig eine Kollektion über Ostfriesland zu verteilen. Wie weit die
   Bubble reicht, ist **nicht gemessen** — 200 m und 1,6 km gingen, die Grenze ist offen.
3. **Höhe muss nicht gerechnet werden.** `OnGround=1` setzt sauber auf Gelände wie auf Wasser.

## Was ausdrücklich nicht gemacht wurde

Kein Paket, keine `manifest.json`, kein WASM, keine Änderung an `app/` oder der Datenbank,
kein Robbenmodell, kein Eintrag in `exe.xml`, keine Messung, wie viele Objekte der Sim
verträgt. Und nicht gepusht — nur lokal committet, weil ein Deploy den Container neu startet
und offene Kniebretter abreißt.
