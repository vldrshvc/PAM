"""Account rules that are not HTTP concerns: the default account every
user gets and lookups scoped to a user."""

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Account, AccountType

GENERAL_NAME = "General"


def seed_general_account(session: Session, user_id: int) -> Account:
    """Every user starts with one account. Does not commit: registration
    commits the user, their categories and this account together."""
    account = Account(name=GENERAL_NAME, type=AccountType.DEBIT, user_id=user_id)
    session.add(account)
    return account


def get_general(session: Session, user_id: int) -> Account:
    account = find_by_name(session, user_id, GENERAL_NAME)
    if account is None:
        # Seeded at registration (or by migration), so this is a data bug.
        raise RuntimeError(f'reserved account "{GENERAL_NAME}" is missing for user {user_id}')
    return account


def find_by_name(session: Session, user_id: int, name: str) -> Account | None:
    statement = select(Account).where(
        Account.user_id == user_id, func.lower(Account.name) == name.lower()
    )
    return session.exec(statement).first()
