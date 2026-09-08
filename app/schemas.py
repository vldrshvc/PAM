import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import field_validator
from sqlmodel import Field, SQLModel

from app.models import CategoryBase, ExpenseBase, ExpenseStatus, quantize_money


class HealthRead(SQLModel):
    status: Literal["ok"]


# --- Categories ---------------------------------------------------------------


class CategoryCreate(CategoryBase):
    """Body for POST /categories."""


class CategoryUpdate(SQLModel):
    """Body for PATCH /categories/{id}. Every field optional; sending
    "monthly_limit": null removes the budget."""

    name: str | None = Field(default=None, min_length=1, max_length=50)
    monthly_limit: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("monthly_limit")
    @classmethod
    def _limit(cls, value: Decimal | None) -> Decimal | None:
        return None if value is None else quantize_money(value)


class CategoryRead(CategoryBase):
    id: int


# --- Expenses -----------------------------------------------------------------


class ExpenseCreate(ExpenseBase):
    """Body for POST /expenses. Status is not client-settable: manual entries
    are always confirmed; pending is reserved for auto-ingested transactions.
    Omitting category_id files the expense under "uncategorized"."""

    category_id: int | None = None


class ExpenseUpdate(SQLModel):
    """Body for PATCH /expenses/{id}. Only the fields sent are changed."""

    price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    date: dt.date | None = None
    description: str | None = Field(default=None, max_length=255)
    category_id: int | None = None

    @field_validator("price")
    @classmethod
    def _normalize_price(cls, value: Decimal | None) -> Decimal | None:
        return None if value is None else quantize_money(value)


class ExpenseRead(ExpenseBase):
    id: int
    category_id: int
    status: ExpenseStatus


# --- Summaries (public client contract, see README) ---------------------------


class CategoryBudgetRead(SQLModel):
    id: int
    name: str
    monthly_limit: Decimal | None
    spent: Decimal
    # None when the category has no limit; negative when over budget.
    remaining: Decimal | None
    over_budget: bool


class DailySummaryRead(SQLModel):
    """Shape consumed by the Android widget. Treat as frozen: add fields if
    needed, never rename or remove."""

    date: dt.date
    timezone: str
    spent_today: Decimal
    spent_this_month: Decimal
    budget_total: Decimal
    remaining_total: Decimal
    over_budget: bool
    categories: list[CategoryBudgetRead]


class MonthlySummaryRead(SQLModel):
    month: str
    timezone: str
    spent_total: Decimal
    budget_total: Decimal
    remaining_total: Decimal
    over_budget: bool
    categories: list[CategoryBudgetRead]
