"""Turn free text like "SuperValu €12.40" into a category and an amount.

The model is only ever asked to choose from the caller-supplied list, and
its answer is validated against that same list. Anything that does not
match exactly falls back to "uncategorized". No LLM output reaches the
database unverified.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.models import Category, quantize_money
from app.services.categories import UNCATEGORIZED_NAME


class Completer(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 30) -> str: ...


@dataclass(frozen=True)
class Categorization:
    category: Category
    amount: Decimal | None
    fell_back: bool


SYSTEM_PROMPT = (
    "You classify personal expenses. You will be given an expense description "
    "and a list of category names. Reply with exactly one category name copied "
    "verbatim from the list, and nothing else: no punctuation, no explanation. "
    f'If nothing fits, reply "{UNCATEGORIZED_NAME}".'
)

_NUMBER = r"\d+(?:[.,]\d{1,2})?"
# A number next to a currency marker wins over a bare number, so
# "2 coffees €7" parses as 7, not 2.
_CURRENCY_AMOUNT = re.compile(
    rf"(?:[€$£]\s*({_NUMBER}))|(?:({_NUMBER})\s*(?:€|\$|£|eur|euro|euros|usd|gbp)\b)",
    re.IGNORECASE,
)
_BARE_AMOUNT = re.compile(_NUMBER)


def build_user_prompt(text: str, category_names: list[str]) -> str:
    listed = "\n".join(f"- {name}" for name in category_names)
    return f"Categories:\n{listed}\n\nExpense: {text.strip()}\n\nCategory:"


def parse_amount(text: str) -> Decimal | None:
    match = _CURRENCY_AMOUNT.search(text)
    raw = (match.group(1) or match.group(2)) if match else None
    if raw is None:
        bare = _BARE_AMOUNT.search(text)
        raw = bare.group(0) if bare else None
    if raw is None:
        return None
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None
    return quantize_money(value) if value > 0 else None


def match_category(answer: str, categories: list[Category]) -> Category | None:
    """Exact, case-insensitive match after stripping quotes and trailing
    punctuation. Deliberately no fuzzy matching: a near miss is a miss."""
    cleaned = answer.strip(" \t\n\"'`.").lower()
    for category in categories:
        if category.name.lower() == cleaned:
            return category
    return None


def categorize(text: str, categories: list[Category], llm: Completer) -> Categorization:
    uncategorized = next(c for c in categories if c.name == UNCATEGORIZED_NAME)
    answer = llm.complete(SYSTEM_PROMPT, build_user_prompt(text, [c.name for c in categories]))
    matched = match_category(answer, categories)
    return Categorization(
        category=matched or uncategorized,
        amount=parse_amount(text),
        fell_back=matched is None or matched.id == uncategorized.id,
    )
