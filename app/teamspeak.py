"""TeamSpeak-ServerQuery-Client für FriesenSpy (Phase 1).

Kurzlebige ServerQuery-Verbindung pro Poll (kein dauerhafter Event-Thread, kein
TS-Client). Liest die Clients im Zielkanal und parst FRS-Nummern aus den Nicknames.
"""
from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

_FRS_RE = re.compile(r"FRS(\d+[A-Z]?)", re.IGNORECASE)


def parse_frs(nick: str) -> str | None:
    """FRS-Nummer aus einem TS-Nickname extrahieren, oder None.

    Portiert aus TSBot/bot/ts_query.py:_parse_nickname. FRS-Nummer kann an beliebiger
    Stelle stehen (vor/nach Name, diverse Trennzeichen, Klammer-Suffix). Rückgabe in
    Großbuchstaben, z. B. "FRS135" / "FRS135A".
    """
    m = _FRS_RE.search(nick or "")
    return m.group(0).upper() if m else None
