def test_me_returns_id_and_username(client, auth):
    assert client.get("/me", headers=auth()).json() == {"id": 1, "username": "vlad"}


def test_balance_is_opening_plus_income_minus_confirmed_expenses(client, auth):
    headers = auth()
    client.patch("/accounts/1", json={"opening_balance": 150}, headers=headers)
    client.post("/incomes", json={"amount": 500, "date": "2026-09-10"}, headers=headers)
    client.post("/incomes", json={"amount": 25.5, "date": "2026-08-01"}, headers=headers)
    client.post("/expenses", json={"price": 12.4, "date": "2026-09-10", "category_id": 2}, headers=headers)

    body = client.get("/balance", headers=headers).json()

    assert body["opening_balance"] == "150.00"
    assert body["income_total"] == "525.50"
    assert body["expense_total"] == "12.40"
    assert body["balance"] == "663.10"
    assert [(a["name"], a["balance"]) for a in body["accounts"]] == [("General", "663.10")]


def test_transfers_move_money_between_accounts_but_not_the_total(client, auth):
    headers = auth()
    cash = client.post("/accounts", json={"name": "Cash", "type": "cash"}, headers=headers).json()["id"]
    client.patch("/accounts/1", json={"opening_balance": 100}, headers=headers)
    client.post("/transfers", json={"amount": 40, "date": "2026-09-10", "from_account_id": 1, "to_account_id": cash}, headers=headers)

    body = client.get("/balance", headers=headers).json()

    assert body["balance"] == "100.00"
    assert {a["name"]: a["balance"] for a in body["accounts"]} == {"General": "60.00", "Cash": "40.00"}


def test_balance_is_per_user(client, auth):
    vlad, bob = auth("vlad"), auth("bob", "bobs-password-1")
    client.post("/incomes", json={"amount": 500, "date": "2026-09-10"}, headers=vlad)
    assert client.get("/balance", headers=bob).json()["balance"] == "0.00"


def test_requires_auth(client):
    assert client.get("/me").status_code == 401
    assert client.get("/balance").status_code == 401
