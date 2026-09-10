def test_registration_seeds_general_account(client, auth):
    body = client.get("/accounts", headers=auth()).json()
    assert body == [{"id": 1, "name": "General", "type": "debit", "subtype": None, "opening_balance": "0.00", "balance": "0.00"}]


def test_create_account_with_type_subtype_and_opening_balance(client, auth):
    response = client.post(
        "/accounts", json={"name": "Revolut", "type": "debit", "subtype": "Revolut", "opening_balance": 200}, headers=auth()
    )
    assert response.status_code == 201
    assert response.json() == {"id": 2, "name": "Revolut", "type": "debit", "subtype": "Revolut", "opening_balance": "200.00"}


def test_create_account_validation(client, auth):
    headers = auth()
    assert client.post("/accounts", json={"name": "  ", "type": "cash"}, headers=headers).status_code == 422
    assert client.post("/accounts", json={"name": "Visa", "type": "credit"}, headers=headers).status_code == 422
    assert client.post("/accounts", json={"name": "general", "type": "cash"}, headers=headers).status_code == 409


def test_same_name_allowed_for_different_users(client, auth):
    vlad, bob = auth("vlad"), auth("bob", "bobs-password-1")
    assert client.post("/accounts", json={"name": "Cash", "type": "cash"}, headers=vlad).status_code == 201
    assert client.post("/accounts", json={"name": "Cash", "type": "cash"}, headers=bob).status_code == 201


def test_patch_account(client, auth):
    headers = auth()
    patched = client.patch("/accounts/1", json={"name": "Main", "subtype": "AIB", "opening_balance": -20.5}, headers=headers).json()
    assert patched["name"] == "Main" and patched["subtype"] == "AIB" and patched["opening_balance"] == "-20.50"
    assert client.patch("/accounts/1", json={"name": None}, headers=headers).status_code == 422
    assert client.patch("/accounts/1", json={"subtype": None}, headers=headers).json()["subtype"] is None
    cash = client.post("/accounts", json={"name": "Cash", "type": "cash"}, headers=headers).json()["id"]
    assert client.patch(f"/accounts/{cash}", json={"name": "main"}, headers=headers).status_code == 409
    assert client.patch("/accounts/999", json={"name": "x"}, headers=headers).status_code == 404


def test_expenses_and_incomes_default_to_general_and_can_target_an_account(client, auth):
    headers = auth()
    cash = client.post("/accounts", json={"name": "Cash", "type": "cash"}, headers=headers).json()["id"]
    assert client.post("/expenses", json={"price": 4, "date": "2026-09-10"}, headers=headers).json()["account_id"] == 1
    assert client.post("/expenses", json={"price": 6, "date": "2026-09-10", "account_id": cash}, headers=headers).json()["account_id"] == cash
    assert client.post("/incomes", json={"amount": 50, "date": "2026-09-10", "account_id": cash}, headers=headers).json()["account_id"] == cash
    assert client.post("/expenses", json={"price": 1, "date": "2026-09-10", "account_id": 999}, headers=headers).status_code == 422
    assert [e["price"] for e in client.get("/expenses", params={"account_id": cash}, headers=headers).json()] == ["6.00"]
    assert {a["name"]: a["balance"] for a in client.get("/accounts", headers=headers).json()} == {"General": "-4.00", "Cash": "44.00"}


def test_cannot_use_another_users_account(client, auth):
    vlad, bob = auth("vlad"), auth("bob", "bobs-password-1")
    vlad_cash = client.post("/accounts", json={"name": "Cash", "type": "cash"}, headers=vlad).json()["id"]
    assert client.post("/expenses", json={"price": 1, "date": "2026-09-10", "account_id": vlad_cash}, headers=bob).status_code == 422
    assert client.get(f"/accounts/{vlad_cash}", headers=bob).status_code == 404
    assert client.delete(f"/accounts/{vlad_cash}", headers=bob).status_code == 404


def test_delete_general_is_409(client, auth):
    assert client.delete("/accounts/1", headers=auth()).status_code == 409


def test_delete_account_folds_its_history_into_general(client, auth):
    headers = auth()
    cash = client.post("/accounts", json={"name": "Cash", "type": "cash", "opening_balance": 20}, headers=headers).json()["id"]
    other = client.post("/accounts", json={"name": "Other", "type": "other"}, headers=headers).json()["id"]
    client.patch("/accounts/1", json={"opening_balance": 100}, headers=headers)
    expense_id = client.post("/expenses", json={"price": 6, "date": "2026-09-10", "account_id": cash}, headers=headers).json()["id"]
    income_id = client.post("/incomes", json={"amount": 50, "date": "2026-09-10", "account_id": cash}, headers=headers).json()["id"]
    # General -> Cash must vanish; Other -> Cash must become Other -> General.
    client.post("/transfers", json={"amount": 30, "date": "2026-09-10", "from_account_id": 1, "to_account_id": cash}, headers=headers)
    kept = client.post("/transfers", json={"amount": 5, "date": "2026-09-10", "from_account_id": other, "to_account_id": cash}, headers=headers).json()["id"]
    before = client.get("/balance", headers=headers).json()["balance"]

    assert client.delete(f"/accounts/{cash}", headers=headers).status_code == 204

    assert client.get(f"/expenses/{expense_id}", headers=headers).json()["account_id"] == 1
    assert client.get(f"/incomes/{income_id}", headers=headers).json()["account_id"] == 1
    transfers = client.get("/transfers", headers=headers).json()
    assert [(t["id"], t["from_account_id"], t["to_account_id"]) for t in transfers] == [(kept, other, 1)]
    after = client.get("/balance", headers=headers).json()
    assert after["balance"] == before
    # General: 100 + 20 (Cash's opening) + 50 - 6 + 5 (Other -> General) = 169
    assert {a["name"]: a["balance"] for a in after["accounts"]} == {"General": "169.00", "Other": "-5.00"}
    assert client.get("/accounts/1", headers=headers).json()["opening_balance"] == "120.00"


def test_requires_auth(client):
    assert client.get("/accounts").status_code == 401
