"""accounts and transfers

Every user gets a "General" account that inherits their old
users.opening_balance; every existing expense and income is attached to it.

Revision ID: 4004c26c965e
Revises: 05abbea478d2
Create Date: 2026-09-10 19:08:51.446693

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '4004c26c965e'
down_revision: Union[str, Sequence[str], None] = '05abbea478d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GENERAL = "General"


def upgrade() -> None:
    op.create_table('accounts',
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('subtype', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
    sa.Column('opening_balance', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('type', sa.Enum('debit', 'cash', 'other', name='account_type'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name', name='uq_accounts_user_name')
    )
    op.create_index(op.f('ix_accounts_user_id'), 'accounts', ['user_id'], unique=False)
    op.create_table('transfers',
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('from_account_id', sa.Integer(), nullable=False),
    sa.Column('to_account_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['from_account_id'], ['accounts.id'], ),
    sa.ForeignKeyConstraint(['to_account_id'], ['accounts.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transfers_from_account_id'), 'transfers', ['from_account_id'], unique=False)
    op.create_index(op.f('ix_transfers_to_account_id'), 'transfers', ['to_account_id'], unique=False)
    op.create_index(op.f('ix_transfers_user_id'), 'transfers', ['user_id'], unique=False)

    # Data: one General account per existing user, carrying their opening balance.
    op.execute(sa.text(
        "INSERT INTO accounts (name, type, subtype, opening_balance, user_id) "
        f"SELECT '{GENERAL}', 'debit', NULL, opening_balance, id FROM users"
    ))

    # Nullable first so existing rows can be backfilled, then tightened.
    for table in ("expenses", "incomes"):
        op.add_column(table, sa.Column('account_id', sa.Integer(), nullable=True))
        op.execute(sa.text(
            f"UPDATE {table} SET account_id = accounts.id FROM accounts "
            f"WHERE accounts.user_id = {table}.user_id AND accounts.name = '{GENERAL}'"
        ))
        op.alter_column(table, 'account_id', nullable=False)
        op.create_index(op.f(f'ix_{table}_account_id'), table, ['account_id'], unique=False)
        op.create_foreign_key(f'{table}_account_id_fkey', table, 'accounts', ['account_id'], ['id'])

    op.drop_column('users', 'opening_balance')


def downgrade() -> None:
    op.add_column('users', sa.Column('opening_balance', sa.NUMERIC(precision=12, scale=2), nullable=False, server_default='0'))
    op.execute(sa.text(
        "UPDATE users SET opening_balance = accounts.opening_balance FROM accounts "
        f"WHERE accounts.user_id = users.id AND accounts.name = '{GENERAL}'"
    ))
    op.alter_column('users', 'opening_balance', server_default=None)
    for table in ("incomes", "expenses"):
        op.drop_constraint(f'{table}_account_id_fkey', table, type_='foreignkey')
        op.drop_index(op.f(f'ix_{table}_account_id'), table_name=table)
        op.drop_column(table, 'account_id')
    op.drop_index(op.f('ix_transfers_user_id'), table_name='transfers')
    op.drop_index(op.f('ix_transfers_to_account_id'), table_name='transfers')
    op.drop_index(op.f('ix_transfers_from_account_id'), table_name='transfers')
    op.drop_table('transfers')
    op.drop_index(op.f('ix_accounts_user_id'), table_name='accounts')
    op.drop_table('accounts')
    sa.Enum(name='account_type').drop(op.get_bind(), checkfirst=True)
