"""Tests für die KI-Sprüche in app/llm.py (event_summary, flight_quip).

Kein echter API-Call: ``_chat`` wird gemockt, damit wir den generierten Prompt prüfen können —
das eigentliche Sprach-Modell wird nicht getestet, nur dass die Fakten (insbesondere Verluste)
überhaupt im Prompt ankommen (#67-Folgefund: Tagesend-Spruch behauptete "niemand versunken",
obwohl event_summary() die Verlust-Fakten aus dem Kontext gar nicht in den Prompt übernahm).
"""
from unittest.mock import patch

from app import llm


class TestEventSummaryPrompt:
    def test_prompt_includes_losses_when_present(self):
        captured = {}

        def fake_chat(system, user, max_tokens):
            captured["user"] = user
            return "Spruch"

        context = {
            "name": "Test", "route": "EDWG ↔ EDXP", "destination": "EDXP",
            "total_kg": 460, "loaded_count": 3, "cargo": ["🦐 Krabbenbrötchen 460/460 kg"],
            "pilots": {"Tobias": 3},
            "lost_total_kg": 292.0,
            "verluste": ["Klaus: Kutter versunken (292 kg)"],
        }
        with patch.object(llm, "_chat", side_effect=fake_chat):
            result = llm.event_summary(context)
        assert result == "Spruch"
        assert "Klaus: Kutter versunken (292 kg)" in captured["user"]
        assert "MUSST du sie erwähnen" in captured["user"]

    def test_prompt_states_no_losses_when_absent(self):
        captured = {}

        def fake_chat(system, user, max_tokens):
            captured["user"] = user
            return "Spruch"

        context = {
            "name": "Test", "route": "EDWG ↔ EDXP", "destination": "EDXP",
            "total_kg": 460, "loaded_count": 3, "cargo": ["🦐 Krabbenbrötchen 460/460 kg"],
            "pilots": {"Tobias": 3},
            "lost_total_kg": 0.0,
            "verluste": [],
        }
        with patch.object(llm, "_chat", side_effect=fake_chat):
            llm.event_summary(context)
        assert "Verluste: keine — alles kam heil an" in captured["user"]
