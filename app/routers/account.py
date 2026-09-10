from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.models import User
from app.schemas import BalanceRead, MeRead, MeUpdate
from app.security import get_current_user
from app.services.ledger import balance, expense_total, income_total

router = APIRouter(tags=["account"])


@router.get("/me", response_model=MeRead)
def read_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me", response_model=MeRead)
def update_me(
    body: MeUpdate, session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> User:
    user.opening_balance = body.opening_balance
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.get("/balance", response_model=BalanceRead)
def read_balance(session: Session = Depends(get_session), user: User = Depends(get_current_user)) -> BalanceRead:
    income = income_total(session, user.id)
    expenses = expense_total(session, user.id)
    return BalanceRead(
        opening_balance=user.opening_balance,
        income_total=income,
        expense_total=expenses,
        balance=balance(user, income, expenses),
    )
