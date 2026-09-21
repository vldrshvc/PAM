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
from app.routers.receipts import rates_dependency, vision_dependency


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
        self.images: list[tuple[bytes, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 30) -> str:
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return self.answer

    def read_image(
        self, system: str, user: str, image: bytes, media_type: str, max_tokens: int | None = None
    ) -> str:
        self.images.append((image, media_type))
        return self.complete(system, user, max_tokens or 0)


@pytest.fixture
def fake_llm(client: TestClient) -> FakeLLM:
    fake = FakeLLM()
    app.dependency_overrides[llm_dependency] = lambda: fake
    return fake


# The ECB's own file, trimmed to three working days and a handful of
# currencies. Friday 18th, then a weekend with nothing published.
ECB_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <gesmes:Sender><gesmes:name>European Central Bank</gesmes:name></gesmes:Sender>
  <Cube>
    <Cube time="2026-09-18">
      <Cube currency="USD" rate="1.1742"/>
      <Cube currency="GBP" rate="0.86530"/>
      <Cube currency="RON" rate="5.0755"/>
      <Cube currency="PLN" rate="4.2480"/>
    </Cube>
    <Cube time="2026-09-17">
      <Cube currency="USD" rate="1.1710"/>
      <Cube currency="RON" rate="5.0740"/>
    </Cube>
    <Cube time="2026-09-16">
      <Cube currency="USD" rate="1.1688"/>
      <Cube currency="GBP" rate="0.86610"/>
      <Cube currency="RON" rate="5.0722"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


# The NBU answers one date at a time; this is the shape of one answer.
NBU_JSON = b'[{"r030":978,"txt":"\xd0\x84\xd0\xb2\xd1\x80\xd0\xbe","rate":48.5031,"cc":"EUR","exchangedate":"18.09.2026"}]'


@pytest.fixture
def rates():
    """The real chain, with both banks' files served from memory."""
    import httpx

    from app.services.fx import Chain, EcbRates, parse_rates

    class StubHryvnia:
        def rate_on(self, currency, on):
            from app.services.fx import UAH, CurrencyNotPublishedError, parse_nbu

            if currency.upper() != UAH:
                raise CurrencyNotPublishedError(f"{currency.upper()} is not published by the NBU")
            return parse_nbu(NBU_JSON, on)

    from app.routers.notifications import rates_dependency as notification_rates

    chain = Chain((EcbRates(parse_rates(ECB_XML)), StubHryvnia()))
    app.dependency_overrides[rates_dependency] = lambda: chain
    app.dependency_overrides[notification_rates] = lambda: chain
    return chain


@pytest.fixture
def fake_vision(client: TestClient, rates: dict) -> FakeLLM:
    fake = FakeLLM()
    app.dependency_overrides[vision_dependency] = lambda: fake
    return fake


@pytest.fixture
def unavailable_llm(fake_llm: FakeLLM) -> FakeLLM:
    fake_llm.error = LLMUnavailableError("LLM provider timed out")
    return fake_llm
