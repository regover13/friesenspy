# Welche Objekte gibt es? — Titel je Simulator

**Nachschlagewerk für die Tabelle `bruegge_katalog` auf dem Server.** Der Server nennt eine
**Art** und liefert die Titel gleich mit (PROTOKOLL.md, Abschnitt 3).

> ### ⚠ Umgekehrt seit dem 14.09.2026
>
> Hier stand: *„Nachschlagewerk für `titel_fuer` in `msfs/bruegge.cpp`. Welches Modell daraus
> wird, entscheidet die Brügge, weil nur sie ihren Simulator kennt."*
>
> **Die Brügge entscheidet das nicht mehr.** Ihre Tabelle `g_gattungen[]` ist entfernt — in
> beiden Umsetzungen, zusammen rund 320 Zeilen. Die Zuordnung steht im Katalog des Servers,
> und dieses Dokument beschreibt, was dort drinsteht und warum.
>
> Der Grund ist das Leitbild des Protokolls (*„Die Brügge ist dumm"*) und ein doppelter Preis:
> Eine neue Art kostete einen Windows-Build und eine Verteilung an 61 Piloten — und die
> Tabelle wusste nichts darüber, was tatsächlich funktioniert. Drei ihrer Titel scheiterten
> nachweislich seit dem 12.09.2026, sie probierte sie trotzdem bei jedem Fehlversuch durch.
>
> **Was daraus für dieses Dokument folgt:** Es ist eine *Fundgeschichte*, kein Verzeichnis.
> Das Verzeichnis ist die Datenbank; hier steht, warum etwas drinsteht.

> ### ⚠ Diese Listen sind AUSGELESEN, nicht recherchiert
>
> Eine Websuche brachte am 12.09.2026 nichts Brauchbares: Die offizielle SDK-Doku beschreibt
> `AICreateSimulatedObject`, nennt aber **keine Titel**; Community-Seiten listen Add-ons statt
> Bordmittel. Die Titel unten stammen aus der Installation selbst — das ist die einzige
> Quelle, die auch stimmt, wenn Asobo etwas umbenennt.

> ### ⚠ Und sie waren zuerst UNVOLLSTÄNDIG — `find` steigt nicht in Symlinks
>
> Die Suchbefehle unten laufen über `LocalCache\Packages`. Der **Community-Ordner liegt dort
> als Sammlung von Symlinks** (Addons Linker), und `find` folgt ihnen ohne `-L` nicht. Damit
> blieben 32 Tier-SimObjects unsichtbar, die direkt neben der Behauptung „keine Robben"
> lagen — darunter der Seehund, um den sich der ganze FriesenKieker dreht (s. Abschnitt
> „Robben" unten).
>
> **Wer den Bestand erhebt, nimmt `find -L`** — oder liest den Community-Ordner an seinem
> echten Ort (hier `E:\Addons\Community`) zusätzlich.

---

## 📚 Der Katalog — 1693 setzbare Objekte, einzeln geprüft (13.09.2026)

**Alles hier Genannte ist im laufenden MSFS 2024 gesetzt worden**, Titel für Titel
(`probe-msfs/katalog_pruefen.py`). Der Bestand liegt in der Tabelle `bruegge_katalog` auf dem
Server; `friesenbruegge/katalog_sammeln.py` liest ihn von der Platte, `katalog_hochladen.py`
schiebt ihn hoch.

| Quelle | gesamt | **setzbar** | nicht |
|---|---|---|---|
| MSFS 2024, Community-Addons | 1417 | **1417** | 0 |
| MSFS 2020, Community-Addons | 119 | **119** | 0 |
| MSFS 2020, Bordmittel | 200 | **155** | 45 |
| gestreamte Platzhalter | 53 | 2 | 13 |
| X-Plane 12 | 1146 | *offen* | — (aber s. Gattungstabelle unten: 22 Pfade einzeln nachgesehen) |

**Was aus einer `sim.cfg` eines installierten Pakets kommt, lässt sich setzen — ausnahmslos.**
1536 von 1536 Addon-Titeln. Der einzige nennenswerte Ausfall sind **Tiere im Bordbestand**:

| Kategorie (MSFS-2020-Bestand) | setzbar | nicht |
|---|---|---|
| Humans | **75** | 0 |
| GroundVehicles | 30 | 7 |
| Misc | 18 | 0 |
| Boats | 14 | 0 |
| Landmarks | 11 | 0 |
| **Animals** | **7** | **38** |

⚠ **Die 75 Menschen sind ein Fund für sich** — sie stehen im Bordbestand, brauchen also kein
Addon: Wanderer, Läufer, Strandgänger, Arbeiter, Bodenpersonal, Piloten.

### Rauch und Feuer — was im Cockpit wirklich zu sehen war

| Titel | Paket | gesehen? |
|---|---|---|
| `SIAI_VFX_Smoke_Red` | SayIntentions | ✅ **rote Säule, auffällig** |
| `Smoke_Volcano` | **Bordmittel** | ✅ sichtbar, aber unspektakulär |
| `item_flare_red/blue/green/yellow` | p42-util-campout-mp | vier Farben, gesetzt |
| `winter_fire_bucket`, `item_gas_cooker_fire_red` | p42-util-campout-mp | winzig, als Marke untauglich |

⚠ **„Setzbar" heißt nicht „sichtbar".** Der Katalog misst nur, ob der Simulator ein Objekt
anlegt — ob man es sieht, sagt allein der Blick aus dem Cockpit. Bei VFX-Objekten ist das
keine Formsache: Sie können als unsichtbare Hülle dastehen.

---

## ⚠ Woher stammt was — und was mutet das den Piloten zu?

**Die Frage entscheidet über den Zuschnitt** (Nutzerfrage, 12.09.2026): *„Davon hängt ab, was
wir Piloten zumuten, oder ob wir sie extrahieren und in ein eigenes Paket schneiden."*

### Was GEMESSEN ist

| Gattung | Titel aus | auf diesem Rechner |
|---|---|---|
| `tier_gross`, `tier_wasser` | `BlackBear`, `GrizzlyBear`, `SyrianBear`, `HumpbackWhale` | **MSFS-2020-Installation** (`Microsoft.FlightSimulator…`) |
| `boot_klein`, `boot_gross` | `Boat01` … `CruiseShip02` | ebenda |
| `bauwerk`, `marke` | `Windmill`, `Flag_*` | ebenda (`windmill` klein auch im 2024-Bestand) |
| `fahrzeug` | `ASO_*` | ebenda |
| **`robbe`, `tier_klein/vieh/wild`** | `ahqa …` | **`human-library-animated`** (Superspud, Community) |
| **`rauch`, `feuer`** | `SIAI_*` | **`SayIntentions-SimObjects-Optional`** (Community) |
| **`punkt`, `kegel`** | `SI_SimObject_*` | **`sayintentions-fly-in-library`** (Community) |
| **`himmel`** | `southoakco_aurora1`, `Parachute` | **`southoakco-auroraborealis`** + 2020-Bestand |

### ⚠ Was NICHT gemessen ist — und die wichtigste offene Frage

**Alle Bordmittel-Titel wurden auf diesem Rechner gefunden, und dieser Rechner hat MSFS 2020
UND 2024 installiert.** Ob ein Pilot mit **nur MSFS 2024** `BlackBear` oder `Boat01` bekommt,
ist **ungeprüft**.

Zwei Indizien, die sich widersprechen:

- **Dafür:** `UserCfg.opt` von MSFS 2024 zeigt **ausschließlich** auf den eigenen Paketordner
  (`Microsoft.Limitless…`) — es greift nicht in die 2020-Installation hinein. Die Titel müssen
  also aus dem eigenen Bestand oder dem Streaming kommen.
- **Dagegen:** Im eigenen Bestand ist nichts davon zu finden. `Official2020/OneStore` enthält
  **ein einziges Flugzeug**, und `fs24-asobo-simobjects-animals` ist ein **16-KB-Platzhalter**
  (`minimal.fsarchive`, eine Datei). Auch die 41 Tierpakete bestehen aus je einer Sounddatei.

**Die wahrscheinliche Erklärung ist das Streaming:** MSFS 2024 lädt Inhalte bei Bedarf aus der
Cloud, die lokalen Dateien sind nur Marker. Dann hätte jeder Pilot die Titel. **Belegen lässt
sich das hier nicht** — dafür bräuchte es einen Rechner ohne MSFS 2020.

**Bis dahin gilt:** Die Gattungen sind im Admin in zwei Gruppen geteilt („Bordmittel" und
„braucht ein Community-Paket"). Fehlt ein Titel, rückt der nächste nach; fehlen alle, meldet
die Brügge `EXCEPTION_22` statt still etwas Falsches hinzustellen. **Ein Event, das auf
Bordmittel setzt, ist also in jedem Fall auf der sicheren Seite** — und wenn sich zeigt, dass
ein Pilot ohne MSFS 2020 leer ausgeht, fällt das sofort auf, statt still falsch zu zählen.

### Und die Idee, Objekte zu extrahieren?

**Technisch** wäre es ein eigenes Paket mit `SimObjects/<Name>/sim.cfg` plus Modell — dass ein
solcher Titel von der Brügge gesetzt wird, ist belegt (`ahqa seal moving` stammt genau aus so
einem Paket).

⚠ **Rechtlich ist es etwas anderes.** Asobos und Superspuds Modelle weiterzugeben ist eine
Weitergabe fremder Werke; **einen Titel zu nennen dagegen nicht** — die Brügge sagt nur
„stell ein `ahqa seal moving` hin", und ob es existiert, entscheidet die Installation des
Piloten. Die beschlossene Reihenfolge steht in
[`../docs/offene-aufgaben.md`](../docs/offene-aufgaben.md): **jetzt Abhängigkeit** (funktioniert,
braucht keine Erlaubnis), **parallel fragen**, **eigenes Modell nur wenn nötig**.

---

## MSFS 2020 — `sim.cfg` liegt als Datei vor

```bash
P=".../Microsoft.FlightSimulator_8wekyb3d8bbwe/LocalCache/Packages"
find "$P" -path "*SimObjects/Animals/*" -name "sim.cfg" \
  -exec grep -ohiE '^\s*title\s*=\s*"?[^";]+' {} \;
```

**Tiere (45 Titel):** `AfricanElephant`, `AfricanElephant_Child`, `AfricanGiraffe`,
`AngolanGiraffe`, `AsianElephant`, `AsianElephant_Child`, **`BlackBear`**, `BorneoElephant`,
`BorneoElephant_Child`, `Flamingo`, `Goose`, `GrizzlyBear`, `Hippo`, `HippoChild`,
`HippoFeetInWater`, `HippoIdle2`, `HippoIdle3`, `HippoInWater`, `HippoUnderWater`,
`HippoUnderWaterStatic`, `Horse_black`, `Horse_brown`, `Horse_cream`, `Horse_grey`,
`Horse_white`, `HumpbackWhale`, `MasaiGiraffe`, `PolarBear`, `ReticulatedGiraffe`, `Rhino02`,
`RhinoBlack`, `RhinoBlackWestern`, `RhinoWhite`, `RhinoWhiteChild`, `RhinoWhiteIdle2`,
`RhinoWhiteIdle3`, `RhinoWhiteNorthern`, `Seagull`, `SriLankanElephant`,
`SriLankanElephant_Child`, `SriLankanElephant_Child_Albino`, `SumatranElephant`,
`SumatranElephant_Child`, `SumatranElephant_Child_Albino`, `SyrianBear`

⚠ **Keine Robben, keine Seehunde** — nicht im Bordbestand. Für den FriesenKieker ist das der
wichtigste Eintrag dieser Liste: Was gezählt werden soll, bringt der Simulator nicht mit.
`devprops-counting-seals-frisian-islands` löst das über **Szenerie**-Objekte (BGL), nicht über
SimObjects — und Szenerie lässt sich nicht zur Laufzeit setzen.

⭐ **Seit dem 14.09.2026 bringt die Brügge einen eigenen Seehund mit** — s. Abschnitt
„Robben" unten. Der Befund gilt inzwischen breiter als diese Liste: Auch in den **2642
gestreamten Titeln** (`fsarchive.py`) und in X-Planes gesamtem Bestand gibt es keine.

**Boote (14):** `Boat01`, `Boat02`, `CargoContainer01`, `CargoGas01`, `CargoOil01`,
`CargoShip01`, **`CruiseShip01`**, `CruiseShip02`, `FishingBoat`, `FishingShip02`,
`FishingShip03`, `Yacht01`, `Yacht02`, `Yacht03`

**Landfahrzeuge (37):** `ASO_Aircraft_Caddy`, **`ASO_Ambulance_Japan`**, `ASO_BaggageTruck01`,
`ASO_Baggage_Cart01`, `ASO_Baggage_Cart02`, `ASO_Boarding_Stairs`, `ASO_Boarding_Stairs_Red`,
`ASO_Boarding_Stairs_Yellow`, `ASO_CarFacillity01_Black`, `ASO_CarFacillity01_White`,
`ASO_CarUtility01`, `ASO_Catering_Truck_01`, `ASO_Firetruck01`, `ASO_Firetruck02`,
`ASO_FuelTruck01_Black`, `ASO_FuelTruck01_White`, `ASO_FuelTruck02_Black`,
`ASO_FuelTruck02_White`, `ASO_Ground_Power_Unit`, `ASO_LoaderCab_Red`, `ASO_LoaderCab_White`,
`ASO_Operation_Truck_White`, `ASO_Operation_Truck_Yellow`, `ASO_Pushback_Blue`,
`ASO_Pushback_White`, `ASO_Shuttle_01_Gray`, `ASO_Shuttle_01_Yellow`,
`ASO_TruckFacility01_Black`, `ASO_TruckFacility01_White`, `ASO_TruckFacility01_Yellow`,
`ASO_TruckUtility01`, `ASO_Tug01_White`, `ASO_Tug02_White`, `Aso_Baggage_Loader_01`

---

## MSFS 2024 — `sim.cfg` ist gepackt, die ORDNERNAMEN tragen die Titel

MSFS 2024 legt keine `sim.cfg` als Datei ab (deshalb fand die Titelsuche der Probe hier
nichts). Die Modelle stecken in `StreamedPackages`, und der Ordner heißt wie der Titel:

```bash
P=".../Microsoft.Limitless_8wekyb3d8bbwe/LocalCache/Packages"
for d in $(find "$P" -type d -name Animals -path "*SimObjects*"); do ls "$d"; done | sort -u
```

**41 Tierpakete** sind angelegt (`fs24-microsoft-simobjects-animals-*`): aardvark, anteater,
antelope, bear, bison, bongo, buffalo, camel, capra, capybara, cheetah, chimp, cow, crocodile,
deer, elephant, elk, gazelle, giraffe, gnu, goat, hippo, horse, hyena, kangaroo, leopard,
lion, llama, monkey, moose, ostrich, panda, reindeer, rhino, sheep, tiger, vulpes, warthogs,
wolf, zebra.

⚠ **Wieder keine Robben.**

**Lokal entpackt und damit sofort nutzbar** (der Rest wird gestreamt):
`Bear_U_Maritimus`, `Bison_B_Bison`, `Buffalo_S_Caffer_Caffer`, `Horse_E_Przewalskii`,
`Sheep_O_Dalli_Dalli`, `Wolf_C_Lupus_Albus`, `deer_o_hemionus`, `gnu_c_taurinus_taurinus`,
`hippo_h_amphibius`, `ostrich_s_camelus_camelus`, `reindeer_r_tarandus_groenlandicus`

**Landmarks:** `windmill`, `windsock`, `Windsock_05`, `Windsock_08`, `Windsock_NoBase`

⚠ **Zwei Namensschemata nebeneinander.** 2024 nutzt wissenschaftliche Namen
(`Bear_U_Maritimus`), 2020 schlichte (`BlackBear`) — und **beide funktionieren in MSFS 2024**
(`BlackBear`, `Boat01`, `CruiseShip01`, `Windmill` sind dort im Flug belegt). Die alten Titel
sind also nicht verschwunden, nur ergänzt.

⚠ **Aber nicht alle:** `ASO_Ambulance_Japan` existiert **nur** unter
`Microsoft.FlightSimulator` (2020), nicht unter `Microsoft.Limitless` (2024). Genau daran
scheiterte die Gattung `fahrzeug` am 12.09.2026 mit `EXCEPTION_22` — und weil dort **ein
einziger** Titel stand, fiel die ganze Gattung aus. Seit Fassung 1.3.0 rückt bei einer
Ausnahme der nächste Titel nach.

---

## Robben — ⭐ seit dem 14.09.2026 EIGENES MODELL

> ### Die Lage hat sich gedreht, und zwar aus einem Grund, der lange übersehen wurde
>
> Bis zum 14.09.2026 hing die Art `robbe` vollständig an Superspuds Community-Paket. Der
> Plan war: Abhängigkeit jetzt, ihn um Erlaubnis fragen, eigenes Modell nur im Notfall.
>
> **Sein Paket ist ein MSFS-Paket.** Für das Drittel der Gruppe, das X-Plane fliegt, hätte
> es nie etwas gelöst — und dieses Drittel ist der Grund, warum die Brügge überhaupt zwei
> Simulatoren spricht. Die Frage war also nie „eigenes Modell oder seins", sondern nur
> „wann".
>
> Dazu kam: **Es gibt in keinem der beiden Simulatoren eine Robbe.** Vier Durchgänge —
> MSFS' 45 Tiertitel und 41 Tierpakete, die 2642 Titel aus den gestreamten `.fsarchive`,
> X-Planes 1146 Bordobjekte, dessen Szeneriebibliothek. Und die Anfrage an Superspud lief
> ins Leere; er war zuletzt vor rund einem Jahr online.
>
> **Seit dem 14.09.2026 gibt es einen eigenen Seehund** in drei Größen, für beide
> Simulatoren, aus „Walrus" von Poly by Google unter CC BY 3.0. Einzelheiten in
> [`seehund/LIESMICH.md`](seehund/LIESMICH.md).
>
> Superspuds Titel stehen weiterhin in der Art — aber **hinter** unseren: Wer sein Addon
> hat, bekommt als Zugabe die animierte Robbe. Alles darunter gilt unverändert und bleibt
> stehen, weil es die Ausgangslage erklärt.

Beide Simulatoren bringen keine mit. **Ein Community-Paket schon**, und zwar in genau der Form,
die `AICreateSimulatedObject` braucht — nicht als Szenerie:

`human-library-animated` (Freeware, `creator: Superspud`, v1.4.0, 556 MB, 32 Tier-SimObjects),
in MSFS 2024 verlinkt, in MSFS 2020 **nicht**. Ausgelesen aus
`E:\Addons\Community\human-library-animated\SimObjects\Animals\*\sim.cfg`:

| Titel | Modell | Dateien |
|---|---|---|
| `ahqa seal moving` ✅ | Seehund, Bounding-Box 0,74 × 1,53 × 0,31 m | 186 KB glTF + `.bin`, 131 KB DDS |
| `ahqa sea lion moving` | Seelöwe | 380 KB |
| `ahqa walrus moving` | Walross | 224 KB |
| `ahqa puffin walking` | Papageitaucher | — |

`category=Animal`, zwei Animationen (`Default_State`, `sealmove`), glTF 2.0 mit
`ASOBO_asset_optimized` — also fertig kompiliert, nicht rohes Blender-Material. Die Textur
liegt per `texture.CFG`-Fallback im Nachbarordner (`ahqa Deer Running\texture`), beim
Umpacken also mitnehmen.

⚠ **Das ist dasselbe Paket, das `counting seals` seit immer als Abhängigkeit hat** — dort
werden die Modelle aber über GUIDs aus `Hummods.BGL` als **Szenerie** platziert. Seine
SimObject-Seite hat nie jemand angefasst.

**Gattung `robbe` (Fassung 1.4.0) trägt diese drei Titel, bewusst ohne Rückfall auf den
Bordbestand:** Fiele sie still auf `BlackBear` zurück, lieferte der Kieker eine Zahl, während
am Strand Bären liegen. Eine fehlende Robbe muss als `EXCEPTION_22` sichtbar werden.

✅ **Gemessen am 12.09.2026 (parallele Sitzung):** `ahqa seal moving` wurde mit
`probe-msfs/titel_schau.py` gesetzt und gezeichnet — Screenshot mit Robbe und Kuh im Bild.
**`AICreateSimulatedObject` findet also auch Community-Titel**, nicht nur Asobos Bordbestand.
Ein eigenes Robben-Paket scheitert damit nicht mehr am Verfahren.

⚠ **Noch offen:** derselbe Weg über die Brügge (WASM statt externer Client) — s. Messliste 8.

**Die ganze Bibliothek ist animiert.** Alle dreißig Tiere tragen `walking`, `running` oder
`moving` im Namen; die Bewegung steckt im Modell, nicht in einem SimConnect-Befehl. Damit
erledigt sich die Frage, wie man Beine und Kopf bewegt — und es entsteht die umgekehrte:
ob eine Robbe namens „moving" am Strand liegen bleibt (Messliste 8, Prüfpunkt 2).

**Für die Gattung heißt das:** Superspuds Robbe zuerst, ein eigenes Modell als zweiter Titel.
Die Nachrück-Mechanik nimmt dann das Addon, wo es installiert ist, und das eigene Modell bei
allen anderen — kein Pilot wird ausgeschlossen, und wer das Addon hat, bekommt eine bewegte
Robbe. **Was weiterhin nicht passieren darf, ist ein Rückfall auf eine andere ART** (Bär,
Schaf): Gezählt wird hier eine bestimmte Art, nicht „irgendein Tier".

---

## ⭐ Addon-Bibliotheken — die eigentliche Fundgrube (12.09.2026)

**Ein SimObject aus einem Community-Addon lässt sich genauso setzen wie ein Bordmittel.** Die
Brügge merkt keinen Unterschied; es zählt allein, ob der Titel auf dem Rechner des Piloten
existiert. Auf diesem Rechner liegen **1417 Addon-Titel** in 15 Paketen.

⚠ **Der Preis:** Wer das Addon nicht hat, bekommt das Objekt nicht. **Dafür ist die Titelliste
je Gattung da** (`g_gattungen` in `bruegge.cpp`, seit Fassung 1.3.0): erst das schöne
Addon-Modell, dann ein Bordmittel als Rückfall. Scheitert der erste Titel, rückt der nächste
automatisch nach.

### 🦭 `human-library-animated` (Superspud) — Tiere, und zwar BEWEGTE

**Der wichtigste Fund für den FriesenKieker.** 30 Tiere, alle mit `walking`, `running` oder
`moving` im Namen — **die Animation steckt im Modell**, es braucht keine SimConnect-API:

```
ahqa seal moving        ← die ROBBE, im Screenshot belegt
ahqa sea lion moving    ahqa walrus moving    ahqa puffin walking
ahqa Deer Running       ahqa stag walking     ahqa moose bull/cow walking
ahqa boar walking       ahqa fox walking      ahqa wolf running   ahqa coyote walking
ahqa cow walking (+ highland, longhorn, longhorn_c1)   ahqa sheep walking
ahqa goat walking       ahqa pig walking      ahqa donkey walking
ahqa shetland pony walking   ahqa chicken walking   ahqa goose walking
ahqa crocodile walking  ahqa gazelle walking  ahqa buffalo african walking
ahqa ibex walking       ahqa dog 1/4 walking
```

**Robbe, Seelöwe, Walross und Papageitaucher** — das Wattenmeer-Sortiment, fertig und animiert.
Damit erledigt sich die Frage, wie man Beine und Kopf bewegt (s. MESSLISTE 2d): **gar nicht
über SimConnect, sondern über die Wahl des Modells.**

### 🔥 `SayIntentions-SimObjects-Optional` — Feuer und Rauch

```
SIAI_VFX_Smoke_Red   SIAI_VFX_Smoke_Orange   SIAI_VFX_Fire
SIAI_SignalFire      SIAI_VFX_WildFire       SIAI_SmokeCanister
```

⚠ **Das löst ein gemessenes Problem:** Ein `Boat01` ist erst ab rund **1 km** eingeblendet
(11.09.2026), ein `CruiseShip01` ab 22 km. Eine **Rauchsäule** sieht man kilometerweit — damit
findet ein Pilot eine Station, ohne dass die Koordinate auf zehn Meter stimmen muss. Dazu
Radfahrer (`ahqm cyclist …`).

### 🎯 `sayintentions-fly-in-library` — Marken für Events

```
SI_SimObject_Fly-In_Landing_Blue/Green/Red/Yellow_Dot    farbige Landepunkte
SI_SimObejct_Cone                                        Kegel
SI_SimObejct_Event_Parking_Signs_Left/Right/Straight      Wegweiser
```

Vier Farben — genug, um Stationen zu unterscheiden, ohne Text lesen zu müssen.

### Und der Rest

| Paket | was drin ist |
|---|---|
| `p42-util-campout-mp` | **Hunde** in 14 Rassen, Futternäpfe, Campingzeug |
| `superspud-airport-edxh-duene-2024models` | **Helgoland-Düne**: `helgosachsen`, `OLTIslander`, Windsack, Flaggen |
| `southoakco-auroraborealis` | **Polarlichter** `southoakco_aurora1`–`4` |
| `aerosoft-airfields-east-frisian-islands` | `Strandkorb_1`, `Schild_RWY10`, Parkpositionen |
| `hangar8-airport-edkb-bonn` | statische Flugzeuge, Hallen |
| `aerosoft-modellib-vdgs` | Andockleitsysteme |

**Alle hier genannten Titel sind gesetzt und gezeichnet worden**, außer wo anders vermerkt.

**So findet man weitere:**

```bash
C=".../LocalCache/Packages/Community"
find -L "$C" -path "*SimObjects/*" -name sim.cfg   -exec grep -ohiE '^[[:space:]]*title[[:space:]]*=[[:space:]]*"?[^";]+' {} \;
```

⚠ **`-L` ist Pflicht** — viele Community-Pakete sind Symlinks, und ohne `-L` übersieht die
Suche sie. Beim ersten Anlauf fand sie so 265 statt 1417 Titel.

---

## X-Plane 12 — **schon gemessen, s. `probe-xplane/ERGEBNIS.md`**

> ⚠ **Dieser Abschnitt stand hier zuerst als Web-Recherche. Das war überflüssig:** Am
> 11.09.2026 wurde X-Plane 12 bereits im Probeflug vermessen, mit einem eigenen Plugin und
> Sichtbestätigung. Die Belege stehen in
> [`probe-xplane/ERGEBNIS.md`](probe-xplane/ERGEBNIS.md) — **erst dort nachsehen, dann
> suchen.**

**Mitgelieferte Objekte** in `Resources/default scenery/sim objects/dynamic/` (auf der Platte
nachgesehen, nicht aus einer Doku):

| Datei | wofür |
|---|---|
| `SailBoat.obj` | im Flug belegt — gesetzt und gesehen |
| `OilPlatform.obj`, `OilRig.obj` | passt zur Nordsee |
| `Perry.obj` | Fregatte |
| **`deer_buck.obj`, `deer_doe.obj`** | **Tiere** |
| **`seagull_far/flap/glide.obj`** | **Möwen**, in drei Flugzuständen |

Dazu rund 8.000 weitere `.obj` in `Resources/`, u. a. eine ganze Schiffsflotte
(`sim objects/ships/`: `Cruiser_1200_01`, `Dinghy_360_01`, `Whaler_470_01` …).

**Für einen Zähl-Event ist das reichhaltiger als MSFS' Sortiment** — Hirsche und Möwen stehen
der Robben-Idee näher als alles, was Asobo mitbringt.

### Der Mechanismus

| | MSFS | X-Plane 12 |
|---|---|---|
| Objekt benennen | `title` aus `sim.cfg` | **Dateipfad** zur `.obj` |
| Koordinaten | `lat`/`lon` direkt | lokale Meter, `XPLMWorldToLocal` |
| erzeugen | `SimConnect_AICreateSimulatedObject` | `XPLMLoadObject` + `XPLMCreateInstance` |
| bewegen | entfernen und neu erzeugen | `XPLMInstanceSetPosition` — **echtes Verschieben** |
| entfernen | `SimConnect_AIRemoveObject` | `XPLMDestroyInstance` |
| **auf den Boden** | Sonde mit `OnGround=1` (s. MESSLISTE 2c) | **`XPLMProbeTerrainXYZ`** |

### ⚠ Und das wiegt am schwersten: X-Plane kann das Gelände direkt fragen

**`XPLMProbeTerrainXYZ` lieferte im Probeflug 335,11 m** — eine echte Geländeabfrage an einer
beliebigen Koordinate, ohne dass etwas gesetzt werden müsste.

**Der ganze Sondenumweg in MSFS (Objekt setzen, Höhe ablesen, wegräumen — MESSLISTE 2c) ist
der Ersatz für eine Funktion, die X-Plane einfach mitbringt.** Wer die Brügge portiert, baut
ihn dort nicht nach.

**Das bestätigt zugleich den Entwurf:** Der Server nennt eine **Gattung**, keinen Modellnamen
und keine Höhe — sonst wäre das Protokoll an MSFS gekettet. Eine X-Plane-Brügge bildet
`tier_gross` auf `deer_buck.obj` ab, fragt das Gelände selbst und meldet dieselbe
`steht`-Struktur zurück. Der Server merkt vom Unterschied nichts.

**Quellen:** [`probe-xplane/ERGEBNIS.md`](probe-xplane/ERGEBNIS.md) (gemessen) ·
[XPLMInstance](https://developer.x-plane.com/sdk/XPLMInstance/) ·
[XPLMScenery](https://developer.x-plane.com/sdk/XPLMScenery/)

### Die Gattungstabelle der X-Plane-Brügge (13.09.2026)

Alle Pfade stehen relativ zum X-System-Ordner und sind **auf der Platte nachgesehen**, jeder
einzeln (`xplane/bruegge.cpp`). Der gemeinsame Anfang `Resources/default scenery/sim objects/`
ist weggelassen.

| Gattung | Modelle, in dieser Reihenfolge |
|---|---|
| `tier_gross` | `dynamic/deer_buck.obj`, `dynamic/deer_doe.obj` |
| `tier_wild` | dieselben — ein Hirsch **ist** Wild |
| `tier_klein` | `dynamic/seagull_glide.obj`, `…_flap.obj`, `…_far.obj` |
| `bauwerk` | `dynamic/OilPlatform.obj` (63 MB, weithin sichtbar), `dynamic/OilRig.obj`, `legacy env files/radio_tower.obj` |
| `boot_klein` | `dynamic/SailBoat.obj` ✅, `ships/Sail_1000_01.obj`, `ships/Runabout_750_01.obj`, `ships/Dinghy_400_01.obj` |
| `boot_gross` | `dynamic/Perry.obj` (Fregatte, ~135 m), `ships/Cruiser_1900_01.obj`, `ships/Cruiser_1200_01.obj` |
| `marke` | `dynamic/balloon1-3.obj`, `landscape/windsock_orange.obj` |
| `punkt` | `landscape/buoy.obj`, `landscape/radar.obj` |

✅ = im Probeflug gesetzt und im Bild gesehen (11.09.2026)

### ✅ Am 13.09.2026 geflogen — sechs Gattungen auf einmal, alle gesehen

Gesetzt aus dem Stand auf einem Rollweg (47,80461 / 12,99683, Boden 1403,7 ft), eine Reihe
nach Osten. **Screenshot: Hirsch, Segelboot, Boje, Heißluftballon mit Schattenwurf, und die
Ölplattform — alle sichtbar, alle auf dem Boden.**

| Objekt | Abstand | gemeldete Höhe |
|---|---|---|
| Hirsch (`tier_gross`) | 5 m | 1403,7 ft |
| Möwe (`tier_klein`) | 8 m | 1403,7 ft |
| Segelboot (`boot_klein`) | 16 m | 1403,4 ft |
| Boje (`punkt`) | 24 m | 1403,3 ft |
| Ballon (`marke`) | 45 m | 1402,7 ft |
| Ölplattform (`bauwerk`) | 120 m | **1400,5 ft** |

⭐ **Das ist der Befund, der X-Plane von MSFS trennt.** Das Gelände fällt nach Osten um gut
drei Fuß ab, und **jedes Objekt sitzt auf seiner eigenen Höhe** — jedes einzeln geprobt, alle
mit `hoehe_gemessen: true`. In MSFS bekämen alle sechs die Höhe unter dem Flugzeug: Genau so
standen am 12.09.2026 zwölf Objekte in einem Raster von 180 m, eines versunken, eines sauber,
eines schwebend.

**Nebenbei belegt:**

- **Abräumen.** Fünf der sechs aus `soll` genommen → beim nächsten Takt fort, nur der Hirsch
  meldete weiter.
- **Umsetzen.** Der Hirsch von 5 m auf 60 m — er meldete danach 1402,3 ft statt 1403,7, war
  also wirklich dort. ⚠ Und `seit_s` lief dabei **weiter** (74 s), statt bei null neu zu
  beginnen: In X-Plane wird dieselbe Instanz verschoben, in MSFS muss sie weg und neu hin.
  Wer `seit_s` als „seit wann steht es dort" liest, liest es in X-Plane falsch.
- **Die Kennung übersteht einen Neustart** (`Kennung gelesen`, dieselbe wie vorher). Genau
  daran ist die MSFS-Fassung anfangs gescheitert.
- **`alt_agl_ft` ist 0,0, während das Flugzeug 4 ft über dem Boden meldet.** X-Planes
  `elevation` misst den Referenzpunkt des Musters (bei der Cirrus SR22 rund 1,2 m über Grund),
  `y_agl` dagegen das Fahrwerk. Wer aus `alt_msl_ft - alt_agl_ft` die Geländehöhe rechnet —
  der MSFS-Weg —, liegt hier um die Fahrwerkshöhe daneben. In X-Plane braucht es das nicht,
  die Probe antwortet direkt.

⚠ **Ohne VATSIM war das nicht zu messen**, und das hat an diesem Abend eine Stunde gekostet:
Der Server liefert `soll` nur an einen zugeordneten Piloten, und der VATSIM-Client (xPilot)
fand seinen eigenen Simulator nicht. Deshalb gibt es jetzt
[`pruefserver.py`](pruefserver.py) — er spielt den Server, und eine Datei
`Output/preferences/friesenbruegge.url` biegt die Brügge auf ihn um. **Der Weg gilt für jede
Brügge**, auch für MSFS 2020, wenn die drankommt.

⭐ **Der Heißluftballon ist das X-Plane-Gegenstück zur Rauchsäule.** In MSFS löst `rauch` das
Problem, dass ein Boot erst ab rund 1 km eingeblendet wird; X-Plane kennt keine
Rauchobjekte — aber ein Ballon steht in der Luft und ist kilometerweit zu sehen. Für jedes
Event, bei dem jemand etwas *finden* soll, zählt das mehr als das genauere Modell am Boden.

### ⚠ Was die X-Plane-Brügge NICHT kann — und warum das so dasteht

Sie meldet diese Gattungen gar nicht erst in `kann`; der Server fordert sie damit bei einem
X-Plane-Piloten nicht an (PROTOKOLL.md, Abschnitt 3).

| Gattung | Grund |
|---|---|
| `fahrzeug` | X-Plane 12 bringt **kein Bodenfahrzeug als eigenständige `.obj`** mit. Was am Flughafen fährt, liegt in der Szenerie-Bibliothek (`lib/airport/vehicles/…`) und ist nur über `XPLMLookupObjects` erreichbar, nicht über `XPLMLoadObject`. Gangbar, aber ungemessen. |
| `robbe`, `tier_vieh`, `tier_wasser` | kein Modell im Bordbestand, und kein Addon-Gegenstück zu `human-library-animated` gemessen |
| `feuer` | X-Plane zeichnet Feuer über Partikelsysteme, nicht über Objekte. Für **Rauch gilt das seit dem 13.09.2026 nicht mehr** — die Säulen liegen als eigenes Werk im Paket, s. unten. |
| `kegel` | keine Pylone im Bordbestand |

⚠ **Die dicken Pötte fallen aus, und das ist ein Katalogfund:** `BulkCarrier`,
`ContainerCarrier`, `OilTanker` und `LNGCarrier` liegen **nur als `.agp`** vor — das ist ein
Autogen-Punkt für den Szenerienbau, keine ladbare `.obj`. Im Katalog stehen sie trotzdem als
Zeilen, weil der Sammler Dateien gelistet hat; **gesetzt werden kann davon keine.** Von 403
Einträgen der Kategorie `ships` sind nur **47** wirklich `.obj`, und das größte davon ist eine
19-m-Yacht. Deshalb ist `boot_gross` hier die Fregatte und kein Containerschiff.

Das ist derselbe Vorbehalt wie bei den 1693 grünen Haken der MSFS-Seite, nur eine Stufe
früher: Dort hieß „setzbar ≠ sichtbar", hier heißt es **„gelistet ≠ ladbar"**.

---

## ⭐ Eigener Rauch — sechs Farben, in beiden Simulatoren (13.09.2026)

Seit diesem Tag hängt keine Rauchgattung mehr an einem Fremdpaket. Die Säulen sind eigenes
Werk und liegen im jeweiligen Brügge-Paket:

| | X-Plane | MSFS |
|---|---|---|
| Quelle | `xplane/rauch_bauen.py` → `.pss` | `msfs-rauch/rauch_bauen.py` → VFX-XML |
| Titel | `objekte/rauch_<farbe>.obj` | `FrsRauch_<Farbe>` (SimObject) |
| Farben | navy, hellblau, rot, orange, signalrot, signalorange | dieselben sechs |

**Warum überhaupt selbst:** Am selben Tag wurde im laufenden MSFS alles geprüft, was es von
der Stange gibt — `SIAI_VFX_Smoke_Red` ist eine Wand über mehrere hundert Meter (und braucht
das SayIntentions-Abo), `Smoke_Volcano` eine Halbkugel, `VfxSpawner` zeichnet gar nichts,
Emeralds Schornstein raucht nur unter 10 °C. Keines ist eine Signalsäule, und **mitliefern
darf man keines**: Emerald verbietet es wörtlich, SayIntentions hängt am Abo, Campout ist
fremd. Navy und Orange gab es in MSFS überhaupt nicht.

**Dass das ohne Klickeditor geht, war der Fund:** Ein MSFS-Partikeleffekt ist als `.spb`
kompiliert, seine **Quelle ist aber lesbares XML** (SDK-Beispiel `SimpleFX/EngineSmoke.xml`).
Damit lässt sich der Effekt schreiben statt klicken — und aus derselben Zahlenbasis wie die
X-Plane-Fassung erzeugen.

⚠ **Die Fallen stehen als Warnungen im Quelltext**, nicht hier; jede hat einen Tag gekostet.
Die vier teuersten:

1. **Ein `data:`-URI im glTF baut fehlerfrei und lädt nie.** Der Modell-Compiler schreibt ihn
   auf eine externe `.bin` um, ohne sie zu erzeugen — das Trägermodell fehlt dann still.
2. **Farben müssen linear übergeben werden**, nicht als sRGB. Navy (`#191D53`) stand sonst als
   helles Lavendel am Himmel.
3. **Drei Größen hängen am Auftrieb** (Dichte, Kegelbreite, Endgröße). Wer ihn ändert und sie
   stehen lässt, bekommt einen Fächer oder einen Ball — beides im Sim gesehen.
4. **Das Auflösen hängt am Alter, nicht an der Strecke.** Bei 27 kt zog die Fahne deshalb über
   300 m. Gelöst über `GetParticleAttribute → Position`: Die Deckkraft wird nach der
   tatsächlich zurückgelegten waagerechten Strecke gedämpft. Der naheliegendere Weg über
   `GetSimVar` mit `AMBIENT WIND VELOCITY` ist **erprobt und tot** — ein statisches Objekt
   bekommt die Variable nicht, der Knoten liefert 0.

**Die Brenndauer ist Absicht:** `TimeEmission` steht auf 30 s. Solange das Trägerobjekt lebt,
startet MSFS den Emitter nach Ablauf von selbst neu (`FX_CODE` ist dauerhaft wahr), die Säule
brennt also durchgehend. Erst wenn das Objekt abgeräumt ist, fällt der Neustart aus und es ist
nach spätestens einer halben Minute Ruhe. Ohne `TimeEmission` raucht es bis zum Neustart des
Fluges weiter — auch das ist gemessen.

**Ausgeliefert wird EIN Paket** (ab 1.7.1). Der Project Editor baut den Rauch in drei Teilen —
Effekte, Material, SimObjects, weil er je AssetGroup-Typ eine eigene Definition und einen
eigenen `PackageOrderHint` will. Das ist der **Bauweg, nicht die Auslieferung**: `paket.ps1`
kopiert die drei kompilierten Bäume (`VisualEffectLibs\`, `MaterialLibs\`, `SimObjects\`) neben
das Modul (`modules\`) in den Ordner `friesenbruegge` und schreibt **eine** `layout.json` über
alles. Vier disjunkte Äste in einem Baum — ein MSFS-Paket ist nichts weiter als ein Ordner mit
Manifest, Layout und Inhalten, und welche das sind, steht ihm frei.

Bis 1.7.0 entpackte das ZIP vier Ordner, während die Anleitung von einem sprach. Wer nur drei
davon kopiert, hat eine Brügge, die auf Titel zeigt, die es bei ihm nicht gibt — und merkt es
nur daran, dass nichts raucht. `paket.ps1` räumt die alten Einzelordner im Community-Verzeichnis
deshalb selbst weg (nur die eigenen, erkannt am Manifest): zwei Quellen für denselben Titel sind
eine zu viel.

## Offen

- **Robben: das Modell ist gefunden, der Weg dorthin nicht gemessen.** Die drei Titel aus
  `human-library-animated` stehen in der Gattung `robbe` — ob ein Community-SimObject gesetzt
  werden kann, entscheidet Messliste 8. Danach die zwei Folgefragen: Superspud um Weitergabe
  der Modelle bitten oder ein eigenes bauen, und wie das Paket aussieht (Vorbild ist
  `human-library-animated` selbst: `content_type: SCENERY` mit **minimalem** Manifest — ohne
  `export_type`, `builder`, `minimum_compatibility_version`, also genau die Felder, die das
  WASM-Paket der Brügge zwingend braucht). Ziel ist ein eigenes Paket im selben Download wie
  die Brügge, keine 556-MB-Fremdabhängigkeit.
- Die 30 gestreamten Tierpakete sind ungeprüft: Ob ein Titel aus einem noch nicht geladenen
  Paket gesetzt werden kann, ist nicht gemessen.
- Für MSFS 2020 ist **nichts** von alldem im Flug belegt — nur die Titel sind ausgelesen.
- Für X-Plane: ob eine Instanz das Entladen des Plugins überdauert (s. `probe-xplane`).

---

## ⚠ Lehre aus dem Entstehen dieser Datei

Der X-Plane-Abschnitt entstand zuerst als **Websuche** — obwohl seit dem 11.09.2026 ein
vollständiger Probeflug samt Plugin, Protokoll und Screenshot im Repo lag. Die Suche fand
weniger und Ungenaueres als das, was schon dastand, und nannte vor allem `XPLMProbeTerrainXYZ`
nicht als das, was es ist: die Antwort auf genau die Frage, um die sich der ganze Abend drehte.

**Erst `probe-*/ERGEBNIS.md` lesen, dann suchen.** Dasselbe gilt für die MSFS-Titel: Die
brauchbare Quelle war nicht das Netz, sondern die Installation auf der Platte.
