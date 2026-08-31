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
| | **Summe** | **556** |

**Alle 110 Ground-ICAOs haben auch eine Sichtflugkarte.** Ohne den zweiteiligen Schlüssel
kollidieren genau diese 110 Zeilen — gemessen, nicht vermutet.

**`nicht_gefunden` wird geschrieben, nicht hergeleitet.** Eine frühere Fassung dieses Plans
ließ Plätze „ohne Zeile" als `nicht_gefunden` erscheinen. Gemessen am 31.08.2026 gibt es
davon **keinen einzigen**: `aip_charts` deckt `airport_links` mit 446 zu 446 exakt ab. Der
Status entsteht, wenn jemand die Seitenauswahl öffnet und keine passende Seite findet — dabei
entsteht auch die Zeile. Ein Platz **ohne** Zeile erscheint als **„— nicht nachgesehen"**;
das ist kein Status, sondern die Abwesenheit eines Eintrags (Spec 4.2).

**Die Klickpunkte der 446 Sichtflugkarten sind nicht verloren.** `rahmen_px` ist bei ihnen
das Klickprotokoll, keine Innerei der Automatik: `EDWE  rahmen_px = "85.0,238.0,1147.0,818.0"`
sind `p1_x,p1_y,p2_x,p2_y`, und `feld_nord/feld_west` bzw. `feld_sued/feld_ost` sind deren
Koordinaten. **Alle 446 Zeilen sind wohlgeformt, kein einziger Ausfall** — die Migration
füllt daraus `p1_*`/`p2_*` (Task 1). Bei den 110 Ground-Zeilen wurden die Punkte nie abgelegt;
dort bleiben sie leer. Das ist der einzige echte Verlust der Migration.

## Dateien

| Datei | Verantwortung |
|---|---|
| `app/database.py` | Tabelle `aip_charts_dfs`, Migration, Lese-/Schreibfunktionen |
| `app/ground_charts.py` | bleibt: `handpassung`, `norden`, `bahnfarbe`, `sorte_aus_ton`; `norden` bekommt Sorte und Drehschwelle (Task 4b) |
| `app/aip_charts.py` | schrumpft auf Beschaffung: AIRAC, Kapitelseiten, Bild, Ablage |
| `app/runway_ref.py` | unverändert |
| `app/main.py` | eine Endpunktgruppe `/api/admin/aip-charts-dfs`, alte entfallen |
| `app/poller.py` | ein Job `aip_hash_pruefen`, zwei alte entfallen |
| `scripts/aip_bestand.py` | schrumpft auf den Hash-Vergleich |
| `scripts/ground_chart_bestand.py` | **gelöscht** — geht in `aip_bestand.py` auf |
| `scripts/ground_chart_probe.py` | **gelöscht** |
| `scripts/aip_handpassung.py` | **gelöscht** — ruft `Rahmen`, `rahmen_finden`, `tick_positionen_mit_band` und `raster` **produktiv** (Zeilen 157–161), nicht nur im Kommentar |
| `scripts/aip_band_zeigen.py` | **gelöscht** — `Rahmen`, `rahmen_finden`, `tick_positionen_mit_band`, `band_grenzen` |
| `scripts/aip_schablonen.py` | **gelöscht** — `rahmen_finden`, `raster`, `tick_positionen`, `zeichen_im_band`, `_SCHABLONEN` |
| `app/static/admin.html` | eine Ansicht „AIP Charts DFS" |
| `app/static/index.html` | Transparenzregler, sonst unverändert |
| `tests/test_charts_dfs.py` (neu) | Tabelle, Migration, Statusübergänge |
| `tests/test_charts_dfs_api.py` (neu) | Endpunkte |
| `tests/test_charts_dfs_ui.py` (neu) | Admin- und Frontend-Quelltext |
| `tests/test_aip_charts.py` | 744 Zeilen — der Automatiktest, wird stark gekürzt |
| `tests/test_ground_charts.py` | Bahnvermessungsreste entfernen |
| `tests/test_handpassung_schutz.py` | 436 Zeilen — die Sperre **bleibt**, das Prädikat wechselt auf `status='gepasst'` (Task 9) |
| `tests/test_aip_api.py` | alte Endpunkte entfallen |

---

# Phase 1 — Daten

## Task 1: Tabelle und Migration

**Die Migration ist der gefährlichste Schritt des ganzen Plans.** Sie bewegt 556 Zeilen, und
`init_db` läuft bei **jedem Containerstart**. Eine Migration, die zweimal läuft und dabei
Nutzerarbeit überschreibt, wäre genau der Fehler, gegen den die ganze Vorgängerspec
geschrieben wurde.

**Und sie kann den Dienststart verhindern.** Das Migrationsmuster in `app/database.py:830-837`
lautet `except sqlite3.OperationalError: pass` — das ist ausschließlich für
`ALTER TABLE … ADD COLUMN` idempotent. Ein `INSERT` in eine Tabelle mit Primärschlüssel wirft
`IntegrityError`, und die ist **kein** `OperationalError`: `init_db` bräche ab, die App
startete nicht. Deshalb **drei** Riegel statt einem — Merker, `ON CONFLICT DO NOTHING` und
ein eigener `try`-Block mit `except sqlite3.Error`.

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
                   '85.0,238.0,1147.0,818.0', 0, 0, ?, '2026AUG20', 'gepasst', '',
                   '2026-08-30T12:00:00Z')""",
        (icao, quelle))
# rahmen_px traegt echte Werte, weil die Migration daraus die Klickpunkte gewinnt -- die
# Zahlen sind der Bestandswert von EDWE. seite_url ist leer, weil sie es im Bestand in
# ALLEN 446 Zeilen ist (gemessen 31.08.2026).


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


def test_die_klickpunkte_der_sichtflugkarten_wandern_mit(conn):
    """rahmen_px IST bei den Sichtflugkarten das Klickprotokoll, keine Innerei.

    Gemessen am Bestand: EDWE traegt rahmen_px = '85.0,238.0,1147.0,818.0', und
    feld_nord/feld_west (53.512167/6.886654) bzw. feld_sued/feld_ost (53.291635/7.564815)
    sind genau die Koordinaten dieser beiden Ecken. Alle 446 Zeilen sind wohlgeformt.

    Wer die Spalte als Automatikrest verwirft, zerstoert die Eingabe, die er aufheben will.
    """
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    k = get_chart_dfs(conn, "EDDL", "sichtflug")
    assert (k["p1_x"], k["p1_y"]) == pytest.approx((85.0, 238.0))
    assert (k["p2_x"], k["p2_y"]) == pytest.approx((1147.0, 818.0))
    assert k["p1_lat"] == pytest.approx(51.31)      # feld_nord
    assert k["p1_lon"] == pytest.approx(6.72)       # feld_west
    assert k["p2_lat"] == pytest.approx(51.26)      # feld_sued
    assert k["p2_lon"] == pytest.approx(6.81)       # feld_ost


def test_kaputtes_rahmen_px_bricht_die_migration_nicht(conn):
    """Im Bestand kommt das nicht vor -- aber eine Migration, die an einer einzigen
    unlesbaren Zeile abbricht, laesst die anderen 445 liegen."""
    conn.execute(
        """INSERT INTO aip_charts (icao, bild_hash, nord, sued, west, ost,
                                   feld_nord, feld_sued, feld_west, feld_ost,
                                   rahmen_px, tick_px_lat, tick_px_lon,
                                   quelle, airac, status, seite_url, geprueft_am)
           VALUES ('EDXX', 'a', 51.32, 51.25, 6.71, 6.82, 51.31, 51.26, 6.72, 6.81,
                   'kaputt', 0, 0, 'hand', '2026AUG20', 'gepasst', '', NULL)""")
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    assert migration_charts_dfs(conn) == 2
    assert get_chart_dfs(conn, "EDXX", "sichtflug")["p1_x"] is None
    assert get_chart_dfs(conn, "EDXX", "sichtflug")["status"] == "gepasst"


def test_quell_hash_bleibt_leer(conn):
    """Einen Startwert, den wir nicht haben, traegt man nicht ein.

    Naheliegend waere bild_hash -- fuer 439 der 446 Zeilen sogar richtig, denn
    genordet_rechnen gibt die DFS-Bytes unveraendert zurueck, wenn nicht gedreht wird
    (app/aip_charts.py, letzte Zeile: 'return roh, ...'), ohne Pillow-Re-Encode. Fuer die
    SIEBEN quer gedruckten Blaetter aber nicht: dort ist bild_hash der Hash des gedrehten,
    neu kodierten Blatts (app/main.py:4671) -- ein Wert, den die DFS nie geliefert hat.

    Leer heisst 'noch nie gesehen': Der erste Joblauf traegt den echten Rohbytes-Hash ein
    und meldet nichts. Kein einziger Fehlalarm, und die Regel haengt an einem leeren Feld
    statt an einem Vergleich mit dem AIRAC der Migration.
    """
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    k = get_chart_dfs(conn, "EDDL", "sichtflug")
    assert k["quell_hash"] == ""
    assert k["bild_hash"] == "a"          # der bleibt -- er ist der Cache-Schluessel


def test_die_seitennummer_bleibt_leer(conn):
    """seite_url ist im Bestand in ALLEN 446 Zeilen leer -- es gibt nichts zu uebernehmen.
    Die Nummer traegt der erste Joblauf nach (Task 6)."""
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    assert get_chart_dfs(conn, "EDDL", "sichtflug")["seite_nr"] is None


def test_die_urspruenglichen_spalten_wandern_nicht_mit(conn):
    """tick_px_*, rest_max und bahnen waren Innereien der Passungsrechnung -- rahmen_px
    ausdruecklich NICHT, dessen Inhalt wandert (s. o.). seite_url faellt, weil sie den
    AIRAC enthaelt und den naechsten Zyklus nicht ueberlebt (Task 6)."""
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    spalten = {r[1] for r in conn.execute("PRAGMA table_info(aip_charts_dfs)")}
    assert not spalten & {"rahmen_px", "tick_px_lat", "tick_px_lon", "rest_max", "bahnen",
                          "quelle", "seite_url"}
    assert {"p1_x", "p2_lon", "seite_nr", "status_vorher"} <= spalten
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
    -- Die SEITENNUMMER, nicht die URL: die enthaelt den AIRAC
    -- (https://aip.dfs.de/BasicVFR/2026AUG20/pages/8E6E....html) und liefert nach dem
    -- naechsten Zyklus 404 -- fuer ALLE Zeilen gleichzeitig, und zwar genau dann, wenn
    -- sich Blaetter tatsaechlich aendern koennten. Der dauerhafte Bezeichner ist
    -- airport_links.aip_url; der Job loest daraus bei jedem Lauf frisch auf.
    seite_nr      INTEGER,
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
    -- gepasst|auto|offen|nicht_gefunden|pruefen|verwaist. 'pruefen' OHNE Umlaut: der Wert
    -- wird in Python, SQL, JavaScript und Testliteralen verglichen.
    status        TEXT NOT NULL,
    status_vorher TEXT,                       -- woher 'pruefen' kam; siehe Task 5/6
    airac         TEXT NOT NULL DEFAULT '',
    geprueft_am   TEXT,
    PRIMARY KEY (icao, sorte)
);
```

- [ ] **Schritt 4: Migration schreiben**

```python
_DFS_SPALTEN = ("icao", "sorte", "seite_nr", "quell_hash", "bild_hash",
                "nord", "sued", "west", "ost",
                "feld_nord", "feld_sued", "feld_west", "feld_ost",
                "drehung", "mps",
                "p1_x", "p1_y", "p1_lat", "p1_lon",
                "p2_x", "p2_y", "p2_lat", "p2_lon",
                "status", "status_vorher", "airac", "geprueft_am")


def _punkte_aus_rahmen(rahmen_px, r):
    """Die beiden geklickten Rahmenecken aus dem Bestand zurueckgewinnen.

    ``rahmen_px`` ist bei den Sichtflugkarten das Klickprotokoll: vier Zahlen
    ``p1_x,p1_y,p2_x,p2_y``, und ``feld_nord/feld_west`` bzw. ``feld_sued/feld_ost`` sind
    deren Koordinaten. Alle 446 Bestandszeilen sind wohlgeformt (gemessen 31.08.2026); der
    Ausfallweg ist trotzdem noetig, damit eine einzige unlesbare Zeile nicht die anderen
    445 liegen laesst.

    Rueckgabe: acht Werte, oder achtmal None.
    """
    try:
        x1, y1, x2, y2 = (float(t) for t in (rahmen_px or "").split(","))
    except (ValueError, AttributeError):
        return (None,) * 8
    return (x1, y1, r["feld_nord"], r["feld_west"],
            x2, y2, r["feld_sued"], r["feld_ost"])


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
            """SELECT icao, rahmen_px, bild_hash, nord, sued, west, ost,
                      feld_nord, feld_sued, feld_west, feld_ost,
                      quelle, airac, status, geprueft_am
               FROM aip_charts""").fetchall():
        # 'verwaist' bleibt 'verwaist': Der Link ist verschwunden, die Passung nicht. Sie
        # kehrt zurueck, sobald der Link wieder auftaucht -- ein AIRAC-Wechsel benennt
        # Kapitelseiten um. Wer sie hier auf 'gepasst' hebt, verliert die Information.
        if r["status"] == "verwaist":
            status = "verwaist"
        else:
            status = "gepasst" if r["quelle"] == "hand" else "auto"
        p = _punkte_aus_rahmen(r["rahmen_px"], r)
        conn.execute(
            f"""INSERT INTO aip_charts_dfs ({', '.join(_DFS_SPALTEN)})
                VALUES ({', '.join('?' * len(_DFS_SPALTEN))})
                ON CONFLICT(icao, sorte) DO NOTHING""",
            # seite_nr bleibt None und quell_hash leer: seite_url ist im Bestand in ALLEN
            # 446 Zeilen leer, und den Rohbytes-Hash haben wir nicht -- bild_hash wird NACH
            # dem Drehen gebildet (app/main.py:4671) und stimmt bei den sieben quer
            # gedruckten Blaettern nicht. Beides traegt der erste Joblauf nach (Task 6);
            # leerer quell_hash heisst dort "noch nie gesehen: eintragen, nicht melden".
            (r["icao"], "sichtflug", None, "", r["bild_hash"] or "",
             r["nord"], r["sued"], r["west"], r["ost"],
             r["feld_nord"], r["feld_sued"], r["feld_west"], r["feld_ost"],
             0.0, 0.0, *p,
             status, None, r["airac"] or "", r["geprueft_am"]))
        n += 1

    # Flugplatz- und Rollkarten. ALLE bestehenden Passungen stammen von Claude, nicht vom
    # Nutzer -- sie fallen deshalb auf 'auto' zurueck, nicht auf 'gepasst'.
    # Die Klickpunkte sind hier UNRETTBAR: Sie wurden nie abgelegt. p1_*/p2_* bleiben leer;
    # wer nachjustieren will, klickt neu. Das ist der einzige echte Verlust der Migration.
    for r in conn.execute(
            """SELECT icao, sorte, quell_hash, bild_hash,
                      nord, sued, west, ost, feld_nord, feld_sued, feld_west, feld_ost,
                      drehung, mps, airac, status, geprueft_am
               FROM aip_ground_charts""").fetchall():
        status = "auto" if r["status"] == "gepasst" else "offen"
        conn.execute(
            f"""INSERT INTO aip_charts_dfs ({', '.join(_DFS_SPALTEN)})
                VALUES ({', '.join('?' * len(_DFS_SPALTEN))})
                ON CONFLICT(icao, sorte) DO NOTHING""",
            (r["icao"], r["sorte"], None, r["quell_hash"] or "",
             r["bild_hash"] or "",
             r["nord"], r["sued"], r["west"], r["ost"],
             r["feld_nord"], r["feld_sued"], r["feld_west"], r["feld_ost"],
             r["drehung"], r["mps"], None, None, None, None, None, None, None, None,
             status, None, r["airac"] or "", r["geprueft_am"]))
        n += 1

    conn.execute("INSERT INTO job_laeufe (name, zuletzt) VALUES (?, ?)",
                 ("migration_charts_dfs", _now_utc()))
    return n
```

**`ON CONFLICT DO NOTHING` ist die zweite Sicherung** neben dem Merker: Selbst wenn jemand
den Merker löscht, überschreibt der erneute Lauf keine Zeile, die inzwischen bearbeitet
wurde.

- [ ] **Schritt 5: In `init_db` aufrufen**

Nach den Migrationslisten, in einem **eigenen** `try`-Block — **nicht** im Block der
Spaltenmigrationen:

```python
        # EIGENER Block mit sqlite3.Error, nicht OperationalError. Das Muster darueber
        # (app/database.py:830-837) faengt nur OperationalError -- richtig fuer
        # "ALTER TABLE ... ADD COLUMN", das bei vorhandener Spalte genau den wirft. Ein
        # INSERT in eine Tabelle mit Primaerschluessel wirft dagegen IntegrityError, und
        # die ist KEIN OperationalError: init_db braeche ab, die App startete nicht.
        #
        # Ein Fehlschlag der Migration darf den Dienststart nicht verhindern -- er wird
        # protokolliert, die alten Tabellen stehen noch, und der Merker bleibt ungesetzt,
        # sodass der naechste Start es erneut versucht.
        try:
            uebernommen = migration_charts_dfs(conn)
            if uebernommen:
                logger.info("aip_charts_dfs: %d Zeilen uebernommen", uebernommen)
        except sqlite3.Error:
            logger.exception("aip_charts_dfs: Migration fehlgeschlagen")
```

- [ ] **Schritt 6: Tests laufen lassen** — `pytest tests/test_charts_dfs.py -v`, 11 PASS

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
- Produziert: `STATUS_DFS = ("gepasst", "auto", "offen", "nicht_gefunden", "pruefen", "verwaist")`
- Produziert: `PassungGesperrt(Exception)` — Nachfolgerin von `HandpassungGesperrt`

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


def test_verwaist_ist_ein_gueltiger_status(conn):
    """Eine Karte, deren Eintrag in airport_links verschwindet, wird NICHT geloescht --
    sie kehrt zurueck, sobald der Link wieder auftaucht (ein AIRAC-Wechsel benennt
    Kapitelseiten um). Nutzerentscheidung vom 30.08.2026."""
    from app.database import get_chart_dfs, upsert_chart_dfs
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="verwaist", **LAGE)
    assert get_chart_dfs(conn, "EDDL", "sichtflug")["status"] == "verwaist"


def test_eine_gepasste_karte_wird_nicht_stillschweigend_ueberschrieben(conn):
    """Die Sperre bleibt -- nur ihr Praedikat wechselt von quelle='hand' auf
    status='gepasst'.

    Der Rueckbau nimmt zwar dem JOB die Faehigkeit, eine Passung zu rechnen. Der
    Seitenwaehler bleibt aber und schreibt bei gescheiterter Passung alle Lagefelder auf 0
    (app/main.py:4694). Nach dem Rueckbau ist ``passung`` dort IMMER None -- der nullende
    Zweig waere der einzige. Genau das ist am 25.08.2026 schon einmal passiert: EDAZ stand
    danach auf 0/0/0/0.
    """
    from app.database import PassungGesperrt, upsert_chart_dfs
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst", **LAGE)
    with pytest.raises(PassungGesperrt):
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="auto",
                         **{**LAGE, "nord": 0, "sued": 0, "west": 0, "ost": 0})


def test_mit_ausdruecklicher_ansage_geht_es_doch(conn):
    """Der Nutzer selbst muss eine gepasste Karte neu passen koennen -- die Sperre richtet
    sich gegen stillschweigendes Ueberschreiben, nicht gegen ihn."""
    from app.database import get_chart_dfs, upsert_chart_dfs
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst", **LAGE)
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst",
                     **{**LAGE, "drehung": 7.5}, hand_ueberschreiben=True)
    assert get_chart_dfs(conn, "EDDL", "sichtflug")["drehung"] == pytest.approx(7.5)


def test_der_status_allein_darf_ohne_ansage_wechseln(conn):
    """Der Job setzt status='pruefen' und quell_hash auf einer gepassten Karte -- er ruehrt
    die Lage nicht an. Wuerde die Sperre auch das abweisen, koennte er nichts melden."""
    from app.database import get_chart_dfs, upsert_chart_dfs
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst", **LAGE)
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="pruefen",
                     status_vorher="gepasst", quell_hash="n" * 64)
    k = get_chart_dfs(conn, "EDDL", "sichtflug")
    assert k["status"] == "pruefen" and k["status_vorher"] == "gepasst"
    assert k["nord"] == pytest.approx(LAGE["nord"])


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
# 'pruefen' OHNE Umlaut: der Wert wird in Python, SQL, JavaScript und Testliteralen
# verglichen -- ein Umlaut darin ist eine Fehlerquelle ohne Gegenwert.
STATUS_DFS = ("gepasst", "auto", "offen", "nicht_gefunden", "pruefen", "verwaist")
SORTEN_DFS = ("sichtflug", "flugplatzkarte", "rollkarte")

# Die Lagefelder. Wer eines davon anfasst, passt -- und braucht bei einer gepassten Karte
# die ausdrueckliche Ansage. Wer nur Status, quell_hash oder seite_nr setzt, nicht.
_LAGE_FELDER = ("nord", "sued", "west", "ost",
                "feld_nord", "feld_sued", "feld_west", "feld_ost",
                "drehung", "mps",
                "p1_x", "p1_y", "p1_lat", "p1_lon", "p2_x", "p2_y", "p2_lat", "p2_lon")


class PassungGesperrt(Exception):
    """Eine vom Nutzer gepasste Karte sollte stillschweigend ueberschrieben werden."""


def upsert_chart_dfs(conn: sqlite3.Connection, icao: str, sorte: str,
                     hand_ueberschreiben: bool = False, **felder) -> None:
    """Karte setzen. ``status`` ist Pflicht und muss aus STATUS_DFS stammen.

    **Die Sperre bleibt, das Praedikat wechselt** -- von ``quelle='hand'`` auf
    ``status='gepasst'``. Der Rueckbau nimmt zwar dem Job die Faehigkeit, eine Passung zu
    rechnen; der Seitenwaehler bleibt aber und schreibt bei gescheiterter Passung alle
    Lagefelder auf 0 (heute app/main.py:4694). Nach dem Rueckbau ist ``passung`` dort
    IMMER None -- der nullende Zweig waere der einzige. Am 25.08.2026 hat genau das EDAZ
    auf 0/0/0/0 gesetzt.

    Die Sperre greift nur, wenn ein LAGEfeld mitkommt. Der Job setzt Status, ``quell_hash``
    und ``seite_nr`` -- er soll melden koennen, ohne die Passung anzuruehren.
    """
    code = (icao or "").strip().upper()
    if sorte not in SORTEN_DFS:
        raise ValueError(f"unbekannte Sorte: {sorte!r}")
    if felder.get("status") not in STATUS_DFS:
        raise ValueError(f"unbekannter Status: {felder.get('status')!r}")
    if not hand_ueberschreiben and any(f in felder for f in _LAGE_FELDER):
        alt = conn.execute(
            "SELECT status FROM aip_charts_dfs WHERE icao = ? AND sorte = ?",
            (code, sorte)).fetchone()
        if alt is not None and alt["status"] == "gepasst":
            raise PassungGesperrt(
                f"{code}/{sorte} ist vom Nutzer gepasst -- hand_ueberschreiben noetig")
    # Nur die mitgegebenen Felder nachziehen. Ein Aufruf, der bloss den Status aendert
    # (etwa der Job mit status='pruefen'), darf die Passung nicht auf Null zuruecksetzen.
    setzbar = [f for f in _DFS_SPALTEN
               if f not in ("icao", "sorte", "geprueft_am") and f in felder]
    if not setzbar:
        raise ValueError("nichts zu setzen")
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
- Ändern: `scripts/aip_bestand.py` (347 → ~140)
- Löschen: `scripts/ground_chart_bestand.py`, `scripts/ground_chart_probe.py`,
  `scripts/aip_handpassung.py`, `scripts/aip_band_zeigen.py`, `scripts/aip_schablonen.py`

- [ ] **Schritt 1: Die drei Skripte gehen mit — sie brechen sonst beim Import**

Eine frühere Fassung dieses Plans wollte `aip_handpassung.py` „prüfen und entscheiden" mit
der Begründung, es erwähne die Automatik nur im Kommentar. **Es ruft sie in vier Zeilen
auf** (157–161: `A.Rahmen`, `A.rahmen_finden`, `A.tick_positionen_mit_band`, `A.raster`).
Ohne Task 3 lief es; nach Task 3 bricht es beim Import. Dasselbe gilt für zwei weitere:

| Skript | ruft |
|---|---|
| `scripts/aip_handpassung.py` | `Rahmen`, `rahmen_finden`, `tick_positionen_mit_band`, `raster` |
| `scripts/aip_band_zeigen.py` | `Rahmen`, `rahmen_finden`, `tick_positionen_mit_band`, `band_grenzen` |
| `scripts/aip_schablonen.py` | `rahmen_finden`, `raster`, `tick_positionen`, `zeichen_im_band`, `_SCHABLONEN` |

Alle drei sind Werkzeuge der Automatik: Sie zeigen Rahmen, Bänder und Schablonen an, damit
man die Erkennung nachvollziehen kann. Fällt die Erkennung, haben sie keinen Gegenstand
mehr. Die Passen-Maske aus Task 7 kann alles, was `aip_handpassung.py` konnte, und mehr —
sie zeigt das Blatt.

**Gegenprobe vor dem Löschen:**

```bash
grep -rn "aip_handpassung\|aip_band_zeigen\|aip_schablonen" --include=*.py --include=*.md \
     --include=*.yml app/ scripts/ tests/ docs/ .github/
```

Erwartet: nur Treffer in den Skripten selbst und in dieser Planungsdatei. Gibt es einen
Aufrufer in `.github/workflows/`, wird der zuerst entfernt.

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
    """Fuer jede Karte das Rohblatt holen und den Hash vergleichen.

    Weicht er ab, wird status='pruefen' gesetzt (mit status_vorher) und das neue Blatt
    daneben gelegt. Sonst passiert nichts. Kein Rechnen, kein Schreiben einer Passung.

    **Die Seite wird als Nummer gefuehrt, nicht als URL.** ``seite_url`` enthielt den AIRAC
    (https://aip.dfs.de/BasicVFR/2026AUG20/pages/8E6E....html) und liefert nach dem
    naechsten Zyklus 404 -- fuer ALLE Zeilen gleichzeitig, und zwar genau dann, wenn sich
    Blaetter tatsaechlich aendern koennten. Der Lauf loest deshalb bei jedem Durchgang
    ueber ``airport_links.aip_url`` (ohne AIRAC, Meta-Refresh) frisch auf.

    **Zeilen ohne seite_nr werden NICHT uebersprungen.** Im Bestand ist ``seite_url`` in
    ALLEN 446 Sichtflugzeilen leer -- ein Lauf, der nur Zeilen mit gesetzter Seite prueft,
    pruefte 110 von 556 und ausgerechnet keine Sichtflugkarte. Fuer eine Zeile ohne
    ``seite_nr`` sucht der Lauf einmalig die Kapitelseite, deren Bild dem gespeicherten
    ``bild_hash`` entspricht, und merkt sich die Nummer. Findet er keine, bleibt sie leer
    und die Zeile erscheint als "Seite unbekannt" -- sichtbar, nicht stumm uebersprungen.

    Kosten: **ein** Abruf je Karte, nicht zwei -- das Bild steckt als data-URI in derselben
    HTML-Seite (``bild_aus_html``). Dazu je Platz einen fuer die Kapitelaufloesung.
    """
```

---

## Task 4b: `norden` bekommt die Sorte und eine Drehschwelle

Zwei Fehler, die erst auffallen, wenn dieselbe Funktion **beide** Kartentypen bedient — was
sie ab Task 5 tut.

**Dateien:**
- Ändern: `app/ground_charts.py`
- Test: `tests/test_ground_charts.py`

**Interfaces:**
- Ändert: `norden(png: bytes, p: GroundPassung, sorte: str) -> tuple[bytes, dict] | None`
- Produziert: `FELD_SAUM_M = {"sichtflug": 0.0, "flugplatzkarte": 1000.0, "rollkarte": 1000.0}`
- Produziert: `DREH_SCHWELLE = 0.25`

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

```python
# tests/test_ground_charts.py
def test_der_saum_haengt_an_der_sorte():
    """Zwei Bedeutungen in einer Spalte waeren sonst die Folge.

    Das alte aip_charts.handpassung legte feld_* EXAKT auf die geklickten Rahmenecken --
    richtig, denn bei einer Sichtflugkarte definiert der Rahmen das Kartenfeld praezise.
    ground_charts.norden legt es auf die Huelle plus 1000 m -- richtig fuer eine
    Flugplatzkarte, wo die Passpunkte zwei Bahnschwellen mitten auf dem Platz sind und die
    Karte sonst erst einschaltete, wenn man schon auf der Bahn steht.

    Beides durch dieselbe Funktion und ohne Sorte hiesse: die 171 migrierten
    Sichtflugzeilen behielten ihr rahmengenaues feld_*, jede neu gesetzte bekaeme das
    andere -- und die Ebene schaltete auf allen vier Seiten einen Kilometer zu frueh ein.
    """
    im = _blatt([(200, 500, 1970, 500, 28)], groesse=(2200, 1000))
    p = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    _, sicht = ground_charts.norden(_png(im), p, "sichtflug")
    _, platz = ground_charts.norden(_png(im), p, "flugplatzkarte")
    # Mit Saum liegt das Feld weiter aussen -- also naeher an den Blattgrenzen.
    assert platz["feld_nord"] > sicht["feld_nord"]
    assert platz["feld_sued"] < sicht["feld_sued"]
    assert platz["feld_ost"] > sicht["feld_ost"]
    assert platz["feld_west"] < sicht["feld_west"]


def test_ohne_saum_ist_das_feld_genau_die_punkthuelle():
    """Die Gegenprobe zum rahmengenauen Verhalten der 171 Bestandszeilen."""
    im = _blatt([(200, 500, 1970, 500, 28)], groesse=(2200, 1000))
    p = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    _, g = ground_charts.norden(_png(im), p, "sichtflug")
    assert g["feld_nord"] == pytest.approx(max(S_05R[0], S_23L[0]), abs=1e-4)
    assert g["feld_sued"] == pytest.approx(min(S_05R[0], S_23L[0]), abs=1e-4)


def test_eine_winzige_drehung_dreht_nicht():
    """An EDWE und EDAZ gemessen ergibt die Rechnung aus den Rahmenecken 0,04 bis 0,09 Grad.

    rotate(expand=True) liesse die Leinwand um ein bis zwei Pixel wachsen und jedes Pixel
    interpolieren -- an einem Blatt, dessen Gradnetzstriche drei Pixel breit sind. Der
    bild_hash aenderte sich, obwohl inhaltlich nichts geschieht, und der Job meldete beim
    naechsten Lauf eine Aenderung.
    """
    im = _blatt([(200, 500, 1970, 500, 28)], groesse=(2200, 1000))
    # Zwei Punkte auf einer fast waagerechten Linie, die genau nach Osten zeigt.
    p = ground_charts.handpassung((200.0, 500.0), (51.28, 6.75), (1970.0, 500.0), (51.28, 6.80))
    gedreht, g = ground_charts.norden(_png(im), p, "sichtflug")
    assert Image.open(io.BytesIO(gedreht)).size == im.size
    assert g["drehung"] == 0.0


def test_rechte_winkel_werden_verlustfrei_gedreht():
    """Die sieben quer gedruckten Blaetter sind genau dieser Fall. transpose() ist
    verlustfrei, rotate(resample=BICUBIC) interpoliert jedes Pixel."""
    import inspect
    import re

    quelle = re.sub(r"#[^\n]*", "", inspect.getsource(ground_charts.norden))
    assert "transpose" in quelle
    assert "ROTATE_90" in quelle and "ROTATE_180" in quelle and "ROTATE_270" in quelle
```

- [ ] **Schritt 2: Tests laufen lassen** — vier FAIL

- [ ] **Schritt 3: `norden` umbauen**

```python
# Wie weit ueber die Passpunkte hinaus die Ebene noch einschaltet.
#
# Bei einer Sichtflugkarte sind die Passpunkte zwei Rahmenecken -- der Rahmen IST das
# Kartenfeld, ein Saum waere schlicht falsch. Bei einer Flugplatzkarte sind es zwei
# Bahnschwellen mitten auf dem Platz; ohne Saum schaltete die Karte erst ein, wenn man
# schon auf der Bahn steht.
FELD_SAUM_M = {"sichtflug": 0.0, "flugplatzkarte": 1000.0, "rollkarte": 1000.0}

# Unter dieser Schwelle wird nicht gedreht. Aus zwei Rahmenecken faellt fast immer ein
# Restwinkel von Hundertsteln bis Zehnteln Grad an (an EDWE und EDAZ: 0,04 bis 0,09).
# rotate(expand=True) liesse die Leinwand um ein bis zwei Pixel wachsen und interpolierte
# jedes Pixel -- an einem Blatt mit drei Pixel breiten Gradnetzstrichen. Der bild_hash
# aenderte sich ohne inhaltlichen Grund.
DREH_SCHWELLE = 0.25

_VIERTEL = {90: Image.Transpose.ROTATE_90,
            180: Image.Transpose.ROTATE_180,
            270: Image.Transpose.ROTATE_270}


def _drehen(im: Image.Image, drehung: float) -> tuple[Image.Image, float]:
    """Blatt nach Norden drehen. Rueckgabe: Bild und die TATSAECHLICH angewandte Drehung."""
    if min(drehung % 360.0, 360.0 - (drehung % 360.0)) < DREH_SCHWELLE:
        return im, 0.0
    for grad, wie in _VIERTEL.items():
        if abs((drehung % 360.0) - grad) < DREH_SCHWELLE:
            # Verlustfrei -- genau der Fall der sieben quer gedruckten Blaetter.
            return im.transpose(wie), float(grad)
    return im.rotate(-drehung, resample=Image.BICUBIC, expand=True,
                     fillcolor=(0, 0, 0, 0)), drehung
```

`norden` nimmt `sorte` als drittes Argument, holt den Saum aus `FELD_SAUM_M`, dreht über
`_drehen` und gibt die **tatsächlich angewandte** Drehung in `grenzen["drehung"]` zurück —
sonst schriebe der Aufrufer 0,07° in die Datenbank, während das Blatt ungedreht liegt.

**Die vier Blattecken werden weiterhin durch die Abbildung geschickt**, nicht die Hülle der
Passpunkte — das ist die Absicherung gegen den 45-Prozent-Maßstabsfehler und bleibt
unverändert. Nur `feld_*` bekommt den sortenabhängigen Saum.

- [ ] **Schritt 4: Bestandstests nachziehen**

Alle bisherigen Aufrufe von `norden` in `tests/test_ground_charts.py` brauchen das dritte
Argument. `test_feldgrenzen_sind_die_punkthuelle_nicht_die_blattgrenzen` und
`test_das_feld_ragt_nie_ueber_das_blatt_hinaus` prüfen den Saumfall — dort
`"flugplatzkarte"` übergeben.

- [ ] **Schritt 5: Tests laufen lassen** — `pytest tests/test_ground_charts.py -v`

- [ ] **Schritt 6: Commit**

```bash
git add app/ground_charts.py tests/test_ground_charts.py
git commit -m "norden: Saum haengt an der Sorte, keine Drehung unter 0,25 Grad"
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
| `POST /api/admin/aip-charts-dfs/{icao}/nicht-gefunden` | Status `nicht_gefunden` **schreiben** |
| `POST /api/admin/aip-charts-dfs/{icao}/{sorte}` | Passung setzen: zwei Punkte + Drehung |
| `POST /api/admin/aip-charts-dfs/{icao}/{sorte}/uebernehmen` | neues Blatt gilt, `quell_hash` nachziehen, → `gepasst` |
| `POST /api/admin/aip-charts-dfs/{icao}/{sorte}/verwerfen` | altes Blatt bleibt, `quell_hash` **trotzdem** nachziehen, → `status_vorher` |
| `DELETE /api/admin/aip-charts-dfs/{icao}/{sorte}` | Karte entfernen |

**Aus `pruefen` heraus gibt es drei Wege, und keiner endet pauschal auf `gepasst`.** Beim
Setzen von `pruefen` merkt sich der Job den bisherigen Status in `status_vorher`; „verwerfen"
stellt ihn zurück. Ohne das landete eine der 42 als `offen` migrierten Zeilen — Lagefelder
alle 0 — nach einem Blattwechsel auf `gepasst` und damit im Kniebrett, mit
`nord=sued=west=ost=0`.

**Auch „verwerfen" zieht `quell_hash` nach.** Sonst findet der nächste Wochenlauf denselben
abweichenden Hash und setzt die Zeile erneut auf `pruefen` — die Liste wäre nach dem ersten
Verwerfen dauerhaft unaufräumbar. Diese Falle war bei der Vorschlagstabelle schon einmal
gestellt und behoben (`app/database.py:371-377`).

**Die Rohbild-Route bekommt einen eigenen Pfad**, nicht `.roh.png` als Suffix — **und
`require_admin`**, das die heute erreichbare Route nicht hat und die unerreichbare schon:

```python
@app.get("/aip-chart-roh/{icao}/{sorte}.png", include_in_schema=False)
async def aip_chart_roh(icao: str, sorte: str, _=Depends(require_admin)):
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
    gefunden hast.' Ein Platz OHNE Zeile erscheint mit status=None -- die Oberflaeche
    schreibt dafuer 'nicht nachgesehen'.

    Das ist KEIN Status: 'nicht_gefunden' heisst 'nachgesehen, es gibt keine', und das ist
    eine Aussage, die jemand getroffen hat. Waere sie hergeleitet, liesse sie sich nicht
    speichern -- die Arbeitsliste bliebe dauerhaft rund 780 Eintraege lang, in denen nichts
    abhakbar ist.
    """
    c, db_pfad, _tmp = client
    conn = get_connection(db_pfad)
    try:
        conn.execute("INSERT INTO airport_links (icao, aip_url, updated_at) "
                     "VALUES ('EDZZ', 'https://x/k.html', '2026-08-31T00:00:00Z')")
        conn.commit()
    finally:
        conn.close()
    d = c.get("/api/admin/aip-charts-dfs").json()
    zzz = [k for k in d["charts"] if k["icao"] == "EDZZ"]
    assert zzz and zzz[0]["status"] is None


def test_nicht_gefunden_wird_geschrieben(client, db_pfad):
    """Wer die Seitenauswahl oeffnet und keine passende Seite findet, haelt das fest --
    dabei entsteht die Zeile. Sonst kaeme derselbe Platz beim naechsten Durchgang wieder."""
    from app.database import get_chart_dfs, get_connection

    c, db_pfad, _tmp = client
    antwort = c.post("/api/admin/aip-charts-dfs/EDZZ/nicht-gefunden",
                     json={"sorte": "rollkarte"})
    assert antwort.status_code == 200
    conn = get_connection(db_pfad)
    try:
        assert get_chart_dfs(conn, "EDZZ", "rollkarte")["status"] == "nicht_gefunden"
    finally:
        conn.close()


def test_eine_gepasste_karte_wird_ueber_die_api_nicht_stillschweigend_genullt(client, db_pfad):
    """Der Seitenwaehler schrieb bei gescheiterter Passung alle Lagefelder auf 0
    (app/main.py:4694). Nach dem Rueckbau ist die Passung dort IMMER None -- der nullende
    Zweig waere der einzige. Am 25.08.2026 hat genau das EDAZ auf 0/0/0/0 gesetzt.

    Deshalb schreibt der Seitenwaehler bei unveraendertem Blatthash GAR NICHTS: Er waehlt
    die Seite, er passt nicht.
    """
    from app.database import get_chart_dfs, get_connection, upsert_chart_dfs

    c, db_pfad, _tmp = client
    conn = get_connection(db_pfad)
    try:
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst", **LAGE)
        conn.commit()
    finally:
        conn.close()
    c.post("/api/admin/aip-charts-dfs/EDDL/seite",
           json={"sorte": "sichtflug", "seite_nr": 3})
    conn = get_connection(db_pfad)
    try:
        k = get_chart_dfs(conn, "EDDL", "sichtflug")
        assert k["nord"] == pytest.approx(LAGE["nord"])
        assert k["status"] == "gepasst"
    finally:
        conn.close()


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


def test_uebernehmen_hebt_pruefen_auf(client, db_pfad):
    """Neues Blatt angesehen, Passung stimmt noch: quell_hash nachziehen, Status gepasst.

    Die Passung selbst bleibt dabei unangetastet.
    """
    from app.database import get_chart_dfs, get_connection, upsert_chart_dfs

    c, db_pfad, _tmp = client
    conn = get_connection(db_pfad)
    try:
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst", **LAGE)
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="pruefen",
                         status_vorher="gepasst", quell_hash="n" * 64)
        conn.commit()
    finally:
        conn.close()
    assert c.post("/api/admin/aip-charts-dfs/EDDL/sichtflug/uebernehmen").status_code == 200
    conn = get_connection(db_pfad)
    try:
        k = get_chart_dfs(conn, "EDDL", "sichtflug")
        assert k["status"] == "gepasst"
        assert k["drehung"] == pytest.approx(LAGE["drehung"])
    finally:
        conn.close()


def test_verwerfen_stellt_den_alten_status_zurueck(client, db_pfad):
    """NICHT pauschal auf 'gepasst'. Eine der 42 als 'offen' migrierten Zeilen hat
    Lagefelder von 0 -- sie landete sonst nach einem Blattwechsel im Kniebrett, mit
    nord=sued=west=ost=0."""
    from app.database import get_chart_dfs, get_connection, upsert_chart_dfs

    c, db_pfad, _tmp = client
    conn = get_connection(db_pfad)
    try:
        upsert_chart_dfs(conn, "EDZZ", "rollkarte", status="offen",
                         **{k: 0.0 for k in LAGE})
        upsert_chart_dfs(conn, "EDZZ", "rollkarte", status="pruefen",
                         status_vorher="offen", quell_hash="n" * 64)
        conn.commit()
    finally:
        conn.close()
    assert c.post("/api/admin/aip-charts-dfs/EDZZ/rollkarte/verwerfen").status_code == 200
    conn = get_connection(db_pfad)
    try:
        assert get_chart_dfs(conn, "EDZZ", "rollkarte")["status"] == "offen"
    finally:
        conn.close()


def test_auch_verwerfen_zieht_den_quell_hash_nach(client, db_pfad):
    """Sonst findet der naechste Wochenlauf denselben abweichenden Hash und setzt die Zeile
    erneut auf 'pruefen' -- die Liste waere nach dem ersten Verwerfen dauerhaft
    unaufraeumbar. Dieselbe Falle war bei der Vorschlagstabelle schon einmal gestellt."""
    from app.database import get_chart_dfs, get_connection, upsert_chart_dfs

    c, db_pfad, _tmp = client
    conn = get_connection(db_pfad)
    try:
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst",
                         quell_hash="alt" + "0" * 61, **LAGE)
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="pruefen",
                         status_vorher="gepasst", quell_hash="n" * 64)
        conn.commit()
    finally:
        conn.close()
    c.post("/api/admin/aip-charts-dfs/EDDL/sichtflug/verwerfen")
    conn = get_connection(db_pfad)
    try:
        assert get_chart_dfs(conn, "EDDL", "sichtflug")["quell_hash"] == "n" * 64
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

Der Passen-Endpunkt ruft `ground_charts.handpassung` und dann
`ground_charts.norden(png, passung, sorte)` — **mit der Sorte** (Task 4b): Bei `sichtflug`
ist der Saum 0, bei Flugplatz- und Rollkarten 1000 m. Geschrieben wird die von `norden`
**tatsächlich angewandte** Drehung, nicht die gerechnete; unter 0,25° sind das 0,0.

Weil der Nutzer selbst passt, ist `hand_ueberschreiben=True` richtig — die Sperre aus Task 2
richtet sich gegen stillschweigendes Überschreiben, nicht gegen ihn. Der **Seitenwähler**
ruft `upsert_chart_dfs` dagegen ohne dieses Flag und **ohne ein einziges Lagefeld**: Er wählt
die Seite, er passt nicht.

**Alte Endpunkte entfallen:** `/api/aip-charts`, `/aip-chart/{icao}.png`,
`/api/admin/aip-charts*`, `/api/aip-ground-charts`, `/aip-ground-chart/*`,
`/api/admin/aip-ground-charts*`, `/api/admin/aip-vorschlaege*`, `/aip-vorschlag/{id}.png`.

**Die Blätter bekommen einen neuen Pfad, und die Migration verschiebt sie mit.** Heute liegen
sie unter `<db>/aip/<ICAO>.png` und `<db>/aip_ground/<ICAO>.png`; der Ground-Pfad ist **nur
auf ICAO geschlüsselt** (`app/main.py:4243`), Flugplatz- und Rollkarte desselben Platzes
überschrieben sich also. Künftig:

```
<db>/aip_dfs/<ICAO>.<sorte>.png                 # abgelegt, ggf. gedreht
<db>/aip_dfs/<ICAO>.<sorte>.roh.png             # Rohblatt, zum Klicken
<db>/aip_dfs/<ICAO>.<sorte>.neu.<hash8>.png     # neues Blatt bei Status 'pruefen'
```

Der Hash im Namen des neuen Blatts ist kein Schmuck: Ändert sich ein Blatt ein **zweites**
Mal, während `pruefen` noch steht, sieht der Nutzer sonst ein anderes Bild als das, was er
bestätigt. **Ohne das Verschieben zeigt nach dem Deploy jede Karte ins Leere** — der Schritt
gehört in Task 10, vor die Gegenprobe.

---

## Task 6: Der Job

**Dateien:**
- Ändern: `app/poller.py`
- Test: `tests/test_charts_dfs.py`

**Interfaces:**
- Produziert: `VatsimPoller._aip_hash_pruefen()`, Job-Kennung `aip_hash_pruefen`
- Entfällt: `_aip_auffrischen`, `_ground_charts_melden`

**Was der Job je Zeile tut:**

1. Kapitel über `airport_links.aip_url` auflösen (ohne AIRAC, Meta-Refresh), Seite `seite_nr`
   holen.
2. Ist `seite_nr` leer: einmalig die Kapitelseite suchen, deren Bild dem gespeicherten
   `bild_hash` entspricht, und die Nummer merken. Ohne Fund bleibt sie leer — die Zeile
   erscheint als „Seite unbekannt", nicht stumm übersprungen.
3. Rohbytes hashen, mit `quell_hash` vergleichen.
4. Weicht er ab → `status_vorher` sichern, Status `pruefen`, neues Blatt daneben legen, SSE
   `{"type": "aip_charts"}`.
5. Steht der Platz nicht mehr in `airport_links` → Status `verwaist` (nicht löschen).

**Kosten: ein Abruf je Karte**, nicht zwei — das Bild steckt als data-URI in derselben
HTML-Seite (`bild_aus_html`). 556 Zeilen, plus je Platz einen für die Kapitelauflösung. Der
Kommentar in `app/poller.py:569`, der 1100 nennt, war schon dort falsch.

**Ein leerer `quell_hash` wird eingetragen, nicht verglichen.** Nach der Migration ist er in
allen 556 Zeilen leer — den Rohbytes-Hash gab es nie zu übernehmen (`bild_hash` wird nach dem
Drehen gebildet und stimmt bei den sieben quer gedruckten Blättern nicht). Der erste Lauf
trägt ihn ein und meldet nichts:

```python
if not zeile["quell_hash"]:
    # Noch nie gesehen -- es gibt nichts zu vergleichen. Eintragen, nicht melden.
    # Ohne diesen Zweig meldete der erste Lauf alle 556 Karten als geaendert.
    status_melden(conn, icao, sorte, quell_hash=roh_hash)
    continue
if roh_hash != zeile["quell_hash"]:
    ...
```

**Verglichen wird immer Roh gegen Roh**, nie Roh gegen Gedreht — einen wiederkehrenden
Fehlalarm kann es deshalb nicht geben. Betroffen war ausschließlich der Startwert.

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


def test_ein_leerer_quell_hash_wird_eingetragen_nicht_gemeldet():
    """Nach der Migration ist er in allen 556 Zeilen leer -- den Rohbytes-Hash gab es nie zu
    uebernehmen. Ohne diesen Zweig meldete der erste Lauf alle 556 Karten als geaendert.

    Die Regel haengt an einem leeren Feld, NICHT an einem Vergleich mit dem AIRAC der
    Migration: Was in sechs Monaten niemand mehr versteht, wird beim naechsten Umbau
    herausgeworfen.
    """
    import inspect
    import re

    from app import poller

    quelle = re.sub(r"#[^\n]*", "", inspect.getsource(poller.VatsimPoller._aip_hash_pruefen))
    stelle = quelle.index("quell_hash")
    assert "not " in quelle[max(0, stelle - 40):stelle + 40]


def test_der_job_traegt_fehlende_seitennummern_nach():
    """seite_url ist im Bestand in ALLEN 446 Sichtflugzeilen leer. Ein Lauf, der nur Zeilen
    mit gesetzter Seite prueft, pruefte 110 von 556 -- und ausgerechnet keine
    Sichtflugkarte."""
    import inspect

    from app import poller

    quelle = inspect.getsource(poller.VatsimPoller._aip_hash_pruefen)
    assert "seite_nr" in quelle and "bild_hash" in quelle


def test_der_job_merkt_sich_den_vorherigen_status():
    """Ohne status_vorher landete eine der 42 als 'offen' migrierten Zeilen -- Lagefelder
    alle 0 -- nach einem Blattwechsel auf 'gepasst' und damit im Kniebrett."""
    import inspect

    from app import poller

    quelle = inspect.getsource(poller.VatsimPoller._aip_hash_pruefen)
    assert "status_vorher" in quelle


def test_der_job_loest_die_seiten_url_frisch_auf():
    """Eine gemerkte seite_url enthaelt den AIRAC und liefert nach dem naechsten Zyklus 404
    -- fuer ALLE Zeilen gleichzeitig, und zwar genau dann, wenn sich Blaetter tatsaechlich
    aendern koennten."""
    import inspect
    import re

    from app import poller

    quelle = re.sub(r"#[^\n]*", "", inspect.getsource(poller.VatsimPoller._aip_hash_pruefen))
    assert "seite_url" not in quelle
    assert "airac_url" in quelle or "seiten_des_kapitels" in quelle


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
   die Sorte, vorbelegt aus dem Ton. Dazu ein Knopf **„keine passende Seite"**, der
   `nicht_gefunden` schreibt — sonst kommt derselbe Platz beim nächsten Durchgang wieder.
4. **Passen-Maske** — Rohblatt zum Klicken, zwei Punkte mit Grad **und** Minuten getrennt,
   Drehung als eigenes Feld mit Vorschau. Bei Flugplatz- und Rollkarten zusätzlich die
   **Bahnschwellen des Platzes** aus `runway_ref.bahnen()` — Bezeichnung, Länge und beide
   Koordinaten in Grad und Minuten, zum Abschreiben. Auf diesem Weg sind die 68
   Ground-Karten überhaupt entstanden; bei Sichtflugkarten steht die Anzeige nicht, dort
   liest man die Werte vom Kartenrand ab.
5. **Zwei Anzeigen, die keine Status sind** — „— nicht nachgesehen" für einen Platz ohne
   Zeile, „Seite unbekannt" für eine Zeile ohne `seite_nr`. Beides sichtbar machen, nicht
   verschweigen.

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


def test_die_bahnschwellen_helfen_beim_passen():
    """Auf diesem Weg sind die 68 Ground-Karten entstanden: Schwellenkoordinaten aus
    runways.csv abschreiben. Ohne die Anzeige haette runway_ref.bahnen() keinen
    Produktivaufrufer mehr -- 110 Zeilen toter Code mit zehn Tests dahinter."""
    stelle = ADMIN_RUMPF.index("function dfsPassen(")
    block = ADMIN_RUMPF[stelle:stelle + 3000]
    assert "schwellen" in block.lower()


def test_die_seitenauswahl_kann_nicht_gefunden_festhalten():
    """Sonst kommt derselbe Platz beim naechsten Durchgang wieder -- und die Arbeitsliste
    bliebe dauerhaft rund 780 Eintraege lang, in denen nichts abhakbar ist."""
    stelle = ADMIN_RUMPF.index("function dfsSeiten(")
    block = ADMIN_RUMPF[stelle:stelle + 3000]
    assert "nicht-gefunden" in block


def test_platz_ohne_zeile_heisst_nicht_nachgesehen():
    """Nicht 'nicht gefunden'. Der Unterschied ist, ob jemand nachgesehen hat."""
    assert "nicht nachgesehen" in ADMIN
```

- [ ] **Schritt 2 bis 6:** wie zuvor.

---

## Task 8: Stapelung und Transparenzregler im Frontend

Zwei Änderungen an derselben Stelle: Die Flugplatzkarte liegt künftig **über** der
Sichtflugkarte statt an ihrer Stelle (Spec 8a), und der Deckkraftregler muss beide bedienen.

**Dateien:**
- Ändern: `app/static/index.html`
- Test: `tests/test_charts_dfs_ui.py`

**Interfaces:**
- Produziert: `_Z_SICHTFLUG = 300`, `_Z_PLATZKARTE = 310`
- Entfällt: `_groundVerdecktSichtflug()`
- Ändert: `_groundAktiv`, `_groundFest`, `_groundAus` halten künftig `"<ICAO>|<sorte>"`
  statt einer nackten ICAO

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_die_platzkarte_liegt_ueber_der_sichtflugkarte():
    """Ein um 37 Grad gedrehtes Blatt wird als achsenparalleles Rechteck abgelegt, dessen
    Ecken durchsichtig sind -- bei EDDL rund die Haelfte der Flaeche. Darunter gehoert die
    Sichtflugkarte, nicht die nackte Grundkarte."""
    rumpf = _ohne_kommentare(QUELLE)
    z_sicht = int(re.search(r"_Z_SICHTFLUG\s*=\s*(\d+)", rumpf).group(1))
    z_platz = int(re.search(r"_Z_PLATZKARTE\s*=\s*(\d+)", rumpf).group(1))
    assert z_platz > z_sicht


def test_die_stapelung_haengt_nicht_an_der_einfuegereihenfolge():
    """bringToFront() kippt, sobald eine Karte nachgeladen wird -- etwa nach dem
    SSE-Ereignis, das den Kartenbestand neu holt."""
    rumpf = _ohne_kommentare(QUELLE)
    assert "bringToFront" not in rumpf
    for name in ("_Z_SICHTFLUG", "_Z_PLATZKARTE"):
        assert re.search(rf"zIndex:\s*{name}", rumpf), name


def test_die_verdeckungslogik_ist_entfernt():
    """Mit ihr entfallen die drei Zustaende, die sie noetig gemacht hatte: festgenagelte
    Sichtflugkarte gegen anlaufende Automatik, abgehakte Ebene ohne Ersatz, geteilter
    Wegklick-Merker."""
    rumpf = _ohne_kommentare(QUELLE)
    assert "_groundVerdecktSichtflug" not in rumpf


def test_der_deckkraftregler_erscheint_auch_bei_flugplatzkarten():
    """Er haengt heute an _aipKarteAktiv; liegt eine Flugplatzkarte, ist der null und der
    Regler verschwindet -- obwohl genau dann etwas zu regeln waere."""
    rumpf = _ohne_kommentare(QUELLE)
    stelle = rumpf.index("function _aipDeckkraftAnzeigen")
    block = rumpf[stelle:stelle + 400]
    assert "_groundAktiv" in block


def test_der_kartenzustand_haengt_an_icao_und_sorte():
    """_groundAktiv, _groundFest und _groundAus halten heute eine ICAO (index.html:10404);
    der Kommentar darueber begruendet den getrennten Zustand ausdruecklich damit, dass
    Sichtflug- und Flugplatzkarte desselben Platzes dieselbe ICAO tragen.

    Sobald ein Platz Flugplatz- UND Rollkarte hat -- was diese Spec ermoeglicht --, ist der
    Schluessel mehrdeutig und find(k => k.icao === _groundFest) trifft die erste von zweien.
    """
    rumpf = _ohne_kommentare(QUELLE)
    stelle = rumpf.index("function _groundSchluessel")
    assert "sorte" in rumpf[stelle:stelle + 300]
    # Kein Vergleich mehr auf die nackte ICAO.
    assert "k.icao === _groundFest" not in rumpf
    assert "k.icao === _groundAktiv" not in rumpf


def test_der_regler_bedient_beide_overlays():
    """Mit demselben Wert -- zwei verschiedene waeren ein zweiter Regler, und im Cockpit
    ist ein Regler besser als zwei."""
    rumpf = _ohne_kommentare(QUELLE)
    stelle = rumpf.index("function _aipDeckkraftSetzen")
    block = rumpf[stelle:stelle + 600]
    assert "_aipKarteOverlay" in block and "_groundOverlay" in block
```

- [ ] **Schritt 2: Test laufen lassen** — alle sechs FAIL

- [ ] **Schritt 3: Stapelung setzen**

Bei den übrigen Konstanten der Kartenebenen:

```javascript
// Beide Blaetter liegen im selben overlayPane; allein der zIndex entscheidet, welches oben
// liegt. NICHT ueber bringToFront() -- das haengt an der Einfuegereihenfolge und kippt,
// sobald eine Karte nachgeladen wird (etwa nach dem SSE-Ereignis 'aip_charts').
const _Z_SICHTFLUG = 300;
const _Z_PLATZKARTE = 310;
```

In `_aipKarteZeigen`: `zIndex: _Z_SICHTFLUG` an die `L.imageOverlay`-Optionen.
In `_groundZeigen`: `zIndex: _Z_PLATZKARTE`.

- [ ] **Schritt 4: Verdeckungslogik entfernen**

`_groundVerdecktSichtflug()` löschen (`index.html:10421`), dazu den Block in
`_aipKarteNachfuehren` (`index.html:10256`), der bei liegender Flugplatzkarte
`_aipKarteZeigen(null)` ruft. Der Aufruf von `_aipKarteNachfuehren()` am Ende von
`_groundZeigen` wird ebenfalls überflüssig — die Sichtflugkarte führt sich selbst nach.

- [ ] **Schritt 5: Deckkraftregler auf beide Karten**

```javascript
function _aipDeckkraftAnzeigen() {
  // Der Regler haengt an "irgendein Blatt liegt", nicht an einem bestimmten. Bis zum
  // 31.08.2026 fragte er nur _aipKarteAktiv ab und verschwand deshalb, sobald eine
  // Flugplatzkarte allein lag -- also genau dann, wenn etwas zu regeln war.
  const liegt = !!_aipKarteAktiv || !!_groundAktiv;
  if (_deckkraftBox) _deckkraftBox.classList.toggle('deckkraft-an', liegt);
}
```

und in `_aipDeckkraftSetzen` zusätzlich `if (_groundOverlay) _groundOverlay.setOpacity(_aipDeckkraft);`

- [ ] **Schritt 5b: Kartenzustand auf `(icao, sorte)` umstellen**

```javascript
// Sichtflug- und Flugplatzkarte desselben Platzes tragen dieselbe ICAO -- deshalb reicht
// sie als Schluessel nicht. Sobald ein Platz Flugplatz- UND Rollkarte hat, traefe
// find(k => k.icao === _groundFest) die erste von zweien, und der Nutzer bekaeme beim
// Festnageln eine andere Karte als die, auf die er getippt hat.
function _groundSchluessel(k) { return k.icao + '|' + k.sorte; }
```

`_groundAktiv`, `_groundFest` und `_groundAus` halten künftig diesen Schlüssel; jedes
`find(k => k.icao === …)` wird zu `find(k => _groundSchluessel(k) === …)`.

- [ ] **Schritt 6: Tests laufen lassen** — sechs PASS

- [ ] **Schritt 7: Im Kniebrett ansehen.** Nicht nur im Browser: Coherent GT rendert
  anders, und die Stapelung zweier halbtransparenter Bilder ist genau die Art Detail, die
  dort abweicht. Über einem Platz mit beiden Karten prüfen, dass die Platzkarte oben liegt
  und die Sichtflugkarte die durchsichtigen Ecken füllt.

- [ ] **Schritt 8: Commit**

---

# Phase 4 — Abschluss

## Task 9: Vorschlagsweg entfernen — die Sperre bleibt

**Dateien:**
- Ändern: `app/database.py`, `app/main.py`, `app/static/admin.html`
- Ändern: `tests/test_handpassung_schutz.py` (436 Zeilen) — **anpassen, nicht löschen**

**Was entfällt, ist die Vorschlagstabelle:** `vorschlag_anlegen`, `get_vorschlaege`,
`vorschlag_verwerfen`, `vorschlag_entfernen`, `/api/admin/aip-vorschlaege*`,
`/aip-vorschlag/{id}.png` und die zugehörige Admin-Ansicht. Ohne gerechnete Alternative gibt
es nichts vorzuschlagen; ihr Grabstein-Mechanismus (`zustand='verworfen'`) lebt in
„verwerfen zieht `quell_hash` nach" (Task 5) weiter.

**`HandpassungGesperrt` bleibt** — als `PassungGesperrt`, mit dem Prädikat `status='gepasst'`
statt `quelle='hand'` (Task 2). Eine frühere Fassung dieses Plans strich sie mit der
Begründung, es gebe nach dem Rückbau keinen automatischen Schreibpfad mehr. **Für den Job
stimmt das, für das System nicht:** Der Seitenwähler bleibt und schreibt bei gescheiterter
Passung alle Lagefelder auf 0 (`app/main.py:4694`). Nach dem Rückbau ist `passung` dort
**immer** `None` — der nullende Zweig wäre der einzige. Am 25.08.2026 hat genau das EDAZ auf
0/0/0/0 gesetzt; die zwei Riegel, die seitdem davorstehen (Bildhash-Vergleich `:4686` und
`HandpassungGesperrt` `:4713`), sind der Grund, dass es nicht wieder passiert ist.

**`verwaisen` bleibt ebenfalls** — als Teil des Jobs (Task 6). Eine Karte, deren Eintrag in
`airport_links` verschwindet, geht auf `verwaist` und kehrt zurück, sobald der Link wieder
auftaucht; ein AIRAC-Wechsel benennt Kapitelseiten um. Nutzerentscheidung vom 30.08.2026.

- [ ] **Schritt 1: Belegen, dass kein Job mehr eine Passung schreiben kann**

```python
def test_kein_job_und_kein_skript_schreibt_eine_passung():
    """Die zweite Verteidigungslinie neben der Sperre: Was gar nicht erst schreiben kann,
    muss auch nicht abgewiesen werden.

    upsert_chart_dfs darf ausschliesslich aus database.py und main.py heraus gerufen
    werden -- nicht aus poller.py. Der Job setzt Status, quell_hash und seite_nr; dafuer
    gibt es status_melden().
    """
    import subprocess

    treffer = subprocess.run(
        ["grep", "-rn", "upsert_chart_dfs", "--include=*.py", "app/", "scripts/"],
        capture_output=True, text=True).stdout.splitlines()
    dateien = {z.split(":")[0] for z in treffer}
    assert dateien <= {"app/database.py", "app/main.py"}, dateien


def test_der_vorschlagsweg_ist_fort():
    """Ohne gerechnete Alternative gibt es nichts vorzuschlagen -- und 'gueltig .
    Vorschlag' zeigte ohnehin meist zweimal dasselbe Bild (Nutzer, 31.08.2026)."""
    from app import database

    for weg in ("vorschlag_anlegen", "get_vorschlaege", "vorschlag_verwerfen",
                "vorschlag_entfernen"):
        assert not hasattr(database, weg), weg
```

- [ ] **Schritt 2: `test_handpassung_schutz.py` umschreiben, nicht löschen**

Es prüft auf 436 Zeilen eine Invariante, die bleibt: **Eine vom Nutzer gesetzte Passung wird
nicht stillschweigend überschrieben.** Der erste Joblauf unter dieser Sperre hat am
30.08.2026 neun Handpassungen geschützt, darunter EDDL, dessen `geprueft_am` bis heute den
Zeitstempel des Nutzers trägt.

Was sich ändert, ist mechanisch:

| alt | neu |
|---|---|
| `HandpassungGesperrt` | `PassungGesperrt` |
| `quelle='hand'` | `status='gepasst'` |
| `upsert_aip_chart` | `upsert_chart_dfs` |
| `aip_charts` | `aip_charts_dfs` |
| Vorschlagstests | ersatzlos gelöscht |

**Tests, die die Vorschlagstabelle prüfen, gehen mit. Tests, die die Sperre prüfen, bleiben.**

- [ ] **Schritt 3 bis 6:** Test laufen lassen, entfernen, Gesamtlauf, Commit.

---

## Task 10: Deploy und Gegenprobe

- [ ] **Schritt 1: Datenbank sichern**

Die Migration bewegt 556 Zeilen und **verschiebt Dateien**; einen Rückwärtsgang im Code gibt
es nicht. Sie ist durch drei Riegel gegen Doppellauf gesichert, aber wenn die Abbildung selbst
falsch ist, hilft nur diese Sicherung.

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

- [ ] **Schritt 3: Changelog, Version und `CLAUDE.md`**

Ein Changelog-Eintrag, `"highlight": false`.

Dazu bekommt `CLAUDE.md` die Invarianten des neuen Standes — heute steht dort nichts zum
AIP-Teilsystem, und in drei Monaten rekonstruiert das sonst niemand:

* **Eine Tabelle** `aip_charts_dfs`, Schlüssel `(icao, sorte)`. Alle 110 Plätze mit
  Flugplatzkarte haben auch eine Sichtflugkarte.
* **Keine Automatik.** Eine Passung entsteht ausschließlich aus zwei geklickten Punkten mit
  Koordinaten. Wer Rahmenerkennung oder Ziffernlesen zurückbaut, baut etwas zurück, das
  bewusst entfernt wurde.
* **`nicht_gefunden` wird geschrieben, nicht hergeleitet.** Ein Platz ohne Zeile heißt
  „nicht nachgesehen".
* **Die Seite wird als Nummer geführt.** Eine gemerkte DFS-URL enthält den AIRAC und stirbt
  mit dem nächsten Zyklus.
* **`quelle='hand'` ist zu `status='gepasst'` geworden** — das Prädikat der Sperre.

- [ ] **Schritt 3b: Blätter verschieben**

**Vor** dem ersten Start mit dem neuen Stand — ohne diesen Schritt zeigt jede Karte ins Leere:

```bash
sudo -u 1001 mkdir -p /opt/friesenspy/data/aip_dfs
cd /opt/friesenspy/data
for f in aip/*.png;        do sudo mv "$f" "aip_dfs/$(basename "$f" .png).sichtflug.png"; done
# Die Ground-Blaetter tragen die Sorte nicht im Namen -- sie steht in der Datenbank.
sudo sqlite3 friesenspy.db "SELECT icao||' '||sorte FROM aip_ground_charts;" | \
  while read icao sorte; do
    [ -f "aip_ground/$icao.png" ] && sudo mv "aip_ground/$icao.png" "aip_dfs/$icao.$sorte.png"
  done
ls aip_dfs | wc -l       # erwartet: 556
```

- [ ] **Schritt 4: Deploy, dann sofort die Gegenprobe**

```bash
sudo sqlite3 /opt/friesenspy/data/friesenspy.db \
  "SELECT sorte,status,COUNT(*) FROM aip_charts_dfs GROUP BY 1,2;
   SELECT COUNT(*) FROM aip_charts_dfs WHERE sorte='sichtflug' AND p1_x IS NOT NULL;
   SELECT COUNT(*) FROM aip_charts_dfs WHERE quell_hash = '';"
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

Dazu **446 Sichtflugzeilen mit gesetztem `p1_x`** — die aus `rahmen_px` gewonnenen
Klickpunkte, alle 446 Bestandszeilen sind wohlgeformt — und **556 Zeilen mit leerem
`quell_hash`**: Der Rohbytes-Hash war nie vorhanden, der erste Joblauf trägt ihn nach. Steht
dort eine andere Zahl als 556, hat die Migration einen Wert erfunden.

**Weicht eine Zahl ab, wird zurückgerollt** — die Sicherung aus Schritt 1 zurückspielen und
die Ursache suchen, bevor irgendetwas anderes geschieht.

- [ ] **Schritt 5: Im Admin ansehen**

Filter auf „alles außer gepasst" — es müssen 385 Zeilen erscheinen (275 + 30 + 10 + 38 + 32).
Plätze ohne Zeile erscheinen als „— nicht nachgesehen"; **es gibt davon keinen**, weil
`aip_charts` `airport_links` mit 446 zu 446 exakt abdeckt. Eine Karte probeweise passen und
im Kniebrett prüfen, dass sie erscheint — und dass die Platzkarte über der Sichtflugkarte
liegt.

- [ ] **Schritt 5b: Den ersten Joblauf abwarten und ansehen**

Er trägt 556 `seite_nr` **und** 556 `quell_hash` nach. **Erwartet: null Zeilen auf
`pruefen`** und null mit leerem `quell_hash`. Stehen dort hunderte auf `pruefen`, fehlt der
Leer-Zweig; stehen dort noch leere Hashes, hat der Lauf Zeilen übersprungen.

```bash
sudo sqlite3 /opt/friesenspy/data/friesenspy.db \
  "SELECT status,COUNT(*) FROM aip_charts_dfs GROUP BY 1;
   SELECT COUNT(*) FROM aip_charts_dfs WHERE seite_nr IS NULL;"
```

- [ ] **Schritt 6: Nicht während eines Fluges deployen.** Jeder Push startet den Container
  neu und reißt offene Sitzungen ab; ob jemand fliegt, steht im nginx-Log (`/panel`,
  `/api/live`).

---

## Selbstprüfung dieses Plans

Gegen die Spec durchgegangen; jeder Abschnitt hat einen Task:

| Spec | Task |
|---|---|
| 2 Rückbau, 2.1 die drei Skripte, 2.2 `runway_ref` | 3, 4 (Skripte), 7 (Schwellenanzeige) |
| 3 Tabelle, 3.1 drei Riegel, 3.2 `rahmen_px`, 3.3 Blattpfade | 1, 5 (Pfade), 10 (Verschieben) |
| 4 Status, 4.2 `nicht_gefunden`, 4.3 aus `pruefen` heraus, 4.5 `verwaist` | 2, 5 |
| 5 Passen-Maske, 5.1 Saum, 5.2 Drehschwelle, 5.3 Schwellen, 5.4 `pruefen` | 4b, 5, 7 |
| 6 Liste, 6.1 `seite_nr`, 6.2 Nachtragen, 6.3 Seitenauswahl | 5, 6, 7 |
| 7 Job | 6 |
| 8 die Sperre bleibt | 2, 9 |
| 9 Platzkarte über Sichtflugkarte, Zustand `(icao, sorte)` | 8 |
| 10 die drei Fehler | 5 (Route), 8 (Regler), 9 (Vorschläge) |
| 11 `CLAUDE.md` bekommt die Invarianten | 10, Schritt 3 |

**Zwei Punkte, die ein Bearbeiter kennen muss:**

1. **Die Reihenfolge ist zwingend.** Task 3 löscht Funktionen, die Task 4 bis 6 noch
   aufrufen. Wer Task 3 vorzieht, bricht den Import von `app/main.py` und damit den
   gesamten Dienst. Schritt 1 von Task 3 listet die Aufrufer deshalb **vor** dem Löschen
   auf.

2. **Die Migration hat keinen Rückwärtsgang im Code.** Sie ist durch drei Riegel gegen
   Doppellauf gesichert — Merker, `ON CONFLICT DO NOTHING` und einen eigenen `try`-Block
   mit `except sqlite3.Error` —, aber wenn die Abbildung selbst falsch ist, hilft nur die
   Sicherung aus Task 10 Schritt 1. Deshalb steht die Gegenprobe mit den erwarteten Zahlen
   dort und nicht am Ende.

3. **Task 4b ist keine Kür.** Er behebt zwei Fehler, die erst sichtbar werden, wenn
   dieselbe Funktion beide Kartentypen bedient — und beide schreiben stillschweigend
   falsche Werte in die Datenbank, statt sichtbar zu scheitern: `feld_*` einen Kilometer zu
   weit außen bei Sichtflugkarten, und ein neuer `bild_hash` nach einer 0,07°-Drehung, die
   nichts bewirkt. Wer ihn überspringt, merkt es beim ersten Joblauf.
