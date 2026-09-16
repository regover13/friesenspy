# -*- coding: utf-8 -*-
"""Die Brügge meldet den Titel ihres eigenen Flugzeugs (14.09.2026).

**Warum es diesen Weg überhaupt gibt:** Die Standardflugzeuge von MSFS 2024 sind
**gestreamt**. Im gesamten Paketbestand steht keine einzige `aircraft.cfg`; die Pakete
liegen als 256-kB-Platzhalter (`.fsarchive`) auf der Platte. Auch vPilots Modellscan half
nicht — 3823 Titel, davon **0** aus `Official`, alle aus Community-Paketen des jeweiligen
Piloten.

Der Titel existiert nur im laufenden Simulator. Genau dort läuft die Brügge.

**Und es ist die einzige Quelle, die ehrlich ist.** Am selben Tag wurden dreimal Objekte
gesetzt, die nur auf einem Rechner existierten (Black Square Bonanza, Superspuds Vieh,
Digital Aeronautics Mi-2) — der zweite Pilot bekam jedes Mal `EXCEPTION_22`. Dazu kam ein
Titel, der aus einer `aircraft.cfg` gelesen war und trotzdem nicht funktionierte.

⚠ **Am 16.09.2026 nachgemessen, und dabei hat sich die Erklärung geändert.** Hier stand,
MSFS verlange „den Livery-Titel, nicht den Kopfzeilen-Namen". Genauer ist: Setzbar ist eine
**wählbare Variante** — ein Preset oder eine vollständige Livery. Nicht setzbar ist der
Basiseintrag der Modular-Struktur (`common/config/aircraft.cfg`), den man nicht einmal
fliegen kann. Gemessen am fliegenden Simulator: `Mi-2 [passenger]` **und** der gemeldete
`Digital Aeronautics Mi-2 Hoplite - Czech Air Force` stehen beide; `Digital Aeronautics Mi-2
Hoplite` scheitert. Der Verzeichnislauf zieht diese Linie seitdem selbst
(`katalog_sammeln._ist_basiseintrag`, s. `tests/test_katalog_sammeln_flugzeuge.py`).
"""

import pytest

from tests.test_bruegge_endpunkt import (  # noqa: F401  (klient ist eine Fixture)
    klient, _meldung, _friese_anlegen,
)

TITEL = "Cessna 172 Skyhawk G1000 Asobo"


def _katalog(db_pfad, titel=TITEL, simulator="msfs2024"):
    from app.database import get_connection
    conn = get_connection(db_pfad)
    conn.row_factory = __import__("sqlite3").Row
    z = conn.execute(
        "SELECT * FROM bruegge_katalog WHERE titel = ? AND simulator = ?",
        (titel, simulator)).fetchone()
    conn.close()
    return dict(z) if z else None


def test_gemeldeter_titel_landet_im_katalog(klient, tmp_path):
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    r = klient.post("/api/bruegge/melden", json=_meldung(flugzeug=TITEL))
    assert r.status_code == 200
    z = _katalog(db)
    assert z is not None, "der gemeldete Titel muss im Katalog stehen"
    assert z["quelle"] == "gemeldet"
    assert z["kategorie"] == "Airplanes"


def test_ohne_zuordnung_wird_nichts_eingetragen(klient, tmp_path):
    """Kein Friese auf VATSIM → keine Zuordnung → auch kein Titel.

    Sonst könnte jeder den Katalog mit Erfundenem füllen, ohne je zu fliegen.
    """
    klient.post("/api/bruegge/melden", json=_meldung(flugzeug=TITEL))
    assert _katalog(str(tmp_path / "t.db")) is None


def test_der_titel_bekommt_KEIN_pruefergebnis(klient, tmp_path):
    """Dass jemand ein Flugzeug fliegt, heißt nicht, dass es sich SETZEN lässt.

    Die Mi-2 scheiterte am 14.09.2026 mit `EXCEPTION_22`, obwohl ihr Besitzer sie flog. Das
    Ergebnis darf erst aus einem echten Setzversuch kommen.
    """
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    klient.post("/api/bruegge/melden", json=_meldung(flugzeug=TITEL))
    z = _katalog(db)
    assert z["ergebnis"] is None
    assert z["geprueft_am"] is None


def test_ein_vorhandenes_pruefergebnis_wird_nicht_ueberschrieben(klient, tmp_path):
    """Was im Simulator geprüft wurde, ist teurer als das, was sich neu einlesen lässt."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    from app.database import get_connection, katalog_eintragen, katalog_ergebnis
    conn = get_connection(db)
    katalog_eintragen(conn, [{"simulator": "msfs2024", "titel": TITEL,
                              "quelle": "bord", "kategorie": "Airplanes"}])
    katalog_ergebnis(conn, "msfs2024", TITEL, "fehlgeschlagen", fehler="EXCEPTION_22")
    conn.commit()
    conn.close()

    klient.post("/api/bruegge/melden", json=_meldung(flugzeug=TITEL))
    z = _katalog(db)
    assert z["ergebnis"] == "fehlgeschlagen", "das Ergebnis muss stehen bleiben"
    assert z["fehler"] == "EXCEPTION_22"


def test_der_simulator_entscheidet_wo_der_titel_landet(klient, tmp_path):
    """Ein MSFS-Titel gehört nicht in den X-Plane-Bestand — dort sind es Dateipfade."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    klient.post("/api/bruegge/melden",
                json=_meldung(flugzeug=TITEL, simulator="msfs2020"))
    assert _katalog(db, simulator="msfs2020") is not None
    assert _katalog(db, simulator="msfs2024") is None


def test_leerer_oder_fehlender_titel_stoert_nicht(klient, tmp_path):
    """Eine Brügge der Fassung 1 schickt das Feld gar nicht."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    for nutzlast in (_meldung(), _meldung(flugzeug=""), _meldung(flugzeug="   ")):
        assert klient.post("/api/bruegge/melden", json=nutzlast).status_code == 200


def test_ein_ueberlanger_titel_wird_beschnitten(klient, tmp_path):
    """Der Titel kommt von außen — 256 Zeichen sind das Maß des Simulators, nicht unseres."""
    db = str(tmp_path / "t.db")
    _friese_anlegen(db)
    klient.post("/api/bruegge/melden", json=_meldung(flugzeug="A" * 500))
    z = _katalog(db, titel="A" * 200)
    assert z is not None, "auf 200 Zeichen beschnitten"
