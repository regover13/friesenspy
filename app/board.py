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
_TOKEN_PATTERN = re.compile(r'<input type="hidden" name="form_token" value="([^"]+)"')
_CREATION_PATTERN = re.compile(r'<input type="hidden" name="creation_time" value="([^"]+)"')
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
            # Schritt 1: Login-Seite laden um CSRF-Token zu erhalten
            login_page = await client.get("/ucp.php?mode=login")
            form_token = _TOKEN_PATTERN.search(login_page.text)
            creation_time = _CREATION_PATTERN.search(login_page.text)

            # Schritt 2: Login mit CSRF-Token
            resp = await client.post(
                "/ucp.php?mode=login",
                data={
                    "username": username,
                    "password": password,
                    "autologin": "on",
                    "viewonline": "1",
                    "redirect": "index.php",
                    "login": "Anmelden",
                    "form_token": form_token.group(1) if form_token else "",
                    "creation_time": creation_time.group(1) if creation_time else "",
                },
            )

            # phpBB setzt phpbb3_*_u auf die echte User-ID (>1) bei Erfolg
            uid = next(
                (v for k, v in client.cookies.items() if k.endswith("_u")), "1"
            )
            if uid == "1":
                logger.warning("Board-Login fehlgeschlagen (UID=1/Gast)")
                return []

            logger.debug("Board-Login OK (UID=%s)", uid)

            # Schritt 3: Alle Seiten scrapen
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
                if len(found) < _PAGE_SIZE:
                    break

            logger.info("Board-Scraper: %d Friesen-CIDs geladen", len(cids))
            return cids

    except Exception:
        logger.exception("Fehler beim Scrapen der Mitgliederliste")
        return []
