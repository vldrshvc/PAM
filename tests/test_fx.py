"""Euro reference rates: reading the ECB's file, picking a day, converting.

The fetch and its cache are tested separately from the maths, the same split
the code itself has.
"""

import datetime as dt
from decimal import Decimal

import httpx
import pytest

from app import ecb
from app import nbu
from app.services.fx import (
    Chain,
    CurrencyNotPublishedError,
    EcbRates,
    Rate,
    RateUnavailableError,
    parse_nbu,
    parse_rates,
    rate_on,
    to_euro,
)
from tests.conftest import ECB_XML, NBU_JSON


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
    assert (rate.per_euro, rate.published, rate.source) == (
        Decimal("5.0740"), dt.date(2026, 9, 17), "ECB",
    )


def test_a_day_with_nothing_published_falls_back_to_the_last_one(table):
    # A Sunday: the ECB publishes on working days only.
    rate = rate_on(table, "RON", dt.date(2026, 9, 20))
    assert rate.published == dt.date(2026, 9, 18)


def test_a_currency_missing_on_its_day_falls_back_too(table):
    # GBP is absent on the 17th but present on the 16th.
    rate = rate_on(table, "GBP", dt.date(2026, 9, 17))
    assert (rate.per_euro, rate.published) == (Decimal("0.86610"), dt.date(2026, 9, 16))


def test_a_date_before_the_file_starts_uses_its_earliest_rate(table):
    # The file holds ninety days. A receipt older than that — or a misread
    # year — must not cost the whole reading, so the nearest rate is used and
    # the caller shows which day it came from.
    rate = rate_on(table, "RON", dt.date(2024, 9, 20))

    assert rate.published == dt.date(2026, 9, 16)
    assert rate.per_euro == Decimal("5.0722")


def test_a_currency_the_ecb_does_not_publish_says_so(table):
    # A distinct error, because it is the only reason to try another source.
    with pytest.raises(CurrencyNotPublishedError, match="not published by the ECB"):
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
    rate = Rate(currency="X", per_euro=Decimal(per_euro), published=dt.date(2026, 9, 18), source="ECB")

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


def test_the_file_is_fetched_once_and_then_reused(monkeypatch, caplog):
    calls = serve(monkeypatch)

    with caplog.at_level("INFO", logger="app.ecb"):
        first, second = ecb.get_rates(), ecb.get_rates()

    assert first is second
    assert len(calls) == 1
    # One line per load, so a deploy can be checked from the server log.
    assert "ECB rates loaded: 3 days, latest 2026-09-18" in caplog.text


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


# --- the hryvnia, from its own central bank ----------------------------------


def test_the_nbus_row_is_read_as_hryvnia_per_euro():
    rate = parse_nbu(NBU_JSON, dt.date(2026, 9, 18))

    assert (rate.currency, rate.per_euro, rate.source) == ("UAH", Decimal("48.5031"), "NBU")
    # The bank's own date wins: asked about a weekend it answers with the day
    # the rate was actually set.
    assert rate.published == dt.date(2026, 9, 18)


def test_the_date_asked_for_is_used_when_the_bank_prints_none():
    row = b'[{"rate":48.5031,"cc":"EUR"}]'

    assert parse_nbu(row, dt.date(2026, 9, 20)).published == dt.date(2026, 9, 20)


@pytest.mark.parametrize(
    "payload",
    [b"", b"not json", b"[]", b'[{"cc":"USD","rate":41.2}]', b'[{"cc":"EUR"}]', b'[{"cc":"EUR","rate":0}]'],
)
def test_an_answer_without_a_usable_euro_row_is_refused(payload):
    with pytest.raises(RateUnavailableError):
        parse_nbu(payload, dt.date(2026, 9, 18))


@pytest.fixture(autouse=True)
def clean_nbu_cache():
    nbu.reset_cache()
    yield
    nbu.reset_cache()


def serve_nbu(monkeypatch, body: bytes = NBU_JSON, fail: bool = False) -> list[dict]:
    calls: list[dict] = []

    def fake_get(self, url, params=None):
        calls.append(params or {})
        if fail:
            raise httpx.ConnectError("no route to the NBU")
        return httpx.Response(200, content=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    return calls


def test_the_hryvnia_is_asked_for_by_date_and_then_cached(monkeypatch, caplog):
    calls = serve_nbu(monkeypatch)
    source = nbu.HryvniaRates()

    with caplog.at_level("INFO", logger="app.nbu"):
        first = source.rate_on("UAH", dt.date(2026, 9, 18))
        second = source.rate_on("uah", dt.date(2026, 9, 18))

    assert "48.5031 UAH per euro" in caplog.text

    assert first == second
    assert len(calls) == 1
    assert calls[0] == {"json": "", "valcode": "EUR", "date": "20260918"}


def test_each_day_is_its_own_question(monkeypatch):
    calls = serve_nbu(monkeypatch)
    source = nbu.HryvniaRates()

    source.rate_on("UAH", dt.date(2026, 9, 18))
    source.rate_on("UAH", dt.date(2026, 9, 17))

    assert [c["date"] for c in calls] == ["20260918", "20260917"]


def test_the_ukrainian_bank_is_not_asked_about_other_currencies(monkeypatch):
    calls = serve_nbu(monkeypatch)

    with pytest.raises(CurrencyNotPublishedError):
        nbu.HryvniaRates().rate_on("RON", dt.date(2026, 9, 18))

    assert calls == []


def test_an_unreachable_bank_is_an_error_not_a_guess(monkeypatch):
    serve_nbu(monkeypatch, fail=True)

    with pytest.raises(RateUnavailableError, match="National Bank of Ukraine"):
        nbu.HryvniaRates().rate_on("UAH", dt.date(2026, 9, 18))


# --- asking one bank, then the other -----------------------------------------


def test_the_chain_stops_at_the_first_source_that_quotes_it(table, monkeypatch):
    calls = serve_nbu(monkeypatch)
    chain = Chain((EcbRates(lambda: table), nbu.HryvniaRates()))

    rate = chain.rate_on("RON", dt.date(2026, 9, 18))

    assert rate.per_euro == Decimal("5.0755")
    assert calls == []


def test_the_chain_falls_through_for_a_currency_the_ecb_skips(table, monkeypatch):
    serve_nbu(monkeypatch)
    chain = Chain((EcbRates(lambda: table), nbu.HryvniaRates()))

    assert chain.rate_on("UAH", dt.date(2026, 9, 18)).per_euro == Decimal("48.5031")


def test_a_currency_one_source_quotes_never_reaches_the_next(table, monkeypatch):
    # The ECB quotes RON, so the Ukrainian bank is never asked about it —
    # whatever date is involved.
    calls = serve_nbu(monkeypatch)
    chain = Chain((EcbRates(lambda: table), nbu.HryvniaRates()))

    chain.rate_on("RON", dt.date(2024, 1, 1))

    assert calls == []


def test_a_currency_no_source_quotes_says_so(table, monkeypatch):
    serve_nbu(monkeypatch)
    chain = Chain((EcbRates(lambda: table), nbu.HryvniaRates()))

    with pytest.raises(CurrencyNotPublishedError, match="VND is not a currency"):
        chain.rate_on("VND", dt.date(2026, 9, 18))


def test_the_table_is_only_fetched_when_something_is_not_in_euro(monkeypatch):
    # A euro receipt asks no rate at all. If the ECB were contacted anyway,
    # an outage there would fail scans that never needed a rate.
    loads = []

    def load():
        loads.append(1)
        return parse_rates(ECB_XML)

    chain = Chain((EcbRates(load), nbu.HryvniaRates()))

    assert loads == []
    chain.rate_on("RON", dt.date(2026, 9, 18))
    assert loads == [1]
