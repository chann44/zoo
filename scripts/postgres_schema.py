"""Prints the Postgres schema matching the SQLite one that db/migrations builds, for a new file in db/postgres.

    uv run python scripts/postgres_schema.py > db/postgres/<timestamp>_<name>.sql

It was used once for the baseline. Later schema changes get a migration in both directories, written by hand, and
the test suite run against Postgres (ZOO_TEST_DATABASE_URL, see docs/development.md) checks that they agree.

The translation keeps what the queries see the same on both databases:
  - timestamps stay TEXT in SQLite's CURRENT_TIMESTAMP format, which zoo_now() returns (db/connection.py rewrites
    CURRENT_TIMESTAMP to it), so they compare and sort as strings everywhere;
  - integers are BIGINT and REAL is DOUBLE PRECISION;
  - every table gets zoo_rowid, which queries ordering by SQLite's rowid use instead.
"""

import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NOW = """CREATE FUNCTION zoo_now() RETURNS TEXT LANGUAGE sql STABLE AS $$
    SELECT to_char(statement_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
$$;"""


def sqlite_schema() -> sqlite3.Connection:
    path = Path(tempfile.mkdtemp()) / "schema.db"
    subprocess.run(
        ["goose", "-dir", str(ROOT / "db" / "migrations"), "sqlite3", str(path), "up"], check=True, capture_output=True
    )
    return sqlite3.connect(path)


def translate_table(sql: str) -> str:
    sql = re.sub(r'^CREATE TABLE "?(\w+)"?\s*\(', r"CREATE TABLE \1 (\n    zoo_rowid BIGSERIAL,", sql)
    sql = re.sub(r"\b(DATETIME|TIMESTAMP)\b", "TEXT", sql)
    sql = re.sub(r"\bINTEGER\b", "BIGINT", sql)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql)
    sql = sql.replace("DEFAULT CURRENT_TIMESTAMP", "DEFAULT zoo_now()")
    # columns added by ALTER TABLE end up on the closing line: one per line, like the rest
    sql = re.sub(r"\n?, (?=\w+ (TEXT|BIGINT|DOUBLE))", ",\n    ", sql)
    sql = sql.strip().rstrip(";")
    return re.sub(r"(?<!\n)\)$", "\n)", sql) + ";"


def references(sql: str) -> set[str]:
    return set(re.findall(r"REFERENCES\s+\"?(\w+)\"?", sql))


def main():
    conn = sqlite_schema()
    tables = {
        name: sql
        for name, sql in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "AND name != 'goose_db_version' ORDER BY rowid"
        )
    }
    indexes = [
        sql
        for (sql,) in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL ORDER BY rowid"
        )
    ]
    # foreign keys need the table they name to exist first
    ordered: list[str] = []
    while len(ordered) < len(tables):
        ready = [n for n in tables if n not in ordered and references(tables[n]) - {n} <= set(ordered)]
        if not ready:
            raise SystemExit(f"circular foreign keys among {sorted(set(tables) - set(ordered))}")
        ordered += ready
    out = ["-- +goose Up", "-- +goose StatementBegin", NOW, "-- +goose StatementEnd", ""]
    out += [translate_table(tables[n]) + "\n" for n in ordered]
    out += [re.sub(r'"(\w+)"', r"\1", sql).strip().rstrip(";") + ";" for sql in indexes]
    out += ["", "-- +goose Down"]
    out += [f"DROP TABLE IF EXISTS {n} CASCADE;" for n in reversed(ordered)]
    out += ["DROP FUNCTION IF EXISTS zoo_now();", ""]
    sys.stdout.write("\n".join(out))


if __name__ == "__main__":
    main()
