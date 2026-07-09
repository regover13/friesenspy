# Design — Paket A: Kutter-Sofort-Fixes (v8.18.0)

Datum: 2026-07-09
Scope: drei kleine, unabhängige Fixes, gemeinsam deploybar. Teil des Gesamtvorhabens
„Alles fixen" (A → B → C); B = Verlust-Kern (#6/#7/#8), C = Milchmann + Boden-Beladung
bekommen eigene Specs.

## Ziel

Drei niedrigschwellige Ärgernisse beseitigen, die keine Design-Tiefe brauchen und sich
gefahrlos zusammen ausliefern lassen.

## A1 — Startplatz-Warnung ignoriert Leerzeichen (#1)

**Problem:** Beim Anlegen/Speichern eines Kutter-Events prüft die Client-Warnung „Unbekannte
Flugplätze" die Startplätze mit `.split(',')` (nur Komma). Mehrere ICAOs mit Leerzeichen
getrennt („EDXH EDXP") bleiben ein Token → falsche „keine bekannten Plätze"-Warnung. Das
echte Speichern ist NICHT betroffen (`_normalize_icao_list`, def
`D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\database.py:4274`, Split-Logik bei :4285 —
splittet bereits an Komma/Semikolon/Space/Tab).

**Fix:** `app/static/admin.html:2310`

```js
const unknown = await checkUnknownIcaos([dest].concat(cargo.flatMap(c => (c.departure || '').split(/[,\s]+/))));
```

`.split(',')` → `.split(/[,\s]+/)` (identisch zur Bummel-Strecke in `admin.html:1325`). Rein
clientseitig, keine Serveränderung.

**Test:** keiner nötig (reine String-Trennung, Vorlage existiert im selben File).

## A2 — Event-Erinnerungs-Push zeigt echte Restzeit (#2)

**Problem:** Der Push zeigt immer hart „🗓 In etwa 1 Std", egal wie lange es bis zum Start
wirklich ist. Der Job feuert, sobald `dtstart` im 60-min-Fenster liegt; bei einem knapp vor
Beginn angelegten Event stimmt „1 Std" grob nicht (Live-Fund: Push 6 min vor Start sagte „1 Std").

**Fix:** neuer reiner Helfer in `app/poller.py`:

```python
from app.database import _parse_iso  # lebt in database.py:327, in poller.py NICHT importiert

def _lead_phrase(dtstart: str, now: str) -> str:
    """Restzeit bis dtstart als gestufter Text. Rein, testbar."""
    mins = (_parse_iso(dtstart) - _parse_iso(now)).total_seconds() / 60
    if mins > 45:
        return "In etwa 1 Std"
    if mins >= 10:
        return f"In etwa {int(round(mins / 5) * 5)} min"
    return "In wenigen Minuten"
```

`_parse_iso` existiert nur in `D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\database.py:327` und
ist in `D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\poller.py` **nicht** importiert — daher
zwingend `from app.database import _parse_iso` ergänzen (Alternative: lokal via
`datetime.fromisoformat` nach Z-Strip). Kein separater `datetime`-Import im Helfer nötig.

Stufen (vom Nutzer abgenommen):
- `> 45 min` → „In etwa 1 Std"
- `10–45 min` → „In etwa X min" (X auf 5 gerundet)
- `< 10 min` → „In wenigen Minuten"

Ersetzt das harte „In etwa 1 Std" in **allen drei** Push-Schleifen (`app/poller.py:1428`
generic, `:1438` bummel, `:1448` kutter). `dtstart` liefern `events_due_for_reminder` /
`bummel_races_due_for_reminder` / `transport_events_due_for_reminder` bereits mit. Der
Body wird zu z. B. `f"🗓 {_lead_phrase(ev['dtstart'], now)}: {name}"`.

**Test:** Unit-Test für `_lead_phrase` — Stufengrenzen 46/45/25/10/9 min prüfen.

## A3 — Wording „zurück" → „leer" (#3)

**Problem:** Ein Kutter-Flug ohne Fracht im Ruhezustand (loaded=false, in_air=false) heißt an
einer Stelle „zurück" (unterstellt Heimflug-Richtung), an anderer schon „leer". „zurück" ist
irreführend, weil derselbe Zustand ein Leerflug ZUR Insel sein kann.

**Fix:** `D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\static\index.html:4623` (Live-Feed,
Funktion `_kCargoLabel`, def bei `index.html:4609`, einziger Aufrufer `_kutterDetailBody`
`index.html:4751`) — Text „zurück" → „leer" (vereinheitlicht mit `index.html:4749`, das denselben
Zustand `!loaded && !loss_kind && !in_air` schon „leer" nennt; beide Texte landen sogar in
derselben Tabellenzeile). `_kLossLabel` und der loss_kind `'returned'` („↩️ zurückgebracht",
`index.html:4636–4639`) bleiben unberührt — getrennter Codepfad (`f.loss_kind` greift vor dem
`!f.loaded`-Zweig), anderer korrekter Begriff.

Hinweis: Beim Umsetzen die tatsächliche Zeile per Grep bestätigen (Text `>zurück<` in
`D:\User\Tobias\OneDrive\Claude\FriesenSpy\app\static\index.html`), da Zeilennummern driften.

**Test:** keiner nötig (String-Änderung).

## Nicht-Ziele

- Keine Änderung an der Verlust-Logik (#6/#7/#8 → Paket B).
- Keine Änderung an der Reservierungs-Anzeige am Boden (#5 → Paket C).

## Versionierung & Deploy

- Version-Bump (Patch/Minor je nach Einschätzung, Vorschlag v8.18.0), CHANGELOG-Eintrag,
  Git-Tag, Docs-Abgleich (README/api.md/architecture.md nur falls betroffen — hier kaum).
- Push auf main → GitHub Actions → GHCR → VPS. Vorher kurz bestätigen lassen.
