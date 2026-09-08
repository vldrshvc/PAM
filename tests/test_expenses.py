from decimal import Decimal


def test_create_expense_normalizes_price_and_defaults_status(client, auth):
    response = client.post(
        "/expenses",
        json={"price": 12.4, "date": "2026-09-08", "description": "SuperValu", "category_id": 2},
        headers=auth(),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["price"] == "12.40"
    assert body["status"] == "confirmed"
    assert body["category_id"] == 2


def test_create_expense_without_category_falls_back_to_uncategorized(client, auth):
    body = client.post("/expenses", json={"price": 7, "date": "2026-09-08"}, headers=auth()).json()
    assert body["category_id"] == 1


def test_create_expense_with_unknown_category_is_422(client, auth):
    response = client.post("/expenses", json={"price": 5, "date": "2026-09-08", "category_id": 999}, headers=auth())
    assert response.status_code == 422
    assert response.json()["detail"] == "Category 999 does not exist"


def test_create_expense_validation(client, auth):
    headers = auth()
    assert client.post("/expenses", json={"price": -5, "date": "2026-09-08"}, headers=headers).status_code == 422
    assert client.post("/expenses", json={"price": 1.234, "date": "2026-09-08"}, headers=headers).status_code == 422
    assert client.post("/expenses", json={"price": 5}, headers=headers).status_code == 422


def test_client_cannot_set_status(client, auth):
    body = client.post("/expenses", json={"price": 5, "date": "2026-09-08", "status": "pending"}, headers=auth()).json()
    assert body["status"] == "confirmed"


def test_list_filters_and_orders_newest_first(client, auth):
    headers = auth()
    for price, day, category in [(120, "2026-09-02", 2), (80, "2026-09-05", 3), (35, "2026-09-08", 3)]:
        client.post("/expenses", json={"price": price, "date": day, "category_id": category}, headers=headers)

    everything = client.get("/expenses", headers=headers).json()
    assert [e["date"] for e in everything] == ["2026-09-08", "2026-09-05", "2026-09-02"]

    by_category = client.get("/expenses", params={"category_id": 3}, headers=headers).json()
    assert [e["price"] for e in by_category] == ["35.00", "80.00"]

    by_range = client.get("/expenses", params={"date_from": "2026-09-03", "date_to": "2026-09-06"}, headers=headers).json()
    assert [e["price"] for e in by_range] == ["80.00"]

    reversed_range = client.get("/expenses", params={"date_from": "2026-09-06", "date_to": "2026-09-03"}, headers=headers)
    assert reversed_range.status_code == 422


def test_get_unknown_expense_is_404(client, auth):
    assert client.get("/expenses/99", headers=auth()).status_code == 404


def test_patch_changes_only_sent_fields(client, auth):
    headers = auth()
    created = client.post("/expenses", json={"price": 10, "date": "2026-09-08", "description": "x"}, headers=headers).json()

    patched = client.patch(f"/expenses/{created['id']}", json={"price": 12.5, "category_id": 2}, headers=headers).json()
    assert patched["price"] == "12.50" and patched["category_id"] == 2
    assert patched["description"] == "x" and patched["date"] == "2026-09-08"

    cleared = client.patch(f"/expenses/{created['id']}", json={"description": None}, headers=headers).json()
    assert cleared["description"] is None

    assert client.patch(f"/expenses/{created['id']}", json={}, headers=headers).json() == cleared


def test_patch_rejects_null_price_and_unknown_category(client, auth):
    headers = auth()
    expense_id = client.post("/expenses", json={"price": 10, "date": "2026-09-08"}, headers=headers).json()["id"]
    assert client.patch(f"/expenses/{expense_id}", json={"price": None}, headers=headers).status_code == 422
    assert client.patch(f"/expenses/{expense_id}", json={"category_id": 999}, headers=headers).status_code == 422


def test_delete_expense(client, auth):
    headers = auth()
    expense_id = client.post("/expenses", json={"price": 10, "date": "2026-09-08"}, headers=headers).json()["id"]
    assert client.delete(f"/expenses/{expense_id}", headers=headers).status_code == 204
    assert client.get(f"/expenses/{expense_id}", headers=headers).status_code == 404
    assert client.delete(f"/expenses/{expense_id}", headers=headers).status_code == 404


def test_users_cannot_see_or_touch_each_others_expenses(client, auth):
    vlad, bob = auth("vlad"), auth("bob", "bobs-password-1")
    expense_id = client.post("/expenses", json={"price": 10, "date": "2026-09-08", "category_id": 2}, headers=vlad).json()["id"]

    assert client.get("/expenses", headers=bob).json() == []
    assert client.get(f"/expenses/{expense_id}", headers=bob).status_code == 404
    assert client.patch(f"/expenses/{expense_id}", json={"price": 1}, headers=bob).status_code == 404
    assert client.delete(f"/expenses/{expense_id}", headers=bob).status_code == 404
    # vlad's Groceries is id 2; bob's own categories start at 9.
    assert client.post("/expenses", json={"price": 1, "date": "2026-09-08", "category_id": 2}, headers=bob).status_code == 422

    assert client.get(f"/expenses/{expense_id}", headers=vlad).json()["price"] == "10.00"
