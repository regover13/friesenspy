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
    "aircraft": "C172",
    "departure": "EDKB",
    "arrival": "EDDK",
    "latitude": 50.767,
    "longitude": 7.162,
    "altitude": 3500,
    "groundspeed": 110,
    "heading": 317,
    "logon_time": "2026-06-04T07:14:54Z",
    "updated_at": "2026-06-04T07:28:41Z"
  }
]
```

---

## GET /api/stats

Flugstunden und Fluganzahl pro Pilot, absteigend sortiert.

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
    "flights": 12,
    "total_hours": 14.5
  }
]
```

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
      "positions": [
        {
          "callsign": "FRS49",
          "latitude": 50.865,
          "longitude": 7.142,
          "altitude": 2800,
          "groundspeed": 95,
          "heading": 270,
          "ts": "2024-01-01T11:23:00Z"
        }
      ]
    }
  ]
}
```

Nur Piloten die mindestens eine Position innerhalb von `radius` km um einen der ICAOs hatten werden zurückgegeben. `positions` enthält **alle** aufgezeichneten Positionen des Piloten im Zeitfenster — nicht nur die die im Radius waren.

---

## GET /api/sse

Server-Sent Events Stream. Verbindung bleibt offen; bei jedem VATSIM-Poll-Zyklus (~15s) wird ein Event gesendet.

**Voraussetzung:** `Accept: text/event-stream` (automatisch bei `EventSource`)

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
