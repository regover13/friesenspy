# Messliste für den nächsten Simulator-Termin

**Alles, was an der Brügge noch ungemessen ist — in einem Zug abzuarbeiten.**

Diese Liste gibt es, weil am 11.09.2026 acht Simulator-Neustarts draufgingen: Nach jedem Fund
wurde sofort gebaut und neu gestartet, statt erst fertigzubauen und dann alles am Stück zu
messen. Die laufende Sim-Sitzung ist die knappe Ressource, nicht die Bauzeit.

---

## ✅ ABGENOMMEN 14.09.2026 — Protokollfassung 2 trägt

**Der Umbau ist im Flug belegt.** Die Brügge führt keine Artentabelle mehr; der Server
liefert die Titel mit. Gemessen auf Wangerooge, MSFS 2024, Brügge **1.8.0**:

| angefordert | Art | zurückgemeldet | gesehen |
|---|---|---|---|
| `p2-tier` | `tier_gross` | steht, 0,9 ft | — |
| `p2-rad` | **`windrad`** | steht, 4,4 ft | ✅ **„windrad ist da"** |
| `p2-rauch` | `rauch_signalrot` | steht, 1,7 ft | — |

⭐ **`windrad` ist der eigentliche Befund.** Diese Art existiert in **keiner**
Brügge-Fassung — sie entstand am selben Tag auf dem Server. Die Brügge hat ein Windrad
hingestellt, ohne zu wissen, was ein Windrad ist: `Windmill` kam aus `bruegge_katalog`.
Damit ist bewiesen, was der Umbau versprach — **eine neue Art kostet kein Client-Release
mehr.**

`auf_boden` traf zwischen 0,9 und 4,4 ft. Das Objektsetzen über den Admin funktioniert
unverändert (`windsack` gesetzt, angekommen, ohne Fehlermeldung).

### Was der Fassungssprung unterwegs bewies

**Der 426-Pfad läuft — und er ist teuer.** Die 1.8.0 meldete sich beim noch alten Server
(Fassung 1) und bekam `426`; sie räumte auf und setzte ihren Takt auf **900 s**, genau wie
vorgesehen. Danach kam sie 15 Minuten lang nicht wieder, und ein Flugwechsel half nicht:
**MSFS lädt WASM-Module nur beim Simulator-Start.**

> ⚠ **Für den nächsten Fassungssprung heißt das: Server ZUERST.** Ein Deploy braucht ein
> paar Minuten, in denen jede neue Brügge auf 900 s geht — und dann muss der Pilot den
> Simulator neu starten. Die Reihenfolge ist nicht Geschmack, sondern spart einen Neustart.
>
> Ob 900 s nach einem `426` richtig gewählt sind, ist offen: Ein Server-Update ist genau der
> Fall, in dem man schnell zurückwill. Ein kürzerer Wiederanlauf (60 s) wäre zu erwägen —
> gegen das Argument, in einem toten Vertrag nicht weiterzureden, steht hier nichts.

### Und zwei Dinge, die dabei auffielen

**Die Melderliste hatte keine Altersgrenze.** FRS61s Position von sieben Stunden zuvor stand
als blauer Punkt gleichwertig neben der aktuellen. Behoben: Die Karte zeichnet nur Frisches,
die Tabelle nennt das Alter.

**`bauen.ps1` installierte nicht von selbst.** Die X-Plane-Fassung 1.2.0 lag gebaut im
Arbeitsordner, während im Simulator 1.1.0 lief — der Probeflug hätte getestet, was sich
nicht geändert hat. Behoben: Installieren ist jetzt die Vorgabe, `-NurBauen` die Ausnahme.

### ✅ X-Plane 1.2.0 gleich mit — und der Autogen-Befund

Dieselben drei Anforderungen, zweimal gestellt: einmal an die alte **1.1.0** mit ihrer
eigenen Tabelle, dann an die neue **1.2.0**, die keine mehr hat.

| Art | alte 1.1.0 | neue 1.2.0 | gesehen |
|---|---|---|---|
| `tier_gross` | steht, 1335,8 ft | steht, 1324,3 ft | ✅ **„hirsch ist da"** |
| `windrad` | **GATTUNG_UNBEKANNT** | steht, 1327,2 ft | ✅ **„windrad ist da"** |
| `leuchtturm` | **GATTUNG_UNBEKANNT** | steht, 1320,0 ft | ✅ **„leuchtturm ist da"** |

**Die linke Spalte ist der Beweis in die andere Richtung:** Eine Fassung-1-Brügge läuft am
neuen Server unverändert weiter (`tier_gross` steht) — aber alles, was nicht in ihrer
Tabelle steht, bleibt ihr verschlossen. Genau das war der Grund für den Umbau, und genau so
läuft FRS61 weiter, ohne etwas herunterzuladen.

> ### ⭐ AUTOGEN-OBJEKTE LASSEN SICH LADEN UND WERDEN GEZEICHNET
>
> **Das war vorher völlig offen** und ist der wertvollste Befund des Abends. Windrad und
> Leuchtturm liegen beide unter `Resources/default scenery/1000 autogen/US/industrial/` —
> einem Zweig, den `katalog_sammeln.py` bewusst ausspart („Autogen-Bausteine — die gehören
> in eine Szenerie, nicht an eine Kieker-Station").
>
> Die Begründung stimmt für Bänke und Gartentische. Für **64 Leuchttürme**
> (`lighthouse_13` bis `lighthouse_64` — die Zahl ist die Höhe in Metern), Windräder, Tanks,
> Masten und Schornsteine stimmt sie nicht.
>
> **Damit lohnt sich der Sammellauf**, der bisher nur eine Vermutung war: `airport scenery/`
> (333 Fahrzeuge, darunter `fire_truck_small_1.obj`) und `1000 autogen/US/industrial/`.
> Beides steht in `docs/offene-aufgaben.md`.

### Offen geblieben

- **Sichtbarkeit der übrigen Arten** — im Bild bestätigt sind Windrad, Hirsch und
  Leuchtturm; die restlichen 19 Arten sind nur als `steht` zurückgemeldet.

---

## ⭐ DER SEEHUND STEHT — X-Plane gesehen am 14.09.2026

**Erster Beweis im Simulator, und ausgerechnet in X-Plane** — dem Simulator, für den
Superspuds Paket nie etwas gelöst hätte. Eine Kolonie aus zwanzig Tieren, 120 m voraus bei
Passau: elf Kühe, drei Bullen, sechs Heuler, jedes mit gewürfelter Richtung.

Sein Urteil: **„sind da"**.

Damit ist belegt, was sich ohne Simulator nicht prüfen ließ: Die `.obj` lädt, X-Plane
zeichnet sie, und die Achsenumrechnung von Blender (Z-oben) nach OBJ8 (Y-oben) stimmt —
sonst läge das Tier auf der Seite oder im Boden.

### Noch offen an derselben Stelle

- **Farbe** — greift die Palettentextur? Graubraun wäre richtig, grau oder schwarz hieße,
  X-Plane findet `seehund.png` nicht.
- **Die gewürfelten Richtungen** — sehen sie natürlich aus oder zufällig im schlechten Sinn?
- **Aus welcher Entfernung ist die Kolonie erkennbar?** X-Plane hat MSFS' LOD-System nicht;
  die Bounding-Box-Grenze gilt dort nicht.

## ⭐ 200 OBJEKTE, DREIZEHN ARTEN, ALLES GLEICHZEITIG — X-Plane, 14.09.2026

**Der bisher größte Lauf, und er trägt.** Zwei Durchgänge, beide abgenommen:

| | |
|---|---|
| 200 Seehunde in fünf Rudeln, 90 bis 420 m gestaffelt | „scheint zu klappen" |
| 200 gemischte Objekte im Halbkreis, bis 400 m | **„sieht gut aus. lass sie stehen"** |

Die Mischung umfasste **alle dreizehn Arten, die X-Plane kann** — Boote, Hirsche, Möwen,
Windräder, Tanks, Masten, Kräne, Flugplatzfahrzeuge, Windsäcke und unsere beiden eigenen
Modelle (Rauch und Seehund). Sechs Rauchsäulen als Baaken, eine je Farbe; bei
gleichmäßiger Mischung wären es über dreißig gewesen, und darunter hätte man von den
Tieren nichts mehr gesehen.

### Was damit zum ersten Mal belegt ist

- **`SOLL_MAX` 200 trägt praktisch.** Die Grenze stand bis heute bei 32, und die Antwort
  bricht bei Überlauf **lautlos** ab — man hätte es nur an fehlenden Objekten gemerkt.
- **Die zufälligen Richtungen wirken.** Erster Praxistest des Kurses, der seit heute im
  Server gewürfelt wird; vorher zeigte alles nach Norden.
- **Die Autogen-Arten `kran`, `tank` und `mast` standen zum ersten Mal im Bild.** Sie
  stammen aus dem Sammellauf über `1000 autogen/US/industrial/` vom selben Tag — bis dahin
  war nur belegt, dass Autogen-Objekte *grundsätzlich* ladbar sind (Windrad, Leuchtturm).
- **Zweihundert Objekte gleichzeitig kosten nichts Sichtbares.** Vorher waren dreißig das
  Maximum (12.09.2026).

### Und was weiterhin offen ist

- **Aus welcher Entfernung ist eine Kolonie erkennbar?** Die Staffelung 90–420 m lag im
  Bild, aber gezählt hat sie niemand. Für den Kieker ist das die eigentliche Zahl.
- **Die Farbe des Seehunds** — greift die Palettentextur? Aus der Ferne nicht zu beurteilen.

## ✅ MSFS TRÄGT AUCH — 377 Objekte, beide Simulatoren (14.09.2026)

Dieselbe Kolonie in MSFS, an denselben Koordinaten. Sein Urteil: **„alles OK jetzt"**.

Damit ist der Seehund in **beiden** Simulatoren bestätigt, und zwar über zwei ganz
verschiedene Ketten: X-Plane lädt eine handgeschriebene OBJ8 mit PNG, MSFS ein glTF mit
KTX2 aus einem kompilierten Paket. Dass beide aus derselben Blender-Datei stammen, war die
eigentliche Frage.

### Nebenbei belegt

- **Ein Simulatorwechsel bei gleicher CID funktioniert.** X-Plane und MSFS melden
  verschiedene Kennungen (`fb0225a72bb734be` / `2119477d19353117`); die Objekte hängen an
  der CID und kamen in MSFS als `FrsSeehund_Kuh` an, wo X-Plane `…/seehund_kuh.obj` bekam.
- **Der Kennungs-Wettlauf in MSFS ist behoben.** `KENNUNG_WARTE_S 3` in der 1.10.0 — die
  Brügge meldete mit einer stabilen Kennung.
- **Ohne VATSIM geschieht wirklich nichts.** Im Log stand minutenlang *„keine Zuordnung
  (1 Kandidaten) -- kein Kandidat innerhalb 400 m / 300 ft"*, bis er gewechselt hatte.
  Die Schranke wirkt wie entworfen.

### ⚠ UND EIN BEFUND, DER ÜBER DIESEN TAG HINAUSREICHT: GESTREAMTE TITEL SIND NICHT SETZBAR

Von 402 angeforderten Objekten scheiterten **25**, und zwar ausschließlich zwei Arten:

| Art | Fehlschläge | MSFS-Titel | Quelle |
|---|---|---|---|
| `mast` | 14 | `VO_Fire_R1_150` … `_200` | `streamed` |
| `kran` | 11 | `Microsoft_Truck_Crane_Small` … | `streamed` |

Beide Arten **haben** MSFS-Titel — die Brügge hat alle durchprobiert und dann
`KEIN_MODELL_MEHR` gemeldet. Genau das Verhalten, für das der Rückfall gebaut wurde.

**Die Gemeinsamkeit ist `quelle='streamed'`.** Diese Titel stammen aus dem
`.fsarchive`-Leser vom selben Tag; sie stehen im Katalog, weil MSFS sie im
Paketverzeichnis nennt. Ob der Simulator sie **lokal vorliegen** hat, ist etwas völlig
anderes — gestreamte Pakete lädt er bei Bedarf nach, und `AICreateSimulatedObject` kann
nur setzen, was da ist.

⚠ **Das trifft potenziell jeden der 2642 gestreamten Titel**, nicht nur diese beiden Arten.
Und es fällt erst im Flug auf. Wer aus dem Katalog eine Art zusammenstellt, sollte
gestreamte Titel nicht allein stehen lassen — mindestens ein Titel aus `bord` oder
`community` gehört dahinter.

**In keinem Simulator gesehen.** Das Modell ist gebaut, in beide Pakete eingebaut und auf
dem Server der Art `robbe` zugeordnet — für MSFS **und** X-Plane. Was es leistet, weiß
niemand.

Anfordern lässt es sich über den Admin, Art `robbe`. In MSFS heißen die Titel
`FrsSeehund_Kuh` / `_Bulle` / `_Heuler`, in X-Plane liegen sie unter
`Resources/plugins/FriesenBruegge/objekte/seehund_*.obj`.

**Drei Dinge können stumm schiefgehen** — das Modell erscheint dann nicht, wie es soll,
ohne eine einzige Fehlermeldung:

| Frage | woran man es erkennt |
|---|---|
| Greift die Textur? | grauer oder schwarzer Seehund statt graubraun |
| Stimmen die Achsen? | liegt auf der Seite oder steckt im Boden |
| Wirken `minSize="0"` und `DistanceToNotAnimate`? | aus 200 ft nicht zu sehen |

⚠ **`DistanceToNotAnimate=2000` ist gesetzt, aber ungeprüft — und zwar anders ungeprüft als
beim Rauch.** Dort gibt es einen nachvollziehbaren Zusammenhang: Ein Partikel-Emitter läuft
ohne Animation nicht. Ein Seehund ist starre Geometrie; es gibt daran nichts zu animieren.
Der Wert steht dort, weil Aerosofts Wangerooge-Paket ihn bei **allen** SimObjects setzt,
nicht weil seine Wirkung belegt wäre. Bleibt der Seehund aus der Luft unsichtbar, ist er
**nicht** die Ursache — dann liegt es am LOD oder am Modell selbst.

### ⚠ Und eine Schranke, die schon feststeht: die Reichweite

Aus der Rauch-Messung derselben Sitzung (14.09.2026): **Eine Rauchsäule trägt 6480 m
(3,5 NM), und dort ist eine harte Grenze.** `MaxDistanceEmission` 15000 und 50000 geben
beide denselben Wert; nur die Vorgabe 2000 wirkt 1:1. Die SDK-Doku nennt kein Maximum.

⚠ **Und für den Seehund gilt sie NICHT — das war mein Fehlschluss, hier steht er
korrigiert.** Die 6480 m sind die Grenze des **Partikelsystems**. Ein Seehund hat keine
Partikel; bei ihm entscheidet allein die **Geometrie**, und die trägt nachweislich weiter
(ein `CruiseShip01` war aus 22 km zu sehen).

Was zur Geometrie belegt ist, sind genau zwei Punkte — beide aus der Rauch-Messreihe:

| Bounding Box | sichtbar ab | Anmerkung |
|---|---|---|
| 2 m | 100 m | **mit `minSize="0"` bereits gesetzt** |
| 90 m | ≥ 1830 m | wie viel mehr, verdeckt die Partikelgrenze |

Die erste Zeile ist die wichtigere: `minSize="0"` kam einen Commit **vor** der 90-m-Säule
(`f7673a6`), der Nutzer ist dazwischen geflogen und sah keine Änderung. **Die Größe der
Bounding Box schlägt `minSize` glatt** — es gibt im Simulator eine zweite
Entfernungsprüfung, die an `minSize` vorbeigeht. Welche, ist unbekannt; dass es sie gibt,
ist gemessen.

Ein 1,6-m-Tier liegt damit am unteren Ende einer Skala, deren Verlauf wir nicht kennen.
**Der Weg ist ein unsichtbarer Träger**, wie ihn der Rauch schon hat: ein Quader mit
`ASOBO_material_invisible` (`paket_bauen.py`, 24 Ecken — jede Fläche braucht ihre eigene
Normale), der Seehund als sichtbares Teil darin. Zwei Dinge dabei beachten:

- **Der Quader steht auf dem Ursprung, nicht um ihn herum** (`min[1] = 0.0`). `auf_boden`
  setzt den Ursprung auf Geländehöhe; ein zentrierter Quader steckt zur Hälfte im Watt.
- **Ungeprüft ist, ob MSFS unsichtbare Geometrie überhaupt mitmisst.** Beim Rauch war der
  Träger immer unsichtbar, ein Gegenversuch fehlt. Bringt ein großer unsichtbarer Träger
  nichts, ist das die erste Stelle zum Nachsehen — ein Durchgang mit sichtbarem Material
  trennt die beiden Fälle.

Das ist keine Schwäche des Modells, sondern eine Vorgabe für den **Kieker**: Eine Kolonie
findet man nicht durch Suchen am Horizont. Entweder der Server nennt das Gebiet (Karte im
Kniebrett), oder die Aufgabe gibt eine Route vor, die daran vorbeiführt. Beides ist
ohnehin näher an dem, was echte Seehundzähler tun.

### Und zwei Dinge, die nur im Flug zu beantworten sind

1. **Aus welcher Entfernung ist ein Seehund erkennbar?** Gerechnet sind es aus 200 ft rund
   30 Pixel schräg voraus und 55 senkrecht darunter — gemessen ist nichts. Davon hängt ab,
   wie eng der Kieker seine Kolonien setzen darf.
2. **Was kosten viele?** Ein Objekt mit `DistanceToNotAnimate=2000` wird auch dann
   mitgeführt, wenn niemand hinsieht. Bei einer Handvoll egal — eine Kolonie sind zwanzig,
   und ein Event mehrere Kolonien. Vor dem ersten Kieker gehört das gemessen.

---

## ✅ 30 s SIND ABGENOMMEN — und X-Plane ist es ganz (14.09.2026)

Beide Simulatoren im Flug gesehen, bei **10 kt** Wind. Sein Urteil:

> *„xplane ist jetzt OK. … xPlane ist schöner, weil sich kleine Wölkchen bilden und es
> besser auf den Wind reagiert."*

**X-Plane ist damit fertig** — die 30 s stimmen, die Fahne franst aus und weht sichtbar ab.
**MSFS war es nicht**, und die beiden Mängel hatten zwei verschiedene Ursachen, die beide
gefunden sind.

### ⚠ Ursache 1: Jedes MSFS-Partikel zeigte SECHZEHN Wölkchen auf einmal

Die Textur ist ein 4×4-Atlas. **X-Plane kennt Zellen** (`TEX_CELLS_X/Y`,
`ANIM_CELL_RANDOM 1`) und zieht je Partikel **eine** der sechzehn Formen — daher die
Wölkchen. **MSFS kennt sie nicht:** Sein Material bildet die Datei mit `UVScale 1.0` auf
**jedes** Partikel ab. Ein MSFS-Partikel war also ein Raster aus sechzehn Scheiben, und
hundert Raster übereinander ergeben zwangsläufig eine glatte Fläche. Eine einzelne Wolke
konnte darin gar nicht entstehen.

Asobos eigene Rauchtextur (`SDK/Samples/…/vfx_smoke.png`) ist genau deshalb **eine** große
fransige Wolke über die volle Fläche — sein Material steht ebenfalls auf `UVScale 1.0`.
MSFS bekommt jetzt eine eigene Textur nach diesem Vorbild (`msfs-rauch/rauch_msfs.png`,
dieselbe Rauschfunktion mit `atlas=1`).

### ⚠ Ursache 2: Meine eigene 30-s-Umstellung hat den Wind gedämpft

MSFS hat eine **Streckendämpfung**, die X-Plane gar nicht kennt: Ein Partikel wird
ausgeblendet, sobald es seitlich weit genug getragen wurde (gegen die kilometerlange Fahne
vom 13.09.2026). Sie stand fest auf **60 m** — eingestellt bei 22 s und 66 m Säulenhöhe.

Mit 30 s wuchs die Säule auf 90 m, die 60 m blieben stehen. Ein Partikel lebt länger, wird
weiter getragen und trifft die feste Grenze **früher in seinem Leben**:

| bei 10 kt, Alter 0,8 | seitlich | Dämpfung |
|---|---|---|
| 22 s / 60 m (der Screenshot) | 36 m | 0,38 |
| 30 s / 60 m (so gebaut) | 49 m | **0,10** |
| 30 s / 82 m (jetzt) | 49 m | 0,39 |

**Der Mangel, den er benannt hat, war also zum Teil frisch von mir eingebaut.** Die
Bezugsweite hängt jetzt an der Säulenhöhe (`0,909 × _HOEHE_M`), wie alles andere auch. Bei
27 kt bleibt die Begrenzung wirksam (Dämpfung 0,12 schon bei Alter 0,6).

### Und der Fuß ist jetzt in beiden gleich

Seine Entscheidung nach dem Vergleich: X-Plane von 1,20 m **herunter** auf 0,80 m, also auf
den MSFS-Wert. Damit ist die Säule in beiden Simulatoren von unten bis oben gleich
vermessen — 0,80 m am Fuß, 11,97 m an der Krone, 90 m hoch.

### ⭐ Was beim nächsten Start zu sehen ist

Neue Fassungen: **MSFS 1.8.2**, **X-Plane 1.2.2**. Beide installiert, beide brauchen einen
Neustart ihres Simulators.

| | was zu prüfen ist |
|---|---|
| **MSFS, Struktur** | Bilden sich jetzt einzelne Wölkchen statt einer glatten Fläche? Das ist die Hauptfrage — Ursache 1. |
| **MSFS, Wind** | Weht die Fahne sichtbar ab? ⚠ Nicht erwarten, dass sie so weit trägt wie in X-Plane: Dort gibt es **keine** Begrenzung, hier endet sie bei 82 m. Ob die Zahl stimmt, sagt nur das Bild. |
| **MSFS, Leistung** | Die 22 s waren eine Leistungsentscheidung. 30 s heißen 36 % mehr gleichzeitige Partikel — Bildrate neben der Säule, und ob mehrere Säulen nebeneinander tragen. |
| **X-Plane, Fuß** | Nur der schmalere Fuß hat sich geändert. Verwäscht die Quelle jetzt, oder ist sie besser ortbar? |

⚠ **Beide nebeneinander anschauen, wenn es geht.** Der Sinn der Übung ist, dass sie sich
gleichen; jede für sich betrachtet sagt darüber nichts.

## ✅ SICHTWEITE DER RAUCHSÄULE — GELÖST (14.09.2026)

**Von 100 m auf 3,5 NM**, und dort ist eine harte Grenze. Der Befund war *„die säulen
kommen erst 100m vorher"*; gebraucht hat es zwei Schritte — und drei, die nichts brachten.

| Schritt | sichtbar ab | was tatsächlich wirkte |
|---|---|---|
| Ausgangslage, 2-m-Träger | 100 m | das **Objekt** war zu klein und wurde ausgeblendet |
| Träger auf 12 × 90 × 12 m | 1830 m | Objekt groß genug — jetzt greift die Partikelschranke |
| Träger auf 40 × 300 × 40 m | 1830 m | **nichts** — siehe Warnung unten |
| **`MaxDistanceEmission` 15000** | **6480 m = 3,5 NM** | das eigentliche Feld |
| `MaxDistanceEmission` 50000 | 6480 m | **harte Schranke**, die Doku nennt keine |

Gesetzt bleibt **15000**: Alles darüber ist Rechenlast ohne Sicht.

### ⭐ `MaxDistanceEmission` — das Feld, das die Suche beendet hat

Die SDK-Doku nennt genau eines für die Sichtweite eines Partikeleffekts:

> *„Once the camera exceeds this distance from the emitter, particles will stop being
> created."* — **Standardwert: 2000 Meter.**

Wir hatten es nie gesetzt, also galt die Vorgabe. Der gemessene Abriss bei **1830 m** passt
dazu, und **eine Seemeile sind 1852 m** — die Zahl war die ganze Zeit ein Fingerzeig.

⚠ **Gefunden hat es eine Web-Recherche, auf Verlangen des Nutzers.** Davor drei Anläufe
geraten, alle im Flug widerlegt:

| Versuch | warum er nichts brachte |
|---|---|
| `minSize="0"` im LOD | regelt die Bildschirmgröße des **Modells** |
| `DistanceToNotAnimate=15000` | regelt die **Animation**, nicht das Spawnen |
| Träger 90 → 300 m | siehe die Warnung gleich darunter |

`minSize` und `DistanceToNotAnimate` bleiben trotzdem gesetzt — sie schaden nicht, und
Asobo selbst nutzt `DistanceToNotAnimate=15000` in `wENLK_lightdummy`.

### ⚠⚠ Die 300-m-Messung war VERDECKT — wer sie zitiert, zitiert einen Messfehler

„Träger 300 m brachte nichts" steht oben in der Tabelle und stimmt als Beobachtung. Als
Aussage über Geometrie ist es **falsch**, und der Unterschied entscheidet alles, was ohne
Partikel gebaut wird.

Während der ganzen Träger-Reihe stand `MaxDistanceEmission` noch auf der Vorgabe 2000. Ab
90 m war deshalb nicht mehr die Geometrie der Engpass, sondern der Effekt. Die 300-m-Zeile
misst die Partikelgrenze ein zweites Mal — über Geometrie sagt sie nichts.

**Belegt sind über Geometrie genau zwei Punkte:** 2 m → 100 m (mit `minSize="0"`!) und
90 m → mindestens 1830 m. Dazwischen und darüber ist nichts gemessen. Für Seehunde, Tiere
und Fahrzeuge gilt allein diese Skala — dort fällt die Partikelgrenze weg.

### ⚠ Hin- und Wegflug sind verschieden, und das ist kein Fehler

Der Nutzer sieht die Säule beim **Hinflug erst bei 3,5 NM**; beim Wegflug hört sie von
unten her auf und wirkt dadurch länger da, als sie emittiert. Beides ist dieselbe Grenze.

Der Emitter beginnt in beiden Richtungen bei 6480 m. Beim Hinflug braucht die Säule aber
ihre **30 Sekunden Lebensdauer**, um von unten aufzuwachsen — der Nutzer beschrieb es
genau so: *„Sie steigt langsam vom Boden auf."*

**Für eine Baake ist das die ungünstigere Richtung** — man soll sie beim *Hin*flug finden.
Wer das verbessern will, setzt an der Aufbauzeit an (kürzere Lebensdauer bei höherer Rate
ergäbe dieselbe Säule, schneller aufgebaut), nicht an der Reichweite.

### Was weiter reicht als Partikel: ein Licht

Positionsleuchten sieht man kilometerweit, wenn das Flugzeug längst ein Punkt ist — sie
sind kein Geometrie-, sondern ein Licht-Sprite mit eigener Reichweite.

**Ein SimObject kann aus nichts als Licht bestehen**, belegt am 14.09.2026:
`fs24-microsoft-airport-enlk-leknes` enthält `wENLK_lightdummy` mit genau diesem Zweck.
Seine `sim.cfg`:

```ini
[General]
category=Human ;StaticObject
DistanceToNotAnimate=15000
```

Die Kategorie ist **`Human`**, nicht `StaticObject`, mit der Alternative als Kommentar
daneben — die Kategorie beeinflusst das Verhalten also.

**Woran es fehlt:** Die Lichtdefinition steckt im Modell (glTF-Erweiterung
`ASOBO_macro_light`), und das liegt im verschlüsselten Archivteil. Nachbaubar, aber ein
eigener Umbau. Für eine Baake wäre es die bessere Lösung: eine rote Blitzleuchte auf der
Säulenspitze, die man sieht, **bevor** man den Rauch sieht.

### Was ungemessen bleibt

**Was ein Emitter kostet, der aus 6,5 km spawnt.** Bei einer Fackel egal; bei zwanzig
Kolonien mit je einer Säule gehört es gemessen, bevor der Kieker so etwas setzt.

---

## ⭐ ZWEI CLIENT-FEHLER, BEHOBEN UND UNGEPRÜFT (14.09.2026)

### Die Kennung überlebte keinen Neustart

Gemessen, nachdem sie dreimal hintereinander wechselte:

```
-rw-r--r-- 1 Tobias 0  17:12:09  friesenbruegge.kennung
```

**Null Bytes.** `fsIOWrite` ist asynchron (es nimmt einen `FsIOFileWriteCallback`,
MSFS_IO.h Zeile 62) — das `fsIOClose` direkt danach überholte das Schreiben. Jetzt wird im
Callback geschlossen.

⚠ **Dieselbe Falle stand zwanzig Zeilen tiefer schon beschrieben** (dort überholte das
Schreiben das asynchrone *Lesen*). Ich hatte den Kommentar gelesen, verstanden — und beim
Schreiben nicht wiedererkannt.

### Der Flugzeugtitel kam nie an

`SimConnect_AddToDataDefinition(..., "TITLE", ...)` — Asobos eigenes SDK-Beispiel
(`RequestData.cpp`, Zeile 121) schreibt **`"Title"`**. Mit der Großschreibung feuerte der
Callback nie. Bei anderen SimVars ist die Schreibweise gleichgültig, bei dieser offenbar
nicht.

**Zu prüfen ist beides am selben Start:** Bleibt die Kennung nach einem Neustart dieselbe
(sichtbar in `bruegge_zuordnung`), und steht der Flugzeugtitel danach im Katalog
(`quelle='gemeldet'`)?

---

## Vorbereitung (einmal, vor dem Start)

**Der Stand ist schon abgelegt** — Paket `friesenbruegge` liegt im Community-Ordner, Fassung
**1.1.3**. Nichts mehr zu bauen.

> ### ⚠ Zuerst: lädt das Modul überhaupt?
>
> Am 12.09.2026 wurde das Paket einen Tag lang **gar nicht geladen**. Ursache war ein
> UTF-8-BOM in `manifest.json` und `layout.json` — `Set-Content -Encoding UTF8` schreibt
> unter Windows PowerShell 5.1 eines, unter PowerShell 7 nicht. Das Paket wird damit
> registriert, gemountet und in der `Content.xml` als „Activated" geführt, aber MSFS kann die
> `layout.json` nicht parsen, findet null Inhalte und sieht die `.wasm` nie. **Keine
> Fehlermeldung, keine Logzeile** — von außen sieht es aus wie ein übergangenes Paket.
> `paket.ps1` schreibt jetzt ohne BOM und prüft sich selbst.
>
> **Erste Zeile, auf die zu achten ist** (DevMode-Konsole):
>
> ```
> WASM: Module bruegge.wasm loaded
> ```
>
> Kommt sie nicht, ist jede weitere Messung sinnlos — dann erst das Laden klären.
> Die Gegenprobe ist schnell: In `.../Community/friesenbruegge` müssen `manifest.json` und
> `layout.json` mit `7b` („`{`") beginnen, nicht mit `ef bb bf`.

```
MSFS 2024 starten  →  Flug laden  →  vPilot verbinden (FRS49 oder FRS49N)
```

Ohne VATSIM-Verbindung geschieht **nichts** — das ist die Regel, nicht der Fehler. Und ohne
Forum-Login der CID ebenso wenig.

**Nach dem Verbinden höchstens 10 Sekunden warten**, dann steht die Zuordnung.

---

## 1. Setzt die Brügge ein Objekt aus `soll`?

> ### ✅ Gemessen am 12.09.2026 — **ja, sie setzt**
>
> Ein `tier_gross` (BlackBear) wurde 30 m vor dem stehenden Flugzeug angefordert und war
> sofort da. Damit trägt die Kette von Ende zu Ende: Admin → `bruegge_soll` → Antwort des
> Endpunkts → `soll_abgleichen` im Modul → `AICreateSimulatedObject` → sichtbares Objekt.
>
> **Nebenbefund, und kein kleiner: Der Bär stand auf einem Zelt.**
>
> Die Höhe kommt aus der Geländeabfrage, und die kennt **nur das Terrain, keine
> Szenerie-Objekte**. Die Brügge setzt also auf den nackten Boden und merkt nicht, was dort
> schon steht — hier ein Zelt des Campout-Moduls, anderswo ein Gebäude, ein Hangar, eine
> Mauer.
>
> ⚠ **Für den Kieker ist das eine Spielregel, keine Randnotiz:** Eine Station, die in einem
> Gebäude oder auf einem Dach landet, ist entweder unsichtbar oder unerreichbar. Wer
> Stationen setzt, kann sich auf „der Boden ist frei" nicht verlassen — und der Server hat
> keine Möglichkeit, das von sich aus zu prüfen. Die gemeldete `hoehe_ft` aus dem
> `steht`-Block ist der einzige Hinweis, den er bekommt, und sie sagt nur, wie hoch das
> Objekt liegt, nicht worauf.

**Die Kernfrage.** Alles Weitere hängt daran.

Im Admin (`/admin`, Panel „🌉 Brügge") ein `boot_gross` anfordern — Breite und Länge aus der
eigenen Position, ein paar hundert Meter versetzt. Oder per curl:

```
POST /api/admin/bruegge/soll   {"art":"boot_gross","lat":…,"lon":…}
```

| Beobachtung | heißt |
|---|---|
| Schiff steht da | ✅ die Brügge setzt |
| nichts zu sehen | `--boote-zaehlen` als Gegenprobe (s. unten) — das Auge taugt nicht |

⚠ **Ein „ich sehe nichts" ist ohne Gegenprobe nichts wert.** Ein `Boat01` misst acht Meter und
ist erst ab rund **1 km** eingeblendet (am 11.09. gemessen); ein `CruiseShip01` ab 22 km.
Deshalb im Zweifel:

```
python probe-msfs/kieker_probe.py --boote-zaehlen --radius 5000
```

---

## 2. Kommt `steht` korrekt zurück?

Das ist der einzige Weg, auf dem der Server erfährt, ob eine Stelle taugt — **FriesenSpy hat
kein Geländemodell.**

> ⚠ **Bis v14.30.1 war das gar nicht messbar.** Die Brügge sendete den `steht`-Block seit
> Fassung 1 und das Protokoll sah ihn vor — der Endpunkt las ihn schlicht nicht aus und warf
> ihn weg. Aufgefallen ist das erst beim Versuch, genau diesen Punkt zu messen: Es war
> nirgends etwas da. Seit v14.30.1 landet die Rückmeldung in `bruegge_steht` und steht im
> Admin **in derselben Zeile wie die Anforderung**, unter „steht wirklich?".

```
GET /api/admin/bruegge      →  Melder, soll UND steht
```

Zu prüfen: Meldet die Brügge `zustand: steht` mit einer **plausiblen Höhe**? Am Wasser rund
0 ft, über Land die Geländehöhe.

⚠ Die Höhe wird aus `PLANE ALTITUDE − PLANE ALT ABOVE GROUND` **gerechnet**, weil `OnGround=1`
aus WASM heraus nicht aufsetzt (gemessen: 49 ft auf Wangerooge, 122–130 ft in Seattle). Das
ist die Höhe **unter dem Flugzeug**, nicht am Zielort — für ein Objekt wenige hundert Meter
daneben taugt sie, für eines 5 km weiter nicht.

> ### ✅ Gegenprobe gemessen am 12.09.2026 — **die Höhe ist ein Echo, keine Messung**
>
> Drei `boot_gross` in 2, 5 und 10 km Entfernung nach Norden, ins Bergland:
>
> | Entfernung | gemeldete `hoehe_ft` |
> |---|---|
> | 2 km | 1378,2 |
> | 5 km | 1378,2 |
> | 10 km | 1378,2 |
> | *Boden unter dem Flugzeug* | *1378,2* |
>
> Auf die Nachkommastelle identisch — **der Simulator gibt zurück, was hineingeschrieben
> wurde.** Die Rückmeldung bestätigt nicht die Platzierung, sie wiederholt die Anforderung.
>
> Das schärft den Bodensee-Fund vom 11.09. (2106,5 ft aus der Ferne, 1297,2 ft aus der Nähe):
> Es ist nicht „grobes Gelände", es ist **gar keine Messung**.
>
> **Regel für den Kieker:** Für ein Objekt in der Nähe des Piloten ist `gelaendehoehe()`
> brauchbar (am Boden auf 1–2 ft genau gemessen). Für alles Weitere ist sie geraten, und die
> Rückmeldung deckt den Irrtum nicht auf. Wer Stationen im Voraus verteilt, muss die Höhe
> **mitliefern** — `erwartete_hoehe_ft` wirkt exakt (s. Punkt 2b) und ist genau dafür da.
>
> ⚠ **Das ändert nichts am Befund des Flugtests** („der Server darf einmal verteilen", s.
> `probe-msfs/FLUGTEST.md`) — es ergänzt ihn um eine Bedingung: verteilen ja, aber mit Höhe.

---

## 2b. Der Referenzpunkt eines Modells liegt NICHT am Boden

> ### ✅ Gemessen am 12.09.2026 — mit zwei Booten im selben Bild
>
> Ein `boot_klein` auf Geländehöhe und eines 10 ft darüber, nebeneinander:
>
> | | Was zu sehen ist |
> |---|---|
> | 10 ft über Grund | komplettes Motorboot — Rumpf, Deck, Verdeck |
> | auf Geländehöhe | **nur Verdeck und Streben** — der Rumpf steckt im Boden |
>
> **Der Referenzpunkt eines Bootsmodells liegt an der Wasserlinie, nicht am Kiel.** Wird es
> auf Geländehöhe gesetzt, verschwindet alles darunter im Boden — bei `Boat01` rund
> anderthalb Meter.
>
> ⚠ **Und der Simulator meldet dabei nichts Auffälliges:** Die zurückgegebene `hoehe_ft` ist
> die des Referenzpunkts, und die stimmt. Aus den Zahlen allein ist das Versenken **nicht**
> zu erkennen — es brauchte den Blick aus dem Cockpit. Das ist die Gegenrichtung zur Lehre
> von Punkt 3b (*der Simulator weiß es besser als das Auge*): Hier weiß das Auge es besser.
> Beide Prüfungen sehen verschiedene Dinge, und keine ersetzt die andere.
>
> **Folge für den Kieker — zwei Regeln:**
>
> 1. „Auf Geländehöhe setzen" heißt **nicht** „steht auf dem Boden". Jede Gattung hat ihren
>    eigenen Referenzpunkt; ein Tier steht auf den Pfoten, ein Boot auf der Wasserlinie.
> 2. `erwartete_hoehe_ft` ist der Hebel dagegen — **nachweislich exakt**: 1388,2 ft
>    angefordert, 1388,2 ft gesetzt. Damit kann der Server einen Versatz je Gattung vorgeben.
>
> **Offen:** der Versatz je Gattung ist nicht vermessen. Für `boot_klein` liegt er bei rund
> 4–5 ft; für `tier_gross`, `bauwerk` und `fahrzeug` ist er unbekannt. Das ist eine
> Stand-Messung und braucht keinen Flug.

---

## 2c. DIE SONDE — ✅ `OnGround=1` wirkt doch, und misst das Gelände am Zielort

> **Gemessen am 12.09.2026, und es ist der wichtigste Befund des Tages.** Die Idee stammt vom
> Nutzer: erst etwas hinstellen, das sich selbst auf den Boden setzt, die gemeldete Höhe
> ablesen, dann das eigentliche Objekt mit `erwartete_hoehe_ft` setzen.
>
> Fünf Sonden nebeneinander, alle mit `auf_boden: 1` **und einer absichtlich um 200 ft zu
> hohen** `erwartete_hoehe_ft` — so ist am Rückgabewert eindeutig zu sehen, ob das Flag
> gewirkt hat:
>
> | Sonde | angefordert | **gemeldet** | |
> |---|---|---|---|
> | `bauwerk` | 1565,5 ft | **1370,0 ft** | aufgesetzt |
> | `boot_klein` | 1565,5 ft | **1367,3 ft** | aufgesetzt |
> | `boot_gross` | 1565,5 ft | **1358,7 ft** | aufgesetzt |
> | `tier_gross` | 1565,5 ft | **steht** (im Bild) | aufgesetzt — die Meldung log |
> | `fahrzeug` | — | `KEINE_ANTWORT` | einziger echter Fehlschlag |
>
> **Keines steht auf den angeforderten 1565,5 ft.** Der frühere Befund „`OnGround=1` ist aus
> WASM unbrauchbar" (11.09.2026, nur mit `Boat01` geprüft) gilt so **nicht**.
>
> ### Und der eigentliche Ertrag: die drei Werte sind VERSCHIEDEN
>
> 1358,7 — 1367,3 — 1370,0 ft, über 160 m Breite verteilt: **11,3 Fuß Geländeunterschied.**
> Genau die Welligkeit, die in 5c zwölf Boote unterschiedlich tief versenkt hat. Der Boden
> unter dem Flugzeug lag bei 1365,5 ft — **keiner der drei Orte trifft das.**
>
> ### ⚠⚠ DER SONDENUMWEG IST GESTRICHEN — `auf_boden: 1` genügt allein
>
> **Nutzerentscheidung, 12.09.2026**, nachdem die Messung oben lief: *„Streiche den
> Sondenumweg! Dass du nicht ständig wieder damit kommst."*
>
> Der Gedanke war, mit einer Sonde erst die Geländehöhe zu **messen** und das eigentliche
> Objekt dann mit `erwartete_hoehe_ft` zu setzen — drei Schritte. **Das ist überflüssig:**
> Wenn `OnGround=1` wirkt, setzt der Simulator das Objekt selbst auf den Boden. Man muss die
> Höhe gar nicht wissen.
>
> Gemessen mit **vier Gattungen gleichzeitig, alle ohne jede Höhenangabe**:
>
> | | gemeldet |
> |---|---|
> | `og-tier_gross` | 1367,5 ft |
> | `og-bauwerk` | 1369,5 ft |
> | `og-boot_klein` | 1368,6 ft |
> | `og-fahrzeug` | 1363,0 ft |
>
> Alle vier liegen sauber auf ihrem jeweiligen Gelände, und die Werte unterscheiden sich um
> 6,5 ft — die Welligkeit ist also berücksichtigt, ohne dass jemand sie berechnet hätte.
>
> **Der Weg für MSFS 2024 lautet damit schlicht:**
>
> ```
> { "art": "tier_gross", "lat": …, "lon": …, "auf_boden": 1 }
> ```
>
> ### Die Sonden-IDEE bleibt aufgehoben — für MSFS 2020
>
> Aufheben, nicht wegwerfen (ebenfalls Nutzerentscheidung): **Für MSFS 2020 ist ungemessen,
> ob `OnGround=1` dort wirkt.** Tut es das nicht, ist die Sonde der Ausweg, und sie ist dann
> vollständig durchgemessen und einsatzbereit:
>
> ```
> 1. Sonde setzen    { "art": "bauwerk", "auf_boden": 1, "lat": …, "lon": … }
> 2. Höhe ablesen    "steht": [{ "id": "sonde", "hoehe_ft": 1370.0 }]
> 3. Sonde weg, Objekt hin   { "art": "…", "erwartete_hoehe_ft": 1370.0 }
> ```
>
> Ein zweiter Fall bleibt ihr ebenfalls: wenn der **Server** die Geländehöhe wissen will, ohne
> ein Objekt stehenzulassen — etwa um beim Planen zu prüfen, ob eine Station im Wasser läge.
> Fürs bloße Platzieren braucht er sie nicht.
>
> **Nebenbei bewiesen:** Fassung 1.2.0 läuft — sonst wäre `auf_boden` ignoriert worden und
> alle fünf hätten 1565,5 gemeldet.
>
> ### ✅ Und der ganze Ablauf, am Stück gemessen (12.09.2026)
>
> Ein `bauwerk` als Sonde **250 m voraus**, mit absichtlich 300 ft zu hoher Anforderung:
>
> | | |
> |---|---|
> | Boden unter dem Flugzeug | 1386,4 ft |
> | **Sonde meldet** | **1422,1 ft** |
> | Unterschied auf 250 m | **35,7 ft — elf Meter** |
>
> Dann Sonde weg und **zwei** `boot_klein` an dieselbe Stelle, 60 m auseinander:
>
> | Boot | Höhe aus | Ergebnis |
> |---|---|---|
> | rechts | **der Sondenmessung** (1422,1 ft) | ✅ steht sauber im Feld, voller Rumpf |
> | links | der Höhe unterm Flugzeug (1386,4 ft) | ✖ **elf Meter im Boden, unsichtbar** |
>
> Der Zähler findet **beide** (`146980866` und `146800641`) — das versunkene existiert, es ist
> nur begraben. Weder das Auge noch die Rückmeldung allein hätten das verraten; erst der
> Vergleich zeigt es.
>
> **Das Verfahren steht damit vollständig:**
>
> ```
> 1. Sonde setzen   { "art": "bauwerk", "auf_boden": 1, "lat": …, "lon": … }
> 2. Höhe ablesen   "steht": [{ "hoehe_ft": 1422.1 }]
> 3. Sonde weg, Objekt hin   { …, "erwartete_hoehe_ft": 1422.1 }
> ```
>
> Kein Höhenmodell, kein Überflug, keine fremde Datenquelle — gemessen in genau dem
> Simulator, in dem das Objekt später stehen soll.

> ### ✅✅ Und sie trägt über ZEHN KILOMETER (12.09.2026)
>
> Die entscheidende Frage am Verfahren: Misst die Sonde auch dort, wo der Pilot **nicht** ist?
> Vier `bauwerk`-Sonden nach Süden ins Bergland, alle mit absichtlich 500 ft zu hoher
> Anforderung (1886,5 ft):
>
> | Sonde | **gemeldet** |
> |---|---|
> | 1 km | **1425,2 ft** |
> | 3 km | **1422,5 ft** |
> | 6 km | **1311,4 ft** |
> | 10 km | **1297,5 ft** |
>
> **Keine steht auf der angeforderten Höhe** — alle sind aufgesetzt, und das Gelände fällt
> über die Strecke um **128 Fuß** ab.
>
> ⚠ **Die Gegenprobe liegt in der letzten Zeile:** Der Bodensee liegt bei 395,5 m =
> **1297,6 ft**. Die 10-km-Sonde meldet **1297,5 ft** — sie steht im Wasser und trifft den
> Seespiegel auf einen Zehntelfuß. Das ist keine Schätzung, das ist eine Messung.
>
> ### Damit ist auch das „Phantom vom 11.09." erklärt
>
> Damals meldete ein Schiff am Bodensee aus der Ferne 2106,5 ft und aus der Nähe 1297,2 ft.
> Daraus wurde geschlossen: *„Aus der Ferne lügt sogar die Lagemeldung."* **Das stimmte
> nicht.** Es stand wirklich auf 2106,5 ft — die *gerechnete* Höhe war falsch, nicht die
> Meldung. Mit `OnGround=1` steht dasselbe Objekt aus 10 km Entfernung sofort richtig.
>
> ### Folge für den FriesenKieker
>
> **Der Server kann ein Revier vorab vermessen, ohne dass jemand hinfliegt.** Sonden setzen,
> Höhen einsammeln, Sonden wegräumen, Stationen exakt platzieren — aus der Ferne, in wenigen
> Takten. Das war die offene Architekturfrage aus 5c, und sie ist damit beantwortet.

> ### ⚠ Und ein Bug, den erst der Blick aus dem Cockpit aufdeckte
>
> `tier_gross` wurde als **`fehlgeschlagen / EXCEPTION_22`** gemeldet — **der Bär stand aber
> sichtbar im Gras** (Screenshot). Ursache in `SIMCONNECT_RECV_ID_EXCEPTION`: Die Exception
> wurde dem *letzten unbestätigten* Erzeugungsversuch zugeschrieben, weil `dwSendID` angeblich
> nicht zuzuordnen sei. Bei fünf gleichzeitig gesetzten Objekten kam sie vom **Fahrzeug** und
> landete beim **Bären**, dessen Objekt-ID noch unterwegs war.
>
> **Das ist schlimmer als ein falsches Etikett:** Ohne zugeordnete Objekt-ID kann die Brügge
> das Objekt **nie wieder abräumen** — es steht bis zum Verbindungsende. Und der Server hält
> die Stelle für unbrauchbar und setzt die nächste Station woanders hin. Zwei Objekte, eines
> davon für alle Beteiligten unsichtbar.
>
> **Behoben in 1.2.1:** `SimConnect_GetLastSentPacketID` merkt beim Erzeugen die Paketnummer,
> die Exception nennt sie in `dwSendID` — die Zuordnung ist damit **exakt statt geraten**.
> Passt eine Exception zu keinem Erzeugungsversuch, wird sie **gar keinem** Objekt angehängt;
> lieber keine Meldung als eine falsche.
>
> ⚠ **Rückwirkend erklärt das auch die Vierergruppe (5b-Vorgeschichte):** Dort galt
> `tier_gross` ebenfalls als `EXCEPTION_22` und `fahrzeug` als `KEINE_ANTWORT` — dasselbe
> Muster. Daraus wurde damals fälschlich geschlossen, die *Gleichzeitigkeit* sei schuld.
>
> ### Offen
>
> - **`fahrzeug` scheitert weiterhin**, auch einzeln. `ASO_Ambulance_Japan` ist der
>   Verdächtige — ein Titel aus dem 2020er Bestand. Die Titelsuche der Probe taugt als Beleg
>   nicht (sie findet `BlackBear` und `Windmill` ebenfalls nicht, beide funktionieren).
> - Ob die gemeldete Höhe wirklich das Gelände trifft oder nur den Referenzpunkt des
>   Sondenmodells (2b), ist ungeprüft. Für `bauwerk` (Windmühle, Fundament am Boden) ist die
>   Verwechslungsgefahr am kleinsten — deshalb ist sie die richtige Sonde.

---

## 2d. Tiere und Fahrzeuge BEWEGEN SICH von selbst — ✅ gemessen am 12.09.2026

> **Das Fahrzeug rollt davon** (vom Nutzer im Cockpit gesehen). Die `ASO_*`-Modelle sind
> Flughafenfahrzeuge und bringen eigenes Fahrverhalten mit — ein `AICreateSimulatedObject`
> erzeugt eben ein **AI**-Objekt.
>
> | Objekt | bewegt sich? | |
> |---|---|---|
> | `fahrzeug` | **ja, rollt weg** | gesehen |
> | `tier_gross` | **nein, steht starr** | gesehen |
> | `bauwerk`, `boot_klein` | nein | gesehen und gemessen |
>
> ### ⚠ Zwei Fehlschlüsse aus DIESER Messung, beide vom Nutzer korrigiert
>
> **1. „Der Bär bewegt sich auch."** Hier stand, seine gemeldete Höhe wandere (1368,3 →
> 1367,5 ft), also bewege er sich. **Falsch** — er steht nachweislich völlig starr.
>
> **2. „Dann ist es eine Atem- oder Kopfanimation."** Ebenfalls falsch: *„Es gibt keine Atem-
> oder Kopfanimation. Das wäre ja gut! Aber die gibt es nicht."*
>
> **Die Verlaufsmessung klärt es:** Der Bär springt zwischen **genau zwei** Werten hin und her,
> immer denselben — 1368,3 und 1367,5 ft. Kein Wandern, sondern Quantisierung oder ein Wechsel
> zwischen zwei Geländeauflösungen. Das Auto dagegen fällt monoton:
>
> ```
> Auto  1363,4 → 1357,7 → 1344,2 → 1342,2 → 1342,2 ft     21 ft bergab, dann steht es
> Bär   1368,3 → 1367,5 → 1367,5 → 1368,3 → 1367,5 ft     zwei Werte, hin und her
> ```
>
> **Das Auto rollte einen Hang hinunter und hielt unten.** 21 Fuß in zwei Minuten.
>
> **Die belastbare Lehre:** *Kleine Höhenänderungen in der Rückmeldung beweisen nichts.* Wer
> daraus auf Bewegung schließt, liegt falsch. Für eine Aussage über Bewegung braucht es die
> **Position**, und die meldet die Brügge heute nicht zurück (nur `hoehe_ft`).
>
> ### Für den FriesenKieker
>
> **Ein `fahrzeug` bleibt nicht liegen, wo man es hinstellt — Tiere, Bauwerke und Boote schon.**
>
> ⚠ Hier stand zuerst „Fahrzeuge taugen nicht als Zählstation". Das ist eine **Wertung, kein
> Befund** (vom Nutzer angemerkt: *„naja, wer weiß. Aber man muss das wissen."*). Ein
> rollendes Fahrzeug kann genauso gut erwünscht sein — ein bewegliches Ziel, ein Konvoi, etwas
> zum Hinterherfliegen. Wer ein Event baut, entscheidet das; die Messung liefert nur die
> Eigenschaft.
>
> **Was sie liefert, ist präzise:** 21 ft Höhenverlust in zwei Minuten, dann Stillstand. Wer
> ein Fahrzeug an einem Hang setzt, findet es unten wieder; auf ebenem Grund vermutlich nicht
> — **das ist ungemessen.**
>
> ### Ein Tier in Bewegung setzen — ✅ geht, aber als Notlösung
>
> **Gemessen am 12.09.2026:** Der Server schrieb die Koordinate eines `tier_gross` zwanzigmal
> fort, je 2 m im Sekundentakt. Der Bär legte damit **40 m zurück** — allein über das
> Versetzen aus Fassung 1.1.3, **ohne eine Zeile neuen Code**.
>
> ⚠ **Es sieht aber nicht gut aus:** Das Objekt **blinkt und springt**, weil jedes Versetzen
> in Wahrheit ein Entfernen und Neuerzeugen ist (vom Nutzer gesehen). Für eine Robbe, die sich
> auf der Bank rührt, taugt das nicht.
>
> **Aufheben, nicht verwerfen** (Nutzerentscheidung): *„das geht :-) aber ist nur eine
> Notlösung… vielleicht können wir das mal brauchen. Also merken."* Wo ein Sprung nicht
> stört — ein Schiff, das alle paar Minuten ein Stück weiterfährt, ein Objekt, das
> verschwindet und anderswo auftaucht — reicht es aus und kostet nichts.
>
> ### Der richtige Weg wäre `SetDataOnSimObject`
>
> Dem Objekt eine **Geschwindigkeit** geben, statt es umzusetzen — dann bewegt der Simulator
> es selbst, flüssig und mit der Laufanimation des Modells. Die Brügge kennt die Objekt-IDs
> bereits (sie bekommt sie bei der Erzeugung), es wäre also **ein neuer Import** und sonst
> wenig.
>
> **Ungemessen ist:** ob sich ein Tier über `SetDataOnSimObject` überhaupt steuern lässt, und
> welche Variablen dafür taugen. Der frühere Verdacht, ein neuer Import lasse das Modul nicht
> mehr laden, ist widerlegt — `AIRemoveObject` und `GetLastSentPacketID` kamen beide dazu,
> ohne dass etwas zerbrach.
>
> ### Und was ist mit Beinen und Kopf? — recherchiert am 12.09.2026
>
> **Die Animationen existieren.** Der DevMode bietet beim Spawnen eines SimObjects eine
> **„Play Animation"-Liste** — die Modelle können also laufen, sich umsehen, sich hinlegen.
>
> ⚠ **Über SimConnect gibt es aber keinen dokumentierten Weg dorthin.** Im MSFS-DevSupport
> steht ein offener Feature-Request eines Entwicklers mit genau diesem Problem: Er erzeugt
> `Tarmac_Male_Summer_Caucasian` per `AICreateSimulatedObject_EX1` und bekommt ihn nur im
> Zustand *standing idle*, obwohl er *Driving_Pushback* braucht. **Keine Antwort von Asobo.**
> ([Thread 17717](https://devsupport.flightsimulator.com/t/simconnect-aicreatesimulatedobject-character-animation-state/17717))
>
> **Zwei Hoffnungen bleiben, beide ungemessen:**
>
> 1. **Geschwindigkeit löst die Animation aus.** Bei AI-Fahrzeugen drehen sich die Räder beim
>    Fahren — das `fahrzeug` rollt ja nachweislich. Gibt `SetDataOnSimObject` einem Tier eine
>    Geschwindigkeit, könnte die Laufanimation von selbst anspringen. Das wäre der Glücksfall:
>    **ein** Import, und Bewegung samt Beinen.
> 2. **Ein Animationszustand als Datenvariable.** Nicht dokumentiert, aber der DevMode macht
>    es irgendwie.
>
> **Ein Test kostet nichts und braucht keinen Neustart:** Im DevMode selbst einen `BlackBear`
> spawnen und in die „Play Animation"-Liste sehen. Stehen dort „walk", „idle", „look around",
> lohnt die Richtung; steht dort nur „idle", erübrigt sie sich.

---

## 3. Räumt sie ab, was aus `soll` verschwindet?

Im Admin auf „wegnehmen" klicken. Innerhalb eines Takts (1 s) verschwindet das Objekt aus
`steht` — **aber nicht aus dem Simulator.** Das war in Fassung 1.1.1 so und kein
Fehler: `SimConnect_AIRemoveObject` ist vorerst ausgebaut (s. `objekt_entfernen` in
`bruegge.cpp`), weil beim ersten Lauf nach dem BOM-Fund genau **eine** Sache anders sein
sollte. Die Brügge vergisst das Objekt also nur; weggeräumt wird es beim Schließen der
Verbindung.

**Das ist der Kern des Sollzustands-Gedankens:** Die Brügge befolgt keine Befehle, sondern
gleicht ab. Geht eine Anfrage verloren, holt die nächste den Zustand wieder ein.

### 3b. `AIRemoveObject` — ✅ **bestätigt am 12.09.2026, Fassung 1.1.3 läuft**

> **Das Modul lädt mit dem Import.** Der Verdacht gegen ihn war von Anfang an falsch; es war
> immer nur das BOM im Paket.
>
> Gemessen nach dem Neustart, mit sauberer Ausgangslage (alle Objekte frisch, `seit_s` = 112):
>
> | | Boote | |
> |---|---|---|
> | vorher | 3 | 43 m, 94 m, 2021 m |
> | `ref-boot` aus `soll` genommen | **2** | das 94-m-Boot ist **weg** |
>
> Damit trägt der Sollzustand-Gedanke in **beide** Richtungen. Bis dahin konnte die Brügge
> ihn nur zur Hälfte durchsetzen: hinstellen ja, wegnehmen nein.

> #### ⚠ Der Aufruf ist eine Voraussetzung, keine Annehmlichkeit — gemessen am 12.09.2026
>
> Nachgewiesen mit `kieker_probe.py --boote-zaehlen`, weil das Auge hier nicht ausreicht.
> Ein `boot_klein` an fester Koordinate, in drei Schritten:
>
> | Schritt | Boote im Umkreis | Objekt-IDs |
> |---|---|---|
> | angefordert | 1 | `149372931` |
> | aus `soll` genommen, Brügge vergisst es | **1** | `149372931` — steht weiter |
> | **dieselbe id erneut angefordert** | **2** | `149372931` + `148946946` |
>
> **Jeder Verbindungsabriss verdoppelt die gesetzten Objekte.** Für den FriesenKieker heißt
> das: Ein Pilot mit wackliger Leitung zählt Tiere doppelt und dreifach — und niemand sähe
> dem Ergebnis an, dass es falsch ist. Deshalb ist der Aufruf wieder drin, obwohl er ein
> Import mehr ist.
>
> ⚠ **Warum gezählt und nicht hingeschaut wurde:** Derselbe Vorgang lief zuvor mit einem
> Bären, und der Blick aus dem Cockpit meldete **einen**. Zwei gleiche Modelle an derselben
> Koordinate sind nicht zu unterscheiden — die Sichtprüfung hätte den Befund glatt verneint.
> Das ist dieselbe Lehre wie am 11.09. beim `Boat01`: *Der Simulator weiß es besser als das
> Auge.* Zwei Zahlen aus der Rückmeldung (`seit_s` sprang von 860 auf 186, `hoehe_ft` von
> 1384,9 auf 1379,2) deuteten zwar richtig auf ein Neusetzen hin — **belegt** haben sie die
> Verdopplung aber nicht, denn sie sagen nichts darüber, ob das alte Objekt noch existiert.
>
> **Zu prüfen bleibt nur noch, ob das Modul damit lädt.** Fassung 1.1.3 liegt im
> Community-Ordner (69.041 Bytes).

| Beobachtung | heißt |
|---|---|
| `WASM: Module bruegge.wasm loaded` kommt weiterhin, Objekt verschwindet | ✅ der Import ist da, Ausbau war unnötig — drin lassen |
| Modul lädt nicht mehr | Der Import fehlt im 2024er SDK wirklich → wieder raus, und der Ausweg ist `SetDataOnSimObject` (weit wegsetzen), **selbst wieder ein neuer Import — also einzeln messen** |

⚠ Nicht mit anderen Änderungen zusammenlegen. Ein Modul, das nicht lädt, sagt nicht, woran es
lag — genau das hat den 12.09. gekostet.

---

## 3c. Ein Objekt VERSETZEN — gefunden am 12.09.2026, behoben in 1.1.3

> ### ⚠ Der Server konnte ein Objekt nicht verschieben — und merkte es nicht
>
> Ein Bär wurde unter **derselben `id`** 5 m weiter östlich angefordert. Er rührte sich
> nicht: `seit_s` lief unverändert auf **1725** weiter, statt bei null neu zu beginnen.
>
> **Die Ursache steht in `soll_abgleichen`:** Ist `erzeugt_gerufen` gesetzt, läuft der
> Erzeugungspfad nicht mehr. Die neue Koordinate wurde übernommen und nie verwendet — ein
> bereits erzeugtes Objekt lässt sich nicht nachträglich verschieben.
>
> **Das ist ein stiller Fehler der schlimmsten Sorte:** Die Brügge meldet `zustand: steht`,
> der Server hält das Objekt für umgesetzt, und alles sieht richtig aus. Nur steht es am
> alten Ort. Für den Kieker hieße das eine Station, die dort ist, wo sie letzte Woche war.
>
> **Behoben in 1.1.3:** Ändert der Server Ort, Ausrichtung oder Gattung eines stehenden
> Objekts, wird es entfernt und neu gesetzt. Die Schranke ist bewusst grob (~1 m, 1°) — sie
> soll eine **Absicht** erkennen, kein Rundungsrauschen; sonst flackert das Objekt bei jeder
> Meldung.
>
> ### ✅ Bestätigt am 12.09.2026 — und der Härtetest gleich mit
>
> | Versatz | Ergebnis |
> |---|---|
> | Boot 20 m nach Norden, gleiche `id` | ✅ umgezogen, neue Objekt-ID, **weiterhin 2 Boote** |
> | Kreuzfahrtschiff **2 km** herangeholt | ✅ in EINEM Takt da, **weiterhin 2 Boote** |
>
> Der springende Punkt ist die unveränderte Anzahl: Das alte Objekt wird beim Umzug
> weggeräumt. Ohne `AIRemoveObject` wären es jetzt vier. Beide Änderungen aus 1.1.3 greifen
> also ineinander — das Versetzen funktioniert nur, weil das Wegnehmen funktioniert.

---

## 4. Was passiert bei einer unbekannten Gattung?

> ### ✅ Gemessen am 12.09.2026 — sie meldet, statt zu raten
>
> Eine Gattung `seeungeheuer` am Admin vorbei in `soll` geschrieben:
>
> ```
> messung-4-unbekannt   fehlgeschlagen   GATTUNG_UNBEKANNT
> ```
>
> Kein Modell geraten, kein endloser Wiederholungsversuch im Sekundentakt, und der Server
> weiß, dass diese Anforderung nie erfüllt wird. Ohne den `steht`-Block (v14.30.1) wäre
> dieser Fehlschlag dauerhaft unsichtbar geblieben.

Der Admin lässt nur die fünf bekannten zu — für diesen Test also per curl eine erfinden, oder
im Modul einen Titel verstellen, den MSFS nicht kennt.

**Erwartet:** `steht[].zustand = "fehlgeschlagen"` mit `fehler`, und **kein** erneuter Versuch
im Sekundentakt. Ohne diese Bremse versuchte die Brügge es für immer.

---

## 5. Überlebt ein Objekt einen Flugwechsel?

> ### ✅ Gemessen am 12.09.2026 — **ja, alle vier waren noch da**
>
> Neuer Flug geladen, dieselbe Gegend: Die gesetzten Objekte standen unverändert. **Die
> Brügge muss nach einem Flugwechsel nichts nachholen** — der Simulator behält, was gesetzt
> wurde.
>
> ⚠ **Nicht verwechseln mit dem, was danach geschah:** Die Objekte verschwanden kurz darauf,
> und das sah nach Flackern aus. Ursache war aber das Leeren von `soll` für den Mengentest
> (5b) — die Brügge räumte pflichtgemäß ab. Wer im Simulator misst, während jemand am
> Sollzustand arbeitet, misst den anderen mit.

Objekt setzen, dann im Sim einen anderen Flug laden.

**Erwartet:** Die Brügge räumt beim `FlightLoaded` alles ab und setzt neu, was der Server für
die neue Lage schickt. (Dass die Objekte den Wechsel technisch überleben, ist gemessen — sie
gehören aber zur alten Position des Piloten.)

---

## 5c. EINE Geländehöhe für ein ganzes Feld taugt nicht — ✅ gesehen am 12.09.2026

> Der Mengentest (5b) lieferte den Beleg nebenbei mit. Zwölf Boote in einem Raster von
> 180 × 180 m, **alle auf dieselbe Höhe gesetzt** (1386,4 ft — die Bodenhöhe unter dem
> Flugzeug), **alle melden 1386,4 ft zurück**. Im Bild:
>
> | Boot | |
> |---|---|
> | eines | bis zum Verdeck **im Boden** |
> | eines | steht sauber |
> | eines | **schwebt** über dem Gras |
>
> **Die Wiese ist nicht flach.** Über 200 m ändert sich das Gelände um mehrere Fuß, und die
> Brügge setzt alles auf eine einzige Höhe, weil sie nur die unter dem Flugzeug kennt
> (`gelaendehoehe()` = `PLANE ALTITUDE − PLANE ALT ABOVE GROUND`).
>
> **Im Bild des 30er-Rasters (5d) ist es unübersehbar:** Ein Boot im Vordergrund zeigt nur
> noch Verdeck und Sitzbänke, die hinteren stehen vollständig da, eines wirkt angehoben —
> und alle wurden auf **dieselbe** Höhe gesetzt.
>
> **Drei Befunde dieses Abends greifen hier ineinander:**
>
> 1. Die Geländehöhe gilt nur am Flugzeug — schon 100 m weiter ist sie falsch (5c)
> 2. Die Rückmeldung ist ein Echo und deckt den Fehler nicht auf (Punkt 2, Gegenprobe)
> 3. Der Referenzpunkt des Modells kommt obendrauf (Punkt 2b)
>
> ### ⚠ Das ist die zentrale offene Frage für den FriesenKieker
>
> **Der Server muss die Geländehöhe je Station kennen**, sonst stehen Robben mal im Watt und
> mal in der Luft. `erwartete_hoehe_ft` ist der Weg dorthin und wirkt exakt — **woher die
> Zahl kommt, ist offen.** Drei denkbare Wege, keiner gemessen:
>
> | Weg | Haken |
> |---|---|
> | Höhenmodell auf dem Server (DEM/SRTM) | weicht vom MSFS-Gelände ab — **gemessen: bis 11,6 ft, s. unten** |
> | Die Brügge fragt am Zielort nach und meldet zurück | braucht einen neuen Rückkanal; der Pilot muss hinfliegen |
> | Nur dort setzen, wo der Pilot schon ist | widerspricht „der Server darf einmal verteilen" |
>
> ⚠ **Hier stand, das Problem entschärfe sich am Wattenmeer, weil es dort flach ist. Das war
> frei erfunden** — aus dem Namen „FriesenKieker" und den Robben geschlossen, nicht aus den
> Unterlagen. **Der Kieker spielt überall auf der Welt** (vom Nutzer richtiggestellt,
> 12.09.2026), also auch in Bergen, an Steilküsten und auf Hochebenen. Damit ist die
> Höhenfrage nicht kleiner als gedacht, sondern größer.
>
> ### Ein vierter Weg lag nahe — und trägt NICHT
>
> Die Brügge misst die Geländehöhe bei jeder Meldung mit (`alt_msl_ft − alt_agl_ft`, dieselbe
> Rechnung wie `gelaendehoehe()`), und es lag nahe, daraus eine Geländekarte aufzubauen.
>
> **Das beantwortet die Frage aber nicht** (vom Nutzer eingewandt, 12.09.2026 — der Vorschlag
> stand hier zuvor als Lösung): Es ist die Höhe **unter dem Flugzeug**, also nur dort, wo der
> Pilot schon war. Eine Station wird **voraus** gesetzt, bevor jemand dort war. Genau das ist
> der Kern der ganzen Frage, und der Weg geht daran vorbei.
>
> Als Nebenertrag bleibt er brauchbar: Für ein Revier, das schon einmal beflogen wurde, wäre
> die Höhe bekannt. Heute wird das ohnehin weggeworfen — `bruegge_positions` hat
> `cid INTEGER PRIMARY KEY`, also eine Zeile je Pilot, bei jeder Meldung überschrieben.
>
> ### Und ein Höhenmodell? — ✅ gemessen, taugt so nicht
>
> Vier Punkte, an denen MSFS heute die Geländehöhe gemeldet hat, gegen `open-elevation` (SRTM):
>
> | Koordinate | MSFS | SRTM | Abweichung |
> |---|---|---|---|
> | 47.80173 / 8.97819 | 1383,0 ft | 1374,7 ft | **−8,3 ft** |
> | 47.80157 / 8.97796 | 1378,2 ft | 1374,7 ft | −3,5 ft |
> | 47.80138 / 8.97822 | 1386,3 ft | 1374,7 ft | **−11,6 ft** |
> | 47.80373 / 8.98159 | 1353,2 ft | 1358,3 ft | **+5,1 ft** |
>
> **Eine Spanne von 17 Fuß, mal zu hoch, mal zu tief.** Ein `Boat01` hat rund 5 ft Rumpf — es
> stünde damit mal in der Luft und mal bis zum Verdeck im Boden.
>
> ⚠ **Aufschlussreicher noch ist die dritte Spalte:** SRTM liefert für drei Punkte **denselben**
> Wert (1374,7 ft), weil seine Auflösung rund 30 m beträgt und die Punkte enger beisammen
> liegen. MSFS hat dort 8 ft Unterschied. Ein Höhenmodell dieser Körnung kann die Geländeform,
> auf die es ankommt, gar nicht abbilden.
>
> ### Was bleibt
>
> **Keiner der vier Wege ist belegt.** Was heute schon funktioniert: das Objekt grob setzen und
> **bei Annäherung versetzen** (seit Fassung 1.1.3 möglich, s. 3c) — dann misst die Brügge
> unter sich, wo der Pilot ohnehin ist. Das widerspricht dem Flugtest-Befund („der Server darf
> einmal verteilen") nicht, es ergänzt ihn: **verteilen ja, aber die endgültige Höhe fällt erst
> vor Ort.**
>
> Ungemessen bleibt dabei, **wie genau `alt_agl_ft` aus großer Höhe ist** — unter dem Flugzeug
> ist das Terrain geladen, in Reiseflughöhe aber gröber aufgelöst. Liegt die Messung aus
> 10.000 ft um zwanzig Fuß daneben, muss die Korrektur tief genug geschehen.

---

## 5b. Wie viele Objekte auf einmal? — ✅ gemessen am 12.09.2026

> **Zwölf `boot_klein` in EINEM `soll`-Durchlauf angefordert: 12 gesetzt, 12 gezählt, 0 Fehler.**
>
> Damit ist eine Vermutung widerlegt, die beinahe zu einer Codeänderung geführt hätte: Als
> vier Gattungen gleichzeitig angefordert wurden, scheiterten zwei (`EXCEPTION_22` und
> `KEINE_ANTWORT`), und die Gleichzeitigkeit lag als Erklärung nahe — `soll_abgleichen` ruft
> `AICreateSimulatedObject` für alle Objekte in einem Durchlauf. **Die Menge ist es nicht.**
> Zwölf auf einen Schlag gehen glatt durch.
>
> **Und das Abräumen skaliert ebenso:** `soll` komplett geleert → alle sieben stehenden
> Objekte weg, keines blieb zurück.
>
> ⚠ **Offen bleibt damit, woran der Krankenwagen scheitert** (`fahrzeug` →
> `ASO_Ambulance_Japan`, `EXCEPTION_22` auch einzeln). Vier der fünf Gattungen laufen; die
> Titelsuche der Probe taugt als Beleg nicht, weil `BlackBear` und `Windmill` dort ebenfalls
> fehlen und beide nachweislich funktionieren.

---

## 5d. Dreißig Objekte — ✅ gemessen am 12.09.2026, mit einem Fund

> **Die Mechanik hält:** 30 Objekte angefordert → 30 gesetzt, 30 gezählt, 0 Fehler. Dann alle
> 30 **gleichzeitig** um 25 m versetzt → 30 vorher, 30 nachher. Kein Verlust, kein
> Doppelgänger, obwohl dabei 30 × `AIRemoveObject` + 30 × `AICreateSimulatedObject` in einen
> Frame fallen.
>
> ### ⚠ Der Fund steckte aber woanders: die Antwort passte fast nicht mehr in den Puffer
>
> | | |
> |---|---|
> | Antwortgröße bei 30 Objekten | **3776 Bytes** |
> | Puffer in `anfrage_fertig` (bis 1.1.3) | 4096 Bytes → **92 % belegt** |
> | je Eintrag | 126 Bytes |
> | bei `SOLL_MAX` = 32 | rund 4030 + Rahmen → **Überlauf** |
>
> Die Brügge konnte also **mehr anfordern, als sie lesen kann** — und das Abschneiden war
> vollkommen lautlos: Das JSON bricht mitten im Satz ab, `json_array` findet die vorderen
> Einträge, der Rest fehlt. Von außen sieht das aus wie Objekte, die der Simulator nicht
> setzen wollte. Mit `erwartete_hoehe_ft` je Eintrag (was der Höhenfrage nach nötig wäre, s.
> 5c) wäre die Grenze schon bei rund 25 Objekten erreicht.
>
> **Behoben in Fassung 1.1.4**, in zwei Schritten:
>
> 1. `ANTWORT_PUFFER` = 16384 — trägt einen vollen Sollzustand rund viermal.
> 2. **Passt eine Antwort trotzdem nicht, wird sie gar nicht ausgewertet** und die Brügge
>    behält ihren letzten Stand. Ein halb gelesener Sollzustand wäre schlimmer als ein
>    unveränderter: Er räumte alles ab, was hinter der Schnittstelle stand, und setzte es
>    beim nächsten Takt neu — ein Flackern, dessen Ursache niemand fände.
> 3. Sie meldet es als `antwort_zu_gross` mit der tatsächlichen Größe, der Server schreibt
>    eine Warnung ins Log. Aus einem stillen Fehler wird ein lauter.
>
> ### ✅ Und die Leistung? — **89,4 FPS mit dreißig Objekten**
>
> Aus dem DevMode-Overlay, während dreißig Objekte gleichzeitig um 60 m versetzt wurden
> (MSFS 2024, Mi-2 am Boden):
>
> | | |
> |---|---|
> | Bildrate | **89,4 FPS** |
> | MainThread | 23,6 ms |
> | RdrThread | 20,5 ms |
> | Terrain-/Objects-/Buildings-LOD | je 1.00 |
>
> **Kein spürbarer Einbruch, kein Ruckler** (vom Nutzer bestätigt: „habe nichts gesehen").
> Damit bleibt die Brügge so einfach, wie sie ist: **kein Verteilen über mehrere Takte, keine
> Warteschlange.** Der Server darf ein ganzes Revier auf einmal umsetzen.
>
> Das passt zum Bild: Der Simulator setzt AI-Objekte ohnehin laufend (Verkehr, Schiffe);
> dreißig mehr fallen nicht ins Gewicht.
>
> ⚠ **Eine Zeile im Overlay ist ungedeutet:** `MarkersFailed: 20` bei `MarkersWait: 0`. Ob
> das mit den gesetzten Objekten zusammenhängt oder aus einer ganz anderen Ecke kommt, ist
> **nicht** geklärt — hier steht es als Beobachtung, nicht als Befund.

---

## 6. Was tut sie bei Netzausfall?

> ### ✅ Nebenbei beantwortet am 12.09.2026 — **und schneller als erwartet**
>
> Der Pilot trennte vPilot und flog weiter. Ergebnis nach rund 2 km: **kein einziges der 30
> Boote mehr da** (mit `--boote-zaehlen` über 20 km Umkreis geprüft, also kein Ausblenden
> durch Entfernung).
>
> **Abgeräumt wurde sofort, nicht nach 300 s.** Denn ohne Zuordnung schickt der Server
> `soll: []` — die Brügge räumt also nicht wegen Zeitablaufs ab, sondern weil der Sollzustand
> leer ist. Das ist der Gedanke in Reinform: *Niemand ist zuständig, also steht nichts.*
>
> **Die 300-Sekunden-Frist bleibt trotzdem nötig** — sie greift in einem anderen Fall: wenn
> gar keine Antwort mehr kommt (Netz weg, Server tot). Der ist damit weiterhin ungemessen.
>
> ⚠ **Fallstrick bei der Messung, für den nächsten:** `bruegge_steht` wird nur bei
> bestehender Zuordnung geschrieben. Ohne VATSIM bleibt die letzte Rückmeldung als
> Karteileiche stehen, und eine Abfrage der Tabelle meldet fröhlich „30 stehen", während im
> Simulator nichts mehr steht. Die Admin-Ansicht filtert das (60 s Höchstalter), rohes SQL
> nicht. **Der Zähler ist die Wahrheit, nicht die Datenbank.**

Für den ungemessenen Fall: WLAN aus, oder den Container kurz anhalten.

**Erwartet:** Nach `gilt_bis_s` (300 s) räumt die Brügge alles ab. Ohne das bliebe stehen, was
der Server längst zurückgenommen hat — für eine Baake hieße das eine Station, die nie
verschwindet.

⚠ Das dauert fünf Minuten. Lohnt sich nur, wenn ohnehin Zeit ist.

---

## 7. Die Drossel

Im Admin den Schieber auf 15 s, dann auf „ganz aus".

**Erwartet:** Der Takt im nginx-Log folgt sofort, ohne Deploy. „Aus" ist 900 s, nicht 0 — eine
Brügge ohne Antwort könnte Abschaltung nicht von Netzausfall unterscheiden.

```
grep 'bruegge/melden' /var/log/nginx/access.log | tail -5 | awk '{print $4}'
```

---

## 8. ROBBEN — ✅ **ein Community-SimObject lässt sich setzen** (12.09.2026)

> ### ✅ Prüfpunkt 1 ist beantwortet — und zwar mit einer Robbe im Bild
>
> Die parallele Sitzung hat `ahqa seal moving` am selben Abend mit `probe-msfs/titel_schau.py`
> gesetzt: **gezeichnet, im Screenshot belegt**, neben einer Kuh als Größenvergleich, flach am
> Boden liegend. Damit ist die Frage beantwortet, von der alles Weitere abhing —
> `AICreateSimulatedObject` findet auch einen Titel aus dem **Community-Ordner**, nicht nur aus
> Asobos Bordbestand.
>
> **Ein eigenes Robben-Paket ist damit gangbar.** Es scheitert nicht mehr am Verfahren,
> sondern nur noch an Modell und Rechten.
>
> ⚠ **Was das NICHT belegt:** Gesetzt hat es ein externer SimConnect-Client, nicht die Brügge.
> Der Weg Server → Brügge → `robbe` (WASM, `g_gattungen`) ist weiterhin ungemessen — in
> `bruegge_steht` stand an diesem Abend keine einzige `robbe`-Zeile. Es ist derselbe Aufruf und
> bei allen fünf bisherigen Gattungen war er deckungsgleich, aber „derselbe Aufruf" ist ein
> Argument, kein Befund.
>
> **Und ein zweiter Fund, der Prüfpunkt 2 verschärft:** Alle dreißig Tiere dieser Bibliothek
> heißen `walking`, `running` oder `moving` — **die Animation steckt im Modell**. Das erledigt
> die Frage, wie man Beine und Kopf bewegt (gar nicht über SimConnect, sondern über die Wahl
> des Modells), macht aber die Gegenfrage dringlicher: Eine Robbe, die „moving" heißt, könnte
> genau das tun.

**Die wichtigste offene Frage der ganzen Liste — beantwortet.** Von ihr hing nicht nur diese
Gattung ab, sondern jedes künftige eigene Modellpaket: Alle zuvor belegten Titel (`BlackBear`,
`Boat01`, `Windmill`) stammen aus **Asobos Bordbestand**.

Und für den FriesenKieker ist es die Existenzfrage: **Weder MSFS 2020 noch 2024 bringt eine
Robbe mit** (s. [`OBJEKTE.md`](OBJEKTE.md)). Was gezählt werden soll, muss von außen kommen.

### Was schon dasteht

`human-library-animated` (Superspud, Freeware) liegt im Community-Ordner und ist **in MSFS
2024 verlinkt** (in 2020 nicht). Es enthält 32 Tier-**SimObjects**, darunter:

| Titel | Modell | Größe |
|---|---|---|
| `ahqa seal moving` | Seehund, 0,74 × 1,53 × 0,31 m | 186 KB glTF + 131 KB DDS |
| `ahqa sea lion moving` | Seelöwe | 380 KB |
| `ahqa walrus moving` | Walross | 224 KB |

Ausgelesen aus `E:\Addons\Community\human-library-animated\SimObjects\Animals\*\sim.cfg`
(`category=Animal`). **Dasselbe Paket benutzt `counting seals` schon** — aber als Szenerie,
über GUIDs aus `Hummods.BGL`. Seine SimObject-Seite hat nie jemand angefasst.

Gattung `robbe` ist seit Fassung 1.4.0 eingetragen, **ohne Rückfall auf den Bordbestand**:
Fiele sie still auf `BlackBear` zurück, lieferte der Kieker eine Zahl, während am Strand Bären
liegen. Eine fehlende Robbe muss als `EXCEPTION_22` sichtbar werden.

### Vier Prüfpunkte, in einem Zug

Über den Admin drei `robbe` an einen Inselstrand setzen, **mit `auf_boden: 1` und ohne
Höhenangabe** (Koordinaten aus `counting seals/seal_colonies.json`, z. B. Norderney Oststrand
53,7235 / 7,2502), dann:

1. **Kommt sie auch über die Brügge?** Der Titel ist belegt (Kasten oben), der Weg noch nicht:
   `zustand: steht` in der Rückmeldung heißt ja, `fehler: EXCEPTION_22` hieße, dass das
   WASM-Modul den Titel anders auflöst als ein externer Client. Das ist jetzt eine
   Bestätigungsmessung, keine Existenzfrage mehr.
2. **Bleibt sie liegen, wo sie liegt?** ⚠ **Jetzt der wichtigste Punkt.** Das Modell heißt
   `ahqa seal moving` und trägt zwei Animationen (`Default_State`, `sealmove`); auslösen lässt
   sich davon nichts (über SimConnect nicht dokumentiert, Punkt 2d). Die Frage ist die
   umgekehrte: ob sie von selbst losrobbt. Punkt 2d hat gezeigt, dass Tiere und Fahrzeuge das
   tun, und die parallele Sitzung hat **21 ft Höhenverlust in zwei Minuten** an den
   `ASO_*`-Fahrzeugen gemessen — die rollen einen Hang hinunter. Eine Robbenkolonie, die über
   den Deich wandert, wäre für einen Zähl-Event das Ende. **Also: hinsetzen, zwei Minuten
   stehen lassen, wieder hinsehen** — nicht nur einmal zählen.
3. **Setzt `auf_boden: 1` sie sauber in den Sand?** Die Bounding-Box beginnt bei z =
   **−0,003 m**, der Referenzpunkt liegt also praktisch am Boden — anders als bei `boot_klein`
   (Wasserlinie, rund anderthalb Meter im Boden, Punkt 2b). Erwartung: passt ohne Zuschlag.
   Geprüft wird mit dem Auge, nicht mit `hoehe_ft` — genau das ist die Lehre aus 2b.
   Sollte MSFS 2020 das Flag ignorieren, greift der aufgehobene Sondenweg aus 2c.
4. **Trägt eine Kolonie?** 30 Robben auf 60 m Radius, gegen Punkt 5d gemessen (dort waren 30
   Objekte fehlerfrei, bei 89,4 FPS). Eine echte Kolonie hat 12–40 Tiere (s.
   `counting seals/README.md`), das ist also schon die Zählgröße und nicht der Härtetest.

### Was danach zu entscheiden ist (nicht hier)

Das Ziel ist ein **eigenes Paket**, ausgeliefert mit der Brügge — nicht eine 556-MB-Abhängigkeit
auf Superspuds Sammlung. Denn per SimConnect erzeugte Objekte sind **lokal**: Wer das Modell
nicht hat, sieht nichts und kann nicht mitzählen. Das eine schließt das andere nicht aus — in
der Titelliste stehen beide, Superspuds Robbe zuerst, das eigene Modell dahinter. Offen bleiben
zwei Dinge:

- **Das Modell.** Superspud um Weitergabe der drei Meerestiere bitten (~320 KB je Tier,
  Freeware) oder ein eigenes bauen (Blender + Asobo-glTF-Exporter). Für ein eigenes spricht
  mehr als die Rechtelage: Bei einem fremden Modell ist die `sim.cfg` gegeben, bei einem
  eigenen schreiben wir sie selbst — und damit auch, was das Tier von sich aus tut
  (`DistanceToNotAnimate`, `max_speed_mph` im `[DesignSpecs]`-Block, s. Prüfpunkt 2).
- **Die Verpackung.** Vorbild ist `human-library-animated` selbst: `content_type: SCENERY` mit
  einem **minimalen** Manifest — ohne `export_type`, ohne `builder`, ohne
  `minimum_compatibility_version`, also genau die Felder, die das WASM-Paket der Brügge
  zwingend braucht (s. `msfs/paket.ps1`). Ob ein `MISC`-Paket *auch* `SimObjects/` indexiert,
  ist ungemessen — deshalb eher zwei Ordner in einem Download als ein Ordner mit beidem.

---

## ✅ X-Plane 12 — am 13.09.2026 am Stück abgearbeitet

**Die zweite Brügge (`xplane/bruegge.cpp`, Fassung 1.0.0) ist geflogen.** Alles in einer
Sitzung, ohne einen einzigen Simulator-Neustart zwischendurch — genau so, wie diese Liste es
seit dem 11.09. vorschreibt.

| Punkt | Ergebnis |
|---|---|
| Plugin lädt | ✅ `Loaded: …/FriesenBruegge.xpl (de.friesenflieger.bruegge)` |
| Datarefs | ✅ gefunden (sonst stünde die FEHLT-Zeile im Log) |
| Kennung | ✅ geschrieben **und nach einem Neustart wiedergelesen** (`fb0225a72bb734be`) |
| Netz (eigener Thread, WinHTTP, TLS) | ✅ Meldungen kommen an, HTTP 200 statt 422 — das JSON ist also gültig |
| Objekt setzen | ✅ sechs Gattungen gleichzeitig, **alle im Bild gesehen** |
| Terrain-Probe am Zielort | ✅ jedes Objekt auf seiner eigenen Höhe, alle `hoehe_gemessen: true` |
| Abräumen | ✅ fünf aus `soll` genommen → beim nächsten Takt fort |
| Umsetzen | ✅ Hirsch von 5 m auf 60 m, meldete danach 1402,3 ft statt 1403,7 |
| Positionsmeldung im Flug | ✅ Sekundentakt mit Höhe, Kurs, AGL, Steigrate |

### Der Befund, der X-Plane von MSFS trennt

Eine Reihe nach Osten, aus dem Stand auf einem Rollweg gesetzt (47,80461 / 12,99683):

| Objekt | Abstand | Höhe |
|---|---|---|
| Hirsch | 5 m | 1403,7 ft |
| Möwe | 8 m | 1403,7 ft |
| Segelboot | 16 m | 1403,4 ft |
| Boje | 24 m | 1403,3 ft |
| Ballon | 45 m | 1402,7 ft |
| Ölplattform | 120 m | **1400,5 ft** |

Das Gelände fällt nach Osten um gut drei Fuß, und **jedes Objekt sitzt auf seiner eigenen
Höhe**. Der ganze Sondenumweg aus Punkt 2c entfällt hier: `XPLMProbeTerrainXYZ` fragt das
Gelände an einer beliebigen Koordinate, ohne dass etwas gesetzt werden müsste.

### Drei Funde, die man leicht falsch liest

1. **`seit_s` läuft beim Umsetzen WEITER** (74 s), statt bei null neu zu beginnen. In X-Plane
   wird dieselbe Instanz verschoben, in MSFS muss sie weg und neu hin (Punkt 3c). Wer `seit_s`
   als „seit wann steht es dort" auswertet, liegt in X-Plane falsch.
2. **`alt_agl_ft` meldet 0,0, während das Flugzeug 4 ft über dem Boden steht.** X-Planes
   `elevation` misst den Referenzpunkt des Musters (Cirrus SR22: rund 1,2 m über Grund),
   `y_agl` dagegen das Fahrwerk. Wer daraus die Geländehöhe rechnet — der MSFS-Weg —, liegt um
   die Fahrwerkshöhe daneben.
3. **`hoehe_ft` ist nicht immer eine Messung.** Außerhalb des geladenen Geländes trifft die
   Probe nicht, das Objekt bekommt Meereshöhe, und das sieht aus wie ein Wattobjekt auf 0,0 ft.
   Dafür gibt es `hoehe_gemessen` (PROTOKOLL.md, Abschnitt 1).

### ⚠ Ohne VATSIM war nichts davon zu messen — bis auf den Prüfserver

Der Server liefert `soll` nur an einen zugeordneten Piloten. Das kostete an diesem Abend eine
Stunde: Die Brügge lief nachweislich, meldete sauber, bekam immer ein leeres `soll` — weil
xPilot seinen eigenen Simulator nicht fand (`UseTcpSocket: false` im Plugin gegen einen
Client, der TCP erwartete).

**[`pruefserver.py`](pruefserver.py) löst das dauerhaft**, für jede Brügge: Er spielt den
Server, zeigt die Meldung im Klartext und antwortet mit einem Sollzustand, den man im
laufenden Betrieb ändert.

```powershell
py pruefserver.py                                   # lauscht auf 127.0.0.1:8099
py pruefserver.py --setzen tier_gross --neben 5     # 5 m oestlich von dir
py pruefserver.py --leeren
```

Umgebogen wird die Brügge über eine Datei mit einer Zeile —
`<X-Plane 12>\Output\preferences\friesenbruegge.url`, Inhalt
`http://127.0.0.1:8099/api/bruegge/melden`. Liegt sie nicht da, ist das Ziel fest
einkompiliert. **Sie muss nach dem Messen wieder weg**, sonst meldet die Brügge an niemanden;
das Log sagt bei jedem Start, welches Ziel gilt.

### Was in X-Plane noch offen ist

- **Ab welcher Entfernung ist ein Objekt sichtbar?** Für MSFS gemessen (Boot 1 km,
  Kreuzfahrtschiff 22 km), für X-Plane unbekannt. Davon hängt ab, wie fein Stationen im
  FriesenKieker gesetzt werden dürfen.
- **Das Nachrücken bei ungeladenem Gelände** (`hoehe_gemessen` von `false` auf `true`) — im
  Code vorgesehen, noch nie im Flug gesehen. Beides zusammen in einem Zug messbar: etwas
  Großes weit voraus setzen und hinsehen.
- **1146 Katalogzeilen** sind ungeprüft, und dabei gilt „gelistet ≠ ladbar" (s. OBJEKTE.md).
- **Offene Entscheidung: Muss jede Gattung in der Brügge stehen?** Heute ja — und das kostet
  bei jeder neuen Gattung ein Plugin-Update bei allen Piloten. Am 13.09.2026 zweimal
  aufgelaufen: FRS61s ältere Brügge kannte `robbe` und `tier_wild` nicht und meldete
  `GATTUNG_UNBEKANNT`. Denkbar wäre, dass der Server Titel als *Vorschlag* mitschickt, die
  eine Brügge nur nutzt, wenn sie die Gattung selbst nicht kennt — das brächte aber
  Simulatorwissen in den Server, das dort bewusst nicht liegt (PROTOKOLL.md, Abschnitt 3).
  **Nicht entschieden.**
- **Ein Scheitern merkt sich die Brügge pro `id`** (13.09.2026 zweimal reproduziert): Wird
  dieselbe `id` mit einer anderen Gattung neu gesetzt, meldet sie weiter
  `GATTUNG_UNBEKANNT`. Erst eine neue `id` wird neu bewertet. Ob das Absicht ist oder ein
  Fund, ist ungeklärt.

---

## Was NICHT mehr zu messen ist

Am 11.09.2026 bereits im Flug bestätigt:

- Positionsmeldung über HTTPS aus WASM ✅
- Zuordnung allein über die Position, ohne Anmeldung ✅
- Steigflug (1900 ft, 1044 ft Höhendifferenz gehalten) ✅
- Abfangen (nachlaufende Höhenschranke) ✅
- Absturz und Respawn (Selbstheilung) ✅
- VATSIM-Trennung und Wiederverbindung ✅
- Sprungerkennung beim Laden (0/90, Seattle) ✅

Am 13./14.09.2026 am eigenen MSFS-Rauch bestätigt:

- Eigener Partikeleffekt ohne DevMode-Klickeditor, aus lesbarem XML gebaut ✅
- Sechs Farben in beiden Simulatoren, kein Fremdpaket mehr nötig ✅
- **`TimeEmission` begrenzt nur den Nachlauf, nicht die Standzeit** ✅ — solange das
  Trägerobjekt lebt, startet MSFS den Emitter selbst neu; erst nach dem Abräumen läuft er
  aus. Die zwischenzeitlich in 1.7.0 eingebaute Erneuerung durch die Brügge war deshalb
  überflüssig und wurde wieder entfernt.
- **`GetSimVar` mit `AMBIENT WIND VELOCITY` liefert einem statischen Objekt nichts** ❌ —
  gegengeprüft bei 27 kt: Die Fahne blieb so lang wie ohne jede Windkürzung. Der gangbare
  Weg ist `GetParticleAttribute → Position`, also die tatsächlich zurückgelegte Strecke
  messen statt den Wind zu schätzen.

---

## Danach

Ergebnisse in [`probe-msfs/ERGEBNIS.md`](probe-msfs/ERGEBNIS.md), offene Punkte in
[`../docs/offene-aufgaben.md`](../docs/offene-aufgaben.md). Was sich am Vertrag ändert, gehört
in [`PROTOKOLL.md`](PROTOKOLL.md) — **und dann in alle drei Umsetzungen.**
