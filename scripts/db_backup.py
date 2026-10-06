"""Back up the database and prove the backup can be restored.

  uv run python scripts/db_backup.py               # backup + restore check (recommended)
  uv run python scripts/db_backup.py --no-verify   # backup only

Steps:
  1. BACKUP   pg_dump (custom format: schema AND data) runs inside the
              Postgres container and is saved to backups/<db>_<timestamp>.dump
  2. RESTORE  the file is restored into a separate, throwaway database
              (<db>_restore_check), recreated from scratch every run
  3. COMPARE  tables, views, extensions, constraints, indexes, the Alembic
              version and the exact row count of every table must match
              the original; any difference fails the run (exit code 1)

The source database is only read, never changed. Backups contain real
customer data, so the script refuses to write them anywhere git doesn't
ignore.

Restore a backup into the real database only deliberately, e.g.:
  docker exec -i rule_intelligent_postgres pg_restore -U postgres \
      --clean --if-exists --no-owner -d rule_intelligent_sol < backups/<file>.dump
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402

BACKUP_DIR = ROOT / "backups"
CONTAINER = os.environ.get("POSTGRES_CONTAINER", "rule_intelligent_postgres")
RESTORE_SUFFIX = "_restore_check"


def fail(message: str) -> None:
    print(f"FAILED: {message}")
    sys.exit(1)


def docker(*args: str, stdin=None, stdout=None) -> subprocess.CompletedProcess:
    """Run a command inside the Postgres container. The container's local
    socket is trusted, so no password is passed on any command line."""
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, *args],
        stdin=stdin,
        stdout=stdout if stdout is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        fail(f"{' '.join(args[:2])}: {result.stderr.decode(errors='replace').strip()[:500]}")
    return result


def ensure_ignored(path: Path) -> None:
    probe = subprocess.run(
        ["git", "check-ignore", "-q", str(path.relative_to(ROOT) / "probe.dump")], cwd=ROOT
    )
    if probe.returncode != 0:
        fail(f"{path} is not git-ignored; refusing to write a backup with real data there")


def backup(db_name: str) -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    ensure_ignored(BACKUP_DIR)
    target = BACKUP_DIR / f"{db_name}_{datetime.now():%Y%m%d_%H%M%S}.dump"
    with open(target, "wb") as out:
        docker("pg_dump", "-U", settings.postgres_username, "-d", db_name, "-Fc", stdout=out)
    if target.stat().st_size == 0:
        fail(f"{target.name} is empty")
    print(f"1. BACKUP   {target.relative_to(ROOT)}  ({target.stat().st_size / 1_000_000:.1f} MB)")
    return target


def restore(dump: Path, restore_db: str) -> None:
    if not restore_db.endswith(RESTORE_SUFFIX) or restore_db == settings.postgres_db_name:
        fail(f"refusing to restore into {restore_db!r}")
    user = settings.postgres_username
    docker(
        "psql",
        "-U",
        user,
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        f'DROP DATABASE IF EXISTS "{restore_db}" WITH (FORCE)',
        "-c",
        f'CREATE DATABASE "{restore_db}"',
    )
    with open(dump, "rb") as src:
        docker(
            "pg_restore", "-U", user, "-d", restore_db, "--no-owner", "--exit-on-error", stdin=src
        )
    print(f"2. RESTORE  into {restore_db}")


def snapshot(db_name: str) -> dict:
    """Everything that must be identical between original and restore."""
    dsn = settings.pg_dsn.rsplit("/", 1)[0] + f"/{db_name}"
    engine = create_engine(dsn)
    try:
        with engine.connect() as c:
            rows = lambda q: [tuple(r) for r in c.execute(text(q))]  # noqa: E731
            tables = [
                r[0]
                for r in rows(
                    "select tablename from pg_tables where schemaname not in ('pg_catalog','information_schema') order by 1"
                )
            ]
            return {
                "tables": tables,
                "views": rows(
                    "select table_schema, table_name from information_schema.views "
                    "where table_schema not in ('pg_catalog','information_schema') order by 1, 2"
                ),
                "extensions": rows("select extname from pg_extension order by 1"),
                "constraints": rows(
                    "select conrelid::regclass::text, conname, contype from pg_constraint "
                    "where connamespace not in ('pg_catalog'::regnamespace, 'information_schema'::regnamespace) "
                    "and conrelid <> 0 order by 1, 2"
                ),
                "indexes": rows(
                    "select tablename, indexname from pg_indexes "
                    "where schemaname not in ('pg_catalog','information_schema') order by 1, 2"
                ),
                "alembic_version": rows("select version_num from alembic_version")
                if "alembic_version" in tables
                else [],
                "row_counts": {
                    t: c.execute(text(f'select count(*) from "{t}"')).scalar() for t in tables
                },
            }
    finally:
        engine.dispose()


def compare(source_db: str, restore_db: str) -> None:
    original, restored = snapshot(source_db), snapshot(restore_db)
    problems = [k for k in original if original[k] != restored[k]]
    for key in problems:
        if key == "row_counts":
            for t, n in original[key].items():
                if restored[key].get(t) != n:
                    print(f"   row count differs: {t}: {n} vs {restored[key].get(t)}")
        else:
            print(f"   {key} differ")
    total_rows = sum(original["row_counts"].values())
    print(
        f"3. COMPARE  {len(original['tables'])} tables, {len(original['views'])} views, "
        f"{len(original['constraints'])} constraints, {len(original['indexes'])} indexes, "
        f"{total_rows:,} rows, alembic {original['alembic_version'][0][0] if original['alembic_version'] else '-'}"
    )
    if problems:
        fail(f"restored database differs from the original in: {', '.join(problems)}")
    print("OK: the backup restores to an identical database.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-verify", action="store_true", help="only create the backup")
    args = parser.parse_args()

    source_db = settings.postgres_db_name
    if source_db.endswith(RESTORE_SUFFIX):
        fail("the configured database is itself a restore check database")
    dump = backup(source_db)
    if args.no_verify:
        return
    restore_db = source_db + RESTORE_SUFFIX
    restore(dump, restore_db)
    compare(source_db, restore_db)


if __name__ == "__main__":
    main()
