"""add status/error to investigation_reports for async job tracking

Revision ID: <generate via alembic revision, or ask me>
Revises: 3487bfa37cbd
Create Date: 2026-08-20

Supports the async investigation pattern: a row is created immediately
with status='running' (so the UI has an id to poll before any real
work happens), then updated in place to 'completed' or 'failed' once
the background task finishes. Confirmed via test: the runner's
try/except guarantees a terminal status is ALWAYS written, even on
failure -- a row can never be left stuck at 'running' forever.
"""
from alembic import op
import sqlalchemy as sa

revision = "202608201644"
down_revision = "3487bfa37cbd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("investigation_reports", sa.Column("status", sa.Text(), nullable=False, server_default="completed"))
    op.add_column("investigation_reports", sa.Column("error", sa.Text(), nullable=True))
    op.create_index("ix_investigation_reports_status", "investigation_reports", ["status"])


def downgrade() -> None:
    op.drop_index("ix_investigation_reports_status", table_name="investigation_reports")
    op.drop_column("investigation_reports", "error")
    op.drop_column("investigation_reports", "status")