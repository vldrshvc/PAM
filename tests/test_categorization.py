"""LLM categorization: the pure logic and the fallback path through the API."""

from decimal import Decimal

import pytest

from app.models import Category
from app.services.categorization import (
    SYSTEM_PROMPT,
    build_user_prompt,
    categorize,
    match_category,
    parse_amount,
)
from tests.conftest import FakeLLM

CATEGORIES = [
    Category(id=1, user_id=1, name="uncategorized"),
    Category(id=2, user_id=1, name="Groceries"),
    Category(id=3, user_id=1, name="Eating out"),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SuperValu €12.40", "12.40"),
        ("12,40 EUR lidl", "12.40"),
        ("2 coffees €7", "7.00"),  # currency-adjacent number beats the bare one
        ("taxi 15.5", "15.50"),
        ("$4.99 app", "4.99"),
        ("bus 3", "3.00"),
        ("€0 free sample", None),
        ("just words", None),
    ],
)
def test_parse_amount(text: str, expected: str | None):
    result = parse_amount(text)
    assert result == (None if expected is None else Decimal(expected))


@pytest.mark.parametrize(
    ("answer", "expected_id"),
    [
        ("Groceries", 2),
        (" groceries. ", 2),
        ('"Eating out".', 3),
        ("EATING OUT", 3),
        ("Pizza Palace", None),  # invented category
        ("Groceries, Eating out", None),  # two answers is no answer
        ("", None),
    ],
)
def test_match_category_is_exact_after_cleanup(answer: str, expected_id: int | None):
    match = match_category(answer, CATEGORIES)
    assert (match.id if match else None) == expected_id


def test_prompt_lists_live_categories_and_constrains_output():
    prompt = build_user_prompt("SuperValu €12.40", [c.name for c in CATEGORIES])
    assert "- Groceries" in prompt and "- Eating out" in prompt and "- uncategorized" in prompt
    assert "SuperValu €12.40" in prompt
    assert "exactly one category name" in SYSTEM_PROMPT


def test_categorize_uses_model_answer_when_it_matches():
    llm = FakeLLM()
    llm.answer = "Groceries"
    result = categorize("SuperValu €12.40", CATEGORIES, llm)
    assert result.category.id == 2
    assert result.amount == Decimal("12.40")
    assert result.fell_back is False


def test_categorize_falls_back_when_model_invents_a_category():
    llm = FakeLLM()
    llm.answer = "Pizza Palace"
    result = categorize("pizza 18,50", CATEGORIES, llm)
    assert result.category.name == "uncategorized"
    assert result.amount == Decimal("18.50")
    assert result.fell_back is True


def test_categorize_falls_back_on_empty_answer():
    llm = FakeLLM()
    llm.answer = ""
    result = categorize("bus ticket", CATEGORIES, llm)
    assert result.category.name == "uncategorized"
    assert result.amount is None
    assert result.fell_back is True


def test_categorize_reports_fallback_when_model_picks_uncategorized():
    llm = FakeLLM()
    llm.answer = "uncategorized"
    result = categorize("qwerty", CATEGORIES, llm)
    assert result.category.name == "uncategorized"
    assert result.fell_back is True


# --- through the API -------------------------------------------------------


def test_endpoint_returns_users_own_category(client, auth, fake_llm):
    headers = auth()
    fake_llm.answer = "Groceries"

    response = client.post("/categorize", json={"text": "SuperValu €12.40"}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["category"]["name"] == "Groceries"
    assert body["amount"] == "12.40"
    assert body["fell_back"] is False
    # The model saw this user's live category list, not a hardcoded one.
    _, user_prompt = fake_llm.calls[0]
    assert "- Groceries" in user_prompt and "- uncategorized" in user_prompt


def test_endpoint_sees_custom_categories(client, auth, fake_llm):
    headers = auth()
    client.post("/categories", json={"name": "Coffee"}, headers=headers)
    fake_llm.answer = "coffee"

    response = client.post("/categorize", json={"text": "flat white 3,80"}, headers=headers)

    assert response.json()["category"]["name"] == "Coffee"
    assert "- Coffee" in fake_llm.calls[0][1]


def test_endpoint_falls_back_to_uncategorized(client, auth, fake_llm):
    headers = auth()
    fake_llm.answer = "Pizza Palace"

    body = client.post("/categorize", json={"text": "pizza €18"}, headers=headers).json()

    assert body["category"]["name"] == "uncategorized"
    assert body["category"]["id"] == 1
    assert body["fell_back"] is True


def test_endpoint_never_writes_an_expense(client, auth, fake_llm):
    headers = auth()
    fake_llm.answer = "Groceries"
    client.post("/categorize", json={"text": "SuperValu €12.40"}, headers=headers)
    assert client.get("/expenses", headers=headers).json() == []


def test_endpoint_maps_provider_failure_to_502(client, auth, unavailable_llm):
    response = client.post("/categorize", json={"text": "SuperValu €12.40"}, headers=auth())
    assert response.status_code == 502
    assert response.json()["detail"] == "LLM provider timed out"


def test_endpoint_returns_503_when_no_key_configured(client, auth, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", None)
    response = client.post("/categorize", json={"text": "SuperValu €12.40"}, headers=auth())
    assert response.status_code == 503
    assert "LLM_API_KEY" in response.json()["detail"]


def test_endpoint_rejects_blank_text(client, auth, fake_llm):
    assert client.post("/categorize", json={"text": ""}, headers=auth()).status_code == 422


def test_endpoint_requires_auth(client, fake_llm):
    assert client.post("/categorize", json={"text": "x"}).status_code == 401
