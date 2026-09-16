# -*- coding: utf-8 -*-
"""Der Verzeichnislauf findet Flugzeugtitel — und lässt die untauglichen weg (16.09.2026).

**Der Lauf hat in diesem Projekt noch nie einen Flugzeugtitel geliefert.** `_alle_objekt_cfg`
suchte bis zum 16.09.2026 nur `sim.cfg`; Flugzeuge tragen ihren Titel in `aircraft.cfg`. Die
Gegenprobe am echten Bestand: `gotfriends-wilga` stand mit 19 Katalogzeilen da — Bienen,
Wohnwagen, Pfützen, ein Windsack —, aber ohne einen einzigen der zwölf `Wilga 80X: …`-Titel
aus seiner `aircraft.cfg`.

**Und der zweite Teil ist wichtiger als der erste:** Nicht jeder `title=` aus einer
`aircraft.cfg` lässt sich setzen. Am fliegenden Simulator gemessen (GitHub-Issue #40):

    presets/…/passenger/config/aircraft.cfg    "Mi-2 [passenger]"                   steht
    common/config/aircraft.cfg                 "Digital Aeronautics Mi-2 Hoplite"   EXCEPTION_22

Die Trennlinie ist an beiden Enden belegt — ein Name nur in `common` scheitert, ein Name in
`common` **und** als Preset steht (`A2A Piper PA-24-250 Comanche`). Beide Enden stehen hier
als Test, denn nur zusammen beschreiben sie die Regel.

Der Paketbaum wird nachgebaut statt gemockt: Der Bau hängt an Pfadbestandteilen
(`SimObjects`, `Community`, `common`), und die prüft man nicht gegen eine Attrappe.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "friesenbruegge"))
import katalog_sammeln as ks  # noqa: E402


def _cfg(pfad: Path, *titel: str) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    zeilen = ["[FLTSIM.0]"] + [f'title="{t}"' for t in titel]
    pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")


@pytest.fixture
def bestand(tmp_path):
    """Ein Community-Ordner nach dem Vorbild der echten Pakete vom 16.09.2026."""
    gem = tmp_path / "Community"

    # Mi-2: Basiseintrag in `common`, vier Varianten als Presets.
    mi2 = gem / "digitalaeronautics-mi2-v.1.2.0" / "SimObjects" / "Airplanes" / "mi_2"
    _cfg(mi2 / "common" / "config" / "aircraft.cfg", "Digital Aeronautics Mi-2 Hoplite")
    _cfg(mi2 / "presets" / "digitalaeronautics" / "passenger" / "config" / "aircraft.cfg",
         "Mi-2 [passenger]")
    _cfg(mi2 / "presets" / "digitalaeronautics" / "passenger-l-r-aux" / "config" / "aircraft.cfg",
         "Digital Aeronautics Mi-2 Hoplite - Czech Air Force")

    # A2A: derselbe String in `common` UND als Preset -- gemessen setzbar.
    a2a = gem / "a2a-aircraft-pa24" / "SimObjects" / "Airplanes" / "pa24-250"
    _cfg(a2a / "common" / "config" / "aircraft.cfg", "A2A Piper PA-24-250 Comanche")
    _cfg(a2a / "presets" / "a2a" / "PA24-250" / "config" / "aircraft.cfg",
         "A2A Piper PA-24-250 Comanche")

    # Ein Szenerieobjekt daneben: `sim.cfg` darf sich durch nichts davon ändern.
    _cfg(gem / "irgendwas-tiere" / "SimObjects" / "Animals" / "Seals" / "sim.cfg",
         "SealHarbor")
    return tmp_path


def _nach_titel(eintraege):
    return {e["titel"]: e for e in eintraege}


def test_flugzeugtitel_kommen_jetzt_mit(bestand):
    """Vorher: keine einzige Zeile aus einer `aircraft.cfg`."""
    eintraege, _ = ks.sammle_msfs(bestand, "msfs2024")
    titel = _nach_titel(eintraege)
    assert "Mi-2 [passenger]" in titel
    assert "Digital Aeronautics Mi-2 Hoplite - Czech Air Force" in titel


def test_die_szenerieobjekte_bleiben_unberuehrt(bestand):
    """`sim.cfg` war nie das Problem — und muss es auch nach dem Umbau nicht werden."""
    eintraege, _ = ks.sammle_msfs(bestand, "msfs2024")
    robbe = _nach_titel(eintraege)["SealHarbor"]
    assert robbe["kategorie"] == "Animals"
    assert robbe["paket"] == "irgendwas-tiere"
    assert robbe["quelle"] == "community"


def test_der_basiseintrag_bleibt_draussen(bestand):
    """`Digital Aeronautics Mi-2 Hoplite` scheiterte im Flug mit EXCEPTION_22."""
    eintraege, nur_basis = ks.sammle_msfs(bestand, "msfs2024")
    assert "Digital Aeronautics Mi-2 Hoplite" not in _nach_titel(eintraege)
    assert nur_basis == ["Digital Aeronautics Mi-2 Hoplite"], (
        "und er muss gemeldet werden — ein still weggelassener Titel sieht später aus wie "
        "ein Titel, den es nicht gibt")


def test_derselbe_name_auch_als_preset_zaehlt_als_setzbar(bestand):
    """Das andere Ende der Trennlinie: `common` schadet nicht, es genügt nur nicht.

    Beide A2A-Muster stehen im Simulator, obwohl ihr Name auch in `common` vorkommt. Wer
    hier auf „steht in common" filtert statt auf „steht NUR in common", wirft sie weg.
    """
    eintraege, nur_basis = ks.sammle_msfs(bestand, "msfs2024")
    assert "A2A Piper PA-24-250 Comanche" in _nach_titel(eintraege)
    assert "A2A Piper PA-24-250 Comanche" not in nur_basis


def test_die_reihenfolge_der_fundstellen_aendert_nichts(bestand, monkeypatch):
    """Die Preset-Datei kann vor ODER nach der common-Datei kommen — das Dateisystem
    entscheidet das, nicht wir. Ein Durchlauf, der beim ersten Treffer urteilt, wäre hier
    zufällig richtig oder falsch."""
    echt = ks._alle_objekt_cfg
    monkeypatch.setattr(ks, "_alle_objekt_cfg", lambda w: reversed(list(echt(w))))
    eintraege, nur_basis = ks.sammle_msfs(bestand, "msfs2024")
    assert "A2A Piper PA-24-250 Comanche" in _nach_titel(eintraege)
    assert nur_basis == ["Digital Aeronautics Mi-2 Hoplite"]


def test_mit_basis_nimmt_ihn_doch_mit_aber_markiert(bestand):
    eintraege, _ = ks.sammle_msfs(bestand, "msfs2024", mit_basis=True)
    z = _nach_titel(eintraege)["Digital Aeronautics Mi-2 Hoplite"]
    assert "nicht setzbar" in z["bemerkung"].lower()


def test_basiseintrag_gilt_nur_fuer_aircraft_cfg(tmp_path):
    """Ein Ordner `common` macht aus einem Szenerieobjekt keinen Basiseintrag."""
    _cfg(tmp_path / "Community" / "p" / "SimObjects" / "Misc" / "common" / "sim.cfg", "Kiste")
    eintraege, nur_basis = ks.sammle_msfs(tmp_path, "msfs2024")
    assert _nach_titel(eintraege).keys() == {"Kiste"}
    assert nur_basis == []
