# Mithören und Meldepunkte — Design

**Stand:** 16.08.2026 · **Betrifft:** `app/static/index.html`, `app/main.py`, neu `app/vrp.py`,
`scripts/vrp_daten.py` · **Quelle:** die beiden Einträge in `docs/offene-aufgaben.md`
(Nutzer, 16.08.2026) · **Ziel:** beides in **einer** Version — Vorschlag **v13.7.0**

Zwei Aufgaben, ein Release. Sie haben nichts miteinander zu tun außer dem Ort: beide sitzen in
der Live-Ansicht, beide fassen `index.html` an. Genau deshalb gehören sie in eine Fassung —
zweimal hintereinander dieselbe Datei umzubauen und zweimal zu deployen kostet mehr, als es
bringt. Teil A ist klein und sicher, Teil B ist der Aufwand; die Reihenfolge der Umsetzung
steht in Abschnitt 4.

---

## 1. Teil A — Mithören über `listen.vatsim.net`

### 1.1 Was gebaut wird

Hinter dem Callsign in der Live-Ansicht steht ein **Lautsprechersymbol**, das auf
`https://listen.vatsim.net/live/<CALLSIGN>` zeigt. Ein Klick öffnet einen neuen Tab, und dort
läuft die Frequenz, auf der der Pilot gerade ist. Vorbild ist
[vatsim-radar.com](https://vatsim-radar.com) („Listen as \<Callsign\>").

### 1.2 Die URL ist geprüft, nicht geraten

Gemessen am 16.08.2026 gegen die ausgelieferte Anwendung
(`https://listen.vatsim.net/assets/main-gP8x-Jvh.js`):

```js
const Le = "afv_listen_pending_live_cs";
let z = null;
(function () {
  const e = /^\/live\/([^/]+)\/?$/i.exec(window.location.pathname);
  e ? (z = decodeURIComponent(e[1]).toUpperCase(),
       sessionStorage.setItem(Le, z),
       history.replaceState({}, "", "/" + window.location.search))
    : z = sessionStorage.getItem(Le) || null;
})();
```

Daraus folgt vier Dinge, die für unsere Umsetzung zählen:

| Beobachtung | Folge für uns |
|---|---|
| `^/live/([^/]+)/?$`, Wert wird `decodeURIComponent`-t | Callsign gehört **URL-kodiert** in den Pfad (`encodeURIComponent`) |
| Wert wird intern auf Großschreibung gezogen | Unsere Groß-/Kleinschreibung ist gleichgültig — wir schreiben trotzdem groß, wie überall |
| Der Wunsch überlebt in `sessionStorage` und der Pfad wird auf `/` zurückgesetzt | Der Link funktioniert auch, wenn erst noch der **VATSIM-Login (OAuth)** dazwischenkommt: nach dem Rücksprung wird derselbe Pilot aufgeschaltet |
| `if (!s.callsigns.some(n => n.callsign === e)) { x(`${e} is not currently online`, "error"); return }` | Fällt der Pilot durch, gibt es eine saubere Fehlermeldung statt einer leeren Seite — **wir werden sie aber kaum je sehen**, s. unten |

`GET /live/DLH123` liefert HTTP 200 (die Anwendung selbst), `GET /live/` erwartungsgemäß 404.
Damit ist die offene Frage aus der Aufgabenliste („ob der Stream für jeden Piloten existiert,
ist ungeprüft") beantwortet, soweit sie sich von außen beantworten lässt: Die **Route** gilt für
jeden Callsign.

**Die Fehlermeldung ist nicht unser Normalfall** (Nutzer-Einwand, 16.08.2026): Wir zeigen das
Symbol nur bei Piloten, die VATSIM uns gerade als online gemeldet hat. Genau die stehen auf der
Gegenseite fast immer auch in der Liste. Zwei Lücken bleiben, beide schmal:

- Die Liste dort ist die Sicht des **Audio-Netzes** (AFV, per WebSocket gepusht:
  `{type:"callsigns", data:[…]}`), nicht der VATSIM-Datenfeed. Wer bei VATSIM steht, aber keine
  Tonverbindung hat, fehlt.
- Zwischen unserem Abruf (15 s) und dem Klick vergeht Zeit. Loggt der Pilot dazwischen aus,
  greift dieselbe Meldung — bzw. nach dem Login-Rücksprung die Schwester dazu,
  `„… is no longer online"`.

**Der eigentliche Alltagsfall ist Stille, und das ist kein Fehler.** Zu hören gibt es nur, was
gerade gesprochen wird: Steht kein Lotse auf der Frequenz oder redet niemand, bleibt es still.
Das gehört so in den Changelog-Text — sonst liest sich der erste stumme Klick als Defekt.
Ungeprüft bleibt allein die Tonqualität; die prüft der erste Friese, der es benutzt.

**Zu wissen, bevor jemand fragt:** Mithören setzt einen **VATSIM-Login auf listen.vatsim.net**
voraus (OAuth mit der eigenen CID). Wir bauen dafür nichts; die Gegenstelle regelt es. Das
gehört aber in den Changelog-Text, sonst liest sich der erste Klick als Fehler.

### 1.3 Wo das Symbol steht

| Ort | Symbol? | Warum |
|---|---|---|
| Live-Tabelle, Spalte **Callsign** (`index.html:6661`) | **ja** | Das ist die Live-Ansicht aus der Aufgabe |
| Karten-Popup eines Friesen (`buildPopupHtml`, `index.html:9823`) | **ja** | Derselbe Pilot, derselbe Blick — wer auf der Karte klickt, soll nicht erst in die Tabelle zurück |
| Flugplan-Fenster (`fp-callsign-title`, `index.html:3611`) | nein | Es öffnet sich **aus** der Tabelle, in der das Symbol schon steht. Zwei Wege zum selben Ziel im selben Klickpfad sind Rauschen |
| Fremdverkehr-Popup (`_verkehrPopup`, `index.html:5716`) | nein (v1) | Dort steht mal ein VATSIM-Callsign, mal gar keines (der Simulator liefert keines). Ein Symbol, das je nach Quelle da ist oder nicht, erklärt sich niemandem — als eigener Schritt nachrüstbar, wenn der Nutzer es will |
| **Kniebrett (MSFS-EFB)** | **nein, ausdrücklich** | Ein externer Link ist dort nutzlos: kein Browser, in den er sich öffnen ließe (Vorgabe aus der Aufgabenliste) |

### 1.4 Umsetzung

Es gibt dafür bereits ein funktionierendes Vorbild im Haus — `airportLinkIcon`
(`index.html:6574`). Es wird nicht neu erfunden, sondern gespiegelt:

```js
// Vorbild: airportLinkIcon(). Abstand als CSS-Rand, NICHT als Leerzeichen im Text -- im
// Kniebrett ist das Symbol ausgeblendet, ein Leerzeichen davor bliebe stehen.
function listenLinkIcon(callsign) {
  const cs = String(callsign || '').toUpperCase();
  if (!cs) return '';
  return '<a href="https://listen.vatsim.net/live/' + encodeURIComponent(cs) + '"'
       + ' target="_blank" rel="noopener" class="listen-link-icon"'
       + ' title="Mithören als ' + escHtml(cs) + '" onclick="event.stopPropagation()">'
       + icon('speaker') + '</a>';
}
```

Dazu gehören genau fünf weitere Handgriffe:

1. **Sprite** `#icon-speaker` in den `<symbol>`-Block (`index.html:3085 ff.`, neben
   `icon-headset`) — Lautsprecher mit Schallwellen, `stroke="currentColor"`, `fill="none"` wie
   alle anderen. `href` **und** `xlink:href` beim `<use>` — das erledigt `icon()` bereits, und
   `test_jedes_use_hat_xlink_fallback` hält dagegen.
   *Nicht* `icon-headset` wiederverwenden: das Headset steht in dieser Anwendung für TeamSpeak
   (`index.html:3333, 3350, 3462, 7685`). Zwei Bedeutungen für ein Symbol ist eine zu viel.
2. **CSS** neben `.airport-link-icon` (`index.html:594`):
   `.listen-link-icon { margin-left: 6px; color: var(--green); }`.
   Die Farbe muss **explizit** hin: `.icon` hat `fill: none`, gezeichnet wird über
   `stroke: currentColor`, und ein globales `a { color: … }` gibt es in diesem Stylesheet nicht
   (nachgesehen: nur `.leaflet-control-zoom a`, `.leaflet-control-attribution a` und
   `#ac-body .hint a` setzen eine Linkfarbe). Ohne Angabe zeichnete der Browser sein
   Standard-Linkblau. Blau (`--green`) ist hier richtig: Das Symbol **ist** ein Link. Das
   Callsign daneben bleibt neutral — `.td-callsign` trägt dazu bereits den Kommentar.
3. **Kniebrett-Wache**: `html.vr-panel .listen-link-icon { display: none; }` in dieselbe Regel
   wie `html.vr-panel .airport-link-icon` (`index.html:1879`). Eine CSS-Regel reicht; die
   Karten-Popups laufen im selben Dokument.
4. **Einbau** an den zwei Stellen aus 1.3: `…${escHtml(cs)}${listenLinkIcon(p.callsign)}`.
5. **`event.stopPropagation()`** ist Pflicht, nicht Kosmetik: In der Live-Tabelle hängen
   Klick-Handler an Zellen (`.td-callsign-link`, `.td-map-btn`, `index.html:6676 ff.`), im
   Popup schließt ein Klick daneben die Blase.

### 1.5 Zusicherungen (Tests)

Neu `tests/test_mithoeren.py`, Quelltext-Zusicherungen nach dem Muster von
`tests/test_aircraft_ui_static.py`:

- Die URL steht genau einmal im Quelltext und lautet `https://listen.vatsim.net/live/`.
- Der Link trägt `target="_blank"` **und** `rel="noopener"`.
- Es gibt eine Regel `html.vr-panel .listen-link-icon { display: none }` — die Kniebrett-Vorgabe
  ist damit nicht nur Absicht, sondern geprüft.
- `.listen-link-icon` setzt `color: var(--green)`.
- `#icon-speaker` existiert als `<symbol>`.

---

## 2. Teil B — Meldepunkte (VRP) groß und deutlich

### 2.1 Der Befund und warum die naheliegende Lösung ausfällt

Die visuellen Meldepunkte des OpenAIP-Layers sind zu klein und zu unauffällig (Nutzer,
16.08.2026). OpenAIP kommt als **Kachel-Layer** (`TILE_AIP_URL`, `index.html:3803`) — fertig
gerenderte PNG. In einem Bild lässt sich eine einzelne Punktart nicht vergrößern. Kein CSS,
kein Leaflet-Parameter ändert daran etwas; `opacity` und `maxZoom` sind alles, was wir haben.

**Es gibt zwei Dinge, die beide „OpenAIP-Schnittstelle nur für Meldepunkte" heißen — und nur
eines davon hilft** (Nutzer-Rückfrage, 16.08.2026):

| | Was zurückkommt | Größe änderbar? |
|---|---|---|
| **Kachel-Endpunkt** `api.tiles.openaip.net/api/data/reporting-points/{z}/{x}/{y}.png` | fertig gezeichnete PNG, nur mit Meldepunkten | **nein** — ein Bild ist ein Bild. Er **trennt** die Meldepunkte vom übrigen Luftraumbild, vergrößert sie aber nicht |
| **Core-API** `api.core.openaip.net/api/reporting-points` | **Koordinaten** als JSON (`geometry.coordinates`, `name`, `compulsory`, `elevation`) | **ja, vollständig** — wir zeichnen selbst, Form, Farbe und Größe sind allein unsere Entscheidung |

Damit ist die Frage beantwortet, und zwar **ohne Restunsicherheit**: Die Vergrößerung hängt
nicht daran, was OpenAIP liefert, sondern daran, *dass* es Koordinaten statt Pixel liefert. Was
ich geprüft habe, ist genau das — Parameter, Felder und Antwortform aus dem OpenAPI-Schema
(Abschnitt 2.2). Was ich **nicht** geprüft habe: eine echte Abfrage mit gültigem Schlüssel; der
liegt nur in `config.env` auf dem VPS, nicht in dieser Sitzung. Offen ist dadurch der
**Datenumfang** (5.2), nicht die Darstellbarkeit. Den Kachel-Endpunkt für Meldepunkte brauchen
wir nach dieser Entscheidung gar nicht mehr (er antwortet mit Phantasie-Schlüssel mit 404 wie
der bekannte Layer, ist also von hier aus ohnehin nicht belegbar).

Für „größer und prominenter" gibt es also genau einen Weg: **eigene Vektordaten, eigene
Symbole**.

**Und genau so ist dieser Entwurf gemeint** (Nutzer-Klarstellung, 16.08.2026): **Die
Kachelkarte bleibt, wie sie ist** — OpenAIP als Luftraumbild, OFM/Satellit/Topo als Untergrund,
unverändert. Darüber blenden wir **nur** die Meldepunkte groß und deutlich ein. Es wird nichts
ersetzt und nichts nachgebaut; die neue Ebene ist ein Zusatz mit eigenem Haken. Der winzige
Punkt im Kachelbild bleibt darunter stehen — er ist Teil des Bildes und nicht wegzuretuschieren
—, aber er verschwindet optisch unter unserem Dreieck. Dasselbe gilt seit jeher für die
Platzrunden, die OFM ebenfalls zeichnet.

### 2.1.1 Könnten wir uns die Kachelkarte gleich ganz selbst zusammenbauen?

Technisch ja. Die Core-API führt zehn Listen-Endpunkte, alle mit denselben Filtern
(`country`, `pos`+`dist`, `bbox`, `page`/`limit`, `fields`):

`/airports` · `/airspaces` · `/navaids` · `/obstacles` · `/hotspots` · `/hang-glidings` ·
`/rc-airfields` · `/rc-airfields/airspaces` · `/special-rules-areas` · `/reporting-points`

**Und es gibt einen handfesten Grund, der dafür spricht** — er ist beim Schreiben dieser Spec
aufgefallen und stand vorher nirgends: Der OpenAIP-Kachel-Layer läuft mit `maxZoom: 14`
(`index.html:6449`), ohne `maxNativeZoom`. Die Karte selbst geht bis 19 (`_KARTE_ZOOM_MAX`).
Oberhalb von Stufe 14 ist das Luftraumbild also **ganz weg** — nicht unscharf, weg. Bei OFM
endet der Luftfahrtinhalt schon bei Stufe 12 (`OFM_NATIVE_MAX_ZOOM`), darüber schaltet der
Auto-Switch auf Satellit. Genau im Anflug, wo man am weitesten hineinzoomt, tragen beide
Kachelquellen nichts mehr. Das ist dieselbe Lücke, für die es die Platzrunden-Ebene schon gibt
— eigene Vektordaten liegen **über jeder Karte und auf jeder Zoomstufe**.

**Trotzdem: nicht jetzt und nicht in einem Stück.** Ein eigener Lufträume-Nachbau ist keine
Datenfrage, sondern Kartografie — Klassen, Unter- und Obergrenzen, Beschriftung, Entzerrung bei
Überlappung, und das alles bei einer Zeichenlast, an der Coherent GT schon bei ein paar hundert
Pfaden zäh wird (deshalb das Punktebudget in `app/fse.py`). Die Kacheln stecken voller
Darstellungswissen, das wir dann selbst hätten.

**Der Weg ist stattdessen: Element für Element, jedes mit eigenem Anlass.** Meldepunkte sind
das erste, weil der Anlass da ist — sie sind zu klein. Die Bauteile aus dieser Spec (Skript →
Abzug im Repo → Ausschnitt-Endpunkt → Ebene mit Merker, Deckel und Attribution) sind bewusst so
geschnitten, dass das nächste Element sie erbt und nur noch Symbol und Popup mitbringt. Wenn
die Meldepunkte im Sim stehen, ist der nächste Kandidat leicht zu benennen — meine Vermutung:
Funkfeuer und Hindernisse, weil beide punktförmig sind und damit denselben Rahmen nutzen.
Lufträume wären der große Brocken und gehören in eine eigene Spec.

### 2.2 Woher die Daten kommen — gemessen, nicht vermutet

| Weg | Ergebnis der Probe (16.08.2026) | Urteil |
|---|---|---|
| Tages-Exporte im GCS-Bucket (`storage.googleapis.com/29f98e10-…/de_rpp.geojson`) | HTTP 400 `UserProjectMissing` — „Bucket is a requester pays bucket" | **fällt aus**: verlangt ein zahlendes Google-Cloud-Projekt |
| Core-API `GET https://api.core.openaip.net/api/reporting-points` | ohne Key HTTP 403 `auth/forbidden`; Schema und Parameter vollständig aus `…/system/specs/v1/schema.json` gelesen | **das ist der Weg** |

Aus dem OpenAPI-Schema, was zählt:

- **Authentifizierung** wie bei den Kacheln: Query-Parameter `apiKey` (alternativ Header
  `x-openaip-api-key`). Sehr wahrscheinlich reicht unser vorhandener `OPENAIP_API_KEY` —
  **Gegenprobe vor der Umsetzung**, siehe 5.1.
- **Filter**: `country` (ISO-2), `pos` + `dist` (Meter), `bbox`, `page`, `limit` (Vorgabe
  1000), `fields`.
- **`bbox` ist ausdrücklich nicht für den laufenden Betrieb gedacht**: „mainly intended for
  export use-cases, not for regular queries because they are very compute intensive. This
  endpoint is rate limited. Once rate limits are hit, the endpoint responds with a 429."
- **Felder je Punkt**: `_id`, `name`, `compulsory` (bool), `country`, `geometry` (GeoJSON
  Point), `elevation` `{value, unit:0=m, referenceDatum:1=MSL}`, `airports` (Liste von
  OpenAIP-Dokument-IDs), `remarks`. Eine Unterscheidung „visuell / enroute" gibt es im
  Antwortschema **nicht** — nur `compulsory` ja/nein.
- **Lizenz: CC BY-NC 4.0** und „Please add a proper attribution link to OpenAIP as data source
  within your application!". Für FriesenSpy (Hobby, nicht kommerziell) unkritisch, die
  Namensnennung ist aber Pflicht — und zwar auch dann, wenn der Kachel-Layer aus ist, der sie
  heute automatisch mitbringt.

### 2.3 Architektur: genau wie FSE, aus denselben Gründen

Der Bestand wird **einmal geholt und im Repo abgelegt**, der Browser bekommt nur den
Ausschnitt. Das ist nicht neu erfunden, sondern das Muster von `app/fse.py` /
`scripts/fse_daten.py` / `/api/fse/airports` — dort steht die Begründung bereits ausgeschrieben
(Spec vom 16.08.2026, „FSE weltweit im Ausschnitt").

Warum hier dasselbe und nicht ein Live-Durchgriff auf OpenAIP:

- **Ratenbegrenzung.** Die API drosselt, das Kniebrett lädt beim Fliegen dauernd nach. Ein
  Durchgriff pro Kartenbewegung ist genau das Verhalten, vor dem die Doku warnt.
- **Der Schlüssel bleibt im Server.** Beim Kachel-Layer geht das nicht anders (die URL steht im
  Browser). Hier geht es anders, also machen wir es anders.
- **Die Daten ändern sich in Monaten, nicht in Minuten.** Ein Abzug, den ein Skript erneuert,
  ist ehrlicher als ein Cache, der so tut, als wäre er live.
- **Es funktioniert im Kniebrett.** Dieselbe Antwortform wie FSE, derselbe Deckel gegen die
  Zeichenlast von Coherent GT.

Konkret:

```
scripts/vrp_daten.py   → holt Seite für Seite (limit=1000, page=n), weltweit (s. 5.2),
                         schreibt app/data/vrp/vrp_welt.json  (im Repo, wie app/data/fse/)
app/vrp.py             → Bestand beim Start lesen, Umkreis schneiden, Punkte deckeln
GET /api/vrp?lat&lon&r → { punkte: [...], gekappt: bool }   (gespiegelt von /api/fse/airports)
index.html             → Ebene „Meldepunkte" in der Ebenen-Auswahl
```

Format je Punkt, bewusst knapp (der Bestand liegt im Speicher, s. `app/fse.py`):
`{ n: Name, y: lat, x: lon, c: 1|0 (meldepflichtig), e: Höhe in ft MSL|null }`.
`airports` (OpenAIP-IDs) und `remarks` fallen weg — die IDs wären ohne einen zweiten
Abzug der Flugplätze nicht auflösbar, und ein Popup mit `60085dd4268e90000eb327ce` hilft
niemandem. `remarks` ist bei den meisten Punkten leer; nachrüstbar, wenn es jemand vermisst.

### 2.4 Darstellung — der eigentliche Auftrag

| Frage | Entscheidung | Begründung |
|---|---|---|
| Symbolform | **Dreieck**, Spitze nach oben | Das ist das Kartenzeichen für Meldepunkte; ein Kreis wäre mit den FSE-Plätzen verwechselbar |
| meldepflichtig / auf Anforderung | **gefüllt** (`compulsory: true`) / **hohl** | Genau die Unterscheidung, die die Quelle hergibt — und die einzige, die im Flug zählt |
| Größe | 11 px bis Zoom 10, 15 px darüber | „größer und prominenter" heißt sichtbar auf Reiseflug-Zoom, nicht bildschirmfüllend im Anflug |
| Farbe | Magenta `#e07be0` mit dunklem Saum (`drop-shadow` ohne Versatz, CSS-Klasse wie `.platzrunde`) | Kartenüblich für Meldepunkte, und im Haus noch frei: Blau `#2d9cdb` ist Klickbarem vorbehalten, Hellblau `#8ab4d8` sind die Platzrunden, Grau die FSE-Landeflächen. Der Saum trägt das Symbol auf Satellit **und** auf hellem CARTO |
| Beschriftung | Name als Dauer-Tooltip ab **Zoom 11**, über `_labelsImSichtbereich` (`index.html:4190`) | Ein Meldepunkt ohne Namen ist nutzlos — man meldet ihn ja beim Namen. Der Helfer bindet Labels nur im Bild; das ist der Fund vom 15.08. gegen die hängende Karte |
| Popup | Name (fett), „meldepflichtig" / „auf Anforderung", Höhe in ft MSL, wenn vorhanden | |
| Untere Zoomgrenze | **9** | Darunter wird jede Region zum Punktteppich — dieselbe Überlegung wie `_PLATZRUNDEN_MIN_ZOOM` |
| Deckel | Punktbudget im Server (`MAX_PUNKTE_VRP`, Startwert 300), gemeldet als `gekappt` | Wie bei FSE: nach Zeichenlast, nicht nach Stückzahl |
| Doppelt mit dem OpenAIP-Kachel-Layer? | **hinnehmen** | Genau wie die Platzrunden, die OFM ebenfalls zeichnet. Wer es sauber will, schaltet OpenAIP ab — beide Haken stehen nebeneinander |

Bedienung wie jede andere Ebene: ein Haken **„Meldepunkte"** in der Ebenen-Auswahl, einsortiert
zwischen `Platzrunden` und `FSE-Landeflächen` (Reihenfolge in `liveOverlays`,
`index.html:9691 ff.` — von der größten zur kleinsten Fläche, der Verkehr bleibt unten).
Merker `friesenspy_vrp` über `_prefSchreib`/`_prefLies`; die Ebene wird **vor** dem Bau der
Layers-Control hinzugefügt, sonst steht der Haken falsch (derselbe Grund wie bei
`_addPreferredAIPLayer` — der Kommentar dort ist der maßgebliche).

**Zwei Fallen, beide schon einmal bezahlt:**

- `L.featureGroup`, nicht `L.layerGroup`: nur erstere feuert `layeradd`, an dem die
  Label-Zoom-Wache hängt (steht bei `_platzrundenGruppe` und `_fsePlaetzeGruppe`).
- **Kein Canvas-Renderer.** Die Live-Karte läuft mit `leaflet-rotate`, und das Plugin trägt
  SVG-Pfade und DOM-Marker, aber nicht den Canvas-Ursprung — der Versatz verdoppelt sich mit
  jeder Zoomstufe (Fund vom 16.08., `index.html:4533 ff.`). Dreiecke also als `L.marker` mit
  `divIcon` oder als SVG-Pfad, **nicht** über `L.canvas()`.

Attribution: `_vrpAttributionAn/Aus` nach dem Muster von `_fseAttributionAn` (`index.html:4839`)
— `L.circleMarker`/`L.marker` bringen keine Attribution mit, anders als `L.TileLayer`.
Text: `<a href="https://www.openaip.net">OpenAIP</a>`. Leaflet zählt gleiche Zeichenketten
intern mit, ein doppelter Eintrag neben dem Kachel-Layer erscheint also nur einmal.

### 2.5 Zusicherungen (Tests)

- `tests/test_vrp.py` (Python): Umkreis-Schnitt und Deckel gegen einen kleinen Kunstbestand —
  gespiegelt von `tests/test_fse.py`; Endpunkt liefert `gekappt: true`, wenn das Budget greift;
  `r` wird serverseitig auf `MAX_KM` begrenzt.
- Quelltext-Zusicherungen für die Ebene: Merker-Schlüssel, `L.featureGroup`, kein `L.canvas`
  in der VRP-Ebene, Attribution wird beim Einschalten gesetzt und beim Ausschalten entfernt.
- `scripts/vrp_daten.py` schreibt **nicht** nach `app/static/` (was dort liegt, wird als Ganzes
  ausgeliefert — die Begründung steht in `scripts/fse_daten.py`).

---

## 3. Was der Nutzer sieht (Changelog-Entwurf v13.7.0)

```json
{
  "version": "13.7.0",
  "date": "2026-08-1X",
  "highlight": true,
  "title": "Mithören und deutliche Meldepunkte",
  "items": [
    "🔊 Hinter jedem Callsign in der Live-Ansicht steht jetzt ein Lautsprecher. Ein Klick öffnet listen.vatsim.net und schaltet auf die Frequenz, auf der dieser Pilot gerade ist. Dafür ist einmal eine Anmeldung mit der eigenen VATSIM-CID nötig. Zu hören ist, was gerade gesprochen wird — steht kein Lotse auf der Frequenz oder redet niemand, bleibt es still. Im Kniebrett erscheint das Symbol nicht: dort gibt es keinen Browser, in dem sich der Link öffnen ließe.",
    "📍 Neue Karten-Ebene „Meldepunkte\": die visuellen Meldepunkte als eigene Dreiecke mit Namen, statt der winzigen Punkte im OpenAIP-Bild. Gefüllt heißt meldepflichtig, hohl heißt auf Anforderung. Ab Zoomstufe 9, der Name ab Stufe 11 — weltweit, und anders als das OpenAIP-Bild auch dann noch da, wenn man ganz hineinzoomt. Datenquelle: OpenAIP."
  ]
}
```

## 4. Reihenfolge und Abnahme

1. **Teil A** zuerst und vollständig (Sprite, Helfer, zwei Einbauorte, CSS, Panel-Regel,
   Tests). Er hängt an nichts und ist danach abgehakt.
2. **Gegenprobe des API-Schlüssels** (5.1). Fällt sie negativ aus, geht Teil A allein als
   v13.6.6 raus, und Teil B wartet auf einen Schlüssel — beides zusammen zu halten, bis eine
   fremde Zugangsfrage geklärt ist, wäre der falsche Weg herum.
3. **Testabzug ziehen** (`--umfang test`, 5.2): damit stehen Skript, Endpunkt und Ebene in
   Minuten statt in einem Weltabzug. Der Weltabzug (`--umfang welt`) kommt zum Schluss, wenn
   nichts mehr am Format geändert wird — und er ist der, der ausgeliefert wird.
4. **Teil B**: `scripts/vrp_daten.py` → `app/vrp.py` + Endpunkt (mit Tests) → Ebene im Frontend.
5. Ein Changelog-Eintrag, ein Deploy.

**Abnahme:**

- Ein Klick auf den Lautsprecher eines online stehenden Friesen führt in einem neuen Tab zu
  dessen Frequenz — dort steht sein Callsign als Ziel. Stille ist dabei ein gültiges Ergebnis
  (s. 1.2) und **kein** Abnahmefehler; abgenommen wird, dass die Gegenstelle den richtigen
  Piloten aufschaltet, nicht dass jemand spricht.
- Im Kniebrett ist kein Lautsprecher zu sehen — auch nicht als Lücke oder Leerzeichen.
- Die Ebene „Meldepunkte" zeigt bei EDWG auf Zoom 11 die dortigen Punkte mit Namen, deutlich
  größer als im OpenAIP-Bild; der Haken überlebt einen Neustart (Server-Merker); die
  OpenAIP-Nennung steht in der Attributionszeile, auch wenn der Kachel-Layer aus ist.
- `pytest tests/ -v` grün.

## 5. Offene Punkte

**5.1 Gilt unser vorhandener Schlüssel auch für die Core-API?** Die Kacheln nutzen `apiKey` als
Query-Parameter, die Core-API ebenfalls — sehr wahrscheinlich derselbe Schlüssel. Nachweisbar
ist es nur mit dem echten Wert, der in `config.env` steht (nicht im Repo). Ein Befehl genügt:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  "https://api.core.openaip.net/api/reporting-points?country=DE&limit=1&apiKey=$OPENAIP_API_KEY"
# 200 = alles gut · 403 = eigener API-Client nötig (accounts.openaip.net → API Clients)
```

**5.2 Der Länderumfang ist entschieden: die ganze Welt** (Nutzer, 16.08.2026). Deutschland und
Nachbarn dienen nur als **Testabzug** während der Umsetzung.

Die Begründung des Nutzers hebelt meinen Vorschlag sauber aus, und sie gehört festgehalten:
**In Deutschland fliegt er ohnehin mit der OpenFlightMap, OpenAIP ist die Karte für den Rest
der Welt.** Ein VRP-Abzug „Deutschland und Nachbarn" hätte also ausgerechnet dort gefehlt, wo
diese Ebene gebraucht wird. Es ist derselbe Schluss wie beim FSE-Bestand am 16.08.: Der
Zuschnitt auf Europa bekämpfte die Zeichenlast am falschen Ende und beschnitt dabei die Daten
— der richtige Hebel ist der **Ausschnitt zur Laufzeit**, und den hat diese Ebene ab dem ersten
Tag (`/api/vrp?lat&lon&r` plus Punktebudget). Damit ist der Umfang des Abzugs für den Browser
gleichgültig; er kostet nur Plattenplatz im Repo und Speicher im Server.

Umsetzung im Skript:

```bash
python3 scripts/vrp_daten.py --umfang test    # DE,NL,BE,LU,FR,CH,AT,CZ,PL,DK -> vrp_test.json
python3 scripts/vrp_daten.py --umfang welt    # ohne country-Filter, seitenweise -> vrp_welt.json
```

Weltweit heißt: **ohne `country`-Filter**, `page`/`limit=1000` durchpaginieren, bis `nextPage`
fehlt, mit Pause zwischen den Seiten (die API drosselt, s. 2.2). `fields` auf das Nötige
begrenzen (`name,compulsory,geometry,elevation`) — das spart auf jeder Seite den Ballast aus
`createdBy`, `updatedAt` und Konsorten.

**Was noch zu messen ist, ist die Größe, nicht die Entscheidung.** Zum Vergleich: der
FSE-Weltbestand sind 23.780 Plätze in 5,8 MB, im Server 49,7 MB. Meldepunkte sind reine Punkte
mit vier Feldern, also je Stück deutlich leichter als ein FSE-Platz mit Zone. Erst wenn der
Weltabzug wider Erwarten in eine andere Größenordnung fällt, ist neu zu reden — dann aber über
Kürzung der Felder oder Koordinatengenauigkeit, nicht über weggelassene Länder.

**5.3 Farbe und Symbolgröße** sind Vorschläge aus der Kartenkonvention, kein Naturgesetz. Sie
stehen an genau einer Stelle als Konstante und lassen sich nach dem ersten Blick im Sim
nachziehen.

**5.4 Kleiner Nachbar-Befund, nicht Teil des Auftrags:** `.airport-link-icon` setzt keine Farbe
und es gibt keine globale Linkfarbe — das Flugplatz-Symbol zeichnet also im Standard-Linkblau
des Browsers, nicht im Hausblau `--green`. Eine Zeile CSS würde das angleichen. Nur auf
Zuruf — ich fasse es nicht ungefragt an.

**5.5 Fremdverkehr-Popup** (1.3) bleibt vorerst ohne Lautsprecher. Wenn der Nutzer ihn dort
haben will, ist das ein Zusatz von drei Zeilen — aber mit der Frage im Schlepptau, was beim
Sim-Verkehr ohne Callsign passieren soll.
