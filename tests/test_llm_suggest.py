"""Tests für die Härtung des Zuladungs-Vorschlags (app/llm.py, suggest_aircraft_payload).

Live-Befund 2026-07-01: die Recherche für 'AS65' (Hubschrauber, nicht in den Typ-Hinweisen)
drehte minutenlang (SDK-Default-Timeout 10 min je Call, bis zu 6 Fortsetzungsrunden) und kam
leer zurück. Härtung: großzügiger, aber ENDLICHER Timeout je Call + Gesamtbudget, plus
kuratierte Hinweise für Hubschrauber und gruppenrelevante Muster.
"""
from __future__ import annotations

import json
import sys
import types
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Block:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _Resp:
    def __init__(self, stop_reason: str, text: str = ""):
        self.stop_reason = stop_reason
        self.content = [_Block(text)] if text else []


def _fake_anthropic(responses: list[_Resp], calls: dict):
    """Fake-anthropic-Modul: zeichnet Konstruktor-/create-Aufrufe auf, liefert responses."""
    mod = types.ModuleType("anthropic")

    class Anthropic:
        def __init__(self, **kwargs):
            calls["init"] = kwargs
            self.messages = self

        def create(self, **kwargs):
            calls["create"] = calls.get("create", 0) + 1
            return responses[min(calls["create"] - 1, len(responses) - 1)]

    mod.Anthropic = Anthropic
    return mod


class TestTypeHints:
    def test_as65_and_helicopters_hinted(self):
        from app.llm import _TYPE_HINTS
        assert "AS65" in _TYPE_HINTS and "Dauphin" in _TYPE_HINTS["AS65"]
        assert "R44" in _TYPE_HINTS
        assert "EC35" in _TYPE_HINTS

    def test_friesen_islander_hinted(self):
        from app.llm import _TYPE_HINTS
        assert "BN2P" in _TYPE_HINTS and "Islander" in _TYPE_HINTS["BN2P"]


class TestSuggestHardening:
    SPEC = json.dumps({"make_model": "Test", "mtow_kg": 1000.0,
                       "empty_kg": 600.0, "fuel_full_kg": 100.0})

    def test_client_gets_finite_timeout(self):
        from app import llm
        calls: dict = {}
        fake = _fake_anthropic([_Resp("end_turn", self.SPEC)], calls)
        with patch.dict(sys.modules, {"anthropic": fake}):
            result = llm.suggest_aircraft_payload("C172")
        assert result is not None and result["payload_kg"] == 215.0  # 1000-600-100-85
        assert calls["init"].get("timeout") == llm._SUGGEST_REQUEST_TIMEOUT_S
        assert llm._SUGGEST_REQUEST_TIMEOUT_S <= 300  # endlich, nicht SDK-Default (10 min)

    def test_pause_loop_respects_total_budget(self, monkeypatch):
        """Erschöpftes Gesamtbudget beendet die Fortsetzungsschleife — kein Endlos-Drehen."""
        from app import llm
        calls: dict = {}
        fake = _fake_anthropic([_Resp("pause_turn")], calls)
        monkeypatch.setattr(llm, "_SUGGEST_TOTAL_BUDGET_S", 0.0)
        with patch.dict(sys.modules, {"anthropic": fake}):
            result = llm.suggest_aircraft_payload("AS65")
        assert result is None          # sauberes „kein Ergebnis", kein Hänger/Crash
        assert calls["create"] == 1    # nach Budget-Ende keine weitere Runde
