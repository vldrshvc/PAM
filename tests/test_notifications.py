"""POST /notifications: a banking notification in, a pending expense out.

Pending is the whole point: nothing here may move a balance, a budget or a
total until the user confirms it.
"""

import json

import pytest

from app.services.notifications import could_be_money


def post(client, headers, **fields):
    body = {"key": "n1", "package": "com.revolut.revolut", "text": "You spent €12.40 at SuperValu", **fields}
    return client.post("/notifications", json=body, headers=headers)


def answer(**fields) -> str:
    return json.dumps(
        {"direction": "out", "amount": "12.40", "currency": "EUR",
         "merchant": "SuperValu", "category": "Groceries", **fields}
    )


# --- a payment ---------------------------------------------------------------


def test_a_payment_becomes_a_pending_expense(client, auth, fake_llm, rates):
    headers = auth()
    client.post("/categories", json={"name": "Groceries"}, headers=headers)
    fake_llm.answer = answer()

    body = post(client, headers).json()

    assert body["outcome"] == "pending"
    assert body["expense"]["price"] == "12.40"
    assert body["expense"]["status"] == "pending"
    assert body["expense"]["description"] == "SuperValu"


def test_a_pending_expense_counts_towards_nothing(client, auth, fake_llm, rates):
    headers = auth()
    fake_llm.answer = answer()

    post(client, headers)

    summary = client.get("/summary/daily", headers=headers).json()
    assert summary["spent_today"] == "0.00"
    assert summary["balance"] == "0.00"
    assert summary["accounts"][0]["balance"] == "0.00"


def test_confirming_puts_it_in_the_books(client, auth, fake_llm, rates):
    headers = auth()
    fake_llm.answer = answer()
    expense_id = post(client, headers).json()["expense"]["id"]

    confirmed = client.post(f"/expenses/{expense_id}/confirm", headers=headers)

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert client.get("/summary/daily", headers=headers).json()["spent_today"] == "12.40"


def test_confirming_twice_is_harmless(client, auth, fake_llm, rates):
    headers = auth()
    fake_llm.answer = answer()
    expense_id = post(client, headers).json()["expense"]["id"]

    client.post(f"/expenses/{expense_id}/confirm", headers=headers)
    again = client.post(f"/expenses/{expense_id}/confirm", headers=headers)

    assert again.status_code == 200
    assert client.get("/summary/daily", headers=headers).json()["spent_today"] == "12.40"


def test_another_users_pending_expense_cannot_be_confirmed(client, auth, fake_llm, rates):
    mine = auth("vlad")
    theirs = auth("dima")
    fake_llm.answer = answer()
    expense_id = post(client, mine).json()["expense"]["id"]

    assert client.post(f"/expenses/{expense_id}/confirm", headers=theirs).status_code == 404


def test_pending_expenses_can_be_listed_on_their_own(client, auth, fake_llm, rates):
    headers = auth()
    fake_llm.answer = answer()
    post(client, headers)
    client.post("/expenses", json={"price": "5.00", "date": "2026-09-21"}, headers=headers)

    pending = client.get("/expenses?status=pending", headers=headers).json()
    confirmed = client.get("/expenses?status=confirmed", headers=headers).json()

    assert [e["price"] for e in pending] == ["12.40"]
    assert [e["price"] for e in confirmed] == ["5.00"]


# --- what must not be booked -------------------------------------------------


def test_money_arriving_is_reported_not_recorded(client, auth, fake_llm, rates):
    # "You received €850" would otherwise become an €850 spend.
    headers = auth()
    fake_llm.answer = answer(direction="in", amount="850.00", merchant="yarodev")

    body = post(client, headers, text="You received €850.00 from yarodev").json()

    assert body["outcome"] == "incoming"
    assert body["expense"] is None
    assert client.get("/expenses", headers=headers).json() == []


def test_a_notification_that_is_not_a_transaction_is_ignored(client, auth, fake_llm, rates):
    headers = auth()
    fake_llm.answer = answer(direction="none", amount=None)

    body = post(client, headers, text="Your balance is €703.53").json()

    assert body["outcome"] == "ignored"
    assert client.get("/expenses", headers=headers).json() == []


def test_a_notification_with_no_amount_never_reaches_the_model(client, auth, fake_llm, rates):
    headers = auth()

    body = post(client, headers, text="Sasha sent you a message").json()

    assert body["outcome"] == "ignored"
    assert fake_llm.calls == []


def test_the_same_notification_twice_makes_one_expense(client, auth, fake_llm, rates):
    # A listener restart re-posts everything it can still see.
    headers = auth()
    fake_llm.answer = answer()

    first = post(client, headers).json()
    second = post(client, headers).json()

    assert first["outcome"] == "pending"
    assert second["outcome"] == "duplicate"
    assert second["expense"]["id"] == first["expense"]["id"]
    assert len(client.get("/expenses", headers=headers).json()) == 1


def test_the_same_key_for_two_users_is_two_expenses(client, auth, fake_llm, rates):
    mine = auth("vlad")
    theirs = auth("dima")
    fake_llm.answer = answer()

    post(client, mine)
    post(client, theirs)

    assert len(client.get("/expenses", headers=mine).json()) == 1
    assert len(client.get("/expenses", headers=theirs).json()) == 1


# --- which account, which category -------------------------------------------


def test_the_app_that_posted_it_picks_the_account(client, auth, fake_llm, rates):
    headers = auth()
    revolut = client.post(
        "/accounts", json={"name": "Revolut", "type": "debit"}, headers=headers
    ).json()["id"]
    fake_llm.answer = answer()

    body = post(client, headers, package="com.revolut.revolut").json()

    assert body["expense"]["account_id"] == revolut


def test_an_unrecognised_app_charges_the_default_account(client, auth, fake_llm, rates):
    headers = auth()
    default = client.get("/accounts", headers=headers).json()[0]["id"]
    fake_llm.answer = answer()

    body = post(client, headers, package="ie.aib.something.unknown").json()

    assert body["expense"]["account_id"] == default


def test_an_invented_category_falls_back(client, auth, fake_llm, rates):
    headers = auth()
    fake_llm.answer = answer(category="Supermarket Runs")

    expense_id = post(client, headers).json()["expense"]["id"]
    expense = client.get(f"/expenses/{expense_id}", headers=headers).json()

    categories = client.get("/categories", headers=headers).json()
    uncategorized = next(c for c in categories if c["name"] == "uncategorized")
    assert expense["category_id"] == uncategorized["id"]


# --- foreign currency and failures -------------------------------------------


def test_a_foreign_payment_is_converted(client, auth, fake_llm, rates):
    headers = auth()
    fake_llm.answer = answer(amount="57.90", currency="RON", merchant="K-MAX")

    body = post(client, headers, text="Plata 57.90 RON la K-MAX").json()

    assert body["expense"]["price"] == "11.41"
    assert "57.90 RON" in body["note"]


def test_a_provider_failure_is_502(client, auth, unavailable_llm, rates):
    response = post(client, auth())

    assert response.status_code == 502


def test_an_unreadable_answer_is_422(client, auth, fake_llm, rates):
    fake_llm.answer = "I think they bought something?"

    assert post(client, auth()).status_code == 422


def test_posting_a_notification_needs_a_token(client, fake_llm, rates):
    assert client.post("/notifications", json={"key": "n1", "package": "x.y", "text": "€5"}).status_code == 401


# --- the filter the phone applies too ----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "You spent €12.40 at SuperValu",
        "Plata 57.90 RON la K-MAX",
        "Оплата 500 грн",
        "Payment of 1,234.56 EUR sent",
        "£8.99 charged to your card",
        "Списано 500₴",
    ],
)
def test_text_with_money_in_it_gets_through(text):
    assert could_be_money(text)


@pytest.mark.parametrize(
    "text",
    [
        "Sasha sent you a message",
        "Your card is on its way",
        "3 new emails",
        "Battery at 15%",
        "Meeting at 14:30 with Ana",
    ],
)
def test_text_with_no_money_in_it_is_dropped(text):
    assert not could_be_money(text)
