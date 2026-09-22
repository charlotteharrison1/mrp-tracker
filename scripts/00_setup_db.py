"""
Create (or re-create) the SQLite database from schema.sql.

Usage:
    python scripts/00_setup_db.py [--reset]

--reset drops the existing db file first. Without it, this is safe to
re-run — CREATE TABLE/VIEW statements all use IF NOT EXISTS.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"
SCHEMA_PATH = ROOT / "schema.sql"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete the existing db file first")
    args = parser.parse_args()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if args.reset and DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Deleted existing db at {DB_PATH}")

    schema_sql = SCHEMA_PATH.read_text()
    con = sqlite3.connect(DB_PATH)
    try:
        con.executescript(schema_sql)
        con.commit()
        print(f"Database ready at {DB_PATH}")

        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        print(f"Tables created ({len(tables)}): {', '.join(tables)}")
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
