# Flugplatzkarten-Overlay — Implementierungsplan

> **Für agentische Bearbeiter:** ERFORDERLICHE SUB-SKILL: `superpowers:subagent-driven-development`
> (empfohlen) oder `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe umzusetzen.
> Die Schritte tragen Kästchen (`- [ ]`) zur Nachverfolgung.

**Ziel:** Die amtliche DFS-Flugplatzkarte eines Verkehrsflughafens liegt georeferenziert über
der Leaflet-Karte und erscheint von allein, sobald die eigene Position über dem Platz liegt.
Vorgeschaltet: eine von Hand gesetzte Passung wird nie wieder automatisch überschrieben.

**Architektur:** Ein neues Servermodul misst die Bahnflächen im Kartenbild, ordnet sie den
Schwellenkoordinaten von OurAirports zu und rechnet daraus eine Ähnlichkeitstransformation.
Fünf Prüfungen entscheiden, ob eine Passung gilt. Das Blatt wird genordet abgelegt, das
Frontend blendet es als `L.imageOverlay` ein und verdeckt dabei die Sichtflugkarte.

**Tech-Stack:** Python 3.11, FastAPI, SQLite (WAL), Pillow, APScheduler, Leaflet, Vanilla JS.

**Spec:** [`docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md`](../specs/2026-08-30-ground-chart-overlay-design.md)

---

## Zwei Phasen

**Phase 1 (Task 1–6) ist für sich auslieferbar** und betrifft produktive Bestandsdaten: die
171 handgepassten Sichtflugkarten. Sie schließt drei Überschreib-Lücken und weckt den
Auffrischjob, der seit seiner Einführung nie gearbeitet hat.

**Die Reihenfolge ist zwingend.** Task 6 weckt einen Job, der 446 Karten anfasst. Er darf
erst laufen, wenn die Sperre aus Task 1 steht — sonst tut er beim ersten Durchgang genau
das, was der Nutzer verboten hat.

**Phase 2 (Task 7–18)** baut die Flugplatzkarten. Sie setzt Phase 1 voraus, weil ihr
Auffrischlauf dieselbe Sperre benutzt.

---

## Globale Vorgaben

Aus Spec-Abschnitt 13. Sie gelten für **jede** Aufgabe dieses Plans:

- **Keine neue Abhängigkeit.** Pillow, httpx, airportsdata, APScheduler sind vorhanden.
  numpy, scipy und OpenCV sind es **nicht** und werden nicht hinzugefügt.
- **Echte Namen des Projekts:** `init_db(db_path: str)` nimmt einen **Pfad**, keine
  Verbindung. `get_connection(db_path: str)` — es gibt **kein** `get_conn`.
  `settings.DB_PATH` — es gibt **kein** `settings.DATEN_PFAD`. Verzeichnisse bildet man als
  `Path(settings.DB_PATH).parent / …`.
- **Es gibt kein `tests/conftest.py`.** Fixtures werden je Testdatei angelegt, die DB über
  `tmp_path` wie in `tests/test_aip_charts.py:29-35`.
- **Verbindungen:** `conn = get_connection(...)` / `try` / `finally: conn.close()`.
  `with conn` ist in sqlite3 eine **Transaktion**, kein Close.
- **Deutsche Bezeichner und Kommentare** in neuen Modulen, wie in `app/vrp.py` und
  `app/aip_charts.py`.
- **`"highlight": false`** in jedem Changelog-Eintrag. Ohne Ausnahme.
- **Kein `localStorage`** im Frontend — Merker über `_prefLies` / `_prefSchreib`.
- **Eine Karte, die eine Prüfung nicht besteht, wird nicht angezeigt.**
- Tests: `pytest tests/ -q`. Der volle Lauf dauert rund vier Minuten.
- Frontend-Tests binden an **Deklarationen**, nicht an Kommentare. Wo Quelltext auf
  Zeichenketten geprüft wird, vorher die Kommentare entfernen — sonst trifft der Test die
  eigene Erklärung statt des Codes:
  ```python
  def _ohne_kommentare(text: str) -> str:
      return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))
  ```

---

## Dateien

| Datei | Verantwortung |
|---|---|
| `app/database.py` | **Task 1:** die Sperre an einer Stelle. Dann zwei neue Tabellen. |
| `scripts/aip_bestand.py` | Task 2: Lücke im letzten Zweig |
| `app/main.py` | Task 3: Lücke im Seitenwähler. Task 15: neue Endpoints. |
| `scripts/aip_handpassung.py` | Task 2: dritter Schreibpfad, bisher unbeachtet |
| `app/poller.py` | Task 6: `next_run_time`. Task 18: zweiter Job. |
| `app/ground_charts.py` (neu) | Bildanalyse und Passung — ohne DB- und FastAPI-Bezug |
| `app/runway_ref.py` (neu) | OurAirports-Schwellen, mit Zwischenspeicher |
| `app/data/ground_chart_kopf/*.png` (neu) | Kopfmuster je Kartensorte |
| `scripts/ground_chart_bestand.py` (neu) | Erstbefüllung und Auffrischung |
| `app/static/index.html` | Task 16: Ebene, Automatik, magenta Marke |
| `app/static/admin.html` | Task 5 und 17: Vorschläge, Liste, Handpassung |
| `tests/test_handpassung_schutz.py` (neu) | **die Sperre, für beide Kartentypen** |
| `tests/test_ground_charts.py` (neu) | Bildanalyse und Prüfkette |
| `tests/test_ground_chart_api.py` (neu) | Endpoints |

---

# Phase 1 — Schutz der Handkorrektur

## Task 1: Die Sperre an einer Stelle

Heute gibt es **sieben** Schreibpfade auf `aip_charts`. Zwei davon überschreiben eine
Handpassung, ein dritter (`scripts/aip_handpassung.py:369`) war beim Schreiben der Spec noch
nicht bekannt. Eine Prüfung an jeder Aufrufstelle würde auseinanderlaufen; sie kommt deshalb
in `upsert_aip_chart` selbst.

**Dateien:**
- Ändern: `app/database.py:6531` (`upsert_aip_chart`)
- Test: `tests/test_handpassung_schutz.py` (neu)

**Schnittstellen:**
- Produziert: `upsert_aip_chart(conn, icao, *, hand_ueberschreiben: bool = False, **felder) -> str`
  — wirft `HandpassungGesperrt`, wenn die bestehende Zeile `quelle == "hand"` trägt und der
  neue Wert nicht ebenfalls `"hand"` ist.
- Produziert: `class HandpassungGesperrt(Exception)` in `app/database.py`.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_handpassung_schutz.py
"""Eine von Hand gesetzte Passung darf nie automatisch ueberschrieben werden.

Festlegung des Nutzers vom 30.08.2026:
    "Eine manuell durchgefuehrte Korrektur darf nicht einfach ueberschrieben werden! Wenn es
    eine neue Version gibt, kann diese zur Pruefung angezeigt werden. Aber keinesfalls
    erneut verzerrt werden!"

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md, Abschnitt 7
"""
from __future__ import annotations

import pytest

from app.database import (
    HandpassungGesperrt, get_aip_chart, get_connection, init_db, upsert_aip_chart,
)

BOUNDS = dict(nord=54.24, sued=54.19, west=9.55, ost=9.65,
              feld_nord=54.235, feld_sued=54.195, feld_west=9.56, feld_ost=9.64)
GEO = dict(rahmen_px="132,180,817,865", tick_px_lat=219.0, tick_px_lon=128.4)
# Eine Handpassung legt Nullen in den Rasterfeldern ab -- siehe aip_charts.handpassung().
# Genau deshalb kann geometrie_gleich() sie nie erkennen; das war die zweite Luecke.
GEO_HAND = dict(rahmen_px="132,180,817,865", tick_px_lat=0.0, tick_px_lon=0.0)


@pytest.fixture()
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    c = get_connection(db)
    yield c
    c.close()


def _hand(conn, icao="EDDL", **abweichend):
    werte = {**BOUNDS, **GEO_HAND, "bild_hash": "a" * 64, "quelle": "hand",
             "airac": "2026AUG20", "status": "gepasst", **abweichend}
    return upsert_aip_chart(conn, icao, **werte)


def test_automatik_darf_handpassung_nicht_ueberschreiben(conn):
    _hand(conn)
    with pytest.raises(HandpassungGesperrt):
        upsert_aip_chart(conn, "EDDL", bild_hash="b" * 64, **{**BOUNDS, "nord": 55.0},
                         **GEO, quelle="auto", airac="2026SEP17", status="gepasst")
    assert get_aip_chart(conn, "EDDL")["nord"] == pytest.approx(54.24)
    assert get_aip_chart(conn, "EDDL")["quelle"] == "hand"


def test_eine_neue_handpassung_darf_die_alte_ersetzen(conn):
    """Der Mensch korrigiert sich selbst -- das ist kein automatisches Ueberschreiben."""
    _hand(conn)
    _hand(conn, **{**BOUNDS, "nord": 55.0})
    assert get_aip_chart(conn, "EDDL")["nord"] == pytest.approx(55.0)


def test_bildauffrischung_unter_bestehender_handpassung_bleibt_erlaubt(conn):
    """Regel 4 aus scripts/aip_bestand.py: Das BILD darf nachgezogen werden, solange die
    Passung selbst unveraendert bleibt und quelle='hand' mitgeschrieben wird."""
    _hand(conn)
    _hand(conn, bild_hash="c" * 64, airac="2026SEP17")
    k = get_aip_chart(conn, "EDDL")
    assert k["bild_hash"] == "c" * 64 and k["quelle"] == "hand"
    assert k["nord"] == pytest.approx(54.24)


def test_ausdrueckliches_ueberschreiben_ist_moeglich(conn):
    """Der Admin uebernimmt einen Vorschlag -- ein Handgriff, kein Automatismus."""
    _hand(conn)
    upsert_aip_chart(conn, "EDDL", bild_hash="b" * 64, **{**BOUNDS, "nord": 55.0}, **GEO,
                     quelle="auto", airac="2026SEP17", status="gepasst",
                     hand_ueberschreiben=True)
    assert get_aip_chart(conn, "EDDL")["nord"] == pytest.approx(55.0)


def test_ohne_bestehende_zeile_greift_die_sperre_nicht(conn):
    upsert_aip_chart(conn, "EDWJ", bild_hash="a" * 64, **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="gepasst")
    assert get_aip_chart(conn, "EDWJ")["quelle"] == "auto"


def test_auto_darf_auto_ueberschreiben(conn):
    upsert_aip_chart(conn, "EDWJ", bild_hash="a" * 64, **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="gepasst")
    upsert_aip_chart(conn, "EDWJ", bild_hash="b" * 64, **{**BOUNDS, "nord": 55.0}, **GEO,
                     quelle="auto", airac="y", status="gepasst")
    assert get_aip_chart(conn, "EDWJ")["nord"] == pytest.approx(55.0)


def test_ungepasste_handzeile_sperrt_nicht(conn):
    """Nur eine gueltige Handpassung ist schuetzenswert. Eine Zeile mit status='ungepasst'
    traegt keine Arbeit, die verloren gehen koennte."""
    _hand(conn, status="ungepasst")
    upsert_aip_chart(conn, "EDDL", bild_hash="b" * 64, **BOUNDS, **GEO,
                     quelle="auto", airac="y", status="gepasst")
    assert get_aip_chart(conn, "EDDL")["quelle"] == "auto"
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag prüfen**

Aufruf: `pytest tests/test_handpassung_schutz.py -v`
Erwartet: `ImportError: cannot import name 'HandpassungGesperrt' from 'app.database'`

- [ ] **Schritt 3: Sperre einbauen**

In `app/database.py`, direkt vor `upsert_aip_chart` (Zeile 6531):

```python
class HandpassungGesperrt(Exception):
    """Versuch, eine von Hand gesetzte Passung automatisch zu ueberschreiben.

    Die Sperre sitzt hier und nicht bei den Aufrufern, weil es sieben Schreibpfade auf
    ``aip_charts`` gibt (Stand 30.08.2026: drei in scripts/aip_bestand.py, zwei in
    app/main.py, einer in scripts/aip_handpassung.py, dazu die Tests). Zwei davon haben
    Handpassungen ueberschrieben, ein dritter war beim Schreiben der Spec nicht einmal
    bekannt. Eine Pruefung an jeder Aufrufstelle waere schon beim naechsten neuen Pfad
    wieder unvollstaendig.
    """
```

Und in `upsert_aip_chart` als erste Anweisung nach der Pflichtfeldpruefung:

```python
def upsert_aip_chart(conn: sqlite3.Connection, icao: str, *,
                     hand_ueberschreiben: bool = False, **felder) -> str:
    """Kartenpassung setzen/aktualisieren. Alle Felder aus _AIP_FELDER sind Pflicht.

    **Eine bestehende Handpassung ist gesperrt.** Wer sie ersetzen will, schreibt entweder
    selbst ``quelle="hand"`` (ein Mensch korrigiert sich) oder setzt ausdruecklich
    ``hand_ueberschreiben=True`` (der Admin uebernimmt einen Vorschlag). Alles andere wirft
    ``HandpassungGesperrt``. Siehe die Spec vom 30.08.2026, Abschnitt 7.
    """
    code = (icao or "").strip().upper()
    fehlt = [f for f in _AIP_FELDER if f not in felder]
    if fehlt:
        raise ValueError(f"Pflichtfelder fehlen: {', '.join(fehlt)}")
    if not hand_ueberschreiben and felder.get("quelle") != "hand":
        alt = conn.execute(
            "SELECT quelle, status FROM aip_charts WHERE icao = ?", (code,)).fetchone()
        # Nur eine GUELTIGE Handpassung ist schuetzenswert -- eine Zeile mit
        # status='ungepasst' traegt keine Arbeit, die verloren gehen koennte.
        if alt is not None and alt["quelle"] == "hand" and alt["status"] == "gepasst":
            raise HandpassungGesperrt(
                f"{code}: Handpassung wird nicht automatisch ueberschrieben")
    platz = ", ".join("?" * len(_AIP_SPALTEN))
    setzen = ", ".join(f"{f}=excluded.{f}" for f in (*_AIP_FELDER, "geprueft_am"))
    conn.execute(
        f"""INSERT INTO aip_charts ({', '.join(_AIP_SPALTEN)}) VALUES ({platz})
            ON CONFLICT(icao) DO UPDATE SET {setzen}""",
        (code, *(felder[f] for f in _AIP_FELDER), _now_utc()),
    )
    return code
```

- [ ] **Schritt 4: Test laufen lassen**

Aufruf: `pytest tests/test_handpassung_schutz.py -v`
Erwartet: 7 PASS

- [ ] **Schritt 5: Den gesamten Bestand prüfen**

Aufruf: `pytest tests/ -q`
Erwartet: Fehlschläge in `tests/test_aip_charts.py` und `tests/test_aip_api.py`, wo bisher
eine Handpassung überschrieben wurde. **Diese Tests sind jetzt falsch** — sie beschreiben
das Verhalten, das gerade verboten wurde. Insbesondere
`test_handpassung_ueberschreibt_und_bleibt_erkennbar` in `tests/test_aip_charts.py:52` prüft
die umgekehrte Richtung (auto → hand) und muss **unverändert bestehen bleiben**; prüfe das,
statt ihn blind anzupassen.

- [ ] **Schritt 6: Betroffene Bestandstests nachziehen**

Jeden Fehlschlag einzeln ansehen. Wo ein Test eine Handpassung durch eine Automatikpassung
ersetzt, ist entweder `hand_ueberschreiben=True` zu ergänzen (wenn der Test die
Admin-Übernahme meint) oder `pytest.raises(HandpassungGesperrt)` zu erwarten (wenn er den
Auffrischlauf meint). **Keinen Test löschen.**

- [ ] **Schritt 7: Commit**

```bash
git add app/database.py tests/test_handpassung_schutz.py tests/test_aip_charts.py tests/test_aip_api.py
git commit -m "Handpassung ist eine Sperre, kein Vermerk

Sieben Schreibpfade auf aip_charts, zwei davon haben Handpassungen
ueberschrieben. Die Pruefung sitzt deshalb in upsert_aip_chart selbst.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Die Lücke im Auffrischlauf

**Dateien:**
- Ändern: `scripts/aip_bestand.py:213` (letzter Zweig)
- Ändern: `scripts/aip_handpassung.py:369` (dritter Schreibpfad, prüfen und belegen)
- Test: `tests/test_handpassung_schutz.py` (erweitern)

**Schnittstellen:**
- Konsumiert: `HandpassungGesperrt` aus Task 1.
- Produziert: `lauf()` liefert zusätzlich den Zähler `hand_gesperrt` und die Liste
  `vorschlag_faellig` (ICAO-Codes, für die die Automatik ein abweichendes Ergebnis hatte).

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

Ans Ende von `tests/test_handpassung_schutz.py`:

```python
def test_auffrischlauf_faengt_die_sperre_und_meldet_sie(conn, monkeypatch, tmp_path):
    """Der Lauf darf an einer gesperrten Karte nicht abbrechen -- er zaehlt sie und macht
    weiter. Eine Ausnahme mitten im Durchgang liesse die restlichen 400 Karten liegen."""
    import scripts.aip_bestand as bestand

    _hand(conn, icao="EDDL")
    conn.commit()
    zaehler = {}
    faellig = []
    bestand._karte_schreiben(conn, "EDDL", zaehler, faellig,
                             bild_hash="b" * 64, **{**BOUNDS, "nord": 55.0}, **GEO,
                             quelle="auto", airac="y", status="gepasst")
    assert zaehler.get("hand_gesperrt") == 1
    assert faellig == ["EDDL"]
    assert get_aip_chart(conn, "EDDL")["nord"] == pytest.approx(54.24)
```

- [ ] **Schritt 2: Test laufen lassen**

Aufruf: `pytest tests/test_handpassung_schutz.py::test_auffrischlauf_faengt_die_sperre_und_meldet_sie -v`
Erwartet: `AttributeError: module 'scripts.aip_bestand' has no attribute '_karte_schreiben'`

- [ ] **Schritt 3: Schreibhelfer einführen**

In `scripts/aip_bestand.py`, vor `lauf()`:

```python
def _karte_schreiben(conn, icao: str, zaehler, vorschlag_faellig: list, **felder) -> bool:
    """Passung ablegen und eine gesperrte Handpassung sauber abfangen.

    Der Lauf darf an einer gesperrten Karte nicht abbrechen: Eine Ausnahme mitten im
    Durchgang liesse die restlichen Karten liegen, und der naechste Lauf faengt wieder von
    vorn an. Gemeldet wird sie stattdessen -- ihr Fund wird in Task 4 zum Vorschlag.
    """
    try:
        upsert_aip_chart(conn, icao, **felder)
        return True
    except HandpassungGesperrt:
        logger.info("%s: Handpassung gilt, Automatikergebnis wird nur vorgeschlagen", icao)
        zaehler["hand_gesperrt"] += 1
        vorschlag_faellig.append(icao)
        return False
```

Import ergänzen: `from app.database import HandpassungGesperrt` in der bestehenden
Importliste ab Zeile 40.

- [ ] **Schritt 4: Den letzten Zweig umstellen**

`scripts/aip_bestand.py:213` — der Aufruf, der bisher bedingungslos `quelle="auto"` schrieb.
Wichtig: **`blatt_schreiben` darf erst danach laufen**, sonst liegt das neue Bild unter der
alten Handpassung und die Karte ist verzerrt. Genau davor hat der Nutzer gewarnt.

```python
                geschrieben = _karte_schreiben(
                    conn, icao, zaehler, vorschlag_faellig, bild_hash=neuer_hash,
                    nord=passung.nord, sued=passung.sued,
                    west=passung.west, ost=passung.ost,
                    feld_nord=passung.feld_nord, feld_sued=passung.feld_sued,
                    feld_west=passung.feld_west, feld_ost=passung.feld_ost,
                    rahmen_px=passung.rahmen_px,
                    tick_px_lat=passung.tick_px_lat, tick_px_lon=passung.tick_px_lon,
                    quelle="auto", airac=airac or "", status="gepasst")
                if not geschrieben:
                    continue          # Bild NICHT anfassen -- es gehoert nicht zur Passung
                aip_charts.blatt_schreiben(aip_charts.blatt_pfad(einst.DB_PATH, icao), roh)
                zaehler["gepasst"] += 1
```

Die übrigen `upsert_aip_chart`-Aufrufe in derselben Datei (Zeile 123, 185, 202) schreiben
`quelle=alt["quelle"]` beziehungsweise legen eine neue Zeile an — sie laufen nicht in die
Sperre. **Das ist zu belegen, nicht zu vermuten:** Lies jeden der drei Aufrufe und halte in
einem Kommentar fest, warum er unbedenklich ist.

- [ ] **Schritt 5: `lauf()` gibt die neue Liste zurück**

`vorschlag_faellig: list[str] = []` neben `nachsehen` anlegen und in den Rückgabewert
aufnehmen: `"vorschlag_faellig": sorted(vorschlag_faellig)`.

- [ ] **Schritt 6: Den dritten Schreibpfad prüfen**

`scripts/aip_handpassung.py:369` schreibt ebenfalls in `aip_charts`. Lies das Skript und
stelle fest, ob es `quelle="hand"` setzt. Falls ja: Es läuft nicht in die Sperre, halte das
in einem Kommentar fest. Falls nein: Es ist ein vierter Überschreib-Pfad — dann gehört
`quelle="hand"` dorthin, denn ein Skript namens `aip_handpassung` setzt Handpassungen.

- [ ] **Schritt 7: Tests laufen lassen**

Aufruf: `pytest tests/test_handpassung_schutz.py tests/test_aip_charts.py -v`
Erwartet: alle PASS

- [ ] **Schritt 8: Commit**

```bash
git add scripts/aip_bestand.py scripts/aip_handpassung.py tests/test_handpassung_schutz.py
git commit -m "Auffrischlauf laesst Handpassungen stehen und meldet sie

Der letzte Zweig schrieb bedingungslos quelle=auto. Die Sicherung davor
(geometrie_gleich) konnte nie greifen: handpassung() legt Nullen in
tick_px_lat/lon ab, verglichen wurde gegen gemessene ~219.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Die Lücke im Seitenwähler

**Dateien:**
- Ändern: `app/main.py:4399` (in `admin_aip_seite_waehlen`)
- Test: `tests/test_aip_api.py` (erweitern)

**Schnittstellen:**
- Konsumiert: `HandpassungGesperrt` aus Task 1.
- Produziert: Antwort um das Feld `vorschlag` erweitert (bool) — Task 4 füllt es.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

Ans Ende von `tests/test_aip_api.py`:

```python
def test_seitenwahl_loescht_keine_handpassung(client, db_pfad):
    """Die bisherige Sicherung hing an `passung is None`. Liefert die Automatik auf der
    gewaehlten Seite ein Ergebnis, war die Handpassung weg -- auch bei unveraendertem Bild.
    """
    conn = get_connection(db_pfad)
    try:
        upsert_aip_chart(conn, "EDDL", bild_hash="a" * 64, **BOUNDS,
                         rahmen_px="10,10,800,800", tick_px_lat=0.0, tick_px_lon=0.0,
                         quelle="hand", airac="2026AUG20", status="gepasst")
        conn.commit()
    finally:
        conn.close()
    antwort = client.post("/api/admin/aip-charts/EDDL/seite",
                          json={"url": "https://aip.dfs.de/BasicVFR/2026AUG20/pages/x.html"},
                          cookies=ADMIN_COOKIE)
    assert antwort.status_code in (200, 422)
    conn = get_connection(db_pfad)
    try:
        assert get_aip_chart(conn, "EDDL")["quelle"] == "hand"
    finally:
        conn.close()
```

- [ ] **Schritt 2: Test laufen lassen**

Aufruf: `pytest tests/test_aip_api.py::test_seitenwahl_loescht_keine_handpassung -v`
Erwartet: FAIL — `quelle` ist `auto`

- [ ] **Schritt 3: Den Aufruf absichern**

In `app/main.py`, die `upsert_aip_chart`-Anweisung ab Zeile 4399 umschließen:

```python
            try:
                upsert_aip_chart(conn, code, bild_hash=neuer_hash,
                                 quelle="auto" if passung else "hand", airac=airac,
                                 status="gepasst" if passung else "ungepasst", **werte)
            except HandpassungGesperrt:
                # Die bisherige Sicherung hing an `passung is None` und griff deshalb
                # nicht, wenn die Automatik auf der gewaehlten Seite ein Ergebnis lieferte.
                # Das Bild wurde oben bereits geschrieben -- das ist hier richtig, denn der
                # Admin hat diese Seite ausdruecklich gewaehlt; falsch waere nur, die
                # Passung mitzuziehen.
                conn.rollback()
                return {"status": "ok", "gepasst": True, "hand_behalten": True,
                        "vorschlag": True}
            conn.commit()
```

Import ergänzen: `HandpassungGesperrt` in die Importliste bei `app/main.py:141`.

- [ ] **Schritt 4: Test laufen lassen**

Aufruf: `pytest tests/test_aip_api.py -v`
Erwartet: alle PASS

- [ ] **Schritt 5: Commit**

```bash
git add app/main.py tests/test_aip_api.py
git commit -m "Seitenwahl loescht keine Handpassung mehr

Die Sicherung hing an 'passung is None'. Lieferte die Automatik auf der
gewaehlten Seite ein Ergebnis, war die Handpassung weg.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Vorschlagstabelle

**Dateien:**
- Ändern: `app/database.py` (Schema hinter `aip_charts`, Zeile 348 ff.)
- Test: `tests/test_handpassung_schutz.py` (erweitern)

**Schnittstellen:**
- Produziert: `vorschlag_anlegen(conn, art, icao, quell_hash, passung: dict, grund) -> int`,
  `get_vorschlaege(conn, art=None) -> list[dict]`,
  `vorschlag_loeschen(conn, id_: int) -> int`.
  `passung` wird als JSON abgelegt, weil die Form je nach `art` verschieden ist.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_vorschlag_wird_je_blatt_nur_einmal_abgelegt(conn):
    """Ohne das erschiene derselbe Fund bei jedem Wochenlauf erneut in der Liste."""
    from app.database import get_vorschlaege, vorschlag_anlegen, vorschlag_loeschen
    a = vorschlag_anlegen(conn, "sichtflug", "EDDL", "h1", {"nord": 55.0}, "Automatik weicht ab")
    b = vorschlag_anlegen(conn, "sichtflug", "EDDL", "h1", {"nord": 55.0}, "Automatik weicht ab")
    assert a == b
    assert len(get_vorschlaege(conn)) == 1
    # Ein NEUES Blatt ist ein neuer Vorschlag.
    vorschlag_anlegen(conn, "sichtflug", "EDDL", "h2", {"nord": 56.0}, "Automatik weicht ab")
    assert len(get_vorschlaege(conn)) == 2
    assert len(get_vorschlaege(conn, art="ground")) == 0
    assert vorschlag_loeschen(conn, a) == 1


def test_vorschlag_gibt_die_passung_als_dict_zurueck(conn):
    """Der Admin muss die vorgeschlagenen Werte anzeigen koennen, ohne JSON zu parsen."""
    from app.database import get_vorschlaege, vorschlag_anlegen
    vorschlag_anlegen(conn, "ground", "EDDM", "h1", {"drehung": 353.5, "mps": 2.576}, "neu")
    v = get_vorschlaege(conn, art="ground")[0]
    assert v["passung"]["drehung"] == pytest.approx(353.5)
```

- [ ] **Schritt 2: Test laufen lassen**

Erwartet: `ImportError: cannot import name 'vorschlag_anlegen'`

- [ ] **Schritt 3: Schema und Funktionen ergänzen**

In `app/database.py`, hinter der Tabelle `aip_charts`:

```sql
CREATE TABLE IF NOT EXISTS aip_chart_vorschlaege (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    art           TEXT NOT NULL,        -- 'sichtflug' oder 'ground'
    icao          TEXT NOT NULL,
    quell_hash    TEXT NOT NULL,        -- welches Rohblatt der Vorschlag betrifft
    passung       TEXT NOT NULL,        -- JSON; die Form haengt an 'art'
    grund         TEXT NOT NULL,
    gefunden_am   TEXT NOT NULL,
    UNIQUE(art, icao, quell_hash)
);
```

```python
def vorschlag_anlegen(conn: sqlite3.Connection, art: str, icao: str, quell_hash: str,
                      passung: dict, grund: str) -> int:
    """Automatikergebnis zu einer gesperrten Handpassung ablegen, statt sie zu ueberschreiben.

    ``UNIQUE(art, icao, quell_hash)`` haelt die Liste kurz: Solange dasselbe Rohblatt
    vorliegt, erscheint der Fund einmal und nicht bei jedem Wochenlauf erneut.
    """
    code = (icao or "").strip().upper()
    conn.execute(
        """INSERT INTO aip_chart_vorschlaege (art, icao, quell_hash, passung, grund,
                                              gefunden_am)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(art, icao, quell_hash) DO NOTHING""",
        (art, code, quell_hash, json.dumps(passung, sort_keys=True), grund, _now_utc()))
    zeile = conn.execute(
        "SELECT id FROM aip_chart_vorschlaege WHERE art=? AND icao=? AND quell_hash=?",
        (art, code, quell_hash)).fetchone()
    return int(zeile["id"])


def get_vorschlaege(conn: sqlite3.Connection, art: str | None = None) -> list[dict]:
    wo = "WHERE art = ?" if art else ""
    rows = conn.execute(
        f"""SELECT id, art, icao, quell_hash, passung, grund, gefunden_am
            FROM aip_chart_vorschlaege {wo} ORDER BY gefunden_am DESC, icao""",
        (art,) if art else ()).fetchall()
    aus = []
    for r in rows:
        d = dict(r)
        try:
            d["passung"] = json.loads(d["passung"])
        except (TypeError, ValueError):
            d["passung"] = {}
        aus.append(d)
    return aus


def vorschlag_loeschen(conn: sqlite3.Connection, id_: int) -> int:
    return conn.execute(
        "DELETE FROM aip_chart_vorschlaege WHERE id = ?", (int(id_),)).rowcount
```

`import json` steht in `app/database.py` bereits — prüfen, nicht doppelt ergänzen.

- [ ] **Schritt 4: Test laufen lassen**

Aufruf: `pytest tests/test_handpassung_schutz.py -v` — alle PASS

- [ ] **Schritt 5: Den Auffrischlauf Vorschläge anlegen lassen**

In `scripts/aip_bestand.py`, in `_karte_schreiben` im `except`-Zweig, vor dem `return False`:

```python
        vorschlag_anlegen(conn, "sichtflug", icao, felder.get("bild_hash", ""),
                          {k: felder[k] for k in ("nord", "sued", "west", "ost",
                                                  "feld_nord", "feld_sued", "feld_west",
                                                  "feld_ost", "rahmen_px", "airac")
                           if k in felder},
                          "Automatik weicht von der Handpassung ab")
```

- [ ] **Schritt 6: Commit**

```bash
git add app/database.py scripts/aip_bestand.py tests/test_handpassung_schutz.py
git commit -m "Automatikfunde zu Handpassungen werden vorgeschlagen, nicht eingespielt

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Vorschläge im Admin

**Dateien:**
- Ändern: `app/main.py` (drei Endpoints, bei den übrigen Admin-AIP-Routen ab Zeile 4177)
- Ändern: `app/static/admin.html`
- Test: `tests/test_aip_api.py`

**Schnittstellen:**
- Konsumiert: `get_vorschlaege`, `vorschlag_loeschen` aus Task 4.
- Produziert: `GET /api/admin/aip-vorschlaege`,
  `POST /api/admin/aip-vorschlaege/{id}/uebernehmen`,
  `DELETE /api/admin/aip-vorschlaege/{id}`.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_vorschlag_uebernehmen_setzt_die_passung(client, db_pfad):
    from app.database import get_aip_chart, get_connection, vorschlag_anlegen
    conn = get_connection(db_pfad)
    try:
        upsert_aip_chart(conn, "EDDL", bild_hash="a" * 64, **BOUNDS,
                         rahmen_px="10,10,800,800", tick_px_lat=0.0, tick_px_lon=0.0,
                         quelle="hand", airac="2026AUG20", status="gepasst")
        vid = vorschlag_anlegen(conn, "sichtflug", "EDDL", "b" * 64,
                                {**BOUNDS, "nord": 55.0, "rahmen_px": "1,1,2,2",
                                 "airac": "2026SEP17"}, "Automatik weicht ab")
        conn.commit()
    finally:
        conn.close()
    assert client.post(f"/api/admin/aip-vorschlaege/{vid}/uebernehmen",
                       cookies=ADMIN_COOKIE).status_code == 200
    conn = get_connection(db_pfad)
    try:
        assert get_aip_chart(conn, "EDDL")["nord"] == pytest.approx(55.0)
    finally:
        conn.close()


def test_vorschlag_verwerfen_laesst_die_passung_stehen(client, db_pfad):
    from app.database import get_aip_chart, get_connection, vorschlag_anlegen
    conn = get_connection(db_pfad)
    try:
        upsert_aip_chart(conn, "EDDL", bild_hash="a" * 64, **BOUNDS,
                         rahmen_px="10,10,800,800", tick_px_lat=0.0, tick_px_lon=0.0,
                         quelle="hand", airac="2026AUG20", status="gepasst")
        vid = vorschlag_anlegen(conn, "sichtflug", "EDDL", "b" * 64,
                                {**BOUNDS, "nord": 55.0}, "Automatik weicht ab")
        conn.commit()
    finally:
        conn.close()
    assert client.delete(f"/api/admin/aip-vorschlaege/{vid}",
                         cookies=ADMIN_COOKIE).status_code == 200
    conn = get_connection(db_pfad)
    try:
        k = get_aip_chart(conn, "EDDL")
        assert k["nord"] == pytest.approx(54.24) and k["quelle"] == "hand"
    finally:
        conn.close()
```

- [ ] **Schritt 2: Test laufen lassen** — Erwartet: 404 statt 200

- [ ] **Schritt 3: Endpoints ergänzen**

```python
@app.get("/api/admin/aip-vorschlaege")
async def admin_get_aip_vorschlaege(request: Request):
    """Offene Vorschlaege beider Kartentypen -- Funde der Automatik zu handgepassten Karten."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        return {"vorschlaege": get_vorschlaege(conn)}
    finally:
        conn.close()


@app.post("/api/admin/aip-vorschlaege/{vid}/uebernehmen")
async def admin_aip_vorschlag_uebernehmen(vid: int, request: Request):
    """Einen Vorschlag zur gueltigen Passung machen. Der ausdrueckliche Handgriff aus
    Abschnitt 7.3 der Spec -- nur er darf ``hand_ueberschreiben=True`` setzen."""
    require_admin(request)
    einst = get_settings()
    conn = get_connection(einst.DB_PATH)
    try:
        treffer = [v for v in get_vorschlaege(conn) if v["id"] == vid]
        if not treffer:
            raise HTTPException(status_code=404, detail="unbekannter Vorschlag")
        v = treffer[0]
        if v["art"] != "sichtflug":
            raise HTTPException(status_code=400, detail="nur Sichtflugkarten, siehe Task 17")
        p = v["passung"]
        upsert_aip_chart(conn, v["icao"], bild_hash=v["quell_hash"],
                         nord=p["nord"], sued=p["sued"], west=p["west"], ost=p["ost"],
                         feld_nord=p["feld_nord"], feld_sued=p["feld_sued"],
                         feld_west=p["feld_west"], feld_ost=p["feld_ost"],
                         rahmen_px=p.get("rahmen_px", ""),
                         tick_px_lat=p.get("tick_px_lat", 0.0),
                         tick_px_lon=p.get("tick_px_lon", 0.0),
                         quelle="auto", airac=p.get("airac", ""), status="gepasst",
                         hand_ueberschreiben=True)
        # Das vorgeschlagene Blatt wird zum gueltigen. Erst jetzt -- vorher lag es
        # bewusst daneben, damit die alte Passung nicht auf einem neuen Bild sass.
        vorschlag_bild = Path(einst.DB_PATH).parent / "aip" / f"{v['icao']}.vorschlag.png"
        if vorschlag_bild.is_file():
            os.replace(vorschlag_bild, aip_charts.blatt_pfad(einst.DB_PATH, v["icao"]))
        vorschlag_loeschen(conn, vid)
        conn.commit()
    finally:
        conn.close()
    _aip_karten_geaendert(request)
    return {"status": "ok"}


@app.delete("/api/admin/aip-vorschlaege/{vid}")
async def admin_aip_vorschlag_verwerfen(vid: int, request: Request):
    """Vorschlag verwerfen. Die bestehende Passung bleibt unberuehrt."""
    require_admin(request)
    einst = get_settings()
    conn = get_connection(einst.DB_PATH)
    try:
        treffer = [v for v in get_vorschlaege(conn) if v["id"] == vid]
        if treffer:
            (Path(einst.DB_PATH).parent / "aip"
             / f"{treffer[0]['icao']}.vorschlag.png").unlink(missing_ok=True)
        n = vorschlag_loeschen(conn, vid)
        conn.commit()
    finally:
        conn.close()
    if not n:
        raise HTTPException(status_code=404, detail="unbekannter Vorschlag")
    return {"status": "ok"}
```

- [ ] **Schritt 4: Test laufen lassen** — alle PASS

- [ ] **Schritt 5: Admin-Oberfläche**

In `app/static/admin.html` einen Abschnitt „Vorschläge" über der Kartenliste. Er zeigt je
Zeile ICAO, Art, Grund, Funddatum und zwei Schaltflächen. Solange keine Vorschläge offen
sind, bleibt der Abschnitt **ganz verborgen** — eine dauerhaft leere Überschrift ist ein
Reiz, den niemand braucht.

Beide Blätter nebeneinander: `<img src="/aip-chart/{icao}.png">` und
`<img src="/aip-chart/{icao}.png?vorschlag=1">`. Dafür bekommt `aip_chart_bild` einen
Abfrageparameter, der auf `<ICAO>.vorschlag.png` zeigt.

- [ ] **Schritt 6: Commit**

```bash
git add app/main.py app/static/admin.html tests/test_aip_api.py
git commit -m "Vorschlaege im Admin: uebernehmen oder verwerfen

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Den Auffrischjob wecken

**Erst jetzt.** Der Job fasst 446 Karten an; ohne Task 1 bis 5 täte er beim ersten Durchgang
genau das, was verboten wurde.

**Dateien:**
- Ändern: `app/poller.py:553`
- Test: `tests/test_poller_jobs.py` (neu, falls nicht vorhanden — sonst erweitern)

**Schnittstellen:**
- Produziert: keine neuen. Der Job behält Namen und Kennung `aip_auffrischen`.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_aip_job_laeuft_kurz_nach_dem_start_zum_ersten_mal():
    """`interval` ohne `next_run_time` plant den ersten Lauf eine Woche nach dem Anmelden --
    und angemeldet wird bei jedem Containerstart neu. FriesenSpy wird deutlich haeufiger als
    woechentlich deployt; der Job hat deshalb seit seiner Einfuehrung nie gearbeitet.

    Belegt am Bestand (30.08.2026): Von 446 Karten trug keine ein geprueft_am nach dem
    25.08., ausser der einen, die von Hand gepasst wurde. Ein Durchlauf haette alle 446
    angefasst.
    """
    import inspect
    from app import poller
    quelle = inspect.getsource(poller.VatsimPoller)
    stelle = quelle.index('id="aip_auffrischen"')
    ausschnitt = quelle[max(0, stelle - 400):stelle]
    assert "next_run_time" in ausschnitt
```

- [ ] **Schritt 2: Test laufen lassen** — Erwartet: FAIL

- [ ] **Schritt 3: `next_run_time` setzen**

```python
        # AIP-Sichtflugkarten woechentlich auffrischen. NICHT monatlich: Der AIRAC-Zyklus
        # ist 28 Tage lang, ein Monatsjob wuerde frueher oder spaeter eine Ausgabe
        # ueberspringen. Arbeit faellt ohnehin nur an, wenn sich ein bild_hash geaendert hat.
        #
        # `next_run_time` ist nicht schmueckend: Ohne die Angabe plant APScheduler den
        # ERSTEN Lauf eine Woche nach dem Anmelden, und angemeldet wird bei jedem
        # Containerstart neu. Zwischen zwei Deploys liegt hier selten eine Woche -- der Job
        # hat von seiner Einfuehrung bis zum 30.08.2026 kein einziges Mal gearbeitet.
        # Fuenf Minuten Verzug, damit der Start nicht mit dem Warmlauf des flight_cache
        # zusammenfaellt.
        self._scheduler.add_job(
            self._aip_auffrischen, "interval", weeks=1, id="aip_auffrischen",
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
```

Prüfen, ob `datetime`, `timezone` und `timedelta` in `app/poller.py` importiert sind.

- [ ] **Schritt 4: Test laufen lassen** — PASS

- [ ] **Schritt 5: Den ersten Lauf beobachten**

**Nicht überspringen.** Nach dem Deploy im Log nachsehen:

```bash
docker logs friesenspy-friesenspy-1 2>&1 | grep -i "AIP-Karten"
```

Erwartet: eine Zeile „AIP-Karten aufgefrischt: N von 446 gepasst". Steht dort ein
`hand_gesperrt` größer null, prüfe im Admin, ob die Vorschläge sinnvoll aussehen — das ist
die Gegenprobe auf Task 1 bis 5 an echten Daten.

- [ ] **Schritt 6: Commit**

```bash
git add app/poller.py tests/test_poller_jobs.py
git commit -m "AIP-Auffrischjob laeuft ueberhaupt erst

interval ohne next_run_time plant den ersten Lauf eine Woche nach dem
Anmelden -- und angemeldet wird bei jedem Containerstart neu.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

# Phase 2 — Flugplatzkarten

## Task 7: Bahnschwellen von OurAirports

**Dateien:**
- Erstellen: `app/runway_ref.py`
- Test: `tests/test_runway_ref.py` (neu)

**Schnittstellen:**
- Produziert: `bahnen(icao: str) -> list[Bahn]` mit
  `Bahn = namedtuple("Bahn", "name le he laenge kurs")`; `le`/`he` sind `(lat, lon)`,
  `laenge` in Metern, `kurs` rechtweisend in Grad.
- Produziert: `datei_holen(ziel: Path, hole=None) -> Path` — lädt `runways.csv`, wenn die
  Ablage älter als 30 Tage ist.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_runway_ref.py
"""Bahnschwellen als Referenz fuer die Flugplatzkarten-Passung.

OpenAIP scheidet aus: Es liefert keine Schwellenkoordinaten, sondern nur trueHeading -- fuer
EDDL den Wert 50 bei tatsaechlich 052,7 Grad. Drei Grad sind auf 3 km 150 m.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md, Abschnitt 5.1
"""
from __future__ import annotations

import math

import pytest

from app import runway_ref

# Zwei echte Zeilen aus runways.csv, gekuerzt auf die benutzten Spalten.
CSV = """id,airport_ref,airport_ident,length_ft,width_ft,surface,lighted,closed,le_ident,le_latitude_deg,le_longitude_deg,le_elevation_ft,le_heading_degT,le_displaced_threshold_ft,he_ident,he_latitude_deg,he_longitude_deg,he_elevation_ft,he_heading_degT,he_displaced_threshold_ft
1,1,EDDL,9843,148,ASP,1,0,05R,51.2775,6.7502,147,53,0,23L,51.2937,6.7885,147,233,0
2,1,EDDL,8858,148,ASP,1,0,05L,51.2811,6.7570,147,53,0,23R,51.2957,6.7915,147,233,0
3,1,EDDL,3000,100,ASP,1,1,09,51.2800,6.7600,147,90,0,27,51.2800,6.7700,147,270,0
4,1,EDXX,3000,100,ASP,1,0,09,,,,,,27,,,,,
"""


@pytest.fixture()
def csv_datei(tmp_path):
    p = tmp_path / "runways.csv"
    p.write_text(CSV, encoding="utf-8")
    return p


def test_zwei_bahnen_mit_laenge_und_kurs(csv_datei):
    b = runway_ref.bahnen("EDDL", csv_datei)
    assert [x.name for x in b] == ["05R/23L", "05L/23R"]
    assert b[0].laenge == pytest.approx(3000, abs=60)
    assert b[0].kurs == pytest.approx(52.7, abs=1.5)


def test_geschlossene_bahn_faellt_weg(csv_datei):
    assert all(x.name != "09/27" for x in runway_ref.bahnen("EDDL", csv_datei))


def test_bahn_ohne_schwellenkoordinaten_faellt_weg(csv_datei):
    """Ohne beide Schwellen ist die Zeile als Passreferenz wertlos."""
    assert runway_ref.bahnen("EDXX", csv_datei) == []


def test_unbekannter_platz_gibt_leere_liste(csv_datei):
    assert runway_ref.bahnen("EDZZ", csv_datei) == []
```

- [ ] **Schritt 2: Test laufen lassen** — `ModuleNotFoundError: No module named 'app.runway_ref'`

- [ ] **Schritt 3: Modul schreiben**

```python
"""Bahnschwellen als Referenz fuer die Flugplatzkarten-Passung.

Quelle ist OurAirports -- dieselbe, die scripts/nearby_airports.py schon benutzt. Es kommt
also kein neuer Lieferant hinzu, nur eine zweite Datei desselben.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md, Abschnitt 5.1
"""
from __future__ import annotations

import csv
import math
import time
from collections import namedtuple
from pathlib import Path

Bahn = namedtuple("Bahn", "name le he laenge kurs")

URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"
HOECHSTALTER_S = 30 * 24 * 3600

_SCHWELLEN = ("le_latitude_deg", "le_longitude_deg", "he_latitude_deg", "he_longitude_deg")


def _meter(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """Ost- und Nordabstand in Metern. Fuer die Ausdehnung eines Flughafens genau genug:
    Die Naeherung weicht auf 4 km um weniger als einen Meter ab."""
    mitte = math.radians((lat1 + lat2) / 2)
    return ((lon2 - lon1) * 111320.0 * math.cos(mitte), (lat2 - lat1) * 110540.0)


def bahnen(icao: str, datei: Path | str) -> list[Bahn]:
    """Alle offenen Bahnen des Platzes, die beide Schwellenkoordinaten tragen."""
    code = (icao or "").strip().upper()
    aus: list[Bahn] = []
    with open(datei, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("airport_ident", "").upper() != code or r.get("closed") == "1":
                continue
            if not all(r.get(k) for k in _SCHWELLEN):
                continue
            le = (float(r["le_latitude_deg"]), float(r["le_longitude_deg"]))
            he = (float(r["he_latitude_deg"]), float(r["he_longitude_deg"]))
            ost, nord = _meter(le[0], le[1], he[0], he[1])
            aus.append(Bahn(name=f"{r['le_ident']}/{r['he_ident']}", le=le, he=he,
                            laenge=math.hypot(ost, nord),
                            kurs=math.degrees(math.atan2(ost, nord)) % 360))
    return aus


def datei_holen(ziel: Path, hole=None) -> Path:
    """runways.csv besorgen, wenn die Ablage fehlt oder aelter als 30 Tage ist.

    Faellt die Quelle aus, bleibt eine vorhandene Datei in Gebrauch: Neue Passungen sind
    dann unmoeglich, bestehende bleiben unberuehrt -- dieselbe Regel wie bei einem
    fehlgeschlagenen Blattabruf.
    """
    ziel = Path(ziel)
    if ziel.is_file() and time.time() - ziel.stat().st_mtime < HOECHSTALTER_S:
        return ziel
    if hole is None:
        import httpx

        def hole(url: str) -> str:
            r = httpx.get(url, timeout=60.0, follow_redirects=True)
            r.raise_for_status()
            return r.text
    try:
        text = hole(URL)
    except Exception:
        if ziel.is_file():
            return ziel
        raise
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ziel)
    return ziel
```

- [ ] **Schritt 4: Test laufen lassen** — alle PASS

- [ ] **Schritt 5: Commit**

```bash
git add app/runway_ref.py tests/test_runway_ref.py
git commit -m "Bahnschwellen von OurAirports als Passreferenz

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: Bahnfarbe und Bahnflächen

**Dateien:**
- Erstellen: `app/ground_charts.py`
- Test: `tests/test_ground_charts.py` (neu)

**Schnittstellen:**
- Produziert: `bahnfarbe(im) -> int | None`,
  `bahnflaechen(im, ton) -> list[list[tuple[int, int, int]]]` (Läufe je Fläche als
  `(y, x0, x1)`).

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_ground_charts.py
"""Flugplatzkarten: Bildanalyse und Pruefkette.

Die Testblaetter werden gezeichnet, nicht heruntergeladen -- die DFS ist keine Testfixture
und ein Blatt aendert sich mit jedem AIRAC.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md
"""
from __future__ import annotations

import math

import pytest
from PIL import Image, ImageDraw

from app import ground_charts

TON = 153


def blatt(bahnen, groesse=(1200, 700), ton=TON, rauschen=True):
    """Ein Blatt mit den angegebenen Bahnen. bahnen: [(x0,y0,x1,y1,breite), ...]"""
    im = Image.new("L", groesse, 255)
    z = ImageDraw.Draw(im)
    if rauschen:
        # Gebaeude und Vorfelder in ANDEREN Grautoenen -- sonst prueft der Test nur, ob
        # der Code das einzige Nichtweiss findet.
        z.rectangle((40, 40, 200, 160), fill=228)
        z.rectangle((900, 500, 1100, 640), fill=200)
        z.ellipse((300, 40, 380, 120), fill=176)
    for x0, y0, x1, y1, br in bahnen:
        z.line((x0, y0, x1, y1), fill=ton, width=br)
    return im


def test_bahnfarbe_wird_gemessen_nicht_festgelegt():
    """Flugplatzkarte 153, Rollkarte 179 -- der Ton ist keine Konstante des Formats."""
    assert ground_charts.bahnfarbe(blatt([(100, 350, 1100, 350, 28)])) == 153
    assert ground_charts.bahnfarbe(
        blatt([(100, 350, 1100, 350, 28)], ton=179)) == 179


def test_ohne_bahnfarbe_kommt_none():
    """Ein Blatt ohne grosse mittelgraue Flaeche ist keine Flugplatzkarte."""
    assert ground_charts.bahnfarbe(Image.new("L", (1200, 700), 255)) is None


def test_zwei_parallelbahnen_werden_getrennt_gefunden():
    im = blatt([(100, 250, 1100, 250, 28), (100, 450, 1100, 450, 28)])
    f = ground_charts.bahnflaechen(im, TON)
    assert len(f) == 2


def test_gebaeude_in_anderer_farbe_zaehlen_nicht_mit():
    im = blatt([(100, 350, 1100, 350, 28)])
    assert len(ground_charts.bahnflaechen(im, TON)) == 1
```

- [ ] **Schritt 2: Test laufen lassen** — `ModuleNotFoundError`

- [ ] **Schritt 3: Modul anlegen**

`app/ground_charts.py` mit `bahnfarbe` und `bahnflaechen` — die Fassungen aus
`scripts/ground_chart_probe.py` (Funktionen `bahnfarbe` und `komponenten`), mit
ausformulierten Docstrings. Der Prototyp ist der Beleg, nicht die Vorlage für den Stil.

Schwellen aus der Spec, Abschnitt 5.2 und 5.3:
- Ton: häufigster Wert zwischen 100 und 210, mindestens 0,6 % der Stichprobe (jedes dritte
  Pixel je Achse).
- Fläche: mindestens 8000 Pixel, Toleranz ± 6 um den Ton, Läufe ab 3 px.

- [ ] **Schritt 4: Test laufen lassen** — alle PASS

- [ ] **Schritt 5: Commit**

```bash
git add app/ground_charts.py tests/test_ground_charts.py
git commit -m "Flugplatzkarten: Bahnfarbe messen, Bahnflaechen finden

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: Achse und Bahnenden

**Dateien:**
- Ändern: `app/ground_charts.py`
- Test: `tests/test_ground_charts.py`

**Schnittstellen:**
- Konsumiert: `bahnflaechen` aus Task 8.
- Produziert: `hauptachse(flaeche) -> Achse` mit den Feldern
  `cx, cy, winkel_rad, laenge, breite, u0, u1`;
  `enden_tasten(im, ton, achse) -> tuple[float, float]` (Achskoordinaten der echten Enden).

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_achswinkel_stimmt_auf_ein_zehntel_grad():
    """Der Winkel ist die verlaesslichste Groesse der Kette -- gemessen stimmten die Achsen
    zweier Parallelbahnen desselben Blattes auf 0,01 bis 0,06 Grad ueberein."""
    im = blatt([(100, 600, 1100, 400, 28)])          # Steigung -200/1000
    a = ground_charts.hauptachse(ground_charts.bahnflaechen(im, TON)[0])
    soll = math.degrees(math.atan2(-200, 1000))
    assert math.degrees(a.winkel_rad) == pytest.approx(soll, abs=0.1)


def test_abzweig_verkuerzt_die_flaeche_das_tasten_holt_es_zurueck():
    """Rollwegabzweige und Markierungen trennen die Flaeche; gemessene Laengen fielen bis zu
    24 Prozent zu kurz aus. Bei EDDL hob das Tasten 1414 px auf die richtigen 1769 px."""
    im = blatt([(100, 350, 1100, 350, 28)])
    z = ImageDraw.Draw(im)
    z.rectangle((580, 330, 620, 370), fill=255)      # weisse Luecke mitten in der Bahn
    flaechen = ground_charts.bahnflaechen(im, TON)
    a = ground_charts.hauptachse(max(flaechen, key=lambda f: sum(b - x + 1
                                                                for _, x, b in f)))
    assert a.laenge < 900                            # die Flaeche allein ist zu kurz
    u0, u1 = ground_charts.enden_tasten(im, TON, a)
    assert u1 - u0 == pytest.approx(1000, abs=40)    # getastet stimmt es wieder


def test_tasten_schiesst_nicht_ueber_das_bahnende_hinaus():
    """Die erlaubte Luecke von 60 px darf nicht dazu fuehren, dass ein anschliessender
    Rollweg gleicher Farbe als Teil der Bahn gilt."""
    im = blatt([(100, 350, 700, 350, 28)])
    z = ImageDraw.Draw(im)
    z.line((820, 350, 1100, 350, ), fill=TON, width=28)   # zweites Stueck, 120 px entfernt
    flaechen = ground_charts.bahnflaechen(im, TON)
    a = ground_charts.hauptachse(max(flaechen, key=lambda f: sum(b - x + 1
                                                                for _, x, b in f)))
    u0, u1 = ground_charts.enden_tasten(im, TON, a)
    assert u1 - u0 == pytest.approx(600, abs=40)
```

- [ ] **Schritt 2: Test laufen lassen** — Erwartet: `AttributeError: hauptachse`

- [ ] **Schritt 3: Implementieren**

`hauptachse` über die zweiten Momente, `enden_tasten` entlang der Achse mit erlaubter Lücke
von 60 px und geforderter Querabdeckung von 55 % — Fassungen aus
`scripts/ground_chart_probe.py`.

**Zur Lückenweite:** 60 px sind bei 1,7 m/px rund 100 m, bei 2,6 m/px rund 155 m. Der dritte
Test oben prüft, dass ein 120 px entferntes zweites Stück **nicht** mitgenommen wird.
Schlägt er fehl, ist die Lücke zu weit — dann gehört sie an den gemessenen Maßstab gebunden
statt an eine feste Pixelzahl. Das ist ein bekannter offener Punkt (Spec, Abschnitt 14.1).

- [ ] **Schritt 4: Test laufen lassen** — alle PASS

- [ ] **Schritt 5: Commit**

```bash
git add app/ground_charts.py tests/test_ground_charts.py
git commit -m "Flugplatzkarten: Achse aus Momenten, Enden durch Tasten

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: Zuordnung, Transformation, Prüfkette

Der Kern. Fünf Prüfungen, jede mit einem Messwert dahinter.

**Dateien:**
- Ändern: `app/ground_charts.py`
- Test: `tests/test_ground_charts.py`

**Schnittstellen:**
- Konsumiert: `hauptachse`, `enden_tasten` aus Task 9; `runway_ref.Bahn` aus Task 7.
- Produziert: `passung_rechnen(im, bahnen: list[Bahn]) -> GroundPassung | None` mit den
  Feldern `drehung, mps, rest_max, bahnen, punkte, ost_n, nord_n` (die beiden letzten sind
  die Koeffizientenpaare der Transformation).
- Produziert: `REST_SCHRANKE_M = 15.0`.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def _kunstblatt(drehung_grad, mps, bahnen_m):
    """Ein Blatt aus bekannter Wahrheit zeichnen: So laesst sich pruefen, ob die Rechnung
    genau das zurueckgibt, was hineingesteckt wurde."""
    ...  # Hilfsfunktion, in Schritt 3 zusammen mit der Implementierung ausformuliert


def test_die_rechnung_findet_die_eingesetzte_drehung_wieder():
    im, bahnen, soll = _kunstblatt(drehung_grad=-37.2, mps=1.69, bahnen_m=[
        ((0, 0), (2400, 0)), ((0, 400), (2700, 400))])
    p = ground_charts.passung_rechnen(im, bahnen)
    assert p is not None
    assert p.drehung == pytest.approx(322.8, abs=0.5)
    assert p.mps == pytest.approx(1.69, rel=0.02)
    assert p.rest_max < ground_charts.REST_SCHRANKE_M


def test_ohne_y_spiegelung_gaebe_es_keine_loesung():
    """Bildkoordinaten laufen nach unten, Nordmeter nach oben. Ohne die Spiegelung liegt die
    richtige Loesung nicht im Suchraum -- die Vorabprobe lieferte dann 59 m statt 5,7 m fuer
    dasselbe Blatt (Spec 5.6 Punkt 3). Der Test bindet an die Deklaration, damit die
    Spiegelung nicht spaeter 'vereinfacht' wird."""
    import inspect
    quelle = inspect.getsource(ground_charts.passung_rechnen)
    assert "-y" in quelle or "spiegel" in quelle.lower()


def test_kopfueber_wird_verworfen():
    """Zwei gleich lange Parallelbahnen sind unter 180 Grad symmetrisch; der Restfehler kann
    das nicht unterscheiden. Bei EDDM waehlte die Rechnung ohne diese Bedingung 173,5 statt
    353,5 Grad, bei gleich kleinem Restfehler."""
    im, bahnen, _ = _kunstblatt(drehung_grad=-6.5, mps=2.58, bahnen_m=[
        ((0, 0), (4000, 0)), ((0, 500), (4000, 500))])
    p = ground_charts.passung_rechnen(im, bahnen)
    assert p is not None
    assert not (90.0 < p.drehung < 270.0)


def test_widerspruechliche_massstaebe_werden_abgewiesen():
    """Eine Karte hat genau einen Massstab. Weichen zwei Bahnen um mehr als 8 Prozent ab,
    ist die Zuordnung falsch -- diese Pruefung hat vier Fehlpassungen mit 229, 793, 849 und
    1152 m abgewiesen."""
    im, bahnen, _ = _kunstblatt(drehung_grad=0.0, mps=2.0, bahnen_m=[
        ((0, 0), (3800, 0)), ((0, 600), (2300, 600))])
    falsch = [bahnen[1], bahnen[0]]          # Zuordnung vertauscht
    assert ground_charts.passung_rechnen(im, falsch) is None or \
        ground_charts.passung_rechnen(im, falsch).rest_max < ground_charts.REST_SCHRANKE_M


def test_eine_bahn_allein_reicht_nicht():
    """Zwei Punkte bestimmen die Passung exakt und lassen keinen Restfehler uebrig -- sie
    ist dann unpruefbar, nicht richtig. Betrifft EDDB, EDDC, EDDE, EDDG, EDDR, EDDW."""
    im, bahnen, _ = _kunstblatt(drehung_grad=0.0, mps=2.0,
                                bahnen_m=[((0, 0), (2600, 0))])
    assert ground_charts.passung_rechnen(im, bahnen) is None
```

- [ ] **Schritt 2: Test laufen lassen** — Erwartet: `AttributeError: passung_rechnen`

- [ ] **Schritt 3: Implementieren**

Die Kette aus `scripts/ground_chart_probe.py`, Funktion `probe`, ausformuliert. Die fünf
Prüfungen der Spec, Abschnitt 5.6:

1. mindestens vier Passpunkte
2. Ähnlichkeit (vier Unbekannte), **nicht** affin
3. y-Spiegelung vor der Rechnung
4. Nordung außerhalb (90°, 270°) verworfen
5. Maßstäbe zweier Bahnen höchstens 8 % auseinander

Und `rest_max <= REST_SCHRANKE_M`, sonst `None`.

Auch `_kunstblatt` gehört hierher: Es dreht Sollkoordinaten in Bildkoordinaten und zeichnet
sie — die Umkehrung dessen, was `passung_rechnen` tut. **Es darf den Code des Moduls nicht
mitbenutzen**, sonst prüft der Test sich selbst.

- [ ] **Schritt 4: Test laufen lassen** — alle PASS

- [ ] **Schritt 5: Gegen die echten Blätter halten**

```bash
.venv/bin/python scripts/ground_chart_probe.py
```

Erwartet: EDDL rund 5,7 m, EDDM rund 6,6 m. **Weicht die neue Rechnung von diesen Werten ab,
ist sie nicht dieselbe** — dann steht die Abweichung vor dem nächsten Task.

- [ ] **Schritt 6: Commit**

```bash
git add app/ground_charts.py tests/test_ground_charts.py
git commit -m "Flugplatzkarten: Zuordnung durchprobieren, fuenf Pruefungen

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 11: Welche Seite ist eine Flugplatzkarte?

**Dateien:**
- Ändern: `app/ground_charts.py`
- Erstellen: `app/data/ground_chart_kopf/flugplatzkarte.png`,
  `app/data/ground_chart_kopf/rollkarte.png`
- Erstellen: `scripts/ground_chart_kopfmuster.py` (gewinnt die Muster einmalig)
- Test: `tests/test_ground_charts.py`

**Schnittstellen:**
- Produziert: `sorte_erkennen(im) -> str | None` — `"flugplatzkarte"`, `"rollkarte"` oder
  `None`.
- Produziert: `KOPF_SCHRANKE = 0.97` (Anteil übereinstimmender Pixel).

- [ ] **Schritt 1: Den Ausschnitt vermessen**

**Nicht schätzen.** Eine Voruntersuchung über einen Hash eines nach Augenmaß gewählten
Ausschnitts hat vier verschiedene Cluster über Blätter geliefert, die alle Flugplatzkarten
sein müssten — der Ausschnitt traf bei den breiteren Blättern Weißraum.

Vorgehen: Von EDDL Seite 6 und EDDM Seite 7 den Bereich oben links so weit ausschneiden, bis
er den vollständigen zweizeiligen Titel enthält und **keinen** platzabhängigen Inhalt. Die
Grenzen im Kommentar festhalten, mit den gemessenen Pixelwerten.

- [ ] **Schritt 2: Fehlschlagenden Test schreiben**

```python
def test_sorte_wird_am_kopf_erkannt(tmp_path):
    """Der Titel steht bei allen Blaettern an derselben Stelle und in derselben Setzung.
    Verglichen wird der Pixelanteil, nicht ein Hash -- ein einzelnes veraendertes Pixel darf
    die Erkennung nicht kippen."""
    muster = Image.open("app/data/ground_chart_kopf/flugplatzkarte.png")
    im = Image.new("L", (3101, 1754), 255)
    im.paste(muster, ground_charts.KOPF_ECKE)
    assert ground_charts.sorte_erkennen(im) == "flugplatzkarte"


def test_ein_veraendertes_pixel_kippt_die_erkennung_nicht():
    muster = Image.open("app/data/ground_chart_kopf/rollkarte.png").copy()
    muster.putpixel((3, 3), 0 if muster.getpixel((3, 3)) > 128 else 255)
    im = Image.new("L", (3691, 1754), 255)
    im.paste(muster, ground_charts.KOPF_ECKE)
    assert ground_charts.sorte_erkennen(im) == "rollkarte"


def test_fremdes_blatt_gibt_none():
    assert ground_charts.sorte_erkennen(Image.new("L", (875, 1241), 255)) is None
```

- [ ] **Schritt 3: Test laufen lassen** — FAIL

- [ ] **Schritt 4: Implementieren und die Muster gewinnen**

`scripts/ground_chart_kopfmuster.py` lädt die beiden belegten Seiten, schneidet den in
Schritt 1 vermessenen Bereich aus und legt ihn als PNG ab. Das Skript ist einmalig; es liegt
im Repo, damit die Muster bei einem Formatwechsel der DFS neu gewonnen werden können, ohne
den Ausschnitt erneut zu suchen.

`sorte_erkennen` vergleicht den Ausschnitt gegen beide Muster und gibt die Sorte zurück,
deren Übereinstimmung `KOPF_SCHRANKE` erreicht.

- [ ] **Schritt 5: An allen 30 heruntergeladenen Blättern prüfen**

Der Ausschnitt muss über die ganze Breitenspanne (1240 bis 3800 px) tragen. Notiere, wie
viele Blätter als Flugplatzkarte, als Rollkarte und als keins erkannt werden — und sieh dir
mindestens drei davon selbst an, um die Zuordnung zu bestätigen.

- [ ] **Schritt 6: Commit**

```bash
git add app/ground_charts.py app/data/ground_chart_kopf scripts/ground_chart_kopfmuster.py tests/test_ground_charts.py
git commit -m "Flugplatzkarten: Sorte am Kopfbereich erkennen, ohne Zeichen zu lesen

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 12: Genordet ablegen

**Dateien:**
- Ändern: `app/ground_charts.py`
- Test: `tests/test_ground_charts.py`

**Schnittstellen:**
- Konsumiert: `GroundPassung` aus Task 10.
- Produziert: `norden(roh: bytes, p: GroundPassung) -> tuple[bytes, dict]` — das gedrehte
  PNG und die Grenzen `{nord, sued, west, ost, feld_nord, feld_sued, feld_west, feld_ost}`.
- Produziert: `FELD_SAUM_M = 1000.0`.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_gedrehtes_blatt_wird_groesser_und_die_grenzen_wachsen_mit():
    """expand=True vergroessert das Bild; bei 37 Grad waechst die Flaeche um rund 60 Prozent.
    Die Ecken des GEDREHTEN Blattes bestimmen nord/sued/west/ost."""
    im, bahnen, _ = _kunstblatt(drehung_grad=-37.2, mps=1.69, bahnen_m=[
        ((0, 0), (2400, 0)), ((0, 400), (2700, 400))])
    p = ground_charts.passung_rechnen(im, bahnen)
    roh = _als_png(im)
    gedreht, g = ground_charts.norden(roh, p)
    neu = Image.open(io.BytesIO(gedreht))
    assert neu.size[0] > im.size[0] and neu.size[1] > im.size[1]
    assert g["nord"] > g["sued"] and g["ost"] > g["west"]


def test_feldgrenzen_sind_die_bahnhuelle_nicht_die_blattgrenzen():
    """Die Verwechslung von Blatt- und Feldgrenzen steckte hinter dem 45-Prozent-
    Massstabsfehler der Sichtflugkarten. Nach dem Drehen zeigt das Blatt viel Weissraum --
    ueber dem duerfte die Automatik nicht schon einschalten."""
    im, bahnen, _ = _kunstblatt(drehung_grad=-37.2, mps=1.69, bahnen_m=[
        ((0, 0), (2400, 0)), ((0, 400), (2700, 400))])
    p = ground_charts.passung_rechnen(im, bahnen)
    _, g = ground_charts.norden(_als_png(im), p)
    assert g["feld_nord"] < g["nord"] and g["feld_sued"] > g["sued"]
    assert g["feld_west"] > g["west"] and g["feld_ost"] < g["ost"]
```

- [ ] **Schritt 2: Test laufen lassen** — FAIL

- [ ] **Schritt 3: Implementieren**

```python
def norden(roh: bytes, p) -> tuple[bytes, dict]:
    """Blatt genordet ablegen und seine Grenzen ausrechnen.

    ``L.imageOverlay`` kann nicht rotieren, die DFS-Blaetter sind aber nach der Bahnrichtung
    gesetzt. Gedreht wird deshalb hier, einmal beim Ablegen -- dasselbe Verfahren wie bei den
    sieben quer gedruckten Sichtflugkarten, nur mit beliebigem statt rechtem Winkel.

    ``fillcolor=255``: Der Rand, den ``expand=True`` freilaesst, muss WEISS sein und nicht
    schwarz -- er liegt im Overlay ueber der Karte.
    """
```

Die Feldgrenzen sind die Hülle der zur Passung benutzten Bahnen zuzüglich `FELD_SAUM_M`,
umgerechnet in Grad. **Nicht** die Blattgrenzen.

- [ ] **Schritt 4: Test laufen lassen** — alle PASS

- [ ] **Schritt 5: Ein echtes Blatt ansehen**

EDDL norden lassen, als PNG ablegen und **selbst betrachten**. Die Bahnen müssen nach 053°
zeigen, der Rand weiß sein, nichts abgeschnitten. Ein Test prüft Zahlen; ob die Karte
aussieht wie eine Karte, sieht nur ein Auge.

- [ ] **Schritt 6: Commit**

```bash
git add app/ground_charts.py tests/test_ground_charts.py
git commit -m "Flugplatzkarten genordet ablegen, Feldgrenzen aus der Bahnhuelle

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 13: Tabelle `aip_ground_charts`

**Dateien:**
- Ändern: `app/database.py`
- Test: `tests/test_ground_charts.py`

**Schnittstellen:**
- Produziert: `upsert_ground_chart(conn, icao, *, hand_ueberschreiben=False, **felder) -> str`
  (mit derselben Sperre wie Task 1), `get_ground_charts(conn, nur_gepasst=True) -> list[dict]`,
  `get_ground_chart(conn, icao) -> dict | None`, `delete_ground_chart(conn, icao) -> int`.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

Die Testfälle aus Task 1 sinngemäß für die neue Tabelle — **einschließlich der Sperre**.
Sie ist hier keine Kür: Die Handpassung einer Flugplatzkarte ist genauso schutzwürdig.

```python
def test_ground_handpassung_ist_ebenso_gesperrt(conn):
    from app.database import HandpassungGesperrt, get_ground_chart, upsert_ground_chart
    werte = dict(sorte="flugplatzkarte", seite_url="https://aip.dfs.de/x.html",
                 bild_hash="a" * 64, quell_hash="b" * 64,
                 nord=51.30, sued=51.27, west=6.74, ost=6.80,
                 feld_nord=51.295, feld_sued=51.275, feld_west=6.745, feld_ost=6.795,
                 drehung=322.8, mps=1.69, rest_max=5.7, bahnen=2,
                 airac="2026AUG20", status="gepasst")
    upsert_ground_chart(conn, "EDDL", quelle="hand", **werte)
    with pytest.raises(HandpassungGesperrt):
        upsert_ground_chart(conn, "EDDL", quelle="auto", **{**werte, "drehung": 0.0})
    assert get_ground_chart(conn, "EDDL")["drehung"] == pytest.approx(322.8)
```

- [ ] **Schritt 2 bis 5:** Schema aus Spec-Abschnitt 3.1 anlegen, Funktionen schreiben, Tests
  laufen lassen, committen. Die Sperrprüfung wird aus `upsert_aip_chart` **herausgezogen** in
  eine gemeinsame Hilfsfunktion `_handpassung_pruefen(conn, tabelle, code, felder,
  hand_ueberschreiben)`, damit sie nicht in zwei Fassungen existiert.

---

## Task 14: Beschaffung und Bestand

**Dateien:**
- Erstellen: `scripts/ground_chart_bestand.py`
- Test: `tests/test_ground_chart_bestand.py` (neu)

**Schnittstellen:**
- Konsumiert: alles aus Task 7 bis 13.
- Produziert: `lauf(nur: set[str] | None = None, pause: float = 0.4) -> dict` mit den
  Schlüsseln `gesamt, gepasst, quote, ungepasst, hand_gesperrt, vorschlag_faellig`.

Regeln wie in `scripts/aip_bestand.py`, ergänzt um:

- **Die Rollkarte hat Vorrang.** Gibt es beide Sorten mit bestandener Prüfkette, gewinnt die
  Rollkarte (Spec 1.1).
- **Mehrere Blätter derselben Sorte:** das mit dem kleinsten `rest_max`. Zusammensetzen ist
  ausgeschlossen (Spec 1.2).
- **Handpassung ist gesperrt** — über `_karte_schreiben` wie in Task 2, mit
  `vorschlag_anlegen(conn, "ground", ...)`.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben** — mit einem gefälschten `holen`, das
  drei Seiten liefert: eine Textseite, eine Flugplatzkarte, eine Rollkarte. Erwartet wird,
  dass die Rollkarte gewinnt.
- [ ] **Schritt 2 bis 6:** wie in den Tasks zuvor.

---

## Task 15: Endpoints

**Dateien:**
- Ändern: `app/main.py`
- Test: `tests/test_ground_chart_api.py` (neu)

Die sechs Endpoints aus Spec-Abschnitt 9. Zwei Dinge sind zu übernehmen, nicht neu zu
erfinden:

- **`Cache-Control: private`** beim Bild. `public` erlaubte jedem Zwischen-Cache das
  Ausliefern ohne Anmeldung, und genau die Beschränkung auf angemeldete Nutzer trägt das
  rechtliche Argument.
- **Nur die Felder, die der Admin braucht.** Die Vollzeile hat bei den Sichtflugkarten
  209 KB für 446 Karten ergeben und die Seite lahmgelegt.

Nach jeder ändernden Operation `_aip_karten_geaendert(request)` — ohne das erscheint eine
frisch gepasste Karte im Kniebrett erst nach einem Neuladen, das dort innerhalb einer
Sim-Sitzung nie stattfindet.

- [ ] **Schritt 1 bis 6:** wie zuvor, je Endpoint ein Test.

---

## Task 16: Ebene, Automatik, magenta Marke

**Dateien:**
- Ändern: `app/static/index.html`
- Test: `tests/test_ground_chart_ui.py` (neu)

**Schnittstellen:**
- Konsumiert: `GET /api/aip-ground-charts` aus Task 15.
- Produziert: `liveOverlays['Flugplatzkarte']`, CSS-Klasse `.ground-marke`.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_flugplatzkarte_verdeckt_die_sichtflugkarte_und_gibt_sie_zurueck():
    """Zwei halbtransparente Blaetter uebereinander sind nicht lesbar, und beim Rollen
    traegt die Sichtflugkarte nichts. Sie bleibt aber als EBENE eingeschaltet -- sonst
    stuende nach der Landung ein Haekchen aus, das niemand weggeklickt hat."""
    rumpf = _ohne_kommentare(QUELLE)
    assert "_groundKarteNachfuehren" in rumpf
    assert "_aipKarteVerdeckt" in rumpf


def test_engere_hysterese_als_bei_der_sichtflugkarte():
    """0,02 Grad sind rund 2 km -- groesser als mancher Platz."""
    rumpf = _ohne_kommentare(QUELLE)
    m = re.search(r"_GROUND_KARTE_HYSTERESE\s*=\s*([0-9.]+)", rumpf)
    assert m and float(m.group(1)) < 0.02


def test_marke_ist_magenta_und_hohl():
    """Hohl wie .aip-marke und aus demselben Grund: Sie liegt UEBER dem Platz, ein
    Vollsymbol deckte genau die Stelle zu, auf die es ankommt."""
    rumpf = _ohne_kommentare(QUELLE)
    m = re.search(r"\.ground-marke rect\s*\{([^}]*)\}", rumpf)
    assert m
    assert "fill: rgba(" in m.group(1)          # durchscheinend, nicht deckend
    assert "#2d9cdb" not in m.group(1)          # nicht die Farbe der Sichtflugkarte
```

- [ ] **Schritt 2 bis 6:** Ebene bauen. Die Mechanik der Sichtflugkarten-Ebene wird
  **geteilt, nicht kopiert** — Nachführen, Hysterese, Festnageln, Wegklicken, Deckkraft und
  Marken tragen dort je einen Kommentar, der einen Nutzerbefund festhält. Zwei Fassungen
  davon liefen auseinander.

- [ ] **Schritt 7: Im Kniebrett ansehen**

Nicht nur im Browser. Coherent GT rendert anders; `.aip-marke` hat dort eigene Regeln
gebraucht, und das Ebenen-Menü ist eine Zeile länger geworden — dessen Zeilenzahl hatte laut
Kommentar in `index.html` schon einmal Folgen.

---

## Task 17: Admin für Flugplatzkarten

**Dateien:**
- Ändern: `app/static/admin.html`, `app/main.py`
- Test: `tests/test_ground_chart_api.py`

Liste mit Sorte, Status, **Restfehler** und Bahnenzahl. Der Restfehler ist die einzige Zahl,
an der ein Mensch von außen erkennt, ob eine automatische Passung sitzt — er gehört sichtbar
in die Liste, nicht in ein Aufklappmenü.

Handpassung: **zwei Punkte klicken und ihre Koordinaten angeben**, die Drehung folgt daraus.
Nicht nach einem Winkel fragen — den kann niemand auf einer Karte ablesen.

Den Vorschlagsweg aus Task 5 auf `art="ground"` erweitern (dort steht heute ein
`HTTPException(400, "nur Sichtflugkarten, siehe Task 17")`).

---

## Task 18: Der zweite Job

**Dateien:**
- Ändern: `app/poller.py`
- Test: `tests/test_poller_jobs.py`

Wöchentlich, mit `next_run_time` wie in Task 6, aber **um zwei Stunden versetzt** gegen
`aip_auffrischen`: Beide Läufe sind reines Python über jedes Pixel und ziehen dieselbe
Bandbreite von derselben Quelle.

Über `asyncio.to_thread`, aus demselben Grund wie beim Vorbild: Auf dem Event-Loop stünden
derweil SSE, der 15-Sekunden-Poll und jede einzelne Anfrage.

- [ ] **Schritt 1 bis 6:** wie in Task 6.

---

## Abschluss

- [ ] **Voller Testlauf:** `pytest tests/ -q` — erwartet über 2042 PASS (der Stand vor
  diesem Plan), keine Fehlschläge.
- [ ] **Changelog:** ein Eintrag je Phase, `"highlight": false` in beiden.
- [ ] **README:** der Abschnitt zu den AIP-Karten bekommt die Flugplatzkarten und den
  Vorschlagsweg.
- [ ] **Deploy nicht während eines Fluges.** Jeder Push startet den Container neu und reißt
  offene Sitzungen ab; vorher fragen.

---

## Selbstprüfung dieses Plans

Gegen die Spec durchgegangen. Zwei Punkte, die ein Bearbeiter kennen muss:

1. **Spec-Abschnitt 5.8 (ARP-Kreuz für Plätze mit einer Bahn) hat keinen Task.** Das ist
   Absicht: Die Spec nennt es einen abtrennbaren Schritt, und `test_eine_bahn_allein_reicht_nicht`
   in Task 10 hält das heutige Verhalten fest (diese Plätze bekommen kein Overlay). Wer das
   ändern will, schreibt einen eigenen Plan — das Merkmal steht und fällt für sich.
2. **Die Ausbeute ist heute zu klein** (Spec 14.1): zwei von rund zehn Blättern unter 15 m.
   Task 10 Schritt 5 hält die Werte fest, aber **kein Task hebt sie**. Wenn nach Task 14 der
   erste volle Lauf eine Quote unter 30 % zeigt, ist das kein Fehlschlag der Umsetzung,
   sondern der offene Punkt aus der Spec — dann gehört untersucht, ob die abgetasteten Enden
   systematisch neben den Schwellen liegen, weil Stopways und Blast Pads in derselben Farbe
   gezeichnet sind.
