#!/usr/bin/env python3
"""Admin-CLI für die ts_consent-Tabelle (FriesenSpy Phase 1).

Seedet/zeigt Einwilligungen ohne Hand-SQL. Kein Web-UI (spec-konform).

Beispiele:
  python manage_ts_consent.py set FRS135 nobody
  python manage_ts_consent.py set FRS135 allowlist --allow FRS2 FRS7
  python manage_ts_consent.py get FRS135
  python manage_ts_consent.py list
  python manage_ts_consent.py delete FRS135
"""
from __future__ import annotations

import argparse
import sys

from app.config import get_settings
from app.database import get_connection, get_ts_consent, upsert_ts_consent

_VISIBILITIES = ("everyone", "nobody", "allowlist")


def _db_path(args: argparse.Namespace) -> str:
    return args.db or get_settings().DB_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ts_consent verwalten")
    parser.add_argument("--db", default=None, help="DB-Pfad (Default: Settings.DB_PATH)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_set = sub.add_parser("set", help="Einwilligung setzen")
    p_set.add_argument("frs")
    p_set.add_argument("visibility", choices=_VISIBILITIES)
    p_set.add_argument("--allow", nargs="*", default=None,
                       help="Empfänger-FRS für visibility=allowlist")

    p_get = sub.add_parser("get", help="Einwilligung einer FRS anzeigen")
    p_get.add_argument("frs")

    sub.add_parser("list", help="Alle Einträge anzeigen")

    p_del = sub.add_parser("delete", help="Eintrag löschen (= zurück auf Default 'everyone')")
    p_del.add_argument("frs")

    args = parser.parse_args(argv)
    conn = get_connection(_db_path(args))
    try:
        if args.cmd == "set":
            allow = args.allow if args.visibility == "allowlist" else None
            upsert_ts_consent(conn, args.frs, args.visibility, allow)
            conn.commit()
            print(f"OK: {args.frs} → {args.visibility}"
                  + (f" {allow}" if allow else ""))
        elif args.cmd == "get":
            row = get_ts_consent(conn, args.frs)
            print(row if row else f"{args.frs}: kein Eintrag (Default 'everyone')")
        elif args.cmd == "list":
            rows = conn.execute(
                "SELECT frs, visibility, allowlist, updated_at FROM ts_consent ORDER BY frs"
            ).fetchall()
            if not rows:
                print("(leer)")
            for r in rows:
                print(f"{r['frs']:>10}  {r['visibility']:<10}  {r['allowlist'] or ''}")
        elif args.cmd == "delete":
            conn.execute("DELETE FROM ts_consent WHERE frs = ?", (args.frs,))
            conn.commit()
            print(f"OK: {args.frs} gelöscht (gilt jetzt als 'everyone')")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
