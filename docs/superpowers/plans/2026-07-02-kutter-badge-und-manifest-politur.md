# FriesenKutter v7.7.0 — Forum-Badge (#18) + Manifest-Editor-Politur (#21)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** (A) Der Manifest-Editor im Admin zeigt die Katalog-Kappung (`per_flight_max_kg`)
live an und speist die Vorschlagsliste aus dem Katalog. (B) Nach der Feierabend-Bilanz gibt
es pro Kutter-Teilnehmer ein rundes Forum-Badge-PNG (analog Bummel-Badge) mit Verlust-Spott.

**Architecture:** Badge-Rendering erweitert `app/badge.py` (Pillow, vorhandene Helfer
`_ctext`/`_load_bg`/`_finish`/`_event_caption`/`_footer`); zwei neue Endpoints in
`app/main.py` spiegeln exakt das Bummel-Muster (öffentlich mit ETag-/Datei-Cache, Admin-
Vorschau frisch). Daten kommen aus `compute_transport_progress` (participants + losses).
Die Editor-Politur ist reines `admin.html`-JavaScript.

**Tech Stack:** Python 3.11, FastAPI, Pillow, Vanilla JS.

## Global Constraints (Nutzer-Entscheidungen, verbatim einhalten)

- **Ein Badge für alle Teilnehmer** (kooperativ, kein Sieger-Badge). Hintergrund:
  `medal_bg.png` (navy Kern), Fallback-Scheibe navy.
- **Slogan:** exakt `VOLL BELADEN!` (einzeilig, Orange).
- **Zusatzlabel nur für Verlust-Piloten:** nur geklaut → `SPITZBOOV!`; nur versenkt →
  `BADEMESTER!`; beides im selben Event → `SEEROVER!`. Kein Label ohne Verlust.
- **Inhalt:** Callsign, Name, Muster, gelieferte kg gesamt, Event-Name + Datum; bei Verlust
  zusätzlich Mengen-Zeile, z. B. `292 kg versenkt`, `150 kg geklaut` oder beides kombiniert.
- **Verfügbar erst nach Feierabend-Bilanz** (`summarized_at` gesetzt), vorher 404.
  Admin-Endpoint rendert immer (Vorschau).
- **Nur ASCII-Text auf dem Badge** (Pillow-Default-Font rendert Emoji/typografische
  Sonderzeichen als Tofu — bestehende Konvention in `app/badge.py`).
- Mobile-Regel: neue/angefasste Tabellen bleiben in Scroll-Wrappern; Blau `#2d9cdb`
  (CSS-Var `--green`) nur für Klickbares.
- Version **v7.7.0** (Minor): `app/CHANGELOG.json` oben ergänzen, Git-Tag `v7.7.0`
  (macht der Controller beim Abschluss), Docs (README, docs/api.md, docs/architecture.md)
  nachziehen.

---

### Task 1: Manifest-Editor-Politur (#21) — nur `app/static/admin.html`

**Files:**
- Modify: `app/static/admin.html` (Manifest-Formular ~Z. 837–851, `keCargoRow` ~Z. 1968,
  Katalog-Ladefunktion mit `_keCatalog`)

**Interfaces:**
- Consumes: `_keCatalog` (Array `{id, name, emoji, per_flight_max_kg}`), Datalist
  `#ke-cargo-suggestions`, `keCargoRow(name, kg)`.
- Produces: keine neuen Schnittstellen (reine UI-Politur).

**Anforderungen:**

- [ ] **Kappungs-Hinweis pro Manifest-Zeile:** In `keCargoRow` einen kleinen Hinweis-Span
  ergänzen (Farbe `#8aa0b8`, ~0.75rem, gleiche Optik wie der `max X kg/Flug`-Hinweis in der
  Katalogliste ~Z. 2211). Bei jedem `input`-Event auf `.ke-c-name` gegen `_keCatalog`
  matchen (case-insensitive, exakter Name — dieselbe Logik wie `keCollectCargo` ~Z. 1988):
  Treffer mit `per_flight_max_kg` → `max X kg/Flug` anzeigen (+ Emoji davor, falls
  vorhanden); Treffer ohne Kappung → nur Emoji bzw. nichts; Freitext → Hinweis leeren.
  Beim Befüllen bestehender Zeilen (Event bearbeiten) muss der Hinweis initial stimmen
  (Update-Funktion nach dem Setzen von `value` einmal aufrufen).
- [ ] **Vorschlagsliste aus dem Katalog:** Nach erfolgreichem Katalog-Load die Optionen der
  Datalist `#ke-cargo-suggestions` aus `_keCatalog`-Namen neu aufbauen. Ist der Katalog
  leer, bleibt die hartkodierte Liste (Z. 838–849) unverändert stehen (Fallback).
  Nach Katalog-Änderungen (Speichern/Löschen einer Frachtart) aktualisiert sich die
  Datalist mit (an derselben Stelle einhängen, an der `_keCatalog` neu geladen wird).
- [ ] **Snapshot-Hinweis:** Unter dem Titel „Fracht-Manifest (Reihenfolge = Beladung)"
  einen Hilfetext ergänzen (Optik wie ~Z. 803): „Emoji + Max/Flug kommen beim Speichern
  aus dem Katalog (Snapshot) — spätere Katalog-Änderungen wirken nicht auf bestehende
  Events; erneutes Speichern übernimmt den aktuellen Stand."
- [ ] **Kein Test-Framework für admin.html** — Verifikation: `node --check` ist auf das
  eingebettete Script nicht direkt anwendbar; stattdessen JS-Syntax prüfen, indem der
  Script-Block extrahiert und mit `node --check` geparst wird (Muster: Scratchpad
  `check.js`), plus Selbstreview der drei Punkte.
- [ ] **Commit:** `feat(admin): Manifest-Editor zeigt Katalog-Kappung + Vorschläge aus Katalog (#21)`

### Task 2: Kutter-Forum-Badge (#18) — Backend + Endpoints + App-Verlinkung

**Files:**
- Modify: `app/badge.py` (neu: `render_kutter_badge`)
- Modify: `app/main.py` (2 Endpoints, Muster: `get_bummel_badge` Z. 958–1006 /
  `admin_bummel_badge` Z. 1009–1025, Helfer `_badge_entry_data`)
- Modify: `app/static/index.html` (Badge-Links in der Kutter-Detailansicht nach Bilanz)
- Test: `tests/test_transport.py` (neue Klasse `TestKutterBadge`)

**Interfaces:**
- Consumes: `compute_transport_progress(...)` → `participants`
  (`{cid, name, callsign, aircraft, flights, delivered_kg|delivered, lost, status}` — exakte
  Feldnamen in `app/database.py` nachschlagen!) und `losses`
  (Einträge mit `cid`, `kind` ∈ {stolen, sunk, returned}, kg-Angaben — exakte Struktur
  ebenfalls nachschlagen); `get_transport_event(conn, id)` mit `summarized_at`.
- Produces:
  - `render_kutter_badge(d: dict) -> bytes` mit
    `d = {callsign, name, aircraft, delivered_kg, stolen_kg, sunk_kg, event, date}`
  - `GET /api/transport/event/{event_id}/badge/{cid}.png` (öffentlich)
  - `GET /api/admin/transport/events/{event_id}/badge/{cid}.png` (Admin-Vorschau)

**Anforderungen:**

- [ ] **`render_kutter_badge` in `app/badge.py`:** Hintergrund `medal_bg.png`
  (`_load_bg`) bzw. `_fallback_disk(_NAVY)`. Layout (y-Anteile an `_S`, per `_ctext`):
  - 0.215: `VOLL BELADEN!` (Orange `_ORANGE`, Größe 34)
  - 0.310: Callsign (`_LBLUE`, 58)
  - 0.430: Name (`_WHITE`, 24) — nur wenn vorhanden
  - 0.520: Muster (`_LBLUE`, 22; leer → `k. A.`)
  - 0.585: `X kg geliefert` (`_LBLUE`, 20; kg gerundet int; 0 kg → `0 kg geliefert`)
  - Nur bei Verlust (stolen_kg>0 oder sunk_kg>0):
    - 0.648: Label `SPITZBOOV!` / `BADEMESTER!` / `SEEROVER!` (`_ORANGE`, 24) —
      Auswahl als **pure Funktion** `_kutter_loss_label(stolen_kg, sunk_kg) -> str | None`
      (None wenn beide 0) — direkt testbar.
    - 0.706: Mengen-Zeile (`_WHITE`, 18): nur geklaut → `150 kg geklaut`; nur versenkt →
      `292 kg versenkt`; beides → `150 kg geklaut, 292 kg versenkt` (ASCII-Komma, kein `·`).
  - `_event_caption` (0.750/0.805) + `_footer` wie bei den Bummel-Badges.
- [ ] **Öffentlicher Endpoint** `GET /api/transport/event/{event_id}/badge/{cid}.png` in
  `app/main.py`: Event laden; 404 wenn nicht vorhanden oder `summarized_at` leer.
  `compute_transport_progress` aufrufen (mit denselben Parametern/Radius wie der bestehende
  `GET /api/transport/event/{id}`-Endpoint — dort nachlesen), Teilnehmer per `cid` suchen
  (404 wenn nicht dabei). Verlust-kg pro Art aus `losses` für die CID aufsummieren
  (`returned` zählt NICHT). ETag-/Datei-Cache exakt nach Bummel-Muster (Z. 979–1006):
  MD5-Key über `summarized_at | delivered | stolen | sunk | aircraft | callsign | event`,
  Cache-Datei `badges/kutter_{event_id}_{cid}_{key}.png`, `Cache-Control: no-cache` + 304.
- [ ] **Admin-Endpoint** `GET /api/admin/transport/events/{event_id}/badge/{cid}.png`:
  `require_admin`, rendert immer frisch (auch ohne `summarized_at`), `Cache-Control: no-store`.
- [ ] **App-Verlinkung (`app/static/index.html`):** In der Kutter-Detailansicht im
  Events-Tab (`_kutterDetailBody`) NUR wenn das Event `summarized_at` hat: kompakter
  Abschnitt „🎖 Badges" über dem Feed — pro Teilnehmer eine Zeile
  `Callsign — 🎖 Badge (Link, öffnet PNG) · 📋 Forum (kopiert BBCode)`, exakt nach dem
  Muster `_bummelBadgeLinks`/`copyBummelBadgeCode` (Z. 2874–2888; BBCode
  `[img]…/api/transport/event/{id}/badge/{cid}.png[/img]`). Kein Inline-onclick mit
  interpolierten Strings für Callsigns (XSS-Regel) — Zahlen (id, cid) sind ok.
  Buttons/Links sind klickbar → dürfen blau sein; der Callsign-Text bleibt neutral.
- [ ] **Tests (`tests/test_transport.py`, Klasse `TestKutterBadge`):**
  - `_kutter_loss_label`: (0,0)→None, (x,0)→SPITZBOOV!, (0,x)→BADEMESTER!, (x,y)→SEEROVER!
  - `render_kutter_badge` liefert PNG-Bytes (Signatur `\x89PNG`) mit und ohne Verlust.
  - Endpoint-Tests mit `TestClient` (Muster: bestehende Transport-API-Tests):
    404 vor Bilanz, 200 + `image/png` nach `summarized_at` (Event-Fixture direkt in der DB
    auf summarized setzen), 404 für Nicht-Teilnehmer, Admin-Endpoint 200 auch ohne Bilanz
    (mit Admin-Session) und 401/403 ohne.
- [ ] **Docs:** `docs/api.md` (beide Endpoints), `docs/architecture.md` (Badge-Abschnitt um
  Kutter ergänzen), `README.md` (Feature-Zeile).
- [ ] **Commit:** `feat(kutter): Forum-Badge pro Teilnehmer nach Feierabend-Bilanz (#18)`

---

## Verifikation (Controller)

1. `pytest tests/ -v` grün (Basis: 559).
2. Lokale Demo (Port 8091, Demo-DB hat summarized-fähiges Event): Badge-PNG im Browser
   prüfen (normal + Verlust-Pilot mit BADEMESTER!/SPITZBOOV!), Badge-Sektion im Events-Tab.
3. Changelog v7.7.0 + Tag, Docs, Push auf main → Actions-Health-Check → Prod-Version 7.7.0.
