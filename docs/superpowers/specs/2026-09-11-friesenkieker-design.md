# 🔭 FriesenKieker — Objekte aus der Luft zählen · Design

**Datum:** 2026-09-11 · **Status:** Entwurf, noch nicht abgenommen · **Vorlauf:** Brainstorming
10.09.2026, GitHub-Issue #20 · **Verwandt:** #21 (Suchflug), #22 (Deichkontrolle)

> **Diese Spec ist in Abwesenheit des Nutzers entstanden.** Alle Entscheidungen darin sind
> *Vorschläge mit Begründung*, keine Abnahmen. Die Punkte, bei denen ich die Entscheidung
> nicht selbst treffen kann oder wollte, stehen gesammelt in Abschnitt 17.

---

## 1. Ziel

Ein dritter Eventtyp neben 🏁 **FriesenBummel** und 🦐 **FriesenKutter**: Die Gruppe fliegt
eine Liste von Stellen ab, sieht hin und zählt, was dort liegt. Gewertet wird, wer der
Wahrheit am nächsten kommt — **aber nur an den Stellen, die er auch wirklich überflogen hat.**

Der Typ heißt nach dem Hinsehen, nicht nach dem Gezählten: „Kieker" ist auf Platt das Fernglas
und zugleich der, der guckt. Gezählt werden kann alles — Boote in der Deutschen Bucht, Robben
auf den Sandbänken, Elche in Norwegen. Die Objektart ist ein Feld, keine Programmvariante.

## 2. Der Zuschnitt, der diese Spec überhaupt umsetzbar macht

Im Brainstorming stand der Eventtyp und das MSFS-Paket, das die Objekte setzt, als **ein**
Vorhaben. So ist es nicht baubar: Das Paket hängt an vier Messfragen, die nur am Simulator zu
beantworten sind (Abschnitt 13), und solange sie offen sind, ist auch der Server nicht fertig
zu bekommen.

**Der Ausweg ist eine Beobachtung, die im Brainstorming untergegangen ist: Es gibt Objekte, die
in jedem Simulator an derselben Stelle stehen und in bekannter Zahl — die fest gebaute
Szenerie.** Windräder eines Offshore-Parks, Schiffe an einer Pier, Silos, Leuchttürme. Wer sie
zählen lässt, braucht **kein Addon, keine Verteilung, kein SimConnect** — die Wahrheit trägt
der Admin von Hand ein, und sie stimmt für jeden Teilnehmer, weil sie im Simulator selbst
steht.

Daraus folgt die Staffelung:

| Stufe | Was sie bringt | Was sie braucht | Risiko |
|---|---|---|---|
| **1 — Der Eventtyp** | vollständig spielbarer Kieker auf fest gebaute Szenerie | nur Server + Oberfläche | keins, alles bekannt |
| **2 — Das Paket** | frei gesetzte Objekte, Lage vom Server, je Pilot verschieden | `msfs-kieker/`, SimConnect | vier offene Messfragen |
| **3 — Politur** | Badge fürs Forum, eigene Robben-Modelle | Stufe 2 muss stehen | Modellierung, Lizenzfragen |

**Stufe 1 ist der eigentliche Gegenstand dieser Spec.** Stufe 2 ist als Vertrag ausgearbeitet
(Abschnitt 13) — der Server bekommt schon jetzt die Felder, die sie braucht, damit die Stufe
später kein Schema-Umbau ist. Stufe 3 ist bewusst nur benannt.

**Der erste echte Kieker könnte damit ohne einen einzigen Handgriff am Simulator stattfinden:**
„Zählt die Windräder in Riffgat, Nordergründe und Alpha Ventus." Das ist kein Ersatzprogramm,
sondern eine eigenständig gute Aufgabe — und sie prüft die gesamte Server-Mechanik unter
echten Bedingungen, bevor irgendjemand ein Addon installiert.

## 3. Die Wertung

### 3.1 Zwei Fragen, nicht eine

Issue #20 stellte „Zählen oder Fliegen?" als Alternative dar und nannte beides zusammen den
teuersten Schnitt. **Das ist bei genauerem Hinsehen falsch herum:** Ohne die Flugprüfung ist
der Kieker ein Ratespiel, das man vom Sofa aus gewinnt — bei fest gebauter Szenerie (Stufe 1)
steht die Antwort im Zweifel bei OpenStreetMap. Die Abdeckung ist also nicht die zweite
Wertung, sie ist die **Zulassung**.

- **Abdeckung (A)** — je Stelle: Hat der Pilot sie im Korridor überflogen? Ja/Nein.
- **Schätzung (B)** — je Stelle: Welche Zahl hat er eingetragen? Bewertet am Abstand zur
  Wahrheit.

**Eine Stelle wird nur gewertet, wenn sie abgedeckt ist.** Eine Schätzung ohne Überflug zählt
nicht — und das steht im Ergebnis ausdrücklich als `abgedeckt: false` daneben, damit niemand
denkt, der Server habe seine Zahl verschluckt.

Das ist genau die Grammatik, die der Bummel schon hat (`complete` / `incomplete` mit
`visited` / `missing`). Es entsteht keine neue Denkfigur, nur eine neue Füllung.

### 3.2 Die Formel

Je Stelle *p*:

```
fehler_p = min(1.0, |schätzung_p − wahrheit_p| / max(wahrheit_p, 1))     wenn abgedeckt und eingetragen
fehler_p = 1.0                                                           sonst
```

Gemittelt wird über die **Wertungsmenge** — das sind standardmäßig *alle* Stellen der Liste,
und nur wenn `wertungspunkte = N` gesetzt ist, die *N* Stellen mit dem kleinsten Fehler
(Abschnitt 3.3). Daraus die Güte in Prozent:

```
güte = (1 − Ø fehler über die Wertungsmenge) × 100
```

Vier Eigenschaften, um derentwillen die Formel so und nicht anders aussieht:

- **Relativ, nicht absolut.** Zehn daneben ist bei 200 Robben nichts und bei 5 Booten alles.
  Ein absoluter Fehler würde die großen Kolonien zur einzigen relevanten Stelle machen.
- **Bei 1,0 gedeckelt.** Ohne den Deckel wäre ein wilder Fehlgriff (5 wahr, 100 geraten →
  Fehler 19) schlimmer als gar nicht hinzufliegen — man käme durch **Nichtstun** nach vorn.
  Mit dem Deckel ist ein Fehlgriff höchstens so teuer wie ein Nichtantritt. Raten wird nie
  bestraft, nur nie belohnt.
- **`max(wahrheit, 1)` im Nenner** erlaubt eine Stelle mit **null** Objekten — eine legitime
  Falle. Wer dort 0 einträgt, hat Fehler 0; wer 3 einträgt, Fehler 1,0.
- **Eine nicht abgedeckte Stelle bleibt in der Wertungsmenge** (mit Fehler 1,0) und fällt
  nicht einfach heraus. Sonst schlüge der, der eine einzige Stelle anfliegt und sie trifft,
  jeden, der vierzehn mit kleinen Fehlern abarbeitet.

### 3.3 Nicht jede Stelle muss zählen

Ein Feld am Event: **`wertungspunkte`** — „es zählen die *N* besten Stellen" (leer = alle).

Der Admin kann damit vierzehn Kolonien auslegen und sagen: „sechs davon reichen." Jede
weitere geflogene Stelle kann das Ergebnis dann nur verbessern, nie verschlechtern — es wird
also belohnt, mehr zu fliegen, ohne dass ein Abend mit vierzehn Pflichtstellen unspielbar
wird. Die Anzeige listet trotzdem **alle** Stellen mit ihrem Einzelergebnis und markiert, welche
in die Wertung gingen.

Kosten: eine Sortierung. Nutzen: der Unterschied zwischen einer Aufgabe und einer Zumutung.

### 3.4 Rang

Absteigend nach Güte. Gleichstand bekommt denselben Rang (dicht, wie beim Bummel). Kein
Zeitkriterium — der Kieker ist ausdrücklich kein Rennen, wer langsam und tief fliegt, zählt
besser.

## 4. Die Deckungsprüfung

Der teuerste Denkfehler wäre, die Positionsstichproben einzeln gegen den Umkreis zu prüfen.

**Der Feed liefert alle ~15 Sekunden einen Punkt** (`VATSIM_POLL_INTERVAL=15`, mit Jitter).
Bei 140 kt liegen zwischen zwei Stichproben **1,08 km**. Eine Stelle mit 500 m Radius —
1 km Durchmesser — kann ein Pilot damit **sauber überspringen**, ohne dass eine einzige
Stichprobe hineinfällt. Er wäre mitten drüber geflogen und hätte nichts abgedeckt.

**Deshalb wird gegen die Verbindungsstrecken zwischen aufeinanderfolgenden Stichproben
geprüft, nicht gegen die Stichproben.** Der Test wird damit unabhängig von der Abtastdichte
und der Fluggeschwindigkeit.

Das ist zugleich die Antwort auf die Sequenzierungs-Warnung aus #22: Eine
**Streckenabdeckung** braucht exakt dieselbe Geometrie (Abstand Punkt ↔ Strecke), nur in die
andere Richtung gelesen. Wer den Kieker so baut, verbaut sich die Deichkontrolle nicht,
sondern legt ihr Fundament.

### 4.1 Der Korridor

Zwei Kriterien, nicht drei:

| Kriterium | Feld | Vorschlag |
|---|---|---|
| seitlicher Abstand | `radius_km` je Stelle, Rückfall aufs Event | **1,0 km** |
| Höhe | `max_alt_ft` je Stelle, Rückfall aufs Event | **2000 ft** |

**Geschwindigkeit ist bewusst KEIN Kriterium.** Sie soll erzwingen, dass jemand wirklich
hinsieht — das tut die Schätzung aber von selbst: Wer mit 200 kt vorbeirauscht, zählt
schlecht und verliert. Ein Geschwindigkeitsdeckel fügt dem nichts hinzu und schließt dafür
Muster aus, die nicht langsamer können. Die Wertung erledigt es billiger als die Regel.

**Die Höhe ist MSL, nicht AGL — und das ist eine Entscheidung, keine Nachlässigkeit.**
`position_history.altitude` trägt die vom VATSIM-Feed gemeldete Flughöhe in Fuß. Eine
AGL-Rechnung bräuchte ein Geländemodell, das FriesenSpy nicht hat und für ein Feature dieser
Größe auch nicht bekommen sollte. Über dem Wattenmeer ist der Unterschied null (Gelände ≈ 0),
über norwegischen Bergen wäre er groß — dort setzt der Admin die Obergrenze eben höher. Das
Feld heißt `max_alt_ft` und **nicht** `max_agl_ft`, damit niemand später etwas anderes
hineinliest.

⚠ **Die gemeldete Höhe ist barometrisch und kann je nach Druckeinstellung um mehrere hundert
Fuß danebenliegen.** Eine enge Obergrenze ist deshalb eine Falle: Bei 500 ft Deckel scheitert
ein Pilot, der real auf 400 ft war, an seinem Höhenmesser statt an seinem Flug. Darum der
großzügige Vorschlag von 2000 ft — er trennt zuverlässig „tief drüber" von „im Reiseflug
zufällig darüber hinweg", und mehr soll er nicht.

### 4.2 Die Lücken-Regel

**Zwei Stichproben bilden nur dann eine Strecke, wenn zwischen ihnen höchstens 90 Sekunden
liegen** (sechs Poll-Takte, großzügig gegen einen Aussetzer).

Ohne diese Regel entsteht aus einem Reconnect — Pilot loggt sich bei Norderney aus und bei
München wieder ein — eine schnurgerade Strecke quer über die Republik, die **jede** Stelle
auf ihrem Weg abdeckt. Das ist kein Randfall: `position_history` führt die Positionen einer
CID durchgehend, sitzungsübergreifend, und `canonicalize_legs` existiert genau deshalb.

### 4.3 Die Rechnung

Neu in `app/geo.py`:

```python
def punkt_zu_strecke_km(plat, plon, alat, alon, blat, blon) -> tuple[float, float]:
    """Kürzester Abstand (km) von P zur Strecke A→B, plus Lageparameter t ∈ [0,1].

    Der Fußpunkt wird in einer örtlich flachen Näherung bestimmt (bei Streckenlängen
    unter ~10 km unter einem halben Prozent Fehler), der zurückgegebene ABSTAND aber
    mit :func:`haversine` gemessen — damit misst der Kieker mit demselben Maßstab wie
    der Rest des Projekts. Entartete Strecke (A == B) → Abstand zu A, t = 0.
    """
```

Ablauf je Event:

1. Positionen im Fenster `[dtstart, dtend]` einmal laden:
   `SELECT cid, latitude, longitude, altitude, ts FROM position_history
    WHERE ts >= ? AND ts <= ? ORDER BY cid, ts` — der Index `idx_ph_ts` trägt das.
   **In `position_history` stehen ausschließlich Piloten mit dem `CALLSIGN_PREFIX`** — der
   Kieker gilt wie Bummel und Kutter nur für Friesen, ohne dass dafür etwas gefiltert werden
   müsste.
2. Je CID die Stichproben zu Strecken paaren, Lücken > 90 s trennen.
3. Je Stelle: Umgebungsrechteck über die Strecke (min/max der Endpunkte, um `radius_km`
   aufgeweitet) gegen das Rechteck der Stelle prüfen — schneidet es nicht, ist auch der Kreis
   nicht getroffen, und die teure Rechnung entfällt.
4. Sonst `punkt_zu_strecke_km`, dann die Höhe am Fußpunkt interpolieren
   (`alt = alt_a + t·(alt_b − alt_a)`) und beide Bedingungen prüfen.
5. Ein Treffer genügt je (CID, Stelle) — danach Abbruch für diese Kombination.

**Größenordnung:** Ein Abend mit 15 Piloten × 4 h ergibt rund 14.000 Stichproben, also ebenso
viele Strecken. Gegen 14 Stellen sind das 200.000 Rechteck-Prüfungen und ein paar tausend
Haversine-Aufrufe — Bruchteile einer Sekunde. Zum Vergleich: Die Kutter-Rechnung kam am
09.09.2026 auf 4,86 Mio. Haversine-Aufrufe je Lauf. Der Kieker ist gutmütig.

## 5. Datenmodell

Drei neue Tabellen. Die Namensgebung folgt dem jüngeren Bestand (deutsch), die Struktur der
von `bummel_races` / `transport_events`.

```sql
CREATE TABLE IF NOT EXISTS kieker_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT,
    objekt_art     TEXT,                 -- Anzeigewort: "Boote", "Robben", "Windräder"
    objekt_emoji   TEXT,                 -- Twemoji-Dateiname, s. Abschnitt 9
    dtstart        TEXT,
    dtend          TEXT,                 -- effektiv (Mitternacht-Default bereits angewandt)
    radius_km      REAL DEFAULT 1.0,     -- Vorgabe für Stellen ohne eigenen Wert
    max_alt_ft     REAL DEFAULT 2000,    -- dito; MSL, NICHT AGL (Abschnitt 4.1)
    wertungspunkte INTEGER,              -- NULL = alle Stellen zählen
    lage_modus     TEXT DEFAULT 'gemeinsam',  -- 'gemeinsam' | 'je_pilot' (Stufe 2)
    source         TEXT,                 -- 'calendar' | 'manual'
    calendar_uid   TEXT UNIQUE,
    push_enabled   INTEGER DEFAULT 1,
    started_at     TEXT,                 -- Latch: erste Abdeckung
    revealed_at    TEXT,                 -- Latch: Ergebnisse enthüllt
    reveal_suppressed INTEGER DEFAULT 0,
    manual_fields  TEXT,                 -- #19: im Admin von Hand gesetzte Felder
    badge_name     TEXT,                 -- Stufe 3
    created_at     TEXT
);

CREATE TABLE IF NOT EXISTS kieker_stellen (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     INTEGER NOT NULL,       -- REFERENCES kieker_events(id)
    position     INTEGER NOT NULL,       -- Reihenfolge in der Liste
    name         TEXT NOT NULL,          -- "Kachelotplate", "Riffgat Nord"
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    radius_km    REAL,                   -- NULL = Vorgabe des Events
    max_alt_ft   REAL,                   -- NULL = Vorgabe des Events
    soll_anzahl  INTEGER                 -- DIE WAHRHEIT. Niemals vor der Enthüllung ausliefern.
);
CREATE INDEX IF NOT EXISTS idx_kieker_stellen_event ON kieker_stellen(event_id);

CREATE TABLE IF NOT EXISTS kieker_schaetzungen (
    event_id   INTEGER NOT NULL,
    stelle_id  INTEGER NOT NULL,
    cid        INTEGER NOT NULL,
    anzahl     INTEGER NOT NULL,
    updated_at TEXT,
    PRIMARY KEY (event_id, stelle_id, cid)
);
```

**Kein `icao`-Feld an der Stelle.** Im Szenerie-Repo steht es und steuert nichts (null
Verweise im Generator), vier von sieben Werten sind falsch. FriesenSpy leitet den nächsten
Platz bei Bedarf über `geo.nearest_airport_icao` selbst her, und zwar richtig. Ein Feld, das
nur falsch sein kann, wird nicht angelegt.

**Für Stufe 2 kommt `kieker_lagen(event_id, stelle_id, cid, anzahl, objekte_json)` dazu**
(Abschnitt 13). Die Auflösung ist dann: *gibt es eine Zeile für (Event, Stelle, CID), gilt
deren Zahl; sonst `kieker_stellen.soll_anzahl`.* Genau **eine** Funktion darf das entscheiden
(`_wahrheit(conn, event, stelle, cid)`), damit die Wahrheit nicht an zwei Orten
auseinanderläuft.

## 6. Identität — wer trägt eine Schätzung ein?

`_current_cid(request, settings)` (`app/main.py:2351`) liefert die CID des angemeldeten
Nutzers. **Das Kniebrett kommt über denselben Weg**: Die Geräte-Bindung wird in
`app/main.py:2549` gegen `panel_devices` geprüft und setzt danach dasselbe `USER_COOKIE`.
Eine Sonderbehandlung fürs Panel ist also weder nötig noch erlaubt — es gibt einen
Identitätsweg, nicht zwei.

⚠ **Daraus folgt eine harte Abhängigkeit:** `_current_cid` gibt `None` zurück, solange das
Board-Login abgeschaltet ist. **Ohne aktives Forum-SSO kann niemand eine Schätzung eintragen,
und der Kieker ist unspielbar.** Das ist kein Fehler, den man wegprogrammieren sollte —
Schätzungen brauchen eine Person —, aber es gehört sichtbar gemacht: Der Admin zeigt an einem
Kieker-Event einen Warnhinweis, wenn das Board-Login aus ist. Siehe Frage 5 in Abschnitt 17.

## 7. Verdeckung, Enthüllung, Einfrieren

### 7.1 Was wann sichtbar ist

| | vor der Enthüllung | nach der Enthüllung |
|---|---|---|
| Stellen (Name, Lage, Radius, Höhe) | **sichtbar** — man muss ja wissen, wohin | sichtbar |
| `soll_anzahl` (die Wahrheit) | **nie** | sichtbar |
| eigene Schätzung | nur für einen selbst | sichtbar |
| fremde Schätzungen | **nie** | sichtbar |
| Abdeckung anderer | nur als Zahl („4 Stellen") | vollständig |
| Güte, Rang | **nie** | sichtbar |

**Die Wahrheit darf die Redaktionsfunktion nicht passieren, nicht einmal versehentlich.**
Beim Bummel ist die Verdeckung eine Frage der Höflichkeit — hier ist sie die Spielregel
selbst. `public_kieker_view(...)` ist die **einzige** Stelle, die aus dem inneren Zustand ein
Antwort-Dict macht, und ein Test bindet daran: `soll_anzahl` darf im serialisierten JSON einer
unenthüllten Sicht nicht vorkommen — geprüft am rekursiv durchsuchten Ergebnis, nicht am
Vorhandensein eines Schlüssels auf oberster Ebene.

### 7.2 Eingabefenster

Schätzungen sind von `dtstart` bis `dtend` änderbar, danach gesperrt — der zuletzt gespeicherte
Wert zählt. Ausdrücklich **nicht** an die Enthüllung gebunden: Ein vom Admin zurückgehaltenes
Ergebnis darf das Eingabefenster nicht heimlich verlängern.

### 7.3 Enthüllung

Der Bummel wartet vor der Enthüllung darauf, dass niemand mehr unterwegs ist — weil eine
Blockzeit erst nach dem Abstellen feststeht. **Beim Kieker gibt es nichts zu warten:** Sowohl
die Abdeckung als auch die Schätzung sind mit `dtend` definitionsgemäß abgeschlossen. Die
Enthüllung latcht deshalb beim ersten Job-Lauf mit `now >= dtend`, sofern
`reveal_suppressed = 0` ist.

Dass Positionen nach `dtend` nicht mehr zählen, ist zu dokumentieren — es ist die
Vereinfachung, die den ganzen `bummel_wartestand`-Apparat hier erspart.

### 7.4 Snapshot

`progress_snapshot` mit `kind='kieker'`, über `_frozen_or_compute` (`app/main.py:3856`).
Abgeschlossen heißt wie beim Bummel: `revealed_at` gesetzt **und** `now >= dtend` — ein per
Admin vor `dtend` erzwungenes Reveal friert nicht ein.

⚠ **`_PROGRESS_SNAPSHOT_VERSION` ist eine gemeinsame Zahl für alle Arten** (`app/database.py:5391`).
Eine reine Kieker-Rechenänderung entwertet damit auch alle Kutter- und Bummel-Snapshots. Das
ist hinnehmbar (sie rechnen sich beim nächsten Lesen neu), aber die stehende Regel aus
`CLAUDE.md` — *vor jedem Bump prüfen, wen die Neuberechnung trifft, und das Payload sichern* —
gilt ab jetzt für **drei** Eventtypen statt zwei. Der Kommentar an der Konstante ist
entsprechend zu ergänzen.

Die Admin-Vorschau ruft die Rechenfunktion **direkt** auf (`force_reveal=True`), nie über
`_frozen_or_compute` — sonst schriebe eine Vorschau ein enthülltes Ergebnis fest, bevor das
Event zu Ende ist. Genau so macht es `admin_bummel_badge` (`app/main.py:2120`).

## 8. API

Öffentlich:

```
GET  /api/kieker/events                      Liste (Status, Teilnehmerzahl, Objektart)
GET  /api/kieker/event/{id}                  volle, redigierte Sicht
GET  /api/kieker/event/{id}/meine-schaetzung  eigene Einträge (braucht CID)
POST /api/kieker/event/{id}/schaetzung        {stelle_id, anzahl} → speichern
GET  /api/kieker/active                       laufendes Event fürs Live-Banner, sonst null
```

Admin:

```
GET    /api/admin/kieker/events
POST   /api/admin/kieker/events                    anlegen
POST   /api/admin/kieker/events/{id}               ändern
DELETE /api/admin/kieker/events/{id}
POST   /api/admin/kieker/events/{id}/stellen       ganze Liste ersetzen (wie set_transport_cargo)
GET    /api/admin/kieker/events/{id}/preview       force_reveal-Sicht
POST   /api/admin/kieker/events/{id}/reveal        enthüllen
POST   /api/admin/kieker/events/{id}/hide          zurückhalten
POST   /api/admin/kieker/events/{id}/push          Push an/aus
POST   /api/admin/kieker/events/{id}/kalenderstand/{feld}   #19-Rückholknopf
```

**Die rechnenden Endpunkte werden als `def` geschrieben, nicht als `async def`.** Sie laufen
damit im Threadpool und blockieren den Event-Loop nicht. Das ist die frisch bezahlte Lehre aus
v14.29.0 (Kutter-Rechnung raus aus der Event-Loop) und aus Issue #16; ein neuer Eventtyp darf
sie nicht neu einführen. Ebenso zu übernehmen: die Einfachlauf-Sperre `_progress_sperre('kieker', id)`.

Antwortform der öffentlichen Sicht (enthüllt):

```jsonc
{
  "id": 3, "name": "Seehundzählflug Ostfriesland", "status": "finished",
  "objekt_art": "Robben", "objekt_emoji": "1f9ad",
  "dtstart": "...", "dtend": "...", "revealed": true, "wertungspunkte": 6,
  "stellen": [ { "id": 11, "position": 0, "name": "Kachelotplate",
                 "lat": 53.66, "lon": 6.98, "radius_km": 1.0, "max_alt_ft": 2000,
                 "soll_anzahl": 217 } ],
  "teilnehmer": [
    { "cid": 1234567, "callsign": "FRS49N", "name": "…",
      "guete": 84.2, "rang": 1, "abgedeckt_zahl": 6,
      "stellen": [ { "stelle_id": 11, "abgedeckt": true, "schaetzung": 200,
                     "fehler": 0.078, "gewertet": true } ] } ],
  "teilnehmer_zahl": 7
}
```

Unenthüllt fehlen `soll_anzahl`, `guete`, `rang`, `fehler`, `schaetzung` **vollständig** — nicht
als `null`, sondern als abwesende Schlüssel. Ein `null` lädt dazu ein, es später „nur noch
richtig zu befüllen".

## 9. Oberfläche

### 9.1 Events-Tab

Ein drittes Panel `#kieker-results` neben `#bummel-results` und `#kutter-results`
(`app/static/index.html:4293 ff.`), gleiche Grammatik, gleicher Teilen-Knopf.

Inhalt:
- Kopf: Objektart mit Emoji, Zeitraum, Status, bei laufendem Event die eigene Abdeckung
  („4 von 14 Stellen").
- **Die Eingabemaske**: je Stelle eine Zeile mit Name, Zustand (abgedeckt ✓ / offen) und einem
  Zahlenfeld. Speichern je Zeile, sofort, ohne Formular-Absenden.
- Nach der Enthüllung: Rangliste, darunter je Teilnehmer die Aufschlüsselung nach Stellen mit
  Markierung der gewerteten.

**UI-Standards** (`CLAUDE.md`): Die Aufschlüsselung ist eine breite Tabelle → `.table-scroll`
mit `width:max-content; min-width:100%`. Blau bleibt Klickbarem vorbehalten — Zahlen und
Callsigns neutral. Auf dem Zahlenfeld `font-size:16px`, sonst zoomt iOS beim Antippen hinein
(stehende Regel).

### 9.2 Karte

Die Stellen als eigene Ebene mit ihrem Radius als Kreis. Vorbild und Weg stehen bereit:
`app/static/data/platzrunden_de.geojson` wird über `/static/data/` ausgeliefert und in einer
eigenen Pane gezeichnet; der MIME-Typ `application/geo+json` ist in `app/main.py:277` dafür
registriert. Die Kieker-Stellen kommen allerdings aus der Datenbank, nicht aus einer Datei —
sie werden aus der Event-Sicht heraus gezeichnet, der Rest des Musters (eigene Pane, eigener
Ebenen-Schalter) gilt unverändert.

### 9.3 Emoji

`🔭` ist U+1F52D → `app/static/emoji/1f52d.svg`. **Die Datei fehlt** (30 Twemoji-SVGs sind
vorhanden, diese nicht) und ist mit anzulegen; ebenso das Emoji der jeweiligen Objektart
(🦭 = `1f9ad` fehlt ebenfalls). Der Helfer `emoji(name)` (`index.html:8692`) erwartet den
Dateinamen ohne Endung.

### 9.4 Statistik-Kacheln

Die Sektion „Spezial-Events" behandelt Kutter und Bummel bewusst gleichrangig
(`docs/superpowers/specs/2026-07-07-spezialevents-kpi-statistiken-design.md`). Ein dritter
Typ gehört dort in derselben Kachel-Grammatik hinein: *Eventart · Teilnahmen · Stellen
abgedeckt · Ø Güte*. Dafür kommt `aggregate_kieker_kpis(views)` neben die beiden bestehenden
Aggregatfunktionen. Reine Summierung über eingefrorene Sichten, keine Neurechnung.

## 10. Kalender

Marker `friesenkieker` in Titel oder Beschreibung, genau wie `friesenkutter` in
`parse_route` (`app/calendar_sync.py:147`). Der Termin legt jedoch **nur die Hülle** an —
Name, Zeitraum, Push.

**Die Stellenliste kommt immer aus dem Admin, nie aus dem Kalender.** Der Kutter kann seine
Fracht aus einer Beschreibungszeile lesen, weil „1000 kg Krabbenbrötchen" ein Satz ist. Eine
Liste von vierzehn Koordinaten ist keiner. Ein Event ohne Stellen ist inaktiv, wird nicht
gewertet und im Admin sichtbar als „noch nicht bestückt" geführt.

`route` bleibt leer — der Kieker hat keine Strecke. Die Plausibilitätsprüfung
`_route_is_plausible`, die `is_bummel` und `is_transport` an mindestens zwei Flugplätzen
festmacht, darf für `is_kieker` **nicht** übernommen werden: Sie würde jeden Kieker-Termin
abweisen, in dem kein ICAO steht. Das ist beim Einbau die naheliegendste Falle.

## 11. Push und Latches

Zwei Ereignisse, beide über den bestehenden Events-Kanal (`_check_bummel_reveals` ist die
Vorlage, `app/poller.py:1539`):

- **Start** — die erste Abdeckung eines beliebigen Piloten setzt `started_at`.
  „FRS49N hat den Kieker eröffnet."
- **Enthüllung** — `revealed_at`. „Die Zählung ist ausgewertet! 🔭"

Der Job läuft im selben Takt wie `_check_bummel_reveals`. Er rechnet dabei die Abdeckung —
also gilt auch hier: **keine Datenbank-Transaktion um einen Netzabruf**, und die Rechnung
gehört nicht in den Poll-Takt der Positionsverarbeitung.

## 12. Ehrlichkeit: Der Kieker ist nicht manipulationssicher

Das gehört an eine sichtbare Stelle, weil es sonst später als Fehler gemeldet wird.

**Stufe 1** zählt fest gebaute Szenerie. Die Wahrheit steht damit prinzipiell auch in
OpenStreetMap, in Wikipedia oder im Simulator selbst, wenn man ihn im Slew-Modus abfliegt.
Wer nachschlagen will, kann nachschlagen. Die Abdeckungsprüfung verhindert genau eine Sache:
dass jemand gewinnt, **ohne zu fliegen**. Mehr verspricht sie nicht.

**Stufe 2** verschiebt das, hebt es aber nicht auf: Der Server erzeugt die Lage, also kennt
nur er sie — aber er muss sie dem Paket des Piloten mitteilen, damit es die Objekte setzen
kann. **Die Lage-Schnittstelle ist die Wahrheit in maschinenlesbarer Form.** Kein
Verschlüsselungskniff ändert daran etwas; der Rechner, der die Objekte zeichnet, muss wissen,
wie viele es sind.

Eine echte Erschwerung gibt es trotzdem, und sie ist einzubauen:

> **Die Lage wird nach Nähe ausgeliefert.** Das Paket fragt mit seiner aktuellen Position und
> bekommt nur die Objekte im Umkreis von *n* km. Wer die vollständige Wahrheit will, muss
> jede Stelle anfliegen — also genau das tun, was die Aufgabe verlangt.

Das ist keine Sicherheit, sondern ein Preis. Für eine Gruppe befreundeter Piloten ist er
angemessen; als Sicherheitsversprechen wäre er gelogen.

**Der Rückfallweg aus Issue #20 — der Server erzeugt Szenerie-XML, das Paket holt sie ab — ist
in diesem Punkt deutlich schlechter:** Dort liegt die vollständige Objektliste danach als
lesbare Datei auf der Platte des Piloten. Wer sie öffnet, hat alle vierzehn Zahlen, ohne einen
Meter zu fliegen. Das ist neben dem Handgriff vor dem Flug und dem Wegfall von MSFS 2020 der
dritte Grund, warum dieser Weg nur der Rückfall ist.

## 13. Stufe 2 — das Paket `msfs-kieker/`

**Nicht Gegenstand der Umsetzung dieser Spec.** Hier steht der Vertrag, damit Stufe 1 ihn
nicht verbaut.

### 13.1 Ort

`msfs-kieker/` im friesenspy-Repo, neben `msfs-panel/`. Begründung ist die Kopplung: Das Paket
holt seine Lage vom Server, und ein eigenes Repo ließe Paketversion und Server-Schnittstelle
auseinanderdriften — dasselbe Problem, das das Kniebrett schon einmal hatte („Erforderlich ist
mindestens 2.0.0"), nur über zwei Repos verteilt.

Der Einwand dagegen ist berechtigt und wird nur vorläufig überstimmt: Ein Paket mit
3D-Modellen bläht ein Repo dauerhaft auf. **Solange Boote gezählt werden, enthält es kein
einziges Modell** — MSFS bringt Boote als SimObjects mit. Schwer wird es erst mit den Robben,
und dann weiß man auch, wie schwer.

`msfs-panel/` liefert das Muster: `PackageSources/`, ein `build-package.ps1`, das unter
Windows läuft, und ein ZIP, das **nicht im Docker-Image steckt**, sondern einmal je Release
neben die Datenbank gelegt und über eine gate-geschützte Seite ausgeliefert wird
(`_efb_zip_path`, `app/main.py:572`). Der Kieker folgt dem, mit eigenem Pfad und eigener
Seite.

### 13.2 Warum SimObjects und nicht die vorhandenen Tiere

Im Szenerie-Repo `regover13/east-frisian-islands-counting-seals` steht die Antwort im
Quelltext (`generate_seals.py:22`):

```python
# Library Object GUIDs from Hummods.BGL (human-library-animated)
# These are the PLACEABLE GUIDs (not SimObject model GUIDs)
```

Ein **LibraryObject** existiert nur als GUID in einer Modellbibliothek und hat keinen Namen,
unter dem etwas von außen es setzen könnte. `SimConnect_AICreateSimulatedObject` erwartet
einen **Container-Titel** aus einer `sim.cfg`. Fremde Bibliotheksmodelle lassen sich nicht
nachträglich zu SimObjects erklären — eigene schon. Szenerie ist überdies statisch: Sie wird
beim Laden gelesen und ist zur Laufzeit nicht änderbar. Beides zusammen schließt den
Szenerie-Weg für ein serverseitig gesteuertes Event aus.

**Verworfen bleibt vPilot**, aus zwei unabhängigen Gründen: Es zeichnet ausschließlich, was
das VATSIM-Netz meldet — ein Objekt erschiene nur, wenn sich etwas als Flugzeug an dieser
Position einloggt, was gegen den Code of Conduct verstößt — und eine Injektionsschnittstelle
gibt es ohnehin nicht.

### 13.3 Die Schnittstelle

```
GET /api/kieker/event/{id}/lage?lat=<breite>&lon=<laenge>&umkreis_km=<n>
Authorization: Bearer <kieker-schluessel>
→ { "objekte": [ {"titel": "Boat_Small", "lat": …, "lon": …, "kurs": 210} ] }
```

Der Schlüssel ist ein Zufallswert, den der Pilot einmal aus der Weboberfläche in die
Konfigurationsdatei des Pakets kopiert (`kieker_schluessel(schluessel PK, cid, created_at,
last_seen)`). Ein nativer Spawner kann den Geräteweg des Kniebretts nicht mitbenutzen — der
lebt in MSFS' eigenem Speicher, nicht auf der Platte. **Der Schlüssel ist ein Zugangsgeheimnis
und muss im Admin widerrufbar sein**, genau wie eine Panel-Gerätebindung.

### 13.4 Die vier Messfragen

Sie sind vom Nutzer am Simulator zu beantworten; ich kann sie hier nicht klären, und ein
geratener Wert wäre schlimmer als eine offene Frage.

1. Erreicht `AICreateSimulatedObject` ein **WASM-Modul** im Paket? Wenn ja, entfällt das externe
   Programm ganz — die WASM-Fassung von SimConnect kennt nur einen Teil des Befehlsvorrats.
2. Welche **SimObject-Kategorie** passt für ein liegendes Tier, ohne dass der Simulator ihm ein
   Verhalten andichtet? (Für Boote stellt sich die Frage nicht.)
3. Gibt es **`exe.xml`** in MSFS 2024 noch als Autostart-Weg?
4. Wie viele Objekte verträgt der Simulator, bevor es ruckelt?

**Der erste Schritt ist billig und beantwortet den Kern:** ein mitgeliefertes Boot per
SimConnect an eine Wattkoordinate setzen und nachsehen, ob es dort steht. Liegt das Boot auf
der Sandbank, lohnt sich alles Weitere; liegt es nicht dort, ist Stufe 1 trotzdem fertig und
spielbar.

## 14. Tests

`tests/test_kieker.py` — Geometrie und Wertung, rein, ohne Datenbank:

- `test_strecke_deckt_uebersprungene_stelle_ab` — zwei Stichproben 1,1 km auseinander, die
  Stelle mit 500 m Radius genau dazwischen. **Der Punkttest schlüge fehl, der Streckentest
  greift.** Dieser Test ist die Existenzberechtigung von Abschnitt 4 und muss ohne die
  Streckenrechnung rot werden.
- `test_luecke_verbindet_nicht` — Norderney 18:00, München 19:00. Keine Stelle dazwischen
  gilt als abgedeckt.
- `test_hoehe_ueber_deckel_deckt_nicht_ab` — direkt über der Stelle, aber in 5000 ft.
- `test_hoehe_wird_am_fusspunkt_interpoliert` — Steigflug über die Stelle hinweg, Endpunkte
  darunter und darüber.
- `test_fehler_gedeckelt` — Wahrheit 5, Schätzung 100 → Fehler 1,0, nicht 19,0.
- `test_null_objekte_zaehlbar` — Wahrheit 0, Schätzung 0 → Fehler 0.
- `test_nicht_abgedeckte_stelle_zaehlt_voll` — Schätzung ohne Überflug wird nicht gewertet.
- `test_wertungspunkte_nimmt_die_besten` — 14 Stellen, `wertungspunkte=6`.
- `test_gleichstand_gleicher_rang`.

`tests/test_kieker_api.py`:

- `test_wahrheit_fehlt_vor_enthuellung` — **rekursiv** über das serialisierte JSON, nicht nur
  über die oberste Ebene.
- `test_fremde_schaetzung_unsichtbar`.
- `test_schaetzung_nach_dtend_abgewiesen`.
- `test_schaetzung_ohne_cid_abgewiesen`.
- `test_endpunkte_sind_nicht_async` — an den Funktionsobjekten geprüft
  (`inspect.iscoroutinefunction`), nicht per Textsuche. Vorbild: `tests/test_kutter_eventloop.py`.
- `test_admin_vorschau_schreibt_keinen_snapshot`.

`tests/test_calendar_sync.py`: `test_kieker_marker_ohne_icao_erkannt` — der Termin ohne
Flugplatzangabe muss durchkommen (Abschnitt 10).

**Jeder dieser Tests ist gegen den entfernten Fix gegenzuprüfen** — er muss ohne ihn rot
werden. Die stehende Regel steht in `CLAUDE.md` und hat am 08.09.2026 zwei falsch-grüne Tests
entlarvt.

## 15. Version und Doku

- `app/CHANGELOG.json`: neuer Eintrag oben, **`"highlight": false`** (stehende Regel, ohne
  Ausnahme). Nummer: **v15.0.0** — ein dritter Eventtyp ist ein Major-Schritt, und die Nummer
  ist von `highlight` unabhängig. Siehe Frage 4 in Abschnitt 17.
- `README.md`: eigener Abschnitt im Handbuchteil, dazu der Hilfetext hinter dem `?` —
  ein Feature-Commit ohne beides gilt in diesem Projekt als unfertig.
- `docs/api.md`: alle Endpunkte aus Abschnitt 8.
- `docs/architecture.md`: Wertungsformel, Deckungsprüfung, Snapshot-Art `kieker`.
- Der Kommentar an `_PROGRESS_SNAPSHOT_VERSION` wird um den dritten Typ ergänzt (Abschnitt 7.4).

## 16. Bewusst nicht im Umfang

- **Kein Badge-PNG in Stufe 1.** `app/badge.py` rendert heute `total_min` und `delta` — eine
  Blockzeit-Semantik. Eine Güte in Prozent ist eine dritte Bedeutung im selben Bild; das ist
  Politur und darf den Eventtyp nicht aufhalten. Stufe 3.
- **Keine Lagen je Pilot in Stufe 1.** Das Feld `lage_modus` existiert und steht auf
  `gemeinsam`; die zweite Einstellung wird erst mit dem Paket sinnvoll, weil vorher niemand
  eine Lage erzeugt.
- **Keine Streckenabdeckung.** Das ist #22 und bleibt es. Die Geometrie aus Abschnitt 4 ist so
  gewählt, dass sie dort weiterverwendbar ist — mehr nicht (YAGNI).
- **Keine KI-Sprüche.** Der Kutter hat sie; ob der Kieker sie braucht, entscheidet sich, wenn
  er ein paarmal gelaufen ist.
- **Kein Umbau am Szenerie-Repo.** `east-frisian-islands-counting-seals` ist für sich fertig:
  Robben an den Stränden für jeden, der da langfliegt, auch ohne Event. Beisteuern wird es die
  **14 von Hand im World Editor kalibrierten Koordinaten** — das ist die eigentliche Arbeit
  darin und die Startliste für einen Robben-Kieker.
- **Die vier falschen ICAO-Codes in `seal_colonies.json`** bleiben liegen. Das Feld steuert
  dort nichts, und der Kieker legt es gar nicht erst an (Abschnitt 5).

## 17. Offene Fragen

Nummeriert, damit du mit „mach 2 und 5" antworten kannst.

1. **Stimmt die Staffelung?** Stufe 1 zählt fest gebaute Szenerie (Windräder, Schiffe an der
   Pier) und braucht kein Addon. Damit wäre ein Kieker sofort spielbar und die ganze Mechanik
   unter echten Bedingungen erprobt, bevor irgendwer etwas installiert. Oder willst du den
   Eventtyp ausdrücklich erst zusammen mit den gesetzten Objekten haben?

2. **Die Wertungsformel** (Abschnitt 3.2): relativer Fehler je Stelle, bei 100 % gedeckelt,
   gemittelt, als Güte in Prozent. Ist das die Wertung, die du willst — oder soll der Sieger
   wie beim Bummel über den Abstand zu einem *Gruppenschnitt* ermittelt werden, sodass es gar
   keine hinterlegte Wahrheit braucht?

3. **Der Korridor:** 1 km seitlich, 2000 ft MSL, **keine** Geschwindigkeitsgrenze
   (Begründung in 4.1). Zu großzügig? Ich habe bewusst weit angesetzt, weil die gemeldete
   Höhe barometrisch ist und um Hunderte Fuß danebenliegen kann.

4. **Versionsnummer:** Ich schlage **v15.0.0** vor — dritter Eventtyp. Der Haken `highlight`
   bleibt in jedem Fall aus, das ist deine Entscheidung allein. Lieber v14.30.0?

5. **Board-Login:** Ohne aktives Forum-SSO kann niemand eine Schätzung eintragen (Abschnitt 6).
   Ist es dauerhaft an? Wenn nicht, brauchen wir einen zweiten Eingabeweg — und dann wäre die
   Frage, welchen.

6. **Wer trägt die Wahrheit ein?** In Stufe 1 der Admin von Hand. Bei Windrädern ist das
   Abzählen einer Karte; bei Schiffen an einer Pier musst du selbst hinfliegen und zählen.
   Reicht dir das, oder soll die erste Ausprägung etwas sein, dessen Zahl du ohnehin kennst?

7. **Das erste Event.** Wenn Stufe 1 gebaut wird: Welche Objekte, welche Stellen? Die
   ostfriesischen Offshore-Windparks liegen nahe (Riffgat, Alpha Ventus, Nordergründe —
   alle gut fliegbar von EDWR/EDWG aus, feste Anlagenzahlen, und über Wasser stimmt MSL ≈ AGL
   exakt).

8. **Der Probeflug für Stufe 2** (ein mitgeliefertes Boot per SimConnect an eine
   Wattkoordinate setzen) braucht deinen Simulator, nicht meinen Server. Willst du ihn
   machen, bevor Stufe 1 gebaut wird — oder unabhängig davon, wann es dir passt?
