# FriesenBrügge-Kennung und Zuordnung: Beschluss vom 25./26.09.2026

**GitHub-Issues:** #46 (Brügge und Server), #47 (Kniebrett). Jede Entscheidung steht dort
zusätzlich als Kommentar, mit dem Wortlaut des Nutzers.
**Stand:** besprochen und entschieden, **noch nicht umgesetzt**.
**Vorgehen:** These für These mit dem Nutzer durchgesprochen; die Szenarien zweimal von einem
zweiten Modell (Fable) gegen Code und Historie geprüft.

---

## 1. Anlass

Am 25.09.2026 bekam die FriesenBrügge des Nutzers (FRS49) die Kennung von FRS111N, der 22 m
daneben am Stand stand. FRS49 war noch nicht auf VATSIM, FRS111N schon; er war damit der
einzige Kandidat. Danach lehnte die Rückkehr-Schranke die Brügge dauerhaft ab, bis MSFS neu
gestartet wurde (#46). Im Kniebrett hing am selben Abend das Rufzeichen der geparkten VJH3RX
am fliegenden FRS111N (#47). Engelhard hatte Reiner auf seinem Kniebrett, obwohl Reiner in
den USA flog.

## 2. Was gemessen und geklärt ist

- **Die Kennung lässt sich wieder speichern.** `fopen` im `\work`-Ordner des Pakets übersteht
  in MSFS 2020 **und** 2024 einen Neustart, einen harten Abbruch und das Löschen und
  Neuablegen des Pakets. Ein gemeinsames Modul reicht (`friesenbruegge/probe-kennung/ERGEBNIS.md`).
  Bis 1.13 lief die Ablage über `MSFS_IO.h`, das es nur im 2024er SDK gibt; sie ist deshalb
  am 16.09. (1.14.0) entfallen. `fopen` war nie versucht worden.
- **Im Stand liegen Brügge und eigener VATSIM-Eintrag unter 1 m auseinander** (0,4–0,7 m,
  zwei Piloten, MSFS 2024). Die 20 m aus V13.5.2 betrafen die vPilot-Wiedergabe im Kniebrett,
  nicht die Brügge. MSFS 2020 und X-Plane sind nicht gemessen.
- **Verzögerung:** VATSIM-Position beim Server bis rund 20 s alt (2–5 s bei VATSIM, bis 15 s
  unser Abruf), auf der Karte bis 35 s (Kartenlegende, `fc12fa6`). Eine zwischenzeitlich
  genannte Zahl von 60 s war doppelt gezählt.
- **Ein Absturz des Simulators beendet auch die VATSIM-Verbindung** (Nutzer: vPilot merkt es
  und beendet sich).
- **Der Wechsel zu einem besseren Partner** war zweimal gebaut und wurde zweimal
  zurückgenommen: im Kniebrett am 16.08. (Flackern), auf dem Server am 14./15.09.
  (`deutlich_besser`, schwächte die Bindung statt die Identität). Er kommt nicht zurück.

## 3. Brügge und Server (#46)

### Grundsatz
- **Die Kennung benennt die Installation, nicht den Piloten.** Eine neue Brügge bekommt beim
  ersten Kontakt eine frische Zufallskennung vom Server, nie die eines Piloten, und speichert
  sie in `\work`. Welche CID dazugehört, steht nur auf dem Server. Eine Fehlzuordnung ist damit
  eine falsche Zeile auf dem Server, nie eine geteilte Kennung. Heute gibt `bruegge_kennung_fuer`
  die Kennung des Piloten zurück; genau so kam am 25.09. FRS111Ns Kennung zu FRS49.
- **Kandidaten über die CID, nicht über das Rufzeichen:** alle VATSIM-Verbindungen, deren CID
  sich über das Forum angemeldet hat, gleich unter welchem Rufzeichen. Heute: nur `FRS%`.
- **Zuordnung und Bewährung sind zwei Dinge.** Zugeordnet wird so früh wie möglich, im Stand.
  Bewährt wird erst im Flug. Nur eine bewährte Bindung verdient vollen Schutz.

### Die Thesen
| # | Entscheidung |
|---|---|
| 1 | **Keine Abkürzung „allein am Platz“.** Vor der eigenen Verbindung zeigt der Simulator keine VATSIM-Flugzeuge; zwei am selben Punkt sähen beide allein aus. Bewährt wird nur im Flug. |
| 2 | **Eindeutig im Flug heißt doppelter Abstand**, keine feste Strecke: Die gebundene Verbindung ist die nächste, jede andere infrage kommende mindestens doppelt so weit weg. Piloten, deren bewährte Brügge gerade meldet, zählen nicht mit. Rahmen: in der Luft (`am_boden` falsch), mindestens 40 kt. |
| 3 | **2 Minuten am Stück.** Reißt eine Bedingung, beginnt die Zählung neu. Gezählt an der Sekundenspur der Brügge. Die Platzrunde mit zwei Maschinen hintereinander ist kein Risiko: Die eigene Verbindung des echten Piloten liegt ihm immer näher als der Vordermann. |
| 4 | **Eine unbewährte Bindung wird nur nach einem Widerspruch vergessen** (vier Verstöße in Folge oder ein Sprung), nie weil der Partner fehlt. Widersprüche zählen nur mit frischen VATSIM-Daten. Eine bewährte Bindung bleibt. |
| 5 | **Keine Anwärter-Regel.** Stattdessen ein Admin-Knopf „vergessen“ (Bindung und Erinnerung löschen) und ein Hinweis in der Verwaltung auf Brügges, die seit Minuten abgelehnt werden („gebunden an A, passt zu B“). |
| 6 | **Erste Zuordnung einer neuen Brügge:** im Stand, wenn eine Verbindung höchstens 5 m entfernt steht. Beim Rollen keine Zuordnung über den Abstand. Im Flug (Sim-Start in der Luft) nach dem Maßstab für „bewährt“, dann sofort bewährt. |
| 7 | **Zwei am selben Punkt:** Im Stand wird nicht zugeordnet. Das Anrollen entscheidet: Die Brügge gehört zu der Verbindung, die sich innerhalb von 30 s danach ebenfalls bewegt. Rollen beide gleichzeitig los, entscheidet der Flug. |
| 8 | **Bei der ersten Zuordnung im Stand zählen nur Verbindungen, die nach der Brügge kamen** (VATSIM-Anmeldezeit nach der ersten Meldung dieser Sitzung). Sitzungsbeginn im Server-Speicher. Im Flug gilt die Bedingung nicht. |
| 9 | **Belegt-Test (10 s) und der zweite Versuch ohne Sperre entfallen.** „Vergeben“ gibt es nur beim Bewähren (These 2): bewährte Brügge, letzte Meldung höchstens 2 Minuten alt. Ein Pilot kann mehrere gebundene Brügges haben, eine je Rechner und Simulator; `bruegge_zuordnung_setzen` räumt ältere Zeilen nicht mehr weg. |
| 10 | **Eine bekannte Brügge wird ohne Suche zurückgebunden**, wenn ihre CID online ist und passt. Sonst wartet sie; andere werden nicht betrachtet. |
| 11 | **Protokoll 3 für die neue Fassung.** Die alte (Protokoll 2, bis 1.17.0) läuft vier Wochen weiter wie heute. `bruegge_kennung_fuer` gibt dabei nur Kennungen alter Fassungen zurück. Danach antwortet der Server mit 426. |
| 12 | **Umstieg:** Neue MSFS-Installationen beginnen ohne Bindung; nichts wird übernommen. X-Plane-Bindungen bleiben, gelten aber zunächst als unbewährt. Nicht direkt vor einem Event verteilen. **Download-Seite:** Nach der Installation den ersten Flug möglichst allein auf VATSIM machen, damit sich die FriesenBrügge bewährt. |
| 13 | **Kein Login-Anker für die Brügge auf dem Server**, vorerst. Wieder aufnehmen, wenn falsche erste Zuordnungen auftauchen. |

### Technisch, ohne eigene Entscheidung
- Zustand für noch nicht gebundene Brügges (Sitzungsbeginn, letzte Position) im Server-Speicher,
  nicht in der Datenbank. Sonst ließen sich per Skript massenhaft Zeilen anlegen (nginx erlaubt
  180 Meldungen je Minute).
- Die mitgeschickte Sekundenspur (`spur`) ablegen, als Grundlage für die 2 Minuten.
- Eine gelesene Kennung gilt nur mit genau 16 Hex-Zeichen, sonst verwerfen. Ein Lesefehler gilt
  als „keine Kennung“; eine fehlende Datei meldet `errno` 29, nicht `ENOENT`.
- Die Steam-Fassung ist nicht gemessen.
- Handbuch: Beim Deinstallieren bleiben `\work` und übersetzte Modulteile unter `LocalState` liegen.

## 4. Kniebrett (#47)

| # | Entscheidung |
|---|---|
| 14 | **Der Ausschluss bekommt dieselbe Entfernungsgrenze wie jede Zuordnung** (`_paarungMaxM`). Heute paart er ohne Grenze, und die Friesen kommen weltweit aus `liveData`. Die Spec vom 16.08. verlangte „im Gebiet“; das ging in der Umsetzung verloren. Beleg: Reiner in den USA. |
| 15 | **Der Filter „das bin ich“ (150 m / 100 ft) im Kniebrett-Paket wird ersatzlos gestrichen.** Gedacht gegen ein Geisterbild des eigenen Flugzeugs, das laut Code gar nicht vorkommt; gekostet hat er Nachbarn am Stand und den Rottenflieger. Die Seite zählt in der Diagnose mit, ob je ein Sim-Flugzeug auf der eigenen Position steht. Braucht ein neues Paket. |
| 16 | **Zuordnungen überstehen kurze Aussetzer.** Ist die Sim-Liste veraltet, bleiben die Zuordnungen gemerkt (heute: alle gelöscht). Fehlt ein Flugzeug in einer neuen Liste, bleibt seine Zuordnung 30 s erhalten. |
| 17 | **Ein stehender Partner hält kein bewegtes Flugzeug, und umgekehrt**, nach 35 s. Der Widerspruch zählt wie jeder andere (vier in Folge). Auch bei der Erstzuordnung. Anlass: `_paarungMaxM` rechnet mit der Geschwindigkeit des Sim-Flugzeugs; bei 119 kt hielt die geparkte VJH3RX es über 5 km fest. |
| 18 | **Anker:** Friesen mit eigenem Kniebrett (`e`) und bewährte Brügges (`b`). Das Sim-Flugzeug, das einem Anker klar am nächsten ist, gehört diesem Friesen. Über die CID; der Strom trägt das Rufzeichen und die Angabe „bewährt“ mit. Der Strom wird im Panel dafür wieder verarbeitet (heute verworfen, seit v14.45.0). |
| 19 | **Keine weiteren Umbauten** („nur bei Ereignissen zuordnen“, „Wechsel am Boden“). Nach den ersten Abenden die Diagnose der gelösten Zuordnungen ansehen. |

### Was „Kandidaten über die CID“ fachlich heißt (Nachfrage des Nutzers, 26.09.2026)
Es betrifft nur, **wem der Server eine FriesenBrügge zuordnet** — nicht, wer als Friese gilt
oder wie jemand angezeigt wird.
- Ein Friese unter fremdem Rufzeichen (etwa „DLH12“) bekommt seine Brügge jetzt zugeordnet:
  Objekte im Simulator (Wrack, Rauch) und Brügge-Punkte in der Reddung. Vorher blieb sie
  unerkannt.
- Ein nie im Forum angemeldeter FRS-Pilot ist kein Kandidat mehr und kann den Treffer eines
  anderen nicht mehr schlucken.
- **Unverändert:** Friese ist, wer mit FRS-Rufzeichen fliegt (Karte, Listen, Statistik, Bummel,
  Kutter). Unter fremdem Rufzeichen bleibt er auf der Karte grauer Fremdverkehr.

## 5. Umsetzung in drei Paketen

1. **Kniebrett-Seite:** Thesen 14, 16, 17 und die `e`-Anker aus 18. Nur ein Deploy, sofort wirksam.
2. **Server und neue MSFS-Brügge:** Thesen 1–12, dazu die `b`-Anker aus 18 (Angabe „bewährt“ im Strom).
   Server zuerst, dann die Brügge an einem eventfreien Tag, mit dem Satz auf der Download-Seite.
   Danach vier Wochen Übergang.
3. **Kniebrett-Paket:** These 15, zusammen mit Paket 2 in einem Zug an die Piloten.

Reihenfolge und Zeitpunkt entscheidet der Nutzer.

### Stand 26.09.2026
- **Paket 1 ist live** (15.21.1): Thesen 14, 16, 17, `e`-Anker aus 18; Tests
  `tests/test_kniebrett_zuordnung_regeln.py` (führt die echte Zuordnung in Node aus).
- **Paket 2, Server-Seite, ist live** (15.22.0): `app/bruegge_bindung.py`, Protokoll 3,
  Verwaltung (Hinweis, „vergessen“), `bw`/`cs` im Strom; Tests `tests/test_bruegge_bindung.py`
  und `tests/test_bruegge_protokoll3.py`. Plan: `docs/superpowers/plans/2026-09-26-bruegge-protokoll3-server.md`.
  X-Plane-Brügges laufen bereits über die neuen Regeln; die alte MSFS-Brügge über den alten Weg,
  **ohne Stichtag** (`_BRUEGGE_P2_MSFS_BIS = None`).
- **Offen:** MSFS-Brügge 1.18.0 und Kniebrett-Paket ohne Eigenfilter (Simulator-Rechner,
  `friesenbruegge/UEBERGABE-kennung-umsetzung.md`). Danach, auf Wort des Nutzers und an einem
  Tag ohne Event: Pakete hochladen, Satz auf die Download-Seite, Stichtag setzen, Handbuch zum
  Deinstallieren.
