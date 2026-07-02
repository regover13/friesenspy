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
    """Fake-anthropic-Modul: zeichnet Konstruktor-/stream-Aufrufe auf, liefert responses."""
    mod = types.ModuleType("anthropic")

    class _Stream:
        def __init__(self, resp):
            self._resp = resp

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return self._resp

    class Anthropic:
        def __init__(self, **kwargs):
            calls["init"] = kwargs
            self.messages = self

        def stream(self, **kwargs):
            calls["stream_kwargs"] = kwargs
            calls["create"] = calls.get("create", 0) + 1
            return _Stream(responses[min(calls["create"] - 1, len(responses) - 1)])

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

    def test_wilga_and_ga_classics_hinted(self):
        """Live-Befund 2026-07-02: 'PZ04' (PZL-104 Wilga) wurde nicht gefunden — ohne
        Klartext-Hinweis scheitert die Recherche an der Designator-Identifikation."""
        from app.llm import _TYPE_HINTS
        assert "PZ04" in _TYPE_HINTS and "Wilga" in _TYPE_HINTS["PZ04"]
        for code in ("DO27", "C185", "PA32", "AN2", "J3"):
            assert code in _TYPE_HINTS, code

    def test_msfs_fleet_and_more_helis_hinted(self):
        """Nachforderung 2026-07-02: MSFS-Standardflotte + gängige Addons (Huey, Lama, H160,
        Vision Jet, King Air, C310/C414, DC-3, Ju 52 …) als Klartext-Hinweise."""
        from app.llm import _TYPE_HINTS
        for code in ("UH1", "LAMA", "H160", "B407", "R66",
                     "SF50", "BE20", "B350", "C310", "C414", "DC3", "JU52",
                     "DHC2", "KODI", "SF25",
                     # aus der msfsaddons-Liste des Auftraggebers ergänzt
                     "GA8", "HUSK", "DHC3", "C337", "PTS2", "B105", "ALO3", "ST75"):
            assert code in _TYPE_HINTS, code
        assert "Huey" in _TYPE_HINTS["UH1"]


class TestSuggestHardening:
    SPEC = json.dumps({"make_model": "Test", "mtow_kg": 1000.0,
                       "empty_kg": 600.0, "fuel_full_kg": 100.0})

    def test_client_gets_finite_timeout(self):
        from app import llm
        calls: dict = {}
        fake = _fake_anthropic([_Resp("end_turn", self.SPEC)], calls)
        with patch.dict(sys.modules, {"anthropic": fake}):
            result = llm.suggest_aircraft_payload("C172")
        assert result is not None and result["payload_kg"] == 265.0  # 1000-600-50-85
        assert calls["init"].get("timeout") == llm._SUGGEST_REQUEST_TIMEOUT_S
        assert llm._SUGGEST_REQUEST_TIMEOUT_S <= 300  # endlich, nicht SDK-Default (10 min)

    def test_uses_basic_web_search_tool(self):
        """Live-Befund 2026-07-02: das neue web_search_20260209 (Dynamic Filtering) lässt das
        Modell Suchergebnisse per code_execution nachbearbeiten — bei obskuren Typen (PZ04)
        drehte EIN Request >9 min in Code-Runden à 30–95 s (Event-Trace) und riss 185
        Web-Suchen/6,4M Tokens in zwei Tagen (~14 $). Das Basis-Tool web_search_20250305
        liefert dasselbe Ergebnis in 16 s für ~0,07 $."""
        from app.llm import _WEB_SEARCH_TOOL
        assert _WEB_SEARCH_TOOL["type"] == "web_search_20250305"
        assert _WEB_SEARCH_TOOL.get("max_uses", 99) <= 3

    def test_streams_without_client_retries(self):
        """Nicht-Streaming-Calls >120 s brachen im Client-Timeout ab; das SDK wiederholte
        still 2× (Default) — jeder abgebrochene Versuch wurde serverseitig zu Ende gerechnet
        und berechnet (Dreifach-Billing). Streaming hält die Verbindung; max_retries=0."""
        from app import llm
        calls: dict = {}
        fake = _fake_anthropic([_Resp("end_turn", self.SPEC)], calls)
        with patch.dict(sys.modules, {"anthropic": fake}):
            result = llm.suggest_aircraft_payload("C172")
        assert result is not None
        assert calls["init"].get("max_retries") == 0
        assert "stream_kwargs" in calls  # Streaming-Pfad, nicht messages.create

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
