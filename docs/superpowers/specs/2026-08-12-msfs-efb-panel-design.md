# MSFS-2024-EFB-Panel — eigene In-Game-App für FriesenSpy

**Status:** Design (2026-08-12). Zweiter Schritt zum In-Game-Panel, nach dem Web-Teil
(`docs/superpowers/specs/2026-08-11-vr-panel-modus-design.md`, gemerged/deployed). Dieser
Schritt behandelt das eigentliche MSFS-2024-SDK-Package, das `/panel` im Sim einbettet — das
war im vorherigen Design explizit ausgeklammert.

## Ziel

Der Nutzer will FriesenSpy als eigene App in der Electronic Flight Bag (EFB) von MSFS 2024
öffnen können — ohne Alt-Tab, ohne Desktop-Browser, auch in VR nutzbar. Technisch ist eine
EFB-App ein JS/JSX-basiertes Modul, das zu einem Community-Package gebaut wird und danach
automatisch in der EFB **jedes** Flugzeugs erscheint (kein aircraft-spezifisches Wiring
nötig).

## Kontext-Recherche (2026-08-12)

- Lokale SDK-Installation vorhanden: `C:\MSFS 2024 SDK` (Store-Version, Package Microsoft.
  Limitless). `Community2024`-Ordner existiert und ist aktuell leer:
  `C:\Users\Tobias\AppData\Local\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\
  Packages\Community2024`.
- Node.js (`v24.13.1`) + npm lokal vorhanden — kein Hindernis für den JS/JSX-Build.
- Die SDK-Beispiel-App (`PackageSources/TemplateApp`, aus der offiziellen EFB-API-Doku
  referenziert) liegt NICHT in der lokalen SDK-Installation — vermutlich separater
  Sample-Download oder über den Project Editor im Dev-Mode (auf dieser Maschine laut
  `DevMode.xml` in `LocalState` bereits mal aktiv). Exakte Scaffolding-Mechanik wird im
  Implementierungsplan direkt am SDK geklärt, nicht hier spekulativ vorweggenommen.
- Ein bereits existierender Community-Mod ("EFB web browser mod", flightsim.to #91219)
  belegt, dass echter Netzwerkzugriff/iframe auf externe Inhalte aus der EFB heraus
  grundsätzlich funktioniert. Einziges bekanntes Blockrisiko sind iframe-blockierende
  Header (`X-Frame-Options`/CSP) — FriesenSpy setzt aktuell **keine** solchen Header
  (geprüft: weder in `app/main.py` noch in der nginx-Config unter `devprops.de/`), also
  kein Hindernis von unserer Seite.
- Der Mod selbst wurde geprüft und bewusst NICHT als Lösung übernommen (s. „Warum keine
  Wiederverwendung" unten).

## Warum keine Wiederverwendung des existierenden Browser-Mods

Der Mod ist ein generischer Adressleisten-Browser zum manuellen Herumsurfen, keine feste
Startseite/dedizierte App. Der Autor selbst beschreibt ihn als „mostly a toy": *„Only very
basic websites that allow iframes will work, and you can expect a good chunk that don't work
at all."* FriesenSpy ist keine einfache statische Seite, sondern eine SPA mit SSE-Live-Updates,
interaktiver Karte, Formularen und einem Forum-SSO-Login-Flow — genau die Komplexität, vor der
gewarnt wird. Dazu kommt: Drittanbieter-Addon unbekannter Wartung/Lizenz, kein Branding, keine
Kontrolle. Eine eigene, minimale App ist nicht mehr Aufwand als den fremden Mod zu
konfigurieren, bleibt aber unter eigener Kontrolle und passt zum Zielbild (siehe unten).

## Nutzer-Entscheidungen 2026-08-12

- **Nur Web-Einbettung, keine SimConnect-Anbindung.** Die App liest keine Sim-Daten (Position,
  Callsign, o. ä.) aus und schreibt keine zurück — sie zeigt ausschließlich die eingebettete
  Seite. Eine tiefere Integration wäre ein separater, hier nicht behandelter Schritt.
- **Iterativ, aber mit finaler Identität von Anfang an.** V1 läuft nur auf dieser Maschine,
  ohne Installer, ohne Doku für Dritte, ohne Update-Mechanismus — das bleibt ein bewusst
  kleiner erster Schritt. ABER: Package-Name, Creator und Branding werden schon so gewählt,
  wie sie auch im späteren, an die ganze FriesenFlieger-Gruppe verteilten Addon heißen würden
  (s. Design), damit später niemand wegen einer geänderten Package-ID neu installieren muss.
- **Kein Zwischentest mit dem fremden Mod.** Direkt die eigene App bauen, statt vorab mit dem
  Community-Mod die grundsätzliche Machbarkeit (Login/SSE/Karte im Coherent-iframe) zu prüfen.
  Größtes verbleibendes Risiko bleibt damit ungetestet bis zum eigenen Live-Test in MSFS.

## Design

**Ablage:** neuer Unterordner `FriesenSpy/msfs-panel/` im bestehenden Repo (dasselbe Produkt,
andere Oberfläche — analog zur bisherigen Struktur mit `app/` für den Web-Teil). Enthält:

- `PackageSources/` — EFB-App-Quellcode (JS/JSX + Manifest), gebaut mit den SDK-Tools
- Icon: `app/static/icon-512.png` wiederverwendet (kein neues Branding-Asset nötig)

Das gebaute Package selbst ist NICHT Teil des Git-Repos (wie ein `dist/`-Ordner) — es wird
lokal nach `Community2024/friesenflieger-friesenspy-efb/` kopiert oder verlinkt, um es im Sim
zu testen.

**Package-Identität** (final, nicht als Wegwerf-Test gewählt; Creator während der Umsetzung
von `FriesenFlieger` auf `devprops` geändert, Package-ID unverändert):
- Creator: `devprops`
- Package-/App-Titel: `FriesenSpy`
- Package-ID: `friesenflieger-friesenspy-efb`

**App-Verhalten:** Beim Öffnen rendert die App einen eingebetteten Webview/iframe auf die
feste URL `https://friesenspy.devprops.de/panel` — dasselbe VR-optimierte Panel, das der
Web-Teil bereits liefert (Login-Gate bleibt aktiv, Hash-Tab-Navigation funktioniert
unverändert dahinter). Keine eigene Navigation, keine Adressleiste, keine Einstellungen.

**Exakte SDK-Mechanik** (Manifest-Felder, Build-Tooling-Aufruf, Project-Editor-Workflow) wird
im Implementierungsplan direkt am lokalen SDK/Dev-Mode geklärt — die lokale SDK-Installation
enthält keine gecachte Doku dazu, eine Recherche vorab wäre spekulativ.

## Bekannte Risiken

- **Login-Flow im Coherent-iframe ungetestet.** Größtes offenes Risiko: ob der
  Forum-SSO-Redirect-Flow innerhalb der eingeschränkten Coherent-GT-Browser-Engine
  überhaupt sauber durchläuft, zeigt sich erst beim Live-Test.
- **Rendering-Treue der SPA** (Karte, SSE-Updates) in Coherent GT ist nicht durch eigene
  Tests, nur durch Analogieschluss aus dem fremden Mod belegt.

## Testen

Kein automatisierter Test möglich (wie beim VR-Web-Teil des vorherigen Schritts) — reines
SDK-Package-/Rendering-Verhalten. Abnahme ist der Live-Test des Nutzers: Package bauen, nach
`Community2024` kopieren, MSFS starten, EFB-Tab „FriesenSpy" öffnen, Login-Flow + Live-Tab +
Karte prüfen.

## Nicht Teil dieses Schritts

- SimConnect-Datenanbindung (Position, Callsign, Fuel etc.).
- Installer, README/Installationsanleitung für Dritte, Verteilung an die FriesenFlieger-Gruppe,
  Update-Mechanismus — eigener, späterer Schritt, sobald V1 im eigenen Live-Test funktioniert.
- Konfigurierbarkeit (z. B. Start-Tab, Zoom-Faktor als Einstellung) — die App zeigt fest
  `/panel`, dessen bestehende Skalierung (`zoom: 1.35`, s. vorheriges Design) gilt unverändert.
