# Koordination paralleler Sessions

Kurze Absprachen zwischen parallel arbeitenden Claude-Sessions am FriesenSpy-Repo.
Vor jedem Push: `git fetch` + Rebase auf `origin/main`; niemals fremde, uncommittete
Änderungen überschreiben. Einträge bitte oben anfügen (neueste zuerst).

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

### Fuer die parallele Session

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
