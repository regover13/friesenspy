"""Scraper für die FriesenFlieger-Mitgliederliste (board.friesenflieger.de).

Loggt sich ein und extrahiert VATSIM-CIDs aller Mitglieder die eine
stats.vatsim.net-Verlinkung hinterlegt haben.
"""
from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

_CID_PATTERN = re.compile(
    r'<td class="info"><div><a href="https://stats\.vatsim\.net/stats/(\d+)">'
)
_PAGE_SIZE = 25


async def fetch_friesen_cids(
    base_url: str,
    username: str,
    password: str,
) -> list[int]:
    """Loggt sich ins FriesenFlieger-Board ein und gibt alle VATSIM-CIDs zurück.

    Gibt eine leere Liste zurück wenn Login fehlschlägt oder kein Credential
    konfiguriert ist (silent fail — Poller behält dann die bisherige CID-Liste).
    """
    if not username or not password:
        return []

    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            # Login
            resp = await client.post(
                "/ucp.php?mode=login",
                data={
                    "username": username,
                    "password": password,
                    "autologin": "on",
                    "login": "Anmelden",
                },
            )
            if "memberlist.php" not in resp.text and resp.status_code not in (200, 302):
                logger.warning("Board-Login fehlgeschlagen (status %s)", resp.status_code)
                return []

            # Alle Seiten scrapen
            cids: list[int] = []
            start = 0
            while True:
                page = await client.get(f"/memberlist.php?start={start}")
                found = _CID_PATTERN.findall(page.text)
                if not found:
                    break
                for raw in found:
                    cid = int(raw)
                    if cid not in cids:
                        cids.append(cid)
                start += _PAGE_SIZE
                # Abbruch wenn letzte Seite weniger als PAGE_SIZE Einträge
                if len(found) < _PAGE_SIZE:
                    break

            logger.info("Board-Scraper: %d Friesen-CIDs geladen", len(cids))
            return cids

    except Exception:
        logger.exception("Fehler beim Scrapen der Mitgliederliste")
        return []
