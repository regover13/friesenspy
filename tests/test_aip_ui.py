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
    """Seit dem Rueckbau (31.08.2026) liefert EIN Endpunkt beide Kartentypen; das Frontend
    filtert nach k.sorte. Der alte '/api/aip-charts' gibt es nicht mehr."""
    assert "'/api/aip-charts-dfs'" in INDEX


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


def test_eine_auswahlregel_fuer_beide_kartenarten():
    """Nutzerentscheidung 02.09.2026: was ins Bild ragt, davon die naechsten zur
    Kartenmitte, hoechstens N.

    Bis dahin mass diese Ebene das Verhaeltnis von Ausschnitt zu BLATT. Der Gedanke war
    richtig -- "sichtbar, wenn etwas mehr als das ganze Blatt im Bild ist" (24.08.2026) --,
    der Bezugspunkt aber unsichtbar: Die Blaetter streuen um den Faktor 7 (0,094 Grad bei
    279 von 446, 0,670 bei EDSB), dieselbe Marke erschien deshalb je nach Platz zwischen
    0,75 und 5,36 Grad Ausschnitt.
    """
    start = INDEX.index("function _aipMarkenAnpassen(")
    abschnitt = INDEX[start:start + 1200]
    assert "_markenAuswahl(_aipKarten" in abschnitt
    assert "_AIP_MARKE_SICHTBAR_FAKTOR" not in INDEX.replace(
        "_AIP_MARKE_FAKTOR = 2,0", ""), "die alte Schwelle darf nicht wieder auftauchen"


def test_der_deckel_haelt_die_zahl_der_marken_klein():
    """Ohne ihn stuenden auf der Deutschlandkarte 446 Marken -- und je Marke ein
    DOM-Element, das Leaflet bei jeder Kartenbewegung anfasst."""
    import re
    m = re.search(r"const _MARKEN_HOECHSTENS = (\d+)", INDEX)
    assert m and 5 <= int(m.group(1)) <= 40


def test_wer_schon_steht_bleibt_stehen():
    """Hysterese gegen Flackern: Bei Moving Map schiebt der Sekundentakt die Kartenmitte,
    die "naechsten 20" sind also eine Menge, die sich staendig neu bildet. Ohne Haltezone
    kaeme und ginge am Rand eine Marke im Sekundentakt."""
    import re
    hoechstens = int(re.search(r"const _MARKEN_HOECHSTENS = (\d+)", INDEX).group(1))
    halten = int(re.search(r"const _MARKEN_HALTEN_BIS = (\d+)", INDEX).group(1))
    assert halten > hoechstens
    start = INDEX.index("function _markenAuswahl(")
    block = INDEX[start:INDEX.index("\n}", start)]
    assert "vorhanden && vorhanden[e.s]" in block


def test_die_auswahl_sortiert_nach_abstand_zur_mitte():
    start = INDEX.index("function _markenAuswahl(")
    block = INDEX[start:INDEX.index("\n}", start)]
    assert "nah.sort(" in block
    # Laengengrade sind auf 53 Grad Nord nur rund 0,6 so lang wie Breitengrade -- ohne
    # diesen Faktor waere "am naechsten" nach Osten grosszuegiger als nach Norden.
    assert "Math.cos(mitte.lat" in block


def test_die_auswahl_prueft_die_blattgrenzen():
    """Nach dem BLATT, nicht nach dem Kartenfeld: So bleibt die Marke des Nachbarblatts
    erreichbar, solange sein Blatt ins Bild ragt -- und ein grosses Blatt verliert seine
    Marke nicht, sobald man in eine seiner Ecken hineinzoomt."""
    start = INDEX.index("function _markenAuswahl(")
    block = INDEX[start:INDEX.index("\n}", start)]
    assert "b.intersects([[k.sued, k.west], [k.nord, k.ost]])" in block


def test_beschriftet_wird_nach_der_zahl_der_marken():
    """Die zweite Stufe bleibt -- ein permanenter Tooltip je Marke ist die Falle vom
    15.08.2026. Nur ihr Massstab ist neu: die Zahl der Marken statt das Blattformat."""
    import re
    assert re.search(r"const _MARKEN_BESCHRIFTEN_BIS = (\d+)", INDEX)
    start = INDEX.index("function _aipMarkenAnpassen(")
    abschnitt = INDEX[start:start + 1200]
    assert "anzahl <= _MARKEN_BESCHRIFTEN_BIS" in abschnitt
    # Und die Verkleinerung muss es weiter geben, sonst ist der Teppich da.
    assert "transform: scale(0.6)" in INDEX
    assert ".leaflet-container.aip-nah .aip-marke svg { transform: scale(1); }" in INDEX


def test_beschriftung_bleibt_an_der_schwelle():
    """446 dauerhafte Tooltips auf der Deutschlandkarte sind die Falle vom 15.08.2026.

    Ein permanenter Tooltip ist ein DOM-Element, das Leaflet bei jeder Kartenbewegung neu
    setzt. Die Marke selbst ist billig, ihre Beschriftung nicht.
    """
    start = INDEX.index("function _aipMarkeBeschriften(")
    abschnitt = INDEX[start:start + 600]
    assert "bindTooltip" in abschnitt and "unbindTooltip" in abschnitt
    anpassen = INDEX.index("function _aipMarkenAnpassen(")
    assert "if (wechsel) _aipMarkeBeschriften(m, nah)" in INDEX[anpassen:anpassen + 3500]


def test_beschriftung_nur_beim_wechsel():
    """Sonst laeuft bei JEDER Kartenbewegung die Tooltip-Logik ueber alle Marken.

    Genau diese quadratische Arbeit kostete bei den FSE-Plaetzen 31.375 Layer-Besuche fuer
    250 Marker (Nutzer-Fund am laufenden Bild, 16.08.2026).
    """
    start = INDEX.index("function _aipMarkenAnpassen(")
    abschnitt = INDEX[start:start + 3500]
    assert "const wechsel = (_aipNah !== nah)" in abschnitt


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
# Admin -- Handpassung ist mit dem Rueckbau (31.08.2026) in die vereinigte Maske
# "AIP Charts DFS" aufgegangen. Siehe tests/test_charts_dfs_ui.py.
# ---------------------------------------------------------------------------
ADMIN = (Path(__file__).resolve().parents[1] / "app" / "static" / "admin.html").read_text(
    encoding="utf-8"
)


# ---------------------------------------------------------------------------
# Deckkraft-Regler
# ---------------------------------------------------------------------------
def test_regler_erscheint_nur_bei_liegendem_blatt():
    """Nutzer-Wahl 24.08.2026. Er haengt am gezeigten Blatt, NICHT an der Ebene.

    Ist die Ebene an, liegt aber gerade kein Blatt, gaebe es nichts zu regeln -- ein
    Dauerregler kostete im Cockpit Platz fuer etwas, das nichts tut.

    Seit dem 31.08.2026 zaehlt JEDES Blatt, nicht nur die Sichtflugkarte: Lag eine
    Flugplatzkarte allein, verschwand der Regler vorher ausgerechnet dann, wenn es etwas
    zu regeln gab.
    """
    start = INDEX.index("function _aipDeckkraftAnzeigen(")
    abschnitt = INDEX[start:start + 700]
    assert "!!_aipKarteAktiv || !!_groundAktiv" in abschnitt
    assert "classList.toggle('deckkraft-an', liegt)" in abschnitt
    # ... und beide Wege durch _aipKarteZeigen muessen ihn nachziehen, auch der frueh
    # abbrechende fuer "kein Blatt".
    zeigen = INDEX.index("function _aipKarteZeigen(")
    assert INDEX[zeigen:zeigen + 1200].count("_aipDeckkraftAnzeigen()") == 2


def test_regler_nutzt_kein_emoji():
    """Coherent GT hat keinen Emoji-Font-Fallback -- im Kniebrett waere es ein leeres Kaestchen.

    Derselbe Befund wie beim Gradzeichen der Windanzeige (v13.8.1). Seit dem 24.08.2026 traegt
    der Regler ueberhaupt kein Symbol mehr; die Regel gilt trotzdem weiter fuer alles, was
    dort spaeter hinzukaeme.
    """
    start = INDEX.index("function _addDeckkraftControl(")
    abschnitt = INDEX[start:start + 2500]
    assert "\U0001F5FA" not in abschnitt and "\U0001F4CC" not in abschnitt


def test_regler_steht_senkrecht():
    """Nutzer nach dem Kniebrett-Test 24.08.2026: schmal, senkrecht, in der Zoom-Spalte.

    Gedreht statt ``appearance: slider-vertical``: Diese Eigenschaft ist in Chromium ab 121
    entfernt, ihr Nachfolger ``writing-mode: vertical-*`` wirkt erst ab derselben Fassung.
    Welche Fassung in Coherent GT steckt, ist unbekannt -- ein Regler, der in einer der
    beiden Welten waagerecht liegen bleibt, ist im Cockpit unbrauchbar. Drehen koennen beide.
    """
    assert "rotate(-90deg)" in INDEX
    # An die DEKLARATION gebunden, nicht an das Wort: Der Kommentar im Stylesheet nennt
    # `appearance: slider-vertical` ausdruecklich, um zu begruenden, warum es NICHT benutzt
    # wird. Ein Test, der das Wort verbietet, schlaegt an der Begruendung an.
    assert "slider-vertical;" not in INDEX
    start = INDEX.index("function _addDeckkraftControl(")
    assert "deckkraft-schacht" in INDEX[start:start + 2500]


def test_regler_verschluckt_die_wischgeste():
    """Sonst zieht ein Wisch ueber den Regler die Karte mit -- im Kniebrett der Normalfall."""
    start = INDEX.index("function _addDeckkraftControl(")
    abschnitt = INDEX[start:start + 2500]
    assert "L.DomEvent.disableClickPropagation(box)" in abschnitt


def test_deckkraft_wird_ueber_den_server_gemerkt():
    """Im Kniebrett haelt kein Browser-Speicher einen Sim-Neustart aus (CLAUDE.md)."""
    assert "_prefSchreib(_AIP_KARTE_DECKKRAFT_KEY" in INDEX
    assert "_prefLies(_AIP_KARTE_DECKKRAFT_KEY)" in INDEX


def test_gemerkter_unsinn_faellt_auf_die_vorgabe():
    """Ein gespeicherter Wert von 0 machte das Blatt unsichtbar, einer von 5 die Karte darunter.

    Deshalb Bereichspruefung statt blossem isNaN -- und dieselben Grenzen wie am Regler.
    """
    start = INDEX.index("function _aipDeckkraftLesen(")
    abschnitt = INDEX[start:start + 600]
    assert "roh >= _AIP_KARTE_DECKKRAFT_MIN && roh <= 1" in abschnitt
    regler = INDEX.index("function _addDeckkraftControl(")
    assert "_deckkraftRegler.min = String(_AIP_KARTE_DECKKRAFT_MIN)" in INDEX[regler:regler + 2500]


def test_overlay_nimmt_den_eingestellten_wert():
    """Sonst zeigt der Regler etwas anderes an, als auf der Karte liegt."""
    start = INDEX.index("function _aipKarteZeigen(")
    abschnitt = INDEX[start:start + 1200]
    assert "opacity: _aipDeckkraft" in abschnitt
    assert "opacity: _AIP_KARTE_DECKKRAFT" not in abschnitt


# ---------------------------------------------------------------------------
# Marke als Schalter (Nutzerwunsch 24.08.2026)
# ---------------------------------------------------------------------------
def test_marke_schaltet_auch_ein_automatisch_gebrachtes_blatt_aus():
    """Am Platz blendet die Automatik ein -- man muss es trotzdem wegklicken koennen.

    Vorher nagelte ein Klick die Karte zusaetzlich fest, statt sie loszuwerden; am Platz war
    sie damit nicht abzuschalten.
    """
    start = INDEX.index("function _aipMarkeGeklickt(")
    abschnitt = INDEX[start:start + 700]
    assert "_aipKarteAktiv === icao" in abschnitt
    assert "_aipKarteAus = icao" in abschnitt
    assert "_aipKarteZeigen(null)" in abschnitt


def test_weggeklicktes_blatt_bleibt_aus_solange_die_automatik_es_will():
    """Sonst brächte der naechste Takt es sofort zurueck -- eine Sekunde spaeter."""
    start = INDEX.index("function _aipKarteNachfuehren(")
    abschnitt = INDEX[start:INDEX.index("\n}", start)]
    assert "treffer.icao === _aipKarteAus) treffer = null" in abschnitt


def test_sperre_faellt_beim_verlassen_des_platzes():
    """Ohne Zuruecksetzen muesste man jedes weggeklickte Blatt fuer immer von Hand einschalten."""
    # Bis zum Ende der Funktion statt einer festen Zeichenzahl -- ein Zusatz weiter oben
    # schoebe die Zeile sonst aus dem Fenster (derselbe Fehler wie bei _aipEingaben).
    start = INDEX.index("function _aipKarteNachfuehren(")
    abschnitt = INDEX[start:INDEX.index("\n}", start)]
    assert "!treffer || treffer.icao !== _aipKarteAus" in abschnitt
    assert "_aipKarteAus = null;" in abschnitt


def test_symbol_zeigt_liegt_gerade_nicht_festgenagelt():
    """Ein automatisch eingeblendetes Blatt sah sonst aus wie ein ausgeschaltetes."""
    start = INDEX.index("function _aipMarkenAnpassen(")
    assert "const fest = _aipKarteAktiv === icao" in INDEX[start:start + 3500]
    anstrich = INDEX.index("function _aipMarkenAnstrich(")
    assert "const an = _aipKarteAktiv === icao" in INDEX[anstrich:anstrich + 600]


def test_automatischer_wechsel_zieht_den_anstrich_nach():
    """Sonst bliebe das Symbol des vorigen Blatts gefuellt, obwohl ein anderes liegt."""
    start = INDEX.index("function _aipKarteZeigen(")
    abschnitt = INDEX[start:start + 1400]
    assert abschnitt.count("_aipMarkenAnstrich()") == 2


def test_ebenen_auswahl_ist_sichtbar_scrollbar():
    """Mit der Sichtflugkarte ist die Liste eine Zeile laenger und passt nicht mehr in die Karte.

    Leaflet begrenzt sie dann selbst und macht sie scrollbar -- aber Windows/Edge/Chrome
    blenden eine korrekt scrollende Box unsichtbar, wenn keine Scrollbar-Styles gesetzt sind.
    Im Kniebrett war der letzte Eintrag ("Radar Label") dadurch nicht mehr erreichbar
    (Nutzer-Bild 24.08.2026). Beide Teile sind noetig, einer allein reicht nicht -- derselbe
    Fund wie bei .scroll-list in CLAUDE.md.
    """
    assert "leaflet-control-layers-scrollbar::-webkit-scrollbar-thumb" in INDEX
    assert "scrollbar-color: rgba(45,156,219,0.7)" in INDEX
    assert "max-height: 60vh" in INDEX


def test_kartenliste_wird_beim_einschalten_aufgefrischt():
    """Sonst erscheint eine frisch gepasste Karte nie.

    Die Liste wird einmal beim Seitenaufbau geholt, und im Kniebrett laedt die Seite innerhalb
    einer Sim-Sitzung nicht neu (die EFB-App wird nur schlafen gelegt). Der Nutzer hat am
    24.08.2026 EDVM von Hand gepasst und es blieb aus -- in der Datenbank stand es laengst.
    """
    start = INDEX.index("function _addPreferredAipKarteLayer(")
    abschnitt = INDEX[start:start + 900]
    assert "_aipKartenLaden(true)" in abschnitt
    # Und der Zwischenspeicher muss weiter greifen, wenn NICHT erzwungen wird -- sonst holt
    # jeder Takt die Liste neu.
    laden = INDEX.index("function _aipKartenLaden(")
    assert "if (_aipKarten && !erzwingen) return" in INDEX[laden:laden + 400]


def test_frontend_frischt_auf_statt_neu_zu_laden():
    """Ein Neu-laden-Hinweis waere im Flug entweder unbrauchbar oder stoerend.

    Aufgefrischt wird nur, wenn die Liste ueberhaupt schon geholt wurde -- sonst zieht ein
    Admin-Klick auf JEDEM offenen Geraet einen Abruf nach sich.
    """
    start = INDEX.index("sseSource.onmessage")
    abschnitt = INDEX[start:start + 2200]
    assert "msg.type === 'aip_charts'" in abschnitt
    assert "if (_aipKarten) _aipKartenLaden(true)" in abschnitt
    assert "location.reload" not in abschnitt


def test_fadenkreuz_schluckt_den_klick_nicht():
    """Die Linien liegen ueber dem Bild -- ohne pointer-events:none faenge sie der Klick,
    den sie ausrichten sollen."""
    start = ADMIN.index(".aip-fadenkreuz {")
    assert "pointer-events: none" in ADMIN[start:start + 400]


def test_das_liegende_blatt_behaelt_seine_marke():
    """Sonst verliert es sie in dichten Gegenden an den Deckel -- und mit ihr den Anstrich,
    der zeigt, dass es liegt, und den Weg, es wieder wegzuklicken."""
    start = INDEX.index("function _markenAuswahl(")
    block = INDEX[start:INDEX.index("\n}", start)]
    assert "e.s === pflicht" in block
    anpassen = INDEX.index("function _aipMarkenAnpassen(")
    assert "_aipMarken, _aipKarteAktiv)" in INDEX[anpassen:anpassen + 600]
