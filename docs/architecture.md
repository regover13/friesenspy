# Architektur

## Überblick

```
VATSIM Data API (15s)
        │
        ▼
  VatsimPoller (APScheduler)
        │
        ├─► filter_friesen_pilots(callsign_prefix)
        │         → alle Piloten mit Callsign FRS*
        │
        ├─► Flug-State-Machine
        │         newly_online → open_flight, Telegram-Alert
        │         still_online → update position
        │         went_offline → close_flight
        │
        ├─► SQLite WAL (positions, flights, history)
        │
        └─► asyncio.Queue → SSE-Stream → Browser
```

## Module

### `app/config.py`

pydantic-settings liest `config.env` oder Umgebungsvariablen. `get_settings()` ist mit `@lru_cache` als Singleton implementiert — einmal geladen, für die Prozess-Lebensdauer gecacht.

Pflichtfelder: `SECRET_KEY`. Optional: `STATSIM_API_KEY` für historische Flugdaten, `OPENAIP_API_KEY` für OpenAIP-Overlay im Frontend, `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_CONTACT_EMAIL` für Web Push Notifications, `LOG_LEVEL` (Default `INFO`).

**Logging:** `configure_logging(LOG_LEVEL)` wird beim Lifespan-Startup aufgerufen und installiert via `logging.basicConfig(..., force=True)` einen Handler am Root-Logger. Ohne das hat der Root-Logger unter uvicorn keinen Handler, sodass Pythons Last-Resort-Handler nur `WARNING`+ ausgibt und App-`INFO`-Logs (z. B. `PrefilePush … sent OK`) verschluckt würden. Ungültiges Level → Fallback `INFO`.

### `app/auth.py`

Admin-Authentifizierung per signiertem httponly-Cookie.

- **`ADMIN_PASSWORD`** (aus `config.py`) — leer = Admin-Bereich deaktiviert; gesetzt = Cookie-Login aktiv.
- **Cookie `fs_admin`**: HMAC-SHA256-Signatur über das konfigurierte Passwort, signiert mit `SECRET_KEY` (stdlib `hmac`, kein Session-Store). Ein Passwort- oder Key-Wechsel invalidiert alle bestehenden Cookies sofort, da die Signatur nicht mehr passt.
- **`require_admin`** — FastAPI-Dependency, die das Cookie prüft und bei fehlendem oder ungültigem Cookie `401` zurückwirft. Schützt alle `/api/admin/*`-Endpoints.
- **`require_admin_page`** — dasselbe für HTML-Seiten **außerhalb** von `/api/admin` (bisher nur `/admin/push-overview`). Nötig, weil `fs_admin` auf `path=/api/admin` liegt und vom Browser für eine Seite unter `/admin/…` nie mitgesendet wird: `require_admin` würde dort jeden echten Admin aussperren. Geprüft wird stattdessen die Break-glass-Kopie `fs_admin_site` (`path=/`) bzw. eine Forum-Session mit Admin-Recht. **Für jede neue Seite außerhalb von `/api/admin` diese Variante nehmen.**
- **`POST /api/admin/login`** setzt das Cookie (httponly, SameSite=Strict); **`POST /api/admin/logout`** löscht es; **`GET /api/admin/me`** gibt `{"admin": true}` zurück wenn die Session gültig ist.
- Die Admin-Seite selbst (`/admin` → `app/static/admin.html`) ist eine eigenständige Vanilla-JS-Seite; sie nutzt denselben Login-Flow und kommuniziert ausschließlich über die `/api/admin/*`-Endpoints.

### `app/forum_sso.py` (Board-Login, optional)

Token-Primitiven für den optionalen Login über das phpBB-Forum (`board.friesenflieger.de`). Zwei HMAC-signierte Token im Format `base64url(payload).hmac_sha256_hex`, strikt getrennt über ein `typ`-Feld:

- **Eingehendes SSO-Token (`typ="sso"`)** — von der Bridge `deploy/forum/sso.php` (liegt neben phpBB, liest nur Session/Profil/Gruppe, schreibt nie ins Forum). Signiert mit dem geteilten `SSO_SECRET`, kurzlebig (`iat` ≤ 60 s), mit Einmal-`nonce`. `verify_sso_token` prüft Signatur/Typ/Frische/Nonce.
- **FriesenSpy-Session (`typ="user"`, Cookie `fs_user`)** — nach erfolgreichem Login, signiert mit `SECRET_KEY`, mit `exp`. `make_user_token`/`verify_user_token`.

Der Flow (`/auth/forum/login` → Bridge → `/auth/forum/callback`) und die **Gate-Middleware** (`forum_login_gate` in `app/main.py`, mit Allowlist + Break-glass-Cookie `fs_admin_site` auf `path=/`) leben in `app/main.py`. Aktiv nur, wenn der Admin-Schalter `forum_login_enabled` AN ist **und** die Bridge konfiguriert ist (sonst No-op, öffentlicher Normalbetrieb). Design: `docs/superpowers/specs/2026-07-13-forum-sso-design.md`.

### `app/vatsim.py`

- `fetch_vatsim_data(client)` — HTTP GET auf die VATSIM Data API, gibt geparsten JSON-Dict zurück.
- `filter_friesen_pilots(callsign_prefix, vatsim_data)` — filtert Piloten-Liste nach Callsign-Prefix (case-insensitiv).
- `pilot_to_position(pilot)` — normalisiert rohe VATSIM-Daten in ein flaches Dict mit 23 Feldern, inkl. aller `flight_plan`-Details (flight_rules, aircraft_icao, cruise_altitude, cruise_tas, route, remarks, …). **`aircraft_short`-Fallback**: VATSIM liefert `flight_plan.aircraft_short` nicht immer zuverlässig; wenn das Feld leer ist, wird es aus dem vollen `aircraft`-String (z.B. `"S22T/L-SDGRY/S"`) durch Split am ersten `"/"` abgeleitet.
- `snapshot_other_traffic(callsign_prefix, vatsim_data)` (v12.7.0) — das Gegenstück zu `filter_friesen_pilots`: alle **Nicht**-Friesen als schlanke Karten-Einträge (`cid`, `cs`, `lat`, `lon`, `alt`, `gs`, `hdg`, `ac`, `dep`, `arr`). Kurze Feldnamen, weil dieselbe Antwort über die Netzwerkverbindung des Simulators ins Kniebrett geht. Verworfen werden Einträge ohne Koordinate und der Platzhalter `0/0` („noch keine Position"). Ausgeschlossen wird allein über das Callsign-Präfix — ein per Admin-Checkbox auf „inaktiv" gesetzter Pilot fällt damit aus **beiden** Listen heraus, und das ist die Absicht der Checkbox.

### `app/statsim.py`

StatSim API-Client für historische Flugdaten.

- `fetch_pilot_flights(client, cid, api_key, days)` — paginierte Abfrage in ≤31-Tage-Chunks. Fehlerhafte Chunks werden einzeln übersprungen (kein Abbruch der Gesamtabfrage). Timeout: 30s. Silent fail → []. Normalisiert Felder: `statsim_id`, `callsign`, `departure`, `arrival`, `aircraft`, `logon_time`, `logoff_time`, `duration_min`.
- `fetch_flight_track(client, statsim_id, api_key)` — GPS-Track eines einzelnen Fluges. Silent fail → [].

StatSim API: `https://api.statsim.net`, Auth: `X-API-Key` Header, max. 31 Tage pro Query.

### `app/database.py`

SQLite mit WAL-Mode und `PRAGMA foreign_keys=ON`. Wichtigste Tabellen (Auszug):

| Tabelle | Inhalt |
|---------|--------|
| `pilots` | CID + Name; `list_pilots`/`upsert_pilot`/`delete_pilot` für die Admin-Piloten-Verwaltung (`upsert_pilot` aktualisiert den Namen via `ON CONFLICT`, `added_at` bleibt erhalten). Die Tabelle füllt sich auch automatisch aus VATSIM — die Verwaltung dient der Namenspflege, ist **keine** Mitglieder-Allowlist |
| `app_settings` | Generischer Key-Value-Store (`key` PK, `value`, `updated_at`); `get_app_setting`/`set_app_setting`. Schlüssel `banner_version`: `auto` (Default) \| `off` \| konkrete Version — steuert den Startseiten-Hinweis-Banner |
| `flights` | Pro Flug: Callsign, Typ (`aircraft_short`), DEP/ARR, Logon/Logoff, `duration_min` (Online-/Verbindungszeit), `block_min` (Bewegungszeit), `distance_nm` (GPS-Summe via Haversine), `superseded_by` (reversibler Dedup-Verweis), sowie vollständige Flugplan-Felder: `route`, `remarks`, `cruise_altitude`, `cruise_tas`, `flight_rules`, `aircraft_icao`, `alternate`, `deptime`, `enroute_time`, `fuel_time` (ab Aufzeichnungsdatum gefüllt, ältere Einträge NULL) |
| `live_positions` | Aktuelle Position pro CID (UPSERT, maximal 1 Zeile pro CID) |
| `position_history` | Jede einzelne VATSIM-Positions-Update (für Tracks + Events) |
| `calendar_events` | FriesenFlieger Google-Kalender (alle 6h synchronisiert, UID als Primary Key); `route` (CSV aller ICAOs) + `is_bummel` (Flag) für die FriesenFliegerBummel-Erkennung; `delete_stale_calendar_events` räumt bei jedem Sync Termine weg, die im Google-Kalender gelöscht wurden (Mark-and-Sweep über die im Lauf gelieferten UIDs, begrenzt auf das Sync-Fenster ±365/90 Tage) — `bummel_races`/`transport_events` bleiben davon unberührt. **Kutter-Termine ausgeschlossen (Variante ①, 20.07.2026):** Einträge mit „kutter"/„friesenkutter" im Titel/Text werden bereits bei der Aufnahme verworfen (`is_kutter_calendar_entry`) — sie landen gar nicht in dieser Tabelle |
| `bummel_races` | Persistente Bummel-Rennen (vom Poller beim Kalender-Sync oder Admin manuell angelegt); `revealed_at` steuert die Fairness-Verdeckung — `NULL` = noch verborgen, Zeitstempel = enthüllt (Latch); `started_at` = Start-Latch (erster Pilot mit Blockzeit an einem Streckenflugplatz, `NULL` = noch kein Start); `push_enabled` steuert Push-Benachrichtigungen je Rennen (1 = an, 0 = aus); `source` ∈ `calendar` | `manual` |
| `bummel_overrides` | Admin-Korrekturen pro Rennen + Pilot (PK `race_id + cid`); `action` ∈ `exclude` \| `disqualify` \| `winner` \| `manual`; bei `manual`: `manual_total_min` ersetzt die gemessene Block-Zeit; Overrides werden durch `apply_bummel_overrides` auf die Wertung angewendet |
| `transport_events` | Persistente FriesenKutter-Transport-Events. **Seit 20.07.2026 nur noch Admin/manuell** (`source = manual`) — der Kalender-Import ist deaktiviert, Kutter-Kalendertermine werden bei der Aufnahme verworfen (`is_kutter_calendar_entry`); der `source = calendar`-Pfad (`upsert_calendar_transport_event`) bleibt für eine spätere forum-basierte Lösung im Code, wird aber nicht mehr getriggert. `route` (ICAO-CSV), `destination` (Ziel-ICAO — nur Flüge dorthin laden Fracht), Latches `started_at`/`goal_reached_at`/`summarized_at` für die Pushs; `push_enabled` steuert Push-Benachrichtigungen je Event (1 = an, 0 = aus, analog `bummel_races.push_enabled`); `source` ∈ `calendar` \| `manual` |
| `transport_cargo` | Fracht-Manifest je Event (geordnet): `position`, `name` (Frachtart), `target_kg`, `emoji`/`per_flight_max_kg` (Snapshot aus `cargo_catalog`) und `departure` — **genau EIN Startplatz ≠ Ziel, Pflicht** (Stapel-Modell, Entscheidung 6: eine Zeile = ein Stapel = ein Ort; `set_transport_cargo` wirft `ValueError` bei fehlendem/mehrfachem Platz). Σ `target_kg` = Event-Ziel; kein „geteilter Topf" (`departure NULL`) und keine CSV-Liste mehr, ein Event **ohne** Manifest liefert 0 (kein reiner Zähler) |
| `aircraft_payloads` | Zuladung je Flugzeugtyp (Admin-editierbar): `mtow_kg`/`empty_kg`/`fuel_kg` (Tankinhalt fürs Rechnen = halber Tank)/`fuel_full_kg` (max. Tankinhalt, volle Tanks; `fuel_kg` = Hälfte davon)/`crew_kg` (Pilot, Default 85, zählt nicht als Fracht) → `payload_kg = max(0, mtow−empty−fuel−crew)`, direkt überschreibbar; `source` ∈ `manual` \| `llm` \| `curated` \| `default`; `make_model` (Klartext, im Admin editierbar). **Vorbefüllung (v8.17.0):** beim Start pflegt `seed_curated_payloads` die Typen aus `app/data/aircraft_specs.json` ein (~108 GA-/Privat-/Hubschraubermuster inkl. Transall C-160 & A400M, `source='curated'`, viele Werte aus FSEconomy): fehlende Typen werden eingefügt, **bestehende automatisch recherchierte Zeilen (`source='llm'`/`'default'`/`NULL`) werden auf die kuratierten Werte gehoben** (Max-Tank nachtragen + Tankfüllung korrigieren), `source='manual'` (Handpflege) und bereits `'curated'` bleiben unangetastet (idempotent, verlustfrei); ein Backfill setzt `fuel_full_kg = fuel_kg*2` für Altbestand. Damit läuft die Live-Web-Recherche (`suggest_aircraft_payload`) nur noch für unbekannte Muster. **Inf/NaN-Härtung (v8.8.1/#64):** ein Phantom-Flugzeugtyp (z. B. ein Buchstabendreher im Flugplan, `SA65` statt `AS65`) kann Claude zu unplausiblen Werten verleiten; `json.loads`/`float()` akzeptieren `Infinity`/`NaN` klaglos, ein solcher Wert sprengte dann die ganze Zuladungs-Liste beim JSON-Encoding (`ValueError: Out of range float values are not JSON compliant`, 500 auf `GET /api/admin/transport/payloads`). Vierfach gehärtet: (1) `llm.suggest_aircraft_payload` verwirft nicht-endliche/nicht-positive Werte vor der Rückgabe, (2) `upsert_payload` kappt inf/nan zu `None`, (3) `init_db` bereinigt Bestandsschäden einmalig (idempotent; `payload_kg` ist `NOT NULL` → dort `0.0`-Fallback statt `NULL`), (4) `list_aircraft_payloads` gibt inf/nan defensiv als `None` zurück (`_finite_or_none`) — keine einzelne Ebene muss allein tragen. |
| `custom_airports` | Ergänzungs-Flugplätze (v8.5.0/#50, seit v8.6.0/#56 ein **Override** statt reiner Fallback): Plätze, die in `airportsdata` fehlen (z. B. Segelfluggelände ohne offizielle ICAO-Kennung — `icao` erlaubt dann einen Platzhalter-Code wie `ZZSALZ`, kein echter 4-Buchstaben-ICAO nötig) ODER deren `airportsdata`-Koordinaten nachweislich falsch sind (Fund: EBUL/Ursel Air Base ~15 km daneben). `lat`/`lon` Pflicht (seit v8.7.0/#62 nur, wenn der Code nirgends bekannt ist — s. u.), `elevation_ft` optional (`NULL` macht die GPS-Rettung am Track-Ende, #53, konservativ; den Spawn-Guard, #49, bleibt sie permissiv). `radius_km` (v8.7.0/#62, optional, `NULL` = Standardradius der aufrufenden Funktion) überschreibt NUR den Suchradius für diesen Code, unabhängig von lat/lon — für Großflughäfen, deren tatsächlicher Abhebe-/Aufsetzpunkt weiter vom `airportsdata`-Referenzpunkt entfernt liegen kann als der Standardradius (Fund: EHAM/Schiphol, Abhebepunkt nach langem Rollweg 6,6 km entfernt, Standardradius 4 km — die Koordinate selbst war korrekt, nur der Radius zu eng). Admin-CRUD unter `/api/admin/airports`; `app/geo.py` konsultiert die Tabelle jetzt ZUERST (Push-Modell über `geo.set_custom_airports()`, kein direkter DB-Zugriff in `geo.py`) — ein von Custom überschatteter `airportsdata`-Eintrag wird in `nearest_airport_icao`/`nearest_airport_icao_fast` übersprungen, sonst würde die falsche Standard-Position weiter konkurrieren. In beiden Funktionen zählt ein Custom-Kandidat mit eigenem `radius_km` auch jenseits des übergebenen Standardradius als zulässig, gewinnt aber (wie jeder Kandidat) nur bei tatsächlich kürzerer Distanz als der bisher beste Treffer — „nearest" bleibt „nearest", der eigene Radius entscheidet nur über die Zulassung, nicht über den Vorrang. Seed (idempotent, nur bei leerer Tabelle) enthält zehn in Live-Analysen (2026-07-05) bestätigte Plätze (EBUL bewusst nicht — Override bleibt eine bewusste Admin-Handlung). Ein Admin-Write ohne `override: true` lehnt bereits in `airportsdata` bekannte Codes ab (`geo.is_known_in_airportsdata`, `409` — „Bestätigung nötig", nicht `400` „echter Fehler"); mit `override: true` wird trotzdem gespeichert. Bleiben `lat`/`lon` beim Speichern leer, werden die bereits bekannten Koordinaten übernommen (Custom-Eintrag, sonst `airportsdata`) — praktisch für einen reinen Radius-Override, ohne Koordinaten eintippen zu müssen, die man selbst nicht genau kennt; ist der Code nirgends bekannt, bleiben `lat`/`lon` Pflicht (`400`). Jeder Write stößt einen vollen `rebuild_flight_cache` an (der inkrementelle 7-Tage-Refresh würde ältere, durch den neuen/geänderten Platz betroffene Flüge nicht heilen). `reason` (v9.5.0/#78, optional, `NULL` erlaubt) dokumentiert, WARUM der Eintrag existiert — reine Dokumentation ohne Wirkung auf die Erkennung, bewusst **nie** Pflicht (der Eintrag selbst ist die Funktion; ein Pflichtfeld würde im Zweifel echte Korrekturen verhindern) und bewusst Freitext statt Enum/`CHECK` (neue Gründe sollen durch Benutzung entstehen; das Admin-UI schlägt per `<datalist>` nur die bereits vergebenen vor — abgeleitet aus der ohnehin geladenen Liste, kein eigener Endpoint). Bestandseinträge wurden einmalig über `migrate_custom_airport_reasons` (idempotent, `WHERE reason IS NULL` → Admin-Texte überleben jeden `init_db`-Lauf) **aus den Daten** beschriftet statt über eine gepflegte Code-Liste: Code nicht in `airportsdata` → `Fehlt in airportsdata`; Koordinate > 1 km abweichend → `airportsdata-Koordinate falsch`; sonst → `Abhebepunkt außerhalb Standardradius`. Der Vergleich nutzt `geo.airportsdata_coords()` (reiner `airportsdata`-Wert) statt `icao_to_coords()` — letzteres liefert bei einem Override den Custom-Wert, der Abstand wäre also immer 0 km und JEDER Override sähe wie ein Radius-Fall aus. Die 1-km-Schwelle trennt sauber: EHAM (reiner Radius-Override) liegt bei 0,00 km, der nächstkleinere echte Korrekturfall (EBUL) bei 15,0 km. |
| `airport_links` | Kuratierte Karten-Links für Deutschland (amtliche DFS-AIP-VFR-Flugplatzkarte, `aip.dfs.de`): `icao` (PK) → `aip_url`. 446 Flugplätze (Stand 2026-06-25) beim ersten Start geseedet (`seed_airport_links`, idempotent — nur bei leerer Tabelle, Admin-Änderungen überleben jeden Neustart), abgeleitet aus der lokal installierten AIPBrowserDE-App (`aip-de-vfr.db`, `AIPReference`/`AIPPage`, kein Navdata-Store — nur Kapitel-/Seiten-Struktur, daher einmaliger Extraktionslauf statt Live-Abfrage). Admin-CRUD unter `/api/admin/airport-links`. Für Codes AUSSERHALB dieser Tabelle, aber bei `airportsdata` bekannt: `GET /api/airport-links` (öffentlich) ergänzt server-seitig einen rechnerischen ChartFox-Fallback (`chartfox.org/{ICAO}`, kein eigener DB-Eintrag) — Codes weder amtlich noch bei `airportsdata` bekannt (z. B. unbestätigte Navigraph-only-Platzhalter) bleiben ohne Link. Rein informativ (Frontend-Icon neben angezeigten Flugplatz-Codes), keine Wirkung auf Flug-Erkennung — kein `rebuild_flight_cache` nötig. |
| `gps_detection_dismissals` | Admin-Prüfliste „Erkennungslücken" (v8.6.0): `(cid, logon_time)` markiert einen einzelnen Flug dauerhaft als „kein Datenfehler" (Absturz, abgerissene Aufzeichnung) — blendet ihn aus `list_gps_detection_gaps` aus, unabhängig vom betroffenen Flugplatz-Code. Kein Cache: die Prüfliste selbst ruft `canonicalize_legs` live auf, damit ein neu ergänzter `custom_airports`-Eintrag den betroffenen Flug sofort verschwinden lässt. |
| `cargo_catalog` | Frachtart-Stammdaten (Phase 2): `name`, `emoji`, `per_flight_max_kg` (Obergrenze pro Flug für Co-Load). Beim Manifest wählbar; `set_transport_cargo` speichert Emoji/Max als Snapshot in `transport_cargo`. In `init_db` idempotent geseedet (`seed_cargo_catalog`) |
| `transport_quips` | Cache der lustigen KI-Sprüche je Flug (PK `event_id + flight_key` mit `flight_key = "{cid}:{logon_time}"`). Tagesend-Zusammenfassung liegt in `transport_events.summary_quip` |
| `push_subscriptions` | Browser-Push-Subscriptions (Endpoint, ECDH-Keys, `pilot_filter` als JSON-Array — gilt für Online/Flugplan/TS, `notify_prefiles`/`notify_ts`/`notify_events` Flags, `owner_cid` = Besitzer-CID aus dem Forum-Login für die Subjekt-Allowlist; `created_at` wird bei Re-Abo mit aktualisiert). `owner_cid` wird beim Konflikt per `COALESCE` nur mit Nicht-NULL überschrieben (anonymer Re-Subscribe löscht den Owner nicht) |
| `pilot_visibility` | **Subjekt-Sichtbarkeit** pro CID („wer darf über mich benachrichtigt werden?"): `mode` ∈ `everyone`/`allowlist`/`nobody`, `allowlist` als JSON-CID-Liste. Kein Eintrag = Default `everyone`. Gilt für **alle** Push-Pfade (Online/Flugplan/TS) + den Telegram-Online-Kanal |
| `forum_callsign` | Autoritative Callsign→CID-Map aus dem Forum-Login (`callsign` PK UPPER, `cid`); beim Callback gefüllt/selbst-bereinigt. Quelle für `cid_for_callsign_authoritative` (TS-Subjektauflösung) |
| `prefile_sigs` | Letzte bekannte Prefile-Signatur pro CID (`deptime`, `departure`, `arrival`) — wird nach jedem Poll persistiert, damit Container-Neustarts keine Änderungen verpassen |
| `event_reminders_sent` | Gesendete Event-Erinnerungen (Latch-Tabelle): `uid` (Kalender-Event-UID als PRIMARY KEY) + `sent_at` — verhindert, dass eine Erinnerung mehrfach versandt wird; idempotent über Container-Neustarts |
| `flight_cache` | Materialisierte `canonicalize_legs`-Ergebnisse (GPS-only Phase 2, #23) für die globale Statistik; `UNIQUE(cid, logon_time)`, Feldvertrag identisch zu `canonicalize_legs` plus `computed_at`. Vom Poller warmgehalten (`flight_cache_warmup` beim Start, `flight_cache_refresh` alle 5 min) und bei Bedarf von `get_cached_flights` selbst nachgezogen |
| `statsim_position_history` | Lokal gecachte GPS-Tracks importierter StatSim-Flüge (`statsim_id` + Positionsreihe) — Voraussetzung dafür, dass die GPS-Leg-Erkennung auch StatSim-Flüge auswerten kann statt auf den Flugplan-Fallback zurückzufallen; befüllt vom proaktiven Poller-Job `statsim_track_fetch` und dem Admin-Bulk-Backfill `POST /api/admin/statsim-backfill` |
| `progress_snapshot` | Eingefrorenes Rechenergebnis abgeschlossener Spezial-Events (#66, v8.10.0): PK `(kind, ref_id)` — `kind` ∈ `kutter`\|`bummel`, `ref_id` = `transport_events.id` bzw. `bummel_races.id` —, `code_version` (Wert von `_PROGRESS_SNAPSHOT_VERSION` zum Einfrierzeitpunkt), `computed_at`, `payload_json` (das komplette `compute_transport_progress`- bzw. `_build_race_view`-Ergebnis als JSON). Siehe „Fortschritts-Snapshot + Retention" unten. |

Drei Indizes: `idx_ph_cid_ts`, `idx_ph_ts`, `idx_flights_cid`.

**Sessionisierung — `(cid, logon_time)` als Schlüssel.** Eine VATSIM-Verbindung ist eindeutig über `(cid, logon_time)` bestimmt (VATSIM kennt keine Session-ID; `logon_time` ist pro Verbindung stabil). Diese Invariante wird strukturell erzwungen durch einen **partiellen Unique-Index** `idx_flights_session ON flights(cid, logon_time) WHERE superseded_by IS NULL` — pro Verbindung existiert höchstens **ein aktiver** Flug. Die Spalte `superseded_by` (NULL = aktiv, sonst id des Behalt-Records) erlaubt es, Duplikate **reversibel** zu markieren statt zu löschen.

**`open_flight(conn, ..., *, route, remarks, ...)`** — `INSERT … ON CONFLICT(cid, logon_time) WHERE superseded_by IS NULL DO NOTHING`, danach wird die bestehende id zurückgegeben. Ein erneutes Öffnen derselben Verbindung (z. B. nach Container-Neustart) ist damit ein **strukturelles No-Op** — unabhängig vom In-Memory-State.

**`update_flight_plan(conn, flight_id, departure, arrival, *, route, remarks, ...)`** — setzt DEP/ARR und alle erweiterten Flugplan-Felder eines laufenden Fluges nachträglich, wenn der Pilot den Plan nach dem Verbindungsaufbau einreicht oder ändert. Wird ausschließlich vom Poller aufgerufen (Flugplanwechsel-Erkennung in `_poll_once`).

Alle DB-Operationen sind synchron (SQLite ist thread-safe mit WAL). Verbindungen werden pro Request geöffnet und in `finally`-Blöcken geschlossen.

**`merge_fragmented_flights(flights, gap_minutes=5, conn=None)`** — führt zwei aufeinanderfolgende Verbindungen desselben Piloten read-time zu **einem logischen Flug** zusammen (Reconnect-Stitching). Ein vorübergehender Reconnect ist für VATSIM zwei Verbindungen (zwei Zeilen, atomar gespeichert); hier werden sie für Anzeige/Statistik gemergt. Bedingungen:

1. **Gleicher Callsign** (nicht leer)
2. **Flugplan = Hauptsignal** — entweder (a) genau einer der beiden hat keinen Flugplan (no-FP-Reconnect vor Neu-Filen), oder (b) beide haben denselben nicht-leeren DEP+ARR (unterbrochener Flug)
3. **Gap-Fenster nach Flugplan** — same-FP bis **30 Min** (`_RECONNECT_GAP_SAME_FP_MIN`, der gleiche Flugplan trägt die Beweislast), no-FP bis **15 Min** (`_RECONNECT_GAP_NO_FP_MIN`); Toleranz −2 Min für VATSIM-Jitter
4. **Geo-Kontinuität** (`_segments_continuous`, nur mit `conn`): **Distanz-Budget** statt fester Radius — der Abstand zwischen der **letzten Position von Segment 1** und der **ersten Position von Segment 2** darf höchstens `Lückendauer × 600 kt + 10 nm` betragen. Das löst den Fall „Pilot 10 Min ohne Netz, Sim fliegt weiter" (Reconnect taucht stromabwärts auf), weist aber Teleports ab. **Fertig-gelandet-Regel**: ist Segment 1 nachweislich **geflogen** (mind. eine Position ≥ `_FLOWN_MIN_GS_KT` = 60 kt) und endete **am Boden** (letzte Position ≤ `_LANDED_MAX_GS_KT` = 40 kt), ist der Flug abgeschlossen — Segment 2 ist dann ein **neuer Flug**, kein Reconnect, unabhängig vom Landeort. Das verhindert beide Stale-FP-Fälle vom Live-Test 2026-07-01 (FRS102): der Rückflug mit stehengebliebenem Flugplan startet „am Ziel" und passierte die Richtungsprüfung (282+286); und er landet am FP-**Start**, sodass der nächste echte Hinflug wieder als „Fortschritt Richtung Ziel" durchging (286+287). Reine Boden-Segmente (nie geflogen, z. B. Gate-Reconnect vor dem Neu-Filen) mergen weiterhin. Zusätzlich **Richtungsprüfung**: Segment 2 darf nicht deutlich weiter vom Ziel entfernt sein als das Ende von Segment 1. Fallback Merge, wenn keine GPS-Daten vorhanden.

Das gemergde Ergebnis übernimmt logon_time des früheren, logoff_time des späteren Segments; **duration_min wird addiert** (die Disconnect-Lücke zählt nicht mit → keine Inflation); distance_nm wird addiert. Gegenprobe: gleicher Callsign aber **anderer FP** (z. B. Rückleg) → kein Merge, zwei Flüge.

**`backfill_flight_distances(conn)`** — läuft beim Start in `init_db()` einmalig: Berechnet `distance_nm` für abgeschlossene Flüge nach, die noch `0` haben aber `position_history`-Einträge besitzen (Haversine-Summe über alle Positionspunkte im Logon–Logoff-Fenster). Idempotent — bereits berechnete Flüge (`distance_nm > 0`) werden übersprungen. Deckt Flüge ab, die vor Einführung der GPS-Distanzberechnung aufgezeichnet wurden.

**Block-Zeit (`block_min`).** Zusätzlich zur **Online-Zeit** (Verbindungsdauer logon→logoff, `duration_min`) wird die **Block-Zeit** geführt: die **Summe der bewegten Abschnitte** (`groundspeed > _BLOCK_GS_KT`, 2 kt) innerhalb [logon, logoff] aus `position_history` (`_block_minutes()`/`_block_seconds()`, gate-to-gate inkl. Taxi). **Belegte Standphasen** — zusammenhängende Positionen mit `groundspeed ≤ 2 kt` zwischen zwei Bewegungen, ab `_BLOCK_STAND_MIN_SEC` (10 min) — zählen **nicht** mit: so verfälscht eine Zwischenlandung ohne Disconnect die Bummel-Wertung nicht mehr (vorher zählte „erste bis letzte Bewegung" die Standzeit mit). Kürzere Stopps (Rollhalt) bleiben enthalten; Datenlücken **ohne** Stillstands-Beleg (Feed-Aussetzer) zählen weiterhin voll. `close_flight` setzt `block_min` mit; `backfill_block_minutes(conn)` füllt Bestandsflüge in `init_db()` nach; `merge_fragmented_flights` summiert `block_min` der Segmente; `canonicalize_flights` liefert es mit. Block-Zeit ist **FriesenSpy-only** (StatSim/Altflüge ohne dichte GS-Spur → keine Block-Zeit). So lässt sich „angesteckt am Gate" von echter Bewegung trennen.

**`close_stale_flights(conn, max_age_hours=8)`** — Startup-Notnagel: schließt offene Flüge älter als 8 h (echte Waisen, die Rehydration + Live-Close nicht erwischt haben). Als `logoff_time` wird die letzte `position_history` ab `logon_time` verwendet, **gedeckelt auf `MIN(logon_time)` der nächsten Session** desselben Piloten — so kann ein Logoff nie Positionen eines späteren Fluges greifen (das war die Ursache der 139-Min-Zombie-Inflation). Ohne Positionen wird `logon_time` gesetzt (duration=0, ghost-gefiltert).

**`consolidate_flights(conn, *, statsim_correct=True, shrink_margin_min=10)`** — läuft idempotent in `init_db()` **vor** dem Anlegen des partiellen Unique-Index (Reihenfolge zwingend, sonst Constraint-Verletzung) und ist als `scripts/consolidate_flights.py` (mit `--dry-run`) manuell aufrufbar. **Selbst-korrigierend:** zu Beginn werden der Unique-Index gedroppt und `superseded_by` zurückgesetzt — jeder Lauf rechnet von vorn (idempotent), sodass auch früher falsch markierte Flüge wieder auftauchen. Reversibler Cleanup in fünf Schritten: (A) mehrere offene Flüge je cid → nur die **jüngste** (aktuelle Live-Verbindung) offen lassen, ältere offene Flüge als beendete Verbindungen **schließen** (gedeckelter Logoff, kein supersede) — ein Pilot hat nur eine Verbindung gleichzeitig; mehrere offene Zeilen entstehen, wenn ein Disconnect verpasst wurde (z. B. Reconnect über einen Neustart) und sind sequenzielle, keine gleichzeitigen Verbindungen; (B) exakte Duplikate (gleiche cid+logon_time) → Keeper-Priorität **(1) Flug mit echtem Inhalt** (Nicht-Ghost: `distance_nm > 0.5 OR duration_min > 5`), (2) offener Flug, (3) niedrigste id — verhindert, dass ein 0-Min-Ghost mit gleicher logon_time den echten Flug verdrängt; (C) Zombie-Logoffs auf die gedeckelte letzte Position korrigieren (nur wenn das die Dauer um ≥ `shrink_margin_min` verkürzt); (D) StatSim-Backstop: grob unplausible FS-Dauern (> 2× StatSim + 10) auf den StatSim-Wert korrigieren; (E) **Selbstheilung unmöglicher Blockzeiten**: `block_min > duration_min` kann nicht sein → mit dem gespeicherten Fenster neu berechnen. C und D rechnen `block_min` bei jeder Fenster-Korrektur mit (früher blieb dort eine Blockzeit aus dem aufgeblähten Fenster stehen — Ursache von „block 92 > duration 28", Live-Test 2026-07-01). `consolidate_flights` committet **nicht** selbst (Aufrufer committen → ermöglicht Dry-Run via rollback). Rückgängig: `UPDATE flights SET superseded_by = NULL`.

**`reconstruct_orphaned_flights(conn, *, cids=None)`** — läuft in `init_db()` nach `consolidate_flights` **und** (cid-gefiltert) direkt nach jedem StatSim-Refresh (Drill-down-Hintergrund-Fetch in `main.py`, Neu-Pilot-Load im Poller): rekonstruiert flights-Einträge für **verwaiste GPS-Tracks** (A1-Schadensbild). **Anker ist die StatSim-LANDEZEIT** (`arrived` → `logoff_time`): StatSims `loggedOn` ist die Session-Anmeldung und bei mehreren Flügen einer Verbindung für alle gleich — als Flugbeginn unbrauchbar. Kandidat = jede StatSim-Landung mit Strecke, die in **keinem** aktiven FS-Fenster (± `_RECONSTRUCT_COVER_MARGIN_MIN` = 5 min) liegt. Der Flugbeginn wird per Rückwärtssuche im Track bestimmt (letzte belegte Standphase ≥ `_RECONSTRUCT_STAND_SEC` = 5 min vor der Landung trennt das Leg vom vorigen; sonst ab voriger Session, gedeckelt `_RECONSTRUCT_MAX_LOOKBACK_H` = 3 h); Fensterende = Landung + `_RECONSTRUCT_MARGIN_MIN` = 10 min Taxi-in, gedeckelt auf die nächste Session. Nur mit belegter Flugbewegung (≥ 2 Positionen `groundspeed ≥ 40`); Dauer/Distanz/Block aus den **echten Positionsdaten**, Strecke/Callsign/Muster aus StatSim. Idempotent (einmal rekonstruiert deckt die neue Zeile die Landung); läuft nie für offene Sessions; Historie ohne Track bleibt unberührt. **Achtung Schwester-Regel:** `consolidate_flights` Schritt D nimmt aus demselben Grund das `MAX(duration_min)` aller StatSim-Zeilen derselben Anmelde-Minute — die Zeile des ersten Legs würde eine legitime Multi-Leg-Session fälschlich schrumpfen.

**`canonicalize_flights(conn, *, cids, callsign_prefix, start, end, include_statsim)` — die refile-/disconnect-basierte Flugzählung (seit GPS-only Phase 2/#23 kein produktiver Endpunkt mehr).** Liefert eine nach logon_time absteigend sortierte Liste kanonischer Flug-Dicts (Feld `source`: `friesenspy` | `statsim`). Pipeline: aktive FS-Flüge laden (`superseded_by IS NULL`, abgeschlossen) → Reconnect-/Fragment-Merge (`merge_fragmented_flights`) → Ghost-Filter (`distance_nm ≤ 0.5 AND duration_min ≤ 5` verwerfen) → StatSim laden und gegen die kanonische FS-Menge deduplizieren (`_dedup_statsim_against_fs`). Bis v7.9.5 war dies die einzige Wahrheit für alle Views; **seit v8.0.0 ist `canonicalize_legs` (s. u.) die produktive Wahrheit** — `canonicalize_flights` bleibt als Baustein bestehen: `merge_fragmented_flights`/der Ghost-Filter werden weiterhin als **Fallback** genutzt (`_gps_flights_for_positions`, wenn kein GPS-Track vorliegt), und die Funktion selbst dient dem **Diagnose-Audit** `GET /api/admin/gps-leg-audit` als Vergleichswert gegen die aktive GPS-Sicht. **Seit v8.3.0 (#33) läuft auch `/api/events` über `canonicalize_legs`** (letzter verbliebener Consumer der alten `flights`-Zeilen-Query) — `app/main.py` `get_events`.

**Ghost-Flight-Filter:** zentral in `canonicalize_flights` (Schritt 2). Verworfen werden (a) Test-Connects (`distance_nm ≤ 0.5 AND duration_min ≤ 5`) und (b) **belegte Steh-Sessions**: keine Strecke, `block_min` 0 und Positionen im Fenster vorhanden — wer verbunden nur herumsteht, hat nicht geflogen, egal wie lange (Live-Test 2026-07-01: 14-min-Session mit stalem FP erschien als 0-nm-„Flug"). Echte Kurzstrecken (z. B. 4 min, 15 nm) bleiben; ältere Flüge **ohne** Positionsdaten bleiben über `duration_min > 5` erhalten (kein Stillstands-Beleg → im Zweifel echter Flug).

**StatSim-Deduplizierung:** an **einer** Stelle (`_dedup_statsim_against_fs`). Ein StatSim-Eintrag wird unterdrückt, wenn (a) sein Logon innerhalb eines FS-Fensters [logon, logoff] liegt, oder (b) gleiche Strecke und FS-Logon bis 10 Min nach StatSim (Flugplanwechsel nach Connect). Distanz/Track/Flugplan bleiben immer FriesenSpy (reicher); StatSim korrigiert nur kaputte FS-Dauern (siehe `consolidate_flights` Schritt D).

**GPS-Leg-Erkennung — seit v8.0.0 die produktive Wahrheit (`app/gps_legs.py` + `canonicalize_legs` + `flight_cache`, #23).** Flüge/Etappen werden **rein aus GPS** erkannt (Landung = am Boden an einem Platz), statt aus Refile-Split/Disconnect.

> **Die fachlichen Anforderungen an einem Stück: [`docs/gps-flugerkennung.md`](gps-flugerkennung.md).** Dieser Abschnitt hier beschreibt den Aufbau (*wie*), das andere Dokument die Regeln und ihre Begründung (*was* und *warum*) — inklusive der bewussten Asymmetrien (#49 permissiv vs. #53 konservativ) und belegter Irrwege. **Vor jeder Änderung an der Erkennung dort den Abschnitt „Fallstricke" lesen** — zwei schlüssig wirkende Vereinfachungen sind daran nachweislich gescheitert.

- **`detect_gps_legs(positions, *, nearest_airport, airport_elev_ft, radius_km, gap_minutes, rescue_before)`** (`app/gps_legs.py`) — eine **reine, DB-freie** Zustandsmaschine `ON_GROUND → AIRBORNE → ON_GROUND` über die ts-sortierten Positionen eines Piloten (vorsegmentiert an Zeitlücken > `gap_minutes`). **Höhe (AGL) ist das Leitsignal:** Abheben, wenn die Höhe > `_GPS_AIR_AGL_FT` (500 ft) über den Boden-Ausgangspunkt steigt (die Boden-Referenz bleibt auf der Feldhöhe verankert — als Minimum geführt — und klettert **nicht** mit dem Steigflug mit, sonst bliebe der Anstieg immer nur ein Sample-Schritt und ein normal steigendes Flugzeug würde nie als abgehoben erkannt); **ODER** (v8.1.0, genauerer Startpunkt) `groundspeed > _GPS_FLYING_GS_KT` (50 kt) **UND** steigend (`AGL > _GPS_CLIMB_MIN_AGL_FT` = 100 ft und höher als das Vor-Sample) — so triggert ein schnelles Flugzeug schon beim Steigen statt erst 500 ft hoch, während ein Startlauf/Startabbruch (schnell, aber nicht steigend) **keinen** Scheinflug auslöst. Groundspeed ohne Höhe (`alt = None`) bleibt der reine sekundäre Fallback — so wird auch ein langsamer STOL/Heli erkannt und nicht als Ghost verworfen. **Landung wird NUR an einem Platz gewertet:** `groundspeed < 2 kt` UND AGL-Guard (`< _GPS_GROUND_AGL_FT` = 300 ft) UND im Umkreis eines DB-Platzes (`radius_km`, produktiv der feste `_BUMMEL_AIRPORT_RADIUS_KM` = 4 km); **kein Platz im Umkreis → keine Landung** (eine Außenlandung ist per GPS nicht von einem Absturz zu unterscheiden — bewusst nie als Ankunft). Die Landung wird **sofort am Touchdown-Sample finalisiert** (kein Dwell/LANDED-Zwischenzustand); jedes erneute Abheben startet über die normale, verankerte ON_GROUND-Erkennung einen neuen Roh-Leg. Der Ghost-Filter fällt strukturell weg: ein Track, der nie abhebt, erzeugt keinen Leg. Airport-Auflösung im Poll-tauglichen Tempo über `geo.nearest_airport_icao_fast` (Grad-Grid-Bucket-Index statt Linearscan) + `geo.airport_elevation_ft`.
  **Spawn-Startplatz (v8.5.0, #49):** spawnt der Track bereits airborne (`gs >= 50` beim allerersten Sample — typisch, wenn eine StatSim-Aufzeichnung erst im Steigflug direkt über dem Abflugplatz beginnt), wird `dep_icao` nicht mehr bedingungslos auf `None` gesetzt: liegt ein Platz im `radius_km`-Umkreis **und** die Höhe ist unbekannt **oder** unter `_GPS_SPAWN_MAX_AGL_FT` (1500 ft), zählt dieser Platz als Startplatz — **permissiv** bei unbekannter Elevation.
  **Landungs-Rettung am Track-Ende (v8.5.0, #53):** endet ein Segment airborne, weil der Track (StatSim-Aufzeichnungsende oder FriesenSpy-Disconnect) abbricht, BEVOR die reguläre `gs<2`-Touchdown-Erkennung greifen konnte, wird der letzte Sample geprüft: liegt er im Platz-Umkreis **und** unter `_GPS_GROUND_AGL_FT` (300 ft) — hier **konservativ**, KEINE Rettung bei unbekannter Elevation/Höhe, bewusst anders als der Spawn-Guard —, gilt der Flug dort als gelandet (`landing_ts` = letzter Sample). Der Parameter `rescue_before` steuert einen Live-Guard: `None` (StatSim, immer beendet) rettet immer; ein ISO-Zeitstempel (FriesenSpy) rettet nur, wenn der letzte Sample davor liegt — ein gerade laufender Anflug darf nicht fälschlich geschlossen werden. Absturz und sauberer Aufsetzer sind aus GPS nicht unterscheidbar, aber für die Wertung irrelevant: „an diesem Platz beendet" stimmt so oder so; ein Low-Pass/Durchstart wird nie fälschlich gerettet, weil der Track dort tatsächlich weiterläuft.
- **`collapse_same_airport(legs)`** (`app/gps_legs.py`) — verschmilzt aufeinanderfolgende Roh-Legs am **selben** Platz zu einem Flug (Platzrunde/Touch-and-Go/Stop-and-Go bleibt EIN Flug, keine Mehrfachzählung); ein Flug = Abheben an X → Landung am nächsten **anderen** Platz (oder offen). Eine X→X-Landung wird aber nur dann in den laufenden Flug absorbiert, wenn der **nächste Start binnen `_GPS_STOP_AND_GO_MAX_SEC` (300 s)** folgt (v8.1.0); nach einer längeren Bodenpause (Tanken/Kaffee) wird der Flug als X→X abgeschlossen und ab dem nächsten Start beginnt ein neuer Flug — sonst würde die Bodenzeit als Flugzeit verschluckt (`duration_min = Ende − Takeoff`). Die Schwelle ist bewusst knapp: zu groß → Pause zählt als Flugzeit (Korrektheitsfehler), zu klein → ein langer Taxi-Back wird in zwei Platzrunden-Flüge getrennt (nur kosmetisch). Segment-Wechsel (Zeitlücke) trennt immer.
- **`canonicalize_legs(conn, *, cids, start, end, callsign_prefix, radius_km)` — formgleicher GPS-Ersatz für `canonicalize_flights`, die EINZIGE produktive Wahrheit für „echte Flüge" seit v8.0.0.** Pipeline je Pilot/StatSim-Flug: Fenster-Lookback (12 h vor `start`, gegen Spawn-Artefakte an der Fensterkante) → Positionen laden → `detect_gps_legs` + `collapse_same_airport` über die echten Positionen → Flugplan-Zuordnung (zeitbasiert — zuletzt gefilter Plan zum Landungszeitpunkt, Spec G, Update 2026-07-05) → **Fallback** auf die reine Connection-/StatSim-Zeile (`canonicalize_flights`-Logik), wenn kein Track vorliegt oder kein Leg erkannt wurde → Ergebnis auf Überlappung mit `[start, end]` gefiltert → StatSim-Flüge, die einen FriesenSpy-Flug desselben cid überlappen, werden pro Flug (nicht pro Session) verworfen. Jedes Flug-Dict trägt zusätzlich zu den `canonicalize_flights`-Feldern: `gps_departure`/`gps_arrival` (GPS-erkannter Start/Ziel-ICAO, `null` ohne Track bzw. solange nicht gelandet), `plan_departure`/`plan_arrival` (reine Flugplan-Beschriftung), `connection_closed` (VATSIM-Verbindung beendet — **kein** Beweis, dass der Flug selbst fertig ist; das entscheidet allein `arrival`/`gps_arrival`/`logoff_time`) und `last_pos_ts` (v8.1.0 — Zeit der letzten belegten Position des Legs, **statisch**, nicht „now"; das Frontend leitet daraus „🛫 läuft" = offen UND letzte Position frisch ab und nutzt es als Track-Obergrenze offener Legs) sowie `block_start` (v8.9.0/#62 — **Rollbeginn**, Rückwärts-Walk ab `takeoff_ts` bis zum ersten zusammenhängenden Sample, begrenzt durch das Ende des Vorflugs/eine 30-min-Lücke; dieselbe Größe, die schon `block_min` liefert. Das Frontend nutzt sie als Track-**Unter**grenze der gefensterten FriesenSpy-Track-Endpoints, damit Taxi-out + Startlauf sichtbar werden — bisher begann der Track erst am Abheben `logon_time`/`takeoff_ts`. Das Ende bleibt `logoff_time`/`last_pos_ts`: die Landung wird ohnehin erst beim Vollstopp am Gate gewertet, der Taxi-in ist also schon enthalten. Der StatSim-Track lädt ungefenstert und zeigte den Rollbeginn schon immer). `last_pos_ts` steht bewusst **nicht** in `_FLIGHT_CACHE_COLUMNS` — nur die Direktaufruf-Pfade (Piloten-Detail, Events) brauchen es, die globale Statistik/der Cache nicht. `callsign_prefix=""` liefert alle Callsigns (Piloten-Detail-Ansicht, inkl. Fremd-Callsign-Flüge, die im Frontend als „nicht gewertet" markiert werden) — `/api/events` (seit v8.3.0, #33) ruft dagegen mit dem konfigurierten `CALLSIGN_PREFIX` auf: Fremd-Callsign-Flüge eines bekannten Piloten gehören nur in die Piloten-Statistik, nicht in die Event-Analyse (2-Klassen-Regel; die FS-Seite ist ohnehin implizit FRS-only, da der Poller nur FRS-Sessions in `position_history`/`flights` aufzeichnet, `filter_friesen_pilots`). **Aircraft ohne Plan-Match (v8.5.0, #52 — ersetzt den früheren `last_known_aircraft`-Fallback von v8.1.0):** hat ein GPS-Leg keinen Plan-Match (`id=None` — kein Plan existierte zum Landungszeitpunkt, oder der Connect blieb bis dahin planlos), bleibt `aircraft` im FS-Zweig bewusst `None` — der frühere Fallback auf das zuletzt gefilte Muster desselben Piloten (`last_known_aircraft`) war zeitlich blind (lieferte den GLOBAL neuesten Typ aus der `flights`-Tabelle, auch wenn der aus der Zukunft des jeweiligen Legs stammte) und wurde ersatzlos entfernt: der VATSIM-Feed führt ohne Flugplan grundsätzlich keine Typ-Info, ein Raten ist also immer eine Vermutung. StatSim-Zweig kennt den Typ dagegen weiterhin direkt aus `row["aircraft"]` (die `statsim_cache`-Zeile trägt ihn ohnehin — seit v8.3.0 bereits auf den kurzen ICAO-Typ normalisiert, `app/statsim.py` `_normalize_flight`, analog `aircraft_short` bei FriesenSpy-Flügen, seit v8.5.0/#51 auch beim Poller-Ingest zentral normalisiert). Genutzt von `/api/pilots/{cid}/flights` (live, ungecacht), `/api/events`, `compute_bummel_standings` und `compute_transport_progress` (radius_km-Parameter dort nur noch aus Signatur-Kompatibilität erhalten, wirkungslos — der Radius steckt fest im Leg-Detektor).
- **`flight_cache` + `rebuild_flight_cache`/`get_cached_flights`** (`app/database.py`) — materialisiert `canonicalize_legs`-Ergebnisse für die **globale** Statistik (alle Piloten, großes Fenster), wo `canonicalize_legs` live zu teuer wäre; Bummel/Kutter/Piloten-Detail (kleine cid-Mengen) rufen `canonicalize_legs` weiterhin direkt. `rebuild_flight_cache(conn, *, full)`: `full=True` (oder leerer Cache) räumt die Tabelle komplett und befüllt sie mit **allen** Flügen (`INSERT OR REPLACE` gegen `UNIQUE(cid, logon_time)`, idempotent); `full=False` löscht/berechnet nur Flüge der letzten `_FLIGHT_CACHE_INCREMENTAL_DAYS` (7) Tage neu — ältere, abgeschlossene Flüge bleiben unangetastet. `get_cached_flights(conn, *, start, end, callsign_prefix)` liest aus dem Cache und stößt selbst den Refresh an: leerer Cache → Voll-Rebuild; sonst, wenn der jüngste `computed_at` älter als `_FLIGHT_CACHE_MAX_AGE_SEC` (600 s) ist → inkrementeller Rebuild. Der Poller ergänzt das um einen **einmaligen Warm-up** kurz nach App-Start (`flight_cache_warmup`, voller Rebuild via `asyncio.to_thread`, ~5,5 s — blockiert den ersten `/api/stats`-Aufruf nach einem Deploy nicht) und einen **periodischen inkrementellen Refresh** (`flight_cache_refresh`, alle 5 min, ~0,5 s). Genutzt von `get_stats`/`get_stats_activity` (`/api/stats`, `/api/stats/activity`); ein Flug ohne Landepunkt bei noch offener Connection (`logoff_time IS NULL AND NOT connection_closed`) zählt dort bewusst **noch nicht** ("läuft" noch).
- **`audit_gps_vs_refile`** (`app/database.py`, `GET /api/admin/gps-leg-audit`) — read-only **Diagnose-Werkzeug** (kein produktiver Pfad mehr): vergleicht die alte `canonicalize_flights`-Zählung mit der collapsed GPS-Sicht aus `canonicalize_legs` (matches / extra / missing / arr_divergence / incomplete_rate / airborne_spawn_rate); `statsim_sample` hängt zusätzlich eine on-demand aus `statsim_position_history` gerechnete GPS-Interpretation der jüngsten StatSim-Flüge an. Nützlich zur Fehlersuche bei einem einzelnen Piloten/Zeitraum, ändert nie Wertung oder Cache.
- **StatSim-Mid-Air-Split-Merge (`_statsim_rows_continuous`, v8.6.5, Live-Fund KNF04WC CYYR→KCAR→KOWD):** StatSim schneidet einen echten durchgehenden Flug manchmal MITTEN IN DER LUFT (Flugplan-Umplanung ohne Landung, z. B. Ziel geändert) in zwei `statsim_cache`-Zeilen — verarbeitet man jede Zeile isoliert, entsteht ein Geister-Leg (gestartet, nie gelandet, weil die Positionsdaten der ersten Zeile vor der Landung enden). `canonicalize_legs` gruppiert dafür VOR der Leg-Erkennung zeitlich benachbarte `statsim_cache`-Zeilen desselben Piloten zu Clustern (Positionen werden aneinandergehängt, alle betroffenen Flugpläne gemeinsam als `plan_rows` übergeben — `_flightplan_asof` ordnet jedem erkannten Leg automatisch den zeitlich richtigen Plan zu). Die Merge-Entscheidung (`_statsim_rows_continuous`) nutzt dieselben Zeit-/Distanz-/Richtungs-Regeln wie der FriesenSpy-Reconnect (`_segments_continuous`: gleicher Plan ≤ 30 min, sonst ≤ 15 min; Distanz-Budget 600 kt + 10 nm Marge; Richtungstoleranz 20 km) — aber auf den ECHTEN Positions-Zeitstempeln statt den `logon_time`/`logoff_time`-Feldern von `statsim_cache` (die sind für diesen Zweck nachweislich unzuverlässig — im Fund lag dort eine vorgetäuschte 45-Minuten-Lücke, während die echten Positionen nur 60 s auseinanderlagen). **Ein Unterschied zum FS-Reconnect:** statt der einseitigen „Fertig gelandet"-Sperre gilt ein SYMMETRISCHES Airborne-Kriterium — beide Seiten der Naht müssen mit ≥ `_FLOWN_MIN_GS_KT` (60 kt) in der Luft sein. Bei einem echten Mid-Air-Split fliegt das Flugzeug über die id-Grenze hinweg weiter (im Fund: 236 kt → 241 kt); ein separater neuer Flug beginnt dagegen typischerweise am Boden (Taxi/Startlauf, niedrige gs) und wird so ausgeschlossen — ohne das großzügige Zeitfenster einzuengen. Eine Read-only-Messung über den gesamten Produktivbestand (2026-07-06, 2562 `statsim_cache`-Zeilen, 2524 benachbarte Paare) ergab 15 Merges bei 8 Piloten, alle stichprobenhaft gegen die Tracks verifiziert (ein Grenzfall mit großer Aufzeichnungslücke, aber nachweislich demselben Flug).
- **Proaktives StatSim-Track-Nachladen (Phase 2b, Poller-Job `statsim_track_fetch`, alle 10 min)** — holt die GPS-Tracks neu importierter, noch ungecachter StatSim-Flüge nach `statsim_position_history`, damit auch frisch importierte StatSim-Flüge sofort GPS-basiert (statt über den Flugplan-Fallback) ausgewertet werden. **Halb-und-halb-Split (v8.6.1, #61-Fund):** `get_uncached_statsim_ids()` sortiert standardmäßig `ORDER BY logon_time DESC` (jüngste zuerst) — bei laufend neu importiertem Bestand verhungert damit aber der alte Backlog auf ewig (Fund: Flüge aus 01/2025 blieben über einen Monat nach dem Metadaten-Import ohne Track, weil praktisch immer ein jüngerer ungecachter Flug zuerst bedient wurde). Der Job holt daher pro Lauf zwei Batches à 10 (`oldest_first=False`/`True`, dedupliziert) — je zur Hälfte jüngste und älteste ungecachte Flüge —, sodass der Rückstand garantiert schrumpft, ohne die Aktualität frischer Flüge zu opfern. Der Admin-Endpoint `POST /api/admin/statsim-backfill` bleibt für einen gezielten Voll-Backfill (größere Batches, manuell wiederholbar) erhalten.

**`compute_bummel_standings(conn, route_icaos, start, end, *, cids, radius_km)` — FriesenFliegerBummel-Wertung.** Baut seit v8.0.0 auf `canonicalize_legs` auf (GPS-Landung statt Disconnect/Refile, Fragment-Merge/Ghost-Filter bleiben als deren Fallback erhalten). **Anwesenheit GPS-basiert:** Start/Ziel je Flug (`gps_departure`/`gps_arrival`) kommen bereits GPS-korrigiert aus `canonicalize_legs` — der gefilte **Flugplan dient nur als Fallback** ohne GPS-Track (z. B. reine StatSim-Flüge). Dadurch sind Flugplan-Tippfehler irrelevant. Der `radius_km`-Parameter der Funktion wird nur noch aus Signatur-Kompatibilität entgegengenommen (`bummel_races.radius_km` reicht ihn weiterhin durch) — er hat **keine Wirkung mehr**: die Platz-Zuordnung sitzt fest im GPS-Leg-Detektor mit dem globalen, festen Radius `_BUMMEL_AIRPORT_RADIUS_KM` = **4 km** (datenbasiert justiert, #23) — es gibt keinen per-Rennen-Radius mehr.

**Track-/tour-basiert (Bummel = gemütlich):** Statt jedes Leg einzeln zu prüfen, bildet die Wertung pro Pilot eine zeitlich geordnete **Tour** — vom ersten Leg, dessen Start auf der Strecke liegt, bis zum letzten Leg, dessen Ziel auf der Strecke liegt. **Zwischenlandungen dazwischen sind erlaubt** (z. B. EDPS→EDNX→EDMA) und brechen die Wertung nicht. Gewertete Zeit = Summe `block_min` (Fallback `duration_min`) der Tour-Legs; da `block_min` pro Flug zählt, fällt die **Bodenzeit der Zwischenstopps automatisch raus**. **Frühstarter:** Flüge werden mit Vorlauf `_BUMMEL_EARLY_START_LOOKBACK_H` (12 h) geladen und nach Überlappung mit dem Eventfenster (`logoff_time >= start`) gefiltert — wer vor `start` losfliegt, aber im Fenster unterwegs ist, zählt mit **voller Blockzeit**. **Komplett** = alle Streckenflugplätze in der Tour besucht (Set-Inklusion, Reihenfolge/Richtung egal). Komplette Touren kommen ins Ranking (aufsteigend nach dem Abstand zum Schnitt), unvollständige werden separat mit `visited`/`missing` gelistet — bewusst, damit ein nicht erkanntes Leg sofort sichtbar ist, statt den Piloten still zu verwerfen. Jeder Standing-Eintrag trägt zusätzlich `aircraft` (repräsentatives Muster) und `leg_count`.

**Sekundengenaue Wertung (Gleichstand-Auflösung).** Zusätzlich zur Minuten-Wertung wird pro Leg eine **sekundengenaue Block-Zeit** geführt: `_block_seconds(conn, cid, logon, logoff)` summiert die bewegten Abschnitte aus `position_history` (belegte Standphasen ≥ 10 min ausgenommen; Fallback `minutes * 60`, z. B. StatSim ohne dichten Track) und summiert sich je Pilot zu `total_sec`. Daraus berechnet die Wertung den **signierten** Abstand `delta_sec = round(total_sec − average_sec)` (positiv = über dem Schnitt, negativ = darunter) und sortiert das Ranking sekundengenau mit dem Sortierschlüssel `(abs(delta_sec), total_sec, cid)` — das löst Gleichstände auf, die bei gleicher Minuten-Blockzeit entstünden. Die **Anzeige** von Block-Gesamtzeit und Schnitt bleibt in Minuten; nur der Abstand zum Schnitt wird signiert + sekundengenau gezeigt. Neue Felder pro Eintrag: `total_sec`, `delta_sec`; auf Standings-Ebene zusätzlich `average_sec`. Das parallel weiter berechnete `delta` (gerundete Minuten-Differenz) bleibt nur aus Kompatibilitätsgründen erhalten. Die Sekunden-Felder stehen auf der Whitelist von `public_bummel_view` **nicht** und werden daher vor der Enthüllung nicht durchgereicht (Fairness).

**Fairness-Verdeckung und Enthüllungs-Logik (Bummel-Rennen).**

- **`_effective_dtend(race)`** — gibt `dtend` aus `bummel_races` zurück. Fehlt es im Original-Kalendertermin, hat `upsert_calendar_bummel_race` es beim Anlegen auf Mitternacht UTC des Folgetags (00:00:00Z nach dem Starttag) gesetzt, sodass `_effective_dtend` immer einen gültigen Zeitstempel liefert.

- **`public_bummel_view(conn, race)`** — zentrale Redigierfunktion. Prüft `revealed_at IS NULL`; ist die Enthüllung noch nicht erfolgt, werden aus der Antwort entfernt: Block-/Gesamtzeiten, Durchschnitt, Abstand zum Schnitt, Ranking-Reihenfolge, Lande-/Logoff-Zeit, Online-Dauer, geflogene nm. Sichtbar bleiben: Callsign, Name, Flugzeugtyp, Flugplan (Start/Ziel/Route), Abflugzeit, besuchte/fehlende Flugplätze, Anzahl Legs, wer gerade unterwegs ist. Die Redigierung passiert **serverseitig** — die Zeiten stehen vor Enthüllung nicht mal im JSON.

- **`_bummel_anyone_in_progress(conn, race)`** — prüft, ob noch ein Teilnehmer aktiv unterwegs ist: offener Flug (`logoff_time IS NULL`), der vor `dtend` gestartet hat und dessen Start-Airport zur Strecke gehört.

- **`update_bummel_starts(conn)`** — Start-Latch, ebenfalls vom `bummel_reveal_check`-Job (alle 60 s) aufgerufen. Prüft alle Rennen mit `started_at IS NULL` und `status = running`; setzt `started_at = now()` sobald mindestens ein Teilnehmer eine Blockzeit an einem Streckenflugplatz aufweist (d. h. der erste Pilot hat abgehoben). Einmal gesetzt wird `started_at` nicht zurückgesetzt. Ist `push_enabled = 1`, löst der Job direkt einen `send_web_push`-Broadcast aus — ausschließlich an Subscriptions mit `notify_events = 1` (via `get_push_subscriptions_for_events`) („FRSxx hat den Bummel gestartet!").

- **`update_bummel_reveals(conn)`** — Enthüllungs-Latch, aufgerufen vom Poller-Job `bummel_reveal_check` (alle 60 s). Durchläuft alle Rennen mit `revealed_at IS NULL` **und `reveal_suppressed = 0`** (ein vom Admin manuell verborgenes Rennen wird übersprungen — sonst würde der Job ein bereits abgelaufenes Rennen sofort wieder enthüllen). Enthüllt (setzt `revealed_at = now()`) ein Rennen, sobald **beide** Bedingungen erfüllt sind: (1) `_effective_dtend` ist überschritten, (2) `_bummel_anyone_in_progress` liefert `False`. Ist noch ein Nachzügler in der Luft, wartet der Job weiter (`status = waiting`). **Einmal enthüllt bleibt enthüllt** — der Zeitstempel in `revealed_at` wird nie zurückgesetzt (`set_bummel_revealed`). Ist `push_enabled = 1`, wird bei der Enthüllung ein `send_web_push`-Broadcast ausschließlich an Subscriptions mit `notify_events = 1` (via `get_push_subscriptions_for_events`) versandt. Dasselbe gilt für die manuelle Enthüllung über `POST /api/admin/bummel/races/{id}/reveal` — der Ergebnis-Push wird einmalig und gegated über `push_enabled` an `notify_events`-Abonnenten gesendet.

- **`apply_bummel_overrides(standings, overrides)`** — reine Funktion, wendet die Admin-Overrides aus der `bummel_overrides`-Tabelle auf die berechnete Wertung an. `exclude` entfernt den Piloten vollständig; `disqualify` belässt ihn in der Liste, zieht ihn aber aus Schnitt und Ranking heraus; `winner` setzt Rang 1 erzwungen; `manual` ersetzt `total_min` durch `manual_total_min` und rechnet Schnitt und Ranking neu. Wird von `public_bummel_view` und dem Admin-Preview-Endpoint gleichermaßen aufgerufen — Overrides wirken auf alle öffentlichen Sichten.

**`app/calendar_sync.py` — `parse_route(location, summary, description)`.** Sammelt alle 4-buchstabigen ICAO-Codes aus Ort, Titel und Beschreibung (Reihenfolge erhaltend, dedupliziert) → `route`-CSV. `is_bummel` wird gesetzt, wenn „Bummel" in Titel/Beschreibung steht, die Strecke ≥ 2 Flugplätze hat **und** plausibel ist: `_route_is_plausible` lehnt ab, sobald zwei auflösbare Flugplätze weiter als 600 nm auseinanderliegen (fängt zufällig als ICAO erkannte Wörter ab; reale Bummel-Strecken liegen < 200 nm). `parse_cargo_lines(description)` liest optional eine Fracht-Zeile hinter dem Marker `Fracht:` (kommagetrennt mit Leerzeichen, um Dezimalkommas nicht zu zerreißen) → `[{name, target_kg}]`. `upsert_calendar_transport_event` gleicht diese Namen beim **erstmaligen** Anlegen gegen `cargo_catalog` ab (Emoji/Kappung) und befüllt das Manifest; existiert bereits eines (z. B. vom Admin gepflegt), bleibt es bei erneutem Sync unangetastet.

**FriesenKutter-Fortschritt — Stapel-Modell (`compute_transport_progress` + `app/transport_stacks.py`, Spec `docs/superpowers/specs/2026-07-15-kutter-stapel-modell-design.md`).** Ladung ist ein **Bestand mit einem Ort** („Stapel" je Ladeplatz), kein Attribut eines Legs. Die reine Zustandsmaschine `derive_stacks` (`app/transport_stacks.py`, DB-frei, Vorbild `gps_legs.py`) bekommt das Manifest + eine chronologische Ereignisliste (`login`/`takeoff`/`landing`/`logout`, aus `canonicalize_legs`/Sessions übersetzt von `_stack_inputs`) und liefert, wo welche Ware liegt. Regeln:

- **Laden** ist ein Zustand: wer am **Boden an einem Ladeplatz** steht, nimmt Ware **vom Stapel dieses Platzes** — in Manifest-Reihenfolge (Co-Load), begrenzt durch die freie Kapazität (`aircraft_payloads`, Fallback `transport_default_payload_kg`) und `per_flight_max_kg` (kappt, was AN BORD ist, nicht je Ladevorgang). Der Wartende lädt nach, sobald Ware auf seinen Stapel kommt.
- **Liefern** passiert **sofort bei der Landung am `destination`**: der ganze Flieger-Stapel geht in den Ziel-Stapel. **Kein Latch, kein Disconnect nötig** — genau die Frage, die früher der Live-Ankunfts-Latch beantwortete.
- Was geladen ist, **bleibt an Bord** — auch über Zwischenlandungen an fremden/Wegpunkt-Plätzen (Milchmann/Zwischenstopp); eine Landung ≠ Ziel bewegt nichts.
- **Platzrunden/Stop-and-Go (X→X) tragen die Ware unverändert weiter:** `collapse_same_airport` absorbiert eine Landung am selben Platz in den laufenden Flug (**kein** eigenes `landing`-Event für `derive_stacks`), solange der nächste Start binnen `_GPS_STOP_AND_GO_MAX_SEC` (300 s) folgt — dazwischen wird also **nichts geladen, geliefert oder verloren**, die Bordladung bleibt an Bord bis zur nächsten echten Landung an einem anderen Platz. Die `per_flight_max_kg`-Kappung greift ohnehin auf die **Bordladung**, nicht je Aufsetzer (#63) — Runden über dem eigenen Ladeplatz können die Grenze nicht umgehen.
- **Logout mit Ware an Bord** (auch unfreiwilliger Disconnect) wandert dorthin, wo der Pilot gerade ist: an einem **Ladeplatz** → `returned` (kein Verlust), an einem **fremden Platz** → `stolen`, **in der Luft** → `sunk`.
- **Reine Am-Platz-Rückgabe ist kein Flug (v10.0.2):** Lädt jemand an einem Ladeplatz und legt die Ware ohne einen Meter Flug am **selben Platz** wieder ab (Logout ohne echtes GPS-Leg), erzeugt das **keine Feed-Zeile und keinen Flug** — als Leg zählt nur, was `canonicalize_legs` als echten Track erfasst. Die Buchung ist kg-neutral (die Ware liegt wieder auf ihrem Stapel), der Erhaltungssatz bleibt unberührt; es entfällt lediglich die irreführende `returned`-Bewegung ohne Ortswechsel (`transport_stacks._drop_load` bucht sie weiter auf den Stapel, `compute_transport_progress` unterdrückt nur die Feed-Zeile/den Flugzähler dafür).
- **Erhaltungssatz:** Σ Stapel + Σ Bordladung == Σ Manifest. Ware entsteht nicht und verschwindet nicht; `total_kg` (= Σ Ziel-Stapel) kann den Balken daher nicht überzeichnen (#63) — das ist jetzt **Arithmetik, keine Zusicherung**.

`compute_transport_progress` ruft `derive_stacks` und formt das Ergebnis nur noch in den API-Vertrag: Zahlen kommen direkt aus den Stapeln (`delivered_kg` = Ziel-Stapel, `lost_kg` = STOLEN+SUNK-Stapel, `reserved_kg` = Bordladung), der Feed ordnet die `movements` (`load`/`deliver`/`returned`/`stolen`/`sunk`) je Leg/Session zu. **Eine `returned`-Bewegung wird nur an ein Leg gehängt, das die Ware wirklich getragen hat** (Takeoff-`onboard_kg` > 0, v10.2.3): wer nach der Landung an einem Platz lädt und beim Touchdown-Disconnect dort gleich wieder ablädt, buchte die Rückgabe sonst auf den vorherigen, LEER abgeflogenen Anflug — sichtbar bei mehrdeutiger Herkunft (namensgleiche Ware an zwei Ladeplätzen → `_loss_origin` = None, wo der frühere `origin`-Vergleich leerlief). Die reine Am-Platz-Rückgabe bleibt eine stille Stapel-Buchung ohne Feed-Zeile. **Fracht je Leg = die Bordladung, EINE Quelle (v10.0.5):** Jede fertige Leg-Zeile nimmt ihre `cargo_lines`/`cargo_name`/`onboard_kg` aus `derive_stacks()["carried"]` — der Bordladung beim **Abheben** dieses Legs (Snapshot je `takeoff`-Ereignis, Schlüssel `(cid, takeoff-ts)`), denn zwischen Start und Landung lädt ein Leg nichts nach: `carried_at` IST die Modell-Wahrheit „was trug das Flugzeug auf diesem Leg" (Stapel-Modell, `ladung {cid:{…}}` bleibt an Bord). `delivered_by` liefert nur noch das **Geliefert-Signal** (`delivered = bool(...)`, am Ziel gelandet) — es ist KEINE zweite Frachtquelle: In die Bilanz zählt `tonnage_kg` nur bei `delivered`; ein durchgetragenes Zwischenleg trägt `carried_through=True`/`reserved_kg` und zählt 0. (Bis v10.0.4 war `delivered_by` primär und `carried_at` nur Fallback `if tonnage<=0` — derselbe Sonderfall über sechs Felder verstreut, der ein Zwischenleg „leer" zeigte, Fund Michael 19.07.) Reine Anzeige — Stapel/Bilanz unberührt. Ein Event **ohne** Manifest hat keinen Ziel-Stapel-Inhalt zu füllen und liefert 0 (der frühere „reine kg-Zähler" entfällt). `radius_km`/`skip_open_probe` werden nur noch aus Signatur-Kompatibilität angenommen und **ignoriert** (Anwesenheitsradius global fest, #23; der Freeze braucht keinen Open-Probe-Filter mehr, weil eingefroren erst wird, wenn niemand mehr Ware trägt). Der Feed-Filter ist reine **Sichtbarkeit** (Start ODER Ziel auf der Route, oder Ware an Bord) — er ersetzt den alten Streckenfilter, der BEIDE Enden auf der Route verlangte und deshalb vom Latch aufgehoben werden musste. Der Poller-Job `transport_event_check` latcht Start/Ziel/Feierabend, sendet je einmal einen Push und erzeugt Flug-/Tagesend-Sprüche (`transport_quips`/`summary_quip`). **Der Ziel-Latch (`goal_reached_at`) feuert, sobald `geliefert + verloren ≥ Ziel`** (v10.2.3) — nicht mehr nur `geliefert ≥ Ziel`: ging der Rest unwiederbringlich verloren (STOLEN/SUNK), ist das Manifest trotzdem aufgelöst (nichts liegt mehr auf einem Ladeplatz), der Kutter „schließt" ab und der Push nennt dann die angekommene UND die verlorene Menge. **Der Feierabend-Latch wartet auf Nachzügler:** `transport_anyone_in_progress` bedeutet jetzt **„trägt noch jemand Ware?"** (Σ Flieger-Stapel > 0, Entscheidung 10) — nicht mehr „offener Flug auf der Strecke". Ein leerer Pilot hält den Feierabend nicht mehr auf, ein beladener sehr wohl (auch über `dtend` hinaus).

**Fracht je Startplatz (Entscheidung 6):** jede Manifest-Zeile (`transport_cargo.departure`) bindet an **genau EINEN Startplatz ≠ Ziel, Pflicht** — eine Zeile = ein Stapel = ein Ort. `set_transport_cargo` erzwingt das serverseitig (`ValueError` bei fehlendem/mehrfachem Platz); der „geteilte Topf" (`departure NULL`) und die CSV-Liste entfallen. `transport_events.route` wird beim Speichern aus (allen Cargo-Startplätzen ∪ Ziel) **abgeleitet** (`_derive_route`). Manuelle wie Kalender-Events verlangen Ziel + mind. eine Frachtart mit Startplatz; eine Kalender-`Fracht:`-Zeile ohne ICAO wird abgewiesen statt still geteilt.

**Ersatzlos entfernt (Stapel-Modell):** der Live-Ankunfts-Latch (`transport_live_arrivals`, `set/get_transport_live_arrival(s)`, `check_live_arrival`, `_latch_hits_flight`), die **Reservierung als eigener Mechanismus** (`reserved_alloc` — wer lädt, nimmt vom Stapel, das IST die Reservierung), der Latch-Fallback „unbekanntes `dep` füllt alle Zeilen", die separate **Verlust-Erkennung** (`detect_transport_losses`, `record/get_transport_losses`, Tabelle `transport_cargo_losses`) samt Positions-Klassifikation, `active_transport_destinations` und der Streckenfilter/„geteilte Topf". Verluste kommen jetzt aus `compute_transport_progress` selbst (`losses[]`, `lost_total_kg`, `cargo[].lost_kg`), abgeleitet aus dem STOLEN/SUNK-Stapel. Die Tabellen `transport_live_arrivals`/`transport_cargo_losses` werden **nicht gedroppt** (Altdaten), aber nicht mehr gelesen oder geschrieben.

**Reservierung, Teilnehmer, Verluste (Stapel-Modell).** Eine Reservierung ist kein eigener Topf mehr: **die Bordladung IST die Reservierung.** Ein noch offener Flug mit Ware an Bord erscheint als `in_air`-Zeile, `reserved_kg` = Σ Bordladung, `onboard_reserved_kg` = volle Musterzuladung (für die „belegt / an Bord"-Anzeige); `reserved_total_kg` = Σ aller Flieger-Stapel. **`airborne`** trennt „wirklich abgehoben" (`position == None` im Stapel-Modell) von „am Ladeplatz geparkt" (steht am Boden, lädt schon vom Stapel). `participants` liefert eine Zeile pro Pilot (`cid`, `name`, `callsign`, `aircraft`, `flights`, `delivered_kg`, `reserved_kg` = Bordladung, `lost_kg`, `status`) plus die neuen Sichtbarkeits-/Ort-Felder `visible` (letzter Bodenkontakt an einem teilnehmenden Platz ODER Ladung > 0, Entscheidung 14), `place` (ICAO, an dem er steht; `None` = unterwegs), `last_ground` (letzter Landeplatz) und `cargo_lines` (Bordladung-Aufschlüsselung). Der **`status`** ist eine grobe Kategorie aus **Ort × Ladung** (der Live-Text leitet das Frontend daraus ab, Spec „Der Live-Status = Ort × Ladung"): `flying` (Ware an Bord, in der Luft), `loaded` (Ware an Bord, am Boden), `dabei` (leer in der Luft — macht noch mit), `loading` (leer, steht am Ladeplatz), `standing` (leer, steht am Ziel oder fremden Platz), `done` (Default ohne Feed-Zeile). **`arrived` und `returning` entfallen ersatzlos** — Ankommen ist eine Tatsache im Balken (kein Zustand), und die Richtung eines leeren Fluges wird nicht mehr unterstellt (`returning` → `dabei`). **Verluste** entstehen ohne separate Erkennung: `derive_stacks` bucht die Bordladung beim Logout je nach Ort auf den `returned`-Ladeplatz-Stapel, den STOLEN- oder den SUNK-Stapel (`loss_kind` ∈ `returned`\|`stolen`\|`sunk`). `losses[]` ist die Teilmenge des Feeds mit gesetztem `loss_kind`; `lost_total_kg` = Σ STOLEN+SUNK; `cargo[].lost_kg` zeigt je Frachtart, warum ein Event ggf. <100 % bleibt. `lost_kg` ist **netto** (nur was real an Bord war): `returned` verliert nichts (`lost_kg=0`, zeigt aber seine Bordladung), `stolen`/`sunk` tragen `lost_kg > 0`. **UI-Aufteilung (v7.6.0, Nutzer-Entscheidung):** Der Live-Tab zeigt bei laufendem Event einen Kutter-Block (Analogie Bummel-Banner, 25-s-Poll): Balken + Mengen + „wer ist gerade mit welcher Ladung unterwegs" (Callsign statt Name, 🗺️-Sprung zur Karte via `switchToMapAndCenter`, Teilen + Zum-Kutter-Link); die Events-Ansicht zeigt Balken + Mengen + Flug-Feed.

**Fortschritts-Snapshot + Anzeige-Retention (#66/#67, v8.10.0).** Die beiden Spezial-Event-Listen (`/api/transport/events`, `/api/bummel/races`) riefen bislang bei **jedem** Request für **jedes** Event `canonicalize_legs` live neu auf — Kosten wuchsen linear mit der Anzahl abgeschlossener Events. Da ein abgeschlossenes Event/Rennen sich per Definition nicht mehr ändert, wird sein Ergebnis jetzt **einmal** in `progress_snapshot` eingefroren und danach nur noch gelesen (kein `flight_cache`-artiger Live-Materialisierungs-Job — der würde abgeschlossene Events nach jedem Deploy still neu schreiben).

- **Versions-Gate.** `get_progress_snapshot(conn, kind, ref_id)` liefert das per-Read frisch aus `payload_json` geparste Dict **nur**, wenn die gespeicherte `code_version` der aktuellen Modul-Konstante `_PROGRESS_SNAPSHOT_VERSION` (`app/database.py`, aktuell `"10"` — jede Ausgabe-Änderung von `compute_transport_progress` hebt sie an, zuletzt v10.0.2: eine reine Am-Platz-Rückgabe ist eine stille Buchung, kein Leg/Flug; alte Snapshots gelten als veraltet und werden neu gerechnet) entspricht — sonst `None` (der Eintrag gilt als veraltet und wird beim nächsten Schreiben per PK überschrieben). **Wer den Rechen-Code von `compute_transport_progress`/`compute_bummel_standings`/`_build_race_view` ändert, erhöht diese Konstante im selben Commit** — das ist die einzige „globale Neuberechnung", bewusst ohne Admin-Button/Recompute-Endpoint. `write_progress_snapshot(conn, kind, ref_id, payload, computed_at)` schreibt `INSERT OR REPLACE` und poppt vorsorglich ein evtl. vorhandenes `_conn_logon`-Feld aus jedem `flights`-Eintrag (interne Markierung, darf nie einfrieren). `delete_progress_snapshot`/`delete_progress_snapshots(kind)` invalidieren gezielt bzw. komplett je Typ.
- **Freeze-Zeitpunkt pro Typ.** **Kutter** friert **eager** im Poller ein: `_check_transport_events` (`app/poller.py`) schreibt den Snapshot direkt im `summarized_at`-Latch-Moment (Feierabend, `transport_anyone_in_progress` war `False`) — dabei werden zuvor alle `flights[].in_air`/`airborne` auf `False` normalisiert (ein abgeschlossenes Event hat niemanden mehr „unterwegs"; Tonnage bleibt unverändert). Ein bereits `summarized`-Event überspringt den teuren `compute_transport_progress`-Aufruf komplett — nur noch fehlende Pro-Flug-KI-Sprüche werden aus der `flights`-Liste des Snapshots (billiger Read, kein Compute) nachgesammelt, solange welche fehlen. **Bummel** friert dagegen **lazy** beim ersten Endpoint-Read ein — der Reveal-Poller (`update_bummel_reveals`) baut die View nicht selbst, die lebt in `app/main.py`. Ein Rennen gilt erst als abgeschlossen, wenn **beide** Bedingungen gelten: `revealed_at` gesetzt **und** `now >= dtend` — eine Admin-Notfall-Enthüllung VOR `dtend` (`force_reveal`) friert bewusst NICHT ein (bleibt live, sonst fehlten spätere Legs/Teilnehmer dauerhaft).
- **Gemeinsamer Zugriffs-Helfer (`app/main.py`).** `_frozen_or_compute(conn, kind, ref_id, *, finished, compute_fn, now)` kapselt „eingefroren lesen, sonst einmal rechnen + einfrieren, sonst live rechnen" für beide Typen identisch. `_kutter_progress(conn, ev, now, prefix)` wrappt ihn für Kutter (`finished = bool(ev["summarized_at"])`, `compute_fn` ruft `compute_transport_progress(..., skip_open_probe=finished)`); `_bummel_view(conn, race, now, *, force_reveal=False)` analog für Bummel (`finished = bool(race["revealed_at"]) and now >= (race["dtend"] or "")`, `compute_fn` ruft `_build_race_view(...)`).
- **`skip_open_probe` (`compute_transport_progress`).** Seit dem Stapel-Modell **wirkungslos** — der Parameter wird nur noch aus Signatur-Kompatibilität angenommen und ignoriert (`_kutter_progress` reicht ihn weiter durch). Beide früheren Gründe entfallen: es gibt keinen zweiten `canonicalize_legs`-Aufruf mehr (nur noch einen in `_stack_inputs`), und eine für immer falsche `in_air`-Zeile kann beim Einfrieren nicht mehr entstehen, weil eingefroren erst wird, wenn niemand mehr Ware trägt (`transport_anyone_in_progress`) — und eine `in_air`-Zeile entsteht nur MIT Ware an Bord.
- **Frische Überlagerung beim Read (zeitabhängige/nachlaufende Felder gehören NICHT zur eingefrorenen Identität).** `_kutter_progress` überlagert nach dem Snapshot-Read `summary_quip` (aus `transport_events.summary_quip`) und je Flug den Pro-Flug-`quip` (aus `get_transport_quips`) — beide entstehen erst NACH dem `summarized_at`-Latch (Summary danach, Pro-Flug-Quips async, max. 8/Poll-Lauf) und wären in einem zum Latch-Zeitpunkt geschriebenen Snapshot noch leer. `_bummel_view` überlagert `status` frisch aus `_race_status(race, now)` sowie `name`/`route`/`dtstart`/`dtend` aus der **DB-Zeile**, nicht aus dem eingefrorenen `view` — eine spätere Umbenennung im Admin zeigt sich so sofort in der Liste, ohne den Snapshot zu invalidieren.
- **Invalidierung (bewusste Daten-Änderung, kein Auto-Invalidieren bei Hintergrund-Nachladen).** Kutter: `admin_update_transport_event` löscht den Snapshot **unbedingt**, auch bei leerem Body — ein Event im Admin nur antippen + speichern ist damit der bewusste manuelle Neuberechnungs-Hebel; `admin_delete_transport_event` räumt auf; die globale Payload-/Default-kg-Pflege (`/payloads`, `/default-payload`) löscht **alle** Kutter-Snapshots (`delete_progress_snapshots(conn, "kutter")`). Bummel: Override setzen/löschen, Rennen-Edit (ebenfalls unbedingt), `/hide` und Löschen invalidieren gezielt; `/reveal` braucht kein Delete (es gab noch keinen Snapshot). Kalender-Sync (`upsert_calendar_transport_event`/`upsert_calendar_bummel_race`) invalidiert **nur bei tatsächlicher Wertänderung** von `route`/`dtstart`/`dtend`/`destination` (Kutter) bzw. `route`/`dtstart`/`dtend` (Bummel) — sonst würde jeder 6h-Sync alle Snapshots wegwerfen. Ein nachgetragener `custom_airports`-Eintrag oder ein verspätet nachgeladener StatSim-Track invalidiert **nicht** automatisch (bewusster Randfall) — wer das will, tippt das Event/Rennen im Admin an und speichert.
- **`_DATA_RETENTION_DAYS = 365` — reine Anzeige-/Eingabegrenze (#67, global über alle zeitgefensterten Flächen).** **Wichtig: der tägliche `position_history`-Cleanup ist deaktiviert** (`Poller._daily_cleanup` ist auskommentiert, `poller.py`) — die Rohdaten bleiben dauerhaft in der DB; 365 Tage ist ausschließlich eine Anzeige-/Suchgrenze, nichts wird gelöscht. Angewandt wird sie an vier Stellen: (1) `list_transport_events`/`list_bummel_races` akzeptieren `since: str | None` und filtern mit gesetztem `since` `WHERE (dtend IS NULL OR dtend >= ?)` (NULL-Guard für Altbestände) — nur die **öffentlichen** Listen-Endpoints (`/api/transport/events`, `/api/bummel/races`) übergeben `since = now − 365 Tage` (`_retention_since(now)`), Poller und Admin-Listen weiter `since=None`. (2) `/api/stats` + `/api/stats/activity`: `days` wird über `_clamp_retention_days(days)` auf `1…365` geklemmt (Sicherheitsnetz gegen URL-Manipulation; das UI bietet ohnehin nur 30/90/365). (3) `/api/pilots/{cid}/flights`: das Anzeigefenster wird ebenfalls auf 365 geklemmt, `days=0` („letztes Jahr") ergibt genau 365 Tage statt des früheren ungekappten 99999-Tage-Fensters. (4) `/api/events`: `_clamp_retention_start(start, now)` hebt einen leeren/älteren `start` auf `now − 365 Tage` an; das Frontend setzt zusätzlich `min` an den `datetime-local`-Feldern + Hinweis „Nur die letzten 365 Tage sind durchsuchbar.". `/api/stats/special-events` ist über seine `{30,90,365}`-Whitelist bereits konsistent (und aggregiert ohnehin aus Snapshots, nicht aus `position_history`).

**Aggregierte KPI-Statistiken (v8.11.0, #64).** `aggregate_kutter_kpis`/`aggregate_bummel_kpis` (`app/database.py`, rein) summieren die fertigen Snapshot-/Progress-Dicts; der Endpoint `GET /api/stats/special-events` (`app/main.py`) iteriert nur abgeschlossene Events/Rennen im Zeitfenster über `_kutter_progress`/`_bummel_view` (Snapshot-Reuse, kein `canonicalize_legs`).

### `app/llm.py`

Schlanke Claude-API-Anbindung (offizielles `anthropic`-SDK) mit **Silent-Fail**: `suggest_aircraft_payload(type_code)` (Modell `claude-haiku-4-5` seit v7.4.2, ~4 ct/Recherche; Haiku lehnt den `effort`-Parameter ab — `output_config` nur mit `format`) **recherchiert per Web-Search** (serverseitiges `web_search`-Tool, `max_uses=3`) die dokumentierten Handbuch-/POH-Werte und liefert sie als Structured Output (`output_config.format`, Server-Tool-Loop über `pause_turn`). **Bewusst die Basis-Tool-Variante `web_search_20250305` + Streaming + `max_retries=0`** (v7.4.1): das neuere `web_search_20260209` (Dynamic Filtering) ließ das Modell die Suchergebnisse in `code_execution`-Runden à 30–95 s nachbearbeiten — ein PZ04-Request lief >9 min und riss den 120-s-Client-Timeout, dessen stille SDK-Retries jeden abgebrochenen Versuch trotzdem voll bezahlten (Live-Messung 2026-07-02: 185 Web-Suchen/6,4 M Input-Tokens ≈ 14 $ in zwei Tagen; mit Basis-Tool: 16 s, ~0,07 $ pro Recherche). Rückgabe: make_model, MTOW, Leergewicht, volle Tanks als Maximum (`fuel_full_kg`) + halbe Füllung als Default (`fuel_kg`), Crew (85 kg) und die abgeleitete Zuladung `max(0, mtow−empty−fuel_halb−crew)`. Die reine Rechnung steckt in `_build_result` (testbar ohne API). Ohne `ANTHROPIC_API_KEY` (mit TSBot geteilt) oder ohne `anthropic`-Paket → `None`, der Rest bleibt manuell pflegbar. Dauer ~30 s (Web-Recherche). **Lustige KI-Sprüche (Phase 2):** `flight_quip(context)` und `event_summary(context)` — Sonnet 5 ohne Web-Search (Denken aus, effort low, ~4–8 s), Persona „Bordfunker im Friesen-Humor". Der Kontext (Vorname, Fleiß, Tempo, Umweg) kommt aus `database.flight_quip_context`/`event_summary_context` (rein, testbar). **`tonnage_kg` = Bordladung, nicht Netto-Gutschrift (v8.8.3/#67).** Bei einem Verlust (versunken/geklaut) ist die Netto-Gutschrift (`flight["tonnage_kg"]`) IMMER 0 — trotzdem war weiterhin Fracht an Bord (`cargo_lines`). Beide Werte unverändert gleichzeitig in den Prompt zu geben erzeugte widersprüchliche Sprüche („220 kg ... Zuladung: 0 Kilo", Live-Fund 06.07.). `flight_quip_context` leitet die im Prompt gezeigte „Zuladung" daher aus der Summe von `cargo_lines` ab (`onboard_kg`) statt aus `flight["tonnage_kg"]` direkt — bei normalen Lieferungen identisch (beide stammen aus derselben Co-Load-Verteilung), bei Verlusten zeigt es die tatsächlich mitgeführte Fracht. **Tagesend-Spruch ignorierte Verluste (v8.8.4, Live-Fund 06.07.).** `event_summary_context` (database.py) berechnete `lost_total_kg`/`verluste` zwar korrekt, aber `event_summary()` übernahm diese Felder nie in den Prompt-Text — die KI wusste dadurch nichts von Verlusten und konnte unwidersprochen Sätze wie „niemand versunken" erfinden, obwohl tatsächlich Fracht versunken/gestohlen wurde. Der Prompt enthält jetzt immer eine explizite Verlust-Zeile (Details bei Verlusten, sonst „keine — alles kam heil an") plus die Anweisung, Verluste zwingend zu nennen und Vollständigkeit nicht vorzutäuschen. **Einzelflug-Spruch griff Verluste nicht auf (v8.8.6, gleicher #67-Fehlertyp).** `flight_quip_context` liefert bereits ein Feld `verlust` (versunken/geklaut/zurückgebracht), aber `flight_quip()` übernahm es nie in den Prompt → ein geklauter/versunkener Flug bekam trotzdem einen fröhlichen Liefer-Spruch. Bei gesetztem `verlust` schaltet `flight_quip()` jetzt auf einen eigenen Prompt um, der den Verlust zwingend aufgreift und Auslieferungs-Formulierungen verbietet. **Ton (v8.8.7):** dieser Verlust-Prompt ist bewusst frech-spitzbübisch — ein Dieb wird augenzwinkernd zum Spitzbub auf Kaperfahrt, ein versunkener Kutter bekommt eine konkrete Nordsee-Szene mit der jeweiligen Fracht (nie der Pilot geht unter, immer der Kutter) — deftiger Nordton erlaubt, aber weiter ohne übersetzungsbedürftige Platt-Wörter (#14). **Sprüche neu generieren:** `clear_transport_quips(conn, event_id)` löscht die gecachten Flug-Sprüche eines Events und setzt `summary_quip` zurück; der Poller baut sie beim nächsten Durchlauf neu (Bedingung dort: `not f.get("quip")`). Ausgelöst über `POST /api/admin/transport/events/{id}/regenerate-quips` (Admin-Knopf „🔄 Sprüche neu" je Event) — nötig, wenn die Spruch-Logik sich ändert und bereits gecachte Sprüche veraltet sind.

### `app/poller.py`

`VatsimPoller` kapselt:
- **APScheduler `AsyncIOScheduler`** mit bis zu zehn aktiven Jobs: `vatsim_poll` (interval, 15s), `calendar_sync` (interval, 6h — lädt FriesenFlieger-Google-Kalender), `calendar_sync_initial` (date, einmalig beim Start), `bummel_reveal_check` (interval, 60s — ruft `update_bummel_starts` (Start-Latch + Start-Push) und `update_bummel_reveals` (Enthüllungs-Latch + Enthüllungs-Push) auf; beide Pushs nur an `notify_events`-Abonnenten via `get_push_subscriptions_for_events`), `transport_event_check` (interval, 60s — latcht FriesenKutter Start/Ziel/Feierabend, s. u.), `event_reminder_check` (interval, 5min — ruft `events_due_for_reminder` auf, sendet für jedes fällige Event einmalig einen Push an `get_push_subscriptions_for_events` und latcht via `mark_event_reminded`), `flight_cache_warmup` (date, einmalig kurz nach Start — voller `rebuild_flight_cache`-Rebuild via `asyncio.to_thread`, ~5,5 s), `flight_cache_refresh` (interval, 5min — inkrementeller `rebuild_flight_cache`, ~0,5 s), `statsim_track_fetch` (interval, 10min — Phase 2b: proaktives StatSim-GPS-Track-Nachladen in kleinen Batches, s. „GPS-Leg-Erkennung" oben), sowie optional `ts_poll` (interval, `TS_POLL_INTERVAL`s) wenn `TS_NOTIFY_ENABLED=true`. Der `ts_poll`-Job ist **von VAPID entkoppelt** — er läuft für die Live-Anzeige auch ohne VAPID; ohne VAPID werden lediglich keine TS-Push-Benachrichtigungen versandt. `daily_cleanup` ist deaktiviert — `position_history` wird dauerhaft behalten.
- **`_active_flights: dict[int, dict]`** — In-Memory State: CID → `{"id": flight_id, "dep": departure, "arr": arrival}`. Wird beim Start in `PollerService.start()` aus der DB **rehydriert** (alle offenen Flüge `logoff_time IS NULL AND superseded_by IS NULL`), sodass ein Container-Neustart laufende Flüge adoptiert: Pilot noch online → `still_online` (kein neuer Flug); inzwischen offline → `went_offline` → korrekt geschlossen (kein Zombie). **Flugende:** Beim Offline-Gehen wird als `logoff_time` die letzte gespeicherte Position verwendet (nicht die Wanduhr). **Flugplanwechsel ohne Disconnect:** gleicher Abflughafen → `update_flight_plan` (selbes Leg); **geänderter** Abflughafen → echtes neues Leg (Pilot gelandet, neu gefiled) → altes Segment schließen, neues mit eindeutiger Mikrosekunden-`logon_time` öffnen (kollidiert nie mit dem Unique-Index).
- **`_sse_subscribers: set[asyncio.Queue]` (Per-Client-Fan-out)** — Jede SSE-Verbindung registriert über `subscribe_sse()` ihre **eigene** beschränkte Queue (`_SSE_QUEUE_MAXSIZE=50`) und deregistriert sie beim Disconnect über `unsubscribe_sse()` (im `finally` des Generators). `broadcast_sse(msg)` verteilt jedes Update an **alle** Queues (Iteration über Snapshot, `put_nowait`, non-blocking); bei voller Queue wird der älteste Eintrag verworfen (Drop-Oldest). So bekommt **jeder** Client jedes Update — früher teilten sich alle Clients **eine** Queue, sodass jede Nachricht nur **einen** Consumer erreichte. Der maxsize-Deckel begrenzt zugleich den serverseitigen Rückstau für einen gedrosselten Hintergrund-Tab.
- **`last_prefiles: list`** — aktuell eingereichte VATSIM-Prefile-Pläne mit FRS*-Callsign (In-Memory, aus dem letzten Poll-Zyklus)
- **`ts_clients: list[dict]`** — letzter TS-Poll-Snapshot der FRS-getaggten Clients (intern `{frs, nick, cid}`), In-Memory. Speist `/api/teamspeak` (Live-Tab-Panel) und den `/widget`-Zähler — **nach außen wird bewusst nur `frs` ausgegeben** (Klarnamen/Nick-Zusätze bleiben serverseitig). Bleibt bei `None`-Abruf (TS nicht erreichbar) unverändert.
- **`_prefile_sigs: dict | None`** — CID → `(deptime, departure, arrival)` für Änderungserkennung. Wird beim Start aus `prefile_sigs`-DB-Tabelle geladen (nicht `None`) und nach jedem Poll gespeichert. Beim allerersten Start ohne DB-Einträge ist die Dict leer — keine Spam-Notifications. Container-Neustarts verpassen dadurch keine Prefile-Änderungen mehr.

**`send_web_push(vapid_private_key, vapid_contact_email, db_path, subscriptions, payload, label)`** — generischer WebPush-Kern, der von VATSIM-Online- und TS-Notifications gemeinsam genutzt wird. Führt für jede Subscription einen Send-Versuch aus (1× Retry nach 5 s), loggt Fehler, löscht 410-Endpoints aus der DB — **sowie 403-Endpoints mit VAPID-Mismatch-Body** (`"do not correspond"`, d. h. mit alten VAPID-Keys angelegte, nie zustellbare Subscriptions; Client re-registriert beim nächsten Besuch). Derselbe 403-Cleanup gilt im Inline-Loop von `send_prefile_push_notifications`.

**`_poll_teamspeak()`** — TS-Job (Live-Anzeige + Verweildauer-/Streak-Benachrichtigung):
1. `fetch_channel_clients` aufrufen → `None` bei Fehler (Poll überspringen, **Snapshot bleibt erhalten**); `[]` ist ein gültig leerer Kanal
1a. Erfolgreicher Abruf → `self.ts_clients = clients` (Anzeige-Snapshot, **vor** der Notify-Logik). Ist kein VAPID gesetzt, endet der Poll hier (reiner Display-Modus, keine Benachrichtigung)
2. Erster erfolgreicher Poll: Baseline — präsente FRS in `_ts_streak` mit `_TS_BASELINE_STREAK` (sehr hoch) markieren, sodass sie die Schwelle nie treffen → keine Notifications
3. Präsenz-Streak: je präsenter FRS `_ts_streak[frs] += 1`; abwesende FRS fallen aus dem Dict (Reset). Bestätigt = Streak erreicht erstmals `TS_MIN_DWELL_POLLS + 1` → erst dann Kandidat. Kurzes „Reinschauen" (vor dem Folge-Poll weg) erreicht die Schwelle nie.
4. Pro bestätigter FRS: Debounce prüfen (`_ts_last_notified`, `TS_REJOIN_DEBOUNCE_SEC`); `subject_cid = cid_for_callsign_authoritative(frs)` (Forum-Map vor flights/live/statsim); `get_ts_push_subscriptions(conn, subject_cid)` (notify_ts=1, gefiltert über denselben `pilot_filter` wie Online/Flugplan; `cid is None` → nur „Alle"-Subs); dann `visible_recipients(conn, subject_cid, …)` (Subjekt-Sichtbarkeit); `send_web_push` als asyncio-Task starten

**Prefile Push-Notification-Logik:**
- `_prefile_sig(p)` → `(deptime, departure, arrival)` — Änderungssignatur
- Neuer oder geänderter Prefile → `asyncio.create_task(send_prefile_push_notifications(...))`
- Unterdrückt wenn CID bereits in `_active_flights` (Pilot online — kein Prefile-Alert nötig)
- Nur an Subscriptions mit `notify_prefiles = 1` (Filter in `get_push_subscriptions_for_prefile`)
- **Nicht rückwirkend:** Ein Push entsteht nur in dem Poll, in dem der Prefile neu auftaucht oder
  sich die Signatur ändert. Ein bereits vorhandener Prefile löst beim nachträglichen Abonnieren
  keine Benachrichtigung aus.

Die Flug-State-Machine in `_poll_once`:

```
CIDs jetzt online: {A, B, C}
CIDs vorher aktiv: {B, C, D}

newly_online  = {A}       → open_flight, Alert
still_online  = {B, C}    → update position + Flugplan-Check
went_offline  = {D}       → close_flight
```

**Typ-Fallback ohne Flugplan** (vatsim-radar-Prinzip): der öffentliche Feed führt den Flugzeugtyp nur im `flight_plan`. Piloten ohne Plan bekommen ihr Muster aus dem **Prefile** (falls vorhanden) — **kein** Fallback mehr auf frühere eigene Flüge (`last_known_aircraft` war zeitlich blind, lieferte teils den GLOBAL neuesten gefileten Typ aus der Zukunft des Legs, und wurde in v8.5.0/#52 ersatzlos entfernt); ohne Plan/Prefile bleibt der Typ ehrlich leer statt geraten. `aircraft_short`/`aircraft_icao` werden zentral pro Poll-Takt normalisiert (v8.5.0/#51, `normalize_type_code`), bevor sie in `open_flight`/`update_flight_plan` geschrieben werden. **Nachtrag bei laufendem Flug (v8.6.0/#54):** `update_flight_plan()` schreibt `aircraft_short` jetzt mit (`COALESCE(NULLIF(?, ''), aircraft_short)` — ein Plan-Update ohne bekannten Typ löscht nie einen bereits gesetzten); vorher blieb ein ohne Typ eröffnetes Leg dauerhaft ohne `aircraft_short`, selbst wenn ein später eintreffender Plan (`aircraft_icao`) den Typ längst kannte. Zusätzlich stößt der Poller für **neu gesehene, ungepflegte Typcodes** automatisch die Zuladungs-Recherche an (`_auto_research_payload`, `source='llm'`, einmal je Prozess-Lebensdauer; manuell gepflegte Typen werden nie überschrieben).

**Feed-Aussetzer-Robustheit:** Fehlt ein Pilot für eine Poll-Runde im VATSIM-Feed (Feed-Glitch), greift `went_offline` → `close_flight`. Taucht er in der nächsten Runde mit **derselben `logon_time`** wieder auf, beweist das, dass die Verbindung nie abriss — `open_flight` **re-öffnet** dann die geschlossene Zeile (`logoff_time = NULL`, duration/distance/block werden beim echten Close neu berechnet), statt gegen eine geschlossene Zeile weiterzulaufen. Ohne dieses Reopen verwaisten alle Folgeflüge der Session (nur `position_history` lief weiter — Live-Test 2026-07-01, cid 1031301).

**Online-Reconnect-Debounce:** Im `newly_online`-Zweig wird die Benachrichtigung (Telegram + WebPush) nur ausgelöst, wenn der Pilot nicht innerhalb von `VATSIM_REJOIN_DEBOUNCE_SEC` (Default 900 s) zuletzt schon gemeldet wurde (`_online_last_notified[cid]`). So erzeugt ein vPilot-Reconnect (offline → kurz darauf wieder `newly_online`) keinen zweiten „ist online!"-Ping. DB-/State-Logik (`open_flight`, `upsert_live_position`, `_active_flights`) läuft unabhängig weiter — nur das Versenden wird gedämpft.

**Flugplan-Änderungserkennung** (für `still_online`-Piloten): Pro Poll wird der aktuelle DEP/ARR aus dem VATSIM-Feed mit dem in `_active_flights` gespeicherten verglichen. Bei Abweichung:
- **Kein alter Plan → neuer Plan**: `update_flight_plan()` setzt DEP/ARR und alle Flugplan-Felder (Route, Remarks, Altitude, TAS, Flight Rules, Aircraft ICAO, Alternate, Off Block, Enroute, Fuel) im laufenden Flug-Record nach.
- **Alter Plan → anderer Plan**: laufenden Flug sofort schließen (`close_flight`), neues Segment öffnen (`open_flight`) mit allen Feldern des neuen Plans. Behandelt Fälle wie Zwischenstopps oder Planänderung nach dem Start.

Ein einziges `conn.commit()` am Ende — kein partieller Schreibzustand möglich.

**Kutter-Status, leeres Event & 3-Quellen-Erinnerung (v7.8.0):**
- `_transport_status(ev, now)` (`app/main.py`) liefert `scheduled` \| `running` \| `waiting` \| `done` — analog `_race_status` beim Bummel (`summarized_at` gesetzt → `done`; `now < dtstart` → `scheduled`; `now < dtend` → `running`; sonst `waiting` = `dtend` erreicht, Feierabend-Latch aber noch offen, z. B. Nachzügler in der Luft). Fließt nur ins `status`-Feld von `GET /api/admin/transport/events` — kein Piloten-Frontend-Feld.
- `_check_transport_events` (`app/poller.py`) wrapt den Feierabend-Block (Zusammenfassungstext, optionaler KI-Aufruf, Push) jetzt in `progress["flight_count"] > 0`. Der `summarized_at`-Latch selbst wird weiterhin **unbedingt** gesetzt (Event bleibt abgeschlossen), aber ein komplett leeres Event verschickt keinen „0 Frachtflüge"-Push mehr und löst keinen bezahlten Claude-Aufruf mehr aus. Start- und Ziel-Push sind davon unberührt.
- `_check_event_reminders` (`app/poller.py`) speist die ~1h-Erinnerung jetzt aus drei Quellen: `events_due_for_reminder` (generische Kalender-Events; schließt `is_bummel`/`is_transport` aus), `bummel_races_due_for_reminder` und `transport_events_due_for_reminder` (beide manuell + Kalender, `push_enabled`-gated). Dedup läuft über synthetische Keys `bummel:{id}` / `kutter:{id}` in der bestehenden `event_reminders_sent`-Tabelle (`uid` ist reiner Text, kein Fremdschlüssel — kein Schema-Umbau nötig).
- **Boden-Beladung GPS-only (v8.22.0, #5):** Der Login-Ort eines Piloten (der `login`-Event-`airport`, den `derive_stacks` als Standort verbucht) wird in `_stack_inputs` **rein aus GPS** bestimmt, kein Flugplan-Fallback: kennt das erste GPS-Leg der Session einen `gps_departure`, gilt der; sonst die **aktuelle** Live-Position (`_current_pos` → `live_positions`, am Boden `groundspeed < _BLOCK_GS_KT`), sonst die erste Position der Session (`_first_pos`-Muster). Liegt der Platz nicht in der Route (≠ Ziel), gilt der Pilot als in der Luft/anderswo eingeloggt (unsichtbar) — ein alter Plan verortet nie falsch. Wer am Boden an einem Ladeplatz steht, lädt sofort vom Stapel; das Frontend zeigt ihn als „🅿️ lädt in <Platz>". Ein zurückgekehrter Pilot, der an einem Ladeplatz landet, erscheint dadurch mit `status: loading` („lädt", bereit für die nächste Runde) — den früheren `returning`-Status gibt es nicht mehr (der #65-Bug bleibt behoben).

### `app/fse.py`

Hält den FSE-Weltbestand (23.780 Plätze + Landeflächen aus dem FSE-Planner) im Speicher und
schneidet den Kartenausschnitt heraus. Einmal beim Start gelesen (`lifespan`), danach nur
gelesen — deshalb ohne Sperre. Speist `/api/fse/airports` und `/api/fse/zones`.

**Speicher:** **49,7 MB** dauerhaft (Container 141 → ~191 MB), Ladezeit 0,5 s. Der Wert hängt
an einer einzigen Bedingung: `_auf_einen_zweig` reicht unveränderte Punktlisten durch, statt
sie neu zu bauen. Ein bedingungsloser Neubau erzeugt 23.780 frische Listenstrukturen,
während die Rohdaten noch leben, und kostet **70,7 MB** — 21 MB für zwei geänderte Zonen
(Review-Fund 16.08.2026; ein Identitätstest hält es fest). Erwogen und **gemessen
verworfen** war, die Zonen als vorserialisierte JSON-Zeichenketten zu halten: `json.load` baut
die Listenstruktur ohnehin, bevor irgendetwas daraus abgeleitet werden kann, die Zeichenketten
kämen also obendrauf — und der freigegebene Listenspeicher geht nicht ans Betriebssystem
zurück (mit `malloc_trim` gegengeprüft). Gemessen 55,3 statt 50,8 MB, also 4,5 MB **teurer**.

**Kartenfenster:** Die Panel-Selbstdiagnose meldet aus dem MSFS **440 × 620 px**
(Halbdiagonale 380 px), ein Desktop-Browser eher 900 × 700 (570 px). Dieselbe Zoomstufe deckt
im Kniebrett also nur rund zwei Drittel der Strecke ab — dort kommen weniger Objekte an
(z10 über Wangerooge: 7 Plätze statt 14), dafür füllt der 250-km-Deckel auf z6 nur 36 % des
Bildes. Wer Zoomstufen in Kilometer umrechnet, muss sagen, für welches Fenster.

**Deckel in Punkten, nicht in Stück** (`MAX_PUNKTE_PLAETZE = 250`, `MAX_PUNKTE_ZONEN = 900`):
Ein Platz ist ein `CircleMarker` mit 1 Punkt, eine Zone ein Polygon mit im Mittel 7 (max 21).
Bei New York stellen die Zonen 88 % der Zeichenlast — ein Stückzahl-Deckel schonte die falsche
Ebene. Die Werte sind gegen Coherent GT gewählt (s. `main.py`: „ab ein paar hundert Elementen
zäh") und stehen zur Korrektur, sobald die Panel-Selbstdiagnose Canvas misst (Feld `canvas`).

**Zonen sortieren nach dem Abstand des Bezugspunkts zu ihrer Bounding-Box.** Zwei
Entscheidungen stecken darin:

- Gemessen wird vom **Punkt**, nicht vom Ausschnitts-**Rechteck**: gegen das Rechteck hätte
  jede schneidende Zone Abstand 0 (bei New York 389 Stück), und der Deckel entschiede zwischen
  ihnen alphabetisch — die Zelle, in der man steht, fiel dabei nachweislich heraus.
- Gemessen wird zur **Bbox**, nicht zur Position des Flugplatzes. Die ursprüngliche Begründung
  („sonst fiele die Zelle heraus, in der man steht") war **falsch** und wurde am 16.08.2026 im
  Review widerlegt: Die Zonen sind Voronoi-Zellen, die umschließende gehört per Definition dem
  nächstgelegenen Flugplatz und stünde auch nach Flugplatzentfernung ganz vorn (131 von 131
  geprüften Punkten). Der echte Grund: Die Bbox hält auch die großen **Nachbar**zellen im Bild,
  deren Flugplatz weit außerhalb liegt — über dem Ozean gerade die, die die graue Kulisse
  lückenlos machen.

**Zwei Zonen werden beim Laden verworfen:** `CYLT` (Alert) und `NZPG` (McMurdo) umschließen je
einen Pol — ihre Ecken laufen einmal um die Erde, ein solcher Ring hat in Länge/Breite keine
nahtfreie Darstellung. Erkannt datengetrieben (Längenspanne > 180° nach Zweig-Korrektur), nicht
über eine ICAO-Liste. Die übrigen 34 Zonen mit Koordinaten jenseits ±180 sind **durchgehend**
(`NFNA` 175,98 → 181,65) und bleiben unangetastet: pauschales Normalisieren machte aus genau
ihnen die Bänder, die hier vermieden werden.

**Bekannter Rest:** Das Abfragefenster rechnet nicht über die Datumsgrenze — bei Länge 179,5
fällt alles westlich von −180 weg. Betroffen sind 14 der 23.780 Plätze (Fiji, Neuseeland,
Marshallinseln, Aleuten). Nutzer-Entscheidung 16.08.2026: nicht in dieser Umstellung.

### `app/geo.py`

- `haversine(lat1, lon1, lat2, lon2)` — Großkreis-Abstand in km
- `icao_to_coords(icao)` / `airport_elevation_ft(icao)` — ICAO → (lat, lon) bzw. Höhe (ft). Seit v8.6.0/#56 wird `_CUSTOM_AIRPORTS` ZUERST geprüft (Override), erst danach `airportsdata` (keine Netzwerk-Anfrage, statische Daten) — vorher (#50) war die Reihenfolge umgekehrt (reiner Fallback für gänzlich fehlende Codes).
- `nearest_airport_icao(lat, lon, max_km)` / `nearest_airport_icao_fast(lat, lon, max_km)` — nächstgelegener Flugplatz im Umkreis. Überspringen beim `airportsdata`-Scan jeden Code, der in `_CUSTOM_AIRPORTS` steckt (`icao in _CUSTOM_AIRPORTS`) — sonst würde eine falsche `airportsdata`-Position (Fund: EBUL) weiter konkurrieren, statt vollständig von der korrekten Custom-Position verdrängt zu werden. Custom wird danach linear nachgeprüft (Distanz-Gleichstand gewinnt Custom). Seit v8.7.0/#62 zählt dabei pro Custom-Code ein eigener `radius_km` statt des übergebenen `max_km`, wenn gesetzt (`None` = unverändert `max_km`) — ein Kandidat mit größerem eigenen Radius ist auch jenseits von `max_km` zulässig, gewinnt aber weiterhin nur bei kürzerer Distanz als der bisher beste Treffer (Fund: EHAM/Schiphol, s. Tabelle oben).
- `filter_event_pilots(rows, icao_list, radius_km, start_utc, end_utc)` — filtert `position_history`-Zeilen auf Piloten die im Zeitfenster innerhalb von `radius_km` um einen der ICAOs waren (liefert nur die cid-Menge; die Flug-Dicts selbst kommen seit v8.3.0 aus `canonicalize_legs`, s. u.)

### `app/teamspeak.py`

TeamSpeak-ServerQuery-Client für die TS-Login-Benachrichtigung (Phase 1). Baut pro Poll eine kurzlebige ServerQuery-Verbindung auf (kein dauerhafter Event-Thread, kein TS-Client-Prozess).

- `parse_frs(nick)` — extrahiert die FRS-Nummer aus einem TS-Nickname via Regex (`FRS[\s_-]*(\d+N?)`; optionale Trennzeichen zwischen `FRS` und Zahl, sodass auch `FRS 144`/`FRS-144` erkannt werden; einziges erlaubtes Suffix ist das optionale `N`, z. B. `FRS13N`). Der Tag wird **normalisiert ohne Trennzeichen** zurückgegeben (`FRS 144` → `FRS144`), oder `None` wenn kein FRS-Tag gefunden wird. Portiert aus TSBot.
- `_parse_clientlist(clients, channel_id)` — filtert die rohe ts3-clientlist: nur echte Clients (`client_type == "0"`), nur im Zielkanal (channel_id 0 = ganzer Server), nur Clients mit FRS-Tag. Gibt `[{frs, nick, cid}]` zurück.
- `fetch_channel_clients(*, host, port, user, password, server_id, channel_id)` — async Wrapper: führt `_fetch_clients_sync` (login → use → clientlist → close) per `run_in_executor` aus. Gibt `None` bei Fehler zurück (kein Crash), damit der Caller zwischen nicht-erreichbarem Server (`None`) und echtem leeren Kanal (`[]`) unterscheiden kann.

### Empfänger-Auswahl (einheitlich, `app/database.py`)

Online, Flugplan und TS nutzen denselben empfängerseitigen `pilot_filter` (CID-Liste je Subscription; `NULL` = alle). Selbst-Ausschluss = eigenen CID weglassen (Modus „Nur bestimmte"). Es gibt kein separates `recipients_for` mehr.

- `cid_for_callsign(conn, callsign)` — mappt eine FRS/Callsign (z. B. `FRS49`) auf die CID (Quelle: `live_positions` → jüngster `flights` → `statsim_cache`), oder `None` für reine TS-Leute ohne VATSIM-Flug.
- `get_ts_push_subscriptions(conn, cid)` — TS-Opt-in-Subscriptions (`notify_ts = 1`), gefiltert über `pilot_filter` (NULL = alle; sonst nur wenn `cid` enthalten; `cid is None` → nur NULL-Filter). Spiegelt die Logik von `get_push_subscriptions_for_pilot`.
- `get_push_subscriptions_for_events(conn)` — Gibt alle Push-Subscriptions mit `notify_events = 1` zurück (ohne Pilot-Filter, da Event-Erinnerungen und Bummel-Benachrichtigungen pilot-unabhängig sind). Wird vom Poller für `event_reminder_check` sowie für Bummel-Start- und Enthüllungs-Push genutzt.
- `get_push_subscription_by_endpoint(conn, endpoint)` — Gibt genau **eine** Subscription anhand ihres Endpoints zurück (oder `None`). Genutzt vom Admin-Test-Push (`POST /api/admin/push/test`), um ausschließlich ans eigene Gerät zu senden.
- `get_all_push_subscriptions(conn)` — alle Subscriptions ungefiltert; genutzt vom Admin-Broadcast (`POST /api/admin/push/broadcast`, `audience = all`).
- `events_due_for_reminder(conn)` — Gibt alle Kalender-Events zurück, deren `dtstart` im Fenster `(jetzt, jetzt+60min]` liegt und für die in `event_reminders_sent` noch kein Eintrag existiert. Vergangene Events werden nicht mehr zurückgegeben.
- `mark_event_reminded(conn, uid)` — Schreibt einen Eintrag in `event_reminders_sent` (`uid` + `sent_at = now()`). `INSERT OR IGNORE` — idempotenter Latch.
- **Subjekt-Sichtbarkeit** (`pilot_visibility`, Modi `everyone`/`allowlist`/`nobody`) wird über den Helfer `visible_recipients(conn, subject_cid, recipients)` in **allen drei** Push-Pfaden (Online/Flugplan/TS) sowie am Telegram-Online-Kanal (`everyone` → Alert) vorgeschaltet. `nobody` → leer; `allowlist` → nur Empfänger, deren `owner_cid` in der Liste steht (Alt-Abos ohne Owner nie). 

### `app/badge.py`

Serverseitiges Badge-Rendering mit **Pillow** für Forensignaturen nach einem FriesenFliegerBummel bzw. FriesenKutter-Event. Alle Badges sind **rund (256 px)** mit transparenten Rändern und nutzen die FriesenFlieger-Markenhintergründe aus `app/static/badge/` (`winner_bg.png` / `medal_bg.png` — Flugzeug, ostfriesische Inselkette, Vereinsfarben aus dem Repaint-Kit). Der Text wird zentriert in die ruhigen Zonen gelegt, strikt in der FF-Palette (Navy `#191D53`, Hellblau `#8FBFF1`, Rot `#8A1B1B`, Orange `#D75F28`).

- **`render_winner_badge(d: dict)`** — Sieger-Badge „Absoluter Durchschnitt!" (helle Kuppel, dunkle Schrift) mit Callsign, Name, Flugzeugmuster, Block-Gesamtzeit und Abstand zum Schnitt; **Event-Name als Überschrift** (unter der Inselkette) und **Datum**; Fußzeile „friesenflieger.de".
- **`render_medal(d: dict)`** — Medaille „Voll daneben!" (navy Kern, helle Schrift) für alle anderen Teilnehmer (auch unvollständige), mit Flugzeugmuster, **Event-Name** und **Datum** sowie (bei kompletter Tour) dem Abstand zum Schnitt; Fußzeile „friesenflieger.de".
- **`render_kutter_badge(d: dict)`** — Kutter-Abschluss-Badge „Voll beladen!" (navy Kern wie `render_medal`) mit Callsign, Flugzeugmuster, Event-Name + Datum. **Team-Tonnage (v8.8.1/#64):** direkt unter dem Muster steht `_fmt_team_kg(team_total_kg, team_target_kg)` — die GESAMTE Team-Leistung des Events (z. B. „1610 / 2810 kg Team"), nicht nur der Anteil dieses einen Piloten (Name entfällt bewusst). Hat ein Teilnehmer Fracht verloren, ergänzt ein Verlust-Abschnitt einen Titel (`_kutter_loss_label(stolen_kg, sunk_kg)`: **SPITZBOOV!** nur geklaut, **BADEMESTER!** nur versenkt, **SEEROVER!** beides, `None` bei keinem Verlust — pure Funktion, direkt testbar) plus eine Mengen-Zeile (z. B. „150 kg geklaut, 292 kg versenkt", ASCII-Komma). Datum/Fußzeile sitzen enger zusammen als beim Bummel-Badge (`_kutter_event_heading(..., date_y=0.800)`, `_footer(..., y_frac=0.838)`) — der ursprüngliche Abstand ließ „friesenflieger.de" in den unteren Ring der Kreisgrafik hineinlaufen.

Alle Badges tragen **Event-Name und Datum**. Der Abstand zum Schnitt (Bummel) wird signiert + sekundengenau über `_fmt_signed_delta(sec)` formatiert (z. B. „+1:23 zum Schnitt", bei `0` „punktgenau", `None` → leer). `_badge_entry_data` (`app/main.py`) liefert dafür zusätzlich `event` (Renn-Name aus `race.name`) und `delta_sec`; `_kutter_badge_data` (`app/main.py`) liefert analog `event` (Event-Name), `date`, `delivered_kg`, `stolen_kg`, `sunk_kg` aus `compute_transport_progress` (`participants`/`losses`) sowie (v8.8.1) `team_total_kg`/`team_target_kg` direkt aus `progress["total_kg"]`/`progress["target_kg"]` (Gesamt-Event, nicht der Pilot). Der Datei-Cache-/ETag-Hash (`_BADGE_RENDER_VERSION`, `GET /api/transport/event/{id}/badge/{cid}.png`) enthält `team_total_kg` — ändert sich die Team-Bilanz nachträglich (z. B. Admin-Korrektur), invalidiert das den Cache.

Alle Funktionen nutzen `ImageFont.load_default(size=…)` (Pillow ≥ 10) — keine gebündelten Schriftdateien, keine zusätzlichen apt-Pakete nötig. Fehlt ein Hintergrund-PNG, wird auf eine schlichte gezeichnete Scheibe zurückgefallen (Tests/lokal bleiben grün). Abhängigkeit: **`pillow>=10.0`** in `requirements.txt`. Badge-Text ist **ASCII-only** (der eingebettete Pillow-Default-Font rendert Emoji/Sonderzeichen wie `–`/`—` als leeres Kästchen).

**Badge-Endpoint (`GET /api/bummel/race/{race_id}/badge/{cid}.png` in `app/main.py`):** Prüft, ob das Rennen enthüllt ist (`revealed_at IS NOT NULL`) und ob die CID Teilnehmer ist — andernfalls `404` (kein Leak vor der Enthüllung). Rang 1 → `render_winner_badge`, alle anderen → `render_medal`.

**Cache-Strategie (ETag statt fixem max-age).** Aus den ergebnisrelevanten Feldern (`revealed_at`, Sieger-Flag, `total_min`, `delta_sec`, `aircraft`, `callsign`, `event`) wird ein MD5-Hash (`key`) gebildet, der zweierlei dient: (a) als Datei-Cache-Schlüssel — das PNG liegt unter `data/badges/<race_id>_<cid>_<key>.png` — und (b) als `ETag`. Antwort-Header sind jetzt **`Cache-Control: no-cache` + `ETag`** (vorher `Cache-Control: public, max-age=86400`). Schickt der Client ein passendes `If-None-Match`, antwortet der Server mit `304 Not Modified` (kein erneuter Download). Ändert sich der Sieger (z. B. durch Admin-Override oder Wertungsänderung), ändert sich der Hash → ETag → Browser/Forum holen sofort ein frisches Bild statt eines bis zu einen Tag veralteten. Das behebt den Bug, dass ein alter Gewinner-Badge nach einer Wertungsänderung hängenblieb. `Content-Type: image/png`.

**Kutter-Badge-Endpoint (`GET /api/transport/event/{event_id}/badge/{cid}.png` in `app/main.py`):** Prüft, ob das Event abgeschlossen ist (`summarized_at IS NOT NULL`) und ob die CID unter `compute_transport_progress(...)["participants"]` auftaucht — sonst `404` (kein Zwischenstand als „fertig"). Verlust-kg pro Art (`stolen_kg`/`sunk_kg`) werden aus `progress["losses"]` für die CID aufsummiert (`loss_kind == "returned"` zählt NICHT als Verlust — ehrlich zurückgebrachte Fracht). Gleiches ETag-/Datei-Cache-Muster wie beim Bummel-Badge (Hash über `summarized_at|delivered_kg|stolen_kg|sunk_kg|aircraft|callsign|event`, Datei `data/badges/kutter_<event_id>_<cid>_<key>.png`). Admin-Vorschau `GET /api/admin/transport/events/{event_id}/badge/{cid}.png` (`require_admin`) rendert immer frisch (`Cache-Control: no-store`), auch ohne `summarized_at`.

### `app/alerts.py`

Telegram-Alert beim "Online gehen" eines Piloten. Alle VATSIM-Felder werden mit `html.escape()` sanitized bevor sie in den `parse_mode=HTML` Telegram-Body eingebettet werden. Fehler werden nur als `type(e).__name__` geloggt (kein Full-Exception-String, der den Token in der Telegram-API-URL exponieren würde).

### `app/main.py`

FastAPI mit `lifespan`-Kontext-Manager (startup: DB init + Poller start; shutdown: Poller stop).

Endpoints: `/api/live`, `/api/prefiles`, `/api/stats`, `/api/stats/activity`, `/api/pilots/{cid}/flights`, `/api/pilots/{cid}/live-track`, `/api/flights/{id}/track`, `/api/flights/statsim/{id}/track`, `/api/events`, `/api/calendar/events`, `/api/bummel/races`, `/api/bummel/race/{id}`, `/api/bummel/active`, `/api/bummel/race/{race_id}/badge/{cid}.png` (Badge-PNG via `app/badge.py`, Reveal-Gating + `data/badges/`-Cache), `/api/transport/events`, `/api/transport/event/{id}`, `/api/transport/event/{event_id}/badge/{cid}.png` (Kutter-Badge-PNG, Gate über `summarized_at` + `data/badges/`-Cache), `/admin` (statische `admin.html`), `/api/admin/login`, `/api/admin/logout`, `/api/admin/me`, `/api/admin/bummel/races` (GET/POST + Unterrouten für einzelne Rennen inkl. reveal/hide/push/override/preview — alle via `require_admin`-Dependency geschützt), `/api/admin/bummel/races/{race_id}/badge/{cid}.png` (Badge-Vorschau ohne Reveal-Gate), `/api/admin/transport/events` (GET/POST + Unterrouten inkl. `badge/{cid}.png` Vorschau ohne `summarized_at`-Gate), `/api/admin/banner` (GET/POST), `/api/admin/push/test`, `/api/admin/push/broadcast`, `/api/admin/pilots` (GET/POST), `/api/admin/pilots/{cid}` (DELETE), `/api/admin/gps-leg-audit` (Diagnose-Vergleich `canonicalize_flights` vs. `canonicalize_legs`, s. „GPS-Leg-Erkennung" oben), `/api/admin/statsim-backfill` (Bulk-Nachladen von StatSim-GPS-Tracks), `/api/admin/airports` (GET/POST, v8.5.0/#50 — Ergänzungs-Flugplätze), `/api/admin/airports/{icao}` (DELETE), `/widget`, `/api/sse`.

**Hinweis-Banner-Mechanik:** `_resolve_banner_version(selected)` löst die in `app_settings['banner_version']` gespeicherte Admin-Auswahl auf eine konkrete Changelog-Version (oder `None` = kein Banner) auf: `off` → `None`, eine konkrete Version → diese (falls in `CHANGELOG` vorhanden, sonst `None`), `auto`/leer → neuester Eintrag mit `highlight: true` (Fallback: neuester Eintrag). `GET /api/frontend-config` liefert das Ergebnis im Feld `banner_version`. `GET /api/admin/banner` gibt die aktuelle Auswahl + alle Changelog-Einträge (`version`, `date`, `title`, `highlight`) zurück; `POST /api/admin/banner` schreibt die Auswahl via `set_app_setting`.

**Neue Admin-Endpoints (alle `require_admin`):**
- `GET /api/admin/bummel/races/{race_id}/badge/{cid}.png` — Badge-Vorschau eines Teilnehmers ohne Reveal-Gate (`_build_race_view(..., force_reveal=True)` + `_badge_entry_data`/`_render_badge`); immer frisch gerendert, `Cache-Control: no-store`. `404` wenn Rennen/Teilnehmer fehlt.
- `POST /api/admin/push/test` — sendet eine Test-Notification über `send_web_push` nur an die per `endpoint` adressierte Subscription (`get_push_subscription_by_endpoint`). Unbekannter Endpoint → `404`, kein VAPID → `400`.
- `POST /api/admin/push/broadcast` — freie Nachricht (`title`, `body`) an `audience = all` (`get_all_push_subscriptions`) oder `events` (`get_push_subscriptions_for_events`); Antwort enthält `sent` (Empfängerzahl).
- `GET/POST /api/admin/pilots` + `DELETE /api/admin/pilots/{cid}` — Piloten-Verwaltung über `list_pilots`/`upsert_pilot`/`delete_pilot`.
- `POST /api/admin/transport/events/{id}/push` — Push für ein Kutter-Event an-/abschalten (`set_transport_push_enabled`), spiegelt `POST /api/admin/bummel/races/{id}/push`.
- `GET /api/admin/airports` + `POST /api/admin/airports` + `DELETE /api/admin/airports/{icao}` (v8.5.0/#50, Override seit v8.6.0/#56) — CRUD für `custom_airports` (`list_custom_airports`/`upsert_custom_airport`/`delete_custom_airport`). `POST` lehnt Codes, die bereits in `airportsdata` bekannt sind, OHNE `override: true` ab (`geo.is_known_in_airportsdata`, `409`; MIT `override: true` wird trotzdem gespeichert — überschreibt einen ggf. falschen `airportsdata`-Wert); Pflichtfelder `icao`/`lat`/`lon`, `elevation_ft` optional, `reason` optional (v9.5.0/#78 — Freitext, `.strip()`, leer → `NULL`; keine Validierung, da reine Dokumentation). Jeder erfolgreiche Write ruft synchron `geo.set_custom_airports(...)` (Cache-Invalidierung — sofort wirksam, kein Neustart nötig). **`rebuild_flight_cache(conn, full=True)` läuft seit v8.6.2 als `BackgroundTasks`-Task NACH der Response** (Fund: der volle Rebuild über den GESAMTEN Bestand dauert bei großem StatSim-Bestand mehrere Sekunden — blockierend fühlte sich das Admin-Speichern/-Löschen "eingefroren" an); der Task öffnet eine eigene DB-Connection (die des Requests ist zu dem Zeitpunkt schon geschlossen). Der inkrementelle 7-Tage-Refresh würde ältere, durch den neuen/geänderten Platz betroffene Flüge ohnehin nicht heilen, daher bleibt `full=True` nötig — nur der Zeitpunkt (nach statt in der Response) hat sich geändert.
- `GET /api/admin/detection-gaps` + `POST /api/admin/detection-gaps/dismiss` (v8.6.0) — Prüfliste für Flüge mit fehlendem GPS-Start/-Landung trotz bekanntem Flugplan (`list_gps_detection_gaps`, live über `canonicalize_legs` — rechnet den GESAMTEN Flugbestand neu durch, ~15 s auf Prod, kein Cache); `dismiss` markiert einen einzelnen Flug via `(cid, logon_time)` dauerhaft als „kein Datenfehler" (`gps_detection_dismissals`). Die Admin-UI lädt diese Liste bewusst NICHT automatisch beim Öffnen der Seite (v8.6.1) — nur auf Klick auf „Jetzt prüfen", sonst würde jeder Seitenaufruf die teure Berechnung auslösen.

`/api/pilots/{cid}/flights` antwortet **sofort** mit FriesenSpy-Daten + gecachten StatSim-Daten — seit v8.0.0 direkt (live, ungecacht) über `canonicalize_legs(callsign_prefix="")`, inkl. `gps_departure`/`gps_arrival`/`plan_departure`/`plan_arrival`/`connection_closed` und Fremd-Callsign-Flügen (Frontend markiert sie als „nicht gewertet"). StatSim-Update läuft als FastAPI `BackgroundTask`: normaler Aufruf → letzter 31-Tage-Chunk; `days=0` → volle 365 Tage (Force-Refresh). Status-Tracking via `_statsim_updating` und `_full_history_fetching` (In-Memory-Sets) verhindert parallele Doppel-Fetches. Response-Header `X-StatSim-Status: fresh | updating | no-key`.

`/api/pilots/{cid}/live-track` gibt `position_history` des aktuell offenen Fluges zurück (logoff_time IS NULL). Wird vom Frontend beim ersten ◎-Klick geladen; danach wächst der Track mit jedem SSE-Update.

`/api/flights/{id}/track` akzeptiert optionale `logon`/`logoff`-Query-Params, die die DB-Zeitstempel überschreiben. Notwendig nach `merge_fragmented_flights`, wenn die DB noch die alten Zeiten der Ursprungsfragmente enthält.

**`/api/events` (seit v8.3.0 auf `canonicalize_legs` migriert, #33):** Die cid-Ermittlung bleibt
zweistufig — `filter_event_pilots`/Global-Suche über `position_history` (GPS-Nähe) **plus**
ein StatSim-`departure`/`arrival`-Match für Piloten ohne eigenen Track (nur zur cid-Ermittlung,
kein Flug-Dict-Bau mehr). Sobald die cid-Menge feststeht, EIN
`canonicalize_legs(conn, cids=..., callsign_prefix=CALLSIGN_PREFIX, start=start, end=end)`-Aufruf
(Muster wie `/api/pilots/{cid}/flights`, aber MIT Präfix-Filter — 2-Klassen-Regel, s. o.). Damit
entfallen die alte manuelle `flights`-Query, `merge_fragmented_flights`, der `segment_into_flights`-
Fallback (die Funktion selbst wurde entfernt, `app/geo.py`) sowie die On-the-fly-Dauer/Distanz-
Berechnung für aktive Flüge — `canonicalize_legs` liefert das bereits konsistent zu allen anderen
Views. Response-Flüge enthalten **keine** `positions` mehr (Formvertrag identisch zu
`flight_cache`) — das Frontend lädt den Track pro Flug bei Bedarf nach (dieselbe Quellen-Auswahl
wie der Track-Button in der Statistik-Ansicht: StatSim → `/api/flights/statsim/{statsim_id}/track`,
FriesenSpy mit `id` → `/api/flights/{id}/track`, sonst → `/api/pilots/{cid}/track`).

### `app/static/index.html`

Single-File-SPA ohne Build-Step. Vier Tabs:

**Layer-Präferenz:** `_saveLayerPref(key)` / `_loadLayerPref()` / `_getPreferredLayer(layers)` — speichert den zuletzt manuell gewählten Basis-Layer (Schlüssel `friesenspy_layer`) in `localStorage`. Alle drei Karten (Live, Track-Modal, Events) initialisieren mit dem gespeicherten Layer. OFM-Auto-Switch ist nur aktiv wenn OFM die gespeicherte Präferenz ist; manuell zurück zu OFM → Auto-Switch reaktiviert sich.

**OpenAIP-Overlay-Präferenz:** `_saveAIPPref(on)` / `_loadAIPPref()` / `_setupAIPPref(map, aipLayer)` — speichert ob das OpenAIP-Overlay aktiv war (Schlüssel `friesenspy_aip`, Wert `'1'`/`'0'`) in `localStorage`. Alle drei Karten rufen `_setupAIPPref` nach dem Layer-Control-Init auf: restauriert den gespeicherten Zustand und registriert `overlayadd`/`overlayremove`-Listener zum Speichern bei Änderung.

- **LIVE** — EventSource(`/api/sse`) mit Reconnect; **Flugplan-Zelle (DEP→ARR) anklicken** → Flugplan-Modal (vollständige Live-Daten); ◎-Klick → `switchToMapAndCenter()`
- **KARTE** — Leaflet.js; Marker mit Heading-Rotation; Double-RAF-Init beim Tab-Wechsel; Live-Track-Polyline pro Pilot (`liveTrackPoints`/`liveTrackLines`): beim ersten ◎-Klick oder Map-Init via `/api/pilots/{cid}/live-track` geladen, danach per SSE-Update erweitert; Track wird entfernt wenn Pilot offline geht

**Moving Map, Track-up und gleitende Marker (v12.6.0).** Ein einziger Sekundentakt (`_naviTakt`, `setInterval` 1 s) bewegt alles: fortgerechnete Marker, Kartendrehung und Nachführung. Bewusst kein `requestAnimationFrame` — die Lehre aus v12.5.2 ist, dass eine Schleife, die in *jedem* Einzelbild etwas anfasst, in Coherent GT die Zeichenlast dauerhaft hochhält.

- **Zwei Positionsquellen, klar getrennt.** Das *eigene* Flugzeug kommt im Kniebrett aus dem Simulator (`SimVar` in der EFB-Shell → `postMessage {art:'position'}` → `_simPos`); alle *anderen* kamen bis v12.10.0 ausschließlich aus dem VATSIM-Strom.
  **Diese Trennung ist mit v12.10.0 gefallen** — siehe „Verkehr aus dem Simulator" weiter unten. Die frühere Begründung, fremder Verkehr sei über den JS-Weg nicht zu bekommen, stützte sich auf [DevSupport 3794](https://devsupport.flightsimulator.com/t/online-multiplayer-traffic-not-being-returned-in-traffic-requests/3794) (kein Multiplayer-Verkehr) und [DevSupport 4993](https://devsupport.flightsimulator.com/t/ai-aircraft-generated-airborne-do-not-get-returned-with-the-get-air-traffic-coherent-call/4993) (in der Luft erzeugte AI-Objekte fehlen — und genau so injiziert vPilot). **4993 ist für MSFS 2024 überholt:** gemessen am 15.08.2026 über Hamburg, `GET_AIR_TRAFFIC` meldete 6 Flugzeuge, VATSIM im selben Moment im 75-km-Umkreis ebenfalls 6.
  [DevSupport 13002](https://devsupport.flightsimulator.com/t/js-npcplane-parameter-name-always-empty-msfs2020-2024/13002) (`name` immer leer) **behält dagegen recht** — gemessen am 16.08.2026: `name` und `plane_model_icao` kommen leer. Der Sim liefert also Bewegung, aber keine Identität. Genau daraus folgt die Zusammenführung beider Quellen (v13.2.0, weiter unten): Rufzeichen, Muster und Flugplan können nur von VATSIM kommen.
  **Für SimConnect galt die Einschränkung ohnehin nie:** Dort sind die von vPilot per `SimConnect_AICreateNonATCAircraft` erzeugten AI-Objekte sehr wohl lesbar — Little Navmap lebt davon; die 0-Werte betreffen nur echte Multiplayer-Objekte ([DevSupport 17557](https://devsupport.flightsimulator.com/t/multiplayer-traffic-not-ai-incorrect-values/17557)).
- **`_eigenePosition()`** staffelt: frische Sim-Position (< 5 s) → eigener Flieger aus `liveData` (CID aus `/api/me` in `_meineCid`) → `null`. Ohne beides bleiben beide Knöpfe wirkungslos.
- **Fortrechnung (`_jetztGerechnet`)**: ebene Näherung aus Kurs und GS, ausgehend von `_positionsRoh[callsign]` — dem letzten *echten* VATSIM-Wert mit Empfangszeit, nie vom zuletzt gezeichneten Punkt (sonst summiert sich der Fehler auf). Bekannte Ungenauigkeit: VATSIM meldet `heading`, nicht den Weg über Grund; bei Wind läuft die Schätzung leicht schräg. **`liveTrackPoints` bleibt unberührt** — aufgezeichnete Wege enthalten nur echte Messpunkte.
- **Track-up** über [`leaflet-rotate`](https://github.com/Raruto/leaflet-rotate) 0.2.8 (unpkg, mit SRI + `onerror`). Nur die Live-Karte bekommt `rotate: true`; Gesten sind aus (`touchRotate`/`shiftKeyRotate`/`rotateControl` = false), gedreht wird ausschließlich per Kompassknopf — eine im Cockpit versehentlich verdrehte Karte wäre schlimmer als eine, die sich nicht dreht. Jede Nutzung hinter `_kannDrehen(map)`; fällt das Plugin aus, läuft alles unverändert weiter, nur ohne Track-up. Bearing = −Kurs; die Kompassnadel dreht **mit** der Karte (zeigt also weiter nach Norden). Marker werden vom Plugin *nicht* gegenrotiert und drehen mit dem Pane mit — bei Track-up zeigt ein Flugzeug mit dem eigenen Kurs damit korrekt nach oben.
- **Zustand** in `localStorage` (`friesenspy_trackup`, `friesenspy_movingmap`). `dragstart` schaltet Moving Map ab, Zoomen nicht.
- **Messung** `panel_diag` `kind="navi"`: einmalig 20 s nach dem Kartenaufbau — beantwortet, ob die Sim-Position wirklich ankam oder der VATSIM-Fallback lief (`quelle`), ob das Plugin greift und wie das Bearing steht.

**Fremdverkehr auf der Karte (v12.7.0).** Anderer VATSIM-Verkehr als abschaltbare Ebene „Verkehr" in der bestehenden `L.control.layers` — dieselbe Bedienung wie OpenAIP, kein eigener Knopf. Geschaltet wird **ausschließlich** der Fremdverkehr; die Friesen sind der Kern der Anwendung und bleiben immer sichtbar.

- **Datenweg**: `_poll_once` legt den kompletten Feed als `poller.traffic_snapshot` **im Speicher** ab (nicht in der Datenbank — Fremdverkehr ist reine Anzeige, und eine Historie über ~1000 Flugzeuge im 15-Sekunden-Takt wäre in Tagen größer als alles andere in dieser Datenbank zusammen). `/api/traffic` schneidet daraus den Umkreis der Kartenmitte heraus.
- **Dieselbe Trennung wie bei den Friesen**: `_verkehrRoh[callsign]` hält den gemeldeten Wert mit Zeitstempel, der Marker die geschätzte Position; gerechnet wird immer vom Rohwert (`_jetztGerechnet`, unverändert wiederverwendet). Der Zeitstempel wird **nur bei wirklich neuen Koordinaten** gesetzt und um `age` zurückdatiert — sonst begänne die Fortrechnung bei jedem Abruf von vorn bzw. beim Empfang statt beim Abruf durch den Poller.
- **Bewegt wird nur im Sekundentakt** (`_naviTakt`, Abschnitt 2b) — dieselbe Regel, die das Zurückspringen der Friesen-Marker behoben hat.
- **Drei Sparmaßnahmen**: unterhalb `_VERKEHR_MIN_ZOOM` (7, = Start-Zoomstufe der Karte) wird nicht abgefragt und nichts gezeichnet; auf verdeckter Karte ruht der Abruf; `moveend` löst nur bei **fremder** Kartenbewegung einen Abruf aus (`!_naviSelbstBewegt`) — ohne diese Wache feuerte das eigene sekündliche `setView` der Moving Map den Abruf im Drossel-Takt, also alle 3 s statt alle 15 s.
- **Hysterese beim Entfernen**: Ein Marker verschwindet erst, wenn sein Callsign **zwei** Abrufe hintereinander gefehlt hat. Der Server kappt hart bei 60 nach Entfernung; ohne Hysterese flackerte das Flugzeug auf Rang 60/61, und jedes Neuanlegen ist in Coherent GT als Aufblitzen sichtbar.
- **Label** (`_verkehrLabel`, `_labelHoehe`): **immer** Callsign, darunter `MUSTER HÖHE GS` — für Fremdverkehr, Friesen und das eigene Flugzeug dieselbe Funktion, ein Argument. Bis v13.1.3 gab es zwei Ausnahmen (Callsign nur unter 10 000 ft oder bei Friesen; eigenes Flugzeug mit eigener Form); beide sind raus, seit es den Haken „Radar Label" gibt — ein Schalter ist das ehrlichere Mittel als eine Karte, die selbst entscheidet, welche Zeile man wohl braucht. `_LABEL_FL_AB_FT` steuert jetzt nur noch die **Schreibweise** der Höhe (FL ab 10 000 ft, darunter Fußzahl), keine Sichtbarkeit mehr. Unter 10 000 ft Fuß-Zahl, ab genau 10 000 ft `FL` + Hunderter. Eine Funktion für Label **und** Popup — das vorhandene `fmtAlt` schreibt Flugflächen erst ab 18 000 ft, zwei Regeln nebeneinander ergäben am Symbol `FL120` und einen Klick daneben `12.000 ft`. Das Label sitzt als Leaflet-Tooltip **außerhalb** des Marker-Icons: Der Marker dreht bei Track-up mit (`rotateWithView`), ein Label darin stünde auf dem Kopf. `leaflet-rotate` legt `tooltipPane` in seinen nicht drehenden Pane — nachgesehen im Plugin-Quelltext und im Browser bestätigt (84×25 px bei Bearing 0/315/270/90).
- **Naht zu Teilprojekt 2**: Der zeichnende Teil liest ausschließlich aus `_verkehrRoh` und kennt seinen Zulieferer nicht. Diese Naht hat gehalten — v12.10.0 füllt dieselbe Struktur aus dem Simulator, ohne dass Marker, Label, Ebene oder Fortrechnung angefasst werden mussten.

**Verkehr aus dem Simulator (v12.10.0, Kniebrett-Paket 1.5.0; seit v13.2.0 *ergänzend* statt ersetzend).** Im Kniebrett steuert der Sim die Bewegung bei: 1 Hz statt 15 s, gemessene statt geschätzter Positionen, und auch ohne VATSIM-Verbindung (dann der AI-Verkehr des Simulators). Spec: `docs/superpowers/specs/2026-08-15-sim-verkehr-design.md`.

> ⚠️ **Die Vorbedingung ist Teil des Aufrufs** (Fund 15.08.2026, behoben in Paket 1.7.0). Vor `GET_AIR_TRAFFIC` muss der Karten-Listener angemeldet sein:
>
> ```js
> RegisterViewListener('JS_LISTENER_MAPS').trigger('JS_BIND_BINGMAP', '<name>', true);
> ```
>
> Ohne sie gibt der Simulator **nichts** heraus — und meldet auch keinen Fehler. Der Aufruf löst nicht auf, der Ein-Sekunden-Abbruch greift, `verkehrSenden` kehrt wortlos um. Im Kniebrett blieb dabei der VATSIM-Verkehr stehen, was aussieht wie „funktioniert, nur langsam".
>
> **Wie es dazu kam — der eigentliche Lehrsatz.** Die Messsonde (Paket 1.3.0) hatte die Zeile und lieferte am 15.08.2026 um 10:33 UTC sechs Flugzeuge (`viewListener: "angemeldet"`, `typ: "[object Array]"`, `anzahl: 6`, `vatsimNah: 6` — das ist die 6:6-Messung). Beim Ausbau der Sonde wurde die *Messfunktion* entfernt und die Vorbedingung mit ihr, ohne dass sie in den Produktivcode wanderte. **Wird eine Sonde durch Produktivcode ersetzt, muss jede Zeile geprüft werden, die zum Erfolg der Messung beigetragen hat — nicht nur die, die das Ergebnis liest.**
>
> **Und warum es so lange unentdeckt blieb:** Es gab keine Meldung über das Ausbleiben. `_simVerkehrDiagnoseEinmal` feuert nur bei **nichtleerer** Liste; „nichts gekommen" war von „nichts in der Nähe" nicht zu unterscheiden. Seit 1.7.0 geht deshalb ein `sim-verkehr-start`-Befund einmal je Sitzung raus, **bevor** über die Liste entschieden wird — mit `coherentDa`, `viewListener`, `typ`, `anzahl` und den Feldnamen. Eine Diagnose, die nur den Erfolgsfall meldet, ist im Fehlerfall wertlos.
>
> Nebenbei belegt derselbe Datensatz die offenen Feldfragen: `GET_AIR_TRAFFIC` liefert `__Type, name, plane_model_icao, uId, lat, lon, alt, heading, isOnGround` — `isOnGround` **wird** also geliefert.

- **Datenweg**: `onUpdate` der EFB-App → `kartenListenerAnmelden()` → `Coherent.call('GET_AIR_TRAFFIC')` → aufbereiten → `postMessage {art:'sim-verkehr', liste}` → `_verkehrNeuZeichnen` → `_verkehrZusammenfuehren` → `_verkehrZeichnen` → `_verkehrRoh`. Kein Server, kein Netz, kein WASM-Modul.
- **Die Einheiten stehen in keiner Dokumentation, aber im ausgelieferten Simulator.** Nachgelesen in Asobos eigenen Auswertern unter `…\Packages\Official\OneStore\` — `workingtitle-instruments-g1000\…\msfssdk.js` (`TrafficInstrument`) und `workingtitle-ingamepanels-vfrmap\…\GameVFRMap.js` (`VfrTrafficManager`):

  | Frage | Antwort | Beleg |
  |---|---|---|
  | `alt` | **Meter** | `UnitType.METER.convertTo(entry.alt, UnitType.FOOT)` |
  | `heading` | **Grad** | `NavMath.diffAngle` wickelt bei ±180/360, nicht bei ±π |
  | Schlüssel | `uId`, über Abrufe stabil | beide führen ihre Map darüber |
  | Takt | **1000 ms** | `VfrTrafficManager.POLL_INTERVAL = 1000` |
  | Grundgeschwindigkeit | **wird nicht geliefert** | beide leiten sie aus Positionsdifferenzen ab |
  | Aufruf kann hängen | ja | SDK: `Promise.race([Coherent.call(…), Wait.awaitDelay(1000)])` + `isBusy` |

  **Verallgemeinerbar:** Bei jeder undokumentierten MSFS-JS-Schnittstelle zuerst nach Asobos eigenem Verbraucher im Installationsverzeichnis suchen. Das ist schneller und belastbarer als raten oder messen.
- **Grundgeschwindigkeit** (`verkehrGsAbleiten`): Haversine zwischen zwei Meldungen ÷ Zeit, exponentiell geglättet mit der Zeitkonstante des SDK (`2/ln2` s) und oberhalb von 1500 kt verworfen — beides die Werte, die das SDK an derselben Stelle selbst ansetzt („to reduce artifacts from potentially noisy data").
- **Filter im Panel, in dieser Reihenfolge**: eigenes Flugzeug (< 150 m **und** < 100 ft Unterschied — greift nach heutigem Stand nie, kostet aber nichts), dann Deckel auf 60 **nach Entfernung**. Mehr nicht.
- **Geparkte Flugzeuge werden gezeigt wie alle anderen, mit Schild** (Paket 1.7.0, 15.08.2026). Davor gab es eine Sonderregel — sichtbar erst ab Zoomstufe 13, und dann ohne Beschriftung. Sie ist **ersatzlos entfernt**, und der Weg dahin ist die eigentliche Lehre:
  - Im Flug standen geparkte Maschinen mit Schild auf dem Vorfeld, obwohl die Regel sie hätte stumm schalten müssen. Die Regel griff nie.
  - Der Grund ist die Erkennung selbst. „Steht am Boden" hing an `isOnGround` bzw. `gnd`. Der **VATSIM-Feed liefert dieses Feld gar nicht** — jeder VATSIM-Eintrag fiel also durch. Und ob der Simulator es liefert, ist bis heute **unbelegt** (s. offener Punkt unten).
  - Eine Regel, die nur manchmal greift, ist schlechter als keine: Sie erzeugt zwei Verhaltensweisen für dieselbe Sache, je nach Quelle, und niemand kann vorhersagen, welche gerade gilt.
  - Damit ist auch der Rückkanal wieder einfach: `{art:'verkehr-schalter', an}` trägt genau eine Aussage. Die Zoom-Nachführung (`zoomend`) und der Zustandsvergleich dahinter sind entfallen.
- **Schilder ein- und ausschaltbar** (`_schilderSchalterEinbauen`, ab v13.1.0) — in der Oberfläche heißt der Haken **„Radar Label"**, im Quelltext durchgängig „Schilder"; der Anzeigename steht an genau einer Stelle. Ein zweiter Haken **unter** der Verkehrs-Ebene in der Ebenen-Auswahl, sichtbar nur solange diese an ist (`_schilderSchalterSichtbarkeit`, an `overlayadd`/`overlayremove` — bei einem Klick *in* der Auswahl setzt Leaflet `_handlingClick` und ruft `_update` absichtlich nicht, die Umhüllung unten greift dort also nicht). Weil Leaflet die Liste bei jeder Layer-Änderung per `innerHTML` neu aufbaut und dabei alles Fremde verwirft, wird `_update` umhüllt und der Haken danach wieder eingesetzt; die Einbau-Funktion ist dafür idempotent (v13.1.1). Leaflet sieht so etwas nicht vor (die Control kennt nur Ebenen), deshalb wird das Kästchen nach dem Aufbau ins fertige DOM gehängt — findet es seinen Anker nicht, fehlt still der Zusatzhaken, die Karte bleibt heil. Ausgeblendet wird über **CSS** (`.ohne-verkehrsschilder .traffic-label-fremd`), nicht über `unbindTooltip`: So wirkt der Haken sofort statt erst beim nächsten Zulauf, und ein neu dazukommendes Flugzeug hat den Zustand automatisch richtig, ohne dass die Zeichenroutine ihn kennen muss. Betroffen ist nur der **fremde** Verkehr — eigene Maschine und Friesen behalten ihr Schild. Vorgabe ist **an** (anders als bei den übrigen Merkern, wo „nie entschieden" = aus).
- **Das eigene Flugzeug trägt dasselbe Schild wie alle anderen** (`_eigenLabel`, ab v13.1.0). Dort stand „DEIN FLUGZEUG" als Kopfzeile — als einziges Schild der Karte mit einem Text, der kein Rufzeichen ist. Welches Symbol das eigene ist, sagen Farbe und die Tatsache, dass die Karte ihm folgt.
- **Beide Quellen werden zusammengeführt** (`_verkehrZusammenfuehren`, ab v13.2.0) — nicht gegeneinander getauscht. Die erste Fassung ließ immer nur eine gelten: Sobald der Sim lieferte, brach `_verkehrAbrufen` ab. Im Flug fiel das sofort auf (15.08.2026): Beim vPilot-Connect verschwanden Flugzeuge, die VATSIM kannte und der Sim nicht — vPilot spawnt nicht jede Maschine (Model Matching, Sichtbarkeitsgrenzen) — **und mit ihnen alle Rufzeichen**, denn der Sim liefert `name`/`plane_model_icao` leer.
  - **Paarung**: Zu jeder Sim-Meldung wird das nächstgelegene noch freie VATSIM-Flugzeug in verträglicher Höhe gesucht (`_verkehrPartnerSuchen`, ≤ 6 km **und** ≤ 1500 ft). Die Ortsschranke ist bewusst weit: Die VATSIM-Position ist bis zu 15 s alt, ein Verkehrsflugzeug legt darin ~3 km zurück — eng gefasst würden ausgerechnet die schnellen nie paaren. Die Höhe ist das schärfere Merkmal.
  - **Gepaart**: Position, Kurs und Geschwindigkeit vom **Sim**, Rufzeichen/Muster/Flugplan von **VATSIM**. Schlüssel ist das Callsign — reißt die Paarung ab und kommt wieder, bleibt es derselbe Marker.
  - **Nur Sim**: Schlüssel `sim:<uId>`, ohne Rufzeichen. **Nur VATSIM**: wie bisher.
  - Dubletten verhindert die Belegung (`belegt[cs]`), nicht mehr der Abbruch des Netzabrufs. Ein VATSIM-Eintrag wird höchstens einmal gepaart.
  - **Jeder Eintrag trägt seinen eigenen Messzeitpunkt** (`_ts`) und Schlüssel (`_key`). Das muss am Eintrag hängen, seit beide Quellen in einer Liste stehen: Eine Sim-Meldung gilt für diese Sekunde, eine VATSIM-Meldung ist bis zu 15 s alt — ein gemeinsamer Wert würde die eine Hälfte falsch fortrechnen.
  - `_verkehrQuelleWechseln`/`_verkehrLeeren` beim Wechsel sind entfallen. Was nicht mehr gemeldet wird, fällt über die vorhandene Hysterese heraus — einzeln statt alles auf einmal.
- **Aus = wirklich aus**: Die Seite meldet den Zustand der Ebene über den bestehenden Rückkanal (`{quelle:'friesenspy', art:'verkehr-schalter'}`); ohne ein „an" fragt das Panel den Sim gar nicht erst ab. Gemeldet wird auch beim Aufbau — eine gespeicherte Präferenz schaltet die Ebene ohne Klick ein, und `overlayadd` feuert dabei nicht.
- **STATISTIKEN** — `/api/stats?days=N`; KPI-Box oben (Piloten, Flüge, Stunden, Ø/Tag, Aktivster Pilot, Ø Flugdauer — klickbar); Liniendiagramm via `/api/stats/activity?days=N` (Piloten/Flüge/Stunden/Ø Flugdauer, täglich für ≤93 Tage mit Wochentag-Labels, monatlich für 365 Tage, Dual-Y-Achse); Callsign + Pilot + geloggte Flüge (FS + ST) + letzter Flug; Pilot-Klick → `openPilotFlights()` → `/api/pilots/{cid}/flights?days=N` (sofort aus Cache, StatSim im Hintergrund); Fluglisten-Tabelle zeigt **GPS-Route** (`gps_departure`/`gps_arrival`) und **Flugplan** (`plan_departure`/`plan_arrival`) in getrennten Spalten (Spec G, #23) sowie **Flugzeit**/**Block**-Spalten; ein noch nicht gelandeter Flug (`!gps_arrival && !connection_closed`) zeigt `🛫 läuft` statt Ziel; Flüge unter Nicht-`FRS`-Callsign tragen ein `nicht gewertet`-Badge (`_callsignPrefix` aus `/api/frontend-config`); Badge „⟳ StatSim wird aktualisiert…" wenn `X-StatSim-Status: updating`; Auto-Refresh nach 10s; „Alle Flüge laden (letztes Jahr)" → `?days=0` (365-Tage-Force-Refresh); **Flugplan-Zelle (DEP→ARR) anklicken** → `openFlightDetailModal()` — zeigt dieselben Felder wie das Live-Flugplan-Modal (Flight Rules, Aircraft, DEP, ARR, Alternate, Off Block UTC, Altitude, TAS, Enroute, Fuel Endurance, Route, Remarks) plus historisch-spezifische Felder (Datum UTC, Dauer, Strecke, Quelle); optionale Felder ausgeblendet wenn leer; ◎-Klick → Track-Modal; ⎘ Teilen in Drill-Down, Track-Modal und Flugdetail-Modal
- **EVENTS** — `/api/events`; Layout: Karte oben (560px, OFM), Pilotenliste darunter; pro Pilot eine Flugtabelle **im selben renderFlightsList-Schema wie die Statistik-Ansicht** (seit v8.3.0, #33 — gemeinsame Hilfsfunktion `_flightRowHtml`/`_wireFlightRowClicks`): Callsign, Aircraft, GPS-Strecke, Plan, Datum, Flugzeit, Block, Distanz, Track, Quelle. **GPS-Strecke anklicken** → `openFlightDetailModal()` (GPS-Detail), **Plan anklicken** (nur wenn vorhanden) → `openPlanDetailModal()` (Flugplan-Detail), **Track-Symbol** → `openTrackModal()`; Karte lädt Tracks pro Flug asynchron nach (`_flightTrackUrl`, gleiche Quellen-Auswahl wie der Track-Button — Positionen werden nicht mehr eingebettet aus dem Backend geliefert) und zeichnet sie ein, sobald verfügbar; Klick auf Flug-Zeile → `highlightEventFlight()` hebt Track hervor (auch wenn er noch nicht geladen ist — `if (pl)`-Guard), „↺ Alle Tracks"-Button setzt zurück; ⎘ Teilen (Event-Suche + offenes Flugdetail-/Flugplan-Modal); `searchEvents()` behandelt `datetime-local` direkt als UTC

**Client-Polling & Rate-Limiting**: `/api/prefiles` und `/api/teamspeak` werden auf **eigenem, festem Takt** gepollt (`setInterval` 60 s bzw. 30 s) — bewusst **nicht** mehr an den SSE-`positions`-Handler gekoppelt. Grund: Browser drosseln Hintergrund-Tabs und puffern eingehende SSE-Frames; beim Wiederöffnen werden hunderte gepufferte `positions`-Frames auf einmal an `onmessage` zugestellt. Solange dort je Frame ein `/api/prefiles`+`/api/teamspeak`-**Paar** ausgelöst wurde, erzeugte ein einziger Vordergrund-Wechsel ~900 HTTP-Requests in Sekunden → 429-Sturm → „Fehler beim Laden". Der SSE-Handler rendert jetzt nur noch lokal (Tabelle/Karte), ohne zusätzliche Fetches. `/api/live` läuft als unabhängiger 15-s-Fallback (iOS/PWA). Bei einem 429 zeigen `fetchAndRenderPrefiles`/`fetchAndRenderTeamspeak`/`fetchStats` **keinen** harten Fehler mehr, sondern behalten den letzten Stand (Stats: ein automatischer Retry nach 1,5 s). nginx limitiert **nur `/api/`** (`zone friesenspy_limit`, `rate=120r/m`, `burst=60 nodelay`, `limit_req_status 429`); `/api/sse` ist ausgenommen (längster Prefix), SPA-Shell/statische Assets/PWA-Icons sind **nicht** limitiert, damit der Asset-Schwall beim Laden den Burst nicht sprengt. Historie: `rate=30r/m, burst=10` für `location /` verursachte verbreitete 429 (teils als „Fehler 409" gemeldet); 30→120 r/m half live/stats, aber das prefiles+teamspeak-Paar erst die Entkopplung oben (27.06.2026).

**URL Deep-Linking** via `location.hash` (URLSearchParams): Tab, Pilot-CID, Zeitraum (days=), Track-ID/Source, Callsign (fp=), Events-Filter (icao/radius/start/end), Flugdetail-Modal (`fld=<logon_time>`), **Bummel-Rennen (`bummel=<race_id>`)** werden im Hash gespeichert → Seite neu laden öffnet den gleichen Zustand. `openFlightDetailModal()` schreibt `fld=logon_time` in den Hash; `closeFldModal()` entfernt es. `openBummel()` schreibt `tab=events&bummel=<race_id>` (Deep-Link auf ein konkretes Rennen); der „⎘ Teilen"-Button oben rechts im Bummel-Panel-Header nutzt denselben `copyShareUrl()` wie alle anderen Views (Clipboard-Copy von `location.href`). `initFromUrl()` wird beim Seitenstart nach `fetchLiveInitial()` ausgeführt; beim `bummel=`-Param lädt es `/api/bummel/races`, findet das Rennen per `id` und ruft `openBummel()` (über den `_raceId`-Pfad) auf; re-aktiviert den korrekten Tab am Ende aller Async-Operationen (Race-Condition-Schutz).

**Karten-Layer**: OpenFlightMap (OFM) als Standard auf allen Leaflet-Instanzen (Live/Karte, Track-Modal, Events). Fünf Basislayer via `L.control.layers()`: OFM (native Tiles Zoom 6–11, `minZoom:6`), OpenTopoMap (OSM+SRTM, Zoom bis 17), Satellit (ESRI World Imagery), Light (CartoDB Positron), Dark (CartoDB Dark Matter). **OpenAIP-Overlay**: Checkbox für Luftraum/Flugplätze/Navaids — wird nur angezeigt wenn `OPENAIP_API_KEY` gesetzt; Key wird via `/api/frontend-config` an das Frontend übergeben und per `_makeAIPOverlay()` als separater Tile-Layer eingebunden. **Auto-Switch** (`_setupOFMAutoSwitch`): Solange OFM aktiv ist, wechselt die Karte bei Zoom < 7 oder Zoom > 12 automatisch auf Satellit und zurück im OFM-Bereich (Zoom 7–12). Manueller Wechsel zu einem Nicht-OFM-Layer deaktiviert den Auto-Switch; manuell zurück zu OFM reaktiviert ihn. `initLiveMap()`, `renderEventsMap()` und der Track-Modal-Init awaiten `_configPromise` (den `/api/frontend-config`-Fetch) um Race Conditions beim OpenAIP-Key-Laden zu vermeiden.

**Web Push Notifications**: Bell-Icon 🔔 im Header — sichtbar wenn `VAPID_PUBLIC_KEY` gesetzt. Klick öffnet Panel mit Toggle + Pilot-Filter. `_registerServiceWorker()` registriert `sw.js` und lädt bestehende Push-Subscription. `_subscribePush()` fragt Notification-Erlaubnis, abonniert via `pushManager.subscribe()` und postet Subscription an `/api/push/subscribe`. Service Worker (`app/static/sw.js`) empfängt `push`-Events und zeigt Notifications im Hintergrund — auch bei geschlossenem Browser. **PWA-Installation**: Web-App-Manifest (`app/static/manifest.webmanifest`, via `<link rel="manifest">`; MIME `application/manifest+json` in `main.py` registriert) + Icons (`icon-192/512`, `icon-maskable-512`, `apple-touch-icon`, erzeugt mit `generate_icons.py`) machen die SPA installierbar. Ein sichtbarer, schließbarer **Install-Banner** (`#install-banner`, oberhalb der Tab-Nav) weist darauf hin: `_maybeShowInstallBanner()` zeigt ihn nur, wenn nicht bereits `display-mode: standalone` und nicht in `localStorage` (`fs_install_dismissed`) weggeklickt. Auf Android/Desktop feuert `beforeinstallprompt` → Button öffnet den nativen Dialog (`prompt()`); auf iOS-Safari zeigt der Banner die manuelle Anleitung ("Teilen ⬆ → Zum Home-Bildschirm"). `appinstalled` blendet den Banner aus. Der alte "Als App installieren"-Button im Push-Panel bleibt zusätzlich erhalten. Pilot-Filter (Alle / bestimmte CIDs) wird serverseitig in `push_subscriptions.pilot_filter` (JSON) gespeichert. **Pilot-Filter-UX**: Bei "Alle Friesen" sind alle Checkboxen checked + disabled (visuell ausgegraut, nicht änderbar). Bei "Nur bestimmte Piloten" werden Checkboxen aktiviert; beim Umschalten von "select" → "all" wird der aktuelle Zustand in `_notifCustomFilter` (in-memory) gemerkt, sodass bei erneutem Wechsel zurück der Stand erhalten bleibt — auch ohne Speichern. Beim ersten Öffnen wird der gespeicherte Filter aus `localStorage` geladen und der Radio-Modus entsprechend wiederhergestellt. **„Push zurücksetzen"**: deabonniert, deregistriert alle SW-Registrierungen und lädt neu — erzwingt frischen FCM/APNs/WNS-Token (nötig bei `permanently-removed.invalid`-Endpoints). **Endpoint-Validierung**: `/api/push/subscribe` lehnt `permanently-removed.invalid`-Endpoints mit HTTP 400 ab. **VAPID-Keys**: `VAPID_PRIVATE_KEY` muss als raw base64url-kodierter EC-Skalar (32 Byte, 43 Zeichen, kein PEM) in config.env stehen — generiert mit `generate_vapid.py`. pywebpush mutiert das `claims`-Dict in-place (fügt `aud`/`exp` hinzu) → pro Push ein frisches Dict erstellen. WNS erfordert `ttl=3600` (TTL=0 wird von WNS abgelehnt). Bei transientem Fehler (z.B. APNs 4xx) wird einmal nach 5 Sekunden wiederholt.

**Versionierung & Changelog**: Single Source of Truth ist die Repo-Datei `app/CHANGELOG.json`
(neueste Version zuerst; je Eintrag `version`, `date`, `title`, `items`). `app/version.py` liest
sie ein und stellt `VERSION` (= `CHANGELOG[0].version`) und `CHANGELOG` bereit; `/api/frontend-config`
liefert beides ans Frontend. Im Header zeigt `#app-version` die kleine Versionsnummer (Klick →
Versionsverlauf-Modal `#changelog-modal`, wiederverwendet die `.fp-modal-*`-Klassen). `#changelog-banner`
(Basis-Styling vom Install-Banner) zeigt die Neuerungen **einmal pro Version**. Welcher Eintrag
Banner ist, bestimmt jetzt der **Server**: `_initVersionUI(cfg.version, cfg.changelog, cfg.banner_version)`
reicht das Feld `banner_version` aus `/api/frontend-config` an `_maybeShowChangelogBanner()` weiter — ist
es `null`, erscheint **kein** Banner; sonst der Eintrag dieser Version. Das Seen-Gating pro App-Version
bleibt: das Banner erscheint nur, wenn `localStorage['fs_changelog_seen'] !== version`; ✕ oder das Öffnen
des Verlaufs setzt den Key auf die aktuelle Version. Die Banner-Auswahl (`auto`/`off`/Version) steuert der
Admin über `/api/admin/banner`. **Release-Workflow:** bei signifikanten Änderungen einen neuen Eintrag oben
in `app/CHANGELOG.json` einfügen — mit `highlight: true` erscheint er bei `banner_version = auto` automatisch
als Banner bei allen Nutzern.

Design: FriesenFlieger-Blau (`#04080f` Hintergrund, `#2d9cdb` Blau, `#D31141` Vereinsrot).

## Datenfluss SSE

```
Browser                     FastAPI                  VatsimPoller
   │                           │                          │
   │─── GET /api/sse ──────────►│── subscribe_sse() ──────►│  (eigene Queue registriert)
   │                           │                          │
   │                           │◄─── queue.get() ─────────│
   │                           │     (wartet bis Event)   │
   │                           │                          │
   │                           │    (15s später)          │
   │                           │    VATSIM poll ──────────►│
   │                           │                          │─ State-Machine
   │                           │                          │─ SQLite commit
   │                           │◄─ broadcast_sse({...}) ──│  (put_nowait je Client-Queue)
   │                           │                          │
   │◄── data: {...}\n\n ────────│                          │
   │  (Disconnect → unsubscribe_sse() im finally)         │
```

### Zweiter Ereignistyp: `notify` (Sim-Benachrichtigungen, v12.1.0)

Web-Push existiert in Coherent GT nicht (kein OS-Push-Kanal). Damit das MSFS-Kniebrett
trotzdem meldet, wenn jemand online geht, laufen dieselben Meldungen zusätzlich über den
ohnehin offenen SSE-Strom:

```
poller.broadcast_notify(service, subject_cid, payload)   ← neben jedem Web-Push-Auslöser,
        │                                                  bewusst außerhalb des
        │                                                  `if vapid_private_key`-Zweigs
        ▼
_event_generator  ── is_visible_to(subject, viewer, service)? ── nein → verworfen
        │                                                        (verlässt den Server nie)
        ▼ ja
index.html  ── Kategorie-Schalter (localStorage) ── _translitText ──► window.parent.postMessage
        │                                                             │
        │  Ersatzweg, falls die Shell nicht antwortet:                ▼
        └─ eigener Hinweis im Panel (.panel-hinweis)     FriesenSpy.tsx: NotificationManager
                                                          .addNotification(createPermanent…)
```

Drei Punkte, die das Verhalten bestimmen:

- **Die Zuschauer-CID wird einmal beim Verbindungsaufbau aus `fs_user` gelesen.** Ohne Session
  gibt es keine `notify`-Ereignisse; `positions` bleibt öffentlich wie bisher.
- **Der Text wird im Panel aufbereitet** (`_panelMeldungstext` → `_translitText`), *bevor* er
  hochgereicht wird. Die EFB-Shell zeichnet ihn außerhalb unseres iframes — der
  MutationObserver, der sonst Umlaute und Emoji umschreibt, sieht ihn nie.
- **Ein ping/pong-Handshake** (`_initPanelShellKanal`) misst, ob `postMessage` die
  iframe-Grenze in Coherent GT überhaupt überquert; das Ergebnis landet als
  `panel_diag`-Datensatz `kind="shell"`. Solange die Shell nicht bestätigt hat, zeigt das
  Panel jede Meldung zusätzlich selbst an.

## Datenfluss TS-Login-Benachrichtigung (Phase 1)

```
TeamSpeak-Server (port 10011)
        │
        ▼  alle TS_POLL_INTERVAL Sekunden (Default: 30s)
  _poll_teamspeak (APScheduler Job: ts_poll)
        │
        ├─► fetch_channel_clients (ts3 ServerQuery, kurzlebige Verbindung)
        │         None  → Poll überspringen (Server nicht erreichbar, Snapshot bleibt)
        │         []    → gültiger leerer Kanal (Baseline oder Diff)
        │         [...]  → FRS-Clients im Kanal
        │
        ├─► self.ts_clients = clients  (Anzeige-Snapshot)
        │         → /api/teamspeak (Live-Tab-Panel) + /widget-Zähler; nach außen nur frs
        │         → ohne VAPID endet der Poll hier (reiner Display-Modus, keine Pushes)
        │
        ├─► Präsenz-Streak (_ts_streak)
        │         Erster Poll → Baseline (präsente FRS = _TS_BASELINE_STREAK), keine Notifications
        │         je präsenter FRS: streak += 1; abwesende fallen raus
        │         bestätigt = streak erreicht erstmals TS_MIN_DWELL_POLLS + 1
        │
        ├─► Pro bestätigter FRS:
        │         Debounce-Check (_ts_last_notified, TS_REJOIN_DEBOUNCE_SEC)
        │         subject_cid = cid_for_callsign_authoritative(frs)  (Forum-Map → flights/live/statsim)
        │         get_ts_push_subscriptions(conn, subject_cid) → notify_ts=1 ∩ pilot_filter
        │         visible_recipients(conn, subject_cid, …) → Subjekt-Sichtbarkeit (nobody/allowlist)
        │
        └─► send_web_push(recipients, payload)
                  Payload: {"title": "🎧 <nick> ist im TeamSpeak", "body": "FriesenFlieger TeamSpeak"}
```

**Subjekt-Sichtbarkeit:** Mitglieder stellen über den Board-Login in FriesenSpy selbst ein, wer über sie benachrichtigt wird (`pilot_visibility`, Modi `everyone`/`allowlist`/`nobody`) — für alle Push-Pfade + den Telegram-Online-Kanal. Die frühere `ts_consent`-Tabelle samt `manage_ts_consent.py` ist entfernt; bestehende DBs behalten die tote Tabelle unangetastet. Voraussetzung für die TS-Auflösung ist die beim Login gefüllte `forum_callsign`-Map; ist ein TS-Kürzel nicht auflösbar, greift die Sichtbarkeit dort nicht (Rollout-Voraussetzung: `sso.php` v2 aktiv, Callsign-Profilfelder gepflegt).

## Datenbankschema

```sql
CREATE TABLE pilots (
    cid       INTEGER PRIMARY KEY,
    name      TEXT,
    added_at  TEXT
);

CREATE TABLE flights (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cid           INTEGER REFERENCES pilots(cid),
    callsign      TEXT,
    aircraft_short TEXT,
    departure     TEXT,
    arrival       TEXT,
    logon_time    TEXT,
    logoff_time   TEXT,
    duration_min  INTEGER
);

CREATE TABLE live_positions (
    cid           INTEGER PRIMARY KEY,
    callsign      TEXT,
    aircraft      TEXT,
    departure     TEXT,
    arrival       TEXT,
    latitude      REAL,
    longitude     REAL,
    altitude      INTEGER,
    groundspeed   INTEGER,
    heading       INTEGER,
    logon_time    TEXT,
    updated_at    TEXT,
    -- Flugplan-Details (für Modal)
    flight_rules  TEXT,
    aircraft_icao TEXT,
    alternate     TEXT,
    deptime       TEXT,
    cruise_tas    TEXT,
    enroute_time  TEXT,
    fuel_time     TEXT,
    route         TEXT,
    remarks       TEXT
);

CREATE TABLE position_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cid         INTEGER NOT NULL REFERENCES pilots(cid),
    callsign    TEXT,
    latitude    REAL,
    longitude   REAL,
    altitude    INTEGER,
    groundspeed INTEGER,
    heading     INTEGER,
    ts          TEXT NOT NULL
);

-- StatSim-Historik-Cache (24h TTL, lazy per Pilot)
CREATE TABLE statsim_cache (
    statsim_id   INTEGER PRIMARY KEY,
    cid          INTEGER NOT NULL,
    callsign     TEXT,
    departure    TEXT,
    arrival      TEXT,
    aircraft     TEXT,
    logon_time   TEXT,
    logoff_time  TEXT,
    duration_min INTEGER,
    fetched_at   TEXT NOT NULL
);

-- FriesenFlieger Google-Kalender (alle 6h synchronisiert)
CREATE TABLE calendar_events (
    uid       TEXT PRIMARY KEY,
    summary   TEXT,
    dtstart   TEXT,
    dtend     TEXT,
    location  TEXT,
    route     TEXT,        -- CSV aller ICAOs der Strecke (FriesenFliegerBummel)
    is_bummel INTEGER DEFAULT 0
);

-- Browser-Push-Subscriptions für Web Push Notifications
CREATE TABLE push_subscriptions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint       TEXT UNIQUE NOT NULL,
    p256dh         TEXT NOT NULL,
    auth           TEXT NOT NULL,
    pilot_filter   TEXT DEFAULT NULL,    -- JSON-Array von CIDs oder NULL = alle
    notify_prefiles INTEGER DEFAULT 0,  -- 1 = auch Prefile-Änderungen benachrichtigen
    notify_ts      INTEGER DEFAULT 0,   -- 1 = TS-Login-Benachrichtigungen erwünscht
    notify_events  INTEGER DEFAULT 0,   -- 1 = Event-Erinnerungen + Bummel-Start/Ergebnis-Push
    ts_self_frs    TEXT,                -- tote Spalte: bleibt in Alt-DBs, wird nicht mehr beschrieben
    created_at     TEXT NOT NULL
);

-- Letzte Prefile-Signaturen pro CID (persistiert für Neustart-Robustheit)
CREATE TABLE prefile_sigs (
    cid       INTEGER PRIMARY KEY,
    deptime   TEXT,
    departure TEXT,
    arrival   TEXT,
    saved_at  TEXT
);

-- Hinweis: 'ts_consent' (Phase 1) ist aus dem Schema entfernt — 'pilot_visibility' hat es
-- abgelöst. Bestehende DBs behalten die Tabelle unangetastet; kein Code liest oder schreibt
-- sie noch. Neue DBs legen sie nicht mehr an.

-- Persistente FriesenFliegerBummel-Rennen (vom Poller beim Kalender-Sync oder Admin manuell angelegt)
CREATE TABLE bummel_races (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    route        TEXT NOT NULL,          -- CSV der Strecken-ICAOs, z. B. "EDWF,EDWG,EDWR"
    dtstart      TEXT NOT NULL,          -- ISO8601 UTC — Termin-Beginn aus dem Kalender
    dtend        TEXT NOT NULL,          -- ISO8601 UTC — effektiver Renn-Endtermin:
                                         --   aus Kalender übernommen; fehlt dtend im Termin
                                         --   → Mitternacht UTC des Folgetags (_effective_dtend)
    radius_km    REAL DEFAULT 10.0,      -- Legacy-Spalte (#23): seit GPS-only Phase 2 wirkungslos,
                                         --   über Admin-Endpoints nicht mehr setzbar; die Platz-
                                         --   Zuordnung nutzt überall den festen globalen 4-km-Radius
                                         --   (_BUMMEL_AIRPORT_RADIUS_KM im GPS-Leg-Detektor)
    source       TEXT DEFAULT 'calendar', -- 'calendar' | 'manual'
    calendar_uid TEXT UNIQUE,            -- UID aus calendar_events (NULL für manuelle Einträge)
    revealed_at  TEXT DEFAULT NULL,      -- NULL = Ergebnisse noch verborgen;
                                         -- Zeitstempel = Enthüllungs-Latch (einmal gesetzt, nie zurückgesetzt)
    started_at   TEXT DEFAULT NULL,      -- NULL = noch kein Start;
                                         -- Zeitstempel = Start-Latch (erster Pilot mit Blockzeit, nie zurückgesetzt)
    push_enabled INTEGER DEFAULT 1,      -- 1 = Start- und Enthüllungs-Push aktiv; 0 = deaktiviert
    reveal_suppressed INTEGER DEFAULT 0, -- 1 = manuell verborgen, übersteuert den Auto-Reveal
    created_at   TEXT NOT NULL
);

-- Admin-Korrekturen pro Rennen + Pilot (PK race_id + cid)
CREATE TABLE bummel_overrides (
    race_id          INTEGER NOT NULL REFERENCES bummel_races(id) ON DELETE CASCADE,
    cid              INTEGER NOT NULL,
    action           TEXT NOT NULL,      -- exclude | disqualify | winner | manual
    manual_total_min INTEGER DEFAULT NULL, -- Manuelle Block-Zeit in Minuten (nur bei action = 'manual')
    note             TEXT,               -- Optionale interne Notiz
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (race_id, cid)
);

-- Event-Erinnerungen (Latch: einmal gesendet, nie erneut)
CREATE TABLE event_reminders_sent (
    uid      TEXT PRIMARY KEY,   -- Kalender-Event-UID (aus calendar_events.uid)
    sent_at  TEXT NOT NULL       -- ISO8601 UTC
);

-- Generischer Key-Value-Store (App-Einstellungen, z. B. banner_version)
CREATE TABLE app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);
```
