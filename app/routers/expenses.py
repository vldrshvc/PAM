from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas import ExpenseCreate, ExpenseRead
from app.store import InMemoryExpenseStore, get_store

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.post("", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED)
def create_expense(
    body: ExpenseCreate, store: InMemoryExpenseStore = Depends(get_store)
) -> ExpenseRead:
    return store.add(body)


@router.get("", response_model=list[ExpenseRead])
def list_expenses(store: InMemoryExpenseStore = Depends(get_store)) -> list[ExpenseRead]:
    return store.list()


@router.get("/{expense_id}", response_model=ExpenseRead)
def get_expense(
    expense_id: int, store: InMemoryExpenseStore = Depends(get_store)
) -> ExpenseRead:
    expense = store.get(expense_id)
    if expense is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expense {expense_id} not found",
        )
    return expense
