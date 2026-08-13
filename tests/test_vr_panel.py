"""Tests für den VR-Panel-Modus (/panel) — Web-Vorbereitung für ein separat gebautes
MSFS-2024-EFB-Panel (s. docs/superpowers/specs/2026-08-11-vr-panel-modus-design.md).

Für Vanilla-JS/CSS gibt es in diesem Projekt keinen Testläufer -- die Skalierungs-Tests
greifen deshalb wie tests/test_aircraft_ui_static.py auf den Quelltext zu.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import make_admin_token, make_confirm_token
from app.database import init_db

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

SECRET = "s3cr3t-key"
PW = "test-admin-pw"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    # Minimaler Zwilling des env-Fixtures aus tests/test_forum_sso_api.py — reicht hier, weil
    # wir nur Routing (/panel) + Gate brauchen, keinen vollen SSO-Roundtrip.
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
    client = TestClient(main.app)
    return SimpleNamespace(client=client, db=p, settings=settings)


def _admin_cookie() -> dict:
    return {
        "fs_admin": make_admin_token(SECRET, PW),
        "fs_confirm": make_confirm_token(SECRET, PW, 9_999_999_999),
    }


def test_panel_liefert_dieselbe_datei_wie_index():
    """/panel MUSS exakt dieselbe Response wie / liefern -- keine zweite HTML-Datei, keine
    Duplikation (s. Global Constraints). Mit aktuellem v= -- sonst liefert panel() den
    Cache-Bust-Redirect (s. test_panel_ohne_oder_mit_alter_version_leitet_um)."""
    index_resp = asyncio.run(main.index())
    panel_resp = asyncio.run(main.panel(v=main.VERSION))
    assert panel_resp.path == index_resp.path
    assert dict(panel_resp.headers) == dict(index_resp.headers)


def test_panel_ohne_oder_mit_alter_version_leitet_um():
    """Cache-Bust-Fix (Live-Test-Fund 13.08.2026): Coherent GT hat sich als unzuverlässig beim
    Befolgen von Cache-Control erwiesen -- /panel ohne oder mit veraltetem v= muss auf die
    aktuelle, garantiert noch nie angefragte, versionierte URL umleiten statt den (potenziell
    gecachten) Inhalt direkt auszuliefern."""
    resp_ohne = asyncio.run(main.panel(v=None))
    assert resp_ohne.status_code == 302
    assert resp_ohne.headers["location"] == f"/panel?v={main.VERSION}"

    resp_alt = asyncio.run(main.panel(v="0.0.1"))
    assert resp_alt.status_code == 302
    assert resp_alt.headers["location"] == f"/panel?v={main.VERSION}"


def test_vr_panel_klasse_wird_bei_panel_pfad_und_query_gesetzt():
    """Beide Aktivierungswege müssen im Quelltext stehen -- /panel (Task 1) UND ?vr=1
    (Design-Entscheidung: gleichwertiger Trigger auch ohne Pfadwechsel)."""
    assert "location.pathname === '/panel'" in INDEX
    assert "qs.get('vr') === '1'" in INDEX
    assert "classList.add('vr-panel')" in INDEX


def test_vr_panel_css_skaliert_alles_gemeinsam():
    """zoom (nicht nur font-size!) -- Innenabstände/Buttons sind im Rest der Seite
    überwiegend feste px-Werte, s. Design-Doku 'Warum eine reine Schriftgrößen-Anpassung
    nicht reicht'."""
    assert re.search(r"html\.vr-panel\s*\{[^}]*zoom:\s*1\.35", INDEX)
    assert re.search(r"html\.vr-panel body\s*\{[^}]*font-weight:\s*400", INDEX)


def test_panel_route_ist_wirklich_unter_slash_panel_registriert(env):
    """Echter Request über TestClient/Routing statt Direktaufruf von main.panel() -- ein
    Tippfehler im @app.get("/panel")-Pfad (den auch die JS-Erkennung in index.html prüft)
    würde hier auffallen, im alten Direktaufruf-Test dagegen nicht. Mit aktuellem v=, sonst
    Redirect statt 200 (s. Cache-Bust-Fix)."""
    r = env.client.get(f"/panel?v={main.VERSION}", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 200
    assert "vr-panel" in r.text  # dieselbe Seite wie /, samt VR-Erkennungs-Skript


def test_panel_route_leitet_ueber_echten_http_request_um(env):
    """Cache-Bust-Redirect auch über den echten Routing-Pfad (TestClient), nicht nur bei
    Direktaufruf von main.panel() -- deckt z. B. ab, dass FastAPI den v-Query-Parameter
    tatsächlich an die Handler-Signatur durchreicht."""
    r = env.client.get("/panel", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == f"/panel?v={main.VERSION}"


def test_panel_bleibt_hinter_dem_login_gate(env):
    """Design-Entscheidung 'kein öffentlicher Zugang' -- bei aktivem Gate muss /panel wie jede
    andere Seite zum Login umleiten. Eine künftige Erweiterung von _GATE_ALLOW_PREFIXES um
    "/panel" würde diesen Test brechen."""
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    r = env.client.get("/panel", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("/auth/forum/login")
    assert loc == "/auth/forum/login?next=%2Fpanel"
