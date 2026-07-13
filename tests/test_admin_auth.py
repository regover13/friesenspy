"""Tests für die Admin-Authentifizierung (signiertes Cookie via SECRET_KEY)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as main
from app.auth import (
    ADMIN_COOKIE,
    CONFIRM_COOKIE,
    check_password,
    make_admin_token,
    make_confirm_token,
    verify_admin_token,
    verify_confirm_token,
)


class FakeReq:
    def __init__(self, cookies=None, body=None, headers=None, scheme="http", ip="1.2.3.4"):
        self.cookies = cookies or {}
        self._body = body or {}
        self.headers = headers or {}
        self.url = SimpleNamespace(scheme=scheme)
        self.client = SimpleNamespace(host=ip)

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


class TestConfirmTokenCrypto:
    NOW = 1_000_000

    def test_roundtrip(self):
        tok = make_confirm_token("secret", "pw", self.NOW + 600)
        assert verify_confirm_token(tok, "secret", "pw", self.NOW) is True

    def test_expired_fails(self):
        tok = make_confirm_token("secret", "pw", self.NOW - 1)
        assert verify_confirm_token(tok, "secret", "pw", self.NOW) is False

    def test_wrong_password_fails(self):
        tok = make_confirm_token("secret", "pw", self.NOW + 600)
        assert verify_confirm_token(tok, "secret", "anders", self.NOW) is False

    def test_wrong_secret_fails(self):
        tok = make_confirm_token("secret", "pw", self.NOW + 600)
        assert verify_confirm_token(tok, "other", "pw", self.NOW) is False

    def test_tampered_expiry_fails(self):
        # Ablaufzeit im Klartext hochsetzen, Signatur bleibt alt → ungültig.
        tok = make_confirm_token("secret", "pw", self.NOW + 10)
        _, _, sig = tok.partition(".")
        forged = f"{self.NOW + 99999}.{sig}"
        assert verify_confirm_token(forged, "secret", "pw", self.NOW) is False

    def test_empty_password_never_verifies(self):
        tok = make_confirm_token("secret", "", self.NOW + 600)
        assert verify_confirm_token(tok, "secret", "", self.NOW) is False

    def test_garbage_token_fails(self):
        assert verify_confirm_token("", "secret", "pw", self.NOW) is False
        assert verify_confirm_token("nodot", "secret", "pw", self.NOW) is False
        assert verify_confirm_token("abc.def", "secret", "pw", self.NOW) is False


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


class TestRequireConfirm:
    def _admin_cookie(self):
        return make_admin_token("s3cr3t", "test-admin-pw")

    def test_valid_confirm_cookie_passes(self, monkeypatch):
        _patch(monkeypatch)
        import time as _t
        tok = make_confirm_token("s3cr3t", "test-admin-pw", int(_t.time()) + 600)
        main.require_confirm(FakeReq(cookies={CONFIRM_COOKIE: tok}))  # kein Raise

    def test_missing_confirm_cookie_403(self, monkeypatch):
        _patch(monkeypatch)
        with pytest.raises(HTTPException) as e:
            main.require_confirm(FakeReq(cookies={ADMIN_COOKIE: self._admin_cookie()}))
        assert e.value.status_code == 403
        assert e.value.detail == "confirm_required"

    def test_expired_confirm_cookie_403(self, monkeypatch):
        _patch(monkeypatch)
        import time as _t
        tok = make_confirm_token("s3cr3t", "test-admin-pw", int(_t.time()) - 5)
        with pytest.raises(HTTPException) as e:
            main.require_confirm(FakeReq(cookies={CONFIRM_COOKIE: tok}))
        assert e.value.status_code == 403


class TestConfirmEndpoint:
    def test_confirm_sets_cookie(self, monkeypatch):
        _patch(monkeypatch)
        tok = make_admin_token("s3cr3t", "test-admin-pw")
        resp = asyncio.run(main.admin_confirm(FakeReq(
            cookies={ADMIN_COOKIE: tok}, body={"password": "test-admin-pw"}, ip="t-cf-ok",
        )))
        cookie = resp.headers.get("set-cookie", "")
        assert CONFIRM_COOKIE in cookie
        # Das gesetzte Confirm-Cookie validiert anschließend gegen require_confirm.
        import re, time as _t
        m = re.search(r"fs_confirm=([^;]+)", cookie)
        assert m and verify_confirm_token(m.group(1), "s3cr3t", "test-admin-pw", int(_t.time()))

    def test_confirm_wrong_password_401(self, monkeypatch):
        _patch(monkeypatch)
        tok = make_admin_token("s3cr3t", "test-admin-pw")
        with pytest.raises(HTTPException) as e:
            asyncio.run(main.admin_confirm(FakeReq(
                cookies={ADMIN_COOKIE: tok}, body={"password": "falsch"}, ip="t-cf-wrong",
            )))
        assert e.value.status_code == 401

    def test_confirm_requires_admin_login(self, monkeypatch):
        _patch(monkeypatch)
        with pytest.raises(HTTPException) as e:
            asyncio.run(main.admin_confirm(FakeReq(body={"password": "test-admin-pw"}, ip="t-cf-noadm")))
        assert e.value.status_code == 401


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
            asyncio.run(main.admin_login(FakeReq(body={"password": "falsch"}, ip="t-wrong")))
        assert e.value.status_code == 401

    def test_secure_cookie_behind_https(self, monkeypatch):
        _patch(monkeypatch)
        resp = asyncio.run(main.admin_login(FakeReq(
            body={"password": "test-admin-pw"}, headers={"x-forwarded-proto": "https"}, ip="t-https",
        )))
        cookie = resp.headers.get("set-cookie", "").lower()
        assert "secure" in cookie and "path=/api/admin" in cookie

    def test_login_rate_limited_after_failures(self, monkeypatch):
        _patch(monkeypatch)
        main._login_fails.pop("t-rl", None)
        for _ in range(5):
            with pytest.raises(HTTPException) as e:
                asyncio.run(main.admin_login(FakeReq(body={"password": "x"}, ip="t-rl")))
            assert e.value.status_code == 401
        # 6. Versuch ist gebremst → 429 (auch mit korrektem Passwort)
        with pytest.raises(HTTPException) as e:
            asyncio.run(main.admin_login(FakeReq(body={"password": "test-admin-pw"}, ip="t-rl")))
        assert e.value.status_code == 429
