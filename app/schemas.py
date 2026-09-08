from typing import Literal

from sqlmodel import SQLModel

from app.models import CategoryBase, ExpenseBase, ExpenseStatus


class HealthRead(SQLModel):
    status: Literal["ok"]


class CategoryCreate(CategoryBase):
    """Body for POST /categories."""


class CategoryRead(CategoryBase):
    id: int


class ExpenseCreate(ExpenseBase):
    """Body for POST /expenses. Status is not client-settable: manual entries
    are always confirmed; pending is reserved for auto-ingested transactions.
    Omitting category_id files the expense under "uncategorized"."""

    category_id: int | None = None


class ExpenseRead(ExpenseBase):
    id: int
    category_id: int
    status: ExpenseStatus
