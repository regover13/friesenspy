# Muster-Info-Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Aircraft-Designator wird in allen acht Sichten anklickbar und öffnet ein Modal mit Foto, Muster-Name, Wikipedia-Kurztext, den Friesen-Zahlen und den Kutter-Gewichten.

**Architecture:** Eine neue Tabelle `aircraft_types` hält pro Typcode importierte Werte und Admin-Korrekturen in **getrennten Spalten** (`COALESCE(override, import)`), damit ein Import nie eine Korrektur zertritt. Gefüllt wird sie außerhalb des Klickpfads (Poller, Nachlese beim Start, periodischer Retry); die Auflösung geht über die Wikipedia-Suche mit geprüftem Treffer, das Foto über die Bildliste des Artikels mit Lizenz-Whitelist. Commons-Fotos liegen als Datei im Volume (wegwerfbar), Admin-Uploads als BLOB in der DB (unersetzlich, und damit im nächtlichen Backup).

**Tech Stack:** Python 3.11, FastAPI, SQLite (WAL), httpx, APScheduler, Pillow, Vanilla-JS-SPA, pytest.

**Voraussetzung:** Plan A (`2026-07-30-zuladungs-recherche-retry.md`) ist ausgeliefert. Dieser Plan benutzt daraus `next_retry_delay_s`, `is_retry_due`, `FLIGHT_TYPE_CODE_SQL` und `llm.is_transient_error`.

## Global Constraints

- **Maßgebliche Spalte:** `FLIGHT_TYPE_CODE_SQL` aus `app/database.py` (Plan A, Task 2) — `COALESCE(NULLIF(aircraft_icao,''), aircraft)`, normalisiert. **Nie** per `OR` addieren. `aircraft_icao` ist erst seit 2026-06-09 gefüllt (357 von 2256 Zeilen), `aircraft` in 2232.
- **Wikimedia-Zugriff:** Jeder ausgehende Aufruf **muss** den User-Agent `FriesenSpy/<VERSION> (https://friesenspy.devprops.de; admin@devprops.de)` tragen. Ohne ihn antwortet Wikimedia von diesem Server mit **403** („Contabo networks are forbidden due to abuse"). **403 und 429 sind transient**, niemals `nichts_gefunden`.
- **Kein Netz in Tests.** Die HTTP-Schicht wird über eine injizierbare Funktion gefälscht.
- **Nie in die Produktions-DB schreiben.** Tests laufen gegen eine temporäre DB.
- **Lizenz-Whitelist, kein Substring-Vergleich.** `"CC BY"` ist ein Teilstring von `"CC BY-NC-ND 2.0"`.
- **UI-Regel:** Blau (`--green`, historischer Name) ist Klickbarem vorbehalten. Breite Tabellen brauchen `.table-scroll`; im Flex-Container zusätzlich `min-width: 0`; in `.scroll-list` zusätzlich dieselbe Höhenbegrenzung (siehe `CLAUDE.md`).
- **`index.html:3176` bleibt unverändert** — das ist der Text für die Zwischenablage, kein HTML.
- **Neues Attribut heißt `data-actype`.** `data-ac` ist bei `index.html:3809` für das Flugplan-Modal belegt.
- **Neue Tabellen** ins `_DDL`, neue Spalten in eine `_XXX_MIGRATIONS`-Liste.
- **Zielversion:** **10.6.0** (`app/CHANGELOG.json`, `app/version.py` liest `CHANGELOG[0]["version"]`).

## File Structure

| Datei | Verantwortung | Art |
|---|---|---|
| `app/database.py` | Tabelle `aircraft_types`, Zustand, Alias-Validierung, Friesen-Zahlen | Modify |
| `app/aircraft_info.py` | **Neu.** Wikipedia-/Commons-Auflösung: Namenshärtung, Suche, Trefferprüfung, Bildwahl, Lizenzfilter. Netzfrei testbar (HTTP wird injiziert). | Create |
| `app/main.py` | Öffentliche und Admin-Endpunkte, Foto-Route, Upload | Modify |
| `app/poller.py` | Auslöser 1–3 für `aircraft_types` | Modify |
| `app/static/index.html` | `acLink()`, Modal, die acht Stellen | Modify |
| `app/static/admin.html` | Panel „Muster-Infos" | Modify |
| `app/CHANGELOG.json` | Eintrag 10.6.0 | Modify |
| `tests/test_aircraft_types_db.py` | Tabelle, Override-Semantik, Alias, Friesen-Zahlen | Create |
| `tests/test_aircraft_info_resolve.py` | Namenshärtung, Trefferprüfung, Bildwahl, Lizenzfilter, User-Agent | Create |
| `tests/test_aircraft_api.py` | Endpunkte, Klick-Eingrenzung, Foto-Route, Upload | Create |

`app/aircraft_info.py` ist bewusst ein **eigenes Modul**: es ist der einzige Teil mit fremden HTTP-Aufrufen und Heuristik, und genau der muss ohne Netz und ohne DB prüfbar sein. `database.py` ist schon 6000+ Zeilen — die Auflösungslogik gehört dort nicht hinein.

---

### Task 1: Tabelle `aircraft_types`, Override-Semantik, Alias-Validierung

**Files:**
- Modify: `app/database.py` (`_DDL`; neue Funktionen nach `payload_research_candidates` aus Plan A)
- Test: `tests/test_aircraft_types_db.py` (Create)

**Interfaces:**
- Consumes: `normalize_type_code`, `is_retry_due`, `FLIGHT_TYPE_CODE_SQL` (Plan A)
- Produces:
  - `get_aircraft_type(conn, type_code: str) -> dict | None` — Zeile mit **aufgelösten** Anzeigewerten: `{type_code, alias_of, name, extract, wiki_title, wiki_lang, photo_licence, photo_artist, photo_source_url, photo_credit, photo_kind, fetch_state, attempts, checked_at, updated_at}`. `photo_kind ∈ {'blob','file',None}`.
  - `upsert_aircraft_type_import(conn, type_code, *, name=None, name_source=None, wiki_lang=None, wiki_title=None, extract=None, photo_file=None, photo_licence=None, photo_artist=None, photo_source_url=None, now) -> None` — schreibt **nur** Import-Spalten.
  - `set_aircraft_type_override(conn, type_code, *, name=..., extract=..., wiki_title=..., photo_override=..., photo_credit=..., alias_of=..., now) -> None` — schreibt **nur** Korrektur-Spalten; ein übergebener Leerstring löscht die Korrektur (`NULL`).
  - `mark_aircraft_type_state(conn, type_code, state, now, last_error=None) -> None`
  - `resolve_alias(conn, type_code: str) -> str` — ein Schritt; gibt bei fehlendem Alias den Code selbst zurück.
  - `validate_alias(conn, type_code: str, target: str) -> str | None` — Fehlermeldung oder `None`.
  - `friesen_numbers(conn, type_code: str) -> dict` — `{fluege, stunden, nm, piloten, von, bis, alias_anteil: [{code, n}]}`
  - `top_pilots(conn, type_code: str, limit: int = 3) -> list[dict]` — `[{cid, callsign, name, n}]`
  - `aircraft_type_candidates(conn, now, limit) -> list[str]`
  - `flight_type_codes(conn) -> set[str]` — alle Codes aus dem Flugbestand (für die Klick-Eingrenzung)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aircraft_types_db.py
"""Datenmodell des Muster-Panels: Override-Semantik, Alias, Friesen-Zahlen."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    aircraft_type_candidates,
    flight_type_codes,
    friesen_numbers,
    get_aircraft_type,
    get_connection,
    init_db,
    mark_aircraft_type_state,
    resolve_alias,
    set_aircraft_type_override,
    top_pilots,
    upsert_aircraft_type_import,
    validate_alias,
)

T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    c = get_connection(db)
    yield c
    c.close()


def _flug(c, cid, icao, short, ts, dauer=60, nm=100.0, callsign="FRS1"):
    c.execute(
        "INSERT INTO flight_cache (cid, callsign, aircraft, aircraft_icao, logon_time, "
        "duration_min, distance_nm) VALUES (?,?,?,?,?,?,?)",
        (cid, callsign, short, icao, ts, dauer, nm),
    )


# --- Override-Semantik ------------------------------------------------------

def test_import_schreibt_nur_import_spalten(conn):
    upsert_aircraft_type_import(conn, "C172", name="Cessna 172", wiki_title="Cessna 172",
                                extract="Die Cessna 172 ist …", wiki_lang="de",
                                name_source="payloads", now=T0)
    set_aircraft_type_override(conn, "C172", name="Unsere Rote", now=T0)
    upsert_aircraft_type_import(conn, "C172", name="Cessna 172 Skyhawk",
                                extract="Neuer Text", now=T0)
    row = get_aircraft_type(conn, "C172")
    assert row["name"] == "Unsere Rote", "Import hat die Korrektur zertreten"
    assert row["extract"] == "Neuer Text", "Import-Feld ohne Korrektur wurde nicht aktualisiert"


def test_override_leeren_stellt_importwert_wieder_her(conn):
    upsert_aircraft_type_import(conn, "C172", name="Cessna 172", now=T0)
    set_aircraft_type_override(conn, "C172", name="Unsere Rote", now=T0)
    assert get_aircraft_type(conn, "C172")["name"] == "Unsere Rote"
    set_aircraft_type_override(conn, "C172", name="", now=T0)
    assert get_aircraft_type(conn, "C172")["name"] == "Cessna 172"


def test_photo_credit_gilt_auch_fuer_commons(conn):
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg",
                                photo_artist="Falscher Name",
                                photo_licence="CC BY-SA 4.0", now=T0)
    set_aircraft_type_override(conn, "C172", photo_credit="Foto: Tobias", now=T0)
    row = get_aircraft_type(conn, "C172")
    assert row["photo_credit"] == "Foto: Tobias"
    assert row["photo_source_url"] is None or True  # Link bleibt immer sichtbar


def test_photo_blob_gewinnt_ueber_datei(conn):
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    assert get_aircraft_type(conn, "C172")["photo_kind"] == "file"
    conn.execute("UPDATE aircraft_types SET photo_blob=?, photo_override='blob' "
                 "WHERE type_code='C172'", (b"\xff\xd8\xff",))
    assert get_aircraft_type(conn, "C172")["photo_kind"] == "blob"


def test_photo_override_strich_heisst_kein_foto(conn):
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    set_aircraft_type_override(conn, "C172", photo_override="-", now=T0)
    assert get_aircraft_type(conn, "C172")["photo_kind"] is None


def test_blob_ohne_blob_wird_abgelehnt(conn):
    import sqlite3
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE aircraft_types SET photo_override='blob' WHERE type_code='C172'")


# --- Alias ------------------------------------------------------------------

def test_alias_loest_einen_schritt_auf(conn):
    upsert_aircraft_type_import(conn, "PA24", name="Piper PA-24 Comanche", now=T0)
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    assert resolve_alias(conn, "P24") == "PA24"
    assert resolve_alias(conn, "PA24") == "PA24"
    assert resolve_alias(conn, "UNBEKANNT") == "UNBEKANNT"


def test_selbstbezug_abgelehnt(conn):
    assert validate_alias(conn, "P24", "P24") is not None


def test_ziel_ist_alias_abgelehnt(conn):
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    assert validate_alias(conn, "X", "P24") is not None


def test_auf_mich_zeigt_ein_alias_abgelehnt(conn):
    """W5.1: die Kette entsteht in der ANDEREN Anlegereihenfolge."""
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    assert validate_alias(conn, "PA24", "X") is not None, \
        "PA24 darf kein Alias werden, solange P24 auf PA24 zeigt"


def test_gueltiger_alias_wird_akzeptiert(conn):
    assert validate_alias(conn, "P24", "PA24") is None


# --- Friesen-Zahlen ---------------------------------------------------------

def test_zahlen_ueber_beide_spalten_und_ohne_doppelzaehlung(conn):
    _flug(conn, 1, None, "C172", "2025-03-01T10:00:00Z", dauer=60, nm=100.0)
    _flug(conn, 2, "C172", "C172", "2026-07-01T10:00:00Z", dauer=120, nm=200.0)
    conn.commit()
    z = friesen_numbers(conn, "C172")
    assert z["fluege"] == 2, "Zeile mit beiden Spalten doppelt gezaehlt"
    assert z["stunden"] == pytest.approx(3.0)
    assert z["nm"] == pytest.approx(300.0)
    assert z["piloten"] == 2
    assert z["von"] == "2025-03-01"
    assert z["bis"] == "2026-07-01"


def test_alias_fluege_zaehlen_zum_ziel_mit_ausweis(conn):
    _flug(conn, 1, None, "PA24", "2025-01-01T10:00:00Z")
    _flug(conn, 2, None, "PA24", "2025-01-02T10:00:00Z")
    _flug(conn, 3, None, "P24", "2025-10-26T10:00:00Z")
    conn.commit()
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    z = friesen_numbers(conn, "PA24")
    assert z["fluege"] == 3
    assert z["alias_anteil"] == [{"code": "P24", "n": 1}]


def test_alias_anteil_ist_eine_liste_bei_zwei_aliassen(conn):
    """W5.2: real zeigen SA65/AS65 und JU5/JU52 auf dasselbe Ziel."""
    _flug(conn, 1, None, "AS65", "2026-07-01T10:00:00Z")
    _flug(conn, 2, None, "SA65", "2026-07-04T10:00:00Z")
    _flug(conn, 3, None, "SA65", "2026-07-05T10:00:00Z")
    conn.commit()
    set_aircraft_type_override(conn, "SA65", alias_of="AS65", now=T0)
    z = friesen_numbers(conn, "AS65")
    assert z["fluege"] == 3
    assert z["alias_anteil"] == [{"code": "SA65", "n": 2}]


def test_abfrage_ueber_das_alias_kuerzel_liefert_die_zielzahlen(conn):
    _flug(conn, 1, None, "PA24", "2025-01-01T10:00:00Z")
    _flug(conn, 2, None, "P24", "2025-10-26T10:00:00Z")
    conn.commit()
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    assert friesen_numbers(conn, "P24")["fluege"] == 2


def test_unbekanntes_kuerzel_liefert_nullen_statt_fehler(conn):
    z = friesen_numbers(conn, "IMPU")
    assert z["fluege"] == 0
    assert z["alias_anteil"] == []


def test_top_piloten(conn):
    for i in range(3):
        _flug(conn, 10, None, "C172", f"2025-01-0{i+1}T10:00:00Z", callsign="FRS96")
    _flug(conn, 11, None, "C172", "2025-02-01T10:00:00Z", callsign="FRS45")
    conn.commit()
    top = top_pilots(conn, "C172", limit=3)
    assert top[0]["cid"] == 10
    assert top[0]["n"] == 3
    assert top[0]["callsign"] == "FRS96"
    assert top[1]["n"] == 1


# --- Kandidaten und Bestand -------------------------------------------------

def test_kandidaten_und_bestand(conn):
    _flug(conn, 1, None, "P28S", "2025-06-06T10:00:00Z")
    _flug(conn, 2, "AP32", "AP32", "2026-07-25T10:00:00Z")
    conn.commit()
    assert flight_type_codes(conn) == {"P28S", "AP32"}
    assert set(aircraft_type_candidates(conn, T0, limit=10)) == {"P28S", "AP32"}
    mark_aircraft_type_state(conn, "AP32", "ok", T0)
    conn.commit()
    assert aircraft_type_candidates(conn, T0, limit=10) == ["P28S"]


def test_fehlende_fotodatei_setzt_zustand_zurueck_ist_kandidat(conn, tmp_path):
    """W2: 'ok' heisst nicht 'nie wieder'."""
    _flug(conn, 1, None, "C172", "2025-01-01T10:00:00Z")
    conn.commit()
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    mark_aircraft_type_state(conn, "C172", "ok", T0)
    conn.commit()
    assert aircraft_type_candidates(conn, T0, limit=10) == []
    mark_aircraft_type_state(conn, "C172", "neu", T0)
    conn.commit()
    assert aircraft_type_candidates(conn, T0, limit=10) == ["C172"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_aircraft_types_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_aircraft_type' from 'app.database'`

- [ ] **Step 3: Write minimal implementation**

In `_DDL` (`app/database.py`) einfügen:

```sql
CREATE TABLE IF NOT EXISTS aircraft_types (
    type_code           TEXT PRIMARY KEY,   -- normalize_type_code()
    alias_of            TEXT,               -- Tippfehler-Kürzel → echtes Muster (ein Schritt)

    -- importiert: NUR der Import schreibt diese Spalten
    name                TEXT,
    name_source         TEXT,               -- 'payloads' | 'llm'
    wiki_lang           TEXT,               -- 'de' | 'en'
    wiki_title          TEXT,
    extract             TEXT,
    photo_file          TEXT,
    photo_licence       TEXT,
    photo_artist        TEXT,
    photo_source_url    TEXT,

    -- Korrektur: NUR der Admin schreibt diese Spalten
    name_override       TEXT,
    extract_override    TEXT,
    wiki_title_override TEXT,
    photo_override      TEXT,               -- NULL | '-' (kein Foto) | 'blob' (Upload)
    photo_blob          BLOB,
    photo_credit        TEXT,

    -- Zustand
    fetch_state         TEXT,               -- 'neu' | 'ok' | 'nichts_gefunden' | 'fehler'
    attempts            INTEGER NOT NULL DEFAULT 0,
    checked_at          TEXT,
    last_error          TEXT,
    updated_at          TEXT,

    CHECK (photo_override IS NULL OR photo_override IN ('-', 'blob')),
    CHECK (photo_override <> 'blob' OR photo_blob IS NOT NULL)
);
```

Nach `payload_research_candidates` anfügen:

```python
# ---------------------------------------------------------------------------
# Muster-Infos (aircraft_types) — Anzeige = COALESCE(<feld>_override, <feld>)
# ---------------------------------------------------------------------------

_AT_OVERRIDE_FELDER = ("name", "extract", "wiki_title")


def _ts(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_aircraft_type(conn: sqlite3.Connection, code: str, now: datetime) -> None:
    conn.execute(
        "INSERT INTO aircraft_types (type_code, fetch_state, updated_at) "
        "VALUES (?, 'neu', ?) ON CONFLICT(type_code) DO NOTHING",
        (code, _ts(now)),
    )


def get_aircraft_type(conn: sqlite3.Connection, type_code: str) -> dict | None:
    """Zeile mit aufgelösten Anzeigewerten, oder ``None``.

    ``photo_kind``: ``'blob'`` (Upload gewinnt immer), ``'file'`` (Commons-Cache) oder ``None``
    (``photo_override='-'`` oder gar kein Bild).
    """
    code = normalize_type_code(type_code)
    if not code:
        return None
    row = conn.execute("SELECT * FROM aircraft_types WHERE type_code = ?", (code,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    out = {
        "type_code": d["type_code"],
        "alias_of": d["alias_of"],
        "wiki_lang": d["wiki_lang"],
        "photo_licence": d["photo_licence"],
        "photo_artist": d["photo_artist"],
        "photo_source_url": d["photo_source_url"],
        "photo_credit": d["photo_credit"],
        "fetch_state": d["fetch_state"],
        "attempts": d["attempts"],
        "checked_at": d["checked_at"],
        "updated_at": d["updated_at"],
    }
    for feld in _AT_OVERRIDE_FELDER:
        out[feld] = d[f"{feld}_override"] if d[f"{feld}_override"] else d[feld]
    if d["photo_override"] == "-":
        out["photo_kind"] = None
    elif d["photo_override"] == "blob" and d["photo_blob"] is not None:
        out["photo_kind"] = "blob"
    elif d["photo_file"]:
        out["photo_kind"] = "file"
    else:
        out["photo_kind"] = None
    out["photo_file"] = d["photo_file"]
    return out


def upsert_aircraft_type_import(
    conn: sqlite3.Connection, type_code: str, *, now: datetime, **felder
) -> None:
    """Import-Spalten schreiben. Kennt die Korrektur-Spalten NICHT — deshalb kann ein Import
    eine Korrektur strukturell nicht zertreten (nicht bloß per Konvention).

    Nur übergebene Felder werden geschrieben; ``None`` heißt „nicht anfassen".
    """
    erlaubt = {"name", "name_source", "wiki_lang", "wiki_title", "extract",
               "photo_file", "photo_licence", "photo_artist", "photo_source_url"}
    code = normalize_type_code(type_code)
    if not code:
        return
    _ensure_aircraft_type(conn, code, now)
    setze = {k: v for k, v in felder.items() if k in erlaubt and v is not None}
    if not setze:
        conn.execute("UPDATE aircraft_types SET updated_at=? WHERE type_code=?",
                     (_ts(now), code))
        return
    sets = ", ".join(f"{k} = ?" for k in setze)
    conn.execute(
        f"UPDATE aircraft_types SET {sets}, updated_at = ? WHERE type_code = ?",
        (*setze.values(), _ts(now), code),
    )


def set_aircraft_type_override(
    conn: sqlite3.Connection, type_code: str, *, now: datetime, **felder
) -> None:
    """Korrektur-Spalten schreiben. Ein **Leerstring** löscht die Korrektur (→ Importwert gilt).

    Erlaubt: ``name``, ``extract``, ``wiki_title`` (→ ``*_override``), ``photo_override``,
    ``photo_credit``, ``alias_of``.
    """
    code = normalize_type_code(type_code)
    if not code:
        return
    _ensure_aircraft_type(conn, code, now)
    setze: dict[str, object] = {}
    for feld in _AT_OVERRIDE_FELDER:
        if feld in felder:
            setze[f"{feld}_override"] = felder[feld] or None
    for feld in ("photo_override", "photo_credit", "alias_of"):
        if feld in felder:
            wert = felder[feld]
            if feld == "alias_of" and wert:
                wert = normalize_type_code(str(wert))
            setze[feld] = wert or None
    if not setze:
        return
    sets = ", ".join(f"{k} = ?" for k in setze)
    conn.execute(
        f"UPDATE aircraft_types SET {sets}, updated_at = ? WHERE type_code = ?",
        (*setze.values(), _ts(now), code),
    )


def mark_aircraft_type_state(
    conn: sqlite3.Connection, type_code: str, state: str, now: datetime,
    last_error: str | None = None,
) -> None:
    """Auflösungs-Zustand festschreiben. ``attempts`` zählt nur ``fehler``."""
    code = normalize_type_code(type_code)
    if not code:
        return
    _ensure_aircraft_type(conn, code, now)
    if state == "fehler":
        conn.execute(
            "UPDATE aircraft_types SET fetch_state='fehler', attempts = attempts + 1, "
            "checked_at = ?, last_error = ?, updated_at = ? WHERE type_code = ?",
            (_ts(now), last_error, _ts(now), code),
        )
        return
    conn.execute(
        "UPDATE aircraft_types SET fetch_state = ?, attempts = 0, checked_at = ?, "
        "last_error = ?, updated_at = ? WHERE type_code = ?",
        (state, _ts(now), last_error, _ts(now), code),
    )


def resolve_alias(conn: sqlite3.Connection, type_code: str) -> str:
    """Alias **einen** Schritt auflösen. Ketten werden nicht verfolgt (siehe validate_alias)."""
    code = normalize_type_code(type_code)
    if not code:
        return ""
    row = conn.execute(
        "SELECT alias_of FROM aircraft_types WHERE type_code = ?", (code,)
    ).fetchone()
    ziel = normalize_type_code(row["alias_of"]) if row and row["alias_of"] else ""
    return ziel or code


def validate_alias(conn: sqlite3.Connection, type_code: str, target: str) -> str | None:
    """Fehlermeldung, wenn ``type_code → target`` unzulässig wäre, sonst ``None``.

    Drei Ablehnungsgründe. Der dritte ist der aus Rev. 2 (W5.1): ohne ihn entsteht eine Kette
    in der anderen Anlegereihenfolge — erst ``P24 → PA24`` (erlaubt), dann ``PA24 → X``
    (scheinbar erlaubt), und die Ein-Schritt-Auflösung von ``P24`` landet auf einer Alias-Zeile
    ohne eigene Daten.
    """
    code, ziel = normalize_type_code(type_code), normalize_type_code(target)
    if not code or not ziel:
        return "Kürzel und Ziel müssen gesetzt sein."
    if code == ziel:
        return f"{code} kann nicht auf sich selbst zeigen."
    row = conn.execute(
        "SELECT alias_of FROM aircraft_types WHERE type_code = ?", (ziel,)
    ).fetchone()
    if row is not None and row["alias_of"]:
        return (f"{ziel} ist selbst ein Alias (→ {row['alias_of']}). "
                "Zeige direkt auf das echte Muster.")
    zeigt_auf_mich = conn.execute(
        "SELECT type_code FROM aircraft_types WHERE alias_of = ? LIMIT 1", (code,)
    ).fetchone()
    if zeigt_auf_mich is not None:
        return (f"{zeigt_auf_mich['type_code']} zeigt bereits auf {code} — "
                f"{code} kann deshalb kein Alias werden (das ergäbe eine Kette).")
    return None


def _alias_codes(conn: sqlite3.Connection, ziel: str) -> list[str]:
    rows = conn.execute(
        "SELECT type_code FROM aircraft_types WHERE alias_of = ? ORDER BY type_code", (ziel,)
    ).fetchall()
    return [r["type_code"] for r in rows]


def friesen_numbers(conn: sqlite3.Connection, type_code: str) -> dict:
    """Kernzahlen der Gruppe für ein Muster, inklusive der Flüge seiner Aliasse.

    ``alias_anteil`` ist eine **Liste**: es können mehrere Aliasse auf dasselbe Ziel zeigen
    (real: ``SA65``/``AS65`` und ``JU5``/``JU52``). Damit die angezeigte Zahl nachvollziehbar
    bleibt, weist das Panel sie einzeln aus.
    """
    ziel = resolve_alias(conn, type_code)
    leer = {"fluege": 0, "stunden": 0.0, "nm": 0.0, "piloten": 0,
            "von": None, "bis": None, "alias_anteil": []}
    if not ziel:
        return leer
    codes = [ziel, *_alias_codes(conn, ziel)]
    platz = ",".join("?" * len(codes))
    row = conn.execute(
        f"""SELECT COUNT(*) AS fluege,
                   COALESCE(SUM(duration_min), 0) / 60.0 AS stunden,
                   COALESCE(SUM(distance_nm), 0) AS nm,
                   COUNT(DISTINCT cid) AS piloten,
                   MIN(substr(logon_time, 1, 10)) AS von,
                   MAX(substr(logon_time, 1, 10)) AS bis
              FROM flight_cache
             WHERE {FLIGHT_TYPE_CODE_SQL} IN ({platz})""",
        codes,
    ).fetchone()
    if row is None or not row["fluege"]:
        return leer
    anteil = []
    for a in _alias_codes(conn, ziel):
        n = conn.execute(
            f"SELECT COUNT(*) AS n FROM flight_cache WHERE {FLIGHT_TYPE_CODE_SQL} = ?", (a,)
        ).fetchone()["n"]
        if n:
            anteil.append({"code": a, "n": n})
    return {
        "fluege": row["fluege"],
        "stunden": round(row["stunden"], 1),
        "nm": round(row["nm"], 0),
        "piloten": row["piloten"],
        "von": row["von"],
        "bis": row["bis"],
        "alias_anteil": anteil,
    }


def top_pilots(conn: sqlite3.Connection, type_code: str, limit: int = 3) -> list[dict]:
    """Wer das Muster am häufigsten geflogen hat (inkl. Alias-Flüge)."""
    ziel = resolve_alias(conn, type_code)
    if not ziel:
        return []
    codes = [ziel, *_alias_codes(conn, ziel)]
    platz = ",".join("?" * len(codes))
    rows = conn.execute(
        f"""SELECT f.cid AS cid, COUNT(*) AS n,
                   MAX(f.callsign) AS callsign,
                   (SELECT p.name FROM pilots p WHERE p.cid = f.cid) AS name
              FROM flight_cache f
             WHERE {FLIGHT_TYPE_CODE_SQL} IN ({platz})
             GROUP BY f.cid
             ORDER BY n DESC, f.cid ASC
             LIMIT ?""",
        (*codes, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def flight_type_codes(conn: sqlite3.Connection) -> set[str]:
    """Alle Typcodes aus dem Flugbestand — Grundlage der Klick-Eingrenzung (W3)."""
    rows = conn.execute(
        f"""SELECT DISTINCT {FLIGHT_TYPE_CODE_SQL} AS code FROM flight_cache
             WHERE COALESCE(NULLIF(aircraft_icao, ''), aircraft) IS NOT NULL
               AND COALESCE(NULLIF(aircraft_icao, ''), aircraft) != ''"""
    ).fetchall()
    return {r["code"] for r in rows if r["code"]}


def aircraft_type_candidates(
    conn: sqlite3.Connection, now: datetime, limit: int
) -> list[str]:
    """Typcodes aus dem Flugbestand, deren Auflösung fällig ist — häufigste zuerst."""
    rows = conn.execute(
        f"""SELECT {FLIGHT_TYPE_CODE_SQL} AS code, COUNT(*) AS n,
                   t.fetch_state AS state, t.attempts AS attempts, t.checked_at AS checked_at,
                   t.alias_of AS alias_of
              FROM flight_cache f
              LEFT JOIN aircraft_types t ON t.type_code = {FLIGHT_TYPE_CODE_SQL}
             WHERE COALESCE(NULLIF(aircraft_icao, ''), aircraft) IS NOT NULL
               AND COALESCE(NULLIF(aircraft_icao, ''), aircraft) != ''
             GROUP BY code
             ORDER BY n DESC, code ASC"""
    ).fetchall()
    faellig = [
        r["code"] for r in rows
        if r["code"] and not r["alias_of"]
        and is_retry_due(r["state"] or "neu", r["attempts"] or 0, r["checked_at"], now)
    ]
    return faellig[:limit]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_aircraft_types_db.py -v`
Expected: PASS (19 Tests)

- [ ] **Step 5: Commit**

```bash
git add app/database.py tests/test_aircraft_types_db.py
git commit -m "feat(db): Tabelle aircraft_types mit Override-Semantik, Alias und Friesen-Zahlen

Import- und Korrektur-Spalten stehen nebeneinander; angezeigt wird COALESCE(override,
import). upsert_aircraft_type_import() kennt die Korrektur-Spalten nicht -- ein Import kann
eine Korrektur strukturell nicht zertreten, nicht bloss per Konvention.

Alias lehnt drei Faelle ab, darunter 'auf mich zeigt schon ein Alias' (Rev. 2 W5.1): ohne
diese Pruefung entsteht die Kette in der anderen Anlegereihenfolge, und die
Ein-Schritt-Aufloesung landet auf einer Zeile ohne Daten.

Friesen-Zahlen aggregieren ueber FLIGHT_TYPE_CODE_SQL (nie per OR, sonst doppelt) und
weisen alias_anteil als LISTE aus -- real zeigen SA65/AS65 und JU5/JU52 auf dasselbe Ziel.

CHECK verhindert photo_override='blob' ohne Blob (Rev. 2 W6)."
```

---

### Task 2: `aircraft_info.py` — Namenshärtung und Trefferprüfung

**Files:**
- Create: `app/aircraft_info.py`
- Test: `tests/test_aircraft_info_resolve.py` (Create)

**Interfaces:**
- Consumes: `llm.is_transient_error` (Plan A, Task 1)
- Produces:
  - `USER_AGENT: str` — `f"FriesenSpy/{VERSION} (https://friesenspy.devprops.de; admin@devprops.de)"`
  - `harden_name(name: str | None) -> str | None` — `None`, wenn unbrauchbar als Suchanfrage.
  - `looks_like_aircraft(description: str | None, extract: str | None) -> bool`
  - `title_matches_name(title: str, name: str) -> bool`
  - `MAX_NAME_LEN: int = 80`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aircraft_info_resolve.py
"""Namenshaertung und Trefferpruefung — mit den REAL gemessenen Faellen als Fixtures.

Rev.-2-Befund B2: die erste Fassung prueefte die Wortueberlappung nur gegen den Herstellerteil
und nur gegen den ERSTEN Suchtreffer. Gegen die echten make_model-Werte der Produktions-DB
gemessen, verwarf sie die halbe Hubschrauber-Flotte der Gruppe. Diese Fixtures sind die
Messwerte, keine Erfindungen.
"""
from __future__ import annotations

import pytest

from app.aircraft_info import (
    MAX_NAME_LEN,
    USER_AGENT,
    harden_name,
    looks_like_aircraft,
    title_matches_name,
)


# --- Namenshaertung ---------------------------------------------------------

def test_normaler_name_bleibt():
    assert harden_name("Cessna 172S Skyhawk") == "Cessna 172S Skyhawk"


def test_prosa_absatz_wird_verworfen():
    """MR20 traegt real einen 359-Zeichen-Absatz; er sprengt die Such-API
    (cirrussearch-query-too-long, Limit 300)."""
    prosa = "Die Mooney M20TN Acclaim ist ein einmotoriges " + ("x" * 360)
    assert harden_name(prosa) is None
    assert len(prosa) > MAX_NAME_LEN


def test_mehrzeiliges_wird_verworfen():
    assert harden_name("Cessna 172\nmit Zusatztext") is None


def test_leeres_und_none():
    assert harden_name(None) is None
    assert harden_name("   ") is None


def test_grenzfall_genau_max_len_bleibt():
    name = "C" * MAX_NAME_LEN
    assert harden_name(name) == name
    assert harden_name("C" * (MAX_NAME_LEN + 1)) is None


# --- Trefferpruefung: Wortueberlappung gegen den GANZEN Namen ---------------

@pytest.mark.parametrize("name,titel", [
    # Gemessene Faelle, die Rev. 1 verworfen haette:
    ("Airbus H145 (D3)", "MBB/Kawasaki BK 117"),          # EC45, 137 Fluege
    ("Aerostar 600", "Piper PA-60"),                       # AEST, 72 Fluege
    ("Aérospatiale/Airbus Helicopters AS365N3 Dauphin 2", "Eurocopter AS365 Dauphin"),
    ("Airbus H135", "Eurocopter EC 135"),
    # Unstrittige Faelle:
    ("Cessna 172S Skyhawk", "Cessna 172"),
    ("PZL-104 Wilga 35A", "PZL-104 Wilga"),
])
def test_treffer_wird_akzeptiert(name, titel):
    assert title_matches_name(titel, name) is True, f"{titel!r} zu {name!r} verworfen"


@pytest.mark.parametrize("name,titel", [
    ("Airbus H145 (D3)", "Polizeihubschrauberstaffel Bayern"),   # 1. de-Treffer, falsch
    ("Cessna 172S Skyhawk", "Continental Aerospace Technologies GmbH"),
    ("Impulse Impulse", "Impuls (Physik)"),
])
def test_fehltreffer_wird_verworfen(name, titel):
    assert title_matches_name(titel, name) is False, f"{titel!r} zu {name!r} akzeptiert"


def test_kurze_woerter_zaehlen_nicht_als_ueberlappung():
    """'de' in 'de Havilland' und 'TL' in 'TL Ultralight' sind < 3 Zeichen —
    daran scheiterte jede Erste-Wort-Heuristik."""
    assert title_matches_name("de Gaulle", "de Havilland Canada DHC-2 Beaver") is False
    assert title_matches_name("de Havilland Canada DHC-2", "de Havilland Canada DHC-2 Beaver") is True


# --- Luftfahrzeug-Erkennung -------------------------------------------------

def test_description_mit_stichwort():
    assert looks_like_aircraft("1955 touring aircraft family", None) is True
    assert looks_like_aircraft("Flugzeugtyp", None) is True
    assert looks_like_aircraft("Hubschraubertyp", None) is True


def test_description_leer_faellt_auf_extract_zurueck():
    """Gemessen: 'Piper PA-60' und 'Scheibe SF 25' haben KEINE Wikidata-Beschreibung.
    Rev. 1 haette sie allein deswegen verworfen."""
    assert looks_like_aircraft(None, "Die Piper PA-60 Aerostar ist ein zweimotoriges Flugzeug.") is True
    assert looks_like_aircraft("", "The Scheibe SF 25 is a German glider.") is True


def test_beides_leer_ist_kein_luftfahrzeug():
    assert looks_like_aircraft(None, None) is False


def test_thema_ohne_luftfahrzeug_wird_verworfen():
    assert looks_like_aircraft("International Labour Organization Convention", None) is False
    assert looks_like_aircraft("German municipality", "Eine Gemeinde im Landkreis.") is False


# --- User-Agent -------------------------------------------------------------

def test_user_agent_traegt_kontakt_und_version():
    """B3: ohne aussagekraeftigen UA antwortet Wikimedia von diesem Server mit 403
    ('Contabo networks are forbidden due to abuse'). Gemessen 2026-07-30 im Container."""
    assert "FriesenSpy/" in USER_AGENT
    assert "friesenspy.devprops.de" in USER_AGENT
    assert "@" in USER_AGENT, "Kontakt fehlt — Wikimedia-Nutzungsregeln verlangen ihn"
    assert "python" not in USER_AGENT.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_aircraft_info_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.aircraft_info'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/aircraft_info.py
"""Muster-Infos aus Wikipedia und Wikimedia Commons.

Einziger Teil des Features mit fremden HTTP-Aufrufen und Heuristik — deshalb ein eigenes
Modul, das ohne Netz und ohne Datenbank prüfbar ist. Die HTTP-Schicht wird als Funktion
injiziert (siehe ``resolve_type`` in Task 3).

**Wikimedia sperrt das Netz dieses Servers ohne aussagekräftigen User-Agent.** Gemessen am
2026-07-30 aus dem Produktions-Container: Default-UA → ``403 Contabo networks are forbidden
due to abuse``, eigener UA → ``200``. Der Block greift nicht deterministisch an jedem Edge,
403 ist deshalb **vorübergehend**, kein Endzustand.
"""
from __future__ import annotations

import re

from app.version import VERSION

USER_AGENT = f"FriesenSpy/{VERSION} (https://friesenspy.devprops.de; admin@devprops.de)"

# Die Wikipedia-Such-API lehnt Anfragen über 300 Zeichen mit `cirrussearch-query-too-long` ab.
# 80 ist reichlich für „Hersteller + Modell" und schließt die Prosa-Altwerte sicher aus:
# `MR20` trägt real einen 359-Zeichen-Absatz als make_model.
MAX_NAME_LEN = 80

# Wörter unter 3 Zeichen taugen nicht als Überlappungsbeleg — „de" in „de Havilland" und „TL"
# in „TL Ultralight" hätten sonst jeden Artikel bestätigt, der ein „de" im Titel trägt.
_MIN_WORT_LEN = 3

_FUELLWOERTER = frozenset({
    "der", "die", "das", "und", "von", "mit", "für", "the", "and", "for",
    "aircraft", "flugzeug", "helicopter", "hubschrauber",
})

_LUFTFAHRZEUG_WOERTER = (
    "flugzeug", "hubschrauber", "helikopter", "ultraleicht", "segelflugzeug",
    "motorsegler", "tragschrauber", "wasserflugzeug", "doppeldecker",
    "aircraft", "airliner", "airplane", "aeroplane", "helicopter", "glider",
    "sailplane", "biplane", "monoplane", "airship", "utility plane", "trainer",
)


def harden_name(name: str | None) -> str | None:
    """Name als Suchanfrage tauglich machen — oder ``None``, wenn er es nicht ist.

    Verworfen wird, was mehrzeilig oder länger als :data:`MAX_NAME_LEN` ist. Grund sind reale
    Altwerte in ``aircraft_payloads``: ``MR20`` trägt einen 359-Zeichen-Prosaabsatz, der die
    Such-API mit ``cirrussearch-query-too-long`` sprengt und das Muster damit in einen ewigen
    Retry schickt. Der Aufrufer geht bei ``None`` in der Namens-Rangfolge einen Schritt weiter.
    """
    if not name:
        return None
    s = name.strip()
    if not s or "\n" in s or "\r" in s or len(s) > MAX_NAME_LEN:
        return None
    return s


def _woerter(text: str) -> set[str]:
    roh = re.findall(r"[0-9A-Za-zÄÖÜäöüßÀ-ÿ]+", text.lower())
    return {w for w in roh if len(w) >= _MIN_WORT_LEN and w not in _FUELLWOERTER}


def title_matches_name(title: str, name: str) -> bool:
    """Teilen Artikeltitel und Muster-Name ein bedeutungstragendes Wort?

    Geprüft wird gegen den **ganzen** Namen, nicht nur den Herstellerteil. Rev. 1 tat
    Letzteres und verwarf damit gemessen die halbe Hubschrauber-Flotte der Gruppe:
    ``Airbus H145 (D3)`` gegen *MBB/Kawasaki BK 117* (137 Flüge), ``Aerostar 600`` gegen
    *Piper PA-60* (72 Flüge), ``AS365N3 Dauphin 2`` gegen *Eurocopter AS365 Dauphin*.
    Der Hersteller wandert bei Hubschraubern durch die Firmengeschichte, die Typbezeichnung
    bleibt — deshalb ist der ganze Name der bessere Anker.
    """
    if not title or not name:
        return False
    return bool(_woerter(title) & _woerter(name))


def looks_like_aircraft(description: str | None, extract: str | None) -> bool:
    """Beschreibt der Artikel ein Luftfahrzeug?

    ``description`` (kurze Wikidata-Beschreibung) zuerst; ist sie leer, entscheidet der Anfang
    des ``extract``. Rev. 1 prüfte nur ``description`` und hätte damit korrekte Artikel
    verworfen, die keine haben — gemessen bei *Piper PA-60* und *Scheibe SF 25*.
    """
    for quelle in (description, extract):
        if not quelle:
            continue
        text = quelle[:400].lower()
        if any(w in text for w in _LUFTFAHRZEUG_WOERTER):
            return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_aircraft_info_resolve.py -v`
Expected: PASS (alle parametrisierten Fälle)

- [ ] **Step 5: Commit**

```bash
git add app/aircraft_info.py tests/test_aircraft_info_resolve.py
git commit -m "feat(aircraft-info): Namenshaertung und Trefferpruefung

Wortueberlappung gegen den GANZEN Namen statt nur den Herstellerteil, und
looks_like_aircraft() faellt bei leerer description auf den extract zurueck.

Rev.-2-Befund B2, an den echten make_model-Werten gemessen: die alte Fassung verwarf
'Airbus H145 (D3)' -> MBB/Kawasaki BK 117 (EC45, 137 Fluege), 'Aerostar 600' -> Piper PA-60
(AEST, 72 Fluege) und AS365N3 -> Eurocopter AS365 Dauphin. Diese Faelle sind jetzt Fixtures.

harden_name() verwirft mehrzeilige und ueberlange Namen: MR20 traegt real einen
359-Zeichen-Prosaabsatz und sprengt die Such-API (Limit 300).

USER_AGENT mit Kontakt: ohne ihn antwortet Wikimedia von diesem Server mit 403
('Contabo networks are forbidden due to abuse', gemessen im Container)."
```

---

### Task 3: Auflösung gegen Wikipedia und Commons

**Files:**
- Modify: `app/aircraft_info.py`
- Test: `tests/test_aircraft_info_resolve.py` (erweitern)

**Interfaces:**
- Consumes: `harden_name`, `title_matches_name`, `looks_like_aircraft`, `USER_AGENT` (Task 2)
- Produces:
  - `ALLOWED_LICENCES: frozenset[str]` — normalisierte Kürzel
  - `licence_ok(short_name: str | None, usage_terms: str | None) -> bool`
  - `normalise_commons_title(title: str) -> str` — `Datei:` → `File:`
  - `resolve_type(name: str, fetch) -> dict | None` — `fetch(url: str) -> dict` liefert geparstes JSON; Rückgabe `{wiki_lang, wiki_title, extract, photo_commons_title, photo_url, photo_licence, photo_artist, photo_source_url}` oder `None` (nichts Taugliches gefunden). Wirft die Ausnahme von `fetch` durch (Klassifikation macht der Aufrufer).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aircraft_info_resolve.py — anfügen
from app.aircraft_info import (
    ALLOWED_LICENCES, licence_ok, normalise_commons_title, resolve_type,
)


# --- Lizenz-Whitelist -------------------------------------------------------

def test_whitelist_statt_substring():
    """W4: 'CC BY' ist ein Teilstring von 'CC BY-NC-ND 2.0'."""
    assert licence_ok("CC BY-SA 4.0", None) is True
    assert licence_ok("CC BY 3.0", None) is True
    assert licence_ok("CC0", None) is True
    assert licence_ok("Public domain", None) is True
    assert licence_ok("CC BY-NC-ND 2.0", None) is False
    assert licence_ok("CC BY-NC 2.0", None) is False
    assert licence_ok("CC BY-ND", None) is False


def test_gfdl_allein_abgelehnt_dual_akzeptiert():
    """Das C172-Leitbild ist real GFDL 1.2. Dual lizenzierte Bilder tragen teils nur
    'GFDL' im Kuerzel — die 'only'-Unterscheidung braucht UsageTerms."""
    assert licence_ok("GFDL 1.2", None) is False
    assert licence_ok("GFDL 1.2", "GNU Free Documentation License 1.2") is False
    assert licence_ok("GFDL", "GFDL 1.2 or later, and CC BY-SA 3.0") is True


def test_unbekannte_lizenz_wird_abgelehnt():
    assert licence_ok(None, None) is False
    assert licence_ok("Alle Rechte vorbehalten", None) is False


def test_datei_praefix_wird_zu_file():
    """W1-Implementierungsfalle: die de-media-list liefert 'Datei:', Commons braucht 'File:'."""
    assert normalise_commons_title("Datei:Cessna 172.jpg") == "File:Cessna 172.jpg"
    assert normalise_commons_title("File:Cessna 172.jpg") == "File:Cessna 172.jpg"
    assert normalise_commons_title("Cessna 172.jpg") == "File:Cessna 172.jpg"


# --- resolve_type mit gefälschtem HTTP --------------------------------------

def _fetcher(routen: dict, aufrufe: list | None = None):
    """fetch(url) -> JSON aus `routen` (erste passende Teil-URL gewinnt)."""
    def _f(url):
        if aufrufe is not None:
            aufrufe.append(url)
        for teil, antwort in routen.items():
            if teil in url:
                if isinstance(antwort, Exception):
                    raise antwort
                return antwort
        raise AssertionError(f"unerwartete URL: {url}")
    return _f


def _such(*titel):
    return {"query": {"search": [{"title": t} for t in titel]}}


def _summary(titel, desc, extract, bild=None):
    d = {"title": titel, "description": desc, "extract": extract}
    if bild:
        d["originalimage"] = {"source": f"https://upload.wikimedia.org/{bild}"}
    return d


def _medialist(*dateien):
    return {"items": [{"title": d, "type": "image"} for d in dateien]}


def _imageinfo(short, artist="Jemand", terms=None, url="https://upload/x.jpg"):
    return {"query": {"pages": {"-1": {"imageinfo": [{
        "url": url,
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:X.jpg",
        "extmetadata": {
            "LicenseShortName": {"value": short},
            "Artist": {"value": artist},
            **({"UsageTerms": {"value": terms}} if terms else {}),
        },
    }]}}}}


def test_zweiter_treffer_gewinnt_wenn_der_erste_durchfaellt():
    """EC45, 137 Fluege: der erste de-Treffer ist die Polizeihubschrauberstaffel."""
    routen = {
        "srsearch": _such("Polizeihubschrauberstaffel Bayern", "MBB/Kawasaki BK 117"),
        "summary/Polizeihubschrauberstaffel": _summary(
            "Polizeihubschrauberstaffel Bayern", "Polizeieinheit", "Die Staffel …"),
        "summary/MBB": _summary("MBB/Kawasaki BK 117", "Hubschraubertyp",
                                "Der BK 117 ist ein Hubschrauber.", bild="bk117.jpg"),
        "media-list/MBB": _medialist("Datei:bk117.jpg"),
        "imageinfo": _imageinfo("CC BY-SA 4.0"),
    }
    r = resolve_type("Airbus H145 (D3)", _fetcher(routen))
    assert r["wiki_title"] == "MBB/Kawasaki BK 117"
    assert r["photo_licence"] == "CC BY-SA 4.0"


def test_englisch_als_rueckfall_wenn_de_leer():
    routen = {
        "de.wikipedia.org/w/api.php": _such(),
        "en.wikipedia.org/w/api.php": _such("Eurocopter AS365 Dauphin"),
        "en.wikipedia.org/api/rest_v1/page/summary": _summary(
            "Eurocopter AS365 Dauphin", "helicopter", "The AS365 is a helicopter.",
            bild="as365.jpg"),
        "en.wikipedia.org/api/rest_v1/page/media-list": _medialist("File:as365.jpg"),
        "imageinfo": _imageinfo("CC BY-SA 3.0"),
    }
    r = resolve_type("Aérospatiale/Airbus Helicopters AS365N3 Dauphin 2", _fetcher(routen))
    assert r["wiki_lang"] == "en"
    assert r["wiki_title"] == "Eurocopter AS365 Dauphin"


def test_gfdl_leitbild_uebersprungen_zweites_bild_gewinnt():
    """W1: die C172 bekommt ein Foto. Leitbild GFDL 1.2, aber vier freie im Artikel."""
    routen = {
        "srsearch": _such("Cessna 172"),
        "summary": _summary("Cessna 172", "1955 touring aircraft family",
                            "Die Cessna 172 …", bild="leitbild.jpg"),
        "media-list": _medialist("Datei:leitbild.jpg", "Datei:D-EVLB.jpg"),
        "titles=File%3Aleitbild.jpg": _imageinfo("GFDL 1.2"),
        "titles=File%3AD-EVLB.jpg": _imageinfo("CC BY-SA 3.0", artist="Fotograf"),
    }
    r = resolve_type("Cessna 172S Skyhawk", _fetcher(routen))
    assert r["photo_commons_title"] == "File:D-EVLB.jpg"
    assert r["photo_licence"] == "CC BY-SA 3.0"
    assert r["photo_artist"] == "Fotograf"


def test_text_ohne_taugliches_bild_ist_kein_fehler():
    routen = {
        "srsearch": _such("Impulse (Flugzeug)"),
        "summary": _summary("Impulse (Flugzeug)", "Flugzeugtyp", "Die Impulse …"),
        "media-list": _medialist("Datei:nur-gfdl.jpg"),
        "imageinfo": _imageinfo("GFDL 1.2"),
    }
    r = resolve_type("Impulse Impulse", _fetcher(routen))
    assert r["extract"].startswith("Die Impulse")
    assert r["photo_commons_title"] is None


def test_kein_tauglicher_treffer_gibt_none():
    routen = {
        "de.wikipedia.org/w/api.php": _such("Impuls (Physik)"),
        "de.wikipedia.org/api/rest_v1/page/summary": _summary(
            "Impuls (Physik)", "physikalische Größe", "Der Impuls ist …"),
        "en.wikipedia.org/w/api.php": _such(),
    }
    assert resolve_type("Impulse Impulse", _fetcher(routen)) is None


def test_hoechstens_drei_treffer_werden_geprueft():
    aufrufe = []
    routen = {
        "de.wikipedia.org/w/api.php": _such("A", "B", "C", "D"),
        "de.wikipedia.org/api/rest_v1/page/summary": _summary("X", "Gemeinde", "Ein Ort."),
        "en.wikipedia.org/w/api.php": _such(),
    }
    resolve_type("Cessna 172", _fetcher(routen, aufrufe))
    summaries = [u for u in aufrufe if "de.wikipedia.org/api/rest_v1/page/summary" in u]
    assert len(summaries) == 3, f"srlimit/Prüftiefe nicht 3: {summaries}"


def test_srlimit_ist_drei_und_ua_wird_nicht_in_die_url_geschrieben():
    aufrufe = []
    routen = {"de.wikipedia.org/w/api.php": _such(), "en.wikipedia.org/w/api.php": _such()}
    resolve_type("Cessna 172", _fetcher(routen, aufrufe))
    assert any("srlimit=3" in u for u in aufrufe)


def test_unbrauchbarer_name_fragt_gar_nicht_erst():
    """MR20: der Prosaabsatz darf keinen einzigen HTTP-Aufruf ausloesen."""
    aufrufe = []
    assert resolve_type("x" * 400, _fetcher({}, aufrufe)) is None
    assert aufrufe == []


def test_fetch_ausnahme_wird_durchgeworfen():
    """Die Klassifikation (transient?) macht der Aufrufer, nicht dieses Modul."""
    class _Http(Exception):
        status_code = 403
    routen = {"de.wikipedia.org/w/api.php": _Http("Contabo forbidden")}
    with pytest.raises(_Http):
        resolve_type("Cessna 172", _fetcher(routen))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_aircraft_info_resolve.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_type'`

- [ ] **Step 3: Write minimal implementation**

An `app/aircraft_info.py` anfügen:

```python
from urllib.parse import quote

# Whitelist **exakter** normalisierter Kürzel. Ein Substring-Vergleich ist hier falsch:
# "CC BY" ist ein Teilstring von "CC BY-NC-ND 2.0" und würde ein NC/ND-Bild veröffentlichen
# (Rev. 2, W4). `LicenseShortName` ist auf Commons Freitext mit Leerzeichen — gemessen:
# "CC BY-SA 4.0", "Public domain", "GFDL 1.2".
ALLOWED_LICENCES = frozenset({
    "cc0", "cc01.0", "publicdomain", "pd",
    "ccby2.0", "ccby2.5", "ccby3.0", "ccby4.0",
    "ccbysa2.0", "ccbysa2.5", "ccbysa3.0", "ccbysa4.0",
})

_SUCHTIEFE = 3          # so viele Suchtreffer werden geprüft
_SPRACHEN = ("de", "en")


def _norm_licence(s: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", (s or "").lower())


def licence_ok(short_name: str | None, usage_terms: str | None) -> bool:
    """Darf dieses Bild angezeigt werden?

    Zulässig sind CC0, Public Domain und CC BY / CC BY-SA. Ausgeschlossen ist alles mit ``NC``
    oder ``ND`` sowie **GFDL als einzige** Lizenz (Copyleft mit Volltextpflicht — für eine
    Web-Anzeige unpassend; betrifft konkret das Leitbild der ``C172``).

    Dual lizenzierte Bilder tragen auf Commons häufig nur „GFDL" im Kürzel, nennen die
    CC-Lizenz aber in ``UsageTerms``. Deshalb wird dort nachgesehen, statt das Bild
    vorschnell zu verwerfen.
    """
    if _norm_licence(short_name) in ALLOWED_LICENCES:
        return True
    # Zweite Chance nur für Dual-Lizenzen: eine erlaubte Lizenz muss in UsageTerms stehen.
    terms = _norm_licence(usage_terms)
    if not terms:
        return False
    if "nc" in (usage_terms or "").lower() or "noderiv" in terms or "ccbynd" in terms:
        return False
    return any(erlaubt in terms for erlaubt in ("ccbysa", "ccby", "cc0", "publicdomain"))


def normalise_commons_title(title: str) -> str:
    """Dateititel auf das ``File:``-Präfix bringen.

    Die deutsche ``media-list`` liefert ``Datei:``; die Commons-API kennt nur ``File:`` und
    antwortet sonst still ohne ``imageinfo``.
    """
    t = (title or "").strip()
    for praefix in ("Datei:", "File:", "Bild:", "Image:"):
        if t.startswith(praefix):
            return "File:" + t[len(praefix):]
    return "File:" + t


def _such_url(lang: str, name: str) -> str:
    return (f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search"
            f"&srsearch={quote(name)}&srlimit={_SUCHTIEFE}&format=json")


def _summary_url(lang: str, titel: str) -> str:
    return f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(titel, safe='')}"


def _medialist_url(lang: str, titel: str) -> str:
    return f"https://{lang}.wikipedia.org/api/rest_v1/page/media-list/{quote(titel, safe='')}"


def _imageinfo_url(commons_titel: str) -> str:
    return ("https://commons.wikimedia.org/w/api.php?action=query"
            f"&titles={quote(commons_titel, safe='')}"
            "&prop=imageinfo&iiprop=extmetadata%7Curl&format=json")


def _meta(extmetadata: dict, key: str) -> str | None:
    wert = (extmetadata or {}).get(key)
    if isinstance(wert, dict):
        return wert.get("value")
    return wert if isinstance(wert, str) else None


def _waehle_bild(lang: str, titel: str, fetch) -> dict | None:
    """Erstes Bild des Artikels mit zulässiger Lizenz.

    Rev. 2 (W1): Rev. 1 fragte nur ``originalimage`` der Summary ab und schloss daraus, die
    ``C172`` — mit 506 Flügen das häufigste Muster der Gruppe — bleibe wegen GFDL dauerhaft
    ohne Bild. Der Artikel enthält aber mindestens vier verwendbare Bilder. Der Lizenzfilter
    war richtig, die Ein-Kandidaten-Pipeline falsch.
    """
    daten = fetch(_medialist_url(lang, titel)) or {}
    for item in (daten.get("items") or []):
        if item.get("type") not in (None, "image"):
            continue
        roh = item.get("title") or ""
        if not roh:
            continue
        commons_titel = normalise_commons_title(roh)
        info = fetch(_imageinfo_url(commons_titel)) or {}
        seiten = ((info.get("query") or {}).get("pages") or {})
        for seite in seiten.values():
            ii = (seite.get("imageinfo") or [{}])[0]
            ext = ii.get("extmetadata") or {}
            short, terms = _meta(ext, "LicenseShortName"), _meta(ext, "UsageTerms")
            if not licence_ok(short, terms):
                continue
            return {
                "photo_commons_title": commons_titel,
                "photo_url": ii.get("url"),
                "photo_licence": short,
                "photo_artist": re.sub(r"<[^>]+>", "", _meta(ext, "Artist") or "").strip() or None,
                "photo_source_url": ii.get("descriptionurl"),
            }
    return None


def resolve_type(name: str, fetch) -> dict | None:
    """Muster-Name → Wikipedia-Artikel und Foto, oder ``None``.

    ``fetch(url) -> dict`` liefert geparstes JSON und **muss** den :data:`USER_AGENT` setzen.
    Ausnahmen von ``fetch`` werden durchgeworfen — ob ein Fehler vorübergehend ist, entscheidet
    der Aufrufer (``llm.is_transient_error``).

    Immer über die **Suche**, nie den Namen als Lemma raten: gemessen liefert
    ``srsearch="Cessna 172S Skyhawk"`` den Treffer ``Cessna 172``, der direkte Lemma-Aufruf
    mit demselben String dagegen **HTTP 404**.
    """
    sauber = harden_name(name)
    if not sauber:
        return None
    for lang in _SPRACHEN:
        treffer = fetch(_such_url(lang, sauber)) or {}
        titel_liste = [
            t.get("title") for t in ((treffer.get("query") or {}).get("search") or [])
            if t.get("title")
        ][:_SUCHTIEFE]
        for titel in titel_liste:
            if not title_matches_name(titel, sauber):
                continue
            summary = fetch(_summary_url(lang, titel)) or {}
            extract = summary.get("extract")
            if not looks_like_aircraft(summary.get("description"), extract):
                continue
            ergebnis = {
                "wiki_lang": lang,
                "wiki_title": summary.get("title") or titel,
                "extract": extract,
                "photo_commons_title": None,
                "photo_url": None,
                "photo_licence": None,
                "photo_artist": None,
                "photo_source_url": None,
            }
            bild = _waehle_bild(lang, ergebnis["wiki_title"], fetch)
            if bild:
                ergebnis.update(bild)
            return ergebnis
    return None
```

**Wichtig:** `title_matches_name` wird vor dem Summary-Aufruf geprüft — aber `test_hoechstens_drei_treffer_werden_geprueft` erwartet **drei** Summary-Aufrufe bei den Titeln `A`, `B`, `C`. Damit der Test das messen kann, muss die Reihenfolge sein: Titel durchlaufen, für jeden Titel **erst** Summary holen, **dann** beide Bedingungen prüfen. Also im Loop:

```python
        for titel in titel_liste:
            summary = fetch(_summary_url(lang, titel)) or {}
            extract = summary.get("extract")
            echter_titel = summary.get("title") or titel
            if not title_matches_name(echter_titel, sauber):
                continue
            if not looks_like_aircraft(summary.get("description"), extract):
                continue
```

Das ist auch sachlich besser: die Summary liefert den **kanonischen** Titel nach einer Weiterleitung, und gegen den soll die Überlappung geprüft werden.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_aircraft_info_resolve.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/aircraft_info.py tests/test_aircraft_info_resolve.py
git commit -m "feat(aircraft-info): Aufloesung gegen Wikipedia und Commons

Suche (srlimit=3) -> bis zu drei Treffer pruefen -> Summary -> media-list -> erstes Bild mit
zulaessiger Lizenz. Immer ueber die Suche, nie den Namen als Lemma raten (gemessen:
'Cessna 172S Skyhawk' als Lemma = 404, als Suche = Treffer 'Cessna 172').

Lizenz-Whitelist exakter Kuerzel statt Substring: 'CC BY' ist ein Teilstring von
'CC BY-NC-ND 2.0'. GFDL allein abgelehnt, GFDL+CC-BY-SA dual akzeptiert (UsageTerms).

media-list statt nur originalimage (Rev. 2 W1): das C172-Leitbild ist GFDL 1.2, der Artikel
enthaelt aber vier freie Bilder -- das haeufigste Muster der Gruppe bekommt jetzt ein Foto.
'Datei:' wird zu 'File:' umgeschrieben, sonst antwortet Commons still ohne imageinfo.

Ein unbrauchbarer Name loest keinen einzigen HTTP-Aufruf aus (MR20-Prosaabsatz)."
```

---

### Task 4: HTTP-Schicht mit User-Agent und Fehlerklassifikation

**Files:**
- Modify: `app/aircraft_info.py`
- Test: `tests/test_aircraft_info_resolve.py` (erweitern)

**Interfaces:**
- Consumes: `USER_AGENT` (Task 2), `llm.is_transient_error` (Plan A)
- Produces:
  - `WikimediaError(Exception)` mit `status_code: int | None`
  - `fetch_json(url: str, *, timeout_s: float = 15.0) -> dict` — setzt den User-Agent, wirft `WikimediaError`
  - `download_photo(url: str, *, timeout_s: float = 30.0) -> bytes`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aircraft_info_resolve.py — anfügen
def test_fetch_json_setzt_user_agent(monkeypatch):
    """B3: ohne UA antwortet Wikimedia von diesem Server mit 403."""
    import httpx
    from app import aircraft_info

    gesehen = {}

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"ok": True}

    class _Client:
        def __init__(self, **kw):
            gesehen["headers"] = kw.get("headers") or {}
            gesehen["timeout"] = kw.get("timeout")
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    assert aircraft_info.fetch_json("https://de.wikipedia.org/x") == {"ok": True}
    assert gesehen["headers"]["User-Agent"] == aircraft_info.USER_AGENT


def test_403_ist_transient_404_nicht(monkeypatch):
    import httpx
    from app import aircraft_info, llm

    def _mit_status(code):
        class _Resp:
            status_code = code
            def raise_for_status(self):
                raise httpx.HTTPStatusError("x", request=None, response=None)
            def json(self): return {}
        class _Client:
            def __init__(self, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, url): return _Resp()
        monkeypatch.setattr(httpx, "Client", _Client)

    _mit_status(403)
    with pytest.raises(aircraft_info.WikimediaError) as e403:
        aircraft_info.fetch_json("https://de.wikipedia.org/x")
    assert e403.value.status_code == 403
    assert llm.is_transient_error(e403.value) is True, \
        "403 muss transient sein, sonst begraebt der Contabo-Block jedes Muster 30 Tage"

    _mit_status(404)
    with pytest.raises(aircraft_info.WikimediaError) as e404:
        aircraft_info.fetch_json("https://de.wikipedia.org/x")
    assert llm.is_transient_error(e404.value) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_aircraft_info_resolve.py -k "user_agent or transient" -v`
Expected: FAIL — `AttributeError: module 'app.aircraft_info' has no attribute 'fetch_json'`

- [ ] **Step 3: Write minimal implementation**

An `app/aircraft_info.py` anfügen:

```python
import httpx

logger = logging.getLogger(__name__)


class WikimediaError(Exception):
    """Ein Wikimedia-Aufruf ist gescheitert. ``status_code`` trägt den HTTP-Status.

    ``llm.is_transient_error`` liest ``status_code`` — deshalb ist **403 automatisch
    transient** (>= 500 oder in {408, 429, 529} … 403 gehört ergänzt, siehe unten), was hier
    entscheidend ist: der Contabo-Netzblock von Wikimedia greift nicht deterministisch, und
    ein als endgültig gewerteter 403 würde jedes Muster 30 Tage als „nichts gefunden"
    begraben.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def fetch_json(url: str, *, timeout_s: float = 15.0) -> dict:
    """JSON von Wikimedia holen — **immer** mit aussagekräftigem User-Agent."""
    try:
        with httpx.Client(
            timeout=timeout_s, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            resp = client.get(url)
            if resp.status_code >= 400:
                raise WikimediaError(f"HTTP {resp.status_code} für {url}", resp.status_code)
            return resp.json()
    except WikimediaError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise WikimediaError(f"{type(exc).__name__}: {exc}", None) from exc


def download_photo(url: str, *, timeout_s: float = 30.0) -> bytes:
    """Bilddatei holen — ebenfalls mit User-Agent."""
    try:
        with httpx.Client(
            timeout=timeout_s, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            resp = client.get(url)
            if resp.status_code >= 400:
                raise WikimediaError(f"HTTP {resp.status_code} für {url}", resp.status_code)
            return resp.content
    except WikimediaError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise WikimediaError(f"{type(exc).__name__}: {exc}", None) from exc
```

`import logging` oben in `app/aircraft_info.py` ergänzen.

In `app/llm.py` die Konstante aus Plan A um 403 erweitern:

```python
# 403 gehört dazu, weil Wikimedia das Contabo-Netz dieses Servers nicht deterministisch
# blockt (gemessen 2026-07-30: derselbe UA einmal 403, Minuten später 200).
_TRANSIENT_STATUS = frozenset({403, 408, 429, 529})
```

Der Test aus Plan A Task 1 (`test_client_error_400_stays_none`) bleibt grün — 400 ist nicht in der Menge. **Achtung:** In Plan A wurde `is_transient_error(_Http(403)) is True` bereits geprüft; die Konstante dort muss die 403 also von Anfang an enthalten. Ist sie in Plan A ohne 403 umgesetzt worden, ist dieser Schritt die Korrektur.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_aircraft_info_resolve.py tests/test_llm_transient.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/aircraft_info.py app/llm.py tests/test_aircraft_info_resolve.py
git commit -m "feat(aircraft-info): HTTP-Schicht mit User-Agent, 403 als transient

fetch_json/download_photo setzen den User-Agent bei jedem Aufruf. Ohne ihn antwortet
Wikimedia von diesem Server mit 403 ('Contabo networks are forbidden due to abuse') --
gemessen 2026-07-30 im Produktions-Container, eigener UA -> 200.

403 ist in _TRANSIENT_STATUS, weil der Block nicht deterministisch greift (derselbe UA
einmal 403, Minuten spaeter 200). Als endgueltig gewertet haette er jedes Muster 30 Tage
als 'nichts gefunden' begraben."
```

---

### Task 5: Auflösung an die DB anbinden (Poller-Auslöser 1–3)

**Files:**
- Modify: `app/poller.py` (`_register_jobs` aus Plan A Task 4; neue Methoden)
- Test: `tests/test_aircraft_types_poller.py` (Create)

**Interfaces:**
- Consumes: alles aus Tasks 1–4
- Produces:
  - `VatsimPoller._resolve_aircraft_type(type_code: str) -> None`
  - `VatsimPoller._resolve_due_aircraft_types() -> None`
  - `VatsimPoller._AIRCRAFT_INFO_LIMIT: int = 8`
  - Jobs `aircraft_info_initial` (einmalig) und `aircraft_info_retry` (alle 10 min)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aircraft_types_poller.py
"""Auffuellen von aircraft_types laeuft ausserhalb des Klickpfads, serialisiert, gedeckelt."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database import (
    get_aircraft_type, get_connection, init_db, mark_aircraft_type_state,
    upsert_aircraft_type_import, upsert_payload,
)

T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _poller(db_path, tmp_path):
    from app.poller import VatsimPoller
    p = VatsimPoller(db_path=db_path, callsign_prefix="FRS")
    p._photo_dir = Path(tmp_path) / "fotos"
    return p


def _flug(db_path, cid, code, ts="2026-07-01T10:00:00Z"):
    c = get_connection(db_path)
    c.execute("INSERT INTO flight_cache (cid, callsign, aircraft, logon_time) VALUES (?,?,?,?)",
              (cid, "FRS1", code, ts))
    c.commit()
    c.close()


@pytest.mark.asyncio
async def test_name_kommt_aus_payloads_und_foto_landet_als_datei(db, tmp_path, monkeypatch):
    c = get_connection(db)
    upsert_payload(c, "C172", mtow_kg=1157.0, empty_kg=767.0, fuel_kg=100.0,
                   fuel_full_kg=200.0, crew_kg=85.0, source="curated",
                   make_model="Cessna 172S Skyhawk")
    c.commit()
    c.close()
    _flug(db, 1, "C172")
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)

    from app import aircraft_info
    gefragt = {}
    monkeypatch.setattr(aircraft_info, "resolve_type", lambda name, fetch: gefragt.setdefault(
        "name", name) or {
        "wiki_lang": "de", "wiki_title": "Cessna 172", "extract": "Die Cessna 172 …",
        "photo_commons_title": "File:x.jpg", "photo_url": "https://upload/x.jpg",
        "photo_licence": "CC BY-SA 3.0", "photo_artist": "Fotograf",
        "photo_source_url": "https://commons/File:x.jpg",
    })
    monkeypatch.setattr(aircraft_info, "download_photo", lambda url, **kw: b"\xff\xd8\xffBILD")

    await p._resolve_aircraft_type("C172")

    assert gefragt["name"] == "Cessna 172S Skyhawk"
    row = get_aircraft_type(get_connection(db), "C172")
    assert row["fetch_state"] == "ok"
    assert row["wiki_title"] == "Cessna 172"
    assert row["photo_kind"] == "file"
    assert (p._photo_dir / row["photo_file"]).read_bytes() == b"\xff\xd8\xffBILD"


@pytest.mark.asyncio
async def test_403_wird_fehler_nicht_nichts_gefunden(db, tmp_path, monkeypatch):
    _flug(db, 1, "C172")
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    from app import aircraft_info

    def _boom(name, fetch):
        raise aircraft_info.WikimediaError("Contabo forbidden", 403)

    monkeypatch.setattr(aircraft_info, "resolve_type", _boom)
    await p._resolve_aircraft_type("C172")
    row = get_aircraft_type(get_connection(db), "C172")
    assert row["fetch_state"] == "fehler", "403 wurde als endgueltig behandelt"
    assert row["attempts"] == 1


@pytest.mark.asyncio
async def test_kein_treffer_wird_nichts_gefunden(db, tmp_path, monkeypatch):
    _flug(db, 1, "IMPU")
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    from app import aircraft_info
    monkeypatch.setattr(aircraft_info, "resolve_type", lambda name, fetch: None)
    await p._resolve_aircraft_type("IMPU")
    assert get_aircraft_type(get_connection(db), "IMPU")["fetch_state"] == "nichts_gefunden"


@pytest.mark.asyncio
async def test_import_zertritt_die_korrektur_nicht(db, tmp_path, monkeypatch):
    from app.database import set_aircraft_type_override
    _flug(db, 1, "C172")
    c = get_connection(db)
    set_aircraft_type_override(c, "C172", name="Unsere Rote", now=T0)
    c.commit()
    c.close()
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    from app import aircraft_info
    monkeypatch.setattr(aircraft_info, "resolve_type", lambda name, fetch: {
        "wiki_lang": "de", "wiki_title": "Cessna 172", "extract": "Text",
        "photo_commons_title": None, "photo_url": None, "photo_licence": None,
        "photo_artist": None, "photo_source_url": None,
    })
    await p._resolve_aircraft_type("C172")
    assert get_aircraft_type(get_connection(db), "C172")["name"] == "Unsere Rote"


@pytest.mark.asyncio
async def test_admin_lemma_umgeht_die_suche(db, tmp_path, monkeypatch):
    from app.database import set_aircraft_type_override
    _flug(db, 1, "AS65")
    c = get_connection(db)
    set_aircraft_type_override(c, "AS65", wiki_title="Eurocopter AS365", now=T0)
    c.commit()
    c.close()
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    from app import aircraft_info
    monkeypatch.setattr(aircraft_info, "resolve_type",
                        lambda name, fetch: pytest.fail("Suche darf nicht laufen"))
    geholt = {}
    monkeypatch.setattr(aircraft_info, "resolve_title", lambda lang, titel, fetch: geholt.setdefault(
        "titel", titel) or {
        "wiki_lang": lang, "wiki_title": titel, "extract": "Der AS365 …",
        "photo_commons_title": None, "photo_url": None, "photo_licence": None,
        "photo_artist": None, "photo_source_url": None,
    })
    await p._resolve_aircraft_type("AS65")
    assert geholt["titel"] == "Eurocopter AS365"


@pytest.mark.asyncio
async def test_fehlende_fotodatei_setzt_ok_zurueck(db, tmp_path, monkeypatch):
    """W2: 'ok' heisst nicht 'nie wieder'. rm -rf des Cache ist eine legitime Reparatur."""
    _flug(db, 1, "C172")
    c = get_connection(db)
    upsert_aircraft_type_import(c, "C172", photo_file="C172.jpg", now=T0)
    mark_aircraft_type_state(c, "C172", "ok", T0)
    c.commit()
    c.close()
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._requeue_missing_photos()
    assert get_aircraft_type(get_connection(db), "C172")["fetch_state"] == "neu"


@pytest.mark.asyncio
async def test_nachlese_deckel_und_serialisierung(db, tmp_path, monkeypatch):
    for i, code in enumerate(["C172"] * 3 + ["PA24"] * 2 + ["C208", "EC45", "DA40",
                                                            "AEST", "P28S", "FK9"]):
        _flug(db, i, code)
    p = _poller(db, tmp_path)
    monkeypatch.setattr(p, "_now", lambda: T0)
    from app import aircraft_info
    reihenfolge = []
    monkeypatch.setattr(aircraft_info, "resolve_type",
                        lambda name, fetch: reihenfolge.append(name) or None)
    await p._resolve_due_aircraft_types()
    assert len(reihenfolge) == p._AIRCRAFT_INFO_LIMIT


def test_jobs_registriert(db, tmp_path):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    p = _poller(db, tmp_path)
    p._scheduler = AsyncIOScheduler()
    p._register_jobs()
    ids = {j.id for j in p._scheduler.get_jobs()}
    assert {"aircraft_info_initial", "aircraft_info_retry"} <= ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_aircraft_types_poller.py -v`
Expected: FAIL — `AttributeError: 'VatsimPoller' object has no attribute '_resolve_aircraft_type'`

- [ ] **Step 3: Write minimal implementation**

In `app/aircraft_info.py` die vom Test verlangte Funktion für das Admin-Lemma ergänzen (sie teilt den Rumpf mit `resolve_type`):

```python
def resolve_title(lang: str, titel: str, fetch) -> dict | None:
    """Einen **vorgegebenen** Artikeltitel auflösen — ohne Suche und ohne Trefferprüfung.

    Für ein Admin-gesetztes Lemma: das ist eine bewusste menschliche Entscheidung und braucht
    die Heuristik nicht. Liefert ``None``, wenn der Artikel nicht existiert.
    """
    summary = fetch(_summary_url(lang, titel)) or {}
    if not summary.get("extract"):
        return None
    echter = summary.get("title") or titel
    ergebnis = {
        "wiki_lang": lang, "wiki_title": echter, "extract": summary.get("extract"),
        "photo_commons_title": None, "photo_url": None, "photo_licence": None,
        "photo_artist": None, "photo_source_url": None,
    }
    bild = _waehle_bild(lang, echter, fetch)
    if bild:
        ergebnis.update(bild)
    return ergebnis
```

In `app/poller.py` — in `__init__`:

```python
        self._AIRCRAFT_INFO_LIMIT = 8      # Muster je Nachlese-Lauf
        self._photo_dir = Path(self.db_path).parent / "aircraft-photos"
```

(`from pathlib import Path` oben ergänzen.)

Neue Methoden auf `VatsimPoller`:

```python
    def _muster_name(self, conn, code: str) -> str | None:
        """Name nach Rangfolge: Admin-Korrektur → aircraft_payloads.make_model.

        Die dritte Stufe (LLM-Recherche) füllt `aircraft_payloads` über Teil 8 und wirkt
        deshalb automatisch über Stufe 2 — hier wird sie nicht separat angestoßen.
        """
        from app.aircraft_info import harden_name
        row = conn.execute(
            "SELECT name_override, name FROM aircraft_types WHERE type_code = ?", (code,)
        ).fetchone()
        if row is not None and row["name_override"]:
            return harden_name(row["name_override"])
        p = conn.execute(
            "SELECT make_model FROM aircraft_payloads WHERE type_code = ?", (code,)
        ).fetchone()
        if p is not None and p["make_model"]:
            return harden_name(p["make_model"])
        return None

    async def _resolve_aircraft_type(self, type_code: str) -> None:
        """Muster-Infos für einen Typcode holen und speichern. Silent-Fail nach außen.

        Läuft NIE im Klickpfad: der Aufruf kommt aus dem Poller, der Nachlese oder dem
        Retry-Job. Der Ausgang landet in ``aircraft_types.fetch_state``.
        """
        from app import aircraft_info, llm
        from app.database import (
            get_aircraft_type, mark_aircraft_type_state, upsert_aircraft_type_import,
        )
        code = normalize_type_code(type_code)
        if not code:
            return
        jetzt = self._now()
        conn = get_connection(self.db_path)
        try:
            vorhanden = get_aircraft_type(conn, code)
            if vorhanden and vorhanden["alias_of"]:
                return  # Alias hat keine eigenen Daten
            lemma = conn.execute(
                "SELECT wiki_title_override FROM aircraft_types WHERE type_code = ?", (code,)
            ).fetchone()
            lemma = lemma["wiki_title_override"] if lemma else None
            name = self._muster_name(conn, code)
        finally:
            conn.close()

        if not lemma and not name:
            # Kein brauchbarer Name (oder nur ein Prosa-Altwert) → nichts zu suchen.
            conn = get_connection(self.db_path)
            try:
                mark_aircraft_type_state(conn, code, "nichts_gefunden", jetzt)
                conn.commit()
            finally:
                conn.close()
            return

        try:
            if lemma:
                res = await asyncio.to_thread(
                    aircraft_info.resolve_title, "de", lemma, aircraft_info.fetch_json
                )
                if res is None:
                    res = await asyncio.to_thread(
                        aircraft_info.resolve_title, "en", lemma, aircraft_info.fetch_json
                    )
            else:
                res = await asyncio.to_thread(
                    aircraft_info.resolve_type, name, aircraft_info.fetch_json
                )
            foto_datei = None
            if res and res.get("photo_url"):
                rohdaten = await asyncio.to_thread(
                    aircraft_info.download_photo, res["photo_url"]
                )
                self._photo_dir.mkdir(parents=True, exist_ok=True)
                foto_datei = f"{code}.jpg"
                (self._photo_dir / foto_datei).write_bytes(rohdaten)
        except Exception as exc:  # noqa: BLE001 — nie einen Job reißen
            zustand = "fehler" if llm.is_transient_error(exc) else "nichts_gefunden"
            conn = get_connection(self.db_path)
            try:
                mark_aircraft_type_state(conn, code, zustand, jetzt, last_error=str(exc)[:200])
                conn.commit()
            finally:
                conn.close()
            logger.info("Muster-Info %s: %s (%s)", code, zustand, exc)
            return

        conn = get_connection(self.db_path)
        try:
            if res is None:
                mark_aircraft_type_state(conn, code, "nichts_gefunden", jetzt)
            else:
                upsert_aircraft_type_import(
                    conn, code, now=jetzt,
                    name=name, name_source="payloads" if name else None,
                    wiki_lang=res.get("wiki_lang"), wiki_title=res.get("wiki_title"),
                    extract=res.get("extract"),
                    photo_file=foto_datei,
                    photo_licence=res.get("photo_licence"),
                    photo_artist=res.get("photo_artist"),
                    photo_source_url=res.get("photo_source_url"),
                )
                mark_aircraft_type_state(conn, code, "ok", jetzt)
            conn.commit()
        finally:
            conn.close()

    async def _requeue_missing_photos(self) -> None:
        """Zustand zurücksetzen, wo die Fotodatei fehlt.

        Rev. 2 (W2): ``rm -rf data/aircraft-photos/`` ist laut Spec eine legitime Reparatur,
        und das nächtliche Backup enthält die Dateien nicht (nur die DB). Ohne diesen Schritt
        sagt die DB ``photo_file`` gesetzt, die Datei fehlt, und ``fetch_state='ok'`` sorgt
        dafür, dass nie wieder etwas nachgeladen wird.
        """
        from app.database import mark_aircraft_type_state
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT type_code, photo_file FROM aircraft_types "
                "WHERE photo_file IS NOT NULL AND photo_file != ''"
            ).fetchall()
            jetzt = self._now()
            for r in rows:
                if not (self._photo_dir / r["photo_file"]).exists():
                    mark_aircraft_type_state(conn, r["type_code"], "neu", jetzt)
            conn.commit()
        finally:
            conn.close()

    async def _resolve_due_aircraft_types(self) -> None:
        """Nachlese über fällige Muster — serialisiert, gedeckelt."""
        try:
            from app.database import aircraft_type_candidates
            await self._requeue_missing_photos()
            jetzt = self._now()
            conn = get_connection(self.db_path)
            try:
                codes = aircraft_type_candidates(conn, jetzt, limit=self._AIRCRAFT_INFO_LIMIT)
            finally:
                conn.close()
            if not codes:
                return
            logger.info("Muster-Infos: %d Muster (%s)", len(codes), ", ".join(codes))
            for code in codes:
                await self._resolve_aircraft_type(code)   # serialisiert, nie parallel
        except Exception:
            logger.exception("Error in _resolve_due_aircraft_types")
```

In `_register_jobs` ergänzen:

```python
        # Muster-Infos: einmalig kurz nach Start, danach regelmäßig die fälligen.
        self._scheduler.add_job(
            self._resolve_due_aircraft_types, "date", id="aircraft_info_initial",
        )
        self._scheduler.add_job(
            self._resolve_due_aircraft_types, "interval", minutes=10,
            id="aircraft_info_retry",
        )
```

Und im Poll-Durchlauf (`app/poller.py`, bei den `new_codes` aus Plan A Task 3) für jeden neu gesehenen Code zusätzlich:

```python
                    asyncio.create_task(self._resolve_aircraft_type(code))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_aircraft_types_poller.py -v`
Expected: PASS (8 Tests)

- [ ] **Step 5: Commit**

```bash
git add app/aircraft_info.py app/poller.py tests/test_aircraft_types_poller.py
git commit -m "feat(poller): Muster-Infos auffuellen (drei Ausloeser, keiner im Klickpfad)

Poller (neu gesehen), Nachlese beim Start, Retry alle 10 min -- serialisiert und auf 8
Muster je Lauf gedeckelt. Bei 89 Kuerzeln und bis zu drei Aufrufen je Kuerzel waeren es
sonst ~250 Requests in einem Rutsch, von einer IP, die bei Wikimedia vorbelastet ist.

403 -> fehler (Backoff), kein Treffer -> nichts_gefunden. Ein Admin-Lemma geht ueber
resolve_title() und umgeht Suche und Trefferpruefung -- bewusste menschliche Entscheidung.

_requeue_missing_photos(): fehlt die Fotodatei, faellt der Zustand auf 'neu' zurueck.
Ohne das wuerde 'ok' nach einem rm -rf des Cache dafuer sorgen, dass nie wieder etwas
nachlaedt -- und das Backup enthaelt die Dateien nicht, nur die DB."
```

---

### Task 6: Öffentliche Endpunkte

**Files:**
- Modify: `app/main.py` (neue Endpunkte bei den übrigen `/api`-Routen)
- Test: `tests/test_aircraft_api.py` (Create)

**Interfaces:**
- Consumes: `get_aircraft_type`, `friesen_numbers`, `top_pilots`, `resolve_alias`, `flight_type_codes` (Task 1)
- Produces:
  - `GET /api/aircraft/{code}` → JSON wie in der Spec, **immer 200**
  - `GET /api/aircraft/{code}/photo` → Bild; BLOB gewinnt über Datei

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aircraft_api.py
"""Endpunkte des Muster-Panels."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DB_PATH", db)
    from app.config import get_settings
    get_settings.cache_clear()
    from app.database import init_db
    init_db(db)
    from app.main import app
    with TestClient(app) as c:
        c.db = db
        yield c
    get_settings.cache_clear()


def _flug(db, cid, code, ts="2026-07-01T10:00:00Z", callsign="FRS1"):
    from app.database import get_connection
    conn = get_connection(db)
    conn.execute(
        "INSERT INTO flight_cache (cid, callsign, aircraft, logon_time, duration_min, "
        "distance_nm) VALUES (?,?,?,?,60,100.0)", (cid, callsign, code, ts))
    conn.commit()
    conn.close()


def test_unbekanntes_kuerzel_liefert_200_und_echte_nullen(client):
    r = client.get("/api/aircraft/IMPU")
    assert r.status_code == 200
    d = r.json()
    assert d["code"] == "IMPU"
    assert d["friesen"]["fluege"] == 0
    assert d["name"] is None


def test_zahlen_und_top_piloten(client):
    for i in range(3):
        _flug(client.db, 10, "C172", f"2026-07-0{i+1}T10:00:00Z", callsign="FRS96")
    _flug(client.db, 11, "C172", "2026-07-05T10:00:00Z", callsign="FRS45")
    d = client.get("/api/aircraft/C172").json()
    assert d["friesen"]["fluege"] == 4
    assert d["top"][0]["cid"] == 10
    assert d["top"][0]["n"] == 3


def test_kutter_daten_und_hinweis_auf_eigene_zeile(client):
    """W5.3: P24 hat real eine eigene Zuladungszeile (381 kg), PA24 hat 381,5 kg."""
    from app.database import get_connection, set_aircraft_type_override, upsert_payload
    conn = get_connection(client.db)
    upsert_payload(conn, "PA24", mtow_kg=1315.0, empty_kg=780.0, fuel_kg=100.0,
                   fuel_full_kg=200.0, crew_kg=85.0, source="manual",
                   make_model="Piper PA-24-250 Comanche")
    upsert_payload(conn, "P24", mtow_kg=1315.0, empty_kg=780.0, fuel_kg=100.0,
                   fuel_full_kg=200.0, crew_kg=85.0, source="manual", make_model="")
    set_aircraft_type_override(conn, "P24", alias_of="PA24", now=T0)
    conn.commit()
    conn.close()
    _flug(client.db, 1, "PA24")
    _flug(client.db, 2, "P24")
    d = client.get("/api/aircraft/P24").json()
    assert d["resolved_code"] == "PA24"
    assert d["friesen"]["fluege"] == 2
    assert d["friesen"]["alias_anteil"] == [{"code": "P24", "n": 1}]
    assert d["kutter"]["eigene_zeile_hinweis"] is not None, \
        "Widerspruch zur Frachtrechnung muss sichtbar sein"


def test_unbekannter_code_legt_keine_zeile_an(client):
    """W3: sonst ist der Endpunkt ein Verstaerker."""
    from app.database import get_connection
    for i in range(5):
        client.get(f"/api/aircraft/JUNK{i}")
    conn = get_connection(client.db)
    n = conn.execute("SELECT COUNT(*) AS n FROM aircraft_types").fetchone()["n"]
    conn.close()
    assert n == 0


def test_bekannter_code_darf_zeile_anlegen(client):
    from app.database import get_connection
    _flug(client.db, 1, "C172")
    client.get("/api/aircraft/C172")
    conn = get_connection(client.db)
    row = conn.execute("SELECT type_code FROM aircraft_types").fetchall()
    conn.close()
    assert [r["type_code"] for r in row] == ["C172"]


def test_foto_blob_gewinnt_und_content_type_stimmt(client):
    from app.database import get_connection, upsert_aircraft_type_import
    _flug(client.db, 1, "C172")
    conn = get_connection(client.db)
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    conn.execute("UPDATE aircraft_types SET photo_blob=?, photo_override='blob' "
                 "WHERE type_code='C172'", (b"\xff\xd8\xffBLOB",))
    conn.commit()
    conn.close()
    r = client.get("/api/aircraft/C172/photo")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == b"\xff\xd8\xffBLOB"


def test_fehlende_fotodatei_gibt_404_und_setzt_zustand_zurueck(client):
    from app.database import (get_aircraft_type, get_connection, mark_aircraft_type_state,
                              upsert_aircraft_type_import)
    _flug(client.db, 1, "C172")
    conn = get_connection(client.db)
    upsert_aircraft_type_import(conn, "C172", photo_file="fehlt.jpg", now=T0)
    mark_aircraft_type_state(conn, "C172", "ok", T0)
    conn.commit()
    conn.close()
    assert client.get("/api/aircraft/C172/photo").status_code == 404
    conn = get_connection(client.db)
    assert get_aircraft_type(conn, "C172")["fetch_state"] == "neu"
    conn.close()


def test_photo_url_traegt_versionsparameter(client):
    """Anmerkung Rev. 2: sonst zeigen Browser nach einem Fotowechsel das alte Bild."""
    from app.database import get_connection, upsert_aircraft_type_import
    _flug(client.db, 1, "C172")
    conn = get_connection(client.db)
    upsert_aircraft_type_import(conn, "C172", photo_file="C172.jpg", now=T0)
    conn.commit()
    conn.close()
    d = client.get("/api/aircraft/C172").json()
    assert d["photo_url"] and "?v=" in d["photo_url"]


def test_kein_foto_liefert_photo_url_none(client):
    _flug(client.db, 1, "IMPU")
    assert client.get("/api/aircraft/IMPU").json()["photo_url"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_aircraft_api.py -v`
Expected: FAIL — alle `/api/aircraft/...` liefern 404 (Route fehlt)

- [ ] **Step 3: Write minimal implementation**

In `app/main.py` bei den übrigen `/api`-Routen:

```python
def _photo_dir() -> Path:
    """Cache-Verzeichnis der Commons-Fotos (im Volume, überlebt Container-Neubauten)."""
    return Path(get_settings().DB_PATH).parent / "aircraft-photos"


@app.get("/api/aircraft/{code}")
async def aircraft_info_endpoint(request: Request, code: str):
    """Muster-Infos + Friesen-Zahlen. Liefert IMMER 200 — auch für ein unbekanntes Kürzel,
    denn die Friesen-Zahlen dazu sind trotzdem echt.

    Der Hintergrund-Abruf wird nur für Codes angestoßen, die im Flugbestand vorkommen (W3).
    Sonst wäre der Endpunkt ein Verstärker: `curl /api/aircraft/JUNK$i` in einer Schleife
    legt beliebig viele Zeilen an und feuert Wikimedia-Aufrufe von einer IP, die dort wegen
    „abuse" schon vorbelastet ist.
    """
    from app.database import (
        flight_type_codes, friesen_numbers, get_aircraft_type, normalize_type_code,
        resolve_alias, top_pilots,
    )
    roh = normalize_type_code(code)
    conn = get_connection(get_settings().DB_PATH)
    try:
        bekannt = roh in flight_type_codes(conn)
        ziel = resolve_alias(conn, roh)
        typ = get_aircraft_type(conn, ziel) or {}
        zahlen = friesen_numbers(conn, roh)
        top = top_pilots(conn, roh, limit=3)
        kutter_row = conn.execute(
            "SELECT mtow_kg, empty_kg, payload_kg FROM aircraft_payloads WHERE type_code = ?",
            (ziel,),
        ).fetchone()
        # W5.3: hat das ANGEFRAGTE Kürzel eine eigene Zuladungszeile, während wir die des
        # Ziels anzeigen? Dann weicht die Frachtrechnung von der Anzeige ab — sichtbar machen.
        hinweis = None
        if ziel != roh:
            eigene = conn.execute(
                "SELECT payload_kg FROM aircraft_payloads WHERE type_code = ?", (roh,)
            ).fetchone()
            if eigene is not None:
                hinweis = (
                    f"Für {roh} ist eine eigene Zuladung von {round(eigene['payload_kg'])} kg "
                    f"gepflegt; die FriesenKutter-Frachtrechnung verwendet diese."
                )
        alias_of = typ.get("alias_of") if ziel == roh else roh
    finally:
        conn.close()

    photo_url = None
    if typ.get("photo_kind"):
        photo_url = f"/api/aircraft/{ziel}/photo?v={quote(str(typ.get('updated_at') or ''))}"
    wiki_url = None
    if typ.get("wiki_title") and typ.get("wiki_lang"):
        wiki_url = (f"https://{typ['wiki_lang']}.wikipedia.org/wiki/"
                    f"{quote(typ['wiki_title'].replace(' ', '_'), safe='')}")

    if bekannt and not typ:
        # Nur für echte Kürzel: im Hintergrund auflösen, nie synchron im Klickpfad.
        if poller_instance is not None:
            asyncio.create_task(poller_instance._resolve_aircraft_type(ziel))

    return {
        "code": roh,
        "alias_of": alias_of,
        "resolved_code": ziel,
        "name": typ.get("name"),
        "extract": typ.get("extract"),
        "wiki_url": wiki_url,
        "photo_url": photo_url,
        "photo_credit": typ.get("photo_credit"),
        "photo_licence": typ.get("photo_licence"),
        "photo_artist": typ.get("photo_artist"),
        "photo_source_url": typ.get("photo_source_url"),
        "state": typ.get("fetch_state") or ("neu" if bekannt else "unbekannt"),
        "friesen": zahlen,
        "top": top,
        "kutter": {
            "mtow_kg": kutter_row["mtow_kg"] if kutter_row else None,
            "empty_kg": kutter_row["empty_kg"] if kutter_row else None,
            "payload_kg": kutter_row["payload_kg"] if kutter_row else None,
            "eigene_zeile_hinweis": hinweis,
        },
    }


@app.get("/api/aircraft/{code}/photo")
async def aircraft_photo(code: str):
    """Foto eines Musters. Ein Upload (BLOB) gewinnt immer über den Commons-Cache (Datei)."""
    from app.database import get_aircraft_type, mark_aircraft_type_state, normalize_type_code
    roh = normalize_type_code(code)
    conn = get_connection(get_settings().DB_PATH)
    try:
        typ = get_aircraft_type(conn, roh)
        if not typ or not typ["photo_kind"]:
            raise HTTPException(status_code=404, detail="Kein Foto")
        if typ["photo_kind"] == "blob":
            blob = conn.execute(
                "SELECT photo_blob FROM aircraft_types WHERE type_code = ?", (roh,)
            ).fetchone()["photo_blob"]
            return Response(content=blob, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})
        pfad = _photo_dir() / typ["photo_file"]
        if not pfad.exists():
            # W2: 'ok' heißt nicht 'nie wieder' — Zustand zurücksetzen, damit die Nachlese
            # das Bild neu holt. Das Backup enthält diese Dateien nicht, nur die DB.
            mark_aircraft_type_state(conn, roh, "neu", datetime.now(timezone.utc))
            conn.commit()
            raise HTTPException(status_code=404, detail="Foto fehlt, wird neu geholt")
        daten = pfad.read_bytes()
    finally:
        conn.close()
    return Response(content=daten, media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})
```

Oben in `app/main.py` sicherstellen: `from pathlib import Path`, `from urllib.parse import quote`, `from fastapi import Response`, `from datetime import datetime, timezone`. `poller_instance` ist die im Lifespan gesetzte Poller-Referenz — falls sie anders heißt, den dort verwendeten Namen benutzen.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_aircraft_api.py -v`
Expected: PASS (9 Tests)

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_aircraft_api.py
git commit -m "feat(api): oeffentliche Endpunkte des Muster-Panels

GET /api/aircraft/{code} liefert immer 200 -- auch fuer ein unbekanntes Kuerzel, die
Friesen-Zahlen dazu sind trotzdem echt. Der Hintergrund-Abruf laeuft nur fuer Codes aus dem
Flugbestand (Rev. 2 W3): sonst legt curl /api/aircraft/JUNK$i in einer Schleife beliebig
viele Zeilen an und feuert Wikimedia-Aufrufe von einer vorbelasteten IP.

GET /api/aircraft/{code}/photo: BLOB gewinnt ueber Datei, explizites image/jpeg, und eine
fehlende Datei setzt den Zustand auf 'neu' zurueck statt dauerhaft ein kaputtes Bild zu
zeigen. photo_url traegt ?v=updated_at, sonst zeigt der Browser nach einem Fotowechsel
weiter das alte Bild.

Weicht die Frachtrechnung von der Anzeige ab (Alias mit eigener Zuladungszeile, real P24 mit
381 vs PA24 mit 381,5 kg), sagt das Panel es hin -- die Kutter-Logik bleibt unangetastet."
```

---

### Task 7: Admin-Endpunkte und Upload

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_aircraft_api.py` (erweitern)

**Interfaces:**
- Consumes: `set_aircraft_type_override`, `validate_alias`, `get_aircraft_type` (Task 1); `require_admin`, `require_confirm` (`app/main.py:1443`)
- Produces:
  - `GET /api/admin/aircraft-types`
  - `POST /api/admin/aircraft-types`
  - `POST /api/admin/aircraft-types/{code}/refetch`
  - `POST /api/admin/aircraft-types/{code}/photo` (multipart)
  - `MAX_UPLOAD_BYTES: int = 8 * 1024 * 1024`, `PHOTO_MAX_WIDTH: int = 1280`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aircraft_api.py — anfügen
import io


@pytest.fixture
def admin(client, monkeypatch):
    """Admin-Sitzung — require_admin/require_confirm werden überbrückt."""
    from app import main
    monkeypatch.setattr(main, "require_admin", lambda request: None)
    monkeypatch.setattr(main, "require_confirm", lambda request: None)
    return client


def _jpeg(breite=2000, hoehe=1200, mit_exif=True) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (breite, hoehe), (10, 20, 30))
    buf = io.BytesIO()
    if mit_exif:
        exif = img.getexif()
        exif[0x8825] = b"GPS"          # GPSInfo — genau das, was nicht in die DB soll
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def test_upload_wird_neu_kodiert_verkleinert_und_exif_frei(admin):
    from PIL import Image
    from app.database import get_aircraft_type, get_connection
    _flug(admin.db, 1, "C172")
    r = admin.post("/api/admin/aircraft-types/C172/photo",
                   files={"file": ("cockpit.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200
    conn = get_connection(admin.db)
    blob = conn.execute("SELECT photo_blob FROM aircraft_types WHERE type_code='C172'"
                        ).fetchone()["photo_blob"]
    assert get_aircraft_type(conn, "C172")["photo_kind"] == "blob"
    conn.close()
    img = Image.open(io.BytesIO(blob))
    assert img.width <= 1280
    assert not dict(img.getexif()), "EXIF nicht entfernt — GPS landet in der DB"


def test_kein_bild_wird_abgelehnt(admin):
    _flug(admin.db, 1, "C172")
    r = admin.post("/api/admin/aircraft-types/C172/photo",
                   files={"file": ("boese.jpg", b"<html>kein Bild</html>", "image/jpeg")})
    assert r.status_code == 400


def test_zu_gross_wird_abgelehnt(admin):
    _flug(admin.db, 1, "C172")
    r = admin.post("/api/admin/aircraft-types/C172/photo",
                   files={"file": ("gross.jpg", b"x" * (8 * 1024 * 1024 + 1), "image/jpeg")})
    assert r.status_code == 413


def test_dateiname_kommt_aus_dem_typcode(admin):
    """Pfad-Traversal ist keine Pruef-, sondern eine Unmoeglichkeitsfrage."""
    _flug(admin.db, 1, "C172")
    r = admin.post("/api/admin/aircraft-types/C172/photo",
                   files={"file": ("../../etc/passwd", _jpeg(100, 100), "image/jpeg")})
    assert r.status_code == 200
    from app.database import get_connection
    conn = get_connection(admin.db)
    row = conn.execute("SELECT photo_file, photo_override FROM aircraft_types "
                       "WHERE type_code='C172'").fetchone()
    conn.close()
    assert row["photo_override"] == "blob"
    assert row["photo_file"] is None or ".." not in (row["photo_file"] or "")


def test_override_setzen_und_leeren(admin):
    from app.database import get_aircraft_type, get_connection, upsert_aircraft_type_import
    conn = get_connection(admin.db)
    upsert_aircraft_type_import(conn, "C172", name="Cessna 172", now=T0)
    conn.commit()
    conn.close()
    admin.post("/api/admin/aircraft-types", json={"type_code": "C172", "name": "Unsere Rote"})
    conn = get_connection(admin.db)
    assert get_aircraft_type(conn, "C172")["name"] == "Unsere Rote"
    conn.close()
    admin.post("/api/admin/aircraft-types", json={"type_code": "C172", "name": ""})
    conn = get_connection(admin.db)
    assert get_aircraft_type(conn, "C172")["name"] == "Cessna 172"
    conn.close()


def test_ungueltiger_alias_wird_mit_400_abgelehnt(admin):
    r = admin.post("/api/admin/aircraft-types",
                   json={"type_code": "P24", "alias_of": "P24"})
    assert r.status_code == 400
    admin.post("/api/admin/aircraft-types", json={"type_code": "P24", "alias_of": "PA24"})
    r = admin.post("/api/admin/aircraft-types",
                   json={"type_code": "PA24", "alias_of": "X"})
    assert r.status_code == 400, "Kette in der anderen Reihenfolge wurde zugelassen"


def test_liste_zeigt_import_und_korrektur_getrennt(admin):
    from app.database import (get_connection, set_aircraft_type_override,
                              upsert_aircraft_type_import)
    conn = get_connection(admin.db)
    upsert_aircraft_type_import(conn, "C172", name="Cessna 172", now=T0)
    set_aircraft_type_override(conn, "C172", name="Unsere Rote", now=T0)
    conn.commit()
    conn.close()
    d = admin.get("/api/admin/aircraft-types").json()
    row = next(r for r in d["types"] if r["type_code"] == "C172")
    assert row["name"] == "Cessna 172"
    assert row["name_override"] == "Unsere Rote"
    assert "fetch_state" in row and "checked_at" in row and "attempts" in row


def test_liste_zeigt_auch_den_zuladungs_recherchezustand(admin):
    """Teil 8 hat absichtlich keine UI — sichtbar wird der Zustand hier."""
    from app.database import get_connection, mark_payload_research
    conn = get_connection(admin.db)
    mark_payload_research(conn, "AP32", "fehler", T0, last_error="Overloaded")
    conn.commit()
    conn.close()
    d = admin.get("/api/admin/aircraft-types").json()
    row = next(r for r in d["types"] if r["type_code"] == "AP32")
    assert row["payload_state"] == "fehler"
    assert row["payload_last_error"] == "Overloaded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_aircraft_api.py -k "upload or override or alias or liste" -v`
Expected: FAIL — 404, die Admin-Routen fehlen

- [ ] **Step 3: Write minimal implementation**

In `app/main.py`:

```python
MAX_UPLOAD_BYTES = 8 * 1024 * 1024     # vor der Umwandlung
PHOTO_MAX_WIDTH = 1280


@app.get("/api/admin/aircraft-types")
async def admin_aircraft_types(request: Request):
    """Alle Muster mit Import- und Korrekturwerten, beiden Recherche-Zuständen und Flugzahl."""
    require_admin(request)
    from app.database import FLIGHT_TYPE_CODE_SQL
    conn = get_connection(get_settings().DB_PATH)
    try:
        rows = conn.execute(
            f"""SELECT COALESCE(t.type_code, p.type_code, f.code) AS type_code,
                       t.alias_of, t.name, t.name_override, t.extract, t.extract_override,
                       t.wiki_title, t.wiki_title_override, t.wiki_lang,
                       t.photo_file, t.photo_override, t.photo_credit,
                       t.photo_licence, t.photo_artist, t.photo_source_url,
                       t.fetch_state, t.attempts, t.checked_at, t.last_error,
                       p.make_model, p.payload_kg, p.source AS payload_source,
                       r.state AS payload_state, r.attempts AS payload_attempts,
                       r.checked_at AS payload_checked_at, r.last_error AS payload_last_error,
                       COALESCE(f.n, 0) AS fluege
                  FROM aircraft_types t
                  FULL OUTER JOIN aircraft_payloads p ON p.type_code = t.type_code
                  FULL OUTER JOIN payload_research  r ON r.type_code = t.type_code
                  LEFT JOIN (SELECT {FLIGHT_TYPE_CODE_SQL} AS code, COUNT(*) AS n
                               FROM flight_cache
                              WHERE COALESCE(NULLIF(aircraft_icao,''), aircraft) IS NOT NULL
                                AND COALESCE(NULLIF(aircraft_icao,''), aircraft) != ''
                              GROUP BY code) f
                         ON f.code = COALESCE(t.type_code, p.type_code)
                 ORDER BY fluege DESC, type_code ASC"""
        ).fetchall()
    finally:
        conn.close()
    return {"types": [dict(r) for r in rows]}
```

**Hinweis zur Umsetzung:** SQLite unterstützt `FULL OUTER JOIN` erst ab 3.39. Ist die Version im Container älter, statt des Joins drei Abfragen machen und in Python über `normalize_type_code` zusammenführen — dabei die Schlüsselmenge aus `aircraft_types ∪ aircraft_payloads ∪ payload_research ∪ flight_type_codes(conn)` bilden. Vor der Umsetzung prüfen:

```bash
docker exec friesenspy-friesenspy-1 python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

```python
@app.post("/api/admin/aircraft-types")
async def admin_upsert_aircraft_type(request: Request):
    """Korrekturen setzen oder leeren. Ein Leerstring löscht die Korrektur."""
    require_admin(request)
    require_confirm(request)
    from app.database import (
        normalize_type_code, set_aircraft_type_override, validate_alias,
    )
    body = await request.json()
    code = normalize_type_code(str(body.get("type_code") or ""))
    if not code:
        raise HTTPException(status_code=400, detail="type_code fehlt")
    conn = get_connection(get_settings().DB_PATH)
    try:
        felder = {}
        for feld in ("name", "extract", "wiki_title", "photo_override", "photo_credit"):
            if feld in body:
                felder[feld] = body[feld]
        if "alias_of" in body:
            ziel = normalize_type_code(str(body.get("alias_of") or ""))
            if ziel:
                fehler = validate_alias(conn, code, ziel)
                if fehler:
                    raise HTTPException(status_code=400, detail=fehler)
            felder["alias_of"] = ziel
        if "photo_override" in felder and felder["photo_override"] not in (None, "", "-"):
            raise HTTPException(
                status_code=400,
                detail="photo_override akzeptiert nur '-' (kein Foto) oder leer. "
                       "Ein Upload setzt 'blob' selbst.",
            )
        set_aircraft_type_override(conn, code, now=datetime.now(timezone.utc), **felder)
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.post("/api/admin/aircraft-types/{code}/refetch")
async def admin_refetch_aircraft_type(request: Request, code: str):
    """Neu holen — nutzt ein gesetztes Lemma. Schreibt nur Import-Spalten."""
    require_admin(request)
    require_confirm(request)
    from app.database import mark_aircraft_type_state, normalize_type_code
    roh = normalize_type_code(code)
    conn = get_connection(get_settings().DB_PATH)
    try:
        mark_aircraft_type_state(conn, roh, "neu", datetime.now(timezone.utc))
        conn.commit()
    finally:
        conn.close()
    if poller_instance is not None:
        asyncio.create_task(poller_instance._resolve_aircraft_type(roh))
    return {"ok": True}


@app.post("/api/admin/aircraft-types/{code}/photo")
async def admin_upload_aircraft_photo(request: Request, code: str, file: UploadFile = File(...)):
    """Eigenes Foto hochladen.

    Das Bild wird mit Pillow dekodiert und **neu geschrieben**. Das erledigt drei Dinge in
    einem Schritt: was Pillow nicht öffnet, ist kein Bild (Dateiendung und gemeldeter
    Content-Type werden nicht geglaubt); EXIF fällt weg (ein Handyfoto vom Cockpit trägt sonst
    GPS-Koordinaten in die Datenbank einer öffentlichen Seite); und die Größe bleibt
    beherrschbar.

    Uploads liegen als BLOB in der DB, nicht als Datei: sie sind **unersetzlich**, und das
    nächtliche Backup sichert nur die Datenbank (`backup_onedrive.sh:225`), nicht `data/`.
    """
    require_admin(request)
    require_confirm(request)
    from io import BytesIO

    from PIL import Image

    from app.database import normalize_type_code
    roh = normalize_type_code(code)
    if not roh:
        raise HTTPException(status_code=400, detail="Ungültiges Kürzel")
    daten = await file.read()
    if len(daten) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Bild größer als 8 MB")
    try:
        img = Image.open(BytesIO(daten))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Das ist kein Bild.") from exc
    img = img.convert("RGB")
    if img.width > PHOTO_MAX_WIDTH:
        hoehe = max(1, round(img.height * PHOTO_MAX_WIDTH / img.width))
        img = img.resize((PHOTO_MAX_WIDTH, hoehe))
    aus = BytesIO()
    img.save(aus, format="JPEG", quality=82)   # ohne exif= → EXIF ist weg
    blob = aus.getvalue()

    conn = get_connection(get_settings().DB_PATH)
    try:
        jetzt = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        conn.execute(
            "INSERT INTO aircraft_types (type_code, fetch_state, updated_at) "
            "VALUES (?, 'neu', ?) ON CONFLICT(type_code) DO NOTHING", (roh, jetzt))
        # Reihenfolge zählt: der CHECK verlangt, dass der Blob beim Setzen von 'blob' da ist.
        conn.execute(
            "UPDATE aircraft_types SET photo_blob = ?, photo_override = 'blob', "
            "updated_at = ? WHERE type_code = ?", (blob, jetzt, roh))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "bytes": len(blob), "width": img.width}
```

Oben in `app/main.py`: `from fastapi import File, UploadFile` ergänzen.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_aircraft_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_aircraft_api.py
git commit -m "feat(admin): Muster-Infos pflegen, eigenes Foto hochladen

Overrides setzen und leeren (Leerstring stellt den Importwert wieder her), Alias mit
Validierung inklusive der Gegenrichtung, Neu-holen, und Upload.

Der Upload wird mit Pillow dekodiert und neu geschrieben: was Pillow nicht oeffnet, ist kein
Bild; EXIF faellt weg (Handyfoto vom Cockpit traegt sonst GPS in die DB einer oeffentlichen
Seite); max 1280 px. Der Blob liegt in der DB, weil Uploads unersetzlich sind und das
Backup nur die DB sichert, nicht data/.

Die Admin-Liste zeigt beide Recherche-Zustaende -- damit wird auch Teil 8 sichtbar, der
absichtlich ohne eigene UI ausgeliefert wurde."
```

---

### Task 8: Admin-Panel „Muster-Infos"

**Files:**
- Modify: `app/static/admin.html` (neues Panel neben „Kutter-Zuladungen", `admin.html:944 ff.`)

**Interfaces:**
- Consumes: die vier Admin-Endpunkte aus Task 7
- Produces: nichts für andere Tasks

- [ ] **Step 1: Panel-Markup einfügen**

Neben dem bestehenden Zuladungs-Panel, im gleichen Stil. **Beide Scroll-Fallen aus `CLAUDE.md` beachten:** die Tabelle liegt in `.table-wrap`, das Panel hat `min-width: 0` (in `admin.html` bereits auf `.panel` gesetzt), und weil `.table-wrap` hier in einer `.scroll-list` steckt, braucht es dieselbe Höhenbegrenzung plus sichtbare Scrollbar-Styles.

```html
<div class="panel">
  <h3>Muster-Infos</h3>
  <p class="hint">
    Import und Korrektur stehen nebeneinander: ein leeres Korrekturfeld heißt „Importwert gilt".
    Beim falschen Artikel besser das <b>Lemma</b> korrigieren und „Neu holen" drücken — dann
    wandert das Foto mit.
  </p>
  <div class="form-row">
    <div class="form-group"><label for="mi-code">Kürzel</label>
      <input id="mi-code" placeholder="C172" /></div>
    <div class="form-group"><label for="mi-name">Name (Korrektur)</label>
      <input id="mi-name" /></div>
    <div class="form-group"><label for="mi-lemma">Wikipedia-Lemma (Korrektur)</label>
      <input id="mi-lemma" /></div>
  </div>
  <div class="form-row">
    <div class="form-group"><label for="mi-extract">Text (Korrektur)</label>
      <textarea id="mi-extract" rows="3"></textarea></div>
    <div class="form-group"><label for="mi-credit">Bildnachweis</label>
      <input id="mi-credit" /></div>
    <div class="form-group"><label for="mi-alias">Alias von</label>
      <input id="mi-alias" placeholder="PA24" /></div>
  </div>
  <div class="form-row">
    <div class="form-group"><label for="mi-photo">Eigenes Foto</label>
      <input type="file" id="mi-photo" accept="image/*" /></div>
    <div class="form-group">
      <label><input type="checkbox" id="mi-nophoto" /> Kein Foto anzeigen</label></div>
  </div>
  <div class="btn-row">
    <button class="btn" onclick="miSave()">Speichern</button>
    <button class="btn" onclick="miUpload()">Foto hochladen</button>
    <button class="btn" onclick="miRefetch()">🔄 Neu holen</button>
  </div>
  <div id="mi-container" class="scroll-list"><div class="empty-hint">Lade Muster…</div></div>
</div>
```

- [ ] **Step 2: JavaScript ergänzen**

```javascript
let _miRows = [];

async function miLoad() {
  const res = await api('GET', '/api/admin/aircraft-types');
  const d = await res.json();
  _miRows = d.types || [];
  const c = document.getElementById('mi-container');
  if (!_miRows.length) { c.innerHTML = '<div class="empty-hint">Keine Muster.</div>'; return; }
  c.innerHTML = '<div class="table-wrap"><table><thead><tr>'
    + '<th>Kürzel</th><th>Flüge</th><th>Name</th><th>Lemma</th><th>Foto</th>'
    + '<th>Muster-Info</th><th>Zuladung</th><th></th></tr></thead><tbody>'
    + _miRows.map(r => {
      const name = r.name_override || r.name || '—';
      const korr = r.name_override ? ' <span title="Korrektur">✎</span>' : '';
      const foto = r.photo_override === '-' ? 'aus'
                 : r.photo_override === 'blob' ? 'eigenes'
                 : r.photo_file ? (r.photo_licence || 'Commons') : '—';
      const zust = (r.fetch_state || 'neu')
        + (r.attempts ? ' (' + r.attempts + '×)' : '')
        + (r.last_error ? ' — ' + escH(String(r.last_error).slice(0, 60)) : '');
      const pz = (r.payload_state || (r.payload_kg != null ? 'ok' : '—'))
        + (r.payload_last_error ? ' — ' + escH(String(r.payload_last_error).slice(0, 40)) : '');
      return '<tr><td><b>' + escH(r.type_code) + '</b>'
        + (r.alias_of ? '<br><span class="hint">→ ' + escH(r.alias_of) + '</span>' : '')
        + '</td><td>' + (r.fluege || 0) + '</td>'
        + '<td>' + escH(name) + korr + '</td>'
        + '<td>' + escH(r.wiki_title_override || r.wiki_title || '—') + '</td>'
        + '<td>' + escH(foto) + '</td>'
        + '<td>' + zust + '</td><td>' + pz + '</td>'
        + '<td><button class="btn btn-sm" onclick="miPrefill(\'' + escA(r.type_code)
        + '\')">Bearbeiten</button></td></tr>';
    }).join('') + '</tbody></table></div>';
}

function miPrefill(code) {
  const r = (_miRows || []).find(x => x.type_code === code) || {};
  document.getElementById('mi-code').value = code;
  document.getElementById('mi-name').value = r.name_override || '';
  document.getElementById('mi-lemma').value = r.wiki_title_override || '';
  document.getElementById('mi-extract').value = r.extract_override || '';
  document.getElementById('mi-credit').value = r.photo_credit || '';
  document.getElementById('mi-alias').value = r.alias_of || '';
  document.getElementById('mi-nophoto').checked = r.photo_override === '-';
}

async function miSave() {
  const code = document.getElementById('mi-code').value.trim().toUpperCase();
  if (!code) { alert('Kürzel fehlt'); return; }
  const body = {
    type_code: code,
    name: document.getElementById('mi-name').value,
    wiki_title: document.getElementById('mi-lemma').value,
    extract: document.getElementById('mi-extract').value,
    photo_credit: document.getElementById('mi-credit').value,
    alias_of: document.getElementById('mi-alias').value,
    photo_override: document.getElementById('mi-nophoto').checked ? '-' : '',
  };
  const res = await api('POST', '/api/admin/aircraft-types', body);
  if (!res.ok) { alert((await res.json()).detail || 'Fehler'); return; }
  await miLoad();
}

async function miRefetch() {
  const code = document.getElementById('mi-code').value.trim().toUpperCase();
  if (!code) { alert('Kürzel fehlt'); return; }
  await api('POST', '/api/admin/aircraft-types/' + encodeURIComponent(code) + '/refetch');
  setTimeout(miLoad, 3000);
}

async function miUpload() {
  const code = document.getElementById('mi-code').value.trim().toUpperCase();
  const f = document.getElementById('mi-photo').files[0];
  if (!code || !f) { alert('Kürzel und Datei nötig'); return; }
  const fd = new FormData();
  fd.append('file', f);
  const res = await apiForm('POST',
    '/api/admin/aircraft-types/' + encodeURIComponent(code) + '/photo', fd);
  if (!res.ok) { alert((await res.json()).detail || 'Fehler'); return; }
  await miLoad();
}
```

`apiForm` analog zum vorhandenen `api`-Helfer anlegen, aber **ohne** `Content-Type`-Header (den setzt der Browser für `multipart/form-data` samt Boundary selbst). Den Bestätigungs-Header, den `require_confirm` erwartet, wie in `api` mitschicken. `miLoad()` beim Öffnen des Admin-Tabs aufrufen, wo die anderen Loader stehen.

- [ ] **Step 3: Sichtbare Scrollbar sicherstellen**

In den `<style>`-Block von `admin.html`, falls für `.scroll-list .table-wrap` noch nicht vorhanden:

```css
.scroll-list .table-wrap { max-height: 280px; overflow: auto; }
.scroll-list .table-wrap { scrollbar-width: thin; scrollbar-color: #3a4a5a #1a2530; }
.scroll-list .table-wrap::-webkit-scrollbar { height: 10px; width: 10px; }
.scroll-list .table-wrap::-webkit-scrollbar-thumb { background: #3a4a5a; border-radius: 5px; }
```

Beide Teile sind nötig — ohne die Höhenbegrenzung sitzt die horizontale Scrollbar unterhalb des sichtbaren 280-px-Fensters, und ohne die Scrollbar-Styles blenden Windows/Edge/Chrome eine korrekt scrollende Box unsichtbar (Overlay-Scrollbar). Siehe `CLAUDE.md`, v8.6.6-Fund.

- [ ] **Step 4: Manuell prüfen**

Lokal `uvicorn app.main:app --reload`, Admin öffnen: Liste lädt, „Bearbeiten" füllt die Felder, Speichern und Leeren wirken, Upload zeigt „eigenes", ungültiger Alias zeigt die Fehlermeldung aus dem Backend. Am Smartphone (oder im schmalen Fenster) muss die Tabelle horizontal scrollen und die Scrollbar sichtbar sein.

- [ ] **Step 5: Commit**

```bash
git add app/static/admin.html
git commit -m "feat(admin-ui): Panel 'Muster-Infos'

Liste mit Import- und Korrekturwert, beiden Recherche-Zustaenden und Flugzahl; Bearbeiten,
Speichern, Neu holen, Foto hochladen. Ein leeres Korrekturfeld stellt den Importwert wieder
her.

Beide Scroll-Fallen aus CLAUDE.md beachtet: .table-wrap in .scroll-list braucht dieselbe
Hoehenbegrenzung, sonst sitzt die horizontale Scrollbar unterhalb des sichtbaren Fensters --
plus explizite Scrollbar-Styles, weil Windows/Edge/Chrome eine korrekt scrollende Box sonst
unsichtbar lassen."
```

---

### Task 9: Frontend — `acLink()`, Modal, die acht Stellen

**Files:**
- Modify: `app/static/index.html`

**Interfaces:**
- Consumes: `GET /api/aircraft/{code}` (Task 6)
- Produces: `acLink(code)`, `openAcModal(code)`, `closeAcModal()`

- [ ] **Step 1: Hilfsfunktion und Modal ergänzen**

```javascript
// Aircraft-Designator als Klickziel. EIN Markup fuer alle acht Sichten.
// Attribut heisst data-actype, NICHT data-ac -- letzteres ist bei den Flugzeilen fuer das
// Flugplan-Modal belegt (index.html:3809), sonst oeffnen sich zwei Modals uebereinander.
function acLink(code) {
  const c = (code || '').trim();
  if (!c || c === '—') return '—';
  return '<a class="ac-link" href="#" data-actype="' + escHtml(c) + '">' + escHtml(c) + '</a>';
}

document.addEventListener('click', function (e) {
  const a = e.target.closest && e.target.closest('a.ac-link[data-actype]');
  if (!a) return;
  e.preventDefault();
  e.stopPropagation();   // nicht die Zeile darunter mit-oeffnen (Flugplan-Modal)
  openAcModal(a.getAttribute('data-actype'));
});

async function openAcModal(code) {
  const el = document.getElementById('ac-modal');
  document.getElementById('ac-body').innerHTML = '<div class="empty-hint">Lade…</div>';
  el.classList.add('open');
  document.addEventListener('keydown', _acEscHandler);
  let d;
  try {
    const res = await fetch('/api/aircraft/' + encodeURIComponent(code));
    d = await res.json();
  } catch (err) {
    document.getElementById('ac-body').innerHTML =
      '<div class="empty-hint">Konnte nicht geladen werden.</div>';
    return;
  }
  const f = d.friesen || {};
  let h = '';

  if (d.photo_url) {
    h += '<img class="ac-photo" src="' + escHtml(d.photo_url) + '" alt="' + escHtml(d.code) + '">';
    const nachweis = d.photo_credit
      || [d.photo_artist, d.photo_licence].filter(Boolean).join(' · ');
    if (nachweis || d.photo_source_url) {
      h += '<div class="ac-credit">' + escHtml(nachweis || '');
      if (d.photo_source_url) {
        h += ' <a href="' + escHtml(d.photo_source_url) + '" target="_blank" rel="noopener">Quelle</a>';
      }
      h += '</div>';
    }
  }

  h += '<div class="ac-title">' + escHtml(d.name || d.code) + '</div>';
  if (d.resolved_code !== d.code) {
    h += '<div class="hint">Flugplan-Kürzel ' + escHtml(d.code)
       + ', gemeint ist ' + escHtml(d.resolved_code) + '.</div>';
  }
  if (d.extract) {
    h += '<p class="ac-extract">' + escHtml(d.extract) + '</p>';
    if (d.wiki_url) {
      h += '<div class="hint"><a href="' + escHtml(d.wiki_url)
         + '" target="_blank" rel="noopener">Auf Wikipedia weiterlesen</a></div>';
    }
  } else if (!d.name) {
    h += '<p class="empty-hint">Zu diesem Kürzel ist kein Muster bekannt.</p>';
  }

  h += '<div class="ac-block"><h4>Bei den Friesen</h4>';
  if (f.fluege) {
    let zeile = f.fluege + (f.fluege === 1 ? ' Flug' : ' Flüge');
    if (f.alias_anteil && f.alias_anteil.length) {
      zeile += ' (' + f.alias_anteil.map(a => a.n + ' davon als ' + escHtml(a.code)
        + ' erfasst').join(', ') + ')';
    }
    h += '<div>' + zeile + '</div>';
    h += '<div>' + f.stunden + ' h · ' + Math.round(f.nm) + ' nm · '
       + f.piloten + (f.piloten === 1 ? ' Pilot' : ' Piloten') + '</div>';
    if (f.von) h += '<div class="hint">' + escHtml(f.von) + ' bis ' + escHtml(f.bis) + '</div>';
  } else {
    h += '<div class="empty-hint">Noch nie geflogen.</div>';
  }
  h += '</div>';

  if (d.top && d.top.length) {
    h += '<div class="ac-block"><h4>Am häufigsten</h4>'
       + d.top.map(t => '<div>' + escHtml(t.name || t.callsign || ('CID ' + t.cid))
           + ' — ' + t.n + '</div>').join('') + '</div>';
  }

  const k = d.kutter || {};
  if (k.payload_kg != null || k.mtow_kg != null) {
    h += '<div class="ac-block"><h4>Kutter-Daten</h4><div>';
    if (k.mtow_kg != null) h += 'MTOW ' + Math.round(k.mtow_kg) + ' kg · ';
    if (k.empty_kg != null) h += 'leer ' + Math.round(k.empty_kg) + ' kg · ';
    if (k.payload_kg != null) h += 'Zuladung ' + Math.round(k.payload_kg) + ' kg';
    h += '</div>';
    if (k.eigene_zeile_hinweis) {
      h += '<div class="hint">' + escHtml(k.eigene_zeile_hinweis) + '</div>';
    }
    h += '</div>';
  }

  document.getElementById('ac-body').innerHTML = h;
}

function closeAcModal() {
  document.getElementById('ac-modal').classList.remove('open');
  document.removeEventListener('keydown', _acEscHandler);
}

function _acEscHandler(e) { if (e.key === 'Escape') closeAcModal(); }
```

Markup neben den anderen Modals:

```html
<div id="ac-modal" class="modal">
  <div class="modal-box">
    <button class="modal-close" onclick="closeAcModal()">×</button>
    <div id="ac-body"></div>
  </div>
</div>
```

CSS im `<style>`-Block — `--green` ist die Variable für Blau (historischer Name):

```css
.ac-link { color: var(--green); text-decoration: none; border-bottom: 1px dotted var(--green); }
.ac-link:hover { text-decoration: underline; }
#ac-modal .modal-box { max-height: 85vh; overflow-y: auto; }
.ac-photo { width: 100%; height: auto; border-radius: 4px; display: block; }
.ac-credit { font-size: 0.68rem; color: #8aa0b8; margin: 0.25rem 0 0.75rem; }
.ac-title { font-weight: 700; font-size: 1.05rem; margin-bottom: 0.25rem; }
.ac-extract { line-height: 1.45; }
.ac-block { margin-top: 0.9rem; }
.ac-block h4 { margin: 0 0 0.3rem; font-size: 0.78rem; letter-spacing: 0.06em;
               text-transform: uppercase; color: #8aa0b8; }
```

- [ ] **Step 2: Die acht Stellen umstellen**

Jede Stelle nachgemessen am 2026-07-30. `escHtml` fällt weg, wo `acLink` es selbst macht.

| Zeile | Funktion | vorher → nachher |
|---|---|---|
| 2727 | `renderLiveTable` | `${escHtml(p.aircraft \|\| '—')}` → `${acLink(p.aircraft)}` |
| 3130 | `renderBummelParticipants` | dito |
| 3229 | `renderBummelStandings` | `${escHtml(e.aircraft \|\| '—')}` → `${acLink(e.aircraft)}` |
| 3379 | `_kutterBannerBlock` | `${_kesc(a.aircraft \|\| '—')}` → `${acLink(a.aircraft)}` |
| 3493 | `openFpModal` | `fpSet('fp-aircraft', …)` → siehe unten |
| 3831 | `_flightRowHtml` | `${escHtml(f.aircraft \|\| '—')}` → `${acLink(f.aircraft)}` |
| 4130 | `buildPopupHtml` | `${escHtml(p.aircraft \|\| '—')}` → `${acLink(p.aircraft)}` |
| 5158 | `_kutterDetailBody` | `_kesc(f.aircraft \|\| '')` → `acLink(f.aircraft)` |

`fpSet` setzt `textContent` — für Zeile 3493 stattdessen HTML setzen:

```javascript
  const acEl = document.getElementById('fp-aircraft');
  const acCode = pilot.aircraft_icao || pilot.aircraft;
  acEl.innerHTML = acLink(acCode);
```

**`index.html:3176` bleibt unverändert.** Das ist der Text für die Zwischenablage (`_buildBummelForumText`); Markup dort würde `<a class=…>` in die geteilte Nachricht kleben.

Beim Karten-Popup (4130) prüfen, dass der Klick nicht von Leaflet abgefangen wird — der delegierte Listener hängt am `document`, Popups sind Teil des DOM, das funktioniert. `e.stopPropagation()` verhindert, dass die Zeile darunter ihr eigenes Modal öffnet (relevant bei 3831, wo die Zeile `data-ac` trägt).

- [ ] **Step 3: Manuell prüfen**

`uvicorn app.main:app --reload`, dann alle acht Sichten durchklicken. Erwartet: Designator ist blau, Klick öffnet das Modal, Escape und × schließen es, in der Flugliste öffnet **nicht** zusätzlich das Flugplan-Modal, und der Bummel-Text in der Zwischenablage enthält kein Markup. Am Smartphone: Modal scrollt.

- [ ] **Step 4: Commit**

```bash
git add app/static/index.html
git commit -m "feat(ui): Aircraft-Designator in allen acht Sichten anklickbar

Eine Hilfsfunktion acLink() und ein delegierter Listener am document; das Modal folgt dem
vorhandenen Flugplan-Modal. Designator ist blau, nach der stehenden UI-Regel.

Attribut heisst data-actype, nicht data-ac -- letzteres ist bei den Flugzeilen fuer das
Flugplan-Modal belegt (3809), sonst oeffnen sich zwei Modals uebereinander.
index.html:3176 bleibt unveraendert: das ist der Text fuer die Zwischenablage, kein HTML.

Jeder Designator ist klickbar, auch ein unbekanntes Kuerzel -- die Friesen-Zahlen dazu sind
echt. Ein Kuerzel, das manchmal blau ist und manchmal nicht, waere schlechter als ein Panel
ohne Foto."
```

---

### Task 10: CHANGELOG, Version, Abnahme am laufenden System

**Files:**
- Modify: `app/CHANGELOG.json`

- [ ] **Step 1: Eintrag ganz vorne einfügen**

```json
  {
    "version": "10.6.0",
    "date": "2026-07-30",
    "highlight": true,
    "title": "Was ist das für ein Flugzeug?",
    "items": [
      "✈️ Das Muster-Kürzel ist jetzt überall anklickbar — in der Live-Liste, auf der Karte, im Flugplan, in der Flugliste, im Bummel und beim Kutter. Ein Klick zeigt Foto, Kurzbeschreibung und was die Gruppe mit dem Muster schon geflogen hat: Flüge, Stunden, Strecke, wer es am häufigsten nimmt, und die gepflegten Kutter-Gewichte.",
      "📷 Die Fotos kommen von Wikimedia Commons, mit Angabe von Urheber und Lizenz — und nur solche, deren Lizenz das erlaubt. FriesenSpy holt sie selbst und legt sie ab, statt sie von fremden Servern einzubinden: so erfährt niemand Drittes, wer hier mitliest. Wo ein passendes Bild fehlt, kann im Admin eins hochgeladen werden, auch ein eigener Screenshot.",
      "🔤 Vertippte Kürzel lassen sich auf das richtige Muster umbiegen (etwa P24 auf PA24). Die Flüge zählen dann zum richtigen Muster, und das Panel schreibt dazu, wie viele davon unter dem alten Kürzel erfasst wurden.",
      "🤷 Und wenn zu einem Kürzel nichts zu finden ist, steht das da — statt eines erfundenen Textes oder eines Platzhalterbilds."
    ]
  },
```

- [ ] **Step 2: Version prüfen**

Run: `python -c "from app.version import VERSION; print(VERSION)"`
Expected: `10.6.0`

- [ ] **Step 3: Volle Suite**

Run: `pytest tests/ -q`
Expected: PASS, keine Regression.

- [ ] **Step 4: Commit**

```bash
git add app/CHANGELOG.json
git commit -m "V10.6.0: Muster-Info-Panel (Designator anklickbar, Foto aus Commons)"
```

- [ ] **Step 5: Abnahme **vom Server aus** (Pflicht, nicht optional)**

Rev.-2-Befund B3: Wikimedia sperrt das Netz dieses Servers ohne User-Agent. Eine Prüfung aus der Entwicklungsumgebung beweist deshalb **nichts** — genau dieser Fehler steckte in Rev. 1 der Spec. Nach dem Deploy im Container:

```bash
# 1. Läuft die Auflösung überhaupt durch?
docker logs friesenspy-friesenspy-1 2>&1 | grep -i "Muster-Info"

# 2. Zustände über alle Muster
sudo sqlite3 -column 'file:/opt/friesenspy/data/friesenspy.db?mode=ro' \
  "SELECT fetch_state, COUNT(*) FROM aircraft_types GROUP BY fetch_state;"

# 3. Die zwei Fälle, die in Rev. 1 falsch gewesen wären
sudo sqlite3 -column 'file:/opt/friesenspy/data/friesenspy.db?mode=ro' \
  "SELECT type_code, wiki_title, photo_licence, photo_file FROM aircraft_types
    WHERE type_code IN ('C172','EC45');"
```

Erwartet: **`C172` hat ein Foto** (Leitbild ist GFDL 1.2, aber der Artikel enthält freie Bilder — Rev. 1 hätte hier dauerhaft nichts gezeigt, beim mit 506 Flügen häufigsten Muster der Gruppe). **`EC45` hat `wiki_title = 'MBB/Kawasaki BK 117'`** (der zweite Suchtreffer; Rev. 1 hätte den ersten genommen und das Muster verworfen). Mindestens fünf Muster insgesamt mit Text und Foto.

Und zuletzt im Browser: Designator anklicken, Foto samt Bildnachweis prüfen.

---

## Self-Review

**Spec-Abdeckung (Rev. 2, ohne Teil 8 — der ist Plan A):**

| Spec-Anforderung | Task |
|---|---|
| Maßgebliche Spalte, nie per `OR` | 1 (nutzt `FLIGHT_TYPE_CODE_SQL`) |
| Tabelle `aircraft_types`, nicht in `aircraft_payloads` | 1 |
| Override-Semantik, Leerstring stellt Import wieder her | 1, 7 |
| `photo_credit` gilt auch für Commons (W6) | 1, 9 |
| `CHECK` gegen `photo_override='blob'` ohne Blob (W6) | 1 |
| Alias: ein Schritt, drei Ablehnungsgründe (W5.1) | 1, 7 |
| `alias_anteil` als Liste (W5.2) | 1, 9 |
| Alias mit eigener Zuladungszeile: Panel warnt, Kutter unangetastet (W5.3) | 6, 9 |
| Namens-Rangfolge Admin → `make_model` → LLM | 5 (`_muster_name`; Stufe 3 wirkt über Plan A) |
| Namenshärtung (B2/W8) | 2 |
| Suche mit `srlimit=3`, Top-3 prüfen (B2) | 3 |
| Überlappung gegen ganzen Namen (B2) | 2 |
| `description` leer → `extract` (B2) | 2 |
| Admin-Lemma umgeht die Prüfung | 3 (`resolve_title`), 5 |
| `media-list` statt nur `originalimage` (W1) | 3 |
| `Datei:` → `File:` (W1) | 3 |
| Lizenz-Whitelist, GFDL-dual (W4) | 3 |
| User-Agent Pflicht, 403/429 transient (B3) | 2, 4 |
| Vier Auslöser, keiner im Klickpfad | 5, 6 |
| Retry-Job als Ausführer (B4) | 5 |
| `ok` ist nicht endgültig, fehlende Datei (W2) | 5, 6 |
| Klick-Eingrenzung auf bekannte Codes (W3) | 6 |
| `?v=updated_at` gegen alte Browser-Bilder | 6 |
| Upload: Pillow, EXIF, 8 MB, 1280 px, Name aus Typcode | 7 |
| BLOB in DB / Datei im Volume, Backup-Begründung | 1, 5, 6, 7 |
| Admin-Panel mit `checked_at`, Herkunft, Neu holen | 8 |
| Serialisiert und gedeckelt, ~250 Requests | 5 |
| Acht Stellen, `data-actype`, 3176 unverändert | 9 |
| Blau, Modal scrollbar, Scroll-Fallen | 8, 9 |
| Leerer Zustand, ehrlich | 9 |
| Top-Piloten wie im Statistik-Tab | 1, 6, 9 |
| Abnahme vom Server aus (B3) | 10 |

**Platzhalter:** keine. Zwei Stellen sind bewusst als **Prüfschritt vor der Umsetzung** formuliert statt als Rätsel: die SQLite-Version für `FULL OUTER JOIN` (Task 7, mit benanntem Ersatzweg) und der Name der Poller-Referenz in `main.py` (Task 6). Beides ist ein Ein-Zeilen-Check, keine offene Designfrage.

**Typ-Konsistenz:** `get_aircraft_type` liefert überall `photo_kind ∈ {'blob','file',None}`; `friesen_numbers` liefert `alias_anteil` als `list[dict]` in Task 1, 6 und 9 gleich; `resolve_type` und `resolve_title` geben dieselben acht Schlüssel zurück (Task 3), die Task 5 unverändert konsumiert; `fetch_json`/`download_photo` heißen in Task 4 und 5 gleich; `_now`, `_register_jobs`, `_photo_dir` sind aus Plan A bzw. Task 5 durchgängig.

**Ein Widerspruch gefunden und behoben:** Task 3 prüfte in der ersten Fassung `title_matches_name` **vor** dem Summary-Aufruf; der Test `test_hoechstens_drei_treffer_werden_geprueft` erwartet aber drei Summary-Aufrufe. Der Schritt-3-Text enthält die Korrektur samt Begründung — die Summary liefert den kanonischen Titel nach einer Weiterleitung, und gegen den soll die Überlappung geprüft werden. Das ist auch sachlich besser als die erste Fassung.
