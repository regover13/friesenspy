"""Messpunkte im Poll-Zyklus (GitHub-Issue #16).

Am Abend des 04.09.2026 wuchs die Laufzeit von ``_poll_once`` ueber Stunden von 0,28 s auf
ueber 5 s -- bei 15 s Takt lief der Job praktisch durchgehend und belegte einen ganzen Kern.
Ausgeschlossen wurden Netz, DB-Sperren, fehlende Indizes, Requestlast und Speicher; **was die
Zeit verbraucht hat, ist bis heute unbelegt**, weil im Log nur Start und Ende des Jobs stehen.

Diese Tests binden die Abschnittsmessung fest, die genau diese Luecke schliesst. Sie behebt
nichts -- sie sorgt dafuer, dass beim naechsten Mal Zahlen dastehen statt Vermutungen.
"""
from __future__ import annotations

import logging
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.poller import VatsimPoller, _Abschnittsuhr


class TestAbschnittsuhr:
    def test_bericht_nennt_den_teuersten_abschnitt_zuerst(self):
        """Der Bericht ist absteigend sortiert -- die erste Zahl ist die, die man sucht."""
        uhr = _Abschnittsuhr()
        time.sleep(0.03)
        uhr.marke("abruf")
        uhr.marke("filter")           # praktisch 0 s
        time.sleep(0.06)
        uhr.marke("db")

        bericht = uhr.bericht()
        assert bericht.index("db") < bericht.index("abruf") < bericht.index("filter")
        assert uhr.gesamt() >= 0.09

    def test_marke_misst_nur_den_abschnitt_seit_der_vorigen_marke(self):
        """Jede Marke steht fuer ihren eigenen Abschnitt, nicht fuer die Zeit seit dem Start."""
        uhr = _Abschnittsuhr()
        time.sleep(0.05)
        uhr.marke("abruf")
        uhr.marke("filter")

        assert uhr.dauern["abruf"] >= 0.05
        assert uhr.dauern["filter"] < 0.02


class TestLangsamerPollWirdBerichtet:
    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        from app.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    async def _poll(self, tmp_path, abrufdauer: float):
        from app.database import init_db

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        poller = VatsimPoller(db_path=db_file, callsign_prefix="FRS", poll_interval=60)
        poller._http_client = AsyncMock()

        async def _langsamer_abruf(*_a, **_k):
            time.sleep(abrufdauer)   # blockiert den Event-Loop -- genau der beobachtete Fall
            return {"pilots": [], "controllers": []}

        with patch("app.poller.fetch_vatsim_data", new=_langsamer_abruf):
            await poller._poll_once()

    @pytest.mark.asyncio
    async def test_langsamer_zyklus_loggt_die_aufschluesselung(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr("app.poller._POLL_LANGSAM_SEC", 0.05)
        with caplog.at_level(logging.WARNING, logger="app.poller"):
            await self._poll(tmp_path, abrufdauer=0.1)

        zeilen = [r.getMessage() for r in caplog.records if "Poll-Zyklus" in r.getMessage()]
        assert len(zeilen) == 1, caplog.text
        assert "abruf" in zeilen[0] and "db" in zeilen[0]

    @pytest.mark.asyncio
    async def test_schneller_zyklus_bleibt_still(self, tmp_path, monkeypatch, caplog):
        """Kein Rauschen im Normalbetrieb -- sonst steht die Warnung 5760-mal am Tag im Log."""
        monkeypatch.setattr("app.poller._POLL_LANGSAM_SEC", 5.0)
        with caplog.at_level(logging.WARNING, logger="app.poller"):
            await self._poll(tmp_path, abrufdauer=0.0)

        assert not [r for r in caplog.records if "Poll-Zyklus" in r.getMessage()]
