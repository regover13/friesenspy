# 🌉 Das Brügge-Protokoll

**Der Vertrag zwischen dem FriesenSpy-Server und einer Brügge im Simulator.**
Verbindlich für alle Umsetzungen — MSFS 2020, MSFS 2024, X-Plane 12.

> Stand 11.09.2026 · Protokollfassung **1** · ✅ **vom Nutzer abgenommen** — noch nicht umgesetzt
> Grundlage: GitHub-Issue [#25](https://github.com/regover13/friesenspy/issues/25) und die
> Probeflüge in [`probe-msfs/ERGEBNIS.md`](probe-msfs/ERGEBNIS.md) und
> [`probe-xplane/ERGEBNIS.md`](probe-xplane/ERGEBNIS.md).

---

## Warum dieses Dokument zuerst entsteht

Es ist das einzige Stück, das **alle drei** Brüggen teilen. Ein Fehler darin kostet dreimal,
und jede Korrektur kostet ein Client-Release — einen Windows-Build und eine Verteilung an
61 Piloten. Ein Server-Release kostet einen Push.

Daraus folgt das Leitbild, und alles Weitere folgt aus ihm:

> **Die Brügge ist dumm. Alle Klugheit bleibt auf dem Server.**

Die Brügge fragt: *„Ich bin hier — was soll um mich herum stehen?"* Der Server antwortet mit
einer Liste. Die Brügge stellt sie hin. Sie weiß nicht, ob gerade gezählt, gesucht oder
gerätselt wird. Ein neuer Eventtyp braucht deshalb **keine** Änderung an der Brügge und kein
neues Paket beim Piloten.

---

## 1. Ein Endpunkt, beide Richtungen

```
POST /api/bruegge/melden
Content-Type: application/json
```

**Kein `Authorization`-Kopf, aber eine Kennung.** Die Brügge weist sich nicht aus — sie meldet
eine Position, und der Server sucht sich den Piloten dazu (Abschnitt 5). Was sie trotzdem
mitschickt, ist eine selbst erzeugte, dauerhafte `kennung`: **kein Geheimnis, sondern ein
Wiedererkennungszeichen.** Was sie leistet, steht in Abschnitt 5 unter „Die Kennung
beschleunigt, sie autorisiert nicht".

Die Brügge muss ohnehin sagen, wo sie ist, damit der Server weiß, was um sie herum stehen
soll. Position hinauf und Objekte hinunter in einer Anfrage ist deshalb nicht gespart, sondern
die natürliche Form.

### Hinauf

```jsonc
{
  "protokoll": 1,
  "simulator": "msfs2024",        // msfs2020 | msfs2024 | xplane12
  "bruegge_version": "1.0.0",
  "kennung": "a3f9c1e0…",        // dauerhaft, je Installation -- s. unten
  "kann": ["tier_gross", "bauwerk", "fahrzeug", "boot_klein"],

  "lage": {                        // der Stand JETZT -- maßgeblich für "soll"
    "lat": 53.7863, "lon": 7.9104,
    "alt_msl_ft": 1348.9,
    "alt_agl_ft": 12.3,           // null, wenn der Simulator sie nicht kennt
    "gs_kt": 0.0,
    "kurs": 210.4,
    "vs_ft_min": 0.0,             // Steig-/Sinkrate -- der Server braucht sie, s. unten
    "am_boden": true
  },

  "spur": [                        // die Punkte seit der letzten Meldung, ältester zuerst
    { "alter_s": 1.9, "lat": 53.7861, "lon": 7.9099, "alt_msl_ft": 1347.1,
      "gs_kt": 0.0, "kurs": 210.1 },
    { "alter_s": 0.9, "lat": 53.7862, "lon": 7.9102, "alt_msl_ft": 1348.0,
      "gs_kt": 0.0, "kurs": 210.3 }
  ],

  "steht": [                       // wie es JEDEM Objekt aus "soll" ergangen ist
    { "id": "k7-3-a", "zustand": "steht", "hoehe_ft": 1297.0, "seit_s": 143 },
    { "id": "k7-3-b", "zustand": "fehlgeschlagen", "fehler": "NAME_UNRECOGNIZED" },
    { "id": "k7-3-c", "zustand": "verschwunden", "seit_s": 12 }
  ]
}
```

#### `lage` ist die aktuelle Position des Piloten — sie geht immer mit

**Das ist keine Zugabe, sondern der Kern der Meldung.** Bei *jeder* Anfrage trägt die Brügge
die Position hinauf, an der der Pilot in diesem Augenblick steht oder fliegt — unabhängig
davon, ob gerade ein Event läuft, ob Objekte in der Nähe stehen oder ob überhaupt etwas
zurückkommt. Der Server braucht sie ohnehin, um `soll` zu füllen.

**Damit ist die Brügge die bessere Positionsquelle als der VATSIM-Feed** und löst
[#23](https://github.com/regover13/friesenspy/issues/23) für ihre Nutzer mit ein: Wer sie
laufen hat, ist in Echtzeit auf der Karte, ohne dass das Kniebrett offen sein muss. Die
Felder decken sich mit denen, die das EFB-Panel heute schon aus dem Simulator liest
(`msfs-panel/…/FriesenSpy.tsx`, `POSITION_INTERVALL_MS`).

#### ⚠ `vs_ft_min` ist keine Zugabe — ohne sie reißt die Zuordnung im Steigflug

**Nachgetragen am 11.09.2026, nach dem ersten echten Flug.** Der Server rechnet die
Höhenschranke aus der Steig-/Sinkrate: Ein steigendes Flugzeug **muss** von seiner
VATSIM-Höhe abweichen, weil der Feed 29 Sekunden alt ist.

| Steigrate | Abweichung nach 29 s | Schranke (Faktor 2) |
|---|---|---|
| 0 (Reiseflug) | 0 ft | 300 ft (Untergrenze) |
| 700 ft/min | 338 ft | 677 ft |
| 1500 ft/min | 725 ft | 1450 ft |

**Fehlt das Feld, rechnet der Server mit 0 und bekommt die Untergrenze von 300 ft** — und
ein normaler Steigflug reißt sie. Genau das ist im ersten Flug passiert: Die Zuordnung stand,
solange das Flugzeug am Boden war, und fiel beim Steigen.

**Und sie riss zweimal, nicht einmal.** Die abgelehnten Meldungen schrieben die gemerkte
Position nicht fort, der Abstand dazu wuchs, und schließlich löste ein *Phantom-Sprung* die
Zuordnung vollends (s. Sprungregel oben). Ein fehlendes Feld erzeugte damit einen Fehler, der
wie ein ganz anderer aussah.

Eine Brügge, die die Rate nicht liefern kann, schickt `0` — dann gilt die Untergrenze, und
das Matching funktioniert im Reiseflug weiterhin.

#### `spur` trägt die Auflösung, die `lage` allein nicht schafft

**Die Brügge liest ihre Lage jede Sekunde — unabhängig davon, wie oft sie sendet.** Was
zwischen zwei Anfragen anfällt, geht als `spur` mit.

Beim Regeltakt von 1 s (Abschnitt 6) ist `spur` deshalb leer oder trägt einen Punkt. **Sie ist
die Rückfallebene für den gedrosselten Fall:** Setzt der Server `naechste_frage_in_s` auf 5
oder 10, kommen fünf bzw. zehn Punkte in einer Anfrage — der Track bleibt sekundengenau, auch
wenn seltener gesendet wird. Ohne `spur` verlöre jede Drosselung unwiederbringlich
Auflösung.

`alter_s` ist das Alter des Punktes in Sekunden **zum Zeitpunkt des Absendens**, nicht eine
Uhrzeit. Der Server rechnet es gegen seine eigene Empfangszeit auf — damit hängt nichts an
der Systemuhr des Piloten, die falsch gehen darf.

`spur` darf leer sein: bei der ersten Meldung, nach einer Pause, oder wenn die Brügge nicht
sammeln kann. Der Server kommt dann mit `lage` allein aus.

#### Flüssig oder aktuell — ein Zielkonflikt, den erst der 1-s-Takt auflöst

**Sobald gedrosselt wird, muss die Karte sich entscheiden.** Wer die Spur abspielt, bewegt das
Flugzeug im Sekundentakt — zeigt aber dauerhaft eine Position, die so alt ist wie der Takt.
Bei `t=2` erscheint der Punkt von `t=0`, bei `t=3` der von `t=1`.

Genau deshalb ist der Regeltakt 1 s und nicht 2 s: **Dort stellt sich die Frage gar nicht.**

Gerechnet bei 90 kt (rund 46 m/s):

| | bewegt sich | Sprungweite | Alter des Gezeigten |
|---|---|---|---|
| heute, VATSIM-Feed | alle 15 s | ~700 m | 0 → 15 s |
| Brügge 2 s, Spur **abgespielt** | **jede Sekunde** | ~46 m | **durchgehend 2 s** |
| Brügge 2 s, nur **neuester** Punkt | alle 2 s | ~93 m | 0 → 2 s |
| Brügge **1 s** | jede Sekunde | ~46 m | 0 → 1 s |

**Nur der 1-s-Takt löst den Konflikt auf**, statt ihn zu verschieben — der Gewinn ist nicht
nur „eine Sekunde", sondern die Möglichkeit, flüssig *und* aktuell zu sein. Die beiden
mittleren Zeilen beschreiben, was eine Drosselung kostet; sie ist damit nicht gratis, sondern
eine bewusste Notbremse.

**Eine Abschwächung gibt es.** `lage` wird **beim Absenden frisch gelesen** und ist damit
nicht Teil des Rückstands — nur die Punkte in `spur` sind älter. Wer den Marker auf `lage`
setzt und `spur` nur für die gezeichnete Linie nimmt, bekommt die aktuellste Position und
einen vollständigen Track; er zahlt mit dem gröberen Sprung des Markers.

**Diese Wahl gehört ins Frontend und kann später fallen.** Das Protokoll liefert beide
Möglichkeiten aus denselben Daten — es legt sich hier bewusst nicht fest.

⚠ **Nicht interpolieren, abspielen.** Leaflets Bewegungsanimation ist in dieser App bewusst
abgeschaltet (`app/static/index.html:11828`): *„in Coherent GT genau die Sorte Dauerbewegung,
die uns schon einmal Flackern beschert hat."* Gerechnete Zwischenschritte führen dorthin
zurück; echte Messpunkte nicht.

⚠ **Für den Server:** Diese Punkte gehören **nicht** nach `position_history` — die Tabelle
wird nie aufgeräumt, und eine dichtere Reihe verschiebt Aufsetz- und Abstellpunkte in
`canonicalize_legs`. Bummel-Blockzeiten würden sich rückwirkend ändern, je nachdem wer eine
Brügge laufen hatte. Die Begründung steht ausführlich in #23, Fundstück 2.

#### ⚠ Beim Laden springt die Position — und die Brügge darf das nicht melden

**Gemessen am 11.09.2026, in drei Anläufen gelernt.** Wer nach dem Start eines Simulators die
eigene Lage abfragt, bekommt nicht sofort den geladenen Flug:

| | was ankam | |
|---|---|---|
| Sekunden 1–5 | `0.00000 / 90.00763` | der SimConnect-Nullpunkt |
| Sekunde 9 | `47.51893 / -122.29450` | **Seattle** — der Standard-Startpunkt von MSFS |
| danach | `53.78226 / 7.92593` | Wangerooge, der tatsächlich geladene Flug |

**Jeder dieser Werte sieht für sich vernünftig aus.** Seattle ist eine gültige Koordinate mit
gültiger Geländehöhe; nichts daran verrät, dass der Pilot dort nie war.

**Die Brügge darf solche Punkte weder in `lage` noch in `spur` schicken.** Was sonst geschähe:

- Der **Positionsmatch** liefe gegen Seattle — er fände niemanden, aber der Server rechnete
  ihn bei jeder Meldung neu, weil keine Zuordnung zustande kommt.
- Der **Track** bekäme einen Sprung über 8.000 km. In `position_history` gehören diese Punkte
  ohnehin nicht (s. oben), aber auch die Karte zeigte eine Linie quer über den Atlantik.
- Objekte würden **am falschen Ort gesetzt** — genau das ist im Probeflug dreimal passiert.

**Die Regel: gemeldet wird erst, wenn die Lage ruhig ist.** Zwei aufeinanderfolgende Messungen
müssen weniger als **500 m** auseinanderliegen. Bei 1-Sekunden-Takt liegt selbst ein sehr
schnelles Flugzeug darunter — 600 kt sind 309 m/s.

⚠ **Nicht auf bekannte Fehlwerte prüfen.** Der erste Anlauf verwarf `0/90` und lief in Seattle
hinein; eine Liste deckt immer nur die Orte ab, die schon aufgefallen sind. Der Sprung
dagegen verrät den Ladevorgang, ohne dass man einen einzigen Ort kennen muss.

**Dasselbe gilt nach jedem Slew und jedem Flugwechsel** — beides erzeugt denselben Sprung, und
beides kommt im Alltag häufiger vor als ein Simulatorstart.

#### Wie die Position zum VATSIM-Flug findet

**Die Zuordnung entsteht im Server aus der gemeldeten Position** (Abschnitt 5) und mündet in
eine CID — `live_positions` ist nach CID geschlüsselt (`app/database.py:77`). Die Brügge
schickt **nichts mit, was einen Piloten benennt:** keine CID, kein Callsign, keine Flugnummer.
Sie weiß nichts von VATSIM und nichts von Flugplänen.

**Die `kennung` ist davon ausgenommen — und sie benennt auch niemanden.** Sie ist eine
Zufallsfolge ohne Bedeutung; erst der Server verknüpft sie mit einer CID, und zwar allein
über die Position. Beim allerersten Mal sagt sie gar nichts aus, danach nur noch: *dieselbe
wie vorhin*. Der Unterschied zu einem Ausweis ist, dass die Prüfung trotzdem stattfindet —
s. „Die Kennung beschleunigt, sie autorisiert nicht“.

**Die Rollen sind verschieden und ergänzen sich:**

| | liefert |
|---|---|
| **VATSIM-Feed** | Identität: Callsign, Flugplan, Route, Flugregeln, Muster |
| **Brügge** | Position: genauer, dichter, aktueller |

⚠ **Ein Fehler, der sonst sicher einträte:** Der Poller schreibt alle 15 s
`INSERT OR REPLACE INTO live_positions` (`app/database.py:2280`). Schriebe die Brügge in
dieselbe Zeile, **überbügelte der nächste Poll die genaue Position mit der groben** — und zwar
dreimal je Minute. Die Karte ruckelte zwischen zwei Quellen hin und her.

**Also:** Die Brügge-Position gehört in eine **eigene** Ablage
(`bruegge_positions(cid PK, lat, lon, alt_msl_ft, gs_kt, kurs, gemeldet_am)`), und `/api/live`
mischt beim Ausliefern: Ist der Brügge-Punkt jünger als eine kurze Frist, hat er Vorrang;
sonst zählt der VATSIM-Punkt. `live_positions` bleibt dem Poller allein, wie es heute ist.

#### Ohne VATSIM geschieht nichts — und das ist zugleich die Sparregel

**Nutzerentscheidung vom 11.09.2026:** *„Das braucht es nicht. Kein Matching, keine Anzeige."*

Meldet eine Brügge, während die CID **keine** Zeile in `live_positions` hat, dann ist der
Pilot nicht auf VATSIM — der Poller löscht die Zeile beim Ausloggen
(`app/database.py:2299`). Der Server tut dann **nichts**:

```
kein VATSIM  →  { "protokoll": 1, "naechste_frage_in_s": 60, "gilt_bis_s": 0, "soll": [] }
```

Keine Anzeige, keine Ablage, keine Objekte. Die Brügge räumt ab und fragt im Minutentakt
weiter, bis der Pilot online geht.

⚠ **Eine Ausnahme, und sie ist im ersten Flug erzwungen worden:** Sind Friesen in der Luft,
aber passt keiner, antwortet der Server mit **3 s** statt 60. Ohne diese Unterscheidung
entsteht ein Teufelskreis — ohne Zuordnung meldet die Brügge im Minutentakt, und in einer
Minute fliegt ein Flugzeug so weit, dass die Zuordnung *schwerer* wird statt leichter. Am
Boden fällt das nicht auf; ein stehendes Flugzeug fliegt in einer Minute nirgendwohin.

**Der Takt verrät damit eine Kleinigkeit** — ob gerade Friesen fliegen. Das steht aber
ohnehin im öffentlichen VATSIM-Feed, und über eine *bestimmte* Person sagt er nichts. Die
Nutzlast bleibt in allen Ablehnungsfällen gleich: leeres `soll`, `gilt_bis_s: 0`, kein Grund.

**Dieselbe Antwort gilt, wenn die Position zu niemandem passt** — der Pilot ist auf VATSIM,
aber der Match aus Abschnitt 5 findet keinen eindeutigen Treffer. Für die Brügge ist beides
ununterscheidbar und soll es auch sein: Sie erfährt nicht, ob sie unbekannt ist oder nur
gerade niemand in der Nähe. **Eine Fehlermeldung wäre hier ein Werkzeug** — wer probieren
wollte, welche erfundene Position durchgeht, bekäme vom Server die Rückmeldung dazu.

⚠ **Und es heißt, dass sich das Objektsetzen ohne VATSIM nicht prüfen lässt.** Am 13.09.2026
hat das eine Stunde gekostet: Die X-Plane-Brügge lief nachweislich, meldete sauber, bekam aber
immer ein leeres `soll` — weil der VATSIM-Client des Piloten seinen eigenen Simulator nicht
fand. Dafür gibt es jetzt [`pruefserver.py`](pruefserver.py): Er spielt den Server, und eine
Datei neben dem Plugin biegt die Brügge auf ihn um. **Er prüft nicht, was der Server prüft** —
Zuordnung, Rechtefrage und Drosselung bleiben außen vor.

**Das ist auch die Antwort auf die Lastfrage**, und es trifft genau die richtige Stelle: Die
Prüfung ist ein Blick auf den Primärschlüssel von `live_positions` — sie steht **vor** allem
Teuren. Was dahinter läge, entfällt vollständig:

| Was sonst je Meldung anfiele | ohne VATSIM |
|---|---|
| Geo-Abstände gegen alle Stellen rechnen (`soll`) | entfällt |
| Position schreiben | entfällt |
| `spur` auswerten | entfällt |
| Plausibilitätsprüfung gegen VATSIM | gegenstandslos |

Ein Pilot, der den Simulator mit installierter Brügge laufen lässt, ohne zu fliegen, kostet
den Server damit **eine Indexabfrage je Minute**. Das ist billiger als jede Verbindung, die
heute schon offen steht.

**Ein Nebeneffekt, der zählt:** Damit kann die Brügge gar nicht erst zur Hintertür für eine
Sichtbarkeit werden, die niemand eingeräumt hat. Wer nicht auf VATSIM ist, erscheint nicht —
unabhängig davon, was in seiner Konfigurationsdatei steht.

#### `zustand` — ohne ihn dreht die Brügge endlos im Kreis

**`steht` meldet nicht nur Erfolge.** Jedes Objekt aus `soll` bekommt eine Zeile, auch ein
gescheitertes:

| `zustand` | Bedeutung |
|---|---|
| `steht` | erzeugt, lebt, Lage wird gemeldet |
| `fehlgeschlagen` | Erzeugen abgelehnt — `fehler` nennt den Grund |
| `verschwunden` | war da, meldet nicht mehr (`seit_s` = seit wann) |

#### `hoehe_gemessen` — ab der X-Plane-Brügge 1.0.0, und der Server darf es ignorieren

**Ein `hoehe_ft` ist nicht immer eine Messung.** Die X-Plane-Brügge fragt das Gelände am
Zielort selbst (`XPLMProbeTerrainXYZ`) — aber nur geladenes Gelände antwortet, und X-Plane
hält jeweils nur einen Umkreis geladen. Steht das Ziel außerhalb, bekommt das Objekt
Meereshöhe, und die Meldung sieht dann **genau aus wie ein Wattobjekt auf 0,0 ft**.

Das ist heikel, weil der Server nach Abschnitt 4 gerade daraus schließen soll, ob eine Stelle
taugt: *„meldet ein Objekt über Land 0,0 ft, ist die Stelle für diese Gattung untauglich."*
Ohne dieses Feld wäre das ein stiller Fehlschluss — und zwar einer, der eine brauchbare Stelle
dauerhaft aussortiert.

```jsonc
{ "id": "k7-3-a", "zustand": "steht", "hoehe_ft": 0.0, "hoehe_gemessen": false }
```

`false` heißt also: *„da steht etwas, aber die Höhe ist geraten."* Die Brügge versucht die
Probe jede Sekunde erneut und **rückt das Objekt nach**, sobald sie trifft — in X-Plane geht
das, weil `XPLMInstanceSetPosition` jederzeit erneut aufgerufen werden darf.

**Die MSFS-Brügge sendet das Feld nicht**, und das ist richtig so: Dort gibt es keine
Geländeabfrage am Zielort, also auch nicht die beiden Fälle, die das Feld unterscheidet.

**Warum das kein Beiwerk ist:** Scheitert das Erzeugen — `NAME_UNRECOGNIZED` (die Brügge
kennt den Titel nicht), `TOO_MANY_OBJECTS`, `OBJECT_OUTSIDE_REALITY_BUBBLE` —, dann steht das
Objekt nicht in `steht`, bleibt aber in `soll`. Ohne dieses Feld **versucht die Brügge es jede
Sekunde erneut, für immer**, und der Server erfährt nie, dass die Stelle für diese Brügge
unbrauchbar ist.

**Die Regeln dazu:**

- Nach `fehlgeschlagen` versucht die Brügge es erst wieder, wenn die `id` aus `soll`
  verschwunden und wiedergekommen ist. Der Server entscheidet, wann das ist.
- Bei `verschwunden` setzt die Brügge neu (Abschnitt 2) — das ist der gemessene Fall.

#### Was bei Fehlern geschieht

| Lage | Die Brügge tut |
|---|---|
| `426` — Protokollfassung zu alt | räumt auf und hält an, nennt dem Piloten die Hinweisadresse |
| `429` — Rate-Limit | verdoppelt den Abstand bis 60 s |
| `5xx`, Zeitüberschreitung, kein Netz | behält den letzten Sollzustand, solange `gilt_bis_s` reicht |

**`gilt_bis_s` steht in jeder Antwort** und sagt, wie lange der gelieferte Sollzustand ohne
neue Auskunft gültig bleibt. Danach räumt die Brügge ab. Ohne diese Zahl entschiede jede der
drei Umsetzungen selbst, was bei Netzausfall geschieht — und für die Baake wäre „stehen
bleiben" eine Station, die nie verschwindet.

#### `kennung` — dauerhaft, je Installation, kein Geheimnis

**Hier stand `instanz`: ein Zufallswert je Prozessstart, begründet damit, dass jemand MSFS und
X-Plane gleichzeitig laufen lassen könnte. Der Nutzer hat widersprochen, und zu Recht:**

> *„Zwei Sims gleichzeitig geht gegen 0! Wie will man zwei Flugzeuge gleichzeitig bewegen?
> Außerdem geht nur eine VATSIM-Verbindung."*

Beides stimmt. Der Fall, für den `instanz` gebaut war, existiert praktisch nicht — und der
zweite Satz erledigt ihn endgültig: Ohne zweite VATSIM-Verbindung gibt es keine zweite
Position, der eine zweite Brügge zugeordnet werden könnte.

**An seine Stelle tritt etwas anderes, mit einem anderen Zweck.** Die `kennung` wird
**einmal** erzeugt und bleibt — über Prozessstarts, Sim-Neustarts und Rechner-Neustarts hinweg.
Sie sagt nicht „ich bin Friese 12345", sondern nur: **„ich bin dieselbe wie vorhin."**

**Das Vorbild steht schon im Kniebrett.** Dort erzeugt das Panel eine `device_id` und legt sie
in MSFS' eigener Ablage ab (`SetStoredData`, s. `panel_devices` in `app/database.py:577`).
Heute wird sie **nach einem Forum-Login** an die CID gebunden; morgen entsteht dieselbe
Bindung **über die Position**. Die Kennung selbst ändert sich dabei nicht — nur, wodurch sie
ihren Piloten bekommt.

**Wo sie liegt, ist je Umsetzung verschieden** und keine Protokollfrage: in MSFS' Ablage, in
einer Datei neben dem X-Plane-Plugin, in der Registry. Verloren gegangen ist sie nie ein
Problem — die Brügge zieht eine neue, und der nächste Positionsmatch bindet sie erneut.

#### Die übrigen Felder

`kann` ist die Liste der Gattungen, die diese Brügge beherrscht (Abschnitt 3). Sie wird bei
**jeder** Anfrage mitgeschickt, nicht nur beim ersten Mal — der Server hält keine Sitzung, und
eine zustandslose Meldung übersteht jeden Neustart auf beiden Seiten.

`alt_agl_ft` ist in X-Plane direkt vorhanden (`sim/flightmodel/position/y_agl`). In MSFS gibt
es dafür das SimVar `PLANE ALT ABOVE GROUND` — der „Umweg über die Platzhöhe", der anderswo
beschrieben ist, betrifft das EFB-Panel im Browser, **nicht** SimConnect. Kann eine Brügge das
Feld nicht liefern, schickt sie `null`, und der Server rechnet ohne.

### Hinunter

```jsonc
{
  "protokoll": 1,
  "naechste_frage_in_s": 1,        // Regeltakt, s. Abschnitt 6
  "gilt_bis_s": 300,               // so lange gilt "soll" ohne neue Auskunft
  "soll": [
    { "id": "k7-3-a", "art": "tier_gross", "lat": 53.6612, "lon": 6.9835,
      "kurs": 210, "erwartete_hoehe_ft": null, "auf_boden": 0 }
  ]
}
```

`soll` ist **die vollständige Liste dessen, was jetzt dastehen soll** — kein Strom von
Befehlen. Der Unterschied entscheidet über die Robustheit (Abschnitt 2).

`erwartete_hoehe_ft` darf `null` sein und ist dann „nimm die Oberfläche". Setzt der Server
einen Wert, ist er MSL und die Brügge versucht ihn zu treffen.

### `auf_boden` — die Sonde (seit Brügge 1.2.0)

`auf_boden: 1` weist die Brügge an, das Objekt mit **`OnGround=1`** zu setzen, statt mit einer
gerechneten Höhe. Vorgabe ist `0`.

**Wozu, wenn das Flag aus WASM heraus doch nicht wirkt?** Weil das nur für **ein** Modell
gemessen ist. Am 11.09.2026 landete `Boat01` mit `OnGround=1` bei 49,0 ft, unabhängig vom
gesetzten Höhenwert — ein Boot will aber womöglich auf *Wasser* aufsetzen und scheitert über
Land. Für `tier_gross`, `bauwerk` und `fahrzeug` ist es **ungemessen**.

**Und daran hängt mehr als eine Randfrage.** Setzt auch nur eine Gattung auf, dann meldet sie
danach ihre **tatsächliche** Höhe zurück — das ist die Geländehöhe am **Zielort**, ohne
Höhenmodell und ohne dass jemand hinfliegen müsste:

```
1. Sonde setzen           → { "art": "tier_gross", "auf_boden": 1 }
2. Höhe ablesen           → "steht": [{ "hoehe_ft": 1297.4 }]
3. Sonde weg, Objekt hin  → { "art": "boot_klein", "erwartete_hoehe_ft": 1297.4 }
```

Dass die Rückmeldung die **tatsächliche** Lage trägt und nicht die angeforderte, ist belegt:
Mit `OnGround=1` kam 49,0 ft zurück, obwohl 0 bzw. 500 gesetzt waren.

Ohne diesen Weg bleibt nur, alles auf die Geländehöhe **unter dem Flugzeug** zu setzen — und
die stimmt schon 100 m weiter nicht mehr. Am 12.09.2026 standen zwölf Objekte in einem Raster
von 180 m nebeneinander: eines versunken, eines sauber, eines schwebend, alle auf derselben
angeforderten Höhe.

---

## 2. Der Sollzustand wird abgeglichen, nicht befolgt

> ### ✅ Einmal verteilen genügt — geflogen am 11.09.2026
>
> Die Frage war, ob der Server Objekte **einmal** setzen lassen darf oder ob die Brügge sie
> unterwegs nachsetzen muss, sobald der Pilot in Reichweite kommt. Das Anlegen gelingt bis
> 10.000 km, belegt war die **Sichtbarkeit** aber nur im Nahbereich (1,6 km auf dem Wasser).
>
> **Ein `CruiseShip01`, aus 44,7 km Entfernung vor Norderney gesetzt, war bei 22,1 km
> zweifelsfrei zu sehen** (EDWG→EDWY, MSFS 2024). Der Server darf also verteilen, sobald er
> weiß, wohin der Pilot fliegt — und muss nicht jede Sekunde nachlegen.
>
> ### Und mit einem kleinen Objekt nachgemessen
>
> | Objekt | Länge | gesetzt aus | **sichtbar ab** |
> |---|---|---|---|
> | `CruiseShip01` | ~300 m | 44,7 km | **22,1 km** |
> | `Boat01` | ~8 m | 41 km | **1,0 km** |
>
> Die Einblendreichweite skaliert mit der Größe — **der Befund selbst hängt aber nicht daran:**
> Beide Objekte wurden aus über 40 km gesetzt, beide waren da. Der Simulator vergisst sie nicht.
>
> ⚠ **Für den Kieker ist 1 km die wichtigere Zahl.** Sie sagt, wie nah ein Pilot an eine
> Station heran muss, um überhaupt etwas zu sehen — eine Spielregel, keine technische Randnotiz.
> Stationen dürfen nicht so gesetzt werden, dass man sie nur mit Zufall findet.
>
> ⚠ **Für MSFS 2020 und X-Plane ist das nicht gemessen.** Die Anleitung steht in
> [`probe-msfs/FLUGTEST.md`](probe-msfs/FLUGTEST.md) und gilt für jede Strecke.

Die Brügge vergleicht `soll` mit dem, was sie tatsächlich gesetzt hat, und gleicht in **beide**
Richtungen ab:

| Lage | Was die Brügge tut |
|---|---|
| In `soll`, noch nicht gesetzt | erzeugen |
| In `soll`, gesetzt, lebt | nichts |
| In `soll`, gesetzt, **verschwunden** | **neu erzeugen** |
| Gesetzt, nicht mehr in `soll` | entfernen |

Geht eine Anfrage verloren, hängt das Netz kurz oder startet der Simulator neu, holt die
nächste Antwort den Zustand von allein wieder ein. Bei Befehlen bliebe eine verpasste Löschung
für immer stehen.

**Die dritte Zeile ist gemessen und keine Vorsichtsmaßnahme.** In MSFS 2020 verschwand
zweimal derselbe Aufruf unterschiedlich: einmal nach einer Sekunde spurlos, einmal 600 s
stabil. Eine Brügge, die nach dem Erzeugen nicht mehr hinsieht, liefert dem Piloten ein leeres
Revier und dem Server eine Lüge.

**Also: nach jedem Erzeugen die Lage abonnieren.** In MSFS `RequestDataOnSimObject` auf die
Objekt-ID; bleiben die Meldungen aus oder kommt `EXCEPTION 3 · UNRECOGNIZED_ID`, gilt das
Objekt als fort.

### Die `id` gehört dem Server

Sie ist undurchsichtig für die Brügge — ein Zeichenkettenschlüssel, den der Server vergibt und
wiedererkennt. Die Brügge führt daneben ihre eigene Simulator-ID (`496` in MSFS, ein
`XPLMInstanceRef` in X-Plane) und hält die Zuordnung. **Auf Wertebereiche ist kein Verlass:**
MSFS 2024 vergab achtstellige IDs, MSFS 2020 dreistellige, das WASM-Modul in 2024 begann bei
16384 und in 2020 bei 1.

---

## 3. Der Server spricht in Gattungen, nie in Dateinamen

MSFS kennt Container-Titel, X-Plane kennt `.obj`-Pfade. Sagt der Server `"Boat01"`, ist
X-Plane raus.

**Die Zuordnungstabelle gehört zur Brügge.** Sie kennt ihren Simulator; der Server kennt ihn
nicht. Meldet eine Brügge eine Gattung nicht in `kann`, weicht der Server aus oder lässt die
Stelle aus — er sendet nie ins Leere.

### Der Katalog der Fassung 1

| Gattung | MSFS 2020 + 2024 | X-Plane 12 | Grund |
|---|---|---|---|
| `tier_gross` | `BlackBear` ✅ | `deer_buck.obj` ⚠ | Gelände |
| `bauwerk` | `Windmill` ✅ | `OilPlatform.obj` ⚠ | Gelände |
| `fahrzeug` | `ASO_Ambulance_Japan` ✅ | **gibt es nicht** — s. u. | Gelände |
| `boot_klein` | `Boat01` ✅ | `SailBoat.obj` ✅ | Gelände — **außer MSFS 2020: Meereshöhe** |
| `boot_gross` | `CruiseShip01` ✅ | `Perry.obj` ⚠ | Gelände — **außer MSFS 2020: Meereshöhe** |
| `robbe` (ab 1.4.0) | `ahqa seal moving` ✅ **Community** | — | Gelände |

⚠ **`fahrzeug` stand hier als `lib/airport/vehicles/…` — das war eine Annahme, und sie trägt
nicht.** X-Plane 12 bringt kein Bodenfahrzeug als eigenständige `.obj` mit; was am Flughafen
fährt, liegt in der Szenerie-Bibliothek und ist nur über `XPLMLookupObjects` erreichbar, nicht
über `XPLMLoadObject`. Die X-Plane-Brügge meldet die Gattung deshalb nicht in `kann`. Die
vollständige Tabelle steht in [`OBJEKTE.md`](OBJEKTE.md); dort auch, welche acht Gattungen sie
stattdessen beherrscht.

✅ = gesetzt und im Bild gesehen · ⚠ = Datei auf der Platte nachgewiesen, aber nie gesetzt

### ⚠ `robbe` ist die erste Gattung ohne Bordmodell

Weder MSFS 2020 noch 2024 bringt eine Robbe mit (`OBJEKTE.md`). Die drei Titel kommen aus dem
Community-Paket `human-library-animated` — **und dass `AICreateSimulatedObject` auch einen
solchen Titel findet, ist seit dem 12.09.2026 belegt** (gesetzt, gezeichnet, Screenshot;
Messliste 8). Alle übrigen ✅ oben stammen aus Asobos Bordbestand. Offen ist nur noch, ob das
WASM-Modul denselben Titel auflöst wie der externe Client, mit dem gemessen wurde.

Diese Gattung hat **bewusst keinen Rückfall auf eine andere Art**: Der Pilot zählt sonst
Tiere, hier aber eine *bestimmte Art* — fiele sie still auf `BlackBear` zurück, lieferte der
Kieker eine Zahl, während am Strand Bären liegen. Das ist der Fall, den der Satz oben („Wer
eine bestimmte Art braucht, braucht eine eigene Gattung") bis zum Ende gedacht meint: eine
eigene Gattung **und** kein artfremdes Ausweichen.

**Eine zweite Robbe darf dagegen jederzeit dazu.** Sobald ein eigenes Modellpaket steht,
gehört sein Titel hinter Superspuds: Das Addon zieht, wo es installiert ist, das eigene Modell
überall sonst. Damit wird niemand ausgeschlossen, und wer das Addon hat, bekommt eine bewegte
Robbe — die ganze Bibliothek ist animiert (`walking`/`running`/`moving` im Modellnamen).

**Eine Gattung ist eine Bedeutung, kein Modell.** Welches Tier ein `tier_gross` ist, darf sich
zwischen Simulatoren und zwischen Brügge-Fassungen unterscheiden — der Pilot zählt Tiere, nicht
Bären. Wer eine bestimmte Art braucht, braucht eine eigene Gattung.

**Neue Gattungen brauchen keine Server-Änderung.** Eine neuere Brügge meldet in `kann` einfach
mehr; der Server darf anfordern, was mindestens eine Brügge kann.

⚠ **Für den Admin gilt das nicht — dort steht eine Positivliste** (`_BRUEGGE_GATTUNGEN`,
`app/main.py`), damit ein Tippfehler nicht als stille Nicht-Anforderung endet. Eine neue Gattung
braucht also keinen neuen *Endpunkt*, aber einen Eintrag in dieser Liste und in der Auswahl im
Admin. Bei `robbe` wäre das beinahe übersehen worden: Das Modul hätte sie setzen können, im
Admin ließ sie sich nicht anfordern — und damit nicht messen (`tests/test_bruegge_endpunkt.py`,
`test_robbe_ist_eine_erlaubte_gattung`).

**`kann` wird in der Brügge aus der Gattungstabelle erzeugt, nicht aufgezählt** (ab 1.4.0).
Vorher stand dieselbe Liste zweimal im Modul, und beim Eintragen von `robbe` meldete es
prompt, es könne eine Gattung nicht, die es setzen konnte.

---

## 4. Die Spalte `Grund` ist der wichtigste Messbefund des Probeflugs

**Die Objektart bestimmt, auf welcher Höhe ein Objekt landet — und nicht jede findet die
Oberfläche.** Gemessen am Bodensee auf EDNY Friedrichshafen, Objekte 2,5 km südlich auf dem
See (Spiegel ≈ 1296 ft):

| Titel | Kategorie | gemessene Höhe |
|---|---|---|
| `CruiseShip01` | **Boat** | **0,0 ft** — 395 m unter dem See |
| `Windmill` | StaticObject | 1297,0 ft ✅ |
| `BlackBear` | Animal | 1297,0 ft ✅ |
| `ASO_Ambulance_Japan` | GroundVehicle | 1297,0 ft ✅ |

Daraus die **Grundregel**, die jede Gattung im Katalog trägt:

- **`Grund: Gelände`** — das Objekt findet die Oberfläche, überall. Land, Nordsee, Binnensee.
  `OnGround=1` genügt.
- **`Grund: Meereshöhe`** — das Objekt landet **immer** auf 0 ft MSL, gleich was darunter
  liegt. `OnGround`, `Altitude` und `SetDataOnSimObject` sind wirkungslos.

### ✅ Die Regel gilt für MSFS 2020 — in MSFS 2024 nicht (beides gemessen)

**Hier stand die Regel ohne Simulator, und das war falsch.** Am selben Abend nachgemessen, auf
demselben Platz, an derselben Koordinate:

| | MSFS 2020 | MSFS 2024 |
|---|---|---|
| `Windmill` (Kontrolle) | 1297,0 ft | 1297,1 ft |
| `CruiseShip01` (**Boat**) | **0,0 ft** — 395 m zu tief | **1297,2 ft** — schwimmt |
| `Boat01` (**Boat**) | 0,0 ft über Land | 1297,1 ft |

**Die Kontrollzeile trägt den Beweis:** Der Simulator kannte die Seehöhe in beiden Fällen. Wo
das Boot trotzdem auf 0 liegt, ist es die Kategorie — und das ist nur in MSFS 2020 so.

**Folge für den Katalog:** Die Spalte `Grund` steht **je Simulator**, nicht gemeinsam.

| Gattung | MSFS 2020 | MSFS 2024 | X-Plane 12 |
|---|---|---|---|
| `boot_klein`, `boot_gross` | **Meereshöhe** | Gelände | Gelände (Terrain-Probe) |
| alle übrigen | Gelände | Gelände | Gelände |

**Praktisch heißt das:** Nur in MSFS 2020 darf der Server keine Boote über Land oder
Binnengewässern anfordern. Auf der Nordsee sind sie auch dort brauchbar, weil MSL die
Oberfläche ist — und der FriesenKieker spielt an den Friesischen Inseln. **MSFS 2020 fliegen
laut Nutzer ohnehin nur wenige.**

Der zugrundeliegende MSFS-Fehler ist seit dem 11.05.2022 im DevSupport gemeldet
(*„SimConnect injected Boat underwater"*, Great Lakes) und bis heute ohne Antwort von Asobo.
Der Melder fragte im Juni 2023, ob MSFS 2024 es behebe —
**die Antwort ist, nach dieser Messung: ja.**
<https://devsupport.flightsimulator.com/t/simconnect-injected-boat-underwater/4226>

*(Auf dem Weg hierher stand diese Regel zweimal zu weit gefasst: erst gestützt auf eine
untaugliche Probe aus 800 km Entfernung, dann ohne Simulator-Angabe. Beide Male hat der
Nutzer widersprochen, beide Male zu Recht.)*

### ⚠ In WASM wirkt `OnGround` nicht — gemessen, mit Ausweg

**Vier Aufrufe aus einem WASM-Modul, auf Wangerooge (Boden ≈ 4 ft):**

| angefordert | erreicht | |
|---|---|---|
| `OnGround=1`, `Altitude=0` | **49,0 ft** | ✗ |
| `OnGround=0`, `Altitude=0` | **0,0 ft** | ✅ exakt |
| `OnGround=0`, `Altitude=500` | **500,0 ft** | ✅ exakt |
| `OnGround=1`, `Altitude=500` | **49,2 ft** | ✗ |

**`OnGround=0` wirkt auf die Nachkommastelle genau.** `OnGround=1` setzt nicht auf, und die
angegebene Altitude ändert daran fast nichts — es ist also nicht die Höhe, die ignoriert wird,
sondern `OnGround` tut etwas Eigenes. **Im externen Programm gibt es das nicht** — dort setzt
dasselbe Flag zuverlässig auf, in beiden Simulatoren.

**Der Wert ist ortsabhängig** — auf Wangerooge (Boden 5 ft) landeten die Objekte bei 49 ft,
in Seattle (Boden ~21 ft) bei 122–130 ft, an einem ungeladenen Ort bei 213–216 ft. Er ist am
selben Ort reproduzierbar, folgt aber keiner erkennbaren Regel. **Ein Herausrechnen scheidet
damit aus**; brauchbar ist allein `OnGround=0`.

*(Eine Zwischenmessung ergab 216 ft und schien zu zeigen, dass der Wert schwankt. Sie war
falsch — die Boote standen bei 0°/90° im Indischen Ozean, weil das Modul bei der ersten
Lagemeldung setzte, vor dem Laden der Welt. Belegt in `probe-msfs/ERGEBNIS.md`.)*

#### Der Ausweg steht schon im Protokoll

**Die Brügge kann die Geländehöhe selbst ausrechnen**, aus zwei Werten, die sie ohnehin liest:

```
Geländehöhe  =  PLANE ALTITUDE  −  PLANE ALT ABOVE GROUND
                (alt_msl_ft)       (alt_agl_ft)
```

Beide stehen in `lage` (Abschnitt 1). Eine WASM-Brügge setzt damit **`OnGround=0` und eine
gerechnete Höhe** statt `OnGround=1`.

⚠ **Die Grenze davon:** Das ist die Geländehöhe **unter dem Flugzeug**, nicht am Zielort. Für
ein Objekt wenige hundert Meter daneben ist sie ein guter Anhalt, für eines 5 km weiter nicht
mehr. **Für den FriesenKieker fällt das kaum ins Gewicht** — er spielt an den Friesischen
Inseln, wo Watt und Wasser auf Meereshöhe liegen.

**Und `erwartete_hoehe_ft` bleibt der bessere Weg, wo der Server es weiß** (Abschnitt 1): Was
er einmal aus einer Rückmeldung gelernt hat, kann er beim nächsten Mal mitgeben, statt die
Brügge raten zu lassen.

### Wie der Server davon erfährt

**FriesenSpy hat kein Geländemodell.** Der Server kann nicht wissen, ob an einer Koordinate
Wasser auf Meereshöhe liegt. Deshalb steht in jeder Meldung `steht[].hoehe_ft`: die Höhe, die
das Objekt **tatsächlich** erreicht hat.

Weicht sie deutlich von `erwartete_hoehe_ft` ab, oder meldet ein Objekt über Land 0,0 ft, ist
die Stelle für diese Gattung untauglich — der Server nimmt sie aus der Wertung, statt einem
Piloten etwas zuzumuten, das niemand sehen kann. **Die Rückmeldung ist der einzige Weg dorthin;
Raten wäre der Anfang einer neuen Fehlersuche.**

#### ⚠ Aber nur aus der Nähe — gemessen am 11.09.2026 spätabends

**Dieselbe Koordinate, zwei Entfernungen, 810 ft Unterschied:**

| `CruiseShip01` am Bodensee | Flieger 691 km entfernt | Flieger in der Nähe |
|---|---|---|
| gemeldete Höhe | **2106,5 ft** | 1297,2 ft |

Der Seespiegel liegt bei 1296 ft. 2106 ft entspricht 642 m und gehört zu keinem Punkt des
Sees — aus der Entfernung antwortet der Simulator aus einer groben Geländestufe, nicht aus
geladenem Terrain.

**Der Server darf `hoehe_ft` deshalb nur auswerten, wenn der Pilot in der Nähe ist.** Sonst
sortierte er brauchbare Stellen aus und behielte untaugliche — beides aus Werten, die gar keine
Messung sind. Wie nah „nah genug" ist, ist **nicht gemessen**: Die vorhandene Reihe zeigt
brauchbare Geländehöhen bis 200 km (`probe-msfs/ERGEBNIS.md`, Reality Bubble), der erste
falsche Wert liegt bei 691 km. Dazwischen ist eine Lücke.

**Praktisch entschärft sich das von selbst:** Der Server fordert Objekte in der Umgebung des
Piloten an — weit entfernte gibt es im Betrieb gar nicht. Die Regel schützt gegen den Fall, in
dem jemand später doch einmal auf Vorrat setzt.

---

## 5. Anmeldung: gar keine — der Server erkennt den Piloten an der Position

**Nutzerentscheidung vom 11.09.2026:** *„Wert entsteht bei beiden durch Positionsmatching der
VATSIM-Verbindung eines bereits in FriesenSpy eingeloggten Users. Keine Gerätebindung, kein
Login, keine Weboberfläche mehr!"*

Hier standen nacheinander zwei Entwürfe — eine eigene Tabelle `bruegge_schluessel`, dann ein
Eintrag in `panel_devices`. **Beide sind verworfen.** Die Brügge bekommt **keinen Schlüssel,
keine Konfigurationsdatei und keinen Anmeldeschritt.**

**Nicht verworfen ist die Kennung.** Sie ist etwas anderes als ein Schlüssel: selbst erzeugt
statt vom Server vergeben, öffentlich statt geheim, und sie öffnet nichts — sie sagt nur, wer
schon einmal da war. Was sie leistet, steht weiter unten unter „Die Kennung beschleunigt, sie
autorisiert nicht“.

### Wie die Zuordnung stattdessen entsteht

Die Brügge meldet einfach, was sie sieht. Der Server sucht dazu den passenden Piloten:

```
Meldung: lat/lon/alt/gs/kurs   →   welcher Friese ist in live_positions dort?
                                    genau einer?  → das ist er
                                    keiner / mehrere → keine Zuordnung, nichts geschieht
```

### Die Regeln dafür gibt es schon — `_verkehrZusammenfuehren`

**Nutzerentscheidung:** *„Für das Matching nehmen wir die Regeln, die auch das
Positionsmatching des EFB nutzt."* Das Kniebrett ordnet seit v13.2.0 Sim-Verkehr und
VATSIM-Verkehr einander zu (`app/static/index.html:6026`), und diese Regeln sind nicht
ausgedacht, sondern im Flug erarbeitet. Sie werden übernommen, nicht neu erfunden.

| Regel | Wert | wofür |
|---|---|---|
| Vergleich gegen die **fortgerechnete** VATSIM-Position | `_jetztGerechnet` | holt das Alter des Feeds auf, statt gegen einen veralteten Punkt zu messen |
| Schranke aus der Geschwindigkeit | `_PAARUNG_FAKTOR = 2` | deckt Latenzstreuung, Wind, leichte Kurven |
| Untergrenze der Schranke | `_PAARUNG_MIN_M = 400` | damit ein **stehendes** Flugzeug überhaupt einen Partner findet |
| Eindeutigkeit über den **Vorsprung** | `_PAARUNG_VORSPRUNG = 0.5` | der beste Kandidat muss halb so weit weg sein wie der zweitbeste |
| Zuordnung wird gemerkt | je Sitzung | eine einmal gefundene bleibt |
| Gelöst erst nach Verstößen **in Folge** | `_PAARUNG_LOESEN_TAKTE = 4` | ein einzelner Ausreißer löst nichts |
| Beim Lösen großzügiger als beim Zuordnen | `_PAARUNG_LOESEN_FAKTOR = 3` | zu frühes Lösen bringt das Flackern zurück |

### Und damit löst sich das Mehrdeutigkeitsproblem von selbst

**Hier stand: „Bei Mehrdeutigkeit geschieht nichts" — das war eine schlechtere Fassung einer
Frage, die am 16.08.2026 im Flug schon beantwortet wurde.** Der Kommentar bei
`index.html:5954` hält beide Fehlversuche fest:

> *Mit 400 m Untergrenze lagen auf dem Vorfeld mehrere Flugzeuge im selben Umkreis — nichts
> war eindeutig, also wurde gar nicht zugeordnet. Mit 150 m fand mancher gar keinen Partner
> mehr und blieb namenlos. Beide Male war die Zahl schuld, und beide Male hätte jede andere
> Zahl an anderer Stelle dasselbe Problem gemacht.*

**Ein Verhältnis hat diese Schwäche nicht.** Steht die eine Maschine 20 m von ihrer
VATSIM-Meldung und die nächste 80 m, ist die Zuordnung klar — gleich wo die Schranke liegt.
Sie sagt nur noch, wer überhaupt in Frage kommt; entschieden wird über den Vorsprung.

Dazu kommt das **Merken**: Einmal zugeordnet, bleibt die Zuordnung bestehen, auch wenn der
Pilot später dicht neben einem anderen fliegt. Die Formation, die ich als Verlust beschrieben
hatte, ist damit keiner — die Zuordnung entstand beim Rollen oder Steigen und hält.

**Für die Brügge ist die Aufgabe sogar leichter als im Kniebrett:** Dort werden *viele*
Sim-Flugzeuge *vielen* VATSIM-Meldungen zugeordnet. Hier ist es **eine** gemeldete Position
gegen die Liste der Friesen — dieselben Regeln, ein einfacherer Fall.

⚠ **Die Konstanten liegen heute im Frontend** (`index.html:5948–5971`). Wandert das Matching
in den Server, gehören sie an **eine** Stelle, nicht in zwei Dateien mit zwei Wahrheiten.

### Die Kennung beschleunigt, sie autorisiert nicht

**Nutzerfrage vom 11.09.2026:** *„Beim EFB wird aber der Sim-Key für die Authentifizierung
gespeichert, richtig? Was ist, wenn EFB und Brügge Positionen melden? Auch könnte man das
ständige Neurechnen des Matchings stark reduzieren, weil man über die dann schon gespeicherte
ID matchen kann."*

**Beides trifft zu, und das Protokoll nimmt es auf.** Der Match aus dem Abschnitt darüber
läuft **nicht** bei jeder Meldung neu:

```
erste Meldung einer kennung  →  voller Match gegen alle Friesen in live_positions
                                 Treffer? → bruegge_zuordnung(kennung, cid) merken
jede weitere Meldung         →  cid nachschlagen (ein Indexzugriff),
                                 Position nur noch gegen DIESE eine VATSIM-Meldung prüfen
```

Das ist derselbe Weg, den das Kniebrett schon geht: `_verkehrZusammenfuehren` merkt sich eine
gefundene Paarung und löst sie erst nach `_PAARUNG_LOESEN_TAKTE = 4` Verstößen **in Folge**
(Abschnitt darüber). Die Kennung überträgt dieses Merken vom Sitzungs- auf den Serverzustand.

| | ohne Kennung | mit Kennung |
|---|---|---|
| je Meldung zu prüfen | alle Friesen in der Luft | **eine** Zeile |
| bei 13 gleichzeitig, 1-s-Takt | 13 × 13 Abstände je Sekunde | 13 Abstände je Sekunde |
| EFB und Brügge desselben Piloten | nicht unterscheidbar | zwei Kennungen, zwei Zeilen |

**Der zweite Punkt ist der wichtigere.** Melden EFB und Brügge gleichzeitig, sind es zwei
Quellen für dieselbe CID. Ohne Kennung sieht der Server zwei Positionen und muss raten,
welche gilt; mit Kennung weiß er, welche Quelle welche ist, und kann die genauere vorziehen
oder die ältere verwerfen.

⚠ **Und jetzt die Grenze, die dabei einzuhalten ist.** Eine gemerkte Zuordnung ist eine
**Abkürzung der Rechnung, keine Vollmacht.** Die Prüfung entfällt nicht, sie wird billiger:

- Die Position muss **weiterhin** zur VATSIM-Meldung derselben CID passen. Tut sie das
  wiederholt nicht, fällt die Zuordnung, und der nächste Match beginnt von vorn.
- Loggt die CID von VATSIM ab, fällt die Zuordnung sofort — ohne VATSIM geschieht ohnehin
  nichts.
- Die Kennung allein reicht **nie**, um Positionen zu setzen. Wer eine fremde Kennung stiehlt,
  muss trotzdem die öffentliche VATSIM-Position dieses Piloten treffen — und gewinnt damit
  genau das, was er auch ohne sie gewinnt: nichts.

**Deshalb ist die Kennung kein Geheimnis** und braucht keinen Schutz, kein Ablaufdatum und
keine Übertragungssicherung. Sie unterscheidet sich darin von der `device_id` des Kniebretts,
die heute *doch* ein Zugangsschlüssel ist (`app/database.py:573`: „wer ihn hat, ist als dieser
Nutzer angemeldet"). **Genau diese Eigenschaft verliert sie mit der Umstellung** — was sie
nach der Umstellung noch trägt, ist die Wiedererkennung.

### Die ehrliche Einordnung: das ist Identifikation, keine Authentifizierung

**VATSIM-Positionen sind öffentlich.** Jeder kann den Feed lesen und weiß, wo FRS61 gerade
ist — und diese Position dann selbst melden. Die Zuordnung ist damit nicht fälschungssicher,
und das muss hier stehen, statt in einer Fußnote zu verschwinden.

**Warum es trotzdem trägt:** Die Prüfung lässt nur durch, was zur öffentlichen Position
passt. Ein Fälscher kann deshalb nur **bestätigen, was der VATSIM-Feed ohnehin sagt** — er
gewinnt nichts. Sein einziger Spielraum ist die Toleranz der Prüfung: Zwischen zwei
VATSIM-Punkten könnte er einen falschen Weg behaupten, solange dessen Enden passen.

**Für den Kieker heißt das:** Die Toleranz der Prüfung begrenzt, wie weit sich eine Abdeckung
erschleichen lässt. Das ist eine bewusste Abwägung, keine Lücke — Spec-Abschnitt 12 hält
ohnehin fest, dass der Kieker nicht manipulationssicher ist, und für eine Gruppe von 61
Leuten, die sich kennen, ist der Aufwand die Sache nicht wert.

**Ein Schlüssel hätte daran wenig geändert:** Er hätte in einer Textdatei gelegen, die mit dem
Community-Ordner weiterwandert. Ein Geheimnis, das auf zwanzig fremden Rechnern liegt, ist
keines.

### Wer melden darf: `forum_callsign` ist der Nachweis

**Nutzervorgabe vom 11.09.2026:** *„Ich will vermeiden, dass jemand sich einfach ein
FRS-Callsign setzt und damit fliegt. […] Hier will ich nur authentifizierte CIDs, die auf
VATSIM und mit FRS-Callsign fliegen."*

Hier stand, „eingeloggt" sei serverseitig nicht feststellbar. **Das war zu kurz gesucht.** Der
Login ist zwar zustandslos (`make_user_token`, `app/forum_sso.py:96`), aber er **hinterlässt
eine Spur**:

```sql
forum_callsign (callsign TEXT PRIMARY KEY, cid INTEGER NOT NULL, updated_at TEXT)
```

Diese Tabelle wird bei **jedem** Forum-Login aus dem Forum-Profil gepflegt
(`app/main.py:2740`, Token v2, Feld `cs`). Sie beantwortet mehr als die ursprüngliche Frage:
nicht nur *„war diese CID je angemeldet?"*, sondern **„gehört dieses Callsign laut Forum
diesem Nutzer?"**

### Die drei Bedingungen

1. **Der Pilot steht in `live_positions`** — er fliegt also gerade auf VATSIM, und zwar mit
   Friesen-Präfix (`CALLSIGN_PREFIX`, Vorgabe `FRS`); andere nimmt der Poller gar nicht auf.
2. **Seine CID hat eine Zeile in `forum_callsign`.** Das ist die eigentliche
   Authentifizierung: Die Zeile entsteht nur beim Forum-Login, aus dem Forum-Profil.
3. **Die Position passt** nach den Regeln oben.

### ⚠ Geprüft wird die CID, nicht das Callsign

**Das ist eine bewusste Entscheidung und war zwischenzeitlich anders.** Hier stand, das
gemeldete Callsign müsse in `forum_callsign` stehen und auf dieselbe CID zeigen. **Das
zerbricht beim ersten Callsign-Wechsel** — und der kommt bei fast jedem Friesen genau einmal:
wenn er das `N` verliert und aus `FRS123N` ein `FRS556` wird.

Die Tabelle zieht zwar sauber nach — der Login trägt die Callsigns des Profils ein und löscht
alle anderen Zeilen derselben CID (`app/main.py:2755-2766`). **Aber eben erst beim nächsten
Login.** Wer sein Rufzeichen im Forum ändert und sich danach nicht bei FriesenSpy anmeldet,
fliegt als `FRS556`, während die Tabelle nur `FRS123N` kennt: keine Zuordnung, ohne dass
irgendwo etwas kaputt aussieht.

**Über die CID gibt es dieses Problem nicht.** Sie ist der VATSIM-Kontoschlüssel und ändert
sich nie; welches Rufzeichen daran hängt, ist gleichgültig.

```sql
EXISTS (SELECT 1 FROM forum_callsign WHERE cid = :vatsim_cid)
```

### Der Angriff scheitert trotzdem

| Fall | CID in `forum_callsign`? | Ergebnis |
|---|---|---|
| Fremder setzt sich `FRS99` | **nein** — sein VATSIM-Konto war nie angemeldet | **keine Zuordnung** |
| Fremder nimmt das Callsign eines echten Friesen | **nein** — es zählt seine eigene CID, nicht das getippte Rufzeichen | **keine Zuordnung** |
| Friese nach dem Callsign-Wechsel | **ja** — Zeile hängt an der CID | ✅ |
| Friese, nie bei FriesenSpy angemeldet | nein | keine Zuordnung *(gewollt)* |

**Der Grund ist derselbe wie vorher, nur sauberer:** Das getippte Rufzeichen beweist nichts,
die CID kommt vom VATSIM-Konto. Wer nie per Forum angemeldet war, hat keine Zeile — gleich
welches Callsign er sich gibt.

**Die Callsign-Spalte bleibt trotzdem nützlich**, nur nicht als Schranke: `upsert_forum_callsign`
meldet eine Kollision, wenn ein Callsign die CID wechselt (`app/database.py:9095`) — das ist
ein Hinweis fürs Log, kein Prüfkriterium.

### Der Unterschied zum Kniebrett im Alltag

**Das EFB selbst bleibt, wie es ist** — CID-gebunden über den Forum-Login, **unabhängig vom
Callsign**. Wer als Friese angemeldet ist, benutzt sein Kniebrett auch dann, wenn er gerade
als `DEABC` unterwegs ist. Das soll so bleiben.

**Nur die Positionsmeldung ist strenger**, und das gilt für Kniebrett und Brügge gleich:

| | Kniebrett benutzen | Position melden |
|---|---|---|
| Forum-Login (CID) | nötig | nötig — als Zeile in `forum_callsign` |
| FRS-Callsign auf VATSIM | **nicht** nötig | **nötig** (Präfix, nicht das genaue Rufzeichen) |
| auf VATSIM online | nicht nötig | nötig |

### ⚠ Was das kostet

**Wer gar kein Callsign im Forum-Profil führt, kann nicht melden.** Ohne Eintrag legt der
Login keine Zeile an, und ohne Zeile gibt es keine CID zum Prüfen. Ein *veraltetes* Callsign
schadet dagegen nicht — geprüft wird die CID.

**Entschieden am 11.09.2026:** Dafür wird **keine** Ersatzzeile angelegt (CID ohne Callsign).
Auf die Frage, ob der Login eine solche schreiben soll, kam: *„Das darf eigentlich nicht
vorkommen — also lass es."* Ein Friese ohne Rufzeichen im Profil ist ein gepflegtes Profil
weniger, kein Sonderfall, den das Protokoll abfangen muss.

Der Preis gehört trotzdem in die Anleitung, sonst sucht der erste Betroffene den Fehler in der
Brügge statt im Forum.

**Und der Forum-Login bleibt die einmalige Voraussetzung.** „Keine Anmeldung" heißt: kein
Schlüssel, keine Konfiguration, kein Schritt vor jedem Flug. Es heißt nicht, dass jemand ohne
FriesenSpy-Konto melden könnte.

## 6. Takt

**Der Server bestimmt den Takt, nicht die Brügge** — `naechste_frage_in_s` steht in jeder
Antwort. Das ist die einzige Stellschraube, die nach der Verteilung an 61 Piloten noch
erreichbar ist, und sie darf **je Pilot** verschieden stehen.

### Der Regeltakt ist 1 s — gemessen, nicht geschätzt

Die Frage „warum nicht jede Sekunde?" stand hier zweimal, und die Antwort war beide Male
schlechter als die Frage. **Hier stand als Empfehlung 2 s**, gestützt auf die Annahme, es
könnten 20 Brüggen gleichzeitig melden. Diese Zahl war geschätzt und nie geprüft.

**Am 11.09.2026 in der Produktionsdatenbank nachgesehen** (`position_history`, 30 Tage,
11.318 Minuten mit Flugbetrieb):

| | gleichzeitig in der Luft |
|---|---|
| Spitze, einmal erreicht | **13** |
| Mittel über alle Flugminuten | **1,58** |
| Minuten mit 10 oder mehr | 97 von 11.318 |

Das sind **alle** Friesen in der Luft, nicht nur die mit Brügge — die echte Obergrenze liegt
also darunter. Daraus die Last bei 1 s Takt:

| | Anfragen je Sekunde |
|---|---|
| im Mittel | **1,6** |
| in der 30-Tage-Spitze | **13** |
| unter der verworfenen Annahme (20 Brüggen) | 20 |

**13 Anfragen je Sekunde sind für FastAPI kein Thema.** Dazu kommt die Sparregel aus
Abschnitt 1: Wer nicht auf VATSIM ist, kostet eine Indexabfrage je Minute — eine Brügge im
Leerlauf zählt nicht mit.

**Also 1 s als Voreinstellung.** Das löst zugleich den Zielkonflikt aus Abschnitt 1: flüssige
Bewegung *und* aktuelle Position, ohne Wahl zwischen beidem.

### Die Drosselung bleibt — als Reserve, nicht als Voreinstellung

Zwei Dinge müssen trotzdem stehen, bevor die erste Brügge ausgeliefert wird:

- **Eine eigene `location` mit eigener Zone** für `/api/bruegge/`. Bei 1 s sind es 60 Anfragen
  je Minute — in der gemeinsamen Zone wäre das die **halbe** Ration eines Anschlusses
  (`nginx/friesenspy.devprops.de.conf:7`, 120 r/m je IP), und ein Pilot mit Brügge *und*
  geöffnetem Kniebrett teilt sich diese Ration. Getrennt ist es kein Thema; gemeinsam wäre es
  genau die Falle, die schon einmal 429er erzeugt hat.
- **`naechste_frage_in_s` in jeder Antwort**, und der Server darf es **je Pilot verschieden**
  setzen. Wird es einmal eng, drosselt er auf 2 s — ohne Client-Release, ohne dass jemand
  etwas neu installiert, und ohne dass es jemand merkt außer der Karte. Fällt der Server aus,
  verdoppelt die Brügge ihren Abstand von selbst bis 60 s, statt zu hämmern.

### Ein Schieber im Admin — bis hin zum Aus

**Nutzerentscheidung vom 11.09.2026:** *„Baue eine Drossel zur Deaktivierung der
Brügge-Positionsmeldungen unter Admin ein. Zur Notabschaltung, wenn Performance-Probleme
auftreten. Beispielsweise einen Schieber von 1 s – 15 s – aus."*

**Verbindlich, und der Grund ist die Geschichte dieser Codebasis.** Wenn die App langsam wird,
steht in CLAUDE.md eine Liste gemessener Hebel, die *nicht* wirken — Container abschalten,
Priorität, `cpu_shares`. Was fehlt, ist ein Hebel, der wirkt, **ohne** einen Deploy: Der reißt
jede offene Sitzung ab und macht ein geöffnetes Kniebrett schwarz.

| Stellung | `naechste_frage_in_s` | wofür |
|---|---|---|
| **1 s** | 1 | Regelbetrieb (Abschnitt oben) |
| Zwischenstufen | 2, 5, 10 | spürbare Entlastung, Track bleibt sekundengenau (`spur`) |
| **15 s** | 15 | so grob wie der VATSIM-Feed — die Brügge bringt dann keinen Vorteil mehr |
| **aus** | 900 | keine Positionen, keine Objekte |

**Wie es wirkt:** Der Wert steht in `app_settings` (`bruegge_takt_s`, Muster wie die
Bannerverwaltung, `app/database.py:1182`) und wird bei **jeder** Antwort gelesen. Er wirkt
damit **sofort für alle** — ohne Deploy, ohne Client-Release, ohne dass ein Pilot etwas tun
muss. Genau dafür steht `naechste_frage_in_s` überhaupt im Protokoll.

⚠ **„Aus" heißt 900 s, nicht 0.** Eine Brügge, die gar keine Antwort mehr bekommt, weiß nicht,
ob der Server abgeschaltet hat oder ob das Netz weg ist — sie behielte ihren Sollzustand,
bis `gilt_bis_s` abläuft, und versuchte es weiter. Mit 900 s räumt sie ab und fragt
viertelstündlich nach; das Zurückschalten erreicht sie dann von allein.

⚠ **Was der Schieber nicht abschaltet:** die Prüfung selbst. Eine Meldung kommt weiterhin an
und wird beantwortet — nur eben mit leerem `soll` und langem Takt. Wer den Endpunkt ganz
schließen will, nimmt ihn im nginx heraus; das ist eine andere Entscheidung mit anderen
Folgen.

**Stand:** Noch nicht gebaut — es gibt keinen Endpunkt, den ein Schieber drosseln könnte, und
einen Knopf ohne Wirkung wollte ich nicht in den Admin stellen. Er entsteht **zusammen mit
`/api/bruegge/melden`**, im selben Zug.

### Die Position ist ein eigener Sichtbarkeitsgrad

⚠ **Vor der ersten Auslieferung zu entscheiden, nicht danach.** `pilot_visibility` kennt heute
die Dienste `online`, `prefile` und `ts` — das sind **Benachrichtigungen**. Eine
sekundengenaue Position ist etwas anderes als ein Eintrag im 15-Sekunden-Raster, das ohnehin
öffentlich über VATSIM läuft: Sie zeigt Platzrunden, Fehlanflüge und Abbrüche in einer
Auflösung, die es vorher nicht gab.

Das ist keine Blockade für das Protokoll — die Brügge meldet, der Server entscheidet, wem er
es zeigt. Aber es ist eine Entscheidung, die dem Nutzer gehört, und sie steht auch in
[#23](https://github.com/regover13/friesenspy/issues/23) noch offen.

---

## 7. Die Brügge läuft durch — ein Einmal-Aufruf hinterlässt nichts

**Gemessen:** Objekte leben nur, solange die SimConnect-Verbindung offen ist. Nach `Close`
liefert jede Anfrage auf die Objekt-ID `EXCEPTION 3 · UNRECOGNIZED_ID`, und die Schiffe waren
sichtbar weg.

Die Brügge hält ihre Verbindung deshalb offen, solange der Simulator läuft. Sie startet mit ihm
und endet mit ihm.

| Simulator | Autostart | Belegt |
|---|---|---|
| MSFS 2020 + 2024 | **WASM-Modul im Community-Ordner** | ✅ ein Quelltext für beide |
| MSFS 2020 + 2024 | externes Programm über `exe.xml` | ✅ derselbe Adapter; SmartScreen **ungemessen** |
| X-Plane 12 | `Resources/plugins/` | ✅ läuft auch in der kostenlosen Demo |

**Empfohlen für MSFS ist der WASM-Weg:** ein Ordner zum Hineinkopieren, kein `exe.xml`-Eintrag,
keine unsignierte EXE, kein SmartScreen. Zwei Build-Flags sind dabei unverzichtbar und stehen
in [`probe-msfs/wasm/bauen.ps1`](probe-msfs/wasm/bauen.ps1) dokumentiert — ohne sie wird das
Modul lautlos verworfen.

⚠ **Eine WASM-Eigenheit ist offen:** `OnGround=1` setzte das Objekt dort **nicht** auf den
Boden (extern tut es das zuverlässig). Vor dem Bau zu klären, sonst schwebt alles.

---

## 8. Was die Brügge nicht tut

Bewusst aufgezählt, weil jede dieser Versuchungen sie teuer macht:

- **Keine Eventlogik.** Sie weiß nicht, was ein Kieker ist.
- **Keine Wertung.** Ob eine Stelle abgedeckt ist, entscheidet der Server aus den Positionen.
- **Kein Zwischenspeicher mit eigener Meinung.** Der Sollzustand kommt vom Server.
- **Keine Oberfläche.** Kein Fenster, kein Menü. Was der Pilot sieht, sieht er im Simulator.
- **Keine Geheimnisse auf der Platte.** Sie bekommt nur, was in ihrer Nähe steht — das ist in
  [#24](https://github.com/regover13/friesenspy/issues/24) die Spielmechanik und in
  [#20](https://github.com/regover13/friesenspy/issues/20) der Schummelschutz.

---

## 9. Fassungen

`protokoll` ist eine ganze Zahl und steht in **beiden** Richtungen. Der Server bedient jede
Fassung, die er kennt; eine Brügge, die eine unbekannte meldet, bekommt `426` und eine
Hinweisadresse — nie eine halb verstandene Antwort.

**Die Regel für Änderungen:** Felder hinzufügen erhöht die Fassung nicht (unbekannte Felder
werden auf beiden Seiten übergangen). Bedeutungen ändern oder Felder entfernen erhöht sie.

---

## 10. Offen — vor dem Bau zu klären

1. **Wird ein weit entfernt gesetztes Objekt gezeichnet, wenn der Pilot hinkommt?** Das
   Anlegen gelingt bis 10.000 km, die Sichtbarkeit ist nur im Nahbereich belegt (200 m an
   Land, 1,6 km auf dem Wasser). Die Antwort entscheidet, ob die Brügge einmal verteilen darf
   oder unterwegs nachsetzen muss — und damit über den Takt aus Abschnitt 6. **Braucht einen
   echten Flug.**
2. **`OnGround` in WASM** (Abschnitt 7).
3. **Überdauert eine X-Plane-Instanz das Entladen des Plugins?** Für den Zuschnitt belanglos,
   weil die Brügge durchläuft — aber sauber zu wissen.
4. **Die ⚠-Zeilen im Katalog** (Abschnitt 3): X-Plane-Objekte außer `SailBoat.obj` sind
   nachgewiesen, aber nie gesetzt.
