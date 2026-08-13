"""Tests für neue Admin-DB-Funktionen: app_settings, Pilots-CRUD, Push-Einzellookup."""
from __future__ import annotations

import pytest

from app.database import (
    delete_pilot,
    get_app_setting,
    get_connection,
    get_inactive_cids,
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

    def test_new_pilot_active_by_default(self, conn):
        upsert_pilot(conn, 111, "Tobias")
        conn.commit()
        assert list_pilots(conn)[0]["active"] is True
        assert get_inactive_cids(conn) == set()

    def test_upsert_with_active_false_excludes_from_detection(self, conn):
        upsert_pilot(conn, 111, "Gast-CID", active=False)
        conn.commit()
        pilots = {p["cid"]: p for p in list_pilots(conn)}
        assert pilots[111]["active"] is False
        assert get_inactive_cids(conn) == {111}

    def test_reactivating_pilot_removes_from_inactive_cids(self, conn):
        upsert_pilot(conn, 111, "Gast-CID", active=False)
        conn.commit()
        assert get_inactive_cids(conn) == {111}

        upsert_pilot(conn, 111, "Gast-CID", active=True)
        conn.commit()
        assert get_inactive_cids(conn) == set()

    def test_get_inactive_cids_only_lists_inactive(self, conn):
        upsert_pilot(conn, 111, "Aktiv")
        upsert_pilot(conn, 222, "Inaktiv", active=False)
        upsert_pilot(conn, 333, "Auch aktiv")
        conn.commit()
        assert get_inactive_cids(conn) == {222}


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


class TestGesperrtePilotenVerschwindenRueckwirkend:
    """Gesperrt heißt überall weg -- auch für bereits gespeicherte Flüge.

    Live-Fund 13.08.2026: Die Sperre wirkte zunächst NUR im Live-Abgleich gegen VATSIM. Neue
    Flüge wurden dadurch zwar nicht mehr aufgezeichnet, aber alles bereits Gespeicherte zählte
    in der Statistik unverändert weiter -- der Nutzer sperrte vier IDs und sah sie weiterhin.
    Der Filter sitzt jetzt in den beiden Ladefunktionen, durch die Flüge überhaupt in
    Statistik, Piloten, Bummel und Kutter gelangen.
    """

    def _flug(self, conn, cid, callsign, logon, logoff):
        """Abgeschlossene Connection ohne GPS-Track -- canonicalize_legs nimmt dafür den
        Flugplan-Fallback. Felder wie in tests/test_bummel.py::_add_flight: ohne
        duration_min/distance_nm/block_min gilt die Zeile nicht als echter Flug.
        flights.cid hat zudem einen Fremdschlüssel auf pilots.
        """
        upsert_pilot(conn, cid, f"Pilot {cid}")
        conn.execute(
            "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, "
            "logon_time, logoff_time, duration_min, distance_nm, block_min) "
            "VALUES (?, ?, 'C172', 'EDDH', 'EDDW', ?, ?, 30, 50.0, 35)",
            (cid, callsign, logon, logoff),
        )

    def test_gesperrter_pilot_faellt_aus_canonicalize_legs(self, conn):
        from app.database import canonicalize_legs

        self._flug(conn, 111, "FRS111", "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")
        self._flug(conn, 222, "FRS222", "2026-06-01T12:00:00Z", "2026-06-01T13:00:00Z")
        conn.commit()

        vorher = {f["cid"] for f in canonicalize_legs(conn)}
        assert vorher == {111, 222}

        upsert_pilot(conn, 222, "Gesperrt", active=False)
        conn.commit()

        nachher = {f["cid"] for f in canonicalize_legs(conn)}
        assert nachher == {111}, "gesperrte CID muss auch rueckwirkend verschwinden"

    def test_entsperren_bringt_die_fluege_zurueck(self, conn):
        """Die Flüge bleiben in der Datenbank -- gesperrt ist eine Sicht, kein Löschen."""
        from app.database import canonicalize_legs

        self._flug(conn, 333, "FRS333", "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
        upsert_pilot(conn, 333, "Erst gesperrt", active=False)
        conn.commit()
        assert {f["cid"] for f in canonicalize_legs(conn)} == set()

        upsert_pilot(conn, 333, "Wieder frei", active=True)
        conn.commit()
        assert {f["cid"] for f in canonicalize_legs(conn)} == {333}

    def test_ohne_sperre_bleibt_alles_unveraendert(self, conn):
        from app.database import canonicalize_legs

        self._flug(conn, 444, "FRS444", "2026-06-03T10:00:00Z", "2026-06-03T11:00:00Z")
        conn.commit()
        assert {f["cid"] for f in canonicalize_legs(conn)} == {444}
