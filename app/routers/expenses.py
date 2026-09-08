from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session, select

from app.database import get_session
from app.models import Category, Expense, User
from app.schemas import ExpenseCreate, ExpenseRead, ExpenseUpdate
from app.security import get_current_user
from app.services.categories import get_uncategorized

router = APIRouter(prefix="/expenses", tags=["expenses"])


def resolve_category_id(session: Session, user_id: int, category_id: int | None) -> int:
    if category_id is None:
        return get_uncategorized(session, user_id).id
    category = session.get(Category, category_id)
    # Another user's category is "does not exist" from this user's point of view.
    if category is None or category.user_id != user_id:
        # 422 rather than 404: the URL resource exists, the body is what's wrong.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Category {category_id} does not exist",
        )
    return category_id


def get_expense_or_404(session: Session, user_id: int, expense_id: int) -> Expense:
    expense = session.get(Expense, expense_id)
    if expense is None or expense.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expense {expense_id} not found",
        )
    return expense


@router.post("", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED)
def create_expense(
    body: ExpenseCreate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Expense:
    expense = Expense.model_validate(
        body,
        update={
            "user_id": user.id,
            "category_id": resolve_category_id(session, user.id, body.category_id),
        },
    )
    session.add(expense)
    session.commit()
    session.refresh(expense)
    return expense


@router.get("", response_model=list[ExpenseRead])
def list_expenses(
    date_from: date | None = Query(default=None, description="Inclusive lower bound"),
    date_to: date | None = Query(default=None, description="Inclusive upper bound"),
    category_id: int | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[Expense]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must not be after date_to",
        )
    statement = select(Expense).where(Expense.user_id == user.id)
    if date_from is not None:
        statement = statement.where(Expense.date >= date_from)
    if date_to is not None:
        statement = statement.where(Expense.date <= date_to)
    if category_id is not None:
        statement = statement.where(Expense.category_id == category_id)
    return list(session.exec(statement.order_by(Expense.date.desc(), Expense.id.desc())).all())


@router.get("/{expense_id}", response_model=ExpenseRead)
def get_expense(
    expense_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Expense:
    return get_expense_or_404(session, user.id, expense_id)


@router.patch("/{expense_id}", response_model=ExpenseRead)
def update_expense(
    expense_id: int,
    body: ExpenseUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Expense:
    expense = get_expense_or_404(session, user.id, expense_id)
    # exclude_unset: a field left out of the body is untouched; a field
    # sent as null is written as null (only description allows that).
    changes = body.model_dump(exclude_unset=True)
    if "category_id" in changes:
        changes["category_id"] = resolve_category_id(session, user.id, changes["category_id"])
    if changes.get("price", ...) is None or changes.get("date", ...) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="price and date cannot be null",
        )
    expense.sqlmodel_update(changes)
    session.add(expense)
    session.commit()
    session.refresh(expense)
    return expense


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    expense_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    expense = get_expense_or_404(session, user.id, expense_id)
    session.delete(expense)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
