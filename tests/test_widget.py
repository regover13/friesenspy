"""Tests für das einbettbare /widget — Transparenz, Hell/Dunkel-Schalter, FF-Palette.

Hintergrund: Das Widget hatte die Hintergrundfarbe der Homepage fest verdrahtet und saß
in andersfarbigen Containern (z. B. dem rosa Regeln-Kasten des Forums) als sichtbarer
Fleck. Seit v9.2.4 ist die Fläche transparent — dadurch kann das iframe aber nicht mehr
wissen, ob die einbettende Seite hell oder dunkel ist; dafür gibt es `?dark=1`.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.main as main
from app.database import init_db


class FakeReq:
    def __init__(self, query=None, poller=None):
        self.query_params = query or {}
        self.app = SimpleNamespace(state=SimpleNamespace(poller=poller))


@pytest.fixture
def widget_env(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    monkeypatch.setattr(
        main, "get_settings",
        lambda: SimpleNamespace(
            DB_PATH=p, CALLSIGN_PREFIX="FRS", TS_NOTIFY_ENABLED=True,
        ),
    )
    monkeypatch.setattr(main, "get_live_positions", lambda conn: [{"callsign": "FRS49"}])
    monkeypatch.setattr(
        main, "get_stats",
        lambda conn, days, callsign_prefix: [{"total_duration_min": 120}],
    )
    return SimpleNamespace(poller=SimpleNamespace(last_prefiles=[], ts_clients=["a"]))


def _render(env, query=None):
    resp = asyncio.run(main.widget(FakeReq(query=query, poller=env.poller)))
    return resp.body.decode("utf-8")


def test_hintergrund_ist_transparent(widget_env):
    """Kern der Änderung: keine eigene Flächenfarbe, sonst sitzt das Widget als Fleck."""
    html = _render(widget_env)
    assert "html,body{background:transparent}" in html
    assert "#d0e0f0" not in html  # die alte, fest verdrahtete Homepage-Farbe


def test_hell_ist_der_standard(widget_env):
    """Ohne Parameter: dunkle Schrift für helle Seiten (Homepage, Forum im Light Mode)."""
    html = _render(widget_env)
    assert "color:#053080" in html
    assert f"color:{main._FF_LBLUE}" not in html


@pytest.mark.parametrize("wert", ["1", "true", "yes", "on", "TRUE", "On"])
def test_dark_schaltet_auf_helle_schrift(widget_env, wert):
    html = _render(widget_env, {"dark": wert})
    assert f"color:{main._FF_LBLUE}" in html   # helle Schrift für dunkle Seiten
    assert "color:#053080" not in html


@pytest.mark.parametrize("wert", ["0", "false", "", "nein"])
def test_dark_bleibt_aus_bei_anderen_werten(widget_env, wert):
    html = _render(widget_env, {"dark": wert})
    assert "color:#053080" in html


def test_dark_gibt_der_zaehler_box_einen_rand(widget_env):
    """Die Navy-Box würde auf dunklem Grund sonst mit dem Hintergrund verschwimmen."""
    hell = _render(widget_env)
    dunkel = _render(widget_env, {"dark": "1"})
    assert f"border:1px solid {main._FF_LBLUE}" in dunkel
    assert "border:1px solid transparent" in hell


def test_zaehler_stehen_in_einer_gemeinsamen_navy_box(widget_env):
    html = _render(widget_env)
    assert f".side{{background:{main._FF_NAVY}" in html
    # beide Zähler liegen in derselben Box (im Markup mit &nbsp; statt Leerzeichen)
    side = html.split('<div class="side">')[1].split('</div>')[0]
    assert "online" in side and "TS" in side
    assert side.count('class="badge') == 2


def test_keine_markenfremden_farben(widget_env):
    """Nur die FF-Palette: das frühere TS-Grün und das alte Rot sind raus."""
    for html in (_render(widget_env), _render(widget_env, {"dark": "1"})):
        assert "#0a7a3a" not in html   # Grün — gibt es in der FF-Palette nicht
        assert "#D31141" not in html   # altes Badge-Rot, nicht aus dem Repaint Kit


def test_ts_badge_fehlt_wenn_teamspeak_aus(tmp_path, monkeypatch):
    p = str(tmp_path / "t2.db")
    init_db(p)
    monkeypatch.setattr(
        main, "get_settings",
        lambda: SimpleNamespace(DB_PATH=p, CALLSIGN_PREFIX="FRS", TS_NOTIFY_ENABLED=False),
    )
    monkeypatch.setattr(main, "get_live_positions", lambda conn: [])
    monkeypatch.setattr(main, "get_stats", lambda conn, days, callsign_prefix: [])
    poller = SimpleNamespace(last_prefiles=[], ts_clients=[])
    html = asyncio.run(main.widget(FakeReq(poller=poller))).body.decode("utf-8")
    assert "im TS" not in html
    assert "online" in html
