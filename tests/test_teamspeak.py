"""Tests für app/teamspeak.py."""
from __future__ import annotations

import pytest

from app.teamspeak import parse_frs
from app.teamspeak import _parse_clientlist


class TestParseFrs:
    @pytest.mark.parametrize("nick,expected", [
        ("Vorname Nachname/FRS22", "FRS22"),
        ("Klaus Löfflad | FRS22", "FRS22"),
        ("FRS22/Vorname Nachname", "FRS22"),
        ("Marco WeißFRS135(MSFS2024)", "FRS135"),
        ("frs7 lowercase", "FRS7"),
        ("FRS135A", "FRS135A"),
        ("Nur ein Name", None),
        ("", None),
    ])
    def test_parse_frs(self, nick, expected):
        assert parse_frs(nick) == expected


class TestParseClientlist:
    RAW = [
        {"clid": "1", "cid": "5", "client_type": "0", "client_nickname": "Max/FRS1"},
        {"clid": "2", "cid": "7", "client_type": "0", "client_nickname": "Anna FRS2"},
        {"clid": "3", "cid": "5", "client_type": "0", "client_nickname": "Gast ohne Tag"},
        {"clid": "4", "cid": "5", "client_type": "1", "client_nickname": "serveradmin"},
    ]

    def test_filter_target_channel(self):
        out = _parse_clientlist(self.RAW, channel_id=5)
        assert out == [{"frs": "FRS1", "nick": "Max/FRS1", "cid": 5}]

    def test_other_channel_excluded(self):
        out = _parse_clientlist(self.RAW, channel_id=7)
        assert [c["frs"] for c in out] == ["FRS2"]

    def test_whole_server_when_zero(self):
        out = _parse_clientlist(self.RAW, channel_id=0)
        assert {c["frs"] for c in out} == {"FRS1", "FRS2"}

    def test_query_clients_and_untagged_excluded(self):
        out = _parse_clientlist(self.RAW, channel_id=0)
        assert all(c["frs"] for c in out)
        assert "serveradmin" not in [c["nick"] for c in out]
