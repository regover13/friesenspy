# -*- coding: utf-8 -*-
"""Zwei Brüggen, eine Kennung — der Fall vom 14.09.2026.

Die MSFS-Brügge baut ihre Kennung aus der Modul-Adresse und `rand()` ohne `srand()`. In
einem WASM-Modul ist der Speicher linear und bei jedem Start identisch, also erzeugt
**jede** Installation dieselbe Zeichenfolge `9e3711c100000000`.

Live vorgeführt mit zwei Piloten auf Wangerooge, 130 m auseinander: Der Server schrieb die
Position des einen unter die CID des anderen, mit **null** Verstößen — 130 m liegen unter
der 400-m-Toleranz für ein stehendes Flugzeug (`PAARUNG_MIN_M`).

Geprüft wird hier die Server-Seite: Auch bei gemerkter Kennung muss die Vorsprungsregel
greifen, sodass jede Meldung dem zugeordnet wird, der sie geschickt hat.
"""

from app import bruegge

# Die echten Koordinaten des Vorfalls.
FRS49 = (53.787560, 7.909490)
FRS123 = (53.786790, 7.911000)


def _kandidat(cid: int, rufz: str, lat: float, lon: float,
              alt_ft: float = 10.0) -> bruegge.Kandidat:
    return bruegge.Kandidat(cid=cid, callsign=rufz, lat=lat, lon=lon, alt_ft=alt_ft)


def _beide() -> list[bruegge.Kandidat]:
    return [_kandidat(1602713, "FRS49", *FRS49), _kandidat(1642160, "FRS123", *FRS123)]


def test_die_beiden_stehen_naeher_als_die_toleranz():
    """Die Voraussetzung des Falls — sonst prüft der Test etwas anderes."""
    d = bruegge.abstand_m(*FRS49, *FRS123)
    assert 100 < d < bruegge.PAARUNG_MIN_M, f"{d:.0f} m"


def test_bleibt_plausibel_sieht_den_fehler_NICHT():
    """Der Grund, warum es überhaupt schiefging: Die alte Prüfung sagt brav ja."""
    fremder = _kandidat(1642160, "FRS123", *FRS123)
    # FRS49 meldet seine eigene Position -- der gemerkte FRS123 gilt trotzdem als plausibel.
    assert bruegge.bleibt_plausibel(*FRS49, 10.0, 0.0, fremder) is True


def test_vorsprungsregel_haengt_auf_den_tatsaechlichen_melder_um():
    """FRS49 meldet, gemerkt ist FRS123 → der Server muss auf FRS49 umhängen."""
    besser = bruegge.deutlich_besser(*FRS49, 10.0, 0.0, _beide(), gemerkte_cid=1642160)
    assert besser is not None
    assert besser.cid == 1602713


def test_und_in_der_gegenrichtung_genauso():
    """FRS123 meldet, gemerkt ist FRS49 → zurück auf FRS123."""
    besser = bruegge.deutlich_besser(*FRS123, 10.0, 0.0, _beide(), gemerkte_cid=1602713)
    assert besser is not None
    assert besser.cid == 1642160


def test_der_richtige_melder_wird_nicht_angetastet():
    """Meldet der Gemerkte selbst, darf nichts umgehängt werden — sonst flackert es."""
    assert bruegge.deutlich_besser(*FRS49, 10.0, 0.0, _beide(),
                                   gemerkte_cid=1602713) is None
    assert bruegge.deutlich_besser(*FRS123, 10.0, 0.0, _beide(),
                                   gemerkte_cid=1642160) is None


def test_ohne_klaren_vorsprung_wird_nicht_geraten():
    """Genau in der Mitte zwischen beiden: Eine falsche Zuordnung ist schlimmer als keine."""
    mitte = ((FRS49[0] + FRS123[0]) / 2, (FRS49[1] + FRS123[1]) / 2)
    assert bruegge.deutlich_besser(*mitte, 10.0, 0.0, _beide(), gemerkte_cid=1642160) is None


def test_ein_einzelner_kandidat_haengt_nie_um():
    """Ist nur der Gemerkte da, gibt es nichts zu vergleichen."""
    nur_er = [_kandidat(1642160, "FRS123", *FRS123)]
    assert bruegge.deutlich_besser(*FRS123, 10.0, 0.0, nur_er, gemerkte_cid=1642160) is None


def test_die_hoehe_zaehlt_mit():
    """Wer 5000 ft höher fliegt, ist kein besserer Kandidat, so nah er waagerecht auch ist."""
    hoch = [_kandidat(1602713, "FRS49", *FRS49, alt_ft=5000.0), _kandidat(1642160, "FRS123", *FRS123)]
    assert bruegge.deutlich_besser(*FRS49, 10.0, 0.0, hoch, gemerkte_cid=1642160) is None
