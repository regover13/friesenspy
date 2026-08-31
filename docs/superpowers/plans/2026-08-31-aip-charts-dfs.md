# AIP Charts DFS — Umsetzungsplan

> **Für agentische Bearbeiter:** ERFORDERLICHE SUB-SKILL: `superpowers:subagent-driven-development`
> (empfohlen) oder `superpowers:executing-plans`. Die Schritte tragen Kästchen (`- [ ]`).

**Ziel:** Beide Passungs-Automatiken sind zurückgebaut, die bestehenden Passungen liegen in
einer Tabelle, eine Admin-Ansicht bedient beide Kartentypen, und ein Job meldet nur noch,
wenn sich ein Blatt bei der DFS wirklich geändert hat.

**Architektur:** `aip_charts` und `aip_ground_charts` werden zu `aip_charts_dfs` mit
Primärschlüssel `(icao, sorte)` zusammengeführt. Die Passung entsteht ausschließlich aus zwei
geklickten Punkten mit Koordinaten (`ground_charts.handpassung`), gefolgt vom Drehen und
Ablegen (`ground_charts.norden`). Alles, was Bilder deutet — Rahmen, Ticks, Ziffern,
Bahnflächen —, wird gelöscht.

**Tech-Stack:** Python 3.11, FastAPI, SQLite (WAL), Pillow, APScheduler, Vanilla JS.

**Spec:** [`docs/superpowers/specs/2026-08-31-aip-charts-dfs-design.md`](../specs/2026-08-31-aip-charts-dfs-design.md)

## Globale Vorgaben

- **Keine neue Abhängigkeit.** Pillow, httpx, airportsdata, APScheduler sind vorhanden.
- `init_db(db_path: str)` nimmt einen **Pfad**; `get_connection(db_path: str)` — es gibt
  **kein** `get_conn`; `settings.DB_PATH`.
- Es gibt **kein** `tests/conftest.py`. Fixtures je Testdatei, DB über `tmp_path`.
- `conn = get_connection(...)` / `try` / `finally: conn.close()`. `with conn` ist in sqlite3
  eine **Transaktion**, kein Close.
- Deutsche Bezeichner und Kommentare.
- **`"highlight": false`** in jedem Changelog-Eintrag, ohne Ausnahme.
- Kein `localStorage` im Frontend — `_prefLies` / `_prefSchreib`.
- Frontend-Tests binden an **Deklarationen**, nicht an Kommentare. Vor jeder
  Zeichenkettensuche im Quelltext die Kommentare entfernen:
  ```python
  def _ohne_kommentare(text: str) -> str:
      return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))
  ```
- Breite Tabellen brauchen `.table-wrap`; innerhalb `.scroll-list` zusätzlich eigene
  Höhenbegrenzung **und** sichtbare Scrollbar-Styles — beides zusammen, sonst unsichtbar.
- Tests: `pytest tests/ -q`, rund fünf Minuten. Stand vor diesem Plan: **2130 PASS**.

## Der Bestand, um den es geht

| Quelle | Zeilen | wird |
|---|---|---|
| `aip_charts`, `quelle='hand'` | 171 | `sorte='sichtflug'`, `status='gepasst'` |
| `aip_charts`, `quelle='auto'` | 275 | `sorte='sichtflug'`, `status='auto'` |
| `aip_ground_charts`, `status='gepasst'` | 68 | Sorte übernehmen, `status='auto'` |
| `aip_ground_charts`, `status='ungepasst'` | 42 | Sorte übernehmen, `status='offen'` |
| `airport_links` ohne Zeile | — | erscheinen als `nicht_gefunden` (nur in der Liste, nicht in der Tabelle) |

**Alle 110 Ground-ICAOs haben auch eine Sichtflugkarte.** Ohne den zweiteiligen Schlüssel
kollidieren genau diese 110 Zeilen — gemessen, nicht vermutet.

## Dateien

| Datei | Verantwortung |
|---|---|
| `app/database.py` | Tabelle `aip_charts_dfs`, Migration, Lese-/Schreibfunktionen |
| `app/ground_charts.py` | bleibt: `handpassung`, `norden`, `bahnfarbe`, `sorte_aus_ton` |
| `app/aip_charts.py` | schrumpft auf Beschaffung: AIRAC, Kapitelseiten, Bild, Ablage |
| `app/runway_ref.py` | unverändert |
| `app/main.py` | eine Endpunktgruppe `/api/admin/aip-charts-dfs`, alte entfallen |
| `app/poller.py` | ein Job `aip_hash_pruefen`, zwei alte entfallen |
| `scripts/aip_bestand.py` | schrumpft auf den Hash-Vergleich |
| `scripts/ground_chart_bestand.py` | **gelöscht** — geht in `aip_bestand.py` auf |
| `scripts/ground_chart_probe.py` | **gelöscht** |
| `scripts/aip_handpassung.py` | prüfen, dann löschen oder anpassen (Task 4) |
| `app/static/admin.html` | eine Ansicht „AIP Charts DFS" |
| `app/static/index.html` | Transparenzregler, sonst unverändert |
| `tests/test_charts_dfs.py` (neu) | Tabelle, Migration, Statusübergänge |
| `tests/test_charts_dfs_api.py` (neu) | Endpunkte |
| `tests/test_charts_dfs_ui.py` (neu) | Admin- und Frontend-Quelltext |
| `tests/test_aip_charts.py` | 744 Zeilen — der Automatiktest, wird stark gekürzt |
| `tests/test_ground_charts.py` | Bahnvermessungsreste entfernen |
| `tests/test_handpassung_schutz.py` | 436 Zeilen — Sperre entfällt, Task 9 |
| `tests/test_aip_api.py` | alte Endpunkte entfallen |

---

# Phase 1 — Daten

## Task 1: Tabelle und Migration

**Die Migration ist der gefährlichste Schritt des ganzen Plans.** Sie bewegt 556 Zeilen, und
`init_db` läuft bei **jedem Containerstart**. Eine Migration, die zweimal läuft und dabei
Nutzerarbeit überschreibt, wäre genau der Fehler, gegen den die ganze Vorgängerspec
geschrieben wurde.

**Dateien:**
- Ändern: `app/database.py`
- Test: `tests/test_charts_dfs.py` (neu)

**Interfaces:**
- Produziert: Tabelle `aip_charts_dfs` (Schema siehe Spec, Abschnitt 3)
- Produziert: `migration_charts_dfs(conn) -> int` — Zahl der übernommenen Zeilen, 0 wenn
  bereits gelaufen

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
# tests/test_charts_dfs.py
"""Eine Tabelle fuer beide Kartentypen -- Migration und Zugriff.

Spec: docs/superpowers/specs/2026-08-31-aip-charts-dfs-design.md
"""
from __future__ import annotations

import pytest

from app.database import (
    get_chart_dfs,
    get_charts_dfs,
    get_connection,
    init_db,
    migration_charts_dfs,
    upsert_chart_dfs,
)

# Zwei echte EDDL-Werte, damit der Test keine Geometrie prueft, die es nicht gibt.
LAGE = dict(nord=51.32, sued=51.25, west=6.71, ost=6.82,
            feld_nord=51.31, feld_sued=51.26, feld_west=6.72, feld_ost=6.81,
            drehung=322.8, mps=1.69)


@pytest.fixture()
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)                       # nimmt einen PFAD, keine Verbindung
    c = get_connection(db)
    yield c
    c.close()


def _alt_sichtflug(conn, icao="EDDL", quelle="hand"):
    """Eine Zeile im ALTEN Schema anlegen, so wie sie heute in aip_charts steht."""
    conn.execute(
        """INSERT INTO aip_charts (icao, bild_hash, nord, sued, west, ost,
                                   feld_nord, feld_sued, feld_west, feld_ost,
                                   rahmen_px, tick_px_lat, tick_px_lon,
                                   quelle, airac, status, seite_url, geprueft_am)
           VALUES (?, 'a', 51.32, 51.25, 6.71, 6.82, 51.31, 51.26, 6.72, 6.81,
                   '1,2,3,4', 0, 0, ?, '2026AUG20', 'gepasst', 'https://x/s.html',
                   '2026-08-30T12:00:00Z')""",
        (icao, quelle))


def _alt_ground(conn, icao="EDDL", sorte="rollkarte", status="gepasst"):
    conn.execute(
        """INSERT INTO aip_ground_charts (icao, sorte, seite_url, quell_hash, bild_hash,
                                          nord, sued, west, ost,
                                          feld_nord, feld_sued, feld_west, feld_ost,
                                          drehung, mps, rest_max, bahnen,
                                          quelle, airac, status, geprueft_am)
           VALUES (?, ?, 'https://x/g.html', 'q', 'b', 51.30, 51.27, 6.74, 6.80,
                   51.295, 51.275, 6.745, 6.795, 353.4, 2.58, 0, 0,
                   'hand', '2026AUG20', ?, '2026-08-31T09:00:00Z')""",
        (icao, sorte, status))


def test_beide_kartentypen_desselben_platzes_ueberleben(conn):
    """Alle 110 Ground-ICAOs haben auch eine Sichtflugkarte -- gemessen am 31.08.2026.

    Mit einem Schluessel auf icao allein kollidieren genau diese 110 Zeilen.
    """
    _alt_sichtflug(conn, "EDDL")
    _alt_ground(conn, "EDDL", "rollkarte")
    conn.commit()
    assert migration_charts_dfs(conn) == 2
    sorten = {k["sorte"] for k in get_charts_dfs(conn) if k["icao"] == "EDDL"}
    assert sorten == {"sichtflug", "rollkarte"}


def test_status_wird_richtig_abgebildet(conn):
    """hand -> gepasst, auto -> auto, ungepasst -> offen. Und die Ground-Passungen fallen
    auf auto zurueck: Sie sind von Claude gesetzt, nicht vom Nutzer geprueft."""
    _alt_sichtflug(conn, "EDAA", quelle="hand")
    _alt_sichtflug(conn, "EDAB", quelle="auto")
    _alt_ground(conn, "EDAC", "flugplatzkarte", "gepasst")
    _alt_ground(conn, "EDAD", "rollkarte", "ungepasst")
    conn.commit()
    migration_charts_dfs(conn)
    status = {(k["icao"], k["sorte"]): k["status"] for k in get_charts_dfs(conn)}
    assert status[("EDAA", "sichtflug")] == "gepasst"
    assert status[("EDAB", "sichtflug")] == "auto"
    assert status[("EDAC", "flugplatzkarte")] == "auto"
    assert status[("EDAD", "rollkarte")] == "offen"


def test_migration_laeuft_genau_einmal(conn):
    """init_db laeuft bei JEDEM Containerstart. Eine Migration, die dabei zweimal
    ausgefuehrt wird, wuerde Nutzerarbeit ueberschreiben -- genau der Fehler, gegen den die
    ganze Vorgaengerspec geschrieben wurde."""
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    assert migration_charts_dfs(conn) == 1
    assert migration_charts_dfs(conn) == 0


def test_nach_der_migration_geaenderte_zeilen_bleiben_geaendert(conn):
    """Der eigentliche Schaden waere nicht das Doppeln, sondern das Zuruecksetzen."""
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst",
                     **{**LAGE, "drehung": 12.5})
    migration_charts_dfs(conn)                     # zweiter Start
    assert get_chart_dfs(conn, "EDDL", "sichtflug")["drehung"] == pytest.approx(12.5)


def test_die_alten_tabellen_bleiben_stehen(conn):
    """Damit die Migration ohne Datenverlust wiederholbar ist, solange der neue Stand nicht
    geprueft wurde."""
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    assert conn.execute("SELECT COUNT(*) FROM aip_charts").fetchone()[0] == 1


def test_automatik_innereien_wandern_nicht_mit(conn):
    """rahmen_px, tick_px_* und rest_max waren Innereien der Passungsrechnung."""
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    spalten = {r[1] for r in conn.execute("PRAGMA table_info(aip_charts_dfs)")}
    assert not spalten & {"rahmen_px", "tick_px_lat", "tick_px_lon", "rest_max", "bahnen",
                          "quelle"}
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag prüfen**

Aufruf: `pytest tests/test_charts_dfs.py -v`
Erwartet: `ImportError: cannot import name 'migration_charts_dfs' from 'app.database'`

- [ ] **Schritt 3: Schema anlegen**

In `app/database.py`, im SCHEMA-String hinter `aip_ground_charts`:

```sql
-- Beide Kartentypen in einer Tabelle. Der Schluessel ist zweiteilig, weil ein Platz eine
-- Sichtflugkarte UND eine Flugplatzkarte haben kann -- gemessen am 31.08.2026 trifft das
-- auf ALLE 110 Plaetze mit Flugplatzkarte zu.
CREATE TABLE IF NOT EXISTS aip_charts_dfs (
    icao          TEXT NOT NULL,
    sorte         TEXT NOT NULL,              -- 'sichtflug' | 'flugplatzkarte' | 'rollkarte'
    seite_url     TEXT NOT NULL DEFAULT '',
    quell_hash    TEXT NOT NULL DEFAULT '',   -- SHA-256 des ROHblatts: der Aenderungsdetektor
    bild_hash     TEXT NOT NULL DEFAULT '',   -- des abgelegten Blatts, nur Cache-Schluessel
    nord          REAL NOT NULL DEFAULT 0,
    sued          REAL NOT NULL DEFAULT 0,
    west          REAL NOT NULL DEFAULT 0,
    ost           REAL NOT NULL DEFAULT 0,
    feld_nord     REAL NOT NULL DEFAULT 0,    -- Huelle der Passpunkte plus Saum: danach
    feld_sued     REAL NOT NULL DEFAULT 0,    -- schaltet die Automatik im Frontend.
    feld_west     REAL NOT NULL DEFAULT 0,    -- NICHT die Blattgrenzen -- diese Verwechslung
    feld_ost      REAL NOT NULL DEFAULT 0,    -- war der 45-Prozent-Massstabsfehler.
    drehung       REAL NOT NULL DEFAULT 0,    -- Grad, im Uhrzeigersinn gegen Nord
    mps           REAL NOT NULL DEFAULT 0,    -- Meter je Pixel im Rohblatt
    p1_x          REAL, p1_y REAL, p1_lat REAL, p1_lon REAL,
    p2_x          REAL, p2_y REAL, p2_lat REAL, p2_lon REAL,
    status        TEXT NOT NULL,              -- gepasst|auto|offen|nicht_gefunden|pruefen
    airac         TEXT NOT NULL DEFAULT '',
    geprueft_am   TEXT,
    PRIMARY KEY (icao, sorte)
);
```

- [ ] **Schritt 4: Migration schreiben**

```python
_DFS_SPALTEN = ("icao", "sorte", "seite_url", "quell_hash", "bild_hash",
                "nord", "sued", "west", "ost",
                "feld_nord", "feld_sued", "feld_west", "feld_ost",
                "drehung", "mps",
                "p1_x", "p1_y", "p1_lat", "p1_lon",
                "p2_x", "p2_y", "p2_lat", "p2_lon",
                "status", "airac", "geprueft_am")


def migration_charts_dfs(conn: sqlite3.Connection) -> int:
    """Bestand aus aip_charts und aip_ground_charts nach aip_charts_dfs uebernehmen.

    **Laeuft genau einmal.** ``init_db`` wird bei jedem Containerstart aufgerufen; eine
    Migration, die dabei erneut liefe, wuerde Nutzerarbeit zuruecksetzen. Der Merker steht
    in ``job_laeufe`` -- dieselbe Tabelle, die auch die Faelligkeit der Wochenlaeufe traegt.

    Die alten Tabellen bleiben stehen. Erst wenn der neue Stand geprueft ist, darf jemand
    sie loeschen -- bis dahin ist die Migration ohne Datenverlust wiederholbar (nach
    Loeschen des Merkers).

    Rueckgabe: Zahl der uebernommenen Zeilen, 0 wenn schon gelaufen.
    """
    schon = conn.execute(
        "SELECT 1 FROM job_laeufe WHERE name = 'migration_charts_dfs'").fetchone()
    if schon:
        return 0

    n = 0
    # Sichtflugkarten. quelle='hand' heisst "vom Nutzer gesetzt" -> gepasst.
    # quelle='auto' heisst "gerechnet, ungeprueft" -> auto.
    for r in conn.execute(
            """SELECT icao, seite_url, bild_hash, nord, sued, west, ost,
                      feld_nord, feld_sued, feld_west, feld_ost,
                      quelle, airac, status, geprueft_am
               FROM aip_charts""").fetchall():
        status = "gepasst" if r["quelle"] == "hand" else "auto"
        if r["status"] == "verwaist":
            # Der Link ist verschwunden, die Passung blieb erhalten. Sie ist Arbeit eines
            # Menschen und bleibt es -- sichtbar wird sie ueber den Statusfilter.
            status = "gepasst" if r["quelle"] == "hand" else "auto"
        conn.execute(
            f"""INSERT INTO aip_charts_dfs ({', '.join(_DFS_SPALTEN)})
                VALUES ({', '.join('?' * len(_DFS_SPALTEN))})
                ON CONFLICT(icao, sorte) DO NOTHING""",
            (r["icao"], "sichtflug", r["seite_url"] or "", "", r["bild_hash"] or "",
             r["nord"], r["sued"], r["west"], r["ost"],
             r["feld_nord"], r["feld_sued"], r["feld_west"], r["feld_ost"],
             0.0, 0.0, None, None, None, None, None, None, None, None,
             status, r["airac"] or "", r["geprueft_am"]))
        n += 1

    # Flugplatz- und Rollkarten. ALLE bestehenden Passungen stammen von Claude, nicht vom
    # Nutzer -- sie fallen deshalb auf 'auto' zurueck, nicht auf 'gepasst'.
    for r in conn.execute(
            """SELECT icao, sorte, seite_url, quell_hash, bild_hash,
                      nord, sued, west, ost, feld_nord, feld_sued, feld_west, feld_ost,
                      drehung, mps, airac, status, geprueft_am
               FROM aip_ground_charts""").fetchall():
        status = "auto" if r["status"] == "gepasst" else "offen"
        conn.execute(
            f"""INSERT INTO aip_charts_dfs ({', '.join(_DFS_SPALTEN)})
                VALUES ({', '.join('?' * len(_DFS_SPALTEN))})
                ON CONFLICT(icao, sorte) DO NOTHING""",
            (r["icao"], r["sorte"], r["seite_url"] or "", r["quell_hash"] or "",
             r["bild_hash"] or "",
             r["nord"], r["sued"], r["west"], r["ost"],
             r["feld_nord"], r["feld_sued"], r["feld_west"], r["feld_ost"],
             r["drehung"], r["mps"], None, None, None, None, None, None, None, None,
             status, r["airac"] or "", r["geprueft_am"]))
        n += 1

    conn.execute("INSERT INTO job_laeufe (name, zuletzt) VALUES (?, ?)",
                 ("migration_charts_dfs", _now_utc()))
    return n
```

**`ON CONFLICT DO NOTHING` ist die zweite Sicherung** neben dem Merker: Selbst wenn jemand
den Merker löscht, überschreibt der erneute Lauf keine Zeile, die inzwischen bearbeitet
wurde.

- [ ] **Schritt 5: In `init_db` aufrufen**

Nach den Migrationslisten, im selben `try`-Block wie die Tabellenerstellung:

```python
        try:
            uebernommen = migration_charts_dfs(conn)
            if uebernommen:
                logger.info("aip_charts_dfs: %d Zeilen uebernommen", uebernommen)
        except sqlite3.OperationalError:
            # Frische Datenbank ohne die alten Tabellen -- nichts zu tun.
            pass
```

- [ ] **Schritt 6: Tests laufen lassen** — `pytest tests/test_charts_dfs.py -v`, 6 PASS

- [ ] **Schritt 7: Commit**

```bash
git add app/database.py tests/test_charts_dfs.py
git commit -m "Eine Tabelle fuer beide Kartentypen, Migration laeuft genau einmal"
```

---

## Task 2: Zugriffsfunktionen und Statusübergänge

**Dateien:**
- Ändern: `app/database.py`
- Test: `tests/test_charts_dfs.py`

**Interfaces:**
- Produziert: `upsert_chart_dfs(conn, icao, sorte, **felder) -> None`
- Produziert: `get_charts_dfs(conn, status=None, sorte=None) -> list[dict]`
- Produziert: `get_chart_dfs(conn, icao, sorte) -> dict | None`
- Produziert: `delete_chart_dfs(conn, icao, sorte) -> int`
- Produziert: `STATUS_DFS = ("gepasst", "auto", "offen", "nicht_gefunden", "pruefen")`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_status_muss_bekannt_sein(conn):
    """Ein Tippfehler im Status waere sonst eine Zeile, die kein Filter je findet."""
    from app.database import upsert_chart_dfs
    with pytest.raises(ValueError):
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="halbgepasst", **LAGE)


def test_sorte_muss_bekannt_sein(conn):
    from app.database import upsert_chart_dfs
    with pytest.raises(ValueError):
        upsert_chart_dfs(conn, "EDDL", "anflugkarte", status="offen", **LAGE)


def test_filter_nach_status_und_sorte(conn):
    from app.database import get_charts_dfs, upsert_chart_dfs
    upsert_chart_dfs(conn, "EDAA", "sichtflug", status="gepasst", **LAGE)
    upsert_chart_dfs(conn, "EDAB", "sichtflug", status="offen", **LAGE)
    upsert_chart_dfs(conn, "EDAC", "rollkarte", status="offen", **LAGE)
    assert len(get_charts_dfs(conn, status=["offen"])) == 2
    assert len(get_charts_dfs(conn, status=["offen"], sorte=["rollkarte"])) == 1
    assert len(get_charts_dfs(conn, status=["gepasst", "offen"])) == 3
    assert len(get_charts_dfs(conn)) == 3


def test_geprueft_am_wird_bei_jedem_schreiben_gesetzt(conn):
    from app.database import get_chart_dfs, upsert_chart_dfs
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="offen", **LAGE)
    assert get_chart_dfs(conn, "EDDL", "sichtflug")["geprueft_am"]


def test_icao_wird_normalisiert(conn):
    from app.database import get_chart_dfs, upsert_chart_dfs
    upsert_chart_dfs(conn, "eddl", "sichtflug", status="offen", **LAGE)
    assert get_chart_dfs(conn, "EDDL", "sichtflug") is not None
```

- [ ] **Schritt 2 bis 5:** Test laufen lassen (FAIL), Funktionen schreiben, Test laufen
  lassen (PASS), committen.

Die Statusprüfung gehört in `upsert_chart_dfs`:

```python
STATUS_DFS = ("gepasst", "auto", "offen", "nicht_gefunden", "pruefen")
SORTEN_DFS = ("sichtflug", "flugplatzkarte", "rollkarte")


def upsert_chart_dfs(conn: sqlite3.Connection, icao: str, sorte: str, **felder) -> None:
    """Karte setzen. ``status`` ist Pflicht und muss aus STATUS_DFS stammen.

    Es gibt hier KEINE Sperre wie im alten upsert_aip_chart: Nach dem Rueckbau existiert
    kein automatischer Schreibpfad mehr, der eine Passung ueberschreiben koennte. Der Job
    setzt ausschliesslich status='pruefen' und quell_hash (s. Task 6), er rechnet nichts.
    """
    code = (icao or "").strip().upper()
    if sorte not in SORTEN_DFS:
        raise ValueError(f"unbekannte Sorte: {sorte!r}")
    if felder.get("status") not in STATUS_DFS:
        raise ValueError(f"unbekannter Status: {felder.get('status')!r}")
    # Nur die mitgegebenen Felder nachziehen. Ein Aufruf, der bloss den Status aendert
    # (etwa der Job mit status='pruefen'), darf die Passung nicht auf Null zuruecksetzen.
    setzbar = [f for f in _DFS_SPALTEN
               if f not in ("icao", "sorte", "geprueft_am") and f in felder]
    spalten = ("icao", "sorte", *setzbar, "geprueft_am")
    platz = ", ".join("?" * len(spalten))
    nachziehen = ", ".join(f"{f}=excluded.{f}" for f in (*setzbar, "geprueft_am"))
    conn.execute(
        f"""INSERT INTO aip_charts_dfs ({', '.join(spalten)}) VALUES ({platz})
            ON CONFLICT(icao, sorte) DO UPDATE SET {nachziehen}""",
        (code, sorte, *(felder[f] for f in setzbar), _now_utc()),
    )
```

---

# Phase 2 — Rückbau

## Task 3: `aip_charts.py` auf Beschaffung zurückbauen

**Dateien:**
- Ändern: `app/aip_charts.py` (1621 → ~250 Zeilen)
- Ändern: `tests/test_aip_charts.py` (744 Zeilen)

**Interfaces:**
- Bleibt: `airac_url`, `airac_kennung`, `bild_aus_html`, `kapitel_links`, `kapitelseiten`,
  `seiten_des_kapitels`, `blatt_schreiben`, `blatt_pfad`
- Entfällt: alles zwischen `Rahmen` und `blatt_beschaffen`

- [ ] **Schritt 1: Alle Aufrufer auflisten — vor dem Löschen**

```bash
grep -rn "aip_charts\.\(rahmen_finden\|tick_positionen\|passung_rechnen\|zahl_lesen\|ziffer_erkennen\|beschriftung_lesen\|ausgleichsgerade\|ist_quer_gedruckt\|geometrie_gleich\|gerade_aus_bestand\|zeigt_denselben_ausschnitt\|blatt_auffrischen\|genordet_rechnen\|blatt_beschaffen\|handpassung\)" --include=*.py app/ scripts/ tests/
```

Erwartet (Stand 31.08.2026): `app/main.py:4566` und `:4667`, `scripts/aip_bestand.py`
(vier Stellen), `scripts/aip_handpassung.py`, sowie `tests/test_aip_charts.py`.
**Jede Fundstelle wird in Task 4 bis 6 behandelt — erst dann darf gelöscht werden.**

- [ ] **Schritt 2: Fehlschlagenden Test schreiben**

Ans Ende von `tests/test_aip_charts.py`:

```python
def test_die_bilddeutung_ist_zurueckgebaut():
    """Sie hat ihren Zweck erfuellt -- 446 Sichtflugkarten und 110 Flugplatzblaetter sind
    beschafft und zugeordnet. Laufend gebraucht wird sie nicht: Die Blaetter aendern sich
    fast nie (Ausgabedaten von 2014 bis 2026; 437 von 446 beim einzigen Auffrischlauf
    unveraendert), und wenn doch, ist die Frage eine fuer einen Menschen.

    Der Test bindet an die Abwesenheit, damit sie nicht unbemerkt zurueckkehrt.
    """
    from app import aip_charts

    for weg in ("rahmen_finden", "tick_positionen", "tick_positionen_mit_band",
                "passung_rechnen", "zahl_lesen", "ziffer_erkennen", "beschriftung_lesen",
                "ausgleichsgerade", "ist_quer_gedruckt", "geometrie_gleich",
                "gerade_aus_bestand", "zeigt_denselben_ausschnitt", "blatt_auffrischen",
                "genordet_rechnen", "blatt_beschaffen", "handpassung", "raster",
                "Rahmen", "Passung"):
        assert not hasattr(aip_charts, weg), weg


def test_die_beschaffung_bleibt():
    """Blaetter holen und ablegen wird weiter gebraucht -- nur das Deuten nicht."""
    from app import aip_charts

    for da in ("airac_url", "airac_kennung", "bild_aus_html", "kapitel_links",
               "kapitelseiten", "seiten_des_kapitels", "blatt_schreiben", "blatt_pfad"):
        assert hasattr(aip_charts, da), da
```

- [ ] **Schritt 3: Test laufen lassen** — beide FAIL

- [ ] **Schritt 4: Löschen**

Aus `app/aip_charts.py` alles entfernen zwischen der Klasse `Rahmen` und
`blatt_schreiben` — außer den in Schritt 2 als bleibend genannten Funktionen. Der
Modul-Docstring wird ersetzt:

```python
"""DFS-Kartenblaetter beschaffen und ablegen.

Bis zum 31.08.2026 stand hier auch die Deutung: Kartenrahmen finden, Gradnetz-Ticks messen,
Ziffern per Schablone lesen, daraus eine Passung rechnen. Das hat 446 Sichtflugkarten
zugeordnet und dabei 171 der Handarbeit ueberlassen -- die Ziffernerkennung traegt nicht bei
jedem Blatt.

Laufend gebraucht wird sie nicht: Die Blaetter aendern sich fast nie. Die am 31.08.2026
durchgesehenen tragen Ausgabedaten von 2014 bis 2026, und beim einzigen Auffrischlauf waren
437 von 446 unveraendert. Und wenn sich eines aendert, ist die Frage ohnehin eine, die nur
ein Mensch beantworten kann: Stimmt die Passung auf dem neuen Blatt noch?

Die Passung entsteht seitdem in ``app/ground_charts.handpassung`` aus zwei geklickten
Punkten -- fuer beide Kartentypen.
"""
```

- [ ] **Schritt 5: Bestandstests kürzen**

`tests/test_aip_charts.py` prüft auf 744 Zeilen ganz überwiegend die gelöschte Deutung.
**Jeden Test einzeln ansehen.** Wer `rahmen_finden`, `tick_positionen`, `zahl_lesen`,
`passung_rechnen`, `geometrie_gleich` oder `zeigt_denselben_ausschnitt` prüft, wird
gelöscht; wer `bild_aus_html`, `kapitelseiten` oder `airac_url` prüft, bleibt. Die
Testfixtures unter `tests/fixtures/aip/` (`blatt_bauen.py`, `messwerte.json`) gehen mit —
sie erzeugen Blätter mit Gradnetz für eine Messung, die es nicht mehr gibt.

- [ ] **Schritt 6: Tests laufen lassen** — `pytest tests/test_aip_charts.py -v`

- [ ] **Schritt 7: Commit**

---

## Task 4: `scripts/` aufräumen

**Dateien:**
- Ändern: `scripts/aip_bestand.py` (347 → ~120)
- Löschen: `scripts/ground_chart_bestand.py`, `scripts/ground_chart_probe.py`
- Prüfen: `scripts/aip_handpassung.py`

- [ ] **Schritt 1: `aip_handpassung.py` lesen und entscheiden**

Das Skript ist bisher nicht geprüft worden. Es schreibt in `aip_charts` (Zeile 369) und
erwähnt `genordet_rechnen` im Kommentar. **Lies es ganz.** Entweder es kann Passungen setzen,
die die neue Maske nicht kann — dann wird es auf `aip_charts_dfs` und
`ground_charts.handpassung` umgestellt —, oder es ist ein Vorläufer der Admin-Maske und wird
gelöscht. Entscheidung im Commit begründen.

- [ ] **Schritt 2: Fehlschlagenden Test schreiben**

```python
# tests/test_charts_dfs.py
def test_der_bestandslauf_rechnet_nichts_mehr():
    """Er vergleicht Hashes. Mehr nicht -- damit kann er per Bauart keine Passung
    beschaedigen, und die Sperre aus der Vorgaengerspec wird ueberfluessig."""
    import inspect
    import re

    from scripts import aip_bestand

    quelle = re.sub(r"#[^\n]*", "", inspect.getsource(aip_bestand))
    for weg in ("passung_rechnen", "genordet_rechnen", "geometrie_gleich",
                "blatt_beschaffen", "blatt_auffrischen", "platz_koordinate"):
        assert weg not in quelle, weg
    assert "sha256" in quelle
```

- [ ] **Schritt 3 bis 5:** `aip_bestand.py` auf `melden()` zurückbauen (die Funktion aus
  `ground_chart_bestand.py` ist die Vorlage — sie tut bereits genau das), die beiden anderen
  Skripte löschen, Tests, Commit.

Der verbleibende Lauf:

```python
def melden(pause: float = 0.4) -> dict:
    """Fuer jede Karte mit gesetzter seite_url das Rohblatt holen und den Hash vergleichen.

    Weicht er ab, wird status='pruefen' gesetzt und das neue Blatt daneben gelegt. Sonst
    passiert nichts. Kein Rechnen, kein Schreiben einer Passung.

    Zeilen OHNE seite_url werden uebersprungen -- bei ihnen ist nicht bekannt, welches Blatt
    zu pruefen waere. Sie erscheinen in der Liste als 'offen' und warten auf die
    Seitenauswahl.
    """
```

---

# Phase 3 — Oberfläche

## Task 5: Endpunkte

**Dateien:**
- Ändern: `app/main.py`
- Test: `tests/test_charts_dfs_api.py` (neu)

**Interfaces:**

| Methode und Pfad | Zweck |
|---|---|
| `GET /api/aip-charts-dfs` | Metadaten der gepassten Karten fürs Frontend, gefiltert auf `status in ('gepasst','auto')` |
| `GET /aip-chart-dfs/{icao}/{sorte}.png` | das abgelegte (gedrehte) Blatt |
| `GET /aip-chart-roh/{icao}/{sorte}.png` | das **Rohblatt** zum Klicken, nur Admin |
| `GET /api/admin/aip-charts-dfs` | Liste über **alle 446 Plätze**, mit Status und Filter |
| `GET /api/admin/aip-charts-dfs/{icao}/seiten` | Kapitelseiten mit Vorschau |
| `POST /api/admin/aip-charts-dfs/{icao}/seite` | Seite und Sorte festlegen |
| `POST /api/admin/aip-charts-dfs/{icao}/{sorte}` | Passung setzen: zwei Punkte + Drehung |
| `POST /api/admin/aip-charts-dfs/{icao}/{sorte}/bestaetigen` | Status `prüfen` → `gepasst` |
| `DELETE /api/admin/aip-charts-dfs/{icao}/{sorte}` | Karte entfernen |

**Die Rohbild-Route bekommt einen eigenen Pfad**, nicht `.roh.png` als Suffix:

```python
@app.get("/aip-chart-roh/{icao}/{sorte}.png", include_in_schema=False)
```

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_rohbild_wird_ausgeliefert(client, tmp_path):
    """Der alte Pfad /aip-ground-chart/{icao}.roh.png war nie erreichbar: FastAPI prueft
    Routen in Registrierungsreihenfolge, {icao} schluckt den Punkt, und die davor
    registrierte Route /aip-ground-chart/{icao}.png fing die Anfrage mit icao='EDDL.roh'
    ab -- scheiterte an der Vierzeichenpruefung und lieferte 404. Deshalb ein eigener Pfad
    statt eines Suffixes.
    """
    c, db, tmp = client
    _karte(db, "EDDL", "rollkarte")
    (tmp / "aip_dfs").mkdir(exist_ok=True)
    (tmp / "aip_dfs" / "EDDL.rollkarte.roh.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 40)
    antwort = c.get("/aip-chart-roh/EDDL/rollkarte.png")
    assert antwort.status_code == 200


def test_liste_zeigt_auch_plaetze_ohne_blatt(client, db_pfad):
    """Ausdruecklicher Wunsch: 'Vielleicht finde ich ja eine geeignete Karte, die du nicht
    gefunden hast.' Ein Platz ohne Zeile erscheint als nicht_gefunden."""
    conn = get_connection(db_pfad)
    try:
        conn.execute("INSERT INTO airport_links (icao, aip_url, updated_at) "
                     "VALUES ('EDZZ', 'https://x/k.html', '2026-08-31T00:00:00Z')")
        conn.commit()
    finally:
        conn.close()
    d = c.get("/api/admin/aip-charts-dfs").json()
    zzz = [k for k in d["charts"] if k["icao"] == "EDZZ"]
    assert zzz and zzz[0]["status"] == "nicht_gefunden"


# Die beiden Schwellen der EDDL-Bahn 05R/23L, UNGERUNDET aus runways.csv. Auf fuenf
# Nachkommastellen gerundet ergaeben dieselben Punkte 3211 m statt 2999 -- ein
# Laengenfehler von sieben Prozent, und der Test pruefte eine Geometrie, die es nicht gibt.
S_05R = (51.279598236083984, 6.751989841461182)
S_23L = (51.2958984375, 6.786220073699951)


def test_passen_setzt_status_gepasst(client, db_pfad, tmp_path):
    """Setzt der Nutzer selbst eine Passung, ist sie geprueft -- nicht 'auto'."""
    from app.database import get_chart_dfs, get_connection

    c, _db, tmp = client
    (tmp / "aip_dfs").mkdir(exist_ok=True)
    _rohblatt(tmp / "aip_dfs" / "EDDL.flugplatzkarte.roh.png", 2200, 1000)
    antwort = c.post("/api/admin/aip-charts-dfs/EDDL/flugplatzkarte", json={
        "p1_x": 200, "p1_y": 500, "p1_lat": S_05R[0], "p1_lon": S_05R[1],
        "p2_x": 1970, "p2_y": 500, "p2_lat": S_23L[0], "p2_lon": S_23L[1],
    })
    assert antwort.status_code == 200
    conn = get_connection(db_pfad)
    try:
        k = get_chart_dfs(conn, "EDDL", "flugplatzkarte")
        assert k["status"] == "gepasst"
        # Bahnrichtung 052,8 Grad waagerecht ins Blatt gelegt heisst 052,8 - 90 = -37,2,
        # also 322,8 -- genau der an EDDL gemessene Wert.
        assert k["drehung"] == pytest.approx(322.8, abs=1.5)
        assert k["p1_x"] == pytest.approx(200)
    finally:
        conn.close()


def test_die_drehung_laesst_sich_ueberschreiben(client, db_pfad, tmp_path):
    """Bei zwei nah beieinanderliegenden Punkten ist der abgeleitete Wert schlecht;
    dann ist Nachjustieren von Hand der schnellere Weg."""
    from app.database import get_chart_dfs, get_connection

    c, _db, tmp = client
    (tmp / "aip_dfs").mkdir(exist_ok=True)
    _rohblatt(tmp / "aip_dfs" / "EDDL.flugplatzkarte.roh.png", 2200, 1000)
    c.post("/api/admin/aip-charts-dfs/EDDL/flugplatzkarte", json={
        "p1_x": 200, "p1_y": 500, "p1_lat": S_05R[0], "p1_lon": S_05R[1],
        "p2_x": 1970, "p2_y": 500, "p2_lat": S_23L[0], "p2_lon": S_23L[1],
        "drehung": 15.0,
    })
    conn = get_connection(db_pfad)
    try:
        assert get_chart_dfs(conn, "EDDL", "flugplatzkarte")["drehung"] == pytest.approx(15.0)
    finally:
        conn.close()


def test_bestaetigen_hebt_pruefen_auf(client, db_pfad):
    """Neues Blatt angesehen, Passung stimmt noch: quell_hash nachziehen, Status gepasst.

    Die Passung selbst bleibt dabei unangetastet -- das ist der Unterschied zum Uebernehmen
    eines Vorschlags, das es nicht mehr gibt.
    """
    from app.database import get_chart_dfs, get_connection, upsert_chart_dfs

    c, _db, _tmp = client
    conn = get_connection(db_pfad)
    try:
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="pruefen",
                         quell_hash="neu" + "0" * 61, drehung=322.8, **LAGE_OHNE_DREHUNG)
        conn.commit()
    finally:
        conn.close()
    assert c.post("/api/admin/aip-charts-dfs/EDDL/sichtflug/bestaetigen").status_code == 200
    conn = get_connection(db_pfad)
    try:
        k = get_chart_dfs(conn, "EDDL", "sichtflug")
        assert k["status"] == "gepasst"
        assert k["drehung"] == pytest.approx(322.8)
    finally:
        conn.close()


def _rohblatt(pfad, breite: int, hoehe: int) -> None:
    """Ein zeichnerisch belangloses, aber gueltiges PNG der gewuenschten Groesse.

    Die Groesse ist nicht belanglos: norden() rechnet die Blattecken durch die Passung, und
    ein 1x1-Bild ergaebe Grenzen, an denen kein Test etwas sieht.
    """
    from PIL import Image

    pfad.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (breite, hoehe), 255).save(pfad, "PNG")
```

- [ ] **Schritt 2 bis 6:** wie in den Tasks zuvor. Nach jeder ändernden Operation
  `_aip_karten_geaendert(request)` — ohne das erscheint eine frisch gepasste Karte im
  Kniebrett erst nach einem Neuladen, das dort innerhalb einer Sim-Sitzung nie stattfindet.

**Alte Endpunkte entfallen:** `/api/aip-charts`, `/aip-chart/{icao}.png`,
`/api/admin/aip-charts*`, `/api/aip-ground-charts`, `/aip-ground-chart/*`,
`/api/admin/aip-ground-charts*`, `/api/admin/aip-vorschlaege*`, `/aip-vorschlag/{id}.png`.

---

## Task 6: Der Job

**Dateien:**
- Ändern: `app/poller.py`
- Test: `tests/test_charts_dfs.py`

**Interfaces:**
- Produziert: `VatsimPoller._aip_hash_pruefen()`, Job-Kennung `aip_hash_pruefen`
- Entfällt: `_aip_auffrischen`, `_ground_charts_melden`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_es_gibt_genau_einen_kartenjob():
    """Zwei Jobs, die dieselbe Quelle abfragen, waren eine Folge der zwei Tabellen."""
    import inspect
    import re

    from app import poller

    quelle = re.sub(r"#[^\n]*", "", inspect.getsource(poller.VatsimPoller._register_jobs))
    assert 'id="aip_hash_pruefen"' in quelle
    assert "aip_auffrischen" not in quelle
    assert "ground_charts_melden" not in quelle


def test_der_job_haengt_am_faelligkeitsmerker():
    """interval ohne next_run_time plant den ersten Lauf eine Woche nach dem Anmelden --
    und angemeldet wird bei jedem Containerstart. Der Vorgaengerjob hat deshalb von seiner
    Einfuehrung bis zum 31.08.2026 kein einziges Mal gearbeitet.

    next_run_time allein macht daraus aber einen Deploy-Job. Erst der Merker in job_laeufe
    macht 'woechentlich' wirklich woechentlich.
    """
    import inspect

    from app import poller

    quelle = inspect.getsource(poller.VatsimPoller._aip_hash_pruefen)
    assert "job_faellig" in quelle and "job_erledigt" in quelle
```

- [ ] **Schritt 2 bis 5:** Job schreiben, alte entfernen, Tests, Commit.

---

## Task 7: Admin-Ansicht „AIP Charts DFS"

**Dateien:**
- Ändern: `app/static/admin.html`
- Test: `tests/test_charts_dfs_ui.py` (neu)

Eine Ansicht ersetzt beide alten. Enthält:

1. **Filterleiste** — Status als Mehrfachauswahl (Vorgabe: alles außer `gepasst`), Sorte
   als Mehrfachauswahl, Freitextsuche nach ICAO.
2. **Liste** — ICAO, Sorte, Status, AIRAC, Drehung, Blattlink, Aktionen.
3. **Seitenauswahl** — Vorschaubild und Seitennummer je Kapitelseite. **Sonst nichts** —
   keine „passt"-Spalte, kein Bahnton, keine Dateigröße. Beim Übernehmen wählt der Nutzer
   die Sorte, vorbelegt aus dem Ton.
4. **Passen-Maske** — Rohblatt zum Klicken, zwei Punkte mit Grad **und** Minuten getrennt,
   Drehung als eigenes Feld mit Vorschau.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_grad_und_minuten_sind_getrennte_felder():
    """Auf dem Blatt steht 'N 47 Grad 51,53 Minuten'. Ein einzelnes Feld '(Grad)' verleitet
    dazu, 47.5153 einzutragen -- gemeint sind 47,859. Der Unterschied sind zwoelf
    Kilometer; am 24.08.2026 genau so passiert."""
    for feld in ("p1-lat-grad", "p1-lat-min", "p1-lon-grad", "p1-lon-min",
                 "p2-lat-grad", "p2-lat-min", "p2-lon-grad", "p2-lon-min"):
        assert 'id="' + feld + '"' in ADMIN


def test_klicks_werden_auf_die_natuerliche_bildgroesse_umgerechnet():
    """Der Server kennt Originalpixel, der Browser skaliert auf seine Anzeigebreite. Bei
    einem 3101 px breiten Blatt in einem 900 px breiten Kasten laege jeder Punkt um mehr
    als das Dreifache daneben."""
    stelle = ADMIN_RUMPF.index("function dfsPassen(")
    block = ADMIN_RUMPF[stelle:stelle + 2000]
    assert "naturalWidth" in block and "naturalHeight" in block


def test_die_seitenauswahl_zeigt_kein_passt_haekchen():
    """Es war irrefuehrend: Dieselbe Automatik hat bei EDDK aus sechs Kapitelseiten die
    falsche gewaehlt (Nutzer, 24.08.2026)."""
    stelle = ADMIN_RUMPF.index("function dfsSeiten(")
    block = ADMIN_RUMPF[stelle:stelle + 2500]
    assert "passt" not in block


def test_statusfilter_erlaubt_mehrfachauswahl():
    stelle = ADMIN_RUMPF.index("dfsFilterStatus")
    block = ADMIN_RUMPF[stelle:stelle + 1500]
    assert "checkbox" in block.lower()


def test_drehung_ist_ein_eigenes_feld():
    assert 'id="dfs-drehung"' in ADMIN
```

- [ ] **Schritt 2 bis 6:** wie zuvor.

---

## Task 8: Transparenzregler im Frontend

**Dateien:**
- Ändern: `app/static/index.html`
- Test: `tests/test_charts_dfs_ui.py`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_der_deckkraftregler_erscheint_auch_bei_flugplatzkarten():
    """Er haengt heute an _aipKarteAktiv; liegt eine Flugplatzkarte, ist der null und der
    Regler verschwindet -- obwohl genau dann etwas zu regeln waere."""
    rumpf = _ohne_kommentare(QUELLE)
    stelle = rumpf.index("function _aipDeckkraftAnzeigen")
    block = rumpf[stelle:stelle + 400]
    assert "_groundAktiv" in block


def test_der_regler_bedient_beide_overlays():
    rumpf = _ohne_kommentare(QUELLE)
    stelle = rumpf.index("function _aipDeckkraftSetzen")
    block = rumpf[stelle:stelle + 600]
    assert "_aipKarteOverlay" in block and "_groundOverlay" in block
```

- [ ] **Schritt 2 bis 5:** beide Funktionen anpassen, Tests, Commit.

---

# Phase 4 — Abschluss

## Task 9: Vorschlagsweg und Sperre entfernen

**Dateien:**
- Ändern: `app/database.py`, `app/main.py`, `app/static/admin.html`
- Ändern: `tests/test_handpassung_schutz.py` (436 Zeilen)

Die Vorschlagstabelle, `HandpassungGesperrt`, `_handpassung_pruefen`, `vorschlag_anlegen`,
`get_vorschlaege`, `vorschlag_verwerfen`, `vorschlag_entfernen` und `verwaisen` entfallen.

- [ ] **Schritt 1: Belegen, dass die Sperre wirklich entbehrlich ist**

```python
def test_es_gibt_keinen_automatischen_schreibpfad_auf_eine_passung():
    """Die Sperre war noetig, solange ein Job Passungen rechnen und schreiben konnte. Nach
    dem Rueckbau schreibt nur noch der Admin-Endpunkt -- und der wird von einem Menschen
    ausgeloest.

    Der Test bindet an die Aufrufer: upsert_chart_dfs darf ausschliesslich aus main.py und
    aus der Migration heraus gerufen werden, nicht aus poller.py oder scripts/.
    """
    import subprocess

    treffer = subprocess.run(
        ["grep", "-rn", "upsert_chart_dfs", "--include=*.py", "app/", "scripts/"],
        capture_output=True, text=True).stdout.splitlines()
    dateien = {z.split(":")[0] for z in treffer}
    assert dateien <= {"app/database.py", "app/main.py"}, dateien
```

- [ ] **Schritt 2 bis 6:** Test laufen lassen, entfernen, `test_handpassung_schutz.py`
  löschen (es prüft eine Sperre, die es nicht mehr gibt — der Test oben ersetzt sie),
  Gesamtlauf, Commit.

**`test_handpassung_schutz.py` wird gelöscht, nicht angepasst.** Es prüft auf 436 Zeilen
den Schutz gegen einen automatischen Schreibpfad. Fällt der Pfad weg, prüft es nichts mehr.
Was bleiben muss, ist der eine Test aus Schritt 1.

---

## Task 10: Deploy und Gegenprobe

- [ ] **Schritt 1: Datenbank sichern**

```bash
sudo mkdir -p /root/charts-dfs-backup-2026-08-31
sudo cp /opt/friesenspy/data/friesenspy.db /root/charts-dfs-backup-2026-08-31/
sudo sqlite3 /opt/friesenspy/data/friesenspy.db \
  "SELECT quelle,status,COUNT(*) FROM aip_charts GROUP BY 1,2;
   SELECT sorte,status,COUNT(*) FROM aip_ground_charts GROUP BY 1,2;" \
  | tee /tmp/vorher.txt
```

- [ ] **Schritt 2: Voller Testlauf** — `pytest tests/ -q`

Erwartet: keine Fehlschläge. Die Gesamtzahl **sinkt** gegenüber 2130 — rund 1700 Zeilen
Tests prüfen gelöschtes Verhalten. Das ist richtig; entscheidend ist, dass kein Test
fehlschlägt und die neuen Dateien alle Anforderungen der Spec abdecken.

- [ ] **Schritt 3: Changelog und Version**

Ein Eintrag, `"highlight": false`.

- [ ] **Schritt 4: Deploy, dann sofort die Gegenprobe**

```bash
sudo sqlite3 /opt/friesenspy/data/friesenspy.db \
  "SELECT sorte,status,COUNT(*) FROM aip_charts_dfs GROUP BY 1,2;"
```

**Erwartet, aus dem Bestand gerechnet:**

| sorte | status | Anzahl |
|---|---|---|
| sichtflug | gepasst | 171 |
| sichtflug | auto | 275 |
| flugplatzkarte | auto | 30 |
| flugplatzkarte | offen | 10 |
| rollkarte | auto | 38 |
| rollkarte | offen | 32 |
| | **Summe** | **556** |

**Weicht eine Zahl ab, wird zurückgerollt** — die Sicherung aus Schritt 1 zurückspielen und
die Ursache suchen, bevor irgendetwas anderes geschieht.

- [ ] **Schritt 5: Im Admin ansehen**

Filter auf „alles außer gepasst" — es müssen 385 Zeilen erscheinen (275 + 30 + 10 + 38 + 32),
dazu die Plätze ohne Blatt als `nicht_gefunden`. Eine Karte probeweise passen und im
Kniebrett prüfen, dass sie erscheint.

- [ ] **Schritt 6: Nicht während eines Fluges deployen.** Jeder Push startet den Container
  neu und reißt offene Sitzungen ab; ob jemand fliegt, steht im nginx-Log (`/panel`,
  `/api/live`).

---

## Selbstprüfung dieses Plans

Gegen die Spec durchgegangen; jeder Abschnitt hat einen Task:

| Spec | Task |
|---|---|
| 2 Rückbau | 3, 4 |
| 3 Tabelle, 3.1 Migration | 1 |
| 4 Status | 2 |
| 5 Passen-Maske | 5 (Endpunkt), 7 (Maske) |
| 6 Liste, Filter, Seitenauswahl | 5, 7 |
| 7 Job | 6 |
| 8 die drei Fehler | 5 (Route), 8 (Regler), 9 (Vorschläge) |

**Zwei Punkte, die ein Bearbeiter kennen muss:**

1. **Die Reihenfolge ist zwingend.** Task 3 löscht Funktionen, die Task 4 bis 6 noch
   aufrufen. Wer Task 3 vorzieht, bricht den Import von `app/main.py` und damit den
   gesamten Dienst. Schritt 1 von Task 3 listet die Aufrufer deshalb **vor** dem Löschen
   auf.

2. **Die Migration hat keinen Rückwärtsgang im Code.** Sie ist durch den Merker und
   `ON CONFLICT DO NOTHING` gegen Doppellauf gesichert, aber wenn die Abbildung selbst
   falsch ist, hilft nur die Sicherung aus Task 10 Schritt 1. Deshalb steht die Gegenprobe
   mit den erwarteten Zahlen dort und nicht am Ende.
