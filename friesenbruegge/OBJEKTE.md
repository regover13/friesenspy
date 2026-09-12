# Welche Objekte gibt es? — Titel je Simulator

**Nachschlagewerk für `titel_fuer` in `msfs/bruegge.cpp`.** Der Server nennt nur eine
**Gattung**; welches Modell daraus wird, entscheidet die Brügge, weil nur sie ihren Simulator
kennt (PROTOKOLL.md, Abschnitt 2).

> ### ⚠ Diese Listen sind AUSGELESEN, nicht recherchiert
>
> Eine Websuche brachte am 12.09.2026 nichts Brauchbares: Die offizielle SDK-Doku beschreibt
> `AICreateSimulatedObject`, nennt aber **keine Titel**; Community-Seiten listen Add-ons statt
> Bordmittel. Die Titel unten stammen aus der Installation selbst — das ist die einzige
> Quelle, die auch stimmt, wenn Asobo etwas umbenennt.

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

⚠ **Keine Robben, keine Seehunde.** Für den FriesenKieker ist das der wichtigste Eintrag
dieser Liste: Was gezählt werden soll, bringt der Simulator nicht mit. `devprops-counting-
seals-frisian-islands` löst das über **Szenerie**-Objekte (BGL), nicht über SimObjects — und
Szenerie lässt sich nicht zur Laufzeit setzen.

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

---

## Offen

- **Robben fehlen in beiden Simulatoren.** Für den FriesenKieker die grundlegendste Frage:
  Womit wird gezählt? Ein eigenes SimObject-Paket wäre nötig (als SimObject, nicht als
  Szenerie wie `counting-seals`) — oder eine andere Gattung als Platzhalter.
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
