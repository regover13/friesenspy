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
