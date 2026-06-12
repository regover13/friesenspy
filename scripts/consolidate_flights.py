#!/usr/bin/env python3
"""Einmaliger, reversibler Cleanup der flights-Tabelle.

Markiert exakte Duplikate (gleiche cid+logon_time) sowie überzählige offene Flüge
als `superseded_by` und korrigiert Zombie-Logoffs (gedeckelt + StatSim-Backstop).
Dieselbe Logik läuft auch idempotent beim App-Start (init_db). Dieses Skript ist
für manuelle Läufe, einen Trockenlauf-Report und die lokale Verifikation gedacht.

Verwendung:
    python -m scripts.consolidate_flights [DB_PATH] [--dry-run]

Rückgängig machen (reversibel):
    UPDATE flights SET superseded_by = NULL;
"""
from __future__ import annotations

import sys

from app.config import get_settings
from app.database import consolidate_flights, get_connection


def _report(conn) -> dict:
    active_open = conn.execute(
        "SELECT COUNT(*) FROM flights WHERE logoff_time IS NULL AND superseded_by IS NULL"
    ).fetchone()[0]
    superseded = conn.execute(
        "SELECT COUNT(*) FROM flights WHERE superseded_by IS NOT NULL"
    ).fetchone()[0]
    active_dupes = conn.execute(
        "SELECT COUNT(*) FROM (SELECT cid, logon_time FROM flights "
        "WHERE superseded_by IS NULL GROUP BY cid, logon_time HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    return {"active_open": active_open, "superseded": superseded, "active_dupes": active_dupes}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    dry_run = "--dry-run" in argv
    db_path = args[0] if args else get_settings().DB_PATH

    conn = get_connection(db_path)
    try:
        # Spalten sicherstellen (auf roher Prod-DB evtl. noch nicht vorhanden).
        for ddl in (
            "ALTER TABLE flights ADD COLUMN superseded_by INTEGER",
            "ALTER TABLE flights ADD COLUMN block_min INTEGER",
        ):
            try:
                conn.execute(ddl)
                conn.commit()
            except Exception:
                pass

        before = _report(conn)
        print(f"DB: {db_path}")
        print(f"VORHER : offen(aktiv)={before['active_open']}  "
              f"superseded={before['superseded']}  aktive_Dubletten={before['active_dupes']}")

        if dry_run:
            # Trockenlauf in einer Transaktion, die wir zurückrollen.
            conn.execute("BEGIN")
            marked = consolidate_flights(conn)
            after = _report(conn)
            conn.rollback()
            print(f"[DRY-RUN] würde {marked} Zeilen als superseded markieren")
            print(f"[DRY-RUN] NACHHER: offen(aktiv)={after['active_open']}  "
                  f"superseded={after['superseded']}  aktive_Dubletten={after['active_dupes']}")
            print("[DRY-RUN] Änderungen verworfen (rollback).")
            return 0

        marked = consolidate_flights(conn)
        conn.commit()
        after = _report(conn)
        print(f"{marked} Zeilen als superseded markiert.")
        print(f"NACHHER: offen(aktiv)={after['active_open']}  "
              f"superseded={after['superseded']}  aktive_Dubletten={after['active_dupes']}")
        if after["active_dupes"] != 0:
            print("WARNUNG: es verbleiben aktive Dubletten — partieller Unique-Index "
                  "kann nicht angelegt werden!", file=sys.stderr)
            return 1
        # Partiellen Unique-Index neu anlegen (consolidate_flights droppt ihn am Anfang).
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_flights_session "
            "ON flights(cid, logon_time) WHERE superseded_by IS NULL"
        )
        conn.commit()
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
