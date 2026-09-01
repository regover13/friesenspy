"""Endpunkte der vereinigten AIP-Kartenansicht.

Spec: docs/superpowers/specs/2026-08-31-aip-charts-dfs-design.md
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.auth import ADMIN_COOKIE, CONFIRM_COOKIE, make_admin_token, make_confirm_token
from app.config import Settings
from app.database import (
    get_chart_dfs,
    get_connection,
    init_db,
    upsert_chart_dfs,
)

SECRET = "test-secret"
PW = "test-admin-pw"
TOKEN = make_admin_token(SECRET, PW)

# Eine vollstaendige Lage, wie sie aus einer Handpassung faellt.
LAGE = dict(nord=51.32, sued=51.25, west=6.71, ost=6.82,
            feld_nord=51.31, feld_sued=51.26, feld_west=6.72, feld_ost=6.81,
            drehung=322.8, mps=1.69)

# Die beiden Schwellen der EDDL-Bahn 05R/23L, UNGERUNDET aus runways.csv. Auf fuenf
# Nachkommastellen gerundet ergaeben dieselben Punkte 3211 m statt 2999 -- ein
# Laengenfehler von sieben Prozent, und der Test pruefte eine Geometrie, die es nicht gibt.
S_05R = (51.279598236083984, 6.751989841461182)
S_23L = (51.2958984375, 6.786220073699951)


@pytest.fixture()
def client(tmp_path):
    """Eigene Datenbank je Test, TestClient mit gesetztem Admin-Cookie.

    OHNE die Umlenkung von ``get_settings`` zeigt sie auf die Produktionsdatenbank auf dem
    VPS -- Muster wie in den uebrigen API-Tests des Projekts.
    """
    db = str(tmp_path / "t.db")
    init_db(db)
    einst = Settings(SECRET_KEY=SECRET, ADMIN_PASSWORD=PW, DB_PATH=db)
    main.app.dependency_overrides.clear()
    orig = main.get_settings
    main.get_settings = lambda: einst
    c = TestClient(main.app)
    c.cookies.set(ADMIN_COOKIE, TOKEN)
    yield c, db, tmp_path
    main.get_settings = orig


def _rohblatt(pfad, breite: int, hoehe: int) -> None:
    """Ein zeichnerisch belangloses, aber gueltiges PNG der gewuenschten Groesse.

    Die Groesse ist nicht belanglos: norden() rechnet die Blattecken durch die Passung, und
    ein 1x1-Bild ergaebe Grenzen, an denen kein Test etwas sieht.
    """
    pfad.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (breite, hoehe), 255).save(pfad, "PNG")


def _karte(db: str, icao: str, sorte: str = "sichtflug", status: str = "gepasst") -> None:
    conn = get_connection(db)
    try:
        upsert_chart_dfs(conn, icao, sorte, status=status, **LAGE)
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- Oeffentlich
def test_liste_liefert_beide_sorten(client):
    c, db, _tmp = client
    _karte(db, "EDDL", "sichtflug")
    _karte(db, "EDDL", "flugplatzkarte")
    r = c.get("/api/aip-charts-dfs")
    assert r.status_code == 200
    karten = r.json()["charts"]
    assert {k["sorte"] for k in karten} == {"sichtflug", "flugplatzkarte"}
    assert karten[0]["bild"].startswith("/aip-chart-dfs/EDDL/")


def test_offene_karte_erscheint_nicht_in_der_oeffentlichen_liste(client):
    """Eine Karte, die falsch liegt, ist schlimmer als gar keine."""
    c, db, _tmp = client
    _karte(db, "EDWJ", "sichtflug", status="offen")
    assert c.get("/api/aip-charts-dfs").json()["charts"] == []


def test_rohbild_wird_ausgeliefert(client):
    """Der alte Pfad /aip-ground-chart/{icao}.roh.png war nie erreichbar: FastAPI prueft
    Routen in Registrierungsreihenfolge, {icao} schluckt den Punkt, und die davor
    registrierte Route /aip-ground-chart/{icao}.png fing die Anfrage mit icao='EDDL.roh'
    ab -- scheiterte an der Vierzeichenpruefung und lieferte 404. Deshalb ein eigener Pfad
    statt eines Suffixes.
    """
    c, db, tmp = client
    _karte(db, "EDDL", "rollkarte")
    _rohblatt(tmp / "aip_dfs" / "EDDL.rollkarte.roh.png", 400, 300)
    antwort = c.get("/aip-chart-roh/EDDL/rollkarte.png")
    assert antwort.status_code == 200


def test_rohbild_braucht_anmeldung(client):
    c, db, tmp = client
    _rohblatt(tmp / "aip_dfs" / "EDDL.rollkarte.roh.png", 400, 300)
    c.cookies.clear()
    assert c.get("/aip-chart-roh/EDDL/rollkarte.png").status_code == 401


# --------------------------------------------------------------------------- Admin-Liste
def test_admin_liste_braucht_anmeldung(client):
    c, _db, _tmp = client
    c.cookies.clear()
    assert c.get("/api/admin/aip-charts-dfs").status_code == 401


def test_liste_zeigt_auch_plaetze_ohne_blatt(client):
    """Ausdruecklicher Wunsch: 'Vielleicht finde ich ja eine geeignete Karte, die du nicht
    gefunden hast.' Ein Platz OHNE Zeile erscheint mit status=None -- die Oberflaeche
    schreibt dafuer 'nicht nachgesehen'."""
    c, db, _tmp = client
    conn = get_connection(db)
    try:
        conn.execute("INSERT INTO airport_links (icao, aip_url, updated_at) "
                     "VALUES ('EDZZ', 'https://x/k.html', '2026-08-31T00:00:00Z')")
        conn.commit()
    finally:
        conn.close()
    d = c.get("/api/admin/aip-charts-dfs").json()
    zzz = [k for k in d["charts"] if k["icao"] == "EDZZ"]
    assert zzz and zzz[0]["status"] is None and zzz[0]["sorte"] is None


def test_liste_zeigt_offene_und_geprueften_status(client):
    c, db, _tmp = client
    _karte(db, "EDAA", "sichtflug", status="offen")
    _karte(db, "EDAB", "rollkarte", status="pruefen")
    d = c.get("/api/admin/aip-charts-dfs").json()
    status = {k["icao"]: k["status"] for k in d["charts"]}
    assert status["EDAA"] == "offen"
    assert status["EDAB"] == "pruefen"


# --------------------------------------------------------------------------- nicht-gefunden
def test_nicht_gefunden_wird_geschrieben(client):
    """Wer die Seitenauswahl oeffnet und keine passende Seite findet, haelt das fest --
    dabei entsteht die Zeile. Sonst kaeme derselbe Platz beim naechsten Durchgang wieder."""
    c, db, _tmp = client
    antwort = c.post("/api/admin/aip-charts-dfs/EDZZ/nicht-gefunden",
                     json={"sorte": "rollkarte"})
    assert antwort.status_code == 200
    conn = get_connection(db)
    try:
        assert get_chart_dfs(conn, "EDZZ", "rollkarte")["status"] == "nicht_gefunden"
    finally:
        conn.close()


def test_nicht_gefunden_lehnt_unbekannte_sorte_ab(client):
    c, _db, _tmp = client
    assert c.post("/api/admin/aip-charts-dfs/EDZZ/nicht-gefunden",
                  json={"sorte": "anflugkarte"}).status_code == 400


# --------------------------------------------------------------------------- Seitenwahl
def test_eine_gepasste_karte_wird_ueber_die_api_nicht_stillschweigend_genullt(client):
    """Der Seitenwaehler schrieb bei gescheiterter Passung alle Lagefelder auf 0
    (app/main.py:4694, Stand vor dem Rueckbau). Nach dem Rueckbau ist die Passung dort
    IMMER None -- der nullende Zweig waere der einzige. Am 25.08.2026 hat genau das EDAZ
    auf 0/0/0/0 gesetzt.

    Deshalb ruehrt der neue Seitenwaehler nie ein Lagefeld an -- unabhaengig vom Ausgang
    dieses konkreten Aufrufs (hier: 404, weil kein airport_links-Eintrag existiert).
    """
    c, db, _tmp = client
    _karte(db, "EDDL", "sichtflug", status="gepasst")
    c.post("/api/admin/aip-charts-dfs/EDDL/seite",
          json={"sorte": "sichtflug", "seite_nr": 3})
    conn = get_connection(db)
    try:
        k = get_chart_dfs(conn, "EDDL", "sichtflug")
        assert k["nord"] == pytest.approx(LAGE["nord"])
        assert k["status"] == "gepasst"
    finally:
        conn.close()


def test_seite_waehlen_ohne_kartenlink_ist_404(client):
    c, _db, _tmp = client
    r = c.post("/api/admin/aip-charts-dfs/EDZZ/seite",
              json={"sorte": "sichtflug", "seite_nr": 0})
    assert r.status_code == 404


def test_seite_waehlen_lehnt_unbekannte_sorte_ab(client):
    c, _db, _tmp = client
    r = c.post("/api/admin/aip-charts-dfs/EDZZ/seite",
              json={"sorte": "anflugkarte", "seite_nr": 0})
    assert r.status_code == 400


# --------------------------------------------------------------------------- Passen
def test_passen_setzt_status_gepasst(client):
    """Setzt der Nutzer selbst eine Passung, ist sie geprueft -- nicht 'auto'."""
    c, db, tmp = client
    _rohblatt(tmp / "aip_dfs" / "EDDL.flugplatzkarte.roh.png", 2200, 1000)
    antwort = c.post("/api/admin/aip-charts-dfs/EDDL/flugplatzkarte", json={
        "p1_x": 200, "p1_y": 500, "p1_lat": S_05R[0], "p1_lon": S_05R[1],
        "p2_x": 1970, "p2_y": 500, "p2_lat": S_23L[0], "p2_lon": S_23L[1],
    })
    assert antwort.status_code == 200
    conn = get_connection(db)
    try:
        k = get_chart_dfs(conn, "EDDL", "flugplatzkarte")
        assert k["status"] == "gepasst"
        # Bahnrichtung 052,8 Grad waagerecht ins Blatt gelegt heisst 052,8 - 90 = -37,2,
        # also 322,8 -- genau der an EDDL gemessene Wert.
        assert k["drehung"] == pytest.approx(322.8, abs=1.5)
        assert k["p1_x"] == pytest.approx(200)
    finally:
        conn.close()


def test_die_drehung_laesst_sich_ueberschreiben(client):
    """Bei zwei nah beieinanderliegenden Punkten ist der abgeleitete Wert schlecht;
    dann ist Nachjustieren von Hand der schnellere Weg."""
    c, db, tmp = client
    _rohblatt(tmp / "aip_dfs" / "EDDL.flugplatzkarte.roh.png", 2200, 1000)
    c.post("/api/admin/aip-charts-dfs/EDDL/flugplatzkarte", json={
        "p1_x": 200, "p1_y": 500, "p1_lat": S_05R[0], "p1_lon": S_05R[1],
        "p2_x": 1970, "p2_y": 500, "p2_lat": S_23L[0], "p2_lon": S_23L[1],
        "drehung": 15.0,
    })
    conn = get_connection(db)
    try:
        assert get_chart_dfs(conn, "EDDL", "flugplatzkarte")["drehung"] == pytest.approx(15.0)
    finally:
        conn.close()


def test_passen_ohne_rohblatt_ist_409(client):
    c, _db, _tmp = client
    r = c.post("/api/admin/aip-charts-dfs/EDDL/sichtflug", json={
        "p1_x": 200, "p1_y": 500, "p1_lat": S_05R[0], "p1_lon": S_05R[1],
        "p2_x": 1970, "p2_y": 500, "p2_lat": S_23L[0], "p2_lon": S_23L[1],
    })
    assert r.status_code == 409


def test_passen_ueberschreibt_eine_gepasste_karte_ohne_extra_ansage(client):
    """Der Nutzer selbst passt hier -- die Sperre richtet sich gegen stillschweigendes
    Ueberschreiben, nicht gegen ihn. hand_ueberschreiben=True ist deshalb serverseitig
    fest verdrahtet."""
    c, db, tmp = client
    _rohblatt(tmp / "aip_dfs" / "EDDL.sichtflug.roh.png", 2200, 1000)
    _karte(db, "EDDL", "sichtflug", status="gepasst")
    r = c.post("/api/admin/aip-charts-dfs/EDDL/sichtflug", json={
        "p1_x": 200, "p1_y": 500, "p1_lat": S_05R[0], "p1_lon": S_05R[1],
        "p2_x": 1970, "p2_y": 500, "p2_lat": S_23L[0], "p2_lon": S_23L[1],
    })
    assert r.status_code == 200


# --------------------------------------------------------------------------- pruefen
def test_uebernehmen_hebt_pruefen_auf(client):
    """Neues Blatt angesehen, Passung stimmt noch: Status gepasst.

    Die Passung selbst bleibt dabei unangetastet.
    """
    c, db, _tmp = client
    conn = get_connection(db)
    try:
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst", **LAGE)
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="pruefen",
                         status_vorher="gepasst", gesehener_hash="n" * 64)
        conn.commit()
    finally:
        conn.close()
    assert c.post("/api/admin/aip-charts-dfs/EDDL/sichtflug/uebernehmen").status_code == 200
    conn = get_connection(db)
    try:
        k = get_chart_dfs(conn, "EDDL", "sichtflug")
        assert k["status"] == "gepasst"
        assert k["drehung"] == pytest.approx(LAGE["drehung"])
    finally:
        conn.close()


def test_uebernehmen_ohne_offene_pruefung_ist_404(client):
    c, db, _tmp = client
    _karte(db, "EDDL", "sichtflug", status="gepasst")
    assert c.post("/api/admin/aip-charts-dfs/EDDL/sichtflug/uebernehmen").status_code == 404


def test_verwerfen_stellt_den_alten_status_zurueck(client):
    """NICHT pauschal auf 'gepasst'. Eine der 42 als 'offen' migrierten Zeilen hat
    Lagefelder von 0 -- sie landete sonst nach einem Blattwechsel im Kniebrett, mit
    nord=sued=west=ost=0."""
    c, db, _tmp = client
    conn = get_connection(db)
    try:
        upsert_chart_dfs(conn, "EDZZ", "rollkarte", status="offen",
                         **{k: 0.0 for k in LAGE})
        upsert_chart_dfs(conn, "EDZZ", "rollkarte", status="pruefen",
                         status_vorher="offen", gesehener_hash="n" * 64)
        conn.commit()
    finally:
        conn.close()
    assert c.post("/api/admin/aip-charts-dfs/EDZZ/rollkarte/verwerfen").status_code == 200
    conn = get_connection(db)
    try:
        assert get_chart_dfs(conn, "EDZZ", "rollkarte")["status"] == "offen"
    finally:
        conn.close()


def test_auch_verwerfen_zieht_den_gesehener_hash_nach(client):
    """Sonst findet der naechste Wochenlauf denselben abweichenden Hash und setzt die Zeile
    erneut auf 'pruefen' -- die Liste waere nach dem ersten Verwerfen dauerhaft
    unaufraeumbar. Dieselbe Falle war bei der Vorschlagstabelle schon einmal gestellt."""
    c, db, _tmp = client
    conn = get_connection(db)
    try:
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst",
                         gesehener_hash="alt" + "0" * 61, **LAGE)
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="pruefen",
                         status_vorher="gepasst", gesehener_hash="n" * 64)
        conn.commit()
    finally:
        conn.close()
    c.post("/api/admin/aip-charts-dfs/EDDL/sichtflug/verwerfen")
    conn = get_connection(db)
    try:
        assert get_chart_dfs(conn, "EDDL", "sichtflug")["gesehener_hash"] == "n" * 64
    finally:
        conn.close()


# --------------------------------------------------------------------------- Loeschen
def test_delete_entfernt_die_karte(client):
    c, db, _tmp = client
    _karte(db, "EDDL", "sichtflug")
    assert c.delete("/api/admin/aip-charts-dfs/EDDL/sichtflug").status_code == 200
    conn = get_connection(db)
    try:
        assert get_chart_dfs(conn, "EDDL", "sichtflug") is None
    finally:
        conn.close()


def test_delete_unbekannter_karte_ist_404(client):
    c, _db, _tmp = client
    assert c.delete("/api/admin/aip-charts-dfs/EDZZ/sichtflug").status_code == 404


# ------------------------------------------------------- Hauptschalter der Platzkarten-Ebene
#
# Die Ebene "Flugplatzkarte" traegt im Kniebrett BEIDE Bodensorten (flugplatzkarte und
# rollkarte) -- sie ist ein einziger Eintrag in der Ebenen-Auswahl. Der Schalter legt genau
# diesen Eintrag still, ohne eine einzige Passung anzuruehren: Die Handarbeit an den
# Blaettern soll eine schlechte Auslieferung ueberleben, sonst muesste man zum Abschalten
# loeschen.

def _ebene(c, an: bool):
    """Der Schalter verlangt zusaetzlich das Step-up-Token -- wie die beiden anderen
    globalen Schalter des Projekts."""
    c.cookies.set(CONFIRM_COOKIE,
                  make_confirm_token(SECRET, PW, int(time.time()) + 300))
    return c.post("/api/admin/aip-charts-dfs/ebene", json={"enabled": an})


def test_ohne_eintrag_ist_die_platzkarten_ebene_an(client):
    """Kein Eintrag heisst 'wie bisher'. Ein Deploy darf die Ebene nicht stillschweigend
    abschalten -- wer sie aus haben will, sagt es."""
    c, db, _tmp = client
    _karte(db, "EDDL", "flugplatzkarte")
    d = c.get("/api/aip-charts-dfs").json()
    assert d["flugplatzkarte_aktiv"] is True
    assert [k["sorte"] for k in d["charts"]] == ["flugplatzkarte"]


def test_der_hauptschalter_nimmt_beide_bodensorten_aus_der_liste(client):
    """Rollkarte MUSS mit verschwinden: Im Kniebrett haengen beide an demselben Eintrag.
    Bliebe die Rollkarte, waere die Ebene sichtbar 'aus' und trotzdem belegt."""
    c, db, _tmp = client
    _karte(db, "EDDL", "sichtflug")
    _karte(db, "EDDL", "flugplatzkarte")
    _karte(db, "EDDH", "rollkarte")
    assert _ebene(c, False).status_code == 200
    d = c.get("/api/aip-charts-dfs").json()
    assert d["flugplatzkarte_aktiv"] is False
    assert [k["sorte"] for k in d["charts"]] == ["sichtflug"]


def test_der_hauptschalter_laesst_die_passungen_stehen(client):
    """Der Unterschied zu 'Loeschen'. Nach dem Zurueckschalten muss dieselbe Karte wieder
    da sein, mit derselben Lage -- sonst waere der Schalter eine Falle."""
    c, db, _tmp = client
    _karte(db, "EDDL", "flugplatzkarte")
    _ebene(c, False)
    conn = get_connection(db)
    try:
        assert get_chart_dfs(conn, "EDDL", "flugplatzkarte")["status"] == "gepasst"
    finally:
        conn.close()
    _ebene(c, True)
    d = c.get("/api/aip-charts-dfs").json()
    assert [k["sorte"] for k in d["charts"]] == ["flugplatzkarte"]
    assert d["flugplatzkarte_aktiv"] is True


def test_die_admin_liste_nennt_den_zustand_der_ebene(client):
    """Die Admin-Ansicht muss den Schalter richtig herum zeichnen koennen, ohne zu raten."""
    c, _db, _tmp = client
    assert c.get("/api/admin/aip-charts-dfs").json()["ebene_aktiv"] is True
    _ebene(c, False)
    assert c.get("/api/admin/aip-charts-dfs").json()["ebene_aktiv"] is False


def test_der_hauptschalter_braucht_anmeldung(client):
    c, _db, _tmp = client
    c.cookies.clear()
    assert c.post("/api/admin/aip-charts-dfs/ebene", json={"enabled": False}).status_code == 401


def test_der_hauptschalter_verdeckt_die_route_auf_eine_einzelne_karte_nicht(client):
    """'ebene' steht an derselben Stelle wie eine ICAO. Faengt die neue Route zu gierig,
    waere das Passen von Hand kaputt -- und zwar lautlos."""
    c, db, tmp = client
    _rohblatt(tmp / "aip_dfs" / "EDDL.flugplatzkarte.roh.png", 1200, 900)
    _karte(db, "EDDL", "flugplatzkarte", status="offen")
    r = c.post("/api/admin/aip-charts-dfs/EDDL/flugplatzkarte", json={
        "p1_x": 100, "p1_y": 200, "p1_lat": S_05R[0], "p1_lon": S_05R[1],
        "p2_x": 900, "p2_y": 700, "p2_lat": S_23L[0], "p2_lon": S_23L[1]})
    assert r.status_code == 200, r.text


# ------------------------------------------------------------ Vorschau der Passung
#
# Um zu sehen, ob eine Passung stimmt, braucht die Admin-Ansicht dieselben Grenzen, mit
# denen das Kniebrett das Blatt auflegt -- sonst zeigt die Vorschau etwas anderes als die
# App, und genau dafuer waere sie nutzlos.

def test_die_admin_liste_liefert_die_blattgrenzen_fuer_die_vorschau(client):
    c, db, _tmp = client
    _karte(db, "EDDL", "flugplatzkarte")
    k = [x for x in c.get("/api/admin/aip-charts-dfs").json()["charts"]
         if x["icao"] == "EDDL" and x["sorte"] == "flugplatzkarte"][0]
    assert (k["nord"], k["sued"], k["west"], k["ost"]) == (
        LAGE["nord"], LAGE["sued"], LAGE["west"], LAGE["ost"])
    assert k["mps"] == LAGE["mps"]
    assert k["bild"].startswith("/aip-chart-dfs/EDDL/flugplatzkarte.png")


def test_die_vorschau_bekommt_denselben_bildpfad_wie_das_kniebrett(client):
    """Nicht das Rohblatt: Die Drehung steckt im ABGELEGTEN Bild, das Overlay liegt
    achsenparallel. Wer hier /aip-chart-roh/ zeigte, saehe eine schiefe Karte und suchte
    einen Fehler, den es nicht gibt."""
    c, db, _tmp = client
    _karte(db, "EDDL", "flugplatzkarte")
    admin = [x for x in c.get("/api/admin/aip-charts-dfs").json()["charts"]
             if x["sorte"] == "flugplatzkarte"][0]
    oeff = c.get("/api/aip-charts-dfs").json()["charts"][0]
    assert admin["bild"].split("?")[0] == oeff["bild"].split("?")[0]


def test_eine_karte_ohne_passung_hat_keine_grenzen(client):
    """Damit die Ansicht den Vorschau-Knopf weglassen kann, statt eine leere Karte zu zeigen.

    Achtung, die Falle: Eine Zeile ohne Passung traegt ``nord=sued=west=ost=0`` -- NULL ist
    es nicht (s. CLAUDE.md). Ungeprueft weitergereicht laege das Blatt in der Vorschau bei
    0/0 im Golf von Guinea und saehe aus wie eine kaputte Passung statt wie gar keine.
    """
    c, db, _tmp = client
    conn = get_connection(db)
    try:
        upsert_chart_dfs(conn, "EDWJ", "flugplatzkarte", status="offen")
        conn.commit()
    finally:
        conn.close()
    k = [x for x in c.get("/api/admin/aip-charts-dfs").json()["charts"]
         if x["icao"] == "EDWJ"][0]
    assert k["nord"] is None


# ------------------------------------------------------------------ Passhilfe fuer die Maske

def test_die_passhilfe_nennt_die_platzmitte(client):
    """Ohne sie stuende die Vorschau bei einer noch ungepassten Karte auf 0/0 im Golf von
    Guinea -- statt ueber dem Platz, den man anklicken soll."""
    c, db, _tmp = client
    _karte(db, "EDDL", "flugplatzkarte", status="offen")
    d = c.get("/api/admin/aip-charts-dfs/EDDL/flugplatzkarte/passhilfe").json()
    assert d["mitte"] and 51 < d["mitte"][0] < 52 and 6 < d["mitte"][1] < 7


def test_die_passhilfe_rechnet_punkte_aus_einer_auto_lage_zurueck(client):
    """DER Punkt: Die 68 auto-Karten tragen ein fertiges Rechteck, aber keine geklickten
    Punkte -- die zurueckgebaute Automatik hat nie welche erzeugt. In der Maske kam deshalb
    allein die Drehung an."""
    c, db, tmp = client
    _rohblatt(tmp / "aip_dfs" / "EDDL.flugplatzkarte.roh.png", 1600, 1100)
    _karte(db, "EDDL", "flugplatzkarte", status="auto")
    d = c.get("/api/admin/aip-charts-dfs/EDDL/flugplatzkarte/passhilfe").json()
    p = d["punkte"]
    assert p is not None
    for feld in ("p1_x", "p1_y", "p1_lat", "p1_lon", "p2_x", "p2_y", "p2_lat", "p2_lon"):
        assert isinstance(p[feld], (int, float))
    assert LAGE["sued"] - 0.01 < p["p1_lat"] < LAGE["nord"] + 0.01
    assert abs(p["p2_x"] - p["p1_x"]) > 800


def test_die_passhilfe_ruehrt_geklickte_punkte_nicht_an(client):
    """Wo echte Punkte stehen, wird nichts zurueckgerechnet -- die Maske nimmt dann die
    gespeicherten."""
    c, db, tmp = client
    _rohblatt(tmp / "aip_dfs" / "EDDL.flugplatzkarte.roh.png", 1600, 1100)
    _karte(db, "EDDL", "flugplatzkarte", status="offen")
    c.post("/api/admin/aip-charts-dfs/EDDL/flugplatzkarte", json={
        "p1_x": 100, "p1_y": 200, "p1_lat": S_05R[0], "p1_lon": S_05R[1],
        "p2_x": 900, "p2_y": 700, "p2_lat": S_23L[0], "p2_lon": S_23L[1]})
    d = c.get("/api/admin/aip-charts-dfs/EDDL/flugplatzkarte/passhilfe").json()
    assert d["punkte"] is None


def test_die_passhilfe_braucht_anmeldung(client):
    c, _db, _tmp = client
    c.cookies.clear()
    assert c.get("/api/admin/aip-charts-dfs/EDDL/flugplatzkarte/passhilfe").status_code == 401


def test_die_passhilfe_lehnt_eine_unbekannte_sorte_ab(client):
    c, _db, _tmp = client
    assert c.get("/api/admin/aip-charts-dfs/EDDL/unfug/passhilfe").status_code == 404
