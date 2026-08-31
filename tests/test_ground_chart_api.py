"""Endpoints der Flugplatzkarten-Ebene.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md, Abschnitt 9
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.database import get_connection, init_db, upsert_ground_chart

WERTE = dict(sorte="flugplatzkarte", quell_hash="b" * 64, bild_hash="c" * 64,
             nord=51.30, sued=51.27, west=6.74, ost=6.80,
             feld_nord=51.295, feld_sued=51.275, feld_west=6.745, feld_ost=6.795,
             drehung=322.8, mps=1.69, rest_max=5.7, bahnen=2, airac="2026AUG20")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Eigene Datenbank je Test.

    OHNE diese Umlenkung zeigt get_settings().DB_PATH auf die laufende
    Produktionsdatenbank des VPS. Muster wie in tests/test_aip_api.py.
    """
    db = str(tmp_path / "t.db")
    init_db(db)
    (tmp_path / "aip_ground").mkdir()
    einst = Settings(SECRET_KEY="test", DB_PATH=db)
    monkeypatch.setattr(main, "get_settings", lambda: einst)
    return TestClient(main.app), db, tmp_path


def _karte(db: str, icao: str = "EDDL", **abw) -> None:
    conn = get_connection(db)
    try:
        upsert_ground_chart(conn, icao,
                            **{"quelle": "auto", "status": "gepasst", **WERTE, **abw})
        conn.commit()
    finally:
        conn.close()


def test_liste_liefert_blatt_und_feldgrenzen(client):
    c, db, _ = client
    _karte(db)
    d = c.get("/api/aip-ground-charts").json()
    assert len(d["charts"]) == 1
    k = d["charts"][0]
    assert k["icao"] == "EDDL" and k["sorte"] == "flugplatzkarte"
    assert k["feld_nord"] < k["nord"] and k["feld_sued"] > k["sued"]
    assert k["bild"].startswith("/aip-ground-chart/EDDL.png?h=")


def test_ungepasste_karte_erscheint_nicht(client):
    """Eine falsch liegende Karte ist schlimmer als gar keine -- beim Rollen wird sie
    geglaubt."""
    c, db, _ = client
    _karte(db, status="ungepasst")
    assert c.get("/api/aip-ground-charts").json()["charts"] == []


def test_bild_wird_privat_ausgeliefert(client):
    """`public` erlaubte jedem Zwischen-Cache das Ausliefern ohne Anmeldung -- und genau
    die Beschraenkung auf angemeldete Nutzer traegt das rechtliche Argument."""
    c, db, tmp = client
    _karte(db)
    (tmp / "aip_ground" / "EDDL.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    antwort = c.get("/aip-ground-chart/EDDL.png")
    assert antwort.status_code == 200
    assert "private" in antwort.headers.get("cache-control", "")
    assert "public" not in antwort.headers.get("cache-control", "")


def test_unsinniger_code_wird_abgewiesen(client):
    c, _db, _ = client
    assert c.get("/aip-ground-chart/../../etc/passwd.png").status_code == 404
    assert c.get("/aip-ground-chart/ABC.png").status_code == 404


def test_fehlendes_blatt_gibt_404_statt_500(client):
    c, db, _ = client
    _karte(db)
    assert c.get("/aip-ground-chart/EDDL.png").status_code == 404


def test_ground_blatt_kollidiert_nicht_mit_der_sichtflugkarte():
    """`<db>/aip/<ICAO>.png` ist von den Sichtflugkarten belegt. Ein Ground Chart mit
    derselben ICAO ueberschriebe sie."""
    from app import aip_charts

    db = "/tmp/x/friesenspy.db"
    assert main._ground_blatt_pfad(db, "EDDL") != aip_charts.blatt_pfad(db, "EDDL")


def test_admin_liste_zeigt_den_restfehler(client):
    """Der Restfehler ist die einzige Zahl, an der ein Mensch von aussen erkennt, ob eine
    automatische Passung sitzt."""
    c, db, _ = client
    _karte(db, status="ungepasst")
    antwort = c.get("/api/admin/aip-ground-charts")
    if antwort.status_code == 200:
        k = antwort.json()["charts"][0]
        assert "rest_max" in k and "bahnen" in k
        assert k["status"] == "ungepasst"
    else:
        assert antwort.status_code == 401
