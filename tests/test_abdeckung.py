# -*- coding: utf-8 -*-
"""Der Abdeckungskern (``app/abdeckung.py``) — Geometrie, Fenster, Erstabdeckung (20.09.2026).

Drei Eventtypen wollen dieselbe Frage beantwortet haben: *Ist dieses Ziel tief und langsam
überflogen worden, und von wem zuerst?* Zählflug (#20) fragt es für eine Punktliste,
Deichkontrolle (#22) für Abschnitte einer Linie, FriesenReddung (#21) für ein Zellraster **und** für
den Havaristen — der ist nur ein Ziel mit engem Radius.

**Warum die Tests gegen Strecken prüfen und nicht gegen Punkte.** Gemessen am 20.09.2026 über
40.570 Punktpaare der Produktion (unter 4.000 ft, in Bewegung) liegen aufeinanderfolgende
Positionen **0,95 km** auseinander (Median; p90 1,35 km, p99 2,45 km, Ausreißer bis 12,6 km),
bei 15 s Abstand. Ein Fundradius unter ~1,3 km ist damit **punktweise nicht entscheidbar** —
der Pilot rutscht zwischen zwei Messpunkten über den Havaristen hinweg. Deshalb rechnet der
Kern Abstand Punkt-zu-Strecke, und deshalb steht hier ein Test, der genau das erzwingt.
"""
from __future__ import annotations

import math
import random

import pytest

from app import geo
from app.abdeckung import (
    Fenster,
    abdeckung,
    abschnitte_aus_linie,
    abstand_zu_strecke_km,
    bezugsbreite,
    zellen_aus_box,
)

# Mitte des ostfriesischen Wattenmeers — alle Testfälle liegen hier, damit die flache
# Projektion in ihrem dokumentierten Gültigkeitsbereich arbeitet.
LAT, LON = 53.72, 7.25
GRAD_JE_KM_LAT = 1.0 / 111.32
GRAD_JE_KM_LON = 1.0 / (111.32 * math.cos(math.radians(LAT)))

#: Weit offen — wer das Fenster nicht selbst prüft, soll nicht daran scheitern.
OFFEN = Fenster(hoehe_max_ft=5000, gs_max_kt=300)


def nord(km: float) -> float:
    return LAT + km * GRAD_JE_KM_LAT


def ost(km: float) -> float:
    return LON + km * GRAD_JE_KM_LON


def punkt(lat, lon, *, hoehe=800.0, gs=110.0, ts="2026-09-20T12:00:00Z"):
    return (lat, lon, hoehe, gs, ts)


def spur(cid, *punkte):
    return (cid, list(punkte))


def ts(sekunden: int) -> str:
    m, s = divmod(sekunden, 60)
    return f"2026-09-20T12:{m:02d}:{s:02d}Z"


class TestGeometrie:
    """Abstand Punkt-zu-Strecke — die einzige Rechnung, die wirklich schiefgehen kann."""

    def test_punkt_auf_der_strecke_hat_abstand_null(self):
        assert abstand_zu_strecke_km(LAT, LON, nord(-2), LON, nord(2), LON) == pytest.approx(0, abs=0.01)

    def test_seitlicher_abstand_wird_gemessen(self):
        # Strecke laeuft 4 km nach Osten, Ziel liegt 2 km noerdlich der Mitte
        d = abstand_zu_strecke_km(nord(2), ost(2), LAT, LON, LAT, ost(4))
        assert d == pytest.approx(2.0, rel=0.01)

    def test_ziel_hinter_dem_streckenende_zaehlt_ab_dem_endpunkt(self):
        """Der Fall, der bei naiver Rechnung mit der UNENDLICHEN Gerade falsch wird: Auf der
        Verlaengerung der Strecke ist der Geradenabstand null, der Streckenabstand aber 3 km."""
        d = abstand_zu_strecke_km(LAT, ost(5), LAT, LON, LAT, ost(2))
        assert d == pytest.approx(3.0, rel=0.01)

    def test_strecke_der_laenge_null_ist_ein_punktabstand(self):
        d = abstand_zu_strecke_km(nord(1), LON, LAT, LON, LAT, LON)
        assert d == pytest.approx(1.0, rel=0.01)

    def test_die_flache_rechnung_bleibt_unter_zwei_promille(self):
        """Die flache Projektion ist der Grund, warum die Rechnung schnell ist.

        Der naheliegende Test — „Abweichung gegen ``geo.haversine`` unter einem Promille" —
        prüft die falsche Sache und war zuerst genau so geschrieben. Gemessen (mit geteiltem
        Maßstab, sonst misst der Test seine eigene Punktkonstruktion):

        ======  ========  ========  ========  ========
        km        0 Grad   45 Grad   90 Grad  135 Grad
        ======  ========  ========  ========  ========
        0,2     1,12e-03  1,13e-03  1,12e-03  1,12e-03
        5       1,12e-03  1,31e-03  1,12e-03  9,4e-04
        20      1,12e-03  1,88e-03  1,13e-03  3,7e-04
        ======  ========  ========  ========  ========

        **1,12 Promille davon sind eine Konstante** und stammen aus der Länge eines
        Breitengrads (111,32 km hier gegen 111,195 km auf der Kugel mit R = 6371 km) — sie
        stehen schon bei 200 m da. Der eigene Beitrag der Ebene ist der Rest: über 20 km
        **0,76 Promille**, richtungsabhängig, bei 1 km nicht messbar. Auf einen Radius von
        1,5 km sind das drei Meter.
        """
        fehler = {}
        for km in (0.2, 1, 5, 10, 20):
            for richtung in (0, 45, 90, 135, 180, 225, 270, 315):
                zlat = LAT + km * GRAD_JE_KM_LAT * math.cos(math.radians(richtung))
                zlon = LON + km * GRAD_JE_KM_LON * math.sin(math.radians(richtung))
                # bezug_lat = LAT: dieselbe Grundlage, mit der die Punkte gebaut wurden.
                flach = abstand_zu_strecke_km(zlat, zlon, LAT, LON, LAT, LON, bezug_lat=LAT)
                rund = geo.haversine(LAT, LON, zlat, zlon)
                fehler[(km, richtung)] = abs(flach - rund) / rund
        assert max(fehler.values()) < 2e-3, fehler
        # Und der Teil, der wirklich der Ebene gehoert: die Streuung um die Konstante.
        nah = max(f for (km, _r), f in fehler.items() if km == 0.2)
        weit = max(fehler.values())
        assert weit - nah < 1e-3, f"Ebenenfehler laeuft davon: {nah:.2e} nah, {weit:.2e} weit"

    def test_einzelabstand_urteilt_nur_mit_bezugsbreite_wie_der_lauf(self):
        """⚠ Die Falle, die der Gleichheitstest unten gefunden hat. Ohne ``bezug_lat`` nimmt
        der Einzelabstand die Breite seines Ziels, der Lauf das Mittel aller Ziele — über
        einen Sektor sind das 0,25 % Unterschied, und ein Ziel am Rand seines Radius wird
        einmal so und einmal anders entschieden. Fuer die Fundpruefung im Sekundentakt heisst
        das: bei 1 Hz gefunden, in der Abendbilanz nicht."""
        ziele = [("sued", 53.0, 7.0, 1.0), ("nord", 54.0, 7.0, 1.0)]
        mitte = bezugsbreite(ziele)
        assert mitte == pytest.approx(53.5)
        eigen = abstand_zu_strecke_km(53.0, 7.0, 53.0, 7.05, 53.0, 7.06)
        geteilt = abstand_zu_strecke_km(53.0, 7.0, 53.0, 7.05, 53.0, 7.06, bezug_lat=mitte)
        assert eigen != geteilt
        assert abs(eigen - geteilt) / eigen < 0.02


class TestReichweite:
    def test_ziel_in_reichweite_wird_abgedeckt(self):
        erg = abdeckung([spur(1, punkt(nord(-2), LON), punkt(nord(2), LON))],
                        [("z1", LAT, LON, 1.0)], OFFEN)
        assert erg.treffer["z1"].cid == 1
        assert erg.offen == ()
        assert erg.anteil == 1.0

    def test_ziel_knapp_ausserhalb_bleibt_offen(self):
        ziele = [("z1", nord(2), LON, 1.0)]        # 2 km neben der Strecke, Radius 1 km
        erg = abdeckung([spur(1, punkt(LAT, LON), punkt(LAT, ost(4)))], ziele, OFFEN)
        assert erg.treffer == {}
        assert erg.offen == ("z1",)
        assert erg.anteil == 0.0

    def test_derselbe_fall_mit_weiterem_radius_deckt_ab(self):
        """Gegenprobe zum Test darueber: es liegt am Radius, nicht an der Geometrie."""
        ziele = [("z1", nord(2), LON, 2.5)]
        erg = abdeckung([spur(1, punkt(LAT, LON), punkt(LAT, ost(4)))], ziele, OFFEN)
        assert "z1" in erg.treffer

    def test_zwischen_zwei_messpunkten_wird_gefunden(self):
        """Der Kernbefund der Messung: 15 s Abstand, 2,4 km Luecke, Havarist mit 400 m Radius
        genau in der Mitte. Punktweise wuerde hier NICHTS ausloesen."""
        a, b = punkt(LAT, LON, ts=ts(0)), punkt(LAT, ost(2.4), ts=ts(15))
        havarist = [("havarist", LAT, ost(1.2), 0.4)]
        assert geo.haversine(LAT, LON, LAT, ost(1.2)) > 1.0      # weit weg von BEIDEN Punkten
        assert geo.haversine(LAT, ost(2.4), LAT, ost(1.2)) > 1.0
        erg = abdeckung([spur(1, a, b)], havarist, OFFEN)
        assert "havarist" in erg.treffer


class TestFenster:
    def test_beide_endpunkte_muessen_unter_der_hoehenschranke_liegen(self):
        ziele = [("z1", LAT, LON, 1.0)]
        eng = Fenster(hoehe_max_ft=1000, gs_max_kt=300)
        hoch_und_tief = spur(1, punkt(nord(-2), LON, hoehe=1500), punkt(nord(2), LON, hoehe=500))
        assert abdeckung([hoch_und_tief], ziele, eng).treffer == {}
        beide_tief = spur(1, punkt(nord(-2), LON, hoehe=900), punkt(nord(2), LON, hoehe=500))
        assert "z1" in abdeckung([beide_tief], ziele, eng).treffer

    def test_die_hoehenschranke_selbst_gilt_noch_als_drin(self):
        ziele = [("z1", LAT, LON, 1.0)]
        eng = Fenster(hoehe_max_ft=1000, gs_max_kt=300)
        genau = spur(1, punkt(nord(-2), LON, hoehe=1000), punkt(nord(2), LON, hoehe=1000))
        assert "z1" in abdeckung([genau], ziele, eng).treffer

    def test_zu_schnell_zaehlt_nicht(self):
        ziele = [("z1", LAT, LON, 1.0)]
        eng = Fenster(hoehe_max_ft=5000, gs_max_kt=120)
        rasant = spur(1, punkt(nord(-2), LON, gs=160), punkt(nord(2), LON, gs=110))
        assert abdeckung([rasant], ziele, eng).treffer == {}

    def test_stillstand_zaehlt_nicht_wenn_eine_untergrenze_gesetzt_ist(self):
        """Sonst deckt ein am Boden parkendes Flugzeug seine Zelle die ganze Nacht ab."""
        ziele = [("z1", LAT, LON, 1.0)]
        eng = Fenster(hoehe_max_ft=5000, gs_max_kt=300, gs_min_kt=30)
        steht = spur(1, punkt(LAT, LON, gs=0, ts=ts(0)), punkt(LAT, LON, gs=0, ts=ts(15)))
        assert abdeckung([steht], ziele, eng).treffer == {}

    def test_fehlende_hoehe_macht_das_segment_unbrauchbar(self):
        """NULL heisst nicht null Fuss. Ohne Hoehe ist der Ueberflug nicht belegbar."""
        ziele = [("z1", LAT, LON, 1.0)]
        ohne = spur(1, punkt(nord(-2), LON, hoehe=None), punkt(nord(2), LON))
        assert abdeckung([ohne], ziele, OFFEN).treffer == {}

    def test_fehlende_geschwindigkeit_macht_das_segment_unbrauchbar(self):
        ziele = [("z1", LAT, LON, 1.0)]
        ohne = spur(1, punkt(nord(-2), LON, gs=None), punkt(nord(2), LON))
        assert abdeckung([ohne], ziele, OFFEN).treffer == {}


class TestKappungen:
    def test_zu_langes_segment_faellt_weg(self):
        """Ueber 60 s weiss niemand, was dazwischen geflogen wurde — p99 der Messung liegt bei
        22 s, es trifft also praktisch nur die echten Luecken."""
        ziele = [("z1", LAT, LON, 1.0)]
        lang = spur(1, punkt(nord(-2), LON, ts=ts(0)), punkt(nord(2), LON, ts=ts(90)))
        assert abdeckung([lang], ziele, OFFEN).treffer == {}

    def test_knapp_unter_der_zeitkappung_zaehlt_noch(self):
        ziele = [("z1", LAT, LON, 1.0)]
        knapp = spur(1, punkt(nord(-2), LON, ts=ts(0)), punkt(nord(2), LON, ts=ts(55)))
        assert "z1" in abdeckung([knapp], ziele, OFFEN).treffer

    def test_zu_weites_segment_faellt_weg(self):
        """Der Sprung beim Laden eines Flugs oder beim Slew: 12,6 km in 15 s stand so in der
        Messung. Ohne diese Kappung gilt die ganze Luftlinie als abgesucht."""
        ziele = [("z1", LAT, LON, 1.0)]
        sprung = spur(1, punkt(nord(-20), LON, ts=ts(0)), punkt(nord(20), LON, ts=ts(15)))
        assert abdeckung([sprung], ziele, OFFEN).treffer == {}

    def test_rueckwaerts_laufende_zeit_wird_nicht_gewertet(self):
        ziele = [("z1", LAT, LON, 1.0)]
        rueck = spur(1, punkt(nord(-2), LON, ts=ts(30)), punkt(nord(2), LON, ts=ts(10)))
        assert abdeckung([rueck], ziele, OFFEN).treffer == {}

    def test_gleicher_zeitstempel_zweimal_zaehlt_noch(self):
        """2,8 % der Folgepositionen sind identisch (gemessen). Das ist der Normalfall eines
        haengenden VATSIM-Datensatzes, kein Fehler — und ein Punktabstand bleibt gueltig."""
        ziele = [("z1", LAT, LON, 1.0)]
        doppelt = spur(1, punkt(LAT, LON, ts=ts(0)), punkt(LAT, LON, ts=ts(0)))
        assert "z1" in abdeckung([doppelt], ziele, OFFEN).treffer


class TestErstabdeckung:
    def test_der_frueheste_ueberflug_gewinnt_das_ziel(self):
        ziele = [("z1", LAT, LON, 1.0)]
        spaet = spur(7, punkt(nord(-2), LON, ts=ts(0)), punkt(nord(2), LON, ts=ts(40)))
        frueh = spur(9, punkt(nord(-2), LON, ts=ts(5)), punkt(nord(2), LON, ts=ts(20)))
        erg = abdeckung([spaet, frueh], ziele, OFFEN)
        assert erg.treffer["z1"].cid == 9, "gewertet wird das Ende des Segments, nicht sein Anfang"
        assert erg.treffer["z1"].ts == ts(20)

    def test_gleichstand_entscheidet_die_kleinere_cid(self):
        """Damit zweimal Rechnen dasselbe sagt — sonst haengt das Ergebnis an der Sortierung."""
        ziele = [("z1", LAT, LON, 1.0)]
        a = spur(42, punkt(nord(-2), LON, ts=ts(0)), punkt(nord(2), LON, ts=ts(15)))
        b = spur(11, punkt(nord(-2), ost(0.1), ts=ts(0)), punkt(nord(2), ost(0.1), ts=ts(15)))
        assert abdeckung([a, b], ziele, OFFEN).treffer["z1"].cid == 11
        assert abdeckung([b, a], ziele, OFFEN).treffer["z1"].cid == 11

    def test_je_pilot_zaehlt_nur_erstabdeckungen(self):
        ziele = [("z1", LAT, LON, 1.0), ("z2", nord(6), LON, 1.0)]
        erster = spur(1, punkt(nord(-2), LON, ts=ts(0)), punkt(nord(2), LON, ts=ts(15)))
        zweiter = spur(2, punkt(nord(4), LON, ts=ts(20)), punkt(nord(8), LON, ts=ts(50)))
        erg = abdeckung([erster, zweiter], ziele, OFFEN)
        assert erg.je_pilot == {1: 1, 2: 1}, "z1 gehoert dem Ersten, z2 dem Zweiten"

    def test_wer_nichts_abdeckt_steht_mit_null_da(self):
        """Sonst fehlt er in der Abendbilanz ganz — mitgeflogen ist er trotzdem."""
        ziele = [("z1", LAT, LON, 1.0)]
        treffer = spur(1, punkt(nord(-2), LON), punkt(nord(2), LON))
        daneben = spur(2, punkt(nord(40), LON), punkt(nord(44), LON))
        assert abdeckung([treffer, daneben], ziele, OFFEN).je_pilot == {1: 1, 2: 0}


class TestVorfilter:
    def test_der_vorfilter_liefert_dasselbe_wie_die_naive_rechnung(self):
        """Der wichtigste Test des Moduls. Der Kachelfilter ist der Grund, warum die Rechnung
        68 ms statt 1.393 ms braucht — und die einzige Stelle, an der ein Fehler sich als
        *fehlende* Abdeckung tarnt, die niemandem auffaellt. Deshalb hier gegen die stumpfe
        Rechnung ueber Zufallsdaten geprueft, nicht gegen erwartete Werte."""
        zufall = random.Random(20260920)
        ziele = zellen_aus_box(LAT - 0.18, LON - 0.30, LAT + 0.18, LON + 0.30,
                               kante_km=2.0, korridor_km=1.5)
        spuren = []
        for cid in range(1, 6):
            lat, lon = LAT + zufall.uniform(-.15, .15), LON + zufall.uniform(-.25, .25)
            kurs = zufall.uniform(0, 360)
            punkte = []
            for k in range(120):
                if k % 25 == 0:
                    kurs = (kurs + zufall.uniform(60, 120)) % 360
                weg = 110 * 1.852 * 15 / 3600
                lat += weg * math.cos(math.radians(kurs)) * GRAD_JE_KM_LAT
                lon += weg * math.sin(math.radians(kurs)) * GRAD_JE_KM_LON
                punkte.append(punkt(lat, lon, ts=ts(k * 15 % 3600)))
            spuren.append((cid, punkte))

        erg = abdeckung(spuren, ziele, OFFEN)

        # Stumpfe Gegenrechnung: jedes Segment gegen jedes Ziel, ohne jeden Filter.
        roh: dict[str, tuple[str, int]] = {}
        for cid, punkte in spuren:
            for a, b in zip(punkte, punkte[1:]):
                for schluessel, zlat, zlon, radius in ziele:
                    # bezug_lat wie im Lauf -- ohne diese Zeile prueft der Test die
                    # Projektion statt den Filter (s. Test oben).
                    if abstand_zu_strecke_km(zlat, zlon, a[0], a[1], b[0], b[1],
                                             bezug_lat=bezugsbreite(ziele)) <= radius:
                        marke = (b[4], cid)
                        if schluessel not in roh or marke < roh[schluessel]:
                            roh[schluessel] = marke
        assert {k: (t.ts, t.cid) for k, t in erg.treffer.items()} == roh
        assert len(erg.treffer) > 20, "sonst prueft der Test nichts"


class TestZiellisten:
    def test_zellen_aus_box_deckt_die_box_lueckenlos_ab(self):
        """Kante gleich Korridor: jeder Punkt der Box liegt im Radius mindestens einer Zelle.

        ⚠ **Gerastert, nicht ausgelost.** Zuerst stand hier eine Stichprobe von 300
        Zufallspunkten — und die ließ eine abgerundete Zellenzahl durchgehen, die den Rand der
        Box abschneidet: Der unversorgte Streifen ist 0,26 × 0,9 km groß, die Box 22 × 33 km,
        also trifft ihn die Auslosung so gut wie nie. Der schlimmste Fall liegt IMMER in einer
        Ecke; er gehört geprüft, nicht gehofft. (Gegengeprüft: mit ``int`` statt ``ceil`` in
        ``zellen_aus_box`` wird dieser Test rot, die Zufallsfassung blieb grün.)
        """
        sued, west, nord, ost = 53.6, 7.0, 53.8, 7.5
        ziele = zellen_aus_box(sued, west, nord, ost, kante_km=2.0, korridor_km=2.0)
        schritte = 40
        for i in range(schritte + 1):                     # Rand eingeschlossen
            plat = sued + (nord - sued) * i / schritte
            for j in range(schritte + 1):
                plon = west + (ost - west) * j / schritte
                naechster = min(geo.haversine(plat, plon, z[1], z[2]) for z in ziele)
                assert naechster <= 2.0, (plat, plon, round(naechster, 3))

    def test_zu_grosse_kante_laesst_loecher(self):
        """Die Kopplung, die man leicht uebersieht — hier festgehalten, damit sie beim
        Einstellen der Werte im Admin nicht als Zufall erscheint."""
        ziele = zellen_aus_box(53.6, 7.0, 53.8, 7.5, kante_km=6.0, korridor_km=1.5)
        zufall = random.Random(2)
        loecher = 0
        for _ in range(300):
            plat, plon = zufall.uniform(53.6, 53.8), zufall.uniform(7.0, 7.5)
            if min(geo.haversine(plat, plon, z[1], z[2]) for z in ziele) > 1.5:
                loecher += 1
        assert loecher > 0

    def test_zellen_haben_stabile_schluessel(self):
        a = zellen_aus_box(53.6, 7.0, 53.8, 7.5, kante_km=2.0, korridor_km=1.5)
        b = zellen_aus_box(53.6, 7.0, 53.8, 7.5, kante_km=2.0, korridor_km=1.5)
        assert [z[0] for z in a] == [z[0] for z in b]
        assert len(set(z[0] for z in a)) == len(a)

    def test_zellen_tragen_den_korridor_als_radius(self):
        for _, _, _, radius in zellen_aus_box(53.6, 7.0, 53.8, 7.5, kante_km=2.0, korridor_km=1.5):
            assert radius == 1.5

    def test_abschnitte_liegen_auf_der_linie(self):
        linie = [(53.70, 7.10), (53.70, 7.40), (53.75, 7.60)]
        ziele = abschnitte_aus_linie(linie, laenge_km=2.0, korridor_km=1.0)
        assert len(ziele) > 10
        for _, zlat, zlon, _ in ziele:
            naechster = min(abstand_zu_strecke_km(zlat, zlon, a[0], a[1], b[0], b[1])
                            for a, b in zip(linie, linie[1:]))
            assert naechster < 0.05, (zlat, zlon, naechster)

    def test_abschnitte_decken_die_ganze_linie_ab(self):
        """Kein Stueck der Linie darf zwischen zwei Abschnitten hindurchfallen."""
        linie = [(53.70, 7.10), (53.70, 7.40)]
        ziele = abschnitte_aus_linie(linie, laenge_km=2.0, korridor_km=1.2)
        for anteil in [i / 200 for i in range(201)]:
            plon = 7.10 + anteil * (7.40 - 7.10)
            assert min(geo.haversine(53.70, plon, z[1], z[2]) for z in ziele) <= 1.2

    def test_kurze_linie_ergibt_einen_abschnitt(self):
        ziele = abschnitte_aus_linie([(53.70, 7.10), (53.70, 7.105)], laenge_km=5.0, korridor_km=1.0)
        assert len(ziele) == 1

    def test_leere_linie_ergibt_keine_abschnitte(self):
        assert abschnitte_aus_linie([], laenge_km=2.0, korridor_km=1.0) == []
        assert abschnitte_aus_linie([(53.7, 7.1)], laenge_km=2.0, korridor_km=1.0) == []


class TestRandfaelle:
    def test_ohne_ziele_ist_der_anteil_null(self):
        erg = abdeckung([spur(1, punkt(LAT, LON), punkt(nord(1), LON))], [], OFFEN)
        assert erg.anteil == 0.0 and erg.treffer == {} and erg.offen == ()

    def test_ohne_spuren_bleibt_alles_offen(self):
        erg = abdeckung([], [("z1", LAT, LON, 1.0)], OFFEN)
        assert erg.offen == ("z1",) and erg.anteil == 0.0 and erg.je_pilot == {}

    def test_spur_mit_einem_punkt_hat_kein_segment(self):
        erg = abdeckung([spur(1, punkt(LAT, LON))], [("z1", LAT, LON, 1.0)], OFFEN)
        assert erg.treffer == {} and erg.je_pilot == {1: 0}

    def test_leere_spur_stoert_nicht(self):
        erg = abdeckung([(1, [])], [("z1", LAT, LON, 1.0)], OFFEN)
        assert erg.treffer == {} and erg.je_pilot == {1: 0}

    def test_havarist_und_raster_im_selben_lauf(self):
        """Der FriesenReddung in einem Aufruf: 400 m um den Havaristen, 1,5 km je Rasterzelle."""
        ziele = zellen_aus_box(LAT - 0.09, LON - 0.15, LAT + 0.09, LON + 0.15,
                               kante_km=2.0, korridor_km=1.5)
        ziele.append(("havarist", nord(1), ost(1), 0.4))
        vorbei = spur(1, punkt(LAT, ost(-2.5), ts=ts(0)), punkt(LAT, ost(2.5), ts=ts(30)))
        erg = abdeckung([vorbei], ziele, OFFEN)
        assert "havarist" not in erg.treffer, "1 km daneben bei 400 m Radius"
        drueber = spur(2, punkt(nord(1), ost(-2.5), ts=ts(0)), punkt(nord(1), ost(2.5), ts=ts(30)))
        erg2 = abdeckung([vorbei, drueber], ziele, OFFEN)
        assert erg2.treffer["havarist"].cid == 2
        assert 0 < erg2.anteil < 1

    def test_die_koordinate_taucht_im_ergebnis_nicht_auf(self):
        """Die Kernanforderung der FriesenReddung (#21): Der Server darf die Lage des Havaristen
        NIEMALS herausgeben. Das Ergebnis dieses Moduls geht in API-Antworten — es darf den
        Schluessel nennen, nicht den Ort."""
        import json
        from dataclasses import asdict
        ziele = [("havarist", nord(1), ost(1), 0.4)]
        drueber = spur(2, punkt(nord(1), ost(-2.5), ts=ts(0)), punkt(nord(1), ost(2.5), ts=ts(30)))
        erg = abdeckung([drueber], ziele, OFFEN)
        text = json.dumps(asdict(erg))
        assert "havarist" in text
        for zahl in (f"{nord(1):.4f}", f"{ost(1):.4f}"):
            assert zahl not in text, f"Koordinate {zahl} steht im Ergebnis"


# --- raster_masse: die Geometrie des Sektorrasters (Spec 2026-09-23, Abschnitt 3) ---------

from app.abdeckung import raster_masse, zellen_aus_box  # noqa: E402


def test_raster_masse_passt_zu_zellen_aus_box():
    """Die Karte rechnet Zellen aus (zeilen, spalten, d_lat, d_lon). Weicht das von
    zellen_aus_box ab, liegt jede gezeichnete Zelle neben der gewerteten."""
    box = (53.54, 6.95, 53.90, 7.55)
    zeilen, spalten, d_lat, d_lon = raster_masse(*box, kante_km=1.0)
    ziele = zellen_aus_box(*box, kante_km=1.0, korridor_km=1.0)
    assert len(ziele) == zeilen * spalten
    for schluessel, lat, lon, _r in ziele:
        i, j = (int(x) for x in schluessel[1:].split("_"))
        assert box[0] + i * d_lat < lat < box[0] + (i + 1) * d_lat, schluessel
        assert box[1] + j * d_lon < lon < box[1] + (j + 1) * d_lon, schluessel


def test_raster_masse_sortiert_vertauschte_ecken():
    assert raster_masse(53.90, 7.55, 53.54, 6.95, 1.0) == raster_masse(53.54, 6.95, 53.90, 7.55, 1.0)


def test_raster_masse_klemmt_die_kante_wie_zellen_aus_box():
    """Eine Null-Kante darf kein Raster aus Millionen Zellen ergeben -- dieselbe Klemme."""
    zeilen, spalten, _, _ = raster_masse(53.54, 6.95, 53.56, 6.97, 0.0)
    assert zeilen * spalten == len(zellen_aus_box(53.54, 6.95, 53.56, 6.97, 0.0, 1.0))


# --- Fläche mit angeschnittenen Randzellen (#44, Punkt 8) -------------------------------

from app.abdeckung import box_flaeche_km2, zellen_flaeche_km2  # noqa: E402


def test_volle_abdeckung_ist_genau_die_sektorflaeche():
    """Die letzte Zeile/Spalte ragt ueber den Sektor (aufgerundet). Voll gezaehlt waren das bei
    Event 2 138 km^2 Raster gegen 126 km^2 Sektor -- +9 %. Gezaehlt wird jetzt nur, was im
    Sektor liegt."""
    box = (53.54, 6.95, 53.575, 7.012)          # kein Vielfaches der Kante
    zeilen, spalten, _, _ = raster_masse(*box, 1.0)
    alle = [f"z{i}_{j}" for i in range(zeilen) for j in range(spalten)]
    assert zellen_flaeche_km2(*box, 1.0, alle) == pytest.approx(box_flaeche_km2(*box))
    assert box_flaeche_km2(*box) < zeilen * spalten * 1.0


def test_eine_innere_zelle_hat_kante_zum_quadrat():
    box = (53.54, 6.95, 53.90, 7.55)
    assert zellen_flaeche_km2(*box, 1.0, ["z3_4"]) == pytest.approx(1.0)
    assert zellen_flaeche_km2(*box, 0.5, ["z3_4"]) == pytest.approx(0.25)
    assert zellen_flaeche_km2(*box, 1.0, []) == 0.0
