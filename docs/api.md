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

Gruppierung: ≤93 Tage → täglich (`%Y-%m-%d`), >93 Tage → monatlich (`%Y-%m`). Alle Perioden werden zurückgegeben (Lücken mit 0 aufgefüllt). Nur FRS*-Callsigns. Ghost-Flüge (`duration_min ≤ 5`) werden ausgeschlossen. StatSim-Einträge, die bereits in FriesenSpy vorhanden sind (gleiche CID + Minute), werden nicht doppelt gezählt.

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

`flight_count` = `fs_count` + `st_count`. StatSim-Daten sind nur vorhanden wenn der Pilot zuvor im Statistiken-Tab angeklickt wurde (lazy cache).

---

## GET /api/pilots/{cid}/flights

Alle Flüge eines Piloten — kombiniert FriesenSpy-eigene Aufzeichnungen und StatSim-Historik. Antwortet **sofort** mit gecachten Daten; StatSim-Update läuft im Hintergrund (letzter 31-Tage-Chunk). Response-Header `X-StatSim-Status: fresh | updating | no-key`.

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
    "duration_min": 51
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

Ein Prefile ist ein eingereicher Flugplan ohne aktive VATSIM-Verbindung — der Pilot hat den Plan aufgegeben, ist aber noch nicht online.

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
    "location": "EDVK"
  }
]
```

`location` enthält den ersten 4-buchstabigen ICAO-Code aus dem Kalender-Feld „Ort", sonst aus dem Event-Titel (leer wenn nicht erkannt). Bei Events ohne ICAO wird `global` ins Suchfeld vorgefüllt. Zeiten sind immer UTC.

---

## GET /widget

Einbettbares HTML-Widget für friesenflieger.de. Zeigt online-Piloten mit Callsigns, eingereichte Prefile-Flugpläne (FRS*) und 7-Tage-Flugstunden. Design im hellen Stil von friesenflieger.de (bg `#d0e0f0`, Navy `#053080`, Vereinsrot `#D31141`). Klickbar → öffnet friesenspy.devprops.de.

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
| `pilot_filter` | int[] \| null | — | CID-Liste der zu benachrichtigenden Piloten; `null` = alle |
| `notify_prefiles` | bool | — | Auch bei eingereichten oder geänderten Flugplänen benachrichtigen — feuert bei neuem Prefile oder Änderung von Abflugzeit, Abflug- oder Zielflughafen; wird unterdrückt wenn der Pilot bereits online ist (default: true) |

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
