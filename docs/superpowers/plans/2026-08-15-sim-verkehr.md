# Verkehr aus dem Simulator — Implementation Plan (Teilprojekt 2a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das Kniebrett zeigt den Verkehr, den der Simulator kennt — jede Sekunde, exakt, auch ohne VATSIM-Verbindung.

**Architecture:** Die EFB-App ruft `Coherent.call('GET_AIR_TRAFFIC')` im Sekundentakt ab, rechnet die Einheiten um, leitet die Grundgeschwindigkeit aus Positionsdifferenzen ab und reicht eine fertige Liste per `postMessage` in die Seite. Dort landet sie in **denselben** Ablagen, die der VATSIM-Feed aus Teil 1 benutzt (`_verkehrRoh`, `_verkehrMarker`) — der zeichnende Teil erfährt nicht, wer geliefert hat. Genau eine Quelle ist aktiv; solange der Sim frisch meldet, unterbleibt der Netzabruf.

**Tech Stack:** TypeScript + esbuild (`msfs-panel/PackageSources/FriesenSpy`), Vanilla JS + Leaflet (`app/static/index.html`), pytest

**Spec:** `docs/superpowers/specs/2026-08-15-sim-verkehr-design.md`

## Global Constraints

- **Sprachstand `index.html` ist ES2017.** Verboten sind `?.`, `??`, Spread und `flatMap` — ein Parserfehler dort tötet das ganze `<script>`. `padStart`, `Object.entries`, Pfeilfunktionen und Template-Literale sind in Ordnung und stehen bereits drin.
- **Nur eine Stelle bewegt Marker:** `_naviTakt`. Der Rohwert (`_verkehrRoh`) bleibt vom gezeichneten Ort getrennt, und der Zeitstempel wird **nur bei wirklich neuen Koordinaten** gesetzt — sonst springen die Marker zurück (der Fehler, der bei den Friesen drei Anläufe gekostet hat).
- **Einheiten aus dem Simulator, belegt:** `alt` in **Metern**, `heading` in **Grad**, Schlüssel `uId`, Takt 1000 ms. Belege in Abschnitt 2 der Spec. Diese vier Werte nicht „vereinfachen".
- **Nicht anfassen:** alles, was die parallele Sitzung auf `platzrunden-karte` baut — neue Blöcke **vor** dem Verkehrs-Block, `liveOverlays`, `app/static/data/`, `tests/test_platzrunden.py`, `tests/test_fse.py`. Diese Arbeit hier bleibt im Verkehrs-Block, im Nachrichten-Empfänger und in `msfs-panel/`.
- **Changelog:** Version **12.10.0**. 12.8.0 und 12.9.0 gehören der anderen Sitzung. `highlight` bleibt `false` — das setzt allein der Betreiber. Im JSON **typographische** Anführungszeichen (`„…"`), keine geraden.
- **Kein Heredoc.** Dateien werden mit Write/Edit geschrieben, nie mit `cat > datei <<EOF`.
- **Direkt auf `main`, kein PR-Umweg, nach jedem Task committen und sofort pushen.**
- **Tests:** `python -m pytest tests/ -q` (Vollauf ~140 s). Frontend- und Panel-Verhalten wird über den Quelltext geprüft — Muster in `tests/test_vr_panel.py` (`INDEX`, `PANEL_TSX`, `@ohne_panel`).
- **Doku wird mitgeführt:** `docs/architecture.md`, `docs/efb-panel-debugging.md`, `README.md`.

---

### Task 1: Die Sonde ausbauen

Sie hat ihre Frage beantwortet (6 = 6), und ihre festen Termine gehen am Arbeitsablauf vorbei. An ihre Stelle tritt in Task 6 eine Diagnose aus dem echten Zulieferer. Die **Gegenprobe gegen VATSIM** bleibt — sie ist das, was eine Messung überhaupt erst lesbar macht.

**Files:**
- Modify: `msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx`
- Modify: `app/static/index.html`
- Modify: `tests/test_vr_panel.py`

**Interfaces:**
- Produces: `_diagnoseMitVergleichMelden(art, befund)` — dieselbe Funktion wie bisher `_sondeMitVergleichMelden`, nur mit der Diagnose-Art als erstem Parameter. Task 6 benutzt sie.

- [ ] **Schritt 1: Die Tests der alten Sonde entfernen**

In `tests/test_vr_panel.py` ersatzlos streichen: `_sonde_rumpf`, `_sonde_melden_rumpf` und alle Tests, die sie oder `_SONDE_ZEITPUNKTE` benutzen (`test_sonde_ist_selbstbegrenzt`, `test_sonde_misst_nicht_nur_in_den_ersten_minuten`, `test_sonde_wird_gegen_vatsim_gegengeprueft`, `test_sonde_kann_den_panel_start_nicht_zerreissen`, `test_sonde_meldet_keine_fremden_positionen`, `test_sonde_meldung_traegt_die_quelle`, `test_sonde_greift_auf_die_richtige_referenz_zu`, `test_sonde_wird_mit_zwei_argumenten_gemeldet`).

`test_sonde_greift_auf_die_richtige_referenz_zu` prüft mit `assert ".current" not in PANEL_TSX` etwas, das weiter gelten soll (React-Syntax statt `NodeReference.instance` — der Fehler ist schon einmal passiert). Diesen einen Test **behalten** und umbenennen:

```python
@ohne_panel
def test_panel_benutzt_nodereference_nicht_react():
    """FSComponent.createRef liefert eine NodeReference mit .instance -- NICHT .current wie
    React. Der Griff daneben kostet keinen Compilerfehler, nur eine Funktion, die zur Laufzeit
    nichts tut."""
    assert ".instance" in PANEL_TSX
    assert ".current" not in PANEL_TSX
```

Zwei neue Tests, die den Ausbau festhalten:

```python
@ohne_panel
def test_alte_sonde_ist_raus():
    """Feste Termine nach dem Oeffnen der App treffen den richtigen Moment nur zufaellig: Der
    Nutzer laedt erst den Flug -- dann ist das Tablet schon offen -- und verbindet ERST DANACH
    vPilot. Genau daran ist die erste Messung gescheitert (dreimal 'null Flugzeuge', alle drei
    vor der Verbindung). Ersetzt durch eine Diagnose aus dem echten Zulieferer, s. Task 6."""
    assert "_SONDE_ZEITPUNKTE" not in PANEL_TSX
    assert "sondeMessen" not in PANEL_TSX
    assert "traffic-sonde" not in INDEX


def test_gegenprobe_gegen_vatsim_bleibt():
    """Eine Null ohne Vergleich beantwortet nichts. 'Sim 0, VATSIM 7' ist eine Antwort,
    'Sim 0, VATSIM 0' ist keine -- deshalb haengt an jeder Diagnose die Zahl der Flugzeuge,
    die VATSIM im selben Moment in der Naehe kennt."""
    assert "function _diagnoseMitVergleichMelden(" in INDEX
    assert "vatsimNah" in INDEX
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_vr_panel.py -q -k "sonde or gegenprobe or nodereference"`
Expected: FAIL — `_SONDE_ZEITPUNKTE` steht noch in `PANEL_TSX`, `_diagnoseMitVergleichMelden` fehlt

- [ ] **Schritt 3: Panel-Seite ausbauen**

In `msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx` ersatzlos entfernen:
- den Kommentarblock und `const _SONDE_ZEITPUNKTE = [...]`
- das Feld `private sondeTermine: ReturnType<typeof setTimeout>[] = [];`
- die Methoden `sondeMessen` und `sondeMelden`
- in `onAfterRender` die Zuweisung `this.sondeTermine = _SONDE_ZEITPUNKTE.map(...)`
- in `destroy` die Zeile `this.sondeTermine.forEach((t) => clearTimeout(t));`

`onAfterRender` bleibt damit:

```ts
  /** @inheritdoc */
  public onAfterRender(node: VNode): void {
    super.onAfterRender(node);
    window.addEventListener("message", this.onNachricht);
  }
```

- [ ] **Schritt 4: Seiten-Seite umbenennen**

In `app/static/index.html`: `_sondeMitVergleichMelden(befund)` heißt jetzt `_diagnoseMitVergleichMelden(art, befund)`. Nur die Signatur und die eine Meldezeile ändern sich, der Kommentarkopf darüber wird auf den neuen Zweck umgeschrieben:

```js
/**
 * Eine Diagnose melden -- und ihr die Gegenprobe gegen VATSIM anhaengen.
 *
 * Das ist der Kern des Verfahrens, nicht Beiwerk: Eine Zahl aus dem Simulator ist fuer sich
 * genommen nicht lesbar. Erst neben der Zahl der Flugzeuge, die VATSIM im selben Moment im
 * 75-km-Umkreis kennt, wird sie zur Aussage -- "Sim 0, VATSIM 7" ist eine Antwort,
 * "Sim 0, VATSIM 0" ist keine. Die erste Messung (15.08.2026) war ohne diesen Vergleich
 * wertlos: dreimal null, jedes Mal vor der vPilot-Verbindung gemessen.
 *
 * 75 km ist bewusst etwas mehr als vPilots Injektionsradius von ~40 NM -- lieber ein paar
 * Flugzeuge zu viel gezaehlt als eine Gegenprobe, die faelschlich null meldet.
 */
function _diagnoseMitVergleichMelden(art, befund) {
  const melden = function () {
    try { window._panelDiag(art, befund); } catch (e) {}
  };
  if (!_simPos || !_simPosFrisch()) {
    befund.vatsimNah = null;   // ohne eigene Position keine Gegenprobe moeglich
    melden();
    return;
  }
  befund.eigenLat = Number(_simPos.lat.toFixed(3));
  befund.eigenLon = Number(_simPos.lon.toFixed(3));
  fetch('/api/traffic?lat=' + _simPos.lat.toFixed(4) + '&lon=' + _simPos.lon.toFixed(4) + '&r=75')
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { befund.vatsimNah = d ? (d.traffic || []).length : null; })
    .catch(function () { befund.vatsimNah = null; })
    // Gemeldet wird in JEDEM Fall -- eine fehlgeschlagene Gegenprobe darf die Messung
    // nicht verschlucken.
    .then(melden, melden);
}
```

Im Empfänger `_initPanelShellKanal` den Zweig für die alte Sonde streichen:

```js
    if (d.art === 'panel-diag' && d.befund && typeof window._panelDiag === 'function') {
      _sondeMitVergleichMelden(d.befund);
      return;
    }
```

- [ ] **Schritt 5: Tests laufen lassen**

Run: `python -m pytest tests/test_vr_panel.py -q`
Expected: PASS

- [ ] **Schritt 6: Commit und Push**

```bash
git add msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx app/static/index.html tests/test_vr_panel.py
git commit -m "Sonde ausgebaut, Gegenprobe bleibt

Ihre Frage ist beantwortet (Sim 6, VATSIM 6). Die festen Termine nach dem
Oeffnen der App treffen den richtigen Moment ohnehin nur zufaellig.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

---

### Task 2: Panel — den Verkehr abrufen

**Files:**
- Modify: `msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx`
- Test: `tests/test_vr_panel.py`

**Interfaces:**
- Produces: Nachricht `{ quelle: "friesenspy-shell", art: "sim-verkehr", liste: SimVerkehrEintrag[] }`; Empfang von `{ quelle: "friesenspy", art: "verkehr-schalter", an: boolean }`
- Produces: `SimVerkehrEintrag = { id: number, lat: number, lon: number, alt: number, hdg: number, gs: number, ac: string, cs: string, gnd: boolean }` — `alt` in **Fuß**, `hdg` in Grad 0–359, `gs` in Knoten

- [ ] **Schritt 1: Failing tests schreiben (an `tests/test_vr_panel.py` anhängen)**

```python
# --- Sim-Verkehr (Teilprojekt 2a) ------------------------------------------------------

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
    assert "FUSS_JE_METER" in PANEL_TSX
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
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_vr_panel.py -q -k verkehr`
Expected: FAIL — `AssertionError` bzw. `ValueError: substring not found`

- [ ] **Schritt 3: Konstanten und Typ ergänzen**

In `FriesenSpy.tsx` nach `POSITION_HERZSCHLAG_MS` einfügen:

```ts
/**
 * Wie oft der Verkehr aus dem Simulator geholt wird.
 *
 * Eine Sekunde ist nicht geschaetzt, sondern Asobos eigener Takt in seiner eigenen VFR-Karte
 * (`VfrTrafficManager.POLL_INTERVAL = 1000` im ausgelieferten `GameVFRMap.js`). Zwischen zwei
 * Abrufen rechnet die Seite die Positionen fort -- genau wie Asobos Karte es tut.
 */
const VERKEHR_INTERVALL_MS = 1000;

/**
 * So lange darf ein Abruf hoechstens dauern.
 *
 * `Coherent.call` kann haengen bleiben; das offizielle SDK laesst ihn deshalb gegen eine
 * Sekunde antreten (`Promise.race([Coherent.call(…), Wait.awaitDelay(1000)])`). Ohne diese
 * Grenze bliebe der Riegel gegen Doppelaufrufe im Fehlerfall fuer immer zu.
 */
const VERKEHR_WARTE_MAX_MS = 1000;

/**
 * `alt` kommt aus `GET_AIR_TRAFFIC` in METERN.
 *
 * Nirgends dokumentiert, aber im ausgelieferten Simulator nachzulesen: Das offizielle SDK
 * rechnet in `TrafficInstrument.createContact` mit
 * `UnitType.METER.convertTo(entry.alt, UnitType.FOOT)` um. Ohne diese Zeile stuende an einem
 * Airliner in FL350 die Zahl 10 668 -- und im Label FL107.
 */
const FUSS_JE_METER = 3.28084;

/** Hoechstens so viele Flugzeuge in die Seite reichen -- wie die Obergrenze in /api/traffic. */
const VERKEHR_MAX = 60;

/** Ein Eintrag, wie ihn `GET_AIR_TRAFFIC` liefert. Alle Felder defensiv als optional. */
interface SimVerkehrRoh {
  uId?: number;
  name?: string;
  plane_model_icao?: string;
  lat?: number;
  lon?: number;
  alt?: number;
  heading?: number;
  isOnGround?: boolean;
}

/** Ein Eintrag, wie ihn die Seite bekommt: fertig gerechnet, in Fuss und Knoten. */
interface SimVerkehrEintrag {
  id: number;
  lat: number;
  lon: number;
  alt: number;
  hdg: number;
  gs: number;
  ac: string;
  cs: string;
  gnd: boolean;
}
```

`PanelNachricht` um das Schalterfeld erweitern:

```ts
interface PanelNachricht {
  quelle?: string;
  art?: string;
  titel?: string;
  text?: string;
  service?: string;
  an?: boolean;
}
```

- [ ] **Schritt 4: Felder und Schalter in der Klasse**

Nach `private letztesSendenMs = 0;` einfügen:

```ts
  /** Ist die Verkehrs-Ebene auf der Seite eingeschaltet? Gemeldet ueber den Rueckkanal. */
  private verkehrAn = false;
  /** Riegel gegen Doppelaufrufe -- das offizielle SDK haelt an derselben Stelle `isBusy`. */
  private verkehrLaeuft = false;
  private letzterVerkehrMs = 0;
  private letzteVerkehrMeldung = "";
  private letztesVerkehrSendenMs = 0;
```

In `onNachricht`, direkt nach dem `ping`-Zweig:

```ts
    // Die Ebene ist aus? Dann wird gar nicht erst abgefragt. Ein Coherent.call je Sekunde,
    // dessen Ergebnis niemand zeichnet, ist Arbeit im Simulator ohne jeden Gegenwert.
    if (d.art === "verkehr-schalter") {
      this.verkehrAn = d.an === true;
      if (!this.verkehrAn) {
        this.letzteVerkehrMeldung = "";
      }
      return;
    }
```

- [ ] **Schritt 5: Abruf und Takt**

Nach `positionSenden` einfügen:

```ts
  /**
   * Den Verkehr aus dem Simulator holen -- oder `null`, wenn das nicht geht.
   *
   * Der Wettlauf gegen eine Sekunde ist kein Feinschliff: `Coherent.call` kann haengen
   * bleiben, und der Riegel in `verkehrTakt` bliebe dann fuer immer zu. Das offizielle SDK
   * macht an derselben Stelle dasselbe.
   */
  private async verkehrHolen(): Promise<SimVerkehrRoh[] | null> {
    const c = (globalThis as { Coherent?: { call(n: string): Promise<unknown> } }).Coherent;
    if (!c || typeof c.call !== "function") {
      return null;
    }
    const abbruch = new Promise<null>((loesen) =>
      setTimeout(() => loesen(null), VERKEHR_WARTE_MAX_MS),
    );
    const daten = await Promise.race([c.call("GET_AIR_TRAFFIC"), abbruch]);
    return Array.isArray(daten) ? (daten as SimVerkehrRoh[]) : null;
  }

  /**
   * Ein Abruf je Sekunde, aber nie zwei gleichzeitig.
   *
   * Warum HIER und nicht in einem setInterval: `onUpdate` ist die Schleife der EFB und laeuft
   * nur, solange die App sichtbar ist -- derselbe Grund wie bei der Positionsmeldung.
   */
  private verkehrTakt(time: number): void {
    if (!this.verkehrAn || this.verkehrLaeuft) {
      return;
    }
    if (time - this.letzterVerkehrMs < VERKEHR_INTERVALL_MS) {
      return;
    }
    this.letzterVerkehrMs = time;
    this.verkehrLaeuft = true;
    const auf = (): void => {
      this.verkehrLaeuft = false;
    };
    void this.verkehrSenden(time).then(auf, auf);
  }

  /** Abrufen, aufbereiten, in die Seite reichen. */
  private async verkehrSenden(jetztMs: number): Promise<void> {
    const ziel = this.rahmenRef.instance ? this.rahmenRef.instance.contentWindow : null;
    if (!ziel) {
      return;
    }
    const roh = await this.verkehrHolen();
    if (roh === null) {
      return;
    }
    const liste = this.verkehrAufbereiten(roh, jetztMs);

    // Dieselbe Regel wie bei der Position, aus demselben Grund: Die Seite verwirft eine
    // Quelle, die schweigt. Bei bewegtem Verkehr aendert sich ohnehin jede Sekunde etwas --
    // der Herzschlag greift nur, wenn die Liste leer bleibt.
    const meldung = JSON.stringify(liste);
    const stillGenugLange = (jetztMs - this.letztesVerkehrSendenMs) >= POSITION_HERZSCHLAG_MS;
    if (meldung === this.letzteVerkehrMeldung && !stillGenugLange) {
      return;
    }
    this.letzteVerkehrMeldung = meldung;
    this.letztesVerkehrSendenMs = jetztMs;

    ziel.postMessage({ quelle: "friesenspy-shell", art: "sim-verkehr", liste: liste }, "*");
  }
```

- [ ] **Schritt 6: Vorläufige Aufbereitung (Task 3 macht sie fertig)**

Damit der Bau in diesem Task schon läuft, eine erste Fassung ohne abgeleitete Geschwindigkeit und ohne Filter — sie wird in Task 3 ersetzt:

```ts
  private verkehrAufbereiten(roh: SimVerkehrRoh[], _jetztMs: number): SimVerkehrEintrag[] {
    const out: SimVerkehrEintrag[] = [];
    for (let i = 0; i < roh.length && out.length < VERKEHR_MAX; i++) {
      const r = roh[i];
      const id = Number(r.uId);
      const lat = Number(r.lat);
      const lon = Number(r.lon);
      if (!isFinite(id) || !isFinite(lat) || !isFinite(lon) || (lat === 0 && lon === 0)) {
        continue;
      }
      out.push({
        id: id,
        lat: Number(lat.toFixed(5)),
        lon: Number(lon.toFixed(5)),
        alt: Math.round(Number(r.alt) * FUSS_JE_METER) || 0,
        hdg: ((Math.round(Number(r.heading)) || 0) % 360 + 360) % 360,
        gs: 0,
        ac: String(r.plane_model_icao || ""),
        cs: String(r.name || ""),
        gnd: r.isOnGround === true,
      });
    }
    return out;
  }
```

- [ ] **Schritt 7: `onUpdate` erweitern**

Der bisherige Rumpf wandert unverändert in `positionTakt`, damit `onUpdate` beide Takte anstößt und keiner den anderen blockiert:

```ts
  /** @inheritdoc */
  public onUpdate(time: number): void {
    super.onUpdate(time);
    this.positionTakt(time);
    this.verkehrTakt(time);
  }

  private positionTakt(time: number): void {
    if (this.positionFehler >= POSITION_MAX_FEHLER) {
      return;
    }
    if (time - this.letztePositionMs < POSITION_INTERVALL_MS) {
      return;
    }
    this.letztePositionMs = time;
    this.positionSenden(time);
  }
```

- [ ] **Schritt 8: Bauen und Tests**

```bash
cd msfs-panel/PackageSources/FriesenSpy && npm run build && cd -
python -m pytest tests/test_vr_panel.py -q
```
Expected: Build ohne TypeScript-Fehler, Tests PASS

- [ ] **Schritt 9: Commit und Push**

```bash
git add msfs-panel/ tests/test_vr_panel.py
git commit -m "Kniebrett: Verkehr aus dem Simulator abrufen

Ein Coherent.call je Sekunde -- Asobos eigener Takt --, mit Riegel gegen
Doppelaufrufe und Wettlauf gegen eine Sekunde, beides aus dem offiziellen SDK.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

---

### Task 3: Panel — Geschwindigkeit ableiten, filtern, deckeln

**Files:**
- Modify: `msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx`
- Test: `tests/test_vr_panel.py`

**Interfaces:**
- Consumes: `SimVerkehrRoh`, `SimVerkehrEintrag`, `verkehrAufbereiten` aus Task 2
- Produces: `verkehrGsAbleiten(id, lat, lon, jetztMs) -> number` (Knoten), `entfernungM(lat1, lon1, lat2, lon2) -> number`

- [ ] **Schritt 1: Failing tests schreiben**

```python
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
def test_stehende_flugzeuge_werden_nicht_gemeldet():
    """Am Heimatplatz stehen sonst dreissig Symbole uebereinander, alle ohne Aussage.
    Rollverkehr dagegen ist am Platz die wertvollste Information ueberhaupt -- deshalb die
    Schwelle an der Geschwindigkeit und nicht an isOnGround allein."""
    stelle = PANEL_TSX.index("private verkehrAufbereiten(")
    rumpf = PANEL_TSX[stelle:PANEL_TSX.index("\n  }", stelle)]
    assert "VERKEHR_STEHT_KT" in rumpf
    assert "gnd" in rumpf or "isOnGround" in rumpf


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
    assert "delete" in rumpf or "verkehrSpur.delete" in PANEL_TSX
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_vr_panel.py -q -k "geschwindigkeit or stehende or eigenes or deckel or spur"`
Expected: FAIL — `ValueError: substring not found` bei `verkehrGsAbleiten`

- [ ] **Schritt 3: Konstanten und Entfernungsrechnung**

Nach `VERKEHR_MAX` einfügen:

```ts
/** Darueber ist der Wert kein Messfehler mehr, sondern Unsinn (SDK: MAX_VALID_GROUND_SPEED). */
const VERKEHR_MAX_GS_KT = 1500;

/**
 * Zeitkonstante der Glaettung, in Sekunden.
 *
 * `2 / Math.LN2` ist der Wert, den das offizielle SDK fuer genau diese Groesse ansetzt
 * (`TrafficContactClass.GROUND_SPEED_TIME_CONSTANT`). Die Rohdaten sind rauschig; ohne
 * Glaettung zappelt die Zahl im Label bei jedem Abruf um zweistellige Betraege.
 */
const VERKEHR_GLAETTUNG_S = 2 / Math.LN2;

/** Darunter gilt ein Flugzeug am Boden als stehend und wird nicht gezeichnet. */
const VERKEHR_STEHT_KT = 5;

/** Naeher und hoehengleicher als das ist kein fremdes Flugzeug -- das sind wir selbst. */
const VERKEHR_EIGEN_M = 150;
const VERKEHR_EIGEN_FT = 100;

/** Erdradius in Metern -- fuer die Entfernung zwischen zwei Meldungen. */
const ERDRADIUS_M = 6371000;

/** Grosskreisentfernung in Metern. Dieselbe Formel wie app/geo.py, nur hier. */
function entfernungM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const bog = Math.PI / 180;
  const dLat = (lat2 - lat1) * bog;
  const dLon = (lon2 - lon1) * bog;
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2)
    + Math.cos(lat1 * bog) * Math.cos(lat2 * bog) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  return 2 * ERDRADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
}
```

- [ ] **Schritt 4: Spur und eigene Position als Felder**

Zu den Feldern der Klasse:

```ts
  /**
   * Letzte Meldung je uId -- die Grundlage der abgeleiteten Geschwindigkeit.
   * `gs: null` heisst "noch nie gerechnet"; der erste Wert wird dann ungeglaettet uebernommen,
   * sonst kroche die Anzeige von 0 aus hoch.
   */
  private readonly verkehrSpur = new Map<number, { lat: number; lon: number; t: number; gs: number | null }>();

  /** Die zuletzt gemeldete eigene Position -- fuer Eigenfilter und Entfernungssortierung. */
  private eigenPos: { lat: number; lon: number; alt: number } | null = null;
```

In `positionSenden`, direkt nach der Plausibilitätsprüfung (`if (!isFinite(lat) || … ) return;`) und **vor** der Änderungsprüfung:

```ts
      // Auch merken, wenn die Meldung gleich als unveraendert verworfen wird: Der Verkehrs-
      // teil braucht sie in JEDEM Takt, nicht nur wenn sich etwas bewegt hat.
      this.eigenPos = { lat: lat, lon: lon, alt: isFinite(alt) ? alt : 0 };
```

- [ ] **Schritt 5: Ableitung der Geschwindigkeit**

```ts
  /**
   * Grundgeschwindigkeit aus zwei aufeinanderfolgenden Positionen, in Knoten.
   *
   * `GET_AIR_TRAFFIC` liefert sie nicht -- beide Auswerter im Simulator rechnen sie selbst
   * aus. Geglaettet wird exponentiell mit der Zeitkonstante des SDK; unplausible Werte
   * (ein Sprung in den Rohdaten, ein neu geladenes Flugzeug) werden verworfen statt angezeigt.
   */
  private verkehrGsAbleiten(id: number, lat: number, lon: number, jetztMs: number): number {
    const vorher = this.verkehrSpur.get(id);
    let gs: number | null = null;
    if (vorher) {
      gs = vorher.gs;
      const dtS = (jetztMs - vorher.t) / 1000;
      if (dtS > 0) {
        const knoten = (entfernungM(vorher.lat, vorher.lon, lat, lon) / 1852) / (dtS / 3600);
        if (isFinite(knoten) && knoten <= VERKEHR_MAX_GS_KT) {
          gs = vorher.gs === null
            ? knoten
            : vorher.gs + (1 - Math.exp(-dtS / VERKEHR_GLAETTUNG_S)) * (knoten - vorher.gs);
        }
      }
    }
    this.verkehrSpur.set(id, { lat: lat, lon: lon, t: jetztMs, gs: gs });
    return gs === null ? 0 : gs;
  }
```

- [ ] **Schritt 6: `verkehrAufbereiten` ersetzen**

Die Fassung aus Task 2 vollständig durch diese ersetzen:

```ts
  /**
   * Aus dem Rohsatz die Liste machen, die die Seite zeichnen kann.
   *
   * Reihenfolge der Filter ist nicht beliebig: Die Geschwindigkeit muss VOR dem Stehen-Filter
   * abgeleitet werden (sonst gibt es nichts zu pruefen), und die Spur muss auch fuer
   * herausgefilterte Flugzeuge fortgeschrieben werden -- sonst faengt die Ableitung bei einem
   * anrollenden Flugzeug jedes Mal von vorn an.
   */
  private verkehrAufbereiten(roh: SimVerkehrRoh[], jetztMs: number): SimVerkehrEintrag[] {
    const eigen = this.eigenPos;
    const gesehen = new Set<number>();
    const mitAbstand: { d: number; e: SimVerkehrEintrag }[] = [];

    for (let i = 0; i < roh.length; i++) {
      const r = roh[i];
      const id = Number(r.uId);
      const lat = Number(r.lat);
      const lon = Number(r.lon);
      if (!isFinite(id) || !isFinite(lat) || !isFinite(lon) || (lat === 0 && lon === 0)) {
        continue;
      }
      gesehen.add(id);

      const altFt = Math.round(Number(r.alt) * FUSS_JE_METER) || 0;
      const gs = Math.round(this.verkehrGsAbleiten(id, lat, lon, jetztMs));
      const abstand = eigen ? entfernungM(eigen.lat, eigen.lon, lat, lon) : 0;

      // Wir selbst. Nach heutigem Stand steht das eigene Flugzeug gar nicht in der Liste --
      // aber falls doch, laege sein Symbol genau ueber dem eigenen.
      if (eigen && abstand < VERKEHR_EIGEN_M && Math.abs(altFt - eigen.alt) < VERKEHR_EIGEN_FT) {
        continue;
      }
      // Geparkte. Rollende bleiben ausdruecklich drin.
      if (r.isOnGround === true && gs < VERKEHR_STEHT_KT) {
        continue;
      }

      mitAbstand.push({
        d: abstand,
        e: {
          id: id,
          lat: Number(lat.toFixed(5)),
          lon: Number(lon.toFixed(5)),
          alt: altFt,
          hdg: ((Math.round(Number(r.heading)) || 0) % 360 + 360) % 360,
          gs: gs,
          ac: String(r.plane_model_icao || ""),
          cs: String(r.name || ""),
          gnd: r.isOnGround === true,
        },
      });
    }

    // Wer nicht mehr gemeldet wird, fliegt aus der Spur -- sonst waechst die Map ueber einen
    // langen Flug mit jedem Flugzeug, das je in Reichweite war.
    this.verkehrSpur.forEach((_wert, id) => {
      if (!gesehen.has(id)) {
        this.verkehrSpur.delete(id);
      }
    });

    // Naehe entscheidet, nicht die Reihenfolge im Rohsatz -- dieselbe Regel wie in
    // /api/traffic. Ohne eigene Position bleibt die Reihenfolge, wie sie kam.
    mitAbstand.sort((a, b) => a.d - b.d);
    const out: SimVerkehrEintrag[] = [];
    for (let i = 0; i < mitAbstand.length && i < VERKEHR_MAX; i++) {
      out.push(mitAbstand[i].e);
    }
    return out;
  }
```

Beim Ausschalten der Ebene (`verkehr-schalter`, Task 2) die Spur mit leeren:

```ts
      if (!this.verkehrAn) {
        this.letzteVerkehrMeldung = "";
        this.verkehrSpur.clear();
      }
```

- [ ] **Schritt 7: Bauen und Tests**

```bash
cd msfs-panel/PackageSources/FriesenSpy && npm run build && cd -
python -m pytest tests/test_vr_panel.py -q
```
Expected: PASS

- [ ] **Schritt 8: Commit und Push**

```bash
git add msfs-panel/ tests/test_vr_panel.py
git commit -m "Kniebrett: Geschwindigkeit ableiten, geparkte Flugzeuge weglassen

GET_AIR_TRAFFIC liefert keine Grundgeschwindigkeit -- sie kommt aus zwei
aufeinanderfolgenden Positionen, geglaettet mit der Zeitkonstante des SDK.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

---

### Task 4: Seite — Empfang und Umschalter

**Files:**
- Modify: `app/static/index.html` (Verkehrs-Block und `_initPanelShellKanal`)
- Test: `tests/test_vr_panel.py`

**Interfaces:**
- Consumes: Nachricht `art: "sim-verkehr"` aus Task 2
- Produces: `_simVerkehr`, `_simVerkehrFrisch()`, `_verkehrQuelleWechseln(simIstQuelle)`

- [ ] **Schritt 1: Failing tests schreiben**

```python
def test_sim_verkehr_wird_empfangen():
    assert "d.art === 'sim-verkehr'" in INDEX


def test_solange_der_sim_liefert_wird_nicht_abgefragt():
    """Beide Quellen gleichzeitig zu zeichnen hiesse: jedes Flugzeug zweimal, 15 Sekunden
    versetzt. Und der Netzabruf waere Arbeit, die niemand sieht -- ausgerechnet ueber die
    Verbindung des Simulators."""
    stelle = INDEX.index("function _verkehrAbrufen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_simVerkehrFrisch()" in rumpf


def test_beim_quellwechsel_wird_geleert():
    """Beide Quellen schreiben in dieselben Ablagen. Ohne das Leeren blieben die Marker der
    alten Quelle stehen -- und _naviTakt rechnete ihre Position endlos weiter, obwohl niemand
    sie mehr meldet."""
    stelle = INDEX.index("function _verkehrQuelleWechseln(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_verkehrLeeren()" in rumpf


def test_frischewache_benutzt_dieselbe_grenze_wie_die_position():
    """Zwei Grenzen fuer dieselbe Bruecke waeren zwei Wahrheiten darueber, ob der Simulator
    noch da ist."""
    stelle = INDEX.index("function _simVerkehrFrisch(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_SIM_POS_MAX_ALTER_MS" in rumpf
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_vr_panel.py -q -k "sim_verkehr or quellwechsel or frischewache or abgefragt"`
Expected: FAIL — `ValueError: substring not found`

- [ ] **Schritt 3: Zustand und Wache in den Verkehrs-Block**

Direkt nach `let _verkehrNachholer = null;`:

```js
// --------------------------------------------------------------------------
//  Zweite Quelle: der Simulator
// --------------------------------------------------------------------------
// Im Kniebrett weiss der Simulator es besser als VATSIM: jede Sekunde statt alle 15, die
// echte Position statt einer fortgerechneten -- und auch dann, wenn gar keine VATSIM-
// Verbindung besteht (dann ist es der AI-Verkehr des Simulators).
//
// Genau EINE Quelle ist aktiv. Beides gleichzeitig zu zeichnen hiesse: jedes Flugzeug
// zweimal, 15 Sekunden versetzt.
let _simVerkehr = null;             // { ts, liste } -- zuletzt gemeldet, oder null
let _simVerkehrWarQuelle = false;   // wer zuletzt geliefert hat (fuer den Wechsel)

// Dieselbe Grenze wie fuer die eigene Position: Es ist dieselbe Bruecke, und zwei Grenzen
// waeren zwei Wahrheiten darueber, ob der Simulator noch da ist.
function _simVerkehrFrisch() {
  return !!(_simVerkehr && (Date.now() - _simVerkehr.ts) < _SIM_POS_MAX_ALTER_MS);
}

// Der einzige Umschaltpunkt. Beide Quellen schreiben in dieselben Ablagen (_verkehrRoh,
// _verkehrMarker) -- ohne das Leeren blieben beim Wechsel die Marker der alten Quelle stehen,
// und _naviTakt rechnete ihre Position endlos weiter.
function _verkehrQuelleWechseln(simIstQuelle) {
  if (simIstQuelle === _simVerkehrWarQuelle) return;
  _simVerkehrWarQuelle = simIstQuelle;
  _verkehrLeeren();
}
```

- [ ] **Schritt 4: Abruf abschalten, solange der Sim liefert**

In `_verkehrAbrufen`, direkt nach der Zoom-Prüfung (`if (map.getZoom() < _VERKEHR_MIN_ZOOM) …`):

```js
  // Solange der Simulator liefert, ist er die Quelle -- der Netzabruf waere Arbeit, die
  // niemand zeichnet. Faellt er aus, merkt es spaetestens der naechste Takt (15 s) und die
  // Quelle wechselt still zurueck.
  if (_simVerkehrFrisch()) return;
  _verkehrQuelleWechseln(false);
```

- [ ] **Schritt 5: Empfang eintragen**

In `_initPanelShellKanal`, an der Stelle, wo der alte `panel-diag`-Zweig stand:

```js
    if (d.art === 'sim-verkehr') {
      const liste = Array.isArray(d.liste) ? d.liste : [];
      _simVerkehr = { ts: Date.now(), liste: liste };
      _simVerkehrDiagnoseEinmal(liste);
      _verkehrQuelleWechseln(true);
      _simVerkehrUebernehmen(liste);
      return;
    }
```

`_simVerkehrDiagnoseEinmal` kommt in Task 6, `_simVerkehrUebernehmen` in Task 5 — beide werden hier bereits gerufen. Bis dahin bleibt dieser Zweig ungetestet lauffähig, weil er nur im Kniebrett durchlaufen wird; die Reihenfolge der Tasks ist trotzdem einzuhalten.

- [ ] **Schritt 6: Tests laufen lassen**

Run: `python -m pytest tests/test_vr_panel.py -q -k "sim_verkehr or quellwechsel or frischewache or abgefragt"`
Expected: PASS

- [ ] **Schritt 7: Commit und Push**

```bash
git add app/static/index.html tests/test_vr_panel.py
git commit -m "Karte: Sim-Verkehr empfangen, genau eine Quelle aktiv

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

---

### Task 5: Seite — zeichnen

Der zeichnende Teil soll seinen Zulieferer nicht kennen. Deshalb wird der Rumpf von `_verkehrUebernehmen` herausgelöst und von beiden Quellen benutzt — nicht kopiert.

**Files:**
- Modify: `app/static/index.html` (Verkehrs-Block)
- Test: `tests/test_vr_panel.py`

**Interfaces:**
- Consumes: `_verkehrLabel`, `_verkehrPopup`, `makeAircraftIcon`, `_verkehrRoh`, `_verkehrMarker`, `_verkehrFehlt`
- Produces: `_verkehrZeichnen(liste, gemessenTs, schluesselVon)`, `_simVerkehrUebernehmen(liste)`

- [ ] **Schritt 1: Failing tests schreiben**

```python
def test_beide_quellen_zeichnen_ueber_denselben_weg():
    """Zwei Kopien derselben Markerpflege waeren zwei Orte, an denen dieselbe Hysterese, das
    Icon-Sparen und das Popup-Sparen kaputtgehen koennen."""
    assert "function _verkehrZeichnen(" in INDEX
    stelle = INDEX.index("function _verkehrUebernehmen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_verkehrZeichnen(" in rumpf
    stelle = INDEX.index("function _simVerkehrUebernehmen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_verkehrZeichnen(" in rumpf


def test_sim_schluessel_kollidiert_nicht_mit_callsigns():
    """Beide Quellen legen in derselben Ablage ab. Ein Sim-Schluessel muss deshalb erkennbar
    ein Sim-Schluessel sein, auch wenn sich die Quellen einmal ueberschneiden."""
    stelle = INDEX.index("function _simVerkehrUebernehmen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "'sim:'" in rumpf


def test_sim_positionen_gelten_ab_jetzt():
    """Der VATSIM-Feed traegt ein Alter (die Momentaufnahme des Pollers), der Sim nicht -- er
    meldet, was in dieser Sekunde gilt. Ein Alter dazuzurechnen wuerde die Fortrechnung um
    genau diesen Betrag zu weit laufen lassen."""
    stelle = INDEX.index("function _simVerkehrUebernehmen(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "Date.now()" in rumpf


def test_popup_bleibt_lesbar_ohne_callsign():
    """Der Simulator liefert nach heutigem Stand keinen Callsign. Eine leere fette Zeile ganz
    oben im Popup waere ein sichtbarer Fehler."""
    stelle = INDEX.index("function _verkehrPopup(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "Verkehr" in rumpf
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_vr_panel.py -q -k "quellen or schluessel or sim_positionen or lesbar"`
Expected: FAIL — `ValueError: substring not found`

- [ ] **Schritt 3: Den Rumpf herauslösen**

`_verkehrUebernehmen` schrumpft auf den Teil, der wirklich VATSIM-eigen ist:

```js
function _verkehrUebernehmen(liste, ageSek) {
  // Die Fortrechnung muss dort beginnen, wo der Poller die Daten geholt hat, nicht dort, wo
  // die Antwort ankam -- sonst laeuft die Anzeige um das Alter der Momentaufnahme hinterher.
  _verkehrZeichnen(liste, Date.now() - Math.round(ageSek * 1000), function (e) { return e.cs; });
}

// Der Simulator meldet, was in DIESER Sekunde gilt -- kein Alter, nichts nachzuholen.
// Der Schluessel traegt sein Praefix, damit er nie mit einem VATSIM-Callsign kollidieren kann.
function _simVerkehrUebernehmen(liste) {
  _verkehrZeichnen(liste, Date.now(), function (e) { return 'sim:' + e.id; });
}
```

Und der gemeinsame Teil — inhaltlich **unverändert** aus dem bisherigen `_verkehrUebernehmen`, nur mit `schluesselVon(e)` statt `e.cs`:

```js
// Marker anlegen, fortschreiben, aufraeumen -- fuer beide Quellen derselbe Weg. Der
// zeichnende Teil kennt seinen Zulieferer nicht: Er bekommt eine Liste, einen Zeitpunkt, zu
// dem sie gemessen wurde, und eine Vorschrift, wie ein Eintrag zu seinem Schluessel kommt.
function _verkehrZeichnen(liste, gemessenTs, schluesselVon) {
  if (!_verkehrGruppe) return;
  const gesehen = Object.create(null);

  for (let i = 0; i < liste.length; i++) {
    const e  = liste[i];
    const cs = e && schluesselVon(e);
    if (!cs) continue;
    // Das eigene Flugzeug ist hier nicht auszufiltern -- das erledigt der Server ueber die
    // CID, und beim Sim-Verkehr das Panel ueber die Entfernung.
    gesehen[cs] = true;
    delete _verkehrFehlt[cs];

    // Zeitstempel NUR bei wirklich neuen Koordinaten -- sonst faengt die Fortrechnung bei
    // jedem Abruf von vorn an und der Marker springt zurueck. Genau dieser Fehler kostete
    // bei den Friesen drei Anlaeufe (s. Kommentar in updateMap).
    const alt = _verkehrRoh[cs];
    if (!alt || alt.lat !== e.lat || alt.lon !== e.lon) {
      _verkehrRoh[cs] = { lat: e.lat, lon: e.lon,
                          hdg: Number(e.hdg) || 0, gs: Number(e.gs) || 0, ts: gemessenTs };
    }

    const hdg = Math.round(Number(e.hdg) || 0);
    const beschriftung = _verkehrLabel(e, false);
    const popup = _verkehrPopup(e);
    const vorhanden = _verkehrMarker[cs];
    if (vorhanden) {
      if (vorhanden._fsHeading !== hdg) {
        vorhanden.setIcon(makeAircraftIcon(hdg, true));
        vorhanden._fsHeading = hdg;
      }
      if (vorhanden._fsLabel !== beschriftung) {
        vorhanden.setTooltipContent(beschriftung);
        vorhanden._fsLabel = beschriftung;
      }
      // Auch hier nur bei echter Aenderung -- 60 Popups bei jedem Abruf neu zu bauen ist
      // dieselbe unnoetige Arbeit, die beim Tooltip zwei Zeilen darueber vermieden wird.
      if (vorhanden._fsPopup !== popup) {
        vorhanden.setPopupContent(popup);
        vorhanden._fsPopup = popup;
      }
    } else {
      const m = L.marker([e.lat, e.lon], { icon: makeAircraftIcon(hdg, true), rotateWithView: true })
        .bindPopup(popup, { maxWidth: 220 })
        .bindTooltip(beschriftung, { permanent: true, direction: 'bottom', offset: [0, 2],
                                     className: 'traffic-label', opacity: 1 })
        .addTo(_verkehrGruppe);
      m._fsHeading = hdg;
      m._fsLabel = beschriftung;
      m._fsPopup = popup;
      _verkehrMarker[cs] = m;
    }
  }

  // Wer nicht mehr gemeldet wird, verschwindet -- sonst rechnet der Takt eine Position
  // endlos weiter, deren Flugzeug laengst ausser Reichweite ist.
  //
  // Aber erst beim ZWEITEN Fehlen: Der Server kappt hart bei 60 nach Entfernung, ohne
  // Hysterese. Ein Flugzeug auf Rang 60/61 wechselt zwischen zwei Abrufen hin und her, und
  // jedes Loeschen samt Neuanlegen ist im Kniebrett als Aufblitzen sichtbar (derselbe Fund,
  // der schon setIcon aus dem Takt genommen hat). Beim Sim-Verkehr gilt dasselbe -- dort
  // deckelt das Panel.
  for (const cs in _verkehrMarker) {
    if (gesehen[cs]) continue;
    _verkehrFehlt[cs] = (_verkehrFehlt[cs] || 0) + 1;
    if (_verkehrFehlt[cs] < 2) continue;
    _verkehrGruppe.removeLayer(_verkehrMarker[cs]);
    delete _verkehrMarker[cs];
    delete _verkehrRoh[cs];
    delete _verkehrFehlt[cs];
  }
}
```

- [ ] **Schritt 4: Popup ohne Callsign**

In `_verkehrPopup` die Kopfzeile absichern — der Simulator liefert nach heutigem Stand keinen:

```js
  const kopf = String(e.cs || '').toUpperCase() || 'Verkehr';
```
und in der Rückgabe `escHtml(kopf)` statt des bisherigen Ausdrucks.

- [ ] **Schritt 5: Volle Testsuite**

Run: `python -m pytest tests/ -q`
Expected: PASS — insbesondere müssen alle Verkehrs-Tests aus V12.7.0 grün bleiben; sie prüfen genau den Rumpf, der hier verschoben wurde

- [ ] **Schritt 6: Commit und Push**

```bash
git add app/static/index.html tests/test_vr_panel.py
git commit -m "Karte: beide Verkehrsquellen zeichnen ueber denselben Weg

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

---

### Task 6: Seite — Schalter melden und einmal messen

**Files:**
- Modify: `app/static/index.html`
- Test: `tests/test_vr_panel.py`

**Interfaces:**
- Consumes: `_diagnoseMitVergleichMelden(art, befund)` aus Task 1
- Produces: `_verkehrSchalterMelden(an)`, `_simVerkehrDiagnoseEinmal(liste)`

- [ ] **Schritt 1: Failing tests schreiben**

```python
def test_schalter_wird_an_die_shell_gemeldet():
    assert "art: 'verkehr-schalter'" in INDEX
    stelle = INDEX.index("function _setupVerkehrPref(")
    rumpf = INDEX[stelle:INDEX.index("\n}", stelle)]
    assert "_verkehrSchalterMelden" in rumpf


def test_schalter_wird_auch_ohne_klick_gemeldet():
    """Eine gespeicherte Praeferenz schaltet die Ebene beim Aufbau ein, ohne dass jemand
    klickt -- overlayadd feuert dabei nicht zuverlaessig. Ohne diese Meldung bliebe das Panel
    stumm, und der Nutzer saehe eine eingeschaltete Ebene ohne Verkehr."""
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
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `python -m pytest tests/test_vr_panel.py -q -k "schalter or diagnose"`
Expected: FAIL — `ValueError: substring not found`

- [ ] **Schritt 3: Schalter melden**

In den Verkehrs-Block, nach `_loadVerkehrPref`:

```js
// Dem Kniebrett sagen, ob die Ebene an ist. Ohne diese Meldung fragt es den Simulator gar
// nicht erst ab -- ein Coherent.call je Sekunde, den niemand zeichnet, ist Arbeit ohne
// Gegenwert. Ausserhalb des Kniebretts geht die Meldung ins Leere, und das ist richtig so.
function _verkehrSchalterMelden(an) {
  try {
    if (!window.parent || window.parent === window) return;
    window.parent.postMessage({ quelle: 'friesenspy', art: 'verkehr-schalter', an: !!an }, '*');
  } catch (e) {}
}
```

In `_setupVerkehrPref` die beiden Zweige ergänzen:

```js
  map.on('overlayadd',    (e) => { if (e.layer === gruppe) { _saveVerkehrPref(true);  _verkehrSchalterMelden(true);  _verkehrStarten(map); } });
  map.on('overlayremove', (e) => { if (e.layer === gruppe) { _saveVerkehrPref(false); _verkehrSchalterMelden(false); _verkehrStoppen(); } });
```

Und in `_addPreferredVerkehrLayer` — die gespeicherte Präferenz schaltet die Ebene ohne Klick ein:

```js
function _addPreferredVerkehrLayer(map, gruppe) {
  const an = !!(gruppe && _loadVerkehrPref());
  if (an) gruppe.addTo(map);
  // Auch ein "aus" melden: Das Panel startet mit verkehrAn = false, aber nach einem
  // Neuladen der Seite bei eingeschalteter Ebene wuerde sonst niemand ein "an" schicken.
  _verkehrSchalterMelden(an);
}
```

- [ ] **Schritt 4: Die einmalige Diagnose**

Nach `_verkehrQuelleWechseln`:

```js
// Was steht wirklich drin? Die alte Sonde meldete nur die FELDNAMEN -- damit blieb offen,
// ob `name` den Callsign traegt und was `plane_model_icao` enthaelt. Genau davon haengt ab,
// ob Sim-Positionen und VATSIM-Flugplaene zusammengefuehrt werden koennen (Teilprojekt 2b).
//
// Einmal je Sitzung, beim ersten nichtleeren Eintreffen -- mit Rohwerten, mit der groessten
// Entfernung (wie weit reicht der Sim-Horizont?) und mit der Gegenprobe gegen VATSIM.
let _simVerkehrDiagnoseGemeldet = false;

function _simVerkehrDiagnoseEinmal(liste) {
  if (_simVerkehrDiagnoseGemeldet || !liste.length) return;
  _simVerkehrDiagnoseGemeldet = true;
  let weitesteKm = null;
  if (_simPos && _simPosFrisch()) {
    // Leaflet rechnet das bereits -- keine zweite Entfernungsformel in dieser Datei.
    // Denselben Weg geht _verkehrRadiusKm ein paar Zeilen weiter oben.
    const eigen = L.latLng(_simPos.lat, _simPos.lon);
    weitesteKm = 0;
    for (let i = 0; i < liste.length; i++) {
      const km = eigen.distanceTo([liste[i].lat, liste[i].lon]) / 1000;
      if (km > weitesteKm) weitesteKm = Math.round(km);
    }
  }
  _diagnoseMitVergleichMelden('sim-verkehr', {
    anzahl: liste.length,
    weitesteKm: weitesteKm,
    felder: Object.keys(liste[0]),
    ersterEintrag: liste[0],
  });
}
```

Eine eigene Haversine-Funktion gibt es in `index.html` **nicht** und soll auch nicht entstehen: Leaflet bringt `latLng.distanceTo()` mit, und der Verkehrs-Block benutzt genau das schon in `_verkehrRadiusKm`.

- [ ] **Schritt 5: Volle Testsuite**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Schritt 6: Commit und Push**

```bash
git add app/static/index.html tests/test_vr_panel.py
git commit -m "Karte: Ebenen-Schalter ans Kniebrett melden, einmal messen

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

---

### Task 7: Paket bauen, Changelog, Doku

**Files:**
- Modify: `msfs-panel/PackageSources/FriesenSpy/manifest.json`
- Modify: `app/CHANGELOG.json`
- Modify: `docs/architecture.md`, `docs/efb-panel-debugging.md`, `README.md`
- Build: `msfs-panel/Package/`

- [ ] **Schritt 1: Paketversion auf 1.5.0**

In `manifest.json` `package_version` auf `1.5.0` und die Release Notes neu schreiben (deutsch, wie die bestehenden): Verkehr aus dem Simulator im Sekundentakt, geparkte Flugzeuge weggelassen, Sonde entfallen.

- [ ] **Schritt 2: Paket bauen**

```bash
cd msfs-panel/PackageSources/FriesenSpy && npm run build && cd -
powershell -File msfs-panel/build-package.ps1
```
Erwartet: `msfs-panel/Package/` trägt 1.5.0. Beim Nutzer zeigt eine Junction dorthin — ein Sim-Neustart genügt.

**Wichtig:** `Package/` und Quelltext dürfen nicht auseinanderlaufen. Genau das war zuletzt der Fall (Paket 1.4.0 mit alten Sonden-Zeitpunkten, Quelltext schon mit neuen).

- [ ] **Schritt 3: Changelog**

Neuer Eintrag **ganz vorne** in `app/CHANGELOG.json`. Typographische Anführungszeichen, `highlight: false`:

```json
  {
    "version": "12.10.0",
    "date": "2026-08-15",
    "highlight": false,
    "title": "Verkehr aus dem Simulator",
    "items": [
      "✈️ Im Kniebrett kommt der Verkehr jetzt aus dem Simulator selbst — jede Sekunde statt alle 15, und mit der Position, die wirklich gilt, statt einer zwischen zwei Abrufen geschätzten. Die Symbole gleiten, statt zu springen.",
      "📡 Das gilt auch ohne VATSIM-Verbindung: Dann zeigt die Karte den Verkehr, den der Simulator selbst erzeugt. Reißt die Verbindung zum Tablet ab, übernimmt still wieder der bisherige Weg über VATSIM.",
      "🅿️ Geparkte Flugzeuge bleiben weg — am Heimatplatz wären das dreißig Symbole übereinander, keines davon eine Information. Rollende Flugzeuge sind ausdrücklich dabei; am Platz sind sie das Wichtigste, was es zu sehen gibt.",
      "🔬 Der Simulator gibt fremden Verkehr über seine Schnittstelle also doch heraus — das war bis zur Messung am 15.08.2026 die offene Frage des ganzen Vorhabens, und die Antwort erspart ein eigenes Zusatzmodul."
    ]
  },
```

Nach dem Schreiben `python -c "import json; json.load(open('app/CHANGELOG.json', encoding='utf-8'))"` — ein gerades Anführungszeichen im Text zerlegt sonst die Datei.

- [ ] **Schritt 4: Doku**

- `docs/architecture.md`: Abschnitt „Fremdverkehr" um die zweite Quelle erweitern — Panel-Takt, Einheiten mit ihren Belegen, der Umschalter, und die Korrektur der bisherigen Aussage zu DevSupport 4993 (für MSFS 2024 überholt, gemessen 6 = 6).
- `docs/efb-panel-debugging.md`: Feldtabelle `kind="traffic-sonde"` durch `kind="sim-verkehr"` ersetzen (`anzahl`, `weitesteKm`, `felder`, `ersterEintrag`, `vatsimNah`, `eigenLat`, `eigenLon`).
- `README.md`: bei der Karten-Ebene „Verkehr" ergänzen, dass sie im Kniebrett aus dem Simulator gespeist wird.

- [ ] **Schritt 5: Volle Testsuite**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Schritt 6: Commit und Push**

```bash
git add msfs-panel/ app/CHANGELOG.json docs/ README.md
git commit -m "V12.10.0: Verkehr aus dem Simulator

Kniebrett-Paket 1.5.0. GET_AIR_TRAFFIC liefert in MSFS 2024 auch den von
vPilot injizierten Verkehr (gemessen 15.08.2026, Sim 6 zu VATSIM 6) --
DevSupport 4993 ist damit fuer 2024 ueberholt, ein WASM-Modul entfaellt.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

- [ ] **Schritt 7: Ausrollen kontrollieren**

Nicht auf `/health` warten — der **alte** Container antwortet dort die ganze Zeit mit 200, während GitHub Actions noch baut. Stattdessen auf den Inhalt warten:

```bash
until curl -s https://friesenspy.devprops.de/static/index.html | grep -q "_simVerkehrFrisch"; do sleep 20; done; echo "live"
```

---

### Task 8: Abnahme im Simulator

**Files:** keine

- [ ] **Schritt 1: Die zehn Punkte aus Abschnitt 11 der Spec durchgehen**

Reihenfolge, die zum Arbeitsablauf des Nutzers passt: Flug laden → Tablet öffnet → **dann** vPilot verbinden. Der Sim-Verkehr ist davon unabhängig; Punkt 2 (AI-Verkehr ohne vPilot) lässt sich sogar vorher prüfen.

- [ ] **Schritt 2: Die Diagnose auswerten**

`/admin` → Panel-Diagnose, `kind="sim-verkehr"`. Vier Fragen, die dieser eine Datensatz beantwortet:

| Feld | Was es entscheidet |
|---|---|
| `ersterEintrag.cs` | trägt `name` den Callsign? → Zuschnitt von Teil 2b |
| `ersterEintrag.ac` | `C172` oder ein Asobo-interner Modellname? → taugt das Label |
| `ersterEintrag.alt` vs. `vatsimNah` | stimmt die Umrechnung Meter → Fuß |
| `weitesteKm` vs. `vatsimNah` | wie weit reicht der Sim-Horizont |

- [ ] **Schritt 3: Teil 2b zuschneiden**

Erst jetzt, mit dem Befund in der Hand — Spec Abschnitt 8. Trägt `name` den Callsign, ist es eine kleine Ergänzung; ist er leer, wird die Zuordnung über die Position gebaut.

- [ ] **Schritt 4: Forum-Beitrag 9184 korrigieren**

Er behauptet „Der Simulator gibt fremden Verkehr über seine Schnittstelle nicht heraus". Das ist widerlegt. Die Bedingung des Nutzers („erst korrigieren, wenn es funktioniert") ist mit einer bestandenen Abnahme erfüllt.

---

## Self-Review

**Spec-Abdeckung:** Abschnitt 4 (Panel) → Tasks 2 + 3. Abschnitt 5 (Seite) → Tasks 4 + 5 + 6. Abschnitt 7 (Sonde raus, Diagnose rein) → Tasks 1 + 6. Abschnitt 11 (Abnahme) → Task 8. Abschnitt 8 (Teil 2b) ist ausdrücklich **kein** Task dieses Plans — er wird in Task 8 Schritt 3 zugeschnitten.

**Typkonsistenz:** `SimVerkehrEintrag` wird in Task 2 definiert und in Task 3 unverändert weiterbenutzt; die Feldnamen (`ac`, `cs`, `alt`, `gs`, `hdg`) sind genau die, die `_verkehrLabel` und `_verkehrPopup` bereits lesen — deshalb kommt die Seite ohne Übersetzungsschicht aus. `_verkehrZeichnen(liste, gemessenTs, schluesselVon)` wird in Task 5 definiert und von beiden Übernehmern gerufen. `_diagnoseMitVergleichMelden(art, befund)` wird in Task 1 umbenannt und in Task 6 benutzt.

**Bekannte Lücken:**
- Fällt die Sim-Quelle aus, merkt es erst der nächste 15-s-Takt. Bis dahin stehen die letzten Marker. Das ist bewusst so: Die Brücke schickt alle zwei Sekunden ein Lebenszeichen, ein Ausfall heißt praktisch „Tablet zu" — und dann sieht ohnehin niemand hin.
- Was in `ac` steht, ist bis Task 8 unbekannt. Steht dort ein Asobo-Modellname statt eines ICAO-Musters, wird das Label unschön, aber nicht falsch — die Korrektur gehört dann zu Teil 2b.
