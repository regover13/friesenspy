# Koordination paralleler Sessions

Kurze Absprachen zwischen parallel arbeitenden Claude-Sessions am FriesenSpy-Repo.
Vor jedem Push: `git fetch` + Rebase auf `origin/main`; niemals fremde, uncommittete
Änderungen überschreiben. Einträge bitte oben anfügen (neueste zuerst).

---

## 2026-09-15 — Brügge-Zuordnung: `deutlich_besser` raus, `frei` rein (v14.44.0)

**Wer:** Sitzung „Sim restart ⑂", Zweig `worktree-bruegge-zuordnung-haerten`, direkt nach
`main` gepusht.

**Was und warum:** `bruegge.deutlich_besser` ist **entfernt**. Es hängte eine gemerkte
Zuordnung bei jeder Meldung sofort um, sobald ein anderer Kandidat halb so weit weg lag —
ohne den Verstoßzähler, den `PAARUNG_LOESEN_TAKTE` verlangt. Im Log vom 14.09.:

    19:30:22  Kennung 9e3711c100000000 haengt um, 1642160 -> 1602713 (572 m gegen 1175 m)

572/1175 = 0,486, also knapp „deutlich besser" — ein Pilot verlor seine Zuordnung bei 572 m
an jemanden 1,2 km entfernt. Der Anlass (zwei MSFS-Brüggen mit derselben Kennung) war echt,
das Mittel falsch: Das Problem war eine geteilte **Identität**, geschwächt wurde die
**Bindung**. Die Identität sichert seit v14.40.0 der Server selbst.

An seine Stelle tritt **`frei` aus dem Kniebrett**: `zuordnen()` nimmt jetzt `belegt` — die
CIDs, die innerhalb von `MELDUNG_FRIST_S` (10 s) eine andere Brügge meldet. Das löst die
Lage, an der der Server am 14.09. anderthalb Minuten lang scheiterte („2 Kandidaten ohne
Vorsprung (76 m gegen 93 m)"). Der Ausschluss-Schritt des Kniebretts braucht dadurch keinen
eigenen Zweig — er ist hier `len(passende) == 1` nach Abzug der Belegten.

**Zwei Fallen, die dabei aufgefallen sind** (bitte nicht wieder einbauen):
- Bleibt nach dem Abzug niemand übrig, wird die Sperre **einmal zurückgenommen**. Ohne das
  sperrt sich ein Pilot nach dem Simulator-Neustart mit seiner eigenen alten Kennung aus —
  gebunden in `test_eine_neue_kennung_verdraengt_die_alte_derselben_cid`.
- Die Frist steht jetzt **einmal** in `app/bruegge.py`; `VatsimPoller.BRUEGGE_FRIST_S` holt
  sie von dort. Nicht die 24 h aus `bruegge_aufraeumen` nehmen, das ist Müllabfuhr.

**Berührte Dateien:** `app/bruegge.py`, `app/main.py` (`_bruegge_zuordnen`),
`app/database.py` (neu: `bruegge_belegte_cids`), `app/poller.py` (nur die Fristkonstante),
`tests/test_bruegge_geteilte_kennung.py` (neu geschrieben), `docs/api.md`.

**Noch offen aus derselben Untersuchung** (nicht angefasst, Reihenfolge mit dem Nutzer
abgestimmt):
1. nginx: `/api/bruegge/melden` braucht eine **eigene** `limit_req`-Zone. Heute liegt es mit
   allem unter `/api/` in einem Topf von 120 r/m je IP; eine Brügge im Regeltakt belegt davon
   60. Gemessen: 67× HTTP 429 am 14.09.
2. **288× HTTP 502** am 14.09. auf denselben Endpunkt, in Blöcken (14:21, 15:51, 17:46,
   19:51 …). Der Endpunkt ist `async def` und macht rund zehn synchrone SQLite-Operationen
   auf dem Event-Loop. ⚠ **Er ist heute atomar, WEIL er blockiert** — zwischen Lesen und
   Commit liegt kein `await`. Wer ihn in den Threadpool legt, baut den Wettlauf ein, den
   `belegt` gerade verhindert. Erst messen, dann entscheiden.
3. Der Brügge-Strom soll aus dem Kniebrett heraus (Nutzerentscheidung): Dort trägt das
   Sim-Matching, das den direkten Weg hat und alle Flugzeuge im Umkreis sieht.
4. Verstoß-Fenster: `main.py` antwortet dort mit `soll=[]`, woraufhin die Brügge **alle
   Objekte abräumt** und drei Takte später neu setzt. Im Kniebrett gilt die Zuordnung im
   Verstoß-Fenster weiter — hier sollte sie es auch.
5. 42× `/api/fse/zones` je Minute von einer IP (eigenständiger Befund, ohne Brügge).

---

## 2026-09-13 (nachmittags) — Website-Karte: Friesen mit Brügge im Sekundentakt

**Wer:** Server-Session (VPS), Zweig `karte-bruegge-1hz`.

**Was:** Die Website-Karte zeigt fremde Friesen bisher im VATSIM-Takt — alle 15 Sekunden ein
echter Punkt, dazwischen fortgerechnet aus Kurs und Fahrt. Wer eine Brügge fliegt, meldet dem
Server aber **jede Sekunde** seine echte Position (`bruegge_positions`, `_BRUEGGE_TAKT_VORGABE_S = 1`).
Diese Meldungen landen heute in der Datenbank und gehen von dort nicht weiter —
`bruegge_positionen_holen` ist in `app/main.py` importiert und **nirgends aufgerufen**; ihr
Docstring verspricht „für /api/live, das sie über die VATSIM-Punkte legt", und genau das fehlt.

Das Kniebrett macht dasselbe im Kleinen schon: `_verkehrZusammenfuehren` schreibt die
Sim-Werte eines erkannten Friesen in `_positionsRoh`, und der Sekundentakt (`_naviTakt`) bewegt
ihn damit sekundengenau. Die Brügge ist die bessere Quelle — sie reicht über den ganzen
Kartenausschnitt statt nur über den geladenen Umkreis, und sie gilt auf jeder Plattform.

**Berührte Dateien (bitte dort nichts parallel ändern):**
- `app/main.py` — Brügge-Endpunkt `/api/bruegge/melden`, SSE-Strom
- `app/poller.py` — SSE-Broadcast
- `app/static/index.html` — `_positionsRoh`, `_naviTakt`, SSE-Empfang, `updateMap`
- `tests/` — neue Zusicherungen

**Nicht berührt:** `friesenbruegge/**`. Das Protokoll bleibt, wie es ist — die Brügge sendet
schon alles Nötige, es wird serverseitig nur nicht weitergereicht. Ein neues Paket ist für
diese Änderung **nicht** nötig.

**Offen und davon unabhängig:** Der Zweig `bruegge-posix` (macOS/Linux, Fassung 1.1.0) wartet
auf den Merge nach `main`. Der Kontrollstart unter Windows ist bestanden (13.09., alle vier
Punkte). Wer an `friesenbruegge/xplane/bruegge.cpp` arbeitet, wartet diesen Merge ab —
`netz.h` zieht dort Netz und Threads aus der Datei heraus.

---

## 2026-09-13 (nachts, 02:30) — ✅ X-Plane IST GEFLOGEN, und beide Pakete sind draußen

**Für die parallele Sitzung, damit niemand doppelt misst:** Der Eintrag darunter ist überholt.
Dort steht „im Simulator noch nicht geflogen" — das stimmt seit 02:25 nicht mehr.

**Gemessen, in einer Sitzung, ohne Simulator-Neustart zwischendurch:**

| | |
|---|---|
| Plugin lädt, Datarefs, Kennung | ✅ — die Kennung übersteht auch einen Neustart |
| Netzschicht (eigener Thread, WinHTTP, TLS) | ✅ HTTP 200, nicht 422 — das JSON ist gültig |
| Objekte setzen | ✅ **sechs Gattungen gleichzeitig, alle im Bild gesehen** |
| Terrain-Probe am Zielort | ✅ jedes Objekt auf seiner eigenen Höhe |
| Abräumen, Umsetzen | ✅ beides |
| Position im Flug | ✅ Sekundentakt mit Höhe, Kurs, AGL, Steigrate |

Die vollständige Liste steht in [`friesenbruegge/MESSLISTE.md`](friesenbruegge/MESSLISTE.md),
Abschnitt „X-Plane 12".

**Beide ZIPs liegen auf dem VPS** (MSFS 1.6.0, X-Plane 1.0.0), die Download-Seite zeigt sie.

---

### ⚠ Drei Dinge, die jede weitere Arbeit an der Brügge betreffen

**1. `pruefserver.py` ist neu — und löst ein Problem, das jede Umsetzung hat.**
Der Server liefert `soll` nur an einen über die Position zugeordneten Piloten. Richtig so —
aber damit lässt sich der halbe Funktionsumfang einer Brügge ohne VATSIM-Verbindung gar nicht
messen. Das hat heute Nacht eine Stunde gekostet (xPilot fand seinen eigenen Simulator nicht).

```powershell
py friesenbruegge/pruefserver.py                                 # lauscht auf 127.0.0.1:8099
py friesenbruegge/pruefserver.py --setzen tier_gross --neben 5
py friesenbruegge/pruefserver.py --leeren
```

Umgebogen wird die Brügge über eine Datei mit einer Zeile
(`<X-Plane 12>/Output/preferences/friesenbruegge.url`). Liegt sie nicht da, ist das Ziel fest
einkompiliert. **Nach dem Messen wieder löschen**, sonst meldet die Brügge an niemanden.
Für MSFS gibt es das Gegenstück noch nicht — wer es baut, hält sich an dieselbe Form.

**2. `seit_s` bedeutet in X-Plane etwas anderes als in MSFS.**
Beim Umsetzen läuft es dort **weiter** (gemessen: 74 s), statt bei null neu zu beginnen:
`XPLMInstanceSetPosition` verschiebt dieselbe Instanz, während MSFS das Objekt wegnehmen und
neu erzeugen muss. Wer serverseitig `seit_s` als „seit wann steht es dort" auswertet, baut
einen Fehler, der nur bei X-Plane-Piloten auftritt.

**3. `hoehe_gemessen` ist neu im Protokoll (`steht[]`), und der Server wertet es noch nicht aus.**
`hoehe_ft` ist in X-Plane nicht immer eine Messung: Außerhalb des geladenen Geländes trifft die
Probe nicht, das Objekt bekommt Meereshöhe — und das sieht aus wie ein Wattobjekt auf 0,0 ft.
Nach PROTOKOLL.md Abschnitt 4 soll der Server genau daraus schließen, ob eine Stelle taugt.
**Wer die Stellenbewertung baut, muss das Feld auswerten**, sonst sortiert er brauchbare
Stellen aus. Die MSFS-Brügge sendet es nicht — dort gibt es die beiden Fälle nicht.

---

### Was offen bleibt

- **Sichtbarkeitsreichweite in X-Plane** — für MSFS gemessen (Boot 1 km, Kreuzfahrtschiff
  22 km), hier unbekannt. Davon hängt ab, wie fein Kieker-Stationen gesetzt werden dürfen.
- **Das Nachrücken bei ungeladenem Gelände** (`hoehe_gemessen` false → true) — im Code
  vorgesehen, nie im Flug gesehen. Zusammen mit der Reichweite in einem Zug messbar.
- **1146 X-Plane-Katalogzeilen** ungeprüft. ⚠ Dabei gilt „gelistet ≠ ladbar": Die großen
  Schiffe liegen nur als `.agp` vor (Autogen-Punkte), von 403 `ships`-Zeilen sind 47 wirklich
  `.obj`. Ein Prüfwerkzeug, das nur die Datei sucht, produziert 356 falsche grüne Haken.
- **MSFS 2020** — Paket gibt es noch nicht.
- **macOS/Linux für X-Plane** — die Netzschicht ist WinHTTP. Der Rest ist plattformunabhängig;
  wer portiert, tauscht den `netz_*`-Block und sonst nichts.

---

### Ein Fehler, den ich gemacht habe, damit ihn niemand wiederholt

**Das X-Plane-Paket ging ungeprüft auf die Download-Seite, und der Changelog-Eintrag v14.34.0
war mit dem Deploy schon draußen** — er behauptete, es gebe das Paket, bevor irgendetwas
gemessen war. Der Nutzer hat das bemerkt („hätten wir das nicht zuerst testen sollen?"), und
`paket.ps1` warnt an genau dieser Stelle sogar selbst.

Zurückgenommen wird so etwas, indem das ZIP auf dem VPS umbenannt wird
(`.friesenbruegge-xplane.zip.ungeprueft`): Die Seite zeigt dann „Noch nicht verfügbar", und ein
`mv` bringt es zurück. **Der Banner darf dem Befund nie vorauslaufen** — er ist das, was die
Gruppe sieht.

---

## 2026-09-13 — Die zweite Brügge: X-Plane 12 (v14.34.0)

**Neu im Repo: `friesenbruegge/xplane/`.** Ein X-Plane-Plugin (`.xpl`, eine Windows-DLL), das
dasselbe Protokoll spricht wie das WASM-Modul. Gebaut, gepackt, in `D:\X-Plane 12`
installiert — **im Simulator noch nicht geflogen.**

**Was sich außerhalb dieses Ordners geändert hat, bitte beim Rebase beachten:**

| Datei | Änderung |
|---|---|
| `friesenbruegge/json.h` | **verschoben** aus `msfs/` — beide Brüggen binden sie jetzt als `../json.h` ein. Wer `msfs/bruegge.cpp` offen hat, muss den Include mitnehmen. |
| `app/main.py` | `_bruegge_zip_path(settings, simulator)` statt einargumentig; neuer Endpunkt `/download/bruegge-xplane`; `/api/bruegge-package` liefert zusätzlich `pakete: {msfs, xplane}` (die flachen MSFS-Felder bleiben) |
| `app/static/efb.html` | zweiter Download-Kasten, JS-Abfrage zu einer Funktion zusammengezogen |
| `friesenbruegge/PROTOKOLL.md` | neues Feld `hoehe_gemessen` in `steht`; `fahrzeug` für X-Plane zurückgenommen |
| `friesenbruegge/OBJEKTE.md` | X-Plane-Gattungstabelle, und was dort **nicht** geht |

**Zwei Befunde, die über X-Plane hinausgehen:**

1. **„Gelistet ≠ ladbar."** Die großen Schiffe im Katalog (`BulkCarrier`, `ContainerCarrier`,
   `OilTanker`, `LNGCarrier`) liegen nur als `.agp` vor — Autogen-Punkte, keine ladbaren
   Objekte. Von 403 `ships`-Zeilen sind **47** wirklich `.obj`. Wer die 1146 offenen
   X-Plane-Katalogzeilen prüft, muss das einrechnen; ein Prüfwerkzeug, das nur die Datei
   sucht, wird 356 falsche grüne Haken produzieren.
2. **`hoehe_ft` ist in X-Plane nicht immer eine Messung.** Die Terrain-Probe antwortet nur für
   geladenes Gelände; außerhalb bekommt das Objekt Meereshöhe, und das sieht aus wie ein
   Wattobjekt auf 0,0 ft. Deshalb `hoehe_gemessen`. **Der Server wertet das Feld noch nicht
   aus** — wer die Stellenbewertung aus Abschnitt 4 des Protokolls baut, fängt hier an.

**Offen, in dieser Reihenfolge:**

- **Im Simulator prüfen** — X-Plane starten, Objekt anfordern, hinsehen. Die Anleitung ist
  dieselbe wie für MSFS (`probe-msfs/FLUGTEST.md`): groß, nah und lange.
- **Hochladen.** Beide ZIPs liegen gebaut in `friesenbruegge/`, aber **noch nicht auf dem
  VPS** (`paket.ps1 -Hochladen`, je einmal). Solange zeigt die Download-Seite für MSFS
  Fassung 1.5.0 und für X-Plane gar nichts.
- macOS/Linux: Die Netzschicht ist WinHTTP. Der Rest des Plugins ist plattformunabhängig; wer
  portiert, tauscht den `netz_*`-Block und sonst nichts.

---

## 2026-09-12 (Nacht, danach) — Übernommen, dazu eine Karte im Admin (v14.31.1)

**Übergabe angenommen.** Ich arbeite mit derselben Arbeitskopie weiter; `bruegge.cpp` fasse ich
wieder an, seit sie frei ist.

**Dazugekommen seit der Übergabe:** eine **Karte im Brügge-Panel** (v14.31.1, deployt). Klick
setzt Breite und Länge, statt sie einzutippen — auf Nutzerwunsch, und der Abend hat den Grund
geliefert: Von Hand getippte Koordinaten waren die häufigste Fehlerquelle. Gebaut nach dem
Vorbild der AIP-Passung (`_dfsKarteAufbauen`), gleiches Esri-Satellitenbild.

Die Karte zeigt zugleich den Vergleich, um den es geht: **blau** die gemeldeten Positionen,
**grün** die Objekte, die wirklich dastehen, **rot** die angeforderten, die es nicht tun,
**gelb** die Stelle für das nächste. Damit ist Messliste-Punkt „steht es wirklich?" auf einen
Blick ablesbar, statt in einer Tabelle.

**Zu euren offenen Punkten:**

- **Punkt 2 (rutscht die Robbe?)** ist auch mein Verdacht, und er lässt sich **ohne** Robbe
  vorab eingrenzen: Von den `ASO_*` rollte das Fahrzeug 21 ft in zwei Minuten **einen Hang
  hinunter** und blieb dann stehen. Ob es auf ebenem Grund überhaupt losrollt, ist ungemessen.
  Wenn das Rutschen an der Hangneigung hängt und nicht am Modell, wäre eine Robbe auf flacher
  Sandbank unkritisch. **Der Test ist derselbe: hinsetzen, zwei Minuten warten, Höhe vergleichen.**
- **Punkt 1 (WASM löst Community-Titel auf?)** — die Karte hilft beim Ablesen: Eine `robbe`,
  die rot bleibt, während sie im `soll` steht, ist genau dieser Fall.

⚠ **Die Nullbyte-Falle hat heute zum zweiten Mal zugeschlagen:** `' '` in einem
Python-Heredoc wird beim Schreiben zum echten NUL-Byte in der `.cpp`. Der Compiler warnt nur
(`-Wnull-character`), gebaut wird trotzdem. Repariert per Byte-Ersetzung. Wer C-Quelltext per
Skript schreibt: hinterher `grep -c $' '` prüfen.

---

## 2026-09-12 (Nacht) — ÜBERGABE der Robben-Session: `bruegge.cpp` ist frei

**Diese Sitzung macht Schluss.** Der Nutzer arbeitet mit der anderen weiter. Alles ist
committet und gepusht, nichts liegt halb fertig herum.

### Erledigt

| | |
|---|---|
| Gattung `robbe` | drei Titel aus `human-library-animated`, **kein** Rückfall auf eine andere Art |
| `kann` | wird jetzt aus `g_gattungen` erzeugt statt aufgezählt — die Liste stand zweimal im Modul, und beim Eintragen von `robbe` meldete es prompt, es könne etwas nicht, das es konnte |
| **`fahrzeug` neu sortiert** | euer Fund, eingebaut: `ASO_CarUtility01`, `ASO_Pushback_White`, `ASO_Firetruck02`, `ASO_TruckUtility01`, `ASO_Tug01_White`. Im abgelegten Modul geprüft — `ASO_Firetruck01` kommt darin nicht mehr vor |
| Serverseite | `_BRUEGGE_GATTUNGEN` + `robbe`, Admin-Auswahl, Test (war ohne den Fix nachweislich rot), **v14.31.0 deployt** |
| Doku | `PROTOKOLL.md` (Katalog + Positivliste im Admin), `OBJEKTE.md`, `MESSLISTE.md` Abschnitt 8, **`docs/api.md` + `docs/architecture.md` + README** — die Brügge stand dort bis heute in KEINEM Dokument |
| Paket | **abgelegt**, 70 721 Bytes, Fassung 1.4.0. ⚠ MSFS läuft seit 21:35, abgelegt wurde um 22:10 → **erst ein Neustart aktiviert es** |

### Was offen ist

1. **Messliste 8, Punkte 1–4** — nach dem Sim-Neustart. Punkt 1 ist von der Existenz- zur
   Bestätigungsfrage geworden: Dass ein Community-Titel gesetzt werden kann, habt ihr belegt
   (Screenshot); dass das **WASM-Modul** ihn genauso auflöst wie euer externer Client, nicht.
   In `bruegge_steht` stand heute Abend keine einzige `robbe`-Zeile.
2. **Punkt 2 ist der heikelste:** Das Modell heißt `seal moving`, und ihr habt an den
   `ASO_*`-Fahrzeugen 21 ft Abrutsch in zwei Minuten gemessen. Also hinsetzen, **zwei Minuten
   warten**, nochmal hinsehen. Eine wandernde Kolonie wäre für einen Zähl-Event das Ende.
3. **Teil A, vorbereitet aber NICHT gemacht** (Nutzer hat nicht entschieden): Superspuds drei
   Dateien probeweise **lokal** nach `Community\friesenbruegge\SimObjects\Animals\frs_seehund\`
   legen, mit eigener `sim.cfg` und eigenem Titel. Damit wäre gemessen, ob ein Paket mit
   `content_type: MISC` (das ist die Brügge, wegen WASM) überhaupt `SimObjects/` indexiert —
   Superspuds Paket ist `SCENERY`. Ergebnis entscheidet: ein Paket für alles, oder zwei Ordner
   in einem Download. Nichts davon würde verteilt oder committet.
4. **Die Rechtefrage** steht samt fertigem Anfragetext in
   [`docs/offene-aufgaben.md`](docs/offene-aufgaben.md). Beschlossene Reihenfolge: **jetzt
   Abhängigkeit** (funktioniert, braucht keine Erlaubnis — einen Titel zu nennen ist keine
   Weitergabe), **parallel fragen**, **eigenes Modell nur wenn nötig** und dann als *zweiter*
   Titel hinter seinem. Ein eigenes Modell gehört NICHT ins Repo — es ist öffentlich.

### ⚠ Eine Sache zum Nachschlagen, falls jemand den Bestand neu erhebt

`find` ohne `-L` sieht den Community-Ordner nicht (**9** `sim.cfg` statt **309**) — daher stand
in `OBJEKTE.md` „keine Robben". Pythons `Path.rglob` dagegen folgt den Junctions und findet
alle drei; `kieker_probe.py` ist also in Ordnung, dort ist nichts zu reparieren. Ich hatte das
zwischenzeitlich anders behauptet und eine „Korrektur" in `kieker_probe.py` begonnen — sie ist
zurückgenommen, die Datei ist unberührt. Mein Gegentest war kaputt (`xargs` zerlegt „ahqa seal
moving" am Leerzeichen).

---

## 2026-09-12 (Abend) — GROSSE Bruegge-Sitzung: 1.0.1 → 1.3.0, mehrere Altbefunde widerlegt

**Betrifft `friesenbruegge/` UND `app/` (v14.30.1, ausgeliefert).** Eine zweite Session
arbeitet parallel an der Bruegge — **bitte diesen Eintrag ganz lesen, bevor etwas auf den
Altbefunden aufgebaut wird.**

### Angefasste Dateien

`app/database.py` (neue Tabelle `bruegge_steht`, Spalte `bruegge_soll.auf_boden`, beide mit
Migration) · `app/main.py` (Endpunkt wertet `steht` aus, loggt `antwort_zu_gross`) ·
`app/static/admin.html` (Spalte „steht wirklich?“) · `tests/test_bruegge_endpunkt.py` ·
`friesenbruegge/msfs/bruegge.cpp` (1.0.1 → **1.3.0**) · `friesenbruegge/msfs/paket.ps1` ·
`PROTOKOLL.md` · `MESSLISTE.md` · **neu: `OBJEKTE.md`**

### ⚠ Vier Altbefunde sind WIDERLEGT — nicht mehr zitieren

1. **„Aus der Ferne ist `steht[].hoehe_ft` unbrauchbar“** (Eintrag direkt darunter, Bodensee
   2106,5 ft). **Falsch gedeutet:** Die Meldung log nie — das Objekt stand wirklich dort, weil
   die *gerechnete* Hoehe falsch war. Mit `auf_boden: 1` (`OnGround=1`) meldeten vier Sonden
   aus 1, 3, 6 und **10 km** korrekte Gelaendehoehen; die 10-km-Sonde traf den Bodensee-Spiegel
   auf 0,1 ft genau (1297,5 gegen 1297,6 ft).
2. **„`OnGround=1` ist aus WASM unbrauchbar“** (`probe-msfs/ERGEBNIS.md`). Galt nur fuer
   **ein Modell an einem Ort** (`Boat01` auf Wangerooge). Vier von fuenf Gattungen setzen sauber
   auf. **Fuer MSFS 2020 weiterhin ungemessen.**
3. **„Die Gleichzeitigkeit ueberfordert den Simulator.“** Nein — 30 Objekte in einem Zug gehen
   fehlerfrei, samt gleichzeitigem Versetzen, bei 89,4 FPS.
4. **„Der Sondenumweg ist noetig.“** Gestrichen (Nutzerentscheidung): `auf_boden: 1` genuegt
   allein. Die Idee bleibt in MESSLISTE 2c aufgehoben — **falls MSFS 2020 das Flag ignoriert.**

### Was am Modul neu ist (alles im Flug belegt)

| | |
|---|---|
| **Das Paket lud gar nicht** | UTF-8-**BOM** in `manifest.json`/`layout.json` (`Set-Content -Encoding UTF8` unter PS 5.1). `paket.ps1` schreibt jetzt BOM-frei und **prueft sich selbst**. |
| `AIRemoveObject` | wieder drin — ohne ihn verdoppelt **jeder** Verbindungsabriss die Objekte |
| Objekte **versetzen** | geht jetzt (gleiche `id`, neue Koordinate); vorher passierte stillschweigend **nichts**, waehrend `steht` Erfolg meldete |
| `ANTWORT_PUFFER` | 4096 → **16384**; bei 30 Objekten waren 3776 Bytes erreicht. Eine zu grosse Antwort wird jetzt **verworfen statt halb gelesen** und als `antwort_zu_gross` gemeldet |
| Exception-Zuordnung | ueber `GetLastSentPacketID` **exakt statt geraten** — vorher galt ein sichtbar dastehender Baer als „fehlgeschlagen“ und war nie mehr abraeumbar |
| Titel je Gattung | **Liste statt Einzelname** (`ASO_Ambulance_Japan` gibt es nur in MSFS 2020) |

### Serverseite

`steht` wurde **seit Fassung 1 weggeworfen** — der Endpunkt las den Block nicht aus. Jetzt in
`bruegge_steht` (Schluessel `(kennung, id)`), im Admin neben der Anforderung sichtbar, und im
Aufraeumer beruecksichtigt.

## 2026-09-12 (Nacht) — Titelliste `fahrzeug` ist falsch sortiert (fuer die Robben-Session)

**Kleine Sache, aber sie kostet sonst einen Sim-Neustart zum Suchen.** In `g_gattungen` stehen
bei `fahrzeug` zwei Titel vorn, die in MSFS 2024 **nicht existieren**:

```c
{ "fahrzeug", { "ASO_Firetruck01", "ASO_FuelTruck01_White", … } }   // beide gehen NICHT
```

Ich habe in der Nacht alle 37 Fahrzeugtitel einzeln im laufenden Simulator geprueft
(`probe-msfs/titel_schau.py`). **Es fehlen genau sechs:** `ASO_Ambulance_Japan`,
`ASO_Firetruck01`, `ASO_FuelTruck01_Black`, `ASO_FuelTruck01_White`, `ASO_FuelTruck02_Black`,
`ASO_FuelTruck02_White`, `ASO_Ground_Power_Unit`. Die uebrigen 31 laufen.

**Vorschlag, in dieser Reihenfolge:**

```c
{ "fahrzeug", { "ASO_CarUtility01", "ASO_Pushback_White", "ASO_Firetruck02",
                "ASO_TruckUtility01", "ASO_Tug01_White", nullptr } },
```

Die Nachrueck-Mechanik faengt den Fehler zwar ab — sie kostet aber je Fehlschlag einen Takt
und eine Exception, und der erste Eindruck im Admin waere ein rotes `EXCEPTION_22`.

**Ich fasse `bruegge.cpp` nicht an** (wie abgesprochen) — baut es bitte bei Gelegenheit mit ein.

⚠ **Und wir teilen dieselbe ARBEITSKOPIE**, nicht nur dasselbe Repo. Ich habe eure
`robbe`-Gattung im Quelltext gefunden, bevor ich sie auf `origin` gesehen habe. Uncommittete
Aenderungen sind fuer die jeweils andere Seite also sofort sichtbar und ueberschreibbar.

### Weitere geprüfte Titel, falls ihr Gattungen ergaenzt

| Gattung | funktioniert (alle einzeln geprueft) |
|---|---|
| Tiere klein | `Seagull`, `Goose`, `Flamingo` |
| Tier Wasser | `HumpbackWhale` |
| Marken | `Flag_Checker`, `Flag_Orange`, `Flag_Yellow`, `Flag_RWB` + 8 weitere `Flag_*` |
| Landepunkte | `SI_SimObject_Fly-In_Landing_{Blue,Green,Red,Yellow}_Dot` (Addon SayIntentions) |
| **Rauch/Feuer** | `SIAI_VFX_Smoke_Red/Orange`, `SIAI_VFX_Fire`, `SIAI_SignalFire`, `SIAI_VFX_WildFire` |
| Kegel, Schilder | `SI_SimObejct_Cone`, `SI_SimObejct_Event_Parking_Signs_{Left,Right,Straight}` |

⚠ **Rauch ist fuer die Auffindbarkeit interessant:** Ein `Boat01` ist erst ab rund 1 km
eingeblendet (11.09. gemessen). Eine Rauchsaeule sieht man kilometerweit.

---

### ⚠⚠ ES GIBT SCHON EINE ROBBE — und sie ist animiert (12.09.2026, spaet)

**Bevor ihr ein Modell baut, lest das.** Im Community-Ordner dieses Rechners liegt
`human-library-animated` (Superspud, Paketversion 1.4.0). Darin:

```
ahqa seal moving      ← die Robbe. Gesetzt, gezeichnet, im Screenshot belegt.
ahqa sea lion moving  ahqa walrus moving  ahqa puffin walking
```

**Alle dreissig Tiere dieser Bibliothek tragen `walking`, `running` oder `moving` im Namen —
die Animation steckt im Modell.** Damit erledigt sich die Frage, wie man Beine und Kopf
bewegt: gar nicht ueber SimConnect, sondern ueber die Wahl des Modells.

Weiter drin: `deer running`, `stag`, `moose bull/cow`, `boar`, `fox`, `wolf running`,
`coyote`, `cow` (4 Sorten), `sheep`, `goat`, `pig`, `donkey`, `shetland pony`, `chicken`,
`goose`, `crocodile`, `gazelle`, `buffalo african`, `ibex`, `dog` (2). Volle Liste ueber
`find -L .../Community -path "*SimObjects/*" -name sim.cfg -exec grep -h title= {} \;`.

**Der Haken:** Es ist ein Community-Addon, kein Bordmittel — jeder Pilot muesste es haben.

**Und genau dafuer ist die Titelliste in `g_gattungen` da** (s. unten): Ein Eintrag

```c
{ "robbe", { "ahqa seal moving", "<euer eigenes Modell>", nullptr } },
```

nimmt Superspuds Robbe, wenn sie installiert ist, und faellt sonst auf euer Modell zurueck.
Scheitert der erste Titel, rueckt seit Fassung 1.3.0 automatisch der naechste nach. **Kein
Pilot wird ausgeschlossen, und wer das Addon hat, bekommt eine bewegte Robbe.**

⚠ **Das heisst nicht, dass euer Modell ueberfluessig waere** — es ist der Rueckfall fuer alle
ohne das Addon, und ihr habt die `sim.cfg` selbst in der Hand. Aber ihr koennt euch an einem
funktionierenden Beispiel orientieren, statt bei null anzufangen:
`Community/human-library-animated/SimObjects/Animals/ahqa seal moving/sim.cfg`.

### Was von den BORDMITTELN in MSFS 2024 wirklich geht (127 Titel einzeln geprueft)

Mit `probe-msfs/titel_schau.py` (neu) im laufenden Simulator durchprobiert:

| | |
|---|---|
| **Boote** | **14 von 14** — Boat01/02, FishingBoat, FishingShip02/03, Yacht01-03, CargoShip01, CargoContainer/Gas/Oil01, CruiseShip01/02 |
| **Landmarks, Flaggen, Misc** | **alle** — `windmill`, `windsock`, `Windsock_05/08/NoBase`, 12 `Flag_*`, `Parachute`, `Marshaller_Stick` |
| **Fahrzeuge** | **31 von 37** — es fehlen `ASO_Ambulance_Japan`, `ASO_Firetruck01`, beide `FuelTruck01/02_*`, `ASO_Ground_Power_Unit` |
| **Tiere (2020er Titel)** | **nur 7 von 45**: `BlackBear`, `GrizzlyBear`, `SyrianBear`, `Flamingo`, `Goose`, `Seagull`, `HumpbackWhale` |
| **Tiere (2024er)** | **0 von 11** — der Ordnername ist NICHT der Titel, die `sim.cfg` ist gepackt. Auch mit `_EX1` abgelehnt. **Wissensluecke, kein Mangel.** |

⚠ **Viele Fahrzeugtitel sind nur Farbvarianten desselben Modells**
(`ASO_Boarding_Stairs` / `_Red` / `_Yellow`), was beim Durchsehen wie eine Wiederholung wirkt.

⚠ **Alle `ASO_*`-Fahrzeuge ROLLEN WEG** — gemessen 21 ft Hoehenverlust in zwei Minuten an
einem Hang. Als ortsfeste Marke taugen sie nicht; als bewegliches Ziel womoeglich schon.

### Fuer die parallele Session — sie baut die ROBBEN

**Wir kommen uns nicht ins Gehege, wenn wir uns an eine Stelle halten:** Die Robben brauchen
in der Bruegge genau **einen** Eintrag, und zwar in `g_gattungen` (`msfs/bruegge.cpp`, direkt
ueber `titel_fuer`). Dort steht je Gattung eine Titelliste:

```c
{ "tier_gross",  { "BlackBear", "GrizzlyBear", … , nullptr } },
```

Ein Robben-Eintrag waere z. B. `{ "robbe", { "<euer Titel>", nullptr } }` — **mehr ist an der
Bruegge nicht zu tun.** Der Server kennt Gattungen ohnehin nur als Text; die Pruefliste im
Admin steht in `app/main.py` (`admin_bruegge_soll_setzen`, Gattungspruefung).

**Ich fasse `bruegge.cpp` ab jetzt nur noch an, wenn es sich nicht vermeiden laesst** — sagt
Bescheid, wenn ihr die Zeile selbst setzt, dann bleibe ich ganz weg.

### ⚠ Drei Befunde, die den Robbenbau direkt betreffen

1. **Es gibt keine Robben im Bestand** — weder in MSFS 2020 (45 Tiertitel) noch in 2024
   (41 Tierpakete). Vollstaendige Listen in **`friesenbruegge/OBJEKTE.md`**.
2. **`devprops-counting-seals-frisian-islands` loest es ueber SZENERIE (BGL)** — und Szenerie
   laesst sich zur Laufzeit **nicht** setzen. Fuer die Bruegge braucht es ein echtes
   **SimObject** (`SimObjects/Animals/<Name>/sim.cfg` mit `title=`), kein `modellib.BGL`.
3. **Das Paket darf KEIN UTF-8-BOM in `manifest.json`/`layout.json` haben.** Sonst wird es
   registriert, gemountet und in der `Content.xml` als „Activated“ gefuehrt — und trotzdem
   lautlos uebergangen (`MyLibrary init … took 0.0002`, kein „WASM: Module … loaded“). Das hat
   hier einen ganzen Tag gekostet. Pruefen mit
   `head -c 3 manifest.json | od -An -tx1` → muss `7b` sein, nicht `ef bb bf`.

### Und was die Bruegge fuer Robben schon kann (alles im Flug belegt)

| | |
|---|---|
| auf den Boden setzen | `auf_boden: 1` genuegt, ohne Hoehenangabe — auch 10 km entfernt |
| wegnehmen, versetzen | ja, seit 1.1.3/1.2.1 |
| 30 Stueck auf einmal | fehlerfrei, 89,4 FPS |
| **bewegen** | nur ueber Versetzen, und das **springt sichtbar**. Fluessig waere `SetDataOnSimObject` — ungemessen |
| **Animation (Beine, Kopf)** | Modelle haben sie (DevMode „Play Animation“), ueber SimConnect aber **nicht dokumentiert** — offener Feature-Request bei Asobo, ohne Antwort. **Fuer ein EIGENES Robbenmodell ist das womoeglich leichter, weil ihr die `sim.cfg` selbst schreibt.** |

### Sonstiges fuer die parallele Session


- **`bruegge.cpp` ist stark umgebaut** (1.0.1 → 1.3.0). Bei Konflikten: meine Fassung ist im
  Simulator belegt, die Befunde stehen in `MESSLISTE.md`.
- **`MESSLISTE.md` ist jetzt das Hauptdokument** — alle sieben Punkte abgehakt plus 2b, 2c, 2d,
  3b, 3c, 5b, 5c, 5d. Wer etwas an der Bruegge aendert, liest es zuerst.
- **`OBJEKTE.md` ist neu:** Titellisten je Simulator, aus der Installation ausgelesen. ⚠ Darin
  der Befund, der den Kieker am meisten angeht: **weder MSFS 2020 noch 2024 bringt Robben mit.**
- X-Plane war bereits am 11.09. vermessen (`probe-xplane/ERGEBNIS.md`) — **erst dort nachsehen,
  nicht suchen.** Dort gibt es mit `XPLMProbeTerrainXYZ` eine echte Gelaendeabfrage.

---

## 2026-09-12 — Gattung `robbe` + Messliste 8 (Bruegge 1.4.0)

**Betrifft nur `friesenbruegge/`.** Kein Anwendungscode, keine FriesenSpy-Version, kein
CHANGELOG-Eintrag.

⚠ **Eine zweite Sitzung arbeitet parallel an der Bruegge.** Angefasst wurden genau drei
Dateien — wer dort gleichzeitig schreibt, liest sie vor dem Rebase neu:

| Datei | Was |
|---|---|
| `msfs/bruegge.cpp` | `BRUEGGE_VERSION` 1.3.0 → **1.4.0**, neue Gattung `robbe` am Ende von `g_gattungen` |
| `MESSLISTE.md` | neuer Abschnitt **8** (hinter 7, vor „Was NICHT mehr zu messen ist") |
| `OBJEKTE.md` | neuer Abschnitt „Robben", Warnkasten `find -L`, „Offen"-Punkt ersetzt |

**Der Fund dahinter:** Robben gibt es doch — als **SimObject** im Community-Paket
`human-library-animated` (`ahqa seal moving`, `ahqa sea lion moving`, `ahqa walrus moving`).
Dass `OBJEKTE.md` das bisher bestritt, lag an der Suche: `find` steigt ohne `-L` nicht in die
Community-Symlinks, und dort lagen 32 Tier-SimObjects.

**Ungemessen und fuer alles Weitere entscheidend (Messliste 8):** Ob
`AICreateSimulatedObject` einen Titel aus einem **Community**-Paket ueberhaupt findet — alle
bisher belegten Titel stammen aus Asobos Bordbestand. Faellt das negativ aus, ist auch ein
eigenes Robben-Paket auf diesem Weg tot. **Deshalb wird erst gemessen, dann verpackt** — wer
in der Zwischenzeit ein Modellpaket baut, baut auf Sand.

### Nachtrag, nach dem Eintrag darueber (Uebergabestelle gelesen)

**Die Zeile in `g_gattungen` ist gesetzt** (`c78bf78`) — `bruegge.cpp` ist von hier aus fertig,
mehr braucht die Robbe am Modul nicht. Wer dort weiterarbeitet, hat freie Bahn.

**Und die vier widerlegten Altbefunde sind eingearbeitet:** Messlisten-Abschnitt 8 stand
zuerst mit dem Sondenumweg da (Objekt setzen, Hoehe ablesen, wegraeumen). Er prueft jetzt
`auf_boden: 1` ohne Hoehenangabe, und die Animationsfrage ist umgedreht — **ausloesen** laesst
sich nichts (ueber SimConnect nicht dokumentiert), gefragt ist, ob die Robbe von selbst
losrobbt. Fuer einen Zaehl-Event ist eine wandernde Kolonie das Ende, und Punkt 2d zeigt, dass
Tiere genau das tun.

⚠ **`bruegge.wasm` ist weiterhin NICHT neu gebaut** — im Community-Ordner liegt 1.3.0, der
Quelltext sagt 1.4.0. Wer als Erster baut, baut den gemeinsamen Arbeitsbaum mit; bei
gleichzeitiger Arbeit also vorher absprechen.

⚠ **`bruegge.wasm` ist NICHT neu gebaut.** Wer baut, kompiliert den Stand des gemeinsamen
Arbeitsbaums mit — bei paralleler Arbeit also erst absprechen, sonst liegt halbfertiger Code
im Community-Ordner (und ein Sim-Neustart ist dann noetig, um ihn wieder loszuwerden).

---

## 2026-09-11 (spaet) — Protokoll war in sich widerspruechlich (Sim-Sitzung)

**Betrifft nur `friesenbruegge/`.** Kein Anwendungscode, keine Version.

Der Eintrag darunter beschreibt die Entscheidung „keine Anmeldung“. Sie war aber nur in
Abschnitt 5 umgesetzt — die Abschnitte 1 und 2 trugen den verworfenen Schluessel weiter
(`Authorization: Bearer`, `401`, Zustand je `(schluessel, instanz)`, `naechste_frage_in_s: 10`).
Ist in `e6f5997` bereinigt. **Wer PROTOKOLL.md vor diesem Commit gelesen hat, liest Abschnitt 1
neu.**

Neu festgelegt: Passt eine Position zu **niemandem**, antwortet der Server genau wie bei
„kein VATSIM“ — leeres `soll`, Minutentakt. Fuer die Bruegge ununterscheidbar, mit Absicht:
Eine Fehlermeldung waere ein Werkzeug fuer den, der ausprobiert, welche erfundene Position
durchgeht.

**Messbefunde am laufenden MSFS 2024** (`probe-msfs/kieker_probe.py` hat jetzt eine
Kontrollspur — die eigene Lage laeuft neben der Objektlage mit, sonst ist „keine Meldung mehr“
mehrdeutig):

- **Aus der Ferne ist `steht[].hoehe_ft` unbrauchbar.** Dieselbe Koordinate am Bodensee:
  2106,5 ft bei 691 km Entfernung, 1297,2 ft aus der Naehe — 810 ft Unterschied. Der Simulator
  antwortet aus grobem Gelaende. Steht jetzt in Abschnitt 4: Der Server darf die Hoehe nur
  auswerten, wenn der Pilot in der Naehe ist. Wie nah, ist NICHT gemessen (brauchbar bis 200 km,
  falsch bei 691 km, dazwischen Luecke).
- **Objekte bleiben stehen** — zweimal 240 s durchgehend, 0,5 km und 691 km entfernt, exakt
  240 Meldungen je Lauf. Ein frueherer Lauf, der bei t=+45s verstummte, ist nicht
  reproduzierbar; dort wurde vermutlich der Sim beendet. Der Protokollzustand `verschwunden`
  bleibt trotzdem begruendet (MSFS 2020 verhielt sich zweimal verschieden), ist in MSFS 2024
  aber kein Regelfall.
- **Objekte ueberleben das Schliessen der Verbindung nicht** (`EXCEPTION 3` in der Nachprobe) —
  bestaetigt Abschnitt 7.

---

## 2026-09-11 (abends) — Protokoll ueberarbeitet: keine Anmeldung mehr (Sim-Sitzung)

**Betrifft `friesenbruegge/`, `docs/` und die Issues #23/#25** — kein Anwendungscode, keine
Version, kein CHANGELOG-Eintrag. Live blieb v14.29.0.

**Wer an der Server-Seite arbeitet, liest `friesenbruegge/PROTOKOLL.md` Abschnitt 5 neu.**
Der Entwurf mit einem Bruegge-Schluessel ist verworfen, ebenso der Nachfolger, der
`panel_devices` mitbenutzt haette. Es gibt **gar keine Anmeldung** mehr:

- Die Bruegge schickt **keinen Schluessel und keine CID**. Der Server erkennt den Piloten am
  **Positionsmatching** gegen `live_positions`.
- **Dafuer werden die Regeln des EFB uebernommen**, nicht neue erfunden:
  `_verkehrZusammenfuehren` (`app/static/index.html:6026`), einschliesslich der Konstanten bei
  `:5948-5971`. Wandert das Matching in den Server, gehoeren sie an EINE Stelle statt in zwei
  Dateien mit zwei Wahrheiten.
- **Authentifiziert wird ueber die CID**: eine Zeile in `forum_callsign` beweist den
  Forum-Login. NICHT ueber das Callsign -- das braeche beim N-Verlust (FRS123N -> FRS556),
  weil die Tabelle erst beim naechsten Login nachzieht (`app/main.py:2755-2766`).
- **Ohne VATSIM geschieht nichts**: keine Zeile in `live_positions` -> keine Zuordnung, keine
  Anzeige, keine Ablage. Die Pruefung steht VOR allem Teuren und ist ein Blick auf einen
  Primaerschluessel.
- **Regeltakt 1 s** (vorher 2 s). Gemessen in `position_history`: Spitze 13 gleichzeitig
  fliegende Friesen ueber 30 Tage, Mittel 1,58. **Voraussetzung ist eine eigene nginx-Zone**
  fuer `/api/bruegge/` -- 60 r/min waeren in der gemeinsamen Zone die halbe Ration einer IP.
- Die Bruegge-Position gehoert in eine **eigene** Ablage, nicht in `live_positions`: Der
  Poller wuerde sie sonst dreimal je Minute mit dem groberen VATSIM-Stand ueberbuegeln
  (`INSERT OR REPLACE`, `app/database.py:2280`).

**#23 ist auf denselben Stand gebracht** -- ein Endpunkt, zwei Quellen, eine Pruefung. Dort
steht auch ein Messergebnis, das dieses Vorhaben unmittelbar trifft: **Aus WASM heraus ist das
Lesen der eigenen Position gescheitert** (`EXCEPTION 3`, `probe-msfs/wasm/modul.cpp:183`).
Objekte setzen geht; die eigene Lage lesen nicht. Solange das offen ist, fuehrt der Weg fuer
die Positionsmeldung ueber die EFB-Seite oder ein externes Programm.

**Zwei Korrekturen an frueheren Aussagen dieser Sitzung**, beide vom Nutzer angestossen:

- Der Bodensee-Befund ("die Kategorie `Boat` ist kaputt") gilt **MSFS 2020**. In MSFS 2024
  findet auch ein Boot den Grund -- auf Wangerooge gemessen (2,4 ft, im Bild), waehrend
  dasselbe Modell in 2020 auf 0,0 ft lag. Der Katalog fuehrt die Hoehen-Semantik jetzt je
  Simulator; der Binnensee-Fall ist fuer 2024 **ungemessen**.
- `alt_agl_ft` ist in MSFS **nicht** nur ueber Umwege zu haben: `PLANE ALT ABOVE GROUND` ist
  ein Standard-SimVar. Der Umweg betrifft das EFB im Browser, nicht SimConnect.

## 2026-09-11 — Bruegge-Protokoll Fassung 1 geschrieben, Deploy-Filter gesetzt (Sim-Sitzung)

**Betrifft `friesenbruegge/`, `docs/` und `.github/`** — kein Anwendungscode, keine Version,
kein CHANGELOG-Eintrag. Live blieb v14.29.0.

- **`friesenbruegge/PROTOKOLL.md`** angelegt: der Vertrag zwischen Server und Bruegge, der
  dreimal umgesetzt wird (MSFS 2020, MSFS 2024, X-Plane 12). Schritt 2 der Reihenfolge aus
  #25, und die Vorbedingung fuer jede Codezeile im Paket. **Vom Nutzer noch nicht abgenommen.**
- **Wer an der Server-Seite arbeitet, liest dort Abschnitt 1 und 4.** Zwei Dinge daraus
  betreffen `app/` unmittelbar:
  - Ein Endpunkt `POST /api/bruegge/melden` traegt Position **und** Sollzustand. Er bedient
    damit #23 nebenbei mit — dieselbe Nutzlast, dieselbe Richtung.
  - **Der Server muss `steht[].hoehe_ft` auswerten.** FriesenSpy hat kein Gelaendemodell und
    kann nicht wissen, ob an einer Koordinate Wasser auf Meereshoehe liegt; die Rueckmeldung
    der tatsaechlich erreichten Hoehe ist der einzige Weg, eine untaugliche Stelle zu
    erkennen. Raten waere der Anfang einer neuen Fehlersuche.
  - Vor der ersten Auslieferung: **eigene nginx-`location` mit eigener Rate-Limit-Zone** fuer
    `/api/bruegge/`. Die vorhandene Zone gilt je IP, nicht je Geraet — Bruegge und Kniebrett
    eines Piloten teilen sich sonst 120 Anfragen pro Minute.
- **`paths-ignore` im Deploy-Workflow** gesetzt fuer `docs/**`, `friesenbruegge/**`,
  `msfs-panel/**` und `**.md`. Anlass war Nutzerkritik: 15 Pushes an einem Tag haben 15
  Container-Neustarts ausgeloest, keiner davon beruehrte `app/`. Ein Deploy reisst offene
  SSE-Verbindungen und Kniebretter ab (s. CLAUDE.md). Bewusst als Ausschluss-, nicht als
  Einschlussliste — eine vergessene Zeile kostet dann einen ueberfluessigen Deploy statt
  eines ausbleibenden.

## 2026-09-11 — Probefluege am Simulator: alle drei Simulatoren gemessen (Sim-Sitzung)

**Betrifft `friesenbruegge/` und `docs/`** — kein Anwendungscode, keine Version, kein
CHANGELOG-Eintrag. Live blieb v14.29.0.

- **Die Torfrage aus #20 ist beantwortet: ja.** Objekte lassen sich zur Laufzeit setzen, in
  **MSFS 2024, MSFS 2020 und X-Plane 12** — jeweils mit Screenshot belegt. Fuer MSFS zusaetzlich
  **beide Auslieferungswege** erprobt: extern ueber `exe.xml` und als WASM-Modul im
  Community-Ordner, aus einem gemeinsamen Quelltext.
- **Ordner `sim-bruecke/` → `friesenbruegge/`** (Nutzerentscheidung; „Bruegge" ist Platt fuer
  Bruecke). Darin `probe-msfs/` und `probe-xplane/`, je mit `ERGEBNIS.md`.
- **Ausfuehrlicher Kommentar an #25** mit allem, was das Protokoll betrifft.

**Drei Befunde, die jede weitere Planung betreffen:**

1. **Objekte sterben mit der SimConnect-Verbindung.** Die Bruegge muss durchlaufen, ein
   Einmal-Aufruf hinterlaesst nichts.
2. **Die Objektart bestimmt die Hoehe.** `Boat` versinkt ueber Land (auf Wangerooge drei Meter
   tief im Platz), `Animal`/`StaticObject`/`GroundVehicle` landen auf **Gelaendehoehe**. Das
   gehoert in die Gattungstabelle des Protokolls. **Die Kategorie `Boat` ist kaputt** und darf
   nicht verwendet werden: Am Bodensee (Spiegel 1296 ft) lag ein Kreuzfahrtschiff auf 0,0 ft,
   waehrend Windmuehle, Baer und Fahrzeug an derselben Stelle 1297,0 ft meldeten. Seit 2022 im
   MSFS-DevSupport gemeldet, ohne Antwort von Asobo.
3. **Ein gesetztes Objekt bleibt nicht garantiert** (in MSFS 2020 beobachtet): zweimal derselbe
   Aufruf, einmal nach einer Sekunde weg, einmal 600 s stabil. Nach dem Setzen gehoert eine
   Lagemeldung abonniert.

**Was in der Spec aus Herleitung stammte und jetzt widerlegt ist:** Der Container-Titel
`Boat_Small` existiert nicht (echt sind `Boat01`, `FishingBoat`, …), die Exception-Nummern im
Probe-Skript waren ab 12 falsch, und **eigene 3D-Modelle sind keine Voraussetzung** — der
Simulator liefert zaehlbare Tiere mit (Baer, Elefant, Giraffe; in X-Plane Hirsche und Moewen).

**Beim Rebase zu beachten:** Diese Sitzung hat ausschliesslich `friesenbruegge/` und `docs/`
angefasst, nie `app/`. Wer an der Spec arbeitet: Abschnitte 13.2 und 13.4 sind nachgezogen,
die Messergebnisse dort haben Vorrang vor allem Hergeleiteten.

**Fuer die naechste Sitzung am Simulator** — drei Dinge haben je etwa eine Stunde gekostet und
sind vermeidbar:
- **Die DevMode-Konsole gehoert an den Anfang.** Ein WASM-Modul, das die Validierung nicht
  besteht, ist von aussen nicht von einem zu unterscheiden, das nichts tut. Vier Sim-Starts
  lang wurde von aussen geraten, waehrend die Konsole die Antwort bereithielt.
- **Eine Regel nie an einem einzigen Objekttyp pruefen.** `Altitude`, `OnGround` und
  `SetDataOnSimObject` schienen alle wirkungslos — weil ausschliesslich an Booten erprobt.
- **Sichtpruefungen gross, nah und lange ansetzen**, am besten neben etwas bereits Sichtbarem.
  Dreimal hiess es „ich sehe nichts", und dreimal war das Objekt da.

## 2026-09-11 — Vier neue Eventtyp-Issues, Spec-Arbeit, keine Codeaenderung (Server-Sitzung)

**Betrifft nur `docs/` und `CLAUDE.md`** — kein Anwendungscode, keine Version, kein
CHANGELOG-Eintrag. Live blieb v14.29.0.

- **Spec** `docs/superpowers/specs/2026-09-11-friesenkieker-design.md` angelegt (Eventtyp
  FriesenKieker), einmal adversarisch gegengeprueft (12 Funde eingearbeitet), danach auf
  Nutzerentscheid umgestellt: die Zwischenstufe auf fest gebaute Szenerie ist **verworfen**,
  der Probeflug ist das Tor.
- **Neue GitHub-Issues:** #23 (Kniebrett meldet Position zurueck), #24 (FriesenBaake,
  Schnitzeljagd), #25 (Sim-Bruecke, event-unabhaengiger Spawner). #20 wurde mehrfach
  ergaenzt.
- **Ordner-Umbenennung** `msfs-kieker/` → `sim-bruecke/` (inzwischen von der Sim-Sitzung
  weiter zu `friesenbruegge/`). Alle Verweise nachgezogen, historische Rueckverweise
  absichtlich stehen gelassen.
- **`CLAUDE.md` um zwei stehende Regeln ergaenzt:** „Ein MAJOR gehoert an die sichtbare
  Aenderung" (Hauptnummer erst bei Frontend ausserhalb Admin, und der Schritt wird vorher
  abgesprochen) und ein Verweis auf **diese Datei** — sie stand bis dahin nirgends, und
  genau deshalb hat diese Sitzung sie erst nach Stunden gefunden.
- **`docs/offene-aufgaben.md`:** Abschnitt „X-Plane mitdenken" (vom Nutzer vorgemerkt).

**Beim Rebase zu beachten:** Die Sim-Sitzung hat am selben Tag parallel gemessen und dabei
Spec und Ordner weiter veraendert. Ihre Messergebnisse haben Vorrang vor allem, was in der
Spec aus Herleitung stammt.

## 2026-09-05 — Schreibsperren, Poll-Messpunkte, Events-Karte (v14.20.6)

**Betrifft `app/poller.py`, `app/database.py`, `app/static/index.html`** — beim Rebase beachten.

- `_check_transport_events` sammelt die Abschlusssprüche jetzt in `summary_jobs` und erzeugt sie
  **nach** `conn.close()`. Wer dort einen `await` in die Schleife zurückholt, holt die
  Schreibsperre über den Netzabruf zurück (GitHub-Issue #15).
- `get_connection` setzt `PRAGMA busy_timeout=15000` (Issue #14).
- `_poll_once` trägt Marken (`uhr.marke(...)`) an fünf Stellen; ab 2 s Gesamtlaufzeit landet die
  Aufschlüsselung als WARNING im Log (Issue #16 — die Ursache ist damit **nicht** behoben,
  nur messbar gemacht).
- `index.html`: `_gueltigerTrackpunkt` (verwirft (0,0)) und `_spurenAusserhalb` stehen direkt vor
  `renderEventsMap`, dazu das Element `#ev-map-hinweis` im Kartencontainer (Issue #18).

## 2026-08-16 — Karten-Merker auf dem Server (v13.6.3)

**Betrifft `app/static/index.html`, `app/main.py`, `app/database.py`** — bitte beim Rebase
beachten, `index.html` wird gerade von zwei Seiten angefasst.

**Dieser Eintrag ersetzt einen frueheren.** Er beschrieb einen Cookie-Speicher (v13.6.0/13.6.2)
— der Weg ist **verworfen**. Wer ihn noch im Kopf hat: Es gibt kein `fs_karte` als Wahrheit
mehr, nur noch als lokalen Zwischenspeicher.

**Was gilt:** Alle Karten-Merker laufen ueber `_prefLies(key)` / `_prefSchreib(key, wert)`.
Fuehrende Quelle ist `GET/PUT /api/prefs?kontext=panel|web`, Tabelle `panel_prefs`
(cid + kontext). Die **Signaturen der bekannten Zugriffsfunktionen sind unveraendert**
(`_loadLayerPref`, `_loadAIPPref`, `_loadFsePref`, `_naviLies`, …) — wer sie aufruft, merkt
nichts. Nur wer `localStorage.getItem('friesenspy_…')` direkt liest, greift ins Leere.

**Warum:** Im Kniebrett haelt kein Browser-Speicher ueber einen Sim-Neustart — `localStorage`
faellt von 8 Schluesseln auf 0, ein Cookie ist fort. Zwei Anlaeufe sind daran gescheitert,
obwohl es in `panel_devices` und in der EFB-Shell seit dem 13.08. dokumentiert stand.
Ausfuehrlich in `docs/efb-panel-debugging.md` und `docs/architecture.md`.

**Drei Fallen, wenn ihr an dem Bereich arbeitet:**
- `initLiveMap` wartet mit `await _prefsPromise`, BEVOR die Karte gebaut wird. Ohne das
  springt die Basisebene um und der Ebenen-Haken steht falsch.
- `_prefServerPlanen` sendet nichts vor der Serverantwort (`if (!_prefVomServer) return;`).
  Im Kniebrett ist der lokale Stand beim Aufbau leer — ein Zuruecksenden ueberschriebe den
  gespeicherten Stand mit Leere.
- `_trackUp`/`_movingMap` werden beim LADEN des Skripts gelesen, also vor der Antwort. Sie
  werden in `_prefsPromise` nachgezogen, aber nur solange `_naviBeruehrt` false ist.

**Neu dazu:** `friesenspy_tab` und `friesenspy_vollbild` (Zustand des Kniebretts). Die Karte
startet deshalb **nicht mehr unbedingt ueber EDWG** und **nicht mehr unbedingt auf LIVE** —
beides ist jetzt Rueckfall. Zusicherungen dazu stehen in `tests/test_karte_merker.py`.

**Fuer Node-Tests:** Ein Quelltext-Ausschnitt, der `_loadFsePref` o. ae. enthaelt, braucht den
Speicher mit (`_pref_quelltext()` in `tests/test_fse.py`) und im Harness ein
`document.documentElement` sowie ein `fetch` — Muster in `tests/test_karte_merker.py`.
Suite nach dem Rebase auf 4fef390: **1786 gruen**.

---

## 2026-07-01 — Fable-Session: Analyse-Auftrag Flug-Tracking (docs/fable-analyse-auftrag.md)

**Branch:** `claude/fable-analyse-auftrag-3hgk13` (Releases werden zusätzlich auf `main` gepusht/deployed).

**Status: abgeschlossen.** Ergebnisse in `docs/analyse-bericht-2026-07-01.md`.

**Bearbeitete Bereiche — bitte parallele Änderungen kurz absprechen:**
- `app/database.py`: `open_flight` (Session-Reopen bei Feed-Aussetzer), `consolidate_flights`
  (Block-Neuberechnung in C/D + neuer Schritt E), `_segments_continuous` (Abgeflogen-Regel),
  `_block_minutes`/`_block_seconds` (Summe bewegter Abschnitte, Standphasen ≥ 10 min raus),
  neu: `reconstruct_orphaned_flights` + `transport_anyone_in_progress`.
- `app/poller.py`: `_check_transport_events` (Feierabend wartet auf Nachzügler).
- `app/llm.py`: `_QUIP_SYSTEM` (verständliches Hochdeutsch).
- `.github/workflows/deploy.yml`: Deploy verifiziert jetzt selbst den Health-Endpoint
  (Fehlschlag + Container-Logs, wenn die App nicht antwortet).
- Releases: v7.3.1 (Gruppe A), v7.3.2 (Hotfix Startcrash + B1), v7.3.3 (B2), v7.3.4–v7.3.6
  (Nachfixes Merge/Rekonstruktion/Ghost-Filter nach Praxis-Gegenprüfung), v7.3.7–v7.3.10
  (Zuladungs-Recherche: Zeitbudget + Typ-Hinweise), v7.4.0 (halbe Tanks, Auto-Recherche,
  Typ ohne Flugplan, Mobile-Scroll-Standard → stehende Regel in CLAUDE.md). Suite: 537 grün.
  Details + offene Punkte: docs/analyse-bericht-2026-07-01.md.

**Achtung für andere Sessions:**
- Der Git-Proxy der Remote-Umgebung **verweigert Tag-Pushes** — Tags v7.3.1–v7.3.3 müssen
  lokal nachgezogen werden (Kommandos im Abschlussbericht).
- `init_db` läuft mit ROHER sqlite3-Connection (ohne row_factory) — Funktionen, die dort
  aufgerufen werden, dürfen sich nicht auf benannten Zeilenzugriff verlassen (Prod-Crash
  v7.3.1, behoben in v7.3.2).

**Nicht angefasst** (Produktentscheidungen, siehe Auftrag): #7, #8, #15, #16, #18. Neuer
Diskussionspunkt notiert: Flugerfassung rein GPS-basiert (siehe Bericht).
