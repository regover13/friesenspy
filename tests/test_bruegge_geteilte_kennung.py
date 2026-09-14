# -*- coding: utf-8 -*-
"""Zwei Brüggen am selben Ort — der Fall vom 14.09.2026, und was ihn löst.

Zwei Piloten stehen auf demselben Vorfeld, beide mit Brügge. Der Server bekommt zwei
Meldungen, die einander zum Verwechseln ähnlich sehen, und muss sie auseinanderhalten.

**Erster Anlauf war `deutlich_besser`, und er war falsch.** Er hängte eine gemerkte
Zuordnung bei jeder Meldung um, sobald ein anderer Kandidat halb so weit weg war — ohne
Verstoßzähler. Das hat live so ausgesehen::

    19:30:22  Kennung 9e3711c100000000 haengt um, 1642160 -> 1602713 (572 m gegen 1175 m)

572/1175 = 0,486, also knapp „deutlich besser": Einem Piloten wurde seine Zuordnung bei
572 m Abstand an jemanden abgegeben, der 1,2 km entfernt war. Die Funktion ist entfernt.

**Richtig ist `belegt`** — `frei[]` aus dem Kniebrett (`index.html`): Wessen CID gerade eine
ANDERE Brügge meldet, der ist als Kandidat vergeben. Damit braucht es keine Umhäng-Regel,
weil die Verwechslung gar nicht erst entsteht.

⚠ Diese Datei arbeitet deshalb mit **zwei verschiedenen** Kennungen. Bei einer geteilten
Kennung kann `belegt` nichts ausrichten — dann gibt es nur eine Zeile in
`bruegge_zuordnung`, und „vergeben" ist nicht definierbar. Die geteilte Kennung ist ein
Client-Fehler und seit v14.40.0 an der Wurzel behoben (der Server vergibt sie).
"""

from app import bruegge

# Die echten Koordinaten des Vorfalls (Wangerooge).
FRS49 = (53.787560, 7.909490)
FRS123 = (53.786790, 7.911000)

# Ungefähr mittig zwischen beiden: von hier aus hat keiner der beiden einen Vorsprung.
MITTE = ((FRS49[0] + FRS123[0]) / 2, (FRS49[1] + FRS123[1]) / 2)


def _kandidat(cid: int, rufz: str, lat: float, lon: float,
              alt_ft: float = 10.0) -> bruegge.Kandidat:
    return bruegge.Kandidat(cid=cid, callsign=rufz, lat=lat, lon=lon, alt_ft=alt_ft)


def _beide() -> list[bruegge.Kandidat]:
    return [_kandidat(1602713, "FRS49", *FRS49), _kandidat(1642160, "FRS123", *FRS123)]


# ---------------------------------------------------------------------------------------
# Die Ausgangslage — ohne sie prüfen die Tests darunter etwas anderes
# ---------------------------------------------------------------------------------------

def test_die_beiden_stehen_naeher_als_die_toleranz():
    d = bruegge.abstand_m(*FRS49, *FRS123)
    assert 100 < d < bruegge.PAARUNG_MIN_M, f"{d:.0f} m"


def test_bleibt_plausibel_sieht_den_fehler_NICHT():
    """Der Grund, warum es überhaupt schiefging: Die Plausibilitätsprüfung sagt brav ja."""
    fremder = _kandidat(1642160, "FRS123", *FRS123)
    assert bruegge.bleibt_plausibel(*FRS49, 10.0, 0.0, fremder) is True


def test_aus_der_mitte_hat_niemand_vorsprung():
    """Die Lage, in der der Server am 14.09. anderthalb Minuten lang gar nichts zuordnete."""
    treffer, grund = bruegge.zuordnen(*MITTE, 10.0, 0.0, _beide())
    assert treffer is None
    assert "ohne Vorsprung" in grund


# ---------------------------------------------------------------------------------------
# `belegt` — der eigentliche Fix
# ---------------------------------------------------------------------------------------

def test_belegte_cid_macht_die_lage_eindeutig():
    """Der Kern: Meldet einer der beiden schon selbst, bleibt der andere übrig.

    Ohne `belegt` ist dies exakt der Fall aus `test_aus_der_mitte_hat_niemand_vorsprung`
    (Treffer ist None) — der Test wird also rot, sobald die Sperre wegfällt.
    """
    treffer, grund = bruegge.zuordnen(*MITTE, 10.0, 0.0, _beide(), belegt={1602713})
    assert treffer is not None, "nach Abzug des Belegten bleibt genau einer"
    assert treffer.cid == 1642160
    assert "1 belegt" in grund, grund


def test_der_ausschluss_braucht_keinen_eigenen_zweig():
    """Was das Kniebrett als Schritt 3 führt, ist hier `len(passende) == 1`.

    Deshalb steht die Begründung auf „eindeutig" und nicht auf „Vorsprung": Es gibt nach
    dem Abzug schlicht keinen zweiten mehr, mit dem zu vergleichen wäre.
    """
    treffer, grund = bruegge.zuordnen(*MITTE, 10.0, 0.0, _beide(), belegt={1642160})
    assert treffer is not None and treffer.cid == 1602713
    assert grund.startswith("eindeutig"), grund


def test_belegt_kann_die_lage_auch_leerraeumen():
    """Sind alle Kandidaten vergeben, wird nicht geraten — der Aufrufer entscheidet weiter.

    `_bruegge_zuordnen` nimmt die Sperre danach einmal zurück (sonst sperrte sich ein Pilot
    nach dem Sim-Neustart mit seiner eigenen alten Kennung aus); dass hier zunächst nichts
    herauskommt, ist die Voraussetzung dafür, diesen Fall überhaupt zu erkennen.
    """
    treffer, grund = bruegge.zuordnen(*MITTE, 10.0, 0.0, _beide(),
                                      belegt={1602713, 1642160})
    assert treffer is None
    assert "2 belegt" in grund, grund


def test_ohne_belegt_bleibt_alles_wie_bisher():
    """Die Sperre ist rein additiv: Wer keine mitgibt, bekommt das alte Verhalten."""
    for leer in (None, set()):
        treffer, grund = bruegge.zuordnen(*FRS49, 10.0, 0.0, _beide(), belegt=leer)
        assert treffer is not None and treffer.cid == 1602713
        assert "belegt" not in grund, grund


def test_ein_belegter_nimmt_keinen_vorsprung_mehr_weg():
    """Der zweitbeste zählt nicht mehr mit, wenn er vergeben ist.

    Ohne die Sperre wäre FRS49 aus 20 m eindeutig (Vorsprung gegen 130 m). Interessant ist
    der umgekehrte Fall: Steht der Melder dicht bei FRS123, während FRS49 belegt ist, darf
    FRS49 die Rechnung gar nicht erst betreten.
    """
    dicht_bei_123 = (FRS123[0] + 0.0001, FRS123[1])
    treffer, grund = bruegge.zuordnen(*dicht_bei_123, 10.0, 0.0, _beide(), belegt={1602713})
    assert treffer is not None and treffer.cid == 1642160
    assert grund.startswith("eindeutig"), grund


def test_die_hoehe_zaehlt_weiterhin():
    """`belegt` ersetzt keine der bisherigen Schranken, es kommt vor sie."""
    hoch = [_kandidat(1602713, "FRS49", *FRS49, alt_ft=5000.0),
            _kandidat(1642160, "FRS123", *FRS123)]
    treffer, _ = bruegge.zuordnen(*FRS49, 10.0, 0.0, hoch, belegt={1642160})
    assert treffer is None, "FRS49 ist zu hoch, FRS123 belegt -- also niemand"


# ---------------------------------------------------------------------------------------
# Und die Regel, die NICHT zurückkommen darf
# ---------------------------------------------------------------------------------------

def test_deutlich_besser_ist_entfernt_und_bleibt_es():
    """Eine gemerkte Zuordnung wird geprüft, nicht neu ausgehandelt.

    Wer die Funktion wieder einführt, hebelt die harte Bindung aus, die das Kniebrett seit
    v13.2.0 trägt — und den Zweck von `belegt` gleich mit.
    """
    assert not hasattr(bruegge, "deutlich_besser"), (
        "deutlich_besser haengte Zuordnungen ohne Verstosszaehler um "
        "(572 m gegen 1175 m, 14.09.2026) -- s. Begruendung in app/bruegge.py"
    )
