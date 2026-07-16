# FriesenKutter Stapel-Modell — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Kutter-Fracht wird zu einem Bestand mit einem Ort („Stapel"), der beim Landen geladen und geliefert und beim Ausloggen zurückgegeben, gestohlen oder versenkt wird — statt aus dem Startplatz des letzten Flugbeins geraten zu werden.

**Architecture:** Eine neue, DB-freie Zustandsmaschine (`app/transport_stacks.py`, Vorbild: `app/gps_legs.py`) arbeitet eine chronologische Ereignisliste ab und liefert Stapel + Bordladung. `compute_transport_progress` wird zu ihrem Adapter: Es holt Manifest, Legs, Sessions und Zuladungen aus der DB, ruft die Ableitung und formt deren Ergebnis in den bestehenden API-Vertrag. Der Ankunfts-Latch (`transport_live_arrivals`) und die Reservierung als eigener Mechanismus entfallen ersatzlos.

**Tech Stack:** Python 3.11, SQLite (WAL), FastAPI, pytest. Keine neuen Abhängigkeiten, **keine neuen Tabellen**.

## Global Constraints

- **Spec ist verbindlich:** `docs/superpowers/specs/2026-07-15-kutter-stapel-modell-design.md` — 14 Entscheidungen, alle vom Nutzer bestätigt. Bei Widerspruch zwischen Plan und Spec gewinnt die Spec; melde den Widerspruch, statt ihn still aufzulösen.
- **Erhaltungssatz:** `Σ Stapel + Σ Ladung == Σ Manifest`, immer. Float-Toleranz `1e-6` relativ (Zuladungen sind auf 0,1 kg gerundet — exakte Gleichheit ist nicht testbar).
- **Niemals in die Produktions-DB schreiben.** Messungen laufen gegen eine Kopie oder In-Memory. Die Prod-DB liegt auf dem VPS unter `/opt/friesenspy/data/friesenspy.db`.
- **GPS-only (#23):** Der Flugplan ist keine Wahrheit. `gps_departure`/`gps_arrival` sind maßgeblich; `departure`/`arrival` aus dem Plan dürfen **nie** eine Lieferung begründen.
- **Feld-Vertrag `canonicalize_legs`:** Die Landezeit heißt **`logoff_time`**, nicht `landing_ts`. Weitere Felder: `gps_departure`, `gps_arrival`, `logon_time`, `last_pos_ts`, `connection_closed`, `statsim_id`, `block_min`, `duration_min`, `cid`, `callsign`, `aircraft`, `aircraft_icao`, `distance_nm`.
- **Versionierung (stehende Regel):** Bei Release Version in `app/CHANGELOG.json` oben erhöhen + Git-Tag `vX.Y.Z`. Dieser Umbau ist ein **Major** (`highlight: true`).
- **Docs mitpflegen (stehende Regel):** `README.md`, `docs/api.md`, `docs/architecture.md` bei jeder Codeänderung nachziehen.
- **UI-Standard:** Blau (`--green`, `#2d9cdb`) ist ausschließlich Klickbarem vorbehalten. Breite Tabellen gehören in `.table-scroll`/`.table-wrap`.
- **Deployt wird einmal.** Der Latch kann nicht halb weg sein — `compute_transport_progress` und `detect_transport_losses` hängen beide an ihm. Die Etappen unten sind Prüfpunkte, keine Releases.
- **Sprache:** Code-Kommentare, Doku und Changelog auf Deutsch, mit korrekten Umlauten.

---

## Vorarbeit, die schon existiert

| Datei | Was sie liefert |
|---|---|
| `scripts/kutter_stapel_prototyp.py` | Der Prototyp der Ableitung (`rechne()`, 65 Zeilen) — rechnet die vier abgeschlossenen Events nach. **Vorlage für Task 1–5.** |
| `scripts/kutter_ladung_szenarien.py` | S1–S5, S3b, S2b, S8 mit echten GPS-Tracks gegen den Produktionscode. **Die Helfer `leg()`, `pos()`, `flight_row()`, `coords()` sind die Vorlage für die Test-Fixtures.** |

**Regressionswerte der Migration (gemessen, Prototyp gegen eingefrorene Snapshots):**

| Event | Snapshot (altes Modell) | Stapel-Modell | |
|---|---:|---:|---|
| #1 FriesenKutter-Test Wangerooge | 1610 kg | **1610 kg** | identisch, Position für Position |
| #81 Strandkörbe und Sonnenschirme | 1120 kg | **1120 kg** | identisch |
| #136 Großauftrag für Wooge | 1090 kg | **1090 kg** | identisch, alle fünf Frachtarten |
| #123 Multi-Kutter-Test | 618 kg | 417 kg | Testlauf, darf abweichen (die einzige CSV-Zeile im Bestand) |

---

## File Structure

| Datei | Verantwortung |
|---|---|
| **Neu:** `app/transport_stacks.py` | Die Zustandsmaschine. Ereignisliste → Stapel + Ladung. **Keine DB, kein sqlite3-Import** — Vorbild `app/gps_legs.py`. Testbar mit Listen von Dicts. |
| **Neu:** `tests/test_transport_stacks.py` | Tests der reinen Funktion. Kein DB-Setup, keine Tracks — nur Ereignisse. |
| `app/database.py` | `compute_transport_progress` wird Adapter (Eingänge holen, Ergebnis in den API-Vertrag formen). Latch-Bausteine raus. `set_transport_cargo` bekommt die Plausibilitätsprüfung. |
| `app/poller.py` | `check_live_arrival`-Aufruf (Z. 870) + Import (Z. 45) raus. |
| `app/main.py` | Nur der Feld-Vertrag, wo das Progress-Dict umgeformt wird. |
| `app/static/index.html` | Status-Texte, Sichtbarkeitsregel, Mengen am Boden. |
| `tests/test_transport.py` | Umbau: Latch-Fixtures → echte GPS-Tracks. |

**Warum eine neue Datei:** `database.py` hat 6422 Zeilen, `compute_transport_progress` allein 642. Die Ableitung als reine Funktion herauszuziehen ist der eigentliche Hebel dieses Umbaus — sie ist ohne DB-Setup testbar, und die Regeln stehen an einer Stelle statt verteilt über Latch, Reservierung und Verlust-Klassifikation.

**Testinfrastruktur (wichtig — es gibt keine Fixtures):** Das Projekt hat **keine `conftest.py`** und
nutzt **kein `@pytest.fixture`**. Jede Testklasse baut ihre DB über freie Funktionen in
`tests/test_transport.py` auf: `_make_conn()` (Z. 61), `_add_flight()` (74), `_add_open_flight()` (90),
`_add_delivered_flight()` (104), `_event()` (119), `_feed_by_callsign()` (127), `_add_pos()` (131),
`_set_live_pos()` (144), `_shift()` (155). Neue Tests folgen diesem Muster — **keine Fixtures einführen.**

---

## Die Ableitung im Überblick

Die Zustandsmaschine arbeitet **eine chronologische Ereignisliste** ab. Vier Ereignisse, ein Zustand:

```
Zustand:  stacks[ort][frachtart] = kg      # Orte: Ladeplätze, Ziel, gestohlen, versenkt
          onboard[cid][frachtart] = kg     # der Stapel, den der Flieger trägt
          position[cid] = "EDWG" | None    # None = unterwegs
          since[cid] = ts                  # seit wann er dort steht (Ankunftsreihenfolge)

Ereignis            Wirkung
login (Ort|None)    position = Ort (nur wenn am Boden, sonst None); onboard = {}
takeoff             position = None
landing (Ort)       position = Ort; ist Ort == Ziel -> onboard komplett in den Ziel-Stapel
logout              onboard -> Ladeplatz-Stapel / gestohlen / versenkt, je nach position
```

**Nach jedem Ereignis** laden alle, die an einem Ladeplatz stehen, in Ankunftsreihenfolge auf
(`_load_standing`). Das ist „Laden ist ein Zustand" (Entscheidung 4) und trägt zugleich
Entscheidung 13 („der Wartende lädt nach") — ohne eigene Regel.

**Der Logout-Ort braucht keine Sonderregel.** `position[cid]` ist zum Logout-Zeitpunkt bereits
korrekt, weil `takeoff` sie auf `None` gesetzt hat: Ein Logout zwischen Takeoff und Landung findet
`None` vor → versenkt. Genau das ist der belegte Fall **S8** (Nutzer-Fund 15.07., `flights.id`
357/358, CID 1602713), bei dem der Detektor **ein** durchgehendes Leg `EDXH → EDXH` mit sauberer
Landung sieht — eine Regel „letzter Leg → `gps_arrival`" ergäbe dort fälschlich *zurück*.

---

### Task 1: Das Gerüst — Manifest als Anfangsbestand, Erhaltungssatz

**Files:**
- Create: `app/transport_stacks.py`
- Test: `tests/test_transport_stacks.py`

**Interfaces:**
- Produces: `derive_stacks(*, manifest, events, destination, loading_airports) -> dict` mit den
  Schlüsseln `stacks: dict[str, dict[str, float]]`, `onboard: dict[int, dict[str, float]]`,
  `position: dict[int, str | None]`, `last_ground: dict[int, str | None]`, `movements: list[dict]`.
  Virtuelle Orte: `STOLEN = "\x00gestohlen"`, `SUNK = "\x00versenkt"` (das `\x00`-Präfix kann mit
  keinem ICAO kollidieren).
- `manifest`: `[{"name": str, "target_kg": float, "departure": str, "per_flight_max_kg": float|None}]`
  in **Ladereihenfolge** (Entscheidung 7: Manifest-Reihenfolge im Admin, oben zuerst).
- `events`: `[{"ts": str, "kind": "login"|"takeoff"|"landing"|"logout", "cid": int,
  "airport": str|None, "capacity_kg": float}]`, chronologisch.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transport_stacks.py
"""Tests der Stapel-Ableitung — reine Funktion, keine DB, keine GPS-Tracks.

Die Fälle folgen den Szenarien aus scripts/kutter_ladung_szenarien.py (S1-S8), hier aber ohne
Track-Erzeugung: geprüft wird nur, was die Zustandsmaschine aus Ereignissen macht.
"""
import pytest

from app.transport_stacks import derive_stacks, STOLEN, SUNK

# Manifest wie in den Szenarien: zwei Ladeplätze, verschiedene Fracht, Ziel EDXH.
MANIFEST = [
    {"name": "Fischbrötchen", "target_kg": 800.0, "departure": "EDWG", "per_flight_max_kg": None},
    {"name": "Friesen Tee", "target_kg": 500.0, "departure": "EDWZ", "per_flight_max_kg": None},
]
DEST = "EDXH"
LOADING = {"EDWG", "EDWZ"}
T0 = "2026-07-01T09:00:00Z"


def _ev(kind, cid, ts, airport=None, capacity_kg=1000.0):
    return {"ts": ts, "kind": kind, "cid": cid, "airport": airport, "capacity_kg": capacity_kg}


def _sum_stacks(stacks):
    return sum(sum(inner.values()) for inner in stacks.values())


def _sum_onboard(onboard):
    return sum(sum(inner.values()) for inner in onboard.values())


def _assert_erhaltung(r, total=1300.0):
    """Der Erhaltungssatz: Summe Stapel + Summe Ladung == Summe Manifest. Immer."""
    assert _sum_stacks(r["stacks"]) + _sum_onboard(r["onboard"]) == pytest.approx(total)


def test_ohne_ereignisse_liegt_das_manifest_auf_seinen_stapeln():
    r = derive_stacks(manifest=MANIFEST, events=[], destination=DEST, loading_airports=LOADING)

    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 800.0
    assert r["stacks"]["EDWZ"]["Friesen Tee"] == 500.0
    assert _sum_onboard(r["onboard"]) == 0.0
    _assert_erhaltung(r)


def test_ein_leerer_stapel_ist_immer_noch_ein_stapel():
    """Entscheidung 3: Ein Ladeplatz ohne Ware bleibt ein Ort, kein fehlender Schlüssel."""
    manifest = [{"name": "Nichts", "target_kg": 0.0, "departure": "EDWG", "per_flight_max_kg": None}]
    r = derive_stacks(manifest=manifest, events=[], destination=DEST, loading_airports={"EDWG", "EDWZ"})

    assert "EDWZ" in r["stacks"]          # Ladeplatz ohne eigene Manifest-Zeile
    assert r["stacks"]["EDWG"]["Nichts"] == 0.0


def test_ziel_gestohlen_versenkt_sind_auch_stapel():
    r = derive_stacks(manifest=MANIFEST, events=[], destination=DEST, loading_airports=LOADING)

    assert DEST in r["stacks"] and STOLEN in r["stacks"] and SUNK in r["stacks"]
    assert _sum_stacks({k: v for k, v in r["stacks"].items() if k in (DEST, STOLEN, SUNK)}) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport_stacks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.transport_stacks'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/transport_stacks.py
"""Stapel-Modell des FriesenKutter — Ladung als Bestand mit einem Ort.

Reine Zustandsmaschine, KEINE Datenbank (Vorbild: app/gps_legs.py). Die Funktion bekommt das
Manifest und eine chronologische Ereignisliste und liefert, wo welche Ware liegt.

Grundsatz (Spec docs/superpowers/specs/2026-07-15-kutter-stapel-modell-design.md):
    Ware liegt auf Stapeln (Orte). Der Flieger trägt selbst einen Stapel, der eine Position hat.
    Ware wechselt nur zwischen Stapeln — sie entsteht nie und verschwindet nie:

        Summe Stapel + Summe Ladung == Summe Manifest      (Erhaltungssatz)

Dieser Satz ist die Kernzusage des Modells und als Test zu prüfen. Er macht #63 („der Balken
lügt nicht") von einer Zusicherung zu Arithmetik.
"""
from __future__ import annotations

# Virtuelle Orte. Das \x00-Präfix kann mit keinem ICAO kollidieren.
STOLEN = "\x00gestohlen"
SUNK = "\x00versenkt"

# kg-Schwelle. Zuladungen sind auf 0,1 kg gerundet — darunter ist nichts mehr zu verteilen.
_EPS = 0.01


def derive_stacks(
    *,
    manifest: list[dict],
    events: list[dict],
    destination: str,
    loading_airports: set[str],
) -> dict:
    """Wo liegt welche Ware, nachdem alle Ereignisse abgearbeitet sind?

    :param manifest: Frachtarten in LADEREIHENFOLGE (oben zuerst, Entscheidung 7). Je Zeile
        ``{"name", "target_kg", "departure", "per_flight_max_kg"}``; ``departure`` ist genau
        EIN Platz (Entscheidung 6).
    :param events: chronologisch, ``{"ts", "kind", "cid", "airport", "capacity_kg"}``.
    :param destination: Ziel-ICAO. Der Ziel-Stapel ist ein End-Stapel.
    :param loading_airports: die Ladeplätze (Route ohne Ziel).
    """
    order = [c["name"] for c in manifest]

    def _empty() -> dict[str, float]:
        return {n: 0.0 for n in order}

    # Anfangsbestand: jede Manifest-Zeile liegt an ihrem Platz. Ein leerer Stapel ist immer noch
    # ein Stapel (Entscheidung 3) — deshalb wird JEDER Ladeplatz angelegt, auch ohne Ware.
    stacks: dict[str, dict[str, float]] = {a: _empty() for a in loading_airports}
    for virtual in (destination, STOLEN, SUNK):
        stacks[virtual] = _empty()
    for c in manifest:
        dep = (c.get("departure") or "").upper()
        if dep:
            stacks.setdefault(dep, _empty())
            stacks[dep][c["name"]] += float(c.get("target_kg") or 0.0)

    return {
        "stacks": stacks,
        "onboard": {},
        "position": {},
        "last_ground": {},
        "movements": [],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_transport_stacks.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/transport_stacks.py tests/test_transport_stacks.py
git commit -m "feat(kutter): Stapel-Geruest — Manifest als Anfangsbestand + Erhaltungssatz"
```

---

### Task 2: Laden ist ein Zustand — wer am Ladeplatz steht, lädt

**Files:**
- Modify: `app/transport_stacks.py`
- Test: `tests/test_transport_stacks.py`

**Interfaces:**
- Consumes: `derive_stacks` (Task 1).
- Produces: die Ereignisse `login`/`takeoff`; die internen Helfer `_load_standing(state, ts)` und
  `_take(state, cid, airport, ts)`. `movements` trägt Einträge
  `{"ts", "cid", "kind": "load", "airport", "name", "kg"}`.

**Regeln (Spec):** Am Boden an einem Ladeplatz wird geladen — egal, wie er dorthin kam (Entscheidung
4). **Der Abflug lädt nie**, er wechselt nur die Position auf *unterwegs*. Wer zuerst kommt, lädt
zuerst; der Zweite hat Pech (Entscheidung 5).

- [ ] **Step 1: Write the failing test**

```python
def test_login_am_ladeplatz_laedt_sofort():
    """Entscheidung 4: Am Boden wird geladen — auch ohne je gelandet zu sein.

    Kein neues Verhalten: schon heute reserviert ein am Ladeplatz geparkter Pilot seine volle
    Zuladung (tests/test_transport.py::test_open_flight_on_ground_is_not_airborne, reserved_kg
    == 292.0). Neu ist nur, dass aus der flüchtigen Reservierung eine echte Ladung wird.
    """
    r = derive_stacks(manifest=MANIFEST, events=[_ev("login", 1, T0, "EDWG")],
                      destination=DEST, loading_airports=LOADING)

    assert r["onboard"][1]["Fischbrötchen"] == 800.0
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 0.0
    _assert_erhaltung(r)


def test_abflug_laedt_nie_nur_die_position_wechselt():
    """Spec: 'Der Abflug lädt nie' — 'beim Abheben laden' ist NICHT bilanzgleich."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[_ev("login", 1, T0, "EDWG"), _ev("takeoff", 1, "2026-07-01T09:05:00Z")],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["position"][1] is None                      # unterwegs
    assert r["onboard"][1]["Fischbrötchen"] == 800.0    # beim Login geladen, nicht beim Abflug
    _assert_erhaltung(r)


def test_wer_am_fremden_platz_einloggt_laedt_nichts():
    r = derive_stacks(manifest=MANIFEST, events=[_ev("login", 1, T0, "EDDW")],
                      destination=DEST, loading_airports=LOADING)

    assert _sum_onboard(r["onboard"]) == 0.0
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 800.0


def test_wer_in_der_luft_einloggt_laedt_nichts():
    r = derive_stacks(manifest=MANIFEST, events=[_ev("login", 1, T0, None)],
                      destination=DEST, loading_airports=LOADING)

    assert r["position"][1] is None
    assert _sum_onboard(r["onboard"]) == 0.0


def test_wer_zuerst_kommt_laedt_zuerst_der_zweite_hat_pech():
    """Entscheidung 5: Kein Teilen, keine Quote."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[_ev("login", 1, T0, "EDWG"), _ev("login", 2, "2026-07-01T09:01:00Z", "EDWG")],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["onboard"][1]["Fischbrötchen"] == 800.0
    assert r["onboard"][2]["Fischbrötchen"] == 0.0
    _assert_erhaltung(r)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport_stacks.py -v`
Expected: FAIL — `KeyError: 1` in `test_login_am_ladeplatz_laedt_sofort` (`onboard` bleibt leer,
Ereignisse werden noch nicht verarbeitet)

- [ ] **Step 3: Write minimal implementation**

Ersetze in `derive_stacks` den `return`-Block aus Task 1 durch die Ereignis-Schleife:

```python
    onboard: dict[int, dict[str, float]] = {}
    position: dict[int, str | None] = {}
    last_ground: dict[int, str | None] = {}   # letzter Bodenkontakt (Sichtbarkeit, Entscheidung 14)
    since: dict[int, str] = {}                # seit wann steht er dort (Ankunftsreihenfolge)
    capacity: dict[int, float] = {}
    movements: list[dict] = []

    state = {
        "manifest": manifest, "order": order, "stacks": stacks, "onboard": onboard,
        "position": position, "since": since, "capacity": capacity, "empty": _empty,
        "loading_airports": loading_airports, "destination": destination, "movements": movements,
    }

    for e in events:
        cid = int(e["cid"])
        kind = e["kind"]
        ts = e["ts"]
        if e.get("capacity_kg") is not None:
            capacity[cid] = float(e["capacity_kg"])

        if kind == "login":
            # Ein frisch eingeloggter Pilot trägt nichts: die Ladung ist eine Ableitung, kein
            # Speicher — beim letzten Logout hat sie einen End-Stapel gefunden.
            onboard[cid] = _empty()
            position[cid] = e.get("airport")     # None = in der Luft eingeloggt
            since[cid] = ts
            if e.get("airport"):
                last_ground[cid] = e["airport"]
        elif kind == "takeoff":
            position[cid] = None                 # unterwegs. Lädt NICHT.
        elif kind == "landing":
            position[cid] = e.get("airport")
            since[cid] = ts
            if e.get("airport"):
                last_ground[cid] = e["airport"]
        elif kind == "logout":
            position.pop(cid, None)
            since.pop(cid, None)
            onboard.pop(cid, None)

        _load_standing(state, ts)

    return {
        "stacks": stacks,
        "onboard": onboard,
        "position": position,
        "last_ground": last_ground,
        "movements": movements,
    }


def _load_standing(state: dict, ts: str) -> None:
    """Alle, die gerade an einem Ladeplatz stehen, laden auf — in Ankunftsreihenfolge.

    Wird nach JEDEM Ereignis aufgerufen. Das trägt zwei Entscheidungen ohne eigene Regel:
    'Laden ist ein Zustand' (4) und 'der Wartende lädt nach' (13) — kommt Ware auf einen Stapel,
    an dem jemand steht, nimmt er sie beim nächsten Durchlauf mit.
    """
    standing = [c for c, p in state["position"].items() if p in state["loading_airports"]]
    for cid in sorted(standing, key=lambda c: (state["since"].get(c, ""), c)):
        _take(state, cid, state["position"][cid], ts)


def _take(state: dict, cid: int, airport: str, ts: str) -> None:
    """Vom Stapel dieses Platzes nehmen, soweit Platz im Flieger ist — Manifest-Reihenfolge."""
    stack = state["stacks"].get(airport)
    if not stack:
        return
    load = state["onboard"].setdefault(cid, state["empty"]())
    free = state["capacity"].get(cid, 0.0) - sum(load.values())
    for c in state["manifest"]:
        if free <= _EPS:
            break
        name = c["name"]
        available = stack.get(name, 0.0)
        if available <= _EPS:
            continue
        take = min(available, free)
        if take <= _EPS:
            continue
        stack[name] -= take
        load[name] = load.get(name, 0.0) + take
        free -= take
        state["movements"].append(
            {"ts": ts, "cid": cid, "kind": "load", "airport": airport, "name": name, "kg": take}
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_transport_stacks.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add app/transport_stacks.py tests/test_transport_stacks.py
git commit -m "feat(kutter): Laden ist ein Zustand — wer am Ladeplatz steht, laedt"
```

---

### Task 3: Landung — am Ziel wird geliefert, sonst bleibt die Ladung an Bord

**Files:**
- Modify: `app/transport_stacks.py`
- Test: `tests/test_transport_stacks.py`

**Interfaces:**
- Consumes: `derive_stacks`, `_load_standing` (Task 2).
- Produces: das Ereignis `landing` liefert am Ziel; `movements` bekommt
  `{"kind": "deliver", "airport": <Ziel>, ...}`.

**Regeln (Spec):** Landung am Ziel → gesamter Flieger-Stapel in den Ziel-Stapel, **sofort** (kein
Disconnect nötig). Landung am fremden Platz → nichts, Ladung bleibt an Bord. **Dies ist der Kern
des Milchmann-Falls (S2):** Wer an einem zweiten Ladeplatz landet, behält seine erste Ladung und
füllt auf.

- [ ] **Step 1: Write the failing test**

```python
def test_s1_normalfall_landung_am_ziel_liefert():
    """S1: EDWG -> EDXH. Heute wie neu 800 kg."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDXH"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][DEST]["Fischbrötchen"] == 800.0
    assert _sum_onboard(r["onboard"]) == 0.0
    _assert_erhaltung(r)


def test_s2_milchmann_erste_ladung_bleibt_an_bord():
    """S2: EDWG -> EDWZ -> EDXH. HEUTE: 0 Fisch + 500 Tee (die erste Ladung verschwindet).
    Stapel-Modell: 800 Fisch + 200 Tee = 1000 (die Zuladung ist die Grenze)."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),                               # lädt 800 Fisch
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDWZ"),         # Ladeplatz: füllt auf
            _ev("takeoff", 1, "2026-07-01T09:40:00Z"),
            _ev("landing", 1, "2026-07-01T10:10:00Z", "EDXH"),         # liefert alles
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][DEST]["Fischbrötchen"] == 800.0
    assert r["stacks"][DEST]["Friesen Tee"] == 200.0     # nur 200 passten noch in die 1000 kg
    assert r["stacks"]["EDWZ"]["Friesen Tee"] == 300.0   # der Rest liegt weiter in EDWZ
    _assert_erhaltung(r)


def test_s3_zwischenlandung_am_fremden_platz_aendert_nichts():
    """S3: EDWG -> EDDW(fremd) -> EDXH. HEUTE ohne Latch 0 kg, mit Latch 1000 kg (Tee, der nie
    an Bord war). Stapel-Modell: 800 Fisch — EDDW hat keinen Stapel."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDDW"),   # fremd: nichts passiert
            _ev("takeoff", 1, "2026-07-01T09:40:00Z"),
            _ev("landing", 1, "2026-07-01T10:10:00Z", "EDXH"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][DEST]["Fischbrötchen"] == 800.0
    assert r["stacks"][DEST]["Friesen Tee"] == 0.0       # Tee war nie an Bord
    assert r["stacks"]["EDWZ"]["Friesen Tee"] == 500.0
    _assert_erhaltung(r)


def test_landung_am_ziel_liefert_sofort_ohne_disconnect():
    """Der Latch beantwortete 'hat er geliefert?' — das Modell weiß es beim Touchdown."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDXH"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][DEST]["Fischbrötchen"] == 800.0   # kein logout nötig
    assert r["position"][1] == "EDXH"                     # steht am Ziel, bleibt sichtbar
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport_stacks.py -v`
Expected: FAIL — `assert 0.0 == 800.0` (die Landung liefert noch nicht; `stacks["EDXH"]` bleibt leer)

- [ ] **Step 3: Write minimal implementation**

Erweitere den `landing`-Zweig in `derive_stacks`:

```python
        elif kind == "landing":
            airport = e.get("airport")
            position[cid] = airport
            since[cid] = ts
            if airport:
                last_ground[cid] = airport
            if airport == destination:
                # Landung am Ziel: der GESAMTE Flieger-Stapel geht in den Ziel-Stapel, sofort.
                # Kein Disconnect nötig — genau die Frage, die früher der Latch beantwortete.
                load = onboard.get(cid) or {}
                for name, kg in list(load.items()):
                    if kg <= _EPS:
                        continue
                    stacks[destination][name] += kg
                    movements.append({"ts": ts, "cid": cid, "kind": "deliver",
                                      "airport": destination, "name": name, "kg": kg})
                onboard[cid] = _empty()
            # Landung woanders: NICHTS. Die Ladung bleibt an Bord (Milchmann/Zwischenlandung).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_transport_stacks.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add app/transport_stacks.py tests/test_transport_stacks.py
git commit -m "feat(kutter): Landung am Ziel liefert, Zwischenlandung laesst die Ladung an Bord"
```

---

### Task 4: Logout — zurück, gestohlen, versenkt

**Files:**
- Modify: `app/transport_stacks.py`
- Test: `tests/test_transport_stacks.py`

**Interfaces:**
- Consumes: alles aus Task 3.
- Produces: `_drop_load(state, cid, ts)` — der gemeinsame Helfer fuer `logout` UND einen
  zweiten `login` ohne Logout dazwischen. `movements` bekommt
  `{"kind": "returned"|"stolen"|"sunk", ...}` — **dieselben drei Namen wie das heutige
  `loss_kind`**, damit Feed und Badge unverändert weiterlesen können.

**Regeln (Spec, Entscheidung 2):** Logout am Ladeplatz → zurück in den Stapel **dieses** Platzes
(nicht des ursprünglichen!). Logout am fremden Platz → gestohlen. Logout in der Luft → versenkt.
Logout am Ziel → nichts (bei der Landung längst geliefert). **Das gilt auch beim unfreiwilligen
Verbindungsabbruch** („Ja. Ist halt so.", Nutzer 15.07.).

- [ ] **Step 1: Write the failing test**

```python
def test_s4_logout_am_zweiten_ladeplatz_gibt_dort_zurueck():
    """S4: EDWG -> EDWZ, Logout. HEUTE: 'returned' -> zurück in den EDWG-Topf.
    Nutzer 15.07.: 'Die Ware bleibt an dem Platz, an dem ausgeloggt wird!'"""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),                        # lädt 800 Fisch
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDWZ"),  # + 200 Tee (Kapazität 1000)
            _ev("logout", 1, "2026-07-01T09:35:00Z"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"]["EDWZ"]["Fischbrötchen"] == 800.0   # liegt jetzt in EDWZ, NICHT in EDWG
    assert r["stacks"]["EDWZ"]["Friesen Tee"] == 500.0      # 300 lagen noch da + 200 zurück
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 0.0
    _assert_erhaltung(r)


def test_s5_logout_am_fremden_platz_ist_diebstahl():
    """S5: EDWG -> EDDW(fremd), Logout. Er nimmt die Ware mit nach Hause."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDDW"),
            _ev("logout", 1, "2026-07-01T09:35:00Z"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][STOLEN]["Fischbrötchen"] == 800.0
    _assert_erhaltung(r)


def test_s8_logout_in_der_luft_versenkt():
    """S8 — der Nutzer-Fund vom 15.07. (Event #123, CID 1602713, flights.id 357/358).

    Der Pilot loggt kurz nach dem Start IN DER LUFT aus und Sekunden später am Platz wieder ein.
    Der GPS-Detektor macht daraus EIN Leg EDXH->EDXH mit sauberer Landung — der Logout ist für
    ihn unsichtbar. Eine Regel 'letzter Leg -> gps_arrival' ergäbe fälschlich 'zurück'.
    Hier fällt es von selbst richtig: takeoff hat position auf None gesetzt.
    """
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),                          # lädt 800 Fisch
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),            # position -> None
            _ev("logout", 1, "2026-07-01T09:07:00Z"),             # IN DER LUFT -> versenkt
            _ev("login", 1, "2026-07-01T09:08:00Z", "EDWG"),      # sofort wieder da, leer
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][SUNK]["Fischbrötchen"] == 800.0
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 0.0   # der Stapel ist leer, nichts nachzuladen
    assert _sum_onboard(r["onboard"]) == 0.0
    _assert_erhaltung(r)


def test_logout_am_ziel_verliert_nichts():
    """Bei der Landung wurde längst geliefert — der Logout findet einen leeren Flieger vor."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:30:00Z", "EDXH"),
            _ev("logout", 1, "2026-07-01T09:35:00Z"),
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"][DEST]["Fischbrötchen"] == 800.0
    assert r["stacks"][STOLEN]["Fischbrötchen"] == 0.0   # NICHT gestohlen
    assert r["stacks"][SUNK]["Fischbrötchen"] == 0.0


def test_logout_gibt_auch_frisch_geladenes_zurueck():
    """Entscheidung 4: 'Auch mit dem, was er eben erst geladen hat.'"""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[_ev("login", 1, T0, "EDWG"), _ev("logout", 1, "2026-07-01T09:01:00Z")],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 800.0
    _assert_erhaltung(r)


def test_zweiter_login_ohne_logout_verliert_keine_ware():
    """Fable-Review 16.07. — der Erhaltungssatz braecher sonst in einem REALEN Fall.

    Trigger: Ein ungracefuler Disconnect lässt die alte flights-Zeile offen (logoff_time NULL),
    der Reconnect erzeugt eine neue. close_stale_flights räumt erst nach 8 h auf
    (database.py:895). In diesem Fenster liefert der Adapter zwei login-Ereignisse OHNE logout
    dazwischen. Würde login die Bordladung einfach leeren, verschwänden 800 kg aus dem
    Universum — und weil dann Summe onboard == 0 gilt, könnte das Event mit der verschwundenen
    Ware sogar EINFRIEREN (transport_anyone_in_progress = False). Der Freeze ist endgültig.

    Der zweite Login verteilt die alte Ladung deshalb wie ein Logout: dieselbe Regel, derselbe
    Helfer (_drop_load) — kein Sonderfall.
    """
    r = derive_stacks(
        manifest=MANIFEST,
        events=[_ev("login", 1, T0, "EDWG"), _ev("login", 1, "2026-07-01T09:01:00Z", None)],
        destination=DEST, loading_airports=LOADING,
    )

    _assert_erhaltung(r)                                   # <- der eigentliche Test
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 800.0   # stand am Ladeplatz -> zurück
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport_stacks.py -v`
Expected: FAIL — `assert 0.0 == 800.0` in `test_s4_...` (der Logout wirft die Ladung heute weg,
statt sie zu verteilen: `onboard.pop` ohne Ziel-Stapel → **der Erhaltungssatz bricht**)

- [ ] **Step 3: Write minimal implementation**

Ersetze den `logout`-Zweig in `derive_stacks`:

```python
        elif kind == "logout":
            _drop_load(state, cid, ts)
            position.pop(cid, None)
            since.pop(cid, None)
```

Und der `login`-Zweig gibt eine etwaige Alt-Ladung **mit derselben Regel** ab, statt sie zu leeren:

```python
        if kind == "login":
            # Trägt er noch etwas (zwei logins ohne logout dazwischen — ungracefuler Disconnect
            # + Reconnect, close_stale_flights räumt erst nach 8 h auf), fällt es hier ab wie
            # bei einem Logout. Ein bloßes onboard[cid] = {} würde die Ware aus dem Universum
            # löschen und den Erhaltungssatz brechen (Fable-Review 16.07.).
            _drop_load(state, cid, ts)
            onboard[cid] = _empty()
            position[cid] = e.get("airport")     # None = in der Luft eingeloggt
            since[cid] = ts
            if e.get("airport"):
                last_ground[cid] = e["airport"]
```

Der gemeinsame Helfer — **eine** Regel, zwei Aufrufer:

```python
def _drop_load(state: dict, cid: int, ts: str) -> None:
    """Die Bordladung abgeben — dorthin, wo der Pilot gerade ist (Entscheidung 2).

    Wer ausloggt, beendet seine Tour: Was dann an Bord ist, bleibt liegen, wo er ist. Das gilt
    auch beim unfreiwilligen Verbindungsabbruch — ein Netzausfall in der Luft ist im Track nicht
    von einem bewussten Ausstieg zu unterscheiden ("Ja. Ist halt so.", Nutzer 15.07.).

    Der Ort braucht keine Sonderregel: `position` ist bereits richtig, weil `takeoff` sie auf
    None gesetzt hat. Ein Logout zwischen Takeoff und Landung findet None vor -> versenkt. Genau
    der Fall S8 (Logout in der Luft, Sekunden später Login am Platz), bei dem der Detektor EIN
    durchgehendes Leg mit sauberer Landung sieht — eine Regel "letzter Leg -> gps_arrival"
    ergäbe dort fälschlich 'zurück'.
    """
    load = state["onboard"].pop(cid, None) or {}
    if not any(kg > _EPS for kg in load.values()):
        return
    where = state["position"].get(cid)
    if where == state["destination"]:
        return                                   # bei der Landung längst geliefert
    if where in state["loading_airports"]:
        target, kind_name = where, "returned"
    elif where:
        target, kind_name = STOLEN, "stolen"
    else:
        target, kind_name = SUNK, "sunk"
    for name, kg in load.items():
        if kg <= _EPS:
            continue
        state["stacks"][target][name] += kg
        state["movements"].append({"ts": ts, "cid": cid, "kind": kind_name,
                                   "airport": where, "name": name, "kg": kg})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_transport_stacks.py -v`
Expected: PASS (18 passed)

- [ ] **Step 5: Commit**

```bash
git add app/transport_stacks.py tests/test_transport_stacks.py
git commit -m "feat(kutter): Logout verteilt die Ladung — zurueck, gestohlen oder versenkt"
```

---

### Task 5: Kappung, Musterwechsel und der Wartende

**Files:**
- Modify: `app/transport_stacks.py`
- Test: `tests/test_transport_stacks.py`

**Interfaces:**
- Consumes: alles aus Task 4. Ändert `_take` um die `per_flight_max_kg`-Grenze.
- Produces: keine neue Signatur — nur die Kappungs-Regel in `_take`.

**Regel (Spec):** `per_flight_max_kg` begrenzt, **was ein Flieger von einer Frachtart AN BORD hat**
— nicht, was er je Ladevorgang aufnimmt. Sonst wäre die Kappung durch mehrfaches Landen am selben
Platz umgehbar (zehn Platzrunden = zehnmal die Kappungsmenge in einer Lieferung; Fable-Review).
Formal: `nimm = min(Stapel, freie Kapazität, per_flight_max_kg − bereits_an_Bord[frachtart])`.

- [ ] **Step 1: Write the failing test**

```python
CAPPED = [
    {"name": "Fischbrötchen", "target_kg": 800.0, "departure": "EDWG", "per_flight_max_kg": 50.0},
    {"name": "Friesen Tee", "target_kg": 500.0, "departure": "EDWG", "per_flight_max_kg": None},
]


def test_kappung_begrenzt_was_an_bord_ist_nicht_den_ladevorgang():
    """Fable-Review: sonst wäre die Kappung durch mehrfaches Landen umgehbar (zehn Platzrunden
    = zehnmal die Kappungsmenge, alles in EINER Lieferung)."""
    r = derive_stacks(
        manifest=CAPPED,
        events=[
            _ev("login", 1, T0, "EDWG"),                          # nimmt 50 Fisch + 500 Tee
            _ev("takeoff", 1, "2026-07-01T09:05:00Z"),
            _ev("landing", 1, "2026-07-01T09:10:00Z", "EDWG"),    # Platzrunde: NICHT nochmal 50
            _ev("takeoff", 1, "2026-07-01T09:15:00Z"),
            _ev("landing", 1, "2026-07-01T09:20:00Z", "EDWG"),    # und nochmal nicht
        ],
        destination=DEST, loading_airports={"EDWG"},
    )

    assert r["onboard"][1]["Fischbrötchen"] == 50.0     # nicht 150
    assert r["onboard"][1]["Friesen Tee"] == 500.0
    _assert_erhaltung(r)


def test_kappung_spillt_in_die_naechste_frachtart():
    """Co-Load: was die Kappung übrig lässt, füllt die nächste Zeile (Bestandsverhalten)."""
    r = derive_stacks(manifest=CAPPED, events=[_ev("login", 1, T0, "EDWG", capacity_kg=200.0)],
                      destination=DEST, loading_airports={"EDWG"})

    assert r["onboard"][1]["Fischbrötchen"] == 50.0
    assert r["onboard"][1]["Friesen Tee"] == 150.0      # 200 kg Zuladung - 50 Fisch


def test_der_wartende_laedt_nach_wenn_ware_zurueckkommt():
    """Entscheidung 13: Steht jemand am leeren Stapel und ein anderer gibt dort zurück,
    lädt der Wartende — er steht ja am Platz, und Ware ist da."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),                              # nimmt alle 800
            _ev("login", 2, "2026-07-01T09:01:00Z", "EDWG"),          # steht am leeren Stapel
            _ev("logout", 1, "2026-07-01T09:02:00Z"),                 # gibt 800 zurück
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["onboard"][2]["Fischbrötchen"] == 800.0   # der Wartende hat nachgeladen
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 0.0
    _assert_erhaltung(r)


def test_von_zwei_wartenden_laedt_der_laenger_stehende():
    """Entscheidung 5, der einzige Fall, in dem die Ankunftsreihenfolge überhaupt befragt wird.

    Bei nur EINEM Wartenden ist die Sortierung wirkungslos: `_load_standing` läuft nach jedem
    Ereignis, der Erste hat den Stapel also leergeräumt, bevor der Zweite überhaupt einloggt.
    Erst wenn ZWEI am leeren Stapel stehen und Ware zurückkommt, entscheidet der Schlüssel,
    wer sie bekommt.

    Die später angekommene CID ist absichtlich die KLEINERE (3 vor 2): sonst wären Ankunfts-
    und CID-Reihenfolge identisch und ein `sorted(standing)` ohne `since` bliebe grün.
    """
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG"),                              # nimmt alle 800
            _ev("login", 3, "2026-07-01T09:01:00Z", "EDWG"),          # wartet, größere CID
            _ev("login", 2, "2026-07-01T09:02:00Z", "EDWG"),          # wartet, aber später da
            _ev("logout", 1, "2026-07-01T09:03:00Z"),                 # gibt 800 zurück
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["onboard"][3]["Fischbrötchen"] == 800.0   # stand länger da
    assert r["onboard"][2]["Fischbrötchen"] == 0.0     # kleinere CID, aber zu spät
    _assert_erhaltung(r)


def test_musterwechsel_am_boden_laedt_mit_der_neuen_kapazitaet():
    """Entscheidung 11: Am Boden wird umgeladen. Braucht keine eigene Regel — der Musterwechsel
    IST ein Logout (Ladung fällt ab) plus ein Login (lädt neu, mit neuer Kapazität)."""
    r = derive_stacks(
        manifest=MANIFEST,
        events=[
            _ev("login", 1, T0, "EDWG", capacity_kg=1000.0),
            _ev("logout", 1, "2026-07-01T09:05:00Z"),                          # gibt 800 zurück
            _ev("login", 1, "2026-07-01T09:06:00Z", "EDWG", capacity_kg=250.0),  # kleineres Muster
        ],
        destination=DEST, loading_airports=LOADING,
    )

    assert r["onboard"][1]["Fischbrötchen"] == 250.0
    assert r["stacks"]["EDWG"]["Fischbrötchen"] == 550.0
    _assert_erhaltung(r)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport_stacks.py -v`
Expected: FAIL — `assert 150.0 == 50.0` in `test_kappung_begrenzt_was_an_bord_ist...`
(`per_flight_max_kg` wird noch gar nicht gelesen)

- [ ] **Step 3: Write minimal implementation**

Ersetze in `_take` den Schleifenrumpf:

```python
    for c in state["manifest"]:
        if free <= _EPS:
            break
        name = c["name"]
        available = stack.get(name, 0.0)
        if available <= _EPS:
            continue
        take = min(available, free)
        # #63: `per_flight_max_kg` begrenzt, was AN BORD ist — nicht, was je Ladevorgang
        # aufgenommen wird. Sonst wäre die Kappung durch mehrfaches Landen am selben Platz
        # umgehbar (zehn Platzrunden = zehnmal die Kappungsmenge in EINER Lieferung).
        cap = c.get("per_flight_max_kg")
        if cap is not None and cap > 0:
            take = min(take, float(cap) - load.get(name, 0.0))
        if take <= _EPS:
            continue
        stack[name] -= take
        load[name] = load.get(name, 0.0) + take
        free -= take
        state["movements"].append(
            {"ts": ts, "cid": cid, "kind": "load", "airport": airport, "name": name, "kg": take}
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_transport_stacks.py -v`
Expected: PASS (23 passed)

- [ ] **Step 4b: Beweisen, dass der Reihenfolge-Test wirklich beißt** (Mutationsprobe)

`test_von_zwei_wartenden_laedt_der_laenger_stehende` ist der **einzige** Test im ganzen Plan, der
die Ankunftsreihenfolge überhaupt befragt. Ein Test, der eine Regel nur scheinbar schützt, ist
schlimmer als keiner — deshalb wird er hier gegengeprüft, nicht geglaubt.

Ändere in `app/transport_stacks.py` die Sortierzeile in `_load_standing` **vorübergehend**:

```python
    # NUR ZUR PROBE — danach zurückdrehen:
    for cid in sorted(standing):                    # statt: key=lambda c: (state["since"].get(c, ""), c)
```

Run: `pytest tests/test_transport_stacks.py -v`
Expected: **FAIL** in `test_von_zwei_wartenden_laedt_der_laenger_stehende`
(`assert 0.0 == 800.0` — CID 2 hätte geladen, obwohl CID 3 länger stand)

Bleibt der Test dabei **grün**, prüft er die Reihenfolge nicht und ist wertlos — dann melden,
nicht weitergehen. Danach die Zeile zurückdrehen und erneut `pytest tests/test_transport_stacks.py -v`
laufen lassen: wieder 23 grün. Den Mutations-Output (rot) und den Rückdreh-Output (grün) in den
Bericht aufnehmen.

- [ ] **Step 5: Commit**

```bash
git add app/transport_stacks.py tests/test_transport_stacks.py
git commit -m "feat(kutter): per_flight_max_kg begrenzt die Bordladung, nicht den Ladevorgang"
```

---

### Task 6: Der Adapter — aus der DB wird eine Ereignisliste

**Files:**
- Modify: `app/database.py` (neue Funktion, **noch kein Aufrufer** — der alte Kern bleibt intakt)
- Test: `tests/test_transport.py` (neue Klasse `TestStackInputs` ans Dateiende)

**Interfaces:**
- Consumes: `canonicalize_legs` (`database.py:2483`), `get_payload_map` (4076),
  `transport_default_payload_kg` (4067), `get_transport_cargo` (4405), `_nearest_airport` (3131),
  `_first_pos` (1730), `_current_pos` (5179), `_BLOCK_GS_KT`, `_BUMMEL_AIRPORT_RADIUS_KM`,
  `_BUMMEL_EARLY_START_LOOKBACK_H`, `_shift_iso`, `normalize_type_code`.
- Produces: `_stack_inputs(conn, event, now, *, callsign_prefix="FRS") -> dict` mit den Schlüsseln
  `manifest`, `events`, `loading_airports`, `destination`, `legs_by_cid`, `sessions`.
  Die ersten vier gehen direkt in `derive_stacks`; `legs_by_cid` und `sessions` braucht Task 8 für
  den Feed (Callsign, Muster, `distance_nm`, `block_min`) — `canonicalize_legs` ein zweites Mal
  aufzurufen wäre teuer, das ist der Grund für das Dict statt eines Tupels.
- Produces: `_sort_stack_events(events) -> list[dict]`.

**Feld-Vertrag `canonicalize_legs` (kritisch — hier lag schon einmal ein Messfehler):** Ein Leg trägt
`logon_time` = **GPS-Takeoff dieses Legs** und `logoff_time` = **Landezeit** (nicht `landing_ts`!).
Beleg im Bestand: `database.py:5527` (`leg_takeoff = current_leg.get("logon_time")`) und
`database.py:5361` (`if _leg.get("logoff_time")` = Leg abgeschlossen).

**⚠ Drei Fallen, die dieser Task lösen MUSS** (Fable-Review 16.07., alle am Code verifiziert):

**1. Eine `flights`-Zeile ist KEINE VATSIM-Session.** Der Poller **splittet** eine laufende
Verbindung, sobald der Flugplan mit **geändertem Abflugplatz** refiled wird: `close_flight` +
`open_flight` in derselben Verbindung (`poller.py:832-852`, Log „Neues Leg CID …"). Wer unterwegs
schon den Rückflug filed (`dep` = aktuelles Ziel), bekommt so ein `logoff_time` **mitten in der
Luft** — ungefixt würde eine reine **Flugplan-Änderung die Fracht versenken**. Das verletzt #23
(„der Flugplan ist keine Wahrheit") und Entscheidung 2 (die nur echte Verbindungsabbrüche meint).

**Fix (Nutzer-Entscheidung 16.07.): Sessions verketten.** Endet eine Session und beginnt binnen
`_SESSION_GAP_SEC` = 2 s eine neue derselben CID, war es ein Refile-Split — beide werden zu **einer**
Verbindung verschmolzen, der Logout dazwischen entfällt. Das ist robust gegen
Implementierungsdetails (der Poller schreibt Split-Zeilen zwar mit Mikrosekunden-Zeitstempel,
`poller.py:838` — aber daran wollen wir nicht hängen). **Der echte S8-Fall bleibt ein Logout**: dort
liegen 2:54 min zwischen Logout und Re-Login.

**2. Legs nach `dtend` dürfen nicht verschwinden.** `canonicalize_legs` filtert `takeoff > end`
(`database.py:2573-2582`). Mit `end = min(now, dtend)` sähe das Modell weder Takeoff noch Landung
eines um 22:05 gestarteten Fluges (dtend 22:00) — der Pilot „stünde" ewig am Ladeplatz, seine Ware
könnte **nie** ankommen, und beim Logout am Ziel würde sie als `returned` verbucht. Die Spec
verspricht das Gegenteil (Entscheidung 10: „das Event wartet, bis die Ware angekommen ist").
**Fix:** `end=now` für die Legs; das Event-Fenster begrenzt, welche **Sessions** teilnehmen
(`logon_time <= dtend`), nicht welche Legs fliegen. Der Altcode löst dasselbe mit einem zweiten
`canonicalize_legs`-Aufruf (`database.py:5344-5349`) — wir brauchen nur einen.

**3. StatSim-Legs haben keine `flights`-Zeile.** Sie sind der Backfill-Pfad bei Poller-/VPS-Ausfall
(eigene Tabellen `statsim_cache`/`statsim_position_history`, `database.py:107-130`). Ohne Session
gäbe es für sie weder Takeoff noch Landung — sie lieferten still 0 kg, obwohl sie heute mitzählen.
**Fix (Nutzer-Entscheidung 16.07.): wie ein normaler Flug.** Ein StatSim-Leg erzeugt seine
Ereignisse selbst: `login` am `gps_departure`, `takeoff`, `landing` — und ein `logout` am Landeort,
denn der Flug ist vorbei. Landet er am Ziel, liefert er; landet er woanders, gilt dort dieselbe
Regel wie sonst.

**4. Der Logout darf nie auf der eigenen Landung liegen** *(am 16.07. beim Bauen gefunden — die
gefährlichste Falle des Adapters, und sie stand zunächst nicht in diesem Plan).*

`app/poller.py:885-891` schließt einen Flug mit `close_flight(conn, id, last_pos or now_str)`, wobei
`last_pos = MAX(ts) FROM position_history` ist. **`logoff_time` ist also der Zeitstempel des letzten
GPS-Samples**, nicht eine eigene Uhrzeit. Der Poll-Takt beträgt 15 s (`VATSIM_POLL_INTERVAL=15`).

Wer landet und **innerhalb eines Poll-Takts** aussteigt, dessen letztes Sample *ist* damit das
Touchdown-Sample: `logoff_time == landing_ts`, exakt. Bei Gleichstand sortiert
`_STACK_EVENT_PRIO` den Logout **vor** die Landung; er findet `position=None` vor (der `takeoff`
hat sie geleert) und **versenkt die Fracht, statt sie abzuliefern**.

Das ist kein Grenzfall, sondern der **Normalfall des FriesenKutter**: „Fracht am Ziel abgeliefert,
Sim zu, Feierabend." Ungefixt hätte das Modell ausgerechnet die häufigste Lieferung versenkt.

**Fix:** Der Logout einer Session wird auf `letzte eigene Landung + 1 s` geschoben, **wenn** er auf
oder vor ihr liegt — sonst bleibt er, wo er ist. `_STACK_EVENT_PRIO` bleibt unverändert
(`test_bei_gleicher_zeit_gilt_der_logout_zuerst` pinnt die Regel bewusst). Derselbe Kniff wie im
StatSim-Zweig, aber dort war er nur für synthetische Logouts gedacht.

**Der Login-Ort — Regel (kein Flugplan, #23):**

1. Hat die Session ein erstes Leg, dessen Takeoff **nach** dem Login liegt → `gps_departure` dieses
   Legs. Das ist die GPS-Wahrheit und deckt auch den Piloten ab, der beim ersten Poll schon **rollt**
   (`gs > 2`) — eine reine `gs<2`-Prüfung würde ihn fälschlich als „nicht am Platz" werten und seine
   Fracht still verlieren.
2. Sonst (kein Leg — er steht nur da): aktuelle Live-Position (`_current_pos`) bzw. erste Position
   der Session, wenn am Boden (`gs < _BLOCK_GS_KT`) und im Radius eines Platzes. Das ist exakt die
   heutige Boden-Beladung (#5, v8.22.0) — kein neues Verhalten.
3. Sonst `None` (in der Luft eingeloggt / keine verwertbare Position).

**Sortierung:** nach `ts`, bei Gleichstand nach Priorität `{"logout": 0, "login": 1, "landing": 2,
"takeoff": 3}`. Der Logout zuerst (Spec: er beendet die Tour, eine Landung im selben Moment kann
nichts mehr abliefern); `landing` vor `takeoff`, damit ein Stop-and-Go im selben Sample nicht
verdreht wird.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transport.py — neue Klasse ans Dateiende anhängen
class TestStackInputs:
    """Der Adapter: aus Legs + Sessions wird eine chronologische Ereignisliste."""

    def _load_event(self, conn):
        upsert_payload(conn, "C208", payload_kg=1000)
        conn.commit()
        return _event(conn, route="EDWG,EDXH", destination="EDXH",
                      cargo=[{"name": "Fisch", "target_kg": 800, "departure": "EDWG"}])

    def test_session_ohne_leg_ergibt_login_am_platz_aus_der_live_position(self):
        from app.database import _stack_inputs
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._load_event(conn)
        _add_open_flight(conn, 61, "EDXP", "EDWK", "C208", START)   # Flugplan bewusst falsch
        lat, lon = icao_to_coords("EDWG")
        _set_live_pos(conn, 61, lat, lon, 0)                        # real steht er in EDWG

        inp = _stack_inputs(conn, ev, _shift(START, 5))

        assert inp["destination"] == "EDXH"
        assert inp["loading_airports"] == {"EDWG"}
        assert [e["kind"] for e in inp["events"]] == ["login"]
        assert inp["events"][0]["airport"] == "EDWG"   # Live-Position gewinnt, nicht der Plan
        assert inp["events"][0]["capacity_kg"] == 1000.0
        assert len(inp["sessions"]) == 1               # für den Feed (Task 8)

    def test_leg_ergibt_takeoff_und_landing_mit_gps_orten(self):
        from app.database import _stack_inputs
        from app.geo import icao_to_coords, airport_elevation_ft
        conn = _make_conn()
        ev = self._load_event(conn)
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        alat, alon = icao_to_coords("EDXH")
        aelev = airport_elevation_ft("EDXH") or 0
        _add_flight(conn, 12, "EDWG", "EDXH", "C208", START, duration_min=40)
        _add_pos(conn, 12, START, dlat, dlon, 0, alt=delev)
        _add_pos(conn, 12, _shift(START, 2), dlat, dlon, 80, alt=delev + 1200)   # Takeoff
        _add_pos(conn, 12, _shift(START, 20), 54.0, 7.9, 120, alt=4000)
        _add_pos(conn, 12, _shift(START, 38), alat, alon, 40, alt=aelev + 400)
        _add_pos(conn, 12, _shift(START, 40), alat, alon, 0, alt=aelev)          # Touchdown

        inp = _stack_inputs(conn, ev, END)

        kinds = [e["kind"] for e in inp["events"]]
        assert kinds == ["login", "takeoff", "landing", "logout"]
        assert inp["events"][0]["airport"] == "EDWG"   # Login-Ort aus gps_departure des Legs
        assert inp["events"][2]["airport"] == "EDXH"   # Landung aus gps_arrival
        assert 12 in inp["legs_by_cid"]                # für den Feed (Task 8)

    def test_bei_gleicher_zeit_gilt_der_logout_zuerst(self):
        """Spec: er beendet die Tour — eine Landung im selben Moment kann nichts mehr abliefern."""
        from app.database import _sort_stack_events
        same = "2026-07-01T10:00:00Z"
        events = [
            {"ts": same, "kind": "landing", "cid": 1, "airport": "EDXH", "capacity_kg": 0},
            {"ts": same, "kind": "logout", "cid": 1, "airport": None, "capacity_kg": 0},
        ]
        assert [e["kind"] for e in _sort_stack_events(events)] == ["logout", "landing"]

    def test_manifest_kommt_in_ladereihenfolge(self):
        from app.database import _stack_inputs
        conn = _make_conn()
        ev = _event(conn, route="EDWG,EDXH", destination="EDXH", cargo=[
            {"name": "Zuerst", "target_kg": 100, "departure": "EDWG"},
            {"name": "Danach", "target_kg": 200, "departure": "EDWG"},
        ])
        inp = _stack_inputs(conn, ev, END)

        assert [c["name"] for c in inp["manifest"]] == ["Zuerst", "Danach"]

    def test_refile_split_ist_kein_logout(self):
        """Fable-Review 16.07. (BLOCKER): Der Poller splittet eine LAUFENDE Verbindung, sobald
        der Flugplan mit geändertem Abflugplatz refiled wird (poller.py:832) — close_flight +
        open_flight. Wer unterwegs den Rückflug filed, bekäme so ein logoff_time in der Luft
        und seine Fracht würde durch eine reine Flugplan-Aenderung versenkt (#23-Verstoß).
        """
        from app.database import _stack_inputs
        conn = _make_conn()
        ev = self._load_event(conn)
        # Session 1: bis 09:30:00 (Poller schließt sie beim Refile)
        _add_flight(conn, 12, "EDWG", "EDXH", "C208", START, duration_min=30)
        # Session 2: 09:30:00.123456 — Mikrosekunden = Split-Signatur des Pollers
        conn.execute(
            "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, logon_time) "
            "VALUES (12, 'FRS12', 'C208', 'EDXH', 'EDWG', ?)",
            ("2026-07-01T09:30:00.123456Z",),
        )
        conn.commit()

        inp = _stack_inputs(conn, ev, END)

        # EINE Verbindung: kein logout dazwischen, nur der (noch offene) Rest.
        assert [e["kind"] for e in inp["events"]].count("logout") == 0
        assert [e["kind"] for e in inp["events"]].count("login") == 1
        assert len(inp["sessions"]) == 1
        assert inp["sessions"][0]["logoff_time"] is None   # verkettet -> die Session läuft

    def test_echter_logout_bleibt_ein_logout(self):
        """Gegenprobe zu S8 (Nutzer-Fund, flights.id 357/358): 2:54 min Lücke = echter Logout,
        keine Verkettung. Sonst würde der Fix den Fall kaputtmachen, den er schützen soll."""
        from app.database import _stack_inputs
        conn = _make_conn()
        ev = self._load_event(conn)
        _add_flight(conn, 12, "EDWG", "EDXH", "C208", START, duration_min=30)   # bis 09:30
        _add_open_flight(conn, 12, "EDWG", "EDXH", "C208", "2026-07-01T09:32:54Z")

        inp = _stack_inputs(conn, ev, END)

        assert [e["kind"] for e in inp["events"]].count("logout") == 1
        assert len(inp["sessions"]) == 2

    def test_leg_nach_dtend_geht_nicht_verloren(self):
        """Fable-Review 16.07. (BLOCKER): canonicalize_legs filtert takeoff > end
        (database.py:2573). Mit end=min(now,dtend) könnte die Ware eines um 22:05 gestarteten
        Fluges NIE ankommen — Widerspruch zu Entscheidung 10."""
        from app.database import _stack_inputs
        from app.geo import icao_to_coords, airport_elevation_ft
        conn = _make_conn()
        ev = self._load_event(conn)          # dtend = END = 23:00
        spät = "2026-07-01T22:55:00Z"       # Start kurz vor dtend, Landung DANACH
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        alat, alon = icao_to_coords("EDXH")
        aelev = airport_elevation_ft("EDXH") or 0
        _add_flight(conn, 12, "EDWG", "EDXH", "C208", spät, duration_min=30)
        _add_pos(conn, 12, spät, dlat, dlon, 0, alt=delev)
        _add_pos(conn, 12, _shift(spät, 2), dlat, dlon, 80, alt=delev + 1200)
        _add_pos(conn, 12, _shift(spät, 28), alat, alon, 40, alt=aelev + 400)
        _add_pos(conn, 12, _shift(spät, 30), alat, alon, 0, alt=aelev)   # 23:25 — NACH dtend

        inp = _stack_inputs(conn, ev, "2026-07-01T23:40:00Z")

        assert "landing" in [e["kind"] for e in inp["events"]]
        landing = next(e for e in inp["events"] if e["kind"] == "landing")
        assert landing["airport"] == "EDXH"

    def test_statsim_leg_erzeugt_eigene_ereignisse(self):
        """Nutzer-Entscheidung 16.07.: StatSim (Backfill bei VPS-Ausfall) zählt wie ein
        normaler Flug — Login am Startplatz, Takeoff, Landung, Logout am Landeort."""
        from app.database import _stack_inputs
        conn = _make_conn()
        ev = self._load_event(conn)
        # StatSim-Flug OHNE flights-Zeile (der Poller lief nicht):
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id, cid, callsign, departure, arrival, "
            "aircraft, logon_time, logoff_time) VALUES (9001, 12, 'FRS12', 'EDWG', 'EDXH', "
            "'C208', ?, ?)", (START, _shift(START, 30)),
        )
        conn.commit()

        inp = _stack_inputs(conn, ev, END)
        kinds = [e["kind"] for e in inp["events"]]

        assert kinds == ["login", "takeoff", "landing", "logout"]
        assert inp["events"][0]["airport"] == "EDWG"
```

*(Schema `statsim_cache`, `database.py:106-117` — am 16.07. am Code geprueft: Die Tabelle hiess
im Plan zunaechst faelschlich `statsim_flights`; die gibt es nicht. Pflichtfelder sind
`duration_min` (canonicalize_legs verlangt `duration_min > 5`) und `fetched_at TEXT NOT NULL` —
beim Schreiben des Tests dort nachsehen und die Spalten exakt übernehmen; `statsim_position_history`
braucht zusätzlich einen Track, damit `canonicalize_legs` ein Leg erkennt.)*

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport.py::TestStackInputs -v`
Expected: FAIL — `ImportError: cannot import name '_stack_inputs' from 'app.database'`

- [ ] **Step 3: Write minimal implementation**

Neue Funktionen in `app/database.py`, direkt **vor** `compute_transport_progress` (also vor Zeile
5278) einfügen:

```python
# Reihenfolge bei gleichem Zeitstempel. Der Logout zuerst (er beendet die Tour — eine Landung im
# selben Moment kann nichts mehr abliefern, Spec). `landing` vor `takeoff`, damit ein Stop-and-Go
# im selben Sample nicht verdreht wird.
_STACK_EVENT_PRIO = {"logout": 0, "login": 1, "landing": 2, "takeoff": 3}


def _sort_stack_events(events: list[dict]) -> list[dict]:
    """Ereignisse chronologisch ordnen; bei gleichem ts entscheidet _STACK_EVENT_PRIO."""
    return sorted(events, key=lambda e: (e["ts"], _STACK_EVENT_PRIO.get(e["kind"], 9), e["cid"]))


# Refile-Splits erkennen: Der Poller schließt eine laufende Verbindung und öffnet sofort eine
# neue, sobald der Flugplan mit GEAENDERTEM Abflugplatz refiled wird (poller.py:832-852). Beide
# Zeilen gehören zu EINER VATSIM-Verbindung — der "Logout" dazwischen ist keiner. Zwei Sekunden
# reichen als Grenze: der Split passiert im selben Poll-Takt (close/open unmittelbar nacheinander),
# ein echter Reconnect braucht länger. Belegter Gegenfall S8 (flights.id 357/358): 2:54 min.
_SESSION_GAP_SEC = 2


def _transport_sessions(conn: sqlite3.Connection, start: str, end: str,
                        callsign_prefix: str) -> list[dict]:
    """VATSIM-Verbindungen, die das Event-Fenster berühren (offene wie geschlossene).

    Der Logout ist ein Ereignis der VERBINDUNG, nicht des Tracks (Spec) — der GPS-Detektor kennt
    keine Verbindungsgrenzen und segmentiert erst bei Lücken > 30 min.

    **Achtung, Refile-Split (Fable-Review 16.07.):** Eine `flights`-Zeile ist KEINE Verbindung.
    Der Poller splittet bei einem Refile mit geändertem Abflugplatz (close_flight + open_flight,
    poller.py:832) — wer unterwegs den Rückflug filed, hätte sonst ein logoff_time IN DER LUFT
    und seine Fracht würde durch eine reine Flugplan-Aenderung versenkt (#23-Verstoß). Solche
    Zeilen werden hier wieder zu einer Verbindung VERKETTET.

    ``logon_time <= end`` begrenzt die TEILNAHME (wer nach dtend einloggt, macht nicht mehr mit);
    die LEGS laufen bewusst bis ``now`` weiter (s. _stack_inputs) — sonst könnte die Ware eines
    kurz vor dtend gestarteten Fluges nie ankommen.
    """
    rows = conn.execute(
        "SELECT cid, callsign, aircraft_short AS aircraft, aircraft_icao, logon_time, logoff_time "
        "FROM flights WHERE superseded_by IS NULL AND callsign LIKE ? "
        "AND logon_time <= ? AND (logoff_time IS NULL OR logoff_time >= ?) "
        "ORDER BY cid, logon_time",
        (callsign_prefix + "%", end, start),
    ).fetchall()

    merged: list[dict] = []
    for r in (dict(x) for x in rows):
        prev = merged[-1] if merged else None
        if (prev is not None and prev["cid"] == r["cid"] and prev.get("logoff_time")
                and _gap_seconds(prev["logoff_time"], r["logon_time"]) <= _SESSION_GAP_SEC):
            # Refile-Split: dieselbe Verbindung läuft weiter. Das Ende der neuen Zeile gilt,
            # das Muster ebenso (der Pilot kann beim Refile den Typ gewechselt haben).
            prev["logoff_time"] = r.get("logoff_time")
            prev["aircraft"] = r.get("aircraft") or prev.get("aircraft")
            prev["aircraft_icao"] = r.get("aircraft_icao") or prev.get("aircraft_icao")
            continue
        merged.append(r)
    merged.sort(key=lambda s: (s["logon_time"], s["cid"]))
    return merged


def _gap_seconds(a: str, b: str) -> float:
    """Sekunden zwischen zwei ISO-Zeitstempeln (b - a); inf bei unlesbaren Werten."""
    try:
        return (_parse_iso(b) - _parse_iso(a)).total_seconds()
    except (ValueError, AttributeError, TypeError):
        return float("inf")


def _covered_by_session(sessions: list[dict], cid: int, takeoff: str | None) -> bool:
    """Deckt eine echte VATSIM-Verbindung dieses Leg ab? (StatSim-Doppelzählung verhindern.)

    canonicalize_legs verwirft StatSim-Legs, die einen FriesenSpy-Flug DESSELBEN cid überlappen,
    bereits selbst (database.py:2499 ff.) — aber nur PRO FLUG, ein unüberdeckter Rest überlebt
    bewusst (z. B. nach einem FS-Absturz). Dieser Test hält die Ereignis-Erzeugung dazu konsistent.
    """
    if not takeoff:
        return False
    for s in sessions:
        if int(s["cid"]) != cid:
            continue
        if (s.get("logon_time") or "") <= takeoff <= (s.get("logoff_time") or "9999"):
            return True
    return False


def _stack_inputs(conn: sqlite3.Connection, event: dict, now: str, *,
                  callsign_prefix: str = "FRS") -> dict:
    """Die Eingänge für :func:`app.transport_stacks.derive_stacks` aus der DB holen.

    Liefert ``{manifest, events, loading_airports, destination, legs_by_cid, sessions}``.
    Reine Uebersetzung — die Regeln stehen in transport_stacks.py, hier wird nur gelesen und
    sortiert. ``legs_by_cid``/``sessions`` reicht der Feed-Bau (compute_transport_progress)
    weiter, damit canonicalize_legs nur EINMAL läuft.
    """
    from app.geo import icao_to_coords

    dest = normalize_type_code(event.get("destination"))
    route_set = {c for c in (normalize_type_code(x) for x in (event.get("route") or "").split(",")) if c}
    loading = route_set - {dest}
    coords_map = {icao: icao_to_coords(icao) for icao in route_set}
    radius = _BUMMEL_AIRPORT_RADIUS_KM
    payload_map = get_payload_map(conn)
    default_kg = transport_default_payload_kg(conn)

    manifest = [
        {"name": c["name"], "target_kg": float(c["target_kg"] or 0.0),
         "departure": (c.get("departure") or "").upper(),
         "per_flight_max_kg": c.get("per_flight_max_kg"),
         "emoji": c.get("emoji")}
        for c in get_transport_cargo(conn, int(event["id"]))
    ]

    start = event.get("dtstart") or ""
    window_end = min(now, event.get("dtend") or now)   # begrenzt die TEILNAHME (Sessions)
    load_start = _shift_iso(start, hours=-_BUMMEL_EARLY_START_LOOKBACK_H)

    # LEGS laufen bis `now`, NICHT bis dtend: canonicalize_legs filtert takeoff > end
    # (database.py:2573) — mit dtend als Grenze könnte die Ware eines kurz vor Schluss
    # gestarteten Fluges nie ankommen (Entscheidung 10 verspricht das Gegenteil). Der Altcode
    # löste dasselbe mit einem ZWEITEN canonicalize_legs-Aufruf (database.py:5344); hier
    # reicht einer.
    legs = canonicalize_legs(conn, start=load_start, end=now, callsign_prefix=callsign_prefix)
    legs = [g for g in legs if (g.get("logoff_time") or now) >= start]   # nichts vor dem Fenster
    legs_by_cid: dict[int, list[dict]] = {}
    for leg in legs:
        if leg.get("cid") is None:
            continue
        legs_by_cid.setdefault(int(leg["cid"]), []).append(leg)
    for rows in legs_by_cid.values():
        rows.sort(key=lambda x: x.get("logon_time") or "")

    sessions = _transport_sessions(conn, start, window_end, callsign_prefix)
    out: list[dict] = []
    for s in sessions:
        cid = int(s["cid"])
        lo = s.get("logon_time") or ""
        lf = s.get("logoff_time")
        type_code = normalize_type_code(s.get("aircraft_icao")) or normalize_type_code(s.get("aircraft"))
        cap = round(payload_map.get(type_code, default_kg), 1)

        # Legs DIESER Session: Takeoff liegt im Sessionfenster.
        own = [g for g in legs_by_cid.get(cid, [])
               if (g.get("logon_time") or "") >= lo and (not lf or (g.get("logon_time") or "") <= lf)]

        # --- Login-Ort (GPS-only, kein Flugplan-Fallback) ---
        airport = None
        if own:
            # 1. Das erste Leg kennt seinen eigenen Startplatz — gilt auch, wenn der Pilot beim
            #    ersten Poll schon rollte (gs > 2). Eine reine gs<2-Prüfung würde ihn hier
            #    fälschlich als "nicht am Platz" werten und seine Fracht still verlieren.
            airport = normalize_type_code(own[0].get("gps_departure")) or None
        else:
            # 2. Er steht nur da (kein Leg): aktuelle Live-Position, sonst die erste der Session.
            #    Am Boden = gs < _BLOCK_GS_KT — exakt die heutige Boden-Beladung (#5, v8.22.0).
            gpos = _current_pos(conn, cid) if lf is None else None
            if gpos and gpos[2] is not None and gpos[2] < _BLOCK_GS_KT:
                airport = _nearest_airport(coords_map, (gpos[0], gpos[1]), radius)
            else:
                row = conn.execute(
                    "SELECT latitude, longitude, groundspeed FROM position_history "
                    "WHERE cid=? AND ts>=? AND ts<=? ORDER BY ts ASC LIMIT 1",
                    (cid, lo, lf or now),
                ).fetchone()
                if row is not None and row["groundspeed"] is not None \
                        and row["groundspeed"] < _BLOCK_GS_KT:
                    airport = _nearest_airport(coords_map, (row["latitude"], row["longitude"]), radius)
        if airport not in route_set:
            airport = None      # kein teilnehmender Platz -> in der Luft/anderswo eingeloggt

        out.append({"ts": lo, "kind": "login", "cid": cid, "airport": airport, "capacity_kg": cap})
        for g in own:
            out.append({"ts": g["logon_time"], "kind": "takeoff", "cid": cid,
                        "airport": None, "capacity_kg": cap})
            if g.get("logoff_time"):     # abgeschlossenes Leg = Landung erkannt
                out.append({"ts": g["logoff_time"], "kind": "landing", "cid": cid,
                            "airport": normalize_type_code(g.get("gps_arrival")) or None,
                            "capacity_kg": cap})
        if lf:
            # Der Logout darf NIE vor oder auf der eigenen Landung liegen: bei gleichem ts gewinnt
            # laut _STACK_EVENT_PRIO der Logout, fände position=None vor (der takeoff hat sie
            # geleert) und würde die Ladung VERSENKEN statt sie abzuliefern.
            # Das ist kein Grenzfall: poller.py:891 schließt den Flug mit
            # `close_flight(conn, id, last_pos)`, wobei last_pos = MAX(ts) aus position_history —
            # logoff_time IST also das letzte GPS-Sample. Wer landet und innerhalb eines
            # Poll-Takts (15 s) aussteigt, hat logoff_time == landing_ts. Das ist der Normalfall
            # "abgeliefert, Feierabend". Dann: eine Sekunde nach der Landung, synthetisch.
            ts_logout = lf
            letzte_landung = max((g["logoff_time"] for g in own if g.get("logoff_time")),
                                 default=None)
            if letzte_landung and _parse_iso(ts_logout) <= _parse_iso(letzte_landung):
                ts_logout = (_parse_iso(letzte_landung) + timedelta(seconds=1)
                             ).strftime("%Y-%m-%dT%H:%M:%SZ")
            out.append({"ts": ts_logout, "kind": "logout", "cid": cid,
                        "airport": None, "capacity_kg": cap})

    # --- StatSim-Legs: Backfill bei Poller-/VPS-Ausfall (Nutzer-Entscheidung 16.07.) ---
    # Sie haben KEINE flights-Zeile (eigene Tabellen, database.py:107-130) und würden sonst
    # still 0 kg liefern, obwohl sie heute mitzählen. Behandlung: wie ein normaler Flug — der
    # Flug ist vorbei, also gehört ein Logout am Landeort dazu.
    session_cids = {int(s["cid"]) for s in sessions}
    for cid, rows in legs_by_cid.items():
        for g in rows:
            if not g.get("statsim_id"):
                continue
            if cid in session_cids and _covered_by_session(sessions, cid, g.get("logon_time")):
                continue     # eine echte Verbindung deckt dieses Leg ab -> kein Doppel
            type_code = normalize_type_code(g.get("aircraft_icao")) or normalize_type_code(g.get("aircraft"))
            cap = round(payload_map.get(type_code, default_kg), 1)
            dep = normalize_type_code(g.get("gps_departure")) or None
            out.append({"ts": g["logon_time"], "kind": "login", "cid": cid,
                        "airport": dep if dep in route_set else None, "capacity_kg": cap})
            out.append({"ts": g["logon_time"], "kind": "takeoff", "cid": cid,
                        "airport": None, "capacity_kg": cap})
            if g.get("logoff_time"):
                arr = normalize_type_code(g.get("gps_arrival")) or None
                out.append({"ts": g["logoff_time"], "kind": "landing", "cid": cid,
                            "airport": arr, "capacity_kg": cap})
                # Der Logout MUSS nach der Landung liegen: bei gleichem ts gewinnt laut
                # _STACK_EVENT_PRIO der Logout — er fände dann position=None vor und würde die
                # Ladung VERSENKEN statt sie abzuliefern. Eine Sekunde später, synthetisch.
                out.append({
                    "ts": (_parse_iso(g["logoff_time"]) + timedelta(seconds=1))
                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "kind": "logout", "cid": cid, "airport": None, "capacity_kg": cap,
                })

    return {
        "manifest": manifest,
        "events": _sort_stack_events(out),
        "loading_airports": loading,
        "destination": dest,
        "legs_by_cid": legs_by_cid,
        "sessions": sessions,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_transport.py::TestStackInputs -v`
Expected: PASS (8 passed)

Dann die Gegenprobe, dass **nichts Bestehendes** kaputt ist (der alte Kern läuft unverändert weiter):

Run: `pytest tests/ -q`
Expected: alle Tests grün (Stand vor dem Umbau)

- [ ] **Step 5: Commit**

```bash
git add app/database.py tests/test_transport.py
git commit -m "feat(kutter): Adapter — aus Legs und Sessions wird eine Ereignisliste"
```

---

### Task 7: ⏸ GATE — die Migration nachrechnen, bevor irgendetwas umgestellt wird

**Files:**
- Modify: `scripts/kutter_stapel_prototyp.py` (auf `_stack_inputs` + `derive_stacks` umstellen —
  bisher rechnet er mit einer eigenen, im Skript eingebauten Kopie der Regeln)

**Interfaces:**
- Consumes: `_stack_inputs` (Task 6), `derive_stacks` (Task 5).

**Das ist der wichtigste Prüfpunkt des ganzen Plans.** Der Prototyp hat mit einer *eigenen*
Implementierung 3 von 4 Events bitidentisch nachgerechnet. Jetzt muss die **echte** Ableitung
dieselben Zahlen liefern. Weicht sie ab, ist der Fehler in Task 1–6 — **nicht** weiterbauen.

**Achtung, Nutzer-Regel:** Niemals in die Produktions-DB schreiben. Das Skript ist rein lesend;
es läuft gegen eine **Kopie** der Prod-DB.

- [ ] **Step 1: Prototyp auf die echte Ableitung umstellen**

**Zuerst die DB-Verbindung entschärfen.** `scripts/kutter_stapel_prototyp.py:20` lautet heute:

```python
conn = sqlite3.connect("/opt/friesenspy/data/friesenspy.db")
```

Das zeigt **hart auf die Originaldatei** und öffnet sie **schreibend** (der Default von
`connect()`). Das Skript liest zwar nur, aber es widerspricht der stehenden Nutzer-Regel im
Ansatz — und ein schreibend geöffnetes WAL-Handle legt `-wal`/`-shm` neben der Prod-DB an.
Ersetze die Zeile durch einen Pfad per Argument und eine **erzwungen lesende** Verbindung:

```python
import sys

# Pfad zur KOPIE als Argument — niemals die Original-Prod-DB.
db_pfad = sys.argv[1] if len(sys.argv) > 1 else "/tmp/friesenspy-kopie.db"
if db_pfad.startswith("/opt/friesenspy/"):
    raise SystemExit("Das ist die Produktions-DB. Bitte eine Kopie angeben.")
# mode=ro erzwingt Lesen auf DB-Ebene — nicht nur per Vorsatz.
conn = sqlite3.connect(f"file:{db_pfad}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
```

Dann ersetze die komplette Funktion `rechne(ev)` durch:

```python
from app.database import _stack_inputs
from app.transport_stacks import derive_stacks, STOLEN, SUNK


def rechne(ev):
    """Jetzt mit der ECHTEN Ableitung statt der Skript-eigenen Kopie."""
    inp = _stack_inputs(conn, ev, ev["dtend"], callsign_prefix="FRS")
    r = derive_stacks(
        manifest=inp["manifest"], events=inp["events"],
        destination=inp["destination"], loading_airports=inp["loading_airports"],
    )
    dest = inp["destination"]
    reihenfolge = [c["name"] for c in inp["manifest"]]
    return (dest, reihenfolge, r["stacks"], r["stacks"][dest],
            r["stacks"][STOLEN], r["stacks"][SUNK])
```

- [ ] **Step 2: Gegen eine Kopie der Prod-DB laufen lassen**

```bash
# DB-Kopie holen (NIE gegen die Original-Datei arbeiten)
# Windows/Git-Bash: KEIN /tmp verwenden (siehe Falle 4 unten). Ein Pfad im Repo-Laufwerk.
scp server:/opt/friesenspy/data/friesenspy.db     "D:/User/Tobias/kutter-kopie.db"
scp server:/opt/friesenspy/data/friesenspy.db-wal "D:/User/Tobias/kutter-kopie.db-wal"  # falls vorhanden
python -m scripts.kutter_stapel_prototyp "D:/User/Tobias/kutter-kopie.db"
```

**Drei Fallen, alle am 16.07. real angetroffen — der Plan war hier zunächst falsch:**

1. **Der Host heißt `server`, nicht `friesenspy`** (`~/.ssh/config`: `server` → 167.86.127.129).
   Ein Host `friesenspy` existiert nicht; der ursprüngliche `scp`-Befehl lief ins Leere.
2. **Die Prod-DB ist live und im WAL-Modus** (43 MB, der Poller schreibt laufend hinein). Die
   `.db`-Datei allein ist ohne ihr `-wal` kein konsistenter Stand — deshalb beide kopieren.
   Sauberer, falls `sqlite3` auf dem Host liegt:
   `sqlite3 'file:/opt/friesenspy/data/friesenspy.db?mode=ro' ".backup '/tmp/friesenspy-kopie.db'"`
3. **Der Zugriff auf den Produktions-Host braucht eine ausdrückliche Freigabe des Nutzers.**
   Die Berechtigungsprüfung lehnt ihn sonst ab — zu Recht. Nicht umgehen: den Nutzer fragen
   oder ihn den Befehl selbst mit `!`-Prefix ausführen lassen.
4. **Git Bash verbiegt Unix-Pfade** (MSYS-Pfadumwandlung). Ein Argument `/tmp/kopie.db` kommt bei
   `python.exe` als `D:/Program Files/Git/tmp/kopie.db` an — am 16.07. gemessen:
   `python -c "import sys; print(repr(sys.argv[1:]))" /opt/friesenspy/x` gibt
   `['D:/Program Files/Git/opt/friesenspy/x']`. Auf dieser Maschine deshalb **Windows-Pfade**
   verwenden (siehe oben), sonst greift die `/opt/friesenspy/`-Sperre im Skript nicht und die
   DB-Kopie landet an einer überraschenden Stelle. Zum Gegentest der Sperre:
   `MSYS_NO_PATHCONV=1 python -m scripts.kutter_stapel_prototyp /opt/friesenspy/data/friesenspy.db`
   → muss „Das ist die Produktions-DB. Bitte eine Kopie angeben." ausgeben (verifiziert 16.07.).
   Die eigentliche Sicherung ist ohnehin `mode=ro` auf DB-Ebene, nicht die Pfad-Sperre.

Expected — **diese drei Zahlen müssen exakt stehen**:

```
#1    FriesenKutter-Test Wangerooge     SUMME  1610 -> 1610   IDENTISCH
#81   Strandkörbe und Sonnenschirme     SUMME  1120 -> 1120   IDENTISCH
#136  Großauftrag für Wooge             SUMME  1090 -> 1090   IDENTISCH
#123  Multi-Kutter-Test                 SUMME   618 ->  417   ABWEICHUNG  (erwartet: die CSV-Zeile)
```

- [ ] **Step 3: Erhaltungssatz auf echten Daten prüfen**

Ergänze am Ende des Skripts:

```python
    summe_stapel = sum(sum(s.values()) for s in stapel.values())
    summe_manifest = sum(float(c.get("target_kg") or 0) for c in cargo)
    print("      Erhaltungssatz: Stapel %.1f == Manifest %.1f  %s" % (
        summe_stapel, summe_manifest,
        "OK" if abs(summe_stapel - summe_manifest) < 0.5 else "<-- GEBROCHEN"))
```

Expected: `OK` für **alle vier** Events (die Ladung ist am Event-Ende überall verteilt).

- [ ] **Step 4: ⏸ Nutzer-Gate**

**Stopp.** Die drei Zahlen dem Nutzer vorlegen. Erst nach seiner Freigabe weiter mit Task 8.
Stimmen sie nicht, ist der Fehler in Task 1–6 — zurück, nicht vorwärts.

- [ ] **Step 5: Commit**

```bash
git add scripts/kutter_stapel_prototyp.py
git commit -m "test(kutter): Prototyp rechnet mit der echten Ableitung — 1610/1120/1090 bestaetigt"
```

---

### Task 8: `compute_transport_progress` liest die Ableitung

**Files:**
- Modify: `app/database.py:5278-5913` (die Funktion wird ersetzt)
- Test: `tests/test_transport.py`

**Interfaces:**
- Consumes: `_stack_inputs` (Task 6), `derive_stacks`/`STOLEN`/`SUNK` (Task 5).
- Produces: **derselbe API-Vertrag wie heute** — `route`, `destination`, `flights[]`, `cargo[]`,
  `total_kg`, `flight_count`, `loaded_count`, `target_kg`, `progress_pct`, `reserved_total_kg`,
  `unmapped_types`, `summary_quip`, `losses[]`, `lost_total_kg`, `participants[]`. Die Signatur
  bleibt unverändert (inkl. `radius_km` und `skip_open_probe`), damit `main.py`/`poller.py` nicht
  angefasst werden müssen.

**Die Übersetzung — jedes Feld hat jetzt eine Quelle im Bestand:**

| API-Feld | kommt aus |
|---|---|
| `cargo[i].delivered_kg` | `stacks[dest][name]` |
| `cargo[i].lost_kg` | `stacks[STOLEN][name] + stacks[SUNK][name]` |
| `cargo[i].reserved_kg` | `Σ onboard[*][name]` — **die Bordladung *ist* die Reservierung** |
| `total_kg` | `Σ stacks[dest].values()` |
| `reserved_total_kg` | `Σ Σ onboard` |
| `lost_total_kg` | `Σ stacks[STOLEN] + Σ stacks[SUNK]` |
| `flights[].tonnage_kg` | Σ der `deliver`-movements dieses Legs |
| `flights[].loss_kind` | `movements` mit `kind ∈ {returned, stolen, sunk}` — **gleiche Namen wie heute** |

**Der Feed-Filter (ersetzt den Streckenfilter):** Ein Leg gehört in den Feed, wenn
`dep ∈ route` **ODER** `arr ∈ route` **ODER** es Ware bewegt hat. Heute verlangt
`database.py:5388` **beides** (`dep not in route_set or arr not in route_set` → skip) — genau
deshalb fiel die Zwischenlandung heraus und der Latch musste den Filter wieder aufheben. Der neue
Filter ist reine **Sichtbarkeit**; was gebucht wird, entscheidet die Ware.

**Sichtbarkeit in `participants` (Entscheidung 14):**
`sichtbar = last_ground[cid] ∈ (loading ∪ {dest})` **ODER** `Σ onboard[cid] > 0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transport.py — neue Klasse ans Dateiende
class TestStapelProgress:
    """compute_transport_progress auf Basis der Stapel-Ableitung — die Fälle, an denen sich das
    Modell entscheidet (S1-S5 aus scripts/kutter_ladung_szenarien.py, hier mit echten Tracks)."""

    def _leg(self, conn, cid, von, nach, t0, *, dauer=20, callsign=None):
        """Ein GPS-erkennbarer Flug von 'von' nach 'nach'. Vorlage: scripts/kutter_ladung_szenarien.leg()"""
        from app.geo import icao_to_coords, airport_elevation_ft
        callsign = callsign or f"FRS{cid:02d}"
        la, lo = icao_to_coords(von)
        ea = airport_elevation_ft(von) or 0
        lb, lb2 = icao_to_coords(nach)
        eb = airport_elevation_ft(nach) or 0
        _add_pos(conn, cid, t0, la, lo, 0, alt=ea, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, 1), la, lo, 70, alt=ea + 250, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, 2), la, lo, 120, alt=ea + 2500, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, dauer // 2), (la + lb) / 2, (lo + lb2) / 2, 130,
                 alt=3000, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, dauer - 1), lb, lb2, 60, alt=eb + 200, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, dauer), lb, lb2, 0, alt=eb, callsign=callsign)
        return _shift(t0, dauer)

    def _milchmann_event(self, conn):
        upsert_payload(conn, "C208", payload_kg=1000)
        conn.commit()
        return _event(conn, route="EDWG,EDWZ,EDXH", destination="EDXH", cargo=[
            {"name": "Fisch", "target_kg": 800, "departure": "EDWG"},
            {"name": "Tee", "target_kg": 500, "departure": "EDWZ"},
        ])

    def test_s2_milchmann_erste_ladung_bleibt_an_bord(self):
        """HEUTE: 0 Fisch + 500 Tee. Der Startplatz des LETZTEN Beins bestimmt die Fracht."""
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        t1 = self._leg(conn, 1, "EDWG", "EDWZ", START)
        t2 = self._leg(conn, 1, "EDWZ", "EDXH", _shift(t1, 10))
        _add_flight(conn, 1, "EDWG", "EDWZ", "C208", START, duration_min=20)
        _add_flight(conn, 1, "EDWZ", "EDXH", "C208", _shift(t1, 10), duration_min=20)

        p = compute_transport_progress(conn, ev, END)

        fisch = next(c for c in p["cargo"] if c["name"] == "Fisch")
        tee = next(c for c in p["cargo"] if c["name"] == "Tee")
        assert fisch["delivered_kg"] == 800.0
        assert tee["delivered_kg"] == 200.0     # 1000 kg Zuladung - 800 Fisch
        assert p["total_kg"] == 1000.0

    def test_s3_zwischenlandung_fremd_liefert_die_echte_ladung(self):
        """HEUTE: ohne Latch 0 kg, mit Latch 1000 kg (Tee, der nie an Bord war)."""
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        t1 = self._leg(conn, 1, "EDWG", "EDDW", START)
        t2 = self._leg(conn, 1, "EDDW", "EDXH", _shift(t1, 10))
        _add_flight(conn, 1, "EDWG", "EDDW", "C208", START, duration_min=20)
        _add_flight(conn, 1, "EDDW", "EDXH", "C208", _shift(t1, 10), duration_min=20)

        p = compute_transport_progress(conn, ev, END)

        assert p["total_kg"] == 800.0           # nur der Fisch, der wirklich an Bord war
        tee = next(c for c in p["cargo"] if c["name"] == "Tee")
        assert tee["delivered_kg"] == 0.0

    def test_s4_logout_am_zweiten_ladeplatz_legt_die_ware_dorthin(self):
        """HEUTE: 'returned' -> zurück in den EDWG-Topf. Die Ware liegt aber in EDWZ."""
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        t1 = self._leg(conn, 1, "EDWG", "EDWZ", START)
        _add_flight(conn, 1, "EDWG", "EDWZ", "C208", START, duration_min=20)

        p = compute_transport_progress(conn, ev, END)

        assert p["total_kg"] == 0.0
        loss = next((f for f in p["flights"] if f.get("loss_kind")), None)
        assert loss is not None and loss["loss_kind"] == "returned"
        assert p["lost_total_kg"] == 0.0        # zurückgebracht ist kein Verlust

    def test_die_bordladung_ist_die_reservierung(self):
        """Die Reservierung ist kein eigener Mechanismus mehr: wer lädt, nimmt vom Stapel."""
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        _add_open_flight(conn, 61, "EDWG", "EDXH", "C208", START)
        lat, lon = icao_to_coords("EDWG")
        _set_live_pos(conn, 61, lat, lon, 0)

        p = compute_transport_progress(conn, ev, _shift(START, 5))

        assert p["reserved_total_kg"] == 800.0   # er hat den EDWG-Stapel an Bord
        fisch = next(c for c in p["cargo"] if c["name"] == "Fisch")
        assert fisch["reserved_kg"] == 800.0
        assert fisch["delivered_kg"] == 0.0

    def test_der_erhaltungssatz_gilt_auch_im_api_vertrag(self):
        """geliefert + verloren + reserviert + Rest == Manifest. Der Balken kann nicht lügen."""
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        t1 = self._leg(conn, 1, "EDWG", "EDDW", START)
        _add_flight(conn, 1, "EDWG", "EDDW", "C208", START, duration_min=20)

        p = compute_transport_progress(conn, ev, END)

        assert p["total_kg"] + p["lost_total_kg"] == 800.0   # gestohlen in EDDW
        assert p["lost_total_kg"] == 800.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport.py::TestStapelProgress -v`
Expected: FAIL — `assert 500.0 == 800.0` in `test_s2_milchmann_...` (der alte Kern rät die Fracht
aus dem Startplatz des letzten Beins: 0 Fisch + 500 Tee)

- [ ] **Step 3: Write minimal implementation**

Ersetze `compute_transport_progress` (`database.py:5278-5913`) vollständig:

```python
def compute_transport_progress(
    conn: sqlite3.Connection,
    event: dict,
    now: str,
    *,
    callsign_prefix: str = "FRS",
    radius_km: float | None = None,
    skip_open_probe: bool = False,
) -> dict:
    """Live-Fortschritt eines FriesenKutter-Events — Stapel-Modell (Spec 2026-07-15).

    Ladung ist ein BESTAND mit einem Ort, kein Attribut eines Flugbeins: Das Manifest liegt als
    Stapel an seinen Ladeplätzen; wer am Boden an einem Ladeplatz steht, lädt; wer am Ziel
    landet, liefert; wer ausloggt, gibt zurück / bestiehlt / versenkt. Die Regeln stehen
    vollständig in :mod:`app.transport_stacks`, die DB-Uebersetzung in :func:`_stack_inputs` —
    diese Funktion formt nur noch das Ergebnis in den API-Vertrag.

    **Erhaltungssatz:** Summe Stapel + Summe Ladung == Summe Manifest. Ware entsteht nicht und
    verschwindet nicht; ``total_kg`` kann den Balken daher nicht überzeichnen (#63).

    ``radius_km`` und ``skip_open_probe`` werden nur noch für die Signatur-Verträglichkeit
    angenommen und **ignoriert**:

    * ``radius_km`` — der Anwesenheitsradius ist seit #23 global (``_BUMMEL_AIRPORT_RADIUS_KM``).
    * ``skip_open_probe`` (#66) hatte zwei Gründe, beide entfallen. (1) Kosten: Es sparte den
      ZWEITEN ``canonicalize_legs``-Aufruf — hier läuft nur einer. (2) Richtigkeit: Es verhinderte,
      dass der Freeze eine ``in_air``-Zeile für immer als "unterwegs" einfriert. Das kann nicht
      mehr passieren, weil das Modell es selbst ausschließt: Eingefroren wird erst, wenn niemand
      mehr Ware trägt (Entscheidung 10, :func:`transport_anyone_in_progress`) — und eine
      ``in_air``-Zeile entsteht nur MIT Ware an Bord. Es gibt also nichts wegzufiltern.

    (Ein Filter wäre hier sogar schädlich gewesen: pro CID statt pro Session gefiltert, hätte
    er dem Piloten, der eben geliefert hat und noch online am Ziel parkt, seine ganze Tonnage aus
    dem Snapshot gelöscht — Fable-Review 16.07.)
    """
    inp = _stack_inputs(conn, event, now, callsign_prefix=callsign_prefix)
    manifest, dest = inp["manifest"], inp["destination"]
    route_set = {c for c in (normalize_type_code(x) for x in (event.get("route") or "").split(",")) if c}
    payload_map = get_payload_map(conn)
    default_kg = transport_default_payload_kg(conn)
    if not dest:
        # Ohne Ziel gibt es keinen Ziel-Stapel — und eine Landung mit unerkanntem Platz
        # (airport=None) würde sonst `airport == destination` erfüllen und ins Nichts liefern.
        return _empty_transport_progress(event, route_set, manifest)

    r = derive_stacks(manifest=manifest, events=inp["events"], destination=dest,
                      loading_airports=inp["loading_airports"])
    stacks, onboard = r["stacks"], r["onboard"]

    # --- Bewegungen je Leg/Session zuordnen (Feed) ---
    delivered_by: dict[tuple[int, str], list[dict]] = {}
    loss_by: dict[tuple[int, str], list[dict]] = {}
    for m in r["movements"]:
        key = (m["cid"], m["ts"])
        if m["kind"] == "deliver":
            delivered_by.setdefault(key, []).append(m)
        elif m["kind"] in ("returned", "stolen", "sunk"):
            loss_by.setdefault(key, []).append(m)

    emoji_of = {c["name"]: c.get("emoji") for c in manifest}

    def _lines(ms: list[dict]) -> list[dict]:
        agg: dict[str, float] = {}
        for m in ms:
            agg[m["name"]] = agg.get(m["name"], 0.0) + m["kg"]
        return [{"name": n, "emoji": emoji_of.get(n), "kg": round(kg, 1)}
                for n, kg in sorted(agg.items(), key=lambda kv: kv[1], reverse=True)]

    names = {}
    cids = {int(s["cid"]) for s in inp["sessions"]}
    if cids:
        rows = conn.execute(
            "SELECT cid, name FROM pilots WHERE cid IN (%s)" % ",".join("?" * len(cids)),
            list(cids),
        ).fetchall()
        names = {r["cid"]: (r["name"] or "") for r in rows}

    unmapped: set[str] = set()
    network: list[dict] = []
    for s in inp["sessions"]:
        cid = int(s["cid"])
        type_code = normalize_type_code(s.get("aircraft_icao")) or normalize_type_code(s.get("aircraft"))
        if type_code and type_code not in payload_map:
            unmapped.add(type_code)
        cap = round(payload_map.get(type_code, default_kg), 1)
        own = [g for g in inp["legs_by_cid"].get(cid, [])
               if (g.get("logon_time") or "") >= (s.get("logon_time") or "")
               and (not s.get("logoff_time") or (g.get("logon_time") or "") <= s["logoff_time"])]

        for g in own:
            dep = normalize_type_code(g.get("gps_departure"))
            arr = normalize_type_code(g.get("gps_arrival"))
            dl = delivered_by.get((cid, g.get("logoff_time") or ""), [])
            tonnage = round(sum(m["kg"] for m in dl), 1)
            # Feed-Filter = reine SICHTBARKEIT (ersetzt den alten Streckenfilter, der BEIDE
            # Enden auf der Route verlangte und deshalb vom Latch aufgehoben werden musste).
            if not (dep in route_set or arr in route_set or tonnage > 0):
                continue
            row = {
                "dep_time": g.get("logon_time") or "", "cid": cid,
                "callsign": g.get("callsign") or s.get("callsign") or "",
                "name": names.get(cid, ""), "aircraft": s.get("aircraft") or type_code,
                "dep": dep, "arr": arr,
                "tonnage_kg": tonnage, "onboard_kg": tonnage,
                "loaded": tonnage > 0.0,
                "cargo_lines": _lines(dl), "cargo_name": _lines(dl)[0]["name"] if dl else None,
                "in_air": False, "airborne": False,
                "reserved_kg": 0.0, "onboard_reserved_kg": 0.0,
                "flight_key": f"{cid}:{g.get('logon_time') or ''}",
                "distance_nm": g.get("distance_nm") or 0,
                "block_min": g.get("block_min") or g.get("duration_min") or 0,
            }
            network.append(row)

        # Verlust-Zeile (Logout mit Ware an Bord). Sie gehört an das LETZTE Leg DIESER Session —
        # `next(reversed(network) if cid == …)` wäre falsch: es fischt quer über Sessions und
        # könnte eine bereits mit einem Verlust behaftete Zeile überschreiben (aus zwei
        # Rückgaben würde eine, Fable-Review 16.07.).
        ls = loss_by.get((cid, s.get("logoff_time") or ""), [])
        if ls:
            kind = ls[0]["kind"]
            lost = round(sum(m["kg"] for m in ls), 1) if kind in ("stolen", "sunk") else 0.0
            own_keys = {f"{cid}:{g.get('logon_time') or ''}" for g in own}
            target = next((q for q in reversed(network)
                           if q["flight_key"] in own_keys and not q["loaded"]
                           and not q.get("loss_kind")), None)
            if target is not None:
                target["loss_kind"], target["lost_kg"] = kind, lost
                target["cargo_lines"] = _lines(ls)
                target["cargo_name"] = target["cargo_lines"][0]["name"]
            else:
                network.append({
                    "dep_time": s.get("logon_time") or "", "cid": cid,
                    "callsign": s.get("callsign") or "", "name": names.get(cid, ""),
                    "aircraft": s.get("aircraft") or type_code,
                    "dep": "", "arr": ls[0].get("airport") or "—",
                    "tonnage_kg": 0.0, "loaded": False, "in_air": False, "airborne": False,
                    "reserved_kg": 0.0, "cargo_lines": _lines(ls),
                    "cargo_name": _lines(ls)[0]["name"],
                    "flight_key": f"{cid}:{s.get('logon_time') or ''}",
                    "distance_nm": 0, "block_min": 0, "loss_kind": kind, "lost_kg": lost,
                })

        # Offene Session mit Ware an Bord: die Bordladung IST die Reservierung.
        load = onboard.get(cid) or {}
        aboard = round(sum(load.values()), 1)
        if not s.get("logoff_time") and aboard > 0.0:
            where = r["position"].get(cid)
            network.append({
                "dep_time": s.get("logon_time") or "", "cid": cid,
                "callsign": s.get("callsign") or "", "name": names.get(cid, ""),
                "aircraft": s.get("aircraft") or type_code,
                "dep": where or "", "arr": dest,
                "tonnage_kg": 0.0, "loaded": False,
                "in_air": True, "airborne": where is None,
                "reserved_kg": aboard, "onboard_reserved_kg": cap,
                "cargo_lines": [{"name": n, "emoji": emoji_of.get(n), "kg": round(kg, 1)}
                                for n, kg in load.items() if kg > 0.01],
                "cargo_name": max(load, key=load.get) if aboard > 0 else None,
                "flight_key": f"{cid}:{s.get('logon_time') or ''}",
                "distance_nm": 0, "block_min": 0,
            })

    quips = get_transport_quips(conn, int(event["id"]))
    for q in network:
        q["quip"] = quips.get(q["flight_key"])

    # --- Zahlen: direkt aus den Stapeln ---
    cargo_out: list[dict] = []
    for c in manifest:
        n = c["name"]
        delivered = stacks[dest].get(n, 0.0)
        lost = stacks[STOLEN].get(n, 0.0) + stacks[SUNK].get(n, 0.0)
        reserved = sum(l.get(n, 0.0) for l in onboard.values())
        cargo_out.append({
            "name": n, "emoji": c.get("emoji"), "target_kg": c["target_kg"],
            "delivered_kg": round(delivered, 1), "reserved_kg": round(reserved, 1),
            "lost_kg": round(lost, 1),
            "pct": round(100.0 * delivered / c["target_kg"], 1) if c["target_kg"] > 0 else 0.0,
            "per_flight_max_kg": c.get("per_flight_max_kg"),
            "departure": c.get("departure"),
        })

    total_kg = round(sum(stacks[dest].values()), 1)
    lost_total = round(sum(stacks[STOLEN].values()) + sum(stacks[SUNK].values()), 1)
    reserved_total = round(sum(sum(l.values()) for l in onboard.values()), 1)
    target_kg = round(sum(c["target_kg"] for c in manifest), 1) if manifest else None

    # --- Teilnehmer + Sichtbarkeit (Entscheidung 14) ---
    # WICHTIG: parts entsteht aus den SESSIONS, nicht aus dem Feed. Ein Pilot ohne Feed-Zeile ist
    # trotzdem Teilnehmer — der Wartende am leeren Stapel (Entscheidung 13) und der Pilot, der
    # leer am Ziel parkt (Spec-Statustabelle: `🅿️ steht in EDXH · 0 kg`), haben beide kein Leg
    # und keine Ladung. Aus dem Feed gebaut wären sie unsichtbar, obwohl die Sichtbarkeits-
    # formel sie einschließt (Fable-Review 16.07.).
    visible_places = set(inp["loading_airports"]) | {dest}
    parts: dict[int, dict] = {}
    for s in inp["sessions"]:
        cid = int(s["cid"])
        parts.setdefault(cid, {
            "cid": cid, "name": names.get(cid, ""), "callsign": s.get("callsign") or "",
            "aircraft": normalize_type_code(s.get("aircraft") or s.get("aircraft_icao") or ""),
            "flights": 0, "delivered_kg": 0.0, "reserved_kg": 0.0, "lost_kg": 0.0,
            "status": "done",
        })
    for q in network:
        p = parts.setdefault(int(q["cid"]), {
            "cid": int(q["cid"]), "name": q.get("name") or "", "callsign": q.get("callsign") or "",
            "aircraft": normalize_type_code(q.get("aircraft") or ""), "flights": 0,
            "delivered_kg": 0.0, "reserved_kg": 0.0, "lost_kg": 0.0, "status": "done",
        })
        p["flights"] += 1
        p["delivered_kg"] += q["tonnage_kg"]
        p["lost_kg"] += q.get("lost_kg") or 0.0
        # reserved_kg NICHT hier aufsummieren — es kommt unten direkt aus der Bordladung
        # (eine Wahrheit, nicht zwei: die Feed-Zeile ist nur eine Sicht auf denselben Stapel).
    for cid, p in parts.items():
        load = onboard.get(cid) or {}
        aboard = sum(load.values())
        where = r["position"].get(cid)
        # sichtbar = letzter Bodenkontakt an einem teilnehmenden Platz ODER Ladung > 0
        # (Entscheidung 14). Kostet kein Feld: beide Werte führt das Modell ohnehin — die
        # Ladung IST der Flieger-Stapel, der letzte Bodenkontakt IST der Logout-Ort.
        p["visible"] = (r["last_ground"].get(cid) in visible_places) or aboard > 0.01
        p["place"] = where          # None = unterwegs; sonst das ICAO, an dem er steht
        # Der Status ist eine grobe Kategorie für die API; die ANZEIGE leitet das Frontend aus
        # place + reserved_kg ab (Ort x Ladung, Spec). Werte ehrlich statt `arrived`/`returning`:
        if aboard > 0.01:
            p["status"] = "flying" if where is None else "loaded"
        elif where is None:
            p["status"] = "dabei"                       # leer in der Luft — macht noch mit
        elif where in inp["loading_airports"]:
            p["status"] = "loading"                     # steht am Stapel
        else:
            p["status"] = "standing"                    # Ziel oder fremder Platz
        # Was er trägt — der Live-Block zeigt es je Pilot (index.html, fetchKutterActive).
        p["cargo_lines"] = [{"name": n, "emoji": emoji_of.get(n), "kg": round(kg, 1)}
                            for n, kg in load.items() if kg > 0.01]
        p["reserved_kg"] = round(aboard, 1)   # die Bordladung IST die Reservierung
        for k in ("delivered_kg", "lost_kg"):
            p[k] = round(p[k], 1)

    return {
        "route": sorted(route_set),
        "destination": dest,
        "flights": sorted(network, key=lambda x: x["dep_time"], reverse=True),
        "cargo": cargo_out,
        "total_kg": total_kg,
        "flight_count": len(network),
        "loaded_count": sum(1 for q in network if q["loaded"]),
        "target_kg": target_kg,
        "progress_pct": round(100.0 * total_kg / target_kg, 1) if target_kg else None,
        "reserved_total_kg": reserved_total,
        "unmapped_types": sorted(unmapped),
        "summary_quip": event.get("summary_quip"),
        "losses": [q for q in network if q.get("loss_kind")],
        "lost_total_kg": lost_total,
        "participants": sorted(parts.values(), key=lambda x: (-x["delivered_kg"], x["name"])),
    }
```

Und der Helfer fuer den fehlenden `dest` (Fable-Review K3 — der Altcode schuetzte alles mit
`bool(dest)`; ohne Guard wuerde eine Landung mit unerkanntem Platz (`airport=None`) die Bedingung
`airport == destination` erfuellen und ins Nichts liefern):

```python
def _empty_transport_progress(event: dict, route_set: set[str], manifest: list[dict]) -> dict:
    """Leerer Fortschritt für ein Event ohne Ziel — es kann keine Lieferung geben."""
    return {
        "route": sorted(route_set), "destination": None, "flights": [],
        "cargo": [{"name": c["name"], "emoji": c.get("emoji"), "target_kg": c["target_kg"],
                   "delivered_kg": 0.0, "reserved_kg": 0.0, "lost_kg": 0.0, "pct": 0.0,
                   "per_flight_max_kg": c.get("per_flight_max_kg"),
                   "departure": c.get("departure")} for c in manifest],
        "total_kg": 0.0, "flight_count": 0, "loaded_count": 0,
        "target_kg": round(sum(c["target_kg"] for c in manifest), 1) if manifest else None,
        "progress_pct": None, "reserved_total_kg": 0.0, "unmapped_types": [],
        "summary_quip": event.get("summary_quip"), "losses": [], "lost_total_kg": 0.0,
        "participants": [],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_transport.py::TestStapelProgress -v`
Expected: PASS (5 passed)

Run: `pytest tests/ -q`
Expected: **viele Fehler** in `tests/test_transport.py` — das ist erwartet und der Gegenstand von
Task 9/10. Die Latch-Tests testen entfallene Bausteine. **Wichtig:** Es dürfen **keine** Fehler
außerhalb von `tests/test_transport.py` auftreten. Passiert das doch, ist der API-Vertrag verletzt
— zurück in Step 3.

- [ ] **Step 5: Commit**

```bash
git add app/database.py tests/test_transport.py
git commit -m "feat(kutter): compute_transport_progress rechnet mit Stapeln statt zu raten"
```

---

### Task 9: Der Latch-Rückbau

**Files:**
- Modify: `app/database.py` — **ersatzlos löschen**: `set_transport_live_arrival` (4928-4936),
  `get_transport_live_arrivals` (4939-4951), `record_transport_loss` (4954-4962),
  `get_transport_losses` (4965-4971), `_LATCH_SLACK_SEC` (4974-4978), `_latch_hits_flight`
  (4981-5021), `detect_transport_losses` (5038-5140), `check_live_arrival` (5193-5240),
  `active_transport_destinations` (5143-5151), `open_transport_flights` (5154-5161),
  `_returning_pilot_landed` (5164-5176). **Umbauen**: `transport_anyone_in_progress` (5241-5275).
- Modify: `app/poller.py` — Importe Z. 44/45, der Block Z. 858-873, der Kommentar Z. 561,
  Import + Aufruf von `detect_transport_losses` (Z. 1243/1299)
- Modify: `tests/test_transport.py`, `tests/test_poller.py`, `scripts/kutter_ladung_szenarien.py`
  — löschen/umbauen (Listen unten)

**Interfaces:**
- `transport_anyone_in_progress(conn, event, *, started_before=None, callsign_prefix="FRS",
  radius_km=None) -> bool` — Signatur bleibt, Bedeutung wird ehrlich: **trägt noch jemand Ware?**
- `detect_transport_losses(conn, event, *, callsign_prefix="FRS") -> int` — Signatur bleibt.

**`transport_anyone_in_progress` (Entscheidung 10):** Das Event endet erst, wenn `Σ onboard == 0`.
Die Streckenprüfung entfällt — sie war ein *Proxy* für „trägt vermutlich noch Ware", der beste, den
ein Modell ohne Ladungsbegriff hatte. **Verhaltensänderung (gewollt):** Ein leerer Pilot hält den
Feierabend nicht mehr auf; ein beladener sehr wohl, auch über `dtend` hinaus.

**`detect_transport_losses` entfällt ERSATZLOS — samt `record_transport_loss`,
`get_transport_losses` und dem Schreiben in `transport_cargo_losses`.**

Die Spec ließ offen, ob die Funktion „als Latch für den Push" bleiben muss. **Sie muss nicht — den
Push gibt es nicht** (Fable-Review 16.07., am Code verifiziert):

- `poller.py:1299` ruft sie auf und **wirft den Rückgabewert weg**; im ganzen Repo existiert kein
  Verlust-Push.
- Einziger Leser von `get_transport_losses` ist `compute_transport_progress:5581` — also genau die
  Funktion, die Task 8 ersetzt — plus die Funktion selbst (Idempotenz-Check, `:5065`).

Bliebe sie stehen, schriebe sie in eine Tabelle, die **niemand mehr liest**: zwei
Klassifikations-Wahrheiten ohne Konsumenten — exakt die Doppelbuchhaltung, die dieser Umbau abbaut.
Die Verluste stehen jetzt in `movements` und fließen über `losses[]`/`lost_total_kg` in denselben
API-Vertrag wie bisher.

Damit entfällt auch ihre eigene Positions-Klassifikation (`nearest_airport` mit
`_LANDED_MAX_GS_KT` = 40, **ohne AGL-Guard**) — das löst zugleich **A10** (Großplatz > 4 km vom ARP
→ fälschlich „sunk").

`transport_cargo_losses` wird **nicht gedroppt** (Altdaten, stört nicht), nur nicht mehr
geschrieben und nicht mehr gelesen.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transport.py — in TestStapelProgress ergänzen
def test_ein_leerer_pilot_haelt_den_feierabend_nicht_auf(self):
    """Entscheidung 10: Es zählt nur, ob jemand Ware trägt — nicht 'offener Flug auf der Strecke'."""
    from app.database import transport_anyone_in_progress
    from app.geo import icao_to_coords
    conn = _make_conn()
    ev = self._milchmann_event(conn)
    # Der Stapel ist leer: ein anderer hat alles geholt und geliefert.
    t1 = self._leg(conn, 1, "EDWG", "EDXH", START)
    _add_flight(conn, 1, "EDWG", "EDXH", "C208", START, duration_min=20)
    t2 = self._leg(conn, 2, "EDWZ", "EDXH", START)
    _add_flight(conn, 2, "EDWZ", "EDXH", "C208", START, duration_min=20)
    # Jetzt loggt ein Dritter am (leeren) EDWG ein und steht dort:
    _add_open_flight(conn, 3, "EDWG", "EDXH", "C208", _shift(START, 60))
    lat, lon = icao_to_coords("EDWG")
    _set_live_pos(conn, 3, lat, lon, 0)

    assert transport_anyone_in_progress(conn, ev, started_before=END) is False

def test_ein_beladener_pilot_haelt_den_feierabend_auf(self):
    from app.database import transport_anyone_in_progress
    from app.geo import icao_to_coords
    conn = _make_conn()
    ev = self._milchmann_event(conn)
    _add_open_flight(conn, 3, "EDWG", "EDXH", "C208", START)
    lat, lon = icao_to_coords("EDWG")
    _set_live_pos(conn, 3, lat, lon, 0)      # steht am vollen Stapel -> lädt 800 Fisch

    assert transport_anyone_in_progress(conn, ev, started_before=END) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport.py::TestStapelProgress::test_ein_leerer_pilot_haelt_den_feierabend_nicht_auf -v`
Expected: FAIL — `assert True is False` (heute zählt „offener Flug, Start auf der Strecke")

- [ ] **Step 3: Write minimal implementation**

Ersetze `transport_anyone_in_progress` (`database.py:5241-5275`):

```python
def transport_anyone_in_progress(
    conn: sqlite3.Connection,
    event: dict,
    *,
    started_before: str | None = None,
    callsign_prefix: str = "FRS",
    radius_km: float | None = None,
) -> bool:
    """True, wenn noch jemand Ware dieses Events trägt — dann muss der Feierabend warten.

    Entscheidung 10 (Spec): Das Event endet erst, wenn alle Ware einen End-Stapel gefunden hat
    (geliefert, zurück, gestohlen, versenkt). Formal ``Summe Flieger-Stapel == 0``.

    Damit entfällt die frühere Streckenprüfung ("gibt es einen offenen Flug, der auf der
    Strecke gestartet ist?") — sie war ein PROXY für "trägt vermutlich noch Ware", der beste,
    den ein Modell ohne Ladungsbegriff hatte. Ein LEERER Pilot hält jetzt nichts mehr auf; ein
    beladener sehr wohl, auch über ``dtend`` hinaus (dann wartet das Event auf seine Ware).

    ``started_before``/``radius_km`` bleiben für die Signatur-Verträglichkeit erhalten und
    werden nicht mehr ausgewertet: Wer Ware trägt, zählt — unabhängig davon, wann er einloggte.
    """
    inp = _stack_inputs(conn, event, _now_utc(), callsign_prefix=callsign_prefix)
    if not inp["destination"]:
        return False
    r = derive_stacks(manifest=inp["manifest"], events=inp["events"],
                      destination=inp["destination"], loading_airports=inp["loading_airports"])
    return any(sum(load.values()) > 0.01 for load in r["onboard"].values())
```

Am Dateikopf von `database.py` den Import ergänzen:

```python
from app.transport_stacks import derive_stacks, STOLEN, SUNK
```

Dann **löschen** (in dieser Reihenfolge, damit der Import-Check greift):

```bash
# app/database.py — diese Bloecke ersatzlos entfernen:
#   set_transport_live_arrival     (4928-4936)
#   get_transport_live_arrivals    (4939-4951)
#   _LATCH_SLACK_SEC + Kommentar   (4974-4978)
#   _latch_hits_flight             (4981-5021)
#   check_live_arrival             (5193-5240)
```

`app/poller.py`: Zeile 45 (`check_live_arrival,`) aus dem Import entfernen und den Block
`poller.py:858-873` (Abschnitt „2c. Live-Ankunft prüfen") ersatzlos löschen — die Landung am Ziel
erkennt der Detektor selbst, sofort beim Touchdown.

**Ersatzlos löschen** (die Verluste stehen jetzt in `movements`, s. o.):

```bash
# app/database.py — diese Bloecke ebenfalls ersatzlos entfernen:
#   record_transport_loss          (4954-4962)
#   get_transport_losses           (4965-4971)
#   detect_transport_losses        (5038-5140)
```

`app/poller.py`: `detect_transport_losses` aus dem Import (Z. 1243) und den Aufruf (Z. 1299) samt
seiner `if ev.get("destination"):`-Zeile entfernen.

**Verwaiste Bausteine, die dabei mit abfallen** (Fable-Review — sonst bleibt tote API stehen):

- `active_transport_destinations` (`database.py:5143`) — verliert mit dem gelöschten Poller-Block
  seinen letzten Aufrufer; auch der Import `poller.py:44` und der Kommentar `poller.py:561`
  („Live-Ankunft (FriesenKutter) → check_live_arrival je Pilot") gehen.
- `open_transport_flights` (`database.py:5154`) und `_returning_pilot_landed` (`:5164`) — ihr
  letzter Produktions-Aufrufer war der Offen-Zweig der alten `compute_transport_progress`. Prüfen
  und mit ihren Tests entfernen (`tests/test_transport.py:612-624`).

- [ ] **Step 4: Die entfallenen Tests entfernen und die Latch-Fixtures umbauen**

**Ersatzlos löschen** (testen entfallene Bausteine):

| Klasse / Test | Zeile |
|---|---|
| `TestLiveArrivalLatch` (3 Tests) | 578-626 |
| `TestCheckLiveArrival` (5 Tests) | 666-714 |
| `TestLatchHitsFlight` (9 Tests) | 716-762 |
| `test_check_live_arrival_uses_global_radius_regardless_of_event_radius` | 951 |
| `test_latch_persists_after_disconnect_without_known_arrival` | 814 (Entscheidung 8: Lieferung ohne jede Position ist bewusst nicht mehr möglich) |

**Den Helper `_add_delivered_flight` (104-116) auf einen echten GPS-Track umbauen** — er ist die
Wurzel von 15 Aufrufen in 12 Tests:

```python
def _add_delivered_flight(conn, cid, dep, aircraft, logon, ev_id, *, duration_min=30, callsign=None,
                          latch_offset_min=5, destination="EDXH"):
    """Eine tatsächlich am Ziel angekommene Fracht-Lieferung — jetzt mit echtem GPS-Track.

    Früher: Connection + Live-Ankunfts-Latch (der Latch WAR der Nachweis). Der Latch ist weg;
    die Lieferung ist genau dann eine, wenn der Detektor die Landung am Ziel sieht. ``ev_id`` und
    ``latch_offset_min`` bleiben für die Aufrufer-Verträglichkeit erhalten und werden ignoriert.
    """
    from app.geo import icao_to_coords, airport_elevation_ft
    callsign = callsign or f"FRS{cid:02d}"
    dlat, dlon = icao_to_coords(dep)
    delev = airport_elevation_ft(dep) or 0
    alat, alon = icao_to_coords(destination)
    aelev = airport_elevation_ft(destination) or 0
    _add_flight(conn, cid, dep, destination, aircraft, logon, duration_min=duration_min,
                callsign=callsign)
    _add_pos(conn, cid, logon, dlat, dlon, 0, alt=delev, callsign=callsign)
    _add_pos(conn, cid, _shift(logon, 2), dlat, dlon, 80, alt=delev + 1200, callsign=callsign)
    _add_pos(conn, cid, _shift(logon, duration_min // 2), (dlat + alat) / 2, (dlon + alon) / 2,
             120, alt=4000, callsign=callsign)
    _add_pos(conn, cid, _shift(logon, duration_min - 2), alat, alon, 60, alt=aelev + 400,
             callsign=callsign)
    _add_pos(conn, cid, _shift(logon, duration_min), alat, alon, 0, alt=aelev, callsign=callsign)
    conn.commit()
```

**Anzupassen** (echte Verhaltensänderung, kein reiner Testumbau — jeweils prüfen, nicht blind
umschreiben):

| Test | Zeile | Was sich ändert |
|---|---|---|
| `test_latched_flight_does_not_delay` | 880 | Kriterium ist jetzt „trägt Ware" |
| `test_open_flight_from_route_counts_as_in_progress` | 873 | leerer Pilot verzögert nicht mehr |
| `test_arrived_status_with_latch` | 2133 | `arrived` entfällt |
| `test_returning_pilot_still_shown_while_still_airborne` | 2118 | `returning` → `dabei`, bleibt sichtbar |
| `test_statuses_and_sums` | 2068 | Status-Werte neu |
| `TestReservation` (10 Tests) | 975-1130 | Reservierung = Bordladung |
| `TestGPSLegReconcile` (11 Tests) | 1663-2064 | Latch-Reconcile/`arrived`-Demotion — Bug-Klasse entfällt |
| `TestCargoLosses` (16 Tests) | 1342-1662 | Latch-Kopplung + entfallende Positions-Eigenprüfung |
| `TestCoLoadPerDeparture.test_latch_fallback_unknown_dep_fills_all` | 1218 | Der Fallback entfällt (S3b: erzeugte Ware) |
| `TestGroundLoading` (5 Tests) | 2717-2780 | „lädt" beansprucht jetzt echte Stapelware |
| `TestCargoLosses` (16 Tests) | 1342-1662 | `detect_transport_losses` ist weg — die Verluste kommen jetzt aus `compute_transport_progress` (`losses[]`). Die Fälle bleiben gültig, nur der Prüfpfad ändert sich. |

**`tests/test_poller.py` NICHT vergessen** (Fable-Review — stand nicht in meiner ersten Liste und
hätte „alle grün" unerreichbar gemacht):

| Stelle | Was |
|---|---|
| `tests/test_poller.py:509-635` | Latch-Integrationstest, importiert `get_transport_live_arrivals` + `compute_transport_progress` |
| `tests/test_poller.py:2195-2236` | nutzt `get_transport_live_arrivals` |

**`scripts/kutter_ladung_szenarien.py` bricht beim Import** (Z. 37, 177, 186:
`set_transport_live_arrival`) — ausgerechnet das Skript, das dieser Plan als Vorlage und S8-Beleg
zitiert. Die Latch-Szenarien S2b/S3b entfallen (sie zeigten den Fehler, den es nicht mehr gibt);
S1–S5 und S8 bleiben und müssen weiter laufen.

Run: `pytest tests/ -q && python -m scripts.kutter_ladung_szenarien`
Expected: **alle grün**, und die Szenarien zeigen S2 = 800 Fisch + 200 Tee, S3 = 800 Fisch,
S4 = Ware liegt in EDWZ, S8 = versenkt. Erst dann ist Task 9 fertig.

- [ ] **Step 5: Commit**

```bash
git add app/database.py app/poller.py tests/test_transport.py
git commit -m "refactor(kutter): Latch-Rueckbau — der Detektor kennt die Landung selbst"
```

---

### Task 10: Das Frontend — zwei Zeichen, vier Wörter

**Files:**
- Modify: `app/static/index.html` — `fetchKutterActive` (3271-3339), `_kCargoLabel` (4853-4878),
  `_kutterDetailBody` (5007-5027)
- Test: manuell (Vanilla-JS-SPA, keine JS-Tests im Projekt)

**`app/static/admin.html` ist NICHT betroffen** — es liest keines der Progress-Felder, nur die
Admin-CRUD-Endpoints (anderes Schema). Geprüft, nicht angenommen.

**Der Status (Spec „Der Live-Status = Ort × Ladung"):**

| Ort | An Bord | Anzeige |
|---|---|---|
| Boden, Ladeplatz | egal | `🅿️ lädt in EDWG · 800 kg` |
| Boden, Ziel | 0 kg | `🅿️ steht in EDXH · 0 kg` |
| Boden, fremder Platz | > 0 kg | `🅿️ steht in EDDW · 800 kg` |
| Boden, fremder Platz | 0 kg | nicht in der Liste |
| Luft | > 0 kg | `✈️ unterwegs · 800 kg` |
| Luft | 0 kg, letzter Platz teilnehmend | `✈️ dabei` |
| Luft | 0 kg, letzter Platz fremd | nicht in der Liste |

**🅿️ heißt parken** (am Boden, egal wo), **✈️** heißt in der Luft — exakt die Trennung, die
`index.html:5017` heute schon macht (`f.airborne ? ' ✈️' : ' 🅿️'`). Die Bedeutung trägt das
**Wort**: *lädt* (dort liegt ein Stapel) · *steht* (hier gibt es nichts zu holen) · *unterwegs*
(trägt Ware) · *dabei* (fliegt leer). Am Boden steht **immer** eine Menge — ob dieser Pilot beladen
ist, sieht man ihm sonst nicht an. `✈️ dabei` braucht keine: Es *bedeutet* leer.

**`✅ angekommen` entfällt ersatzlos** (im sauberen Pfad ~0 s sichtbar; 14 von 22 Latches fielen ins
selbe `gs<2`-Sample wie die Leg-Schließung). Eine Lieferung ist eine Tatsache im Balken, kein
Zustand. **`↩️ Rückflug` → `✈️ dabei`** — der Name war eine Unterstellung über die Richtung; die
Funktion („man sieht, wer noch mitmacht") bleibt.

**`_kLossLabel` (4880-4884) bleibt unverändert** — `returned`/`stolen`/`sunk` heißen im
Stapel-Modell genauso.

- [ ] **Step 1: Den Live-Block auf `participants` umstellen**

Ersetze in `fetchKutterActive` (index.html, Zeilen 3290-3311) die Schleifen über `d.flights` **und**
`d.participants` durch eine einzige über `d.participants`:

```javascript
    // Aktive Piloten: das Modell sagt, wer sichtbar ist (Entscheidung 14 — letzter Bodenkontakt
    // an einem teilnehmenden Platz ODER Ladung an Bord). Kein Ziel unterstellt (#23).
    const active = [];
    (d.participants || []).forEach(p => {
      if (!p.visible) return;
      const kg = p.reserved_kg || 0;
      const inAir = !p.place;
      const status = inAir
        ? (kg > 0 ? '✈️ unterwegs' : '✈️ dabei')
        : ((d.route || []).includes(p.place) && p.place !== d.destination
            ? '🅿️ lädt in ' + _kesc(p.place)
            : '🅿️ steht in ' + _kesc(p.place));
      active.push({
        callsign: p.callsign, aircraft: p.aircraft,
        kg: kg, lines: p.cargo_lines || [],
        dep: p.place || '', dest: d.destination || '',
        // Am Boden IMMER die Menge — ob er beladen ist, sieht man ihm sonst nicht an.
        // '✈️ dabei' braucht keine: es bedeutet leer.
        status: status + (inAir && kg <= 0 ? '' : ' · ' + Math.round(kg) + ' kg'),
      });
    });
```

- [ ] **Step 2: Die Feed-Labels nachziehen**

In `_kCargoLabel` (4864-4867):

```javascript
  // 'lädt (reserviert)' hiess frueher: er reserviert, hat aber nichts. Jetzt traegt er die Ware
  // wirklich — die Reservierung IST die Bordladung.
  if (!f.loaded) return f.in_air ? (f.airborne ? '<td class="kf-empty">unterwegs</td>'
                                               : '<td class="kf-empty">lädt</td>')
                                 : '<td class="kf-empty">leer</td>';
```

In `_kutterDetailBody` (5017) — die Tilde entfällt, die Menge ist keine Schätzung mehr:

```javascript
      : f.in_air ? '<td class="kf-res">' + _kDualKg(f.reserved_kg, f.onboard_reserved_kg)
                 + (f.airborne ? ' ✈️' : ' 🅿️') + '</td>'
```

- [ ] **Step 3: Manuell prüfen**

```bash
uvicorn app.main:app --reload
# http://localhost:8091 -> Live-Tab (laufendes Kutter-Event) + Events-Tab -> Kutter-Detail
```

Prüfen: Blau (`--green`) nur auf Klickbarem (stehende UI-Regel), Tabelle horizontal scrollbar
(`.table-scroll`), kein `✅ angekommen` und kein `↩️ Rückflug` mehr.

- [ ] **Step 4: Commit**

```bash
git add app/static/index.html
git commit -m "feat(kutter): Status ehrlich — laedt/steht/unterwegs/dabei, kein angekommen mehr"
```

---

### Task 11: Plausibilitätsprüfung am `departure`-Feld

**Files:**
- Modify: `app/database.py` — `set_transport_cargo` (4473-4503)
- Modify: `app/main.py` — `_validate_transport_manifest` (2770-2797)
- Modify: `app/calendar_sync.py` — `_CARGO_MARKER_RE` (62-64), `parse_cargo_lines` (67-100)
- Modify: `app/static/admin.html` — Feld-Beschreibung am `departure`-Eingabefeld
- Test: `tests/test_transport.py`, `tests/test_calendar_sync.py`

**Regel (Entscheidung 6):** Genau **ein** gültiges ICAO, ≠ Ziel, Feld ist **Pflicht**.
*Nicht* „muss in der abgeleiteten Route liegen" — die Route wird aus eben diesen Startplätzen
abgeleitet (`_derive_route`, `database.py:4445`), die Bedingung könnte nie fehlschlagen und prüft
nichts (Fable-Review).

**Fehlertext (wörtlich):** „Jede Frachtart liegt an genau einem Platz. Für dieselbe Ware an
mehreren Plätzen leg mehrere Zeilen an."

**Bestand:** 16 von 17 Zeilen tragen bereits genau einen Platz; `departure IS NULL` kommt **kein
einziges Mal** vor. Einzige CSV-Zeile: Event #123 („Multi-Kutter-Test", Krabbenbrötchen ab
`EDWL,EDXH,EDXP`) — ein Testlauf, darf abweichen oder gelöscht werden.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transport.py — in TestKutterCreateValidation (ab 2272) ergänzen
def test_mehrfach_icao_wird_abgewiesen(self):
    from app.main import _validate_transport_manifest
    err = _validate_transport_manifest("EDXH", [
        {"name": "Krabbenbrötchen", "target_kg": 500, "departure": "EDWL,EDXP"},
    ])
    assert err is not None
    assert "genau einem Platz" in err

def test_genau_ein_icao_geht_durch(self):
    from app.main import _validate_transport_manifest
    assert _validate_transport_manifest("EDXH", [
        {"name": "Krabbenbrötchen", "target_kg": 500, "departure": "EDWL"},
    ]) is None

def test_departure_ist_pflicht(self):
    from app.main import _validate_transport_manifest
    err = _validate_transport_manifest("EDXH", [{"name": "Fisch", "target_kg": 500}])
    assert err is not None

def test_departure_gleich_ziel_wird_abgewiesen(self):
    """Heute still zu NULL normalisiert — das erzeugte eine nie füllbare Zeile."""
    from app.main import _validate_transport_manifest
    err = _validate_transport_manifest("EDXH", [
        {"name": "Fisch", "target_kg": 500, "departure": "EDXH"},
    ])
    assert err is not None
```

```python
# tests/test_calendar_sync.py — ergänzen
def test_fracht_marker_mit_mehreren_icao_wird_abgewiesen():
    """Statt still zu teilen: der Sync meldet den Fehler am Event (Entscheidung 6)."""
    from app.calendar_sync import parse_cargo_lines
    lines = parse_cargo_lines("Fracht EDWG, EDWZ: 500 Fisch")
    assert lines == []      # keine stille Zeile ohne eindeutigen Ort

def test_fracht_marker_ohne_icao_wird_abgewiesen():
    from app.calendar_sync import parse_cargo_lines
    assert parse_cargo_lines("Fracht: 500 Fisch") == []

def test_fracht_marker_mit_einem_icao_bleibt(self=None):
    from app.calendar_sync import parse_cargo_lines
    lines = parse_cargo_lines("Fracht EDWG: 500 Fisch")
    assert lines == [{"name": "Fisch", "target_kg": 500.0, "departure": "EDWG"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport.py::TestKutterCreateValidation -v tests/test_calendar_sync.py -v`
Expected: FAIL — `assert None is not None` (`_validate_transport_manifest` verlangt heute nur
„mindestens einen Startplatz", `parse_cargo_lines` teilt Mehrfach-ICAO still auf)

- [ ] **Step 3: Write minimal implementation**

`app/main.py`, in `_validate_transport_manifest` die `departure`-Prüfung ersetzen:

```python
        rows += 1
        # Entscheidung 6 (Spec 2026-07-15): eine Manifest-Zeile = ein Stapel = GENAU ein Platz.
        # Der "geteilte Topf" (departure NULL) und die CSV-Liste entfallen: eine Zeile ohne
        # eindeutigen Ort hat keinen Stapel, an dem sie liegen könnte.
        dep = _normalize_icao_list(line.get("departure"), exclude=destination)
        if not dep or "," in dep:
            return (f"Frachtart „{name}“: Jede Frachtart liegt an genau einem Platz. "
                    "Für dieselbe Ware an mehreren Plätzen leg mehrere Zeilen an.")
```

`app/database.py`, in `set_transport_cargo` (verbindlich serverseitig — der Endpoint ist nicht der
einzige Aufrufer):

```python
        dep = _normalize_icao_list(line.get("departure"), exclude=destination)
        if not dep or "," in dep:
            raise ValueError(
                f"Frachtart „{name}“: Jede Frachtart liegt an genau einem Platz. "
                "Für dieselbe Ware an mehreren Plätzen leg mehrere Zeilen an."
            )
```

`app/calendar_sync.py`, in `parse_cargo_lines` nach der `dep`-Normalisierung:

```python
        # Entscheidung 6: genau ein Platz je Zeile. Ohne oder mit mehreren ICAO wird die Zeile
        # ABGEWIESEN, statt still eine Zeile ohne Ort ("geteilter Topf") anzulegen — der
        # Kalender-Sync meldet den Fehler am Event.
        if not dep or "," in dep:
            continue
```

`app/static/admin.html`, am `departure`-Eingabefeld die Beschreibung ergänzen:

```html
<small>Genau ein Platz je Frachtart. Dieselbe Ware an mehreren Plätzen? Mehrere Zeilen anlegen.</small>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ -q`
Expected: alle grün. **Achtung:** Die CSV-Tests (`test_legacy_all_null_unchanged` 1228,
`test_latch_fallback_unknown_dep_fills_all` 1218, sowie 1162, 1170, 1279) testen das entfallene
Verhalten — sie werden hier gelöscht bzw. auf die neue Regel umgeschrieben.

- [ ] **Step 5: Commit**

```bash
git add app/database.py app/main.py app/calendar_sync.py app/static/admin.html tests/
git commit -m "feat(kutter): eine Frachtart liegt an genau einem Platz (Plausibilitaetspruefung)"
```

---

### Task 12: Migration, Doku, Changelog

**Files:**
- Modify: `app/database.py:4053` (`_PROGRESS_SNAPSHOT_VERSION`)
- Modify: `docs/architecture.md`, `docs/api.md`, `README.md`
- Modify: `app/CHANGELOG.json`

**Kein Auftau-Schutz, kein Einfrieren** (Entscheidung 9): Version erhöhen, neu rechnen. Die drei
echten Abende bleiben aufs Gramm gleich, obwohl das Modell völlig anders rechnet.

`transport_live_arrivals` wird **nicht gelöscht**, nur nicht mehr gelesen — kein DROP in dieser
Änderung; die Tabelle ist der Beleg für die Migration und stört nicht.

- [ ] **Step 1: Snapshot-Version erhöhen**

`app/database.py:4053`:

```python
_PROGRESS_SNAPSHOT_VERSION = "4"  # "4": Stapel-Modell — Ladung ist ein Bestand mit einem Ort
```

- [ ] **Step 2: Doku nachziehen** (stehende Regel)

- `docs/architecture.md` — die Kutter-Sektion (ab Z. 172) ersetzen: Latch/Reservierung/
  Verlust-Klassifikation raus, Stapel-Modell + Erhaltungssatz rein, Verweis auf
  `app/transport_stacks.py` und die Spec.
- `docs/api.md` (Z. 649) — der Feld-Vertrag: `reserved_kg` heißt jetzt „was an Bord ist";
  `participants[].status` ∈ `flying|dabei|done` (kein `arrived`, kein `returning`), neu
  `participants[].visible` und `participants[].place`.
- `README.md` — die Kutter-Beschreibung, falls sie den Latch erwähnt.

- [ ] **Step 3: Changelog + Version** (stehende Regel: Major, `highlight: true`)

`app/CHANGELOG.json`, oben einfügen:

```json
{
  "version": "9.2.0",
  "date": "2026-07-16",
  "highlight": true,
  "changes": [
    "📦 Der FriesenKutter weiß jetzt, was an Bord ist. Bisher hat er die Fracht aus dem Startplatz deines LETZTEN Flugbeins geraten — wer über einen zweiten Ladeplatz flog, bei dem verschwand die erste Ladung (800 kg Fisch wurden zu 0), und wer über einen fremden Platz zwischenlandete, bekam 1000 kg gutgeschrieben, darunter Ware, die nie an Bord war. Jetzt liegt die Ware auf Stapeln: Du lädst, wenn du am Boden an einem Ladeplatz stehst, lieferst beim Landen am Ziel und gibst zurück, wenn du dort ausloggst. Was du geladen hast, bleibt an Bord — auch über Zwischenlandungen.",
    "🚚 Der Milchmann funktioniert: EDWG → EDWZ → Ziel lädt an BEIDEN Plätzen und liefert beides.",
    "🅿️ Neue Anzeige: „lädt in EDWG · 800 kg“ (am Stapel), „steht in EDDW · 800 kg“ (Zwischenstopp — vorher unsichtbar), „unterwegs · 800 kg“ (mit Menge) und „dabei“ (fliegt leer). „✅ angekommen“ ist weg: eine Lieferung ist eine Tatsache im Balken, kein Zustand.",
    "⚖️ Der Balken kann nicht mehr lügen: geliefert + verloren + an Bord + Rest = Manifest. Immer. Das ist jetzt Arithmetik, keine Zusicherung."
  ]
}
```

Version auch in `app/main.py`/`app/config.py` erhöhen, falls dort gepflegt.

- [ ] **Step 4: Verifikation**

```bash
pytest tests/ -q
```

Expected: alle grün.

```bash
git tag v9.2.0
```

- [ ] **Step 5: Commit**

```bash
git add app/database.py app/CHANGELOG.json docs/ README.md
git commit -m "docs(kutter): Stapel-Modell dokumentiert, Snapshot-Version 4, v9.2.0"
```

---

## Verifikation nach dem Deploy

⏸ **Nutzer-Gate.** Nach dem Deploy gegen die Live-Daten prüfen:

1. **Die drei Regressionswerte** stehen in den abgeschlossenen Events: #1 = 1610, #81 = 1120,
   #136 = 1090 kg. Weichen sie ab, ist die Migration kaputt — das ist der aussagekräftigste Test,
   weil er echte Abende gegen ein völlig anderes Rechenmodell hält.
2. **#123** („Multi-Kutter-Test") zeigt 417 statt 618 kg — erwartet, das war die CSV-Zeile.
   Der Nutzer wollte das Event ggf. löschen.
3. Ein laufender Kutter zeigt `🅿️ lädt in <Platz> · <kg>` vor dem Start, `✈️ unterwegs · <kg>`
   danach, und die Lieferung erscheint **beim Touchdown** (nicht erst beim Disconnect).

## Risiken

| Risiko | Gegenmittel |
|---|---|
| **Big Bang** — der Latch kann nicht halb weg sein | Task 7 ist das Netz: Die Migration wird verifiziert, **bevor** ein produktiver Pfad angefasst wird. |
| **Das Task-7-Gate deckt die Adapter-Fallen NICHT ab** (Fable-Review): Die vier Alt-Events haben nur geschlossene Sessions, vermutlich keine Refile-Splits und kein StatSim im Fenster. Ein grünes Gate beweist die Migration, nicht den Adapter. | Deshalb hat **jede** der drei Fallen einen eigenen Test in Task 6 (`test_refile_split_ist_kein_logout`, `test_leg_nach_dtend_geht_nicht_verloren`, `test_statsim_leg_erzeugt_eigene_ereignisse`) plus die Gegenprobe `test_echter_logout_bleibt_ein_logout`. |
| **Die 2-Sekunden-Grenze der Session-Verkettung** ist eine Annahme über den Poll-Takt | Gegenprobe im Test: S8 (2:54 min Lücke) muss ein Logout **bleiben**. Wird der Split je anders implementiert, schlägt `test_refile_split_ist_kein_logout` an. |
| Der Feed-Filter (`dep ∈ route` **oder** `arr ∈ route`) zieht mehr Zeilen als heute | Bewusst: Wer mit Ware zwischenlandet, ist heute unsichtbar, obwohl er Teil des Abends ist. |
| `test_transport.py` hat 173 Tests in 34 Klassen; ~60 hängen am Latch | Task 9 Step 4 listet sie einzeln. Die „Anzupassen"-Zeile ist echte Verhaltensprüfung, kein Suchen-und-Ersetzen. |
| Ein beladener Pilot hält das Event über `dtend` offen | Gewollt (Entscheidung 10). Sicherung: `close_stale_flights` (`database.py:895`, 8 h) schließt hängende Sessions. |

## Was dieser Plan NICHT anfasst

- **Der tote Refile-Pfad** (409 Zeilen: `canonicalize_flights`, `merge_fragmented_flights`,
  `_segments_continuous`, `audit_gps_vs_refile`; einziger Aufrufer `/api/admin/gps-leg-audit`, in
  keiner UI verlinkt). Eigener Task, nicht dieser.
- **`transport_live_arrivals`** wird nicht gedroppt (Beleg für die Migration).
- **Der 365-Tage-Cleanup** (Entscheidung 12) — der Job ist auskommentiert (`poller.py:424`); die
  Regel gilt für jede Reaktivierung, ist aber nicht Teil dieses Umbaus.




