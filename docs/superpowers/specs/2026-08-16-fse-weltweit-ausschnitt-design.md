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

**Zonen** als **vorserialisierte JSON-Zeichenketten** je ICAO, dazu eine Bounding-Box-Tabelle
`{icao: (latmin, latmax, lonmin, lonmax)}` und die Eckenzahl. Gemessen:

| Haltung | Speicher |
|---|---|
| beide Dateien als Python-Objekte | **42 MB** |
| Zonen als fertige JSON-Strings | **5 MB** |

Der Container liegt heute bei 141 MB — 42 MB wären eine Steigerung um 30 % für Daten, die pro
Anfrage ohnehin nur durchgereicht werden. Die Antwort entsteht dann durch
Zeichenketten-Verkettung statt durch Serialisierung je Anfrage.

**Zonen werden über den Bbox-Schnitt gefiltert, nicht über die Position ihres Flugplatzes.**
Die Zonen sind Voronoi-Zellen: Median 53 km Diagonale, p99 **1.348 km**, max **14.127 km**.
Die große Ozeanzelle, in der man steht, hat ihren Flugplatz womöglich 600 km entfernt — nach
Flugplatzposition gefiltert fiele sie genau dann heraus, wenn sie gebraucht wird.

**Kein exakter Polygon-Schnitt.** Geprüft, ob die Bbox nennenswert überliefert:

| Ort | Bbox-Treffer | echte Treffer |
|---|---|---|
| Wangerooge z8 | 90 | 90 |
| New York z8 | 389 | 389 |
| Nordatlantik z8 | 3 | 2 |

Der teure Test spart eine Zone. Er entfällt.

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

Die Zonen-Antwort wird als `Response(content=..., media_type="application/json")` aus den
vorserialisierten Stücken zusammengesetzt — sonst wäre die Vorserialisierung wirkungslos.

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
| `_FSE_NACHLADEN_ANTEIL` | 0.25 | neuer Abruf, wenn die Mitte ein Viertel Radius gewandert ist |

Der Rand deckt genau die Strecke ab, die bis zum nächsten Abruf zurückgelegt wird — der
sichtbare Bereich hat nie ein Loch. Ein Zoomwechsel löst immer aus.

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
- `scripts/fse_zuschnitt.py` löschen (`scripts/fse_daten.py --europa` kann dasselbe)
- README: „rund 2 300 europäischen Plätzen" → 23.780 weltweit
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
- Zonen-Antwort ist gültiges JSON (die Zeichenketten-Verkettung ist die Fehlerquelle)

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
| exakter Polygon-Schnitt am Server | gemessen: spart eine Zone, kostet CPU je Anfrage |
| Client-Cache bereits geladener ICAOs | baut den Speicherberg wieder auf, den die Umstellung abträgt |
| feste Zoomschwelle für Zonen | das Punktebudget entscheidet ortsabhängig und damit richtig |
| Takt-Timer wie beim Verkehr | die Daten ändern sich nicht |
| Deckel auf Stückzahlen | eine Zone kostet das Siebenfache eines Platzes |

**Offen, nicht Teil dieser Umstellung:** Ob der Deckelwert im Panel trägt. Coherent GT wird
laut `main.py:665` „ab ein paar hundert Elementen zäh" — das ist für DOM-Marker gemessen, nicht
für Canvas. Die Werte in Abschnitt 3 sind Konstanten; die Panel-Messung aus Abschnitt 7 liefert
die Grundlage, sie zu korrigieren.
