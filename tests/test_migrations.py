"""Migrations must produce exactly the schema the models describe.

Runs every revision against an empty database, then asks Alembic's
autogenerate whether it would emit anything. An empty diff means models and
migrations agree; a non-empty one means someone changed a model without
writing a migration (or the reverse).
"""

from decimal import Decimal

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlmodel import SQLModel

from app.database import alembic_config


def test_migrations_match_models(engine):
    url = engine.url.render_as_string(hide_password=False)
    SQLModel.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    try:
        command.upgrade(alembic_config(url), "head")
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), SQLModel.metadata)
        assert diff == [], f"models and migrations differ: {diff}"
    finally:
        # Hand the other tests back the schema the way conftest built it.
        SQLModel.metadata.drop_all(engine)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        SQLModel.metadata.create_all(engine)


BASELINE = "05abbea478d2"


def test_accounts_migration_backfills_existing_data(engine):
    """Upgrading from the baseline gives every user a General account with
    their old opening balance and attaches their rows to it."""
    url = engine.url.render_as_string(hide_password=False)
    SQLModel.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    try:
        command.upgrade(alembic_config(url), BASELINE)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (username, hashed_password, opening_balance) VALUES ('vlad', 'x', 150), ('bob', 'x', -20.5)"))
            conn.execute(text("INSERT INTO categories (name, user_id) VALUES ('uncategorized', 1), ('uncategorized', 2)"))
            conn.execute(text("INSERT INTO expenses (price, date, user_id, category_id, status) VALUES (12.40, '2026-09-10', 1, 1, 'confirmed'), (5, '2026-09-10', 2, 2, 'confirmed')"))
            conn.execute(text("INSERT INTO incomes (amount, date, user_id, source) VALUES (500, '2026-09-10', 1, 'work')"))

        command.upgrade(alembic_config(url), "head")

        with engine.connect() as conn:
            accounts = conn.execute(text("SELECT user_id, name, type, opening_balance FROM accounts ORDER BY user_id")).all()
            assert [tuple(row) for row in accounts] == [(1, "General", "debit", Decimal("150.00")), (2, "General", "debit", Decimal("-20.50"))]
            assert conn.execute(text("SELECT count(*) FROM expenses WHERE account_id IS NULL")).scalar() == 0
            assert conn.execute(text("SELECT count(*) FROM incomes WHERE account_id IS NULL")).scalar() == 0
            assert conn.execute(text("SELECT account_id FROM expenses WHERE user_id = 2")).scalar() == 2
            assert "opening_balance" not in {c["name"] for c in inspect(conn).get_columns("users")}
    finally:
        SQLModel.metadata.drop_all(engine)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        SQLModel.metadata.create_all(engine)
