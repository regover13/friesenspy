# Schutz der Handkorrektur — Implementierungsplan

> **Für agentische Bearbeiter:** ERFORDERLICHE SUB-SKILL: `superpowers:subagent-driven-development`
> (empfohlen) oder `superpowers:executing-plans`. Die Schritte tragen Kästchen (`- [ ]`).

**Ziel:** Eine von Hand gesetzte Kartenpassung wird nie wieder automatisch überschrieben oder
gelöscht. Weicht die Automatik ab, erscheint ihr Ergebnis als Vorschlag zur Prüfung.

**Architektur:** Die Sperre sitzt in `upsert_aip_chart` selbst, nicht bei den sieben
Aufrufern. Abweichende Automatikfunde landen in einer Vorschlagstabelle mit Grabstein statt
im Bestand. Der wöchentliche Auffrischlauf wird geweckt — aber über einen persistenten
Fälligkeitsmerker, nicht über einen festen Versatz nach dem Start.

**Tech-Stack:** Python 3.11, FastAPI, SQLite (WAL), APScheduler, Vanilla JS.

**Spec:** [`docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md`](../specs/2026-08-30-ground-chart-overlay-design.md),
Abschnitte 3.2, 3.3, 7, 8, 9

**Dieser Plan ist für sich lieferbar** und hängt nicht am Flugplatzkarten-Vorhaben. Die
Kopplung geht nur in eine Richtung: Jener Plan braucht diesen, nicht umgekehrt.

---

## Warum das dringend ist

Es geht um **171 handgepasste Sichtflugkarten** — Arbeit des Nutzers, die heute an vier
Stellen verloren gehen kann. Sie ist bisher nur deshalb erhalten, weil der Auffrischlauf seit
seiner Einführung **kein einziges Mal gelaufen ist** (Spec 8.1). Aufgabe 8 weckt ihn.

**Die Reihenfolge ist zwingend: Aufgabe 8 kommt zuletzt.**

---

## Globale Vorgaben

- **Keine neue Abhängigkeit.**
- **Echte Namen:** `init_db(db_path: str)` nimmt einen **Pfad**. `get_connection(db_path: str)`
  — es gibt **kein** `get_conn`. `settings.DB_PATH`. `broadcast_sse` ist eine **Methode am
  Poller**; im Endpoint wird `_aip_karten_geaendert(request)` benutzt (`app/main.py:4204`).
- **Es gibt kein `tests/conftest.py`.** Fixtures je Testdatei, DB über `tmp_path` wie in
  `tests/test_aip_charts.py:29-35`.
- `conn = get_connection(...)` / `try` / `finally: conn.close()`. `with conn` ist in sqlite3
  eine **Transaktion**, kein Close.
- Deutsche Bezeichner und Kommentare.
- **`"highlight": false`** im Changelog-Eintrag.
- Tests: `pytest tests/ -q`, rund vier Minuten. Stand vor diesem Plan: **2042 PASS**.

---

## Task 1: Die Sperre an einer Stelle

**Die Bedingung lautet: Schreibversuch mit `quelle='auto'` auf eine bestehende Zeile mit
`quelle='hand'`.** Nicht „keine Zeile mit `quelle='hand'` überschreiben" — das bräche drei
legitime Pfade (Spec 7.1): `_handblatt_auffrischen` frischt hand über hand auf,
`admin_set_aip_chart` lässt einen Menschen sich selbst korrigieren,
`scripts/aip_handpassung.py` dasselbe von der Kommandozeile.

**Dateien:**
- Ändern: `app/database.py:6531` (`upsert_aip_chart`)
- Test: `tests/test_handpassung_schutz.py` (neu)

**Interfaces:**
- Produziert: `class HandpassungGesperrt(Exception)` in `app/database.py`
- Produziert: `upsert_aip_chart(conn, icao, *, hand_ueberschreiben: bool = False, **felder) -> str`

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
# Eine Handpassung legt Nullen in den Rasterfeldern ab -- app/aip_charts.py:1620. Genau
# deshalb kann geometrie_gleich() sie nie wiedererkennen; das ist die Ursache der Luecke.
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
    k = get_aip_chart(conn, "EDDL")
    assert k["nord"] == pytest.approx(54.24) and k["quelle"] == "hand"


def test_ein_mensch_darf_seine_eigene_passung_ersetzen(conn):
    """admin_set_aip_chart und scripts/aip_handpassung.py -- beide schreiben hand ueber
    hand. Eine Sperre, die das verhindert, macht die Korrektur unmoeglich."""
    _hand(conn)
    _hand(conn, **{**BOUNDS, "nord": 55.0})
    assert get_aip_chart(conn, "EDDL")["nord"] == pytest.approx(55.0)


def test_bildauffrischung_unter_bestehender_handpassung_bleibt_erlaubt(conn):
    """Regel 4 aus scripts/aip_bestand.py: _handblatt_auffrischen zieht das BILD nach,
    nachdem zeigt_denselben_ausschnitt nachgewiesen hat, dass es dieselbe Karte ist. Es
    schreibt quelle=alt['quelle'], also 'hand' -- und muss durchkommen."""
    _hand(conn)
    _hand(conn, bild_hash="c" * 64, airac="2026SEP17")
    k = get_aip_chart(conn, "EDDL")
    assert k["bild_hash"] == "c" * 64 and k["nord"] == pytest.approx(54.24)


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


def test_auch_eine_ungepasste_handzeile_ist_geschuetzt(conn):
    """Die Sperre haengt NICHT am status. Der Seitenwaehler schreibt heute
    quelle='auto' if passung else 'hand' (app/main.py:4400) und erzeugt damit Zeilen mit
    quelle='hand', status='ungepasst'. Waere die Sperre an status='gepasst' gebunden,
    fielen genau diese durch -- das war die dritte Luecke. Task 2 behebt die Fehlbenennung
    an der Wurzel; bis dahin und danach schuetzt die Sperre beide Faelle."""
    _hand(conn, status="ungepasst")
    with pytest.raises(HandpassungGesperrt):
        upsert_aip_chart(conn, "EDDL", bild_hash="b" * 64, **BOUNDS, **GEO,
                         quelle="auto", airac="y", status="gepasst")
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag prüfen**

Aufruf: `pytest tests/test_handpassung_schutz.py -v`
Erwartet: `ImportError: cannot import name 'HandpassungGesperrt' from 'app.database'`

- [ ] **Schritt 3: Sperre einbauen**

In `app/database.py`, direkt vor `upsert_aip_chart`:

```python
class HandpassungGesperrt(Exception):
    """Versuch, eine von Hand gesetzte Passung automatisch zu ueberschreiben.

    Die Sperre sitzt hier und nicht bei den Aufrufern, weil es sieben Schreibpfade auf
    ``aip_charts`` gibt (Stand 30.08.2026): drei in scripts/aip_bestand.py, zwei in
    app/main.py, einer in scripts/aip_handpassung.py, dazu delete_aip_chart. Zwei davon
    haben Handpassungen ueberschrieben, ein dritter war beim Schreiben der Spec nicht
    einmal bekannt. Eine Pruefung an jeder Aufrufstelle waere beim naechsten neuen Pfad
    wieder unvollstaendig.
    """
```

`upsert_aip_chart` bekommt die Prüfung nach der Pflichtfeldprüfung:

```python
def upsert_aip_chart(conn: sqlite3.Connection, icao: str, *,
                     hand_ueberschreiben: bool = False, **felder) -> str:
    """Kartenpassung setzen/aktualisieren. Alle Felder aus _AIP_FELDER sind Pflicht.

    **Gesperrt ist genau eines: ein Schreibversuch mit quelle='auto' auf eine bestehende
    Zeile mit quelle='hand'.** Nicht "keine Handzeile ueberschreiben" -- das braeche drei
    berechtigte Pfade: _handblatt_auffrischen (Bild nachziehen, hand ueber hand),
    admin_set_aip_chart und scripts/aip_handpassung.py (ein Mensch korrigiert sich selbst).

    ``hand_ueberschreiben=True`` ist ausschliesslich fuer die Uebernahme eines Vorschlags
    durch den Admin gedacht. Kein automatischer Pfad setzt es.

    Der ``status`` spielt bewusst KEINE Rolle: Der Seitenwaehler erzeugt heute Zeilen mit
    quelle='hand' und status='ungepasst'; an den status gebunden fielen sie durch.
    """
    code = (icao or "").strip().upper()
    fehlt = [f for f in _AIP_FELDER if f not in felder]
    if fehlt:
        raise ValueError(f"Pflichtfelder fehlen: {', '.join(fehlt)}")
    if not hand_ueberschreiben and felder.get("quelle") != "hand":
        alt = conn.execute(
            "SELECT quelle FROM aip_charts WHERE icao = ?", (code,)).fetchone()
        if alt is not None and alt["quelle"] == "hand":
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

Aufruf: `pytest tests/test_handpassung_schutz.py -v` — Erwartet: 7 PASS

- [ ] **Schritt 5: Vollen Bestand prüfen**

Aufruf: `pytest tests/ -q`
Erwartet: Fehlschläge dort, wo Bestandstests bisher eine Handpassung durch eine
Automatikpassung ersetzt haben. **Jeden einzeln ansehen, keinen löschen.** Wo ein Test die
Admin-Übernahme meint, gehört `hand_ueberschreiben=True` hinein; wo er den Auffrischlauf
meint, `pytest.raises(HandpassungGesperrt)`.

`tests/test_aip_charts.py:52` (`test_handpassung_ueberschreibt_und_bleibt_erkennbar`) prüft
die Richtung auto → hand und **muss unverändert bestehen bleiben** — das ist die Gegenprobe,
dass die Sperre nicht zu breit geraten ist.

- [ ] **Schritt 6: Commit**

```bash
git add app/database.py tests/
git commit -m "Handpassung ist eine Sperre, kein Vermerk

Gesperrt ist genau ein Fall: quelle=auto ueber eine bestehende Zeile mit
quelle=hand. Nicht jede Handzeile -- sonst koennte ein Mensch seine eigene
Passung nicht mehr korrigieren.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Die Fehlbenennung im Seitenwähler und der `ungepasst`-Zweig

`app/main.py:4400` schreibt `quelle="auto" if passung else "hand"`. Scheitert die Automatik
auf der gewählten Seite, steht dort `quelle='hand'`, **obwohl kein Mensch etwas gepasst
hat**. Das ist die Wurzel der dritten Lücke: `'hand'` heißt dort „wartet auf Handarbeit"
statt „von Hand gesetzt".

**Dateien:**
- Ändern: `app/main.py:4400`
- Ändern: `scripts/aip_bestand.py:194` (der Schutz im `passung is None`-Zweig)
- Test: `tests/test_aip_api.py`, `tests/test_handpassung_schutz.py`

**Interfaces:**
- Konsumiert: `HandpassungGesperrt` aus Task 1
- Verändert: Der Seitenwähler schreibt bei gescheiterter Passung `quelle="auto"` und
  `status="ungepasst"` — nicht mehr `quelle="hand"`.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_gescheiterte_seitenwahl_behauptet_keine_handpassung(client, db_pfad):
    """'hand' heisst 'von einem Menschen gesetzt', nicht 'wartet auf einen Menschen'. Der
    Unterschied traegt die ganze Sperre aus Task 1: Eine falsch als 'hand' benannte Zeile
    waere fuer immer gegen die Automatik gesperrt, ohne je Handarbeit enthalten zu haben."""
    antwort = client.post("/api/admin/aip-charts/EDWJ/seite",
                          json={"url": "https://aip.dfs.de/BasicVFR/2026AUG20/pages/x.html"},
                          cookies=ADMIN_COOKIE)
    assert antwort.status_code in (200, 422)
    conn = get_connection(db_pfad)
    try:
        k = get_aip_chart(conn, "EDWJ")
        if k is not None and k["status"] == "ungepasst":
            assert k["quelle"] == "auto"
    finally:
        conn.close()
```

- [ ] **Schritt 2: Test laufen lassen** — Erwartet: FAIL, `quelle` ist `hand`

- [ ] **Schritt 3: Umbenennen**

`app/main.py:4400`: `quelle="auto" if passung else "hand"` wird zu `quelle="auto"`. Der
Zustand „wartet auf Handarbeit" steht bereits in `status="ungepasst"`; ein zweites Feld
dafür ist die Verwechslung.

Kommentar dazu:

```python
            # quelle='auto' auch bei gescheiterter Passung. Bis 30.08.2026 stand hier
            # "auto" if passung else "hand" -- das benannte eine Zeile als handgesetzt,
            # die kein Mensch je angefasst hatte. Der Zustand "wartet auf Handarbeit"
            # steht in status='ungepasst'; ein zweites Feld dafuer war die Verwechslung.
```

- [ ] **Schritt 4: Den Schutz in `aip_bestand.py` nachziehen**

`scripts/aip_bestand.py:194` verlangt `alt["quelle"] == "hand" and alt["status"] == "gepasst"`.
Die Statusbedingung kann jetzt weg — nach Schritt 3 entstehen keine `hand`/`ungepasst`-Zeilen
mehr, und die Sperre aus Task 1 kennt den Status ohnehin nicht.

**Bestandsdaten prüfen, bevor das geändert wird:**

```bash
sudo sqlite3 /opt/friesenspy/data/friesenspy.db \
  "SELECT quelle, status, COUNT(*) FROM aip_charts GROUP BY 1,2;"
```

Erwartet nach heutigem Stand: nur `auto|gepasst` und `hand|gepasst`. Erscheint dort
`hand|ungepasst`, sind das Zeilen aus dem alten Verhalten — sie gehören auf `auto|ungepasst`
korrigiert, sonst bleiben sie für immer gesperrt. Das ist eine Datenmigration und gehört als
solche in `init_db` neben die übrigen.

- [ ] **Schritt 5: Tests laufen lassen** — `pytest tests/ -q`, alle PASS

- [ ] **Schritt 6: Commit**

```bash
git add app/main.py app/database.py scripts/aip_bestand.py tests/
git commit -m "quelle='hand' heisst von Hand gesetzt, nicht wartet auf Handarbeit

Der Seitenwaehler schrieb bei gescheiterter Passung 'hand'. Mit der Sperre
aus Task 1 waere so eine Zeile fuer immer gegen die Automatik gesperrt,
ohne je Handarbeit zu enthalten.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Auffrischlauf und Seitenwähler fangen die Sperre

**Dateien:**
- Ändern: `scripts/aip_bestand.py:213`, `app/main.py:4399`
- Test: `tests/test_handpassung_schutz.py`, `tests/test_aip_api.py`

**Interfaces:**
- Produziert: `_karte_schreiben(conn, icao, zaehler, vorschlag_faellig, **felder) -> bool`
  in `scripts/aip_bestand.py`
- Produziert: `lauf()` liefert zusätzlich `hand_gesperrt` (Zähler) und `vorschlag_faellig`
  (Liste von ICAO-Codes)

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_lauf_bricht_an_einer_gesperrten_karte_nicht_ab(conn):
    """Eine Ausnahme mitten im Durchgang liesse die restlichen 400 Karten liegen, und der
    naechste Lauf finge wieder von vorn an."""
    import scripts.aip_bestand as bestand
    _hand(conn, icao="EDDL")
    conn.commit()
    zaehler, faellig = {}, []
    ergebnis = bestand._karte_schreiben(
        conn, "EDDL", zaehler, faellig, bild_hash="b" * 64,
        **{**BOUNDS, "nord": 55.0}, **GEO, quelle="auto", airac="y", status="gepasst")
    assert ergebnis is False
    assert zaehler.get("hand_gesperrt") == 1 and faellig == ["EDDL"]
    assert get_aip_chart(conn, "EDDL")["nord"] == pytest.approx(54.24)


def test_bei_gesperrter_karte_wird_auch_das_bild_nicht_getauscht(conn, tmp_path):
    """Das ist der Kern der Nutzerfestlegung: 'keinesfalls erneut verzerrt werden'. Ein
    neues Bild unter der alten Passung IST die Verzerrung -- schlimmer als beides alt."""
    import inspect
    import scripts.aip_bestand as bestand
    quelle = inspect.getsource(bestand.lauf)
    stelle = quelle.index("_karte_schreiben")
    danach = quelle[stelle:stelle + 600]
    # blatt_schreiben darf erst NACH einem erfolgreichen _karte_schreiben kommen.
    assert "if not geschrieben" in danach
    assert danach.index("if not geschrieben") < danach.index("blatt_schreiben")
```

- [ ] **Schritt 2: Test laufen lassen** — `AttributeError: _karte_schreiben`

- [ ] **Schritt 3: Schreibhelfer einführen**

```python
def _karte_schreiben(conn, icao: str, zaehler, vorschlag_faellig: list, **felder) -> bool:
    """Passung ablegen, eine gesperrte Handpassung sauber abfangen.

    Der Lauf darf an einer gesperrten Karte nicht abbrechen. Gemeldet wird sie stattdessen;
    ihr Fund wird in Task 5 zum Vorschlag.
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

- [ ] **Schritt 4: Den letzten Zweig umstellen**

`scripts/aip_bestand.py:213`. **`blatt_schreiben` erst nach erfolgreichem Schreiben** —
sonst läge das neue Bild unter der alten Passung, und genau das ist die Verzerrung, vor der
der Nutzer gewarnt hat:

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
                    continue          # Bild NICHT anfassen: es gehoert nicht zur Passung
                aip_charts.blatt_schreiben(aip_charts.blatt_pfad(einst.DB_PATH, icao), roh)
                zaehler["gepasst"] += 1
```

- [ ] **Schritt 5: Die drei anderen Aufrufe belegen**

`scripts/aip_bestand.py:123`, `:185` und `:202` laufen nicht in die Sperre. **Das ist zu
belegen, nicht zu vermuten:** Jeden lesen und in einem Kommentar festhalten, warum — 123 und
185 schreiben `quelle=alt["quelle"]`, 202 trifft nach Task 2 nur noch Zeilen ohne
Handpassung.

- [ ] **Schritt 6: Den Seitenwähler absichern**

`app/main.py:4399` in `try`/`except HandpassungGesperrt` fassen, mit `conn.rollback()` und
einer Antwort, die `hand_behalten: True` trägt.

- [ ] **Schritt 7: Tests** — `pytest tests/ -q`, alle PASS

- [ ] **Schritt 8: Commit**

---

## Task 4: Verwaiste Handpassungen werden nicht gelöscht

`scripts/aip_bestand.py:148` räumt jede Karte ab, deren ICAO nicht mehr in `airport_links`
steht — **Zeile und Blatt**. Für eine Handpassung ist das ein unwiederbringlicher Verlust,
und die Sperre aus Task 1 greift dort nicht: Sie sitzt in `upsert_aip_chart`, nicht in
`delete_aip_chart`.

**Dateien:**
- Ändern: `app/database.py` (`delete_aip_chart`), `scripts/aip_bestand.py:144-151`
- Test: `tests/test_handpassung_schutz.py`

**Interfaces:**
- Produziert: `verwaisen(conn, icao) -> str` — setzt `status='verwaist'` statt zu löschen.
- `delete_aip_chart` bleibt unverändert; sie wird vom Auffrischlauf nur noch für
  Automatikkarten aufgerufen.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_verwaiste_handpassung_wird_nicht_geloescht(conn):
    """Verschwindet der Link, verliert eine Automatikkarte Zeile und Blatt -- das ist
    richtig, sie ist in Minuten neu gerechnet. Eine Handpassung ist Arbeit eines Menschen
    und wird nur aus der Anzeige genommen."""
    from app.database import get_aip_charts, verwaisen
    _hand(conn, icao="EDDL")
    verwaisen(conn, "EDDL")
    k = get_aip_chart(conn, "EDDL")
    assert k is not None and k["status"] == "verwaist" and k["quelle"] == "hand"
    assert "EDDL" not in [x["icao"] for x in get_aip_charts(conn)]


def test_verwaiste_karte_kann_zurueckkehren(conn):
    """Taucht der Link wieder auf -- ein AIRAC-Wechsel benennt Kapitelseiten um --, muss die
    Handpassung wieder greifen, ohne dass jemand sie neu setzt."""
    from app.database import get_aip_charts, verwaisen
    _hand(conn, icao="EDDL")
    verwaisen(conn, "EDDL")
    _hand(conn, icao="EDDL", status="gepasst")
    assert "EDDL" in [x["icao"] for x in get_aip_charts(conn)]
```

- [ ] **Schritt 2 bis 6:** `verwaisen` schreiben, den Aufräumzweig umstellen (Handpassungen
  verwaisen, Automatikkarten weiter löschen), Blatt in beiden Fällen **behalten** — es kostet
  1,4 MB und ist die Grundlage jeder späteren Prüfung —, Tests, Commit.

---

## Task 5: `seite_url` in `aip_charts`

**Die Seitenwahl ist Teil der Handkorrektur und geht heute verloren** (Spec 3.2). Wählt der
Admin für EDDK Seite 4, merkt sich `aip_charts` das nicht; der nächste Lauf nimmt wieder „die
erste Seite, deren Passung durchgeht". Das geschieht, **ohne dass `quelle` je auf `hand`
stand** — die Sperre aus Task 1 erfasst es nicht.

**Dateien:**
- Ändern: `app/database.py` (Spalte, Migration, `_AIP_FELDER`), `app/main.py` (Seitenwähler
  speichert), `scripts/aip_bestand.py` (Lauf bevorzugt sie)
- Test: `tests/test_handpassung_schutz.py`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_gespeicherte_seitenwahl_ueberlebt_den_auffrischlauf(conn):
    """Bei EDDK enthaelt das Kapitel sechs Seiten, und die automatisch gewaehlte war die
    falsche (Nutzer, 24.08.2026). Ohne gespeicherte Wahl waehlt der naechste Lauf sie
    erneut."""
    _hand(conn, icao="EDDK", seite_url="https://aip.dfs.de/BasicVFR/2026AUG20/pages/s4.html")
    assert get_aip_chart(conn, "EDDK")["seite_url"].endswith("s4.html")
```

- [ ] **Schritt 2 bis 6:** Spalte über die vorhandene Migrationsliste ergänzen (Muster:
  `_PANEL_DIAG_MIGRATIONS` in `app/database.py`), `_AIP_FELDER` erweitern — **Achtung:** Das
  macht `seite_url` zum Pflichtfeld für alle sieben Aufrufer; entweder alle nachziehen oder
  einen Vorgabewert `""` vorsehen. Den zweiten Weg wählen und begründen: Ein Pflichtfeld,
  das sechs Aufrufer nicht kennen, wäre ein Bruch ohne Gewinn.

  Danach: Seitenwähler schreibt die URL, `blatt_beschaffen` bekommt sie als bevorzugte Seite.

---

## Task 6: Vorschlagstabelle mit Grabstein

**Dateien:**
- Ändern: `app/database.py`
- Test: `tests/test_handpassung_schutz.py`

**Interfaces:**
- Produziert: `vorschlag_anlegen(conn, art, icao, quell_hash, passung: dict, grund) -> int`,
  `get_vorschlaege(conn, art=None, zustand="offen") -> list[dict]`,
  `vorschlag_verwerfen(conn, id_) -> int`, `vorschlag_entfernen(conn, id_) -> int`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_verworfener_vorschlag_kommt_nicht_wieder(conn):
    """Ein DELETE waere wirkungslos: UNIQUE verhindert Doppel nur, solange die Zeile
    existiert. Der naechste Wochenlauf faende denselben unveraenderten quell_hash und legte
    den Vorschlag sofort neu an -- die Liste waere dauerhaft unaufraeumbar."""
    from app.database import get_vorschlaege, vorschlag_anlegen, vorschlag_verwerfen
    vid = vorschlag_anlegen(conn, "sichtflug", "EDDL", "h1", {"nord": 55.0}, "weicht ab")
    vorschlag_verwerfen(conn, vid)
    assert get_vorschlaege(conn) == []
    vorschlag_anlegen(conn, "sichtflug", "EDDL", "h1", {"nord": 55.0}, "weicht ab")
    assert get_vorschlaege(conn) == []           # derselbe quell_hash bleibt verworfen


def test_ein_neues_rohblatt_ist_ein_neuer_vorschlag(conn):
    from app.database import get_vorschlaege, vorschlag_anlegen, vorschlag_verwerfen
    vid = vorschlag_anlegen(conn, "sichtflug", "EDDL", "h1", {"nord": 55.0}, "weicht ab")
    vorschlag_verwerfen(conn, vid)
    vorschlag_anlegen(conn, "sichtflug", "EDDL", "h2", {"nord": 56.0}, "weicht ab")
    assert len(get_vorschlaege(conn)) == 1


def test_beide_kartentypen_koennen_gleichzeitig_offen_sein(conn):
    """Der Dateiname des Vorschlagsbilds muss art UND quell_hash tragen -- sonst
    ueberschreiben sich zwei offene Vorschlaege zu EDDL gegenseitig."""
    from app.database import get_vorschlaege, vorschlag_anlegen
    vorschlag_anlegen(conn, "sichtflug", "EDDL", "h1", {}, "a")
    vorschlag_anlegen(conn, "ground", "EDDL", "h1", {}, "b")
    assert len(get_vorschlaege(conn)) == 2
    assert len(get_vorschlaege(conn, art="ground")) == 1
```

- [ ] **Schritt 2 bis 6:** Schema aus Spec 3.3, Funktionen, Tests, Commit. Der Bildname ist
  `<ICAO>.<art>.<quell_hash[:12]>.png`.

---

## Task 7: Vorschläge im Admin

**Dateien:**
- Ändern: `app/main.py` (vier Endpoints), `app/static/admin.html`
- Test: `tests/test_aip_api.py`

**Interfaces:**
- `GET /api/admin/aip-vorschlaege`
- `POST /api/admin/aip-vorschlaege/{id}/uebernehmen` — der einzige Ort, der
  `hand_ueberschreiben=True` setzt
- `POST /api/admin/aip-vorschlaege/{id}/verwerfen` — **nicht `DELETE`**
- `GET /aip-vorschlag/{id}.png` — eigener Endpunkt; `/aip-chart/{icao}.png` kann es nicht,
  dort steht `re.fullmatch(r"[A-Z0-9]{4}", code)` (`app/main.py:443`)

- [ ] **Schritt 1 bis 8:** je Endpoint ein Test, dann die Oberfläche. Der Abschnitt
  „Vorschläge" bleibt **ganz verborgen**, solange keiner offen ist — eine dauerhaft leere
  Überschrift ist ein Reiz, den niemand braucht.

Beim Übernehmen wird das Vorschlagsbild zum gültigen Blatt (`os.replace`). **Erst dann** —
vorher lag es bewusst daneben, damit die alte Passung nicht auf einem neuen Bild saß.

---

## Task 8: Den Auffrischjob wecken — mit Fälligkeitsmerker

**Erst jetzt.** Der Job fasst 446 Karten an; ohne Task 1 bis 7 täte er beim ersten Durchgang
genau das, was verboten wurde.

**Ein fester Versatz nach dem Start wäre falsch.** Der Lauf ist teuer: Der Hash wird erst
gebildet, **nachdem** die ganze Arbeit getan ist (`scripts/aip_bestand.py:178`). Vorher
laufen je Platz zwei HTTP-Abrufe, 0,4 s Pause und die volle Bildanalyse — bei den ~171
handgepassten zusätzlich ein kompletter Kapiteldurchlauf über 4 bis 12 Seiten. Realistisch
sind über 1000 Abrufe gegen `aip.dfs.de` je Lauf. Mit `next_run_time = start + 5min` würde
daraus ein **Deploy-Job**: An einem Tag mit zwölf Deploys wären das zwölf Vollcrawls.

**Dateien:**
- Ändern: `app/poller.py:553` und `_aip_auffrischen`
- Ändern: `app/database.py` (Merker)
- Test: `tests/test_poller_jobs.py` (neu)

**Interfaces:**
- Produziert: `job_faellig(conn, name: str, abstand_s: float) -> bool` und
  `job_erledigt(conn, name: str) -> None` in `app/database.py`, gestützt auf eine kleine
  Tabelle `job_laeufe(name TEXT PRIMARY KEY, zuletzt TEXT NOT NULL)`.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_job_laeuft_nach_deploy_nur_wenn_wirklich_faellig(tmp_path):
    """Zwoelf Deploys an einem Tag duerfen nicht zwoelf Vollcrawls der DFS ausloesen."""
    from app.database import get_connection, init_db, job_erledigt, job_faellig
    db = str(tmp_path / "t.db")
    init_db(db)
    conn = get_connection(db)
    try:
        assert job_faellig(conn, "aip_auffrischen", 7 * 24 * 3600) is True
        job_erledigt(conn, "aip_auffrischen")
        assert job_faellig(conn, "aip_auffrischen", 7 * 24 * 3600) is False
        assert job_faellig(conn, "aip_auffrischen", 0) is True
    finally:
        conn.close()


def test_der_job_meldet_seine_aenderungen():
    """_aip_auffrischen ruft heute kein _aip_karten_geaendert. Sobald er laeuft und Karten
    aendert, bliebe jedes offene Kniebrett auf dem alten Stand -- genau das Fehlerbild, das
    der Helfer am 24.08.2026 beheben sollte."""
    import inspect
    from app import poller
    quelle = inspect.getsource(poller.VatsimPoller._aip_auffrischen)
    assert "broadcast_sse" in quelle or "karten_geaendert" in quelle
```

- [ ] **Schritt 2 bis 7:** Merker bauen, `_aip_auffrischen` prüft ihn zuerst und ruft am Ende
  `job_erledigt` und das SSE-Ereignis. `next_run_time` auf wenige Minuten nach Start — der
  Merker entscheidet dann, ob wirklich gearbeitet wird.

- [ ] **Schritt 8: Den ersten echten Lauf beobachten**

**Nicht überspringen.**

```bash
docker logs friesenspy-friesenspy-1 2>&1 | grep -i "AIP-Karten"
sudo sqlite3 /opt/friesenspy/data/friesenspy.db \
  "SELECT quelle, status, COUNT(*) FROM aip_charts GROUP BY 1,2;"
```

Erwartet: weiterhin 171 Zeilen mit `quelle='hand'`. **Wenn diese Zahl sinkt, ist die Sperre
undicht** — dann sofort anhalten und die Ursache suchen, bevor der nächste Lauf kommt.

Steht im Log ein `hand_gesperrt` größer null, im Admin nachsehen, ob die Vorschläge sinnvoll
aussehen. Das ist die Gegenprobe an echten Daten.

---

## Abschluss

- [ ] **Voller Testlauf:** `pytest tests/ -q` — erwartet über 2042 PASS.
- [ ] **Changelog:** ein Eintrag, `"highlight": false`.
- [ ] **Deploy nicht während eines Fluges.** Jeder Push startet den Container neu und reißt
  offene Sitzungen ab; vorher fragen.

---

## Selbstprüfung dieses Plans

Gegen die Spec durchgegangen (Abschnitte 3.2, 3.3, 7, 8, 9). Alle vier Lücken aus 7.2 haben
einen Task: `:213` in Task 3, der Seitenwähler in Task 3, der `ungepasst`-Zweig in Task 2,
`delete_aip_chart` in Task 4. Die fünfte Lücke — die verlorene Seitenwahl aus 3.2 — hat
Task 5.

Ein Punkt bleibt offen und ist bewusst nicht eingeplant: **Spec 7.2 nennt `geometrie_gleich`
als Stelle, an der die vorhandene Lösung schon steht** (`gerade_aus_bestand` rechnet
ausdrücklich nicht über die Tick-Werte). Diese Funktion für Handpassungen brauchbar zu machen
würde Regel 3 wiederbeleben und den Vorschlagsweg in vielen Fällen überflüssig machen. Das
ist eine Verbesserung, kein Schutz — sie gehört in einen eigenen Plan, nachdem dieser läuft.
