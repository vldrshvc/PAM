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
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.models import Category, quantize_money
from app.services.categories import UNCATEGORIZED_NAME

MAX_MERCHANT = 120
# Every amount in the app is euro; there is no conversion anywhere, so a
# receipt in another currency has to be refused rather than recorded as if
# its number were euro. Spellings a till actually prints, as well as the code.
EURO = {"EUR", "EURO", "EUROS", "€"}
# A receipt cannot be from the future; one day of slack covers a till whose
# clock disagrees with the user's timezone.
FUTURE_SLACK = dt.timedelta(days=1)


class ImageReader(Protocol):
    def read_image(
        self, system: str, user: str, image: bytes, media_type: str, max_tokens: int | None = None
    ) -> str: ...


class ReceiptUnreadableError(ValueError):
    """The photo produced no total worth showing the user."""


class ReceiptCurrencyError(ValueError):
    """The receipt is priced in a currency this app does not keep books in."""


@dataclass(frozen=True)
class ScannedReceipt:
    total: Decimal
    merchant: str | None
    date: dt.date | None
    category: Category
    fell_back: bool


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

def extract_json(answer: str) -> str:
    """The first balanced {...} in the answer.

    The model is asked for bare JSON and usually obliges, but providers wrap
    it in a code fence, or in a sentence, or put a note after it. Being strict
    about that turns a perfectly good reading of the paper into "could not
    read this receipt", so the object is picked out of whatever came back.
    Quoted braces inside strings are skipped, so a merchant called "{Spar}"
    does not confuse the scan.
    """
    depth = 0
    start = None
    in_string = False
    escaped = False
    for index, char in enumerate(answer):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return answer[start : index + 1]
    raise ReceiptUnreadableError("Could not read this receipt")


def build_user_prompt(category_names: list[str]) -> str:
    listed = "\n".join(f"- {name}" for name in category_names)
    return f"Categories:\n{listed}\n\nRead this receipt."


def parse_answer(answer: str) -> dict:
    try:
        parsed = json.loads(extract_json(answer))
    except json.JSONDecodeError as exc:
        raise ReceiptUnreadableError("Could not read this receipt") from exc
    if not isinstance(parsed, dict):
        raise ReceiptUnreadableError("Could not read this receipt")
    return parsed


def check_currency(value: object) -> None:
    """Silence is taken as euro; a stated other currency is a refusal.

    The model cannot always find a currency on a receipt, and most of this
    user's are euro, so an absent answer carries on as before. A currency it
    did read and that is not euro would be recorded as a euro amount, which is
    a wrong number in the ledger, so it stops here instead.
    """
    if not isinstance(value, str):
        return
    code = value.strip().upper()
    if code and code not in EURO:
        raise ReceiptCurrencyError(
            f"This receipt is in {code}. PAM keeps everything in euro, so add it by hand."
        )


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
    check_currency(parsed.get("currency"))
    matched = match_category(parsed.get("category"), categories)
    return ScannedReceipt(
        total=parse_total(parsed.get("total")),
        merchant=parse_merchant(parsed.get("merchant")),
        date=parse_date(parsed.get("date"), today),
        category=matched or uncategorized,
        fell_back=matched is None or matched.id == uncategorized.id,
    )
