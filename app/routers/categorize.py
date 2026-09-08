from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.database import get_session
from app.llm import LLMClient, LLMNotConfiguredError, LLMUnavailableError, get_llm_client
from app.models import Category, User
from app.schemas import CategorizeRequest, CategorizeResponse, CategoryRead
from app.security import get_current_user
from app.services.categorization import categorize

router = APIRouter(tags=["categorization"])


def llm_dependency() -> LLMClient:
    # Turns a missing key into a clean 503 instead of a 500 on every call.
    try:
        return get_llm_client()
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.post("/categorize", response_model=CategorizeResponse)
def categorize_expense(
    body: CategorizeRequest,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(llm_dependency),
    user: User = Depends(get_current_user),
) -> CategorizeResponse:
    statement = select(Category).where(Category.user_id == user.id).order_by(Category.id)
    categories = list(session.exec(statement).all())
    try:
        result = categorize(body.text, categories, llm)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return CategorizeResponse(
        category=CategoryRead.model_validate(result.category),
        amount=result.amount,
        fell_back=result.fell_back,
    )
