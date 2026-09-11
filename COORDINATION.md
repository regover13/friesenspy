# Koordination paralleler Sessions

Kurze Absprachen zwischen parallel arbeitenden Claude-Sessions am FriesenSpy-Repo.
Vor jedem Push: `git fetch` + Rebase auf `origin/main`; niemals fremde, uncommittete
Änderungen überschreiben. Einträge bitte oben anfügen (neueste zuerst).

---

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
