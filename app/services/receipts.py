"""Turn a photo of a receipt into a suggested expense.

The model reads the picture; this module decides what of its answer is
usable. Nothing it returns is written anywhere: the caller gets a suggestion
to put in the form, and the user confirms it like any other expense.

The total is the one number taken from the model, because reading it off the
paper is the whole point. It is still validated as money, and a receipt
priced in another currency is converted at a central bank's rate rather than
recorded as if its number were euro.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.models import Category
from app.services.answers import (
    AnswerError,
    match_category,
    parse_currency,
    parse_day,
    parse_money,
    parse_object,
    parse_text,
)
from app.services.categories import UNCATEGORIZED_NAME
from app.services.fx import RateLookup, to_euro

MAX_MERCHANT = 120
UNREADABLE = "Could not read this receipt"
NO_TOTAL = "Could not read a total on this receipt"


class ImageReader(Protocol):
    def read_image(
        self, system: str, user: str, image: bytes, media_type: str, max_tokens: int | None = None
    ) -> str: ...


@dataclass(frozen=True)
class Conversion:
    """What a foreign total was before it became euro, so the user can check."""

    amount: Decimal
    currency: str
    per_euro: Decimal
    rate_date: dt.date
    # The central bank the rate came from.
    source: str


@dataclass(frozen=True)
class ScannedReceipt:
    # Always euro: the ledger has one currency and this is it.
    total: Decimal
    merchant: str | None
    date: dt.date | None
    category: Category
    fell_back: bool
    # None when the receipt was already in euro.
    converted: Conversion | None = None


SYSTEM_PROMPT = (
    "You read photographs of shop receipts. A receipt may be in any language, "
    "and the total line may be labelled TOTAL, SUMA, SUMME, TOTALE, ИТОГО or "
    "similar. Reply with one JSON object and nothing else, with exactly these "
    'keys: "total" (the final amount actually paid, including tax and after '
    'any discount, as a plain number such as 12.40), "currency" (the currency '
    "the receipt is priced in, as a three-letter code such as EUR, RON or GBP, "
    'copied from what is printed; null if nothing says), "merchant" (the shop '
    'name as printed, or null), "date" (the purchase date as YYYY-MM-DD, '
    'converting from whatever format is printed, or null if it is not '
    'legible), and "category" (one name copied verbatim from the list you are '
    "given). Never guess a total you cannot read: if the total is not legible, "
    "set it to null."
)


def build_user_prompt(category_names: list[str]) -> str:
    listed = "\n".join(f"- {name}" for name in category_names)
    return f"Categories:\n{listed}\n\nRead this receipt."


def scan(
    image: bytes,
    media_type: str,
    categories: list[Category],
    reader: ImageReader,
    today: dt.date,
    rates: RateLookup,
) -> ScannedReceipt:
    uncategorized = next(c for c in categories if c.name == UNCATEGORIZED_NAME)
    answer = reader.read_image(
        SYSTEM_PROMPT,
        build_user_prompt([c.name for c in categories]),
        image,
        media_type,
    )
    parsed = parse_object(answer, UNREADABLE)
    matched = match_category(parsed.get("category"), categories)
    total = parse_money(parsed.get("total"), NO_TOTAL)
    date = parse_day(parsed.get("date"), today)

    converted = None
    currency = parse_currency(parsed.get("currency"))
    if currency is not None:
        # The rate that applied the day the receipt was printed, not the day
        # it was photographed.
        rate = rates.rate_on(currency, date or today)
        converted = Conversion(
            amount=total,
            currency=currency,
            per_euro=rate.per_euro,
            rate_date=rate.published,
            source=rate.source,
        )
        total = to_euro(total, rate)

    return ScannedReceipt(
        total=total,
        merchant=parse_text(parsed.get("merchant"), MAX_MERCHANT),
        date=date,
        category=matched or uncategorized,
        fell_back=matched is None or matched.id == uncategorized.id,
        converted=converted,
    )


# The router maps this to a 422; kept as a name so the meaning reads at the
# call site.
ReceiptUnreadableError = AnswerError
