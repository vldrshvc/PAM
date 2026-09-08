from fastapi import FastAPI

from app.routers import expenses, health

app = FastAPI(
    title="Personal Finance Tracker",
    description="Self-hosted expense tracker with LLM categorization and a daily summary for an Android widget.",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(expenses.router)
