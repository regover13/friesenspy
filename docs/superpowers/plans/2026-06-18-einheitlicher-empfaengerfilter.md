# Einheitlicher Empfänger-Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die bestehende Piloten-Auswahl (`pilot_filter`: Alle / Nur bestimmte) gilt zusätzlich für TeamSpeak-Benachrichtigungen; Selbst-Ausschluss läuft überall über das Abwählen in der Liste; das separate `ts_self_frs`-Feld entfällt.

**Architecture:** TS-Beitritte (FRS = Callsign) werden über `cid_for_callsign` auf eine CID gemappt und gegen denselben `pilot_filter` geprüft wie Online/Flugplan (Logik wie `get_push_subscriptions_for_pilot`). `recipients_for`/`ts_self_frs` entfallen; `ts_consent` bleibt als Subjekt-Privacy auf `everyone`/`nobody` reduziert.

**Tech Stack:** Python 3.11, SQLite, pytest, FastAPI, Vanilla-JS-Frontend.

---

## File Structure

| Datei | Änderung |
|---|---|
| `app/database.py` | Neu: `cid_for_callsign`; Umbau: `get_ts_push_subscriptions(conn, cid)` (notify_ts + pilot_filter) |
| `app/poller.py` | `_poll_teamspeak`: Empfänger über `cid_for_callsign` + `get_ts_push_subscriptions`; `recipients_for`-Import/Nutzung raus; `ts_consent`-`nobody`-Kurzcheck |
| `app/ts_notify.py` | **gelöscht** (recipients_for entfällt) |
| `tests/test_ts_notify.py` | **gelöscht** |
| `manage_ts_consent.py` | `visibility`-`choices` = `everyone`/`nobody`; `--allow` entfällt |
| `app/main.py` | `/api/push/subscribe`: `ts_self_frs` nicht mehr auswerten |
| `app/static/index.html` | FRS-Feld/Label/localStorage/POST-Feld entfernen; Hinweis „gilt auch für TS" |
| `tests/test_database.py`, `tests/test_poller.py`, `tests/test_manage_ts_consent.py` | ergänzen/anpassen |
| `README.md`, `docs/api.md`, `docs/architecture.md`, `CLAUDE.md` | Doku |

---

## Task 1: `cid_for_callsign` + `get_ts_push_subscriptions(conn, cid)`

**Files:**
- Modify: `app/database.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Failing tests anhängen** an `tests/test_database.py`:

```python
class TestCidForCallsign:
    def test_from_flights(self):
        from app.database import cid_for_callsign, open_flight
        conn = _make_conn()
        open_flight(conn, 111, "FRS49", "C172", "EDDW", "EDDH", _ts_offset(0))
        assert cid_for_callsign(conn, "FRS49") == 111
        assert cid_for_callsign(conn, "frs49") == 111  # case-insensitiv

    def test_unknown_returns_none(self):
        from app.database import cid_for_callsign
        conn = _make_conn()
        assert cid_for_callsign(conn, "FRS999") is None
        assert cid_for_callsign(conn, "") is None

    def test_live_position_preferred(self):
        from app.database import cid_for_callsign, open_flight, upsert_live_position
        conn = _make_conn()
        open_flight(conn, 111, "FRS49", "C172", "EDDW", "EDDH", _ts_offset(-10))
        upsert_live_position(conn, 222, "FRS49", "C172", "EDDW", "EDDH",
                             53.0, 8.0, 1000, 120, 90, _ts_offset(0))
        assert cid_for_callsign(conn, "FRS49") == 222


class TestGetTsPushSubscriptions:
    def _db(self, tmp_path):
        from app.database import init_db, get_connection
        db = str(tmp_path / "t.db"); init_db(db)
        return get_connection(db)

    def test_only_notify_ts(self, tmp_path):
        from app.database import upsert_push_subscription, get_ts_push_subscriptions
        conn = self._db(tmp_path)
        upsert_push_subscription(conn, "e1", "p", "a", notify_ts=True)
        upsert_push_subscription(conn, "e2", "p", "a", notify_ts=False)
        conn.commit()
        assert [s["endpoint"] for s in get_ts_push_subscriptions(conn, 111)] == ["e1"]
        conn.close()

    def test_pilot_filter_membership(self, tmp_path):
        from app.database import upsert_push_subscription, get_ts_push_subscriptions
        conn = self._db(tmp_path)
        upsert_push_subscription(conn, "all", "p", "a", notify_ts=True, pilot_filter=None)
        upsert_push_subscription(conn, "only111", "p", "a", notify_ts=True, pilot_filter=[111])
        upsert_push_subscription(conn, "only999", "p", "a", notify_ts=True, pilot_filter=[999])
        conn.commit()
        eps = {s["endpoint"] for s in get_ts_push_subscriptions(conn, 111)}
        assert eps == {"all", "only111"}
        conn.close()

    def test_unknown_cid_only_all(self, tmp_path):
        from app.database import upsert_push_subscription, get_ts_push_subscriptions
        conn = self._db(tmp_path)
        upsert_push_subscription(conn, "all", "p", "a", notify_ts=True, pilot_filter=None)
        upsert_push_subscription(conn, "only111", "p", "a", notify_ts=True, pilot_filter=[111])
        conn.commit()
        # cid None (reine TS-Leute) → nur pilot_filter NULL
        assert [s["endpoint"] for s in get_ts_push_subscriptions(conn, None)] == ["all"]
        conn.close()
```

- [ ] **Step 2: Fehlschlag bestätigen**

Run: `pytest tests/test_database.py::TestCidForCallsign tests/test_database.py::TestGetTsPushSubscriptions -v`
Expected: FAIL — `ImportError: cannot import name 'cid_for_callsign'`

- [ ] **Step 3: `cid_for_callsign` ergänzen** (in `app/database.py`, im Push-Abschnitt):

```python
def cid_for_callsign(conn: sqlite3.Connection, callsign: str) -> int | None:
    """CID zu einem FRS-/Callsign-String, oder None (nie auf VATSIM gesehen).

    Quelle in Reihenfolge: aktuelle live_positions, jüngster flights-Eintrag,
    statsim_cache. Vergleich case-insensitiv/getrimmt.
    """
    cs = (callsign or "").strip().upper()
    if not cs:
        return None
    for q in (
        "SELECT cid FROM live_positions WHERE UPPER(callsign) = ? LIMIT 1",
        "SELECT cid FROM flights WHERE UPPER(callsign) = ? ORDER BY logon_time DESC LIMIT 1",
        "SELECT cid FROM statsim_cache WHERE UPPER(callsign) = ? ORDER BY logon_time DESC LIMIT 1",
    ):
        row = conn.execute(q, (cs,)).fetchone()
        if row is not None and row[0] is not None:
            return int(row[0])
    return None
```

- [ ] **Step 4: `get_ts_push_subscriptions` umbauen** — ersetze die bestehende Funktion (heute parameterlos, liefert `ts_self_frs`) durch:

```python
def get_ts_push_subscriptions(conn: sqlite3.Connection, cid: int | None) -> list[dict]:
    """TS-Opt-in-Subscriptions (notify_ts = 1), gefiltert über pilot_filter.

    pilot_filter NULL = alle; sonst nur wenn cid in der JSON-Liste. cid None
    (reine TS-Leute ohne CID) → nur die NULL-Filter-Subscriptions. Defektes
    pilot_filter-JSON wird (wie get_push_subscriptions_for_pilot) als "alle" gewertet.
    """
    rows = conn.execute(
        "SELECT endpoint, p256dh, auth, pilot_filter FROM push_subscriptions WHERE notify_ts = 1"
    ).fetchall()
    result = []
    for row in rows:
        pf = row["pilot_filter"]
        if pf is None:
            result.append({"endpoint": row["endpoint"], "p256dh": row["p256dh"], "auth": row["auth"]})
        elif cid is not None:
            try:
                if cid in json.loads(pf):
                    result.append({"endpoint": row["endpoint"], "p256dh": row["p256dh"], "auth": row["auth"]})
            except (json.JSONDecodeError, TypeError):
                result.append({"endpoint": row["endpoint"], "p256dh": row["p256dh"], "auth": row["auth"]})
    return result
```

- [ ] **Step 5: Erfolg bestätigen** — beide bisherigen `get_ts_push_subscriptions`-Tests in `TestTsPushSubscriptions` (aus der TS-Login-Arbeit) erwarten die alte parameterlose Signatur und `ts_self_frs` → **anpassen/entfernen**: ersetze die alte `TestTsPushSubscriptions`-Klasse vollständig durch `TestGetTsPushSubscriptions` aus Step 1 (gleicher Zweck, neue Signatur).

Run: `pytest tests/test_database.py -v`
Expected: PASS (alle, inкl. neue)

- [ ] **Step 6: Commit**

```bash
git add app/database.py tests/test_database.py
git commit -m "feat(filter): cid_for_callsign + get_ts_push_subscriptions(cid) über pilot_filter

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `_poll_teamspeak` auf `pilot_filter` umstellen, `ts_notify` entfernen

**Files:**
- Modify: `app/poller.py`
- Delete: `app/ts_notify.py`, `tests/test_ts_notify.py`
- Test: `tests/test_poller.py`

- [ ] **Step 1: Failing tests** — ersetze in `tests/test_poller.py` den Block in `test_new_join_triggers_push` bzw. ergänze diese Tests in `TestPollTeamspeak` (sie prüfen die neue pilot_filter-Wirkung; `_ts_poller` nutzt `dwell=0`):

```python
    @pytest.mark.asyncio
    async def test_ts_respects_pilot_filter_include(self, tmp_path):
        """FRS mit bekannter CID: nur Subs, deren pilot_filter die CID enthält (oder NULL)."""
        from app.database import (init_db, get_connection, upsert_push_subscription, open_flight)
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        open_flight(conn, 111, "FRS1", "C172", "EDDW", "EDDH", "2026-06-18T10:00:00Z")
        upsert_push_subscription(conn, "all", "p", "a", notify_ts=True, pilot_filter=None)
        upsert_push_subscription(conn, "only111", "p", "a", notify_ts=True, pilot_filter=[111])
        upsert_push_subscription(conn, "only999", "p", "a", notify_ts=True, pilot_filter=[999])
        conn.commit(); conn.close()
        poller = self._ts_poller(db)
        poller._ts_streak = {}
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        # send_web_push wird einmal mit der gefilterten Empfängerliste aufgerufen
        assert len(sent) == 1
        recipients = sent[0][3]  # (vapid, email, db, recipients, payload, ...)
        eps = {r["endpoint"] for r in recipients}
        assert eps == {"all", "only111"}

    @pytest.mark.asyncio
    async def test_ts_unknown_frs_only_all(self, tmp_path):
        """Reine TS-FRS ohne CID: nur pilot_filter NULL bekommt den Push."""
        from app.database import init_db, get_connection, upsert_push_subscription
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "all", "p", "a", notify_ts=True, pilot_filter=None)
        upsert_push_subscription(conn, "only111", "p", "a", notify_ts=True, pilot_filter=[111])
        conn.commit(); conn.close()
        poller = self._ts_poller(db)
        poller._ts_streak = {}
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS9", "nick": "Gast/FRS9", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert len(sent) == 1
        assert {r["endpoint"] for r in sent[0][3]} == {"all"}

    @pytest.mark.asyncio
    async def test_ts_consent_nobody_suppresses(self, tmp_path):
        from app.database import (init_db, get_connection, upsert_push_subscription,
                                  upsert_ts_consent, open_flight)
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        open_flight(conn, 111, "FRS1", "C172", "EDDW", "EDDH", "2026-06-18T10:00:00Z")
        upsert_push_subscription(conn, "all", "p", "a", notify_ts=True, pilot_filter=None)
        upsert_ts_consent(conn, "FRS1", "nobody", None)
        conn.commit(); conn.close()
        poller = self._ts_poller(db)
        poller._ts_streak = {}
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert sent == []
```

Außerdem: das bestehende `test_new_join_triggers_push` (nutzt `ts_self_frs="FRS9"`) anpassen — `ts_self_frs` gibt es nicht mehr; ersetze es durch eine Subscription ohne pilot_filter und ohne `open_flight` (FRS1 unbekannt → cid None → „all"-Sub bekommt Push), oder entferne den Test zugunsten der drei neuen.

- [ ] **Step 2: Fehlschlag bestätigen**

Run: `pytest tests/test_poller.py::TestPollTeamspeak -v`
Expected: FAIL (neue Tests rot)

- [ ] **Step 3: Imports anpassen** in `app/poller.py` — entferne `from app.ts_notify import recipients_for`; in `from app.database import (...)` `get_ts_consent` behalten und `get_ts_push_subscriptions` behalten, `cid_for_callsign` ergänzen.

- [ ] **Step 4: Empfänger-Block ersetzen** in `_poll_teamspeak` — ersetze:

```python
                conn = get_connection(self.db_path)
                try:
                    consent = get_ts_consent(conn, frs)
                    subs = get_ts_push_subscriptions(conn)
                finally:
                    conn.close()

                recipients = recipients_for(consent, subs, frs)
                if not recipients:
                    continue
```

durch:

```python
                conn = get_connection(self.db_path)
                try:
                    consent = get_ts_consent(conn, frs)
                    if consent and consent.get("visibility") == "nobody":
                        recipients = []  # Subjekt-Privacy: gar nicht über diese FRS melden
                    else:
                        cid = cid_for_callsign(conn, frs)
                        recipients = get_ts_push_subscriptions(conn, cid)
                finally:
                    conn.close()

                if not recipients:
                    continue
```

- [ ] **Step 5: `ts_notify` löschen**

```bash
git rm app/ts_notify.py tests/test_ts_notify.py
```

- [ ] **Step 6: Erfolg bestätigen**

Run: `pytest tests/test_poller.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/poller.py tests/test_poller.py
git commit -m "feat(filter): TS-Empfänger über pilot_filter + cid_for_callsign; recipients_for/ts_notify entfernt

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `ts_consent` auf everyone/nobody reduzieren (CLI)

**Files:**
- Modify: `manage_ts_consent.py`
- Test: `tests/test_manage_ts_consent.py`

Hinweis: Die DB-Funktionen `get_ts_consent`/`upsert_ts_consent` bleiben unverändert (unterstützen die `allowlist`-Spalte weiter, werden aber nicht mehr darüber bedient). Der Poller wertet nur `nobody` aus (Task 2). Hier wird nur die CLI auf `everyone`/`nobody` beschränkt.

- [ ] **Step 1: Tests anpassen** in `tests/test_manage_ts_consent.py` — ersetze `test_set_then_get` (nutzt `allowlist`/`--allow`) durch:

```python
def test_set_everyone(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    assert main(["--db", db, "set", "FRS135", "everyone"]) == 0
    conn = get_connection(db)
    assert get_ts_consent(conn, "FRS135")["visibility"] == "everyone"
    conn.close()


def test_allowlist_rejected(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    with pytest.raises(SystemExit):
        main(["--db", db, "set", "FRS135", "allowlist"])
```

(`test_set_nobody`, `test_invalid_visibility_rejected`, `test_delete`, `test_list_runs` bleiben.)

- [ ] **Step 2: Fehlschlag bestätigen**

Run: `pytest tests/test_manage_ts_consent.py -v`
Expected: FAIL (`test_allowlist_rejected` rot, da `allowlist` noch erlaubt)

- [ ] **Step 3: CLI anpassen** in `manage_ts_consent.py`:

```python
_VISIBILITIES = ("everyone", "nobody")
```

und im `set`-Subparser die `--allow`-Option entfernen sowie den `allow`-Zweig in `main`:

```python
    p_set = sub.add_parser("set", help="Einwilligung setzen")
    p_set.add_argument("frs")
    p_set.add_argument("visibility", choices=_VISIBILITIES)
```

```python
        if args.cmd == "set":
            upsert_ts_consent(conn, args.frs, args.visibility, None)
            conn.commit()
            print(f"OK: {args.frs} → {args.visibility}")
```

- [ ] **Step 4: Erfolg bestätigen**

Run: `pytest tests/test_manage_ts_consent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add manage_ts_consent.py tests/test_manage_ts_consent.py
git commit -m "feat(filter): ts_consent-CLI auf everyone/nobody reduziert (allowlist entfällt)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Frontend + Endpoint — `ts_self_frs` entfernen, TS-Hinweis

**Files:**
- Modify: `app/static/index.html`, `app/main.py`

- [ ] **Step 1: Endpoint** — in `app/main.py` im `push_subscribe`-Aufruf die `ts_self_frs`-Zeile entfernen:

```python
        upsert_push_subscription(
            conn, endpoint, p256dh, auth,
            body.get("pilot_filter"),
            notify_prefiles=bool(body.get("notify_prefiles", False)),
            notify_ts=bool(body.get("notify_ts", False)),
        )
```

- [ ] **Step 2: HTML** — in `app/static/index.html` den FRS-Feld-Block entfernen:

```html
      <label class="notif-toggle-row" style="margin-top:6px; display:block;">
        <span style="font-size:0.85em; opacity:0.8;">Eigene FRS-Nr. (optional, unterdrückt Pings über deine eigenen TeamSpeak-Beitritte):</span><br>
        <input type="text" id="notif-ts-frs" placeholder="z. B. FRS49" autocapitalize="characters" style="margin-top:4px; width:130px;">
      </label>
```

und beim Filter-Titel einen Hinweis ergänzen — ersetze:

```html
      <div class="notif-filter-title">Benachrichtigen wenn:</div>
```

durch:

```html
      <div class="notif-filter-title">Benachrichtigen wenn (gilt für Online, Flugplan &amp; TeamSpeak):</div>
```

- [ ] **Step 3: JS** — in `app/static/index.html` die `ts_self_frs`-Logik entfernen:

In `_showNotifPanelContent` den Block streichen:

```javascript
  const tsFrsInput = document.getElementById('notif-ts-frs');
  if (tsFrsInput) {
    tsFrsInput.value = localStorage.getItem('notif_ts_frs') || '';
  }
```

In `_saveNotifFilter` streichen:

```javascript
  let tsSelfFrs = (document.getElementById('notif-ts-frs')?.value || '').trim().toUpperCase();
  if (/^\d+[A-Z]?$/.test(tsSelfFrs)) tsSelfFrs = 'FRS' + tsSelfFrs;  // "49" → "FRS49"
  localStorage.setItem('notif_ts_frs', tsSelfFrs);
```

und im Subscribe-POST-Body die Zeile `ts_self_frs: tsSelfFrs || null,` entfernen.

- [ ] **Step 4: Regression**

Run: `pytest -q`
Expected: PASS (Python unverändert grün). Frontend: keine Test-Harness → durch Smoke + Live-Verifikation abgedeckt.

- [ ] **Step 5: Commit**

```bash
git add app/static/index.html app/main.py
git commit -m "feat(filter): ts_self_frs-Feld entfernt; Auswahl gilt für Online/Flugplan/TS

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Doku + Gesamt-Verifikation

**Files:**
- Modify: `README.md`, `docs/api.md`, `docs/architecture.md`, `CLAUDE.md`

- [ ] **Step 1: README** — im TS-Abschnitt den „Abonnieren"-Absatz aktualisieren: die Piloten-Auswahl („Alle"/„Nur bestimmte") gilt jetzt für Online, Flugplan UND TS; Selbst-Ausschluss = eigenen Haken in „Nur bestimmte" entfernen; das eigene FRS-Feld entfällt. `ts_consent` nur noch `everyone`/`nobody` (CLI ohne `--allow`). Hinweis: in „Nur bestimmte" bekommen reine TS-Leute ohne VATSIM-Flug keinen Ping.

- [ ] **Step 2: docs/api.md** — bei `POST /api/push/subscribe` das `ts_self_frs`-Feld streichen; vermerken, dass `pilot_filter` für alle drei Benachrichtigungstypen gilt.

- [ ] **Step 3: docs/architecture.md** — `app/ts_notify.py`/`recipients_for` als entfernt markieren; den TS-Empfänger-Datenfluss aktualisieren (`cid_for_callsign` → `get_ts_push_subscriptions(cid)` → `ts_consent`-`nobody`-Check); `ts_self_frs` als tote Spalte vermerken.

- [ ] **Step 4: CLAUDE.md** — `app/ts_notify.py` aus der Projektstruktur entfernen; Hinweis auf gemeinsamen `pilot_filter`.

- [ ] **Step 5: Volle Verifikation**

Run: `pytest -q`
Expected: PASS (keine Regressionen; `test_ts_notify.py` ist weg)

Run: `python -c "import app.main; import app.poller; import app.database; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add README.md docs/api.md docs/architecture.md CLAUDE.md
git commit -m "docs: einheitlicher Empfänger-Filter (Online/Flugplan/TS) dokumentiert

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec-Abdeckung:**
- `pilot_filter` gilt auch für TS → Task 1 (`cid_for_callsign`, `get_ts_push_subscriptions(cid)`) + Task 2 (`_poll_teamspeak`) ✓
- Selbst-Ausschluss via Abwählen (kein Extra-Feld) → ergibt sich aus pilot_filter-Nutzung; `ts_self_frs` raus → Task 4 ✓
- `ts_self_frs`-Feld entfernt (UI + Endpoint + Logik) → Task 2 (Logik via recipients_for-Wegfall), Task 4 (UI/Endpoint) ✓
- `ts_consent` → `everyone`/`nobody`, CLI ohne `--allow` → Task 3; Poller nur `nobody` → Task 2 ✓
- Reine TS-Leute nicht einzeln wählbar, cid None → nur „Alle" → Task 1/2 (`test_ts_unknown_frs_only_all`) ✓
- Verhaltenstabelle (Alle/Nur bestimmte × Online/Flugplan/TS/Self/TS-only) → Tests in Task 1/2 ✓
- Doku → Task 5 ✓

**Platzhalter:** keine.

**Typ-/Signatur-Konsistenz:** `get_ts_push_subscriptions(conn, cid)` neue Signatur überall (DB-Test, Poller); `cid_for_callsign(conn, callsign) -> int | None`; `recipients_for` vollständig entfernt (Import + Datei + Tests).
