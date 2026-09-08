def test_create_category_with_limit(client, auth):
    response = client.post("/categories", json={"name": "Coffee", "monthly_limit": 40}, headers=auth())
    assert response.status_code == 201
    assert response.json() == {"id": 9, "name": "Coffee", "monthly_limit": "40.00"}


def test_create_category_validation(client, auth):
    headers = auth()
    assert client.post("/categories", json={"name": "   "}, headers=headers).status_code == 422
    assert client.post("/categories", json={"name": "X", "monthly_limit": -1}, headers=headers).status_code == 422


def test_duplicate_name_is_409_case_insensitively(client, auth):
    headers = auth()
    client.post("/categories", json={"name": "Coffee"}, headers=headers)
    assert client.post("/categories", json={"name": "  coffee "}, headers=headers).status_code == 409
    assert client.post("/categories", json={"name": "groceries"}, headers=headers).status_code == 409


def test_same_name_allowed_for_different_users(client, auth):
    vlad, bob = auth("vlad"), auth("bob", "bobs-password-1")
    assert client.post("/categories", json={"name": "Coffee"}, headers=vlad).status_code == 201
    assert client.post("/categories", json={"name": "Coffee"}, headers=bob).status_code == 201


def test_patch_sets_and_clears_limit(client, auth):
    headers = auth()
    assert client.patch("/categories/2", json={"monthly_limit": 300}, headers=headers).json()["monthly_limit"] == "300.00"
    assert client.patch("/categories/2", json={"monthly_limit": None}, headers=headers).json()["monthly_limit"] is None


def test_patch_rename_rules(client, auth):
    headers = auth()
    assert client.patch("/categories/4", json={"name": "Travel"}, headers=headers).json()["name"] == "Travel"
    assert client.patch("/categories/4", json={"name": "bills"}, headers=headers).status_code == 409
    assert client.patch("/categories/1", json={"name": "Misc"}, headers=headers).status_code == 409
    assert client.patch("/categories/999", json={"name": "X"}, headers=headers).status_code == 404


def test_delete_reassigns_expenses_to_uncategorized(client, auth):
    headers = auth()
    coffee_id = client.post("/categories", json={"name": "Coffee"}, headers=headers).json()["id"]
    expense_id = client.post("/expenses", json={"price": 3.5, "date": "2026-09-08", "category_id": coffee_id}, headers=headers).json()["id"]

    assert client.delete(f"/categories/{coffee_id}", headers=headers).status_code == 204

    assert client.get(f"/expenses/{expense_id}", headers=headers).json()["category_id"] == 1
    assert coffee_id not in [c["id"] for c in client.get("/categories", headers=headers).json()]


def test_delete_uncategorized_is_409(client, auth):
    assert client.delete("/categories/1", headers=auth()).status_code == 409


def test_delete_unknown_or_foreign_category_is_404(client, auth):
    vlad, bob = auth("vlad"), auth("bob", "bobs-password-1")
    assert client.delete("/categories/999", headers=vlad).status_code == 404
    assert client.delete("/categories/2", headers=bob).status_code == 404
    assert client.get("/categories", headers=vlad).json()[1]["name"] == "Groceries"
