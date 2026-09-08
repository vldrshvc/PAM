from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import field_validator
from sqlmodel import Field, SQLModel


class ExpenseStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"


class ExpenseBase(SQLModel):
    # Decimal, not float: money must round-trip exactly. Two decimal places
    # matches cents; ten digits total caps a single expense at 99,999,999.99.
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    date: date
    description: str | None = Field(default=None, max_length=255)

    @field_validator("price")
    @classmethod
    def _normalize_price(cls, value: Decimal) -> Decimal:
        # JSON numbers drop trailing zeros (12.40 -> 12.4); quantize so the
        # API always renders exactly two decimal places.
        return value.quantize(Decimal("0.01"))


class Expense(ExpenseBase):
    id: int
    status: ExpenseStatus = ExpenseStatus.CONFIRMED
