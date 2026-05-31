from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False, server_default="pending"),
        sa.Column("summary", sa.String(), nullable=False, server_default=""),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("findings", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_table("reviews")
