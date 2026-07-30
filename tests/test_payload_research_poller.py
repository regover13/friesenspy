# tests/test_payload_research_poller.py
"""Der AP32-Regressionstest.

Gemessen 2026-07-30: poller.py:892 setzte _payload_research_attempted.add(code) VOR dem
Versuch und nahm den Code bei Misserfolg nie wieder heraus. Ein zweiter Anlauf brauchte einen
Prozess-Neustart UND einen Piloten, der genau dieses Muster wieder live fliegt.

Der Test aus Rev. 1 ("ein zweiter Lauf versucht es erneut") waere gruen gewesen, ohne dass je
ein zweiter Lauf stattfindet. Deshalb hier mit kontrollierter Uhr: bei t0+2min NICHT, bei
t0+6min DOCH.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import llm
from app.database import (
    get_connection,
    get_payload_research,
    init_db,
    mark_payload_research,
)

T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    return p


def _poller(db_path):
    from app.poller import VatsimPoller
    return VatsimPoller(db_path=db_path, callsign_prefix="FRS")


def _flug(db_path, cid, code, ts):
    c = get_connection(db_path)
    c.execute(
        "INSERT INTO flight_cache (cid, callsign, aircraft, logon_time) VALUES (?,?,?,?)",
        (cid, "FRS1", code, ts),
    )
    c.commit()
    c.close()


@pytest.mark.asyncio
async def test_transienter_fehler_sperrt_nicht_dauerhaft(db, monkeypatch):
    p = _poller(db)
    versuche = []

    def _fake(code):
        versuche.append(code)
        raise llm.TransientResearchError("Overloaded")

    monkeypatch.setattr(llm, "suggest_aircraft_payload", _fake)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._auto_research_payload("AP32")
    assert versuche == ["AP32"]
    row = get_payload_research(get_connection(db), "AP32")
    assert row["state"] == "fehler"
    assert row["attempts"] == 1

    # Zu frueh: kein zweiter Versuch.
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(minutes=2))
    await p._auto_research_payload("AP32")
    assert versuche == ["AP32"], "Backoff nicht eingehalten"

    # Faellig: erneut.
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(minutes=6))
    await p._auto_research_payload("AP32")
    assert versuche == ["AP32", "AP32"], "transienter Fehler wurde als endgueltig behandelt"


@pytest.mark.asyncio
async def test_keine_daten_wird_nicht_stuendlich_wiederholt(db, monkeypatch):
    p = _poller(db)
    versuche = []
    monkeypatch.setattr(llm, "suggest_aircraft_payload",
                        lambda code: versuche.append(code) or None)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._auto_research_payload("NAV")
    assert get_payload_research(get_connection(db), "NAV")["state"] == "nichts_gefunden"
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(days=29))
    await p._auto_research_payload("NAV")
    assert len(versuche) == 1
    monkeypatch.setattr(p, "_now", lambda: T0 + timedelta(days=31))
    await p._auto_research_payload("NAV")
    assert len(versuche) == 2


@pytest.mark.asyncio
async def test_erfolg_schreibt_payload_und_ok(db, monkeypatch):
    p = _poller(db)
    monkeypatch.setattr(llm, "suggest_aircraft_payload", lambda code: {
        "make_model": "Aeroprakt A-32 Vixxen", "mtow_kg": 600.0, "empty_kg": 350.0,
        "fuel_kg": 40.0, "fuel_full_kg": 80.0, "crew_kg": 85.0, "payload_kg": 125.0,
    })
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._auto_research_payload("AP32")
    c = get_connection(db)
    assert get_payload_research(c, "AP32")["state"] == "ok"
    row = c.execute(
        "SELECT make_model, source FROM aircraft_payloads WHERE type_code='AP32'"
    ).fetchone()
    assert row["make_model"] == "Aeroprakt A-32 Vixxen"
    assert row["source"] == "llm"


@pytest.mark.asyncio
async def test_manuell_gepflegt_wird_nie_ueberschrieben(db, monkeypatch):
    from app.database import upsert_payload
    c = get_connection(db)
    upsert_payload(c, "AP32", mtow_kg=1.0, empty_kg=1.0, fuel_kg=1.0, fuel_full_kg=1.0,
                   crew_kg=85.0, source="manual", make_model="Von Hand")
    c.commit()
    p = _poller(db)
    monkeypatch.setattr(llm, "suggest_aircraft_payload",
                        lambda code: pytest.fail("darf nicht aufgerufen werden"))
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._auto_research_payload("AP32")
    row = get_connection(db).execute(
        "SELECT make_model FROM aircraft_payloads WHERE type_code='AP32'"
    ).fetchone()
    assert row["make_model"] == "Von Hand"


@pytest.mark.asyncio
async def test_nachlese_holt_altbestand_und_haelt_den_deckel(db, monkeypatch):
    """30 der 33 Luecken sind Altfluege ohne aircraft_icao -- ohne Nachlese unerreichbar."""
    for i, code in enumerate(["P28S", "P28S", "AP32", "FK9", "M20T", "PA60", "C195", "B58T"]):
        _flug(db, i, code, "2025-06-06T10:00:00Z")
    p = _poller(db)
    geholt = []
    monkeypatch.setattr(llm, "suggest_aircraft_payload",
                        lambda code: geholt.append(code) or None)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._research_due_payloads()
    assert len(geholt) == p._PAYLOAD_RESEARCH_LIMIT, "Deckel je Lauf nicht eingehalten"
    assert geholt[0] == "P28S", "haeufigstes Muster nicht zuerst"


@pytest.mark.asyncio
async def test_nachlese_stirbt_nicht_an_einem_einzelnen_fehler(db, monkeypatch):
    for i, code in enumerate(["AP32", "FK9"]):
        _flug(db, i, code, "2026-07-25T10:00:00Z")
    p = _poller(db)
    gesehen = []

    def _fake(code):
        gesehen.append(code)
        if code == "AP32":
            raise RuntimeError("irgendwas Unerwartetes")
        return None

    monkeypatch.setattr(llm, "suggest_aircraft_payload", _fake)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._research_due_payloads()   # darf nicht durchschlagen
    assert set(gesehen) == {"AP32", "FK9"}


@pytest.mark.asyncio
async def test_nachlese_uebersteht_db_fehler_beim_schreiben_eines_kandidaten(db, monkeypatch):
    """Review-Befund: der Schreib-Block nach erfolgreicher (oder ergebnisloser) Recherche war
    nur in try/finally, nicht try/except. Ein DB-Fehler dort (z. B. SQLite-Lock-Kontention
    zwischen Live-Trigger und Nachlese) propagierte ungefangen bis in _research_due_payloads
    und beendete dort die GESAMTE Nachlese -- nicht nur den einen Kandidaten. Bei drei fälligen
    Mustern durfte ein Fehler bei AP32 FK9/M20T nicht verhindern."""
    for i, code in enumerate(["AP32", "FK9", "M20T"]):
        _flug(db, i, code, "2026-07-25T10:00:00Z")
    p = _poller(db)
    gesehen = []
    monkeypatch.setattr(llm, "suggest_aircraft_payload",
                        lambda code: gesehen.append(code) or None)

    from app import database
    original = database.mark_payload_research

    def _boom_bei_ap32(conn, code, state, now, last_error=None):
        if code == "AP32":
            raise RuntimeError("database is locked")
        return original(conn, code, state, now, last_error=last_error)

    monkeypatch.setattr(database, "mark_payload_research", _boom_bei_ap32)
    monkeypatch.setattr(p, "_now", lambda: T0)
    await p._research_due_payloads()
    assert set(gesehen) == {"AP32", "FK9", "M20T"}, \
        "ein DB-Fehler beim Schreiben fuer EINEN Kandidaten darf die uebrigen nicht verhindern"


@pytest.mark.asyncio
async def test_in_memory_set_ist_weg(db):
    """Explizit: der alte Mechanismus darf nicht als zweite Wahrheit zurueckkommen."""
    p = _poller(db)
    assert not hasattr(p, "_payload_research_attempted")
