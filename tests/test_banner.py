"""Tests für die Banner-Verwaltung (Admin-Endpoints + frontend-config-Auflösung)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.main as main
from app.auth import ADMIN_COOKIE, CONFIRM_COOKIE, make_admin_token, make_confirm_token
from app.database import init_db

SECRET = "s3cr3t"
PW = "test-admin-pw"
TOKEN = make_admin_token(SECRET, PW)
CONFIRM_TOKEN = make_confirm_token(SECRET, PW, 9_999_999_999)


class FakeReq:
    def __init__(self, cookies=None, body=None):
        self.cookies = cookies if cookies is not None else {
            ADMIN_COOKIE: TOKEN, CONFIRM_COOKIE: CONFIRM_TOKEN,
        }
        self._body = body or {}

    async def json(self):
        return self._body


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    monkeypatch.setattr(
        main, "get_settings",
        lambda: SimpleNamespace(
            DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD=PW,
            OPENAIP_API_KEY="", CARTO_API_KEY="", VAPID_PUBLIC_KEY="",
        ),
    )
    return p


def _first_highlight_version():
    for e in main.CHANGELOG:
        if e.get("highlight"):
            return e["version"]
    return main.CHANGELOG[0]["version"]


def test_requires_admin(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.admin_get_banner(FakeReq(cookies={})))
    assert e.value.status_code == 401


def test_get_banner_lists_entries_default_auto(db):
    res = asyncio.run(main.admin_get_banner(FakeReq()))
    assert res["selected"] == "auto"
    assert any(e["version"] == main.CHANGELOG[0]["version"] for e in res["entries"])


def test_frontend_config_auto_resolves_to_newest_highlight(db):
    cfg = asyncio.run(main.frontend_config())
    assert cfg["banner_version"] == _first_highlight_version()


def test_set_banner_off_hides(db):
    asyncio.run(main.admin_set_banner(FakeReq(body={"version": "off"})))
    cfg = asyncio.run(main.frontend_config())
    assert cfg["banner_version"] is None


def test_set_banner_specific_version(db):
    target = main.CHANGELOG[0]["version"]
    asyncio.run(main.admin_set_banner(FakeReq(body={"version": target})))
    cfg = asyncio.run(main.frontend_config())
    assert cfg["banner_version"] == target


def test_set_banner_unknown_version_resolves_none(db):
    asyncio.run(main.admin_set_banner(FakeReq(body={"version": "99.99.99"})))
    cfg = asyncio.run(main.frontend_config())
    assert cfg["banner_version"] is None
