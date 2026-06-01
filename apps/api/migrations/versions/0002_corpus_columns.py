from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("coverage", JSONB(), nullable=True))
    op.add_column("reviews", sa.Column("parent_review_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("reviews", "parent_review_id")
    op.drop_column("reviews", "coverage")
