"""Tests für app/ts_notify.py:recipients_for."""
from __future__ import annotations

from app.ts_notify import recipients_for

SUBS = [
    {"endpoint": "e1", "ts_self_frs": "FRS1"},
    {"endpoint": "e2", "ts_self_frs": "FRS2"},
    {"endpoint": "e3", "ts_self_frs": None},
]


def _eps(subs):
    return [s["endpoint"] for s in subs]


def test_no_consent_means_everyone():
    out = recipients_for(None, SUBS, joining_frs="FRS9")
    assert _eps(out) == ["e1", "e2", "e3"]


def test_everyone_explicit():
    out = recipients_for({"visibility": "everyone", "allowlist": []}, SUBS, "FRS9")
    assert _eps(out) == ["e1", "e2", "e3"]


def test_nobody():
    out = recipients_for({"visibility": "nobody", "allowlist": []}, SUBS, "FRS9")
    assert out == []


def test_allowlist_only_listed():
    consent = {"visibility": "allowlist", "allowlist": ["FRS2"]}
    out = recipients_for(consent, SUBS, "FRS9")
    assert _eps(out) == ["e2"]


def test_self_ping_skipped():
    # FRS1 betritt den Kanal → eigenes Gerät (ts_self_frs == FRS1) bekommt nichts
    out = recipients_for(None, SUBS, joining_frs="FRS1")
    assert _eps(out) == ["e2", "e3"]
