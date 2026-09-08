from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.database import get_session
from app.models import Category, Expense
from app.schemas import ExpenseCreate, ExpenseRead
from app.services.categories import get_uncategorized

router = APIRouter(prefix="/expenses", tags=["expenses"])


def resolve_category_id(session: Session, category_id: int | None) -> int:
    if category_id is None:
        return get_uncategorized(session).id
    if session.get(Category, category_id) is None:
        # 422 rather than 404: the URL resource exists, the body is what's wrong.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Category {category_id} does not exist",
        )
    return category_id


@router.post("", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED)
def create_expense(body: ExpenseCreate, session: Session = Depends(get_session)) -> Expense:
    expense = Expense.model_validate(
        body, update={"category_id": resolve_category_id(session, body.category_id)}
    )
    session.add(expense)
    session.commit()
    session.refresh(expense)
    return expense


@router.get("", response_model=list[ExpenseRead])
def list_expenses(session: Session = Depends(get_session)) -> list[Expense]:
    return list(session.exec(select(Expense).order_by(Expense.id)).all())


@router.get("/{expense_id}", response_model=ExpenseRead)
def get_expense(expense_id: int, session: Session = Depends(get_session)) -> Expense:
    expense = session.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expense {expense_id} not found",
        )
    return expense
