"""Tests für den VR-Panel-Modus (/panel) — Web-Vorbereitung für ein separat gebautes
MSFS-2024-EFB-Panel (s. docs/superpowers/specs/2026-08-11-vr-panel-modus-design.md).

Für Vanilla-JS/CSS gibt es in diesem Projekt keinen Testläufer -- die Skalierungs-Tests
greifen deshalb wie tests/test_aircraft_ui_static.py auf den Quelltext zu.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import make_admin_token, make_confirm_token
from app.database import init_db

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

SECRET = "s3cr3t-key"
PW = "test-admin-pw"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    # Minimaler Zwilling des env-Fixtures aus tests/test_forum_sso_api.py — reicht hier, weil
    # wir nur Routing (/panel) + Gate brauchen, keinen vollen SSO-Roundtrip.
    p = str(tmp_path / "t.db")
    init_db(p)
    settings = SimpleNamespace(
        DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD=PW,
        SSO_SECRET="shared-forum-secret", FORUM_SSO_URL="https://board.friesenflieger.de/sso.php",
        FORUM_SSO_CALLBACK="https://friesenspy.devprops.de/auth/forum/callback",
        USER_SESSION_MAX_AGE_SEC=3600, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main._reset_gate_cache()
    client = TestClient(main.app)
    return SimpleNamespace(client=client, db=p, settings=settings)


def _admin_cookie() -> dict:
    return {
        "fs_admin": make_admin_token(SECRET, PW),
        "fs_confirm": make_confirm_token(SECRET, PW, 9_999_999_999),
    }


def test_panel_liefert_dieselbe_datei_wie_index():
    """/panel MUSS exakt dieselbe Response wie / liefern -- keine zweite HTML-Datei, keine
    Duplikation (s. Global Constraints). Mit aktuellem v= -- sonst liefert panel() den
    Cache-Bust-Redirect (s. test_panel_ohne_oder_mit_alter_version_leitet_um)."""
    index_resp = asyncio.run(main.index())
    panel_resp = asyncio.run(main.panel(v=main.VERSION))
    assert panel_resp.path == index_resp.path
    assert dict(panel_resp.headers) == dict(index_resp.headers)


def test_panel_ohne_oder_mit_alter_version_leitet_um():
    """Cache-Bust-Fix (Live-Test-Fund 13.08.2026): Coherent GT hat sich als unzuverlässig beim
    Befolgen von Cache-Control erwiesen -- /panel ohne oder mit veraltetem v= muss auf die
    aktuelle, garantiert noch nie angefragte, versionierte URL umleiten statt den (potenziell
    gecachten) Inhalt direkt auszuliefern."""
    resp_ohne = asyncio.run(main.panel(v=None))
    assert resp_ohne.status_code == 302
    assert resp_ohne.headers["location"] == f"/panel?v={main.VERSION}"

    resp_alt = asyncio.run(main.panel(v="0.0.1"))
    assert resp_alt.status_code == 302
    assert resp_alt.headers["location"] == f"/panel?v={main.VERSION}"


def test_vr_panel_klasse_wird_bei_panel_pfad_und_query_gesetzt():
    """Beide Aktivierungswege müssen im Quelltext stehen -- /panel (Task 1) UND ?vr=1
    (Design-Entscheidung: gleichwertiger Trigger auch ohne Pfadwechsel)."""
    assert "location.pathname === '/panel'" in INDEX
    assert "qs.get('vr') === '1'" in INDEX
    assert "classList.add('vr-panel')" in INDEX


def test_vr_panel_css_skaliert_alles_gemeinsam():
    """zoom (nicht nur font-size!) -- Innenabstände/Buttons sind im Rest der Seite
    überwiegend feste px-Werte, s. Design-Doku 'Warum eine reine Schriftgrößen-Anpassung
    nicht reicht'."""
    assert re.search(r"html\.vr-panel\s*\{[^}]*zoom:\s*1\.35", INDEX)
    assert re.search(r"html\.vr-panel body\s*\{[^}]*font-weight:\s*400", INDEX)


def test_panel_route_ist_wirklich_unter_slash_panel_registriert(env):
    """Echter Request über TestClient/Routing statt Direktaufruf von main.panel() -- ein
    Tippfehler im @app.get("/panel")-Pfad (den auch die JS-Erkennung in index.html prüft)
    würde hier auffallen, im alten Direktaufruf-Test dagegen nicht. Mit aktuellem v=, sonst
    Redirect statt 200 (s. Cache-Bust-Fix)."""
    r = env.client.get(f"/panel?v={main.VERSION}", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 200
    assert "vr-panel" in r.text  # dieselbe Seite wie /, samt VR-Erkennungs-Skript


def test_panel_route_leitet_ueber_echten_http_request_um(env):
    """Cache-Bust-Redirect auch über den echten Routing-Pfad (TestClient), nicht nur bei
    Direktaufruf von main.panel() -- deckt z. B. ab, dass FastAPI den v-Query-Parameter
    tatsächlich an die Handler-Signatur durchreicht."""
    r = env.client.get("/panel", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == f"/panel?v={main.VERSION}"


def test_panel_bleibt_hinter_dem_login_gate(env):
    """Design-Entscheidung 'kein öffentlicher Zugang' -- bei aktivem Gate muss /panel wie jede
    andere Seite zum Login umleiten. Eine künftige Erweiterung von _GATE_ALLOW_PREFIXES um
    "/panel" würde diesen Test brechen."""
    env.client.post("/api/admin/forum-login", json={"enabled": True}, cookies=_admin_cookie())
    main._reset_gate_cache()
    r = env.client.get("/panel", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("/auth/forum/login")
    assert loc == "/auth/forum/login?next=%2Fpanel"


# ---------------------------------------------------------------------------
#  Umschreibung deutscher Sonderzeichen im Panel (v11.11.0)
# ---------------------------------------------------------------------------
# Hintergrund: Coherent GT hat genau EINE eingebaute Schrift und nimmt nachweislich keine
# zweite an (gemessen ueber /api/panel-diag: document.fonts leer, neun Familien identisch
# breit, eine eingebettete data:-URI-Schrift kam vollstaendig an und wurde trotzdem nicht
# angewandt). Diese Schrift kann kein Zeichen ueber U+007F. Deshalb wird der Text
# umgeschrieben statt die Schrift repariert -- die Tests sichern das Verfahren, nicht die
# einzelne Zeichentabelle.


def test_panel_schreibt_deutsche_sonderzeichen_um():
    """ä/ö/ü/ß muessen auf ae/oe/ue/ss abgebildet sein -- sonst stehen im Tablet leere
    Kaesten statt Text."""
    for zeichen, ersatz in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        assert f"'{zeichen}': '{ersatz}'" in INDEX, f"{zeichen} fehlt in _TRANSLIT_MAP"


def test_umschreibung_haengt_an_einer_zentralen_stelle():
    """Die Umschreibung muss ueber den MutationObserver laufen, nicht in einzelnen Renderern.
    Text entsteht an weit ueber hundert Stellen; jede einzeln anzufassen hiesse, die naechste
    neue zwangslaeufig zu vergessen -- und der Fehler faellt erst im Sim auf."""
    assert "new MutationObserver" in INDEX
    assert "_translitBaum(e.addedNodes[i])" in INDEX
    assert "characterData: true" in INDEX


def test_umschreibung_nur_im_panel():
    """Die normale Webseite behaelt echte Umlaute -- die Umschreibung ist eine Kroete, die
    nur der Sim schlucken muss."""
    m = re.search(r"function _initPanelTranslit\(\) \{\n(.*?)\n\}", INDEX, re.S)
    assert m, "_initPanelTranslit nicht gefunden"
    assert "classList.contains('vr-panel')" in m.group(1).split("\n")[0] + m.group(1)


def test_umschreibung_schreibt_nur_bei_echter_aenderung():
    """Ohne diese Wache weckt der Beobachter sich endlos selbst: eine Zuweisung meldet auch
    dann eine Mutation, wenn sich der Wert nicht geaendert hat."""
    assert "if (neu !== knoten.nodeValue) knoten.nodeValue = neu;" in INDEX
    assert "td.getAttribute('data-label') !== heads[i]" in INDEX


# ---------------------------------------------------------------------------
#  Karten statt waagerechtem Scrollen (v11.11.0)
# ---------------------------------------------------------------------------
# Messung v11.10.1: Der Wrapper meldet korrekt canScroll=true (scrollWidth 501 gegen
# clientWidth 334) -- CSS und Layout stimmen also. Coherent GT zeichnet aber keine
# Scrollleiste, kennt kein Ziehen und hat kein Mausrad: die Spalten rechts vom Rand sind
# schlicht unerreichbar. Karten umgehen das, statt es zu bekaempfen.


def test_karten_layout_gilt_fuer_alle_breiten_tabellen():
    """Die erste Fassung fasste nur Live-Positionen und Events an und liess u. a. die
    Flugplaene stehen -- genau die Ansicht, die der Nutzer im Sim nicht bedienen konnte."""
    m = re.search(r"function _panelKartenLayout\(wurzel\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_panelKartenLayout nicht gefunden"
    rumpf = m.group(1)
    assert ".live-table-wrap, .table-scroll" in rumpf, "beide Wrapper-Klassen noetig"
    assert "kopfzellen.length < 3" in rumpf, "Zweispalter bleiben absichtlich Tabellen"


def test_karten_layout_wird_zentral_ausgeloest_nicht_je_renderer():
    """Regression: _panelLabelCells wurde von genau zwei Renderern aufgerufen. Jede neue
    Tabelle haette den Fix wieder verpasst."""
    assert "_panelLabelCells" not in INDEX, "alter Einzelaufruf-Weg lebt noch"
    assert "_panelKartenLayout(e.addedNodes[i])" in INDEX
    assert "_panelKartenLayout(document.body)" in INDEX


def test_sortierbare_kopfzeilen_ueberleben_das_karten_layout():
    """thead ist im Karten-Modus ausgeblendet -- bei sortierbaren Tabellen (Muster-Statistik,
    Rangliste) waeren damit die einzigen Sortier-Bedienelemente weg. Sie bleiben als Reihe
    antippbarer Schalter stehen."""
    assert "panel-cards-sortable" in INDEX
    assert "html.vr-panel .panel-cards-sortable thead { display: block; }" in INDEX
    assert "th.hasAttribute('onclick')" in INDEX


def test_karten_layout_nutzt_kein_flex_gap():
    """CSS.supports('gap','1px') ist in Coherent GT false (gemessen) -- ein Abstand ueber
    flex-gap faellt dort ersatzlos weg. Im Karten-Layout deshalb margin statt gap."""
    m = re.search(r"html\.vr-panel \.panel-cards tbody td \{(.*?)\}", INDEX, re.S)
    assert m, "Karten-Zellenregel nicht gefunden"
    assert "gap:" not in m.group(1)


def test_panel_initialisierung_wartet_auf_das_fertige_dokument():
    """Die festen Knoepfe stehen HINTER dem Inline-Skript. Ein direkter Aufruf fand per
    getElementById nur null -- _initPanelBackButton brach dann stumm an seiner eigenen Wache
    ab, und der Zurueck-Knopf blieb fuer immer versteckt."""
    assert "_initPanelBackButton();\n_initPanelTranslit();" not in INDEX
    m = re.search(r"document\.addEventListener\('DOMContentLoaded', \(\) => \{\n"
                  r"  _initPanelBackButton\(\);\n  _initPanelTranslit\(\);\n\}\);", INDEX)
    assert m, "Panel-Initialisierung haengt nicht an DOMContentLoaded"


def test_flugaktivitaets_grafik_im_panel_ausgeblendet():
    """Chart.js 4.x benutzt Class-Field-Syntax (ES2022), die Coherent GT nicht parst. Ein
    bestehendes try/catch faengt das ab -- uebrig bleibt ein leerer Kasten mit Ueberschrift."""
    assert "html.vr-panel #stats-activity-wrap { display: none; }" in INDEX


# ---------------------------------------------------------------------------
#  Eine Darstellung fuer alle Strecken-Zellen (v11.12.0)
# ---------------------------------------------------------------------------
# Nutzer-Frage 13.08.: "Wieso haben wir immer noch verschiedene Ansichten für Flugpläne??
# Macht doch gar keinen Sinn." -- zu Recht: dasselbe Abflug-Ziel-Paar wurde an vier Stellen
# unterschiedlich gebaut.


def test_streckenzellen_kommen_alle_aus_einer_funktion():
    """Vier Fassungen desselben Paares gab es vorher: fmtRoute (Live-Tabelle, reiner Text),
    zwei handgebaute Vorlagen (Flugplan-Tabelle, Flugliste) und fmtRouteHtml (nur im
    Karten-Popup). Nur letztere zeigte die Flugplatz-Karten-Symbole."""
    assert "function fmtRoute(" not in INDEX, "reine Textfassung lebt noch"
    # Kein handgebautes "DEP - ARR" mehr in den Renderern
    assert "${planDep ? escHtml(planDep) : '—'} - " not in INDEX
    assert "`${escHtml(p.departure)} - ${escHtml(p.arrival)}`" not in INDEX
    assert INDEX.count("fmtRouteHtml(") >= 6, "nicht alle Aufrufstellen umgestellt"


def test_streckenzelle_kann_sonderfaelle_ohne_zweite_fassung():
    """Die Flugliste braucht zwei Abweichungen (laufender Flug, beide Seiten leer). Sie
    gehoeren in die gemeinsame Funktion -- sonst entsteht die naechste Sonderfassung."""
    m = re.search(r"function fmtRouteHtml\(dep, arr, opts\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "fmtRouteHtml nicht gefunden"
    assert "o.arrHtml" in m.group(1)
    assert "o.leerHtml" in m.group(1)


def test_flugplan_spalte_heisst_ueberall_gleich():
    """Dieselbe Angabe hiess in der Flugliste 'Plan' und sonst 'Flugplan'."""
    assert "<th>Plan</th>" not in INDEX
    assert INDEX.count("<th>Flugplan</th>") >= 3


def test_flugplatz_symbol_haelt_abstand_ueber_css():
    """Im Panel ist das Symbol ausgeblendet -- ein Leerzeichen im Text bliebe sichtbar
    stehen ('EDDE  - EDDC')."""
    assert ".airport-link-icon { margin-left: 4px; }" in INDEX
    assert "return ' <a href=" not in INDEX


def test_karten_selbstdiagnose_meldet_nach():
    """Der Bericht beim Laden hilft bei Kartenfragen nicht -- die Karte entsteht erst beim
    Wechsel auf den Karten-Tab. Deshalb ein Nachtrag-Kanal."""
    assert "window._panelDiag = function (kind, data)" in INDEX
    assert "function _diagKarte(map, name, aipLayer)" in INDEX
    for karte in ["_diagKarte(liveMap, 'live'", "_diagKarte(trackMap, 'track'",
                  "_diagKarte(eventsMap, 'events'"]:
        assert karte in INDEX, f"{karte} nicht verdrahtet"
    # Die zwei offenen Fragen muessen tatsaechlich gemessen werden
    assert "aipAufKarte" in INDEX and "kachelStil" in INDEX


# ---------------------------------------------------------------------------
#  Keine Arbeit fuer verdeckte Ansichten (v11.13.x)
# ---------------------------------------------------------------------------
# Nutzer-Fund im Sim: im Events-Tab blitzten alle paar Sekunden die Kartenkacheln weg, im
# Karten-Tab dagegen nie -- und zusaetzlich, seltener und kuerzer, ein Aufblitzen IN der
# Karte. Zwei verschiedene Ursachen, beide unnoetige Arbeit.


def test_verdeckte_ansichten_werden_nicht_gezeichnet():
    """renderLiveTable und updateMap liefen auch dann, wenn ihre Ansicht verdeckt war --
    im Events-Tab also alle 10 UND alle 15 Sekunden umsonst."""
    assert "function _istSichtbar(el)" in INDEX
    m = re.search(r"function renderLiveTable\(pilots\) \{\n(.*?)\n\n", INDEX, re.S)
    assert m and "_istSichtbar(container)" in m.group(1)
    m2 = re.search(r"function updateMap\(pilots\) \{(.*?)\n\n", INDEX, re.S)
    assert m2 and "_istSichtbar(liveMap.getContainer())" in m2.group(1)


def test_marker_werden_nur_bei_kursaenderung_neu_gebaut():
    """setIcon ersetzt das DOM-Element des Markers komplett. In jedem Takt fuer jeden
    Flieger aufgerufen heisst: alle 10 bzw. 15 Sekunden die halbe Karte neu aufbauen."""
    assert "_fsHeading !== hdg" in INDEX
    assert "vorhanden._fsHeading = hdg;" in INDEX
    assert "marker._fsHeading = hdg;" in INDEX
    # Der alte, bedingungslose Aufruf darf nicht zurueckkehren
    assert ".setIcon(icon)" not in INDEX


def test_login_name_im_panel_ausgeblendet():
    """Im Tablet weiss man, wer man ist -- auf der Website ist der Name dagegen der einzige
    Hinweis darauf, als wer man angemeldet ist."""
    assert "html.vr-panel #userBox { display: none !important; }" in INDEX


def test_ebenen_haken_wird_selbst_gezeichnet():
    """Gemessen: hasLayer, gemerkter Wunsch und Kaestchen-Zustand stimmen alle drei ueberein
    -- der Zustand ist richtig, Coherent GT malt die eingebauten Haken nur nicht."""
    assert "html.vr-panel .leaflet-control-layers-selector {" in INDEX
    assert "html.vr-panel .leaflet-control-layers-selector:checked { background: var(--green); }" in INDEX


def test_versions_endpunkt_ist_schlank(env):
    """Die Neue-Version-Wache fragt im Minutentakt. /api/frontend-config haengt den
    kompletten Changelog an -- den im Minutentakt mitzuschleppen, nur um eine Nummer zu
    vergleichen, waere Verschwendung."""
    r = env.client.get("/api/version")
    assert r.status_code == 200
    assert set(r.json()) == {"version"}
    assert r.json()["version"] == main.VERSION


def test_wache_fragt_den_schlanken_endpunkt_und_im_minutentakt():
    """Beim Live-Test 13.08. erschien der Knopf nicht: visibilitychange/focus kommen in
    Coherent GT offenbar nie, und das Intervall stand auf fuenf Minuten."""
    m = re.search(r"function _startPanelUpdateWatch\(loadedVersion\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_startPanelUpdateWatch nicht gefunden"
    rumpf = m.group(1)
    assert "fetch('/api/version'" in rumpf
    assert "/api/frontend-config" not in rumpf
    assert "setInterval(check, 60 * 1000)" in rumpf


def test_kachel_einblendung_im_panel_abgeschaltet():
    """Leaflet laesst die Deckkraft frisch geladener Kacheln ueber requestAnimationFrame
    hochlaufen. Kommt die Schleife nicht ans Ziel, bleiben die Kacheln im DOM stehen und
    sind trotzdem unsichtbar -- genau das Bild aus dem Sim: keine Strukturaenderung, aber
    66 style-Aenderungen an geladenen Kacheln in 30 Sekunden, und Bewegen der Karte holt
    sie zurueck (Nutzer, in beiden Ansichten bestaetigt). Erklaert auch den aeltesten
    ungeklaerten Fund: Satellitenkacheln, die vollstaendig ankamen und nicht erschienen."""
    assert "const _KARTE_EINBLENDEN = !document.documentElement.classList.contains('vr-panel');" in INDEX
    # Alle drei Karten muessen die Option bekommen, sonst bleibt eine Ansicht kaputt
    assert INDEX.count("fadeAnimation: _KARTE_EINBLENDEN") == 3
