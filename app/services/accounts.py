"""Account rules that are not HTTP concerns: the default account every user
gets, and lookups scoped to a user."""

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Account, AccountType

DEFAULT_NAME = "General"


def seed_default_account(session: Session, user_id: int) -> Account:
    """Every user starts with one account, flagged as their default. Does not
    commit: registration commits the user, their categories and this together."""
    account = Account(name=DEFAULT_NAME, type=AccountType.DEBIT, user_id=user_id, is_default=True)
    session.add(account)
    return account


def default_account(session: Session, user_id: int) -> Account:
    """The account that unassigned expenses and incomes fall back to.

    Identified by a flag, not by name, so renaming it (everyone renames it to
    their real bank) does not break anything. The oldest account is a fallback
    for rows that predate the flag.
    """
    flagged = select(Account).where(Account.user_id == user_id, Account.is_default == True)  # noqa: E712
    account = session.exec(flagged).first()
    if account is None:
        oldest = select(Account).where(Account.user_id == user_id).order_by(Account.id)
        account = session.exec(oldest).first()
    if account is None:
        # Seeded at registration, so this is a data bug, not user input.
        raise RuntimeError(f"user {user_id} has no accounts")
    return account


def find_by_name(session: Session, user_id: int, name: str) -> Account | None:
    statement = select(Account).where(
        Account.user_id == user_id, func.lower(Account.name) == name.lower()
    )
    return session.exec(statement).first()
