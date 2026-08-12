# MSFS-2024-EFB-Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine eigene MSFS-2024-EFB-App "FriesenSpy" registriert sich in der Electronic Flight
Bag jedes Flugzeugs und rendert dort per iframe das bestehende, VR-optimierte
`https://friesenspy.devprops.de/panel`.

**Architecture:** Ein Node/esbuild-Projekt (`PackageSources/FriesenSpy/`, abgeleitet vom
offiziellen SDK-Sample `TemplateApp`) wird zu statischem JS/CSS gebaut. Diese Dateien werden
zusammen mit einem handgeschriebenen `manifest.json` in einen Community-Package-Ordner
(`Package/`) kopiert; `layout.json` wird darüber per CLI-Tool generiert. Der fertige
`Package/`-Ordner wird per Windows-Junction mit dem MSFS-`Community2024`-Ordner verbunden.
Kein SimConnect, keine eigene Navigation — die App zeigt ausschließlich die feste URL.

**Tech Stack:** TypeScript/TSX + esbuild (EFB-App), `@efb/efb-api` + `@microsoft/msfs-sdk`
(Asobo-SDK-Pakete, aus dem SDK-Sample übernommen), PowerShell (Build-/Deploy-Skripte),
`MSFSLayoutGenerator.exe` (community CLI-Tool, bereits lokal vorhanden unter
`D:\User\Tobias\OneDrive\GIT\ga-inventory\MSFSLayoutGenerator.exe`).

## Global Constraints

- Package-Identität (aus Spec, final, nicht als Wegwerf-Test gewählt): Creator `FriesenFlieger`,
  Titel `FriesenSpy`, Package-ID `friesenflieger-friesenspy-efb`.
- Feste URL `https://friesenspy.devprops.de/panel`, keine Adressleiste, keine Einstellungen,
  keine SimConnect-Datenanbindung (s. Design-Doku `docs/superpowers/specs/2026-08-12-msfs-efb-panel-design.md`).
- `PackageSources/efb_api/` und `PackageSources/vendor/` sind Sibling-Abhängigkeiten aus dem
  offiziellen SDK-Sample — laut SDK-Doku niemals inhaltlich verändern, nur kopieren.
- `fspackagetool.exe` wird NICHT verwendet — es startet laut SDK-Doku und Live-Beobachtung auf
  dieser Maschine ungefragt eine Teil-Instanz von MSFS. Der komplette Build läuft stattdessen
  über `npm`/`esbuild` (keine Asset-Kompilierung nötig, EFB-Apps sind reine Kopier-Assets) und
  `MSFSLayoutGenerator.exe` für `layout.json`.
- Der gebaute Package-Ordner (`msfs-panel/Package/`) ist NICHT Teil des Git-Repos (wie ein
  `dist/`-Ordner) — nur `PackageSources/` (Quellcode) wird versioniert.
- `minimum_game_version` in `manifest.json` ist auf dieser Maschine nicht anhand eines echten
  MSFS-2024-Packages verifizierbar (das lokale Referenzprojekt `ga-inventory` hat nur
  MSFS-2020-Pakete mit altem Versionsschema). Wert `1.0.0` ist eine informierte Annahme, kein
  verifizierter Fakt — siehe Hinweis in Task 2.

---

### Task 1: Sibling-Abhängigkeiten (efb_api, vendor) ins Repo übernehmen

**Files:**
- Create: `msfs-panel/PackageSources/efb_api/` (kopiert aus SDK-Sample, unverändert)
- Create: `msfs-panel/PackageSources/vendor/microsoft-msfs-sdk-2.1.1.tgz` (kopiert aus SDK-Sample, unverändert)
- Create: `msfs-panel/.gitignore`

**Interfaces:**
- Produces: `PackageSources/efb_api/dist/` (enthält `EfbApi.d.ts`, `App.d.ts`, `index.js` u. a. —
  wird von Task 2 als npm-Dependency `@efb/efb-api` via `file:../efb_api/dist/` referenziert).
  `PackageSources/vendor/microsoft-msfs-sdk-2.1.1.tgz` wird von Task 2 als npm-Dependency
  `@microsoft/msfs-sdk` via `file:../vendor/microsoft-msfs-sdk-2.1.1.tgz` referenziert.

- [ ] **Step 1: Ordnerstruktur anlegen und Dateien kopieren**

```powershell
New-Item -ItemType Directory -Force -Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources" | Out-Null

Copy-Item -Path "C:\MSFS 2024 SDK\Samples\DevmodeProjects\EFB\PackageSources\efb_api" `
  -Destination "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\efb_api" `
  -Recurse -Force

New-Item -ItemType Directory -Force -Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\vendor" | Out-Null
Copy-Item -Path "C:\MSFS 2024 SDK\Samples\DevmodeProjects\EFB\PackageSources\vendor\microsoft-msfs-sdk-2.1.1.tgz" `
  -Destination "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\vendor\microsoft-msfs-sdk-2.1.1.tgz" `
  -Force
```

- [ ] **Step 2: Verifizieren, dass die Kern-Dateien vorhanden sind**

```powershell
Test-Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\efb_api\dist\EfbApi.d.ts"
Test-Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\efb_api\dist\App.d.ts"
Test-Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\efb_api\package.json"
Test-Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\vendor\microsoft-msfs-sdk-2.1.1.tgz"
```

Expected: alle vier `True`.

- [ ] **Step 3: `.gitignore` für das neue Package anlegen**

Neue Datei `msfs-panel/.gitignore`:

```
# Build-Output (Task 2) und Community-Package (Task 3) -- nicht versioniert,
# siehe Global Constraints im Plan.
# WICHTIG: efb_api/dist ist KEIN Build-Output, sondern vendorierter SDK-Sample-Code
# (Task 1) und wird bewusst NICHT ausgeschlossen -- er muss committet werden.
PackageSources/efb_api/node_modules/
PackageSources/FriesenSpy/node_modules/
PackageSources/FriesenSpy/dist/
Package/
```

- [ ] **Step 4: Commit**

```bash
cd "D:\User\Tobias\OneDrive\Claude\FriesenSpy"
git add msfs-panel/PackageSources/efb_api msfs-panel/PackageSources/vendor msfs-panel/.gitignore
git commit -m "chore(msfs-panel): efb_api + msfs-sdk Sibling-Dependencies aus SDK-Sample uebernommen"
```

---

### Task 2: FriesenSpy-EFB-App-Quellcode erstellen und lokal bauen

**Files:**
- Create: `msfs-panel/PackageSources/FriesenSpy/package.json`
- Create: `msfs-panel/PackageSources/FriesenSpy/build.js`
- Create: `msfs-panel/PackageSources/FriesenSpy/.env`
- Create: `msfs-panel/PackageSources/FriesenSpy/tsconfig.json`
- Create: `msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx`
- Create: `msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.scss`
- Create: `msfs-panel/PackageSources/FriesenSpy/src/Assets/app-icon.png` (kopiert)
- Create: `msfs-panel/PackageSources/FriesenSpy/manifest.json`

**Interfaces:**
- Consumes: `@efb/efb-api` aus `../efb_api/dist/` (Task 1) — Klassen `App`, `AppView`,
  `AppBootMode`, `AppSuspendMode`, `Efb`, Typen `AppInstallProps`, `AppViewProps`,
  `RequiredProps`, `TVNode`. `@microsoft/msfs-sdk` aus `../vendor/...tgz` (Task 1) — `FSComponent`,
  `VNode`.
- Produces: `PackageSources/FriesenSpy/dist/` (FriesenSpy.js, FriesenSpy.css, Assets/) — wird von
  Task 3 in den Community-Package-Ordner kopiert. `PackageSources/FriesenSpy/manifest.json` wird
  von Task 3 unverändert in den Package-Ordner kopiert.

Der Ordnername `FriesenSpy` ist absichtlich identisch zum App-Klassennamen und zum späteren
`html_ui/efb_ui/efb_apps/FriesenSpy/`-Zielordner (Task 3) — `build.js` leitet daraus sowohl den
SCSS-Klassen-Prefix (`__dirname`-Basisname) als auch `BASE_URL` ab; bei einem anderen Ordnernamen
müssten beide Stellen manuell synchron gehalten werden.

- [ ] **Step 1: `package.json` schreiben**

```json
{
  "name": "@efb/friesenspy",
  "version": "0.1.0",
  "license": "UNLICENSED",
  "author": "FriesenFlieger",
  "scripts": {
    "build": "node ./build.js",
    "clean": "npm run clean:dist && npm run clean:node_modules",
    "clean:dist": "if exist ./dist/ (rmdir /s /q dist)",
    "clean:node_modules": "if exist ./node_modules/ (rmdir /s /q node_modules)",
    "rebuild": "npm run clean:dist && npm run build",
    "watch": "cross-env SERVING_MODE=WATCH node ./build.js"
  },
  "dependencies": {
    "@efb/efb-api": "file:../efb_api/dist/",
    "@microsoft/msfs-sdk": "file:../vendor/microsoft-msfs-sdk-2.1.1.tgz",
    "@microsoft/msfs-types": "^1.14.6"
  },
  "devDependencies": {
    "@fal-works/esbuild-plugin-global-externals": "^2.1.2",
    "@jgoz/esbuild-plugin-typecheck": "^3.0.2",
    "@types/node": "^18.15.5",
    "cross-env": "^7.0.3",
    "dotenv": "^16.0.3",
    "esbuild": "^0.21.3",
    "esbuild-copy-static-files": "^0.1.0",
    "esbuild-plugin-copy": "^2.1.1",
    "esbuild-sass-plugin": "^3.3.0",
    "postcss": "^8.4.30",
    "postcss-prefix-selector": "^1.16.0",
    "postcss-url": "^10.1.3",
    "prettier": "^2.7.1",
    "typescript": "~5.6.2"
  }
}
```

- [ ] **Step 2: `build.js` schreiben** (1:1 aus `TemplateApp/build.js` übernommen, nur
  `entryPoints` und `BASE_URL` angepasst)

```js
const copyStaticFiles = require("esbuild-copy-static-files");
const globalExternals = require("@fal-works/esbuild-plugin-global-externals");
const { typecheckPlugin } = require("@jgoz/esbuild-plugin-typecheck");
const esbuild = require("esbuild");
const postcss = require("postcss");
const postCssUrl = require("postcss-url");
const postcssPrefixSelector = require("postcss-prefix-selector");
const sassPlugin = require("esbuild-sass-plugin");

require("dotenv").config({ path: __dirname + "/.env" });

const env = {
  typechecking: process.env.TYPECHECKING === "true",
  sourcemaps: process.env.SOURCE_MAPS === "true",
  minify: process.env.MINIFY === "true",
};

const baseConfig = {
  entryPoints: ["src/FriesenSpy.tsx"],
  keepNames: true,
  bundle: true,
  outdir: "dist",
  sourcemap: env.sourcemaps,
  minify: env.minify,
  logLevel: "debug",
  loader: {
    ".html": "copy",
  },
  target: "es2017",
  define: { BASE_URL: `"coui://html_ui/efb_ui/efb_apps/FriesenSpy"` },
  plugins: [
    copyStaticFiles({
      src: "./src/Assets",
      dest: "./dist/Assets",
    }),
    globalExternals.globalExternals({
      "@microsoft/msfs-sdk": {
        varName: "msfssdk",
        type: "cjs",
      },
      "@workingtitlesim/garminsdk": {
        varName: "garminsdk",
        type: "cjs",
      },
    }),
    sassPlugin.sassPlugin({
      async transform(source) {
        const { css } = await postcss([
          postCssUrl({
            url: "copy",
          }),
          postcssPrefixSelector({
            prefix: `.efb-view.${__dirname.split("\\").at(-1)}`,
          }),
        ]).process(source, { from: undefined });
        return css;
      },
    }),
  ],
};

if (env.typechecking) {
  baseConfig.plugins.push(
    typecheckPlugin({ watch: process.env.SERVING_MODE === "WATCH" })
  );
}

if (process.env.SERVING_MODE === "WATCH") {
  esbuild.context(baseConfig).then((ctx) => ctx.watch());
} else if (process.env.SERVING_MODE === "SERVE") {
  esbuild
    .context(baseConfig)
    .then((ctx) => ctx.serve({ port: process.env.PORT_SERVER }));
} else if (["", undefined].includes(process.env.SERVING_MODE)) {
  esbuild.build(baseConfig);
} else {
  console.error(`MODE ${process.env.SERVING_MODE} is unknown`);
}
```

- [ ] **Step 3: `.env` schreiben** (identisch zum Sample-Default)

```
TYPECHECKING=true
SOURCE_MAPS=true
MINIFY=false
```

- [ ] **Step 4: `tsconfig.json` schreiben** (1:1 aus `TemplateApp/tsconfig.json` kopiert)

```json
{
  "compilerOptions": {
    "incremental": false,
    "target": "es2017",
    "jsx": "react",
    "experimentalDecorators": true,
    "jsxFactory": "FSComponent.buildComponent",
    "jsxFragmentFactory": "FSComponent.Fragment",
    "module": "ES2015",
    "moduleResolution": "node",
    "rootDir": ".",
    "baseUrl": ".",
    "resolveJsonModule": true,
    "noEmit": true,
    "allowJs": false,
    "declaration": false,
    "declarationMap": false,
    "sourceMap": false,
    "removeComments": false,
    "allowSyntheticDefaultImports": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "strict": true,
    "skipLibCheck": true
  },
  "exclude": ["node_modules", "dist", "tsconfig.json"]
}
```

- [ ] **Step 5: App-Quellcode schreiben**

`src/FriesenSpy.scss`:

```scss
.friesenspy-app {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.friesenspy-frame {
  width: 100%;
  height: 100%;
  border: none;
}
```

`src/FriesenSpy.tsx`:

```tsx
import {
  App,
  AppBootMode,
  AppInstallProps,
  AppSuspendMode,
  AppView,
  AppViewProps,
  Efb,
  RequiredProps,
  TVNode,
} from "@efb/efb-api";
import { FSComponent, VNode } from "@microsoft/msfs-sdk";

import "./FriesenSpy.scss";

/**
 * BASE_URL ist eine globale Variable aus build.js, zeigt im gebauten Package
 * auf den eigenen dist-Ordner (fuer Assets wie das App-Icon).
 */
declare const BASE_URL: string;

const PANEL_URL = "https://friesenspy.devprops.de/panel";

class FriesenSpyView extends AppView<RequiredProps<AppViewProps, "bus">> {
  /**
   * Rendert direkt das eingebettete Panel, ohne AppViewService/Mehrseiten-
   * Navigation -- s. Design-Doku 2026-08-12: nur Web-Einbettung, keine eigene
   * Navigation. AppView.render() erlaubt das laut SDK-Sample-Kommentar
   * ausdruecklich ("can render anything").
   */
  public render(): VNode {
    return (
      <div class="friesenspy-app">
        <iframe class="friesenspy-frame" src={PANEL_URL} />
      </div>
    );
  }
}

class FriesenSpy extends App {
  public get name(): string {
    return FriesenSpy.name;
  }

  public get icon(): string {
    return `${BASE_URL}/Assets/app-icon.png`;
  }

  public BootMode = AppBootMode.COLD;
  public SuspendMode = AppSuspendMode.SLEEP;

  public async install(_props: AppInstallProps): Promise<void> {
    Efb.loadCss(`${BASE_URL}/FriesenSpy.css`);
    return Promise.resolve();
  }

  public get compatibleAircraftModels(): string[] | undefined {
    return undefined;
  }

  public render(): TVNode<FriesenSpyView> {
    return <FriesenSpyView bus={this.bus} />;
  }
}

Efb.use(FriesenSpy);
```

**Bekanntes Risiko (für den Live-Test in Task 4 vormerken):** Das `<iframe>`-Tag in
`FriesenSpyView.render()` ist im SDK-Sample nicht vorbelegt (dort werden nur `<div>`/`<h2>`
über generische DOM-Tags gerendert) — dass `FSComponent.buildComponent` beliebige HTML-Tags
inklusive `iframe` 1:1 als DOM-Element erzeugt, ist eine begründete Annahme (das Verhalten für
`<div>` ist im Sample belegt, `iframe` ist kein Sonderfall in diesem Framework), aber nicht am
echten SDK verifiziert. Falls der Build in Step 7 durchläuft, aber im Live-Test (Task 4) kein
iframe erscheint, ist das der erste Verdächtige.

- [ ] **Step 6: Icon kopieren**

```powershell
New-Item -ItemType Directory -Force -Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\FriesenSpy\src\Assets" | Out-Null
Copy-Item -Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\static\icon-512.png" `
  -Destination "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\FriesenSpy\src\Assets\app-icon.png" `
  -Force
```

- [ ] **Step 7: `manifest.json` schreiben** (Schema verifiziert an echten Community-Packages in
  `D:\User\Tobias\OneDrive\GIT\ga-inventory\`; `minimum_game_version` ist eine Annahme, s. Global
  Constraints)

```json
{
  "dependencies": [],
  "content_type": "MISC",
  "title": "FriesenSpy",
  "manufacturer": "",
  "creator": "FriesenFlieger",
  "package_version": "0.1.0",
  "minimum_game_version": "1.0.0",
  "release_notes": {
    "neutral": {
      "LastUpdate": "",
      "OlderHistory": ""
    }
  },
  "total_package_size": "00000000000000000000"
}
```

- [ ] **Step 8: Dependencies installieren und bauen**

```powershell
cd "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\efb_api"
npm install

cd "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\FriesenSpy"
npm install
npm run build
```

Expected: `npm run build` endet ohne Fehler; `esbuild`-Log zeigt geschriebene Dateien nach
`dist/`.

- [ ] **Step 9: Build-Output verifizieren**

```powershell
Test-Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\FriesenSpy\dist\FriesenSpy.js"
Test-Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\FriesenSpy\dist\FriesenSpy.css"
Test-Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\PackageSources\FriesenSpy\dist\Assets\app-icon.png"
```

Expected: alle drei `True`.

- [ ] **Step 10: Commit**

```bash
cd "D:\User\Tobias\OneDrive\Claude\FriesenSpy"
git add msfs-panel/PackageSources/FriesenSpy/package.json msfs-panel/PackageSources/FriesenSpy/build.js \
  msfs-panel/PackageSources/FriesenSpy/.env msfs-panel/PackageSources/FriesenSpy/tsconfig.json \
  msfs-panel/PackageSources/FriesenSpy/src msfs-panel/PackageSources/FriesenSpy/manifest.json
git commit -m "feat(msfs-panel): FriesenSpy-EFB-App -- rendert /panel per iframe"
```

(`node_modules/` und `dist/` sind durch `msfs-panel/.gitignore` aus Task 1 bereits ausgeschlossen.)

---

### Task 3: Community-Package zusammenbauen (manifest.json + layout.json)

**Files:**
- Create: `msfs-panel/build-package.ps1`

**Interfaces:**
- Consumes: `PackageSources/FriesenSpy/dist/` und `PackageSources/FriesenSpy/manifest.json`
  (Task 2).
- Produces: `msfs-panel/Package/` (manifest.json, layout.json,
  `html_ui/efb_ui/efb_apps/FriesenSpy/...`) — wird von Task 4 nach `Community2024` verlinkt.

- [ ] **Step 1: Build-Skript schreiben**

```powershell
# build-package.ps1 -- baut msfs-panel/Package/ aus PackageSources/FriesenSpy/dist.
# Ausfuehren aus msfs-panel/ (oder per vollem Pfad, Skript ist ortsunabhaengig via $PSScriptRoot).
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$dist = Join-Path $root "PackageSources\FriesenSpy\dist"
$manifestSrc = Join-Path $root "PackageSources\FriesenSpy\manifest.json"
$pkg = Join-Path $root "Package"
$appOut = Join-Path $pkg "html_ui\efb_ui\efb_apps\FriesenSpy"
$layoutGen = "D:\User\Tobias\OneDrive\GIT\ga-inventory\MSFSLayoutGenerator.exe"

if (-not (Test-Path $dist)) {
    throw "dist-Ordner fehlt: $dist -- erst 'npm run build' in PackageSources\FriesenSpy ausfuehren (Task 2)."
}
if (-not (Test-Path $layoutGen)) {
    throw "MSFSLayoutGenerator.exe nicht gefunden unter: $layoutGen"
}

if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
New-Item -ItemType Directory -Path $appOut -Force | Out-Null

Copy-Item -Path (Join-Path $dist "*") -Destination $appOut -Recurse -Force
Copy-Item -Path $manifestSrc -Destination (Join-Path $pkg "manifest.json") -Force

$layoutJson = Join-Path $pkg "layout.json"
Set-Content -Path $layoutJson -Value "{}" -Encoding UTF8 -NoNewline

& $layoutGen $layoutJson

Write-Output "Package gebaut: $pkg"
```

- [ ] **Step 2: Skript ausführen**

```powershell
cd "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel"
.\build-package.ps1
```

Erwartung: Konsolen-Ausgabe endet mit `Package gebaut: ...\msfs-panel\Package`, keine Exception.
`MSFSLayoutGenerator.exe` öffnet dabei kein GUI-Fenster (reines CLI-Tool, s. Global Constraints).

- [ ] **Step 3: Ergebnis verifizieren**

```powershell
Test-Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\Package\manifest.json"
Test-Path "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\Package\html_ui\efb_ui\efb_apps\FriesenSpy\FriesenSpy.js"
Get-Content "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\Package\layout.json" | Select-String '"path"'
```

Expected: beide `Test-Path` `True`; `layout.json` enthält mindestens einen `"path"`-Eintrag
(bestätigt, dass `MSFSLayoutGenerator.exe` die Datei-Liste tatsächlich befüllt hat, nicht nur
das leere `{}`-Grundgerüst stehen ließ).

- [ ] **Step 4: Commit**

```bash
cd "D:\User\Tobias\OneDrive\Claude\FriesenSpy"
git add msfs-panel/build-package.ps1
git commit -m "chore(msfs-panel): Build-Skript fuer den Community-Package-Ordner"
```

(`msfs-panel/Package/` bleibt ungetrackt, s. `.gitignore` aus Task 1.)

---

### Task 4: Nach Community2024 verlinken und im Sim live testen

**Files:**
- Keine neuen Dateien im Repo — legt eine Windows-Junction außerhalb des Repos an und ist der
  manuelle Live-Test aus der Design-Doku ("Testen").

**Interfaces:**
- Consumes: `msfs-panel/Package/` (Task 3).

- [ ] **Step 1: Junction anlegen** (einmalig; verlinkt den Package-Ordner in `Community2024`,
  ohne die Datei zu duplizieren — jeder neue `build-package.ps1`-Lauf aus Task 3 ist damit sofort
  im Sim sichtbar)

```powershell
New-Item -ItemType Junction `
  -Path "C:\Users\Tobias\AppData\Local\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community2024\friesenflieger-friesenspy-efb" `
  -Target "D:\User\Tobias\OneDrive\Claude\FriesenSpy\msfs-panel\Package"
```

- [ ] **Step 2: Junction verifizieren**

```powershell
Test-Path "C:\Users\Tobias\AppData\Local\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community2024\friesenflieger-friesenspy-efb\manifest.json"
```

Expected: `True`.

- [ ] **Step 3: Live-Test in MSFS (manuell, vom Nutzer auszuführen)**

1. MSFS 2024 selbst starten.
2. Einen Flug mit einem beliebigen Flugzeug mit EFB starten (z. B. DA 62, von Asobo als
   Referenz für den EFB-Test empfohlen).
3. Die EFB öffnen (physisches Tablet im Cockpit oder 2D-Panel-Taste je nach Flugzeug).
4. Prüfen: Erscheint ein App-Icon **"FriesenSpy"** in der App-Liste?
5. Antippen — öffnet sich `/panel`? Läuft der Forum-Login-Flow durch (größtes bekanntes
   Risiko aus der Design-Doku)? Werden Live-Tab, Karte und SSE-Updates sichtbar?
6. Rückmeldung, was funktioniert und was nicht — insbesondere ob das `<iframe>` aus Task 2
   überhaupt rendert (bekanntes offenes Risiko).

- [ ] **Step 4: Ergebnis festhalten**

Kein Commit in diesem Step — abhängig vom Ergebnis des Live-Tests entscheidet sich, ob weitere
Tasks (z. B. Zoom-Anpassung analog zum Web-Teil, Fehlerbehebung am iframe) nötig sind. Das
Ergebnis wird im Gespräch mit dem Nutzer ausgewertet, nicht in diesem Plan vorweggenommen.
