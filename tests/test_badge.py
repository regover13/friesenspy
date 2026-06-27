"""Tests für die Bummel-Badge-Erzeugung (Pillow)."""
from __future__ import annotations

from app.badge import render_medal, render_winner_badge

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _is_png(b: bytes) -> bool:
    return isinstance(b, (bytes, bytearray)) and b[:8] == _PNG_MAGIC and len(b) > 500


class TestWinnerBadge:
    def test_returns_valid_png(self):
        png = render_winner_badge({
            "callsign": "FRS49", "name": "Tobias", "aircraft": "PA24",
            "total_min": 80, "delta": 0, "rank": 1, "date": "27.06.2026",
        })
        assert _is_png(png)

    def test_handles_missing_fields(self):
        assert _is_png(render_winner_badge({"callsign": "FRS1"}))


class TestMedal:
    def test_complete_with_delta(self):
        png = render_medal({
            "callsign": "FRS93", "name": "Arvind", "aircraft": "C172",
            "delta": 20, "complete": True, "date": "27.06.2026",
        })
        assert _is_png(png)

    def test_incomplete(self):
        png = render_medal({
            "callsign": "FRS5", "name": "X", "aircraft": "C152",
            "complete": False, "date": "27.06.2026",
        })
        assert _is_png(png)

    def test_handles_missing_fields(self):
        assert _is_png(render_medal({"callsign": "FRS1"}))
