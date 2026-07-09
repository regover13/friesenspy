# GPS-only Boden-Beladung am Abholplatz (#5) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein am Abholplatz am Boden geparkter FriesenKutter-Pilot erscheint schon vor dem Start als „🅿️ lädt in <Platz>" mit reservierter Fracht — der Startplatz kommt aus der aktuellen GPS-Position, nicht aus dem Flugplan.

**Architecture:** In `compute_transport_progress` (Offen-Flug-Zweig) wird die `dep`-Auflösung um die aktuelle Live-Boden-Position als **oberste** Quelle erweitert (`current_leg` → aktuelle Boden-Position → `_first_pos` → Flugplan-Notnagel). Rein additiv, daher regressionsfrei. Das Frontend benennt den Boden-Status um.

**Tech Stack:** Python 3.11 (SQLite/`live_positions`), Vanilla-JS-Frontend, pytest.

## Global Constraints

- **GPS-only (#23):** Die aktuelle Live-Position bestimmt den Abholplatz. Der Flugplan bleibt nur letzter Notnagel, wenn gar keine Live-Position existiert (im Betrieb nie).
- **Regressionsfrei:** Bestehende Offen-Flug-Tests ohne Live-Position müssen unverändert grün bleiben (Live-Position prioritär, sonst wie bisher).
- **Boden = `groundspeed < _BLOCK_GS_KT`** (`_BLOCK_GS_KT = 2`, `app/database.py:978`).
- **Radius:** `_BUMMEL_AIRPORT_RADIUS_KM` (bereits als `radius` in der Funktion vorhanden, kein per-Event-Override).
- **Ziel-Ausschluss:** Der bestehende Check `if dep not in route_set or dep == dest: continue` bleibt — am Ziel geparkt heißt nie „lädt".
- **Versionierung:** Neues nutzer-sichtbares Feature → Minor-Bump **v8.22.0**, Git-Tag, Banner automatisch.
- **Commit-Co-Author:** `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- `app/database.py` — neuer Helfer `_current_pos`; erweiterte `dep`-Auflösung im Offen-Flug-Zweig von `compute_transport_progress`.
- `app/static/index.html` — Boden-Status-Text „🅿️ lädt in <dep>" (Live-Banner) + „lädt (reserviert)" (Detail-Feed).
- `tests/test_transport.py` — Test-Helfer `_set_live_pos`; 5 neue Unit-Tests.
- `docs/api.md`, `docs/architecture.md` — Notiz „Boden-Beladung GPS-only".
- `app/CHANGELOG.json` — v8.22.0-Eintrag (Version leitet sich daraus ab, `app/version.py:27`).

---

### Task 1: Backend — `_current_pos` + GPS-only dep-Auflösung (mit Tests)

**Files:**
- Modify: `app/database.py` (Helfer nach `_returning_pilot_landed`, ~Zeile 5019; dep-Auflösung ~Zeile 5297–5300)
- Test: `tests/test_transport.py` (Helfer + neue Testklasse)

**Interfaces:**
- Produces: `_current_pos(conn, cid) -> tuple[float, float, float] | None` — `(lat, lon, groundspeed)` der aktuellen Live-Position oder `None`.
- Consumes: vorhandene `_nearest_airport(coords_map, pos, radius_km)`, `_first_pos(conn, cid, logon, now)`, `_BLOCK_GS_KT`, in der Funktion vorhandene `coords_map`/`radius`/`route_set`/`dest`.

- [ ] **Step 1: Test-Helfer `_set_live_pos` ergänzen**

In `tests/test_transport.py` nach `_add_pos` (~Zeile 142) einfügen:

```python
def _set_live_pos(conn, cid, lat, lon, gs, *, callsign=None):
    """Aktuelle Live-Position setzen (live_positions) — Quelle für _current_pos / Boden-Beladung."""
    callsign = callsign or f"FRS{cid:02d}"
    conn.execute(
        "INSERT OR REPLACE INTO live_positions (cid, callsign, latitude, longitude, groundspeed) "
        "VALUES (?, ?, ?, ?, ?)",
        (cid, callsign, lat, lon, gs),
    )
    conn.commit()
```

- [ ] **Step 2: Failing tests schreiben**

In `tests/test_transport.py` ans Ende eine Testklasse anfügen. Route so wählen, dass **EDXH ein Abholplatz** ist und **EDWG das Ziel** (`destination="EDWG"`):

```python
class TestGroundLoading:
    """#5: geparkt am Abholplatz -> sichtbar als ladend, dep aus AKTUELLER Live-Position."""

    def _load_event(self, conn):
        return _event(
            conn, route="EDXH,EDWG", destination="EDWG",
            cargo=[{"name": "Filmrollen", "target_kg": 200, "emoji": "🎞️", "departure": "EDXH"}],
        )

    def test_parked_at_pickup_shows_loading_from_live_pos_not_plan(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._load_event(conn)
        # Flugplan bewusst FALSCH/veraltet (EDXP->EDWK), real steht der Pilot in EDXH:
        _add_open_flight(conn, 61, "EDXP", "EDWK", "C208", START)
        lat, lon = icao_to_coords("EDXH")
        _set_live_pos(conn, 61, lat, lon, 0)  # am Boden in EDXH
        progress = compute_transport_progress(conn, ev, "2026-07-01T09:05:00Z")
        f = _feed_by_callsign(progress, "FRS61")
        assert f is not None
        assert f["dep"] == "EDXH"          # Live-Position gewinnt, nicht der Plan (EDXP)
        assert f["airborne"] is False
        assert f["loaded"] is False
        assert f["reserved_kg"] > 0

    def test_parked_at_destination_not_loading(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._load_event(conn)
        _add_open_flight(conn, 62, "EDXH", "EDWG", "C208", START)
        lat, lon = icao_to_coords("EDWG")  # am ZIEL geparkt
        _set_live_pos(conn, 62, lat, lon, 0)
        progress = compute_transport_progress(conn, ev, "2026-07-01T09:05:00Z")
        assert _feed_by_callsign(progress, "FRS62") is None

    def test_parked_off_route_invisible(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._load_event(conn)
        _add_open_flight(conn, 63, "EDXH", "EDWG", "C208", START)
        lat, lon = icao_to_coords("EDDF")  # weit weg von jedem Streckenplatz
        _set_live_pos(conn, 63, lat, lon, 0)
        progress = compute_transport_progress(conn, ev, "2026-07-01T09:05:00Z")
        assert _feed_by_callsign(progress, "FRS63") is None

    def test_airborne_over_pickup_uses_leg_not_ground(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._load_event(conn)
        _add_open_flight(conn, 64, "EDXH", "EDWG", "C208", START)
        lat, lon = icao_to_coords("EDXH")
        _set_live_pos(conn, 64, lat, lon, 120)  # in der Luft -> Boden-Zweig darf nicht greifen
        progress = compute_transport_progress(conn, ev, "2026-07-01T09:05:00Z")
        f = _feed_by_callsign(progress, "FRS64")
        assert f is not None            # sichtbar (Plan-Notnagel EDXH), aber nicht wegen Boden-Position
        assert f["airborne"] is False   # kein GPS-Leg erkannt -> weiterhin nicht „abgehoben"

    def test_no_live_position_falls_back_to_plan(self):
        conn = _make_conn()
        ev = self._load_event(conn)
        _add_open_flight(conn, 65, "EDXH", "EDWG", "C208", START)  # keine Live-Position
        progress = compute_transport_progress(conn, ev, "2026-07-01T09:05:00Z")
        f = _feed_by_callsign(progress, "FRS65")
        assert f is not None and f["dep"] == "EDXH"   # Notnagel Plan greift, regressionsfrei
```

- [ ] **Step 3: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_transport.py::TestGroundLoading -v`
Expected: FAIL — `test_parked_at_pickup_shows_loading_from_live_pos_not_plan` erwartet `dep == "EDXH"`, bekommt aber `"EDXP"` (Plan gewinnt noch); `_set_live_pos`/`_current_pos` noch nicht wirksam.

- [ ] **Step 4: Helfer `_current_pos` implementieren**

In `app/database.py` direkt nach `_returning_pilot_landed` (endet ~Zeile 5019) einfügen:

```python
def _current_pos(conn: sqlite3.Connection, cid: int) -> tuple[float, float, float] | None:
    """(lat, lon, groundspeed) der AKTUELLEN Live-Position (live_positions), oder None.

    Quelle der GPS-only Boden-Beladung (#5): eine Zeile je aktuell verbundener CID, vom Poller
    jede Runde aktualisiert. Fehlt sie (Pilot gerade offline / erste Runde) oder fehlen die
    Koordinaten, gilt None (Aufrufer fällt dann auf _first_pos/Flugplan zurück)."""
    row = conn.execute(
        "SELECT latitude, longitude, groundspeed FROM live_positions WHERE cid = ?", (cid,)
    ).fetchone()
    if not row or row["latitude"] is None or row["longitude"] is None:
        return None
    return (row["latitude"], row["longitude"], row["groundspeed"])
```

- [ ] **Step 5: dep-Auflösung erweitern**

In `app/database.py` den Block bei ~Zeile 5297–5300 ersetzen. Vorher:

```python
            current_leg = current_leg_by_cid.get(int(cid))
            dep = (normalize_type_code(current_leg.get("departure")) if current_leg else None) \
                or _nearest_airport(coords_map, _first_pos(conn, int(cid), lo, now), radius) \
                or normalize_type_code(f.get("departure"))
```

Nachher:

```python
            current_leg = current_leg_by_cid.get(int(cid))
            # GPS-only Boden-Beladung (#5): steht der Pilot am Boden, bestimmt die AKTUELLE
            # Live-Position den Abholplatz — NICHT der (evtl. veraltete) Flugplan und nicht die
            # erste Position der Verbindung. Reihenfolge: abgehobenes GPS-Leg → aktuelle
            # Boden-Position → _first_pos (GPS) → Flugplan (Notnagel, im Betrieb nie nötig).
            gpos = None if current_leg else _current_pos(conn, int(cid))
            dep = (normalize_type_code(current_leg.get("departure")) if current_leg else None) \
                or (_nearest_airport(coords_map, (gpos[0], gpos[1]), radius)
                    if gpos and gpos[2] is not None and gpos[2] < _BLOCK_GS_KT else None) \
                or _nearest_airport(coords_map, _first_pos(conn, int(cid), lo, now), radius) \
                or normalize_type_code(f.get("departure"))
```

- [ ] **Step 6: Tests laufen lassen — müssen bestehen**

Run: `python -m pytest tests/test_transport.py::TestGroundLoading -v`
Expected: PASS (5 Tests).

- [ ] **Step 7: Volle Suite — keine Regression**

Run: `python -m pytest tests/ -q`
Expected: alle grün (bisher 929 + 5 neue).

- [ ] **Step 8: Commit**

```bash
git add app/database.py tests/test_transport.py
git commit -m "feat: GPS-only Boden-Beladung — dep aus aktueller Live-Position (#5)"
```

---

### Task 2: Frontend — Boden-Status „🅿️ lädt in <Platz>"

**Files:**
- Modify: `app/static/index.html:3103` (Live-Banner-Status) und `app/static/index.html:4651` (Detail-Feed-Text)

**Interfaces:**
- Consumes: `f.dep` (Ladeplatz, bereits im Flug-Objekt und im Live-Banner-`active`-Push als `a.dep` vorhanden), `f.loaded`, `f.airborne`.

- [ ] **Step 1: Live-Banner-Status ändern**

In `app/static/index.html` (~Zeile 3103), im `active.push({...})`-Block, Status-Zeile ersetzen. Vorher:

```javascript
        status: f.loaded ? '✅ angekommen' : (f.airborne ? '✈️ unterwegs' : '🅿️ am Start'),
```

Nachher:

```javascript
        status: f.loaded ? '✅ angekommen'
              : (f.airborne ? '✈️ unterwegs'
                 : '🅿️ lädt' + (f.dep ? ' in ' + _kesc(f.dep) : '')),
```

- [ ] **Step 2: Detail-Feed-Text ändern**

In `app/static/index.html` (~Zeile 4651) den reservierten Boden-Text angleichen. Vorher:

```javascript
                  : '<td class="kf-empty">am Start (reserviert)</td>')
```

Nachher:

```javascript
                  : '<td class="kf-empty">lädt (reserviert)</td>')
```

- [ ] **Step 3: JS-Syntax prüfen**

Run:
```bash
node -e "const fs=require('fs');let h=fs.readFileSync('app/static/index.html','utf8');let m=[...h.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(x=>x[1]).join('\n;\n');new Function(m);console.log('JS OK')"
```
Expected: `JS OK`

- [ ] **Step 4: Commit**

```bash
git add app/static/index.html
git commit -m "feat: Kutter-Boden-Status 'lädt in <Platz>' statt 'am Start' (#5)"
```

---

### Task 3: Docs + CHANGELOG + Version

**Files:**
- Modify: `docs/api.md`, `docs/architecture.md`, `app/CHANGELOG.json`

- [ ] **Step 1: CHANGELOG-Eintrag v8.22.0 (oben) einfügen**

In `app/CHANGELOG.json` als erstes Array-Element (typografische Anführungszeichen „…", nie ASCII `"`):

```json
  {
    "version": "8.22.0",
    "date": "2026-07-09",
    "title": "FriesenKutter: Beladung schon am Boden am Abholplatz sichtbar",
    "items": [
      "🅿️ Ein Kutter-Pilot, der am Abholplatz am Boden steht, erscheint jetzt schon vor dem Start als „🅿️ lädt in <Platz>“ mit seiner reservierten Fracht — nicht erst nach dem Abheben. Der Abholplatz kommt aus der aktuellen GPS-Position; ein veralteter oder fremder Flugplan spielt keine Rolle mehr (GPS-only)."
    ]
  },
```

- [ ] **Step 2: JSON prüfen**

Run: `python -c "import json; d=json.load(open('app/CHANGELOG.json',encoding='utf-8')); print('OK', d[0]['version'])"`
Expected: `OK 8.22.0`

- [ ] **Step 3: docs/architecture.md ergänzen**

Im FriesenKutter-Abschnitt einen Satz ergänzen:

```markdown
- **Boden-Beladung (GPS-only, #5):** Ein verbundener FRS-Pilot am Boden (`groundspeed < _BLOCK_GS_KT`)
  im Abhol-Radius eines Streckenplatzes (≠ Ziel) wird als „lädt" mit reservierter Fracht gezeigt.
  Der Abholplatz (`dep`) kommt aus der aktuellen `live_positions`-Position (`_current_pos`); der
  Flugplan ist nur noch Notnagel ohne Live-Position.
```

- [ ] **Step 4: docs/api.md ergänzen**

Beim `GET /api/transport/event/{id}`-Flug-Objekt notieren, dass ein geparkter Pilot mit `airborne=false`, `loaded=false`, `reserved_kg>0` und `dep`=aktueller Abholplatz erscheint (Boden-Beladung).

- [ ] **Step 5: Commit**

```bash
git add docs/api.md docs/architecture.md app/CHANGELOG.json
git commit -m "docs: v8.22.0 — GPS-only Boden-Beladung dokumentiert (#5)"
```

---

## Nach Abschluss (außerhalb der Tasks)

- Voll-Suite grün → `git push origin main` (vorher kurz bestätigen lassen) + Tag `v8.22.0`.
- Manuelle Live-Prüfung beim nächsten Kutter-Test: am Abholplatz parken → „🅿️ lädt in <Platz>" muss vor dem Start erscheinen.

## Self-Review

- **Spec-Abdeckung:** `_current_pos` (Spec §1) → T1/S4. GPS-only dep, Plan-Notnagel (§2, Nutzer-Entscheid) → T1/S5. Status-Text (§3) → T2. Edge Cases (Ziel/off-route/Luft/keine Position) → T1 Tests 2–5. Docs/Version → T3. ✓
- **Platzhalter:** keine — jeder Code-Schritt zeigt vollständigen Code. ✓
- **Typkonsistenz:** `_current_pos` liefert `(lat, lon, gs)`; Aufruf nutzt `gpos[0]/gpos[1]/gpos[2]` mit `gpos[2] is not None`-Guard (gs kann NULL sein). `f.dep` im Frontend existiert bereits (aus #12). ✓
