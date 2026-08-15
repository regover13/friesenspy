# Platzrunden auf der Karte — Design

**Datum:** 2026-08-15
**Status:** abgestimmt, bereit für die Planung

## Ziel

Platzrunden erscheinen auf der Karte, **mit Höhenangabe** — auf jeder Zoomstufe und über
jedem Basis-Layer, nicht nur in einem schmalen Fenster über einer einzigen Karte.

Dazu kommen die FSE-Ebenen mit den MSFS-Entsprechungen (Abschnitt 6). Nebenthemen der
Recherche waren VFR-Meldepunkte und VFR-Routen — beide führen zu keiner Umsetzung, die
Begründung steht in Abschnitt 7.

## Abgrenzung

| Teil | Status |
|---|---|
| 1 — OFM-Zoomstufe freigeben | umzusetzen, zwei Konstanten |
| 2 — eigener Platzrunden-Layer aus GeoJSON | umzusetzen, Kern dieses Dokuments |
| 3 — FSE-Layer und MSFS-Entsprechungen | umzusetzen, Abschnitt 6 |
| 4 — Meldepunkte als Vektor-Layer | **zurückgestellt**, OpenAIP leistet es bereits |
| 5 — VFR-Routen | **entfällt**, keine offene Datenquelle |

Die drei Teile sind unabhängig voneinander und einzeln auslieferbar. Teil 1 bringt
Platzrunden für ganz Europa, aber nur bei einem Basis-Layer und einer Zoomstufe. Teil 2
bringt deutsche Platzrunden überall und immer, dazu die Höhen. Teil 3 beantwortet, unter
welchem Namen ein Platz im Simulator zu finden ist.

## Getroffene Entscheidungen

| Frage | Entscheidung |
|---|---|
| Eigener Layer oder nur OFM? | **beides** — OFM deckt Europa ab, der eigene Layer die Zoomstufen |
| Bedienung | dritte Checkbox in der bestehenden Ebenen-Auswahl, neben OpenAIP und Fremdverkehr |
| Datenquelle | euroscope-Repo (VATGER), geprüft und korrigiert — nicht NavFarm |
| Laden | lazy beim Einschalten der Ebene, nicht beim Seitenaufbau |
| Geschätzte Höhen | werden **nicht** als Zahl angezeigt |
| Höhenbezug `MSL?` | wird als MSL behandelt (statistisch belegt, Abschnitt 5.2) |
| FSE-Ebenen | Flugplätze **und** Landeflächen, Europa-Zuschnitt |
| MSFS-Entsprechung | ins Popup, nicht als eigene Ebene |
| Meldepunkte | zurückgestellt |

---

## 1. Befund: Warum OFM heute keine Platzrunden zeigt

Die OFM-Kacheln zeichnen Platzrunden, Meldepunkte und VFR-Strecken **erst ab Zoom 12**.
Empirisch an den Kacheln geprüft, nicht aus der Dokumentation:

| Zoom | Inhalt der Kachel |
|---|---|
| 11 | Platzsymbol, Lufträume — keine Platzrunden |
| 12 | **Platzrunden**, Meldepunkte (Dreieck im Kreis), VFR-Strecken |
| 13 / 14 | 1233 Byte = leere Kachel, an vier Orten geprüft |

Zwei Konstanten in `app/static/index.html` sperren genau diese Ebene aus:

```js
const OFM_NATIVE_MAX_ZOOM = 11;   // Zeile 3578 — real ist die Grenze 12
const SWITCH_HIGH = 12;           // Zeile 4002 — > 12 schaltet auf Satellit
```

Bei Kartenzoom 12 skaliert Leaflet wegen `maxNativeZoom: 11` (Zeile 3648) die z11-Kachel
hoch, statt die z12-Kachel zu laden; ab 13 kommt Satellit. **Die einzige Zoomstufe mit
Platzrunden wird nie nativ geladen.**

`README.md` Zeile 368 nennt Platzrunden als Inhalt des OFM-Layers. Der Text ist richtig —
falsch war die Konfiguration.

**Warum das allein nicht reicht:** OFM endet bei z12, danach Satellit. OpenTopoMap, CARTO
hell/dunkel und Satellit tragen überhaupt keine Luftfahrtdaten. Beim Anflug zoomt man
weiter hinein, genau dann verschwände die Runde wieder. Deshalb Teil 2.

---

## 2. Teil 1 — OFM-Zoomstufe freigeben

`OFM_NATIVE_MAX_ZOOM` auf **12**.

Zusätzlich zu erproben, **im Browser**, nicht nur an den Kacheln: Die OFM-Kacheln sind
512×512, Leaflets Default ist 256. Georeferenziert ist das korrekt (Retina-Verhalten),
aber alles wird auf halber Größe gezeichnet — die Runden wären winzig. Mit
`tileSize: 512, zoomOffset: -1` läge die native z12-Ebene auf Kartenzoom 13 und würde
doppelt so groß gerendert; `SWITCH_HIGH` müsste dann auf 13.

Zwei Varianten, die Entscheidung fällt am Bildschirm:

| | `maxNativeZoom: 12` allein | zusätzlich `tileSize: 512, zoomOffset: -1` |
|---|---|---|
| Platzrunden sichtbar ab | Kartenzoom 12 | Kartenzoom 13 |
| Größe | halbe native Auflösung | volle Auflösung |
| `SWITCH_HIGH` | bleibt 12 | auf 13 |
| Risiko | keins | Kachelraster verschiebt sich, alle Zoomstufen prüfen |

**Abnahme:** Bei eingeschaltetem OFM-Layer über EDWG Wangerooge ist die Platzrunde
sichtbar, und der Auto-Switch auf Satellit greift erst danach.

---

## 3. Teil 2 — Der Platzrunden-Layer

### 3.1 Datensatz

Quelle ist eine KML aus dem `euroscope`-Repo (`_archiv/sectorfiles/Platzrunden-Deutschland/`),
die ihrerseits auf `vlflugzeuge.de/Dateien/Platzrunden.txt` zurückgeht, gepflegt von
Michael Wellner, Datenstand 05/2022.

| | Wert |
|---|---|
| Features | 412 (408 Polygone + 4 An-/Abflugstrecken) |
| Plätze | 385 |
| Echte Höhen | 265 von 412 (64 %) |
| Größe | 204 KB, **28,3 KB gzip** |
| Abdeckung | nur Deutschland |

Die Alternative (NavFarm/PocketFMS, 139 Features, 121 Plätze, Stand 2019) ist unterlegen
und wurde verworfen — sie diente als unabhängige Gegenprobe, siehe 5.1.

**Verwendet wird `platzrunden_de_korrigiert.geojson`**, nicht die Rohfassung: Vier ICAO-Codes
waren falsch zugeordnet (Abschnitt 5.3).

### 3.2 Feature-Format

```json
{
  "type": "Feature",
  "properties": {
    "name": "Norderney",
    "icao": "EDWY",
    "typ": "platzrunde",              // oder "strecke" (4 Stück)
    "bahn": "08/26",
    "hoehe_ft": 700,                  // null wenn hoehe_geschaetzt
    "hoehe_bezug": "MSL",             // "MSL" | "MSL?" | "unbekannt"
    "hoehe_label": "700 ft",
    "hoehe_geschaetzt": false,        // true = Platzhalter
    "info": "1000 m , UL",
    "quelle": "vlflugzeuge.de/Dateien/Platzrunden.txt"
  },
  "geometry": { "type": "Polygon", "coordinates": [[…]] }
}
```

### 3.3 Ablage und Auslieferung

Das GeoJSON liegt statisch neben den übrigen Frontend-Dateien und wird von nginx
ausgeliefert. Kein Endpunkt, keine Datenbank, kein Poller — die Daten ändern sich im
Jahresmaßstab.

Ablageort: `app/static/data/platzrunden_de.geojson`. Dorthin kommt die **korrigierte**
Fassung (`platzrunden_de_korrigiert.geojson` aus Abschnitt 11) — der Dateiname im Repo
trägt den Zusatz nicht, die Korrekturen sind je Feature in `icao_original` dokumentiert.

### 3.4 Frontend

Dem Muster des Fremdverkehr-Layers folgen, der in V12.7.0 entstanden ist:

- eine `L.geoJSON`-Ebene in einer eigenen Gruppe, gebaut wie `_makeTileLayers()` die
  Basis-Layer baut
- Registrierung in der Ebenen-Auswahl **vor** dem Bau der Layers-Control — sonst zeigt der
  Haken dauerhaft den falschen Zustand (derselbe Fallstrick wie bei OpenAIP und
  Fremdverkehr, dokumentiert bei `_addPreferredVerkehrLayer`, Zeile 3759)
- Zustand über dieselbe Präferenz-Mechanik wie die anderen Ebenen, damit die Wahl den
  Seitenwechsel überlebt
- **Lazy Load:** Das GeoJSON wird erst beim ersten Einschalten geholt, dann im Speicher
  gehalten. 28 KB gzip rechtfertigen keinen Abruf beim Seitenaufbau.

**Darstellung:** dünne Linie, gedeckte Farbe, `fill: false`, `interactive: true` für das
Popup. Die 4 Features mit `typ: "strecke"` sind Linien, keine Ringe — als `LineString`
zeichnen, nicht schließen.

### 3.5 Popup

```
EDWY  Norderney
Bahn 08/26
Platzrunde 700 ft MSL
```

**Bei `hoehe_geschaetzt: true` entfällt die Höhenzeile** und wird durch „Höhe nicht
bekannt" ersetzt.

> **Fallstrick:** Bei allen 147 Platzhaltern lautet `hoehe_label`
> „keine Angabe (Annahme 1000 ft)". Wer das Feld ungeprüft rendert, zeigt die erfundene
> Zahl trotzdem an — nur in Klammern. **Im Frontend auf `hoehe_geschaetzt` verzweigen,
> nicht auf das Label.**

Bei `hoehe_bezug: "MSL?"` wird trotzdem „MSL" geschrieben; die Begründung steht in 5.2.

### 3.6 Zoom-Verhalten

Der Layer hat **keine** Zoomgrenzen. Das ist sein ganzer Zweck: Er liegt über jedem
Basis-Layer und auf jeder Stufe. Bei weit herausgezoomter Karte werden 412 Polygone zu
Rauschen — deshalb unterhalb von Zoom 9 ausblenden, ohne die Ebene abzuschalten.

---

## 4. Was der Nutzer sieht

| Situation | vorher | nachher |
|---|---|---|
| OFM, Zoom 12 | keine Platzrunden | Platzrunden europaweit (Teil 1) |
| Satellit, Zoom 14, Anflug EDWY | nichts | Platzrunde + Höhe (Teil 2) |
| CARTO dunkel, Zoom 13 | nichts | Platzrunde + Höhe (Teil 2) |
| Platz ohne bekannte Höhe | — | Runde sichtbar, „Höhe nicht bekannt" |

---

## 5. Qualitätssicherung des Datensatzes

Alle Zahlen stammen aus ausgeführten Prüfskripten, Referenz sind 1.364 deutsche Flugplätze
aus der OpenAIP-Core-API.

### 5.1 Kreuzvergleich zweier unabhängiger Quellen

NavFarm (12/2019) und vlflugzeuge (05/2022) sind unabhängig entstanden. **119 Plätze sind
in beiden enthalten — bei allen stimmt die Höhe überein, null Abweichungen.** Das validiert
beide Datensätze gegenseitig.

Nebenergebnisse: Die 141 Plätze ohne Höhe lassen sich aus NavFarm **nicht** füllen.
`EDEF` Babenhausen ist nur bei NavFarm vorhanden, existiert aber laut OpenAIP nicht mehr.
**Borkum (`EDWR`) fehlt in beiden Quellen.**

### 5.2 Höhenbezug — geklärt

127 Einträge tragen eine Höhe ohne expliziten Bezug. Rechnet man jede Höhe gegen die
Platzhöhe, ergibt sich die Höhe über Grund:

| Gruppe | n | Median | 10 %–90 % |
|---|---|---|---|
| `MSL` (explizit) | 134 | 864 ft | 708–1034 ft |
| `MSL?` (unklar) | 121 | 895 ft | 693–1078 ft |

Die Verteilungen sind deckungsgleich und liegen dort, wo deutsche Platzrunden liegen. Wären
die unklaren Werte AGL, müsste ihr Median um die mittlere Platzhöhe verschoben sein.
**`MSL?` wird als MSL behandelt.**

Ein echter Ausreißer: `EDTD` Donaueschingen, 2200 ft bei Platzhöhe 2231 ft — das wären
−31 ft über Grund. Vermutlich ein Zahlendreher. Nicht korrigiert.

### 5.3 Vier falsche ICAO-Zuordnungen — korrigiert

Fünf Features liegen mehr als 4 km vom Platz mit dem angegebenen ICAO. Bei vieren steht ein
anderer Platz unmittelbar daneben:

| Feature | ICAO im Datensatz | Abstand | tatsächlich | Abstand |
|---|---|---|---|---|
| Hamm | `EDFJ` | 231,6 km | **EDLH** Hamm-Lippewiesen | 1,7 km |
| Magdeburg | `EDBC` | 27,5 km | **EDBM** Magdeburg-City | 0,7 km |
| Schweinfurt | `EDQT` | 20,2 km | **EDFS** Schweinfurt-Süd | 0,6 km |
| Zweibrücken | `EDRP` | 8,2 km | **EDRZ** Zweibrücken | 0,8 km |

Die Geometrie ist jeweils richtig, nur die Verknüpfung war falsch. Korrigiert; die
Originalwerte stehen als `icao_original` im Feature.

Ungeklärt: `EDVP` Peine-Eddesse liegt 9,6 km vom OpenAIP-Platz `EDVP`
„Peine-Glindbruchkippe", und es gibt keinen näheren Platz.

### 5.4 Geprüft und unauffällig

- Alle 408 Polygon-Ringe sind geschlossen — im GeoJSON ist nichts nachzubessern
- 265 echte Höhen, alle mit Wert; 147 Platzhalter, alle mit `hoehe_ft: null`
- Umfang der Runden: Median 11,8 km; die größten (EDGS 28,7 km, EDRW 24,7 km, EDNX 24,3 km)
  gehören zu großen Plätzen und sind kein Fehlerverdacht
- 16 ICAO-Codes sind in OpenAIP nicht mehr vorhanden, überwiegend geschlossene Plätze

---


## 6. Teil 3 — FSE-Layer und MSFS-Entsprechungen

Quelle: <https://github.com/piero-la-lune/FSE-Planner>, **MIT-Lizenz**, React + **Leaflet**
— dieselbe Kartenbibliothek. Der Renderer der Zonen ist `src/MapLayers/Zones.js`,
**43 Zeilen** reines `L.polyline`, praktisch unverändert übernehmbar.

### 6.1 Was übernommen wird

| Ebene | Inhalt | Quelle im Repo |
|---|---|---|
| **FSE-Flugplätze** | Marker mit Name, Bahnlänge, Belag, Elevation | `src/data/icaodata.json` |
| **FSE-Landeflächen** | Voronoi-Zellen, median 7 Punkte | `public/data/zones.json` |

Die Landefläche ist das Gebiet, dessen Landungen diesem FSE-Platz zugerechnet werden.

### 6.2 Die MSFS-Entsprechung

Das `msfs`-Feld ist der eigentliche Gewinn — es beantwortet, unter welchem Namen ein Platz
im Simulator existiert:

| | Anteil |
|---|---|
| ICAO identisch in MSFS | 13.008 (54,7 %) |
| **abweichender / zusätzlicher ICAO** | **8.458 (35,6 %)** |
| in MSFS gar nicht vorhanden | 2.314 (9,7 %) |

Deutschland: 464 FSE-Plätze, 222 mit abweichendem ICAO, 7 nicht in MSFS (darunter EDDI
Tempelhof). Im FriesenFlieger-Revier sind alle Inseln unter demselben Code vorhanden;
Abweichungen bei Emden (`EDWE`/`EHOW`) und Papenburg (`EDWF`/`EDHJ`).

Diese Information gehört **ins Popup**, nicht in eine eigene Ebene — sie beantwortet eine
Frage, die man am konkreten Platz stellt:

```
8D7  Clark Co
Bahn 3687 ft Asphalt · 1791 ft
In MSFS als: SD59
```

Bei fehlender Entsprechung: „In MSFS nicht vorhanden".

### 6.3 Datenmenge und Zuschnitt

Weltweit sind es 17 MB (9,5 MB Plätze + 7,5 MB Zonen) — zu viel für die Auslieferung.
Regional zugeschnitten und auf die gebrauchten Felder reduziert:

| Zuschnitt | Plätze | Flugplätze | Zonen |
|---|---|---|---|
| Deutschland (47–56 N, 5–16 E) | 667 | 22 KB gzip | 21 KB gzip |
| **Europa (35–72 N, −25–45 E)** | 2.335 | 85 KB gzip | 76 KB gzip |

**Europa-Zuschnitt**, erzeugt als Build-Schritt aus dem FSE-Planner-Repo, abgelegt unter
`app/static/data/fse_airports_eu.json` und `fse_zones_eu.json`.

Beide Ebenen brauchen **keinen FSEconomy-Account** — nur die Job- und Flugzeug-Layer des
FSE-Planners benötigen einen Key, die statischen Flugplatz- und Zonendaten nicht.

### 6.4 Verhalten

Wie der Platzrunden-Layer: eigene Checkbox je Ebene, **lazy** beim Einschalten geladen,
Zustand über die Präferenz-Mechanik. Die Zonen sind reine Linien (`fill: false`,
`interactive: false`) und dienen als Kulisse — angeklickt wird der Platz, nicht die Zelle.

**Attribution:** MIT deckt Code und Repo-Inhalt; die Flugplatzliste stammt aus FSEconomy.
Ein Hinweis auf FSE-Planner gehört in die Karten-Attribution.

---

## 7. Nicht umgesetzt

### 7.1 Meldepunkte — zurückgestellt

Der bestehende OpenAIP-Layer zeichnet sie bereits, ab Zoom 12, mit Label und
Dreieck-im-Kreis (geprüft am Pflichtmeldepunkt BRAVO, Karlsruhe TMA). Ein eigener Layer
brächte nur Klickbarkeit und die Unterscheidung Pflicht/Nicht-Pflicht — die
OpenAIP-Core-API liefert 6.121 Meldepunkte weltweit mit `compulsory`-Flag (DE 336, FR 675,
IT 476, GB 393, US 0). Kein hinreichender Grund für einen weiteren Layer.

### 7.2 VFR-Routen — entfällt

Es gibt keine offene Vektorquelle. Die OpenAIP-Endpunkte `vfr-routes`, `routes`,
`procedures` und `traffic-circuits` liefern alle 404; vorhanden sind nur `airports`,
`airspaces`, `navaids`, `obstacles`, `reporting-points`, `hotspots`. AIXM 5.1.1 kennt
VFR-Routen, die Daten liegen bei den nationalen AIS. OFM zeichnet sie als Pixel — über
Teil 1 sind sie damit indirekt zu haben, mehr ist nicht möglich.

---

## 8. Herkunft der Daten

**Bezogen** wurden die Platzrunden aus dem `euroscope`-Repo (VATGER), wo sie seit 2022 unter
`_archiv/sectorfiles/Platzrunden-Deutschland/` liegen. Die KML nennt im Header
`vlflugzeuge.de/Dateien/Platzrunden.txt` als Ursprung und „Update: Michael Wellner"; dieser
Verweis steht als `quelle` in jedem Feature und bleibt dort.

Eine weitergehende Lizenzprüfung findet **nicht** statt — Entscheidung des Betreibers von
FriesenSpy. Übernommen werden ausschließlich die Geometrien und Höhenwerte, keine Grafiken
und keine Kartendarstellung.

Zur Einordnung: Einzelne Koordinaten sind Fakten und als solche nicht urheberrechtlich
geschützt; Platzrunden werden zudem amtlich bekanntgemacht (AIP VFR / NfL), und § 5 UrhG
nimmt amtliche Bekanntmachungen vom Schutz aus. Die DFS formuliert für die digitale AIP
selbst nur „urheberrechtlichen Schutz, soweit rechtlich möglich".

---

## 9. Offene fachliche Punkte

Keiner davon blockiert die Umsetzung; sie verbessern den Datenbestand.

- Die 141 Plätze ohne Höhe aus der AIP VFR nachtragen
- **Borkum (`EDWR`)** ergänzen — fehlt in beiden Quellen
- `EDTD` (Höhe) und `EDVP` (Verortung) gegen AIP VFR prüfen
- Datenstand 05/2022 gegen die aktuelle AIP gegenprüfen

---

## 10. Abnahmekriterien

1. Bei OFM und Kartenzoom 12 ist über EDWG die Platzrunde sichtbar.
2. Die Platzrunden-Ebene lässt sich in der Ebenen-Auswahl schalten; der Haken zeigt nach
   dem Neuladen den richtigen Zustand.
3. Die Ebene bleibt bei Satellit, CARTO und OpenTopoMap sichtbar, auch bei Zoom 14.
4. Ein Klick auf die Runde von EDWY zeigt ICAO, Namen, Bahn und „700 ft MSL".
5. Ein Klick auf eine Runde mit `hoehe_geschaetzt: true` zeigt **keine Zahl**, sondern
   „Höhe nicht bekannt".
6. Das GeoJSON wird erst beim Einschalten der Ebene geladen, nicht beim Seitenaufbau.
7. Unterhalb von Zoom 9 sind die Runden ausgeblendet, die Ebene bleibt aktiv.
8. Die FSE-Flugplatz-Ebene lässt sich schalten; ein Klick auf einen Platz mit abweichendem
   MSFS-Code (z. B. Emden) zeigt „In MSFS als: EHOW".
9. Ein Platz ohne MSFS-Entsprechung zeigt „In MSFS nicht vorhanden".
10. Die FSE-Landeflächen liegen als Linien unter den Markern und fangen keine Klicks ab.

---

## 11. Artefakte

Außerhalb des Repos, unter `~/projects/platzrunden-recherche/`:

| Datei | Inhalt |
|---|---|
| `platzrunden_de_korrigiert.geojson` | der geprüfte Datensatz, 4 ICAO-Korrekturen |
| `PRUEFBERICHT.md` | die vollständige Gegenprüfung mit allen Zahlen |
| `openaip-airports-de.json` | 1.364 deutsche Plätze, Referenz aller Prüfungen |
| `rohdaten/`, `parse_platzrunden.py`, `pruefe_quelle.py` | NavFarm-Quelle und Werkzeuge des Kreuzvergleichs |

Der FSE-Planner-Klon liegt in `/tmp/FSE-Planner` und ist flüchtig.
