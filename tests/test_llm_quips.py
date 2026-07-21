"""Tests für die KI-Sprüche in app/llm.py (event_summary, flight_quip).

Kein echter API-Call: ``_chat`` wird gemockt, damit wir den generierten Prompt prüfen können —
das eigentliche Sprach-Modell wird nicht getestet, nur dass die Fakten (insbesondere Verluste)
überhaupt im Prompt ankommen (#67-Folgefund: Tagesend-Spruch behauptete "niemand versunken",
obwohl event_summary() die Verlust-Fakten aus dem Kontext gar nicht in den Prompt übernahm).
"""
from unittest.mock import patch

from app import llm
from app.database import event_summary_context, flight_quip_context


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

    def test_returned_leg_is_relay_not_loss_in_prompt(self):
        # v10.2.1-Umbenennung: eine „returned"-Bewegung heißt jetzt „am Ladeplatz abgeladen"
        # (Staffel-Übergabe, KEIN Verlust), nie mehr „zurückgebracht"/„umgedreht". Die
        # Umbenennung war nur in der UI, nicht in der KI-Schicht — der Tagesend-Spruch redete
        # weiter von „zurückgebracht" und framte den Piloten als „unentschlossen" (Live-Fund
        # 21.07., #238/#239). Ein abgeladenes Leg darf NICHT in der „MUSST als Verlust nennen"-
        # Liste landen.
        captured = {}

        def fake_chat(system, user, max_tokens):
            captured["user"] = user
            return "Spruch"

        context = {
            "name": "Touristen für Helgoland", "destination": "EDXH",
            "pickups": ["EDWG", "EDWY"], "total_kg": 300, "loaded_count": 1,
            "cargo": ["🧳 Passagiere 300/600 kg"], "pilots": {"Reiner (FRS61)": 1},
            "lost_total_kg": 0.0, "verluste": [],
            "abgeladen": ["Reiner (FRS61): Fracht an einem Ladeplatz abgeladen (liegt zum Weitertragen bereit)"],
        }
        with patch.object(llm, "_chat", side_effect=fake_chat):
            llm.event_summary(context)
        u = captured["user"]
        assert "Ladeplatz abgeladen" in u
        assert "zurückgebracht" not in u
        assert "umgedreht" not in u

    def test_event_summary_has_headroom_for_many_pilots(self):
        # Live-Fund 21.07. (#237): der Abschluss-Spruch nannte 5 Piloten + Verluste und wurde
        # mitten im Wort abgeschnitten („… und als wäre das nicht genug, ist s"). max_tokens war
        # 400 — zu knapp für eine volle Bilanz mit vielen Piloten.
        captured = {}

        def fake_chat(system, user, max_tokens):
            captured["max_tokens"] = max_tokens
            return "Spruch"

        context = {
            "name": "Krabbenbrötchen für Wooge", "destination": "EDWG",
            "pickups": ["EDWJ", "EDWY", "EDWZ", "EDXH", "EDXP"], "total_kg": 3350,
            "loaded_count": 5, "cargo": ["🦐 Krabbenbrötchen 3350/3660 kg"],
            "pilots": {"Reiner (FRS61)": 2, "Michael (FRS96)": 1, "Tobias (FRS49)": 1,
                       "Micha (FRS44)": 1, "Ralf (FRS102)": 1},
            "lost_total_kg": 310.0,
            "verluste": ["Ralf (FRS102): Fracht geklaut (230 kg)", "Ralf (FRS102): Kutter versunken (80 kg)"],
            "abgeladen": [],
        }
        with patch.object(llm, "_chat", side_effect=fake_chat):
            llm.event_summary(context)
        assert captured["max_tokens"] >= 800

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

    def test_returned_leg_framed_as_relay_not_failure(self):
        # v10.2.1-Umbenennung auch für den Einzelflug-Spruch: eine „returned"-Bewegung ist eine
        # Staffel-Übergabe („am Ladeplatz abgeladen"), KEIN schiefgegangener Flug — darf nicht
        # über den „GING SCHIEF / neck ihn fürs Kneifen"-Zweig laufen.
        user = self._capture({
            "vorname": "Reiner", "callsign": "FRS61", "flights_tonight": 1,
            "aircraft": "C172", "route": "EDWY→EDWG", "tonnage_kg": 300,
            "cargo": ["🧳 Passagiere (300 kg)"], "speed_kt": 92, "detour_ratio": None,
            "verlust": None, "relay": "an einem Ladeplatz abgeladen (nicht bis zum Ziel) — liegt dort zum Weitertragen bereit",
        })
        assert "GING SCHIEF" not in user
        assert "Ladeplatz abgeladen" in user
        assert "zurückgebracht" not in user
        assert "umgedreht" not in user


class TestReturnedRelayContext:
    """Die Kontext-Bauer in app.database dürfen eine „returned"-Bewegung nicht mehr als Verlust
    („zurückgebracht"/„umgedreht") ausweisen, sondern als Staffel-Übergabe am Ladeplatz."""

    def test_event_summary_context_splits_relay_out_of_verluste(self):
        progress = {
            "name": "Test", "destination": "EDXH", "route": ["EDWG", "EDWY", "EDXH"],
            "total_kg": 300, "loaded_count": 2, "cargo": [], "lost_total_kg": 130.0,
            "flights": [
                {"cid": 61, "name": "Reiner Meyer", "callsign": "FRS61", "loaded": True},
                {"cid": 96, "name": "Michael Schmidt", "callsign": "FRS96", "loaded": True},
            ],
            "losses": [
                {"cid": 61, "name": "Reiner Meyer", "callsign": "FRS61", "loss_kind": "returned", "lost_kg": 0.0},
                {"cid": 96, "name": "Michael Schmidt", "callsign": "FRS96", "loss_kind": "stolen", "lost_kg": 130.0},
            ],
        }
        ctx = event_summary_context({"name": "Test"}, progress)
        verluste_joined = " ".join(ctx["verluste"])
        abgeladen_joined = " ".join(ctx.get("abgeladen") or [])
        assert "FRS96" in verluste_joined and "geklaut" in verluste_joined
        assert "FRS61" not in verluste_joined            # Relay ist kein Verlust
        assert "FRS61" in abgeladen_joined
        assert "Ladeplatz abgeladen" in abgeladen_joined
        assert "zurückgebracht" not in verluste_joined + abgeladen_joined

    def test_flight_quip_context_returned_sets_relay_not_verlust(self):
        flight = {
            "cid": 61, "name": "Reiner Meyer", "callsign": "FRS61", "aircraft": "C172",
            "dep": "EDWY", "arr": "EDWG", "distance_nm": 20, "block_min": 15,
            "cargo_lines": [{"name": "Passagiere", "emoji": "🧳", "kg": 300.0}],
            "loss_kind": "returned", "lost_kg": 0.0,
        }
        ctx = flight_quip_context(flight, {"flights": [flight]})
        assert ctx["verlust"] is None
        assert ctx.get("relay")
        assert "Ladeplatz abgeladen" in ctx["relay"]
        assert "zurückgebracht" not in ctx["relay"]
        assert "umgedreht" not in ctx["relay"]
