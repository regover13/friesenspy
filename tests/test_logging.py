"""Tests für die Logging-Konfiguration (app.main.configure_logging).

Unter uvicorn hat der Root-Logger sonst keinen Handler → App-INFO-Logs
(z. B. "PrefilePush … sent OK") werden verschluckt, nur WARNING+ erscheint.
"""
from __future__ import annotations

import logging


def test_configure_logging_respects_level():
    from app.main import configure_logging

    root = logging.getLogger()
    old_level = root.level
    old_handlers = root.handlers[:]
    try:
        configure_logging("WARNING")
        assert root.level == logging.WARNING
        configure_logging("DEBUG")
        assert root.level == logging.DEBUG
        # ungültiger Wert → Fallback INFO, kein Crash
        configure_logging("nonsense")
        assert root.level == logging.INFO
    finally:
        root.setLevel(old_level)
        root.handlers[:] = old_handlers


def test_configure_logging_adds_root_handler():
    """Nach configure_logging emittiert der Root-Logger (mind. ein Handler)."""
    from app.main import configure_logging

    root = logging.getLogger()
    old_level = root.level
    old_handlers = root.handlers[:]
    try:
        configure_logging("INFO")
        assert root.handlers, "Root-Logger sollte nach configure_logging einen Handler haben"
    finally:
        root.setLevel(old_level)
        root.handlers[:] = old_handlers
