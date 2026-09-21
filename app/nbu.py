"""Fetching the hryvnia's euro rate from the National Bank of Ukraine.

The ECB does not quote the hryvnia, so it gets its own central bank: free, no
key, no sign-up, and the same standing for UAH that the ECB has for the euro.

It answers one date at a time rather than handing over a file, so each answer
is cached under the day it is for. A past day's rate never changes, and the
current one is set once in the morning, so a cached answer stays right.

Only the hryvnia goes through here. Any other currency the ECB does not quote
is reported as unsupported rather than guessed at through a cross rate.
"""

import datetime as dt
import logging

import httpx

from app.config import settings
from app.services.fx import (
    UAH,
    CurrencyNotPublishedError,
    Rate,
    RateUnavailableError,
    parse_nbu,
)

logger = logging.getLogger(__name__)

# One row of JSON; anything far past this is not the bank's answer.
MAX_BYTES = 200_000

_cache: dict[dt.date, Rate] = {}


def _download(on: dt.date) -> Rate:
    params = {"json": "", "valcode": "EUR", "date": on.strftime("%Y%m%d")}
    with httpx.Client(timeout=settings.fx_timeout_seconds, follow_redirects=True) as client:
        response = client.get(settings.nbu_rates_url, params=params)
        response.raise_for_status()
        body = response.content
    if len(body) > MAX_BYTES:
        raise RateUnavailableError("The hryvnia rate could not be read")
    return parse_nbu(body, on)


class HryvniaRates:
    """A rate source for UAH alone, so it can sit in the chain after the ECB."""

    def rate_on(self, currency: str, on: dt.date) -> Rate:
        if currency.upper() != UAH:
            raise CurrencyNotPublishedError(f"{currency.upper()} is not published by the NBU")
        if on in _cache:
            return _cache[on]
        try:
            rate = _download(on)
        except httpx.HTTPError as exc:
            raise RateUnavailableError("Could not reach the National Bank of Ukraine") from exc
        _cache[on] = rate
        logger.info("NBU rate for %s: %s UAH per euro (set %s)", on, rate.per_euro, rate.published)
        return rate


def reset_cache() -> None:
    """Forget the cached rates. For tests; nothing in the app calls it."""
    _cache.clear()
