"""default account flag

Marks each user's fallback account with a flag instead of relying on its
name, so renaming it (everyone renames it to their real bank) keeps
account-less expenses and incomes working.

Revision ID: cdf791184e60
Revises: e890c56b0580
Create Date: 2026-09-19 09:01:39.341383

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'cdf791184e60'
down_revision: Union[str, Sequence[str], None] = 'e890c56b0580'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Added with a default so existing rows are valid, then backfilled: the
    # oldest account of each user is the one registration seeded.
    op.add_column("accounts", sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(sa.text(
        "UPDATE accounts SET is_default = true "
        "WHERE id IN (SELECT MIN(id) FROM accounts GROUP BY user_id)"
    ))
    op.alter_column("accounts", "is_default", server_default=None)


def downgrade() -> None:
    op.drop_column("accounts", "is_default")
