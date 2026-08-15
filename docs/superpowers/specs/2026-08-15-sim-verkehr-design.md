# Verkehr aus dem Simulator — Design (Teilprojekt 2)

**Datum:** 2026-08-15
**Status:** abgestimmt, bereit für die Planung
**Vorgänger:** `2026-08-15-fremdverkehr-karte-design.md` (Teil 1, ausgeliefert als V12.7.0)

## Ziel

Im Kniebrett zeigt die Karte den Verkehr so, wie der Simulator ihn kennt: **jede Sekunde,
auf den Meter genau, auch ohne VATSIM-Verbindung**. Statt alle 15 Sekunden eine
Momentaufnahme aus dem Internet, die zwischen zwei Abrufen geraten werden muss.

## Abgrenzung

| Teil | Inhalt | Status |
|---|---|---|
| 1 | VATSIM-Feed, 15 s + Fortrechnung, Website **und** Kniebrett | **fertig** (V12.7.0) |
| 2a | Sim-Verkehr im Kniebrett, 1 Hz, ersetzt dort den VATSIM-Feed | dieses Dokument |
| 2b | Identität: Callsign und Flugplan an den Sim-Verkehr | dieses Dokument, Abschnitt 8 |

**2b hängt an einer Messung, die 2a nebenbei mitliefert.** Deshalb blockiert sie nichts:
2a wird gebaut und ausgeliefert, der erste Flug damit beantwortet die offene Frage, und
erst danach wird 2b zugeschnitten.

---

## 1. Der Befund, der dieses Teilprojekt umgekrempelt hat

Ursprünglich war für Teil 2 ein C++-WASM-Modul eingeplant: DevSupport 4993 sagt, dass in
der Luft erzeugte AI-Objekte bei `GET_AIR_TRAFFIC` fehlen — von Asobo bestätigt, und genau
so injiziert vPilot seinen Verkehr. Für MSFS 2024 war das nie bestätigt.

**Messung 15.08.2026, 10:32 UTC, Hamburg (53.634/10.003), vPilot verbunden:**

```
Coherent.call('GET_AIR_TRAFFIC')  ->  6 Flugzeuge
VATSIM im 75-km-Umkreis           ->  6 Flugzeuge
Felder: __Type, name, plane_model_icao, uId, lat, lon, alt, heading, isOnGround
```

Sechs zu sechs. **DevSupport 4993 ist für MSFS 2024 überholt.** Kein WASM-Modul, kein
CommBus, kein SimConnect — ein `Coherent.call` in der EFB-App genügt.

Die Zahl allein wäre wertlos gewesen: Ein erster Anlauf meldete dreimal „0 Flugzeuge",
weil der Nutzer zu allen drei Zeitpunkten noch gar nicht mit vPilot verbunden war. Erst
die Gegenprobe gegen den eigenen VATSIM-Feed macht einen Datensatz aussagekräftig — „Sim 0,
VATSIM 7" ist eine Antwort, „Sim 0, VATSIM 0" ist keine. Das Verfahren bleibt (Abschnitt 7).

---

## 2. Die Schnittstelle — belegt, nicht vermutet

Die Einheiten von `GET_AIR_TRAFFIC` stehen in keiner Dokumentation. Sie stehen aber im
ausgelieferten Code des Simulators, und der ist auf der Platte lesbar. Zwei Fundstellen,
beide aus der MSFS-2020-Installation, beide Asobo/Working Title:

| Datei | Rolle |
|---|---|
| `workingtitle-instruments-g1000/…/msfssdk.js` → `TrafficInstrument` | offizielles SDK |
| `workingtitle-ingamepanels-vfrmap/…/GameVFRMap.js` → `VfrTrafficManager` | Asobos VFR-Karte |

| Frage | Antwort | Beleg |
|---|---|---|
| `alt` | **Meter** | `UnitType.METER.convertTo(entry.alt, UnitType.FOOT)` |
| `heading` | **Grad** | `NavMath.diffAngle` wickelt bei ±180/360, nicht bei ±π |
| Schlüssel | **`uId`**, über Abrufe stabil | beide führen ihre Map über `entry.uId` |
| Abruftakt | **1000 ms** | `VfrTrafficManager.POLL_INTERVAL = 1000` |
| Grundgeschwindigkeit | **wird nicht geliefert** | beide leiten sie aus Positionsdifferenzen ab |
| Aufruf kann hängen | **ja** | SDK: `Promise.race([Coherent.call(…), Wait.awaitDelay(1000)])` |
| Doppelaufruf | verhindern | SDK: `isBusy`-Riegel um den Aufruf |
| Zwischen den Abrufen | linear interpolieren | Asobos Karte rechnet `percentTraveled` fort |

Dazu die Plausibilitätsgrenzen, die das SDK selbst ansetzt — die Rohdaten sind rauschig,
und das SDK glättet sie ausdrücklich („to reduce artifacts from potentially noisy data"):

```
MAX_VALID_GROUND_SPEED     = 1500 kt
MAX_VALID_VERTICAL_SPEED   = 10000 fpm
MIN_GROUND_TRACK_DISTANCE  = 10 m      (darunter ist die Richtung bedeutungslos)
Glättungs-Zeitkonstante    = 2/ln2 ≈ 2,885 s
```

**Was der Beleg nicht hergibt:** Was in `name` und `plane_model_icao` steht. Asobos Karte
liest beide Felder gar nicht. DevSupport 13002 behauptet „`name` ist immer leer" — nach
4993 ist das kein Argument mehr, sondern eine Vermutung. Siehe Abschnitt 7.

**Was der Beleg nahelegt, aber nicht beweist:** Dass das eigene Flugzeug **nicht** in der
Liste steht. Asobos VFR-Karte zeichnet jeden Eintrag ungefiltert — stünde das eigene darin,
läge ein zweites Symbol über dem eigenen. Dazu passt die Messung (6 = 6; der Server filtert
das eigene Flugzeug über die CID heraus). Trotzdem wird defensiv gefiltert (Abschnitt 4).

---

## 3. Entscheidungen

| Frage | Entscheidung | Warum |
|---|---|---|
| Wer liefert im Kniebrett? | **Sim**, solange seine Meldungen frisch sind | 1 Hz statt 15 s, exakt statt gerechnet, und ohne Internet |
| Und wenn nicht? | VATSIM, wie bisher | die Brücke reißt (Tablet zu, App-Neustart) — dann ist der alte Weg der richtige |
| Beides gleichzeitig? | **nein** | jedes Flugzeug hätte zwei Symbole, 15 s versetzt |
| Wo wird gerechnet? | **im Panel** | dort liegt die uId-Historie und der feste Sekundentakt; die Seite bekommt fertige Werte |
| Bedienung | **dieselbe Checkbox „Verkehr"** | für den Nutzer ist es dieselbe Sache, nur besser |
| Aus = wirklich aus | Panel fragt nicht ab, wenn die Ebene aus ist | ein `Coherent.call`/s, den niemand sieht, ist Verschwendung |
| Stehende Flugzeuge | **nicht zeichnen** (GS < 5 kt **und** am Boden) | am Heimatplatz sonst dreißig Symbole übereinander, alle ohne Aussage |
| Rollverkehr | **zeichnen** | am Platz ist er die wertvollste Information, die es gibt |
| Deckel | 60, nach Entfernung | wie serverseitig in Teil 1 |
| Symbol und Label | unverändert aus Teil 1 | dunkel mit hellem Saum, `MUSTER HÖHE GS` |

---

## 4. Panel-Seite

### 4.1 Der Abruf

Wie `positionSenden`: in `onUpdate` der EFB, nicht in einem eigenen `setInterval`. Die
EFB-Schleife läuft nur, solange die App sichtbar ist — ein Timer liefe im Zweifel weiter,
während niemand hinsieht (Asobo nennt genau diesen Weg, DevSupport 10986).

```
Takt:     1000 ms  (VERKEHR_INTERVALL_MS — Asobos eigener Takt)
Riegel:   solange ein Aufruf offen ist, kein zweiter  (verkehrLaeuft)
Wettlauf: Promise.race gegen 1000 ms — der Aufruf darf nicht hängen bleiben
Schalter: nur abrufen, wenn die Seite die Ebene als eingeschaltet gemeldet hat
```

Der Schalter kommt über den **bestehenden** Rückkanal Seite → Shell
(`quelle: "friesenspy"`, ausgewertet in `onNachricht`) als neue Art `verkehr-schalter`.

### 4.2 Aufbereitung

Aus dem Rohsatz wird je Eintrag:

| Feld | Herkunft |
|---|---|
| `id` | `uId` |
| `lat`, `lon` | unverändert, auf 5 Nachkommastellen gerundet |
| `alt` | `alt` × 3,28084 → Fuß, ganzzahlig |
| `hdg` | `heading`, ganzzahlig, auf 0–359 normiert |
| `gs` | **abgeleitet**: Strecke zur letzten Position ÷ Zeit, geglättet |
| `ac` | `plane_model_icao`, sonst leer |
| `cs` | `name`, sonst leer — bis Abschnitt 8 geklärt ist, nur mitgeführt |
| `gnd` | `isOnGround` |

**Die Ableitung der Grundgeschwindigkeit** ist der einzige rechnende Teil und folgt dem
SDK: Haversine zwischen der letzten und der aktuellen Position, geteilt durch die
verstrichene Zeit, in Knoten. Ohne Glättung zappelt die Zahl im Label bei jedem Abruf —
also exponentiell glätten mit derselben Zeitkonstante wie das SDK (≈ 2,885 s) und Werte
über 1500 kt verwerfen. Beim ersten Auftauchen eines `uId` gibt es keine Vorgängerposition;
dann bleibt `gs` bei 0, bis die zweite Meldung da ist.

Der Zustand je `uId` (letzte Position, Zeitstempel, geglättete GS) lebt im Panel und wird
aufgeräumt, sobald ein `uId` nicht mehr gemeldet wird.

### 4.3 Filter und Deckel

In dieser Reihenfolge:

1. **Das eigene Flugzeug**: Eintrag verwerfen, dessen Position weniger als 150 m von der
   eigenen entfernt liegt **und** dessen Höhe um weniger als 100 ft abweicht. Nach heutigem
   Stand greift der Filter nie — er kostet nichts und verhindert ein Doppelsymbol genau
   dort, wo es am meisten stören würde.
2. **Stehende**: `isOnGround` **und** abgeleitete GS < 5 kt.
3. **Deckel**: nach Entfernung zur eigenen Position sortieren, die ersten 60 behalten.

### 4.4 Die Nachricht

```js
{ quelle: "friesenspy-shell", art: "sim-verkehr", liste: [ … ] }
```

Nur wenn die Liste sich geändert hat oder der Herzschlag fällig ist — dieselbe Regel wie
bei der Position (`POSITION_HERZSCHLAG_MS`), aus demselben Grund: Die Seite verwirft eine
Quelle, die schweigt. Bei bewegtem Verkehr ändert sich ohnehin jede Sekunde etwas; die
Regel greift nur, wenn die Liste leer bleibt.

---

## 5. Seiten-Seite

### 5.1 Empfang und Frischewache

Neue Art im bestehenden Empfänger (`_initPanelShellKanal`, `art === 'sim-verkehr'`).
Analog zu `_simPos`/`_simPosFrisch()`:

```js
_simVerkehr      = { ts, liste }
_simVerkehrFrisch()  ->  ts jünger als _SIM_POS_MAX_ALTER_MS
```

### 5.2 Der Umschalter

**Genau eine Quelle ist aktiv.** Die Regel steht an einer Stelle und wird von beiden Seiten
gelesen:

- `_verkehrAbrufen` bricht ab, solange `_simVerkehrFrisch()` — kein Netzabruf, den ohnehin
  niemand zeichnet.
- Wechselt die Quelle (Sim wird frisch / Sim wird alt), wird **einmal** `_verkehrLeeren()`
  gerufen. Beide Quellen schreiben in dieselben Ablagen (`_verkehrRoh`, `_verkehrMarker`);
  ohne das Leeren blieben die Marker der alten Quelle stehen und würden endlos fortgerechnet.

### 5.3 Zeichnen

`_simVerkehrUebernehmen(liste)` schreibt in **dieselben** Ablagen wie
`_verkehrUebernehmen` und benutzt dieselben Bausteine (`makeAircraftIcon(hdg, true)`,
`_verkehrLabel`, `_verkehrPopup`, Fehl-Hysterese). Schlüssel ist `'sim:' + id` — so kann
ein Sim-Schlüssel nie mit einem VATSIM-Callsign kollidieren, auch wenn beide Quellen sich
einmal überschneiden sollten.

Bewegt wird weiterhin **ausschließlich** in `_naviTakt` über `_verkehrRoh` — die Regel aus
Teil 1 bleibt unangetastet: eine Bewegung, ein Eigentümer. Bei 1 Hz ist die Fortrechnung
kaum noch sichtbar, sie bleibt aber richtig und kostet nichts.

### 5.4 Der Schalter zum Panel

Beim Ein- und Ausschalten der Ebene meldet die Seite an die Shell:

```js
{ quelle: "friesenspy", art: "verkehr-schalter", an: true|false }
```

Gesendet in `_setupVerkehrPref` (`overlayadd`/`overlayremove`) und einmal beim Aufbau, damit
eine gespeicherte Präferenz auch ohne Klick ankommt.

---

## 6. Was der Nutzer sieht

| Lage | vorher | nachher |
|---|---|---|
| Kniebrett, vPilot verbunden | Marker alle 15 s neu gesetzt, dazwischen gerechnet | flüssig, jede Sekunde echt |
| Kniebrett, **ohne** VATSIM | leere Karte | der AI-Verkehr des Simulators |
| Kniebrett, Tablet gerade zu | — | beim Öffnen sofort wieder Sim-Verkehr |
| Brücke abgerissen | — | VATSIM übernimmt still, wie vorher |
| Website | VATSIM | unverändert VATSIM |
| Am Heimatplatz | — | Rollverkehr ja, geparkte Flugzeuge nein |

---

## 7. Die Messung, die mitläuft

Die Sonde aus Paket 1.3.0/1.4.0 (`_SONDE_ZEITPUNKTE`, feste Termine nach dem Öffnen der
App) **entfällt ersatzlos.** Sie hat ihre Frage beantwortet, und ihre Termine gehen am
Arbeitsablauf des Nutzers vorbei: Der Flug wird geladen, **dann** ist das Tablet schon
offen, **erst danach** verbindet vPilot. Eine Sonde, die N Minuten nach dem Öffnen misst,
trifft den richtigen Moment nur zufällig.

An ihre Stelle tritt eine **einmalige Diagnose aus dem echten Zulieferer**: Beim ersten
Eintreffen einer nichtleeren Sim-Verkehrsliste meldet die Seite den ersten Eintrag
vollständig — mit Rohwerten — über `window._panelDiag('sim-verkehr', …)`, ergänzt um die
Gegenprobe gegen `/api/traffic` wie gehabt.

Das beantwortet in einem einzigen Flug, ohne Zusatzarbeit:

- Was steht in `name`? (entscheidet Abschnitt 8)
- Was steht in `plane_model_icao`? (`C172` oder Asobo-interner Modellname?)
- Stimmt die Umrechnung der Höhe? (ein Flugzeug in FL350 muss ~35 000 zeigen, nicht ~10 700)
- Steht das eigene Flugzeug doch in der Liste?
- Wie weit reicht der Sim-Horizont? (größte Entfernung im Vergleich zur VATSIM-Zahl)

---

## 8. Teil 2b — Identität (nach der Messung zuzuschneiden)

Der Sim liefert Position und Muster, aber nach heutigem Wissen keinen Flugplan. Callsign
und Route sind das, was die VATSIM-Quelle besser kann. Zwei Wege, die Messung entscheidet:

| Fall | Weg | Aufwand |
|---|---|---|
| `name` trägt den Callsign | direkt übernehmen, Flugplan über den Callsign aus dem VATSIM-Feed nachschlagen | klein |
| `name` ist leer | Zuordnung über die Position: Sim-Eintrag und VATSIM-Eintrag, die < 2 km und < 500 ft auseinanderliegen, sind dasselbe Flugzeug; einmal je VATSIM-Abruf (15 s) bestimmt und festgehalten | mittel, fehleranfällig bei dichtem Verkehr |

Ein Nebeneffekt von 2b wäre, dass VATSIM-Verkehr **außerhalb** des Sim-Horizonts wieder
mitgezeichnet werden könnte, ohne Doppelbilder. Das ist ausdrücklich **nicht** Teil von 2a:
Der harte Umschalter ist einfach und richtig, solange die Zuordnung fehlt.

---

## 9. Bewusst nicht gemacht (YAGNI)

- **Kein Vertikalprofil, keine Steig-/Sinkrate.** Das SDK leitet sie mit ab; im Label ist
  kein Platz, und auf einer Karte von oben ist sie nicht die Frage.
- **Keine Kollisionswarnung.** FriesenSpy ist eine Lagekarte, kein TCAS. Wer daraus eine
  Warnung baut, muss für sie geradestehen.
- **Kein Sim-Verkehr auf der Website.** Er existiert dort nicht — die Seite ohne Kniebrett
  hat keinen Simulator hinter sich.
- **Keine Zusammenführung im ersten Wurf.** Siehe Abschnitt 8.
- **Kein Verkehr aus SimConnect/WASM.** Der Grund dafür ist entfallen.

---

## 10. Risiken

| Risiko | Gegenmittel |
|---|---|
| `Coherent.call` hängt | 1-s-Wettlauf + Riegel, beides aus dem SDK übernommen |
| Falsche Höheneinheit in 2024 | sofort im Bild sichtbar (FL110 statt 35 000); Diagnose meldet Rohwerte |
| Abgeleitete GS zappelt | Glättung mit der SDK-Zeitkonstante, Verwerfen über 1500 kt |
| Markerflut am Platz | stehende Flugzeuge werden nicht gezeichnet |
| Kosten im Sim | 1 Aufruf/s ist Asobos eigener Takt in seiner eigenen Karte |
| Beide Quellen zeichnen gleichzeitig | genau ein Umschaltpunkt, beim Wechsel wird geleert |

---

## 11. Abnahmekriterien

1. Im Kniebrett mit verbundenem vPilot bewegen sich die Fremdverkehr-Marker **flüssig**,
   nicht in 15-Sekunden-Sprüngen.
2. Bei getrenntem vPilot, aber laufendem Sim-AI-Verkehr, sind Flugzeuge auf der Karte.
3. Die Höhen im Label sind plausibel (ein Airliner zeigt `FL…`, kein vierstelliger Fuß-Wert).
4. Die Symbole zeigen in die Flugrichtung.
5. Am Heimatplatz stehen keine Symbole auf geparkten Flugzeugen; ein rollendes ist sichtbar.
6. Ebene „Verkehr" aus → keine Marker, und das Panel fragt den Sim nicht mehr ab.
7. Tablet schließen und wieder öffnen → Verkehr ist sofort wieder da.
8. Auf der Website ist alles unverändert.
9. `/admin` zeigt genau eine `sim-verkehr`-Diagnose je Flug, mit Rohwerten und Gegenprobe.
10. Die alte Sonde meldet nichts mehr (`traffic-sonde` taucht nicht mehr auf).

---

## 12. Berührungspunkte mit der parallelen Sitzung

Die zweite Sitzung arbeitet auf `platzrunden-karte` (Spec/Plan
`2026-08-15-platzrunden-karte*`). Ihr Plan reserviert den Verkehrs-Block in `index.html`
ausdrücklich für diese Arbeit hier. Die Aufteilung:

| Datei | diese Arbeit | Platzrunden |
|---|---|---|
| `index.html`, Verkehrs-Block | **ja** | ausdrücklich nein |
| `index.html`, neue Blöcke davor | nein | ja |
| `index.html`, `liveOverlays` | nein — die Ebene existiert schon | ja, drei neue Zeilen |
| `msfs-panel/` | **ja**, allein | nein |
| `tests/test_vr_panel.py` | **ja** | nein (eigene Dateien) |
| `app/CHANGELOG.json` | **ja**, V12.10.0 | ja, V12.8.0 + V12.9.0 |

**Einziger echter Konflikt: `app/CHANGELOG.json`.** Beide Seiten setzen einen Eintrag an
den Anfang des Feldes — das kollidiert textlich, unabhängig von der Reihenfolge. Deshalb
hier **12.10.0**, damit wenigstens die Versionsnummern nicht kollidieren; der Konflikt
selbst ist beim Zusammenführen in einer Minute aufgelöst (beide Einträge behalten,
absteigend sortieren).
