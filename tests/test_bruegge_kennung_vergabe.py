# -*- coding: utf-8 -*-
"""Der Server vergibt die Kennung — die Brügge erfindet keine mehr (14.09.2026).

**Warum das umgestellt wurde:** Die MSFS-Brügge baute ihre Kennung aus einer
Speicheradresse und `rand()` ohne `srand()`. In einem WASM-Modul ist der Speicher linear
und bei jedem Start identisch, und `rand()` liefert ohne Saat überall dieselbe Folge —
**jede** Installation erzeugte `9e3711c100000000`.

Live vorgeführt mit zwei Piloten auf Wangerooge: Der Server schrieb die Position des einen
unter die CID des anderen, mit null Verstößen.

Jeder Versuch, das im Client zu reparieren, läuft auf dieselbe Frage hinaus — woher nimmt
ein WASM-Modul Entropie? Der Server hat diese Frage nicht: Er sieht alle Kennungen.

Der Ablauf, den diese Tests absichern, ist derselbe wie im Kniebrett
(`getOrCreateDeviceId`): einmal beschaffen, dauerhaft speichern, bei jeder Meldung
mitliefern. Nur die Quelle ist eine andere.
"""

import pytest

from tests.test_bruegge_endpunkt import (  # noqa: F401  (klient ist eine Fixture)
    klient, _meldung, _friese_anlegen,
)


def test_ohne_kennung_teilt_der_server_eine_zu(klient, tmp_path):
    """Schritt 1 und 2: Die allererste Meldung kommt ohne, die Antwort bringt eine."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    r = klient.post("/api/bruegge/melden", json=_meldung(kennung=""))
    assert r.status_code == 200
    zugeteilt = r.json().get("kennung")
    assert zugeteilt, "ohne Kennung muss der Server eine vergeben"
    assert len(zugeteilt) == 16 and all(c in "0123456789abcdef" for c in zugeteilt), zugeteilt


def test_die_zugeteilte_kennung_wird_sofort_gehalten(klient, tmp_path):
    """Schritt 3: Mit ihr gemeldet, greift die gemerkte Zuordnung — ohne neuen Vollmatch."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    zugeteilt = klient.post("/api/bruegge/melden",
                            json=_meldung(kennung="")).json()["kennung"]

    from app.database import get_connection
    conn = get_connection(db)
    zeile = conn.execute("SELECT cid FROM bruegge_zuordnung WHERE kennung = ?",
                         (zugeteilt,)).fetchone()
    conn.close()
    assert zeile is not None, "die zugeteilte Kennung muss sofort in bruegge_zuordnung stehen"
    assert zeile[0] == 1234567


def test_wer_eine_kennung_mitbringt_bekommt_keine_neue(klient, tmp_path):
    """Sonst bekäme eine laufende Brügge bei jeder Meldung eine andere — Flackern."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    r = klient.post("/api/bruegge/melden", json=_meldung(kennung="a3f9c1e0b2d48576"))
    assert r.status_code == 200
    assert "kennung" not in r.json()


def test_auch_die_zweite_meldung_bekommt_keine_neue(klient, tmp_path):
    """Die zugeteilte gilt — der Server darf sie nicht bei jeder Meldung erneuern."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    zugeteilt = klient.post("/api/bruegge/melden",
                            json=_meldung(kennung="")).json()["kennung"]
    zweite = klient.post("/api/bruegge/melden", json=_meldung(kennung=zugeteilt)).json()
    assert "kennung" not in zweite


def test_ohne_zuordnung_gibt_es_auch_keine_kennung(klient, tmp_path):
    """Wer nicht auf VATSIM ist, bekommt nichts — sonst wäre die Vergabe ein offenes Tor."""
    r = klient.post("/api/bruegge/melden", json=_meldung(kennung=""))
    assert r.status_code == 200
    assert "kennung" not in r.json()
    assert r.json()["soll"] == []


def test_ohne_forum_login_gibt_es_auch_keine(klient, tmp_path):
    """Ein FRS-Präfix allein genügt nicht — sonst könnte jeder eines wählen."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db, mit_forum_login=False)
    r = klient.post("/api/bruegge/melden", json=_meldung(kennung=""))
    assert r.status_code == 200
    assert "kennung" not in r.json()


def test_zwei_bruegge_bekommen_verschiedene_kennungen(klient, tmp_path):
    """Der Kern der Sache — und genau das konnte der alte Client nicht.

    Zwei Piloten, 130 m auseinander (die echten Koordinaten vom 14.09.2026). Beide melden
    ohne Kennung; beide müssen eine eigene bekommen.
    """
    db = str(tmp_path / "t.db")
    _friese_anlegen(db, cid=1602713, callsign="FRS49", lat=53.787560, lon=7.909490)
    _friese_anlegen(db, cid=1642160, callsign="FRS123", lat=53.786790, lon=7.911000)

    eine = klient.post("/api/bruegge/melden",
                       json=_meldung(kennung="", lat=53.787560, lon=7.909490)).json()
    andere = klient.post("/api/bruegge/melden",
                         json=_meldung(kennung="", lat=53.786790, lon=7.911000)).json()

    assert eine.get("kennung") and andere.get("kennung")
    assert eine["kennung"] != andere["kennung"], "genau das war der Fehler"

    from app.database import get_connection
    conn = get_connection(db)
    zuordnung = dict(conn.execute(
        "SELECT kennung, cid FROM bruegge_zuordnung").fetchall())
    conn.close()
    assert zuordnung[eine["kennung"]] == 1602713
    assert zuordnung[andere["kennung"]] == 1642160
