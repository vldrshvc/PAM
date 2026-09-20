"""POST /receipts/scan: read a photo, suggest an expense, store nothing.

The unit tests below the endpoint ones cover the parsing, because that is
where a model's answer is turned into money and a date.
"""

import datetime as dt
import json
from decimal import Decimal

import pytest

from app.models import Category
from app.services.receipts import (
    ReceiptUnreadableError,
    match_category,
    parse_answer,
    parse_date,
    parse_merchant,
    parse_total,
)

PHOTO = ("receipt.jpg", b"not really a jpeg, the model is faked", "image/jpeg")


def post_scan(client, headers, photo=PHOTO, **params):
    return client.post("/receipts/scan", files={"photo": photo}, headers=headers, params=params)


def answer(**fields) -> str:
    return json.dumps({"total": "12.40", "merchant": "SuperValu", "date": None, "category": "Groceries", **fields})


# --- the endpoint ------------------------------------------------------------


def test_scan_suggests_an_expense(client, auth, fake_vision):
    headers = auth()
    client.post("/categories", json={"name": "Groceries"}, headers=headers)
    fake_vision.answer = answer(date="2026-09-18")

    response = post_scan(client, headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == "12.40"
    assert body["merchant"] == "SuperValu"
    assert body["date"] == "2026-09-18"
    assert body["category"]["name"] == "Groceries"
    assert body["fell_back"] is False
    # the photo reached the model exactly as uploaded, and only once
    assert fake_vision.images == [(PHOTO[1], "image/jpeg")]


def test_scan_creates_nothing(client, auth, fake_vision):
    headers = auth()
    fake_vision.answer = answer(category="uncategorized")

    post_scan(client, headers)

    assert client.get("/expenses", headers=headers).json() == []


def test_an_invented_category_falls_back(client, auth, fake_vision):
    headers = auth()
    fake_vision.answer = answer(category="Supermarket Runs")

    body = post_scan(client, headers).json()

    assert body["category"]["name"] == "uncategorized"
    assert body["fell_back"] is True


def test_the_users_own_categories_are_offered_to_the_model(client, auth, fake_vision):
    headers = auth()
    client.post("/categories", json={"name": "Site materials"}, headers=headers)
    fake_vision.answer = answer(category="Site materials")

    body = post_scan(client, headers).json()

    _, prompt = fake_vision.calls[0]
    assert "- Site materials" in prompt
    assert body["category"]["name"] == "Site materials"


def test_another_users_categories_are_not_offered(client, auth, fake_vision):
    mine = auth("vlad")
    theirs = auth("dima")
    client.post("/categories", json={"name": "Someone elses"}, headers=theirs)
    fake_vision.answer = answer(category="Someone elses")

    body = post_scan(client, mine).json()

    _, prompt = fake_vision.calls[0]
    assert "Someone elses" not in prompt
    assert body["category"]["name"] == "uncategorized"


def test_an_unreadable_total_is_422(client, auth, fake_vision):
    headers = auth()
    fake_vision.answer = answer(total=None)

    response = post_scan(client, headers)

    assert response.status_code == 422
    assert "total" in response.json()["detail"]


def test_a_non_json_answer_is_422(client, auth, fake_vision):
    headers = auth()
    fake_vision.answer = "It looks like a receipt from SuperValu for about twelve euro."

    assert post_scan(client, headers).status_code == 422


def test_a_photo_that_is_not_an_image_is_415(client, auth, fake_vision):
    response = post_scan(client, auth(), photo=("notes.txt", b"12.40", "text/plain"))

    assert response.status_code == 415
    assert fake_vision.images == []


def test_a_photo_over_the_limit_is_413(client, auth, fake_vision, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "receipt_max_bytes", 100)

    response = post_scan(client, auth(), photo=("big.jpg", b"x" * 101, "image/jpeg"))

    assert response.status_code == 413
    assert fake_vision.images == []


def test_an_empty_photo_is_422(client, auth, fake_vision):
    assert post_scan(client, auth(), photo=("empty.jpg", b"", "image/jpeg")).status_code == 422


def test_a_provider_failure_is_502(client, auth, fake_vision):
    from app.llm import LLMUnavailableError

    fake_vision.error = LLMUnavailableError("LLM provider timed out")

    response = post_scan(client, auth())

    assert response.status_code == 502
    assert response.json()["detail"] == "LLM provider timed out"


def test_scanning_needs_a_token(client, fake_vision):
    assert client.post("/receipts/scan", files={"photo": PHOTO}).status_code == 401


# --- parsing -----------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [("12.40", "12.40"), (12.4, "12.40"), ("12,40", "12.40"), ("€12.40", "12.40"), (" 7 ", "7.00"), ("12.404", "12.40")],
)
def test_a_total_is_read_as_money(raw, expected):
    assert parse_total(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "free", "0", "-3.00", True])
def test_a_total_that_is_not_money_is_unreadable(raw):
    with pytest.raises(ReceiptUnreadableError):
        parse_total(raw)


def test_a_fenced_json_answer_is_still_read():
    assert parse_answer('```json\n{"total": "5.00"}\n```') == {"total": "5.00"}


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '"just a string"'])
def test_an_answer_that_is_not_an_object_is_unreadable(raw):
    with pytest.raises(ReceiptUnreadableError):
        parse_answer(raw)


def test_a_date_on_the_receipt_is_kept():
    assert parse_date("2026-09-18", dt.date(2026, 9, 20)) == dt.date(2026, 9, 18)


def test_a_date_from_the_future_is_dropped():
    # One day of slack for a till clock in another timezone; beyond that the
    # model misread it, and today is a better guess than a wrong date.
    today = dt.date(2026, 9, 20)
    assert parse_date("2026-09-21", today) == dt.date(2026, 9, 21)
    assert parse_date("2026-09-22", today) is None


@pytest.mark.parametrize("raw", [None, 42, "18/09/2026", "yesterday"])
def test_an_unusable_date_is_dropped(raw):
    assert parse_date(raw, dt.date(2026, 9, 20)) is None


def test_a_merchant_is_tidied_and_capped():
    assert parse_merchant("  SuperValu\n Rathmines ") == "SuperValu Rathmines"
    assert len(parse_merchant("x" * 500)) == 120
    assert parse_merchant("   ") is None
    assert parse_merchant(None) is None


def test_a_category_must_match_exactly():
    categories = [Category(id=1, name="Groceries", user_id=1)]
    assert match_category("groceries", categories) is not None
    assert match_category('"Groceries".', categories) is not None
    assert match_category("Grocery", categories) is None
    assert match_category(None, categories) is None
