"""Category rules that are not HTTP concerns: the reserved fallback
category, the default set, and idempotent seeding."""

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Category

UNCATEGORIZED_NAME = "uncategorized"

DEFAULT_CATEGORY_NAMES: tuple[str, ...] = (
    UNCATEGORIZED_NAME,
    "Groceries",
    "Eating out",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
)


def seed_default_categories(session: Session, user_id: int) -> None:
    """Give a new user the default set. Does not commit: registration
    commits the user and their categories together."""
    for name in DEFAULT_CATEGORY_NAMES:
        session.add(Category(name=name, user_id=user_id))


def get_uncategorized(session: Session, user_id: int) -> Category:
    category = find_by_name(session, user_id, UNCATEGORIZED_NAME)
    if category is None:
        # Seeded at registration, so this is a data bug, not user input.
        raise RuntimeError(f'reserved category "{UNCATEGORIZED_NAME}" is missing for user {user_id}')
    return category


def find_by_name(session: Session, user_id: int, name: str) -> Category | None:
    # Case-insensitive so "groceries" and "Groceries" cannot coexist; the
    # LLM categorizer matches names the same way.
    statement = select(Category).where(
        Category.user_id == user_id, func.lower(Category.name) == name.lower()
    )
    return session.exec(statement).first()
