from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.database import get_session
from app.ecb import get_rates
from app.llm import LLMClient, LLMUnavailableError
from app.models import Account, Category, Expense, ExpenseStatus, User
from app.nbu import HryvniaRates
from app.routers.categorize import llm_dependency
from app.routers.summary import TzQuery, parse_timezone
from app.schemas import ExpenseRead, NotificationIn, NotificationRead
from app.security import get_current_user
from app.services.accounts import default_account
from app.services.answers import AnswerError
from app.services.budget import today_in
from app.services.fx import Chain, EcbRates, RateLookup, RateUnavailableError
from app.services.notifications import OUT, could_be_money, read

router = APIRouter(prefix="/notifications", tags=["notifications"])


def rates_dependency() -> RateLookup:
    try:
        return Chain((EcbRates(get_rates()), HryvniaRates()))
    except RateUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


def guess_account(session: Session, user_id: int, package: str) -> Account:
    """Charge it to the account whose name looks like the app that posted it.

    An Android package is something like com.revolut.revolut, so its segments
    are matched against the user's account names and bank names. A miss is not
    a problem: the default account is the right answer for cash-like spending
    anyway, and the user can change it before confirming.
    """
    segments = {part.lower() for part in package.split(".") if len(part) > 2}
    accounts = session.exec(select(Account).where(Account.user_id == user_id)).all()
    for account in accounts:
        names = {account.name.lower()}
        if account.subtype:
            names.add(account.subtype.lower())
        if names & segments:
            return account
    return default_account(session, user_id)


@router.post("", response_model=NotificationRead, status_code=status.HTTP_200_OK)
def receive_notification(
    body: NotificationIn,
    tz: str = TzQuery,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(llm_dependency),
    rates: RateLookup = Depends(rates_dependency),
    user: User = Depends(get_current_user),
) -> NotificationRead:
    """Take one notification and, if it is a payment, park it for confirmation.

    Always 200 for a notification that simply is not about a payment: the
    phone sends whatever looked like money and should not have to interpret
    an error to learn that it guessed wrong.
    """
    seen = session.exec(
        select(Expense).where(Expense.user_id == user.id, Expense.source_key == body.key)
    ).first()
    if seen is not None:
        return NotificationRead(outcome="duplicate", expense=ExpenseRead.model_validate(seen))

    full_text = f"{body.title}: {body.text}" if body.title else body.text
    if not could_be_money(full_text):
        # The phone's filter and this one are the same rule; this one also
        # guards the endpoint against anything else that might call it.
        return NotificationRead(outcome="ignored")

    today = today_in(parse_timezone(tz))
    categories = list(
        session.exec(select(Category).where(Category.user_id == user.id).order_by(Category.id)).all()
    )
    try:
        result = read(full_text, categories, llm, today, rates)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except (AnswerError, RateUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))

    if result.direction != OUT or result.amount is None:
        return NotificationRead(outcome="incoming" if result.direction == "in" else "ignored")

    expense = Expense(
        price=result.amount,
        date=today,
        description=result.merchant,
        user_id=user.id,
        category_id=result.category.id,
        account_id=guess_account(session, user.id, body.package).id,
        # Pending: it counts towards nothing until the user says so.
        status=ExpenseStatus.PENDING,
        source_key=body.key,
    )
    session.add(expense)
    session.commit()
    session.refresh(expense)
    note = None
    if result.converted_from is not None:
        amount, currency = result.converted_from
        note = f"{amount} {currency} ({result.rate_note})"
    return NotificationRead(
        outcome="pending", expense=ExpenseRead.model_validate(expense), note=note
    )
