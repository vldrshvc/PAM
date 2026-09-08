"""Shared fixtures.

Tests run against a real PostgreSQL database named after the main one
with a "_test" suffix (or TEST_DATABASE_URL). It is created if missing,
tables are built once per session and truncated after every test. The
app's DB session and LLM client are swapped via FastAPI dependency
overrides, so the app code under test is exactly what runs in production.
"""

import os
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ProgrammingError
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.database import get_session
from app.llm import LLMUnavailableError
from app.main import app
from app.routers.categorize import llm_dependency


def _test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(settings.database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def _ensure_database_exists(test_url: str) -> None:
    url = make_url(test_url)
    admin = create_engine(
        url.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    except ProgrammingError as exc:
        raise pytest.UsageError(
            f"Could not create test database {url.database!r}: {exc.orig}. "
            f"Create it manually or set TEST_DATABASE_URL."
        ) from exc
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    test_url = _test_database_url()
    _ensure_database_exists(test_url)
    engine = create_engine(test_url)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _truncate_after_test(engine: Engine) -> Iterator[None]:
    yield
    tables = ", ".join(f'"{t.name}"' for t in SQLModel.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    def override_get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    # No `with`: the lifespan (wait_for_db + create_all on the main DB) must
    # not run; the test engine owns the schema.
    yield TestClient(app)
    app.dependency_overrides.clear()


AuthHeaders = dict[str, str]


@pytest.fixture
def auth(client: TestClient) -> Callable[..., AuthHeaders]:
    """Register a user and return bearer headers for them."""

    def _make(username: str = "vlad", password: str = "correct horse battery") -> AuthHeaders:
        response = client.post("/register", json={"username": username, "password": password})
        assert response.status_code == 201, response.text
        response = client.post("/token", data={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _make


class FakeLLM:
    """Stands in for LLMClient. Set .answer to script the model, or .error
    to make the call fail the way the real client would."""

    def __init__(self) -> None:
        self.answer = "uncategorized"
        self.error: Exception | None = None
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 30) -> str:
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return self.answer


@pytest.fixture
def fake_llm(client: TestClient) -> FakeLLM:
    fake = FakeLLM()
    app.dependency_overrides[llm_dependency] = lambda: fake
    return fake


@pytest.fixture
def unavailable_llm(fake_llm: FakeLLM) -> FakeLLM:
    fake_llm.error = LLMUnavailableError("LLM provider timed out")
    return fake_llm
