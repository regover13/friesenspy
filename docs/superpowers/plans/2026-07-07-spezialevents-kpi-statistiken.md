# Spezial-Events-KPIs im Statistiken-Tab — Implementierungsplan (#64)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine eigene, optisch abgetrennte Sektion „Spezial-Events" im Statistiken-Tab, die aggregierte KPI-Kacheln für beide Spezial-Events (FriesenKutter + FriesenFliegerBummel) zeigt, gespeist aus den #66-Snapshots.

**Architecture:** Zwei reine Aggregatfunktionen in `app/database.py` summieren fertige Progress-/View-Dicts. Ein neuer Endpoint `GET /api/stats/special-events` iteriert die abgeschlossenen Events/Rennen im Zeitfenster (über die vorhandenen Snapshot-Helfer `_kutter_progress`/`_bummel_view`) und ruft die Aggregatfunktionen. Das Frontend rendert ein eigenes Panel mit zwei KPI-Zeilen.

**Tech Stack:** Python 3.11, FastAPI, SQLite, Vanilla-JS. Spec: `docs/superpowers/specs/2026-07-07-spezialevents-kpi-statistiken-design.md`.

## Global Constraints

- **Nur abgeschlossene Events:** Kutter `summarized_at` gesetzt & `dtend >= since`; Bummel `revealed_at` gesetzt & `now >= dtend` & `dtend >= since`. NULL-`dtend` wird ausgeschlossen (`(row.get("dtend") or "") ...`) — sonst TypeError → 500.
- **Nur Events mit Aktivität zählen:** Kutter `flight_count > 0`, Bummel `participant_count > 0`.
- **Defensive `.get()`-Zugriffe** auf alle Snapshot-Felder (JSON-Payloads).
- **`days` Whitelist** `{30, 90, 365}`, Default 30.
- **Symmetrie (Memory `feedback_spezialevents_symmetric`):** Kutter und Bummel gleichrangig, nie kutterlastig.
- **KPI-Werte in bestehender `.stats-kpi-*`-Konvention** (blau/`--green`, wie die vorhandenen Flug-KPIs) — keine Kachel klickbar.
- **Stehende Regeln:** TDD, Tests grün vor Commit, Version-Bump + Git-Tag + CHANGELOG (deutsche „geschwungene" Anführungszeichen — ASCII `"` bricht JSON), Docs (api.md/architecture.md) mitpflegen, vor `git push` bestätigen lassen.

---

### Task 1: Aggregatfunktionen in `app/database.py`

**Files:**
- Modify: `app/database.py` (neue reine Funktionen, ans Ende des Transport-/Bummel-Abschnitts)
- Test: `tests/test_database.py`

**Interfaces:**
- Produces:
  - `aggregate_kutter_kpis(progresses: list[dict]) -> dict` → Keys `event_count, participations, flights, delivered_kg, sunk_kg, sunk_count, stolen_kg, stolen_count`
  - `aggregate_bummel_kpis(views: list[dict]) -> dict` → Keys `race_count, participations, legs, avg_absolute_min` (`None` ohne gewertetes Rennen)

- [ ] **Step 1: Failing-Tests schreiben** — in `tests/test_database.py` anhängen:

```python
from app.database import aggregate_kutter_kpis, aggregate_bummel_kpis


def test_aggregate_kutter_kpis_sums_and_splits_losses():
    progresses = [
        {  # aktives, gültiges Event
            "flight_count": 4, "total_kg": 1200.0,
            "participants": [{"cid": 1}, {"cid": 2}],
            "losses": [
                {"loss_kind": "sunk", "lost_kg": 300.0},
                {"loss_kind": "stolen", "lost_kg": 150.0},
                {"loss_kind": "returned", "lost_kg": 0.0},  # kein Verlust, ignoriert
            ],
        },
        {  # leeres Event -> zählt NICHT (flight_count 0)
            "flight_count": 0, "total_kg": 0.0, "participants": [], "losses": [],
        },
    ]
    r = aggregate_kutter_kpis(progresses)
    assert r["event_count"] == 1
    assert r["participations"] == 2
    assert r["flights"] == 4          # inkl. Verlust-Zeilen (Teil von flight_count)
    assert r["delivered_kg"] == 1200.0
    assert r["sunk_kg"] == 300.0 and r["sunk_count"] == 1
    assert r["stolen_kg"] == 150.0 and r["stolen_count"] == 1


def test_aggregate_kutter_kpis_empty_is_zero():
    r = aggregate_kutter_kpis([])
    assert r == {"event_count": 0, "participations": 0, "flights": 0,
                 "delivered_kg": 0.0, "sunk_kg": 0.0, "sunk_count": 0,
                 "stolen_kg": 0.0, "stolen_count": 0}


def test_aggregate_bummel_kpis_sums_legs_and_avg():
    views = [
        {"participant_count": 3, "count": 2, "average_min": 90.0,
         "complete": [{"leg_count": 3}, {"leg_count": 3}],
         "incomplete": [{"leg_count": 1}]},
        {"participant_count": 2, "count": 1, "average_min": 60.0,
         "complete": [{"leg_count": 2}], "incomplete": []},
        {"participant_count": 0, "count": 0, "average_min": 0.0,  # leer -> ignoriert
         "complete": [], "incomplete": []},
    ]
    r = aggregate_bummel_kpis(views)
    assert r["race_count"] == 2
    assert r["participations"] == 5
    assert r["legs"] == 3 + 3 + 1 + 2      # 9
    assert r["avg_absolute_min"] == 75.0   # (90 + 60) / 2


def test_aggregate_bummel_kpis_avg_none_without_scored_race():
    views = [{"participant_count": 2, "count": 0, "average_min": 0.0,
              "complete": [], "incomplete": [{"leg_count": 1}, {"leg_count": 1}]}]
    r = aggregate_bummel_kpis(views)
    assert r["race_count"] == 1
    assert r["participations"] == 2
    assert r["legs"] == 2
    assert r["avg_absolute_min"] is None
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_database.py -k aggregate_ -q`
Expected: FAIL (`ImportError: cannot import name 'aggregate_kutter_kpis'`).

- [ ] **Step 3: Aggregatfunktionen implementieren** — in `app/database.py` anhängen (z. B. nach `event_summary_context`):

```python
def aggregate_kutter_kpis(progresses: list[dict]) -> dict:
    """Aggregiert fertige compute_transport_progress-/Snapshot-Dicts abgeschlossener Kutter-Events
    zu KPI-Summen. Rein (keine DB). Nur Events mit flight_count>0 zählen (leere Test-Events
    verfälschen die Anzahl nicht). `returned`-Verluste sind kg-neutral und werden nicht als
    Verlust gezählt (aber ihre Flug-Zeile steckt in flight_count)."""
    event_count = participations = flights = 0
    delivered_kg = sunk_kg = stolen_kg = 0.0
    sunk_count = stolen_count = 0
    for p in progresses:
        if (p.get("flight_count") or 0) <= 0:
            continue
        event_count += 1
        participations += len(p.get("participants", []))
        flights += p.get("flight_count") or 0
        delivered_kg += p.get("total_kg") or 0.0
        for l in p.get("losses", []):
            kg = l.get("lost_kg") or 0.0
            if l.get("loss_kind") == "sunk":
                sunk_kg += kg
                sunk_count += 1
            elif l.get("loss_kind") == "stolen":
                stolen_kg += kg
                stolen_count += 1
    return {
        "event_count": event_count,
        "participations": participations,
        "flights": flights,
        "delivered_kg": round(delivered_kg, 1),
        "sunk_kg": round(sunk_kg, 1), "sunk_count": sunk_count,
        "stolen_kg": round(stolen_kg, 1), "stolen_count": stolen_count,
    }


def aggregate_bummel_kpis(views: list[dict]) -> dict:
    """Aggregiert fertige _bummel_view-/Snapshot-Dicts abgeschlossener (enthüllter) Rennen zu
    KPI-Summen. Rein (keine DB). Nur Rennen mit participant_count>0 zählen. „Flüge" = gewertete
    Tour-Legs (Σ leg_count über complete+incomplete). „Ø Absoluter Durchschnitt" = Mittel der
    average_min NUR über Rennen mit count>0 (average_min ist bei 0 Touren 0.0, nicht None)."""
    race_count = participations = legs = 0
    avg_values: list[float] = []
    for v in views:
        if (v.get("participant_count") or 0) <= 0:
            continue
        race_count += 1
        participations += v.get("participant_count") or 0
        for e in list(v.get("complete", [])) + list(v.get("incomplete", [])):
            legs += e.get("leg_count", len(e.get("legs", []) or []))
        if (v.get("count") or 0) > 0:
            avg_values.append(v.get("average_min") or 0.0)
    return {
        "race_count": race_count,
        "participations": participations,
        "legs": legs,
        "avg_absolute_min": round(sum(avg_values) / len(avg_values), 1) if avg_values else None,
    }
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `python -m pytest tests/test_database.py -k aggregate_ -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/database.py tests/test_database.py
git commit -m "feat: Aggregatfunktionen Spezial-Events-KPIs (Kutter+Bummel) (#64)"
```

---

### Task 2: Endpoint `GET /api/stats/special-events` in `app/main.py`

**Files:**
- Modify: `app/main.py` (neuer Endpoint neben `/api/stats`, ~Zeile 368; Import von `aggregate_kutter_kpis`/`aggregate_bummel_kpis` sicherstellen)
- Test: `tests/test_special_events_stats.py` (neu)

**Interfaces:**
- Consumes: `aggregate_kutter_kpis`, `aggregate_bummel_kpis` (Task 1); vorhandene `list_transport_events(conn, since=)`, `list_bummel_races(conn, since=)`, `_kutter_progress(conn, ev, now, prefix)`, `_bummel_view(conn, race, now)`, `update_bummel_reveals(conn, now, callsign_prefix=)`, `_now_iso()`.
- Produces: `GET /api/stats/special-events?days=` → `{"kutter": {...8 keys...}, "bummel": {...4 keys...}}`

- [ ] **Step 1: Failing-Test schreiben** — `tests/test_special_events_stats.py`:

```python
"""Wiring-Test für GET /api/stats/special-events — Aggregation über abgeschlossene Spezial-Events."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import app.main as main
from app.database import (
    get_connection, init_db, create_transport_event, set_transport_summarized,
    write_progress_snapshot,
)


def _iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _patch(monkeypatch, db):
    monkeypatch.setattr(main, "get_settings",
                        lambda: SimpleNamespace(DB_PATH=db, CALLSIGN_PREFIX="FRS"))


def test_special_events_only_finished_in_window(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch(monkeypatch, db)
    now = datetime.now(timezone.utc)
    conn = get_connection(db)

    # (a) abgeschlossener Kutter IM Fenster, mit Fracht + Verlusten
    dtend_ok = _iso(now - timedelta(days=2))
    eid = create_transport_event(conn, name="Nachschub", route="EDWG,EDXH",
                                 dtstart=_iso(now - timedelta(days=2, hours=3)),
                                 dtend=dtend_ok, destination="EDXH")
    set_transport_summarized(conn, eid, dtend_ok)
    write_progress_snapshot(conn, "kutter", eid, {
        "flight_count": 3, "total_kg": 900.0,
        "participants": [{"cid": 1}, {"cid": 2}],
        "losses": [{"loss_kind": "sunk", "lost_kg": 200.0}],
        "flights": [], "cargo": [], "route": ["EDWG", "EDXH"], "destination": "EDXH",
        "target_kg": None, "loaded_count": 2,
    }, dtend_ok)

    # (b) abgeschlossener Kutter AUSSERHALB des 30-Tage-Fensters -> zählt nicht
    dtend_old = _iso(now - timedelta(days=200))
    eid2 = create_transport_event(conn, name="Alt", route="EDWG,EDXH",
                                  dtstart=_iso(now - timedelta(days=200, hours=3)),
                                  dtend=dtend_old, destination="EDXH")
    set_transport_summarized(conn, eid2, dtend_old)
    write_progress_snapshot(conn, "kutter", eid2, {
        "flight_count": 9, "total_kg": 5000.0, "participants": [{"cid": 9}],
        "losses": [], "flights": [], "cargo": [], "route": ["EDWG", "EDXH"],
        "destination": "EDXH", "target_kg": None, "loaded_count": 9,
    }, dtend_old)

    # (c) laufender Kutter (kein summarized_at) -> zählt nicht
    create_transport_event(conn, name="Laeuft", route="EDWG,EDXH",
                           dtstart=_iso(now - timedelta(hours=1)),
                           dtend=_iso(now + timedelta(hours=3)), destination="EDXH")
    conn.commit()
    conn.close()

    res = asyncio.run(main.get_special_events_stats(days=30))

    assert res["kutter"]["event_count"] == 1          # nur (a)
    assert res["kutter"]["flights"] == 3
    assert res["kutter"]["participations"] == 2
    assert res["kutter"]["delivered_kg"] == 900.0
    assert res["kutter"]["sunk_kg"] == 200.0 and res["kutter"]["sunk_count"] == 1
    assert res["kutter"]["stolen_count"] == 0
    # Bummel leer -> Nullstruktur
    assert res["bummel"]["race_count"] == 0
    assert res["bummel"]["avg_absolute_min"] is None


def test_special_events_shape(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch(monkeypatch, db)
    res = asyncio.run(main.get_special_events_stats(days=365))
    assert set(res.keys()) == {"kutter", "bummel"}
    assert set(res["kutter"].keys()) == {
        "event_count", "participations", "flights", "delivered_kg",
        "sunk_kg", "sunk_count", "stolen_kg", "stolen_count"}
    assert set(res["bummel"].keys()) == {
        "race_count", "participations", "legs", "avg_absolute_min"}
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `python -m pytest tests/test_special_events_stats.py -q`
Expected: FAIL (`AttributeError: module 'app.main' has no attribute 'get_special_events_stats'`).

- [ ] **Step 3: Endpoint implementieren** — in `app/main.py` nach `get_stats_endpoint` (~Zeile 368). Zuerst sicherstellen, dass `aggregate_kutter_kpis, aggregate_bummel_kpis` aus `app.database` importiert sind (zum bestehenden Sammel-Import hinzufügen). Dann:

```python
@app.get("/api/stats/special-events")
async def get_special_events_stats(days: int = 30):
    """Aggregierte Kennzahlen beider Spezial-Events (FriesenKutter + FriesenFliegerBummel) im
    Zeitfenster — NUR abgeschlossene Events/Rennen, bedient aus den #66-Snapshots (kein
    Track-Recompute). ?days=30|90|365."""
    if days not in (30, 90, 365):
        days = 30
    now = _now_iso()
    since = (datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_timezone.utc)
             - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    settings = get_settings()
    prefix = settings.CALLSIGN_PREFIX
    conn = get_connection(settings.DB_PATH)
    try:
        # --- FriesenKutter: abgeschlossen (summarized_at) & dtend im Fenster ---
        k_progresses = []
        for ev in list_transport_events(conn, since=since):
            if not ev.get("summarized_at") or (ev.get("dtend") or "") < since:
                continue
            p = _kutter_progress(conn, ev, now, prefix)
            if (p.get("flight_count") or 0) > 0:
                k_progresses.append(p)
        kutter = aggregate_kutter_kpis(k_progresses)

        # --- FriesenFliegerBummel: revealed_at & now>=dtend & dtend im Fenster ---
        update_bummel_reveals(conn, now, callsign_prefix=prefix)
        b_views = []
        for race in list_bummel_races(conn, since=since):
            dtend = race.get("dtend") or ""
            if not race.get("revealed_at") or now < dtend or dtend < since:
                continue
            v = _bummel_view(conn, race, now)
            if (v.get("participant_count") or 0) > 0:
                b_views.append(v)
        bummel = aggregate_bummel_kpis(b_views)

        return {"kutter": kutter, "bummel": bummel}
    finally:
        conn.close()
```

- [ ] **Step 4: Test laufen lassen — muss bestehen**

Run: `python -m pytest tests/test_special_events_stats.py -q`
Expected: 2 passed. (Der Test seedet bewusst nur Kutter-Events; der Bummel-Zweig wird über die Null-Struktur geprüft. Ein Bummel-Aggregations-Wiring-Test ist optional — die Aggregatlogik selbst deckt Task 1 ab.)

- [ ] **Step 5: Volle Suite grün**

Run: `python -m pytest tests/ -q`
Expected: alle grün.

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_special_events_stats.py
git commit -m "feat: Endpoint /api/stats/special-events (Kutter+Bummel-KPIs) (#64)"
```

---

### Task 3: Frontend — Panel „Spezial-Events" (`app/static/index.html`)

**Files:**
- Modify: `app/static/index.html` (HTML-Panel im `#tab-statistiken`, JS `fetchSpecialEventStats` + Render, Aufruf-Einhängung)

**Interfaces:**
- Consumes: `GET /api/stats/special-events?days=` (Task 2), bestehende CSS-Klassen `.stats-kpi-row/.stats-kpi-card/.stats-kpi-value/.stats-kpi-label/.stats-kpi-note`, `_statsDays()`, `escHtml`.

- [ ] **Step 1: HTML-Panel ergänzen** — in `app/static/index.html` das `#tab-statistiken` (~Zeile 1637) um ein ZWEITES Panel NACH dem Flugstatistiken-Panel (nach dessen `</div>`, noch innerhalb `#tab-statistiken`) erweitern:

```html
    <div class="panel" id="special-events-panel" style="display:none;">
      <div class="panel-title">Spezial-Events</div>
      <div id="special-events-content"></div>
    </div>
```

- [ ] **Step 2: Render- + Fetch-Funktion ergänzen** — im `<script>`-Bereich (z. B. direkt nach `fetchStats`, ~Zeile 3953):

```javascript
function _kpiCard(value, label, note) {
  const noteHtml = note ? `<span class="stats-kpi-note" style="margin-top:0;">${escHtml(note)}</span>` : '';
  return `<div class="stats-kpi-card">
      <span class="stats-kpi-value">${escHtml(String(value))}</span>
      <span class="stats-kpi-label">${escHtml(label)}</span>
      ${noteHtml}
    </div>`;
}

function _fmtTons(kg) { return (Math.round((kg || 0) / 100) / 10).toFixed(1) + ' t'; }

function _fmtAvgMin(min) {
  if (min == null) return '—';
  const m = Math.round(min);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')} h` : `${m} min`;
}

function renderSpecialEventStats(data) {
  const panel = document.getElementById('special-events-panel');
  const box   = document.getElementById('special-events-content');
  const k = (data && data.kutter) || {};
  const b = (data && data.bummel) || {};
  const rows = [];
  if ((k.event_count || 0) > 0) {
    rows.push(`<div class="stats-kpi-row">
      ${_kpiCard(k.event_count, '🦐 FriesenKutter')}
      ${_kpiCard(k.participations, 'Teilnahmen')}
      ${_kpiCard(k.flights, 'Flüge')}
      ${_kpiCard(_fmtTons(k.delivered_kg), 'Tonnage')}
      ${_kpiCard(_fmtTons(k.sunk_kg), 'Versunken', `${k.sunk_count || 0} Kutter`)}
      ${_kpiCard(_fmtTons(k.stolen_kg), 'Geklaut', `${k.stolen_count || 0} Ladungen`)}
    </div>`);
  }
  if ((b.race_count || 0) > 0) {
    rows.push(`<div class="stats-kpi-row" style="border-bottom:none;margin-bottom:0;">
      ${_kpiCard(b.race_count, '🛩 FriesenBummel')}
      ${_kpiCard(b.participations, 'Teilnahmen')}
      ${_kpiCard(b.legs, 'Flüge')}
      ${_kpiCard(_fmtAvgMin(b.avg_absolute_min), 'Ø Absoluter Durchschnitt')}
    </div>`);
  }
  if (rows.length === 0) { panel.style.display = 'none'; box.innerHTML = ''; return; }
  box.innerHTML = rows.join('');
  panel.style.display = '';
}

async function fetchSpecialEventStats(days) {
  try {
    const res = await fetch(`/api/stats/special-events?days=${days}`);
    if (!res.ok) { document.getElementById('special-events-panel').style.display = 'none'; return; }
    renderSpecialEventStats(await res.json());
  } catch (e) {
    document.getElementById('special-events-panel').style.display = 'none';
  }
}
```

- [ ] **Step 3: Aufruf einhängen** — `fetchSpecialEventStats(days)` überall dort auslösen, wo bereits `fetchAndRenderChart(days)` aufgerufen wird (gleiches Trigger-Muster: Zusatz-Load neben `fetchStats`, beim Tab-Öffnen und beim `days`-Wechsel). In `index.html` nach `fetchAndRenderChart(...)` grep und je Fundstelle eine Zeile `fetchSpecialEventStats(<dieselbe days-Variable>);` ergänzen. Sicherstellen, dass `days` als String/Number zum Endpoint passt (URL-Param, egal).

- [ ] **Step 4: Manuelle Verifikation (lokal)** — App starten (`uvicorn app.main:app --reload`, Port 8091), Statistiken-Tab öffnen:
  - Panel „Spezial-Events" erscheint nur, wenn es abgeschlossene Events im Zeitraum gibt (sonst ausgeblendet).
  - Zeilen-Reihenfolge Kutter: FriesenKutter · Teilnahmen · Flüge · Tonnage · Versunken · Geklaut; Bummel: FriesenBummel · Teilnahmen · Flüge · Ø Absoluter Durchschnitt.
  - Zeitraum-Wechsel (30/90/365) lädt die Kacheln neu.
  - Mobil-Breite (schmales Fenster): Kacheln brechen um, kein horizontaler Scroll, keine gequetschte Tabelle.
  - Keine Kachel wirkt klickbar (kein Cursor-Pointer, kein Hover-Effekt).

- [ ] **Step 5: Commit**

```bash
git add app/static/index.html
git commit -m "feat: Spezial-Events-KPI-Panel im Statistiken-Tab (#64)"
```

---

### Task 4: Docs + Version + CHANGELOG

**Files:**
- Modify: `app/CHANGELOG.json`, `docs/api.md`, `docs/architecture.md`

- [ ] **Step 1: CHANGELOG-Eintrag** — in `app/CHANGELOG.json` als OBERSTEN Eintrag (deutsche „geschwungene" Anführungszeichen!):

```json
{
  "version": "8.11.0",
  "date": "2026-07-07",
  "title": "Neue Spezial-Events-Kennzahlen im Statistiken-Tab",
  "items": [
    "Der Statistiken-Tab zeigt jetzt eine eigene Sektion „Spezial-Events“ mit Kennzahlen für beide Spezial-Events: FriesenKutter (Teilnahmen, Flüge, gelieferte Tonnage, versunkene und geklaute Fracht) und FriesenFliegerBummel (Teilnahmen, Flüge, Ø absoluter Durchschnitt). Die Zahlen richten sich nach dem gewählten Zeitraum und umfassen nur abgeschlossene Events."
  ]
}
```

- [ ] **Step 2: JSON validieren + Version prüfen**

Run: `python -c "import json; d=json.load(open('app/CHANGELOG.json',encoding='utf-8')); print(d[0]['version'])"`
Expected: `8.11.0` (VERSION wird daraus abgeleitet).

- [ ] **Step 3: `docs/api.md`** — neuen Abschnitt ergänzen (bei den Stats-Endpoints):

```markdown
### GET /api/stats/special-events
Aggregierte Kennzahlen beider Spezial-Events im Zeitfenster (`?days=30|90|365`, Default 30, Whitelist —
`days>365` würde die Snapshot-Retention überschreiten). NUR abgeschlossene Events/Rennen, bedient aus den
#66-Snapshots (kein Track-Recompute). Antwort:
`{"kutter": {event_count, participations, flights, delivered_kg, sunk_kg, sunk_count, stolen_kg, stolen_count},
  "bummel": {race_count, participations, legs, avg_absolute_min}}`.
Abgrenzung: Kutter „Flüge" = alle Flug-/Verlust-Zeilen (`flight_count`); Bummel „Flüge" = gewertete Tour-Legs
(`Σ leg_count`). `returned` (zurückgebracht) ist kein Verlust (0 kg). `avg_absolute_min` ist `null` ohne
gewertetes Rennen. NULL-`dtend`-Events werden ausgeschlossen.
```

- [ ] **Step 4: `docs/architecture.md`** — bei den Kutter/Bummel-Funktionen ergänzen: „`aggregate_kutter_kpis`/`aggregate_bummel_kpis` (`app/database.py`, rein) summieren die fertigen Snapshot-/Progress-Dicts; der Endpoint `GET /api/stats/special-events` (`app/main.py`) iteriert nur abgeschlossene Events/Rennen im Zeitfenster über `_kutter_progress`/`_bummel_view` (Snapshot-Reuse, kein `canonicalize_legs`)."

- [ ] **Step 5: Commit**

```bash
git add app/CHANGELOG.json docs/api.md docs/architecture.md
git commit -m "docs: Spezial-Events-KPIs dokumentiert, CHANGELOG v8.11.0 (#64)"
```

---

## Nach allen Tasks

- Finales Whole-Branch-Review (subagent-driven-development: broad review) — Fokus: NULL-`dtend`-Guard greift, keine Doppelzählung, Symmetrie, Blau-Regel-Entscheidung.
- Git-Tag `v8.11.0`, dann **vor `git push origin main` Nutzer-Bestätigung** (stehende Regel).
- Nach Deploy: Statistiken-Tab live prüfen, Task #64 auf completed.
