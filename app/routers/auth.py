from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlmodel import Session, select

from app.database import get_session
from app.models import User
from app.schemas import TokenRead, UserCreate, UserRead
from app.security import create_access_token, hash_password, verify_password
from app.services.categories import seed_default_categories

router = APIRouter(tags=["auth"])


def find_user_by_username(session: Session, username: str) -> User | None:
    statement = select(User).where(func.lower(User.username) == username.lower())
    return session.exec(statement).first()


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, session: Session = Depends(get_session)) -> User:
    if find_user_by_username(session, body.username) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'Username "{body.username}" is taken',
        )
    user = User(username=body.username, hashed_password=hash_password(body.password))
    session.add(user)
    # flush assigns user.id without committing, so the default categories
    # land in the same transaction: no user without an "uncategorized".
    session.flush()
    seed_default_categories(session, user.id)
    session.commit()
    session.refresh(user)
    return user


@router.post("/token", response_model=TokenRead)
def login(
    form: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)
) -> TokenRead:
    user = find_user_by_username(session, form.username)
    # Same message for unknown user and wrong password: don't reveal which.
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenRead(access_token=create_access_token(user.id), token_type="bearer")
