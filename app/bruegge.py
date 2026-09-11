"""Die Brügge: Positionsmeldungen aus dem Simulator einem Piloten zuordnen.

Der Vertrag steht in `friesenbruegge/PROTOKOLL.md` (Fassung 1, abgenommen 11.09.2026).
Dieses Modul ist die Serverseite davon — genauer: der Teil, der die Frage beantwortet
*„wer meldet hier?"*, ohne dass die Brügge es sagen müsste.

**Die Matching-Regeln sind aus dem Kniebrett übernommen, nicht neu erfunden.**
`_verkehrZusammenfuehren` (`app/static/index.html:6026`) ordnet seit v13.2.0 Sim-Verkehr und
VATSIM-Verkehr einander zu, und die Konstanten dort sind im Flug erarbeitet — zwei
Fehlversuche am 16.08.2026 stecken in ihnen. Wer sie hier ändert, ändert sie an der falschen
Stelle: Sie gehören langfristig an EINE Stelle statt in zwei Dateien mit zwei Wahrheiten
(s. Protokoll, Abschnitt 5).

Für die Brügge ist die Aufgabe leichter als im Kniebrett: Dort werden *viele* Sim-Flugzeuge
*vielen* VATSIM-Meldungen zugeordnet. Hier ist es **eine** gemeldete Position gegen die Liste
der Friesen.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------------------
# Die Konstanten des Kniebretts, wörtlich übernommen (index.html:5941-5971).
# ---------------------------------------------------------------------------------------

# Wie alt eine VATSIM-Meldung im Mittel ist, wenn sie hier ankommt. Gemessen, nicht geschätzt.
VATSIM_LATENZ_S = 29

# Der erwartete Versatz ist reine Kinematik und wird deshalb GERECHNET, nicht gesetzt: Eine
# C172 legt in 29 s 1,5 km zurück, ein Airliner 6,6 km. Jede feste Zahl wäre für das eine zu
# weit und für das andere zu eng.
PAARUNG_FAKTOR = 2          # deckt Latenzstreuung, Wind, leichte Kurven
PAARUNG_MIN_M = 400         # damit ein STEHENDES Flugzeug überhaupt einen Partner findet
PAARUNG_MIN_FT = 300        # dasselbe für die Höhe
PAARUNG_VORSPRUNG = 0.5     # der beste muss halb so weit weg sein wie der zweitbeste
PAARUNG_LOESEN_FAKTOR = 3   # beim Lösen großzügiger als beim Zuordnen
PAARUNG_LOESEN_TAKTE = 4    # erst nach so vielen Verstößen IN FOLGE

# Ein Sprung über diese Weite zwischen zwei Meldungen ist kein Flug, sondern ein Ladevorgang
# oder ein Slew (Protokoll, Abschnitt 1). 600 kt sind 309 m/s — bei 1-Sekunden-Takt liegt
# selbst ein sehr schnelles Flugzeug darunter.
#
# Gemessen am 11.09.2026: Nach dem Start eines Simulators kommt erst 0°/90° (der
# SimConnect-Nullpunkt), dann Seattle (der Standard-Startpunkt von MSFS), dann der geladene
# Flug. Jeder dieser Werte sieht für sich vernünftig aus — nur der Sprung verrät sie.
SPRUNG_M = 500

ERDRADIUS_M = 6371000.0


def abstand_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinie in Metern (Haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * ERDRADIUS_M * math.asin(math.sqrt(a))


def jetzt_gerechnet(lat: float, lon: float, kurs: float, gs_kt: float,
                    alter_s: float) -> tuple[float, float]:
    """Wo steht ein VATSIM-Flugzeug JETZT, wenn seine Meldung ``alter_s`` alt ist?

    Verglichen wird gegen die fortgerechnete Stelle, nicht gegen die gemeldete — sonst misst
    man das Alter des Feeds mit. Aufgeholt wird damit aber nur das bekannte Alter; die
    Verzögerung im VATSIM-Netz bleibt als Rest stehen, und dafür ist die Schranke da.

    Wörtlich aus `_jetztGerechnet` (index.html), einschließlich des Sicherheitsnetzes nahe
    den Polen: Dort geht der Nenner gegen null und die Längengrad-Rechnung explodiert. Auf
    Friesen-Breiten nie ein Thema, aber es kostet hier nichts.
    """
    if alter_s <= 0 or gs_kt <= 0:
        return lat, lon
    km = gs_kt * 1.852 / 3600 * alter_s
    rad = math.radians(kurs or 0.0)
    d_lat = km * math.cos(rad) / 111.32
    nenner = math.cos(math.radians(lat))
    d_lon = 0.0 if abs(nenner) < 0.01 else km * math.sin(rad) / (111.32 * nenner)
    return lat + d_lat, lon + d_lon


def schranke_m(gs_kt: float, faktor: float) -> float:
    """Wie weit darf die Brügge-Position von der VATSIM-Meldung entfernt sein?

    Keine Geschmacksfrage, sondern Kinematik: Weg = Geschwindigkeit mal Zeit. Die Zeit ist
    gemessen, die Geschwindigkeit kommt aus der Meldung — aktuell und zuverlässig, anders als
    die 29 Sekunden alte VATSIM-Angabe.
    """
    gs_ms = (gs_kt or 0.0) * 0.514444
    # ACHTUNG, ueberraschende Eigenschaft (aus dem Kniebrett uebernommen): Bei gs = 0 ist das
    # Ergebnis unabhaengig vom Faktor immer PAARUNG_MIN_M. Der groesszuegigere
    # PAARUNG_LOESEN_FAKTOR greift also erst oberhalb von rund 13 kt. Fuer ein stehendes
    # Flugzeug ist das unkritisch -- es bewegt sich ja nicht -- aber wer die Konstanten
    # aendert, sollte es wissen, statt es fuer einen Fehler zu halten.
    # Gebunden in tests/test_bruegge.py::test_im_stand_wirkt_der_loesefaktor_nicht.
    return max(PAARUNG_MIN_M, gs_ms * VATSIM_LATENZ_S * faktor)


def schranke_ft(vs_ft_min: float, faktor: float) -> float:
    """Dasselbe für die Höhe.

    Ein sinkendes Flugzeug MUSS von seiner VATSIM-Höhe abweichen: 2000 ft/min ergeben nach
    29 Sekunden 970 Fuß — das ist der Sollwert, kein Fehler. Genau hier kippte die erste
    Fassung im Kniebrett an einer festen Schranke von 1500 ft.
    """
    erwartet = abs(vs_ft_min or 0.0) / 60 * VATSIM_LATENZ_S
    return max(PAARUNG_MIN_FT, erwartet * faktor)


class Kandidat:
    """Ein Friese aus ``live_positions``, auf JETZT fortgerechnet."""

    __slots__ = ("cid", "callsign", "lat", "lon", "alt_ft", "abstand")

    def __init__(self, cid: int, callsign: str, lat: float, lon: float, alt_ft: float):
        self.cid = cid
        self.callsign = callsign
        self.lat = lat
        self.lon = lon
        self.alt_ft = alt_ft
        self.abstand = 0.0


def _alter_s(updated_at: str | None, jetzt: float) -> float:
    """Wie alt ist eine ``live_positions``-Zeile? ``updated_at`` ist ISO-Text, keine Zahl."""
    if not updated_at:
        return 0.0
    try:
        t = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return max(0.0, jetzt - t.timestamp())


def kandidaten_bilden(friesen, jetzt_ts: float | None = None) -> list[Kandidat]:
    """Aus den Zeilen von ``live_positions`` die fortgerechneten Kandidaten machen.

    Nimmt die Spalten, wie sie dort heißen (``latitude``/``longitude``/``updated_at``), statt
    eine Übersetzungsschicht dazwischenzulegen -- die wäre eine zweite Stelle, an der Namen
    auseinanderlaufen können.
    """
    jetzt = jetzt_ts if jetzt_ts is not None else time.time()
    out: list[Kandidat] = []
    for f in friesen:
        f = dict(f)
        lat, lon = f.get("latitude"), f.get("longitude")
        if lat is None or lon is None:
            continue
        alter = _alter_s(f.get("updated_at"), jetzt)
        g_lat, g_lon = jetzt_gerechnet(float(lat), float(lon),
                                       float(f.get("heading") or 0.0),
                                       float(f.get("groundspeed") or 0.0),
                                       alter)
        out.append(Kandidat(int(f["cid"]), str(f.get("callsign") or ""),
                            g_lat, g_lon, float(f.get("altitude") or 0.0)))
    return out


def zuordnen(lat: float, lon: float, alt_ft: float, gs_kt: float,
             kandidaten: list[Kandidat], vs_ft_min: float = 0.0,
             faktor: float = PAARUNG_FAKTOR) -> tuple[Kandidat | None, str]:
    """Welcher Friese meldet hier? ``(Treffer, Begründung)`` — Treffer kann ``None`` sein.

    **Eindeutig heißt: Der beste Kandidat ist DEUTLICH näher als der zweitbeste.**
    Das ersetzt „genau einer innerhalb der Schranke", und der Grund steht im Kniebrett
    ausführlich: Mit 400 m Untergrenze lagen auf dem Vorfeld mehrere Flugzeuge im selben
    Umkreis, mit 150 m fand mancher gar keinen Partner. Beide Male war die Zahl schuld.
    Ein Verhältnis hat diese Schwäche nicht.

    Die Begründung wandert nicht zur Brügge — sie ist für den Admin und fürs Log. Nach außen
    sind „niemand passt" und „nicht auf VATSIM" ununterscheidbar, und zwar mit Absicht
    (Protokoll, Abschnitt 1): Eine Fehlermeldung wäre ein Werkzeug für den, der ausprobiert,
    welche erfundene Position durchgeht.
    """
    max_m = schranke_m(gs_kt, faktor)
    max_ft = schranke_ft(vs_ft_min, faktor)

    passende: list[Kandidat] = []
    for k in kandidaten:
        if abs(k.alt_ft - (alt_ft or 0.0)) > max_ft:
            continue
        m = abstand_m(lat, lon, k.lat, k.lon)
        if m > max_m:
            continue
        k.abstand = m
        passende.append(k)

    if not passende:
        return None, f"kein Kandidat innerhalb {max_m:.0f} m / {max_ft:.0f} ft"

    passende.sort(key=lambda k: k.abstand)
    if len(passende) == 1:
        return passende[0], f"eindeutig, {passende[0].abstand:.0f} m"

    if passende[0].abstand <= passende[1].abstand * PAARUNG_VORSPRUNG:
        return passende[0], (f"Vorsprung: {passende[0].abstand:.0f} m gegen "
                             f"{passende[1].abstand:.0f} m")

    # Mehrere ohne klaren Vorsprung: nicht raten. Eine falsche Zuordnung ist schlimmer als
    # gar keine -- man sieht ihr nicht an, dass sie falsch ist.
    return None, (f"{len(passende)} Kandidaten ohne Vorsprung "
                  f"({passende[0].abstand:.0f} m gegen {passende[1].abstand:.0f} m)")


def bleibt_plausibel(lat: float, lon: float, alt_ft: float, gs_kt: float,
                     kandidat: Kandidat, vs_ft_min: float = 0.0) -> bool:
    """Gilt eine GEMERKTE Zuordnung noch?

    Beim Lösen großzügiger als beim Zuordnen (``PAARUNG_LOESEN_FAKTOR``): Ein zu frühes Lösen
    bringt das Flackern zurück, eine zu weite Erstzuordnung kostet nur Eindeutigkeit.
    """
    if abstand_m(lat, lon, kandidat.lat, kandidat.lon) > schranke_m(gs_kt, PAARUNG_LOESEN_FAKTOR):
        return False
    return abs(kandidat.alt_ft - (alt_ft or 0.0)) <= schranke_ft(vs_ft_min, PAARUNG_LOESEN_FAKTOR)


def ist_sprung(lat: float, lon: float, vor_lat: float | None, vor_lon: float | None) -> bool:
    """Ist die Position gegenüber der vorigen gesprungen?

    Ein Sprung heißt: Ladevorgang, Slew oder Flugwechsel — kein Flug. Solche Punkte gehören
    weder in die Ablage noch in den Track (Protokoll, Abschnitt 1).

    Die erste Meldung einer Brügge hat keinen Vorgänger und gilt nicht als Sprung; sie wird
    stattdessen vom Matching geprüft, und eine Position mitten im Indischen Ozean findet dort
    keinen Friesen.
    """
    if vor_lat is None or vor_lon is None:
        return False
    return abstand_m(lat, lon, vor_lat, vor_lon) > SPRUNG_M
