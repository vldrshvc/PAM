"""Money in, money out, and the running balance. These are the only
aggregates that span both incomes and expenses, so they live together."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Expense, ExpenseStatus, Income, User
from app.services.budget import ZERO


def income_total(session: Session, user_id: int, start: date | None = None, end: date | None = None) -> Decimal:
    statement = select(func.coalesce(func.sum(Income.amount), 0)).where(Income.user_id == user_id)
    if start is not None:
        statement = statement.where(Income.date >= start)
    if end is not None:
        statement = statement.where(Income.date <= end)
    return Decimal(session.exec(statement).one()).quantize(ZERO)


def expense_total(session: Session, user_id: int, start: date | None = None, end: date | None = None) -> Decimal:
    """Confirmed expenses only; pending (auto-ingested) rows never count."""
    statement = (
        select(func.coalesce(func.sum(Expense.price), 0))
        .where(Expense.user_id == user_id, Expense.status == ExpenseStatus.CONFIRMED)
    )
    if start is not None:
        statement = statement.where(Expense.date >= start)
    if end is not None:
        statement = statement.where(Expense.date <= end)
    return Decimal(session.exec(statement).one()).quantize(ZERO)


def balance(user: User, income: Decimal, expenses: Decimal) -> Decimal:
    return (user.opening_balance + income - expenses).quantize(ZERO)


def current_balance(session: Session, user: User) -> Decimal:
    return balance(user, income_total(session, user.id), expense_total(session, user.id))
