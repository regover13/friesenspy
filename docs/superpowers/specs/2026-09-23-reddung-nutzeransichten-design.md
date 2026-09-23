# 🚨 FriesenReddung — die Nutzeransichten (23.09.2026)

Zweite Runde zum Eventtyp. Die erste
(`2026-09-20-friesenreddung-design.md`) hat Server, Poller, Wertung und Admin gebaut; sie
endet mit dem Satz *„Karte, Kniebrett, Badge und Forumsbeitrag kommen danach und werden vorher
eigens besprochen"*. Das hier ist das Danach — **ohne Badge und ohne Forumsbeitrag**.

Der Eventtyp ist heute für Piloten fast unsichtbar: Es gibt den Hinweiskasten „dir fehlt die
FriesenBrügge" und eine Zeile in der Eventliste. Wer an einem Abend sucht, sieht nicht, welche
Fläche schon abgesucht ist; wer nicht dabei war, erfährt nie, wie der Abend ausging.

**Vier Ansichten, eine Runde:** Kartenansicht, Live-Ansicht, Bilanz unter Events, Kennzahlen in
den Statistiken.

**Fassung 15.18.0.** Nutzerentscheidung vom 23.09.2026: Die Hauptnummer bleibt frei — sie gehört
an Badge und Forumsbeitrag, mit denen der Eventtyp wirklich fertig ist.

**Das Kniebrett ist dabei, ohne eigene Arbeit.** `app/static/index.html` ist Website *und*
EFB-Panel (`_PANEL_MODUS`). Was in die Kartenansicht kommt, liegt damit im Cockpit. Die erste
Spec führte Karte und Kniebrett als zwei Runden; das sind in Wahrheit anderthalb.

---

## 1. Die vier Entscheidungen dieser Runde

Alle vier vom Nutzer am 23.09.2026 getroffen, mit den verworfenen Alternativen daneben — damit
keine davon zurückkommt.

| Frage | Entscheidung | Verworfen, und warum |
|---|---|---|
| Was zeigt die Karte im laufenden Abend? | **Sektorrahmen plus Raster: abgesucht oder offen** | *Nur Rahmen und Prozentbalken* — nimmt dem Abend das taktische Element, das #21 gerade ausmacht. *Raster mit „wer hat was"* — mehr Daten je Takt, schwierige Farbgebung, und der eigene Beitrag steht in der Bilanz. |
| Zeigt die Karte die Unglücksstelle nach der Auflösung? | **Ja, der genaue Punkt** | *Nur die Rasterzelle* — bis zu einem Kilometer Unschärfe macht die Nachbesprechung ungenau. *Gar nicht* — wer an dem Abend nicht geflogen ist, erführe nie, wo der Havarist lag. |
| Wie weit geht die Bilanz? | **Panel mit Teilen-Text** | *Zusätzlich Badge-Bilder* — eigene Runde, siehe Abschnitt 8. *Nur das Panel* — dann tippt die Nachbesprechung jemand von Hand. |
| Welche Kennzahlen? | **Kachelzeile im Schnitt von Kutter und Bummel** | *Zusätzlich eine Finder-Rangliste* — eine Darstellung, die es bei den anderen Eventtypen nicht gibt; erst einführen, wenn sie dort auch gewollt ist. *Nur Grundzahlen* — Fläche und Rettungsdauer sind gerade das Eigene dieses Eventtyps. |

---

## 2. Die Verdeckung wird umformuliert, nicht aufgegeben

Heute gilt: `compute_reddung_stand` **gibt nie eine Koordinate heraus**, und
`tests/test_reddung_db.py` hält es fest. Die Karte stellt diese Zusage neu, denn nach
`aufgeloest_am` ist die Lage ohnehin öffentlich — im Simulator steht dort bis `dtend` die rote
Fackel, sichtbar für jeden, der hinfliegt.

**Neue Fassung der Zusage:**

> Die Lage des Havaristen verlässt den Server in Richtung Browser **ausschließlich über
> `GET /api/reddung/events/{id}/raster`, und dort erst, wenn `aufgeloest_am` gesetzt ist.**

⚠ **`compute_reddung_stand` bleibt unangetastet koordinatenfrei.** Der vorhandene Test gilt
unverändert weiter, und `/api/reddung/events` (die Liste, die die Eventliste füllt) gibt die
Koordinate auch **nach** der Auflösung nicht heraus. Die Freigabe geschieht in einer eigenen
kleinen Funktion im neuen Endpunkt:

```python
def _havarist_freigabe(ev: dict) -> dict | None:
    """Die Lage — aber nur nach der Auflösung. Die EINZIGE Stelle, die sie herausgibt."""
    if not ev.get("aufgeloest_am"):
        return None
    if ev.get("havarist_lat") is None or ev.get("havarist_lon") is None:
        return None
    return {"lat": ev["havarist_lat"], "lon": ev["havarist_lon"],
            "fund_radius_m": rd.fund_radius_m(ev)}
```

Der Grund für die eigene Funktion ist derselbe wie in der ersten Spec: **Die Zusicherung soll
eine Eigenschaft des Aufbaus sein, keine Frage der Sorgfalt.** Es gibt genau eine Stelle zu
prüfen, und sie hat einen Test in beide Richtungen.

⚠ **Kein Eintrag in `BEWUSST_OFFEN`.** Der Endpunkt liegt wie die Eventliste hinter dem
Login-Gate (`tests/test_api_schutz.py`, Stufe 1) — er ist damit ohne weiteres Zutun nur für
angemeldete Friesen erreichbar. Wer ihn je gate-frei stellt, muss dort eine Zeile schreiben und
diese Spec widerlegen.

---

## 3. Der Raster-Endpunkt

```
GET /api/reddung/events/{id}/raster
```

```json
{
  "id": 3,
  "name": "Vermisst über der Jade",
  "dtstart": "2026-09-23T17:00:00Z",
  "dtend": "2026-09-23T20:00:00Z",
  "sektor": {"sued": 53.5, "west": 7.8, "nord": 53.86, "ost": 8.4},
  "raster": {"zeilen": 40, "spalten": 40, "d_lat": 0.00900, "d_lon": 0.01514},
  "zellen": 1600,
  "abgedeckt": ["z0_0", "z0_1", "z1_0"],
  "anteil": 0.42,
  "aufgeloest": false,
  "havarist": null
}
```

**Die Karte rechnet die Geometrie nicht nach.** Mit `d_lat` und `d_lon` ist jede Zelle eine
Multiplikation: Südkante `sued + i · d_lat`, Westkante `west + j · d_lon`. Der Schlüssel
`z{i}_{j}` ist derselbe, den `zellen_aus_box` vergibt — Zeile und Spalte stehen also schon drin.

⚠ **Die Maße kommen aus EINER Funktion.** `app/abdeckung.py` bekommt

```python
def raster_masse(sued, west, nord, ost, kante_km) -> tuple[int, int, float, float]:
    """Zeilen, Spalten und Zellgröße in Grad — die Geometrie des Sektorrasters."""
```

und `zellen_aus_box` benutzt sie selbst. Sonst gäbe es zwei Rechnungen für dasselbe Raster, und
die zweite wäre irgendwann still falsch. Das Aufrunden der Zellenzahl und das Tauschen
verdrehter Ecken wandert mit dorthin.

**Die abgedeckten Schlüssel kommen aus der Fortschreibung.** `reddung_fortschreiben` hält sie
ohnehin im Snapshot (`treffer`), gibt sie heute aber nicht zurück. Die Rückgabe bekommt einen
Schlüssel dazu:

```python
"zellen_abgedeckt": sorted(treffer),   # nur Schlüssel, nie Koordinaten
```

⚠ **Der Name ist absichtlich ein anderer als im Endpunkt.** In `reddung_fortschreiben` ist
`abgedeckt` bereits vergeben — als **Anzahl** (`len(treffer)`). Die Liste heißt dort deshalb
`zellen_abgedeckt`; der Endpunkt reicht sie als `abgedeckt` heraus, weil dort keine Zahl
gleichen Namens steht. Wer die beiden verwechselt, bekommt eine Zahl, wo die Karte eine Liste
erwartet.

Den Snapshot im Endpunkt ein zweites Mal zu lesen wäre die Alternative gewesen — verworfen, weil
dann zwei Stellen wüssten, wie ein Snapshot innen aussieht.

**Unbekannte `id` ergibt 404**, wie bei `/api/transport/event/{event_id}`. Eine leere Antwort
mit 200 wäre für die Karte nicht von „Sektor noch unberührt" zu unterscheiden.

**Der Endpunkt schreibt fort wie die Liste** (`compute_reddung_stand` ruft dasselbe) und
committet danach — das Fortschreiben ergänzt den Snapshot.

**Datenmenge.** Bei vollständig abgesuchtem 40 × 40-km-Sektor mit Kilometer-Kante sind das 1.600
Schlüssel, rund 16 kB JSON. Das ist der ungünstigste Fall und wird alle 30 s geholt; eine
kompaktere Kodierung (Bitfeld, Lauflängen) wäre vorzeitige Optimierung und würde den Endpunkt
unlesbar machen.

---

## 4. Kartenansicht

**Eine Ebene „FriesenReddung"**, eingehängt über `_liveEbenenControl.addOverlay(...)` — also
nachträglich, nicht beim Kartenaufbau. Grund: Sie soll **nur da sein, wenn es etwas zu zeigen
gibt** (eine Reddung läuft, oder eine ist heute abgelaufen). Ein dauerhaft sichtbarer Haken, der
meistens nichts tut, ist genau das, was Kompassnadel und Folgen-Pfeil im Projekt schon bewusst
vermeiden. Gibt es nichts, wird die Ebene wieder entfernt.

**Gezeichnet wird:**

* der **Sektorrahmen** als gestricheltes Rechteck — die Grenze der Aufgabe,
* die **abgesuchten Zellen** gefüllt, ohne eigenen Rand,
* nach der Auflösung: die **Unglücksstelle** als Marke, dazu ein Kreis mit `fund_radius_m`.

**Nur die abgesuchten Zellen, nicht die offenen.** Das liest sich richtig herum („was gefüllt
ist, hat jemand angesehen"), hält die Zeichenlast am Anfang des Abends klein — wenn ohnehin fast
alles offen ist — und spart die Frage, wie man 1.600 leere Rechtecke unaufdringlich zeichnet.
Ohne Rand verschmelzen benachbarte Zellen optisch zu einer Fläche; genau das ist die Aussage
(„dieser Streifen ist abgesucht"), und ein Gitternetz aus 1.600 Linienzügen wäre sowohl teurer
als auch unruhiger.

⚠ **Eigener Canvas-Renderer für diese Ebene** (`L.canvas()`), sonst legt Leaflet je Zelle ein
SVG-Element an. Bei 1.600 Rechtecken ist das der Unterschied zwischen einer ruhigen und einer
stockenden Karte — auf dem Cockpit-Tablet zuerst.

**Nachgeladen alle 30 s**, solange die Ebene an ist und eine Reddung läuft. Der Takt folgt dem
Poller: Die Einlieferung wird dort seit dem 20.09.2026 im 30-s-Takt geprüft, und die Abdeckung
ändert sich in Sekunden nicht sichtbar. Ist die Reddung abgelaufen, wird einmal geladen und
nicht mehr nachgefragt.

**Mehrere gleichzeitig laufende Reddungen** werden alle gezeichnet — wie der Live-Block sie
stapelt. Das Datenmodell lässt sie zu, also darf die Karte nicht die erste beste wählen.

**Sprung auf den Sektor:** Live-Block und Bilanz-Panel bekommen einen Knopf, der in die
Kartenansicht wechselt und `fitBounds` auf den Sektor setzt — nach dem Muster von
`switchToMapAndCenter`.

---

## 5. Live-Ansicht

Ein Block `#reddung-banner` im LIVE-Tab, **über** dem Bummel- und dem Kutter-Banner: Eine
laufende FriesenReddung ist die Lage mit der Uhr im Nacken.

Inhalt, nach dem Muster von `_kutterBannerBlock`:

* Name und „läuft gerade",
* der Gruppenbalken mit dem abgesuchten Anteil,
* wie viel Fläche noch offen ist,
* die erreichten Marken mit Namen und Zeit — gefunden, aufgenommen, eingeliefert,
* ein Knopf zur Karte.

**Nichts davon sagt etwas über die Lage.** Der Block liest ausschließlich
`/api/reddung/events` — die Liste, die die Koordinate nie führt. Ein eigener Endpunkt für den
Live-Block ist nicht nötig; `fetchKutterActive` macht es mit den Kutter-Events genauso.

**Der Hinweiskasten „dir fehlt die FriesenBrügge" bleibt, wo er ist.** Er hängt absichtlich
außerhalb der Tabs und ist auf jeder Ansicht sichtbar — ihn in den Live-Block zu ziehen hieße,
ihn nur dort zu zeigen, wo ohnehin jemand hinsieht. Er ist die einzige Stelle, an der ein Pilot
vor dem Flug erfährt, dass er sonst einen leeren Sektor absucht.

---

## 6. Bilanz unter Events

Ein Panel `#reddung-results` neben `#bummel-results` und `#kutter-results`, mit dem Teilen-Knopf
rechts oben in der Titelzeile — dieselbe Machart, damit die drei Eventtypen sich nicht ohne
Grund unterscheiden.

Inhalt:

* Gruppenbalken mit Anteil, Zellenzahl und abgesuchter Fläche in km²,
* die Marken: gefunden von wem und wann, aufgenommen von wem, eingeliefert wo und wann,
* die Rettungsdauer (`dauer_min`, Fund bis Einlieferung),
* Tabelle **Beitrag je Pilot** — die Zellen, die jeder als erster abgesucht hat, mit Anteil,
* wurde nicht gefunden: dieser Satz, mit der erreichten Abdeckung,
* ein Knopf zur Karte.

**Das behebt nebenbei einen echten Fehler.** Heute fällt ein Klick auf die Reddung-Zeile in der
Eventliste durch bis `_prefillEventForm` und füllt das Suchformular der Event-Analyse — es
passiert also etwas Unverständliches statt etwas Nützliches. Die Zeile bekommt denselben Zweig,
den Bummel und Kutter längst haben.

**Der Teilen-Text** (`copyReddungShareHeader`, Vorbild `copyKutterShareHeader`) legt einen
forumsfertigen Absatz in die Zwischenablage: Name, Abdeckung, die Marken mit Namen und Zeiten,
die Rettungsdauer und die Beiträge. Wo der Havarist lag, steht **nicht** darin — das ist eine
Karte, kein Satz.

---

## 7. Kennzahlen in den Statistiken

`aggregate_reddung_kpis(staende)` neben `aggregate_bummel_kpis` und `aggregate_kutter_kpis` in
`app/database.py` — rein, ohne Datenbankzugriff, nach demselben Muster:

| Schlüssel | Bedeutung |
|---|---|
| `event_count` | abgeschlossene Reddungen im Zeitraum |
| `participations` | Σ Einträge in `je_pilot` — siehe Warnung darunter |
| `gefunden_count` | wie oft der Havarist gefunden wurde |
| `flaeche_km2` | Σ abgedeckte Zellen × Kante², gerundet |
| `avg_rettung_min` | Mittel über `dauer_min`, nur über Abende mit Einlieferung |

`/api/stats/special-events` bekommt `reddung` als dritten Schlüssel, die Oberfläche eine
Kachelzeile über `_kpiCard`: FriesenReddung · Teilnahmen · Gefunden (als Anteil) · Abgesucht ·
Ø Rettung. Sie erscheint nur, wenn `event_count > 0` — wie die beiden anderen Zeilen auch.

⚠ **`participations` zählt JEDEN, der im Sektor gemessen wurde — auch mit null Zellen.**
`reddung_fortschreiben` legt für jeden Piloten mit Punkten einen Eintrag an
(`je_pilot.setdefault(cid, 0)`), auch wenn jede seiner Zellen schon einem anderen gehörte. Das
ist die richtige Zählung für „Teilnahmen": Wer eine Fläche abgeflogen hat, war dabei — dass ein
anderer dort zuerst war, ist Doppelarbeit und kein Grund, ihn aus der Statistik zu streichen.
Wer stattdessen nur Einträge mit `zellen > 0` zählt, misst etwas anderes und muss es anders
nennen.

**Abgeschlossen heißt `dtend` vorbei**, nicht `aufgeloest_am` gesetzt. Bei
`aufnehmen_noetig = 0` löst schon der Fund die Lage auf, während der Abend weiterläuft; wer auf
`aufgeloest_am` filtert, zählt solche Abende zu früh und bekommt eine Abdeckung, die noch wächst.

⚠ **Nichts wird nachgerechnet.** Die Kennzahlen kommen aus den fortgeschriebenen Snapshots. Bei
einem abgeschlossenen Event ist `alt["bis"] == dtend`, und `reddung_fortschreiben` läuft nicht
erneut an — das ist auch die einzige Fassung, die trägt: `bruegge_spur` wird nach zwölf Stunden
aufgeräumt, eine Neuberechnung fände nur noch VATSIM-Punkte vor, verwürfe sie mangels Meldung
und setzte die abgesuchte Fläche eines verkündeten Abends auf null (Nachtrag 3 der ersten Spec).
**`_REDDUNG_STAND_FASSUNG` wird in dieser Runde nicht erhöht** — die Rechnung ändert sich nicht.

---

## 8. Was diese Runde NICHT enthält

* **Badge-Bilder.** Eigene Runde, zusammen mit dem Forumsbeitrag; dort gehört auch die Frage
  hin, was ein Pilot bekommt, der nur Fläche abgeflogen hat.
* **„Wer hat welche Zelle" auf der Karte.** Verworfen (Abschnitt 1); der eigene Beitrag steht
  in der Bilanz.
* **Eine Finder-Rangliste über die Saison.** Verworfen, solange Bummel und Kutter keine haben.
* **Mehrere Havaristen je Event.** Steht seit der ersten Spec offen (#21, Frage 4) und berührt
  das Datenmodell, nicht die Ansichten.
* **Ein Kartenraster im Admin.** Der Admin setzt den Sektor mit zwei Ecken; die abgesuchte
  Fläche sieht er über dieselbe Nutzeransicht wie alle anderen.

---

## 9. Tests

Neu, jeder an Bezeichnern verankert statt an Kommentartexten:

1. **`tests/test_reddung_raster_api.py`**
   * Struktur der Antwort; `zellen == zeilen · spalten`.
   * Die Schlüssel in `abgedeckt` sind eine Teilmenge der Schlüssel aus `zellen_aus_box` —
     das bindet Endpunkt und Rechenkern aneinander.
   * `raster_masse` und `zellen_aus_box` liefern dieselbe Geometrie (der Mittelpunkt von
     `z{i}_{j}` liegt in der Zelle, die `d_lat`/`d_lon` aufspannen).
   * **`havarist` ist `None`, solange `aufgeloest_am` leer ist** — und gesetzt, sobald es steht.
     Beide Richtungen, das ist der Kern der Verdeckung.
   * `/api/reddung/events` führt die Koordinate auch **nach** der Auflösung nicht.
2. **`tests/test_reddung_kpi.py`** — reines Aggregat ohne Datenbank: leere Liste, Abend ohne
   Fund, Abend mit Einlieferung, und dass `avg_rettung_min` Abende ohne Einlieferung auslässt.
3. **Quelltexttests der Oberfläche** (Muster `tests/test_events_liste.py`,
   `tests/test_kutter_balken.py`): `#reddung-banner` und `#reddung-results` sind vorhanden,
   der Klick in der Eventliste ruft `openReddungDetail`, die Kartenebene bekommt einen eigenen
   Renderer, und der Teilen-Text enthält keine Koordinatenfelder.

Die Testsuite läuft in `/home/claude/.venv-friesenspy`.

---

## 10. Doku und Fassung

* **README** — ein Absatz im Handbuchteil: was ein Pilot auf Karte, Live-Ansicht und in der
  Bilanz sieht. Nicht, woher die Zahlen kommen; das steht in `docs/`.
* **Hilfetext hinter dem `?`** — zur Kartenebene und zum Live-Block, im selben Commit wie die
  Sache selbst.
* **Karten-Legende** — ein Eintrag für die Reddung-Ebene, im Abschnitt „Bedienelemente" bei den
  übrigen Zusatzebenen.
* **`app/CHANGELOG.json`** — ein Eintrag für **15.18.0**, `"highlight": false`.
* **`docs/architecture.md`** — der neue Endpunkt in der Endpunktliste.

## 11. Reihenfolge der Umsetzung

1. `raster_masse` in `app/abdeckung.py`, `zellen_aus_box` darauf umgestellt.
2. `zellen_abgedeckt` in der Rückgabe von `reddung_fortschreiben`.
3. Der Raster-Endpunkt samt `_havarist_freigabe` und seinen Tests.
4. Kartenebene (der größte und riskanteste Brocken — deshalb vor den einfachen Ansichten).
5. Live-Block.
6. Bilanz-Panel samt Teilen-Text und dem Klick aus der Eventliste.
7. Kennzahlen.
8. README, Hilfetexte, Legende, Changelog, `docs/architecture.md`.

Die Schritte 1 bis 3 tragen alles Weitere; 4 bis 7 sind untereinander unabhängig und je für
sich lauffähig.
