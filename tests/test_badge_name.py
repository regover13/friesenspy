"""Eigener Badge-Name für Bummel und Kutter — der Event-Name sprengt die runde Grafik.

Der Badge zeichnet ``d["event"]``; gespeist wird das aus ``badge_name`` und faellt auf
``name`` zurueck, solange nichts Eigenes gesetzt ist. Leeren heisst deshalb: zurueck zur
Automatik.
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.auth import ADMIN_COOKIE, make_admin_token
from app.database import (
    _DDL,
    create_bummel_race,
    create_transport_event,
    get_bummel_race,
    get_connection,
    get_transport_event,
    init_db,
    update_bummel_race,
    update_transport_event,
)

SECRET = "test-secret"
PW = "test-pw"
START = "2026-07-01T18:00:00Z"
END = "2026-07-01T23:00:00Z"


def _make_conn() -> sqlite3.Connection:
    init_db(":memory:")
    conn = get_connection(":memory:")
    conn.executescript(_DDL)
    conn.commit()
    return conn


def _race(conn, name="Montagsfluege in Deutschland - Aach-Bummel") -> int:
    return create_bummel_race(conn, name=name, route="EDWF,EDWG", dtstart=START, dtend=END)


def _kutter(conn, name="Montagsfluege in Deutschland - Aach-Kutter") -> int:
    return create_transport_event(
        conn, name=name, dtstart=START, dtend=END, destination="EDXH",
        cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])


class TestSpalteBadgeName:
    """Die Spalte existiert, ist standardmaessig leer und laesst sich setzen und leeren."""

    def test_bummel_default_ist_leer(self):
        conn = _make_conn()
        assert get_bummel_race(conn, _race(conn))["badge_name"] is None

    def test_kutter_default_ist_leer(self):
        conn = _make_conn()
        assert get_transport_event(conn, _kutter(conn))["badge_name"] is None

    def test_bummel_setzen_und_leeren(self):
        conn = _make_conn()
        rid = _race(conn)
        update_bummel_race(conn, rid, badge_name="Aach-Bummel")
        assert get_bummel_race(conn, rid)["badge_name"] == "Aach-Bummel"
        update_bummel_race(conn, rid, badge_name=None)
        assert get_bummel_race(conn, rid)["badge_name"] is None

    def test_kutter_setzen_und_leeren(self):
        conn = _make_conn()
        eid = _kutter(conn)
        update_transport_event(conn, eid, badge_name="Aach-Kutter")
        assert get_transport_event(conn, eid)["badge_name"] == "Aach-Kutter"
        update_transport_event(conn, eid, badge_name=None)
        assert get_transport_event(conn, eid)["badge_name"] is None


class TestBadgeNimmtDenKurznamen:
    """Der Lesepfad: ``badge_name`` schlaegt ``name``, leer faellt zurueck."""

    VIEW = {"complete": [{"cid": 500, "callsign": "FRS500", "aircraft": "C172",
                          "rank": 1, "total_min": 90, "delta_sec": 0}],
            "incomplete": []}

    def test_bummel_nutzt_badge_name(self):
        race = {"name": "Montagsfluege in Deutschland - Aach-Bummel",
                "badge_name": "Aach-Bummel", "dtstart": START}
        d, _ = main._badge_entry_data(self.VIEW, race, 500)
        assert d["event"] == "Aach-Bummel"

    def test_bummel_faellt_auf_name_zurueck(self):
        race = {"name": "Aach-Bummel", "badge_name": None, "dtstart": START}
        d, _ = main._badge_entry_data(self.VIEW, race, 500)
        assert d["event"] == "Aach-Bummel"

    def test_bummel_leerer_string_faellt_auf_name_zurueck(self):
        race = {"name": "Aach-Bummel", "badge_name": "", "dtstart": START}
        d, _ = main._badge_entry_data(self.VIEW, race, 500)
        assert d["event"] == "Aach-Bummel"

    def _progress(self):
        return {"participants": [{"cid": 500, "callsign": "FRS500", "aircraft": "C172",
                                  "delivered_kg": 250.0}],
                "losses": [], "total_kg": 250.0, "target_kg": 500.0}

    def test_kutter_nutzt_badge_name(self):
        ev = {"name": "Montagsfluege in Deutschland - Aach-Kutter",
              "badge_name": "Aach-Kutter", "dtstart": START}
        assert main._kutter_badge_data(self._progress(), ev, 500)["event"] == "Aach-Kutter"

    def test_kutter_faellt_auf_name_zurueck(self):
        ev = {"name": "Aach-Kutter", "badge_name": None, "dtstart": START}
        assert main._kutter_badge_data(self._progress(), ev, 500)["event"] == "Aach-Kutter"

    def test_kutter_leerer_string_faellt_auf_name_zurueck(self):
        ev = {"name": "Aach-Kutter", "badge_name": "", "dtstart": START}
        assert main._kutter_badge_data(self._progress(), ev, 500)["event"] == "Aach-Kutter"


class TestAdminSpeichertBadgeName:
    def _app(self, tmp_path, monkeypatch):
        p = str(tmp_path / "badge_name.db")
        init_db(p)
        monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(
            DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD=PW,
            VAPID_PRIVATE_KEY="vapid", VAPID_CONTACT_EMAIL="mailto:test"))
        client = TestClient(main.app)
        client.cookies.update({ADMIN_COOKIE: make_admin_token(SECRET, PW)})
        return client, p

    def test_bummel_anlegen_mit_badge_name(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        r = client.post("/api/admin/bummel/races", json={
            "name": "Montagsfluege in Deutschland - Aach-Bummel", "route": "EDWF,EDWG",
            "dtstart": START, "badge_name": "Aach-Bummel"})
        assert r.status_code == 200
        conn = get_connection(db)
        assert get_bummel_race(conn, r.json()["id"])["badge_name"] == "Aach-Bummel"
        conn.close()

    def test_kutter_anlegen_mit_badge_name(self, tmp_path, monkeypatch):
        """Beim Anlegen laeuft zusaetzlich die Routen-Ableitung aus dem Manifest (#84) — sie
        darf den Kurznamen nicht ueberfahren."""
        client, db = self._app(tmp_path, monkeypatch)
        r = client.post("/api/admin/transport/events", json={
            "name": "Montagsfluege in Deutschland - Aach-Kutter", "destination": "EDXH",
            "dtstart": START, "badge_name": "Aach-Kutter",
            "cargo": [{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}]})
        assert r.status_code == 200
        conn = get_connection(db)
        ev = get_transport_event(conn, r.json()["id"])
        assert ev["badge_name"] == "Aach-Kutter"
        assert ev["route"]          # Route weiterhin abgeleitet, nicht leergeraeumt
        conn.close()

    def test_bummel_bearbeiten_setzt_und_loescht(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        conn = get_connection(db)
        rid = _race(conn)
        conn.commit()
        conn.close()

        assert client.post(f"/api/admin/bummel/races/{rid}",
                           json={"badge_name": "Aach-Bummel"}).status_code == 200
        conn = get_connection(db)
        assert get_bummel_race(conn, rid)["badge_name"] == "Aach-Bummel"
        conn.close()

        # Leeres Feld = zurueck zur Automatik, nicht "leerer Text im Badge".
        assert client.post(f"/api/admin/bummel/races/{rid}",
                           json={"badge_name": ""}).status_code == 200
        conn = get_connection(db)
        assert get_bummel_race(conn, rid)["badge_name"] is None
        conn.close()

    def test_kutter_bearbeiten_setzt_und_loescht(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        conn = get_connection(db)
        eid = _kutter(conn)
        conn.commit()
        conn.close()

        assert client.post(f"/api/admin/transport/events/{eid}",
                           json={"badge_name": "Aach-Kutter"}).status_code == 200
        conn = get_connection(db)
        assert get_transport_event(conn, eid)["badge_name"] == "Aach-Kutter"
        conn.close()

        assert client.post(f"/api/admin/transport/events/{eid}",
                           json={"badge_name": ""}).status_code == 200
        conn = get_connection(db)
        assert get_transport_event(conn, eid)["badge_name"] is None
        conn.close()

    def test_badge_name_wird_nicht_als_handgesetzt_markiert(self, tmp_path, monkeypatch):
        """#19: Der Kalender kennt kein ``badge_name``. Eine Marke haette dort einen
        Rueckholknopf, hinter dem nichts liegt."""
        client, db = self._app(tmp_path, monkeypatch)
        conn = get_connection(db)
        rid, eid = _race(conn), _kutter(conn)
        conn.commit()
        conn.close()

        client.post(f"/api/admin/bummel/races/{rid}", json={"badge_name": "Aach-Bummel"})
        client.post(f"/api/admin/transport/events/{eid}", json={"badge_name": "Aach-Kutter"})

        conn = get_connection(db)
        assert "badge_name" not in (get_bummel_race(conn, rid)["manual_fields"] or "")
        assert "badge_name" not in (get_transport_event(conn, eid)["manual_fields"] or "")
        conn.close()


class TestOberflaeche:
    """Statik-Tests am Quelltext von admin.html — es gibt dort keine JS-Laufzeit im Test.
    Verankert an IDs und Eigenschaftsnamen, die der Code wirklich benutzt."""

    import re as _re
    from pathlib import Path as _Path

    ADMIN = (_Path(__file__).resolve().parent.parent / "app" / "static" / "admin.html").read_text(
        encoding="utf-8")
    SKRIPT = "\n".join(_re.findall(r"<script>(.*?)</script>", ADMIN, _re.S))

    def test_alle_drei_formulare_haben_das_feld(self):
        assert 'id="nr-badge-name"' in self.ADMIN        # Bummel anlegen
        assert 'id="ke-badge-name"' in self.ADMIN        # Kutter anlegen/bearbeiten
        assert "edit-badge-name-" in self.SKRIPT         # Bummel bearbeiten (gerendert)

    def test_der_event_name_steht_als_platzhalter(self):
        """„Voreingestellt der Name des Events" — sichtbar, ohne den Wert festzuschreiben."""
        assert 'placeholder="${escA(r.name)}"' in self.SKRIPT           # Bummel bearbeiten
        assert "keBadgeFeld.placeholder = ev.name" in self.SKRIPT       # Kutter bearbeiten

    def test_bearbeiten_sendet_auch_den_leeren_wert(self):
        """Leeren = zurueck zum Event-Namen. Wird der leere Wert wegoptimiert, bleibt ein
        einmal gesetzter Kurzname fuer immer stehen."""
        assert "body.badge_name = document.getElementById(`edit-badge-name-${id}`)" in self.SKRIPT
        assert "if (_keEditingId || keBadge) body.badge_name = keBadge" in self.SKRIPT
