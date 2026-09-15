"""Der Sekundenstrom traegt den Fremdverkehr NICHT ins Kniebrett (GitHub-Issue #39).

Der Broadcast kennt seine Empfaenger nicht — jede offene Verbindung bekommt dieselbe
Nachricht. Seit der Schalterstufe `fremd` koennen darin bis zu 40 zusaetzliche Flugzeuge
stehen, und das Kniebrett wirft sie **alle** weg: Im Cockpit traegt das Sim-Matching, und
`_kniebrettFremdEinarbeiten` steigt bei `_PANEL_MODUS` sofort aus. Bis dahin sind sie aber
ueber die Netzverbindung des Simulators gegangen.

⚠ **Diese Datei bindet zwei Enden aneinander**, die in verschiedenen Sprachen stehen:
`app/static/index.html` haengt `?kb=1` an die SSE-URL, `app/main.py` liest den Parameter.
Faellt eine Seite weg, merkt es sonst niemand — der Strom sieht in beiden Faellen gesund aus,
er ist nur zu breit (oder das Feld fehlt ueberall).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main
from app.database import init_db
from app.poller import VatsimPoller

INDEX = Path("app/static/index.html")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    monkeypatch.setattr(main, "get_settings",
                        lambda: SimpleNamespace(DB_PATH=p, SECRET_KEY="s3cr3t"))
    return p


class _FakeRequest:
    def __init__(self, query_params: dict | None = None, runden: int = 1):
        self.cookies = {}
        self.query_params = query_params or {}
        self._uebrig = runden

    async def is_disconnected(self) -> bool:
        self._uebrig -= 1
        return self._uebrig < 0


def _poller(db: str) -> VatsimPoller:
    return VatsimPoller(db_path=db, callsign_prefix="FRS", poll_interval=60)


async def _ausgeliefert(request, poller, aktion) -> list[dict]:
    raus: list[dict] = []

    async def lauf():
        async for stueck in main._event_generator(request, poller):
            if stueck.startswith("data: "):
                raus.append(json.loads(stueck[6:]))

    aufgabe = asyncio.ensure_future(lauf())
    await asyncio.sleep(0.05)          # Abonnement steht
    aktion(poller)
    await asyncio.wait_for(aufgabe, timeout=5)
    return raus


def _strom_mit_fremd(poller: VatsimPoller) -> None:
    """Ein Friese aus seiner Bruegge, dazu ein Fremdflugzeug aus einem Kniebrett."""
    jetzt = time.monotonic()
    poller._bruegge_live[100200] = {
        "cid": 100200, "lat": 53.7, "lon": 7.15, "alt": 2500, "hdg": 270,
        "gs": 95, "ts": jetzt, "guete": poller.QUELLE_FREMD, "melder": None,
    }
    poller._kniebrett_fremd["DLH400"] = {
        "cs": "DLH400", "lat": 50.03, "lon": 8.57, "alt": 12000, "hdg": 90,
        "gs": 320, "ts": jetzt, "melder": 100200,
    }
    poller.bruegge_strom_senden()


class TestStromFilter:
    def test_karte_bekommt_den_fremdverkehr(self, env):
        """Ohne `kb=1` bleibt alles, wie es war — die Website lebt davon."""
        raus = asyncio.run(_ausgeliefert(_FakeRequest(), _poller(env), _strom_mit_fremd))
        assert len(raus) == 1
        assert [e["cs"] for e in raus[0]["fremd"]] == ["DLH400"]

    def test_kniebrett_bekommt_ihn_nicht(self, env):
        raus = asyncio.run(_ausgeliefert(_FakeRequest({"kb": "1"}), _poller(env),
                                         _strom_mit_fremd))
        assert len(raus) == 1
        assert "fremd" not in raus[0]

    def test_kniebrett_bekommt_die_friesen_weiterhin(self, env):
        """Gefiltert wird EIN Feld, nicht die Nachricht.

        Die Friesen-Positionen sind der Grund, warum das Kniebrett den Strom ueberhaupt
        abonniert.
        """
        raus = asyncio.run(_ausgeliefert(_FakeRequest({"kb": "1"}), _poller(env),
                                         _strom_mit_fremd))
        assert raus[0]["type"] == "bruegge"
        assert [e["cid"] for e in raus[0]["data"]] == [100200]

    def test_andere_nachrichten_bleiben_unberuehrt(self, env):
        """Der Filter darf nur an `type: bruegge` gehen — `positions` traegt kein `fremd`,
        aber ein zu grober Filter faende hier trotzdem etwas zum Wegwerfen."""
        def aktion(p):
            p.broadcast_sse({"type": "positions", "data": [{"cid": 1}], "fremd": ["x"]})
        raus = asyncio.run(_ausgeliefert(_FakeRequest({"kb": "1"}), _poller(env), aktion))
        assert raus[0].get("fremd") == ["x"]

    def test_die_nachricht_der_anderen_bleibt_heil(self, env):
        """⚠ Der Broadcast legt DASSELBE dict in jede Queue.

        Wer im Generator `del data["fremd"]` schreibt, nimmt das Feld auch den Karten weg —
        und zwar nur dann, wenn zufaellig ein Kniebrett vor ihnen in der Schleife stand. Das
        ist genau die Sorte Fehler, die im Betrieb sporadisch aussieht.
        """
        nachricht = {"type": "bruegge", "data": [], "fremd": [{"cs": "DLH400"}]}
        raus = asyncio.run(_ausgeliefert(_FakeRequest({"kb": "1"}), _poller(env),
                                         lambda p: p.broadcast_sse(nachricht)))
        assert "fremd" not in raus[0]
        assert nachricht["fremd"] == [{"cs": "DLH400"}]   # Original unveraendert


class TestBeideEnden:
    """Quelltexttests — sie ersetzen den Browser, den es hier nicht gibt."""

    def test_das_kniebrett_haengt_kb_an_die_sse_url(self):
        s = INDEX.read_text(encoding="utf-8")
        # An die Zuweisung gebunden, nicht an den Kommentar daneben.
        m = re.search(r"sseSource\s*=\s*new EventSource\((.+?)\);", s)
        assert m, "SSE-Verbindung im Kniebrett nicht gefunden"
        assert "_PANEL_MODUS" in m.group(1) and "kb=1" in m.group(1), m.group(1)

    def test_die_website_haengt_nichts_an(self):
        s = INDEX.read_text(encoding="utf-8")
        m = re.search(r"sseSource\s*=\s*new EventSource\((.+?)\);", s)
        assert "'/api/sse'" in m.group(1), m.group(1)

    def test_der_server_liest_denselben_parameter(self):
        s = Path("app/main.py").read_text(encoding="utf-8")
        assert 'query_params.get("kb") == "1"' in s

    def test_beide_seiten_verweisen_aufeinander(self):
        """Ein Kommentar an nur einem Ende findet nicht, wer am anderen sitzt."""
        assert "app/main.py" in INDEX.read_text(encoding="utf-8")
        assert "app/static/index.html" in Path("app/main.py").read_text(encoding="utf-8")
