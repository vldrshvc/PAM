"""Turn a photo of a receipt into a suggested expense.

The model reads the picture; this module decides what of its answer is
usable. Nothing it returns is written anywhere: the caller gets a suggestion
to put in the form, and the user confirms it like any other expense. Same
rule as the text categorizer — the category must match the user's own list
exactly, and a near miss is a miss.

The total is the one number we do take from the model, because reading it
off the paper is the whole point. It is still validated as money: a positive
decimal with at most two places, or the scan is treated as unreadable.
"""

import datetime as dt
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.models import Category, quantize_money
from app.services.categories import UNCATEGORIZED_NAME

MAX_MERCHANT = 120
# A receipt cannot be from the future; one day of slack covers a till whose
# clock disagrees with the user's timezone.
FUTURE_SLACK = dt.timedelta(days=1)


class ImageReader(Protocol):
    def read_image(
        self, system: str, user: str, image: bytes, media_type: str, max_tokens: int = 200
    ) -> str: ...


class ReceiptUnreadableError(ValueError):
    """The photo produced no total worth showing the user."""


@dataclass(frozen=True)
class ScannedReceipt:
    total: Decimal
    merchant: str | None
    date: dt.date | None
    category: Category
    fell_back: bool


SYSTEM_PROMPT = (
    "You read photographs of shop receipts. Reply with one JSON object and "
    "nothing else, with exactly these keys: "
    '"total" (the final amount actually paid, including tax and after any '
    'discount, as a plain number such as 12.40), "merchant" (the shop name as '
    'printed, or null), "date" (the purchase date as YYYY-MM-DD, or null if it '
    'is not legible), and "category" (one name copied verbatim from the list '
    "you are given). Never guess a total you cannot read: if the total is not "
    "legible, set it to null."
)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def build_user_prompt(category_names: list[str]) -> str:
    listed = "\n".join(f"- {name}" for name in category_names)
    return f"Categories:\n{listed}\n\nRead this receipt."


def parse_answer(answer: str) -> dict:
    """The model was asked for bare JSON; accept it wrapped in a code fence too."""
    try:
        parsed = json.loads(_FENCE.sub("", answer).strip())
    except json.JSONDecodeError as exc:
        raise ReceiptUnreadableError("Could not read this receipt") from exc
    if not isinstance(parsed, dict):
        raise ReceiptUnreadableError("Could not read this receipt")
    return parsed


def parse_total(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ReceiptUnreadableError("Could not read a total on this receipt")
    try:
        total = Decimal(str(value).replace(",", ".").strip().lstrip("€$£"))
    except InvalidOperation as exc:
        raise ReceiptUnreadableError("Could not read a total on this receipt") from exc
    if total <= 0:
        raise ReceiptUnreadableError("Could not read a total on this receipt")
    return quantize_money(total)


def parse_date(value: object, today: dt.date) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.date.fromisoformat(value.strip())
    except ValueError:
        return None
    return None if parsed > today + FUTURE_SLACK else parsed


def parse_merchant(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    merchant = " ".join(value.split())[:MAX_MERCHANT]
    return merchant or None


def match_category(answer: object, categories: list[Category]) -> Category | None:
    if not isinstance(answer, str):
        return None
    cleaned = answer.strip(" \t\n\"'`.").lower()
    for category in categories:
        if category.name.lower() == cleaned:
            return category
    return None


def scan(image: bytes, media_type: str, categories: list[Category], reader: ImageReader, today: dt.date) -> ScannedReceipt:
    uncategorized = next(c for c in categories if c.name == UNCATEGORIZED_NAME)
    answer = reader.read_image(
        SYSTEM_PROMPT,
        build_user_prompt([c.name for c in categories]),
        image,
        media_type,
    )
    parsed = parse_answer(answer)
    matched = match_category(parsed.get("category"), categories)
    return ScannedReceipt(
        total=parse_total(parsed.get("total")),
        merchant=parse_merchant(parsed.get("merchant")),
        date=parse_date(parsed.get("date"), today),
        category=matched or uncategorized,
        fell_back=matched is None or matched.id == uncategorized.id,
    )
