"""Tests für das Admin-CLI manage_ts_consent.py."""
from __future__ import annotations

import pytest

from app.database import init_db, get_connection, get_ts_consent
from manage_ts_consent import main


def test_set_then_get(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    init_db(db)
    rc = main(["--db", db, "set", "FRS135", "allowlist", "--allow", "FRS2", "FRS7"])
    assert rc == 0
    conn = get_connection(db)
    row = get_ts_consent(conn, "FRS135")
    conn.close()
    assert row["visibility"] == "allowlist"
    assert row["allowlist"] == ["FRS2", "FRS7"]


def test_set_nobody(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    assert main(["--db", db, "set", "FRS135", "nobody"]) == 0
    conn = get_connection(db)
    assert get_ts_consent(conn, "FRS135")["visibility"] == "nobody"
    conn.close()


def test_invalid_visibility_rejected(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    with pytest.raises(SystemExit):
        main(["--db", db, "set", "FRS135", "bogus"])


def test_delete(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    main(["--db", db, "set", "FRS135", "nobody"])
    assert main(["--db", db, "delete", "FRS135"]) == 0
    conn = get_connection(db)
    assert get_ts_consent(conn, "FRS135") is None
    conn.close()


def test_list_runs(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    init_db(db)
    main(["--db", db, "set", "FRS1", "everyone"])
    assert main(["--db", db, "list"]) == 0
    assert "FRS1" in capsys.readouterr().out
