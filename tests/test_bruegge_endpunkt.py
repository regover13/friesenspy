"""Der Endpunkt `/api/bruegge/melden` gegen eine Brügge-Attrappe.

**Warum das hier steht und nicht im Simulator gemessen wird:** Zwischen Client und Server
liegt ein JSON-Vertrag, und ein Tippfehler darin kostet im Simulator einen Neustart und im
schlimmsten Fall ein Client-Release an 61 Piloten. Hier kostet er eine Sekunde.

Die Nutzlast unten ist dieselbe, die `friesenbruegge/msfs/bruegge.cpp` zusammenbaut --
Feldnamen und Verschachtelung wörtlich. Wer dort etwas ändert, ändert es hier mit, sonst
bemerkt es niemand, bis jemand fliegt.
"""

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def klient(tmp_path, monkeypatch):
    """Nach dem Muster von tests/test_vr_panel.py -- Einstellungen vorbeischieben statt
    Umgebungsvariablen zu setzen, damit der Lauf unabhaengig von der echten config.env ist."""
    from types import SimpleNamespace
    import app.main as main
    from app.database import init_db

    pfad = str(tmp_path / "t.db")
    init_db(pfad)
    settings = SimpleNamespace(
        DB_PATH=pfad, CALLSIGN_PREFIX="FRS",
        SECRET_KEY="test-nur-fuer-diesen-lauf", ADMIN_PASSWORD="test",
        SSO_SECRET="", FORUM_SSO_URL="", FORUM_SSO_CALLBACK="",
        USER_SESSION_MAX_AGE_SEC=3600, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    if hasattr(main, "_reset_gate_cache"):
        main._reset_gate_cache()
    return TestClient(main.app)


def _meldung(lat=53.78227, lon=7.92593, kennung="a3f9c1e0b2d48576", **mehr):
    """Genau die Nutzlast, die bruegge.cpp baut."""
    lage = {
        "lat": lat, "lon": lon,
        "alt_msl_ft": 5.3, "alt_agl_ft": 0.0,
        "gs_kt": 0.0, "kurs": 210.4, "vs_ft_min": 0.0, "am_boden": True,
    }
    lage.update(mehr.pop("lage", {}))
    m = {
        "protokoll": 1,
        "simulator": "msfs2024",
        "bruegge_version": "1.0.0",
        "kennung": kennung,
        # ⚠ `kann` GIBT ES SEIT PROTOKOLLFASSUNG 2 NICHT MEHR (14.09.2026) -- die Bruegge
        # fuehrt keine Artentabelle mehr und kann deshalb nichts behaupten.
        #
        # Es steht hier trotzdem, und zwar mit Absicht: Die Attrappe spielt eine Bruegge der
        # Fassung 1, wie FRS61 sie fliegt. Dass der Server sie weiter bedient, ist kein
        # Nebenschauplatz -- ein Feld zu entfernen darf niemanden brechen, der nichts
        # herunterlaedt. Der Server wirft `kann` weg, wie seit jeher.
        "kann": ["tier_gross", "bauwerk", "fahrzeug", "boot_klein", "boot_gross", "robbe"],
        "lage": lage,
        "spur": [],
        "steht": [],
    }
    m.update(mehr)
    return m


def _friese_anlegen(db_pfad, cid=1234567, callsign="FRS61",
                    lat=53.78227, lon=7.92593, mit_forum_login=True):
    """Ein Friese auf VATSIM -- und, wenn gewollt, mit Forum-Login."""
    from app.database import get_connection, _now_utc
    conn = get_connection(db_pfad)
    conn.execute(
        "INSERT OR REPLACE INTO live_positions "
        "(cid, callsign, latitude, longitude, altitude, groundspeed, heading, updated_at) "
        "VALUES (?, ?, ?, ?, 5, 0, 210, ?)",
        (cid, callsign, lat, lon, _now_utc()),
    )
    if mit_forum_login:
        conn.execute(
            "INSERT OR REPLACE INTO forum_callsign (callsign, cid, updated_at) VALUES (?, ?, ?)",
            (callsign, cid, _now_utc()),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------------------
# Der gute Fall
# ---------------------------------------------------------------------------------------

def test_meldung_eines_bekannten_friesen_wird_abgelegt(klient, tmp_path):
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    r = klient.post("/api/bruegge/melden", json=_meldung())
    assert r.status_code == 200
    antwort = r.json()
    assert antwort["protokoll"] == 1
    assert antwort["soll"] == [], "Fassung 1 verteilt noch keine Objekte"
    assert antwort["naechste_frage_in_s"] == 1, "Regeltakt"

    from app.database import get_connection, bruegge_position_holen
    conn = get_connection(db)
    lage = bruegge_position_holen(conn, 1234567)
    conn.close()
    assert lage is not None
    assert lage["lat"] == pytest.approx(53.78227)
    assert lage["kennung"] == "a3f9c1e0b2d48576"


def test_zweite_meldung_nutzt_die_gemerkte_zuordnung(klient, tmp_path):
    """Die Kennung erspart den vollen Match -- die Zuordnung muss also stehenbleiben."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    klient.post("/api/bruegge/melden", json=_meldung())

    from app.database import get_connection, bruegge_zuordnung_holen
    conn = get_connection(db)
    z = bruegge_zuordnung_holen(conn, "a3f9c1e0b2d48576")
    conn.close()
    assert z is not None and z["cid"] == 1234567
    assert z["verstoesse"] == 0
    assert z["vor_lat"] == pytest.approx(53.78227)


# ---------------------------------------------------------------------------------------
# Die Ablehnungen -- und dass sie ununterscheidbar sind
# ---------------------------------------------------------------------------------------

def test_ohne_vatsim_geschieht_nichts(klient, tmp_path):
    """Niemand in live_positions: leeres soll, Minutentakt, kein Eintrag."""
    r = klient.post("/api/bruegge/melden", json=_meldung())
    assert r.status_code == 200
    assert r.json()["soll"] == []
    assert r.json()["naechste_frage_in_s"] == 10
    assert r.json()["gilt_bis_s"] == 0

    from app.database import get_connection, bruegge_position_holen
    conn = get_connection(str(tmp_path / "t.db"))
    assert bruegge_position_holen(conn, 1234567) is None
    conn.close()


def test_ohne_forum_login_geschieht_nichts(klient, tmp_path):
    """Auf VATSIM mit FRS-Präfix, aber nie im Forum angemeldet.

    Das ist der Fall, den der Nutzer ausdrücklich ausschließen wollte: Wer sich einfach ein
    FRS-Callsign setzt, soll nicht melden dürfen.
    """
    _friese_anlegen(str(tmp_path / "t.db"), mit_forum_login=False)
    r = klient.post("/api/bruegge/melden", json=_meldung())
    assert r.status_code == 200
    assert r.json()["soll"] == []


def test_die_ablehnungen_verraten_keinen_grund(klient, tmp_path):
    """Mit Absicht: Eine Fehlermeldung wäre ein Werkzeug.

    Wer ausprobieren wollte, welche erfundene Position durchgeht, bekäme vom Server sonst die
    Rückmeldung dazu. Deshalb sind `soll` und `gilt_bis_s` in jedem Ablehnungsfall gleich.

    ⚠ **Der Takt ist davon ausgenommen, und das ist eine bewusste Abwägung** (11.09.2026,
    nach dem ersten Flug): Er unterscheidet „niemand in der Luft" von „jemand in der Luft,
    aber keiner passt". Ohne diese Unterscheidung entsteht ein Teufelskreis -- ohne Zuordnung
    meldet die Brügge im Minutentakt, und in einer Minute fliegt ein Flugzeug so weit, dass
    die Zuordnung schwerer wird statt leichter.

    **Was der Takt damit preisgibt, ist bereits öffentlich:** ob gerade Friesen auf VATSIM
    fliegen, steht im VATSIM-Feed, den jeder lesen kann. Über eine *bestimmte* Person sagt er
    nichts -- und nur das wäre die Information, die ein Angreifer nicht ohnehin hat.
    """
    db = str(tmp_path / "t.db")
    ohne_vatsim = klient.post("/api/bruegge/melden", json=_meldung()).json()
    _friese_anlegen(db, mit_forum_login=False)
    ohne_login = klient.post("/api/bruegge/melden", json=_meldung()).json()
    weit_weg = klient.post("/api/bruegge/melden",
                           json=_meldung(lat=48.0, lon=11.0)).json()

    for a in (ohne_vatsim, ohne_login, weit_weg):
        assert a["soll"] == []
        assert a["gilt_bis_s"] == 0
    # Kein Friese in der Luft: Minutentakt. Mit Friesen: gleich nochmal.
    assert ohne_vatsim["naechste_frage_in_s"] == 10
    assert ohne_login["naechste_frage_in_s"] == weit_weg["naechste_frage_in_s"] <= 5


def test_wer_fliegt_aber_nicht_erkannt_wird_darf_bald_wieder_fragen(klient, tmp_path):
    """Der Teufelskreis, als Test festgehalten.

    Im ersten echten Flug (11.09.2026) stand die Zuordnung am Boden und fiel beim Steigen.
    Danach meldete die Brügge im Minutentakt -- und fand nie wieder zurück, weil sie zwischen
    zwei Meldungen zu weit geflogen war.
    """
    _friese_anlegen(str(tmp_path / "t.db"))
    # Weit weg vom einzigen Friesen: kein Treffer, aber es gibt Kandidaten.
    a = klient.post("/api/bruegge/melden", json=_meldung(lat=48.35, lon=11.78)).json()
    assert a["naechste_frage_in_s"] <= 5, "sonst verhindert der Takt die Zuordnung"


def test_position_ohne_passenden_friesen_wird_nicht_abgelegt(klient, tmp_path):
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    # München, 600 km entfernt.
    r = klient.post("/api/bruegge/melden", json=_meldung(lat=48.35, lon=11.78))
    assert r.status_code == 200
    from app.database import get_connection, bruegge_position_holen
    conn = get_connection(db)
    assert bruegge_position_holen(conn, 1234567) is None
    conn.close()


# ---------------------------------------------------------------------------------------
# Missbrauch und Schlamperei
# ---------------------------------------------------------------------------------------

def test_kaputtes_json_wird_abgewiesen(klient):
    r = klient.post("/api/bruegge/melden", content=b"{nicht wirklich json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_fehlende_lage_wird_abgewiesen(klient):
    m = _meldung()
    del m["lage"]
    assert klient.post("/api/bruegge/melden", json=m).status_code == 400


def test_unsinnige_koordinaten_werden_abgewiesen(klient):
    assert klient.post("/api/bruegge/melden",
                       json=_meldung(lat=91.0, lon=7.0)).status_code == 400
    assert klient.post("/api/bruegge/melden",
                       json=_meldung(lat=53.0, lon=181.0)).status_code == 400


def test_zu_grosse_meldung_wird_abgewiesen(klient):
    r = klient.post("/api/bruegge/melden", content=b"{" + b"x" * 70000,
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_neuere_protokollfassung_bekommt_426(klient):
    """Damit eine neuere Brügge aufräumt und anhält, statt in einem Vertrag zu reden,
    den niemand liest.

    Die Zahl wandert mit: Seit dem 14.09.2026 spricht der Server Fassung 2, also ist erst 3
    zu neu. Wer sie hier hochzieht, ohne `_BRUEGGE_PROTOKOLL` anzufassen, hebelt den Test aus.
    """
    import app.main as main
    r = klient.post("/api/bruegge/melden",
                    json=_meldung(protokoll=main._BRUEGGE_PROTOKOLL + 1))
    assert r.status_code == 426


def test_eine_alte_bruegge_bekommt_ihre_eigene_fassung_zurueck(klient, tmp_path):
    """Geantwortet wird in der Fassung, in der gefragt wurde — höchstens der eigenen.

    Eine Brügge, die Fassung 1 spricht, bekäme sonst eine 2 zurück und müsste daraus
    schließen, dass sie etwas nicht versteht — obwohl der Server ihr genau das schickt, was
    Fassung 1 vorsieht. Die Zahl steht laut Abschnitt 9 in BEIDEN Richtungen; dann muss sie
    auch beide Seiten meinen.
    """
    _friese_anlegen(str(tmp_path / "t.db"))
    assert klient.post("/api/bruegge/melden",
                       json=_meldung(protokoll=1)).json()["protokoll"] == 1
    assert klient.post("/api/bruegge/melden",
                       json=_meldung(protokoll=2)).json()["protokoll"] == 2


# ---------------------------------------------------------------------------------------
# Die Drossel
# ---------------------------------------------------------------------------------------

def test_die_drossel_wirkt_sofort(klient, tmp_path):
    """Der Takt wird bei JEDER Antwort gelesen -- ohne Deploy, ohne Client-Release."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    assert klient.post("/api/bruegge/melden", json=_meldung()
                       ).json()["naechste_frage_in_s"] == 1

    from app.database import get_connection, set_app_setting
    conn = get_connection(db)
    set_app_setting(conn, "bruegge_takt_s", "15")
    conn.commit()
    conn.close()

    assert klient.post("/api/bruegge/melden", json=_meldung()
                       ).json()["naechste_frage_in_s"] == 15


def test_unsinniger_taktwert_faellt_auf_die_vorgabe_zurueck(klient, tmp_path):
    """Ein kaputter Eintrag in app_settings darf die Brügge nicht lahmlegen."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    from app.database import get_connection, set_app_setting
    conn = get_connection(db)
    set_app_setting(conn, "bruegge_takt_s", "voellig kaputt")
    conn.commit()
    conn.close()
    assert klient.post("/api/bruegge/melden", json=_meldung()
                       ).json()["naechste_frage_in_s"] == 1


# ---------------------------------------------------------------------------------------
# Das Forum-Gate
# ---------------------------------------------------------------------------------------

def test_der_endpunkt_liegt_nicht_hinter_dem_forum_gate():
    """Gefunden am 11.09.2026 beim ersten Aufruf gegen die Produktion: `401 Login erforderlich`.

    FriesenSpy steht hinter dem Forum-Login, und ein Community-Modul im Simulator hat kein
    Sitzungs-Cookie und kann keines bekommen -- die Brügge hat bewusst **keine** Anmeldung.
    Läge der Endpunkt hinter dem Gate, wäre das Protokoll schlicht nicht umsetzbar.

    Gate-frei heißt nicht ungeprüft: Der Endpunkt setzt seine eigenen drei Bedingungen, und
    eine davon ist genau der Forum-Login -- nur zeitversetzt, über `forum_callsign`.
    """
    import app.main as main
    assert "/api/bruegge/melden" in main._GATE_ALLOW_PREFIXES


def test_der_endpunkt_antwortet_auch_ohne_anmeldung(klient, tmp_path):
    """Die Gegenprobe zum Test darüber, über den echten Aufruf statt über die Liste."""
    r = klient.post("/api/bruegge/melden", json=_meldung())
    assert r.status_code == 200, "kein 401 -- die Brügge kann sich nicht anmelden"


def test_die_hoehenschranke_laeuft_der_vatsim_hoehe_nach(klient, tmp_path):
    """Der Abfang-Moment, als Test festgehalten (11.09.2026, erster Flug).

    Maßgeblich ist nicht die *jetzige* Steigrate, sondern die von vor 16–29 Sekunden — so alt
    ist die VATSIM-Höhe, mit der verglichen wird. Beim Abfangen geht die jetzige schlagartig
    auf null, und genau dann ist die Differenz am größten.
    """
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)

    # Steigflug: 1200 ft/min, der Sim ist 580 ft über der VATSIM-Höhe (5 ft).
    steigend = _meldung()
    steigend["lage"]["vs_ft_min"] = 1200.0
    steigend["lage"]["alt_msl_ft"] = 585.0
    assert klient.post("/api/bruegge/melden", json=steigend
                       ).json()["naechste_frage_in_s"] == 1

    # Abgefangen: Steigrate null, Höhendifferenz noch da. Ohne Nachlauf risse es hier.
    abgefangen = _meldung()
    abgefangen["lage"]["vs_ft_min"] = 0.0
    abgefangen["lage"]["alt_msl_ft"] = 585.0
    assert klient.post("/api/bruegge/melden", json=abgefangen
                       ).json()["naechste_frage_in_s"] == 1, \
        "die Schranke muss der VATSIM-Höhe nachlaufen"

    from app.database import get_connection, bruegge_zuordnung_holen
    conn = get_connection(db)
    z = bruegge_zuordnung_holen(conn, "a3f9c1e0b2d48576")
    conn.close()
    assert z is not None and z["verstoesse"] == 0


def test_eine_neue_kennung_verdraengt_die_alte_derselben_cid(klient, tmp_path):
    """Die Kennung hält in MSFS nicht über einen Sim-Neustart — jede Sitzung zieht eine neue.

    Ohne diese Regel sammelt sich je Pilot eine Karteileiche pro Simulator-Start. Am
    11.09.2026 standen nach einem Abend zwei Zeilen für dieselbe CID, und die ältere hat beim
    Nachsehen in die Irre geführt.
    """
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    klient.post("/api/bruegge/melden", json=_meldung(kennung="1111111111111111"))
    klient.post("/api/bruegge/melden", json=_meldung(kennung="2222222222222222"))

    from app.database import get_connection
    conn = get_connection(db)
    zeilen = conn.execute("SELECT kennung FROM bruegge_zuordnung WHERE cid = 1234567").fetchall()
    conn.close()
    assert len(zeilen) == 1, "zwei Brüggen gleichzeitig gibt es nicht"
    assert zeilen[0][0] == "2222222222222222", "die neuere gilt"


def test_alte_zuordnungen_werden_aufgeraeumt(tmp_path):
    """Wer die Brügge deinstalliert, hinterlässt sonst eine Zeile für immer."""
    from app.database import (get_connection, init_db, bruegge_zuordnung_setzen,
                              bruegge_aufraeumen)
    pfad = str(tmp_path / "a.db")
    init_db(pfad)
    conn = get_connection(pfad)
    bruegge_zuordnung_setzen(conn, "altealtealteaaaa", 111, "msfs2024")
    conn.execute("UPDATE bruegge_zuordnung SET gesehen_am = '2020-01-01T00:00:00Z'")
    bruegge_zuordnung_setzen(conn, "neueneueneueaaaa", 222, "msfs2024")
    conn.commit()

    assert bruegge_aufraeumen(conn, stunden=24) == 1
    uebrig = [r[0] for r in conn.execute("SELECT kennung FROM bruegge_zuordnung")]
    conn.close()
    assert uebrig == ["neueneueneueaaaa"]


# ---------------------------------------------------------------------------------------
# Der Sollzustand
# ---------------------------------------------------------------------------------------

def _soll_anlegen(db, soll_id, art="boot_gross", lat=47.7050, lon=8.9750, cid=None,
                  gilt_bis=None):
    from app.database import get_connection, bruegge_soll_setzen
    conn = get_connection(db)
    bruegge_soll_setzen(conn, soll_id, art, lat, lon, cid=cid, gilt_bis=gilt_bis)
    conn.commit()
    conn.close()


def test_soll_wird_an_die_bruegge_ausgeliefert(klient, tmp_path):
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    _soll_anlegen(db, "schiff-1")
    a = klient.post("/api/bruegge/melden", json=_meldung()).json()
    assert len(a["soll"]) == 1
    o = a["soll"][0]
    assert o["id"] == "schiff-1"
    assert o["art"] == "boot_gross"
    assert o["lat"] == pytest.approx(47.7050)


def test_soll_ohne_cid_gilt_fuer_alle(klient, tmp_path):
    """Eine Station für ein Event soll nicht je Pilot vervielfacht werden müssen."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    _soll_anlegen(db, "fuer-alle", cid=None)
    assert len(klient.post("/api/bruegge/melden", json=_meldung()).json()["soll"]) == 1


def test_soll_mit_fremder_cid_kommt_nicht_an(klient, tmp_path):
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    _soll_anlegen(db, "fuer-jemand-anderen", cid=999999)
    assert klient.post("/api/bruegge/melden", json=_meldung()).json()["soll"] == []


def test_abgelaufenes_soll_faellt_weg(klient, tmp_path):
    """Ein Event lässt sich mit Zeitfenster vorbereiten, ohne dass jemand hinterherräumt."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    _soll_anlegen(db, "abgelaufen", gilt_bis="2020-01-01T00:00:00Z")
    _soll_anlegen(db, "laeuft-noch", gilt_bis="2099-01-01T00:00:00Z")
    ids = [o["id"] for o in klient.post("/api/bruegge/melden", json=_meldung()).json()["soll"]]
    assert ids == ["laeuft-noch"]


def test_ohne_zuordnung_kommt_kein_soll(klient, tmp_path):
    """Ohne VATSIM geschieht nichts -- auch keine Objekte."""
    _soll_anlegen(str(tmp_path / "t.db"), "schiff-1")
    assert klient.post("/api/bruegge/melden", json=_meldung()).json()["soll"] == []


def test_unbekannte_art_wird_abgewiesen(klient, tmp_path):
    """Ein Tippfehler in der Art darf nicht als stille Nicht-Anforderung enden."""
    from app.auth import make_admin_token, make_confirm_token
    import app.main as main
    s = main.get_settings()
    kekse = {"fs_admin": make_admin_token(s.SECRET_KEY, s.ADMIN_PASSWORD),
             "fs_confirm": make_confirm_token(s.SECRET_KEY, s.ADMIN_PASSWORD, 9_999_999_999)}
    r = klient.post("/api/admin/bruegge/soll",
                    json={"art": "raumschiff", "lat": 53.0, "lon": 7.0}, cookies=kekse)
    assert r.status_code == 400
    assert "Art" in r.json()["detail"]


def test_robbe_ist_eine_erlaubte_art(klient, tmp_path):
    """Ohne diese Art ist der FriesenKieker nicht messbar.

    Weder MSFS noch X-Plane bringt eine Robbe mit -- deshalb gibt es seit dem 14.09.2026 ein
    EIGENES Modell, und seit dem 15.09.2026 in drei Groessen als drei Arten. Die Pruefliste
    hier ist die einzige Stelle, die das verhindern koennte -- und sie tat es einmal: `robbe`
    war nicht drin, das Modul konnte die Art setzen, und im Admin liess sie sich nicht
    anfordern. Aufgefallen ist das NICHT im Simulator, sondern beim Nachsehen.

    ⚠ Geprueft wird an `seehund_kuh`, nicht mehr an `robbe`. Der Sammelbegriff ist
    stillgelegt: Ein Soll-Eintrag traegt genau EINE Art, und die Bruegge nimmt daraus immer
    Rang 1 -- mit einer Sammelart staende an jeder Station dieselbe Kuh. Gemischte Kolonien
    gibt es nur ueber getrennte Arten (Nutzerwunsch: *"unsere robben sollen schon trennbar
    sein. also bitte 3 Arten fuer Robben."*).
    """
    from app.auth import make_admin_token, make_confirm_token
    import app.main as main
    s = main.get_settings()
    kekse = {"fs_admin": make_admin_token(s.SECRET_KEY, s.ADMIN_PASSWORD),
             "fs_confirm": make_confirm_token(s.SECRET_KEY, s.ADMIN_PASSWORD, 9_999_999_999)}
    r = klient.post("/api/admin/bruegge/soll",
                    json={"art": "seehund_kuh", "lat": 53.7235, "lon": 7.2502}, cookies=kekse)
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------------------
# Die Rueckmeldung: was steht WIRKLICH?
#
# Der Block stand seit Fassung 1 im Protokoll und wurde von bruegge.cpp gesendet -- der
# Server hat ihn bis zum 12.09.2026 weggeworfen. Aufgefallen ist das erst im Simulator, als
# Punkt 2 der Messliste gemessen werden sollte und schlicht nichts da war.
# ---------------------------------------------------------------------------------------

def _steht_lesen(db, kennung="a3f9c1e0b2d48576"):
    import sqlite3
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM bruegge_steht WHERE kennung = ? ORDER BY id",
                     (kennung,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def test_steht_wird_festgehalten(klient, tmp_path):
    """DER Test gegen den Fund. Ohne die Auswertung im Endpunkt bleibt die Tabelle leer."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    klient.post("/api/bruegge/melden", json=_meldung(steht=[
        {"id": "baer-1", "zustand": "steht", "hoehe_ft": 1297.4, "seit_s": 143},
    ]))
    zeilen = _steht_lesen(db)
    assert len(zeilen) == 1
    assert zeilen[0]["zustand"] == "steht"
    assert zeilen[0]["hoehe_ft"] == pytest.approx(1297.4)
    assert zeilen[0]["seit_s"] == 143


def test_ein_fehlschlag_kommt_mit_grund_an(klient, tmp_path):
    """Der wichtigste Fall: Der Server MUSS erfahren, dass eine Stelle unbrauchbar ist."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    klient.post("/api/bruegge/melden", json=_meldung(steht=[
        {"id": "station-7", "zustand": "fehlgeschlagen", "fehler": "KEINE_ANTWORT"},
    ]))
    z = _steht_lesen(db)[0]
    assert z["zustand"] == "fehlgeschlagen"
    assert z["fehler"] == "KEINE_ANTWORT"
    assert z["hoehe_ft"] is None


def test_die_rueckmeldung_ist_vollstaendig_und_ersetzt(klient, tmp_path):
    """`steht` ist die ganze Lage, kein Zuwachs -- wie `soll` in der Gegenrichtung.

    Sonst behauptete eine stehengebliebene Zeile, ein Objekt staende noch, das die Bruegge
    laengst vergessen hat.
    """
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    klient.post("/api/bruegge/melden", json=_meldung(steht=[
        {"id": "a", "zustand": "steht"}, {"id": "b", "zustand": "steht"},
    ]))
    assert [z["id"] for z in _steht_lesen(db)] == ["a", "b"]
    klient.post("/api/bruegge/melden", json=_meldung(steht=[{"id": "b", "zustand": "steht"}]))
    assert [z["id"] for z in _steht_lesen(db)] == ["b"]


def test_zwei_simulatoren_melden_dasselbe_objekt_getrennt(klient, tmp_path):
    """Ein `soll`-Eintrag ohne cid gilt fuer ALLE -- er hat so viele Wirklichkeiten wie Piloten.

    Genau deshalb ist der Schluessel (kennung, id) und nicht id allein.
    """
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    klient.post("/api/bruegge/melden",
                json=_meldung(kennung="aaaa", steht=[{"id": "s1", "zustand": "steht"}]))
    klient.post("/api/bruegge/melden",
                json=_meldung(kennung="bbbb",
                              steht=[{"id": "s1", "zustand": "fehlgeschlagen",
                                      "fehler": "KEINE_ANTWORT"}]))
    assert _steht_lesen(db, "aaaa")[0]["zustand"] == "steht"
    assert _steht_lesen(db, "bbbb")[0]["zustand"] == "fehlgeschlagen"


def test_muell_in_der_rueckmeldung_wirft_den_endpunkt_nicht_um(klient, tmp_path):
    """Der Endpunkt liegt NICHT hinter dem Login -- jeder kann ihn bedienen.

    Erwartet wird deshalb: verdauen, was verdaulich ist, den Rest verwerfen, und in keinem
    Fall eine 500 -- die waere fuer einen offenen Endpunkt eine Einladung.
    """
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    r = klient.post("/api/bruegge/melden", json=_meldung(steht=[
        {"id": "gut", "zustand": "steht", "hoehe_ft": "keine Zahl", "seit_s": None},
        {"id": "ohne-zustand"},
        "gar kein Objekt",
        {"zustand": "steht"},
        {"id": "x" * 500, "zustand": "steht"},
    ]))
    assert r.status_code == 200
    ids = [z["id"] for z in _steht_lesen(db)]
    assert "gut" in ids and "ohne-zustand" not in ids
    assert all(len(i) <= 64 for i in ids)
    assert [z for z in _steht_lesen(db) if z["id"] == "gut"][0]["hoehe_ft"] is None


def test_steht_ohne_zuordnung_wird_nicht_geschrieben(klient, tmp_path):
    """Ohne VATSIM geschieht nichts -- auch kein Festhalten fremder Rueckmeldungen.

    Sonst waere der offene Endpunkt eine Ablage, die jeder ungefragt fuellen kann.
    """
    db = str(tmp_path / "t.db")
    klient.post("/api/bruegge/melden", json=_meldung(steht=[{"id": "x", "zustand": "steht"}]))
    assert _steht_lesen(db) == []


def test_alte_rueckmeldungen_werden_aufgeraeumt(tmp_path):
    """Karteileichen: `bruegge_steht` haengt an der Kennung, nicht an der cid.

    `bruegge_position_loeschen` beim Loesen der Zuordnung erfasst sie deshalb nicht -- und
    das Loesen ist ohnehin nur einer der Wege, auf denen eine Bruegge verschwindet. Wer den
    Simulator schliesst, loest gar nichts aus.
    """
    import sqlite3
    from app.database import init_db, get_connection, bruegge_steht_melden, bruegge_aufraeumen

    db = str(tmp_path / "t.db")
    init_db(db)
    conn = get_connection(db)
    bruegge_steht_melden(conn, "alte-bruegge", 111, [{"id": "x", "zustand": "steht"}])
    conn.execute("UPDATE bruegge_steht SET gemeldet_am = '2020-01-01T00:00:00Z'")
    bruegge_steht_melden(conn, "frische-bruegge", 222, [{"id": "y", "zustand": "steht"}])
    conn.commit()

    bruegge_aufraeumen(conn)
    conn.commit()
    uebrig = [r[0] for r in conn.execute("SELECT kennung FROM bruegge_steht")]
    conn.close()
    assert uebrig == ["frische-bruegge"]


def test_antwort_zu_gross_wird_geloggt_und_stoert_nicht(klient, tmp_path, caplog):
    """Die Bruegge meldet, wenn unsere Antwort nicht in ihren Puffer passte.

    Gemessen am 12.09.2026: 30 Objekte ergeben 3776 Bytes, der Puffer stand auf 4096. Bei
    SOLL_MAX = 32 lief er ueber -- lautlos, denn ein abgeschnittenes JSON sieht von aussen
    aus wie Objekte, die der Simulator nicht setzen wollte.

    Der Endpunkt darf daran nicht scheitern: Die Meldung ist im Uebrigen gueltig, und die
    Position gehoert trotzdem verarbeitet.
    """
    import logging
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    with caplog.at_level(logging.WARNING):
        r = klient.post("/api/bruegge/melden", json=_meldung(antwort_zu_gross=17004))
    assert r.status_code == 200
    assert "17004" in caplog.text
    # Und die Meldung wurde ganz normal verarbeitet -- die Position steht.
    import sqlite3
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM bruegge_positions").fetchone()[0] == 1
    c.close()


def test_auf_boden_geht_bis_zur_bruegge_durch(klient, tmp_path):
    """Die Sonden-Idee: Der Server kann `OnGround=1` je Objekt verlangen.

    Gebaut fuer EINE Frage (Nutzeridee 12.09.2026): Setzt in WASM irgendeine Art mit
    OnGround=1 auf, meldet sie danach ihre TATSAECHLICHE Hoehe -- und das ist die
    Gelaendehoehe am ZIELORT, ohne Hoehenmodell und ohne dass jemand hinfliegen muss.
    Mit `Boat01` wirkt das Flag nicht; Tier, Bauwerk und Fahrzeug sind ungemessen.

    Der Test bindet nur den Weg: Was im Admin gesetzt wird, muss bei der Bruegge ankommen.
    """
    import sqlite3
    from app.database import init_db, get_connection, bruegge_soll_setzen

    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    conn = get_connection(db)
    bruegge_soll_setzen(conn, "sonde", "tier_gross", 53.78227, 7.92593, auf_boden=True)
    bruegge_soll_setzen(conn, "normal", "tier_gross", 53.78227, 7.92593)
    conn.commit()
    conn.close()

    soll = klient.post("/api/bruegge/melden", json=_meldung()).json()["soll"]
    nach_id = {o["id"]: o for o in soll}
    assert nach_id["sonde"]["auf_boden"] == 1
    assert nach_id["normal"]["auf_boden"] == 0


def test_die_admin_karte_hat_alles_was_sie_braucht():
    """Die Karte im Admin zeichnet Melder, angeforderte und stehende Objekte.

    Gebaut auf Nutzerwunsch (12.09.2026): Koordinaten von Hand einzutippen war die
    haeufigste Fehlerquelle des Abends -- ein Vorzeichen daneben, und das Objekt steht in
    einem anderen Land.

    Der Test bindet die drei Dinge, die beim Nachbauen leicht verlorengehen:
    das Aufbauen der Karte, das Nachziehen aus `bgLaden`, und `invalidateSize` -- ohne das
    bleibt eine Leaflet-Karte grau, wenn sie in einem versteckten Container entsteht.
    """
    from pathlib import Path
    html = Path(__file__).resolve().parents[1] / "app" / "static" / "admin.html"
    s = html.read_text(encoding="utf-8")

    assert 'id="bg-karte"' in s, "der Kartencontainer fehlt"
    assert "bgKarteAufbauen" in s and "bgKarteFuellen" in s
    # Ohne invalidateSize bleibt die Karte grau -- sie entsteht in einem hidden-Container.
    assert "invalidateSize" in s, "ohne invalidateSize bleibt die Karte grau"
    # Der Klick MUSS beide Felder fuellen, sonst ist die Karte nur Zierat.
    assert "'bg-lat').value = e.latlng.lat" in s
    assert "'bg-lon').value = e.latlng.lng" in s
    # Und bgLaden muss den Stand weiterreichen, sonst zeigt die Karte nie etwas an.
    assert "_bgStand = {" in s and "if (_bgKarte) bgKarteFuellen();" in s


# ---------------------------------------------------------------------------------------
# Der Objektkatalog
#
# Entstanden aus einer Nutzerforderung (12.09.2026): ein Verzeichnis aller Objekte, die
# sich hinstellen lassen, je Simulator und mit der Abhaengigkeit dahinter. Die Begruendung
# steckt in den Zahlen -- von 45 Tiertiteln des 2020er Bestands laufen in MSFS 2024 nur 7,
# und welche, verraet keine Dokumentation.
# ---------------------------------------------------------------------------------------

def _admin_kekse():
    from app.auth import make_admin_token, make_confirm_token
    import app.main as main
    s = main.get_settings()
    return {"fs_admin": make_admin_token(s.SECRET_KEY, s.ADMIN_PASSWORD),
            "fs_confirm": make_confirm_token(s.SECRET_KEY, s.ADMIN_PASSWORD, 9_999_999_999)}


def test_katalog_nimmt_eintraege_und_zaehlt_sie(klient):
    r = klient.post("/api/admin/bruegge/katalog", cookies=_admin_kekse(), json={"eintraege": [
        {"simulator": "msfs2024", "titel": "Boat01", "quelle": "bord", "kategorie": "Boats"},
        {"simulator": "msfs2024", "titel": "ahqa seal moving", "quelle": "community",
         "paket": "human-library-animated", "kategorie": "Animals"},
        {"simulator": "xplane12", "titel": "Resources/.../SailBoat.obj", "quelle": "bord"},
    ]})
    assert r.status_code == 200
    d = r.json()
    assert d["eingetragen"] == 3
    nach = {(z["simulator"], z["quelle"]): z for z in d["zusammenfassung"]}
    assert nach[("msfs2024", "community")]["gesamt"] == 1
    assert nach[("xplane12", "bord")]["gesamt"] == 1


def test_ein_pruefergebnis_ueberlebt_das_neue_einlesen(klient):
    """DER Kernfall: Ein Simulator-Lauf ist teuer, ein Verzeichnislauf billig.

    Wer den Bestand neu einliest, darf die Arbeit eines Sim-Termins nicht wegwerfen --
    dieselbe Ueberlegung wie bei `gesehener_hash` in den AIP-Blaettern.
    """
    ein = {"simulator": "msfs2024", "titel": "Windmill", "quelle": "bord"}
    klient.post("/api/admin/bruegge/katalog", cookies=_admin_kekse(), json={"eintraege": [ein]})
    klient.post("/api/admin/bruegge/katalog/ergebnis", cookies=_admin_kekse(), json={
        "ergebnisse": [{"simulator": "msfs2024", "titel": "Windmill",
                        "ergebnis": "steht", "hoehe_ft": 1370.0}]})
    # Jetzt den Bestand NOCHMAL einlesen, mit geaendertem Paketnamen.
    ein2 = dict(ein, paket="anderes-paket")
    klient.post("/api/admin/bruegge/katalog", cookies=_admin_kekse(), json={"eintraege": [ein2]})

    d = klient.get("/api/admin/bruegge/katalog?simulator=msfs2024",
                   cookies=_admin_kekse()).json()
    z = [x for x in d["eintraege"] if x["titel"] == "Windmill"][0]
    assert z["ergebnis"] == "steht", "das Pruefergebnis wurde ueberschrieben"
    assert z["hoehe_ft"] == 1370.0
    assert z["paket"] == "anderes-paket", "der Bestand wurde NICHT nachgezogen"


def test_katalog_verwirft_muell_statt_ihn_zu_speichern(klient):
    r = klient.post("/api/admin/bruegge/katalog", cookies=_admin_kekse(), json={"eintraege": [
        {"simulator": "msfs2024", "titel": "gut", "quelle": "bord"},
        {"simulator": "msfs2024", "titel": "kein_quellentyp", "quelle": "erfunden"},
        {"titel": "ohne simulator", "quelle": "bord"},
        "gar kein Objekt",
    ]})
    assert r.status_code == 200
    assert r.json()["eingetragen"] == 1


def test_der_katalog_liegt_hinter_dem_admin(klient):
    """Er verraet, welche Addons auf dem Rechner des Piloten liegen -- das geht niemanden an."""
    for weg in ("/api/admin/bruegge/katalog",):
        assert klient.get(weg).status_code in (401, 403)
    assert klient.post("/api/admin/bruegge/katalog",
                       json={"eintraege": []}).status_code in (401, 403)


def test_katalog_trennt_fundort_von_pruefort(klient):
    """`simulator` sagt WO GEFUNDEN, `geprueft_in` WO GESETZT -- und das ist nicht dasselbe.

    Der interessanteste Teil des Katalogs haengt daran: `BlackBear` steht in der
    MSFS-2020-Installation und laesst sich in MSFS 2024 setzen, waehrend 38 seiner Nachbarn
    es nicht tun. Beim ersten Lauf am 12.09.2026 filterte das Pruefwerkzeug nach dem FUNDORT
    und uebersprang dadurch alle 200 Titel des 2020er Bestands.
    """
    klient.post("/api/admin/bruegge/katalog", cookies=_admin_kekse(), json={"eintraege": [
        {"simulator": "msfs2020", "titel": "BlackBear", "quelle": "bord"},
        {"simulator": "msfs2020", "titel": "AfricanElephant", "quelle": "bord"},
    ]})
    # In MSFS 2024 geprueft, obwohl in der 2020er Installation gefunden.
    klient.post("/api/admin/bruegge/katalog/ergebnis", cookies=_admin_kekse(), json={
        "ergebnisse": [{"simulator": "msfs2020", "titel": "BlackBear",
                        "geprueft_in": "msfs2024", "ergebnis": "steht"}]})

    # `offen_fuer=msfs2024` muss den geprueften AUSLASSEN und den anderen liefern --
    # unabhaengig davon, dass beide als msfs2020 eingetragen sind.
    d = klient.get("/api/admin/bruegge/katalog?offen_fuer=msfs2024",
                   cookies=_admin_kekse()).json()
    offen = {z["titel"] for z in d["eintraege"]}
    assert "AfricanElephant" in offen, "ein 2020er Titel gehoert im 2024er Lauf geprueft"
    assert "BlackBear" not in offen, "der wurde in msfs2024 schon geprueft"


def test_geratene_titel_kommen_gar_nicht_erst_in_die_pruefung(klient):
    """Bei gestreamten Paketen ohne entpackten Ordner steht nur der PAKETNAME im Katalog.

    Den zu setzen versuchen hiesse, einen Fehlschlag zu messen, den man selbst verursacht hat
    -- am 12.09.2026 standen so 49 "gescheiterte" Titel im Katalog, die nie welche waren.
    """
    klient.post("/api/admin/bruegge/katalog", cookies=_admin_kekse(), json={"eintraege": [
        {"simulator": "msfs2024", "titel": "echt", "quelle": "streamed"},
        {"simulator": "msfs2024", "titel": "animals", "quelle": "streamed",
         "bemerkung": "Titel unbekannt (Paket gestreamt, kein entpackter Ordner)"},
    ]})
    d = klient.get("/api/admin/bruegge/katalog?offen_fuer=msfs2024",
                   cookies=_admin_kekse()).json()
    offen = {z["titel"] for z in d["eintraege"]}
    assert "echt" in offen
    assert "animals" not in offen, "ein geratener Titel gehoert nicht in die Pruefung"


def test_die_gattungsliste_steht_nur_noch_an_einer_stelle():
    """Der Vorgaenger dieses Tests hielt ZWEI Listen gegeneinander -- und war damit selbst
    ein Beleg fuer das Problem.

    Bis zum 14.09.2026 stand dieselbe Aufzaehlung dreimal: `_BRUEGGE_GATTUNGEN` (main.py),
    `_bgGattungen` (admin.html) und `g_gattungen[]` in BEIDEN Bruegge-Quelltexten. Ein Test
    konnte nur zwei davon vergleichen, weil sich C++ von Python aus nicht laden laesst -- die
    dritte und vierte blieben ungeprueft. Und eine neue Art kostete einen Windows-Build,
    eine Verteilung an 61 Piloten UND einen Server-Deploy.

    Jetzt steht sie in der Tabelle `bruegge_art`. Dieser Test bindet die ABWESENHEIT der
    Konstanten -- wer eine neue danebenlegt, faengt von vorn an.
    """
    from pathlib import Path
    import app.main as main

    assert not hasattr(main, "_BRUEGGE_GATTUNGEN"), (
        "Die Arten gehoeren in die Datenbank, nicht in eine Konstante")
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "admin.html").read_text(
        encoding="utf-8")
    assert "const _bgGattungen = [" not in html, (
        "Der Admin laedt die Arten vom Server, er fuehrt sie nicht selbst")


def test_das_cid_feld_sucht_ueber_callsign_name_und_cid():
    """Eine CID ist eine siebenstellige Zahl ohne Aussagekraft -- wer sie eintippt, sieht
    nicht, ob er den richtigen erwischt hat. Nutzerwunsch 13.09.2026: FRS-Callsign davor.
    """
    from pathlib import Path
    s = (Path(__file__).resolve().parents[1] / "app" / "static" / "admin.html").read_text(
        encoding="utf-8")
    assert "bgPilotenLaden" in s and "/api/admin/pilots" in s
    # Callsign zuerst in der Zeile -- danach sucht man.
    assert "function bgPilotZeile" in s
    assert "rufe.includes(q)" in s, "es muss auch ueber das Callsign gesucht werden"
    # mousedown statt click: sonst schliesst der Picker vor dem Klick (Frachtart-Falle).
    assert "mousedown" in s
    # Und Freitext darf NICHT als CID durchgehen -- ein Objekt versehentlich fuer ALLE zu
    # setzen ist der teurere Fehler.
    assert "ist keine CID" in s


def test_auf_der_website_steht_der_volle_name():
    """„FriesenBrügge" ist der Name, „Brügge" nur unsere Abkürzung im Gespräch.

    Stehende Regel (Nutzer, 13.09.2026): *„Nur weil wir das abkürzen, muss das auf der
    Website immer so stehen."* Betroffen sind die Download-Seite, der Admin und der
    Änderungsverlauf — überall dort, wo ein Mitglied den Namen liest.

    Kommentare im Quelltext sind ausgenommen; dort ist „Brügge" die Arbeitsbezeichnung.
    """
    import json
    import re
    from pathlib import Path
    wurzel = Path(__file__).resolve().parents[1]

    # 1. Die Download-Seite -- sichtbarer Text, also alles ausserhalb von <script>.
    efb = (wurzel / "app" / "static" / "efb.html").read_text(encoding="utf-8")
    ohne_skript = re.sub(r"<script\b.*?</script>", "", efb, flags=re.S | re.I)
    nackt = re.findall(r"(?<!Friesen)(?<!friesen)\bBrügge\b", ohne_skript)
    assert not nackt, f"{len(nackt)}x Bruegge ohne Friesen auf der Download-Seite"

    # 2. Der Aenderungsverlauf -- er erscheint als Banner bei jedem Besucher.
    log = json.loads((wurzel / "app" / "CHANGELOG.json").read_text(encoding="utf-8"))
    for e in log:
        text = e["title"] + " " + " ".join(e.get("items", []))
        treffer = re.findall(r"(?<!Friesen)(?<!friesen)\bBrügge\b", text)
        assert not treffer, f"v{e['version']}: Bruegge ohne Friesen"


def test_ein_xplane_pfad_gehoert_nicht_in_einen_msfs_lauf(klient):
    """Ein X-Plane-Eintrag ist ein DATEIPFAD, kein Container-Titel -- in MSFS sinnlos.

    Ohne die Schranke lieferte `offen_fuer=msfs2024` am 13.09.2026 auch die 1146
    X-Plane-Objekte. Das waeren 1146 Versuche gewesen, die nur Fehlschlaege ergeben koennen,
    und ein Katalog voller falscher "geht nicht".

    MSFS 2020 und 2024 gehoeren dagegen ZUSAMMEN geprueft: Sie teilen sich den Bestand, und
    genau daran zeigt sich, welche 2020er Titel in 2024 ueberlebt haben.
    """
    klient.post("/api/admin/bruegge/katalog", cookies=_admin_kekse(), json={"eintraege": [
        {"simulator": "msfs2020", "titel": "BlackBear", "quelle": "bord"},
        {"simulator": "msfs2024", "titel": "Boat01", "quelle": "bord"},
        {"simulator": "xplane12", "titel": "Resources/.../SailBoat.obj", "quelle": "bord"},
    ]})
    fuer_msfs = {z["titel"] for z in klient.get(
        "/api/admin/bruegge/katalog?offen_fuer=msfs2024", cookies=_admin_kekse()
    ).json()["eintraege"]}
    assert "BlackBear" in fuer_msfs and "Boat01" in fuer_msfs
    assert "Resources/.../SailBoat.obj" not in fuer_msfs

    fuer_xp = {z["titel"] for z in klient.get(
        "/api/admin/bruegge/katalog?offen_fuer=xplane12", cookies=_admin_kekse()
    ).json()["eintraege"]}
    # Keine Gleichheit mehr: Seit dem 14.09.2026 legt die Erstbefuellung der Arten beim
    # Start weitere X-Plane-Pfade an (Ballons, Moewen, unseren eigenen Rauch), und die sind
    # naturgemaess ungeprueft. Gesichert wird, worum es hier geht -- dass die BAENDER
    # getrennt bleiben, nicht wie viele Zeilen zufaellig im Katalog stehen.
    assert "Resources/.../SailBoat.obj" in fuer_xp
    assert not any(t in fuer_xp for t in ("BlackBear", "Boat01"))
    assert all(t.startswith("Resources/") for t in fuer_xp)


def test_der_admin_setzt_objekte_standardmaessig_auf_den_boden(klient, tmp_path):
    """`auf_boden` ist die Vorgabe, nicht die Ausnahme.

    `OnGround=1` laesst den Simulator selbst aufsetzen und trifft bis 10 km Entfernung
    (13.09.2026 gemessen). Die Alternative -- eine gerechnete Hoehe -- gilt nur unter dem
    Flugzeug: Zwoelf Objekte in einem 180-m-Raster standen damit eines versunken, eines
    sauber, eines schwebend.

    Bis zum 13.09.2026 nahm der Endpunkt das Feld gar nicht entgegen, und der Admin setzte
    alles mit gerechneter Hoehe. Aufgefallen an einem Buckelwal, der sechs Fuss ueber dem
    Boden schwebte.
    """
    import sqlite3
    db = str(tmp_path / "t.db")
    k = _admin_kekse()

    klient.post("/api/admin/bruegge/soll", cookies=k,
                json={"art": "seehund_kuh", "lat": 53.0, "lon": 7.0, "id": "ohne-angabe"})
    klient.post("/api/admin/bruegge/soll", cookies=k,
                json={"art": "seehund_kuh", "lat": 53.0, "lon": 7.0, "id": "ausdruecklich-aus",
                      "auf_boden": False})

    c = sqlite3.connect(db)
    werte = dict(c.execute("SELECT id, auf_boden FROM bruegge_soll").fetchall())
    c.close()
    assert werte["ohne-angabe"] == 1, "ohne Angabe muss auf_boden gelten"
    assert werte["ausdruecklich-aus"] == 0, "ausdrueckliches False muss durchkommen"


# ---------------------------------------------------------------------------------------
# Protokollfassung 2: Die Titel kommen vom Server (14.09.2026)
# ---------------------------------------------------------------------------------------

def test_die_titel_kommen_mit_der_antwort(klient, tmp_path):
    """DAS IST DER GANZE UMBAU, in einem Test.

    Die Brügge führte bis zum 14.09.2026 eine eigene Tabelle `g_gattungen[]` — eine neue Art
    kostete damit einen Windows-Build und eine Verteilung an 61 Piloten. Jetzt schickt der
    Server die Titel mit, und die Brügge probiert sie der Reihe nach durch.
    """
    _friese_anlegen(str(tmp_path / "t.db"))
    klient.post("/api/admin/bruegge/soll", cookies=_admin_kekse(),
                json={"art": "tier_gross", "lat": 53.78, "lon": 7.92, "id": "prueflauf"})

    antwort = klient.post("/api/bruegge/melden", json=_meldung(protokoll=2)).json()
    assert antwort["soll"] and antwort["soll"][0]["art"] == "tier_gross"
    assert "BlackBear" in antwort["arten"]["tier_gross"]
    # ... und was nachweislich scheitert, geht gar nicht erst hinaus (`PolarBear`,
    # EXCEPTION_22 am 12.09.2026). Das kann eine Tabelle im Client grundsätzlich nicht.
    assert "PolarBear" not in antwort["arten"]["tier_gross"]


def test_eine_x_plane_bruegge_bekommt_pfade_keine_titel(klient, tmp_path):
    """X-Plane kennt keine Container-Titel — dort ist der Dateipfad der Bezeichner.

    Die Trennung passiert auf dem Server, an `simulator` aus der Meldung. Eine Brügge, die
    beide Bänder bekäme, müsste selbst entscheiden — genau das soll sie nicht mehr.
    """
    _friese_anlegen(str(tmp_path / "t.db"))
    klient.post("/api/admin/bruegge/soll", cookies=_admin_kekse(),
                json={"art": "tier_gross", "lat": 53.78, "lon": 7.92, "id": "xp"})

    m = _meldung(protokoll=2)
    m["simulator"] = "xplane12"
    titel = klient.post("/api/bruegge/melden", json=m).json()["arten"]["tier_gross"]
    assert titel and all(t.startswith("Resources/") for t in titel)


def test_ohne_soll_gehen_auch_keine_titel_hinaus(klient, tmp_path):
    """Eine abgelehnte Meldung gibt keinen Zustand preis — auch keine Artenliste.

    Sonst verriete der Server einem Fremden, was er überhaupt zu bieten hat. Und wo nichts
    hinzustellen ist, braucht niemand Titel.
    """
    antwort = klient.post("/api/bruegge/melden", json=_meldung(protokoll=2)).json()
    assert antwort["soll"] == []
    assert "arten" not in antwort


def test_nur_die_angeforderten_arten_gehen_hinaus(klient, tmp_path):
    """Alles mitzuschicken wäre bequemer und kostete 914 Bytes statt ~200.

    Der Puffer (16384 in bruegge.cpp) trüge das — aber die Brügge kann mit Titeln zu Arten,
    die sie nicht setzen soll, nichts anfangen.
    """
    _friese_anlegen(str(tmp_path / "t.db"))
    klient.post("/api/admin/bruegge/soll", cookies=_admin_kekse(),
                json={"art": "tier_gross", "lat": 53.78, "lon": 7.92, "id": "nur-eins"})
    arten = klient.post("/api/bruegge/melden", json=_meldung(protokoll=2)).json()["arten"]
    assert list(arten) == ["tier_gross"]


# ---------------------------------------------------------------------------------------
# Das Verstoß-Fenster: die Zuordnung gilt, die Position nicht
# ---------------------------------------------------------------------------------------

def test_im_verstoss_fenster_bleiben_die_objekte_stehen(klient, tmp_path):
    """Ein einzelner Ausreißer darf der Brügge nicht alle Objekte wegnehmen.

    `soll` ist die VOLLSTÄNDIGE Liste dessen, was dastehen soll — kein Strom von Befehlen.
    Kommt sie leer zurück, räumt `soll_abgleichen` (friesenbruegge/msfs/bruegge.cpp) alles ab
    und setzt es drei Takte später neu. Bis zum 15.09.2026 löste genau das ein einziger
    VATSIM-Ausreißer aus: Der Verstoß-Zweig gab `cid = None` zurück, und ohne cid antwortet
    der Endpunkt mit leerem `soll`.

    Das Kniebrett macht es im selben Fall richtig — dort gilt die Zuordnung im Verstoß-Fenster
    weiter. Die Objekte hängen am Piloten, nicht an seiner Momentanposition.
    """
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    klient.post("/api/admin/bruegge/soll", cookies=_admin_kekse(),
                json={"art": "tier_gross", "lat": 53.78, "lon": 7.92, "id": "bleibt-stehen"})

    erste = klient.post("/api/bruegge/melden", json=_meldung()).json()
    assert erste["soll"], "Voraussetzung: das Objekt geht beim guten Fall mit"

    # 0,004° Breite ≈ 445 m: über PAARUNG_MIN_M (400, also ein Verstoß), aber unter
    # SPRUNG_M (500) — sonst greift die Sprungerkennung und löst die Zuordnung sofort.
    zweite = klient.post("/api/bruegge/melden",
                         json=_meldung(lat=53.78227 + 0.004)).json()
    assert zweite["soll"], "im Verstoß-Fenster darf `soll` NICHT leer werden"

    # ... und die unplausible Position darf trotzdem nicht in die Ablage.
    from app.database import get_connection
    conn = get_connection(db)
    zeile = conn.execute("SELECT lat FROM bruegge_positions WHERE cid = 1234567").fetchone()
    conn.close()
    assert zeile is not None
    assert abs(zeile[0] - 53.78227) < 1e-6, (
        "die Karte behält den letzten guten Punkt, statt dem Ausreißer zu folgen")


# ---------------------------------------------------------------------------------------
# Die alte Kollisionskennung — gemeldet, nicht behandelt
# ---------------------------------------------------------------------------------------

def test_die_kollisionskennung_wird_im_log_gemeldet(klient, tmp_path, caplog):
    """Damit sie beim nächsten Mal in Sekunden auffällt statt in Stunden.

    Die MSFS-Brügge baute ihre Kennung bis zum 14.09.2026 aus Modul-Adresse und `rand()` ohne
    `srand()` — in WASM auf jedem Rechner gleich. Zwei Piloten darunter, und der Server
    schrieb die Position des einen unter die CID des anderen.

    ⚠ Bewusst NUR eine Warnung: Den Wert als „keine Kennung" zu behandeln und eine zuzuteilen
    macht es schlimmer, weil eine alte Brügge die Zuteilung nicht annehmen kann
    (`kennung_uebernehmen` gibt es erst in der neuen Fassung). Sie zöge dann bei jeder Meldung
    eine frische — ohne Sprungerkennung, ohne Verstoßzähler, ohne Hysterese.
    """
    import logging
    import app.main as main

    main._bruegge_kollision_gemeldet.clear()
    _friese_anlegen(str(tmp_path / "t.db"))
    with caplog.at_level(logging.WARNING, logger="app.main"):
        klient.post("/api/bruegge/melden",
                    json=_meldung(kennung=main._BRUEGGE_KOLLISIONSKENNUNG))
    treffer = [r for r in caplog.records if "KOLLISIONSKENNUNG" in r.getMessage()]
    assert len(treffer) == 1, "die alte Kennung muss auffallen"
    assert main._BRUEGGE_KOLLISIONSKENNUNG in treffer[0].getMessage()


def test_die_warnung_flutet_das_log_nicht(klient, tmp_path, caplog):
    """Die Brügge meldet im Sekundentakt — eine Zeile je Meldung wären 3600 in der Stunde.

    Das ist genau das Rauschen, gegen das der Log-Filter in nginx gebaut wurde
    (`access_log … if=$fs_bruegge_loggen`). Eine Warnung, die man wegfiltern muss, ist keine.
    """
    import logging
    import app.main as main

    main._bruegge_kollision_gemeldet.clear()
    _friese_anlegen(str(tmp_path / "t.db"))
    with caplog.at_level(logging.WARNING, logger="app.main"):
        for _ in range(5):
            klient.post("/api/bruegge/melden",
                        json=_meldung(kennung=main._BRUEGGE_KOLLISIONSKENNUNG))
    treffer = [r for r in caplog.records if "KOLLISIONSKENNUNG" in r.getMessage()]
    assert len(treffer) == 1, f"fünf Meldungen, aber {len(treffer)} Warnungen"


def test_eine_normale_kennung_loest_keine_warnung_aus(klient, tmp_path, caplog):
    import logging
    import app.main as main

    main._bruegge_kollision_gemeldet.clear()
    _friese_anlegen(str(tmp_path / "t.db"))
    with caplog.at_level(logging.WARNING, logger="app.main"):
        klient.post("/api/bruegge/melden", json=_meldung())
    assert not [r for r in caplog.records if "KOLLISIONSKENNUNG" in r.getMessage()]


# ---------------------------------------------------------------------------------------
# Der Katalog lernt aus der Rückmeldung
# ---------------------------------------------------------------------------------------

def _katalog_anlegen(db_pfad, eintraege):
    """(simulator, titel, art, status) direkt in den Katalog — der Admin-Weg bräuchte drei
    Aufrufe je Zeile und würde nur verdecken, worum es geht.

    ⚠ **`init_db` bringt einen GRUNDKATALOG mit**, und der ist keine leere Tafel: `tier_gross`
    hat dort in X-Plane bereits `deer_buck.obj` und `deer_doe.obj`. Wer hier einen einzelnen
    Titel anlegt und „genau einer" prüft, prüft in Wahrheit drei — die Tests waren beim ersten
    Anlauf genau daran rot, und der Code war richtig.

    Deshalb wird die Art vorher freigeräumt: Was der Test danach anlegt, ist alles, was es
    von ihr gibt.
    """
    from app.database import get_connection
    conn = get_connection(db_pfad)
    for art in {e[2] for e in eintraege}:
        conn.execute("UPDATE bruegge_katalog SET art = NULL, status = NULL WHERE art = ?",
                     (art,))
    for sim, titel, art, status in eintraege:
        conn.execute(
            "INSERT OR REPLACE INTO bruegge_katalog (simulator, titel, art, status, quelle) "
            "VALUES (?, ?, ?, ?, 'bord')", (sim, titel, art, status))
    conn.commit()
    conn.close()


def _katalog_lesen(db_pfad, art):
    from app.database import get_connection
    conn = get_connection(db_pfad)
    rows = conn.execute(
        "SELECT titel, simulator, ergebnis, status, fehler FROM bruegge_katalog "
        "WHERE art = ? ORDER BY simulator, titel", (art,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _soll_und_melden(klient, steht, simulator="xplane12", art="tier_gross"):
    """⚠ Die Art muss in BEIDEN Töpfen einen Titel haben, sonst lehnt der Admin-Endpunkt das
    Anfordern ab (`bruegge_arten_beidseitig`, stehende Regel seit 14.09.2026: eine Art, die
    ein Simulator nicht zeigen kann, geht an KEINEN hinaus). Ohne Soll-Zeile gibt es keine
    Art zur Objekt-`id`, und der Rückfluss hätte nichts zu lernen — die Tests hier wären
    dann grün, ohne etwas zu prüfen."""
    klient.post("/api/admin/bruegge/soll", cookies=_admin_kekse(),
                json={"art": art, "lat": 53.78, "lon": 7.92, "id": "t1"})
    return klient.post("/api/bruegge/melden",
                       json=_meldung(simulator=simulator, steht=steht))


#: Der Gegenpart im jeweils anderen Topf -- nur damit die Art überhaupt anforderbar ist.
#: Er wird in den Prüfungen nicht angefasst und darf sich auch nicht verändern.
def _gegenpart(simulator):
    return ("msfs2024", "Gegenpart_Deer") if simulator == "xplane12" \
        else ("xplane12", "gegenpart.obj")


def test_kein_titel_ging_legt_die_ganze_art_still(klient, tmp_path):
    """Die Brügge hat ALLE Titel durchprobiert — dann gilt es für jeden von ihnen.

    Ohne diesen Rückfluss wusste der Katalog nach Monaten Betrieb nicht, was funktioniert:
    2932 X-Plane-Titel, kein einziges Prüfergebnis. Und `bruegge_arten_beidseitig` hängt
    daran — die Regel fußt auf `status='aus'`.
    """
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    _katalog_anlegen(db, [
        ("xplane12", "a.obj", "tier_gross", "aktiv"),
        ("xplane12", "b.obj", "tier_gross", "aktiv"),
        ("msfs2024", "Deer", "tier_gross", "aktiv"),   # darf NICHT mitsterben
    ])
    _soll_und_melden(klient, [{"id": "t1", "zustand": "fehlgeschlagen",
                               "fehler": "KEIN_MODELL_MEHR"}])

    zeilen = {(z["simulator"], z["titel"]): z for z in _katalog_lesen(db, "tier_gross")}
    assert zeilen[("xplane12", "a.obj")]["status"] == "aus"
    assert zeilen[("xplane12", "b.obj")]["status"] == "aus"
    assert zeilen[("xplane12", "a.obj")]["ergebnis"] == "fehlgeschlagen"
    assert zeilen[("msfs2024", "Deer")]["status"] == "aktiv", (
        "ein X-Plane-Fehlschlag darf keinen MSFS-Titel stilllegen")


def test_msfs_sagt_dasselbe_mit_einem_anderen_wort(klient, tmp_path):
    """MSFS meldet `KEIN_TITEL_GING`, X-Plane `KEIN_MODELL_MEHR` — beide müssen greifen."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    _katalog_anlegen(db, [("msfs2024", "Deer", "tier_gross", "aktiv"),
                          ("msfs2024", "Elk", "tier_gross", "aktiv"),
                          (*_gegenpart("msfs2024"), "tier_gross", "aktiv")])
    _soll_und_melden(klient, [{"id": "t1", "zustand": "fehlgeschlagen",
                               "fehler": "KEIN_TITEL_GING"}], simulator="msfs2024")
    zeilen = {z["titel"]: z for z in _katalog_lesen(db, "tier_gross")}
    assert zeilen["Deer"]["status"] == "aus"
    assert zeilen["Elk"]["status"] == "aus"
    assert zeilen["gegenpart.obj"]["status"] == "aktiv", "X-Plane bleibt unberührt"


def test_ein_einzelner_fehlschlag_raet_nicht(klient, tmp_path):
    """Bei mehreren Titeln nennt die Rückmeldung nicht, WELCHER scheiterte.

    Ein falsch stillgelegter Titel wäre schlimmer als eine Lücke — man sieht ihm nicht an,
    dass er zu Unrecht aus ist.
    """
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    _katalog_anlegen(db, [("xplane12", "a.obj", "tier_gross", "aktiv"),
                          ("xplane12", "b.obj", "tier_gross", "aktiv"),
                          (*_gegenpart("xplane12"), "tier_gross", "aktiv")])
    _soll_und_melden(klient, [{"id": "t1", "zustand": "fehlgeschlagen",
                               "fehler": "NAME_UNRECOGNIZED"}])
    assert all(z["ergebnis"] is None for z in _katalog_lesen(db, "tier_gross")), \
        "bei zwei Titeln darf nichts geschrieben werden"


def test_bei_genau_einem_titel_ist_auch_das_einzelergebnis_eindeutig(klient, tmp_path):
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    _katalog_anlegen(db, [("xplane12", "nur_der.obj", "tier_gross", "aktiv"),
                          (*_gegenpart("xplane12"), "tier_gross", "aktiv")])
    _soll_und_melden(klient, [{"id": "t1", "zustand": "fehlgeschlagen",
                               "fehler": "NAME_UNRECOGNIZED"}])
    z = [x for x in _katalog_lesen(db, "tier_gross") if x["titel"] != "Gegenpart_Deer"][0]
    assert z["ergebnis"] == "fehlgeschlagen" and z["status"] == "aus"
    assert z["fehler"] == "NAME_UNRECOGNIZED"


def test_ein_gelungener_versuch_wird_vermerkt_aber_aendert_den_status_nicht(klient, tmp_path):
    """`steht` ist eine Beobachtung, keine Entscheidung.

    Die Zuordnung einer Art gehört dem Nutzer (`bruegge_arten_zuordnen`); ein gelungener
    Setzversuch hält nur fest, dass es geklappt hat. Der Status wird ausschließlich beim
    Fehlschlag angefasst — und dann nur in eine Richtung.

    ⚠ Ein Titel auf `aus` taucht in dieser Prüfung bewusst nicht auf: Er wird gar nicht erst
    ausgeliefert (`bruegge_titel_fuer` filtert auf `status='aktiv'`), die Brügge kann ihn
    also nicht probiert haben. Ein Test dafür prüfte einen Fall, den es nicht gibt.
    """
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    _katalog_anlegen(db, [("xplane12", "nur_der.obj", "tier_gross", "aktiv"),
                          (*_gegenpart("xplane12"), "tier_gross", "aktiv")])
    _soll_und_melden(klient, [{"id": "t1", "zustand": "steht", "hoehe_ft": 12.5}])
    z = [x for x in _katalog_lesen(db, "tier_gross") if x["titel"] == "nur_der.obj"][0]
    assert z["ergebnis"] == "steht"
    assert z["status"] == "aktiv", "der Status bleibt, wie der Nutzer ihn gesetzt hat"


def test_verschwunden_sagt_nichts_ueber_den_titel(klient, tmp_path):
    """Das Objekt WAR da — der Grund kann die Reality Bubble sein, nicht der Titel."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    _katalog_anlegen(db, [("xplane12", "nur_der.obj", "tier_gross", "aktiv"),
                          (*_gegenpart("xplane12"), "tier_gross", "aktiv")])
    _soll_und_melden(klient, [{"id": "t1", "zustand": "verschwunden", "seit_s": 12}])
    z = [x for x in _katalog_lesen(db, "tier_gross") if x["titel"] != "Gegenpart_Deer"][0]
    assert z["ergebnis"] is None and z["status"] == "aktiv"
