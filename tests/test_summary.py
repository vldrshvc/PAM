"""Summary endpoints end to end: dates, timezone, per-user scoping."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from app.services.budget import month_bounds, today_in

TZ = "Europe/Dublin"


def seed(client, headers) -> tuple[date, date]:
    """Limits on Groceries (300) and Eating out (100); spending today, earlier
    this month, and last month. Returns (today, a day in the previous month)."""
    today = today_in(ZoneInfo(TZ))
    month_start, _ = month_bounds(today.year, today.month)
    earlier = today if today == month_start else month_start
    last_month = month_start - timedelta(days=1)

    client.patch("/categories/2", json={"monthly_limit": 300}, headers=headers)
    client.patch("/categories/3", json={"monthly_limit": 100}, headers=headers)
    client.patch("/me", json={"opening_balance": 100}, headers=headers)
    client.post("/incomes", json={"amount": 500, "date": today.isoformat(), "source": "work"}, headers=headers)
    client.post("/incomes", json={"amount": 30, "date": last_month.isoformat(), "source": "friend"}, headers=headers)
    for price, day, category in [
        (120, earlier, 2),
        (45.5, today, 2),
        (80, earlier, 3),
        (35, today, 3),
        (7, today, None),  # uncategorized, unbudgeted
        (999, last_month, 2),
    ]:
        body = {"price": price, "date": day.isoformat()}
        if category:
            body["category_id"] = category
        assert client.post("/expenses", json=body, headers=headers).status_code == 201
    return today, last_month


def test_daily_summary_shape_and_maths(client, auth):
    headers = auth()
    today, _ = seed(client, headers)

    body = client.get("/summary/daily", params={"tz": TZ}, headers=headers).json()

    assert body["date"] == today.isoformat()
    assert body["timezone"] == TZ
    assert body["spent_today"] == "87.50"  # 45.50 + 35 + 7
    assert body["spent_this_month"] == "287.50"  # 120 + 45.50 + 80 + 35 + 7
    assert body["budget_total"] == "400.00"
    assert body["remaining_total"] == "119.50"  # 400 - (165.50 + 115); the 7 is unbudgeted
    assert body["over_budget"] is False
    # Only budgeted categories appear.
    assert [c["name"] for c in body["categories"]] == ["Groceries", "Eating out"]
    groceries, eating_out = body["categories"]
    assert groceries == {"id": 2, "name": "Groceries", "monthly_limit": "300.00", "spent": "165.50", "remaining": "134.50", "over_budget": False}
    assert eating_out["remaining"] == "-15.00" and eating_out["over_budget"] is True
    assert body["earned_today"] == "500.00"
    assert body["earned_this_month"] == "500.00"
    # 100 opening + 530 income - (287.50 + 999) expenses, all time
    assert body["balance"] == "-656.50"


def test_daily_summary_is_empty_for_fresh_user(client, auth):
    body = client.get("/summary/daily", params={"tz": TZ}, headers=auth()).json()
    assert body["spent_today"] == "0.00"
    assert body["budget_total"] == "0.00"
    assert body["categories"] == []
    assert body["earned_today"] == "0.00" and body["balance"] == "0.00"


def test_daily_summary_defaults_to_utc_and_rejects_unknown_zone(client, auth):
    headers = auth()
    assert client.get("/summary/daily", headers=headers).json()["timezone"] == "UTC"
    response = client.get("/summary/daily", params={"tz": "Mars/Olympus"}, headers=headers)
    assert response.status_code == 422


def test_monthly_summary_lists_every_category(client, auth):
    headers = auth()
    today, _ = seed(client, headers)

    body = client.get("/summary/monthly", params={"tz": TZ}, headers=headers).json()

    assert body["month"] == today.strftime("%Y-%m")
    assert body["spent_total"] == "287.50"
    assert len(body["categories"]) == 8
    by_name = {c["name"]: c for c in body["categories"]}
    assert by_name["uncategorized"]["spent"] == "7.00"
    assert by_name["uncategorized"]["remaining"] is None
    assert by_name["Transport"]["spent"] == "0.00"
    assert body["earned_total"] == "500.00"


def test_monthly_summary_accepts_explicit_month(client, auth):
    headers = auth()
    _, last_month = seed(client, headers)

    body = client.get("/summary/monthly", params={"month": last_month.strftime("%Y-%m")}, headers=headers).json()

    assert body["spent_total"] == "999.00"
    assert body["remaining_total"] == "-599.00"
    assert body["over_budget"] is True
    assert body["earned_total"] == "30.00"
    assert client.get("/summary/monthly", params={"month": "2026-13"}, headers=headers).status_code == 422


def test_summaries_are_per_user(client, auth):
    vlad, bob = auth("vlad"), auth("bob", "bobs-password-1")
    seed(client, vlad)
    body = client.get("/summary/daily", params={"tz": TZ}, headers=bob).json()
    assert body["spent_this_month"] == "0.00" and body["categories"] == []


def test_summary_requires_auth(client):
    assert client.get("/summary/daily").status_code == 401
    assert client.get("/summary/monthly").status_code == 401
