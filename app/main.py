import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.database import run_migrations, wait_for_db
from app.routers import account, auth, categories, categorize, expenses, health, incomes, summary


# Uvicorn configures only its own loggers; give the app's loggers a
# handler so lines like the per-call LLM record reach the server log.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    wait_for_db()
    run_migrations()
    yield


app = FastAPI(
    title="Personal Finance Tracker",
    description="Self-hosted expense tracker with LLM categorization and a daily summary for an Android widget.",
    version="0.9.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(account.router)
app.include_router(expenses.router)
app.include_router(incomes.router)
app.include_router(categories.router)
app.include_router(summary.router)
app.include_router(categorize.router)

# The mobile web client. Plain static files; every action it takes is one
# of the API calls above, so it needs no server-side code of its own.
app.mount("/app", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="app")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/app/")
