from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import create_tables, wait_for_db
from app.routers import expenses, health


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    wait_for_db()
    create_tables()
    yield


app = FastAPI(
    title="Personal Finance Tracker",
    description="Self-hosted expense tracker with LLM categorization and a daily summary for an Android widget.",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(expenses.router)
