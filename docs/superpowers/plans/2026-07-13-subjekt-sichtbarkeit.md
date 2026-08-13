# Subjekt-Sichtbarkeit („Wer darf über mich benachrichtigt werden?") — Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) oder
> subagent-driven-development. Schritte nutzen Checkbox-Syntax (`- [ ]`).

**Goal:** Eingeloggte Mitglieder legen selbst fest, wer über ihre Aktivität (Online, Flugplan,
TeamSpeak) per Push benachrichtigt wird — `everyone` / `allowlist` / `nobody`.

**Architecture:** Subjekt-Sichtbarkeit gekeyt an CID (`pilot_visibility`). Push-Abos bekommen
einen `owner_cid` (aus dem Login-Cookie), sodass die Allowlist am Empfänger prüfbar ist. Ein
Helfer `visible_recipients` filtert in allen drei Sendepfaden. Callsign→CID kommt autoritativ
aus dem Forum (`sso.php` v2 → `forum_callsign`).

**Tech Stack:** Python 3.11 (Tests laufen 3.13), FastAPI, SQLite (stdlib `sqlite3`), Vanilla JS,
PHP (nur `sso.php`).

Spec: `docs/superpowers/specs/2026-07-13-subjekt-sichtbarkeit-design.md`.

## Global Constraints

- **Nur Push** wird beeinflusst, nie die Live-Sichtbarkeit.
- `owner_cid` **ausschließlich serverseitig aus dem `fs_user`-Cookie** — niemals aus dem Body.
- Feature/Panel nur sichtbar/wirksam bei **aktivem Board-Login** (liefert die CID).
- **Keine** `ts_consent`-Migration (laut Nutzer keine produktiven Zeilen). `ts_consent` wird nur
  nicht mehr gelesen.
- UI-Standard (CLAUDE.md): jede breite/lange Liste in scrollbarem Wrapper mit sichtbarer
  Scrollbar; Blau (`--green`) nur für Klickbares.
- Docs mitpflegen: `README.md`, `docs/api.md`, `docs/architecture.md` (stehende Regel).
- Versionierung + Git-Tag + Changelog beim Aktivieren (gemeinsam mit Board-Login-Highlight).
- Bestehende Testsuite (~982 Tests) muss grün bleiben.

---

### Task 1: DB — `pilot_visibility` Tabelle + CRUD

**Files:**
- Modify: `app/database.py` (CREATE-Block ~Z.138 nach `ts_consent`; MIGRATIONS ~Z.381; neue Funktionen bei den anderen Push-Funktionen ~Z.6027)
- Test: `tests/test_database.py`

**Interfaces:**
- Produces: `get_pilot_visibility(conn, cid) -> dict|None` (`{"mode": str, "allowlist": list[int]}`),
  `set_pilot_visibility(conn, cid, mode, allowlist=None) -> None`.

- [ ] **Step 1: Failing test**

```python
# tests/test_database.py
def test_pilot_visibility_default_and_roundtrip(tmp_db):
    conn = tmp_db
    assert db.get_pilot_visibility(conn, 111) is None          # Default = everyone
    db.set_pilot_visibility(conn, 111, "allowlist", [222, 333])
    v = db.get_pilot_visibility(conn, 111)
    assert v["mode"] == "allowlist" and v["allowlist"] == [222, 333]
    db.set_pilot_visibility(conn, 111, "everyone")             # nullt allowlist
    v = db.get_pilot_visibility(conn, 111)
    assert v["mode"] == "everyone" and v["allowlist"] == []
    db.set_pilot_visibility(conn, 111, "nobody")
    assert db.get_pilot_visibility(conn, 111)["mode"] == "nobody"
```

- [ ] **Step 2: Run — expect FAIL** (`pytest tests/test_database.py::test_pilot_visibility_default_and_roundtrip -v`) → `AttributeError: get_pilot_visibility`.

- [ ] **Step 3: Implement**

CREATE-Block (nach `ts_consent`):
```sql
CREATE TABLE IF NOT EXISTS pilot_visibility (
    cid        INTEGER PRIMARY KEY,
    mode       TEXT NOT NULL DEFAULT 'everyone',
    allowlist  TEXT,
    updated_at TEXT
);
```
MIGRATIONS-Liste ergänzen (idempotent, für bestehende DBs):
```python
"CREATE TABLE IF NOT EXISTS pilot_visibility (cid INTEGER PRIMARY KEY, "
"mode TEXT NOT NULL DEFAULT 'everyone', allowlist TEXT, updated_at TEXT)",
```
Funktionen:
```python
def get_pilot_visibility(conn: sqlite3.Connection, cid: int) -> dict | None:
    """Subjekt-Sichtbarkeit einer CID, oder None (= Default 'everyone')."""
    row = conn.execute(
        "SELECT mode, allowlist FROM pilot_visibility WHERE cid = ?", (cid,)
    ).fetchone()
    if row is None:
        return None
    try:
        allow = json.loads(row["allowlist"]) if row["allowlist"] else []
    except (json.JSONDecodeError, TypeError):
        allow = []
    return {"mode": row["mode"], "allowlist": [int(x) for x in allow]}


def set_pilot_visibility(conn: sqlite3.Connection, cid: int, mode: str,
                         allowlist: list[int] | None = None) -> None:
    """Sichtbarkeit setzen. mode ∈ {'everyone','allowlist','nobody'}.
    Bei everyone/nobody wird die allowlist genullt."""
    if mode not in ("everyone", "allowlist", "nobody"):
        raise ValueError(f"invalid visibility mode: {mode}")
    stored = json.dumps([int(x) for x in allowlist]) if (mode == "allowlist" and allowlist) else None
    conn.execute(
        """INSERT INTO pilot_visibility (cid, mode, allowlist, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(cid) DO UPDATE SET
               mode=excluded.mode, allowlist=excluded.allowlist, updated_at=excluded.updated_at""",
        (cid, mode, stored, _now_utc()),
    )
```

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: pilot_visibility-Tabelle + CRUD (Subjekt-Sichtbarkeit)`

---

### Task 2: DB — `forum_callsign` + autoritative Auflösung

**Files:**
- Modify: `app/database.py` (CREATE + MIGRATIONS; Funktionen bei `cid_for_callsign` ~Z.6068)
- Test: `tests/test_database.py`

**Interfaces:**
- Produces: `upsert_forum_callsign(conn, callsign, cid) -> None`,
  `cid_for_callsign_authoritative(conn, callsign) -> int|None`.
- Consumes: bestehendes `cid_for_callsign` (Fallback).

- [ ] **Step 1: Failing test**

```python
def test_forum_callsign_authoritative(tmp_db):
    conn = tmp_db
    assert db.cid_for_callsign_authoritative(conn, "FRS49") is None
    db.upsert_forum_callsign(conn, "frs49", 1602713)          # wird UPPER/trim
    assert db.cid_for_callsign_authoritative(conn, "FRS49") == 1602713
    assert db.cid_for_callsign_authoritative(conn, " frs49 ") == 1602713

def test_forum_callsign_collision_keeps_last_and_warns(tmp_db, caplog):
    conn = tmp_db
    db.upsert_forum_callsign(conn, "FRS99", 111)
    db.upsert_forum_callsign(conn, "FRS99", 222)              # anderer Owner → Warnung
    assert db.cid_for_callsign_authoritative(conn, "FRS99") == 222
    assert any("FRS99" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement**

CREATE + MIGRATION:
```sql
CREATE TABLE IF NOT EXISTS forum_callsign (
    callsign   TEXT PRIMARY KEY,
    cid        INTEGER NOT NULL,
    updated_at TEXT
);
```
```python
def upsert_forum_callsign(conn: sqlite3.Connection, callsign: str, cid: int) -> None:
    """Autoritatives Callsign→CID aus dem Forum. UPPER/trim. Kollision (anderer Owner)
    wird geloggt; last-write-wins (Callsigns sind im Forum je Mitglied eindeutig)."""
    cs = (callsign or "").strip().upper()
    if not cs:
        return
    prev = conn.execute("SELECT cid FROM forum_callsign WHERE callsign = ?", (cs,)).fetchone()
    if prev is not None and int(prev["cid"]) != int(cid):
        logger.warning("forum_callsign-Kollision: %s war CID %s, jetzt CID %s",
                       cs, prev["cid"], cid)
    conn.execute(
        """INSERT INTO forum_callsign (callsign, cid, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(callsign) DO UPDATE SET cid=excluded.cid, updated_at=excluded.updated_at""",
        (cs, int(cid), _now_utc()),
    )


def cid_for_callsign_authoritative(conn: sqlite3.Connection, callsign: str) -> int | None:
    """Zuerst die autoritative Forum-Map, sonst Fallback auf cid_for_callsign (flights/live/statsim)."""
    cs = (callsign or "").strip().upper()
    if not cs:
        return None
    row = conn.execute("SELECT cid FROM forum_callsign WHERE callsign = ?", (cs,)).fetchone()
    if row is not None:
        return int(row["cid"])
    return cid_for_callsign(conn, cs)
```

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: forum_callsign-Map + autoritative Callsign→CID-Auflösung`

---

### Task 3: DB — `push_subscriptions.owner_cid` + Owner-Funktionen

**Files:**
- Modify: `app/database.py` (`push_subscriptions`-Schema ~Z.129; MIGRATIONS ~Z.381;
  `upsert_push_subscription` ~Z.3618; `get_push_subscriptions_for_pilot`/`_for_prefile` ~Z.5909;
  `get_ts_push_subscriptions` ~Z.6088)
- Test: `tests/test_database.py`

**Interfaces:**
- Produces: `upsert_push_subscription(..., owner_cid=None)`,
  `set_push_subscription_owner(conn, endpoint, owner_cid) -> None`;
  die drei `get_push_subscriptions_*` liefern zusätzlich `owner_cid` je Zeile.

- [ ] **Step 1: Failing test**

```python
def test_push_owner_cid_and_backfill(tmp_db):
    conn = tmp_db
    db.upsert_push_subscription(conn, "e1", "p", "a", owner_cid=None)   # anonym
    db.set_push_subscription_owner(conn, "e1", 555)
    subs = db.get_push_subscriptions_for_pilot(conn, 999)              # pilot_filter NULL → alle
    assert subs[0]["owner_cid"] == 555
    # Re-Subscribe ohne Owner (ausgeloggt) darf gesetzten Owner NICHT löschen:
    db.upsert_push_subscription(conn, "e1", "p", "a", owner_cid=None)
    subs = db.get_push_subscriptions_for_pilot(conn, 999)
    assert subs[0]["owner_cid"] == 555
    # Re-Subscribe mit Owner überschreibt:
    db.upsert_push_subscription(conn, "e1", "p", "a", owner_cid=777)
    assert db.get_push_subscriptions_for_pilot(conn, 999)[0]["owner_cid"] == 777
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement**

Schema `push_subscriptions` + MIGRATION:
```python
"ALTER TABLE push_subscriptions ADD COLUMN owner_cid INTEGER DEFAULT NULL",
```
`upsert_push_subscription` — Parameter `owner_cid: int | None = None`; Spalte in INSERT ergänzen;
im ON CONFLICT **nicht mit NULL überschreiben**:
```python
               owner_cid=COALESCE(excluded.owner_cid, push_subscriptions.owner_cid),
```
(Werte-Tupel: `owner_cid` an passender Position ergänzen.)

Neue Funktion:
```python
def set_push_subscription_owner(conn: sqlite3.Connection, endpoint: str, owner_cid: int) -> None:
    """Owner-CID eines bestehenden Abos setzen (Backfill nach Login)."""
    conn.execute("UPDATE push_subscriptions SET owner_cid = ? WHERE endpoint = ?",
                 (int(owner_cid), endpoint))
```

`get_push_subscriptions_for_pilot` + `_for_prefile`: `owner_cid` in die SELECT-Spaltenliste
aufnehmen (`SELECT endpoint, p256dh, auth, pilot_filter, notify_prefiles, owner_cid …`) — der
Rest (dict(row)) trägt es automatisch mit.
`get_ts_push_subscriptions`: `owner_cid` in SELECT UND in die manuell gebauten Ergebnis-Dicts
aufnehmen (`{"endpoint":…, "p256dh":…, "auth":…, "owner_cid": row["owner_cid"]}` an beiden
`result.append`-Stellen).

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: owner_cid an Push-Abos (COALESCE-Backfill) + in Empfänger-Queries`

---

### Task 4: Poller — `visible_recipients` + Durchsetzung in 3 Sendepfaden  ⚠️ FABLE-CHECKPOINT

**Files:**
- Modify: `app/database.py` (Helfer `visible_recipients` bei `get_pilot_visibility`)
- Modify: `app/poller.py` (`send_web_push_notifications` ~Z.208; `send_prefile_push_notifications`
  ~Z.255; TS-Versand ~Z.985; Imports ~Z.24)
- Test: `tests/test_poller.py`, `tests/test_database.py`

**Interfaces:**
- Consumes: `get_pilot_visibility`, `cid_for_callsign_authoritative`, `get_ts_push_subscriptions`.
- Produces: `visible_recipients(conn, subject_cid, recipients) -> list[dict]`.

- [ ] **Step 1: Failing test (Helfer, in test_database.py)**

```python
def _subs(*owners): return [{"endpoint": f"e{o}", "owner_cid": o} for o in owners]

def test_visible_recipients_modes(tmp_db):
    conn = tmp_db
    subs = _subs(10, 20, None)
    assert db.visible_recipients(conn, 5, subs) == subs               # kein Eintrag → everyone
    db.set_pilot_visibility(conn, 5, "nobody")
    assert db.visible_recipients(conn, 5, subs) == []
    db.set_pilot_visibility(conn, 5, "allowlist", [20])
    got = db.visible_recipients(conn, 5, subs)
    assert [s["owner_cid"] for s in got] == [20]                      # None nie in allowlist
    assert db.visible_recipients(conn, None, subs) == subs            # unbekanntes Subjekt
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement Helfer**

```python
def visible_recipients(conn: sqlite3.Connection, subject_cid: int | None,
                       recipients: list[dict]) -> list[dict]:
    """Filtert Empfänger nach der Subjekt-Sichtbarkeit von subject_cid.
    recipients: dicts mit mind. 'owner_cid'. everyone/None → unverändert; nobody → []; 
    allowlist → nur Empfänger, deren owner_cid in der Liste steht (owner_cid None nie)."""
    if subject_cid is None:
        return recipients
    vis = get_pilot_visibility(conn, subject_cid)
    if not vis or vis["mode"] == "everyone":
        return recipients
    if vis["mode"] == "nobody":
        return []
    allow = set(vis["allowlist"])
    return [r for r in recipients if r.get("owner_cid") in allow]
```

- [ ] **Step 4: Failing test (Poller-Integration, test_poller.py)** — je ein Test, dass Online-,
  Flugplan- und TS-Versand bei `nobody` niemanden erreicht und bei `allowlist` nur den erlaubten
  Owner (TS via `cid_for_callsign_authoritative`). Muster an vorhandene Poller-Push-Tests anlehnen.

- [ ] **Step 5: Run — expect FAIL.**

- [ ] **Step 6: Implement Poller-Wiring**

Import in `app/poller.py` ergänzen: `get_pilot_visibility, visible_recipients,
cid_for_callsign_authoritative`.

Online (`send_web_push_notifications`), innerhalb `try` vor `conn.close()`:
```python
        subscriptions = get_push_subscriptions_for_pilot(conn, cid)
        subscriptions = visible_recipients(conn, cid, subscriptions)
```
Flugplan (`send_prefile_push_notifications`), analog innerhalb `try`:
```python
        subscriptions = get_push_subscriptions_for_prefile(conn, cid)
        subscriptions = visible_recipients(conn, cid, subscriptions)
```
TeamSpeak (~Z.985) — den `ts_consent`-Block ersetzen durch:
```python
                    subject_cid = cid_for_callsign_authoritative(conn, frs)
                    recipients = get_ts_push_subscriptions(conn, subject_cid)
                    recipients = visible_recipients(conn, subject_cid, recipients)
```

- [ ] **Step 6b: Telegram-Kanal-Alert respektieren (F6, `poller.py:727`)** — vor
  `send_telegram_alert` prüfen; nur bei `everyone` (bzw. kein Eintrag) senden:
```python
                        vis = get_pilot_visibility(conn, cid)
                        tg_allowed = (not vis) or vis["mode"] == "everyone"
                        if self.telegram_token and self.telegram_chat_id and tg_allowed:
                            ...  # bestehender send_telegram_alert-Block
```
  Test: Subjekt `nobody`/`allowlist` → `send_telegram_alert` wird **nicht** aufgerufen (mocken);
  `everyone` → schon.

- [ ] **Step 7: Run — expect PASS. Volle Suite laufen lassen** (`pytest -q`) — nichts rot.
- [ ] **Step 8: Commit** — `feat: visible_recipients — Subjekt-Sichtbarkeit in allen 3 Push-Pfaden + Telegram`

- [ ] **Step 9: ⚠️ FABLE-REVIEW-CHECKPOINT.** Fable-Subagent (read-only) prüft die Durchsetzung:
  Gibt es einen Push-Pfad, der `visible_recipients` umgeht? Ist die Filter-Reihenfolge
  (Empfänger-`pilot_filter` → Subjekt-Sichtbarkeit) korrekt? Wird `owner_cid=None` konsequent
  ausgeschlossen? Findings vor Task 5 einarbeiten.

---

### Task 5: API — `owner_cid` beim Subscribe + `/api/push/claim` + `/api/me/visibility`  ⚠️ FABLE-CHECKPOINT

**Files:**
- Modify: `app/main.py` (`push_subscribe` ~Z.360; neue Endpoints nach `/api/me` ~Z.1611; Helfer
  `_current_cid` bei den anderen Auth-Helfern)
- Test: `tests/test_forum_sso_api.py` (o. neue `tests/test_visibility_api.py`)

**Interfaces:**
- Consumes: `verify_user_token`, `USER_COOKIE`, `get_pilot_visibility`, `set_pilot_visibility`,
  `set_push_subscription_owner`, `upsert_push_subscription`.

- [ ] **Step 1: Failing tests** — (a) eingeloggter `POST /api/push/subscribe` setzt `owner_cid`
  aus dem Cookie und **ignoriert `owner_cid` im Body**; (b) `GET /api/me/visibility` liefert Default
  `everyone` + `pilots`-Liste bei eingeloggt, **`401` ohne Login auch bei aktivem Gate** (nicht das
  Gate schützt — F1); (c) `POST /api/me/visibility {mode:'allowlist', allowlist:[..]}` speichert;
  ungültiger `mode` → `400`; **leere Allowlist bei `allowlist` erlaubt** (F13); **>500 Einträge
  gekappt** (F10); (d) `POST /api/push/claim` setzt Owner nur eingeloggt, anonym → No-op; (e)
  **String-CID** im Cookie („1602713") wird zu `int`, **nicht-numerische CID → `None` → 401** (F2);
  (f) **Board-Login AUS → wie nicht eingeloggt**, selbst mit gültigem Rest-Cookie (F8).
  (Cookie via `make_user_token` bauen wie in test_forum_sso_api.)

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement**

Helfer (F2 + F8 — String-CID validieren, bei inaktivem Board-Login wie ausgeloggt):
```python
def _current_cid(request: Request, settings) -> int | None:
    if not _forum_login_active_cached(settings):
        return None
    claims = verify_user_token(request.cookies.get(USER_COOKIE, ""), settings.SECRET_KEY)
    if not claims:
        return None
    raw = str(claims.get("cid", "")).strip()
    return int(raw) if raw.isdigit() else None      # Break-glass-Admin/Tippfehler-CID → None
```
`push_subscribe`: `owner_cid` aus Cookie und an den Upsert geben (Body-Feld ignorieren):
```python
        upsert_push_subscription(
            conn, endpoint, p256dh, auth,
            body.get("pilot_filter"),
            notify_prefiles=bool(body.get("notify_prefiles", False)),
            notify_ts=bool(body.get("notify_ts", False)),
            notify_events=bool(body.get("notify_events", False)),
            owner_cid=_current_cid(request, settings),
        )
```
Neue Endpoints:
```python
@app.get("/api/me/visibility")
async def api_me_visibility(request: Request):
    settings = get_settings()
    cid = _current_cid(request, settings)
    if cid is None:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    conn = get_connection(settings.DB_PATH)
    try:
        vis = get_pilot_visibility(conn, cid) or {"mode": "everyone", "allowlist": []}
        pilots = [{"cid": p["cid"],
                   "callsign": (p["callsigns"][0] if p["callsigns"] else p["name"])}
                  for p in list_pilots(conn)]          # Mitglieder-Registry, nicht /api/stats (F7)
    finally:
        conn.close()
    return {"mode": vis["mode"], "allowlist": vis.get("allowlist", []), "pilots": pilots}


@app.post("/api/me/visibility")
async def api_me_visibility_set(request: Request):
    settings = get_settings()
    cid = _current_cid(request, settings)
    if cid is None:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    body = await request.json()
    mode = body.get("mode")
    if mode not in ("everyone", "allowlist", "nobody"):
        raise HTTPException(status_code=400, detail="Ungültiger Modus")
    allowlist = None
    if mode == "allowlist":
        allowlist = [int(x) for x in (body.get("allowlist") or [])
                     if str(x).lstrip("-").isdigit()][:500]      # F10: Länge kappen; leer erlaubt (F13)
    conn = get_connection(settings.DB_PATH)
    try:
        set_pilot_visibility(conn, cid, mode, allowlist)
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "mode": mode}


@app.post("/api/push/claim")
async def api_push_claim(request: Request):
    """Backfill: bestehendes Abo dem eingeloggten Nutzer zuordnen. Anonym → No-op."""
    settings = get_settings()
    cid = _current_cid(request, settings)
    body = await request.json()
    endpoint = body.get("endpoint", "")
    if cid is None or not endpoint:
        return {"status": "skipped"}
    conn = get_connection(settings.DB_PATH)
    try:
        set_push_subscription_owner(conn, endpoint, cid)
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}
```
Import `list_pilots` in main.py ergänzen. **Auth-Grundsatz (F1):** Das Gate schützt `/api/me/*`
NICHT (steht in `_GATE_ALLOW_PREFIXES`) — die alleinige Verteidigung ist `_current_cid` IM
Endpoint (inkl. `_forum_login_active_cached`-Check). Deshalb muss der Anonym-Test bei **aktivem**
Gate laufen und `401` erwarten (nicht das Gate-Verhalten).

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: /api/me/visibility + /api/push/claim + owner_cid beim Subscribe`

- [ ] **Step 6: ⚠️ FABLE-REVIEW-CHECKPOINT.** Fable prüft Auth: Kann ein nicht eingeloggter
  Nutzer fremde Sichtbarkeit setzen oder ein fremdes Abo claimen? Kommt `owner_cid` garantiert
  nur aus dem Cookie? Findings einarbeiten.

---

### Task 6: Login-Callback — Callsign(s) aus dem Token in `forum_callsign`

**Files:**
- Modify: `app/main.py` (`forum_callback` ~Z.1560–1569)
- Test: `tests/test_forum_sso_api.py`

**Interfaces:**
- Consumes: `verify_sso_token` (liefert jetzt evtl. `cs`-Liste), `upsert_forum_callsign`.

- [ ] **Step 1: Failing test** — (a) Callback mit `cs: ["FRS49","FRS49N"]` schreibt zwei
  `forum_callsign`-Zeilen auf die CID; (b) Token **ohne** `cs` wirft nicht, loggt normal ein;
  (c) **defektes `cs`** (Zahl, dict, Liste mit Nicht-Strings/überlangen — F12) → ignoriert, Login
  klappt; (d) **Selbst-Bereinigung** (F4): ein zweiter Login mit kürzerer `cs`-Liste löscht die
  weggefallene Alt-Zeile dieser CID.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** — im `forum_callback` nach erfolgreicher `claims`-Prüfung, vor dem
  Redirect (nur numerische CID, `cs` defensiv, danach Selbst-Bereinigung):
```python
    raw_cid = str(claims.get("cid", "")).strip()
    cs_list = claims.get("cs")
    if raw_cid.isdigit() and isinstance(cs_list, list):
        cid_int = int(raw_cid)
        clean = []
        for cs in cs_list:
            if isinstance(cs, str):
                v = cs.strip().upper()
                if 0 < len(v) <= 16 and v not in clean:
                    clean.append(v)
        conn = get_connection(settings.DB_PATH)
        try:
            for v in clean:
                upsert_forum_callsign(conn, v, cid_int)          # loggt Kollision (F4)
            # Selbst-Bereinigung veralteter eigener Callsigns:
            keep = ",".join("?" * len(clean))
            conn.execute(
                f"DELETE FROM forum_callsign WHERE cid = ? AND callsign NOT IN ({keep or 'NULL'})",
                (cid_int, *clean),
            )
            conn.commit()
        finally:
            conn.close()
```
Sicherstellen, dass `verify_sso_token` das `cs`-Feld durchreicht (Payload wird als dict
zurückgegeben — keine Whitelist im Token-Parser; falls doch, `cs` explizit übernehmen).

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: Login-Callback speichert Forum-Callsign(s) → forum_callsign`

---

### Task 7: `sso.php` v2 — Callsign-Profilfelder ins Token

**Files:**
- Modify: `deploy/forum/sso.php` (Token-Payload), `deploy/forum/README.md` (v2-Notiz)
- Kein Python-Test (PHP). Verifikation: `php -l` + Live-Login-Test.

- [ ] **Step 1** — In `sso.php` die drei Felder aus `PROFILE_FIELDS_DATA_TABLE` mitlesen
  (`pf_phpbb_callsign`, `pf_phpbb_last_cs`, `pf_phpbb_alt_cs`), nicht-leere getrimmte, groß­
  geschriebene, deduplizierte Werte als `cs`-Liste ins Payload legen:
```php
$cs = array();
foreach (array('pf_phpbb_callsign','pf_phpbb_last_cs','pf_phpbb_alt_cs') as $f) {
    $v = isset($row[$f]) ? strtoupper(trim($row[$f])) : '';
    if ($v !== '' && !in_array($v, $cs, true)) { $cs[] = $v; }
}
$payload['cs'] = $cs;
```
  (Die SELECT-Spaltenliste um die drei Felder erweitern.)
- [ ] **Step 2** — `README.md`: Hinweis, welche Felder gelesen werden und dass Callsign optional
  ist (fehlt es, funktioniert alles außer der autoritativen TS-Auflösung, die dann auf die
  Flughistorie zurückfällt).
- [ ] **Step 3** — Desktop-Datei entsprechend anpassen, per `scp` auf den Forum-Server, `php -l`,
  `640`/Gruppe prüfen (Rollout-Schritt, kein Commit-Gate).
- [ ] **Step 4: Commit** — `feat(forum): sso.php v2 — Callsign-Felder ins SSO-Token`

---

### Task 8: Frontend — Panel „Wer darf über mich benachrichtigt werden?"

**Files:**
- Modify: `app/static/index.html` (Benachrichtigungs-Panel ~Z.1513; JS bei den notif-Funktionen
  ~Z.2096)
- Kein Unit-Test (Vanilla JS) — manuelle Verifikationsschritte am Ende.

- [ ] **Step 1** — Panel-Markup (nur einblenden, wenn `/api/me` `logged_in && cid`):
  Überschrift, Radio `visibility-mode` (Alle / Nur bestimmte / Keiner), darunter die
  Mitglieder-Checkboxliste in einer **scrollbaren Box mit sichtbarer Scrollbar** (UI-Standard),
  „Speichern"-Button. Klickbares in Blau (`--green`), Anzeige-Text neutral.
- [ ] **Step 2** — JS `loadVisibility()`: `GET /api/me/visibility` → Modus + Allowlist setzen;
  Mitgliederliste aus dem **`pilots`-Feld derselben Antwort** rendern (Quelle `list_pilots`, F7 —
  NICHT `/api/stats`). Hinweistext: nur eingeloggte Mitglieder mit eigenem Abo profitieren
  effektiv. Beim Umschalten auf „Nur bestimmte" **alle angehakt** (Default, wie bestehender
  Picker; Nutzer nimmt weg) — *Detail im Spec-Review bestätigen.*
- [ ] **Step 3** — `saveVisibility()`: `POST /api/me/visibility {mode, allowlist}`.
- [ ] **Step 4** — Beim App-Start als eingeloggter Nutzer mit vorhandenem Abo:
  `POST /api/push/claim {endpoint}` (Owner-Backfill), fire-and-forget.
- [ ] **Step 5: Manuelle Verifikation** (lokal, Board-Login an): Panel erscheint nur eingeloggt;
  Modi speichern/laden korrekt; Liste horizontal/vertikal scrollbar mit sichtbarer Leiste;
  ausgeloggt kein Panel.
- [ ] **Step 6: Commit** — `feat: Sichtbarkeits-Panel (Alle/Nur bestimmte/Keiner) im Frontend`

---

### Task 9: Datenschutz (Forum-Login + Sichtbarkeit) + Docs

**Files:**
- Modify: `app/static/datenschutz.html`, `README.md`, `docs/api.md`, `docs/architecture.md`

Die Datenschutzerklärung erwähnt den **Forum-Login (SSO) bisher gar nicht** — das muss vor
Aktivierung rein und wird hier gemeinsam mit dem Sichtbarkeits-Absatz ergänzt.

- [ ] **Step 1a — Abschnitt „Anmeldung über das FriesenFlieger-Forum (SSO)"** (neuer `<h3>` in §2,
  vor „Empfänger/Hosting"): Login über `board.friesenflieger.de`; das Forum bestätigt die
  Mitgliedschaft und übermittelt VATSIM-CID, Anzeigename, FRS-Rufzeichen und Admin-Kennung
  (Gruppe „Events"); **Forum-Passwort wird NICHT an FriesenSpy übermittelt**; Zweck
  Zugangsbeschränkung + Identifikation; Rechtsgrundlage Art. 6 (1) f. Technisch notwendige
  Cookies: `fs_user` (~20 min, gleitend) + kurzlebiges Sicherheits-Cookie beim Anmeldevorgang
  (§ 25 Abs. 2 TTDSG, keine Einwilligung nötig).
- [ ] **Step 1b — Abschnitt „Benachrichtigungs-Sichtbarkeit (optional)"**: angemeldete Mitglieder
  legen fest, wer über ihre Aktivität (Online, Flugplan, TeamSpeak) benachrichtigt wird — alle /
  nur ausgewählte / niemand; wirkt auch auf den **öffentlichen Telegram-Online-Kanal**, nicht auf
  die Live-Anzeige; Zuordnung über CID + FRS-Callsign; Rechtsgrundlage Art. 6 (1) f.
- [ ] **Step 1c** — je eine Zeile bei **§3 Empfänger** (das Vereinsforum als Quelle der
  Mitgliedsbestätigung) und **§4 Speicherdauer** (Sitzungs-Cookie endet nach ~20 min Inaktivität).
  „Stand"-Datum aktualisieren.
- [ ] **Step 2** — `docs/api.md`: `/api/me/visibility` (GET/POST), `/api/push/claim`,
  `owner_cid` am Subscribe. `docs/architecture.md`: `pilot_visibility`, `forum_callsign`,
  `owner_cid`, `visible_recipients`-Fluss. `README.md`: Feature-Kurzbeschreibung.
- [ ] **Step 3: Commit** — `docs: Datenschutz (Forum-Login + Sichtbarkeit) + api/architecture`

---

### Task 10: Google Fonts self-hosten (Datenschutz — alle 4 Seiten)

**Kontext:** `datenschutz.html`, `impressum.html`, `index.html`, `admin.html` laden Fonts von
`fonts.googleapis.com`/`gstatic.com` → überträgt Besucher-IP an Google (DE-Abmahnthema). Alle vier
nutzen identisch **Exo 2** (300/500/700) + **Courier Prime** (400/700), beide OFL → self-hostbar.

**Files:**
- Create: `app/static/fonts/` (woff2-Dateien), `app/static/fonts/fonts.css` (@font-face)
- Modify: die 4 HTML-Seiten (Font-`<link>` + beide `preconnect` ersetzen)

- [ ] **Step 1** — woff2 der zwei Familien (Exo 2 300/500/700, Courier Prime 400/700) besorgen
  (OFL) und unter `app/static/fonts/` ablegen (Latin-Subset genügt).
- [ ] **Step 2** — `fonts/fonts.css` mit `@font-face`-Regeln (je Gewicht, `font-display: swap`,
  `src: url('/static/fonts/…woff2') format('woff2')`).
- [ ] **Step 3** — in allen 4 Seiten die beiden `<link rel="preconnect" …google…>` **und** den
  `<link …googleapis.com/css2…>` durch **ein** `<link rel="stylesheet" href="/static/fonts/fonts.css">`
  ersetzen. Kein `googleapis`/`gstatic`-Treffer darf übrig bleiben.
- [ ] **Step 4: Verifikation** — `grep -r "googleapis\|gstatic" app/static` liefert **nichts**;
  Seiten laden lokal, Schriftbild unverändert (Exo 2 / Courier Prime).
- [ ] **Step 5: Commit** — `feat: Google Fonts self-hosten (kein externer Font-Load mehr)`

---

### Task 11: Abschluss — volle Suite + finaler Fable-Review + Release-Vorbereitung

- [ ] **Step 1** — `pytest -q` komplett grün.
- [ ] **Step 2: ⚠️ FINALER FABLE-REVIEW** über den gesamten Diff (Durchsetzung, Auth,
  Kollisionen, Rückwärtskompatibilität sso.php ohne `cs`, Board-Login-AUS-Verhalten). Findings
  fixen.
- [ ] **Step 3** — CHANGELOG-Eintrag vorbereiten (`highlight:false`, wird bei Aktivierung mit
  Board-Login auf true geflippt). Version/Tag erst bei Aktivierung setzen (stehende Regel).
- [ ] **Step 4** — Vor `git push origin main` kurz beim Nutzer bestätigen lassen (stehende Regel).

## Self-Review (Autor)

- **Spec-Abdeckung:** 3 Modi (Task 1/4/5/8), owner_cid (3/5), autoritatives Callsign (2/6/7),
  Durchsetzung 3 Pfade (4), Datenschutz (9), Board-Login-Abhängigkeit (8) — abgedeckt.
- **Offene Detailfrage** (Default „Nur bestimmte" angehakt vs. leer) bleibt im Frontend-Task
  markiert, blockiert die Umsetzung nicht.
- **Typkonsistenz:** `owner_cid` int|None überall; `visible_recipients` erwartet `owner_cid`-Key
  → in allen drei `get_push_subscriptions_*` ergänzt (Task 3).
- **Reihenfolge:** DB (1–3) vor Poller (4) vor API (5–6) vor sso.php (7) vor Frontend (8) vor
  Datenschutz/Docs (9) vor Fonts (10) vor Abschluss (11) — jede Stufe für sich testbar. Fonts (10)
  ist unabhängig und könnte auch separat laufen.
- **Datenschutz (Task 9)** deckt jetzt AUCH den Forum-Login (SSO) ab, der bisher gar nicht in der
  Erklärung stand — Pflicht vor Aktivierung.
