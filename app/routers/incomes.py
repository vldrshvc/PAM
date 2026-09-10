from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session, select

from app.database import get_session
from app.models import Income, IncomeSource, User
from app.schemas import IncomeCreate, IncomeRead, IncomeUpdate
from app.routers.expenses import resolve_account_id
from app.security import get_current_user

router = APIRouter(prefix="/incomes", tags=["incomes"])


def get_income_or_404(session: Session, user_id: int, income_id: int) -> Income:
    income = session.get(Income, income_id)
    if income is None or income.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Income {income_id} not found")
    return income


@router.post("", response_model=IncomeRead, status_code=status.HTTP_201_CREATED)
def create_income(
    body: IncomeCreate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Income:
    income = Income.model_validate(
        body,
        update={"user_id": user.id, "account_id": resolve_account_id(session, user.id, body.account_id)},
    )
    session.add(income)
    session.commit()
    session.refresh(income)
    return income


@router.get("", response_model=list[IncomeRead])
def list_incomes(
    date_from: date | None = Query(default=None, description="Inclusive lower bound"),
    date_to: date | None = Query(default=None, description="Inclusive upper bound"),
    source: IncomeSource | None = None,
    account_id: int | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[Income]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must not be after date_to",
        )
    statement = select(Income).where(Income.user_id == user.id)
    if date_from is not None:
        statement = statement.where(Income.date >= date_from)
    if date_to is not None:
        statement = statement.where(Income.date <= date_to)
    if source is not None:
        statement = statement.where(Income.source == source)
    if account_id is not None:
        statement = statement.where(Income.account_id == account_id)
    return list(session.exec(statement.order_by(Income.date.desc(), Income.id.desc())).all())


@router.get("/{income_id}", response_model=IncomeRead)
def get_income(
    income_id: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> Income:
    return get_income_or_404(session, user.id, income_id)


@router.patch("/{income_id}", response_model=IncomeRead)
def update_income(
    income_id: int,
    body: IncomeUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Income:
    income = get_income_or_404(session, user.id, income_id)
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(field, ...) is None for field in ("amount", "date", "source", "account_id")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="amount, date, source and account_id cannot be null",
        )
    if "account_id" in changes:
        resolve_account_id(session, user.id, changes["account_id"])
    income.sqlmodel_update(changes)
    session.add(income)
    session.commit()
    session.refresh(income)
    return income


@router.delete("/{income_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_income(
    income_id: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> Response:
    income = get_income_or_404(session, user.id, income_id)
    session.delete(income)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
