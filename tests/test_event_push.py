"""Tests für Events-Push-Abo (notify_events) + ~1h-Erinnerung (events_due_for_reminder)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    bummel_races_due_for_reminder,
    events_due_for_reminder,
    get_connection,
    get_push_subscriptions_for_events,
    init_db,
    mark_event_reminded,
    transport_events_due_for_reminder,
    upsert_calendar_bummel_race,
    upsert_calendar_events,
    upsert_calendar_transport_event,
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

    def test_ausschluss_haengt_an_der_verknuepfung_nicht_am_flag(self, conn):
        """#19: Ausgeschlossen wird ein Termin, an dem ein Objekt HÄNGT — nicht einer, der bloß
        wie ein Bummel oder Kutter aussieht. Ein Kutter-Termin, zu dem niemand einen Kutter
        angelegt hat, ist ein ganz normaler Abend und muss erinnern; vorher fiel er still
        durch (das Flag allein reichte zum Ausschluss)."""
        now = datetime(2026, 6, 27, 20, 0, 0, tzinfo=timezone.utc)
        soon = _iso(now + timedelta(minutes=30))
        upsert_calendar_events(conn, [
            self._ev("generic", soon),
            {**self._ev("kutter-ohne-objekt", soon), "is_transport": 1, "route": "EDWG,EDXH"},
        ])
        conn.commit()
        due = events_due_for_reminder(conn, _iso(now), lead_min=60)
        assert {e["uid"] for e in due} == {"generic", "kutter-ohne-objekt"}

    def test_verknuepfter_termin_erinnert_nicht_doppelt(self, conn):
        """Gegenprobe: Sobald ein manuell angelegter Kutter mit dem Termin verknüpft ist,
        erinnert nur noch das Objekt."""
        from app.database import create_transport_event
        now = datetime(2026, 6, 27, 20, 0, 0, tzinfo=timezone.utc)
        soon = _iso(now + timedelta(minutes=30))
        upsert_calendar_events(conn, [
            {**self._ev("kutter-verknuepft", soon), "is_transport": 1, "route": "EDWG,EDXH"}])
        eid = create_transport_event(conn, name="Krabben", destination="EDWG",
                                     dtstart=soon, dtend="", cargo=None)
        conn.execute("UPDATE transport_events SET calendar_uid = 'kutter-verknuepft' WHERE id = ?",
                     (eid,))
        conn.commit()
        assert events_due_for_reminder(conn, _iso(now), lead_min=60) == []
        due = transport_events_due_for_reminder(conn, _iso(now), lead_min=60)
        assert [k["name"] for k in due] == ["Krabben"]

    def test_calendar_bummel_reminded_once_via_own_function_not_twice(self, conn):
        """Kalender-Bummel: erscheint über bummel_races_due_for_reminder, NICHT über
        events_due_for_reminder -- genau eine Erinnerung."""
        now = datetime(2026, 6, 27, 20, 0, 0, tzinfo=timezone.utc)
        soon = _iso(now + timedelta(minutes=30))
        ev = {"uid": "cal-bummel", "summary": "FFB Juli", "dtstart": soon, "dtend": "",
              "location": "", "route": "EDWF,EDWG", "is_bummel": 1, "is_transport": 0}
        upsert_calendar_events(conn, [ev])
        upsert_calendar_bummel_race(conn, ev)
        conn.commit()

        assert events_due_for_reminder(conn, _iso(now), lead_min=60) == []
        due = bummel_races_due_for_reminder(conn, _iso(now), lead_min=60)
        assert [r["name"] for r in due] == ["FFB Juli"]

    def test_calendar_kutter_reminded_once_via_own_function_not_twice(self, conn):
        """Altpfad: Ein Kutter-Objekt MIT calendar_uid (``upsert_calendar_transport_event``) wird
        über transport_events_due_for_reminder erinnert, nicht generisch. Seit #19 legt der
        Poller solche Objekte nicht mehr an — die Funktion bleibt für den Fall, dass der
        Kalenderimport für Kutter je zurückkehrt."""
        now = datetime(2026, 6, 27, 20, 0, 0, tzinfo=timezone.utc)
        soon = _iso(now + timedelta(minutes=30))
        ev = {"uid": "cal-kutter", "summary": "Kutter Juli", "dtstart": soon, "dtend": "",
              "location": "", "route": "EDWG,EDXH", "is_bummel": 0, "is_transport": 1}
        upsert_calendar_events(conn, [ev])
        upsert_calendar_transport_event(conn, ev)
        conn.commit()

        assert events_due_for_reminder(conn, _iso(now), lead_min=60) == []
        due = transport_events_due_for_reminder(conn, _iso(now), lead_min=60)
        assert [k["name"] for k in due] == ["Kutter Juli"]


# --- FriesenReddung: Erinnerung eine Stunde vorher (25.09.2026) --------------------------
#
# Nutzer nach dem Abend vom 25.09.: „es kam kein Push für den Start des Events." Die
# Erinnerung kannte Kalender-Events, Bummel und Kutter -- die Reddung nicht.

def _reddung(conn, name, dtstart, **extra):
    from app.database import create_reddung_event
    eid = create_reddung_event(conn, name=name, dtstart=dtstart, sued=53.54, west=6.95,
                               nord=53.90, ost=7.55, **extra)
    conn.commit()
    return eid


def test_reddung_erinnerung_fenster_und_dedup(conn):
    from app.database import reddung_events_due_for_reminder
    now = datetime(2026, 9, 25, 16, 0, 0, tzinfo=timezone.utc)
    nah = _reddung(conn, "Nah", _iso(now + timedelta(minutes=30)))
    _reddung(conn, "Fern", _iso(now + timedelta(minutes=90)))
    _reddung(conn, "Vorbei", _iso(now - timedelta(minutes=10)))
    _reddung(conn, "Stumm", _iso(now + timedelta(minutes=20)), push_enabled=0)
    due = reddung_events_due_for_reminder(conn, _iso(now), lead_min=60)
    assert [e["id"] for e in due] == [nah]
    mark_event_reminded(conn, f"reddung:{nah}", _iso(now))
    conn.commit()
    assert reddung_events_due_for_reminder(conn, _iso(now), lead_min=60) == []


def test_die_erinnerung_meldet_auch_die_reddung(tmp_path):
    """Die Pruefung laeuft ueber den echten Poller-Job, nicht nur ueber die Abfrage."""
    import asyncio
    from app.poller import VatsimPoller
    db = str(tmp_path / "t.db")
    init_db(db)
    c = get_connection(db)
    jetzt = datetime.now(timezone.utc)
    _reddung(c, "Abendsuche", _iso(jetzt + timedelta(minutes=8)))
    c.close()
    p = VatsimPoller(db_path=db, callsign_prefix="FRS", poll_interval=60)
    gesendet = []
    p.broadcast_notify = lambda kanal, ziel, payload: gesendet.append(payload)
    asyncio.run(p._check_event_reminders())
    assert any(g["title"] == "FriesenReddung" and "Abendsuche" in g["body"] for g in gesendet), gesendet
