from typing import Literal

from sqlmodel import SQLModel

from app.models import ExpenseBase, ExpenseStatus


class HealthRead(SQLModel):
    status: Literal["ok"]


class ExpenseCreate(ExpenseBase):
    """Body for POST /expenses. Status is not client-settable: manual entries
    are always confirmed; pending is reserved for auto-ingested transactions."""


class ExpenseRead(ExpenseBase):
    id: int
    status: ExpenseStatus
