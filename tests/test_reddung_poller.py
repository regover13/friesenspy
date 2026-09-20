# -*- coding: utf-8 -*-
"""Der Poller-Job der FriesenReddung: Fund, Aufnahme, Einlieferung, Verfall (20.09.2026).

⚠ **Die Zeiten sind relativ zur echten Uhr gerechnet, nicht festgeschrieben.** Der Job
ueberspringt Events, die noch nicht begonnen haben (`now < dtstart`) -- ein Testevent mit
festem Datum in der Zukunft wuerde also stumm nie geprueft, und der Test waere gruen, ohne
etwas zu belegen. Genau das ist beim Schreiben passiert.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    create_reddung_event, get_connection, get_reddung_event, init_db, upsert_pilot,
)
from app.poller import VatsimPoller

LAT, LON = 53.72, 7.25
G_LAT = 1.0 / 111.32
G_LON = 1.0 / (111.32 * math.cos(math.radians(LAT)))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


JETZT = datetime.now(timezone.utc)


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _event(pfad, *, start_vor_h=2.0, ende_in_h=2.0, **extra):
    c = get_connection(pfad)
    try:
        eid = create_reddung_event(
            c, name="Reddung Probe",
            dtstart=_iso(JETZT - timedelta(hours=start_vor_h)),
            dtend=_iso(JETZT + timedelta(hours=ende_in_h)),
            sued=LAT - 2 * G_LAT, west=LON - 2 * G_LON,
            nord=LAT + 2 * G_LAT, ost=LON + 2 * G_LON,
            havarist_lat=LAT, havarist_lon=LON, havarist_grund_ft=10.0, **extra)
        c.commit()
        return eid
    finally:
        c.close()


def _punkte(pfad, cid, punkte, alt=900, gs=110):
    c = get_connection(pfad)
    try:
        upsert_pilot(c, cid, f"Pilot {cid}")
        for lat, lon, ts in punkte:
            c.execute("INSERT INTO position_history (cid, callsign, latitude, longitude, "
                      "altitude, groundspeed, heading, ts) VALUES (?,?,?,?,?,?,?,?)",
                      (cid, f"FRS{cid}", lat, lon, alt, gs, 90, ts))
        c.commit()
    finally:
        c.close()


def _quer(vor_min: float):
    """Ost-West durch die Sektormitte, 1 km je 15 s, ``vor_min`` Minuten vor jetzt."""
    t0 = JETZT - timedelta(minutes=vor_min)
    return [(LAT, LON + k * G_LON, _iso(t0 + timedelta(seconds=15 * (k + 2))))
            for k in (-2, -1, 0, 1)]


def _stand(pfad, vor_min: float, gs: float, alt: float = 30):
    """Zwei Punkte am Havaristen -- Vollstopp oder Schwebeflug."""
    t0 = JETZT - timedelta(minutes=vor_min)
    return [(LAT, LON, _iso(t0)), (LAT, LON, _iso(t0 + timedelta(seconds=15)))]


def _lauf(pfad):
    p = VatsimPoller(db_path=pfad, callsign_prefix="FRS", poll_interval=60)
    asyncio.run(p._check_reddung())


def _ev(pfad, eid):
    c = get_connection(pfad)
    try:
        return get_reddung_event(c, eid)
    finally:
        c.close()


def test_der_ueberflug_latcht_den_fund(db):
    eid = _event(db)
    _punkte(db, 111, _quer(60))
    _lauf(db)
    ev = _ev(db, eid)
    assert ev["gefunden_von"] == 111
    # Gestempelt wird das Ende des ERSTEN Segments, das den Ueberflug beweist -- und das ist
    # hier schon das Stueck von 2 km auf 1 km Abstand, denn 1 km liegt im Fundradius von
    # 1,71 km. Nicht der Punkt genau ueber dem Wrack.
    assert ev["gefunden_am"] == _quer(60)[1][2]


def test_ein_zu_hoher_ueberflug_findet_nicht(db):
    eid = _event(db)
    _punkte(db, 111, _quer(60), alt=2000)
    _lauf(db)
    assert _ev(db, eid)["gefunden_am"] is None


def test_der_ueberflug_des_finders_ist_nicht_gleich_die_aufnahme(db):
    """Sonst waere jeder Fund sofort eine Rettung."""
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _stand(db, 60, gs=10), alt=200, gs=10)
    _lauf(db)
    ev = _ev(db, eid)
    assert ev["gefunden_am"] is None, "10 kt liegt unter der Suchuntergrenze von 30 kt"
    assert ev["aufgenommen_am"] is None


def test_ein_schwebeflug_nach_dem_fund_nimmt_auf(db):
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _quer(90))
    _lauf(db)
    assert _ev(db, eid)["gefunden_von"] == 111
    # ⚠ Der Schwebeflug muss INNERHALB der Schonfrist liegen. Ein Pilot, dessen letzte
    # Meldung eine halbe Stunde alt ist, gilt als verschwunden -- dann latcht Stufe 2 die
    # Aufnahme und Stufe 4 nimmt sie im selben Lauf wieder weg. Das ist richtig so und war
    # beim Schreiben eine Ueberraschung.
    _punkte(db, 222, _stand(db, 2, gs=10), alt=200, gs=10)
    _lauf(db)
    assert _ev(db, eid)["aufgenommen_von"] == 222


def test_ein_schwebeflug_genuegt_NICHT_wenn_eine_landung_verlangt_ist(db):
    eid = _event(db, landung_noetig=1)
    _punkte(db, 111, _quer(90))
    _lauf(db)
    _punkte(db, 222, _stand(db, 30, gs=10), alt=200, gs=10)
    _lauf(db)
    assert _ev(db, eid)["aufgenommen_am"] is None


def test_ein_vollstopp_nimmt_auch_mit_verlangter_landung_auf(db):
    eid = _event(db, landung_noetig=1)
    _punkte(db, 111, _quer(90))
    _lauf(db)
    _punkte(db, 222, _stand(db, 2, gs=0), alt=30, gs=0)
    _lauf(db)
    assert _ev(db, eid)["aufgenommen_von"] == 222


def test_endet_der_abend_mit_dem_fund_wird_nichts_mehr_geprueft(db):
    """⚠ Fund und Vollstopp liegen hier in EINEM Lauf -- und das ist der Punkt.

    Ein zweiter Lauf wuerde nichts beweisen: Nach dem Fund ist die Lage aufgeloest, und ein
    aufgeloestes Event wird oben uebersprungen. Der Haken `aufnehmen_noetig` traegt also nur
    innerhalb eines Takts, zwischen Stufe 2 und Stufe 5. Mit zwei Laeufen blieb die Gegenprobe
    "Haken ignoriert" gruen.
    """
    eid = _event(db, aufnehmen_noetig=0)
    _punkte(db, 111, _quer(5))
    _punkte(db, 222, _stand(db, 2, gs=0), alt=30, gs=0)
    _lauf(db)
    ev = _ev(db, eid)
    assert ev["gefunden_am"] is not None and ev["aufgenommen_am"] is None
    assert ev["aufgeloest_am"] is not None, "der Fund loest die Lage auf"


def test_bei_dtend_wird_aufgeloest_auch_ohne_fund(db):
    eid = _event(db, start_vor_h=3.0, ende_in_h=-1.0)
    _lauf(db)
    ev = _ev(db, eid)
    assert ev["aufgeloest_am"] is not None and ev["gefunden_am"] is None


def test_vor_dem_start_steht_kein_havarist_im_simulator(db):
    """⚠ Das ist der eigentliche Zweck der dtstart-Wache.

    Einen Fund verhindert sie ohnehin nicht -- ein Spurenfenster von einem Startpunkt in der
    Zukunft bis jetzt ist leer. Was sie verhindert, ist der Objektabgleich: Ohne sie stellt
    der Server das Wrack schon hin, bevor das Event begonnen hat, und wer zufaellig
    darueberfliegt, findet es vorher. Ein Test auf "kein Fund" blieb deshalb gruen, als die
    Wache entfernt war.
    """
    eid = _event(db, start_vor_h=-1.0, ende_in_h=3.0)
    _punkte(db, 111, _quer(0))
    _lauf(db)
    assert _ev(db, eid)["gefunden_am"] is None
    c = get_connection(db)
    try:
        assert c.execute("SELECT count(*) FROM bruegge_soll").fetchone()[0] == 0
    finally:
        c.close()


def test_die_aufnahme_verfaellt_wenn_der_aufnehmende_verschwindet(db):
    """Ausloeser ist die Abmeldung, nicht eine Zeitschwelle -- und eine Schonfrist, weil ein
    Absturz zum Desktop mit Wiederanmeldung im Simulator Alltag ist."""
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _quer(120))
    _lauf(db)
    # Der Schwebeflug liegt 100 Minuten zurueck, danach hat 222 nichts mehr gemeldet -- er
    # ist also weg. Der Verfall greift deshalb im SELBEN Lauf, in dem die Aufnahme gelatcht
    # wird; ein zweiter Lauf ist dafuer nicht noetig.
    _punkte(db, 222, _stand(db, 100, gs=10), alt=200, gs=10)
    _lauf(db)
    ev = _ev(db, eid)
    assert ev["aufgenommen_am"] is None and ev["aufgenommen_von"] is None


def test_wer_noch_meldet_behaelt_die_aufnahme(db):
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _quer(120))
    _lauf(db)
    _punkte(db, 222, _stand(db, 100, gs=10), alt=200, gs=10)
    # Er fliegt weiter und meldet gerade eben -- also ist er da, auch wenn der Schwebeflug
    # laenger zurueckliegt.
    _punkte(db, 222, [(LAT + 20 * G_LAT, LON, _iso(JETZT - timedelta(minutes=2)))])
    _lauf(db)
    assert _ev(db, eid)["aufgenommen_von"] == 222


def test_ohne_den_haken_verfaellt_die_aufnahme_nicht(db):
    eid = _event(db, landung_noetig=0, aufnahme_verfaellt=0)
    _punkte(db, 111, _quer(120))
    _lauf(db)
    _punkte(db, 222, _stand(db, 100, gs=10), alt=200, gs=10)
    _lauf(db)
    assert _ev(db, eid)["aufgenommen_von"] == 222


def test_die_objekte_stehen_nach_dem_lauf(db):
    """Der Objektabgleich laeuft ZULETZT -- die Fackel zeigt den Stand nach allen Latches."""
    eid = _event(db)
    _punkte(db, 111, _quer(60))
    _lauf(db)
    c = get_connection(db)
    try:
        arten = sorted(r[0] for r in c.execute("SELECT art FROM bruegge_soll").fetchall())
    finally:
        c.close()
    assert "rauch_signalorange" in arten


def test_der_ueberflug_des_finders_zaehlt_auch_bei_offenem_fenster_nicht_als_aufnahme(db):
    """⚠ Der Test, der den `ab`-Filter erst tragend macht.

    Bei den Vorgaben koennen Fund und Aufnahme geometrisch nie dasselbe Segment sein: Suchen
    verlangt mindestens 30 kt, Schweben hoechstens 30 kt. Setzt ein Admin aber `gs_min_kt`
    auf 0 -- und das darf er --, dann erfuellt ein schwebender Hubschrauber beide Fenster
    gleichzeitig, und ohne den Filter waere jeder Fund sofort seine eigene Rettung.
    """
    eid = _event(db, landung_noetig=0, gs_min_kt=0)
    _punkte(db, 111, _stand(db, 2, gs=10), alt=200, gs=10)
    _lauf(db)
    ev = _ev(db, eid)
    assert ev["gefunden_von"] == 111, "bei gs_min_kt=0 findet auch ein Schwebeflug"
    assert ev["aufgenommen_am"] is None, "derselbe Ueberflug darf nicht auch die Aufnahme sein"


def test_wer_aufgenommen_hat_und_gelandet_ist_behaelt_die_rettung(db):
    """⚠ Der Fehler, den die Reihenfolge zuerst hatte: Stand der Poller einmal still und
    rechnet nach, ist der Pilot laengst gelandet UND abgemeldet. Prueft der Verfall vor der
    Einlieferung, loescht er die Aufnahme, bevor die Landung gesehen wird -- die Rettung waere
    verloren, obwohl sie stattgefunden hat.

    Hier ohne echte Landung geprueft, sondern an der Reihenfolge im Quelltext: Eine Landung zu
    stellen verlangt einen vollstaendigen GPS-Track samt Platzumkreis (s. `_seed_kutter_track`
    in tests/test_poller.py), und der Fall haengt allein an der Abfolge der beiden Stufen.
    """
    import pathlib
    quelle = pathlib.Path("app/poller.py").read_text(encoding="utf-8")
    einliefern = quelle.index("# 3 -- Einliefern")
    verfall = quelle.index("# 4 -- Aufnahme verfallen lassen")
    assert einliefern < verfall, "Einliefern muss VOR dem Verfall geprueft werden"


def test_die_grundhoehe_wird_vor_den_pruefungen_gelernt(db):
    """⚠ Die Gegenprobe "Grundhoehe zuletzt gelernt" blieb gruen, weil kein Test eine
    Bruegge-Messung in den Poller gab.

    Hier liegt das Wrack auf 1.000 ft Gelaende, und der Pilot fliegt in 1.800 ft MSL -- das
    sind 800 ft ueber dem Wrack, also innerhalb der 1.000-ft-Schranke. Ohne die gelernte
    Grundhoehe waere die Schranke 1.000 ft MSL, und der Ueberflug zaehlte nicht. Wer das
    Lernen hinter die Pruefungen schiebt, wertet einen ganzen Takt mit der falschen Schranke.
    """
    eid = _event(db)
    c = get_connection(db)
    try:
        c.execute("UPDATE reddung_events SET havarist_grund_ft = NULL, "
                  "havarist_grund_quelle = NULL WHERE id = ?", (eid,))
        # Eine Bruegge hat das Wrack gesetzt und meldet, worauf es steht.
        c.execute("INSERT INTO bruegge_soll (id, art, lat, lon, angelegt_am, auf_boden) "
                  "VALUES (?, 'flugzeug_echo', ?, ?, ?, 1)",
                  (f"reddung-{eid}-havarist", LAT, LON, _iso(JETZT)))
        c.execute("INSERT INTO bruegge_positions (cid, lat, lon, gemeldet_am, simulator) "
                  "VALUES (111, ?, ?, ?, 'msfs2024')", (LAT, LON, _iso(JETZT)))
        c.execute("INSERT INTO bruegge_steht (kennung, id, cid, zustand, hoehe_ft, "
                  "hoehe_gemessen, gemeldet_am) VALUES ('k1', ?, 111, 'steht', 1000.0, 1, ?)",
                  (f"reddung-{eid}-havarist", _iso(JETZT)))
        c.commit()
    finally:
        c.close()
    _punkte(db, 111, _quer(20), alt=1800)
    _lauf(db)
    ev = _ev(db, eid)
    assert ev["havarist_grund_ft"] == 1000.0
    assert ev["havarist_grund_quelle"] == "gemessen"
    assert ev["gefunden_von"] == 111, "1.800 ft MSL sind 800 ft ueber dem Wrack"
