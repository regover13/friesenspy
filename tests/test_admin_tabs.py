"""Die Admin-Oberfläche ist in Tabs gegliedert — geprüft am Quelltext.

`admin.html` hat im Test keine JS-Laufzeit. Geprüft wird deshalb an den Namen, die der
Code wirklich benutzt (`data-tab`, `id="tab-…"`, Funktionsnamen), nicht an Kommentaren.
Der Aufbau selbst wird mit einem Parser geprüft, nicht mit Textsuche: Ob ein Panel
INNERHALB eines Tab-Bereichs liegt, ist eine Frage der Verschachtelung, und die beantwortet
keine Zeichenkette.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ADMIN_PFAD = Path(__file__).resolve().parent.parent / "app" / "static" / "admin.html"
ADMIN = ADMIN_PFAD.read_text(encoding="utf-8")
SKRIPT = "\n".join(re.findall(r"<script>(.*?)</script>", ADMIN, re.S))

GRUPPEN = ["events", "stammdaten", "karten", "mitteilungen", "bruegge", "betrieb"]
#: Reihenfolge der Chips in der Typ-Leiste. Waechst mit jedem neuen Eventtyp --
#: "reddung" kam am 20.09.2026 dazu (FriesenReddung, #21).
TYPEN = ["bummel", "kutter", "reddung"]


def _rumpf(name: str) -> str:
    """Der Körper einer Funktion `name` — bis zur schließenden Klammer auf ihrer Ebene."""
    anfang = SKRIPT.index(f"function {name}(")
    auf = SKRIPT.index("{", anfang)
    tiefe = 0
    for i in range(auf, len(SKRIPT)):
        if SKRIPT[i] == "{":
            tiefe += 1
        elif SKRIPT[i] == "}":
            tiefe -= 1
            if tiefe == 0:
                return SKRIPT[auf: i + 1]
    raise AssertionError(f"Funktion {name} ist nicht geschlossen")


class _Baum(HTMLParser):
    """Sammelt für jedes Panel die Kette seiner Vorfahren-IDs und -Klassen."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stapel: list[tuple[str, dict[str, str]]] = []
        self.panels: list[tuple[str, list[str]]] = []
        self.leer = {"br", "hr", "img", "input", "meta", "link", "source", "use", "path"}

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag not in self.leer:
            self.stapel.append((tag, a))
        klassen = a.get("class", "").split()
        if "panel" in klassen or a.get("id") == "preview-panel":
            name = a.get("id") or klassen[0]
            vorfahren = [v.get("id", "") or v.get("class", "") for _, v in self.stapel[:-1]]
            self.panels.append((name, vorfahren))

    def handle_endtag(self, tag):
        if tag in self.leer:
            return
        for i in range(len(self.stapel) - 1, -1, -1):
            if self.stapel[i][0] == tag:
                del self.stapel[i:]
                return


def _baum() -> _Baum:
    p = _Baum()
    p.feed(ADMIN)
    return p


# --------------------------------------------------------------- Aufbau

def test_sechs_gruppen_stehen_in_der_leiste():
    gefunden = re.findall(r'class="tab-btn[^"]*" data-tab="([a-z]+)"', ADMIN)
    assert gefunden == GRUPPEN, f"Leiste weicht ab: {gefunden}"


def test_zu_jeder_gruppe_gehoert_genau_ein_bereich():
    for g in GRUPPEN:
        assert ADMIN.count(f'id="tab-{g}"') == 1, f"tab-{g} fehlt oder ist doppelt"
        stelle = ADMIN.index(f'id="tab-{g}"')
        umgebung = ADMIN[stelle - 120: stelle + 120]
        assert "tab-panel" in umgebung, f"tab-{g} traegt keine Klasse tab-panel"


def test_die_event_typen_haben_eine_eigene_leiste():
    gefunden = re.findall(r'class="typ-btn[^"]*" data-typ="([a-z]+)"', ADMIN)
    assert gefunden == TYPEN, f"Typ-Leiste weicht ab: {gefunden}"
    for t in TYPEN:
        assert ADMIN.count(f'id="typ-{t}"') == 1


def test_kein_panel_steht_ausserhalb_eines_tabs():
    """Ein Panel, das keinen Tab-Bereich ueber sich hat, ist auf keiner Seite erreichbar."""
    verwaist = [name for name, vorfahren in _baum().panels
                if not any("tab-" in v for v in vorfahren)]
    assert verwaist == [], f"Panels ohne Tab: {verwaist}"


def test_alle_panels_sind_noch_da():
    """Beim Umsortieren darf keines verlorengehen — 17 Panels plus die Wertungs-Vorschau.

    Die Zahl ist ein Bestandswaechter: Sie steigt, wenn jemand bewusst ein Panel ergaenzt (am
    20.09.2026 die FriesenReddung, von 17 auf 18), und faellt nur, wenn beim Umsortieren eines
    verlorengegangen ist. Genau deshalb steht hier eine Zahl und keine Untergrenze.
    """
    assert len(_baum().panels) == 18


# --------------------------------------------------- Laden erst beim Oeffnen

def test_showAdmin_laedt_keine_bereiche_mehr():
    rumpf = _rumpf("showAdmin")
    for lader in ("loadBanner", "loadForumLogin", "loadPilots", "loadKutterAdmin",
                  "loadCustomAirports", "loadAirportLinks", "loadDfsCharts", "miLoad"):
        assert f"{lader}(" not in rumpf, f"{lader} laeuft immer noch beim Anmelden"


def test_der_backfill_status_laeuft_weiter_beim_anmelden():
    """Ein im Hintergrund laufender Backfill muss sich zeigen, egal welcher Tab offen ist."""
    assert "_pollStatsimBackfillStatus()" in _rumpf("showAdmin")


def test_jede_gruppe_hat_einen_lader():
    rumpf = _rumpf("_tabLader")
    for g in GRUPPEN:
        assert f"{g}:" in rumpf, f"kein Lader fuer {g}"


def test_jeder_typ_hat_einen_lader():
    rumpf = _rumpf("_typLader")
    for t in TYPEN:
        assert f"{t}:" in rumpf


def test_ein_bereich_laedt_nur_beim_ersten_oeffnen():
    assert "_geladen" in SKRIPT
    rumpf = _rumpf("tabOeffnen")
    assert "_geladen" in rumpf


# ------------------------------------------------------- Die beiden Taktgeber

def test_die_taktgeber_haengen_am_tab_und_nicht_am_seitenaufruf():
    """Bruegge und Kniebrett fragten bisher im 10-Sekunden-Takt, auch auf der Anmeldeseite."""
    assert "setInterval(bgLaden" in _rumpf("bgStart")
    assert "setInterval(kbLaden" in _rumpf("kbStart")
    # und nirgends sonst
    assert SKRIPT.count("setInterval(bgLaden") == 1
    assert SKRIPT.count("setInterval(kbLaden") == 1


def test_der_takt_haelt_an_wenn_der_tab_weggeht():
    for stop in ("bgStop", "kbStop"):
        assert "clearInterval" in _rumpf(stop)


# ---------------------------------------------------------------- Deep-Link

def test_der_tab_steht_im_hash_und_uebersteht_ein_neuladen():
    assert "location.hash" in SKRIPT
    assert "replaceState" in SKRIPT


def test_eine_karte_wird_beim_zurueckkehren_neu_vermessen():
    """Leaflet misst 0 Pixel, solange der Bereich `display:none` ist."""
    assert "invalidateSize" in _rumpf("tabOeffnen")
