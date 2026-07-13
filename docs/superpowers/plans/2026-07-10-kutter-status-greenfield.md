# FriesenKutter: Statusführung auf der grünen Wiese — Brainstorming

> **Status: OFFENE ENTSCHEIDUNG — noch kein Implementierungsplan.** Dies ist eine Design-Notiz
> zum Nachdenken, kein Task-by-Task-Plan. Bevor irgendetwas umgesetzt wird, wird daraus ein
> eigener Spec + Plan abgeleitet und freigegeben.

**Kernfrage:** Können wir die Kutter-Statusführung radikal vereinfachen, indem wir den permanenten
Ankunfts-Latch ganz abschaffen — statt ihn weiter zu flicken?

## Warum überhaupt (das Problem)

Die heutige Statusführung ruht auf einem **dauerhaften Ankunfts-Latch** (`transport_live_arrivals`,
eingeführt in `2026-07-01-kutter-live-ankunft.md`). Dieser Merker wird für *jeden* am Boden im
Zielradius stehenden FRS-Piloten gesetzt (`check_live_arrival`) und danach benutzt, um den
**Live-Status** („angekommen") zu bestimmen. Das ist der Wurzel-Missgriff: ein *permanenter*
Merker („war mal am Ziel") steuert einen *aktuellen* Zustand („ist gerade angekommen").

Symptom dieser Verquickung: Der Latch wurde bis Juli 2026 mehrfach nachgebessert —
#6/v8.19.0 (Latch ans liefernde Leg binden), #22 (Refile-Split-Key), #62/#65/#66 (Rückflug/dep),
v8.25.0 (FRS102 Luft-Phase), v8.25.1 (A3 Boden-Phase). Wenn eine Mechanik so oft geflickt wird,
ist meist die Mechanik das Problem, nicht der jeweilige Flicken.

Belegte Fehlerklassen (s. Zustandsanalyse vom 10.07.):
- **A3** (v8.25.1 chirurgisch gefixt): am Abholplatz geparkter Pilot mit altem Latch → falsches
  „angekommen" + Phantom-Fracht.
- **Z1**: Anwesenheits-Latch feuert für jeden am Ziel Geparkten, auch Nie-Lieferer.
- **A11** (offen): Verlust + Lieferung gleichzeitig bei Reconnect > 30 min.
- **A8** (bewusst offen): spuriser Latch + fehlgeschlagene Leg-Schließung → kurz „unterwegs"
  statt „angekommen".

## Die Idee (grüne Wiese)

**Eine einzige Wahrheit für die Zählung:** Eine Lieferung = ein geflogenes GPS-Bein, das an einem
Abholplatz startet (`dep ∈ route, ≠ Ziel`) und am Ziel landet (`gps_arrival == Ziel`). Menge =
Zuladung des Musters. Das steht bereits vollständig im GPS-Track — **kein Latch, kein `arrived_at`,
keine Demotion** nötig, um zu zählen.

**Live-Status = nur die aktuelle Position, drei Fälle:**

| Wo der Pilot GERADE ist | Status |
|---|---|
| am Boden an einem Abholplatz | 🅿️ lädt |
| in der Luft, zuletzt von einem Abholplatz gestartet | ✈️ unterwegs (reserviert Zuladung) |
| alles andere (am Ziel, wegfliegend, fremder Platz) | nicht in der Live-Liste |

## Was dadurch wegfällt

- **„angekommen" als Live-Zustand** — ersatzlos. Ankunft ist eine gezählte Tatsache im Balken,
  kein Pilotenstatus, der hängenbleiben kann. (Im sauberen Pfad ist er ohnehin ~0 s sichtbar,
  weil das Leg im selben gs<2-Sample schließt.)
- **„↩️ Rückflug" als eigener Status** — wer vom Ziel wegfliegt, liefert gerade nicht → unsichtbar.
- **Der gesamte Latch-Apparat** (`transport_live_arrivals`, `check_live_arrival`,
  `_latch_hits_flight`, die Demotion in `compute_transport_progress`). Damit by-design gelöst:
  A3, Z1, A8, die „echter-Anflug"-Frage.

Netto: **Code wird entfernt, nicht hinzugefügt.**

## Der eine echte Knackpunkt

Wozu war der Latch da? Für **löchrige GPS-Tracks / kein Disconnect** — wenn die Ankunft am Ziel
nicht sauber als GPS-Bein erkannt wird. Ohne Dauer-Merker sauber lösbar: **beim Verbindungsende
einmal abrechnen** — stand der Pilot zuletzt am Ziel und kam er von einem Abholplatz? Dann zählt
die Lieferung. Einmalige Abrechnung, kein permanentes Flag, das den Live-Status vergiften kann.
(Das ist strukturell dasselbe wie die heutige Verlust-Erkennung `detect_transport_losses`, nur mit
umgekehrtem Vorzeichen — „am Ziel gelandet" statt „woanders geendet".)

## Was NICHT angefasst wird (berechtigte Domänen-Komplexität)

- Mehrere Abholplätze, Fracht/Ziel je Startplatz (#15).
- Zuladung je Muster (kuratierter Datensatz, v8.17.0).
- Verluste: versunken / geklaut / zurückgebracht (bleibt inhaltlich unverändert — Entscheidung
  vom 10.07.: „zurückgebracht" ist fair, nicht umdeuten).
- GPS-only-Wahrheit (#23): Ankunft aus dem Track, nicht aus dem Flugplan. Der Flugplan bleibt für
  das **Muster** (= Frachtmenge) nötig.

## Offene Fragen fürs spätere Brainstorming

1. Genügt „Verbindungsende-Abrechnung" wirklich für alle Track-Lücken, oder braucht es einen
   leichten Live-Vorgriff (ohne Dauer-Merker)? Wie sichtbar soll „gerade geliefert" live sein?
2. Sollen reservierte In-Air-Mengen bei Event-Ende als „nicht geliefert" statt „offen" erscheinen?
   (Getrennt vom Latch-Thema, s. Bilanz-Frage 10.07.)
3. Migration: Bestandsdaten haben `transport_live_arrivals`-Einträge. Beim Umbau ignorierbar
   (nur GPS-Bein zählt) oder einmalig abzugleichen?
4. Test-Strategie: Die bestehende Zustandstabelle (Artifact 10.07.) als Abnahme-Matrix gegen den
   neuen Kern durchspielen — jede heutige ✅-Zeile muss gleich oder besser rauskommen.

## Bezugspunkte

- Aktuelle Mechanik: `app/database.py` — `compute_transport_progress`, `check_live_arrival`,
  `_latch_hits_flight`, `detect_transport_losses`; `app/gps_legs.py` (Leg-Erkennung);
  `app/static/index.html` — `fetchKutterActive`, `_kutterDetailBody`.
- Ursprung des Latch: `docs/superpowers/plans/2026-07-01-kutter-live-ankunft.md` (diese Notiz
  schlägt vor, dessen Kernmechanik zu ersetzen).
- Zustandsanalyse + Fehlerklassen: Chat-Sitzung 10.07.2026 (Artifact „FriesenKutter — Statusführung").
