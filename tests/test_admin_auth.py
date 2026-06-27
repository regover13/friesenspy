"""Tests für die Admin-Authentifizierung (signiertes Cookie via SECRET_KEY)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as main
from app.auth import (
    ADMIN_COOKIE,
    check_password,
    make_admin_token,
    verify_admin_token,
)


class FakeReq:
    def __init__(self, cookies=None, body=None):
        self.cookies = cookies or {}
        self._body = body or {}

    async def json(self):
        return self._body


class TestTokenCrypto:
    def test_roundtrip(self):
        tok = make_admin_token("secret", "test-admin-pw")
        assert verify_admin_token(tok, "secret", "test-admin-pw") is True

    def test_wrong_password_fails(self):
        tok = make_admin_token("secret", "test-admin-pw")
        assert verify_admin_token(tok, "secret", "anders") is False

    def test_wrong_secret_fails(self):
        tok = make_admin_token("secret", "test-admin-pw")
        assert verify_admin_token(tok, "other-secret", "test-admin-pw") is False

    def test_empty_password_never_verifies(self):
        tok = make_admin_token("secret", "")
        assert verify_admin_token(tok, "secret", "") is False

    def test_check_password(self):
        assert check_password("test-admin-pw", "test-admin-pw") is True
        assert check_password("x", "test-admin-pw") is False
        assert check_password("", "") is False  # unkonfiguriert → nie erlaubt


def _patch(monkeypatch, password="test-admin-pw"):
    monkeypatch.setattr(
        main, "get_settings",
        lambda: SimpleNamespace(SECRET_KEY="s3cr3t", ADMIN_PASSWORD=password, DB_PATH=":memory:"),
    )


class TestRequireAdmin:
    def test_valid_cookie_passes(self, monkeypatch):
        _patch(monkeypatch)
        tok = make_admin_token("s3cr3t", "test-admin-pw")
        main.require_admin(FakeReq(cookies={ADMIN_COOKIE: tok}))  # kein Raise

    def test_missing_cookie_401(self, monkeypatch):
        _patch(monkeypatch)
        with pytest.raises(HTTPException) as e:
            main.require_admin(FakeReq())
        assert e.value.status_code == 401

    def test_unset_password_blocks(self, monkeypatch):
        _patch(monkeypatch, password="")
        tok = make_admin_token("s3cr3t", "")
        with pytest.raises(HTTPException):
            main.require_admin(FakeReq(cookies={ADMIN_COOKIE: tok}))


class TestLoginLogout:
    def test_login_sets_cookie(self, monkeypatch):
        _patch(monkeypatch)
        resp = asyncio.run(main.admin_login(FakeReq(body={"password": "test-admin-pw"})))
        cookie = resp.headers.get("set-cookie", "")
        assert ADMIN_COOKIE in cookie
        # Das gesetzte Cookie validiert anschließend
        tok = make_admin_token("s3cr3t", "test-admin-pw")
        assert tok in cookie

    def test_login_wrong_password_401(self, monkeypatch):
        _patch(monkeypatch)
        with pytest.raises(HTTPException) as e:
            asyncio.run(main.admin_login(FakeReq(body={"password": "falsch"})))
        assert e.value.status_code == 401
