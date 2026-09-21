"""Turning what a model sent back into values that can be trusted.

Shared by the receipt scanner and the notification reader, because both ask a
model for a small JSON object and then have to decide what of it is usable.
Nothing here trusts the model: every value is validated, and anything that
does not check out is an error rather than a guess.
"""

import datetime as dt
import json
from decimal import Decimal, InvalidOperation

from app.models import Category, quantize_money

# Spellings a till or a banking app actually prints, as well as the code.
EURO = {"EUR", "EURO", "EUROS", "€"}
# One day of slack covers a clock in another timezone.
FUTURE_SLACK = dt.timedelta(days=1)


class AnswerError(ValueError):
    """The model's answer cannot be used, for a reason worth telling the user."""


def extract_json(answer: str) -> str:
    """The first balanced {...} in the answer.

    The model is asked for bare JSON and usually obliges, but providers wrap
    it in a code fence, or in a sentence, or put a note after it. Being strict
    about that turns a perfectly good reading into a refusal, so the object is
    picked out of whatever came back. Quoted braces inside strings are
    skipped, so a merchant called "{Spar}" does not confuse it.
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
    raise AnswerError("Could not read the model's answer")


def parse_object(answer: str, unreadable: str) -> dict:
    try:
        parsed = json.loads(extract_json(answer))
    except json.JSONDecodeError as exc:
        raise AnswerError(unreadable) from exc
    except AnswerError as exc:
        raise AnswerError(unreadable) from exc
    if not isinstance(parsed, dict):
        raise AnswerError(unreadable)
    return parsed


def parse_money(value: object, unreadable: str) -> Decimal:
    """A positive amount with at most two places, or nothing at all."""
    if isinstance(value, bool) or value is None:
        raise AnswerError(unreadable)
    try:
        amount = Decimal(str(value).replace(",", ".").strip().lstrip("€$£"))
    except InvalidOperation as exc:
        raise AnswerError(unreadable) from exc
    if amount <= 0:
        raise AnswerError(unreadable)
    return quantize_money(amount)


def parse_currency(value: object) -> str | None:
    """The currency an amount is in, or None for "the usual one".

    Silence means euro: a model cannot always find a currency, and most of
    these are Irish. A stated one is converted by the caller.
    """
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    return None if not code or code in EURO else code


def parse_day(value: object, today: dt.date) -> dt.date | None:
    """An ISO date that is not in the future, or None."""
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.date.fromisoformat(value.strip())
    except ValueError:
        return None
    return None if parsed > today + FUTURE_SLACK else parsed


def parse_text(value: object, cap: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())[:cap]
    return text or None


def match_category(answer: object, categories: list[Category]) -> Category | None:
    """Exact, case-insensitive, after stripping quotes and trailing stops.

    Deliberately no fuzzy matching: a near miss is a miss, and falling back to
    "uncategorized" is honest where inventing a category is not.
    """
    if not isinstance(answer, str):
        return None
    cleaned = answer.strip(" \t\n\"'`.").lower()
    for category in categories:
        if category.name.lower() == cleaned:
            return category
    return None
