"""Ein vorübergehender API-Fehler ist kein "keine Daten" (AP32-Fall, 2026-07-30).

Gemessen: suggest_aircraft_payload('AP32') scheiterte an overloaded_error und gab None
zurück — nicht unterscheidbar von "Muster nicht auffindbar". Der Aufrufer merkte sich den
Code daraufhin dauerhaft als erledigt.
"""
from __future__ import annotations

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


# Die anthropic-Ausnahmeklassen auf Modulebene nachgebaut, damit Tests eine Ausnahme
# konstruieren können, BEVOR das Fake-Modul gesetzt wird. (Eine Factory, die die Klassen
# selbst erst anlegt, führt zum Henne-Ei-Problem: man braucht die Klasse für das Argument,
# das man der Factory übergeben will.)
class _APIError(Exception):
    pass


class _APIStatusError(_APIError):
    def __init__(self, message="", status_code=500):
        super().__init__(message)
        self.status_code = status_code


class _APIConnectionError(_APIError):
    pass


class _APITimeoutError(_APIConnectionError):
    pass


class _RateLimitError(_APIStatusError):
    pass


class _InternalServerError(_APIStatusError):
    pass


def _fake_anthropic(exc: BaseException):
    """Fake-anthropic-Modul, dessen ``stream()`` beim Betreten ``exc`` wirft."""
    mod = types.ModuleType("anthropic")

    class _Messages:
        def stream(self, **kwargs):
            raise exc

    class _Client:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    mod.APIError = _APIError
    mod.APIStatusError = _APIStatusError
    mod.APIConnectionError = _APIConnectionError
    mod.APITimeoutError = _APITimeoutError
    mod.RateLimitError = _RateLimitError
    mod.InternalServerError = _InternalServerError
    mod.Anthropic = _Client
    return mod


def _run(exc: BaseException):
    """suggest_aircraft_payload gegen ein Fake-anthropic, das ``exc`` wirft."""
    from app import llm
    with patch.dict("sys.modules", {"anthropic": _fake_anthropic(exc)}):
        return llm.suggest_aircraft_payload("AP32")


def test_overloaded_raises_transient():
    """529 Overloaded — genau der gemessene AP32-Fall."""
    from app import llm
    with pytest.raises(llm.TransientResearchError):
        _run(_APIStatusError("Overloaded", status_code=529))


def test_timeout_raises_transient():
    from app import llm
    with pytest.raises(llm.TransientResearchError):
        _run(_APITimeoutError("timeout"))


def test_rate_limit_raises_transient():
    from app import llm
    with pytest.raises(llm.TransientResearchError):
        _run(_RateLimitError("slow down", status_code=429))


def test_forbidden_raises_transient():
    """403: Wikimedia blockt das Netz dieses Servers nicht deterministisch — Plan B nutzt
    denselben Klassifikator, deshalb gehört 403 zu den vorübergehenden Fehlern."""
    from app import llm
    with pytest.raises(llm.TransientResearchError):
        _run(_APIStatusError("forbidden", status_code=403))


def test_value_error_stays_none():
    """Ein Programmier-/Datenfehler ist NICHT transient — Vertrag bleibt None."""
    assert _run(ValueError("kaputtes JSON")) is None


def test_client_error_400_stays_none():
    """4xx außer 403/408/429 ist endgültig: erneutes Fragen ändert nichts."""
    assert _run(_APIStatusError("bad request", status_code=400)) is None


def test_is_transient_error_classifies_plain_status_codes():
    """Plan B braucht den Klassifikator für HTTP-Fehler ohne anthropic-Typen."""
    from app import llm

    class _Http(Exception):
        def __init__(self, status_code):
            super().__init__(str(status_code))
            self.status_code = status_code

    assert llm.is_transient_error(_Http(403)) is True   # Wikimedia-Contabo-Block
    assert llm.is_transient_error(_Http(429)) is True
    assert llm.is_transient_error(_Http(503)) is True
    assert llm.is_transient_error(_Http(404)) is False
    assert llm.is_transient_error(ValueError("x")) is False
