# -*- coding: utf-8 -*-
"""Gemeinsame Einstellungen der Testsuite.

**Temporäre Dateien in den Arbeitsspeicher** (25.09.2026). Fast jeder Test legt über
``tmp_path`` eine eigene SQLite-Datenbank an (``init_db``, 1409-mal je Lauf). Auf der Platte
kostet das 368 ms je Aufruf, fast alles Warten aufs Synchronisieren; in ``/dev/shm`` 35 ms.
Die Suite lief damit in 2:59 statt 8:46 -- mit denselben 3409 bestandenen Tests, also ohne
dass ein Test weniger beweist (``tests/test_testumgebung.py``).

``tempfile.tempdir`` ist die Stelle, aus der ``tmp_path`` und ``tempfile.mkdtemp`` ihren
Ursprung nehmen. Ein ausdrücklich gesetztes ``TMPDIR`` hat Vorrang, und wo es kein
``/dev/shm`` gibt (Windows, macOS), bleibt alles, wie es war.
"""
from __future__ import annotations

import os
import tempfile

_RAM = "/dev/shm"

if "TMPDIR" not in os.environ and os.path.isdir(_RAM) and os.access(_RAM, os.W_OK):
    tempfile.tempdir = _RAM


import pytest


@pytest.fixture(autouse=True)
def _kein_stichtag_fuer_die_alte_bruegge(monkeypatch):
    """Ab dem Stichtag (`_BRUEGGE_P2_MSFS_BIS`, 24.10.2026) weist der Server die alte
    MSFS-Brügge mit 426 ab. Viele Tests spielen genau diese alte Brügge -- sie würden an dem Tag
    alle rot, ohne dass sich am Code etwas geändert hätte. Deshalb gilt in den Tests kein
    Stichtag; wer ihn prüfen will, setzt ihn selbst (tests/test_bruegge_protokoll3.py)."""
    import app.main as main
    monkeypatch.setattr(main, "_BRUEGGE_P2_MSFS_BIS", None)
    yield
