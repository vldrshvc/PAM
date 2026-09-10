from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.database import get_session
from app.models import Target, User
from app.routers.summary import TzQuery, parse_timezone, read_targets
from app.schemas import TargetCreate, TargetRead, TargetUpdate
from app.security import get_current_user
from app.services.budget import today_in
from app.services.ledger import current_balance
from app.services.targets import target_progress

router = APIRouter(prefix="/targets", tags=["targets"])


def get_target_or_404(session: Session, user_id: int, target_id: int) -> Target:
    target = session.get(Target, target_id)
    if target is None or target.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Target {target_id} not found")
    return target


def check_dates(start: date, end: date) -> None:
    if end < start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="end_date must be on or after start_date",
        )


def read_target(session: Session, user_id: int, target: Target, today: date) -> TargetRead:
    progress = target_progress(target, current_balance(session, user_id), today)
    return TargetRead.model_validate(target, update=vars(progress))


@router.post("", response_model=TargetRead, status_code=status.HTTP_201_CREATED)
def create_target(
    body: TargetCreate,
    tz: str = TzQuery,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TargetRead:
    today = today_in(parse_timezone(tz))
    start = body.start_date or today
    check_dates(start, body.end_date)
    target = Target.model_validate(
        body,
        update={"user_id": user.id, "start_date": start, "start_balance": current_balance(session, user.id)},
    )
    session.add(target)
    session.commit()
    session.refresh(target)
    return read_target(session, user.id, target, today)


@router.get("", response_model=list[TargetRead])
def list_targets(
    tz: str = TzQuery, session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[TargetRead]:
    return read_targets(session, user.id, today_in(parse_timezone(tz)))


@router.get("/{target_id}", response_model=TargetRead)
def get_target(
    target_id: int,
    tz: str = TzQuery,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TargetRead:
    target = get_target_or_404(session, user.id, target_id)
    return read_target(session, user.id, target, today_in(parse_timezone(tz)))


@router.patch("/{target_id}", response_model=TargetRead)
def update_target(
    target_id: int,
    body: TargetUpdate,
    tz: str = TzQuery,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TargetRead:
    target = get_target_or_404(session, user.id, target_id)
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(field, ...) is None for field in ("name", "amount", "end_date")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="name, amount and end_date cannot be null",
        )
    check_dates(target.start_date, changes.get("end_date", target.end_date))
    target.sqlmodel_update(changes)
    session.add(target)
    session.commit()
    session.refresh(target)
    return read_target(session, user.id, target, today_in(parse_timezone(tz)))


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_target(
    target_id: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> Response:
    target = get_target_or_404(session, user.id, target_id)
    session.delete(target)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
