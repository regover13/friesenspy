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

## GET /api/stats

Letzter Flug und Fluganzahl pro Pilot, absteigend nach Datum. Nur FriesenSpy-eigene Aufzeichnungen; für historische Daten → `/api/pilots/{cid}/flights`.

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
    "flight_count": 12,
    "last_flight": "2026-06-04T07:14:54Z"
  }
]
```

---

## GET /api/pilots/{cid}/flights

Alle Flüge eines Piloten — kombiniert FriesenSpy-eigene Aufzeichnungen und StatSim-Historik (wenn `STATSIM_API_KEY` konfiguriert). StatSim wird immer mit mindestens 365 Tagen abgefragt und gecacht (24h TTL).

**Query-Parameter**

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `days` | int | `365` | Zeitraum in Tagen; `0` = alle verfügbaren Flüge seit 2020-01-22 |

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

`flights` enthält die Positionen des Piloten im Zeitfenster aufgeteilt in einzelne Flüge. Liegen zwei aufeinanderfolgende Positionen mehr als 30 Minuten auseinander, beginnt ein neuer Flug-Eintrag. `positions` enthält alle aufgezeichneten Positionen des jeweiligen Fluges — nicht nur die im Radius.

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
