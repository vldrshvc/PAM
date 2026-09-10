from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, Transfer, User
from app.schemas import TransferCreate, TransferRead, TransferUpdate
from app.security import get_current_user

router = APIRouter(prefix="/transfers", tags=["transfers"])


def resolve_account_id(session: Session, user_id: int, account_id: int) -> int:
    account = session.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Account {account_id} does not exist",
        )
    return account_id


def check_distinct(from_id: int, to_id: int) -> None:
    if from_id == to_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="from_account_id and to_account_id must differ",
        )


def get_transfer_or_404(session: Session, user_id: int, transfer_id: int) -> Transfer:
    transfer = session.get(Transfer, transfer_id)
    if transfer is None or transfer.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transfer {transfer_id} not found")
    return transfer


@router.post("", response_model=TransferRead, status_code=status.HTTP_201_CREATED)
def create_transfer(
    body: TransferCreate, session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> Transfer:
    check_distinct(body.from_account_id, body.to_account_id)
    resolve_account_id(session, user.id, body.from_account_id)
    resolve_account_id(session, user.id, body.to_account_id)
    transfer = Transfer.model_validate(body, update={"user_id": user.id})
    session.add(transfer)
    session.commit()
    session.refresh(transfer)
    return transfer


@router.get("", response_model=list[TransferRead])
def list_transfers(
    date_from: date | None = Query(default=None, description="Inclusive lower bound"),
    date_to: date | None = Query(default=None, description="Inclusive upper bound"),
    account_id: int | None = Query(default=None, description="Either end of the transfer"),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[Transfer]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must not be after date_to",
        )
    statement = select(Transfer).where(Transfer.user_id == user.id)
    if date_from is not None:
        statement = statement.where(Transfer.date >= date_from)
    if date_to is not None:
        statement = statement.where(Transfer.date <= date_to)
    if account_id is not None:
        statement = statement.where(or_(Transfer.from_account_id == account_id, Transfer.to_account_id == account_id))
    return list(session.exec(statement.order_by(Transfer.date.desc(), Transfer.id.desc())).all())


@router.get("/{transfer_id}", response_model=TransferRead)
def get_transfer(
    transfer_id: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> Transfer:
    return get_transfer_or_404(session, user.id, transfer_id)


@router.patch("/{transfer_id}", response_model=TransferRead)
def update_transfer(
    transfer_id: int,
    body: TransferUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Transfer:
    transfer = get_transfer_or_404(session, user.id, transfer_id)
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(field, ...) is None for field in ("amount", "date", "from_account_id", "to_account_id")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="amount, date and account ids cannot be null",
        )
    for field in ("from_account_id", "to_account_id"):
        if field in changes:
            resolve_account_id(session, user.id, changes[field])
    check_distinct(
        changes.get("from_account_id", transfer.from_account_id),
        changes.get("to_account_id", transfer.to_account_id),
    )
    transfer.sqlmodel_update(changes)
    session.add(transfer)
    session.commit()
    session.refresh(transfer)
    return transfer


@router.delete("/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transfer(
    transfer_id: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> Response:
    transfer = get_transfer_or_404(session, user.id, transfer_id)
    session.delete(transfer)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
