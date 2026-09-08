from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import Session, select

from app.database import get_session
from app.models import Category, Expense, ExpenseStatus
from app.schemas import CategoryBudgetRead, DailySummaryRead, MonthlySummaryRead
from app.services.budget import ZERO, budget_totals, month_bounds, today_in

router = APIRouter(prefix="/summary", tags=["summary"])

# The client sends its own zone so "today" rolls over at the user's
# midnight, not the server's. UTC is only the fallback for clients that
# send nothing.
TzQuery = Query(default="UTC", description="IANA timezone name, e.g. Europe/Dublin")


def parse_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown timezone {name!r}",
        )


def spent_by_category(session: Session, start: date, end: date) -> dict[int, Decimal]:
    """One GROUP BY over confirmed expenses in [start, end]."""
    statement = (
        select(Expense.category_id, func.sum(Expense.price))
        .where(Expense.date >= start, Expense.date <= end)
        .where(Expense.status == ExpenseStatus.CONFIRMED)
        .group_by(Expense.category_id)
    )
    return {category_id: total for category_id, total in session.exec(statement).all()}


def spent_total(session: Session, start: date, end: date) -> Decimal:
    statement = (
        select(func.coalesce(func.sum(Expense.price), 0))
        .where(Expense.date >= start, Expense.date <= end)
        .where(Expense.status == ExpenseStatus.CONFIRMED)
    )
    return Decimal(session.exec(statement).one()).quantize(ZERO)


def all_categories(session: Session) -> list[Category]:
    return list(session.exec(select(Category).order_by(Category.id)).all())


@router.get("/daily", response_model=DailySummaryRead)
def daily_summary(tz: str = TzQuery, session: Session = Depends(get_session)) -> DailySummaryRead:
    zone = parse_timezone(tz)
    today = today_in(zone)
    month_start, month_end = month_bounds(today.year, today.month)

    totals = budget_totals(all_categories(session), spent_by_category(session, month_start, month_end))
    # The widget wants at-a-glance state, so only budgeted categories are
    # listed; the monthly endpoint has the full breakdown.
    budgeted = [c for c in totals.categories if c.monthly_limit is not None]
    return DailySummaryRead(
        date=today,
        timezone=zone.key,
        spent_today=spent_total(session, today, today),
        spent_this_month=totals.spent_total,
        budget_total=totals.budget_total,
        remaining_total=totals.remaining_total,
        over_budget=totals.over_budget,
        categories=[CategoryBudgetRead.model_validate(c, from_attributes=True) for c in budgeted],
    )


@router.get("/monthly", response_model=MonthlySummaryRead)
def monthly_summary(
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM; defaults to the current month in tz"),
    tz: str = TzQuery,
    session: Session = Depends(get_session),
) -> MonthlySummaryRead:
    zone = parse_timezone(tz)
    if month is None:
        today = today_in(zone)
        year, month_number = today.year, today.month
    else:
        year, month_number = (int(part) for part in month.split("-"))
    start, end = month_bounds(year, month_number)

    totals = budget_totals(all_categories(session), spent_by_category(session, start, end))
    return MonthlySummaryRead(
        month=f"{year:04d}-{month_number:02d}",
        timezone=zone.key,
        spent_total=totals.spent_total,
        budget_total=totals.budget_total,
        remaining_total=totals.remaining_total,
        over_budget=totals.over_budget,
        categories=[CategoryBudgetRead.model_validate(c, from_attributes=True) for c in totals.categories],
    )
