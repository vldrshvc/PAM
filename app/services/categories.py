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


def seed_default_categories(session: Session) -> None:
    """Insert any default category that does not exist yet. Safe to run on
    every startup; never touches categories the user already has."""
    existing = set(session.exec(select(Category.name)).all())
    for name in DEFAULT_CATEGORY_NAMES:
        if name not in existing:
            session.add(Category(name=name))
    session.commit()


def get_uncategorized(session: Session) -> Category:
    category = find_by_name(session, UNCATEGORIZED_NAME)
    if category is None:
        # Seeding runs at startup, so this is a deployment bug, not user input.
        raise RuntimeError(f'reserved category "{UNCATEGORIZED_NAME}" is missing')
    return category


def find_by_name(session: Session, name: str) -> Category | None:
    # Case-insensitive so "groceries" and "Groceries" cannot coexist; the
    # LLM categorizer later matches names the same way.
    statement = select(Category).where(func.lower(Category.name) == name.lower())
    return session.exec(statement).first()
