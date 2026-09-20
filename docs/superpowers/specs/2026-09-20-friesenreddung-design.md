# Eventtyp 🚨 „FriesenReddung" — Entwurf (20.09.2026)

Gewinner der Forumsumfrage (Thema 1838, bis 21.09.2026). Grundlage: Issue #21, dort noch unter
dem Arbeitstitel „Suchflug". Der gemeinsame Rechenkern `app/abdeckung.py` steht seit 15.7.0 und
wird hier benutzt, nicht neu geschnitten.

**Der Name:** „Reddung" ist Platt für Rettung (von „redden" = retten). Er reiht sich neben
🏁 FriesenBummel, 🦐 FriesenKutter, 🔭 FriesenKieker, 🚩 FriesenBaake und 🌊 Deichkontrolle.
**Beim ersten Nennen in Nutzertexten in Klammern erklären** — „FriesenReddung (Reddung ist Platt
für Rettung)" —, wie es die FriesenBrügge vormacht. Und wie dort: **niemals nur „Reddung",
immer der volle Name.**

**Diese Runde ist Server und Admin.** Karte, Kniebrett, Badge und Forumsbeitrag kommen danach
und werden vorher eigens besprochen — die Hauptnummer gehört an die sichtbare Änderung.

## 1. Der Ablauf

| Stufe | Bedingung | Was der Server tut |
|---|---|---|
| **Suchen** | Eventbeginn | Havarist an alle Brüggen (Art je Simulator) |
| **Gefunden** | tiefer, langsamer Überflug im Fundradius | `gefunden_am`/`gefunden_von`; **`rauch_signalorange`** neben den Havaristen |
| **Aufgenommen** | *nur wenn `aufnehmen_noetig`* — im Umkreis des Havaristen, **nach** dem Fund: *Haken an* eine Landung nach den Regeln des Projekts · *Haken aus* unter 30 kt | `aufgenommen_am`/`aufgenommen_von`; Fackel wechselt auf **`rauch_hellblau`** |
| **Eingeliefert** | *nur wenn `aufnehmen_noetig`* — Landung des **Aufnehmenden** an irgendeinem registrierten Platz | `eingeliefert_am`/`_von`/`_icao`; gewertet ist die Zeit **vom Fund bis zu dieser Landung** |

**Aufnehmen darf irgendeiner.** Das ist eine Teamleistung, und der Finder kann es unter Umständen
gar nicht — er sitzt im falschen Flugzeug, steht zu weit weg, oder hat nicht mehr genug Sprit.
Der Überflug des Finders ist deshalb auch nicht gleichzeitig das Aufnehmen: Dafür zählt nur ein
Überflug **nach** `gefunden_am`.

**Das Finden selbst ist in allen Fällen gleich** — derselbe tiefe, langsame Überflug, egal ob
danach gelandet oder geschwebt werden muss. Ein Flächenflugzeug findet den Havaristen also auch
dann, wenn nur ein Hubschrauber ihn aufnehmen kann. Suchen ist Gruppenarbeit, Bergen
Spezialarbeit; der Haken „Landung zur Rettung nötig" wirkt ausschließlich auf Stufe 3.

### Ein Abend kann mit dem Fund enden

**Haken „Aufnehmen nötig", Vorgabe an.** Ist er aus, ist der Fund der Schluss: keine Aufnahme,
keine Einlieferung. Gewertet sind dann die Abdeckung, der Finder und die Zeit. Das ist der
kurze Abend — eine Stunde suchen, jemand findet, fertig.

Die beiden Haken verschachteln sich:

| `aufnehmen_noetig` | `landung_noetig` | Der Abend |
|---|---|---|
| **aus** | (im Admin gesperrt) | endet mit dem Fund |
| an | an | Landung am Wrack, dann einliefern |
| an | aus | Schwebeflug, dann einliefern |

**Die Fackel wird dann gleich hellblau.** Orange heißt „gefunden, noch nicht gerettet" — wenn
nichts mehr zu tun ist, wäre das eine falsche Auskunft an alle, die noch in der Luft sind.

### Wenn der Aufnehmende abbricht

Wer aufgenommen hat und dann ohne Landung verschwindet, blockierte sonst die Einlieferung für
den ganzen Abend. Ein Haken im Admin regelt das: **„Aufnahme verfällt, wenn der Aufnehmende
abmeldet"**, Vorgabe an.

⚠ **Der Auslöser ist die Abmeldung, keine Zeitschwelle.** „20 Minuten Funkstille" war der erste
Vorschlag und wäre eine erfundene Größe gewesen — das Ereignis steht längst in den Daten: Der
Pilot verschwindet aus dem VATSIM-Strom, und der Poller sieht das ohnehin in jedem Takt.

**Eine Schonfrist braucht es trotzdem, aber aus einem anderen Grund:** Ein Absturz zum Desktop
mit Wiederanmeldung ist im Simulator Alltag. Ohne Schonfrist reichte ein zweiminütiger Aussetzer
die Rettung an jemand anderen weiter. Zehn Minuten nach dem Verschwinden, und nur wenn er nicht
zurückgekommen ist — dann werden `aufgenommen_am`/`aufgenommen_von` geleert, die Fackel geht
zurück auf **orange**, und ein Push sagt, dass die Rettung wieder offen ist.

**Ohne den Haken bleibt die Aufnahme stehen, bis der Admin sie freigibt.** Der Knopf dafür muss
es in beiden Fällen geben — sonst hängt ein Abend an einer Automatik, die im Einzelfall falsch
liegt.

**Die Fackel hat drei Stufen, und sie bleibt stehen:** 🟠 orange nach dem Fund („gefunden, noch
nicht gerettet"), 🔵 hellblau nach der Aufnahme („unterwegs zum Platz"), 🔴 **rot beim Abschluss**
— und die rote steht bis `dtend`.

⚠ **Eine aufgelöste Reddung räumt nichts weg.** Hier stand zuerst das Gegenteil, und das war ein
Fehler: Bei `aufnehmen_noetig = 0` löst der Fund die Lage im **selben** Poller-Takt auf — die
Fackel wäre erschienen und verschwunden, ohne dass sie jemand gesehen hätte. Und im Normalfall
hätte sich nach der Einlieferung alles schlagartig aufgelöst, vor den Augen derer, die noch
hinfliegen. Wrack und Fackel laufen jetzt über `gilt_bis` (= `dtend`) von selbst ab; gezielt
weggenommen wird nur beim **Löschen** des Events.

**Findet niemand:** Bei `dtend` wird die Lage aufgelöst und veröffentlicht — die rote Fackel
markiert dann die Stelle, und die Bilanz sagt „nicht gefunden" und nennt die erreichte
Abdeckung.

## 2. Gesucht wird meist ein Flugzeug

**Der Havarist ist im Regelfall eine abgestürzte oder notgelandete Maschine**, nicht ein Boot —
ein Fliegerverein sucht Flieger. Daraus folgen drei Vorgaben, die nicht kosmetisch sind:

* **Vorgabe-Art ist `flugzeug_echo`** (kleines Flugzeug am Boden). `wilga` ist die
  dramatischere Wahl: das ist die Vereinsmaschine **D-EFRS**, und sie zu suchen erklärt sich
  ohne ein Wort. Ebenso möglich: `flugzeug_ga`, `hubschrauber`, `segelflugzeug`.
* **Der Haken heißt „Landung zur Rettung nötig" und ist standardmäßig AN.** Eine abgestürzte
  Maschine liegt meist an Land, und dann muss zum Aufnehmen jemand **dort** landen — nicht auf
  dem nächsten Platz, sondern an der Unglücksstelle. Ist er aus, genügt ein Schwebeflug.

  ⚠ **Der Haken ist die REGEL, nicht das Gelände** — und das ist der Kern. Ein Zwischenentwurf
  nannte ihn `im_wasser`, weil der Admin die Tatsache ja sieht. Das hat einen Fall weggenommen:
  **Ein Wrack am Waldrand liegt an Land und ist trotzdem nicht landbar**, und dort ist die
  Rettung per Winde über dem Schwebeflug genau richtig. Umgekehrt genauso — ein Wrack im Wasser
  *mit* verlangter Landung ist ein Wasserflugzeug-Abend. Beides ist mit der Regel sagbar, mit
  dem Gelände nicht:

  | Wo der Havarist liegt | Haken | Wie gerettet wird | Wer kann es |
  |---|---|---|---|
  | an Land, landbar | **an** | Landung am Wrack, Vollstopp | jeder |
  | an Land, nicht landbar (Wald, Hang) | **aus** | Schwebeflug darüber | Hubschrauber |
  | im Wasser | **aus** | Schwebeflug oder Wasserung | Hubschrauber, Wasserflugzeug |
  | im Wasser, absichtlich streng | **an** | Wasserung mit Vollstopp | nur Wasserflugzeug |

  ⚠ **Und die Regel wird NICHT aus der Art abgeleitet.** Das lag nahe („Bootsart ⇒ keine
  Landung") und ist falsch: Ein im Wasser notgelandetes Flugzeug bleibt ein Flugzeug, und wer
  die Art wechselt, um das Objekt hübscher zu machen, würde sonst versehentlich die Wertung
  kippen. Die Art ist ein eigenes Feld.
* **Das Objekt steht auf dem Boden** (OnGround, wie seit 15.6.1 bei den Booten), mit dem
  `boden_versatz_ft` seiner Art — bei `flugzeug_echo` 3,9 ft.

**Die Simulatorlücke, die bei Booten ein Problem war, gibt es bei Flugzeugen nicht:**
`flugzeug_echo` (5/185/2 aktive Titel), `flugzeug_ga` (1/70/3), `hubschrauber` (1/41/4) und
`wilga` (1/1/1) sind in MSFS 2020, MSFS 2024 **und** X-Plane 12 aktiv. Die Auflösung der Art je
Simulator bleibt trotzdem im Entwurf — sie kostet fast nichts und trägt die Sonderfälle
(`segelflugzeug` fehlt in MSFS 2020, `flugzeug_klassik` in X-Plane, alle Bootsarten irgendwo).

## 3. Die Wertung gehört der Gruppe

Zwei Zahlen nebeneinander, wie beim FriesenKutter:

* **Gruppenabdeckung** — Anteil der abgesuchten Zellen am Sektor. Das ist der Balken.
* **Beitrag je Pilot** — die Zellen, die er als **erster** abgesucht hat. Doppelarbeit bringt
  niemandem etwas, die Aufteilung entsteht dadurch von selbst.

Dazu die Namen und Zeiten der Latches — **einer bis drei, je nach Zuschnitt des Abends**
(endet er mit dem Fund, gibt es nur den einen). Ein Wettlauf um den Fund bleibt daneben möglich,
aber niemand geht leer aus, der eine Fläche abgeflogen und nichts gefunden hat.

## 4. Die Zahlen — und warum sie aneinander hängen

**Suchen und Finden sind zwei Fenster.** Das ist die wichtigste Zahl-Entscheidung des Entwurfs
und hat drei Fassungen gebraucht (s. unten).

| | seitlich | Höhe (AGL über dem Havaristen) | bedeutet |
|---|---|---|---|
| **Suchen** | `korridor_km` **1,0 km** | `hoehe_max_ft` **2.000 ft** | „Fläche abgeflogen" — was der Balken zählt |
| **Finden** | `fund_radius_m` **150 m** | `fund_hoehe_ft` **1.000 ft** | die Rauchfackel — der echte Fund |

**Seitliche Abstände stehen in Metern, Höhen in Fuß** — die Sprache der Sache: In der Luft
rechnet man Höhen in Fuß, am Boden Entfernungen in Metern.

Dazu, für beide gleich: **30–140 kt** (die Untergrenze, damit ein geparktes Flugzeug nicht seine
Zelle abdeckt), `kante_km` **1,0 km** (Feinheit der Buchhaltung, nie größer als der Korridor),
und fürs Aufnehmen die Landeregeln des Projekts (`< 2 kt` mit Landung, `< 30 kt` im Schwebeflug,
je unter `< 300 ft` AGL).

**Die Sektorgröße ist KEINE Vorgabe** — sie ergibt sich aus den zwei geklickten Ecken. 40 × 40 km
ist eine *Empfehlung* (simuliert: 4–6 Piloten suchen das bei 1-km-Korridor in rund einer halben
Stunde ab); der Admin sieht die gerechnete Größe und Suchdauer, während er zieht.

### „Abgesucht" heißt nicht „hätten wir ihn gesehen" — und das ist Absicht

Bei zwei Fenstern kann ein Sektor vollständig abgeflogen sein, ohne dass jemand den Havaristen
gesehen hat. **Das ist kein Mangel, sondern die Folge davon, dass zu jedem Event eine Geschichte
gehört** („über der Sandbank bei Spiekeroog weggeblieben"). Die Geschichte grenzt das Gebiet ein;
niemand sucht blind 1.600 km² ab. Genau deshalb muss der Admin die Lage kennen — **er erfindet
sie.** (Und genau deshalb war das Würfeln nicht nur unnötig, sondern hätte geschadet.)

**Drei verworfene Fassungen, damit keine wiederkommt:**

1. **Fundradius gerechnet** aus `korridor + kante/√2` (bei 1/1 km: 1,71 km), damit volle
   Abdeckung den Fund garantiert. Die Garantie war schön und die Zahl falsch: **Eine Cessna 172
   sieht niemand aus 1,7 km.**
2. **Schrägabstand** — Höhe und Seitenabstand in einem, also eine Kugel. Verworfen, weil er Höhe
   bestraft, obwohl man von oben weiter sieht: Bei 1.000 ft Radius und 1.000 ft Flughöhe bliebe
   null Spielraum zur Seite.
3. **Eine Zahl für beides** (Korridor = Fundradius, 300 m). Konsistent, aber dann ist ein
   40-km-Sektor 26 Flugstunden — oder der Fund eine Farce.

### Die Höhenschranke ist AGL über dem Havaristen

**Nicht MSL.** Ein erster Entwurf nahm `position_history.altitude` (MSL) und rechtfertigte das
mit „über dem Wattenmeer ist die Geländehöhe ~0". **Der Sektor ist aber nicht aufs Watt
beschränkt** — er darf überall liegen, und bei Flugzeugen wird er meist über Land liegen. Nötig
ist die Annahme ohnehin nicht, **denn der Server kennt die Höhe des Havaristen.**

Die FriesenBrügge meldet für jedes gesetzte Objekt zurück, auf welcher Höhe es tatsächlich
gelandet ist (`bruegge_steht.hoehe_ft`, PROTOKOLL Abschnitt 1). In der Produktion stehen drei
Objekte bei Wangerooge mit 8,8 ft (MSFS 2020) und 7,9 ft (MSFS 2024) — eine echte Messung des
Geländes an genau dieser Koordinate, aus zwei Simulatoren mit einem Fuß Unterschied.

Gewertet wird deshalb `Höhe des Piloten (MSL) − Grundhöhe des Havaristen`. Das ist **AGL über
dem Wrack**, nicht AGL unter dem Flugzeug — und genau das ist die richtige Bezugsgröße für die
Frage „ist er tief über der Unglücksstelle hinweggeflogen?".

`havarist_grund_ft` wird in dieser Reihenfolge belegt:

1. **Gemessen** — die erste brauchbare Rückmeldung einer Brügge (`zustand = "steht"`).
2. **Vom Admin eingetragen** — er setzt den Punkt ja von Hand und sieht die Karte.
3. **Höhe des nächsten Platzes** (`geo.airport_elevation_ft`), sonst 0.

⚠ **Zwei Vorbehalte aus dem Protokoll, beide sind Fallstricke und keine Randfälle:**

* **`hoehe_gemessen: false`** — die X-Plane-Brügge probt das Gelände selbst
  (`XPLMProbeTerrainXYZ`), und nur geladenes Gelände antwortet. Steht das Ziel außerhalb,
  bekommt das Objekt Meereshöhe, und die Meldung sieht **genau aus wie ein Wattobjekt auf
  0,0 ft**. Solche Meldungen dürfen `havarist_grund_ft` nicht setzen. Die MSFS-Brügge sendet
  das Feld nicht — dort gibt es den Fall nicht.
* **Nur aus der Nähe.** Aus großer Entfernung antwortet der Simulator aus einer groben
  Geländestufe: am Bodensee gemessen 2.106 ft statt 1.297 ft, bei 691 km Abstand. Brauchbar
  belegt sind Werte bis 200 km, dazwischen ist eine Lücke. Für eine Reddung im Umkreis des
  Heimatplatzes ist das unkritisch, aber die Regel gehört in den Code, nicht in die Hoffnung.

### Aufnehmen benutzt die Landeregeln des Projekts

**Keine eigenen Schwellen.** Ist der Haken „Landung zur Rettung nötig" gesetzt, gilt, was im
Projekt eine Landung ist:

| Konstante in `app/gps_legs.py` | Wert | Bedeutung |
|---|---|---|
| `_GPS_BLOCK_GS_KT` | 2 kt | Vollstopp — der Touchdown-Kandidat |
| `_GPS_GROUND_AGL_FT` | 300 ft | AGL-Obergrenze für „am Boden" |

Beide werden **importiert, nicht abgeschrieben**: Ändert jemand später die Landeerkennung, zieht
die Reddung mit. Die AGL-Bezugsgröße ist die Grundhöhe des Havaristen (Abschnitt darüber).

⚠ **`detect_gps_legs` selbst lässt sich nicht benutzen, und das ist kein Mangel.** Die Funktion
verlangt für eine Landung einen **Platz im Umkreis** — im Code steht ausdrücklich „Kein Platz /
AGL-Guard verletzt → bleibt AIRBORNE (Absturz/Hover nie als Landung)". Die Außenlandung am Wrack
ist genau der Fall, den sie absichtlich nicht zählt, und diese Absicht ist richtig: sonst würde
jeder Absturz als Landung gewertet. Deshalb dieselben **Regeln** statt derselben Funktion.

**Ohne den Haken gilt `< 30 kt` statt `< 2 kt`** — ein Schwebeflug über der Unglücksstelle.
Damit verlangt diese Fassung praktisch **einen Hubschrauber**: Ein Flächenflugzeug kommt nicht
unter 30 kt, ohne zu landen. Ein Wasserflugzeug erfüllt die Bedingung ebenfalls, weil eine
Wasserung unter 2 kt endet. **Das muss im Admin dabeistehen**, sonst legt jemand ein Event an,
das nur Hubschrauberpiloten abschließen können, ohne es zu wissen.

⚠ **Bei 15 s Abtastung kann ein sehr kurzer Stopp durchfallen.** Eine Rettungslandung dauert
länger als einen Messabstand, der Fall ist also theoretisch — festgehalten, weil er beim
Sekundentakt der Brügge (spätere Ausbaustufe) von selbst verschwindet.

**Als Nebenertrag fällt eine Prüfung ab:** Weicht die gemessene Höhe deutlich von der
eingetragenen ab, ist die Stelle für diese Art untauglich (PROTOKOLL Abschnitt 4) — der Admin
bekommt dann einen Hinweis, bevor Piloten ausschwärmen.

**Die Zellkante gehört nie über den Korridor.** Eine abgedeckte Zelle heißt „ein Track lief im
Korridor an ihrem **Mittelpunkt** vorbei"; in der Zellecke sind es bis zu 0,71 · Kante mehr. Bei
Kante gleich Korridor ist das ein Drittel Spielraum, bei gröberer Kante wird der Balken
großzügig. Löcher entstehen dabei **nicht** — das stand hier zuerst falsch; jeder Mittelpunkt ist
überfliegbar.

**Und die Kante gehört nie über den Korridor.** Hier stand zuerst, eine zu große Kante lasse
„Löcher zwischen den Zellen, die niemand füllen kann" — das ist **falsch** (berichtigt am
20.09.2026, beim Erklären der beiden Werte aufgefallen). Löcher gibt es nicht: Jeder
Zellmittelpunkt ist überfliegbar, 100 % sind immer erreichbar. Was wirklich passiert, ist eine
grobe Buchhaltung — eine 6-km-Zelle gilt als komplett abgesucht, obwohl nur ein Streifen von
2 · Korridor durch ihre Mitte führte, und der gerechnete Fundradius wächst mit (bei 6 km Kante
auf 5,2 km). Das Versprechen bleibt eingehalten, aber der Abend wird beliebig leicht.
Umgekehrt ist feiner immer erlaubt und nur eine Frage der Rechenzeit.

1,71 km Sichtweite aus 1.000 ft ist dabei keine Nachgiebigkeit, sondern die Bedingung dafür, dass
Balken und Fund dasselbe versprechen. Auf ein Wrack im Gelände ist sie allerdings **optimistischer
als auf ein Boot auf offener See** — wer es strenger will, verkleinert Korridor und Zellkante
gemeinsam (0,6 km/0,6 km ergibt 1,02 km Fundradius) und nimmt die längere Suchzeit in Kauf. Das
Verhältnis bleibt dabei erhalten, weil der Fundradius gerechnet wird.

## 5. Verdeckung: wohin die Koordinate geht und wohin nicht

**An die FriesenBrügge: ja, ab Eventbeginn, ohne Abstandsprüfung.** Sie muss das Objekt
hinstellen. Ein Riegel „erst ab 15 km" war erwogen und **verworfen**: Der einzige Angriff wäre,
den eigenen Datenverkehr mitzulesen, und das ist in dieser Gruppe ein theoretisches Problem.

**An Website und Kniebrett: nie.** Deren Endpunkte liefern `gefunden: ja/nein, von wem, wann` und
das Zellraster mit `offen`/`abgedeckt` — Schlüssel, keine Orte. Das ist keine Anzeigefrage,
sondern eine Zusicherung des Datenmodells: `app/abdeckung.py` gibt nie eine Koordinate heraus
(ein Test hält das fest), und die Endpunkte dieser Runde tun es auch nicht.

Dass abgesuchte Zellen verraten, wo er **nicht** ist, ist kein Leck, sondern die Spielmechanik
aus #21: Wer eine Fläche absucht und nichts findet, verkleinert den Sektor für alle.

## 6. Datenmodell

Eine neue Tabelle, nach dem Muster von `bummel_races` und `transport_events`:

```sql
CREATE TABLE IF NOT EXISTS reddung_events (
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
    hoehe_max_ft    REAL DEFAULT 1000,      -- AGL UEBER DEM HAVARISTEN, nicht MSL
    gs_max_kt       REAL DEFAULT 140,
    gs_min_kt       REAL DEFAULT 30,
    -- Der Havarist. ⚠ Diese zwei Spalten verlassen den Server nur in Richtung FriesenBrügge.
    havarist_lat    REAL,
    havarist_lon    REAL,
    havarist_art    TEXT,                   -- Art aus bruegge_art; NULL = 'flugzeug_echo'
    havarist_grund_ft REAL,                 -- Geländehöhe MSL an der Unglücksstelle
    havarist_grund_quelle TEXT,             -- 'gemessen' | 'admin' | 'platz'
    aufnehmen_noetig INTEGER DEFAULT 1,     -- 0 = der Abend endet mit dem Fund
    landung_noetig  INTEGER DEFAULT 1,      -- 0 = Schwebeflug genügt (Winde, Wasserung)
    -- Latches
    gefunden_am     TEXT,  gefunden_von     INTEGER,
    aufgenommen_am  TEXT,  aufgenommen_von  INTEGER,
    aufnahme_verfaellt INTEGER DEFAULT 1,   -- 1 = verfällt, wenn der Aufnehmende abmeldet
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

**Keine Zellentabelle.** Das Raster entsteht bei jeder Rechnung aus `zellen_aus_box()`.

**Die Abdeckung wird FORTGESCHRIEBEN, nicht neu gerechnet.** Der Zustand — welche Zelle gehört
wem, bis wann gerechnet, ist der Havarist gefunden — liegt in `progress_snapshot` mit
`kind='reddung'`; jeder Aufruf ergänzt nur die neuen Punkte gegen die noch offenen Ziele. Das ist
erlaubt, weil `abdeckung()` die Segmente nach ihrem **Ende** sortiert verarbeitet: Ein Treffer von
vorhin kann durch einen späteren Punkt nie umgeworfen werden. Gemessen:

| | von vorn | fortgeschrieben |
|---|---|---|
| `compute_reddung_stand` | 129 ms **je Aufruf**, wachsend | 129 ms einmal, danach **4 ms** |
| `_check_reddung` je Takt | 139 ms, wachsend | **30 ms**, gleichbleibend |

⚠ **Zwei Fallstricke, beide mit eigenem Test und je einer roten Gegenprobe:**

* **Der letzte Punkt vor dem Schnitt gehört dazu.** Ein Segment besteht aus zwei Punkten; ohne
  den letzten Punkt des vorigen Takts fehlt genau das Stück über die Schnittkante, und es
  entstünde alle 60 Sekunden ein blinder Fleck, in dem ein Überflug verschwindet.
* **`_REDDUNG_STAND_FASSUNG` erhöhen, wenn sich die Rechnung ändert** — sonst bleibt ein Ergebnis
  stehen, das mit der neuen Rechnung nie entstanden wäre. Die Zahl steht **im Payload** und nicht
  in `_PROGRESS_SNAPSHOT_VERSION`: Die ist global und würde Bummel und Kutter mit entwerten.

**Und geladen wird nur die Gegend.** Die Abfragen filtern auf den Sektor plus 15 km Rand — wer
nicht dort fliegt, wird nicht geladen. Der Rand ist gerechnet, nicht geraten: Ein Segment ist
höchstens 6 km lang, also liegt bei einem sektornahen Segment ein Endpunkt innerhalb von
Korridor + 6 km und der andere innerhalb von Korridor + 12 km.

## 7. Wo die Prüfung läuft

Im Poller, im vorhandenen Takt (15 s) — ein Job `_check_reddung`, nach dem Muster von
`_check_bummel_reveals`. Er rechnet je laufender Reddung:

1. **Abdeckung** — `abdeckung(spuren, zellen_aus_box(...), fenster)`.
2. **Fund** — dieselbe Funktion, ein Ziel mit dem gerechneten Fundradius, dasselbe Fenster.
3. **Aufnehmen** — entfällt bei `aufnehmen_noetig = 0`; dann schließt der Fund den Abend ab.
   Sonst dasselbe Ziel, nur Spurenpunkte **nach** `gefunden_am`, mit
   `Fenster(hoehe_max_ft=_GPS_GROUND_AGL_FT, gs_max_kt=_GPS_BLOCK_GS_KT bzw. 30, gs_min_kt=0)`. Die
   Untergrenze muss dabei auf 0 — sonst schlösse das Suchfenster (30 kt) den Stillstand aus,
   der hier gerade gefragt ist.
4. **Einliefern** — entfällt ebenso; sonst die Landung des Aufnehmenden aus
   `canonicalize_legs`, erster Zielpunkt nach `aufgenommen_am`.

Jede Stufe setzt ihren Latch über eine Funktion, die nur beim ersten Mal schreibt (Muster
`_set_transport_latch`) und dabei die Fackel tauscht. Push je Stufe, wenn `push_enabled`.

**Der Sekundentakt der Brügge bleibt in dieser Runde außen vor.** Er wäre genauer (1 Hz, echte
AGL) und `abstand_zu_strecke_km` kostet eine Mikrosekunde — aber `bruegge_positions` hält nur die
letzte Zeile je Pilot, und Issue #42 (438 × HTTP 500 auf `/api/bruegge/melden`) sagt, dass dieser
Pfad kein guter Ort für neue Arbeit ist, solange er nicht verstanden ist.

## 8. Was der Admin bedient

Ein Bereich wie bei Bummel und Kutter: Sektor durch zwei Ecken auf der Karte, Zellkante,
Korridor, Höhen- und Geschwindigkeitsfenster, Art des Havaristen, Haken „Havarist liegt im
Wasser", Kalendertermin, Push. Dazu:

* **„Aufnehmen nötig" sperrt den Haken darunter**, wenn er aus ist — sonst stellt jemand eine
  Landung ein, die nie geprüft wird, und wundert sich.
* **Neben dem Haken steht, was er bedeutet.** Gesetzt: *„Aufnehmen verlangt eine Landung an der
  Unglücksstelle (Vollstopp unter 300 ft AGL) — sieh nach, ob dort jemand landen kann."* Nicht
  gesetzt: *„Aufnehmen per Schwebeflug, unter 30 kt über der Unglücksstelle. Das verlangt einen
  Hubschrauber oder ein Wasserflugzeug."*

* **Die Lage des Havaristen setzt der Admin von Hand** auf die Karte — das ist die Vorgabe. Sie
  ist dort auch sichtbar, denn wer das Event anlegt, weiß es ohnehin.

  Ein Land-Wasser-Modell haben wir nicht: Ob dort Wasser liegt, entscheidet das Auge des
  Veranstalters — deshalb der Haken daneben. Und über die Entfernung zum Platz bestimmt er
  gleich mit, wie lang der Abend wird.

  ⚠ **Ein Wrack an Land verlangt eine Außenlandung, und die ist nicht überall möglich.** Eine
  Zusatzregel („der nächste Platz zählt auch") ist ausdrücklich **nicht** vorgesehen — das wäre
  keine Rettung mehr. Wo gelandet werden kann, beurteilt der Admin beim Setzen des Punktes; ein
  Wrack mitten im Wald macht den Abend unlösbar, und das sieht er dort.

* **Ein Zufallspunkt ist ausdrücklich NICHT vorgesehen.** Die Idee stand im Entwurf und ist
  verworfen: Sie hatte genau einen Zweck — dass der Veranstalter selbst mitsuchen kann, ohne die
  Lage zu kennen — und kostete dafür eine Tabelle mit geprüften Kandidatenstellen, ein
  Verdeckungsfeld und drei Sonderregeln. **Der Admin setzt den Ort und kennt ihn dann eben.**

  Den freien Würfel über den Sektor gibt es auch deshalb nicht, weil er die falsche Frage
  beantwortet hätte: Gefragt ist nicht „ist dort Wasser?", sondern „kann dort jemand landen?" —
  und ein Zufallspunkt trifft Wald, Dorf, Hang, Baggersee oder Autobahn. Das beurteilt ein
  Mensch beim Klick auf die Karte in einer Sekunde, und keine Landmaske kann es ihm abnehmen.

* **Die erwartete Suchdauer** als Hinweis neben der Sektorgröße, aus Kantenlänge, Korridor und
  angenommenen 110 kt — sonst setzt niemand einen Sektor, der zur Abendlänge passt.
* **Sektor und Havarist werden auf einer Karte geklickt**, nicht getippt — Luftbild, weil man
  sehen muss, was an der Stelle liegt. Ein Klick setzt das gewählte Ziel und schaltet dann von
  selbst weiter: **Ecke 1 → Ecke 2 → Havarist**. Vorbild ist das Einfassen der Flugplatzkarten
  (`_dfsKarteAufbauen` in `admin.html`). Welche Ecke zuerst kam, sortiert die Oberfläche selbst
  in Süd/Nord/West/Ost — sonst legte ein verdrehtes Rechteck ein leeres Raster an.
* ⚠ **Hinweistexte stehen nie in einer Gitterzelle neben einem Feld.** Ein langer Text macht
  seine Zelle hoch, das Nachbarfeld bleibt oben, und die Eingabefelder rutschen gegeneinander
  aus der Zeile. Sie gehören über die volle Breite unter die Zeile, zu der sie sprechen — zwei
  Tests im Projekt halten das fest.

## 9. Abhängigkeiten

* **Die Fackeln laufen in allen drei Simulatoren** — geprüft und aktiviert.
  `FrsRauch_Signalorange` und `FrsRauch_Hellblau` sind eigene Objekte der FriesenBrügge, die sie
  selbst kennt (`friesenbruegge/msfs/bruegge.cpp`); dass im Katalog keine `msfs2020`-Zeile
  steht, steuert hier nichts. **Keine Abhängigkeit.**
* **Für den Normalfall keine Abhängigkeit:** Die vier Flugzeugarten sind in allen drei
  Simulatoren aktiv (s. Abschnitt 2). Nur die Sonderfälle brauchen die Auflösung je Simulator —
  **keine Bootsart** ist überall aktiv (`boot_klein`/`boot_gross` fehlen in MSFS 2024,
  `schiff_segel`/`schnellboot` in MSFS 2020), `segelflugzeug` fehlt in MSFS 2020,
  `flugzeug_klassik` in X-Plane.

## 10. Was der erste Abend gezeigt hat (20.09.2026)

Die erste Reddung lief noch am selben Abend. Fünf Funde, alle behoben:

1. ⚠ **Der Havarist stand als Verkehrspunkt auf dem Kniebrett** — und damit die Lage, die der
   ganze Eventtyp verbirgt. Die Brügge stellt ein Flugzeug-SimObject hin, `GET_AIR_TRAFFIC`
   liefert es wie jeden anderen Verkehr, und das Kniebrett zeichnete alles. Der Filter braucht
   die geheime Lage nicht: **Ein stehendes Sim-Objekt ohne VATSIM-Partner ist kein Verkehr.**
   Das trifft geparkte KI genauso, und das ist richtig.
2. ⚠ **In LittleNavMap ist er weiterhin zu sehen, und daran lässt sich nichts ändern.** LNM
   liest SimConnect direkt; wer ein AI-Objekt in den Simulator stellt, stellt es für jedes
   Werkzeug dorthin. Wer das ausschließen will, darf kein Objekt setzen — dann sieht aber auch
   niemand etwas aus dem Fenster.
3. **Das Event tauchte in keiner Liste auf.** Es gibt jetzt `/api/reddung/events` (ohne
   Koordinate), und die Eventliste mischt es ein — mit dem Abdeckungsstand statt eines Platzes.
4. **Kein Bearbeiten und kein Link-Knopf** im Admin. Beides nachgezogen, nach dem Muster des
   Kutters.
5. **Die Einlieferung wurde erst nach Minuten bemerkt.** Sie hing an `canonicalize_legs`
   (VATSIM alle 15 s, Vollstopp in Platznähe) und am 60-s-Takt. Jetzt fragt der Poller
   **zuerst die Brügge** (`am_boden`, Sekundentakt) und fällt nur zurück, wenn der Pilot keine
   hat; der Takt steht auf 30 s.

## 11. Die FriesenBrügge trägt die Wertung, wo sie da ist

**Bis zum 20.09.2026 lief alles auf VATSIM** (`position_history`, alle 15 s, rund 950 m
Punktabstand) — die Brügge war nur für die Landung eingebaut. Das ist bei einem Fundradius von
150 m nicht bloß ungenau, sondern grenzwertig: Die Rechnung nimmt zwischen zwei Punkten eine
**Gerade** an, und bei einer Kurve dazwischen trägt diese Annahme die ganze Entscheidung falsch.

| | VATSIM | FriesenBrügge |
|---|---|---|
| Takt | 15 s | **1 s** |
| Punktabstand bei 110 kt | ~950 m | **~50 m** |
| Höhe | luftdruckabhängig | **echte MSL** |

Deshalb gibt es `bruegge_spur` — den Sekundenverlauf, **aber nur solange eine Reddung läuft und
der Pilot in ihrem Sektor ist** (plus Rand). 1 Hz je Pilot sind 3.600 Zeilen je Stunde; ohne
Abnehmer wäre das Müll, und `bruegge_aufraeumen` räumt es nach 12 Stunden weg.

⚠ **Gemischt wird je Pilot nach ZEITRAUM, nicht nach Punkt.** Für die Zeit, die die Brügge
abdeckt, gilt ausschließlich sie; davor und danach VATSIM. Punktweise zu mischen erzeugte an
jeder Naht einen Sprung zwischen zwei Höhenmessarten — und Höhen entscheiden hier über Treffer.

**Wer keine Brügge hat, wird trotzdem gewertet** — nur gröber. Das ist der Grund, warum der
Fund weiterhin am gerechneten Umkreis hängt und nicht daran, ob jemand das Objekt gesehen hat.

## 12. Der Havarist erscheint erst aus der Nähe

`bruegge_soll.nur_nah_m` — ein Objekt wird erst ausgeliefert, wenn der Pilot näher ist als der
Wert **und** nicht höher darüber (1.000 m, beides). Der Grund ist nicht die eigene Karte, die
filtert seit 15.13.0 selbst: **LittleNavMap liest SimConnect direkt** und zeigt ein gesetztes
Flugzeug als Flugzeug, egal was wir zeichnen. Von weitem stünde dort die Lage, die der ganze
Eventtyp verbirgt.

Der Riegel ist deshalb kein Geheimnis-Ersatz, sondern eine Entfernungsfrage: **Wer näher als
1.000 m ist und nicht höher, hätte das Wrack ohnehin gesehen.**

⚠ **Er gilt nur VOR dem Fund.** Danach ist die Lage öffentlich, und Wrack wie Fackel sollen von
weitem zu sehen sein — das ist der Sinn einer Rauchsäule.

⚠ **Ohne gemeldete Position kommt ein Nähe-Objekt gar nicht.** Lieber nichts ausliefern als eine
geheime Lage an einen Aufrufer, der seine Entfernung nicht kennt.

## 13. Offene Punkte

1. **Mehrere Havaristen je Event** — nicht in dieser Runde (#21, Frage 4). Das Datenmodell
   verträgt es später als eigene Tabelle; die Latches wandern dann dorthin.
2. **Gewertet wird vom Fund bis zur Landung.** #21 sagt „von der Meldung bis zur Landung", und
   das Aufnehmen liegt jetzt dazwischen. Die Zeit des Aufnehmens wird mitgeschrieben, damit sich
   die Wertung später ohne Datenverlust anders schneiden lässt.
3. **Woher die Grundhöhe kommt, wenn niemand sie meldet.** Die Messung setzt voraus, dass
   mindestens eine Brügge das Objekt gesetzt und zurückgemeldet hat. Fliegt an einem Abend
   niemand mit Brügge, bleibt der Admin-Wert oder die Platzhöhe. Der Rechenweg bleibt richtig;
   nur die Bezugszahl ist dann geschätzt — und weil der Sektor über Land liegen darf, kann sie
   dort um mehr als die 1.000 ft der Höhenschranke danebenliegen. Deshalb gehört
   `havarist_grund_quelle` im Admin sichtbar neben die Zahl.
4. **Wie oft ein Abbruch wirklich vorkommt, ist nicht gemessen.** Die Schonfrist von zehn
   Minuten ist geschätzt, nicht belegt — sie lässt sich nach dem ersten Abend gegen
   `position_history` prüfen (wie lange sind Aussetzer der eigenen Piloten wirklich?) und dann
   begründet setzen.
