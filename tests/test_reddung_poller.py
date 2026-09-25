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


def _punkte(pfad, cid, punkte, alt=900, gs=110, bruegge=True):
    """Eine VATSIM-Spur -- und die FriesenBruegge-Anmeldung dazu.

    ⚠ Ohne Bruegge keine Teilnahme (Nutzerentscheidung 20.09.2026): Der Mischer wirft die
    VATSIM-Punkte eines Piloten weg, der an diesem Abend nie gemeldet hat. Die Anmeldung
    liegt deshalb bewusst AUSSERHALB des Sektors (Startplatz) und auf dem Eventstart -- eine
    Meldung im Sektor wuerde ueber `spanne` den ganzen Zeitraum fuer die Bruegge beanspruchen
    und genau die VATSIM-Punkte verdraengen, die der Test pruefen will.

    ``bruegge=False`` ist der Gegenfall: jemand ohne FriesenBruegge, der nicht teilnimmt.
    """
    c = get_connection(pfad)
    try:
        upsert_pilot(c, cid, f"Pilot {cid}")
        if bruegge and punkte:
            # ⚠ Auf dem Zeitstempel des ERSTEN Punktes, nicht davor: `gemeldet_seit` bezieht
            # sich auf den Eventstart, und ein Test darf mit dem ersten Punkt genau darauf
            # liegen -- eine Sekunde frueher fiele aus dem Event heraus und zaehlte nicht.
            # Den VATSIM-Punkt verdraengt sie trotzdem nicht: Sie liegt AUSSERHALB des
            # Sektors und taucht in der Zeitraum-Rechnung (`spanne`) deshalb gar nicht auf.
            c.execute("INSERT OR REPLACE INTO bruegge_spur "
                      "(cid, ts, lat, lon, alt_msl_ft, gs_kt) VALUES (?,?,?,?,?,?)",
                      (cid, punkte[0][2], 48.1, 11.5, 1500, 0))
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
    # Gestempelt wird das Ende des ERSTEN Segments, das den Ueberflug beweist. Mit einem
    # Fundradius von 500 ft (152 m) ist das das Stueck, das ueber das Wrack fuehrt -- nicht
    # mehr das Stueck davor: 1 km Abstand liegt jetzt weit ausserhalb.
    assert ev["gefunden_am"] == _quer(60)[2][2]


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


def test_nach_einem_verfall_latcht_derselbe_schwebeflug_nicht_wieder(db):
    """⚠ Der Fehler, den der Test darueber NICHT gesehen hat: den ZWEITEN Takt.

    Stufe 2 rechnet die Aufnahme aus allen Spuren seit dem Fund. Verfaellt die Aufnahme, weil
    der Pilot verschwunden ist, bleibt sein Schwebeflug in `position_history` -- und war bis
    zum 21.09.2026 im naechsten Takt wieder der zeitlich erste Treffer. Latch, Verfall, Latch,
    Verfall, alle 30 s, mit zwei Push-Nachrichten je Runde an alle Abonnenten.
    """
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _quer(120))          # Fund frueh, damit der Schwebeflug danach liegt
    _lauf(db)
    # 222 schwebte vor 100 Minuten und meldet seitdem nicht mehr -- Latch und Verfall im
    # selben Lauf, das ist gewollt.
    _punkte(db, 222, _stand(db, 100, gs=10), alt=200, gs=10)
    _lauf(db)
    ev = _ev(db, eid)
    assert ev["aufgenommen_von"] is None, "verfallen, denn er ist weg"
    # ⚠ KEIN Zeitriegel beim Verfall -- der sperrte auch den, der gerade uebernehmen will.
    # Dass der Verschwundene nicht erneut latcht, regelt der Melde-Filter in Stufe 2.
    assert ev["aufnahme_ab"] is None
    # Und jetzt der Takt, auf den es ankommt: nichts Neues ist passiert.
    _lauf(db)
    assert _ev(db, eid)["aufgenommen_von"] is None, "derselbe alte Schwebeflug darf nicht erneut latchen"


def test_ein_kaputtes_event_reisst_den_takt_nicht_fuer_alle(db):
    """⚠ Ein einziger `try` um die ganze Schleife liess ein kaputtes Event den Takt fuer ALLE
    beenden -- kein Commit, keine Latches, keine Objekte, jede Minute neu.

    Der Fall ist real: Bis zum 21.09.2026 kam eine Zeichenkette in einem Zahlenfeld ungeprueft
    in die Datenbank. Die Eingabepruefung schliesst das jetzt aus; dieser Test haelt die
    zweite Verteidigungslinie fest.
    """
    kaputt = _event(db)
    heil = _event(db)
    c = get_connection(db)
    try:
        c.execute("UPDATE reddung_events SET korridor_km = 'kaputt' WHERE id = ?", (kaputt,))
        c.commit()
    finally:
        c.close()
    _punkte(db, 111, _quer(90))
    _lauf(db)                              # darf NICHT werfen
    assert _ev(db, heil, )["gefunden_von"] == 111, "das heile Event muss gewertet werden"


def test_der_abschluss_push_behauptet_nicht_unentdeckt_wenn_gefunden_wurde(db):
    """`fertig` heisst nur "eingeliefert" -- der Text hing allein daran und log jeden Abend
    an, an dem gefunden, aber nicht mehr eingeliefert wurde."""
    eid = _event(db, ende_in_h=-0.01, landung_noetig=0)   # Fenster ist gerade vorbei
    _punkte(db, 111, _quer(90))
    p = VatsimPoller(db_path=db, callsign_prefix="FRS", poll_interval=60)
    gesendet = []
    p.broadcast_notify = lambda kanal, ziel, payload: gesendet.append(payload)
    asyncio.run(p._check_reddung())
    ev = _ev(db, eid)
    assert ev["gefunden_von"] == 111 and ev["aufgeloest_am"]
    # ⚠ Erst pruefen, DASS gemeldet wurde -- sonst ist der Test trivial gruen.
    assert gesendet, "zum Abschluss muss eine Meldung rausgehen"
    texte = " ".join(str(g) for g in gesendet)
    assert "unentdeckt" not in texte, f"gefunden, trotzdem 'unentdeckt': {texte}"
    assert "nicht mehr eingeliefert" in texte, f"der richtige Text fehlt: {texte}"


def test_die_admin_freigabe_haelt_laenger_als_einen_takt(db):
    """⚠ Der Knopf hielt bis zum 21.09.2026 genau 30 Sekunden.

    Anders als beim Verfall meldet der Pilot hier weiter -- der Admin greift ja ein, WEIL die
    Automatik falsch lag. Der Melde-Filter aus Stufe 2 hilft deshalb nicht; es braucht den
    Zeitriegel `aufnahme_ab`. Ohne ihn rechnet der naechste Takt wieder ab dem Fund, findet
    denselben Schwebeflug und latcht ihn erneut -- samt Push an alle.
    """
    from app.database import clear_reddung_aufnahme
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _quer(120))
    _lauf(db)
    _punkte(db, 222, _stand(db, 2, gs=10), alt=200, gs=10)
    _lauf(db)
    assert _ev(db, eid)["aufgenommen_von"] == 222
    # Der Admin gibt frei -- mit Zeitpunkt, wie es der Endpunkt tut.
    c = get_connection(db)
    try:
        clear_reddung_aufnahme(c, eid, _iso(JETZT))
        c.commit()
    finally:
        c.close()
    _lauf(db)
    assert _ev(db, eid)["aufgenommen_von"] is None, "der alte Schwebeflug liegt vor der Freigabe"


def test_nach_einem_verfall_kann_ein_anderer_uebernehmen(db):
    """Die Kehrseite: Der Riegel darf nicht das ganze Event blockieren."""
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _quer(120))
    _lauf(db)
    _punkte(db, 222, _stand(db, 100, gs=10), alt=200, gs=10)
    _lauf(db)
    assert _ev(db, eid)["aufgenommen_von"] is None
    # 333 schwebt JETZT am Wrack und meldet auch -- er muss drankommen.
    _punkte(db, 333, _stand(db, 2, gs=10), alt=200, gs=10)
    _lauf(db)
    assert _ev(db, eid)["aufgenommen_von"] == 333


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


def test_die_landung_kommt_aus_der_bruegge_und_nicht_aus_vatsim(db):
    """⚠ Der Grund fuer die Aenderung, gemeldet am 20.09.2026: 'warum dauert es dann so lange,
    bis eine Landung bemerkt wird?'

    canonicalize_legs arbeitet auf VATSIM (alle 15 s, mit Verzoegerung) und verlangt einen
    Vollstopp in Platznaehe. Die Bruegge meldet im Sekundentakt und kennt `am_boden` -- hier
    steht KEINE einzige position_history-Zeile fuer den Aufnehmenden, und die Einlieferung
    wird trotzdem erkannt.
    """
    from app.geo import icao_to_coords
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _quer(120))
    _lauf(db)
    _punkte(db, 222, _stand(db, 2, gs=10), alt=200, gs=10)
    _lauf(db)
    assert _ev(db, eid)["aufgenommen_von"] == 222

    lat, lon = icao_to_coords("EDWF")
    c = get_connection(db)
    try:
        c.execute("INSERT OR REPLACE INTO bruegge_positions (cid, lat, lon, gs_kt, am_boden, "
                  "gemeldet_am, simulator) VALUES (222, ?, ?, 0, 1, ?, 'msfs2024')",
                  (lat, lon, _iso(JETZT)))
        c.commit()
    finally:
        c.close()
    _lauf(db)
    ev = _ev(db, eid)
    assert ev["eingeliefert_von"] == 222
    assert ev["eingeliefert_icao"] == "EDWF"


def test_ein_sim_neustart_am_heimatplatz_ist_keine_einlieferung(db):
    """⚠ Die Bruegge-Einlieferung prueft nur die MOMENTANPOSITION: am Boden, langsam, Platz
    in der Naehe.

    Wer nach der Aufnahme zum Desktop abstuerzt und seinen Simulator am Heimatplatz neu
    startet, erfuellte das bis zum 21.09.2026 sofort -- Event aufgeloest, Wertung vergeben,
    kein Meter geflogen. Der Kommentar an der Schonfrist nennt genau diesen Absturz selbst
    „im Simulator Alltag".
    """
    from app.geo import icao_to_coords
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _quer(120))
    _lauf(db)
    # Aufnahme vor 30 Minuten, danach meldet 222 NICHTS mehr -- er ist abgestuerzt.
    c = get_connection(db)
    try:
        c.execute("UPDATE reddung_events SET aufgenommen_am = ?, aufgenommen_von = 222 "
                  "WHERE id = ?", (_iso(JETZT - timedelta(minutes=30)), eid))
        lat, lon = icao_to_coords("EDWF")
        c.execute("INSERT OR REPLACE INTO bruegge_positions (cid, lat, lon, gs_kt, am_boden, "
                  "gemeldet_am, simulator) VALUES (222, ?, ?, 0, 1, ?, 'msfs2024')",
                  (lat, lon, _iso(JETZT)))
        c.commit()
    finally:
        c.close()
    _lauf(db)
    assert _ev(db, eid)["eingeliefert_von"] is None, "30 Minuten Funkstille sind kein Flug"


def test_wer_durchgehend_gemeldet_hat_liefert_ein(db):
    """Die Kehrseite: Ein echter Flug darf nicht an der Kontinuitaetspruefung scheitern."""
    from app.geo import icao_to_coords
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _quer(120))
    _lauf(db)
    _punkte(db, 222, _stand(db, 30, gs=10), alt=200, gs=10)
    c = get_connection(db)
    try:
        c.execute("UPDATE reddung_events SET aufgenommen_am = ?, aufgenommen_von = 222 "
                  "WHERE id = ?", (_iso(JETZT - timedelta(minutes=30)), eid))
        # Er fliegt zum Platz und meldet dabei alle 15 Sekunden.
        for k in range(120):
            c.execute("INSERT INTO position_history (cid, callsign, latitude, longitude, "
                      "altitude, groundspeed, heading, ts) VALUES (222,'FRS222',?,?,600,110,90,?)",
                      (LAT + k * 0.002, LON, _iso(JETZT - timedelta(seconds=15 * (120 - k)))))
        lat, lon = icao_to_coords("EDWF")
        c.execute("INSERT OR REPLACE INTO bruegge_positions (cid, lat, lon, gs_kt, am_boden, "
                  "gemeldet_am, simulator) VALUES (222, ?, ?, 0, 1, ?, 'msfs2024')",
                  (lat, lon, _iso(JETZT)))
        c.commit()
    finally:
        c.close()
    _lauf(db)
    assert _ev(db, eid)["eingeliefert_icao"] == "EDWF"


def test_eine_aussenlandung_ist_keine_einlieferung(db):
    """Zweite Bedingung: am Boden UND ein registrierter Platz im Umkreis."""
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _quer(120))
    _lauf(db)
    _punkte(db, 222, _stand(db, 2, gs=10), alt=200, gs=10)
    _lauf(db)
    c = get_connection(db)
    try:
        # Mitten in der Nordsee, weit weg von jedem Platz
        c.execute("INSERT OR REPLACE INTO bruegge_positions (cid, lat, lon, gs_kt, am_boden, "
                  "gemeldet_am, simulator) VALUES (222, 55.5, 4.0, 0, 1, ?, 'msfs2024')",
                  (_iso(JETZT),))
        c.commit()
    finally:
        c.close()
    _lauf(db)
    assert _ev(db, eid)["eingeliefert_am"] is None


def test_wer_noch_rollt_ist_noch_nicht_eingeliefert(db):
    eid = _event(db, landung_noetig=0)
    _punkte(db, 111, _quer(120))
    _lauf(db)
    _punkte(db, 222, _stand(db, 2, gs=10), alt=200, gs=10)
    _lauf(db)
    from app.geo import icao_to_coords
    lat, lon = icao_to_coords("EDWF")
    c = get_connection(db)
    try:
        c.execute("INSERT OR REPLACE INTO bruegge_positions (cid, lat, lon, gs_kt, am_boden, "
                  "gemeldet_am, simulator) VALUES (222, ?, ?, 25, 1, ?, 'msfs2024')",
                  (lat, lon, _iso(JETZT)))
        c.commit()
    finally:
        c.close()
    _lauf(db)
    assert _ev(db, eid)["eingeliefert_am"] is None


def test_nach_dem_eventende_werden_die_objekte_weggenommen(db):
    """⚠ Sie blieben stehen, und der Grund war die Reihenfolge: Ein aufgeloestes Event lief
    gar nicht mehr durch die Schleife, also hat niemand mehr aufgeraeumt. Im Admin stand ein
    Wrack zu einem Event, das vorbei war (gemeldet am 20.09.2026).
    """
    from app.database import reddung_objekte_abgleichen, get_reddung_event as _g
    eid = _event(db, start_vor_h=3.0, ende_in_h=2.0, havarist_art="flugzeug_echo")
    c = get_connection(db)
    try:
        reddung_objekte_abgleichen(c, _g(c, eid))
        c.commit()
        assert c.execute("SELECT count(*) FROM bruegge_soll").fetchone()[0] > 0
    finally:
        c.close()
    # Aufgeloest, aber das Zeitfenster laeuft noch -> die Objekte BLEIBEN.
    _punkte(db, 111, _quer(60))
    _lauf(db)
    c = get_connection(db)
    try:
        c.execute("UPDATE reddung_events SET aufgeloest_am = ? WHERE id = ?",
                  (_iso(JETZT), eid))
        c.commit()
    finally:
        c.close()
    _lauf(db)
    c = get_connection(db)
    try:
        assert c.execute("SELECT count(*) FROM bruegge_soll").fetchone()[0] > 0, \
            "bis dtend sollen Wrack und rote Fackel die Stelle markieren"
        c.execute("UPDATE reddung_events SET dtend = ? WHERE id = ?",
                  (_iso(JETZT - timedelta(minutes=1)), eid))
        c.commit()
    finally:
        c.close()
    _lauf(db)
    c = get_connection(db)
    try:
        assert c.execute("SELECT count(*) FROM bruegge_soll").fetchone()[0] == 0
    finally:
        c.close()


# --- Start-Push (25.09.2026) ----------------------------------------------------------------
#
# „es kam kein Push für den Start des Events." Die Suche beginnt mit der Uhrzeit: Zu
# `dtstart` steht der Havarist im Sektor. Der Hinweis auf die FriesenBruegge gehoert genau
# hierher -- danach ist es fuer den, der sie nicht hat, zu spaet.

def _meldungen(db):
    p = VatsimPoller(db_path=db, callsign_prefix="FRS", poll_interval=60)
    gesendet = []
    p.broadcast_notify = lambda kanal, ziel, payload: gesendet.append(payload)
    asyncio.run(p._check_reddung())
    return [g for g in gesendet if "läuft" in g.get("body", "")]


def test_zum_start_geht_genau_ein_push_raus(db):
    _event(db, start_vor_h=0.05)
    erst = _meldungen(db)
    assert len(erst) == 1, erst
    assert "FriesenBrügge" in erst[0]["body"]
    assert _meldungen(db) == [], "der naechste Takt darf nicht noch einmal melden"


def test_ohne_push_kein_start_push(db):
    _event(db, start_vor_h=0.05, push_enabled=0)
    assert _meldungen(db) == []


def test_ein_vorbeies_event_meldet_keinen_start(db):
    """Laeuft der Poller erst nach dtend wieder an, darf niemand „läuft" lesen."""
    _event(db, start_vor_h=3.0, ende_in_h=-0.5)
    assert _meldungen(db) == []
