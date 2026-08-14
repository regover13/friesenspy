"""Sim-Benachrichtigungen im SSE-Strom (Anzeigefläche: MSFS-Kniebrett).

Der Schwerpunkt liegt auf der Filterung: `/api/sse` ist unauthentifiziert und geht an alle
Verbindungen. Benachrichtigungen dürfen deshalb NUR an angemeldete Zuschauer und nur nach
Subjekt-Sichtbarkeit raus — wer „nobody" gesetzt hat, taucht bei niemandem auf.
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from app import forum_sso, main
from app.database import get_connection, init_db, is_visible_to, set_pilot_visibility
from app.poller import VatsimPoller, payload_online, payload_prefile, payload_ts

SECRET = "s3cr3t-key"
SUBJEKT = 1234567          # der Pilot, über den benachrichtigt wird
ZUSCHAUER = 7654321        # wer zuschaut


@pytest.fixture()
def env(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    settings = SimpleNamespace(DB_PATH=p, SECRET_KEY=SECRET)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    return SimpleNamespace(db=p, settings=settings)


class _FakeRequest:
    """Minimaler Request-Ersatz: Cookies + ein Disconnect nach N Schleifendurchläufen.

    ``runden`` muss der Zahl der eingelegten Ereignisse entsprechen — auch ein verworfenes
    Ereignis verbraucht einen Durchlauf. Eine Runde zu viel und der Generator wartet 30 s auf
    Nachschub, bevor er den Keepalive schickt.
    """

    def __init__(self, cookies: dict | None = None, runden: int = 1):
        self.cookies = cookies or {}
        self._uebrig = runden

    async def is_disconnected(self) -> bool:
        self._uebrig -= 1
        return self._uebrig < 0


def _user_cookie(cid: int) -> dict:
    exp = time.time() + 3600
    return {"fs_user": forum_sso.make_user_token(SECRET, "Pilot", str(cid), False, exp)}


async def _ausgeliefert(request, poller, aktion) -> list[dict]:
    """Generator laufen lassen, dabei ``aktion(poller)`` broadcasten, Ausgabe einsammeln.

    Die Reihenfolge ist entscheidend: Der Generator abonniert seine Queue erst beim ersten
    Durchlauf. Wer vorher broadcastet, sendet an niemanden — der Broadcast kennt keine
    Abonnenten und verwirft still.
    """
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


def _poller(db: str) -> VatsimPoller:
    return VatsimPoller(db_path=db, callsign_prefix="FRS", poll_interval=60)


# ---------------------------------------------------------------------------
# broadcast_notify — Form des Ereignisses
# ---------------------------------------------------------------------------

def test_broadcast_notify_legt_vollstaendiges_ereignis_ab(env):
    p = _poller(env.db)
    q = p.subscribe_sse()
    p.broadcast_notify("online", SUBJEKT, {"title": "FRS61 ist online! ✈",
                                           "body": "EDWG → EDXP", "url": "/"})
    ereignis = q.get_nowait()
    assert ereignis == {
        "type": "notify", "service": "online", "subject_cid": SUBJEKT,
        "title": "FRS61 ist online! ✈", "body": "EDWG → EDXP", "url": "/",
    }


def test_nutzlasten_je_kategorie_haben_titel_und_text():
    """Push und Sim-Meldung speisen sich aus denselben Funktionen — sie dürfen nicht leer sein."""
    online = payload_online({"callsign": "FRS61", "departure": "EDWG", "arrival": "EDXP",
                             "aircraft_short": "C172"})
    assert "FRS61" in online["title"] and "EDWG" in online["body"]

    prefile = payload_prefile({"callsign": "FRS61", "flight_plan": {
        "departure": "EDWG", "arrival": "EDXP", "deptime": "1430"}})
    assert "FRS61" in prefile["title"] and "14:30 UTC" in prefile["body"]

    ts = payload_ts("Micha")
    assert "Micha" in ts["title"]


# ---------------------------------------------------------------------------
# is_visible_to — die Regel, die Dritte schützt
# ---------------------------------------------------------------------------

def test_is_visible_to_folgt_der_subjekt_sichtbarkeit(env):
    conn = get_connection(env.db)
    try:
        # Ohne Eintrag: sichtbar (Vorgabe „everyone")
        assert is_visible_to(conn, SUBJEKT, ZUSCHAUER, "online") is True

        set_pilot_visibility(conn, SUBJEKT, "nobody", services=["online"])
        assert is_visible_to(conn, SUBJEKT, ZUSCHAUER, "online") is False
        # Andere Dienste bleiben von dieser Einschränkung unberührt
        assert is_visible_to(conn, SUBJEKT, ZUSCHAUER, "ts") is True

        set_pilot_visibility(conn, SUBJEKT, "allowlist", allowlist=[999], services=["online"])
        assert is_visible_to(conn, SUBJEKT, ZUSCHAUER, "online") is False
        assert is_visible_to(conn, SUBJEKT, 999, "online") is True
    finally:
        conn.close()


def test_is_visible_to_ohne_subjekt_und_ohne_zuschauer(env):
    conn = get_connection(env.db)
    try:
        # Event-Meldungen betreffen keine Person → immer sichtbar
        assert is_visible_to(conn, None, ZUSCHAUER, "events") is True
        # Nicht angemeldet → kein Empfänger
        assert is_visible_to(conn, SUBJEKT, None, "online") is False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# /api/sse — Auslieferung pro Verbindung
# ---------------------------------------------------------------------------

def _nur_positionen(p):
    p.broadcast_sse({"type": "positions", "data": []})


def _online_dann_positionen(p):
    p.broadcast_notify("online", SUBJEKT, {"title": "T", "body": "B", "url": "/"})
    p.broadcast_sse({"type": "positions", "data": []})


def _nur_online(p):
    p.broadcast_notify("online", SUBJEKT, {"title": "T", "body": "B", "url": "/"})


@pytest.mark.asyncio
async def test_positions_gehen_auch_ohne_anmeldung_raus(env):
    raus = await _ausgeliefert(_FakeRequest(runden=1), _poller(env.db), _nur_positionen)
    assert [e["type"] for e in raus] == ["positions"]


@pytest.mark.asyncio
async def test_notify_erreicht_keine_anonyme_verbindung(env):
    raus = await _ausgeliefert(_FakeRequest(runden=2), _poller(env.db),
                               _online_dann_positionen)
    assert [e["type"] for e in raus] == ["positions"]


@pytest.mark.asyncio
async def test_notify_erreicht_angemeldete_verbindung(env):
    raus = await _ausgeliefert(_FakeRequest(cookies=_user_cookie(ZUSCHAUER), runden=1),
                               _poller(env.db), _nur_online)
    assert [e["type"] for e in raus] == ["notify"]
    assert raus[0]["service"] == "online"
    assert raus[0]["subject_cid"] == SUBJEKT


@pytest.mark.asyncio
async def test_opt_out_des_subjekts_unterdrueckt_die_meldung(env):
    """Wenn Reiner „niemand" gesetzt hat, darf die Meldung bei Tobias nicht auftauchen."""
    conn = get_connection(env.db)
    try:
        set_pilot_visibility(conn, SUBJEKT, "nobody", services=["online"])
        conn.commit()
    finally:
        conn.close()

    raus = await _ausgeliefert(_FakeRequest(cookies=_user_cookie(ZUSCHAUER), runden=2),
                               _poller(env.db), _online_dann_positionen)
    assert [e["type"] for e in raus] == ["positions"]


@pytest.mark.asyncio
async def test_allowlist_laesst_nur_die_gelisteten_durch(env):
    conn = get_connection(env.db)
    try:
        set_pilot_visibility(conn, SUBJEKT, "allowlist", allowlist=[ZUSCHAUER],
                             services=["online"])
        conn.commit()
    finally:
        conn.close()

    drin = await _ausgeliefert(_FakeRequest(cookies=_user_cookie(ZUSCHAUER), runden=1),
                               _poller(env.db), _nur_online)
    assert [e["type"] for e in drin] == ["notify"]

    draussen = await _ausgeliefert(_FakeRequest(cookies=_user_cookie(4242), runden=2),
                                   _poller(env.db), _online_dann_positionen)
    assert [e["type"] for e in draussen] == ["positions"]


@pytest.mark.asyncio
async def test_event_meldungen_brauchen_kein_subjekt(env):
    """Event-Erinnerungen betreffen keine Person — sie passieren die Pruefung immer."""
    def aktion(p):
        p.broadcast_notify("events", None, {"title": "FriesenKutter", "body": "geht los",
                                            "url": "/"})

    raus = await _ausgeliefert(_FakeRequest(cookies=_user_cookie(ZUSCHAUER), runden=1),
                               _poller(env.db), aktion)
    assert [e["type"] for e in raus] == ["notify"]
