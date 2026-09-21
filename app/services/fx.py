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
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from app.models import quantize_money

# {published day: {currency: units per euro}}
RateTable = dict[dt.date, dict[str, Decimal]]


class RateUnavailableError(RuntimeError):
    """No rate to convert with: unknown currency, or none published in range."""


@dataclass(frozen=True)
class Rate:
    currency: str
    # Units of `currency` per one euro, exactly as the ECB quotes it.
    per_euro: Decimal
    # The day the ECB published it, which is not always the receipt's day.
    published: dt.date


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
            return Rate(currency=code, per_euro=per_euro, published=day)
    if any(code in rates for rates in table.values()):
        raise RateUnavailableError(
            f"No {code} rate published on or before {on:%-d %b %Y}"
        )
    raise RateUnavailableError(f"{code} is not a currency the ECB publishes a euro rate for")


def to_euro(amount: Decimal, rate: Rate) -> Decimal:
    """The ECB quotes units per euro, so converting to euro is a division."""
    return quantize_money(amount / rate.per_euro)
