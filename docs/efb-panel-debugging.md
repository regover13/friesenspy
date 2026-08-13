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

**Leaflet selbst läuft einwandfrei** (Karte, Marker, Popups) — es ist kein generelles
„alte Engine"-Problem, sondern diese konkreten Lücken.
