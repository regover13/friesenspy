"""Tests für die Panel-Selbstdiagnose (/api/panel-diag).

Hintergrund: Die Rendering-Engine im MSFS-EFB-Panel (Coherent GT) ist von außen praktisch
nicht untersuchbar -- der SDK-Debugger stürzt reproduzierbar ab. Das Panel misst deshalb
selbst und meldet hierher. Der Endpunkt ist bewusst OHNE Anmeldung erreichbar, weil ein
wesentlicher Teil der Fehlersuche genau die Fälle betrifft, in denen die Anmeldung im Panel
scheitert -- läge er hinter dem Login-Gate, fehlten die Messwerte ausgerechnet dann.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import make_admin_token, make_confirm_token
from app.database import (
    PANEL_DIAG_KEEP,
    get_connection,
    init_db,
    insert_panel_diag,
    list_panel_diag,
)

SECRET = "s3cr3t-key"
PW = "test-admin-pw"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    settings = SimpleNamespace(
        DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD=PW,
        SSO_SECRET="shared-forum-secret", FORUM_SSO_URL="https://board.friesenflieger.de/sso.php",
        FORUM_SSO_CALLBACK="https://friesenspy.devprops.de/auth/forum/callback",
        USER_SESSION_MAX_AGE_SEC=3600, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main._reset_gate_cache()
    return SimpleNamespace(client=TestClient(main.app), db=p, settings=settings)


def _admin_cookie() -> dict:
    return {
        "fs_admin": make_admin_token(SECRET, PW),
        "fs_confirm": make_confirm_token(SECRET, PW, 9_999_999_999),
    }


class TestPanelDiagEndpoint:
    def test_nimmt_bericht_an_und_speichert(self, env):
        r = env.client.post("/api/panel-diag", json={
            "kind": "report", "appVersion": "v9.9.9",
            "css": {"maxContent": False}, "glyphs": {"chars": {"ae": {"missing": True}}},
        })
        assert r.status_code == 200

        conn = get_connection(env.db)
        try:
            rows = list_panel_diag(conn)
        finally:
            conn.close()
        assert len(rows) == 1
        assert rows[0]["kind"] == "report"
        assert rows[0]["app_version"] == "v9.9.9"
        payload = json.loads(rows[0]["payload_json"])
        assert payload["css"]["maxContent"] is False

    def test_ohne_anmeldung_erreichbar_auch_bei_aktivem_gate(self, env):
        """Kernanforderung: Gerade wenn der Login im Panel klemmt, müssen Messwerte ankommen."""
        env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
        main._reset_gate_cache()

        # Gegenprobe: eine normale Seite ist jetzt gesperrt ...
        blocked = env.client.get("/panel", headers={"accept": "text/html"}, follow_redirects=False)
        assert blocked.status_code == 302

        # ... die Diagnose aber weiterhin offen.
        r = env.client.post("/api/panel-diag", json={"kind": "report"})
        assert r.status_code == 200

    def test_lehnt_ungueltiges_json_ab(self, env):
        r = env.client.post("/api/panel-diag", content=b"kein json",
                            headers={"Content-Type": "application/json"})
        assert r.status_code == 400

    def test_lehnt_nicht_objekt_ab(self, env):
        r = env.client.post("/api/panel-diag", json=["liste", "statt", "objekt"])
        assert r.status_code == 400

    def test_lehnt_uebergrossen_datensatz_ab(self, env):
        """Der Endpunkt ist gate-frei -- ohne Größendeckel wäre er ein Einfallstor."""
        huge = json.dumps({"kind": "report", "junk": "x" * (main._PANEL_DIAG_MAX_BYTES + 100)})
        r = env.client.post("/api/panel-diag", content=huge.encode(),
                            headers={"Content-Type": "application/json"})
        assert r.status_code == 413


class TestPanelDiagAdmin:
    def test_lesen_nur_mit_admin(self, env):
        env.client.post("/api/panel-diag", json={"kind": "report"})
        assert env.client.get("/api/admin/panel-diag").status_code == 401

        r = env.client.get("/api/admin/panel-diag", cookies=_admin_cookie())
        assert r.status_code == 200
        assert len(r.json()["entries"]) == 1

    def test_loeschen_nur_mit_admin(self, env):
        env.client.post("/api/panel-diag", json={"kind": "report"})
        assert env.client.delete("/api/admin/panel-diag").status_code == 401

        assert env.client.request("DELETE", "/api/admin/panel-diag",
                                  cookies=_admin_cookie()).status_code == 200
        r = env.client.get("/api/admin/panel-diag", cookies=_admin_cookie())
        assert r.json()["entries"] == []


class TestPanelDiagPruning:
    def test_haelt_nur_die_neuesten_eintraege(self, env):
        """Ohne Deckel würde ein Panel in einer Fehlerschleife die DB vollschreiben."""
        conn = get_connection(env.db)
        try:
            for i in range(PANEL_DIAG_KEEP + 15):
                insert_panel_diag(conn, kind="report", payload_json=json.dumps({"n": i}))
            conn.commit()
            rows = list_panel_diag(conn, limit=PANEL_DIAG_KEEP + 50)
            assert len(rows) == PANEL_DIAG_KEEP
            # Die neuesten müssen überlebt haben, nicht die ältesten.
            assert json.loads(rows[0]["payload_json"])["n"] == PANEL_DIAG_KEEP + 14
        finally:
            conn.close()
