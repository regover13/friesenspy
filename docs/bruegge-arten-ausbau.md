# Mehr Arten für die FriesenBrügge

> Stand 15.09.2026 · Bestandsaufnahme und Vorschlag · **noch nichts davon umgesetzt**

Anlass ist ein Satz des Nutzers: *„16 Arten waren viel zu wenig für so viele Objekte!"*
Er hat recht — und die Zahl ist inzwischen sogar gesunken. Dieses Papier sagt, was der
Bestand hergibt, was davon sofort geht, und wo der eigentliche Hebel liegt.

**Der Maßstab ist die stehende Regel vom 14.09.2026:** Eine Art geht nur hinaus, wenn
**beide** Simulatoren etwas aus ihr zeigen können, und sie darf **kein Fremdpaket**
brauchen. Alles unten ist daran gemessen.

---

## Wo wir stehen

| | Zahl |
|---|---|
| Arten in der Tabelle | 29 |
| davon **anforderbar** | **17** (nach dem Robben-Umbau; `test_tank` fällt durch die neue Regel) |
| Titel im Katalog | 6786 |
| davon **einer Art zugeordnet** | **rund 100** |

Rund 100 von 6786. Das ist das Missverhältnis, das der Nutzer meint.

---

## ⭐ Der eigentliche Befund: Der Katalog kennt X-Plane nur zu einem Viertel

X-Plane 12 hat **7995 `.obj` unter `default scenery`** (10 016 mit dem xPilot-Plugin, das
nicht zählt — Fremdpaket). Der Katalog führt **2327**.

Die fehlenden Zweige sind kein Versehen, sondern eine Auswahl vom 14.09.2026 („was nur im
Verbund funktioniert, bleibt draußen"). Vier davon halten dieser Begründung aber nicht
stand — dort stehen Dinge, die als einzelnes Objekt sehr wohl Sinn ergeben:

| Zweig | Objekte | was drinsteht |
|---|---|---|
| `1000 roads/objects/cars` + `cars_EU` | 167 | **PKW, Busse, Polizeiwagen** — statisch und dynamisch, EU und US |
| `airport scenery/Euro_Airports` | 189 | **24 Gabelstapler**, 3 Silos, europäische Flugplatzgebäude |
| `airport scenery/Common_Elements` | 1247 | **16 Zelte**, der **Flaggenmast**, eine **Boje**, Fahrzeuge |
| `900 roads/trains` | 187 | Güterwagen, Containerwagen — **MSFS hat nichts davon**, fällt aus |

Ein erweiterter Sammellauf über die ersten drei ist die billigste Maßnahme auf dieser
Liste: Er kostet einen Durchlauf von `katalog_sammeln.py` und bringt drei neue Artenpaare
mit, die heute an fehlenden X-Plane-Titeln scheitern (`flagge`, `zelt`, und eine echte
Auswahl bei `auto`/`bus`).

---

## Was sofort geht — 13 neue Arten aus dem vorhandenen Katalog

### Schiffe (6) — der größte Block, und für die Nordsee der passendste

MSFS bringt **58 echte Schiffe** mit (je 12 Varianten und eine `_Sink`-Fassung, daher die
1392 Zeilen). X-Plane hält unter `ships/parts/` die großen Frachter bereit.

| Art | MSFS | X-Plane |
|---|---|---|
| `schiff_container` | MscBremen, Belgorod, CMACGMExupery | ContainerCarrier_399A/399B/155A |
| `schiff_massengut` | BulkItaly, Nikos, OreShenzhen | BulkCarrier_342A/190B `_StaticOnly` |
| `schiff_tanker` | TIAsiaULCC, GoldenState, Ivyan | OilTanker_183A |
| `schiff_gastanker` | Taitar4CG | LNGCarrier_190A |
| `schiff_segel` | Elcano, LillaDan | Sail_1500_01–04 |
| `schnellboot` | BHLExpress5 | SpeedBoat_1300_01/02 |

⚠ **Fünf davon hängen an einer einzigen ungemessenen Frage:** Lädt `XPLMLoadObject` ein
Objekt aus `ships/parts/`? Die großen Schiffe liegen dort als Bausteine der
Szeneriebibliothek, aus denen X-Plane ein Schiff zusammensetzt. Nur `schiff_segel` ist
davon frei (`Sail_1500_*` liegt direkt unter `ships/`).

**Die Messung ist bereits vorbereitet:** `boot_gross` steht in X-Plane seit heute auf
`BulkCarrier_342A_StaticOnly` (Rang 1), mit den Kajütbooten als Rückfall auf Rang 5/6. Ein
gesetztes `boot_gross` beantwortet die Frage für alle fünf Arten auf einmal.

### Flugplatz und Gerät (4)

| Art | MSFS | X-Plane |
|---|---|---|
| `jetway` | EDDF_Jetway_01, EHAM_Jetway_01, EGLL_Jetway_01 | Ang_Jetway_250cm, JetWayExt_10m |
| `gabelstapler` | Forklift_Large, Forklift_Medium | wheel_loader_1, cargo_loader_ch70w |
| `bus` | Microsoft_Bus_EUR_Vintage, Bus_Modern | pax_bus_1, pax_bus_2 |
| `treppe` | *(noch zu suchen)* | pax_stairs_1, Stair_Maint_1 |

### Bau und Hafen (3)

| Art | MSFS | X-Plane |
|---|---|---|
| `baufahrzeug` | Microsoft_Bulldozer | bulldozer_1, excavator_1 |
| `seecontainer` | Drop_Container, Truck_Container | container_20f_01a … (57 Stück) |
| `lastwagen` | Microsoft_EUR_Truck, Truck_Container | Fuel_Truck_Large, Fuel_Truck_Small |

⚠ `lastwagen` überschneidet sich mit der bestehenden Art `fahrzeug`, die heute Tankwagen
**und** Pushback **und** Crew-Car in einen Topf wirft. Wer `lastwagen`, `bus` und `auto`
trennt, sollte `fahrzeug` gleichzeitig auflösen — sonst gehört ein Titel zu zwei Arten,
und das ist ausgeschlossen.

---

## Was an der Regel scheitert — und warum es weh tut

Diese Themen hat **nur ein** Simulator. Nach der Regel bleiben sie gesperrt.

### Nur MSFS (X-Plane hat nichts davon — im ganzen Dateibaum gesucht)

**Fischkutter** (9 Schiffe, darunter `SGGreetsiel` — ein Krabbenkutter aus Greetsiel) ·
**Seenotretter** (4, darunter die `HermannMarwede` und die `PeterHabig`, beide DGzRS) ·
**Fähre** (7, u. a. `HSeawaysDFDS`) · **Kreuzfahrtschiff** (4) · **Lotsenboot** (2) ·
**Binnenschiff** (3) · **Startwinde** (40 Segelflugwinden!) · **Pferd, Schaf, Ziege, Kuh** ·
**Menschen** (190)

Das ist die bittere Liste: Ausgerechnet Krabbenkutter und Seenotkreuzer — die beiden
Dinge, die an der Nordsee am meisten Sinn ergäben — fehlen X-Plane vollständig.

**Es gibt einen erprobten Ausweg, und wir sind ihn schon zweimal gegangen:** ein eigenes
Modell. Beim Rauch und beim Seehund war die Lage dieselbe, und beide laufen heute in
beiden Simulatoren. Ein Krabbenkutter für X-Plane wäre der dritte Fall — und der erste,
bei dem MSFS die Vorlage liefert statt umgekehrt.

### Nur X-Plane (MSFS hat nichts davon)

**Boje** · **Silo** (111) · **Radar** · **Flugplatzfeuer** (5) · **Navigationsanlagen**
(ILS, NDB, Marker) · **Segelflugzeug** (28 ASK 21 und Ventus 3, mit echten Kennzeichen,
darunter vier deutsche) · **Zug** (187) · **Leuchtturm** (63)

Auch hier ist der Ausweg bekannt: Ein Leuchtturm für MSFS wäre ein eigenes Modell — und
hätte an der Nordsee mehr Berechtigung als fast alles andere auf dieser Seite.

---

## Vorschlag in der Reihenfolge des Nutzens

1. **`boot_gross` im Flug setzen** (X-Plane). Eine Minute, und sie entscheidet über fünf
   der dreizehn neuen Arten. Steht der Frachter, sind die Schiffsarten frei.
2. **Sammellauf um drei Zweige erweitern** (`cars`, `cars_EU`, `Euro_Airports`,
   `Common_Elements`) und neu einlesen. Bringt `flagge`, `zelt` und eine echte Auswahl bei
   `auto`/`bus`.
3. **Die 13 Arten anlegen**, nach dem Ausgang von 1. gestaffelt.
4. **`fahrzeug` auflösen** in `auto`, `bus`, `lastwagen`, `baufahrzeug` — die Art ist
   heute eine Restekiste, und die Titel liegen alle schon da.
5. **Eigenes Modell erwägen**, wo es thematisch am meisten trägt: ein **Krabbenkutter**
   für X-Plane, ein **Leuchtturm** für MSFS.

Aus 17 anforderbaren Arten werden damit rund 30 — ohne ein einziges Fremdpaket.
