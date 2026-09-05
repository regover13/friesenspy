# Kalendertermin und Event-Objekt: Verknüpfung explizit machen

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline) oder
> superpowers:subagent-driven-development. Schritte sind Checkboxen.

**Goal:** Ein Event-Objekt (Bummel/Kutter) verdeckt seinen Kalendertermin nur noch, wenn beide
ausdrücklich verknüpft sind — und was im Admin geändert wurde, überschreibt der Kalender-Sync nie
wieder.

**Architecture:** Drei Bausteine. (1) `manual_fields` je Objekt: eine CSV der Feldnamen, die ein
Mensch im Admin tatsächlich geändert hat; der Kalender-Upsert lässt genau diese Felder in Ruhe.
(2) `calendar_uid` wird im Admin wählbar — es ist ab jetzt die *einzige* Aussage darüber, ob
Termin und Objekt dasselbe Ereignis sind; das Stichwort-Verwerfen (`is_kutter_calendar_entry`)
entfällt. (3) Die Events-Liste zeigt für ein verknüpftes Paar nur noch das Objekt (mit den
Admin-Werten) und den Termin nur, wenn kein Objekt an ihm hängt.

**Tech Stack:** Python 3.11, FastAPI, SQLite (WAL), pytest; Frontend Vanilla JS in
`app/static/index.html` + `app/static/admin.html`.

**Spec:** GitHub-Issue [regover13/friesenspy#19](https://github.com/regover13/friesenspy/issues/19)

## Global Constraints

- **Regel 2 wird je Feld umgesetzt** (Entscheidung des Nutzers, 05.09.2026): geschützt ist nur,
  was im Admin tatsächlich einen anderen Wert bekommen hat. Verschiebt der Kalender danach
  `dtstart`, zieht die Zeit weiter mit, solange die Zeit nicht von Hand angefasst wurde.
- **Der Kalenderimport für Kutter bleibt deaktiviert** (Entscheidung 20.07.2026, Variante ①).
  Ein Kalendertermin legt *keinen* Kutter an — er braucht ein Frachtmanifest. Nach dem Wegfall
  von `is_kutter_calendar_entry` muss deshalb der `is_transport`-Zweig in `_sync_calendar`
  entfernt werden, sonst kommt der Kalender-Kutter durch die Hintertür zurück.
- **Keine Automatik über Datum/Uhrzeit.** Verknüpft wird von Hand; FriesenSpy darf nur
  *vorschlagen*.
- `"highlight": false` in jedem CHANGELOG-Eintrag (stehende Regel).
- Tests laufen im venv: `/home/claude/.venv-friesenspy/bin/pytest`.
- `app/CHANGELOG.json` erst anfassen, wenn keine Suite läuft (auch keine in einer Parallelsitzung).

---

### Task 1: `manual_fields` — Schutzmarke je Feld

**Files:**
- Modify: `app/database.py` (Schema ~Z. 177/208, `_BUMMEL_MIGRATIONS` ~Z. 736, Transport-Migrationen)
- Modify: `app/database.py:4833` (`upsert_calendar_bummel_race`)
- Test: `tests/test_bummel_admin_db.py`

**Interfaces:**
- Produces: Spalte `manual_fields TEXT` in `bummel_races` und `transport_events` (CSV, z. B.
  `"route,dtstart"`, NULL/leer = nichts von Hand).
- Produces: `manual_fields_of(row) -> set[str]`, `mark_manual_fields(conn, table, obj_id, fields: set[str]) -> None`,
  `clear_manual_field(conn, table, obj_id, field: str) -> None` in `app/database.py`.
  `table` ∈ `"bummel_races"` | `"transport_events"` (Whitelist, kein freier String ins SQL).

- [ ] **Step 1: Failing test — der Kalender-Sync lässt ein von Hand geändertes Feld in Ruhe**

```python
def test_calendar_sync_laesst_handgeaenderte_route_stehen(tmp_path):
    conn = get_connection(str(tmp_path / "t.db"))
    ev = {"uid": "u1", "summary": "Bummel", "route": "EDWF,EDWG",
          "dtstart": "2026-09-07T18:00:00Z", "dtend": "2026-09-07T22:00:00Z"}
    upsert_calendar_bummel_race(conn, ev)
    rid = conn.execute("SELECT id FROM bummel_races WHERE calendar_uid='u1'").fetchone()[0]
    update_bummel_race(conn, rid, route="EDWF,EDWG,EDXR")
    mark_manual_fields(conn, "bummel_races", rid, {"route"})
    # Kalender liefert erneut den alten (falschen) Stand — plus eine neue Uhrzeit
    ev["dtstart"] = "2026-09-07T19:00:00Z"
    upsert_calendar_bummel_race(conn, ev)
    row = get_bummel_race(conn, rid)
    assert row["route"] == "EDWF,EDWG,EDXR"        # von Hand → geschützt
    assert row["dtstart"] == "2026-09-07T19:00:00Z"  # nicht angefasst → folgt dem Kalender
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag sehen**

`/home/claude/.venv-friesenspy/bin/pytest tests/test_bummel_admin_db.py -k handgeaenderte -v`
Erwartet: `ImportError: cannot import name 'mark_manual_fields'`.

- [ ] **Step 3: Spalte, Migration und Helfer anlegen**

Im `CREATE TABLE`-Block beider Tabellen `manual_fields TEXT` ergänzen, dazu in den passenden
Migrationslisten `ALTER TABLE bummel_races ADD COLUMN manual_fields TEXT` bzw.
`ALTER TABLE transport_events ADD COLUMN manual_fields TEXT`. Helfer:

```python
_MANUAL_TABLES = {"bummel_races", "transport_events"}

def manual_fields_of(row: dict | sqlite3.Row) -> set[str]:
    raw = (dict(row).get("manual_fields") or "")
    return {f for f in (p.strip() for p in raw.split(",")) if f}

def mark_manual_fields(conn, table: str, obj_id: int, fields: set[str]) -> None:
    """Feldnamen als 'von Hand gesetzt' vormerken (additiv, idempotent)."""
    if table not in _MANUAL_TABLES or not fields:
        return
    row = conn.execute(f"SELECT manual_fields FROM {table} WHERE id = ?", (obj_id,)).fetchone()
    if row is None:
        return
    merged = sorted(manual_fields_of(row) | set(fields))
    conn.execute(f"UPDATE {table} SET manual_fields = ? WHERE id = ?",
                 (",".join(merged), obj_id))

def clear_manual_field(conn, table: str, obj_id: int, field: str) -> None:
    """Schutz für ein Feld aufheben — der nächste Kalender-Sync darf es wieder setzen."""
    if table not in _MANUAL_TABLES:
        return
    row = conn.execute(f"SELECT manual_fields FROM {table} WHERE id = ?", (obj_id,)).fetchone()
    if row is None:
        return
    rest = sorted(manual_fields_of(row) - {field})
    conn.execute(f"UPDATE {table} SET manual_fields = ? WHERE id = ?",
                 (",".join(rest) or None, obj_id))
```

- [ ] **Step 4: `upsert_calendar_bummel_race` respektiert die Marken**

Das `ON CONFLICT ... DO UPDATE SET` schreibt heute vier Felder bedingungslos. Statt SQL-Akrobatik
wird die vorhandene Zeile ohnehin schon gelesen (`before`) — die geschützten Felder werden vor dem
Upsert aus `ev` durch die Bestandswerte ersetzt:

```python
    before = conn.execute(
        "SELECT id, route, dtstart, dtend, name, manual_fields FROM bummel_races "
        "WHERE calendar_uid = ?", (uid,)).fetchone()
    # Regel 2 (#19): Was im Admin angefasst wurde, überschreibt der Kalender nicht mehr.
    protected = manual_fields_of(before) if before else set()
    name    = before["name"]    if "name"    in protected else (ev.get("summary") or "")
    route   = before["route"]   if "route"   in protected else (ev.get("route") or "")
    dtstart = before["dtstart"] if "dtstart" in protected else (ev.get("dtstart") or "")
    dtend   = before["dtend"]   if "dtend"   in protected else _effective_dtend(
        ev.get("dtstart") or "", ev.get("dtend"))
```

Die Snapshot-Invalidierung darunter bleibt unverändert — sie vergleicht die Zeile vorher/nachher
und greift damit automatisch nur noch bei echten Änderungen.

**Achtung:** `dtstart` geschützt, `dtend` nicht → `_effective_dtend` bekäme den *Kalender*-Start.
Deshalb im ungeschützten Zweig `_effective_dtend(dtstart, ev.get("dtend"))` mit dem oben
berechneten effektiven `dtstart` aufrufen, nicht mit `ev["dtstart"]`.

- [ ] **Step 5: Dasselbe in `upsert_calendar_transport_event`** (`app/database.py:5742`) —
gleiche Ersetzung für `name`/`route`/`dtstart`/`dtend`. `destination` wird dort schon heute nicht
überschrieben; das bleibt so.

- [ ] **Step 6: Tests grün**

`/home/claude/.venv-friesenspy/bin/pytest tests/test_bummel_admin_db.py tests/test_database.py -q`

- [ ] **Step 7: Commit** — `feat(#19): manual_fields — Kalender-Sync laesst handgeaenderte Felder stehen`

---

### Task 2: Der Admin markiert automatisch, was er ändert

**Files:**
- Modify: `app/main.py:3421` (`admin_update_race`), `app/main.py:3897` (`admin_update_transport_event`)
- Test: `tests/test_admin_api.py`

**Interfaces:**
- Consumes: `mark_manual_fields` aus Task 1.

**Warum Wert-Vergleich und nicht „steht im Body":** `saveEdit` in `admin.html:2023` schickt
**immer alle vier Felder**, auch die unveränderten. Wer die Marke am Vorhandensein im Body
festmacht, markiert beim ersten Speichern alles und hebelt Regel 2 komplett aus. Verglichen wird
deshalb die Zeile *vorher* gegen *nachher* — dasselbe Muster, das `upsert_calendar_bummel_race`
schon für den Snapshot benutzt.

- [ ] **Step 1: Failing test**

```python
def test_admin_speichern_markiert_nur_wirklich_geaenderte_felder(client, admin_cookie):
    # Rennen aus dem Kalender, danach nur die Strecke korrigieren
    rid = _kalender_rennen(route="EDWF,EDWG", dtstart="2026-09-07T18:00:00Z")
    client.post(f"/api/admin/bummel/races/{rid}", cookies=admin_cookie, json={
        "name": "Bummel", "route": "EDWF,EDWG,EDXR",
        "dtstart": "2026-09-07T18:00:00Z", "dtend": "2026-09-07T22:00:00Z"})
    row = _race_row(rid)
    assert manual_fields_of(row) == {"route"}
```

- [ ] **Step 2: Fehlschlag sehen** — `AssertionError: set() == {'route'}`.

- [ ] **Step 3: Implementieren** — in beiden Endpunkten nach `update_*(...)`:

```python
        after = get_bummel_race(conn, race_id)
        changed = {k for k in ("name", "route", "dtstart", "dtend")
                   if (cur.get(k) or "") != (after.get(k) or "")}
        if changed:
            mark_manual_fields(conn, "bummel_races", race_id, changed)
```

Für den Kutter analog mit `get_transport_event` / `"transport_events"` und der Feldliste
`("name", "destination", "dtstart", "dtend")`.

- [ ] **Step 4: Tests grün** — `pytest tests/test_admin_api.py -q`
- [ ] **Step 5: Commit** — `feat(#19): Admin-Aenderungen markieren sich selbst als handgesetzt`

---

### Task 3: `calendar_uid` im Admin wählbar — die Verknüpfung wird ausgesprochen

**Files:**
- Modify: `app/main.py` (neuer Endpunkt + `calendar_uid` in beiden Update-Endpunkten)
- Modify: `app/database.py` (`_UPDATABLE_RACE_FIELDS`, Update-Funktion Transport)
- Test: `tests/test_admin_api.py`

**Interfaces:**
- Produces: `GET /api/admin/calendar/events?around=<ISO>&days=3` →
  `[{uid, summary, dtstart, dtend, route, is_bummel, is_transport, claimed_by}]`,
  `claimed_by` ∈ `null` | `"bummel:{id}"` | `"kutter:{id}"`.
- Produces: `POST /api/admin/bummel/races/{id}` und `.../transport/events/{id}` akzeptieren
  `calendar_uid` (String oder `null` zum Lösen).
- Produces: `claimed_calendar_uids(conn) -> set[str]` in `app/database.py` — alle UIDs, an denen
  ein Objekt hängt. Wird in Task 4 und 5 wiederverwendet.

- [ ] **Step 1: Failing test**

```python
def test_verknuepfen_setzt_calendar_uid_und_schuetzt_alle_felder(client, admin_cookie):
    rid = _manuelles_rennen(name="Aach-Bummel")
    r = client.post(f"/api/admin/bummel/races/{rid}", cookies=admin_cookie,
                    json={"calendar_uid": "u-abend"})
    assert r.status_code == 200
    row = _race_row(rid)
    assert row["calendar_uid"] == "u-abend"
    # Ein von Hand angelegtes Objekt ist in allen Feldern Menschenwerk -> komplett geschuetzt
    assert manual_fields_of(row) == {"name", "route", "dtstart", "dtend"}

def test_verknuepfen_auf_belegten_termin_gibt_409(client, admin_cookie):
    _kalender_rennen(uid="u-abend")
    rid = _manuelles_rennen()
    r = client.post(f"/api/admin/bummel/races/{rid}", cookies=admin_cookie,
                    json={"calendar_uid": "u-abend"})
    assert r.status_code == 409
```

- [ ] **Step 2: Fehlschlag sehen** (`calendar_uid` wird heute stillschweigend ignoriert → 200,
      aber `calendar_uid is None`).

- [ ] **Step 3: Implementieren**

`_UPDATABLE_RACE_FIELDS` um `calendar_uid` erweitern (analog beim Transport-Update). Im Endpunkt
vor dem Update prüfen:

```python
    if "calendar_uid" in body:
        uid = (body.get("calendar_uid") or "").strip() or None
        if uid:
            if not conn.execute("SELECT 1 FROM calendar_events WHERE uid = ?", (uid,)).fetchone():
                raise HTTPException(status_code=400, detail="Kalendertermin nicht gefunden")
            taken = conn.execute(
                "SELECT id FROM bummel_races WHERE calendar_uid = ? AND id != ?",
                (uid, race_id)).fetchone()
            if taken or conn.execute(
                    "SELECT id FROM transport_events WHERE calendar_uid = ?", (uid,)).fetchone():
                raise HTTPException(status_code=409, detail="Termin hängt schon an einem Event")
        fields["calendar_uid"] = uid
        # Ein von Hand gepflegtes Objekt ist in allen Feldern Menschenwerk: beim Verknuepfen
        # alles schuetzen, sonst zieht der naechste Sync den Kalenderstand darueber.
        if uid and cur.get("source") == "manual":
            mark_manual_fields(conn, "bummel_races", race_id,
                               {"name", "route", "dtstart", "dtend"})
```

- [ ] **Step 4: Auswahl-Endpunkt** (`app/main.py`, bei den übrigen Admin-Routen):

```python
@app.get("/api/admin/calendar/events")
async def admin_calendar_events(request: Request, around: str = "", days: int = 3):
    """Kalendertermine im Umkreis von ``around`` (±``days`` Tage) zur Auswahl im Admin —
    #19: die Verknüpfung Termin↔Objekt wird von Hand ausgesprochen, FriesenSpy schlägt nur vor."""
    require_admin(request)
    ...
```

Er liefert Termine sortiert nach `dtstart` samt `claimed_by`, damit die Oberfläche belegte
Termine ausgrauen kann statt in den 409 zu laufen.

- [ ] **Step 5: Tests grün**, **Step 6: Commit** — `feat(#19): Termin und Objekt im Admin verknuepfbar`

---

### Task 4: Stichwort-Verwerfen entfällt — ohne den Kalender-Kutter zurückzuholen

**Files:**
- Modify: `app/calendar_sync.py:151` (`is_kutter_calendar_entry` entfernen), `:226` (Aufruf)
- Modify: `app/poller.py:1357-1360` (`is_transport`-Zweig)
- Modify: `app/database.py:8520` (`events_due_for_reminder`)
- Test: `tests/test_calendar_sync.py` (Klasse `TestKutterCalendarSuppression` ersetzen),
  `tests/test_event_push.py`

- [ ] **Step 1: Failing tests**

```python
def test_kutter_termin_wird_aufgenommen():
    evs = parse_ical_bytes(_ical("Krabben für Wooge — FriesenKutter", "EDWG"))
    assert [e["summary"] for e in evs] == ["Krabben für Wooge — FriesenKutter"]

def test_kalender_legt_keinen_kutter_an(poller_conn):
    # Variante ① bleibt: ein Termin erzeugt kein Transport-Objekt
    assert poller_conn.execute("SELECT COUNT(*) FROM transport_events").fetchone()[0] == 0

def test_unverknuepfter_kutter_termin_wird_erinnert(conn):
    # Regel 1: ohne Objekt ist der Termin ein ganz normales Event — er erinnert
    due = events_due_for_reminder(conn, now="2026-09-07T17:30:00Z", lead_min=60)
    assert [e["uid"] for e in due] == ["u-kutter"]

def test_verknuepfter_termin_erinnert_nicht_doppelt(conn):
    _link("u-kutter", "transport_events")
    assert events_due_for_reminder(conn, now="2026-09-07T17:30:00Z", lead_min=60) == []
```

- [ ] **Step 2: Fehlschläge sehen.**

- [ ] **Step 3: Implementieren.** `is_kutter_calendar_entry` samt Aufruf und Docstring-Absatz
löschen. In `_sync_calendar` den `is_transport`-Zweig entfernen und durch einen Kommentar
ersetzen:

```python
                        if ev.get("is_bummel"):
                            upsert_calendar_bummel_race(conn, ev)
                        # Kein Kutter aus dem Kalender (Variante ①, 20.07.2026): ein Termin kann
                        # kein Frachtmanifest tragen. #19 hat das Stichwort-Verwerfen entfernt —
                        # der Termin wird jetzt gespeichert und angezeigt, aber kein Objekt daraus.
```

`upsert_calendar_transport_event` bleibt ungenutzt im Code (wie seit 20.07.2026) — der Import in
`_sync_calendar` fällt weg.

In `events_due_for_reminder` die Bedingung `AND is_bummel = 0 AND is_transport = 0` ersetzen:

```sql
        AND uid NOT IN (SELECT calendar_uid FROM bummel_races     WHERE calendar_uid IS NOT NULL)
        AND uid NOT IN (SELECT calendar_uid FROM transport_events WHERE calendar_uid IS NOT NULL)
```

Das ist der Kern von Regel 3 auf der Push-Seite: Doppel-Pushs verhindert ab jetzt die
Verknüpfung, nicht mehr ein Flag im Termin.

- [ ] **Step 4: Tests grün** — `pytest tests/test_calendar_sync.py tests/test_event_push.py -q`
- [ ] **Step 5: Commit** — `feat(#19): Kutter-Termine nicht mehr am Stichwort verwerfen`

---

### Task 5: Anzeige — Objekt schlägt Termin, aber nur bei Verknüpfung

**Files:**
- Modify: `app/database.py:4816` (`get_calendar_events`)
- Modify: `app/static/index.html:8996-9040` (`fetchFriesenEvents`)
- Test: `tests/test_events_endpoint.py`, `tests/test_ui_static.py` (Muster: Zeichenketten an
  Eigenschaftsnamen binden, nicht an Kommentare)

- [ ] **Step 1: Failing test**

```python
def test_verknuepfter_termin_taucht_nicht_mehr_in_der_liste_auf(conn):
    _termin("u-abend"); _rennen(calendar_uid="u-abend")
    assert [e["uid"] for e in get_calendar_events(conn)] == []

def test_unverknuepfter_termin_bleibt_sichtbar(conn):
    _termin("u-abend")
    assert [e["uid"] for e in get_calendar_events(conn)] == ["u-abend"]
```

- [ ] **Step 2: Fehlschlag sehen.**

- [ ] **Step 3: Implementieren** — `get_calendar_events` filtert beanspruchte UIDs weg
(dieselben zwei Unterabfragen wie in Task 4).

- [ ] **Step 4: Frontend nachziehen.** `fetchFriesenEvents` ergänzt heute nur
`source === 'manual'`. Da verknüpfte Kalender-Termine jetzt fehlen, muss die Liste **alle**
Rennen/Kutter aufnehmen, sonst verschwinden Kalender-Bummel ganz:

```javascript
      manualEvents = (races || [])
        .filter(r => r.dtstart && r.dtstart <= _nowIso())   // Liste zeigt Vergangenes
        .map(r => ({ ..., _manual: r.source === 'manual' }));
```

Der `(manuell)`-Hinweis hängt danach an `source === 'manual'`, nicht mehr daran, wie die Zeile in
die Liste kam. Name und Strecke kommen jetzt aus dem Objekt — genau dadurch wird eine
Admin-Korrektur an einem Kalender-Bummel im Events-Tab endlich sichtbar.

- [ ] **Step 5: Tests grün**, **Step 6: Commit** — `feat(#19): Events-Liste zeigt das Objekt, den Termin nur unverknuepft`

---

### Task 6: Admin zeigt die Marken und kann sie zurücknehmen

**Files:**
- Modify: `app/main.py` (Renn-/Kutter-Listen im Admin um `manual_fields` erweitern; neuer
  Endpunkt `POST /api/admin/bummel/races/{id}/kalenderstand/{feld}`)
- Modify: `app/static/admin.html` (Etikett je Feld + Knopf, Termin-Auswahlfeld aus Task 3)
- Test: `tests/test_admin_api.py`, `tests/test_admin_ui_static.py`

- [ ] **Step 1: Failing test**

```python
def test_kalenderstand_zurueckholen_setzt_den_termin_wert(client, admin_cookie):
    rid = _kalender_rennen(route="EDWF,EDWG")
    client.post(f"/api/admin/bummel/races/{rid}", cookies=admin_cookie, json={"route": "EDWF,EDXR"})
    r = client.post(f"/api/admin/bummel/races/{rid}/kalenderstand/route", cookies=admin_cookie)
    assert r.status_code == 200
    row = _race_row(rid)
    assert row["route"] == "EDWF,EDWG"          # sofort zurück, nicht erst in 6 Stunden
    assert manual_fields_of(row) == set()
```

- [ ] **Step 2: Fehlschlag sehen (404).**

- [ ] **Step 3: Implementieren** — Endpunkt liest den Wert aus `calendar_events` über
`calendar_uid`, schreibt ihn zurück und ruft `clear_manual_field`. Ohne `calendar_uid` → 400
(„Rennen hängt an keinem Termin"). Der Wert kommt sofort zurück; auf den nächsten Sync zu warten
wäre für den Bediener nicht erklärbar.

- [ ] **Step 4: Admin-Oberfläche.** Im Bearbeiten-Formular je Feld ein kleines Etikett
(`aus dem Kalender` / `von Hand ↺`), der Pfeil ruft den Endpunkt. Dazu das Auswahlfeld
„Kalendertermin" (Liste aus `GET /api/admin/calendar/events?around=<dtstart>`), Vorbelegung:
gleicher Tag + Stichwort passt — **vorausgewählt, nicht gesetzt**; gespeichert wird erst mit dem
Formular.

- [ ] **Step 5: Tests grün**, **Step 6: Commit** — `feat(#19): Admin zeigt Schutzmarken und holt den Kalenderstand zurueck`

---

### Task 7: Doku und Release

**Files:**
- Modify: `CLAUDE.md`, `docs/api.md:619`, `docs/architecture.md:81/84`, `README.md`
- Modify: `app/CHANGELOG.json`, `app/version.py`

- [ ] **Step 1:** Alle vier Doku-Stellen, die „Kutter-Termine ausgeschlossen (Variante ①)"
behaupten, auf den neuen Stand bringen: Termine werden aufgenommen und angezeigt, **kein** Objekt
entsteht daraus, und die Verknüpfung ist Handarbeit.
- [ ] **Step 2:** CHANGELOG-Eintrag (`"highlight": false`), Version MINOR (14.20.x → 14.21.0).
  Vorher prüfen, dass keine Suite läuft.
- [ ] **Step 3:** Volle Suite: `/home/claude/.venv-friesenspy/bin/pytest tests/ -q`
- [ ] **Step 4:** Commit + Push **erst nach Rückfrage** — jeder Push deployt sofort und startet
  den Container neu (stehende Regel: nicht in den laufenden Betrieb deployen).

---

## Was dieser Plan bewusst nicht tut

- **Keine Datenmigration bestehender Zeilen.** `manual_fields` startet leer; Admin-Korrekturen,
  die vor heute gemacht wurden, sind nicht rekonstruierbar (der Kalender hat sie längst
  überschrieben). Der Schutz greift ab der nächsten Bearbeitung.
- **Kein Auto-Verknüpfen** bestehender Kutter mit ihren alten Kalenderterminen — die Termine
  wurden nie gespeichert, es gibt nichts zu verknüpfen. Ab dem nächsten Sync stehen sie zur
  Auswahl.
