# Flugplatz- und Rollkarten von Hand passen

Arbeitsanweisung für die 43 Karten, die noch keine Passung haben. Stand 01.09.2026.

**Der Auftrag lautet nicht „so gut wie möglich", sondern „nachweisbar richtig".** Eine falsch
gepasste Karte ist schlimmer als gar keine: Sie sieht plausibel aus und liegt im Cockpit
daneben. Was hier zählt, ist die Gegenprobe — nicht der Eindruck, dass es passt.

---

## Warum das Augenmaß allein nicht reicht

Beim Passen klickt man zwei Bahnschwellen an. Der häufigste Fehler ist, statt der Schwelle
das **Ende der grauen Fläche** zu treffen: Stopways und Blast Pads sind in derselben
Grauabstufung gezeichnet wie die Bahn. Genau daran ist die alte automatische Bahnvermessung
gescheitert — bei EDDV maß sie 2784 m für eine 2340-m-Bahn. Der Fehler verschiebt und
skaliert das ganze Blatt, und **nichts an der Passung selbst verrät ihn.**

Die naheliegende Gegenprobe funktioniert nicht: Pixelabstand mal Maßstab mit der Bahnlänge
zu vergleichen besteht **immer** mit 0,00 Prozent, auch bei einem absichtlich um 71 px
danebengesetzten Klick. Grund ist ein Zirkelschluss — `handpassung` leitet den Maßstab aus
denselben zwei Punkten ab. Die Rechnung prüft sich selbst.

**Unabhängig ist nur die gedruckte Maßstabsleiste.** Sie steht auf jedem DFS-Blatt und weiß
nichts von den Schwellen.

---

## Ablauf je Karte

### 1. Blatt mit Raster ansehen

```bash
python scripts/blatt_raster.py EDVM rollkarte 200      # Raster alle 200 px
```

Legt ein beschriftetes Pixelraster über `/opt/friesenspy/data/aip_dfs/<ICAO>.<sorte>.roh.png`
und schreibt es nach `/tmp/<ICAO>.<sorte>.raster.png`. Die abgelesenen Zahlen sind
**Originalpixel**, auch wenn die Ansicht verkleinert ist — darauf kommt es an.

Bei engen Stellen ein feineres Raster nehmen (`50`) oder einen Ausschnitt vergrößern.

### 2. Vier Punkte ablesen

| Punkt | Was genau |
|---|---|
| Schwelle 1 | Der **Beginn der befestigten Bahn**, nicht das Ende des Stopways. Erkennbar an den Schwellenmarkierungen (Zebrastreifen) und der Bahnbezeichnung. |
| Schwelle 2 | Dasselbe am anderen Ende. |
| Leiste A / B | Zwei beschriftete Marken der Maßstabsleiste, **so weit auseinander wie möglich**. |

**Die längste Leiste nehmen, die das Blatt hergibt.** Die Prüfschärfe hängt fast ganz an
ihr: Bei 295 px Leistenlänge liegt die Schranke bei 3,1 Prozent, bei 1180 px bei 0,9 — und
erst dann wird ein 60-m-Stopway gefangen.

### 3. Gegenprobe rechnen — **vor** dem Speichern

```bash
python scripts/passung_pruefen.py EDVM rollkarte \
    --schwellen 120,300 640,880 \
    --leiste 100,1150 400,1150 --leiste-m 500
```

Ausgabe nennt beide Maßstäbe, die Abweichung und die abgeleitete Schranke.

* **BESTANDEN** → weiter zu Schritt 4.
* **DURCHGEFALLEN** → **nicht speichern.** Erst nachsehen, was los ist (s. unten).
* **UNGEPRÜFT** → keine Leiste gemessen. Ebenfalls nicht speichern.

Rückgabewert: `0` bestanden, `1` durchgefallen, `2` Karte nicht prüfbar.

### 4. Speichern

```bash
curl -s -X POST "http://127.0.0.1:8091/api/admin/aip-charts-dfs/EDVM/rollkarte" \
  -H "Content-Type: application/json" -b "fs_admin=$TOKEN" \
  -d '{"p1_x":120,"p1_y":300,"p1_lat":52.4611,"p1_lon":9.6836,
       "p2_x":640,"p2_y":880,"p2_lat":52.4525,"p2_lon":9.6981}'
```

Die Koordinaten sind die **Schwellenwerte aus OurAirports**, nicht selbst geschätzte. Sie
stehen in der Ausgabe von Schritt 3 (`p1 ->` / `p2 ->`) oder über
`/api/admin/aip-charts-dfs/<ICAO>/schwellen`.

Der Status wird dabei `gepasst`. **Das ist bewusst nicht `auto`:** Eine geprüfte Passung
unterscheidet sich von einer gerechneten.

### 5. Danach ansehen

Karte im Admin öffnen und das genordete Blatt über der echten Karte prüfen. Die Gegenprobe
fängt Maßstabsfehler — sie fängt **nicht**, wenn die Bahn selbst verwechselt wurde (bei
mehreren Bahnen) oder die Schwellen vertauscht sind. Das Blatt läge dann um 180 Grad
verdreht, und das sieht man sofort.

---

## Wenn die Gegenprobe durchfällt

Drei Ursachen, in dieser Reihenfolge prüfen:

1. **Stopway mitgeklickt.** Der wahrscheinlichste Fall. Nochmal ansehen: Wo beginnt die
   Zebra-Markierung?
2. **Verlegte Schwelle** (displaced threshold). Dann stimmt die OurAirports-Länge nicht mit
   der gezeichneten Bahn überein, und der Klick war trotzdem richtig. Erkennbar an den
   Pfeilmarkierungen vor der Schwelle. **Diesen Fall aufschreiben und liegen lassen** — er
   gehört einem Menschen vorgelegt, nicht weggedrückt.
3. **Falsche Bahn erwischt** bei mehreren Bahnen. `--bahn 07/25` gibt sie ausdrücklich an.

---

## Vor dem Klicken: die OurAirports-Koordinaten selbst prüfen

**Gefund am 01.09.2026, bevor die 43 Karten bearbeitet wurden.** Die Gegenprobe gegen die
Maßstabsleiste prüft nur, ob der Klick zu den ANGEGEBENEN Koordinaten passt — nicht, ob
diese Koordinaten selbst richtig sind. Bei 12 der 43 offenen Plätze weicht der geodätische
Abstand zwischen `le_latitude_deg`/`le_longitude_deg` und den `he_*`-Werten um 5 bis 66
Prozent von der `length_ft`-Angabe **derselben Zeile** ab — ein interner Widerspruch, der
nur eine falsche Geokodierung bedeuten kann. Dort wäre selbst ein pixelgenauer Klick an
einer falschen Stelle auf der echten Karte verankert, und die Gegenprobe würde das NICHT
bemerken.

**Deshalb vor jedem Passen prüfen:**

```python
from app import runway_ref
import math
for b in runway_ref.bahnen(icao, "/opt/friesenspy/data/runways.csv"):
    geo = math.hypot(*runway_ref.meter(b.le, b.he))
    print(b.name, "gerechnet", round(geo), "m vs. Tabelle", round(b.laenge), "m")
```

`b.laenge` in `runway_ref.Bahn` ist bereits die geodätische Länge aus den Koordinaten —
Abweichung > 5 % von der auf dem Blatt gedruckten Bahnlänge heißt: **diese Koordinaten
nicht als Anker benutzen.**

**Der Vorfilter ist ein Hinweis, kein Ausschlusskriterium.** EDLO zeigt, warum: Seine
Koordinaten sind intern selbstkonsistent (Geo-Abstand 595 m passt zur eigenen
`length_ft`-Angabe 594 m) — und trotzdem falsch, denn das DFS-Blatt selbst druckt für
dieselbe Bahn 04/22 „800 x 20 m ASPH". Der Vorfilter hätte das nicht gefunden. Gefunden hat
es die **Leisten-Gegenprobe**: Ein Klick auf die tatsächlichen, sichtbaren Schwellen ergab
2,04 m/px, die Leiste 2,70 m/px — 24 % Abweichung, durchgefallen. Die Gegenprobe ist damit
der eigentliche Schutz, nicht der Vorfilter davor.

**Deshalb: Jeder Platz wird geklickt und gegen die Leiste geprüft — der Vorfilter blockiert
nichts, er warnt nur vorab.** Plätze mit auffälligem Vorfilter (Stand 01.09.2026): EDAK,
EDAZ, EDBH, EDLA, EDLF, EDLO, EDPH, EDQA, EDQC, EDSN, EDTF, EDWH. EDKB hat gar keine
Koordinaten und bleibt der einzige echte Sonderfall (Gradnetz ablesen, keine Gegenprobe
möglich).

**Gerettet über eine zweite Bahn auf demselben Blatt:** EDBR (`17/35` 25 % verdächtig →
`17R/35L` 0,1 % sauber), EDMA (`07/25` 20 % verdächtig → `07R/25L` 0,1 % sauber), EDTB
(`03/21` 5,0 % grenzwertig → `03L/21R` 1,8 % sauber). Wenn das Blatt beide Bahnen zeigt,
zählt für die Georeferenz nur, DASS zwei Schwellen sicher zuzuordnen sind — nicht, welche
Bahn davon die längste ist.

## Wenn OurAirports nicht zum Blatt passt: das ARP-Verfahren

Zwölf der offenen Blätter lagen daran fest, dass die OurAirports-Schwellen nicht zum Blatt
passen — mal länger (EDRB: 3056 m stillgelegte Vollbahn gegen 1230 m genutzten Abschnitt),
mal kürzer (EDWH: 536 gegen 778 m). Die Schwellenkoordinaten sind dort unbrauchbar. **Alles
andere auf dem Blatt ist es nicht:**

| Was | Woher | Genauigkeit |
|---|---|---|
| Lage | ARP-Symbol auf der Karte + ARP-Koordinate im Blattkopf | rund 20 m |
| Maßstab | gedruckte Maßstabsleiste | 0,1–0,6 % |
| Drehung | gezeichnete Bahnrichtung gegen den **Kurs** aus OurAirports | unter 0,7° |

**Der Kurs bleibt richtig, auch wenn die Länge falsch ist** — ein veralteter Eintrag
beschreibt dieselbe Achse. Gemessen am 01.09.2026 liegt er für 19 der 23 offenen Plätze
unter 0,7° genau; nur EDPH (±9,5°), EDQA (±41°) und EDQC (±7,4°) sind zu grob gerundet, und
EDKB hat gar keine Daten. Gegenprobe der Peilung, wo das Blatt sie druckt: `062 MAG` plus
`VAR 3° E` ergibt 065 — genau den OurAirports-Kurs (EDSI).

```python
from scripts.passung_pruefen import aus_arp, blattdrehung, probe_bahnlaenge
dreh = blattdrehung(bahn_ende_a, bahn_ende_b, kurs_aus_ourairports)
probe_bahnlaenge(bahn_ende_a, bahn_ende_b, mps_aus_leiste, gedruckte_laenge)   # muss bestehen
p1, g1, p2, g2 = aus_arp(arp_pixel, arp_aus_dem_blattkopf, mps_aus_leiste, dreh)
```

**Die Gegenprobe ist hier eine andere.** Die Leiste steckt schon im Maßstab, kann also nicht
mehr prüfen. An ihre Stelle tritt die **gezeichnete Bahnlänge gegen die auf dem Blatt
gedruckte** — zwei Angaben desselben Blatts, die nichts voneinander wissen. Bei EDSI: 859,5
gegen 860 m, also 0,06 %. Die Schranke steht bei drei Prozent, weil die gedruckte Länge
gerundet ist (EDBM nennt 1000 m für 1001,6).

**Voraussetzung ist das ARP-Symbol auf der Karte.** Ohne das gibt es keinen Lage-Anker, und
das Verfahren greift nicht — EDWH ist so ein Fall: Maßstab und Drehung ließen sich sauber
bestimmen (gezeichnet 782 m gegen gedruckte 778 m), aber das Blatt zeichnet kein ⊕.

**Nicht annehmen, der ARP läge auf der Bahnmitte.** Bei EDBM tut er das (auf ein Pixel), bei
EDSI liegt er 131 m daneben. Wer die Annahme braucht, hat keinen Anker.

## Der bessere Weg, wenn das Blatt ein Gradnetz hat

Alles oben Beschriebene holt die Koordinaten aus OurAirports. Genau daran liegen dreizehn
der offenen Blätter fest — die Daten stimmen dort nicht (EDRB: 3056 m stillgelegte Vollbahn
statt 1230 m genutztem Abschnitt; für EDDN liegt airportsdata um 775 m daneben).

**Ein Blatt mit gedrucktem Gradnetz braucht davon nichts.** Die Linien tragen ihre
Koordinaten selbst; zwei Schnittpunkte genügen für die Passung. So sind am 01.09.2026
EDDH, EDDS, EDDN und EDLP gepasst worden, mit 0,08 bis 0,61 Prozent Abweichung gegen die
gedruckte Maßstabsleiste — besser als jede Schwellenpassung dieser Runde.

```bash
python scripts/gradnetz.py EDDS rollkarte --bild /tmp/netz.png
```

Danach `/tmp/netz.png` ansehen, die nummerierten Linien den gedruckten Beschriftungen
zuordnen, zwei weit auseinanderliegende Schnittpunkte mit `punkt()` rechnen und wie gewohnt
gegen die Leiste prüfen.

**Nur vier der 27 offenen Blätter haben überhaupt eines.** Die kleinen Platzblätter
(875×1240) tragen bloß die ARP-Koordinate im Kopf. Das Verfahren ersetzt das
Schwellenverfahren also nicht, es ist der Weg für die großen Blätter.

### Drei Fallen, jede davon einmal zugeschnappt

1. **Das Winkelfenster.** EDLP ist um 57 Grad gedreht. Eine Suche über ±8 Grad findet dort
   nichts — und meldet trotzdem einen Treffer, nämlich irgendwelche Rollwege, gleichmäßig
   genug, um zu überzeugen. Das Fenster steht deshalb auf ±46 Grad.

2. **Welche Schar welche ist, entscheidet nicht die Neigung.** Bei EDLP sind die
   *waagerechteren* Linien die der **Längen**, nicht der Breiten. Wer das verwechselt,
   bekommt ein Abstandsverhältnis, das nach einem Fehler im Blatt aussieht, und sucht ihn an
   der falschen Stelle. Die Probe dagegen kommt ohne Beschriftung aus und steht als
   `verhaeltnis_stimmt()` im Werkzeug: Sind beide Scharen 10-Sekunden-Linien, muss der
   Abstand der Breiten zu dem der Längen stehen wie 1/cos(Breite).

3. **Die Beschriftung niemals durch Zuschneiden an einer gerechneten Stelle ablesen.**
   Dabei erwischt man das Etikett der Nachbarlinie. Bei EDDS kostete das einen um eins
   verzählten Index und 8,28 Prozent Abweichung — die Gegenprobe hat es gefangen, aber
   erst nach zwei Stunden. `--bild` zeichnet die erkannten Linien nummeriert ins Blatt;
   erst danebengelegt ist die Zuordnung belegt.

### Die Leiste bleibt die Gegenprobe, nicht der Schiedsrichter

Bei EDDN weicht sie um 3,4 Prozent vom Netz ab. Nachgeprüft hat **das Netz** recht: Es ist
in sich stimmig (Abstandsverhältnis 1,535 gegen 1/cos(49,5°) = 1,540), beide Beschriftungen
sind zweifach belegt, und die Bahnmitte aus den Schwellenkoordinaten landet 31 m neben dem
ARP-Symbol. Eine gedruckte Maßstabsleiste kann falsch sein — zweiter Fall nach EDBM.

**Was daraus folgt, wenn Netz und Leiste sich widersprechen:** nicht raten, sondern eine
dritte, unabhängige Größe holen. Das war hier die Bahnmitte aus den Schwellenkoordinaten,
gegen das gedruckte ARP-Symbol gehalten.

## Dritte Fehlerklasse: die Leiste selbst widerspricht dem Blatt

**EDBM Flugplatzkarte, 01.09.2026.** Schwellenabstand (Bars bei den Beschriftungen "09"/"27",
pixelgenau mit Rastersuche vermessen) ergibt 1,51 m/px — deckt sich auf 0,2 % mit der
OurAirports-Länge UND mit dem auf dem Blatt selbst gedruckten Text "1000 x 30 m". Die
Maßstabsleiste ergibt dagegen 1,266 m/px, mehrfach nachgemessen (vier 100-m-Segmente exakt
je 79 px, keine Messunsicherheit). Beide Werte sind für sich genommen präzise — sie
widersprechen sich trotzdem um 20 %.

Drei voneinander unabhängige Quellen (OurAirports-Länge, gedruckter Text, Schwellenabstand)
stimmen überein; nur die grafische Leiste weicht ab. Nahliegendste Erklärung: Die Leiste ist
auf diesem einen Blatt nicht im selben Maßstab gerendert wie der Rest der Zeichnung — ein
Fehler der Quelle, nicht der Messung. Trotzdem **nicht gespeichert**: Die Gegenprobe ist
genau dafür da, sich nicht auf die plausiblere Erklärung zu verlassen, sondern auf eine
zweite Messung zu bestehen. EDBM bleibt offen, bis jemand das Blatt ansieht.

## Sonderfälle

* **EDKB Flugplatzkarte** hat keine Schwellenkoordinaten bei OurAirports. Dort müssen die
  Werte am **Gradnetz des Blatts** abgelesen werden — und die Gegenprobe greift nicht. Diese
  Karte bleibt liegen, bis jemand sie mit offenen Augen macht.
* **Blätter ohne erkennbare Maßstabsleiste**: nicht speichern, aufschreiben.
* Die **13 Plätze**, an denen die alte Automatik an verfälschten Längen scheiterte (EDAK,
  EDAZ, EDBH, EDPH, EDSI, EDMB, EDLA, EDQA, EDNG, EDQC, EDRB, EDLP, EDDS), sind von Hand
  kein Sonderfall — man klickt die Schwellen, statt graue Flächen zu vermessen. Bei ihnen
  ist aber mit Stopways zu rechnen; also besonders genau hinsehen.

---

## Was NICHT zu tun ist

* **Keine Automatik nachbauen.** Sie ist am 31.08.2026 auf ausdrückliche Entscheidung
  zurückgebaut worden, weil sie über drei von 107 Plätzen nicht hinauskam. Wer sie
  wiederbelebt, baut etwas zurück, das bewusst entfernt wurde.
* **Keine Passung speichern, die die Gegenprobe nicht bestanden hat** — auch nicht „weil sie
  plausibel aussieht". Genau so entstehen die Fehler, die niemand mehr findet.
* **Nicht deployen.** Das Passen schreibt nur in die Datenbank; es braucht keinen Deploy und
  darf keinen auslösen.

---

## Stand

| Sorte | Status | Zahl |
|---|---|---|
| Flugplatzkarte | offen | 11 |
| Rollkarte | offen | 32 |
| beide | `auto` (von Claude gesetzt, ungeprüft) | 68 |
| beide | `gepasst` (bestätigt) | 0 |

Die 68 auf `auto` stammen aus der alten Bahnvermessung und sind **nicht** durch die
Gegenprobe gelaufen. Sie später ebenso nachzuprüfen wäre folgerichtig — aber erst, wenn die
43 offenen stehen.
