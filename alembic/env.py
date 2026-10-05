from logging.config import fileConfig

from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401 - registers all models onto Base.metadata
from alembic import context
from app.core.config import settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.pg_dsn.replace("%", "%%"))

# Now that models exist, autogenerate is available for future migrations:
#   alembic revision --autogenerate -m "describe the change"
# Always review the generated diff before committing it.
target_metadata = Base.metadata


def process_revision_directives(context, revision, directives) -> None:
    """Gives new migrations a sequential id (0033, 0034, ...) so files are
    named NNNN_<slug>.py and sort in apply order. Existing revisions keep
    their original ids -- only their file names were renumbered."""
    if not directives:
        return
    revision_count = len(list(ScriptDirectory.from_config(config).walk_revisions()))
    directives[0].rev_id = f"{revision_count + 1:04d}"


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        process_revision_directives=process_revision_directives,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            process_revision_directives=process_revision_directives,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()