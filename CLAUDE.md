# FriesenSpy

VATSIM Live-Tracker für die FriesenFlieger-Gruppe.

## Stack

Python 3.11, FastAPI, APScheduler, SQLite (WAL), httpx, pydantic-settings, airportsdata, ts3

## Lokale Entwicklung

```bash
pip install -r requirements.txt
# config.env anlegen (SECRET_KEY erforderlich; Friesen-Erkennung via CALLSIGN_PREFIX=FRS)
uvicorn app.main:app --reload
# http://localhost:8091
```

## Tests

```bash
pytest tests/ -v
```

## Deployment

GitHub Push → main-Branch → GitHub Actions → GHCR → SSH-Deploy auf VPS

- Container: `ghcr.io/regover13/friesenspy:latest`
- Port: 8091 (intern), friesenspy.devprops.de (extern)
- DB: `/opt/friesenspy/data/friesenspy.db` (Volume)
- Config: `/opt/friesenspy/config.env` (niemals in git!)

## VPS-Einrichtung (einmalig)

```bash
mkdir -p /opt/friesenspy/data
# config.env anlegen mit echten CIDs + Token
# nginx-Config: nginx/friesenspy.devprops.de.conf einbinden
# certbot: certbot --nginx -d friesenspy.devprops.de
```

## UI-Standards (stehende Regeln — IMMER einhalten)

- **Blau (#2d9cdb, CSS-Variable `--green` — historischer Name!) ist Klickbarem vorbehalten:**
  Links, klickbare Strecken-Zellen, klickbare Zeilen. Callsigns und andere reine Anzeige-Texte
  bleiben neutral (weiß/mono) — „blau = da passiert was beim Klick" muss überall stimmen.
- **Breite Tabellen/Feeds sind auf dem Smartphone horizontal scrollbar, nie gequetscht:**
  jede Tabelle gehört in einen Wrapper mit `overflow-x: auto; -webkit-overflow-scrolling: touch`,
  und die Tabelle selbst braucht `width: max-content; min-width: 100%` (sonst hat der Wrapper
  nichts zu scrollen). Fertige Klassen: `.table-scroll` (index.html), `.table-wrap` (admin.html).
  Gilt ausdrücklich auch für alle NEUEN Ansichten (z. B. kommende Kutter-Live-Ansicht).
  **Flexbox-Falle (v8.6.5-Fund):** liegt der Wrapper in einem Flex-Container (z. B. `#app` in
  admin.html, `display:flex; flex-direction:column`), reicht `.table-wrap`/`.table-scroll`
  allein NICHT — Flex-Items dürfen sich per CSS-Default nicht unter ihre Inhaltsbreite
  schrumpfen (`min-width:auto`), eine breite Tabelle sprengt dann das ganze Flex-Item und
  `overflow-x:hidden` am `body` schneidet den Überstand einfach ab, statt dass die innere
  Scrollbar greift. Jeder Flex-Item-Container um eine scrollbare Tabelle braucht zusätzlich
  `min-width: 0` (in admin.html bereits auf `.panel` gesetzt).
  **Verschachtelungs-Falle (v8.6.6-Fund, wichtiger als die Flexbox-Falle oben):** steckt
  `.table-wrap` INNERHALB einer vertikal begrenzten `.scroll-list` (`max-height:280px;
  overflow-y:auto` — Piloten/Flugplätze/Erkennungslücken), braucht `.table-wrap` selbst
  ZWINGEND dieselbe Höhenbegrenzung (`.scroll-list .table-wrap { max-height: 280px; overflow:
  auto; }`). Ohne sie ist `.table-wrap` so hoch wie die GESAMTE Tabelle (bei vielen Zeilen
  mehrere tausend Pixel) — seine horizontale Scrollbar sitzt dann an SEINEM EIGENEN unteren
  Rand, weit unterhalb des durch `.scroll-list` sichtbar gemachten 280-px-Fensters, und ist
  praktisch nie zu sehen (auch mit korrektem `overflow-x:auto`!). **Zusätzlich (unabhängiges
  zweites Problem, gleicher Fund):** Windows/Edge/Chrome blenden eine technisch korrekt
  scrollende Box trotzdem unsichtbar, wenn keine Scrollbar-Styles gesetzt sind (Overlay-
  Scrollbar, nur bei aktivem Hover/Scrollen sichtbar) — `scrollbar-width`/`scrollbar-color`
  (Firefox) + `::-webkit-scrollbar*` (Chrome/Edge/Safari) erzwingen eine dauerhaft sichtbare
  Leiste. Beide Fixes sind nötig, einer allein reicht nicht — vor jeder neuen scrollbaren
  Tabelle in `.scroll-list` beide prüfen. Bei vielen Spalten zusätzlich erwägen, Aktionen-
  Buttons in eine eigene Zeile UNTER die Daten zu legen (`colspan`), statt in eine Spalte ganz
  rechts, die sonst erst nach Scrollen erreichbar ist (Erkennungslücken-Muster).

## Projektstruktur

- `app/config.py` — pydantic-settings, CALLSIGN_PREFIX (Friesen-Erkennung), ADMIN_PASSWORD, VAPID
- `app/database.py` — SQLite WAL, alle DB-Funktionen
- `app/vatsim.py` — VATSIM-API-Client
- `app/geo.py` — Haversine, ICAO→Koordinaten, Event-Filter
- `app/alerts.py` — Telegram-Alerts (silent fail)
- `app/teamspeak.py` — TeamSpeak-ServerQuery-Client (parse_frs, fetch_channel_clients)
- `app/poller.py` — APScheduler, Flug-State-Machine, SSE-Queue
- `app/main.py` — FastAPI-App, REST + SSE-Endpoints
- `app/static/index.html` — Vanilla-JS-SPA (4 Tabs)

## Konfiguration (config.env — NIE in git)

```bash
# Friesen werden über das Callsign-Präfix erkannt (NICHT über eine CID-Liste).
CALLSIGN_PREFIX=FRS              # Default: FRS
SECRET_KEY=<random-string>
TELEGRAM_BOT_TOKEN=          # Optional
TELEGRAM_CHAT_ID=            # Optional
VATSIM_POLL_INTERVAL=15
VATSIM_REJOIN_DEBOUNCE_SEC=900   # Default: 900 s (15 min) — Reconnect-Fenster Online-Push
LOG_LEVEL=INFO                   # Default: INFO — App-Logger sichtbar (unter uvicorn sonst nur WARNING+)
DB_PATH=/opt/friesenspy/data/friesenspy.db
ANTHROPIC_API_KEY=               # Optional — FriesenKutter-Zuladungs-Vorschlag (Claude Sonnet 5 + Web-Search); denselben Key wie TSBot verwenden

# TeamSpeak-Login-Benachrichtigung (Phase 1, alle Optional)
TS_NOTIFY_ENABLED=false      # Default: false — Feature aktivieren
TS_HOST=127.0.0.1            # Default: 127.0.0.1
TS_QUERY_PORT=10011          # Default: 10011
TS_QUERY_USER=               # ServerQuery-Login
TS_QUERY_PASS=               # ServerQuery-Passwort
TS_SERVER_ID=1               # Default: 1
TS_NOTIFY_CHANNEL_ID=0       # Default: 0 = ganzer Server; sonst Kanal-ID
TS_EXCLUDE_CHANNEL_IDS=      # CSV Kanal-IDs, die nie benachrichtigen (z. B. Verwaltung)
TS_MIN_DWELL_POLLS=1         # Verweildauer: muss beim Folge-Poll noch da sein (0 = sofort)
TS_POLL_INTERVAL=30          # Default: 30 Sekunden
TS_REJOIN_DEBOUNCE_SEC=900   # Default: 900 s (15 min) Debounce gegen Re-Join-Spam
```

Hinweis: Der `ts_poll`-Job läuft jetzt, sobald `TS_NOTIFY_ENABLED=true` (Live-Anzeige im
Live-Tab + Widget-Zähler, gespeist aus `poller.ts_clients` via `/api/teamspeak`). VAPID ist
nur noch für Push-Benachrichtigungen nötig, nicht für die Anzeige.

## Cloud-Session: wenn CLI-`git` kein Credential hat (Fallback)

In einer Claude-Code-**Cloud-Session** (claude.ai/code) bekommt CLI-`git` normalerweise ein
kurzlebiges, scoped GitHub-Installations-Token über den Proxy — es liegt KEIN Key/PAT dauerhaft
im Container (so soll es sein). Schlägt die Token-Ausstellung beim Container-Start fehl, stehen in
`GITHUB_TOKEN`/`GH_TOKEN` nur Platzhalter und `git push/fetch` bricht mit
`could not read Username/Password … terminal prompts disabled` ab. Das ist ein
Provisionierungs-Fehler der Session, **kein** Repo-, Netz- oder Setup-Bug (github.com ist über den
Egress-Proxy erreichbar; MCP-GitHub-Tools funktionieren derweil weiter, anderer Auth-Pfad).

**Schnelltest zu Session-Beginn:** `git ls-remote origin` — geht das ohne Prompt, geht auch `push`.

**Recovery, in dieser Reihenfolge:**
1. **Dauerhafter Fix (nur der Nutzer):** GitHub-App-Verbindung in claude.ai/code → GitHub-Integration
   für `regover13/friesenspy` neu autorisieren. Danach stellt jede neue Session ihr Token wieder
   korrekt aus. Das ist der eigentliche Hebel — aus der Session heraus NICHT reparierbar.
2. **Frische Cloud-Session** starten (war es ein einmaliger Ausstellungs-Fehler, ist sie sauber).
3. **Ohne CLI-git trotzdem liefern:** Doku/Einzeldateien via GitHub-**MCP-Tools** direkt committen;
   ganze Code-Stände über den **Bundle-Weg** übergeben. Beides funktioniert nachweislich.
4. NICHT tun: 8× mit Backoff retryen, Session-Ingress-Token als Credential missbrauchen, oder
   dauerhaft einen PAT/SSH-Key in der Cloud hinterlegen.

**Signatur-„Fehler" `%G? = N` ist ein False Positive:** Die Commit-Signatur-Prüfung passiert im
Cloud-**Harness**, nicht im Repo (dieses Repo hat KEINE eigenen git-Hooks und keine
`gpg.ssh.allowedSignersFile`). Der Sandbox fehlt nur die `allowedSignersFile` für die lokale
*Verifikation* — die Commits tragen trotzdem eine gültige SSH-Signatur. Kein History-Rewrite
deswegen (ändert nur SHAs bereits gepushter Branches).
