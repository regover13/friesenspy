# Subjekt-Sichtbarkeit — „Wer darf über mich benachrichtigt werden?" — Design

Datum: 2026-07-13 · Status: Entwurf, zur Abnahme · Scope: mittel · Abhängigkeit: **Board-Login (Forum-SSO)** muss aktiv sein (liefert die Identität).

## Context

FriesenSpy hat heute nur die **Empfänger-Achse**: jedes Push-Abo wählt über `pilot_filter`
(CID-Liste, `NULL` = alle), über **wen** es benachrichtigt werden will (Online, Flugplan,
TeamSpeak — vereinheitlicht in `2026-06-18-einheitlicher-empfaengerfilter-design.md`).

Was fehlt, ist die **Subjekt-Achse**: ein Mitglied soll selbst bestimmen, **wer über die eigene
Aktivität benachrichtigt werden darf**. Drei Modi:

| Modus | Wirkung |
|---|---|
| **everyone** (Default) | jeder passende Abonnent wird benachrichtigt (heutiges Verhalten) |
| **allowlist** | nur ausgewählte Mitglieder |
| **nobody** | niemand (Voll-Opt-out) |

Das Feature wird durch den **Forum-Login** möglich: erst dadurch kennt FriesenSpy die
Identität (VATSIM-CID) des eingeloggten Nutzers und — neu — dessen **FRS-Callsign(s)** aus den
phpBB-Profilfeldern. Die Callsign-Kenntnis ist **autoritativ** und löst das
Eindeutigkeitsproblem (kein Raten aus der Flughistorie mehr).

Eine schon vorhandene, aber nie per UI setzbare Tabelle `ts_consent` (`everyone/nobody/allowlist`
je FRS) war der Keim dieses Features; sie wird **abgelöst** (siehe unten). Laut Nutzer existieren
**keine** produktiven `ts_consent`-Zeilen → **keine Migration** nötig.

## Entscheidungen (mit Nutzer bestätigt)

- **Voller Scope:** alle drei Modi inkl. Mitglieder-Picker („Nur bestimmte").
- **Identität = CID** (aus dem Forum-Login). Die Subjekt-Sichtbarkeit wird an die **CID** gekeyt,
  nicht ans Callsign — stabil über Callsign-Wechsel hinweg.
- **Callsign(s) autoritativ aus dem Forum:** `sso.php` v2 legt `phpbb_callsign` + `phpbb_last_cs`
  (+ `phpbb_alt_cs`, falls gesetzt) ins Login-Token; der Callback speichert sie als
  Callsign→CID-Map. Bestätigt read-only: Feld ist befüllt, FRS-Format (z. B. `FRS49`, zweit
  `FRS49N`).
- **Abo-Besitzer:** Push-Abos bekommen einen `owner_cid`; serverseitig aus dem `fs_user`-Cookie
  gesetzt (nie aus dem Request-Body). Nur „allowlist" braucht ihn; „everyone"/„nobody" nicht.
- **`ts_consent` wird abgelöst** (nicht mehr gelesen/geschrieben). Tabelle bleibt als tote
  Struktur liegen (kein Migrationszwang). Der TS-Poller-Check wandert auf `pilot_visibility`.
- **Nur Push** wird beeinflusst — die Live-Sichtbarkeit (Karte/Liste/Statistik) bleibt unberührt.
- **`sso.php` v2 wird selbst ausgerollt** (Desktop-Datei ändern → per `ssh`/`scp` auf den
  Forum-Server), kein erneuter Micha-Handoff.

## Architektur

### Datenmodell (`app/database.py`, im `CREATE`-Block + `MIGRATIONS`)

```sql
CREATE TABLE IF NOT EXISTS pilot_visibility (
    cid        INTEGER PRIMARY KEY,
    mode       TEXT NOT NULL DEFAULT 'everyone',   -- 'everyone' | 'allowlist' | 'nobody'
    allowlist  TEXT,                               -- JSON-Liste erlaubter CIDs (nur bei 'allowlist')
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS forum_callsign (
    callsign   TEXT PRIMARY KEY,                   -- UPPER, getrimmt (z. B. 'FRS49N')
    cid        INTEGER NOT NULL,
    updated_at TEXT
);
```

`push_subscriptions` bekommt per Migration eine Spalte:
```sql
ALTER TABLE push_subscriptions ADD COLUMN owner_cid INTEGER DEFAULT NULL;
```

Kein Eintrag in `pilot_visibility` = Default `everyone`.

### DB-Funktionen (neu/geändert, `app/database.py`)

- `get_pilot_visibility(conn, cid) -> dict | None` — `{mode, allowlist:[int,…]}` oder `None`
  (= Default everyone). `allowlist` JSON-geparst, defekt → `[]`.
- `set_pilot_visibility(conn, cid, mode, allowlist=None)` — Upsert; `mode` ∈
  {`everyone`,`allowlist`,`nobody`}; bei `everyone`/`nobody` wird `allowlist` auf `NULL` gesetzt.
- `upsert_forum_callsign(conn, callsign, cid)` — Upsert eines Callsign→CID-Eintrags (UPPER/trim).
- `cid_for_callsign_authoritative(conn, callsign) -> int | None` — zuerst `forum_callsign`,
  sonst Fallback auf das bestehende `cid_for_callsign` (live/flights/statsim).
- `upsert_push_subscription(...)` — zusätzlicher Parameter `owner_cid: int | None = None`
  (in INSERT + `ON CONFLICT … DO UPDATE SET owner_cid=excluded.owner_cid`, aber **nur wenn
  nicht NULL** überschreiben — s. u. „Backfill").
- `set_push_subscription_owner(conn, endpoint, owner_cid)` — setzt `owner_cid` für ein
  bestehendes Abo (Backfill beim Öffnen der App als eingeloggter Nutzer).
- `get_push_subscriptions_for_pilot` / `_for_prefile` / `get_ts_push_subscriptions` — geben
  zusätzlich `owner_cid` je Zeile zurück (für die allowlist-Prüfung).
- `list_visibility_pilots(conn) -> list[dict]` — Kandidaten für den Picker (siehe Frontend);
  kann `/api/stats`-Pilotenquelle spiegeln oder `list_pilots` nutzen — Plan pinnt die konkrete
  Quelle. Muss `cid` + Anzeige-Callsign/Name liefern.

### Durchsetzung — ein Helfer, drei Sendepfade (`app/poller.py`)

Neuer Helfer in **`app/database.py`** (pur, testbar; wird von poller.py importiert):

```python
def visible_recipients(conn, subject_cid, recipients):
    """Filtert Empfänger nach der Subjekt-Sichtbarkeit von subject_cid.
    recipients: Liste dicts mit mind. 'endpoint','p256dh','auth','owner_cid'."""
    if subject_cid is None:
        return recipients                      # unbekanntes Subjekt → keine Einschränkung
    vis = get_pilot_visibility(conn, subject_cid)
    if not vis or vis["mode"] == "everyone":
        return recipients
    if vis["mode"] == "nobody":
        return []
    allow = set(vis["allowlist"])              # 'allowlist'
    return [r for r in recipients if r.get("owner_cid") in allow]
```

- **Online** (`send_web_push_notifications`): `subject_cid = pilot["cid"]`; nach dem Laden der
  Subscriptions durch `visible_recipients` filtern, dann senden.
- **Flugplan** (`send_prefile_push_notifications`): `subject_cid = prefile["cid"]`; analog.
- **TeamSpeak** (`_poll_teamspeak`, ~Z. 985): den heutigen `ts_consent`-`nobody`-Check ersetzen
  durch `subject_cid = cid_for_callsign_authoritative(conn, frs)` und
  `recipients = visible_recipients(conn, subject_cid, get_ts_push_subscriptions(conn, subject_cid))`.
- **Telegram-Kanal-Alert** (`poller.py:727`, nur Online): der Broadcast-Alert kennt keinen
  Empfänger, kann also keine Allowlist bedienen. Regel: **`everyone` → Alert; `allowlist` → kein
  Alert; `nobody` → kein Alert.** Prüfung per `get_pilot_visibility(conn, cid).mode == 'everyone'`
  (bzw. kein Eintrag) direkt vor `send_telegram_alert`. So respektiert der Kanal die
  Selbstbestimmung; „nur diese Leute" lässt sich auf einem öffentlichen Kanal nicht abbilden →
  konservativ unterdrückt. *(Entscheidung — im Review bestätigen.)*

**Konsequenz „allowlist" + Alt-Abos:** Empfänger mit `owner_cid = NULL` (anonym/vor dem
Login-Rollout angelegt) sind **nie** in einer Allowlist → werden nicht benachrichtigt. Bewusst
privacy-sicher. Der Backfill (unten) hebt aktive Nutzer schrittweise auf einen `owner_cid`.

### Identität, Login & Abo-Besitzer (`app/main.py`, `app/forum_sso.py`)

- **Token v2:** `sso.php` v2 legt die Callsign(s) als Feld `cs` (Liste, UPPER) ins Token.
  `forum_sso.verify_sso_token` / `make_user_token` unverändert im Kern; der **Callback**
  (`/auth/forum/callback`) liest `cs` **defensiv** (nur Liste, nur String-Einträge, überlange
  verwerfen — F12) und ruft `upsert_forum_callsign(callsign, cid)` je Eintrag. Fehlt `cs` (altes
  sso.php), passiert nichts Schlimmes — Map bleibt leer, TS-Auflösung fällt auf `cid_for_callsign`
  zurück.
- **Selbst-Bereinigung veralteter Callsigns (F4):** der Callback löscht danach die eigenen
  Alt-Zeilen: `DELETE FROM forum_callsign WHERE cid = ? AND callsign NOT IN (<cs-Liste>)`. So
  verschwindet ein im Forum geändertes Callsign zuverlässig. Kollision (zwei Mitglieder, gleiches
  Callsign) → `upsert_forum_callsign` loggt eine Warnung, last-write-wins; Restrisiko einer
  Cross-User-Übernahme bis zum ersten Login des neuen Inhabers wird bewusst akzeptiert (Callsigns
  sind im Forum je Mitglied eindeutig).
- **Abo anlegen** (`POST /api/push/subscribe`): Server liest die CID aus dem `fs_user`-Cookie
  (falls eingeloggt) und übergibt sie als `owner_cid` an `upsert_push_subscription`. **Nie** aus
  dem Body.
- **Backfill** bestehender Abos: wenn ein eingeloggter Nutzer die App öffnet, meldet die SPA ihr
  aktuelles Abo-Endpoint an einen kleinen Endpoint `POST /api/push/claim` (Body: `{endpoint}`);
  der Server setzt `owner_cid = fs_user.cid` für dieses Endpoint (`set_push_subscription_owner`).
  Ohne Login: No-op.
- **Einheitliche Backfill-Semantik = last-login-wins (F3):** Der aktuelle Cookie-Besitzer ist der
  wahre Abo-Besitzer. `claim` **überschreibt** auch einen bereits gesetzten `owner_cid` (Shared-
  Browser: loggt sich B auf As Gerät ein, gehört das Abo nun B). Das `COALESCE` im Upsert
  (`COALESCE(excluded.owner_cid, owner_cid)`) dient **nur** dazu, einen gesetzten Owner beim
  **anonymen** Re-Subscribe (owner=NULL) nicht auszulöschen — es ist kein zweites, abweichendes
  Verhalten.

### API (`app/main.py`)

**Auth-Grundsatz (F1/F8):** Das Login-**Gate schützt `/api/me/*` NIE** — `/api/me` steht in
`_GATE_ALLOW_PREFIXES`, die Endpoints sind also auch anonym erreichbar. Die **einzige**
Verteidigung ist die Cookie-Prüfung **im Endpoint** (`_current_cid`, s. u.). Jeder neue
identitätsbasierte Endpoint prüft zusätzlich `_forum_login_active_cached` (wie `/api/me`), damit
ein Rest-`fs_user`-Cookie bei ausgeschaltetem Board-Login nicht mehr wirkt.

**`_current_cid(request, settings) -> int | None` (F2):** `verify_user_token` auf `fs_user`; die
CID kommt als **String** aus einem freien phpBB-Profilfeld → trimmen, `isdigit`-prüfen, zu `int`.
Nicht eingeloggt / Break-glass-Admin ohne CID / nicht-numerische CID → `None`. Datenqualitäts-Note:
Ist die Forum-VATSIM-ID vertippt, weicht sie von der echten VATSIM-CID (`pilot["cid"]`) ab → die
Sichtbarkeit greift dann im Online/Flugplan-Pfad nicht; kein Crash, aber wirkungslos. `sso.php` v2
trimmt die CID auf `\d+`.

- `GET /api/me/visibility` → `{mode, allowlist:[int,…], pilots:[{cid, callsign}]}`. `cid is None`
  → `401`. `pilots` = Picker-Kandidaten aus **`list_pilots`** (Mitglieder-Registry, F7), nicht aus
  `/api/stats`.
- `POST /api/me/visibility` → Body `{mode, allowlist?}`; `mode` ∈ {everyone,allowlist,nobody}
  sonst `400`; `allowlist` auf ganze Zahlen filtern **und auf ≤ 500 Einträge kappen** (F10).
  `mode='allowlist'` mit leerer Liste ist erlaubt (= effektiv niemand, F13). `cid is None` → `401`.
- `POST /api/push/claim` → Body `{endpoint}`; setzt `owner_cid` (last-login-wins, F3). `cid is
  None` → No-op `200` (bei aktivem Gate erhält ein Anonymer allerdings `401` vom Gate, F9). Ein
  eingeloggter Nutzer kann jeden Endpoint-String claimen — bewusst akzeptiert (Endpoints sind
  hochentropische Capability-URLs, F9).

### Frontend (`app/static/index.html`)

Neues Panel **„Wer darf über mich benachrichtigt werden?"** im Benachrichtigungs-Bereich,
**nur sichtbar wenn per Forum eingeloggt** (aus `/api/me`: `logged_in && cid`). Break-glass-Admin
ohne CID → Panel verborgen.

- Radio **Alle Friesen / Nur bestimmte / Keiner** (`visibility-mode`).
- Bei „Nur bestimmte": Mitglieder-Checkboxliste aus der **Mitglieder-Registry** (`list_pilots`,
  geliefert via `GET /api/me/visibility` → `pilots`), nicht aus `/api/stats` (F7 — sonst fehlen
  reine TS-Leute/lange nicht Geflogene bzw. erscheinen CIDs ohne Abo). Hinweistext: nur
  eingeloggte Mitglieder mit eigenem Abo profitieren effektiv. **UI-Standard:** Liste in
  scrollbarer Box mit sichtbarer Scrollbar gemäß CLAUDE.md.
- **Default beim Umschalten auf „Nur bestimmte": alle angehakt** (spiegelt den bestehenden
  Empfänger-Picker; man nimmt Haken weg = „alle außer"). *(offene Detailfrage, s. u.)*
- „Speichern" → `POST /api/me/visibility`. Zustand beim Laden aus `GET /api/me/visibility`.
- Beim App-Start als eingeloggter Nutzer: `POST /api/push/claim` mit dem aktuellen Endpoint
  (Owner-Backfill), sofern ein Abo existiert.

### `sso.php` v2 (Repo-Template `deploy/forum/sso.php` + Desktop-Datei)

- Zusätzlich lesen: `pf_phpbb_callsign`, `pf_phpbb_last_cs`, `pf_phpbb_alt_cs` aus
  `PROFILE_FIELDS_DATA_TABLE` (dieselbe Zeile wie die schon gelesene VATSIM-ID).
- Nicht-leere, getrimmte, groß­geschriebene Werte **dedupliziert** als Liste `cs` ins
  Token-Payload aufnehmen (neben CID/Name/is_admin).
- `deploy/forum/README.md` → v2-Hinweis (welche Felder, dass Callsign optional ist).
- **Rollout:** Desktop-`sso.php` bearbeiten, per `scp` auf den Forum-Server, dort an ihren
  Platz (`/var/www/bb_friesen/sso.php`, `640`, Gruppe `www-bb_friesen`), `php -l` prüfen.

### Datenschutz (`app/static/datenschutz.html`)

Neuer Absatz: eingeloggte Mitglieder können selbst festlegen, wer über ihre Aktivität (Online,
Flugplan, TeamSpeak) per Push benachrichtigt wird — alle / nur ausgewählte Mitglieder / niemand.
Hinweis, dass dies Push-Benachrichtigungen **und** den öffentlichen Telegram-Online-Kanal
betrifft (bei „nur bestimmte"/„niemand" keine Kanal-Ankündigung), nicht aber die Live-Anzeige,
und dass die Zuordnung über die (vom Forum bereitgestellte) VATSIM-CID und das FRS-Callsign
erfolgt.

## Verhaltenstabelle

| Subjekt-Modus | Online / Flugplan (Push) | TeamSpeak (Push) | Telegram-Kanal (nur Online) |
|---|---|---|---|
| **everyone** (Default) | wie heute (alle passenden Abos) | wie heute | Alert |
| **nobody** | niemand | niemand | kein Alert |
| **allowlist** | nur Abos mit `owner_cid ∈ allowlist` | nur Abos mit `owner_cid ∈ allowlist` | kein Alert |

`owner_cid = NULL` (Alt-/anonyme Abos): unter „allowlist" nie benachrichtigt; unter
„everyone"/„nobody" unverändert.

## Fehlerbehandlung

- `get_pilot_visibility` ohne Zeile → `None` → everyone (kein Crash).
- `cid_for_callsign_authoritative` → `None` bei unbekanntem Callsign → keine Einschränkung
  (everyone). **Zwei Richtungen (F5):** (a) harmlos — kein TS-Push wird fälschlich unterdrückt;
  (b) **Privacy-Loch** — ein gesetztes `nobody`/`allowlist` wird auf TS **ignoriert**, wenn das
  TS-Tag zu keinem `forum_callsign`/`flights`-Eintrag auflösbar ist. Da das Setzen einen Login
  voraussetzt und der Login (v2) `forum_callsign` befüllt, ist das Loch klein — aber daraus folgt
  die **harte Rollout-Voraussetzung** unten.
- `allowlist`-JSON defekt → als `[]` behandelt (= effektiv niemand, konservativ), Log-Warnung.
  Bewusste **Asymmetrie (F10)** zum bestehenden `pilot_filter` (defekt = „alle", großzügig): die
  Empfänger-Achse ist großzügig, die Subjekt-Achse konservativ.
- `POST /api/me/visibility`: ungültiger `mode` → `400`; `allowlist` > 500 Einträge → gekappt;
  Body-Größe durch die übliche Request-Grenze begrenzt.
- `POST /api/push/claim` ohne Login → No-op (`200`); bei aktivem Gate erhält ein Anonymer `401`
  vom Gate (F9).
- Token ohne/mit defektem `cs` → Callback ignoriert es, Login klappt trotzdem (F12).

## Rollout-Voraussetzung (F5, zwingend vor Aktivierung)

`sso.php` v2 **muss deployt** und die `phpbb_callsign`/`phpbb_last_cs`-Felder der Mitglieder
gepflegt sein, **bevor** das Feature scharfgeschaltet wird — sonst ist ein gesetztes `nobody` auf
TeamSpeak nicht garantiert wirksam (siehe Fehlerbehandlung). Empfehlung: gemeinsam mit dem
Board-Login-Highlight aktivieren.

## Tests (`tests/`)

- `test_database.py`: `pilot_visibility` CRUD (Default None→everyone; allowlist JSON round-trip;
  everyone/nobody nullen die allowlist); `forum_callsign` upsert + `cid_for_callsign_authoritative`
  (forum vor flights-Fallback, case-insensitiv, unbekannt→None); `push_subscriptions.owner_cid`
  (Insert mit/ohne, `set_push_subscription_owner`, Backfill überschreibt NULL, lässt gesetzten
  Wert stehen).
- `test_poller.py`: `visible_recipients` (everyone passthrough; nobody→[]; allowlist filtert nach
  owner_cid; owner_cid NULL nie in allowlist; subject_cid None→passthrough). Integration:
  Online/Flugplan/TS unterdrücken bzw. filtern korrekt; TS nutzt `cid_for_callsign_authoritative`.
- `test_forum_sso_api.py`: Callback mit `cs`-Liste schreibt `forum_callsign`-Zeilen; ohne `cs`
  kein Fehler.
- API-Tests: `GET/POST /api/me/visibility` (Auth-Gate; mode-Validierung; allowlist-Filter);
  `POST /api/push/claim` (nur eingeloggt setzt owner; anonym No-op); `/api/push/subscribe` setzt
  `owner_cid` aus Cookie, ignoriert Body-owner.
- `test_forum_sso.py` (sso.php-Logik ist PHP → nicht unit-getestet; Callsign-Sammel-/Dedup-Logik
  wird im Callback/Python getestet).

## Out of Scope (bewusst)

- Live-Sichtbarkeit (Karte/Liste/Statistik) verbergen — nur Push ist betroffen.
- Admin-Override, um jemanden zwangsweise aus-/einzuschließen.
- Periodischer Vollsync aller Forum-Callsigns (Map wird beim Login des jeweiligen Nutzers
  aktualisiert; das reicht, weil nur wer eine Einschränkung setzt, eingeloggt war).
- Drop der toten `ts_consent`-Tabelle (kann später per Migration).

## Offene Detailfrage (im Review zu bestätigen)

- **Default beim Umschalten auf „Nur bestimmte":** alle angehakt (Vorschlag, spiegelt den
  bestehenden Empfänger-Picker) — oder leer starten (bewusst freigeben)?

## Versionierung

Neues Release (login-gebundenes Feature). Version + Git-Tag + Changelog beim Aktivieren gemäß
stehender Regel; da Board-Login Voraussetzung ist, sinnvoll gemeinsam mit dessen Aktivierung als
Highlight.
