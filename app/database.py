import logging
import time
from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, create_engine, text

from app.config import settings

logger = logging.getLogger(__name__)

# pool_pre_ping: test a pooled connection before reusing it, so a Postgres
# restart (docker compose down/up) costs one reconnect, not a 500.
engine = create_engine(settings.database_url, pool_pre_ping=True)


def wait_for_db(timeout_seconds: float = settings.db_startup_timeout_seconds) -> None:
    """Block until Postgres answers a real query, or raise.

    A container reporting "started" is not the same as Postgres accepting
    connections, so this probes with SELECT 1 and backs off between
    attempts instead of sleeping for a fixed guess.
    """
    deadline = time.monotonic() + timeout_seconds
    delay = 0.5
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Database not reachable after {timeout_seconds:.0f}s"
                ) from exc
            logger.warning("Database not ready (%s); retrying in %.1fs", exc.__class__.__name__, delay)
            time.sleep(delay)
            delay = min(delay * 2, 5.0)


def alembic_config(database_url: str = settings.database_url) -> Config:
    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    # "%" is the ConfigParser escape character; a password can contain one.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def run_migrations() -> None:
    """Bring the database to the latest revision. Replaces create_all():
    migrations can add a column to a table that already exists."""
    command.upgrade(alembic_config(), "head")


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
