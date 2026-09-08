"""Budget arithmetic and period boundaries. Pure functions over plain
values so the maths can be tested without a database."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.models import Category

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class CategoryBudget:
    id: int
    name: str
    monthly_limit: Decimal | None
    spent: Decimal
    remaining: Decimal | None
    over_budget: bool


@dataclass(frozen=True)
class BudgetTotals:
    spent_total: Decimal
    budget_total: Decimal
    remaining_total: Decimal
    over_budget: bool
    categories: list[CategoryBudget]


def today_in(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """First and last day of the month, inclusive."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def category_budget(category: Category, spent: Decimal) -> CategoryBudget:
    limit = category.monthly_limit
    remaining = None if limit is None else limit - spent
    return CategoryBudget(
        id=category.id,
        name=category.name,
        monthly_limit=limit,
        spent=spent,
        remaining=remaining,
        over_budget=remaining is not None and remaining < ZERO,
    )


def budget_totals(categories: list[Category], spent_by_category: dict[int, Decimal]) -> BudgetTotals:
    """Combine every category with what was spent in it this period.

    budget_total and remaining_total only cover categories that have a
    limit: spending in an unbudgeted category is reported per category
    and in spent_total, but it cannot "eat" a budget that was never set.
    """
    lines = [category_budget(c, spent_by_category.get(c.id, ZERO)) for c in categories]
    budget_total = sum((c.monthly_limit for c in lines if c.monthly_limit is not None), ZERO)
    spent_in_budgeted = sum((c.spent for c in lines if c.monthly_limit is not None), ZERO)
    remaining_total = budget_total - spent_in_budgeted
    return BudgetTotals(
        spent_total=sum((c.spent for c in lines), ZERO),
        budget_total=budget_total,
        remaining_total=remaining_total,
        over_budget=remaining_total < ZERO,
        categories=lines,
    )
