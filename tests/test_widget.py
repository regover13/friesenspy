"""Tests für das einbettbare /widget — Layout-Grundgerüst und FF-Palette.

Das Widget bringt bewusst seine eigene helle Fläche mit (#d0e0f0, die Farbe von
friesenflieger.de) statt transparent zu sein: dadurch bleibt es auch dann lesbar, wenn
die einbettende Seite auf Dark Mode steht. Die Zähler sitzen zusammen mit dem
Schriftzug in der dunkelblauen Kopfzeile.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.main as main
from app.database import init_db


class FakeReq:
    def __init__(self, poller=None):
        self.app = SimpleNamespace(state=SimpleNamespace(poller=poller))


@pytest.fixture
def widget_env(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    monkeypatch.setattr(
        main, "get_settings",
        lambda: SimpleNamespace(DB_PATH=p, CALLSIGN_PREFIX="FRS", TS_NOTIFY_ENABLED=True),
    )
    monkeypatch.setattr(main, "get_live_positions", lambda conn: [{"callsign": "FRS49"}])
    monkeypatch.setattr(
        main, "get_stats",
        lambda conn, days, callsign_prefix: [{"total_duration_min": 120}],
    )
    return SimpleNamespace(poller=SimpleNamespace(last_prefiles=[], ts_clients=["a"]))


def _render(env):
    resp = asyncio.run(main.widget(FakeReq(poller=env.poller)))
    return resp.body.decode("utf-8")


def test_bringt_eigene_helle_flaeche_mit(widget_env):
    """Eigene Fläche statt transparent — sonst wäre die Schrift im Dark Mode unlesbar."""
    html = _render(widget_env)
    assert "background:#d0e0f0" in html


def test_zaehler_sitzen_in_der_kopfzeile_beim_schriftzug(widget_env):
    html = _render(widget_env)
    kopf = html.split('<div class="hd">')[1].split("</div>")[0]
    assert "FriesenSpy" in kopf
    assert "online" in kopf and "TS" in kopf


def test_badges_sind_ff_hellblau_auf_navy(widget_env):
    """Beide Zähler tragen dieselbe FF-Hellblau-Fläche mit dunklem Text."""
    html = _render(widget_env)
    assert f".badge{{background:{main._FF_LBLUE};color:{main._FF_NAVY}" in html
    assert f".ts-badge{{background:{main._FF_LBLUE}}}" in html


def test_keine_markenfremden_badge_farben(widget_env):
    """Grün gibt es in der FF-Palette nicht; das alte Badge-Rot stammt nicht aus dem Kit."""
    html = _render(widget_env)
    assert "#0a7a3a" not in html   # früheres TS-Grün
    assert "#D31141" not in html   # früheres Badge-Rot


def test_badge_symbole_sind_svg_statt_emoji(widget_env):
    """Ein Farb-Emoji bringt eigene Farben mit und liegt blass auf dem hellblauen Badge;
    das SVG übernimmt per currentColor die Navy-Schriftfarbe."""
    html = _render(widget_env)
    assert "🎧" not in html
    assert html.count('fill="currentColor"') == 2   # Flugzeug (online) + Headset (TS)


def test_online_badge_traegt_das_flugzeug(widget_env):
    html = _render(widget_env)
    online = html.split('<span class="badge">')[1].split("</span>")[0]
    assert main._ICON_PLANE in online
    assert "online" in online


def test_dunkler_balken_bleibt_um_die_badges_stehen(widget_env):
    """Die Kopfzeile ist höher gepolstert als die Badges — der Balken rahmt sie."""
    html = _render(widget_env)
    assert ".hd{background:#053080" in html
    assert "padding:4px 10px" in html   # Kopfzeile
    assert "padding:1px 6px" in html    # Badges, kleiner -> Balken bleibt sichtbar


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
    assert "im&nbsp;TS" not in html
    assert "online" in html
