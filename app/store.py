"""In-memory expense store for phase 1.

Exists only to prove the request/response flow before Postgres arrives in
phase 2, where this module is deleted and routers depend on a DB session
instead. Keeping it behind a dependency means the routers never touch a
module-level list directly.
"""

from itertools import count

from app.models import Expense
from app.schemas import ExpenseCreate


class InMemoryExpenseStore:
    def __init__(self) -> None:
        self._expenses: dict[int, Expense] = {}
        self._ids = count(start=1)

    def add(self, data: ExpenseCreate) -> Expense:
        expense = Expense(id=next(self._ids), **data.model_dump())
        self._expenses[expense.id] = expense
        return expense

    def list(self) -> list[Expense]:
        return list(self._expenses.values())

    def get(self, expense_id: int) -> Expense | None:
        return self._expenses.get(expense_id)


_store = InMemoryExpenseStore()


def get_store() -> InMemoryExpenseStore:
    return _store
