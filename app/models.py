from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import field_validator
from sqlalchemy import Column, Enum as SAEnum, UniqueConstraint
from sqlmodel import Field, SQLModel

CENTS = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    # JSON numbers drop trailing zeros (12.40 -> 12.4); quantize so the
    # API always renders exactly two decimal places.
    return value.quantize(CENTS)


class ExpenseStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"


class IncomeSource(str, Enum):
    WORK = "work"
    FRIEND = "friend"
    DEBT = "debt"
    BONUS = "bonus"
    OTHER = "other"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(min_length=3, max_length=50, unique=True, index=True)
    # Only ever an argon2id hash; the plaintext never touches this model.
    hashed_password: str


class AccountType(str, Enum):
    DEBIT = "debit"
    CASH = "cash"
    OTHER = "other"


class AccountBase(SQLModel):
    name: str = Field(min_length=1, max_length=50)
    type: AccountType = AccountType.DEBIT
    # Free text because it is a bank or provider name: "AIB", "Revolut".
    subtype: str | None = Field(default=None, max_length=50)
    # What was in this account before its first recorded transaction, so the
    # computed balance matches reality. May be negative (overdrawn).
    opening_balance: Decimal = Field(default=Decimal("0.00"), max_digits=12, decimal_places=2)

    @field_validator("name", "subtype")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("opening_balance")
    @classmethod
    def _normalize_opening(cls, value: Decimal) -> Decimal:
        return quantize_money(value)


class Account(AccountBase, table=True):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_accounts_user_name"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    type: AccountType = Field(
        default=AccountType.DEBIT,
        sa_column=Column(
            SAEnum(AccountType, name="account_type", values_callable=lambda e: [m.value for m in e]),
            nullable=False,
        ),
    )


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
        return None if value is None else quantize_money(value)


class Category(CategoryBase, table=True):
    __tablename__ = "categories"
    # Names are unique per user, not globally: every user has their own
    # "Groceries" and their own "uncategorized".
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_categories_user_name"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)


class IncomeBase(SQLModel):
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    date: date
    source: IncomeSource = IncomeSource.WORK
    description: str | None = Field(default=None, max_length=255)

    @field_validator("amount")
    @classmethod
    def _normalize_amount(cls, value: Decimal) -> Decimal:
        return quantize_money(value)


class Income(IncomeBase, table=True):
    __tablename__ = "incomes"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    account_id: int = Field(foreign_key="accounts.id", index=True)
    source: IncomeSource = Field(
        default=IncomeSource.WORK,
        sa_column=Column(
            SAEnum(IncomeSource, name="income_source", values_callable=lambda e: [m.value for m in e]),
            nullable=False,
        ),
    )


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
        return quantize_money(value)


class Expense(ExpenseBase, table=True):
    __tablename__ = "expenses"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    account_id: int = Field(foreign_key="accounts.id", index=True)
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


class TransferBase(SQLModel):
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    date: date
    description: str | None = Field(default=None, max_length=255)

    @field_validator("amount")
    @classmethod
    def _normalize_amount(cls, value: Decimal) -> Decimal:
        return quantize_money(value)


class Transfer(TransferBase, table=True):
    """Money moved between two of the user's own accounts. Neither income
    nor expense: it changes account balances but never the total."""

    __tablename__ = "transfers"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    from_account_id: int = Field(foreign_key="accounts.id", index=True)
    to_account_id: int = Field(foreign_key="accounts.id", index=True)


class TargetBase(SQLModel):
    name: str = Field(min_length=1, max_length=50)
    # The total balance to reach by end_date.
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    start_date: date
    end_date: date

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("amount")
    @classmethod
    def _normalize_amount(cls, value: Decimal) -> Decimal:
        return quantize_money(value)


class Target(TargetBase, table=True):
    __tablename__ = "targets"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    # Balance when the target was set; the pace line runs from here.
    start_balance: Decimal = Field(max_digits=12, decimal_places=2)
