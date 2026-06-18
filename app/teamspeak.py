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


def _parse_clientlist(clients: list[dict], channel_id: int) -> list[dict]:
    """Rohe ts3-clientlist (Liste von Dicts) → [{frs, nick, cid}] für den Zielkanal.

    channel_id == 0 ⇒ ganzer Server. Nur echte Clients (client_type == "0").
    Clients ohne FRS-Tag werden verworfen (Phase 1 ist FRS-zentriert).
    """
    out: list[dict] = []
    for c in clients:
        if c.get("client_type") != "0":
            continue
        try:
            cid = int(c.get("cid", 0))
        except (ValueError, TypeError):
            cid = 0
        if channel_id != 0 and cid != channel_id:
            continue
        nick = c.get("client_nickname", "")
        frs = parse_frs(nick)
        if not frs:
            continue
        out.append({"frs": frs, "nick": nick, "cid": cid})
    return out
