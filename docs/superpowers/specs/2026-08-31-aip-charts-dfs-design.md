# AIP Charts DFS — eine Ansicht, keine Automatik

**Stand:** 31.08.2026
**Ersetzt:** [`2026-08-30-ground-chart-overlay-design.md`](2026-08-30-ground-chart-overlay-design.md)
und den Automatikteil von [`2026-08-23-aip-karten-overlay-design.md`](2026-08-23-aip-karten-overlay-design.md)

---

## 1. Was sich ändert und warum

Zwei Kartentypen, zwei Tabellen, zwei Oberflächen, zwei Automatiken — und beide Automatiken
haben ihren Zweck erfüllt und werden nicht mehr gebraucht. Entscheidung des Nutzers vom
31.08.2026:

> „Wir brauchen die Automatik nicht mehr. Sie war zur initialen Befüllung gut, aber jetzt
> braucht es sie nicht mehr. Wir behalten natürlich die Zuordnungen. […] Wir bauen die
> Automatik komplett zurück. Für alle Kartentypen! Wir belassen es bei einer einfachen
> Hash-Aktualitätsprüfung."

Der Grund liegt in den Daten: **Die Blätter ändern sich fast nie.** Die am 31.08.2026
durchgesehenen Flugplatzkarten tragen Ausgabedaten von 2014 bis 2026 — EDPC von 2014, EDPA
2018, EDSL 2021, EDRB und EDRG 2022, EDRJ 2023, EDRK und EDRT 2024. Beim einzigen bisherigen
Auffrischlauf waren **437 von 446 Blättern unverändert**. Eine Maschinerie, die jede Woche
Rahmen sucht, Ziffern liest und Bahnen vermisst, arbeitet also fast immer für nichts — und
wenn sie doch etwas findet, ist die Frage ohnehin eine, die nur ein Mensch beantworten kann:
*Stimmt die Passung auf dem neuen Blatt noch?*

### 1.1 Was bleibt

Die **Zuordnungen** — jede gesetzte Passung bleibt Zeile für Zeile erhalten. Der Rückbau
löscht Code, keine Daten.

---

## 2. Rückbau

| Datei | vorher | nachher | was fällt |
|---|---|---|---|
| `app/aip_charts.py` | 1621 | ~250 | Rahmenfindung, Tick-Messung, Ziffernschablonen, `passung_rechnen`, `ausgleichsgerade`, `ist_quer_gedruckt`, `geometrie_gleich`, `gerade_aus_bestand`, `zeigt_denselben_ausschnitt`, `blatt_auffrischen`, `genordet_rechnen`, `blatt_beschaffen` |
| `scripts/aip_bestand.py` | 347 | ~120 | die ganze Passungslogik; übrig bleibt der Hash-Vergleich |
| `app/ground_charts.py` | 238 | ~150 | nichts Neues — die Bahnvermessung ist bereits am 31.08. entfernt worden |
| `scripts/ground_chart_probe.py` | — | **gelöscht** | Beleg einer Messung, die nicht mehr gebraucht wird; die Zahlen stehen in der alten Spec |

**Was aus `aip_charts.py` bleibt:** `airac_url`, `airac_kennung`, `bild_aus_html`,
`kapitel_links`, `kapitelseiten`, `seiten_des_kapitels`, `blatt_schreiben`, `blatt_pfad`.
Also alles, was Blätter beschafft und ablegt — nichts, was sie deutet.

**`app/runway_ref.py` bleibt vollständig.** Nicht für eine Automatik: `meter_je_grad` und
`meter` trägt die Handpassung, und `bahnen()` liefert Schwellenkoordinaten, die beim Passen
als Vorschlag angezeigt werden können.

**Die Kopf-/Tonerkennung bleibt** (`bahnfarbe`, `sorte_aus_ton`) — nicht als Entscheidung,
sondern als Vorbelegung in der Seitenauswahl.

---

## 3. Eine Tabelle

```sql
CREATE TABLE IF NOT EXISTS aip_charts_dfs (
    icao          TEXT NOT NULL,
    sorte         TEXT NOT NULL,   -- 'sichtflug' | 'flugplatzkarte' | 'rollkarte'
    seite_url     TEXT NOT NULL DEFAULT '',
    quell_hash    TEXT NOT NULL DEFAULT '',   -- SHA-256 des ROHblatts; der Aenderungsdetektor
    bild_hash     TEXT NOT NULL DEFAULT '',   -- des abgelegten (ggf. gedrehten) Blatts
    nord          REAL NOT NULL DEFAULT 0,    -- Grenzen des abgelegten Blatts
    sued          REAL NOT NULL DEFAULT 0,
    west          REAL NOT NULL DEFAULT 0,
    ost           REAL NOT NULL DEFAULT 0,
    feld_nord     REAL NOT NULL DEFAULT 0,    -- Huelle der Passpunkte plus Saum:
    feld_sued     REAL NOT NULL DEFAULT 0,    -- danach schaltet die Automatik im Frontend
    feld_west     REAL NOT NULL DEFAULT 0,
    feld_ost      REAL NOT NULL DEFAULT 0,
    drehung       REAL NOT NULL DEFAULT 0,    -- Grad, im Uhrzeigersinn gegen Nord
    mps           REAL NOT NULL DEFAULT 0,    -- Meter je Pixel im Rohblatt
    p1_x          REAL, p1_y REAL, p1_lat REAL, p1_lon REAL,   -- die gesetzten Passpunkte,
    p2_x          REAL, p2_y REAL, p2_lat REAL, p2_lon REAL,   -- damit man sie nachjustieren kann
    status        TEXT NOT NULL,   -- siehe Abschnitt 4
    airac         TEXT NOT NULL DEFAULT '',
    geprueft_am   TEXT,
    PRIMARY KEY (icao, sorte)
);
```

**Der Primärschlüssel ist `(icao, sorte)`**, nicht `icao` allein: Ein Platz kann eine
Sichtflugkarte *und* eine Flugplatzkarte haben — bei EDDM sogar Flugplatz- und Rollkarte.
Heute liegen die in zwei Tabellen; zusammengelegt braucht es den zweiteiligen Schlüssel.

**Die Passpunkte werden gespeichert.** Heute geht nach einer Handpassung verloren, *worauf*
geklickt wurde — nur das Ergebnis bleibt. Wer nachjustieren will, fängt bei null an. Mit
`p1_*`/`p2_*` lädt die Maske die letzten Punkte vor.

### 3.1 Migration

Einmalig, in `init_db` neben den übrigen Migrationslisten:

* `aip_charts` → `sorte='sichtflug'`, `status` aus `quelle` (siehe 4.1)
* `aip_ground_charts` → `sorte` aus der bestehenden Spalte, `status` ebenso
* `rahmen_px`, `tick_px_lat`, `tick_px_lon`, `rest_max`, `bahnen` wandern **nicht** mit —
  sie waren Innereien der Automatik. Die alten Tabellen bleiben zunächst liegen, damit die
  Migration ohne Datenverlust wiederholbar ist.

`aip_chart_vorschlaege` wird **nicht** migriert und fällt ersatzlos weg (Abschnitt 7).

---

## 4. Status

| Status | Bedeutung |
|---|---|
| `gepasst` | Der Nutzer hat die Lage gesetzt oder bestätigt. Endgültig. |
| `auto` | Von der alten Automatik oder von Claude gesetzt — **vom Nutzer noch nicht angesehen**. |
| `offen` | Blatt liegt vor, keine Lage gesetzt. |
| `nicht_gefunden` | Kein passendes Blatt im Kapitel. |
| `prüfen` | Neues Blatt bei der DFS; die bestehende Passung ist noch nicht bestätigt. |

`auto` heißt **ungeprüft**, unabhängig davon, wer gerechnet hat. Es stirbt aus, sobald der
Nutzer eine Karte durchsieht, und entsteht neu nur, wenn er Claude eine Passung aufträgt.

### 4.1 Abbildung des Bestands

| bisher | wird |
|---|---|
| `aip_charts`, `quelle='hand'`, `status='gepasst'` (171) | `gepasst` |
| `aip_charts`, `quelle='auto'`, `status='gepasst'` (275) | `auto` |
| `aip_ground_charts`, `quelle='hand'`, `status='gepasst'` (68) | `auto` — von Claude gesetzt, nicht vom Nutzer geprüft |
| `aip_ground_charts`, `status='ungepasst'` (42) | `offen` |
| Plätze aus `airport_links` ohne Zeile | erscheinen als `nicht_gefunden` |

Die 68 Ground-Passungen fallen bewusst auf `auto` zurück. Sie sind am 31.08. von Claude
gesetzt worden; der Nutzer hat keine davon gesehen.

---

## 5. Die Passen-Maske

**Zwei Punkte, je Bildposition und Koordinate.** Zwei Rahmenecken sind zwei Punkte, und die
vier Gradwerte eines Kartenrahmens sind deren Koordinaten — links-oben ist (Nord, West),
rechts-unten ist (Süd, Ost). Es gibt keinen Grund, das als zwei Eingabearten zu bauen; eine
frühere Fassung dieses Entwurfs tat es und beschrieb damit dieselbe Rechnung zweimal.

```
Punkt 1:  Bild x [   ] y [   ]     Breite [  ]° [     ]'  N     Länge [  ]° [     ]'  E
Punkt 2:  Bild x [   ] y [   ]     Breite [  ]° [     ]'  N     Länge [  ]° [     ]'  E
Drehung:  [      ]°   (aus den Punkten vorbelegt, überschreibbar)
```

**Grad und Minuten bleiben getrennt.** Auf dem Blatt steht `N 47° 51,53'`; ein einzelnes
Feld „(Grad)" verleitet dazu, 47.5153 einzutragen — gemeint sind 47,859°. Der Unterschied
sind zwölf Kilometer. Genau so am 24.08.2026 passiert; der Hinweis steht bis heute als
Kommentar in `admin.html` und wird übernommen.

Der Hilfetext nennt beide Fälle: bei einem Blatt mit Gradnetz zwei gegenüberliegende
Rahmenecken, deren Werte am Rand stehen; bei einer Flugplatzkarte zwei Bahnschwellen oder
das ARP-Kreuz.

**Gerechnet wird auf dem Rohblatt**, ungedreht, so wie es abgelegt ist. Aus den zwei Punkten
folgen Drehung, Maßstab und Blattgrenzen (`ground_charts.handpassung`); erst danach wird
gedreht und abgelegt (`ground_charts.norden`). Die alte Sichtflugkarten-Rechnung
(`aip_charts.handpassung`) kannte keinen Rotationsfreiheitsgrad und entfällt — die sieben
quer gedruckten Blätter funktionierten dort nur, weil die Automatik sie vorher gedreht hatte.

**Die Drehung ist überschreibbar.** Bei zwei Punkten weit auseinander ist der abgeleitete
Wert gut; bei zwei nah beieinanderliegenden nicht. Ein Nachjustieren von Hand mit
Bildvorschau ist dann der schnellere Weg als neu zu klicken.

**Bei Status `prüfen`** zeigt die Maske das **neue** Blatt mit den **alten** Passpunkten
darauf. Damit ist auf einen Blick zu sehen, ob die Punkte noch dort liegen, wo sie sollen.
Drei Wege: übernehmen (Status → `gepasst`, `quell_hash` nachziehen), neu passen, oder das
neue Blatt verwerfen (alter Stand bleibt, Status → `gepasst`).

---

## 6. Liste, Filter, Seitenauswahl

**Die Liste zeigt alle 446 Plätze aus `airport_links`**, nicht nur die mit Fund. Ein Platz
ohne Blatt steht als `nicht_gefunden` drin und ist über die Seitenauswahl erreichbar —
ausdrücklicher Wunsch des Nutzers: „Vielleicht finde ich ja eine geeignete Karte, die du
nicht gefunden hast."

Spalten: ICAO, Sorte, Status, AIRAC, Drehung, Blattlink, Aktionen (passen, Seite wählen).

**Filter über Status, Mehrfachauswahl.** Vorgabe: alles außer `gepasst` — das ist die
Arbeitsliste. Zusätzlich ein Filter über die Sorte.

**Die Seitenauswahl** zeigt alle Kapitelseiten mit Vorschau. Beim Übernehmen wählt der
Nutzer die Sorte; die Tonerkennung (153/154 → Flugplatzkarte, 179/180 → Rollkarte, gemessen
über 30 Blätter ohne Überschneidung) belegt sie vor. Eine Seite darf jeder Sorte zugeordnet
werden — die Erkennung schlägt vor, sie entscheidet nicht.

**Die Spalte „passt" verschwindet.** `_aip_seiten_sammeln` (`app/main.py:4566`) ruft heute
für jede Kapitelseite `passung_rechnen` auf und zeigt an, ob die Automatik dort ein Gitternetz
findet. Mit dem Rückbau gibt es diese Auskunft nicht mehr. An ihre Stelle treten Angaben, die
ohne Deutung auskommen und in der Praxis mehr getragen haben: **Bildgröße, Dateigröße,
erkannter Bahnton und die daraus vorgeschlagene Sorte**. Die Vorschaubilder bleiben — sie sind
das, wonach ein Mensch die Seite ohnehin auswählt.

---

## 7. Der Job

Für jede Zeile mit gesetzter `seite_url`: Blatt holen, SHA-256 bilden, mit `quell_hash`
vergleichen. Weicht er ab → Status `prüfen`, neues Rohblatt als
`<ICAO>.<sorte>.neu.png` daneben legen, SSE-Meldung. **Sonst nichts.**

Kein Rechnen, keine Vorschlagstabelle, kein automatisches Schreiben. Damit kann der Job per
Bauart keine Passung beschädigen — die Sperre aus der Vorgängerspec wird überflüssig, weil
es keinen automatischen Schreibpfad mehr gibt.

Wöchentlich, über den bestehenden Fälligkeitsmerker in `job_laeufe` (`interval, weeks=1` mit
`next_run_time`, sonst läuft er nach jedem Deploy — belegt: der Vorgängerjob hat von seiner
Einführung bis zum 31.08.2026 kein einziges Mal gearbeitet).

**Kosten:** zwei HTTP-Abrufe je Karte, keine Bildanalyse. Bei rund 550 Zeilen etwa
1100 Abrufe je Lauf — dieselbe Größenordnung wie heute, aber ohne die Kapiteldurchläufe,
die den alten Lauf teuer machten.

---

## 8. Drei Fehler, die mitgehen

**Rohbild wird beim Passen nicht angezeigt.** `/aip-ground-chart/{icao}.png` ist vor
`/aip-ground-chart/{icao}.roh.png` registriert; FastAPI prüft in Reihenfolge, `{icao}`
schluckt den Punkt, die Anfrage nach `EDDL.roh.png` landet auf der ersten Route mit
`icao="EDDL.roh"`, scheitert an der Vierzeichenprüfung und liefert 404. Die zweite Route
wird nie erreicht. **Behebung:** eigener Pfad `/aip-chart-roh/{icao}/{sorte}.png`.

**Der Transparenzregler fehlt bei Flugplatzkarten.** `_aipDeckkraftAnzeigen()` schaltet ihn
über `_aipKarteAktiv` sichtbar; liegt eine Flugplatzkarte, ist der null. **Behebung:** an
„irgendeine Karte liegt" binden und `_aipDeckkraftSetzen` beide Overlays bedienen lassen.

**„Gültig · Vorschlag" zeigt zweimal dasselbe Bild.** Folgt aus dem Wegfall der
Vorschlagstabelle (Abschnitt 7) — es gibt nur noch ein neues Blatt und die bestehende
Passung darauf.

---

## 9. Vorgaben

* **Keine neue Abhängigkeit.** Pillow, httpx, airportsdata, APScheduler sind vorhanden.
* `init_db(db_path: str)` nimmt einen **Pfad**; `get_connection(db_path: str)` — es gibt
  kein `get_conn`; `settings.DB_PATH`.
* Es gibt kein `tests/conftest.py`. Fixtures je Testdatei, DB über `tmp_path`.
* `conn = get_connection(...)` / `try` / `finally: conn.close()`. `with conn` ist eine
  Transaktion, kein Close.
* Deutsche Bezeichner und Kommentare.
* **`"highlight": false`** in jedem Changelog-Eintrag.
* Kein `localStorage` im Frontend — `_prefLies` / `_prefSchreib`.
* Frontend-Tests binden an Deklarationen, nicht an Kommentare.
* Breite Tabellen brauchen `.table-wrap`; in `.scroll-list` zusätzlich eigene
  Höhenbegrenzung und sichtbare Scrollbar-Styles (beides zusammen, sonst unsichtbar).

---

## 10. Offene Risiken

1. **Die Migration ist einmalig und nicht trivial** — 446 + 110 Zeilen, zwei Quellen, ein
   zweiteiliger Schlüssel. Vorher wird die Produktionsdatenbank gesichert; die alten
   Tabellen bleiben stehen, bis der neue Stand geprüft ist.
2. **Der Rückbau entfernt rund 1600 Zeilen erprobten Code.** Was daran noch gebraucht wird,
   ist in Abschnitt 2 aufgezählt. Die Suche nach Aufrufern hat vier Stellen außerhalb der
   beiden Module gefunden, die alle mitgehen müssen:

   | Stelle | nutzt | Folge |
   |---|---|---|
   | `app/main.py:4566` | `passung_rechnen` | Spalte „passt" entfällt (Abschnitt 6) |
   | `app/main.py:4667` | `genordet_rechnen` | Seitenwähler dreht nicht mehr selbst; die Drehung kommt aus der Passung |
   | `scripts/aip_bestand.py` (4 Stellen) | `blatt_beschaffen`, `genordet_rechnen`, `geometrie_gleich` | fallen mit der Passungslogik weg |
   | `scripts/aip_handpassung.py` | nur im Kommentar | Skript prüfen und mit auf die neue Maske ziehen oder löschen |
3. **Die 42 offenen und die 336 als `nicht_gefunden` erscheinenden Plätze bleiben Arbeit.**
   Die Ansicht macht sie sichtbar und bearbeitbar; sie passt sie nicht.
