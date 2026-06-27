"""Versionierung + nutzerorientierter Changelog für FriesenSpy.

Die Daten liegen als normale Repo-Datei ``app/CHANGELOG.json`` (Single Source of Truth) und
werden hier eingelesen. ``VERSION`` ergibt sich aus dem ersten (= neuesten) Eintrag. Ausgeliefert
wird beides über ``/api/frontend-config`` an das Frontend (Versionsnummer im Header, Changelog-
Banner, Versionsverlauf-Modal).

Release-Workflow: Bei einer signifikanten Änderung in ``app/CHANGELOG.json`` einen neuen Eintrag
**ganz vorne** einfügen (neueste Version zuerst). Dann erscheint bei allen Nutzern, die diese
Version noch nicht gesehen haben, automatisch das Banner. Schema: semantische Version
``MAJOR.MINOR.PATCH`` als ID, ``date`` (ISO) wird überall daneben angezeigt.
"""
from __future__ import annotations

import json
from pathlib import Path

_CHANGELOG_PATH = Path(__file__).resolve().parent / "CHANGELOG.json"


def load_changelog() -> list[dict]:
    """Liest ``app/CHANGELOG.json`` (neueste Version zuerst)."""
    return json.loads(_CHANGELOG_PATH.read_text(encoding="utf-8"))


CHANGELOG: list[dict] = load_changelog()
VERSION: str = CHANGELOG[0]["version"]
