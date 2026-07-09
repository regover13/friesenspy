# Design-Entwurf (DRAFT) — FriesenKutter-Verlust-Kern: #6 / #7 / #8

Datum: 2026-07-09
Status: **Entwurf zur Diskussion, KEIN Umsetzungsplan.** Nur Lösungsansätze + Trade-offs;
keine Codeänderung in diesem Schritt. Gehört zu „Paket B" des Gesamtvorhabens „Alles fixen"
(A = `docs/superpowers/specs/2026-07-09-kutter-sofortfixes-design.md`, bereits Sofort-Fixes;
B = dieser Verlust-Kern; C = Milchmann + Boden-Beladung, eigene Specs).

Alle Pfade absolut. Zeilenangaben Stand 2026-07-09 (Commit `08f64f4`) — vor jeder Umsetzung per
Grep erneut verifizieren (Zeilen driften).

---

## 1. Ist-Analyse

### 1.1 Bug #6 — Live-Ankunfts-Latch gilt pro VERBINDUNG statt pro Leg (ernst)

**Schema:** `transport_live_arrivals` (`D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\database.py:222-228`)
— `PRIMARY KEY (cid, logon_time, event_id)`, plus `arrived_at TEXT NOT NULL`.

**Schreibpfad (Live-Poll):** `D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\poller.py:824-839`
ruft pro Poll `check_live_arrival(conn, cid, leg_logon, lat, lon, gs, active_events)` auf.
`leg_logon` (`poller.py:835`) = `self._active_flights[cid]["logon_time"]`. Dieser Wert wird
**nur bei einem VATSIM-Flugplan-Refile mit geändertem Startplatz** neu gesetzt
(`poller.py:791-818`, insb. `new_dep != old_dep` an `poller.py:796-797`, Split via
`close_flight`+`open_flight` an `poller.py:803-814`) — **nicht** bei einem rein GPS-erkannten
Landen+Wiederabheben ohne Refile. Ein Kutter, der liefert und auf **derselben** VATSIM-Connection
ohne neuen Flugplan weiterfliegt, behält also denselben `leg_logon` = denselben Latch-Schlüssel.

`check_live_arrival` selbst (`database.py:4993-5021`) prüft nur Boden + Zielradius und latcht via
`set_transport_live_arrival` (`database.py:4771-4779`, `INSERT OR IGNORE`) — pro Design bewusst
**nie rückgängig** gemacht.

**Lesepfad / Matching:** `_latch_hits_flight` (`database.py:4810-4835`) entscheidet, ob ein Latch
`(cid, lo)` zu einem konkreten GPS-Leg `(takeoff_ts, landing_ts)` gehört:

```
end = landing_ts or "9999-12-31T23:59:59Z"
for c, lo in latches:
    if c != cid or lo > end: continue
    row = SELECT logoff_time FROM flights WHERE cid=? AND logon_time=?  (mit lo)
    hi = row.logoff_time or "9999-12-31T23:59:59Z"
    if takeoff_ts <= hi: return True
```

Der **positive** Match-Test `takeoff_ts <= hi` vergleicht das Leg-Takeoff gegen `hi` = das Ende der
ganzen **Connection** (per Extra-Query gegen `flights`), nicht gegen das Ende des konkreten Legs.
Da praktisch jedes Leg innerhalb einer offenen/laufenden Connection `takeoff_ts <= hi` erfüllt
(die Connection ist ja per Definition noch nicht zu Ende oder endet erst deutlich später), matcht
EIN Latch **jedes** Leg dieser Connection — auch alle, die erst NACH der eigentlichen Lieferung
starten. `landing_ts` (das eigene Leg-Ende) wird nur als lascher Vorfilter benutzt (`lo > end`
skip), fließt aber **nicht** in den positiven Match ein. `arrived_at` (die Spalte existiert, wird
sogar von `get_transport_live_arrivals` gar nicht erst selektiert, `database.py:4782-4787`) wird
**komplett ignoriert** — obwohl sie exakt der Zeitpunkt ist, zu dem der Live-Latch tatsächlich
gesetzt wurde.

**Zwei Konsumenten, beide betroffen:**
- Anzeige: `compute_transport_progress`, `database.py:5177` (`has_latch = ... _latch_hits_flight(...)`)
  und die Ableitung `loaded` an `database.py:5188` sowie der Offen-Zweig an `database.py:5284`
  (`loaded = bool(dest) and (cid, lo) in live_arrivals` — hier sogar noch gröber: direkter
  Set-Membership-Test ohne jede Leg-Bindung, da der Offen-Zweig per Definition dieselbe `lo`
  wie die Connection nutzt). Ein noch fliegendes, unbeladenes Folge-Leg wird als „bereits
  geliefert" gezeigt → der #66-Skip (`database.py:5258`, `if (int(cid), lo) in loaded_conn_logons
  and int(cid) not in current_leg_by_cid: continue`) blendet den real fliegenden Flug sogar
  komplett aus dem Feed aus.
- Verlust-Erkennung: `detect_transport_losses`, `database.py:4908` (`if _latch_hits_flight(conn,
  latched, cid, lo, conn_logoff): continue`) — ein wirklich verlorenes (gestohlenes/versunkenes)
  Folge-Leg wird nie als Verlust-Kandidat gewertet, weil der alte Latch es fälschlich als „schon
  geliefert" abstempelt. **Der Verlust wird nie erfasst.**

Live reproduziert (Nutzerangabe): ein Kutter liefert einmal korrekt, fliegt auf derselben
Verbindung weiter → „vergiftet" für den Rest der Verbindung. Neue Verbindung = korrekt.

### 1.2 Bug #7 — Verlustmenge brutto statt netto

Block „Verlust-Bordladung aufschlüsseln", `D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\database.py:5511-5554`,
läuft **nach** dem Delivered-Fill (`5431-5470`) und dem Reserved-Fill (`5479-5509`), aber komplett
isoliert von deren Pools:

```python
# database.py:5528-5539
for i, c in enumerate(cargo):
    if remaining <= 1e-9: break
    if not _fillable(q, i): continue
    cap = c.get("per_flight_max_kg") ...
    add = min(remaining, cap, cargo_targets[i])   # <-- Zeile 5535: volles Ziel, kein Abzug
    ...
```

`add` ist gegen das **rohe** `cargo_targets[i]` gekappt — nicht gegen `cargo_targets[i] -
delivered[i]` (wie im Delivered-Fill, `database.py:5444`) und auch nicht gegen ein Äquivalent von
`reserved_alloc[i]` (wie im Reserved-Fill, `database.py:5491`: `space = cargo_targets[i] -
delivered[i] - reserved_alloc[i]`). Der Kommentar `database.py:5511-5515` begründet das bewusst:
„ein Verlust betrifft die GANZE Ladung, nicht nur den Manifest-Anteil". Es gibt zwar bereits eine
Teil-Nettung (`database.py:5546-5554`, „Fix Live 06.07.": `lost_kg` = Σ der tatsächlich
zugeordneten `contrib`-Werte statt der vollen Musterzuladung) — die verhindert nur, dass
Überschuss-Kapazität ohne Manifest-Entsprechung mitgezählt wird (das PZ04-Beispiel im
Kommentar: 290 kg Musterzuladung → 160 kg Event-Fracht). Sie verhindert **nicht**, dass derselbe
Frachtart-„Topf" mehrfach bis zum vollen `cargo_targets[i]` an mehrere Flüge (delivered UND lost)
gleichzeitig vergeben wird — genau das macht die ausgewiesene Verlustmenge in Summe zu hoch,
sobald für dieselbe Frachtart bereits etwas geliefert wurde.

### 1.3 Bug #8 — verlorene Ware bleibt im Pool ladbar

Reservierungs-Block, `database.py:5479-5509`, Space-Formel bei `database.py:5491`:

```python
space = cargo_targets[i] - delivered[i] - reserved_alloc[i]
```

Delivered-Fill-Space-Formel, `database.py:5444`:

```python
space = cargo_targets[i] - delivered[i]
```

Beide ziehen ausschließlich `delivered[i]` (und im Reserved-Fall zusätzlich die laufende
`reserved_alloc[i]`) ab — **nie** verlorene Mengen. Es gibt aktuell **kein** `lost[i]`-Array, das
in eine dieser beiden Space-Formeln einfließt. Konsequenz: gestohlene/versunkene Fracht bleibt für
jeden späteren Flug (delivered- oder reserved-seitig) unsichtbar „noch verfügbares Ziel" — das
Manifest kann in Summe mehr als `target_kg` an Fracht „verbrauchen", als real existierte, weil
verlorene Mengen nie aus dem Topf verschwinden.

`get_transport_cargo`/`cargo` (`database.py:4257-4264`, Felder `target_kg`,
`per_flight_max_kg`, `departure`) hat kein `lost_kg`-Feld; `cargo_out`
(`database.py:5566-5577`) liefert aktuell `target_kg`, `delivered_kg`, `reserved_kg`, `pct` —
ebenfalls kein Verlust-Gegenstück auf Frachtart-Ebene (nur global `lost_total_kg`,
`database.py:5640`, über ALLE Frachtarten hinweg summiert aus den Feed-Zeilen).

**Abschluss-Interaktion:** `goal_reached_at` wird in `poller.py:1280-1284` gesetzt, sobald
`progress["total_kg"] >= target` (rohes `target_kg`). Ist ein Teil des Ziels durch Verluste
physisch nicht mehr erreichbar, kann `total_kg` `target_kg` nie mehr erreichen —
`goal_reached_at` latcht dann **nie**. Das ist laut Aufgabenstellung eine **gewollte** Konsequenz
(„Event kann durch Verluste unvollendbar werden"), berührt aber NICHT den Abschluss selbst: die
Feierabend-Latch `summarized_at` (`poller.py:1285-1320`) hängt einzig an `dtend` +
`transport_anyone_in_progress` (`database.py:5041-5074`), ist von `goal_reached_at` unabhängig —
ein unvollendbares Event schließt also trotzdem sauber ab (Snapshot via `write_progress_snapshot`,
`poller.py:1301-1305`), zeigt aber ggf. dauerhaft <100 % Fortschritt. Das betrifft auch
`progress_pct` (`database.py:5580`, `100.0 * total_kg / target_kg`) und potenziell die
Badge-Anzeige (`main.py:1886-1917`, nutzt `team_target_kg`/`team_total_kg` aus genau diesen
Feldern).

---

## 2. Lösungsansätze für #6 (Kernproblem)

Gemeinsamer Fixpunkt aller drei Ansätze: **beide Konsumenten** (`compute_transport_progress`
UND `detect_transport_losses`) hängen an derselben Funktion `_latch_hits_flight` — ein Fix dort
repariert automatisch beide Seiten gleichzeitig, ohne Duplizierung/Divergenzrisiko.

### Ansatz A — Latch pro echtem GPS-Leg (Live-Zustandsmaschine)

Der Live-Poller bekäme eine eigene, inkrementelle Alt/Groundspeed-Zustandsmaschine
(ON_GROUND→AIRBORNE→ON_GROUND, analog `D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\gps_legs.py:75-140`
`detect_gps_legs`/`_detect_segment`), um live zu wissen „das aktuelle GPS-Leg begann bei ts=X" —
unabhängig vom VATSIM-Flugplan-Refile. `set_transport_live_arrival` würde dann mit diesem echten
Leg-Takeoff statt dem Connection-`logon_time` latchen.

- **Trade-off:** konzeptionell die „reinste" Lösung (Latch = physisches Leg, keine nachträgliche
  Zuordnung nötig).
- **Risiko:** zweite, parallele Leg-Erkennung neben der schon vorhandenen offline
  `detect_gps_legs`/`canonicalize_legs` — Drift-Risiko, wenn beide je unterschiedliche Schwellen
  (`_GPS_AIR_AGL_FT`, `_GPS_BLOCK_GS_KT` etc., `gps_legs.py:14-19`) oder Sonderfälle (Stop-and-Go,
  `_GPS_STOP_AND_GO_MAX_SEC`, `gps_legs.py:26-36`) unterschiedlich behandeln. Hoher
  Implementierungsaufwand, hohes Regressionsrisiko für die Refile-Split-Logik (#22,
  `poller.py:791-818`) und alle daran hängenden #65/#66-Fixes (`_active_flights`,
  `current_leg_by_cid`-Timing).
- **Schema-Bruch:** bestehende `transport_live_arrivals`-Zeilen sind mit Connection-`logon_time`
  geschrieben — ohne Migration/Backfill bleiben ALLE bereits „vergifteten" Live-Events weiterhin
  falsch, der Fix wirkt nur für künftige Latches.
- **Bewertung:** hoher Aufwand, hohes Risiko, **nicht rückwirkend**. Nicht empfohlen.

### Ansatz B — Latch invalidieren, sobald der Zielradius wieder verlassen wird

Neue Spalte `left_at` auf `transport_live_arrivals`. Im selben Poll-Takt
(`poller.py:824-839`), der `check_live_arrival` aufruft, zusätzlich prüfen: ist ein bereits
gelatchtes `(cid, lo)` jetzt wieder außerhalb des Zielradius ODER wieder in Bewegung
(`groundspeed` über Schwelle) — `left_at = now` setzen. `_latch_hits_flight` nutzt dann
`[arrived_at, left_at oder ∞]` als Gültigkeitsfenster statt des Connection-Intervalls.

- **Trade-off:** einfacher als A (kein volles Leg-Detektor-Duplikat, nur ein Grenzwert-Übergang),
  aber ein neuer Schreibpfad mit eigenem Timing (Invalidierung kann 1 Poll-Takt hinter dem echten
  Abheben liegen — `TS_POLL_INTERVAL`/`VATSIM_POLL_INTERVAL`-Granularität).
- **Risiko:** mittel — neuer State, neue Racebedingung zwischen „Latch setzen" und „Latch
  invalidieren" im selben Poll (Reihenfolge der `current_cids`-Iteration beachten).
- **Schema-Bruch:** wie A **nicht rückwirkend** für Alt-Latches (NULL `left_at` = weiterhin altes,
  breites Verhalten, bis das Cid diesen Radius im laufenden Betrieb erneut verlässt — bei bereits
  disconnecteten Piloten passiert das nie mehr, Alt-Events bleiben vergiftet).
- **Bewertung:** mittlerer Aufwand, mittleres Risiko, **nur teilweise rückwirkend**.

### Ansatz C — Latch-Match über die bereits gespeicherte `arrived_at`-Zeit an das Leg binden (empfohlen)

**Kernidee:** `arrived_at` (existiert in `transport_live_arrivals` bereits, wird nur aktuell nicht
gelesen/genutzt) ist exakt der Live-Zeitpunkt der Ankunfts-Erkennung — und liegt damit fast
zeitgleich mit dem echten GPS-Touchdown des LIEFERNDEN Legs. Statt den Connection-Logoff
nachzuschlagen, bindet `_latch_hits_flight` den Latch an GENAU das Leg, in dessen eigenem
`[takeoff_ts, landing_ts]`-Fenster `arrived_at` liegt:

- `get_transport_live_arrivals` (`database.py:4782-4787`) zusätzlich `arrived_at` selektieren
  (ein Feld mehr in der bestehenden Query) → Rückgabe `{(cid, logon_time): arrived_at}` statt
  eines nackten Sets.
- `_latch_hits_flight(conn, latches, cid, takeoff_ts, landing_ts)` (`database.py:4810-4835`)
  Match-Kriterium ersetzen durch (Skizze, kein Code):
  - Connection-Scoping als Vorfilter behalten (`c == cid and lo <= takeoff_ts`) — verhindert,
    dass ein Latch einer örtlich/zeitlich völlig anderen (späteren ODER sehr alten) Connection
    versehentlich zugeordnet wird.
  - Positiver Match: `takeoff_ts <= arrived_at` (das Leg muss zum Ankunfts-Zeitpunkt bereits
    gestartet gewesen sein) **und** (`landing_ts is None` **oder** `arrived_at <= landing_ts`)
    (die Ankunft muss innerhalb des GPS-eigenen Lebensfensters DIESES Legs liegen, nicht
    irgendwann später in der Connection).
  - Die interne `SELECT logoff_time FROM flights ...`-Nachschau entfällt komplett (Vereinfachung,
    kein Connection-Lookup mehr nötig) — `arrived_at` liefert direkt genug Information.
- Beide Aufrufer (`compute_transport_progress:5177`, `detect_transport_losses:4908`) übergeben
  bereits heute `f.get("logon_time")`/`f.get("logoff_time")` — laut `canonicalize_legs`-Doku
  (`database.py:2391-2426`, „formgleich zu `canonicalize_flights`") sind das für echte GPS-Legs
  bereits die **eigenen** Leg-Grenzen (Takeoff/Landing), NICHT die Connection-Grenzen (nur der
  trackless Fallback, `_flightrow_as_flight`, spiegelt 1:1 die Connection — dort ist Leg==
  Connection ohnehin dasselbe, keine Ambiguität). **Keine Signaturänderung an den Aufrufstellen
  nötig**, nur an `_latch_hits_flight` selbst + `get_transport_live_arrivals`.

- **Warum das beide Seiten gleichzeitig repariert:** ein Folge-Leg, das NACH der Lieferung
  startet, hat `takeoff_ts > arrived_at` → kein Match mehr → gilt in der Anzeige korrekt als
  unbeladen/„unterwegs" (statt fälschlich „beladen") UND wird von `detect_transport_losses` nicht
  mehr fälschlich als „schon behandelt" übersprungen — ein echter Verlust auf diesem Leg wird
  jetzt erkannt.
- **Rückwirkend, ohne Migration:** `arrived_at` wurde immer schon geschrieben — der Fix wirkt
  SOFORT auch auf bereits „vergiftete" Alt-Verbindungen, sobald `compute_transport_progress`/
  `detect_transport_losses` das nächste Mal laufen. Kein Backfill-Skript nötig.
- **Risiko für #66/#65/#23:** gering — die Änderung sitzt ausschließlich in `_latch_hits_flight`
  und der Latch-Selektion; sie rührt nicht an `current_leg_by_cid`, `_returning_pilot_landed`,
  den #66-Skip (`database.py:5258`) oder die Fenstergrenzen (`start`/`end`,
  `_BUMMEL_EARLY_START_LOOKBACK_H`) — diese bleiben unverändert und funktionieren weiter exakt wie
  dokumentiert, weil sie nur DARÜBER entscheiden, WELCHE Legs überhaupt als Kandidaten in die
  Schleifen kommen, nicht WIE ein Latch einem Kandidaten zugeordnet wird.
- **Randfall zu klären:** minimale Zeitversatz-Toleranz zwischen `check_live_arrival`s eigenem
  Boden+Radius-Kriterium (`database.py:5010-5021`) und dem GPS-Leg-Detektors Touchdown-Kriterium
  (`_GPS_BLOCK_GS_KT`, `gps_legs.py:19`) — in der Praxis meist derselbe oder ein direkt
  benachbarter Poll-Takt, sollte aber an einem Live-Fall verifiziert werden (offene Frage 1 unten).

**Empfehlung: Ansatz C.** Geringster Aufwand, geringstes Regressionsrisiko, einzige der drei
Varianten, die bereits bestehende (Live-)Poisoned-Verbindungen ohne Migration rückwirkend heilt.

---

## 3. Umbau-Vorschlag #7 + #8 (gemeinsam, da #8 strukturell auf #7 aufbaut)

### 3.1 Grundidee: Verlust-Fill in den bestehenden chronologischen Delivered-Fill einreihen

Heute existieren de facto drei unabhängige, sequenzielle Verteil-Durchläufe über `network`
(bereits nach `dep_time` aufsteigend sortiert, `database.py:5391`):

1. Delivered-Fill (`database.py:5431-5470`) — nur `q["loaded"]`, füllt `delivered[i]`,
   `space = cargo_targets[i] - delivered[i]`.
2. Reserved-Fill (`database.py:5479-5509`) — nur offene In-Air-Flüge ohne Latch, füllt
   `reserved_alloc[i]`, `space = cargo_targets[i] - delivered[i] - reserved_alloc[i]`.
3. Verlust-Fill (`database.py:5516-5554`) — nur `q.get("loss_kind")`, **isoliert**, `cap =
   cargo_targets[i]` roh (das ist #7), schreibt nirgends in einen Pool zurück, den 1./2. sehen
   (das ist #8).

**Vorschlag:** Pass 1 und Pass 3 zu EINEM gemeinsamen, weiterhin chronologischen Durchlauf
verschmelzen (derselbe `for q in network:`-Loop, network bleibt global nach `dep_time` sortiert),
mit einem neuen parallelen Array `lost = [0.0] * len(cargo)` neben `delivered`:

- `q["loaded"]` → wie heute, füllt `delivered[i]`, `space = cargo_targets[i] - delivered[i] -
  lost[i]` (NEU: zusätzlich `lost[i]` abziehen).
- `q.get("loss_kind") in ("stolen", "sunk")` → dieselbe Fill-Logik (gleicher `_fillable`-Check,
  gleiche `per_flight_max_kg`-Kappung), aber schreibt in `lost[i]` statt `delivered[i]`, **gegen
  dieselbe** Space-Formel `cargo_targets[i] - delivered[i] - lost[i]` (nicht das rohe
  `cargo_targets[i]` wie heute Zeile 5535).
- `q.get("loss_kind") == "returned"` → bewusst NICHT in diesen Pool-Pass aufnehmen (kein
  Pool-Verbrauch, „Ware kam heil zurück"). Die Bordladungs-Anzeige für `returned` bleibt die
  bestehende, rein kosmetische Brutto-Berechnung (unverändert, kein Korrektheitsproblem — nur
  Anzeige „x Krabbenbrötchen", `database.py:5511` Nutzer-Wunsch 02.07.) — **Scope-Reduktion**, um
  Risiko zu minimieren: nur `stolen`/`sunk` bekommen die neue Pool-Bindung.
- Reserved-Fill (Pass 2) läuft danach unverändert strukturell, nur die Space-Formel
  (`database.py:5491`) erweitert sich zu `cargo_targets[i] - delivered[i] - lost[i] -
  reserved_alloc[i]`.

**Warum das #7 löst:** ein `stolen`/`sunk`-Flug beansprucht jetzt exakt so viel einer Frachtart,
wie zum Zeitpunkt seines eigenen `dep_time` (in der bestehenden chronologischen Verteil-Reihenfolge
relativ zu allen ANDEREN bereits aufgelösten — delivered ODER lost — Flügen) tatsächlich noch im
Topf war. Kein Doppel-Ausweisen derselben Kapazität an mehrere Flüge gleichzeitig mehr.

**Warum das #8 löst:** `lost[i]` fließt jetzt in JEDE nachfolgende Space-Berechnung ein (sowohl für
spätere `delivered`- als auch für `reserved`-Flüge, da beide Formeln erweitert werden) — verlorene
Fracht ist damit dauerhaft aus dem ladbaren Pool verschwunden, unabhängig davon, wie viele weitere
Flüge danach noch dieselbe Frachtart anfragen.

### 3.2 „Snapshot zum Ladezeitpunkt, nicht laufend gegen Restbedarf" — Einordnung

Der chronologische Merge-Ansatz erfüllt die Nutzer-Vorgabe **im Sinne des bereits etablierten
#63-Präzedenzfalls**: schon heute ist ein delivered-Flug's `tonnage_kg` NICHT strikt unveränderlich
— ein SPÄTER (nach `dep_time`) noch offener Flug, der ERST NACH diesem poll seine Landung meldet,
aber einen FRÜHEREN `dep_time` als ein bereits gezählter Flug hat, kann bei der nächsten
`compute_transport_progress`-Neuberechnung dessen Netto-Anteil nachträglich verringern (die
komplette `delivered[]`-Verteilung wird bei jedem Poll aus dem gesamten bekannten `network` neu
gerechnet, s. Docstring-Abschnitt „Durchgängig Netto (#63)", `database.py:5101-5104`). Der
Merge-Vorschlag überträgt exakt dasselbe, bereits akzeptierte Verhalten auf `lost[i]` — er führt
**keine neue Instabilität** ein, sondern beseitigt die heutige Extra-Instabilität (Verlust ist
BRUTTO gegen ein sich real veränderndes Restziel gerechnet, ohne jede Pool-Bindung — das ist
tatsächlich schlimmer, weil es überhaupt keinem konsistenten Rahmen folgt).

**Falls eine STRENGERE, wirklich unveränderliche Snapshot-Semantik gewünscht ist** (der Wert einer
einmal erkannten Verlust-Zeile ändert sich NIE wieder, auch nicht durch später auftauchende, aber
früher gestartete andere Verlust-/Liefer-Flüge derselben Frachtart) — das wäre eine **zusätzliche**
Persistenz-Schicht: `record_transport_loss`/`transport_cargo_losses` (`database.py:4790-4798`,
Schema `database.py:230-240`) um eine JSON-Spalte (z. B. `cargo_breakdown_json`) erweitern, die
EINMALIG beim ersten `detect_transport_losses`-Lauf (INSERT-Zeitpunkt, `database.py:4950-4951`)
den zu diesem Moment gültigen `contrib`-Snapshot persistiert — `compute_transport_progress` würde
diesen dann NUR NOCH LESEN statt live neu zu verteilen. Das ist die technisch strengere, aber
invasivere Variante (neue Spalte, Schreibpfad in `detect_transport_losses` statt in
`compute_transport_progress`, zwei Quellen der Wahrheit für „was wurde verteilt" die synchron
bleiben müssen). **Offene Frage 2** unten.

### 3.3 Auswirkung auf `compute_transport_progress` (API-Form)

- `cargo_out` (`database.py:5566-5577`) bekommt ein neues Feld je Frachtart, z. B. `lost_kg:
  round(lost[i], 1)` — analog zu `delivered_kg`/`reserved_kg`. UI kann damit „X kg unwiederbringlich
  verloren" pro Frachtart zeigen statt nur den globalen `lost_total_kg` (`database.py:5640`).
- `target_kg`/`progress_pct` (`database.py:5579-5580`): Bedeutung bewusst NICHT automatisch
  ändern (bleibt das deklarierte Event-Ziel) — stattdessen optional ein neues Feld
  `deliverable_kg = target_kg - lost_total_kg` ergänzen, das UI/Push explizit nutzen können, ohne
  die bestehende `target_kg`-Semantik zu brechen (Rückwärtskompatibilität für alte Events ohne
  Verluste: `deliverable_kg == target_kg`). **Offene Frage 3** unten (ob `progress_pct` selbst
  umgestellt werden soll).

### 3.4 Auswirkung auf die #66-Abschlusslogik

- `poller.py:1280-1284` (`goal_reached_at`): Vergleich `progress["total_kg"] >= target` bleibt
  technisch funktionsfähig (kein Crash, kein Hänger) — latcht nur nie bei einem durch Verluste
  unvollendbaren Event. Das ist laut Aufgabenstellung **gewollt**, sollte aber bewusst bestätigt
  werden (**offene Frage 4**: ggf. gegen `target - lost_total_kg` vergleichen, damit „alles
  Mögliche geliefert" trotzdem einen Push/Latch auslöst).
- `poller.py:1285-1320` (`summarized_at`/Feierabend): **unabhängig** von `goal_reached_at`, hängt
  nur an `dtend` + `transport_anyone_in_progress` — ein unvollendbares Event schließt trotzdem
  sauber ab, Snapshot wird eingefroren (`write_progress_snapshot`, `poller.py:1305`). Kein
  Codeeingriff hier nötig, NUR wenn Frage 5 (eigener Abschluss-Zustand) mit „ja" beantwortet wird.
- Badge (`main.py:1886-1917`, `_kutter_badge_data`): summiert `stolen_kg`/`sunk_kg` bereits heute
  aus `progress["losses"]` je CID (`main.py:1896-1903`) — profitiert automatisch von der
  Netto-Korrektur (#7), keine Änderung an der Badge-Logik selbst nötig. `team_target_kg`/
  `team_total_kg` (`main.py:1913-1914`) könnten optional auf `deliverable_kg` umgestellt werden,
  falls Frage 3 das so entscheidet.

---

## 4. Reihenfolge / Abhängigkeiten

1. **#6 zuerst.** Solange poisonierte Latches echte Verluste vor `detect_transport_losses`
   verstecken, lässt sich #7/#8 an echten, aktuell laufenden Events kaum sauber verifizieren
   (die betroffenen Verlust-Zeilen entstehen schlicht nicht). #6 ist zudem komplett unabhängig von
   #7/#8 (andere Funktion, anderer Datenpfad) — kein technischer Grund, es NICHT zuerst zu
   deployen.
2. **#7 + #8 gemeinsam, in einem Schritt.** #8 („verfügbar = target − delivered − lost −
   reserved") braucht strukturell das `lost[i]`-Array, das #7 als Nebenprodukt der Netto-Fill-Logik
   erzeugt (s. §3.1) — #8 ohne #7 umzusetzen würde nur die BRUTTO-Menge dauerhaft (statt nur
   einmalig) vom Pool abziehen, also den Fehler verlagern statt beheben. Beide gehören in denselben
   PR/dieselbe Codeänderung an `compute_transport_progress` (§3.1).
3. Danach unabhängig, nach Bedarf: `cargo_out`-Erweiterung (`lost_kg` je Frachtart),
   `deliverable_kg`-Feld, ggf. `goal_reached_at`-Anpassung (Frage 4), ggf. eigener
   Abschluss-Zustand (Frage 5) — reine Anzeige-/Zusatzfelder, die auf der #7/#8-Kernlogik aufbauen,
   aber keine Voraussetzung für deren Korrektheit sind.

---

## 5. Offene Fragen (Mensch entscheidet)

1. **#6-Ansatz bestätigen:** Ansatz C (Latch-Match über `arrived_at`) wie empfohlen umsetzen?
   Insbesondere: reicht die automatische Rückwirkung auf bereits „vergiftete" Alt-Verbindungen
   (kein Backfill nötig, da `arrived_at` schon immer gespeichert wurde), oder soll zusätzlich ein
   gezielter Admin-Recompute für bereits sichtbar falsch gelaufene Live-Events angestoßen werden?
2. **#7-Snapshot-Definition:** reicht die chronologische Netto-Fill-Semantik (§3.2, konsistent mit
   dem bestehenden #63-Präzedenzfall — „Snapshot" im Sinne von „konsistent gegen dieselbe
   Pool-Regel wie delivered", aber technisch bei retroaktiver Neuordnung noch minimal
   nachjustierbar), oder wird eine ECHTE, ab dem ersten Erkennen unveränderliche Persistenz
   verlangt (neue Spalte/Tabelle, §3.2 zweiter Absatz)?
3. Soll `progress_pct`/der Fortschrittsbalken künftig gegen `target_kg` (roh, wie heute) oder
   gegen `deliverable_kg = target_kg − lost_total_kg` (real noch erreichbar) gerechnet werden?
4. Soll `goal_reached_at` (`poller.py:1281`) weiterhin strikt gegen das rohe `target_kg` prüfen
   (dann: NIE bei einem durch Verluste unvollendbaren Event, nur Feierabend via `dtend`), oder
   gegen `target_kg − lost_total_kg`, damit „alles real noch Mögliche geliefert" ebenfalls einen
   Push/Latch auslösen kann?
5. Braucht ein durch Verluste unvollendbares Event einen eigenen, sichtbar unterscheidbaren
   Abschluss-Zustand/Badge-Text (z. B. „unvollständig abgeschlossen") statt stillschweigend bei
   <100 % Fortschritt zu verharren?
6. Soll `cargo_out` (API) ein `lost_kg`-Feld je Frachtart bekommen (§3.3), oder bleibt der
   Verlust-Ausweis auf den bestehenden globalen `lost_total_kg`/`progress["losses"]`-Feed
   beschränkt?
7. Rückwirkende Bereinigung bereits laufender/abgeschlossener Live-Events: Alt-Events mit
   `summarized_at` sind bereits als Snapshot eingefroren (`write_progress_snapshot`) — sollen
   erkennbar falsch berechnete Alt-Snapshots nach dem Fix per Admin-Aktion neu berechnet werden,
   oder bleiben sie unangetastet (nur künftige Events profitieren)?
