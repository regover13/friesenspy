# TS-Login-Benachrichtigung in FriesenSpy — Design (Phase 1)

Datum: 2026-06-18 · Status: zur Umsetzung freigegeben · Scope: Phase 1 (Kern)

## Context

Die FriesenFlieger wollen wissen, wenn jemand im TeamSpeak-Server erscheint —
ohne dafür wie TSBot einen TS-Client in Wine/Xvfb laufen zu lassen. Das ist möglich:
TS3 bietet die **ServerQuery** (Port 10011), ein rein server-seitiges Telnet-Admin-Protokoll.
TSBot nutzt sie bereits (`bot/ts_query.py`) für Teilnehmer-Tracking — kein Client, kein Audio,
kein Wine nötig. FriesenSpy hat mit APScheduler-Poller + WebPush (VAPID) + SQLite bereits die
komplette Benachrichtigungs-Infrastruktur. Es fehlt nur ein TS-Modul, das den ServerQuery-Stand
pollt und bei Kanal-Beitritt eine WebPush-Nachricht auslöst.

Zusätzlich soll der **Inhaber einer FRS-Nummer selbst steuern**, ob bzw. an wen eine
Benachrichtigung über sein Erscheinen rausgeht (Datenschutz/Einwilligung). Die maßgebliche
Self-Service-Quelle dafür (Forum-Custom-Flag) liegt aber auf fremder IONOS-Infra und ist nur
umständlich erreichbar → **bewusste Phasen-Trennung**:

- **Phase 1 (dieses Dokument):** TS-Beitritt → WebPush, voll auf dem devprops-VPS, mit lokaler
  Einwilligungs-Tabelle (`ts_consent`), die der Admin zunächst selbst seedet.
- **Phase 2 (separat, später):** Forum-Custom-Flag (oder TS-Opt-out-Kanal) als Self-Service-Quelle,
  die per Sync-Job die lokale `ts_consent`-Tabelle füllt. Kern bleibt unverändert.

## Entscheidungen (bestätigt mit User)

- Kanal: **WebPush** (PWA), nicht Telegram.
- Auslöser: **Beitritt in einen konfigurierten Kanal** (nicht jeder Server-Login). `0` = ganzer Server.
- Kein Web-UI für die Anzeige — reine Benachrichtigung.
- Einwilligung ist **subjekt-kontrolliert**: pro FRS-Nummer `alle` / `niemand` / `allowlist`.
- Identitäts-/Consent-Anker: **FRS-Nummer** (menschenlesbar, deckt sich mit Forum + Empfänger-Denken;
  geparst wie in `bot/ts_query.py` via `FRS(\d+[A-Z]?)`).
- Erkennung per **Poll-Diff** (kurzlebige ServerQuery-Verbindung je Intervall), passt zum
  bestehenden APScheduler-Muster und braucht keinen dauerhaften Event-Thread.
- Default-Einwilligung: **`everyone`** (wer nicht in `ts_consent` steht, löst Pings aus). Bei
  Bedarf auf Privacy-by-default (`nobody`) umstellbar — offener Punkt für die Freigabe.

## Architektur (Phase 1)

Datenfluss:
```
APScheduler-Job (alle ~30 s)
  └─ teamspeak.fetch_channel_clients()  ── ServerQuery 10011 (kurzlebige Verbindung, im Executor)
       └─ Diff gegen letzten Stand  → neue FRS-Beitritte
            └─ pro neuem FRS_J:  consent-Regel + Debounce  → Empfängerliste
                 └─ send_web_push (vorhandene VAPID-Infra)
```

Komponenten (neue/erweiterte Dateien, Projekt-Wurzel = `FriesenSpy/`):

1. **`app/teamspeak.py` (neu)** — ServerQuery-Client.
   - `async fetch_channel_clients(...) -> list[dict]` mit `{frs, nick, cid}` der Clients im
     Zielkanal. Nutzt die `ts3`-Lib (wie TSBot) in `loop.run_in_executor`, **kurzlebige Verbindung**
     pro Aufruf (connect → login → use sid → clientlist → close). Bei `channel_id == 0`: ganzer Server.
   - `parse_frs(nick) -> str | None` — portiert die Parser-Logik aus `bot/ts_query.py:_parse_nickname`
     (`FRS(\d+[A-Z]?)`, diverse Trennzeichen/Klammer-Suffixe). Eigene kleine Funktion + Tests.

2. **`app/database.py` (erweitern)** — neue Tabelle + Migrationen.
   - `CREATE TABLE ts_consent (frs TEXT PRIMARY KEY, visibility TEXT DEFAULT 'everyone',
     allowlist TEXT, updated_at TEXT)` — `visibility ∈ {'everyone','nobody','allowlist'}`,
     `allowlist` = JSON-Liste von Empfänger-FRS. **Kein Eintrag = 'everyone'** (benachrichtigen).
   - Push-Migrationen erweitern (analog `_PUSH_MIGRATIONS`):
     `ALTER TABLE push_subscriptions ADD COLUMN notify_ts INTEGER DEFAULT 0` (Empfänger-Opt-in)
     und `ADD COLUMN ts_self_frs TEXT` (eigene FRS-Nummer des Abonnenten → für allowlist-Zielung
     und optionales Selbst-Überspringen).
   - Helper: `get_ts_consent(conn, frs)`, `upsert_ts_consent(conn, frs, visibility, allowlist)`,
     `get_ts_push_subscriptions(conn)` (alle mit `notify_ts = 1`).

3. **`app/ts_notify.py` (neu)** — Zustell-Logik (reine Funktion, gut testbar).
   - `recipients_for(consent: dict|None, opted_in_subs: list[dict], joining_frs: str) -> list[dict]`:
     - `visibility == 'nobody'` → `[]`.
     - `visibility == 'everyone'` (oder kein Eintrag) → alle opted-in Subs.
     - `visibility == 'allowlist'` → nur Subs mit `ts_self_frs ∈ allowlist`.
     - In allen Fällen optional Subs mit `ts_self_frs == joining_frs` überspringen (kein Selbst-Ping).

4. **`app/poller.py` (erweitern)** — neuer Job in `VatsimPoller`.
   - `add_job(self._poll_teamspeak, "interval", seconds=ts_poll_interval, id="ts_poll")` (nur wenn
     `TS_NOTIFY_ENABLED` und VAPID konfiguriert).
   - `_poll_teamspeak`: aktuelle FRS-Menge im Kanal holen; `newly_joined = current - self._ts_last_seen`;
     Debounce über `self._ts_last_notified[frs]` (kein erneuter Ping innerhalb `TS_REJOIN_DEBOUNCE_SEC`);
     **erster Poll nach Start = Baseline ohne Notifications** (Muster wie `_prefile_sigs is None`);
     pro Treffer `recipients_for(...)` + Push-Versand. Exceptions nur loggen.
   - `send_web_push_notifications` aus `poller.py` so verallgemeinern, dass sie eine fertige
     Subscription-Liste + ein Payload-Dict entgegennimmt (heute fix an `get_push_subscriptions_for_pilot`
     gekoppelt) — die VATSIM-Aufrufstelle bleibt funktional gleich.

5. **`app/config.py` (erweitern)** — neue Settings (mit Defaults):
   `TS_NOTIFY_ENABLED=False`, `TS_HOST=127.0.0.1`, `TS_QUERY_PORT=10011`, `TS_QUERY_USER`,
   `TS_QUERY_PASS`, `TS_SERVER_ID=1`, `TS_NOTIFY_CHANNEL_ID` (0=ganzer Server),
   `TS_POLL_INTERVAL=30`, `TS_REJOIN_DEBOUNCE_SEC=900`.

WebPush-Payload (Beispiel): Titel `🎧 {nick} ist im TeamSpeak`, Body = Kanalname (aus ServerQuery
`channellist`/Cache), `url:"/"`. Reuse der vorhandenen VAPID-Konstanten/`pywebpush`-Logik.

## Fehlerbehandlung

- ServerQuery nicht erreichbar / Login-Fehler → loggen, Poll überspringen (kein Crash; Muster wie
  `_poll_once`, das alle Exceptions schluckt).
- WebPush: Silent-Fail + 410-Endpoint-Cleanup ist bereits vorhanden → wiederverwenden.
- `ts_poll`-Job läuft unabhängig vom VATSIM-Poll; ein Fehler im einen blockiert den anderen nicht.

## Tests (`tests/`)

- `test_teamspeak.py` — `parse_frs`: FRS-Varianten (vor/nach Name, Trennzeichen, `(MSFS2024)`-Suffix,
  kein FRS → None). ServerQuery-Aufruf gemockt → Filter auf Zielkanal korrekt.
- `test_ts_notify.py` — `recipients_for`: `everyone`/`nobody`/`allowlist`, fehlender Consent-Eintrag,
  Selbst-Überspringen.
- `test_poller.py` (ergänzen) — Poll-Diff erkennt neue Beitritte; Baseline beim ersten Poll erzeugt
  keine Notifications; Debounce unterdrückt Re-Join innerhalb des Fensters.
- `test_database.py` (ergänzen) — `ts_consent` CRUD + Migrationen idempotent.

## Deployment (Phase 1)

- FriesenSpy-Container (devprops-VPS) muss **TS_HOST:10011 erreichen**. Der TS-Server läuft auf
  demselben VPS (TSBot nutzt `TS_HOST=127.0.0.1`) → ServerQuery-IP-Whitelist um die FriesenSpy-
  Container-/Host-Adresse erweitern und Query-Zugangsdaten in `/opt/friesenspy/config.env` setzen.
- `ts3`-Lib zu `requirements.txt` hinzufügen.
- Verifikation end-to-end: Config mit kleinem Debounce setzen → mit TS-Client (oder Testidentität)
  den Zielkanal betreten → WebPush-Empfang auf einem abonnierten Gerät prüfen; `nobody`/`allowlist`
  für eine FRS in `ts_consent` setzen und Unterdrückung/Zielung gegenprüfen.

## Ausblick Phase 2 (nicht in diesem Dokument umgesetzt)

- Self-Service-Quelle für `ts_consent`: **Forum-Custom-Flag** (phpBB-Profilfeld auf IONOS) via
  HTTP-Scrape öffentlicher Profile **oder** phpBB-Extension/JSON-Endpoint; alternativ TS-nativer
  **Opt-out-Kanal/Bot-Kommando** (authentifiziert über die TS-UID, braucht aber Bot-Client).
- Sync-Job schreibt nur in die lokale `ts_consent`-Tabelle — der Phase-1-Kern bleibt unverändert.
- Optional Empfänger-Identität (`ts_self_frs`) verlässlich an Forum-Account koppeln.
