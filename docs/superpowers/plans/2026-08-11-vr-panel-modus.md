# VR-Panel-Modus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine neue Route `/panel` liefert dieselbe FriesenSpy-Seite wie `/`, mit einer per
Pfad oder Query-Parameter aktivierbaren CSS-Skalierung, die Text/Abstände/Buttons/Karte
gemeinsam vergrößert — vorbereitet für ein späteres, separat gebautes MSFS-2024-EFB-Panel in VR.

**Architecture:** Rein additiv, keine neue HTML-Datei. Eine neue FastAPI-Route liefert dieselbe
`index.html` wie `/`. Ein kleines Inline-Script im `<head>` erkennt Pfad/Query-Parameter und
setzt eine CSS-Klasse auf `<html>`; eine CSS-Regel unter dieser Klasse skaliert per `zoom`.

**Tech Stack:** FastAPI (`app/main.py`), Vanilla JS/CSS (`app/static/index.html`), pytest.

## Global Constraints

- Login bleibt aktiv — `/panel` bekommt KEINEN Eintrag in `_GATE_ALLOW_PREFIXES`
  (`app/main.py`), läuft durch dasselbe `forum_login_gate` wie jede andere Route.
- Keine zweite HTML-Datei, keine Logik-Duplikation — `/panel` liefert exakt dieselbe Datei wie
  `/` (`app/static/index.html`).
- Volle Funktionalität bleibt unverändert — keine Features werden für den Panel-Modus entfernt
  oder vereinfacht, nur Skalierung kommt hinzu.
- Zoom-Faktor `1.35` ist ein Startwert (Design-Doku:
  `docs/superpowers/specs/2026-08-11-vr-panel-modus-design.md`), nach einem Live-VR-Test durch
  den Nutzer nachjustierbar — beide Tasks schreiben den Wert an genau EINER Stelle, damit das
  Nachjustieren ein Einzeiler bleibt.

---

### Task 1: `/panel`-Route

**Files:**
- Modify: `app/main.py:298-300` (direkt nach der bestehenden `@app.get("/")`-Route)
- Test: `tests/test_vr_panel.py` (neue Datei)

**Interfaces:**
- Produces: Route-Handler `panel()` in `app/main.py`, registriert unter `GET /panel` —
  identisches Verhalten zu `index()` (liefert `FileResponse("app/static/index.html",
  headers=_HTML_NO_CACHE)`). Wird von Task 2 nicht angefasst.

- [ ] **Step 1: Write the failing test**

Neue Datei `tests/test_vr_panel.py`:

```python
"""Tests für den VR-Panel-Modus (/panel) — Web-Vorbereitung für ein separat gebautes
MSFS-2024-EFB-Panel (s. docs/superpowers/specs/2026-08-11-vr-panel-modus-design.md).

Für Vanilla-JS/CSS gibt es in diesem Projekt keinen Testläufer -- die Skalierungs-Tests
greifen deshalb wie tests/test_aircraft_ui_static.py auf den Quelltext zu.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import app.main as main

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_panel_liefert_dieselbe_datei_wie_index():
    """/panel MUSS exakt dieselbe Response wie / liefern -- keine zweite HTML-Datei, keine
    Duplikation (s. Global Constraints)."""
    index_resp = asyncio.run(main.index())
    panel_resp = asyncio.run(main.panel())
    assert panel_resp.path == index_resp.path
    assert dict(panel_resp.headers) == dict(index_resp.headers)
```

- [ ] **Step 2: Run test to verify it fails**

Run (aus `~/projects/friesenspy`):
```bash
docker run --rm -v "$HOME/projects/friesenspy:/src:ro" -w /src -e SECRET_KEY=test \
  ghcr.io/regover13/friesenspy:latest python -m pytest tests/test_vr_panel.py -v -p no:cacheprovider
```
Expected: FAIL mit `AttributeError: module 'app.main' has no attribute 'panel'`

- [ ] **Step 3: Write minimal implementation**

In `app/main.py`, direkt nach der bestehenden Route (Zeile ~298-300):

```python
@app.get("/")
async def index():
    return FileResponse("app/static/index.html", headers=_HTML_NO_CACHE)


@app.get("/panel", include_in_schema=False)
async def panel():
    """VR-Panel-Modus fürs MSFS-EFB-Panel (s. Design-Doku) — dieselbe Seite wie `/`, das
    Frontend erkennt den Pfad selbst und skaliert per CSS. Kein eigener Login-Ausnahmefall:
    läuft durch dasselbe forum_login_gate wie jede andere Route."""
    return FileResponse("app/static/index.html", headers=_HTML_NO_CACHE)
```

- [ ] **Step 4: Run test to verify it passes**

Run (Kommando wie Step 2, jetzt `tests/test_vr_panel.py -v`):
Expected: `test_panel_liefert_dieselbe_datei_wie_index PASSED`

- [ ] **Step 5: Commit**

```bash
cd ~/projects/friesenspy
git add app/main.py tests/test_vr_panel.py
git commit -m "feat(panel): /panel-Route liefert dieselbe Seite wie / (VR-Panel-Modus, Web-Teil 1/2)"
```

---

### Task 2: VR-Skalierung (JS-Erkennung + CSS)

**Files:**
- Modify: `app/static/index.html:3-4` (Inline-Script direkt nach `<meta charset>`)
- Modify: `app/static/index.html` (CSS-Regel direkt nach dem `:root { ... }`-Block, vor
  `html, body { ... }` — aktuell Zeilen 37-56, exakte Zeilennummern können sich durch Task 1
  NICHT verschieben, da Task 1 nur `app/main.py` ändert)
- Test: `tests/test_vr_panel.py` (aus Task 1, hier ergänzt)

**Interfaces:**
- Consumes: nichts aus Task 1 (unabhängig — `/panel` und `?vr=1` funktionieren beide bereits
  ohne Task 1, `?vr=1` sogar auf `/` selbst; Task 1 liefert nur den zweiten Aktivierungsweg).
- Produces: CSS-Klasse `vr-panel` auf `<html>`, gesetzt von einem Inline-Script — von keiner
  anderen Datei konsumiert, rein clientseitig.

- [ ] **Step 1: Write the failing tests**

In `tests/test_vr_panel.py` ergänzen (unter der bestehenden Test-Funktion):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run (Kommando wie Task 1 Step 2, jetzt `tests/test_vr_panel.py -v`):
Expected: beide neuen Tests FAIL (Klasse/CSS existieren noch nicht im Quelltext)

- [ ] **Step 3: Write minimal implementation**

In `app/static/index.html`, direkt nach `<meta charset="UTF-8" />` (Zeile 4), VOR allen
anderen `<meta>`-Tags und vor allem vor dem `<style>`-Block einfügen:

```html
  <script>
    (function () {
      // VR-Panel-Modus (MSFS-EFB, s. docs/superpowers/specs/2026-08-11-vr-panel-modus-design.md):
      // /panel als eigene Route (Task 1) ODER ?vr=1 als gleichwertiger Trigger auf jeder URL.
      // Muss VOR dem <style>-Block laufen, damit html.vr-panel beim ersten Paint schon greift.
      var qs = new URLSearchParams(location.search);
      if (location.pathname === '/panel' || qs.get('vr') === '1') {
        document.documentElement.classList.add('vr-panel');
      }
    })();
  </script>
```

In `app/static/index.html`, direkt nach dem schließenden `}` des `:root { ... }`-Blocks
(nach `--text-display: 'Exo 2', sans-serif;` und der schließenden `}`, vor `html, body {`)
einfügen:

```css
    html.vr-panel {
      /* VR-Panel-Modus (MSFS-EFB, /panel oder ?vr=1): skaliert Text, Abstände, Buttons und
         Karten-Controls gemeinsam wie ein manuelles Browser-Zoom -- Innenabstände/Button-
         Größen sind im Rest der Seite überwiegend feste px-Werte, eine reine Schriftgrößen-
         Änderung würde nur den Text wachsen lassen. Startwert, nach dem VR-Test in MSFS
         nachjustierbar (docs/superpowers/specs/2026-08-11-vr-panel-modus-design.md). */
      zoom: 1.35;
    }
    html.vr-panel body {
      /* App läuft sonst durchgehend auf font-weight 300 (dünn) -- in der Headset-Optik
         vermutlich zu blass. */
      font-weight: 400;
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run (Kommando wie Task 1 Step 2, jetzt `tests/test_vr_panel.py -v`):
Expected: alle drei Tests in `tests/test_vr_panel.py` PASSED

- [ ] **Step 5: Run the full suite (Regressionsschutz)**

```bash
docker run --rm -v "$HOME/projects/friesenspy:/src:ro" -w /src -e SECRET_KEY=test \
  ghcr.io/regover13/friesenspy:latest python -m pytest tests/ -q -p no:cacheprovider
```
Expected: alle Tests grün (Referenzwert vor dieser Änderung: 1343 — hier zusätzlich `+3`, also
`1346 passed`, keine Fehlschläge)

- [ ] **Step 6: Commit**

```bash
cd ~/projects/friesenspy
git add app/static/index.html tests/test_vr_panel.py
git commit -m "feat(panel): VR-Skalierung per zoom unter html.vr-panel (VR-Panel-Modus, Web-Teil 2/2)"
```

---

## Nach beiden Tasks

Push auf `main` löst den bestehenden Deploy-Workflow aus (Build & Push nach GHCR, SSH-Deploy,
Discord-Meldung) — wie bei jeder anderen Änderung an diesem Repo. Danach: `/panel` bzw.
`https://friesenspy.devprops.de/?vr=1` im Browser aufrufen, grobe Optik prüfen (kein
automatisierter Test dafür, s. Design-Doku „Testen"). Der eigentliche Abnahmetest ist der
Live-Versuch des Nutzers in MSFS-VR — den Zoom-Faktor `1.35` danach ggf. an den beiden Stellen
in `app/static/index.html` UND im Test `test_vr_panel_css_skaliert_alles_gemeinsam`
(`tests/test_vr_panel.py`) gemeinsam anpassen, sonst bricht der Test beim nächsten Lauf.
