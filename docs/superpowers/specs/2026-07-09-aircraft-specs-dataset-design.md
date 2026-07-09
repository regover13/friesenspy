# Kuratierter Flugzeug-Spec-Datensatz statt Live-Web-Recherche

**Datum:** 2026-07-09
**Status:** Design abgenommen (Nutzer), Implementierungsplan folgt
**Betrifft:** `app/llm.py`, `app/poller.py`, `app/database.py`, `app/static/admin.html`, neu: `app/data/aircraft_specs.json`

## Problem

Die Zuladungs-Werte pro Flugzeugtyp (MTOW, Leergewicht, Sprit → `payload_kg`) werden
**live per Web-Search** ermittelt (Haiku 4.5 + serverseitiges `web_search`-Tool,
`llm.suggest_aircraft_payload`). Das passiert **automatisch im Poller**: sobald ein
getrackter Pilot einen Typ fliegt, der noch nicht in `aircraft_payloads` steht, stößt
`poller.py` (~Zeile 866-886) im Hintergrund `_auto_research_payload(code)` an. Der
Admin-Knopf „KI-Vorschlag" ist nur der zusätzliche manuelle Weg.

Drei Schmerzpunkte (vom Nutzer bestätigt):

- **Wartezeit:** Der manuelle „Vorschlag"-Knopf blockiert ~15-20 s mit Spinner.
- **Kosten:** Jede automatische Recherche kostet ~4-7 ct auf dem geteilten
  `ANTHROPIC_API_KEY`. Über viele neu gesehene Typen summiert sich das.
- **Qualität:** Die in einem hektischen Web-Call ermittelten Werte schwanken, erwischen
  mal die falsche Variante oder sind schlicht falsch.

Flugzeug-Spezifikationen ändern sich nie, und die Typen, die die FriesenFlieger fliegen,
stehen praktisch fest — die kuratierte `_TYPE_HINTS`-Liste in `app/llm.py` führt bereits
~120 Muster (MSFS-Standardflotte + gängige GA-Addons). Es gibt also keinen Grund, dieselben
Werte bei jedem neu gesehenen Typ live neu zu recherchieren.

## Ziel

Für die ~120 bekannten Typen: **sofort, kostenlos, verlässlich** — kein Web-Call. Der
Web-Search bleibt nur noch als Fallback für echte Exoten (Nutzer-Entscheidung:
„Web-Search behalten").

## Ansatz (abgenommen)

Ein einmalig sorgfältig recherchierter, **im Repo versionierter** Spec-Datensatz, mit dem
die bestehende `aircraft_payloads`-Tabelle beim Start vorbefüllt wird. **Keine neue
DB-Tabelle**, und — weil vorbefüllt wird — **keine Änderung an
`suggest_aircraft_payload`**: der Poller recherchiert ohnehin nur für Typen, die noch
nicht in `aircraft_payloads` stehen; sind die 120 vorbefüllt, feuert der Web-Search für
sie nie.

### Erzeugung des Datensatzes

- Die Recherche der ~120 Typen macht **der Agent selbst** (eigene Such-/Prüf-Tools bzw.
  Wissen + Kreuzprüfung) — **nicht** über den App-`web_search`. Kosten auf dem
  `ANTHROPIC_API_KEY`: **null**.
- Jeder Eintrag erhält beim Erzeugen intern Konfidenz + Quelle; unsichere/widersprüchliche
  Fälle werden markiert.
- Zusätzlich automatischer Plausibilitäts-Check: `empty_kg < mtow_kg`, beide > 0,
  `fuel_full_kg > 0`, resultierende `payload_kg ≥ 0`.
- **Review:** Der Nutzer prüft **nur die markierten Ausreißer** (~10-20), der Rest gilt als
  solide. Nach Freigabe wird die JSON eingecheckt.

## Komponenten

### 1. `app/data/aircraft_specs.json` (neu)

Statische Werteliste, keyed nach **normalisiertem** Typcode (`normalize_type_code`:
Uppercase, vor `/` gekürzt). Nur die drei physikalischen Rohwerte + Klartextname:

```json
{
  "C172": {"make_model": "Cessna 172", "mtow_kg": 1111, "empty_kg": 743, "fuel_full_kg": 144},
  "PZ04": {"make_model": "PZL-104 Wilga 35A", "mtow_kg": 1300, "empty_kg": 850, "fuel_full_kg": 137}
}
```

Alles Weitere (halber Tank als Default-Betankung, Crew, `payload_kg`) rechnet die
**bestehende** `llm._build_result()` — eine einzige Wahrheit, keine doppelte Mathematik.
Die Schlüssel-Menge orientiert sich an `_TYPE_HINTS`.

### 2. Idempotentes Seeding beim Start (neu, in `app/database.py`)

Beim Start/Migration werden alle kuratierten Typen in `aircraft_payloads` eingefügt:

- **Nur einfügen, wenn `type_code` noch nicht vorhanden** — bestehende Zeilen (insb.
  `source='manual'`) werden **nie** überschrieben.
- Neue Zeilen: `source='curated'`, Komponenten aus `_build_result()` (mtow/empty/fuel/crew/
  payload), `make_model` aus der JSON.
- Idempotent, läuft bei jedem Start: schickt ein späteres Release neue Typen in der JSON
  mit, seeden die sich beim nächsten Deploy automatisch.
- Bewusste Konsequenz: ein absichtlich gelöschter kuratierter Typ kommt beim nächsten
  Start wieder (kuratierter Grundstock — vom Nutzer so gewollt).

### 3. `suggest_aircraft_payload` — unverändert

Der Web-Search-Pfad (Haiku + `web_search_20250305`) bleibt exakt wie heute. Er greift nur
noch für Typen, die **nicht** kuratiert und **nicht** in der Tabelle sind — also seltene
Exoten. Kein Code-Eingriff nötig.

### 4. Admin-UI: editierbares Namensfeld (`app/static/admin.html`)

Heute ist `make_model` nur ein Anzeige-`<span>` (`admin.html:925`) — der Name lässt sich
nicht bearbeiten (z. B. „Aerostar 600" nachtragen). Änderung, **UI-only**:

- `<span id="kp-make-model">` → `<input type="text" id="kp-make-model">` als eigenes
  Formularfeld (Label „Muster/Name").
- KI-Vorschlag/Bearbeiten setzt `.value` statt `.textContent` (`admin.html:2450`, `2480`).
- Speichern liest `.value` statt `.textContent` (`admin.html:2494`).
- **Kein Backend-Umbau:** `admin_upsert_payload` liest `make_model` bereits aus dem Body
  (`main.py:2171`), `upsert_payload` persistiert ihn. Beim Speichern wird die Zeile
  `source='manual'` — der kuratierte Seed fasst sie danach nie wieder an (konsistent mit
  der Seeding-Regel).

### 5. Admin-Tabelle: Sortierung

Bleibt alphabetisch nach `type_code` (`list_aircraft_payloads` → `ORDER BY type_code`,
`database.py:3930`); greift automatisch auch für die 120 vorbefüllten Zeilen.

## Datenfluss

```
Poller sieht Typ live
  └─ Typ in aircraft_payloads? ── ja ──> nutzt DB-Wert (Seed oder manuell), KEIN Web-Call
                               └─ nein ─> _auto_research_payload → suggest_* → Web-Search
                                          (nur echte Exoten)

Start/Migration
  └─ für jeden kuratierten Typ: fehlt in aircraft_payloads? ── ja ─> INSERT source='curated'
                                                             └─ nein ─> unangetastet lassen

Admin „Bearbeiten"/„KI-Vorschlag"/„Speichern"
  └─ Name jetzt editierbar (input); Speichern → source='manual', immun gegen Seed
```

## Tests

- **Seeding fügt ein:** leere Tabelle → nach Seed sind die kuratierten Typen mit
  `source='curated'` und korrekt gerechnetem `payload_kg` vorhanden.
- **Seeding verschont `manual`:** vorhandene `source='manual'`-Zeile wird durch den Seed
  nicht verändert (Werte + source bleiben).
- **Idempotenz:** zweiter Seed-Lauf ändert nichts.
- **JSON-Plausibilität:** jeder Eintrag erfüllt `mtow_kg > empty_kg > 0`,
  `fuel_full_kg > 0`, `_build_result(...)['payload_kg'] ≥ 0`; alle Schlüssel sind
  normalisiert (`normalize_type_code(k) == k`).
- **Admin-Namensfeld:** Upsert mit gesetztem `make_model` speichert den Namen (Backend-Pfad
  ist schon vorhanden; Test sichert das Verhalten ab).
- **Fallback unverändert:** bestehende `test_llm_suggest`/`test_poller`-Pfade bleiben grün.

## Nicht im Scope (YAGNI)

- Kein neuer Runtime-Cache-Layer. Gespeicherte/geseedete Typen liegen in
  `aircraft_payloads`; unbekannte laufen wie heute über den Web-Fallback.
- Keine Änderung am Web-Search-Call selbst (Prompt, Runden, Modell).
- Kein zweites Schema / keine Sync-Logik zwischen JSON und DB — die JSON ist reine
  Seed-Quelle, zur Laufzeit ist `aircraft_payloads` die einzige Wahrheit.

## Versionierung & Docs (stehende Regel)

- Version-Bump **Minor** (Feature) in `app/CHANGELOG.json` (oben), Git-Tag `vX.Y.0`, Banner
  automatisch.
- README + `docs/api.md` + `docs/architecture.md` mitpflegen (neuer Seed-Schritt,
  Datensatz-Datei, editierbares Namensfeld).
