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

    def test_prompt_frames_destination_not_route_chain(self):
        # Live-Fund 09.07.: die KI textete „auf der Runde EDWG-EDWL-EDXH-EDXP", weil der Prompt die
        # Streckenplätze als Kette fütterte. Jetzt: Ziel als Anker, Abholplätze getrennt, plus
        # explizite Ansage, es NICHT als Runde darzustellen.
        captured = {}

        def fake_chat(system, user, max_tokens):
            captured["user"] = user
            return "Spruch"

        context = {
            "name": "Multi-Kutter", "destination": "EDWG",
            "pickups": ["EDWL", "EDXH", "EDXP"],
            "total_kg": 618, "loaded_count": 4, "cargo": ["🦐 Krabbenbrötchen 368/500 kg"],
            "pilots": {"Tobias": 4}, "lost_total_kg": 0.0, "verluste": [],
        }
        with patch.object(llm, "_chat", side_effect=fake_chat):
            llm.event_summary(context)
        u = captured["user"]
        assert "EDWG" in u                              # Ziel als Anker
        assert "EDWL, EDXH, EDXP" in u                   # Abholplätze getrennt gelistet
        assert "KEINE geflogene Route" in u             # Anti-Runde-Ansage steht im Prompt
        assert "↔" not in u                             # keine irreführende Pfeil-Kette mehr


class TestFlightQuipPrompt:
    """#67-Folgefund: der EINZELflug-Spruch (flight_quip) ignorierte das im Kontext bereits
    berechnete `verlust`-Feld und textete für einen geklauten/versunkenen Flug einen normalen
    Liefer-Spruch."""

    def _capture(self, context):
        captured = {}

        def fake_chat(system, user, max_tokens):
            captured["user"] = user
            return "Spruch"

        with patch.object(llm, "_chat", side_effect=fake_chat):
            result = llm.flight_quip(context)
        assert result == "Spruch"
        return captured["user"]

    def test_prompt_frames_theft_when_loss_present(self):
        user = self._capture({
            "vorname": "Tobias", "callsign": "FRS49", "flights_tonight": 0,
            "aircraft": "PZ04", "route": "EDWG→EDWZ", "tonnage_kg": 290,
            "cargo": ["🪑 Strandkörbe (290 kg)"], "speed_kt": None, "detour_ratio": None,
            "verlust": "am falschen Ort gelandet (EDWZ) — 290 kg Fracht geklaut",
        })
        assert "am falschen Ort gelandet (EDWZ) — 290 kg Fracht geklaut" in user
        assert "DIESER FLUG GING SCHIEF" in user

    def test_prompt_normal_delivery_has_no_loss_framing(self):
        user = self._capture({
            "vorname": "Marco", "callsign": "FRS135", "flights_tonight": 1,
            "aircraft": "C172", "route": "EDWG→EDWY", "tonnage_kg": 160,
            "cargo": ["⛱️ Sonnenschirme (120 kg)", "🪑 Strandkörbe (40 kg)"],
            "speed_kt": 98, "detour_ratio": None, "verlust": None,
        })
        assert "GING SCHIEF" not in user
