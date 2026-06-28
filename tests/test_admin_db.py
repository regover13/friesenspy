"""Tests für neue Admin-DB-Funktionen: app_settings, Pilots-CRUD, Push-Einzellookup."""
from __future__ import annotations

import pytest

from app.database import (
    delete_pilot,
    get_app_setting,
    get_connection,
    get_push_subscription_by_endpoint,
    init_db,
    list_pilots,
    set_app_setting,
    upsert_pilot,
    upsert_push_subscription,
)


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    c = get_connection(db)
    yield c
    c.close()


class TestAppSettings:
    def test_default_when_absent(self, conn):
        assert get_app_setting(conn, "banner_version") is None
        assert get_app_setting(conn, "banner_version", "auto") == "auto"

    def test_set_get_overwrite(self, conn):
        set_app_setting(conn, "banner_version", "6.1.2")
        conn.commit()
        assert get_app_setting(conn, "banner_version") == "6.1.2"
        set_app_setting(conn, "banner_version", "off")
        conn.commit()
        assert get_app_setting(conn, "banner_version") == "off"


class TestPilotsCrud:
    def test_upsert_list_delete(self, conn):
        upsert_pilot(conn, 111, "Tobias")
        upsert_pilot(conn, 222, "Arvind")
        conn.commit()
        pilots = {p["cid"]: p["name"] for p in list_pilots(conn)}
        assert pilots == {111: "Tobias", 222: "Arvind"}

        upsert_pilot(conn, 111, "Tobi")  # Name aktualisieren
        conn.commit()
        assert {p["cid"]: p["name"] for p in list_pilots(conn)}[111] == "Tobi"

        delete_pilot(conn, 111)
        conn.commit()
        assert 111 not in {p["cid"] for p in list_pilots(conn)}


class TestPilotCallsigns:
    """list_pilots liefert je CID alle bekannten FRS-Callsigns (distinct, sortiert)."""

    def _add_flight(self, conn, cid, callsign, logon):
        conn.execute(
            "INSERT INTO flights (cid, callsign, departure, arrival, logon_time, logoff_time) "
            "VALUES (?, ?, 'EDDH', 'EDDW', ?, ?)",
            (cid, callsign, logon, logon),
        )

    def test_list_pilots_includes_distinct_frs_callsigns(self, conn):
        upsert_pilot(conn, 111, "Tobias")
        upsert_pilot(conn, 222, "Arvind")  # keine Flüge
        self._add_flight(conn, 111, "FRS123", "2026-06-01T10:00:00Z")
        self._add_flight(conn, 111, "FRS 144", "2026-06-02T10:00:00Z")
        self._add_flight(conn, 111, "FRS123", "2026-06-04T10:00:00Z")  # Duplikat → einmal
        self._add_flight(conn, 111, "DLH400", "2026-06-03T10:00:00Z")  # kein FRS → ignoriert
        conn.commit()

        pilots = {p["cid"]: p for p in list_pilots(conn)}
        assert pilots[111]["callsigns"] == ["FRS 144", "FRS123"]  # distinct, sortiert, nur FRS
        assert pilots[222]["callsigns"] == []                     # keine Flüge → leer

    def test_callsign_prefix_is_configurable(self, conn):
        upsert_pilot(conn, 333, "Klaus")
        self._add_flight(conn, 333, "DLH400", "2026-06-01T10:00:00Z")
        self._add_flight(conn, 333, "FRS9", "2026-06-02T10:00:00Z")
        conn.commit()
        pilots = {p["cid"]: p for p in list_pilots(conn, callsign_prefix="DLH")}
        assert pilots[333]["callsigns"] == ["DLH400"]


class TestPushByEndpoint:
    def test_lookup_hit_and_miss(self, conn):
        upsert_push_subscription(conn, "ep1", "p256", "auth1")
        conn.commit()
        sub = get_push_subscription_by_endpoint(conn, "ep1")
        assert sub is not None
        assert sub["endpoint"] == "ep1" and sub["p256dh"] == "p256" and sub["auth"] == "auth1"
        assert get_push_subscription_by_endpoint(conn, "does-not-exist") is None
