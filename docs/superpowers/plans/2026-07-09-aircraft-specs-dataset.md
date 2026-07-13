# Kuratierter Flugzeug-Spec-Datensatz Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die ~120 gängigen Flugzeugtypen aus einem im Repo versionierten Datensatz beim Start in `aircraft_payloads` vorbefüllen, sodass der teure Live-Web-Search nur noch für echte Exoten feuert; zusätzlich den Muster-Namen im Admin editierbar machen.

**Architecture:** Neue Datendatei `app/data/aircraft_specs.json` (vom Agent recherchiert). `init_db()` ruft ein idempotentes `seed_curated_payloads()`, das fehlende kuratierte Typen mit `source='curated'` per `INSERT OR IGNORE` einfügt (bestehende/`manual`-Zeilen unangetastet). `suggest_aircraft_payload` bleibt unverändert = Web-Fallback. Admin-UI: Anzeige-`<span>` für `make_model` wird ein editierbares `<input>`.

**Tech Stack:** Python 3.11, sqlite3, FastAPI, Vanilla-JS (admin.html), pytest.

## Global Constraints

- Typcodes werden IMMER über `database.normalize_type_code()` normalisiert (Uppercase, vor `/` gekürzt). JSON-Schlüssel müssen bereits normalisiert sein.
- Zuladungs-Mathematik NUR über `llm._build_result()` — keine Neu-Implementierung (DRY). Default: halber Tank (`fuel_kg = fuel_full_kg/2`), Crew 85 kg zählt nicht als Fracht.
- Seeding überschreibt NIE bestehende Zeilen (insb. `source='manual'`). Nur `INSERT OR IGNORE`.
- Nur endliche, positive Werte (`math.isfinite`, `> 0`) — kein `inf`/`nan` in die DB.
- Versionierung (stehende Regel): Version-Bump **Minor** in `app/CHANGELOG.json` (oben einfügen), Git-Tag `v8.17.0`, Banner automatisch. Aktuelle Version: `8.16.4` → neu `8.17.0`.
- Docs mitpflegen: `README.md`, `docs/api.md`, `docs/architecture.md`.
- Commits direkt auf `main`, kein PR. Vor `git push` kurz bestätigen lassen.

---

### Task 1: Kuratierter Datensatz `aircraft_specs.json` + Validierungstest

**Files:**
- Create: `app/data/aircraft_specs.json`
- Test: `tests/test_aircraft_specs.py`

**Interfaces:**
- Produces: JSON-Datei `{TYPECODE: {"make_model": str, "mtow_kg": number, "empty_kg": number, "fuel_full_kg": number}}` mit ~120 normalisierten Schlüsseln (Basis: `llm._TYPE_HINTS`).

- [ ] **Step 1: Validierungstest schreiben** (definiert den Qualitäts-Vertrag des Datensatzes)

Datei `tests/test_aircraft_specs.py`:

```python
"""Plausibilitäts-/Struktur-Validierung des kuratierten Flugzeug-Spec-Datensatzes."""
import math

from app import database
from app.llm import _build_result


def test_curated_specs_loadable_and_nonempty():
    specs = database.load_curated_specs()
    assert isinstance(specs, dict)
    assert len(specs) >= 100, "Datensatz sollte ~120 Typen enthalten"


def test_curated_specs_keys_normalized():
    specs = database.load_curated_specs()
    for code in specs:
        assert database.normalize_type_code(code) == code, f"Schlüssel nicht normalisiert: {code}"


def test_curated_specs_values_plausible():
    specs = database.load_curated_specs()
    for code, spec in specs.items():
        assert set(spec) >= {"make_model", "mtow_kg", "empty_kg", "fuel_full_kg"}, code
        mtow, empty, fuel = spec["mtow_kg"], spec["empty_kg"], spec["fuel_full_kg"]
        for v in (mtow, empty, fuel):
            assert isinstance(v, (int, float)) and math.isfinite(v) and v > 0, (code, v)
        assert empty < mtow, f"{code}: Leergewicht ({empty}) >= MTOW ({mtow})"
        assert isinstance(spec["make_model"], str) and spec["make_model"].strip(), code
        r = _build_result(spec["make_model"], float(mtow), float(empty), float(fuel))
        assert r["payload_kg"] >= 0, f"{code}: negative Zuladung"
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen** (JSON fehlt noch, `load_curated_specs` gibt es noch nicht)

Run: `pytest tests/test_aircraft_specs.py -v`
Expected: FAIL (`AttributeError: module 'app.database' has no attribute 'load_curated_specs'`) — das ist ok, `load_curated_specs` kommt in Task 2. Für Task 1 zunächst nur die JSON erzeugen; der Test wird nach Task 2 grün. **Reihenfolge-Hinweis:** Wer strikt test-first arbeitet, kann Task 2 Step 1-3 (Loader) vorziehen; die Datei-Erzeugung hier ist unabhängig davon.

- [ ] **Step 3: Datensatz recherchieren und schreiben** (macht der Agent selbst — KEIN App-`web_search`, kein `ANTHROPIC_API_KEY`)

Für jeden Code aus `llm._TYPE_HINTS` (app/llm.py:49) die realen Herstellerangaben ermitteln (MTOW, Standard-Leergewicht, nutzbarer Sprit bei vollen Tanks in kg), mit Kreuzprüfung mehrerer Quellen. Konservativ runden, dokumentierte Werte, gängigste zertifizierte Variante. Ergebnis nach `app/data/aircraft_specs.json`:

```json
{
  "C172": {"make_model": "Cessna 172", "mtow_kg": 1111, "empty_kg": 743, "fuel_full_kg": 144},
  "PZ04": {"make_model": "PZL-104 Wilga 35A", "mtow_kg": 1300, "empty_kg": 850, "fuel_full_kg": 137}
}
```

Jeden Eintrag intern mit Konfidenz + Quelle versehen; unsichere/widersprüchliche Fälle in einer separaten Ausreißer-Liste sammeln.

- [ ] **Step 4: Ausreißer-Review (Human-Gate)**

Dem Nutzer die markierten Ausreißer (~10-20) als Tabelle (Typ, MTOW, Leer, Sprit, Quelle, Zweifel) vorlegen. Erst nach Freigabe/Korrektur weiter.

- [ ] **Step 5: Test laufen lassen — muss (nach Task-2-Loader) grün sein**

Run: `pytest tests/test_aircraft_specs.py -v`
Expected: PASS (alle Einträge plausibel, Schlüssel normalisiert).

- [ ] **Step 6: Commit**

```bash
git add app/data/aircraft_specs.json tests/test_aircraft_specs.py
git commit -m "feat: kuratierter Flugzeug-Spec-Datensatz (~120 Typen) + Validierung"
```

---

### Task 2: Loader + idempotentes Seeding in `database.py`

**Files:**
- Modify: `app/database.py` (neue Funktionen `load_curated_specs`, `seed_curated_payloads`; Aufruf in `init_db`, ~Zeile 500 vor `conn.commit()`; Import `pathlib.Path`)
- Test: `tests/test_database.py` (neue Tests am Ende)

**Interfaces:**
- Consumes: `llm._build_result(make_model, mtow_kg, empty_kg, fuel_full_kg) -> dict` (Keys u.a. `mtow_kg, empty_kg, fuel_kg, crew_kg, payload_kg, make_model`); `database.normalize_type_code`, `database._now_utc`.
- Produces:
  - `load_curated_specs() -> dict[str, dict]` — lädt `app/data/aircraft_specs.json`, `{}` bei Fehler.
  - `seed_curated_payloads(conn: sqlite3.Connection) -> int` — fügt fehlende kuratierte Typen ein (`INSERT OR IGNORE`, `source='curated'`), gibt Anzahl neu eingefügter Zeilen zurück.

- [ ] **Step 1: Failing-Tests schreiben**

Ans Ende von `tests/test_database.py` (nutzt vorhandene Test-Helfer für eine temp-DB via `init_db` + `get_connection`; falls das Modul ein Fixture `db_path`/`conn` hat, dieses verwenden — sonst analog zu bestehenden Tests eine temp-DB anlegen):

**WICHTIG:** synthetischer Typcode `ZTST` (NICHT im echten Datensatz) — sonst hat ihn
`init_db` nach Task 1 schon geseedet und `inserted == 1` schlägt fehl.

```python
def test_seed_inserts_curated(tmp_path, monkeypatch):
    from app import database
    db = str(tmp_path / "t.db")
    database.init_db(db)
    conn = database.get_connection(db)
    monkeypatch.setattr(database, "load_curated_specs", lambda: {
        "ZTST": {"make_model": "Test-Muster", "mtow_kg": 1111, "empty_kg": 743, "fuel_full_kg": 144},
    })
    inserted = database.seed_curated_payloads(conn)
    conn.commit()
    assert inserted == 1
    row = conn.execute("SELECT source, make_model, payload_kg FROM aircraft_payloads WHERE type_code='ZTST'").fetchone()
    assert row["source"] == "curated"
    assert row["make_model"] == "Test-Muster"
    # payload = 1111 - 743 - 144/2 - 85 = 211
    assert abs(row["payload_kg"] - 211.0) < 0.5
    conn.close()


def test_seed_skips_existing_manual(tmp_path, monkeypatch):
    from app import database
    db = str(tmp_path / "t.db")
    database.init_db(db)
    conn = database.get_connection(db)
    database.upsert_payload(conn, "ZTST", payload_kg=999.0, make_model="Handpflege", source="manual")
    conn.commit()
    monkeypatch.setattr(database, "load_curated_specs", lambda: {
        "ZTST": {"make_model": "Test-Muster", "mtow_kg": 1111, "empty_kg": 743, "fuel_full_kg": 144},
    })
    inserted = database.seed_curated_payloads(conn)
    conn.commit()
    assert inserted == 0
    row = conn.execute("SELECT source, make_model, payload_kg FROM aircraft_payloads WHERE type_code='ZTST'").fetchone()
    assert row["source"] == "manual"
    assert row["make_model"] == "Handpflege"
    assert abs(row["payload_kg"] - 999.0) < 0.5
    conn.close()


def test_seed_idempotent(tmp_path, monkeypatch):
    from app import database
    db = str(tmp_path / "t.db")
    database.init_db(db)
    conn = database.get_connection(db)
    monkeypatch.setattr(database, "load_curated_specs", lambda: {
        "ZTST": {"make_model": "Test-Muster", "mtow_kg": 1111, "empty_kg": 743, "fuel_full_kg": 144},
    })
    database.seed_curated_payloads(conn); conn.commit()
    inserted2 = database.seed_curated_payloads(conn); conn.commit()
    assert inserted2 == 0
    cnt = conn.execute("SELECT COUNT(*) c FROM aircraft_payloads WHERE type_code='ZTST'").fetchone()["c"]
    assert cnt == 1
    conn.close()
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_database.py -k seed -v`
Expected: FAIL (`AttributeError: ... 'seed_curated_payloads'`).

- [ ] **Step 3: Loader + Seeding implementieren**

In `app/database.py` den Import ergänzen (zu den bestehenden Imports oben, Zeile ~2-7):

```python
from pathlib import Path
```

Vor `def upsert_payload(` (oder in der Nähe der übrigen Payload-Funktionen, ~Zeile 3934) einfügen:

```python
_CURATED_SPECS_PATH = Path(__file__).parent / "data" / "aircraft_specs.json"


def load_curated_specs() -> dict[str, dict]:
    """Kuratierte Flugzeug-Specs aus dem Repo laden.

    Rückgabe: ``{type_code: {"make_model", "mtow_kg", "empty_kg", "fuel_full_kg"}}``.
    Bei fehlender/kaputter Datei ``{}`` (Silent-Fail — Seeding ist Komfort, kein kritischer Pfad).
    """
    try:
        with open(_CURATED_SPECS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def seed_curated_payloads(conn: sqlite3.Connection) -> int:
    """Fehlende kuratierte Flugzeugtypen in ``aircraft_payloads`` einfügen (idempotent).

    Nur ``INSERT OR IGNORE`` → bestehende Zeilen (insb. ``source='manual'``) bleiben
    unangetastet. Werte werden über ``llm._build_result`` gerechnet (halber Tank, Crew 85).
    Rückgabe: Anzahl neu eingefügter Zeilen.
    """
    from app.llm import _build_result  # lazy: reine Rechnung, vermeidet Modul-Kopplung
    inserted = 0
    for raw_code, spec in load_curated_specs().items():
        code = normalize_type_code(raw_code)
        if not code or not isinstance(spec, dict):
            continue
        try:
            mtow, empty, fuel_full = (
                float(spec["mtow_kg"]), float(spec["empty_kg"]), float(spec["fuel_full_kg"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) and v > 0 for v in (mtow, empty, fuel_full)):
            continue
        r = _build_result(str(spec.get("make_model") or code), mtow, empty, fuel_full)
        cur = conn.execute(
            """INSERT OR IGNORE INTO aircraft_payloads
                   (type_code, mtow_kg, empty_kg, fuel_kg, crew_kg, payload_kg, source, make_model, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'curated', ?, ?)""",
            (code, r["mtow_kg"], r["empty_kg"], r["fuel_kg"], r["crew_kg"], r["payload_kg"],
             r["make_model"], _now_utc()),
        )
        inserted += cur.rowcount
    return inserted
```

In `init_db` (app/database.py) direkt VOR dem abschließenden `conn.commit()` (nach dem `make_model`-Cleanup-Block, ~Zeile 500) einfügen:

```python
        # Kuratierte Flugzeug-Specs vorbefüllen (idempotent, überschreibt nie manuelle Zeilen).
        try:
            seed_curated_payloads(conn)
        except Exception:  # noqa: BLE001 — Seeding ist Komfort, nie den Start blockieren
            pass
```

- [ ] **Step 4: Tests laufen lassen — müssen grün sein**

Run: `pytest tests/test_database.py -k seed -v && pytest tests/test_aircraft_specs.py -v`
Expected: PASS (Seeding-Tests + Datensatz-Validierung).

- [ ] **Step 5: Regression — voller DB-/LLM-/Poller-Testlauf**

Run: `pytest tests/test_database.py tests/test_llm_suggest.py tests/test_poller.py -q`
Expected: PASS (keine Regression; `suggest_aircraft_payload` unverändert).

- [ ] **Step 6: Commit**

```bash
git add app/database.py tests/test_database.py
git commit -m "feat: idempotentes Seeding kuratierter Zuladungen in init_db"
```

---

### Task 2b: Neue Spalte `fuel_full_kg` (max. Tankinhalt) + Halb-Tank im Rechenfeld

**Nachträgliche Anforderung (Nutzer):** Der MAXIMALE Tankinhalt wird als eigenes Feld
gespeichert; das Rechenfeld `fuel_kg` bleibt der HALBE Tank (`fuel_full_kg/2`). Gilt auch für
bestehende DB-Zeilen (Backfill `fuel_full_kg = fuel_kg*2`, weil `fuel_kg` bisher schon halb war).

**Files:**
- Modify: `app/database.py` (DDL `aircraft_payloads`, `_TRANSPORT_MIGRATIONS`, `init_db`-Backfill, `upsert_payload`, `seed_curated_payloads`, `list_aircraft_payloads`)
- Test: `tests/test_database.py`

**Interfaces:**
- Produces: `aircraft_payloads.fuel_full_kg` (REAL, max. Tank, kg); `upsert_payload(..., fuel_full_kg=None)`; `list_aircraft_payloads` liefert `fuel_full_kg` mit.

- [ ] **Step 1: Failing-Tests schreiben** (ans Ende von `tests/test_database.py`)

```python
def test_upsert_stores_fuel_full(tmp_path):
    from app import database
    db = str(tmp_path / "t.db"); database.init_db(db)
    conn = database.get_connection(db)
    database.upsert_payload(conn, "ZFUL", mtow_kg=1000, empty_kg=600, fuel_kg=50,
                            fuel_full_kg=100, crew_kg=85, source="manual")
    conn.commit()
    row = conn.execute("SELECT fuel_kg, fuel_full_kg FROM aircraft_payloads WHERE type_code='ZFUL'").fetchone()
    assert abs(row["fuel_kg"] - 50) < 0.5
    assert abs(row["fuel_full_kg"] - 100) < 0.5
    conn.close()


def test_fuel_full_backfill(tmp_path):
    from app import database
    db = str(tmp_path / "t.db"); database.init_db(db)
    conn = database.get_connection(db)
    conn.execute("INSERT INTO aircraft_payloads (type_code, fuel_kg, payload_kg, fuel_full_kg, source) "
                 "VALUES ('ZBACK', 60, 100, NULL, 'manual')")
    conn.commit(); conn.close()
    database.init_db(db)  # Backfill läuft erneut (idempotent)
    conn = database.get_connection(db)
    row = conn.execute("SELECT fuel_full_kg FROM aircraft_payloads WHERE type_code='ZBACK'").fetchone()
    assert abs(row["fuel_full_kg"] - 120) < 0.5
    conn.close()


def test_seed_stores_fuel_full(tmp_path, monkeypatch):
    from app import database
    db = str(tmp_path / "t.db"); database.init_db(db)
    conn = database.get_connection(db)
    monkeypatch.setattr(database, "load_curated_specs", lambda: {
        "ZTST": {"make_model": "Test-Muster", "mtow_kg": 1111, "empty_kg": 743, "fuel_full_kg": 144},
    })
    database.seed_curated_payloads(conn); conn.commit()
    row = conn.execute("SELECT fuel_kg, fuel_full_kg FROM aircraft_payloads WHERE type_code='ZTST'").fetchone()
    assert abs(row["fuel_full_kg"] - 144) < 0.5   # Max
    assert abs(row["fuel_kg"] - 72) < 0.5          # Hälfte
    conn.close()
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_database.py -k "fuel_full or backfill" -v`
Expected: FAIL (Spalte/Parameter fehlt).

- [ ] **Step 3: Implementieren**

(a) DDL: in der `CREATE TABLE IF NOT EXISTS aircraft_payloads`-Definition nach der `fuel_kg`-Zeile ergänzen:
```sql
    fuel_full_kg REAL,                   -- max. Tankinhalt (volle Tanks); fuel_kg = Hälfte davon
```

(b) `_TRANSPORT_MIGRATIONS` (die Liste mit dem `crew_kg`-ALTER) um einen Eintrag ergänzen:
```python
    "ALTER TABLE aircraft_payloads ADD COLUMN fuel_full_kg REAL",
```

(c) `init_db`: bei den übrigen Backfills (nach dem `make_model`-Cleanup, vor `seed_curated_payloads`) einfügen:
```python
        try:
            conn.execute(
                "UPDATE aircraft_payloads SET fuel_full_kg = fuel_kg * 2 "
                "WHERE fuel_full_kg IS NULL AND fuel_kg IS NOT NULL"
            )
        except sqlite3.OperationalError:
            pass
```

(d) `upsert_payload`: Parameter `fuel_full_kg: float | None = None` ergänzen, per `_finite_or_none` härten, in INSERT-Spaltenliste + VALUES + ON CONFLICT DO UPDATE aufnehmen (analog zu `fuel_kg`).

(e) `seed_curated_payloads`: in der INSERT-Anweisung die Spalte `fuel_full_kg` ergänzen und `r["fuel_full_kg"]` (Max) mitschreiben — `fuel_kg` bleibt `r["fuel_kg"]` (Hälfte):
```python
        cur = conn.execute(
            """INSERT OR IGNORE INTO aircraft_payloads
                   (type_code, mtow_kg, empty_kg, fuel_kg, fuel_full_kg, crew_kg, payload_kg, source, make_model, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'curated', ?, ?)""",
            (code, r["mtow_kg"], r["empty_kg"], r["fuel_kg"], r["fuel_full_kg"], r["crew_kg"],
             r["payload_kg"], r["make_model"], _now_utc()),
        )
```

(f) `list_aircraft_payloads`: `fuel_full_kg` in die SELECT-Spaltenliste aufnehmen (damit das Admin es bekommt).

- [ ] **Step 4: Tests grün**

Run: `python -m pytest tests/test_database.py -q`
Expected: PASS (inkl. der bestehenden Seeding-Tests).

- [ ] **Step 5: Commit**

```bash
git add app/database.py tests/test_database.py
git commit -m "feat: max. Tankinhalt (fuel_full_kg) speichern; Rechenfeld bleibt halber Tank"
```

---

### Task 2c: Poller-Auto-Erkennung schreibt `fuel_full_kg` mit

**Anforderung (Nutzer):** Auch die automatische Erkennung/AI-Abfrage soll den max. Tank speichern
und das Rechenfeld auf die Hälfte setzen. `fuel_kg` ist dort schon die Hälfte (aus `_build_result`);
es fehlt nur die Weitergabe von `fuel_full_kg`.

**Files:**
- Modify: `app/poller.py` (`_auto_research_payload`, ~Zeile 1371)
- Test: `tests/test_poller.py`

- [ ] **Step 1: Test** — in `tests/test_poller.py` (nutzt das dortige Poller-Test-Setup; die
  vorhandenen Tests patchen `app.llm.suggest_aircraft_payload`). Ein Test, der eine Suggestion mit
  `fuel_kg` (halb) UND `fuel_full_kg` (voll) mockt, `_auto_research_payload` auslöst und prüft, dass
  die geschriebene Zeile beide Werte hat (`fuel_full_kg` = voll, `fuel_kg` = halb). An das bestehende
  Mock-Muster (`patch("app.llm.suggest_aircraft_payload", return_value={...})`) anlehnen.

- [ ] **Step 2: Test fehlschlägt** (`fuel_full_kg` wird nicht geschrieben → NULL).

- [ ] **Step 3: Implementieren** — den `upsert_payload`-Aufruf in `_auto_research_payload` um eine
  Zeile ergänzen:
```python
                upsert_payload(
                    conn, type_code,
                    mtow_kg=s.get("mtow_kg"), empty_kg=s.get("empty_kg"),
                    fuel_kg=s.get("fuel_kg", s.get("fuel_full_kg")),
                    fuel_full_kg=s.get("fuel_full_kg"),
                    crew_kg=s.get("crew_kg"), source="llm",
                    make_model=s.get("make_model"),
                )
```

- [ ] **Step 4: Tests grün** — `python -m pytest tests/test_poller.py -q`

- [ ] **Step 5: Commit** — `git add app/poller.py tests/test_poller.py` + `git commit -m "feat: Auto-Zuladung speichert max. Tankinhalt mit (Rechenfeld bleibt halb)"`

---

### Task 3: Admin-UI — editierbares Muster-Namensfeld + max. Tankinhalt

**Files:**
- Modify: `app/static/admin.html` (Formularfeld statt Anzeige-`<span>`; 4 JS-Stellen von `.textContent` auf `.value`)

**Interfaces:**
- Consumes: bestehender Endpoint `POST /api/admin/transport/payloads` (nimmt `make_model` bereits entgegen, `main.py:2171`).

- [ ] **Step 1: `<span>` durch Eingabefeld ersetzen**

In `app/static/admin.html` das Formularraster (Zeile 907-921) um ein Feld ergänzen — nach dem Typcode-Feld (nach Zeile 909) einfügen:

```html
            <div class="form-group"><label for="kp-make-model">Muster/Name</label>
              <input type="text" id="kp-make-model" placeholder="z. B. Aerostar 600" /></div>
```

Und den bisherigen Anzeige-`<span>` (Zeile 925) entfernen:

```html
            <span id="kp-make-model" style="color:#8aa0b8;font-size:0.8rem;align-self:center;"></span>
```

- [ ] **Step 2: JS-Zugriffe von `.textContent` auf `.value` umstellen**

Vier Stellen in `app/static/admin.html`:

`kePrefillType` (Zeile 2450):
```javascript
      document.getElementById('kp-make-model').value = p && p.make_model ? p.make_model : '';
```

Suggest-Handler (Zeile 2480):
```javascript
        document.getElementById('kp-make-model').value = s.make_model;
```

Save-Handler, Body (Zeile 2494):
```javascript
        make_model: document.getElementById('kp-make-model').value.trim() || null,
```

Save-Handler, Reset nach Erfolg (Zeile 2501):
```javascript
      document.getElementById('kp-make-model').value = '';
```

- [ ] **Step 3: Backend-Round-Trip absichern (Test)**

In `tests/test_admin_api.py`. **Muster beachten:** diese Tests nutzen KEINEN
`TestClient`, sondern rufen die async-Endpoint-Funktionen direkt mit `FakeReq` +
`asyncio.run` auf und verwenden das dortige `db`-Fixture (siehe `test_admin_api.py:29,43,76`).
`FakeReq(body=...)` liefert einen authentifizierten Request (Admin-Cookie ist Default).

```python
def test_upsert_payload_persists_make_model(db):
    asyncio.run(main.admin_upsert_payload(FakeReq(body={
        "type_code": "AEST", "mtow_kg": 2767, "empty_kg": 1700,
        "fuel_kg": 200, "crew_kg": 85, "make_model": "Aerostar 600",
    })))
    res = asyncio.run(main.admin_transport_payloads(FakeReq()))
    row = next(p for p in res["payloads"] if p["type_code"] == "AEST")
    assert row["make_model"] == "Aerostar 600"
    assert row["source"] == "manual"
```

- [ ] **Step 4: Test laufen lassen**

Run: `pytest tests/test_admin_api.py -k make_model -v`
Expected: PASS.

- [ ] **Step 5: Manuelle UI-Verifikation**

App lokal starten (`uvicorn app.main:app --reload`), Admin → Kutter → Zuladungen: einen Typ „Bearbeiten", Name in „Muster/Name" ändern (z. B. „Aerostar 600"), speichern, Seite neu laden → Name steht in der Tabelle. „KI-Vorschlag" füllt das Feld ebenfalls.

- [ ] **Step 6: Commit**

```bash
git add app/static/admin.html tests/test_admin_api.py
git commit -m "feat: Muster-Name im Admin editierbar (Eingabefeld statt Anzeige)"
```

---

### Task 4: Versionierung + Changelog + Docs

**Files:**
- Modify: `app/CHANGELOG.json` (neuer Eintrag oben)
- Modify: `README.md`, `docs/api.md`, `docs/architecture.md`

**Interfaces:** keine (reine Doku/Metadaten).

- [ ] **Step 1: Changelog-Eintrag**

`app/CHANGELOG.json` oben lesen (aktuelles Schema übernehmen) und einen Eintrag `8.17.0` mit `type: "minor"` ergänzen. Text sinngemäß:
> „Zuladungen der ~120 gängigen Flugzeugtypen kommen jetzt aus einem kuratierten Datensatz (sofort & kostenlos statt Live-Web-Recherche); Web-Recherche nur noch für seltene Muster. Muster-Name im Admin editierbar."

- [ ] **Step 2: Docs aktualisieren**

- `docs/architecture.md`: Abschnitt zu `aircraft_payloads`/Zuladungs-Recherche um den Seed-Schritt (`aircraft_specs.json` → `seed_curated_payloads` in `init_db`) und die Fallback-Rolle des Web-Search ergänzen.
- `docs/api.md`: beim `/api/admin/transport/payloads[/suggest]`-Abschnitt vermerken, dass bekannte Typen vorbefüllt sind (Suggest = Fallback) und `make_model` editierbar ist.
- `README.md`: kurzer Hinweis auf den kuratierten Datensatz.

- [ ] **Step 3: Verifikation gesamter Testlauf**

Run: `pytest tests/ -q`
Expected: PASS (alles grün).

- [ ] **Step 4: Commit + Tag**

```bash
git add app/CHANGELOG.json README.md docs/api.md docs/architecture.md
git commit -m "docs: v8.17.0 — kuratierter Zuladungs-Datensatz + editierbarer Muster-Name"
git tag v8.17.0
```

- [ ] **Step 5: Push (erst nach Nutzer-Bestätigung)**

```bash
git push origin main --follow-tags
```

---

## Hinweise zur Ausführung

- **Task-Reihenfolge:** Task 2 (Loader) sollte praktisch vor/zusammen mit Task 1 Step 5 laufen, weil der Validierungstest `database.load_curated_specs` braucht. Am saubersten: Task 2 Loader-Teil zuerst, dann Task 1 Datensatz, dann Task 2 Seeding-Tests. Beim subagent-getriebenen Vorgehen kann der Reviewer beide Tasks als Paar behandeln.
- **Kein Push ohne Bestätigung** (stehende Regel).
- **`suggest_aircraft_payload` wird bewusst NICHT angefasst** — der Web-Fallback bleibt exakt wie heute.
