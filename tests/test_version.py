"""Tests für app/version.py + app/CHANGELOG.json (Datenintegrität)."""
from __future__ import annotations

from datetime import date

from app.version import CHANGELOG, VERSION, load_changelog


def _ver_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def test_version_matches_newest_entry():
    assert VERSION == CHANGELOG[0]["version"]


def test_load_changelog_matches_module_constant():
    assert load_changelog() == CHANGELOG


def test_changelog_not_empty():
    assert len(CHANGELOG) >= 1


def test_every_entry_well_formed():
    for e in CHANGELOG:
        assert set(e) >= {"version", "date", "title", "items"}
        assert isinstance(e["version"], str) and e["version"]
        assert isinstance(e["title"], str) and e["title"]
        assert isinstance(e["items"], list) and len(e["items"]) >= 1
        assert all(isinstance(it, str) and it for it in e["items"])


def test_dates_are_iso_parseable():
    for e in CHANGELOG:
        date.fromisoformat(e["date"])  # wirft bei ungültigem Datum


def test_versions_unique():
    versions = [e["version"] for e in CHANGELOG]
    assert len(versions) == len(set(versions))


def test_versions_sorted_newest_first():
    tuples = [_ver_tuple(e["version"]) for e in CHANGELOG]
    assert tuples == sorted(tuples, reverse=True)
