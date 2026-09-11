# 🌉 Das Brügge-Protokoll

**Der Vertrag zwischen dem FriesenSpy-Server und einer Brügge im Simulator.**
Verbindlich für alle Umsetzungen — MSFS 2020, MSFS 2024, X-Plane 12.

> Stand 11.09.2026 · Protokollfassung **1** · Entwurf, noch nicht umgesetzt
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
Authorization: Bearer <brügge-schlüssel>
Content-Type: application/json
```

Die Brügge muss ohnehin sagen, wo sie ist, damit der Server weiß, was um sie herum stehen
soll. Position hinauf und Objekte hinunter in einer Anfrage ist deshalb nicht gespart, sondern
die natürliche Form.

### Hinauf

```jsonc
{
  "protokoll": 1,
  "simulator": "msfs2024",        // msfs2020 | msfs2024 | xplane12
  "bruegge_version": "1.0.0",
  "instanz": "a3f9c1",            // Zufallswert je Prozessstart -- s. unten
  "kann": ["tier_gross", "bauwerk", "fahrzeug", "boot_klein"],

  "lage": {                        // der Stand JETZT -- maßgeblich für "soll"
    "lat": 53.7863, "lon": 7.9104,
    "alt_msl_ft": 1348.9,
    "alt_agl_ft": 12.3,           // null, wenn der Simulator sie nicht kennt
    "gs_kt": 0.0,
    "kurs": 210.4,
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

#### Wie die Position zum VATSIM-Flug findet

**Die Zuordnung geschieht im Server über die CID** — der Brügge-Schlüssel trägt sie
(Abschnitt 5), und `live_positions` ist ebenfalls nach CID geschlüsselt
(`app/database.py:77`). Die Brügge schickt **keine** Kennung des Fluges mit; sie weiß nichts
von VATSIM, von Callsigns oder von Flugplänen.

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
| `401` — Schlüssel ungültig oder widerrufen | räumt auf und hält an. Kein Wiederholen. |
| `426` — Protokollfassung zu alt | räumt auf und hält an, nennt dem Piloten die Hinweisadresse |
| `429` — Rate-Limit | verdoppelt den Abstand bis 60 s |
| `5xx`, Zeitüberschreitung, kein Netz | behält den letzten Sollzustand, solange `gilt_bis_s` reicht |

**`gilt_bis_s` steht in jeder Antwort** und sagt, wie lange der gelieferte Sollzustand ohne
neue Auskunft gültig bleibt. Danach räumt die Brügge ab. Ohne diese Zahl entschiede jede der
drei Umsetzungen selbst, was bei Netzausfall geschieht — und für die Baake wäre „stehen
bleiben" eine Station, die nie verschwindet.

#### `instanz` — ein Pilot kann zwei Brüggen laufen haben

Ein Zufallswert, den die Brügge bei jedem Prozessstart neu zieht. **Der Schlüssel allein
genügt nicht:** Ein Drittel der Gruppe fliegt X-Plane, manche haben beides installiert. Wer
MSFS und X-Plane gleichzeitig laufen lässt — oder zwei Rechner benutzt — meldet sonst zwei
Positionen unter einer CID. Der Server sähe eine springende Position und ein `steht`, das sich
mit jeder Anfrage widerspricht.

Der Server führt den Zustand je `(schlüssel, instanz)` und zeigt Doppelmeldungen im Admin an.

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
  "naechste_frage_in_s": 10,
  "gilt_bis_s": 300,               // so lange gilt "soll" ohne neue Auskunft
  "soll": [
    { "id": "k7-3-a", "art": "tier_gross", "lat": 53.6612, "lon": 6.9835,
      "kurs": 210, "erwartete_hoehe_ft": null }
  ]
}
```

`soll` ist **die vollständige Liste dessen, was jetzt dastehen soll** — kein Strom von
Befehlen. Der Unterschied entscheidet über die Robustheit (Abschnitt 2).

`erwartete_hoehe_ft` darf `null` sein und ist dann „nimm die Oberfläche". Setzt der Server
einen Wert, ist er MSL und die Brügge versucht ihn zu treffen.

---

## 2. Der Sollzustand wird abgeglichen, nicht befolgt

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

| Gattung | Grund | MSFS 2020 + 2024 | X-Plane 12 |
|---|---|---|---|
| `tier_gross` | Gelände | `BlackBear` ✅ | `deer_buck.obj` ⚠ |
| `bauwerk` | Gelände | `Windmill` ✅ | `OilPlatform.obj` ⚠ |
| `fahrzeug` | Gelände | `ASO_Ambulance_Japan` ✅ | `lib/airport/vehicles/…` ⚠ |
| `boot_klein` | **Meereshöhe** | `Boat01` ✅ | `SailBoat.obj` ✅ |
| `boot_gross` | **Meereshöhe** | `CruiseShip01` ✅ | `Perry.obj` ⚠ |

✅ = gesetzt und im Bild gesehen · ⚠ = Datei auf der Platte nachgewiesen, aber nie gesetzt

**Eine Gattung ist eine Bedeutung, kein Modell.** Welches Tier ein `tier_gross` ist, darf sich
zwischen Simulatoren und zwischen Brügge-Fassungen unterscheiden — der Pilot zählt Tiere, nicht
Bären. Wer eine bestimmte Art braucht, braucht eine eigene Gattung.

**Neue Gattungen brauchen keine Server-Änderung.** Eine neuere Brügge meldet in `kann` einfach
mehr; der Server darf anfordern, was mindestens eine Brügge kann.

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

### ⚠ Für welchen Simulator diese Regel gilt, ist NICHT geklärt

**Die Bodensee-Messung ist ohne Simulator-Angabe protokolliert.** Im ganzen
[`probe-msfs/ERGEBNIS.md`](probe-msfs/ERGEBNIS.md) steht der Simulator genau einmal (Zeile 4,
MSFS 2024) und gilt dort dem Vormittagslauf; der Bodensee-Abschnitt am Ende nennt keinen.
Damit ist **nicht belegt**, dass die Regel für beide MSFS-Fassungen gilt — der Katalog oben
führt sie trotzdem unter „MSFS 2020 + 2024".

**Es gibt sogar einen Hinweis auf das Gegenteil.** Unmittelbar nach der Bodensee-Tabelle steht
in ERGEBNIS.md: *„Für MSFS 2024 gilt das nicht: Dort kommt `Altitude` an."* Wenn das stimmt,
ist `Boat` in MSFS 2024 **steuerbar** — man müsste nur die Zielhöhe kennen. Dann wäre die
Kategorie dort nicht kaputt, sondern nur unbequem.

Auch die Gegenprobe an Land trennt nicht sauber: Auf Wangerooge (Platzhöhe ~3–10 ft) sind
„Meereshöhe" und „Geländehöhe" nur wenige Fuß auseinander — dieselbe Schwäche, die schon den
Nordsee-Fall wertlos machte.

**Zu klären, bevor der Katalog steht:** Bodensee-Messung je Simulator wiederholen, mit
`Boat01` **und** `CruiseShip01`, und den Simulator ins Protokoll schreiben. Bis dahin führt
die `Grund`-Spalte je Simulator einen eigenen Wert, statt einen gemeinsamen zu behaupten.

*(Gefunden im Fable-Review vom 11.09.2026. Es ist an diesem Tag das dritte Mal, dass eine
Aussage über Bootshöhen weiter reichte als ihre Messung.)*

**Eine Gattung mit `Grund: Meereshöhe` darf nur dort angefordert werden, wo der Meeresspiegel
die Oberfläche ist.** Auf der Nordsee stimmt das — und der FriesenKieker spielt an den
Friesischen Inseln, dort sind Boote also brauchbar. Über Land versinken sie (auf Wangerooge
drei Meter tief im Platz, komplett unsichtbar), auf dem Bodensee 395 m tief.

Das ist ein **bekannter MSFS-Fehler**, kein Aufbaufehler: *„SimConnect injected Boat
underwater"*, gemeldet am 11.05.2022 für die Great Lakes, bis heute ohne Antwort von Asobo
([DevSupport](https://devsupport.flightsimulator.com/t/simconnect-injected-boat-underwater/4226)).
Der dort genannte Ausweg ist ein eigenes SimObject mit **Flugzeug-Kategorie** — mit dem
Nachteil, dass Schiffe dann als Flugzeuge gezählt werden.

### Wie der Server davon erfährt

**FriesenSpy hat kein Geländemodell.** Der Server kann nicht wissen, ob an einer Koordinate
Wasser auf Meereshöhe liegt. Deshalb steht in jeder Meldung `steht[].hoehe_ft`: die Höhe, die
das Objekt **tatsächlich** erreicht hat.

Weicht sie deutlich von `erwartete_hoehe_ft` ab, oder meldet ein Objekt über Land 0,0 ft, ist
die Stelle für diese Gattung untauglich — der Server nimmt sie aus der Wertung, statt einem
Piloten etwas zuzumuten, das niemand sehen kann. **Die Rückmeldung ist der einzige Weg dorthin;
Raten wäre der Anfang einer neuen Fehlersuche.**

---

## 5. Anmeldung: der Brügge-Schlüssel

### Warum nicht der Weg des Kniebretts

Das Kniebrett bindet ein Gerät über ein Cookie (`panel_devices` → `USER_COOKIE`). **Dieser Weg
steht der Brügge nicht offen:** Er lebt im Speicher von MSFS, in der Browser-Umgebung des EFB.
Die Brügge ist ein eigenständiges Programm ohne Browser — sie hat keinen Cookie-Speicher, und
im WASM-Fall nicht einmal ein Fenster, in dem sich jemand anmelden könnte.

### Der Ablauf

1. Der Pilot meldet sich **in der Weboberfläche** an (der Board-Login läuft).
2. Dort drückt er einmal auf „Brügge-Schlüssel erzeugen" und bekommt einen Zufallswert.
3. Er kopiert ihn in die Konfigurationsdatei neben der Brügge.
4. Die Brügge schickt ihn bei jeder Anfrage mit:
   `Authorization: Bearer <schlüssel>`

```
bruegge_schluessel(schluessel PK, cid, erzeugt_am, zuletzt_gesehen, widerrufen_am)
```

**Der Schlüssel trägt die CID** — deshalb muss die Brügge keine Kennung mitschicken und der
Server keine Zuordnung raten.

### Was der Schlüssel darf und was nicht

| | |
|---|---|
| **darf** | an `/api/bruegge/melden` Position melden und Objekte abholen |
| **darf nicht** | alles andere — kein Konto, kein Admin, keine Einstellungen, keine fremden Daten |

**Das ist keine Formalie.** Ein Schlüssel, der in eine Textdatei auf 20 Rechnern wandert, ist
kein Passwort-Ersatz: Er muss so wenig können, dass sein Verlust nichts kostet außer falschen
Positionsmeldungen — und die fängt die VATSIM-Plausibilitätsprüfung unten ab.

**Er ist trotzdem ein Zugangsgeheimnis und muss im Admin widerrufbar sein**, wie eine
Panel-Gerätebindung. Ein widerrufener Schlüssel bekommt `401`, und die Brügge räumt auf,
statt es erneut zu versuchen.

**Nur über HTTPS.** Der Schlüssel geht bei jeder Anfrage über die Leitung. Für MSFS-WASM ist
das ohnehin die einzige Möglichkeit — die Network-API dort lässt ausschließlich `https` zu
(und genau daran scheiterte im Probeflug der Versuch mit `http://127.0.0.1`).

⚠ **Der Schlüssel wandert mit dem Ordner.** Ein WASM-Paket liegt im Community-Ordner, und
Community-Ordner werden kopiert und weitergegeben. Wer seinen Ordner teilt, teilt seinen
Schlüssel mit — das ist beim Widerrufen mitzudenken.

### Die Position wird gegen VATSIM geprüft

**Der Server nimmt eine gemeldete Position nicht ungeprüft an.** Passt sie nicht zur letzten
bekannten VATSIM-Position derselben CID — Sprung über hunderte Kilometer, Geschwindigkeit
jenseits des Musters —, antwortet er `409` und verwirft sie.

Das steht schon in der Kieker-Spec (13.3) und ist beim Schreiben dieses Protokolls
herausgefallen. **Ohne die Prüfung ist eine Kieker-Abdeckung frei erfindbar**, und zwar
billiger als über jeden Weg, den Spec-Abschnitt 12 als Schummelrisiko diskutiert: Man
schickte einfach Koordinaten. Die Prüfung kostet die Brügge nichts — sie geschieht
vollständig im Server.

---

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
