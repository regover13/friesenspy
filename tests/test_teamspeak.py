"""Tests für app/teamspeak.py."""
from __future__ import annotations

import pytest

from app.teamspeak import parse_frs


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
