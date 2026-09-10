from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, or_, update
from sqlmodel import Session

from app.database import get_session
from app.models import Account, Expense, Income, Transfer, User
from app.schemas import AccountBalanceRead, AccountCreate, AccountRead, AccountUpdate
from app.security import get_current_user
from app.services.accounts import GENERAL_NAME, find_by_name, get_general
from app.services.ledger import account_balances

router = APIRouter(prefix="/accounts", tags=["accounts"])


def get_account_or_404(session: Session, user_id: int, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Account {account_id} not found")
    return account


def ensure_name_free(session: Session, user_id: int, name: str, except_id: int | None = None) -> None:
    clash = find_by_name(session, user_id, name)
    if clash is not None and clash.id != except_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'Account "{name}" already exists')


@router.get("", response_model=list[AccountBalanceRead])
def list_accounts(
    session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[AccountBalanceRead]:
    return [
        AccountBalanceRead.model_validate(entry.account, update={"balance": entry.balance})
        for entry in account_balances(session, user.id)
    ]


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(
    body: AccountCreate, session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> Account:
    ensure_name_free(session, user.id, body.name)
    account = Account.model_validate(body, update={"user_id": user.id})
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@router.get("/{account_id}", response_model=AccountBalanceRead)
def get_account(
    account_id: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> AccountBalanceRead:
    get_account_or_404(session, user.id, account_id)
    entry = next(e for e in account_balances(session, user.id) if e.account.id == account_id)
    return AccountBalanceRead.model_validate(entry.account, update={"balance": entry.balance})


@router.patch("/{account_id}", response_model=AccountRead)
def update_account(
    account_id: int,
    body: AccountUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Account:
    account = get_account_or_404(session, user.id, account_id)
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(field, ...) is None for field in ("name", "type", "opening_balance")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="name, type and opening_balance cannot be null",
        )
    if "name" in changes:
        ensure_name_free(session, user.id, changes["name"], except_id=account.id)
    account.sqlmodel_update(changes)
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> Response:
    account = get_account_or_404(session, user.id, account_id)
    general = get_general(session, user.id)
    if account.id == general.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'"{GENERAL_NAME}" is the default account and cannot be deleted',
        )
    # Its history becomes General's history: the opening balance and every
    # expense and income move over, transfers to/from General vanish (the
    # money is back where it started) and transfers with a third account are
    # re-pointed at General. The user's total balance is unchanged.
    general.opening_balance += account.opening_balance
    session.add(general)
    session.exec(update(Expense).where(Expense.account_id == account.id).values(account_id=general.id))
    session.exec(update(Income).where(Income.account_id == account.id).values(account_id=general.id))
    session.exec(
        delete(Transfer).where(
            Transfer.user_id == user.id,
            or_(
                (Transfer.from_account_id == account.id) & (Transfer.to_account_id == general.id),
                (Transfer.from_account_id == general.id) & (Transfer.to_account_id == account.id),
            ),
        )
    )
    session.exec(update(Transfer).where(Transfer.from_account_id == account.id).values(from_account_id=general.id))
    session.exec(update(Transfer).where(Transfer.to_account_id == account.id).values(to_account_id=general.id))
    session.delete(account)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
