"""Das Kniebrett meldet SEIN GEBIET -- `/api/kniebrett/melden` (GitHub-Issue #23).

Der Unterschied zur FriesenBrügge steht in einem Satz: Die Brügge meldet **einen** Piloten
(sich selbst) und der Server rät aus der Position, wer das ist. Das Kniebrett meldet **alle
in Reichweite** und bringt die Identität mit -- es ist über die Sitzung authentifiziert
(`_current_cid`) und kennt die Rufzeichen aus seinem eigenen Sim-/VATSIM-Matching
(`_verkehrZusammenfuehren`). Deshalb gibt es hier kein Positionsmatching auf dem Server.

**Was diese Datei vor allem bewacht, ist nicht der Normalfall, sondern die drei Grenzen:**

1. **Der Ausschalter wirkt SERVERSEITIG.** Ein Client, der die Abschaltung übergeht, darf
   den Server nicht belasten -- verworfen wird, bevor irgendetwas Teures geschieht.
2. **Die Meldung geht in den Prozessspeicher, nicht in die Datenbank.** Fünf Kniebretter mit
   je zehn erkannten Flugzeugen wären 50 Schreibvorgänge je Sekunde, größtenteils redundant.
   Die Live-Karte speist sich ohnehin aus `VatsimPoller._bruegge_live`.
3. **Wer dieselbe CID mehrfach gemeldet bekommt, entscheidet EINMAL, wessen Meldung gilt.**

`bruegge_belegte_cids` wird hier bewusst NICHT angefasst: Diese Sperre ist gegen
*verwechselte* Identitäten gebaut (zwei Brüggen streiten um denselben Piloten), nicht gegen
mehrere Quellen für dieselbe, richtig erkannte CID.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.database import (
    get_connection,
    init_db,
    set_app_setting,
    upsert_live_position,
)
from app.forum_sso import USER_COOKIE, make_user_token

SECRET = "s3cr3t-key"
MELDER = 1602713          # der Pilot mit dem offenen Kniebrett
MELDER_CS = "FRS49"
FREMD = 1642160           # ein zweiter Friese, den das Kniebrett mitsieht
FREMD_CS = "FRS123"
DRITT = 1401925           # ein DRITTER mit eigenem Kniebrett -- er sieht dieselben wie MELDER
DRITT_CS = "FRS7"

# Ein Platz und seine Umgebung -- Norddeich, wie überall sonst in diesen Tests.
LAT, LON = 53.78227, 7.92593


from app.poller import VatsimPoller


class _PollerAttrappe(VatsimPoller):
    """Nur so viel Poller, wie der Endpunkt anfasst.

    Die App-Fixture baut keinen echten (das gilt für die Brügge-Tests genauso) -- und der
    Endpunkt darf daran nicht scheitern, sondern nur die Live-Anzeige verlieren.

    ⚠ **Sie ERBT, statt Methoden einzeln zu kopieren.** Die erste Fassung hat sich die
    beiden Methoden per `__get__` geholt und die Konstanten von Hand nachgezogen -- und ist
    prompt gebrochen, als eine neue Konstante dazukam (`KNIEBRETT_ZUSCHLAG_S`). Eine
    Attrappe, die bei jeder Erweiterung nachgepflegt werden muss, prüft irgendwann etwas
    anderes als die Produktion. `__init__` bleibt außen vor: Der echte baut Scheduler und
    HTTP-Client auf, und nichts davon wird hier angefasst.
    """

    def __init__(self, friesen=None):        # bewusst ohne super().__init__()
        self._bruegge_live = {}
        self.friesen_snapshot = list(friesen or [])
        self.friesen_snapshot_ts = time.time()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    pfad = str(tmp_path / "t.db")
    init_db(pfad)
    settings = SimpleNamespace(
        DB_PATH=pfad, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD="pw",
        SSO_SECRET="shared-forum-secret", FORUM_SSO_URL="https://board.example/sso",
        FORUM_SSO_CALLBACK="https://friesenspy.example/sso/callback",
        USER_SESSION_MAX_AGE_SEC=1200, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main._reset_gate_cache()
    if hasattr(main, "_reset_kniebrett_cache"):
        main._reset_kniebrett_cache()

    conn = get_connection(pfad)
    try:
        # Beide Friesen sind auf VATSIM, dicht beieinander am Platz.
        # Der Sender haengt an der Sitzung -- ohne scharfgeschaltetes Board-Login gibt
        # `_current_cid` grundsaetzlich None zurueck, und dann meldet niemand.
        set_app_setting(conn, "forum_login_enabled", "1")
        _friese(conn, MELDER, MELDER_CS, LAT, LON)
        _friese(conn, FREMD, FREMD_CS, LAT + 0.001, LON + 0.001)
        _friese(conn, DRITT, DRITT_CS, LAT + 0.002, LON + 0.002)
        conn.commit()
    finally:
        conn.close()

    klient = TestClient(main.app)
    poller = _PollerAttrappe(friesen=_friesen_rohzeilen())
    main.app.state.poller = poller
    yield SimpleNamespace(client=klient, db=pfad, poller=poller)
    if hasattr(main.app.state, "poller"):
        del main.app.state._state["poller"]


def _friese(conn, cid, cs, lat, lon, alt=500, gs=0, hdg=210):
    upsert_live_position(
        conn, cid=cid, callsign=cs, aircraft="C172", departure="EDWS", arrival="EDWS",
        latitude=lat, longitude=lon, altitude=alt, groundspeed=gs, heading=hdg,
        logon_time="2026-09-15T10:00:00Z",
    )


def _friesen_rohzeilen():
    """Derselbe Bestand wie in `live_positions` -- so, wie der Poller ihn im Speicher hält."""
    jetzt = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return [
        {"cid": MELDER, "callsign": MELDER_CS, "latitude": LAT, "longitude": LON,
         "altitude": 500.0, "groundspeed": 0.0, "heading": 210.0, "updated_at": jetzt},
        {"cid": FREMD, "callsign": FREMD_CS, "latitude": LAT + 0.001, "longitude": LON + 0.001,
         "altitude": 500.0, "groundspeed": 0.0, "heading": 210.0, "updated_at": jetzt},
        {"cid": DRITT, "callsign": DRITT_CS, "latitude": LAT + 0.002, "longitude": LON + 0.002,
         "altitude": 500.0, "groundspeed": 0.0, "heading": 210.0, "updated_at": jetzt},
    ]


def _cookie(cid: int = MELDER) -> dict:
    return {USER_COOKIE: make_user_token(SECRET, "Tobias", str(cid), False, time.time() + 3600)}


def _flugzeug(cs=FREMD_CS, lat=LAT + 0.001, lon=LON + 0.001, **mehr):
    e = {"cs": cs, "lat": lat, "lon": lon, "alt": 500.0, "gs": 0.0, "hdg": 210.0, "gnd": True}
    e.update(mehr)
    return e


def _melden(env, flugzeuge, cid=MELDER):
    return env.client.post("/api/kniebrett/melden",
                           json={"protokoll": 1, "flugzeuge": flugzeuge},
                           cookies=_cookie(cid))


def _modus_setzen(env, wert, cid=None):
    conn = get_connection(env.db)
    try:
        if cid is None:
            set_app_setting(conn, "kniebrett_melden_modus", wert)
        else:
            from app.database import kniebrett_modus_setzen
            kniebrett_modus_setzen(conn, cid, wert)
        conn.commit()
    finally:
        conn.close()
    main._reset_kniebrett_cache()


# ---------------------------------------------------------------------------------------
#  1. Der Ausschalter -- und zwar serverseitig
# ---------------------------------------------------------------------------------------

class TestAusschalter:
    def test_ohne_einstellung_ist_aus(self, env):
        """Die Vorgabe ist `aus`. Gebaut wird vor der Sichtbarkeitsentscheidung (#35) --
        wer nichts einstellt, bekommt nichts, auch nicht versehentlich durch einen Deploy."""
        r = _melden(env, [_flugzeug()])
        assert r.status_code == 200
        assert r.json()["modus"] == "aus"
        assert r.json()["uebernommen"] == 0
        assert env.poller._bruegge_live == {}

    def test_aus_kostet_den_client_fast_keine_anfragen_mehr(self, env):
        """`aus` ist ein langer Takt, keine 0: Ein Kniebrett, das gar keine Antwort mehr
        bekäme, könnte Abschaltung nicht von Netzausfall unterscheiden -- dasselbe Muster
        wie bei `_bruegge_takt`. Und über dieselbe Antwort kommt das Wiedereinschalten an.

        ⚠ Hier stand `>= 300`, und das war zu grob gedacht: Der Wert muss nach OBEN begrenzt
        sein, nicht nach unten (s. TestAusTaktIstKurzGenug). Ein Takt von 900 s macht aus dem
        Wiedereinschalten eine Viertelstunde Warten."""
        r = _melden(env, [])
        takt = r.json()["naechste_frage_in_s"]
        assert takt >= 30                      # nicht im Regeltakt weiterreden
        assert takt <= 60                      # aber auch nicht verstummen

    def test_ein_client_der_die_abschaltung_uebergeht_wird_verworfen(self, env):
        """Der eigentliche Punkt: Nicht der Client entscheidet, ob er schweigt."""
        _modus_setzen(env, "aus")
        r = _melden(env, [_flugzeug(), _flugzeug(cs=MELDER_CS, lat=LAT, lon=LON)])
        assert r.json()["uebernommen"] == 0
        assert env.poller._bruegge_live == {}

    def test_alle_nimmt_fremde_mit(self, env):
        _modus_setzen(env, "alle")
        r = _melden(env, [_flugzeug()])
        assert r.json()["modus"] == "alle"
        assert r.json()["uebernommen"] == 1
        assert FREMD in env.poller._bruegge_live

    def test_eigene_nimmt_nur_den_melder(self, env):
        """Der mittlere Zustand: Das Kniebrett meldet wie eine Brügge -- nur sich selbst."""
        _modus_setzen(env, "eigene")
        r = _melden(env, [_flugzeug(), _flugzeug(cs=MELDER_CS, lat=LAT, lon=LON)])
        assert r.json()["modus"] == "eigene"
        assert r.json()["uebernommen"] == 1
        assert list(env.poller._bruegge_live) == [MELDER]

    def test_der_takt_kommt_vom_server(self, env):
        _modus_setzen(env, "alle")
        conn = get_connection(env.db)
        try:
            set_app_setting(conn, "kniebrett_takt_s", "5")
            conn.commit()
        finally:
            conn.close()
        main._reset_kniebrett_cache()
        assert _melden(env, [_flugzeug()]).json()["naechste_frage_in_s"] == 5


class TestSchalterJePilot:
    def test_ein_pilot_laesst_sich_einzeln_abschalten(self, env):
        _modus_setzen(env, "alle")
        _modus_setzen(env, "aus", cid=MELDER)
        assert _melden(env, [_flugzeug()]).json()["uebernommen"] == 0

    def test_ein_pilot_laesst_sich_einzeln_auf_eigene_begrenzen(self, env):
        _modus_setzen(env, "alle")
        _modus_setzen(env, "eigene", cid=MELDER)
        r = _melden(env, [_flugzeug(), _flugzeug(cs=MELDER_CS, lat=LAT, lon=LON)])
        assert r.json()["modus"] == "eigene"
        assert list(env.poller._bruegge_live) == [MELDER]

    def test_der_globale_schalter_ist_ein_deckel_kein_vorschlag(self, env):
        """Steht global `eigene`, hebt kein Pilot-Eintrag das auf. Sonst wäre die globale
        Drossel -- der Hebel für den Fall, dass es im Betrieb klemmt -- wirkungslos."""
        _modus_setzen(env, "eigene")
        _modus_setzen(env, "alle", cid=MELDER)
        r = _melden(env, [_flugzeug()])
        assert r.json()["modus"] == "eigene"
        assert r.json()["uebernommen"] == 0

    def test_ein_anderer_pilot_bleibt_unberuehrt(self, env):
        _modus_setzen(env, "alle")
        _modus_setzen(env, "aus", cid=FREMD)
        assert _melden(env, [_flugzeug()]).json()["uebernommen"] == 1


# ---------------------------------------------------------------------------------------
#  2. Die Datenbank bleibt außen vor
# ---------------------------------------------------------------------------------------

class TestKeineDatenbankImMeldeweg:
    def test_die_meldung_schreibt_keine_zeile(self, env):
        """`bruegge_positionen_holen` wird nirgends aufgerufen -- die Live-Karte speist sich
        aus dem Prozessspeicher. Eine Zeile je gemeldetem Flugzeug und Sekunde wäre Aufwand
        ohne Leser."""
        _modus_setzen(env, "alle")
        for _ in range(3):
            _melden(env, [_flugzeug(), _flugzeug(cs=MELDER_CS, lat=LAT, lon=LON)])
        conn = get_connection(env.db)
        try:
            anzahl = conn.execute("SELECT COUNT(*) FROM bruegge_positions").fetchone()[0]
        finally:
            conn.close()
        assert anzahl == 0

    def test_die_kandidaten_kommen_aus_dem_pollerspeicher(self, env):
        """Der Regelweg fragt nicht die Datenbank: Der Poller hat die Friesen ohnehin
        gerade in der Hand gehabt (`live_positions` je Poll-Zyklus)."""
        conn = get_connection(env.db)
        try:
            conn.execute("DELETE FROM live_positions")
            conn.commit()
        finally:
            conn.close()
        _modus_setzen(env, "alle")
        assert _melden(env, [_flugzeug()]).json()["uebernommen"] == 1

    def test_ohne_poller_geht_die_meldung_verloren_statt_zu_scheitern(self, env):
        """Genau die Rangfolge, die schon für die Brügge gilt: lieber nicht live als kaputt."""
        _modus_setzen(env, "alle")
        del main.app.state._state["poller"]
        try:
            r = _melden(env, [_flugzeug()])
            assert r.status_code == 200
            assert r.json()["uebernommen"] == 0
        finally:
            main.app.state.poller = env.poller


# ---------------------------------------------------------------------------------------
#  3. Wessen Meldung gilt?
# ---------------------------------------------------------------------------------------

class TestVorrang:
    def test_eine_bruegge_wird_nicht_von_einem_fremden_kniebrett_ueberschrieben(self, env):
        """Die Brügge sitzt IM Simulator des Piloten. Ein fremdes Kniebrett sieht ihn über
        vPilot -- eine Quelle weiter weg. Bei gleichzeitigem Betrieb gewinnt die nähere."""
        _modus_setzen(env, "alle")
        env.poller.bruegge_position_merken(FREMD, {"lat": LAT, "lon": LON, "kurs": 90.0,
                                                   "gs_kt": 0.0, "alt_msl_ft": 500.0})
        _melden(env, [_flugzeug(hdg=270.0)])
        assert env.poller._bruegge_live[FREMD]["hdg"] == 90.0

    def test_die_selbstmeldung_des_piloten_gilt_vor_der_fremdmeldung(self, env):
        """Sein eigenes Kniebrett liest die Position direkt aus seinem Simulator."""
        _modus_setzen(env, "alle")
        _melden(env, [_flugzeug(cs=FREMD_CS, hdg=270.0)])          # fremdes Kniebrett
        _melden(env, [_flugzeug(cs=FREMD_CS, hdg=90.0)], cid=FREMD)  # er selbst
        assert env.poller._bruegge_live[FREMD]["hdg"] == 90.0

    def test_zwei_kniebretter_streiten_nicht_um_dieselbe_cid(self, env):
        """Beim FriesenFlieger-Freitag sehen mehrere Kniebretter dieselben Flugzeuge. Wer
        dieselbe CID mehrfach gemeldet bekommt, entscheidet EINMAL -- statt N-mal zu
        schreiben, was ohnehin dasselbe ist."""
        _modus_setzen(env, "alle")
        _melden(env, [_flugzeug(hdg=270.0)])                  # MELDER sieht FREMD
        r = _melden(env, [_flugzeug(hdg=90.0)], cid=DRITT)    # DRITT sieht ihn auch
        # Beide sind Fremdmelder derselben cid und gleich gut. Der zweite kommt nicht zum
        # Zug, solange der erste frisch meldet -- entschieden wird EINMAL, nicht je Meldung.
        assert env.poller._bruegge_live[FREMD]["hdg"] == 270.0
        assert r.json()["uebernommen"] == 0


# ---------------------------------------------------------------------------------------
#  4. Plausibilisieren -- hier meldet ein Client über DRITTE
# ---------------------------------------------------------------------------------------

class TestPlausibel:
    def test_ein_unbekanntes_rufzeichen_wird_verworfen(self, env):
        _modus_setzen(env, "alle")
        r = _melden(env, [_flugzeug(cs="FRS999")])
        assert r.json()["uebernommen"] == 0
        assert env.poller._bruegge_live == {}

    def test_eine_position_fernab_des_vatsim_standes_wird_verworfen(self, env):
        """Die Schranke aus `app/bruegge.py` ist dafür schon da und kostet nichts. Ohne sie
        könnte ein angemeldeter Pilot jeden anderen auf der Karte verschieben."""
        _modus_setzen(env, "alle")
        r = _melden(env, [_flugzeug(lat=LAT + 2.0)])   # gut 200 km daneben
        assert r.json()["uebernommen"] == 0
        assert env.poller._bruegge_live == {}

    def test_kaputte_zahlen_fallen_einzeln_heraus(self, env):
        _modus_setzen(env, "alle")
        r = _melden(env, [{"cs": FREMD_CS, "lat": "nord", "lon": None},
                          _flugzeug(cs=MELDER_CS, lat=LAT, lon=LON)])
        assert r.json()["uebernommen"] == 1
        assert list(env.poller._bruegge_live) == [MELDER]


class TestFormales:
    def test_ohne_anmeldung_wird_nichts_uebernommen(self, env):
        """Zwei Riegel, und beide zaehlen: Bei scharfem Board-Login haelt schon das
        Login-Gate die Anfrage an (der Endpunkt steht bewusst NICHT in der Allowlist --
        anders als `/api/bruegge/melden`, das gar keine Anmeldung haben KANN). Ist das
        Board-Login aus, kommt sie durch und findet keine cid -- dann ist die Antwort
        `aus`. In beiden Faellen wird nichts uebernommen."""
        _modus_setzen(env, "alle")
        r = env.client.post("/api/kniebrett/melden",
                            json={"protokoll": 1, "flugzeuge": [_flugzeug()]})
        # Board-Login ist in dieser Fixture scharf, also greift der erste Riegel -- und
        # genau das wird hier gebunden. Ein `in (200, 401)` hätte beides durchgelassen und
        # damit nichts geprüft.
        assert r.status_code == 401
        assert env.poller._bruegge_live == {}

    def test_ohne_board_login_antwortet_der_endpunkt_selbst_mit_aus(self, env, monkeypatch):
        """Der zweite Riegel: Ist das Board-Login aus, kommt die Anfrage durch das Gate und
        findet keine cid. Dann ist die Antwort `aus` -- kein Fehler, damit der Sender im
        Kniebrett ruhig wird statt in eine Fehlerschleife zu laufen."""
        _modus_setzen(env, "alle")
        monkeypatch.setattr(main, "_forum_login_active_cached", lambda s: False)
        r = env.client.post("/api/kniebrett/melden",
                            json={"protokoll": 1, "flugzeuge": [_flugzeug()]})
        assert r.status_code == 200
        assert r.json()["modus"] == "aus"
        assert env.poller._bruegge_live == {}

    def test_eine_uebergrosse_meldung_wird_abgewiesen(self, env):
        _modus_setzen(env, "alle")
        r = env.client.post("/api/kniebrett/melden",
                            content=json.dumps({"flugzeuge": [_flugzeug()] * 20000}),
                            headers={"Content-Type": "application/json"},
                            cookies=_cookie())
        assert r.status_code == 413

    def test_mehr_flugzeuge_als_die_obergrenze_werden_gekappt(self, env):
        """92 km Reichweite sind gemessen, zwanzig Flugzeuge darin sind viel. Die Grenze
        schützt den Sekundentakt, ohne dass der Client etwas davon wissen muss."""
        _modus_setzen(env, "alle")
        r = _melden(env, [_flugzeug()] * (main._KNIEBRETT_MAX_FLUGZEUGE + 10))
        assert r.json()["verworfen"] >= 10

    def test_kaputtes_json_wird_abgewiesen(self, env):
        r = env.client.post("/api/kniebrett/melden", content="{kein json",
                            headers={"Content-Type": "application/json"}, cookies=_cookie())
        assert r.status_code == 400


# ---------------------------------------------------------------------------------------
#  5. Admin
# ---------------------------------------------------------------------------------------

class TestAdmin:
    def _admin(self, env):
        from app.auth import ADMIN_COOKIE, make_admin_token
        env.client.cookies.set(ADMIN_COOKIE, make_admin_token(SECRET, "pw"))
        return env.client

    def test_uebersicht_nennt_beide_ebenen(self, env):
        c = self._admin(env)
        r = c.get("/api/admin/kniebrett")
        assert r.status_code == 200
        d = r.json()
        assert d["modus"] == "aus"
        assert d["takt_s"] >= 1
        assert d["piloten"] == []

    def test_global_umstellen(self, env):
        c = self._admin(env)
        assert c.post("/api/admin/kniebrett/modus", json={"modus": "alle"}).status_code == 200
        assert c.get("/api/admin/kniebrett").json()["modus"] == "alle"

    def test_ein_erfundener_modus_wird_abgewiesen(self, env):
        c = self._admin(env)
        r = c.post("/api/admin/kniebrett/modus", json={"modus": "vielleicht"})
        assert r.status_code == 400

    def test_je_pilot_setzen_und_wieder_loeschen(self, env):
        c = self._admin(env)
        c.post("/api/admin/kniebrett/pilot", json={"cid": MELDER, "modus": "aus"})
        assert c.get("/api/admin/kniebrett").json()["piloten"] == [
            {"cid": MELDER, "modus": "aus"}]
        c.post("/api/admin/kniebrett/pilot", json={"cid": MELDER, "modus": ""})
        assert c.get("/api/admin/kniebrett").json()["piloten"] == []

    def test_ohne_anmeldung_kein_zugriff(self, env):
        assert env.client.get("/api/admin/kniebrett").status_code in (401, 403)


# ---------------------------------------------------------------------------------------
#  6. Der Sender im Kniebrett -- am Quelltext, weil er sonst niemand prüft
# ---------------------------------------------------------------------------------------
#
# Diese Wachen hängen an DEKLARATIONEN, nicht an Kommentartext: Eine freie Zeichenkettensuche
# findet sonst die Erklärung statt der Sache und bleibt grün, während der Code weg ist.

from pathlib import Path

_INDEX = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(
    encoding="utf-8")
_ADMIN = (Path(__file__).resolve().parents[1] / "app" / "static" / "admin.html").read_text(
    encoding="utf-8")


class TestSenderImQuelltext:
    def test_der_sender_kennt_den_endpunkt(self):
        assert "const _KB_PFAD = '/api/kniebrett/melden';" in _INDEX

    def test_er_laeuft_nur_im_kniebrett(self):
        """Auf der Website gibt es keinen Sim-Verkehr -- jede Meldung wäre die Abschrift
        dessen, was der Server gerade selbst geschickt hat."""
        stelle = _INDEX.index("function _kbStarten()")
        assert "_PANEL_MODUS" in _INDEX[stelle:stelle + 400]
        stelle2 = _INDEX.index("function _kbVorratMerken(")
        assert "_PANEL_MODUS" in _INDEX[stelle2:stelle2 + 200]

    def test_der_takt_kommt_vom_server_also_kein_setinterval(self):
        """`setInterval` nähme eine geänderte Drossel erst nach einem Neuladen an -- und
        könnte sich überholen, wenn eine Anfrage länger braucht als der Takt."""
        stelle = _INDEX.index("function _kbStarten()")
        block = _INDEX[stelle:_INDEX.index("\n}", stelle)]
        assert "setTimeout(_kbMelden" in block
        # Auf den AUFRUF prüfen, nicht auf das Wort: Der Kommentar daneben erklärt, warum
        # es kein `setInterval` ist -- eine freie Suche fände ihn und wäre grün, egal was
        # der Code tut.
        assert "setInterval(" not in block
        assert "naechste_frage_in_s" in _INDEX

    def test_die_wiederholung_liegt_unter_der_serverfrist(self):
        """⭐ Die eigentliche Kopplung dieser Änderung, und sie geht über zwei Sprachen:
        Der Sender lässt Unverändertes weg -- der Server lässt einen Punkt nach
        `MELDUNG_FRIST_S` verfallen. Liegt die Wiederholung darüber, verschwindet ein
        stehendes Flugzeug von der Karte, obwohl es genau dort noch steht."""
        import re
        from app import bruegge
        m = re.search(r"const _KB_WIEDERHOLEN_MS = (\d+);", _INDEX)
        assert m, "_KB_WIEDERHOLEN_MS fehlt"
        assert int(m.group(1)) / 1000.0 < bruegge.MELDUNG_FRIST_S

    def test_der_vorrat_wird_im_matching_gefuellt(self):
        """Nur dort steht die Zuordnung fest -- und nur für einen Friesen, für den der
        Server überhaupt eine cid hat."""
        stelle = _INDEX.index("function _verkehrZusammenfuehren()")
        ende = _INDEX.index("function _zuordnungDiagnose(")
        assert "_kbVorratMerken(v.cs, s);" in _INDEX[stelle:ende]

    def test_der_sender_startet_erst_mit_bekannter_cid(self):
        assert "if (_PANEL_MODUS && _meineCid != null) _kbStarten();" in _INDEX


class TestAdminOberflaeche:
    def test_alle_drei_zustaende_sind_bedienbar(self):
        from app.database import KNIEBRETT_MODI
        for modus in KNIEBRETT_MODI:
            assert f'data-modus="{modus}"' in _ADMIN, f"Knopf für {modus} fehlt"

    def test_je_pilot_laesst_sich_dasselbe_stellen(self):
        stelle = _ADMIN.index('id="kb-pilot-modus"')
        block = _ADMIN[stelle:_ADMIN.index("</select>", stelle)]
        from app.database import KNIEBRETT_MODI
        for modus in KNIEBRETT_MODI:
            assert f'value="{modus}"' in block

    def test_die_tabellen_sind_horizontal_scrollbar(self):
        """UI-Standard: breite Tabellen werden auf dem Smartphone gescrollt, nicht gequetscht."""
        for tabelle in ('id="kb-piloten"', 'id="kb-live"'):
            stelle = _ADMIN.index(tabelle)
            assert 'class="table-wrap"' in _ADMIN[max(0, stelle - 400):stelle]


# ---------------------------------------------------------------------------------------
#  7. Die Karte darf niemandem eine Installation andichten
# ---------------------------------------------------------------------------------------
#
# Das Kartenfenster schrieb an JEDEN sekundengenauen Punkt „Quelle: FriesenBrügge". Sobald
# ein Kniebrett fremde Piloten mitmeldet, ist das eine Falschaussage über jemanden, der gar
# nichts installiert hat -- und sie sähe für den Leser genauso aus wie die Wahrheit.

class TestQuellenangabe:
    def test_die_drei_faelle_werden_unterschieden(self):
        from app.poller import VatsimPoller
        k = VatsimPoller._quelle_kuerzel
        assert k({"cid": 1, "melder": None}) == "b"          # Brügge
        assert k({"cid": 1, "melder": 1}) == "e"             # sein eigenes Kniebrett
        assert k({"cid": 1, "melder": 2}) == "k"             # ein fremdes Kniebrett

    def test_der_strom_verraet_nicht_wer_wen_sieht(self, env):
        """`q` sagt, WIE der Punkt entsteht -- nicht, WER ihn gemeldet hat. Die CID des
        Melders hat auf einer offenen Karte nichts zu suchen."""
        gesendet = []
        env.poller.broadcast_sse = lambda m: gesendet.append(m)
        from app.poller import VatsimPoller
        env.poller.bruegge_strom_senden = VatsimPoller.bruegge_strom_senden.__get__(env.poller)
        env.poller._quelle_kuerzel = VatsimPoller._quelle_kuerzel
        _modus_setzen(env, "alle")
        _melden(env, [_flugzeug()])
        env.poller.bruegge_strom_senden()
        assert gesendet, "der Strom hat gar nichts gesendet"
        eintrag = gesendet[0]["data"][0]
        assert eintrag["q"] == "k"
        assert "melder" not in eintrag
        assert "guete" not in eintrag

    def test_das_kartenfenster_benennt_alle_drei(self):
        stelle = _INDEX.index("function _quelleName(")
        block = _INDEX[stelle:_INDEX.index("\n}", stelle)]
        assert "'k'" in block and "'e'" in block
        assert "FriesenBrügge" in block
        # Und es wird auch benutzt -- eine Funktion, die niemand ruft, korrigiert nichts.
        assert "_quelleName(p.callsign)" in _INDEX


# ---------------------------------------------------------------------------------------
#  8. Was ein Melder über Dritte NICHT darf (Fable-Review, 15.09.2026)
# ---------------------------------------------------------------------------------------
#
# Die Prüfung stammt von der FriesenBrügge, und dort ist sie richtig: `schranke_m` rechnet mit
# der Geschwindigkeit AUS DER MELDUNG, weil die Brügge sich selbst meldet und nichts davon
# hätte, ihr eigenes Toleranzfenster aufzublasen. Hier meldet ein Client über DRITTE — und
# lieferte die Größe des Fensters damit selbst mit.

class TestMelderBlaehtDieSchrankeNichtAuf:
    def test_eine_erfundene_geschwindigkeit_vergroessert_das_fenster_nicht(self, env):
        """Gemessen vor dem Fix: `gs: 1000` ließ eine Position 33 km neben dem VATSIM-Stand
        durch — und weil der erste Fremdmelder den Zuschlag behält, blieb der Punkt dort."""
        _modus_setzen(env, "alle")
        r = _melden(env, [_flugzeug(lat=LAT + 0.3, gs=1000.0)])
        assert r.json()["uebernommen"] == 0
        assert env.poller._bruegge_live == {}

    def test_eine_erfundene_steigrate_vergroessert_das_hoehenfenster_nicht(self, env):
        _modus_setzen(env, "alle")
        r = _melden(env, [_flugzeug(alt=40000.0, vs=99999.0)])
        assert r.json()["uebernommen"] == 0

    def test_ein_kurs_ausserhalb_des_kreises_geht_nicht_in_den_strom(self, env):
        """Was hier durchrutscht, steht eine Sekunde später auf jeder offenen Karte."""
        _modus_setzen(env, "alle")
        _melden(env, [_flugzeug(hdg=99999.0, gs=-5.0)])
        e = env.poller._bruegge_live[FREMD]
        assert 0.0 <= e["hdg"] < 360.0
        assert e["gs"] >= 0.0

    def test_eine_ehrliche_beschleunigung_geht_weiterhin_durch(self, env):
        """Die Gegenprobe zur Härtung: Wer wirklich schneller ist als sein VATSIM-Stand,
        darf weiter weg sein. Sonst wäre die Schranke nur noch streng, nicht mehr richtig."""
        _modus_setzen(env, "alle")
        r = _melden(env, [_flugzeug(lat=LAT + 0.004, gs=60.0)])
        assert r.json()["uebernommen"] == 1


class TestHoeheFehltIstNichtNull:
    def test_ohne_hoehenangabe_wird_die_hoehe_nicht_geprueft(self, env):
        """Ein Panel-Paket vor 1.4.0 schickt keine Höhe. Sie als 0 ft zu lesen hieße, jede
        Meldung aus der Luft still zu verwerfen — und das sähe aus wie „meldet eben nicht"."""
        _modus_setzen(env, "alle")
        e = _flugzeug()
        e["alt"] = None
        r = _melden(env, [e])
        assert r.json()["uebernommen"] == 1
        assert env.poller._bruegge_live[FREMD]["alt"] is None


class TestUebergabeZwischenMeldern:
    def test_ein_verstummter_melder_blockiert_nicht_bis_zum_verfall(self, env, monkeypatch):
        """Sonst steht ein fliegendes Flugzeug zehn Sekunden lang auf allen Karten still:
        Der Strom schickt brav den letzten Stand weiter, während der zweite Melder mit
        frischen Zahlen abgewiesen wird."""
        import app.poller as poller_modul
        _modus_setzen(env, "alle")
        _melden(env, [_flugzeug(hdg=270.0)])
        t0 = env.poller._bruegge_live[FREMD]["ts"]
        # Vier Sekunden später: über dem Zuschlagsfenster, unter der Verfallsfrist.
        monkeypatch.setattr(poller_modul.time, "monotonic", lambda: t0 + 4.0)
        _melden(env, [_flugzeug(hdg=90.0)], cid=DRITT)
        assert env.poller._bruegge_live[FREMD]["hdg"] == 90.0

    def test_solange_der_erste_meldet_wird_nicht_gewechselt(self, env):
        """Die andere Hälfte derselben Regel — sonst wäre es das Flackern zurück."""
        _modus_setzen(env, "alle")
        _melden(env, [_flugzeug(hdg=270.0)])
        _melden(env, [_flugzeug(hdg=90.0)], cid=DRITT)
        assert env.poller._bruegge_live[FREMD]["hdg"] == 270.0

    def test_das_zuschlagsfenster_liegt_unter_der_verfallsfrist(self):
        from app.poller import VatsimPoller
        assert VatsimPoller.KNIEBRETT_ZUSCHLAG_S < VatsimPoller.BRUEGGE_FRIST_S


class TestTaktUndFrist:
    def test_der_takt_darf_die_verfallsfrist_nicht_ueberschreiten(self):
        """Bei einem Takt von 15 s lebte jeder Punkt 10 s und fiele 5 s auf VATSIM zurück —
        ein sichtbarer Sprung, alle 15 Sekunden. Eine Drossel macht die Anzeige gröber, sie
        lässt sie nicht blinken."""
        from app import bruegge
        assert main._KNIEBRETT_TAKT_MAX_S <= bruegge.MELDUNG_FRIST_S

    def test_der_admin_kann_nicht_darueber_hinaus_stellen(self, env):
        from app.auth import ADMIN_COOKIE, make_admin_token
        env.client.cookies.set(ADMIN_COOKIE, make_admin_token(SECRET, "pw"))
        assert env.client.post("/api/admin/kniebrett/takt",
                               json={"takt_s": 900}).status_code == 400
        assert env.client.post("/api/admin/kniebrett/takt",
                               json={"takt_s": main._KNIEBRETT_TAKT_MAX_S}).status_code == 200

    def test_aus_bleibt_trotzdem_ein_langer_takt(self, env):
        """Der Ausschalter-Takt ist kein Meldetakt: Da wird ja gerade nichts gemeldet."""
        r = _melden(env, [])
        assert r.json()["modus"] == "aus"
        assert r.json()["naechste_frage_in_s"] == main._KNIEBRETT_TAKT_AUS_S


class TestSenderNachFehlschlag:
    def test_gemerkt_wird_erst_nach_der_antwort(self):
        """Sonst gilt nach einem 429 ein Punkt als gesendet, der nie ankam — und ein
        stehendes Flugzeug, das nur von der Wiederholung lebt, verschwindet von der Karte."""
        nutz = _INDEX.index("function _kbNutzlast()")
        assert "_kbGesendet[e.cs] =" not in _INDEX[nutz:_INDEX.index("\n}", nutz)]
        melden = _INDEX.index("async function _kbMelden()")
        block = _INDEX[melden:_INDEX.index("\n}", melden)]
        assert block.index("await r.json()") < block.index("_kbGesendetVermerken(nutzlast)")

    def test_die_eigene_steigrate_wird_gerechnet_nicht_genullt(self):
        """Ohne sie verliert ausgerechnet die beste Quelle — der Pilot selbst — ihren Punkt
        im Steigflug an ein fremdes Kniebrett, das die Rate mitschickt."""
        stelle = _INDEX.index("function _kbEigenes()")
        block = _INDEX[stelle:_INDEX.index("\n}", stelle)]
        assert "vs: vs" in block and "_kbEigenVs()" in block

    def test_der_vorrat_wird_in_jedem_modus_aufgeraeumt(self):
        stelle = _INDEX.index("function _kbNutzlast()")
        block = _INDEX[stelle:_INDEX.index("\n}", stelle)]
        # Das Aufräumen steht VOR der Modus-Abfrage, sonst wächst der Vorrat in `aus`
        # und `eigene` mit jedem je gesehenen Flugzeug weiter.
        assert block.index("delete _kbVorrat[cs]") < block.index("if (_kbModus === 'aus')")
        assert "delete _kbGesendet[cs]" in block


# ---------------------------------------------------------------------------------------
#  9. Brügge UND Kniebrett gleichzeitig -- wer gewinnt? (Nutzerfrage, 15.09.2026)
# ---------------------------------------------------------------------------------------
#
# ⚠ Der Fall war vorher NICHT entschieden, sondern zufällig: Beide melden im Sekundentakt,
# `bruegge_position_merken` prüft gar nichts, und `kniebrett_position_merken` ließ bei
# gleicher Güte durch. Es gewann also, wer zuletzt kam -- im Wechsel, jede Sekunde.
#
# Sichtbar wäre das an der Quellenangabe im Kartenfenster geworden (mal „FriesenBrügge", mal
# „Kniebrett"), und `agl`/`gnd` wären zwischen echtem Wert und leer gesprungen: Die Brügge
# liest per SimConnect und liefert beides, die Positionsbrücke des Kniebretts nicht.
#
# Deshalb: **Für die eigene Position gewinnt die Brügge.** Sie ist die reichere Quelle.

class TestBrueggeUndKniebrettZugleich:
    def _bruegge_meldet(self, env, cid=MELDER):
        env.poller.bruegge_position_merken(cid, {
            "lat": LAT, "lon": LON, "kurs": 90.0, "gs_kt": 0.0,
            "alt_msl_ft": 500.0, "alt_agl_ft": 12.0, "am_boden": True})

    def test_die_eigene_bruegge_gewinnt_gegen_das_eigene_kniebrett(self, env):
        _modus_setzen(env, "eigene")
        self._bruegge_meldet(env)
        r = _melden(env, [_flugzeug(cs=MELDER_CS, lat=LAT, lon=LON, hdg=270.0)])
        assert r.json()["uebernommen"] == 0
        assert env.poller._bruegge_live[MELDER]["hdg"] == 90.0

    def test_und_ihre_zusatzwerte_bleiben_erhalten(self, env):
        """Das ist der eigentliche Grund für die Regel: Das Kniebrett kennt für die eigene
        Position weder AGL noch „am Boden" -- die Positionsbrücke liefert sie nicht. Ein
        Wechsel im Sekundentakt ließe beide Felder flackern."""
        _modus_setzen(env, "eigene")
        self._bruegge_meldet(env)
        _melden(env, [_flugzeug(cs=MELDER_CS, lat=LAT, lon=LON)])
        e = env.poller._bruegge_live[MELDER]
        assert e["agl"] == 12 and e["gnd"] is True

    def test_verstummt_die_bruegge_uebernimmt_das_kniebrett(self, env, monkeypatch):
        """Sonst wäre die Regel ein Ausschalter: Wer den Simulator verlässt und das Tablet
        offen behält, verschwände, obwohl eine Quelle weiter meldet."""
        import app.poller as poller_modul
        _modus_setzen(env, "eigene")
        self._bruegge_meldet(env)
        t0 = env.poller._bruegge_live[MELDER]["ts"]
        monkeypatch.setattr(poller_modul.time, "monotonic", lambda: t0 + 4.0)
        r = _melden(env, [_flugzeug(cs=MELDER_CS, lat=LAT, lon=LON, hdg=270.0)])
        assert r.json()["uebernommen"] == 1
        assert env.poller._bruegge_live[MELDER]["hdg"] == 270.0

    def test_ein_fremdes_kniebrett_kommt_gegen_die_bruegge_ohnehin_nicht_an(self, env):
        """Die schon vorher geltende Regel, hier nur noch einmal neben der neuen."""
        _modus_setzen(env, "alle")
        self._bruegge_meldet(env, cid=FREMD)
        _melden(env, [_flugzeug(hdg=270.0)])
        assert env.poller._bruegge_live[FREMD]["hdg"] == 90.0


# ---------------------------------------------------------------------------------------
#  10. Zur Auswahl steht, wer ein Kniebrett HAT (Nutzerfrage, 15.09.2026)
# ---------------------------------------------------------------------------------------
#
# Die erste Fassung bot alle Piloten an -- am 15.09.2026 waren das **64**, von denen **vier**
# ein Kniebrett gebunden hatten. Das zwingt den Admin, unter sechzig Namen die vier zu finden,
# die der Schalter überhaupt etwas angeht, und legt nahe, die anderen sechzig meldeten etwas.

class TestAuswahlNurKniebretter:
    def _geraet(self, env, cid, device="dev-abc123", zuletzt="2026-09-15T08:00:00Z"):
        conn = get_connection(env.db)
        try:
            conn.execute(
                "INSERT INTO panel_devices (device_id, cid, name, created_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (device, cid, "Tablet", "2026-09-01T00:00:00Z", zuletzt))
            conn.commit()
        finally:
            conn.close()

    def _admin(self, env):
        from app.auth import ADMIN_COOKIE, make_admin_token
        env.client.cookies.set(ADMIN_COOKIE, make_admin_token(SECRET, "pw"))
        return env.client

    def test_ohne_gebundenes_geraet_steht_niemand_zur_auswahl(self, env):
        """Und zwar auch dann nicht, wenn es Piloten gibt — die Auswahl ist keine
        Mitgliederliste."""
        assert self._admin(env).get("/api/admin/kniebrett").json()["auswahl"] == []

    def test_wer_ein_kniebrett_hat_steht_drin(self, env):
        self._geraet(env, MELDER)
        a = self._admin(env).get("/api/admin/kniebrett").json()["auswahl"]
        assert [k["cid"] for k in a] == [MELDER]
        assert a[0]["geraete"] == 1 and a[0]["zuletzt"] == "2026-09-15T08:00:00Z"

    def test_wer_bereits_einen_eintrag_hat_bleibt_waehlbar(self, env):
        """Seine Gerätebindung kann längst gelöst sein — der Eintrag gilt trotzdem weiter und
        muss ohne Umweg zurücknehmbar bleiben."""
        _modus_setzen(env, "aus", cid=FREMD)
        a = self._admin(env).get("/api/admin/kniebrett").json()["auswahl"]
        assert FREMD in [k["cid"] for k in a]

    def test_wer_gerade_meldet_steht_auch_drin(self, env):
        """Ein Pilot kann das Kniebrett benutzen, ohne das Gerät dauerhaft zu binden — dann
        steht er in `panel_devices` nicht. Genau bei ihm braucht man den Schalter."""
        _modus_setzen(env, "alle")
        _melden(env, [_flugzeug()])
        a = self._admin(env).get("/api/admin/kniebrett").json()["auswahl"]
        assert MELDER in [k["cid"] for k in a]

    def test_die_oberflaeche_fuellt_die_auswahl_nicht_aus_der_pilotenliste(self):
        """Die Bindung an den Code, nicht an den Kommentar: Im Block, der das Auswahlfeld
        füllt, darf `/api/admin/pilots` nicht vorkommen."""
        stelle = _ADMIN.index("const sel = document.getElementById('kb-pilot');")
        block = _ADMIN[stelle:stelle + 900]
        assert "_kbStand.auswahl" in block
        assert "/api/admin/pilots" not in block


# ---------------------------------------------------------------------------------------
#  11. Der Ausschalter muss sich wie ein Schalter anfühlen
# ---------------------------------------------------------------------------------------

class TestAusTaktIstKurzGenug:
    def test_aus_wirkt_binnen_einer_minute_zurueck(self, env):
        """⚠ 900 s waren die Zahl der FriesenBrügge, und sie ist hier übernommen worden,
        ohne die Gegenrichtung zu bedenken: Abschalten wirkt sofort, aber das
        WIEDEREINSCHALTEN erfährt der Client erst bei seiner nächsten Frage. Bei 900 s sind
        das bis zu 15 Minuten, in denen ein zurückgestellter Schalter nichts tut -- am
        15.09.2026 im Betrieb erlebt und zuerst für einen Fehler gehalten.

        Die Last spricht nicht dagegen: 60 Anfragen je Stunde und Client sind nichts."""
        assert main._KNIEBRETT_TAKT_AUS_S <= 60
        r = _melden(env, [])
        assert r.json()["modus"] == "aus"
        assert r.json()["naechste_frage_in_s"] == main._KNIEBRETT_TAKT_AUS_S

    def test_aber_lang_genug_um_nicht_im_takt_zu_bleiben(self):
        """Eine 0 oder ein Sekundentakt wäre kein Aus-Zustand, sondern derselbe Verkehr
        ohne Nutzen."""
        assert main._KNIEBRETT_TAKT_AUS_S >= 30


# ---------------------------------------------------------------------------------------
#  12. Wer darf schweigen? -- die Brügge, wenn das Kniebrett denselben Piloten meldet
# ---------------------------------------------------------------------------------------
#
# ⭐ Der eigentliche Lasthebel, und er ist ein anderer als die Vorrangregel: Dort geht es
# darum, WESSEN Punkt gilt -- hier darum, dass die teure Seite gar nicht erst fragt.
#
# Gemessen: `/api/bruegge/melden` macht fünf DB-Aufrufe je Meldung plus Positionsmatching,
# `/api/kniebrett/melden` keinen. Melden beide denselben Piloten, ist die Brügge-Anfrage
# reine Arbeit ohne Ergebnis -- ihr Punkt wird ohnehin vom Kniebrett überschrieben oder
# überschreibt es.
#
# Ihre Objekte gelten 300 s (`_BRUEGGE_GILT_BIS_S`), ein Takt von 5 s ist dafür unkritisch.

class TestBrueggeDarfSchweigen:
    def test_ohne_kniebrett_bleibt_der_regeltakt(self, env):
        assert env.poller.kniebrett_meldet_fuer(MELDER) is False

    def test_meldet_ein_kniebrett_denselben_piloten_darf_die_bruegge_langsamer_fragen(self, env):
        _modus_setzen(env, "eigene")
        _melden(env, [_flugzeug(cs=MELDER_CS, lat=LAT, lon=LON)])
        assert env.poller.kniebrett_meldet_fuer(MELDER) is True

    def test_eine_fremdmeldung_zaehlt_dafuer_NICHT(self, env):
        """Das ist die wichtige Grenze: Ein fremdes Kniebrett sieht den Piloten nur, solange
        er in dessen Umkreis fliegt. Seine Brügge deswegen zu drosseln hieße, die Auflösung
        von jemandem abhängig zu machen, der jederzeit wegfliegen kann."""
        _modus_setzen(env, "alle")
        _melden(env, [_flugzeug()])          # MELDER meldet FREMD mit
        assert env.poller.kniebrett_meldet_fuer(FREMD) is False

    def test_eine_alte_meldung_zaehlt_nicht(self, env, monkeypatch):
        import app.poller as poller_modul
        _modus_setzen(env, "eigene")
        _melden(env, [_flugzeug(cs=MELDER_CS, lat=LAT, lon=LON)])
        t0 = env.poller._bruegge_live[MELDER]["ts"]
        monkeypatch.setattr(poller_modul.time, "monotonic", lambda: t0 + 30.0)
        assert env.poller.kniebrett_meldet_fuer(MELDER) is False

    def test_der_gedrosselte_takt_liegt_unter_der_objektfrist(self):
        """Sonst verlöre die Brügge ihren Sollzustand, während sie schweigt -- und räumte
        alle Objekte ab (`g_gilt_bis_s` in bruegge.cpp)."""
        assert main._BRUEGGE_TAKT_MIT_KNIEBRETT_S < main._BRUEGGE_GILT_BIS_S

    def test_und_er_holt_die_bruegge_schnell_zurueck(self):
        """Verstummt das Kniebrett, verfällt sein Eintrag nach MELDUNG_FRIST_S. Die Brügge
        muss davor oder kurz danach wieder fragen, sonst klafft eine Lücke auf der Karte."""
        from app import bruegge
        assert main._BRUEGGE_TAKT_MIT_KNIEBRETT_S <= bruegge.MELDUNG_FRIST_S

    def test_der_hebel_greift_im_bruegge_endpunkt_selbst(self, env, monkeypatch):
        """Die Hilfsfunktion allein beweist nichts -- geprüft wird, was die Brügge in ihrer
        Antwort wirklich zu lesen bekommt."""
        conn = get_connection(env.db)
        try:
            # Ohne Forum-Login weist der Brügge-Endpunkt jede Meldung ab.
            conn.execute("INSERT OR REPLACE INTO forum_callsign (callsign, cid, updated_at) "
                         "VALUES (?, ?, ?)", (MELDER_CS, MELDER, "2026-09-15T00:00:00Z"))
            conn.commit()
        finally:
            conn.close()
        lage = {"lat": LAT, "lon": LON, "alt_msl_ft": 500.0, "alt_agl_ft": 0.0,
                "gs_kt": 0.0, "kurs": 210.0, "vs_ft_min": 0.0, "am_boden": True}

        # 1. Ohne Kniebrett: Regeltakt.
        r = env.client.post("/api/bruegge/melden",
                            json={"protokoll": 2, "simulator": "msfs2024",
                                  "kennung": "aaaa1111bbbb2222", "lage": lage})
        assert r.status_code == 200
        ohne = r.json()["naechste_frage_in_s"]
        assert ohne == main._BRUEGGE_TAKT_VORGABE_S

        # 2. Sein Kniebrett meldet -- jetzt darf sie langsamer fragen.
        #    ⚠ Die Zeit muss dafür über KNIEBRETT_ZUSCHLAG_S hinaus: Die Brügge hält den
        #    Eintrag aus Schritt 1 noch, und genau das ist die Vorrangregel. Beide Regeln
        #    greifen hier nacheinander -- das ist kein Testkniff, sondern der Betriebsfall
        #    (die Brügge meldet zuerst, das Kniebrett kommt dazu).
        import app.poller as poller_modul
        t0 = env.poller._bruegge_live[MELDER]["ts"]
        # `monkeypatch` und nicht von Hand setzen: Ein Fehlschlag mitten im Test ließe die
        # gefälschte Uhr sonst stehen, und der nächste Test in derselben Sitzung erbt sie.
        monkeypatch.setattr(poller_modul.time, "monotonic", lambda: t0 + 4.0)
        _modus_setzen(env, "eigene")
        assert _melden(env, [_flugzeug(cs=MELDER_CS, lat=LAT, lon=LON)]).json()["uebernommen"] == 1
        r = env.client.post("/api/bruegge/melden",
                            json={"protokoll": 2, "simulator": "msfs2024",
                                  "kennung": "aaaa1111bbbb2222", "lage": lage})
        assert r.json()["naechste_frage_in_s"] == main._BRUEGGE_TAKT_MIT_KNIEBRETT_S

        # 3. ... und ihre Objekte bekommt sie weiterhin: Der Hebel drosselt, er schaltet
        #    nicht ab. Ein leeres `soll` hier hieße, dass sie alles abräumt.
        assert "soll" in r.json()
