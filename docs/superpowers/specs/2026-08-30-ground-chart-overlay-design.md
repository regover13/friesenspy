# Flugplatzkarten als Karten-Overlay — Design

**Stand:** 30.08.2026, Fassung 2 nach zwei Gutachten
**Vorgänger:** [`2026-08-23-aip-karten-overlay-design.md`](2026-08-23-aip-karten-overlay-design.md)
(Sichtflugkarten). Dieses Dokument baut darauf auf und ändert es an einer Stelle: dem Schutz
der Handpassung, Abschnitt 7.

**Zwei Vorhaben, zwei Pläne.** Abschnitt 7 und 8 beschreiben den **Schutz der
Handkorrektur** — er betrifft die 444 bestehenden Sichtflugkarten, ist ohne alles andere
lieferbar und hat einen eigenen Plan. Der Rest beschreibt den **Neubau**. Die Kopplung geht
nur in eine Richtung: Der Neubau braucht den reparierten Auffrischlauf, der Schutz braucht
den Neubau nicht.

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

| Sorte | Titel auf dem Blatt | Inhalt |
|---|---|---|
| Flugplatzkarte | „Flugplatzkarte / Aerodrome Chart" | Bahnen mit Maßen, Vorfelder, Gebäude, LOC-Antennen, Umgebung |
| Rollkarte | „Flugplatzrollkarte / Aerodrome Ground Movement Chart" | Rollleitlinien farbcodiert, Haltepunkte, Standplätze einzeln nummeriert, Spannweitenbeschränkungen |

**Nicht jeder Platz hat beide.** EDDL hat nur die Flugplatzkarte, EDDV nur Rollkarten (drei
Blätter), EDDM und EDDN je eine von beiden.

Aufgenommen werden beide. **Die Rollkarte hat Vorrang**, weil sie beim Rollen mehr trägt;
fehlt sie, tritt die Flugplatzkarte an ihre Stelle. Im Ebenen-Menü steht deshalb nur **ein**
Eintrag „Flugplatzkarte".

### 1.2 Abgrenzung

Ausdrücklich **nicht** Teil dieses Vorhabens:

- Mehrblattrige Rollkarten zusammensetzen. EDDV hat drei Blätter mit Ausschnitten. Ein Blatt
  je Platz und Sorte, das andere wird verworfen (Abschnitt 5.8).
- Anflugkarten, Hindernisblätter, Textseiten des Kapitels.
- Plätze außerhalb Deutschlands. Die Quelle ist die DFS.

---

## 2. Was gemessen wurde

Die Machbarkeit wurde am 30.08.2026 an 31 Blättern von 14 Verkehrsflughäfen geprüft, bevor
dieses Dokument entstand. Der Prototyp liegt als `scripts/ground_chart_probe.py` im Repo.

### 2.1 Die Sichtflugkarten-Automatik greift hier nicht

Sie liest Grad-Zahlen an den Gradnetz-Ticks des Kartenrahmens. **Flugplatzkarten haben kein
Gradnetz** — keine Ticks, keine Grad-Beschriftung, keinen vergleichbaren Rahmen. Es gibt nur
einen Maßstabsbalken, ein ARP-Kreuz und eine Missweisungsrose.

Das ist auch der Grund, warum dieses Design nirgends ein Zeichen liest. Die Ziffernerkennung
der Sichtflugkarten hat 171 von 446 Blättern der Handarbeit überlassen.

### 2.2 Die Blätter sind gedreht, nicht genordet

Sie sind so gesetzt, dass die Hauptbahn waagerecht liegt. Gemessene Kartendrehung:

| Platz | Bahnrichtung | Drehung des Blattes |
|---|---|---|
| EDDL | 052,7° | 322,8° (also −37,2°) |
| EDDM | 083,4° | 353,5° (also −6,5°) |
| EDDH | 152,9° | 90,0° |

`L.imageOverlay` kann nicht rotieren. Das Blatt wird deshalb **genordet abgelegt**
(Abschnitt 6).

### 2.3 Die Bahnen sind im Bild sauber zu fassen

Ein Histogramm über EDDL zeigt einen einzelnen dominanten Mittelgrauton: **Wert 153 mit
3,7 % Flächenanteil**, während jeder Nachbarwert bei 0,2 bis 0,4 % liegt. Ein senkrechter
Schnitt durch die Blattmitte trifft genau zwei Bänder dieser Farbe von je 28 px Breite — die
beiden Bahnen, 45 m breit, also 1,6 m je Pixel.

Der Ton ist **nicht konstant**: Flugplatzkarte 153/154, Rollkarte 179/180. Er wird gemessen,
nicht festgelegt (Abschnitt 5.2).

### 2.4 Restfehler der fertigen Passung

| Blatt | Sorte | Restfehler | Bahnen erkannt |
|---|---|---|---|
| EDDL | Flugplatzkarte | **5,7 m** | 2 |
| EDDM | Flugplatzkarte | **6,6 m** | 2 |
| EDDH | Flugplatzkarte | 29,6 m | 2 |
| EDDM | Rollkarte | 74,0 m | 2 |

Zum Maßstab: Eine Bahn ist 45 m breit, ein Rollweg 23 m.

**Zwei von rund zehn echten Flugplatzkarten sitzen heute unter 15 m.** Das Verfahren ist
belegt, seine Robustheit nicht.

**Diese Zahlen enthalten einen bekannten Modellfehler.** Der Prototyp rechnet mit festen
Metern je Breitengrad (Abschnitt 5.1); der daraus folgende Anisotropiefehler von rund 0,45 %
trägt bei einem langgestreckten Layout wie EDDL etwa 1 m bei, bei einem großflächigen Platz
mit kreuzenden Bahnen bis zu 5 m. Nach der Korrektur werden die Werte also eher besser
ausfallen — die Tabelle ist eine Obergrenze, keine Punktschätzung.

### 2.5 Die Prüfungen wirken — mit einer Einschränkung

Vier Passungen mit 229 m, 793 m, 849 m und 1152 m Fehler wurden von den Prüfungen aus
Abschnitt 5.7 abgewiesen, statt still zu erscheinen. Das Verfahren scheitert **erkennbar**.

**Die Maßstabsprüfung schaltet sich allerdings still ab**, sobald nur eine Bahn unverstümmelt
gemessen wurde (Randlage, mehrblattrige Rollkarte). Sie ist dann wirkungslos, ohne dass es
auffällt. Abschnitt 5.7 Punkt 5 sagt, was stattdessen gilt.

### 2.6 Umfang

Ein Durchlauf über alle 446 Einträge in `airport_links` (30.08.2026, ohne einen einzigen
Abruffehler) findet **61 Plätze** mit mindestens einem Blatt in Frage kommender Größe,
14 davon mit mehreren.

---

## 3. Datenmodell

### 3.1 Eigene Tabelle

`aip_ground_charts`, **nicht** eine Erweiterung von `aip_charts`. Die Felder sind zu
verschieden: keine Ticks, keine Rahmen, dafür Drehwinkel, Maßstab, Sorte, Restfehler.

```sql
CREATE TABLE IF NOT EXISTS aip_ground_charts (
    icao          TEXT PRIMARY KEY,
    sorte         TEXT NOT NULL,        -- 'rollkarte' oder 'flugplatzkarte'
    seite_url     TEXT NOT NULL,        -- gewaehlte Kapitelseite; Teil der Handkorrektur
    quell_hash    TEXT NOT NULL,        -- SHA-256 des ROHblatts. DAS ist der Aenderungs-
                                        -- detektor -- siehe die Warnung unten.
    bild_hash     TEXT NOT NULL,        -- SHA-256 des genordeten Blatts, nur fuer die URL
    nord          REAL NOT NULL,        -- Grenzen des genordeten Blatts fuer L.imageOverlay
    sued          REAL NOT NULL,
    west          REAL NOT NULL,
    ost           REAL NOT NULL,
    feld_nord     REAL NOT NULL,        -- Huelle der Bahnen plus Saum: danach schaltet die
    feld_sued     REAL NOT NULL,        -- Automatik. NICHT die Blattgrenzen.
    feld_west     REAL NOT NULL,
    feld_ost      REAL NOT NULL,
    drehung       REAL NOT NULL,        -- Grad; Vorzeichenkonvention siehe Abschnitt 6
    mps           REAL NOT NULL,        -- Meter je Pixel im ROHblatt
    rest_max      REAL NOT NULL,        -- groesster Restfehler in Metern
    bahnen        INTEGER NOT NULL,     -- Zahl der zur Passung verwendeten Bahnen
    quelle        TEXT NOT NULL,        -- 'auto' oder 'hand'
    airac         TEXT NOT NULL,
    status        TEXT NOT NULL,        -- 'gepasst' oder 'ungepasst'
    geprueft_am   TEXT
);
```

**`bild_hash` darf nie als Änderungsdetektor dienen.** Er hängt am Resampling des Drehens:
Ein Pillow-Update ändert ihn ohne jede inhaltliche Änderung und löste damit eine Neupassung
des ganzen Bestands aus. Dafür ist `quell_hash` da. `bild_hash` ist nur der Cache-Schlüssel
in der Bild-URL.

**Ein ungepasstes Blatt hat keine Drehung.** `status = 'ungepasst'` heißt: Die Prüfkette ist
nicht durchgekommen, es gibt keine bekannte Nordung, und das Blatt liegt **roh** ab. Die
Zahlenfelder tragen dann Nullen. Der Admin passt auf dem Rohblatt (Abschnitt 11); die
Nordung entsteht erst aus seinen Klicks.

### 3.2 `aip_charts` bekommt `seite_url`

**Die Seitenwahl ist Teil der Handkorrektur und geht heute verloren.** `_AIP_FELDER`
(`app/database.py:6525`) enthält keine URL. Wählt der Admin für EDDK bewusst Seite 4, merkt
sich `aip_charts` das nicht; der nächste Auffrischlauf ruft `blatt_beschaffen(url, …)` und
die nimmt wieder „die erste Seite, deren Passung durchgeht" — also erneut die falsche.

Das geschieht, **ohne dass `quelle` je auf `hand` stand**, und wird von der Sperre aus
Abschnitt 7 deshalb nicht erfasst. `aip_charts` bekommt dieselbe Spalte wie
`aip_ground_charts`, und der Auffrischlauf bevorzugt sie.

### 3.3 Vorschläge

```sql
CREATE TABLE IF NOT EXISTS aip_chart_vorschlaege (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    art           TEXT NOT NULL,        -- 'sichtflug' oder 'ground'
    icao          TEXT NOT NULL,
    quell_hash    TEXT NOT NULL,
    passung       TEXT NOT NULL,        -- JSON; die Form haengt an 'art'
    grund         TEXT NOT NULL,
    zustand       TEXT NOT NULL,        -- 'offen' oder 'verworfen' -- siehe unten
    gefunden_am   TEXT NOT NULL,
    UNIQUE(art, icao, quell_hash)
);
```

**Verwerfen löscht nicht, es setzt `zustand = 'verworfen'`.** Ein `DELETE` wäre wirkungslos:
`UNIQUE` verhindert Doppel nur, solange die Zeile existiert — der nächste Wochenlauf fände
denselben unveränderten `quell_hash` und legte den Vorschlag sofort wieder an. Die Liste
wäre nach dem ersten Verwerfen dauerhaft unaufräumbar. Ein Grabstein hält den Fund fern, bis
sich das Rohblatt wirklich ändert.

Das Blatt zum Vorschlag liegt als **`<ICAO>.<art>.<quell_hash[:12]>.png`**. Weder `art` noch
`quell_hash` dürfen im Dateinamen fehlen: Zu einer ICAO können gleichzeitig ein
Sichtflug- und ein Ground-Vorschlag offen sein, und zu jeder Art mehrere Rohblätter.

---

## 4. Beschaffung: welches Blatt ist eine Flugplatzkarte?

Die Kapitelseiten kommen über die bestehende Kette: `airac_url` → `seiten_des_kapitels` →
`bild_aus_html`.

### 4.1 Nicht über die Bildgröße

Die Blätter liegen zwischen 1240×1754 und 3800×1170; Anflugkarten liegen im selben Bereich.
Die Größe taugt als Vorfilter, nicht als Entscheidung.

### 4.2 Über den Kopfbereich, ohne ein Zeichen zu lesen

Der Titel steht bei allen Blättern **an derselben Stelle oben links und in derselben
Setzung**. Verglichen wird der Anteil übereinstimmender Pixel gegen zwei hinterlegte Muster,
nicht ein Hash — ein einzelnes verändertes Pixel darf die Erkennung nicht kippen.

Die Muster liegen als PNG unter `app/data/ground_chart_kopf/`. Sie gehören ins Repo, nicht
in die Datenbank: Sie sind Programmbestandteil und müssen nach einem Neuaufbau des Volumes
vorhanden sein.

**Bekannte Schwäche.** Eine Voruntersuchung über einen Hash desselben Ausschnitts hat vier
Cluster über Blätter geliefert, die alle Flugplatzkarten sein müssten — der Ausschnitt war
nach Augenmaß gewählt und traf bei den breiteren Blättern Weißraum. Der Ausschnitt muss
**vermessen** werden, über die ganze Breitenspanne von 1240 bis 3800 px.

### 4.3 Der Admin sticht die Automatik

Die gewählte URL steht in `seite_url` und wird beim Auffrischen bevorzugt (Abschnitt 3.2).

---

## 5. Passung über die Bahngeometrie

### 5.1 Referenz beschaffen

Bahnschwellen aus **OurAirports** (`runways.csv`). Diese Quelle ist im Projekt bereits in
Gebrauch (`scripts/nearby_airports.py`), es kommt kein neuer Lieferant hinzu.

Geprüft am 30.08.2026: Alle 15 untersuchten Verkehrsflughäfen haben Schwellenkoordinaten,
meist für jede Bahn; die daraus gerechneten Bahnlängen stimmen auf wenige Meter mit der
Längenangabe derselben Zeile überein.

**OpenAIP scheidet aus.** Es liefert keine Schwellenkoordinaten, nur `trueHeading` — für
EDDL den Wert 50 bei tatsächlich 052,7°. Drei Grad sind auf 3 km 150 m.

**Der Zwischenspeicher gehört neben die Datenbank**, nicht nach `scripts/.cache/` wie bei
`nearby_airports.py`. Dieses Verzeichnis steht in `.gitignore` und ist im Container eine
Image-Schicht: bei jedem Deploy weg, also bei jedem Containerstart neu zu laden. Richtig ist
`Path(DB_PATH).parent`, aus demselben Grund, aus dem `blatt_pfad` dorthin zeigt.

**Die Meterumrechnung braucht den richtigen Meridiangrad.** Der Prototyp rechnet mit dem
Äquatorwert 110540 m; der Meridiangrad beträgt bei 47,5–55° N aber 111 181 bis 111 324 m —
ein Fehler von 0,58 bis 0,70 %. Zusammen mit dem Längengrad-Fehler von 0,2 % ergibt das eine
**Anisotropie von rund 0,45 %, die eine Ähnlichkeitstransformation prinzipiell nicht
absorbieren kann**: bis zu 5 m auf einem großflächigen Platz, also ein Drittel der
Restfehler-Schranke, völlig ohne Not. Richtig sind die üblichen Reihen

```
meridian(φ) = 111132,95 − 559,82·cos 2φ + 1,175·cos 4φ
laengen(φ)  = 111412,84·cos φ − 93,5·cos 3φ
```

und `φ` je Punktpaar, nicht einmal fest an der ersten Schwelle — über 3 km Nordausdehnung
sind das nochmals rund 2 m Scherung.

### 5.2 Bahnfarbe messen

Der häufigste Grauwert zwischen 100 und 210, wenn er mindestens 0,6 % einer Stichprobe
(jedes dritte Pixel je Achse) ausmacht. Ergebnisse: 153/154 auf Flugplatzkarten, 179/180 auf
Rollkarten. Wird kein solcher Ton gefunden, ist das Blatt keine Flugplatzkarte.

### 5.3 Bahnflächen finden

Zusammenhangskomponenten in dieser Farbe (± 6), zeilenweise Läufe mit Union-Find.
Bahnkandidat ab 8000 Pixeln, Breite ab 4 px, Verhältnis Länge zu Breite ab 8.

Reines Pillow, wie `app/aip_charts.py`. **Keine neue Abhängigkeit** — numpy, scipy und
OpenCV sind im Projekt nicht vorhanden und werden es nicht.

### 5.4 Achse und Enden

Die Längsachse folgt aus den zweiten Momenten. Gemessen: Die Achsen zweier Parallelbahnen
desselben Blattes stimmen auf **0,01° bis 0,06°** überein — der Winkel ist die
verlässlichste Größe der ganzen Kette.

Die Fläche selbst ist es nicht: Rollwegabzweige und Markierungen trennen sie, gemessene
Längen fielen bis zu 24 % zu kurz aus. Die Enden werden deshalb **entlang der Achse
abgetastet**. Bei EDDL hob das die Länge von 1414 auf die richtigen 1769 px.

**Toleranzen gehören in Meter, nicht in Pixel.** Die erlaubte Lücke von 60 px sind bei
1,6 m/px rund 96 m, bei 2,6 m/px rund 156 m — bei Blattbreiten von 1240 bis 3800 px schwankt
dieselbe Zahl real zwischen etwa 60 und 190 m. Dasselbe gilt für den Randsaum von 45 px
(Abschnitt 5.6). Beide werden über eine Grobskala umgerechnet, die vor dem Abtasten aus der
längsten Komponente und der längsten Referenzbahn schätzbar ist.

**Zwei Wege, auf denen das Abtasten überschießt:**

- **Ohne jede Lücke.** Wendehämmer, Stopways und Blast Pads schließen unmittelbar an und
  sind gleichfarbig gezeichnet. Sie werden immer mitgemessen, unabhängig vom
  Lückenparameter. Das ist die wahrscheinlichste Ursache der 29,6 m bei EDDH und der 74 m
  bei der EDDM-Rollkarte (Abschnitt 14.1).
- **Mit Lücke.** Jede gleichfarbige Fläche innerhalb der Toleranz hinter dem Ende, die die
  geforderte Querabdeckung erreicht, verbindet den Scan wieder. Ein 23-m-Rollweg senkrecht
  über die verlängerte Achse einer 45-m-Bahn deckt 51 % — die Schwelle von 55 % steht also
  **ohne Sicherheitsabstand direkt neben dem häufigsten Störer**. Schräg kreuzend oder mit
  Schultern liegt er darüber. Die Schwelle gehört auf 70 % angehoben und der Wert im Test
  gegen einen gezeichneten Querrollweg belegt.

**Die Notbremse darf kein Ergebnis liefern.** Läuft der Scan bis an die Abbruchgrenze, gibt
der Prototyp `u − r·leer` als „Ende" zurück — einen Wert mitten im Nirgendwo. Richtig ist,
die Bahn zu verwerfen.

### 5.5 Zuordnung durchprobieren — auf beiden Seiten

Welche Bildbahn welcher echten Bahn entspricht, wird nicht geraten. Alle Zuordnungen und
beide Laufrichtungen je Bahn werden durchgerechnet; es gewinnt die mit dem kleinsten
Restfehler. Ein Sortieren nach Länge hat bei EDDV zwei verschiedene Maßstäbe für dasselbe
Blatt geliefert und die Passung um 145 m verfehlt.

**Auch die Bildseite muss in die Auswahl.** Der Prototyp permutiert nur die Referenzbahnen
und nimmt auf der Bildseite immer die vier längsten Achsen. Eine lange Nicht-Bahn im
Bahnton — eine Vorfeldkante, auf Rollkarten ein Rollleitlinien-Band — verdrängt dann eine
echte Bahn, und keine Permutation der anderen Seite kann das heilen. Das ist eine plausible,
noch ungeprüfte Spur für die 74 m der EDDM-Rollkarte.

**Nahe beieinanderliegende Achsen werden vorher zusammengefasst.** Eine durch Abzweige
zerteilte Bahn liefert mehrere Komponenten, deren Abtasten alle auf dieselben Vollenden
zieht — zwei praktisch gleiche Achsen, welche die Permutation auf zwei verschiedene
Parallelbahnen legen kann.

### 5.6 Bahnenden am Blattrand

**Ein Bahnende innerhalb des Randsaums ist kein Passpunkt.** Dort ist die Bahn nur
abgeschnitten; mehrblattrige Rollkarten zeigen Ausschnitte. Die Achsrichtung geht trotzdem
ein, der Punkt nicht.

### 5.7 Die Prüfkette

Fünf Prüfungen. **Eine Karte, die eine davon nicht besteht, wird nicht angezeigt** —
dieselbe Regel wie bei den Sichtflugkarten. Eine falsch liegende Karte ist schlimmer als gar
keine, weil sie im Rollverkehr geglaubt wird.

1. **Mindestens vier Passpunkte.** Vier Punkte sind acht Gleichungen auf vier Unbekannte,
   also vier Freiheitsgrade. Zwei Punkte bestimmen die Passung exakt und lassen keinen
   Restfehler übrig — sie ist dann *unprüfbar*, nicht *richtig*. Das ist die Lage bei jedem
   Platz mit nur einer Bahn (Abschnitt 5.9).
   Einschränkung, die dazugehört: **Die vier Punkte sind nicht unabhängig.** Beide Enden
   einer Bahn teilen sich dieselbe Achsschätzung; die vier Freiheitsgrade sind statistisch
   weniger wert, als die Zahl nahelegt.
2. **Ähnlichkeit, nicht Affinität.** Vier Unbekannte: Drehung, Maßstab, zwei Verschiebungen.
   Eine Karte ist nicht geschert. Die affine Rechnung mit sechs Unbekannten hat in der
   Vorabprobe 1,7 m ausgewiesen, wo tatsächlich 5,7 m standen — sie hat **zwei statt vier
   Freiheitsgrade** und schmeichelt deshalb; zusätzlich absorbiert die Scherung genau jene
   Anisotropie, die der Meterfehler aus 5.1 erzeugt, und verdeckt damit einen echten
   Modellfehler.
3. **Die y-Achse wird gespiegelt.** Bildkoordinaten laufen nach unten, Nordmeter nach oben.
   Die Ähnlichkeitsmatrix `[[a,−b],[b,a]]` hat die Determinante `a²+b² > 0`, ist also
   **immer** orientierungserhaltend; die wahre Abbildung ist orientierungsumkehrend und
   liegt ohne Spiegelung nicht im Suchraum. Die Vorabprobe lieferte dann 59 m statt 5,7 m
   für dasselbe Blatt.
4. **Nordung: verworfen wird nur das Fenster (100°, 260°).** Der Zweck ist allein, die
   180°-Alternative auszuschließen — dafür genügt jede Marge unter 80°. Ein strenges Fenster
   (90°, 270°) wäre falsch: **EDDH liegt bei gemessenen 89,97°**, also 0,03° neben der
   Kante, bei einem Achsrauschen von 0,01 bis 0,06°. Ob die richtige Passung durchkommt,
   entschiede dort der Zufall. Der Fall ist nicht exotisch — er tritt bei jedem quer
   gedruckten, an sich genordeten Blatt auf; bei den Sichtflugkarten gibt es sieben davon.
   **Was diese Prüfung nicht kann:** Liegt die Nordung nahe 90°, liegt die Kopfüber-Variante
   nahe 270° und damit ebenfalls am Fensterrand. Bei zwei gleich langen Parallelbahnen im
   Querdruck ist die 180°-Frage dann prinzipiell nicht entscheidbar. Bei EDDH retten die
   sich kreuzenden Bahnen die Eindeutigkeit über den Restfehler; ein EDDM-artiges Layout im
   Querdruck hätte diese Rettung nicht. Eine solche Karte wird verworfen, nicht geraten.
5. **Maßstabskonsistenz — gegen den Fit, nicht nur untereinander.** Der Prototyp vergleicht
   die aus je zwei Bahnen gerechneten Maßstäbe miteinander und schaltet sich damit **still
   ab, sobald nur eine Bahn unverstümmelt ist**. Verglichen wird stattdessen jede einzelne
   Bahnskala gegen die aus dem Fit gewonnene Skala `hypot(a, b)`; dann greift die Prüfung
   auch bei einer Bahn.
   Die Schranke ist **nicht** fest 8 %. Der Malfehler an den Bahnenden ist additiv (feste
   Meter je Ende), der Skalenfehler damit umgekehrt proportional zur Bahnlänge: 120 m Anbau
   an einer 1630-m-Bahn sind 7,4 %, an einer 3000-m-Bahn 4,0 %. Eine feste Schranke verwirft
   deshalb bevorzugt richtige Passungen kurzer Bahnen. Sie wird über die Bahnlänge
   gestaffelt, mit einem festen Meterbetrag als Grundlage.

**Schranke für den Restfehler: 15 m.** Ein Drittel Bahnbreite, weniger als eine Rollwegbreite.
Darüber wird die Karte als `ungepasst` abgelegt.

### 5.8 Mehrere Blätter derselben Sorte

Es gewinnt das Blatt mit dem kleinsten Restfehler. Zusammensetzen ist ausgeschlossen.

### 5.9 Plätze mit einer Bahn

Sechs der geprüften Plätze (EDDB, EDDC, EDDE, EDDG, EDDR, EDDW) haben nur eine Bahn und
liefern zwei Passpunkte: bestimmt, aber unprüfbar. Für sie käme das **ARP-Kreuz** als
drittes Merkmal in Frage — drei Punkte, sechs Gleichungen, zwei Freiheitsgrade. Der Gewinn
ist die **Prüfbarkeit**, nicht die Genauigkeit.

Das ist ein eigenes Vorhaben mit eigener Bildanalyse und eigener Fehlerquelle. **Es hat in
diesem Design keinen Umsetzungsschritt.** Diese sechs Plätze bekommen vorerst kein Overlay;
das ist eine bewusste Lücke, kein Versehen.

---

## 6. Genordete Ablage

Das Rohblatt wird gedreht und in dieser Form abgelegt. Danach ist es ein nordorientiertes
Rechteck und `L.imageOverlay` genügt.

**Die gesamte Analyse läuft auf dem Rohblatt.** `mps` ist Meter je Pixel im Rohblatt, nicht
im gedrehten. Das Drehen ist der letzte Schritt und ändert an der Passung nichts.

Vier Punkte, die im Plan Tests brauchen:

- **Das Vorzeichen der Drehung ist zu belegen, nicht anzunehmen.** `Image.rotate` dreht
  gegen den Uhrzeigersinn. Ob 322,8 oder 37,2 zu übergeben ist, entscheidet über ein exakt
  falsch herum liegendes Blatt. Der Prototyp dreht nie — das ist ungetestet.
- **Die Füllfläche muss durchsichtig sein, nicht weiß.** `expand=True` lässt an den Ecken
  Fläche frei; bei 37° ist das rund die Hälfte des abgelegten Rechtecks. Weiß gefüllt läge
  ein großes Dreieckspaar halbdeckend über der Umgebung des Platzes. Nötig ist RGBA mit
  `fillcolor=(0,0,0,0)` und ein PNG mit Alphakanal. Die quer gedruckten Sichtflugkarten
  kennen dieses Problem nicht — 90° drehen lässt nichts frei.
- **Das Blatt wächst erheblich.** Nicht „rund 60 %", wie eine frühere Fassung dieses
  Dokuments behauptete: bei 37,2° wachsen 1754×1240 um **102 %**, 3101×1754 um **112 %**,
  3800×1170 um **171 %**. 60 % entsprächen einer Drehung um etwa 18°. Das ist für die
  Bildgröße im Browser relevant und gehört im Plan gemessen.
- **PIL rundet Größe und Versatz des gedrehten Bildes.** Die Umrechnung von Passung auf
  `nord/sued/west/ost` muss aus PILs tatsächlicher Formel folgen, nicht aus der idealen
  Hüllbox — sonst bleiben Subpixel-Verschiebungen von bis zu 1 px, hier rund 1,6 m.

**`feld_*` ist nicht `nord/sued/west/ost`.** Die Feldgrenzen sind die Hülle der erkannten
Bahnen zuzüglich eines Saums von 1 km. Nach dem Drehen zeigt das Blatt viel freie Fläche,
und über der dürfte die Automatik nicht schon einschalten. Dieselbe Verwechslung steckte
hinter dem 45-Prozent-Maßstabsfehler der Sichtflugkarten.

---

## 7. Schutz der Handkorrektur

**Festlegung des Nutzers vom 30.08.2026:**

> „Eine manuell durchgeführte Korrektur darf nicht einfach überschrieben werden! Wenn es eine
> neue Version gibt, kann diese zur Prüfung angezeigt werden. Aber keinesfalls erneut
> verzerrt werden!"

Gilt **für beide Kartentypen**, also auch für die 171 handgepassten Sichtflugkarten.

### 7.1 Die Bedingung, genau formuliert

Gesperrt ist **ein Schreibversuch mit `quelle = 'auto'` auf eine bestehende Zeile mit
`quelle = 'hand'`**.

Diese Formulierung ist nicht schmückend, sie trägt die ganze Umsetzung. Die naheliegende
Fassung „keine Zeile mit `quelle='hand'` überschreiben" bräche drei **legitime** Pfade:

- `_handblatt_auffrischen` (`scripts/aip_bestand.py:123`) — schreibt hand über hand und ist
  von dieser Festlegung ausdrücklich gedeckt: Es frischt das *Bild* auf, nachdem
  `zeigt_denselben_ausschnitt` nachgewiesen hat, dass es dieselbe Karte ist.
- `admin_set_aip_chart` (`app/main.py:4443`) — ein Mensch korrigiert seine eigene Passung.
- `scripts/aip_handpassung.py:369` — dasselbe von der Kommandozeile.

Die Prüfung sitzt in `upsert_aip_chart` selbst, nicht bei den Aufrufern: Es gibt **sieben**
Schreibpfade, und der nächste neue wäre sonst wieder ungeschützt.

### 7.2 Vier Lücken im heutigen Code

| Ort | Was passiert |
|---|---|
| `scripts/aip_bestand.py:213` | Gelingt die Automatik, wird bedingungslos mit `quelle="auto"` geschrieben — ohne Blick auf `alt["quelle"]`. |
| `app/main.py:4399` (Seitenwähler) | Die Sicherung hängt an `passung is None`. Liefert die Automatik auf der gewählten Seite ein Ergebnis, ist die Handpassung weg. |
| `scripts/aip_bestand.py:202` | Der Schutz darüber verlangt `alt["status"] == "gepasst"`. Eine Zeile mit `quelle='hand'` und `status='ungepasst'` fällt durch und wird auf `auto` genullt. |
| `scripts/aip_bestand.py:148` (`delete_aip_chart`) | Regel 2 räumt jede Karte ab, deren ICAO nicht mehr in `airport_links` steht — Zeile **und** Blatt. Für eine Handpassung ist das unwiederbringlich. |

**Zur dritten Lücke gehört, dass der Seitenwähler diesen Zustand aktiv erzeugt:**
`quelle="auto" if passung else "hand"` (`app/main.py:4400`). Scheitert die Automatik auf der
gewählten Seite, steht dort `quelle='hand'`, obwohl kein Mensch etwas gepasst hat. Das ist
die eigentliche Fehlbenennung — `'hand'` heißt dort „wartet auf Handarbeit" statt „von Hand
gesetzt". Sie gehört behoben, nicht durch eine Sonderregel in der Sperre umgangen.

**Zur vierten:** Ob `quelle='hand'` auch gegen Löschen sperrt, ist eine Entscheidung, keine
Ableitung. Vorschlag: Eine handgepasste Karte, deren Link verschwindet, wird **nicht**
gelöscht, sondern auf `status='verwaist'` gesetzt und im Admin gemeldet. Sie ist dann aus
der Anzeige, die Arbeit bleibt erhalten.

**Warum `geometrie_gleich` hier nicht hilft.** `handpassung()` legt `tick_px_lat` und
`tick_px_lon` als Null ab (`app/aip_charts.py:1620`); `geometrie_gleich` vergleicht sie mit
`_TOLERANZ_RASTER_PX = 0.5` gegen gemessene ~219 px. Regel 3 fällt für **jede** der 171
Handpassungen durch. Der Code weiß das an anderer Stelle bereits: `gerade_aus_bestand`
rechnet ausdrücklich nicht über die Tick-Werte, „weil `handpassung()` dort Nullen ablegt".
Dieselbe Einsicht ist in `geometrie_gleich` nie angekommen — **dort liegt die vorhandene
Lösung, es braucht keine neue.**

**Ob eine dieser Lücken die EDDL-Passung erwischt hat, ist nicht nachweisbar:** `aip_charts`
führt keine Historie, `geprueft_am` wird bei jedem Schreiben überschrieben.

### 7.3 Der Vorschlagsweg

Findet die Automatik für eine handgepasste Karte ein abweichendes Ergebnis:

1. Passung rechnen, aber **nicht** schreiben.
2. Zeile in `aip_chart_vorschlaege` anlegen, Bild als `<ICAO>.<art>.<hash>.png` ablegen.
3. Im Admin erscheint der Vorschlag mit beiden Blättern nebeneinander.
4. Übernehmen ist ein ausdrücklicher Handgriff. Erst er schreibt.

Live geht bis dahin nichts davon.

---

## 8. Auffrischlauf

### 8.1 Der bestehende Job hat noch nie gearbeitet

`app/poller.py:553` meldet ihn als `"interval", weeks=1` — **ohne `next_run_time`**.
APScheduler setzt dann `start_date = now + interval`, und `_register_jobs()` läuft bei jedem
Containerstart neu gegen einen `MemoryJobStore`. Erster Lauf also frühestens sieben Tage nach
dem letzten Deploy; FriesenSpy wird deutlich häufiger deployt.

**Beleg, in der richtigen Stärke:** Von 446 Karten trägt keine ein `geprueft_am` nach dem
25.08.2026, außer der einen vom 30.08. Ein Durchlauf hätte allerdings **nicht** alle 446
angefasst — `lauf()` schreibt in vier Fällen nichts (`ohne_koordinate`, `abruf_fehler`,
`kein_blatt` und, der große Posten, `hand_behalten` bei unverändertem Bild). Er hätte die
rund 273 automatisch gepassten angefasst. Da keine einzige davon neuer ist, trägt der
Schluss trotzdem.

**Die billigere Gegenprobe ist das Containerlog.** `_aip_auffrischen` protokolliert jeden
Lauf und jeden Fehlschlag. Ein Blick dorthin entscheidet die Frage direkt.

### 8.2 Der Lauf ist teuer — nicht „arbeitsarm"

Eine frühere Fassung dieses Dokuments behauptete, es falle nur Arbeit an, wenn sich ein Hash
geändert habe. **Das ist falsch: Der Hash wird erst gebildet, nachdem die ganze Arbeit
getan ist** (`scripts/aip_bestand.py:178`). Vorher läuft für **jeden** der 446 Plätze:

- mindestens zwei HTTP-Abrufe plus 0,4 s Höflichkeitspause,
- die volle Bildanalyse über `genordet_rechnen` → `passung_rechnen`,
- und bei gescheiterter Passung — also bei allen ~171 handgepassten Blättern — zusätzlich
  ein **kompletter Kapiteldurchlauf** über 4 bis 12 weitere Seiten, jede einzeln geholt und
  vermessen (`app/aip_charts.py:1544-1560`).

Realistisch sind über 1000 Abrufe gegen `aip.dfs.de` und mehrere Minuten reine CPU je Lauf.
Drei Folgen:

1. **`next_run_time` auf „wenige Minuten nach dem Start" wäre falsch.** Es machte aus dem
   Wochenjob einen Deploy-Job; an einem Tag mit zwölf Deploys wären das zwölf Vollcrawls der
   DFS. Richtig ist ein **persistenter Fälligkeitsmerker** in der Datenbank: Der Job läuft
   kurz nach dem Start nur, wenn der letzte Lauf mehr als eine Woche zurückliegt.
2. **`asyncio.to_thread` schützt weniger, als der Kommentar dort verspricht.** Die Analyse
   ist eine reine Python-Pixelschleife und hält den GIL. Ein Lauf, der zur falschen Zeit
   startet, trifft die Sitzung, die gerade fliegt.
3. **Der zweite Job ist teurer als der erste**, nicht billiger: `ground_chart_bestand` muss
   jede Kapitelseite gegen zwei Kopfmuster prüfen, während `blatt_beschaffen` bei der ersten
   passenden Seite abbricht. Beide Jobs dürfen nicht gleichzeitig laufen.

### 8.3 Der Job meldet seine Änderungen nicht

`_aip_auffrischen` ruft kein `_aip_karten_geaendert`. Sobald er tatsächlich läuft und Karten
ändert, bleibt jedes offene Kniebrett auf dem alten Stand — genau das Fehlerbild, das der
Helfer am 24.08.2026 beheben sollte.

### 8.4 Regeln

Die vier Regeln aus `scripts/aip_bestand.py` gelten sinngemäß, ergänzt um:

5. **Handpassung ist unantastbar** (Abschnitt 7). Verdrängt Regel 3, soweit diese eine
   Handpassung durch eine Automatikpassung ersetzen ließ.
6. **Die gespeicherte Seitenwahl hat Vorrang** vor der Suche nach der ersten passenden Seite.

---

## 9. Schnittstellen

| Methode und Pfad | Zweck |
|---|---|
| `GET /api/aip-ground-charts` | Metadaten der gepassten Blätter, zusätzlich `sorte`. |
| `GET /aip-ground-chart/{icao}.png` | Das genordete Blatt. `Cache-Control: private` wie beim Vorbild. |
| `GET /aip-vorschlag/{id}.png` | Das Blatt zu einem Vorschlag. **Eigener Endpunkt:** `/aip-chart/{icao}.png` kann es nicht ausliefern, dort steht `re.fullmatch(r"[A-Z0-9]{4}", code)`. |
| `GET /api/admin/aip-ground-charts` | Liste mit Status, Sorte, Restfehler, Bahnenzahl. |
| `GET /api/admin/aip-ground-charts/{icao}/seiten` | Kapitelseiten mit Vorschau. |
| `POST /api/admin/aip-ground-charts/{icao}/seite` | Seite festlegen. |
| `POST /api/admin/aip-ground-charts/{icao}` | Handpassung: zwei geklickte Punkte mit Koordinaten. |
| `GET /api/admin/aip-vorschlaege` | Offene Vorschläge beider Kartentypen. |
| `POST /api/admin/aip-vorschlaege/{id}/uebernehmen` | Vorschlag übernehmen. |
| `POST /api/admin/aip-vorschlaege/{id}/verwerfen` | **Nicht `DELETE`** — setzt `zustand='verworfen'`, siehe 3.3. |

**Nur die Felder, die der Admin braucht.** Die Vollzeile hat bei den Sichtflugkarten 209 KB
für 446 Karten ergeben und die Seite lahmgelegt.

Nach jeder ändernden Operation der vorhandene Helfer **`_aip_karten_geaendert(request)`**
(`app/main.py:4204`) — nicht `broadcast_sse` direkt; der Helfer trägt den Silent-Fail für
den Fall, dass kein Poller am `app.state` hängt.

---

## 10. Frontend

### 10.1 Der Zustand muss doppelt geführt werden

Die Sichtflugkarten-Ebene führt ihren Zustand **auf ICAO geschlüsselt und einfach
vorhanden**: `_aipKarteAktiv`, `_aipKarteFest`, `_aipKarteAus`, `_aipKarteOverlay`,
`_aipMarken` als ICAO→Marker, dazu **ein** Deckkraftregler mit **einem** Merker.

Die Sichtflugkarte EDDL und die Flugplatzkarte EDDL tragen **dieselbe ICAO**. „Mechanik
teilen" heißt deshalb nicht Wiederverwendung derselben Variablen — jeder dieser Zustände
braucht eine zweite Ausprägung. Geteilt werden die Funktionen, parametrisiert über die
Kartensorte; `_aipKarteImFeld` muss dafür die Hysterese als Argument nehmen statt sie als
Konstante einzubacken.

**Das bricht bestehende Tests.** `tests/test_aip_ui.py` bindet an `_AIP_KARTE_HYSTERESE` und
an ein gutes Dutzend weiterer `_aipKarte*`-Deklarationen. Diese Tests sind nachzuziehen,
nicht zu löschen.

### 10.2 Automatik: verdeckt, schaltet zurück

Liegt die eigene Position im `feld_*` einer Flugplatzkarte **und liegt tatsächlich ein
Blatt**, wird die Sichtflugkarte verdeckt. Die Sichtflugkarte bleibt als Ebene
eingeschaltet; sonst stünde nach der Landung ein Häkchen aus, das niemand weggeklickt hat.

Drei Zustände, die eine frühere Fassung offen ließ:

- **Die Bedingung ist „ein Blatt liegt", nicht „die Position liegt im Feld".** Ist die Ebene
  „Flugplatzkarte" im Menü abgehakt, wäre sonst die Sichtflugkarte weg und die
  Flugplatzkarte nicht da — beim Rollen bliebe die Karte leer.
- **Eine festgenagelte Sichtflugkarte schlägt die Automatik.** `_aipKarteNachfuehren` steigt
  bei festgenageltem Blatt vor jeder Positionsprüfung aus. Ein ausdrücklicher Nutzerbefehl
  darf nicht still überstimmt werden; solange eine Sichtflugkarte festgenagelt ist, bleibt
  sie sichtbar und die Flugplatzkarte tritt nicht an.
- **Wegklicken braucht zwei getrennte Merker.** `_aipKarteAus` speichert eine ICAO. Mit
  einer geteilten Variablen machte ein Wegklick der Flugplatzkarte EDDL auch die
  Sichtflugkarte EDDL unerreichbar — und die Sperre fiele nie, weil beide Automatiken
  dieselbe ICAO wollen.

**Hysterese in beide Richtungen.** Für die Flugplatzkarte gilt 0,003° statt der 0,02° der
Sichtflugkarte — 2 km sind größer als mancher Platz. Die Rückkehr der Sichtflugkarte wird
**aus der Sichtbarkeit der Flugplatzkarte abgeleitet**, nicht unabhängig geprüft; sonst
flackert sie am Feldrand bei jedem Positionsupdate.

**Der Listenplatz im Ebenen-Menü ist festzulegen.** `tests/test_aip_ui.py` fordert heute
`OpenAIP < Sichtflugkarte < Platzrunden`. Die Flugplatzkarte gehört unmittelbar hinter die
Sichtflugkarte. Die Zeilenzahl der Liste ist unkritisch — sie ist seit `max-height: 60vh`
mit erzwungener Scrollbar abgesichert.

### 10.3 Marke in Magenta

Zweites Symbol nach dem Vorbild von `.aip-marke`, in Magenta statt `#2d9cdb`, hohl aus
demselben Grund: Es liegt über dem Platz, ein Vollsymbol deckte genau die Stelle zu, auf die
es ankommt.

**Zwei Dinge sind dabei zu erledigen, nicht zu übersehen:**

- Der Kommentar bei `.aip-marke` (`index.html:2361`) hält fest, sie sei „das einzige
  klickbare Symbol dieser Karte". Das wird durch die zweite Marke falsch und ist
  mitzuändern — ein Kommentar, der lügt, ist schlimmer als keiner.
- Beide Markensätze liegen **exakt übereinander** (beide auf dem Platz) und teilen sich heute
  `_aipMarken` sowie die containerweite Klasse `.leaflet-container.aip-nah`, die pro Karte
  nur einen Nah-Zustand ausdrücken kann. Beides braucht eine zweite Ausprägung, und die
  Marken brauchen einen Versatz gegeneinander, sonst ist die untere nicht anklickbar.

---

## 11. Admin

Eine Ansicht neben der Sichtflugkarten-Liste, mit denselben Handgriffen. Zwei Dinge kommen
hinzu:

- **Der Restfehler steht in der Liste.** Er ist die einzige Zahl, an der ein Mensch von außen
  erkennt, ob eine automatische Passung sitzt.
- **Die Vorschlagsliste** aus Abschnitt 7.3, mit beiden Blättern nebeneinander.

**Die Handpassung arbeitet auf dem Rohblatt.** Ein ungepasstes Blatt hat keine bekannte
Drehung und liegt deshalb ungedreht ab (Abschnitt 3.1). Gefragt wird nach **zwei Punkten mit
ihren Koordinaten** — Drehung, Maßstab und Grenzen werden daraus *hergeleitet*, so wie
`aip_charts.handpassung()` die Blattgrenzen aus zwei Rahmenecken herleitet, statt die Klicks
direkt abzulegen. Genau an dieser Unterscheidung hing bei den Sichtflugkarten der
45-Prozent-Maßstabsfehler.

Nach einem Winkel wird nicht gefragt — den kann niemand auf einer Karte ablesen.

---

## 12. Was im Repo landet

| Datei | Verantwortung |
|---|---|
| `app/ground_charts.py` (neu) | Bahnfarbe, Flächen, Achsen, Zuordnung, Prüfkette, Nordung |
| `app/runway_ref.py` (neu) | OurAirports-Schwellen, Zwischenspeicher neben der DB |
| `app/data/ground_chart_kopf/*.png` (neu) | Kopfmuster je Sorte |
| `app/database.py` | Sperre, `seite_url` in `aip_charts`, zwei neue Tabellen |
| `app/main.py` | Endpoints, die Lücke im Seitenwähler, die Fehlbenennung `quelle='hand'` |
| `app/poller.py` | Fälligkeitsmerker, `_aip_karten_geaendert`, zweiter Job |
| `scripts/aip_bestand.py` | drei der vier Lücken aus 7.2 |
| `scripts/aip_handpassung.py` | prüfen, ob er `quelle='hand'` setzt |
| `scripts/ground_chart_bestand.py` (neu) | Erstbefüllung und Auffrischung |
| `scripts/ground_chart_probe.py` | liegt bereits im Repo, Beleg der Messwerte |
| `app/static/index.html` | Ebene, Automatik, Marke |
| `app/static/admin.html` | Liste, Handpassung, Vorschläge |
| `app/CHANGELOG.json` | je ein Eintrag, `"highlight": false` |
| `tests/test_handpassung_schutz.py` (neu) | die Sperre, für beide Kartentypen |
| `tests/test_ground_charts.py` (neu) | Bildanalyse und Prüfkette |
| `tests/test_ground_chart_api.py` (neu) | Endpoints |
| `tests/test_aip_ui.py` | nachziehen, siehe 10.1 |

**Das Blatt braucht einen eigenen Ablageort.** `<db>/aip/<ICAO>.png` ist von den
Sichtflugkarten belegt; ein Ground Chart mit derselben ICAO überschriebe sie. Vorgesehen ist
`<db>/aip_ground/<ICAO>.png`.

**`scripts/` muss weiter ins Image.** Der Dockerfile-Kommentar hält fest, dass das nur wegen
`from scripts.aip_bestand import lauf` geschieht und ein Fehlen **lautlos** scheitert, weil
der Job jede Exception schluckt. Für den zweiten Job gilt dasselbe.

---

## 13. Vorgaben

- **Keine neue Abhängigkeit.** Pillow, httpx, airportsdata, APScheduler sind vorhanden.
- **Echte Namen:** `init_db(db_path: str)` nimmt einen Pfad, `get_connection(db_path: str)`
  (es gibt kein `get_conn`), `settings.DB_PATH`. `broadcast_sse` ist eine **Methode am
  Poller**; im Endpoint wird `_aip_karten_geaendert(request)` benutzt.
- **Es gibt kein `tests/conftest.py`.** Fixtures je Testdatei, DB über `tmp_path`.
- `conn = get_connection(...)` / `try` / `finally: conn.close()`. `with conn` ist in sqlite3
  eine Transaktion, kein Close.
- Deutsche Bezeichner und Kommentare in neuen Modulen.
- **`"highlight": false`** in jedem Changelog-Eintrag, ohne Ausnahme.
- Kein `localStorage` im Frontend — `_prefLies` / `_prefSchreib`.
- Frontend-Tests binden an Deklarationen, nicht an Kommentare.

---

## 14. Offene Risiken

1. **Die Ausbeute ist heute zu klein.** Zwei von rund zehn Blättern unter 15 m. Die
   wahrscheinlichste Ursache steht in 5.4: Stopways und Blast Pads schließen gleichfarbig an
   die Bahn an und werden immer mitgemessen — der Malfehler ist additiv und trifft kurze
   Bahnen prozentual härter. Das erklärt zwanglos, warum EDDH (29,6 m) und die EDDM-Rollkarte
   (74 m) knapp danebenliegen, statt grob falsch zu sein. **Zu prüfen, bevor der Apparat
   gebaut wird.**
2. **Der Kopfvergleich ist noch nicht vermessen** (4.2).
3. **Die Rollkarten mit drei Blättern** (EDDV) liefern ein Blatt und verwerfen zwei. Ob das
   brauchbar ist, weiß erst der Nutzer im Sim.
4. **OurAirports ist eine Fremdquelle ohne Zusage.** Fällt sie aus, sind neue Passungen
   unmöglich; bestehende bleiben unberührt.
5. **Der reparierte Auffrischlauf fasst 446 Sichtflugkarten an**, sobald er läuft. Er darf
   erst zusammen mit Abschnitt 7 in Betrieb gehen.
6. **Die 180°-Frage ist bei Querdruck mit symmetrischen Parallelbahnen unentscheidbar**
   (5.7 Punkt 4). Ein solcher Platz bekommt keine Karte. Unter den 61 Kandidaten ist noch
   nicht ausgezählt, ob es ihn gibt.
