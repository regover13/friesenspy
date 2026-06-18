# Einheitlicher Empfänger-Filter (Online + Flugplan + TS) — Design

Datum: 2026-06-18 · Status: zur Umsetzung freigegeben · Scope: klein (Wiederverwendung des bestehenden `pilot_filter`)

## Context

FriesenSpy hat heute **drei** Push-Benachrichtigungstypen mit unterschiedlicher Empfänger-Filterung:

- **Online** (`send_web_push_notifications`) und **Flugplan** (`send_prefile_push_notifications`): gefiltert über `pilot_filter` (CID-Liste je Subscription; `NULL` = alle). Quelle der Auswahl im UI: „Alle Friesen" / „Nur bestimmte Piloten" (Piloten aus `/api/stats`, Checkbox `data-cid`).
- **TeamSpeak** (`_poll_teamspeak` → `recipients_for`): eigener Mechanismus über `notify_ts` (Opt-in), `ts_self_frs` (Kein-Selbst-Ping) und die Subjekt-Tabelle `ts_consent` (`everyone`/`nobody`/`allowlist`).

Der User will **eine** Auswahl für alle drei Typen und Selbst-Ausschluss überall — ohne extra Felder. Schlüssel-Erkenntnis: Die bestehende „Nur bestimmte Piloten"-Liste zeigt beim Umschalten **alle angehakt**; man entfernt einfach Haken (sich selbst oder andere). Das ist bereits ein Ausschluss-Mechanismus. Zweite Erkenntnis: Das VATSIM-Callsign eines Friesen **ist** seine FRS-Nummer (z. B. `FRS49`) — das verbindet die CID-Welt (Online/Flugplan) mit der FRS-Welt (TS).

## Entscheidungen (mit User bestätigt)

- **Kein** neues Filter-Modell, **kein** dritter Modus, **keine** neue Tabelle, **keine** Migration. Der bestehende `pilot_filter` (Alle / Nur bestimmte) bleibt unverändert und wird **zusätzlich für TS** herangezogen.
- **Selbst-Ausschluss** für alle drei Typen = in „Nur bestimmte" den eigenen Haken entfernen. Es braucht dafür kein eigenes Identitätsfeld.
- Das **„Eigene FRS-Nr."-Feld** (`ts_self_frs`) wird **entfernt** (UI + Logik). Der Kein-Selbst-Ping läuft künftig über das Abwählen in der Liste.
- **`ts_consent`** wird auf **`everyone` / `nobody`** reduziert (der `allowlist`-Modus zielte über `ts_self_frs` der Empfänger und wird mit dessen Wegfall funktionslos). `ts_consent` bleibt als Subjekt-Privacy („darf über mich auf TS benachrichtigt werden") erhalten.
- **Reine TS-Leute** (FRS-Mitglieder ohne VATSIM-Flug) werden bewusst **nicht** einzeln wählbar (kein `ts_seen_frs`). Konsequenz siehe Verhaltenstabelle.
- Der **`notify_ts`-Opt-in** (Checkbox „🎧 Bei TeamSpeak-Beitritt benachrichtigen") bleibt unverändert — er steuert, ob ein Gerät überhaupt TS-Pings will.

## Architektur

### FRS→CID-Mapping (neu, `app/database.py`)

`cid_for_callsign(conn, callsign) -> int | None` — ermittelt die CID zu einem FRS-/Callsign-String. Quelle in dieser Reihenfolge: `live_positions.callsign` (aktuell online), sonst jüngster `flights.callsign` (nach `logon_time`), sonst `statsim_cache.callsign`. Vergleich case-insensitiv/getrimmt. `None`, wenn die FRS nie auf VATSIM gesehen wurde (reine TS-Leute).

### TS-Empfängerauswahl (umgebaut)

`_poll_teamspeak` ruft pro bestätigter (Verweildauer) FRS:
1. `ts_consent` prüfen (Subjekt): `nobody` → keine Empfänger; sonst weiter.
2. `cid = cid_for_callsign(conn, frs)`.
3. Empfänger = Subscriptions mit `notify_ts = 1` **und** (`pilot_filter IS NULL` **oder** `cid` in `pilot_filter`). Bei `cid is None` (reine TS-Leute) zählt nur `pilot_filter IS NULL` (Modus „Alle").

Die `pilot_filter`-Prüfung wird mit der vorhandenen Logik aus `get_push_subscriptions_for_pilot` geteilt — neue Funktion `get_ts_push_subscriptions(conn, cid)` (ersetzt das heutige parameterlose `get_ts_push_subscriptions`): selektiert `WHERE notify_ts = 1` und filtert pro Zeile über `pilot_filter` (NULL = alle, sonst `cid in JSON`). Liefert `endpoint, p256dh, auth`.

`recipients_for` (in `app/ts_notify.py`) entfällt bzw. wird durch diese DB-gestützte Auswahl ersetzt — die `ts_self_frs`/`allowlist`-Logik wird nicht mehr gebraucht. (Datei kann gelöscht werden, falls keine andere Nutzung; sonst auf den `ts_consent`-`nobody`-Kurzcheck reduzieren.)

### Online/Flugplan

Unverändert — nutzen weiter `get_push_subscriptions_for_pilot(cid)` / `get_push_subscriptions_for_prefile(cid)`. Selbst-Ausschluss funktioniert automatisch, sobald der eigene CID nicht im `pilot_filter` steht (bisher nie genutzt, jetzt der dokumentierte Weg).

### Datenmodell

- `push_subscriptions.ts_self_frs`: wird **nicht mehr gelesen/geschrieben**. Spalte bleibt bestehen (kein Migrationszwang; tote Spalte, harmlos). Endpoint setzt sie nicht mehr.
- `ts_consent.visibility`: nur noch `everyone`/`nobody` wird ausgewertet (`allowlist` wird wie `everyone` behandelt, falls Altbestand). `manage_ts_consent.py` `choices` auf `everyone`/`nobody` reduzieren; `--allow` entfällt.

### API (`app/main.py`)

`POST /api/push/subscribe`: Body-Feld `ts_self_frs` wird nicht mehr ausgewertet (akzeptiert/ignoriert für Rückwärtskompatibilität). `notify_ts` und `pilot_filter` bleiben.

### Frontend (`app/static/index.html`)

- **Entfernen:** das „Eigene FRS-Nr."-Label + Input (`notif-ts-frs`) samt localStorage (`notif_ts_frs`) und dem `ts_self_frs`-Feld im Subscribe-POST.
- **Behalten/klären:** Die Piloten-Auswahl-Sektion bleibt; ein Hinweistext stellt klar, dass die Auswahl für **Online, Flugplan und TeamSpeak** gilt. `notify_ts`-Checkbox bleibt.

## Verhaltenstabelle

| Modus | Online / Flugplan | TeamSpeak (FRS hat geflogen → CID bekannt) | TeamSpeak (reine TS-Leute, keine CID) |
|---|---|---|---|
| **Alle** (`pilot_filter NULL`) | alle gemeldet | alle gemeldet (sofern `notify_ts=1` + `ts_consent≠nobody`) | gemeldet (sofern `notify_ts=1` + `ts_consent≠nobody`) |
| **Nur bestimmte** (Haken) | nur angehakte CIDs | nur wenn CID angehakt | **nie** (nicht in Liste, nicht abhakbar) |
| **Selbst** (eigenen Haken in „Nur bestimmte" entfernt) | kein Selbst-Ping | kein Selbst-Ping | – |

## Fehlerbehandlung

- `cid_for_callsign` gibt `None` ohne Crash; im Modus „Nur bestimmte" → kein Ping für unbekannte FRS, im Modus „Alle" → Ping.
- TS-Poll/Versand-Fehlerpfade unverändert (None=Fehler überspringen, 410-Cleanup, Verweildauer-/Debounce-Logik).

## Tests (`tests/`)

- `test_database.py`: `cid_for_callsign` (live vor flights vor statsim, case-insensitiv, unbekannt→None); `get_ts_push_subscriptions(conn, cid)` (notify_ts-Filter + pilot_filter NULL=alle vs. CID-Mitgliedschaft).
- `test_poller.py`: TS-Empfänger respektieren `pilot_filter` (CID angehakt → Push; abgewählt → kein Push; `pilot_filter NULL` → Push); reine TS-Leute (CID None) nur bei „Alle"; `ts_consent=nobody` unterdrückt; Verweildauer/Debounce/Baseline weiterhin grün.
- `test_manage_ts_consent.py`: nur noch `everyone`/`nobody`; `allowlist`/`--allow` abgelehnt bzw. entfernt.
- `test_ts_notify.py`: an die neue Auswahl angepasst oder entfernt, falls `recipients_for` wegfällt.

## Out of Scope (bewusst nicht)

- Reine TS-Leute einzeln wählbar (`ts_seen_frs`-Tabelle, zweite Listenquelle).
- Subjekt-Privacy (`ts_consent`-artig) für Online/Flugplan.
- Dritter „Alle außer"-Modus (durch „Nur bestimmte + Abhaken" abgedeckt).
- Drop der toten Spalte `ts_self_frs` (kann später per Migration).
