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
> | `tier_gross` | — | `EXCEPTION_22` | |
> | `fahrzeug` | — | `KEINE_ANTWORT` | |
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
> **Damit ist die Geländehöhe am ZIELORT messbar**, ohne Höhenmodell, ohne Überflug, ohne
> SRTM (dessen 30-m-Raster genau diese Unterschiede gar nicht abbilden kann, s. 5c):
>
> ```
> 1. Sonde setzen    { "art": "bauwerk", "auf_boden": 1, "lat": …, "lon": … }
> 2. Höhe ablesen    "steht": [{ "id": "sonde", "hoehe_ft": 1370.0 }]
> 3. Sonde weg, Objekt hin   { "art": "…", "erwartete_hoehe_ft": 1370.0 }
> ```
>
> **Nebenbei bewiesen:** Fassung 1.2.0 läuft — sonst wäre `auf_boden` ignoriert worden und
> alle fünf hätten 1565,5 gemeldet.
>
> ### Offen
>
> - **`tier_gross` und `fahrzeug` scheitern mit `OnGround=1`** (`EXCEPTION_22` /
>   `KEINE_ANTWORT`) — dieselbe Gattung `tier_gross` stand vorher mit `OnGround=0`
>   problemlos. Für die Sonde ist das gleichgültig (`bauwerk` genügt), für den Kieker nicht:
>   **Tiere sind das, was gezählt werden soll.**
> - Ob die gemeldete Höhe wirklich das Gelände trifft oder nur den Referenzpunkt des
>   Sondenmodells (2b), ist ungeprüft. Für `bauwerk` (Windmühle, Fundament am Boden) ist die
>   Verwechslungsgefahr am kleinsten — deshalb ist sie die richtige Sonde.

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
