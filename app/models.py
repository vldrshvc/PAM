from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import field_validator
from sqlalchemy import Column, Enum as SAEnum
from sqlmodel import Field, SQLModel


class ExpenseStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"


class CategoryBase(SQLModel):
    name: str = Field(min_length=1, max_length=50)
    # None means "no budget for this category".
    monthly_limit: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("monthly_limit")
    @classmethod
    def _normalize_limit(cls, value: Decimal | None) -> Decimal | None:
        return None if value is None else value.quantize(Decimal("0.01"))


class Category(CategoryBase, table=True):
    __tablename__ = "categories"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=1, max_length=50, unique=True, index=True)


class ExpenseBase(SQLModel):
    # Decimal, not float: money must round-trip exactly. Two decimal places
    # matches cents; ten digits total caps a single expense at 99,999,999.99.
    # SQLModel maps this to NUMERIC(10, 2) in Postgres.
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    date: date
    description: str | None = Field(default=None, max_length=255)

    @field_validator("price")
    @classmethod
    def _normalize_price(cls, value: Decimal) -> Decimal:
        # JSON numbers drop trailing zeros (12.40 -> 12.4); quantize so the
        # API always renders exactly two decimal places.
        return value.quantize(Decimal("0.01"))


class Expense(ExpenseBase, table=True):
    __tablename__ = "expenses"

    id: int | None = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="categories.id", index=True)
    # values_callable: store "confirmed" in Postgres, not the member name
    # "CONFIRMED", so the column reads the same as the API.
    status: ExpenseStatus = Field(
        default=ExpenseStatus.CONFIRMED,
        sa_column=Column(
            SAEnum(ExpenseStatus, name="expense_status", values_callable=lambda e: [m.value for m in e]),
            nullable=False,
        ),
    )
