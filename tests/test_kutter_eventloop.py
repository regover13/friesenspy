"""Die Kutter-Fortschrittsrechnung darf die Event-Loop nicht blockieren (GitHub-Issue #16).

Am 09.09.2026 hat ein Zuladungs-Speichervorgang die App zweimal fuer rund drei Minuten
vollstaendig lahmgelegt (siehe ``docs/kutter-zuladung-invalidierung.md``). Behoben wurde in
14.27.3 der *Ausloeser* -- das globale Verwerfen aller Snapshots. Der Mechanismus dahinter
blieb: ``compute_transport_progress`` kostet fuer zehn Events rund 110 Sekunden und lief in
Handlern, die zwar ``async def`` waren, aber kein einziges ``await`` enthielten. Starlette
fuehrt solche Handler in der Event-Loop aus -- solange sie rechnen, steht die ganze App.

Diese Tests binden zwei Eigenschaften fest:

* Kein registrierter Endpunkt, der die Rechnung anstoesst, ist eine Koroutine (dann schiebt
  Starlette ihn selbst in den Threadpool).
* Die Rechnung laeuft je Event nur einmal gleichzeitig -- ohne diese Sperre wuerden aus den
  30 Anfragen, die sich am 09.09. aufgestaut hatten, 30 parallele Laeufe.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
import threading
import time

import pytest

from app import main
from app.database import get_connection, get_progress_snapshot, init_db

# Die Aufrufe, die die teure Fortschrittsrechnung anstossen. Ueber den AST gesucht, nicht per
# Textsuche -- ein Funktionsname in einem Kommentar oder Docstring zaehlt sonst als Treffer.
_TEURE_AUFRUFE = {"_kutter_progress", "compute_transport_progress"}


def _stoesst_rechnung_an(fn) -> bool:
    """True, wenn der Quelltext von ``fn`` einen der teuren Aufrufe wirklich *aufruft*."""
    try:
        quelle = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return False
    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        return False
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Call):
            ziel = knoten.func
            name = getattr(ziel, "id", None) or getattr(ziel, "attr", None)
            if name in _TEURE_AUFRUFE:
                return True
    return False


def _rechnende_endpunkte() -> list:
    """Alle bei FastAPI registrierten Endpunkte, die die Kutter-Rechnung anstossen."""
    gefunden = []
    for route in main.app.routes:
        fn = getattr(route, "endpoint", None)
        if fn is not None and _stoesst_rechnung_an(fn):
            gefunden.append((getattr(route, "path", "?"), fn))
    return gefunden


class TestEndpunkteBlockierenDieEventLoopNicht:
    def test_die_suche_findet_ueberhaupt_endpunkte(self):
        """Absicherung: Ohne diesen Test waere der naechste stillschweigend gruen.

        Faellt die AST-Erkennung aus (umbenannte Funktion, geaenderte Route-Struktur), findet
        ``_rechnende_endpunkte`` nichts mehr -- und eine Pruefung ueber eine leere Liste besteht
        immer. Am 10.09.2026 waren es sechs Endpunkte.
        """
        pfade = [p for p, _ in _rechnende_endpunkte()]
        assert len(pfade) >= 6, f"AST-Erkennung greift nicht mehr, gefunden: {pfade}"
        assert "/api/transport/events" in pfade

    def test_kein_rechnender_endpunkt_ist_eine_koroutine(self):
        """Ein ``async def`` ohne ``await`` rechnet in der Event-Loop und blockiert alles.

        Ohne ``async`` schiebt Starlette den Handler von selbst in den Threadpool: Aus
        ``die App steht still`` wird ``dieser eine Aufruf dauert lang``.
        """
        koroutinen = [
            p for p, fn in _rechnende_endpunkte() if inspect.iscoroutinefunction(fn)
        ]
        assert koroutinen == [], (
            "Diese Endpunkte rechnen in der Event-Loop und legen die App still: "
            + ", ".join(koroutinen)
        )


class TestEinfachlaufSperre:
    """Je Event rechnet immer nur einer -- das Gelaender zum Threadpool."""

    def _event_vorbereiten(self, tmp_path):
        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        return db_file

    def test_zwei_gleichzeitige_leser_rechnen_nur_einmal(self, tmp_path):
        """Beim abgeschlossenen Event zahlt nur der erste die Rechnung.

        Der zweite wartet an der Sperre und findet danach den frisch geschriebenen Snapshot --
        er darf ``compute_fn`` nicht noch einmal ausfuehren. Genau dieser Fall lag am
        09.09.2026 vor: neun abgeschlossene Events ohne Snapshot, 30 aufgestaute Anfragen.
        """
        db_file = self._event_vorbereiten(tmp_path)
        laeufe = []
        sperre = threading.Lock()

        def compute_fn():
            with sperre:
                laeufe.append(1)
            time.sleep(0.3)          # lange genug, dass der zweite Thread sicher wartet
            return {"total_kg": 42.0, "flights": []}

        def leser():
            conn = get_connection(db_file)
            try:
                main._frozen_or_compute(
                    conn, "kutter", 1, finished=True, compute_fn=compute_fn,
                    now="2026-09-09T19:29:46Z",
                )
            finally:
                conn.close()

        threads = [threading.Thread(target=leser) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(laeufe) == 1, f"Rechnung lief {len(laeufe)}x statt einmal"
        conn = get_connection(db_file)
        try:
            assert get_progress_snapshot(conn, "kutter", 1) is not None
        finally:
            conn.close()

    def test_ein_aktives_event_rechnet_nie_zwei_mal_gleichzeitig(self, tmp_path):
        """Ein laufendes Event bekommt nie einen Snapshot -- es wird bei jedem Abruf frisch
        gerechnet. Serialisieren spart hier keine Arbeit, verhindert aber, dass 30 Anfragen
        30 Rechnungen gleichzeitig starten und die Maschine ueberrennen.
        """
        db_file = self._event_vorbereiten(tmp_path)
        gleichzeitig = 0
        hoechststand = 0
        zaehler_sperre = threading.Lock()

        def compute_fn():
            nonlocal gleichzeitig, hoechststand
            with zaehler_sperre:
                gleichzeitig += 1
                hoechststand = max(hoechststand, gleichzeitig)
            time.sleep(0.2)
            with zaehler_sperre:
                gleichzeitig -= 1
            return {"total_kg": 0.0, "flights": []}

        def leser():
            conn = get_connection(db_file)
            try:
                main._frozen_or_compute(
                    conn, "kutter", 7, finished=False, compute_fn=compute_fn,
                    now="2026-09-09T19:29:46Z",
                )
            finally:
                conn.close()

        threads = [threading.Thread(target=leser) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert hoechststand == 1, f"{hoechststand} Rechnungen liefen gleichzeitig"

    def test_verschiedene_events_blockieren_sich_nicht(self, tmp_path):
        """Die Sperre gilt je Event, nicht global -- sonst wuerde ein langsames Event alle
        anderen ausbremsen, und ``/api/transport/events`` rechnet zehn Events hintereinander.
        """
        db_file = self._event_vorbereiten(tmp_path)
        gleichzeitig = 0
        hoechststand = 0
        zaehler_sperre = threading.Lock()

        def compute_fn():
            nonlocal gleichzeitig, hoechststand
            with zaehler_sperre:
                gleichzeitig += 1
                hoechststand = max(hoechststand, gleichzeitig)
            time.sleep(0.25)
            with zaehler_sperre:
                gleichzeitig -= 1
            return {"total_kg": 0.0, "flights": []}

        def leser(ref_id):
            conn = get_connection(db_file)
            try:
                main._frozen_or_compute(
                    conn, "kutter", ref_id, finished=False, compute_fn=compute_fn,
                    now="2026-09-09T19:29:46Z",
                )
            finally:
                conn.close()

        threads = [threading.Thread(target=leser, args=(i,)) for i in (11, 12, 13)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert hoechststand == 3, f"nur {hoechststand} von 3 Events liefen gleichzeitig"
