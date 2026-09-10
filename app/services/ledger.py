"""Money in, money out, and balances. These are the only aggregates that
span incomes, expenses and transfers, so they live together."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Account, Expense, ExpenseStatus, Income, Transfer
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


@dataclass(frozen=True)
class AccountBalance:
    account: Account
    balance: Decimal


def account_balances(session: Session, user_id: int) -> list[AccountBalance]:
    """Per-account balance: opening + income - confirmed expenses + transfers
    in - transfers out. Four GROUP BY queries, then arithmetic in Python."""
    accounts = list(session.exec(select(Account).where(Account.user_id == user_id).order_by(Account.id)).all())

    def sums(column, amount, *extra) -> dict[int, Decimal]:
        statement = select(column, func.sum(amount)).where(*extra).group_by(column)
        return {key: Decimal(total) for key, total in session.exec(statement).all()}

    income = sums(Income.account_id, Income.amount, Income.user_id == user_id)
    spent = sums(Expense.account_id, Expense.price, Expense.user_id == user_id, Expense.status == ExpenseStatus.CONFIRMED)
    moved_in = sums(Transfer.to_account_id, Transfer.amount, Transfer.user_id == user_id)
    moved_out = sums(Transfer.from_account_id, Transfer.amount, Transfer.user_id == user_id)

    return [
        AccountBalance(
            account=a,
            balance=(
                a.opening_balance
                + income.get(a.id, ZERO)
                - spent.get(a.id, ZERO)
                + moved_in.get(a.id, ZERO)
                - moved_out.get(a.id, ZERO)
            ).quantize(ZERO),
        )
        for a in accounts
    ]


def opening_total(session: Session, user_id: int) -> Decimal:
    statement = select(func.coalesce(func.sum(Account.opening_balance), 0)).where(Account.user_id == user_id)
    return Decimal(session.exec(statement).one()).quantize(ZERO)


def balance(opening: Decimal, income: Decimal, expenses: Decimal) -> Decimal:
    # Transfers move money between the user's own accounts; they cancel out.
    return (opening + income - expenses).quantize(ZERO)


def current_balance(session: Session, user_id: int) -> Decimal:
    return balance(opening_total(session, user_id), income_total(session, user_id), expense_total(session, user_id))
