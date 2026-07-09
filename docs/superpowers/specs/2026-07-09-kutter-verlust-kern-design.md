# Design — Paket B: FriesenKutter-Verlust-Kern (#6/#7/#8)

Datum: 2026-07-09
Scope: die drei zusammenhängenden Verlust-Bugs des FriesenKutter. Tiefe Ist-Analyse +
Ansatz-Abwägung stehen im Entwurf
`D:\User\Tobias\OneDrive\Claude\FriesenSpy\docs\superpowers\specs\2026-07-09-kutter-verlust-DRAFT-ansaetze.md`
— diese Spec fixiert die **entschiedene** Umsetzung. Alle Pfade absolut; Zeilen driften, vor
Umsetzung per Grep verifizieren.

## Entscheidungen (vom Nutzer abgenommen, 2026-07-09)

| Frage | Entscheidung |
|---|---|
| #6 Latch-Fix | **Ansatz C** — Latch über die gespeicherte `arrived_at`-Zeit ans Leg binden (rückwirkend, keine Migration) |
| #7 Verlustmenge | **Chronologisch-netto** — Verlust füllt netto gegen denselben Pool wie Lieferungen (kein Persist-Snapshot, konsistent mit #63) |
| #8 | Verlorene Ware (stolen/sunk) **dauerhaft aus dem ladbaren Pool** entfernen |
| Fortschritt/Abschluss | **Target bleibt Maßstab** — `progress_pct`/`goal_reached_at`-Semantik UNVERÄNDERT; verlustbehaftete Events bleiben sichtbar <100 % und schließen normal zum `dtend` ab |
| Q6 | `lost_kg` je Frachtart in `cargo_out` ergänzen (zeigt, warum <100 %) |
| Q7 | Eingefrorene Alt-Snapshots NICHT automatisch neu rechnen (kein Backfill; #6-Fix wirkt ohnehin rückwirkend auf noch nicht eingefrorene Events) |

`returned` ist von #7/#8 ausgenommen (Ware kam heil zurück, kein Pool-Verbrauch, `lost=0`).

## Reihenfolge

1. **#6 zuerst** (eigener Datenpfad, unabhängig; ohne ihn bleiben Verluste unsichtbar und #7/#8
   nicht an Live-Daten verifizierbar). Einzeln deploybar.
2. **#7 + #8 gemeinsam** (ein Umbau an `compute_transport_progress`; #8 braucht das `lost[i]`-Array
   aus #7).

---

## Teil 1 — #6: Latch über `arrived_at` ans Leg binden

**Kern:** `transport_live_arrivals.arrived_at` (existiert, `database.py:222-228`) ist der
Live-Zeitpunkt der Ankunftserkennung — praktisch der Touchdown des LIEFERNDEN Legs. Der Latch wird
an genau das Leg gebunden, in dessen `[takeoff_ts, landing_ts]`-Fenster `arrived_at` liegt, statt
ans ganze Verbindungsintervall.

### B1 — `get_transport_live_arrivals` gibt `arrived_at` mit zurück

Datei: `D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\database.py:4782-4787`

- Query zusätzlich `arrived_at` selektieren; Rückgabe von `set[(cid, logon_time)]` →
  `dict[(cid, logon_time), arrived_at]`.
- **Kompatibilität:** Alle Aufrufer, die nur Membership testen (`(cid, lo) in live_arrivals`),
  funktionieren unverändert weiter (dict-Key-Membership). Aufrufer prüfen/anpassen:
  - `compute_transport_progress:5156` (`live_arrivals = get_transport_live_arrivals(...)`),
    Nutzung an `:5284` (`(cid, lo) in live_arrivals`) — Membership, bleibt.
  - `detect_transport_losses:4878` (`latched = get_transport_live_arrivals(...)`), Nutzung via
    `_latch_hits_flight` — bekommt jetzt das dict.
  - `compute_transport_progress:5177` (`_latch_hits_flight(conn, live_arrivals, ...)`) — dito.
  - Ein etwaiger dritter Aufrufer in `transport_anyone_in_progress`/`:5064` — per Grep
    `get_transport_live_arrivals(` prüfen; falls Membership-only, bleibt er unverändert.

### B2 — `_latch_hits_flight` bindet an das Leg statt an die Connection

Datei: `D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\database.py:4810-4835`

Neue Signatur nimmt das dict (`latches: dict[tuple[int, str], str]`). Match-Logik ersetzen:

- **Vorfilter (Connection-Scoping behalten):** `c == cid and lo <= takeoff_ts` — verhindert
  Zuordnung eines Latches einer anderen/späteren Connection.
- **Positiver Match (NEU, gegen `arrived_at` statt Connection-Logoff):**
  `takeoff_ts <= arrived_at and (landing_ts is None or arrived_at <= landing_ts)`.
- Die interne `SELECT logoff_time FROM flights ...`-Nachschau **entfällt** (kein Connection-Lookup
  mehr nötig).

Damit matcht ein Latch nur noch das Leg, dessen Lebensfenster den Ankunftszeitpunkt enthält. Ein
Folge-Leg mit `takeoff_ts > arrived_at` matcht NICHT mehr → in der Anzeige korrekt „unterwegs"
statt „geliefert", und `detect_transport_losses` überspringt es nicht mehr → echter Verlust wird
erkannt. Wirkt rückwirkend (arrived_at war immer gespeichert), sobald der nächste Poll läuft.

**Randfall (Entwurf offene Frage 1):** minimaler Poll-Takt-Versatz zwischen `check_live_arrival`s
Boden+Radius-Kriterium (`database.py:5010-5021`) und dem GPS-Touchdown des Legs. In der Praxis
gleicher oder Nachbar-Takt; `arrived_at` liegt am Ende des liefernden Legs, sein `landing_ts` ist
gesetzt → `arrived_at <= landing_ts` gilt. An einem Live-Fall verifizieren.

### B3 — Tests #6

Datei: `D:\User\Tobias\OneDrive\Claude\FriesenSpy\tests\test_database.py` (bestehende
Kutter-Testklasse erweitern) und/oder `tests/test_poller.py`.

- **Regressionsschutz — der eigentliche Bug:** Eine Verbindung mit ZWEI Legs auf demselben
  `logon_time`: Leg 1 liefert am Ziel (arrived_at im Leg-1-Fenster), Leg 2 startet DANACH
  (`takeoff_ts > arrived_at`) Richtung streckenfremd + disconnectet dort.
  - `compute_transport_progress`: Leg 2 ist NICHT `loaded`, erscheint als offen/`in_air` bzw. wird
    von `detect_transport_losses` als Verlust erkannt (vorher: unsichtbar / kein Verlust).
- **Positiv-Fall bleibt grün:** Ein einzelnes Liefer-Leg mit `arrived_at` im eigenen Fenster wird
  weiterhin als `loaded` erkannt.
- **Trackless Fallback:** Leg == Connection (arrived_at im Connection-Fenster) → unverändert
  `loaded`.

---

## Teil 2 — #7 + #8: Verlust netto in den Pool einreihen

Heute drei isolierte Verteil-Durchläufe in `compute_transport_progress`
(`D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\database.py`): Delivered-Fill (5431-5470),
Reserved-Fill (5479-5509), Verlust-Fill (5516-5554, brutto + poollos).

### B4 — `lost[i]`-Array + Verlust-Fill in den chronologischen Delivered-Pass einreihen

- Neues Array `lost = [0.0] * len(cargo)` neben `delivered`.
- Der Delivered-Pass (`for q in network:`, network nach `dep_time` sortiert, `database.py:5391`)
  behandelt zusätzlich `q.get("loss_kind") in ("stolen", "sunk")`:
  - gleicher `_fillable`-Check, gleiche `per_flight_max_kg`-Kappung,
  - füllt `lost[i]` statt `delivered[i]`,
  - Space-Formel `space = cargo_targets[i] - delivered[i] - lost[i]` (dieselbe wie für Lieferungen,
    beide ziehen sich gegenseitig ab, chronologisch in `dep_time`-Reihenfolge aufgelöst).
- `q["loaded"]` (Lieferung): Space-Formel um `- lost[i]` erweitern (`database.py:5444`):
  `space = cargo_targets[i] - delivered[i] - lost[i]`.
- `returned` bleibt AUSSEN vor diesem Pool-Pass. Der bestehende Verlust-Fill-Block
  (`database.py:5516-5554`) wird dabei von `if q.get("loss_kind"):` auf
  `if q.get("loss_kind") == "returned":` **verengt** — stolen/sunk werden dort ENTFERNT (die
  wandern in den Merge-Pass B4), nur die rein kosmetische Brutto-Bordladungs-Anzeige für
  `returned` bleibt dort unverändert. Kein Pool-Verbrauch durch `returned`.
- Die je-Flug-Ausgabe (`q["lost_kg"]`/`q["cargo_lines"]` für Verlust-Zeilen) = Σ der tatsächlich in
  `lost[i]` zugeordneten `contrib`-Werte (netto), NICHT das rohe Ziel. Löst #7.

### B5 — Reserved-Fill zieht `lost[i]` zusätzlich ab

Datei: `database.py:5491`. Space-Formel:
`space = cargo_targets[i] - delivered[i] - lost[i] - reserved_alloc[i]`.
→ verlorene Ware wird keinem späteren offenen Flug mehr als ladbar angeboten. Löst #8 (gemeinsam
mit B4: `lost[i]` fließt in JEDE nachfolgende Space-Berechnung).

### B6 — `cargo_out`: `lost_kg` je Frachtart (Q6)

Datei: `database.py:5566-5577`. Neues Feld je Frachtart: `"lost_kg": round(lost[i], 1)` — analog zu
`delivered_kg`/`reserved_kg`. UI kann „🎞️ 100 kg verloren" zeigen und damit sichtbar machen, warum
ein Event <100 % bleibt. `progress_pct`/`target_kg` (`database.py:5579-5580`) bleiben UNVERÄNDERT
gegen das rohe Ziel (Entscheidung „Target bleibt Maßstab").

### B7 — Nicht angefasst (Entscheidung „Target bleibt Maßstab")

- `poller.py:1280-1284` (`goal_reached_at` gegen rohes `target_kg`) — UNVERÄNDERT. Ein durch
  Verluste unvollendbares Event latcht `goal_reached_at` nicht; das ist gewollt.
- `poller.py:1285-1320` (`summarized_at`/Feierabend) — UNVERÄNDERT, hängt an `dtend`, schließt
  normal ab.
- Badge (`main.py:1886-1917`) — profitiert automatisch von der Netto-Korrektur (summiert
  `stolen_kg`/`sunk_kg` aus `progress["losses"]`), keine Logikänderung.
- Kein `deliverable_kg`-Feld, kein eigener Abschluss-Zustand (bewusst nicht gewählt).

### B8 — Tests #7/#8

Datei: `tests/test_database.py` (Kutter-Progress-Tests).

- **#7 netto:** Frachtart mit `target=500`, `delivered=368`; ein `stolen`-Flug ab passendem
  Startplatz. Erwartung: dessen `lost_kg` = das noch verfügbare Netto (≤ 132 + was der Payload
  hergibt), NICHT 500. Kein Doppel-Ausweisen der schon gelieferten 368.
- **#8 Pool-Verbrauch:** Nach einem `stolen`/`sunk` einer Frachtart bietet ein späterer offener
  Flug (Reserved-Fill) diese Menge NICHT mehr an: `reserved_kg` respektiert
  `target - delivered - lost`. Gesamt „verbraucht" (delivered+lost) übersteigt `target` nie.
- **`returned` verbraucht NICHT:** Ein `returned`-Flug reduziert weder `lost[i]` noch den
  ladbaren Pool; die Frachtart bleibt voll verfügbar.
- **Unvollendbar bleibt <100 %:** Event mit einem echten Verlust erreicht `progress_pct` < 100 und
  latcht `goal_reached_at` nicht, schließt aber via `dtend` (Snapshot) ab.

---

## Versionierung & Deploy

- #6 als eigener Commit (einzeln deploybar, v8.19.0). #7+#8 als zweiter Commit (v8.20.0) — oder
  gebündelt, je nach Testlage; Entscheidung bei Umsetzung. Jeweils CHANGELOG + Tag + Docs-Abgleich
  (`docs/api.md` für das neue `cargo_out.lost_kg`-Feld; `docs/architecture.md` für die
  Latch-Semantik).
- Push auf `main` → GitHub Actions → GHCR → VPS. Vor Push kurz bestätigen lassen.
- Volle Test-Suite muss grün sein; die #6-Regressionstests sind die wichtigsten (sie sichern, dass
  die #66/#65/#23-Altfixes nicht brechen).
