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
  "kann": ["tier_gross", "bauwerk", "fahrzeug", "boot_klein"],

  "lage": {
    "lat": 53.7863, "lon": 7.9104,
    "alt_msl_ft": 1348.9,
    "alt_agl_ft": 12.3,           // null, wenn der Simulator sie nicht kennt
    "gs_kt": 0.0,
    "kurs": 210.4,
    "am_boden": true
  },

  "steht": [                       // was die Brügge JETZT gesetzt hat
    { "id": "k7-3-a", "hoehe_ft": 1297.0, "seit_s": 143 }
  ]
}
```

`kann` ist die Liste der Gattungen, die diese Brügge beherrscht (Abschnitt 3). Sie wird bei
**jeder** Anfrage mitgeschickt, nicht nur beim ersten Mal — der Server hält keine Sitzung, und
eine zustandslose Meldung übersteht jeden Neustart auf beiden Seiten.

`alt_agl_ft` ist in X-Plane direkt vorhanden (`sim/flightmodel/position/y_agl`), in MSFS nur
über Umwege — dort steht `null`, und der Server rechnet ohne. Die Kieker-Spec beschränkt ihre
Deckungsprüfung aus genau diesem Grund auf MSL (Abschnitt 4.2).

### Hinunter

```jsonc
{
  "protokoll": 1,
  "naechste_frage_in_s": 10,
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
MSFS 2024 vergibt achtstellige IDs, MSFS 2020 dreistellige, das WASM-Modul begann bei 16384.

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

Die Brügge ist ein eigenständiges Programm ohne Browser — der Geräteweg des Kniebretts
(`panel_devices` → `USER_COOKIE`) steht ihr nicht offen, er lebt im Speicher von MSFS.

Also ein Zufallswert, den der Pilot **einmal** aus der Weboberfläche in die Konfigurationsdatei
kopiert. Er trägt die CID.

```
bruegge_schluessel(schluessel PK, cid, erzeugt_am, zuletzt_gesehen, widerrufen_am)
```

**Er ist ein Zugangsgeheimnis und muss im Admin widerrufbar sein**, wie eine
Panel-Gerätebindung. Ein widerrufener Schlüssel bekommt `401`, und die Brügge räumt auf,
statt es erneut zu versuchen.

---

## 6. Takt

⚠ **`nginx/friesenspy.devprops.de.conf:7` erlaubt 120 Anfragen pro Minute je IP**, und die Zone
geht über die Adresse, nicht das Gerät. Ein Pilot mit Brügge *und* geöffnetem Kniebrett teilt
sich dieses Budget.

- **Eine eigene `location` mit eigener Zone** für `/api/bruegge/`, bevor die erste Brügge
  ausgeliefert wird.
- **Der Server bestimmt den Takt**, nicht die Brügge: `naechste_frage_in_s` in jeder Antwort.
  Damit lässt er sich ohne Client-Release ändern — die einzige Stellschraube, die nach der
  Verteilung noch erreichbar ist.
- Vorschlag für die Voreinstellung: **2 s**, wenn Objekte in der Nähe stehen oder stehen
  könnten, sonst **10 s**. Fällt der Server aus, verdoppelt die Brügge ihren Abstand bis
  60 s, statt zu hämmern.

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
| MSFS 2020 + 2024 | externes Programm über `exe.xml` | ✅ derselbe Adapter, aber SmartScreen |
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
