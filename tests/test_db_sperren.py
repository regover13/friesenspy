"""Schreibsperren in SQLite: Wartezeit und Transaktionsdauer (GitHub-Issues #14, #15).

Am 04.09.2026 (Ausmotten-Event) war die App wiederholt fuer Minuten kaum bedienbar. Zwei
verschiedene Ursachen, dieselbe Wirkung -- ``database is locked``:

* Ein Job hielt die Schreibsperre ueber Netzabrufe hinweg offen (StatSim, behoben in 14.20.3;
  der KI-Spruch des Kutters, hier).
* Wer daneben schreiben wollte, gab nach Pythons Vorgabe von 5 Sekunden auf -- aus einer
  Verzoegerung wurde ein Fehler, bei ``PUT /api/prefs`` ein HTTP 500 fuer echte Nutzer.

Die Tests binden beides fest: die Wartezeit an ``get_connection``, die Transaktionsdauer an
``_check_transport_events``.
"""
from __future__ import annotations

import sqlite3

import pytest

from app.database import get_connection, init_db


class TestBusyTimeout:
    """#14 -- eine Verbindung wartet auf eine fremde Schreibsperre, statt sofort aufzugeben."""

    def test_get_connection_wartet_laenger_als_pythons_vorgabe(self, tmp_path):
        """``PRAGMA busy_timeout`` steht auf der Taktzeit des Pollers (15 s).

        Der Wert ist bewusst gewaehlt: Wer laenger als einen vollen Poll-Zyklus nicht an die
        Datenbank kommt, hat kein Gedraenge mehr, sondern ein Problem -- das soll als Fehler
        sichtbar werden. Alles darunter ist Warten, kein Scheitern.
        """
        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        conn = get_connection(db_file)
        try:
            wert = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        finally:
            conn.close()
        assert wert == 15000, f"busy_timeout ist {wert} ms (Pythons Vorgabe waere 5000)"


class TestKiSpruchHaeltKeineSperre:
    """#15 -- der Abschlussspruch des Kutters darf keine Schreibtransaktion umspannen.

    Beleg vom 04.09.2026, nach dem Deploy von 14.20.3 (StatSim-Fall bereits behoben)::

        20:39:47  Running job _check_transport_events
        20:39:56  ERROR Fehler beim Speichern der Prefile-Signaturen   <- database is locked
        20:40:05  httpx2: POST https://api.anthropic.com/v1/messages 200 OK
        20:40:07  ERROR Fehler beim Speichern der Prefile-Signaturen   <- database is locked

    Zwei Sperren, beide um den API-Aufruf herum -- dieselbe Fehlerklasse wie 14.20.3, nur mit
    Sekunden statt Minuten.
    """

    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from app.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def _seed_feierabend_mit_flug(self, db_file: str) -> int:
        """Kutter-Event, dessen dtend erreicht ist, mit einem gelieferten Flug (flight_count > 0)
        und eingeschalteten KI-Spruechen -- genau der Zustand, in dem der Latch schreibt und
        danach die KI ruft."""
        from datetime import datetime, timedelta, timezone
        from app.database import create_transport_event, set_app_setting, set_transport_started
        from tests.test_poller import _seed_kutter_track

        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        dtstart = (now - timedelta(hours=3)).strftime(fmt)
        dtend = (now - timedelta(minutes=10)).strftime(fmt)
        logon = (now - timedelta(hours=2)).strftime(fmt)
        logoff = (now - timedelta(hours=1)).strftime(fmt)
        conn = get_connection(db_file)
        try:
            eid = create_transport_event(
                conn, name="Helgoland-Nachschub", route="EDWG,EDXH",
                dtstart=dtstart, dtend=dtend, destination="EDXH",
            )
            set_transport_started(conn, eid, dtstart)
            set_app_setting(conn, "transport_quips_enabled", "1")
            conn.execute(
                "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (7, 'P', ?)",
                (dtstart,),
            )
            conn.execute(
                "INSERT INTO flights (cid, callsign, departure, arrival, logon_time, "
                "logoff_time, duration_min) VALUES (7, 'FRS07', 'EDWG', 'EDXH', ?, ?, 60)",
                (logon, logoff),
            )
            _seed_kutter_track(conn, 7, "FRS07", "EDWG", "EDXH", logon, logoff)
            conn.commit()
        finally:
            conn.close()
        return eid

    @pytest.mark.asyncio
    async def test_zweiter_schreiber_kommt_waehrend_des_ki_aufrufs_durch(self, tmp_path):
        """Waehrend ``llm.event_summary`` laeuft, muss ein anderer Schreiber sofort drankommen.

        Der zweite Schreiber oeffnet mit ``timeout=0`` -- er wartet also keine Millisekunde.
        Das ist Absicht: Er prueft, ob die Sperre in diesem Moment ueberhaupt frei ist, und
        nicht, ob der ``busy_timeout`` aus #14 lange genug ist.
        """
        from unittest.mock import AsyncMock, patch
        from app.poller import VatsimPoller

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        eid = self._seed_feierabend_mit_flug(db_file)

        beobachtung: dict[str, str] = {}

        def langsamer_spruch(_kontext):
            zweit = sqlite3.connect(db_file, timeout=0)
            try:
                zweit.execute(
                    "INSERT OR REPLACE INTO pilots (cid, name, added_at) "
                    "VALUES (99, 'Zweitschreiber', '2026-09-04T20:39:56Z')"
                )
                zweit.commit()
                beobachtung["zweiter_schreiber"] = "durchgekommen"
            except sqlite3.OperationalError as exc:
                beobachtung["zweiter_schreiber"] = f"gescheitert: {exc}"
            finally:
                zweit.close()
            return "Feierabend, Fisch ist drin!"

        poller = VatsimPoller(db_path=db_file, callsign_prefix="FRS", poll_interval=60)
        with patch("app.llm.event_summary", side_effect=langsamer_spruch), \
                patch.object(VatsimPoller, "_gen_flight_quip", AsyncMock()), \
                patch("app.poller.send_web_push", new=AsyncMock()):
            await poller._check_transport_events()

        assert beobachtung.get("zweiter_schreiber") == "durchgekommen", (
            f"Schreibsperre stand waehrend des KI-Aufrufs: {beobachtung.get('zweiter_schreiber')}"
        )

        # Der Spruch muss trotzdem ankommen -- das Auftrennen darf ihn nicht verlieren.
        conn = get_connection(db_file)
        try:
            row = conn.execute(
                "SELECT summary_quip, summarized_at FROM transport_events WHERE id = ?", (eid,)
            ).fetchone()
        finally:
            conn.close()
        assert row["summary_quip"] == "Feierabend, Fisch ist drin!"
        assert row["summarized_at"] is not None


class TestSpruchFehlschlagKostetNurDenSpruch:
    """Nachhut zu #15: Die Spruch-Schleife laeuft jetzt NACH dem Schliessen der Verbindung und
    bedient mehrere Events hintereinander. Faellt die KI fuer eines aus, darf das die uebrigen
    nicht mitreissen -- und der Feierabend-Push muss trotzdem raus, mit dem Vorgabetext.
    """

    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from app.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_ki_fehler_verhindert_den_feierabend_push_nicht(self, tmp_path):
        from unittest.mock import AsyncMock, patch
        from app.database import upsert_push_subscription
        from app.poller import VatsimPoller

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        eid = TestKiSpruchHaeltKeineSperre()._seed_feierabend_mit_flug(db_file)
        conn = get_connection(db_file)
        try:
            upsert_push_subscription(conn, "e1", "p1", "a1", notify_events=True)
            conn.commit()
        finally:
            conn.close()

        gesendet = []
        poller = VatsimPoller(
            db_path=db_file, callsign_prefix="FRS", poll_interval=60,
            vapid_private_key="priv", vapid_contact_email="mailto:x@y.z",
        )
        with patch("app.llm.event_summary", side_effect=RuntimeError("Overloaded")), \
                patch.object(VatsimPoller, "_gen_flight_quip", AsyncMock()), \
                patch("app.poller.send_web_push",
                      new=AsyncMock(side_effect=lambda *a, **k: gesendet.append(a))):
            await poller._check_transport_events()
            await __import__("asyncio").sleep(0)

        assert len(gesendet) == 1, "Feierabend-Push fehlt, obwohl nur der Spruch scheiterte"
        assert "Feierabend" in gesendet[0][4]["body"]

        conn = get_connection(db_file)
        try:
            row = conn.execute(
                "SELECT summarized_at, summary_quip FROM transport_events WHERE id = ?", (eid,)
            ).fetchone()
        finally:
            conn.close()
        assert row["summarized_at"] is not None   # Latch steht, er haengt nicht an der KI
        assert row["summary_quip"] is None
