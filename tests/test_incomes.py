def test_create_income_defaults_and_formatting(client, auth):
    response = client.post("/incomes", json={"amount": 500, "date": "2026-09-10", "description": "client"}, headers=auth())
    assert response.status_code == 201
    assert response.json() == {"id": 1, "amount": "500.00", "date": "2026-09-10", "source": "work", "description": "client"}


def test_create_income_validation(client, auth):
    headers = auth()
    assert client.post("/incomes", json={"amount": -5, "date": "2026-09-10"}, headers=headers).status_code == 422
    assert client.post("/incomes", json={"amount": 5}, headers=headers).status_code == 422
    assert client.post("/incomes", json={"amount": 5, "date": "2026-09-10", "source": "lottery"}, headers=headers).status_code == 422


def test_list_filters(client, auth):
    headers = auth()
    for amount, day, source in [(500, "2026-09-10", "work"), (25.5, "2026-09-01", "friend"), (40, "2026-09-05", "bonus")]:
        client.post("/incomes", json={"amount": amount, "date": day, "source": source}, headers=headers)
    assert [i["date"] for i in client.get("/incomes", headers=headers).json()] == ["2026-09-10", "2026-09-05", "2026-09-01"]
    assert [i["amount"] for i in client.get("/incomes", params={"source": "work"}, headers=headers).json()] == ["500.00"]
    assert [i["amount"] for i in client.get("/incomes", params={"date_from": "2026-09-02", "date_to": "2026-09-09"}, headers=headers).json()] == ["40.00"]
    assert client.get("/incomes", params={"date_from": "2026-09-09", "date_to": "2026-09-01"}, headers=headers).status_code == 422


def test_patch_and_delete(client, auth):
    headers = auth()
    income_id = client.post("/incomes", json={"amount": 10, "date": "2026-09-10"}, headers=headers).json()["id"]
    patched = client.patch(f"/incomes/{income_id}", json={"amount": 12.5, "source": "debt"}, headers=headers).json()
    assert patched["amount"] == "12.50" and patched["source"] == "debt" and patched["date"] == "2026-09-10"
    assert client.patch(f"/incomes/{income_id}", json={"source": None}, headers=headers).status_code == 422
    assert client.delete(f"/incomes/{income_id}", headers=headers).status_code == 204
    assert client.get(f"/incomes/{income_id}", headers=headers).status_code == 404


def test_incomes_are_per_user(client, auth):
    vlad, bob = auth("vlad"), auth("bob", "bobs-password-1")
    income_id = client.post("/incomes", json={"amount": 10, "date": "2026-09-10"}, headers=vlad).json()["id"]
    assert client.get("/incomes", headers=bob).json() == []
    assert client.get(f"/incomes/{income_id}", headers=bob).status_code == 404
    assert client.delete(f"/incomes/{income_id}", headers=bob).status_code == 404


def test_requires_auth(client):
    assert client.get("/incomes").status_code == 401
