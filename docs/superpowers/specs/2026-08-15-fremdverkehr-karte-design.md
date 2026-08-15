# Fremdverkehr auf der Karte — Design

**Datum:** 2026-08-15
**Status:** abgestimmt, bereit für die Planung

## Ziel

Anderer VATSIM-Verkehr — nicht nur die Friesen — erscheint auf der Live-Karte im Umkreis
des sichtbaren Kartenausschnitts, gleitend statt springend, mit Muster, Höhe und
Geschwindigkeit am Symbol. Sichtbar auf der Website **und** im Kniebrett.

## Abgrenzung: dies ist Teilprojekt 1 von 2

Die Anzeige ist eine Sache, die Datenquelle eine andere. Es gibt zwei Quellen für
denselben Verkehr:

| | Quelle A — VATSIM-Feed | Quelle B — Sim (SimConnect/WASM) |
|---|---|---|
| Takt | 15 s + Fortrechnung | ≥ 1 Hz, echt gemessen |
| Wo | Website **und** Kniebrett | nur Kniebrett, nur mit laufendem Sim |
| Reichweite | ganz VATSIM | ~40 NM (vPilots Injektionsradius) |
| Aufwand | klein — der Poller holt den Feed ohnehin | C++-WASM-Modul, Machbarkeit ungeklärt |

**Dieses Dokument beschreibt ausschließlich Teilprojekt 1 (Quelle A) plus eine Messsonde,
die Teilprojekt 2 vorbereitet.** Teilprojekt 2 tauscht später ausschließlich den
Zulieferer aus; Marker, Label, Ebene und Fortrechnung bleiben unangetastet. Der Stand der
Recherche zu Teilprojekt 2 liegt in der Projekt-Memory (`project_traffic_panel.md`).

Die Naht zwischen beiden ist eine einzige Datenstruktur (`_verkehrRoh`, s. u.): Der
zeichnende Teil liest nur aus ihr und weiß nicht, wer sie gefüllt hat. Genau diesen Weg
nimmt die Eigenposition seit Kniebrett-Paket 1.2.0.

## Getroffene Entscheidungen

| Frage | Entscheidung |
|---|---|
| Reihenfolge | Anzeige + VATSIM-Feed zuerst, WASM später |
| Bezugspunkt für „in der Nähe" | die **Kartenmitte** — mit Moving Map *ist* das die eigene Position |
| Bedienung | zweite Checkbox in der bestehenden **Ebenen-Auswahl**, neben OpenAIP |
| Was die Ebene schaltet | **nur** den Fremdverkehr; die Friesen sind immer sichtbar |
| Label | Callsign, wenn tief **oder** Friese; darunter `MUSTER HÖHE GS` |
| Höhenformat | unter 10 000 ft Fuß-Zahl, ab 10 000 ft `FL` + Hunderter |

---

## 1. Server — Datenquelle

### 1.1 Momentaufnahme im Poller

`VatsimPoller._poll_once` (`app/poller.py`) holt bereits alle 15 s den kompletten Feed und
verwirft alles außer `FRS*`. Künftig legt es **zusätzlich** eine schlanke Momentaufnahme
aller Piloten in einem Attribut ab:

```python
self._traffic_snapshot: list[dict]   # ~1000 Einträge
self._traffic_snapshot_ts: float     # time.time() des Abrufs
```

Je Eintrag nur, was für Karte und Popup gebraucht wird: `callsign`, `lat`, `lon`,
`altitude`, `groundspeed`, `heading`, `aircraft` (aus `flight_plan.aircraft_short`, sonst
`""`), `departure`, `arrival`.

**Nichts davon geht in die Datenbank.** Fremdverkehr wird nicht historisiert — keine
Tabelle, keine Migration, keine Aufbewahrungsfrist.

Ausgeschlossen werden bereits hier:

- Piloten mit `callsign`-Präfix `settings.CALLSIGN_PREFIX` (die Friesen) — sie kommen über
  `/api/live` und SSE und stünden sonst doppelt auf der Karte.
- Einträge ohne brauchbare Koordinate (`latitude`/`longitude` fehlt oder beides exakt 0).

Ausgeschlossen wird **allein über das Callsign-Präfix**, nicht über die Friesen-Liste. Ein
per Admin-Checkbox auf „inaktiv" gesetzter Pilot (`get_inactive_cids`) fällt damit aus
beiden Listen heraus: er ist kein Friese mehr und wird auch nicht als Fremdverkehr
nachgereicht. Das ist die Absicht der Checkbox.

Zur Sichtbarkeit: `get_pilot_visibility` regelt **Benachrichtigungen** (`online`,
`prefile`, `ts`), nicht die Kartenpräsenz, und greift hier deshalb nicht. Ein Friese, der
ausnahmsweise ohne `FRS`-Callsign fliegt, erscheint als anonymer Fremdverkehr — ohne Namen,
wie jeder andere auch. Das ist öffentliche VATSIM-Information und dieselbe, die jede
Karten-Website zeigt.

### 1.2 Endpunkt `GET /api/traffic`

**Parameter:**

| Name | Typ | Bedeutung | Grenzen |
|---|---|---|---|
| `lat` | float | Bezugspunkt (Kartenmitte) | −90 … 90, Pflicht |
| `lon` | float | Bezugspunkt | −180 … 180, Pflicht |
| `r` | float | Radius in km | 1 … 250, Vorgabe 100 |

**Antwort:**

```json
{
  "age": 7.2,
  "traffic": [
    {"cs": "DLH4AB", "lat": 53.51, "lon": 8.12, "alt": 34000,
     "gs": 452, "hdg": 271, "ac": "A320", "dep": "EDDH", "arr": "EDDL"}
  ]
}
```

- `age` — Alter der Momentaufnahme in Sekunden. Der Client braucht es, um die
  Fortrechnung an der richtigen Stelle beginnen zu lassen statt beim Empfang.
- Kurze Feldnamen, weil dieselbe Antwort über die Netzwerkverbindung des Simulators geht.
  Bei 60 Flugzeugen sind das rund 5 KB.

**Verhalten:**

- Sortiert nach Entfernung zum Bezugspunkt, **gekappt bei 60 Flugzeugen** (`_TRAFFIC_MAX`).
  Was näher ist, gewinnt.
- Entfernung über die vorhandene Geo-Hilfsfunktion in `app/geo.py`; kein neuer
  Entfernungscode.
- Poller noch nicht gelaufen oder Momentaufnahme älter als 120 s → `{"age": null,
  "traffic": []}`, Status 200. Eine leere Karte ist die richtige Antwort, kein Fehler.
- Ungültige Parameter → 422 (FastAPI-Standard über Query-Validierung).
- Keine Anmeldung nötig — die Daten sind öffentlich, und der Endpunkt wird auch aus dem
  Kniebrett aufgerufen, wo die Anmeldung ein eigener Weg ist.

---

## 2. Client — Ebene und Abruf

### 2.1 Die Ebene

Zweite Overlay-Checkbox **„Verkehr"** in der bestehenden `L.control.layers`, direkt neben
OpenAIP. Zustand in `localStorage` unter `friesenspy_verkehr`, **Vorgabe aus**.

**Bekannte Stolperfalle, die hier zwingend zu beachten ist:** Der Layer muss dem Karten-
objekt **vor** dem Bau der Layers-Control hinzugefügt werden. Wird er danach per
`layer.addTo(map)` gesetzt, feuert keines der Ereignisse, auf die die Control lauscht, und
der Haken zeigt dauerhaft den falschen Zustand. Für OpenAIP ist das in
`_addPreferredAIPLayer` bereits gelöst und im Code kommentiert — der Verkehrs-Layer folgt
demselben Muster (`_setupVerkehrPref` / `_addPreferredVerkehrLayer`).

Der Layer selbst ist eine `L.layerGroup()`; alle Verkehrs-Marker hängen darin. Ausschalten
bedeutet: Gruppe von der Karte nehmen, Abruf-Timer stoppen, `_verkehrRoh` leeren.

### 2.2 Abruf

Solange die Ebene an ist, alle 15 s:

1. `liveMap.getCenter()` als Bezugspunkt.
2. Radius = Entfernung von der Mitte zur Ecke des sichtbaren Ausschnitts
   (`liveMap.getBounds().getNorthEast()`), auf 250 km gekappt.
3. `GET /api/traffic?lat=…&lon=…&r=…`

**Zoom-Schwelle:** Unterhalb Zoomstufe 8 wird **nicht abgefragt und nichts gezeichnet**,
und vorhandene Marker werden entfernt. Bei Zoom 7 liegt halb Europa im Bild; sechzig
Flugzeuge dort sind keine Information, sondern Rauschen — und im Kniebrett kostet jeder
Marker Rechenzeit in Coherent GT.

Zusätzlich ein Abruf sofort beim Einschalten der Ebene und nach jedem `moveend`, aber
frühestens 3 s nach dem letzten Abruf (Drossel gegen Dauerziehen an der Karte).

### 2.3 Fortrechnung

Rohwerte je Callsign in **einer** Struktur, parallel zu `_positionsRoh`:

```js
const _verkehrRoh = {};   // callsign -> {lat, lon, hdg, gs, ts}
```

`ts` wird beim Eintragen um `age` zurückdatiert (`Date.now() - age * 1000`), damit die
Fortrechnung dort beginnt, wo VATSIM gemessen hat, und nicht dort, wo die Antwort ankam.

Die vorhandene Funktion `_jetztGerechnet(roh)` wird **unverändert wiederverwendet** — sie
kennt ihre Datenstruktur, nicht ihren Besitzer. Bewegt wird ausschließlich im laufenden
Sekundentakt `_naviTakt`, in einer eigenen Schleife direkt nach der bestehenden über
`mapMarkers`.

Zwei Regeln aus der Friesen-Anzeige gelten hier genauso und sind dort teuer erkauft worden:

- **Der Zeitstempel wird nur bei wirklich neuen Koordinaten gesetzt.** Sonst startet die
  Fortrechnung bei jedem Abruf von vorn, und der Marker springt zurück.
- **Aus einer Schätzung wird nie die nächste Schätzung abgeleitet.** `_verkehrRoh` hält den
  gemeldeten Wert, der Marker die geschätzte Position; gerechnet wird immer vom Rohwert.

Callsigns, die in der Antwort fehlen, werden aus `_verkehrRoh` **und** von der Karte
entfernt — sonst rechnet der Takt eine Position endlos weiter, deren Flugzeug längst außer
Reichweite ist.

---

## 3. Marker und Label

### 3.1 Symbol

Dasselbe `_FLUGZEUG_PFAD`-Symbol wie bei den Friesen, aber:

- **18 px** statt 26 px,
- gedämpftes Grau statt Blau (eigene CSS-Klasse `.aircraft-marker-fremd`),
- `rotateWithView: true`, wie bei den Friesen — die Flugrichtung ist die Aussage, sie muss
  bei Track-up mitdrehen.

`makeAircraftIcon(heading)` bekommt dafür einen zweiten Parameter für Größe und Klasse; die
bisherigen Aufrufe behalten ihr Verhalten.

Klick öffnet ein Popup mit Callsign, Muster, Höhe, Geschwindigkeit und Route — derselbe
Aufbau wie `buildPopupHtml`, aber ohne Pilotenname und Online-Zeit, die der Feed für
Fremde nicht sinnvoll liefert.

### 3.2 Label — die Regel

**Callsign wird gezeigt, wenn das Flugzeug tief fliegt oder ein Friese ist.**

| | unter 10 000 ft | ab 10 000 ft |
|---|---|---|
| **Fremder** | `D-EXYZ`<br>`C172 4500 105` | `A320 FL350 450` |
| **Friese** | `FRS123`<br>`C172 4500 105` | `FRS123`<br>`A320 FL350 450` |

Begründung der Regel: Was tief fliegt, ist in der eigenen Nähe — da will man wissen, wer es
ist. Was oben drüberzieht, ist Linienverkehr; Muster, Level und Speed genügen.

**Formatierung im Einzelnen:**

- Trennzeichen ist ein **Leerzeichen**.
- Höhe unter 10 000 ft: ganze Zahl in Fuß, ohne Einheit (`4500`).
- Höhe ab **genau** 10 000 ft: `FL` + auf Hunderter gerundete Höhe (`10500` → `FL105`,
  `10000` → `FL100`).
- Am Boden (0 ft) gilt „unter 10 000" — Rollverkehr zeigt seinen Callsign.
- Fehlendes Muster (Pilot ohne Flugplan): `?`.
- Fehlende Höhe oder Geschwindigkeit: `0` behandeln wie den echten Wert 0 — der Feed
  liefert diese Felder immer, ein fehlender Wert am Boden ist ein gültiger Wert.

Das Label ist **neu für beide Seiten** — die Friesen-Marker haben heute gar kein
dauerhaftes Label, nur ein Popup.

### 3.3 Das Label darf nicht mitdrehen

`rotateWithView: true` dreht das gesamte Marker-Element. Ein Label innerhalb des Icons
stünde bei Track-up auf dem Kopf.

**Erster Ansatz:** `bindTooltip(text, {permanent: true, direction: 'bottom', className:
'traffic-label'})`. Tooltips sind eigene DOM-Elemente in einem eigenen Pane, nicht Teil des
Marker-Icons — sie sollten von `rotateWithView` unberührt bleiben.

**Das ist eine Annahme und muss gemessen werden**, denn `leaflet-rotate` dreht den ganzen
Karten-Pane per CSS-Transform. Verfahren: Karte im Browser auf ein Bearing setzen und die
tatsächliche Bildschirm-Matrix des Label-Elements über `getScreenCTM()` auslesen — **nicht**
das eigene `transform` des Elements, das die Drehungen der Vorfahren nicht enthält.

**Fallback, falls das Label mitdreht:** ein zweiter, eigener Marker je Flugzeug mit
`rotateWithView: false` (dann hält das Plugin ihn aufrecht) und einem `iconAnchor`, der ihn
in Bildschirmpixeln unter das Symbol setzt. Beide Marker werden vom selben Takt bewegt.
Kostet doppelt so viele DOM-Knoten — deshalb zweite Wahl, aber sicher.

---

## 4. Kniebrett

Kein eigener Code, keine eigene Ansicht: dieselbe Seite, dieselbe Ebenen-Auswahl, dieselbe
Fortrechnung. Der einzige Unterschied ist die Datenmenge über die Netzwerkverbindung des
Simulators, und die ist mit ~5 KB je 15 s unkritisch.

### 4.1 Messsonde für Teilprojekt 2

Vor Teilprojekt 2 steht eine offene Machbarkeitsfrage: Reicht der reine JS-Weg
(`Coherent.call('GET_AIR_TRAFFIC')`), oder muss ein C++-WASM-Modul her? DevSupport 4993
spricht dagegen — von Asobo bestätigt geben in der Luft erzeugte AI-Objekte über diesen
Aufruf nichts heraus, und genau so injiziert vPilot. Bestätigt ist das für MSFS 2024 aber
nicht.

Die Antwort kostet nichts, wenn sie beim normalen Fliegen nebenbei entsteht. In
`msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx` kommt deshalb eine Sonde:

- **Dreimal**, bei 20 s, 120 s und 300 s nach dem Start des Panels — die Zeitpunkte decken
  ab, dass vPilot beim ersten Messpunkt noch nichts injiziert hat.
- Je Messpunkt: `Coherent.call('GET_AIR_TRAFFIC')`, zusätzlich der Versuch mit
  vorangestelltem `RegisterViewListener('JS_LISTENER_MAPS')` + `JS_BIND_BINGMAP` — das war
  in MSFS 2020 die Vorbedingung dafür, dass der Aufruf überhaupt etwas liefert.
- Gemeldet wird per `postMessage` an die Seite und von dort über `window._panelDiag` als
  `panel_diag`-Datensatz mit `kind: "traffic-sonde"`: Anzahl der Einträge, die Feldnamen
  des ersten Eintrags, und ob der Aufruf überhaupt existiert.
- **Jede Messung ist in `try/catch` gekapselt und meldet auch ihren Fehler.** Eine Sonde,
  die den Panel-Start zum Absturz bringt, ist schlimmer als eine unbeantwortete Frage.
- Nach dem dritten Messpunkt ist Schluss — kein Dauerbetrieb.

Paketversion steigt auf **1.3.0**. Auswertung später über die Admin-Ansicht
`/api/admin/panel-diag`.

---

## 5. Tests

**Server** (`tests/test_traffic_api.py`, neu):

- Momentaufnahme enthält nach einem Poll-Zyklus alle Nicht-FRS-Piloten und **keinen** FRS.
- Einträge ohne Koordinate fallen raus.
- Radiusfilter: ein Flugzeug knapp innerhalb ist dabei, eins knapp außerhalb nicht.
- Sortierung nach Entfernung, Kappung bei 60.
- Leere/veraltete Momentaufnahme → `{"age": null, "traffic": []}` mit Status 200.
- Ungültiges `lat`/`lon`/`r` → 422.

**Frontend** (`tests/test_vr_panel.py`, ergänzt — statische Quellprüfungen wie bisher):

- Die Höhen-Formatierung existiert als **eine** Funktion und wird sowohl für Friesen als
  auch für Fremde benutzt (keine zweite, abweichende Kopie).
- Die Label-Regel prüft „unter 10 000 **oder** Friese", nicht nur eines von beidem.
- Der Verkehrs-Layer wird vor dem Bau der Layers-Control hinzugefügt (die OpenAIP-Falle).
- Der Verkehr wird ausschließlich im Sekundentakt bewegt — keine `setLatLng` auf
  Verkehrs-Markern außerhalb von `_naviTakt`.
- `_verkehrRoh` wird nur bei geänderten Koordinaten mit neuem Zeitstempel beschrieben.
- Unterhalb der Zoom-Schwelle wird nicht abgefragt.
- Die Sonde ist auf drei Messpunkte begrenzt und vollständig in `try/catch`.

**Ehrlichkeit über die Grenze dieser Tests:** Für JavaScript gibt es in diesem Projekt
keine Testumgebung — `tests/test_vr_panel.py` prüft den Quelltext, nicht sein Verhalten.
Eine Python-Nachbildung der Label-Regel wäre keine Absicherung, sondern eine zweite Regel,
die mit der ersten auseinanderlaufen kann. Stattdessen:

- Die Label-Formatierung wird in **genau eine** JS-Funktion `_verkehrLabel(p, istFriese)`
  gelegt, deren Grenzwert (`10000`) und FL-Formel statisch geprüft werden.
- Ihr Verhalten wird **einmal im Browser gemessen** — mit den Grenzfällen 0, 9999, 10000,
  10499 und 10500 sowie je einem Friesen und einem Fremden über und unter der Grenze.

**Ebenfalls einmalig im Browser zu messen:** dass das Label bei Track-up aufrecht steht —
über `getScreenCTM()`, wie unter 3.3 beschrieben, nicht über das eigene `transform` des
Elements.

## 6. Mitzuführende Dokumentation

- `README.md` — Kartenabschnitt: die neue Ebene und was sie zeigt.
- `docs/api.md` — `GET /api/traffic` mit Parametern, Grenzen und Antwortformat.
- `docs/architecture.md` — Abschnitt zur Momentaufnahme im Poller und zur Trennung
  „Rohwert / gezeichnete Position" für den Fremdverkehr.
- `docs/efb-panel-debugging.md` — der neue `panel_diag`-Typ `traffic-sonde` und wie er zu
  lesen ist.
- `app/CHANGELOG.json` — neuer Eintrag. **`highlight` bleibt `false`** — das setzt
  ausschließlich der Nutzer.

## 7. Was bewusst wegbleibt

Keine Historie des Fremdverkehrs, keine Kollisions- oder Annäherungswarnung, keine
Controller-/ATC-Positionen, keine Bodenfahrzeuge, keine Filterung nach Flugregeln (VFR/IFR),
kein Anklicken eines Fremden zum Verfolgen, keine Tracks hinter Fremdverkehr.

## 8. Risiken

- **Marker-Menge in Coherent GT.** Sechzig Verkehrs-Marker plus Labels sind deutlich mehr
  DOM als heute. Die Zoom-Schwelle und die Kappung bei 60 sind die Gegenmittel; sollte das
  Kniebrett trotzdem träge werden, ist der nächste Hebel eine niedrigere Kappung speziell
  für das Panel, nicht ein Umbau der Anzeige.
- **Das Label könnte mitdrehen** (s. 3.3). Fallback ist beschrieben und getestet
  entscheidbar.
- **Die Sonde läuft im Simulator.** Deshalb dreimalig, gekapselt und selbstbegrenzt.
