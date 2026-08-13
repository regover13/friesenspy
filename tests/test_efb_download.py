"""Tests für die Verteilung der MSFS-EFB-App (Release „Kniebrett").

Das fertige Community-Package liegt bewusst NICHT im Docker-Image: es entsteht aus einem
Windows-Build (esbuild + MSFSLayoutGenerator.exe) und wäre in der Linux-CI nicht
reproduzierbar. Es wird pro EFB-Release einmal ins Volume gelegt. Diese Tests sichern das
Verhalten drumherum ab — vor allem, dass eine FEHLENDE Datei sauber gemeldet wird statt
die Seite mitzureißen.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import make_admin_token, make_confirm_token
from app.database import init_db

SECRET = "s3cr3t-key"
PW = "test-admin-pw"


def _paket_bauen(ziel: Path, version: str = "1.0.0") -> Path:
    """Minimales, aber strukturell echtes Community-Package."""
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ziel, "w") as z:
        z.writestr(
            "friesenflieger-friesenspy-efb/manifest.json",
            json.dumps({"title": "FriesenSpy", "package_version": version}),
        )
        z.writestr(
            "friesenflieger-friesenspy-efb/html_ui/efb_ui/efb_apps/FriesenSpy/FriesenSpy.js",
            "// nur Fuellmaterial",
        )
    return ziel


@pytest.fixture()
def env(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    settings = SimpleNamespace(
        DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD=PW,
        SSO_SECRET="shared-forum-secret", FORUM_SSO_URL="https://board.friesenflieger.de/sso.php",
        FORUM_SSO_CALLBACK="https://friesenspy.devprops.de/auth/forum/callback",
        USER_SESSION_MAX_AGE_SEC=3600, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
        EFB_PACKAGE_PATH="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main._reset_gate_cache()
    return SimpleNamespace(client=TestClient(main.app), settings=settings, tmp=tmp_path)


def _admin_cookie() -> dict:
    return {
        "fs_admin": make_admin_token(SECRET, PW),
        "fs_confirm": make_confirm_token(SECRET, PW, 9_999_999_999),
    }


def test_standardablage_liegt_neben_der_datenbank(env):
    """Das Volume ist der einzige Ort, der einen Deploy überlebt — das Image wird bei jedem
    Release ersetzt."""
    pfad = main._efb_zip_path(env.settings)
    assert pfad.parent.parent == Path(env.settings.DB_PATH).parent
    assert pfad.name == "friesenspy-efb.zip"


def test_eigener_pfad_hat_vorrang(env):
    env.settings.EFB_PACKAGE_PATH = str(env.tmp / "woanders" / "x.zip")
    assert main._efb_zip_path(env.settings) == Path(env.tmp / "woanders" / "x.zip")


def test_ohne_paket_meldet_die_seite_das_sauber(env):
    """Kein Paket hinterlegt darf keine Fehlerseite ergeben — die Installationsseite soll
    dann schlicht sagen, dass gerade nichts da ist."""
    r = env.client.get("/api/efb-package")
    assert r.status_code == 200
    assert r.json() == {"verfuegbar": False}


def test_ohne_paket_gibt_der_download_404(env):
    r = env.client.get("/download/efb")
    assert r.status_code == 404


def test_mit_paket_kommt_version_und_groesse(env):
    _paket_bauen(main._efb_zip_path(env.settings), version="1.2.3")
    d = env.client.get("/api/efb-package").json()
    assert d["verfuegbar"] is True
    assert d["version"] == "1.2.3"
    assert d["groesse_kb"] >= 0
    assert len(d["stand"].split(".")) == 3  # TT.MM.JJJJ


def test_version_kommt_aus_dem_archiv_selbst(env):
    """Bewusst aus der manifest.json IM ZIP statt aus einer Begleitdatei: sonst kann die
    angezeigte Version von der ausgelieferten abweichen, und niemand merkt es."""
    pfad = main._efb_zip_path(env.settings)
    _paket_bauen(pfad, version="9.9.9")
    assert main._efb_package_version(pfad) == "9.9.9"


def test_kaputtes_archiv_reisst_die_seite_nicht_mit(env):
    """Eine halb hochgeladene Datei darf höchstens die Versionsangabe kosten."""
    pfad = main._efb_zip_path(env.settings)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(b"kein zip")
    assert main._efb_package_version(pfad) is None
    d = env.client.get("/api/efb-package").json()
    assert d["verfuegbar"] is True
    assert d["version"] is None


def test_download_liefert_das_zip_unter_sprechendem_namen(env):
    """Der Dateiname landet beim Nutzer im Download-Ordner und ist zugleich der Ordnername,
    den er in Community kopiert -- er muss also passen."""
    _paket_bauen(main._efb_zip_path(env.settings))
    r = env.client.get("/download/efb")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "friesenflieger-friesenspy-efb.zip" in r.headers["content-disposition"]
    assert zipfile.ZipFile(__import__("io").BytesIO(r.content)).namelist()


def test_seite_und_download_liegen_hinter_dem_gate(env):
    """Beides gehört den Mitgliedern. /static/ ist gate-frei — deshalb liegt die Seite
    bewusst unter /efb und nicht unter /static/efb.html."""
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    for pfad in ("/efb", "/download/efb", "/api/efb-package"):
        r = env.client.get(pfad, headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code in (302, 401), f"{pfad} ist nicht geschützt: {r.status_code}"


def test_installationsseite_wird_ausgeliefert(env):
    r = env.client.get("/efb", headers={"accept": "text/html"})
    assert r.status_code == 200
    assert "Kniebrett" in r.text
    assert "/download/efb" in r.text


def test_installationsseite_nennt_beide_community_pfade():
    """Store- und Steam-Installation legen den Community-Ordner woanders ab — wer nur einen
    Pfad nennt, produziert die Hälfte der Rückfragen."""
    seite = (Path(__file__).resolve().parents[1] / "app" / "static" / "efb.html").read_text(encoding="utf-8")
    assert "Microsoft.Limitless_8wekyb3d8bbwe" in seite
    assert "Microsoft Flight Simulator 2024" in seite
