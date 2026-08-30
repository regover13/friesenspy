# Flugplatzkarten als Karten-Overlay — Design

**Stand:** 30.08.2026
**Vorgänger:** [`2026-08-23-aip-karten-overlay-design.md`](2026-08-23-aip-karten-overlay-design.md)
(Sichtflugkarten). Dieses Dokument baut darauf auf und ändert es an einer Stelle: dem Schutz
der Handpassung, Abschnitt 7.

---

## 1. Ziel

Die amtliche DFS-**Flugplatzkarte** eines Verkehrsflughafens liegt georeferenziert und
halbtransparent über der Leaflet-Karte, das eigene Flugzeug rollt darauf. Sie erscheint von
allein, sobald die eigene Position über dem Platz liegt, und tritt beim Verlassen wieder
hinter die Sichtflugkarte zurück.

Die Sichtflugkarte hat den Maßstab 1:100 000 — beim Rollen ist der ganze Flughafen darauf
ein Fleck von zwei Millimetern. Die Flugplatzkarte liegt bei rund 1:10 000 und trägt
Rollwegnamen, Haltepunkte und Standplatznummern. Das ist die Lücke, die dieses Vorhaben
schließt.

### 1.1 Zwei Sorten, ein Eintrag im Menü

Die DFS gibt im BasicVFR-Teil zwei verschiedene Blätter heraus:

| Sorte | Titel auf dem Blatt | Inhalt |
|---|---|---|
| Flugplatzkarte | „Flugplatzkarte / Aerodrome Chart" | Bahnen mit Maßen, Vorfelder, Gebäude, LOC-Antennen, Umgebung |
| Rollkarte | „Flugplatzrollkarte / Aerodrome Ground Movement Chart" | Rollleitlinien farbcodiert, Haltepunkte, Standplätze einzeln nummeriert, Spannweitenbeschränkungen |

**Nicht jeder Platz hat beide.** EDDL hat nur die Flugplatzkarte, EDDV nur Rollkarten (drei
Blätter), EDDM und EDDN je eine von beiden.

Aufgenommen werden beide. **Die Rollkarte hat Vorrang**, weil sie beim Rollen mehr trägt;
fehlt sie, tritt die Flugplatzkarte an ihre Stelle. Im Ebenen-Menü steht deshalb nur **ein**
Eintrag „Flugplatzkarte" — welches Blatt dahinter liegt, ist eine Frage des Bestands und
keine, die der Nutzer im Cockpit beantworten will.

### 1.2 Abgrenzung

Ausdrücklich **nicht** Teil dieses Vorhabens:

- Mehrblattrige Rollkarten zusammensetzen. EDDV hat drei Blätter, die Ausschnitte zeigen.
  Ein Blatt je Platz und Sorte, das andere wird verworfen (Abschnitt 5.7).
- Anflugkarten, Hindernisblätter, Textseiten des Kapitels.
- Plätze außerhalb Deutschlands. Die Quelle ist die DFS.

---

## 2. Was gemessen wurde

Die Machbarkeit wurde am 30.08.2026 an 31 Blättern von 14 Verkehrsflughäfen geprüft, bevor
dieses Dokument entstand. Die Zahlen unten sind Messwerte, keine Schätzungen. Der Prototyp
liegt als `scripts/ground_chart_probe.py` im Repo (Abschnitt 12).

### 2.1 Die Sichtflugkarten-Automatik greift hier nicht

Sie liest Grad-Zahlen an den Gradnetz-Ticks des Kartenrahmens. **Flugplatzkarten haben kein
Gradnetz** — keine Ticks, keine Grad-Beschriftung, keinen vergleichbaren Rahmen. Es gibt nur
einen Maßstabsbalken, ein ARP-Kreuz und eine Missweisungsrose.

Das ist auch der Grund, warum dieses Design nirgends ein Zeichen liest. Die Ziffernerkennung
der Sichtflugkarten hat 171 von 446 Blättern der Handarbeit überlassen; sie hier ein zweites
Mal zu versuchen wäre eine Wiederholung mit schlechteren Karten.

### 2.2 Die Blätter sind gedreht, nicht genordet

Sie sind so gesetzt, dass die Hauptbahn waagerecht liegt. Gemessene Kartendrehung:

| Platz | Bahnrichtung | Drehung des Blattes |
|---|---|---|
| EDDL | 052,7° | 322,8° (also −37,2°) |
| EDDM | 083,4° | 353,5° (also −6,5°) |
| EDDH | 152,9° | 90,0° |

`L.imageOverlay` kann nicht rotieren. Das Blatt wird deshalb **genordet abgelegt**
(Abschnitt 6) — dasselbe Verfahren, das für die sieben quer gedruckten Sichtflugkarten schon
läuft, nur mit beliebigem statt rechtem Winkel.

### 2.3 Die Bahnen sind im Bild sauber zu fassen

Ein Histogramm über EDDL zeigt einen einzelnen dominanten Mittelgrauton: **Wert 153 mit
3,7 % Flächenanteil**, während jeder Nachbarwert bei 0,2 bis 0,4 % liegt. Ein senkrechter
Schnitt durch die Blattmitte trifft genau zwei Bänder dieser Farbe von je 28 px Breite — die
beiden Bahnen, 45 m breit, also 1,6 m je Pixel.

Der Ton ist **nicht konstant**: Die Flugplatzkarte nutzt 153/154, die Rollkarte 179/180. Er
wird deshalb gemessen und nicht festgelegt (Abschnitt 5.2).

### 2.4 Restfehler der fertigen Passung

Passung aus den Bahnen gerechnet, danach gegen dieselben Schwellenkoordinaten geprüft, mit
vier Freiheitsgraden:

| Blatt | Sorte | Restfehler | Bahnen erkannt |
|---|---|---|---|
| EDDL | Flugplatzkarte | **5,7 m** | 2 |
| EDDM | Flugplatzkarte | **6,6 m** | 2 |
| EDDH | Flugplatzkarte | 29,6 m | 2 |
| EDDM | Rollkarte | 74,0 m | 2 |

Zum Maßstab: Eine Bahn ist 45 m breit, ein Rollweg 23 m. Ein Fehler von 30 m setzt das
Flugzeug neben den Rollweg, auf dem es steht.

**Zwei von rund zehn echten Flugplatzkarten sitzen heute unter 15 m.** Das ist die ehrliche
Ausgangslage; die Ausbeute zu heben ist die Arbeit des Plans, nicht dieser Spec. Das
Verfahren ist damit belegt, seine Robustheit nicht.

### 2.5 Die Prüfungen wirken

Vier Passungen mit 229 m, 793 m, 849 m und 1152 m Fehler wurden von den Prüfungen aus
Abschnitt 5.6 zuverlässig abgewiesen, statt still zu erscheinen. Das ist der wichtigere
Befund: Das Verfahren scheitert **erkennbar**.

### 2.6 Umfang

Ein Durchlauf über alle 446 Einträge in `airport_links` (30.08.2026, ohne einen einzigen
Abruffehler) findet **61 Plätze** mit mindestens einem Blatt in Frage kommender Größe,
14 davon mit mehreren. Das Vorhaben betrifft also rund ein Siebtel des Bestands.

---

## 3. Datenmodell

### 3.1 Eigene Tabelle

`aip_ground_charts`, **nicht** eine Erweiterung von `aip_charts`. Begründung: Die Felder sind
zu verschieden. Eine Flugplatzkarte hat keinen Rahmen, keine Ticks und keine Feldgrenzen,
dafür einen Drehwinkel, einen Maßstab, eine Sorte und einen Restfehler. Zusammengelegt wäre
die Hälfte jeder Zeile leer und `nur_gepasst=True` bekäme eine zweite Bedeutung.

```sql
CREATE TABLE IF NOT EXISTS aip_ground_charts (
    icao          TEXT PRIMARY KEY,     -- ICAO-Code (Grossbuchstaben)
    sorte         TEXT NOT NULL,        -- 'rollkarte' oder 'flugplatzkarte'
    seite_url     TEXT NOT NULL,        -- gewaehlte Kapitelseite; der Admin kann sie setzen
    bild_hash     TEXT NOT NULL,        -- SHA-256 des GENORDETEN Blatts, wie abgelegt
    quell_hash    TEXT NOT NULL,        -- SHA-256 des Rohblatts, erkennt den AIRAC-Wechsel
    nord          REAL NOT NULL,        -- Grenzen des genordeten Blatts fuer L.imageOverlay
    sued          REAL NOT NULL,
    west          REAL NOT NULL,
    ost           REAL NOT NULL,
    feld_nord     REAL NOT NULL,        -- Huelle der Bahnen und Rollwege: danach schaltet
    feld_sued     REAL NOT NULL,        -- die Automatik (Abschnitt 10.2)
    feld_west     REAL NOT NULL,
    feld_ost      REAL NOT NULL,
    drehung       REAL NOT NULL,        -- Grad, um die das Rohblatt genordet wurde
    mps           REAL NOT NULL,        -- Meter je Pixel im Rohblatt
    rest_max      REAL NOT NULL,        -- groesster Restfehler in Metern, siehe 5.6
    bahnen        INTEGER NOT NULL,     -- Zahl der zur Passung verwendeten Bahnen
    quelle        TEXT NOT NULL,        -- 'auto' oder 'hand' -- 'hand' ist eine SPERRE
    airac         TEXT NOT NULL,
    status        TEXT NOT NULL,        -- 'gepasst' oder 'ungepasst'
    geprueft_am   TEXT
);
```

### 3.2 Vorschläge

Findet der Auffrischlauf für eine **handgepasste** Karte ein neues Blatt, darf er die
bestehende Passung nicht anfassen (Abschnitt 7). Er legt seinen Fund stattdessen hier ab:

```sql
CREATE TABLE IF NOT EXISTS aip_chart_vorschlaege (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    art           TEXT NOT NULL,        -- 'sichtflug' oder 'ground'
    icao          TEXT NOT NULL,
    quell_hash    TEXT NOT NULL,        -- welches Rohblatt der Vorschlag betrifft
    passung       TEXT NOT NULL,        -- JSON: die gerechneten Werte, Form je nach art
    grund         TEXT NOT NULL,        -- warum vorgeschlagen statt uebernommen
    gefunden_am   TEXT NOT NULL,
    UNIQUE(art, icao, quell_hash)
);
```

Das Blatt zum Vorschlag liegt als `<ICAO>.vorschlag.png` neben dem Livebild — es zu
verwerfen und beim Übernehmen neu zu holen wäre unnötig und beim nächsten AIRAC-Wechsel
nicht mehr möglich.

`UNIQUE(art, icao, quell_hash)` verhindert, dass derselbe Fund bei jedem Wochenlauf erneut
in der Liste erscheint. Die Tabelle gilt **für beide Kartentypen** — der Schutz aus
Abschnitt 7 betrifft die 171 handgepassten Sichtflugkarten genauso.

---

## 4. Beschaffung: welches Blatt ist eine Flugplatzkarte?

Die Kapitelseiten kommen über die bestehende Kette: `airac_url` → `seiten_des_kapitels` →
`bild_aus_html`. Neu ist nur die Frage, welche der 4 bis 12 Seiten die gesuchte ist.

### 4.1 Nicht über die Bildgröße

Naheliegend, aber untauglich: Die Blätter sind zwischen 1240×1754 und 3800×1170 groß, und
Anflugkarten liegen im selben Bereich. Die Größe taugt als Vorfilter, nicht als Entscheidung.

### 4.2 Über den Kopfbereich, ohne ein Zeichen zu lesen

Der Titel steht bei allen Blättern **an derselben Stelle oben links und in derselben
Setzung**. Ein Vergleich dieses Ausschnitts gegen zwei hinterlegte Muster — eines je Sorte —
entscheidet die Zuordnung. Verglichen wird nicht per Hash, sondern über den Anteil
übereinstimmender Pixel mit einer Schranke, damit ein einzelnes verändertes Pixel nicht die
ganze Erkennung kippt.

Die Muster werden einmalig aus je einem belegten Blatt gewonnen
(EDDL Seite 6 für die Flugplatzkarte, EDDM Seite 7 für die Rollkarte) und liegen als
PNG unter `app/data/ground_chart_kopf/`. Sie gehören ins Repo, nicht in die Datenbank: Sie
sind Programmbestandteil und müssen bei einem Neuaufbau des Volumes vorhanden sein.

**Bekannte Schwäche.** Eine Voruntersuchung über einen Hash desselben Ausschnitts hat vier
verschiedene Cluster über Blätter geliefert, die alle Flugplatzkarten sein müssten. Der
Ausschnitt war dabei nach Augenmaß gewählt und traf bei den breiteren Blättern teilweise
Weißraum. Der Plan muss den Ausschnitt **vermessen**, nicht schätzen — dazu Task 3.

### 4.3 Der Admin sticht die Automatik

Wie bei den Sichtflugkarten (`/api/admin/aip-charts/{icao}/seiten`) kann ein Mensch die
Seite festlegen. Die gewählte URL steht in `seite_url` und wird beim Auffrischen bevorzugt.

---

## 5. Passung über die Bahngeometrie

Der Kern. Ablauf für ein Blatt:

### 5.1 Referenz beschaffen

Bahnschwellen aus **OurAirports** (`runways.csv`). Diese Quelle ist im Projekt bereits in
Gebrauch (`scripts/nearby_airports.py`), es kommt kein neuer Lieferant hinzu — nur eine
zweite Datei desselben.

Geprüft am 30.08.2026: Alle 15 untersuchten Verkehrsflughäfen haben Schwellenkoordinaten,
meist für jede Bahn; die daraus gerechneten Bahnlängen stimmen auf wenige Meter mit der
Längenangabe derselben Zeile überein.

**OpenAIP scheidet aus.** Es liefert keine Schwellenkoordinaten, sondern nur `trueHeading` —
für EDDL den Wert 50 bei tatsächlich 052,7°. Drei Grad sind auf 3 km Bahnlänge 150 m.

### 5.2 Bahnfarbe messen

Der häufigste Grauwert zwischen 100 und 210, wenn er mindestens 0,6 % einer Stichprobe
(jedes dritte Pixel je Achse) ausmacht. Ergebnisse: 153/154 auf Flugplatzkarten, 179/180 auf
Rollkarten. Wird kein solcher Ton gefunden, ist das Blatt keine Flugplatzkarte — die Passung
endet hier.

### 5.3 Bahnflächen finden

Zusammenhangskomponenten in dieser Farbe (± 6), zeilenweise Läufe mit Union-Find. Eine
Fläche gilt als Bahnkandidat bei mindestens 8000 Pixeln, einer Breite ab 4 px und einem
Verhältnis Länge zu Breite von mindestens 8.

Reines Pillow, wie `app/aip_charts.py`. **Keine neue Abhängigkeit** — numpy, scipy und OpenCV
sind im Projekt nicht vorhanden und werden es nicht.

### 5.4 Achse und Enden

Die Längsachse folgt aus den zweiten Momenten der Fläche. Gemessen wurde, dass die Achsen
zweier Parallelbahnen desselben Blattes auf **0,01° bis 0,06°** übereinstimmen — der Winkel
ist also die verlässlichste Größe der ganzen Kette.

Die Fläche selbst ist es nicht: Rollwegabzweige und Markierungen trennen sie, gemessene
Längen fielen bis zu 24 % zu kurz aus. Die Enden werden deshalb **entlang der Achse
abgetastet**, mit einer erlaubten Lücke von 60 px und einer geforderten Querabdeckung von
55 %. Bei EDDL hob das die gemessene Länge von 1414 auf 1769 px — den korrekten Wert.

### 5.5 Zuordnung durchprobieren

Welche Bildbahn welcher echten Bahn entspricht, wird **nicht geraten**. Alle Zuordnungen und
beide Laufrichtungen je Bahn werden durchgerechnet; es gewinnt die mit dem kleinsten
Restfehler. Ein Sortieren nach Länge — der erste Versuch — hat bei EDDV zwei verschiedene
Maßstäbe für dasselbe Blatt geliefert und die Passung um 145 m verfehlt.

**Ein Bahnende dicht am Blattrand ist kein Passpunkt.** Dort ist die Bahn nur abgeschnitten;
mehrblattrige Rollkarten zeigen Ausschnitte. Es geht als Achsrichtung ein, nicht als Punkt.

### 5.6 Die Prüfkette

Fünf Prüfungen. **Eine Karte, die eine davon nicht besteht, wird nicht angezeigt** — dieselbe
Regel wie bei den Sichtflugkarten, und aus demselben Grund: Eine falsch liegende Karte ist
schlimmer als gar keine, weil sie im Rollverkehr geglaubt wird.

1. **Mindestens vier Passpunkte.** Bei vier Unbekannten sind vier Punkte acht Gleichungen und
   damit vier Freiheitsgrade. Zwei Punkte bestimmen die Passung exakt und lassen keinen
   Restfehler übrig — sie ist dann *unprüfbar*, nicht *richtig*. Das ist die Lage bei jedem
   Platz mit nur einer Bahn (EDDB, EDDC, EDDE, EDDG, EDDR, EDDW); Abschnitt 5.8.
2. **Ähnlichkeit, nicht Affinität.** Vier Unbekannte: Drehung, Maßstab, zwei Verschiebungen.
   Eine Karte ist nicht geschert. Eine affine Rechnung mit sechs Unbekannten auf vier Punkte
   hat in der Vorabprobe einen Restfehler von 1,7 m vorgetäuscht, wo tatsächlich 5,7 m
   standen — überbestimmte Modelle schmeicheln sich selbst.
3. **Die y-Achse wird gespiegelt.** Bildkoordinaten laufen nach unten, Nordmeter nach oben.
   Ohne die Spiegelung liegt die richtige Lösung nicht im Suchraum; die Vorabprobe lieferte
   dann 59 m statt 5,7 m für dasselbe Blatt.
4. **Nordung zwischen 270° und 90°.** Ein DFS-Blatt ist nie kopfüber gedruckt. Zwei gleich
   lange Parallelbahnen sind unter einer 180°-Drehung symmetrisch, der Restfehler kann das
   nicht unterscheiden — bei EDDM wählte die Rechnung ohne diese Bedingung 173,5° statt der
   richtigen 353,5°, bei gleich kleinem Restfehler.
5. **Maßstabskonsistenz.** Weichen die aus zwei Bahnen desselben Blattes gerechneten
   Maßstäbe um mehr als 8 % voneinander ab, ist die Zuordnung falsch. Eine Karte hat genau
   einen Maßstab. Diese Prüfung hat die vier Fehlpassungen aus Abschnitt 2.5 abgewiesen.

**Schranke für den Restfehler: 15 m.** Ein Drittel Bahnbreite, weniger als eine Rollwegbreite.
Darüber wird die Karte als `ungepasst` abgelegt und wartet auf die Handpassung. Nach heutigem
Stand bestehen EDDL und EDDM diese Schranke, EDDH (29,6 m) und die Rollkarte von EDDM (74 m)
nicht.

### 5.7 Mehrere Blätter derselben Sorte

Es gewinnt das Blatt mit dem kleinsten Restfehler. Zeigen zwei Blätter verschiedene
Ausschnitte desselben Platzes (EDDV), wird das andere verworfen — Zusammensetzen ist
ausgeschlossen (Abschnitt 1.2).

### 5.8 Plätze mit einer Bahn

Sechs der geprüften Plätze haben nur eine Bahn und liefern damit zwei Passpunkte: bestimmt,
aber unprüfbar. Für sie kommt ein drittes Merkmal hinzu: **das ARP-Kreuz**, das auf jedem
Blatt eingezeichnet und mit „ARP" beschriftet ist. Seine echte Koordinate steht in
`airportsdata` und in OpenAIP.

Mit ARP sind es drei Punkte, sechs Gleichungen, zwei Freiheitsgrade — die Passung wird
**prüfbar**. Das ist der Gewinn, nicht die höhere Genauigkeit.

Das ARP-Kreuz zu finden ist eigene Bildanalyse mit eigener Fehlerquelle. Es steht deshalb als
abtrennbarer Schritt im Plan: Fällt er weg, verlieren diese sechs Plätze ihr Overlay, alle
übrigen bleiben unberührt.

---

## 6. Genordete Ablage

Das Rohblatt wird um `drehung` gedreht (`Image.rotate(winkel, expand=True,
resample=BICUBIC, fillcolor=weiß)`) und in dieser Form abgelegt. Danach ist es ein
nordorientiertes Rechteck und `L.imageOverlay` genügt.

Zwei Folgen, die im Plan Tests brauchen:

- **Die Blattgrenzen wachsen.** `expand=True` vergrößert das Bild; die Ecken des gedrehten
  Blattes bestimmen `nord/sued/west/ost`. Bei 37° Drehung wächst die Fläche um rund 60 %.
- **`feld_*` ist nicht `nord/sued/west/ost`.** Die Feldgrenzen sind die Hülle der erkannten
  Bahnen zuzüglich eines Saums von 1 km, nicht die Blattgrenzen. Danach schaltet die
  Automatik: Das Blatt zeigt nach dem Drehen viel Weißraum, und über dem würde die Karte
  sonst schon einschalten, während der Platz noch weit weg ist.

Dieselbe Verwechslung — Blattgrenzen gegen Feldgrenzen — steckte hinter dem
45-Prozent-Maßstabsfehler der Sichtflugkarten. Sie darf hier nicht wiederkehren.

---

## 7. Schutz der Handkorrektur

**Festlegung des Nutzers vom 30.08.2026:**

> „Eine manuell durchgeführte Korrektur darf nicht einfach überschrieben werden! Wenn es eine
> neue Version gibt, kann diese zur Prüfung angezeigt werden. Aber keinesfalls erneut
> verzerrt werden!"

Das gilt **für beide Kartentypen**, also auch für die 171 handgepassten Sichtflugkarten.

### 7.1 `quelle == "hand"` ist eine Sperre

Kein automatischer Pfad schreibt über eine Zeile mit `quelle = 'hand'`. Weder der
Auffrischlauf noch der Seitenwähler, und ausdrücklich auch dann nicht, wenn die Automatik ein
Ergebnis liefert. Die Sperre wird an genau einer Stelle geprüft, damit sie nicht an drei
Stellen auseinanderlaufen kann.

Was bleibt erlaubt: das **Bild** unter einer bestehenden Handpassung auffrischen, wenn
`zeigt_denselben_ausschnitt` nachweist, dass es dieselbe Karte ist. Das ist keine Änderung
der Passung und war der Grund für Regel 4 in `scripts/aip_bestand.py`.

### 7.2 Zwei belegte Lücken im heutigen Code

| Ort | Was passiert |
|---|---|
| `scripts/aip_bestand.py`, letzter Zweig | Gelingt die Automatik, wird bedingungslos mit `quelle="auto"` geschrieben — ohne Blick auf `alt["quelle"]`. Die Sicherung davor (`geometrie_gleich`) kann bei Handpassungen **prinzipiell nie greifen**, weil `handpassung()` `tick_px_lat` und `tick_px_lon` als Null ablegt und gegen gemessene ~219 verglichen wird. |
| `app/main.py`, Seitenwähler | Die Handpassungs-Sicherung hängt an `passung is None`. Liefert die Automatik auf der gewählten Seite ein Ergebnis, ist die Handpassung weg — auch bei unverändertem Bild. |

Ob eine davon die EDDL-Passung des Nutzers erwischt hat, ist **nicht nachweisbar**:
`aip_charts` führt keine Historie, `geprueft_am` wird bei jedem Schreiben überschrieben. Der
Auffrischlauf war es nachweislich nicht — siehe 8.1.

### 7.3 Der Vorschlagsweg

Findet die Automatik für eine handgepasste Karte ein neues Blatt mit abweichender Passung:

1. Passung rechnen, aber **nicht** in `aip_charts`/`aip_ground_charts` schreiben.
2. Zeile in `aip_chart_vorschlaege` anlegen, Bild als `<ICAO>.vorschlag.png` ablegen.
3. Im Admin erscheint der Vorschlag mit beiden Blättern nebeneinander.
4. Übernehmen ist ein ausdrücklicher Handgriff. Erst er schreibt und setzt `quelle = 'auto'`.

Live geht bis dahin nichts davon.

---

## 8. Auffrischlauf

### 8.1 Der bestehende Job hat noch nie gearbeitet

`app/poller.py` meldet ihn als `"interval", weeks=1` an — **ohne `next_run_time`**.
APScheduler plant den ersten Lauf damit eine Woche nach dem Anmelden, und angemeldet wird bei
jedem Containerstart neu. FriesenSpy wird deutlich häufiger als wöchentlich deployt.

Belegt durch den Bestand: Von 446 Karten trägt keine ein `geprueft_am` nach dem 25.08.2026,
außer der einen, die der Nutzer am 30.08. von Hand gepasst hat. Ein Durchlauf hätte alle 446
angefasst.

**Zu ändern:** `next_run_time` auf wenige Minuten nach dem Start setzen. Der Lauf ist
ohnehin arbeitsarm, solange sich kein `quell_hash` geändert hat.

Diese Reparatur ist die Voraussetzung dafür, dass Abschnitt 7 überhaupt gebraucht wird — und
gleichzeitig der Grund, sie nicht ohne ihn auszuliefern.

### 8.2 Regeln

Es gelten die vier Regeln aus `scripts/aip_bestand.py` sinngemäß, ergänzt um:

5. **Handpassung ist unantastbar** (Abschnitt 7). Verdrängt die bisherige Regel 3, soweit
   diese eine Handpassung durch eine Automatikpassung ersetzen ließ.

---

## 9. Schnittstellen

| Methode und Pfad | Zweck |
|---|---|
| `GET /api/aip-ground-charts` | Metadaten der gepassten Blätter. Form wie `/api/aip-charts`, zusätzlich `sorte`. |
| `GET /aip-ground-chart/{icao}.png` | Das genordete Blatt. `Cache-Control: private` wie beim Vorbild — die Beschränkung auf angemeldete Nutzer trägt das rechtliche Argument. |
| `GET /api/admin/aip-ground-charts` | Liste mit Status, Sorte, Restfehler, Bahnenzahl. Nur die Felder, die der Admin braucht (die Vollzeile hat bei den Sichtflugkarten 209 KB ergeben und die Seite lahmgelegt). |
| `GET /api/admin/aip-ground-charts/{icao}/seiten` | Kapitelseiten mit Vorschau zur Auswahl. |
| `POST /api/admin/aip-ground-charts/{icao}/seite` | Seite festlegen. |
| `POST /api/admin/aip-ground-charts/{icao}` | Handpassung: zwei geklickte Punkte mit ihren Koordinaten, dazu die Drehung. |
| `GET /api/admin/aip-vorschlaege` | Offene Vorschläge beider Kartentypen. |
| `POST /api/admin/aip-vorschlaege/{id}/uebernehmen` | Vorschlag übernehmen. |
| `DELETE /api/admin/aip-vorschlaege/{id}` | Vorschlag verwerfen. |

Nach jeder ändernden Operation `broadcast_sse({"type": "aip_charts"})` — ohne das erscheint
eine frisch gepasste Karte im Kniebrett erst nach einem Neuladen, das dort innerhalb einer
Sim-Sitzung nie stattfindet.

---

## 10. Frontend

### 10.1 Eigene Ebene, geteilte Mechanik

Ein zweiter Eintrag `liveOverlays['Flugplatzkarte']` neben `liveOverlays['Sichtflugkarte']`.
Die Mechanik der Sichtflugkarten-Ebene wird geteilt, nicht kopiert: Nachführen nach Position,
Hysterese am Feldrand, Festnageln, Wegklicken, Deckkraftregler und Marken haben dort bereits
je einen Kommentar, der einen Nutzerbefund festhält. Zwei Fassungen davon würden auseinander
laufen.

### 10.2 Automatik: ersetzt, schaltet zurück

Liegt die eigene Position im `feld_*` einer Flugplatzkarte, erscheint sie und die
**Sichtflugkarte wird ausgeblendet**. Beim Verlassen des Feldes kehrt die Sichtflugkarte
zurück. Nur eine Karte gleichzeitig — zwei halbtransparente Blätter übereinander sind nicht
lesbar, und beim Rollen trägt die Sichtflugkarte nichts.

Die Hysterese von 0,02° aus der Sichtflugkarten-Ebene ist hier zu grob: 2 km sind größer als
mancher Platz. Für die Flugplatzkarte gilt **0,003°**, rund 300 m.

Die Sichtflugkarte bleibt dabei als Ebene eingeschaltet; sie wird nur verdeckt. Andernfalls
stünde nach der Landung ein Häkchen aus, das der Nutzer nie weggeklickt hat.

### 10.3 Marke in Magenta

Zweites Symbol nach dem Vorbild von `.aip-marke`, aber in Magenta statt `#2d9cdb`. Hohl wie
das Vorbild und aus demselben Grund: Es liegt über dem Platz, ein Vollsymbol deckte genau die
Stelle zu, auf die es ankommt. Gefüllt erst, wenn das Blatt festgenagelt ist.

Für die Kontrastprüfung gilt dieselbe Doppellast wie bei `.aip-marke`: Das Symbol muss über
dem hellen Kartenblatt und über der dunklen Grundkarte stehen.

---

## 11. Admin

Eine Ansicht neben der bestehenden Sichtflugkarten-Liste, mit denselben Handgriffen:
Seitenauswahl, Handpassung durch Klicken zweier Punkte, Vorbelegung aus dem Bestand.

Zwei Dinge kommen hinzu:

- **Der Restfehler steht in der Liste.** Er ist die einzige Zahl, an der ein Mensch von außen
  erkennt, ob eine automatische Passung sitzt.
- **Die Vorschlagsliste** aus Abschnitt 7.3, mit beiden Blättern nebeneinander.

Die Handpassung braucht hier einen Punkt mehr als bei den Sichtflugkarten: Zwei Punkte plus
Drehung. Die Drehung folgt aus den beiden Punkten, wenn ihre Koordinaten bekannt sind —
gefragt wird also nach zwei Punkten, nicht nach einem Winkel. Ein Winkel ist nichts, was
jemand auf einer Karte ablesen kann.

---

## 12. Was im Repo landet

| Datei | Verantwortung |
|---|---|
| `app/ground_charts.py` (neu) | Bahnfarbe, Flächen, Achsen, Zuordnung, Prüfkette, Nordung — ohne DB- und FastAPI-Bezug, wie `aip_charts.py` |
| `app/data/ground_chart_kopf/*.png` (neu) | Kopfmuster je Sorte, Abschnitt 4.2 |
| `app/database.py` | zwei Tabellen, Lese- und Schreibfunktionen, **die Sperre aus 7.1 an einer Stelle** |
| `app/main.py` | die Endpoints aus Abschnitt 9, dazu die Lücke im Seitenwähler |
| `app/poller.py` | `next_run_time` (8.1), zweiter Auffrischjob |
| `scripts/aip_bestand.py` | die Lücke aus 7.2 |
| `scripts/ground_chart_bestand.py` (neu) | Erstbefüllung und Auffrischung |
| `scripts/ground_chart_probe.py` (neu) | der Prototyp der Vorabprobe, als Beleg der Messwerte aus Abschnitt 2 |
| `app/static/index.html` | Ebene, Automatik, Marke |
| `app/static/admin.html` | Liste, Handpassung, Vorschläge |
| `tests/test_ground_charts.py` (neu) | Bildanalyse und Prüfkette |
| `tests/test_ground_chart_api.py` (neu) | Endpoints |
| `tests/test_handpassung_schutz.py` (neu) | **die Sperre aus 7.1, für beide Kartentypen** |

---

## 13. Vorgaben

- **Keine neue Abhängigkeit.** Pillow, httpx, airportsdata, APScheduler sind vorhanden.
- **Echte Namen:** `init_db(db_path: str)` nimmt einen Pfad, `get_connection(db_path: str)`
  (es gibt kein `get_conn`), `settings.DB_PATH` (es gibt kein `settings.DATEN_PFAD`).
- **Es gibt kein `tests/conftest.py`.** Fixtures je Testdatei, DB über `tmp_path`.
- `conn = get_connection(...)` / `try` / `finally: conn.close()`. `with conn` ist in sqlite3
  eine Transaktion, kein Close.
- Deutsche Bezeichner und Kommentare im neuen Modul.
- **`"highlight": false`** in jedem Changelog-Eintrag, ohne Ausnahme.
- Kein `localStorage` im Frontend — `_prefLies` / `_prefSchreib`.
- Frontend-Tests binden an Deklarationen, nicht an Kommentare.

---

## 14. Offene Risiken

1. **Die Ausbeute ist heute zu klein.** Zwei von rund zehn Blättern unter 15 m. Der Plan muss
   EDDH (29,6 m) und die Rollkarte von EDDM (74 m) untersuchen — beide haben zwei erkannte
   Bahnen, es liegt also nicht an fehlenden Passpunkten. Wenn sich zeigt, dass die
   abgetasteten Enden systematisch neben den Schwellen liegen (Stopways und Blast Pads sind
   in derselben Farbe gezeichnet), ändert das Abschnitt 5.4.
2. **Der Kopfvergleich ist noch nicht vermessen** (4.2).
3. **Die Rollkarten mit drei Blättern** (EDDV) liefern nach dieser Spec ein Blatt und
   verwerfen zwei. Ob das brauchbar ist, weiß erst der Nutzer im Sim.
4. **OurAirports ist eine Fremdquelle ohne Zusage.** Fällt sie aus, sind neue Passungen
   unmöglich; bestehende bleiben unberührt. Die Datei gehört deshalb zwischengespeichert,
   wie es `scripts/nearby_airports.py` bereits tut.
5. **Der reparierte Auffrischjob fasst 446 Sichtflugkarten an**, sobald er läuft. Er darf
   erst zusammen mit der Sperre aus Abschnitt 7 in Betrieb gehen, sonst tut er beim ersten
   Lauf genau das, was der Nutzer verboten hat.
