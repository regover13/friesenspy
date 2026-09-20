# Der Rauch

> Stand 20.09.2026 · ✅ **im Flug abgenommen** in beiden Simulatoren
> („wind und rauch OK", Nutzer) · MSFS-Paket **1.15.0**
>
> ⭐ **Seit 20.09.2026 EIN Bau für MSFS 2020 UND 2024**, gebaut mit dem **2020er SDK**. Vorher baute das
> 2024er SDK, und das Ergebnis lief in MSFS 2020 nicht: **kein Rauch** (die 2024er Behavior-Vorlage
> `ASOBO_VFX_Template` + `CompileBehaviors` kennt MSFS 2020 nicht — das Modell lud, ohne jede
> Fehlermeldung, und es rauchte nicht) und **rosa Seehunde** (die 2024er Toolchain macht aus PNG-Texturen
> `.KTX2`, die MSFS 2020 nicht liest). Jetzt: Behaviors **direkt im Modell-XML** unter `<Behaviors>` mit
> `ASOBO_GT_FX` aus `Asobo\Generic\FX.xml` (Doku `Model_Definitions` des 2020er SDK), Texturen als `.DDS`.
> Im Flug belegt: sechs Säulen in MSFS 2020, und in MSFS 2024 sahen sie neben dem alten Bau **identisch**
> aus. Es gibt nur noch diese eine Fassung. Die Seehund-Textur ist seitdem um 40 % dunkler (s. `seehund/`).

Sechs Rauchsäulen, 90 m hoch, 30 Sekunden Lebensdauer. Sie sind das Sichtzeichen der
FriesenBrügge: Wo eine Säule steht, ist etwas — eine Kolonie, ein Ziel, eine Baake.

Der X-Plane-Teil liegt in [`../xplane/`](../xplane/) und entstand zuerst; **die
X-Plane-Säule ist die Vorlage, MSFS zieht nach.** Das ist eine Entscheidung und kein
Zufall: X-Planes Partikelsystem reagiert sichtbar besser auf Wind, und der Nutzer hat sie
im direkten Vergleich vorgezogen (*„xPlane ist schöner, weil sich kleine Wölkchen bilden
und es besser auf den Wind reagiert"*).

---

## Die Dateien

| Datei | was sie tut |
|---|---|
| [`rauch_bauen.py`](rauch_bauen.py) | schreibt die sechs Effekt-XMLs (Partikel, Physik, Farben) |
| [`paket_bauen.py`](paket_bauen.py) | Material, Trägermodell, SimObjects, Projektdatei für `fspackagetool` |
| [`bauen.ps1`](bauen.ps1) | ruft beide auf, startet den Package Builder und **räumt den Simulator hinterher ab** |
| `rauch_msfs.png` | die Textur — **eine** Wolke, kein Atlas (s. unten) |

Erst `python paket_bauen.py` (schreibt Quellen, Paketdefinitionen und den abgedunkelten Seehund
nach `PackageSourcesSeehund/`), dann `.\bauen.ps1`. **Das 2020er Werkzeug startet MSFS 2020 im
Baumodus** (`FlightSimulator.exe -I ; BuildAssetPackages …`, ohne Fenster) und dauert rund 45
Sekunden; der Simulator beendet sich nicht von selbst, deshalb räumt das Skript vier Prozesse ab:
`fspackagetool`, `FlightSimulator`, `gamelaunchhelper` und `gamingservicesui`. Wer nur das
Werkzeug beendet, lässt den Simulator stehen, und der nächste Bau schreibt dann **nichts** (gemessen
20.09.2026). Das Skript bricht ab, wenn schon ein Simulator läuft (`-Trotzdem` erzwingt es). Der
2024er Weg (`C:\MSFS 2024 SDK`, Start von `FlightSimulator2024`) steht nur noch in der Git-Historie.

⚠ **Niemals bauen, während jemand im Simulator sitzt.**

---

## Die sechs Farben

| Art | RGB | wofür |
|---|---|---|
| `rauch_navy` | `#191D53` | Vereinsfarbe, dunkel |
| `rauch_hellblau` | `#8FBFF1` | Vereinsfarbe, hell |
| `rauch_rot` | `#8A1B1B` | gedecktes Rot |
| `rauch_orange` | `#D75F28` | gedecktes Orange |
| `rauch_signalrot` | `#E30613` | Signalfarbe |
| `rauch_signalorange` | `#FF6A13` | Signalfarbe |

⚠ **Bei Rauchfarben wird nie gewürfelt.** Die Farbe trägt Bedeutung — anders als bei
Autos oder Booten, wo die Variante beliebig ist. Das ist eine stehende Regel.

---

## Die Maße, und woher sie kommen

Keine der Zahlen ist geraten; sie stehen in `rauch_bauen.py` mit ihrer Herleitung.

| Größe | Wert | warum |
|---|---|---|
| Lebensdauer | 30 s | Nutzerwunsch, in beiden Simulatoren gleich |
| Auftrieb | 3 m/s | wie X-Plane (*„lass es bei 3m"*) |
| Höhe | **90 m** | ergibt sich: 3 m/s × 30 s |
| Fuß | 0,80 m | eine Rauchpatrone, kein Krater |
| Krone | 11,97 m | 0,133 × Höhe |
| Dichte | 11 Partikel je Höhenmeter | **der einzige frei gewählte Regler** |

Die Streuung (Lebensdauer 0,55–1,0 ×, Steiggeschwindigkeit 0,5–1,8 ×, Größe 0,8–1,2 ×)
sorgt dafür, dass die Säule nicht wie ein Schlauch aussieht.

**Wind:** Der Anteil, mit dem ein Partikel den Wind aufnimmt, wächst mit der Höhe
(`_WINDANTEIL_STUETZEN`) — unten steht der Rauch fast, oben zieht er voll mit. Bei 30 kt
legt sich die Säule flach, und das ist physikalisch richtig; 30 kt sind an der Nordsee ein
echter Fall.

---

## ⭐ Die Sichtweite — die teuerste Frage des Tages

**Die Säule ist aus 6480 m zu sehen (3,5 NM), und dort ist eine harte Grenze.**

Das Feld heißt **`MaxDistanceEmission`**, steht in jedem Effekt-XML neben `TimeEmission`
und ist auf **15000** gesetzt. Die SDK-Doku nennt es als einziges für diesen Zweck:

> *„Once the camera exceeds this distance from the emitter, particles will stop being
> created."* — Standardwert **2000 Meter**.

| `MaxDistanceEmission` | sichtbar ab |
|---|---|
| 2000 (Vorgabe, nie gesetzt) | 1830 m |
| 15000 | **6480 m** |
| 50000 | 6480 m — harte Schranke, die Doku nennt keine |

Gesetzt bleibt 15000: Alles darüber ist Rechenlast ohne Sicht.

⚠ **Gefunden hat es eine Web-Recherche, auf Verlangen des Nutzers** — davor drei Anläufe
geraten und alle im Flug widerlegt (`minSize="0"`, `DistanceToNotAnimate`, ein größerer
Träger). Die ganze Messreihe samt der Fehlschlüsse steht in
[`../MESSLISTE.md`](../MESSLISTE.md).

### ⚠ Was dabei NICHT gemessen wurde, und wer es übernimmt, irrt sich

„Ein Träger von 300 m brachte nichts" steht in den Kommentaren und stimmt als Beobachtung.
**Als Aussage über Geometrie ist es falsch:** Während der ganzen Träger-Reihe stand
`MaxDistanceEmission` noch auf 2000, ab 90 m war also der Effekt der Engpass und nicht das
Modell. Über Geometrie sind genau zwei Punkte belegt — 2 m → 100 m und 90 m → mindestens
1830 m.

**Für alles ohne Partikel — Seehunde, Tiere, Fahrzeuge — fällt die Partikelgrenze weg, und
nur diese Skala zählt.**

### Hin- und Wegflug sehen verschieden aus

Der Emitter beginnt in beiden Richtungen bei 6480 m. Beim **Hinflug** braucht die Säule
aber ihre 30 Sekunden, um von unten aufzuwachsen (*„Sie steigt langsam vom Boden auf"*) —
deshalb wirkt sie dort später. Für eine Baake ist das die ungünstigere Richtung; wer es
verbessern will, setzt an der **Aufbauzeit** an, nicht an der Reichweite.

---

## Die Fallen

### 1. Die Textur ist eine Wolke, kein Atlas

X-Plane bekommt eine 4×4-Kachel und sucht sich daraus ein Feld je Partikel. **MSFS bildet
denselben Atlas auf *jedes* Partikel ab** — die Säule sah aus wie ein Gitter. Deshalb liegt
hier `rauch_msfs.png` mit einer einzigen Wolke und `atlas=1`.

### 2. Der Träger ist ein unsichtbarer Würfel, 12 × 90 × 12 m

Ein Partikeleffekt braucht in MSFS ein Modell, an dessen Knoten er hängt — anders als in
X-Plane, wo eine `.obj` ganz ohne Geometrie auskommt. Der Würfel hat **24 Ecken**, weil
jede Fläche ihre eigene Normale braucht, und trägt `ASOBO_material_invisible`.

⚠ **Er steht auf dem Ursprung, nicht um ihn herum** (`min: [-B, 0.0, -B]`). `auf_boden`
setzt den Ursprung auf Geländehöhe; ein zentrierter Würfel steckte zur Hälfte im Boden.

### 3. Kein BOM in `manifest.json` und `layout.json`

MSFS übergeht solche Dateien **lautlos** — `Content.xml` sagt „Activated", das Modul lädt
nie. `Set-Content -Encoding UTF8` schreibt unter PowerShell 5.1 eines.

### 4. `creator` ist `devprops`

In allen Manifesten. devprops ist der Herausgeber, FriesenFlieger die Zielgruppe.

---

## Was offen ist

**Was ein Emitter kostet, der aus 6,5 km spawnt.** Er läuft auch, wenn ihn niemand ansieht.
Bei einer Fackel egal; bei zwanzig Kolonien mit je einer Säule gehört es gemessen, bevor
der Kieker so etwas setzt.

**Ein Licht wäre für eine Baake die bessere Lösung.** Positionsleuchten sieht man
kilometerweit, wenn das Flugzeug längst ein Punkt ist. Ein SimObject kann aus nichts als
Licht bestehen — belegt an `wENLK_lightdummy` aus `fs24-microsoft-airport-enlk-leknes`.
Die Lichtdefinition steckt allerdings im Modell (`ASOBO_macro_light`) und damit im
verschlüsselten Archivteil; nachbaubar, aber ein eigener Umbau.
