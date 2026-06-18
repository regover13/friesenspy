"""Empfänger-Auswahl für TS-Login-Benachrichtigungen (reine Logik, Phase 1)."""
from __future__ import annotations


def recipients_for(
    consent: dict | None,
    opted_in_subs: list[dict],
    joining_frs: str,
) -> list[dict]:
    """Welche opt-in-Subscriptions sollen über den Beitritt von joining_frs informiert werden.

    consent: Eintrag aus ts_consent (mit 'visibility' und 'allowlist'-Liste) oder None.
    Default ohne Eintrag = 'everyone'. Subs mit ts_self_frs == joining_frs werden immer
    übersprungen (kein Selbst-Ping).
    """
    visibility = (consent or {}).get("visibility") or "everyone"
    if visibility == "nobody":
        return []
    allowlist = set((consent or {}).get("allowlist") or [])

    out: list[dict] = []
    for sub in opted_in_subs:
        self_frs = sub.get("ts_self_frs")
        if self_frs and self_frs == joining_frs:
            continue
        if visibility == "allowlist" and self_frs not in allowlist:
            continue
        out.append(sub)
    return out
