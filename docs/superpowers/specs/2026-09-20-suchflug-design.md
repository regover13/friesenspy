# Eventtyp „Suchflug" — Entwurf (20.09.2026)

Gewinner der Forumsumfrage (Thema 1838, bis 21.09.2026). Grundlage: Issue #21. Der gemeinsame
Rechenkern `app/abdeckung.py` steht seit 15.7.0 und wird hier benutzt, nicht neu geschnitten.

**Diese Runde ist Server und Admin.** Karte, Kniebrett, Badge und Forumsbeitrag kommen danach
und werden vorher eigens besprochen — die Hauptnummer gehört an die sichtbare Änderung.

## 1. Der Ablauf

| Stufe | Bedingung | Was der Server tut |
|---|---|---|
| **Suchen** | Eventbeginn | Havarist an alle Brüggen (Art je Simulator) |
| **Gefunden** | tiefer, langsamer Überflug im Fundradius | `gefunden_am`/`gefunden_von`; **`rauch_signalorange`** neben den Havaristen |
| **Aufgenommen** | Haken *aus:* zweiter Überflug **nach** dem Fund · Haken *an:* Landung am Havaristen | `aufgenommen_am`/`aufgenommen_von`; Fackel wechselt auf **`rauch_hellblau`** |
| **Eingeliefert** | Landung des **Aufnehmenden** an irgendeinem registrierten Platz | `eingeliefert_am`/`_von`/`_icao`; gewertet ist die Zeit **vom Fund bis zu dieser Landung** |

Der Aufnehmende muss nicht der Finder sein (#21). Der Überflug des Finders ist nicht gleichzeitig
das Aufnehmen: Dafür zählt nur ein Überflug **nach** `gefunden_am`.

**Findet niemand:** Bei `dtend` wird die Lage aufgelöst und veröffentlicht, die Fackeln werden
zurückgenommen, die Bilanz sagt „nicht gefunden" und nennt die erreichte Abdeckung.

## 2. Die Wertung gehört der Gruppe

Zwei Zahlen nebeneinander, wie beim FriesenKutter:

* **Gruppenabdeckung** — Anteil der abgesuchten Zellen am Sektor. Das ist der Balken.
* **Beitrag je Pilot** — die Zellen, die er als **erster** abgesucht hat. Doppelarbeit bringt
  niemandem etwas, die Aufteilung entsteht dadurch von selbst.

Dazu die drei Namen und Zeiten der Latches. Ein Wettlauf um den Fund bleibt daneben möglich, aber
niemand geht leer aus, der eine Fläche abgeflogen und nichts gefunden hat.

## 3. Die Zahlen — und warum sie aneinander hängen

| Größe | Vorgabe | Herkunft |
|---|---|---|
| Sektor | 40 × 40 km, Rechteck | simuliert: 4–6 Piloten suchen ihn in ~30 Min ab, 20 × 20 km wäre nach 10 Min vorbei |
| Zellkante | 1,0 km | gleich dem Korridor ⇒ lückenloses Raster |
| Korridor | 1,0 km | Abdeckungsbreite je Seite |
| **Fundradius** | **1,71 km — gerechnet, nicht eingestellt** | Korridor + halbe Zelldiagonale |
| Höhenschranke | 1.500 ft | über dem Wattenmeer ist die Geländehöhe ~0, MSL ≈ AGL |
| Geschwindigkeit | 30–140 kt | unten, damit ein geparktes Flugzeug nicht seine Zelle abdeckt |
| Aufnehmen mit Landung | ≤ 30 kt im Fundradius | Brügge meldet zusätzlich `am_boden` |

**Der Fundradius wird gerechnet.** Sonst lügt der Fortschrittsbalken: Eine abgedeckte Zelle heißt
„ein Track lief im Korridor an ihrem **Mittelpunkt** vorbei", ein Havarist in der Zellecke ist
noch die halbe Zelldiagonale weiter weg. Mit `Korridor + Kante/√2` gilt dagegen: jede abgedeckte
Zelle bedeutet „hier hätten wir ihn gesehen", und **volle Abdeckung garantiert den Fund**. Der
Admin stellt Korridor und Kante ein und kann den Widerspruch nicht mehr erzeugen.

1,71 km Sichtweite auf ein Boot aus 1.500 ft sind dabei realistisch — die Zahl ist keine
Nachgiebigkeit, sondern die Bedingung dafür, dass Balken und Fund dasselbe versprechen.

## 4. Verdeckung: wohin die Koordinate geht und wohin nicht

**An die FriesenBrügge: ja, ab Eventbeginn, ohne Abstandsprüfung.** Sie muss das Objekt
hinstellen. Ein Riegel „erst ab 15 km" war erwogen und **verworfen**: Der einzige Angriff wäre,
den eigenen Datenverkehr mitzulesen, und das ist in dieser Gruppe ein theoretisches Problem.

**An Website und Kniebrett: nie.** Deren Endpunkte liefern `gefunden: ja/nein, von wem, wann` und
das Zellraster mit `offen`/`abgedeckt` — Schlüssel, keine Orte. Das ist keine Anzeigefrage,
sondern eine Zusicherung des Datenmodells: `app/abdeckung.py` gibt nie eine Koordinate heraus
(ein Test hält das fest), und die Endpunkte dieser Runde tun es auch nicht.

Dass abgesuchte Zellen verraten, wo er **nicht** ist, ist kein Leck, sondern die Spielmechanik
aus #21: Wer eine Fläche absucht und nichts findet, verkleinert den Sektor für alle.

## 5. Datenmodell

Eine neue Tabelle, nach dem Muster von `bummel_races` und `transport_events`:

```sql
CREATE TABLE IF NOT EXISTS suchflug_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    dtstart         TEXT NOT NULL,
    dtend           TEXT NOT NULL,          -- effektiv, Mitternacht-Default angewandt
    -- Sektor als Rechteck
    sued            REAL NOT NULL,
    west            REAL NOT NULL,
    nord            REAL NOT NULL,
    ost             REAL NOT NULL,
    kante_km        REAL DEFAULT 1.0,
    korridor_km     REAL DEFAULT 1.0,
    hoehe_max_ft    REAL DEFAULT 1500,
    gs_max_kt       REAL DEFAULT 140,
    gs_min_kt       REAL DEFAULT 30,
    -- Der Havarist. ⚠ Diese zwei Spalten verlassen den Server nur in Richtung FriesenBrügge.
    havarist_lat    REAL,
    havarist_lon    REAL,
    havarist_art    TEXT,                   -- Art aus bruegge_art; NULL = Bootsart je Simulator
    havarist_verdeckt INTEGER DEFAULT 0,    -- 1 = gewürfelt, auch im Admin verborgen
    landung_noetig  INTEGER DEFAULT 0,      -- 1 = an Land, Aufnehmen verlangt eine Landung
    -- Latches
    gefunden_am     TEXT,  gefunden_von     INTEGER,
    aufgenommen_am  TEXT,  aufgenommen_von  INTEGER,
    eingeliefert_am TEXT,  eingeliefert_von INTEGER,  eingeliefert_icao TEXT,
    aufgeloest_am   TEXT,                   -- Lage veröffentlicht (Fund oder dtend)
    -- wie bei den anderen Eventtypen
    source          TEXT,                   -- 'calendar' | 'manual'
    calendar_uid    TEXT UNIQUE,
    push_enabled    INTEGER DEFAULT 1,
    badge_name      TEXT,
    manual_fields   TEXT,
    created_at      TEXT
);
```

**Keine Zellentabelle.** Das Raster entsteht bei jeder Rechnung aus `zellen_aus_box()`; die
Abdeckung kommt aus `position_history` und wird in `progress_snapshot` mit `kind='suchflug'`
zwischengespeichert — dasselbe Muster wie Bummel und Kutter. Gemessen: 39 ms für 1.640 Zellen
gegen sechs Zweistundenspuren, also unkritisch auch ohne Snapshot.

⚠ **`code_version` erhöhen, wenn sich die Rechnung ändert** — sonst bleibt ein eingefrorener
Snapshot stehen (`app/database.py`, `_build_race_view`-Kommentar).

## 6. Wo die Prüfung läuft

Im Poller, im vorhandenen Takt (15 s) — ein Job `_check_suchflug`, nach dem Muster von
`_check_bummel_reveals`. Er rechnet je laufendem Suchflug:

1. **Abdeckung** — `abdeckung(spuren, zellen_aus_box(...), fenster)`.
2. **Fund** — dieselbe Funktion, ein Ziel mit dem gerechneten Fundradius, dasselbe Fenster.
3. **Aufnehmen** — dasselbe Ziel, nur Spurenpunkte **nach** `gefunden_am`; bei
   `landung_noetig` mit `Fenster(gs_max_kt=30)`.
4. **Einliefern** — Landung des Aufnehmenden aus `canonicalize_legs`, erster Zielpunkt nach
   `aufgenommen_am`.

Jede Stufe setzt ihren Latch über eine Funktion, die nur beim ersten Mal schreibt (Muster
`_set_transport_latch`) und dabei die Fackel tauscht. Push je Stufe, wenn `push_enabled`.

**Der Sekundentakt der Brügge bleibt in dieser Runde außen vor.** Er wäre genauer (1 Hz, echte
AGL) und `abstand_zu_strecke_km` kostet eine Mikrosekunde — aber `bruegge_positions` hält nur die
letzte Zeile je Pilot, und Issue #42 (438 × HTTP 500 auf `/api/bruegge/melden`) sagt, dass dieser
Pfad kein guter Ort für neue Arbeit ist, solange er nicht verstanden ist.

## 7. Was der Admin bedient

Ein Bereich wie bei Bummel und Kutter: Sektor durch zwei Ecken auf der Karte, Zellkante,
Korridor, Höhen- und Geschwindigkeitsfenster, Art des Havaristen, Haken „Landung zur Rettung
nötig", Kalendertermin, Push. Dazu:

* **Die Lage des Havaristen setzt der Admin von Hand** auf die Karte — das ist die Vorgabe. Sie
  ist dort auch sichtbar, denn wer das Event anlegt, weiß es ohnehin.

  Ein Land-Wasser-Modell haben wir nicht: Ob der Punkt im Watt oder auf dem Deich liegt,
  entscheidet das Auge des Veranstalters, und bei „Landung nötig" muss er an Land liegen. Von
  Hand gesetzt ist außerdem die bessere Geschichte (die Sandbank vor Juist statt einer
  Zufallskoordinate) und steuert über die Entfernung zum Platz die Länge des Abends.

* **„Würfeln und verbergen" ist ein Knopf daneben** — für den einen Fall, in dem ein Zufallspunkt
  etwas kann, was die Hand nicht kann: **wenn der Veranstalter selbst mitsuchen will.** Dann
  würfelt der Server im Sektor, und die Lage bleibt **auch im Admin verdeckt**, bis sie
  aufgelöst ist (Fund oder `dtend`). Ein Würfel, dessen Ergebnis der Admin nachsehen kann, wäre
  wertlos — deshalb gehören beide Teile zusammen und sind ein Knopf, nicht zwei Felder.

  Bei gesetztem Haken „Landung zur Rettung nötig" ist Würfeln gesperrt: Der Server weiß nicht,
  wo Land ist.

* **Die erwartete Suchdauer** als Hinweis neben der Sektorgröße, aus Kantenlänge, Korridor und
  angenommenen 110 kt — sonst setzt niemand einen Sektor, der zur Abendlänge passt.

## 8. Abhängigkeiten

* **Die Fackeln sind für MSFS 2020 nicht im Katalog.** `FrsRauch_Signalorange` und
  `FrsRauch_Hellblau` sind eigene Objekte der Brügge und stehen als aktiv für `msfs2024` und
  `xplane12`; für `msfs2020` fehlt die Zeile. Ein Paket bedient beide MSFS — es fehlt der
  Prüflauf, das ist **Issue #43**. Ohne ihn sieht ein MSFS-2020-Pilot keine Fackel.
* **Keine Bootsart ist in allen drei Simulatoren aktiv.** `boot_klein`/`boot_gross` nur
  `msfs2020`+`xplane12`, `schiff_segel`/`schnellboot` nur `msfs2024`+`xplane12`. Die Art wird
  deshalb **beim Ausliefern je Simulator** aufgelöst; der Server weiß beim Melden, wer fragt.

## 9. Offene Punkte

1. **Mehrere Havaristen je Event** — nicht in dieser Runde (#21, Frage 4). Das Datenmodell
   verträgt es später als eigene Tabelle; die Latches wandern dann dorthin.
2. **Gewertet wird vom Fund bis zur Landung.** #21 sagt „von der Meldung bis zur Landung", und
   das Aufnehmen liegt jetzt dazwischen. Die Zeit des Aufnehmens wird mitgeschrieben, damit sich
   die Wertung später ohne Datenverlust anders schneiden lässt.
3. **Abbruch eines Aufnehmenden.** Wer aufgenommen hat und dann ohne Landung abmeldet, blockiert
   die Einlieferung. Vorschlag: `aufgenommen_*` verfällt, wenn der Pilot länger als 20 Minuten
   nicht mehr meldet, und die Fackel geht zurück auf orange.
