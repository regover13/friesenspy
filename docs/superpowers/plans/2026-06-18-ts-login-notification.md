# TS-Login-Benachrichtigung (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FriesenSpy pollt den TeamSpeak-ServerQuery (Port 10011) und schickt eine WebPush-Benachrichtigung, wenn eine FRS-Nummer einen konfigurierten Kanal betritt — gesteuert über eine lokale, subjekt-kontrollierte Einwilligungs-Tabelle.

**Architecture:** Ein neuer APScheduler-Job im bestehenden `VatsimPoller` baut pro Intervall eine kurzlebige ServerQuery-Verbindung auf (`app/teamspeak.py`, im Executor), diffed die FRS-Menge im Zielkanal gegen den letzten Stand und löst pro Neu-Beitritt einen WebPush aus. Empfänger-Auswahl ist reine Logik (`app/ts_notify.py`) auf Basis einer `ts_consent`-Tabelle und der opt-in-Subscriptions. Der WebPush-Versand der VATSIM-Seite wird in eine generische Funktion `send_web_push` ausgelagert, die Subscription-Liste + Payload entgegennimmt.

**Tech Stack:** Python 3.11, FastAPI, APScheduler, SQLite (WAL), `ts3` (PyPI, lazy import), `pywebpush`/VAPID, pytest.

---

## File Structure

| Datei | Verantwortung |
|-------|---------------|
| `app/teamspeak.py` (neu) | ServerQuery-Client: `parse_frs`, `_parse_clientlist` (pure), `_fetch_clients_sync` (ts3-IO), `async fetch_channel_clients` (Executor-Wrapper) |
| `app/ts_notify.py` (neu) | Reine Zustell-Logik: `recipients_for(consent, opted_in_subs, joining_frs)` |
| `app/database.py` (erweitern) | `ts_consent`-Tabelle + Push-Migrationen (`notify_ts`, `ts_self_frs`) + Helper |
| `app/config.py` (erweitern) | TS-Settings mit Defaults |
| `app/poller.py` (erweitern) | `send_web_push` generalisieren, neuer Job `_poll_teamspeak` |
| `app/main.py` (erweitern) | `/api/push/subscribe` nimmt `notify_ts` + `ts_self_frs` entgegen |
| `manage_ts_consent.py` (neu) | Admin-CLI zum Seeden/Anzeigen der `ts_consent`-Tabelle (kein Web-UI) |
| `requirements.txt` (erweitern) | `ts3` |
| `tests/test_teamspeak.py` (neu) | `parse_frs`, `_parse_clientlist`-Filter |
| `tests/test_ts_notify.py` (neu) | `recipients_for` |
| `tests/test_database.py` (ergänzen) | `ts_consent` CRUD + Migration idempotent + `get_ts_push_subscriptions` |
| `tests/test_poller.py` (ergänzen) | Poll-Diff, Baseline, Debounce, `send_web_push` |
| `tests/test_manage_ts_consent.py` (neu) | CLI `main()`: set/get/list/delete |
| `README.md`, `docs/api.md`, `docs/architecture.md` | Doku (Memory-Regel: bei jeder Codeänderung mitpflegen) |

**Default-Einwilligung:** `everyone` (kein `ts_consent`-Eintrag ⇒ benachrichtigen) — bestätigte Entscheidung aus der Spec. In der Spec als „offener Punkt für die Freigabe" markiert; falls der User vor der Umsetzung Privacy-by-default (`nobody`) will, nur die Default-Konstante in `recipients_for` und der DDL-Default umstellen.

---

## Task 1: FRS-Parser in `app/teamspeak.py`

**Files:**
- Create: `app/teamspeak.py`
- Test: `tests/test_teamspeak.py`

Portiert die Parser-Logik aus `TSBot/bot/ts_query.py:_parse_nickname` (`FRS(\d+[A-Z]?)`, Trennzeichen, `(MSFS2024)`-Suffix) als freie Funktion `parse_frs(nick) -> str | None`, die nur die FRS-Nummer zurückgibt (Großbuchstaben), oder `None`.

- [ ] **Step 1: Failing test schreiben**

`tests/test_teamspeak.py`:
```python
"""Tests für app/teamspeak.py."""
from __future__ import annotations

import pytest

from app.teamspeak import parse_frs


class TestParseFrs:
    @pytest.mark.parametrize("nick,expected", [
        ("Vorname Nachname/FRS22", "FRS22"),
        ("Klaus Löfflad | FRS22", "FRS22"),
        ("FRS22/Vorname Nachname", "FRS22"),
        ("Marco WeißFRS135(MSFS2024)", "FRS135"),
        ("frs7 lowercase", "FRS7"),
        ("FRS135A", "FRS135A"),
        ("Nur ein Name", None),
        ("", None),
    ])
    def test_parse_frs(self, nick, expected):
        assert parse_frs(nick) == expected
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/test_teamspeak.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.teamspeak'`

- [ ] **Step 3: Minimal-Implementierung**

`app/teamspeak.py`:
```python
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
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `pytest tests/test_teamspeak.py -v`
Expected: PASS (8 Fälle)

- [ ] **Step 5: Commit**

```bash
git add app/teamspeak.py tests/test_teamspeak.py
git commit -m "feat(ts): parse_frs — FRS-Nummer aus TS-Nickname"
```

---

## Task 2: Kanal-Filter `_parse_clientlist` in `app/teamspeak.py`

**Files:**
- Modify: `app/teamspeak.py`
- Test: `tests/test_teamspeak.py`

Pure Funktion, die die rohe ts3-`clientlist().parsed`-Struktur (Liste von Dicts mit String-Werten) auf den Zielkanal filtert und `{frs, nick, cid}` je Client mit FRS-Tag liefert. `channel_id == 0` ⇒ ganzer Server. Nur `client_type == "0"` (echte Clients, keine Query). Clients ohne FRS werden verworfen (Phase 1 ist FRS-zentriert).

- [ ] **Step 1: Failing test schreiben**

In `tests/test_teamspeak.py` ergänzen:
```python
from app.teamspeak import _parse_clientlist


class TestParseClientlist:
    RAW = [
        {"clid": "1", "cid": "5", "client_type": "0", "client_nickname": "Max/FRS1"},
        {"clid": "2", "cid": "7", "client_type": "0", "client_nickname": "Anna FRS2"},
        {"clid": "3", "cid": "5", "client_type": "0", "client_nickname": "Gast ohne Tag"},
        {"clid": "4", "cid": "5", "client_type": "1", "client_nickname": "serveradmin"},
    ]

    def test_filter_target_channel(self):
        out = _parse_clientlist(self.RAW, channel_id=5)
        assert out == [{"frs": "FRS1", "nick": "Max/FRS1", "cid": 5}]

    def test_other_channel_excluded(self):
        out = _parse_clientlist(self.RAW, channel_id=7)
        assert [c["frs"] for c in out] == ["FRS2"]

    def test_whole_server_when_zero(self):
        out = _parse_clientlist(self.RAW, channel_id=0)
        assert {c["frs"] for c in out} == {"FRS1", "FRS2"}

    def test_query_clients_and_untagged_excluded(self):
        out = _parse_clientlist(self.RAW, channel_id=0)
        assert all(c["frs"] for c in out)
        assert "serveradmin" not in [c["nick"] for c in out]
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/test_teamspeak.py::TestParseClientlist -v`
Expected: FAIL — `ImportError: cannot import name '_parse_clientlist'`

- [ ] **Step 3: Implementierung ergänzen**

In `app/teamspeak.py` nach `parse_frs` einfügen:
```python
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
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `pytest tests/test_teamspeak.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/teamspeak.py tests/test_teamspeak.py
git commit -m "feat(ts): _parse_clientlist — Kanal-Filter auf FRS-Clients"
```

---

## Task 3: ServerQuery-IO `_fetch_clients_sync` + `fetch_channel_clients`

**Files:**
- Modify: `app/teamspeak.py`
- Test: `tests/test_teamspeak.py`

`_fetch_clients_sync` macht die blockierende ts3-Arbeit (connect → login → use sid → clientlist → close), lazy-importiert `ts3`. `fetch_channel_clients` wrappt es in `loop.run_in_executor` und liefert bei jedem Fehler `[]` (kein Crash). Getestet wird `fetch_channel_clients` mit gemocktem `_fetch_clients_sync` (kein `ts3` im Dev-Env nötig).

- [ ] **Step 1: Failing test schreiben**

In `tests/test_teamspeak.py` ergänzen:
```python
from unittest.mock import patch
from app.teamspeak import fetch_channel_clients


class TestFetchChannelClients:
    @pytest.mark.asyncio
    async def test_returns_sync_result(self):
        fake = [{"frs": "FRS1", "nick": "Max/FRS1", "cid": 5}]
        with patch("app.teamspeak._fetch_clients_sync", return_value=fake):
            out = await fetch_channel_clients(
                host="h", port=10011, user="u", password="p",
                server_id=1, channel_id=5,
            )
        assert out == fake

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self):
        with patch("app.teamspeak._fetch_clients_sync", side_effect=OSError("refused")):
            out = await fetch_channel_clients(
                host="h", port=10011, user="u", password="p",
                server_id=1, channel_id=0,
            )
        assert out == []
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/test_teamspeak.py::TestFetchChannelClients -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_channel_clients'`

- [ ] **Step 3: Implementierung ergänzen**

In `app/teamspeak.py` ans Ende:
```python
def _fetch_clients_sync(
    host: str, port: int, user: str, password: str,
    server_id: int, channel_id: int,
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
        return _parse_clientlist(list(resp.parsed), channel_id)
    finally:
        try:
            conn.close()
        except Exception:
            pass


async def fetch_channel_clients(
    *, host: str, port: int, user: str, password: str,
    server_id: int, channel_id: int,
) -> list[dict]:
    """FRS-Clients im Zielkanal als [{frs, nick, cid}]. Bei Fehler [] (kein Crash)."""
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(
            None,
            lambda: _fetch_clients_sync(host, port, user, password, server_id, channel_id),
        )
    except Exception as exc:
        logger.warning("ServerQuery-Abruf fehlgeschlagen: %s", type(exc).__name__)
        return []
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `pytest tests/test_teamspeak.py -v`
Expected: PASS

- [ ] **Step 5: `ts3` zu requirements.txt hinzufügen**

In `requirements.txt` nach `recurring-ical-events>=3.0` anfügen:
```
ts3>=2.0
```

- [ ] **Step 6: Commit**

```bash
git add app/teamspeak.py tests/test_teamspeak.py requirements.txt
git commit -m "feat(ts): fetch_channel_clients — kurzlebige ServerQuery-Verbindung im Executor"
```

---

## Task 4: `ts_consent`-Tabelle + Push-Migrationen + DB-Helper

**Files:**
- Modify: `app/database.py`
- Test: `tests/test_database.py`

`ts_consent`-Tabelle in `_DDL` (damit `_make_conn`-Tests sie sehen). Push-Spalten `notify_ts`, `ts_self_frs` als Migration (analog `notify_prefiles`). Helper: `get_ts_consent`, `upsert_ts_consent`, `get_ts_push_subscriptions`. `upsert_push_subscription` um optionale `notify_ts`/`ts_self_frs`-Parameter erweitern (rückwärtskompatibel).

- [ ] **Step 1: Failing test schreiben**

In `tests/test_database.py` ans Ende ergänzen:
```python
# ---------------------------------------------------------------------------
# ts_consent + TS-Push-Subscriptions
# ---------------------------------------------------------------------------

class TestTsConsent:
    def test_get_missing_returns_none(self):
        from app.database import get_ts_consent
        conn = _make_conn()
        assert get_ts_consent(conn, "FRS1") is None

    def test_upsert_and_get(self):
        from app.database import get_ts_consent, upsert_ts_consent
        conn = _make_conn()
        upsert_ts_consent(conn, "FRS1", "allowlist", ["FRS2", "FRS3"])
        conn.commit()
        row = get_ts_consent(conn, "FRS1")
        assert row["frs"] == "FRS1"
        assert row["visibility"] == "allowlist"
        assert row["allowlist"] == ["FRS2", "FRS3"]

    def test_upsert_overwrites(self):
        from app.database import get_ts_consent, upsert_ts_consent
        conn = _make_conn()
        upsert_ts_consent(conn, "FRS1", "everyone", None)
        upsert_ts_consent(conn, "FRS1", "nobody", None)
        conn.commit()
        assert get_ts_consent(conn, "FRS1")["visibility"] == "nobody"


class TestTsPushSubscriptions:
    def test_only_opted_in(self, tmp_path):
        from app.database import (
            init_db, get_connection, upsert_push_subscription,
            get_ts_push_subscriptions,
        )
        db = str(tmp_path / "t.db")
        init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_ts=True, ts_self_frs="FRS9")
        upsert_push_subscription(conn, "e2", "p2", "a2", notify_ts=False)
        conn.commit()
        subs = get_ts_push_subscriptions(conn)
        assert [s["endpoint"] for s in subs] == ["e1"]
        assert subs[0]["ts_self_frs"] == "FRS9"
        conn.close()

    def test_migrations_idempotent(self, tmp_path):
        from app.database import init_db
        db = str(tmp_path / "t.db")
        init_db(db)
        init_db(db)  # zweiter Lauf darf nicht werfen
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/test_database.py::TestTsConsent tests/test_database.py::TestTsPushSubscriptions -v`
Expected: FAIL — `ImportError: cannot import name 'get_ts_consent'`

- [ ] **Step 3: DDL + Migrationen ergänzen**

In `app/database.py`, am Ende von `_DDL` (vor dem schließenden `"""`, nach der `push_subscriptions`-Tabelle) einfügen:
```python
CREATE TABLE IF NOT EXISTS ts_consent (
    frs        TEXT PRIMARY KEY,
    visibility TEXT DEFAULT 'everyone',
    allowlist  TEXT,
    updated_at TEXT
);
```

`_PUSH_MIGRATIONS` erweitern:
```python
_PUSH_MIGRATIONS = [
    "ALTER TABLE push_subscriptions ADD COLUMN notify_prefiles INTEGER DEFAULT 0",
    "ALTER TABLE push_subscriptions ADD COLUMN notify_ts INTEGER DEFAULT 0",
    "ALTER TABLE push_subscriptions ADD COLUMN ts_self_frs TEXT",
]
```

- [ ] **Step 4: `upsert_push_subscription` erweitern**

Ersetze die Signatur + INSERT in `app/database.py`:
```python
def upsert_push_subscription(
    conn: sqlite3.Connection,
    endpoint: str,
    p256dh: str,
    auth: str,
    pilot_filter: list[int] | None = None,
    notify_prefiles: bool = True,
    notify_ts: bool = False,
    ts_self_frs: str | None = None,
) -> None:
    """Browser-Push-Subscription speichern oder aktualisieren."""
    conn.execute(
        """INSERT INTO push_subscriptions
               (endpoint, p256dh, auth, pilot_filter, notify_prefiles,
                notify_ts, ts_self_frs, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(endpoint) DO UPDATE SET
               p256dh=excluded.p256dh,
               auth=excluded.auth,
               pilot_filter=excluded.pilot_filter,
               notify_prefiles=excluded.notify_prefiles,
               notify_ts=excluded.notify_ts,
               ts_self_frs=excluded.ts_self_frs""",
        (
            endpoint, p256dh, auth,
            json.dumps(pilot_filter) if pilot_filter is not None else None,
            1 if notify_prefiles else 0,
            1 if notify_ts else 0,
            ts_self_frs,
            _now_utc(),
        ),
    )
```

- [ ] **Step 5: Consent-Helper ergänzen**

In `app/database.py` im Push-Abschnitt (nach `get_push_subscriptions_for_prefile`) einfügen:
```python
def get_ts_consent(conn: sqlite3.Connection, frs: str) -> dict | None:
    """Einwilligungs-Eintrag für eine FRS-Nummer, oder None (= Default 'everyone').

    allowlist wird aus JSON zu einer Liste geparst (oder []).
    """
    row = conn.execute(
        "SELECT frs, visibility, allowlist, updated_at FROM ts_consent WHERE frs = ?",
        (frs,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["allowlist"] = json.loads(d["allowlist"]) if d["allowlist"] else []
    except (json.JSONDecodeError, TypeError):
        d["allowlist"] = []
    return d


def upsert_ts_consent(
    conn: sqlite3.Connection,
    frs: str,
    visibility: str,
    allowlist: list[str] | None = None,
) -> None:
    """Einwilligung pro FRS setzen. visibility ∈ {'everyone','nobody','allowlist'}."""
    conn.execute(
        """INSERT INTO ts_consent (frs, visibility, allowlist, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(frs) DO UPDATE SET
               visibility=excluded.visibility,
               allowlist=excluded.allowlist,
               updated_at=excluded.updated_at""",
        (
            frs, visibility,
            json.dumps(allowlist) if allowlist is not None else None,
            _now_utc(),
        ),
    )


def get_ts_push_subscriptions(conn: sqlite3.Connection) -> list[dict]:
    """Alle Subscriptions mit notify_ts = 1 (TS-Benachrichtigungen erwünscht)."""
    rows = conn.execute(
        "SELECT endpoint, p256dh, auth, ts_self_frs "
        "FROM push_subscriptions WHERE notify_ts = 1"
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 6: Tests ausführen, Erfolg bestätigen**

Run: `pytest tests/test_database.py -v`
Expected: PASS (neue + bestehende Tests grün)

- [ ] **Step 7: Commit**

```bash
git add app/database.py tests/test_database.py
git commit -m "feat(ts): ts_consent-Tabelle + Push-Opt-in-Spalten + DB-Helper"
```

---

## Task 5: Empfänger-Logik `app/ts_notify.py`

**Files:**
- Create: `app/ts_notify.py`
- Test: `tests/test_ts_notify.py`

Reine Funktion `recipients_for(consent, opted_in_subs, joining_frs)`. Regeln: `nobody` → `[]`; `everyone`/kein Eintrag → alle opted-in Subs; `allowlist` → nur Subs mit `ts_self_frs ∈ allowlist`. In allen Fällen Subs mit `ts_self_frs == joining_frs` überspringen (kein Selbst-Ping).

- [ ] **Step 1: Failing test schreiben**

`tests/test_ts_notify.py`:
```python
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
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/test_ts_notify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ts_notify'`

- [ ] **Step 3: Implementierung**

`app/ts_notify.py`:
```python
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
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `pytest tests/test_ts_notify.py -v`
Expected: PASS (5 Tests)

- [ ] **Step 5: Commit**

```bash
git add app/ts_notify.py tests/test_ts_notify.py
git commit -m "feat(ts): recipients_for — Consent-basierte Empfängerauswahl"
```

---

## Task 6: `send_web_push` aus `send_web_push_notifications` ausklammern

**Files:**
- Modify: `app/poller.py:59-144`
- Test: `tests/test_poller.py`

Generische Funktion `send_web_push(vapid_private_key, vapid_contact_email, db_path, subscriptions, payload, label="WebPush")` mit dem bestehenden Retry-/410-Cleanup-Loop. `send_web_push_notifications` baut weiterhin Payload + holt Subscriptions und ruft `send_web_push` auf — VATSIM-Verhalten bleibt identisch.

- [ ] **Step 1: Failing test schreiben**

In `tests/test_poller.py` ans Ende ergänzen:
```python
# ---------------------------------------------------------------------------
# send_web_push (generisch)
# ---------------------------------------------------------------------------

class TestSendWebPush:
    @pytest.mark.asyncio
    async def test_sends_to_each_subscription(self, tmp_path):
        from app.database import init_db
        from app.poller import send_web_push

        db = str(tmp_path / "t.db")
        init_db(db)
        subs = [
            {"endpoint": "https://x/1", "p256dh": "p1", "auth": "a1"},
            {"endpoint": "https://x/2", "p256dh": "p2", "auth": "a2"},
        ]
        calls = []
        with patch("app.poller.webpush", new=MagicMock(side_effect=lambda **kw: calls.append(kw))):
            await send_web_push("priv", "mailto:x@y.z", db, subs, {"title": "T", "body": "B"})
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_410_deletes_subscription(self, tmp_path):
        from app.database import init_db, get_connection, upsert_push_subscription
        from app.poller import send_web_push
        from pywebpush import WebPushException

        db = str(tmp_path / "t.db")
        init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "https://x/gone", "p", "a")
        conn.commit()
        conn.close()

        resp = MagicMock()
        resp.status_code = 410
        exc = WebPushException("gone")
        exc.response = resp
        subs = [{"endpoint": "https://x/gone", "p256dh": "p", "auth": "a"}]
        with patch("app.poller.webpush", new=MagicMock(side_effect=exc)):
            await send_web_push("priv", "mailto:x@y.z", db, subs, {"title": "T", "body": "B"})

        conn = get_connection(db)
        left = conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]
        conn.close()
        assert left == 0
```

> Hinweis: `webpush`/`WebPushException` werden in `poller.py` bisher *innerhalb* der Funktion importiert. Damit der `patch("app.poller.webpush", ...)` greift, werden sie in Step 3 auf Modulebene importiert.

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/test_poller.py::TestSendWebPush -v`
Expected: FAIL — `ImportError: cannot import name 'send_web_push'` (bzw. `app.poller.webpush` existiert nicht)

- [ ] **Step 3: Modulimport + `send_web_push` einführen**

In `app/poller.py` oben bei den Imports (nach `import httpx`) ergänzen:
```python
from pywebpush import webpush, WebPushException
```

Neue Funktion **vor** `send_web_push_notifications` einfügen:
```python
async def send_web_push(
    vapid_private_key: str,
    vapid_contact_email: str,
    db_path: str,
    subscriptions: list[dict],
    payload: dict,
    label: str = "WebPush",
) -> None:
    """Ein Payload-Dict an eine fertige Subscription-Liste senden.

    Generischer Kern: Retry (1×), 410-Endpoint-Cleanup, Silent-Fail-Logging.
    Wird von der VATSIM- und der TS-Seite gemeinsam genutzt.
    """
    import json as _json

    if not subscriptions:
        return
    data = _json.dumps(payload)
    loop = asyncio.get_event_loop()
    to_delete: list[str] = []

    for sub in subscriptions:
        sub_info = {
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        }
        sent = False
        last_exc = None
        for attempt in range(2):
            if attempt > 0:
                await asyncio.sleep(5)
            try:
                await loop.run_in_executor(
                    None,
                    lambda s=sub_info: webpush(
                        subscription_info=s,
                        data=data,
                        vapid_private_key=vapid_private_key,
                        vapid_claims={"sub": vapid_contact_email},
                        ttl=3600,
                    ),
                )
                logger.info("%s sent OK: %s", label, sub["endpoint"][:40])
                sent = True
                break
            except WebPushException as exc:
                resp = getattr(exc, "response", None)
                sc = getattr(resp, "status_code", None)
                if sc == 410:
                    to_delete.append(sub["endpoint"])
                    break
                last_exc = exc
            except Exception as exc:
                last_exc = exc
                break
        if not sent and last_exc is not None:
            resp = getattr(last_exc, "response", None)
            sc = getattr(resp, "status_code", "?") if resp else type(last_exc).__name__
            cause = repr(getattr(last_exc, "__cause__", None))[:120]
            args = repr(getattr(last_exc, "args", ()))[:200]
            logger.warning("%s failed: %s cause=%s args=%s", label, sc, cause, args)

    if to_delete:
        conn = get_connection(db_path)
        try:
            for endpoint in to_delete:
                delete_push_subscription(conn, endpoint)
            conn.commit()
        finally:
            conn.close()
```

- [ ] **Step 4: `send_web_push_notifications` auf `send_web_push` umstellen**

Ersetze den Body von `send_web_push_notifications` (ab dem `import json`/`from pywebpush`-Block bis zum Ende) durch:
```python
async def send_web_push_notifications(
    vapid_private_key: str,
    vapid_contact_email: str,
    db_path: str,
    pilot: dict,
) -> None:
    """Push-Notification an alle passenden Subscriptions senden."""
    cid = pilot.get("cid")
    callsign = pilot.get("callsign", "?")
    dep = pilot.get("departure") or "?"
    arr = pilot.get("arrival") or "?"
    aircraft = pilot.get("aircraft_short") or pilot.get("aircraft") or ""

    payload = {
        "title": f"{callsign} ist online! ✈",
        "body": f"{dep} → {arr}" + (f" · {aircraft}" if aircraft else ""),
        "url": "/",
    }
    conn = get_connection(db_path)
    try:
        subscriptions = get_push_subscriptions_for_pilot(conn, cid)
    finally:
        conn.close()

    logger.info("WebPush: %s online, %d subscription(s)", callsign, len(subscriptions))
    await send_web_push(
        vapid_private_key, vapid_contact_email, db_path,
        subscriptions, payload, label=f"WebPush[{callsign}]",
    )
```
(Der lokale `from pywebpush import ...` in dieser Funktion entfällt — der Import steht jetzt auf Modulebene. `send_prefile_push_notifications` bleibt unverändert; sie nutzt weiter ihren eigenen lokalen Import, der unschädlich neben dem Modulimport steht.)

- [ ] **Step 5: Tests ausführen, Erfolg bestätigen**

Run: `pytest tests/test_poller.py -v`
Expected: PASS (neue `TestSendWebPush` + alle bestehenden)

- [ ] **Step 6: Commit**

```bash
git add app/poller.py tests/test_poller.py
git commit -m "refactor(push): send_web_push als generischen Kern ausklammern"
```

---

## Task 7: TS-Settings in `app/config.py`

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_config.py` ergänzen (Defaults prüfen). Falls dort ein Muster mit `monkeypatch.setenv("SECRET_KEY", ...)` + `get_settings.cache_clear()` existiert, daran anlehnen:
```python
class TestTsSettings:
    def test_ts_defaults(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "x")
        from app.config import get_settings
        get_settings.cache_clear()
        try:
            s = get_settings()
            assert s.TS_NOTIFY_ENABLED is False
            assert s.TS_QUERY_PORT == 10011
            assert s.TS_NOTIFY_CHANNEL_ID == 0
            assert s.TS_POLL_INTERVAL == 30
            assert s.TS_REJOIN_DEBOUNCE_SEC == 900
        finally:
            get_settings.cache_clear()
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/test_config.py::TestTsSettings -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'TS_NOTIFY_ENABLED'`

- [ ] **Step 3: Settings ergänzen**

In `app/config.py` in der `Settings`-Klasse nach `VAPID_CONTACT_EMAIL` einfügen:
```python
    # TeamSpeak-ServerQuery (Phase 1: Login-Benachrichtigung)
    TS_NOTIFY_ENABLED: bool = False
    TS_HOST: str = "127.0.0.1"
    TS_QUERY_PORT: int = 10011
    TS_QUERY_USER: str = ""
    TS_QUERY_PASS: str = ""
    TS_SERVER_ID: int = 1
    TS_NOTIFY_CHANNEL_ID: int = 0   # 0 = ganzer Server
    TS_POLL_INTERVAL: int = 30
    TS_REJOIN_DEBOUNCE_SEC: int = 900
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(ts): TS-ServerQuery-Settings mit Defaults"
```

---

## Task 8: `_poll_teamspeak`-Job im `VatsimPoller`

**Files:**
- Modify: `app/poller.py` (`__init__`, `start`, neue Methode, `create_poller`)
- Test: `tests/test_poller.py`

Neuer Job-State + `_poll_teamspeak`. Diff `current - _ts_last_seen`; erster Poll = Baseline (kein Push, Muster wie `_prefile_sigs is None` → hier `_ts_last_seen is None`); Debounce pro FRS über `_ts_last_notified`; pro Treffer `recipients_for` + `send_web_push` via `asyncio.create_task`. Exceptions nur loggen. Job nur registrieren wenn `ts_notify_enabled` und VAPID konfiguriert.

- [ ] **Step 1: Failing test schreiben**

In `tests/test_poller.py` ans Ende ergänzen:
```python
# ---------------------------------------------------------------------------
# _poll_teamspeak (TS-Login-Diff)
# ---------------------------------------------------------------------------

class TestPollTeamspeak:
    def _ts_poller(self, db_path):
        return VatsimPoller(
            db_path=db_path, callsign_prefix="FRS", poll_interval=60,
            vapid_private_key="priv", vapid_contact_email="mailto:x@y.z",
            ts_notify_enabled=True, ts_poll_interval=30, ts_rejoin_debounce_sec=900,
        )

    @pytest.mark.asyncio
    async def test_baseline_first_poll_no_push(self, tmp_path):
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = self._ts_poller(db)
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
        assert sent == []
        assert poller._ts_last_seen == {"FRS1"}

    @pytest.mark.asyncio
    async def test_new_join_triggers_push(self, tmp_path):
        from app.database import init_db, get_connection, upsert_push_subscription
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_ts=True, ts_self_frs="FRS9")
        conn.commit(); conn.close()
        poller = self._ts_poller(db)
        poller._ts_last_seen = set()  # Baseline überspringen
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)  # create_task laufen lassen
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_debounce_suppresses_rejoin(self, tmp_path):
        from app.database import init_db, get_connection, upsert_push_subscription
        from datetime import datetime, timezone
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_ts=True)
        conn.commit(); conn.close()
        poller = self._ts_poller(db)
        poller._ts_last_seen = set()
        poller._ts_last_notified["FRS1"] = datetime.now(timezone.utc)  # eben erst benachrichtigt
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert sent == []

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self, tmp_path):
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = self._ts_poller(db)
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(side_effect=RuntimeError("boom"))):
            await poller._poll_teamspeak()  # darf nicht werfen

    @pytest.mark.asyncio
    async def test_ts_job_registered_when_enabled(self, tmp_path):
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = self._ts_poller(db)
        await poller.start()
        try:
            assert "ts_poll" in {j.id for j in poller._scheduler.get_jobs()}
        finally:
            await poller.stop()

    @pytest.mark.asyncio
    async def test_ts_job_absent_when_disabled(self, tmp_path):
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = _make_poller(db_path=db)  # ts_notify_enabled default False
        await poller.start()
        try:
            assert "ts_poll" not in {j.id for j in poller._scheduler.get_jobs()}
        finally:
            await poller.stop()
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/test_poller.py::TestPollTeamspeak -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'ts_notify_enabled'`

- [ ] **Step 3: Imports + `__init__`-State erweitern**

In `app/poller.py` die DB-Importe um die Consent-Helper erweitern:
```python
from app.database import (
    cleanup_old_history,
    close_flight,
    delete_push_subscription,
    ensure_pilot,
    get_connection,
    get_live_positions,
    get_push_subscriptions_for_pilot,
    get_push_subscriptions_for_prefile,
    get_ts_consent,
    get_ts_push_subscriptions,
    load_prefile_sigs,
    open_flight,
    remove_live_position,
    save_position_history,
    save_prefile_sigs,
    update_flight_plan,
    upsert_live_position,
    upsert_statsim_flights,
)
from app.teamspeak import fetch_channel_clients
from app.ts_notify import recipients_for
```

`VatsimPoller.__init__`-Signatur um TS-Parameter erweitern (nach `vapid_contact_email`):
```python
        vapid_contact_email: str = "",
        ts_notify_enabled: bool = False,
        ts_host: str = "127.0.0.1",
        ts_query_port: int = 10011,
        ts_query_user: str = "",
        ts_query_pass: str = "",
        ts_server_id: int = 1,
        ts_notify_channel_id: int = 0,
        ts_poll_interval: int = 30,
        ts_rejoin_debounce_sec: int = 900,
    ) -> None:
```

Im `__init__`-Body nach `self.vapid_contact_email = vapid_contact_email` ergänzen:
```python
        self.ts_notify_enabled = ts_notify_enabled
        self.ts_host = ts_host
        self.ts_query_port = ts_query_port
        self.ts_query_user = ts_query_user
        self.ts_query_pass = ts_query_pass
        self.ts_server_id = ts_server_id
        self.ts_notify_channel_id = ts_notify_channel_id
        self.ts_poll_interval = ts_poll_interval
        self.ts_rejoin_debounce_sec = ts_rejoin_debounce_sec
```

Und nach `self._prefile_sigs: dict | None = None`:
```python
        # TS-Login-Diff: FRS-Menge im Zielkanal beim letzten Poll. None = erster Poll (Baseline).
        self._ts_last_seen: set[str] | None = None
        # FRS → Zeitpunkt der letzten Benachrichtigung (Debounce gegen Re-Joins).
        self._ts_last_notified: dict[str, datetime] = {}
```

- [ ] **Step 4: Job-Registrierung in `start()`**

In `app/poller.py` in `start()`, nach dem `vatsim_poll`-`add_job` und vor `self._scheduler.start()`:
```python
        if self.ts_notify_enabled and self.vapid_private_key:
            self._scheduler.add_job(
                self._poll_teamspeak,
                "interval",
                seconds=self.ts_poll_interval,
                id="ts_poll",
            )
            logger.info("TS-Login-Benachrichtigung aktiv (Kanal %d, %ds)",
                        self.ts_notify_channel_id, self.ts_poll_interval)
```

- [ ] **Step 5: `_poll_teamspeak` implementieren**

In `app/poller.py` nach `_poll_once` (vor `_sync_calendar`) einfügen:
```python
    async def _poll_teamspeak(self) -> None:
        """TS-ServerQuery pollen, neue FRS-Beitritte → WebPush. Exceptions nur loggen."""
        try:
            clients = await fetch_channel_clients(
                host=self.ts_host,
                port=self.ts_query_port,
                user=self.ts_query_user,
                password=self.ts_query_pass,
                server_id=self.ts_server_id,
                channel_id=self.ts_notify_channel_id,
            )
            current = {c["frs"] for c in clients}
            nick_by_frs = {c["frs"]: c["nick"] for c in clients}

            if self._ts_last_seen is None:
                # Erster Poll nach Start — Baseline setzen, keine Notifications.
                self._ts_last_seen = current
                return

            newly_joined = current - self._ts_last_seen
            self._ts_last_seen = current
            if not newly_joined:
                return

            now = datetime.now(timezone.utc)
            for frs in newly_joined:
                last = self._ts_last_notified.get(frs)
                if last and (now - last).total_seconds() < self.ts_rejoin_debounce_sec:
                    continue
                self._ts_last_notified[frs] = now

                conn = get_connection(self.db_path)
                try:
                    consent = get_ts_consent(conn, frs)
                    subs = get_ts_push_subscriptions(conn)
                finally:
                    conn.close()

                recipients = recipients_for(consent, subs, frs)
                if not recipients:
                    continue

                nick = nick_by_frs.get(frs, frs)
                payload = {
                    "title": f"🎧 {nick} ist im TeamSpeak",
                    "body": "FriesenFlieger TeamSpeak",
                    "url": "/",
                }
                asyncio.create_task(
                    send_web_push(
                        self.vapid_private_key,
                        self.vapid_contact_email,
                        self.db_path,
                        recipients,
                        payload,
                        label=f"TSPush[{frs}]",
                    )
                )
        except Exception:
            logger.exception("Error in _poll_teamspeak")
```

- [ ] **Step 6: `create_poller` um TS-Settings erweitern**

In `app/poller.py` in `create_poller()` den `return VatsimPoller(...)` um die TS-Argumente erweitern:
```python
    return VatsimPoller(
        db_path=settings.DB_PATH,
        callsign_prefix=settings.CALLSIGN_PREFIX,
        poll_interval=settings.VATSIM_POLL_INTERVAL,
        telegram_token=settings.TELEGRAM_BOT_TOKEN,
        telegram_chat_id=settings.TELEGRAM_CHAT_ID,
        vapid_private_key=settings.VAPID_PRIVATE_KEY,
        vapid_contact_email=settings.VAPID_CONTACT_EMAIL,
        ts_notify_enabled=settings.TS_NOTIFY_ENABLED,
        ts_host=settings.TS_HOST,
        ts_query_port=settings.TS_QUERY_PORT,
        ts_query_user=settings.TS_QUERY_USER,
        ts_query_pass=settings.TS_QUERY_PASS,
        ts_server_id=settings.TS_SERVER_ID,
        ts_notify_channel_id=settings.TS_NOTIFY_CHANNEL_ID,
        ts_poll_interval=settings.TS_POLL_INTERVAL,
        ts_rejoin_debounce_sec=settings.TS_REJOIN_DEBOUNCE_SEC,
    )
```

- [ ] **Step 7: Tests ausführen, Erfolg bestätigen**

Run: `pytest tests/test_poller.py -v`
Expected: PASS (alle `TestPollTeamspeak` + bestehende)

- [ ] **Step 8: Commit**

```bash
git add app/poller.py tests/test_poller.py
git commit -m "feat(ts): _poll_teamspeak-Job — FRS-Beitritt → WebPush mit Debounce"
```

---

## Task 9: `/api/push/subscribe` um `notify_ts` + `ts_self_frs` erweitern

**Files:**
- Modify: `app/main.py:150-154`

Damit ein Gerät sich für TS-Benachrichtigungen opt-in melden und seine eigene FRS hinterlegen kann (für Selbst-Überspringen + allowlist-Zielung). Rückwärtskompatibel: fehlende Felder ⇒ kein TS-Opt-in.

- [ ] **Step 1: Endpoint anpassen**

In `app/main.py` den `upsert_push_subscription`-Aufruf in `push_subscribe` ersetzen:
```python
        upsert_push_subscription(
            conn, endpoint, p256dh, auth,
            body.get("pilot_filter"),
            notify_prefiles=bool(body.get("notify_prefiles", False)),
            notify_ts=bool(body.get("notify_ts", False)),
            ts_self_frs=(body.get("ts_self_frs") or None),
        )
```

- [ ] **Step 2: Test ausführen (Regression)**

Run: `pytest tests/ -v`
Expected: PASS — bestehende Push-Subscribe-Tests bleiben grün (neue Felder optional).

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat(ts): subscribe-Endpoint nimmt notify_ts + ts_self_frs entgegen"
```

---

## Task 10: Admin-CLI `manage_ts_consent.py`

**Files:**
- Create: `manage_ts_consent.py` (Projekt-Wurzel)
- Test: `tests/test_manage_ts_consent.py`

Kleines stdlib-CLI (argparse) zum Seeden der `ts_consent`-Tabelle ohne Hand-SQL — spec-konform (kein Web-UI). Subcommands: `set`, `get`, `list`, `delete`. Nutzt `upsert_ts_consent`/`get_ts_consent` aus `app.database`; DB-Pfad aus `get_settings().DB_PATH` oder `--db`. `main(argv) -> int` ist testbar (kein Prozess-Spawn nötig).

- [ ] **Step 1: Failing test schreiben**

`tests/test_manage_ts_consent.py`:
```python
"""Tests für das Admin-CLI manage_ts_consent.py."""
from __future__ import annotations

import pytest

from app.database import init_db, get_connection, get_ts_consent
from manage_ts_consent import main


def test_set_then_get(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    init_db(db)
    rc = main(["--db", db, "set", "FRS135", "allowlist", "--allow", "FRS2", "FRS7"])
    assert rc == 0
    conn = get_connection(db)
    row = get_ts_consent(conn, "FRS135")
    conn.close()
    assert row["visibility"] == "allowlist"
    assert row["allowlist"] == ["FRS2", "FRS7"]


def test_set_nobody(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    assert main(["--db", db, "set", "FRS135", "nobody"]) == 0
    conn = get_connection(db)
    assert get_ts_consent(conn, "FRS135")["visibility"] == "nobody"
    conn.close()


def test_invalid_visibility_rejected(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    with pytest.raises(SystemExit):
        main(["--db", db, "set", "FRS135", "bogus"])


def test_delete(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    main(["--db", db, "set", "FRS135", "nobody"])
    assert main(["--db", db, "delete", "FRS135"]) == 0
    conn = get_connection(db)
    assert get_ts_consent(conn, "FRS135") is None
    conn.close()


def test_list_runs(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    init_db(db)
    main(["--db", db, "set", "FRS1", "everyone"])
    assert main(["--db", db, "list"]) == 0
    assert "FRS1" in capsys.readouterr().out
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `pytest tests/test_manage_ts_consent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'manage_ts_consent'`

- [ ] **Step 3: Implementierung**

`manage_ts_consent.py`:
```python
#!/usr/bin/env python3
"""Admin-CLI für die ts_consent-Tabelle (FriesenSpy Phase 1).

Seedet/zeigt Einwilligungen ohne Hand-SQL. Kein Web-UI (spec-konform).

Beispiele:
  python manage_ts_consent.py set FRS135 nobody
  python manage_ts_consent.py set FRS135 allowlist --allow FRS2 FRS7
  python manage_ts_consent.py get FRS135
  python manage_ts_consent.py list
  python manage_ts_consent.py delete FRS135
"""
from __future__ import annotations

import argparse
import sys

from app.config import get_settings
from app.database import get_connection, get_ts_consent, upsert_ts_consent

_VISIBILITIES = ("everyone", "nobody", "allowlist")


def _db_path(args: argparse.Namespace) -> str:
    return args.db or get_settings().DB_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ts_consent verwalten")
    parser.add_argument("--db", default=None, help="DB-Pfad (Default: Settings.DB_PATH)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_set = sub.add_parser("set", help="Einwilligung setzen")
    p_set.add_argument("frs")
    p_set.add_argument("visibility", choices=_VISIBILITIES)
    p_set.add_argument("--allow", nargs="*", default=None,
                       help="Empfänger-FRS für visibility=allowlist")

    p_get = sub.add_parser("get", help="Einwilligung einer FRS anzeigen")
    p_get.add_argument("frs")

    sub.add_parser("list", help="Alle Einträge anzeigen")

    p_del = sub.add_parser("delete", help="Eintrag löschen (= zurück auf Default 'everyone')")
    p_del.add_argument("frs")

    args = parser.parse_args(argv)
    conn = get_connection(_db_path(args))
    try:
        if args.cmd == "set":
            allow = args.allow if args.visibility == "allowlist" else None
            upsert_ts_consent(conn, args.frs, args.visibility, allow)
            conn.commit()
            print(f"OK: {args.frs} → {args.visibility}"
                  + (f" {allow}" if allow else ""))
        elif args.cmd == "get":
            row = get_ts_consent(conn, args.frs)
            print(row if row else f"{args.frs}: kein Eintrag (Default 'everyone')")
        elif args.cmd == "list":
            rows = conn.execute(
                "SELECT frs, visibility, allowlist, updated_at FROM ts_consent ORDER BY frs"
            ).fetchall()
            if not rows:
                print("(leer)")
            for r in rows:
                print(f"{r['frs']:>10}  {r['visibility']:<10}  {r['allowlist'] or ''}")
        elif args.cmd == "delete":
            conn.execute("DELETE FROM ts_consent WHERE frs = ?", (args.frs,))
            conn.commit()
            print(f"OK: {args.frs} gelöscht (gilt jetzt als 'everyone')")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `pytest tests/test_manage_ts_consent.py -v`
Expected: PASS (5 Tests)

- [ ] **Step 5: Commit**

```bash
git add manage_ts_consent.py tests/test_manage_ts_consent.py
git commit -m "feat(ts): Admin-CLI manage_ts_consent zum Seeden der Einwilligungen"
```

---

## Task 11: Doku aktualisieren

**Files:**
- Modify: `README.md`, `docs/api.md`, `docs/architecture.md`, `CLAUDE.md`

Memory-Regel „Docs immer aktualisieren": bei jeder Codeänderung README + docs/api + docs/architecture mitpflegen.

- [ ] **Step 1: Vorhandene Doku sichten**

Run: `ls docs/ && head -50 README.md`
Lies die Stellen, an denen Settings, Endpoints und der Poller/Architektur beschrieben sind, um Stil und Ort zu treffen.

- [ ] **Step 2: README.md**

Abschnitt für die TS-Login-Benachrichtigung ergänzen: Zweck (FRS betritt TS-Kanal → WebPush), die neuen `config.env`-Variablen (`TS_NOTIFY_ENABLED`, `TS_HOST`, `TS_QUERY_PORT`, `TS_QUERY_USER`, `TS_QUERY_PASS`, `TS_SERVER_ID`, `TS_NOTIFY_CHANNEL_ID`, `TS_POLL_INTERVAL`, `TS_REJOIN_DEBOUNCE_SEC`), Hinweis auf `ts_consent` (Admin seedet in Phase 1 via `manage_ts_consent.py` — Beispielaufrufe `set`/`list`) und dass `ts3` jetzt Dependency ist.

- [ ] **Step 3: docs/api.md**

`/api/push/subscribe` um die neuen optionalen Body-Felder `notify_ts` (bool) und `ts_self_frs` (string) ergänzen.

- [ ] **Step 4: docs/architecture.md**

Neue Module `app/teamspeak.py` (ServerQuery-Client) und `app/ts_notify.py` (Empfänger-Logik), den `ts_poll`-APScheduler-Job, die `ts_consent`-Tabelle und den generalisierten `send_web_push`-Kern dokumentieren. Datenfluss-Diagramm aus der Spec (Phase 1) übernehmen.

- [ ] **Step 5: CLAUDE.md (Projektstruktur)**

In `FriesenSpy/CLAUDE.md` unter „Projektstruktur" `app/teamspeak.py` und `app/ts_notify.py` eintragen; bei „Konfiguration" die TS-Variablen ergänzen.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/api.md docs/architecture.md CLAUDE.md
git commit -m "docs(ts): TS-Login-Benachrichtigung in README/api/architecture/CLAUDE dokumentieren"
```

---

## Task 12: Gesamt-Verifikation

**Files:** keine

- [ ] **Step 1: Volle Testsuite**

Run: `pytest tests/ -v`
Expected: alle Tests grün (keine Regressionen).

- [ ] **Step 2: Smoke-Import**

Run: `python -c "import app.main; import app.teamspeak; import app.ts_notify; print('ok')"`
Expected: `ok` (ohne `ts3`-Installation, dank lazy import).

- [ ] **Step 3: Deployment-Hinweise verifizieren (manuell, kein Code)**

Checkliste für den VPS-Rollout (in den PR-/Commit-Text aufnehmen, nicht ausführen):
- `ts3` ist in `requirements.txt` → Container-Image baut es mit.
- `/opt/friesenspy/config.env`: `TS_NOTIFY_ENABLED=true`, `TS_QUERY_USER`/`TS_QUERY_PASS`, `TS_NOTIFY_CHANNEL_ID` setzen.
- TS-ServerQuery-IP-Whitelist um die FriesenSpy-Container-/Host-Adresse erweitern (TS-Server läuft auf demselben VPS, `TS_HOST=127.0.0.1` bzw. Docker-Bridge-IP).
- End-to-end: kleinen `TS_REJOIN_DEBOUNCE_SEC` setzen → Zielkanal mit Testidentität (FRS im Nick) betreten → WebPush auf einem mit `notify_ts=1` abonnierten Gerät prüfen. Danach `ts_consent` für eine FRS via `python manage_ts_consent.py set FRSxx nobody` bzw. `... allowlist --allow FRSyy` setzen und Unterdrückung/Zielung gegenprüfen (Opt-in für Phase-1-Test ggf. per SQL: `UPDATE push_subscriptions SET notify_ts=1, ts_self_frs='FRSxx' WHERE endpoint=...`).

---

## Self-Review

**Spec-Abdeckung:**
- `app/teamspeak.py` (`fetch_channel_clients`, `parse_frs`) → Tasks 1–3 ✓
- `app/database.py` (`ts_consent`, Push-Migrationen, Helper) → Task 4 ✓
- `app/ts_notify.py` (`recipients_for`: everyone/nobody/allowlist, kein Eintrag, Selbst-Überspringen) → Task 5 ✓
- `app/poller.py` (`_poll_teamspeak`, Baseline, Debounce, `send_web_push` generalisiert) → Tasks 6 + 8 ✓
- `app/config.py` (alle 9 TS-Settings) → Task 7 ✓
- WebPush-Payload (`🎧 {nick} ist im TeamSpeak`) → Task 8 ✓
- Fehlerbehandlung (ServerQuery → [], Job unabhängig, 410-Cleanup wiederverwendet) → Tasks 3, 6, 8 ✓
- Tests `test_teamspeak`, `test_ts_notify`, `test_poller`, `test_database` → Tasks 1–8 ✓
- Admin-Seeding der Einwilligung (kein Web-UI) → `manage_ts_consent.py`, Task 10 ✓
- Deployment (`ts3` in requirements, IP-Whitelist, e2e-Verifikation) → Tasks 3, 12 ✓
- Phase-2-Punkte (Forum-Flag-Sync) → bewusst NICHT umgesetzt ✓

**Zusatz über die Spec hinaus (notwendig für funktionierendes Phase-1-Feature):** `/api/push/subscribe`-Erweiterung (Task 9) + `upsert_push_subscription`-Parameter (Task 4) — ohne sie gäbe es keinen Opt-in-Pfad außer manuellem SQL. Plus `manage_ts_consent.py` (Task 10) als spec-konformer (kein Web-UI) Seeding-Weg statt Hand-SQL. Alles minimal gehalten, rückwärtskompatibel.

**Offener Punkt:** Default-Einwilligung `everyone` (so in der Spec bestätigt, aber als Freigabe-Punkt markiert). Falls Privacy-by-default gewünscht: `recipients_for` (Default-`visibility`) + `ts_consent.visibility`-DDL-Default auf `nobody` ändern.
