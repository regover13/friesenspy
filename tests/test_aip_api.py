"""Endpoints der AIP-Kartenebene.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.database import get_connection, init_db, upsert_aip_chart

BOUNDS = dict(nord=54.30, sued=54.10, west=9.40, ost=9.80,
              feld_nord=54.28, feld_sued=54.12, feld_west=9.42, feld_ost=9.78)
GEO = dict(rahmen_px="132,180,817,865", tick_px_lat=219.0, tick_px_lon=128.4)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Eigene Datenbank je Test.

    OHNE diese Umlenkung zeigt ``get_settings().DB_PATH`` auf
    ``/opt/friesenspy/data/friesenspy.db`` -- in der CI fehlt sie, **auf dem VPS ist es die
    laufende Produktionsdatenbank**. Muster wie in den uebrigen API-Tests des Projekts.
    """
    db = str(tmp_path / "t.db")
    init_db(db)
    (tmp_path / "aip").mkdir()
    einst = Settings(SECRET_KEY="test", DB_PATH=db)
    monkeypatch.setattr(main, "get_settings", lambda: einst)
    return TestClient(main.app)


def _karte(db: str, icao: str = "EDXR") -> None:
    conn = get_connection(db)
    try:
        upsert_aip_chart(conn, icao, bild_hash="a" * 64, **BOUNDS, **GEO,
                         quelle="auto", airac="2026AUG20", status="gepasst")
        conn.commit()
    finally:
        conn.close()


def test_liste_liefert_blatt_und_feldgrenzen(client, tmp_path):
    _karte(str(tmp_path / "t.db"))
    r = client.get("/api/aip-charts")
    assert r.status_code == 200
    karten = r.json()["charts"]
    assert len(karten) == 1
    k = karten[0]
    assert set(k) >= {"icao", "nord", "sued", "west", "ost",
                      "feld_nord", "feld_sued", "feld_west", "feld_ost", "bild", "airac"}
    assert "rahmen_px" not in k          # Innereien gehoeren nicht in den Browser
    assert k["bild"].startswith("/aip-chart/EDXR.png")


def test_ungepasste_karte_erscheint_nicht(client, tmp_path):
    """Eine Karte, die falsch liegt, ist schlimmer als gar keine."""
    conn = get_connection(str(tmp_path / "t.db"))
    try:
        upsert_aip_chart(conn, "EDWJ", bild_hash="b" * 64, **BOUNDS, **GEO,
                         quelle="auto", airac="x", status="ungepasst")
        conn.commit()
    finally:
        conn.close()
    assert client.get("/api/aip-charts").json()["charts"] == []


def test_unbekannte_karte_ist_404(client):
    assert client.get("/aip-chart/XXXX.png").status_code == 404


def test_ungueltiger_code_ist_404_und_kein_pfaddurchgriff(client):
    assert client.get("/aip-chart/..%2F..%2Fetc%2Fpasswd.png").status_code == 404
    assert client.get("/aip-chart/AB.png").status_code == 404


def test_blatt_wird_ausgeliefert_und_nicht_oeffentlich_gecacht(client, tmp_path):
    """Die Datei ist lizenzgeschuetzt und liegt hinter dem Login -- 'public' erlaubte jedem
    Zwischen-Cache das Ausliefern ohne Anmeldung."""
    (tmp_path / "aip" / "EDXR.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    r = client.get("/aip-chart/EDXR.png")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "private" in cc and "public" not in cc
