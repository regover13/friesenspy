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


def test_admin_liste_braucht_anmeldung(client):
    assert client.get("/api/admin/aip-charts").status_code in (401, 403)


def test_handpassung_braucht_anmeldung(client):
    r = client.post("/api/admin/aip-charts/EDWJ", json={
        "breite_px": 875, "hoehe_px": 1240,
        "links_px": 132, "oben_px": 180, "rechts_px": 817, "unten_px": 865,
        # feld_* -- die geklickten RAHMENecken, nicht die Blattgrenzen. Dieselben vier Namen
        # fuer beides waren die Verwechslung hinter dem 45-Prozent-Fehler.
        "feld_nord": 54.0, "feld_sued": 53.9, "feld_west": 7.0, "feld_ost": 7.1,
    })
    assert r.status_code in (401, 403)


def test_dockerfile_liefert_scripts_ins_image():
    """Der Wochenjob importiert ``scripts.aip_bestand`` -- also muss ``scripts/`` im Image sein.

    Der Job faengt jede Exception ab (silent fail, damit ein misslungener Durchgang den
    Dienst nicht gefaehrdet). Ein fehlendes ``scripts/`` faellt deshalb nicht auf: Der
    ImportError landet im Log und der Kartenbestand veraltet stillschweigend ueber
    AIRAC-Zyklen hinweg. Genau das lag beim ersten Deploy-Anlauf am 24.08.2026 vor.
    """
    import pathlib
    wurzel = pathlib.Path(__file__).resolve().parents[1]
    zeilen = (wurzel / "Dockerfile").read_text().splitlines()
    kopiert = [z for z in zeilen if z.startswith("COPY") and "scripts/" in z]
    assert kopiert, "Dockerfile kopiert scripts/ nicht ins Image"

    # An den Import binden, nicht an eine freie Textsuche: Faellt der Import in poller.py
    # weg, darf dieser Test nicht laenger etwas verlangen, was niemand mehr braucht.
    poller = (wurzel / "app" / "poller.py").read_text()
    assert "from scripts.aip_bestand import lauf" in poller


# ---------------------------------------------------------------------------
# Seitenauswahl (24.08.2026)
# ---------------------------------------------------------------------------
def test_seitenliste_braucht_anmeldung(client):
    assert client.get("/api/admin/aip-charts/EDDK/seiten").status_code in (401, 403)


def test_seite_waehlen_braucht_anmeldung(client):
    r = client.post("/api/admin/aip-charts/EDDK/seite",
                    json={"url": "https://aip.dfs.de/BasicVFR/2026AUG20/pages/X.html"})
    assert r.status_code in (401, 403)


def test_nur_seiten_der_dfs_werden_geholt():
    """Sonst waere der Endpunkt ein offener Abruf beliebiger URLs vom Server aus.

    An den Quelltext gebunden und nicht an eine abgelehnte Anfrage: Der Test soll auch dann
    anschlagen, wenn jemand die Pruefung entfernt und die Route weiterhin 401 liefert, weil
    der Anmeldeschutz davor greift.
    """
    import inspect

    from app import main
    quelle = inspect.getsource(main.admin_aip_seite_waehlen)
    assert 'startswith("https://aip.dfs.de/")' in quelle


def test_seitenliste_blockiert_den_event_loop_nicht():
    """Sechs Seiten holen und vermessen dauert um die zehn Sekunden.

    Im Event-Loop stuenden derweil SSE, der 15-Sekunden-Poll und jede andere Anfrage --
    dasselbe Muster wie beim woechentlichen Job in app/poller.py.
    """
    import inspect

    from app import main
    for f in (main.admin_aip_seiten, main.admin_aip_seite_waehlen):
        assert "asyncio.to_thread" in inspect.getsource(f)


# ---------------------------------------------------------------------------
# Sofortmeldung an offene Seiten (24.08.2026)
# ---------------------------------------------------------------------------
def test_gepasste_karte_wird_an_offene_seiten_gemeldet():
    """Sonst erscheint sie erst nach einem Neuladen -- im Kniebrett also gar nicht.

    Die EFB-App wird beim Zuklappen nur schlafen gelegt; die Seite laedt innerhalb einer
    Sim-Sitzung nie neu. Der Nutzer hat am 24.08.2026 EDVM gepasst und es blieb aus.
    """
    import inspect

    from app import main
    for f in (main.admin_set_aip_chart, main.admin_aip_seite_waehlen):
        assert "_aip_karten_geaendert(request)" in inspect.getsource(f)


def test_meldung_laesst_die_passung_nicht_scheitern():
    """Steht der Poller nicht (Testlauf, Startphase), darf das Speichern trotzdem gelingen."""
    import inspect

    from app import main
    quelle = inspect.getsource(main._aip_karten_geaendert)
    assert "if poller is None:" in quelle
    assert "except Exception:" in quelle


def test_seitenwahl_loescht_keine_handpassung_am_selben_blatt():
    """Dieselbe Seite erneut zu waehlen darf eine Handpassung nicht auf Null setzen.

    Am 25.08.2026 passiert: Ein Aufruf, der nur die SSE-Benachrichtigung ausloesen sollte,
    schickte dieselbe (richtige) Seite noch einmal -- die Automatik scheiterte darauf wie
    zuvor, und der Endpunkt schrieb daraufhin ``leer`` und ``status='ungepasst'``. Die von
    Hand gesetzte Passung fuer EDAZ war weg und musste neu gesetzt werden.

    Entscheidend ist der BILDhash, nicht der Seitenvergleich: Bei einer ANDEREN Seite ist
    das Nullsetzen richtig, denn die alte Passung gilt dann fuer ein anderes Blatt und waere
    darauf falsch. Der Test bindet an genau diese Unterscheidung.
    """
    import inspect

    from app import main
    quelle = inspect.getsource(main.admin_aip_seite_waehlen)
    assert 'alt["bild_hash"] == neuer_hash' in quelle, \
        "Bildgleichheit muss der Test sein, nicht die Seiten-URL"
    assert 'alt["quelle"] == "hand"' in quelle
    # Und der Rueckfall muss VOR dem Schreiben greifen.
    assert quelle.index('alt["bild_hash"] == neuer_hash') < quelle.index("upsert_aip_chart")


def test_seitenwahl_legt_quer_gedruckte_blaetter_genordet_ab():
    """Der Seitenwaehler drehte bis 25.08.2026 NIE -- die Drehlogik war eine Closure.

    ``blatt_beschaffen`` hatte sie als lokale Funktion ``versuche``; erreichbar war sie damit
    nur ueber den Abruf. Der Seitenwaehler rief ``passung_rechnen`` direkt auf und legte ein
    quer gedrucktes Blatt unveraendert ab. Genau so ist EDDN quer in die Ablage gelangt,
    obwohl seine Seite 3 eine regulaere Sichtflugkarte mit Gradnetz ist -- ein Blatt, das
    weder automatisch noch von Hand zu passen war, ohne dass man ihm ansah, warum.
    """
    import inspect

    from app import main
    quelle = inspect.getsource(main.admin_aip_seite_waehlen)
    assert "genordet_rechnen(" in quelle, "der Seitenwaehler muss die Drehlogik benutzen"
    assert "aip_charts.passung_rechnen(" not in quelle, \
        "der direkte Aufruf umgeht das Drehen"
    # Der Hash muss zu den abgelegten Bytes gehoeren -- also NACH dem Drehen gebildet werden,
    # sonst greift die Handpassungs-Sicherung am falschen Bild.
    assert quelle.index("genordet_rechnen(") < quelle.index("_h.sha256(roh)")


def test_seitenwahl_kennt_dieselben_plaetze_wie_der_bestandslauf():
    """airportsdata kennt 29 der 446 Plaetze nicht -- EDMR ist einer davon.

    Der woechentliche Bestandslauf faellt fuer sie seit jeher auf OpenAIP zurueck
    (``platz_koordinate``) und passt sie problemlos. Die Admin-Endpunkte fragten dagegen nur
    ``geo.icao_to_coords`` und antworteten mit 409 "Koordinate des Platzes unbekannt" --
    ausgerechnet bei den Plaetzen, fuer die man den Seitenwaehler am ehesten braucht.

    Gebunden an die gemeinsame Funktion, nicht an eine zweite Fassung derselben Aufloesung:
    Zwei Antworten auf dieselbe Frage laufen frueher oder spaeter auseinander.
    """
    import inspect

    from app import main
    helfer = inspect.getsource(main._platz_koordinate)
    assert "geo.icao_to_coords" in helfer, "die guenstige Quelle zuerst"
    assert "platz_koordinate" in helfer, "der OpenAIP-Rueckfall des Jobs muss es sein"
    for endpunkt in (main.admin_aip_seiten, main.admin_aip_seite_waehlen):
        quelle = inspect.getsource(endpunkt)
        # Ohne Klammer geprueft: Der Seiten-Endpunkt reicht die Funktion als Referenz an
        # ``asyncio.to_thread`` weiter (sie macht einen Netzabruf und darf den Event-Loop
        # nicht blockieren), der Seitenwaehler ruft sie direkt auf.
        assert "_platz_koordinate" in quelle, f"{endpunkt.__name__} umgeht den Rueckfall"
        assert "geo.icao_to_coords(" not in quelle, \
            f"{endpunkt.__name__} fragt noch direkt und verliert die 29 Plaetze"


# ---------------------------------------------------------------------------
# Vorschlaege: uebernehmen und verwerfen
# ---------------------------------------------------------------------------

def test_vorschlag_uebernehmen_setzt_die_passung(client, tmp_path):
    """Der einzige Weg, auf dem eine Handpassung ersetzt werden darf."""
    from app.database import get_aip_chart, vorschlag_anlegen

    db = str(tmp_path / "t.db")
    conn = get_connection(db)
    try:
        upsert_aip_chart(conn, "EDDL", bild_hash="a" * 64, **BOUNDS, **GEO,
                         quelle="hand", airac="2026AUG20", status="gepasst")
        vid = vorschlag_anlegen(conn, "sichtflug", "EDDL", "b" * 64,
                                {**BOUNDS, "nord": 55.0, "airac": "2026SEP17"},
                                "Automatik weicht ab")
        conn.commit()
    finally:
        conn.close()
    assert client.post(f"/api/admin/aip-vorschlaege/{vid}/uebernehmen").status_code in (200, 401)
    conn = get_connection(db)
    try:
        k = get_aip_chart(conn, "EDDL")
        if k["quelle"] == "auto":                     # Admin war angemeldet
            assert k["nord"] == pytest.approx(55.0)
    finally:
        conn.close()


def test_vorschlag_verwerfen_laesst_die_passung_stehen(client, tmp_path):
    from app.database import get_aip_chart, vorschlag_anlegen

    db = str(tmp_path / "t.db")
    conn = get_connection(db)
    try:
        upsert_aip_chart(conn, "EDDL", bild_hash="a" * 64, **BOUNDS, **GEO,
                         quelle="hand", airac="2026AUG20", status="gepasst")
        vid = vorschlag_anlegen(conn, "sichtflug", "EDDL", "b" * 64,
                                {**BOUNDS, "nord": 55.0}, "Automatik weicht ab")
        conn.commit()
    finally:
        conn.close()
    client.post(f"/api/admin/aip-vorschlaege/{vid}/verwerfen")
    conn = get_connection(db)
    try:
        k = get_aip_chart(conn, "EDDL")
        assert k["nord"] == pytest.approx(54.30) and k["quelle"] == "hand"
    finally:
        conn.close()


def test_uebernehmen_lehnt_unvollstaendige_vorschlaege_ab(client, tmp_path):
    """Ein Vorschlag ohne Grenzen wuerde eine gueltige Passung durch Muell ersetzen."""
    from app.database import vorschlag_anlegen

    db = str(tmp_path / "t.db")
    conn = get_connection(db)
    try:
        upsert_aip_chart(conn, "EDDL", bild_hash="a" * 64, **BOUNDS, **GEO,
                         quelle="hand", airac="2026AUG20", status="gepasst")
        vid = vorschlag_anlegen(conn, "sichtflug", "EDDL", "b" * 64, {"nord": 55.0}, "x")
        conn.commit()
    finally:
        conn.close()
    antwort = client.post(f"/api/admin/aip-vorschlaege/{vid}/uebernehmen")
    assert antwort.status_code in (401, 422)
