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
| `days` | int | `30` | Zeitraum in Tagen; serverseitig auf `1…365` geklemmt (#67, globale Anzeigegrenze) |

Gruppierung: ≤93 Tage → täglich (`%Y-%m-%d`), >93 Tage → monatlich (`%Y-%m`). Alle Perioden werden zurückgegeben (Lücken mit 0 aufgefüllt). Nur FRS*-Callsigns. Aggregiert über `get_cached_flights` (`flight_cache`, materialisierte `canonicalize_legs`-Ergebnisse — GPS-only Phase 2, #23) — dieselbe kanonische Flugmenge wie `/api/stats` und (dort live über `canonicalize_legs`) `/api/pilots/{cid}/flights`: Flüge/Etappen sind aus dem GPS-Track erkannt (echte Landung am Platz), Reconnect-Fragmente ohne Track fallen weiterhin auf die klassische Refile-/Disconnect-Erkennung zurück. Ein noch nicht gelandeter Flug (`logoff_time IS NULL AND connection_closed = false`) wird nicht mitgezählt. Dadurch stimmen die Zahlen über alle Views überein.

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
| `days` | int | `30` | Zeitraum in Tagen (UI: 30, 90, 365); serverseitig auf `1…365` geklemmt (#67, globale Anzeigegrenze) |
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

`flight_count` = `fs_count` + `st_count`. StatSim-Daten sind nur vorhanden wenn der Pilot zuvor im Statistiken-Tab angeklickt wurde (lazy cache). Zählung und Dauer kommen aus `get_cached_flights` (`flight_cache`, materialisierte `canonicalize_legs`-Ergebnisse — GPS-only Phase 2, #23), identisch zu `/api/stats/activity`; die Piloten-Detailansicht (`/api/pilots/{cid}/flights`) ruft `canonicalize_legs` für ihren einen Piloten live (ungecacht) auf — gleiche Wahrheit, nur ohne den globalen Cache.

---

## GET /api/stats/special-events

Aggregierte Kennzahlen beider Spezial-Events im Zeitfenster (`?days=30|90|365`, Default 30, Whitelist —
`days>365` würde die Snapshot-Retention überschreiten). NUR abgeschlossene Events/Rennen, bedient aus den
#66-Snapshots (kein Track-Recompute). Antwort:
`{"kutter": {event_count, participations, flights, delivered_kg, sunk_kg, sunk_count, stolen_kg, stolen_count},
  "bummel": {race_count, participations, legs, avg_absolute_min}}`.
Abgrenzung: Kutter „Flüge" = alle Flug-/Verlust-Zeilen (`flight_count`); Bummel „Flüge" = gewertete Tour-Legs
(`Σ leg_count`). `returned` (zurückgebracht) ist kein Verlust (0 kg). `avg_absolute_min` ist `null` ohne
gewertetes Rennen. NULL-`dtend`-Events werden ausgeschlossen.

---

## GET /api/pilots/{cid}/flights

Alle Flüge eines Piloten — GPS-only Phase 2 (#23): die Antwort kommt direkt und live (ungecacht) aus `canonicalize_legs` (`callsign_prefix=""`, zeigt also auch Flüge unter einem Nicht-FRS-Callsign desselben Piloten). Abheben und Landung werden primär aus dem GPS-Track erkannt (echte Landung an einem Flugplatz, auch Zwischenlandungen ohne neuen Flugplan als eigene Zeile); fehlt ein Track, greift der refile-/disconnect-basierte Fallback (Reconnect-Merge). FriesenSpy-eigene Aufzeichnungen und StatSim-Historik werden dedupliziert kombiniert. Antwortet **sofort**; StatSim-Update läuft im Hintergrund (letzter 31-Tage-Chunk). Response-Header `X-StatSim-Status: fresh | updating | no-key`.

**Query-Parameter**

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `days` | int | `365` | Anzeigefenster in Tagen; serverseitig auf `1…365` geklemmt (#67). `0` = „letztes Jahr": zeigt genau 365 Tage **und** stößt den vollen StatSim-Refresh an (früher ungekappt). Ältere Legs bleiben in der DB, werden aber nicht angezeigt. |

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
    "gps_departure": "EDKB",
    "gps_arrival": "EDDK",
    "plan_departure": "EDKB",
    "plan_arrival": "EDDK",
    "connection_closed": true,
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
    "gps_departure": "EDKB",
    "gps_arrival": "EDDF",
    "plan_departure": "EDKB",
    "plan_arrival": "EDDF",
    "connection_closed": true,
    "aircraft": "PA24/L-SDGRY/S",
    "logon_time": "2026-06-01T14:30:00Z",
    "logoff_time": "2026-06-01T15:50:00Z",
    "duration_min": 80
  }
]
```

Sortiert nach `logon_time` absteigend. FriesenSpy-Einträge haben Vorrang bei Zeitstempel-Überschneidungen (±5 Min).

**Neue Felder (GPS-only Phase 2, #23):**

| Feld | Beschreibung |
|------|--------------|
| `gps_departure` / `gps_arrival` | Start-/Ziel-ICAO, wie es der GPS-Leg-Detektor erkannt hat (erste/letzte Position im 4-km-Umkreis eines Flugplatzes). `null`, wenn kein Track vorlag oder der Flug noch nicht gelandet ist. |
| `plan_departure` / `plan_arrival` | DEP/ARR aus dem eingereichten Flugplan (reine Beschriftung, keine Grundlage mehr für die Flugzählung). Kann von `gps_*` abweichen, z. B. bei einer Zwischenlandung ohne Refile — oder wenn der Pilot bereits vor der Landung des aktuellen Beins den nächsten Plan eingereicht hat (zeitbasierte Zuordnung, Stand 2026-07-05). |
| `connection_closed` | `true`, wenn die zugrunde liegende VATSIM-Verbindung beendet ist (`logoff_time` gesetzt). **Kein** Indikator dafür, ob der Flug selbst fertig geflogen ist — das entscheidet allein `arrival`/`gps_arrival`/`logoff_time`, und „🛫 läuft" leitet das Frontend seit v8.1.0 aus `last_pos_ts` (Frische), nicht aus diesem Feld ab. |
| `last_pos_ts` | (v8.1.0) ISO8601 UTC — Zeit der **letzten belegten Position** dieses Legs (statisch, nicht „now"). Für einen geschlossenen Flug = Landung/letzte Position; für einen offenen Flug = letzte empfangene Position. Das Frontend zeigt „🛫 läuft" nur, wenn der Flug offen ist **und** `last_pos_ts` frisch (< 15 min alt), und nutzt den Wert als Obergrenze beim Nachladen des GPS-Tracks offener Legs. |
| `block_start` | (v8.9.0) ISO8601 UTC — **Rollbeginn** (Rückwärts-Walk ab dem Abheben `logon_time` bis zum ersten zusammenhängenden Sample, begrenzt durch das Ende des Vorflugs/eine 30-min-Lücke). Das Frontend nutzt ihn als **Untergrenze** beim Nachladen des GPS-Tracks der gefensterten FriesenSpy-Endpoints (`/api/flights/{id}/track`, `/api/pilots/{cid}/track`), damit Taxi-out + Startlauf sichtbar sind, statt erst am Abheben zu beginnen. Ohne Track/bei Fallback-Zeilen nicht gesetzt → das Frontend fällt auf `logon_time` zurück. |

`departure`/`arrival` bleiben aus Kompatibilitätsgründen erhalten und entsprechen im Regelfall `gps_departure`/`gps_arrival` (Fallback auf den Flugplan, wenn kein GPS-Wert vorliegt).

`duration_min` = **Flugzeit** (Abheben → Landung). `block_min` = **Blockzeit** (Summe der GPS-Bewegungsabschnitte gate-to-gate inkl. Taxi; belegte Standphasen ≥ 10 min, z. B. eine Zwischenlandung ohne Disconnect, zählen nicht) — nur bei FriesenSpy-Flügen vorhanden, StatSim/Altflüge haben `null`.

Flüge unter einem **Nicht-`FRS`-Callsign** (`callsign_prefix=""` liefert sie mit) erscheinen ebenfalls in der Antwort, zählen aber nicht in Statistik, FriesenFliegerBummel oder FriesenKutter (das Frontend markiert sie als „nicht gewertet").

---

## GET /api/pilots/{cid}/live-track

GPS-Track des aktuell laufenden Fluges aus `position_history` (logoff_time IS NULL). Leeres Array wenn der Pilot nicht online ist.

**Response** — gleiches Format wie `/api/flights/{id}/track`

---

## GET /api/pilots/{cid}/track

(v8.1.0) GPS-Track eines Legs rein über **cid + Zeitfenster** aus `position_history` — anders als `/api/flights/{id}/track` **ohne** `flights`-Zeile. Bedient GPS-Legs ohne zugeordneten Flugplan (`id = null`), sodass der Track in jeder Flugzeile ladbar ist (GPS-only).

**Query-Parameter** (optional)

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| `logon` | string | ISO8601 UTC — untere Fenstergrenze. Das Frontend übergibt seit v8.9.0 den **Rollbeginn** (`block_start`, Fallback `logon_time`/Takeoff), damit Taxi-out + Startlauf im Track erscheinen. |
| `logoff` | string | ISO8601 UTC — obere Fenstergrenze; für offene Legs die letzte Positionszeit (`last_pos_ts`), **nicht** „now", sonst würden Positionen späterer Flüge mitgezogen. Fehlt der Wert, wird „now" verwendet. |

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
| `start` | string | `""` | ISO8601 UTC, z.B. `2024-01-01T10:00:00Z`. Serverseitig auf frühestens `now − 365 Tage` angehoben (#67); ein leerer/älterer Wert wird auf diese Grenze gesetzt. |
| `end` | string | `""` | ISO8601 UTC, z.B. `2024-01-01T18:00:00Z` |

**Retention (#67):** Die Event-Analyse durchsucht nur die letzten 365 Tage — das UI lässt kein älteres Datum wählen (`min`-Attribut + Hinweis „Nur die letzten 365 Tage sind durchsuchbar."), das Backend klemmt `start` zusätzlich. Ältere Positionen bleiben in der DB (der tägliche Cleanup ist deaktiviert), sind aber nicht durchsuchbar. Verhindert irreführende Teil-Treffer aus einem bewusst ausgeblendeten Zeitraum.

**Response**

Flüge kommen seit v8.3.0 aus `canonicalize_legs` (#33) — dieselbe Wahrheit wie
`/api/pilots/{cid}/flights` (Statistik/Piloten-Detail). Ein Flug kann jetzt in mehrere
GPS-Legs aufgeteilt sein (z. B. Landung + echte Bodenpause + Weiterflug = zwei Einträge).

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
          "aircraft": "PA24",
          "aircraft_icao": "PA24",
          "gps_departure": "EDKB",
          "gps_arrival": "EDDK",
          "plan_departure": "EDKB",
          "plan_arrival": "EDDK",
          "connection_closed": true,
          "last_pos_ts": "2026-06-04T10:20:00Z",
          "block_start": "2026-06-04T09:20:00Z",
          "duration_min": 55,
          "block_min": 62,
          "distance_nm": 42,
          "route": "DCT",
          "id": 4711,
          "statsim_id": null,
          "cid": 1602713,
          "source": "friesenspy"
        }
      ]
    }
  ]
}
```

`gps_departure`/`gps_arrival` sind die tatsächlich per GPS erkannte Strecke, `plan_departure`/
`plan_arrival` der eingereichte Flugplan (falls vorhanden — kann bei einer Zwischenlandung ohne
Refile von der GPS-Route abweichen). `connection_closed` ist ein Flugplan-Begriff (VATSIM-Session
beendet) — NICHT gleichbedeutend mit „gelandet"; ob der Flug selbst beendet ist, entscheidet
`gps_arrival`/`logoff_time`. `last_pos_ts` ist die letzte belegte GPS-Position (Obergrenze für
Live-Erkennung und Track-Nachladen, nie „jetzt"). `id`/`statsim_id`/`cid` identifizieren die
Track-Quelle (s. u.). Positionen selbst sind **nicht mehr embedded** — das Frontend lädt den
Track pro Flug bei Bedarf nach.

Jeder Flug-Eintrag enthält ein `source`-Feld: `"friesenspy"` für live von FriesenSpy erkannte
Flüge, `"statsim"` für Einträge aus dem StatSim-Cache. Der Track wird unabhängig von `source`
nachgeladen — StatSim-Flüge bekommen ihren GPS-Track ebenso automatisch im Hintergrund nachgefüllt
(`app/poller.py` `_fetch_statsim_tracks`, unabhängig vom Callsign-Präfix) und zeigen ihn dann
identisch zu einem live aufgezeichneten Flug an:
- `source == "statsim"` → `GET /api/flights/statsim/{statsim_id}/track`
- `source == "friesenspy"` und `id` gesetzt → `GET /api/flights/{id}/track`
- sonst (GPS-Leg ohne Flugplan-Zuordnung) → `GET /api/pilots/{cid}/track?logon=...&logoff=...`

**StatSim-Fallback:** Piloten die in `statsim_cache` per `departure` oder `arrival` im Zeitfenster
gefunden werden, aber keine `position_history` haben (z. B. weil FriesenSpy zu diesem Zeitpunkt
nicht lief), erscheinen ebenfalls in der Antwort — mit `source: "statsim"`.

**2-Klassen-Regel:** Flüge mit einem Callsign außerhalb des konfigurierten `CALLSIGN_PREFIX`
(z. B. ein FriesenSpy-Pilot, der unter einem anderen virtuellen-Airline-Callsign fliegt)
erscheinen HIER NICHT — die gehören nur in die Piloten-Statistik (`/api/pilots/{cid}/flights`,
das dort `callsign_prefix=""` verwendet).

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
  "banner_version": "6.4.0",
  "callsign_prefix": "FRS"
}
```

`version` + `changelog` stammen aus `app/CHANGELOG.json` (via `app/version.py`). `version` ist
die neueste Version (`changelog[0].version`). Das Frontend zeigt damit die kleine Versionsnummer
im Header, das Changelog-Banner (neueste Version, einmal pro Version) und den Versionsverlauf.

`callsign_prefix` spiegelt `settings.CALLSIGN_PREFIX` (Default `FRS`) — das Frontend nutzt ihn
seit GPS-only Phase 2 (#23), um in der Piloten-Detailliste Flüge unter einem Nicht-Präfix-Callsign
als „nicht gewertet" zu markieren, statt den Präfix hart zu verdrahten.

`banner_version` ist die vom Server aufgelöste Version, deren Changelog-Eintrag als Startseiten-Banner
angezeigt werden soll — oder `null`, wenn kein Banner erscheinen soll. Sie wird aus der Admin-Auswahl
(`app_settings['banner_version']`) über `_resolve_banner_version` abgeleitet: `auto` → neuester Eintrag
mit `highlight: true` (Fallback: neuester Eintrag), `off` → `null`, eine konkrete Version → genau diese
(falls sie existiert, sonst `null`). Steuerbar über `GET`/`POST /api/admin/banner`.

---

## GET /api/calendar/events

FriesenEvents aus dem FriesenFlieger-Google-Kalender — letzte 365 Tage bis heute, absteigend nach Startdatum (neueste zuerst).

Der Kalender wird alle 6 Stunden automatisch synchronisiert. RRULE-Wiederholungstermine werden expandiert (jede Wiederholung als eigener Eintrag). Ganztags-Events (ohne Uhrzeit) werden nicht gespeichert. Termine, die im Google-Kalender gelöscht/storniert wurden, entfernt derselbe Sync-Lauf per Mark-and-Sweep (`delete_stale_calendar_events`) wieder aus der lokalen Kopie — sie verschwinden hier spätestens beim nächsten Sync.

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

**Retention (v8.10.0, #66/#67):** zeigt nur Rennen der letzten 365 Tage (`dtend` innerhalb des Fensters bzw. `NULL`) — reine Anzeige-Grenze, nichts wird gelöscht; ältere Rennen bleiben in `GET /api/admin/bummel/races` (ungefiltert) sichtbar. Ein bereits enthülltes Rennen (`revealed_at` gesetzt **und** `now >= dtend`) wird aus einem beim ersten Abruf eingefrorenen Snapshot bedient statt bei jedem Request neu berechnet — Korrekturen greifen erst, sobald das Rennen im Admin erneut gespeichert wird.

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

**Retention (v8.10.0, #66/#67):** zeigt nur Events der letzten 365 Tage (`dtend` innerhalb des Fensters bzw. `NULL`) — reine Anzeige-Grenze, nichts wird gelöscht; ältere Events bleiben in `GET /api/admin/transport/events` (ungefiltert) sichtbar. Ein bereits abgeschlossenes Event (`summarized_at` gesetzt) wird aus einem beim Feierabend-Latch eingefrorenen Snapshot bedient statt bei jedem Request neu berechnet — Korrekturen greifen erst, sobald das Event im Admin erneut gespeichert wird.

**Response** — Array je Event: `id, name, route, destination, dtstart, dtend, source` (`calendar`|`manual`), `radius_km` (Legacy-Feld, seit GPS-only Phase 2/#23 wirkungslos — die Platz-Zuordnung nutzt überall den festen globalen 4-km-Radius; über die Admin-Endpoints nicht mehr setzbar, i. d. R. `null`), `total_kg` (= Σ tatsächlich ins Manifest gelieferter Fracht, „durchgängig Netto" seit v8.8.0/#63 — Überschuss ohne Manifest-Platz zählt nicht; bei Events ohne Manifest schlichter Brutto-kg-Zähler), `target_kg` (= Σ Manifest oder `null`), `progress_pct` (oder `null`), `flight_count`, `loaded_count`, `cargo` (`[{name, target_kg, delivered_kg, reserved_kg, lost_kg, pct, per_flight_max_kg, departure}]`; `lost_kg` (v8.20.0/#7/#8) = unwiederbringlich verlorene (`stolen`/`sunk`) Menge dieser Frachtart, **netto** (nur was real an Bord war, nicht das volle Ziel) — verlorene Ware wird dauerhaft aus dem ladbaren Rest genommen (`verfügbar = target − delivered − lost − reserved`), macht ein Event ggf. unvollendbar und zeigt, warum es <100 % bleibt; `returned` zählt hier NICHT (Ware kam heil zurück); `per_flight_max_kg` = Obergrenze pro Flug oder `null`; `departure` = gebundene Startplatz-LISTE (kommagetrennte ICAOs, seit v8.14.0/#84; einzelner ICAO oder `null` = geteilt) — nur Flüge von einem dieser Startplätze laden die Frachtart, das Frontend gruppiert die Balken danach. Seit v8.14.0 gibt es kein separates `Strecke`-Feld mehr: `route` wird aus den Startplätzen der Fracht + Ziel abgeleitet).

## GET /api/transport/event/{id}

Voller Live-Zustand eines Events: obige Felder plus `flights` (chronologisch, **neueste zuerst**): `{dep_time, cid, callsign, name, aircraft, dep, arr, tonnage_kg, onboard_kg, loaded, cargo_name, in_air, airborne, reserved_kg, onboard_reserved_kg, loss_kind, lost_kg}`. Beladene Flüge tragen `loaded: true` + `cargo_name` (die Frachtart, in die ihr Anteil überwiegend floss); `tonnage_kg` ist die tatsächlich ins Manifest gutgeschriebene Menge (Netto, seit v8.8.0/#63 — nicht mehr die volle Musterzuladung; ein spät ankommender Flug, dessen Fracht keinen Manifest-Platz mehr findet, trägt entsprechend weniger oder 0 kg), `onboard_kg` die volle transportierte Musterzuladung (für die „belegt / an Bord"-Anzeige `50 / 381 kg` — die zweite Zahl nur bei Abweichung). Rückflüge `loaded: false`, `tonnage_kg: 0`, `cargo_name: null`. `in_air: true` markiert einen noch offenen (verbundenen) Flug Richtung Ziel — solange er nicht beladen ist, ist `reserved_kg` die tatsächlich reservierbare Menge (Netto, was noch ins Manifest passt) und `onboard_reserved_kg` die volle Musterzuladung an Bord (Reservierung, s. u.). `airborne` (nur bei `in_air`) trennt „wirklich abgehoben" von „am Streckenplatz geparkt": `false`, solange der Pilot am Boden steht (kein offenes GPS-Leg erkannt — Anzeige „lädt in <Platz> 🅿️"; der Abholplatz `dep` kommt seit v8.22.0/#5 aus der **aktuellen** Live-Position am Boden, GPS-only, nicht mehr aus dem Flugplan), `true` erst nach dem tatsächlichen Abheben („unterwegs ✈️") **oder** wenn der Pilot mitten auf der Reise an einem Wegpunkt geparkt steht (v8.12.1/#15A: seine Verbindung hat bereits ein Strecken-Bein abgeschlossen → „unterwegs", nicht „am Start"). `in_air`/`reserved_kg` sind davon unberührt — geparkte Piloten reservieren bereits. `loss_kind` ∈ `sunk` (in der Luft verschwunden) \| `stolen` (an einem Platz **außerhalb der Strecke** gelandet) \| `returned` (Ladung an einem **Strecken-Wegpunkt** zurückgebracht) \| `null` (kein Verlust); `lost_kg` > 0 nur bei `sunk`/`stolen`.

Zusätzliche Top-Level-Felder: `participants` (`[{cid, name, callsign, aircraft, flights, delivered_kg, reserved_kg, lost_kg, status}]`, `status` ∈ `flying`\|`arrived`\|`returning`\|`done`; `callsign` = zuletzt gesehenes Rufzeichen — der Kutter-Block im Live-Tab zeigt Callsigns statt Namen), `reserved_total_kg` (Σ aller offenen Reservierungen), `lost_total_kg` (Σ aller Verluste), `losses` (Teilmenge von `flights` mit gesetztem `loss_kind`). `cargo_lines` (Bordladung, Co-Load-Aufschlüsselung) tragen beladene Flüge, Verlust-/Rückbringer-Zeilen UND unterwegs befindliche (`in_air`) Flüge. Die Event-Listen-Ausgabe (`GET /api/transport/events`) enthält zusätzlich `reserved_total_kg` + `lost_total_kg` je Event.

> **Reservierung (ab v7.5.0):** Sobald ein Pilot Richtung Ziel abhebt, reserviert er seine volle
> Zuladung im Manifest (`cargo[].reserved_kg`), noch ohne GPS-Bestätigung — sichtbar schon beim
> Rollen, nicht erst bei Ankunft. Die Reservierung verschwindet mit dem Flug (Latch, Landung
> anderswo, Disconnect) und läuft nie rückwärts in den gelieferten Fortschritt.

> **Ohne Disconnect (Live-Ankunft):** Ein noch offener (verbundener) Flug erscheint im Feed,
> sobald sein Start auf der Strecke liegt; sobald er innerhalb des festen 4-km-Radius um
> `destination` auf < 2 kt abbremst, wird er sofort als beladen gezählt (`transport_live_arrivals`)
> — unabhängig vom späteren Disconnect-Ort. Kein Zurücksetzen.

> **Verlorene Fracht:** Ein Flug, der Richtung Ziel gestartet, aber nie dort angekommen ist,
> wird vom Poller (`detect_transport_losses`, alle 60 s) als Verlust erkannt und dauerhaft
> gelatcht (`transport_cargo_losses`) — Klassifikation per letzter Position: am Boden an einem
> **Strecken-Wegpunkt** (inkl. Abflugplatz) → `returned`, am Boden **außerhalb der Strecke** →
> `stolen`, sonst (in der Luft verschwunden) → `sunk`. (v8.12.1/#15A: `returned` galt früher nur
> am Abflugplatz — an einem anderen Wegpunkt wurde die Fracht fälschlich als geklaut gewertet.)

`GET /api/transport/event/{id}` liefert außerdem `summarized_at` (Latch der Feierabend-Bilanz,
`null` solange offen) — Voraussetzung für den Kutter-Badge (s. u.).

---

## GET /api/transport/event/{event_id}/badge/{cid}.png

Forum-Badge (PNG) für einen FriesenKutter-Teilnehmer. Erst nach der Feierabend-Bilanz verfügbar
(kein Zwischenstand als „fertig" verewigt).

**Voraussetzungen — sonst `404`:**
- Das Event mit `event_id` muss existieren und **abgeschlossen** sein (`summarized_at IS NOT NULL`).
- `cid` muss Teilnehmer dieses Events sein (`participants` aus `compute_transport_progress`).

**Response** — `image/png`

Rund (256 × 256 px), transparenter Rand, navy Kern („Voll beladen!") wie die Bummel-Medaille:
Callsign, Flugzeugmuster, **Gesamt-Tonnage des TEAMS** (v8.8.1/#64 — z. B. „1610 / 2810 kg Team",
aus `progress["total_kg"]`/`["target_kg"]`, NICHT nur der Anteil dieses einen Piloten), Event-Name
+ Datum, Fußzeile „friesenflieger.de". Hat der Teilnehmer Fracht verloren (`stolen_kg`/`sunk_kg` >
0, aus `losses` aufsummiert — `returned` zählt nicht als Verlust), erscheint zusätzlich ein
Verlust-Titel: **SPITZBOOV!** (nur geklaut), **BADEMESTER!** (nur versenkt) oder **SEEROVER!**
(beides), plus eine Mengen-Zeile („150 kg geklaut, 292 kg versenkt").

**Caching (ETag + Revalidierung):** Aus den ergebnisrelevanten Feldern (`summarized_at`,
`delivered_kg`, `stolen_kg`, `sunk_kg`, `aircraft`, `callsign`, `event`, `team_total_kg`) wird ein
MD5-Hash gebildet, der als `ETag` dient und in den Cache-Dateinamen einfließt
(`data/badges/kutter_<event_id>_<cid>_<hash>.png`). `Cache-Control: no-cache` + `ETag`; passendes
`If-None-Match` → `304 Not Modified`. Der Hash enthält außerdem `_BADGE_RENDER_VERSION` (in
`app/main.py`) — eine Änderung am Badge-Rendering (z. B. Layout-Fix) erzwingt so automatisch die
Neuerstellung aller gecachten Badges, ohne dass Dateien manuell gelöscht werden müssen.

**Response-Header:**
```
Content-Type: image/png
Cache-Control: no-cache
ETag: "<hash>"
```

**BBCode für board.friesenflieger.de:**
```
[img]https://friesenspy.devprops.de/api/transport/event/{event_id}/badge/{cid}.png[/img]
```

Im Events-Tab erscheint nach der Bilanz je Teilnehmer **🎖 Badge** (öffnet das PNG) und
**📋 Forum** (kopiert den BBCode) über dem Flug-Feed.

> **Admin-Vorschau:** `GET /api/admin/transport/events/{event_id}/badge/{cid}.png` (siehe
> [Admin — Kutter-Badge-Vorschau](#get-apiadmintransporteventsevent_idbadgecidpng)) funktioniert
> auch **vor** der Bilanz — der öffentliche Endpoint hier liefert vorher weiter `404`.

---

## GET /widget

Einbettbares HTML-Widget für friesenflieger.de. Zeigt online-Piloten mit Callsigns, eingereichte Prefile-Flugpläne (FRS*), 7-Tage-Flugstunden und — wenn `TS_NOTIFY_ENABLED=true` — einen TeamSpeak-Zähler-Badge `🎧 N im TS`. Klickbar → öffnet friesenspy.devprops.de.

**Hintergrund transparent** (seit v9.2.4): Das Widget bringt keine eigene Flächenfarbe mit,
sondern übernimmt die der einbettenden Seite — damit passt es ohne Anpassung auf die Homepage
(`#d0e0f0`) wie in beliebige Forum-Kästen. Zuvor war `#d0e0f0` fest verdrahtet und saß in
andersfarbigen Containern als sichtbarer Fleck.

Die beiden Zähler stehen gemeinsam in **einer** Box rechts neben der Pilotenliste, in FF-Navy
`#191D53`; als Blöcke untereinander sind die Labels automatisch gleich breit. Farben aus der
FriesenFlieger-Palette (`Hex codes.txt` aus dem Repaint Kit, dieselbe Quelle wie `app/badge.py`) —
ein Grün gibt es in der Marke nicht.

**Query-Parameter**

| Parameter | Wirkung |
|-----------|---------|
| `dark=1` | Helle Schrift (FF-Hellblau `#8FBFF1`) für **dunkle** Einbettungen; die Zähler-Box erhält einen hellblauen Rand, damit sie auf dunklem Grund nicht verschwimmt. Akzeptiert `1`/`true`/`yes`/`on`. |

Ohne den Parameter rendert das Widget in dunkler Schrift (Navy `#053080`) für helle Hintergründe.
Der Parameter ist nötig, weil der Hintergrund transparent ist: Das iframe kann von außen nicht
erkennen, ob die einbettende Seite gerade hell oder dunkel läuft (z. B. der Dark-Mode-Schalter des
Forums) — die einbettende Seite muss es beim Setzen der `src` mitgeben.

```html
<iframe src="https://friesenspy.devprops.de/widget" width="300" height="90"
  style="border:none;" scrolling="no"></iframe>
```

**Maße:** Ab **300 px** Breite bleiben Titel, Pilotenliste und Fußzeile einzeilig; darunter
brechen sie um (bei 220 px wächst das Widget auf 127 px Höhe). Höhe je nach Inhalt: 56 px
(niemand online), ~70 px (mit einem Flugplan), ~83 px (mehrere Piloten + Flugpläne).

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

Bei aktivem Board-Login setzt der Server zusätzlich `owner_cid` = CID des eingeloggten Nutzers (aus dem `fs_user`-Cookie, **nie** aus dem Body) — nötig für die Subjekt-Allowlist („Nur bestimmte").

**Response** `{"status": "ok"}`

---

## POST /api/push/claim

Ordnet ein bereits bestehendes Push-Abo dem eingeloggten Nutzer zu (Owner-Backfill, last-login-wins). Für Abos, die vor dem Login-Rollout angelegt wurden. Nur bei aktivem Board-Login und eingeloggtem Nutzer wirksam; anonym → No-op.

**Body (JSON)** `{ "endpoint": string }`
**Response** `{"status": "ok"}` bzw. `{"status": "skipped"}`

---

## GET /api/me/visibility

Subjekt-Sichtbarkeit des eingeloggten Nutzers + Picker-Kandidaten. Nur eingeloggt (sonst `401`; das Login-Gate schützt `/api/me/*` nicht — die Cookie-Prüfung erfolgt im Endpoint).

**Response** `{ "mode": "everyone"|"allowlist"|"nobody", "allowlist": int[], "services": string[], "pilots": [{"cid": int, "callsign": string}] }` — `services` ⊆ `["online","prefile","ts"]`: für welche Aktivitäten die Einschränkung gilt (Default alle).

## POST /api/me/visibility

Sichtbarkeit setzen („Wer darf über mich benachrichtigt werden?"). Nur eingeloggt.

**Body (JSON)** `{ "mode": "everyone"|"allowlist"|"nobody", "allowlist"?: int[], "services"?: string[] }` — `allowlist` nur bei `mode="allowlist"` (leere Liste erlaubt = niemand; auf 500 Einträge gekappt). `services` (nur bei restriktivem Modus) wählt, für welche Aktivitäten (`online`/`prefile`/`ts`) die Einschränkung gilt — nicht genannte Services bleiben bei „alle". Fehlt `services`, gilt die Einschränkung für alle drei. Ungültiger `mode` → `400`. Wirkt auf Online-, Flugplan-, TeamSpeak-Push und den Telegram-Online-Kanal (dort nur `everyone`/Service ausgenommen → Alert).

**Response** `{"status": "ok", "mode": ...}`

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

## Board-Login (Forum-SSO)

Optionaler Login über das phpBB-Forum, an-/abschaltbar per Admin-Schalter (`forum_login_enabled`, Default AUS). Nur aktiv, wenn zusätzlich `SSO_SECRET`, `FORUM_SSO_URL` und `FORUM_SSO_CALLBACK` gesetzt sind. Ist der Board-Login aktiv, verlangt eine Gate-Middleware für die gesamte App (außer Login-Flow, Rechtstexten, PWA-Assets, `/api/me` und `/api/admin/*`) eine gültige Session (`fs_user`) oder ein Break-glass-Admin-Cookie.

### GET /auth/forum/login

Startet den Login: erzeugt ein `state`, setzt `fs_sso_state` (httponly) und leitet zur Forum-Bridge `FORUM_SSO_URL` weiter. Bei inaktivem Board-Login → `302` nach `/`.

### GET /auth/forum/callback

Nimmt das signierte Token der Bridge entgegen (`?token=…&state=…`). Prüft `state` gegen das Cookie, verifiziert die HMAC-Signatur (`SSO_SECRET`), Frische (≤ 60 s) und Einmal-`nonce`, legt die eigene Session `fs_user` an und leitet nach `/`. Fehlerfälle: `400` (state), `401` (Token/Nonce).

### GET /auth/forum/logout

Meldet **nur** FriesenSpy ab (löscht `fs_user`); die Forum-Session bleibt. `302` nach `/`.

### GET /api/me

Login-Status fürs Frontend: `{ "logged_in": bool, "name": str, "cid": str, "is_admin": bool }` aus dem `fs_user`-Cookie (kein Cookie → `{ "logged_in": false }`). Nicht durch das Gate blockiert.

### GET/POST /api/admin/forum-login

Board-Login-Status lesen bzw. schalten (require_admin). `GET` → `{ "enabled": bool, "configured": bool }`; `POST` Body `{ "enabled": bool }` → setzt `forum_login_enabled`.

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
    "radius_km": null,
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

`source` ∈ `calendar` | `manual`. `started_at` = Zeitstempel des Renn-Starts (erster Pilot mit Blockzeit an einem Streckenflugplatz); `null` = noch nicht gestartet. `push_enabled` = 1 (an) | 0 (aus). `radius_km` ist ein **Legacy-Feld** (seit GPS-only Phase 2/#23 wirkungslos, i. d. R. `null`) — die Platz-Zuordnung nutzt seit der Aktivierung überall den festen globalen 4-km-Radius aus dem GPS-Leg-Detektor; ein per-Rennen-Radius lässt sich über die Admin-Endpoints nicht mehr setzen.

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

**Kein `radius_km` mehr** (seit GPS-only Phase 2, #23) — die Anwesenheitsprüfung nutzt überall
den festen globalen 4-km-Radius aus dem GPS-Leg-Detektor, kein per-Rennen-Override mehr.

**Response** `{"id": 42}`

---

### POST /api/admin/bummel/races/{id}

Felder eines bestehenden Rennens aktualisieren. Nur angegebene Felder werden geändert.

**Body (JSON)** — `name`/`route`/`dtstart`/`dtend`, alle optional (kein `radius_km` mehr, s. o.).

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

> **Kalender-Fracht:** Ein Termin mit dem `friesenkutter`-Marker kann direkt in der Beschreibung eine Fracht-Zeile enthalten: `Fracht: 1000 Krabbenbrötchen, 500 Friesentee`. Beim Sync wird sie **einmalig** (nur beim erstmaligen Anlegen) gegen den Frachtart-Katalog abgeglichen und ins Manifest übernommen; ein später im Admin gepflegtes Manifest bleibt bei erneutem Sync unverändert. **Fracht je Startplatz (v8.13.0/#15 Sub-Projekt B; Multi-Platz v8.14.0/#84):** eine optionale Startplatz-**Liste** direkt am Marker bindet die Fracht — `Fracht EDDW, EDWG: 500 Äpfel` und `Fracht EDWG: 300 Birnen` (je eigene Zeile, mehrere Marker werden alle gelesen). `Fracht:` ohne ICAO bleibt geteilt. Seit v8.14.0 tragen die Marker-Startplätze zur (abgeleiteten) Route bei; ein **ferner/unauflösbarer** Marker-ICAO wird per Distanzprüfung verworfen (degradiert nur seine Zeile auf „geteilt", kippt das Event nicht).

### GET /api/admin/transport/events
Liste aller Events inkl. Fracht-Manifest (`cargo: [{id, position, name, target_kg, emoji, per_flight_max_kg, departure}]`; `departure` = gebundener Startplatz-ICAO oder `null` = geteilt), `radius_km` (Legacy-Feld — s. o., seit GPS-only Phase 2/#23 nicht mehr über die Admin-Endpoints setzbar, wirkt nicht mehr auf die Platz-Zuordnung) und `status` (`scheduled` \| `running` \| `waiting` \| `done` — analog `_race_status` beim Bummel, siehe `_transport_status`; nur in der Admin-Sicht, kein Piloten-Frontend-Feld).

### POST /api/admin/transport/events
Manuelles Event anlegen. **Seit v8.14.0/#84 kein `route`-Feld mehr** — die Route wird aus den Startplätzen der Fracht + Ziel abgeleitet. Body: `name`, `destination` (ICAO, **Pflicht**), `dtstart` (UTC, Pflicht), `dtend` (optional, sonst Mitternacht UTC), `cargo` (`[{name, target_kg, departure}]`, **Pflicht** — mind. eine Frachtart mit Menge und einer Startplatz-Liste `departure` ≠ Ziel; sonst `400`). → `{status, id}`. **Kein `radius_km` mehr** (fester globaler 4-km-Radius seit GPS-only Phase 2/#23).

### POST /api/admin/transport/events/{id}
Bearbeiten. Übergebene Felder aus `name/destination/dtstart/dtend` werden aktualisiert; `cargo` (falls gesetzt) **ersetzt** das Manifest und muss dieselbe Validierung erfüllen wie beim Anlegen (Ziel + Startplätze, sonst `400`). Die `route` wird danach frisch aus dem Manifest abgeleitet — **kein `route`-Feld mehr** (v8.14.0/#84).

### DELETE /api/admin/transport/events/{id}
Event samt Manifest löschen.

### POST /api/admin/transport/events/{id}/push

Push-Benachrichtigungen (Start, Ziel erreicht, Feierabend-Zusammenfassung, ~1h-Erinnerung) für dieses Event an- oder abschalten. Spiegelt `POST /api/admin/bummel/races/{id}/push`.

**Body (JSON)**

```json
{"enabled": true}
```

**Response** `{"status": "ok"}`

### GET /api/admin/transport/payloads
Zuladungs-Tabelle + globaler Fallback + beobachtete, noch nicht gepflegte Flugzeugtypen. Response: `payloads` (`[{type_code, mtow_kg, empty_kg, fuel_kg, fuel_full_kg, crew_kg, payload_kg, source, make_model}]`; `fuel_full_kg` = max. Tankinhalt, `fuel_kg` = halber Tank fürs Rechnen), `unmapped_types`, `default_kg`, `llm_configured`.

### POST /api/admin/transport/payloads
Zuladung eines Typs setzen. Body: `type_code` (Pflicht), `mtow_kg`, `empty_kg`, `fuel_kg` (Tankinhalt fürs Rechnen = halber Tank), `fuel_full_kg` (max. Tankinhalt, volle Tanks — im Admin ändert das Max-Feld automatisch `fuel_kg` auf die Hälfte), `crew_kg` (Pilot/Crew, Default 85 — zählt nicht als Fracht), optional direktes `payload_kg` (überschreibt die Ableitung `max(0, mtow−empty−fuel−crew)`), `make_model` (editierbar).

### GET /api/admin/transport/payloads/suggest?type=C172
KI-Vorschlag (Claude Haiku 4.5 mit **Web-Search**, Structured Output; seit v7.4.2) für die Komponenten eines Typs — recherchiert dokumentierte Handbuch-/POH-Werte (keine Schätzungen): `{make_model, mtow_kg, empty_kg, fuel_kg, fuel_full_kg, crew_kg, payload_kg}` (Zuladung = MTOW − Leer − halbe Tankfüllung − Crew; `fuel_kg` = halbe Füllung als Default, `fuel_full_kg` = Maximum, volle Tanks). Dauer ~15–30 s (Basis-Web-Search `web_search_20250305`, gestreamt, `max_retries=0` — das neuere Dynamic-Filtering-Tool drehte bei obskuren Typen minutenlang in code_execution-Runden, s. v7.4.1). `400`, wenn `ANTHROPIC_API_KEY` fehlt. **Seit v8.17.0** sind die ~108 gängigen GA-/Privat-/Hubschraubermuster (inkl. Transall C-160, A400M) aus einem kuratierten Repo-Datensatz (`app/data/aircraft_specs.json`) beim Start vorbefüllt (`source='curated'`), sodass dieser Suggest-Call nur noch als Fallback für seltene, unbekannte Muster feuert.

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

### POST /api/admin/transport/events/{event_id}/regenerate-quips
Löscht alle gecachten KI-Flug-Sprüche des Events und setzt den Tagesend-Spruch (`summary_quip`) zurück (`clear_transport_quips`). Der Poller baut sie beim nächsten Durchlauf (~60 s) neu — mit der aktuellen Spruch-Logik. Für den Fall, dass ein bereits generierter Spruch veraltet ist (z. B. Liefer-Text für einen inzwischen als geklaut/versunken erkannten Flug). Antwort: `{status, cleared}` (Anzahl gelöschter Flug-Sprüche).

> **Auch für abgeschlossene Events (v8.10.1, #69):** Bei einem bereits abgeschlossenen Event (`summarized_at` gesetzt) zieht der Poller sowohl die Pro-Flug-Sprüche als auch den fehlenden Tagesend-Spruch (`summary_quip`) aus dem eingefrorenen Snapshot nach — ohne den Fortschritt neu zu berechnen. Der `summary_quip` wird nur bei echter Aktivität (`flight_count > 0`) erzeugt (kein bezahlter LLM-Call für ein leeres Event). Der reguläre Feierabend-Latch erzeugt den Abschlussspruch nur einmal beim Übergang; dieser Nachzieh-Pfad ist nach „Sprüche neu" der einzige Weg zurück.

> **Event-Ausgabe (Phase 2):** `GET /api/transport/event/{id}` liefert zusätzlich je Frachtart `cargo[].emoji`, je Flug `cargo_lines` (`[{name, emoji, kg}]`, Co-Load) und `quip` (gecachter KI-Spruch, sonst `null`) sowie `summary_quip` (lustige Tagesend-Zusammenfassung).

### GET /api/admin/transport/events/{event_id}/badge/{cid}.png

Kutter-Badge-Vorschau eines Teilnehmers für den Admin — funktioniert **auch vor** der
Feierabend-Bilanz (umgeht das `summarized_at`-Gate des öffentlichen Endpoints). Das Badge wird
bei jedem Aufruf **frisch gerendert** (kein Cache).

**Voraussetzungen — sonst `404`:**
- Das Event mit `event_id` muss existieren.
- `cid` muss Teilnehmer dieses Events sein.

**Response** — `image/png`. Gleiches Layout wie beim öffentlichen Endpoint (navy Kern „Voll
beladen!" + Verlust-Titel SPITZBOOV!/BADEMESTER!/SEEROVER!, falls Fracht verloren ging).

**Response-Header:**
```
Content-Type: image/png
Cache-Control: no-store
```

Der öffentliche Endpoint `GET /api/transport/event/{event_id}/badge/{cid}.png` bleibt vor der
Bilanz weiterhin `404`.

## Admin — Flugplätze (Ergänzungen)

Verwaltung von `custom_airports` (v8.5.0/#50, Override seit v8.6.0/#56) — Plätzen, die in der
Standard-Flugplatzdatenbank (`airportsdata`) fehlen (z. B. Segelfluggelände ohne offizielle
ICAO-Kennung) ODER deren `airportsdata`-Koordinaten nachweislich falsch sind (Fund: EBUL/Ursel
Air Base ~15 km daneben). Ein hier eingetragener Code **überschreibt** `airportsdata` (geprüft
zuerst). Alle Endpoints erfordern das Admin-Cookie (`require_admin`).

### GET /api/admin/airports

Liste aller Ergänzungs-Flugplätze.

**Response**

```json
{
  "airports": [
    {"icao": "ZZSALZ", "name": "Segelfluggelände Salzwedel/Klein Gartz", "lat": 52.828, "lon": 11.316, "elevation_ft": 112.0, "radius_km": null, "updated_at": "2026-07-05T12:00:00Z"}
  ]
}
```

### POST /api/admin/airports

Flugplatz anlegen/aktualisieren (Upsert nach `icao`).

**Body (JSON)**

```json
{"icao": "zzsalz", "name": "Segelfluggelände Salzwedel/Klein Gartz", "lat": 52.828, "lon": 11.316, "elevation_ft": 112, "radius_km": null}
```

- `icao` (Pflicht) — beliebiger Code, wird `.strip().upper()` gespeichert; **kein** echter 4-Buchstaben-ICAO nötig (Platzhalter wie `ZZSALZ` erlaubt).
- `lat`/`lon` (Zahl) — Pflicht, **außer** der Code hat bereits bekannte Koordinaten (v8.7.0/#62): ein bestehender Custom-Eintrag ODER `airportsdata`. In dem Fall dürfen beide leer bleiben/`null` sein — die bekannten Koordinaten werden automatisch übernommen (praktisch für einen reinen Radius-Override, s. `radius_km`, ohne Koordinaten eintippen zu müssen, die man selbst nicht genau kennt). Ist der Code nirgends bekannt und lat/lon fehlen, `400`.
- `elevation_ft` (optional) — `null`/leer lassen, um die bereits bekannte Elevation zu übernehmen (Custom-Eintrag oder `airportsdata`, analog lat/lon) bzw. `null` zu speichern, falls auch dort unbekannt. **Wirkt sich auf die GPS-Erkennung aus:** unbekannte Elevation macht den Spawn-Startplatz-Guard (#49) permissiv, die Landungs-Rettung am Track-Ende (#53) dagegen konservativ (keine Rettung ohne Höhenangabe).
- `radius_km` (optional, Zahl > 0, v8.7.0/#62) — überschreibt NUR den Suchradius für diesen Code (unabhängig von lat/lon), sonst `400`. `null`/leer lassen = Standardradius der aufrufenden Funktion (i. d. R. 4 km). Für Großflughäfen, deren tatsächlicher Abhebe-/Aufsetzpunkt weiter vom Referenzpunkt entfernt liegen kann als der Standardradius (Fund: EHAM/Schiphol — Abhebepunkt nach langem Rollweg 6,6 km entfernt, die Koordinate selbst aber korrekt).
- `override` (optional, `bool`, v8.6.0/#56) — `true` erlaubt das bewusste Überschreiben eines bereits in `airportsdata` bekannten Codes.

**Plausiprüfung:** Ist `icao` bereits in `airportsdata` bekannt UND `override` nicht gesetzt, wird der Request mit **`409`** abgelehnt („Bestätigung nötig" — die Response nennt die dort hinterlegten Koordinaten), **auch wenn lat/lon leer sind** (die 409-Prüfung läuft vor der Koordinaten-Autofüllung). Mit `override: true` wird trotzdem gespeichert und überschreibt den Standard-Wert (Fund dieser Session: `EBUL`/Ursel Air Base führte in `airportsdata` Koordinaten, die ~15 km neben der echten Position lagen). Fund der Vorgänger-Session: `EDXU` (Hüttenbusch) war fälschlich als „fehlend" vermutet worden, steckte aber schon (korrekt) in `airportsdata` — dieser Fall bleibt ohne `override` weiterhin abgelehnt.

**Nebenwirkung:** Ein erfolgreicher Write ruft sofort `geo.set_custom_airports(...)` (Cache-Invalidierung, ohne Neustart wirksam) **und** `rebuild_flight_cache(conn, full=True)` auf — der neue/geänderte Platz muss auch ältere, bislang fälschlich offene oder platzlose Flüge neu erkennen lassen; der reguläre inkrementelle Refresh (7 Tage) würde das nicht leisten.

**Response** `{"status": "ok"}`

### DELETE /api/admin/airports/{icao}

Flugplatz löschen. Gleiche Nebenwirkung (Cache-Invalidierung + voller `rebuild_flight_cache`) wie beim Anlegen/Ändern.

**Response** `{"status": "ok"}`

### GET /api/airports/check (v8.15.0/#77)

Prüft eine kommagetrennte ICAO-Liste (`?codes=EDWG,EDXH,…`) gegen die bekannten Plätze
(`airportsdata` + eigene `custom_airports`) und gibt die **unbekannten** zurück. Offline, kein
Auth. Genutzt von den Admin-Editoren (Kutter + Bummel), um beim Speichern vor Tippfehler-ICAOs zu
warnen (weiche Warnung, kein Hard-Block).

**Response** `{"unknown": ["EDZZ", …]}`

### GET /api/airports/search (v8.16.0/#77)

ICAO-**Präfix-Suche** (`?q=EDW`) über `airportsdata` + eigene `custom_airports`, bis zu 20 Treffer
mit Flugplatznamen. Offline, kein Auth. Speist das Autocomplete an den Platz-Eingaben (Kutter-Ziel
+ -Startplätze, Bummel-Strecke); bei Mehrfach-ICAO-Feldern wird das gerade getippte Token
vervollständigt.

**Response** `{"results": [{"icao": "EDWG", "name": "Wangerooge Airport"}, …]}`

## Admin — Erkennungslücken

Prüfliste (v8.6.0) für Flüge, deren GPS-Start oder -Landung trotz bekanntem Flugplan fehlt —
meist ein Hinweis auf einen fehlenden `custom_airports`-Eintrag. Berechnet **live** über
`canonicalize_legs` (kein eigener Cache): ein neu ergänzter Flugplatz lässt den betroffenen
Flug beim nächsten Laden automatisch verschwinden. Alle Endpoints erfordern das Admin-Cookie
(`require_admin`).

### GET /api/admin/detection-gaps

**Response**

```json
{
  "gaps": [
    {
      "cid": 1382870, "logon_time": "2025-07-18T18:40:38+00:00",
      "pilot_name": "Max Muster", "callsign": "FRS96", "aircraft": "C172",
      "plan_departure": "EDST", "plan_arrival": "EDST",
      "gps_departure": null, "gps_arrival": null,
      "missing": "both", "source": "statsim", "id": null, "statsim_id": 23617949,
      "duration_min": 24
    }
  ]
}
```

`missing` ∈ `departure` \| `arrival` \| `both`. Ein offener Flug (kein `connection_closed`) zählt
nie als Landungs-Lücke — er ist schlicht noch nicht gelandet, kein Datenfehler. Neueste zuerst,
auf 200 Zeilen gekappt.

### POST /api/admin/detection-gaps/dismiss

Markiert einen einzelnen Flug dauerhaft als „kein Datenfehler" (Absturz, abgerissene
Aufzeichnung) — verschwindet aus der Prüfliste, unabhängig vom betroffenen Flugplatz-Code.

**Body (JSON)** `{"cid": 1382870, "logon_time": "2025-07-18T18:40:38+00:00"}`

Beide Felder Pflicht (`cid` + `logon_time` als Schlüssel, identisch zum `flight_cache`-Vertrag
`UNIQUE(cid, logon_time)`), sonst `400`.

**Response** `{"status": "ok"}`

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

## Admin — GPS-Leg-Audit (Diagnose-Werkzeug, seit v7.9.0)

### GET /api/admin/gps-leg-audit

Rein lesendes Diagnose-Audit für die GPS-basierte Etappen-Erkennung (#23). Ursprünglich (v7.9.0
– v7.9.5) das Vorab-Audit vor der Aktivierung; seit v8.0.0 ist `canonicalize_legs` die **produktive**
Wahrheit (Statistik/Bummel/Kutter/Piloten-Detail) — der Endpoint bleibt als **Diagnose-Werkzeug**
erhalten, um die alte, refile-/disconnect-basierte Zählung (`canonicalize_flights`) weiterhin gegen
die aktive GPS-Sicht zu vergleichen (z. B. zur Fehlersuche bei einem einzelnen Piloten/Zeitraum).
**Ändert keine Wertung** — beide Sichten werden für das im Fenster liegende Piloten-Set **on-demand**
berechnet (nichts wird gespeichert, kein Bezug zu `flight_cache`). Kein Poll-Impact.

**Query-Parameter**

- `days` (int, Default `30`, 1..365) — Fenster `[jetzt − days, jetzt]` (nach `logon_time`/`takeoff_ts`).
- `cid` (int, optional) — nur diesen Piloten prüfen.
- `statsim` (int, Default `0`, 0..500) — > 0 hängt eine `statsim`-Sektion an: die GPS-Leg-Interpretation
  der jüngsten N StatSim-Flüge im Fenster, **on-demand aus `statsim_position_history` gerechnet
  (in-memory, nichts gespeichert)**. Zeigt, wie StatSim-Flüge unter GPS-only aussähen (Schatten-Vorschau
  auf Phase-2-Task 5b). Pro Flug: `classification` ∈ `match`/`divergent`/`zwischenlandung`/`incomplete`/`none`
  plus `legs`; dazu `sampled`/`total` und eine `summary`-Zählung je Klasse.

**Response**

```json
{
  "window": {"start": "…Z", "end": "…Z"},
  "summary": {
    "flights": 42,            // FriesenSpy-Connections im Fenster (StatSim ausgenommen)
    "statsim_flights": 3,
    "gps_legs": 47,           // erkannte GPS-Etappen im Fenster
    "matches": 40,            // Connections mit ≥ 1 überlappenden Etappe
    "missing_gps_legs": 2,    // Connections ohne Etappe (Track fehlt / Detektor-Miss)
    "extra_gps_legs": 5,      // Zwischenlandungen ohne Refile (Σ max(0, n−1) je Connection)
    "arr_divergence": 1,      // Ziel-ICAO der letzten Etappe ≠ Flugplan-Arrival
    "incomplete_rate": 0.0426,   // Anteil Etappen mit complete=0 (Disconnect mid-air)
    "airborne_spawn_rate": 0.0213 // Anteil Etappen ohne dep_icao (Spawn in der Luft)
  },
  "flights": [
    {
      "cid": 1000001, "callsign": "FRS01",
      "logon_time": "…Z", "logoff_time": "…Z",
      "dep": "EDWF", "arr": "EDWG",
      "n_legs": 2, "arr_match": true,
      "legs": [
        {"dep_icao": "EDWF", "arr_icao": "EDWI", "takeoff_ts": "…Z", "landing_ts": "…Z", "complete": true},
        {"dep_icao": "EDWI", "arr_icao": "EDWG", "takeoff_ts": "…Z", "landing_ts": "…Z", "complete": true}
      ]
    }
  ]
}
```

`401` ohne gültiges Admin-Cookie.

### POST /api/admin/statsim-backfill

Holt die GPS-Tracks importierter StatSim-Flüge **gebündelt** von der StatSim-API und cached sie in
`statsim_position_history` — damit die GPS-Etappen-Erkennung (jetzt produktiv, #23) auch
StatSim-Flüge aus GPS auswerten kann, statt auf den Flugplan-Fallback zurückzufallen. Für den
laufenden Betrieb übernimmt seit v8.0.0 zusätzlich ein periodischer Poller-Job
(`statsim_track_fetch`, alle 10 min, kleine Batches à 20 Flüge) das proaktive Nachladen neuer
StatSim-Importe automatisch (Phase 2b) — dieser Admin-Endpoint bleibt für einen gezielten
Voll-Backfill (z. B. nach einem größeren StatSim-Sync) nützlich. Rein additiv, keine Wertung.
Braucht `STATSIM_API_KEY`.

Seit v8.3.0 filtert der Backfill (Admin-Endpoint UND periodischer Job) **nicht mehr** nach
`CALLSIGN_PREFIX` — Flüge mit fremdem Callsign eines bekannten Piloten (z. B. bei einer anderen
virtuellen Airline) bekommen ihren Track jetzt genauso nachgeladen. Der Präfix entscheidet nur
über die Wertung (Statistik/Bummel/Kutter), nicht darüber, ob GPS-Split-Logik greift.

**Query-Parameter**

- `limit` (int, Default `40`, 1..150) — max. Flüge pro Aufruf (jüngste ohne lokalen Track zuerst).

**Verhalten:** je Flug ein API-Abruf, gedrosselt (0,3 s). **Resumebar** — wiederholt aufrufen, bis
`remaining` = 0. Response: `{ had_key, requested, fetched, empty, points, remaining }`. `401` ohne Admin.

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
