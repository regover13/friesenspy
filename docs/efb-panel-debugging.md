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
(erkennt fehlende Zeichen/Tofu-Kästchen), **Sprite-Symbole** (s. u.), Wrapper- vs.
Tabellenbreite (Scroll-Frage), Verfügbarkeit von `postMessage`/`localStorage`/`EventSource`,
Ladeergebnis der Kartenkacheln sowie alle aufgelaufenen JavaScript-Fehler.

**Feld `sprites`** (seit v12.5.7): Zeichnet ein `<use>` überhaupt etwas? `mitHref` und
`mitXlink` sind die Bounding-Box-Breiten desselben Symbols, einmal über jedes Attribut
angesprochen; `echterKnopf` misst zusätzlich ein Symbol aus dem laufenden Markup. In Coherent
GT war `mitHref` **0** und `mitXlink` > 0 — der Beleg für den `xlink:href`-Fehler weiter unten.
Gemessen wird `getBBox()` des Inhalts, nicht die Größe des `<svg>`: Der Rahmen hat seine Maße
immer, auch wenn der Verweis ins Leere läuft. Genau daran war die frühere Messung gescheitert.

**Datensatz `kind="shell"`** (seit v12.1.0): Beantwortet die Frage, ob `postMessage` die
iframe-Grenze in Coherent GT tatsächlich überquert. Dass die Funktion *existiert*, ist gemessen
(`features.postMessage: true`) — das sagt über die Zustellung nichts. Das Panel schickt beim
Start einmal `{quelle:'friesenspy', art:'ping'}` an die EFB-App; die antwortet `pong`. Nach 5 s
geht das Ergebnis raus:

```bash
ssh server "sqlite3 /opt/friesenspy/data/friesenspy.db \
  \"SELECT created_at, payload_json FROM panel_diag WHERE kind='shell' ORDER BY id DESC LIMIT 1;\""
```

`shellAntwortet: true` → die Meldungen erscheinen als Tablet-Benachrichtigung.
`false` → das Panel zeigt sie im eigenen Fenster an (`.panel-hinweis`), und der Weg über die
Shell muss anders gebaut werden (Plan B: die EFB-App öffnet die SSE-Verbindung selbst,
authentifiziert über die Geräte-ID aus `panel_devices`).

**Datensatz `kind="navi"`** (seit v12.6.0): Beantwortet nach **einem** Sim-Lauf, welcher Weg für
Moving Map und Track-up tatsächlich greift. Einmalig 20 s nach dem Aufbau der Karte — lange
genug, dass die Shell geantwortet und VATSIM einmal geliefert haben kann, aber bewusst kein
Dauer-Messmittel im Renderpfad (Lehre aus `kind="zeichnen"`, s. u.).

```bash
ssh server "docker exec friesenspy-friesenspy-1 python -c \"
import sqlite3,json
c=sqlite3.connect('/opt/friesenspy/data/friesenspy.db')
r=c.execute('SELECT created_at, payload_json FROM panel_diag WHERE kind=? ORDER BY id DESC LIMIT 1',('navi',)).fetchone()
print(r[0]); print(json.dumps(json.loads(r[1]), indent=2, ensure_ascii=False))
\""
```

Das entscheidende Feld ist **`quelle`**: `sim` = die SimVar-Position aus der EFB-Shell kam an,
`vatsim` = der Fallback über den eigenen Flieger im Datenstrom lief, `keine` = weder noch (nicht
eingeloggt oder nicht online). „Sim-Position vorhanden" und „Sim-Position benutzt" sind
zweierlei, deshalb steht beides drin (`simPositionDa`, `simAlterMs`). `rotatePluginDa` sagt, ob
`leaflet-rotate` den Leaflet-Kern erfolgreich erweitert hat.

**Hinweis zu `sqlite3`:** Im Container ist das CLI-Werkzeug **nicht** installiert — die Aufrufe
weiter oben mit `sqlite3 …` funktionieren nur auf dem Host. Aus dem Container heraus geht es
über Python, wie in diesem Beispiel.

**Datensatz `kind="sim-verkehr"`** (seit Kniebrett-Paket 1.5.0): Einmal je Sitzung, beim
ersten Eintreffen einer **nichtleeren** Verkehrsliste aus dem Simulator — für den Fall, dass
gar nichts kommt, gibt es seit 1.7.0 zusätzlich `sim-verkehr-start` (weiter unten). Er ersetzt die alte
Sonde `kind="traffic-sonde"` aus Paket 1.3.0/1.4.0, die mit festen Terminen nach dem Öffnen
der App maß und deshalb den richtigen Moment nur zufällig traf — der Flug wird geladen, dann
ist das Tablet schon offen, und **erst danach** verbindet vPilot.

| Feld | Bedeutung |
|------|-----------|
| `anzahl` | Wie viele Flugzeuge der Simulator in diesem Takt meldet |
| `weitesteKm` | Entfernung des am weitesten entfernten — wie weit reicht der Sim-Horizont? |
| `felder` | Feldnamen des aufbereiteten Eintrags |
| `ersterEintrag` | Der **vollständige** erste Eintrag mit Werten (`id`, `lat`, `lon`, `alt`, `hdg`, `gs`, `ac`, `cs`, `gnd`) |
| `vatsimNah` | Gegenprobe: wie viele Flugzeuge VATSIM im selben Moment im 75-km-Umkreis kennt |
| `eigenLat` / `eigenLon` | Eigene Position, auf drei Stellen gerundet |

**So war das Ergebnis zu lesen — und so ist es ausgefallen** (Messung 15./16.08.2026):

| Feld | Was es entschied | Ergebnis |
|---|---|---|
| `ersterEintrag.cs` | Trägt `name` den Callsign? Davon hängt Teilprojekt 2b ab. [DevSupport 13002](https://devsupport.flightsimulator.com/t/js-npcplane-parameter-name-always-empty-msfs2020-2024/13002) behauptet „immer leer" | **Leer.** DevSupport behält recht. Deshalb kommt die Identität aus VATSIM (`_verkehrZusammenfuehren`) |
| `ersterEintrag.ac` | `C172` oder ein Asobo-interner Modellname? | **Leer**, ebenfalls |
| `ersterEintrag.alt` | Plausibel? Ein Airliner muss ~35 000 zeigen, nicht ~10 700 | **Stimmt.** Gegenprobe am Bildschirm: Sim `FL320`/`FL145` gegen VATSIM `FL323`/`FL156` — die Differenz ist der Zeitversatz bei steigenden Flugzeugen. Meter → Fuß ist richtig |
| `weitesteKm` vs. `vatsimNah` | Wie weit der Sim sieht | **Keine Eigenschaft des Sims**, sondern von vPilot: Dessen Sichtbarkeitsgrenze (z. B. „Do not display aircraft beyond 100nm") bestimmt, was überhaupt injiziert wird. `weitesteKm` sagt nur, wie weit das entfernteste *gemeldete* Flugzeug war — bei einem einzigen in der Nähe also gar nichts. **Nicht als Reichweite lesen** |

Ein weiterer Befund ohne eigenes Feld: **vPilot spawnt nicht jede Maschine**, die VATSIM kennt
(Model Matching, Sichtbarkeitsgrenzen). Der Simulator ist deshalb nie die vollständige Quelle —
der Grund für die Zusammenführung beider Quellen ab v13.2.0.

**Die Gegenprobe ist der Kern, nicht Beiwerk.** Eine Zahl aus dem Simulator ist für sich
genommen nicht lesbar: „Sim 0, VATSIM 7" ist eine Antwort, „Sim 0, VATSIM 0" ist keine. Genau
daran scheiterte die erste Messung (15.08.2026) — dreimal null, jedes Mal gemessen, bevor der
Nutzer überhaupt mit vPilot verbunden war.

**Datensatz `kind="zuordnung"`** (seit v13.5.1): Einmal je Sitzung, **eine Minute nach der
ersten Zuordnung** — lange genug, dass sich der Zustand gesetzt hat. Beantwortet die Frage, die
man am Bildschirm nicht beantworten kann: *Wie gut* läuft die Zuordnung von Sim-Verkehr und
VATSIM?

| Feld | Bedeutung |
|------|-----------|
| `sim` / `vatsim` | Größe beider Listen |
| `zugeordnet` / `offen` | Wie viele Sim-Flugzeuge ein Rufzeichen bekamen, wie viele nicht |
| `davonFriesen` | Wie viele Zuordnungen einen Friesen betrafen |
| `perAusschluss` | Wie oft „es bleibt nur einer übrig" den Ausschlag gab |
| **`geloest`** | **Wie oft eine bestehende Zuordnung wieder verworfen wurde** |
| `gepaartCs` / `nurVatsimCs` | Die Rufzeichen — welche erkannt wurden und welche nur VATSIM kennt |
| `gsFehlt` | uId → gemessene Geschwindigkeit (m/s) bei Flugzeugen, die sich bewegen, aber 0 melden |

**`geloest` ist die aussagekräftigste Zahl.** Am Bildschirm sieht man, *dass* Rufzeichen
dastehen — aber nicht, wie oft eine Zuordnung dazwischen gekippt ist. Bleibt sie bei null,
trägt das Merken; steigt sie, sind die Schranken oder `_PAARUNG_LOESEN_TAKTE` falsch gewählt.

`nurVatsimCs` beantwortet die häufigste Rückfrage aus dem Cockpit („warum hat *das* keine
Live-Daten?"): Wo vPilot nichts gespawnt hat, gibt es im Simulator nichts Schnelleres.

Belegte Werte (16.08.2026, zwei Messungen wenige Minuten auseinander):

| Fassung | Sim | VATSIM | zugeordnet | gelöst |
|---|---|---|---|---|
| „genau einer im Umkreis" | 26 | 15 | **3** | 0 |
| Vorsprung zum Zweitbesten | 30 | 16 | **16** | 0 |

**Datensatz `kind="vatsim-latenz"`** (seit v13.4.0): Wie weit hinken die VATSIM-Positionen
hinter der Wirklichkeit her? Gemessen am **eigenen** Flugzeug — dem einzigen, das in beiden
Quellen steht und dessen Zuordnung feststeht; es braucht also kein Matching, um das Matching zu
vermessen. Abstand zwischen Sim-Position und gemeldeter VATSIM-Position, geteilt durch die
eigene Geschwindigkeit. Zwölf Proben, gemeldet wird der **Median**.

Zwei Bedingungen, ohne die die Messung wertlos ist:

- **> 60 kt** — darunter wird der Quotient instabil, im Stand ist er undefiniert.
- **Kursabweichung ≤ 10°** (`kurs` je Probe). Der erste Messflug war eine **Platzrunde**, und
  dort misst der Abstand die *Sehne* statt der Strecke: Er blieb bei 1,2–1,4 km, obwohl die
  Geschwindigkeit zwischen 60 und 96 kt schwankte. Der Median von 29,3 s war damit zufällig
  fast richtig, aber unbelegt. Die Pflicht kostet nichts — der VATSIM-Kurs *ist* der Kurs von
  vor einer halben Minute; weicht er ab, wurde gekurvt.

**Ergebnis: 29 s** (Median 28,9; Spanne 27,2–30,5). Belastbar, weil der Abstand **mit der
Geschwindigkeit mitwächst**: 1494 m bei 97 kt, 1714 m bei 113 kt — nachgerechnet ergibt
113 kt × 29 s = 1685 m. Die frühere Annahme „bis zu einer Minute" war fast doppelt so hoch.

> **Merksatz:** Ein plausibler Wert ist noch kein gemessener. Erst das erwartete *Verhalten*
> der Messgröße macht sie belastbar.

**Datensatz `kind="sim-verkehr-start"`** (seit Kniebrett-Paket 1.7.0): Einmal je Sitzung, beim
**ersten** Abruf — und zwar **bevor** über die Liste entschieden wird, also auch bei `null` und
bei leerer Liste. Genau diese Meldung fehlte, als sie gebraucht wurde: Zwischen 1.5.0 und 1.6.0
lieferte `GET_AIR_TRAFFIC` gar nichts, weil die Vorbedingung fehlte (s. `architecture.md`), und
weil `sim-verkehr` nur bei **nichtleerer** Liste feuert, hinterließ der Fehler keine Spur. Ein
Ausbleiben war von „gerade kein Verkehr in der Nähe" nicht zu unterscheiden.

| Feld | Bedeutung |
|------|-----------|
| `coherentDa` | Gibt es `Coherent.call` überhaupt? |
| `viewListener` | `angemeldet` / `nicht angemeldet` — die Vorbedingung `JS_BIND_BINGMAP`. Steht hier etwas anderes als `angemeldet`, ist alles Weitere hinfällig |
| `typ` | `Object.prototype.toString` der Rückgabe — `[object Array]` oder eben nicht |
| `anzahl` | Länge der Rohliste, `null` wenn kein Array |
| `felder` | Feldnamen des **Roh**satzes (`__Type`, `name`, `plane_model_icao`, `uId`, `lat`, `lon`, `alt`, `heading`, `isOnGround`) |

**Merksatz:** Eine Diagnose, die nur den Erfolgsfall meldet, ist im Fehlerfall wertlos.

**Datensatz `kind="zeichnen"`** (v12.5.2 bis v12.5.5, wieder ausgebaut): Hat gemessen, ob die
Engine während des Flackerns überhaupt noch Bilder zeichnet — zwei kleine Anzeigen im Panel,
eine auf der Karte, eine daneben, je mit Sekundenzähler und einem per `requestAnimationFrame`
wandernden Punkt.

**Ergebnis:** 22,5 Bilder pro Sekunde, auf die Nachkommastelle konstant, längste Pause 80 ms,
keine Aussetzer — und beide Punkte liefen durchgehend weiter, während die Karte flackerte.
Damit fielen alle Erklärungen weg, die auf Stocken, Einfrieren oder gedrosseltem `rAF`
beruhen; die eigentliche Ursache stand kurz darauf fest (Leaflets `mix-blend-mode`, s. u.).

**Warum es wieder raus ist — und die Lehre daraus:** Die Messschleife hat in *jedem* Bild ein
`transform` gesetzt und damit dauerhaft eine Neuzeichnung angestoßen. Genau das hat das
Flackern während der Messung von „alle paar Sekunden weg" auf „hochfrequent" verstärkt. Ein
Dauer-Messmittel im Renderpfad verändert sein eigenes Messobjekt: als Sonde brauchbar, als
Inventar gefährlich. Wer so etwas wieder einbaut, baut es hinterher auch wieder aus.

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
| `<use href="…">` **ohne** `xlink:href` | zeichnet nichts — siehe unten, betraf **alle** Symbole der App |
| `Cache-Control` | wird nicht zuverlässig befolgt |
| CSS `gap` (Flex/Grid) | `CSS.supports('gap','1px')` = false; Abstand fällt ersatzlos weg — `margin` benutzen |
| CSS `position: sticky` | nicht unterstützt |
| `IntersectionObserver` | nicht vorhanden |
| **Jede** Schriftdatei | siehe unten — die Engine nimmt überhaupt keine an |
| **Waagerechtes Scrollen** | siehe unten — technisch möglich, aber nicht bedienbar |
| `localStorage` **über einen Sim-Neustart** | siehe unten — schreibt und liest innerhalb der Sitzung, hält aber nicht; Cookies halten |

**Leaflet läuft grundsätzlich einwandfrei** (Karte, Marker, Popups) — es ist kein generelles
„alte Engine"-Problem, sondern diese konkreten Lücken. Eine Ausnahme gibt es, und sie ist
keine Coherent-Lücke, sondern ein Simulator-Fehler: siehe unten.

### Kein einziges Symbol war je sichtbar: `href` am `<use>` (geklärt 14.08.2026)

**Symptom:** Im Panel erscheint kein Bediensymbol — kein Zurück-Pfeil, kein Schließen-Kreuz,
kein Vollbild-Zeichen. Der Knopf selbst ist da und funktioniert.

**Ursache:** Coherent GT meldet sich als
`AppleWebKit/604.1.38 (KHTML, like Gecko) Chrome/49.0.2623 Safari/604.1.38 CoherentGT/2.0`
(echter User-Agent aus `panel_diag`). Das SVG-2-Attribut `href` am `<use>`-Element kennt
Chrome erst ab Version **50** — eine Version zu spät (MDN `browser-compat-data`,
`svg.elements.use.href`: Chrome 50, Safari 12.1). Das alte `xlink:href` versteht jede Version.
Unser `icon()` schrieb ausschließlich `href`.

**Fix:** Beide Attribute setzen. Sind beide da, gewinnt `href` (SVG-2-Regel) — moderne Browser
verhalten sich unverändert. Gesichert durch `test_jedes_use_hat_xlink_fallback`, der über die
ganze `index.html` läuft.

**Warum das so lange unentdeckt blieb — die eigentliche Lehre:**

- Der Fehler *sieht aus* wie ein Layout-Problem. Die Messung vom selben Tag steht im Code:
  „Knopf 44x44, SVG 20x20, richtig platziert, nur eben nichts gezeichnet." Alles stimmte —
  gemessen wurde nur nie die Bounding-Box des **Inhalts** (`getBBox()`), und die war 0. Das
  äußere `<svg>` hat seine Größe immer, egal ob der Verweis ins Leere läuft.
- Die Selbstdiagnose hatte einen blinden Fleck: `probeGlyphs` prüft, ob die *Schriftzeichen*
  fehlen (⛶, ✕, →) — und beantwortete damit scheinbar die Symbol-Frage. Dass die
  **Ersatz**-Symbole ankommen, hat niemand gemessen. Genau in dieser Lücke saß der Fehler.
  Deshalb gibt es jetzt `probeSprites` (`base.sprites` im Bericht): es vergleicht `href` gegen
  `xlink:href` und misst zusätzlich ein Symbol aus dem echten Markup.
- Der ganze Icon-Umbau (Phase 1, „Bediensymbole als SVG statt fehlender Glyphen") hat deshalb
  nie gewirkt: Die Zeichen wurden korrekt ersetzt, die Ersatz-SVGs kamen nur nie an.
- Ein Einzelfall war schon aufgefallen (die Glocke) und wurde mit einem inline gezeichneten
  Pfad umgangen — ein Pflaster über einer unerkannten Wurzel. Wenn genau ein Element eine
  Sonderbehandlung braucht, damit es funktioniert, ist das der Hinweis, die Klasse dahinter zu
  suchen, statt die Ausnahme festzuschreiben.

**Merksatz:** Bei „Element ist da, zeichnet aber nichts" gehört die Frage nach der
Attribut-**Schreibweise** an den Anfang. Die Engine ist von 2016 — jede Web-Neuerung ab 2016
ist verdächtig, auch eine, die heute selbstverständlich aussieht.

### Kartenflackern: ein Simulator-Fehler, kein Fehler von uns (geklärt 14.08.2026)

**Symptom:** Die Karte im Panel flackert, verschwindet für Sekunden, kommt beim Bewegen
zurück. In VR so stark, dass die Kartenansichten unbrauchbar sind.

**Ursache:** Leaflet **1.9.4** setzt auf jede Kachel `mix-blend-mode: plus-lighter`
(`leaflet.css`, Verweis auf Chromium-Bug 600120; neu in 1.9.4 durch Leaflet PR #8891 — in
1.9.3 nicht enthalten). In MSFS 2024 zerlegt genau diese Regel die Karte.

**Das ist von Asobo bestätigt.** Sylvain (FlyingRaccoon) im DevSupport-Forum, 28.05.2025:
„So far, we just know it's related to the `mix-blend-mode: plus-lighter` css rule." Betroffen
ist *jedes* Addon mit Leaflet-Karte im EFB (AzurPoly, PMDG, Fenix, NextGen …), gemeldet seit
der 2024er-Veröffentlichung, in MSFS 2020 trat es nie auf.

**Fix** (in `app/static/index.html`, nur unter `html.vr-panel`):

```css
html.vr-panel .leaflet-container img.leaflet-tile { mix-blend-mode: unset !important; }
```

Auf der Website bleibt die Regel: Dort erfüllt sie ihren Zweck (Nähte beim Einblenden frisch
geladener Kacheln) und dort hat nie etwas geflackert. Im Panel ist die Einblendung ohnehin
abgeschaltet (`fadeAnimation: false`), die Regel hat dort also gar keine Aufgabe.

**Warum fünf Runden Eigen-Diagnose daran vorbeiliefen** — als Warnung für das nächste Mal:
Jede DOM-Messung sah sauber aus (30 s lang unveränderte Kacheln, volle Deckkraft, 22,5
Bilder/s ohne einen Aussetzer), weil die Regel erst beim *Zusammensetzen* des Bildes wirkt.
Zwei echte Funde unterwegs (Leaflets Kachel-Einblendung, der `.scanline`-Zierstreifen) haben
den Verdacht zusätzlich im eigenen Code gehalten. Sogar die entscheidende Beobachtung des
Nutzers — „das OpenAIP-Overlay flackert als Einziges nicht" — steht wortgleich im
DevSupport-Thread (*„it only seems to affect the basemap"*).

→ **Merksatz:** Bei einem Symptom, das nur im Sim auftritt und dessen DOM-Messungen alle
sauber sind, gehört eine Netzrecherche in DevSupport/Foren an den **Anfang**, nicht ans Ende.
Andere Addon-Entwickler stoßen auf dieselben Engine-Fehler, und dort stand die Antwort seit
über einem Jahr.

Quellen:
[DevSupport 10552](https://devsupport.flightsimulator.com/t/msfs2020-aircraft-custom-map-flickering-on-html-gauge/10552),
[DevSupport 16967](https://devsupport.flightsimulator.com/t/constant-flickering-with-leaflet-added-onto-an-html-instrument/16967)

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

## `localStorage` überlebt keinen Sim-Neustart (geklärt 16.08.2026)

**Symptom:** Das Kniebrett merkt sich keine Karteneinstellung — nach jedem Start wieder
OpenFlightMap, Ebenen aus, Track-up und Moving Map aus. Im Browser hält alles.

**Die Falle:** Die Sonde in der Selbstdiagnose meldet `features.localStorage: true`. Das ist
keine Fehlmessung, sondern ihre Grenze — sie schreibt und liest im **selben Atemzug** und kann
„funktioniert" von „überlebt einen Neustart" gar nicht unterscheiden. Wer sich auf sie verlässt,
sucht den Fehler anschließend im Anwendungscode, wo keiner ist.

**Der Beleg** kommt aus der aufgezeichneten Diagnose, nicht aus dem Code. `panel_diag`
`kind="karte"` mit `anlass="bereit"` trägt in `kaesten[]` den Zustand **beim Kartenaufbau**;
`anlass="basis:…"` bzw. `"overlay-an:…"` halten jede spätere Wahl fest. Beides
gegeneinandergelegt ergibt für jeden Start: Was war zuletzt gewählt, und was kam zurück?

```sql
SELECT created_at, payload_json FROM panel_diag WHERE kind='karte' ORDER BY id;
```

Über 40 Starts kam eine vom Standard abweichende Basiskarte meist **nicht** zurück. Entscheidend
ist aber ein einzelner Datensatz: Am 16.08.2026 um 16:28 startete das Panel mit **`Light`** — dem
Wert von 14:59 — obwohl um 15:21 **`Satellit`** gewählt worden war. Ein *veralteter* Wert
schließt einen Anwendungsfehler aus: Der Code liest den Schlüssel oder liest ihn nicht; einen
früheren Stand kann nur die Speicherschicht selbst liefern.

**Cookies halten dagegen.** Das Login-Gate ist aktiv (`forum_login_enabled = 1`), und der erste
Panel-Aufruf einer frischen Sitzung bekommt `200 OK` **ohne** vorherige Anmeldung — das
Anmelde-Cookie war also schon vor dem ersten Byte da. Genau das schafft `localStorage` nicht.

→ Alle Karten-Merker liegen seit v13.6.0 in einem Cookie (`fs_karte`, s. `docs/architecture.md`).
`localStorage` bleibt Rückfallebene und Quelle der einmaligen Übernahme.

**Merksatz:** Eine Fähigkeitssonde beantwortet „ist da?", nie „hält?". Für alles, was einen
Neustart überstehen soll, ist der einzige gültige Test ein Wert, der **vor** der Sitzung
geschrieben wurde — im Zweifel die eigene Aufzeichnung über mehrere Starts.

### Nachtrag: Cookies brauchen im Panel `SameSite=None` (16.08.2026)

Der erste Anlauf ersetzte `localStorage` durch ein Cookie mit `SameSite=Lax` — und das Panel
merkte sich **weiterhin nichts** (Start 19:20 wieder auf OpenFlightMap, obwohl um 19:16 `Dark`
gewählt war). Der Grund steht schon im Bericht der Selbstdiagnose: `features.inIframe: true`.

Das Panel läuft in einem iframe unter **fremder Oberseite**. Damit ist jedes Cookie dort
Drittanbieter-Kontext, und ein `Lax`-Cookie wird gar nicht erst abgelegt. Nötig ist
`SameSite=None; Secure` — und `None` **ohne** `Secure` verwirft der Browser komplett, über HTTP
muss also auf `Lax` zurückgefallen werden.

**Das Vorbild stand die ganze Zeit im Projekt:** `_iframe_samesite()` in `app/main.py` setzt für
das Sitzungs-Cookie aus genau diesem Grund `none`, samt Begründung im Docstring. Es wurde als
*Beleg* benutzt („Cookies halten im Kniebrett"), aber nie *gelesen*.

**Merksatz:** Wenn im Projekt schon etwas nachweislich im Panel funktioniert, ist es nicht nur
der Beleg, dass der Weg trägt — es ist die **Vorlage**. Erst seine Konfiguration lesen, dann die
eigene schreiben. Die Tests waren gegen diesen Fehler blind, weil sie gegen eine Cookie-Attrappe
liefen, die `SameSite` nicht kennt: Eine Attrappe kann nur prüfen, was sie nachbildet.

**Seit v13.6.2 misst die Selbstdiagnose das mit** (`speicher` im `report`):

| Feld | Frage |
|---|---|
| `schreibbar` | Lässt sich überhaupt ein Cookie setzen und sofort zurücklesen? `false` = gesperrt |
| `merkerDa` | Lag `fs_karte` schon **vor** dieser Sitzung vor? Das ist die eigentliche Frage |
| `merkerInhalt` | Welche Schlüssel stehen drin — trennt „leer angelegt" von „gefüllt" |
| `lsSchlüssel` | Wie viele `localStorage`-Einträge es gibt, zum Vergleich |

`features.localStorage` beantwortet davon **nichts** — es schreibt und liest im selben Atemzug.
