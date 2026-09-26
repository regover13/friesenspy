# -*- coding: utf-8 -*-
"""Wem gehört diese FriesenBrügge? Der Weg ab Protokoll 3 (`app/bruegge_bindung.py`, #46).

Jeder Test ist eine These aus dem Beschluss vom 26.09.2026
(docs/superpowers/specs/2026-09-26-bruegge-kennung-und-zuordnung-design.md), die meisten mit dem
Fall, der sie ausgelöst hat.
"""
from __future__ import annotations

import math

import pytest

from app import bruegge_bindung as bb
from app.database import (
    bruegge_zuordnung_holen, bruegge_zuordnung_setzen, get_connection, init_db,
)

B, O = 53.78227, 7.92593
T0 = 1_800_000_000.0          # feste Uhr der Tests (epoch)


def _nord(m: float) -> float:
    return B + m / 111320.0


def _ost(m: float) -> float:
    return O + m / (111320.0 * math.cos(math.radians(B)))


@pytest.fixture()
def conn(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    c = get_connection(p)
    bb._SITZUNGEN.clear()
    bb.ABGELEHNT.clear()
    bb._OHNE_ANMELDEZEIT.clear()
    yield c
    c.close()


def _k(cid, n=0.0, o=0.0, gs=0.0, alt=5.0, logon=T0 + 60, alter=5.0):
    return bb.Kand(cid=cid, callsign=f"FRS{cid}", lat=_nord(n), lon=_ost(o), alt_ft=alt,
                   gs_kt=gs, logon_ts=logon, alter_s=alter)


def _m(n=0.0, o=0.0, gs=0.0, boden=True, alt=5.0):
    return bb.Meldung(lat=_nord(n), lon=_ost(o), alt_ft=alt, gs_kt=gs, am_boden=boden,
                      simulator="msfs2024", protokoll=3)


# --- These 6 und 8: die erste Zuordnung im Stand ----------------------------------------

def test_die_eigene_verbindung_auf_den_meter_wird_gebunden(conn):
    bb.zuordnen(conn, "k1", _m(), [], jetzt=T0)                 # Brügge meldet, noch keine Verbindung
    e = bb.zuordnen(conn, "k1", _m(), [_k(1, n=0.5)], jetzt=T0 + 90)
    assert e.cid == 1 and e.lage_gilt
    z = bruegge_zuordnung_holen(conn, "k1")
    assert z["protokoll"] == 3 and z["bewaehrt_am"] is None


def test_der_nachbar_vom_25_09_bekommt_die_bruegge_nicht(conn):
    """FRS111N stand 22 m daneben und war schon lange verbunden, FRS49 noch nicht."""
    bb.zuordnen(conn, "k1", _m(), [], jetzt=T0)
    e = bb.zuordnen(conn, "k1", _m(), [_k(111, n=22, logon=T0 - 3600)], jetzt=T0 + 5)
    assert e.cid is None
    assert bruegge_zuordnung_holen(conn, "k1") is None


def test_ein_frueher_verbundener_nachbar_auf_dem_meter_zaehlt_nicht(conn):
    """These 8: Wer vor der Brügge verbunden war, ist ein Nachbar -- auch direkt daneben."""
    bb.zuordnen(conn, "k1", _m(), [], jetzt=T0)
    e = bb.zuordnen(conn, "k1", _m(), [_k(111, n=1, logon=T0 - 600)], jetzt=T0 + 5)
    assert e.cid is None
    e = bb.zuordnen(conn, "k1", _m(), [_k(111, n=1, logon=T0 - 600), _k(49, n=0.4)],
                    jetzt=T0 + 60)
    assert e.cid == 49


def test_eine_verbindung_mehr_als_fuenf_meter_weg_zaehlt_nicht(conn):
    bb.zuordnen(conn, "k1", _m(), [], jetzt=T0)
    e = bb.zuordnen(conn, "k1", _m(), [_k(1, n=8)], jetzt=T0 + 90)
    assert e.cid is None


def test_beim_rollen_wird_nicht_ueber_den_abstand_zugeordnet(conn):
    bb.zuordnen(conn, "k1", _m(), [], jetzt=T0)
    e = bb.zuordnen(conn, "k1", _m(gs=12), [_k(1, n=0.5, gs=12)], jetzt=T0 + 90)
    assert e.cid is None


# --- These 7: zwei am selben Punkt ----------------------------------------------------------

def test_gleichstand_wartet_und_das_anrollen_entscheidet(conn):
    bb.zuordnen(conn, "k1", _m(), [], jetzt=T0)
    beide = [_k(1, n=0.5), _k(2, n=1.0)]
    assert bb.zuordnen(conn, "k1", _m(), beide, jetzt=T0 + 60).cid is None
    # Die Brügge rollt an; 12 s später bewegt sich Verbindung 2 auf VATSIM, 1 steht.
    assert bb.zuordnen(conn, "k1", _m(n=5, gs=8), beide, jetzt=T0 + 70).cid is None
    e = bb.zuordnen(conn, "k1", _m(n=60, gs=10), [_k(1, n=0.5), _k(2, n=40, gs=9)],
                    jetzt=T0 + 82)
    assert e.cid == 2


def test_rollen_beide_gleichzeitig_bleibt_es_offen(conn):
    bb.zuordnen(conn, "k1", _m(), [], jetzt=T0)
    beide = [_k(1, n=0.5), _k(2, n=1.0)]
    bb.zuordnen(conn, "k1", _m(), beide, jetzt=T0 + 60)
    bb.zuordnen(conn, "k1", _m(n=5, gs=8), beide, jetzt=T0 + 70)
    e = bb.zuordnen(conn, "k1", _m(n=60, gs=10), [_k(1, n=45, gs=9), _k(2, n=40, gs=9)],
                    jetzt=T0 + 82)
    assert e.cid is None


def test_nach_der_frist_entscheidet_das_anrollen_nicht_mehr(conn):
    bb.zuordnen(conn, "k1", _m(), [], jetzt=T0)
    beide = [_k(1, n=0.5), _k(2, n=1.0)]
    bb.zuordnen(conn, "k1", _m(), beide, jetzt=T0 + 60)
    bb.zuordnen(conn, "k1", _m(n=5, gs=8), beide, jetzt=T0 + 70)
    e = bb.zuordnen(conn, "k1", _m(n=300, gs=10), [_k(1, n=0.5), _k(2, n=250, gs=9)],
                    jetzt=T0 + 105)
    assert e.cid is None


# --- These 2, 3 und 9: Bewährung im Flug -------------------------------------------------------

def _fliegen(conn, kennung, cid, t_start, sekunden, andere=(), takt=1, n0=0.0):
    """Die Brügge fliegt mit 100 kt nach Norden, ihr Partner auf VATSIM 30 m dahinter."""
    e = None
    for i in range(0, sekunden + 1, takt):
        n = n0 + i * 51.4
        kands = [_k(cid, n=n - 30, gs=100, alt=1500)] + [a(n) for a in andere]
        e = bb.zuordnen(conn, kennung, _m(n=n, gs=100, boden=False, alt=1500), kands,
                        jetzt=t_start + i)
    return e


def _gebunden(conn, kennung="k1", cid=1):
    bruegge_zuordnung_setzen(conn, kennung, cid, "msfs2024", 3)
    conn.commit()


def test_zwei_minuten_eindeutig_in_der_luft_bewaehren(conn):
    _gebunden(conn)
    _fliegen(conn, "k1", 1, T0, 110)
    assert bruegge_zuordnung_holen(conn, "k1")["bewaehrt_am"] is None
    _fliegen(conn, "k1", 1, T0 + 111, 15, n0=111 * 51.4)
    assert bruegge_zuordnung_holen(conn, "k1")["bewaehrt_am"] is not None


def test_unter_40_knoten_wird_nicht_bewaehrt(conn):
    _gebunden(conn)
    for i in range(0, 200):
        n = i * 15.0
        bb.zuordnen(conn, "k1", _m(n=n, gs=30, boden=False, alt=800),
                    [_k(1, n=n - 10, gs=30, alt=800)], jetzt=T0 + i)
    assert bruegge_zuordnung_holen(conn, "k1")["bewaehrt_am"] is None


def test_in_formation_wird_nicht_bewaehrt(conn):
    """Der doppelte Abstand: Ein Rottenflieger 60 m daneben lässt nichts eindeutig werden."""
    _gebunden(conn)
    _fliegen(conn, "k1", 1, T0, 200, andere=[lambda n: _k(2, n=n + 30, o=30, gs=100, alt=1500)])
    assert bruegge_zuordnung_holen(conn, "k1")["bewaehrt_am"] is None


def test_eine_unterbrechung_setzt_die_zaehlung_zurueck(conn):
    _gebunden(conn)
    _fliegen(conn, "k1", 1, T0, 100)
    # Kurz fliegt ein anderer dicht vorbei ...
    n = 101 * 51.4
    bb.zuordnen(conn, "k1", _m(n=n, gs=100, boden=False, alt=1500),
                [_k(1, n=n - 30, gs=100, alt=1500), _k(2, n=n + 20, gs=100, alt=1500)],
                jetzt=T0 + 101)
    _fliegen(conn, "k1", 1, T0 + 102, 60, n0=102 * 51.4)
    assert bruegge_zuordnung_holen(conn, "k1")["bewaehrt_am"] is None


def test_wer_selbst_bewaehrt_ist_blockiert_die_bewaehrung_nicht(conn):
    """These 9: Fliegt neben dir ein Friese, dessen eigene bewährte Brügge gerade meldet,
    ist er vergeben und zählt beim Abstand nicht mit."""
    _gebunden(conn, "fremd", 2)
    conn.execute("UPDATE bruegge_zuordnung SET bewaehrt_am = '2026-09-26T00:00:00Z' "
                 "WHERE kennung = 'fremd'")
    conn.commit()
    _gebunden(conn, "k1", 1)
    _fliegen(conn, "k1", 1, T0, 130, andere=[lambda n: _k(2, n=n + 30, o=30, gs=100, alt=1500)])
    assert bruegge_zuordnung_holen(conn, "k1")["bewaehrt_am"] is not None


def test_eine_neue_bruegge_im_flug_wird_nach_zwei_minuten_gebunden_und_bewaehrt(conn):
    """These 6 (im Flug): Sim-Start in der Luft -- gleich nach dem Bewährt-Maßstab."""
    e = _fliegen(conn, "neu", 7, T0, 125)
    assert e.cid == 7
    assert bruegge_zuordnung_holen(conn, "neu")["bewaehrt_am"] is not None


# --- These 4 und 10: die bekannte Brügge ---------------------------------------------------

def test_eine_bekannte_bruegge_wird_ohne_suche_zurueckgebunden(conn):
    """These 10: Auch wenn jemand näher steht -- die Kennung sagt, wer es ist."""
    _gebunden(conn, "k1", 49)
    from app.database import bruegge_zuordnung_loesen
    bruegge_zuordnung_loesen(conn, "k1")
    conn.commit()
    e = bb.zuordnen(conn, "k1", _m(), [_k(111, n=0.2), _k(49, n=3)], jetzt=T0)
    assert e.cid == 49


def test_ist_der_pilot_nicht_online_wartet_sie_und_merkt_sich_ihn(conn):
    _gebunden(conn, "k1", 49)
    e = bb.zuordnen(conn, "k1", _m(), [_k(111, n=0.3)], jetzt=T0)
    assert e.cid is None
    z = bruegge_zuordnung_holen(conn, "k1")
    assert z is not None and int(z["cid"]) == 49 and z["geloest_am"] is not None


def _widerspruch(conn, alter=5.0):
    """Die Brügge fährt los, ihr gebundener Partner steht 2 km entfernt."""
    for i in range(6):
        bb.zuordnen(conn, "k1", _m(n=2000 + i * 5, gs=10), [_k(49, n=0, alter=alter)],
                    jetzt=T0 + i)


def test_ein_widerspruch_vergisst_eine_unbewaehrte_bindung(conn):
    _gebunden(conn, "k1", 49)
    bb.zuordnen(conn, "k1", _m(n=2000), [_k(49, n=2000)], jetzt=T0 - 10)
    _widerspruch(conn)
    assert bruegge_zuordnung_holen(conn, "k1") is None


def test_eine_bewaehrte_bindung_ruht_beim_widerspruch_nur(conn):
    _gebunden(conn, "k1", 49)
    conn.execute("UPDATE bruegge_zuordnung SET bewaehrt_am = '2026-09-26T00:00:00Z'")
    conn.commit()
    bb.zuordnen(conn, "k1", _m(n=2000), [_k(49, n=2000)], jetzt=T0 - 10)
    _widerspruch(conn)
    z = bruegge_zuordnung_holen(conn, "k1")
    assert z is not None and z["geloest_am"] is not None


def test_mit_veralteten_vatsim_daten_zaehlt_kein_widerspruch(conn):
    _gebunden(conn, "k1", 49)
    bb.zuordnen(conn, "k1", _m(n=2000), [_k(49, n=2000)], jetzt=T0 - 10)
    _widerspruch(conn, alter=120.0)
    z = bruegge_zuordnung_holen(conn, "k1")
    assert z is not None and z["geloest_am"] is None


def test_eine_abgelehnte_bruegge_erscheint_als_hinweis(conn):
    """These 5: „gebunden an A, passt zu B" -- sonst steht das nur im Log."""
    _gebunden(conn, "k1", 49)
    for i in range(0, 200, 5):
        bb.zuordnen(conn, "k1", _m(), [_k(111, n=0.3)], jetzt=T0 + i)
    h = bb.hinweise(jetzt=T0 + 200)
    assert h and h[0]["kennung"] == "k1" and h[0]["gebunden"] == 49 and h[0]["passt"] == 111


# --- Nacharbeit nach dem Fable-Review und dem Test am Simulator-Rechner (26.09.2026) --------

def test_hinweis_auch_wenn_der_gebundene_online_ist_aber_nicht_passt(conn):
    """Fable 1: Gerade der Fall für „vergessen" -- A fliegt woanders, B steht auf der Brügge."""
    _gebunden(conn, "k1", 49)
    conn.execute("UPDATE bruegge_zuordnung SET bewaehrt_am = '2026-09-26T00:00:00Z'")
    conn.commit()
    for i in range(0, 200, 5):
        bb.zuordnen(conn, "k1", _m(), [_k(49, n=500000), _k(111, n=0.3)], jetzt=T0 + i)
    h = bb.hinweise(jetzt=T0 + 200)
    assert h and h[0]["gebunden"] == 49 and h[0]["passt"] == 111


def test_nach_vergessen_bindet_sie_im_stand_neu(conn):
    """Fable 2: Nach „vergessen" gilt These 8 einmal nicht -- der Pilot ist ja längst verbunden."""
    _gebunden(conn, "k1", 49)
    from app.database import bruegge_zuordnung_vergessen
    bruegge_zuordnung_vergessen(conn, "k1")
    bb.vergessen_im_speicher("k1")
    conn.commit()
    e = bb.zuordnen(conn, "k1", _m(), [_k(111, n=0.3, logon=T0 - 3600)], jetzt=T0)
    assert e.cid == 111


def test_ein_sprung_laesst_auch_eine_unbewaehrte_bindung_nur_ruhen(conn):
    """Fable 4 / Simulator-Rechner: Einen neuen Flug zu laden ist kein Widerspruch zur Identität.
    Danach bindet die Brügge ohne Suche zurück -- auch wenn der Pilot längst verbunden ist."""
    _gebunden(conn, "k1", 49)
    bb.zuordnen(conn, "k1", _m(), [_k(49, n=0.4)], jetzt=T0)
    bb.zuordnen(conn, "k1", _m(n=50000), [_k(49, n=0.4)], jetzt=T0 + 1)      # Sprung
    z = bruegge_zuordnung_holen(conn, "k1")
    assert z is not None and z["geloest_am"] is not None
    e = bb.zuordnen(conn, "k1", _m(n=50000), [_k(49, n=50000.4, logon=T0 - 3600)],
                    jetzt=T0 + 60)
    assert e.cid == 49


def _mit_spur(m, sekunden, gs=100.0):
    """Eine Meldung im langsamen Takt: mit Spur -- und mit dem Abstand zur vorigen Meldung,
    sonst hielte die Sprungschranke 771 m in 15 s für einen Sprung (Fable-Hinweis)."""
    m.spur_s = float(sekunden)
    m.spur_min_gs = gs
    m.sekunden_her = float(sekunden)
    return m


def test_bewaehrung_bei_langsamem_takt_ueber_die_sekundenspur(conn):
    """Fable 3: Bei 15 s Takt riss das „am Stück" an jeder Meldung. Die Sekundenspur deckt die
    Lücke -- so war es beschlossen."""
    _gebunden(conn)
    for i in range(0, 150, 15):
        n = i * 51.4
        m = _mit_spur(_m(n=n, gs=100, boden=False, alt=1500), 15)
        bb.zuordnen(conn, "k1", m, [_k(1, n=n - 30, gs=100, alt=1500)], jetzt=T0 + i)
    assert bruegge_zuordnung_holen(conn, "k1")["bewaehrt_am"] is not None


def test_eine_langsame_stelle_in_der_spur_unterbricht(conn):
    _gebunden(conn)
    for i in range(0, 150, 15):
        n = i * 51.4
        m = _mit_spur(_m(n=n, gs=100, boden=False, alt=1500), 15,
                      gs=(30.0 if i == 60 else 100.0))
        bb.zuordnen(conn, "k1", m, [_k(1, n=n - 30, gs=100, alt=1500)], jetzt=T0 + i)
    assert bruegge_zuordnung_holen(conn, "k1")["bewaehrt_am"] is None


def test_ein_halt_nach_dem_anrollen_verwirft_den_gleichstand_nicht(conn):
    """Fable 5: an der Haltelinie kurz stehen bleiben -- die Entscheidung läuft weiter."""
    bb.zuordnen(conn, "k1", _m(), [], jetzt=T0)
    beide = [_k(1, n=0.5), _k(2, n=1.0)]
    bb.zuordnen(conn, "k1", _m(), beide, jetzt=T0 + 60)
    bb.zuordnen(conn, "k1", _m(n=5, gs=8), beide, jetzt=T0 + 70)
    bb.zuordnen(conn, "k1", _m(n=30, gs=0.5), beide, jetzt=T0 + 75)       # Halt
    e = bb.zuordnen(conn, "k1", _m(n=60, gs=10), [_k(1, n=0.5), _k(2, n=40, gs=9)],
                    jetzt=T0 + 85)
    assert e.cid == 2


def test_eine_zweite_installation_desselben_piloten_bindet_im_flug(conn):
    """Fable 11: Die andere, bewährte Brügge desselben Piloten stand eben noch woanders -- sie
    deckt seine Verbindung hier nicht ab, er ist also nicht „vergeben"."""
    _gebunden(conn, "rechner1", 7)
    conn.execute("UPDATE bruegge_zuordnung SET bewaehrt_am = '2026-09-26T00:00:00Z', "
                 "gesehen_am = strftime('%Y-%m-%dT%H:%M:%SZ','now')")
    conn.execute("INSERT OR REPLACE INTO bruegge_positions (cid, lat, lon, gemeldet_am) "
                 "VALUES (7, 50.0, 10.0, strftime('%Y-%m-%dT%H:%M:%SZ','now'))")
    conn.commit()
    e = _fliegen(conn, "rechner2", 7, T0, 125)
    assert e.cid == 7


def test_der_sitzungsbeginn_uebersteht_einen_neustart_des_servers(conn):
    """Fable 7: Nach einem Deploy begann jede Sitzung neu -- These 8 sperrte dann jeden, der sich
    zwischen dem wirklichen Start der Brügge und dem Deploy angemeldet hatte."""
    bb.zuordnen(conn, "k1", _m(), [], jetzt=T0)
    conn.commit()
    bb._SITZUNGEN.clear()                                   # Deploy
    e = bb.zuordnen(conn, "k1", _m(), [_k(49, n=0.4, logon=T0 + 60)], jetzt=T0 + 90)
    assert e.cid == 49


def test_die_kollisionskennung_wird_nie_gebunden(conn):
    """Die Fassungen vom 11.–14.09. schrieben auf JEDEM Rechner dieselbe Kennung nach \\work."""
    bb.zuordnen(conn, "9e3711c100000000", _m(), [], jetzt=T0)
    e = bb.zuordnen(conn, "9e3711c100000000", _m(), [_k(49, n=0.4)], jetzt=T0 + 60)
    assert e.cid is None
    assert bruegge_zuordnung_holen(conn, "9e3711c100000000") is None
