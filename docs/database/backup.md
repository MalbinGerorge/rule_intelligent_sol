# Backup and restore

## Take a backup (and prove it restores)

```powershell
uv run python scripts/db_backup.py
```

1. **Backup:** `pg_dump` (schema **and** data) runs inside the `rule_intelligent_postgres` container and writes `backups/<database>_<timestamp>.dump`.
2. **Restore:** the file is restored into a separate throwaway database, `<database>_restore_check`, recreated on every run.
3. **Compare:** tables, views, extensions, constraints, indexes, the Alembic version and every table's row count must match the original. Any difference fails the run (exit code 1).

The source database is only read. `backups/` is git-ignored: backups contain real customer data and must never be committed. The script refuses to write anywhere git doesn't ignore.

Run it **before every schema migration** on a database that holds data you care about (see the checklist in [design.md](design.md) §7).

`--no-verify` skips steps 2–3 (backup only).

## Restore a backup into the real database

Only when you mean to replace the current data. Take a fresh backup of the current state first.

```powershell
uv run python scripts/db_backup.py --no-verify      # safety copy of the current state
cmd /c "docker exec -i rule_intelligent_postgres pg_restore -U postgres --clean --if-exists --no-owner -d rule_intelligent_sol < backups\<file>.dump"
uv run alembic current                               # confirm the schema version you restored
```

Stop the API and Celery worker while restoring, then restart them.

## The `_restore_check` database

`rule_intelligent_sol_restore_check` is a complete copy of the data from the last verified backup. Phase 1b of the database redesign uses it to test every new migration (upgrade, downgrade, upgrade again) before it touches the real database. It's safe to drop at any time; the next backup run recreates it.

## Test a migration before it touches the real database

```powershell
uv run python scripts/db_migration_check.py              # refresh the copy, test pending migrations
uv run python scripts/db_migration_check.py --steps 2    # nothing pending: re-test the last 2
```

1. Refreshes `_restore_check` from the real database (backup + verified restore).
2. Builds `<database>_migration_ref` from an empty database with migrations only: what the schema *should* look like.
3. On the copy: (downgrade →) upgrade → downgrade → upgrade.
4. Fails if a step fails, if a step changes the copy's schema differently from how it changes the reference, if the round trip doesn't return to the same schema, or if the round trip loses rows. Row-count changes made by the migration itself are listed.

Drift the database already had (objects created outside migrations) is printed as a note instead of failing, so it doesn't block every future migration. Only after this passes is `alembic upgrade head` run against the real database.
