"""Tests für die Geräte-Bindung des EFB-Panels (/auth/device).

Hintergrund: Coherent GT (die Engine im MSFS-EFB-Panel) hält Cookies offenbar nur im
Speicher -- die Anmeldung ging bei jedem Simulator-Neustart verloren, teils schon nach
Minuten. Das EFB-Paket legt deshalb eine Zufalls-Geräte-ID in MSFS' plattenpersistentem
Speicher ab und weist sich damit aus.

Die Geräte-ID ist ein Zugangsschlüssel -- wer sie hat, ist als der gebundene Nutzer
angemeldet. Entsprechend prüfen diese Tests nicht nur den Erfolgsfall, sondern vor allem die
Grenzen: zu kurze IDs, unbekannte Geräte, Widerruf.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import make_admin_token, make_confirm_token
from app.database import (
    PANEL_DEVICE_MIN_LEN,
    bind_panel_device,
    get_connection,
    get_panel_device,
    init_db,
    list_panel_devices,
    revoke_panel_device,
)
from app.forum_sso import USER_COOKIE, verify_user_token

SECRET = "s3cr3t-key"
PW = "test-admin-pw"
GERAET = "d" * 48          # gültige Länge
KURZ = "abc123"            # zu kurz -> muss abgelehnt werden
CID = 1602713


@pytest.fixture()
def env(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    settings = SimpleNamespace(
        DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD=PW,
        SSO_SECRET="shared-forum-secret", FORUM_SSO_URL="https://board.friesenflieger.de/sso.php",
        FORUM_SSO_CALLBACK="https://friesenspy.devprops.de/auth/forum/callback",
        USER_SESSION_MAX_AGE_SEC=1200, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main._reset_gate_cache()
    return SimpleNamespace(client=TestClient(main.app), db=p, settings=settings)


def _admin_cookie() -> dict:
    return {
        "fs_admin": make_admin_token(SECRET, PW),
        "fs_confirm": make_confirm_token(SECRET, PW, 9_999_999_999),
    }


def _bind(db: str, device: str = GERAET, cid: int = CID, name: str = "Tobias EDKB") -> bool:
    conn = get_connection(db)
    try:
        ok = bind_panel_device(conn, device, cid, name)
        conn.commit()
        return ok
    finally:
        conn.close()


class TestDatenbank:
    def test_bindet_und_findet_geraet(self, env):
        assert _bind(env.db) is True
        conn = get_connection(env.db)
        try:
            dev = get_panel_device(conn, GERAET)
        finally:
            conn.close()
        assert dev is not None
        assert dev["cid"] == CID

    def test_lehnt_zu_kurze_id_ab(self, env):
        """Die ID entsteht im EFB-Paket, also außerhalb unserer Kontrolle -- eine ratbar
        kurze ID darf gar nicht erst gebunden werden."""
        assert _bind(env.db, device=KURZ) is False
        conn = get_connection(env.db)
        try:
            assert get_panel_device(conn, KURZ) is None
            assert list_panel_devices(conn) == []
        finally:
            conn.close()

    def test_unbekanntes_geraet_ist_none(self, env):
        conn = get_connection(env.db)
        try:
            assert get_panel_device(conn, "x" * 48) is None
        finally:
            conn.close()

    def test_widerruf_entfernt_bindung(self, env):
        _bind(env.db)
        conn = get_connection(env.db)
        try:
            revoke_panel_device(conn, GERAET)
            conn.commit()
            assert get_panel_device(conn, GERAET) is None
        finally:
            conn.close()

    def test_bindung_an_fremde_cid_wird_abgelehnt(self, env):
        """Ein stilles Überschreiben wäre ein Übernahme-Weg: Wer eine fremde Geräte-ID kennt,
        könnte sie sonst auf sich umbiegen. Wechselt der Simulator wirklich den Besitzer,
        hebt ein Widerruf im Admin die alte Bindung auf."""
        assert _bind(env.db, cid=111) is True
        assert _bind(env.db, cid=222) is False
        conn = get_connection(env.db)
        try:
            assert get_panel_device(conn, GERAET)["cid"] == 111   # unverändert
            assert len(list_panel_devices(conn)) == 1
        finally:
            conn.close()

    def test_erneute_bindung_derselben_cid_ist_erlaubt(self, env):
        """Dasselbe Gerät, derselbe Nutzer -- z. B. nach einem Widerruf und Neu-Anmelden."""
        assert _bind(env.db, cid=CID) is True
        assert _bind(env.db, cid=CID) is True


class TestAuthDeviceEndpunkt:
    def test_bekanntes_geraet_meldet_ohne_login_an(self, env):
        _bind(env.db)
        r = env.client.get(f"/auth/device?device={GERAET}", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/panel"

        token = r.cookies.get(USER_COOKIE)
        assert token, "Sitzungs-Cookie muss gesetzt sein"
        claims = verify_user_token(token, SECRET)
        assert claims is not None
        assert str(claims["cid"]) == str(CID)

    def test_zieladresse_enthaelt_die_geraete_id_nicht_mehr(self, env):
        """Der Schlüssel darf nicht in der finalen Adresse (und damit im Verlauf) landen."""
        _bind(env.db)
        r = env.client.get(f"/auth/device?device={GERAET}", follow_redirects=False)
        assert GERAET not in r.headers["location"]

    def test_unbekanntes_geraet_geht_in_den_login(self, env):
        r = env.client.get(f"/auth/device?device={'z' * 48}", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].startswith("/auth/forum/login")
        assert not r.cookies.get(USER_COOKIE)
        # Es darf NICHTS gemerkt werden -- ein gemerktes Gerät wäre der Fixierungs-Weg.
        assert not r.cookies.get("fs_dev_bind")

    def test_zu_kurze_id_meldet_nicht_an(self, env):
        r = env.client.get(f"/auth/device?device={KURZ}", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].startswith("/auth/forum/login")
        assert not r.cookies.get(USER_COOKIE)

    def test_ohne_geraet_normaler_login(self, env):
        r = env.client.get("/auth/device", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].startswith("/auth/forum/login")
        assert not r.cookies.get(USER_COOKIE)

    def test_widerrufenes_geraet_meldet_nicht_mehr_an(self, env):
        _bind(env.db)
        conn = get_connection(env.db)
        try:
            revoke_panel_device(conn, GERAET)
            conn.commit()
        finally:
            conn.close()
        r = env.client.get(f"/auth/device?device={GERAET}", follow_redirects=False)
        assert r.headers["location"].startswith("/auth/forum/login")
        assert not r.cookies.get(USER_COOKIE)

    def test_kein_open_redirect(self, env):
        """`next` darf nur seitenintern sein -- sonst wäre der Endpunkt ein Sprungbrett."""
        _bind(env.db)
        r = env.client.get(f"/auth/device?device={GERAET}&next=https://boese.example/",
                           follow_redirects=False)
        assert r.headers["location"] == "/panel"

    def test_erreichbar_trotz_aktivem_login_gate(self, env):
        """Sonst käme man mit einem gebundenen Gerät nie an der Sperre vorbei."""
        env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
        main._reset_gate_cache()
        _bind(env.db)
        r = env.client.get(f"/auth/device?device={GERAET}", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/panel"
        assert r.cookies.get(USER_COOKIE)


class TestBindungNurMitBestaetigung:
    """Die Bindung ist der sicherheitskritische Schritt -- hier liegt der Schwerpunkt.

    Ein früherer Entwurf band automatisch, sobald nach dem Login ein Geräte-Cookie vorlag.
    Das war eine Session-Fixierung: Ein untergeschobener Link mit der Geräte-ID des
    Angreifers hätte diese an die CID des Opfers gebunden -- der Angreifer wäre dauerhaft als
    das Opfer angemeldet gewesen. Dass die ID schwer zu raten ist, half nicht: Der Angreifer
    wählt sie selbst.
    """

    def _login(self, env, cid: int = CID, name: str = "Tobias EDKB") -> str:
        """Sitzungs-Cookie wie nach einem Forum-Login setzen."""
        import time as _t
        from app.forum_sso import make_user_token
        token = make_user_token(SECRET, name, str(cid), False, _t.time() + 3600)
        env.client.cookies.set(USER_COOKIE, token)
        return token

    def test_angemeldet_und_unbekannt_zeigt_bestaetigung_statt_zu_binden(self, env):
        self._login(env)
        r = env.client.get(f"/auth/device?device={GERAET}", follow_redirects=False)
        assert r.status_code == 200
        assert "Dieses Gerät dauerhaft anmelden?" in r.text
        # Entscheidend: Das blosse Aufrufen bindet NICHT.
        conn = get_connection(env.db)
        try:
            assert get_panel_device(conn, GERAET) is None
        finally:
            conn.close()

    def test_bindung_mit_gueltiger_marke(self, env):
        token = self._login(env)
        marke = main._device_bind_csrf(token)
        r = env.client.post("/auth/device/bind",
                            data={"device": GERAET, "next": "/panel", "csrf": marke},
                            follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/panel"
        conn = get_connection(env.db)
        try:
            assert get_panel_device(conn, GERAET)["cid"] == CID
        finally:
            conn.close()

    def test_bindung_ohne_marke_abgelehnt(self, env):
        """Das Sitzungs-Cookie trägt SameSite=None (nötig fürs iframe) und würde bei einem
        seitenfremden POST mitgeschickt -- die Marke ist der eigentliche Schutz."""
        self._login(env)
        r = env.client.post("/auth/device/bind",
                            data={"device": GERAET, "next": "/panel", "csrf": "falsch"},
                            follow_redirects=False)
        assert r.status_code == 403
        conn = get_connection(env.db)
        try:
            assert get_panel_device(conn, GERAET) is None
        finally:
            conn.close()

    def test_bindung_ohne_anmeldung_abgelehnt(self, env):
        r = env.client.post("/auth/device/bind",
                            data={"device": GERAET, "next": "/panel", "csrf": "egal"},
                            follow_redirects=False)
        assert r.status_code == 401

    def test_marke_eines_anderen_nutzers_greift_nicht(self, env):
        """Die Marke ist an die konkrete Sitzung gebunden, nicht global gültig."""
        fremd = self._login(env, cid=999, name="Fremd")
        fremde_marke = main._device_bind_csrf(fremd)
        eigen = self._login(env, cid=CID)
        assert fremde_marke != main._device_bind_csrf(eigen)
        r = env.client.post("/auth/device/bind",
                            data={"device": GERAET, "next": "/panel", "csrf": fremde_marke},
                            follow_redirects=False)
        assert r.status_code == 403

    def test_fremdes_geraet_kann_nicht_uebernommen_werden(self, env):
        """Wer eine fremde Geräte-ID kennt, darf sie nicht auf sich umbiegen können."""
        _bind(env.db, cid=111)                      # gehört jemand anderem
        token = self._login(env, cid=222)
        r = env.client.post("/auth/device/bind",
                            data={"device": GERAET, "next": "/panel",
                                  "csrf": main._device_bind_csrf(token)},
                            follow_redirects=False)
        assert r.status_code == 409
        conn = get_connection(env.db)
        try:
            assert get_panel_device(conn, GERAET)["cid"] == 111   # unverändert
        finally:
            conn.close()

    def test_login_bindet_nichts_automatisch(self, env):
        """Kernschutz gegen die Fixierung: Der Login-Callback darf NIE binden."""
        env.client.cookies.set("fs_dev_bind", GERAET)
        self._login(env)
        conn = get_connection(env.db)
        try:
            assert get_panel_device(conn, GERAET) is None
        finally:
            conn.close()

    def test_kein_open_redirect_beim_binden(self, env):
        token = self._login(env)
        r = env.client.post("/auth/device/bind",
                            data={"device": GERAET, "next": "https://boese.example/",
                                  "csrf": main._device_bind_csrf(token)},
                            follow_redirects=False)
        assert r.headers["location"] == "/panel"


class TestAdminGeraete:
    def test_liste_nur_mit_admin_und_ohne_vollen_schluessel(self, env):
        _bind(env.db)
        assert env.client.get("/api/admin/panel-devices").status_code == 401

        r = env.client.get("/api/admin/panel-devices", cookies=_admin_cookie())
        assert r.status_code == 200
        devices = r.json()["devices"]
        assert len(devices) == 1
        assert devices[0]["cid"] == CID
        # Der Zugangsschlüssel darf nicht vollständig in einer Übersicht auftauchen.
        assert "device_id" not in devices[0]
        assert devices[0]["device_prefix"] == GERAET[:12]
        assert len(devices[0]["device_prefix"]) < PANEL_DEVICE_MIN_LEN

    def test_widerruf_nur_mit_admin(self, env):
        _bind(env.db)
        assert env.client.delete(f"/api/admin/panel-devices/{GERAET[:12]}").status_code == 401

        r = env.client.request("DELETE", f"/api/admin/panel-devices/{GERAET[:12]}",
                               cookies=_admin_cookie())
        assert r.status_code == 200
        assert r.json()["revoked"] == 1

        # Danach meldet das Gerät nicht mehr an.
        r2 = env.client.get(f"/auth/device?device={GERAET}", follow_redirects=False)
        assert r2.headers["location"].startswith("/auth/forum/login")

    def test_widerruf_lehnt_zu_kurzes_praefix_ab(self, env):
        """Sonst könnte ein sehr kurzes Präfix versehentlich mehrere Geräte treffen."""
        _bind(env.db)
        r = env.client.request("DELETE", "/api/admin/panel-devices/dd", cookies=_admin_cookie())
        assert r.status_code == 400

    def test_widerruf_unbekannt_ist_404(self, env):
        r = env.client.request("DELETE", "/api/admin/panel-devices/qqqqqqqqqqqq",
                               cookies=_admin_cookie())
        assert r.status_code == 404
