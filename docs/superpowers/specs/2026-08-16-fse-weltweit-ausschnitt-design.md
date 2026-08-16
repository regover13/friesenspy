# FSE weltweit über Ausschnitt-Endpunkte — Design

**Stand 16.08.2026.** Ersetzt den Umstellungsteil von `docs/fse-daten-weltweit.md` (dessen
Bestandsaufnahme bleibt gültig, dessen Lösungsskizze wird hier präzisiert und an zwei Stellen
korrigiert).

---

## 1. Ausgangslage

Die FSE-Ebenen zeigen heute **2.335 europäische Plätze** aus zwei statischen Dateien unter
`app/static/data/`. Der Browser lädt sie beim Einschalten der Ebene vollständig — 582 KB roh,
193 KB gzip — und hängt anschließend **4.670 Objekte** dauerhaft in die Karte. Leaflet setzt
jeden Pfad bei jeder Kartenbewegung neu, auch die unsichtbaren. Am 15.08.2026 hat das die
Karte am laufenden Bild zum Stehen gebracht; abgefangen wurde es mit einem Canvas-Renderer und
Beschriftungen nur im Sichtbereich — Pflaster auf einer Ebene, die zu viel enthält.

Seit dem 16.08.2026 liegen die **Weltdaten** im Repo (`app/data/fse/`, 23.780 Plätze,
2,58 MB + 3,18 MB). Sie bloß gegen die Europadateien zu tauschen würde die Karte lahmlegen.

**Ziel:** Der gesamte Weltbestand ist verfügbar, und der Browser lädt trotzdem weniger als
heute — im MSFS-Kniebrett (Coherent GT) messbar weniger.

---

## 2. Der Bezugspunkt ist der Kartenausschnitt, nicht das Flugzeug

Geprüft wurde, den Ausschnitt an der Flugzeugposition festzumachen (Reichweite ~1000 NM).
Gemessen ab Wangerooge:

| Bezugspunkt | Plätze | Nutzlast |
|---|---|---|
| heute, Europa fest | 2.335 | 582 KB |
| Radius 1000 NM ums Flugzeug | 2.019 | 489 KB |
| Kartenausschnitt z10 (51 km auf 53,8° N) | 14 | 1,5 KB |

Ein Flugzeug-Radius, der die Reichweite abdeckt, ist praktisch wieder ganz Europa — er spart
nichts. Der Kartenausschnitt ist der um zwei Größenordnungen stärkere Filter, und bei
eingeschalteter Moving Map fällt er ohnehin mit der Flugzeugposition zusammen (die Karte folgt
dem Flugzeug, `index.html:8204`).

**Entscheidung:** Kartenmitte + Radius, wie `/api/traffic`.

---

## 3. Die Begrenzung: ein Punktebudget

Der Radius allein begrenzt die Datenmenge **nicht** — die Flugplatzdichte tut es. Derselbe
150-km-Ausschnitt kostet gemessen:

| Ort | Plätze | Zonen | Zonen-Punkte |
|---|---|---|---|
| Nordatlantik | 0 | 3 | 26 |
| Sahara | 0 | 4 | 31 |
| Wangerooge | 75 | 90 | 631 |
| London | 100 | 117 | 821 |
| **New York** | **359** | **389** | **2.719** |

Und die Last verteilt sich ungleich auf die beiden Ebenen. Ein Platz ist ein `CircleMarker`
mit **1 Punkt**, eine Zone ein Polygon mit **im Mittel 7 Punkten** (max 21). Bei New York z8
stellen die Zonen damit **88 %** der Zeichenlast, die Plätze 12 %. Ein Deckel auf Stückzahlen
würde beide gleich behandeln und die falsche Ebene schonen.

**Entscheidung:** Gedeckelt wird in **Punkten**, je Ebene getrennt.

| Konstante | Wert | Bedeutung |
|---|---|---|
| `_FSE_MAX_PUNKTE_PLAETZE` | 250 | ein Platz zählt 1 |
| `_FSE_MAX_PUNKTE_ZONEN` | 900 | eine Zone zählt ihre Eckenzahl |
| `_FSE_MAX_KM` | 250 | Obergrenze für `r`, wie beim Verkehr |
| `_FSE_MIN_ZOOM` | 6 | darunter kein Abruf (Begründung unten) |

Abgeschnitten wird nach Entfernung, das Nächstgelegene zuerst. Gemessene Wirkung:

| Lage | Plätze | Zonen | Deckel greift? |
|---|---|---|---|
| Wangerooge z10 | 14 | 149 Pkt | nein |
| New York z10 | 50 | 502 Pkt | nein |
| New York z9 | 271 → 250 | 2.166 → 900 Pkt | ja |
| **Nordatlantik, jeder Zoom** | 0 | **26 Pkt** | **nie** |

Damit ist die Ozean-Anforderung erfüllt: Eine Zelle mit 7 Ecken kostet 7 von 900 Punkten und
ist auf jeder Zoomstufe da, weil dort nichts mit ihr um das Budget konkurriert. Eine feste
Zoomschwelle für die Zonen ist deshalb **nicht** nötig — das Budget tut ortsabhängig, was eine
Schwelle pauschal täte.

Wo der Deckel greift, sieht der Nutzer eine **Scheibe statt eines vollen Rechtecks**. Dieselbe
Entscheidung trifft der Verkehr bereits, mit derselben Begründung (`index.html:4605`).

Davon zu trennen ist `_FSE_MIN_ZOOM = 6` — kein Dichteregler, sondern ein Boden gegen sinnlose
Anfragen: Unterhalb z6 macht die Kappung von `r` auf 250 km aus jeder Antwort einen Punkt in
der Mitte einer Kontinentansicht. Ab z6 ist jeder Fall abgedeckt, in dem die Ozean-Zelle
handlungsrelevant wäre.

---

## 4. Server: neues Modul `app/fse.py`

Beide Dateien werden **einmal beim Start** gelesen (aus `lifespan`, `main.py:210`) und an
`app.state.fse` gehängt.

**Plätze** als Dicts: `{icao: {"lat", "lon", "name", "msfs", "rwy", "surface", "elev"}}`.
Sie werden nach Entfernung gefiltert und sortiert, dafür braucht es die Zahlen.

**Zonen** als schlichte Punktlisten, dazu eine Bounding-Box-Tabelle
`{icao: (latmin, latmax, lonmin, lonmax)}` und die Eckenzahl.

Erwogen und **verworfen** war, die Zonen als vorserialisierte JSON-Zeichenketten zu halten und
die Antwort per Verkettung zu bauen. Der Gedanke war, den Speicher zu drücken; gemessen tut er
das Gegenteil:

| Haltung | dauerhaft gehalten (`VmRSS`, nach `gc` und `malloc_trim`) |
|---|---|
| Zonen als Listen | **50,8 MB** |
| Zonen vorserialisiert | **55,3 MB** |

Der Grund: `json.load` baut die Listenstruktur ohnehin, bevor irgendetwas daraus abgeleitet
werden kann. Die Zeichenketten kommen also *obendrauf*, und der freigegebene Listenspeicher
geht nicht ans Betriebssystem zurück (mit `malloc_trim` gegengeprüft: 56,9 → 55,3 MB, der Rest
bleibt im Arena-Verschnitt). Die Vorserialisierung kostet damit 4,5 MB, statt 37 zu sparen.

Ihr verbliebener Vorteil wäre gespartes Serialisieren je Anfrage — das ist neben dem linearen
Durchlauf über 23.780 Einträge (s. unten) nicht messbar und den handgebauten JSON-Rumpf nicht
wert.

**Der Container wächst um 49,7 MB** (141 → ~191), Ladezeit 0,5 s. Das ist der ehrliche Preis
dafür, den Weltbestand im Speicher zu halten, und auf einer Maschine mit 11,7 GB unbedenklich.

**Nachtrag 16.08.2026 (Review-Fund):** Dieser Wert gilt nur, weil die Zweig-Korrektur
unveränderte Punktlisten **durchreicht**. Baut sie bedingungslos neu — die erste Umsetzung tat
das —, entstehen 23.780 frische Listenstrukturen, während die Rohdaten noch leben, und der
Bedarf steigt auf **70,7 MB**. 21 MB für zwei geänderte Zonen.

### Längen jenseits der Datumsgrenze

36 Zonen tragen Koordinaten außerhalb [−180, 180]. **34 davon sind durchgehend** (`NFNA`
175,98 → 181,65) und zeichnen sich über die Grenze korrekt — sie dürfen **nicht** normalisiert
werden, das machte aus jeder ein Band quer über die Karte.

Echte Bänder ziehen genau **zwei**: `CYLT` (Alert) mit 342° und `NZPG` (McMurdo) mit 295°
Längenspanne — ihre Ecken liegen in verschiedenen Zweigen. Beim Laden wird deshalb jedes
Polygon auf den Zweig seiner **ersten Ecke** gezogen (`p[1] − 360·round((p[1] − basis)/360)`).
Das ändert nachweislich nur diese zwei und lässt die 34 unangetastet.

**Zonen werden über den Bbox-Schnitt gefiltert, nicht über die Position ihres Flugplatzes.**
Die Zonen sind Voronoi-Zellen: Median 53 km Diagonale, p99 **1.348 km**, max **14.127 km**
(`NZPG` — die allerdings als Polzelle verworfen wird, s. o.; größte ausgelieferte: `SCIP`,
6.694 km).

> **Korrektur 16.08.2026 (Review).** Hier stand: „nach Flugplatzposition gefiltert fiele sie
> genau dann heraus, wenn sie gebraucht wird". Das ist **falsch**. Die umschließende Zelle
> gehört per Voronoi-Definition dem nächstgelegenen Flugplatz und stünde auch nach
> Flugplatzentfernung ganz vorn (an 131 von 131 geprüften Punkten bestätigt). Der echte Grund
> für die Bbox: Sie hält auch die großen **Nachbar**zellen im Bild, deren Flugplatz weit
> außerhalb liegt. Belegt ist dagegen der Vergleich gegen das Ausschnitts-**Rechteck** — dort
> hätte jede schneidende Zone Abstand 0, und der Deckel entschiede alphabetisch.

**Kein exakter Polygon-Schnitt.** Geprüft, ob die Bbox nennenswert überliefert:

| Ort | Bbox-Treffer | echte Treffer |
|---|---|---|
| Wangerooge z8 | 90 | 90 |
| New York z8 | 389 | 389 |
| Nordatlantik z8 | 3 | 2 |

Der Test spart eine Zone. Er entfällt — nicht wegen seiner Kosten (er liefe über 130–390
Kandidaten und wäre damit Rauschen), sondern weil er nichts bewirkt.

**Beide Endpunkte sind `def`, nicht `async def`.** Ein Anfragepaar kostet rund 10–14 ms, weil
beide Filter linear über alle 23.780 Einträge laufen. In einer Koroutine blockierte das den
Event-Loop und damit auch `/api/sse`; als synchrone Funktion schickt FastAPI sie in den
Threadpool. Aus demselben Grund wird das Ausschnitt-Rechteck **einmal vor der Schleife**
gebildet und durchgereicht, statt es je Zone samt `cos`/`radians` neu zu berechnen.

**Die Sortierung für den Zonen-Deckel geht über den Abstand des Ausschnitts zur Bbox**, nicht
zum Zonenmittelpunkt — was den Ausschnitt umschließt, hat Abstand 0 und ist immer dabei.

**Kein Dockerfile-Eingriff nötig:** `COPY app/ ./app/` zieht `app/data/fse/` mit; die
Weltdateien liegen bereits im laufenden Container (geprüft am 16.08.2026).

---

## 5. Die zwei Endpunkte

```
GET /api/fse/airports?lat=&lon=&r=   →  {"plaetze": {ICAO: {...}}, "gekappt": bool}
GET /api/fse/zones?lat=&lon=&r=      →  {"zonen":   {ICAO: [[lat,lon], ...]}, "gekappt": bool}
```

Getrennt, weil die beiden Ebenen einzeln schaltbar sind — wer nur die Landeflächen anhat, soll
die Plätze nicht mitladen. (Heute lädt `_fseLaden` immer beides, unabhängig davon, welcher
Haken gesetzt ist.)

Parameter wie bei `/api/traffic` (`main.py:673`): `lat` ∈ [−90, 90], `lon` ∈ [−180, 180],
`r` ∈ [1, 250] km. `gekappt` meldet, ob der Deckel gegriffen hat — es ist die Grundlage für
einen späteren Hinweis in der Oberfläche und macht den Effekt in Tests prüfbar.

Anmeldung: kein Sonderweg, verhält sich wie `/api/traffic` und gehört **nicht** in
`_GATE_ALLOW_PREFIXES`.

Beide Antworten entstehen als gewöhnliche Dicts; FastAPI serialisiert sie. Kein handgebauter
JSON-Rumpf — s. die verworfene Vorserialisierung in §4.

**Kompression:** Das nginx-gzip vom 15.08.2026 deckt `application/json` bereits ab, die
Antworten kommen komprimiert an. Keine weitere Arbeit.

---

## 6. Frontend

### 6.1 Auslöser: zurückgelegte Strecke, nicht `moveend`

Die naheliegende Übernahme von `map.on('moveend', … if (!_naviSelbstBewegt) …)` (`index.html:4570`)
wäre ein Fehler: Bei eingeschalteter Moving Map bewegt die Karte sich **selbst**, die Wache
greift also immer. Beim Verkehr ist das folgenlos, weil sein 15-Sekunden-Takt als zweite Quelle
läuft. Die FSE-Ebene hat keinen Takt (die Daten ändern sich nicht) — sie würde im Kniebrett
während des ganzen Fluges nie nachladen.

**Stattdessen:**

| Konstante | Wert | Bedeutung |
|---|---|---|
| `_FSE_RAND` | 1.25 | abgerufen wird das 1,25-fache des Sichtradius |
| `_FSE_NACHLADEN_ANTEIL` | 0.2 | neuer Abruf nach 0,2 × **abgerufenem** Radius |

Der Anteil rechnet gegen den abgerufenen Radius, nicht gegen den sichtbaren — deshalb 0,2 und
nicht 0,25: 0,2 × 1,25 R ergibt genau die Reserve von 0,25 R, die der Rand bereitstellt. Mit
0,25 bliebe zwischen 0,25 R und 0,3125 R zurückgelegter Strecke ein Streifen am vorderen
Bildrand ohne Daten. Ein Zoomwechsel löst immer aus.

Praktische Wirkung: Platzrunden über dem Feld = **null Anfragen**. Reiseflug 120 kt bei 31 km
Sichtradius = ein Abruf alle ~100 Sekunden, je rund 1 KB.

`_naviSelbstBewegt` wird nicht gebraucht, ein Takt-Timer ebenfalls nicht.

Beibehalten aus dem Verkehrsmuster: die Sichtbarkeitswache (`_istSichtbar`, ein Abruf auf einer
verdeckten Karte ist Arbeit ohne Wirkung) und der stille `catch` (im Kniebrett ist ein
Netzabriss keine Seltenheit).

### 6.2 Nachführen: Abgleich statt Neuzeichnen

Der Browser hält je Ebene eine Tabelle `ICAO → Layer`. Jede Antwort ist die vollständige
Wahrheit für den aktuellen Ausschnitt:

- in der Antwort, nicht in der Tabelle → zeichnen
- in der Tabelle, nicht in der Antwort → entfernen
- in beiden → **unangetastet lassen**

Der dritte Fall ist der wichtige: Ein vollständiges Neuzeichnen bei jeder Bewegung ließe die
permanenten ICAO-Beschriftungen flackern. Beim Ausschalten einer Ebene wird ihre Tabelle
geleert.

Fliegt der Nutzer dieselbe Strecke zurück, werden die Objekte erneut übertragen. Ein Cache
lohnt bei 1–4 KB je Abruf nicht — er würde genau den Speicherberg wieder aufbauen, den diese
Umstellung abträgt.

### 6.3 Was entfällt und was bleibt

`_fseGeladen` (das Einmal-Flag) und die beiden `_FSE_*_URL`-Konstanten entfallen.

**Der Canvas-Renderer (`index.html:4127`) bleibt.** Er wurde für 4.670 Objekte gebaut; bei
wenigen hundert ist er nicht mehr zwingend, aber weiterhin die günstigere Wahl im Panel — und
ein Ausbau wäre eine Änderung ohne Anlass.

`_labelsImSichtbereich` und die Zoom-Wachen bleiben ebenfalls. Sie werden durch den Ausschnitt
weitgehend gegenstandslos, kosten aber nichts und tragen den Fall, dass jemand den Deckel
später anhebt.

---

## 7. Panel-Diagnose: Canvas messen

`docs/efb-panel-debugging.md` hält fest: „Ein in Chrome geprüfter Fix ist **nicht** verifiziert,
solange er nicht im Panel gemessen wurde." Der Canvas-Renderer läuft seit dem 15.08.2026
produktiv und ist in Coherent GT **nie gemessen** worden; die Selbstdiagnose prüft CSS,
Glyphen, Sprites und Kacheln, aber kein Canvas.

Neues Feld `canvas` im Diagnosebericht (neben `sprites`, `index.html:408`):

- `kontext` — liefert `getContext('2d')` überhaupt ein Objekt?
- `zeichnet` — ein Testpfad wird gezeichnet und per `getImageData` auf gesetzte Pixel geprüft

Der Sprite-Fall ist die Vorlage: Dort scheiterte die frühere Messung daran, dass sie den Rahmen
statt des Inhalts maß. Ein `<canvas>` existiert immer; die Frage ist, ob etwas darin ankommt.

Damit beantwortet der nächste Panel-Start die Frage von selbst, ohne dass jemand am Simulator
sitzen muss.

---

## 8. Aufräumen

- `app/static/data/fse_airports_eu.json` löschen
- `app/static/data/fse_zones_eu.json` löschen
- `scripts/fse_zuschnitt.py` löschen. `scripts/fse_daten.py --europa` erzeugt denselben
  Zuschnitt, schreibt ihn aber nach `app/data/` statt nach `app/static/data/` — wer den
  Zuschnitt je zurückholt, sucht sonst im falschen Verzeichnis.
- README: prüfen. Die Wendung „rund 2 300 europäischen Plätzen" steht **nicht** dort, sondern
  in `app/CHANGELOG.json` als historischer Release-Eintrag — der bleibt unangetastet.
- `docs/fse-daten-weltweit.md`: Umstellungsteil auf diese Spec verweisen lassen
- `docs/api.md`: die zwei neuen Endpunkte
- `docs/architecture.md`: `app/fse.py` und die Speicherhaltung

**Nicht** gelöscht wird `app/static/data/platzrunden_de.geojson` — die Platzrunden bleiben
statisch. Sie sind 412 Objekte, 39 KB gzip, und haben das Dichteproblem nicht.

---

## 9. Tests

Erweitert wird `tests/test_fse.py` (heute 21 Tests, prüft die alten Dateien und die
Frontend-Konstanten):

**Server:**
- Startladen füllt `app.state.fse`; Plätze- und Zonenzahl stimmen mit den Dateien überein
- `/api/fse/airports` liefert bei Wangerooge z10 die erwarteten Plätze, keine fernen
- `r` außerhalb [1, 250] → 422
- Deckel: eine Anfrage bei New York z9 liefert höchstens 250 Plätze und meldet `gekappt: true`
- Zonen-Budget: höchstens 900 Punkte, `gekappt: true`
- **Ozean-Fall:** Nordatlantik liefert die umschließende Großzelle — der Test, der die
  Sortierung nach Bbox-Abstand statt nach Flugplatzentfernung festnagelt
- **Zweig-Korrektur:** `CYLT` und `NZPG` haben nach dem Laden höchstens 180° Längenspanne,
  `NFNA` behält seine Ecken jenseits 180 unverändert

Die Testfixture darf **nicht** über `with TestClient(app)` laufen. Der Lifespan liest
`SECRET_KEY` (ohne Default), ruft `init_db` auf dem **Produktionspfad**
`/opt/friesenspy/data/friesenspy.db` und startet den VATSIM-Poller gegen die echte API.
Maßgeblich ist das Hausmuster aus `tests/test_traffic_api.py:79` — `TestClient` ohne `with`,
`get_settings` per `monkeypatch` ersetzt, und `app.state.fse` direkt gesetzt.

**Frontend (Node mit Leaflet-Attrappen, wie die bestehenden):**
- kein Abruf unterhalb `_FSE_MIN_ZOOM`
- kein Abruf, solange die Mitte weniger als `_FSE_NACHLADEN_ANTEIL × r` gewandert ist
- Zoomwechsel löst immer aus
- Abgleich: ein ICAO, der in zwei aufeinanderfolgenden Antworten steht, wird **nicht** neu
  gezeichnet — der Test gegen das Beschriftungsflackern
- ein ICAO, der wegfällt, verschwindet aus der Karte

**Panel-Diagnose:**
- `canvas.kontext` und `canvas.zeichnet` stehen im Bericht

Die Tests gegen die gelöschten Europadateien entfallen mit ihnen.

---

## 10. Bewusst nicht gemacht

| Verworfen | Grund |
|---|---|
| Flugzeugposition als Bezugspunkt | gemessen: 1000 NM sind wieder ganz Europa |
| exakter Polygon-Schnitt am Server | gemessen: spart genau eine Zone |
| Zonen vorserialisiert halten | gemessen 4,5 MB **teurer** — `json.load` baut die Listen ohnehin |
| pauschale Normalisierung der Längen auf ±180 | machte aus 34 heilen Zonen Bänder quer über die Karte |
| Client-Cache bereits geladener ICAOs | baut den Speicherberg wieder auf, den die Umstellung abträgt |
| feste Zoomschwelle für Zonen | das Punktebudget entscheidet ortsabhängig und damit richtig |
| Takt-Timer wie beim Verkehr | die Daten ändern sich nicht |
| Deckel auf Stückzahlen | eine Zone kostet das Siebenfache eines Platzes |

**Bekannter Rest — das Abfragefenster rechnet nicht über die Datumsgrenze.** `_rechteck`
liefert bei Länge 179,5 den Ausschnitt `178 … 180`; was westlich von −180 liegt, fällt weg.
Betroffen sind **14 der 23.780 Plätze** (0,06 %): 8 Fiji/Tonga/Wallis, 3 Neuseeland/Chatham,
2 Marshallinseln/Wake, 1 Aleuten. Es sieht nicht kaputt aus, es fehlt still — wer in Nadi
startet, hält die leere Osthälfte für den Datenbestand. Der saubere Schnitt bräuchte zwei
Rechtecke an der Grenze und einen entsprechend geteilten Bbox-Abstand; **Nutzer-Entscheidung
16.08.2026: nicht in dieser Umstellung.** Die zwei Bandzonen aus §4 werden trotzdem behoben,
weil das drei Zeilen sind.

**Offen, nicht Teil dieser Umstellung:** Ob der Deckelwert im Panel trägt. Coherent GT wird
laut `main.py:665` „ab ein paar hundert Elementen zäh" — das ist für DOM-Marker gemessen, nicht
für Canvas. Die Werte in Abschnitt 3 sind Konstanten; die Panel-Messung aus Abschnitt 7 liefert
die Grundlage, sie zu korrigieren.
