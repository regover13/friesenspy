"""Tests für Bummel-Admin-Persistenz (Phase B): CRUD, Overrides, apply_bummel_overrides.

TDD: Diese Datei enthält die Spezifikation — ZUERST rot, dann grün durch die Implementierung.
"""
from __future__ import annotations

import copy
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    _DDL,
    bummel_races_due_for_reminder,
    create_bummel_race,
    delete_bummel_override,
    delete_bummel_race,
    get_bummel_race,
    get_connection,
    init_db,
    list_bummel_overrides,
    list_bummel_races,
    mark_event_reminded,
    set_bummel_push_enabled,
    set_bummel_started,
    update_bummel_race,
    upsert_bummel_override,
    apply_bummel_overrides,
)


# ---------------------------------------------------------------------------
# Gemeinsame Test-Infrastruktur
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    """In-Memory-DB nach dem Muster der bestehenden Bummel-Tests aufbauen."""
    init_db(":memory:")
    conn = get_connection(":memory:")
    conn.executescript(_DDL)
    conn.commit()
    return conn


def _race(conn, *, name="TestBummel", route="EDWF,EDWG,EDWR",
          dtstart="2026-06-27T10:00:00Z", dtend="2026-06-27T20:00:00Z") -> int:
    """Hilfsfunktion: Legt ein manuelles Rennen an und gibt die ID zurück."""
    return create_bummel_race(conn, name=name, route=route, dtstart=dtstart, dtend=dtend)


# ---------------------------------------------------------------------------
# Aufgabe 1 — bummel_races Erweiterung: push_enabled + started_at
# ---------------------------------------------------------------------------

class TestBummelRacesNewColumns:
    def test_push_enabled_default_is_1(self):
        conn = _make_conn()
        rid = _race(conn)
        assert get_bummel_race(conn, rid)["push_enabled"] == 1

    def test_started_at_default_is_null(self):
        conn = _make_conn()
        rid = _race(conn)
        assert get_bummel_race(conn, rid)["started_at"] is None

    def test_list_includes_new_columns(self):
        conn = _make_conn()
        _race(conn)
        row = list_bummel_races(conn)[0]
        assert "push_enabled" in row
        assert "started_at" in row

    def test_set_bummel_started_latches_first_value(self):
        """set_bummel_started setzt nur beim ersten Aufruf (latchend wie revealed_at)."""
        conn = _make_conn()
        rid = _race(conn)
        set_bummel_started(conn, rid, "2026-06-27T10:05:00Z")
        assert get_bummel_race(conn, rid)["started_at"] == "2026-06-27T10:05:00Z"
        # Zweiter Aufruf mit anderem Zeitstempel darf nichts überschreiben
        set_bummel_started(conn, rid, "2026-06-27T10:10:00Z")
        assert get_bummel_race(conn, rid)["started_at"] == "2026-06-27T10:05:00Z"

    def test_set_bummel_push_enabled_toggle(self):
        conn = _make_conn()
        rid = _race(conn)
        set_bummel_push_enabled(conn, rid, False)
        assert get_bummel_race(conn, rid)["push_enabled"] == 0
        set_bummel_push_enabled(conn, rid, True)
        assert get_bummel_race(conn, rid)["push_enabled"] == 1


# ---------------------------------------------------------------------------
# Aufgabe 2 — manuelle Renn-CRUD
# ---------------------------------------------------------------------------

class TestCreateBummelRace:
    def test_source_is_manual_and_uid_is_null(self):
        conn = _make_conn()
        rid = _race(conn)
        race = get_bummel_race(conn, rid)
        assert race["source"] == "manual"
        assert race["calendar_uid"] is None

    def test_fields_stored_correctly(self):
        conn = _make_conn()
        rid = create_bummel_race(
            conn,
            name="Ostfriesland Bummel",
            route="EDWF,EDWG,EDWR",
            dtstart="2026-06-27T10:00:00Z",
            dtend="2026-06-27T20:00:00Z",
            radius_km=15.0,
        )
        race = get_bummel_race(conn, rid)
        assert race["name"] == "Ostfriesland Bummel"
        assert race["route"] == "EDWF,EDWG,EDWR"
        assert race["dtstart"] == "2026-06-27T10:00:00Z"
        assert race["dtend"] == "2026-06-27T20:00:00Z"
        assert race["radius_km"] == 15.0

    def test_dtend_midnight_default_when_none(self):
        """Fehlt dtend → Mitternacht-UTC (Folgetag 00:00Z) als Default."""
        conn = _make_conn()
        rid = create_bummel_race(
            conn, name="X", route="EDWF",
            dtstart="2026-06-27T10:00:00Z", dtend=None,
        )
        assert get_bummel_race(conn, rid)["dtend"] == "2026-06-28T00:00:00Z"

    def test_default_radius_km_is_10(self):
        conn = _make_conn()
        rid = create_bummel_race(
            conn, name="X", route="EDWF",
            dtstart="2026-06-27T10:00:00Z", dtend=None,
        )
        assert get_bummel_race(conn, rid)["radius_km"] == 10.0

    def test_returns_unique_ids(self):
        conn = _make_conn()
        rid1 = _race(conn, name="A", dtstart="2026-06-27T10:00:00Z")
        rid2 = _race(conn, name="B", dtstart="2026-06-28T10:00:00Z")
        assert rid1 != rid2

    def test_appears_in_list(self):
        conn = _make_conn()
        rid = _race(conn, name="ListTest")
        names = [r["name"] for r in list_bummel_races(conn)]
        assert "ListTest" in names

    def test_created_at_set(self):
        conn = _make_conn()
        rid = _race(conn)
        assert get_bummel_race(conn, rid)["created_at"] is not None


class TestUpdateBummelRace:
    def test_update_name(self):
        conn = _make_conn()
        rid = _race(conn, name="Alt")
        update_bummel_race(conn, rid, name="Neu")
        assert get_bummel_race(conn, rid)["name"] == "Neu"

    def test_update_route(self):
        conn = _make_conn()
        rid = _race(conn, route="EDWF,EDWG")
        update_bummel_race(conn, rid, route="EDWF,EDWG,EDWR")
        assert get_bummel_race(conn, rid)["route"] == "EDWF,EDWG,EDWR"

    def test_update_radius_km(self):
        conn = _make_conn()
        rid = _race(conn)
        update_bummel_race(conn, rid, radius_km=20.0)
        assert get_bummel_race(conn, rid)["radius_km"] == 20.0

    def test_update_dtstart_resolves_dtend_to_midnight(self):
        """Wenn nur dtstart geändert wird (ohne dtend), wird dtend via _effective_dtend
        neu als Mitternacht des neuen dtstart aufgelöst."""
        conn = _make_conn()
        rid = _race(conn,
                    dtstart="2026-06-27T10:00:00Z",
                    dtend="2026-06-27T22:00:00Z")
        update_bummel_race(conn, rid, dtstart="2026-06-28T10:00:00Z")
        race = get_bummel_race(conn, rid)
        assert race["dtstart"] == "2026-06-28T10:00:00Z"
        assert race["dtend"] == "2026-06-29T00:00:00Z"

    def test_update_dtend_explicit(self):
        """Wenn dtend explizit übergeben wird, wird es gesetzt (kein Mitternacht-Default)."""
        conn = _make_conn()
        rid = _race(conn, dtstart="2026-06-27T10:00:00Z", dtend=None)
        update_bummel_race(conn, rid, dtend="2026-06-27T23:00:00Z")
        assert get_bummel_race(conn, rid)["dtend"] == "2026-06-27T23:00:00Z"

    def test_unknown_fields_ignored(self):
        conn = _make_conn()
        rid = _race(conn, name="X")
        # Kein Fehler, Felder bleiben unverändert
        update_bummel_race(conn, rid, nonexistent="boom", revealed_at="x")
        assert get_bummel_race(conn, rid)["name"] == "X"

    def test_no_op_when_no_valid_fields(self):
        conn = _make_conn()
        rid = _race(conn, name="Y")
        update_bummel_race(conn, rid)  # leere Felder → kein UPDATE
        assert get_bummel_race(conn, rid)["name"] == "Y"


class TestDeleteBummelRace:
    def test_delete_removes_race(self):
        conn = _make_conn()
        rid = _race(conn)
        delete_bummel_race(conn, rid)
        assert get_bummel_race(conn, rid) is None
        assert list_bummel_races(conn) == []

    def test_delete_removes_associated_overrides(self):
        conn = _make_conn()
        rid = _race(conn)
        upsert_bummel_override(conn, rid, 100, "exclude")
        upsert_bummel_override(conn, rid, 200, "disqualify")
        delete_bummel_race(conn, rid)
        assert get_bummel_race(conn, rid) is None
        assert list_bummel_overrides(conn, rid) == []

    def test_delete_only_affects_target_race(self):
        conn = _make_conn()
        rid1 = _race(conn, name="A")
        rid2 = _race(conn, name="B")
        upsert_bummel_override(conn, rid1, 100, "exclude")
        upsert_bummel_override(conn, rid2, 200, "exclude")
        delete_bummel_race(conn, rid1)
        assert get_bummel_race(conn, rid2) is not None
        assert len(list_bummel_overrides(conn, rid2)) == 1


# ---------------------------------------------------------------------------
# Aufgabe 3 — bummel_overrides CRUD
# ---------------------------------------------------------------------------

class TestBummelOverridesCrud:
    def test_upsert_and_list(self):
        conn = _make_conn()
        rid = _race(conn)
        upsert_bummel_override(conn, rid, 100, "exclude")
        overrides = list_bummel_overrides(conn, rid)
        assert len(overrides) == 1
        assert overrides[0]["cid"] == 100
        assert overrides[0]["action"] == "exclude"

    def test_upsert_updates_existing_entry(self):
        conn = _make_conn()
        rid = _race(conn)
        upsert_bummel_override(conn, rid, 100, "exclude")
        upsert_bummel_override(conn, rid, 100, "disqualify", note="Regelverstoß")
        overrides = list_bummel_overrides(conn, rid)
        assert len(overrides) == 1  # kein Duplikat
        assert overrides[0]["action"] == "disqualify"
        assert overrides[0]["note"] == "Regelverstoß"

    def test_upsert_manual_total_min(self):
        conn = _make_conn()
        rid = _race(conn)
        upsert_bummel_override(conn, rid, 100, "manual", manual_total_min=75, note="Manuell")
        ov = list_bummel_overrides(conn, rid)[0]
        assert ov["manual_total_min"] == 75
        assert ov["note"] == "Manuell"

    def test_list_empty_for_unknown_race(self):
        conn = _make_conn()
        assert list_bummel_overrides(conn, 9999) == []

    def test_list_only_for_given_race(self):
        conn = _make_conn()
        rid1 = _race(conn, name="A")
        rid2 = _race(conn, name="B")
        upsert_bummel_override(conn, rid1, 100, "exclude")
        upsert_bummel_override(conn, rid2, 200, "winner")
        assert len(list_bummel_overrides(conn, rid1)) == 1
        assert list_bummel_overrides(conn, rid1)[0]["cid"] == 100

    def test_delete_override(self):
        conn = _make_conn()
        rid = _race(conn)
        upsert_bummel_override(conn, rid, 100, "exclude")
        upsert_bummel_override(conn, rid, 200, "winner")
        delete_bummel_override(conn, rid, 100)
        overrides = list_bummel_overrides(conn, rid)
        assert len(overrides) == 1
        assert overrides[0]["cid"] == 200

    def test_updated_at_set_on_upsert(self):
        conn = _make_conn()
        rid = _race(conn)
        upsert_bummel_override(conn, rid, 100, "exclude")
        assert list_bummel_overrides(conn, rid)[0]["updated_at"] is not None


# ---------------------------------------------------------------------------
# Aufgabe 4 — apply_bummel_overrides (reine Funktion)
# ---------------------------------------------------------------------------

def _mk_standings(**kwargs) -> dict:
    """Minimales standings-Dict für Tests."""
    defaults = {
        "route": ["EDWF", "EDWG", "EDWR"],
        "complete": [],
        "incomplete": [],
        "average_min": 0.0,
        "count": 0,
        "participant_count": 0,
    }
    defaults.update(kwargs)
    return defaults


def _entry(cid: int, total_min: int, *, name: str = "P", rank: int | None = None,
           delta: float | None = None, visited: list | None = None,
           missing: list | None = None) -> dict:
    e: dict = {
        "cid": cid,
        "name": name,
        "callsign": f"FRS{cid}",
        "aircraft": "C172",
        "total_min": total_min,
        "visited": visited or ["EDWF", "EDWG", "EDWR"],
        "missing": missing or [],
        "leg_count": 2,
        "legs": [],
    }
    if rank is not None:
        e["rank"] = rank
    if delta is not None:
        e["delta"] = delta
    return e


def _ov(cid: int, action: str, manual_total_min: int | None = None, note: str | None = None) -> dict:
    return {"race_id": 1, "cid": cid, "action": action,
            "manual_total_min": manual_total_min, "note": note, "updated_at": "2026-06-27T10:00:00Z"}


class TestApplyBummelOverridesOriginalUnchanged:
    def test_deep_copy_original_not_mutated(self):
        standings = _mk_standings(
            complete=[_entry(100, 60, rank=1, delta=0.0)],
            average_min=60.0, count=1, participant_count=1,
        )
        original = copy.deepcopy(standings)
        apply_bummel_overrides(standings, [_ov(100, "exclude")])
        assert standings == original  # Original unverändert


class TestApplyBummelOverridesExclude:
    def test_exclude_removes_from_complete(self):
        standings = _mk_standings(
            complete=[_entry(100, 80, rank=1, delta=0.0), _entry(200, 60, rank=2, delta=20.0)],
            average_min=70.0, count=2, participant_count=2,
        )
        result = apply_bummel_overrides(standings, [_ov(100, "exclude")])
        cids = [e["cid"] for e in result["complete"]]
        assert 100 not in cids
        assert 200 in cids

    def test_exclude_removes_from_incomplete(self):
        standings = _mk_standings(
            complete=[_entry(200, 80, rank=1, delta=0.0)],
            incomplete=[_entry(300, 40, visited=["EDWF"], missing=["EDWG", "EDWR"])],
            average_min=80.0, count=1, participant_count=2,
        )
        result = apply_bummel_overrides(standings, [_ov(300, "exclude")])
        assert len(result["incomplete"]) == 0

    def test_exclude_recalculates_average(self):
        """Nach Exclude wird der Schnitt über die verbleibenden complete neu berechnet."""
        # 60 + 80 + 100 → Avg 80; exclude 100 → 60+80=140, avg=70
        standings = _mk_standings(
            complete=[
                _entry(100, 60, rank=1, delta=20.0),
                _entry(200, 80, rank=2, delta=0.0),
                _entry(300, 100, rank=3, delta=20.0),
            ],
            average_min=80.0, count=3, participant_count=3,
        )
        result = apply_bummel_overrides(standings, [_ov(300, "exclude")])
        assert result["average_min"] == 70.0
        assert result["count"] == 2

    def test_exclude_reassigns_ranks(self):
        standings = _mk_standings(
            complete=[
                _entry(100, 80, rank=1, delta=0.0),
                _entry(200, 70, rank=2, delta=10.0),
                _entry(300, 90, rank=3, delta=10.0),
            ],
            average_min=80.0, count=3, participant_count=3,
        )
        result = apply_bummel_overrides(standings, [_ov(100, "exclude")])
        ranks = sorted(e["rank"] for e in result["complete"])
        assert ranks == [1, 2]
        assert result["count"] == 2

    def test_exclude_all_complete_gives_zero_average(self):
        standings = _mk_standings(
            complete=[_entry(100, 60, rank=1, delta=0.0)],
            average_min=60.0, count=1, participant_count=1,
        )
        result = apply_bummel_overrides(standings, [_ov(100, "exclude")])
        assert result["average_min"] == 0.0
        assert result["count"] == 0


class TestApplyBummelOverridesDisqualify:
    def test_disqualify_moves_to_disqualified(self):
        standings = _mk_standings(
            complete=[_entry(100, 60, rank=1, delta=0.0), _entry(200, 80, rank=2, delta=20.0)],
            average_min=70.0, count=2, participant_count=2,
        )
        result = apply_bummel_overrides(standings, [_ov(100, "disqualify")])
        assert "disqualified" in result
        dq_cids = [e["cid"] for e in result["disqualified"]]
        complete_cids = [e["cid"] for e in result["complete"]]
        assert 100 in dq_cids
        assert 100 not in complete_cids

    def test_disqualify_not_counted_in_average(self):
        # 100 min und 60 min; disqualify 100 → avg = 60
        standings = _mk_standings(
            complete=[_entry(100, 100, rank=1, delta=20.0), _entry(200, 60, rank=2, delta=20.0)],
            average_min=80.0, count=2, participant_count=2,
        )
        result = apply_bummel_overrides(standings, [_ov(100, "disqualify")])
        assert result["average_min"] == 60.0
        assert result["count"] == 1

    def test_disqualified_counted_in_participant_count(self):
        """Disqualifizierte waren Teilnehmer → participant_count zählt sie mit."""
        standings = _mk_standings(
            complete=[_entry(100, 60, rank=1, delta=0.0), _entry(200, 80, rank=2, delta=20.0)],
            incomplete=[_entry(300, 40, visited=["EDWF"], missing=["EDWG", "EDWR"])],
            average_min=70.0, count=2, participant_count=3,
        )
        result = apply_bummel_overrides(standings, [_ov(100, "disqualify")])
        # complete: [200], incomplete: [300], disqualified: [100] → 3 distinct cids
        assert result["participant_count"] == 3


class TestApplyBummelOverridesManual:
    def test_manual_moves_from_incomplete_to_complete(self):
        standings = _mk_standings(
            complete=[_entry(200, 80, rank=1, delta=0.0)],
            incomplete=[_entry(100, 40, visited=["EDWF", "EDWG"], missing=["EDWR"])],
            average_min=80.0, count=1, participant_count=2,
        )
        result = apply_bummel_overrides(standings, [_ov(100, "manual", manual_total_min=75)])
        complete_cids = [e["cid"] for e in result["complete"]]
        incomplete_cids = [e["cid"] for e in result["incomplete"]]
        assert 100 in complete_cids
        assert 100 not in incomplete_cids

    def test_manual_sets_total_min(self):
        standings = _mk_standings(
            complete=[_entry(200, 80, rank=1, delta=0.0)],
            incomplete=[_entry(100, 40, visited=["EDWF"], missing=["EDWG", "EDWR"])],
            average_min=80.0, count=1, participant_count=2,
        )
        result = apply_bummel_overrides(standings, [_ov(100, "manual", manual_total_min=75)])
        entry = next(e for e in result["complete"] if e["cid"] == 100)
        assert entry["total_min"] == 75

    def test_manual_recalculates_average(self):
        # 200: 80 min; 100 manual: 75 min → avg = round((80+75)/2, 1) = 77.5
        standings = _mk_standings(
            complete=[_entry(200, 80, rank=1, delta=0.0)],
            incomplete=[_entry(100, 40, visited=["EDWF"], missing=["EDWG", "EDWR"])],
            average_min=80.0, count=1, participant_count=2,
        )
        result = apply_bummel_overrides(standings, [_ov(100, "manual", manual_total_min=75)])
        assert result["average_min"] == 77.5
        assert result["count"] == 2

    def test_manual_updates_existing_complete_entry(self):
        """Manual kann auch einen schon-complete Eintrag korrigieren."""
        standings = _mk_standings(
            complete=[_entry(100, 60, rank=1, delta=0.0)],
            average_min=60.0, count=1, participant_count=1,
        )
        result = apply_bummel_overrides(standings, [_ov(100, "manual", manual_total_min=90)])
        entry = next(e for e in result["complete"] if e["cid"] == 100)
        assert entry["total_min"] == 90

    def test_manual_unknown_cid_skipped_no_stub(self):
        """CID nicht in standings → kein Stub, kein Fehler."""
        standings = _mk_standings(
            complete=[_entry(200, 80, rank=1, delta=0.0)],
            average_min=80.0, count=1, participant_count=1,
        )
        result = apply_bummel_overrides(standings, [_ov(999, "manual", manual_total_min=75)])
        assert result["count"] == 1
        assert 999 not in [e["cid"] for e in result["complete"]]

    def test_manual_without_total_min_is_noop(self):
        """manual ohne manual_total_min → kein Fehler, kein Effekt."""
        standings = _mk_standings(
            complete=[_entry(200, 80, rank=1, delta=0.0)],
            average_min=80.0, count=1, participant_count=1,
        )
        result = apply_bummel_overrides(standings, [_ov(200, "manual", manual_total_min=None)])
        assert result["count"] == 1


class TestApplyBummelOverridesWinner:
    def test_winner_forced_to_rank_1(self):
        """CID, der nach Berechnung nicht rank=1 hätte, wird durch winner-Override erzwungen."""
        # 100: total=80, 200: total=200 → avg=(80+200)/2=140
        # delta(100)=60, delta(200)=60; sort by (60,80,100) < (60,200,200) → 100 rank=1, 200 rank=2
        # winner=200 → 200 wird rank=1
        standings = _mk_standings(
            complete=[_entry(100, 80, rank=1, delta=0.0), _entry(200, 200, rank=2, delta=0.0)],
            average_min=80.0, count=2, participant_count=2,
        )
        result = apply_bummel_overrides(standings, [_ov(200, "winner")])
        assert result["complete"][0]["cid"] == 200
        assert result["complete"][0]["rank"] == 1
        assert result["complete"][0].get("forced_winner") is True
        assert result["complete"][1]["cid"] == 100
        assert result["complete"][1]["rank"] == 2

    def test_winner_not_in_complete_is_noop(self):
        """Wenn winner-CID nicht in complete → kein Fehler, kein Effekt."""
        standings = _mk_standings(
            complete=[_entry(100, 80, rank=1, delta=0.0)],
            average_min=80.0, count=1, participant_count=1,
        )
        result = apply_bummel_overrides(standings, [_ov(999, "winner")])
        assert result["complete"][0]["cid"] == 100

    def test_winner_already_at_rank_1_gets_forced_winner_flag(self):
        """Auch wenn winner schon rank=1 ist, wird forced_winner=True gesetzt."""
        standings = _mk_standings(
            complete=[_entry(100, 80, rank=1, delta=0.0)],
            average_min=80.0, count=1, participant_count=1,
        )
        result = apply_bummel_overrides(standings, [_ov(100, "winner")])
        assert result["complete"][0].get("forced_winner") is True


class TestApplyBummelOverridesEdgeCases:
    def test_empty_overrides_returns_valid_result_with_disqualified_list(self):
        standings = _mk_standings(
            complete=[_entry(100, 60, rank=1, delta=0.0)],
            average_min=60.0, count=1, participant_count=1,
        )
        result = apply_bummel_overrides(standings, [])
        assert result["count"] == 1
        assert result["average_min"] == 60.0
        assert "disqualified" in result
        assert result["disqualified"] == []

    def test_empty_standings_empty_overrides(self):
        standings = _mk_standings()
        result = apply_bummel_overrides(standings, [])
        assert result["count"] == 0
        assert result["average_min"] == 0.0
        assert result["disqualified"] == []

    def test_participant_count_recalculated_correctly(self):
        """participant_count = distinct cids in complete+incomplete+disqualified."""
        standings = _mk_standings(
            complete=[_entry(100, 60, rank=1, delta=0.0), _entry(200, 80, rank=2, delta=20.0)],
            incomplete=[_entry(300, 30, visited=["EDWF"], missing=["EDWG", "EDWR"])],
            average_min=70.0, count=2, participant_count=3,
        )
        # exclude 300, disqualify 100 → complete:[200], incomplete:[], disqualified:[100]
        result = apply_bummel_overrides(
            standings,
            [_ov(300, "exclude"), _ov(100, "disqualify")],
        )
        assert result["participant_count"] == 2  # distinct: {200, 100}


# ---------------------------------------------------------------------------
# bummel_races_due_for_reminder (Task 4, #24) -- manuelle 1h-Erinnerung, push_enabled-gated
# ---------------------------------------------------------------------------

def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestBummelRacesDueForReminder:
    def test_manual_race_due_then_dedup_after_mark(self):
        conn = _make_conn()
        now = datetime.now(timezone.utc)
        rid = _race(conn, name="Sommer-Bummel", dtstart=_iso(now + timedelta(minutes=30)))
        conn.commit()

        due = bummel_races_due_for_reminder(conn, _iso(now), lead_min=60)
        assert [r["id"] for r in due] == [rid]

        mark_event_reminded(conn, f"bummel:{rid}", _iso(now))
        conn.commit()
        assert bummel_races_due_for_reminder(conn, _iso(now), lead_min=60) == []

    def test_push_disabled_excluded(self):
        conn = _make_conn()
        now = datetime.now(timezone.utc)
        rid = _race(conn, dtstart=_iso(now + timedelta(minutes=30)))
        set_bummel_push_enabled(conn, rid, False)
        conn.commit()
        assert bummel_races_due_for_reminder(conn, _iso(now), lead_min=60) == []

    def test_outside_window_excluded(self):
        conn = _make_conn()
        now = datetime.now(timezone.utc)
        _race(conn, dtstart=_iso(now + timedelta(minutes=90)))  # außerhalb 60-min-Fenster
        assert bummel_races_due_for_reminder(conn, _iso(now), lead_min=60) == []
