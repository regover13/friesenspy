# Messliste für den nächsten Simulator-Termin

**Alles, was an der Brügge noch ungemessen ist — in einem Zug abzuarbeiten.**

Diese Liste gibt es, weil am 11.09.2026 acht Simulator-Neustarts draufgingen: Nach jedem Fund
wurde sofort gebaut und neu gestartet, statt erst fertigzubauen und dann alles am Stück zu
messen. Die laufende Sim-Sitzung ist die knappe Ressource, nicht die Bauzeit.

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

## 3. Räumt sie ab, was aus `soll` verschwindet?

Im Admin auf „wegnehmen" klicken. Innerhalb eines Takts (1 s) verschwindet das Objekt aus
`steht` — **aber nicht aus dem Simulator.** Das war in Fassung 1.1.1 so und kein
Fehler: `SimConnect_AIRemoveObject` ist vorerst ausgebaut (s. `objekt_entfernen` in
`bruegge.cpp`), weil beim ersten Lauf nach dem BOM-Fund genau **eine** Sache anders sein
sollte. Die Brügge vergisst das Objekt also nur; weggeräumt wird es beim Schließen der
Verbindung.

**Das ist der Kern des Sollzustands-Gedankens:** Die Brügge befolgt keine Befehle, sondern
gleicht ab. Geht eine Anfrage verloren, holt die nächste den Zustand wieder ein.

### 3b. `AIRemoveObject` — **eingebaut, wartet auf einen Neustart**

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
> **Nach dem Neustart zu prüfen:** Bär unter derselben `id` versetzen → `seit_s` beginnt bei
> null, und er steht 5 m weiter.

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

Objekt setzen, dann im Sim einen anderen Flug laden.

**Erwartet:** Die Brügge räumt beim `FlightLoaded` alles ab und setzt neu, was der Server für
die neue Lage schickt. (Dass die Objekte den Wechsel technisch überleben, ist gemessen — sie
gehören aber zur alten Position des Piloten.)

---

## 6. Was tut sie bei Netzausfall?

WLAN aus, oder den Container kurz anhalten.

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

## Was NICHT mehr zu messen ist

Am 11.09.2026 bereits im Flug bestätigt:

- Positionsmeldung über HTTPS aus WASM ✅
- Zuordnung allein über die Position, ohne Anmeldung ✅
- Steigflug (1900 ft, 1044 ft Höhendifferenz gehalten) ✅
- Abfangen (nachlaufende Höhenschranke) ✅
- Absturz und Respawn (Selbstheilung) ✅
- VATSIM-Trennung und Wiederverbindung ✅
- Sprungerkennung beim Laden (0/90, Seattle) ✅

---

## Danach

Ergebnisse in [`probe-msfs/ERGEBNIS.md`](probe-msfs/ERGEBNIS.md), offene Punkte in
[`../docs/offene-aufgaben.md`](../docs/offene-aufgaben.md). Was sich am Vertrag ändert, gehört
in [`PROTOKOLL.md`](PROTOKOLL.md) — **und dann in alle drei Umsetzungen.**
