"""Converting a foreign amount to euro at the rate that applied on the day.

Pure: parsing, picking a day's rate and dividing. Fetching lives in
`app/ecb.py`, the same way the LLM's I/O lives in `app/llm.py`.

The European Central Bank publishes one reference rate per currency per
working day, quoted as units of that currency per euro. There is no rate on a
weekend or a bank holiday, so a Saturday receipt is converted at Friday's
rate — the nearest published day at or before it, which is what an accountant
would do.
"""

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from collections.abc import Callable
from typing import Protocol
from xml.etree import ElementTree

from app.models import quantize_money

# {published day: {currency: units per euro}}
RateTable = dict[dt.date, dict[str, Decimal]]

# Named so the client can say whose rate it showed.
ECB = "ECB"
NBU = "NBU"


class RateUnavailableError(RuntimeError):
    """No rate to convert with, for whatever reason."""


class CurrencyNotPublishedError(RateUnavailableError):
    """This source does not quote that currency at all.

    Kept apart from the plain error because it is the only reason worth
    trying the next source: a currency a source *does* quote but not on some
    day is a gap in that source, not a job for another one.
    """


@dataclass(frozen=True)
class Rate:
    currency: str
    # Units of `currency` per one euro, the convention both banks quote in.
    per_euro: Decimal
    # The day the bank published it, which is not always the receipt's day.
    published: dt.date
    # Which bank said so, because the answer can come from either.
    source: str


def parse_rates(xml: bytes) -> RateTable:
    """Read the ECB's eurofxref file.

    Its shape is nested <Cube> elements: an outer one per day carrying a
    `time`, inner ones carrying `currency` and `rate`. Walking every element
    and keying off the attributes present avoids caring about the two XML
    namespaces it declares.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise RateUnavailableError("Exchange rates could not be read") from exc

    table: RateTable = {}
    day: dt.date | None = None
    for element in root.iter():
        time = element.get("time")
        if time is not None:
            try:
                day = dt.date.fromisoformat(time)
            except ValueError:
                day = None
            if day is not None:
                table.setdefault(day, {})
            continue
        currency, rate = element.get("currency"), element.get("rate")
        if day is None or currency is None or rate is None:
            continue
        try:
            value = Decimal(rate)
        except InvalidOperation:
            continue
        if value > 0:
            table[day][currency.upper()] = value
    if not table:
        raise RateUnavailableError("Exchange rates could not be read")
    return table


def rate_on(table: RateTable, currency: str, on: dt.date) -> Rate:
    """The rate in force on `on`: that day's, or the last one before it."""
    code = currency.upper()
    for day in sorted((d for d in table if d <= on), reverse=True):
        per_euro = table[day].get(code)
        if per_euro is not None:
            return Rate(currency=code, per_euro=per_euro, published=day, source=ECB)
    if any(code in rates for rates in table.values()):
        raise RateUnavailableError(
            f"No {code} rate published on or before {on:%-d %b %Y}"
        )
    raise CurrencyNotPublishedError(f"{code} is not published by the ECB")


def to_euro(amount: Decimal, rate: Rate) -> Decimal:
    """Both sources quote units per euro, so converting to euro is a division."""
    return quantize_money(amount / rate.per_euro)


# --- the hryvnia, which the ECB does not quote ------------------------------

# The National Bank of Ukraine's own directory: official, free, no key, and the
# same standing for the hryvnia that the ECB has for the euro. It answers one
# date at a time and quotes hryvnia per one euro, which is the convention used
# here already.
UAH = "UAH"


def parse_nbu(payload: bytes, asked_for: dt.date) -> Rate:
    """Read one row of the NBU's exchange directory as a euro rate.

    The row is the euro's price in hryvnia, so it *is* the hryvnia's rate per
    euro. `exchangedate` is trusted over the date asked for, because the bank
    answers a weekend with the working day it actually set.
    """
    try:
        rows = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RateUnavailableError("The hryvnia rate could not be read") from exc
    row = next((r for r in rows if isinstance(r, dict) and r.get("cc") == "EUR"), None)
    if row is None:
        raise RateUnavailableError(f"No hryvnia rate published for {asked_for:%-d %b %Y}")
    try:
        per_euro = Decimal(str(row["rate"]))
    except (KeyError, InvalidOperation) as exc:
        raise RateUnavailableError("The hryvnia rate could not be read") from exc
    if per_euro <= 0:
        raise RateUnavailableError("The hryvnia rate could not be read")
    return Rate(
        currency=UAH, per_euro=per_euro, published=parse_nbu_date(row, asked_for), source=NBU
    )


def parse_nbu_date(row: dict, fallback: dt.date) -> dt.date:
    printed = row.get("exchangedate")
    if not isinstance(printed, str):
        return fallback
    try:
        return dt.datetime.strptime(printed.strip(), "%d.%m.%Y").date()
    except ValueError:
        return fallback


# --- asking one source, then the next ---------------------------------------


class RateLookup(Protocol):
    def rate_on(self, currency: str, on: dt.date) -> Rate: ...


@dataclass(frozen=True)
class EcbRates:
    """The ECB's table, wrapped so it can sit in a chain.

    The table is fetched on the first question, not when this is built. Most
    receipts and nearly every notification are in euro and never ask one, and
    an unreachable ECB should not fail a euro scan.
    """

    load: Callable[[], RateTable]

    def rate_on(self, currency: str, on: dt.date) -> Rate:
        return rate_on(self.load(), currency, on)


@dataclass(frozen=True)
class Chain:
    """Each source in turn, moving on only when one does not quote the currency."""

    sources: tuple[RateLookup, ...]

    def rate_on(self, currency: str, on: dt.date) -> Rate:
        for source in self.sources:
            try:
                return source.rate_on(currency, on)
            except CurrencyNotPublishedError:
                continue
        raise CurrencyNotPublishedError(
            f"{currency.upper()} is not a currency PAM has a euro rate for"
        )
