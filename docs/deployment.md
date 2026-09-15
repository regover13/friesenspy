# Deployment

## Automatisch (via GitHub Actions)

Jeder Push auf `main` triggert den CI/CD-Pipeline:

1. `docker build` → Image `ghcr.io/regover13/friesenspy:latest`
2. Push nach GHCR (GitHub Container Registry)
3. SSH auf VPS: `docker compose pull && docker compose up -d`

Der Container läuft als non-root User `friesenspy` (UID 1001).

## Was ein Deploy kostet — und warum das HTTP 502 erzeugt

Ein Deploy ersetzt den Container. In dem Fenster dazwischen antwortet niemand, und nginx
meldet dem Aufrufer **HTTP 502**. Das ist kein Fehler, sondern der Neustart selbst — wer
502er auswertet, muss sie abziehen.

Gemessen am 15.09.2026 über zwei Tage: **Alle 839 Upstream-Fehler lagen im Fenster eines
Deploys, kein einziger daneben** (41 Deploys, davon 25 mit laufenden Clients). Die Größe
des Fensters ist jedes Mal dieselbe:

| Abschnitt | vor dem 15.09.2026 | seither |
|---|---|---|
| alter Container beendet sich | ~10 s (endete mit **SIGKILL**) | ~3 s, sauber |
| neuer Container startet die App | ~7 s | ~7 s |
| **Summe** | **16–20 s** | **~10 s** |

Die 10 Sekunden waren Dockers Gnadenfrist: uvicorn wartet beim Beenden auf das Ende aller
laufenden Antworten, und `/api/sse` liefert einen Stream, der nie endet. Eine einzige offene
SSE-Verbindung hielt den Container deshalb fest, bis `SIGKILL` kam — die App wurde also bei
**jedem** Deploy mitten im Schreiben nach SQLite abgeschossen. Behoben mit
`--timeout-graceful-shutdown 3` im `CMD` des Dockerfiles; die Begründung steht dort
ausführlich, bewacht wird es von `tests/test_deploy_shutdown.py`.

⚠ **`stop_grace_period` in `docker-compose.yml` zu erhöhen wäre der falsche Griff** — das
verlängert nur das Warten, statt es zu beenden.

**Die verbleibenden ~7 Sekunden sind der App-Start** (FSE-Bestand mit 23.780 Plätzen,
6.121 Meldepunkte, Platzrunden). Sie sind noch offen; ein Deploy ohne Ausfall bräuchte einen
zweiten Container, und dem steht die gemeinsame SQLite-Datei im Weg.

**Wer im Sekundentakt meldet, merkt das als Erster.** Für die FriesenBrügge ist jede dieser
Sekunden eine verlorene Meldung — ihr Punkt auf der Karte friert so lange ein. Deshalb gilt:
**nicht in den laufenden Betrieb deployen**, wenn jemand fliegt.

## Manuell auf dem VPS

```bash
ssh root@167.86.127.129
cd /opt/friesenspy
docker compose pull
docker compose up -d
```

## Logs einsehen

```bash
docker logs friesenspy-friesenspy-1 -f
```

## Container neu starten (config.env-Änderungen)

```bash
cd /opt/friesenspy
docker compose up -d --force-recreate
```

**Wichtig:** `docker restart` liest `env_file` nicht neu ein. Immer `docker compose up -d` benutzen wenn `config.env` geändert wurde.

## config.env

Die Datei liegt auf dem VPS unter `/opt/friesenspy/config.env` und wird **niemals** in Git eingecheckt.

```bash
SECRET_KEY=<random-hex-32>
CALLSIGN_PREFIX=FRS
VATSIM_POLL_INTERVAL=15
DB_PATH=/opt/friesenspy/data/friesenspy.db
TELEGRAM_BOT_TOKEN=        # leer = kein Alert
TELEGRAM_CHAT_ID=          # leer = kein Alert
```

`SECRET_KEY` generieren:
```bash
openssl rand -hex 32
```

## Datenbank

SQLite-Datei liegt im gemounteten Volume: `/opt/friesenspy/data/friesenspy.db`

Backup:
```bash
sqlite3 /opt/friesenspy/data/friesenspy.db ".backup /tmp/friesenspy_backup.db"
```

## nginx

Konfiguration in `nginx/friesenspy.devprops.de.conf`:

- `/api/sse`: Kein Rate-Limit, `proxy_read_timeout 3600s`, `X-Accel-Buffering: no`
- Alle anderen Endpoints: Rate-Limit 30req/min, `proxy_pass http://127.0.0.1:8091`

## Telegram-Alerts einrichten (optional)

1. Bot erstellen via [@BotFather](https://t.me/BotFather) → Token kopieren
2. Bot in gewünschte Gruppe einladen
3. Chat-ID ermitteln: `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. In `config.env` eintragen und Container neu erstellen

## GitHub Secrets

| Secret | Beschreibung |
|--------|--------------|
| `VPS_SSH_KEY` | Privater SSH-Key (ohne Passphrase) für `root@167.86.127.129` |
| `GHCR_TOKEN` | GitHub PAT mit `write:packages` Berechtigung |

Secrets setzen (PowerShell):
```powershell
Get-Content -Raw ~/.ssh/tsbot_server | gh secret set VPS_SSH_KEY
```

## Rollback

```bash
# Vorheriges Image taggen und deployen
docker pull ghcr.io/regover13/friesenspy:<sha>
docker tag ghcr.io/regover13/friesenspy:<sha> ghcr.io/regover13/friesenspy:latest
cd /opt/friesenspy && docker compose up -d
```
