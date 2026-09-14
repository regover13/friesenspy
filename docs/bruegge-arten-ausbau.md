# Mehr Arten für die FriesenBrügge

> Stand 15.09.2026 · **umgesetzt** — aus 17 anforderbaren Arten sind **32** geworden

Anlass war ein Satz des Nutzers: *„16 Arten waren viel zu wenig für so viele Objekte!"*
Er hatte recht, und die Zahl war zwischenzeitlich sogar gesunken.

**Der Maßstab ist die stehende Regel vom 14.09.2026:** Eine Art geht nur hinaus, wenn
**beide** Simulatoren etwas aus ihr zeigen können, und sie darf **kein Fremdpaket**
brauchen. Alles unten ist daran gemessen — und beide Brücken bekommen heute exakt dieselben
32 Arten.

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

## Die 32 Arten

| | |
|---|---|
| **Tiere** | `seehund_kuh` · `seehund_bulle` · `seehund_heuler` · `tier_gross` · `tier_klein` |
| **Schiffe** | `boot_gross` · `boot_klein` · `schiff_segel` |
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

## Was noch offen ist

### Die eine Messung, die fünf weitere Arten freigibt

`schiff_container` · `schiff_massengut` · `schiff_tanker` · `schiff_gastanker` ·
`schnellboot` sind vorbereitet, aber **nicht angelegt**. Ihre X-Plane-Seite liegt
vollständig in `ships/parts/` — dort setzt X-Plane ein Schiff aus Bausteinen zusammen
(`_BaseModel` + `_Static_Add` + `_Flags`), und ob `XPLMLoadObject` daraus lädt, ist
ungemessen.

**Die Messung ist vorbereitet:** `boot_gross` steht in X-Plane auf
`BulkCarrier_342A_StaticOnly` (Rang 1, 342 m), mit den Kajütbooten als Rückfall auf Rang 5/6.
Ein gesetztes `boot_gross` beantwortet die Frage für alle fünf auf einmal.

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
`ANTWORT_PUFFER` passen — **49152 Bytes**, in beiden Brügge-Fassungen. Bei 32 Arten braucht
X-Plane rund 6 kB, MSFS 2 kB.

**X-Plane ist der teure Fall, um das Dreifache:** Dort ist der Bezeichner ein Dateipfad, und
`Resources/default scenery/` allein wiederholt sich in jeder Zeile — bei 73 Titeln sind das
1,6 kB reine Wiederholung. 200 Bytes je Art gegen 66 bei MSFS.

`tests/test_bruegge_arten.py` wacht darüber und **liest die Zahl aus `bruegge.cpp` und
`netz.h`**, statt sie abzuschreiben — der alte Test band 16384, eine Grenze, die es seit
einer Verdreifachung nicht mehr gab. Reißt er, ist die nächste Maßnahme **nicht**, ihn
hochzusetzen, sondern den gemeinsamen Pfadstamm einmal statt 73-mal zu schicken. Das spart
auf einen Schlag ein Viertel.
