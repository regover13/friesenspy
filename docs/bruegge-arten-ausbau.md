# Mehr Arten für die FriesenBrügge

> Stand 15.09.2026 · **umgesetzt** — aus 17 anforderbaren Arten sind **37** geworden

Anlass war ein Satz des Nutzers: *„16 Arten waren viel zu wenig für so viele Objekte!"*
Er hatte recht, und die Zahl war zwischenzeitlich sogar gesunken.

**Der Maßstab ist die stehende Regel vom 14.09.2026:** Eine Art geht nur hinaus, wenn
**beide** Simulatoren etwas aus ihr zeigen können, und sie darf **kein Fremdpaket**
brauchen. Alles unten ist daran gemessen — und beide Brücken bekommen heute exakt dieselben
37 Arten.

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

Damit weiß der Katalog nach Monaten Betrieb nicht, was funktioniert, obwohl die Information
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
`ANTWORT_PUFFER` passen — **49152 Bytes**, in beiden Brügge-Fassungen. Bei 37 Arten braucht
X-Plane rund 7,7 kB (15 % des Puffers), MSFS 2,5 kB.

**X-Plane ist der teure Fall, um das Dreifache:** Dort ist der Bezeichner ein Dateipfad, und
`Resources/default scenery/` allein wiederholt sich in jeder Zeile — bei 73 Titeln sind das
1,6 kB reine Wiederholung. 200 Bytes je Art gegen 66 bei MSFS.

`tests/test_bruegge_arten.py` wacht darüber und **liest die Zahl aus `bruegge.cpp` und
`netz.h`**, statt sie abzuschreiben — der alte Test band 16384, eine Grenze, die es seit
einer Verdreifachung nicht mehr gab. Reißt er, ist die nächste Maßnahme **nicht**, ihn
hochzusetzen, sondern den gemeinsamen Pfadstamm einmal statt 73-mal zu schicken. Das spart
auf einen Schlag ein Viertel.
