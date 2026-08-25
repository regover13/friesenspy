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

### 3.1d Ein danebengegriffener Rasterabstand (25.08.2026)

`raster()` bestimmt den Tickabstand aus den gefundenen Strichen. Hat eine Achse Lücken oder
werden nur zwei Striche gefunden, greift es **das Vielfache statt des Abstands**:

| Blatt | gemessen | richtig | Faktor |
|---|---:|---:|---:|
| EDWE (Breite) | 263 px | 43,8 px | 6 |
| EDWI (Breite) | 131 px | 43,8 px | 3 |
| EDUW (Breite) | 127 px | 146 px | — kein ganzzahliger |
| EDCQ (Länge) | 181 px | 135 px | — kein ganzzahliger |

Jede daran hängende Rechnung ist dann um denselben Faktor falsch, und Prüfung (2) verwirft
anschließend auch völlig richtig gelesene Zahlen.

**Berichtigt wird über die Physik.** Eine Bogenminute Länge ist um cos(Breite) kürzer als eine
Bogenminute Breite, es muss also `dx/dy = cos(Breite)` gelten. Weicht das ab, wird geprüft, ob
eine der beiden Größen ein **ganzzahliges** Vielfaches der Wahrheit ist. Nur bei einem sauberen
Faktor unter zwei Prozent Abweichung wird korrigiert.

**Die Korrektur kann nichts verschlimmern.** Trifft kein ganzzahliger Faktor zu — wie bei EDUW
und EDCQ, wo schlicht der Abstand zweier zufälliger Striche gemessen wurde —, bleibt alles beim
gemessenen Wert und die Prüfkette lehnt ab wie bisher. Etwas, das vorher zu Recht verworfen
wurde, kann dadurch nicht durchrutschen.

**Ergebnis: 262 → 264** an denselben 446 Blättern.

### 3.1e Sieben Blätter sind quer gedruckt (25.08.2026)

Bei **EDLP** steht die Kopfzeile „PADERBORN/LIPPSTADT EDLP" **hochkant**, im oberen Band stehen
51°40', 51°35', 51°30' — also **Breiten, die entlang der x-Achse abnehmen** — und im linken Band
die Länge. Das Blatt ist um 90 Grad gedreht gedruckt, mit Norden zur Seite. Betroffen sind sieben
der 446: EDCQ, EDHE, EDLP, EDLV, EDMA, EDQG, EDTY.

Diese Blätter waren mit keinem Leseverfahren zu retten — die Achsen sind vertauscht, die Schrift
liegt auf der Seite, und die gesamte Rechnung setzt ein genordetes Blatt voraus. Abschnitt 8 sagt
ausdrücklich „keine Rotation: Die Karten sind genordet". Für diese sieben stimmt das nicht.

**Erkannt wird an der Geometrie, nicht an der Schrift.** Auf einem genordeten Blatt ist eine
Bogenminute Länge um cos(Breite) kürzer als eine der Breite, also `dx < dy`. Steht das Blatt quer,
tauschen die Achsen ihre Rollen und das Verhältnis kippt. Geprüft wird gegen beide Möglichkeiten;
nur wenn die gedrehte deutlich besser passt, gilt das Blatt als quer. **An 380 genordeten Blättern
kein einziger Fehlalarm** — und ein Fehlalarm wäre teuer, das Blatt läge danach quer auf der Karte.

**Gedreht wird beim Abruf, nicht bei der Anzeige.** Das Blatt wird einmal genordet und so
abgelegt; danach gilt für es alles Weitere unverändert, von der Passungsrechnung bis zur
Platzierung im Browser. Die Alternative wäre ein gedreht aufgelegtes Overlay, und das kann
Leaflets `ImageOverlay` nicht.

### 3.1f Nicht jedes Blatt beschriftet links und oben (25.08.2026)

`tick_positionen` suchte die Ticks je Achse in **einem** Randband: Breite links, Länge oben. Über
die 45 damals offenen Karten gemessen trugen **zehn** ihr Breiten-Gradnetz ausschließlich
**rechts** (EDAT, EDBK, EDBT, EDEW, EDGK, EDNZ, EDOZ, EDWO u. a.), **EDOS** sein Längen-Gradnetz
ausschließlich **unten**. Dort fand der Code null Ticks, und das Blatt fiel durch — obwohl es ein
vollständiges, sauber lesbares Gradnetz trägt.

Auffällig war es an einer unmöglichen Kombination: *ein Rahmen wurde gefunden, die Längenachse
lieferte vier bis sechs Ticks, die Breitenachse null.* Eine Sichtflugkarte ohne Gradnetz auf einer
Achse gibt es nicht; wenn eine Achse liest und die andere nicht, liegt es am Suchort, nicht am
Blatt.

`tick_positionen_mit_band` probiert deshalb je Achse **zuerst das übliche Band, das
gegenüberliegende nur bei Fehlschlag** — und nennt dem Aufrufer, welches es war, damit
`zeichen_im_band` die Zahlen an derselben Seite liest. Die Reihenfolge ist kein Detail: Sie hält
jedes bisher erkannte Blatt bitgleich, die Erweiterung kann nur zusätzlich finden. Sie erweitert
auch den Suchraum nicht auf Verdacht (s. 3.2), sondern nur dort, wo sonst gar nichts stünde.

**Die äußeren Rahmenlinien rechts und unten fielen dabei schon an** — `rahmen_finden` hatte sie
nur verworfen (`_ra`, `_ua`). `Rahmen` trägt sie jetzt als `band_rechts`/`band_unten`; beide sind
`None`, wenn ein Rahmen aus vier gespeicherten Zahlen wiederhergestellt wurde, und `band_grenzen`
liefert dann `None` statt zu raten.

Gegenprobe über alle 446 Blätter, alter gegen neuen Code: **0 Regressionen, 0 veränderte
Passungen, 7 zusätzlich automatisch erkannt.**

### 3.1g Beide Drehrichtungen gehören probiert (25.08.2026)

Nachtrag zu 3.1e: `ist_quer_gedruckt` sieht am Achsenverhältnis, **dass** ein Blatt quer steht —
nicht, **wohin** Norden zeigt. Dafür stand in `blatt_beschaffen` fest `ROTATE_270`. Das ist für
EDTX richtig; bei **EDCQ** liefert erst `ROTATE_90` ein genordetes Blatt. Die feste Richtung ließ
die andere Hälfte unnötig durchfallen.

Jetzt werden beide probiert, `ROTATE_270` zuerst (damit die bereits erkannten unverändert
bleiben), und **die Prüfkette entscheidet** — ein falsch gedrehtes Blatt fällt durch den
Genordet-Test, es kann also nichts Falsches abgelegt werden. Dasselbe Muster wie bei der
Seitensuche: nicht raten, sondern versuchen und prüfen lassen.

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

### 3.5 Die Zahl, gemessen (25.08.2026)

Nachtrag zu 3.4, gemessen mit dem deployten Stand über alle 446 Blätter:

| | Karten | |
|---|---:|---|
| **rein automatisch** | **283 von 446** | **63,5 %** |
| davon an der Bilderkennung gescheitert | 163 | |
| davon an fehlender Platzkoordinate gescheitert | 0 | OpenAIP deckt alle ab |
| **Gesamtstand mit Handarbeit** | **437 von 446** | **98,0 %** |

**Die 91,9 % aus Abschnitt 3 waren die Obergrenze der Geometrie, nicht die fertige Passung** —
die Spec sagt das dort ausdrücklich. Der Abstand zwischen 91,9 % (Rahmen und Raster gefunden) und
63,5 % (Passung durchgerechnet und geprüft) ist genau das, was Abschnitt 3.4 vorhergesagt hat: Es
liegt am **Lesen der Zahlen**, nicht am Finden des Gitters.

**Die beiden Zahlen beantworten verschiedene Fragen, und beide werden gebraucht:**

- **437/446** ist der Stand, den die Nutzer sehen. Er hält: Der wöchentliche AIRAC-Lauf erhält
  jede Handpassung, solange sich die Blattgeometrie nicht ändert (`hand_behalten`, s. 4.2). Für
  die sieben Blätter, deren Seite von Hand getauscht wurde, ist das am 25.08.2026 gegengeprüft
  worden — ein simulierter Frischabruf liefert dort weiterhin `passung=None`, die Handkorrektur
  bleibt also geschützt.
- **283/446** ist, was der Code allein kann. Das ist die Zahl, die zählt, wenn ein **neuer**
  Flugplatz dazukommt oder die DFS ein Blatt neu satzt. Handarbeit erhöht den sichtbaren Stand,
  aber nicht die Fähigkeit — wer die Erkennung verbessern will, misst gegen 283, nicht gegen 437.

Die neun, die auch von Hand nicht zu retten waren, mit Grund:

| ICAO | Warum |
|---|---|
| EDFH, EDMR | In der Quelle liegt **keine Sichtflugkarte** — Frankfurt-Hahn nur Textseiten, EDMR ein Hubschrauber-Detailplan ohne Gradnetz |
| EDDF, EDDH, EDDN, EDDS | Große Verkehrsflughäfen mit eigenem Kartentyp (Bewegungskarte ohne Gradnetz) |
| EDDG, EDLW | 1:200 000-Karten, deren Gradnetz von Kartensymbolen so überdeckt ist, dass die Residuen die Prüfkette nicht bestehen (EDDG: 7 px, zulässig sind 2) |
| EDCQ | Das **gedruckte Gitter selbst** ist ungenau — bis 11 px Abweichung von der Geraden, wo sonst 0–2 px gelten |

Bei EDDG und EDCQ wurde bewusst **nichts** geschrieben: Die Prüfkette hat abgelehnt, und eine
abgelehnte Passung von Hand zu erzwingen würde genau die Sicherung aushebeln, die den Wert der
übrigen 437 garantiert.

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

#### 4.2a Handgepasste Blätter waren eingefroren (25.08.2026)

Der Absatz oben beschreibt, was gedacht war. Gebaut war es anders — und der Unterschied blieb
zwei Tage unbemerkt, weil er nichts kaputtmacht, sondern etwas *unterlässt*.

`scripts/aip_bestand.py` fing den Fehlschlag der Automatik in einem eigenen Zweig ab:

```python
if passung is None:
    if alt and alt["quelle"] == "hand" and alt["status"] == "gepasst":
        continue        # ← vor blatt_schreiben
```

Für die Passung ist das genau richtig. Für das **Bild** war es falsch: Der Sprung ging vor
`blatt_schreiben`, das Blatt wurde also nie ersetzt. Und da die Automatik an genau diesen
Blättern *dauerhaft* scheitert — sonst wären sie nicht von Hand gesetzt worden — hätte sie das
auch in keinem späteren Durchgang getan. **154 Sichtflugkarten waren damit auf dem Stand ihrer
Handarbeit eingefroren:** keine neuen Hindernisse, keine geänderten Lufträume, keine
korrigierten Frequenzen, und nirgends ein Hinweis darauf.

Das ist die Sorte Fehler, die eine Quotenmessung nicht findet. Alle 437 Karten waren „gepasst",
die Zahl stimmte — nur bezog sie sich bei 154 von ihnen auf ein Blatt, das nie wieder jünger
wurde.

**Warum man nicht einfach schreiben darf.** `blatt_beschaffen` liefert bei gescheiterter
Passung das Bild der **verlinkten** Seite. Bei 28 Plätzen ist das nicht die Sichtflugkarte,
sondern eine Textseite oder ein anderes Blatt desselben Kapitels (Abschnitt 1). Blind
geschrieben läge dort die falsche Karte unter einer richtigen Passung — schlimmer als der
eingefrorene Zustand.

**Die Prüfung, die entscheidet** (`aip_charts.zeigt_denselben_ausschnitt`). Drei Stufen, und
die dritte trägt:

1. Das Rahmenrechteck muss auf 2 px stimmen. **Notwendig, aber fast wertlos:** Gemessen an
   50 zufälligen echten Blättern teilen sich **39** dasselbe Rahmenrechteck
   (132, 180, 817, 865) — die DFS setzt einheitlich. Von 2450 Fremdpaaren kamen 1492 allein
   über diese Stufe.
2. Mindestens zwei Ticks je Achse müssen gefunden werden.
3. **Jeder gefundene Tick muss nach der abgelegten Passung auf einer ganzen Bogenminute
   liegen.** Das prüft Maßstab und Lage in einem: Ein verschobener Ausschnitt verschiebt die
   Phase des Gitters, ein anderer Maßstab seinen Abstand. Und es kommt ohne Zahlenlesen aus —
   ausgerechnet das funktioniert auf diesen Blättern ja nicht.

**Gemessen (25.08.2026), gegen echte Blätter, nicht gegen das Prüfblatt:**

| Probe | Ergebnis |
|---|---|
| Eigenes Blatt wiedererkannt | **50 von 50** |
| Fremdes Blatt mit **identischem** Rahmenrechteck fälschlich akzeptiert | **0 von 1492** |

**Die Skala steht nicht in `tick_px_lat`/`tick_px_lon`.** `handpassung()` legt dort `0.0` ab —
ein von Hand gesetzter Rahmen kennt keinen gemessenen Rasterabstand. Ausgerechnet die 154
Blätter, um die es hier geht, tragen also gar keine Rasterwerte, und `geometrie_gleich` kann
bei ihnen nie greifen. `gerade_aus_bestand()` rechnet die Abbildung Pixel → Grad deshalb aus
`rahmen_px` und den Feldgrenzen; die sind bei jeder Passung gefüllt.

**Was bleibt, wenn die Prüfung ablehnt:** nichts wird angefasst, und der Platz landet in
`handpassung_pruefen`. Diese Liste gibt `lauf()` zurück, `main()` druckt sie, und der
wöchentliche Job meldet sie als **Warnung** ins Log. Ein stiller Eintrag wäre derselbe Fehler
noch einmal.

**Grenze, ausdrücklich gesagt:** Zwei Blätter desselben Platzes mit gleichem Rahmen, gleichem
Maßstab und zufällig gleicher Gitterphase wären nicht zu unterscheiden. Der Tickabstand ist
eine Bogenminute (rund 220 px); die Phase müsste auf 2 px zusammenfallen.

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

### 4.4 Werkzeuge für die Handarbeit (25.08.2026)

Zwei Skripte in `scripts/`, entstanden in der Nacht, in der 154 Blätter von Hand gesetzt wurden.
Sie gehören ins Repo und nicht nach `/tmp`: Die Arbeit wiederholt sich bei jedem neuen Platz und
bei jedem Blatt, das die DFS neu satzt.

| Skript | Zweck |
|---|---|
| `scripts/aip_band_zeigen.py` | Randband eines Blattes groß rendern, erkannte Ticks rot einzeichnen und beziffern — daraus liest ein Mensch die Gradzahlen |
| `scripts/aip_handpassung.py` | Aus den abgelesenen `<pixel>=<grad>:<minute>`-Paaren eine **geprüfte** Passung rechnen und ablegen |

**Der Ablauf:** Band rendern → Zahlen ablesen → `aip_handpassung.py` ohne `--schreiben` als
Probelauf → erst wenn alle Proben `OK` melden, mit `--schreiben` ablegen.

**Die Prüfkette ist der Kern, nicht die Bequemlichkeit.** `aip_handpassung.py` rechnet dieselben
Proben wie die Automatik, plus zwei eigene (Residuen über ≥3 Stützstellen; Skala aus den
Ablesungen, wenn das gemessene Raster selbst der Fehler ist). In der Nacht zum 25.08.2026 hat sie
**jeden** Fehler gefangen: sechs eigene Rechenfehler im Werkzeug (u. a. ein Vorzeichenfehler, der
EDBC 36 Bogenminuten nach Süden schob) und jede Fehlablesung der Lese-Agenten. **Keine falsche
Passung ist in die Datenbank gelangt** — nachgeprüft: keines der gepassten Blätter hat einen
`rahmen_px` außerhalb seines Bildes.

Zwei Eigenheiten, die beim Nachbauen Zeit sparen:

- **`--rahmen l,o,r,u,bl,bo,br,bu`** erzwingt einen Rahmen, wenn `rahmen_finden` scheitert, weil
  eine Seite des Doppelrahmens zu schwach gedruckt ist (EDLS, EDEL, EDMP, EDPS). Die inneren
  Linien stehen in der Linienliste von `_linien`, die äußeren liegen rund 24 px weiter außen.
- **`--blatt PFAD`** umgeht `get_settings()`. Ein Anzeigewerkzeug soll auch dort laufen, wo nur
  ein heruntergeladenes PNG liegt und keine Betriebsgeheimnisse gesetzt sind.

**Das Breitenband wird mit `rotate(90)` gedreht, gegen den Uhrzeigersinn.** Mit `rotate(-90)`
sitzen die roten Marken gespiegelt zu ihren Ticks, und die abgelesene Breite nimmt nach rechts
scheinbar zu statt ab. Zuerst so gebaut und erst am widersinnigen Verlauf bemerkt — die Zahlen
wären um die halbe Blattbreite daneben gewesen.

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

  **Hin und her (24. → 25.08.2026), und wo es gelandet ist.** Am 24.08. wurde die Schwelle
  entschärft: Marken auf *jeder* Zoomstufe, klein und stumm in der Übersicht, groß und
  beschriftet erst nah (Commit `c485eaa`). Am 25.08. mittags auf Wunsch zurückgenommen —
  eine einzige Schwelle, sie entschied wieder, **ob** eine Marke entsteht. Am selben Abend
  nachjustiert: So kamen die Marken zu spät.

  **Der gebaute Zustand sind jetzt ZWEI Schwellen am selben Verhältnis:**

  | Schwelle | Wert | entscheidet |
  |---|---|---|
  | `_AIP_MARKE_SICHTBAR_FAKTOR` | `_AIP_MARKE_FAKTOR * 4` = 8,0 | **ob** die Marke da ist |
  | `_AIP_MARKE_FAKTOR` | 2,0 | **wie** sie aussieht: groß und beschriftet |

  Vorgegeben hatte der Nutzer den Ausschnitt („4× größer"), nicht die Stufenzahl; da eine
  Zoomstufe die Kantenlänge verdoppelt, sind das zwei Stufen früher. Die Trennung ist
  nicht kosmetisch: Bei vierfachem Ausschnitt stehen viele Marken im Bild. In voller Größe
  wären sie ein Teppich, und ein permanenter Tooltip je Marke ist ein DOM-Element, das
  Leaflet bei jeder Kartenbewegung neu setzt — die Falle vom 15.08.2026. Die
  Verkleinerung auf `scale(0.6)` und die Beschriftung hängen deshalb weiter an der
  **strengen** Schwelle.

  Wer das Sichtfenster ändert, verdoppelt oder halbiert den Faktor. Zwischenwerte tun
  nichts, weil Zoomstufen ganzzahlig sind.

  Bemerkenswert ist der Zwischenzustand: `c485eaa` hat diesen Absatz **nicht** angefasst.
  Die Spec beschrieb einen Tag lang eine Sichtbarkeitsregel, die der Code nicht mehr
  hatte — und niemandem fiel es auf, weil beide Fassungen für sich plausibel klingen. Wer
  hier wieder etwas ändert, ändert diesen Absatz mit.
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

### 7.1 Was der erste Live-Einsatz am Admin geändert hat (24.08.2026)

Der Nutzer hat mit dem Werkzeug gearbeitet, und dabei kam fünferlei heraus:

**Grad und Minuten in getrennten Feldern.** Ein einziges Feld „Rahmen Nord (Grad)" steht neben
einem Blatt, auf dem „14° 15'" gedruckt ist — und wird prompt als „51.17" gefüllt, gemeint als
51°17'. Gelesen wurde 51,17°, ein Unterschied von zwölf Kilometern, den die Vorschau nur zeigt,
wenn man genau hinsieht. Dazu die Prüfung Nord > Süd und Ost > West; ohne sie ließ sich eine
spiegelverkehrte Passung speichern.

**Filter „nur offene" und 20 Karten je Seite.** 446 Zeilen mit je einem eigenen Knopf und
Ereignis-Handler machten die Seite träge. Der Server brauchte für die Liste 5 ms — die Zeit ging
im Browser drauf. Die Nutzlast ist zusätzlich von 209 auf 97 KB geschrumpft, weil `bild_hash`
und Pixelwerte nicht in den Browser gehören.

**Beim Speichern nicht neu laden.** Ein `loadAipCharts()` setzte Seite und Bildlauf zurück; nach
jeder gepassten Karte stand man wieder ganz oben. Der Eintrag wird jetzt im Speicher an genau
der einen Stelle nachgezogen.

**Vorbelegen aus der gespeicherten Passung**, nicht aus dem, was zuletzt im Formular stand —
inklusive der beiden Rahmenecken aus `rahmen_px`. Sonst arbeitet man an Karte B mit den Zahlen
von Karte A weiter, und das Ergebnis sieht plausibel aus.

**Die Kapitelseite von Hand wählen.** `blatt_beschaffen` nimmt beim Rückfall die **erste** Seite,
deren Passung durchgeht. Bei EDDK hat das Kapitel sechs Seiten, und die gewählte war nicht die
gewünschte. Welche die richtige ist, kann die Automatik nicht wissen — sie prüft nur, ob eine
Karte *irgendwo* passt. Der Admin bekommt deshalb die Liste mit Vorschaubild, Maßen und dem
Hinweis, welche automatisch passen würde (`GET …/seiten`, 6,8 s für sechs Seiten) und setzt eine
davon fest (`POST …/seite`). Beides läuft in `asyncio.to_thread`, und der POST nimmt
ausschließlich URLs von `aip.dfs.de` — sonst wäre er ein offener Abruf beliebiger Adressen vom
Server aus.

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
