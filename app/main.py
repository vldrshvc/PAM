from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from app.database import create_tables, engine, wait_for_db
from app.routers import categories, expenses, health
from app.services.categories import seed_default_categories


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    wait_for_db()
    create_tables()
    with Session(engine) as session:
        seed_default_categories(session)
    yield


app = FastAPI(
    title="Personal Finance Tracker",
    description="Self-hosted expense tracker with LLM categorization and a daily summary for an Android widget.",
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(expenses.router)
app.include_router(categories.router)
