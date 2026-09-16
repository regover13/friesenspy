# -*- coding: utf-8 -*-
"""Ein Modul für MSFS 2020 **und** 2024 — was dafür nie zurückkommen darf (16.09.2026).

Seit Brügge 1.14.0 liegt **ein** ``bruegge.wasm`` im Paket, und es läuft in beiden
Simulatoren. Das hält nur, solange zwei Dinge gelten — und beide sind Textregeln am
Quelltext, weil es für ein WASM-Modul keinen anderen Prüfstand gibt.

**1. Kein Header, den MSFS 2020 nicht kennt.**

Ein WASM-Import ist statisch. Ein Modul, das ``fsIOOpen`` auch nur *vielleicht* benutzt,
importiert es trotzdem — und MSFS 2020 verwirft es dann bei der Validierung, **bevor** eine
einzige Zeile läuft (``ERR_UNKNOWN_BLANK_IMPORT``). Lautlos: kein ``module_init``, keine
Meldung, kein Objekt.

Geprüft wird der ``#include``, nicht der Funktionsname — das ist die Wurzel. Ohne Header
keine Funktion, und die Liste der Header ist kurz und stabil, während die Funktionsnamen
darin es nicht sind.

**2. Der Simulator wird zur Laufzeit bestimmt, nicht beim Übersetzen.**

Stand er in einem ``#ifdef``, war er eine Eigenschaft des *Baus*. Ein Modul, das beide
bedient, weiß erst mit ``SIMCONNECT_RECV_ID_OPEN``, wo es läuft. Und das ist keine
Kosmetik: Der Server sucht die Titel je Simulator heraus (``bruegge_titel_fuer``). Eine
Brügge, die sich in MSFS 2020 als ``msfs2024`` ausgibt, fordert Titel an, die es bei ihr
nicht gibt, meldet sie als gescheitert zurück — und schaltet damit echte Katalogeinträge ab.

⚠ **Der Fund, der diesen Test ausgelöst hat**, steckte weder in 1. noch in 2., sondern
dazwischen: ``g_kennung_fest`` wurde **ausschließlich** innerhalb von
``#ifdef KENNUNG_HAELT`` gesetzt. Mit dem Wegfall der Datei-API wäre es für immer ``false``
geblieben, und ``kennung_uebernehmen`` wäre bei jeder Antwort sofort zurückgekehrt: Die
Brügge hätte **nie** eine Kennung angenommen, der Server bei **jeder** Meldung eine neue
vergeben — im Sekundentakt, jede mit vollem Positionsmatch. Von außen hätte das ausgesehen
wie „die Kennung hält eben nicht", also wie das erwartete Verhalten.

Der Compiler schweigt dazu; ``g_kennung_fest`` blieb eine gültige, nur nie wahre Bedingung.
Deshalb prüft der letzte Test hier, dass von der Datei-API **nichts** übrig ist — kein
Makro, keine Hülle, kein Aufruf.
"""
from pathlib import Path

import pytest

QUELLE = Path(__file__).resolve().parent.parent / "friesenbruegge" / "msfs" / "bruegge.cpp"


@pytest.fixture(scope="module")
def cpp() -> str:
    return QUELLE.read_text(encoding="utf-8")


#: Header, die es NUR im MSFS-2024-SDK gibt. Gegengezählt am 16.09.2026: Das 2020er
#: ``WASM/include/MSFS/`` kennt elf Header, das 2024er dreiundzwanzig.
NUR_2024 = [
    "MSFS_IO.h",            # die Datei-API -- der konkrete Fall von 1.14.0
    "MSFS_AirportContext.h",
    "MSFS_Camera.h",
    "MSFS_Charts.h",
    "MSFS_Events.h",
    "MSFS_FlightPlan.h",
    "MSFS_Flow.h",
    "MSFS_GaugeContext.h",
    "MSFS_PlannedRoute.h",
    "MSFS_SystemContext.h",
    "MSFS_Utils.h",
    "MSFS_Vars.h",
]


@pytest.mark.parametrize("header", NUR_2024)
def test_kein_header_aus_dem_2024_sdk(cpp, header):
    """⚠ Jeder davon macht das Modul in MSFS 2020 unbrauchbar -- und zwar lautlos."""
    eingebunden = [z.strip() for z in cpp.splitlines()
                   if z.lstrip().startswith("#include") and header in z]
    assert not eingebunden, (
        f"{header} gibt es im MSFS-2020-SDK nicht. MSFS 2020 verwirft das Modul dann bei "
        f"der Validierung, ohne eine Meldung zu schreiben. Gefunden: {eingebunden}"
    )


def test_der_simulator_steht_nicht_im_praeprozessor(cpp):
    """Kein ``#ifdef``, das ``msfs2020``/``msfs2024`` fest einbaut.

    ⚠ Geprüft wird nur **Code**, nicht der ganze Text. Die erste Fassung dieses Tests war
    rot, weil der Quelltext in seinen Kommentaren ausführlich erklärt, was `FUER_MSFS2020`
    einmal tat und warum es weg ist — das ist genau die Erklärung, die dort stehen soll.
    Ein Test, der sie verbietet, treibt sie heraus.
    """
    code = [z for z in cpp.splitlines() if not z.lstrip().startswith("//")]
    assert not [z for z in code if "FUER_MSFS2020" in z], (
        "`FUER_MSFS2020` ist zurück -- damit wäre der Simulator wieder eine Eigenschaft "
        "des Baus, und es bräuchte wieder zwei Module."
    )
    assert not [z for z in code if "define SIMULATOR_NAME" in z], (
        "`SIMULATOR_NAME` als Makro macht den Simulator zur Bau-Eigenschaft. Er muss aus "
        "SIMCONNECT_RECV_ID_OPEN kommen."
    )


def test_der_simulator_kommt_aus_recv_open(cpp):
    """Die Gegenprobe zum Test darüber: Der Laufzeitweg muss auch wirklich da sein.

    Ohne ihn wäre die Abwesenheit des Makros nur die halbe Wahrheit — ``g_simulator``
    bliebe auf seinem Anfangswert stehen, und die Brügge meldete dauerhaft ``msfs``.
    """
    assert "SIMCONNECT_RECV_ID_OPEN" in cpp, "Der Fall im dispatch fehlt."
    assert "dwApplicationVersionMajor" in cpp, (
        "Entschieden wird nach der Fassungsnummer, nicht nach `szApplicationName` -- der "
        "ist ein Eigenname und ändert sich, wenn Asobo ihn anfasst."
    )
    assert '"msfs2020"' in cpp and '"msfs2024"' in cpp, (
        "Beide Namen müssen im Laufzeitzweig vorkommen."
    )


def test_von_der_datei_api_ist_nichts_uebrig(cpp):
    """⚠⚠ DER EIGENTLICHE TEST -- s. den Fund oben im Modulkopf.

    Nicht „wird nicht eingebunden", sondern: keine Spur mehr. Ein ``#ifdef``-Zweig, der nie
    gebaut wird, verrottet unbemerkt — und eine Variable, die nur dort gesetzt wurde, kippt
    lautlos eine Bedingung, die anderswo noch abgefragt wird.
    """
    for spur in ("KENNUNG_HAELT", "g_kennung_fest", "fsIOOpen", "fsIOWrite", "fsIOClose",
                 "KENNUNG_DATEI"):
        # Kommentare dürfen die Geschichte erzählen -- Code nicht.
        code = [z for z in cpp.splitlines()
                if spur in z and not z.lstrip().startswith("//")]
        assert not code, f"`{spur}` steht wieder im Code: {code}"


def test_die_kennung_geht_ins_log(cpp):
    """Ohne sie ist von außen nicht zu unterscheiden, WELCHE Brügge gemeldet hat.

    Am 16.09.2026 hat genau das eine Untersuchung aufgehalten: In der Datenbank stand eine
    Kennung unter einer fremden CID, und es ließ sich nicht entscheiden, ob die eigene
    Brügge falsch zugeordnet worden war oder ob schlicht ein anderer Pilot gemeldet hatte.
    Beide Fälle sehen von außen gleich aus.
    """
    assert "Kennung vom Server" in cpp, (
        "Die Log-Zeile in `kennung_uebernehmen` fehlt. Der frühere Grund dagegen "
        "(\"die MSFS-Fassung hat keinen Ausgabeweg\") ist mit `log_zeile` seit 1.13.0 weg."
    )
