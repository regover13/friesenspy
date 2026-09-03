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
    panel_resp = asyncio.run(main.panel(v=main._panel_kennwert()))
    assert panel_resp.path == index_resp.path
    assert dict(panel_resp.headers) == dict(index_resp.headers)


def test_panel_ohne_oder_mit_alter_version_leitet_um():
    """Cache-Bust-Fix (Live-Test-Fund 13.08.2026): Coherent GT hat sich als unzuverlässig beim
    Befolgen von Cache-Control erwiesen -- /panel ohne oder mit veraltetem v= muss auf die
    aktuelle, garantiert noch nie angefragte, versionierte URL umleiten statt den (potenziell
    gecachten) Inhalt direkt auszuliefern.

    Der Kennwert ist seit dem 24.08.2026 nicht mehr die blosse Versionsnummer, sondern
    Version PLUS Kurz-Hash der ausgelieferten index.html. Grund: Die Sichtflugkarten wurden
    einen ganzen Tag lang bei unveraenderter Version 13.8.2 mehrfach deployt -- die URL blieb
    dieselbe, und im Kniebrett kam keine einzige Aenderung an. Deshalb hier an
    ``_panel_kennwert()`` gebunden und nicht an ``VERSION``: Ein Test auf die Versionsnummer
    wuerde genau diesen Rueckfall durchgehen lassen."""
    resp_ohne = asyncio.run(main.panel(v=None))
    assert resp_ohne.status_code == 302
    assert resp_ohne.headers["location"] == f"/panel?v={main._panel_kennwert()}"

    resp_alt = asyncio.run(main.panel(v="0.0.1"))
    assert resp_alt.status_code == 302
    assert resp_alt.headers["location"] == f"/panel?v={main._panel_kennwert()}"


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
    r = env.client.get(f"/panel?v={main._panel_kennwert()}", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 200
    assert "vr-panel" in r.text  # dieselbe Seite wie /, samt VR-Erkennungs-Skript


def test_panel_route_leitet_ueber_echten_http_request_um(env):
    """Cache-Bust-Redirect auch über den echten Routing-Pfad (TestClient), nicht nur bei
    Direktaufruf von main.panel() -- deckt z. B. ab, dass FastAPI den v-Query-Parameter
    tatsächlich an die Handler-Signatur durchreicht."""
    r = env.client.get("/panel", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == f"/panel?v={main._panel_kennwert()}"


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
    getElementById nur null -- _initPanelTopbar braeche dann stumm an seiner eigenen Wache
    ab, und die Leiste bliebe leer."""
    assert "_initPanelTopbar();\n_initPanelTranslit();" not in INDEX
    m = re.search(r"document\.addEventListener\('DOMContentLoaded', \(\) => \{\n"
                  r"(?:  //.*\n)*"                     # erklaerende Kommentare erlaubt
                  r"  _initPanelTopbar\(\);\n  _initPanelTranslit\(\);\n"
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


def test_vollbild_im_panel_zeigt_nur_die_karte():
    """Vollbild im Kniebrett heisst seit 02.09.2026: NUR Karte -- die Zurueck-/Tab-Leiste
    verschwindet mit.

    Sie war das eigentliche Problem: fest am oberen Rand, und alles, was die Karte oben
    anbietet, lag darunter -- zuletzt der ICAO-Suchkasten, dessen Eingabefeld dadurch halb
    verdeckt war (Nutzer-Bild 02.09.2026).

    Die Umkehr davon ist der wichtigere Teil des Tests: Ohne Leiste MUSS der Knopf in der
    Karte zurueckkommen, sonst gibt es aus dem Vollbild gar keinen Weg mehr heraus -- genau
    die Lage, die den Zurueck-Knopf am 13.08.2026 ueberhaupt erst noetig machte."""
    assert "html.vr-panel.karte-vollbild .panel-topbar { display: none !important; }" in INDEX
    # Der Knopf in der Karte darf NICHT mehr ausgeblendet werden -- er ist jetzt der Ausgang.
    assert "html.vr-panel .map-is-fullscreen .map-fullscreen-btn { display: none" not in INDEX
    # ... und er muss ueber Leaflets Herkunftsangabe liegen, die unten links entlanglaeuft.
    assert "html.vr-panel .map-is-fullscreen .map-fullscreen-btn { z-index: 1050; }" in INDEX, \
        "zwischen Herkunftsangabe (1000) und Ebenen-Auswahl (1100)"
    # Der zweite, eigene Notausgang unten rechts ist ganz entfallen: im Panel uebernimmt
    # die Zurueck-Leiste, auf der Website stand er als zweiter "Vollbild verlassen"-Knopf
    # neben dem ersten (Nutzer-Fund 14.08.2026).
    assert "global-map-exit-fs" not in INDEX


def test_die_leiste_bleibt_im_vollbild_einfach_weg():
    """Sie kam bis 02.09.2026 zurueck, sobald ein Fenster offen war: Ihr Zurueck-Knopf war
    der einzige Ausgang, der ueber einem Modal (z-index 10000 gegen 3000 der Karte) noch
    erreichbar blieb. Mit dem Knopf ist auch dieser Grund entfallen -- jedes Fenster
    schliesst ueber sein eigenes X, und das liegt im Fenster selbst, also oben auf."""
    m = re.search(r"function _vollbildKlassePflegen\(\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_vollbildKlassePflegen nicht gefunden"
    rumpf = m.group(1)
    assert "map-is-fullscreen" in rumpf and "classList.toggle(" in rumpf
    assert "_panelOpenModal" not in rumpf
    for stelle in ("function toggleMapFullscreen", "function exitAnyMapFullscreen"):
        block = INDEX[INDEX.index(stelle):]
        block = block[:block.index("\n}\n")]
        assert "_vollbildKlassePflegen()" in block, f"{stelle} ruft die Pflege nicht"


def test_der_ausgang_heisst_nur_vollbild():
    """Beide Zustaende tragen denselben Namen, nur das Zeichen wechselt (Nutzerwunsch
    02.09.2026). Das X sagt bereits, dass es hinausgeht -- und "verlassen" kostete Breite in
    einem Knopf, der seit dem Umbau mitten in der Karte steht statt in einer Leiste."""
    assert "icon('x') + ' Vollbild' : icon('fullscreen') + ' Vollbild'" in INDEX
    assert "Vollbild verlassen" not in _ohne_kommentare(INDEX)


def test_der_zurueck_knopf_ist_ersatzlos_entfallen():
    """Nutzerwunsch 02.09.2026: "den Back-Button brauchen wir nicht mehr".

    Er entstand am 13.08.2026 als Notausgang -- wer ein Fenster oeffnete, war auf dessen
    eigenen Schliess-Knopf angewiesen, und wenn dem Font das Glyph fehlte, sass man fest.
    Beide Gruende sind erledigt: Die Fenster schliessen ueber `#icon-x` aus dem SVG-Sprite,
    und das Karten-Vollbild hat seinen eigenen Ausgang in der Karte.

    Der Test haelt vor allem die BEDINGUNG fest, unter der das richtig bleibt: Verliert auch
    nur eines der sechs Fenster seinen eigenen Ausgang, ist der Knopf wieder noetig."""
    for tot in ("panelGoBack", "_panelCanGoBack", "_updatePanelBackBtn", "_panelOpenModal"):
        assert "function " + tot not in INDEX, tot + " lebt noch"
    assert 'id="panel-back-btn"' not in INDEX
    assert "const _PANEL_MODALS" not in INDEX
    # Die Voraussetzung: jedes Fenster schliesst selbst, und zwar ueber das Sprite.
    for modal, schliessen in (("ac-modal", "closeAcModal"), ("fp-modal", "closeFpModal"),
                              ("track-modal", "closeTrackModal"), ("fld-modal", "closeFldModal"),
                              ("changelog-modal", "closeChangelogModal"),
                              ("types-modal", "closeTypesModal")):
        stelle = INDEX.index('id="' + modal + '"')
        block = INDEX[stelle:stelle + 4000]
        assert 'onclick="' + schliessen + '()"' in block, modal + " hat keinen eigenen Ausgang"
        assert 'use href="#icon-x"' in block, modal + " schliesst nicht ueber das Sprite"


def test_leaflet_bedienelemente_weichen_der_tablet_statusleiste_aus():
    """Im Vollbild ist die eigene Leiste weg -- oben bleibt aber die Statusleiste des
    TABLETS: Die EFB-Oberflaeche legt Glocke (links) und Datum/Uhrzeit (rechts) ueber unsere
    Seite. Zoom (oben links), Ebenen/Kompass/Lupe (oben rechts) und der Suchkasten muessen
    darunter beginnen -- aber auch keinen Pixel tiefer.

    DIE FALLE IST DIE ADDITION: Leaflet gibt jedem Bedienelement selbst schon `margin: 10px`
    (leaflet.css). Der eigene Versatz kommt oben drauf, muss also um genau diese 10 kleiner
    sein als die Hoehe der Statusleiste -- sonst stehen die Knoepfe zu tief (Nutzerfund
    02.09.2026: "die Buttons oben koennen noch weiter hoch").

    Der Suchkasten haengt dagegen als `position:absolute` am Kartencontainer und nicht in
    einer Leaflet-Ecke: Er bekommt nichts geschenkt und traegt die volle Zahl."""
    versatz = re.search(r"html\.vr-panel \.map-is-fullscreen \.leaflet-top \{ margin-top: (\d+)px; \}",
                        INDEX)
    assert versatz, "Versatz der Karten-Bedienelemente nicht gefunden"
    statusleiste = re.search(r"html\.vr-panel \.panel-topbar \{.*?padding-top: (\d+)px;", INDEX, re.S)
    assert statusleiste, "Abstand zur Tablet-Statusleiste nicht gefunden"
    LEAFLET_EIGENER_RAND = 10
    assert int(versatz.group(1)) + LEAFLET_EIGENER_RAND == int(statusleiste.group(1)), \
        "Versatz plus Leaflets eigener Rand muss die Statusleiste genau treffen"
    kasten = re.search(r"html\.vr-panel \.map-is-fullscreen \.icao-box \{ top: (\d+)px; \}", INDEX)
    assert kasten, "Versatz des Suchkastens nicht gefunden"
    assert int(kasten.group(1)) == int(statusleiste.group(1)), \
        "der Kasten liegt ausserhalb von Leaflets Raster und traegt die volle Zahl"


def test_der_folge_knopf_haengt_nicht_im_stapel_der_herkunftsangabe():
    """Er sitzt in derselben Ecke wie Leaflets Herkunftsangabe, und Leaflet STAPELT die
    Elemente einer Ecke. Im Kniebrett bricht die Angabe ueber drei Zeilen um -- genau um
    deren Hoehe stand der Knopf zu hoch (Nutzer-Bild 03.09.2026).

    Erst `position: absolute` nimmt ihn aus dem Stapel heraus; Bezugspunkt ist die Ecke, die
    selbst schon an der Karte klebt. Damit liegt er auf denselben 10px wie der Vollbild-Knopf
    gegenueber, egal wie viele Zeilen die Angabe gerade braucht.

    Ein blosses `margin-bottom: 10px` genuegt NICHT -- das war der Anlauf vom 02.09.2026,
    und er scheiterte genau an diesem Stapel."""
    m = re.search(r"\.leaflet-bottom\.leaflet-right \.navi-bar \{([^}]*)\}", INDEX, re.S)
    assert m, "Regel fuer den Folge-Knopf nicht gefunden"
    regel = m.group(1)
    assert "position: absolute" in regel, "ohne absolute bleibt er im Stapel"
    assert "bottom: 10px" in regel and "right: 10px" in regel
    assert "margin: 0 !important" in regel, "Leaflets eigene Raender muessen weg"
    # ... und UEBER die Herkunftsangabe, die in derselben Ecke sitzt und von Leaflet zuletzt
    # eingefuegt wird -- sonst gewinnt sie den Gleichstand (Nutzer-Bild 03.09.2026).
    assert "z-index: 2;" in regel, "sonst liegt der Knopf unter der Lizenzangabe"
    # Der Gegenpart unten links sitzt auf derselben Zahl.
    knopf = re.search(r"\n    \.map-fullscreen-btn \{([^}]*)\}", INDEX, re.S)
    assert knopf and "bottom: 10px" in knopf.group(1)


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
    stehen, wie die anderen schwebenden Knoepfe davor (#panel-update-hint) -- sie alle sind
    Geschwister von #app, nicht seine Nachfahren.

    Der Zurueck-Knopf, um den es dabei ging, ist am 02.09.2026 entfallen. Der Ort bleibt
    trotzdem richtig: Die Leiste braucht ihre eigene Stapel-Ebene, sonst kappte #app sie auf
    Rang 1."""
    # rindex, nicht index: ganz am Dateianfang steht bereits ein winziges Inline-<script>
    # fuer die vr-panel-Erkennung (s. Kommentar dort), dessen </script> waere hier ein
    # falsch-positiver erster Treffer.
    script_ende = INDEX.rindex("</script>")
    topbar_stelle = INDEX.index('<div id="panel-topbar"')
    app_oeffnung = INDEX.index('<div id="app"')
    assert topbar_stelle > script_ende, "#panel-topbar muss hinter dem Inline-Skript stehen"
    # #app oeffnet weit vor dem Skript-Ende (Kopfzeile/Tabs/Tab-Panels stehen alle darin) --
    # #panel-topbar dagegen erst danach, zusammen mit den uebrigen schwebenden Knoepfen.
    assert app_oeffnung < script_ende


def test_tabs_und_glocke_wandern_per_js_in_die_topbar():
    """Verschieben statt Duplizieren: dieselben Elemente (gleiche ID/Klasse), keine zweite
    Wahrheit -- bestehende Klick-Handler (data-tab) und der SSE-Status-Updater laufen
    unveraendert weiter, weil es keine Kopien sind.

    Ganz rechts steht seit dem 14.08.2026 die GLOCKE statt der Verbindungsanzeige: Sie sagt
    ueber ihre Farbe dasselbe und ist zusaetzlich der Weg zu den Kategorie-Schaltern. Ein
    Punkt daneben, der nur den Zustand wiederholt, waere im Cockpit verschenkter Platz.
    #sse-badge bleibt in der ausgeblendeten Kopfzeile -- ausblenden statt entfernen, damit
    setSSEStatus unveraendert weiterschreiben kann.

    Der Zurueck-Knopf wanderte bis 02.09.2026 als erster mit; er ist ersatzlos entfallen."""
    m = re.search(r"function _initPanelTopbar\(\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_initPanelTopbar nicht gefunden"
    rumpf = m.group(1)
    assert "getElementById('panel-topbar')" in rumpf
    assert "querySelectorAll('.tab-btn').forEach(" in rumpf
    assert "topbar.appendChild(t);" in rumpf
    assert "topbar.appendChild(glocke)" in rumpf
    assert "topbar.appendChild(sseBadge)" not in rumpf
    # KEINE Wache auf den alten Knopf mehr: Sie stand vor dem Verschieben und haette die
    # Leiste leer gelassen, sobald das Element fehlt.
    assert "getElementById('panel-back-btn')" not in rumpf


def test_die_klasse_panel_has_back_bleibt_verschwunden():
    """Der frueher schwebende Zurueck-Balken schaltete den Seiten-Abstand per
    `.panel-has-back` um. Seit die Leiste permanent steht, reserviert festes CSS den Platz --
    ein Klassenschalter daneben waere eine zweite Wahrheit ueber dieselbe Hoehe.

    Hier stand bis 02.09.2026 zusaetzlich ein Test, der einen Spezifitaets-Konflikt am
    versteckten Knopf festhielt (Playwright: Knopf blieb trotz hidden=true 102x59px gross).
    Mit dem Knopf ist er gegenstandslos geworden."""
    assert "classList.toggle('panel-has-back'" not in INDEX
    assert "panel-has-back body" not in INDEX
    assert "html.vr-panel.panel-has-back" not in INDEX


def test_die_leiste_reserviert_ihren_platz_per_festem_css():
    """Kein JS-Klassenschalter mehr fuer den Seiten-Abstand: Die Leiste steht konstant, also
    steht auch der Abstand konstant im CSS."""
    hoehe = re.search(r"html\.vr-panel body \{ padding-top: (\d+)px; \}", INDEX)
    assert hoehe, "Leistenhoehe (body padding-top) nicht gefunden"


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
    Sie muss deshalb wie die Tabs in die Panel-Leiste wandern."""
    m = re.search(r"function _initPanelTopbar\(\) \{\n(.*?)\n\}\n", INDEX, re.S)
    assert m, "_initPanelTopbar nicht gefunden"
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
    (Nutzer, 14.08.2026). Gemessen bei echter Tablet-Breite (413 CSS-Pixel), damals mit dem
    Zurueck-Knopf: BACK 154, Tabs zusammen 214, Glocke 44 -- kein Ueberlauf. Seit dem Wegfall
    des Knopfes am 02.09.2026 teilen sich die vier Tabs dessen 154 Pixel mit."""
    assert "_PANEL_TAB_TEXT = { live: 'LIVE', karte: 'MAP', statistiken: 'STATS', events: 'EVENTS' }" in INDEX
    assert "_panelBeschriftung(btn, 'BACK')" not in INDEX
    # Die Website behaelt ihre deutschen Beschriftungen.
    # Nur die Beschriftung festnageln, nicht das Symbol-Markup dazwischen -- sonst bricht der
    # Test bei jeder Aenderung an den Sprite-Verweisen (passiert beim xlink-Fix).
    assert re.search(r'data-tab="statistiken">.*?STATISTIKEN', INDEX), \
        "die Website muss ihre deutschen Tab-Beschriftungen behalten"
    # Der deutsche Zurueck-Knopf ist mit dem Knopf selbst entfallen.
    assert 'Zur&uuml;ck</button>' not in INDEX


def test_panel_leiste_ist_in_vr_lesbar_dimensioniert():
    """Die Ausgangswerte (Tabs 0.62rem) waren im Headset zu klein.

    `flex: 1 1 0` verteilt die Breite gleichmaessig von der Grundlage null aus, nicht nach
    Textlaenge -- sonst bekaeme "EVENTS" mehr Platz als "MAP" (Nutzerwunsch 02.09.2026:
    "achte dann auf die Breiten des Menues, anzeigen wie auf dem Live-Tab"). Bis dahin stand
    hier `0 1 auto`, und die gleichmaessige Verteilung galt nur, solange der Zurueck-Knopf
    ausgeblendet war."""
    tabs = re.search(r"html\.vr-panel \.panel-topbar \.tab-btn \{(.*?)\n    \}", INDEX, re.S)
    assert tabs, "Tab-Regel der Panel-Leiste nicht gefunden"
    assert "font-size: 0.85rem" in tabs.group(1)
    assert "flex: 1 1 0" in tabs.group(1), "die vier Ansichten muessen sich den Platz teilen"
    assert "flex: 0 1 auto" not in tabs.group(1), "die alte Verteilung nach Textlaenge lebt noch"
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


def test_die_breitenverteilung_haengt_an_keiner_bedingung_mehr():
    """Sie hing bis 02.09.2026 am ausgeblendeten Zurueck-Knopf
    (`.panel-back-btn[hidden] ~ .tab-btn`) und galt deshalb nur, solange es nichts zu
    verlassen gab. Mit dem Knopf ist die Bedingung entfallen -- es gibt niemanden mehr, der
    sich den Rest nehmen koennte."""
    assert ".panel-back-btn[hidden] ~ .tab-btn" not in _ohne_kommentare(INDEX)


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
    # EINE Groesse fuer alle Bedienelemente der Karte -- dieselben 30px, die Leaflet seinen
    # Zoomknoepfen gibt (`.leaflet-touch .leaflet-bar a`). Bis 03.09.2026 standen unsere auf
    # 44px, dem Mindestmass fuer TIPPziele; der Nutzer bedient das Kniebrett aber mit der
    # Maus. Zwei Massstaebe nebeneinander (Leaflets 30 links, unsere 44 rechts) fielen in
    # jedem Bild sofort auf.
    assert "30px !important" in t.group(1), "die Ebenen-Auswahl faellt aus der Reihe"
    k = re.search(r"\.navi-bar \.navi-knopf \{([^}]*)\}", INDEX, re.S)
    assert k and "width: 30px !important" in k.group(1), "Kompass/Lupe/Folge fallen aus der Reihe"
    v = re.search(r"\n    \.map-fullscreen-btn \{([^}]*)\}", INDEX, re.S)
    assert v and "height: 30px;" in v.group(1), \
        "der Vollbild-Knopf muss dieselbe Hoehe haben wie Wind und Zoom"


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
    assert t, "_naviTakt nicht gefunden"
    # NUR das eigene Flugzeug wird uebersprungen. Hier stand _markerGehoertDemSim -- und
    # das wurde zum Fehler, als jene Funktion mit dem Sim-Matching auch fuer FRIESEN "true"
    # zu liefern begann: Ihr Marker wurde damit vom Takt uebersprungen, und da updateMap
    # seit v12.6.2 grundsaetzlich keine Marker mehr bewegt, ruehrte ihn niemand mehr an.
    # Er blieb stehen, wo er angelegt wurde (Nutzer, 23.08.2026 -- ausdruecklich nur bei
    # Friesen, fremder Verkehr lief sauber).
    assert "if (_istEigenesFlugzeug(cs)) continue;" in t.group(1), \
        "der Takt muss NUR das eigene Flugzeug ueberspringen, nicht jeden mit Sim-Werten"
    assert "_eigenesFlugzeugZeichnen()" in t.group(1), \
        "ohne diesen Ersatz bliebe das uebersprungene eigene Flugzeug ungesetzt"


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


def test_label_zeigt_immer_alles():
    """Es gab zwei Ausnahmen: Der Callsign erschien nur unter 10 000 Fuss oder bei einem
    Friesen. Beide sind raus (Nutzer-Wahl 15.08.2026) -- wer es ruhiger will, schaltet die
    Label ganz ab. Eine Karte, die selbst entscheidet, welche Zeile man wohl braucht, ist die
    schlechtere Loesung als ein Schalter."""
    stelle = INDEX.index("function _verkehrLabel(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "istFriese" not in rumpf
    assert "_LABEL_FL_AB_FT" not in rumpf, "keine Hoehenregel mehr fuer den Callsign"
    assert 'class="lbl-cs"' in rumpf and 'class="lbl-dat"' in rumpf


def test_label_zeigt_kein_fragezeichen_fuer_fehlendes_muster():
    """Das "?" stand fuer eine Luecke, die die Paarung schliessen soll -- wo sie nicht greift,
    ist es nur eine Behauptung ueber Unwissen (Nutzer-Wahl 16.08.2026)."""
    stelle = INDEX.index("function _verkehrLabel(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "|| '?'" not in rumpf
    assert "muster ? escHtml(muster) + ' ' : ''" in rumpf, "ohne Muster faellt auch das Leerzeichen weg"


# --- Die beiden Messungen fuer die Zuordnung ---------------------------------------------
#
# Spec: docs/superpowers/specs/2026-08-16-verkehr-zuordnung-design.md. Beide Schranken der
# Zuordnung haengen an Groessen, die bisher geschaetzt sind. Zwei Beobachtungen vom 16.08.2026
# waren Grenzfaelle -- und Grenzfaelle lassen sich nicht wegjustieren, solange die Groesse
# unbekannt ist.

def test_latenz_wird_am_eigenen_flugzeug_gemessen():
    """Das eigene Flugzeug steht in beiden Quellen und seine Zuordnung steht fest -- es
    braucht also kein Matching, um das Matching zu vermessen."""
    stelle = INDEX.index("function _latenzProbeNehmen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_meineCid" in rumpf, "nur das eigene Flugzeug taugt als Massstab"
    assert "_simPosFrisch()" in rumpf
    assert "0.514444" in rumpf, "Knoten in m/s"
    assert "_LATENZ_MIN_GS" in rumpf, "im Stand ist der Quotient undefiniert"


def test_latenz_misst_nur_bei_stabilem_kurs():
    """Die wichtigste Bedingung, und sie fehlte in der ersten Fassung: Der erste Messflug war
    eine Platzrunde. Dort misst der Abstand die Sehne, nicht die Strecke -- die zwoelf Proben
    blieben bei 1,2-1,4 km, obwohl die Geschwindigkeit zwischen 60 und 96 kt schwankte.

    Die Pruefung kostet nichts: Der VATSIM-Kurs IST der Kurs von vor einer halben Minute."""
    stelle = INDEX.index("function _latenzProbeNehmen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_LATENZ_MAX_KURSDIFF" in rumpf
    assert "kursDiff > 180" in rumpf, "Winkeldifferenz muss bei 360 umschlagen"
    assert rumpf.index("kursDiff > _LATENZ_MAX_KURSDIFF") < rumpf.index("distanceTo"), \
        "erst pruefen, dann rechnen"


def test_uids_kommen_aus_der_nichtleeren_diagnose():
    """Der Startbefund faellt beim ERSTEN Abruf an -- da ist vPilot typischerweise noch nicht
    verbunden (zwei von drei Messungen am 16.08.2026 kamen mit null Flugzeugen zurueck).
    Diese Diagnose feuert beim ersten NICHTLEEREN Eintreffen."""
    stelle = INDEX.index("function _simVerkehrDiagnoseEinmal(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "ids:" in rumpf
    assert "slice(0, 20)" in rumpf
    assert "if (_simVerkehrDiagnoseGemeldet || !liste.length) return;" in rumpf


def test_latenz_nimmt_den_median_nicht_den_mittelwert():
    """In einer Kurve misst der Abstand die Kurve mit, nicht die Zeit. Der Median haelt
    solche Proben aus, ein Mittelwert nicht."""
    stelle = INDEX.index("function _latenzMelden(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "median" in rumpf
    assert "sort(" in rumpf
    assert "'vatsim-latenz'" in INDEX


def test_latenz_probe_haengt_am_neuen_wert():
    """Ohne diese Wache liefe die Messung bei jedem Neuzeichnen mit denselben Daten -- und
    wuerde eine Latenz messen, die nur die Zeit seit dem letzten Bild ist."""
    stelle = INDEX.index("const neuerWert = !alt ||")
    rumpf = INDEX[stelle:stelle + 500]
    assert "_latenzProbeNehmen(p)" in rumpf
    assert rumpf.index("if (neuerWert)") < rumpf.index("_latenzProbeNehmen(p)")


@ohne_panel
def test_diagnose_meldet_die_uids_fuer_den_sitzungsvergleich():
    """Ueberlebt die uId eine Sitzung? Davon haengt ab, ob sich eine Zuordnung dauerhaft
    speichern laesst. Eine wiederverwendete ID haenge sonst irgendwann ein falsches
    Rufzeichen an ein fremdes Flugzeug."""
    stelle = PANEL_TSX.index("private async verkehrHolen(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert "startBefund.uIds" in rumpf
    assert "slice(0, 20)" in rumpf, "es geht um das Muster, nicht um Vollstaendigkeit"


@ohne_panel
def test_diagnose_meldet_die_identitaetsfelder_mit_werten():
    """`__Type` hat noch nie jemand angesehen; `name` und `plane_model_icao` kamen leer. Nur
    die Feldnamen zu melden beantwortet nichts -- es braucht die Werte."""
    stelle = PANEL_TSX.index("private async verkehrHolen(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert "erster.__Type" in rumpf
    assert "erster.name" in rumpf
    assert "erster.plane_model_icao" in rumpf
    assert "erster.lat" not in rumpf, "keine Positionen in die Diagnose"


def test_label_nimmt_nur_noch_ein_argument():
    """Der zweite Parameter unterschied Friesen von Fremden -- ohne Unterscheidung ist er
    ueberfluessig, und ein ungenutzter Parameter ist eine Einladung zum Missverstaendnis."""
    assert "function _verkehrLabel(p)" in INDEX
    assert "_verkehrLabel(p, " not in INDEX and "_verkehrLabel(e, " not in INDEX


def test_eigenes_flugzeug_nutzt_dieselbe_labelfunktion():
    """Zwei Fassungen desselben Schildes laufen auseinander -- und beim eigenen Flugzeug
    faellt es zuletzt auf, weil man es fuer selbstverstaendlich haelt."""
    stelle = INDEX.index("function _eigenLabel(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_verkehrLabel({" in rumpf
    assert "lbl-dat" not in rumpf, "kein eigener Zusammenbau mehr"


def test_friesen_marker_tragen_das_label():
    """Das Label ist fuer die Friesen genauso neu wie fuer den Fremdverkehr."""
    assert "_verkehrLabel(p)" in INDEX
    assert "className: 'traffic-label'" in INDEX


def test_ebenen_stehen_in_der_gewaehlten_reihenfolge():
    """Nutzer-Wahl 16.08.2026: erst die Karten-Ebenen von der groessten zur kleinsten Flaeche,
    ganz am Ende der Verkehr -- die einzige, die sich bewegt und einen Unterpunkt traegt.
    Die Reihenfolge im Objekt IST die Reihenfolge in der Auswahl."""
    stelle = INDEX.index("const liveOverlays = {};")
    rumpf = INDEX[stelle:INDEX.index("L.control.layers(", stelle)]
    reihe = [n for n in ["'OpenAIP'", "'Platzrunden'", "'FSE-Landeflächen'",
                         "'FSE-Plätze'", "'Verkehr'"] if n in rumpf]
    stellen = [rumpf.index(n) for n in reihe]
    assert stellen == sorted(stellen), "Reihenfolge stimmt nicht: " + str(reihe)
    assert reihe[-1] == "'Verkehr'", "Verkehr gehoert ans Ende"


def test_eigener_haken_sieht_aus_wie_die_von_leaflet():
    """Im Kniebrett baut das Stylesheet die Kaestchen komplett neu (die Engine zeichnet native
    nicht brauchbar). Ohne Leaflets Klasse blieb unser Haken immer gleich -- an wie aus
    (Nutzer-Fund 16.08.2026)."""
    stelle = INDEX.index("function _schilderSchalterEinbauen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "kasten.className = 'leaflet-control-layers-selector'" in rumpf


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
    # Gezielt DEN moveend-Handler suchen, der den Verkehr abruft: Es gibt inzwischen mehrere
    # (Platzrunden- und FSE-Beschriftungen haengen ebenfalls an moveend, weil sie nur im
    # Sichtbereich gebunden werden). Ein index() auf die blosse Zeichenkette traefe den
    # erstbesten und pruefte damit die falsche Stelle.
    stelle = INDEX.index("_verkehrAbrufen(map); });")
    kontext = INDEX[max(0, stelle - 200):stelle]
    assert "map.on('moveend'" in kontext
    assert "_naviSelbstBewegt" in kontext


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
    """Sonst faengt die Fortrechnung bei jedem Abruf von vorn an und der Marker springt
    zurueck. Seit 16.08.2026 zaehlt auch eine geaenderte Geschwindigkeit als neuer Wert --
    ein anhaltendes Flugzeug behielte sonst die alte und wanderte weiter (s. dort)."""
    stelle = INDEX.index("function _verkehrZeichnen(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "alt.lat !== e.lat" in rumpf and "alt.lon !== e.lon" in rumpf
    assert "alt.gs !== neueGs" in rumpf


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


def test_eigenes_label_folgt_dem_simulator_nicht_vatsim():
    """Nutzer-Fund 16.08.2026 im Flug: Position und Kurs liefen im Sekundentakt, Hoehe und
    Geschwindigkeit sprangen daneben nur alle 15 Sekunden -- an EINEM Symbol zwei verschiedene
    Zeitstaende. Wo eine Sim-Angabe vorliegt, hat sie Vorrang; von VATSIM kommt nur, was der
    Simulator nicht weiss (Rufzeichen, Muster)."""
    stelle = INDEX.index("function _eigenesFlugzeugZeichnen(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    zweig = rumpf[rumpf.index("if (vatsimMarker) {"):]
    assert "_simPos.gs" in zweig, "Geschwindigkeit muss aus dem Simulator kommen"
    assert "_simPos.alt" in zweig, "Hoehe ebenso"
    assert "meiner ? meiner.aircraft" in zweig, "Muster kennt nur VATSIM"
    assert "setTooltipContent" in zweig, "sonst wird das Schild nie aktualisiert"


def test_eigenes_flugzeug_hat_auch_ein_label():
    """Im Sim ohne VATSIM stand am eigenen Flugzeug gar nichts -- nur ein Popup auf Klick
    (Live-Test 15.08.2026). Die Werte muessen am Symbol stehen wie bei allen anderen."""
    assert "_eigenLabel()" in INDEX, "Label wird nie gesetzt"
    stelle = INDEX.index("function _eigenLabel(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_simPos.alt" in rumpf and "_simPos.gs" in rumpf


def test_eigenes_label_traegt_keine_sonderform():
    """Am eigenen Flugzeug stand erst "DEIN FLUGZEUG", danach ein verkuerztes eigenes Label.
    Beides ist raus (Nutzer-Wahl 15.08.2026) -- es ist jetzt dasselbe Schild wie ueberall."""
    stelle = INDEX.index("function _eigenLabel(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "DEIN FLUGZEUG" not in rumpf
    assert "<span" not in rumpf, "kein eigener Zusammenbau -- das macht _verkehrLabel"


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
    rund 130 km westlich -- jedes Oeffnen begann mit Schieben.

    Seit v13.6.0 oeffnet die Karte auf dem zuletzt betrachteten Ausschnitt; EDWG ist der
    RUECKFALL, wenn keiner gemerkt ist. Geprueft wird deshalb der Rueckfall in
    _ausschnittStart -- dort, wo die Vorgabe jetzt wirklich entschieden wird.
    """
    assert "const _KARTE_MITTE = [53.78278, 7.91389];" in INDEX
    assert "center:    [54.5, 8.5]" not in INDEX

    stelle = INDEX.index("function _ausschnittStart(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "const vorgabe = { center: _KARTE_MITTE, zoom: _KARTE_ZOOM };" in rumpf
    # Jeder Abbruch in der Pruefung muss auf EDWG zurueckfallen -- ein `return null` daneben
    # gaebe Leaflet einen leeren Mittelpunkt.
    assert rumpf.count("return vorgabe;") >= 4
    assert "return null" not in rumpf


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


@ohne_panel
def test_geschwindigkeit_wird_abgeleitet_und_geglaettet():
    """GET_AIR_TRAFFIC liefert KEINE Grundgeschwindigkeit -- beide Auswerter im Simulator
    (offizielles SDK und Asobos VFR-Karte) leiten sie aus Positionsdifferenzen ab. Ungeglaettet
    zappelt die Zahl im Label bei jedem Abruf; das SDK glaettet sie ausdruecklich 'to reduce
    artifacts from potentially noisy data'."""
    stelle = PANEL_TSX.index("private verkehrGsAbleiten(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert "Math.exp" in rumpf, "keine exponentielle Glaettung"
    assert "VERKEHR_MAX_GS_KT" in rumpf, "kein Verwerfen unplausibler Werte"


@ohne_panel
def test_unplausible_geschwindigkeiten_werden_verworfen():
    """1500 kt ist die Grenze, die das offizielle SDK selbst ansetzt
    (TrafficContactClass.MAX_VALID_GROUND_SPEED). Ein Sprung in den Rohdaten ergaebe sonst
    kurz vierstellige Werte im Label."""
    m = re.search(r"const VERKEHR_MAX_GS_KT = (\d+);", PANEL_TSX)
    assert m and int(m.group(1)) == 1500


@ohne_panel
def test_stehende_flugzeuge_werden_mitgemeldet():
    """Es gab einen Filter gegen stehende Flugzeuge am Boden. Er ist raus (Nutzer-Wahl
    15.08.2026): Am Platz ist das belegte Vorfeld die Information, und ob `isOnGround`
    ueberhaupt geliefert wird, ist offen -- ein Filter, der nur manchmal greift, ist
    schlechter als keiner."""
    stelle = PANEL_TSX.index("private verkehrAufbereiten(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert "VERKEHR_STEHT_KT" not in rumpf
    assert "if (r.isOnGround" not in rumpf, "keine Entscheidung mehr an einem unsicheren Feld"
    # Weitergereicht wird es trotzdem: Solange offen ist, ob der Simulator das Feld ueberhaupt
    # liefert, ist `gnd` die einzige Spur, an der sich das ueberhaupt ablesen laesst.
    assert "gnd: r.isOnGround === true" in rumpf


@ohne_panel
def test_eigenes_flugzeug_wird_ausgefiltert():
    """Nach heutigem Stand steht es gar nicht in der Liste (Messung 6 = 6; Asobos eigene Karte
    filtert es auch nicht heraus und zeichnet trotzdem kein Doppelsymbol). Der Filter kostet
    nichts und verhindert ein zweites Symbol genau dort, wo es am meisten stoeren wuerde."""
    stelle = PANEL_TSX.index("private verkehrAufbereiten(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert "VERKEHR_EIGEN_M" in rumpf
    assert "VERKEHR_EIGEN_FT" in rumpf


@ohne_panel
def test_deckel_greift_nach_entfernung_nicht_nach_reihenfolge():
    """Die ersten 60 aus der Rohliste waeren eine beliebige Auswahl. Was zaehlt, ist Naehe --
    dieselbe Regel wie serverseitig in /api/traffic."""
    stelle = PANEL_TSX.index("private verkehrAufbereiten(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert ".sort(" in rumpf
    assert "VERKEHR_MAX" in rumpf


@ohne_panel
def test_spur_wird_aufgeraeumt():
    """Ohne Aufraeumen waechst die Map ueber einen langen Flug mit jedem Flugzeug, das je in
    Reichweite war -- und die abgeleitete Geschwindigkeit eines wiederkehrenden uId waere aus
    einer Stunde alten Daten gerechnet."""
    stelle = PANEL_TSX.index("private verkehrAufbereiten(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert "verkehrSpur.delete" in rumpf


def test_beide_quellen_zeichnen_ueber_denselben_weg():
    """Zwei Kopien derselben Markerpflege waeren zwei Orte, an denen dieselbe Hysterese, das
    Icon-Sparen und das Popup-Sparen kaputtgehen koennen. Es gibt genau einen Zeichenpunkt."""
    assert "function _verkehrZeichnen(" in INDEX
    stelle = INDEX.index("function _verkehrNeuZeichnen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_verkehrZeichnen(_verkehrZusammenfuehren())" in rumpf
    assert INDEX.count("_verkehrZeichnen(") == 2, "Aufruf nur an einer Stelle (plus Definition)"


def test_sim_schluessel_kollidiert_nicht_mit_callsigns():
    """Ein ungepaartes Sim-Flugzeug muss erkennbar eines sein -- beide Quellen legen in
    derselben Ablage ab."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "'sim:' + s.id" in rumpf


def test_jeder_eintrag_bringt_seinen_messzeitpunkt_mit():
    """Seit beide Quellen in EINER Liste stehen, geht ein gemeinsamer Zeitpunkt nicht mehr:
    Eine Sim-Meldung gilt fuer diese Sekunde, eine VATSIM-Meldung ist bis zu 15 Sekunden alt.
    Mit einem gemeinsamen Wert wuerde die eine Haelfte falsch fortgerechnet."""
    stelle = INDEX.index("function _verkehrZeichnen(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "const gemessenTs = e._ts" in rumpf
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    zus = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "e._ts = _simVerkehr.ts" in zus
    assert "e._ts = _vatsimVerkehr.gemessenTs" in zus


# --- Zusammenfuehrung beider Quellen -----------------------------------------------------
#
# Die erste Fassung liess immer nur EINE Quelle gelten. Im Flug war das sofort sichtbar
# (Nutzer-Fund 15.08.2026): Beim vPilot-Connect verschwanden Flugzeuge, die VATSIM kannte und
# der Simulator nicht -- und mit ihnen alle Rufzeichen.

def test_vatsim_wird_nicht_mehr_verdraengt():
    """Der Netzabruf laeuft weiter, auch wenn der Simulator liefert."""
    stelle = INDEX.index("function _verkehrAbrufen(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "if (_simVerkehrFrisch()) return;" not in rumpf
    assert "_verkehrQuelleWechseln" not in INDEX, "die Umschaltung ist ersatzlos entfallen"


def test_zuordnung_wird_gemerkt_nicht_je_takt_gesucht():
    """Der Kern des Umbaus. Die erste Fassung suchte in JEDEM Takt neu -- und kippte an
    Grenzfaellen (zwei Schilder an einem Airliner; ein Label, das im Sekundentakt trennt).
    Zu jedem Schwellwert gibt es einen Grenzfall; der Fehler war, die Frage ueberhaupt jede
    Sekunde neu zu stellen."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "_paarungen[s.id]" in rumpf
    assert "const gemerkt = _paarungen[s.id];" in rumpf


def test_zuordnung_gilt_nur_fuer_die_sitzung():
    """Gemessen am 16.08.2026: Die uId ueberlebt keinen Neustart (zwei Sitzungen, 14 und 20
    Kennungen, null Uebereinstimmungen). Eine dauerhaft gespeicherte Zuordnung haengte
    irgendwann ein falsches Rufzeichen an ein fremdes Flugzeug."""
    assert "let _paarungen = Object.create(null);" in INDEX
    assert "localStorage" not in INDEX[INDEX.index("let _paarungen"):INDEX.index("let _paarungen") + 400]


def test_eindeutig_heisst_deutlicher_vorsprung():
    """Zwei Fehlversuche am selben Abend zeigten, dass "genau einer innerhalb der Schranke"
    nicht taugt: Mit 400 m lagen auf dem Vorfeld mehrere im Umkreis -- nichts eindeutig, also
    keine Zuordnung. Mit 150 m fand mancher gar keinen Partner. Jede Zahl macht an anderer
    Stelle dasselbe Problem.

    Ein VERHAELTNIS hat die Schwaeche nicht: Steht das eine 20 m von seiner Meldung und das
    naechste 80 m, ist es klar -- unabhaengig von der Schranke."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "_PAARUNG_VORSPRUNG" in rumpf
    assert "kandidaten[1]._m * _PAARUNG_VORSPRUNG" in rumpf
    assert "kandidaten.sort(" in rumpf, "der naechste muss vorne stehen"
    assert "nochOffen.push(s)" in rumpf


def test_ohne_zuordnung_gewinnt_die_sim_position():
    """Die Kernvorgabe: "Es ist wichtiger zu wissen, WO sich ein anderes Flugzeug aktuell
    aufhaelt, als zu wissen wer oder was es ist." Bisher wurde bei fehlender Zuordnung BEIDES
    gezeichnet -- das namenlose Sim-Symbol und der VATSIM-Marker mit Rufzeichen. Optisch gewann
    der mit Namen, und der haengt im 15-Sekunden-Takt: genau die Umkehrung der Vorgabe."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    stelle_verdecken = rumpf.index("--- 3b.")
    verdecken = rumpf[stelle_verdecken:rumpf.index("--- 4.")]
    assert "delete frei[kandidaten[0].v.cs]" in verdecken
    assert "_paarungen" not in verdecken, "verdecken ist KEINE Zuordnung -- nichts behaupten"
    # Genau einer je unzugeordnetem Sim-Eintrag, damit die Anzahl der Symbole stimmt.
    assert "for (let i = 0; i < nochOffen.length; i++)" in verdecken


def test_ausschluss_kommt_nach_der_naehe():
    """Erst alle sicheren Zuordnungen, DANN der Ausschluss -- sonst nimmt eine schwache
    Naehe-Zuordnung einen Kandidaten weg, den der Ausschluss sicher zugeordnet haette."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "nochOffen.length === 1 && uebrigVat.length === 1" in rumpf
    assert rumpf.index("kandidaten.length === 1") < rumpf.index("uebrigVat.length === 1")


def test_schranke_wird_aus_der_geschwindigkeit_gerechnet():
    """Eine feste Zahl ist grundsaetzlich falsch: Eine C172 legt in 29 s 1,5 km zurueck, eine
    Hornet im Ueberschall 11 km (Nutzer-Einwand 16.08.2026). Die Geschwindigkeit kommt aus dem
    SIMULATOR -- aktuell, anders als die 29 s alte VATSIM-Angabe."""
    stelle = INDEX.index("function _paarungMaxM(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_VATSIM_LATENZ_S" in rumpf
    assert "s.gs" in rumpf
    assert "_PAARUNG_MIN_M" in rumpf, "sonst faende ein stehendes Flugzeug nie einen Partner"
    assert "const _PAARUNG_MAX_M" not in INDEX, "die feste Schranke ist ersetzt"


def test_latenz_steht_genau_einmal_und_ist_gemessen():
    """29 s, gemessen im Flug (Median 28,9 bei zwoelf Proben mit stabilem Kurs). Zwei Stellen
    waeren zwei Wahrheiten ueber dieselbe Groesse."""
    import re as _re
    m = _re.search(r"const _VATSIM_LATENZ_S = (\d+);", INDEX)
    assert m and int(m.group(1)) == 29
    assert INDEX.count("_VATSIM_LATENZ_S =") == 1


def test_hoehenschranke_folgt_der_sinkrate():
    """Ein sinkendes Flugzeug MUSS von seiner VATSIM-Hoehe abweichen -- 2000 ft/min ergeben
    nach 29 s 970 Fuss, das ist der Sollwert und kein Fehler. An einer festen Schranke von
    1500 ft kippte die erste Fassung (Sim FL131 gegen VATSIM FL147)."""
    stelle = INDEX.index("function _paarungMaxFt(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_simSinkrate(" in rumpf
    assert "_VATSIM_LATENZ_S" in rumpf
    assert "const _PAARUNG_MAX_FT" not in INDEX


def test_sinkrate_wird_geglaettet():
    """Bei 1 Hz ist der Rohwert zu zappelig, um eine Schranke darauf zu stuetzen -- dieselbe
    Aufgabe wie beim Ground Speed im Panel, und derselbe Weg."""
    stelle = INDEX.index("function _simHoehenSpurFortschreiben(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "Math.exp(" in rumpf


def test_geloest_wird_erst_nach_mehreren_verstoessen():
    """Nach dem Merken kann Flackern nur noch beim Loesen entstehen. Bei einem einzelnen
    Ausreisser zu loesen waere es durch die Hintertuer."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "++gemerkt.verstoesse >= _PAARUNG_LOESEN_TAKTE" in rumpf
    assert "gemerkt.verstoesse = 0" in rumpf, "eine plausible Meldung setzt den Zaehler zurueck"


def test_loesen_ist_grosszuegiger_als_zuordnen():
    """Ein zu fruehes Loesen bringt das Flackern zurueck; eine zu weite Erstzuordnung kostet
    nur Eindeutigkeit."""
    import re as _re
    a = int(_re.search(r"const _PAARUNG_FAKTOR = (\d+);", INDEX).group(1))
    b = int(_re.search(r"const _PAARUNG_LOESEN_FAKTOR = (\d+);", INDEX).group(1))
    assert b > a


def test_gepaarte_flugzeuge_erben_die_identitaet_von_vatsim():
    """Bewegung vom Simulator, Identitaet von VATSIM -- er liefert weder Rufzeichen noch
    Muster noch Flugplan."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "e.cs  = v.cs" in rumpf
    assert "e.dep = v.dep" in rumpf and "e.arr = v.arr" in rumpf
    assert "e._key = v.cs" in rumpf, "Schluessel bleibt das Callsign -- kein neuer Marker"
    assert "e.lat = " not in rumpf, "die Position muss vom Simulator bleiben"


def test_friesen_erscheinen_nicht_doppelt():
    """Der strukturelle Fehler: /api/traffic filtert die Friesen heraus (sie haben eigene
    blaue Marker), der Simulator kennt sie aber -- vPilot spawnt sie ja. Ihre Sim-Meldung fand
    nie einen Partner und wurde als namenloses graues Symbol NEBEN dem blauen gezeichnet. Am
    FriesenFlieger-Freitag stuende damit jeder Friese doppelt auf der Karte."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "_friesenAlsKandidaten()" in rumpf, "sie muessen zuordenbar sein"
    assert "if (v && v._friese) {" in rumpf, "aber nicht noch einmal gezeichnet"


def test_diagnose_zaehlt_die_geloesten_zuordnungen():
    """Am Bildschirm sieht man, DASS Rufzeichen dastehen -- aber nicht, wie oft eine Zuordnung
    dazwischen gekippt ist. Genau das waere das Flackern, und es ist die aussagekraeftigste
    Zahl der ganzen Diagnose."""
    stelle = INDEX.index("function _zuordnungDiagnose(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "geloest: _zuordnungGeloest" in rumpf
    assert "perAusschluss" in rumpf, "wie oft der Ausschluss getragen hat"
    assert "davonFriesen" in rumpf
    # Und die Rufzeichen, nicht nur die Anzahl -- erst damit laesst sich beantworten, WELCHE
    # Flugzeuge keine Live-Daten haben und warum (Nutzer-Frage 16.08.2026).
    assert "gepaartCs" in rumpf and "nurVatsimCs" in rumpf
    assert "gsFehlt" in rumpf


def test_stehendes_flugzeug_wird_nicht_weitergerechnet():
    """Nutzer-Fund 16.08.2026: "sie stehen eigentlich schon, aber werden mit VATSIM Daten
    weiterberechnet". Ein rollendes Flugzeug wird von VATSIM mit 15 kt gemeldet und haelt an.
    Der Simulator meldet ab jetzt dieselbe Position und 0 kt -- die alte Bedingung "Position
    geaendert?" schlug nie an, der VATSIM-Eintrag mit seinen 15 kt blieb liegen, und der
    Sekundentakt schob das stehende Flugzeug weiter. Am Symbol stand dabei 0."""
    stelle = INDEX.index("function _verkehrZeichnen(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "|| alt.gs !== neueGs" in rumpf


def test_kein_rueckfall_auf_die_vatsim_geschwindigkeit():
    """Eine 0 aus dem Simulator heisst, dass das Flugzeug STEHT -- der 29 Sekunden alte
    VATSIM-Wert sagt nur, dass es damals noch rollte. Ihn zu uebernehmen liesse ein stehendes
    Flugzeug ueber die Karte wandern, denn die Fortrechnung haengt an dieser Zahl."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "e.gs = v.gs" not in rumpf


def test_fehlende_geschwindigkeit_wird_mitgemessen():
    """Die Geschwindigkeit liefert der Simulator nicht -- das Panel leitet sie aus zwei
    Positionen ab. Faellt das bei einzelnen aus, steht dauerhaft 0 am Symbol, obwohl es sich
    sichtbar bewegt (Nutzer-Fund 16.08.2026). Woran es liegt, ist von der Seite aus nicht zu
    sehen; DASS es passiert, schon."""
    stelle = INDEX.index("function _simHoehenSpurFortschreiben(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_simGsFehlt[s.id]" in rumpf
    assert "delete _simGsFehlt[s.id]" in rumpf, "erholt es sich, muss der Eintrag weg"
    assert "'zuordnung'" in INDEX
    # Der Zaehler muss dort hochgehen, wo wirklich geloest wird.
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    zus = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert zus.index("_zuordnungGeloest++") > zus.index("_PAARUNG_LOESEN_TAKTE")


def test_zuordnungsdiagnose_wartet_eine_weile():
    """Sofort gemeldet waere sie wertlos: Der Zustand muss sich erst setzen. Und sie darf
    nicht vor der ERSTEN Zuordnung anfangen zu zaehlen, sonst misst sie die Ladezeit mit."""
    stelle = INDEX.index("function _zuordnungDiagnose(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_ZUORDNUNG_DIAGNOSE_NACH_MS" in rumpf
    assert "if (!_zuordnungErsteMs)" in rumpf


def test_friesen_bewegen_sich_mit_sim_position():
    """Ist ein Friese zugeordnet, bekommt SEIN Marker die Sim-Werte -- ueber _positionsRoh,
    wo der Sekundentakt liest. Mit ts=jetzt ist die Fortrechnung praktisch null."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "_positionsRoh[v.cs] = {" in rumpf
    assert "ts: _simVerkehr.ts" in rumpf
    assert "_friesenSimWerte[v.cs]" in rumpf


def test_vatsim_ruehrt_sim_gefuehrte_friesen_nicht_an():
    """Sonst setzte updateMap sie alle 15 Sekunden auf die alte Meldung zurueck -- genau das
    Zurueckspringen, das beim eigenen Flugzeug schon einmal auffiel."""
    stelle = INDEX.index("function _markerGehoertDemSim(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_friesenSimWerte[callsign]" in rumpf
    assert "_simVerkehrFrisch()" in rumpf


def test_friesen_label_zeigt_sim_hoehe_und_speed():
    """Dieselbe Regel wie ueberall: Wo eine Sim-Angabe vorliegt, hat sie Vorrang. Sonst
    staende an einem Symbol, das sich im Sekundentakt bewegt, eine Hoehe von vor einer halben
    Minute."""
    assert INDEX.count("_verkehrLabel(_mitSimWerten(p))") == 3, \
        "alle drei Stellen in updateMap -- sonst laufen sie auseinander"
    stelle = INDEX.index("function _mitSimWerten(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "Object.assign({}, p)" in rumpf, "liveData darf nicht veraendert werden"
    assert "kopie.altitude" in rumpf and "kopie.groundspeed" in rumpf


def test_sim_werte_werden_freigegeben():
    """Meldet der Simulator einen Friesen nicht mehr, muss sein Marker zurueck an den
    VATSIM-Zulauf -- sonst stuende er fuer immer auf der letzten Sim-Position."""
    stelle = INDEX.index("function _paarungenAufraeumen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "delete _friesenSimWerte[cs]" in rumpf


def test_eigenes_flugzeug_ist_kein_friesen_kandidat():
    """Es hat seinen eigenen Weg (_eigenesFlugzeugZeichnen) und wird vom Panel ohnehin aus
    der Sim-Liste gefiltert."""
    stelle = INDEX.index("function _friesenAlsKandidaten(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_meineCid" in rumpf
    assert "_jetztGerechnet(" in rumpf, "auch die Friesen-Position ist 15 s alt"


def test_nur_von_vatsim_gekannte_flugzeuge_bleiben_stehen():
    """Der Fall, der den Umbau ausgeloest hat: vPilot spawnt nicht jedes Flugzeug."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "if (!v.cs || !frei[v.cs]) continue;" in rumpf


def test_ein_vatsim_flugzeug_wird_nur_einmal_vergeben():
    """Ohne die Freiliste koennten zwei Sim-Meldungen dasselbe Rufzeichen tragen."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert rumpf.count("delete frei[") >= 3, "gehalten, erstzugeordnet und per Ausschluss"
    stelle = INDEX.index("function _verkehrKandidaten(")
    such = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "if (!frei[e.v.cs]) continue;" in such


def test_zuordnungen_werden_aufgeraeumt():
    """Ohne das wuechsen beide Ablagen ueber einen langen Flug hinweg unbegrenzt."""
    stelle = INDEX.index("function _paarungenAufraeumen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "delete _paarungen[id]" in rumpf
    assert "delete _simHoehenSpur[id]" in rumpf


def test_paarung_vergleicht_gegen_die_fortgerechnete_position():
    """Verglichen wird gegen die Stelle, an der das Flugzeug JETZT steht -- dieselbe, an der
    auch der Marker gezeichnet wird."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "_jetztGerechnet(" in rumpf
    assert rumpf.index("vatJetzt.push") < rumpf.index("_verkehrKandidaten(")
    stelle = INDEX.index("function _verkehrKandidaten(")
    such = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "p.distanceTo([e.lat, e.lon])" in such


def test_popup_bleibt_lesbar_ohne_callsign():
    """Der Simulator liefert nach heutigem Stand keinen Callsign. Eine leere fette Zeile ganz
    oben im Popup waere ein sichtbarer Fehler."""
    stelle = INDEX.index("function _verkehrPopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "Verkehr" in rumpf


def test_schalter_wird_an_die_shell_gemeldet():
    assert "art: 'verkehr-schalter'" in INDEX
    stelle = INDEX.index("function _setupVerkehrPref(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_verkehrSchalterMelden" in rumpf


def test_schalter_wird_auch_ohne_klick_gemeldet():
    """Eine gespeicherte Praeferenz schaltet die Ebene beim Aufbau ein, ohne dass jemand
    klickt -- overlayadd feuert dabei nicht. Ohne diese Meldung bliebe das Panel stumm, und
    der Nutzer saehe eine eingeschaltete Ebene ohne Verkehr."""
    stelle = INDEX.index("function _addPreferredVerkehrLayer(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_verkehrSchalterMelden" in rumpf


def test_diagnose_meldet_genau_einmal():
    """Eine Meldung je Sekunde waere kein Befund, sondern eine Flut."""
    stelle = INDEX.index("function _simVerkehrDiagnoseEinmal(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_simVerkehrDiagnoseGemeldet" in rumpf


def test_diagnose_meldet_die_werte_nicht_nur_die_feldnamen():
    """Die alte Sonde meldete nur Object.keys -- damit blieb offen, WAS in `name` und
    `plane_model_icao` steht, und genau davon haengt Teilprojekt 2b ab."""
    stelle = INDEX.index("function _simVerkehrDiagnoseEinmal(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "ersterEintrag" in rumpf
    assert "_diagnoseMitVergleichMelden('sim-verkehr'" in rumpf


def test_sim_verkehr_wird_empfangen():
    assert "d.art === 'sim-verkehr'" in INDEX


def test_doppelte_symbole_verhindert_die_paarung_statt_eines_abbruchs():
    """Frueher brach der Netzabruf ab, solange der Simulator lieferte -- damit jedes Flugzeug
    nur einmal erscheint. Das kostete zu viel (s. Abschnitt "Zusammenfuehrung"). Die Aufgabe
    uebernimmt jetzt die Paarung: Ein VATSIM-Eintrag, der zu einer Sim-Meldung gehoert, wird
    nicht ein zweites Mal gezeichnet."""
    stelle = INDEX.index("function _verkehrZusammenfuehren(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "delete frei[v.cs]" in rumpf, "ein zugeordnetes Callsign ist vergeben"
    assert "if (!v.cs || !frei[v.cs]) continue;" in rumpf
    # Und die Frischewache entscheidet nur noch, ob die Sim-Liste ueberhaupt zaehlt.
    assert "_simVerkehrFrisch()" in INDEX[stelle:stelle + 400]


def test_verschwundene_flugzeuge_raeumen_sich_selbst_ab():
    """Es gab dafuer ein Leeren beim Quellwechsel. Ohne Wechsel braucht es das nicht mehr --
    was nicht mehr gemeldet wird, faellt ueber die vorhandene Hysterese heraus, und zwar
    einzeln statt alles auf einmal."""
    stelle = INDEX.index("function _verkehrZeichnen(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "_verkehrFehlt" in rumpf


def test_frischewache_benutzt_dieselbe_grenze_wie_die_position():
    """Zwei Grenzen fuer dieselbe Bruecke waeren zwei Wahrheiten darueber, ob der Simulator
    noch da ist."""
    stelle = INDEX.index("function _simVerkehrFrisch(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_SIM_POS_MAX_ALTER_MS" in rumpf


# --- Geparkte Flugzeuge -----------------------------------------------------------------
#
# Es gab hier eine Sonderbehandlung: Stehende am Boden erschienen erst ab Zoomstufe 13 und
# trugen kein Schild. Sie ist am 15.08.2026 komplett entfernt worden (Nutzer-Wahl), nachdem
# sie im Flug wirkungslos blieb -- ob ein Eintrag am Boden steht, laesst sich aus den
# vorliegenden Daten nicht verlaesslich sagen. Die Tests halten jetzt fest, dass die
# Sonderbehandlung WEG ist: Ohne sie waere die naechste Sitzung versucht, sie wieder
# einzubauen, weil das Argument dafuer nach wie vor plausibel klingt.

def test_keine_zoomschwelle_fuer_geparkte():
    """Die Schwelle ist raus -- samt der Meldung an das Panel, die an ihr hing."""
    assert "_VERKEHR_GEPARKT_AB_ZOOM" not in INDEX
    assert "_verkehrIstGeparkt" not in INDEX
    assert "_verkehrSchalterNachziehen" not in INDEX


def test_schalter_meldet_nur_noch_an_und_aus():
    """Der Rueckkanal traegt genau eine Aussage: Ist die Ebene an? Alles Weitere entschied
    ueber geparkte Flugzeuge und ist mit ihnen entfallen."""
    stelle = INDEX.index("function _verkehrSchalterMelden(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "an: !!an" in rumpf
    assert "geparkt" not in rumpf


def test_jedes_flugzeug_traegt_sein_schild():
    """Auch das geparkte auf dem Vorfeld. Ein Marker ohne Tooltip kam nur aus der entfernten
    Sonderbehandlung -- gibt es sie nicht mehr, gibt es auch kein unbindTooltip."""
    stelle = INDEX.index("function _verkehrZeichnen(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "const beschriftung = _verkehrLabel(e);" in rumpf
    assert "unbindTooltip" not in rumpf


@ohne_panel
def test_panel_filtert_nicht_nach_bodenstatus():
    """Der Filter im Panel haing an `isOnGround`. Ob der Simulator das Feld ueberhaupt
    liefert, ist offen -- deshalb faellt hier keine Entscheidung mehr daran."""
    assert "verkehrGeparkt" not in PANEL_TSX
    assert "VERKEHR_STEHT_KT" not in PANEL_TSX


# --- Vorbedingung fuer GET_AIR_TRAFFIC ---------------------------------------------------
#
# Der teuerste Fehler dieses Teilprojekts: Die Messsonde meldete am 15.08.2026 um 10:33 UTC
# sechs Flugzeuge (`viewListener: "angemeldet"`, `typ: "[object Array]"`, `anzahl: 6`), weil
# sie VOR dem Aufruf den Karten-Listener anmeldete. Beim Ausbau der Sonde ist die Messfunktion
# verschwunden -- und diese Vorbedingung mit ihr, ohne dass sie in den Produktivcode kam.
# Danach lieferte GET_AIR_TRAFFIC lautlos nichts mehr.

@ohne_panel
def test_karten_listener_wird_vor_dem_abruf_angemeldet():
    """Ohne angemeldeten Listener existiert die Datenquelle fuer diese View nicht."""
    assert 'rvl("JS_LISTENER_MAPS")' in PANEL_TSX
    assert '"JS_BIND_BINGMAP"' in PANEL_TSX
    stelle = PANEL_TSX.index("private async verkehrHolen(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert rumpf.index("this.kartenListenerAnmelden()") < rumpf.index("GET_AIR_TRAFFIC"), \
        "die Anmeldung muss VOR dem Aufruf stehen"


@ohne_panel
def test_fehlversuch_bei_der_anmeldung_ist_nicht_endgueltig():
    """Der Merker darf nur bei Erfolg fallen -- sonst haengt eine ganze Sitzung an einem
    einzigen zu fruehen Versuch."""
    stelle = PANEL_TSX.index("private kartenListenerAnmelden(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert rumpf.count("this.kartenListenerDa = true") == 1
    assert rumpf.index("l.trigger") < rumpf.index("this.kartenListenerDa = true")


@ohne_panel
def test_erster_abruf_wird_gemeldet_auch_wenn_er_leer_bleibt():
    """Das Ausbleiben ist die interessanteste Meldung von allen -- sie fehlte genau dann, als
    sie gebraucht wurde."""
    stelle = PANEL_TSX.index("private async verkehrSenden(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert rumpf.index("this.startBefundSenden(ziel)") < rumpf.index("if (roh === null)"), \
        "der Befund muss raus, bevor ueber die Liste entschieden wird"


def test_startbefund_landet_in_der_diagnose():
    assert "d.art === 'sim-verkehr-start'" in INDEX
    assert "_diagnoseMitVergleichMelden('sim-verkehr-start'" in INDEX


# --- Schalter fuer die Schilder ----------------------------------------------------------

def test_schilder_schalter_sitzt_unter_der_verkehrsebene():
    """Ein zweiter Haken, eingehaengt unter dem der Verkehrs-Ebene. Leaflet sieht dafuer
    nichts vor -- die Ebenen-Auswahl kennt nur Ebenen."""
    stelle = INDEX.index("function _schilderSchalterEinbauen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "'Verkehr'" in rumpf, "der Anker ist der Eintrag der Verkehrs-Ebene"
    assert "insertBefore" in rumpf and "nextSibling" in rumpf, "muss DARUNTER landen"
    assert "_saveSchilderPref" in rumpf and "_schilderAnwenden" in rumpf


def test_schilder_schalter_ueberlebt_den_neuaufbau_der_liste():
    """Leaflets Ebenen-Auswahl baut ihre Liste bei jeder Layer-Aenderung per innerHTML neu --
    alles Fremde ist danach fort. Einmal einhaengen genuegt also nicht (Nutzer-Fund
    15.08.2026: kurz gesehen, dann weg). `_update` wird deshalb umhuellt."""
    stelle = INDEX.index("function _schilderSchalterAnhaengen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "control._update = function" in rumpf
    assert "original.call(this)" in rumpf, "das Original muss zuerst laufen"
    assert rumpf.index("original.call(this)") < rumpf.index("_schilderSchalterEinbauen(map, this)")
    assert "_schilderSchalterAnhaengen(liveMap, liveEbenen)" in INDEX, "sonst greift nichts davon"


def test_schilder_haken_heisst_in_der_oberflaeche_radar_label():
    """Nutzer-Wahl 15.08.2026. Im Quelltext heisst dieselbe Sache weiter "Schilder" -- der
    Anzeigename steht deshalb genau an einer Stelle."""
    assert "' Radar Label'" in INDEX
    assert "' Schilder'" not in INDEX


def test_schilder_schalter_verschwindet_mit_der_verkehrsebene():
    """Ein Unterpunkt zu einer abgeschalteten Ebene hat nichts zu sagen (Nutzer-Wunsch
    15.08.2026). Leaflet ruft bei einem Klick IN der Auswahl absichtlich kein _update, die
    Umhuellung greift hier also nicht -- es braucht die eigene Nachfuehrung."""
    stelle = INDEX.index("function _schilderSchalterSichtbarkeit(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "map.hasLayer(_verkehrGruppe)" in rumpf
    assert "style.display" in rumpf
    stelle = INDEX.index("function _setupVerkehrPref(")
    setup = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert setup.count("_schilderSchalterSichtbarkeit(map)") == 2, \
        "an UND aus muessen nachziehen"


def test_schilder_schalter_haengt_sich_nicht_doppelt_ein():
    """Die Einbau-Funktion laeuft jetzt nach JEDEM Neuaufbau -- ohne Wache staende dort
    irgendwann eine Reihe gleicher Kaestchen."""
    stelle = INDEX.index("function _schilderSchalterEinbauen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "querySelector('.ebenen-unterpunkt')" in rumpf


def test_leere_sim_liste_verdraengt_vatsim_nicht():
    """Eine leere Liste ist eine gueltige Antwort des Simulators (allein am Himmel, vPilot
    noch nicht verbunden). Sie als Quelle zu werten hiess: VATSIM weg, nichts gezeichnet,
    Karte leer -- waehrend die Webseite daneben Verkehr zeigte (Nutzer-Fund 15.08.2026)."""
    stelle = INDEX.index("function _simVerkehrFrisch(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_simVerkehrLetzteMitInhalt" in rumpf
    assert "_simVerkehr &&" not in rumpf, "die blosse Meldung reicht nicht mehr"
    # Und der Empfaenger darf eine leere Liste gar nicht erst als Lieferung werten.
    stelle = INDEX.index("if (d.art === 'sim-verkehr')")
    zweig = INDEX[stelle:stelle + 700]
    assert zweig.index("if (!liste.length) return;") < zweig.index("_simVerkehrLetzteMitInhalt = Date.now()")


def test_schilder_schalter_faellt_weich_aus():
    """Findet er seinen Anker nicht (andere Leaflet-Fassung, umbenannte Ebene), darf die Karte
    davon nichts merken -- ein fehlender Zusatzhaken ist kein Grund, die Karte zu verlieren."""
    stelle = INDEX.index("function _schilderSchalterEinbauen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "if (!anker" in rumpf
    assert "if (!control" in rumpf


def test_schilder_sind_standardmaessig_an():
    """Anders als die uebrigen Merker: "noch nie entschieden" heisst hier AN, denn die
    Schilder sind die Aussage der Ebene."""
    stelle = INDEX.index("function _loadSchilderPref(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "!== '0'" in rumpf, "nur ein ausdrueckliches Aus schaltet sie ab"


def test_schilder_werden_ueber_css_ausgeblendet():
    """Nicht ueber unbindTooltip: Der Haken soll sofort wirken, nicht erst beim naechsten
    Zulauf -- und ein neu dazukommendes Flugzeug hat den Zustand automatisch richtig."""
    assert ".leaflet-container.ohne-verkehrsschilder .traffic-label-fremd { display: none; }" in INDEX
    assert "classList.add('ohne-verkehrsschilder')" in INDEX
    assert "classList.remove('ohne-verkehrsschilder')" in INDEX


def test_nur_fremder_verkehr_verliert_seine_schilder():
    """Die eigene Maschine und die Friesen sind die Aussage der Karte -- sie behalten ihr
    Schild, sonst blendete der Haken mehr aus, als sein Platz in der Liste verspricht."""
    assert INDEX.count("traffic-label traffic-label-fremd") == 1
    stelle = INDEX.index("function _eigenesFlugzeugZeichnen(")
    rumpf = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "traffic-label-fremd" not in rumpf


def test_windanzeige_nur_im_kniebrett_und_richtungstreu():
    """Windpfeil mit Geschwindigkeit (Nutzerwunsch 23.08.2026).

    Der Wind kommt aus dem Simulator; VATSIM kennt ihn nicht. Deshalb wird die Anzeige nur
    im Panel angemeldet und verschwindet, sobald keine Sim-Meldung mehr da ist.

    Die beiden Richtungen sind der heikle Teil: Die Luftfahrt nennt die Richtung, AUS der
    der Wind kommt ("270/15"), ein Pfeil zeigt aber, WOHIN er weht. Deshalb +180 am Pfeil
    und die unveraenderte Zahl im Text. Zusaetzlich das Bearing, sonst zeigt der Pfeil bei
    gedrehter Karte in die Irre."""
    assert "function _addWindControl(map)" in INDEX
    assert "if (_PANEL_MODUS) _addWindControl(liveMap);" in INDEX, \
        "die Anzeige darf nur im Kniebrett entstehen -- auf der Website gibt es keinen Wind"

    m = re.search(r"function _windAnzeigen\(\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_windAnzeigen nicht gefunden"
    rumpf = m.group(1)
    assert "ri + 180 + bearing" in rumpf, \
        "Pfeil muss die Wehrichtung zeigen (+180) und die Kartendrehung beruecksichtigen"
    # Windstille hat keine sinnvolle Richtung -- eine anzuzeigen waere erfunden.
    assert "'still'" in rumpf
    assert "_windKnopf.classList.toggle('navi-weg', !frisch)" in rumpf, \
        "ohne Sim-Meldung muss die Anzeige verschwinden"

    # Die Pfeilspitze zeigt im ungedrehten Zustand nach OBEN. Andersherum stuende die ganze
    # Drehung um 180 Grad daneben -- an den Zahlen nicht zu sehen, nur am Bild.
    assert 'd="M12 2.5 L7.4 8.8 L12 6.9 L16.6 8.8 Z"' in INDEX


def test_windanzeige_steht_immer_oben_links_ueber_dem_zoom():
    """Ein fester Ort in beiden Zustaenden (Nutzerwunsch 02.09.2026) -- die Anzeige springt
    beim Umschalten nicht mehr durchs Bild.

    Sie WANDERTE zweimal, und beide Gruende sind entfallen: erst nach unten links, weil dort
    im Kniebrett-Vollbild Platz war (der Vollbild-Knopf war ausgeblendet), dann nach oben
    rechts, weil der Knopf als Ausgang dorthin zurueckkam.

    Das Umhaengen INNERHALB der Ecke bleibt noetig: Leaflet stapelt die Bedienelemente in der
    Reihenfolge, in der sie dazukommen, und der Zoomknopf entsteht schon beim Anlegen der
    Karte -- ohne insertBefore saesse der Wind darunter."""
    m = re.search(r"function _windPlatzieren\(\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_windPlatzieren nicht gefunden"
    rumpf = m.group(1)
    assert "_windControl.setPosition('topleft')" in rumpf
    assert "bottomleft" not in rumpf and "topright" not in _ohne_kommentare(rumpf)
    assert "ecke.insertBefore(_windKnopf, ecke.firstChild)" in rumpf, \
        "ohne Umhaengen sitzt die Anzeige UNTER den Zoomknoepfen"
    assert "if (wrapId === _ZUSTAND_KARTE_WRAP) _windPlatzieren();" in INDEX, \
        "der Vollbild-Wechsel muss die Anzeige mitnehmen"


def test_windanzeige_bleibt_bei_ascii():
    """Coherent GT malt nichts jenseits von ASCII -- ein Gradzeichen wurde im Kniebrett zum
    leeren Kaestchen ("038[] 6 kt", Nutzer-Bild 23.08.2026). Die Schreibweise "038/6 kt"
    kommt ohne aus und ist die, die man vom Wetterbericht kennt."""
    m = re.search(r"function _windRiText\(ri\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_windRiText nicht gefunden"
    assert "\u00b0" not in m.group(1), "das Gradzeichen ist im Kniebrett ein leeres Kaestchen"
    # Keine Einheiten: Das Gradzeichen kann das Kniebrett nicht malen, und "kt" allein
    # waere halb beschriftet (Nutzer, 23.08.2026). "036/8" ist die uebliche Schreibweise.
    assert "_windRiText(ri) + '/' + kt)" in INDEX
    w = re.search(r"function _windAnzeigen\(\) \{(.*?)\n\}", INDEX, re.S)
    assert w, "_windAnzeigen nicht gefunden"
    assert "' kt'" not in w.group(1), "die Windanzeige darf keine halbe Beschriftung tragen"


def test_die_herkunftsangabe_wird_verdeckt_aber_nie_ausgeblendet():
    """Unten links laeuft Leaflets Herkunftsangabe entlang, die im Kniebrett ueber die volle
    Breite umbricht. Was dort steht, muss vor ihr liegen: bis 02.09.2026 die Windanzeige
    (Nutzer-Bild 23.08.2026), seither der Vollbild-Knopf als Ausgang aus dem Vollbild.

    Der Weg dorthin ist je nach Element ein anderer: Bei einem Kind einer Leaflet-Ecke muss
    die ECKE angehoben werden -- Leaflet gibt jeder `z-index: 1000` und macht damit einen
    eigenen Stapel-Zusammenhang auf, ein hoeherer Wert am Kind bliebe wirkungslos. Der
    Vollbild-Knopf haengt dagegen als `position:absolute` am Karten-Wrapper, ausserhalb des
    Ecken-Rasters, und traegt seinen Rang selbst.

    Die Namensnennung SELBST bleibt in jedem Fall: Sie ist Lizenzbedingung der Kartenquellen
    und wird nirgends ausgeblendet -- verdeckt wird immer nur der Platz des eigenen Kastens,
    der uebrige Text bleibt stehen."""
    assert "html.vr-panel .map-is-fullscreen .map-fullscreen-btn { z-index: 1050; }" in INDEX, \
        "zwischen Herkunftsangabe (1000) und Ebenen-Auswahl (1100)"
    assert "display: none" not in _regel_von(".leaflet-control-attribution"), \
        "die Herkunftsangabe darf nicht verschwinden -- sie ist Lizenzbedingung"


def _regel_von(selektor):
    """Rumpf der ersten CSS-Regel zu diesem Selektor (fuer Pruefungen wie oben)."""
    m = re.search(re.escape(selektor) + r"\s*\{([^}]*)\}", INDEX, re.S)
    return m.group(1) if m else ""


# ==========================================================================================
#  Erreichbarkeit der Ebenen-Auswahl messen (Nutzer-Fund 30.08.2026)
# ==========================================================================================
#
# "Ich konnte das AIP Layer nicht im Tablet aktivieren -- die Checkbox liess sich nicht
# anklicken." Getroffen hat es OpenAIP, den OBERSTEN Overlay-Eintrag; Platzrunden, Meldepunkte
# und die FSE-Ebenen (Plaetze 3 bis 6) gingen im selben Zeitraum nachweislich an. Die
# vorhandene Diagnose haelt fest, WELCHE Haken gesetzt sind -- nicht, ob eine Zeile ueberhaupt
# erreichbar ist. Die beiden plausiblen Ursachen (etwas liegt darueber / die Liste scrollt und
# die Zeile steht ausserhalb) sehen dort identisch aus.

def _rumpf_diag_ebenen() -> str:
    """Nur den Funktionsrumpf, ohne die Kommentare davor.

    Freie Zeichenkettensuche ueber INDEX faende sonst die Begruendung im Kommentarblock statt
    der Messung selbst -- die Tests waeren gruen, ohne dass die Funktion irgendetwas tut.
    """
    stelle = INDEX.index("function _diagEbenenAuswahl(")
    return INDEX[stelle:INDEX.index("\n}\n", stelle)]


def test_ebenen_diagnose_misst_was_der_tipp_wirklich_trifft():
    """Der Kern: `elementFromPoint` auf den Mittelpunkt jedes Kaestchens. Ohne diese Messung
    bleibt "verdeckt" von "nicht da" ununterscheidbar."""
    rumpf = _rumpf_diag_ebenen()
    assert "document.elementFromPoint(" in rumpf
    assert "erreichbar:" in rumpf
    # Bei einem Treffer daneben MUSS der Uebeltaeter benannt werden, sonst weiss man nur,
    # dass es klemmt, aber nicht woran.
    assert "davor:" in rumpf


def test_ebenen_diagnose_trennt_verdeckt_von_nicht_gerendert():
    """Eine Zeile mit Rechteck 0x0 ist gar nicht gezeichnet -- ein anderer Fall als "verdeckt"
    und aus elementFromPoint allein nicht zu erkennen."""
    rumpf = _rumpf_diag_ebenen()
    assert "gerendert:" in rumpf


def test_ebenen_diagnose_haelt_den_scrollstand_fest():
    """Die zweite Erklaerung: Die Liste ist laenger als die Karte hoch ist (s. CSS bei
    .leaflet-control-layers-expanded) und die Zeile steht ausserhalb des Fensters. Genau diese
    Falle gab es hier schon einmal (Radar Label, 24.08.2026)."""
    rumpf = _rumpf_diag_ebenen()
    assert "scrollt:" in rumpf
    assert "scrollTop" in rumpf


def test_ebenen_diagnose_haengt_am_aufklappen_nicht_am_kartenaufbau():
    """Vor dem Aufklappen hat die Liste weder Groesse noch Position -- dort gemessen waere
    jedes Rechteck 0. Leaflet feuert dafuer kein Ereignis, also wird die Aufklapp-Methode
    umhuellt (dasselbe Muster wie bei `_update` in _schilderSchalterAnhaengen)."""
    rumpf = _rumpf_diag_ebenen()
    assert "control.expand" in rumpf
    assert "original.apply(this, arguments)" in rumpf


def test_ebenen_diagnose_haengt_an_expand_nicht_an_unterstrich_expand():
    """Der erste Anlauf am 30.08.2026 griff `control._expand` und erzeugte NULL Meldungen:
    Leaflet 1.9.4 hat diese Methode nicht. Aufgeklappt wird ueber `_expandSafely()` (Touch)
    bzw. `_expandIfNotCollapsed()`, und beide rufen die oeffentliche `expand()`.

    Der Test bindet an das Fehlen des Unterstrichs, weil genau dieser Tippfehler die Messung
    lautlos abschaltet -- der Wachposten steigt aus, und von aussen sieht alles normal aus."""
    rumpf = _rumpf_diag_ebenen()
    assert "control._expand" not in rumpf


def test_ebenen_diagnose_meldet_wenn_sie_selbst_nicht_greift():
    """Lehre aus demselben Fehlgriff: Ein stiller `return` verbirgt, dass die Messung gar
    nicht laeuft. Fehlt die erwartete Methode, gehoert das gemeldet."""
    rumpf = _rumpf_diag_ebenen()
    stelle = rumpf.index("typeof control.expand !== 'function'")
    assert "ebenen-auswahl-fehler" in rumpf[stelle:stelle + 600]


def test_ebenen_diagnose_nur_im_kniebrett_und_gedeckelt():
    """Auf der Website zeichnet der Browser die Kaestchen ohnehin korrekt; und Auf-/Zuklappen
    ist im Cockpit ein haeufiger Handgriff -- ohne Deckel verstopft die Tabelle."""
    rumpf = _rumpf_diag_ebenen()
    assert "'vr-panel'" in rumpf
    assert "anzahl >= " in rumpf


def test_ebenen_diagnose_laeuft_nach_dem_zusatzhaken():
    """Die Messung zaehlt die Zeilen der FERTIGEN Liste. Vor _schilderSchalterAnhaengen fehlte
    "Radar Label" -- und ausgerechnet der Zusatzhaken ist der einzige Eintrag, den nicht
    Leaflet selbst setzt."""
    assert (INDEX.index("_schilderSchalterAnhaengen(liveMap, liveEbenen)")
            < INDEX.index("_diagEbenenAuswahl(liveMap, liveEbenen)"))


# ==========================================================================================
#  Die Positionsbruecke darf nicht endgueltig aufgeben (Nutzer-Fund 30.08.2026)
# ==========================================================================================
#
# Im Flug fehlten das eigene Flugzeug, der Kompass, der Zentrieren-Knopf und die Windanzeige.
# Alle vier haengen an der Eigenposition (`navi-weg`), und die kam nicht an: `simPositionDa:
# false`, `quelle: "keine"` -- bei gleichzeitig `shellAntwortet: true` und `viewListener:
# "angemeldet"`, weil Ping/Pong und der Verkehrsteil ueber andere Pfade laufen.
#
# Ursache in der alten Fassung: Fehlte `SimVar` beim ERSTEN Versuch, setzte die App
# `positionFehler = POSITION_MAX_FEHLER`, und `positionTakt` stieg fuer die restliche Sitzung
# aus. Zurueckgesetzt wurde der Zaehler nur bei einem erfolgreichen Senden -- das danach nie
# wieder stattfand.
#
# Das ist kein Randfall: **Das Kniebrett startet automatisch mit dem Flug**, die erste Abfrage
# faellt also regelmaessig mitten ins Laden. Der Nutzer hat keinen Handgriff, das zu umgehen;
# eine Empfehlung "erst laden, dann oeffnen" geht ins Leere.

def _ohne_kommentare(text: str) -> str:
    """Zeilen- und Blockkommentare entfernen.

    Noetig, weil die verbotene Zuweisung in der ERKLAERUNG steht, warum sie verboten ist
    ("FRUEHER stand hier ..."). Eine freie Suche findet den Kommentar statt des Codes und
    laesst den Test scheitern, obwohl der Code stimmt -- beim ersten Anlauf genau so passiert.
    """
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


@ohne_panel
def test_positionsbruecke_gibt_bei_fehlendem_simvar_nicht_endgueltig_auf():
    """Der Kern des Fehlers: `SimVar` fehlt beim Autostart NOCH, es gibt es nicht etwa gar
    nicht. Wer hier wieder auf das Maximum setzt, schaltet die Bruecke fuer den ganzen Flug ab."""
    stelle = PANEL_TSX.index("private positionSenden(")
    rumpf = _ohne_kommentare(PANEL_TSX[stelle:PANEL_TSX.index("\n  private ", stelle + 10)])
    assert "typeof sv.GetSimVarValue" in rumpf
    assert "positionFehler = POSITION_MAX_FEHLER" not in rumpf
    assert "this.positionFehlgriff(" in rumpf


@ohne_panel
def test_positionstakt_pausiert_statt_zu_enden():
    """`positionTakt` muss aus der Sperre wieder herausfinden -- ohne diesen Weg bleibt der
    Zaehler auf dem Maximum stehen, denn zurueckgesetzt wird er nur beim Senden."""
    stelle = PANEL_TSX.index("private positionTakt(")
    rumpf = _ohne_kommentare(PANEL_TSX[stelle:PANEL_TSX.index("\n  /** @inheritdoc */", stelle)])
    assert "POSITION_PAUSE_MS" in rumpf
    # Der Ausweg: nach der Pause faellt der Zaehler und es wird erneut versucht.
    assert "this.positionFehler = 0" in rumpf


@ohne_panel
def test_positionsbruecke_meldet_ihren_ausfall():
    """Der eigentliche Fortschritt. Vorher war von aussen nicht zu unterscheiden, ob der
    Simulator nichts liefert oder ob gar nicht mehr gefragt wird -- beide Male stand in der
    Diagnose nur `simPositionDa: false`."""
    stelle = PANEL_TSX.index("private positionFehlgriff(")
    rumpf = _ohne_kommentare(PANEL_TSX[stelle:PANEL_TSX.index("\n  private ", stelle + 10)])
    assert "positionZustandMelden(" in rumpf
    assert "positionAusfallGemeldet" in rumpf   # nur EINMAL, sonst flutet es die Diagnose
    assert '"position-bruecke"' in PANEL_TSX


@ohne_panel
def test_paketversion_gehoben_und_gleichlaufend():
    """Die Seite entscheidet an der Paketversion, was das Kniebrett kann. Weicht sie vom
    Manifest ab, meldet die App eine Fassung, die sie nicht ist."""
    import json
    from pathlib import Path
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "msfs-panel" / "PackageSources" / "FriesenSpy"
         / "manifest.json").read_text(encoding="utf-8"))
    assert 'const PAKET_VERSION = "2.2.0"' in PANEL_TSX
    assert manifest["package_version"] == "2.2.0"


def test_seite_nimmt_den_brueckenzustand_entgegen():
    """Ohne diesen Zweig verpufft die neue Meldung der App und landet nie in panel_diag."""
    assert "d.art === 'position-bruecke'" in INDEX
    stelle = INDEX.index("d.art === 'position-bruecke'")
    assert "_panelDiag('position-bruecke'" in INDEX[stelle:stelle + 400]


def test_ebenen_diagnose_haelt_elementFromPoint_streng():
    """Der erste Anlauf hatte `oben.contains(label)` in der Bedingung und meldete deshalb
    ausnahmslos alles als erreichbar (Messung 30.08.2026: 13 von 13, darunter eine Zeile
    zehn Pixel unterhalb des Kastens). Liefert elementFromPoint einen VORFAHREN -- der
    Normalfall, wenn dort nichts Eigenes liegt --, ist die Bedingung immer wahr.

    Kommentare werden gefiltert: Die verbotene Bedingung steht in der Erklaerung, warum sie
    verboten ist. Dieselbe Falle wie bei der Positionsbruecke -- zweimal am selben Tag."""
    rumpf = _ohne_kommentare(_rumpf_diag_ebenen())
    assert "label.contains(oben)" in rumpf
    assert "oben.contains(label)" not in rumpf


def test_ebenen_diagnose_prueft_das_fenster_der_liste_getrennt():
    """Eine ausgescrollte Zeile ist weder verdeckt noch ungerendert -- elementFromPoint allein
    kann sie nicht melden. Genau diese Falle gab es hier schon (Radar Label, 24.08.2026)."""
    rumpf = _rumpf_diag_ebenen()
    assert "imFenster:" in rumpf


# ==========================================================================================
#  Warum ein installiertes Kniebrett nicht in der Geraeteliste auftaucht (Fund 30.08.2026)
# ==========================================================================================
#
# Ein Mitglied hatte das Kniebrett nachweislich installiert und benutzt (Coherent GT,
# `shellAntwortet: true`, eigene Panel-Merker), stand aber nie in `panel_devices` und musste
# sich bei jedem Start neu anmelden: zehn `/auth/forum/callback` in den Logs, kein einziges
# `/auth/device`. Ursache war ein doppelt stiller Rueckfall -- `getOrCreateDeviceId` gab im
# Fehlerfall "" zurueck, `buildPanelUrl` nahm daraufhin die Adresse ohne Bindung. Von aussen
# war "Datenspeicher schlaegt fehl" nicht von "Paket zu alt" zu unterscheiden.

@ohne_panel
def test_geraete_id_haelt_ihren_fehlgrund_fest():
    """Ein leerer Rueckgabewert allein sagt nicht, WARUM es keine Kennung gibt."""
    stelle = PANEL_TSX.index("function getOrCreateDeviceId(")
    rumpf = _ohne_kommentare(PANEL_TSX[stelle:PANEL_TSX.index("\n}", stelle)])
    assert "geraeteIdGrund =" in rumpf


@ohne_panel
def test_geraete_id_prueft_ob_der_speicher_sie_annimmt():
    """`DataStore.set` meldet keinen Fehler, wenn nichts ankommt -- ohne Gegenprobe hiesse
    "kein Fehler" faelschlich "gespeichert", und der Nutzer meldet sich ewig neu an."""
    stelle = PANEL_TSX.index("function getOrCreateDeviceId(")
    rumpf = _ohne_kommentare(PANEL_TSX[stelle:PANEL_TSX.index("\n}", stelle)])
    assert rumpf.count("DataStore.get") >= 2


@ohne_panel
def test_pong_meldet_den_grund_mit():
    """Der Grund muss die App verlassen, sonst liegt er im Simulator und niemand sieht ihn."""
    assert "geraeteIdGrund: geraeteIdGrund" in PANEL_TSX


def test_seite_legt_fehlende_bindung_in_der_diagnose_ab():
    """Ohne diesen Zweig verpufft die Meldung der App."""
    assert "'geraet-ohne-bindung'" in INDEX
    stelle = INDEX.index("d.geraeteIdGrund")
    assert "_panelDiag('geraet-ohne-bindung'" in INDEX[stelle:stelle + 500]


def test_ebenen_diagnose_warnt_vor_elementFromPoint_im_kniebrett():
    """Messreihe 30.08.2026: Coherent GT liefert an JEDEM Punkt der aufgeklappten Liste
    `DIV#leaflet-map` statt des Labels -- in allen 13 Zeilen, bei jedem Scrollstand. Streng
    gelesen hiesse das "keine Zeile bedienbar", waehrend der Nutzer gerade Ebenen schaltete.

    Der Hinweis muss am Code stehen, sonst wertet der naechste Leser `erreichbar` aus und
    zieht daraus den genau falschen Schluss."""
    stelle = INDEX.index("function _diagEbenenAuswahl(")
    block = INDEX[stelle:INDEX.index("\n}\n", stelle)]
    assert "leaflet-map" in block and "imFenster" in block


def test_ebenen_auswahl_liegt_ueber_der_herkunftsangabe():
    """Aufgeklappt reicht die Liste im Kniebrett bis an den unteren Kartenrand (gemessen
    30.08.2026: Kasten endet bei y=489, Karte ist 489 hoch, unterste Eintraege bei y=453 und
    y=471). Dort laeuft Leaflets Herkunftsangabe entlang, die hier ueber die volle Breite
    umbricht -- sie hat den letzten Eintrag ueberdeckt.

    Angehoben wird die ECKE, nicht der Kasten: Leaflet gibt jeder Ecke `z-index: 1000` und
    macht damit einen eigenen Stapel-Zusammenhang auf; ein hoeherer Wert am Kind darin bliebe
    wirkungslos. Gleiches Muster wie beim Windpfeil unten links."""
    assert "html.vr-panel .leaflet-top.leaflet-right { z-index: 1100; }" in INDEX
    # Die gleichartige Anhebung unten links ist am 02.09.2026 entfallen: Die Windanzeige,
    # der sie galt, sitzt im Vollbild jetzt oben rechts, und der Vollbild-Knopf, der dort
    # nachgerueckt ist, haengt gar nicht in einer Leaflet-Ecke -- er traegt seinen Rang
    # selbst (s. test_vollbild_im_panel_zeigt_nur_die_karte).
    assert "html.vr-panel .leaflet-bottom.leaflet-left { z-index: 1100; }" not in INDEX


# ==========================================================================================
#  Die AIP-Checkbox liess sich beim Hereinzoomen nicht mehr schalten (Nutzer-Fund 30.08.2026)
# ==========================================================================================
#
# Leaflets Ebenen-Auswahl SPERRT die Checkbox einer Ebene, die im aktuellen Zoom nichts
# liefern kann:
#
#     input.disabled = (... zoom < layer.options.minZoom) || (... zoom > layer.options.maxZoom)
#
# Der OpenAIP-Layer trug `maxZoom: 14`, war ab Zoom 15 also weder ein- noch auszuschalten.
# Die Messwerte des Tages passen genau: Die Schaltversuche lagen bei z=15, 16 und 17,
# waehrend die Ebenen ohne Zoom-Grenze (Platzrunden, Meldepunkte, FSE) durchgingen.
#
# Vorher wurden drei falsche Faehrten verfolgt -- Ueberdeckung durch ein anderes Element, der
# Scrollstand der Liste, ein Konflikt der gemerkten Vorlieben. Keine trug.

def test_aip_ebene_bleibt_beim_hereinzoomen_schaltbar():
    """`maxNativeZoom` sagt "so weit gibt es Kacheln", `maxZoom` sagt "darueber gibt es mich
    nicht" -- und nur Letzteres sperrt die Checkbox. Dasselbe Muster wie beim OFM-Layer, der
    im selben Projekt seit jeher `maxNativeZoom: OFM_NATIVE_MAX_ZOOM, maxZoom: 19` benutzt."""
    stelle = INDEX.index("function _makeAIPOverlay(")
    rumpf = _ohne_kommentare(INDEX[stelle:INDEX.index("\n}", stelle)])
    assert "maxNativeZoom: AIP_NATIVE_MAX_ZOOM" in rumpf
    # Der springende Punkt: KEIN maxZoom auf Kachel-Reichweite. 19 ist die Kartengrenze.
    assert "maxZoom: 14" not in rumpf
    assert "maxZoom: 19" in rumpf


def test_gesperrte_ebene_ist_im_kniebrett_zu_erkennen():
    """Das eingebaute Kaestchen zeigt "gesperrt" von selbst an -- unseres nicht, es ist selbst
    gezeichnet (`appearance: none`, weil Coherent GT Formularelemente nicht brauchbar malt).
    Eine Ebene, die nicht reagiert und dabei normal aussieht, kostet Stunden."""
    assert "html.vr-panel .leaflet-control-layers-selector:disabled" in INDEX
    assert ".leaflet-control-layers-selector:disabled) {" in INDEX


# ==========================================================================================
#  Zoom nach der Fläche (Nutzerwunsch 03.09.2026)
# ==========================================================================================
def _zoom_block() -> str:
    stelle = INDEX.index("function panelZoomSetzen()")
    return INDEX[stelle:INDEX.index("\n      }", stelle)]


def test_der_zoom_folgt_der_flaeche_aber_nur_nach_unten():
    """Das Kniebrett ist nicht eine Größe, sondern sechs -- gemessen über vier Nutzer:
    angedockt 468, freies Fenster in 2D 242/298/352, in VR 750/894/1035, bei einem anderen
    Nutzer bis 1475 Pixel.

    NUR NACH UNTEN, und das ist der Kern: Der Nutzer ist mit dem angedockten Tablet UND mit
    VR zufrieden -- in VR ist dasselbe Tablet nur feiner aufgelöst, nicht größer im
    Sichtfeld. Ein mitwachsender Zoom machte dort kaputt, was funktioniert. Zu groß ist es
    allein im kleinen 2D-Fenster."""
    block = _zoom_block()
    assert "window.innerWidth" in block
    assert "if (z > ZOOM_MASS) z = ZOOM_MASS;" in block, \
        "ohne Deckel nach oben wuerde VR mitwachsen -- genau das soll nicht passieren"
    assert "if (z < ZOOM_MIN) z = ZOOM_MIN;" in block, "Notbremse gegen Unlesbarkeit fehlt"
    mass = re.search(r"var ZOOM_MASS_BREITE = (\d+);", INDEX)
    assert mass and int(mass.group(1)) == 468, \
        "Bezug ist das gemessene angedockte Tablet, nicht ein gerundeter Wunschwert"
    wert = re.search(r"var ZOOM_MASS = ([\d.]+);", INDEX)
    assert wert and wert.group(1) == "1.35", "bei der Bezugsflaeche muss alles bleiben wie es war"


def test_der_zoom_wird_bei_jeder_groessenaenderung_neu_gesetzt():
    """Die Fläche ändert sich im Betrieb -- Wechsel ins Headset, andere Stufe, gezogenes
    Fenster. Ohne Horcher bliebe der Zoom auf dem Wert des Seitenaufbaus stehen."""
    assert "window.addEventListener('resize', panelZoomSetzen);" in INDEX
    assert "panelZoomSetzen();\n" in INDEX, "beim Aufbau muss er auch einmal laufen"


def test_der_zoom_greift_nur_im_kniebrett():
    """Am Schreibtisch gibt es kein Tablet, dessen Fläche zu klein wäre."""
    assert "if (!isPanel) return;" in _zoom_block()
    # Die CSS-Regel bleibt als Rueckfall, falls das Skript nicht laeuft.
    assert "zoom: 1.35;" in INDEX


def test_beide_kartenarten_nennen_die_quelle_gleichlautend():
    """Leaflet fasst gleichlautende Angaben zu EINER Zeile zusammen. Sichtflug- und
    Flugplatzkarte desselben AIRAC-Standes belegen damit eine Zeile statt zwei -- im
    kleinsten Fenster der Unterschied zwischen drei und fünf Zeilen quer über der Karte.

    Fehlt das Datum, entfällt der Zusatz statt als "AIRAC ?" dazustehen: Das ist keine
    Auskunft, kostet Platz und macht die Zeile ungleich zur anderen -- dann zeigt Leaflet
    wieder zwei."""
    m = re.search(r"function _dfsAttribution\(k\) \{(.*?)\n\}", INDEX, re.S)
    assert m, "_dfsAttribution nicht gefunden"
    assert "AIRAC ?" not in m.group(1) and "'?'" not in m.group(1)
    assert "k.airac ?" in m.group(1), "ohne Datum muss der Zusatz entfallen"
    # Beide Kartenarten muessen durch dieselbe Funktion gehen.
    assert "function _aipKarteAttribution(k) { return _dfsAttribution(k); }" in INDEX
    assert "function _groundAttribution(k) { return _dfsAttribution(k); }" in INDEX
