"""Mark background jobs stuck at 'running' as failed.

  uv run python scripts/fail_stale_jobs.py                  # dry run: only lists them
  uv run python scripts/fail_stale_jobs.py --apply          # marks them failed
  uv run python scripts/fail_stale_jobs.py --older-than-days 2

See app/services/stale_jobs.py for why jobs get stuck and how "stale" is
decided. Take a backup first (scripts/db_backup.py) before --apply.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import engine  # noqa: E402
from app.services.stale_jobs import (  # noqa: E402
    DEFAULT_OLDER_THAN,
    fail_stale_jobs,
    find_stale_jobs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="mark the jobs failed (default: dry run)"
    )
    parser.add_argument(
        "--older-than-days",
        type=float,
        default=DEFAULT_OLDER_THAN.days,
        help=f"running for longer than this counts as stale (default {DEFAULT_OLDER_THAN.days})",
    )
    args = parser.parse_args()
    older_than = timedelta(days=args.older_than_days)

    jobs = (
        fail_stale_jobs(engine, older_than) if args.apply else find_stale_jobs(engine, older_than)
    )
    for job in jobs:
        print(f"  {job.table} id={job.id} running since {job.created_at}")
    if not jobs:
        print(f"No jobs running for more than {older_than}.")
    elif args.apply:
        print(f"Marked {len(jobs)} job(s) failed.")
    else:
        print(f"{len(jobs)} job(s) would be marked failed. Re-run with --apply to do it.")


if __name__ == "__main__":
    main()
