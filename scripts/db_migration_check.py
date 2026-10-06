"""Test migrations on a copy of the real data before they touch the real database.

  uv run python scripts/db_migration_check.py              # refresh copy, test pending migrations
  uv run python scripts/db_migration_check.py --steps 2    # nothing pending: re-test the last 2
  uv run python scripts/db_migration_check.py --no-fresh   # reuse the current copy

All work happens on two throwaway databases on the same Postgres server:
  <db>_restore_check   a full copy of the real data (scripts/db_backup.py)
  <db>_migration_ref   built from an empty database by migrations alone:
                       what the schema SHOULD look like at each revision

Steps:
  0. Refresh the copy: backup + verified restore of the real database.
  1. Pick the range: from the copy's current revision to head; if nothing
     is pending, from --steps revisions below head.
  2. On the copy: [downgrade to start] -> upgrade -> downgrade -> upgrade.
  3. Fail if any step fails; if a downgrade or upgrade doesn't end in the
     schema it must (state before, minus what the migrations remove, plus
     what they add on the reference); if the round trip doesn't return to
     the same schema; or if the round trip loses rows.
     Row-count changes made by the migration itself are listed for the PR.
     Drift the copy already had before (objects created by hand, outside
     migrations) is reported as a note, so it doesn't fail every future run.

The real database is only read (to refresh the copy). The copy ends at head.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import db_backup  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402

COPY_DB = settings.postgres_db_name + db_backup.RESTORE_SUFFIX
REF_DB = settings.postgres_db_name + "_migration_ref"
EXCLUDE = "('pg_catalog','information_schema')"
failures: list[str] = []


def dsn(db: str) -> str:
    return settings.pg_dsn.rsplit("/", 1)[0] + f"/{db}"


def alembic(db: str, *args: str) -> None:
    """Run Alembic against `db` in a subprocess, so settings (read once at
    import) point at that database and never at the real one."""
    if db not in (COPY_DB, REF_DB):
        raise SystemExit(f"refusing to run migrations against {db!r}")
    env = {**os.environ, "POSTGRES_DB_NAME": db}
    r = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True
    )
    if r.returncode != 0:
        tail = "\n      ".join((r.stderr or r.stdout).strip().splitlines()[-6:])
        raise SystemExit(f"FAILED: alembic {' '.join(args)} on {db}:\n      {tail}")


def recreate(db: str) -> None:
    eng = create_engine(dsn("postgres"), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{db}"'))
    eng.dispose()


def snapshot(db: str) -> tuple[set, dict]:
    """(schema facts, row count per table). Schema facts are comparable
    strings; generated names are kept because migrations rely on them."""
    eng = create_engine(dsn(db))
    try:
        with eng.connect() as c:
            q = lambda s: [tuple(r) for r in c.execute(text(s))]  # noqa: E731
            facts = set()
            for t, col, typ, nn, dflt in q(f"""
                select c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                       pg_get_expr(d.adbin, d.adrelid)
                from pg_attribute a join pg_class c on c.oid = a.attrelid
                join pg_namespace n on n.oid = c.relnamespace
                left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
                where n.nspname not in {EXCLUDE} and c.relkind in ('r','v','p')
                  and a.attnum > 0 and not a.attisdropped"""):
                facts.add(
                    f"column {t}.{col} {typ}{' NOT NULL' if nn else ''}{f' DEFAULT {dflt}' if dflt else ''}"
                )
            for (
                t,
                name,
                d,
            ) in q(f"""select conrelid::regclass::text, conname, pg_get_constraintdef(oid)
                from pg_constraint where conrelid <> 0
                and connamespace not in (select oid from pg_namespace where nspname in {EXCLUDE})"""):
                facts.add(f"constraint {t}.{name} {d}")
            for (d,) in q(f"select indexdef from pg_indexes where schemaname not in {EXCLUDE}"):
                facts.add(f"index {d}")
            for name, d in q(
                f"select table_name, view_definition from information_schema.views where table_schema not in {EXCLUDE}"
            ):
                facts.add(f"view {name} {' '.join(d.split())}")
            for (e,) in q("select extname from pg_extension"):
                facts.add(f"extension {e}")
            tables = [
                r[0]
                for r in q(f"select tablename from pg_tables where schemaname not in {EXCLUDE}")
            ]
            counts = {
                t: c.execute(text(f'select count(*) from "{t}"')).scalar()
                for t in tables
                if t != "alembic_version"
            }
            return facts, counts
    finally:
        eng.dispose()


def current_revision(db: str) -> str | None:
    eng = create_engine(dsn(db))
    try:
        with eng.connect() as c:
            return c.execute(text("select version_num from alembic_version")).scalar()
    finally:
        eng.dispose()


def expect_same(label: str, actual: set, expected: set) -> None:
    missing, extra = sorted(expected - actual), sorted(actual - expected)
    if not missing and not extra:
        print(f"   ok    {label}")
        return
    failures.append(label)
    print(f"   FAIL  {label}")
    for f in missing[:8]:
        print(f"           missing: {f[:150]}")
    for f in extra[:8]:
        print(f"           extra:   {f[:150]}")
    if len(missing) + len(extra) > 16:
        print(f"           ... {len(missing) + len(extra) - 16} more")


def count_changes(before: dict, after: dict) -> list[str]:
    return [
        f"{t}: {before.get(t, '-')} -> {after.get(t, '-')}"
        for t in sorted(set(before) | set(after))
        if before.get(t) != after.get(t)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--steps",
        type=int,
        default=1,
        help="if nothing is pending, re-test this many latest migrations",
    )
    parser.add_argument(
        "--no-fresh", action="store_true", help="reuse the current copy instead of refreshing it"
    )
    args = parser.parse_args()

    if not args.no_fresh:
        print("0. REFRESH the copy from the real database")
        db_backup.restore(db_backup.backup(settings.postgres_db_name), COPY_DB)
        db_backup.compare(settings.postgres_db_name, COPY_DB)

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    head = script.get_current_head()
    current = current_revision(COPY_DB)
    if current != head:
        start = current
    else:
        start = head
        for _ in range(args.steps):
            start = script.get_revision(start).down_revision
        if start is None:
            raise SystemExit("--steps goes below the first migration")
    chain = [r.revision for r in script.iterate_revisions(head, start)][::-1]
    print(f"1. RANGE  {start} -> {head}  ({len(chain)} migration(s): {', '.join(chain)})")

    print("2. REFERENCE  build an empty database with migrations only")
    recreate(REF_DB)
    alembic(REF_DB, "upgrade", start)
    ref_start, _ = snapshot(REF_DB)
    alembic(REF_DB, "upgrade", head)
    ref_head, _ = snapshot(REF_DB)

    # The copy may already differ from what migrations build (objects added
    # by hand). That pre-existing drift is reported, not failed. Each step is
    # checked by the state it must END in, derived from what the migrations
    # add/remove on the reference:
    #   after upgrade   = (before - removed) | added
    #   after downgrade = (before - added)   | removed
    # This also accepts migrations that create objects only if missing
    # (no change on a database that already has them).
    added, removed = ref_head - ref_start, ref_start - ref_head

    print(f"3. CYCLE on {COPY_DB}")
    initial, initial_counts = snapshot(COPY_DB)
    if current == head:
        alembic(COPY_DB, "downgrade", start)
        down1, counts_down1 = snapshot(COPY_DB)
        expect_same(
            f"downgrade to {start}: ends in the expected schema", down1, (initial - added) | removed
        )
    else:
        down1, counts_down1 = initial, initial_counts
    alembic(COPY_DB, "upgrade", head)
    up1, counts_up1 = snapshot(COPY_DB)
    expect_same(
        f"upgrade to {head}: ends in the expected schema ({len(added)} added, {len(removed)} removed on a fresh database)",
        up1,
        (down1 - removed) | added,
    )
    alembic(COPY_DB, "downgrade", start)
    down2, _ = snapshot(COPY_DB)
    expect_same(
        f"downgrade to {start} again: ends in the expected schema", down2, (up1 - added) | removed
    )
    alembic(COPY_DB, "upgrade", head)
    up2, counts_up2 = snapshot(COPY_DB)
    expect_same("second upgrade returns to the same schema", up2, up1)

    print("4. DATA")
    made = count_changes(counts_down1, counts_up1)
    print(
        "   changed by the migration(s): " + ("; ".join(made) if made else "no row counts changed")
    )
    lost = (
        count_changes(initial_counts, counts_up2)
        if current == head
        else count_changes(counts_up1, counts_up2)
    )
    if lost:
        failures.append("round trip changed row counts")
        print("   FAIL  round trip changed row counts: " + "; ".join(lost))
    else:
        print("   ok    round trip kept every row")

    drift = sorted(up2 - ref_head), sorted(ref_head - up2)
    if drift[0] or drift[1]:
        print(
            f"   note  pre-existing drift: the database has {len(drift[0])} schema fact(s) no migration "
            f"creates and lacks {len(drift[1])} that migrations create:"
        )
        for f in drift[0][:10]:
            print(f"           not from migrations: {f[:140]}")
        for f in drift[1][:10]:
            print(f"           missing:             {f[:140]}")

    if failures:
        raise SystemExit(f"FAILED: {len(failures)} check(s): " + "; ".join(failures))
    print("OK: migrations upgrade, downgrade and upgrade again cleanly on a copy of the real data.")


if __name__ == "__main__":
    main()
