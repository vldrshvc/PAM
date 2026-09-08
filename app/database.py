import logging
import time
from collections.abc import Generator

from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, text

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url)


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


def create_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
