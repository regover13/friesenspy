# REST API

Basis-URL: `https://friesenspy.devprops.de`

---

## GET /health

Health-Check.

**Response**
```json
{"status": "ok"}
```

---

## GET /api/live

Aktuelle Live-Positionen aller online Friesen (Callsign-Prefix `FRS`).

**Response** — Array von Position-Objekten (leer wenn niemand online)

```json
[
  {
    "cid": 1602713,
    "callsign": "FRS49",
    "name": "Tobias EDKB",
    "aircraft": "PA24",
    "departure": "EDKB",
    "arrival": "EDDK",
    "latitude": 50.767,
    "longitude": 7.162,
    "altitude": 2500,
    "groundspeed": 110,
    "heading": 317,
    "logon_time": "2026-06-04T07:14:54Z",
    "updated_at": "2026-06-04T07:28:41Z",
    "flight_rules": "V",
    "aircraft_icao": "PA24",
    "alternate": "",
    "deptime": "1145",
    "cruise_tas": "147",
    "enroute_time": "0045",
    "fuel_time": "0400",
    "route": "DCT",
    "remarks": "CAVOK VFR DAYLIGHT CS=FRIESE=FRIESENFLIEGER"
  }
]
```

---

## GET /api/stats/activity

Flugaktivität über Zeit — für das Liniendiagramm im Statistiken-Tab.

**Query-Parameter**

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `days` | int | `30` | Zeitraum in Tagen |

Gruppierung: ≤93 Tage → täglich (`%Y-%m-%d`), >93 Tage → monatlich (`%Y-%m`). Alle Perioden werden zurückgegeben (Lücken mit 0 aufgefüllt). Nur FRS*-Callsigns. Aggregiert über `canonicalize_flights` — dieselbe kanonische Flugmenge wie `/api/stats` und `/api/pilots/{cid}/flights`: Reconnects/Fragmente sind zu einem Flug gemergt, Ghost-Flüge (`distance_nm ≤ 0.5 AND duration_min ≤ 5`) ausgeschlossen, StatSim-Duplikate dedupliziert. Dadurch stimmen die Zahlen über alle Views überein.

**Response**

```json
{
  "grouping": "day",
  "data": [
    {
      "period": "2026-06-05",
      "pilot_count": 3,
      "flight_count": 8,
      "total_duration_min": 420
    }
  ]
}
```

---

## GET /api/stats

Letzter Flug und Fluganzahl pro Pilot. Kombiniert FriesenSpy-Aufzeichnungen und gecachte StatSim-Daten.

**Query-Parameter**

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `days` | int | `30` | Zeitraum in Tagen (30, 90, 365) |
| `sort_by` | string | `last_flight` | Sortierfeld: `last_flight`, `flight_count`, `total_duration_min` |
| `sort_dir` | string | `desc` | Sortierrichtung: `asc` oder `desc` |

**Response**

```json
[
  {
    "cid": 1602713,
    "name": "Tobias EDKB",
    "last_callsign": "FRS49",
    "fs_count": 3,
    "st_count": 9,
    "flight_count": 12,
    "total_duration_min": 540,
    "last_flight": "2026-06-04T07:14:54Z"
  }
]
```

`flight_count` = `fs_count` + `st_count`. StatSim-Daten sind nur vorhanden wenn der Pilot zuvor im Statistiken-Tab angeklickt wurde (lazy cache). Zählung und Dauer kommen aus `canonicalize_flights` (Reconnect-Merge + Dedup), identisch zu `/api/stats/activity` und der Piloten-Detailansicht.

---

## GET /api/pilots/{cid}/flights

Alle Flüge eines Piloten — kombiniert FriesenSpy-eigene Aufzeichnungen und StatSim-Historik über `canonicalize_flights` (Reconnect-Merge + StatSim-Dedup, identisch zu den Statistik-Endpoints). Antwortet **sofort** mit gecachten Daten; StatSim-Update läuft im Hintergrund (letzter 31-Tage-Chunk). Response-Header `X-StatSim-Status: fresh | updating | no-key`.

**Query-Parameter**

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `days` | int | `365` | Zeitraum in Tagen; `0` = Force-Refresh aller 365 Tage |

**Response**

```json
[
  {
    "source": "friesenspy",
    "id": 42,
    "statsim_id": null,
    "cid": 1602713,
    "callsign": "FRS49",
    "departure": "EDKB",
    "arrival": "EDDK",
    "aircraft": "PA24",
    "logon_time": "2026-06-04T07:14:54Z",
    "logoff_time": "2026-06-04T08:05:22Z",
    "duration_min": 51,
    "block_min": 44
  },
  {
    "source": "statsim",
    "id": null,
    "statsim_id": 28832100,
    "cid": null,
    "callsign": "FRS49",
    "departure": "EDKB",
    "arrival": "EDDF",
    "aircraft": "PA24/L-SDGRY/S",
    "logon_time": "2026-06-01T14:30:00Z",
    "logoff_time": "2026-06-01T15:50:00Z",
    "duration_min": 80
  }
]
```

Sortiert nach `logon_time` absteigend. FriesenSpy-Einträge haben Vorrang bei Zeitstempel-Überschneidungen (±5 Min).

`duration_min` = **Online-Zeit** (Verbindung logon→logoff). `block_min` = **Block-Zeit** (Summe der GPS-Bewegungsabschnitte gate-to-gate; belegte Standphasen ≥ 10 min, z. B. eine Zwischenlandung ohne Disconnect, zählen nicht) — nur bei FriesenSpy-Flügen vorhanden, StatSim/Altflüge haben `null`.

---

## GET /api/pilots/{cid}/live-track

GPS-Track des aktuell laufenden Fluges aus `position_history` (logoff_time IS NULL). Leeres Array wenn der Pilot nicht online ist.

**Response** — gleiches Format wie `/api/flights/{id}/track`

---

## GET /api/flights/{flight_id}/track

GPS-Track eines FriesenSpy-Fluges aus der `position_history`-Tabelle.

**Query-Parameter** (optional)

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| `logon` | string | ISO8601 UTC — überschreibt den Logon-Zeitstempel aus der DB (nötig nach Flug-Merge, wo DB noch alte Zeiten hat) |
| `logoff` | string | ISO8601 UTC — überschreibt den Logoff-Zeitstempel aus der DB |

**Response**

```json
[
  {
    "latitude": 50.767,
    "longitude": 7.162,
    "altitude": 206,
    "groundspeed": 0,
    "heading": 317,
    "ts": "2026-06-04T07:15:00Z"
  }
]
```

Gibt `404` wenn die `flight_id` nicht existiert. Leeres Array wenn keine Positionsdaten vorhanden.

---

## GET /api/flights/statsim/{statsim_id}/track

GPS-Track eines StatSim-Fluges (live von der StatSim API, nicht gecacht). Gibt `[]` wenn kein `STATSIM_API_KEY` konfiguriert.

**Response** — gleiches Format wie `/api/flights/{id}/track`

---

## GET /api/events

Event-Suche: Wer von den Friesen war in einem bestimmten Zeitraum in der Nähe eines Flughafens — oder weltweit?

**Query-Parameter**

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `icao` | string | — | **Pflicht.** Kommagetrennte ICAO-Codes, z.B. `EDDK,EDDL` — oder `global` für weltweite Suche ohne Radius-Filter |
| `radius` | float | `150.0` | Suchradius in km (wird bei `icao=global` ignoriert) |
| `start` | string | `""` | ISO8601 UTC, z.B. `2024-01-01T10:00:00Z` |
| `end` | string | `""` | ISO8601 UTC, z.B. `2024-01-01T18:00:00Z` |

**Response**

```json
{
  "pilots": [
    {
      "cid": 1602713,
      "callsign": "FRS49",
      "name": "Tobias EDKB",
      "flights": [
        {
          "logon_time": "2026-06-04T07:00:00Z",
          "logoff_time": "2026-06-04T10:20:00Z",
          "callsign": "FRS49",
          "departure": "EDKB",
          "arrival": "EDDK",
          "aircraft": "PA24",
          "positions": [
            {
              "callsign": "FRS49",
              "latitude": 50.865,
              "longitude": 7.142,
              "altitude": 2800,
              "groundspeed": 95,
              "heading": 270,
              "ts": "2026-06-04T07:00:00Z"
            }
          ]
        }
      ]
    }
  ]
}
```

Jeder Flug-Eintrag enthält ein `source`-Feld: `"friesenspy"` für Flüge mit GPS-Track aus `position_history`, `"statsim"` für Einträge aus dem StatSim-Cache (`positions: []`, Track wird im Frontend per `/api/flights/statsim/{statsim_id}/track` nachgeladen).

**StatSim-Fallback:** Piloten die in `statsim_cache` per `departure` oder `arrival` im Zeitfenster gefunden werden, aber keine `position_history` haben (z.B. weil FriesenSpy zu diesem Zeitpunkt nicht lief), erscheinen ebenfalls in der Antwort — mit `source: "statsim"`. Das Frontend lädt den GPS-Track automatisch asynchron von StatSim nach und zeichnet ihn auf der Karte; Zeilen sind wie FriesenSpy-Flüge klickbar (Highlight). Falls kein Track verfügbar ist, erscheint nur das „◌ StatSim"-Badge ohne Kartendarstellung.

`flights` enthält die Positionen des Piloten im Zeitfenster aufgeteilt in einzelne Flüge. Die Segmentierung basiert primär auf echten VATSIM-Session-Records aus der `flights`-Tabelle (Callsign, DEP/ARR, Flugzeugtyp aus dem Flugplan). `callsign`, `departure`, `arrival` und `aircraft` sind `null` wenn kein passender `flights`-Eintrag existiert — in diesem Fall wird als Fallback nach Zeitlücken von mehr als 30 Minuten segmentiert (z.B. für Positionen aus Zeiten vor FriesenSpy-Start). `positions` enthält alle aufgezeichneten Positionen des jeweiligen Fluges — nicht nur die im Radius.

**Erweitertes Response-Beispiel mit StatSim-Pilot:**

```json
{
  "pilots": [
    {
      "cid": 1234567,
      "callsign": "FRS22",
      "name": "Max Mustermann",
      "flights": [
        {
          "logon_time": "2026-04-02T17:55:00Z",
          "logoff_time": "2026-04-02T19:30:00Z",
          "callsign": "FRS22",
          "departure": "EDVK",
          "arrival": "EDDK",
          "aircraft": "C172",
          "statsim_id": 28832100,
          "positions": [],
          "source": "statsim"
        }
      ]
    }
  ]
}
```

---

## GET /api/prefiles

Aktuelle VATSIM-Prefile-Flugpläne mit FRS*-Callsign (aus dem letzten VATSIM-Poll-Zyklus, ~15s alt).

Ein Prefile ist ein eingereichter Flugplan ohne aktive VATSIM-Verbindung — der Pilot hat den Plan aufgegeben, ist aber noch nicht online. Das Feld `remarks` enthält ggf. `DOF/YYMMDD` (Date of Flight) für Flüge an einem anderen Tag als heute; die UI extrahiert daraus Datum und Uhrzeit.

**Response**

```json
[
  {
    "callsign": "FRS49",
    "cid": 1602713,
    "name": "Tobias EDKB",
    "departure": "EDKB",
    "arrival": "EDDK",
    "route": "DCT",
    "planned_deptime": "1345"
  }
]
```

`name` ist nur vorhanden wenn der Pilot FriesenSpy bekannt ist (zuvor als FRS* geflogen). `planned_deptime` ist im Format `HHMM` UTC.

---

## GET /api/teamspeak

Aktuell im FriesenFlieger-TeamSpeak befindliche FriesenFlieger (nur FRS*-getaggte Clients) aus dem letzten TS-Poll-Snapshot. Speist das Live-Tab-Panel „🎧 Im TeamSpeak" und den Widget-Zähler.

Der Snapshot wird bei jedem erfolgreichen TS-Poll aktualisiert (`TS_POLL_INTERVAL`, Default 30 s). Ist der TeamSpeak kurzzeitig nicht erreichbar, bleibt der letzte Snapshot erhalten. Consent (`ts_consent`) wirkt **nicht** auf diese Anzeige (gilt nur für Push). Nicht-Friesen ohne FRS-Tag werden weder gezählt noch gelistet.

Es wird bewusst **nur das FRS-Callsign** ausgegeben — Klarnamen und sonstige Nickname-Zusätze bleiben serverseitig und verlassen den Server nicht.

**Response**

```json
{
  "enabled": true,
  "count": 2,
  "users": [
    {"frs": "FRS49"},
    {"frs": "FRS135"}
  ]
}
```

`enabled` spiegelt `TS_NOTIFY_ENABLED` — ist es `false`, blendet die UI das Panel aus.

---

## GET /api/frontend-config

Konfiguration + Versionsdaten für das Frontend (wird beim Seitenstart einmal geladen).

**Response**

```json
{
  "openaip_api_key": "…",
  "vapid_public_key": "…",
  "version": "5.2.0",
  "changelog": [
    {
      "version": "5.2.0",
      "date": "2026-06-27",
      "title": "Zuverlässigkeit & Versionsverlauf",
      "items": ["🐛 …", "⚡ …"]
    }
  ],
  "banner_version": "6.4.0"
}
```

`version` + `changelog` stammen aus `app/CHANGELOG.json` (via `app/version.py`). `version` ist
die neueste Version (`changelog[0].version`). Das Frontend zeigt damit die kleine Versionsnummer
im Header, das Changelog-Banner (neueste Version, einmal pro Version) und den Versionsverlauf.

`banner_version` ist die vom Server aufgelöste Version, deren Changelog-Eintrag als Startseiten-Banner
angezeigt werden soll — oder `null`, wenn kein Banner erscheinen soll. Sie wird aus der Admin-Auswahl
(`app_settings['banner_version']`) über `_resolve_banner_version` abgeleitet: `auto` → neuester Eintrag
mit `highlight: true` (Fallback: neuester Eintrag), `off` → `null`, eine konkrete Version → genau diese
(falls sie existiert, sonst `null`). Steuerbar über `GET`/`POST /api/admin/banner`.

---

## GET /api/calendar/events

FriesenEvents aus dem FriesenFlieger-Google-Kalender — letzte 365 Tage bis heute, absteigend nach Startdatum (neueste zuerst).

Der Kalender wird alle 6 Stunden automatisch synchronisiert. RRULE-Wiederholungstermine werden expandiert (jede Wiederholung als eigener Eintrag). Ganztags-Events (ohne Uhrzeit) werden nicht gespeichert.

**Response**

```json
[
  {
    "uid": "abc123@google.com_20260515T170000Z",
    "summary": "FriesenFlieger Stammtisch EDVK",
    "dtstart": "2026-05-15T17:00:00Z",
    "dtend": "2026-05-15T20:00:00Z",
    "location": "EDVK",
    "route": "EDVK",
    "is_bummel": 0
  }
]
```

`location` enthält den ersten 4-buchstabigen ICAO-Code aus dem Kalender-Feld „Ort", sonst aus dem Event-Titel (leer wenn nicht erkannt). Bei Events ohne ICAO wird `global` ins Suchfeld vorgefüllt. Zeiten sind immer UTC.

`route` ist die CSV aller erkannten ICAO-Codes (Reihenfolge erhaltend, dedupliziert; aus Ort, Titel und Beschreibung). `is_bummel` ist `1`, wenn das Stichwort „Bummel" im Titel oder der Beschreibung steht, die Strecke ≥ 2 Flugplätze hat und plausibel ist (kein Paar > 600 nm auseinander) — siehe `/api/bummel`.

**Event-Erinnerungen:** Der Poller prüft alle 5 Minuten via `events_due_for_reminder`, welche Kalender-Events innerhalb der nächsten 60 Minuten beginnen (`dtstart` im Fenster `(jetzt, jetzt+60min]`), und sendet einmalig je Event einen Push an alle Abonnenten mit `notify_events=1`. Das Versenden wird durch die Tabelle `event_reminders_sent` als Latch abgesichert — ein Event löst die Erinnerung auch nach Container-Neustarts nur einmal aus.

---

## GET /api/bummel/races

Liste aller bekannten FriesenFliegerBummel-Rennen (aus `bummel_races`, persistent gespeichert). Rennen werden beim Kalender-Sync automatisch angelegt.

**Response** — Array, neueste zuerst

```json
[
  {
    "id": 1,
    "name": "FriesenFliegerBummel Ostfriesland",
    "route": ["EDWF", "EDWG", "EDWR"],
    "dtstart": "2026-06-27T14:00:00Z",
    "dtend": "2026-06-27T20:00:00Z",
    "status": "revealed",
    "participant_count": 5,
    "calendar_uid": "abc123@google.com_20260627T140000Z",
    "source": "calendar"
  }
]
```

`status` ∈ `scheduled` | `running` | `waiting` | `revealed`.
- `scheduled` — Rennen liegt in der Zukunft
- `running` — zwischen `dtstart` und `dtend`
- `waiting` — `dtend` überschritten, aber noch ein Teilnehmer unterwegs (Nachzügler)
- `revealed` — Ergebnisse enthüllt (einmal enthüllt, bleibt es enthüllt)

`dtend` ist der effektive Renn-Endtermin: aus dem Kalender-Event übernommen; fehlt er → Mitternacht UTC des Folgetags (00:00:00Z nach dem Starttag).

`source` ∈ `calendar` | `manual`. Manuell angelegte Rennen (ohne Kalender-Termin) haben `source: "manual"` und `calendar_uid: null` — sie erscheinen in der Events-Tab-Liste und sind anklickbar.

---

## GET /api/bummel/race/{id}

Öffentliche Sicht eines einzelnen Rennens. **Vor der Enthüllung** werden Zeiten, Durchschnitt und Ranking serverseitig weggelassen (`public_bummel_view`) — sie sind nicht im JSON enthalten. Nach der Enthüllung kommen die vollständigen Ergebnisse.

**Vor der Enthüllung** (`revealed: false`):

```json
{
  "id": 1,
  "name": "FriesenFliegerBummel Ostfriesland",
  "route": ["EDWF", "EDWG", "EDWR"],
  "dtstart": "2026-06-27T14:00:00Z",
  "dtend": "2026-06-27T20:00:00Z",
  "status": "running",
  "revealed": false,
  "participant_count": 3,
  "in_progress": [
    {"cid": 400, "callsign": "FRS400", "name": "Dora", "aircraft": "C172",
     "departure": "EDWG", "arrival": "EDWR", "started": "2026-06-27T15:24:00Z"}
  ],
  "participants": [
    {"cid": 300, "callsign": "FRS300", "name": "Cara", "aircraft": "C172",
     "visited": ["EDWF","EDWG","EDWR"], "missing": [],
     "leg_count": 2, "started": "2026-06-27T14:10:00Z", "in_progress": false},
    {"cid": 400, "callsign": "FRS400", "name": "Dora", "aircraft": "C172",
     "visited": ["EDWF","EDWG"], "missing": ["EDWR"],
     "leg_count": 1, "started": "2026-06-27T15:24:00Z", "in_progress": true}
  ]
}
```

Sichtbar vor Enthüllung: Callsign, Name, Flugzeugtyp, Flugplan (Start/Ziel), Abflugzeit, besuchte/fehlende Flugplätze, Anzahl Beine, wer gerade fliegt.

**Nicht sichtbar vor Enthüllung:** Block-/Gesamtzeiten, Durchschnitt, Abstand zum Schnitt, Ranking-Reihenfolge, Lande-/Logoff-Zeit, Online-Dauer, geflogene nm.

**Nach der Enthüllung** (`revealed: true`) kommen zusätzlich:

```json
{
  "revealed": true,
  "average_min": 80.0,
  "average_sec": 4800,
  "count": 3,
  "complete": [
    {"cid": 300, "name": "Cara", "callsign": "FRS300", "total_min": 80,
     "total_sec": 4815, "aircraft": "C172", "leg_count": 2,
     "visited": ["EDWF","EDWG","EDWR"], "missing": [], "legs": [],
     "rank": 1, "delta": 0.0, "delta_sec": 15}
  ],
  "incomplete": [
    {"cid": 500, "name": "Emil", "callsign": "FRS500", "total_min": 35,
     "total_sec": 2100, "aircraft": "C172", "leg_count": 1,
     "visited": ["EDWF","EDWG"], "missing": ["EDWR"], "legs": []}
  ]
}
```

`complete` ist aufsteigend nach dem Abstand zum Schnitt sortiert; `rank` 1 ist der Sieger. Die Sortierung ist **sekundengenau** (Schlüssel `(|delta_sec|, total_sec, cid)`) und löst damit Gleichstände auf, die bei gleicher Minuten-Blockzeit entstünden. `incomplete`-Piloten haben noch nicht alle Flugplätze besucht und zählen nicht in den Schnitt.

**Sekundengenaue Felder.** Zusätzlich zu `total_min`/`average_min`/`delta` (Minuten, für die Anzeige) liefert die enthüllte Sicht die sekundengenaue Variante: `total_sec` (Block-Gesamtzeit in Sekunden) und `delta_sec` (**signierter** Abstand zum Schnitt in Sekunden — positiv = über dem Schnitt, negativ = darunter, `0` = punktgenau) je Eintrag sowie `average_sec` auf Rennen-Ebene. Die Anzeige der Gesamtzeit/des Schnitts bleibt in Minuten; nur der Abstand wird signiert + sekundengenau gezeigt. Diese Sekunden-Felder erscheinen **erst nach der Enthüllung** (vor der Enthüllung von `public_bummel_view` zusammen mit allen Zeiten entfernt).

Gibt `404` zurück wenn die `id` nicht existiert.

---

## GET /api/bummel/active

Aktuell laufendes oder wartendes FriesenFliegerBummel-Rennen als redigierte (öffentliche) Sicht — speist das Live-Banner. Gibt `null` zurück wenn gerade kein Rennen mit `status` ∈ `running` | `waiting` läuft. Bereits enthüllte Rennen erscheinen hier **nicht** mehr.

**Response** — `null`, wenn kein aktives Rennen, sonst die redigierte Rennen-Sicht (identisches Format wie `GET /api/bummel/race/{id}` vor Enthüllung):

```json
{
  "id": 1,
  "name": "FriesenFliegerBummel Ostfriesland",
  "route": ["EDWF", "EDWG", "EDWR"],
  "dtstart": "2026-06-27T14:00:00Z",
  "dtend": "2026-06-27T20:00:00Z",
  "status": "running",
  "revealed": false,
  "participant_count": 3,
  "in_progress": [
    {"cid": 400, "callsign": "FRS400", "name": "Dora", "aircraft": "C172",
     "departure": "EDWG", "arrival": "EDWR", "started": "2026-06-27T15:24:00Z"}
  ],
  "participants": ["..."]
}
```

---

## GET /api/bummel/race/{race_id}/badge/{cid}.png

Badge-PNG für die Forensignatur eines Bummel-Teilnehmers. Erst nach Enthüllung des Rennens verfügbar (kein Leak vor der Enthüllung).

**Voraussetzungen — sonst `404`:**
- Das Rennen mit `race_id` muss enthüllt sein (`revealed_at IS NOT NULL`).
- `cid` muss Teilnehmer dieses Rennens sein (komplett oder unvollständig).

**Response** — `image/png`

Beide Badges sind **rund (256 × 256 px)** mit transparenten Rändern und nutzen die FriesenFlieger-Markenhintergründe (Flugzeug, ostfriesische Inselkette, Vereinsfarben). Die Variante wird automatisch anhand des Rangs gewählt:

| Variante | Bedingung | Inhalt |
|----------|-----------|--------|
| **Sieger-Badge „Absoluter Durchschnitt!"** (helle Kuppel) | Rang 1 | Callsign, Name, Flugzeugmuster, Block-Gesamtzeit, Abstand zum Schnitt, Event-Name + Datum, Fußzeile „friesenflieger.de" |
| **Medaille „Voll daneben!"** (navy Kern) | alle anderen (auch unvollständige) | Callsign, Name, Flugzeugmuster, Event-Name + Datum, Abstand zum Schnitt (falls komplett), Fußzeile „friesenflieger.de" |

Beide Badges tragen jetzt **Event-Name (Überschrift) und Datum** (auch der Sieger-Badge, der vorher kein Datum hatte). Der Abstand zum Schnitt wird **signiert + sekundengenau** formatiert (z. B. „+1:23 zum Schnitt", bei punktgenauem Treffer „punktgenau").

**Caching (ETag + Revalidierung):** Aus den ergebnisrelevanten Feldern (inkl. `delta_sec` und `event`) wird ein Hash gebildet, der als `ETag` dient und in den serverseitigen Cache-Dateinamen einfließt (`data/badges/<race_id>_<cid>_<hash>.png`). Der Endpoint antwortet mit `Cache-Control: no-cache` + `ETag` (statt zuvor `public, max-age=86400`): Schickt der Client ein passendes `If-None-Match`, kommt `304 Not Modified` zurück. Ändert sich der Sieger (z. B. durch Admin-Override oder Wertungsänderung), ändert sich der ETag → Browser/Forum holen sofort ein frisches Bild statt eines bis zu einen Tag veralteten (behebt den Bug, dass ein alter Gewinner-Badge nach Wertungsänderung hängenblieb).

**Response-Header:**
```
Content-Type: image/png
Cache-Control: no-cache
ETag: "<hash>"
```

**BBCode für board.friesenflieger.de:**
```
[img]https://friesenspy.devprops.de/api/bummel/race/{race_id}/badge/{cid}.png[/img]
```

Der **„📋 Forum"**-Button im enthüllten Ranking kopiert diesen BBCode direkt in die Zwischenablage. Der **„🎖 Badge"**-Button öffnet das PNG in einem neuen Tab.

> **Admin-Vorschau:** Für die Vorschau **vor** der Enthüllung gibt es `GET /api/admin/bummel/races/{race_id}/badge/{cid}.png` (siehe [Admin — Badge-Vorschau](#get-apiadminbummelracesrace_idbadgecidpng)) — sie umgeht das Reveal-Gate (require_admin), der öffentliche Endpoint hier liefert vor der Enthüllung weiter `404`.

---

## GET /api/transport/events

Alle FriesenKutter-Transport-Events (Kalender + manuell) mit kompaktem Live-Fortschritt. Ein Event definiert eine ICAO-Streckenmenge (`route`) und ein `destination`; Fracht zählt nur bei Ankunft am Ziel (Rückflug leer). Das Ziel wird über ein **Fracht-Manifest** (Frachtart + kg) beschrieben, das die eingehenden Flüge der Reihe nach füllen.

**Response** — Array je Event: `id, name, route, destination, dtstart, dtend, source` (`calendar`|`manual`), `radius_km` (Anwesenheitsradius in km, Default 10.0), `total_kg`, `target_kg` (= Σ Manifest oder `null`), `progress_pct` (oder `null`), `flight_count`, `loaded_count`, `cargo` (`[{name, target_kg, delivered_kg, reserved_kg, pct}]`).

## GET /api/transport/event/{id}

Voller Live-Zustand eines Events: obige Felder plus `flights` (chronologisch, **neueste zuerst**): `{dep_time, cid, callsign, name, aircraft, dep, arr, tonnage_kg, loaded, cargo_name, in_air, reserved_kg, loss_kind, lost_kg}`. Beladene Flüge tragen `loaded: true` + `cargo_name` (die Frachtart, in die ihr Anteil überwiegend floss); Rückflüge `loaded: false`, `tonnage_kg: 0`, `cargo_name: null`. `in_air: true` markiert einen noch offenen (verbundenen) Flug Richtung Ziel — solange er nicht beladen ist, trägt er seine volle Zuladung als `reserved_kg` (Reservierung, s. u.). `loss_kind` ∈ `sunk` (in der Luft verschwunden) \| `stolen` (am falschen Ort gelandet) \| `returned` (Ladung ehrlich zurückgebracht) \| `null` (kein Verlust); `lost_kg` > 0 nur bei `sunk`/`stolen`.

Zusätzliche Top-Level-Felder: `participants` (`[{cid, name, callsign, aircraft, flights, delivered_kg, reserved_kg, lost_kg, status}]`, `status` ∈ `flying`\|`arrived`\|`returning`\|`done`; `callsign` = zuletzt gesehenes Rufzeichen — der Kutter-Block im Live-Tab zeigt Callsigns statt Namen), `reserved_total_kg` (Σ aller offenen Reservierungen), `lost_total_kg` (Σ aller Verluste), `losses` (Teilmenge von `flights` mit gesetztem `loss_kind`). `cargo_lines` (Bordladung, Co-Load-Aufschlüsselung) tragen beladene Flüge, Verlust-/Rückbringer-Zeilen UND unterwegs befindliche (`in_air`) Flüge. Die Event-Listen-Ausgabe (`GET /api/transport/events`) enthält zusätzlich `reserved_total_kg` + `lost_total_kg` je Event.

> **Reservierung (ab v7.5.0):** Sobald ein Pilot Richtung Ziel abhebt, reserviert er seine volle
> Zuladung im Manifest (`cargo[].reserved_kg`), noch ohne GPS-Bestätigung — sichtbar schon beim
> Rollen, nicht erst bei Ankunft. Die Reservierung verschwindet mit dem Flug (Latch, Landung
> anderswo, Disconnect) und läuft nie rückwärts in den gelieferten Fortschritt.

> **Ohne Disconnect (Live-Ankunft):** Ein noch offener (verbundener) Flug erscheint im Feed,
> sobald sein Start auf der Strecke liegt; sobald er innerhalb 10 km um `destination` auf
> < 2 kt abbremst, wird er sofort als beladen gezählt (`transport_live_arrivals`) — unabhängig
> vom späteren Disconnect-Ort. Kein Zurücksetzen.

> **Verlorene Fracht:** Ein Flug, der Richtung Ziel gestartet, aber nie dort angekommen ist,
> wird vom Poller (`detect_transport_losses`, alle 60 s) als Verlust erkannt und dauerhaft
> gelatcht (`transport_cargo_losses`) — Klassifikation per letzter Position: am Boden am
> Abflugplatz → `returned`, am Boden anderswo → `stolen`, sonst (in der Luft verschwunden) →
> `sunk`.

---

## GET /widget

Einbettbares HTML-Widget für friesenflieger.de. Zeigt online-Piloten mit Callsigns, eingereichte Prefile-Flugpläne (FRS*), 7-Tage-Flugstunden und — wenn `TS_NOTIFY_ENABLED=true` — einen TeamSpeak-Zähler-Badge `🎧 N im TS`. Design im hellen Stil von friesenflieger.de (bg `#d0e0f0`, Navy `#053080`, Vereinsrot `#D31141`). Klickbar → öffnet friesenspy.devprops.de.

```html
<iframe src="https://friesenspy.devprops.de/widget" width="420" height="88"
  style="border:none;" scrolling="no"></iframe>
```

Die Seite enthält `<meta http-equiv="refresh" content="60">` (60-Sekunden-Auto-Refresh) und wird mit `Access-Control-Allow-Origin: *` ausgeliefert. Vorschau + Einbettungscode: `/widget/preview`.

---

## POST /api/push/subscribe

Browser-Push-Subscription speichern oder aktualisieren.

**Body (JSON)**

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|--------------|
| `endpoint` | string | ✓ | Push-Endpoint-URL des Browsers |
| `p256dh` | string | ✓ | ECDH-Schlüssel (base64url) |
| `auth` | string | ✓ | Auth-Secret (base64url) |
| `pilot_filter` | int[] \| null | — | CID-Liste der zu benachrichtigenden Piloten; `null` = alle. Gilt für **alle drei** Benachrichtigungstypen (Online, Flugplan, TS). Selbst-Ausschluss = eigenen CID weglassen. |
| `notify_prefiles` | bool | — | Auch bei eingereichten oder geänderten Flugplänen benachrichtigen — feuert bei neuem Prefile oder Änderung von Abflugzeit, Abflug- oder Zielflughafen; wird unterdrückt wenn der Pilot bereits online ist (default: true) |
| `notify_ts` | bool | — | TS-Login-Benachrichtigungen für diesen Subscriber aktivieren (default: false) |
| `notify_events` | bool | — | Event-Erinnerungen (~1 h vor Beginn jedes FriesenEvents) und Bummel-Start/Ergebnis-Push aktivieren (default: false) |

**Response** `{"status": "ok"}`

---

## DELETE /api/push/unsubscribe

Push-Subscription entfernen.

**Body (JSON):** `{"endpoint": "<url>"}`

**Response** `{"status": "ok"}`

---

## GET /api/sse

Server-Sent Events Stream. Verbindung bleibt offen; bei jedem VATSIM-Poll-Zyklus (~15s) wird ein Event gesendet.

**Event-Format**

```
data: {"type": "positions", "data": [...]}

```

Das `data`-Feld ist identisch mit der Antwort von `/api/live`.

Alle 30 Sekunden wird ein SSE-Kommentar gesendet um Proxy-Timeouts zu verhindern:

```
: keepalive

```

**Reconnect:** Browser-`EventSource` reconnectet automatisch. Die SPA setzt zusätzlich einen 5-Sekunden-Fallback-Reconnect.

---

## Admin-Authentifizierung

Alle Endpoints unter `/api/admin/*` sind durch ein signiertes httponly-Cookie (`fs_admin`) geschützt. Das Cookie wird beim Login gesetzt und per HMAC-SHA256 verifiziert (Passwort + `SECRET_KEY`). Ein Passwort- oder Key-Wechsel invalidiert alle bestehenden Cookies sofort. Ist `ADMIN_PASSWORD` in `config.env` nicht konfiguriert (leer), geben alle Admin-Endpoints `403` zurück.

### POST /api/admin/login

Admin-Login und Cookie setzen.

**Body (JSON)**

```json
{"password": "mein-passwort"}
```

**Responses**
- `200 {"status": "ok"}` — Cookie `fs_admin` gesetzt (httponly, SameSite=Strict)
- `401 {"detail": "Unauthorized"}` — falsches Passwort oder Admin deaktiviert

---

### POST /api/admin/logout

Cookie löschen.

**Response** `200 {"status": "ok"}`

---

### GET /api/admin/me

Aktuelle Session prüfen.

**Responses**
- `200 {"admin": true}` — gültig eingeloggt
- `401` — kein oder ungültiges Cookie

---

## Admin — Bummel-Verwaltung

Alle folgenden Endpoints erfordern ein gültiges `fs_admin`-Cookie (gesetzt via `POST /api/admin/login`). Fehlt das Cookie oder ist es ungültig, wird `401` zurückgegeben.

### GET /api/admin/bummel/races

Volle Liste aller Bummel-Rennen inkl. interner Felder.

**Response** — Array, neueste zuerst

```json
[
  {
    "id": 1,
    "name": "FriesenFliegerBummel Ostfriesland",
    "route": ["EDWF", "EDWG", "EDWR"],
    "dtstart": "2026-06-27T14:00:00Z",
    "dtend": "2026-06-27T20:00:00Z",
    "radius_km": 10.0,
    "source": "calendar",
    "calendar_uid": "abc123@google.com_20260627T140000Z",
    "status": "revealed",
    "revealed_at": "2026-06-27T21:05:00Z",
    "started_at": "2026-06-27T14:22:00Z",
    "push_enabled": 1,
    "participant_count": 5,
    "overrides": [
      {"cid": 400, "action": "disqualify", "manual_total_min": null, "note": "Falscher Flugplatz"}
    ]
  }
]
```

`source` ∈ `calendar` | `manual`. `started_at` = Zeitstempel des Renn-Starts (erster Pilot mit Blockzeit an einem Streckenflugplatz); `null` = noch nicht gestartet. `push_enabled` = 1 (an) | 0 (aus).

---

### POST /api/admin/bummel/races

Neues Rennen manuell anlegen (ohne Kalender-Termin).

**Body (JSON)**

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|--------------|
| `name` | string | ✓ | Renn-Name |
| `route` | string | ✓ | CSV der Strecken-ICAOs, z.B. `"EDWF,EDWG,EDWR"` |
| `dtstart` | string | ✓ | ISO8601 UTC — Renn-Beginn |
| `dtend` | string | — | ISO8601 UTC — Renn-Ende; fehlt → Mitternacht UTC des Starttags |
| `radius_km` | float | — | Anwesenheitsradius in km (Default: 10.0) |

**Response** `{"id": 42}`

---

### POST /api/admin/bummel/races/{id}

Felder eines bestehenden Rennens aktualisieren. Nur angegebene Felder werden geändert.

**Body (JSON)** — gleiche Felder wie beim Anlegen, alle optional.

**Response** `{"status": "ok"}` oder `404`.

---

### DELETE /api/admin/bummel/races/{id}

Rennen dauerhaft löschen (inkl. aller Overrides).

**Response** `{"status": "ok"}` oder `404`.

---

### POST /api/admin/bummel/races/{id}/reveal

Rennen sofort enthüllen (Notfall-Enthüllung). Setzt `revealed_at = now()`.

**Response** `{"status": "ok"}`

---

### POST /api/admin/bummel/races/{id}/hide

Enthüllung zurücksetzen (wieder verbergen). Setzt `revealed_at = NULL`. Ist das Rennen bereits abgelaufen (`now >= dtend`), wird zusätzlich `reveal_suppressed = 1` gesetzt, damit der automatische Enthüllungs-Job (`update_bummel_reveals`) es nicht binnen einer Minute wieder enthüllt. Ein noch laufendes Rennen wird nur verborgen und am regulären Ende normal automatisch enthüllt. Manuelles Enthüllen (`…/reveal`) hebt die Unterdrückung wieder auf.

**Response** `{"status": "ok"}`

---

### POST /api/admin/bummel/races/{id}/push

Push-Benachrichtigungen für Start und Enthüllung dieses Rennens an- oder abschalten.

**Body (JSON)**

```json
{"enabled": true}
```

**Response** `{"status": "ok"}`

---

### POST /api/admin/bummel/races/{id}/override

Teilnehmer-Override setzen oder aktualisieren (PK `race_id + cid`).

**Body (JSON)**

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|--------------|
| `cid` | int | ✓ | VATSIM-CID des Piloten |
| `action` | string | ✓ | `exclude` \| `disqualify` \| `winner` \| `manual` |
| `manual_total_min` | int | — | Manuelle Block-Gesamtzeit in Minuten (nur bei `action = manual`) |
| `note` | string | — | Interne Notiz |

`exclude` = Pilot aus Wertung und Teilnehmerliste entfernen. `disqualify` = in Ergebnis sichtbar, zählt aber nicht in Schnitt/Ranking. `winner` = erzwungener Sieg (Rang 1). `manual` = eigene Block-Zeit statt gemessener (Schnitt/Ranking werden mit `manual_total_min` neu berechnet).

**Response** `{"status": "ok"}`

---

### DELETE /api/admin/bummel/races/{id}/override/{cid}

Override für einen Piloten entfernen.

**Response** `{"status": "ok"}` oder `404`.

---

### GET /api/admin/bummel/races/{id}/preview

Vollständige Wertung (mit Zeiten, Durchschnitt und Ranking) unabhängig vom Enthüllungsstatus. Overrides sind bereits angewendet. Nützlich um das Ergebnis zu prüfen, bevor enthüllt wird.

**Response** — gleiches Format wie `GET /api/bummel/race/{id}` nach der Enthüllung (`revealed: true`)

Gibt `404` zurück wenn die `id` nicht existiert.

---

### GET /api/admin/bummel/races/{race_id}/badge/{cid}.png

Badge-Vorschau eines Teilnehmers für den Admin — funktioniert **auch vor der Enthüllung** (umgeht das Reveal-Gate des öffentlichen Endpoints). Das Badge wird bei jedem Aufruf **frisch gerendert** (kein Cache).

**Voraussetzungen — sonst `404`:**
- Das Rennen mit `race_id` muss existieren.
- `cid` muss Teilnehmer dieses Rennens sein.

**Response** — `image/png`. Variante (Sieger-Badge vs. Medaille) wie beim öffentlichen Endpoint, anhand des Rangs.

**Response-Header:**
```
Content-Type: image/png
Cache-Control: no-store
```

Der öffentliche Endpoint `GET /api/bummel/race/{id}/badge/{cid}.png` bleibt vor der Enthüllung weiterhin `404`. In der Renn-Vorschau (`admin.html`) öffnet **🎖 Badge** diese Admin-Vorschau, **📋 Forum** kopiert den öffentlichen `[img]…[/img]`-BBCode.

---

## Admin — FriesenKutter (Transport-Events)

Alle Endpoints erfordern das Admin-Cookie (`require_admin`).

> **Kalender-Fracht:** Ein Termin mit dem `friesenkutter`-Marker kann direkt in der Beschreibung eine Fracht-Zeile enthalten: `Fracht: 1000 Krabbenbrötchen, 500 Friesentee`. Beim Sync wird sie **einmalig** (nur beim erstmaligen Anlegen) gegen den Frachtart-Katalog abgeglichen und ins Manifest übernommen; ein später im Admin gepflegtes Manifest bleibt bei erneutem Sync unverändert.

### GET /api/admin/transport/events
Liste aller Events inkl. Fracht-Manifest (`cargo: [{id, position, name, target_kg}]`) und `radius_km` (Anwesenheitsradius in km; `null` = Default 10.0).

### POST /api/admin/transport/events
Manuelles Event anlegen. Body: `name`, `route` (Freitext/ICAO-CSV, wird normalisiert; ≥2 ICAOs), `destination` (ICAO; leer → letzter Streckenplatz), `dtstart` (UTC, Pflicht), `dtend` (optional, sonst Mitternacht UTC), `cargo` (`[{name, target_kg}]`), `radius_km` (optional, 0.5–50; leer/fehlend = Default 10 km). → `{status, id}`.

### POST /api/admin/transport/events/{id}
Bearbeiten. Übergebene Felder aus `name/route/destination/dtstart/dtend/radius_km` werden aktualisiert; `cargo` (falls gesetzt) **ersetzt** das Manifest.

### DELETE /api/admin/transport/events/{id}
Event samt Manifest löschen.

### GET /api/admin/transport/payloads
Zuladungs-Tabelle + globaler Fallback + beobachtete, noch nicht gepflegte Flugzeugtypen. Response: `payloads` (`[{type_code, mtow_kg, empty_kg, fuel_kg, crew_kg, payload_kg, source, make_model}]`), `unmapped_types`, `default_kg`, `llm_configured`.

### POST /api/admin/transport/payloads
Zuladung eines Typs setzen. Body: `type_code` (Pflicht), `mtow_kg`, `empty_kg`, `fuel_kg` (Tankinhalt, Default halbe Füllung), `crew_kg` (Pilot/Crew, Default 85 — zählt nicht als Fracht), optional direktes `payload_kg` (überschreibt die Ableitung `max(0, mtow−empty−fuel−crew)`), `make_model`.

### GET /api/admin/transport/payloads/suggest?type=C172
KI-Vorschlag (Claude Haiku 4.5 mit **Web-Search**, Structured Output; seit v7.4.2) für die Komponenten eines Typs — recherchiert dokumentierte Handbuch-/POH-Werte (keine Schätzungen): `{make_model, mtow_kg, empty_kg, fuel_kg, fuel_full_kg, crew_kg, payload_kg}` (Zuladung = MTOW − Leer − halbe Tankfüllung − Crew; `fuel_kg` = halbe Füllung als Default, `fuel_full_kg` = Maximum, volle Tanks). Dauer ~15–30 s (Basis-Web-Search `web_search_20250305`, gestreamt, `max_retries=0` — das neuere Dynamic-Filtering-Tool drehte bei obskuren Typen minutenlang in code_execution-Runden, s. v7.4.1). `400`, wenn `ANTHROPIC_API_KEY` fehlt.

### POST /api/admin/transport/default-payload
Globalen Fallback-Zuladungswert setzen. Body: `default_kg`.

### GET /api/admin/transport/catalog
Frachtart-Katalog (Stammdaten): `[{id, name, emoji, per_flight_max_kg, position}]`.

### POST /api/admin/transport/catalog
Frachtart anlegen/ändern. Body: `name` (Pflicht), `emoji`, `per_flight_max_kg` (Obergrenze pro Flug für Co-Load; NULL = keine Kappung), `id` (für Update).

### DELETE /api/admin/transport/catalog/{id}
Frachtart aus dem Katalog entfernen (bestehende Event-Manifeste bleiben unverändert).

### POST /api/admin/transport/quips-enabled
Lustige KI-Sprüche global an-/ausschalten. Body: `enabled` (bool). Wirken nur mit `ANTHROPIC_API_KEY`.

> **Event-Ausgabe (Phase 2):** `GET /api/transport/event/{id}` liefert zusätzlich je Frachtart `cargo[].emoji`, je Flug `cargo_lines` (`[{name, emoji, kg}]`, Co-Load) und `quip` (gecachter KI-Spruch, sonst `null`) sowie `summary_quip` (lustige Tagesend-Zusammenfassung).

## Admin — Hinweis-Banner

Steuert, welcher Changelog-Eintrag auf der Startseite als Banner erscheint (gespeichert in `app_settings['banner_version']`). Die aufgelöste Version liefert `GET /api/frontend-config` im Feld `banner_version`.

### GET /api/admin/banner

Aktuelle Auswahl + alle Changelog-Einträge für die Admin-Auswahl.

**Response**

```json
{
  "selected": "auto",
  "entries": [
    {"version": "6.4.0", "date": "2026-06-28", "title": "Admin-Erweiterungen", "highlight": true}
  ]
}
```

`selected` ∈ `auto` | `off` | konkrete Version.

### POST /api/admin/banner

Banner-Auswahl setzen.

**Body (JSON)**

```json
{"version": "auto"}
```

`version` ∈ `auto` (neuester Highlight-Eintrag, Default) | `off` (kein Banner) | konkrete Version (genau dieser Eintrag).

**Response** `{"status": "ok", "selected": "auto", "resolved": "6.4.0"}` — `resolved` ist die aufgelöste Version (oder `null`).

---

## Admin — Push (Test & Broadcast)

### POST /api/admin/push/test

Test-Benachrichtigung **nur** an das angegebene (eigene) Gerät senden — nie an andere Friesen. Der Browser meldet seinen eigenen Push-Endpoint; gesendet wird ausschließlich an genau diese eine Subscription (Lookup via `get_push_subscription_by_endpoint`).

**Body (JSON)**

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|--------------|
| `endpoint` | string | ✓ | Push-Endpoint-URL des eigenen Browsers |
| `title` | string | — | Titel als Vorschau (leer → Standard „FriesenSpy Test ✅") |
| `body` | string | — | Text als Vorschau (leer → Standard-Testtext) |

**Responses**
- `200 {"status": "ok", "sent": 1}`
- `400` — VAPID nicht konfiguriert oder `endpoint` fehlt
- `404` — Endpoint unbekannt (in der App zuerst Push aktivieren)

### POST /api/admin/push/broadcast

Freie Nachricht (Titel + Text) als Push an eine wählbare Zielgruppe senden.

**Body (JSON)**

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|--------------|
| `title` | string | ✓ | Titel der Benachrichtigung |
| `body` | string | ✓ | Nachrichtentext |
| `audience` | string | — | `all` (alle Abonnenten, Default) \| `events` (nur Events-Abonnenten, `notify_events = 1`) |

**Responses**
- `200 {"status": "ok", "audience": "all", "sent": <Anzahl Empfänger>}`
- `400` — VAPID nicht konfiguriert oder `title`/`body` fehlt

---

## Admin — Piloten-Verwaltung

Verwaltung der `pilots`-Tabelle (Namenspflege/manuelles Anlegen). **Keine Mitglieder-Allowlist** — Friesen werden weiter über das Callsign-Präfix `FRS` (`settings.CALLSIGN_PREFIX`) erkannt, die Tabelle füllt sich automatisch aus VATSIM.

### GET /api/admin/pilots

Alle bekannten Piloten, nach Name sortiert. `callsigns` = sortierte Liste aller distinct FRS-Callsigns dieser CID aus der `flights`-Tabelle (leer, wenn keine Flüge) — zeigt, wenn eine CID mehrere Tags nutzt.

**Response**

```json
[
  {"cid": 1602713, "name": "Tobias EDKB", "added_at": "2026-06-04T07:14:54Z", "callsigns": ["FRS49", "FRS 144"]}
]
```

### POST /api/admin/pilots

Pilot anlegen oder Namen aktualisieren (`added_at` bleibt beim Update erhalten).

**Body (JSON)**

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|--------------|
| `cid` | int | ✓ | VATSIM-CID |
| `name` | string | ✓ | Anzeigename |

**Responses**
- `200 {"status": "ok", "cid": 1602713, "name": "Tobias EDKB"}`
- `400` — ungültige `cid` oder fehlender `name`

### DELETE /api/admin/pilots/{cid}

Pilot aus der `pilots`-Tabelle entfernen.

**Response** `{"status": "ok"}`
