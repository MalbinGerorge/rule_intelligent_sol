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
