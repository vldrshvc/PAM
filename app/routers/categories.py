from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import update
from sqlmodel import Session, select

from app.database import get_session
from app.models import Category, Expense
from app.schemas import CategoryCreate, CategoryRead, CategoryUpdate
from app.services.categories import UNCATEGORIZED_NAME, find_by_name, get_uncategorized

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryRead])
def list_categories(session: Session = Depends(get_session)) -> list[Category]:
    return list(session.exec(select(Category).order_by(Category.id)).all())


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryCreate, session: Session = Depends(get_session)) -> Category:
    if find_by_name(session, body.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'Category "{body.name}" already exists',
        )
    category = Category.model_validate(body)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def get_category_or_404(session: Session, category_id: int) -> Category:
    category = session.get(Category, category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category {category_id} not found",
        )
    return category


@router.patch("/{category_id}", response_model=CategoryRead)
def update_category(
    category_id: int, body: CategoryUpdate, session: Session = Depends(get_session)
) -> Category:
    category = get_category_or_404(session, category_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        if changes["name"] is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="name cannot be null"
            )
        if category.name == UNCATEGORIZED_NAME:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f'"{UNCATEGORIZED_NAME}" is the fallback category and cannot be renamed',
            )
        clash = find_by_name(session, changes["name"])
        if clash is not None and clash.id != category.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f'Category "{changes["name"]}" already exists',
            )
    category.sqlmodel_update(changes)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: int, session: Session = Depends(get_session)) -> Response:
    category = get_category_or_404(session, category_id)
    if category.name == UNCATEGORIZED_NAME:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'"{UNCATEGORIZED_NAME}" is the fallback category and cannot be deleted',
        )
    uncategorized = get_uncategorized(session)
    # Reassign and delete in one transaction so a failure leaves no orphans.
    session.exec(
        update(Expense)
        .where(Expense.category_id == category_id)
        .values(category_id=uncategorized.id)
    )
    session.delete(category)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
