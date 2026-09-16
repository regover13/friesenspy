# -*- coding: utf-8 -*-
"""Ein Objekt in der Luft wird festgehalten — die Regel, nicht der Wortlaut (16.09.2026).

**Warum ein Textprüfer und kein echter Test:** `bruegge.cpp` ist ein WASM-Modul für MSFS;
es lässt sich von Python aus weder laden noch aufrufen. Was hier gebunden wird, ist deshalb
absichtlich wenig — aber genau das, was beim nächsten Umbau leise verschwinden könnte.

Der Anlass: `AICreateSimulatedObject` erzeugt ein SIMULIERTES Objekt. Auf ein Flugzeug wirkt
damit die Physik, und ein Ballon auf 3000 ft lag nach 15 Sekunden am Boden (gemessen
16.09.2026; ein Windrad daneben stand auf exakt 3000,0 ft — statische SimObjects haben keine
Physik). Die Freeze-Ereignisse halten es fest; dass sie auf ein solches Objekt überhaupt
wirken, wurde vorher extern gemessen (`friesenbruegge/probe-msfs/freeze_probe.py`).

⚠ **Gegengeprüft:** Jede Zusicherung unten wurde gegen die entfernte Stelle laufen gelassen
und wird ohne sie rot (CLAUDE.md verlangt das — ein Regressionstest, der auch ohne den Fix
grün ist, prüft nichts).
"""
from pathlib import Path

import pytest

QUELLE = Path(__file__).resolve().parent.parent / "friesenbruegge" / "msfs" / "bruegge.cpp"


@pytest.fixture(scope="module")
def cpp() -> str:
    return QUELLE.read_text(encoding="utf-8")


def test_alle_drei_ereignisse_werden_angemeldet(cpp):
    """Höhe allein genügt nicht: ohne ATTITUDE kippt das Objekt, ohne ORT treibt es ab."""
    for name in ("FREEZE_ALTITUDE_SET", "FREEZE_ATTITUDE_SET",
                 "FREEZE_LATITUDE_LONGITUDE_SET"):
        assert f'"{name}"' in cpp, name


def test_angemeldet_wird_einmal_je_verbindung(cpp):
    """`MapClientEventToSimEvent` gehört NICHT in den Objektpfad.

    Derselbe Fehler steckte schon einmal in `kieker_probe.py`: Definition und Anfrage in
    einer Funktion, die je Objekt lief — bei 25 Objekten hatte dieselbe Definition danach
    75 Einträge. Hier wäre die Folge dieselbe Sorte stiller Unsinn.
    """
    assert cpp.count("SimConnect_MapClientEventToSimEvent") == 3
    beginn = cpp.index("static void objekt_festhalten")
    ende = cpp.index("static void objekt_entfernen")
    assert "MapClientEventToSimEvent" not in cpp[beginn:ende]


def test_festgehalten_wird_nur_in_der_luft(cpp):
    """Die Nutzerregel vom 16.09.2026: `auf_boden=false` UND eine Höhe.

    Am Boden ist nichts festzuhalten — ein Freeze dort würde nur verdecken, ob `OnGround`
    seine Arbeit tut.
    """
    beginn = cpp.index("static void objekt_festhalten")
    ende = cpp.index("static void objekt_entfernen")
    rumpf = cpp[beginn:ende]
    assert "if (o.auf_boden || !o.hat_hoehe || o.objekt_id == 0) return;" in rumpf


def test_es_wird_nach_der_objekt_id_festgehalten(cpp):
    """Die Ereignisse brauchen die Objekt-ID — die gibt es erst in `ASSIGNED_OBJECT_ID`.

    In `objekt_erzeugen` aufgerufen liefe es ins Leere: Dort ist `objekt_id` noch 0, und
    `TransmitClientEvent` an Objekt 0 trifft das NUTZERFLUGZEUG. Das wäre kein stiller
    Fehlschlag, sondern ein eingefrorener Pilot.
    """
    assert "objekt_festhalten(i);" in cpp
    # ⚠ `case …:` und nicht der nackte Bezeichner: Beide Namen stehen weiter oben auch in
    # Kommentaren, und `str.index` nimmt das erste Vorkommen. Ein Test, der den Kommentar
    # trifft statt den Zweig, vergleicht zwei beliebige Zahlen — hier zuerst passiert, der
    # Lauf war rot, obwohl der Code stimmte.
    aufruf = cpp.index("objekt_festhalten(i);")
    zuweisung = cpp.index("case SIMCONNECT_RECV_ID_ASSIGNED_OBJECT_ID:")
    ausnahme = cpp.index("case SIMCONNECT_RECV_ID_EXCEPTION:")
    assert zuweisung < aufruf < ausnahme

    # ... und NICHT in objekt_erzeugen.
    beginn = cpp.index("static void objekt_erzeugen")
    ende = cpp.index("static void objekt_festhalten")
    assert "objekt_festhalten" not in cpp[beginn:ende]


def test_die_version_traegt_das_festhalten(cpp):
    """Festhalten gibt es seit 1.12.0 — die Fassung darf nicht dahinter zurückfallen.

    ⚠ Hier stand zuerst die Zahl selbst (`== "1.12.0"`), und der Test wurde schon beim
    nächsten Release rot — bei einem, der mit dem Festhalten nichts zu tun hatte. Ein Test,
    der bei jeder Versionserhöhung bricht, sagt nichts über die Sache und wird irgendwann
    gedankenlos nachgezogen. Gebunden ist deshalb die UNTERGRENZE.
    """
    import re
    m = re.search(r'#define BRUEGGE_VERSION\s+"(\d+)\.(\d+)\.(\d+)"', cpp)
    assert m, "keine Versionsnummer gefunden"
    assert tuple(int(x) for x in m.groups()) >= (1, 12, 0)


def test_das_messwerkzeug_liegt_daneben(cpp):
    """Die Messung, die das hier überhaupt gerechtfertigt hat, muss auffindbar bleiben.

    Ohne sie ist der Einbau eine Behauptung: Dass Freeze auf ein Objekt aus
    `AICreateSimulatedObject` wirkt, steht in keiner Doku.
    """
    probe = QUELLE.parent.parent / "probe-msfs" / "freeze_probe.py"
    assert probe.exists()
    assert "freeze_probe.py" in cpp
