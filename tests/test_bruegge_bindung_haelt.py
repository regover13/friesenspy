# -*- coding: utf-8 -*-
"""Eine Brügge wird nicht zu einem fremden Piloten (16./17.09.2026).

**DER FALL, GEMESSEN AN DER PRODUKTION.** Am 16.09.2026 stand in ``bruegge_steht`` eine
Kennung unter einer fremden CID. Rekonstruiert aus Logs und Positionsverlauf:

====================  ========================================================
15:12:53Z             letzte VATSIM-Position des Piloten (Bodensee) — er loggt ab
15:09Z bis 16:15Z     1322 × „keine Zuordnung", alle 3 s (``_BRUEGGE_TAKT_UNERKANNT_S``)
dazwischen            der Simulator läuft weiter, ein Flug auf Wangerooge wird geladen
16:14:08Z–16:15:08Z   ein ANDERER Friese steht dort unbewegt, 6 ft
16:15:22Z             seine Brügge meldet — und bekommt dessen CID
====================  ========================================================

**Nach allen Regeln korrekt**: in der Nähe, frei, eindeutig. Nähe, Vorsprung und die
Belegt-Sperre stammen eins zu eins aus dem Kniebrett (``app/bruegge.py:179``) und griffen
alle. Sie konnten den Fall nicht verhindern, weil der andere Pilot tatsächlich frei und
tatsächlich der einzige in Reichweite war.

⚠ **Der Unterschied, um den es geht** (Nutzer, 16.09.2026): *„Das ist ein Grund, die Bindung
aufzugeben. Aber kein Grund, eine 700 km entfernte aufzunehmen oder überhaupt in Betracht zu
ziehen."* Lösen und Neubinden sind zwei Vorgänge — nur der erste folgt daraus, dass eine
Position nicht mehr passt.

**Warum das Kniebrett den Fehler nicht kennt:** Es muss seinen *eigenen* Piloten nie erraten;
wer es ist, weiß es aus der Anmeldung. Es ordnet nur fremden Verkehr zu, und eine Fehlpaarung
trifft dort einen fremden Punkt auf der Karte. Die Brügge rät sich selbst — rät sie falsch,
*ist* sie jemand anderes. Ihr einziges Gegenstück zur ``device_id`` ist die Kennung, und
``bruegge_zuordnung_loesen`` hat sie beim ersten Verstoß weggeworfen.
"""

import pytest
from fastapi.testclient import TestClient

from tests.test_bruegge_endpunkt import _friese_anlegen, _meldung  # noqa: F401


# Wangerooge und Bodensee -- die beiden Orte aus dem echten Fall.
WOOGE = (53.78701, 7.90987)
BODENSEE = (47.80592, 8.98069)

ICH = 1234567        # der Pilot, dem die Brügge gehört
FREMD = 7654321      # der andere Friese, der in Wooge steht


@pytest.fixture()
def klient(tmp_path, monkeypatch):
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


def _ausloggen(db_pfad, cid):
    """Der Pilot verlässt VATSIM -- seine Zeile in `live_positions` verschwindet."""
    from app.database import get_connection
    conn = get_connection(db_pfad)
    conn.execute("DELETE FROM live_positions WHERE cid = ?", (cid,))
    conn.commit()
    conn.close()


def _zuordnung(db_pfad, kennung):
    from app.database import get_connection, bruegge_zuordnung_holen
    conn = get_connection(db_pfad)
    z = bruegge_zuordnung_holen(conn, kennung)
    conn.close()
    return z


class TestDerFallVom16September:
    """⚠⚠ Der Kern dieser Datei -- Schritt für Schritt wie in der Produktion."""

    def test_die_bruegge_wird_nicht_zum_fremden_piloten(self, klient, tmp_path):
        db = str(tmp_path / "t.db")
        kennung = "a3f9c1e0b2d48576"

        # 1. Der eigene Pilot fliegt, die Brügge meldet, die Bindung steht.
        _friese_anlegen(db, cid=ICH, callsign="FRS49", lat=BODENSEE[0], lon=BODENSEE[1])
        r = klient.post("/api/bruegge/melden",
                        json=_meldung(lat=BODENSEE[0], lon=BODENSEE[1], kennung=kennung))
        assert r.status_code == 200
        assert _zuordnung(db, kennung)["cid"] == ICH

        # 2. Er loggt sich von VATSIM ab. Der Simulator läuft weiter.
        _ausloggen(db, ICH)

        # Die Bindung fällt -- erst nach mehreren Verstößen IN FOLGE, das ist gewollt.
        for _ in range(8):
            klient.post("/api/bruegge/melden",
                        json=_meldung(lat=BODENSEE[0], lon=BODENSEE[1], kennung=kennung))
        z = _zuordnung(db, kennung)
        assert z is not None, "die ZEILE muss bleiben -- sie sagt, wem die Kennung gehört"
        assert z["geloest_am"], "die BINDUNG muss fallen, der Partner ist fort"

        # 3. Ein anderer Friese steht in Wooge. Der Pilot lädt dort einen Flug.
        _friese_anlegen(db, cid=FREMD, callsign="FRS146", lat=WOOGE[0], lon=WOOGE[1])
        r = klient.post("/api/bruegge/melden",
                        json=_meldung(lat=WOOGE[0], lon=WOOGE[1], kennung=kennung))
        assert r.status_code == 200

        # ⭐ DIE EIGENTLICHE ZUSICHERUNG.
        z = _zuordnung(db, kennung)
        assert z["cid"] == ICH, (
            "Die Kennung wurde auf den fremden Piloten umgeschrieben -- genau der Fall vom "
            "16.09.2026."
        )
        assert z["geloest_am"], "und gebunden sein darf sie deswegen auch nicht"

        from app.database import get_connection, bruegge_position_holen
        conn = get_connection(db)
        assert bruegge_position_holen(conn, FREMD) is None, (
            "Die Sim-Position des einen wurde unter der CID des anderen abgelegt."
        )
        conn.close()

    def test_der_eigene_pilot_findet_zurueck(self, klient, tmp_path):
        """⚠ Die Gegenprobe -- ohne sie wäre die Schranke eine Sackgasse.

        Eine Brügge, die nach dem Lösen nie wieder binden könnte, wäre bis zum Aufräumen
        (24 h) tot. Meldet sich der eigene Pilot wieder auf VATSIM, muss dieselbe Zeile
        erneut greifen.
        """
        db = str(tmp_path / "t.db")
        kennung = "a3f9c1e0b2d48576"

        _friese_anlegen(db, cid=ICH, callsign="FRS49", lat=BODENSEE[0], lon=BODENSEE[1])
        klient.post("/api/bruegge/melden",
                    json=_meldung(lat=BODENSEE[0], lon=BODENSEE[1], kennung=kennung))
        _ausloggen(db, ICH)
        for _ in range(8):
            klient.post("/api/bruegge/melden",
                        json=_meldung(lat=BODENSEE[0], lon=BODENSEE[1], kennung=kennung))
        assert _zuordnung(db, kennung)["geloest_am"]

        # Er loggt sich wieder ein -- diesmal in Wooge, wo er auch steht.
        _friese_anlegen(db, cid=ICH, callsign="FRS49", lat=WOOGE[0], lon=WOOGE[1])
        klient.post("/api/bruegge/melden",
                    json=_meldung(lat=WOOGE[0], lon=WOOGE[1], kennung=kennung))

        z = _zuordnung(db, kennung)
        assert z["cid"] == ICH
        assert not z["geloest_am"], "die Bindung muss sich selbst heilen"

    def test_eine_unbekannte_kennung_bindet_weiterhin_frei(self, klient, tmp_path):
        """Die Schranke gilt NUR für erinnerte Kennungen.

        Eine Brügge, die zum ersten Mal meldet, hat keine Vorgeschichte -- für sie muss der
        Erstkontakt weiter funktionieren, sonst käme nie eine zustande.
        """
        db = str(tmp_path / "t.db")
        _friese_anlegen(db, cid=FREMD, callsign="FRS146", lat=WOOGE[0], lon=WOOGE[1])
        r = klient.post("/api/bruegge/melden",
                        json=_meldung(lat=WOOGE[0], lon=WOOGE[1], kennung=""))
        assert r.status_code == 200
        assert r.json().get("kennung"), "der Erstkontakt muss eine Kennung bekommen"


class TestDieKennungHaeltUeberDenSimNeustart:
    """Brügge 1.14.0 kann sie nicht mehr speichern -- also merkt sie sich der Server.

    Seit ein Modul MSFS 2020 und 2024 bedient, gibt es die Datei-API nicht mehr
    (``MSFS_IO.h`` fehlt dem 2020er SDK, und ein WASM-Import ist statisch). Die Brügge meldet
    nach jedem Start ohne Kennung.

    ⚠ Das ist nicht nur Bequemlichkeit: Ohne diese Zusicherung bekäme sie bei jedem Start
    eine neue, und die Erinnerung aus der Klasse darüber liefe ins Leere -- eine Kennung, die
    niemand wiedererkennt, kann auch nicht an ihre CID gebunden bleiben.
    """

    def test_derselbe_pilot_bekommt_dieselbe_kennung_zurueck(self, klient, tmp_path):
        db = str(tmp_path / "t.db")
        _friese_anlegen(db, cid=ICH, callsign="FRS49", lat=WOOGE[0], lon=WOOGE[1])

        r1 = klient.post("/api/bruegge/melden",
                         json=_meldung(lat=WOOGE[0], lon=WOOGE[1], kennung=""))
        erste = r1.json().get("kennung")
        assert erste

        # Simulator-Neustart: dieselbe Installation, aber ohne gespeicherte Kennung.
        r2 = klient.post("/api/bruegge/melden",
                         json=_meldung(lat=WOOGE[0], lon=WOOGE[1], kennung=""))
        assert r2.json().get("kennung") == erste, (
            "Nach dem Neustart eine neue Kennung -- die Wiedererkennung wäre dahin, und mit "
            "ihr die Bindung an die CID."
        )

    def test_der_andere_simulator_bekommt_eine_eigene(self, klient, tmp_path):
        """⚠ Der Simulator gehört in den Schlüssel.

        Der Nutzer wechselt an einem Tag mehrfach zwischen MSFS und X-Plane. Bekäme die
        X-Plane-Brügge die Kennung der MSFS-Brügge, erbte sie deren Vorgeschichte -- und
        beide könnten sich gegenseitig die Bindung lösen.
        """
        db = str(tmp_path / "t.db")
        _friese_anlegen(db, cid=ICH, callsign="FRS49", lat=WOOGE[0], lon=WOOGE[1])

        msfs = klient.post("/api/bruegge/melden",
                           json=_meldung(lat=WOOGE[0], lon=WOOGE[1], kennung="",
                                         simulator="msfs2024")).json().get("kennung")
        xp = klient.post("/api/bruegge/melden",
                         json=_meldung(lat=WOOGE[0], lon=WOOGE[1], kennung="",
                                       simulator="xplane12")).json().get("kennung")
        assert msfs and xp
        assert msfs != xp, "beide Simulatoren teilen sich sonst eine Kennung"

    def test_ein_sim_wechsel_loescht_die_andere_bindung_nicht(self, klient, tmp_path):
        """⚠⚠ Hier stand ``DELETE ... WHERE cid = ? AND kennung <> ?`` OHNE den Simulator.

        Ein Wechsel von MSFS zu X-Plane löschte damit die Bindung des jeweils anderen. Beim
        Zurückwechseln war die Kennung unbekannt, die Brügge lief in die Erstzuordnung --
        und genau dort konnte ein fremder Pilot hereinrutschen.

        Nutzer, 16.09.2026: *„Es geht um die Nutzung verschiedener Simulatoren an einem
        Rechner. Das kann nicht über 24 Stunden lang gehen! Die werden an einem Tag häufiger
        gewechselt."*
        """
        db = str(tmp_path / "t.db")
        _friese_anlegen(db, cid=ICH, callsign="FRS49", lat=WOOGE[0], lon=WOOGE[1])

        msfs = klient.post("/api/bruegge/melden",
                           json=_meldung(lat=WOOGE[0], lon=WOOGE[1], kennung="",
                                         simulator="msfs2024")).json().get("kennung")
        # Jetzt X-Plane -- derselbe Pilot, derselbe Rechner, anderer Simulator.
        klient.post("/api/bruegge/melden",
                    json=_meldung(lat=WOOGE[0], lon=WOOGE[1], kennung="",
                                  simulator="xplane12"))

        assert _zuordnung(db, msfs) is not None, (
            "Die MSFS-Bindung ist durch den Wechsel zu X-Plane verschwunden."
        )
