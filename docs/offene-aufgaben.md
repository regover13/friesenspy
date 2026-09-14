# Offene Aufgaben

Vom Nutzer vorgemerkt, noch nicht begonnen. **Diese Liste ist kein Ideenspeicher** — was hier
steht, ist gewollt; was erledigt ist, wird gelöscht (die Geschichte steht im Changelog).

Am Projekt arbeiten mehrere Sitzungen parallel, auch in der Cloud. Vor dem Start also pullen
und prüfen, ob eine andere die Aufgabe schon erledigt hat.

---

## ⚠ Zwei Titel lassen sich nicht setzen — und es liegt NICHT am Streaming

Gefunden beim Lasttest mit 200 gemischten Objekten: Von 402 Anforderungen scheiterten 25,
ausschließlich in zwei Arten.

| Art | Fehlschläge | MSFS-Titel | Quelle |
|---|---|---|---|
| `mast` | 14 | `VO_Fire_R1_150` … `_200` | `streamed` |
| `kran` | 11 | `Microsoft_Truck_Crane_Small` … | `streamed` |

Beide Arten **haben** Titel — die Brügge hat alle durchprobiert und `KEIN_MODELL_MEHR`
gemeldet. Der Rückfall funktionierte also genau wie gebaut; es gab nur nichts, worauf er
hätte fallen können.

### ⭐ BEIDE naheliegenden Erklärungen sind widerlegt (Archiv-Messung, 14.09.2026)

Hier stand zuerst „die Ursache liegt in der Natur des Streamings" und daneben die
Vermutung, `VO_Fire_R1_*` seien gar keine SimObjects. **Beides stimmt nicht** — nachgesehen
mit [`fsarchive.py`](../friesenbruegge/fsarchive.py) in den Archiven selbst.

⭐ **Und im Simulator gegengeprüft (14.09.2026, MSFS bei Rügen):**
`Microsoft_Aerial_Tank` — aus **demselben Paket** wie die gescheiterte Truck_Crane — wurde
gezielt gesetzt und meldete `steht`. Damit ist auch das Paket als Ursache erledigt; es
liegt an einzelnen Titeln.

**Verzeichnis: Es sind SimObjects, beide.**

```
fs24-microsoft-vertical-obstructions   450 Dateien, 6 sim.cfg
    simobjects\landmarks\vo_r1_fire\model.r1_fire_100\model.cfg
    simobjects\landmarks\vo_r1_fire\model.r1_fire_105\model.cfg   … je Höhe ein Modell

fs24-microsoft-simobjects-vehicles     293 Dateien, 66 sim.cfg
    simobjects\groundvehicles\microsoft_truck_crane_small\sim.cfg   ← eigene sim.cfg
```

Die Truck_Crane ist ein lupenreines SimObject mit eigener `sim.cfg` unter `groundvehicles`.
Die VO_Fire liegen unter `simobjects\landmarks\` — auch dort richtig, nur anders gebaut:
**ein** SimObject `vo_r1_fire` mit rund 70 Höhenvarianten als Modelle; die Titel stammen aus
`[fltsim.N]`-Einträgen einer gemeinsamen `sim.cfg`.

**Streaming: erklärt es auch nicht.** Der Gegenbeleg steht im eigenen Katalog:

| Titel | Paket | quelle | lokal | Ergebnis |
|---|---|---|---|---|
| `windmill`, `windsock` | `fs24-asobo-simobjects-landmarks` | **streamed** | nur `minimal.fsarchive`, 0,6 MB | **steht** |
| `Microsoft_Truck_Crane_Small` | `fs24-microsoft-simobjects-vehicles` | streamed | nur `minimal.fsarchive`, 0,4 MB | `KEIN_MODELL_MEHR` |

Alle drei Pakete liegen ausschließlich unter `StreamedPackages` als Hüllarchiv von unter
1 MB — inhaltlich ist nichts davon auf der Platte. **Ein gestreamtes Paket funktioniert,
zwei nicht.** `quelle='streamed'` ist als Erklärung damit erledigt, und die gute Nachricht
darin: Die 2642 Titel sind nicht pauschal gefährdet.

### Was daraus folgt

- **Eine Art sollte nie nur gestreamte Titel haben.** Mindestens einer aus `bord` oder
  `community` gehört ans Ende der Liste, sonst fällt die ganze Art aus. Das bleibt richtig,
  auch wenn die Begründung eine andere ist als gedacht — es ist schlicht Vorsorge gegen
  einen Ausfall, dessen Ursache wir noch nicht kennen.
- **`mast` und `kran` sind derzeit X-Plane-eigen**, obwohl der Katalog MSFS-Titel zeigt.
  Entweder stilllegen oder setzbare Titel suchen.

### ⭐ Die nächste Messung, und sie ist billig

**`Microsoft_Aerial_Tank` setzen** — oder irgendeinen der 66 Titel mit eigener `sim.cfg` aus
`fs24-microsoft-simobjects-vehicles`, also demselben Paket wie die gescheiterte Truck_Crane.

| Ausgang | Schluss |
|---|---|
| steht | es liegt am einzelnen Titel, die Truck_Crane ist ein Sonderfall |
| scheitert auch | es liegt am Paket — dann lohnt der Vergleich mit `fs24-asobo-simobjects-landmarks`, dem einzigen gestreamten Paket, aus dem nachweislich etwas steht |

⚠ **Eine Spur, die noch niemand verfolgt hat:** `windmill`/`windsock` tragen im Katalog die
Kategorie `Landmarks` (groß), die gescheiterten `vertical`/`simobjects` (klein). Groß heißt:
aus `katalog_sammeln.py`, dem Verzeichnislauf. Klein heißt: aus `fsarchive.py`. **Die beiden
Erfassungswege könnten unterschiedlich verlässliche Titel liefern** — bei den VO_Fire
besonders, weil dort ein Titel aus `[fltsim.N]` stammt und nicht aus einem Verzeichnisnamen.

## ✅ Die Brügge stellt Flugzeuge hin — beantwortet am 14.09.2026

**`AICreateSimulatedObject` nimmt Flugzeugtitel an.** Die Frage, die hier stand, ist im Flug
erledigt: Mi-2-Helikopter und Bonanzas standen sichtbar im Simulator. Ein eigener Aufruf
(`AICreateNonATCAircraft`) wird dafür nicht gebraucht.

**Was dabei schiefging, war etwas anderes** — `mi2-1 flugzeug_ga ✖ GATTUNG_UNBEKANNT`. Das
ist kein Simulator-, sondern ein Artenproblem: Die Titel waren der Art noch nicht zugeordnet.
Wer diesen Fehler sieht, schaut in `bruegge_katalog`, nicht in die SimConnect-Doku.

⚠ **Und eine Falle, die dreimal zugeschlagen hat:** Gesetzt wurden Titel, die es nur auf dem
Rechner des Nutzers gibt (Black Square Bonanza, Superspuds Vieh, Digital Aeronautics Mi-2).
FRS123 bekam jedes Mal `EXCEPTION_22`. Die Information stand die ganze Zeit im Katalog
(`quelle='community'`). **Vor jedem Setzen für andere: `quelle` prüfen.**

### Was davon offen bleibt

| Art | Stand |
|---|---|
| `flugzeug_klassik` | leer — kein Simulator bringt einen statischen Oldtimer mit |
| `ballon` | MSFS 2024 hat einen Heißluftballon, aber **als Flugzeug** — er steht deshalb nicht im Katalog |

**`katalog_sammeln.py` erfasst die Kategorie `Airplanes` weiterhin nicht** — es durchsucht in
MSFS nur `SimObjects/{Animals,Boats,GroundVehicles,Landmarks,Misc}`, und die 14 Treffer unter
`Airplanes` sind Sitze (`SEAT_*`). Jetzt, wo belegt ist, dass Flugzeuge sich setzen lassen,
wäre die Erweiterung ein lohnender Lauf: Sie brächte die Standflugzeuge, die heute nur über
den gemeldeten Titel des eigenen Flugzeugs in den Katalog finden.

---

## ⭐ Soll die FriesenBrügge auch OHNE VATSIM arbeiten? (offen, 14.09.2026)

**Die Frage stellt sich seit heute Abend konkret** (s. den Zwei-Simulatoren-Fall in
[`PROTOKOLL.md`](../friesenbruegge/PROTOKOLL.md)): Wer nicht auf VATSIM ist, bekommt keine
Objekte — auch nicht mit gültiger Kennung, weil der Server bei jeder Meldung die Position
gegen `live_positions` prüft.

**Für den FriesenKieker ist das eine echte Lücke.** Wer das Zählen üben will, ohne online zu
gehen, kann es heute nicht. Dasselbe trifft jeden, der einen zweiten Simulator daneben
laufen hat.

⚠ **Der Preis ist nicht klein:** Die Positionsprüfung ist der einzige Schutz davor, dass
eine fremde Kennung fremde Objekte auslöst. Fällt sie weg, zählt die Kennung allein — und
die ist ausdrücklich **kein Geheimnis** (s. PROTOKOLL, „kennung — dauerhaft, je
Installation, kein Geheimnis"). Ein Weg wäre ein ausdrücklicher Übungsmodus, den der Pilot
im Admin für seine eigene Kennung einschaltet; dann ist die Entscheidung bei ihm und nicht
im Protokoll.

**Nicht begonnen** — der Nutzer hat die Frage noch nicht entschieden.

---

## AIP-Kartenblätter: was noch von Hand durchzusehen ist

Stand 31.08.2026, aus der Datenbank. **Die beiden früher hier offenen Sichtflugkarten (EDDN,
EDMR) sind gepasst** — der Nutzer hat sie von Hand gesetzt.

Nach dem Rückbau der Automatik (31.08.2026) sagt der Status, ob ein **Mensch** die Karte
angesehen hat. Danach steht:

| Sorte | Status | Zahl | Was zu tun ist |
|---|---|---|---|
| Sichtflugkarte | `gepasst` | 171 | nichts |
| Sichtflugkarte | `auto` | 275 | durchsehen; bestätigen macht daraus `gepasst` |
| Flugplatzkarte | `auto` | 30 | dito — von Claude gesetzt, vom Nutzer ungeprüft |
| Flugplatzkarte | `offen` | 10 | Blatt liegt vor, Lage fehlt |
| Rollkarte | `auto` | 38 | durchsehen |
| Rollkarte | `offen` | 32 | Blatt liegt vor, Lage fehlt |

**`auto` heißt ungeprüft, nicht falsch.** Der Status stirbt aus, sobald der Nutzer eine Karte
durchsieht; neu entsteht er nur, wenn er Claude eine Passung aufträgt.

**Die 336 Plätze ohne Flugplatzkarten-Zeile stehen als „nicht nachgesehen".** Der alte
Bestandslauf hat sie durchaus geprüft und dort kein Blatt in Flugplatzkarten-Farbe gefunden —
dieses Ergebnis wurde aber nie festgehalten, es fiel mit der Automatik weg. Das ist kein
Datenverlust, sondern die ausdrückliche Absicht: „Vielleicht finde ich ja eine geeignete
Karte, die du nicht gefunden hast." Wer nachsieht und keine findet, hält das jetzt mit
„keine passende Seite" fest — dann steht dort `nicht gefunden` statt „nicht nachgesehen".

**Die 13 Plätze mit auffälligen OurAirports-Längen** (EDAK, EDAZ, EDBH, EDPH, EDSI, EDMB,
EDLA, EDQA, EDNG, EDQC, EDRB, EDLP, dazu EDDN/EDDS) wurden beim maschinellen Passen
übersprungen, weil dort Stopways in derselben Grauabstufung wie die Bahn gezeichnet sind und
die Längenmessung verfälschten (EDDV: 2784 m für eine 2340-m-Bahn). Von Hand ist das kein
Hindernis — man klickt die Schwellen, statt sie zu messen.

## ✅ Robben für den Kieker — eigenes Modell, erledigt am 14.09.2026

**Es gibt in KEINEM der beiden Simulatoren eine Robbe.** Das ist keine Vermutung mehr,
sondern das Ergebnis von vier Durchgängen:

| durchsucht | Ergebnis |
|---|---|
| MSFS 2020/2024 — 45 Tiertitel und 41 Tierpakete | nichts |
| MSFS — 2642 Titel aus den gestreamten `.fsarchive` | nichts |
| X-Plane 12 — alle 1146 Bordobjekte | nichts |
| X-Plane — die Szeneriebibliothek | nichts |

Damit ist auch die Reihenfolge hinfällig, die hier bis zum 14.09.2026 stand
(*„Abhängigkeit jetzt, fragen parallel, eigenes Modell nur wenn nötig"*). Sie ging von
einer Annahme aus, die sich als falsch erwies: **Superspuds `human-library-animated` ist
ein MSFS-Paket.** Für das Drittel der Gruppe, das X-Plane fliegt, hätte es nie etwas
gelöst — und genau dieses Drittel ist der Grund, warum die Brügge überhaupt zwei
Simulatoren spricht.

**Die Anfrage an ihn ist ins Leere gelaufen:** Der Autor war zuletzt vor rund einem Jahr
online (die Addon-Seite nennt Version 1.4 vom Oktober 2025, und der Nutzer hat es am
14.09.2026 selbst nachgesehen). Auf eine Antwort zu warten, war kein Weg.

### Was stattdessen entstanden ist

Ein eigener Seehund, aus **„Walrus" von Poly by Google** ([poly.pizza/m/5T7nIjx9ekP](https://poly.pizza/m/5T7nIjx9ekP)),
Lizenz **CC BY 3.0** — Änderung und Weitergabe ausdrücklich erlaubt, Bedingung ist allein
die Namensnennung. Von vier freien Modellen ausgewählt, weil es als einziges **flach
liegt**; die beiden „Sea lion" sitzen aufrecht wie im Zoo. Die Pose entscheidet, nicht der
Dateiname — und von oben wird gezählt.

Drei Größen nach den Angaben der Seehundstation Norddeich und des Deutschen Jagdverbands:
Bulle 1,80 m, Kuh 1,60 m, Heuler 0,85 m. Eine Liegegruppe besteht aus allen dreien; zwanzig
gleich große Tiere sähen von oben nach Tapete aus.

Alles Weitere — Bauskripte, Fallen, Maße — steht in
[`friesenbruegge/seehund/LIESMICH.md`](../friesenbruegge/seehund/LIESMICH.md).

### ✅ In beiden Simulatoren abgenommen (14.09.2026)

X-Plane zuerst (*„sind da"*), dann MSFS an denselben Koordinaten (*„alles OK jetzt"*).
Zwischendurch 200 Seehunde in fünf Rudeln und 200 gemischte Objekte aus dreizehn Arten —
*„sieht gut aus. lass sie stehen"*. Einzelheiten in
[`friesenbruegge/MESSLISTE.md`](../friesenbruegge/MESSLISTE.md).

### ⚠ Was offen bleibt

**Die Sichtweite in MSFS.** Der Seehund hat eine Bounding Sphere von 1,86 m, und MSFS
entscheidet die Sichtbarkeit über genau diese Größe — `minSize="0"` wird überstimmt.
Gemessen ist der Zusammenhang am Rauch: ein 2-m-Träger verschwand bei **100 m**, ein
90-m-Träger trug **1830 m**. Dazwischen ist nichts ausgemessen.

Der Weg ist bekannt und beim Rauch erprobt: ein **unsichtbarer Trägerquader**
(`ASOBO_material_invisible`), der die Bounding Box vergrößert, ohne gezeichnet zu werden.
Hochgerechnet braucht es rund 20 m für 1 km Sichtweite. ⚠ Er muss **auf** dem Ursprung
stehen, nicht um ihn herum — `auf_boden` setzt den Ursprung auf Geländehöhe, ein zentrierter
Quader steckte zur Hälfte im Watt.

⚠ **Ungeprüft ist dabei, ob MSFS unsichtbare Geometrie überhaupt mitzählt.** Beim Rauch war
der Träger immer unsichtbar, es fehlt der Gegenversuch. Bringt der Quader nichts, ist das
die erste Stelle zum Nachsehen.

**Und die Farbe.** Dass die Tiere stehen, ist belegt; ob die Palettentextur greift, hat
niemand ausdrücklich bestätigt.

⚠ **`DistanceToNotAnimate=2000` ist gesetzt, aber der Mechanismus ist beim Seehund
ungeprüft.** Beim Rauch gibt es einen nachvollziehbaren Zusammenhang — ein Partikel-Emitter
läuft ohne Animation nicht. Ein Seehund ist starre Geometrie; es gibt daran nichts zu
animieren. Der Wert steht dort, weil Aerosofts Wangerooge-Paket ihn bei **allen** SimObjects
setzt, nicht weil seine Wirkung belegt wäre.

⚠ **Und was ein animiertes Objekt über große Entfernung kostet, ist ungemessen.** Bei einer
Handvoll Baaken egal — bei hundert Seehunden gehört es gemessen, bevor der Kieker Kolonien
setzt.

### Was von der alten Fassung gilt

⚠ **Für alle übrigen Addon-Objekte bleibt es dabei** (SayIntentions-Rauch, p42-Fackeln,
Campout-Zubehör, und weiterhin Superspuds Tiere): Sie im Katalog zu führen und ihre Titel zu
nennen ist unbedenklich; sie in ein eigenes Paket zu kopieren wäre es nicht. **Einen Titel zu
nennen ist keine Weitergabe.** Bei SayIntentions wiegt das besonders schwer — das ist ein
Abo-Dienst, und die README erlaubt nichts dergleichen.

Superspuds Titel stehen weiterhin in der Art `robbe`, aber **hinter** unseren: Wer sein
Addon hat, bekommt als Zugabe die animierte Robbe; alle anderen brauchen nichts weiter.

## X-Plane mitdenken (vorgemerkt 11.09.2026)

**Alles, was gerade an Simulator-Anbindung entworfen wird, setzt stillschweigend MSFS voraus.**
Der Nutzer hat vorgemerkt, dass X-Plane mitgedacht werden muss — **bevor** das erste Paket
gebaut wird, nicht danach.

Betroffen sind zwei laufende Vorhaben:

- **#20 FriesenKieker** — der Spawner, der Objekte setzt. Hängt an `SimConnect`, das es in
  X-Plane nicht gibt.
- **#23 Kniebrett meldet die Position zurück** — hängt heute an der MSFS-2024-EFB-App.

**Warum das jetzt zählt und nicht später:** Nur **4 von 61 Piloten** haben überhaupt eine
Kniebrett-Gerätebindung (`panel_devices`, Stand 11.09.2026, alle vier in den letzten 60 Tagen
aktiv). Ein Weg, der ausschließlich über die MSFS-2024-EFB-App führt, erreicht also einen sehr
kleinen Teil der Gruppe.

### Die Verteilung — vom Nutzer beantwortet (11.09.2026)

> **Etwa ein Drittel der Gruppe fliegt X-Plane.** Der Rest MSFS 2024, **wenige** noch MSFS 2020.

Bei 61 Piloten sind das rund **20 X-Plane-Flieger**. Damit kehrt sich die Annahme um, unter der
die Kieker-Spec geschrieben wurde:

- **X-Plane ist kein Vorbehalt, sondern der zweite Hauptweg.** Ein MSFS-only-Eventtyp schlösse
  ein Drittel der Gruppe aus — mehr als jede andere Einschränkung, die bisher diskutiert wurde.
- **MSFS 2020 ist der Randfall**, nicht X-Plane. Genau andersherum als gedacht. Und selbst der
  kostet fast nichts, s. unten.

Der VATSIM-Feed meldet den Simulator nicht; die Zahl stammt aus der Kenntnis des Nutzers über
die Gruppe und ist nicht gemessen.

### Was sicher ist und was nicht

**Sicher unproblematisch: die Server-Seite.** Wertung, Deckungsprüfung, Endpunkte und
Datenmodell des Kiekers sind simulator-agnostisch — sie rechnen mit Koordinaten, Höhe und
Zeit. Auch der Positions-Endpunkt aus #23 fragt nicht, wer meldet. **Dort ist nichts
verbaut.**

**Simulator-spezifisch ist ausschließlich das Paket.** Der ursprünglich vorgesehene Ordnername
`msfs-kieker/` schrieb MSFS fest; er heißt seit dem 11.09.2026 **`friesenbruegge/`**, und der
MSFS-Probeflug liegt darin als `probe-msfs/`. Der Entwurf dazu steht in **#25** — eine
event-unabhängige Brücke, die für alle drei Simulatoren dasselbe Protokoll spricht.

**Zum Namen** (Nutzerentscheidung, 11.09.2026): Zwischenzeitlich hieß der Ordner `sim-bruecke/`.
Das war beschreibend, fiel aber aus dem Schema — FriesenFlieger, FriesenKutter, FriesenBummel,
FriesenKieker. **`Brügge`** ist das ostfriesische Platt für Brücke (`de Brügg`, auch `Brügge`,
Pl. `de Brüggen`; [Wörterbuch der Ostfriesischen Landschaft](https://www.platt-wb.de/platt-hoch/?term=Br%C3%BCgg)).
Dasselbe Wort bezeichnet die **Schiffsbrücke** — und nebenbei das Butterbrot. Der Ordner heißt
ohne Umlaut `friesenbruegge/`, wie das Repo `friesenspy` heißt; geschrieben wird der Name
**FriesenBrügge**.

### Was gemessen ist — und was noch nicht

Am 11.09.2026 wurde der größte Teil dieser Tabelle **am Gerät nachgemessen**, in allen drei
Simulatoren. Wo „gemessen" steht, liegt ein Protokoll und meist ein Screenshot dazu
([MSFS](../friesenbruegge/probe-msfs/ERGEBNIS.md), [X-Plane](../friesenbruegge/probe-xplane/ERGEBNIS.md));
alles Übrige ist weiterhin nur gelesen und **vor jeder Planung zu bestätigen.**

| Frage | MSFS 2020 + 2024 | X-Plane |
|---|---|---|
| Objekte zur Laufzeit setzen | `SimConnect_AICreateSimulatedObject` — **in 2024 und 2020 gemessen**, sichtbar, 400 Stück ohne Ruckeln | `XPLMInstance` — **gemessen**, sichtbar, 150 s stabil |
| Objekt benennen | Container-Titel (`Boat01`) — **gemessen** | Pfad `…/dynamic/SailBoat.obj` — **gemessen** |
| Eigenes 3D-Modell nötig? | **nein** — Boote liegen bei | **nein** — Boote, Plattformen, Hirsche, Möwen liegen bei |
| Lebensdauer der Objekte | **nur solange die Verbindung offen ist** — gemessen | Instanz gehört dem Plugin — 150 s belegt, Entladen ungeprüft |
| Eigene Position lesen | SimVars — **extern gemessen; aus WASM heraus gescheitert** (`EXCEPTION 3`) | Datarefs `sim/flightmodel/position/latitude` / `longitude` / `elevation` — **gemessen** |
| Höhe über Grund | SimVar `PLANE ALT ABOVE GROUND`; der Umweg über die Platzhöhe betrifft nur das EFB im Browser | `sim/flightmodel/position/y_agl` — **direkt vorhanden** |
| Erweiterungssprache | externes Programm über `exe.xml` **und** WASM-Modul — beides **gemessen**, ein Quelltext für 2020+2024 | XPLM-Plugin (C) — **gebaut und gelaufen** |
| Objektart bestimmt die Höhe | **nur in MSFS 2020** — dort landet `Boat` auf Meereshöhe (Bodensee: 395 m zu tief), alles andere auf Geländehöhe. **In MSFS 2024 findet auch `Boat` den Grund** (Wangerooge gemessen, Binnensee dort ungeprüft) | Terrain-Probe für alles |
| Zählbare Tiere mitgeliefert | **ja** — Bär, Elefant, Giraffe, Nilpferd; gesetzt und gesehen | **ja** — Hirsche, Möwen |
| Tablet-Oberfläche wie das EFB | ja (MSFS 2024) | kein Gegenstück |

**Ein Punkt sticht heraus:** X-Plane liefert die **Höhe über Grund direkt**. Die Spec zu #20
musste sich in Abschnitt 4.2 ausdrücklich auf MSL beschränken, weil FriesenSpy kein
Geländemodell hat. Für X-Plane fiele diese Einschränkung weg — was den Kieker über Land
(Norwegen, Berge) erst richtig brauchbar machte. Das ist ein Argument **für** X-Plane, nicht
nur eine Pflichtübung.

### MSFS 2020 und 2024 sind EIN Adapter, nicht zwei (gemessen 11.09.2026)

Drei Befunde aus dem Probeflug, die zusammen deutlich sind:

- **Dieselben Container-Titel.** In MSFS 2020 liegen die Boote unter
  `Official/OneStore/asobo-simobjects-boats`, in MSFS 2024 unter
  `StreamedPackages/`**`fs20`**`-asobo-simobjects-boats` — MSFS 2024 liefert das 2020er Paket
  mit. Beide Male `Boat01`, `FishingBoat`, `Yacht01`.
- **Beide SDK-DLLs exportieren `SimConnect_AICreateSimulatedObject`** (per `ctypes` geprüft,
  nicht vermutet). Die SDK-Doku nennt als einzigen Schritt für 2024: gegen den neuen Header neu
  kompilieren.
- **SimConnect verbindet sich zu dem Simulator, der läuft.** Ein über `exe.xml` mitgestartetes
  Programm findet den, der es gestartet hat.

**Am 11.09.2026 nachgemessen — es gilt auch praktisch.** MSFS 2020 gestartet, die **2024er**
DLL dagegen laufen lassen:

```
SimConnect.dll: C:\MSFS 2024 SDK\SimConnect SDK\lib\SimConnect.dll
SimConnect_Open: verbunden.
  Flugzeug steht bei 53.78633 / 7.91037, 10 ft.
  ERFOLG: Objekt-ID 463 (Anfrage 4711).
  t=+  31.6s  53.78633 / 7.91341      0.0 ft   (Objekt 463 lebt)
  DURCHGEHEND DA: 40 Lagemeldungen ueber 40s, bis zum Schluss.
  WEG: EXCEPTION 3 -- UNRECOGNIZED_ID
```

Verbindung, Container-Titel `Boat01`, Objektlebensdauer, Sterben beim `Close` — **alles
identisch zu MSFS 2024**. Damit ist „ein Adapter für beide" nicht mehr hergeleitet, sondern
gemessen. Zwei DLLs mitzuliefern erübrigt sich.

**Auch die Sichtbarkeit ist belegt**, und das war nötig: Beim ersten Versuch (`Boat01`, 40 s,
200 m entfernt) hat der Pilot **nichts gesehen** — ein kleines Motorboot auf einem Grasplatz
ist leicht zu übersehen, und die Zeit war knapp. Das sah für einen Moment nach dem
schlimmsten Fall aus: Sim führt das Objekt, zeichnet es aber nicht. Zweiter Versuch mit
`CruiseShip01`, 150 m entfernt, zehn Minuten Standzeit — Screenshot 10:47:13 zeigt ein
vollständig texturiertes Kreuzfahrtschiff mit Schattenwurf auf der Graspiste von Wangerooge,
neben zwei geparkten Maschinen.

**Lehre für jede weitere Sichtprüfung:** groß, nah und lange. Ein „nichts gesehen" bei einem
kleinen Objekt mit kurzer Standzeit ist kein Befund, sondern eine zu knappe Gelegenheit.

Zwei Randbeobachtungen: Die Objekt-IDs sind in MSFS 2020 klein (445, 463) statt achtstellig wie
in 2024 — kein Verlass auf Wertebereiche. Und der allererste Lauf lieferte nur **eine**
Lagemeldung; der unmittelbar folgende war normal. Vermutlich lud der Simulator noch. Wer
gleich nach dem Start misst, sollte einen zweiten Lauf machen, bevor er etwas daraus schließt.

### X-Plane braucht kein eigenes 3D-Modell (recherchiert 11.09.2026, nicht gemessen)

Das war die befürchtete Hürde: In MSFS genügt ein **Container-Titel**, X-Plane dagegen lädt mit
`XPLMLoadObject` eine **`.obj`-Datei aus dem Dateisystem**. Ein eigenes Modell hätte den
X-Plane-Weg von vornherein teuer gemacht.

**Die Befürchtung trifft nicht zu.** X-Plane bringt ladbare Objekte mit, angesprochen über
einen Pfad relativ zum X-System-Ordner — und darunter ist ausgerechnet ein Boot:

```
Resources/default scenery/sim objects/dynamic/SailBoat.obj
```

Dazu kommt eine Bibliothek virtueller Pfade (`Resources/default scenery/sim objects/library.txt`,
z. B. `lib/airport/vehicles/fuel/hyd_disp_truck.obj`). Damit steht dem X-Plane-Adapter dasselbe
offen wie dem MSFS-Adapter: mitgeliefertes Objekt, kein Blender, keine Lizenzfrage.
Quellen: [XPLMLoadObject](https://developer.x-plane.com/sdk/XPLMLoadObject/),
[XPLMScenery](https://developer.x-plane.com/sdk/XPLMScenery/),
[XPPython3-Doku](https://xppython3.readthedocs.io/en/latest/development/modules/scenery.html).

**Eine Falle ist schon bekannt:** In X-Plane 12 stürzt `XPLMLoadObject()` ab, wenn es in
`XPluginStart`/`XPluginEnable` aufgerufen wird und das Objekt einen Emitter hat — Objekte
gehören in einen Flight-Loop-Callback. Ebenso müssen die Datarefs, die ein Objekt animiert,
vorher geladen sein.

### ✅ Am 11.09.2026 gemessen — X-Plane trägt auch

X-Plane 12 wurde installiert, ein Plugin gebaut, und die Kette lief lückenlos: Datarefs
gefunden, Geländehöhe per `XPLMProbeTerrainXYZ` (335,11 m), `XPLMCreateInstance`, Position
gesetzt, `XPLMInstanceSetAutoShift` aktiv, danach über 150 s Lebenszeichen.
**Screenshot 11:29:34** zeigt ein voll texturiertes Segelboot mit Schattenwurf auf einer Wiese.

Alle sieben Annahmen der Tabelle oben haben gehalten — **einschließlich des Pfads**, der aus
einer XPPython3-Doku stammte und die heikelste war. Einzelheiten in
[`friesenbruegge/probe-xplane/ERGEBNIS.md`](../friesenbruegge/probe-xplane/ERGEBNIS.md).

**Unerwartete Zugabe:** X-Plane liefert neben Booten auch `OilPlatform`, `OilRig`, eine
Fregatte, **Hirsche** und **Möwen** als fertige Objekte mit — für einen Zähl-Event reichhaltiger
als MSFS' Bootssortiment und der Robben-Idee näher als alles, was Asobo für 2024 ausliefert.

**Und das lief in der kostenlosen Demo.** Damit ist auch die letzte Vorplanungsfrage
beantwortet: Eine Demo-Installation lädt Plugins und führt sie vollständig aus. Wer aus der
Gruppe die Brügge ausprobieren soll, **braucht X-Plane nicht zu kaufen** — ein Test kostet
25 GB Plattenplatz und sonst nichts. (Die Demo beschränkt nur die *detaillierte* Szenerie auf
Seattle; fliegen lässt sie einen überall — der Flug lief im Alpenraum.)

**Offen bleibt nur,** ob eine Instanz das Entladen des Plugins überdauert — für den Zuschnitt
belanglos, weil die Brügge ohnehin durchläuft.

### Erst zu klären, bevor etwas gebaut wird

1. ~~Wer in der Gruppe fliegt X-Plane?~~ **Beantwortet: etwa ein Drittel.**
2. ~~Lohnt sich ein zweites Paket?~~ **Ja** — bei rund 20 Piloten steht es außer Frage.
3. ~~Ordnerstruktur und Namensgebung **vor** dem ersten Paket-Commit festlegen.~~
   **Geschrieben am 11.09.2026:** [`friesenbruegge/PROTOKOLL.md`](../friesenbruegge/PROTOKOLL.md)
   — der simulatorfreie Vertrag, Fassung 1, einmal adversarisch gegengeprüft. Daneben
   entstehen `msfs/` (für 2020 **und** 2024) und `xplane/`. Die Server-Seite kennt nur das
   Protokoll und nie ein SimObject. **Vom Nutzer noch nicht abgenommen.**
4. ~~Der Positions-Endpunkt (#23) sollte so beschrieben werden, dass ein X-Plane-Plugin ihn
   ohne Änderung bedienen kann.~~ **Erledigt:** `POST /api/bruegge/melden` trägt Position und
   Sollzustand in einer Anfrage und kennt keinen Simulator. #23 ist auf denselben Stand
   gebracht — **ein Endpunkt, zwei Quellen, eine Prüfung.**
5. ~~Ein X-Plane-Probeflug.~~ ✅ **Erledigt am 11.09.2026** (s. unten).

### Was seit dem Protokoll entschieden ist

Vier Entscheidungen des Nutzers vom 11.09.2026, die alles Weitere binden:

- **Keine Anmeldung, kein Schlüssel.** Der Server erkennt den Piloten über das
  Positionsmatching — mit **denselben Regeln, die das EFB schon benutzt**
  (`_verkehrZusammenfuehren`). Damit wandert kein Geheimnis in eine Textdatei und von dort mit
  einem Community-Ordner auf fremde Rechner.
- **Geprüft wird die CID**, nicht das Callsign: eine Zeile in `forum_callsign` beweist den
  Forum-Login. Am Callsign zu prüfen bräche beim N-Verlust (`FRS123N` → `FRS556`), weil die
  Tabelle erst beim *nächsten* Login nachzieht.
- **Der Regeltakt ist 1 s.** Gemessen statt geschätzt: Die Spitze liegt bei 13 gleichzeitig
  fliegenden Friesen (30 Tage), das Mittel bei 1,58. Voraussetzung ist eine eigene nginx-Zone.
- **Ohne VATSIM geschieht nichts** — keine Zuordnung, keine Anzeige, keine Objekte. Das ist
  zugleich die billigste Prüfung, die es gibt.

### Noch zu messen, bevor gebaut wird

| Frage | warum sie zählt |
|---|---|
| ~~WASM kann die eigene Position nicht lesen~~ — **gelöst am 11.09.2026** | Es war eine ID-Kollision im eigenen Quelltext: `DEF_LAGE` und `CD_DEF` standen beide auf 1, und beide leben im selben Nummernraum. Nach dem Auseinanderziehen: 441 Lagemeldungen, Position korrekt. **WASM bleibt als Auslieferungsweg im Rennen.** |
| ~~Wie lange lebt ein vom WASM-Modul gesetztes Objekt?~~ — **geklärt** | Sie verschwinden nicht: 364 s, vier Objekte, von zwei unabhängigen Clients bestätigt. Das frühere „Boot ist fort“ war eine Fehlmessung — es stand bei 0°/90° im Indischen Ozean. |
| ~~`OnGround=1` wirkt in WASM nicht~~ — **gemessen und mit Ausweg** | Dreimal bestätigt: rund 49 ft statt 5,3 ft Boden. `OnGround=0` mit expliziter Höhe trifft dagegen exakt — die Brügge rechnet die Geländehöhe aus `PLANE ALTITUDE − PLANE ALT ABOVE GROUND`. Offen bleibt nur, ob die 49 ft ein fester Wert sind (alle Läufe am selben Ort). |
| ~~Wird ein weit gesetztes Objekt gezeichnet, wenn der Pilot hinkommt?~~ — **geflogen am 11.09.2026: ja** | Aus 44,7 km gesetzt, bei 22,1 km zweifelsfrei gesehen (EDWG→EDWY, MSFS 2024). **Der Server darf einmal verteilen.** Fuer MSFS 2020 und X-Plane noch offen — Anleitung in `friesenbruegge/probe-msfs/FLUGTEST.md`. |
| **Ab welcher Entfernung wird `hoehe_ft` unbrauchbar?** | Brauchbar bis 200 km gemessen und bei 45 km im Flug bestätigt (Wasserlinie über die ganze Strecke); falsch bei 691 km (2106,5 statt 1297,2 ft am selben Punkt). Die Grenze liegt dazwischen — und die Zahl entscheidet, wann der Server einer Höhenmeldung glauben darf. |
| SmartScreen bei unsignierter EXE | betrifft nur den externen Weg |

