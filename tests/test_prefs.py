"""Karten-Merker auf dem Server (/api/prefs, ab v13.6.3).

Hintergrund und Begründung, warum sie NICHT im Browser liegen: Im MSFS-Kniebrett hält kein
Browser-Speicher über einen Sim-Neustart. Gemessen am 16.08.2026 über einen Neustart hinweg
(`speicher`-Block im Panel-Bericht): ``localStorage`` fällt von 8 Schlüsseln auf 0, das
Merker-Cookie ist fort. Zwei Anläufe -- localStorage, dann ein Cookie -- sind daran
gescheitert, obwohl in `panel_devices` und in der EFB-Shell längst dokumentiert stand, dass
Coherent GT Cookies nur im Speicher hält.

Was dort überlebt, ist MSFS' eigene Ablage (``SetStoredData``) mit der Geräte-ID -- derselbe
Weg, den auch Avionik wie das GTN 750 geht. Über sie bekommt das Panel bei jedem Start ein
frisches Sitzungs-Cookie, und daran hängen diese Merker.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.database import get_connection, get_panel_prefs, init_db, set_panel_prefs
from app.forum_sso import USER_COOKIE, make_user_token

SECRET = "s3cr3t-key"
CID = 1602713


@pytest.fixture()
def env(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    settings = SimpleNamespace(
        DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD="pw",
        SSO_SECRET="shared-forum-secret", FORUM_SSO_URL="", FORUM_SSO_CALLBACK="",
        USER_SESSION_MAX_AGE_SEC=1200, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main._reset_gate_cache()
    return SimpleNamespace(client=TestClient(main.app), db=p)


def _cookie(cid: int = CID) -> dict:
    return {USER_COOKIE: make_user_token(SECRET, "Tobias", str(cid), False, time.time() + 3600)}


# ---------------------------------------------------------------------------------------
#  Endpunkt
# ---------------------------------------------------------------------------------------

class TestEndpunkt:
    def test_ohne_anmeldung_leere_merker_statt_fehler(self, env):
        """Die Karte soll dann mit ihren Vorgaben aufgehen, nicht mit einem Fehler."""
        r = env.client.get("/api/prefs?kontext=web")
        assert r.status_code == 200
        assert r.json() == {"prefs": {}}

    def test_schreiben_ohne_anmeldung_wird_abgelehnt(self, env):
        r = env.client.put("/api/prefs?kontext=web", json={"prefs": {"friesenspy_layer": "dark"}})
        assert r.status_code == 401

    def test_hin_und_zurueck(self, env):
        c = _cookie()
        r = env.client.put("/api/prefs?kontext=panel",
                           json={"prefs": {"friesenspy_layer": "dark", "friesenspy_aip": "1"}},
                           cookies=c)
        assert r.status_code == 200 and r.json()["anzahl"] == 2
        r = env.client.get("/api/prefs?kontext=panel", cookies=c)
        assert r.json()["prefs"] == {"friesenspy_layer": "dark", "friesenspy_aip": "1"}

    def test_kniebrett_und_website_stoeren_sich_nicht(self, env):
        """Der Kartenwechsel am Schreibtisch darf nicht die Karte im Cockpit umstellen."""
        c = _cookie()
        env.client.put("/api/prefs?kontext=panel", json={"prefs": {"friesenspy_layer": "dark"}},
                       cookies=c)
        env.client.put("/api/prefs?kontext=web", json={"prefs": {"friesenspy_layer": "sat"}},
                       cookies=c)
        assert env.client.get("/api/prefs?kontext=panel", cookies=c).json()["prefs"] == \
            {"friesenspy_layer": "dark"}
        assert env.client.get("/api/prefs?kontext=web", cookies=c).json()["prefs"] == \
            {"friesenspy_layer": "sat"}

    def test_zwei_nutzer_teilen_sich_nichts(self, env):
        env.client.put("/api/prefs?kontext=panel", json={"prefs": {"friesenspy_layer": "dark"}},
                       cookies=_cookie(CID))
        r = env.client.get("/api/prefs?kontext=panel", cookies=_cookie(1642160))
        assert r.json()["prefs"] == {}

    def test_unbekannter_kontext_legt_keine_neue_zeile_an(self, env):
        """Sonst könnte ein Aufrufer beliebig viele Zeilen je CID erzeugen."""
        c = _cookie()
        env.client.put("/api/prefs?kontext=phantasie", json={"prefs": {"a": "1"}}, cookies=c)
        conn = get_connection(env.db)
        try:
            zeilen = conn.execute("SELECT kontext FROM panel_prefs").fetchall()
        finally:
            conn.close()
        assert [z["kontext"] for z in zeilen] == ["web"]

    def test_schreiben_ersetzt_statt_zu_ergaenzen(self, env):
        """Das Frontend schickt immer den vollständigen Stand -- ein Merker, den der Nutzer
        abwählt, muss dadurch verschwinden können."""
        c = _cookie()
        env.client.put("/api/prefs?kontext=web",
                       json={"prefs": {"a": "1", "b": "1"}}, cookies=c)
        env.client.put("/api/prefs?kontext=web", json={"prefs": {"a": "1"}}, cookies=c)
        assert env.client.get("/api/prefs?kontext=web", cookies=c).json()["prefs"] == {"a": "1"}


class TestGrenzen:
    def test_zu_viele_merker(self, env):
        viele = {f"k{i}": "1" for i in range(main._PREFS_MAX_SCHLUESSEL + 1)}
        r = env.client.put("/api/prefs?kontext=web", json={"prefs": viele}, cookies=_cookie())
        assert r.status_code == 400

    def test_zu_langer_wert(self, env):
        lang = {"a": "x" * (main._PREFS_MAX_LAENGE + 1)}
        r = env.client.put("/api/prefs?kontext=web", json={"prefs": lang}, cookies=_cookie())
        assert r.status_code == 400

    def test_verschachtelte_werte_abgelehnt(self, env):
        r = env.client.put("/api/prefs?kontext=web",
                           json={"prefs": {"a": {"b": 1}}}, cookies=_cookie())
        assert r.status_code == 400

    def test_prefs_muss_ein_objekt_sein(self, env):
        r = env.client.put("/api/prefs?kontext=web", json={"prefs": [1, 2]}, cookies=_cookie())
        assert r.status_code == 400

    def test_zahlen_werden_zu_zeichenketten(self, env):
        """Das Frontend schickt '1'/'0'; ein durchgerutschtes int darf nicht später beim
        Vergleich mit '1' still danebenliegen."""
        c = _cookie()
        env.client.put("/api/prefs?kontext=web", json={"prefs": {"a": 1}}, cookies=c)
        assert env.client.get("/api/prefs?kontext=web", cookies=c).json()["prefs"] == {"a": "1"}


class TestDatenbank:
    def test_beschaedigtes_json_gilt_als_leer(self, env):
        """Ein kaputter Eintrag darf nicht dazu führen, dass die Karte gar nicht aufgeht."""
        conn = get_connection(env.db)
        try:
            conn.execute(
                "INSERT INTO panel_prefs (cid, kontext, prefs_json, updated_at) "
                "VALUES (?, ?, ?, ?)", (CID, "web", "{kaputt", "2026-08-16T00:00:00Z"))
            conn.commit()
            assert get_panel_prefs(conn, CID, "web") == {}
        finally:
            conn.close()

    def test_liste_statt_objekt_gilt_als_leer(self, env):
        conn = get_connection(env.db)
        try:
            set_panel_prefs(conn, CID, "web", {"a": "1"})
            conn.execute("UPDATE panel_prefs SET prefs_json = ?", (json.dumps([1, 2]),))
            conn.commit()
            assert get_panel_prefs(conn, CID, "web") == {}
        finally:
            conn.close()

    def test_ohne_eintrag_leeres_dict(self, env):
        conn = get_connection(env.db)
        try:
            assert get_panel_prefs(conn, 999, "panel") == {}
        finally:
            conn.close()


# ---------------------------------------------------------------------------------------
#  Paketfassung am Gerät (v13.6.5)
# ---------------------------------------------------------------------------------------

class TestPaketVersionAmGeraet:
    @pytest.mark.parametrize("roh,erwartet", [
        ("1.10.0", "1.10.0"), ("1.9", "1.9"), ("1", "1"), ("1.2.3.4", "1.2.3.4"),
        ("", None), ("  ", None), ("1.2.3.4.5", None), ("abc", None),
        ("1.2.3; DROP TABLE", None), ("<script>", None), ("1234", None),
        ("١٢٣", None),   # arabisch-indische Ziffern -- isdigit() allein sagt hier True
    ])
    def test_nur_eine_versionsnummer_wird_uebernommen(self, roh, erwartet):
        assert main._paket_version_saeubern(roh) == erwartet

    @pytest.mark.parametrize("installiert,aktuell,erwartet", [
        ("1.9.0", "2.0.0", True),
        ("2.0.0", "2.0.0", False),
        ("2.1.0", "2.0.0", False),
        (None, "2.0.0", True),      # meldet nichts -> aelter als 2.0.0
        (None, "1.9.0", False),     # noch keine meldende Fassung ausgeliefert -> keine Aussage
        (None, None, False),
        ("1.2.0", None, False),
    ])
    def test_veraltet_spiegelt_das_frontend(self, installiert, aktuell, erwartet):
        assert main._paket_ist_veraltet(installiert, aktuell) is erwartet

    def test_zahlenvergleich_nicht_zeichenkette(self):
        """'1.10.0' ist als Zeichenkette KLEINER als '1.9.0'."""
        assert main._version_kleiner("1.9.0", "1.10.0") is True
        assert main._version_kleiner("1.10.0", "1.9.0") is False

    def test_kaputte_version_wirft_nicht(self):
        assert main._version_kleiner("kaputt", "1.0.0") is True
        assert main._version_kleiner(None, None) is False

    def test_admin_liefert_die_paketfassung_mit(self, env, monkeypatch):
        from app.database import bind_panel_device, touch_panel_device
        conn = get_connection(env.db)
        try:
            bind_panel_device(conn, "d" * 48, CID, "Tobias")
            touch_panel_device(conn, "d" * 48, "1.9.0")
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setattr(main, "_efb_package_version", lambda p: "2.0.0")
        from app.auth import make_admin_token, make_confirm_token
        r = env.client.get("/api/admin/panel-devices", cookies={
            "fs_admin": make_admin_token(SECRET, "pw"),
            "fs_confirm": make_confirm_token(SECRET, "pw", 9_999_999_999),
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["paket_aktuell"] == "2.0.0"
        assert d["devices"][0]["paket_version"] == "1.9.0"
        assert d["devices"][0]["paket_veraltet"] is True

    def test_fehlende_meldung_ueberschreibt_den_letzten_stand_nicht(self, env):
        """Ein Paket vor 2.0.0 meldet nichts. Den bekannten Wert daraufhin zu leeren, waere
        ein Rueckschritt -- der zuletzt bekannte Stand ist die bessere Auskunft."""
        from app.database import bind_panel_device, get_panel_device, touch_panel_device
        conn = get_connection(env.db)
        try:
            bind_panel_device(conn, "e" * 48, CID, "Tobias")
            touch_panel_device(conn, "e" * 48, "2.0.0")
            touch_panel_device(conn, "e" * 48, None)
            conn.commit()
            assert get_panel_device(conn, "e" * 48)["paket_version"] == "2.0.0"
        finally:
            conn.close()
