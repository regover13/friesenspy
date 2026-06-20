"""TeamSpeak-ServerQuery-Client für FriesenSpy (Phase 1).

Kurzlebige ServerQuery-Verbindung pro Poll (kein dauerhafter Event-Thread, kein
TS-Client). Liest die Clients im Zielkanal und parst FRS-Nummern aus den Nicknames.
"""
from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

# Einziges erlaubtes Suffix ist das optionale "N" (z. B. FRS13N) — andere Buchstaben
# gibt es nicht und werden NICHT als Teil des Callsigns gewertet (FRS135A → FRS135).
_FRS_RE = re.compile(r"FRS(\d+N?)", re.IGNORECASE)


def parse_frs(nick: str) -> str | None:
    """FRS-Nummer aus einem TS-Nickname extrahieren, oder None.

    Portiert aus TSBot/bot/ts_query.py:_parse_nickname. FRS-Nummer kann an beliebiger
    Stelle stehen (vor/nach Name, diverse Trennzeichen, Klammer-Suffix). Rückgabe in
    Großbuchstaben, z. B. "FRS135" / "FRS13N". Einziges erlaubtes Suffix ist "N".
    """
    m = _FRS_RE.search(nick or "")
    return m.group(0).upper() if m else None


def parse_channel_ids(raw: str) -> frozenset[int]:
    """Komma-separierte Kanal-IDs (aus Config) → frozenset[int].

    Leerzeichen und leere/ungültige Einträge werden ignoriert. Leerer String → leeres Set.
    """
    out: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return frozenset(out)


def _parse_clientlist(
    clients: list[dict],
    channel_id: int,
    exclude_channel_ids: frozenset[int] = frozenset(),
) -> list[dict]:
    """Rohe ts3-clientlist (Liste von Dicts) → [{frs, nick, cid}] für den Zielkanal.

    channel_id == 0 ⇒ ganzer Server. Nur echte Clients (client_type == "0").
    Clients ohne FRS-Tag werden verworfen (Phase 1 ist FRS-zentriert).
    Clients in einem Kanal aus `exclude_channel_ids` werden ignoriert (z. B. Verwaltung).
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
        if cid in exclude_channel_ids:
            continue
        nick = c.get("client_nickname", "")
        frs = parse_frs(nick)
        if not frs:
            continue
        out.append({"frs": frs, "nick": nick, "cid": cid})
    return out


def _fetch_clients_sync(
    host: str, port: int, user: str, password: str,
    server_id: int, channel_id: int,
    exclude_channel_ids: frozenset[int] = frozenset(),
) -> list[dict]:
    """Blockierend: kurzlebige ServerQuery-Verbindung, clientlist holen, filtern.

    Lazy import von ts3, damit Modulimport und parse_frs ohne ts3 funktionieren.
    """
    import ts3  # type: ignore

    conn = ts3.query.TS3Connection(host, port)
    try:
        conn.login(client_login_name=user, client_login_password=password)
        conn.use(sid=server_id)
        resp = conn.clientlist()
        return _parse_clientlist(list(resp.parsed), channel_id, exclude_channel_ids)
    finally:
        try:
            conn.close()
        except Exception:
            pass


async def fetch_channel_clients(
    *, host: str, port: int, user: str, password: str,
    server_id: int, channel_id: int,
    exclude_channel_ids: frozenset[int] = frozenset(),
) -> list[dict] | None:
    """FRS-Clients im Zielkanal als [{frs, nick, cid}].

    Gibt None bei Fehler zurück (kein Crash), damit der Caller zwischen einem
    echten Fehler (None) und einem echt leeren Kanal ([]) unterscheiden kann.
    Clients in `exclude_channel_ids` (z. B. Verwaltungs-Kanäle) werden ignoriert.
    """
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(
            None,
            lambda: _fetch_clients_sync(
                host, port, user, password, server_id, channel_id, exclude_channel_ids
            ),
        )
    except Exception as exc:
        logger.warning("ServerQuery-Abruf fehlgeschlagen: %s", type(exc).__name__)
        return None
