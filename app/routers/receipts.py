from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlmodel import Session, select

from app.config import settings
from app.database import get_session
from app.ecb import get_rates
from app.nbu import HryvniaRates
from app.llm import LLMClient, LLMNotConfiguredError, LLMUnavailableError, get_vision_client
from app.models import Category, User
from app.routers.summary import TzQuery, parse_timezone
from app.schemas import CategoryRead, ConversionRead, ReceiptScanResponse
from app.security import get_current_user
from app.services.budget import today_in
from app.services.fx import Chain, EcbRates, RateLookup, RateUnavailableError
from app.services.receipts import ReceiptUnreadableError, scan

router = APIRouter(prefix="/receipts", tags=["receipts"])

# What the vision providers accept, and what a phone camera produces once the
# client has downscaled it. Anything else is rejected before a token is spent.
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


def vision_dependency() -> LLMClient:
    # Turns a missing key into a clean 503 instead of a 500 on every call.
    try:
        return get_vision_client()
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


def rates_dependency() -> RateLookup:
    """Where a euro rate comes from: the ECB, then the hryvnia's own bank.

    The ECB's table is fetched once and cached, and a stale copy is served
    when it is down, because a day-old reference rate beats refusing to read
    the receipt. The NBU is only asked about the hryvnia, and only when the
    ECB has said it does not quote the currency at all.
    """
    try:
        return Chain((EcbRates(get_rates()), HryvniaRates()))
    except RateUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/scan", response_model=ReceiptScanResponse)
async def scan_receipt(
    photo: UploadFile = File(description="A photograph of a receipt"),
    tz: str = TzQuery,
    session: Session = Depends(get_session),
    vision: LLMClient = Depends(vision_dependency),
    rates: RateLookup = Depends(rates_dependency),
    user: User = Depends(get_current_user),
) -> ReceiptScanResponse:
    """Read a receipt and suggest an expense. Creates nothing.

    The photo is held in memory for the length of this call and then dropped:
    it is never written to disk and never stored in the database.
    """
    media_type = (photo.content_type or "").split(";")[0].strip().lower()
    if media_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Send a photo as one of: {', '.join(sorted(ALLOWED_TYPES))}",
        )
    # Read one byte past the limit so an oversized upload is refused rather
    # than silently truncated.
    image = await photo.read(settings.receipt_max_bytes + 1)
    if len(image) > settings.receipt_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Photo must be under {settings.receipt_max_bytes // 1_000_000} MB",
        )
    if not image:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The photo was empty"
        )

    statement = select(Category).where(Category.user_id == user.id).order_by(Category.id)
    categories = list(session.exec(statement).all())
    try:
        result = scan(image, media_type, categories, vision, today_in(parse_timezone(tz)), rates)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except (RateUnavailableError, ReceiptUnreadableError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return ReceiptScanResponse(
        total=result.total,
        merchant=result.merchant,
        date=result.date,
        category=CategoryRead.model_validate(result.category),
        fell_back=result.fell_back,
        converted=ConversionRead.model_validate(result.converted, from_attributes=True)
        if result.converted
        else None,
    )
