"""Turn a banking notification into a pending expense.

The phone never decides what a notification means; it only decides whether a
notification could possibly be about money, and sends the ones that could.
Everything below runs on the server.

Three rules shape this:

* **Nothing is ever recorded as fact.** What comes out is a `pending` expense,
  which counts towards no balance, no budget and no total until the user
  confirms it. A notification is a rumour about money, not a receipt.
* **Money in is not an expense.** "You received €50" through this path would
  otherwise become a €50 spend. The model is asked which way the money went,
  and only "out" produces anything.
* **The same notification must not land twice.** A phone re-posts when a
  notification is updated or the listener restarts, so every one carries a key
  and the key is unique per user.
"""

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.models import Category
from app.services.answers import (
    AnswerError,
    match_category,
    parse_currency,
    parse_money,
    parse_object,
    parse_text,
)
from app.services.categories import UNCATEGORIZED_NAME
from app.services.fx import RateLookup, to_euro

MAX_MERCHANT = 120
UNREADABLE = "Could not read that notification"
NO_AMOUNT = "Could not read an amount in that notification"

# Money out, money in, or neither. Anything but OUT creates nothing.
OUT, IN, NONE = "out", "in", "none"

# The same gate the phone applies before sending anything: a number that looks
# like an amount, next to a currency marker. Cheap, and it keeps both a wasted
# token and a stranger's private notification out of the model.
_AMOUNT = r"\d{1,3}(?:[ ,.]\d{3})*(?:[.,]\d{2})?"
LOOKS_LIKE_MONEY = re.compile(
    rf"(?:[€$£₴]\s*{_AMOUNT})|(?:{_AMOUNT}\s*(?:[€$£₴]|eur|euro|usd|gbp|ron|lei|pln|uah|грн))",
    re.IGNORECASE,
)


class Completer(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 30) -> str: ...


@dataclass(frozen=True)
class ReadNotification:
    """What the model made of it. `amount` is euro; None when nothing to book."""

    direction: str
    amount: Decimal | None
    merchant: str | None
    category: Category | None
    fell_back: bool
    converted_from: tuple[Decimal, str] | None = None
    rate_note: str | None = None


SYSTEM_PROMPT = (
    "You read notifications from banking and payment apps. Reply with one JSON "
    'object and nothing else, with exactly these keys: "direction" — "out" if '
    'money left the account, "in" if money arrived, "none" if the notification '
    "is not about a completed transaction at all (a balance update, a card "
    "delivery, a promotion, a login alert, a request to pay); "
    '"amount" — the amount of the transaction as a plain number, or null; '
    '"currency" — its three-letter code if one is shown, else null; '
    '"merchant" — who was paid or who paid, as written, or null; and '
    '"category" — one name copied verbatim from the list you are given, or '
    "null when the direction is not \"out\". Never invent an amount that is "
    "not in the text."
)


def build_user_prompt(text: str, category_names: list[str]) -> str:
    listed = "\n".join(f"- {name}" for name in category_names)
    return f"Categories:\n{listed}\n\nNotification: {text.strip()}\n\nJSON:"


def could_be_money(text: str) -> bool:
    """Whether it is worth asking a model about this at all."""
    return bool(LOOKS_LIKE_MONEY.search(text))


def read(
    text: str,
    categories: list[Category],
    llm: Completer,
    today: dt.date,
    rates: RateLookup,
) -> ReadNotification:
    uncategorized = next(c for c in categories if c.name == UNCATEGORIZED_NAME)
    answer = llm.complete(
        SYSTEM_PROMPT,
        build_user_prompt(text, [c.name for c in categories]),
        max_tokens=400,
    )
    parsed = parse_object(answer, UNREADABLE)

    direction = parsed.get("direction")
    direction = direction.strip().lower() if isinstance(direction, str) else NONE
    if direction != OUT:
        # Money in and everything else are reported, not recorded. Incomes
        # are a separate kind with a source the user picks, and guessing one
        # from a push notification would be worse than asking.
        return ReadNotification(
            direction=direction if direction in (IN, NONE) else NONE,
            amount=None,
            merchant=parse_text(parsed.get("merchant"), MAX_MERCHANT),
            category=None,
            fell_back=False,
        )

    amount = parse_money(parsed.get("amount"), NO_AMOUNT)
    converted_from = None
    rate_note = None
    currency = parse_currency(parsed.get("currency"))
    if currency is not None:
        # A notification is about today, so today's rate is the right one.
        rate = rates.rate_on(currency, today)
        converted_from = (amount, currency)
        rate_note = f"{rate.source} {rate.published:%-d %b}, {rate.per_euro}/€"
        amount = to_euro(amount, rate)

    matched = match_category(parsed.get("category"), categories)
    return ReadNotification(
        direction=OUT,
        amount=amount,
        merchant=parse_text(parsed.get("merchant"), MAX_MERCHANT),
        category=matched or uncategorized,
        fell_back=matched is None or matched.id == uncategorized.id,
        converted_from=converted_from,
        rate_note=rate_note,
    )


# The router maps this to a 422.
NotificationUnreadableError = AnswerError
