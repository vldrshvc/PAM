"""Migrations must produce exactly the schema the models describe.

Runs every revision against an empty database, then asks Alembic's
autogenerate whether it would emit anything. An empty diff means models and
migrations agree; a non-empty one means someone changed a model without
writing a migration (or the reverse).
"""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
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


def test_baseline_is_a_noop_on_a_create_all_database(engine):
    """A database that predates migrations keeps its tables and data."""
    url = engine.url.render_as_string(hide_password=False)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        conn.execute(text("INSERT INTO users (username, hashed_password, opening_balance) VALUES ('keep', 'x', 0)"))
    try:
        command.upgrade(alembic_config(url), "head")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM users WHERE username = 'keep'")).scalar() == 1
            assert conn.execute(text("SELECT count(*) FROM alembic_version")).scalar() == 1
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
