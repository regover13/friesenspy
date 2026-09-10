"""Diagnose-Warnungen ueberleben den Container (GitHub-Issue #16).

Die Abschnittsmessung des Pollers (14.20.6) schreibt ihre Aufschluesselung als WARNING ins
Log -- und das Log lag ausschliesslich im Container. Zweimal ist die Spur dadurch verloren
gegangen, bevor jemand sie lesen konnte: am 09.09.2026 mit dem 14.27.1-Deploy, und in den
sechs Tagen danach bei 15 weiteren Deploys. Ein Eventabend faellt selten, ein Deploy oft.

`data/` ist das einzige Verzeichnis, das per Bind-Mount auf dem Host liegt (dort steht auch
die Datenbank). Eine Logdatei daneben ueberlebt jedes `docker compose up -d`.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from app.main import configure_logging


@pytest.fixture
def root_logger_wiederherstellen():
    """`configure_logging` benutzt `force=True` und raeumt dabei fremde Handler ab --
    ohne diese Fixture verliert pytest seine eigene Log-Erfassung fuer alle Folgetests."""
    root = logging.getLogger()
    alte_handler = root.handlers[:]
    altes_level = root.level
    yield
    for h in root.handlers[:]:
        if h not in alte_handler:
            h.close()
            root.removeHandler(h)
    for h in alte_handler:
        if h not in root.handlers:
            root.addHandler(h)
    root.setLevel(altes_level)


class TestDiagnoseLog:
    def test_warnung_landet_in_der_datei(self, tmp_path, root_logger_wiederherstellen):
        """Der eigentliche Zweck: Was der Poller meldet, steht nach dem Deploy noch da."""
        ziel = tmp_path / "diagnose.log"
        configure_logging("INFO", diagnose_pfad=str(ziel))

        logging.getLogger("app.poller").warning(
            "Poll-Zyklus langsam: 6.12 s — abruf 4.80 s · db 1.10 s")

        assert ziel.exists(), "Diagnosedatei wurde nicht angelegt"
        inhalt = ziel.read_text(encoding="utf-8")
        assert "Poll-Zyklus langsam" in inhalt
        assert "abruf 4.80 s" in inhalt

    def test_info_landet_nicht_in_der_datei(self, tmp_path, root_logger_wiederherstellen):
        """Nur WARNING+ -- auf INFO schreibt der Poller im 15-s-Takt, das fuellt die Platte
        des Hosts mit Rauschen, das die Container-Logs ohnehin schon haben."""
        ziel = tmp_path / "diagnose.log"
        configure_logging("INFO", diagnose_pfad=str(ziel))

        logging.getLogger("app.poller").info("Poll-Zyklus 0.24 s — Normalbetrieb")
        logging.getLogger("app.poller").warning("etwas Erwaehnenswertes")

        inhalt = ziel.read_text(encoding="utf-8")
        assert "Normalbetrieb" not in inhalt
        assert "etwas Erwaehnenswertes" in inhalt

    def test_datei_waechst_nicht_unbegrenzt(self, tmp_path, root_logger_wiederherstellen):
        """Rotation ist Pflicht: Die Datei liegt im selben Bind-Mount wie die Datenbank."""
        ziel = tmp_path / "diagnose.log"
        configure_logging("INFO", diagnose_pfad=str(ziel))

        datei_handler = [
            h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)
        ]
        assert len(datei_handler) == 1, "genau ein rotierender Datei-Handler erwartet"
        h = datei_handler[0]
        assert 0 < h.maxBytes <= 20 * 1024 * 1024
        assert h.backupCount >= 1

    def test_ohne_pfad_bleibt_alles_wie_bisher(self, tmp_path, root_logger_wiederherstellen):
        """Der Datei-Handler ist eine Zugabe, keine Voraussetzung -- Tests und lokale Laeufe
        ohne Datenverzeichnis duerfen davon nichts merken."""
        configure_logging("INFO")

        datei_handler = [
            h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)
        ]
        assert datei_handler == []

    def test_unbeschreibbarer_pfad_legt_die_app_nicht_lahm(self, tmp_path, root_logger_wiederherstellen):
        """Eine fehlende Schreibberechtigung im Datenverzeichnis darf den Start nicht
        verhindern -- die Diagnose ist wichtig, aber nicht wichtiger als der Dienst."""
        ziel = tmp_path / "gibt-es-nicht" / "tiefer" / "diagnose.log"
        (tmp_path / "gibt-es-nicht").mkdir()
        (tmp_path / "gibt-es-nicht").chmod(0o500)
        try:
            configure_logging("INFO", diagnose_pfad=str(ziel))
            logging.getLogger("app.poller").warning("darf niemanden stoeren")
        finally:
            (tmp_path / "gibt-es-nicht").chmod(0o700)


class TestPfadNebenDerDatenbank:
    def test_der_abgeleitete_pfad_liegt_im_bind_mount(self):
        """Der Ort ist die ganze Idee: neben der Datenbank, also auf dem Host.

        Gebunden an `DB_PATH`, nicht an eine zweite Konstante -- sonst zeigt die eine irgendwann
        woanders hin als die andere.
        """
        from types import SimpleNamespace

        from app.config import Settings
        from app.main import _diagnose_log_pfad

        # Gegen die Vorgabe aus `Settings`, nicht gegen ein geladenes `get_settings()`: Der
        # Test soll die Kopplung pruefen, nicht die Umgebung des Testlaufs.
        db_pfad = Settings.model_fields["DB_PATH"].default
        assert db_pfad, "DB_PATH hat keine Vorgabe mehr — Kopplung neu pruefen"
        pfad = Path(_diagnose_log_pfad(SimpleNamespace(DB_PATH=db_pfad)))
        assert pfad.parent == Path(db_pfad).parent
        assert pfad.name.endswith(".log")
