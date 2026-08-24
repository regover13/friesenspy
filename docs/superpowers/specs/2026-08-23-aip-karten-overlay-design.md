# AIP-Sichtflugkarten als Karten-Overlay — Design

**Stand:** 23.08.2026, **Fassung 2** nach unabhängigem Gutachten · **Betrifft:** neu
`app/aip_charts.py`, dazu `app/main.py`, `app/database.py`, `app/poller.py`,
`app/static/index.html`, `app/static/admin.html` · **Quelle:** Auftrag des Nutzers,
23.08.2026 · **Status:** abgestimmt, bereit für die Planung

## Ziel

Die amtliche Sichtflugkarte eines Flugplatzes liegt halbtransparent über der Karte, und das
eigene Flugzeug bewegt sich darauf — in der Weboberfläche wie im MSFS-Kniebrett.

## Abgrenzung

| Teil | Status |
|---|---|
| Kartenabruf, Georeferenzierung, Ablage im Server | umzusetzen, Kern dieses Dokuments |
| Neue Karten-Ebene mit Automatik und Deckkraft | umzusetzen |
| Admin-Maske für die Karten, die die Automatik nicht schafft | umzusetzen |
| Flächendeckende ICAO-Karte 1:500.000 | **entfällt** — nicht im freien AIP-Teil enthalten; die vorhandene nwy-tiles-Ebene leistet das bereits |
| Kachelpyramide, GeoTIFF-Export, Entzerrung, Rotation | **entfällt** (Abschnitt 8) |

## Getroffene Entscheidungen

| Frage | Entscheidung |
|---|---|
| Welche Karten? | nur die Sichtflugkarte je Platz, aus den vorhandenen `airport_links` |
| Zuschnitt | **kein Zuschnitt** — das ganze Blatt mit Kopfzeile, Frequenzen und Texten |
| Georeferenzierung | automatisch aus Rahmen und Gradnetz, Ausreißer von Hand im Admin |
| Darstellung | `L.imageOverlay`, keine Kacheln |
| Sichtbarkeit | automatisch nach Position, manuell übersteuerbar |
| Bei neuer AIRAC-Ausgabe | Passung bleibt gültig, solange die Geometrie unverändert ist |
| Koordinatenquelle | `airportsdata`, ersatzweise OpenAIP (Schlüssel liegt bereits in `config.env`) |

---

## 1. Befund: Was hinter den Links wirklich liegt

Gemessen am 23.08.2026 an allen 446 Einträgen der Tabelle `airport_links`.

**Es sind keine PDFs.** Ein Eintrag wie `aip.dfs.de/BasicVFR/pages/P0016F.html` ist eine
Weiterleitungsseite mit `<meta http-equiv="Refresh">` auf die aktuelle AIRAC-Ausgabe
(`.../BasicVFR/2026AUG20/pages/<hash>.html`). Dort steckt die Karte als **PNG in einem
`data:`-URI** im HTML — 875×1240 Pixel, etwa 105 dpi auf A4. Ein HTTP-Redirect findet nicht
statt; wer `curl -L` benutzt, bekommt die Weiterleitungsseite zurück und hält sie für die Karte.

**Die Blätter sind fast, aber nicht ganz einheitlich:** 413 der 446 Karten sind A4 hoch
(875×1240 oder 874×1240), 33 haben Sonderformate bis 1636×1240, darunter Querformate.

**Das Kartenfeld ist von einem Doppelrahmen umgeben**, im Regelfall bei x 132–817 und
y 180–865, also 685×685 Pixel. Zwischen den beiden Rahmenlinien liegen die Gradnetz-Ticks und
ihre Beschriftung („54°" über dem Strich, „14'" darunter). Die Karten sind genordet.

**Der gespeicherte Link zeigt nicht immer auf die Karte.** Bei EDAZ etwa öffnet er die
Textseite „VFR-Flugverfahren"; die Sichtflugkarte ist die vierte Seite desselben
Platz-Kapitels. Das betrifft 28 Karten.

## 2. Warum die Georeferenzierung selbst gerechnet werden muss

In den DFS-Daten steckt keine Geo-Information. Der verbreitete **AIP Browser DE**
(mpmediasoft) rechnet sie ebenfalls nicht aus, sondern lädt sie fertig: „Vordefinierte
Beschnitt- und Georeferenzierungsinformationen für alle Flugplatzseiten, bei denen dies
sinnvoll möglich ist, stehen auf unserem Server bereit" — mit dem Zusatz, für die Richtigkeit
werde keine Haftung übernommen. **Enroute Flight Navigation** lässt Nutzer die Punkte im
*GeoRef Tool* von Hand setzen. Niemand gewinnt die Passung aus der Karte selbst.

Das geht aber, in vier Schritten: Rahmen finden, Ticks finden, Maßstab aus dem Tick-Abstand,
**absolute Lage aus den Grad-Zahlen neben den Ticks**.

Der vierte Schritt ist unverzichtbar. Aus dem Verhältnis der Tick-Abstände beider Achsen folgt
zwar cos(Breite) und damit die geografische Breite auf etwa 0,1° genau — das sind aber sechs
Bogenminuten. Bei einem Tick-Abstand von einer Bogenminute bleiben damit rund **zwölf mögliche
Lagen** übrig, je 1,85 km auseinander. Ohne die gelesenen Zahlen ist die Karte nicht zu
platzieren.

**Projektionsannahme, die dabei stillschweigend gilt:** Dass aus dem Tick-Verhältnis cos(Breite)
folgt, setzt eine **konforme** Projektion mit **achsparallelem** Gradnetz voraus (Mercator,
transversale Mercator, Lambert konform). Bei einer Plattkarte wäre das Verhältnis 1 und die
Rechnung falsch. Die Annahme ist nicht dokumentiert, sondern empirisch gedeckt: Über 446 Blätter
hinweg ließen sich die Ticks mit geraden Zeilen- und Spaltenscans finden, und die gerechnete
Breite traf die Platzkoordinate im Median auf 0,085°.

## 3. Messergebnis: 410 von 446 Karten automatisch

| Weg | Karten |
|---|---:|
| direkt auf der verlinkten Seite gepasst | 356 |
| Platzkoordinate aus OpenAIP statt `airportsdata` | 26 |
| Karte auf einer anderen Seite desselben Kapitels gefunden | 28 |
| **geometrisch gepasst** | **410 von 446 = 91,9 %** |
| von Hand nachzutragen | 36 (etwa 18 Minuten) |

Von den Nordsee- und Friesen-Plätzen bleibt genau einer offen: **EDWJ**.

Diese 36 bleiben für die Handarbeit:

```
EDAT EDBK EDBT EDBX EDCQ EDCR EDDS EDEL EDEW EDGK EDGO EDGU EDGY EDHE
EDLP EDLS EDLV EDLW EDMP EDMR EDNU EDNV EDNZ EDOC EDOS EDOZ EDPI EDPS
EDQG EDUW EDVC EDVG EDVI EDWJ EDWO EDXO
```

**Diese Quote ist die der Geometrie, nicht der fertigen Passung.** Das Lesen der Grad-Zahlen
ist geprüft, aber nicht durchgerechnet (Abschnitt 3.4). Sie ist eine Obergrenze.

### 3.1 Die Prüfkette — und warum eine Probe allein nicht reicht

**Die erste Fassung dieser Spec hatte hier einen Konstruktionsfehler**, den ein unabhängiges
Gutachten aufgedeckt hat. Sie verließ sich allein auf die cos-Probe: Die aus dem Verhältnis
`dx/dy` gefolgerte Breite musste zur Platzkoordinate passen. Diese Probe prüft aber nur das
**Verhältnis** der Tick-Abstände — die Blattgrenzen entstehen vollständig aus den **gelesenen
Grad-Zahlen**, in die die Tick-Abstände gar nicht eingehen. Eine falsch gelesene Bogenminute
lässt das Verhältnis unverändert; der Probenfehler bleibt exakt null. Die Probe war blind
gegen genau den Fehler, dessentwegen sie eingebaut wurde.

Deshalb gilt eine Karte erst als gepasst, wenn sie **vier** Prüfungen besteht:

**(1) cos-Probe — Vorprüfung der Skala.** Die aus `dx/dy` gefolgerte Breite muss zur
Platzkoordinate passen, Toleranz **0,4°**. Über die 356 direkt gepassten Karten lag der Fehler
im Median bei 0,085°, der 90-%-Wert bei 0,167°, das Maximum bei 0,354°. Zusätzlich muss das
Verhältnis im Band deutscher Breiten liegen (47,3° bis 55,0°, also `v` zwischen 0,57 und 0,68) —
das kostet nichts und schneidet Unsinn früh ab.

**(2) Gleichmäßigkeit der gelesenen Werte.** Die Ticks liegen äquidistant. Also müssen auch die
Differenzen der an ihnen gelesenen Grad-Werte konstant sein, und zwar passend zum Rasterabstand.
Ein Ziffernfehler bricht diese Kette sofort.

**(3) Ausgleichsgerade und Residuen — die eigentliche Absicherung.** Statt nur die erste und
letzte Stützstelle zu verwenden, wird über **alle** gelesenen Paare eine Gerade gelegt und das
größte Residuum geprüft. Ein um eine Bogenminute falsch gelesener Wert erzeugt bei 219 px je
Bogenminute ein Residuum von rund 146 px — die Schwelle liegt bei **2 px**. Diese Prüfung
fängt die Fehlerklasse, gegen die die cos-Probe blind ist.

**Nachtrag vom 24.08.2026 — die Mindestzahl der Stützstellen wurde von drei auf zwei
gesenkt.** Die erste Fassung verlangte drei, weil es bei zweien keine Residuen gibt. In der
Umsetzung erwies sich das als der größte Blocker: Viele Blätter tragen nur drei Breiten-Ticks,
und fällt einer aus, bleiben zwei — daran scheiterten 18 von 100 gemessenen Blättern, die
Quote stieg von 31 auf 42 Prozent, als die Hürde fiel.

Vertretbar ist das, weil **Prüfung (2) unabhängig davon greift**: Die aus den zwei Zahlen
gewonnene Skala muss zum gemessenen Rasterabstand passen. Ist eine der beiden Zahlen falsch
gelesen, ist die Skala falsch und die Prüfung schlägt an. Unentdeckt bliebe nur ein Fehler in
*beiden* Zahlen um denselben Betrag — und das ist ohnehin die bereits benannte Grenze der
Kette. Ab drei Stützstellen greift die Residuenprüfung zusätzlich wie beschrieben.

**(4) Lagetest gegen das Kartenfeld.** Die Platzkoordinate muss im **Kartenfeld** liegen, nicht
bloß irgendwo auf dem Blatt. Das Blatt ist rund 10 km hoch; eine Verschiebung um bis zu 5 km
hätte den weiteren Test bestanden.

Fällt eine Prüfung durch, gilt die Karte als `ungepasst` und wird **nicht angezeigt**. Eine
Karte, die falsch liegt, ist schlimmer als gar keine.

**Was diese Kette nicht kann — und das ist keine Kleinigkeit.** Ein zweites Gutachten hat sie
durchgerechnet: Ein *einzelner* falsch gelesener Wert wird zuverlässig gefangen (Residuum
146 px gegen eine Schwelle von 2 px). Ein **systematischer Offset** dagegen — alle
Stützstellen um denselben Betrag verschoben — lässt das Residuum exakt null. Prüfung (1)
kennt nur das Verhältnis, (2) und (3) messen nur Abweichungen von der Geraden. Es bleibt
allein (4), und die begrenzt den Fehler auf die halbe Feldausdehnung: **bis zu rund 2,9 km
bleiben unentdeckt**, ein Versatz von genau einer Bogenminute (1,85 km) läuft also durch.

Warum das trotzdem vertretbar ist: Jede Zahl wird an *ihrem eigenen* Tick gelesen, ein
Versatz der Zuordnung ist also nicht möglich. Ein systematischer Offset entstünde nur, wenn
der Schablonenvergleich dieselbe Ziffer über mehrere verschiedene Zeichen hinweg konsistent
falsch liest — bei zehn gut unterscheidbaren Mustern unplausibel.

**Aber es ist nicht ausgeschlossen, und niemand sollte glauben, die vier Stufen deckten die
Fehlerklasse vollständig ab.** Wer die Anzeige härter absichern will, braucht einen
unabhängigen Anker im Bild — etwa die erkannte Lage des Flugplatzsymbols. Das ist hier
bewusst nicht gebaut.

#### 3.1a Fehlende Gradzahlen ergänzen (Nachtrag 24.08.2026)

Gemessen über alle 446 Blätter: **360 Ticks tragen eine lesbare Minute, aber keine lesbare
Gradzahl** — sie fielen ersatzlos heraus, weil `beschriftung_lesen` beide Zahlen verlangte.
86 Blätter hätten allein dadurch genug Stützstellen gehabt.

Die Ticks liegen äquidistant und sind nach Bogenminuten beschriftet. Springt die Minute in
Richtung wachsender Werte zurück (58, 59, 00, 01), ist eine Gradgrenze überschritten; daraus
folgt die Gradzahl **jedes** Ticks, sobald sie für **einen** feststeht. Steht sie für keinen,
liefert die Platzkoordinate den Grundwert — das Kartenfeld ist rund fünf Bogenminuten hoch und
enthält den Platz, die mittlere Tickzahl liegt also wenige Minuten neben ihm.

**Was das kostet, ausdrücklich:** Für Ticks mit *ergänzter* Gradzahl prüft der Lagetest (4)
die Gradzahl nicht mehr unabhängig — sie ist ja gerade so gewählt, dass der Platz im Feld
liegt. Gegen alles andere behält er seine Kraft: falsch gelesene Minuten, verrutschte Ticks,
eine schiefe Ausgleichsgerade. **Gelesene Gradzahlen werden nicht überschrieben**, der Zusatz
ist rein additiv.

**Ergebnis, gemessen an denselben 446 Blättern:** 216 → **250** gepasst. Von 52 Blättern, die
die Stützstellen-Hürde neu nehmen, kommen 34 ganz durch; 18 fallen an einer der übrigen
Prüfungen — die also arbeitet.

**Was ausdrücklich NICHT gemacht wird: eine einzige Stützstelle je Achse zulassen.** Es wäre
verlockend, denn 57 Blätter scheitern noch daran, und die Steigung ließe sich aus dem
Rasterabstand gewinnen. Der Preis wäre aber, dass ein einziger Ziffernfehler ungeprüft
durchginge: Eine um eine Bogenminute falsch gelesene Breite verschiebt das Blatt um 1,85 km,
und der Lagetest lässt rund 2,9 km durch. Prüfung (2) wäre dabei tautologisch, Residuen gibt
es bei einem Punkt nicht. Zwei Stützstellen bleiben die Untergrenze.

### 3.1b Der Tickstrich ist nicht überall ein Pixel dick (24.08.2026)

Die Blätter zerfallen in zwei Serien, und die Quote hing daran:

| Format | Blätter | gepasst |
|---|---:|---:|
| 875×1240 | 291 | 70,1 % |
| 874×1240 | 117 | 34,2 % |

Ein Pixel Unterschied in der Breite, und die Quote halbiert sich. Die Ursache ist nicht die
Breite, sondern der **waagerechte Tickstrich: auf der 874er-Serie zwei Pixel dick, auf der
875er einen.** `zeichen_im_band` hielt einen festen Abstand von einem Pixel; die übrige Zeile
blieb im Suchfenster stehen, und weil sie über die ganze Bandbreite dunkel ist, gilt jede
Spalte als beschrieben. Alle Zeichen verschmelzen zu einer Gruppe von 19 Pixeln Breite und
fallen durch die Prüfung `2 <= len(g) <= 12`. Herausgekommen ist **null statt zwei Ziffern**,
obwohl die Zahl gut lesbar danebensteht (gemessen an EDAH, Tick y=315).

Das erklärt auch die auffällige Häufung von „1 von x" lesbaren Stützstellen: Über dem Strich
lag die Zahl im Fenster, darunter nicht. Der Strich wird jetzt abgetastet.

**Nur die waagerechten Striche.** Dieselbe Abtastung auf der Längenachse ließ EDAH von 10 auf
5 lesbare Stützstellen fallen, EDAC von 10 auf 4 — das um eine Spalte breitere Fenster zieht
dort Fremdes herein. Die senkrechten Striche sind auf denselben Blättern einen Pixel dick.

**Ergebnis: 250 → 262** an denselben 446 Blättern, alle zwölf im 874er-Format (34 % → 46 %),
keine Verschlechterung beim 875er.

### 3.1c Zwei Ideen, die gemessen durchgefallen sind (24.08.2026)

Beide sind hier festgehalten, damit sie niemand für ungeprüft hält und wiederholt.

**Segmentierung über zusammenhängende Flecken statt Spaltenprojektion.** Der Anlass war
richtig: Die häufigsten unlesbaren Formen sind Klumpen aus Ziffer *und* Gradzeichen, die keine
Spaltenprojektion trennen kann. Die Flecken trennten sie auch — aus einem unlesbaren
10×10-Klumpen bei EDAR wurden sauber „5" und „0". **Über alle Blätter gemessen: 262 → 96.**
Der Grund liegt tiefer: Die Längenbeschriftung trägt führende Nullen („009°34'"), und
getrennte Flecken erzeugen dort ein Zeichen zu viel oder zu wenig. EDXR las 79° statt 9°,
EDWF 77° statt 7°, EDAD 512° statt 51°. Verklebt war die Zahl unlesbar, aber nie **falsch** —
und ein Blatt, das um einen Grad daneben liegt, ist schlimmer als eines, das fehlt. Wer es
erneut versucht, braucht zuerst eine Antwort auf die führenden Nullen.

**Textschwelle anheben.** Die automatische Beschriftung zeigte zerfallene Ziffern mit leeren
Zeilen in der Mitte, was nach einer zu strengen Schwelle aussah. Gemessen ist das Gegenteil:

| Schwelle | 160 | 172 | 184 | 196 |
|---|---:|---:|---:|---:|
| gepasst von 417 | **262** | 217 | 174 | 103 |

Höhere Schwellen holen Hintergrund herein statt Schrift. 160 bleibt.

## 3.2 Freiheitsgrade schwächen die Probe — auch die verbliebenen

Eine Zwischenfassung der Rastersuche durfte den gefundenen Tick-Abstand unterteilen. Bei EDAB
kam dabei **ein Drittel** des echten Abstands heraus (18,26 statt 54,78 Pixel) — bei einem
Probenfehler von **0,006°**, also völlig unauffällig, weil die Achsen-Vielfachen den Fehler
glattbügelten.

**Wird ein Parameter so gewählt, dass der Probenfehler minimal wird, ist die Probe kein
unabhängiger Test mehr, sondern eine Zielfunktion.** Sie kann dann per Konstruktion nur noch
bestehen.

Das gilt auch für die Freiheitsgrade, die bleiben. Die Suche unter den Achsen-Vielfachen 1, 2
und ½ nimmt dasjenige mit dem kleinsten Fehler — dieselbe Operation, nur mit drei Kandidaten
statt unendlich vielen. Ausgerechnet: Bei 52° Breite ist das Akzeptanzfenster je Kandidat
1,79 % des plausiblen Wertebereichs, bei drei Kandidaten **1,45 % Zufallstrefferquote**; mit
nur einem Kandidaten wären es 0,48 %. Jedes weitere Vielfache kostet rund einen halben
Prozentpunkt. Bei 446 Karten sind das etwa 1,3 erwartete Falschdurchläufe — tragbar, aber nur,
weil die Prüfungen (2) bis (4) daneben stehen.

**Regeln, die daraus folgen:** Der Rasterabstand wird nicht unterteilt. Die Tick-Suche bricht
bei der ersten brauchbaren Schwelle ab und probiert **nicht** alle Schwellenkombinationen gegen
die Probe durch — bei 4×4 Kombinationen stiege die Zufallsquote auf rund 21 %, also etwa 90
falsch platzierte Karten. Wer künftig einen Parameter ergänzt, prüft zuerst, ob die Proben ihn
noch fangen können.

Ein weiterer Vorbehalt: Die Toleranz von 0,4° ist **in-sample** gewählt — der gemessene
Maximalfehler liegt bei 0,354°, die Luft beträgt also 13 %.

### 3.3 Was die Erkennung robust macht

Drei Punkte, jeder aus einem realen Fehlschlag entstanden:

- **Rastersuche statt Folgenprüfung.** In das Randband ragen Hindernissymbole hinein — bei EDCQ
  Windräder — und werden als Tick gelesen. Wer verlangt, dass *alle* gefundenen Positionen
  gleichmäßig liegen, scheitert an einem einzigen Störstrich. Gesucht wird deshalb die größte
  Teilmenge auf einem gemeinsamen Raster. Das hob die direkt gepassten Karten von 336 auf 356
  und die brauchbaren Kapitelseiten von 23 auf 53.
  **Achtung bei der Umsetzung:** Das Gütemaß darf nicht allein die Trefferzahl sein. Ein
  feineres Raster hat immer mindestens so viele Treffer — in einer Zwischenfassung lieferte
  `raster([100, 150, 200, 217, 250])` deshalb 16,67 statt der richtigen 50. Die Gütefunktion
  muss die Rasterweite mitbewerten und Störstriche wirklich als Ausreißer verwerfen.
- **Strenge Schwelle zuerst** (0,95 vor 0,55). Bei EDBY lieferte erst die strengste Schwelle den
  richtigen Abstand von 219 Pixeln; die lockere holte zwei Störstriche herein und drückte ihn
  auf 28,7.
- **Anteil dunkler Pixel statt längster durchgehender Lauf.** Die linke Rahmenlinie wird oft von
  der vertikalen „Berichtigung:"-Beschriftung gekreuzt und ist dann nur zu 88 % durchgehend.
  **Der Anteil ist dabei über die Rahmenbreite zu messen, nicht über die Blattbreite:** Die
  obere Rahmenlinie reicht nur über 78 % des Blatts, ihr Anteil erreicht also nie mehr als
  0,783 — sinkt die Schwellenleiter tief genug, greifen stattdessen die Trennlinien der Kopf-
  und Fußzeile, und die liegen weiter außen.

**Ausreißer beim Lesen dürfen nicht als Stützstelle dienen.** Die Rastersuche erkennt
Störstriche, verwirft sie aber bisher nur für die Abstandsberechnung. Für die Beschriftung
müssen dieselben Ausreißer ausgeschlossen werden — sonst wird ein Windradstrich mit einer Zahl
daneben zur Stützstelle.

Zwei Fehler waren schlichte Programmierfehler und stehen hier, damit sie nicht wiederkommen:
Wurde nur *ein* senkrechtes Rahmenpaar gefunden, nahm der Code dasselbe für beide Seiten und
erzeugte vertauschte Feldgrenzen. Und eine Obergrenze von 30 Ticks warf Querformat-Karten mit
feinerem Gitter hinaus (EDAB hat 31, EDWE 39) — über die Gültigkeit entscheidet die
Gleichmäßigkeit, nicht die Anzahl.

### 3.4 Was noch nicht gemessen ist

Das Lesen der Grad-Zahlen ist geprüft, aber nicht durchgerechnet. Die Ziffernformen sind stabil
— die „1" kam über 55 Karten hinweg 38-mal bitidentisch vor —, aber **nicht durchweg bitgleich**;
die Schwellwertbildung an den Rändern erzeugt Höhenunterschiede von einem Pixel. Ein
Hash-Vergleich scheitert daran, ein Schablonenvergleich mit „bestes Match" nicht.

**Die Segmentierung ist zudem noch nicht zuverlässig.** In einer Stichprobe über 120 Blätter
standen neben sauberen Zeichen auch 2×2- und 2×1-Bruchstücke, und einzelne Muster hatten mitten
im Zeichen eine leere Zeile. Zusammenhängende Zeichen werden also teils zerschnitten, teils
zusammengefasst. Das ist der erwartete Ort für Mehraufwand.

Wie viele Karten am Ende wirklich durchlaufen, steht erst nach dem ersten vollständigen Lauf
fest. **Diese Zahl gehört gemeldet, bevor jemand mit der Handarbeit anfängt.**

---

## 4. Server — neues Modul `app/aip_charts.py`

Ein eigenes Modul, aus demselben Grund wie bei `app/vrp.py`: Der Bestand ist Zustand mit eigener
Lebensdauer, und die Geometrie ist die Sorte Rechnung, die man gegen Messwerte prüfen will.
Das Modul bleibt frei von Datenbank- und FastAPI-Bezügen.

**Abruf.** Stabiler `P…`-Link → Meta-Refresh auflösen → PNG aus dem `data:`-URI. Findet sich auf
der verlinkten Seite kein Kartenrahmen, werden die übrigen Seiten desselben Kapitels geprüft.
Ablage als **ungeschnittenes** Blatt unter `<DB-Verzeichnis>/aip/<ICAO>.png`, dazu der SHA-256
des Originals.

**Passung.** Rahmen, Ticks, Grad-Zahlen wie in Abschnitt 2 und 3, danach die vier Prüfungen aus
3.1. Die Blattgrenzen entstehen aus der **Ausgleichsgeraden** über alle Stützstellen, von den
Rahmenkanten auf die Blattkanten verlängert. Der Mercator-Anteil dieser Verlängerung ist
unkritisch (unter einem halben Pixel, Abschnitt 8); gefährlich wäre nur eine falsche Stützstelle,
und dagegen stehen die Prüfungen (2) und (3).

**Pillow ist bereits in `requirements.txt`** — es kommt keine Abhängigkeit hinzu.

### 4.1 Tabelle `aip_charts`

| Spalte | Zweck |
|---|---|
| `icao` | Primärschlüssel |
| `bild_hash` | SHA-256 des Originalblatts, erkennt den AIRAC-Wechsel |
| `nord`, `sued`, `west`, `ost` | Grenzen des **ganzen Blatts** in WGS84 — danach wird das Overlay platziert |
| `feld_nord`, `feld_sued`, `feld_west`, `feld_ost` | Grenzen des **Kartenfelds** — danach schaltet die Automatik, und der Lagetest prüft dagegen |
| `rahmen_px` | Kartenfeld in Pixeln, für den Geometrievergleich |
| `tick_px_lat`, `tick_px_lon` | Rasterabstände, ebenfalls für den Vergleich |
| `quelle` | `auto` oder `hand` |
| `airac` | Ausgabe, aus der das Blatt stammt |
| `status` | `gepasst` oder `ungepasst` |
| `geprueft_am` | Zeitstempel |

### 4.2 AIRAC-Nachlauf

Der AIRAC-Zyklus ist 28 Tage lang, nicht einen Monat — ein monatlicher Job würde früher oder
später eine Ausgabe überspringen. Ein **wöchentlicher** Job holt die Blätter neu; Arbeit findet
er nur, wenn sich der `bild_hash` geändert hat. Ist das der Fall, werden Rahmenlage und
Rasterabstände mit den gespeicherten verglichen:

- **gleich** → nur der Inhalt hat sich geändert. Die Passung bleibt, **auch eine von Hand
  gesetzte**. Nur das Blatt wird ersetzt.
- **abweichend** → Passung neu rechnen. Scheitert das, fällt die Karte auf `ungepasst` zurück
  und erscheint in der Admin-Liste.

Die Toleranz des Geometrievergleichs ist für die beiden Größen **verschieden**: Für die
Rahmenkanten sind 2 Pixel richtig, für die Rasterabstände zu grob — 2 px auf 219 sind 0,9 %,
was über `dφ/dv = 1/sin φ` rund 0,5° Breite entspricht und damit mehr als die Toleranz der
cos-Probe. Für Rasterabstände gilt deshalb 0,5 px.

### 4.3 Betrieb

Punkte, die die erste Fassung offengelassen hatte:

- **Der Job darf den Event-Loop nicht blockieren.** Der Scheduler in `app/poller.py` ist ein
  `AsyncIOScheduler`, die Bildanalyse ist reines Python über jedes Pixel. Gemessen: rund 0,5 s
  je Blatt allein für die Rahmensuche, bei 446 Blättern über vier Minuten, dazu etwa sechs
  Minuten Abrufe. Beim AIRAC-Wechsel ändern sich alle Hashes, also läuft der volle Durchgang.
  Der Job gehört deshalb in `asyncio.to_thread` — dasselbe Muster, das der Poller bereits für
  den `flight_cache`-Rebuild benutzt.
- **Ein fehlgeschlagener Abruf überschreibt nichts.** Netzfehler, Zeitüberschreitung oder eine
  leere Antwort lassen die bestehende Zeile und das bestehende Blatt unangetastet. Sie setzen
  eine gute Karte insbesondere **nicht** auf `ungepasst`.
- **Blätter werden atomar geschrieben:** erst in eine temporäre Datei im Zielverzeichnis, dann
  `os.replace`. Sonst liefert `FileResponse` mitten im Austausch ein abgeschnittenes PNG aus.
- **Speicherplatz:** 446 Blätter zu je 875×1240 belegen grob 100–250 MB unter
  `/opt/friesenspy/data/aip/`. Das Verzeichnis wird beim Start angelegt (`mkdir(parents=True,
  exist_ok=True)`), gehört der Container-UID 1001 (`containersvc`) — und **das tägliche
  OneDrive-Backup wächst um diesen Betrag.**
- **Verschwindet ein Eintrag aus `airport_links`**, wird die zugehörige Zeile in `aip_charts`
  entfernt und das Blatt gelöscht. Sonst bliebe eine Karte im Umlauf, die der Admin bewusst
  entfernt hat.

## 5. API

- `GET /api/aip-charts` — nur Metadaten (ICAO, Blattgrenzen, Feldgrenzen, Bild-URL, AIRAC).
  Wird einmal beim Einschalten der Ebene geladen, wie bei Meldepunkten und Platzrunden.
  Innereien wie `rahmen_px` gehören nicht in den Browser.
- `GET /aip-chart/<ICAO>.png` — das Blatt, mit dem Hash in der URL.
  **`Cache-Control: private`**, nicht `public`: Der Endpunkt liegt hinter dem
  `forum_login_gate`, und genau diese Beschränkung trägt das rechtliche Argument in Abschnitt 9.
  `public` erlaubte jedem Zwischen-Cache das Ausliefern ohne Anmeldung.

## 6. Frontend — Ebene „Sichtflugkarte"

Eine Ebene genügt für beide Ziele: `/panel` liefert **dieselbe** `index.html` wie `/`.

- **Schalter** in der vorhandenen Ebenen-Auswahl, Vorliebe gemerkt über `_prefLies` /
  `_prefSchreib`. Kein `localStorage` — im Kniebrett überlebt der keinen Sim-Neustart.
- **Automatik.** Aus `_eigenePosition()` wird der nächste gepasste Platz bestimmt. Liegt die
  Position in dessen **Kartenfeld** — nicht in den Blattgrenzen —, wird das Overlay eingeblendet,
  sonst ausgeblendet, mit Hysterese gegen Flackern am Rand. Die Blattgrenzen sind rund
  1,8-mal so hoch wie das Kartenfeld; nach ihnen zu schalten hieße, das Overlay erscheint,
  während das Flugzeug unter der Kopfzeile steht, und benachbarte Blätter überlappen stark.
- **Platziert** wird das Overlay dagegen nach den **Blattgrenzen** — es wird ja das ganze Blatt
  gezeigt.
- **Übersteuern.** „Karte festnageln" im Platz-Popup; festgenagelt bleibt sie bis zum Abwählen.
  **Nachtrag 24.08.2026 — die Handhabe gehört der Ebene, nicht einem fremden Popup.**
  Zuerst im Popup der **FSE-Plätze** gebaut, weil die Karte kein anderes Platz-Popup
  kennt. Der Nutzer hat das noch am selben Tag beanstandet, zu Recht: FSEconomy hat mit
  den DFS-Blättern nichts zu tun, und man musste eine sachfremde Ebene einschalten, um
  an den Knopf zu kommen. Ersetzt durch **eigene Marken der Ebene**: Für jedes gepasste
  Blatt sitzt eine Marke auf der Feldmitte, ein Klick nagelt fest, der nächste gibt frei.
  Sie erscheinen ab dem Zoom, auf dem etwas mehr als das ganze Blatt ins Bild passt, und
  bleiben sichtbar, während ein Blatt liegt (beides Nutzer-Wahl 24.08.2026).
  Gemessen wird dafür **nicht in Zoomstufen**, sondern am Verhältnis von Ausschnitt zu
  Blatt, und zwar auf der **engeren** Achse — eine feste Zoomschwelle hinge an der
  Fenstergröße, und die Blätter sind in drei verschiedenen Maßstäben unterwegs.
- **Deckkraft** über einen Regler.
  **Nachtrag 24.08.2026:** Gebaut als eigenes Leaflet-Control oben links unter den
  Zoom-Knöpfen — dieselbe Ecke wie die Windanzeige und aus demselben Grund (unten links
  sitzt der Vollbild-Knopf außerhalb von Leaflets Ecken-Raster). Er erscheint **nur,
  solange wirklich ein Blatt liegt**, nicht schon, wenn die Ebene an ist: Sonst stünde er
  im Cockpit dauerhaft herum, ohne etwas zu tun. Der Wert wird über die Server-Merker
  gehalten (`friesenspy_aipdeckkraft`), nicht im Browser-Speicher — im Kniebrett
  überlebt der keinen Sim-Neustart. Untergrenze 0,3; ein gemerkter Wert außerhalb
  0,3–1,0 fällt auf die Vorgabe 0,75 zurück.
  **Das ist kein neuer Anlauf in der Flackersuche** — siehe den Absatz weiter unten:
  Die Deckkraft war dort nachweislich die falsche Spur, und daran ändert der Regler
  nichts. Er ist eine Bedienung, keine Messreihe.
- **Attribution:** Quelle **samt AIRAC-Datum** des eingeblendeten Blatts, solange die Ebene an
  ist — also aus den Metadaten gebildet, nicht als feste Zeichenkette.
- **Z-Reihenfolge:** über den Basiskacheln, unter den Verkehrs-Markern.

**Zur Deckkraft im Kniebrett — was hier NICHT zu tun ist.** Die erste Fassung dieser Spec
behauptete, `opacity < 1` sei die Ursache des früheren Flackerns, und leitete daraus eine
Messauflage im Sim ab. Der Kommentar bei `_AIP_DECKKRAFT` in `index.html` sagt das Gegenteil:
Zwei Messreihen (v12.5.3, v12.5.4) wurden vollständig zurückgebaut, „die Spur war falsch",
alle Stufen von 0,99 bis 0,8 haben geflackert. Die wirkliche Ursache ist eine Zeile Fremd-CSS
bei `.leaflet-container img.leaflet-tile`, ein bestätigter Simulator-Fehler — „kein Wert, an
dem man hier drehen müsste". **Die Frage ist erledigt; sie wird nicht wieder aufgemacht.**

**Nebenwirkung des ungeschnittenen Blatts:** Kopf- und Fußzeile fallen mit über die
Umgebungskarte. Das ist gewollt — die Frequenzen und Hinweise sollen lesbar sein.

## 7. Admin — die 36 von Hand

Neuer Abschnitt in `admin.html` mit einer Liste aller Karten und ihrem Status. Beim Passen wird
das Blatt gezeigt, man klickt zwei gegenüberliegende **Rahmenecken** und trägt die zugehörigen
Gradwerte ein.

**Der Handpfad rechnet anschließend genauso weiter wie die Automatik:** Aus den zwei
Rahmenpunkten wird die lineare Abbildung gebildet und **auf die Blattkanten verlängert**; erst
das ergibt `nord/sued/west/ost`. Die geklickten Rahmenwerte direkt als Blattgrenzen abzulegen
wäre falsch — beim Standardblatt würde ein 875×1240-Bild in einen 685×685-Rahmen gequetscht,
rund 45 % Maßstabsfehler senkrecht. Das beträfe ausgerechnet die Karten, denen man am meisten
vertraut, weil ein Mensch sie gesetzt hat. Die Feldgrenzen ergeben sich unmittelbar aus den
geklickten Punkten.

**Vorschau vor dem Speichern:** das Blatt als Overlay über der echten Karte, mit Deckkraftregler
— damit sichtbar ist, ob die Straßen zusammenfallen. **`admin.html` enthält bisher kein
Leaflet**; Kartenbibliothek, Container und Basiskacheln kommen mit diesem Teil dazu. Das ist
kein Nebenschritt, sondern der Aufwandsschwerpunkt der Admin-Arbeit.

Die Liste gehört in einen `.table-wrap`, wie es die UI-Regeln in `CLAUDE.md` verlangen.

## 8. Was nicht gebaut wird

Keine Kachelpyramide: Das Kartenfeld hat 685 Pixel für die Kartenfläche, bei den gemessenen
Blättern zwischen etwa 8 und 13 Metern je Pixel — der Maßstab schwankt je Blatt. Kacheln machen
daraus keine zusätzliche Information. Kein GeoTIFF- oder Trip-Kit-Export. Keine Entzerrung und
keine Rotation: Die Karten sind genordet, und der Mercator-Fehler über fünf Bogenminuten Breite
beträgt 0,2 % Skalenänderung, in der Blattmitte 0,27 Pixel; die Verlängerung auf die Blattkanten
kostet weitere 0,32 Pixel, im ungünstigsten Fall 0,49. Keine ICAO-Karte 1:500.000.

## 9. Herkunft und Recht

Die Blätter tragen „© DFS Deutsche Flugsicherung GmbH". Da nicht zugeschnitten wird, bleibt der
Vermerk im Bild; zusätzlich erscheint als Attribution die Quelle samt AIRAC-Datum, solange die
Ebene an ist.

**Klar gesagt:** FriesenSpy verlinkt die Karten damit nicht mehr nur, es vervielfältigt sie.
Der Zugriff läuft durch `forum_login_gate`, ist also auf die angemeldete Gruppe beschränkt, es
gibt keinen Export, und der Cache-Header ist `private`. Die Entscheidung dafür hat der Nutzer am
23.08.2026 getroffen.

**Im Repo liegen keine echten Kartenblätter.** `regover13/friesenspy` ist öffentlich; zwei
Blätter dort abzulegen wäre eine Veröffentlichung und widerspräche dem Absatz darüber. Die
Tests arbeiten deshalb mit **synthetischen Blättern** aus `tests/fixtures/aip/blatt_bauen.py`
und mit den **Messwerten** echter Blätter in `tests/fixtures/aip/messwerte.json` — Messwerte
sind Tatsachen und kein Werk.

## 10. Tests

- **Synthetische Blätter** für die Erkennung, mit gezielt gebauten Störfällen: Hindernissymbole
  im Randband (Fall EDCQ), unterbrochene Rahmenlinie (Fall „Berichtigung:"), feines Gitter
  (Fall EDAB mit 31 Ticks), Standardlayout. Alle vier werden vom Generator erzeugt und sind
  nachweislich erkannt worden.
- **`messwerte.json` als Referenz** für den Erstlauf: 446 Karten, je Eintrag Weg, Kartenfeld,
  Rasterabstände und Probenfehler. Weicht die Quote deutlich von 91,9 % ab, stimmt etwas nicht.
- **Die Prüfkette aus 3.1 einzeln:** ein um eine Bogenminute verfälschter Stützwert muss an der
  Residuenprüfung scheitern; zwei Stützstellen müssen als zu wenig abgewiesen werden; ein Platz
  außerhalb des Kartenfelds muss die Karte verwerfen.
- **`raster()` gegen Störstriche**, mit der Eingabe, an der die Zwischenfassung scheiterte:
  `[100, 150, 200, 217, 250]` muss 50 ergeben, nicht 16,67.
- **AIRAC-Wechsel** durchgehend: gleiche Geometrie → Handpassung bleibt erhalten; abweichende
  → `ungepasst`.
- **Handpfad:** geklickte Rahmenecken müssen zu Blattgrenzen führen, die größer sind als das
  Kartenfeld — der 45-%-Fehler darf nicht wiederkommen.
- **Betrieb:** fehlgeschlagener Abruf lässt die bestehende Karte unberührt; gelöschter
  `airport_links`-Eintrag räumt Zeile und Blatt ab.
- **Frontend:** Ein- und Ausblenden nach dem **Kartenfeld** mit Hysterese, Festnageln,
  Deckkraft, Attribution mit AIRAC.

## 11. Offene Risiken

- **Die echte Automatik-Quote steht erst nach dem ersten vollständigen Lauf fest** (3.4). Die
  Segmentierung der Ziffern ist der wahrscheinlichste Ort für Mehraufwand.
- **Ändert die DFS die Schrift oder das Blattlayout**, fallen Karten in die Ausreißer-Liste.
  Das ist sichtbar, nicht still falsch — eine durchgefallene Karte wird gar nicht angezeigt.
- **Die Toleranz von 0,4° ist in-sample gewählt** (3.2). Eine Karte, die knapp darunter liegt,
  ist nicht dadurch schon richtig platziert; dagegen stehen die Prüfungen (2) bis (4).
- **Das Backup wächst um 100–250 MB** (4.3).
- **Ein systematischer Lesefehler von einer Bogenminute bliebe unentdeckt** (3.1). Das ist
  die bekannte Grenze der Prüfkette, nicht ein übersehener Fall.

---

## Anhang: Was das Gutachten vom 23.08.2026 geändert hat

Ein unabhängiger Gutachter mit frischem Kontext fand 27 Befunde, fünf davon blockierend. Die
inhaltlich folgenreichen:

| Befund | Folge für diese Spec |
|---|---|
| Die cos-Probe ist blind gegen Offset-Fehler — genau die, gegen die sie gebaut war | Prüfkette aus vier Stufen, Abschnitt 3.1 |
| Die Handpassung legte Rahmenecken als Blattgrenzen ab, 45 % Maßstabsfehler | Extrapolation im Handpfad, Abschnitt 7 |
| Die Automatik schaltete nach Blattgrenzen statt nach dem Kartenfeld | Feldgrenzen in der Tabelle, Abschnitt 4.1 und 6 |
| Der Deckkraft-Kommentar wurde sinnverkehrt zitiert; die Frage war längst geklärt | Abschnitt 6, Messauflage gestrichen |
| Der Wochenjob hätte den Event-Loop rund zehn Minuten blockiert | `asyncio.to_thread`, Abschnitt 4.3 |
| `Cache-Control: public` auf einer anmeldepflichtigen, lizenzgeschützten Datei | `private`, Abschnitt 5 |
| Netzausfall, atomares Schreiben, Speicherplatz, verwaiste Karten waren ungeklärt | Abschnitt 4.3 |
| Das Rastermaß bevorzugte feinere Raster — der behobene Bug war nicht behoben | Abschnitt 3.3, mit Testeingabe |

Bestätigt wurde dagegen die Geometrie: cos(Breite) aus dem Tick-Verhältnis, die 0,2 %
Skalenänderung und die Zulässigkeit der linearen Extrapolation hat der Gutachter nachgerechnet.

**Ein zweiter Durchgang** prüfte die überarbeitete Fassung. Er bestätigte sieben Befunde als
behoben und fand vier weitere:

| Befund | Folge |
|---|---|
| Die Residuenprüfung ist blind gegen einen **systematischen** Offset (~2,9 km) | Abschnitt 3.1, als Grenze benannt statt weggeredet |
| `raster()` lieferte den Anker nicht mit — die Beschriftung filterte die echten Ticks heraus statt der Störstriche | Plan, Task 3 |
| Prüfung (2) der Kette war beschrieben, aber nicht implementiert | Plan, Task 5 |
| Feste Suchfenster beim Zahlenlesen brechen bei feinem Gitter — 25 Karten haben Tickabstände unter 40 px | Plan, Task 4 |

Dazu am eigenen Prüfstand gemessen: Zeichnet man die Layoutlinien von Kopf- und Fußzeile als
*Paar*, wählte die Rahmensuche sie statt des Kartenrahmens. `rahmen_finden` sucht deshalb
jetzt das **engste** Paar-Rechteck, dessen beide Randbänder ein Gradnetz tragen — der
Kartenrahmen ist durch sein Gradnetz definiert, nicht durch seine Lage.
