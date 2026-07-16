# SDD-Ledger — FriesenKutter Stapel-Modell

Plan: docs/superpowers/plans/2026-07-16-kutter-stapel-modell.md
Spec: docs/superpowers/specs/2026-07-15-kutter-stapel-modell-design.md (14 Entscheidungen, alle bestaetigt)
Basis vor Task 1: 7d58e1f
Branch: main (stehende Nutzer-Regel: kein PR-Umweg; nur vor `git push origin main` bestaetigen lassen)

Reihenfolge: 1 -> 2 -> 3 -> 4 -> 5 (reine Funktion) -> 6 (Adapter) -> 7 GATE -> 8 -> 9 -> 10 -> 11 -> 12
             -> Whole-Branch-Review (Opus)

## ⛔ GATE BLOCKIERT — braucht eine Freigabe des Nutzers (Stand 16.07. nachts)

Task 7 Step 2 verlangt eine KOPIE der Produktions-DB. Der Zugriff auf den Produktions-Host wurde
von der Berechtigungspruefung ABGELEHNT ("no explicit user message named this SSH access to the
production host as an authorized operation"). NICHT umgangen — das ist richtig so.

ZWEI PLANFEHLER dabei gefunden (Task 7 Step 2 im Plan korrigieren):
 1. Der Plan schreibt `scp friesenspy:/opt/...`. Einen SSH-Host `friesenspy` GIBT ES NICHT.
    Der VPS heisst `server` (167.86.127.129, ~/.ssh/config). Richtig waere:
        scp server:/opt/friesenspy/data/friesenspy.db /tmp/friesenspy-kopie.db
 2. Die Prod-DB ist LIVE (43 MB, Zeitstempel 02:12, der Poller schreibt hinein) und laeuft im
    WAL-Modus. Ein blosses `scp` der .db-Datei allein kann einen zerrissenen Stand ergeben —
    die -wal/-shm-Dateien gehoeren mitkopiert, oder besser ein rein lesender Snapshot:
        sqlite3 'file:/opt/friesenspy/data/friesenspy.db?mode=ro' ".backup '/tmp/kopie.db'"
    (ungeprueft, ob sqlite3 auf dem Host liegt — konnte ich nicht nachsehen, s.o.)
 Ausserdem: scripts/kutter_stapel_prototyp.py:20 verbindet HART auf
    sqlite3.connect("/opt/friesenspy/data/friesenspy.db") — also schreibend auf die ORIGINALDATEI.
    Das muss auf die Kopie zeigen (und am besten mode=ro), bevor es je laeuft.

WAS DER NUTZER MORGEN TUN MUSS: den DB-Kopier-Befehl freigeben (oder selbst per `!`-Prefix
ausfuehren). Danach laeuft Task 7 Step 2-4 durch und die drei Zahlen stehen fest.

## ⏸ GATE bei Task 7 — NICHT ueberspringen
Die Migration muss 1610 / 1120 / 1090 zeigen (Events #1, #81, #136), bevor Task 8 irgendeinen
produktiven Pfad anfasst. Stimmen die Zahlen nicht, liegt der Fehler in Task 1-6 -> zurueck, nicht
vorwaerts. #123 darf abweichen (618 -> 417, einzige CSV-Zeile im Bestand).

## Bekannter Zwischenzustand (kein Defekt)
Task 1-5 bauen app/transport_stacks.py neben dem alten Kern auf. Bis Task 8 rechnet der Kutter
weiter mit dem alten Modell + Latch. Das ist Absicht (Big Bang: der Latch kann nicht halb weg).

## Vorab behoben (Pre-Flight-Scan, Commit s.u.)
PLANFEHLER Umlaute — identisch zum track-diagnose-Lauf: die python-Bloecke schrieben ASCII-Ersatz
("fuer", "laedt", "Fischbroetchen"), obwohl die Global Constraint des Plans selbst UND das Repo
echte Umlaute verlangen — auch in TESTDATEN (tests/test_transport.py:1436 "Strandkörbe";
app/database.py:4510 Seed; app/database.py:212 Kommentar "Fischbrötchen").
170 Zeilen in python-Bloecken gezogen, Ausgabe-Strings + Assertions gemeinsam. Verifiziert:
kein Identifier mit Umlaut, "Fischbrötchen" 29x konsistent, Spaltenausrichtung im Task-7-
Erwartungsblock nachgezogen (Umlaut = 1 Zeichen statt 2).

## ⚠️ FUENFTE FALLE — vom Task-6-Implementer gefunden, groesser als er dachte (16.07.)
Der Adapter haette die HAEUFIGSTE Lieferung versenkt. Beleg (selbst am Code geprueft):
  app/poller.py:885-891  ->  close_flight(conn, id, last_pos or now_str)
                             last_pos = MAX(ts) FROM position_history
  d.h. logoff_time IST der Zeitstempel des LETZTEN GPS-SAMPLES, keine eigene Uhrzeit.
  Poll-Takt = 15 s (VATSIM_POLL_INTERVAL). Wer landet und binnen 15 s aussteigt, hat also
  logoff_time == landing_ts EXAKT. _STACK_EVENT_PRIO sortiert den Logout dann VOR die Landung,
  er findet position=None vor (takeoff hat sie geleert) -> VERSENKT statt geliefert.
  Das ist der Normalfall "abgeliefert, Feierabend" — nicht ein Grenzfall.
ENTSCHEIDUNG (Option A, von mir getroffen, Nutzer schlief): Logout einer Session auf
  "letzte eigene Landung + 1 s" schieben, WENN er auf/vor ihr liegt. _STACK_EVENT_PRIO bleibt.
  Die verworfene Option B haette den Test entschaerft — also einen echten Produktionsfehler
  weichgeklopft. Genau das Anti-Muster, das uns in Task 2 schon einmal eingeholt hat.
NUTZER BITTE PRUEFEN: das ist die einzige inhaltliche Entscheidung, die ich ohne dich getroffen
  habe. Plan + Code + Test tragen die Begruendung. Fable hatte diese Falle NICHT gefunden.

## Stehende Schreibregel fuer JEDEN Dispatch
- Docstrings / Kommentare / Doku / Ausgabe-Strings / Testdaten = ECHTE Umlaute
- Identifier (def-, Variablen-, Testnamen) = ASCII        <- Repo hat NIRGENDS Umlaute in def-Namen
- Commit-Messages = ASCII                                  <- Repo-Konvention

- Task 1: complete (commit 100d6a1, 3 Tests gruen, Review: Spec ✅ / Qualitaet Approved)
  - Woertliche Umsetzung des Briefs. Umlaut-Vorabfix hat gewirkt: KEINE ASCII-Nacharbeit noetig
    (im track-diagnose-Lauf kostete genau das eine Fix-Schleife).
  - ⚠️ Reviewer: _EPS = 0.01 in diesem Task unbenutzt. SELBST GEPRUEFT -> kein Mangel: der Plan
    verdrahtet es in Task 2 (Z. 423-430), 3 (569), 4 (778/790), 5 (912-925). Zwischenzustand.
  - Minor (kosmetisch, kein Handlungsbedarf): task-1-report nennt 65/57 Zeilen, Diff-Stat 63/59.
- Task 2: complete (commit d319f0c, 8 Tests gruen, Review: Spec ✅ / Qualitaet Approved)
  - Reviewer-Fund "Important: capacity_kg ist in keinem Test bindend" -> SELBST GEPRUEFT, KEIN
    Mangel: Task 5 bindet es (capacity_kg=200 erzwingt exakt 50 Fisch + 150 Tee; capacity_kg=250
    kappt 800 auf 250). Eine kaputte free-Rechnung schluege dort rot. Der Reviewer sah nur Task 2.
  - Reviewer-Fund "Minor: Reihenfolge-Test unterscheidet since nicht von cid" -> ECHT, und GROESSER
    als gedacht. Mein erster Fix (CIDs tauschen) war FALSCH und per Mutation widerlegt:
    `sorted(standing)` statt `key=(since, cid)` liess alle 8 Tests gruen. Grund: _load_standing
    laeuft nach JEDEM Ereignis -> der Erste raeumt den Stapel leer, bevor der Zweite einloggt;
    die Sortierung wird nie befragt. Fix zurueckgedreht.
    ECHTE Ursache: die Ankunftsreihenfolge (Entscheidung 5) wird von KEINEM Test des Plans
    geprueft. Sie kann es erst, wenn ZWEI an einem leeren Stapel warten und Ware zurueckkommt —
    das braucht Logout (Task 4). Task 5 hatte nur EINEN Wartenden.
    => Plan ergaenzt: neuer Test `test_von_zwei_wartenden_laedt_der_laenger_stehende` in Task 5
       (spaeter angekommene CID ist die kleinere) + neuer Step 4b: Mutationsprobe PFLICHT
       (sorted(standing) muss ihn rot machen). Erwartete Zahl in Task 5 Step 4: 22 -> 23.
- Task 3: complete (commit 7612b36, 12 Tests gruen, Review: Spec ✅ / Qualitaet Approved)
  - Reviewer hat die Mutationsfrage selbst durchgerechnet (Lehre aus Task 2): "liefert bei JEDER
    Landung" macht S2 rot (Tee 500 statt 200), S3 rot (Fisch 0 statt 800); Bedingung umgedreht
    macht S1 rot. Die Tests beissen also nachweislich.
  - Minor (fuers finale Review): app/transport_stacks.py:91-92 nutzt e.get("airport") statt der
    zwei Zeilen zuvor gebundenen Variable `airport`. Funktional identisch, doppelter Lookup,
    Abweichung vom Brief (der `if airport:` zeigt). Reine Stilfrage.
  - ⚠️ "Sind die airport-Werte echter landing-Events GPS-abgeleitet?" -> Task 6 (Adapter) baut sie
    aus canonicalize_legs/gps_arrival. Global Constraint deckt das ab, kein offener Punkt.
- Task 4: complete (commit 7d0b080, 18 Tests gruen, Review: Spec ✅ / Qualitaet Approved)
  - Die drei Ausgaenge sind GEGENEINANDER unterscheidbar (nicht nur gegen "verschwunden"):
    S4 trennt aktueller vs. urspruenglicher Ladeplatz vs. gestohlen; S5 trennt gestohlen von
    versenkt (Ort bekannt vs. None); S8 umgekehrt. Der Erhaltungssatz allein koennte das nicht.
  - _drop_load deckt Logout UND zweiten Login ohne Logout ab (Fable-Fund E1) — der Test dazu
    braeche ohne Fix den Erhaltungssatz (500 statt 1300).
  - Minor (fuers finale Review): kein Test prueft movements[].kind direkt. Reviewer hat per Grep
    bestaetigt, dass returned/stolen/sunk zu app/database.py:4795-4800 (Badge/Quips) passen.
    Teilweise aufgefangen: Task 8 assertet loss_kind == "returned" (Plan 1684) und filtert auf
    alle drei (1783) -> Abdriften wuerde dort rot. Fuer stolen/sunk bleibt es duenn.
  - Aufgeraeumt: .superpowers/sdd/ enthielt Briefs/Reports aus DREI frueheren Laeufen mit
    denselben Dateinamen (task-5-report.md, task-6-brief.md ... aus track-diagnose, 15.07.).
    Der Task-4-Implementer stiess darauf. 61 Alt-Dateien nach archiv-vor-kutter-stapel/
    verschoben. Briefs/Reports 1-4 waren nachweislich alle von heute -> kein Reviewer hat
    Fremdes gelesen. Ab Task 5 waere die Falle scharf gewesen.
- Task 5: complete (commit 9241b32, 23 Tests gruen, Review: Spec ✅ / Qualitaet Approved)
  ==> DIE REINE ZUSTANDSMASCHINE IST FERTIG. app/transport_stacks.py, DB-frei, 23 Tests.
  - MUTATIONSPROBE BESTANDEN (Step 4b, den ich nach dem Task-2-Fund eingezogen hatte):
    sorted(standing) ohne since-Key machte GENAU test_von_zwei_wartenden_laedt_der_laenger_stehende
    rot (assert 0.0 == 800.0), die anderen 22 blieben gruen. Rueckgedreht wieder 23 gruen.
    Damit ist Entscheidung 5 nachweislich geprueft — der Kreis aus Task 2 ist geschlossen.
  - Reviewer hat die Kappung von Hand nachgerechnet: unterscheidet "begrenzt die Bordladung" von
    "begrenzt den Ladevorgang" (50 statt 150 kg nach drei Landungen). Kein Placebo.
  - Important (gegen den BRIEF, nicht den Implementer): Step 2 nannte keinen Erwartungswert fuer
    die drei "brauchen keine eigene Regel"-Tests (Wartender/zwei Wartende/Musterwechsel). Ein von
    Anfang an gruener Test beweist nichts, wenn niemand das vorher erwartet hat. Der Implementer
    hat es im Bericht nachgeholt (Step-2-Output 2 failed/21 passed, arithmetisch konsistent:
    18 Alt + 3 schon gruene neue). Erledigt, aber als Planschwaeche notiert.
  - Minor: per_flight_max_kg == 0 wird wie None behandelt (kein Limit statt "null erlaubt"), und
    0 IST erreichbar (_opt_float(0) -> 0.0, nicht None; app/database.py:4415-4419).
    SELBST GEPRUEFT -> KEINE Regression: der ALTE Kern macht es identisch
    (app/database.py:5725 `cap if (cap is not None and cap > 0) else _INF`). Der Plan spiegelt
    bewusst bestehendes Verhalten. Nicht in diesem Umbau anfassen (soll bitidentisch rechnen).
- Task 6: complete (76d1f9a + Fixes 50dab8c + 5a4661e; 1108 Tests gruen, 0 rot — SELBST
  nachgelaufen, nicht nur berichtet. Review: Spec ✅ / Qualitaet Approved nach zwei Fix-Runden.)

  Der teuerste Task des Plans. Opus-Review (bewusst Opus: riskantester Diff, nachts kein Mensch
  im Loop) fand 2 Critical + 2 Important + 3 Minor. Alle behoben, jeder Fix per MUTATION belegt.

  🔴 C2 — MEIN EIGENER FEHLER, vom Review gefangen. Meine Option-A-Anweisung nahm
     max(logoff_time) ueber ALLE eigenen Legs, obwohl `own` nur logon_time begrenzt. Bei S8
     (Logout in der Luft 09:30, EIN durchgehendes Leg mit Landung 10:00) sprang der Logout auf
     10:00:01 — 30 min nach vorn, mitten in Session 2; der Pilot flog aus `position`, waehrend
     er verbunden war, und lieferte 0 kg. Ich hatte beim Beheben eines Critical einen gebaut.
     Fix: Menge auf Landungen <= lf begrenzen. Nebeneffekt (geprueft, richtig): die Bedingung
     kollabiert auf exakte Gleichheit — "Logout vor der Landung" ist strukturell unmoeglich.
  🔴 C1 — der dtend-Test biss nicht (Takeoff 22:57 vor dtend 23:00 -> Filter feuerte nie).
     DER TASK-2-FEHLER WOERTLICH WIEDERHOLT. Fix: Testdaten (Takeoff 23:05 NACH dtend).
     Der Fixer hat ZUERST reproduziert, dass die alte Fassung unter der Mutation gruen blieb.
  🟠 I3 — die SECHSTE FALLE, gefunden nur weil ich den Reviewer ausdruecklich danach suchen
     liess. canonicalize_legs hat einen GPS-losen Fallback (_flightrow_as_flight): ohne
     erkanntes Leg wird eine flights-Zeile als Leg ausgegeben, departure/arrival AUS DEM
     FLUGPLAN. Der Adapter machte daraus Phantom-takeoff/-landing = #23-Verstoss im Herzen des
     Umbaus, der #23 durchsetzen soll. Musste ZWEIMAL gefixt werden (Sessions-Block 50dab8c,
     StatSim-Block 5a4661e) — derselbe Defekt an zwei Stellen.
  🟠 I4 — _covered_by_session war ungetestet (einziger Schutz gegen StatSim-Doppelzaehlung).
     WICHTIG: bei Doppelzaehlung bleibt der Erhaltungssatz FORMAL ERFUELLT (Ware wird doppelt
     aus dem Stapel genommen). Der Satz, auf dem die Kernzusage des Plans ruht, haette es nicht
     gemerkt. Test + Mutation ergaenzt.

  ZWEI MEINER VORGABEN WAREN FALSCH, der Fix-Agent hat sie begruendet zurueckgewiesen — richtig:
   (a) Ich schlug `gps_departure is None and gps_arrival is None` als Fallback-Merkmal vor. Ein
       ECHTES Leg kann das auch haben (nearest_airport liefert None ausserhalb des Radius,
       gps_legs.py:195) -> haette echten Fluegen die Ereignisse geklaut. Er nutzt `block_start`:
       von _gps_flights_for_positions IMMER gesetzt (database.py:2312/2368), von
       _flightrow_as_flight NIE, kein dritter Weg (Reviewer hat es erschoepfend gegengeprueft).
   (b) Mein vorgeschriebener I3-Test biss nicht (nach dem Filtern ist `real` leer -> `if real:`
       schliesst kurz). Er hat es GEMESSEN und einen Test fuer den wirklich erreichbaren Fall
       gebaut (echtes Leg mit gps_departure=None via >30-min-Feed-Luecke + Spawn bei 4000 ft).

  🟡 Minor offen fuers finale Review:
     M5 String-Vergleich auf Zeitstempeln mit moeglichen Mikrosekunden (database.py:5285,
        5419-5420, 5407) — gegen die HAUSEIGENE Regel (_flightplan_asof-Docstring, :2165).
        Kein belegter Live-Schaden; _gap_seconds selbst rechnet korrekt.
     M6 statsim_id als StatSim-Merkmal, obwohl `source` unbedingt gesetzt ist (:5480/:5511).
     M7 Ungeprueft: "landing vor takeoff" in _STACK_EVENT_PRIO, der cid-Tiebreaker, und die
        Manifest-Feldabbildung (.get() -> Schluesseldreher scheitert STILL, Summe 0).
     M8 (Fussnote des Reviewers) Die S8-Testdaten liegen mit Luecken von 25/23 min nahe an
        _GPS_LEG_GAP_MINUTES=30. Heute korrekt, aber der Test braeche still, faellt die
        Konstante je.

  ⚠️⚠️ FUER TASK 8 ZWINGEND VORMERKEN:
   1. canonicalize_legs MARKIERT seine Fallback-Legs nicht — jeder Konsument muss das Fehlen von
      `block_start` selbst erkennen. Task 8 waere der DRITTE Konsument und wuerde die Falle
      erneut aufstellen. Vorschlag des Fix-Agenten: ein Helfer `_is_gps_leg(g)` oder ein Feld
      `source_kind` AN canonicalize_legs — sauberer, aber Eingriff in Fremdcode.
   2. logoff_time == landing_ts ist eine Eigenschaft der DATEN (poller.py:891), nicht des
      Adapters. Wo Task 8 sonst nach Zeitstempel ordnet, gilt dieselbe Kollision.
   3. legs_by_cid/sessions enthalten auch Legs von Nicht-Teilnehmer-Sessions (Legs laufen bis
      now, Sessions nur bis dtend).

- Task 7: offen (GATE)
- Task 8: offen
- Task 9: offen
- Task 10: offen
- Task 11: offen
- Task 12: offen

## Minor-Funde fuers finale Review
(noch keine)

---

## Vorheriger Lauf (abgeschlossen + gepusht): Skill "track-diagnose"
6 Tasks + Whole-Branch-Review, Commits 9a35e96..289d434. Details in der Git-Historie
(6889534 "fix: Code-Review-Findings track-diagnose"). Offen geblieben: Task #2 der Aufgabenliste
(Praxis-Regeln vom 15.07. in die SKILL.md nachtragen) — gehoert NICHT zu diesem Plan.
