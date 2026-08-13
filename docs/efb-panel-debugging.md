# EFB-Panel debuggen (MSFS 2024 / Coherent GT)

Die Rendering-Engine im EFB-Panel ist **Coherent GT**, eine deutlich ältere WebKit-Variante als
moderne Browser. Fehler, die dort auftreten, lassen sich in Chrome oft überhaupt nicht
nachstellen — und umgekehrt bewiesen „lokal in Chrome geprüft"-Tests **nichts** über das
Verhalten im Panel. Dieses Dokument hält die zwei Wege fest, die tatsächlich funktionieren.

## Grundregel

> Ein in Chrome geprüfter Fix ist **nicht** verifiziert, solange er nicht im Panel gemessen
> wurde. Chrome ist die Kontrollgruppe, nicht der Prüfstand.

Am 13.08.2026 sind an einem Abend sechs Patch-Versionen entstanden, weil aus Chrome-Tests und
aus nie geladenen Panel-Ständen falsche Schlüsse gezogen wurden.

---

## Weg 1 — Selbstdiagnose (bevorzugt, funktioniert immer)

Das Panel misst sich selbst und meldet an den Server. **Braucht niemanden am Simulator** und
funktioniert auch in VR.

**Auslösen:** Panel öffnen (`/panel`), oder auf jeder Seite `?diag=1` anhängen. Der Bericht
geht ~2,5 s nach dem Laden automatisch raus.

**Auslesen:**

```bash
ssh server "sqlite3 /opt/friesenspy/data/friesenspy.db \
  \"SELECT created_at, app_version, payload_json FROM panel_diag ORDER BY id DESC LIMIT 1;\""
```

oder als Admin über `GET /api/admin/panel-diag` (s. `docs/api.md`).

**Was gemessen wird:** CSS-Unterstützung (`max-content`, `inset`, `gap`, `zoom`), Glyph-Breiten
(erkennt fehlende Zeichen/Tofu-Kästchen), Wrapper- vs. Tabellenbreite (Scroll-Frage),
Verfügbarkeit von `postMessage`/`localStorage`/`EventSource`, Ladeergebnis der Kartenkacheln
sowie alle aufgelaufenen JavaScript-Fehler.

Die Sonde liegt bewusst im **kleinen Kopf-Skript** von `app/static/index.html`, nicht im großen
Skriptblock: Coherent GT wirft bei unbekannten Sprachmitteln (`?.`, `??`, Spread, `flatMap`)
einen Parse-Fehler, der das gesamte betroffene `<script>` lahmlegt. Läge die Diagnose dort,
würde sie in genau dem Fall mitsterben, den sie melden soll.

---

## Weg 2 — Coherent-DevTools direkt in Chrome

`C:\MSFS 2024 SDK\Tools\CoherentGT Debugger\Debugger.exe` **stürzt seit dem 13.08.2026
reproduzierbar ab** (Access Violation, immer derselbe Codeoffset; ein kompletter
Rechner-Neustart und das Aushängen unseres Community-Packages änderten nichts — es ist ein
SDK-/Windows-seitiges Problem, nicht unseres).

**Die .exe wird gar nicht gebraucht.** Sie ist laut
`C:\MSFS 2024 SDK\Tools\CoherentGT Debugger\html\debugger.html` nichts als eine Hülle:

```html
<iframe id="devtools" src="http://127.0.0.1:19999"/>
```

Die kompletten DevTools sind eine Webseite, die der Simulator selbst ausliefert.

**Vorgehen:** Bei laufendem Sim in einem normalen Chrome öffnen:

```
http://127.0.0.1:19999
```

Es erscheint „Inspectable web views" mit einer Liste. Der Eintrag **`Electronic Flight Bag`**
ist die EFB-Shell (direkt: `http://127.0.0.1:19999/inspector/Main.html?page=<N>`, die Nummer
steht in `http://127.0.0.1:19999/pagelist.json`).

**Wichtig:** Es ist **eine gemeinsame Konsole für die gesamte EFB-Shell**, nicht eine pro App.
Meldungen anderer Addons (Navigraph/SimBrief, `127.0.0.1:8964/8965`) tauchen dort mit auf.
Ebenso normal und ohne Aussagekraft: 404-Meldungen für `.map`-Dateien der Sim-eigenen Skripte
und der `Worker`-Fehler aus Asobos `logger-1.min.js`.

**Schnelltest, ob der Debug-Server lebt:**

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 19999
Invoke-WebRequest "http://127.0.0.1:19999/pagelist.json" -UseBasicParsing
```

---

## Panel neu laden

`SuspendMode` steht auf `TERMINATE` (`msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx`),
damit **Tablet schließen und wieder öffnen** die Seite frisch lädt.

Vorher stand dort `SLEEP` — die App blieb samt geladenem iframe im Speicher, die Seite wurde
nie neu geladen, und es war ein kompletter Sim-Neustart nötig, um eine neue Version zu sehen.
Mehrere „live getestete" Fixes hat das Panel in Wahrheit nie geladen.

Zusätzlich leitet `/panel` ohne bzw. mit veralteter Versionsangabe auf `/panel?v=<VERSION>` um
(Cache-Bust), weil Coherent GT `Cache-Control` nicht zuverlässig befolgt.

Nach Änderungen am **Package** (nicht an der Website) ist ein Rebuild nötig:

```powershell
cd D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\FriesenSpy
npm run build
cd ..\..
.\build-package.ps1
```

Die Junction nach `Community2024` zeigt auf `msfs-panel\Package`, der Build ist damit sofort
im Sim wirksam.

---

## Bestätigte Coherent-GT-Lücken

Jede davon stammt aus einem echten Live-Test, nicht aus Vermutung:

| Fehlt / bricht | Wirkung |
|---|---|
| `?.`, `??` (ES2020) | SyntaxError — legt das **gesamte** `<script>` lahm |
| Object-Spread `{...x}` (ES2018) | dito |
| `Array.prototype.flatMap` (ES2019) | Laufzeitfehler |
| CSS `inset: 0` | wird still ignoriert; `position:fixed`-Overlays unsichtbar, blockieren aber Klicks |
| `navigator.clipboard` | nicht vorhanden; wirft synchron, `.catch()` greift nicht |
| `Notification` | nicht vorhanden; ungeschützter Zugriff wirft `ReferenceError` |
| Chart.js 4.x (ES2022) | bricht komplett; bereits durch `try/catch` abgefangen |
| Emoji-/Symbolzeichen | kein Font-Fallback → leere Kästchen (auch bei UI-Zeichen wie `×`!) |
| SVG mit `<image>`-Referenz | Icon verschwindet; reine Vektor-SVGs funktionieren |
| `Cache-Control` | wird nicht zuverlässig befolgt |
| CSS `gap` (Flex/Grid) | `CSS.supports('gap','1px')` = false; Abstand fällt ersatzlos weg — `margin` benutzen |
| CSS `position: sticky` | nicht unterstützt |
| `IntersectionObserver` | nicht vorhanden |
| **Jede** Schriftdatei | siehe unten — die Engine nimmt überhaupt keine an |
| **Waagerechtes Scrollen** | siehe unten — technisch möglich, aber nicht bedienbar |

**Leaflet selbst läuft einwandfrei** (Karte, Marker, Popups) — es ist kein generelles
„alte Engine"-Problem, sondern diese konkreten Lücken.

### Schriften: eine Sackgasse, keine Aufgabe (gemessen 13.08.2026)

Drei Anläufe an der Schrift-Auslieferung waren nicht falsch, sondern **wirkungslos** — es
gibt dort nichts zu reparieren:

- `document.fonts` bleibt bei **0 Einträgen**; keine einzige `@font-face` kommt an.
- `"Exo 2"` / `sans-serif` / `serif` / `monospace` / `Arial` / `Verdana` / `"Segoe UI"` /
  `Tahoma` rendern denselben Text auf **exakt 252,59 px** → es gibt genau EINE eingebaute
  Schrift, `font-family` wird komplett ignoriert.
- Diese Schrift kann **kein Zeichen über U+007F**: ä/ö/ü/×/✕/⛶/→/🔔 liegen alle exakt auf
  der Tofu-Referenzbreite (U+E000).
- Gegenprobe mit **eingebetteter** Schrift (dieselbe Datei per `fetch` geholt, als
  `data:`-URI angeboten): `status 200`, `bytes 40896` — vollständig angekommen — aber
  `wurdeAngewandt: false`, `faceCount: 0`. Die Engine lehnt Schriften **nicht wegen der
  Herkunft** ab, sondern generell.

→ Konsequenz: Text umschreiben statt Schrift ausliefern. `_TRANSLIT_MAP` /
`_initPanelTranslit` in `app/static/index.html`, nur bei `html.vr-panel`, zentral über
einen MutationObserver.

### Waagerechtes Scrollen ist nicht bedienbar (gemessen 13.08.2026)

Die Messung sagt, dass es *funktioniert* — und trotzdem kommt niemand an die Spalten:

```
{"cls": "live-table-wrap", "wrapClientW": 334, "wrapScrollW": 501, "canScroll": true}
```

CSS und Layout stimmen also. Was fehlt, sind **alle drei Bedienwege**: Coherent GT zeichnet
keine Scrollleiste (`::-webkit-scrollbar` bleibt wirkungslos), kennt kein Ziehen mit
Finger/Maus, und ein Mausrad gibt es im Tablet nicht.

→ Konsequenz: im Panel gar nicht erst waagerecht scrollen. Jede Tabelle ab drei Spalten in
einem `.live-table-wrap`/`.table-scroll`-Wrapper wird zu gestapelten Karten
(`_panelKartenLayout`). **Nicht** durch besseres CSS zu beheben — wer das nächste Mal an
den Scroll-Styles ansetzt, repariert etwas, das bereits funktioniert.


## Zeichenlast: der blinde Fleck jeder DOM-Messung (Fund 13.08.2026)

Drei Aufzeichnungen über den DOM fanden **nichts** — und lagen trotzdem richtig, denn die
Ursache war gar nicht im DOM:

- **Leaflets Kachel-Einblendung.** `GridLayer._updateOpacity` setzt `style.opacity` und
  lässt den Wert über `requestAnimationFrame` hochlaufen, solange `map._fadeAnimated`.
  Kommt die Schleife nicht ans Ziel, bleiben Kacheln unter Deckkraft 1 stehen: **im DOM
  vorhanden und trotzdem unsichtbar.** Jede Kartenbewegung stößt sie neu an und holt die
  Einblendung nach — daher „man muss die Karte bewegen, sonst verschwinden die Tiles".
  Erklärt rückwirkend auch die Satellitenkacheln, die laut Netzwerk-Tab vollständig
  ankamen und nie erschienen. → `fadeAnimation: false` für alle Karten im Panel.
- **Eine dauerlaufende Zierde-Animation.** `.scanline`, ein `position:fixed`-Streifen über
  die ganze Breite mit `z-index: 9999`, zählte im Achtsekundentakt seinen `top`-Wert von
  -2px auf 100vh hoch — also eine **Layout**-Eigenschaft statt `transform`. Jedes Einzelbild
  zwang die gesamte Seite zum Neuzeichnen. Im Sim als Stroboskop über der Karte sichtbar,
  im Desktop-Browser unauffällig. → im Panel abgeschaltet, vom Nutzer als Ursache bestätigt.

**Merksatz:** Wenn eine DOM-Aufzeichnung nichts findet, ist das ein Ergebnis, keine Panne —
dann liegt die Arbeit im Zeichnen. Dort lohnen sich zwei Fragen: Läuft eine Animation im
Dauerbetrieb? Und animiert sie eine Layout-Eigenschaft (`top`, `left`, `width`, `height`)
statt `transform`/`opacity`?
