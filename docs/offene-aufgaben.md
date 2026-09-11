# Offene Aufgaben

Vom Nutzer vorgemerkt, noch nicht begonnen. **Diese Liste ist kein Ideenspeicher** — was hier
steht, ist gewollt; was erledigt ist, wird gelöscht (die Geschichte steht im Changelog).

Am Projekt arbeiten mehrere Sitzungen parallel, auch in der Cloud. Vor dem Start also pullen
und prüfen, ob eine andere die Aufgabe schon erledigt hat.

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
| Eigene Position lesen | SimVars | Datarefs `sim/flightmodel/position/latitude` / `longitude` / `elevation` |
| Höhe über Grund | nur über Umwege | `sim/flightmodel/position/y_agl` — **direkt vorhanden** |
| Erweiterungssprache | externes Programm über `exe.xml` **und** WASM-Modul — beides **gemessen**, ein Quelltext für 2020+2024 | XPLM-Plugin (C) — **gebaut und gelaufen** |
| Objektart bestimmt die Höhe | **ja** — `Boat` auf Meereshöhe, `Animal`/`StaticObject`/`GroundVehicle` auf Geländehöhe | Terrain-Probe für alles |
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
   — der simulatorfreie Vertrag, Fassung 1. Daneben entstehen `msfs/` (für 2020 **und** 2024)
   und `xplane/`. Die Server-Seite kennt nur das Protokoll und nie ein SimObject.
   **Vom Nutzer noch nicht abgenommen.**
4. Der Positions-Endpunkt (#23) sollte von vornherein so beschrieben werden, dass ein
   X-Plane-Plugin ihn ohne Änderung bedienen kann — das kostet jetzt nichts.
5. **Neu:** Ein X-Plane-Probeflug, der dasselbe belegt wie der MSFS-Probeflug — Objekt
   entsteht, bleibt liegen, ist sichtbar. Braucht einen Rechner mit X-Plane.

## Forum

- Thema heißt noch **„V13 - Platzhirsch"**, live ist V14 „Zettelwirtschaft". Umbenennen hieße,
  den **ersten Beitrag des Themas** zu ändern — dafür fehlt bislang die ausdrückliche Freigabe.
