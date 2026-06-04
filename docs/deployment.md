# Deployment

## Automatisch (via GitHub Actions)

Jeder Push auf `main` triggert den CI/CD-Pipeline:

1. `docker build` → Image `ghcr.io/regover13/friesenspy:latest`
2. Push nach GHCR (GitHub Container Registry)
3. SSH auf VPS: `docker compose pull && docker compose up -d`

Der Container läuft als non-root User `friesenspy` (UID 1001).

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
