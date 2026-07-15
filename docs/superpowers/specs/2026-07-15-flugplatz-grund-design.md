# Spalte „Grund" für Ergänzungs-Flugplätze

**Datum:** 2026-07-15
**Status:** abgenommen (Nutzer, 2026-07-15)

## Problem

`custom_airports` sagt *was* korrigiert wurde (Code, Koordinaten, Elevation, Radius), aber nicht
*warum*. Bei 13 gewachsenen Einträgen ist von außen nicht erkennbar, ob ein Platz ergänzt wurde,
weil er in `airportsdata` fehlt, oder ob er einen falschen `airportsdata`-Eintrag überschreibt —
zwei völlig verschiedene Fälle mit verschiedenen Konsequenzen (siehe #56). Wer später aufräumt,
muss das aus Git-History und Code-Kommentaren zusammensuchen.

Ausgelöst durch den EBKT-Fund (2026-07-15): `airportsdata` führt Kortrijk-Wevelgem 37 km neben
der tatsächlichen Position. Die Historien-Analyse zeigte, dass das kein Einzelfall ist (EBBR
42 km, ELLX 30 km, EBAW 15 km — alle Belgien/Luxemburg). Solche Overrides werden häufiger, also
lohnt die Dokumentation im Datensatz statt im Kommentar.

## Entscheidungen

**Kurze Standard-Gründe, kein Enum.** Freitext, aber mit Autocomplete auf die bereits vergebenen
Gründe. Wenige, wiederkehrende Formulierungen halten die Liste gruppierbar; ein Enum im Code
wäre unnötig starr, weil neue Gründe-Arten jederzeit auftauchen können.

Die drei initialen Gründe:

| Grund | Bedeutung |
|---|---|
| `Fehlt in airportsdata` | Ergänzung — der Platz existiert dort gar nicht |
| `airportsdata-Koordinate falsch` | Override — Platz existiert, steht aber am falschen Ort |
| `Abhebepunkt außerhalb Standardradius` | Radius-Override — Koordinate korrekt, nur `radius_km` gesetzt |

Bewusst NICHT aufgenommen: eine eigene Variante für Platzhalter-Codes (`ZZSALZ`). Dass es kein
echter ICAO ist, steht bereits im Code-Kommentar und im Namen; eine vierte Variante verwässert
nur die Vorschlagsliste.

## Schema

```sql
ALTER TABLE custom_airports ADD COLUMN reason TEXT;   -- NULL erlaubt
```

Nullable, und zwar dauerhaft: ein fehlender Grund darf das Speichern **nie** blockieren. Der
Eintrag selbst ist die Funktion, der Grund nur Dokumentation — ein Pflichtfeld würde im
Zweifel echte Korrekturen verhindern.

## Migration der 13 Bestandseinträge

Die Gründe werden **aus den Daten abgeleitet, nicht aus einer gepflegten Namensliste** — damit
ist die Migration auch für Einträge korrekt, die zum Zeitpunkt des Schreibens niemand kennt:

```
Code nicht in airportsdata           -> "Fehlt in airportsdata"
Koordinate weicht > 1 km ab          -> "airportsdata-Koordinate falsch"
sonst (Koordinate praktisch gleich)  -> "Abhebepunkt außerhalb Standardradius"
```

Die 1-km-Schwelle trennt „bewusst korrigiert" von „unverändert übernommen" (`EHAM` liegt bei
0,00 km, `EBUL` bei 15,0 km — keine Grauzone).

Ist-Zustand 2026-07-15, geprüft:

- **Ergänzung** (10): BZWIROS, CML5, EDHD, EDLQ, EDST, EDWD, EXHB, LIVD, LOJB, ZZSALZ
- **Koordinate falsch** (2): EBKT (37,0 km), EBUL (15,0 km)
- **Radius** (1): EHAM (0,00 km, `radius_km=10`)

Läuft in `init_db` mit `WHERE reason IS NULL` — idempotent, überschreibt also niemals einen vom
Admin gepflegten Text und darf bei jedem Start durchlaufen.

## Autocomplete

Natives `<datalist>` am Grund-Eingabefeld, gespeist aus den `distinct` Gründen der bereits
geladenen Einträge. **Kein neuer Endpoint** — das Admin-UI holt über `list_custom_airports`
ohnehin alle Zeilen; die Vorschlagsliste ist eine Frontend-Ableitung daraus. Neue Gründe
entstehen durch Benutzung, bestehende werden konsistent wiederverwendet.

## Betroffene Stellen

- `app/database.py` — Schema, Migration, `_CUSTOM_AIRPORTS_SEED` (+ Grund), `list_custom_airports`,
  `upsert_custom_airport`
- `app/main.py` — `POST /api/admin/airports` nimmt `reason` entgegen
- `app/static/admin.html` — Eingabefeld + datalist, Spalte in der Tabelle
- `tests/` — Migration (inkl. Idempotenz), Ableitungsregel, Upsert mit/ohne Grund
- `README.md`, `docs/api.md`, `docs/architecture.md`, `app/CHANGELOG.json` + Versionsbump

## Nicht im Scope

Der Seed führt `EDDX` (Bad Zwischenahn-Rostrup), die Produktions-DB hat stattdessen `BZWIROS`
mit identischen Koordinaten; `EDDX` erscheint in der Flughistorie einmal als unerkannter Platz.
Sieht nach einer Umbenennung mit verwaistem Altcode aus — eigener Vorgang, nicht Teil dieses
Features.
