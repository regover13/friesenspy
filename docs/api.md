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

Gruppierung: ≤93 Tage → täglich (`%Y-%m-%d`), >93 Tage → monatlich (`%Y-%m`). Alle Perioden werden zurückgegeben (Lücken mit 0 aufgefüllt). Nur FRS*-Callsigns.

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

Letzter Flug und Fluganzahl pro Pilot, absteigend nach Datum. Kombiniert FriesenSpy-Aufzeichnungen und gecachte StatSim-Daten.

**Query-Parameter**

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `days` | int | `30` | Zeitraum in Tagen (30, 90, 365) |

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

Event-Suche: Wer von den Friesen war in einem bestimmten Zeitraum in der Nähe eines Flughafens?

**Query-Parameter**

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `icao` | string | — | **Pflicht.** Kommagetrennte ICAO-Codes, z.B. `EDDK,EDDL` |
| `radius` | float | `150.0` | Suchradius in km |
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

`flights` enthält die Positionen des Piloten im Zeitfenster aufgeteilt in einzelne Flüge. Die Segmentierung basiert primär auf echten VATSIM-Session-Records aus der `flights`-Tabelle (Callsign, DEP/ARR, Flugzeugtyp aus dem Flugplan). `callsign`, `departure`, `arrival` und `aircraft` sind `null` wenn kein passender `flights`-Eintrag existiert — in diesem Fall wird als Fallback nach Zeitlücken von mehr als 30 Minuten segmentiert (z.B. für Positionen aus Zeiten vor FriesenSpy-Start). `positions` enthält alle aufgezeichneten Positionen des jeweiligen Fluges — nicht nur die im Radius.

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
