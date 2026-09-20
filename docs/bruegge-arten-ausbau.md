# Mehr Arten für die FriesenBrügge

> Stand 15.09.2026 · **umgesetzt** — aus 17 anforderbaren Arten sind **37** geworden
>
> ⭐ **Nachtrag 20.09.2026:** Es sind **56 Arten** in der Datenbank (sieben neu, s. unten), und die Regel
> „beide Simulatoren müssen etwas zeigen können“ gilt nicht mehr — s. `CLAUDE.md`, Abschnitt Arten.
> Der Text darunter beschreibt den Stand vom 15.09.

Anlass war ein Satz des Nutzers: *„16 Arten waren viel zu wenig für so viele Objekte!"*
Er hatte recht, und die Zahl war zwischenzeitlich sogar gesunken.

**Der Maßstab ist die stehende Regel vom 14.09.2026:** Eine Art geht nur hinaus, wenn
**beide** Simulatoren etwas aus ihr zeigen können, und sie darf **kein Fremdpaket**
brauchen. Alles unten ist daran gemessen — und beide Brücken bekommen heute exakt dieselben
37 Arten.

---

## Nachtrag 20.09.2026 — sieben neue Arten, und was mit dem Rest der MSFS-2020-Titel wurde

Der MSFS-2020-Katalog ist durchgemessen (2 773 Urteile, davon 225 „steht“; Community-Titel werden nie geprüft). Von
den 346 bestandenen waren **164 ohne Art**. **138 haben jetzt eine**, 26 bleiben **bewusst** ohne:

| Art | neu? | Titel | wo sie geht |
|---|---|---|---|
| `marshaller` | ✅ | 24 (`Marshaller_*`, ohne den Stab) | MSFS 2020 + 2024 |
| `pilot` | ✅ | 26 (`Pilot_*`, auch Uniform und Segelflug) | MSFS 2020 + 2024 |
| `bodenpersonal` | ✅ | 25 (`Tarmac_*` und `Wing_Runner`) | MSFS 2020 + 2024 |
| `elefant`, `giraffe`, `nashorn`, `nilpferd` | ✅ | 14 / 6 / 9 / 5 — je ein Teil aus 2020 (`AfricanElephant`, `AfricanGiraffe`, `Rhino*`, `Hippo*`) und aus 2024 (`LAfricana`/`EMaximus`, `GGiraffa`/`GCamelopardalis`, `CSimum`, `HAmphibius`) | **MSFS 2020 und 2024**, jeweils mit eigenen Titeln — die 2020er Titel gibt es in 2024 nicht. Ersetzt `tier_afrika` (jetzt `aus`): Eine Sammelart lieferte in jedem Simulator immer nur den Elefanten (Nutzerwunsch 20.09.2026) |
| ~~`wal`~~ | ❌ | 1 (`HumpbackWhale`) | **wieder abgeschaltet (20.09.2026):** setzbar, aber in keinem Simulator gezeichnet — s. „Setzbar heißt nicht sichtbar“ in `docs/architecture.md`. Ich hatte die Art am Morgen angelegt, ohne das dort Stehende zu lesen; der Nutzer hat es im Flug bestätigt (MSFS 2024). Urteil von Hand („unsichtbar“) für beide MSFS |
| `bordtreppe` | ✅ | 3 MSFS + 4 X-Plane (`pax_stairs_1`, `_up1`, `_up2`, `Stair_Maint_1`) | **überall** |
| `seilwinde` | ✅ | 3 (`TT:WINCH.*`) | MSFS 2020 + 2024 |
| `flugplatzfahrzeug` | | +11 Nachrücker (Pushback, Catering, Gepäckschlepper, Treppen-Lader …) | |
| `tankwagen` | | +2 (`ASO_FuelTruck01/02_Black`) | |
| `flugzeug_echo` | | +3 (C172 AirTraffic 01/03, klassische C172) | |
| `flagge` | | +10 (Ländermasten aus dem Segelflug-Paket, `Flag_*`) | |
| `tier_gross` | | +2 (`SyrianBear`, `PolarBear` — beide nur in 2020 gemessen) | |

**Warum mit „Nachrücker“:** Die Brügge nimmt aus einer Art immer Rang 1 (s. unten). Was hinten angehängt wird, ändert
nichts an dem, was heute gesetzt wird — es greift erst, wenn ein Titel davor ausfällt. Das ist der sichere Weg, alles
Brauchbare unterzubringen.

**Bewusst ohne Art (26):** Schwimmer- und Kufenversionen der C172 (12) und der Schleppflieger — am Boden falsch;
Flusspferd unter und im Wasser (4); `L_VR_Controller`, `R_VR_Controller`, `VRLeftHand`, `VRRightHand`,
`Marshaller_Stick`, `Optical_Landing_System`, `Parachute`, `Smoke_Volcano`, `VfxSpawner` — Werkzeugobjekte, keine Szenerie.

**X-Plane hat für die drei Personenarten, die Winde und den Wal nichts:** Im Dateibaum
(`Resources/default scenery`, 7 995 `.obj`) gesucht nach `people`, `person`, `pilot`, `marshal`, `winch`, `whale`,
`elephant`, `giraffe`, `worker`, `crew`, `passenger` — Treffer sind nur `Boats_Crew_*` (Schiffsteile), `Whaler_*` (Fangschiffe),
`crew_car*` und `EDDM_Control_Tower_Workers.obj`. Die Arten tragen das in ihrer Bedeutung, damit im Admin niemand
nach einem X-Plane-Titel sucht.

**⚠ „steht“ ist nicht „gezeichnet“ — und das gilt für fast alles, was am 20.09.2026 dazukam.** Der Katalog und die neuen Läufe messen, dass
der Simulator ein Objekt **anlegt**. Im Flug gesehen wurden bisher nur: die 2024er Tiere (Elefant, Giraffe, Nashorn, Nilpferd), Rauch und Seehund.
**Nicht gesehen:** `marshaller`, `pilot`, `bodenpersonal`, `seilwinde`, `bordtreppe`, die 2020er Tiertitel und alle 1 428 neu aufgenommenen 2024er
Titel. Der Wal (`HumpbackWhale`) hat gezeigt, was das heißen kann.

**Der Simulator nennt seine Titel selbst — und was das NICHT abdeckt** (20.09.2026, `probe-msfs/titel_aufzaehlen.py`):
`SimConnect_EnumerateSimObjectsAndLiveries` (nur MSFS 2024) kennt die Typen ALL, AIRCRAFT, HELICOPTER, BOAT, GROUND, HOT_AIR_BALLOON, ANIMAL und
USER; **Typ 8 (`USER_AVATAR`) und alles ab 9 antwortet mit Ausnahme 45**. Es gibt keinen Typ für Misc, Landmarks, Humans oder Bauwerke.
Die gestreamten Pakete (`StreamedPackages`, 1 161) zerfallen in drei Sorten: **521 lesbar** (`minimal.fsarchive`, Kopf `"scheme":"notEncrypted"`, die
`sim.cfg` liegt dort im Klartext — 2 634 Titel, alle schon im Katalog), **715 mit verschlüsselten SimObject-Archiven** (Formatvariante 2.0.3,
`SimObjects\<acht Buchstaben>.fsarchive`, 1 007 Stück) und **61 ohne Archiv**. Von den 715 deckt die Aufzählung 306 ab (Flugzeuge, Schiffe, Tiere,
Fahrzeuge); **409 bleiben unlesbar** — Bushtrips, Discovery-Flüge (Berlin, Paris, London, Gizeh …), Landing Challenges, Activities, Trainings,
Challenges, Red Bull, Spotlight-POIs, POI-Pakete. Dort könnten Bauwerke liegen; ob, weiß nur der Simulator (Objektbrowser im Scenery Editor des DevMode).
Die Wahrzeichen selbst (Brandenburger Tor, Frauenkirche, Hohenzollernbrücke, Aachener Dom …) stehen im Deutschland-POI-Paket als **Szenerie**
(`germany-pois/master.bgl`); als SimObject gibt es dort nur `GERM_POI_Allianz Arena`.

**Aufgenommen und getestet (MSFS 2024, 20.09.2026):** Was die Aufzählung nannte, der Katalog nicht kannte und in keiner Community-`sim.cfg` steht,
kam in den Katalog — **1 428 Titel: 775 Tiere, 102 Bodenfahrzeuge, 551 Flugzeuge/Hubschrauber**, `quelle='streamed'`, alle mit Bemerkung „aus
SimConnect_EnumerateSimObjectsAndLiveries“. **Alle 1 428 melden „steht“** (nicht gezeichnet geprüft). Draußen blieben: 120 Boote (alle auch in
Community-`sim.cfg`), 28 Hubschrauber und 57 Flugzeuge (ebenfalls in Community). Der Abgleich mit Community geht über die `sim.cfg`-Dateien auf der
Platte — Community ist nie verschlüsselt (Nutzer), also ist ein aufgezählter Titel, der dort fehlt, keiner. Ein Loch bleibt: Marketplace-Käufe im
`Official`-Ordner wären verschlüsselt und gingen als „nicht Community“ durch; auf dieser Platte liegen dort nur zwei Pakete
(`asobo-aircraft-c172sp-classic` in 2020, `microsoft-aircraft-antonov2-temp` in 2024), beide von Asobo/Microsoft.

**MSFS 2020 und X-Plane — was dort fehlt (gleiche Methode, 20.09.2026):** *MSFS 2020* hat kein Streaming (nur `Official\OneStore` und `Community`, keine
verschlüsselten Dateien; alle 89 SimObject-`cfg` aus den `layout.json` liegen auf der Platte, alle 254 Official-Titel stehen im Katalog). Was fehlt,
ist Inhalt, den Tobias nicht installiert hat. *X-Plane* hat kein Streaming, aber 5 076 von 7 995 Standardobjekten sind nicht im Katalog (das meiste
bewusst: Autogen, Straßen, Gelände), dazu **16 „X-Plane Landmarks“-Pakete (~165 Objekte, u. a. `Brandenburg_Gate`, `TV_Tower`, `Commerzbank`)** und 6
„X-Plane Airports“ (137 Objekte) aus `Custom Scenery` — davon nichts im Katalog. Einen Kölner Dom gibt es dort nicht.

**Die große Zuordnung (20.09.2026): 49 Arten aus den 1 428 neuen 2024er Titeln.** Tiere nach den Kategorien, die der
Simulator selbst in seinen Paketnamen benutzt (`fs24-microsoft-simobjects-animals-*`): `elch`, `gepard`, `schaf`,
`panda`, `bison`, `bueffel`, `kamel`, `hyaene`, `ziege`, `wolf`, `gnu`, `zebra`, `gazelle`, `wasserschwein`, `baer`,
`antilope`, `loewe`, `tiger`, `schneeleopard`, `affe`, `warzenschwein`, `rentier`, `strauss`, `lama`, `fuchs`,
`kaenguru`, `ameisenbaer`, `erdferkel`, `krokodil`, dazu `pferd`, `kuh`, `hirsch` und die vier einzelnen Afrika-Arten
`elefant`, `giraffe`, `nashorn`, `nilpferd`. Fahrzeuge in die vorhandenen Arten, neu `motorrad` und `lkw`; Flugzeuge nach
Namen in `hubschrauber`, `ballon`, `segelflugzeug` (mit den 28 X-Plane-Segelflugzeugen, also auch dort setzbar),
`flugzeug_airliner`, `_klassik`, `_ga` und `_echo`. **Draußen blieben:** Discus-2c (Premium-Paket eines
Drittanbieters), Militärflugzeuge, Gayal/Yak/Banteng, und alles aus Community. `tier_gross` und `tier_vieh` sind
aufgelöst (`aus`); die X-Plane-Hirsche `deer_buck`/`deer_doe`, vorher bei `tier_gross`, stehen bei `hirsch` — X-Plane hat
sonst kein großes Tier, `tier_gross` geht dort deshalb nicht mehr.

**Sichtprüfung im Flug (MSFS 2024) — automatisch und per Auge.** Je Art der **erste** Titel (die Brügge nimmt immer Rang 1)
hinter dem Piloten, Bildschirmfoto, Differenz zum Leerbild unterhalb des Horizonts und Anteil Magenta (fehlende Textur:
Schachbrett). **Kein einziger erster Titel war rosa**; gefunden wurde: die **Guernsey- und Jersey-Kuh** (6 Titel) ist rosa
(fehlende Textur) — raus aus `kuh`, Urteil von Hand für die zwei gesehenen; der **Pilot** steckt halb im Boden — `pilot`
abgeschaltet; der **Buckelwal** ist unsichtbar (stand seit dem 13.09. in `docs/architecture.md`) — `wal` abgeschaltet;
der **Hubschrauber** `H125 Rescue` **hüpft** (Schwerpunkt 225 px, ein zweiter kippte auf den Kopf), s. „Boden oder Höhe" in
`docs/api.md`. Gepard und Ziege fielen bei der Messung durch (klein), waren im Bild aber da.

**Wo fehlt einer Art noch etwas? — der Filter „Lücke in“** (Nutzerfrage 20.09.2026, im Admin über der Tabelle
„ARTEN“): Ohne Haken steht die ganze Liste da. Mit Haken bleiben die Arten mit Lücke — in **allen** angehakten
Simulatoren (**UND**, die Vorgabe) oder in **mindestens einem** (**ODER**); die Auswahl steht neben den Haken
(Nutzerwunsch 20.09.2026: erst ODER gebaut, dann „soll UND verknüpft sein“, dann „UND oder ODER zur Auswahl“).
Der Picker bei „Objekte anfordern“ verlangt etwas anderes: dass die Art in allen angehakten GEHT. „Lücke“ heißt **geht nicht (✕)**:
kein aktiver Titel oder alle durchgefallen — die fehlenden Zuordnungen. Ein noch ungeprüfter Titel (?) ist zugeordnet und zählt nur mit dem Schalter „auch noch
ungeprüft“. Abgeschaltete Arten (`fahrzeug`, `robbe`, `test_tank`) sind überall leer und erscheinen nur mit „auch
abgeschaltete“. Die Auswahl ist eine reine Funktion (`bgArtenGefiltert` in `admin.html`) und wird in
`tests/test_admin_arten_luecke.py` unter Node ausgeführt.

**Der Simulator nennt seine Titel selbst — `SimConnect_EnumerateSimObjectsAndLiveries` (MSFS 2024).** Von der Platte lassen
sich die Titel gestreamter 2024er Pakete nicht lesen (`StreamedPackages` enthält nur wenige Dateien, die Virtual File System zeigt
leere Platzhalter, manche mit Schloss). Der Simulator kennt sie aber, und diese Funktion liefert sie: `ANIMAL` 1 030 Titel,
`GROUND` 522, `ALL` 7 503 — davon **775 / 102 / 1 633 dem Katalog unbekannt**. `friesenbruegge/probe-msfs/titel_aufzaehlen.py`
(reines `ctypes`, kein Kompilieren) fragt sie ab. Die Tiere heißen in 2024 nach der Art:
`LAfricana…` (Afrikanischer Elefant), `EMaximus…` (Asiatischer), `HAmphibius…` (Flusspferd), `CSimum…` (Breitmaulnashorn),
`GGiraffa…` und `GCamelopardalis…` (Giraffen), `PLeo…` (Löwe), dazu `ahqa …` (Zebra, Robbe, Walross, Seelöwe). Diese sechs wurden
am 20.09.2026 im Flug hinter dem Piloten gesehen, und sie zeigten genau das, was der Name sagt.
⚠ **Grenze:** Die Aufzählung deckt nicht jede Kategorie ab. Die eigenen `FrsRauch_*`/`FrsSeehund_*` (Misc) fehlen in `ALL`, obwohl sie
installiert sind und stehen — wer sie dort sucht, findet sie nicht.

**Zustand:** Die sechs neuen MSFS-Arten stehen im Admin nicht unter „überall“ (X-Plane fehlt), sind aber anforderbar.
`bordtreppe` ist die einzige, die es in allen dreien gibt (23 Arten sind jetzt „überall“, vorher 22).

**Wo sie wirklich nur DB-Zeilen sind:** Es gab dafür kein Release der Brügge — Arten sind Datenbankzeilen (s.
`app/bruegge_arten.py`, „die Erstbefüllung, nicht die Wahrheit“). Eine frisch angelegte Datenbank kennt sie deshalb nicht;
die Sicherung vor der Zuordnung liegt auf dem Server als `/opt/friesenspy/data/zuordnen_backup_20260920_084216.json`.

**Größe der Titelliste** (`ANTWORT_PUFFER` 49 152 Bytes): jetzt **5,5 kB** MSFS 2020, **6,3 kB** MSFS 2024, **9,9 kB** X-Plane
(20 %) — gemessen am 20.09.2026 mit `bruegge_titel_fuer` auf den echten Daten.

---

## ⭐ Der Hebel lag im Sammellauf, nicht im Bestand

Der Katalog kannte von X-Plane **2327 der 7995 `.obj`** unter `default scenery` — nicht
einmal ein Drittel. `Common_Elements` stand pauschal auf der Ausschlussliste („was nur im
Verbund funktioniert"), und für Zäune, Lampen und Absperrungen stimmt das.

**Nicht aber für den Krankenwagen, das Zelt, die Flughafenfeuerwehr, den Leitkegel und den
Fahnenmast.** An genau denen scheiterten fünf Artenpaare, obwohl beide Simulatoren sie
hatten. Elf Zweige sind dazugekommen, **596 Objekte**:

| Zweig | Objekte | was daraus wurde |
|---|---|---|
| `Common_Elements/Vehicles` | 126 | `krankenwagen` |
| `Common_Elements/fire_department` | 18 | `feuerwehr` |
| `Common_Elements/camping` | 27 | `zelt` |
| `Common_Elements/Miscellaneous` | 39 | `flagge` (Fahnenmast), `leitkegel` |
| `Common_Elements/radars`, `antennas`, `Water_Towers`, `Fuel` | 118 | noch unzugeordnet |
| `Euro_Airports` | 189 | `gabelstapler` |
| `1000 roads/objects/cars/static` + `cars_EU/static` | 79 | `auto`, `bus` |

Nebenbei beseitigt: Das zweite Tupelfeld in `_XP_ZWEIGE` war ein ungenutztes `True` und
trägt jetzt die Kategorie — nötig, weil zwei der neuen Zweige beide auf `static` enden.

---

## `fahrzeug` ist zerfallen — in sechs Arten

Sie warf Tankwagen, Pushback, Bus, Feuerwehr und Crew-Car in einen Topf. Wer ein
Feuerwehrauto anfordern wollte, bekam mit gleicher Wahrscheinlichkeit einen
Gepäckschlepper. Die Titel lagen alle schon da, es fehlte nur die Trennung:

`flugplatzfahrzeug` · `tankwagen` · `feuerwehr` · `krankenwagen` · `bus` · `auto`

Die Art selbst steht auf `aus` statt gelöscht — wer die alte Einteilung zurückwill, hat sie
mit einem Klick.

---

## Die 37 Arten

| | |
|---|---|
| **Tiere** | `seehund_kuh` · `seehund_bulle` · `seehund_heuler` · `tier_gross` · `tier_klein` |
| **Schiffe** | `boot_gross` · `boot_klein` · `schiff_segel` · `schiff_massengut` · `schiff_container` · `schiff_tanker` · `schiff_gastanker` · `schnellboot` |
| **Fahrzeuge** | `auto` · `bus` · `tankwagen` · `feuerwehr` · `krankenwagen` · `flugplatzfahrzeug` |
| **Gerät** | `gabelstapler` · `baufahrzeug` · `kran` · `jetway` · `leitkegel` · `seecontainer` |
| **Marken** | `windrad` · `windsack` · `flagge` · `mast` · `tank` · `zelt` |
| **Rauch** | die sechs Farben |

**Drei Arten für die Robben, nicht eine** — *„unsere robben sollen schon trennbar sein"*.
Das ist technisch zwingend: Ein Soll-Eintrag trägt genau **eine** Art, und die Brügge nimmt
daraus **immer Rang 1**. Mit einer Sammelart stünde an jeder Station dieselbe Kuh; eine
Kolonie aus sechs Kühen, zwei Bullen und zwei Heulern gibt es nur über getrennte Arten.
Zusammenfalten ließe sich das erst, wenn der Server unter den Titeln einer Art würfelt — so
wie er den Kurs schon würfelt.

---

## ⭐ Die Messung ist durch — X-Plane zeichnet aus `ships/parts/`

**Am 15.09.2026 im Flug gemessen und im Bild belegt.** `BulkCarrier_342A_StaticOnly` stand
in niederbayerischen Feldern: Rumpf, rote Aufbauten, alle Lukendeckel, die Ladekräne, die
Beschriftung am Rumpf — ein vollständiges 342-m-Schiff.
`ContainerCarrier_399A_BaseModel` daneben ebenso.

Das war nicht selbstverständlich: Unter `parts/` liegen **Bausteine** der
Szeneriebibliothek, aus denen X-Plane ein Schiff sonst aus vier Dateien zusammensetzt
(`_BaseModel` + `_Static_Add` + `_Flags` + `_ContainersA/B`). Dass ein Baustein **allein**
lädt *und dabei aussieht wie ein Schiff*, musste gemessen werden — „erzeugt" und
„gezeichnet" sind zwei verschiedene Dinge, das hat der Rauch teuer genug gelehrt. Die
Rückmeldung sagte bei beiden nur `steht`; entschieden hat das Auge.

**Gemessen wurde mit Kontrolle:** ein Seehund 50 m hinter dem Piloten, der nachweislich
läuft. Ohne ihn wäre ein Fehlschlag mehrdeutig gewesen — `parts/` oder die Kette dahinter.

Damit sind fünf Arten dazugekommen: `schiff_massengut` · `schiff_container` ·
`schiff_tanker` · `schiff_gastanker` · `schnellboot`. `_StaticOnly` steht vorn, wo es sie
gibt (genau zwei: 342A und 190B) — sie trägt das ganze Schiff in einer Datei.

**Und der Ausgangsfehler ist behoben:** Die beiden Cruiser stehen jetzt bei `boot_klein`,
wo sie mit 19 m und 12 m hingehören. `boot_gross` bleibt als Sammelbegriff und behält die
Frachter ohne eigene Art.

---

## Was noch offen ist

### ⚠ Die Rückmeldung fließt nicht in den Katalog zurück

**Die X-Plane-Seite hat null Prüfergebnisse** — 2932 Titel, kein einziges, obwohl seit
Wochen Objekte gesetzt werden. Der Grund: `katalog_ergebnis` wird ausschließlich von
`probe-msfs/titel_schau.py --katalog` gefüttert, einem MSFS-Werkzeug. Die laufende Brügge
meldet bei **jedem** Setzversuch `steht` oder `fehlgeschlagen` — das landet in
`bruegge_steht` und ist nach der nächsten Meldung überschrieben.

Damit weiß der Katalog seit dem ersten Betriebstag nicht, was funktioniert, obwohl die Information
jeden Tag durchs Haus läuft. **Und die Regel „eine Art wird gesperrt, wenn ein Simulator
nichts kann" hängt daran:** Sie fußt auf `status='aus'`, das aus dem Prüfergebnis kommt.
Ohne Rückfluss greift sie nur, wo jemand von Hand gepflegt hat.

Der Einbau ist klein — beim Verarbeiten der Meldung dieselben Zeilen in den Katalog
schreiben. ⚠ **Aber im Meldepfad:** Der Endpunkt ist heute atomar, *weil* er blockiert;
zwischen Lesen und Commit liegt kein `await`. Wer ihn in den Threadpool legt, baut den
Wettlauf ein, den `belegt` gerade verhindert (Hinweis der Parallelsitzung, 15.09.2026).

### Was nur ein Simulator hat — und deshalb gesperrt bleibt

**Nur MSFS:** Fischkutter (9, darunter `SGGreetsiel` aus Greetsiel) · Seenotretter (4,
darunter die `HermannMarwede` und die `PeterHabig`, beide DGzRS) · Fähre (7) ·
Kreuzfahrtschiff (4) · Lotsenboot · Binnenschiff · **Startwinde (40 Segelflugwinden)** ·
Pferd, Schaf, Ziege, Kuh · Menschen (190)

**Nur X-Plane:** Leuchtturm (63) · **Segelflugzeug (28 ASK 21 und Ventus 3, vier mit
deutschen Kennzeichen)** · Boje · Silo (111) · Radar (45) · Antennen (33) · Wasserturm ·
Flugplatzfeuer · NAVAIDS · Zug (187)

Ausgerechnet Krabbenkutter und Seenotkreuzer — das Passendste für die Nordsee — fehlen
X-Plane. **Der erprobte Ausweg ist derselbe wie beim Rauch und beim Seehund: ein eigenes
Modell.** Ein Krabbenkutter für X-Plane wäre der dritte Fall, und der erste, bei dem MSFS
die Vorlage liefert statt umgekehrt. Ein Leuchtturm für MSFS hätte an der Nordsee mehr
Berechtigung als fast alles andere auf diesen Listen.

### Noch unzugeordnet im neuen Bestand

Radar (45), Antennen und Satellitenschüsseln (33), Wassertürme (6), Avgas-Fässer und
Hydranten (34) — alles X-Plane-eigen, alles ohne MSFS-Gegenstück. Sie stehen im Katalog und
warten auf den Tag, an dem MSFS etwas Vergleichbares bekommt oder wir es bauen.

---

## Die Grenze, die das Wachstum irgendwann stoppt

Die Titelliste geht als Wörterbuch **einmal je Antwort** hinaus und muss in
`ANTWORT_PUFFER` passen — **49152 Bytes**, in beiden Brügge-Fassungen. Bei 37 Arten brauchte
X-Plane rund 7,7 kB (15 % des Puffers), MSFS 2,5 kB. (Stand 20.09.2026 mit 56 Arten: 9,9 kB
X-Plane, 5,5 bzw. 6,3 kB MSFS.)

**X-Plane ist der teure Fall, um das Dreifache:** Dort ist der Bezeichner ein Dateipfad, und
`Resources/default scenery/` allein wiederholt sich in jeder Zeile — bei 73 Titeln sind das
1,6 kB reine Wiederholung. 200 Bytes je Art gegen 66 bei MSFS.

`tests/test_bruegge_arten.py` wacht darüber und **liest die Zahl aus `bruegge.cpp` und
`netz.h`**, statt sie abzuschreiben — der alte Test band 16384, eine Grenze, die es seit
einer Verdreifachung nicht mehr gab. Reißt er, ist die nächste Maßnahme **nicht**, ihn
hochzusetzen, sondern den gemeinsamen Pfadstamm einmal statt 73-mal zu schicken. Das spart
auf einen Schlag ein Viertel.
