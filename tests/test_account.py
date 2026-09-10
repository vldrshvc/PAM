def test_me_starts_with_zero_opening_balance(client, auth):
    assert client.get("/me", headers=auth()).json() == {"id": 1, "username": "vlad", "opening_balance": "0.00"}


def test_opening_balance_can_be_set_and_negative(client, auth):
    headers = auth()
    assert client.patch("/me", json={"opening_balance": 150}, headers=headers).json()["opening_balance"] == "150.00"
    assert client.patch("/me", json={"opening_balance": -20.5}, headers=headers).json()["opening_balance"] == "-20.50"
    assert client.patch("/me", json={"opening_balance": 1.234}, headers=headers).status_code == 422


def test_balance_is_opening_plus_income_minus_confirmed_expenses(client, auth):
    headers = auth()
    client.patch("/me", json={"opening_balance": 150}, headers=headers)
    client.post("/incomes", json={"amount": 500, "date": "2026-09-10"}, headers=headers)
    client.post("/incomes", json={"amount": 25.5, "date": "2026-08-01"}, headers=headers)
    client.post("/expenses", json={"price": 12.4, "date": "2026-09-10", "category_id": 2}, headers=headers)

    body = client.get("/balance", headers=headers).json()

    assert body == {"opening_balance": "150.00", "income_total": "525.50", "expense_total": "12.40", "balance": "663.10"}


def test_balance_is_per_user(client, auth):
    vlad, bob = auth("vlad"), auth("bob", "bobs-password-1")
    client.post("/incomes", json={"amount": 500, "date": "2026-09-10"}, headers=vlad)
    assert client.get("/balance", headers=bob).json()["balance"] == "0.00"


def test_requires_auth(client):
    assert client.get("/me").status_code == 401
    assert client.get("/balance").status_code == 401
