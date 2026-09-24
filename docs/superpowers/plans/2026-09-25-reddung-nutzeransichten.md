# FriesenReddung — Nutzeransichten Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die FriesenReddung wird für Piloten sichtbar — Live-Block, Kartenebene mit abgesuchten Zellen, Bilanz unter Events mit Teilen-Text, Kachelzeile in den Statistiken.

**Architecture:** Der Server bekommt einen koordinatenfreien Raster-Endpunkt (`GET /api/reddung/events/{id}/raster`), dessen Geometrie aus einer einzigen Funktion (`raster_masse`) kommt; beide Lesewege enden wie der Poller bei `aufgeloest_am`. Das Frontend holt die Reddung-Liste in einem gemeinsamen 30-s-Takt (`_reddungTakt`) und speist daraus Live-Block, Kartenebene und Bilanz. Die abgesuchten Zellen werden je Zeile zu Läufen zusammengefasst und als **ein** SVG-Mehrfachpolygon gezeichnet.

**Tech Stack:** Python 3.12 / FastAPI / SQLite (`app/`), Vanilla-JS + Leaflet mit leaflet-rotate in einer einzigen `app/static/index.html` (Website **und** Kniebrett), pytest, node 18 für JS-Einzeltests.

**Spec:** `docs/superpowers/specs/2026-09-23-reddung-nutzeransichten-design.md`

## Global Constraints

- **Die Koordinate des Havaristen (`havarist_lat`, `havarist_lon`) verlässt den Server nie in Richtung Browser** — weder vor noch nach dem Fund noch nach der Auflösung (Spec Abschnitt 2). Kein neuer Endpunkt, keine neue Antwort darf sie enthalten.
- **Kein `L.canvas` an `liveMap`.** Die Karte läuft mit leaflet-rotate; Canvas liegt dort je Zoomstufe doppelt so weit daneben (Kommentar über `_fseZoneBauen` in `index.html`).
- **`_REDDUNG_STAND_FASSUNG` wird nicht erhöht.**
- Fassung **15.18.0**, Changelog-Eintrag mit `"highlight": false`.
- Nutzertexte: immer **„FriesenReddung"** und **„FriesenBrügge"**, nie verkürzt; Anrede „du"; **keine ausgeschriebenen Zahlwörter** („zwei", „drei" …) in README, Changelog und Oberfläche.
- Wer ein sichtbares Feature baut, schreibt den README-Absatz **im selben Commit** (die README ist zugleich die Hilfe hinter dem `?`).
- Quelltext-Tests binden an Bezeichner im Code, nie an Kommentartext; wer Kommentare durchsucht, entfernt sie vorher.
- Jede Textersetzung prüft vorher, dass die Fundstelle genau einmal vorkommt.
- Tests laufen mit `/home/claude/.venv-friesenspy/bin/python -m pytest` im Repo-Wurzelverzeichnis `/home/claude/projects/friesenspy`.
- **Nicht pushen.** Ein Push deployt den Container neu; das entscheidet der Nutzer.
- Commits enden mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Sektor mit vertauschten Ecken in der Datenbank** (`nord < sued` oder `ost < west`) — erwartet: Der Raster-Endpunkt liefert den Sektor sortiert, die Karte zeichnet Rahmen und Zellen an der richtigen Stelle. Test in Task 2.
2. **Zwei FriesenReddungen laufen gleichzeitig** — erwartet: Der Live-Block zeigt beide untereinander, die Karte zeigt beide. Tests in Task 4 und Task 5.
3. **Abgesuchte Zellen in der letzten, über den Sektor hinausragenden Zeile oder Spalte** (`zellen_aus_box` rundet auf) — erwartet: Die gefüllte Fläche endet am Sektorrahmen und ragt nicht darüber hinaus. Test in Task 5.
4. **Der Nutzer wählt die Ebene ab, und 30 Sekunden später kommt der nächste Takt** — erwartet: Sie bleibt ab, bis er sie selbst wieder einschaltet oder „Zur Karte" drückt. Test in Task 5.
5. **`/api/reddung/events` ist kurz nicht erreichbar** — erwartet: Live-Block, Ebene und Bilanz bleiben, wie sie waren, statt zu verschwinden. Test in Task 4.

---

## Datei-Übersicht

| Datei | Verantwortung | Tasks |
|---|---|---|
| `app/abdeckung.py` | `raster_masse` — die einzige Rechnung der Rastergeometrie | 1 |
| `app/reddung.py` | `kante_km(ev)` neben `korridor_km(ev)` | 2 |
| `app/database.py` | `reddung_fortschreiben` (+`zellen_abgedeckt`), `_reddung_lese_ende`, `compute_reddung_stand` (+`kante_km`, Ende), `reddung_raster`, `aggregate_reddung_kpis` | 2, 7 |
| `app/main.py` | `GET /api/reddung/events/{id}/raster`, `reddung` in `/api/stats/special-events` | 3, 7 |
| `app/static/index.html` | Takt, Live-Block, Kartenebene, Legende, Bilanz, Teilen, Kachelzeile | 4–7 |
| `tests/test_abdeckung.py` | Rastergeometrie | 1 |
| `tests/test_reddung_db.py` | Stand, Ende, Raster ohne Koordinate | 2 |
| `tests/test_reddung_api.py` | Endpunkt | 3 |
| `tests/test_reddung_ansichten.py` (neu) | Frontend: Takt, Live-Block, Karte, Bilanz | 4–6 |
| `tests/test_reddung_kpi.py` (neu) | Aggregat und Kachelzeile | 7 |
| `tests/test_special_events_stats.py` | Verdrahtung des Statistik-Endpunkts | 7 |
| `docs/api.md` | Endpunkt-Doku (⚠ die Spec nennt `docs/architecture.md`; die Endpunkte stehen aber in `docs/api.md`) | 3, 7 |
| `README.md` | Handbuch | 4–7 |
| `app/CHANGELOG.json` | 15.18.0 | 8 |
| — (nur Messung, Bericht im Chat) | Laufzeit der Testsuite | 9 |

⚠ **Reihenfolge weicht von Spec Abschnitt 11 ab:** Der Live-Block (Task 4) kommt vor der Karte (Task 5), weil er den gemeinsamen Takt `_reddungTakt` und die Liste `_reddungListe` anlegt, die Karte und Bilanz benutzen. Die Spec ordnete nach Risiko, nicht nach Abhängigkeit.

---

### Task 1: `raster_masse` — die Rastergeometrie aus einer Funktion

**Files:**
- Modify: `app/abdeckung.py` (Funktion `zellen_aus_box`, ab `def zellen_aus_box(`)
- Test: `tests/test_abdeckung.py` (anhängen)

**Interfaces:**
- Produces: `raster_masse(sued: float, west: float, nord: float, ost: float, kante_km: float) -> tuple[int, int, float, float]` — `(zeilen, spalten, d_lat, d_lon)`; vertauschte Ecken werden intern sortiert; `kante_km` wird wie bisher auf mindestens 0,05 geklemmt.

- [ ] **Step 1: Write the failing test** — an `tests/test_abdeckung.py` anhängen:

```python
# --- raster_masse: die Geometrie des Sektorrasters (Spec 2026-09-23, Abschnitt 3) ---------

from app.abdeckung import raster_masse, zellen_aus_box


def test_raster_masse_passt_zu_zellen_aus_box():
    """Die Karte rechnet Zellen aus (zeilen, spalten, d_lat, d_lon). Weicht das von
    zellen_aus_box ab, liegt jede gezeichnete Zelle neben der gewerteten."""
    box = (53.54, 6.95, 53.90, 7.55)
    zeilen, spalten, d_lat, d_lon = raster_masse(*box, kante_km=1.0)
    ziele = zellen_aus_box(*box, kante_km=1.0, korridor_km=1.0)
    assert len(ziele) == zeilen * spalten
    for schluessel, lat, lon, _r in ziele:
        i, j = (int(x) for x in schluessel[1:].split("_"))
        assert box[0] + i * d_lat < lat < box[0] + (i + 1) * d_lat, schluessel
        assert box[1] + j * d_lon < lon < box[1] + (j + 1) * d_lon, schluessel


def test_raster_masse_sortiert_vertauschte_ecken():
    assert raster_masse(53.90, 7.55, 53.54, 6.95, 1.0) == raster_masse(53.54, 6.95, 53.90, 7.55, 1.0)


def test_raster_masse_klemmt_die_kante_wie_zellen_aus_box():
    """Eine Null-Kante darf kein Raster aus Millionen Zellen ergeben -- dieselbe Klemme."""
    zeilen, spalten, _, _ = raster_masse(53.54, 6.95, 53.56, 6.97, 0.0)
    assert zeilen * spalten == len(zellen_aus_box(53.54, 6.95, 53.56, 6.97, 0.0, 1.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_abdeckung.py -q -k raster_masse`
Expected: FAIL with `ImportError: cannot import name 'raster_masse'`

- [ ] **Step 3: Implement** — in `app/abdeckung.py` **direkt vor** `def zellen_aus_box(` einfügen:

```python
def raster_masse(sued: float, west: float, nord: float, ost: float,
                 kante_km: float) -> tuple[int, int, float, float]:
    """Zeilen, Spalten und Zellgröße in Grad — die Geometrie des Sektorrasters.

    **Die einzige Stelle, die sie rechnet.** ``zellen_aus_box`` benutzt sie, und der
    Raster-Endpunkt gibt sie an die Karte weiter. Rechneten beide selbst, läge irgendwann
    jede gezeichnete Zelle still neben der gewerteten (Spec 2026-09-23, Abschnitt 3).

    Zelle ``z{i}_{j}`` reicht von ``sued + i·d_lat`` bis ``sued + (i+1)·d_lat`` und von
    ``west + j·d_lon`` bis ``west + (j+1)·d_lon`` — mit den SORTIERTEN Ecken.
    """
    if nord < sued:
        sued, nord = nord, sued
    if ost < west:
        west, ost = ost, west
    kante_km = max(float(kante_km), 0.05)
    km_lon = _km_je_grad_lon((sued + nord) / 2.0)
    zeilen = max(1, math.ceil((nord - sued) * _KM_JE_GRAD_LAT / kante_km))
    spalten = max(1, math.ceil((ost - west) * km_lon / kante_km))
    return zeilen, spalten, kante_km / _KM_JE_GRAD_LAT, kante_km / km_lon
```

Dann in `zellen_aus_box` den Rumpf ab `if nord < sued:` bis einschließlich `return ziele` ersetzen durch:

```python
    if nord < sued:
        sued, nord = nord, sued
    if ost < west:
        west, ost = ost, west
    zeilen, spalten, d_lat, d_lon = raster_masse(sued, west, nord, ost, kante_km)
    ziele: list[Ziel] = []
    for i in range(zeilen):
        zlat = sued + (i + 0.5) * d_lat
        for j in range(spalten):
            zlon = west + (j + 0.5) * d_lon
            ziele.append((f"{praefix}{i}_{j}", zlat, zlon, float(korridor_km)))
    return ziele
```

- [ ] **Step 4: Run tests to verify they pass** — die ganze Datei, denn `zellen_aus_box` hat vorhandene Tests:

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_abdeckung.py tests/test_reddung_db.py tests/test_reddung_poller.py -q`
Expected: alle PASS

- [ ] **Step 5: Commit**

```bash
git add app/abdeckung.py tests/test_abdeckung.py
git commit -m "raster_masse: die Rastergeometrie aus einer Funktion

zellen_aus_box rechnet jetzt darauf; der Raster-Endpunkt reicht sie an die
Karte weiter (Spec 2026-09-23, Abschnitt 3).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Stand und Raster — Kante, Ende bei der Auflösung, abgedeckte Schlüssel

**Files:**
- Modify: `app/reddung.py` (neben `def korridor_km(`; `zellen_fuer`)
- Modify: `app/database.py` (`reddung_fortschreiben` Rückgabe, `compute_reddung_stand`, neue Funktionen `_reddung_lese_ende`, `reddung_raster`)
- Test: `tests/test_reddung_db.py` (anhängen)

**Interfaces:**
- Consumes: `raster_masse` aus Task 1.
- Produces:
  - `app.reddung.kante_km(ev: dict) -> float`
  - `reddung_fortschreiben(...)` gibt zusätzlich `"zellen_abgedeckt": list[str]` zurück (sortierte Schlüssel `z{i}_{j}`). ⚠ `"abgedeckt"` bleibt dort die **Anzahl**.
  - `_reddung_lese_ende(ev: dict) -> str` — `min(jetzt, dtend, aufgeloest_am)` als ISO-String.
  - `compute_reddung_stand(conn, ev)` gibt zusätzlich `"kante_km": float` zurück und schreibt nur noch bis `_reddung_lese_ende(ev)` fort.
  - `reddung_raster(conn, ev) -> dict` mit genau den Schlüsseln `sektor` (`{sued, west, nord, ost}`, sortiert), `raster` (`{zeilen, spalten, d_lat, d_lon}`), `zellen` (int), `abgedeckt` (`list[str]`), `anteil` (float), `aufgeloest` (bool).

- [ ] **Step 1: Write the failing tests** — an `tests/test_reddung_db.py` anhängen (die Hilfen `_kleiner_sektor`, `_spur`, `_quer`, `JETZT`, `_iso`, `LAT`, `LON` stehen dort schon):

```python
# --- Nutzeransichten (Spec 2026-09-23): Kante, Ende, Raster ----------------------------

from app.database import reddung_raster, set_reddung_aufgeloest, set_reddung_gefunden


def test_die_kante_steht_im_stand(conn):
    """Ohne sie laesst sich keine Flaeche nennen -- Bilanz, Live-Block und Kennzahlen
    brauchen sie."""
    stand = compute_reddung_stand(conn, get_reddung_event(conn, _kleiner_sektor(conn)))
    assert stand["kante_km"] == 1.0


def test_nach_der_aufloesung_wird_nichts_mehr_gezaehlt(conn):
    """⚠ Der Poller schreibt nach `aufgeloest_am` nicht mehr fort -- der Leseweg darf es auch
    nicht. Sonst haengt die Flaeche eines frueh aufgeloesten Abends davon ab, ob zufaellig
    jemand die Seite offen hatte (Spec Abschnitt 3). Rote Gegenprobe: ohne die Schranke ist
    `abgedeckt` hier > 0 (vgl. test_ein_ueberflug_deckt_zellen_ab)."""
    eid = _kleiner_sektor(conn)
    set_reddung_aufgeloest(conn, eid, _iso(JETZT - timedelta(minutes=90)))
    _spur(conn, 111, _quer(vor_min=60))       # geflogen NACH der Aufloesung
    assert compute_reddung_stand(conn, get_reddung_event(conn, eid))["abgedeckt"] == 0
    assert reddung_raster(conn, get_reddung_event(conn, eid))["abgedeckt"] == []


def test_das_raster_nennt_die_abgedeckten_zellen(conn):
    eid = _kleiner_sektor(conn)
    _spur(conn, 111, _quer())
    ev = get_reddung_event(conn, eid)
    r = reddung_raster(conn, ev)
    from app import reddung as rd
    alle = {z[0] for z in rd.zellen_fuer(ev)}
    assert r["abgedeckt"] and set(r["abgedeckt"]) <= alle
    assert r["zellen"] == r["raster"]["zeilen"] * r["raster"]["spalten"] == len(alle)
    assert r["abgedeckt"] == sorted(r["abgedeckt"])
    assert set(r) == {"sektor", "raster", "zellen", "abgedeckt", "anteil", "aufgeloest"}


def test_ein_leerer_sektor_hat_ein_raster_ohne_zellen(conn):
    r = reddung_raster(conn, get_reddung_event(conn, _kleiner_sektor(conn)))
    assert r["abgedeckt"] == [] and r["zellen"] > 0 and r["anteil"] == 0.0


def test_das_raster_sortiert_vertauschte_ecken(conn):
    """Review-Fokus 1: Steht der Sektor verdreht in der Tabelle, muss die Karte trotzdem am
    richtigen Ort zeichnen -- sie rechnet von `sued`/`west` aus."""
    eid = _kleiner_sektor(conn)
    ev = get_reddung_event(conn, eid)
    conn.execute("UPDATE reddung_events SET sued=?, nord=?, west=?, ost=? WHERE id=?",
                 (ev["nord"], ev["sued"], ev["ost"], ev["west"], eid))
    s = reddung_raster(conn, get_reddung_event(conn, eid))["sektor"]
    assert s["sued"] < s["nord"] and s["west"] < s["ost"]
    assert s["sued"] == pytest.approx(ev["sued"]) and s["west"] == pytest.approx(ev["west"])


def test_das_raster_enthaelt_NIEMALS_die_koordinate(conn):
    """⚠ Weder vor dem Fund noch danach noch nach der Aufloesung (Spec Abschnitt 2,
    Nutzerentscheidung 24.09.2026: den Ort zeigt die Rauchsaeule im Simulator)."""
    import json
    eid = _kleiner_sektor(conn)
    _spur(conn, 111, _quer())
    for schritt in ("vorher", "gefunden", "aufgeloest"):
        if schritt == "gefunden":
            set_reddung_gefunden(conn, eid, _iso(JETZT - timedelta(minutes=30)), 111)
        if schritt == "aufgeloest":
            set_reddung_aufgeloest(conn, eid, _iso(JETZT - timedelta(minutes=20)))
        text = json.dumps(reddung_raster(conn, get_reddung_event(conn, eid)))
        for zahl in (f"{LAT:.4f}", f"{LON:.4f}", f"{LAT:.3f}", f"{LON:.3f}"):
            assert zahl not in text, f"{schritt}: Koordinate {zahl} steht im Raster"
        assert "havarist" not in text, schritt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_db.py -q`
Expected: FAIL with `ImportError: cannot import name 'reddung_raster'`

- [ ] **Step 3a: `kante_km` in `app/reddung.py`** — direkt nach der Funktion `korridor_km` einfügen:

```python
def kante_km(ev: dict) -> float:
    """Die Zellkante des Rasters — die Feinheit der Buchhaltung, nie größer als der Korridor."""
    return _zahl(ev, "kante_km", _VORGABE_KANTE_KM)
```

und in `zellen_fuer` die Zeile `kante_km=_zahl(ev, "kante_km", _VORGABE_KANTE_KM),` ersetzen durch `kante_km=kante_km(ev),`.

- [ ] **Step 3b: `zellen_abgedeckt` in `reddung_fortschreiben`** (`app/database.py`) — im abschließenden `return {` von `reddung_fortschreiben` nach der Zeile `"abgedeckt": len(treffer),` einfügen:

```python
        # ⚠ Absichtlich ein anderer Name als `abgedeckt` -- das ist hier die ANZAHL. Der
        # Raster-Endpunkt reicht die Liste als `abgedeckt` heraus (Spec Abschnitt 3).
        "zellen_abgedeckt": sorted(treffer),
```

- [ ] **Step 3c: Ende und Kante in `compute_reddung_stand`** — direkt **vor** `def compute_reddung_stand(` einfügen:

```python
def _reddung_lese_ende(ev: dict) -> str:
    """Bis wohin die Lesewege fortschreiben: jetzt, ``dtend`` oder die Auflösung.

    ⚠ Dasselbe Ende wie im Poller, der nach ``aufgeloest_am`` nicht mehr rechnet
    (``_check_reddung``). Ohne die Schranke hinge die Fläche eines früh aufgelösten Abends
    davon ab, ob zwischen Auflösung und ``dtend`` zufällig jemand die Seite offen hatte --
    und nach zwölf Stunden ist ``bruegge_spur`` weg (Spec 2026-09-23, Abschnitt 3).
    """
    return min(_now_utc(), ev["dtend"], ev.get("aufgeloest_am") or ev["dtend"])
```

In `compute_reddung_stand` die Zeile
`    stand = reddung_fortschreiben(conn, ev, bis=min(_now_utc(), ev["dtend"]))`
ersetzen durch
`    stand = reddung_fortschreiben(conn, ev, bis=_reddung_lese_ende(ev))`
und im zurückgegebenen Dict nach `"korridor_km": rd.korridor_km(ev),` einfügen:
`        "kante_km": rd.kante_km(ev),`

- [ ] **Step 3d: `reddung_raster`** — direkt **nach** `compute_reddung_stand` einfügen:

```python
def reddung_raster(conn: sqlite3.Connection, ev: dict) -> dict:
    """Das Raster einer FriesenReddung für die Karte: Geometrie und abgesuchte Zellen.

    ⚠ **Gibt NIE die Koordinate des Havaristen heraus** -- vor dem Fund nicht, danach nicht,
    nach der Auflösung nicht (Spec 2026-09-23, Abschnitt 2; Nutzerentscheidung 24.09.2026:
    den Ort zeigt die Rauchsäule im Simulator). ``tests/test_reddung_db.py`` hält es fest.

    Der Sektor geht SORTIERT hinaus: Die Karte rechnet jede Zelle von ``sued``/``west`` aus,
    und ein verdreht gespeichertes Rechteck läge sonst gespiegelt.
    """
    from app import reddung as rd
    from app.abdeckung import raster_masse

    stand = reddung_fortschreiben(conn, ev, bis=_reddung_lese_ende(ev))
    sued, nord = sorted((float(ev["sued"]), float(ev["nord"])))
    west, ost = sorted((float(ev["west"]), float(ev["ost"])))
    zeilen, spalten, d_lat, d_lon = raster_masse(sued, west, nord, ost, rd.kante_km(ev))
    return {
        "sektor": {"sued": sued, "west": west, "nord": nord, "ost": ost},
        "raster": {"zeilen": zeilen, "spalten": spalten, "d_lat": d_lat, "d_lon": d_lon},
        "zellen": stand["zellen"],
        "abgedeckt": stand["zellen_abgedeckt"],
        "anteil": stand["anteil"],
        "aufgeloest": bool(ev.get("aufgeloest_am")),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_db.py tests/test_reddung_poller.py tests/test_reddung_api.py tests/test_reddung_parameter.py tests/test_abdeckung.py -q`
Expected: alle PASS

- [ ] **Step 5: Commit**

```bash
git add app/reddung.py app/database.py tests/test_reddung_db.py
git commit -m "FriesenReddung: Stand mit Kante, Raster ohne Koordinate, Ende bei der Aufloesung

Der Leseweg schrieb nach aufgeloest_am weiter fort, der Poller nicht -- die
Flaeche eines frueh aufgeloesten Abends hing davon ab, ob jemand die Seite
offen hatte (Spec 2026-09-23, Abschnitt 3).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Der Raster-Endpunkt

**Files:**
- Modify: `app/main.py` (Import-Block `from app.database import (` ab Zeile 50; neuer Endpunkt direkt nach der Funktion `reddung_events`)
- Modify: `docs/api.md` (nach dem Abschnitt `## GET /api/reddung/events`)
- Test: `tests/test_reddung_api.py` (anhängen)

**Interfaces:**
- Consumes: `reddung_raster(conn, ev)` aus Task 2, `get_reddung_event` (bereits importiert).
- Produces: `GET /api/reddung/events/{event_id}/raster` → `{"id", "name", "dtstart", "dtend", "sektor", "raster", "zellen", "abgedeckt", "anteil", "aufgeloest"}`; `404` bei unbekannter id. Python-Name `reddung_raster_endpunkt(event_id: int)`.

- [ ] **Step 1: Write the failing tests** — an `tests/test_reddung_api.py` anhängen:

```python
# --- Raster-Endpunkt (Spec 2026-09-23, Abschnitt 3) ------------------------------------

def test_raster_endpunkt_liefert_geometrie_und_zellen(db):
    eid = _anlegen()
    d = main.reddung_raster_endpunkt(eid)
    assert d["id"] == eid and d["name"] == "Reddung Probe"
    assert set(d) == {"id", "name", "dtstart", "dtend", "sektor", "raster", "zellen",
                      "abgedeckt", "anteil", "aufgeloest"}
    assert d["zellen"] == d["raster"]["zeilen"] * d["raster"]["spalten"]
    assert d["abgedeckt"] == []


def test_raster_endpunkt_kennt_unbekannte_ids_nicht(db):
    """Eine leere 200 waere fuer die Karte nicht von „noch unberuehrt" zu unterscheiden."""
    with pytest.raises(HTTPException) as e:
        main.reddung_raster_endpunkt(9999)
    assert e.value.status_code == 404


def test_raster_endpunkt_traegt_keine_koordinate_auch_nach_dem_fund(db):
    """⚠ Der Riegel an der Stelle, die jeder Browser erreicht."""
    eid = _anlegen()
    asyncio.run(main.admin_update_reddung_event(
        FakeReq(body={"havarist_lat": 53.72, "havarist_lon": 7.25}), eid))
    c = get_connection(db)
    try:
        c.execute("UPDATE reddung_events SET gefunden_am='2026-09-25T18:00:00Z', "
                  "gefunden_von=111, aufgeloest_am='2026-09-25T18:00:00Z' WHERE id=?", (eid,))
        c.commit()
    finally:
        c.close()
    text = json.dumps(main.reddung_raster_endpunkt(eid))
    for zahl in ("53.72", "7.25", "havarist"):
        assert zahl not in text, f"{zahl} steht in der Raster-Antwort"


def test_raster_endpunkt_liegt_hinter_dem_login_gate():
    """Er steht NICHT in den gate-freien Praefixen -- sonst waere die Flaeche oeffentlich."""
    assert not "/api/reddung/events/1/raster".startswith(main._GATE_ALLOW_PREFIXES)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_api.py -q -k raster`
Expected: FAIL with `AttributeError: module 'app.main' has no attribute 'reddung_raster_endpunkt'`

- [ ] **Step 3: Implement** — in `app/main.py` im Import-Block `from app.database import (` nach der Zeile `    compute_reddung_stand,` die Zeile `    reddung_raster,` ergänzen. Dann direkt nach der Funktion `reddung_events` (endet mit `        conn.close()` vor `@app.get("/api/transport/event/{event_id}")`) einfügen:

```python
@app.get("/api/reddung/events/{event_id}/raster")
def reddung_raster_endpunkt(event_id: int):
    """Das Suchraster einer FriesenReddung für die Karte — Geometrie und abgesuchte Zellen.

    ⚠ **Ohne die Lage des Havaristen, auch nach dem Fund.** Den Ort zeigt die Rauchsäule im
    Simulator (Nutzerentscheidung 24.09.2026, Spec 2026-09-23 Abschnitt 2). Die Zusicherung
    steckt in ``reddung_raster``; Tests in ``tests/test_reddung_db.py`` und hier.

    Liegt hinter dem Login-Gate wie die Eventliste. Unbekannte id → 404: Eine leere Antwort
    wäre für die Karte nicht von „noch unberührt" zu unterscheiden.
    """
    conn = get_connection(get_settings().DB_PATH)
    try:
        ev = get_reddung_event(conn, event_id)
        if not ev:
            raise HTTPException(status_code=404, detail="Event nicht gefunden")
        raus = {"id": ev["id"], "name": ev.get("name"), "dtstart": ev.get("dtstart"),
                "dtend": ev.get("dtend"), **reddung_raster(conn, ev)}
        conn.commit()          # das Fortschreiben hat den Snapshot ergaenzt
        return raus
    finally:
        conn.close()
```

In `docs/api.md` direkt vor der Zeile `## Admin: FriesenReddung` (davor steht `---`) einfügen:

```markdown
## GET /api/reddung/events/{id}/raster

Das Suchraster einer FriesenReddung für die Kartenebene. Hinter dem Login-Gate; `404` bei unbekannter id.

**Response** `{"id": int, "name": string, "dtstart": string, "dtend": string, "sektor": {"sued", "west", "nord", "ost"}, "raster": {"zeilen": int, "spalten": int, "d_lat": float, "d_lon": float}, "zellen": int, "abgedeckt": ["z0_0", …], "anteil": float, "aufgeloest": bool}`

Zelle `z{i}_{j}` reicht von `sued + i·d_lat` bis `sued + (i+1)·d_lat` und von `west + j·d_lon` bis `west + (j+1)·d_lon`. Die Maße kommen aus `raster_masse` (`app/abdeckung.py`), derselben Funktion, die auch die gewerteten Zellen schneidet — die Karte rechnet nichts nach. Der Sektor geht sortiert hinaus.

⚠ **Ohne die Lage des Havaristen — vor dem Fund, danach und nach der Auflösung.** Den Ort zeigt die Rauchsäule im Simulator.

Geschrieben wird höchstens bis `min(jetzt, dtend, aufgeloest_am)` — dasselbe Ende wie im Poller.

---

```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_api.py tests/test_api_schutz.py -q`
Expected: alle PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py docs/api.md tests/test_reddung_api.py
git commit -m "GET /api/reddung/events/{id}/raster -- das Suchraster fuer die Karte

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Der gemeinsame Takt und der Live-Block

**Files:**
- Modify: `app/static/index.html` — CSS (Regeln `#bummel-banner, #kutter-banner {` ff.), Markup im LIVE-Tab, neuer JS-Abschnitt direkt vor der Zeile `//  TAB SWITCHING`, Start neben `fetchKutterActive();` und in `alleDatenNeuLaden`
- Modify: `README.md` (Abschnitt `## 🚨 FriesenReddung (Suchen und Retten)`)
- Create: `tests/test_reddung_ansichten.py`

**Interfaces:**
- Consumes: `/api/reddung/events` (Stand enthält seit Task 2 `kante_km`).
- Produces (JS, alle auf oberster Ebene):
  - `let _reddungListe` — letzte Antwort von `/api/reddung/events` (Array).
  - `async function _reddungTakt()` — holt die Liste, ruft danach `_reddungBannerZeigen()`; Task 5 und Task 6 hängen je eine Zeile an.
  - `function _reddungBalken(pct)` → HTML-String.
  - `function _reddungMarkenHtml(st)` → HTML-String (gefunden/aufgenommen/eingeliefert).
  - `function _reddungBannerZeigen()`, `function _reddungBannerBlock(r)`.
  - Der Knopf ruft `reddungAufKarte(id)` — **definiert in Task 5**. Bis dahin tut der Knopf nichts; Task 5 ist Pflicht vor jeder Auslieferung.

- [ ] **Step 1: Write the failing tests** — `tests/test_reddung_ansichten.py` neu anlegen:

```python
# -*- coding: utf-8 -*-
"""Die Nutzeransichten der FriesenReddung (Spec 2026-09-23).

Reine Funktionen werden in node ausgefuehrt (herausgeschnitten aus index.html), alles andere
an Bezeichnern im Code geprueft -- nie an Kommentaren.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
INDEX = (WURZEL / "app" / "static" / "index.html").read_text(encoding="utf-8")
README = (WURZEL / "README.md").read_text(encoding="utf-8")
_NODE = shutil.which("node")


def _funktion(name: str) -> str:
    """Den Quelltext einer Funktion auf oberster Ebene -- bis zur ersten `}` in Spalte 0."""
    m = re.search(rf"^(async )?function {re.escape(name)}\(", INDEX, flags=re.M)
    assert m, f"function {name} fehlt"
    return INDEX[m.start():INDEX.index("\n}\n", m.start()) + 3]


def _ohne_kommentare(text: str) -> str:
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def _node(quelltext: str, ausdruck: str):
    skript = quelltext + "\nconsole.log(JSON.stringify(" + ausdruck + "));"
    erg = subprocess.run([_NODE, "-e", skript], capture_output=True, text=True, timeout=20)
    assert erg.returncode == 0, erg.stderr
    return json.loads(erg.stdout.strip().splitlines()[-1])


# --- Takt und Live-Block ------------------------------------------------------------------

def test_der_live_block_steht_ueber_bummel_und_kutter():
    """Eine laufende FriesenReddung ist die Lage mit der Uhr im Nacken."""
    live = INDEX[INDEX.index('<div id="tab-live"'):INDEX.index('<div id="tab-karte"')]
    assert live.index('id="reddung-banner"') < live.index('id="bummel-banner"')


def test_der_takt_laeuft_und_haelt_einen_aussetzer_aus():
    """Review-Fokus 5: Ist die Liste kurz nicht erreichbar, bleibt alles, wie es war --
    der Block darf nicht bei jedem Netzaussetzer verschwinden."""
    rumpf = _ohne_kommentare(_funktion("_reddungTakt"))
    assert "fetch('/api/reddung/events')" in rumpf
    fang = rumpf.index("catch")
    assert rumpf.index("return", fang) < rumpf.index("_reddungBannerZeigen()")
    assert "setInterval(_reddungTakt, 30000)" in INDEX
    assert "_reddungTakt();" in _funktion("alleDatenNeuLaden")


def test_die_zustaende_stehen_vor_dem_ersten_aufruf():
    """⚠ Ein `let` hinter seinem ersten Aufruf auf oberster Ebene legt die GANZE Seite lahm
    (TDZ) -- und `node --check` findet das nicht."""
    erster_aufruf = INDEX.index("setInterval(_reddungTakt, 30000)")
    assert INDEX.index("let _reddungListe") < erster_aufruf


def test_der_live_block_stapelt_mehrere_laufende():
    """Review-Fokus 2: Zwei gleichzeitig -- beide erscheinen, nicht nur die erste."""
    rumpf = _ohne_kommentare(_funktion("_reddungBannerZeigen"))
    assert ".map(_reddungBannerBlock).join('')" in rumpf


def test_der_live_block_liest_nur_die_liste():
    """Die Liste fuehrt keine Koordinate; das Raster gehoert der Karte."""
    for name in ("_reddungBannerZeigen", "_reddungBannerBlock", "_reddungMarkenHtml"):
        assert "/raster" not in _funktion(name), name


def test_die_readme_beschreibt_den_live_block():
    abschnitt = README[README.index("## 🚨 FriesenReddung"):README.index("## 🔧 Verwaltung")]
    assert "Noch nicht zu sehen" not in abschnitt, "die alte Ankuendigung muss weg"
    assert "**Was du davon siehst:**" in abschnitt
    liste = abschnitt[abschnitt.index("**Was du davon siehst:**"):]
    assert "**Live-Ansicht:**" in liste
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_ansichten.py -q`
Expected: FAIL (`reddung-banner` bzw. `function _reddungTakt fehlt`)

- [ ] **Step 3a: CSS** — in `index.html` diese drei Selektorzeilen ersetzen (jede kommt genau einmal vor):

| alt | neu |
|---|---|
| `    #bummel-banner, #kutter-banner {` | `    #bummel-banner, #kutter-banner, #reddung-banner {` |
| `    #bummel-banner .bb-title, #kutter-banner .bb-title {` | `    #bummel-banner .bb-title, #kutter-banner .bb-title, #reddung-banner .bb-title {` |
| `    #bummel-banner .bb-sub, #kutter-banner .bb-sub {` | `    #bummel-banner .bb-sub, #kutter-banner .bb-sub, #reddung-banner .bb-sub, #reddung-results .bb-sub {` |

und direkt vor `    .bummel-rank-1 {` einfügen:

```css
    /* FriesenReddung: ein schlichter Balken -- die Flaeche hat keine Aufschluesselung wie die
       Kutter-Fracht, nur einen Anteil. */
    .reddung-balken { height: 10px; background: rgba(45,156,219,0.15); margin: 8px 0 6px; }
    .reddung-balken > span { display: block; height: 100%; background: var(--green); }
    .reddung-live-block + .reddung-live-block {
      margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--green-dim);
    }
```

- [ ] **Step 3b: Markup** — im LIVE-Tab die Zeile `    <div id="bummel-banner" hidden></div>` ersetzen durch:

```html
    <div id="reddung-banner" hidden></div>
    <div id="bummel-banner" hidden></div>
```

- [ ] **Step 3c: JS-Abschnitt** — direkt **vor** der Zeile `// ==========================================================================` die unmittelbar über `//  TAB SWITCHING` steht, einfügen:

```js
// ==========================================================================
//  FRIESENREDDUNG — Takt, Live-Block, Karte, Bilanz (Spec 2026-09-23)
// ==========================================================================
// ⚠ Die Koordinate des Havaristen kommt hier nie an: `/api/reddung/events` und der
// Raster-Endpunkt fuehren sie nicht, auch nicht nach dem Fund. Den Ort zeigt die
// Rauchsaeule im Simulator (Nutzerentscheidung 24.09.2026).
//
// ⚠ Alle Zustaende stehen HIER oben -- vor dem ersten Aufruf auf oberster Ebene
// (`setInterval(_reddungTakt, …)` weiter unten). Ein `let` dahinter legte die Seite lahm.
let _reddungListe = [];          // letzte Antwort von /api/reddung/events

function _jetztIso() {
  return new Date().toISOString().slice(0, 19) + 'Z';
}

// Ein Takt fuer alles: Live-Block, Karte und Bilanz lesen dieselbe Liste.
async function _reddungTakt() {
  try {
    const res = await fetch('/api/reddung/events');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    _reddungListe = (await res.json()) || [];
  } catch (e) {
    // Ein Aussetzer nimmt nichts weg: Block, Ebene und Bilanz bleiben, wie sie waren.
    return;
  }
  _reddungBannerZeigen();
}

function _reddungBalken(pct) {
  return `<div class="reddung-balken"><span style="width:${Math.max(0, Math.min(100, pct))}%"></span></div>`;
}

function _reddungMarkenHtml(st) {
  const zeit = ts => (ts || '').slice(11, 16) + ' UTC';
  const z = [];
  if (st.gefunden) z.push(`Gefunden von ${escHtml(st.gefunden.name || '?')} um ${zeit(st.gefunden.ts)}`);
  if (st.aufgenommen) z.push(`Aufgenommen von ${escHtml(st.aufgenommen.name || '?')} um ${zeit(st.aufgenommen.ts)}`);
  if (st.eingeliefert) z.push(`Eingeliefert in ${escHtml(st.eingeliefert.icao || '?')} von ${escHtml(st.eingeliefert.name || '?')} um ${zeit(st.eingeliefert.ts)}`);
  if (!z.length) return '<div class="bb-sub">Noch nicht gefunden.</div>';
  return z.map(t => `<div class="bb-sub">${t}</div>`).join('');
}

function _reddungBannerZeigen() {
  const banner = document.getElementById('reddung-banner');
  if (!banner) return;
  const jetzt = _jetztIso();
  const laufend = _reddungListe.filter(r => (r.dtstart || '') <= jetzt && jetzt <= (r.dtend || ''));
  if (!laufend.length) { banner.hidden = true; banner.innerHTML = ''; return; }
  banner.innerHTML = laufend.map(_reddungBannerBlock).join('');
  banner.hidden = false;
}

function _reddungBannerBlock(r) {
  const st = r.stand || {};
  const pct = Math.round((st.anteil || 0) * 100);
  const kante = st.kante_km || 1;
  const offenKm2 = Math.round((st.offen || 0) * kante * kante);
  let html = `<div class="reddung-live-block"><div class="bb-title">🚨 ${escHtml(r.name || 'FriesenReddung')} läuft gerade</div>`;
  html += _reddungBalken(pct);
  html += `<div class="bb-sub">${pct} % abgesucht · noch offen: ${offenKm2} km²</div>`;
  html += _reddungMarkenHtml(st);
  html += `<div style="margin-top:8px;"><button class="btn-share" onclick="reddungAufKarte(${Number(r.id)})">${icon('map')} Zur Karte</button></div></div>`;
  return html;
}

```

- [ ] **Step 3d: Start** — die Zeile `setInterval(fetchKutterActive, 25000);  // Kutter-Live-Block im Kutter-Detail-Takt (Live-Aktualität)` bleibt; **direkt danach** einfügen:

```js
_reddungTakt();
setInterval(_reddungTakt, 30000);  // FriesenReddung: Live-Block, Karte und Bilanz im Takt des Pollers
```

und in `async function alleDatenNeuLaden()` nach `  fetchKutterActive();` die Zeile `  _reddungTakt();` ergänzen.

- [ ] **Step 3e: README** — im Abschnitt `## 🚨 FriesenReddung (Suchen und Retten)` den Block von `> **Noch nicht zu sehen:**` bis zum Ende dieses Zitats (die Zeile `> Fläche auf der Karte und im Kniebrett — kommt als nächster Schritt.`) **ersetzen** durch:

```markdown
**Was du davon siehst:**

- **Live-Ansicht:** Läuft eine FriesenReddung, steht sie ganz oben — mit dem Balken, wie viel
  vom Sektor schon abgesucht ist, wie viel Fläche noch offen ist, und wer gefunden,
  aufgenommen und eingeliefert hat. Laufen mehrere gleichzeitig, stehen sie untereinander.
  Wo der Havarist liegt, steht dort nie — den Ort zeigt dir die Rauchsäule im Simulator.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_ansichten.py tests/test_readme_aktuell.py tests/test_vr_panel.py -q`
Expected: alle PASS

- [ ] **Step 5: Commit**

```bash
git add app/static/index.html README.md tests/test_reddung_ansichten.py
git commit -m "FriesenReddung: gemeinsamer Takt und Live-Block

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Die Kartenebene „FriesenReddung"

**Files:**
- Modify: `app/static/index.html` — JS-Abschnitt aus Task 4 erweitern; Klick-Handler des Karte-Tabs; Karten-Legende
- Modify: `README.md` (Reddung-Abschnitt, Liste „Was du davon siehst"; Abschnitt `## 🗺️ Karten-Layer`)
- Test: `tests/test_reddung_ansichten.py` (anhängen)

**Interfaces:**
- Consumes: `_reddungListe`, `_reddungTakt`, `_jetztIso` (Task 4); `GET /api/reddung/events/{id}/raster` (Task 3); globale `liveMap`, `_liveEbenenControl`, `initLiveMap`.
- Produces:
  - `function _reddungZuZeigen(liste, jetztIso, geoeffnetId) -> number[]` (rein)
  - `function _reddungLaeufe(abgedeckt, raster, sektor) -> [[lat, lon] × 4][]` (rein)
  - `function _reddungKarteAbgleichen()`, `async function _reddungRasterHolen(id, jetztIso)`, `function _reddungZeichnen(id, d)`
  - `async function reddungAufKarte(id)` — vom Live-Block (Task 4) und der Bilanz (Task 6) gerufen
  - `let _reddungGeoeffnetId` — von `reddungAufKarte` gesetzt

- [ ] **Step 1: Write the failing tests** — an `tests/test_reddung_ansichten.py` anhängen:

```python
# --- Kartenebene -----------------------------------------------------------------------

@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_zu_zeigen_sind_laufende_frische_und_die_geoeffnete():
    """Review-Fokus 2: zwei laufende gleichzeitig -- beide. Dazu, was vor weniger als 24 h
    endete, und die eine aus der Bilanz, gleich welchen Alters (Spec Abschnitt 4)."""
    liste = [
        {"id": 1, "dtstart": "2026-09-24T17:00:00Z", "dtend": "2026-09-24T20:00:00Z"},  # laeuft
        {"id": 2, "dtstart": "2026-09-23T17:00:00Z", "dtend": "2026-09-23T20:30:00Z"},  # vor 22,5 h zu Ende
        {"id": 3, "dtstart": "2026-09-20T17:00:00Z", "dtend": "2026-09-20T20:00:00Z"},  # alt
        {"id": 4, "dtstart": "2026-09-24T17:30:00Z", "dtend": "2026-09-24T21:00:00Z"},  # laeuft auch
        {"id": 5, "dtstart": "2026-09-25T17:00:00Z", "dtend": "2026-09-25T20:00:00Z"},  # kommt erst
    ]
    q = _funktion("_reddungZuZeigen")
    jetzt = '"2026-09-24T19:00:00Z"'
    assert _node(q, f"_reddungZuZeigen({json.dumps(liste)}, {jetzt}, null)") == [1, 2, 4]
    assert _node(q, f"_reddungZuZeigen({json.dumps(liste)}, {jetzt}, 3)") == [1, 2, 3, 4]
    assert _node(q, f"_reddungZuZeigen([], {jetzt}, null)") == []


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_laeufe_fassen_eine_zeile_zusammen_und_enden_am_rahmen():
    """Review-Fokus 3: Die letzte Zeile/Spalte ragt ueber den Sektor (aufgerundet) -- die
    Flaeche muss am Rahmen enden, nicht darueber hinaus."""
    raster = {"zeilen": 2, "spalten": 3, "d_lat": 0.01, "d_lon": 0.02}
    sektor = {"sued": 50.0, "west": 8.0, "nord": 50.015, "ost": 8.05}
    q = _funktion("_reddungLaeufe")
    ringe = _node(q, f"_reddungLaeufe(['z0_1','z0_0','z1_2'], {json.dumps(raster)}, {json.dumps(sektor)})")
    assert len(ringe) == 2
    assert ringe[0] == pytest.approx([[50.0, 8.0], [50.0, 8.04], [50.01, 8.04], [50.01, 8.0]])
    assert ringe[1] == pytest.approx([[50.01, 8.04], [50.01, 8.05], [50.015, 8.05], [50.015, 8.04]])
    luecke = _node(q, f"_reddungLaeufe(['z0_0','z0_2'], {json.dumps(raster)}, {json.dumps(sektor)})")
    assert len(luecke) == 2, "eine Luecke in der Zeile trennt die Laeufe"
    assert _node(q, f"_reddungLaeufe([], {json.dumps(raster)}, {json.dumps(sektor)})") == []


def test_kein_canvas_auf_dieser_karte():
    """⚠ liveMap laeuft mit leaflet-rotate, und das traegt den Canvas-Renderer nicht: Versatz,
    der sich je Zoomstufe verdoppelt (FSE-Ebenen bis 16.08.2026). Geprueft ueber den GANZEN
    Code ohne Kommentare -- dort steht die Warnung, im Code darf der Aufruf nie stehen."""
    assert "L.canvas" not in _ohne_kommentare(INDEX)
    rumpf = _ohne_kommentare(_funktion("_reddungZeichnen"))
    assert "renderer" not in rumpf


def test_die_flaeche_ist_ein_mehrfachpolygon():
    """Als flache Ringliste naehme Leaflet jeden Ring ab dem zweiten als LOCH des ersten."""
    rumpf = _ohne_kommentare(_funktion("_reddungZeichnen"))
    assert "ringe.map(r => [r])" in rumpf and "L.polygon(" in rumpf
    assert "setLatLngs(" in rumpf, "beim Nachladen ersetzen, nicht neu anlegen"


def test_die_ebene_haengt_sich_nachtraeglich_ein_und_wieder_aus():
    rumpf = _ohne_kommentare(_funktion("_reddungKarteAbgleichen"))
    assert "_liveEbenenControl.addOverlay(_reddungGruppe, 'FriesenReddung')" in rumpf
    assert "_liveEbenenControl.removeLayer(_reddungGruppe)" in rumpf


def test_eine_abwahl_haelt_bis_zum_neuladen():
    """Review-Fokus 4: Der naechste Takt darf eine abgewaehlte Ebene nicht wieder einschalten.
    Nur „Zur Karte" schaltet sie zurueck."""
    abgleich = _ohne_kommentare(_funktion("_reddungKarteAbgleichen"))
    assert "!_reddungAbgewaehlt" in abgleich
    assert "overlayremove" in abgleich and "_reddungSelbst" in abgleich
    assert "_reddungAbgewaehlt = false" in _funktion("reddungAufKarte")
    # Nicht gespeichert: kein Merker fuer diese Ebene.
    assert "_prefSchreib" not in abgleich


def test_abgelaufene_werden_einmal_geladen():
    rumpf = _ohne_kommentare(_funktion("_reddungRasterHolen"))
    assert "_reddungRasterFertig" in rumpf and "/raster" in rumpf


def test_die_karte_holt_sich_die_ebene_beim_oeffnen():
    """Sonst erscheint sie erst mit dem naechsten Takt, bis zu 30 s nach dem Oeffnen.

    ⚠ Verankert an `_vollbildWiederherstellen();` -- das steht genau einmal im Code und nur in
    diesem Handler. `if (tab === 'karte') {` steht zweimal (auch in `} else if (tab === …`)."""
    assert INDEX.count("_vollbildWiederherstellen();") == 1
    stelle = INDEX.index("_vollbildWiederherstellen();")
    davor = INDEX[INDEX.rindex("await initLiveMap();", 0, stelle):stelle]
    danach = INDEX[stelle:INDEX.index("refreshLiveData();", stelle)]
    assert "await initLiveMap();" in davor
    assert "_reddungKarteAbgleichen();" in danach


def test_die_kartenzustaende_stehen_vor_dem_ersten_aufruf():
    erster_aufruf = INDEX.index("setInterval(_reddungTakt, 30000)")
    for name in ("let _reddungGruppe", "let _reddungGeoeffnetId", "const _reddungZeichnung",
                 "const _reddungRasterFertig", "let _reddungAbgewaehlt", "let _reddungSelbst"):
        assert INDEX.index(name) < erster_aufruf, name


def test_die_legende_nennt_die_ebene_mit_eigenem_satz():
    start = INDEX.index('<div class="panel-title">Karten-Legende</div>')
    block = INDEX[start:INDEX.index("TAB: STATISTIKEN", start)]
    zeile = next(z for z in re.findall(r"<li>(.*?)</li>", block, re.S)
                 if "<strong>FriesenReddung</strong>" in z)
    satz = re.sub(r"<[^>]+>", "", zeile).split("—", 1)
    assert len(satz) == 2 and len(satz[1].strip()) > 15


def test_die_readme_beschreibt_die_karte():
    abschnitt = README[README.index("## 🚨 FriesenReddung"):README.index("## 🔧 Verwaltung")]
    assert "**Karte:**" in abschnitt
    layer = README[README.index("## 🗺️ Karten-Layer"):]
    assert "**FriesenReddung**" in layer[:layer.index("\n---")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_ansichten.py -q`
Expected: die neuen Tests FAIL (`function _reddungZuZeigen fehlt` usw.)

- [ ] **Step 3a: Zustände** — im JS-Abschnitt aus Task 4 direkt **nach** der Zeile `let _reddungListe = [];          // letzte Antwort von /api/reddung/events` einfügen:

```js
let _reddungGeoeffnetId = null;         // aus Live-Block oder Bilanz auf die Karte geholt
let _reddungGruppe = null;              // L.layerGroup der Ebene „FriesenReddung"
let _reddungEbeneDa = false;            // steht der Eintrag gerade in der Ebenen-Auswahl?
// Vom Nutzer abgewaehlt -- gilt bis zum Neuladen und wird bewusst NICHT gespeichert: Sonst
// verschwaende die Ebene beim naechsten Abend still, und wieder saehe sie niemand.
let _reddungAbgewaehlt = false;
// Eigenes addTo/removeLayer loest overlayadd/overlayremove aus; das darf nicht als Wahl des
// Nutzers zaehlen (dasselbe Muster wie _groundEbeneStilllegen).
let _reddungSelbst = false;
const _reddungZeichnung = new Map();    // id -> { rahmen, flaeche }
const _reddungRasterFertig = new Map(); // id -> Raster abgelaufener Reddungen: einmal geladen
```

- [ ] **Step 3b: Takt** — in `_reddungTakt` nach der Zeile `  _reddungBannerZeigen();` einfügen: `  _reddungKarteAbgleichen();`

- [ ] **Step 3c: Funktionen** — am Ende des JS-Abschnitts aus Task 4 (nach `_reddungBannerBlock`) einfügen:

```js
// Welche Reddungen die Karte zeigt -- eine Liste, keine Zeitspanne (Spec Abschnitt 4):
// die laufenden, die vor weniger als 24 h endeten (die Nachbesprechung ist am Abend danach),
// und die eine, die jemand aus der Bilanz geholt hat, gleich welchen Alters.
function _reddungZuZeigen(liste, jetztIso, geoeffnetId) {
  const jetzt = Date.parse(jetztIso);
  const TAG_MS = 24 * 3600 * 1000;
  const ids = [];
  (liste || []).forEach(r => {
    const start = Date.parse(r.dtstart || ''), ende = Date.parse(r.dtend || '');
    const laeuft = start <= jetzt && jetzt <= ende;
    const frisch = ende < jetzt && jetzt - ende < TAG_MS;
    if (laeuft || frisch || r.id === geoeffnetId) ids.push(r.id);
  });
  return ids;
}

// Die abgesuchten Zellen je Zeile zu Laeufen zusammenfassen -- ein Rechteck je Lauf. Die
// letzte Zeile/Spalte ragt ueber den Sektor (die Zellenzahl ist aufgerundet); gekappt wird
// am Rahmen, sonst stuende gefuellte Flaeche ausserhalb der Aufgabe.
function _reddungLaeufe(abgedeckt, raster, sektor) {
  const zeilen = new Map();
  (abgedeckt || []).forEach(k => {
    const m = /^z(\d+)_(\d+)$/.exec(k);
    if (!m) return;
    const i = Number(m[1]), j = Number(m[2]);
    if (!zeilen.has(i)) zeilen.set(i, []);
    zeilen.get(i).push(j);
  });
  const ringe = [];
  [...zeilen.keys()].sort((a, b) => a - b).forEach(i => {
    const js = zeilen.get(i).sort((a, b) => a - b);
    let von = js[0], bis = js[0];
    const schliessen = () => {
      const s = sektor.sued + i * raster.d_lat;
      const n = Math.min(s + raster.d_lat, sektor.nord);
      const w = sektor.west + von * raster.d_lon;
      const o = Math.min(sektor.west + (bis + 1) * raster.d_lon, sektor.ost);
      ringe.push([[s, w], [s, o], [n, o], [n, w]]);
    };
    for (let k = 1; k < js.length; k++) {
      if (js[k] === bis + 1) { bis = js[k]; continue; }
      schliessen();
      von = bis = js[k];
    }
    schliessen();
  });
  return ringe;
}

function _reddungKarteAbgleichen() {
  if (typeof liveMap === 'undefined' || !liveMap || !_liveEbenenControl) return;
  if (!_reddungGruppe) {
    _reddungGruppe = L.layerGroup();
    liveMap.on('overlayremove', e => {
      if (e.layer === _reddungGruppe && !_reddungSelbst) _reddungAbgewaehlt = true;
    });
    liveMap.on('overlayadd', e => {
      if (e.layer !== _reddungGruppe || _reddungSelbst) return;
      _reddungAbgewaehlt = false;
      _reddungKarteAbgleichen();   // wieder eingeschaltet: sofort laden, nicht erst im Takt
    });
  }
  const jetzt = _jetztIso();
  const ids = _reddungZuZeigen(_reddungListe, jetzt, _reddungGeoeffnetId);
  if (!ids.length) {
    if (_reddungEbeneDa) {
      _reddungSelbst = true;
      try {
        liveMap.removeLayer(_reddungGruppe);
        _liveEbenenControl.removeLayer(_reddungGruppe);
      } finally {
        _reddungSelbst = false;
      }
      _reddungEbeneDa = false;
    }
    return;
  }
  if (!_reddungEbeneDa) {
    _liveEbenenControl.addOverlay(_reddungGruppe, 'FriesenReddung');
    _reddungEbeneDa = true;
  }
  if (!_reddungAbgewaehlt && !liveMap.hasLayer(_reddungGruppe)) {
    _reddungSelbst = true;
    try { _reddungGruppe.addTo(liveMap); } finally { _reddungSelbst = false; }
  }
  for (const [id, z] of _reddungZeichnung) {
    if (!ids.includes(id)) {
      _reddungGruppe.removeLayer(z.rahmen);
      _reddungGruppe.removeLayer(z.flaeche);
      _reddungZeichnung.delete(id);
    }
  }
  // Geladen wird nur, solange die Ebene an ist -- abgewaehlt kostet sie keine Anfrage.
  if (!liveMap.hasLayer(_reddungGruppe)) return;
  ids.forEach(id => _reddungRasterHolen(id, jetzt));
}

async function _reddungRasterHolen(id, jetztIso) {
  const r = _reddungListe.find(x => x.id === id);
  if (!r) return;
  const vorbei = (r.dtend || '') < jetztIso;
  let d = vorbei ? _reddungRasterFertig.get(id) : null;
  if (!d) {
    try {
      const res = await fetch('/api/reddung/events/' + id + '/raster');
      if (!res.ok) return;
      d = await res.json();
    } catch (e) {
      return;
    }
    // Abgelaufen aendert sich nichts mehr -- einmal laden, nie wieder fragen.
    if (vorbei) _reddungRasterFertig.set(id, d);
  }
  _reddungZeichnen(id, d);
}

// ⚠ SVG, KEIN Canvas: liveMap laeuft mit leaflet-rotate, und das Plugin traegt den
// Canvas-Renderer nicht (s. Kommentar ueber _fseZoneBauen). Alle Laeufe sind EIN Pfad.
function _reddungZeichnen(id, d) {
  if (!_reddungGruppe || !d || !d.sektor || !d.raster) return;
  const s = d.sektor;
  const ringe = _reddungLaeufe(d.abgedeckt, d.raster, s);
  // Jeder Lauf ein EIGENES Polygon: Als flache Liste naehme Leaflet die Ringe ab dem zweiten
  // als Loecher des ersten.
  const polys = ringe.map(r => [r]);
  let z = _reddungZeichnung.get(id);
  if (!z) {
    z = {
      rahmen: L.rectangle([[s.sued, s.west], [s.nord, s.ost]],
        { color: '#e05555', weight: 2, dashArray: '8 6', fill: false, interactive: false }),
      flaeche: L.polygon(polys,
        { stroke: false, fillColor: '#2d9cdb', fillOpacity: 0.3, interactive: false }),
    };
    _reddungGruppe.addLayer(z.rahmen);
    _reddungGruppe.addLayer(z.flaeche);
    _reddungZeichnung.set(id, z);
  } else {
    z.flaeche.setLatLngs(polys);
  }
}

async function reddungAufKarte(id) {
  _reddungGeoeffnetId = Number(id);
  _reddungAbgewaehlt = false;
  const tab = document.querySelector('.tab-btn[data-tab="karte"]');
  if (tab) tab.click();
  await new Promise(r => setTimeout(r, 300));
  if (!liveMap) await initLiveMap();
  _reddungKarteAbgleichen();
  const r = _reddungListe.find(x => x.id === Number(id));
  const s = r && r.stand && r.stand.sektor;
  if (s && liveMap) liveMap.fitBounds([[s.sued, s.west], [s.nord, s.ost]], { padding: [30, 30] });
}
```

- [ ] **Step 3d: Karte-Tab** — im Klick-Handler `if (tab === 'karte') {` nach der Zeile `          _vollbildWiederherstellen();` einfügen:

```js
          // Die FriesenReddung-Ebene sofort, nicht erst mit dem naechsten Takt.
          _reddungKarteAbgleichen();
```

- [ ] **Step 3e: Legende** — in `index.html` in der Karten-Legende die Zeile
`              <li><strong>Verkehr</strong> — der fremde VATSIM-Verkehr (grau, siehe oben); aus Platzgründen erst ab Zoomstufe 7</li>`
unverändert lassen und **direkt davor** einfügen:

```html
              <li><strong>FriesenReddung</strong> — der Suchsektor als rot gestrichelter Rahmen, darin blau, was schon abgesucht ist; erscheint nur, solange eine FriesenReddung läuft oder am Vortag lief. Wo der Havarist liegt, zeigt sie nie</li>
```

- [ ] **Step 3f: README** — (1) in der Liste „**Was du davon siehst:**" im Reddung-Abschnitt nach dem Punkt „Live-Ansicht" anhängen:

```markdown
- **Karte:** Die Ebene **FriesenReddung** zeigt den Sektor als rot gestrichelten Rahmen und
  darin blau, was schon abgesucht ist — so seht ihr in der Luft, wo noch niemand war, und
  teilt euch auf. Sie aktualisiert sich alle 30 Sekunden, auch im Kniebrett, und ist nur da,
  solange eine FriesenReddung läuft oder am Vortag lief. „Zur Karte" im Live-Block springt
  direkt auf den Sektor.
```

(2) im Abschnitt `## 🗺️ Karten-Layer` direkt vor dem Absatz, der mit `**Sichtflugkarte**` beginnt, einfügen:

```markdown
**FriesenReddung**: Suchsektor und abgesuchte Fläche einer FriesenReddung — rot gestrichelter Rahmen, darin blau, was schon jemand abgeflogen hat. Die Ebene taucht nur auf, solange eine FriesenReddung läuft oder am Vortag lief, und ist dann eingeschaltet; schaltest du sie ab, bleibt sie bis zum Neuladen der Seite aus. Die Lage des Havaristen zeigt sie nie.

```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_ansichten.py tests/test_vr_panel.py tests/test_readme_aktuell.py -q`
Expected: alle PASS

- [ ] **Step 5: Commit**

```bash
git add app/static/index.html README.md tests/test_reddung_ansichten.py
git commit -m "FriesenReddung: Kartenebene mit Sektor und abgesuchter Flaeche

SVG-Mehrfachpolygon statt Canvas -- liveMap laeuft mit leaflet-rotate.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Die Bilanz unter Events und der Teilen-Text

**Files:**
- Modify: `app/static/index.html` — Markup im EVENTS-Tab; JS-Abschnitt; `renderFriesenEvents`; `_prefillEventForm`, `openBummel`, `openKutterDetail`, Klick-Handler von `events-search-btn`
- Modify: `README.md` (Reddung-Abschnitt)
- Test: `tests/test_reddung_ansichten.py` (anhängen)

**Interfaces:**
- Consumes: `_reddungListe`, `_reddungTakt`, `_jetztIso`, `_reddungBalken`, `_reddungMarkenHtml` (Task 4); `reddungAufKarte` (Task 5); vorhandene `_fmtMin`, `_copyText`, `escHtml`, `icon`.
- Produces: `openReddungDetail(id)`, `_reddungZu()`, `_reddungBilanzZeigen()`, `_reddungBilanzHtml(r)`, `_reddungTeilenText(r, jetztIso) -> string` (rein), `copyReddungShareHeader(btn)`, `let _reddungOffenId`.

- [ ] **Step 1: Write the failing tests** — an `tests/test_reddung_ansichten.py` anhängen:

```python
# --- Bilanz und Teilen -----------------------------------------------------------------

def test_die_eventliste_oeffnet_die_bilanz():
    """Bisher fiel der Klick bis _prefillEventForm durch und fuellte das Suchformular."""
    rumpf = _ohne_kommentare(_funktion("renderFriesenEvents"))
    assert "else if (ev.is_reddung) openReddungDetail(ev._reddungId);" in rumpf
    assert rumpf.index("openReddungDetail") < rumpf.index("_prefillEventForm(ev)")


def test_jede_andere_ansicht_schliesst_die_bilanz():
    for name in ("_prefillEventForm", "openBummel", "openKutterDetail"):
        assert "_reddungZu();" in _funktion(name), name
    suche = INDEX[INDEX.index("getElementById('events-search-btn').addEventListener"):]
    assert "_reddungZu();" in suche[:suche.index("searchEvents();")]


def test_die_bilanz_schliesst_die_anderen():
    rumpf = _funktion("openReddungDetail")
    for panel in ("bummel-results", "kutter-results", "events-results"):
        assert f"getElementById('{panel}').classList.add('hidden')" in rumpf, panel


def test_der_takt_frischt_die_offene_bilanz_auf():
    rumpf = _ohne_kommentare(_funktion("_reddungTakt"))
    assert rumpf.index("_reddungBannerZeigen()") < rumpf.index("_reddungBilanzZeigen()")


def test_die_bilanz_hat_ihr_panel_mit_teilen_knopf():
    ev = INDEX[INDEX.index('<div id="tab-events"'):]
    assert ev.index('id="kutter-results"') < ev.index('id="reddung-results"')
    assert 'onclick="copyReddungShareHeader(this)"' in ev


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_der_teilen_text_nennt_die_marken_und_keinen_ort():
    r = {"id": 3, "name": "Vermisst über der Jade", "dtend": "2026-09-24T20:00:00Z",
         "stand": {"anteil": 0.42, "abgedeckt": 672, "zellen": 1600, "kante_km": 1.0,
                   "sektor": {"sued": 53.54, "west": 6.95, "nord": 53.9, "ost": 7.55},
                   "gefunden": {"cid": 1, "name": "Stefan", "ts": "2026-09-24T19:12:00Z"},
                   "aufgenommen": {"cid": 2, "name": "Wolfgang", "ts": "2026-09-24T19:30:00Z"},
                   "eingeliefert": {"cid": 2, "name": "Wolfgang", "icao": "EDWF",
                                    "ts": "2026-09-24T19:50:00Z"},
                   "dauer_min": 38,
                   "je_pilot": [{"cid": 1, "name": "Stefan", "zellen": 400},
                                {"cid": 3, "name": "Nur Doppelt", "zellen": 0}]}}
    text = _node(_funktion("_reddungTeilenText"),
                 f"_reddungTeilenText({json.dumps(r)}, '2026-09-25T10:00:00Z')")
    assert "FriesenReddung" in text and "Vermisst über der Jade" in text
    assert "42 %" in text and "672 km²" in text
    assert "Stefan um 19:12 UTC" in text and "EDWF" in text and "38 Minuten" in text
    assert "Stefan (400 Zellen)" in text and "Nur Doppelt" not in text
    for zahl in ("53.54", "6.95", "53.9", "7.55"):
        assert zahl not in text, f"Koordinate {zahl} im Teilen-Text"


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_der_teilen_text_unterscheidet_noch_nicht_und_nicht_gefunden():
    r = {"id": 3, "name": "X", "dtend": "2026-09-24T20:00:00Z",
         "stand": {"anteil": 0.1, "abgedeckt": 10, "zellen": 100, "kante_km": 1.0,
                   "je_pilot": []}}
    q = _funktion("_reddungTeilenText")
    assert "Noch nicht gefunden" in _node(q, f"_reddungTeilenText({json.dumps(r)}, '2026-09-24T19:00:00Z')")
    assert "Nicht gefunden" in _node(q, f"_reddungTeilenText({json.dumps(r)}, '2026-09-24T21:00:00Z')")


def test_die_zustaende_der_bilanz_stehen_vor_dem_ersten_aufruf():
    assert INDEX.index("let _reddungOffenId") < INDEX.index("setInterval(_reddungTakt, 30000)")


def test_die_readme_beschreibt_die_bilanz():
    abschnitt = README[README.index("## 🚨 FriesenReddung"):README.index("## 🔧 Verwaltung")]
    assert "**Events:**" in abschnitt and "Teilen" in abschnitt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_ansichten.py -q`
Expected: die neuen Tests FAIL

- [ ] **Step 3a: Markup** — im EVENTS-Tab direkt **nach** dem schließenden `</div>` des Blocks `<div id="kutter-results" class="hidden">` (also vor dem Kommentar `<!-- Steuert nur Karte + Liste unten (events-results)`) einfügen:

```html
    <div id="reddung-results" class="hidden">
      <div class="panel">
        <div class="panel-title" style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
          <span id="reddung-title">🚨 FriesenReddung</span>
          <button class="btn-share" onclick="copyReddungShareHeader(this)">⎘ Teilen</button>
        </div>
        <div id="reddung-content"></div>
      </div>
    </div>

```

- [ ] **Step 3b: Zustand** — im JS-Abschnitt nach `const _reddungRasterFertig = new Map(); // id -> Raster abgelaufener Reddungen: einmal geladen` einfügen:

```js
let _reddungOffenId = null;             // die gerade offene Bilanz unter Events
```

- [ ] **Step 3c: Takt** — in `_reddungTakt` nach `  _reddungKarteAbgleichen();` einfügen: `  _reddungBilanzZeigen();`

- [ ] **Step 3d: Funktionen** — am Ende des JS-Abschnitts (nach `reddungAufKarte`) einfügen:

```js
function _reddungZu() {
  const w = document.getElementById('reddung-results');
  if (w) w.classList.add('hidden');
  _reddungOffenId = null;
}

async function openReddungDetail(id) {
  document.getElementById('bummel-results').classList.add('hidden');
  document.getElementById('kutter-results').classList.add('hidden');
  document.getElementById('events-results').classList.add('hidden');
  clearInterval(_kutterPollTimer);
  _kutterPollTimer = null;
  _kutterOpenId = null;
  _activeBummel = null;
  _activeBummelId = null;
  _reddungOffenId = Number(id);
  const wrap = document.getElementById('reddung-results');
  wrap.classList.remove('hidden');
  _reddungBilanzZeigen();      // sofort aus der vorhandenen Liste …
  await _reddungTakt();        // … und frisch, sobald sie da ist
  wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Im Takt aufgefrischt -- laeuft der Abend noch, waechst die Bilanz mit.
function _reddungBilanzZeigen() {
  if (_reddungOffenId == null) return;
  const r = _reddungListe.find(x => x.id === _reddungOffenId);
  const titel = document.getElementById('reddung-title');
  const inhalt = document.getElementById('reddung-content');
  if (!r || !titel || !inhalt) return;
  titel.textContent = '🚨 ' + (r.name || 'FriesenReddung');
  inhalt.innerHTML = _reddungBilanzHtml(r);
}

function _reddungBilanzHtml(r) {
  const st = r.stand || {};
  const pct = Math.round((st.anteil || 0) * 100);
  const kante = st.kante_km || 1;
  const km2 = Math.round((st.abgedeckt || 0) * kante * kante);
  const vorbei = (r.dtend || '') < _jetztIso();
  let html = _reddungBalken(pct);
  html += `<div class="bb-sub">${pct} % abgesucht — ${st.abgedeckt || 0} von ${st.zellen || 0} Zellen, ${km2} km²</div>`;
  if (st.gefunden) html += _reddungMarkenHtml(st);
  else html += `<div class="bb-sub">${vorbei ? 'Nicht gefunden.' : 'Noch nicht gefunden.'}</div>`;
  if (st.dauer_min != null) {
    html += `<div class="bb-sub">Rettung in ${_fmtMin(st.dauer_min)} — vom Fund bis zur Einlieferung</div>`;
  }
  const piloten = st.je_pilot || [];
  if (piloten.length) {
    html += '<div class="table-scroll"><table><thead><tr><th>Pilot</th><th>Als Erster abgesucht</th><th>Anteil</th></tr></thead><tbody>';
    piloten.forEach(p => {
      const anteil = st.zellen ? Math.round(100 * p.zellen / st.zellen) : 0;
      html += `<tr><td>${escHtml(p.name || String(p.cid))}</td><td class="mono">${p.zellen} Zellen</td><td class="mono">${anteil} %</td></tr>`;
    });
    html += '</tbody></table></div>';
  }
  html += `<div style="margin-top:8px;"><button class="btn-share" onclick="reddungAufKarte(${Number(r.id)})">${icon('map')} Zur Karte</button></div>`;
  return html;
}

// Forumsfertiger Absatz. Wo der Havarist lag, steht nicht darin -- so wenig wie auf der Karte.
function _reddungTeilenText(r, jetztIso) {
  const st = r.stand || {};
  const zeit = ts => (ts || '').slice(11, 16) + ' UTC';
  const pct = Math.round((st.anteil || 0) * 100);
  const kante = st.kante_km || 1;
  const km2 = Math.round((st.abgedeckt || 0) * kante * kante);
  const z = [`🚨 FriesenReddung — ${r.name || 'FriesenReddung'}`, `Abgesucht: ${pct} % (${km2} km²)`];
  if (st.gefunden) z.push(`Gefunden: ${st.gefunden.name} um ${zeit(st.gefunden.ts)}`);
  else z.push((r.dtend || '') < jetztIso ? 'Nicht gefunden' : 'Noch nicht gefunden');
  if (st.aufgenommen) z.push(`Aufgenommen: ${st.aufgenommen.name} um ${zeit(st.aufgenommen.ts)}`);
  if (st.eingeliefert) {
    z.push(`Eingeliefert: ${st.eingeliefert.icao} von ${st.eingeliefert.name} um ${zeit(st.eingeliefert.ts)}`);
  }
  if (st.dauer_min != null) z.push(`Rettung in ${st.dauer_min} Minuten`);
  const piloten = (st.je_pilot || []).filter(p => p.zellen > 0);
  if (piloten.length) {
    z.push('Abgesucht haben: ' + piloten.map(p => `${p.name} (${p.zellen} Zellen)`).join(', '));
  }
  return z.join('\n');
}

function copyReddungShareHeader(btn) {
  const r = _reddungListe.find(x => x.id === _reddungOffenId);
  if (r) _copyText(_reddungTeilenText(r, _jetztIso()), btn);
}
```

- [ ] **Step 3e: Eventliste** — in `renderFriesenEvents` die Zeile
`      else if (ev.is_transport) ev._kutterId ? openKutterDetail(ev._kutterId) : openKutter(ev);`
unverändert lassen und **direkt danach** einfügen:
`      else if (ev.is_reddung) openReddungDetail(ev._reddungId);`

- [ ] **Step 3f: Schließen** — `_reddungZu();` an diesen Stellen einfügen:
  - in `_prefillEventForm` nach `  document.getElementById('kutter-results').classList.add('hidden');`
  - in `openBummel` nach `  document.getElementById('kutter-results').classList.add('hidden');`
  - in `openKutterDetail` nach `  document.getElementById('bummel-results').classList.add('hidden');`
  - im Klick-Handler `document.getElementById('events-search-btn').addEventListener('click', () => {` nach `  document.getElementById('kutter-results').classList.add('hidden');`

⚠ Die Zeile `document.getElementById('kutter-results').classList.add('hidden');` kommt mehrfach vor — jede Einfügung am **Funktionsnamen** verankern, nicht an der Zeile allein.

- [ ] **Step 3g: README** — in der Liste „**Was du davon siehst:**" nach dem Punkt „Karte" anhängen:

```markdown
- **Events:** Ein Klick auf die FriesenReddung in der Eventliste öffnet ihre Bilanz — Balken und
  abgesuchte Fläche, wer gefunden, aufgenommen und wo eingeliefert hat, wie lange die Rettung
  dauerte, und darunter, welche Fläche jeder als Erster abgesucht hat. Der Knopf **Teilen**
  legt dir das Ganze als fertigen Absatz fürs Forum in die Zwischenablage.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_ansichten.py tests/test_events_liste.py tests/test_reddung_api.py tests/test_vr_panel.py -q`
Expected: alle PASS

- [ ] **Step 5: Commit**

```bash
git add app/static/index.html README.md tests/test_reddung_ansichten.py
git commit -m "FriesenReddung: Bilanz unter Events mit Teilen-Text

Der Klick auf die Zeile fuellte bisher das Suchformular der Event-Analyse.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Die Kennzahlen in den Statistiken

**Files:**
- Modify: `app/database.py` (neue Funktion direkt nach `aggregate_bummel_kpis`)
- Modify: `app/main.py` (Import; `get_special_events_stats`)
- Modify: `app/static/index.html` (`renderSpecialEventStats`)
- Modify: `docs/api.md` (Abschnitt `## GET /api/stats/special-events`), `README.md` (Abschnitt `### 📊 Statistiken`)
- Create: `tests/test_reddung_kpi.py`
- Modify: `tests/test_special_events_stats.py` (anhängen)

**Interfaces:**
- Consumes: `compute_reddung_stand` mit `kante_km` (Task 2).
- Produces: `aggregate_reddung_kpis(staende: list[dict]) -> dict` mit `event_count`, `participations`, `gefunden_count`, `flaeche_km2` (int), `avg_rettung_min` (float | None); `/api/stats/special-events` → `{"kutter", "bummel", "reddung"}`.

- [ ] **Step 1: Write the failing tests** — `tests/test_reddung_kpi.py` neu:

```python
# -*- coding: utf-8 -*-
"""Kennzahlen der FriesenReddung in den Statistiken (Spec 2026-09-23, Abschnitt 7)."""
from __future__ import annotations

from pathlib import Path

from app.database import aggregate_reddung_kpis

INDEX = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")


def _stand(**extra):
    basis = {"je_pilot": [{"cid": 1, "zellen": 5}], "abgedeckt": 5, "kante_km": 1.0,
             "gefunden": None, "dauer_min": None}
    basis.update(extra)
    return basis


def test_leer():
    assert aggregate_reddung_kpis([]) == {"event_count": 0, "participations": 0,
                                          "gefunden_count": 0, "flaeche_km2": 0,
                                          "avg_rettung_min": None}


def test_ein_abend_ohne_fund():
    r = aggregate_reddung_kpis([_stand()])
    assert r["event_count"] == 1 and r["gefunden_count"] == 0 and r["avg_rettung_min"] is None


def test_teilnahmen_zaehlen_auch_piloten_ohne_eigene_zelle():
    """⚠ Wer nur Flaeche abflog, die ein anderer zuerst hatte, war trotzdem dabei."""
    r = aggregate_reddung_kpis([_stand(je_pilot=[{"cid": 1, "zellen": 5}, {"cid": 2, "zellen": 0}])])
    assert r["participations"] == 2


def test_flaeche_nimmt_die_kante_jedes_abends():
    # ⚠ Werte ohne halbe km²: Python rundet 12,5 auf 12 (Banker's Rounding).
    r = aggregate_reddung_kpis([_stand(abgedeckt=10, kante_km=1.0), _stand(abgedeckt=12, kante_km=0.5)])
    assert r["flaeche_km2"] == 13      # 10 · 1² + 12 · 0,5²


def test_rettungsdauer_nur_ueber_abende_mit_einlieferung():
    r = aggregate_reddung_kpis([_stand(gefunden={"cid": 1}, dauer_min=30),
                                _stand(gefunden={"cid": 1}, dauer_min=50),
                                _stand(gefunden={"cid": 1}, dauer_min=None)])
    assert r["gefunden_count"] == 3 and r["avg_rettung_min"] == 40.0


def test_ein_abend_ohne_teilnehmer_zaehlt_nicht():
    """Wie beim Kutter: leere Probe-Events verfaelschen die Anzahl nicht."""
    assert aggregate_reddung_kpis([_stand(je_pilot=[])])["event_count"] == 0


def test_die_statistik_zeigt_eine_reddung_zeile():
    stelle = INDEX.index("function renderSpecialEventStats(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "data.reddung" in rumpf and "'🚨 FriesenReddung'" in rumpf
    assert "'Ø Rettung'" in rumpf


def test_die_readme_nennt_die_kennzahlen():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    abschnitt = readme[readme.index("### 📊 Statistiken"):readme.index("### 🔍 Event-Suche")]
    assert "FriesenReddung" in abschnitt
```

und an `tests/test_special_events_stats.py` anhängen:

```python
def test_special_events_zaehlt_abgeschlossene_reddungen(tmp_path, monkeypatch):
    """Nur Abende, deren dtend vorbei ist -- aus dem Snapshot, ohne Neuberechnung."""
    from app.database import (_REDDUNG_STAND_FASSUNG, create_reddung_event, upsert_pilot)
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch(monkeypatch, db)
    now = datetime.now(timezone.utc)
    conn = get_connection(db)
    sektor = dict(sued=53.54, west=6.95, nord=53.90, ost=7.55)
    dtend = _iso(now - timedelta(days=2))
    fertig = create_reddung_event(conn, name="Fertig", dtstart=_iso(now - timedelta(days=2, hours=3)),
                                  dtend=dtend, **sektor)
    upsert_pilot(conn, 111, "Pilot 111")
    write_progress_snapshot(conn, "reddung", fertig, {
        "v": _REDDUNG_STAND_FASSUNG, "bis": dtend,
        "treffer": {"z0_0": [111, dtend], "z0_1": [111, dtend]},
        "je_pilot": {"111": 2}, "fund": None,
    }, dtend)
    create_reddung_event(conn, name="Laeuft", dtstart=_iso(now - timedelta(hours=1)),
                         dtend=_iso(now + timedelta(hours=2)), **sektor)
    conn.commit()
    conn.close()

    r = main.get_special_events_stats(days=30)["reddung"]
    assert r["event_count"] == 1 and r["participations"] == 1
    assert r["flaeche_km2"] == 2 and r["gefunden_count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_kpi.py tests/test_special_events_stats.py -q`
Expected: FAIL with `ImportError: cannot import name 'aggregate_reddung_kpis'`

- [ ] **Step 3a: Aggregat** — in `app/database.py` direkt nach der Funktion `aggregate_bummel_kpis` einfügen:

```python
def aggregate_reddung_kpis(staende: list[dict]) -> dict:
    """Kennzahlen abgeschlossener FriesenReddungen aus fertigen ``compute_reddung_stand``-
    Dicts. Rein (keine DB). Nur Abende mit mindestens einem Teilnehmer zählen -- leere
    Probe-Events verfälschen die Anzahl sonst, wie beim Kutter.

    ⚠ ``participations`` zählt JEDEN Eintrag in ``je_pilot``, auch mit null Zellen: Wer eine
    Fläche abflog, die ein anderer zuerst hatte, war trotzdem dabei (Spec 2026-09-23,
    Abschnitt 7). ``flaeche_km2`` nimmt die Kante JEDES Abends, sie ist einstellbar.
    """
    event_count = participations = gefunden = 0
    flaeche = 0.0
    dauern: list[float] = []
    for st in staende:
        if not st.get("je_pilot"):
            continue
        event_count += 1
        participations += len(st["je_pilot"])
        if st.get("gefunden"):
            gefunden += 1
        kante = float(st.get("kante_km") or 0.0)
        flaeche += (st.get("abgedeckt") or 0) * kante * kante
        if st.get("dauer_min") is not None:
            dauern.append(float(st["dauer_min"]))
    return {
        "event_count": event_count,
        "participations": participations,
        "gefunden_count": gefunden,
        "flaeche_km2": int(round(flaeche)),
        "avg_rettung_min": round(sum(dauern) / len(dauern), 1) if dauern else None,
    }
```

- [ ] **Step 3b: Endpunkt** — in `app/main.py` im Import-Block nach `    aggregate_kutter_kpis,` die Zeile `    aggregate_reddung_kpis,` ergänzen. In `get_special_events_stats`:
  - den Docstring-Anfang `"""Aggregierte Kennzahlen beider Spezial-Events (FriesenKutter + FriesenBummel) im` ersetzen durch `"""Aggregierte Kennzahlen der Spezial-Events (FriesenKutter, FriesenBummel, FriesenReddung) im`
  - die Zeile `        return {"kutter": kutter, "bummel": bummel}` ersetzen durch:

```python
        # --- FriesenReddung: dtend vorbei & im Fenster. Nichts wird nachgerechnet: Der
        # Leseweg endet bei min(dtend, aufgeloest_am), der Snapshot steht dort schon.
        r_staende = [compute_reddung_stand(conn, ev)
                     for ev in list_reddung_events(conn, since=since)
                     if (ev.get("dtend") or "") < now]
        reddung = aggregate_reddung_kpis(r_staende)

        return {"kutter": kutter, "bummel": bummel, "reddung": reddung}
```

- [ ] **Step 3c: Oberfläche** — in `renderSpecialEventStats`:
  - nach `  const b = (data && data.bummel) || {};` einfügen: `  const rd = (data && data.reddung) || {};`
  - direkt nach dem Block, der mit `      ${_kpiCard(_fmtAvgMin(b.avg_absolute_min), 'Ø Absoluter Durchschnitt')}` und `    </div>\`);` und `  }` endet, einfügen:

```js
  if ((rd.event_count || 0) > 0) {
    const quote = Math.round(100 * (rd.gefunden_count || 0) / rd.event_count);
    rows.push(`<div class="stats-kpi-row">
      ${_kpiCard(rd.event_count, '🚨 FriesenReddung')}
      ${_kpiCard(rd.participations, 'Teilnahmen')}
      ${_kpiCard(quote + ' %', 'Gefunden', `${rd.gefunden_count || 0} von ${rd.event_count}`)}
      ${_kpiCard((rd.flaeche_km2 || 0) + ' km²', 'Abgesucht')}
      ${_kpiCard(_fmtAvgMin(rd.avg_rettung_min), 'Ø Rettung')}
    </div>`);
  }
```

- [ ] **Step 3d: Doku** — in `docs/api.md` im Abschnitt `## GET /api/stats/special-events` die Zeile
``  "bummel": {race_count, participations, legs, avg_absolute_min}}`. ``
ersetzen durch

```markdown
  "bummel": {race_count, participations, legs, avg_absolute_min},
  "reddung": {event_count, participations, gefunden_count, flaeche_km2, avg_rettung_min}}`.
```

und nach der Zeile, die mit ``gewertetes Rennen. NULL-`dtend`-Events werden ausgeschlossen.`` endet (vor dem abschließenden `---`) einen Absatz einfügen:

```markdown

`reddung` zählt nur Abende, deren `dtend` vorbei ist und die mindestens einen Teilnehmer hatten. `participations` zählt auch Piloten ohne eigene Zelle; `flaeche_km2` nimmt die Zellkante jedes Abends; `avg_rettung_min` mittelt nur über Abende mit Einlieferung (sonst `null`). Nachgerechnet wird nichts — der Leseweg endet bei `min(dtend, aufgeloest_am)`.
```

In `README.md` im Abschnitt `### 📊 Statistiken` unter „**Was du siehst:**" nach dem Punkt, der mit `- **KPI-Box** oben:` beginnt, einfügen:

```markdown
- **Spezial-Events** über dem Liniendiagramm: je eine Zeile für FriesenKutter, FriesenBummel und FriesenReddung, nur für Abende, die im gewählten Zeitraum zu Ende gingen. Bei der FriesenReddung: Anzahl der Abende, Teilnahmen, wie oft der Havarist gefunden wurde, die insgesamt abgesuchte Fläche und die mittlere Dauer vom Fund bis zur Einlieferung
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_reddung_kpi.py tests/test_special_events_stats.py tests/test_database.py tests/test_readme_aktuell.py -q`
Expected: alle PASS

- [ ] **Step 5: Commit**

```bash
git add app/database.py app/main.py app/static/index.html docs/api.md README.md tests/test_reddung_kpi.py tests/test_special_events_stats.py
git commit -m "FriesenReddung: Kennzahlen in den Statistiken

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Changelog 15.18.0 und Gesamtprüfung

**Files:**
- Modify: `app/CHANGELOG.json` (neuer erster Eintrag)

- [ ] **Step 1: Changelog** — in `app/CHANGELOG.json` vor dem bisher ersten Eintrag (`"version": "15.17.0"`) einfügen, Datum = Tag der Umsetzung:

```json
  {
    "version": "15.18.0",
    "date": "2026-09-25",
    "highlight": false,
    "title": "Die FriesenReddung wird sichtbar",
    "items": [
      "🚨 **Live-Ansicht:** Läuft eine FriesenReddung, steht sie ganz oben — mit Balken, noch offener Fläche und wer gefunden, aufgenommen und eingeliefert hat.",
      "🗺️ **Karte:** Die neue Ebene **FriesenReddung** zeigt den Suchsektor und darin, was schon abgesucht ist. So seht ihr in der Luft, wo noch niemand war — auch im Kniebrett. Wo der Havarist liegt, zeigt sie nie; das tut die Rauchsäule im Simulator.",
      "📋 **Events:** Ein Klick auf die FriesenReddung öffnet ihre Bilanz, mit einem Knopf, der sie als fertigen Absatz fürs Forum kopiert. Bisher füllte der Klick das Suchformular.",
      "📊 **Statistiken:** Eine eigene Zeile für die FriesenReddung — Abende, Teilnahmen, Funde, abgesuchte Fläche und die mittlere Rettungsdauer.",
      "🔧 **Die abgesuchte Fläche hing vom Zufall ab.** Nach dem Ende eines Abends zählte die Seite weiter, der Server nicht — ob ein Flug danach mitgerechnet wurde, hing davon ab, ob gerade jemand die Seite offen hatte. Jetzt endet die Zählung für alle an derselben Stelle."
    ]
  },
```

- [ ] **Step 2: Gesamte Testsuite**

Run: `/home/claude/.venv-friesenspy/bin/python -m pytest -q -p no:cacheprovider`
Expected: alles PASS (Stand vor dieser Runde: 3361 bestanden, 1 übersprungen, plus die neuen)

- [ ] **Step 3: JSON und Modulkopf gegenprüfen**

Run: `python3 -c "import json; d=json.load(open('app/CHANGELOG.json')); print(d[0]['version'], d[0]['highlight'])"`
Expected: `15.18.0 False`

- [ ] **Step 4: Commit**

```bash
git add app/CHANGELOG.json
git commit -m "15.18.0: Die FriesenReddung wird sichtbar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Nicht pushen** — dem Nutzer melden, dass alles lokal committet ist, und nach dem Zeitpunkt für den Push fragen (Push = Deploy, zu Flugzeiten nicht).

---

### Task 9: Wo die Testsuite ihre Zeit verbringt — messen und bewerten

Auftrag des Nutzers vom 24.09.2026: *„welche Tests der kompletten Suite am meisten Zeit
brauchen und ob man sie optimieren kann."* Die Suite brauchte zuletzt **7:26 Minuten** für
3361 Tests (24.09.2026). Das ist ein **Prüfauftrag**: Ergebnis ist ein Bericht mit
Vorschlägen im Chat. **Kein Test wird in diesem Task geändert** — Tests sind Wächter, und
wer einen schneller macht, kann dabei unbemerkt ändern, was er beweist. Umgesetzt wird erst,
was der Nutzer danach freigibt.

**Files:**
- Keine Änderung im Repo. Messdaten nach `/tmp/testlauf/` (wird überschrieben, nicht gelöscht).

- [ ] **Step 1: Messen** — die volle Suite einmal mit Einzelzeiten und JUnit-Bericht:

```bash
mkdir -p /tmp/testlauf
cd /home/claude/projects/friesenspy
/home/claude/.venv-friesenspy/bin/python -m pytest -q -p no:cacheprovider \
  --durations=40 --durations-min=0.5 --junitxml=/tmp/testlauf/junit.xml \
  2>&1 | tee /tmp/testlauf/ausgabe.txt | tail -60
```

Expected: dieselbe Zahl bestandener Tests wie in Task 8, darunter die Liste der langsamsten
Einzelschritte (`setup`, `call` und `teardown` getrennt — ein langsames `setup` zeigt auf eine
teure Fixture, nicht auf den Test).

- [ ] **Step 2: Je Datei summieren** — Einzeltests täuschen, wenn eine Datei hundert mittelschnelle hat:

```bash
python3 - <<'EOF'
import xml.etree.ElementTree as ET
from collections import defaultdict
wurzel = ET.parse("/tmp/testlauf/junit.xml").getroot()
je_datei, anzahl = defaultdict(float), defaultdict(int)
gesamt = 0.0
for tc in wurzel.iter("testcase"):
    datei = tc.get("classname", "").split(".")[1] if "." in tc.get("classname", "") else tc.get("classname")
    t = float(tc.get("time") or 0)
    je_datei[datei] += t; anzahl[datei] += 1; gesamt += t
print(f"Summe {gesamt:.0f} s")
for datei, t in sorted(je_datei.items(), key=lambda x: -x[1])[:15]:
    print(f"{t:7.1f} s  {100*t/gesamt:5.1f} %  {anzahl[datei]:4d} Tests  {datei}")
EOF
```

- [ ] **Step 3: Ursachen je Spitzenreiter bestimmen** — für die obersten zehn Dateien und die
  obersten 15 Einzeltests den Quelltext lesen und die Ursache **benennen, nicht vermuten**.
  Die Kandidaten, nach denen gezielt zu suchen ist:

  | Ursache | Woran man sie erkennt | Typische Abhilfe |
  |---|---|---|
  | Echtes Warten | `time.sleep`, `asyncio.sleep`, Timeouts im Test | Uhr oder Takt injizieren statt warten |
  | Prozessstart | `subprocess.run([node …])`, je Test ein neuer Prozess | mehrere Prüfungen in einem Aufruf bündeln |
  | Datenbank je Test | `init_db` in einer Fixture mit Standard-Scope | Vorlage einmal bauen, je Test kopieren (`.backup`, nie `cp` bei WAL) |
  | Große Dateien je Test neu gelesen/geparst | `read_text` / `json.loads` in der Testfunktion statt auf Modulebene | auf Modulebene einmal lesen |
  | Bildberechnung | Pillow, Badges, Kartenblätter | kleinere Testbilder, falls das Ergebnis dasselbe beweist |
  | Netz | Aufrufe, die trotz Mock hinausgehen | Mock prüfen — das wäre ein Fehler, keine Optimierung |

  Für jeden Befund die Zeitprobe **einzeln** laufen lassen, bevor eine Ursache behauptet wird:
  `/home/claude/.venv-friesenspy/bin/python -m pytest <datei>::<test> -q --durations=0`

- [ ] **Step 4: Bewerten** — je Vorschlag festhalten:
  1. die gemessene Zeit heute und die erwartete Ersparnis (geschätzt, als Schätzung gekennzeichnet),
  2. **ob der Test danach noch dasselbe beweist** — wenn nein, kein Vorschlag, sondern eine Warnung,
  3. den Aufwand in grober Größe (eine Zeile / eine Fixture / eine Datei).

  Ausdrücklich prüfen, ob sich **Parallelisierung** lohnt (`pytest-xdist` ist im venv nicht
  installiert): Welche Tests teilen Zustand (gemeinsame Dateien, feste Pfade unter `/tmp`,
  Modul-Globals wie `main.get_settings`-Monkeypatches)? Das entscheidet, ob `-n auto` gefahrlos
  wäre, nicht die Kernzahl der Maschine.

- [ ] **Step 5: Berichten** — im Chat, nicht als Datei: die Tabelle aus Step 2, die Top 15
  aus Step 1 mit benannter Ursache, und eine **nummerierte** Liste der Vorschläge mit Ersparnis,
  Aufwand und Beweis-Vorbehalt. Dann auf die Entscheidung des Nutzers warten; nichts umsetzen.
