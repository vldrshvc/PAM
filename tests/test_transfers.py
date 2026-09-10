import pytest


@pytest.fixture
def two_accounts(client, auth):
    headers = auth()
    cash = client.post("/accounts", json={"name": "Cash", "type": "cash"}, headers=headers).json()["id"]
    return headers, 1, cash


def test_create_transfer(client, two_accounts):
    headers, general, cash = two_accounts
    response = client.post(
        "/transfers", json={"amount": 100, "date": "2026-09-10", "from_account_id": general, "to_account_id": cash, "description": "atm"}, headers=headers
    )
    assert response.status_code == 201
    assert response.json() == {"id": 1, "amount": "100.00", "date": "2026-09-10", "description": "atm", "from_account_id": general, "to_account_id": cash}


def test_transfer_validation(client, two_accounts):
    headers, general, cash = two_accounts
    base = {"amount": 1, "date": "2026-09-10"}
    assert client.post("/transfers", json={**base, "from_account_id": general, "to_account_id": general}, headers=headers).status_code == 422
    assert client.post("/transfers", json={**base, "from_account_id": general, "to_account_id": 999}, headers=headers).status_code == 422
    assert client.post("/transfers", json={"amount": -1, "date": "2026-09-10", "from_account_id": general, "to_account_id": cash}, headers=headers).status_code == 422


def test_list_filters_by_either_end(client, two_accounts):
    headers, general, cash = two_accounts
    other = client.post("/accounts", json={"name": "Other", "type": "other"}, headers=headers).json()["id"]
    client.post("/transfers", json={"amount": 1, "date": "2026-09-01", "from_account_id": general, "to_account_id": cash}, headers=headers)
    client.post("/transfers", json={"amount": 2, "date": "2026-09-05", "from_account_id": cash, "to_account_id": other}, headers=headers)
    client.post("/transfers", json={"amount": 3, "date": "2026-09-10", "from_account_id": general, "to_account_id": other}, headers=headers)
    assert [t["amount"] for t in client.get("/transfers", params={"account_id": cash}, headers=headers).json()] == ["2.00", "1.00"]
    assert [t["amount"] for t in client.get("/transfers", params={"date_from": "2026-09-02"}, headers=headers).json()] == ["3.00", "2.00"]
    assert client.get("/transfers", params={"date_from": "2026-09-09", "date_to": "2026-09-01"}, headers=headers).status_code == 422


def test_patch_and_delete(client, two_accounts):
    headers, general, cash = two_accounts
    transfer_id = client.post("/transfers", json={"amount": 10, "date": "2026-09-10", "from_account_id": general, "to_account_id": cash}, headers=headers).json()["id"]
    assert client.patch(f"/transfers/{transfer_id}", json={"amount": 12.5}, headers=headers).json()["amount"] == "12.50"
    assert client.patch(f"/transfers/{transfer_id}", json={"to_account_id": general}, headers=headers).status_code == 422
    assert client.patch(f"/transfers/{transfer_id}", json={"amount": None}, headers=headers).status_code == 422
    assert client.delete(f"/transfers/{transfer_id}", headers=headers).status_code == 204
    assert client.get(f"/transfers/{transfer_id}", headers=headers).status_code == 404


def test_transfers_are_per_user(client, auth):
    vlad, bob = auth("vlad"), auth("bob", "bobs-password-1")
    cash = client.post("/accounts", json={"name": "Cash", "type": "cash"}, headers=vlad).json()["id"]
    transfer_id = client.post("/transfers", json={"amount": 1, "date": "2026-09-10", "from_account_id": 1, "to_account_id": cash}, headers=vlad).json()["id"]
    assert client.get("/transfers", headers=bob).json() == []
    assert client.get(f"/transfers/{transfer_id}", headers=bob).status_code == 404


def test_requires_auth(client):
    assert client.get("/transfers").status_code == 401
