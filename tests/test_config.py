"""Tests for app/config.py — Settings, CID parsing, defaults, env overrides."""
from __future__ import annotations

import importlib
import os
import sys

import pytest


def _make_settings(**env_overrides: str):
    """Instantiate a fresh Settings object with the given env vars set."""
    # Patch environment, reload module to bust lru_cache, restore afterwards
    original = {k: os.environ.get(k) for k in env_overrides}
    # Ensure SECRET_KEY is always present unless overridden
    if "SECRET_KEY" not in env_overrides:
        env_overrides.setdefault("SECRET_KEY", "test-secret")

    for k, v in env_overrides.items():
        os.environ[k] = v

    # Re-import Settings directly to avoid cached singleton
    if "app.config" in sys.modules:
        importlib.reload(sys.modules["app.config"])
    from app.config import Settings  # noqa: PLC0415

    # Build without reading config.env so tests are hermetic
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    # Restore env
    for k, orig in original.items():
        if orig is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = orig

    return settings


class TestCIDParsing:
    def test_single_cid(self):
        s = _make_settings(FRIESENFLIEGER_CIDS="1234567")
        assert s.cids == [1234567]

    def test_multiple_cids(self):
        s = _make_settings(FRIESENFLIEGER_CIDS="1234567,8901234")
        assert s.cids == [1234567, 8901234]

    def test_cids_with_spaces(self):
        s = _make_settings(FRIESENFLIEGER_CIDS=" 1234567 , 8901234 ")
        assert s.cids == [1234567, 8901234]

    def test_empty_cids(self):
        s = _make_settings(FRIESENFLIEGER_CIDS="")
        assert s.cids == []

    def test_cids_not_set_defaults_to_empty(self):
        # Make sure FRIESENFLIEGER_CIDS is absent from env
        os.environ.pop("FRIESENFLIEGER_CIDS", None)
        os.environ["SECRET_KEY"] = "test-secret"
        if "app.config" in sys.modules:
            importlib.reload(sys.modules["app.config"])
        from app.config import Settings  # noqa: PLC0415

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.cids == []


class TestDefaults:
    def test_poll_interval_default(self):
        s = _make_settings()
        assert s.VATSIM_POLL_INTERVAL == 15

    def test_db_path_default(self):
        s = _make_settings()
        assert s.DB_PATH == "/opt/friesenspy/data/friesenspy.db"

    def test_telegram_defaults_empty(self):
        s = _make_settings()
        assert s.TELEGRAM_BOT_TOKEN == ""
        assert s.TELEGRAM_CHAT_ID == ""


class TestEnvOverride:
    def test_poll_interval_override(self):
        s = _make_settings(VATSIM_POLL_INTERVAL="30")
        assert s.VATSIM_POLL_INTERVAL == 30

    def test_db_path_override(self):
        s = _make_settings(DB_PATH="/tmp/test.db")
        assert s.DB_PATH == "/tmp/test.db"

    def test_telegram_override(self):
        s = _make_settings(TELEGRAM_BOT_TOKEN="tok123", TELEGRAM_CHAT_ID="chat456")
        assert s.TELEGRAM_BOT_TOKEN == "tok123"
        assert s.TELEGRAM_CHAT_ID == "chat456"

    def test_secret_key_override(self):
        s = _make_settings(SECRET_KEY="my-super-secret")
        assert s.SECRET_KEY == "my-super-secret"


class TestGetSettings:
    def test_singleton_returns_same_instance(self):
        # Reload to get a fresh lru_cache
        if "app.config" in sys.modules:
            importlib.reload(sys.modules["app.config"])
        os.environ.setdefault("SECRET_KEY", "test-secret")
        from app.config import get_settings  # noqa: PLC0415

        a = get_settings()
        b = get_settings()
        assert a is b

    def test_get_settings_returns_settings_instance(self):
        if "app.config" in sys.modules:
            importlib.reload(sys.modules["app.config"])
        os.environ.setdefault("SECRET_KEY", "test-secret")
        from app.config import get_settings, Settings  # noqa: PLC0415

        assert isinstance(get_settings(), Settings)
