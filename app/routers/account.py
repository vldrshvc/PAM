from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.models import User
from app.schemas import AccountBalanceRead, BalanceRead, UserRead
from app.security import get_current_user
from app.services.ledger import account_balances, balance, expense_total, income_total, opening_total

router = APIRouter(tags=["account"])


@router.get("/me", response_model=UserRead)
def read_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/balance", response_model=BalanceRead)
def read_balance(session: Session = Depends(get_session), user: User = Depends(get_current_user)) -> BalanceRead:
    opening = opening_total(session, user.id)
    income = income_total(session, user.id)
    expenses = expense_total(session, user.id)
    return BalanceRead(
        opening_balance=opening,
        income_total=income,
        expense_total=expenses,
        balance=balance(opening, income, expenses),
        accounts=[
            AccountBalanceRead.model_validate(entry.account, update={"balance": entry.balance})
            for entry in account_balances(session, user.id)
        ],
    )
