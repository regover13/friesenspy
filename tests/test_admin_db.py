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


class TestPushByEndpoint:
    def test_lookup_hit_and_miss(self, conn):
        upsert_push_subscription(conn, "ep1", "p256", "auth1")
        conn.commit()
        sub = get_push_subscription_by_endpoint(conn, "ep1")
        assert sub is not None
        assert sub["endpoint"] == "ep1" and sub["p256dh"] == "p256" and sub["auth"] == "auth1"
        assert get_push_subscription_by_endpoint(conn, "does-not-exist") is None
