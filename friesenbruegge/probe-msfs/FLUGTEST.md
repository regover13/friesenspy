# Flugtest: Wird ein weit gesetztes Objekt gezeichnet, wenn der Pilot hinkommt?

> ## ✅ Geflogen am 11.09.2026 — **ja, es wird gezeichnet**
>
> EDWG Wangerooge nach EDWY Norderney, MSFS 2024. Ein `CruiseShip01` wurde aus **44,7 km**
> Entfernung vor Norderney gesetzt und war bei **22,1 km** zweifelsfrei zu sehen.
>
> | Entfernung | gemeldete Höhe | |
> |---|---|---|
> | 44,7 km | −0,8 ft | gesetzt |
> | 22,1 km | 1,8 ft | **gesehen** |
> | 4,5 km | −0,1 ft | |
>
> **Folge: Der Server darf einmal verteilen.** Die Brügge muss nicht unterwegs nachsetzen,
> sobald der Pilot in Reichweite kommt.
>
> ⚠ **Die Zahl 22 km gilt für ein Kreuzfahrtschiff, nicht allgemein.** Ein `CruiseShip01` ist
> rund 300 m lang; große Objekte blendet der Simulator deutlich früher ein als kleine. Für den
> Kieker sind aber gerade die **kleinen** die relevanten — `Boat01` misst acht Meter, ein Tier
> zwei.
>
> **Der tragende Teil des Befunds hängt nicht an der Zahl:** Belegt ist, dass der Simulator ein
> aus 45 km gesetztes Objekt **nicht vergisst**, sondern zeichnet, sobald der Pilot in Reichweite
> kommt. Das ist eine Eigenschaft der Objektverwaltung und nicht der Größe. **Ungemessen bleibt,
> ob ein kleines Objekt denselben Weg geht** — der Test dafür ist derselbe Flug mit `Boat01`
> statt `CruiseShip01`.
>
> **Zweiter Befund:** Die Höhe blieb über die ganze Strecke an der Wasserlinie. Bei 45 km ist
> die Höhenmeldung also brauchbar — der Phantomwert vom Bodensee trat erst bei 691 km auf.
> Das grenzt die offene Frage nach der Grenze ein: irgendwo zwischen 200 und 691 km.
>
> *Die Anleitung unten bleibt stehen — für eine Wiederholung in MSFS 2020 und X-Plane, wo
> die Frage noch offen ist.*


**Die letzte Frage, die einen echten Flug braucht** — alle übrigen sind im Stand zu messen.
Sie entscheidet darüber, wie die Brügge arbeitet:

| Antwort | Folge fürs Protokoll |
|---|---|
| **Ja, es wird gezeichnet** | Der Server darf **einmal verteilen**. Die Brügge setzt beim Betreten eines Reviers alles und ist danach still. |
| **Nein** | Die Brügge muss **unterwegs nachsetzen**, sobald der Pilot in Reichweite kommt — und der Server muss laufend wissen, wo er ist. |

---

## Was schon feststeht

**Das Anlegen gelingt bis 10.000 km.** Elf Läufe, keine einzige `EXCEPTION 33 —
OBJECT_OUTSIDE_REALITY_BUBBLE` (s. „Die Reality Bubble" in [`ERGEBNIS.md`](ERGEBNIS.md)).

**Die Sichtbarkeit ist nur im Nahbereich belegt:** 200 m an Land, 1,6 km auf dem Wasser,
beides per Screenshot. Alles darüber hinaus ist eine Lagemeldung — und die sagt nur, dass das
Objekt **existiert**, nicht dass es **gezeichnet** wird.

⚠ **Und aus der Ferne lügt sogar die Lagemeldung:** Am 11.09.2026 meldete ein Schiff am
Bodensee 2106,5 ft, während dasselbe Schiff an derselben Koordinate aus der Nähe 1297,2 ft
meldete. Der Simulator antwortet aus grobem Gelände. Die Höhe taugt also nicht als Nachweis,
dass „alles in Ordnung" ist.

---

## Aufbau

**Strecke:** irgendein Flug von 20–40 Minuten über Land oder Watt. Die Friesischen Inseln
bieten sich an, weil dort ohnehin gespielt wird — etwa EDWG Wangerooge nach EDWY Norderney
(rund 40 km).

**Vor dem Start**, mit stehendem Flugzeug am Abflugplatz:

```
python kieker_probe.py --titel CruiseShip01 --lat <Ziel-Lat> --lon <Ziel-Lon> --halten 2400
```

Das Kreuzfahrtschiff, weil es groß ist und aus der Luft auffällt. `--halten 2400` sind
40 Minuten — **die Verbindung muss offen bleiben**, sonst räumt SimConnect das Objekt beim
Schließen weg (zweimal gemessen, `EXCEPTION 3` in der Nachprobe).

⚠ **Nicht `--neben-mir` benutzen.** Das setzt östlich des Flugzeugs und wäre genau der
Nahbereich, der schon belegt ist.

**Die Zielkoordinate** liegt am besten auf Wasser und **nicht** auf dem Platz selbst, sondern
2–3 km davor, im Anflug. So ist das Schiff im Blickfeld, ohne dass die Landung darum
herumführen muss.

---

## Während des Flugs

Die Kontrollspur läuft mit und schreibt alle zehn Sekunden eine Zeile:

```
t=+ 620.4s  53.71000 / 7.15000   4.7 ft   (Objekt 100777984 lebt, Flieger 18.3 km entfernt)
```

**Darauf achten — die Entfernung sinkt, und die Höhe ist der eigentliche Messwert:**

- Ändert sich die gemeldete Höhe beim Näherkommen **sprunghaft**, hat der Simulator das
  Gelände neu geladen. Das ist der Übergang von „grober Schätzung" zu „echtem Terrain", und
  der Abstand, bei dem es geschieht, ist eine der gesuchten Zahlen.
- Bleibt sie konstant, war sie von Anfang an echt.

**Notieren, wann das Schiff zuerst zu sehen ist** — mit der Entfernung aus derselben Zeile.
Das ist das Ergebnis.

---

## Die drei möglichen Ausgänge

| Beobachtung | Was daraus folgt |
|---|---|
| Schiff ist beim Näherkommen einfach da | **Einmal verteilen genügt.** Der beste Fall. |
| Schiff erscheint erst ab einer bestimmten Entfernung | Dieselbe Antwort, aber die Reichweite ist zu notieren — sie ist die Vorlaufstrecke, die der Server einhalten muss. |
| Schiff bleibt unsichtbar, obwohl die Lagemeldung läuft | **Nachsetzen ist Pflicht.** Dann gilt: Die Lagemeldung ist kein Beleg für Sichtbarkeit, und das gehört als Warnung ins Protokoll. |

⚠ **Ein „ich sehe nichts" ist ohne Gegenprobe nichts wert.** Ein `Boat01` ist rund acht Meter
lang, und am 11.09.2026 wurde in MSFS 2020 zweimal „kein Boot" gemeldet, obwohl eines
dastand — sichtbar wurde es erst als Kreuzfahrtschiff. Deshalb im Zweifel am Zielort:

```
python kieker_probe.py --boote-zaehlen --radius 5000
```

Der Simulator weiß es besser als das Auge. Findet die Zählung das Schiff und der Pilot sieht
es nicht, ist **das** der Befund — und zwar der wichtigste von allen.

---

## Danach

Ergebnis in [`ERGEBNIS.md`](ERGEBNIS.md) eintragen, die Zeile in
[`../../docs/offene-aufgaben.md`](../../docs/offene-aufgaben.md) streichen, und in
[`../PROTOKOLL.md`](../PROTOKOLL.md) Abschnitt 2 entscheiden, ob der Sollzustand einmal oder
fortlaufend übertragen wird.
