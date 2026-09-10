# 🔭 FriesenKieker — Objekte aus der Luft zählen · Design

**Datum:** 2026-09-11 · **Status:** Entwurf, noch nicht abgenommen · **Vorlauf:** Brainstorming
10.09.2026, GitHub-Issue #20 · **Verwandt:** #21 (Suchflug), #22 (Deichkontrolle)

> **Diese Spec ist in Abwesenheit des Nutzers entstanden.** Alle Entscheidungen darin sind
> *Vorschläge mit Begründung*, keine Abnahmen. Was ich nicht selbst entscheiden konnte, steht
> gesammelt in Abschnitt 18.
>
> Sie ist einmal adversarisch gegengeprüft worden (Fable, 11.09.2026). Die Funde stehen an
> Ort und Stelle als **Fable-Fund** — sie haben die Wertung, die Geometrie, das Datenmodell
> und den Betriebsteil erheblich verändert. Abschnitt 17 fasst zusammen, was sich geändert hat.

---

## 1. Ziel

Ein dritter Eventtyp neben 🏁 **FriesenBummel** und 🦐 **FriesenKutter**: Die Gruppe fliegt
eine Liste von Stellen ab, sieht hin und zählt, was dort liegt. Gewertet wird, wer der
Wahrheit am nächsten kommt — **aber nur an den Stellen, die er auch wirklich überflogen hat.**

Der Typ heißt nach dem Hinsehen, nicht nach dem Gezählten: „Kieker" ist auf Platt das Fernglas
und zugleich der, der guckt. Gezählt werden kann alles — Boote in der Deutschen Bucht, Robben
auf den Sandbänken, Elche in Norwegen. Die Objektart ist ein Feld, keine Programmvariante.

## 2. Der Zuschnitt, der diese Spec umsetzbar macht

Im Brainstorming standen der Eventtyp und das MSFS-Paket, das die Objekte setzt, als **ein**
Vorhaben. So ist es nicht baubar: Das Paket hängt an vier Messfragen, die nur am Simulator zu
beantworten sind (Abschnitt 14), und solange sie offen sind, wird auch der Server nicht fertig.

**Der Ausweg:** Es gibt Objekte, die ohne jedes Addon in bekannter Zahl im Simulator stehen —
fest gebaute Szenerie. Windräder, Schiffe an einer Pier, Silos. Wer sie zählen lässt, braucht
kein Addon, keine Verteilung, kein SimConnect; die Wahrheit trägt der Admin ein.

| Stufe | Was sie bringt | Was sie braucht | Risiko |
|---|---|---|---|
| **1 — Der Eventtyp** | spielbarer Kieker auf fest gebaute Szenerie | nur Server + Oberfläche | **Wahrheit oft nachschlagbar, Szenerie ist addon-abhängig** (s. u.) |
| **2 — Das Paket** | frei gesetzte Objekte, Lage vom Server, je Pilot verschieden | `msfs-kieker/`, SimConnect | vier offene Messfragen |
| **3 — Politur** | Badge fürs Forum, eigene Robben-Modelle | Stufe 2 muss stehen | Modellierung, Lizenzfragen |

**Fable-Fund (KRITISCH), hier stand vorher „Risiko: keins, alles bekannt" — das war falsch,
gleich doppelt:**

1. **Die Wahrheit ist bei fest gebauter Szenerie oft öffentlich.** Riffgat hat 30 Anlagen,
   Alpha Ventus 12, Nordergründe 18 — das steht bei Wikipedia. Wer die Stellen überfliegt und
   die Zahlen abschreibt, hat Fehler 0. Bei `wertungspunkte = N` teilen sich dann **alle**,
   die N Stellen abgeflogen haben, den ersten Platz; das Event verliert als Wettbewerb jede
   Trennschärfe. (Daher der Gleichstands-Bruch in Abschnitt 3.5 — und Frage 6.)
2. **„In jedem Simulator dieselbe Zahl" ist unbelegt.** Ob ein Pilot mit Addon-Szenerie,
   einer auf MSFS 2020 und einer auf MSFS 2024 dieselben Objekte sehen, hängt von deren
   Installation ab. Weder Fable noch ich konnten das prüfen. **Die Objektart für das erste
   Event ist deshalb so zu wählen, dass sie in der Grundszenerie steht** — und es gehört
   ausprobiert, bevor gewertet wird.

Beides macht Stufe 1 nicht wertlos: Sie prüft die gesamte Mechanik unter echten Bedingungen,
bevor irgendwer ein Addon installiert. Es macht sie nur zu etwas, das man ansagen muss.

## 3. Die Wertung

### 3.1 Zwei Fragen, nicht eine

Issue #20 stellte „Zählen oder Fliegen?" als Alternative dar. Das ist falsch herum: Ohne
Flugprüfung ist der Kieker ein Ratespiel, das man vom Sofa aus gewinnt. Die Abdeckung ist
nicht die zweite Wertung, sie ist die **Zulassung**.

- **Abdeckung (A)** — je Stelle: im Korridor überflogen? Ja/Nein.
- **Schätzung (B)** — je Stelle: eingetragene Zahl, bewertet am Abstand zur Wahrheit.

**Eine Stelle wird nur gewertet, wenn sie abgedeckt ist.** Eine Schätzung ohne Überflug zählt
nicht — und das steht im Ergebnis als `abgedeckt: false` daneben, damit niemand denkt, der
Server habe seine Zahl verschluckt.

Das ist die Grammatik, die der Bummel schon hat (`complete`/`incomplete` mit
`visited`/`missing`). Keine neue Denkfigur, nur eine neue Füllung.

### 3.2 Die Formel

Je Stelle *p*:

```
fehler_p = min(1.0, |schätzung_p − wahrheit_p| / max(wahrheit_p, 1))   wenn abgedeckt UND eingetragen
fehler_p = 1.0                                                          sonst
```

Gemittelt wird über die **Wertungsmenge**: standardmäßig alle Stellen der Liste, bei gesetztem
`wertungspunkte = N` die *N* mit dem kleinsten Fehler (Abschnitt 3.3).

```
güte = (1 − Ø fehler über die Wertungsmenge) × 100
```

Vier Eigenschaften, um derentwillen die Formel so aussieht:

- **Relativ, nicht absolut.** Zehn daneben ist bei 200 Robben nichts und bei 5 Booten alles.
- **Bei 1,0 gedeckelt.** Ohne Deckel wäre ein wilder Fehlgriff (5 wahr, 100 geraten → Fehler
  19) schlimmer als gar nicht hinzufliegen — man käme durch **Nichtstun** nach vorn. Mit
  Deckel ist Raten höchstens so teuer wie Nichtantreten: nie bestraft, nie belohnt.
- **`max(wahrheit, 1)`** erlaubt eine Stelle mit **null** Objekten — eine Falle.
- **Eine nicht abgedeckte Stelle bleibt in der Wertungsmenge** (Fehler 1,0), sie fällt nicht
  heraus. Sonst schlüge der, der eine Stelle anfliegt und trifft, jeden, der vierzehn mit
  kleinen Fehlern abarbeitet.

**Leer ist nicht null (Fable-Fund, WICHTIG).** Bei `wahrheit ≥ 1` ergeben „0 eingetragen" und
„nichts eingetragen" denselben Fehler 1,0; bei `wahrheit = 0` ist eine eingetragene 0 dagegen
perfekt. Blind überall 0 einzutragen ist damit **schwach dominant** — nie schlechter als
nichts, an der Falle besser. Als Strategie ist das wertlos (wer überall 0 schreibt, hat an
allen echten Stellen Fehler 1,0 und landet bei ~17 % statt ~90 %), aber es hat eine scharfe
Kante in der Oberfläche:

> **Das Eingabefeld startet leer und wird nie mit 0 vorbelegt.** Ein Feld mit Vorgabewert 0
> und „Speichern je Zeile, sofort" (Abschnitt 9.1) würde für jeden Piloten ungefragt an jeder
> Stelle eine 0 eintragen und die Falle ihres Sinns berauben. Leer und 0 sind zwei Zustände,
> und `NULL ≠ 0` gilt bis in die Tabelle.

### 3.3 Nicht jede Stelle muss zählen

`wertungspunkte` am Event — „es zählen die *N* besten Stellen" (leer = alle).

Der Admin kann vierzehn Kolonien auslegen und sagen: „sechs reichen." Jede weitere geflogene
Stelle kann das Ergebnis dann nur verbessern. Die Anzeige listet trotzdem **alle** Stellen mit
Einzelergebnis und markiert die gewerteten.

**Auswahl bei Gleichstand deterministisch (Fable-Fund, KLEIN):** Haben mehr als *N* Stellen
denselben Fehler — der Regelfall bei mehreren nicht abgedeckten Stellen mit je 1,0 —, wird
nach `(fehler, position)` sortiert. Sonst hinge die Markierung „gewertet" von der
Zeilenreihenfolge der Datenbank ab und wechselte zwischen zwei Aufrufen.

### 3.4 `wertungspunkte` und Deckel spielen zusammen — nachgerechnet

Fable hat auf Pathologien geprüft. Ein Beispiel, das anfangs falsch aussah:

| Pilot | abgedeckt | Fehler je Stelle | beste 6 | Güte |
|---|---|---|---|---|
| A | 6 von 14 | je 0,9 | 0,9 × 6 | **10 %** |
| B | 3 von 14 | je 0,1 | 0,1×3 + 1,0×3 | **45 %** |

B gewinnt, obwohl er nur halb so viele Stellen geflogen ist. **Das ist gewollt:** Der Kieker
wertet Genauigkeit, nicht Fleiß — wer schlecht zählt, soll nicht durch Menge gewinnen. Wer
Fleiß belohnen will, setzt `wertungspunkte` nicht.

### 3.5 Rang

Absteigend nach Güte. Kein Zeitkriterium — der Kieker ist kein Rennen, wer langsam und tief
fliegt, zählt besser.

**Gleichstand wird gebrochen (Fable-Fund, KRITISCH — vorher: geteilter Rang).** Bei
nachschlagbarer Wahrheit (Abschnitt 2) treffen mehrere Piloten exakt; ohne Bruch teilen sich
alle Rang 1 und es gibt keinen Sieger. Reihenfolge:

1. Güte, **auf eine Nachkommastelle gerundet**, absteigend
2. Zahl abgedeckter Stellen, absteigend
3. Summe der absoluten Abweichungen `Σ |schätzung − wahrheit|`, aufsteigend
4. bleibt es gleich: geteilter Rang

**Warum gerundet (Fable-Fund, WICHTIG):** Die Güte ist eine Summe von Fließkommazahlen, und
die Summe hängt von der Reihenfolge ab. Fable hat 20.000 Zufallsfälle mit ganzzahligen
Schätzungen gerechnet — in **12.192** davon lieferte dieselbe Fehlermenge in anderer
Reihenfolge eine andere Summe (`0.1+0.2+0.3 = 0.6000000000000001`, `0.3+0.2+0.1 = 0.6`). Zwei
gleich gute Piloten bekämen verschiedene Ränge, und ein Test mit identischen Eingaben bliebe
grün. Die Rundung auf die *angezeigte* Stelle beseitigt das. (`fractions.Fraction` wäre exakt,
aber die Anzeige rundet ohnehin — dann soll die Wertung nach derselben Zahl gehen, die
dasteht.)

## 4. Die Deckungsprüfung

### 4.1 Gegen Strecken, nicht gegen Stichproben

Der Feed liefert alle ~15 s einen Punkt. Bei 140 kt liegen dazwischen **1,08 km**. Eine Stelle
mit 500 m Radius kann ein Pilot damit **sauber überspringen**, ohne dass eine Stichprobe
hineinfällt — mitten drüber geflogen, nichts abgedeckt.

**Faktisch ist die Abtastung noch gröber (Fable-Fund, KLEIN, nachgemessen):** 33,1 % aller
aufeinanderfolgenden Zeilen einer CID sind exakte Wiederholungen (gleiche Lat/Lon/Höhe) —
6.839 von 20.683 Paaren der letzten Woche. Der Abstand zwischen zwei *echten* Punkten liegt
also oft bei 30 s und über 2 km.

**Deshalb wird gegen die Verbindungsstrecken geprüft, nicht gegen die Stichproben.** Der Test
wird damit unabhängig von Abtastdichte und Geschwindigkeit. Das ist zugleich die Antwort auf
die Sequenzierungs-Warnung aus #22: Eine **Streckenabdeckung** braucht dieselbe Geometrie
(Abstand Punkt ↔ Strecke), nur andersherum gelesen.

### 4.2 Der Korridor

| Kriterium | Feld | Vorschlag |
|---|---|---|
| seitlicher Abstand | `radius_km` je Stelle, Rückfall aufs Event | **1,0 km** |
| Höhe | `max_alt_ft` je Stelle, Rückfall aufs Event | **2000 ft** |

**Geschwindigkeit ist bewusst KEIN Kriterium.** Sie soll erzwingen, dass jemand hinsieht — das
tut die Schätzung von selbst: Wer mit 200 kt vorbeirauscht, zählt schlecht und verliert. Eine
Geschwindigkeitsgrenze fügt nichts hinzu und schließt Muster aus, die nicht langsamer können.

**Die Höhe ist MSL, nicht AGL** — eine Entscheidung, keine Nachlässigkeit. Eine AGL-Rechnung
bräuchte ein Geländemodell, das FriesenSpy nicht hat und für ein Feature dieser Größe nicht
bekommen sollte. Über dem Wattenmeer ist der Unterschied null, über norwegischen Bergen groß —
dort setzt der Admin die Grenze höher. Das Feld heißt `max_alt_ft` und **nicht** `max_agl_ft`,
damit niemand später etwas anderes hineinliest.

⚠ **Warum trotzdem großzügige 2000 ft:** `app/vatsim.py:72` dokumentiert das Feld nur als
„Flughöhe in Fuß". **Ob der Feed die barometrische oder die wahre Höhe meldet, ist hier nicht
belegt** — ich hatte es als Tatsache geschrieben, Fable hat es zu Recht als unbelegt markiert.
Solange das offen ist, ist ein enger Deckel eine Falle: Bei 500 ft scheiterte ein Pilot
möglicherweise an seinem Höhenmesser statt an seinem Flug. 2000 ft trennt zuverlässig „tief
drüber" von „im Reiseflug zufällig darüber hinweg", und mehr soll der Wert nicht.

### 4.3 Wann zwei Stichproben eine Strecke bilden

Hier stand zuerst eine reine 90-Sekunden-Regel. **Fable hat sie an den Produktionsdaten
widerlegt (Fund WICHTIG):** In 14 Tagen gab es 42 Lücken über 90 s, davon **keine** über
600 s — und die Werte häufen sich (103 s ×9, 143 s ×9, 152 s ×9, 196 s ×5), jeweils bei
mehreren CIDs gleichzeitig. Das sind keine Reconnects, das sind **langsame Poll-Zyklen**, die
alle Piloten zugleich treffen (Issue #16). Eine 90-s-Regel hätte also ausgerechnet an einem
Kieker-Abend mit 15 Piloten Abdeckungen verworfen, die der Pilot sich verdient hatte.

Drei Schranken statt einer, jede mit eigenem Zweck:

| Schranke | Wert | wogegen |
|---|---|---|
| Zeitabstand | Δt ≤ **300 s** | Reconnect / Ausloggen; liegt komfortabel über den gemessenen 196 s |
| Streckenlänge | ≤ **10 km** | eine *gekrümmte* Bahn wird über eine lange Lücke zur Sehne begradigt und deckt ab, was nie überflogen wurde |
| implizite Geschwindigkeit | ≤ `max(gs_a, gs_b, 60 kt) × 1,5 + 50 kt` | Sprung innerhalb von 300 s |

Die Geschwindigkeitsschranke ist die einzige, die einen echten Reconnect zuverlässig fängt:
Norderney → München in einer Stunde ergibt 324 kt implizit — unter jeder festen Schwelle wie
600 kt, aber weit über `max(100, 100) × 1,5 + 50 = 200`. Ein fester Wert hätte genau den Fall
durchgelassen, um dessentwillen die Regel existiert.

Zwei weitere Regeln:

- **Aufeinanderfolgende Wiederholungen werden vorher zusammengefasst** (33 %, s. 4.1) — der
  Zeitstempel des *letzten* Punktes der Wiederholung zählt, damit Δt die echte Lücke misst.
  Ohne das erzeugt ein stehender Feed erst tausende entartete Strecken und dann eine gerade
  Linie über den Sprung, die die 300-s-Schranke nicht sieht.
- **Beide Endpunkte unter 30 kt Groundspeed → keine Strecke** (Fable-Fund, KLEIN). Sonst deckt
  ein am Platz abgestelltes Flugzeug eine Stelle ab, die zufällig 1 km entfernt liegt: Höhe ≈ 0
  ist unter jedem Deckel, und Stillstand ist kein Überflug.

### 4.4 Die Rechnung

Neu in `app/geo.py`:

```python
def punkt_zu_strecke_km(plat, plon, alat, alon, blat, blon) -> tuple[float, float]:
    """Kürzester Abstand (km) von P zur Strecke A→B, plus Lageparameter t ∈ [0,1].

    Der Fußpunkt wird in einer örtlich flachen Näherung bestimmt. **Die Längengrad-
    Differenzen MÜSSEN dabei mit cos(Breite) skaliert werden** — auf 53,7° N ist ein
    Längengrad nur 0,59 Breitengrade lang; ohne die Skalierung wandert der Fußpunkt auf
    schrägen Strecken weit ab. Der zurückgegebene ABSTAND wird mit :func:`haversine`
    gemessen, damit der Kieker denselben Maßstab benutzt wie der Rest des Projekts.
    Entartete Strecke (A == B) → Abstand zu A, t = 0.
    """
```

**Fable-Fund (WICHTIG):** Hier stand nur „örtlich flache Näherung", ohne die Skalierung zu
verlangen. Durchgerechnet: Strecke 1,08 km auf Kurs 045° bei 53,7° N, Stelle 0,95 km seitlich
der Mitte. Mit Skalierung t = 0,500 und Abstand 0,950 km (korrekt). Ohne: t = 0,923 und
**1,054 km** — bei Radius 1,0 km fiele die Stelle durch. Kein Test der ersten Fassung hätte es
gemerkt, weil alle Testfälle mittig lagen. Deshalb steht die Anforderung jetzt im Docstring
und der schräge Randfall in Abschnitt 15.

Ablauf je Event:

1. Positionen im Fenster laden:
   `SELECT cid, latitude, longitude, altitude, groundspeed, ts FROM position_history
    WHERE ts > ? AND ts <= ? ORDER BY cid, ts` — Index `idx_ph_ts`.
   **In `position_history` stehen ausschließlich Piloten mit dem `CALLSIGN_PREFIX`**
   (`app/poller.py:848`; nachgezählt: 169.835 Zeilen, 100 % `FRS`) — der Kieker gilt wie
   Bummel und Kutter nur für Friesen, ohne dass dafür gefiltert werden müsste.
2. Je CID Wiederholungen zusammenfassen, dann zu Strecken paaren, Schranken aus 4.3 anwenden.
3. Je Stelle Umgebungsrechteck über die Strecke (min/max der Endpunkte, um `radius_km`
   aufgeweitet) gegen das Rechteck der Stelle — schneidet es nicht, entfällt die teure
   Rechnung.
4. Sonst `punkt_zu_strecke_km`, Höhe am Fußpunkt interpolieren
   (`alt = alt_a + t·(alt_b − alt_a)`), beide Bedingungen prüfen.
5. Ein Treffer je (CID, Stelle) genügt.

### 4.5 Die Abdeckung wird **einmal** gerechnet und festgehalten

**Fable-Fund (WICHTIG) — der teuerste Fund des Reviews.** Die erste Fassung hatte keine
Abdeckungstabelle. Damit hätte **jeder** Lesezugriff die gesamte Positionsmenge neu gerechnet:
`_frozen_or_compute` rechnet ein aktives Event immer live (`app/main.py:3867`), und das
Live-Banner fragt beim Bummel-Vorbild alle 60 s je geöffnetem Client
(`app/static/index.html:14207`). Fünfzehn Piloten mit offener App an einem laufenden Abend
hätten fünfzehnmal je Minute dieselbe Rechnung ausgelöst. Genau dieses Muster hat beim Kutter
110-Sekunden-Läufe erzeugt und in v14.29.0 einen Umbau gekostet; die Spec hätte es
wiederholt und dabei „gutmütig" darüber geschrieben.

Deshalb:

```sql
CREATE TABLE IF NOT EXISTS kieker_abdeckung (
    event_id  INTEGER NOT NULL,
    stelle_id INTEGER NOT NULL,
    cid       INTEGER NOT NULL,
    erster_ts TEXT NOT NULL,          -- wann sie zuerst abgedeckt war (fuer started_at + Feed)
    PRIMARY KEY (event_id, stelle_id, cid)
);
```

- `kieker_events.abdeckung_bis` ist der **Fortschrittszeiger**: bis wohin gerechnet wurde.
- Der Job (Takt wie `_check_bummel_reveals`) liest nur `ts > abdeckung_bis`, zuzüglich je CID
  der letzten Position **bei oder vor** dem Zeiger — sonst ginge genau die Strecke über die
  Laufgrenze verloren.
- **Alle Lesepfade lesen nur noch diese Tabelle.** `/api/kieker/active`, die Event-Sicht und
  die eigene „4 von 14"-Anzeige rechnen nichts.
- `started_at` ist damit die früheste `erster_ts` — ohne eigene Rechnung.
- **Jede Änderung an den Stellen oder an den Korridor-Vorgaben löscht die Abdeckung dieses
  Events und setzt `abdeckung_bis` auf NULL** (Neurechnung beim nächsten Lauf). Sonst gälte
  eine Abdeckung, die mit einem anderen Radius entstanden ist.

**Größenordnung danach:** Ein Abend mit 15 Piloten × 4 h sind rund 14.000 Zeilen, nach dem
Zusammenfassen ~9.400 Strecken. Der Job rechnet je Lauf nur den letzten Takt (~60 neue
Strecken × 14 Stellen), die Lesepfade gar nichts.

## 5. Datenmodell

```sql
CREATE TABLE IF NOT EXISTS kieker_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT,
    objekt_art     TEXT,                 -- Anzeigewort: "Boote", "Robben", "Windräder"
    objekt_emoji   TEXT,                 -- das ZEICHEN, nicht der Dateiname (s. 9.3)
    dtstart        TEXT,
    dtend          TEXT,                 -- effektiv (Mitternacht-Default bereits angewandt)
    radius_km      REAL DEFAULT 1.0,     -- Vorgabe für Stellen ohne eigenen Wert
    max_alt_ft     REAL DEFAULT 2000,    -- dito; MSL, NICHT AGL (Abschnitt 4.2)
    wertungspunkte INTEGER,              -- NULL = alle Stellen zählen
    lage_modus     TEXT DEFAULT 'gemeinsam',   -- 'gemeinsam' | 'je_pilot' (Stufe 2)
    abdeckung_bis  TEXT,                 -- Fortschrittszeiger der Abdeckungsrechnung (4.5)
    source         TEXT,                 -- 'calendar' | 'manual'
    calendar_uid   TEXT UNIQUE,
    push_enabled   INTEGER DEFAULT 1,
    started_at     TEXT,
    revealed_at    TEXT,
    reveal_suppressed INTEGER DEFAULT 0,
    manual_fields  TEXT,                 -- #19
    badge_name     TEXT,                 -- Stufe 3
    created_at     TEXT
);

CREATE TABLE IF NOT EXISTS kieker_stellen (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     INTEGER NOT NULL REFERENCES kieker_events(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    name         TEXT NOT NULL,
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    radius_km    REAL,                   -- NULL = Vorgabe des Events
    max_alt_ft   REAL,                   -- NULL = Vorgabe des Events
    soll_anzahl  INTEGER                 -- DIE WAHRHEIT. Nie vor der Enthüllung ausliefern.
);
CREATE INDEX IF NOT EXISTS idx_kieker_stellen_event ON kieker_stellen(event_id);

CREATE TABLE IF NOT EXISTS kieker_schaetzungen (
    event_id   INTEGER NOT NULL REFERENCES kieker_events(id) ON DELETE CASCADE,
    stelle_id  INTEGER NOT NULL REFERENCES kieker_stellen(id) ON DELETE CASCADE,
    cid        INTEGER NOT NULL,
    anzahl     INTEGER NOT NULL,         -- NIE per Default 0 gefuellt (3.2)
    updated_at TEXT,
    PRIMARY KEY (event_id, stelle_id, cid)
);
```

`kieker_abdeckung` steht in Abschnitt 4.5.

**Fremdschlüssel sind hier benutzbar, anders als bei den Altbeständen (Fable-Fund, KLEIN):**
`PRAGMA foreign_keys=ON` ist aktiv (`app/database.py:878` und `1149`). `transport_cargo` trägt
`REFERENCES` nur als Kommentar und wird von Hand aufgeräumt (`delete_transport_event`,
`app/database.py:6294`) — das ist Altbestand, kein Vorbild. Neue Tabellen bekommen echtes
`ON DELETE CASCADE`. **Der Snapshot hängt nicht am Fremdschlüssel** und muss im
Lösch-Endpunkt weiterhin von Hand entfernt werden (`delete_progress_snapshot(conn, 'kieker', id)`),
genau wie beim Bummel (`app/main.py:3650`).

**Kein `icao`-Feld an der Stelle.** Im Szenerie-Repo steht es, steuert nichts (null Verweise im
Generator) und ist in vier von sieben Fällen falsch. FriesenSpy leitet den nächsten Platz bei
Bedarf über `geo.nearest_airport_icao` selbst her, und zwar richtig.

### 5.1 Die Stellenliste wird geändert, nicht ersetzt

**Fable-Fund (KRITISCH).** Die erste Fassung schrieb „ganze Liste ersetzen, wie
`set_transport_cargo`". Das ist beim Kutter harmlos, weil nichts auf `transport_cargo.id`
verweist — `transport_cargo_losses` hängt an `(event_id, cid, logon_time)`
(`app/database.py:267`). `set_transport_cargo` löscht aber alle Zeilen und fügt sie neu ein
(`app/database.py:6389`), und bei `INTEGER PRIMARY KEY AUTOINCREMENT` bekommen sie dabei
**neue IDs**.

Beim Kieker hängen `kieker_schaetzungen` und `kieker_abdeckung` an `stelle_id`. Ein während
des Abends korrigierter Tippfehler im Stellennamen hätte damit **jede eingetragene Zahl aller
Piloten in eine Waise verwandelt** — und mit `ON DELETE CASCADE` wären sie sogar sauber
gelöscht statt sichtbar kaputt.

Deshalb: `set_kieker_stellen` **upsertet über `id`** — bestehende Zeilen werden geändert, nur
neue eingefügt, nur weggefallene gelöscht. Der Test dazu heißt
`test_stelle_umbenennen_behaelt_schaetzungen` und ist ohne den Fix rot.

### 5.2 Die Wahrheit je Pilot (Stufe 2)

Für Stufe 2 kommt `kieker_lagen(event_id, stelle_id, cid, anzahl, objekte_json)` dazu.
Auflösung: *gibt es eine Zeile für (Event, Stelle, CID), gilt deren Zahl; sonst
`kieker_stellen.soll_anzahl`.* Genau **eine** Funktion darf das entscheiden
(`_wahrheit(conn, event, stelle, cid)`).

**Fable-Fund (WICHTIG):** Die erste Fassung führte `soll_anzahl` in der Antwort an der
**Stelle** — bei `lage_modus='je_pilot'` gibt es dort aber keine eine Wahrheit mehr, und die
Antwortform hätte umgebaut werden müssen. Genau der Umbau, den Abschnitt 2 vermeiden will.
Deshalb schon jetzt: **`soll_anzahl` steht in `teilnehmer[].stellen[]`** (bei „gemeinsam"
überall derselbe Wert) und zusätzlich an der Stelle **nur** bei `lage_modus='gemeinsam'`.
Oberfläche und `aggregate_kieker_kpis` lesen ausschließlich die Teilnehmer-Variante.

## 6. Identität — wer trägt eine Schätzung ein?

`_current_cid(request, settings)` (`app/main.py:2351`). **Das Kniebrett kommt über denselben
Weg**: Die Gerätebindung wird gegen `panel_devices` geprüft (`app/main.py:2549`) und setzt
danach dasselbe `USER_COOKIE` (`2560`). Eine Sonderbehandlung fürs Panel ist weder nötig noch
erlaubt — es gibt einen Identitätsweg, nicht zwei.

⚠ **Harte Abhängigkeit:** `_current_cid` gibt `None` zurück, solange das Board-Login
abgeschaltet ist (`app/main.py:2360`). **Ohne aktives Forum-SSO kann niemand eine Schätzung
eintragen, und der Kieker ist unspielbar.** Der Admin zeigt an einem Kieker-Event einen
Warnhinweis, wenn das Board-Login aus ist. Siehe Frage 4.

### 6.1 Der Schreibweg braucht einen Absenderschutz

**Fable-Fund (WICHTIG).** `USER_COOKIE` wird über HTTPS mit `SameSite=none` gesetzt
(`_iframe_samesite`, `app/main.py:2420-2426` — nötig, damit die Anmeldung im eingebetteten
EFB-Panel funktioniert). Ein fremdes Formular mit `enctype="text/plain"` schickt das Cookie
mit, und Starlettes `request.json()` prüft den Content-Type nicht. Eine fremde Seite könnte
also im Namen eines angemeldeten Piloten Schätzungen eintragen.

Die bestehenden `/api/me`-POSTs stehen ebenso da; hier ist erstmals ein **Wertungsergebnis**
betroffen. Deshalb an allen Cookie-authentifizierten Schreibwegen des Kiekers: **`Origin`
gegen die eigene Hostliste prüfen** und ohne passenden Ursprung mit 403 antworten. Test:
`test_form_post_ohne_origin_abgewiesen`. (Ob derselbe Schutz nachträglich für `/api/me` gilt,
ist eine eigene Entscheidung und nicht Teil dieser Spec.)

## 7. Verdeckung, Enthüllung, Einfrieren

### 7.1 Was wann sichtbar ist

| | vor der Enthüllung | nach der Enthüllung |
|---|---|---|
| Stellen (Name, Lage, Radius, Höhe) | **sichtbar** — man muss wissen, wohin | sichtbar |
| `soll_anzahl` (die Wahrheit) | **nie** | sichtbar |
| eigene Schätzung | nur für einen selbst | sichtbar |
| fremde Schätzungen | **nie** | sichtbar |
| Abdeckung anderer | nur als Zahl („4 Stellen") | vollständig |
| Güte, Rang, Fehler | **nie** | sichtbar |

**Die Wahrheit darf die Redaktionsfunktion nicht passieren, nicht einmal versehentlich.** Beim
Bummel ist die Verdeckung Höflichkeit — hier ist sie die Spielregel. `public_kieker_view(...)`
ist die **einzige** Stelle, die aus dem inneren Zustand ein Antwort-Dict macht, und ein Test
bindet daran: `soll_anzahl` darf im serialisierten JSON einer unenthüllten Sicht nicht
vorkommen — **rekursiv geprüft**, nicht am Vorhandensein eines Schlüssels auf oberster Ebene.
Das gilt auch für die Listen-Antwort `/api/kieker/events` und für Fehlermeldungen.

### 7.2 Eingabefenster

Schätzungen sind von `dtstart` bis `dtend` änderbar, danach gesperrt; der zuletzt gespeicherte
Wert zählt. Ausdrücklich **nicht** an die Enthüllung gebunden: Ein vom Admin zurückgehaltenes
Ergebnis darf das Eingabefenster nicht heimlich verlängern.

### 7.3 Enthüllung — erst, wenn es etwas zu enthüllen gibt

Der Bummel wartet vor der Enthüllung darauf, dass niemand mehr unterwegs ist, weil eine
Blockzeit erst nach dem Abstellen feststeht. Beim Kieker sind Abdeckung und Schätzung mit
`dtend` definitionsgemäß abgeschlossen — der ganze `bummel_wartestand`-Apparat entfällt.

**Aber die Wahrheit ist es nicht (Fable-Fund, WICHTIG).** Frage 5 sieht ausdrücklich vor, dass
der Admin selbst hinfliegt und zählt — er trägt `soll_anzahl` also womöglich **nach** `dtend`
ein. Die erste Fassung hätte bei `dtend` automatisch enthüllt, und der erste Client-Abruf
danach hätte das Ergebnis als Snapshot festgeschrieben (`app/main.py:3874`) — mit leeren
Wahrheiten.

Die Bedingung lautet deshalb:

```
now >= dtend  UND  reveal_suppressed = 0  UND  jede Stelle hat soll_anzahl IS NOT NULL
```

Fehlt eine Wahrheit, bleibt der Status **`wartet_auf_wahrheit`**, das Frontend sagt das auch
so, und der Admin sieht, an welchen Stellen es klemmt. Positionen nach `dtend` zählen nicht —
das ist zu dokumentieren, es ist die Vereinfachung, die den Wartestand erspart.

### 7.4 Snapshot

`progress_snapshot` mit `kind='kieker'` über `_frozen_or_compute` (`app/main.py:3856`).
Abgeschlossen heißt wie beim Bummel: `revealed_at` gesetzt **und** `now >= dtend`.

**Der Snapshot muss bei Änderungen weg (Fable-Fund, WICHTIG).** Der Bummel löscht ihn beim
`hide` (`app/main.py:3719`) und beim Kalender-Sync (`app/database.py:6174`); die erste Fassung
erwähnte das für den Kieker nirgends. Es gilt für: `hide`, jede Änderung am Event, jede
Änderung an den Stellen (inklusive `soll_anzahl`) und das Löschen.

Die Admin-Vorschau ruft die Rechenfunktion **direkt** auf (`force_reveal=True`), nie über
`_frozen_or_compute` — sonst schriebe eine Vorschau ein Ergebnis fest, bevor das Event zu Ende
ist. So macht es `admin_bummel_badge` (`app/main.py:2120`).

⚠ **`_PROGRESS_SNAPSHOT_VERSION` ist eine gemeinsame Zahl für alle Arten**
(`app/database.py:5391`, Filter ohne `kind`-Bezug bei `9200`). Eine reine Kieker-Rechenänderung
entwertet auch alle Kutter- und Bummel-Snapshots. Hinnehmbar — aber die stehende Regel aus
`CLAUDE.md` (vor jedem Bump prüfen, wen es trifft, Payload sichern) gilt ab jetzt für **drei**
Eventtypen. Der Kommentar an der Konstante ist zu ergänzen.

## 8. API

Öffentlich:

```
GET  /api/kieker/events                       Liste (Status, Teilnehmerzahl, Objektart)
GET  /api/kieker/event/{id}                   volle, redigierte Sicht
GET  /api/kieker/event/{id}/meine-schaetzung  eigene Einträge (braucht CID)
POST /api/kieker/event/{id}/schaetzung        {stelle_id, anzahl} → speichern
GET  /api/kieker/active                       laufendes Event fürs Live-Banner, sonst null
```

Admin:

```
GET    /api/admin/kieker/events
POST   /api/admin/kieker/events                    anlegen
POST   /api/admin/kieker/events/{id}               ändern
DELETE /api/admin/kieker/events/{id}               + Stellen, Schätzungen, Abdeckung, Snapshot
POST   /api/admin/kieker/events/{id}/stellen       Liste UPSERTEN (5.1), nicht ersetzen
GET    /api/admin/kieker/events/{id}/preview       force_reveal-Sicht, ohne Snapshot
POST   /api/admin/kieker/events/{id}/reveal
POST   /api/admin/kieker/events/{id}/hide          + Snapshot löschen
POST   /api/admin/kieker/events/{id}/push
POST   /api/admin/kieker/events/{id}/kalenderstand/{feld}   #19-Rückholknopf
```

**Die rechnenden Endpunkte werden als `def` geschrieben, nicht als `async def`** — sie laufen
damit im Threadpool und blockieren den Event-Loop nicht. Frisch bezahlte Lehre aus v14.29.0
und Issue #16; ein neuer Eventtyp darf sie nicht neu einführen. Ebenso zu übernehmen:
`_progress_sperre('kieker', id)`.

### 8.1 Prüfungen, die keine sein wollen, aber müssen

Fable-Fund (KLEIN), alle in der ersten Fassung ungenannt:

| Eingabe | Verhalten |
|---|---|
| `wertungspunkte = 0` | abweisen — sonst Division durch null |
| `wertungspunkte > Stellenzahl` | zulässig, wirkt wie „alle" |
| `anzahl < 0` | abweisen |
| `anzahl` fehlt / leer | Schätzung **löschen**, nicht als 0 speichern (3.2) |
| `dtend` leer | Event gilt nie als beendet. `now >= ''` ist in Python **immer wahr** — ohne Guard enthüllt das Event sofort. Der Bummel schützt sich mit `if not dtend: continue` (`app/database.py:4357`); hier genauso |
| Stelle ohne `soll_anzahl` bei Enthüllung | `wartet_auf_wahrheit` (7.3) |
| `POST` ohne passenden `Origin` | 403 (6.1) |

### 8.2 Antwortform (enthüllt)

```jsonc
{
  "id": 3, "name": "Seehundzählflug Ostfriesland", "status": "finished",
  "objekt_art": "Robben", "objekt_emoji": "🦭",
  "dtstart": "...", "dtend": "...", "revealed": true, "wertungspunkte": 6,
  "stellen": [ { "id": 11, "position": 0, "name": "Kachelotplate",
                 "lat": 53.66, "lon": 6.98, "radius_km": 1.0, "max_alt_ft": 2000,
                 "soll_anzahl": 217 } ],          // nur bei lage_modus='gemeinsam'
  "teilnehmer": [
    { "cid": 1234567, "callsign": "FRS49N", "name": "…",
      "guete": 84.2, "rang": 1, "abgedeckt_zahl": 6,
      "stellen": [ { "stelle_id": 11, "abgedeckt": true, "schaetzung": 200,
                     "soll_anzahl": 217, "fehler": 0.078, "gewertet": true } ] } ],
  "teilnehmer_zahl": 7
}
```

Unenthüllt fehlen `soll_anzahl`, `guete`, `rang`, `fehler` und fremde `schaetzung`
**vollständig** — nicht als `null`, sondern als abwesende Schlüssel. Ein `null` lädt dazu ein,
es später „nur noch richtig zu befüllen".

## 9. Oberfläche

### 9.1 Events-Tab

Ein drittes Panel `#kieker-results` neben `#bummel-results` (`app/static/index.html:4305`) und
`#kutter-results` (`4315`), gleiche Grammatik, gleicher Teilen-Knopf.

- Kopf: Objektart mit Zeichen, Zeitraum, Status, bei laufendem Event die eigene Abdeckung
  („4 von 14 Stellen") — aus `kieker_abdeckung` gelesen, nicht gerechnet (4.5).
- **Eingabemaske:** je Stelle eine Zeile mit Name, Zustand (abgedeckt ✓ / offen) und einem
  Zahlenfeld. Speichern je Zeile, sofort. **Das Feld startet leer, nie mit 0** (3.2); ein
  geleertes Feld löscht die Schätzung.
- Nach der Enthüllung: Rangliste, darunter je Teilnehmer die Aufschlüsselung nach Stellen mit
  Markierung der gewerteten.

**UI-Standards** (`CLAUDE.md`): Die Aufschlüsselung ist eine breite Tabelle → `.table-scroll`
mit `width:max-content; min-width:100%`. Blau bleibt Klickbarem vorbehalten. Auf dem Zahlenfeld
`font-size:16px`, sonst zoomt iOS beim Antippen hinein.

### 9.2 Karte

Die Stellen als eigene Ebene mit ihrem Radius als Kreis. Vorbild:
`app/static/data/platzrunden_de.geojson` in eigener Pane; der MIME-Typ `application/geo+json`
ist in `app/main.py:320` registriert. Die Kieker-Stellen kommen allerdings aus der Datenbank,
nicht aus einer Datei — gezeichnet wird aus der Event-Sicht heraus, der Rest des Musters
(eigene Pane, eigener Ebenen-Schalter) gilt unverändert.

### 9.3 Das Zeichen wird gespeichert, nicht der Dateiname

**Fable-Fund (KLEIN), mit Folgen für Abschnitt 1.** Die erste Fassung wollte in `objekt_emoji`
den Twemoji-Dateinamen ablegen und über `emoji(name)` (`app/static/index.html:8692`) rendern.
Der Helfer hat keinen Rückfall: Fehlt die SVG, steht ein kaputtes Bild da. **Damit bräuchte
jede neue Objektart ein Deploy für ihre Grafik** — und die Behauptung aus Abschnitt 1, die
Objektart sei „ein Feld, keine Programmvariante", wäre nicht wahr.

Deshalb: `objekt_emoji` speichert **das Zeichen** (`🦭`), gerendert wird mit
`emojiChar(ch)` (`8726`) — der leitet den Dateinamen aus dem Codepoint ab und fällt auf das
Rohzeichen zurück, wenn die Datei fehlt. Der Admin kann eine neue Art eintragen, ohne dass
jemand deployt.

Für den Eventtyp selbst wird `🔭` (U+1F52D → `1f52d.svg`) gebraucht; **diese Datei fehlt** und
ist mit anzulegen. `🦭` (`1f9ad.svg`) ist entgegen der ersten Fassung **bereits vorhanden** —
das war schlicht falsch nachgesehen.

### 9.4 Statistik-Kacheln

Die Sektion „Spezial-Events" behandelt Kutter und Bummel gleichrangig
(`docs/superpowers/specs/2026-07-07-spezialevents-kpi-statistiken-design.md`). Ein dritter Typ
gehört dort in derselben Kachel-Grammatik hinein: *Eventart · Teilnahmen · Stellen abgedeckt ·
Ø Güte*. Dafür kommt `aggregate_kieker_kpis(views)` neben die beiden bestehenden
Aggregatfunktionen — reine Summierung über eingefrorene Sichten, keine Neurechnung.

## 10. Kalender

Marker `friesenkieker` in Titel oder Beschreibung. Der Termin legt **nur die Hülle** an —
Name, Zeitraum, Push.

**Die Stellenliste kommt immer aus dem Admin, nie aus dem Kalender.** Der Kutter kann seine
Fracht aus einer Beschreibungszeile lesen, weil „1000 kg Krabbenbrötchen" ein Satz ist. Eine
Liste von vierzehn Koordinaten ist keiner. Ein Event ohne Stellen ist inaktiv und wird im
Admin als „noch nicht bestückt" geführt.

**Als eigene Funktion, nicht als vierter Rückgabewert (Fable-Fund, KLEIN).** `parse_route`
(`app/calendar_sync.py:111-148`) liefert ein 3-Tupel und hat 25 Aufrufstellen in `app/` und
`tests/`. Ein viertes Feld hieße, sie alle anzufassen. Der Kieker braucht die
Streckenlogik ohnehin nicht — er hat keine Strecke, und die Plausibilitätsprüfung
`_route_is_plausible`, an der `is_bummel` und `is_transport` hängen (`Zeile 146/147`), würde
**jeden Kieker-Termin ohne ICAO abweisen**. Deshalb eine eigene, kleine Funktion:

```python
def ist_kieker(summary: str, description: str) -> bool:
    """Marker ``friesenkieker`` in Titel oder Beschreibung. BEWUSST ohne die
    Strecken-Plausibilitätsprüfung: Ein Kieker hat keine Strecke, und ein Termin
    ohne ICAO-Code ist für ihn der Normalfall, nicht der Fehler."""
```

`calendar_events` braucht dazu die Spalte `is_kieker INTEGER DEFAULT 0` — Schema bei
`app/database.py:66-75`, Migration in der Liste bei `669-673`, dazu die SELECT/INSERT-Stellen.
Das ist mehr Handarbeit, als die erste Fassung nahelegte.

## 11. Push und Latches

Zwei Ereignisse über den bestehenden Events-Kanal (`_check_bummel_reveals`,
`app/poller.py:1539`, ist die Vorlage — sie schließt die DB-Verbindung **vor** dem Versand):

- **Start** — die erste Zeile in `kieker_abdeckung` setzt `started_at`.
  „FRS49N hat den Kieker eröffnet."
- **Enthüllung** — `revealed_at`. „Die Zählung ist ausgewertet! 🔭"

Derselbe Job rechnet die Abdeckung inkrementell fort (4.5). Es gilt die stehende Regel: **keine
Datenbank-Transaktion um einen Netzabruf**, und die Rechnung gehört nicht in den Poll-Takt der
Positionsverarbeitung.

## 12. Ehrlichkeit: Der Kieker ist nicht manipulationssicher

Das gehört an eine sichtbare Stelle, weil es sonst später als Fehler gemeldet wird.

**Stufe 1** zählt fest gebaute Szenerie. Die Wahrheit steht damit oft auch bei Wikipedia
(Abschnitt 2). Die Abdeckungsprüfung verhindert genau eine Sache: dass jemand gewinnt, **ohne
zu fliegen**. Mehr verspricht sie nicht.

**Stufe 2** verschiebt das, hebt es nicht auf: Der Server erzeugt die Lage, muss sie aber dem
Paket des Piloten mitteilen. **Die Lage-Schnittstelle ist die Wahrheit in maschinenlesbarer
Form.** Kein Verschlüsselungskniff ändert daran etwas; der Rechner, der die Objekte zeichnet,
muss wissen, wie viele es sind.

Die Erschwerung, die dennoch möglich ist:

> **Die Lage wird nach Nähe ausgeliefert.** Wer die vollständige Wahrheit will, muss jede
> Stelle anfliegen — also genau das tun, was die Aufgabe verlangt.

**Fable-Fund (WICHTIG): In der ersten Fassung war dieser Preis null.** Der Umkreis stand als
Parameter `umkreis_km` in der Anfrage, und auch die Position kam vom Client — `umkreis_km=1000`
hätte alles geliefert. Beides muss der Server bestimmen:

- Der Umkreis ist **serverseitig fest**, kein Parameter.
- Die angefragte Position wird gegen die **letzte bekannte VATSIM-Position derselben CID**
  geprüft (`live_positions`); weicht sie um mehr als wenige Kilometer ab, gibt es 409. Der
  Schlüssel trägt die CID, der Server weiß also, wo der Pilot ist.

Das ist immer noch keine Sicherheit, sondern ein Preis. Für eine Gruppe befreundeter Piloten
ist er angemessen; als Sicherheitsversprechen wäre er gelogen.

**Der Rückfallweg aus Issue #20** — der Server erzeugt Szenerie-XML, das Paket holt sie ab —
ist hier deutlich schlechter: Dort liegt die vollständige Objektliste danach als lesbare Datei
auf der Platte. Wer sie öffnet, hat alle Zahlen, ohne einen Meter zu fliegen. Das ist neben dem
Handgriff vor dem Flug und dem Wegfall von MSFS 2020 der dritte Grund, warum dieser Weg nur der
Rückfall ist.

## 13. Stufe 2 — das Paket `msfs-kieker/`

**Nicht Gegenstand der Umsetzung dieser Spec.** Hier steht der Vertrag, damit Stufe 1 ihn nicht
verbaut.

### 13.1 Ort

`msfs-kieker/` im friesenspy-Repo, neben `msfs-panel/`. Begründung ist die Kopplung: Das Paket
holt seine Lage vom Server; ein eigenes Repo ließe Paketversion und Server-Schnittstelle
auseinanderdriften — dasselbe Problem, das das Kniebrett schon hatte („Erforderlich ist
mindestens 2.0.0"), nur über zwei Repos verteilt.

Der Einwand dagegen ist berechtigt und wird nur vorläufig überstimmt: Ein Paket mit
3D-Modellen bläht ein Repo dauerhaft auf. **Solange Boote gezählt werden, enthält es kein
einziges Modell** — MSFS bringt Boote als SimObjects mit. Schwer wird es erst mit den Robben,
und dann weiß man auch, wie schwer.

`msfs-panel/` liefert das Muster: `PackageSources/`, ein `build-package.ps1` unter Windows, und
ein ZIP, das **nicht im Docker-Image steckt**, sondern je Release einmal neben die Datenbank
gelegt und über eine gate-geschützte Seite ausgeliefert wird (`_efb_zip_path`,
`app/main.py:572`).

### 13.2 Warum eigene SimObjects und nicht die vorhandenen Tiere

Im Szenerie-Repo `regover13/east-frisian-islands-counting-seals` steht die Antwort im
Quelltext (`generate_seals.py:22`):

```python
# Library Object GUIDs from Hummods.BGL (human-library-animated)
# These are the PLACEABLE GUIDs (not SimObject model GUIDs)
```

Ein **LibraryObject** existiert nur als GUID in einer Modellbibliothek und hat keinen Namen,
unter dem etwas von außen es setzen könnte. `SimConnect_AICreateSimulatedObject` erwartet einen
**Container-Titel** aus einer `sim.cfg`. Fremde Bibliotheksmodelle lassen sich nicht
nachträglich zu SimObjects erklären — eigene schon. Szenerie ist überdies statisch: beim Laden
gelesen, zur Laufzeit nicht änderbar. Beides zusammen schließt den Szenerie-Weg für ein
serverseitig gesteuertes Event aus.

**Verworfen bleibt vPilot**, aus zwei unabhängigen Gründen: Es zeichnet ausschließlich, was das
VATSIM-Netz meldet — ein Objekt erschiene nur, wenn sich etwas als Flugzeug an dieser Position
einloggt, was gegen den Code of Conduct verstößt — und eine Injektionsschnittstelle gibt es
ohnehin nicht.

### 13.3 Die Schnittstelle

```
GET /api/kieker/event/{id}/lage?lat=<breite>&lon=<laenge>
Authorization: Bearer <kieker-schluessel>
→ 200 { "objekte": [ {"titel": "Boat_Small", "lat": …, "lon": …, "kurs": 210} ] }
→ 409 wenn die gemeldete Position nicht zur letzten VATSIM-Position der CID passt
```

Kein `umkreis_km` in der Anfrage (Abschnitt 12). Der Schlüssel ist ein Zufallswert, den der
Pilot einmal aus der Weboberfläche in die Konfigurationsdatei des Pakets kopiert
(`kieker_schluessel(schluessel PK, cid, created_at, last_seen)`). Ein nativer Spawner kann den
Geräteweg des Kniebretts nicht mitbenutzen — der lebt in MSFS' eigenem Speicher, nicht auf der
Platte. **Der Schlüssel ist ein Zugangsgeheimnis und muss im Admin widerrufbar sein**, wie eine
Panel-Gerätebindung.

### 13.4 Die vier Messfragen

Vom Nutzer am Simulator zu beantworten; ein geratener Wert wäre schlimmer als eine offene
Frage.

1. Erreicht `AICreateSimulatedObject` ein **WASM-Modul** im Paket? Wenn ja, entfällt das
   externe Programm — die WASM-Fassung von SimConnect kennt nur einen Teil des Befehlsvorrats.
2. Welche **SimObject-Kategorie** passt für ein liegendes Tier, ohne dass der Simulator ihm ein
   Verhalten andichtet? (Für Boote stellt sich die Frage nicht.)
3. Gibt es **`exe.xml`** in MSFS 2024 noch als Autostart-Weg?
4. Wie viele Objekte verträgt der Simulator, bevor es ruckelt?

**Der erste Schritt ist billig und trifft den Kern:** ein mitgeliefertes Boot per SimConnect an
eine Wattkoordinate setzen und nachsehen, ob es dort steht. Liegt es dort, lohnt sich alles
Weitere; liegt es nicht dort, ist Stufe 1 trotzdem fertig und spielbar.

## 14. Tests

`tests/test_kieker.py` — Geometrie und Wertung, rein, ohne Datenbank:

- `test_strecke_deckt_uebersprungene_stelle_ab` — zwei Stichproben 1,1 km auseinander, die
  Stelle mit 500 m Radius dazwischen. Der Punkttest schlüge fehl, der Streckentest greift.
- **`test_schraege_strecke_am_radiusrand`** — Kurs 045° auf 53,7° N, Stelle 0,95 × Radius
  seitlich. Ohne cos(Breite)-Skalierung ergibt sich 1,054 km statt 0,950 km und der Test wird
  rot. **Ohne diesen Fall wäre der Fehler durch alle anderen Tests gerutscht** (Fable-Fund).
- `test_luecke_verbindet_nicht` — Reconnect Norderney → München; keine Stelle dazwischen gilt
  als abgedeckt. Zusätzlich: **196-Sekunden-Aussetzer bei 100 kt bleibt gültig** (4.3).
- `test_lange_strecke_wird_nicht_begradigt` — Δt in der Schranke, Länge über 10 km.
- `test_stehendes_flugzeug_deckt_nicht_ab` — beide Endpunkte unter 30 kt.
- `test_wiederholungen_werden_zusammengefasst` — stehender Feed, danach Sprung.
- `test_hoehe_ueber_deckel_deckt_nicht_ab` / `test_hoehe_wird_am_fusspunkt_interpoliert`.
- `test_fehler_gedeckelt` — Wahrheit 5, Schätzung 100 → 1,0, nicht 19,0.
- `test_null_objekte_zaehlbar` — Wahrheit 0, Schätzung 0 → Fehler 0.
- `test_leer_ist_nicht_null` — leere Schätzung und 0 sind zwei Zustände.
- `test_nicht_abgedeckte_stelle_zaehlt_voll`.
- `test_wertungspunkte_nimmt_die_besten` und `test_wertungspunkte_auswahl_deterministisch`
  (mehr als N Stellen mit Fehler 1,0 → Auswahl nach `position`).
- **`test_rang_unabhaengig_von_reihenfolge`** — dieselbe Fehlermenge in anderer Reihenfolge
  muss denselben Rang ergeben (Fließkomma, 3.5).
- `test_gleichstand_wird_gebrochen` — gleiche Güte, verschiedene Abdeckungszahl.

`tests/test_kieker_api.py`:

- `test_wahrheit_fehlt_vor_enthuellung` — **rekursiv** über das serialisierte JSON, für
  Detailsicht **und** Liste.
- `test_fremde_schaetzung_unsichtbar`.
- `test_schaetzung_nach_dtend_abgewiesen` / `test_schaetzung_ohne_cid_abgewiesen`.
- `test_form_post_ohne_origin_abgewiesen` (6.1).
- `test_keine_enthuellung_ohne_wahrheit` (7.3).
- `test_leeres_dtend_enthuellt_nicht` (8.1).
- `test_endpunkte_sind_nicht_async` — an den Funktionsobjekten geprüft
  (`inspect.iscoroutinefunction`), nicht per Textsuche. Vorbild `tests/test_kutter_eventloop.py`.
- `test_admin_vorschau_schreibt_keinen_snapshot`.
- `test_stellen_aendern_verwirft_snapshot_und_abdeckung`.

`tests/test_kieker_db.py`:

- **`test_stelle_umbenennen_behaelt_schaetzungen`** (5.1) — der Test zum kritischsten Fund.
- `test_event_loeschen_raeumt_kindtabellen_und_snapshot`.
- `test_abdeckung_rechnet_inkrementell` — zweiter Lauf verarbeitet nur neue Positionen und
  verliert die Strecke über die Laufgrenze nicht.

`tests/test_calendar_sync.py`: `test_kieker_marker_ohne_icao_erkannt`.

**Jeder dieser Tests ist gegen den entfernten Fix gegenzuprüfen** — er muss ohne ihn rot
werden. Die stehende Regel steht in `CLAUDE.md` und hat am 08.09.2026 zwei falsch-grüne Tests
entlarvt.

## 15. Version und Doku

- `app/CHANGELOG.json`: neuer Eintrag oben, **`"highlight": false`** (stehende Regel, ohne
  Ausnahme). Nummer: **v15.0.0** — dritter Eventtyp. Siehe Frage 3.
- `README.md`: eigener Handbuch-Abschnitt **und** der Hilfetext hinter dem `?` — ohne beides
  gilt ein Feature-Commit in diesem Projekt als unfertig.
- `docs/api.md`: alle Endpunkte aus Abschnitt 8.
- `docs/architecture.md`: Wertungsformel, Deckungsprüfung, Abdeckungstabelle, Snapshot-Art.
- Kommentar an `_PROGRESS_SNAPSHOT_VERSION` um den dritten Typ ergänzen (7.4).

## 16. Bewusst nicht im Umfang

- **Kein Badge-PNG in Stufe 1.** `app/badge.py` rendert `total_min` und `delta` — eine
  Blockzeit-Semantik. Eine Güte in Prozent ist eine dritte Bedeutung im selben Bild; Politur,
  die den Eventtyp nicht aufhalten darf. Stufe 3.
- **Keine Lagen je Pilot in Stufe 1.** `lage_modus` existiert und steht auf `gemeinsam`.
- **Keine Streckenabdeckung.** Das ist #22. Die Geometrie aus Abschnitt 4 ist so gewählt, dass
  sie dort weiterverwendbar ist — mehr nicht (YAGNI).
- **Keine KI-Sprüche.**
- **Kein CSRF-Schutz für die bestehenden `/api/me`-POSTs** — derselbe Befund (6.1), aber eine
  eigene Entscheidung.
- **Kein Umbau am Szenerie-Repo.** `east-frisian-islands-counting-seals` ist für sich fertig.
  Beisteuern wird es die **14 von Hand im World Editor kalibrierten Koordinaten** — die
  eigentliche Arbeit darin und die Startliste für einen Robben-Kieker.
- **Die vier falschen ICAO-Codes in `seal_colonies.json`** bleiben liegen; der Kieker legt das
  Feld gar nicht erst an.

## 17. Was das Fable-Review geändert hat

Zur Einordnung, falls jemand die erste Fassung im git-Verlauf findet (`56d1dc8`):

| Fund | Folge |
|---|---|
| Stellenliste „ersetzen wie beim Kutter" | **Datenverlust mid-Event.** Jetzt Upsert über `id` (5.1) |
| Kein Tiebreak, Wahrheit nachschlagbar | **kein Sieger.** Jetzt dreistufiger Bruch (3.5), Risiko in §2 ehrlich |
| Keine Abdeckungstabelle | **Kutter-Fehler wiederholt.** Jetzt inkrementell mit Zeiger (4.5) |
| cos(Breite) nicht gefordert | Stellen am Radiusrand fielen durch (4.4), neuer Test |
| 90-s-Lückenregel | an Produktionsdaten widerlegt; jetzt drei Schranken (4.3) |
| Auto-Reveal bei `dtend` | fror leere Wahrheiten ein; jetzt `wartet_auf_wahrheit` (7.3) |
| Snapshot-Invalidierung fehlte | jetzt bei `hide`, Event- und Stellenänderung (7.4) |
| `umkreis_km` vom Client | Nähe-Auslieferung war wirkungslos (12) |
| Fließkomma-Summenreihenfolge | 12.192/20.000 Fälle betroffen; Rang auf gerundeter Güte (3.5) |
| `soll_anzahl` an der Stelle | bei `je_pilot` Umbau nötig; jetzt am Teilnehmer (5.2) |
| Emoji als Dateiname | jede neue Objektart bräuchte ein Deploy (9.3) |
| `SameSite=none` | Schätzung per CSRF fälschbar; jetzt `Origin`-Prüfung (6.1) |
| Zeilenangaben, `1f9ad.svg` | schlicht falsch, korrigiert |

## 18. Offene Fragen

Nummeriert, damit du mit „mach 2 und 5" antworten kannst.

1. **Stimmt die Staffelung?** Stufe 1 zählt fest gebaute Szenerie und braucht kein Addon —
   sofort spielbar, ganze Mechanik unter echten Bedingungen erprobt. **Aber** Fable hat
   gezeigt, dass die Wahrheit dabei oft nachschlagbar ist (Abschnitt 2). Willst du Stufe 1
   trotzdem, oder soll der Eventtyp erst zusammen mit den gesetzten Objekten kommen?

2. **Die Wertungsformel** (3.2): relativer Fehler je Stelle, bei 100 % gedeckelt, gemittelt,
   als Güte in Prozent. Oder soll der Sieger wie beim Bummel über den Abstand zu einem
   **Gruppenschnitt** ermittelt werden? Das bräuchte gar keine hinterlegte Wahrheit — und
   löste damit sowohl das Nachschlage- als auch das Wer-zählt-nach-Problem auf einen Schlag.
   **Das ist nach dem Review die interessanteste Alternative**, und ich habe sie bewusst nicht
   selbst entschieden.

3. **Versionsnummer:** v15.0.0 (dritter Eventtyp) oder lieber v14.30.0? `highlight` bleibt in
   jedem Fall aus, das ist deine Entscheidung allein.

4. **Board-Login:** Ohne aktives Forum-SSO kann niemand eine Schätzung eintragen (6). Ist es
   dauerhaft an? Wenn nicht, brauchen wir einen zweiten Eingabeweg.

5. **Wer trägt die Wahrheit ein?** In Stufe 1 der Admin von Hand — bei Windrädern das Abzählen
   einer Karte, bei Schiffen an einer Pier müsstest du selbst hinfliegen. Reicht dir das?
   (Abschnitt 7.3 wartet jetzt darauf, statt leere Ergebnisse einzufrieren.)

6. **Das erste Event.** Welche Objekte, welche Stellen? Die ostfriesischen Offshore-Windparks
   liegen nahe (Riffgat, Alpha Ventus, Nordergründe — gut fliegbar von EDWR/EDWG, feste
   Anlagenzahlen, über Wasser stimmt MSL ≈ AGL exakt). **Nur:** Genau bei denen steht die
   Zahl bei Wikipedia. Etwas, dessen Zahl nur du kennst, wäre der bessere Anfang.

7. **Der Probeflug für Stufe 2** (ein mitgeliefertes Boot per SimConnect an eine
   Wattkoordinate setzen) braucht deinen Simulator. Vor Stufe 1 — oder unabhängig, wann es
   dir passt?
