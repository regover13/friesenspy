# AIP Charts DFS — eine Ansicht, keine Automatik

**Stand:** 31.08.2026, Fassung 2 nach Gutachten
**Ersetzt:** [`2026-08-30-ground-chart-overlay-design.md`](2026-08-30-ground-chart-overlay-design.md)
und den Automatikteil von [`2026-08-23-aip-karten-overlay-design.md`](2026-08-23-aip-karten-overlay-design.md)

---

## 1. Was sich ändert und warum

Zwei Kartentypen, zwei Tabellen, zwei Oberflächen, zwei Automatiken — und beide Automatiken
haben ihren Zweck erfüllt. Entscheidung des Nutzers vom 31.08.2026:

> „Wir brauchen die Automatik nicht mehr. Sie war zur initialen Befüllung gut, aber jetzt
> braucht es sie nicht mehr. Wir behalten natürlich die Zuordnungen. […] Wir bauen die
> Automatik komplett zurück. Für alle Kartentypen! Wir belassen es bei einer einfachen
> Hash-Aktualitätsprüfung."

Der Grund liegt in den Daten: **Die Blätter ändern sich fast nie.** Die am 31.08.2026
durchgesehenen Flugplatzkarten tragen Ausgabedaten von 2014 bis 2026 — EDPC von 2014, EDPA
2018, EDSL 2021, EDRB und EDRG 2022, EDRJ 2023, EDRK und EDRT 2024. Beim einzigen bisherigen
Auffrischlauf waren **437 von 446 Blättern unverändert**. Eine Maschinerie, die Rahmen sucht,
Ziffern liest und Bahnen vermisst, arbeitet also fast immer für nichts — und wenn sie doch
etwas findet, ist die Frage ohnehin eine, die nur ein Mensch beantworten kann: *Stimmt die
Passung auf dem neuen Blatt noch?*

**Jede gesetzte Passung bleibt erhalten.** Der Rückbau löscht Code, keine Daten — und, siehe
3.2, auch keine Klickpunkte.

---

## 2. Rückbau

| Datei | vorher | nachher |
|---|---|---|
| `app/aip_charts.py` | 1621 | ~250 — nur noch Beschaffung |
| `scripts/aip_bestand.py` | 347 | ~140 — Hash-Vergleich und Abgleich mit `airport_links` |
| `scripts/ground_chart_bestand.py` | 299 | **gelöscht**, geht in `aip_bestand.py` auf |
| `scripts/ground_chart_probe.py` | 253 | **gelöscht** |
| `scripts/aip_schablonen.py` | — | **gelöscht** |
| `scripts/aip_band_zeigen.py` | — | **gelöscht** |
| `scripts/aip_handpassung.py` | — | **gelöscht** |
| `app/ground_charts.py` | 238 | 238 — hier fällt nichts mehr, die Bahnvermessung ist bereits fort |

**Was aus `aip_charts.py` bleibt:** `airac_url`, `airac_kennung`, `bild_aus_html`,
`kapitel_links`, `kapitelseiten`, `seiten_des_kapitels`, `blatt_schreiben`, `blatt_pfad`.
Alles, was Blätter beschafft und ablegt — nichts, was sie deutet. **`handpassung` geht mit**,
ersetzt durch `ground_charts.handpassung` (Abschnitt 5).

**Aus `ground_charts.py` bleibt alles**, einschließlich `sorte_erkennen` — es ist der einzige
Aufrufer von `bahnfarbe` und `sorte_aus_ton` und trägt die Vorbelegung der Seitenauswahl.

### 2.1 Die drei Skripte, die mitgehen müssen

Sie importieren die gelöschten Funktionen **produktiv** und brechen sonst beim Import:

| Skript | ruft |
|---|---|
| `scripts/aip_schablonen.py` | `rahmen_finden`, `raster`, `tick_positionen`, `zeichen_im_band` |
| `scripts/aip_band_zeigen.py` | `Rahmen`, `rahmen_finden`, `tick_positionen_mit_band`, `band_grenzen` |
| `scripts/aip_handpassung.py` | `Rahmen`, `rahmen_finden`, `tick_positionen_mit_band`, `raster` — Zeilen 157–161 |

`aip_handpassung.py` ist **kein** „prüfen und mitziehen"-Fall. Eine frühere Fassung dieser
Spec behauptete, es nutze die Automatik nur im Kommentar; es ruft sie in vier Zeilen auf.
`aip_schablonen.py` hängt zusätzlich an `_SCHABLONEN`, auf die `aip_charts.py`
zurückverweist — fallen die Schablonen, fällt beides.

### 2.2 `runway_ref.py`

`meter` und `meter_je_grad` trägt die Handpassung; die bleiben. `bahnen()` und
`datei_holen()` hätten **keinen Produktivaufrufer mehr**, es sei denn die Passen-Maske zeigt
Schwellenkoordinaten an. Sie tut es (5.3); damit bleibt das Modul vollständig. Ohne diesen
Punkt wären es 110 Zeilen toter Code mit zehn Tests dahinter.

---

## 3. Eine Tabelle

```sql
CREATE TABLE IF NOT EXISTS aip_charts_dfs (
    icao          TEXT NOT NULL,
    sorte         TEXT NOT NULL,   -- 'sichtflug' | 'flugplatzkarte' | 'rollkarte'
    seite_nr      INTEGER,         -- Seite im Kapitel, NICHT die URL. Siehe 6.1.
    quell_hash    TEXT NOT NULL DEFAULT '',
    bild_hash     TEXT NOT NULL DEFAULT '',
    nord          REAL NOT NULL DEFAULT 0,
    sued          REAL NOT NULL DEFAULT 0,
    west          REAL NOT NULL DEFAULT 0,
    ost           REAL NOT NULL DEFAULT 0,
    feld_nord     REAL NOT NULL DEFAULT 0,
    feld_sued     REAL NOT NULL DEFAULT 0,
    feld_west     REAL NOT NULL DEFAULT 0,
    feld_ost      REAL NOT NULL DEFAULT 0,
    drehung       REAL NOT NULL DEFAULT 0,
    mps           REAL NOT NULL DEFAULT 0,
    p1_x REAL, p1_y REAL, p1_lat REAL, p1_lon REAL,
    p2_x REAL, p2_y REAL, p2_lat REAL, p2_lon REAL,
    status        TEXT NOT NULL,
    status_vorher TEXT,            -- woher 'pruefen' kam. Siehe 4.3.
    airac         TEXT NOT NULL DEFAULT '',
    geprueft_am   TEXT,
    PRIMARY KEY (icao, sorte)
);
```

**Der Primärschlüssel ist `(icao, sorte)`**, weil **alle 110** Plätze mit Flugplatzkarte auch
eine Sichtflugkarte haben — gemessen, 110 von 110. Mit `icao` allein kollidieren genau diese
110 Zeilen.

Eine frühere Fassung begründete das mit „bei EDDM Flugplatz- *und* Rollkarte". Das gibt es im
Bestand nicht: `aip_ground_charts.icao` ist heute Primärschlüssel, ein Platz kann dort gar
nicht beide haben. Der Schlüssel ist trotzdem richtig, die Begründung war es nicht.

### 3.1 Migration — drei Riegel

`init_db` läuft bei **jedem Containerstart**, und sein Migrationsmuster ist
`except sqlite3.OperationalError: pass` (`app/database.py:830-837`). Das ist ausschließlich
für `ALTER TABLE … ADD COLUMN` idempotent. **Ein `INSERT` in eine Tabelle mit Primärschlüssel
wirft `IntegrityError` — die wird dort nicht gefangen, `init_db` bricht ab, die App startet
nicht.** Deshalb drei Riegel:

1. **Merker in `job_laeufe`** unter `migration_charts_dfs`. Steht er, passiert nichts.
2. **`INSERT … ON CONFLICT DO NOTHING`** — auch wenn jemand den Merker löscht, wird keine
   bearbeitete Zeile überschrieben.
3. **Eigener `try`-Block mit `except sqlite3.Error`**, nicht `OperationalError`. Ein
   Fehlschlag der Migration darf den Dienststart nicht verhindern; er wird protokolliert.

### 3.2 Was übernommen wird — einschließlich der Klickpunkte

**`rahmen_px` ist bei den Sichtflugkarten das Klickprotokoll, keine Innerei.** Gemessen am
Bestand:

```
EDWE  rahmen_px = "85.0,238.0,1147.0,818.0"    →  p1_x, p1_y, p2_x, p2_y
      feld_nord/feld_west = 53.512167/6.886654  →  p1_lat, p1_lon
      feld_sued/feld_ost  = 53.291635/7.564815  →  p2_lat, p2_lon
```

**Alle 446 Zeilen tragen ein wohlgeformtes `rahmen_px`** — kein einziger Ausfall. Die
Migration füllt daraus `p1_*`/`p2_*` für den **gesamten** Sichtflugbestand.

Eine frühere Fassung verwarf die Spalte zwei Absätze nachdem sie `p1_*`/`p2_*` mit der
Begründung einführte, heute gehe verloren, worauf geklickt wurde — und hätte damit genau das
zerstört, was sie aufheben wollte.

Bei den 110 Ground-Zeilen sind die Punkte **unrettbar**: Sie wurden nie abgelegt. Dort
bleiben `p1_*`/`p2_*` leer; wer nachjustieren will, klickt neu. Das ist der einzige echte
Verlust der Migration.

**`quell_hash` kommt aus `bild_hash`** — mit einer Einschränkung, die zählt:
`aip_charts.bild_hash` ist nicht der Hash der DFS-Rohbytes, sondern der des abgelegten, ggf.
gedrehten Blatts (`app/main.py:4671`: „Der Hash wird NACH dem Drehen gebildet"). Für die
sieben quer gedruckten Blätter stimmt er nicht mit dem Rohblatt überein.

**Regel daraus:** Findet der Job einen abweichenden Hash und trägt die Zeile noch den AIRAC
der Migration, füllt er `quell_hash` **stumm** nach, statt `pruefen` zu setzen. Erst ab dem
zweiten Zyklus ist eine Abweichung eine echte Änderung. Ohne diese Regel meldete der erste
Lauf sieben Karten als geändert, die es nicht sind.

`airac` ist in beiden Tabellen durchgehend `'2026AUG20'`, `geprueft_am` in keiner Zeile
NULL — geprüft, keine Typkonflikte.

**Die alten Tabellen bleiben stehen**, bis der neue Stand geprüft ist. Das ist keine
Absicherung gegen Doppellauf — dafür sind die drei Riegel da —, sondern die Möglichkeit, die
Migration nach Löschen des Merkers zu wiederholen.

### 3.3 Blätter auf der Platte

Heute: `<db>/aip/<ICAO>.png` und `<db>/aip_ground/<ICAO>.png`. Der Ground-Pfad ist **nur auf
ICAO geschlüsselt** (`app/main.py:4243`) — Flugplatz- und Rollkarte desselben Platzes
überschrieben sich. Künftig:

```
<db>/aip_dfs/<ICAO>.<sorte>.png                 # abgelegt, ggf. gedreht
<db>/aip_dfs/<ICAO>.<sorte>.roh.png             # Rohblatt, zum Klicken
<db>/aip_dfs/<ICAO>.<sorte>.neu.<hash8>.png     # neues Blatt bei Status 'pruefen'
```

**Die Migration verschiebt die Dateien mit** — sonst zeigt jede Karte ins Leere. Der Hash im
Namen des neuen Blatts ist kein Schmuck: Ohne ihn gibt es keinen Bezug zwischen dem, was der
Nutzer ansieht, und dem, was er bestätigt (4.4).

---

## 4. Status

| Status | Bedeutung |
|---|---|
| `gepasst` | Der Nutzer hat die Lage gesetzt oder bestätigt. |
| `auto` | Von der alten Automatik oder von Claude gesetzt — **vom Nutzer nicht angesehen**. |
| `offen` | Blatt liegt vor, keine Lage gesetzt. |
| `nicht_gefunden` | Nachgesehen, kein passendes Blatt im Kapitel. Siehe 4.2. |
| `pruefen` | Neues Blatt bei der DFS; die bestehende Passung ist nicht bestätigt. |
| `verwaist` | Der Eintrag in `airport_links` ist verschwunden. Siehe 4.5. |

**Der Wert heißt `pruefen`, ohne Umlaut.** Er wird in Python, SQL, JavaScript und
Testliteralen verglichen; ein Umlaut darin ist eine Fehlerquelle ohne Gegenwert.

`auto` heißt **ungeprüft**, unabhängig davon, wer gerechnet hat. Es stirbt aus, sobald der
Nutzer eine Karte durchsieht, und entsteht neu nur, wenn er Claude eine Passung aufträgt.

### 4.1 Abbildung des Bestands

| bisher | wird | Anzahl |
|---|---|---|
| `aip_charts`, `quelle='hand'` | `sichtflug` / `gepasst`, **mit** Klickpunkten | 171 |
| `aip_charts`, `quelle='auto'` | `sichtflug` / `auto`, **mit** Klickpunkten | 275 |
| `aip_ground_charts`, `status='gepasst'` | Sorte übernehmen / `auto`, ohne Klickpunkte | 68 |
| `aip_ground_charts`, `status='ungepasst'` | Sorte übernehmen / `offen` | 42 |
| | **Summe** | **556** |

Die 68 Ground-Passungen fallen bewusst auf `auto` zurück: Sie stammen von Claude, der Nutzer
hat keine davon gesehen.

### 4.2 `nicht_gefunden` wird geschrieben, nicht hergeleitet

**Kein einziger** der 446 Plätze ist ohne Sichtflugzeile — `aip_charts` deckt `airport_links`
exakt ab. Nach der Definition „Plätze ohne Zeile", die eine frühere Fassung verwendete, gäbe
es also null davon; dieselbe Fassung behauptete an anderer Stelle 336. Der Widerspruch löst
sich, sobald man je Sorte denkt.

Ein hergeleiteter Status ist zudem **nicht speicherbar**: „Ich habe nachgesehen, EDXY hat
keine Rollkarte" ließe sich nicht festhalten, und die Arbeitsliste bliebe dauerhaft rund 780
Einträge lang, in denen nichts abhakbar ist.

**Deshalb:** Wer die Seitenauswahl eines Platzes öffnet und keine passende Seite findet,
setzt `nicht_gefunden`; die Zeile entsteht dabei. Ein Platz ohne Zeile erscheint in der Liste
als **„— nicht nachgesehen"** — das ist kein Status, sondern die Abwesenheit eines Eintrags.

### 4.3 Aus `pruefen` heraus

Alle drei Wege enden **nicht** pauschal auf `gepasst`. Beim Setzen von `pruefen` merkt sich
der Job den bisherigen Status in `status_vorher`:

| Weg | Wirkung |
|---|---|
| **übernehmen** | neues Blatt wird zum gültigen, `quell_hash` nachziehen, Status → `gepasst` |
| **neu passen** | zwei Punkte neu setzen, Status → `gepasst` |
| **verwerfen** | altes Blatt bleibt, **`quell_hash` trotzdem nachziehen**, Status → `status_vorher` |

Ohne das Zurückstellen landete eine der 42 als `offen` migrierten Zeilen — Lagefelder alle
0 — nach einem Blattwechsel auf `gepasst` und damit im Kniebrett, mit
`nord=sued=west=ost=0`.

**Auch „verwerfen" zieht `quell_hash` nach.** Sonst findet der nächste Wochenlauf denselben
abweichenden Hash und setzt die Zeile erneut auf `pruefen` — die Liste wäre nach dem ersten
Verwerfen dauerhaft unaufräumbar. Diese Falle war bei der Vorschlagstabelle schon einmal
gestellt und behoben; die Begründung steht als Kommentar im heutigen Schema
(`app/database.py:371-377`).

### 4.4 Zweite Änderung, während `pruefen` steht

Der Job überschreibt `quell_hash` **nicht** und legt das neue Blatt unter einem Namen mit
Hash ab (3.3). Wer das erste neue Blatt schon angesehen hat, sieht in der Maske weiterhin
genau das, was er bestätigen würde.

### 4.5 `verwaist` — die Regel bleibt

Eine Karte, deren Eintrag in `airport_links` verschwindet, wird **nicht gelöscht**. Sie geht
auf `verwaist`, verschwindet aus der Auslieferung und kehrt zurück, sobald der Link wieder
auftaucht — ein AIRAC-Wechsel benennt Kapitelseiten um. Nutzerentscheidung vom 30.08.2026,
heute in `verwaisen()` umgesetzt (`scripts/aip_bestand.py:200-219`); der Abgleich mit
`airport_links` bleibt Teil des Jobs (Abschnitt 7). Im Bestand steht die Zahl auf 0 — der
Fall ist seit Einführung nicht eingetreten, das heißt nicht, dass es ihn nicht gibt.

---

## 5. Die Passen-Maske

**Zwei Punkte, je Bildposition und Koordinate.** Zwei Rahmenecken sind zwei Punkte, und die
vier Gradwerte eines Kartenrahmens sind deren Koordinaten — links-oben ist (Nord, West),
rechts-unten ist (Süd, Ost).

```
Punkt 1:  Bild x [   ] y [   ]     Breite [  ]° [     ]'  N     Länge [  ]° [     ]'  E
Punkt 2:  Bild x [   ] y [   ]     Breite [  ]° [     ]'  N     Länge [  ]° [     ]'  E
Drehung:  [      ]°   (aus den Punkten vorbelegt, überschreibbar)
```

**Grad und Minuten bleiben getrennt.** Auf dem Blatt steht `N 47° 51,53'`; ein einzelnes Feld
„(Grad)" verleitet dazu, 47.5153 einzutragen — gemeint sind 47,859°. Zwölf Kilometer
Unterschied, am 24.08.2026 genau so passiert.

Gerechnet wird auf dem **Rohblatt** mit `ground_charts.handpassung`, gedreht und abgelegt mit
`norden`. Nachgerechnet an zwei Bestandszeilen (EDWE, EDAZ) mit deren Rahmenecken als
Passpunkten: **`norden()` leitet die Blattgrenzen ebenfalls über die Rahmenkanten hinaus ab**
— es bildet die vier Bildecken durch die Abbildung ab, nicht die Hülle der Passpunkte. Der
45-Prozent-Fehler vom 24.08. kehrt nicht zurück.

### 5.1 Der Saum hängt an der Sorte

`aip_charts.handpassung` legt `feld_*` **exakt** auf die geklickten Rahmenecken;
`ground_charts.norden` legt es auf die Hülle plus `FELD_SAUM_M = 1000`. Für ein Sichtflugblatt,
dessen Kartenfeld der Rahmen präzise definiert, schaltete die Ebene damit auf allen vier
Seiten einen Kilometer früher ein — und die 171 migrierten Zeilen behielten ihr rahmengenaues
`feld_*`, jede neu gesetzte bekäme das andere. Zwei Bedeutungen in einer Spalte.

**Deshalb:** `sichtflug` → 0 m, Flugplatz- und Rollkarte → 1000 m. Bei letzteren sind die
Passpunkte zwei Bahnschwellen mitten auf dem Platz; ohne Saum schaltete die Karte erst ein,
wenn man schon auf der Bahn steht.

### 5.2 Nicht drehen, wenn nichts zu drehen ist

`norden()` ruft `Image.rotate(-drehung, resample=BICUBIC, expand=True)` bedingungslos. An
EDWE und EDAZ gemessen ergibt die Rechnung aus den Rahmenecken Drehungen von **0,04° bis
0,09°** — die Leinwand wüchse um ein bis zwei Pixel, jedes Pixel würde interpoliert, und das
an einem Blatt, dessen Gradnetzstriche drei Pixel breit sind. Der `bild_hash` änderte sich,
obwohl inhaltlich nichts geschieht.

**Deshalb:** Unter **0,25°** wird nicht gedreht, `drehung` wird auf 0 gesetzt. Bei 90°, 180°
und 270° — auf 0,25° genau — wird `Image.transpose` verwendet statt `rotate`: verlustfrei,
und genau der Fall der sieben quer gedruckten Blätter.

### 5.3 Schwellenkoordinaten als Hilfe

Beim Passen einer Flugplatz- oder Rollkarte zeigt die Maske die Bahnschwellen des Platzes aus
`runway_ref.bahnen()` — Bezeichnung, Länge und beide Koordinaten in Grad und Minuten, zum
Abschreiben in die Punktfelder. Das ist die Begründung dafür, `bahnen()` zu behalten (2.2),
und der Weg, auf dem die 68 Ground-Karten überhaupt entstanden sind.

Bei Sichtflugkarten steht die Anzeige nicht — dort liest man die Werte vom Kartenrand ab.

### 5.4 Status `pruefen`

Die Maske zeigt das **neue** Blatt mit den **alten** Passpunkten darauf. Damit ist auf einen
Blick zu sehen, ob sie noch dort liegen, wo sie sollen.

Das ersetzt bewusst eine maschinelle Prüfung: Heute sichern `blatt_auffrischen` und
`zeigt_denselben_ausschnitt` ab, dass ein neues Blatt denselben Kartenausschnitt zeigt, bevor
es unter eine bestehende Passung gelegt wird. Beide werden gelöscht; an ihre Stelle tritt der
Augenschein. Der Nutzerbefehl vom 30.08.2026 („keinesfalls erneut verzerrt werden") bleibt
gewahrt — durch einen Menschen statt durch eine Rechnung.

---

## 6. Liste, Filter, Seitenauswahl

Spalten: ICAO, Sorte, Status, AIRAC, Drehung, Blattlink, Aktionen. Filter über Status und
Sorte, je Mehrfachauswahl; Vorgabe: alles außer `gepasst`.

### 6.1 Die Seite wird als Nummer gemerkt, nicht als URL

**`seite_url` überlebt den AIRAC-Wechsel nicht — sie enthält ihn:**

```
https://aip.dfs.de/BasicVFR/2026AUG20/pages/8E6E4101DFC29400F9A64C7F2E96F12A.html
```

Der dauerhafte Bezeichner ist `airport_links.aip_url` (`…/BasicVFR/pages/P001A7.html`, ohne
AIRAC); er leitet per Meta-Refresh in die jeweils aktuelle Ausgabe. Beim nächsten Zyklus
liefert die gemerkte URL 404 — für **alle** Zeilen gleichzeitig, und zwar genau in dem
Moment, in dem sich Blätter tatsächlich ändern könnten.

**Deshalb speichert die Zeile `seite_nr`**, die Position im Kapitel, und der Job löst die URL
bei jedem Lauf frisch über `airac_url` + `seiten_des_kapitels` auf. Die Nummer zeigt die
Liste ohnehin an.

### 6.2 Die 446 Zeilen ohne Seitenangabe

**`seite_url` ist in allen 446 Sichtflugzeilen leer** — die Spalte wurde am 31.08.2026
nachgetragen und nie befüllt. Ein Job, der „für jede Zeile mit gesetzter Seite" arbeitet,
prüfte 110 von 556 Zeilen und ausgerechnet keine Sichtflugkarte.

**Deshalb:** Die Migration füllt `seite_nr` nicht, der **erste Joblauf** tut es. Für jede
Zeile ohne `seite_nr` löst er das Kapitel auf und sucht die Seite, deren Bild dem
gespeicherten `bild_hash` entspricht. Findet er keine, bleibt `seite_nr` leer und die Zeile
erscheint als **„Seite unbekannt"** — sichtbar, nicht stumm übersprungen.

### 6.3 Seitenauswahl

Vorschaubild und Seitennummer. **Sonst nichts** — keine „passt"-Spalte, kein Bahnton, keine
Dateigröße. Die alte „passt"-Spalte war irreführend: Dieselbe Automatik hat bei EDDK aus
sechs Kapitelseiten die falsche gewählt (Nutzer, 24.08.2026).

Beim Übernehmen wählt der Nutzer die Sorte; `ground_charts.sorte_erkennen` belegt sie vor.

---

## 7. Der Job

Ein Job, `aip_hash_pruefen`, wöchentlich. Je Zeile:

1. Kapitel über `airport_links.aip_url` auflösen, Seite `seite_nr` holen (6.1).
2. Ist `seite_nr` leer: einmalig über den `bild_hash` suchen und merken (6.2).
3. Rohbytes hashen, mit `quell_hash` vergleichen.
4. Weicht er ab → `status_vorher` sichern, Status `pruefen`, neues Blatt ablegen, SSE
   `{"type": "aip_charts"}` senden. **Ausnahme:** die Nachfüllregel aus 3.2.
5. Steht der Platz nicht mehr in `airport_links` → Status `verwaist` (4.5).

Sonst nichts. Kein Rechnen, kein Schreiben einer Passung.

**Kosten: ein Abruf je Karte**, nicht zwei — das Bild steckt als data-URI in derselben
HTML-Seite (`bild_aus_html`). Bei 556 Zeilen also 556 Abrufe, plus je Platz einen für die
Kapitelauflösung. Eine frühere Fassung nannte 1100; die Zahl stammte aus einem Kommentar in
`app/poller.py:569` und war schon dort falsch.

**Fälligkeit:** `interval, weeks=1` **mit** `next_run_time`, damit er nicht erst eine Woche
nach dem Anmelden zum ersten Mal liefe — der Vorgängerjob hat deshalb von seiner Einführung
bis zum 31.08.2026 kein einziges Mal gearbeitet. Und **zusätzlich** der Merker in
`job_laeufe`, damit `next_run_time` ihn nicht zum Deploy-Job macht. Zwei Mechanismen gegen
zwei verschiedene Fehler.

---

## 8. Die Sperre bleibt

Eine frühere Fassung strich sie mit der Begründung, es gebe keinen automatischen Schreibpfad
mehr. Für den Job stimmt das. Für das System nicht:

**Der Seitenwähler bleibt und würde jede Passung nullen.** `admin_aip_seite_waehlen`
(`app/main.py:4630`) schreibt bei gescheiterter Passung alle Lagefelder auf 0 (`:4694`) und
ist heute durch zwei Riegel geschützt — den Bildhash-Vergleich (`:4686`, eingebaut nachdem er
am 25.08.2026 EDAZ auf null zurücksetzte) und `HandpassungGesperrt` (`:4713`). Nach dem
Rückbau ist `passung` **immer** `None`; der nullende Zweig wäre der einzige.

**Deshalb:**

* Die Sperre bleibt. Das Prädikat wechselt von `quelle='hand'` auf `status='gepasst'`.
* Der Seitenwähler schreibt bei **unverändertem Blatthash gar nichts** — er wählt die Seite,
  er passt nicht.
* `upsert_chart_dfs` wirft `PassungGesperrt`, wenn eine Zeile mit `status='gepasst'` ohne
  ausdrückliches `hand_ueberschreiben=True` überschrieben würde.

Was tatsächlich entfällt, ist die **Vorschlagstabelle**: Ohne gerechnete Alternative gibt es
nichts vorzuschlagen. Ihr Grabstein-Mechanismus lebt in 4.3 weiter.

---

## 9. Beide Karten liegen übereinander

**Die Flugplatzkarte liegt immer über der Sichtflugkarte, nicht an ihrer Stelle.**
Entscheidung des Nutzers vom 31.08.2026; sie ersetzt die Verdeckungslogik der Vorgängerspec.

Ein um 37° gedrehtes Blatt wird als achsenparalleles Rechteck abgelegt, dessen Ecken
durchsichtig sind — bei EDDL rund die Hälfte der Fläche. Liegt darunter die Sichtflugkarte,
füllt sie genau diese Ecken und den Rand des Platzes.

**Über `zIndex`**, nicht über `bringToFront()` — letzteres hängt an der Einfügereihenfolge und
kippt, sobald eine Karte nach dem SSE-Ereignis neu geladen wird.

**Was entfällt:** `_groundVerdecktSichtflug()` (`index.html:10421`) und der Block in
`_aipKarteNachfuehren` (`:10256`), der die Sichtflugkarte ausblendet — mit ihnen die drei
Zustände, die sie nötig gemacht hatten.

**Der Frontend-Zustand muss auf `(icao, sorte)` umgestellt werden.** `_groundAktiv`,
`_groundFest` und `_groundAus` halten heute eine ICAO (`index.html:10404`); der Kommentar
darüber begründet den getrennten Zustand ausdrücklich damit, dass Sichtflug- und
Flugplatzkarte desselben Platzes dieselbe ICAO tragen. Sobald ein Platz Flugplatz- **und**
Rollkarte hat — was diese Spec ermöglicht —, ist der Schlüssel mehrdeutig und
`find(k => k.icao === _groundFest)` trifft die erste von zweien.

---

## 10. Drei Fehler, die mitgehen

**Rohbild wird beim Passen nicht angezeigt.** `/aip-ground-chart/{icao}.png`
(`main.py:4278`) steht vor `/aip-ground-chart/{icao}.roh.png` (`:4392`); Starlettes
`str`-Konvertor ist greedy und schluckt den Punkt, `EDDL.roh.png` landet auf der ersten
Route mit `icao="EDDL.roh"`, scheitert an `re.fullmatch(r"[A-Z0-9]{4}")` und liefert 404.
**Behebung:** eigener Pfad `/aip-chart-roh/{icao}/{sorte}.png` — **mit `require_admin`**, das
die erreichbare Route heute nicht hat und die unerreichbare schon.

**Der Transparenzregler fehlt bei Flugplatzkarten.** `_aipDeckkraftAnzeigen` schaltet ihn über
`_aipKarteAktiv` (`index.html:10239`); liegt eine Flugplatzkarte, ist der null.
`_aipDeckkraftSetzen` (`:10233`) führt zudem nur das Sichtflug-Overlay nach. **Behebung:** an
„irgendeine Karte liegt" binden, beide Overlays bedienen. Bricht `tests/test_aip_ui.py:318`
und `:383`, die auf die alten Zeichenketten festgenagelt sind — beide sind anzupassen.

**„Gültig · Vorschlag" zeigt zweimal dasselbe Bild.** Folgt aus dem Wegfall der
Vorschlagstabelle.

---

## 11. Vorgaben

* **Keine neue Abhängigkeit.**
* `init_db(db_path: str)` nimmt einen **Pfad**; `get_connection(db_path: str)` — es gibt kein
  `get_conn`; `settings.DB_PATH`.
* Kein `tests/conftest.py`. Fixtures je Testdatei, DB über `tmp_path`.
* `conn = get_connection(...)` / `try` / `finally: conn.close()`.
* Deutsche Bezeichner und Kommentare.
* **`"highlight": false`** in jedem Changelog-Eintrag.
* Kein `localStorage` im Frontend — `_prefLies` / `_prefSchreib`.
* Frontend-Tests binden an Deklarationen, nicht an Kommentare.
* Breite Tabellen: `.table-wrap`; in `.scroll-list` zusätzlich Höhenbegrenzung **und**
  sichtbare Scrollbar-Styles.
* **`CLAUDE.md` bekommt die Invarianten des neuen Standes**: eine Tabelle, keine Automatik,
  Passung nur über zwei Punkte, `nicht_gefunden` wird geschrieben statt hergeleitet. Heute
  steht dort nichts zum AIP-Teilsystem; in drei Monaten rekonstruiert das sonst niemand.

---

## 12. Offene Risiken

1. **Die Migration bewegt 556 Zeilen und verschiebt Dateien.** Sicherung vorher, Gegenprobe
   mit erwarteten Zahlen nachher, Rückrollen bei Abweichung.
2. **Der Rückbau entfernt rund 1900 Zeilen** (`aip_charts.py`, drei Skripte,
   `ground_chart_bestand.py`). Rund 89 von 222 Tests in den betroffenen Dateien brechen. Die
   meisten sind ersatzlos zu löschen — aber **`test_handpassung_schutz.py` prüft eine
   Invariante, die bleibt** (Abschnitt 8): Die Prädikate wechseln von `quelle='hand'` auf
   `status='gepasst'`, gelöscht wird dort nichts.
3. **Die 42 offenen Karten und die Plätze ohne Ground-Blatt bleiben Arbeit.** Die Ansicht
   macht sie sichtbar; sie passt sie nicht.
