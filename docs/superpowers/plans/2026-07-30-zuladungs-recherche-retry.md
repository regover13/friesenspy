# Zuladungs-Recherche mit Retry und Nachlese — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine gescheiterte Zuladungs-Recherche wird wiederholt statt für immer vergessen, und Muster, die nur im Flugbestand stehen, werden nachgeholt.

**Architecture:** `llm.suggest_aircraft_payload()` unterscheidet ab jetzt einen **transienten** Fehler (API überladen, Timeout, 5xx) von „keine Daten gefunden" — heute wird beides zu `None`. Der Versuchszustand wandert aus dem prozesslokalen `set` in eine eigene Tabelle `payload_research`, ein periodischer Job holt fällige Wiederholungen, und ein Nachlese-Lauf beim Start erfasst den Altbestand.

**Tech Stack:** Python 3.11, SQLite (WAL), APScheduler, anthropic-SDK, pytest.

Dieser Plan ist **Teil 8** der Spec `docs/superpowers/specs/2026-07-30-muster-info-panel-design.md` (Rev. 2) und **unabhängig auslieferbar**. Er hat keine Abhängigkeit auf das Muster-Info-Panel. Umgekehrt schon: Plan B benutzt den hier gebauten Backoff-Helfer.

## Global Constraints

- **Kein Netz in Tests.** Das `anthropic`-Modul wird als `types.ModuleType` gefälscht (Muster: `tests/test_llm_suggest.py:38` `_fake_anthropic`).
- **Nie in die Produktions-DB schreiben.** Tests laufen gegen eine temporäre DB.
- **`normalize_type_code()`** (`app/database.py:4136`, Uppercase + vor `/` gekürzt) ist der einzige Weg, einen Typcode zu einem Tabellenschlüssel zu machen.
- **Maßgebliche Spalte für den Flugbestand:** `normalize_type_code(COALESCE(NULLIF(aircraft_icao,''), aircraft))`. Die beiden Spalten werden **nie** per `OR` addiert (Doppelzählung). `aircraft_icao` existiert erst seit 2026-06-09 und ist nur in 357 von 2256 Zeilen gefüllt.
- **Recherche kostet ~4 ct und ~30 s** (`docs/architecture.md:202`). Die Nachlese läuft **serialisiert** mit hartem Deckel je Lauf — dieselbe Doku hält fest, dass ein `PZ04`-Request über 9 Minuten lief und stille SDK-Retries 14 $ in zwei Tagen kosteten.
- **Silent-Fail-Kultur:** ein Fehler in der Recherche darf niemals einen Poll-Durchlauf abbrechen.
- **Neue Tabellen** gehören in `_DDL` (`app/database.py`, per `executescript` in `init_db`); neue **Spalten** in eine `_XXX_MIGRATIONS`-Liste, die `init_db` mit `try/except sqlite3.OperationalError` durchläuft.
- **Version + CHANGELOG:** `app/CHANGELOG.json` bekommt vorne einen neuen Eintrag; `app/version.py` liest `VERSION = CHANGELOG[0]["version"]`. Zielversion dieses Plans: **10.5.0**.

## File Structure

| Datei | Verantwortung | Art |
|---|---|---|
| `app/llm.py` | Recherche; neu: Ausnahme `TransientResearchError` und deren Auslösung | Modify |
| `app/database.py` | Tabelle `payload_research`, Zustandsfunktionen, Backoff-Helfer, Nachlese-Abfrage | Modify |
| `app/poller.py` | `_auto_research_payload` auf DB-Zustand umstellen, zwei neue Jobs | Modify |
| `app/main.py:3040-3053` | Admin-Endpunkt: transient → 503 statt 502 | Modify |
| `app/CHANGELOG.json` | Nutzer-sichtbarer Eintrag 10.5.0 | Modify |
| `tests/test_llm_transient.py` | Fehlerklassifikation in `llm.py` | Create |
| `tests/test_payload_research_state.py` | Tabelle, Zustandsübergänge, Backoff, Nachlese-Abfrage | Create |
| `tests/test_payload_research_poller.py` | `_auto_research_payload` + die zwei Jobs, mit kontrollierter Uhr | Create |

---

### Task 1: `llm.py` unterscheidet transient von endgültig

Heute fängt `suggest_aircraft_payload()` in `app/llm.py:236` **jede** Ausnahme ab und gibt `None` zurück. Der Aufrufer kann „API war überladen" und „es gibt keine Daten" nicht auseinanderhalten — das ist die Wurzel des AP32-Falls.

**Files:**
- Modify: `app/llm.py` (neue Exception-Klasse oben; `except`-Block bei Zeile ~236)
- Modify: `app/main.py:3040-3053`
- Test: `tests/test_llm_transient.py` (Create)

**Interfaces:**
- Consumes: nichts
- Produces:
  - `llm.TransientResearchError(Exception)` — wird geworfen, wenn die Recherche an einem vorübergehenden Zustand scheitert.
  - `llm.suggest_aircraft_payload(type_code: str) -> dict | None` — Vertrag unverändert für den Erfolgs- und den „keine Daten"-Fall (`None`); wirft **neu** `TransientResearchError`.
  - `llm.is_transient_error(exc: BaseException) -> bool` — Klassifikator, damit Plan B ihn für HTTP-Fehler wiederverwenden kann.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_transient.py
"""Ein vorübergehender API-Fehler ist kein "keine Daten" (AP32-Fall, 2026-07-30).

Gemessen: suggest_aircraft_payload('AP32') scheiterte an overloaded_error und gab None
zurück — nicht unterscheidbar von "Muster nicht auffindbar". Der Aufrufer merkte sich den
Code daraufhin dauerhaft als erledigt.
"""
from __future__ import annotations

import types
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _fake_anthropic_raising(exc: BaseException):
    """Fake-anthropic, dessen stream() beim Betreten die übergebene Ausnahme wirft."""
    mod = types.ModuleType("anthropic")

    class APIError(Exception):
        pass

    class APIStatusError(APIError):
        def __init__(self, message="", status_code=500):
            super().__init__(message)
            self.status_code = status_code

    class APIConnectionError(APIError):
        pass

    class APITimeoutError(APIConnectionError):
        pass

    class RateLimitError(APIStatusError):
        pass

    class InternalServerError(APIStatusError):
        pass

    class _Messages:
        def stream(self, **kwargs):
            raise exc

    class _Client:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    mod.APIError = APIError
    mod.APIStatusError = APIStatusError
    mod.APIConnectionError = APIConnectionError
    mod.APITimeoutError = APITimeoutError
    mod.RateLimitError = RateLimitError
    mod.InternalServerError = InternalServerError
    mod.Anthropic = _Client
    return mod


def _run(exc):
    from app import llm
    mod = _fake_anthropic_raising(exc)
    with patch.dict("sys.modules", {"anthropic": mod}):
        return llm.suggest_aircraft_payload("AP32")


def test_overloaded_raises_transient():
    """529 Overloaded — genau der gemessene AP32-Fall."""
    from app import llm
    mod = _fake_anthropic_raising(None)
    exc = mod.APIStatusError("Overloaded", status_code=529)
    with patch.dict("sys.modules", {"anthropic": mod}):
        mod.APIStatusError  # Modul ist gesetzt
        with pytest.raises(llm.TransientResearchError):
            _run(exc)


def test_timeout_raises_transient():
    from app import llm
    mod = _fake_anthropic_raising(None)
    with patch.dict("sys.modules", {"anthropic": mod}):
        with pytest.raises(llm.TransientResearchError):
            _run(mod.APITimeoutError("timeout"))


def test_rate_limit_raises_transient():
    from app import llm
    mod = _fake_anthropic_raising(None)
    with patch.dict("sys.modules", {"anthropic": mod}):
        with pytest.raises(llm.TransientResearchError):
            _run(mod.RateLimitError("slow down", status_code=429))


def test_value_error_stays_none():
    """Ein Programmier-/Datenfehler ist NICHT transient — Vertrag bleibt None."""
    assert _run(ValueError("kaputtes JSON")) is None


def test_client_error_400_stays_none():
    """4xx außer 408/429 ist endgültig: erneutes Fragen ändert nichts."""
    from app import llm
    mod = _fake_anthropic_raising(None)
    with patch.dict("sys.modules", {"anthropic": mod}):
        assert _run(mod.APIStatusError("bad request", status_code=400)) is None


def test_is_transient_error_classifies_plain_status_codes():
    """Plan B braucht den Klassifikator für HTTP-Fehler ohne anthropic-Typen."""
    from app import llm

    class _Http(Exception):
        def __init__(self, status_code):
            super().__init__(str(status_code))
            self.status_code = status_code

    assert llm.is_transient_error(_Http(403)) is True   # Wikimedia-Contabo-Block
    assert llm.is_transient_error(_Http(429)) is True
    assert llm.is_transient_error(_Http(503)) is True
    assert llm.is_transient_error(_Http(404)) is False
    assert llm.is_transient_error(ValueError("x")) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_transient.py -v`
Expected: FAIL — `AttributeError: module 'app.llm' has no attribute 'TransientResearchError'`

- [ ] **Step 3: Write minimal implementation**

In `app/llm.py`, direkt unter die bestehenden Modul-Konstanten (nach `_WEB_SEARCH_TOOL`, ~Zeile 34):

```python
class TransientResearchError(Exception):
    """Die Recherche scheiterte an einem vorübergehenden Zustand, nicht am Muster.

    Auslöser: API überladen (529), Rate-Limit (429), Timeout, Verbindungsabbruch, 5xx.
    Der Aufrufer MUSS das von "keine Daten gefunden" (``None``) unterscheiden und es später
    erneut versuchen — sonst passiert genau der AP32-Fall vom 2026-07-30: ein einzelnes
    ``overloaded_error`` hat das Muster zwei Monate aus der Tabelle gehalten.
    """


# 408 Request Timeout, 429 Rate Limit, 529 Overloaded (Anthropic) + alle 5xx gelten als
# vorübergehend. Alles andere im 4xx-Bereich ist endgültig: erneutes Fragen ändert nichts.
_TRANSIENT_STATUS = frozenset({408, 429, 529})


def is_transient_error(exc: BaseException) -> bool:
    """True, wenn ``exc`` ein vorübergehender Fehler ist (erneut versuchen lohnt).

    Arbeitet bewusst ohne Import von ``anthropic``: geprüft wird ein vorhandenes
    ``status_code``-Attribut sowie die Namen der anthropic-Verbindungs-/Timeout-Klassen.
    Damit ist der Klassifikator auch für HTTP-Fehler anderer Quellen brauchbar
    (Wikimedia: 403 durch den Contabo-Netzblock ist ausdrücklich vorübergehend).
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status >= 500 or status in _TRANSIENT_STATUS
    # Verbindungs- und Timeout-Fehler tragen keinen Status-Code.
    return any(
        name in {"APIConnectionError", "APITimeoutError", "TimeoutError", "ConnectionError"}
        for name in (c.__name__ for c in type(exc).__mro__)
    )
```

Den bestehenden `except`-Block in `suggest_aircraft_payload` (`app/llm.py:236`) ersetzen:

```python
    except Exception as exc:  # noqa: BLE001 — Komfortpfad, jeder Fehler → kein Vorschlag
        if is_transient_error(exc):
            # NICHT als "keine Daten" behandeln: der Aufrufer soll es erneut versuchen.
            logger.warning("Zuladungs-Vorschlag für %s vorübergehend gescheitert: %s", code, exc)
            raise TransientResearchError(str(exc)) from exc
        logger.warning("Zuladungs-Vorschlag für %s fehlgeschlagen: %s", code, exc)
        return None
```

Zusätzlich das Zeitbudget-Ende als transient behandeln (`app/llm.py`, im `pause_turn`-Loop, wo heute nur geloggt und `break` gemacht wird):

```python
            if _time.monotonic() >= deadline:
                logger.warning("Zuladungs-Vorschlag für %s: Zeitbudget erschöpft", code)
                raise TransientResearchError(f"Zeitbudget erschöpft für {code}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_transient.py -v`
Expected: PASS (7 Tests)

- [ ] **Step 5: Bestehende Aufrufer anpassen und die Regression prüfen**

`app/main.py:3040-3053` fängt die neue Ausnahme ab und meldet sie unterscheidbar:

```python
@app.get("/api/admin/transport/payloads/suggest")
async def admin_transport_payload_suggest(request: Request, type: str):
    """KI-Vorschlag (Claude Haiku 4.5) für die Zuladungs-Komponenten eines Flugzeugtyps."""
    require_admin(request)
    require_confirm(request)
    from app import llm
    if not llm.is_configured():
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY nicht konfiguriert")
    # Blockierender Haiku-Aufruf (Web-Search, bis zu ~1-2 Min.) — in einen Thread auslagern,
    # sonst haengt die Event-Loop und damit die GESAMTE App fuer die Dauer der Recherche.
    try:
        suggestion = await asyncio.to_thread(llm.suggest_aircraft_payload, type)
    except llm.TransientResearchError as exc:
        # 503 + Retry-After: der Admin soll es gleich nochmal versuchen koennen, statt
        # "Kein Vorschlag verfuegbar" zu lesen und das Muster von Hand zu pflegen.
        raise HTTPException(
            status_code=503,
            detail=f"Recherche gerade nicht möglich ({exc}) — bitte in einer Minute erneut.",
            headers={"Retry-After": "60"},
        ) from exc
    if suggestion is None:
        raise HTTPException(status_code=502, detail="Kein Vorschlag verfügbar")
    return suggestion
```

Run: `pytest tests/test_llm_suggest.py tests/test_aircraft_specs.py tests/test_admin_api.py -v`
Expected: PASS — kein bestehender Test bricht. Bricht einer, weil er auf `None` bei einem Timeout-Fake bestand, ist **der Test** anzupassen: das alte Verhalten war der Bug.

- [ ] **Step 6: Commit**

```bash
git add app/llm.py app/main.py tests/test_llm_transient.py
git commit -m "fix(llm): voruebergehenden Recherche-Fehler von 'keine Daten' trennen

suggest_aircraft_payload() gab bei overloaded_error/Timeout/5xx dasselbe None zurueck wie
bei einem unauffindbaren Muster. Der Poller merkte sich den Code daraufhin dauerhaft als
erledigt -- AP32 blieb dadurch zwei Monate ohne Eintrag (gemessen 2026-07-30,
request_id req_011CdXwhjTLWqCv5VGe2KbMv).

Neu: TransientResearchError + is_transient_error(). Der Admin-Endpunkt antwortet bei
transientem Fehler mit 503 + Retry-After statt 502 'Kein Vorschlag verfuegbar'."
```

---

### Task 2: Tabelle `payload_research` und der Backoff-Helfer

Der Versuchszustand kann **nicht** in `aircraft_payloads` liegen: dort ist `payload_kg NOT NULL`, jede Zeile ist eine Aussage über die Tragfähigkeit eines Musters. Ein gescheiterter Versuch hat aber gerade keine Zuladung. Deshalb eine eigene, schlanke Tabelle.

**Files:**
- Modify: `app/database.py` (`_DDL`; neue Funktionen am Ende des Zuladungs-Abschnitts, nach `get_payload_map` bei Zeile 4155)
- Test: `tests/test_payload_research_state.py` (Create)

**Interfaces:**
- Consumes: `normalize_type_code(code: str | None) -> str` (`app/database.py:4136`)
- Produces:
  - `next_retry_delay_s(attempts: int) -> int` — Backoff-Staffel; `attempts=1 → 300`, `2 → 1800`, `3 → 14400`, `≥4 → 86400`.
  - `is_retry_due(state: str, attempts: int, checked_at: str | None, now: datetime) -> bool`
  - `get_payload_research(conn, type_code: str) -> dict | None` — `{state, attempts, checked_at, last_error}`
  - `mark_payload_research(conn, type_code: str, state: str, now: datetime, last_error: str | None = None) -> None` — `state ∈ {'ok','nichts_gefunden','fehler'}`; bei `'fehler'` wird `attempts` erhöht, sonst auf 0 zurückgesetzt.
  - `payload_research_candidates(conn, now: datetime, limit: int) -> list[str]` — Typcodes aus dem Flugbestand ohne `aircraft_payloads`-Eintrag, deren Versuch fällig ist; nach Flugzahl absteigend.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_payload_research_state.py
"""Versuchszustand der Zuladungs-Recherche liegt in der DB, nicht im Prozessgedaechtnis.

Rev.-2-Befund (B4): ein Backoff ohne Ausfuehrer ist kein Retry. Und der Zustand darf einen
Prozess-Neustart ueberleben, sonst ist die Reparatur nur eine andere Form derselben Luecke.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    get_connection,
    get_payload_research,
    init_db,
    is_retry_due,
    mark_payload_research,
    next_retry_delay_s,
    payload_research_candidates,
    upsert_payload,
)

T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    c = get_connection(db)
    yield c
    c.close()


def _flug(c, cid, code_icao, code_short, ts):
    c.execute(
        "INSERT INTO flight_cache (cid, callsign, aircraft, aircraft_icao, logon_time) "
        "VALUES (?,?,?,?,?)",
        (cid, "FRS1", code_short, code_icao, ts),
    )


def test_backoff_staffel():
    assert next_retry_delay_s(1) == 300      # 5 min
    assert next_retry_delay_s(2) == 1800     # 30 min
    assert next_retry_delay_s(3) == 14400    # 4 h
    assert next_retry_delay_s(4) == 86400    # taeglich
    assert next_retry_delay_s(99) == 86400


def test_retry_erst_nach_ablauf_faellig():
    """Der Kern von B4: bei t0+2min NICHT, bei t0+6min DOCH."""
    ts = T0.isoformat().replace("+00:00", "Z")
    assert is_retry_due("fehler", 1, ts, T0 + timedelta(minutes=2)) is False
    assert is_retry_due("fehler", 1, ts, T0 + timedelta(minutes=6)) is True


def test_ok_ist_nie_faellig_nichts_gefunden_nach_30_tagen():
    ts = T0.isoformat().replace("+00:00", "Z")
    assert is_retry_due("ok", 0, ts, T0 + timedelta(days=999)) is False
    assert is_retry_due("nichts_gefunden", 0, ts, T0 + timedelta(days=29)) is False
    assert is_retry_due("nichts_gefunden", 0, ts, T0 + timedelta(days=31)) is True


def test_neu_und_unbekannt_sind_sofort_faellig():
    assert is_retry_due("neu", 0, None, T0) is True


def test_fehler_erhoeht_attempts_erfolg_setzt_zurueck(conn):
    mark_payload_research(conn, "AP32", "fehler", T0, last_error="Overloaded")
    assert get_payload_research(conn, "AP32")["attempts"] == 1
    mark_payload_research(conn, "AP32", "fehler", T0, last_error="Overloaded")
    row = get_payload_research(conn, "AP32")
    assert row["attempts"] == 2
    assert row["state"] == "fehler"
    assert row["last_error"] == "Overloaded"
    mark_payload_research(conn, "AP32", "ok", T0)
    row = get_payload_research(conn, "AP32")
    assert row["attempts"] == 0
    assert row["state"] == "ok"


def test_schluessel_wird_normalisiert(conn):
    mark_payload_research(conn, "ap32/l-sdgy", "fehler", T0)
    assert get_payload_research(conn, "AP32") is not None


def test_zustand_ueberlebt_neue_verbindung(tmp_path):
    """Genau das, was das In-Memory-Set nicht konnte."""
    db = str(tmp_path / "p.db")
    init_db(db)
    c1 = get_connection(db)
    mark_payload_research(c1, "AP32", "fehler", T0, last_error="Overloaded")
    c1.commit()
    c1.close()
    c2 = get_connection(db)
    assert get_payload_research(c2, "AP32")["attempts"] == 1
    c2.close()


def test_kandidaten_kommen_aus_dem_flugbestand_beide_spalten(conn):
    """B1: aircraft_icao ist erst seit 2026-06-09 gefuellt. Altfluege stehen nur in aircraft."""
    _flug(conn, 1, None, "P28S", "2025-06-06T10:00:00Z")   # nur Anzeige-Spalte
    _flug(conn, 2, "AP32", "AP32", "2026-07-25T10:00:00Z") # beide
    _flug(conn, 3, "", "FK9", "2026-04-13T10:00:00Z")      # icao leer, nicht NULL
    conn.commit()
    assert set(payload_research_candidates(conn, T0, limit=10)) == {"P28S", "AP32", "FK9"}


def test_kandidat_faellt_weg_wenn_eintrag_existiert(conn):
    _flug(conn, 1, "AP32", "AP32", "2026-07-25T10:00:00Z")
    upsert_payload(conn, "AP32", mtow_kg=600.0, empty_kg=350.0, fuel_kg=40.0,
                   fuel_full_kg=80.0, crew_kg=85.0, source="llm", make_model="Aeroprakt A-32")
    conn.commit()
    assert payload_research_candidates(conn, T0, limit=10) == []


def test_kandidat_zaehlt_jeden_flug_nur_einmal(conn):
    """Nie per OR addieren: eine Zeile mit beiden Spalten ist EIN Flug."""
    _flug(conn, 1, "AP32", "AP32", "2026-07-25T10:00:00Z")
    _flug(conn, 2, None, "P28S", "2025-06-06T10:00:00Z")
    _flug(conn, 3, None, "P28S", "2025-06-07T10:00:00Z")
    conn.commit()
    # P28S (2 Fluege) vor AP32 (1 Flug)
    assert payload_research_candidates(conn, T0, limit=10) == ["P28S", "AP32"]


def test_nicht_faellige_kandidaten_fehlen(conn):
    _flug(conn, 1, "AP32", "AP32", "2026-07-25T10:00:00Z")
    conn.commit()
    mark_payload_research(conn, "AP32", "fehler", T0, last_error="Overloaded")
    conn.commit()
    assert payload_research_candidates(conn, T0 + timedelta(minutes=2), limit=10) == []
    assert payload_research_candidates(conn, T0 + timedelta(minutes=6), limit=10) == ["AP32"]


def test_limit_greift(conn):
    for i, code in enumerate(["P28S", "AP32", "FK9"]):
        _flug(conn, i, code, code, "2026-07-25T10:00:00Z")
    conn.commit()
    assert len(payload_research_candidates(conn, T0, limit=2)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_payload_research_state.py -v`
Expected: FAIL — `ImportError: cannot import name 'next_retry_delay_s' from 'app.database'`

- [ ] **Step 3: Write minimal implementation**

In `app/database.py`, in `_DDL` neben `CREATE TABLE IF NOT EXISTS aircraft_payloads` einfügen:

```sql
CREATE TABLE IF NOT EXISTS payload_research (
    type_code   TEXT PRIMARY KEY,   -- normalize_type_code()
    state       TEXT NOT NULL,      -- 'ok' | 'nichts_gefunden' | 'fehler'
    attempts    INTEGER NOT NULL DEFAULT 0,
    checked_at  TEXT,
    last_error  TEXT
);
```

Nach `get_payload_map` (`app/database.py:4155`) anfügen:

```python
# Backoff der Recherche-Wiederholung. Bewusst grob gestaffelt: ein überlasteter Anbieter ist
# meist in Minuten wieder da, ein dauerhaft fehlschlagendes Muster soll aber nicht stündlich
# Geld kosten (~4 ct je Recherche, docs/architecture.md).
_RETRY_STAFFEL_S = (300, 1800, 14400)      # 5 min, 30 min, 4 h
_RETRY_MAX_S = 86400                        # danach täglich
_NICHTS_GEFUNDEN_ERNEUT_S = 30 * 86400      # inhaltlich erledigt: nach 30 Tagen erneut


def next_retry_delay_s(attempts: int) -> int:
    """Abstand bis zum nächsten Versuch, nach ``attempts`` Fehlschlägen (in Sekunden)."""
    if attempts <= 0:
        return 0
    if attempts <= len(_RETRY_STAFFEL_S):
        return _RETRY_STAFFEL_S[attempts - 1]
    return _RETRY_MAX_S


def _parse_iso_utc(ts: str | None) -> datetime | None:
    """ISO-8601 mit 'Z' oder Offset zu einem aware datetime; None bei Unbrauchbarem."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_retry_due(state: str, attempts: int, checked_at: str | None, now: datetime) -> bool:
    """Ist ein erneuter Versuch fällig?

    ``ok`` nie. ``nichts_gefunden`` nach 30 Tagen (die Welt kann sich geändert haben, das
    Muster aber nicht stündlich). ``fehler`` nach der Backoff-Staffel — ein transienter
    Fehler ist KEIN Endzustand (AP32-Fall). Unbekannter Zustand oder unlesbares
    ``checked_at``: sofort fällig, im Zweifel lieber einmal zu viel versuchen.
    """
    if state == "ok":
        return False
    seit = _parse_iso_utc(checked_at)
    if seit is None:
        return True
    if state == "nichts_gefunden":
        wartezeit = _NICHTS_GEFUNDEN_ERNEUT_S
    elif state == "fehler":
        wartezeit = next_retry_delay_s(attempts)
    else:
        return True
    return (now - seit).total_seconds() >= wartezeit


def get_payload_research(conn: sqlite3.Connection, type_code: str) -> dict | None:
    """Versuchszustand eines Typcodes oder ``None``, wenn nie versucht wurde."""
    code = normalize_type_code(type_code)
    if not code:
        return None
    row = conn.execute(
        "SELECT state, attempts, checked_at, last_error FROM payload_research WHERE type_code = ?",
        (code,),
    ).fetchone()
    return dict(row) if row is not None else None


def mark_payload_research(
    conn: sqlite3.Connection,
    type_code: str,
    state: str,
    now: datetime,
    last_error: str | None = None,
) -> None:
    """Versuchszustand festschreiben. ``attempts`` zählt NUR Fehlschläge."""
    code = normalize_type_code(type_code)
    if not code:
        return
    ts = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if state == "fehler":
        conn.execute(
            """INSERT INTO payload_research (type_code, state, attempts, checked_at, last_error)
               VALUES (?, 'fehler', 1, ?, ?)
               ON CONFLICT(type_code) DO UPDATE SET
                   state='fehler',
                   attempts = payload_research.attempts + 1,
                   checked_at = excluded.checked_at,
                   last_error = excluded.last_error""",
            (code, ts, last_error),
        )
        return
    conn.execute(
        """INSERT INTO payload_research (type_code, state, attempts, checked_at, last_error)
           VALUES (?, ?, 0, ?, ?)
           ON CONFLICT(type_code) DO UPDATE SET
               state = excluded.state,
               attempts = 0,
               checked_at = excluded.checked_at,
               last_error = excluded.last_error""",
        (code, state, ts, last_error),
    )


# Maßgebliche Spalte für den Flugbestand (Rev.-2-Befund B1): `aircraft_icao` existiert erst
# seit 2026-06-09 und ist nur in 357 von 2256 Zeilen gefüllt — angezeigt und angeklickt wird
# `aircraft` (2232 Zeilen). COALESCE liefert GENAU EINEN Wert je Flug; die beiden Spalten
# dürfen nie per OR addiert werden (Doppelzählung). Bei 358 Zeilen sind beide gefüllt, in 357
# stimmen sie überein.
FLIGHT_TYPE_CODE_SQL = """
    upper(substr(
        COALESCE(NULLIF(aircraft_icao, ''), aircraft), 1,
        CASE WHEN instr(COALESCE(NULLIF(aircraft_icao, ''), aircraft), '/') > 0
             THEN instr(COALESCE(NULLIF(aircraft_icao, ''), aircraft), '/') - 1
             ELSE length(COALESCE(NULLIF(aircraft_icao, ''), aircraft)) END))
"""


def payload_research_candidates(
    conn: sqlite3.Connection, now: datetime, limit: int
) -> list[str]:
    """Typcodes aus dem Flugbestand ohne Zuladungseintrag, deren Versuch fällig ist.

    Nach Flugzahl absteigend — was oft geflogen wird, zuerst. Die Fälligkeit wird in Python
    entschieden (``is_retry_due``), damit die Backoff-Regel an einer Stelle steht.
    """
    rows = conn.execute(
        f"""SELECT {FLIGHT_TYPE_CODE_SQL} AS code, COUNT(*) AS n,
                   r.state AS state, r.attempts AS attempts, r.checked_at AS checked_at
              FROM flight_cache f
              LEFT JOIN aircraft_payloads p ON p.type_code = {FLIGHT_TYPE_CODE_SQL}
              LEFT JOIN payload_research  r ON r.type_code = {FLIGHT_TYPE_CODE_SQL}
             WHERE COALESCE(NULLIF(aircraft_icao, ''), aircraft) IS NOT NULL
               AND COALESCE(NULLIF(aircraft_icao, ''), aircraft) != ''
               AND p.type_code IS NULL
             GROUP BY code
             ORDER BY n DESC, code ASC"""
    ).fetchall()
    faellig = [
        r["code"] for r in rows
        if r["code"] and is_retry_due(r["state"] or "neu", r["attempts"] or 0,
                                     r["checked_at"], now)
    ]
    return faellig[:limit]
```

Sicherstellen, dass `datetime`, `timezone` und `timedelta` in `app/database.py` importiert sind (oben in der Importliste prüfen; `datetime` wird dort schon verwendet).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_payload_research_state.py -v`
Expected: PASS (11 Tests)

- [ ] **Step 5: Commit**

```bash
git add app/database.py tests/test_payload_research_state.py
git commit -m "feat(db): Versuchszustand der Zuladungs-Recherche in die DB

Neue Tabelle payload_research (state/attempts/checked_at/last_error) plus Backoff-Helfer
next_retry_delay_s/is_retry_due und die Kandidatenabfrage payload_research_candidates.

Der Zustand kann nicht in aircraft_payloads liegen: payload_kg ist NOT NULL, jede Zeile dort
ist eine Aussage ueber die Tragfaehigkeit -- ein gescheiterter Versuch hat keine.

FLIGHT_TYPE_CODE_SQL haelt die massgebliche Spalte an einer Stelle fest:
COALESCE(NULLIF(aircraft_icao,''), aircraft). aircraft_icao ist erst seit 2026-06-09
gefuellt (357 von 2256 Zeilen); die Kandidatenabfrage haette sonst 30 von 33 Luecken
uebersehen."
```

---

### Task 3: `_auto_research_payload` benutzt den DB-Zustand

**Files:**
- Modify: `app/poller.py:379` (`_payload_research_attempted` entfernen), `:886-903` (Auslöser im Poll), `:1387-1412` (`_auto_research_payload`)
- Test: `tests/test_payload_research_poller.py` (Create)

**Interfaces:**
- Consumes: `llm.TransientResearchError`, `llm.suggest_aircraft_payload` (Task 1); `get_payload_research`, `mark_payload_research`, `is_retry_due`, `payload_research_candidates` (Task 2)
- Produces:
  - `VatsimPoller._auto_research_payload(type_code: str) -> None` — Signatur unverändert; schreibt jetzt den Zustand.
  - `VatsimPoller._research_due_payloads() -> None` — ein Lauf über fällige Kandidaten, serialisiert, mit Deckel.
  - `VatsimPoller._PAYLOAD_RESEARCH_LIMIT: int = 5` — Muster je Lauf.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_payload_research_poller.py
"""Der AP32-Regressionstest.

Gemessen 2026-07-30: poller.py:892 setzte _payload_research_attempted.add(code) VOR dem
Versuch und nahm den Code bei Misserfolg nie wieder heraus. Ein zweiter Anlauf brauchte einen
Prozess-Neustart UND einen Piloten, der genau dieses Muster wieder live fliegt.

Der Test aus Rev. 1 ("ein zweiter Lauf versucht es erneut") waere gruen gewesen, ohne dass je
ein zweiter Lauf stattfindet. Deshalb hier mit kontrollierter Uhr: bei t0+2min NICHT, bei
t0+6min DOCH.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import llm
from app.database import (
    get_connection,
    get_payload_research,
    init_db,
    mark_payload_research,
)

T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _poller(db_path):
    from app.poller import VatsimPoller
    return VatsimPoller(db_path=db_path, callsign_prefix="FRS")


def _flug(db_path, cid, code, ts):
    c = get_connection(db_path)
    c.execute(
        "INSERT INTO flight_cache (cid, callsign, aircraft, logon_time) VALUES (?,?,?,?)",
        (cid, "FRS1", code, ts),
    )
    c.commit()
    c.close()


@pytest.mark.asyncio
async def test_transienter_fehler_sperrt_nicht_dauerhaft(db, monkeypatch):
    p = _poller(db)
    versuche = []

    def _fake(code):
        versuche.append(code)
        raise llm.TransientResearchError("Overloaded")

    monkeypatch.setattr(llm, "suggest_aircraft_payload", _fake)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._auto_research_payload("AP32")
    assert versuche == ["AP32"]
    row = get_payload_research(get_connection(db), "AP32")
    assert row["state"] == "fehler"
    assert row["attempts"] == 1

    # Zu frueh: kein zweiter Versuch.
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(minutes=2))
    await p._auto_research_payload("AP32")
    assert versuche == ["AP32"], "Backoff nicht eingehalten"

    # Faellig: erneut.
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(minutes=6))
    await p._auto_research_payload("AP32")
    assert versuche == ["AP32", "AP32"], "transienter Fehler wurde als endgueltig behandelt"


@pytest.mark.asyncio
async def test_keine_daten_wird_nicht_stuendlich_wiederholt(db, monkeypatch):
    p = _poller(db)
    versuche = []
    monkeypatch.setattr(llm, "suggest_aircraft_payload",
                        lambda code: versuche.append(code) or None)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._auto_research_payload("NAV")
    assert get_payload_research(get_connection(db), "NAV")["state"] == "nichts_gefunden"
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(days=29))
    await p._auto_research_payload("NAV")
    assert len(versuche) == 1
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(days=31))
    await p._auto_research_payload("NAV")
    assert len(versuche) == 2


@pytest.mark.asyncio
async def test_erfolg_schreibt_payload_und_ok(db, monkeypatch):
    p = _poller(db)
    monkeypatch.setattr(llm, "suggest_aircraft_payload", lambda code: {
        "make_model": "Aeroprakt A-32 Vixxen", "mtow_kg": 600.0, "empty_kg": 350.0,
        "fuel_kg": 40.0, "fuel_full_kg": 80.0, "crew_kg": 85.0, "payload_kg": 125.0,
    })
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._auto_research_payload("AP32")
    c = get_connection(db)
    assert get_payload_research(c, "AP32")["state"] == "ok"
    row = c.execute(
        "SELECT make_model, source FROM aircraft_payloads WHERE type_code='AP32'"
    ).fetchone()
    assert row["make_model"] == "Aeroprakt A-32 Vixxen"
    assert row["source"] == "llm"


@pytest.mark.asyncio
async def test_manuell_gepflegt_wird_nie_ueberschrieben(db, monkeypatch):
    from app.database import upsert_payload
    c = get_connection(db)
    upsert_payload(c, "AP32", mtow_kg=1.0, empty_kg=1.0, fuel_kg=1.0, fuel_full_kg=1.0,
                   crew_kg=85.0, source="manual", make_model="Von Hand")
    c.commit()
    p = _poller(db)
    monkeypatch.setattr(llm, "suggest_aircraft_payload",
                        lambda code: pytest.fail("darf nicht aufgerufen werden"))
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._auto_research_payload("AP32")
    row = get_connection(db).execute(
        "SELECT make_model FROM aircraft_payloads WHERE type_code='AP32'"
    ).fetchone()
    assert row["make_model"] == "Von Hand"


@pytest.mark.asyncio
async def test_nachlese_holt_altbestand_und_haelt_den_deckel(db, monkeypatch):
    """30 der 33 Luecken sind Altfluege ohne aircraft_icao -- ohne Nachlese unerreichbar."""
    for i, code in enumerate(["P28S", "P28S", "AP32", "FK9", "M20T", "PA60", "C195", "B58T"]):
        _flug(db, i, code, "2025-06-06T10:00:00Z")
    p = _poller(db)
    geholt = []
    monkeypatch.setattr(llm, "suggest_aircraft_payload",
                        lambda code: geholt.append(code) or None)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._research_due_payloads()
    assert len(geholt) == p._PAYLOAD_RESEARCH_LIMIT, "Deckel je Lauf nicht eingehalten"
    assert geholt[0] == "P28S", "haeufigstes Muster nicht zuerst"


@pytest.mark.asyncio
async def test_nachlese_stirbt_nicht_an_einem_einzelnen_fehler(db, monkeypatch):
    for i, code in enumerate(["AP32", "FK9"]):
        _flug(db, i, code, "2026-07-25T10:00:00Z")
    p = _poller(db)
    gesehen = []

    def _fake(code):
        gesehen.append(code)
        if code == "AP32":
            raise RuntimeError("irgendwas Unerwartetes")
        return None

    monkeypatch.setattr(llm, "suggest_aircraft_payload", _fake)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._research_due_payloads()   # darf nicht durchschlagen
    assert set(gesehen) == {"AP32", "FK9"}


@pytest.mark.asyncio
async def test_in_memory_set_ist_weg(db):
    """Explizit: der alte Mechanismus darf nicht als zweite Wahrheit zurueckkommen."""
    p = _poller(db)
    assert not hasattr(p, "_payload_research_attempted")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_payload_research_poller.py -v`
Expected: FAIL — `AttributeError: 'VatsimPoller' object has no attribute '_now'` bzw. `_research_due_payloads`; `test_in_memory_set_ist_weg` schlägt fehl, weil das Attribut noch existiert.

- [ ] **Step 3: Write minimal implementation**

`app/poller.py:379` — die Zeile `self._payload_research_attempted: set[str] = set()` **löschen** und eine Uhr einführen (damit Tests sie kontrollieren können). In `__init__` ergänzen:

```python
        self._PAYLOAD_RESEARCH_LIMIT = 5   # Muster je Nachlese-Lauf (~4 ct und ~30 s je Stück)
```

Als Methode auf `VatsimPoller`:

```python
    @staticmethod
    def _now() -> datetime:
        """Aktuelle Zeit — als Methode, damit Tests sie kontrollieren können."""
        return datetime.now(timezone.utc)
```

`app/poller.py:886-903` — der Auslöser im Poll kennt kein Set mehr, sondern fragt die DB:

```python
                # Neu gesehene Flugzeugtypen: Zuladung automatisch recherchieren + vorbefüllen
                # (Admin kann die Werte jederzeit überschreiben; source='llm' kennzeichnet sie).
                # Der Versuchszustand steht in payload_research, NICHT in einem Set im
                # Prozessgedächtnis — sonst überlebt ein Fehlschlag den Neustart als "erledigt"
                # (AP32-Fall 2026-07-30).
                from app.database import get_payload_map, get_payload_research, is_retry_due
                known_types = set(get_payload_map(conn).keys())
                jetzt = self._now()
                new_codes = []
                for pos in current.values():
                    code = normalize_type_code(pos.get("aircraft_icao") or pos.get("aircraft_short"))
                    if not code or code in known_types or code in new_codes:
                        continue
                    st = get_payload_research(conn, code)
                    if st is None or is_retry_due(st["state"], st["attempts"],
                                                  st["checked_at"], jetzt):
                        new_codes.append(code)
```

`_auto_research_payload` (`app/poller.py:1387`) vollständig ersetzen:

```python
    async def _auto_research_payload(self, type_code: str) -> None:
        """Zuladung eines Musters recherchieren und vorbefüllen (source='llm').

        Silent-Fail nach außen, aber der Ausgang wird in ``payload_research`` festgehalten:

        - Erfolg → ``ok``
        - kein Ergebnis (``None``) → ``nichts_gefunden`` (nach 30 Tagen erneut)
        - transienter Fehler → ``fehler`` mit Backoff; **kein Endzustand**

        Der Unterschied ist der ganze Punkt: ``Overloaded`` ist kein „keine Daten".
        """
        from app import llm
        from app.database import (
            get_payload_map, get_payload_research, is_retry_due,
            mark_payload_research, upsert_payload,
        )
        code = normalize_type_code(type_code)
        if not code:
            return
        jetzt = self._now()
        conn = get_connection(self.db_path)
        try:
            if code in get_payload_map(conn):
                return  # inzwischen (manuell) gepflegt → nicht anfassen
            st = get_payload_research(conn, code)
            if st is not None and not is_retry_due(st["state"], st["attempts"],
                                                   st["checked_at"], jetzt):
                return  # Backoff läuft noch
        finally:
            conn.close()

        try:
            s = await asyncio.to_thread(llm.suggest_aircraft_payload, code)
        except llm.TransientResearchError as exc:
            conn = get_connection(self.db_path)
            try:
                mark_payload_research(conn, code, "fehler", jetzt, last_error=str(exc)[:200])
                conn.commit()
            finally:
                conn.close()
            logger.info("Auto-Zuladung %s: vorübergehend gescheitert (%s) — wird wiederholt",
                        code, exc)
            return
        except Exception as exc:  # noqa: BLE001 — nie einen Poll-Durchlauf reißen
            conn = get_connection(self.db_path)
            try:
                mark_payload_research(conn, code, "fehler", jetzt, last_error=str(exc)[:200])
                conn.commit()
            finally:
                conn.close()
            logger.exception("Auto-Zuladung %s: unerwarteter Fehler", code)
            return

        conn = get_connection(self.db_path)
        try:
            if s is None:
                mark_payload_research(conn, code, "nichts_gefunden", jetzt)
                conn.commit()
                logger.info("Auto-Zuladung: keine Daten für %s gefunden", code)
                return
            if code in get_payload_map(conn):
                mark_payload_research(conn, code, "ok", jetzt)
                conn.commit()
                return  # inzwischen manuell gepflegt
            upsert_payload(
                conn, code,
                mtow_kg=s.get("mtow_kg"), empty_kg=s.get("empty_kg"),
                fuel_kg=s.get("fuel_kg", s.get("fuel_full_kg")),
                fuel_full_kg=s.get("fuel_full_kg"),
                crew_kg=s.get("crew_kg"), source="llm",
                make_model=s.get("make_model"),
            )
            mark_payload_research(conn, code, "ok", jetzt)
            conn.commit()
        finally:
            conn.close()
        logger.info("Auto-Zuladung vorbefüllt: %s (%s)", code, s.get("make_model"))

    async def _research_due_payloads(self) -> None:
        """Nachlese: fällige Muster aus dem Flugbestand, serialisiert und gedeckelt.

        30 der 33 Lücken vom 2026-07-30 sind Altflüge, die vor Einführung der Auto-Recherche
        (2026-07-02) stattfanden — der Live-Auslöser erreicht sie nie. Serialisiert und mit
        Deckel, weil jede Recherche ~4 ct und ~30 s kostet und ein einzelner Request schon
        einmal über 9 Minuten lief (docs/architecture.md:202).
        """
        try:
            from app.database import payload_research_candidates
            jetzt = self._now()
            conn = get_connection(self.db_path)
            try:
                codes = payload_research_candidates(
                    conn, jetzt, limit=self._PAYLOAD_RESEARCH_LIMIT
                )
            finally:
                conn.close()
            if not codes:
                return
            logger.info("Zuladungs-Nachlese: %d Muster (%s)", len(codes), ", ".join(codes))
            for code in codes:
                await self._auto_research_payload(code)   # serialisiert, nie parallel
        except Exception:
            logger.exception("Error in _research_due_payloads")
```

Sicherstellen, dass `datetime`/`timezone` in `app/poller.py` importiert sind.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_payload_research_poller.py -v`
Expected: PASS (7 Tests)

- [ ] **Step 5: Regression der bestehenden Poller-Tests**

Run: `pytest tests/test_poller.py -v`
Expected: PASS. Ein Test, der `_payload_research_attempted` benutzt, ist auf den DB-Zustand umzuschreiben — das Attribut ist absichtlich weg.

- [ ] **Step 6: Commit**

```bash
git add app/poller.py tests/test_payload_research_poller.py
git commit -m "fix(poller): Zuladungs-Recherche wiederholen statt vergessen (AP32)

_payload_research_attempted (Set im Prozessgedaechtnis) ist weg. Der Versuchszustand steht
in payload_research: Erfolg -> ok, kein Ergebnis -> nichts_gefunden (30 Tage), transienter
Fehler -> fehler mit Backoff und ohne Endzustand.

Neu _research_due_payloads(): Nachlese ueber den Flugbestand, serialisiert, Deckel 5 Muster
je Lauf. 30 der 33 Luecken stammen von Fluegen VOR Einfuehrung der Auto-Recherche
(2026-07-02) -- der Live-Ausloeser erreicht sie nie.

Regressionstest mit kontrollierter Uhr: bei t0+2min kein zweiter Versuch, bei t0+6min doch.
Der Rev.-1-Test 'zwei Laeufe versuchen es zweimal' waere gruen gewesen, ohne dass je ein
zweiter Lauf stattfindet."
```

---

### Task 4: Die zwei Jobs registrieren

Ohne Ausführer ist der Backoff aus Task 2 Dekoration — das war Rev.-2-Befund B4.

**Files:**
- Modify: `app/poller.py:479-490` (Job-Block, nach `statsim_track_fetch`)
- Test: `tests/test_payload_research_poller.py` (erweitern)

**Interfaces:**
- Consumes: `VatsimPoller._research_due_payloads` (Task 3)
- Produces: Jobs mit den IDs `payload_research_initial` (einmalig kurz nach Start) und `payload_research_retry` (alle 5 min).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_payload_research_poller.py — anfügen
def test_beide_jobs_sind_registriert(db):
    """B4: ein Backoff ohne Ausfuehrer ist kein Retry."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    p = _poller(db)
    p._scheduler = AsyncIOScheduler()
    p._register_jobs()
    ids = {j.id for j in p._scheduler.get_jobs()}
    assert "payload_research_retry" in ids
    assert "payload_research_initial" in ids
    job = p._scheduler.get_job("payload_research_retry")
    assert job.trigger.interval.total_seconds() == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_payload_research_poller.py::test_beide_jobs_sind_registriert -v`
Expected: FAIL — `AttributeError: 'VatsimPoller' object has no attribute '_register_jobs'`

- [ ] **Step 3: Write minimal implementation**

In `app/poller.py`: den bestehenden Block der `self._scheduler.add_job(...)`-Aufrufe (ab `app/poller.py:416`, direkt nach `self._scheduler = AsyncIOScheduler()`) in eine eigene Methode `_register_jobs(self) -> None` verschieben und an der alten Stelle durch `self._register_jobs()` ersetzen. Der Inhalt bleibt unverändert; ergänzt werden am Ende:

```python
        # Zuladungs-Nachlese (Teil 8): einmalig kurz nach Start den Altbestand angehen …
        self._scheduler.add_job(
            self._research_due_payloads,
            "date",
            id="payload_research_initial",
        )
        # … und danach regelmäßig die fälligen Wiederholungen. OHNE diesen Job ist der
        # Backoff aus is_retry_due() reine Dekoration: der Live-Auslöser reagiert nur auf NEU
        # gesehene Muster, ein 'fehler' bliebe bis zum nächsten Container-Neubau liegen.
        self._scheduler.add_job(
            self._research_due_payloads,
            "interval",
            minutes=5,
            id="payload_research_retry",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_payload_research_poller.py -v`
Expected: PASS (8 Tests)

- [ ] **Step 5: Commit**

```bash
git add app/poller.py tests/test_payload_research_poller.py
git commit -m "feat(poller): Ausfuehrer fuer die Zuladungs-Nachlese registrieren

Job-Registrierung nach _register_jobs() ausgelagert (testbar) und zwei Jobs ergaenzt:
payload_research_initial (einmalig nach Start) und payload_research_retry (alle 5 min).

Rev.-2-Befund B4: der Backoff war definiert, aber nichts stiess ihn an -- der Live-Ausloeser
reagiert nur auf NEU gesehene Muster, ein 'fehler' waere bis zum naechsten Container-Neubau
liegen geblieben. Strukturell dieselbe Luecke wie AP32, nur mit DB-Zustand statt Set."
```

---

### Task 5: CHANGELOG und Version

**Files:**
- Modify: `app/CHANGELOG.json` (neuer Eintrag ganz vorne)

**Interfaces:**
- Consumes: nichts
- Produces: `app.version.VERSION == "10.5.0"` (gelesen aus `CHANGELOG[0]["version"]`)

- [ ] **Step 1: Neuen Eintrag ganz vorne einfügen**

```json
  {
    "version": "10.5.0",
    "date": "2026-07-30",
    "highlight": false,
    "title": "Neue Muster werden nicht mehr vergessen",
    "items": [
      "🔎 Wenn ein Muster zum ersten Mal auftaucht, recherchiert FriesenSpy Gewichte und Namen selbst. War der KI-Dienst in diesem Moment gerade überlastet, galt das Muster bisher als „abgehakt\" — und wurde nie wieder angefasst. Genau das war der Aeroprakt A-32 (AP32) passiert, der deshalb zwei Monate ohne Eintrag blieb. Ein vorübergehender Fehler wird jetzt als solcher erkannt und später erneut versucht.",
      "📚 Dazu holt FriesenSpy den Altbestand nach: 33 Muster aus eurem Flugbuch hatten noch keine Zuladungsdaten, die meisten davon Flüge von vor Juli — aus einer Zeit, in der es die automatische Recherche noch nicht gab. Sie werden im Hintergrund nachgetragen, gedrosselt und der Reihe nach, häufig geflogene zuerst."
    ]
  },
```

- [ ] **Step 2: Version prüfen**

Run: `python -c "from app.version import VERSION; print(VERSION)"`
Expected: `10.5.0`

- [ ] **Step 3: Volle Suite**

Run: `pytest tests/ -q`
Expected: PASS, keine Regression.

- [ ] **Step 4: Commit**

```bash
git add app/CHANGELOG.json
git commit -m "V10.5.0: Zuladungs-Recherche mit Retry und Nachlese"
```

- [ ] **Step 5: Abnahme am laufenden System (nach dem Deploy)**

Der Push auf `main` deployt. Danach auf dem Server prüfen, dass die Nachlese läuft und den Altbestand angeht:

```bash
docker logs friesenspy-friesenspy-1 2>&1 | grep -i "Zuladungs-Nachlese\|Auto-Zuladung"
sudo sqlite3 'file:/opt/friesenspy/data/friesenspy.db?mode=ro' \
  "SELECT state, COUNT(*) FROM payload_research GROUP BY state;"
```

Erwartet: Log-Zeilen der Nachlese; nach einigen Läufen Einträge mit `ok` und (für `NAV`, `AERO`, `F22`, `182`) `nichts_gefunden`. **`nichts_gefunden` ist für diese vier der richtige Endzustand, kein Fehler** — es sind keine Flugzeuge.

---

## Self-Review

**Spec-Abdeckung (Teil 8 der Spec, Rev. 2):**

| Spec-Anforderung | Task |
|---|---|
| Transienten Fehler von „nichts gefunden" unterscheiden | 1 |
| Code bei transientem Fehler nicht dauerhaft merken | 3 |
| Zustand + Backoff in der DB | 2 |
| Periodischer Retry-Job (B4) | 4 |
| Nachlese über die maßgebliche Spalte, nicht `DISTINCT aircraft_icao` (B1) | 2 (`FLIGHT_TYPE_CODE_SQL`), 3 |
| Test mit kontrollierter Uhr, nicht „zwei Läufe versuchen es zweimal" | 3 |
| Serialisiert, harter Deckel je Lauf, Kostenargument | 3 (`_PAYLOAD_RESEARCH_LIMIT`), 4 |
| Müllcodes enden als `nichts_gefunden` — richtiger Endzustand | 3, 5 (Abnahme) |
| LLM-Ergebnisse im Admin als solche sichtbar (`source='llm'`, `checked_at`) | `source='llm'` in Task 3; die Admin-**Anzeige** von `payload_research` gehört zu Plan B, Task 7 (dort ist das Panel) — hier bewusst nicht |

**Platzhalter:** keine. Jeder Code-Schritt enthält den vollständigen Code.

**Typ-Konsistenz:** `next_retry_delay_s`, `is_retry_due`, `get_payload_research`, `mark_payload_research`, `payload_research_candidates`, `FLIGHT_TYPE_CODE_SQL`, `TransientResearchError`, `is_transient_error`, `_now`, `_research_due_payloads`, `_register_jobs`, `_PAYLOAD_RESEARCH_LIMIT` — in Tasks 1–4 durchgängig gleich geschrieben. `mark_payload_research` nimmt überall `now: datetime` als Positionsargument nach `state`.

**Offen und bewusst außerhalb:** Die Admin-Sichtbarkeit des Recherche-Zustands (`payload_research` im Admin anzeigen) liegt in Plan B, weil dort das Muster-Panel entsteht. Teil 8 bleibt dadurch ohne UI-Änderung — und damit klein und schnell auslieferbar.
