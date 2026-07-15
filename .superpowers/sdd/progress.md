# SDD-Ledger — FriesenKutter Stapel-Modell

Plan: docs/superpowers/plans/2026-07-16-kutter-stapel-modell.md
Spec: docs/superpowers/specs/2026-07-15-kutter-stapel-modell-design.md (14 Entscheidungen, alle bestaetigt)
Basis vor Task 1: 7d58e1f
Branch: main (stehende Nutzer-Regel: kein PR-Umweg; nur vor `git push origin main` bestaetigen lassen)

Reihenfolge: 1 -> 2 -> 3 -> 4 -> 5 (reine Funktion) -> 6 (Adapter) -> 7 GATE -> 8 -> 9 -> 10 -> 11 -> 12
             -> Whole-Branch-Review (Opus)

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
- Task 3: offen
- Task 4: offen
- Task 5: offen
- Task 6: offen
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
