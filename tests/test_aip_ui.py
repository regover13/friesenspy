"""Karten-Ebene "Sichtflugkarte" im Quelltext.

Die Tests binden an Deklarationen und an die Funktion, die die Entscheidung trifft -- nicht
an das blosse Vorkommen einer Zeichenkette. Sonst bestuende ein Test auch dann, wenn der
Wert nur geloggt wird.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md
"""
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(
    encoding="utf-8"
)


def test_ebene_haengt_in_der_ebenen_auswahl():
    assert "liveOverlays['Sichtflugkarte']" in INDEX


def test_ebene_steht_direkt_hinter_openaip():
    """Nutzer-Wahl 24.08.2026: beides Luftfahrtkarten, sie gehoeren beieinander.

    Die Reihenfolge der Zuweisungen an ``liveOverlays`` IST die Reihenfolge in der Auswahl.
    """
    oa = INDEX.index("liveOverlays['OpenAIP']")
    sfk = INDEX.index("liveOverlays['Sichtflugkarte']")
    pr = INDEX.index("liveOverlays['Platzrunden']")
    assert oa < sfk < pr


def test_listenplatz_aendert_die_stapelung_nicht():
    """Der Listenplatz haengt an ``liveOverlays``, die Stapelung am addTo-Zeitpunkt.

    Beim Hochziehen in der Auswahl am 24.08.2026 blieb der addTo-Aufruf absichtlich stehen,
    damit sich auf der Karte nichts verschiebt. Was dort genau wen verdeckt, ist hier NICHT
    behauptet -- gemessen ist es nicht. Festgehalten ist nur, dass die Reihenfolge der
    Aufrufe dieselbe geblieben ist, und damit auch das Verhalten.
    """
    assert INDEX.index("_addPreferredFseLayer(liveMap") < INDEX.index("_addPreferredAipKarteLayer(liveMap")


def test_vorliebe_wird_vor_der_control_gesetzt():
    """Sonst sieht die Checkbox den Zustand nie (derselbe Fallstrick wie bei OpenAIP)."""
    assert INDEX.index("_addPreferredAipKarteLayer(liveMap") < INDEX.index("liveOverlays,")


def test_daten_kommen_vom_metadaten_endpunkt():
    assert "'/api/aip-charts'" in INDEX


def test_merker_laeuft_ueber_den_server_nicht_localstorage():
    """Im Kniebrett haelt kein Browser-Speicher ueber einen Sim-Neustart."""
    assert "_prefSchreib(_AIP_KARTE_PREF_KEY" in INDEX
    assert "localStorage.getItem('friesenspy_aipkarte')" not in INDEX


def test_geschaltet_wird_nach_dem_kartenfeld():
    """Nach den Blattgrenzen zu schalten hiesse: Overlay an, waehrend das Flugzeug noch unter
    der Kopfzeile steht -- das Blatt ist rund 1,8-mal so hoch wie das Kartenfeld."""
    start = INDEX.index("function _aipKarteImFeld(")
    block = INDEX[start:start + 900]
    for feld in ("feld_sued", "feld_nord", "feld_west", "feld_ost"):
        assert feld in block, feld
    assert "_AIP_KARTE_HYSTERESE" in block


def test_platziert_wird_nach_den_blattgrenzen():
    """Das Overlay selbst nimmt die BLATTgrenzen -- gezeigt wird ja das ganze Blatt."""
    start = INDEX.index("L.imageOverlay(")
    block = INDEX[start:start + 220]
    assert "k.sued" in block and "k.nord" in block
    assert "feld_" not in block


def test_hysterese_ist_vorhanden():
    assert "const _AIP_KARTE_HYSTERESE" in INDEX


def test_attribution_traegt_das_airac_datum():
    start = INDEX.index("function _aipKarteAttribution(")
    assert "airac" in INDEX[start:start + 300]


def test_nachfuehrung_haengt_im_navi_takt():
    """Dort wird die eigene Position ohnehin jede Sekunde ausgewertet."""
    start = INDEX.index("function _naviTakt(")
    assert "_aipKarteNachfuehren(" in INDEX[start:start + 4000]


def test_festnageln_ist_verdrahtet():
    """Nicht nur eine Variable anlegen -- sie muss die Automatik auch uebersteuern."""
    start = INDEX.index("function _aipKarteNachfuehren(")
    assert "_aipKarteFest" in INDEX[start:start + 1200]


def test_festnageln_ist_auch_ausloesbar():
    """Die Uebersteuerung muss jemand ANSTOSSEN koennen -- sonst ist sie unerreichbar.

    Genau das lag am 24.08.2026 vor: ``_aipKarteFestnageln`` war geschrieben, getestet war
    nur, dass ``_aipKarteNachfuehren`` sie beachtet -- aufgerufen hat sie niemand. Ohne
    Sim-Position blendet die Automatik alles aus, die Ebene war damit fuer jeden unbedienbar,
    der nicht gerade fliegt. Deshalb an den Aufruf gebunden, nicht an die Deklaration.
    """
    aufrufe = INDEX.count("_aipKarteFestnageln(")
    deklaration = INDEX.count("function _aipKarteFestnageln(")
    assert aufrufe - deklaration >= 1, "niemand ruft _aipKarteFestnageln auf"


def test_festnageln_haengt_nicht_an_einer_fremden_ebene():
    """Am 24.08.2026 sass die Handhabe im Popup der FSE-Plaetze -- vom Nutzer beanstandet.

    FSEconomy hat mit den DFS-Blaettern nichts zu tun; wer die Sichtflugkarte sehen wollte,
    musste eine sachfremde Ebene einschalten, um an den Knopf zu kommen. Die Ebene bringt
    ihre Handhabe jetzt selbst mit. Der Test bindet an ``_fsePopup``, damit der Rueckfall
    auffliegt, nicht an eine Beschriftung.
    """
    start = INDEX.index("function _fsePopup(")
    ende = INDEX.index("function _fsePlatzBauen(")
    assert "_aipKarte" not in INDEX[start:ende]


# ---------------------------------------------------------------------------
# Marken -- der eigene Zugriff der Ebene
# ---------------------------------------------------------------------------
def test_marken_haengen_in_der_ebene():
    """Sie muessen mit der Ebene kommen und gehen, sonst bleiben sie nach dem Abwaehlen stehen."""
    start = INDEX.index("function _aipMarkenAnpassen(")
    abschnitt = INDEX[start:start + 3000]
    assert "_aipKartenGruppe.addLayer(m)" in abschnitt
    assert "_aipKartenGruppe.removeLayer(" in abschnitt


def test_marken_schwelle_misst_die_engere_achse():
    """Nutzer-Wahl 24.08.2026: sichtbar, wenn etwas mehr als das ganze Blatt im Bild ist.

    ``Math.min`` und nicht ``Math.max``: An der engeren Achse entscheidet sich, ob das Blatt
    ins Fenster passt. Bei breitem Fenster und hochkantem Blatt zeigt die Waagerechte laengst
    zwei Blattbreiten, waehrend die Senkrechte gerade eine Blatthoehe fasst -- nach ``max``
    erschiene die Marke dort nie.
    """
    start = INDEX.index("function _aipMarkenAnpassen(")
    abschnitt = INDEX[start:start + 3000]
    assert "Math.min(sichtLat / blattLat, sichtLon / blattLon) > _AIP_MARKE_FAKTOR" in abschnitt


def test_marken_schwelle_laesst_das_ganze_blatt_zu():
    """Zoomstufen springen in Zweierschritten -- eine zu enge Schwelle ueberspringt die Stufe.

    Nachgerechnet an den drei Blattmassstaeben im Bestand: Die erreichbaren Verhaeltnisse
    liegen bei 0,86 / 1,72 / 3,44 (bzw. 1,13 / 2,26). Eine Schwelle unter 1,72 liesse die
    Marke erst erscheinen, wenn das Blatt schon ueber den Bildrand hinausragt; ab 3,44 waere
    sie auf der Deutschlandkarte zu sehen. Der zulaessige Bereich ist also eng.
    """
    import re
    m = re.search(r"_AIP_MARKE_FAKTOR = ([\d.]+)", INDEX)
    assert m, "Schwelle nicht gefunden"
    assert 1.72 < float(m.group(1)) < 3.44


def test_marke_sitzt_auf_der_feldmitte():
    """Nicht auf der Blattmitte: Die liegt wegen der Kopfzeile deutlich weiter noerdlich.

    Dieselbe Verwechslung von Blatt und Kartenfeld, die im Handpfad 45 Prozent Massstabsfehler
    gekostet haette.
    """
    start = INDEX.index("function _aipMarkenAnpassen(")
    abschnitt = INDEX[start:start + 3000]
    assert "(k.feld_nord + k.feld_sued) / 2" in abschnitt
    assert "(k.nord + k.sued) / 2" not in abschnitt


def test_marken_laufen_nicht_im_sekundentakt():
    """_naviTakt laeuft jede Sekunde. Die Marken haengen an zoomend/moveend, nicht dort."""
    start = INDEX.index("function _naviTakt(")
    assert "_aipMarkenAnpassen" not in INDEX[start:start + 4000]
    wache = INDEX.index("function _aipMarkenWache(")
    abschnitt = INDEX[wache:wache + 800]
    assert "'zoomend'" in abschnitt and "'moveend'" in abschnitt


def test_marke_wechselt_ihr_symbol_nur_bei_echter_aenderung():
    """setIcon ersetzt das DOM-Element und laesst den Marker aufblitzen (Verkehrs-Takt-Lehre)."""
    start = INDEX.index("function _aipMarkenAnpassen(")
    abschnitt = INDEX[start:start + 3000]
    assert "m._fsFest !== fest" in abschnitt


def test_festnageln_schaltet_die_ebene_mit_ein():
    """Bei ausgeschalteter Ebene steigt _aipKarteNachfuehren sofort aus -- der Klick verpuffte."""
    start = INDEX.index("function _aipKarteFestnageln(")
    abschnitt = INDEX[start:start + 1200]
    assert "hasLayer(_aipKartenGruppe)" in abschnitt and "addTo(liveMap)" in abschnitt


# ---------------------------------------------------------------------------
# Admin -- Handpassung
# ---------------------------------------------------------------------------
ADMIN = (Path(__file__).resolve().parents[1] / "app" / "static" / "admin.html").read_text(
    encoding="utf-8"
)


def test_admin_bindet_leaflet_ein():
    """Vorher enthielt admin.html keinerlei Leaflet -- kein Script-Tag, kein CSS."""
    assert "leaflet.js" in ADMIN and "leaflet.css" in ADMIN


def test_kartenliste_ist_horizontal_scrollbar():
    """UI-Regel aus CLAUDE.md: breite Tabellen gehoeren in .table-wrap."""
    start = ADMIN.index('id="aip-charts"')
    assert "table-wrap" in ADMIN[max(0, start - 400):start + 400]


def test_vorschau_zeigt_das_blatt_ueber_der_karte():
    start = ADMIN.index("aip-vorschau-btn').addEventListener")
    assert "L.imageOverlay(" in ADMIN[start:start + 1600]


def test_handpassung_schickt_die_rahmenecken_als_feld_werte():
    """Nicht als nord/sued/west/ost -- dieselben Namen fuer Rahmenecken und Blattgrenzen
    waren die Verwechslung hinter dem 45-Prozent-Massstabsfehler."""
    start = ADMIN.index("function _aipEingaben(")
    block = ADMIN[start:start + 1200]
    assert "feld_nord:" in block and "feld_sued:" in block
    assert "breite_px:" in block and "hoehe_px:" in block


def test_klickkoordinaten_werden_auf_bildpixel_zurueckgerechnet():
    """Das Blatt wird per max-width skaliert; ungerechnete Klickpixel waeren falsch."""
    start = ADMIN.index("aip-blatt').addEventListener")
    assert "naturalWidth" in ADMIN[start:start + 900]
