"""Tests für Events-Push-Abo (notify_events) + ~1h-Erinnerung (events_due_for_reminder)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    events_due_for_reminder,
    get_connection,
    get_push_subscriptions_for_events,
    init_db,
    mark_event_reminded,
    upsert_calendar_events,
    upsert_push_subscription,
)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def conn(tmp_path):
    # init_db legt _DDL + alle Migrationen an (inkl. notify_events) → vollständiges Schema
    db = str(tmp_path / "t.db")
    init_db(db)
    c = get_connection(db)
    yield c
    c.close()


class TestNotifyEventsFlag:
    def test_only_events_subscribers_returned(self, conn):
        upsert_push_subscription(conn, "ep-yes", "p", "a", notify_events=True)
        upsert_push_subscription(conn, "ep-no", "p", "a", notify_events=False)
        conn.commit()
        subs = get_push_subscriptions_for_events(conn)
        assert {s["endpoint"] for s in subs} == {"ep-yes"}

    def test_default_is_off(self, conn):
        upsert_push_subscription(conn, "ep", "p", "a")  # ohne notify_events → default aus
        conn.commit()
        assert get_push_subscriptions_for_events(conn) == []


class TestSubscribeEndpoint:
    def test_subscribe_persists_notify_events(self, tmp_path, monkeypatch):
        import asyncio
        from types import SimpleNamespace
        import app.main as main

        db = str(tmp_path / "t.db")
        init_db(db)
        monkeypatch.setattr(main, "get_settings",
                            lambda: SimpleNamespace(DB_PATH=db, CALLSIGN_PREFIX="FRS"))

        class FakeReq:
            def __init__(self, body):
                self._b = body

            async def json(self):
                return self._b

        asyncio.run(main.push_subscribe(FakeReq(
            {"endpoint": "e", "p256dh": "p", "auth": "a", "notify_events": True}
        )))
        c = get_connection(db)
        try:
            assert [s["endpoint"] for s in get_push_subscriptions_for_events(c)] == ["e"]
        finally:
            c.close()


class TestEventReminders:
    def _ev(self, uid, dtstart):
        return {"uid": uid, "summary": f"Event {uid}", "dtstart": dtstart,
                "dtend": "", "location": "", "route": "", "is_bummel": 0}

    def test_due_window(self, conn):
        now = datetime(2026, 6, 27, 20, 0, 0, tzinfo=timezone.utc)
        upsert_calendar_events(conn, [
            self._ev("near", _iso(now + timedelta(minutes=30))),   # in 30 min → fällig
            self._ev("far", _iso(now + timedelta(minutes=90))),    # in 90 min → noch nicht
            self._ev("past", _iso(now - timedelta(minutes=10))),   # vorbei → nein
        ])
        conn.commit()
        due = events_due_for_reminder(conn, _iso(now), lead_min=60)
        assert {e["uid"] for e in due} == {"near"}

    def test_dedup_after_mark(self, conn):
        now = datetime(2026, 6, 27, 20, 0, 0, tzinfo=timezone.utc)
        upsert_calendar_events(conn, [self._ev("x", _iso(now + timedelta(minutes=30)))])
        conn.commit()
        assert {e["uid"] for e in events_due_for_reminder(conn, _iso(now))} == {"x"}
        mark_event_reminded(conn, "x", _iso(now))
        conn.commit()
        assert events_due_for_reminder(conn, _iso(now)) == []
