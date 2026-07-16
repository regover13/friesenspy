# SDD-Ledger — FriesenKutter Stapel-Modell

##############################################################################
#  GATE BESTANDEN (16.07. vormittags, mit dem Nutzer durchgesprochen)
##############################################################################

Die Migration lief gegen eine KOPIE der Prod-DB (Nutzer hat den scp freigegeben; Kopie lag unter
D:/User/Tobias/kutter-kopie.db, NICHT im Repo, *.db-ignoriert). Ergebnis + Deutung, ALLE VIER
Abweichungen verstanden und vom Nutzer ABGENOMMEN:

  #1   1610 -> 1347  DA40-Reconnect (FRS22): 6-min-Verbindungsabriss 7 km vor EDXH im Endanflug,
                     Landung faellt ins Loch -> 263 kg versenkt. Der "Straddle-Merge" (Sessions
                     verketten, wenn ein Leg drueberlaeuft) wurde VERWORFEN: er haette den
                     Versenk-Test des Nutzers (#123, gleiches Muster!) kaputtgemacht. Als "Pech"
                     akzeptiert. NEUES SOLL 1347.
  #81  1120 -> 1120  identisch. Der Normalfall, nichts Besonderes.
  #136 1090 -> 1240  Staffel-Lieferung: Ware auf Zwischen-Ladeplatz EDWL zurueckgegeben, anderer
                     Pilot nimmt sie mit ans Ziel. Das ALTE Modell unterzaehlte das (Latch konnte
                     Fracht nicht ueber Rueckgabe+Weitergabe verfolgen). Neues Modell RICHTIGER.
                     Erhaltungssatz beweist die 600 (kann nicht mehr liefern als da ist). SOLL 1240.
  #123  618 -> ~250  Nutzers eigener VERSENK-TEST (FRS49, Fluege 357/358, EDXH->EDXH, erreicht das
                     Ziel EDWG nie) + CSV-Zeile mit Komma-departure "EDWL,EDXH,EDXP" (kein echter
                     Platz -> laedt nie). SOLL VERSENKEN — korrekt versenkt. Abweichung erwartet.

+1s-ENTSCHEIDUNG (fuenfte Falle) ABGENOMMEN + BEHALTEN, Kommentar korrigiert:
  An FRS49 in #1 demonstriert: MIT +1s liefert der Flug 316 kg, OHNE ihn werden 316 kg VERSENKT
  (Logout sortiert bei Gleichstand vor die Landung, findet position=None). Meine urspruengliche
  Begruendung "Normalfall abgeliefert Feierabend" war FALSCH (Nutzer: normal rollt man ans Gate,
  logoff kommt spaeter). RICHTIG: seltener Touchdown-Disconnect am Ziel. Kommentar in
  app/database.py:5471 ff., Plan und hier entsprechend gefixt.

STAND: GATE bestanden. Kein SSH / keine Prod-DB mehr noetig. Task 8-12 = reiner Code + Tests,
CLOUD-TAUGLICH. 1108 Suite gruen (+ Kommentar-Fix = No-Op, 214 im Transport-Teil gruen).
NAECHSTER SCHRITT: Task 8 (compute_transport_progress auf die Ableitung umstellen).

##############################################################################


##############################################################################
#  GUTEN MORGEN — STAND 16.07., NACHTS.  DAS HIER ZUERST LESEN.
##############################################################################

TASK 1-7 SIND FERTIG, SOWEIT SIE OHNE DICH GEHEN. 1108 Tests gruen, 0 rot.
NICHTS GEPUSHT (deine stehende Regel: vor `git push origin main` fragen).
NICHTS AM PRODUKTIVEN KUTTER GEAENDERT — der rechnet weiter wie bisher.

## Was du tun musst: EIN Befehl, dann steht das GATE

Die Migration braucht eine KOPIE der Prod-DB. Der Zugriff auf den Produktions-Host wurde von
der Berechtigungspruefung abgelehnt (zu Recht — du hattest ihn nie freigegeben). Ich habe das
NICHT umgangen.

  scp server:/opt/friesenspy/data/friesenspy.db "D:/User/Tobias/kutter-kopie.db"
  python -m scripts.kutter_stapel_prototyp "D:/User/Tobias/kutter-kopie.db"

ACHTUNG Windows: KEIN /tmp-Pfad. Git Bash verbiegt Unix-Pfade (gemessen: /opt/... kommt bei
python.exe als "D:/Program Files/Git/opt/..." an). Deshalb Windows-Pfade wie oben.
Die Prod-DB ist live + WAL (43 MB, der Poller schreibt laufend) — falls eine .db-wal daneben
liegt, mitkopieren. Das Skript oeffnet die Kopie mit mode=ro und weigert sich, auf
/opt/friesenspy/ zu zeigen (beides verifiziert).

ERWARTET:
  #1    FriesenKutter-Test Wangerooge      SUMME  1610 -> 1610   IDENTISCH
  #81   Strandkoerbe und Sonnenschirme     SUMME  1120 -> 1120   IDENTISCH
  #136  Grossauftrag fuer Wooge            SUMME  1090 -> 1090   IDENTISCH
  #123  Multi-Kutter-Test                  SUMME   618 ->  417   ABWEICHUNG (erwartet, CSV-Zeile)
  + Erhaltungssatz "OK" fuer alle vier

STIMMEN DIE DREI ZAHLEN -> Task 8 freigeben (erst dann faesst irgendwas den Produktivpfad an).
STIMMEN SIE NICHT   -> der Fehler liegt in Task 1-6. ZURUECK, NICHT VORWAERTS. So ist der Plan
                       gebaut, und heute Nacht hat sich gezeigt, warum.

## Eine Entscheidung habe ich ohne dich getroffen — bitte anschauen

Der Adapter haette die HAEUFIGSTE Lieferung versenkt. poller.py:891 schliesst einen Flug mit
`close_flight(conn, id, last_pos)`, wobei last_pos = MAX(ts) aus position_history — logoff_time
IST das letzte GPS-Sample. Bei 15 s Poll-Takt hat jeder, der landet und binnen eines Takts
aussteigt, logoff_time == landing_ts EXAKT. Der Logout sortierte dann vor die Landung, fand
position=None und versenkte die Fracht. NICHT der Normalfall (Nutzer-Korrektur 16.07.: normal
  rollt man ans Gate, logoff kommt spaeter) — der seltene Touchdown-Disconnect am Ziel.
Ich habe das gefixt (Logout auf letzte-eigene-Landung + 1 s, wenn er auf/vor ihr liegt).
Die Alternative waere gewesen, den Test zu entschaerfen — das haette den Fehler versteckt.
Begruendung steht im Code, im Plan und unten bei Task 6.

## Bilanz der Nacht: der Plan war an SECHS Stellen falsch

Alle sechs am Code belegt, alle sechs behoben, jeder Fix per Mutation bewiesen statt behauptet.
Zwei davon waren MEINE Fehler (siehe Task 2 und Task 6/C2). Die sechste Falle gab es nur, weil
ich den Reviewer ausdruecklich danach suchen liess.
Ein Muster hat sich dreimal wiederholt und ist die Lehre der Nacht:
  ==> TESTS, DIE EINE REGEL ZU PRUEFEN SCHEINEN, ABER AUCH BEI KAPUTTER REGEL GRUEN BLEIBEN.
      Deshalb ist die Mutationsprobe jetzt ein Pflichtschritt im Plan (Task 5, Step 4b).

##############################################################################

Plan: docs/superpowers/plans/2026-07-16-kutter-stapel-modell.md
Spec: docs/superpowers/specs/2026-07-15-kutter-stapel-modell-design.md (14 Entscheidungen)
Basis vor Task 1: 7d58e1f
Branch: main (stehende Regel: kein PR-Umweg; nur vor `git push origin main` bestaetigen lassen)

Reihenfolge: 1-5 (reine Funktion) ✅ -> 6 (Adapter) ✅ -> 7 GATE ⏸ DU -> 8 -> 9 -> 10 -> 11 -> 12
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
  NICHT der Normalfall (Nutzer-Korrektur 16.07.) — der seltene Touchdown-Disconnect am Ziel.
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

- Task 7: Step 1+3 complete (08a2f16) — Step 2+4 WARTEN AUF DICH (Prod-DB-Freigabe, s.o.)
  Prototyp rechnet jetzt mit der ECHTEN Ableitung (_stack_inputs + derive_stacks) statt mit
  seiner eigenen Regelkopie. DB-Verbindung entschaerft: Pfad per Argument, Sperre gegen
  /opt/friesenspy/, mode=ro. Selbst verifiziert: Sperre feuert (MSYS_NO_PATHCONV=1 noetig,
  sonst verbiegt Git Bash den Testpfad — meine erste Messung war deshalb falsch, nicht der Code).
  Das Skript schreibt NIRGENDS (0 Treffer INSERT/UPDATE/DELETE/COMMIT).
  NICHT verifiziert: die drei Zahlen. Dafuer fehlt die DB.
- Task 8: complete (Cloud-Session, GATE bestanden vorausgesetzt). compute_transport_progress rechnet
  jetzt mit Stapeln (derive_stacks/_stack_inputs) statt zu raten; _empty_transport_progress ergaenzt;
  Import derive_stacks/STOLEN/SUNK auf Modulebene (transport_stacks ist DB-frei -> kein Zyklus).
  5 neue TestStapelProgress gruen, 1056 gesamt gruen. API-Vertrag unveraendert (main/poller importieren
  sauber, alle Konsumenten lesen loss_kind mit .get()/JS-falsy — vertragsgleich zum Altcode).
  DREI Funde/Entscheidungen dieser Session (alle mit dem Nutzer besprochen):
   1. logout_ts (EIGENE Zutat ueber den Plan, vom Nutzer FREIGEGEBEN): der Plan-Feed suchte die
      Verlust-Zeile per logoff_time — die Verlust-Bewegung traegt aber den +1s-verschobenen Logout-ts
      (Touchdown-Disconnect, S4). _stack_inputs vermerkt jetzt den effektiven Logout-ts an der Session,
      der Feed sucht danach. Aendert KEINE Zahl, nur welche Feed-Zeile das loss_kind-Label traegt.
      Mutationsprobe: ohne den Fix war test_s4 rot (loss None), mit gruen.
   2. S2/S3-Testmodellierung KORRIGIERT (Nutzer-Einwand "leg <> Verbindung, das soll so sein"): zwei
      _add_flight mit 10-min-Luecke = echter Disconnect+Reconnect, NICHT die gemeinte durchgehende
      Reise. Beleg im Poller (poller.py:837): ein Refile-Split schliesst Leg 1 IM Refile-Moment
      (logoff(Leg1)==logon(Leg2), keine Luecke) -> _transport_sessions verkettet zu EINER Verbindung.
      Tests bilden das jetzt so ab (duration_min=30/20 statt 20/20). Diskriminiert nachweislich:
      mit Luecke -> S3=0 (stolen am fremden EDDW), ohne Luecke -> S3=800. Kein Placebo.
   3. Poller-Seeds (Nutzer-Regel "ohne Track kein Kutter-Flug", FREIGEGEBEN): _seed_with_flight legte
      eine nackte flights-Zeile OHNE position_history -> Fallback ohne block_start -> zaehlt zu Recht
      nicht mehr (flight_count 0). Neuer Helfer _seed_kutter_track schreibt einen echten GPS-Track
      (Boden-Start EDWG = laedt, Landung EDXH = liefert). TestTransportSummaryEmptyEventSuppressed +
      TestTransportSnapshotFreeze wieder gruen.
  ⚠️ OFFEN fuer Task 9 (kein Task-8-Bug): 57 rote Tests sind ALLE Latch-/entfallene-Feature-Tests
     (56 in test_transport.py, PLAN-erwartet + Gegenstand Task 9/10; 1 in test_poller.py =
     TestLegSplitLatchKey, steht auf der Task-9-Loeschliste des Plans (test_poller.py:509-635,
     importiert get_transport_live_arrivals). NICHT frisiert — Task 9 entfernt ihn.
  💡 EMPFEHLUNG fuers finale Review (NICHT umgesetzt, weil defensiv + keine Beobachtungsaenderung, und
     der Nutzer will keine eigenmaechtigen fachlichen Aenderungen): der Feed-Loop in
     compute_transport_progress iteriert own=legs_by_cid OHNE block_start-Filter. Aktuell harmlos
     (Fallback-Legs haben gps_departure/arrival=None -> Sichtbarkeitsfilter schliesst sie aus), aber
     Ledger-Task-8-Vormerkung #1 wollte den expliziten Guard. Mit dem Nutzer abstimmen.
- Task 9: complete (Cloud-Session). Latch-Rueckbau: aus app/database.py ERSATZLOS geloescht
  set_transport_live_arrival, get_transport_live_arrivals, record_transport_loss, get_transport_losses,
  detect_transport_losses, check_live_arrival, active_transport_destinations, _latch_hits_flight,
  _connection_logon_for_leg (Waise), _returning_pilot_landed (Waise), _LATCH_SLACK_SEC.
  transport_anyone_in_progress auf Entscheidung 10 umgestellt ("traegt noch jemand Ware?" statt
  "offener Flug auf Strecke"). app/poller.py: Block 2c (check_live_arrival) + detect_transport_losses-
  Aufruf/Import raus. block_start-Guard im Feed-Loop ergaenzt (die in Task 8 vermerkte Empfehlung —
  in Task 9 mit umgesetzt, defensiv, keine Verhaltensaenderung). Tabellen transport_live_arrivals/
  transport_cargo_losses bleiben im DDL (Altdaten), werden nur nicht mehr geschrieben/gelesen.
  BEHALTEN (kein Waise, Plan-"pruefen" bestaetigt): open_transport_flights + transport_event_started
  (Start-Push, poller.py:1305), _current_pos, _first_pos, _LANDED_MAX_GS_KT (Zweitnutzer :1797).
  Verifikation: pytest tests/ -q -> 1073 passed, 1 xfailed, 0 failed. scripts/kutter_ladung_szenarien.py
  laeuft (Latch-Importe + S2b/S3b raus, verluste-Block auf losses[]; S2/S3 als Refile-Split; S8-db-
  Import gefixt): S1=800, S2=800+200, S3=800, S4=returned, S5=stolen 800, S8=sunk 800.
  Test-Umbau test_transport.py (Sub-Agent, danach von mir verifiziert): 42 umgeschrieben, 19 geloescht
  (+ 17 Latch-Klassen-Tests von mir vorab). MUTATIONSPROBE bestanden: stolen->returned-Mutation in
  transport_stacks macht 5 Verlust-Tests rot -> sie beissen. Anti-Schwaechungs-Scan: die 72 fehlenden
  Assertions entsprechen exakt den geloeschten Tests, alle umgeschriebenen pruefen konkrete Werte.
  test_poller.py: TestLegSplitLatchKey + TestKutterLiveArrivalHook geloescht (Latch); der Nachzuegler-
  Test (test_summary_deferred_while_pilot_in_progress) auf Entscheidung 10 umgebaut (Pilot traegt Ware
  am Ladeplatz statt "offener Flug").
  ✅ Die manifestlose-Event-Frage ist ENTSCHIEDEN (Nutzer 16.07.): kein Zaehler-Modus, war nie
     gewollt. manifestlos = 0. Test umbenannt -> test_no_manifest_delivers_nothing, prueft
     total_kg == 0.0 (kein Sonder-Code noetig, das Stapel-Modell liefert das von selbst). xfail
     entfernt. pytest tests/ -q -> 1074 passed, 0 failed, 0 xfailed.
- Task 10: complete (Cloud-Session). Frontend app/static/index.html: fetchKutterActive speist den
  Live-Block jetzt aus d.participants (visible/place/reserved_kg/cargo_lines) statt aus d.flights;
  Status = Ort x Ladung (🅿️ laedt/steht, ✈️ unterwegs/dabei). '✅ angekommen' + '↩️ Rueckflug'
  entfallen. _kCargoLabel: laedt/unterwegs/leer; _kutterDetailBody: Tilde vor Reservierungsmenge
  weg. _kLossLabel unveraendert. BROWSER-VERIFIZIERT (Playwright, Chromium /opt/pw-browsers/
  chromium-1194, executable_path noetig wegen Build-Mismatch; API per Route gemockt): Live-Banner
  rendert alle 5 sichtbaren Status korrekt, visible:false ausgeblendet, keine PAGEERRORs; Detail-
  Feed zeigt "500 / 1000 kg ✈️" ohne Tilde. Screenshots im Scratchpad (t10_live.png, t10_detail.png).
  NACHTRAG (Nutzer-Regel 16.07., Commit 6a041d6): Strecke im Live-Block = letzter Landeplatz ->
  Ziel-der-Ware. START = participants.last_ground (neu durchgereicht aus r["last_ground"]): bleibt
  im Flug erhalten (place wird beim Abheben None), wechselt bei jeder Zwischenlandung (auch fremd).
  ZIEL nur MIT Ware bekannt (= Event-Ziel); ohne Ware "Start -> —". Behob: (a) Strecke in der Luft
  MIT Fracht war leer (haing an place statt last_ground), (b) "EDXH -> EDXH" am Ziel. Der ganz leere
  Fall (kein Start) trifft nur unsichtbare Zeilen -> rendert nie (mit dem Nutzer geklaert). Backend-
  Feld per Test abgesichert (test_participant_hat_last_ground_als_strecken_start).
- Task 11: complete (Cloud-Session). Entscheidung 6 durchgesetzt: jede Manifest-Zeile = ein Stapel =
  GENAU EIN Startplatz != Ziel, Pflicht. main.py _validate_transport_manifest (Fehlertext "genau
  einem Platz"), database.py set_transport_cargo (wirft ValueError, verbindlich serverseitig),
  calendar_sync.py parse_cargo_lines (kein-ICAO/Multi-ICAO -> Zeile verworfen), admin.html (Feld-
  hinweis + Client-Check gegen Multi). Der "geteilte Topf" (departure NULL) entfaellt ganz.
  ECHTER NEBENFUND selbst behoben: der Kalender-Sync (upsert_calendar_transport_event) degradierte
  einen fernen/Tippfehler-Marker-ICAO auf departure=None -> set_transport_cargo haette jetzt
  gecrasht. Er VERWIRFT solche ortlosen Zeilen nun (nur Ein-Platz-Zeilen auf der Route != Ziel
  ueberleben), statt den Sync zu killen.
  Tests: 4 neue Validierungstests (main) + 3 (calendar) via Sub-Agent, danach von mir verifiziert.
  19 durch die Regel gebrochene Seeds gefixt (departure ergaenzt; 2 shared/NULL-Tests auf
  pytest.raises umgeschrieben; 1 geloescht). Backfill-Tests: Legacy-NULL jetzt per direktem SQL-
  UPDATE simuliert (via create_transport_event nicht mehr erzeugbar) — Backfill-Kern + Assertion
  unveraendert. MUTATIONSPROBE: alle 3 Guards permissiv -> 8 Tests rot -> sie beissen. Anti-
  Schwaechungs-Scan sauber. pytest tests/ -q: 1080 passed, 0 failed.
- Task 12: complete (Cloud-Session). _PROGRESS_SNAPSHOT_VERSION 3->4 (Entscheidung 9: neu rechnen).
  CHANGELOG: neuer Eintrag — PLANABWEICHUNG noetig, "9.2.0" war schon vergeben (2026-07-13) und die
  Top-Version war 9.5.0, also 9.6.0 (Schema title+items, highlight). VERSION leitet sich automatisch
  daraus ab (app/version.py). Doku via Sub-Agent, danach von mir verifiziert: architecture.md/api.md/
  README.md auf Stapel-Modell umgeschrieben (Latch/Reservierung/Verlust-Klassifikation raus,
  Erhaltungssatz + transport_stacks-Verweis rein). api.md-Feldvertrag GEGEN DEN CODE geprueft: status
  ∈ flying/loaded/loading/standing/dabei/done (kein arrived/returning), neue Felder visible/place/
  last_ground/cargo_lines, loss_kind/losses[]/lost_total_kg, "Event ohne Manifest = 0". Zwei
  widerspruechliche Kalender-Beispiele ("Fracht:" ohne ICAO als "wird uebernommen") selbst korrigiert
  (README + api.md). Commit f631d2a, Tag v9.6.0 remote. pytest tests/ -q: 1080 passed.

==============================================================================
ALLE PLAN-TASKS (8-12) ABGESCHLOSSEN. Offen: nur noch der Whole-Branch-Review (Opus).
Branch claude/session-complete-cloud-ready-oud6dx, Commits ab a31e943 bis f631d2a, Tag v9.6.0.
Stapel-Modell live-faehig: Latch komplett zurueckgebaut, Frontend auf Ort x Ladung, departure
Pflicht (ein Platz), Doku + Changelog + Snapshot-Version nachgezogen. 1080 Tests gruen, 0 rot.
NUTZER-GATE nach Deploy (Plan): #1=1610, #81=1120, #136=1090 pruefen; #123 zeigt erwartet 417.
==============================================================================

## Minor-Funde fuers finale Review
(noch keine)

---

## Vorheriger Lauf (abgeschlossen + gepusht): Skill "track-diagnose"
6 Tasks + Whole-Branch-Review, Commits 9a35e96..289d434. Details in der Git-Historie
(6889534 "fix: Code-Review-Findings track-diagnose"). Offen geblieben: Task #2 der Aufgabenliste
(Praxis-Regeln vom 15.07. in die SKILL.md nachtragen) — gehoert NICHT zu diesem Plan.
