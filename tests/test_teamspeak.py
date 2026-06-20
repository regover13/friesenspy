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
        ("FRS13N", "FRS13N"),
        ("Tobias/FRS13N", "FRS13N"),
        ("FRS13N | Tobias", "FRS13N"),
        ("frs13n lowercase", "FRS13N"),
        # Nur "N" ist ein gültiges Suffix — andere Buchstaben gehören nicht zum Callsign
        ("FRS135A", "FRS135"),
        ("FRS22X", "FRS22"),
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


from unittest.mock import patch
from app.teamspeak import fetch_channel_clients


class TestFetchChannelClients:
    @pytest.mark.asyncio
    async def test_returns_sync_result(self):
        fake = [{"frs": "FRS1", "nick": "Max/FRS1", "cid": 5}]
        with patch("app.teamspeak._fetch_clients_sync", return_value=fake):
            out = await fetch_channel_clients(
                host="h", port=10011, user="u", password="p",
                server_id=1, channel_id=5,
            )
        assert out == fake

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self):
        with patch("app.teamspeak._fetch_clients_sync", side_effect=OSError("refused")):
            out = await fetch_channel_clients(
                host="h", port=10011, user="u", password="p",
                server_id=1, channel_id=0,
            )
        assert out is None


from app.teamspeak import parse_channel_ids


class TestParseChannelIds:
    def test_empty_is_empty_set(self):
        assert parse_channel_ids("") == frozenset()
        assert parse_channel_ids(None) == frozenset()

    def test_parses_csv(self):
        assert parse_channel_ids("12,13,14") == frozenset({12, 13, 14})

    def test_ignores_whitespace_and_invalid(self):
        assert parse_channel_ids(" 12 , , 13 ,abc, 14,") == frozenset({12, 13, 14})


class TestExcludeChannels:
    RAW = [
        {"clid": "1", "cid": "7", "client_type": "0", "client_nickname": "Max/FRS1"},   # Gaststube
        {"clid": "2", "cid": "12", "client_type": "0", "client_nickname": "Admin FRS2"}, # Verwaltung
        {"clid": "3", "cid": "13", "client_type": "0", "client_nickname": "Boss FRS3"},  # Staff (unter Verwaltung)
    ]

    def test_excluded_channels_dropped(self):
        out = _parse_clientlist(self.RAW, channel_id=0, exclude_channel_ids=frozenset({12, 13}))
        assert [c["frs"] for c in out] == ["FRS1"]

    def test_no_exclusion_keeps_all(self):
        out = _parse_clientlist(self.RAW, channel_id=0)
        assert {c["frs"] for c in out} == {"FRS1", "FRS2", "FRS3"}

    @pytest.mark.asyncio
    async def test_fetch_passes_exclusion_through(self):
        captured = {}

        def fake_sync(host, port, user, password, server_id, channel_id, exclude_channel_ids=frozenset()):
            captured["exclude"] = exclude_channel_ids
            return [{"frs": "FRS1", "nick": "Max/FRS1", "cid": 7}]

        with patch("app.teamspeak._fetch_clients_sync", side_effect=fake_sync):
            out = await fetch_channel_clients(
                host="h", port=10011, user="u", password="p",
                server_id=1, channel_id=0, exclude_channel_ids=frozenset({12, 13}),
            )
        assert captured["exclude"] == frozenset({12, 13})
        assert out == [{"frs": "FRS1", "nick": "Max/FRS1", "cid": 7}]
