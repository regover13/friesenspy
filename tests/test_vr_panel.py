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

# Die MSFS-App. Bewusst NICHT bedingungslos gelesen: Fehlt msfs-panel/ in irgendeiner
# Umgebung, braeche sonst das Sammeln der ganzen Datei ab, nicht nur der Panel-Tests.
_TSX_PFAD = (Path(__file__).resolve().parents[1] / "msfs-panel" / "PackageSources"
             / "FriesenSpy" / "src" / "FriesenSpy.tsx")
PANEL_TSX = _TSX_PFAD.read_text(encoding="utf-8") if _TSX_PFAD.exists() else ""
ohne_panel = pytest.mark.skipif(not _TSX_PFAD.exists(), reason="msfs-panel nicht vorhanden")

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
                  r"(?:  //.*\n)*"                     # erklaerende Kommentare erlaubt
                  r"  _initPanelBackButton\(\);\n  _initPanelTranslit\(\);\n"
                  r"(?:.*\n)*?\}\);", INDEX)
    assert m, "Panel-Initialisierung haengt nicht an DOMContentLoaded"
    # Alles Weitere, was Elemente aus dem Dokument braucht, gehoert in denselben Block --
    # sonst wiederholt sich der Fehler von damals mit der naechsten Init-Funktion.
    assert "_initPanelShellKanal();" in m.group(0)


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


def test_dauerlaufende_zierde_animationen_im_panel_aus():
    """.scanline animiert `top` (eine Layout-Eigenschaft!) auf einem position:fixed-Streifen
    ueber die ganze Breite mit z-index 9999, acht Sekunden im Dauerlauf. Jedes Einzelbild
    zwingt die ganze Seite zum Neuzeichnen -- im Sim als Stroboskop ueber der Karte sichtbar.
    Im Cockpit ist beides reine Zierde."""
    assert "html.vr-panel .scanline { display: none !important; }" in INDEX
    assert "html.vr-panel .sse-dot { animation: none !important; }" in INDEX


# ---------------------------------------------------------------------------
#  Fracht-Emoji als self-gehostetes SVG statt Roh-Zeichen (Folgefund zu v11.11.0)
# ---------------------------------------------------------------------------
# _translitText (s. oben) entfernt unbekannte Emoji-Zeichen im Panel inzwischen komplett --
# die Fracht-Emoji aus cargo_catalog.emoji verschwanden damit dort ganz. emojiChar() ersetzt
# das Roh-Zeichen durch ein Twemoji-SVG, dessen Dateiname sich rein aus dem Unicode-Codepoint
# ergibt (keine Zeichen->Name-Tabelle zu pflegen).


def test_frachtstellen_nutzen_emojichar_statt_rohes_kesc():
    """Vor dieser Umstellung gaben alle fuenf Stellen l.emoji/c.emoji roh (nur HTML-escaped)
    aus -- im Panel entweder ein leerer Kasten oder (seit v11.11.0) gar nichts. Keine Stelle
    darf mehr direkt _kesc(...emoji...) aufrufen."""
    assert re.search(r"_kesc\([^)]*emoji[^)]*\)", INDEX, re.I) is None
    # Alle fuenf bekannten Aufrufstellen (Live-Kutter, Kutter-Detail, zwei Legenden, Je-Abholplatz)
    assert INDEX.count("emojiChar(") >= 5


def test_emojidateiname_entfernt_variantenselektor_vor_codepoint_bildung():
    """U+FE0F steuert nur Text- vs. Emoji-Darstellung und steht bei mehreren Fracht-Emoji
    (Filmrollen, Sonnenschirm, Strandspielzeug) hinter dem eigentlichen Zeichen -- Twemoji
    fuehrt es im Dateinamen NICHT, ein vergessenes Entfernen liefe also immer auf 404."""
    m = re.search(r"function _emojiDateiname\(ch\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_emojiDateiname nicht gefunden"
    rumpf = m.group(1)
    assert "ohneVs" in rumpf
    # Surrogatpaar-Zusammenfassung darf nicht fehlen, sonst zerfallen Zeichen jenseits von
    # U+FFFF (z. B. 🦐, U+1F990) in zwei fuer sich bedeutungslose Haelften.
    assert "0xd800" in rumpf and "0xdc00" in rumpf
    assert "punkte.join('-')" in rumpf


def test_emojichar_faellt_bei_fehlender_datei_auf_rohzeichen_zurueck():
    """Kein hartes Scheitern, wenn zu einem (z. B. kuenftig neu angelegten) Fracht-Emoji noch
    keine SVG unter /static/emoji/ liegt: onerror ersetzt das <img> durch das Roh-Zeichen --
    exakt der Zustand vor dieser Umstellung, nie ein kaputtes Bild-Icon."""
    m = re.search(r"function emojiChar\(ch\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "emojiChar nicht gefunden"
    rumpf = m.group(1)
    assert "onerror=" in rumpf
    assert "data-fb" in rumpf
    assert "escHtml(ch)" in rumpf  # Roh-Zeichen muss escaped ins Attribut, sonst XSS-Luecke
    # outerHTML waere hier eine Luecke: getAttribute gibt den DEKODIERTEN Wert zurueck, die
    # Zuweisung parst ihn als HTML und hebt die Maskierung wieder auf. Der Fracht-Katalog
    # ist ueber die Verwaltung pflegbar -- also erreichbare Eingabe, kein Gedankenspiel.
    assert "this.outerHTML=" not in rumpf  # nur die ZUWEISUNG, das Wort steht im Kommentar
    assert "createTextNode" in rumpf


def test_alle_katalog_emoji_haben_eine_self_gehostete_svg():
    """Kein Zeichen aus dem tatsaechlichen Fracht-Katalog (Seed + Live-DB-Erweiterungen wie
    das generische Heringe-Symbol) darf beim Live-Test als leerer Kasten enden, weil die
    zugehoerige Twemoji-SVG schlicht fehlt."""
    from app.database import _CARGO_SEED

    emoji_dir = STATIC / "emoji"
    for name, em, _mx in _CARGO_SEED:
        # Python-Nachbau derselben Regel wie _emojiDateiname in JS: Variantenselektor raus,
        # verbleibende Codepoints klein-hex mit '-' verbunden. Python-Strings sind bereits
        # codepoint-basiert (kein Surrogatpaar-Zerfall wie in JS-UTF-16-Strings), deshalb
        # reicht hier ord(c) direkt.
        codepoints = [c for c in em if ord(c) != 0xFE0F]
        dateiname = "-".join(format(ord(c), "x") for c in codepoints)
        assert (emoji_dir / f"{dateiname}.svg").exists(), (
            f"SVG fuer '{name}' ({em!r} -> {dateiname}.svg) fehlt unter app/static/emoji/"
        )


def test_kein_zweiter_ausgang_aus_dem_vollbild_im_panel():
    """Die Zurueck-Leiste ist im Vollbild ohnehin sichtbar und ihr erster Druck verlaesst
    genau dieses Vollbild -- ein eigener Knopf dafuer ist einer zu viel und kostet Platz
    in der Karte. Der Knopf zum HINEINgehen bleibt."""
    assert "html.vr-panel .map-is-fullscreen .map-fullscreen-btn { display: none !important; }" in INDEX
    # Der zweite, eigene Notausgang unten rechts ist ganz entfallen: im Panel uebernimmt
    # die Zurueck-Leiste, auf der Website stand er als zweiter "Vollbild verlassen"-Knopf
    # neben dem ersten (Nutzer-Fund 14.08.2026).
    assert "global-map-exit-fs" not in INDEX
    # panelGoBack muss das Vollbild weiterhin als ERSTE Stufe verlassen, sonst gibt es
    # nach dem Ausblenden gar keinen Weg mehr heraus.
    m = re.search(r"function panelGoBack\(\) \{(.*?)\n\}", INDEX, re.S)
    assert m and "exitAnyMapFullscreen()" in m.group(1)


def test_leaflet_bedienelemente_liegen_nicht_unter_der_zurueck_leiste():
    """Zoom sitzt oben links, Ebenen oben rechts -- im Vollbild genau unter der Leiste am
    oberen Rand. Der Plus-Knopf war dadurch nicht erreichbar (Nutzer-Fund).

    Der Versatz MUSS der Leistenhoehe folgen: Seit die Leiste der Tablet-Statusleiste mit
    26px Innenabstand ausweicht, sind es 72px statt 46. Drei Stellen haengen an diesem Wert
    (body-Abstand, Karten-Bedienelemente, Hinweis-Stapel) -- laufen sie auseinander, schiebt
    sich wieder etwas unter die Leiste."""
    versatz = re.search(r"html\.vr-panel \.map-is-fullscreen \.leaflet-top \{ margin-top: (\d+)px; \}",
                        INDEX)
    assert versatz, "Versatz der Karten-Bedienelemente nicht gefunden"
    hoehe = re.search(r"html\.vr-panel body \{ padding-top: (\d+)px; \}", INDEX)
    assert hoehe, "Leistenhoehe (body padding-top) nicht gefunden"
    assert versatz.group(1) == hoehe.group(1), "Versatz und Leistenhoehe laufen auseinander"


# ---------------------------------------------------------------------------
#  Vereinheitlichte Kopf-/Tab-Leiste (v11.15.0)
# ---------------------------------------------------------------------------
# Nutzerwunsch 13.08.2026: "Tab-Navigation in den Balken mit zurueck einbauen, als
# Hintergrund dieser Leiste das FriesenSpy-Schriftzug". Kopfzeile + Tab-Reihe fraßen bis
# dahin durchgehend zwei Zeilen auf dem 790px hohen Tablet (gemessen mit Playwright:
# 57px Kopfzeile + 119.8px Tab-Reihe, weil "STATISTIKEN" bei 558px Fensterbreite in eine
# zweite Zeile umbrach) -- jetzt eine feste ~46px-Leiste.


def test_alte_kopfzeile_im_panel_komplett_ausgeblendet():
    """Die Kopfzeile (Logo/Hilfe/Login-Name/Uhr/Verbindungsanzeige) ist ueberfluessig, sobald
    Zurueck-Knopf und Tabs eine eigene feste Leiste haben -- sonst waere der Hoehengewinn
    nur auf dem Papier da."""
    assert "html.vr-panel header { display: none !important; }" in INDEX


def test_tab_leiste_ist_immer_sichtbar_und_bricht_nie_um():
    """Vorher stand die Tab-Reihe nur bei Bedarf (Zurueck-Balken) fest bzw. brach bei vier
    Tabs in zwei Zeilen um (s. Modul-Docstring) -- beides darf nicht zurueckkommen: die
    Leiste steht permanent (position:fixed) und nowrap erzwingt eine einzige Zeile."""
    m = re.search(r"html\.vr-panel \.panel-topbar \{([^}]*)\}", INDEX, re.S)
    assert m, "html.vr-panel .panel-topbar nicht gefunden"
    rumpf = m.group(1)
    assert "position: fixed;" in rumpf
    assert "flex-wrap: nowrap;" in rumpf
    # Mindesthoehe: nicht der exakte Wert zaehlt, sondern dass die Trefferflaeche fuer den
    # Finger reicht. Mit zoom 1.35 werden aus 38 CSS-Pixeln real ~51 -- ueber den 44, um die
    # es urspruenglich ging. Am 14.08.2026 von 44 auf 38 gesenkt, weil der Rest als Leerraum
    # ueber und unter den Beschriftungen stand (Nutzer-Foto).
    hoehe = re.search(r"min-height: (\d+)px;", rumpf)
    assert hoehe, "keine Mindesthoehe gesetzt"
    assert int(hoehe.group(1)) * 1.35 >= 44, "Trefferflaeche unter der Fingerregel"


def test_friesenspy_schriftzug_steht_oben_in_der_statusleiste():
    """Der Schriftzug lag urspruenglich als blasser Hintergrund HINTER den Beschriftungen und
    musste deshalb dezent bleiben. Seit 14.08.2026 steht er stattdessen OBEN auf Hoehe der
    Tablet-Statusleiste, deren Mitte frei ist (links deren Glocke, rechts Datum/Uhrzeit) --
    Nutzerwunsch mit Skizze. Dort liegt keine Beschriftung mehr darueber, also darf er
    kraeftig sein; der Streifen war ohnehin fuer den Abstand reserviert."""
    m = re.search(r"html\.vr-panel \.panel-topbar::before \{([^}]*)\}", INDEX, re.S)
    assert m, "Schriftzug-Pseudoelement nicht gefunden"
    rumpf = m.group(1)
    assert "content: 'FRIESENSPY';" in rumpf
    assert "top: 0;" in rumpf, "Schriftzug muss oben in der Statusleiste sitzen"
    assert "height: 26px;" in rumpf, "Schriftzug darf nicht in den Bereich der Tabs reichen"
    opazitaet = re.search(r"opacity:\s*([\d.]+);", rumpf)
    assert opazitaet and float(opazitaet.group(1)) >= 0.5, "im freien Streifen ruhig deutlich"


def test_panel_topbar_haengt_ausserhalb_von_app():
    """Kritischer Fund (Playwright, elementFromPoint ueber offenem Flugplan-Fenster): #app hat
    'position:relative; z-index:1' und kapselt damit einen eigenen Stapelkontext -- jeder
    Nachfahre darin landet beim Vergleich mit Elementen AUSSERHALB von #app hoechstens auf
    Rang 1, egal welchen z-index er selbst traegt. Haenge/wuerde die Leiste stattdessen die
    bestehende <nav class="tab-nav"> (die IN #app steckt) umbauen, verschwaende der
    Zurueck-Knopf hinter jedem Modal (z-index 10000) -- genau die Situation, die er loesen
    soll. #panel-topbar muss deshalb als eigenes Element NACH dem schliessenden </script>
    stehen, wie die anderen schwebenden Knoepfe davor (
    #panel-update-hint, #panel-back-btn) -- alle vier sind Geschwister von #app, nicht
    seine Nachfahren."""
    # rindex, nicht index: ganz am Dateianfang steht bereits ein winziges Inline-<script>
    # fuer die vr-panel-Erkennung (s. Kommentar dort), dessen </script> waere hier ein
    # falsch-positiver erster Treffer.
    script_ende = INDEX.rindex("</script>")
    topbar_stelle = INDEX.index('<div id="panel-topbar"')
    app_oeffnung = INDEX.index('<div id="app"')
    zurueck_knopf_stelle = INDEX.index('id="panel-back-btn"')
    assert topbar_stelle > script_ende, "#panel-topbar muss hinter dem Inline-Skript stehen"
    # #app oeffnet weit vor dem Skript-Ende (Kopfzeile/Tabs/Tab-Panels stehen alle darin) --
    # #panel-topbar dagegen erst danach, zusammen mit den uebrigen schwebenden Knoepfen.
    assert app_oeffnung < script_ende
    assert zurueck_knopf_stelle < topbar_stelle


def test_zurueck_knopf_tabs_und_glocke_wandern_per_js_in_die_topbar():
    """Verschieben statt Duplizieren: dieselben Elemente (gleiche ID/Klasse), keine zweite
    Wahrheit -- bestehende Klick-Handler (data-tab) und der SSE-Status-Updater laufen
    unveraendert weiter, weil es keine Kopien sind.

    Ganz rechts steht seit dem 14.08.2026 die GLOCKE statt der Verbindungsanzeige: Sie sagt
    ueber ihre Farbe dasselbe und ist zusaetzlich der Weg zu den Kategorie-Schaltern. Ein
    Punkt daneben, der nur den Zustand wiederholt, waere im Cockpit verschenkter Platz.
    #sse-badge bleibt in der ausgeblendeten Kopfzeile -- ausblenden statt entfernen, damit
    setSSEStatus unveraendert weiterschreiben kann."""
    m = re.search(r"function _initPanelBackButton\(\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_initPanelBackButton nicht gefunden"
    rumpf = m.group(1)
    assert "getElementById('panel-topbar')" in rumpf
    assert "topbar.appendChild(btn);" in rumpf
    assert "querySelectorAll('.tab-btn').forEach(" in rumpf
    assert "topbar.appendChild(t);" in rumpf
    assert "topbar.appendChild(glocke)" in rumpf
    assert "topbar.appendChild(sseBadge)" not in rumpf


def test_versteckt_knopf_gewinnt_gegen_die_flex_regel():
    """Regression, beim Bau selbst gefunden (Playwright-Messung: Knopf blieb trotz
    hidden=true 102x59px gross): eine allgemeine Flex-Regel fuer den Knopf IN der Leiste hat
    per CSS-Spezifitaet mehr Gewicht als das einfache '.panel-back-btn[hidden]' von vorher
    und ueberschrieb dessen 'display:none'. Der gezielte Override muss existieren."""
    assert "html.vr-panel .panel-topbar .panel-back-btn[hidden] { display: none; }" in INDEX


def test_back_button_logik_ohne_klassenschalter():
    """Seit die Leiste permanent steht, braucht es kein '.panel-has-back' mehr, das den
    Seiten-Abstand per Klasse umschaltet -- nur noch der Knopf selbst blendet sich ein/aus."""
    m = re.search(r"function _updatePanelBackBtn\(\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_updatePanelBackBtn nicht gefunden"
    rumpf = m.group(1)
    assert "classList.toggle('panel-has-back'" not in rumpf
    assert "btn.hidden = !_panelCanGoBack();" in rumpf
    # Die Klasse darf nirgends mehr GESETZT (JS) oder als CSS-Selektor benutzt werden --
    # Kommentare, die den alten Namen zur Einordnung noch nennen, sind kein Fund hier.
    assert "classList.toggle('panel-has-back'" not in INDEX
    assert "panel-has-back body" not in INDEX
    assert "html.vr-panel.panel-has-back" not in INDEX


def test_karten_zellen_ohne_flexbox():
    """Die Beschriftung muss NEBEN ihrem Wert stehen, nicht darueber -- und zwar in einer
    Engine, die Flexbox auf einem <td> nicht umsetzt.

    Live-Befund 14.08.2026 (drei Screenshots, gleiches Muster in Kutter-Feed UND
    Events-Flugliste): die Beschriftung von Zeile N stand auf derselben Zeile wie der Wert
    von Zeile N-1. Es sah aus wie ein Zellen-Versatz und war keiner -- die Werte waren
    vollstaendig da. Der Nutzer hat es mit einem Satz geklaert ("nur das Layout ist
    schlecht"), nachdem ich zweimal in der falschen Richtung gesucht hatte.

    float + overflow:hidden statt flex: CSS 2.1 statt CSS 3, und `overflow: hidden`
    schliesst den Float in seiner Zelle ein -- ohne das wandert die Beschriftung in die
    naechste Zeile hinein, was genau den beobachteten Versatz erzeugt."""
    m = re.search(r"html\.vr-panel \.panel-cards tbody td \{(.*?)\}", INDEX, re.S)
    assert m, "Karten-Zellenregel nicht gefunden"
    zelle = m.group(1)
    assert "display: flex" not in zelle, "Flexbox auf <td> -- in Coherent GT wirkungslos"
    assert "position: relative" in zelle, "Bezugsrahmen fuer die absolute Beschriftung"
    # Entscheidend: Der Platz der Beschriftung wird per padding RESERVIERT, statt die
    # Engine um Einrueckung zu bitten. Mit `float: left` hat sie den Text NICHT umflossen,
    # Beschriftung und Wert lagen uebereinander ("CALLSIGFRS61", v11.16.1/.2 im Sim).
    assert "5px 46%" in zelle or "5px 44%" in zelle, "linke Spalte nicht freigehalten"

    b = re.search(r"html\.vr-panel \.panel-cards tbody td::before \{(.*?)\}", INDEX, re.S)
    assert b, "Beschriftungsregel nicht gefunden"
    # Der Kern: ausserhalb des Flusses. Weder flex noch float haben gehalten -- beide
    # liessen die Beschriftung den Wert nach unten schieben. Was nicht im Fluss ist,
    # beeinflusst keine Zeilenumbrueche; das gilt unabhaengig von der Engine.
    assert "position: absolute" in b.group(1)
    assert "float:" not in b.group(1)
    assert "flex:" not in b.group(1)


def test_flugliste_fuellt_ihren_kasten_ohne_herauszuragen():
    """Zwei Anforderungen, die zusammen gelten muessen:

    `width:100%` MUSS bleiben -- ohne die Angabe fuellt der Kasten seinen Platz nicht aus
    und schrumpft auf Inhaltsbreite (im Sim gemessen: die Karte nahm nur noch die halbe
    Breite ein).

    `margin-left` daneben darf NICHT stehen -- ein Rand liegt ausserhalb der Box, das
    rechnet auch das globale box-sizing:border-box nicht weg. Beides zusammen ergab einen
    Kasten, der genau um den Rand breiter war als sein Platz und rechts herausschaute
    (Nutzer-Fund 14.08.2026). Die Einrueckung ist deshalb ersatzlos entfallen."""
    assert 'class="live-table-wrap" style="width:100%;"' in INDEX
    # Nur der STIL darf weg sein -- der Kommentar daneben nennt den alten Wert weiterhin,
    # damit ihn niemand versehentlich wieder einbaut.
    assert 'style="width:100%;margin-left:24px;"' not in INDEX


def test_kein_html_kommentar_in_erzeugtem_markup():
    """Ein HTML-Kommentar IM erzeugten Markup hat mit seinen Backticks den Template-String
    beendet -- SyntaxError, das GESAMTE Skript tot, Website und Panel weiss (v11.16.2 bis
    .4, live beim Nutzer). Erklaerungen gehoeren in den Code, nicht in die Zeichenkette,
    die der Code erzeugt. Zweiter Vorfall dieser Art an einem Tag: v11.5.3 schloss einen
    HTML-Kommentar mit `*/` statt `-->` und verschluckte 23 von 35 Icons."""
    m = re.search(r"function renderEventsResults.*?\n\}", INDEX, re.S)
    assert m, "renderEventsResults nicht gefunden"
    assert "<!--" not in m.group(0), "HTML-Kommentar in einem Template-String"


def test_hauptskript_ist_syntaktisch_heil():
    """Billigster moeglicher Schutz gegen genau den Ausfall von oben: Ein Template-String,
    der von einem Backtick im Inhalt beendet wird, hinterlaesst eine ungerade Zahl -- der
    Rest der Datei verrutscht dann in eine Zeichenkette. Kein Ersatz fuer einen Parser,
    aber es haette den Totalausfall gefangen."""
    m = re.search(r"\n<script>\n(.*)\n</script>", INDEX, re.S)
    assert m, "Hauptskript nicht gefunden"
    skript = m.group(1)
    assert skript.count("`") % 2 == 0, "ungerade Zahl an Backticks -- Template-String offen?"


# ---------------------------------------------------------------------------
# Sim-Benachrichtigungen (Kniebrett) — s. tests/test_sse_notify.py für die Server-Seite
# ---------------------------------------------------------------------------

def test_sse_client_kennt_den_notify_zweig():
    """Ohne diesen Zweig kaeme die Meldung zwar am Client an, wuerde aber verworfen."""
    m = re.search(r"sseSource\.onmessage = \(e\) => \{.*?\n  \};", INDEX, re.S)
    assert m, "SSE-Handler nicht gefunden"
    assert "msg.type === 'notify'" in m.group(0)
    assert "_panelBenachrichtigung(msg)" in m.group(0)


def test_benachrichtigung_ausserhalb_des_panels_ein_no_op():
    """Auf der normalen Web-Seite gibt es Web-Push -- eine zweite Anzeige waere doppelt."""
    m = re.search(r"function _panelBenachrichtigung\(msg\) \{\n(.*?)\n\}", INDEX, re.S)
    assert m, "_panelBenachrichtigung nicht gefunden"
    erste = m.group(1).strip().splitlines()[0]
    assert "vr-panel" in erste and "return" in erste


def test_meldungstext_wird_umgeschrieben():
    """Die EFB-Shell zeichnet den Text AUSSERHALB unseres iframes -- der MutationObserver,
    der sonst die Umlaute umschreibt, sieht ihn nie. Also muss der Text vorher durch."""
    m = re.search(r"function _panelMeldungstext\(s\) \{\n(.*?)\n\}", INDEX, re.S)
    assert m, "_panelMeldungstext nicht gefunden"
    assert "_translitText(" in m.group(1)
    # In _panelBenachrichtigung darf nichts UNaufbereitet weitergereicht werden.
    b = re.search(r"function _panelBenachrichtigung\(msg\) \{\n(.*?)\n\}", INDEX, re.S)
    assert "_panelMeldungstext(msg.title)" in b.group(1)
    assert "_panelMeldungstext(msg.body)" in b.group(1)


def test_kategorie_schalter_stehen_nur_im_panel():
    """Vier Schalter, Vorgabe an -- und nur im Panel sichtbar (auf der Web-Seite steuern die
    Web-Push-Abos, was ankommt)."""
    for art in ("online", "prefile", "ts", "events"):
        assert f'id="panel-notif-{art}"' in INDEX
    assert '<div id="panel-notif" hidden>' in INDEX
    m = re.search(r"function _showNotifPanelContent\(\) \{\n(.*?)\n\}", INDEX, re.S)
    assert m, "_showNotifPanelContent nicht gefunden"
    # Der Panel-Zweig muss VOR der Web-Push-Logik greifen -- sonst laeuft im Tablet erst die
    # Push-Erkennung durch und blendet den falschen Hinweis ein.
    vorspann = m.group(1).split("const isIOS")[0]
    assert "vr-panel" in vorspann and "_panelNotifyPanelAufbauen()" in vorspann


def test_web_push_teile_im_panel_ausgeblendet():
    """Sie haengen alle am Browser-Push, den es in Coherent GT nicht gibt."""
    for sel in ("#notif-enabled-row", "#notif-filter", "#notif-install-btn",
                "#notif-reset-btn", "#notif-ios-hint", "#notif-blocked-hint"):
        assert f"html.vr-panel {sel}" in INDEX
    # Die Glocke selbst wird jetzt gebraucht -- sie fuehrt zu den Kategorie-Schaltern.
    assert "html.vr-panel #notif-btn," not in INDEX


def test_handshake_mit_der_shell():
    """Dass postMessage existiert, sagt nichts darueber, ob es die iframe-Grenze ueberquert.
    Der ping/pong-Handshake macht genau das messbar."""
    m = re.search(r"function _initPanelShellKanal\(\) \{\n(.*?)\n\}\n", INDEX, re.S)
    assert m, "_initPanelShellKanal nicht gefunden"
    block = m.group(1)
    assert "art: 'ping'" in block
    assert "'friesenspy-shell'" in block and "'pong'" in block
    assert "window._panelDiag('shell'" in block


def test_ersatzanzeige_ohne_inset():
    """`inset` wird von Coherent GT still ignoriert -- ein fixed-Overlay waere unsichtbar und
    wuerde trotzdem alle Klicks schlucken (Live-Fund, s. docs/efb-panel-debugging.md)."""
    m = re.search(r"\.panel-hinweis-stapel \{\n(.*?)\n    \}", INDEX, re.S)
    assert m, ".panel-hinweis-stapel nicht gefunden"
    assert "inset" not in m.group(1)
    assert "position: fixed" in m.group(1)


def test_ersatzanzeige_haengt_an_der_zustellung_nicht_am_handshake():
    """Sim-Fund 14.08.2026: Die Shell beantwortete den Handshake (`pong`), im Tablet erschien
    trotzdem nichts -- und weil die Ersatzanzeige da schon abgeschaltet war, sah der Nutzer
    GAR nichts. Angenommen heisst nicht angezeigt: erst eine Bestaetigung fuer eine echte
    Meldung (`notify-ok`) darf den Ersatzweg stilllegen."""
    m = re.search(r"function _panelBenachrichtigung\(msg\) \{\n(.*?)\n\}", INDEX, re.S)
    assert m, "_panelBenachrichtigung nicht gefunden"
    assert "_panelShellZeigt !== true" in m.group(1), \
        "Ersatzanzeige haengt am Handshake statt an der Zustellbestaetigung"
    # Und die Bestaetigung muss auch entgegengenommen werden.
    assert "if (d.art === 'notify-ok') {" in INDEX


def test_jede_station_meldet_sich():
    """Ohne Sonde an jeder Station ist ein Ausfall nicht zu lokalisieren -- genau das hat den
    ersten Sim-Test gekostet. Server: zwei Log-Zeilen; Panel: ein Diagnose-Datensatz."""
    poller = (Path(__file__).resolve().parents[1] / "app" / "poller.py").read_text(encoding="utf-8")
    main_py = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "SSE-Abonnent(en)" in poller          # Meldung entstand, N Zuhoerer
    assert "SSE-Notify %s an cid=%s" in main_py  # geliefert oder verworfen
    assert "window._panelDiag('notify'" in INDEX # im iframe angekommen
    assert "'shell-fehler'" in INDEX             # Shell hat sie abgelehnt


def test_shell_bestaetigung_verlangt_einen_zaehlerstand():
    """Sim-Fund 14.08.2026, zweiter Anlauf: Die Shell meldete Erfolg, die Glocke stand auf 0.
    `addNotification` lief ohne Wurf -- nur in die falsche Verwaltung (efb-api ist in unser
    Bundle einkompiliert, die statische INSTANCE ist also NICHT die der Shell). Ein
    fehlerfreier Aufruf beweist daher nichts; erst der Ungelesen-Zaehler tut es."""
    assert "Number(d.ungelesen)" in INDEX
    assert "_panelShellZeigt = (n > 0);" in INDEX


def test_efb_app_nutzt_den_durchgereichten_verwalter():
    """Nur die von der Shell gelieferte Instanz rendert auch. getManager() legt eine zweite an,
    die niemand anzeigt -- genau der Fehler des ersten Versuchs."""
    tsx = (Path(__file__).resolve().parents[1] / "msfs-panel" / "PackageSources" / "FriesenSpy"
           / "src" / "FriesenSpy.tsx").read_text(encoding="utf-8")
    assert "this.props.notificationManager" in tsx
    assert "notificationManager={verwaltung}" in tsx, "View bekommt den Verwalter nicht"
    # Nur echte Aufrufe verbieten -- im Kommentar daneben MUSS der Name stehen bleiben, sonst
    # greift beim naechsten Mal wieder jemand zum scheinbar robusteren Singleton.
    code = "\n".join(z for z in tsx.splitlines() if not z.lstrip().startswith("//"))
    assert "NotificationManager.getManager(" not in code, "getManager liefert die falsche Instanz"
    assert "unseenNotificationsCount.get()" in tsx, "ohne Zaehler ist die Zustellung unbelegt"


def test_glocke_steht_in_der_panel_leiste():
    """Fund 14.08.2026: Die Kopfzeile ist im Panel ausgeblendet (`html.vr-panel header
    { display: none }`) -- die Glocke darin war damit unerreichbar, obwohl sie per JS
    eingeblendet wurde. Ein lokaler Test hatte das nicht gefangen, weil er den Knopf per
    JavaScript geklickt hat statt mit der Maus: die Funktion lief, das Element war unsichtbar.
    Sie muss deshalb wie Zurueck-Knopf und Tabs in die Panel-Leiste wandern."""
    m = re.search(r"function _initPanelBackButton\(\) \{\n(.*?)\n\}\n", INDEX, re.S)
    assert m, "_initPanelBackButton nicht gefunden"
    block = m.group(1)
    assert "getElementById('notif-btn')" in block
    assert "topbar.appendChild(glocke)" in block
    assert "html.vr-panel header { display: none !important; }" in INDEX  # der Grund


def test_glocke_zeigt_den_verbindungszustand():
    """Sie ersetzt in der Leiste den Punkt und muss dessen Aufgabe mituebernehmen: gelb =
    live, rot = getrennt. Gesetzt wird das NUR in setSSEStatus -- eine Quelle fuer den
    Zustand, egal wie viele Stellen ihn anzeigen."""
    m = re.search(r"function setSSEStatus\(status\) \{\n(.*?)\n\}", INDEX, re.S)
    assert m, "setSSEStatus nicht gefunden"
    assert "classList.toggle('sse-live', live)" in m.group(1)
    assert "html.vr-panel .panel-topbar #notif-btn.sse-live { color: var(--amber); }" in INDEX
    assert re.search(r"html\.vr-panel \.panel-topbar #notif-btn \{[^}]*color: var\(--red\)", INDEX)


def test_glocke_im_panel_ist_einfaerbbar_und_steht_fest_im_markup():
    """Die Twemoji-Grafik ist ein fertiges Bild und nimmt keine Farbe an. Im Panel muss
    deshalb das Sprite-Symbol stehen, das `currentColor` folgt.

    BEIDE Glocken stehen fest im Markup und werden per CSS umgeschaltet: Ein per innerHTML
    eingesetztes <svg> blieb in Coherent GT unsichtbar, obwohl dieselbe Sprite-Referenz im
    festen Markup einwandfrei rendert (Sim-Fund 14.08.2026). Wer das wieder auf JavaScript
    umstellt, macht die Glocke im Tablet erneut unsichtbar."""
    assert 'class="emoji-icon notif-glocke-web"' in INDEX
    assert "html.vr-panel .notif-glocke-panel { display: inline-block; }" in INDEX
    assert "html.vr-panel .notif-glocke-web { display: none; }" in INDEX
    assert "glocke.innerHTML" not in INDEX, "Glocke darf nicht per JavaScript erzeugt werden"
    # Der Pfad steht DIREKT im Knopf, nicht als Sprite-Verweis: die <use>-Fassung blieb im
    # Tablet unsichtbar, obwohl gemessen richtig platziert und dimensioniert (44x44 / 20x20).
    m = re.search(r'<svg class="icon notif-glocke-panel"(.*?)</svg>', INDEX, re.S)
    assert m, "Panel-Glocke nicht gefunden"
    assert "<path" in m.group(1), "Glocke ohne eigenen Pfad"
    assert "<use" not in m.group(1), "Sprite-Verweis -- im Tablet unsichtbar"


def test_kategorie_schalter_zeigen_ihren_zustand_als_text():
    """Sim-Fund 14.08.2026: <input type="checkbox"> zeigte im Tablet keinen Zustand an --
    angehakt und nicht angehakt sahen gleich aus, die Schalter waren unbrauchbar. Reiner
    ASCII-Text ist das Einzige, was diese Engine sicher zeichnet."""
    assert "panel-notif-kasten" in INDEX
    assert "'[X]' : '[ ]'" in INDEX
    m = re.search(r'<div id="panel-notif" hidden>(.*?)</div>', INDEX, re.S)
    assert m, "Panel-Schalter-Block nicht gefunden"
    assert 'type="checkbox"' not in m.group(1), "native Kontrollkaestchen im Panel"
    for art in ("online", "prefile", "ts", "events"):
        assert f'data-art="{art}"' in m.group(1)


def test_klick_auf_einen_schalter_schliesst_nicht_das_fenster():
    """Der document-Klick-Handler schliesst #notif-panel bei jedem Klick daneben -- ohne
    stopPropagation waere nach jedem Umschalten das Fenster zu."""
    m = re.search(r"function _panelNotifyPanelAufbauen\(\) \{\n(.*?)\n\}", INDEX, re.S)
    assert m, "_panelNotifyPanelAufbauen nicht gefunden"
    assert "e.stopPropagation();" in m.group(1)


def test_ersatzanzeige_wartet_auf_die_bestaetigung():
    """Sonst erscheint die erste Meldung jeder Sitzung doppelt: entschieden wird, bevor die
    Bestaetigung der Shell eintreffen kann. Der Weg ueber die iframe-Grenze dauert
    Millisekunden -- eine halbe Sekunde Warten reicht und behaelt den Ersatzweg fuer alle,
    die noch eine Huelle ohne Benachrichtigungen haben."""
    m = re.search(r"function _panelBenachrichtigung\(msg\) \{\n(.*?)\n\}", INDEX, re.S)
    assert m, "_panelBenachrichtigung nicht gefunden"
    block = m.group(1)
    assert "setTimeout(" in block and "500" in block
    assert "if (_panelShellZeigt !== true) _panelHinweisZeigen(titel, text);" in block


def test_panel_leiste_ist_englisch_beschriftet():
    """Kurze englische Namen NUR im Panel (die Website bleibt deutsch): Sie sind kuerzer, und
    der gewonnene Platz geht in groessere Schrift -- in VR war die Leiste schlecht zu lesen
    (Nutzer, 14.08.2026). Gemessen bei echter Tablet-Breite (413 CSS-Pixel): BACK 154,
    Tabs zusammen 214, Glocke 44 -- kein Ueberlauf."""
    assert "_PANEL_TAB_TEXT = { live: 'LIVE', karte: 'MAP', statistiken: 'STATS', events: 'EVENTS' }" in INDEX
    assert "_panelBeschriftung(btn, 'BACK')" in INDEX
    # Die Website behaelt ihre deutschen Beschriftungen.
    # Nur die Beschriftung festnageln, nicht das Symbol-Markup dazwischen -- sonst bricht der
    # Test bei jeder Aenderung an den Sprite-Verweisen (passiert beim xlink-Fix).
    assert re.search(r'data-tab="statistiken">.*?STATISTIKEN', INDEX), \
        "die Website muss ihre deutschen Tab-Beschriftungen behalten"
    assert 'Zur&uuml;ck</button>' in INDEX


def test_panel_leiste_ist_in_vr_lesbar_dimensioniert():
    """Die Ausgangswerte (Tabs 0.62rem, Zurueck 0.65rem) waren im Headset zu klein. Der
    Zurueck-Knopf bekommt zusaetzlich den Platz, den die Tabs uebriglassen -- er ist im
    Cockpit das haeufigste Ziel."""
    tabs = re.search(r"html\.vr-panel \.panel-topbar \.tab-btn \{(.*?)\}", INDEX, re.S)
    assert tabs and "font-size: 0.85rem" in tabs.group(1)
    assert "flex: 0 1 auto" in tabs.group(1), "Tabs duerfen den Platz nicht mehr aufteilen"
    zurueck = re.search(r"html\.vr-panel \.panel-topbar \.panel-back-btn \{(.*?)\}", INDEX, re.S)
    assert zurueck and "font-size: 0.95rem" in zurueck.group(1)
    assert "flex: 1 1 auto" in zurueck.group(1), "Zurueck-Knopf bekommt den Rest nicht"
    # Symbole in den Tabs entfallen -- sonst passen Symbol UND Text nicht mehr nebeneinander.
    assert "html.vr-panel .panel-topbar .tab-btn .icon { display: none; }" in INDEX


def test_glocke_bleibt_rechts_auch_ohne_zurueck_knopf():
    """Gemessen im Sim (748px Panel-Breite, kein Zurueck-Knopf sichtbar): Die Glocke stand bei
    x=220 mitten in der Leiste. Der Zurueck-Knopf traegt als Einziger die Breitenverteilung
    (flex:1 1 auto) -- ist er ausgeblendet, faellt sie weg. `margin-left:auto` haelt die
    Glocke unabhaengig davon am rechten Rand."""
    m = re.search(r"html\.vr-panel \.panel-topbar #notif-btn \{(.*?)\n    \}", INDEX, re.S)
    assert m, "Glocken-Regel in der Leiste nicht gefunden"
    assert "margin-left: auto;" in m.group(1)


def test_tabs_fuellen_die_leiste_wenn_kein_zurueck_knopf_da_ist():
    """Ohne Zurueck-Knopf traegt niemand mehr die Breitenverteilung -- dann sollen sich die
    vier Ansichten den Platz gleichmaessig teilen statt links zusammenzurutschen
    (Nutzerwunsch 14.08.2026). Ueber den Geschwister-Kombinator, weil der Knopf im Markup vor
    den Tabs steht: kein JavaScript noetig, der Zustand steht im hidden-Attribut."""
    assert "html.vr-panel .panel-topbar .panel-back-btn[hidden] ~ .tab-btn { flex: 1 1 0; }" in INDEX


def test_schriftzug_sitzt_zwischen_glocke_und_uhr_des_tablets():
    """Nicht ueber die volle Leistenbreite zentrieren: Links sitzt die Glocke der
    EFB-Oberflaeche, rechts Datum/Uhrzeit -- ueber die ganze Breite mittig landet der
    Schriftzug unter der Uhrzeit (Nutzer, 14.08.2026). Er wird deshalb auf den freien
    Streifen dazwischen eingegrenzt und DORT zentriert."""
    m = re.search(r"html\.vr-panel \.panel-topbar::before \{([^}]*)\}", INDEX, re.S)
    assert m, "Schriftzug-Pseudoelement nicht gefunden"
    rumpf = m.group(1)
    assert "left: 0;" not in rumpf and "right: 0;" not in rumpf, \
        "Schriftzug spannt ueber die ganze Leiste statt ueber den freien Streifen"
    assert re.search(r"left: \d+%;", rumpf), "kein linker Rand fuer den freien Streifen"
    assert re.search(r"right: \d+%;", rumpf), "kein rechter Rand fuer den freien Streifen"
    assert "justify-content: center;" in rumpf


def test_kartenflackern_mix_blend_mode_ist_im_panel_abgeschaltet():
    """Die Ursache des Kartenflackerns im Sim, von Asobo selbst bestaetigt: Leaflet 1.9.4
    setzt auf jede Kachel `mix-blend-mode: plus-lighter` (neu in 1.9.4, Leaflet PR #8891),
    und genau diese Regel zerlegt die Karte in MSFS 2024. Nur im Panel abschalten -- auf der
    Website erfuellt sie ihren Zweck (Naehte beim Einblenden), und dort flackert nichts."""
    m = re.search(r"html\.vr-panel \.leaflet-container img\.leaflet-tile \{([^}]*)\}", INDEX, re.S)
    assert m, "Gegenregel zu mix-blend-mode fehlt"
    assert "mix-blend-mode: unset !important;" in m.group(1), \
        "die Regel muss die Leaflet-eigene ueberschreiben -- ohne !important gewinnt sie nicht"


def test_deckkraft_messreihe_ist_vollstaendig_zurueckgebaut():
    """Die Messreihe an der Deckkraft war eine Sackgasse (alle fuenf Stufen flackerten). Sie
    darf keine Spur hinterlassen: Eine Karte mit Deckkraft unter 1 ist dauerhaft blass, und
    die Ursache lag ganz woanders."""
    m = re.search(r"function _makeTileLayers\(\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_makeTileLayers nicht gefunden"
    rumpf = m.group(1)
    assert "opacity" not in rumpf, "Basisebenen tragen immer noch eine gedrosselte Deckkraft"
    assert "className" not in rumpf, "Compositing-Versuch der Messreihe ist noch da"
    assert ".kachel-ebene" not in INDEX, "CSS der Messreihe ist noch da"


def test_aip_overlay_behaelt_seine_deckkraft():
    """Das Luftraum-Overlay hatte immer 0.8 und soll es behalten -- es liegt ueber der Karte
    und wuerde sie sonst zudecken. Die Zahl ist kein Ueberbleibsel der Flacker-Suche."""
    assert "const _AIP_DECKKRAFT = 0.8;" in INDEX
    assert "opacity: _AIP_DECKKRAFT," in INDEX


def test_zeichen_takt_ist_wieder_ausgebaut():
    """Die zwei Messkaesten "M" und "P" haben ihre Frage beantwortet (die Engine zeichnet
    gleichmaessig mit 22,5 Bildern/s -- das Flackern lag woanders) und sind wieder raus.

    Der Ausbau ist nicht bloss Kosmetik: Ihre requestAnimationFrame-Schleife hat in JEDEM
    Bild ein transform gesetzt und damit dauerhaft eine Neuzeichnung angestossen. Genau das
    hat das Flackern waehrend der Messung verstaerkt -- ein Messmittel, das sein eigenes
    Messobjekt veraendert, darf nicht liegenbleiben."""
    assert "_diagZeichnen" not in INDEX, "Takt-Funktion oder ihr Aufruf sind noch da"
    assert "panel-takt" not in INDEX, "CSS der Messkaesten ist noch da"


def test_jedes_use_hat_xlink_fallback():
    """Jeder Sprite-Verweis braucht BEIDE Attribute -- sonst ist im Kniebrett kein einziges
    Symbol zu sehen.

    Coherent GT meldet sich als "Chrome/49.0.2623 ... CoherentGT/2.0" (gemessener User-Agent
    aus panel_diag). Das SVG-2-Attribut `href` am <use>-Element kennt Chrome aber erst ab
    Version 50 (MDN browser-compat-data, svg.elements.use.href) -- eine Version zu spaet. Das
    alte `xlink:href` versteht jede Version, und sind beide gesetzt, gewinnt `href`; moderne
    Browser aendern sich also nicht.

    Der Fehler war lange unsichtbar, weil er wie ein Layout-Problem aussah: Der Knopf ist da,
    das <svg> hat seine Groesse, nur gezeichnet wird nichts. Deshalb prueft dieser Test die
    GANZE Datei und nicht einzelne Stellen -- ein einziges vergessenes `xlink:href` faellt im
    Browser nicht auf und im Tablet sofort."""
    ohne_fallback = re.findall(r'<use href="(#icon-[a-z0-9-]+)"(?![^>]*xlink:href)', INDEX)
    assert not ohne_fallback, (
        "Diese Verweise haben kein xlink:href und sind im Panel unsichtbar: "
        + ", ".join(sorted(set(ohne_fallback)))
    )
    # Auch der dynamische Weg ueber icon() -- er erzeugt die meisten Symbole der App.
    m = re.search(r"function icon\(name\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "icon() nicht gefunden"
    assert "xlink:href" in m.group(1), "icon() erzeugt Symbole ohne xlink:href-Fallback"


def test_jedes_referenzierte_symbol_ist_definiert():
    """Ein Verweis auf ein nicht vorhandenes <symbol> zeichnet nichts -- und faellt genauso
    wenig auf wie der xlink-Fehler oben. Deshalb hier mitgeprueft."""
    definiert = set(re.findall(r'<symbol id="(icon-[a-z0-9-]+)"', INDEX))
    referenziert = set(re.findall(r'<use href="#(icon-[a-z0-9-]+)"', INDEX))
    fehlend = referenziert - definiert
    assert not fehlend, f"referenziert, aber nirgends definiert: {sorted(fehlend)}"


def test_zoom_knoepfe_sind_gezeichnet_nicht_geschrieben():
    """Plus und Minus benutzen denselben waagerechten Balken -- das Plus hat nur einen
    zweiten dazu. Als Schriftzeichen war das nicht zu loesen: "+" und "-" sind in JEDER
    Schrift unterschiedlich gross, und der Nutzer sah genau das (Minus kleiner als Plus).
    Zusaetzlich malte Coherent GT Leaflets echtes Unicode-Minus (U+2212) gar nicht."""
    m = re.search(r"function _zoomSymbol\(mitSenkrechte\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_zoomSymbol nicht gefunden"
    rumpf = m.group(1)
    # EIN Balken, in beiden Knoepfen derselbe -- daran haengt die Gleichheit.
    assert rumpf.count("const balken") == 1
    assert "mitSenkrechte ? senkrecht" in rumpf
    assert "_fixLeafletZoomMinus" not in INDEX, "die alte Textzeichen-Fassung ist noch da"
    assert INDEX.count("_fixLeafletZoomIcons") >= 4, "nicht alle drei Karten benutzen die neue Fassung"


def test_karte_hat_kompass_und_moving_map():
    """Die beiden neuen Bedienelemente der Live-Karte, an der Position aus dem Vorbild:
    Kompass unter der Ebenen-Auswahl (topright), Moving Map unten rechts."""
    assert "function _addKompassControl(map)" in INDEX
    assert "function _addMovingMapControl(map)" in INDEX
    assert "_addKompassControl(liveMap);" in INDEX
    assert "_addMovingMapControl(liveMap);" in INDEX
    # Reihenfolge: Der Kompass muss NACH L.control.layers dazukommen, sonst sitzt er darueber.
    pos_layers = INDEX.index("L.control.layers(")
    pos_kompass = INDEX.index("_addKompassControl(liveMap);")
    assert pos_layers < pos_kompass, "der Kompass sitzt sonst ueber der Ebenen-Auswahl statt darunter"


def test_ziehen_schaltet_moving_map_ab_zoomen_nicht():
    """Wer die Karte von Hand verschiebt, will woanders hinschauen -- dann geht Moving Map
    aus (Nutzerwunsch). Zoomen zaehlt ausdruecklich NICHT: naeher herangehen heisst nicht,
    den eigenen Flieger aus den Augen verlieren zu wollen."""
    m = re.search(r"map\.on\('movestart', function \(\) \{(.*?)\n  \}\);", INDEX, re.S)
    assert m, "movestart-Verknuepfung fehlt"
    rumpf = m.group(1)
    assert "_movingMap = false" in rumpf
    # Zwei Ausnahmen sind Pflicht, sonst schaltet sich Moving Map selbst ab: das eigene
    # Nachfuehren (setView feuert movestart) und Zoomen (feuert es ebenfalls).
    assert "_naviSelbstBewegt" in rumpf, "das eigene Nachfuehren wuerde Moving Map abschalten"
    assert "_naviZoomt" in rumpf, "Zoomen wuerde Moving Map abschalten"
    # Der Merker muss um den setView-Aufruf herum stehen -- und ihn auch bei einem Fehler
    # wieder freigeben, sonst schaltet danach gar nichts mehr ab.
    t = re.search(r"_naviSelbstBewegt = true;(.*?)_naviSelbstBewegt = false;", INDEX, re.S)
    assert t and "setView" in t.group(1)
    assert "} finally {" in INDEX

    # Und die Ursache selbst: Beim Anfassen der Karte setzt das Nachfuehren aus. Ohne diese
    # Pause zieht der Sekundentakt die Karte waehrend des Ziehens zurueck, Leaflets
    # Mindestbewegung kommt nie zustande und es gibt gar kein movestart. Im Browser fiel das
    # zuerst nicht auf, weil ein maschineller Zug in Millisekunden durchlaeuft -- ein
    # menschlicher dauert Sekunden und kollidiert dabei mit der Nachfuehrung.
    assert "_naviPauseBis" in INDEX
    assert "Date.now() >= _naviPauseBis" in INDEX, "die Pause wird beim Nachfuehren nicht beachtet"
    # Die Bedienelemente liegen INNERHALB des Kartenbereichs -- ein Druck auf einen Knopf
    # darf die Nachfuehrung nicht pausieren, sonst zentriert die Karte nach dem Einschalten
    # erst mit 1,5 s Verzoegerung ("klick auf follow me scheint laenger zu dauern",
    # gemessen: 1500 ms vorher, 49 ms nachher).
    assert "ziel.closest('.leaflet-control')" in INDEX, \
        "ohne diese Ausnahme pausiert schon der Klick auf den Knopf die Nachfuehrung"
    for ereignis in ("pointerdown", "touchstart", "mousedown"):
        assert f"flaeche.addEventListener('{ereignis}', anfassen, true)" in INDEX, \
            f"{ereignis} fehlt -- welches im Sim ankommt, ist ungeprueft"
    # Drittes Argument als Boolean, nicht als Options-Objekt: Chrome 49 (das Panel) kennt
    # die Optionen-Form von addEventListener noch nicht.
    assert "anfassen, { passive" not in INDEX


def test_fortrechnung_faelscht_die_tracks_nicht():
    """Die aufgezeichneten Wege duerfen NUR echte VATSIM-Punkte enthalten. Fortgerechnete
    Positionen sind Schaetzungen -- landeten sie im Track, waere die Aufzeichnung erfunden.
    Deshalb bewegt der Takt ausschliesslich Marker."""
    m = re.search(r"function _naviTakt\(sofort\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_naviTakt nicht gefunden"
    rumpf = m.group(1)
    assert "liveTrackPoints" not in rumpf, "der Takt fasst die Track-Punkte an"
    assert "_drawLiveTrackLine" not in rumpf, "der Takt zeichnet Track-Linien neu"
    assert "setLatLng" in rumpf, "der Takt bewegt gar keine Marker"


def test_schaetzung_baut_nicht_auf_schaetzung_auf():
    """Fortgerechnet wird IMMER vom letzten echten VATSIM-Wert aus, nie vom zuletzt
    gezeichneten Punkt. Sonst summiert sich der Fehler mit jedem Takt auf."""
    assert "const _positionsRoh = {}" in INDEX
    m = re.search(r"function _jetztGerechnet\(roh\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_jetztGerechnet nicht gefunden"
    # Der Zeitbezug ist der EMPFANGSZEITPUNKT des Rohwerts, nicht der letzte Takt.
    assert "Date.now() - roh.ts" in m.group(1)


def test_drehung_nur_mit_geprueftem_plugin():
    """leaflet-rotate erweitert den Leaflet-Kern. Faellt es aus (Netz, Hash, Engine), muss
    die Karte unveraendert weiterlaufen -- ohne Track-up, aber ohne Fehler."""
    assert 'onerror="window._leafletRotateFehlt = true;"' in INDEX
    assert "leaflet-rotate@0.2.8" in INDEX
    assert "integrity=\"sha256-+Qs8D9zbGHhw1CGR1C/Ty+hiG/oYv998Rs2DntIXIrY=\"" in INDEX
    m = re.search(r"function _kannDrehen\(map\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_kannDrehen nicht gefunden"
    assert "_leafletRotateFehlt" in m.group(1)
    assert "typeof map.setBearing === 'function'" in m.group(1)
    # Gedreht wird ausschliesslich per Knopf -- eine im Cockpit versehentlich verdrehte
    # Karte ist schlimmer als eine, die sich nicht drehen laesst.
    assert "touchRotate: false" in INDEX
    assert "shiftKeyRotate: false" in INDEX


def test_moving_map_an_ist_auch_sichtbar():
    """Der An-Zustand muss sich SEHEN lassen, nicht nur im DOM stehen.

    Die Grundfarbe des Knopfes traegt !important (noetig gegen Leaflets Stylesheet) -- die
    An-Regel aber nicht. Damit gewann immer die Grundfarbe: Der Knopf blieb dunkel, egal ob
    Moving Map an oder aus war. Von aussen sah es aus, als wuerde das Abschalten nicht
    funktionieren; die Messung aus dem Sim zeigte das Gegenteil (abgeschaltet 1,
    movingMapJetzt false -- bei unveraendertem Aussehen).

    Und der Grund, warum das so lange durchging: Meine eigenen Browser-Tests haben die
    CSS-KLASSE geprueft. Eine gesetzte Klasse ist kein Beleg dafuer, dass man etwas sieht."""
    m = re.search(r"\.navi-bar\.navi-an \.navi-knopf \{([^}]*)\}", INDEX, re.S)
    assert m, "An-Zustand des Moving-Map-Knopfes nicht gefunden"
    regel = m.group(1)
    assert "background: #2d9cdb !important" in regel, \
        "ohne !important gewinnt die Grundfarbe und der Knopf sieht an wie aus aus"
    # Gegenprobe: Die Grundfarbe traegt es tatsaechlich -- sonst waere das obige unnoetig.
    g = re.search(r"\.navi-bar \.navi-knopf \{([^}]*)\}", INDEX, re.S)
    assert g and "background: #071525 !important" in g.group(1)


def test_kartenknoepfe_sehen_gleich_aus():
    """Alle Bedienelemente der Karte gehoeren ins selbe Bild.

    Die Ebenen-Auswahl ist das einzige, das Leaflet selbst zeichnet -- und kam als weisser
    Kasten mit schwarzem Symbol zwischen unseren dunklen Knoepfen daher. Das Symbol ist
    deshalb ein eingebettetes SVG in der Akzentfarbe: Ein PNG liesse sich nur invertieren
    (ergibt weiss, nicht blau) und waere auf dem Tablet ausserdem unscharf."""
    m = re.search(r"\.leaflet-control-layers \{([^}]*)\}", INDEX, re.S)
    assert m and "#071525" in m.group(1), "die Ebenen-Auswahl traegt nicht den dunklen Grund"
    t = re.search(r"\.leaflet-control-layers-toggle \{([^}]*)\}", INDEX, re.S)
    assert t, "Ebenen-Symbol nicht gefunden"
    assert "data:image/svg+xml" in t.group(1), "Leaflets PNG-Symbol ist noch da"
    assert "%232d9cdb" in t.group(1), "das Symbol traegt nicht die Akzentfarbe"
    assert "44px !important" in t.group(1), "die Ebenen-Auswahl ist kleiner als die anderen Knoepfe"


def test_kompass_zeigt_seinen_zustand_wie_der_pfeil():
    """Track-up an sieht aus wie Moving Map an -- zwei Schalter direkt uebereinander, die
    ihren Zustand verschieden anzeigen, waeren im Cockpit eine unnoetige Denkaufgabe.

    Dabei muss die helle Suedhaelfte der Nadel dunkel werden: auf dem blauen Grund des
    eingeschalteten Zustands waere sie sonst hell auf hell."""
    m = re.search(r"function _naviKnopfAnstrich\(\) \{(.*?)\n\}", INDEX, re.S)
    assert m and "box.classList.toggle('navi-an', !!_trackUp" in m.group(1), \
        "der Kompass zeigt seinen Zustand nicht an"
    assert re.search(r"\.navi-bar\.navi-an \.kompass-sued \{[^}]*fill:", INDEX), \
        "die Nadel-Suedhaelfte bleibt hell auf hell"
    assert 'class="kompass-sued"' in INDEX


def test_flugzeuge_drehen_mit_der_karte():
    """Bei Track-up MUSS das Flugzeugsymbol mitdrehen -- seine Richtung ist die Aussage.

    Das Dreh-Plugin haelt Marker standardmaessig aufrecht (rotateWithView: false), damit
    Beschriftungen lesbar bleiben. Fuer Flugzeuge ist das genau verkehrt: Gemessen zeigte
    das Symbol bei um 270 Grad gedrehter Karte exakt denselben Winkel wie vorher, also in
    die falsche Richtung (Nutzer-Fund 15.08.2026).

    Die Alternative waere gewesen, bei jeder Kursaenderung jedes Symbol neu zu zeichnen --
    bei Track-up dreht sich die Karte staendig mit, das haette die halbe Karte dauernd in
    Bewegung gehalten (und genau davor warnt der Kommentar an setIcon in updateMap)."""
    assert INDEX.count("rotateWithView: true") == 3, \
        "alle drei Marker-Arten (VATSIM, Sim, Fremdverkehr) brauchen die Option"
    for stelle in ("icon: makeAircraftIcon(hdg), rotateWithView: true",):
        assert stelle in INDEX


def test_eigenes_flugzeug_auch_ohne_vatsim():
    """Ohne VATSIM gibt es keinen Eintrag in liveData -- und damit war ueberhaupt kein
    eigenes Flugzeug auf der Karte, obwohl die Sim-Position vorlag und die Karte korrekt
    darauf zentrierte (Nutzer-Fund 15.08.2026: "Offline wird das Flugzeug nicht angezeigt.
    aber es wird richtig zentriert").

    Der Simulator bekommt deshalb einen eigenen Marker -- der aber verschwinden MUSS, sobald
    der VATSIM-Marker da ist, sonst steht man doppelt auf der Karte. Und ebenso, wenn die
    Sim-Position veraltet: ein Flugzeug an einer Stelle, an der laengst niemand mehr ist,
    waere schlimmer als keins."""
    m = re.search(r"function _eigenesFlugzeugZeichnen\(\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_eigenesFlugzeugZeichnen nicht gefunden"
    rumpf = m.group(1)
    assert "if (!_simPosFrisch())" in rumpf, "veraltete Position wird nicht abgeraeumt"
    assert rumpf.count("removeLayer(_eigenerSimMarker)") >= 2, \
        "der Eigenbau-Marker wird nicht in BEIDEN Faellen entfernt (veraltet / VATSIM da)"
    assert "if (vatsimMarker) {" in rumpf, "der Online-Fall fehlt -- man staende doppelt da"
    # Aufgerufen wird er aus dem Takt, nicht aus updateMap (dort gilt: nur eine Stelle bewegt).
    t = re.search(r"function _naviTakt\(sofort\) \{(.*?)\n\}", INDEX, re.S)
    assert t and "_eigenesFlugzeugZeichnen();" in t.group(1)


def test_moving_map_zustand_ist_wirklich_zu_sehen():
    """Der An-Zustand braucht !important -- sonst sieht man ihn nicht.

    Die Grundfarbe des Knopfes traegt !important (noetig gegen Leaflets eigenes Stylesheet)
    und gewann damit gegen die An-Regel: Der Knopf blieb dunkel, egal ob Moving Map an oder
    aus war. Von aussen sah es aus, als wuerde das Abschalten beim Verschieben nicht
    funktionieren -- tatsaechlich funktionierte es die ganze Zeit, nur ohne es zu zeigen
    (Messung aus dem Sim: abgeschaltet 1, movingMapJetzt false, Aussehen unveraendert).

    Der Fehler hat drei Runden gekostet, weil meine Tests die gesetzte CSS-KLASSE geprueft
    haben. Eine Klasse ist kein Beleg dafuer, dass man etwas sieht."""
    m = re.search(r"\.navi-bar\.navi-an \.navi-knopf \{([^}]*)\}", INDEX, re.S)
    assert m, "An-Zustand des Moving-Map-Knopfes nicht gefunden"
    regel = m.group(1)
    for eigenschaft in ("background", "color", "border-color"):
        zeile = [z for z in regel.split(";") if z.strip().startswith(eigenschaft)]
        assert zeile, f"{eigenschaft} fehlt im An-Zustand"
        assert "!important" in zeile[0], (
            f"{eigenschaft} ohne !important -- die Grundfarbe (die es hat) gewinnt, "
            "und der Zustand ist unsichtbar")


def test_flugzeug_symbol_ist_mittig_verankert():
    """Das Symbol ist 26 px gross (Nutzer-Wahl). Der Anker MUSS die Mitte sein und mit der
    Groesse mitwachsen -- sonst sitzt das Flugzeug nicht auf seiner eigenen Position,
    sondern daneben, und zwar umso weiter, je groesser das Symbol ist."""
    assert "const _FLUGZEUG_PX = 26;" in INDEX
    # Seit v12.7.0 nimmt die Funktion einen zweiten Parameter fuer den kleineren, grauen
    # Fremdverkehr. Der Anker muss dann erst recht mitwachsen -- er darf sich nicht mehr auf
    # eine feste Groesse verlassen.
    assert "const _FLUGZEUG_PX_FREMD = 18;" in INDEX
    m = re.search(r"function makeAircraftIcon\(heading, fremd\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "makeAircraftIcon nicht gefunden"
    rumpf = m.group(1)
    assert "const mitte = px / 2;" in rumpf
    assert "iconAnchor: [mitte, mitte]" in rumpf, "fester Anker haelt der Groesse nicht stand"
    assert "iconSize:   [px, px]" in rumpf
    # Die alte Form (Rumpf und Fluegel gleich breit -- vergroessert ein Stern) ist raus.
    assert "M12 2L8 10H4" not in INDEX


def test_nur_der_takt_bewegt_marker():
    """updateMap darf Marker anlegen und beschriften, aber nicht mehr bewegen.

    Es laeuft auf DREI Wegen: SSE-Meldung, ein 10-Sekunden-Neuzeichnen mit UNVERAENDERTEN
    Daten und ein 15-Sekunden-Abruf. Jeder Aufruf setzte die Marker auf den letzten
    Meldepunkt zurueck und machte die Fortrechnung zunichte -- sichtbar als staendiges
    Vor- und Zurueckspringen (Nutzer, 15.08.2026: "zeichnet die position immer 3-8 sekunden
    weiter und springt dann immer wieder zurueck zum gezeichneten track").

    Eine bewegte Anzeige braucht genau eine Stelle, die sie bewegt."""
    m = re.search(r"function updateMap\(pilots\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "updateMap nicht gefunden"
    rumpf = m.group(1)
    # Genau EIN setLatLng darf uebrig sein: das beim Anlegen eines neuen Markers.
    assert rumpf.count("setLatLng") == 0, \
        "updateMap bewegt weiterhin Marker -- das macht nur noch _naviTakt"
    # Und die Empfangszeit nur bei wirklich neuen Werten, sonst startet die Fortrechnung
    # bei jedem der drei Aufrufe von vorn.
    assert "const neuerWert = !alt ||" in rumpf
    assert "if (neuerWert) {" in rumpf


def test_eigener_marker_hat_nur_eine_quelle():
    """Solange der Simulator meldet, setzt NUR er den eigenen Marker.

    Anfangs taten es zwei: Der Sekundentakt schrieb die genaue Sim-Position hinein, und der
    VATSIM-Zulauf (updateMap, alle 15 s) ueberschrieb sie danach wieder mit seiner groberen
    Meldung. Sichtbar war das als regelmaessiges Zurueckspringen des eigenen Flugzeugs
    (Nutzer-Fund 15.08.2026: "springt immer kurz zu einem berechneten Wert, der aber nicht
    mit der tatsaechlichen live position zusammenpasst").

    Zwei Quellen fuer dieselbe Sache brauchen eine Rangfolge, keinen Wettlauf."""
    assert "function _markerGehoertDemSim(callsign)" in INDEX
    # Positionen setzt updateMap gar nicht mehr (s. test_nur_der_takt_bewegt_marker) --
    # beim KURS ist die Ausnahme aber weiterhin noetig: Er kam ebenfalls von VATSIM und
    # haette das Symbol wieder in die Richtung von vor bis zu 15 Sekunden gedreht.
    m = re.search(r"const demSim = _markerGehoertDemSim\(p\.callsign\);(.*?)\n    \} else \{", INDEX, re.S)
    assert m, "die Abfrage fehlt in updateMap"
    assert "if (!demSim && vorhanden._fsHeading !== hdg)" in m.group(1), \
        "updateMap ueberschreibt den Kurs aus dem Simulator weiterhin"
    # Und der Takt rechnet den eigenen Flieger nicht als einen von vielen fort.
    t = re.search(r"function _naviTakt\(sofort\) \{(.*?)\n\}", INDEX, re.S)
    assert t and "if (_markerGehoertDemSim(cs)) continue;" in t.group(1), \
        "der Takt setzt den eigenen Marker erst auf den Schaetzwert und korrigiert dann"


def test_vollbild_ohne_viewport_einheiten():
    """Im Vollbild darf die Karte NICHT ueber Viewport-Einheiten bemessen werden.

    Das Kniebrett setzt `zoom: 1.35` auf das Wurzelelement, damit die Schrift im Cockpit
    lesbar ist. Viewport-Einheiten ignorieren diesen Zoom: Gemessen bei 748 px Fensterbreite
    ergab `width: 100vw` glatte 1010 px. Die Karte wurde im Vollbild also ein Drittel zu
    breit, und alles am rechten Rand -- Ebenen-Auswahl, Kompass, Moving-Map-Knopf -- lag
    ausserhalb des Bildschirms (Nutzer-Fund 15.08.2026: "vollbild hat keine Buttons").

    Die vier Raender auf 0 erledigen dasselbe bei `position: fixed` und kennen den Zoom.
    Deshalb hier festgehalten, dass die Masse NICHT zurueckkommen."""
    m = re.search(r"\n    \.map-is-fullscreen \{([^}]*)\}", INDEX, re.S)
    assert m, ".map-is-fullscreen nicht gefunden"
    regel = m.group(1)
    assert "100vw" not in regel, "width:100vw ist im Panel um den Zoomfaktor zu breit"
    assert "100vh" not in regel, "height:100vh ist im Panel um den Zoomfaktor zu hoch"
    # Die vier Raender muessen da sein, sonst fuellt das Element gar nichts mehr.
    for seite in ("top", "right", "bottom", "left"):
        assert f"{seite}: 0 !important" in regel, f"{seite}-Rand fehlt"
    # Die fremden Masse muessen AUFGEHOBEN werden, nicht nur weggelassen: `#map-container`
    # traegt eine feste `height: 580px`, und ein ID-Selektor schlaegt diesen Klassen-
    # Selektor. Als die eigene Hoehe wegfiel, gewann diese Regel -- das Vollbild hoerte
    # unten vor dem Bildschirmrand auf ("was soll der rand unten?", 15.08.2026).
    assert "height: auto !important" in regel, \
        "ohne auto gewinnt #map-container{height:580px} und das Vollbild bleibt zu kurz"
    assert "width: auto !important" in regel


def test_fremder_drehknopf_ist_global_abgeschaltet():
    """Das Plugin haengt seinen eigenen Dreh-Knopf per addInitHook an JEDE Karte -- die
    Voreinstellung ist `rotateControl: true`, unabhaengig von `rotate`. Im Track-Fenster und
    auf der Events-Karte tauchte dadurch ein Knopf auf, der dort nichts bewirken kann
    (Nutzer-Fund 15.08.2026: "Track hat einen kompassbutton?").

    Die Option nur an der Live-Karte zu setzen, half den anderen beiden nicht. Deshalb wird
    die VOREINSTELLUNG umgestellt -- eine Stelle, gilt auch fuer jede Karte, die spaeter
    dazukommt. Genau deshalb darf sie NICHT wieder in die einzelnen Karten wandern."""
    assert "L.Map.mergeOptions({ rotateControl: false })" in INDEX
    # Die globale Umstellung muss NACH dem Plugin stehen, sonst ueberschreibt es sie wieder.
    pos_plugin = INDEX.index("leaflet-rotate@0.2.8")
    pos_aus = INDEX.index("L.Map.mergeOptions({ rotateControl: false })")
    assert pos_plugin < pos_aus, "das Plugin wuerde die Voreinstellung danach wieder setzen"
    # Und keine Wiederholung in den einzelnen Karten -- sonst zwei Wahrheiten.
    assert "rotateControl: false," not in INDEX


def test_das_ding_heisst_ueberall_kniebrett():
    """Ein Name fuer eine Sache. Der Link auf der Startseite hiess „FriesenSpy im Cockpit",
    die Seite dahinter trug beide Namen -- wer nach dem einen sucht, findet das andere nicht.
    Nutzer, 15.08.2026: "Nenn es ueberall Kniebrett" / "Nix mit im Cockpit bleibt!"

    Geprueft wird nur SICHTBARER Text. In Code-Kommentaren ist "im Cockpit" eine Ortsangabe
    ("im Cockpit wird mit dem Finger bedient") und kein Produktname -- die bleiben."""
    assert '<a href="/efb" style="color:var(--green);">Kniebrett</a>' in INDEX
    efb = (STATIC / "efb.html").read_text(encoding="utf-8")
    assert "<title>Kniebrett</title>" in efb
    assert "<h1>Kniebrett</h1>" in efb
    assert "FriesenSpy im Cockpit" not in efb


def test_knoepfe_verschwinden_ohne_eigenes_flugzeug():
    """Ohne eigenes Flugzeug koennen beide Knoepfe nichts ausrichten -- dann sind sie weg,
    statt eine Funktion vorzutaeuschen. Nutzerfrage vom 14.08.2026: "Macht das Sinn, die
    Buttons anzuzeigen, wenn ich gar nicht online bin?"

    EINE Regel fuer Website und Kniebrett. Ein erster Anlauf hatte beide getrennt behandelt
    mit der Begruendung, im Browser sei Selbstfliegen die Ausnahme -- das stimmt nicht ("2d
    piloten werden eher die Website nutzen"). Beide Orte sind gemischt; zwei Verhaltensweisen
    fuer denselben Fall waeren eine Sonderregel ohne Anlass."""
    m = re.search(r"function _naviKnopfAnstrich\(\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_naviKnopfAnstrich nicht gefunden"
    rumpf = m.group(1)
    assert "_eigenePosition()" in rumpf, "der Anstrich fragt gar nicht, ob es eine Position gibt"
    assert "navi-weg" in rumpf
    assert "_PANEL_MODUS" not in rumpf, "Website und Kniebrett duerfen sich hier nicht unterscheiden"
    m2 = re.search(r"\.navi-bar\.navi-weg \{([^}]*)\}", INDEX, re.S)
    assert m2 and "display: none" in m2.group(1)


def test_kompassnadel_dreht_mit_der_karte():
    """Die Nadel zeigt dorthin, wo auf der Karte Norden liegt -- sie dreht also MIT der
    Karte, nicht gegen sie. Das Vorzeichen war zuerst umgekehrt (gemessen: bei Kurs 090
    zeigte sie nach Osten statt nach Westen), deshalb steht es hier fest."""
    assert "_kompassNadel.style.transform = 'rotate(' + soll + 'deg)'" in INDEX


def test_vollbildknopf_ist_zentriert_und_hat_sein_symbol_zurueck():
    """Der Knopf war zwischendurch ohne Symbol -- der Nutzer hatte es aufgegeben, weil es im
    Kniebrett nie erschien. Seit dem xlink-Fix erscheint es, also ist es wieder da; nur
    groesser als sonst, weil 1em hier gerade 8,3 Pixel waeren."""
    m = re.search(r"\.map-fullscreen-btn \{([^}]*)\}", INDEX, re.S)
    assert m, ".map-fullscreen-btn nicht gefunden"
    regel = m.group(1)
    assert "justify-content: center" in regel and "align-items: center" in regel
    assert INDEX.count('<svg class="icon"><use href="#icon-fullscreen"') == 3, \
        "nicht alle drei Vollbild-Knoepfe tragen ihr Symbol"
    m2 = re.search(r"\.map-fullscreen-btn \.icon \{([^}]*)\}", INDEX, re.S)
    assert m2, "eigene Symbolgroesse fehlt"
    # gap gibt es in Coherent GT nicht -- der Abstand MUSS ueber margin kommen.
    assert "margin-right" in m2.group(1)


def test_sprite_messung_ist_im_bericht():
    """Der Beleg fuer den Fix. Die Glyphen-Messung zeigt nur, dass die ZEICHEN fehlen (⛶, ✕)
    -- dass die SVG-Ersatzsymbole ankommen, hat vorher niemand gemessen, und genau dort lag
    der Fehler. probeSprites vergleicht href gegen xlink:href und misst zusaetzlich ein
    Symbol aus dem echten Markup."""
    assert "function probeSprites()" in INDEX
    assert "base.sprites = probeSprites();" in INDEX, "Messung laeuft, geht aber nicht in den Bericht"
    # getBBox statt getBoundingClientRect: das aeussere <svg> hat seine Groesse immer, nur die
    # Bounding-Box des INHALTS ist 0, wenn der Verweis ins Leere lief.
    assert "getBBox()" in INDEX, "ohne getBBox misst die Probe nur den leeren Rahmen"


# ---------------------------------------------------------------------------
# Label am Flugzeug (v12.7.0)
# ---------------------------------------------------------------------------

def test_label_hat_genau_eine_hoehen_funktion():
    """Eine Regel, eine Funktion.

    Eine zweite Fassung fuer den Fremdverkehr waere die eigentliche Gefahr: Zwei
    Formatierungen derselben Hoehe laufen frueher oder spaeter auseinander, und der Fehler
    faellt erst im Cockpit auf.
    """
    assert INDEX.count("function _labelHoehe(") == 1
    assert INDEX.count("function _verkehrLabel(") == 1


def test_label_grenze_steht_bei_zehntausend():
    assert "_LABEL_FL_AB_FT = 10000" in INDEX


def test_label_zeigt_callsign_bei_tief_oder_friese():
    """Die Regel ist ein ODER -- nur eine der beiden Bedingungen waere ein halbes Feature."""
    stelle = INDEX.index("function _verkehrLabel(")
    rumpf = INDEX[stelle:stelle + 1200]
    assert "istFriese ||" in rumpf and "_LABEL_FL_AB_FT" in rumpf


def test_friesen_marker_tragen_das_label():
    """Das Label ist fuer die Friesen genauso neu wie fuer den Fremdverkehr."""
    assert "_verkehrLabel(p, true)" in INDEX
    assert "className: 'traffic-label'" in INDEX


def test_label_ist_nicht_blau():
    """Blau (#2d9cdb) ist in diesem Projekt Klickbarem vorbehalten (CLAUDE.md, UI-Regeln).
    Ein Tooltip ist per Default nicht anklickbar."""
    m = re.search(r"\.traffic-label \.lbl-cs\s*\{([^}]*)\}", INDEX)
    assert m, "Regel fuer den Callsign im Label fehlt"
    assert "2d9cdb" not in m.group(1)


# ---------------------------------------------------------------------------
# Verkehrs-Ebene (v12.7.0)
# ---------------------------------------------------------------------------

def test_verkehr_layer_kommt_vor_der_ebenen_auswahl():
    """Die OpenAIP-Falle: Ein nach dem Bau der Control hinzugefuegter Layer feuert keines der
    Ereignisse, auf die die Control lauscht -- der Haken zeigt dann dauerhaft den falschen
    Zustand. Steht so schon als Kommentar bei _addPreferredAIPLayer.

    ACHTUNG beim Aendern: INDEX.index(sub, start) liefert per Definition immer einen Wert
    >= start -- ein "assert vorher < INDEX.index('L.control.layers(', vorher)" koennte gar
    nicht fehlschlagen. Die Control MUSS unabhaengig gefunden werden (es gibt drei
    L.control.layers-Aufrufe in der Datei), hier ueber ihren eindeutigen Nachbarn.
    """
    vorher = INDEX.index("_addPreferredVerkehrLayer(liveMap")
    control = INDEX.index("liveOverlays,")
    assert vorher < control


def test_verkehr_popup_nimmt_dieselbe_hoehen_regel():
    """Sonst steht am Symbol FL120 und einen Klick daneben 12.000 ft: das vorhandene fmtAlt
    schreibt Flugflaechen erst ab 18 000 ft."""
    stelle = INDEX.index("function _verkehrPopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_labelHoehe(" in rumpf
    assert "fmtAlt(" not in rumpf


def test_eigener_abruf_loest_keinen_neuen_abruf_aus():
    """_naviTakt ruft bei eingeschalteter Moving Map jede Sekunde setView auf, und das feuert
    moveend. Ohne die Wache liefe der Verkehrs-Abruf alle 3 Sekunden statt alle 15 --
    dauerhaft, ausgerechnet ueber die Netzwerkverbindung des Simulators."""
    stelle = INDEX.index("map.on('moveend'")
    assert "_naviSelbstBewegt" in INDEX[stelle:stelle + 200]


def test_verkehr_ruht_auf_verdeckter_karte():
    """updateMap und _naviTakt brechen auf einer verdeckten Karte ab -- der Abruf muss das
    auch, sonst laufen die Rohwerte weiter, waehrend der Takt die Marker nicht bewegt, und
    beim Zurueckwechseln springen sie."""
    stelle = INDEX.index("function _verkehrAbrufen(")
    assert "_istSichtbar(" in INDEX[stelle:stelle + 600]


def test_nur_der_takt_bewegt_den_fremdverkehr():
    """Eine bewegte Anzeige braucht genau eine Stelle, die sie bewegt -- sonst springt sie
    zurueck. Derselbe Fehler kostete bei den Friesen drei Anlaeufe."""
    assert INDEX.count("_verkehrMarker[cs].setLatLng(") == 1


def test_verkehr_zeitstempel_nur_bei_neuen_werten():
    stelle = INDEX.index("function _verkehrUebernehmen(")
    rumpf = INDEX[stelle:stelle + 2500]
    assert "alt.lat !== e.lat" in rumpf and "alt.lon !== e.lon" in rumpf


def test_verkehr_hat_eine_einzige_zoom_schwelle():
    """Der Wert steht genau einmal als Zahl -- eine zweite Stelle daneben waere die Sorte
    Fehler, die man erst im Cockpit bemerkt."""
    assert INDEX.count("_VERKEHR_MIN_ZOOM") >= 2
    assert INDEX.count("_VERKEHR_MIN_ZOOM =") == 1


def test_verkehr_datiert_die_fortrechnung_zurueck():
    stelle = INDEX.index("function _verkehrUebernehmen(")
    assert "Date.now() - Math.round(ageSek * 1000)" in INDEX[stelle:stelle + 1200]


def test_verkehr_verschwindet_erst_beim_zweiten_fehlen():
    """Der Server kappt hart bei 60 nach Entfernung. Ohne Hysterese flackert das Flugzeug auf
    Rang 60/61 zwischen zwei Abrufen -- und jedes Neuanlegen ist im Kniebrett ein Aufblitzen."""
    stelle = INDEX.index("function _verkehrUebernehmen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", INDEX.index("for (const cs in _verkehrMarker)", stelle))]
    assert "_verkehrFehlt[cs] < 2" in rumpf


# ---------------------------------------------------------------------------
# Die Messsonde ist ausgebaut (Kniebrett-Paket 1.5.0)
# ---------------------------------------------------------------------------

@ohne_panel
def test_alte_sonde_ist_raus():
    """Feste Termine nach dem Oeffnen der App treffen den richtigen Moment nur zufaellig: Der
    Nutzer laedt erst den Flug -- dann ist das Tablet schon offen -- und verbindet ERST DANACH
    vPilot. Genau daran ist die erste Messung gescheitert (dreimal 'null Flugzeuge', alle drei
    vor der Verbindung). Ersetzt durch eine Diagnose aus dem echten Zulieferer."""
    assert "_SONDE_ZEITPUNKTE" not in PANEL_TSX
    assert "sondeMessen" not in PANEL_TSX
    assert "traffic-sonde" not in INDEX


def test_gegenprobe_gegen_vatsim_bleibt():
    """Eine Null ohne Vergleich beantwortet nichts. 'Sim 0, VATSIM 7' ist eine Antwort,
    'Sim 0, VATSIM 0' ist keine -- deshalb haengt an jeder Diagnose die Zahl der Flugzeuge,
    die VATSIM im selben Moment in der Naehe kennt."""
    stelle = INDEX.index("function _diagnoseMitVergleichMelden(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "/api/traffic?lat=" in rumpf
    assert "befund.vatsimNah" in rumpf
    # Auch wenn die Gegenprobe scheitert, MUSS gemeldet werden -- sonst verschluckt ein
    # Netzfehler die eigentliche Messung.
    assert ".then(melden, melden)" in rumpf


@ohne_panel
def test_panel_benutzt_nodereference_nicht_react():
    """FSComponent.createRef liefert eine NodeReference mit .instance -- NICHT .current wie
    React. Der Griff daneben kostet keinen Compilerfehler, nur eine Funktion, die zur Laufzeit
    nichts tut."""
    assert ".instance" in PANEL_TSX
    assert ".current" not in PANEL_TSX


def test_diagnose_wird_mit_zwei_argumenten_gemeldet():
    """window._panelDiag(kind, data). Mit einem Argument landete der ganze Befund im Feld
    kind, und der Datensatz bekaeme nie seine Art."""
    assert "window._panelDiag(art, befund)" in INDEX


def test_eigenes_flugzeug_hat_auch_ein_label():
    """Im Sim ohne VATSIM stand am eigenen Flugzeug gar nichts -- nur ein Popup auf Klick
    (Live-Test 15.08.2026). Die Werte muessen am Symbol stehen wie bei allen anderen."""
    stelle = INDEX.index("function _eigenLabel(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_labelHoehe(" in rumpf, "eigene Hoehenregel statt der gemeinsamen"
    assert "DEIN FLUGZEUG" in rumpf
    assert "_eigenLabel()" in INDEX, "Label wird nie gesetzt"


def test_hoehe_kommt_aus_dem_simulator():
    """Ohne PLANE ALTITUDE kann am eigenen Flugzeug keine Hoehe stehen -- die Seite kennt sie
    offline aus keiner anderen Quelle."""
    assert 'GetSimVarValue("PLANE ALTITUDE", "feet")' in PANEL_TSX
    assert "alt: isFinite(alt) ? alt : null" in PANEL_TSX, \
        "unbrauchbare Hoehe muss als null gehen, nicht als NaN"


def test_fehlende_hoehe_ist_nicht_null_fuss():
    """Ein aelteres Kniebrett schickt keine Hoehe. `null` heisst unbekannt und wird
    weggelassen; 0 ist ein gueltiger Wert (Flugzeug auf Meereshoehe)."""
    stelle = INDEX.index("if (d.art === 'position')")
    rumpf = INDEX[stelle:stelle + 900]
    assert "(d.alt == null) ? null : Number(d.alt)" in rumpf


def test_fremde_haben_eine_eigene_silhouette():
    """Form UND Groesse unterscheiden die beiden -- die Farbe allein tut es nicht mehr, seit
    beide dunkel sind. Friesen: gerade Fluegel (Leichtflugzeug). Fremde: gepfeilte Fluegel
    (Verkehrsflugzeug)."""
    assert "const _FLUGZEUG_PFAD_FREMD =" in INDEX
    m_eigen = re.search(r"const _FLUGZEUG_PFAD =\s*(.*?);", INDEX, re.S)
    m_fremd = re.search(r"const _FLUGZEUG_PFAD_FREMD =\s*(.*?);", INDEX, re.S)
    assert m_eigen and m_fremd
    assert m_eigen.group(1) != m_fremd.group(1), "beide Marker zeichnen dieselbe Form"
    assert "const pfad = fremd ?" in INDEX, "makeAircraftIcon waehlt die Form nicht aus"


def test_die_beiden_marker_saeume_sind_gegenlaeufig():
    """Friesen hell mit dunklem Saum, Fremde dunkel mit hellem -- so tragen beide auf jeder
    Kartensorte UND sind voneinander zu unterscheiden.

    Die Gegenprobe wurde im Sim gemacht (15.08.2026): dunkles Vereinsblau mit hellem Saum
    las sich auf allen Karten ausser "Dark" als Schwarz, und die beiden Marker-Arten waren
    nicht mehr auseinanderzuhalten. Beide dunkel ist der Fehler, den dieser Test verhindert.
    """
    m_eigen = re.search(r"\.aircraft-marker \{([^}]*)\}", INDEX)
    m_fremd = re.search(r"\.aircraft-marker-fremd \{([^}]*)\}", INDEX)
    assert m_eigen and m_fremd
    assert "color: var(--green)" in m_eigen.group(1), "Friesen nicht mehr im hellen Blau"
    assert "rgba(0,0,0" in m_eigen.group(1), "heller Marker braucht einen dunklen Saum"
    assert "rgba(255,255,255" in m_fremd.group(1), "dunkler Marker braucht einen hellen Saum"


def test_live_karte_oeffnet_ueber_edwg():
    """EDWG (Wangerooge) ist der Heimatplatz. Der alte Startpunkt lag in der offenen Nordsee,
    rund 130 km westlich -- jedes Oeffnen begann mit Schieben."""
    assert "const _KARTE_MITTE = [53.78278, 7.91389];" in INDEX
    assert "center:    [54.5, 8.5]" not in INDEX
    assert "center:    _KARTE_MITTE," in INDEX


def test_start_zoom_liegt_nicht_unter_der_verkehrs_schwelle():
    """Laege die Verkehrs-Schwelle ueber der Start-Zoomstufe, schaltete man die Ebene ein und
    es passierte sichtbar nichts."""
    m_start = re.search(r"const _KARTE_ZOOM\s*=\s*(\d+);", INDEX)
    m_verkehr = re.search(r"const _VERKEHR_MIN_ZOOM = (\d+);", INDEX)
    assert m_start and m_verkehr
    assert int(m_start.group(1)) >= int(m_verkehr.group(1))


# ---------------------------------------------------------------------------
# Verkehr aus dem Simulator (Teilprojekt 2a, Kniebrett-Paket 1.5.0)
# ---------------------------------------------------------------------------

@ohne_panel
def test_verkehr_wird_im_sekundentakt_geholt():
    """1000 ms ist nicht geraten, sondern Asobos eigener Takt in seiner eigenen VFR-Karte
    (VfrTrafficManager.POLL_INTERVAL im ausgelieferten GameVFRMap.js)."""
    m = re.search(r"const VERKEHR_INTERVALL_MS = (\d+);", PANEL_TSX)
    assert m and int(m.group(1)) == 1000


@ohne_panel
def test_verkehr_hat_einen_riegel_gegen_doppelaufrufe():
    """Das offizielle SDK haelt einen isBusy-Riegel um genau diesen Aufruf. Ohne ihn stapeln
    sich bei einem langsamen Aufruf die Anfragen, und die Antworten kommen durcheinander."""
    assert "verkehrLaeuft" in PANEL_TSX
    stelle = PANEL_TSX.index("private verkehrTakt(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert "this.verkehrLaeuft" in rumpf


@ohne_panel
def test_verkehr_wartet_nicht_ewig():
    """Coherent.call kann haengen bleiben. Das SDK laesst den Aufruf gegen eine Sekunde
    antreten (Promise.race mit Wait.awaitDelay(1000)) -- ohne das bliebe der Riegel aus dem
    Test darueber fuer immer zu."""
    stelle = PANEL_TSX.index("private async verkehrHolen(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert "Promise.race" in rumpf
    assert "VERKEHR_WARTE_MAX_MS" in rumpf


@ohne_panel
def test_hoehe_wird_von_metern_in_fuss_gerechnet():
    """`alt` kommt in METERN. Belegt im ausgelieferten msfssdk.js des Simulators:
    UnitType.METER.convertTo(entry.alt, UnitType.FOOT). Ohne die Umrechnung stuende an einem
    Airliner in FL350 die Zahl 10 668 -- und im Label FL107."""
    m = re.search(r"const FUSS_JE_METER = ([\d.]+);", PANEL_TSX)
    assert m and abs(float(m.group(1)) - 3.28084) < 0.001


@ohne_panel
def test_ohne_eingeschaltete_ebene_wird_nicht_abgefragt():
    """Ein Coherent.call je Sekunde, den niemand zeichnet, ist Arbeit im Simulator ohne
    Gegenwert. Die Seite meldet den Zustand der Ebene ueber den bestehenden Rueckkanal."""
    assert '"verkehr-schalter"' in PANEL_TSX
    stelle = PANEL_TSX.index("private verkehrTakt(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert "this.verkehrAn" in rumpf


@ohne_panel
def test_verkehrsmeldung_traegt_die_quelle():
    """Der Empfaenger in index.html verwirft in seiner ersten Zeile jede Nachricht ohne
    quelle === 'friesenspy-shell'. Ohne sie kommt nichts an, ohne jede Fehlermeldung."""
    assert 'quelle: "friesenspy-shell", art: "sim-verkehr"' in PANEL_TSX
