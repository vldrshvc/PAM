"""Target maths (pure) and the /targets endpoints."""

from datetime import date
from decimal import Decimal

from app.models import Target
from app.services.targets import TargetStatus, target_progress


def target(amount: str, start: date, end: date, start_balance: str = "0") -> Target:
    return Target(id=1, user_id=1, name="Laptop", amount=Decimal(amount), start_date=start, end_date=end, start_balance=Decimal(start_balance))


START, END = date(2026, 9, 1), date(2026, 9, 30)  # 30 days inclusive


def test_day_one_needs_the_whole_amount_spread_over_all_days():
    p = target_progress(target("300", START, END), Decimal("0"), START)
    assert (p.days_total, p.days_elapsed, p.days_left) == (30, 0, 30)
    assert p.remaining == Decimal("300.00")
    assert p.required_per_day == Decimal("10.00")
    assert p.expected_balance == Decimal("0.00")
    assert p.status == TargetStatus.ON_TRACK


def test_required_per_day_rises_when_behind_and_is_rounded_up():
    # Day 11: should be at 100 (10/day), only at 40. 260 left over 20 days = 13.00
    p = target_progress(target("300", START, END), Decimal("40"), date(2026, 9, 11))
    assert p.days_elapsed == 10 and p.days_left == 20
    assert p.expected_balance == Decimal("100.00")
    assert p.required_per_day == Decimal("13.00")
    assert p.status == TargetStatus.BEHIND
    # 40 gained in 10 days -> 4/day -> 40 + 4*20 = 120 by the end
    assert p.projected_balance == Decimal("120.00")
    # 260 left at 4/day -> 65 days
    assert p.projected_date == date(2026, 11, 15)


def test_required_per_day_falls_when_ahead():
    p = target_progress(target("300", START, END), Decimal("200"), date(2026, 9, 11))
    assert p.required_per_day == Decimal("5.00")
    assert p.status == TargetStatus.ON_TRACK
    assert p.projected_balance == Decimal("600.00")
    assert p.projected_date == date(2026, 9, 16)


def test_rounding_never_undershoots():
    # 100 over 3 days = 33.333... -> 33.34, because 33.33 * 3 < 100
    p = target_progress(target("100", START, date(2026, 9, 3)), Decimal("0"), START)
    assert p.required_per_day == Decimal("33.34")


def test_last_day_counts_and_needs_everything_left():
    p = target_progress(target("300", START, END), Decimal("250"), END)
    assert p.days_left == 1
    assert p.required_per_day == Decimal("50.00")


def test_achieved_when_balance_reaches_amount():
    p = target_progress(target("300", START, END), Decimal("305"), date(2026, 9, 20))
    assert p.remaining == Decimal("0.00")
    assert p.required_per_day == Decimal("0.00")
    assert p.status == TargetStatus.ACHIEVED
    assert p.projected_date == date(2026, 9, 20)


def test_expired_after_end_date_without_reaching_it():
    p = target_progress(target("300", START, END), Decimal("100"), date(2026, 10, 5))
    assert p.days_left == 0 and p.days_elapsed == 30
    assert p.required_per_day == Decimal("0.00")
    assert p.status == TargetStatus.EXPIRED


def test_pace_line_starts_from_the_balance_at_creation():
    # Started at 1000, target 1300: expected halfway is 1150, not 150.
    p = target_progress(target("1300", START, END, start_balance="1000"), Decimal("1100"), date(2026, 9, 16))
    assert p.days_elapsed == 15
    assert p.expected_balance == Decimal("1150.00")
    assert p.status == TargetStatus.BEHIND
    assert p.required_per_day == Decimal("13.34")  # 200 / 15 rounded up


def test_no_projection_when_balance_is_falling():
    p = target_progress(target("300", START, END, start_balance="50"), Decimal("20"), date(2026, 9, 11))
    assert p.projected_date is None
    assert p.projected_balance == Decimal("-40.00")


def test_before_start_date_nothing_has_elapsed():
    p = target_progress(target("300", date(2026, 10, 1), date(2026, 10, 30)), Decimal("0"), date(2026, 9, 20))
    assert p.days_elapsed == 0
    assert p.days_left == 41  # counts from today, inclusive, to the end


# --- API ---------------------------------------------------------------------


def test_create_target_snapshots_balance_and_defaults_start_to_today(client, auth):
    headers = auth()
    client.patch("/accounts/1", json={"opening_balance": 100}, headers=headers)
    response = client.post("/targets", json={"name": "Laptop", "amount": 1300, "end_date": "2099-12-31"}, headers=headers)
    assert response.status_code == 201
    body = response.json()
    assert body["start_balance"] == "100.00" and body["current_balance"] == "100.00"
    assert body["remaining"] == "1200.00"
    assert body["start_date"] == date.today().isoformat() or body["days_elapsed"] == 0
    assert body["status"] == "on_track"
    assert Decimal(body["required_per_day"]) > 0


def test_target_progress_follows_live_balance(client, auth):
    headers = auth()
    target_id = client.post("/targets", json={"name": "Fund", "amount": 100, "end_date": "2099-12-31"}, headers=headers).json()["id"]
    client.post("/incomes", json={"amount": 100, "date": "2026-09-10"}, headers=headers)
    body = client.get(f"/targets/{target_id}", headers=headers).json()
    assert body["current_balance"] == "100.00" and body["status"] == "achieved"
    client.post("/expenses", json={"price": 30, "date": "2026-09-10"}, headers=headers)
    body = client.get(f"/targets/{target_id}", headers=headers).json()
    # 70 is still above the pace line (which starts at 0 today), so on track, not achieved.
    assert body["remaining"] == "30.00" and body["status"] == "on_track"


def test_target_validation(client, auth):
    headers = auth()
    assert client.post("/targets", json={"name": "x", "amount": 100, "start_date": "2026-09-10", "end_date": "2026-09-01"}, headers=headers).status_code == 422
    assert client.post("/targets", json={"name": "x", "amount": -1, "end_date": "2099-01-01"}, headers=headers).status_code == 422
    assert client.post("/targets", json={"name": "  ", "amount": 1, "end_date": "2099-01-01"}, headers=headers).status_code == 422


def test_patch_and_delete_target(client, auth):
    headers = auth()
    target_id = client.post("/targets", json={"name": "Fund", "amount": 100, "start_date": "2026-09-01", "end_date": "2026-09-30"}, headers=headers).json()["id"]
    patched = client.patch(f"/targets/{target_id}", json={"amount": 200, "end_date": "2026-10-31"}, headers=headers).json()
    assert patched["amount"] == "200.00" and patched["end_date"] == "2026-10-31"
    assert client.patch(f"/targets/{target_id}", json={"end_date": "2026-08-01"}, headers=headers).status_code == 422
    assert client.patch(f"/targets/{target_id}", json={"amount": None}, headers=headers).status_code == 422
    assert client.delete(f"/targets/{target_id}", headers=headers).status_code == 204
    assert client.get(f"/targets/{target_id}", headers=headers).status_code == 404


def test_targets_listed_by_deadline_and_in_daily_summary(client, auth):
    headers = auth()
    client.post("/targets", json={"name": "Later", "amount": 100, "end_date": "2099-12-31"}, headers=headers)
    client.post("/targets", json={"name": "Sooner", "amount": 100, "end_date": "2099-06-30"}, headers=headers)
    assert [t["name"] for t in client.get("/targets", headers=headers).json()] == ["Sooner", "Later"]
    summary = client.get("/summary/daily", params={"tz": "Europe/Dublin"}, headers=headers).json()
    assert [t["name"] for t in summary["targets"]] == ["Sooner", "Later"]


def test_targets_are_per_user(client, auth):
    vlad, bob = auth("vlad"), auth("bob", "bobs-password-1")
    target_id = client.post("/targets", json={"name": "Fund", "amount": 100, "end_date": "2099-12-31"}, headers=vlad).json()["id"]
    assert client.get("/targets", headers=bob).json() == []
    assert client.get(f"/targets/{target_id}", headers=bob).status_code == 404


def test_requires_auth(client):
    assert client.get("/targets").status_code == 401
