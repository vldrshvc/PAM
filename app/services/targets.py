"""Target arithmetic: how much is still needed, how much per day, and
whether the user is on pace. Pure functions over a target, the current
balance and today's date, so every branch is unit-testable."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from enum import Enum

from app.models import Target, quantize_money
from app.services.budget import ZERO


class TargetStatus(str, Enum):
    ON_TRACK = "on_track"
    BEHIND = "behind"
    ACHIEVED = "achieved"
    EXPIRED = "expired"


@dataclass(frozen=True)
class TargetProgress:
    current_balance: Decimal
    remaining: Decimal
    days_total: int
    days_elapsed: int
    days_left: int
    # remaining / days_left, rounded up to the cent; 0 once achieved.
    required_per_day: Decimal
    # Where the straight line from start_balance to amount says you should be today.
    expected_balance: Decimal
    # Balance at end_date if the average daily change so far continues.
    projected_balance: Decimal
    # Date the target would be hit at the current pace; None if never.
    projected_date: date | None
    status: TargetStatus


def _ceil_cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def target_progress(target: Target, current_balance: Decimal, today: date) -> TargetProgress:
    # Days are counted inclusively: a target ending today has one day left.
    days_total = max((target.end_date - target.start_date).days + 1, 1)
    days_elapsed = min(max((today - target.start_date).days, 0), days_total)
    days_left = max((target.end_date - today).days + 1, 0)

    remaining = max(target.amount - current_balance, ZERO).quantize(ZERO)
    achieved = remaining == ZERO

    if achieved or days_left == 0:
        required_per_day = ZERO
    else:
        required_per_day = _ceil_cents(remaining / days_left)

    climb = target.amount - target.start_balance
    expected_balance = quantize_money(target.start_balance + climb * Decimal(days_elapsed) / Decimal(days_total))

    gained = current_balance - target.start_balance
    daily_rate = gained / Decimal(days_elapsed) if days_elapsed > 0 else ZERO
    projected_balance = quantize_money(current_balance + daily_rate * Decimal(days_left))
    projected_date: date | None = None
    if achieved:
        projected_date = today
    elif daily_rate > 0:
        days_needed = int((remaining / daily_rate).to_integral_value(rounding=ROUND_CEILING))
        projected_date = today + timedelta(days=days_needed)

    if achieved:
        status = TargetStatus.ACHIEVED
    elif days_left == 0:
        status = TargetStatus.EXPIRED
    elif current_balance >= expected_balance:
        status = TargetStatus.ON_TRACK
    else:
        status = TargetStatus.BEHIND

    return TargetProgress(
        current_balance=current_balance,
        remaining=remaining,
        days_total=days_total,
        days_elapsed=days_elapsed,
        days_left=days_left,
        required_per_day=required_per_day,
        expected_balance=expected_balance,
        projected_balance=projected_balance,
        projected_date=projected_date,
        status=status,
    )
