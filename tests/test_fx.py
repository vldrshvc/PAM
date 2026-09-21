"""Euro reference rates: reading the ECB's file, picking a day, converting.

The fetch and its cache are tested separately from the maths, the same split
the code itself has.
"""

import datetime as dt
from decimal import Decimal

import httpx
import pytest

from app import ecb
from app.services.fx import Rate, RateUnavailableError, parse_rates, rate_on, to_euro
from tests.conftest import ECB_XML


@pytest.fixture
def table():
    return parse_rates(ECB_XML)


# --- reading the file --------------------------------------------------------


def test_every_published_day_is_read(table):
    assert sorted(table) == [dt.date(2026, 9, 16), dt.date(2026, 9, 17), dt.date(2026, 9, 18)]
    assert table[dt.date(2026, 9, 18)]["RON"] == Decimal("5.0755")


def test_the_two_namespaces_do_not_get_in_the_way(table):
    # The file declares gesmes: and a default namespace; walking by attribute
    # rather than by tag is what keeps that from mattering.
    assert "USD" in table[dt.date(2026, 9, 16)]


@pytest.mark.parametrize("xml", [b"", b"not xml at all", b"<Envelope/>"])
def test_a_file_that_is_not_the_ecbs_is_refused(xml):
    with pytest.raises(RateUnavailableError):
        parse_rates(xml)


def test_a_broken_row_is_skipped_not_fatal():
    xml = b"""<Envelope><Cube><Cube time="2026-09-18">
      <Cube currency="RON" rate="oops"/>
      <Cube currency="GBP" rate="0"/>
      <Cube currency="USD" rate="1.17"/>
    </Cube></Cube></Envelope>"""

    rates = parse_rates(xml)[dt.date(2026, 9, 18)]

    assert rates == {"USD": Decimal("1.17")}


# --- picking a day -----------------------------------------------------------


def test_the_days_own_rate_is_used(table):
    rate = rate_on(table, "RON", dt.date(2026, 9, 17))
    assert (rate.per_euro, rate.published) == (Decimal("5.0740"), dt.date(2026, 9, 17))


def test_a_day_with_nothing_published_falls_back_to_the_last_one(table):
    # A Sunday: the ECB publishes on working days only.
    rate = rate_on(table, "RON", dt.date(2026, 9, 20))
    assert rate.published == dt.date(2026, 9, 18)


def test_a_currency_missing_on_its_day_falls_back_too(table):
    # GBP is absent on the 17th but present on the 16th.
    rate = rate_on(table, "GBP", dt.date(2026, 9, 17))
    assert (rate.per_euro, rate.published) == (Decimal("0.86610"), dt.date(2026, 9, 16))


def test_a_date_before_anything_published_is_refused(table):
    with pytest.raises(RateUnavailableError, match="on or before"):
        rate_on(table, "RON", dt.date(2026, 9, 15))


def test_a_currency_the_ecb_does_not_publish_says_so(table):
    with pytest.raises(RateUnavailableError, match="not a currency"):
        rate_on(table, "UAH", dt.date(2026, 9, 18))


# --- converting --------------------------------------------------------------


@pytest.mark.parametrize(
    "amount, per_euro, expected",
    [
        ("57.90", "5.0755", "11.41"),  # the receipt that started this
        ("10.00", "1.1742", "8.52"),
        ("0.01", "5.0755", "0.00"),  # rounds to nothing, and says so honestly
        ("100.00", "0.86530", "115.57"),  # a currency stronger than the euro
    ],
)
def test_an_amount_is_divided_by_its_rate(amount, per_euro, expected):
    rate = Rate(currency="X", per_euro=Decimal(per_euro), published=dt.date(2026, 9, 18))

    assert to_euro(Decimal(amount), rate) == Decimal(expected)


# --- fetching and caching ----------------------------------------------------


@pytest.fixture(autouse=True)
def clean_cache():
    ecb.reset_cache()
    yield
    ecb.reset_cache()


def serve(monkeypatch, body: bytes = ECB_XML, fail: bool = False) -> list[int]:
    """Count calls to the ECB, and optionally make them fail."""
    calls: list[int] = []

    def fake_get(self, url):
        calls.append(1)
        if fail:
            raise httpx.ConnectError("no route to the ECB")
        return httpx.Response(200, content=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    return calls


def test_the_file_is_fetched_once_and_then_reused(monkeypatch):
    calls = serve(monkeypatch)

    first, second = ecb.get_rates(), ecb.get_rates()

    assert first is second
    assert len(calls) == 1


def test_the_file_is_refetched_once_it_is_stale(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "fx_cache_seconds", 0)
    calls = serve(monkeypatch)

    ecb.get_rates()
    ecb.get_rates()

    assert len(calls) == 2


def test_a_stale_table_is_served_when_the_ecb_is_down(monkeypatch):
    from app.config import settings

    serve(monkeypatch)
    cached = ecb.get_rates()
    monkeypatch.setattr(settings, "fx_cache_seconds", 0)
    serve(monkeypatch, fail=True)

    # A day-old reference rate beats refusing to read the receipt.
    assert ecb.get_rates() is cached


def test_with_nothing_cached_a_dead_ecb_is_an_error(monkeypatch):
    serve(monkeypatch, fail=True)

    with pytest.raises(RateUnavailableError):
        ecb.get_rates()


def test_an_absurdly_large_file_is_refused(monkeypatch):
    serve(monkeypatch, body=b"x" * (ecb.MAX_BYTES + 1))

    with pytest.raises(RateUnavailableError):
        ecb.get_rates()
