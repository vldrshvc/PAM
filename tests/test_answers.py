"""Reading a model's answer: pick out the JSON, then check every value.

Shared by the receipt scanner and the notification reader, so it is tested
once here rather than twice through their endpoints.
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.models import Category
from app.services.answers import (
    AnswerError,
    extract_json,
    match_category,
    parse_currency,
    parse_day,
    parse_money,
    parse_object,
    parse_text,
)


def parse_text_capped(value):
    return parse_text(value, 120)


def parse_object_or_fail(answer):
    return parse_object(answer, "unreadable")


# --- parsing -----------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [("12.40", "12.40"), (12.4, "12.40"), ("12,40", "12.40"), ("€12.40", "12.40"), (" 7 ", "7.00"), ("12.404", "12.40")],
)
def test_a_total_is_read_as_money(raw, expected):
    assert parse_money(raw, "no total") == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "free", "0", "-3.00", True])
def test_a_total_that_is_not_money_is_unreadable(raw):
    with pytest.raises(AnswerError):
        parse_money(raw, "no total")


@pytest.mark.parametrize("raw, expected", [("RON", "RON"), ("ron", "RON"), (" gbp ", "GBP")])
def test_a_foreign_currency_is_read_as_its_code(raw, expected):
    assert parse_currency(raw) == expected


@pytest.mark.parametrize("raw", ["EUR", "eur", "Euro", "\u20ac", "", None, 42])
def test_euro_or_no_answer_means_no_conversion(raw):
    assert parse_currency(raw) is None


def test_the_first_json_object_is_picked_out_of_the_answer():
    assert extract_json('note {"a": 1} tail') == '{"a": 1}'
    assert extract_json('{"m": "Spar {city}"}') == '{"m": "Spar {city}"}'
    assert extract_json('{"m": "a \\" b {"}') == '{"m": "a \\" b {"}'
    assert extract_json('{"a": {"b": 2}} then {"c": 3}') == '{"a": {"b": 2}}'


def test_an_answer_with_no_object_at_all_is_unreadable():
    with pytest.raises(AnswerError):
        extract_json("no braces here")


def test_a_fenced_json_answer_is_still_read():
    assert parse_object_or_fail('```json\n{"total": "5.00"}\n```') == {"total": "5.00"}


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '"just a string"', "{broken"])
def test_an_answer_that_is_not_an_object_is_unreadable(raw):
    with pytest.raises(AnswerError):
        parse_object_or_fail(raw)


def test_a_date_on_the_receipt_is_kept():
    assert parse_day("2026-09-18", dt.date(2026, 9, 20)) == dt.date(2026, 9, 18)


def test_a_date_from_the_future_is_dropped():
    # One day of slack for a till clock in another timezone; beyond that the
    # model misread it, and today is a better guess than a wrong date.
    today = dt.date(2026, 9, 20)
    assert parse_day("2026-09-21", today) == dt.date(2026, 9, 21)
    assert parse_day("2026-09-22", today) is None


@pytest.mark.parametrize("raw", [None, 42, "18/09/2026", "yesterday"])
def test_an_unusable_date_is_dropped(raw):
    assert parse_day(raw, dt.date(2026, 9, 20)) is None


def test_a_merchant_is_tidied_and_capped():
    assert parse_text_capped("  SuperValu\n Rathmines ") == "SuperValu Rathmines"
    assert len(parse_text_capped("x" * 500)) == 120
    assert parse_text_capped("   ") is None
    assert parse_text_capped(None) is None


def test_a_category_must_match_exactly():
    categories = [Category(id=1, name="Groceries", user_id=1)]
    assert match_category("groceries", categories) is not None
    assert match_category('"Groceries".', categories) is not None
    assert match_category("Grocery", categories) is None
    assert match_category(None, categories) is None
