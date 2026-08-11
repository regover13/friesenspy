# VR-Panel-Modus — vergrößerte Ansicht für ein MSFS-2024-EFB-Panel

**Status:** Design (2026-08-11). Neues Feature, kleiner Schnitt. Erster Schritt zu einem
MSFS-In-Game-Panel — dieser Teil betrifft ausschließlich die Web-Seite selbst, kein SDK-Code.

## Ziel

Der Nutzer will FriesenSpy in VR öffnen können, während er in MSFS 2024 fliegt — dort gibt es
keinen Zugriff auf einen Desktop-Browser, nur In-Game-Panels (EFB-Apps wie Navigraph Charts).
Ein solches Panel ist technisch nichts anderes als ein eingebetteter Chromium-Browser
(Coherent GT), der eine URL lädt — der eigentliche Web-Teil dieser Arbeit ist deshalb: die
**echte, vollständige FriesenSpy-Seite** so herrichten, dass sie in einem EFB-Tablet-großen
Panel (~1000×700 px) unter VR-Headset-Optik lesbar bleibt. Die spätere Einbettung ins
MSFS-SDK-Panel selbst ist ein separater, hier nicht behandelter Schritt.

## Nutzer-Entscheidungen 2026-08-11

- **Kein neues, reduziertes Widget.** Die komplette Seite 1:1 — alle vier Tabs (Live,
  Statistik, Bummel, Kutter), Karte, TeamSpeak-Status, Prefiles. Vorbild `/widget` (bestehende
  Mini-Ansicht) wurde geprüft und verworfen — der Nutzer will dieselben Infos wie im Original.
- **Login bleibt aktiv.** Der VR-Panel-Modus wird NICHT vom Forum-SSO-Login-Gate ausgenommen
  (`_GATE_ALLOW_PREFIXES` in `main.py` bleibt unverändert). Kein öffentlicher Zugang.
- **Zielgröße:** EFB-Tablet-Format (~1000×700 px), nicht ein schmaler MFD-Streifen.
- **Eingabe:** reguläre Maus (kein VR-Controller) — MSFS projiziert die Mausbewegung als
  Zeiger auf VR-Cockpitflächen inkl. eingebetteter Panels; Klicken/Scrollen/Hover verhalten
  sich damit nahe am Desktop. Die Bedienung muss deshalb NICHT vereinfacht werden — die
  Interaktionsdichte der bestehenden Seite bleibt unangetastet.
- **Einzige offene Stellschraube ist Lesbarkeit**, nicht Bedienbarkeit: Headset-Optik macht
  kleine, dünne Schrift unscharf. Muss vor dem echten VR-Test nicht exakt getroffen werden —
  der Nutzer testet live und meldet grob, in welche Richtung der Wert korrigiert werden muss.
- **Keine Zwischenprüfung per Screenshot.** Direkt live in VR getestet, danach nachjustiert.

## Warum eine reine Schriftgrößen-Anpassung nicht reicht

Geprüft (`grep padding: app/static/index.html`): Innenabstände/Button-Größen sind überwiegend
in festen `px`-Werten codiert, nicht `rem`. Eine höhere Root-Schriftgröße würde nur den Text
wachsen lassen, die umgebenden Boxen/Buttons blieben gleich groß — Text liefe über, wirkte
gedrängt statt lesbarer. Der Hebel muss die GESAMTE gerenderte Seite gleichzeitig skalieren.

## Design

**Route (`app/main.py`):** neue Route `GET /panel`, liefert exakt dieselbe Datei wie `/`
(`FileResponse("app/static/index.html", headers=_HTML_NO_CACHE)`) — keine zweite HTML-Datei,
keine Logik-Duplikation. Läuft durch dasselbe `forum_login_gate`-Middleware wie jede andere
Route (kein Eintrag in `_GATE_ALLOW_PREFIXES`), also weiterhin login-pflichtig. Die bestehende
Hash-basierte Tab-Navigation (`#tab=bummel&...`) funktioniert unverändert dahinter, z. B.
`/panel#tab=live` als direkter Einstieg.

**Erkennung + Skalierung (`app/static/index.html`):** beim Laden prüft JS, ob
`location.pathname === '/panel'` ODER der Query-Parameter `vr=1` gesetzt ist (letzterer als
gleichwertiger Trigger auch auf `/`, z. B. für einen Test ohne Pfadwechsel), und setzt in
diesem Fall die Klasse `vr-panel` auf `<html>`. CSS:

```css
html.vr-panel { zoom: 1.35; }             /* Startwert, nach dem VR-Test nachjustierbar */
html.vr-panel body { font-weight: 400; }  /* App läuft sonst durchgehend auf 300 (dünn) */
```

`zoom` (Chromium-/WebKit-Erweiterung, in Coherent GT verfügbar) skaliert Text, Innenabstände,
Buttons und Karten-Controls gemeinsam, exakt wie ein manuelles Browser-Zoom — kein Rewrite
einzelner Regeln nötig. Der Zahlenwert `1.35` ist eine erste Schätzung, keine Messung.

**Sonst keine Änderung.** Volle Funktionalität, alle Tabs, Karte, Bummel, Kutter, Login-Fluss —
identisch zu heute. Umfang: eine neue Route (~3 Zeilen), Erkennungs-Logik (~10 Zeilen JS),
zwei CSS-Zeilen.

## Testen

Automatisiert prüfbar ist hier wenig (reines CSS/Layout-Verhalten) — kein neuer Backend-Test
nötig, `/panel` liefert nachweislich dieselbe Datei wie `/` (ein einfacher Response-Vergleich
im bestehenden `test_forum_sso_api.py`/`test_admin_api.py`-Stil deckt das ab, falls gewünscht).
Die eigentliche Abnahme ist der Live-Test des Nutzers im VR-Headset; der Zoom-Faktor wird danach
als Einzeiler nachjustiert.

## Nicht Teil dieses Schritts

- Das eigentliche MSFS-SDK-Panel/EFB-Package, das `/panel` im Sim einbettet.
- Die offene Frage, ob Netzwerkzugriffe (Kartenkacheln, API-Calls, SSE) aus dem
  In-Game-Panel-Kontext überhaupt möglich sind — betrifft die SDK-Einbettung, nicht diese Seite.
