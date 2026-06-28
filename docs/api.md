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

`duration_min` = **Online-Zeit** (Verbindung logon→logoff). `block_min` = **Block-Zeit** (Bewegung erste→letzte GPS-Bewegung, gate-to-gate) — nur bei FriesenSpy-Flügen vorhanden, StatSim/Altflüge haben `null`.

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
  "count": 3,
  "complete": [
    {"cid": 300, "name": "Cara", "callsign": "FRS300", "total_min": 80,
     "aircraft": "C172", "leg_count": 2,
     "visited": ["EDWF","EDWG","EDWR"], "missing": [], "legs": [],
     "rank": 1, "delta": 0.0}
  ],
  "incomplete": [
    {"cid": 500, "name": "Emil", "callsign": "FRS500", "total_min": 35,
     "aircraft": "C172", "leg_count": 1,
     "visited": ["EDWF","EDWG"], "missing": ["EDWR"], "legs": []}
  ]
}
```

`complete` ist aufsteigend nach `delta` (Abstand zur Durchschnittszeit) sortiert; `rank` 1 ist der Sieger. `incomplete`-Piloten haben noch nicht alle Flugplätze besucht und zählen nicht in den Schnitt.

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
| **Sieger-Badge „Absoluter Durchschnitt!"** (helle Kuppel) | Rang 1 | Callsign, Name, Flugzeugmuster, Block-Gesamtzeit, Zeitdifferenz zum Schnitt, Fußzeile „friesenflieger.de" |
| **Medaille „Voll daneben!"** (navy Kern) | alle anderen (auch unvollständige) | Callsign, Name, Flugzeugmuster, Datum, Zeitdifferenz (falls komplett), Fußzeile „friesenflieger.de" |

**Caching:** Das fertige PNG wird serverseitig unter `data/badges/<race_id>_<cid>.png` gecacht; bei wiederholtem Aufruf wird die Datei direkt aus dem Cache ausgeliefert.

**Response-Header:**
```
Content-Type: image/png
Cache-Control: public, max-age=86400
```

**BBCode für board.friesenflieger.de:**
```
[img]https://friesenspy.devprops.de/api/bummel/race/{race_id}/badge/{cid}.png[/img]
```

Der **„📋 Forum"**-Button im enthüllten Ranking kopiert diesen BBCode direkt in die Zwischenablage. Der **„🎖 Badge"**-Button öffnet das PNG in einem neuen Tab.

> **Admin-Vorschau:** Für die Vorschau **vor** der Enthüllung gibt es `GET /api/admin/bummel/races/{race_id}/badge/{cid}.png` (siehe [Admin — Badge-Vorschau](#get-apiadminbummelracesrace_idbadgecidpng)) — sie umgeht das Reveal-Gate (require_admin), der öffentliche Endpoint hier liefert vor der Enthüllung weiter `404`.

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

Enthüllung zurücksetzen (wieder verbergen). Setzt `revealed_at = NULL`.

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

Alle bekannten Piloten, nach Name sortiert.

**Response**

```json
[
  {"cid": 1602713, "name": "Tobias EDKB", "added_at": "2026-06-04T07:14:54Z"}
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
