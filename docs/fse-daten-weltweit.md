# FSE-Daten weltweit — Übergabe

**Stand 16.08.2026.** Die Daten liegen im Repo, die Umstellung der Anwendung steht noch aus.
Dieses Dokument ist die Übergabe an die Sitzung, die sie macht.

## Was schon da ist

| Datei | Inhalt | Größe |
|---|---|---|
| `app/data/fse/fse_airports_world.json` | **23.780** Plätze, weltweit | 2,58 MB |
| `app/data/fse/fse_zones_world.json` | 23.780 Landeflächen (Polygone) | 3,18 MB |
| `scripts/fse_daten.py` | Erzeugt beides, mit `--laden` direkt von GitHub | — |

Format unverändert gegenüber den bisherigen EU-Dateien:

```json
"EDWG": {"lat":53.7872,"lon":7.91583,"name":"Wangerooge","msfs":["EDWG"],
         "rwy":2803,"surface":1,"elev":5}
"EDWG": [[53.6615,8.0757], [53.8201,7.6904], …]        // Zone
```

Zonenkoordinaten sind auf **4 Nachkommastellen** gerundet (~11 m). Das halbiert die Datei von
7,15 auf 3,18 MB. Zonen sind Zuständigkeitsgebiete, keine Navigationsdaten — eine Grenze auf
den Meter zu führen wäre Genauigkeit, die niemand nutzt.

**Der Ablageort ist bewusst `app/data/`, nicht `app/static/`.** Was unter `static/` liegt,
wird als Ganzes ausgeliefert — genau das soll hier nicht passieren.

Die bisherigen EU-Dateien unter `app/static/data/` sind **unangetastet**; die Ebene
funktioniert unverändert weiter, bis umgestellt wird.

## Was noch fehlt — und warum es so laufen sollte

Der Zuschnitt auf Europa war eine Notlösung gegen die **Zeichenlast**, nicht gegen die
Dateigröße. Alle Plätze liegen gleichzeitig in der Karte, und Leaflet positioniert bei jeder
Kartenbewegung jeden Pfad neu — auch die unsichtbaren. Bei 2.335 Plätzen war das bereits
spürbar (die Karte hing, behoben am 15.08.2026 durch `_labelsImSichtbereich`); bei 23.780
wäre es unbenutzbar, im Kniebrett zuerst.

**Die Daten einfach auszutauschen genügt deshalb nicht.** Der Hebel ist, serverseitig nur den
sichtbaren Ausschnitt zu liefern — dasselbe Muster, das `/api/traffic?lat=&lon=&r=` für den
Verkehr längst benutzt (Nutzer-Entscheidung 16.08.2026):

1. Datei beim Start einmal einlesen, serverseitig im Speicher halten.
2. `GET /api/fse/airports?lat=&lon=&r=` und `GET /api/fse/zones?lat=&lon=&r=` geben zurück,
   was im Ausschnitt liegt.
3. Im Frontend nachladen bei `moveend`/`zoomend`, gedrosselt wie beim Verkehr
   (`_verkehrAbrufen` ist die Vorlage, samt Sichtbarkeitswache und `_naviSelbstBewegt`).
4. **Zoomschwelle nicht vergessen**: Herausgezoomt wären es sonst wieder alle. Der Verkehr
   löst das über `_VERKEHR_MIN_ZOOM` und einen Deckel nach Entfernung; beides ist hier
   genauso nötig.

Ist das gebaut, ist der Umfang des Bestands gleichgültig — das Kniebrett sieht nie mehr als
ein paar hundert Einträge und lädt **weniger** als heute mit Europa.

## Danach aufräumen

- `app/static/data/fse_airports_eu.json` und `fse_zones_eu.json` löschen
- `scripts/fse_zuschnitt.py` löschen (`scripts/fse_daten.py --europa` kann dasselbe)
- README: „rund 2 300 europäischen Plätzen" → weltweit, mit der neuen Zahl
