"""Budget arithmetic: the logic behind both summary endpoints."""

from datetime import date
from decimal import Decimal

from app.models import Category
from app.services.budget import budget_totals, category_budget, month_bounds


def cat(id: int, name: str, limit: str | None) -> Category:
    return Category(id=id, user_id=1, name=name, monthly_limit=None if limit is None else Decimal(limit))


def test_category_under_budget():
    line = category_budget(cat(1, "Groceries", "300.00"), Decimal("120.00"))
    assert line.remaining == Decimal("180.00")
    assert line.over_budget is False


def test_category_exactly_at_limit_is_not_over():
    line = category_budget(cat(1, "Groceries", "300.00"), Decimal("300.00"))
    assert line.remaining == Decimal("0.00")
    assert line.over_budget is False


def test_category_over_budget_has_negative_remaining():
    line = category_budget(cat(1, "Eating out", "100.00"), Decimal("115.00"))
    assert line.remaining == Decimal("-15.00")
    assert line.over_budget is True


def test_category_without_limit_has_no_remaining_and_is_never_over():
    line = category_budget(cat(1, "Travel", None), Decimal("9999.00"))
    assert line.monthly_limit is None
    assert line.remaining is None
    assert line.over_budget is False


def test_totals_only_count_budgeted_categories():
    categories = [cat(1, "uncategorized", None), cat(2, "Groceries", "300.00"), cat(3, "Eating out", "100.00")]
    spent = {1: Decimal("50.00"), 2: Decimal("120.00"), 3: Decimal("80.00")}

    totals = budget_totals(categories, spent)

    assert totals.spent_total == Decimal("250.00")
    assert totals.budget_total == Decimal("400.00")
    # 400 - (120 + 80); the 50 in uncategorized does not reduce the budget.
    assert totals.remaining_total == Decimal("200.00")
    assert totals.over_budget is False


def test_totals_flag_overspend_across_categories():
    categories = [cat(1, "Groceries", "100.00"), cat(2, "Eating out", "100.00")]
    totals = budget_totals(categories, {1: Decimal("150.00"), 2: Decimal("60.00")})
    assert totals.remaining_total == Decimal("-10.00")
    assert totals.over_budget is True


def test_totals_with_no_spending():
    totals = budget_totals([cat(1, "Groceries", "300.00")], {})
    assert totals.spent_total == Decimal("0.00")
    assert totals.remaining_total == Decimal("300.00")
    assert totals.categories[0].spent == Decimal("0.00")


def test_totals_preserve_category_order():
    categories = [cat(3, "C", None), cat(1, "A", None), cat(2, "B", None)]
    assert [c.id for c in budget_totals(categories, {}).categories] == [3, 1, 2]


def test_month_bounds_handle_leap_year_and_december():
    assert month_bounds(2024, 2) == (date(2024, 2, 1), date(2024, 2, 29))
    assert month_bounds(2025, 2) == (date(2025, 2, 1), date(2025, 2, 28))
    assert month_bounds(2026, 12) == (date(2026, 12, 1), date(2026, 12, 31))
