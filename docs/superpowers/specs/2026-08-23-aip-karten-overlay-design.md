# AIP-Sichtflugkarten als Karten-Overlay — Design

**Stand:** 23.08.2026 · **Betrifft:** neu `app/aip_charts.py`, dazu `app/main.py`,
`app/database.py`, `app/static/index.html`, `app/static/admin.html` · **Quelle:** Auftrag des
Nutzers, 23.08.2026 · **Status:** abgestimmt, bereit für die Planung

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

Gemessen am 23.08.2026 an allen 446 Einträgen der Tabelle `airport_links`, nicht aus der
Dokumentation abgeleitet.

**Es sind keine PDFs.** Ein Eintrag wie `aip.dfs.de/BasicVFR/pages/P0016F.html` ist eine
Weiterleitungsseite mit `<meta http-equiv="Refresh">` auf die aktuelle AIRAC-Ausgabe
(`.../BasicVFR/2026AUG20/pages/<hash>.html`). Dort steckt die Karte als **PNG in einem
`data:`-URI** im HTML — 875×1240 Pixel, etwa 105 dpi auf A4. Ein HTTP-Redirect findet nicht
statt; wer `curl -L` benutzt, bekommt die Weiterleitungsseite zurück und hält sie für die Karte.

**Die Blätter sind fast, aber nicht ganz einheitlich:** 413 der 446 Karten sind A4 hoch
(875×1240 oder 874×1240), 33 haben Sonderformate bis 1636×1240, darunter Querformate.

**Das Kartenfeld ist von einem Doppelrahmen umgeben**, im Regelfall bei x 132–817 und
y 180–865, also 685×685 Pixel. Zwischen den beiden Rahmenlinien liegen die Gradnetz-Ticks und
ihre Beschriftung („54°" über dem Strich, „14'" darunter). Die Karten sind genordet; der
Nordpfeil zeigt nur die Missweisung an.

**Der gespeicherte Link zeigt nicht immer auf die Karte.** Bei EDAZ etwa öffnet er die
Textseite „VFR-Flugverfahren"; die Sichtflugkarte ist die vierte Seite desselben
Platz-Kapitels. Das betrifft 28 Karten (Abschnitt 3.3).

## 2. Warum die Georeferenzierung selbst gerechnet werden muss

In den DFS-Daten steckt keine Geo-Information. Der verbreitete **AIP Browser DE**
(mpmediasoft) rechnet sie ebenfalls nicht aus, sondern lädt sie fertig: „Vordefinierte
Beschnitt- und Georeferenzierungsinformationen für alle Flugplatzseiten, bei denen dies
sinnvoll möglich ist, stehen auf unserem Server bereit" — mit dem Zusatz, für die Richtigkeit
werde keine Haftung übernommen. **Enroute Flight Navigation** lässt Nutzer die Punkte im
*GeoRef Tool* von Hand setzen, verbreitete Bastelanleitungen nutzen MapTiler mit fünf
Passpunkten. Niemand gewinnt die Passung aus der Karte selbst.

Das geht aber, und zwar so:

1. **Rahmen finden** über den Anteil dunkler Pixel je Zeile und Spalte. Der Doppelrahmen ist an
   seinem Abstand von etwa 24 Pixeln erkennbar.
2. **Ticks finden** in den Randbändern zwischen den Rahmenlinien.
3. **Maßstab** aus dem Tick-Abstand.
4. **Absolute Lage** aus den Grad-Zahlen neben den Ticks.

Schritt 4 ist unverzichtbar. Aus dem Verhältnis der Tick-Abstände beider Achsen folgt zwar
cos(Breite) und damit die geografische Breite auf etwa 0,1° genau — aber 0,1° sind sechs
Bogenminuten. Bei EDXR blieben zwei mögliche Lagen übrig, **1,85 km auseinander**. Für eine
Moving Map wäre das unbrauchbar, und im Flug würde es niemand bemerken.

## 3. Messergebnis: 410 von 446 Karten automatisch

| Weg | Karten |
|---|---:|
| direkt auf der verlinkten Seite gepasst | 356 |
| Platzkoordinate aus OpenAIP statt `airportsdata` | 26 |
| Karte auf einer anderen Seite desselben Kapitels gefunden | 28 |
| **automatisch gepasst** | **410 von 446 = 91,9 %** |
| von Hand nachzutragen | 36 (etwa 18 Minuten) |

Von den Nordsee- und Friesen-Plätzen bleibt genau einer offen: **EDWJ**. EDHK, EDWE, EDWF,
EDWG, EDWI, EDWQ, EDWS, EDWY, EDWZ, EDXB, EDXF, EDXG, EDXH, EDXM, EDXN, EDXP, EDXR und EDXW
laufen automatisch.

Diese 36 bleiben für die Handarbeit:

```
EDAT EDBK EDBT EDBX EDCQ EDCR EDDS EDEL EDEW EDGK EDGO EDGU EDGY EDHE
EDLP EDLS EDLV EDLW EDMP EDMR EDNU EDNV EDNZ EDOC EDOS EDOZ EDPI EDPS
EDQG EDUW EDVC EDVG EDVI EDWJ EDWO EDXO
```

### 3.1 Die Gegenprobe und ihre Grenze

Jede gerechnete Passung wird gegen die bekannte Platzkoordinate geprüft: Die aus dem
Tick-Verhältnis gefolgerte Breite muss zur Breite des Flugplatzes passen. Toleranz **0,4°**.
Über die 356 direkt gepassten Karten liegt der Fehler im Median bei **0,085°**, der
90-%-Wert bei 0,167°, das Maximum bei 0,354°.

Bei 334 Karten tragen beide Achsen dieselbe Tick-Einheit, bei 22 unterscheiden sie sich um
Faktor 2 oder ½. Diese Freiheit ist nötig, aber sie ist auch die Schwachstelle der Probe —
siehe 3.2.

### 3.2 Eine Lehre, die in den Code gehört

Eine Zwischenfassung der Rastersuche durfte den gefundenen Tick-Abstand unterteilen. Bei EDAB
kam dabei **ein Drittel** des echten Abstands heraus (18,26 statt 54,78 Pixel) — bei einem
Probenfehler von **0,006°**, also völlig unauffällig, weil die Achsen-Vielfachen den Fehler
glattbügelten.

**Freiheitsgrade in der Auswertung schwächen genau die Probe, die sie prüfen soll.** Deshalb
wird der Rasterabstand nicht unterteilt; Lücken zwischen echten Ticks deckt das Raster über
seine Vielfachen ab. Wer später einen weiteren Parameter einführt, prüft zuerst, ob die
Gegenprobe ihn noch fangen kann.

### 3.3 Was die Erkennung robust macht

Drei Punkte, jeder aus einem realen Fehlschlag entstanden:

- **Rastersuche statt Folgenprüfung.** In das Randband ragen Hindernissymbole hinein —
  bei EDCQ Windräder — und werden als Tick gelesen. Wer verlangt, dass *alle* gefundenen
  Positionen gleichmäßig liegen, scheitert an einem einzigen Störstrich. Gesucht wird deshalb
  die größte Teilmenge auf einem gemeinsamen Raster. Das hob die direkt gepassten Karten von
  336 auf 356 und die brauchbaren Kapitelseiten von 23 auf 53.
- **Strenge Schwelle zuerst** (0,95 vor 0,55). Bei EDBY lieferte erst die strengste Schwelle
  den richtigen Abstand von 219 Pixeln; die lockere holte zwei Störstriche herein und drückte
  ihn auf 28,7.
- **Anteil dunkler Pixel statt längster durchgehender Lauf.** Die linke Rahmenlinie wird oft
  von der vertikalen „Berichtigung:"-Beschriftung gekreuzt und ist dann nur zu 88 % durchgehend
  — rechts, wo kein Text kreuzt, sind es 100 %.

Zwei weitere Fehler waren schlichte Programmierfehler und sind hier nur festgehalten, damit sie
nicht wiederkommen: Wurde nur *ein* senkrechtes Rahmenpaar gefunden, nahm der Code dasselbe für
beide Seiten und erzeugte vertauschte Feldgrenzen. Und eine Obergrenze von 30 Ticks warf
Querformat-Karten mit feinerem Gitter hinaus (EDAB hat 31, EDWE 39) — über die Gültigkeit
entscheidet die Gleichmäßigkeit, nicht die Anzahl.

### 3.4 Was noch nicht gemessen ist

Die 91,9 % sind die **Geometrie**-Quote und damit eine Obergrenze. Das Lesen der Grad-Zahlen
ist getrennt geprüft, aber nicht durchgerechnet: Die Ziffernformen sind stabil — die „1" kam
über 55 Karten hinweg 38-mal bitidentisch vor —, aber **nicht durchweg bitgleich**; die
Schwellwertbildung an den Rändern erzeugt Höhenunterschiede von einem Pixel. Ein Hash-Vergleich
scheitert daran, ein Schablonenvergleich mit „bestes Match" nicht. Wie viele Karten am Ende
wirklich durchlaufen, steht erst nach dem ersten vollständigen Lauf fest. Diese Zahl gehört
gemeldet, bevor jemand mit der Handarbeit anfängt.

---

## 4. Server — neues Modul `app/aip_charts.py`

Ein eigenes Modul, aus demselben Grund wie bei `app/vrp.py`: Der Bestand ist Zustand mit eigener
Lebensdauer, und der Zuschnitt auf Geometrie ist die Sorte Rechnung, die man gegen Messwerte
prüfen will.

**Abruf.** Stabiler `P…`-Link → Meta-Refresh auflösen → PNG aus dem `data:`-URI. Findet sich auf
der verlinkten Seite kein Kartenrahmen, werden die übrigen Seiten desselben Kapitels geprüft
(erreichbar über die `../chapter/…`-Verweise). Ablage als **ungeschnittenes** Blatt unter
`/opt/friesenspy/data/aip/<ICAO>.png`, dazu der SHA-256 des Originals.

**Passung.** Rahmen, Ticks, Grad-Zahlen wie in Abschnitt 2 und 3. Die Bounds gelten für das
**ganze Blatt**: Die lineare Abbildung wird von den Rahmenkanten auf die Blattkanten
extrapoliert, damit das Kartenfeld exakt sitzt und die Ränder außen überstehen.

**Gegenprobe.** Platzkoordinate aus `airportsdata`, ersatzweise OpenAIP. Besteht eine Karte die
Probe nicht, bekommt sie den Status `ungepasst` und wird **nicht angezeigt**. Eine Karte, die
falsch liegt, ist schlimmer als gar keine.

**Pillow ist bereits in `requirements.txt`** — es kommt keine Abhängigkeit hinzu.

### 4.1 Tabelle `aip_charts`

| Spalte | Zweck |
|---|---|
| `icao` | Primärschlüssel |
| `bild_hash` | SHA-256 des Originalbilds, erkennt den AIRAC-Wechsel |
| `nord`, `sued`, `west`, `ost` | Bounds des **ganzen Blatts** in WGS84 |
| `rahmen_px` | Kartenfeld in Pixeln, für den Geometrievergleich |
| `tick_px_lat`, `tick_px_lon` | Rasterabstände, ebenfalls für den Vergleich |
| `quelle` | `auto` oder `hand` |
| `airac` | Ausgabe, aus der das Bild stammt |
| `status` | `gepasst` oder `ungepasst` |
| `geprueft_am` | Zeitstempel |

### 4.2 AIRAC-Nachlauf

Der AIRAC-Zyklus ist 28 Tage lang, nicht einen Monat — ein monatlicher Job würde deshalb
früher oder später eine Ausgabe überspringen. Ein **wöchentlicher** APScheduler-Job holt die
Karten neu; Arbeit findet er ohnehin nur, wenn sich der `bild_hash` geändert hat. Ist das der
Fall, werden Rahmenlage und Rasterabstände mit den gespeicherten verglichen:

- **gleich** → nur der Inhalt hat sich geändert (Hindernis ergänzt, Frequenz korrigiert). Die
  Passung bleibt, **auch eine von Hand gesetzte**. Nur das Bild wird ersetzt.
- **abweichend** → Passung neu rechnen. Scheitert das, fällt die Karte auf `ungepasst` zurück
  und erscheint in der Admin-Liste.

## 5. API

- `GET /api/aip-charts` — nur Metadaten (ICAO, Bounds, Bild-URL, AIRAC). Wird einmal beim
  Einschalten der Ebene geladen, genau wie bei Meldepunkten und Platzrunden.
- `GET /aip-chart/<ICAO>.png` — das Blatt, mit dem Hash im Pfad und langlebigem Cache.

## 6. Frontend — Ebene „Sichtflugkarte"

Eine Ebene genügt für beide Ziele: `/panel` liefert **dieselbe** `index.html` wie `/`.

- **Schalter** in der vorhandenen Ebenen-Auswahl, Vorliebe gemerkt über `_prefLies` /
  `_prefSchreib` wie bei `_AIP_PREF_KEY`. Kein `localStorage` — im Kniebrett überlebt der
  keinen Sim-Neustart.
- **Automatik.** Aus `_eigenePosition()` (Sim-Position, ersatzweise die eigene VATSIM-Position)
  wird der nächste gepasste Platz bestimmt. Liegt die Position innerhalb seiner Bounds, wird das
  Overlay eingeblendet, sonst ausgeblendet — **mit Hysterese**, sonst flackert es am Rand.
- **Übersteuern.** „Karte festnageln" im Platz-Popup; festgenagelt bleibt sie bis zum Abwählen.
- **Deckkraft** über einen Regler.
- **Z-Reihenfolge:** über den Basiskacheln, unter den Verkehrs-Markern.

**Warnung aus dem eigenen Code:** Der Kommentar bei `_AIP_DECKKRAFT` in `index.html` hält fest,
dass Leaflet bei `opacity < 1` einen eigenen Container anlegt und genau das die Ursache des
früheren Flackerns im Kniebrett war. Das gehört im Sim gemessen, nicht angenommen.

**Nebenwirkung des ungeschnittenen Blatts:** Kopf- und Fußzeile fallen mit über die
Umgebungskarte, unten ragt das Blatt weit über das Kartenfeld hinaus. Das ist so gewollt — die
Frequenzen und Hinweise sollen lesbar sein. Wem es zu viel verdeckt, regelt die Deckkraft.

## 7. Admin — die 36 von Hand

Neuer Abschnitt in `admin.html` mit einer Liste aller Karten und ihrem Status. Beim Passen wird
das Blatt gezeigt, man klickt zwei gegenüberliegende Rahmenecken und trägt die Gradwerte ein.
**Vorschau als Overlay über der echten Karte mit Deckkraft**, damit vor dem Speichern sichtbar
ist, ob die Straßen zusammenfallen. Speichern setzt `quelle = hand`.

Die Tabelle gehört in einen `.table-wrap`, wie es die UI-Regeln in `CLAUDE.md` verlangen.

## 8. Was nicht gebaut wird

Keine Kachelpyramide — das Kartenfeld hat 685 Pixel für rund 9 km, also 13 Meter je Pixel;
Kacheln machen daraus keine zusätzliche Information. Kein GeoTIFF- oder Trip-Kit-Export. Keine
Entzerrung und keine Rotation: Die Karten sind genordet, und der Mercator-Fehler über fünf
Bogenminuten Breite beträgt 0,2 % Skalenänderung, in der Blattmitte unter einem halben Pixel.
Keine ICAO-Karte 1:500.000.

## 9. Herkunft und Recht

Die Blätter tragen „© DFS Deutsche Flugsicherung GmbH". Da nicht zugeschnitten wird, bleibt der
Vermerk im Bild; zusätzlich erscheint als Leaflet-Attribution die Quelle samt AIRAC-Datum,
solange die Ebene an ist.

**Klar gesagt:** FriesenSpy verlinkt die Karten damit nicht mehr nur, es vervielfältigt sie.
Der Zugriff läuft durch `forum_login_gate`, ist also auf die angemeldete Gruppe beschränkt, und
es gibt keinen Export. Die Entscheidung dafür hat der Nutzer am 23.08.2026 getroffen.

## 10. Tests

- **Passung gegen Messwerte.** Die gemessenen Rahmen-, Raster- und Bounds-Werte einer Auswahl
  von Karten als Fixture; zwei echte Blätter als Bilddatei, der Rest als Zahlen — 410 PNGs
  gehören nicht ins Repo.
- **Gegenprobe.** Für jede gepasste Karte muss die gefolgerte Breite zur Platzkoordinate passen.
- **Die Störstrich-Fälle als Regressionstest:** EDCQ (Windräder im Randband), EDBY (Störstriche
  bei lockerer Schwelle), EDAB (Querformat, 31 Ticks), EDAZ (Karte auf der vierten Seite).
- **Kein Unterteilen.** Ein Test, der sicherstellt, dass der Rasterabstand nicht auf ein
  Vielfaches heruntergerechnet wird — das war der stille Fehler aus 3.2.
- **AIRAC-Wechsel.** Gleiche Geometrie → Handpassung bleibt; abweichende → `ungepasst`.
- **Frontend.** Ein- und Ausblenden mit Hysterese, Festnageln, Deckkraft.

## 11. Offene Risiken

- **Die echte Automatik-Quote steht erst nach dem ersten vollständigen Lauf fest** (3.4).
- **Ändert die DFS die Schrift oder das Blattlayout**, fallen Karten in die Ausreißer-Liste.
  Das ist sichtbar, nicht still falsch — und genau deshalb wird eine durchgefallene Karte gar
  nicht erst angezeigt.
- **Die Deckkraft im Kniebrett** ist ein bekannter Stolperstein (Abschnitt 6) und muss im Sim
  gemessen werden.
