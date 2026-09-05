"""add single-user account login"""

import sqlalchemy as sa
from alembic import op

revision = "b14c7f2d8a01"
down_revision = "c72c5d7c6c05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_account_username"),
    )


def downgrade() -> None:
    op.drop_table("account")
