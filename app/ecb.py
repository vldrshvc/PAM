"""Fetching the European Central Bank's euro reference rates.

Free, no key, no sign-up, and it is the rate a set of Irish books would
actually use. The ninety-day file rather than today's, so a receipt is
converted at the rate that applied on the day it was printed rather than the
day it was photographed.

The file changes once per working day, so it is held in memory and refetched
on a timer. If the ECB cannot be reached the last good copy keeps being used:
a day-old reference rate is a far better answer than refusing to read a
receipt.
"""

import logging
import time

import httpx

from app.config import settings
from app.services.fx import RateTable, RateUnavailableError, parse_rates

logger = logging.getLogger(__name__)

# The published file is around 200 KB; anything far past that is not it.
MAX_BYTES = 4_000_000

_cache: tuple[float, RateTable] | None = None


def _download() -> RateTable:
    with httpx.Client(timeout=settings.fx_timeout_seconds, follow_redirects=True) as client:
        response = client.get(settings.ecb_rates_url)
        response.raise_for_status()
        body = response.content
    if len(body) > MAX_BYTES:
        raise RateUnavailableError("Exchange rate file was unexpectedly large")
    return parse_rates(body)


def get_rates() -> RateTable:
    """The rate table, from memory when it is fresh enough.

    Raises RateUnavailableError only when there is nothing cached to fall
    back on.
    """
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < settings.fx_cache_seconds:
        return _cache[1]
    try:
        table = _download()
    except (httpx.HTTPError, RateUnavailableError) as exc:
        if _cache is not None:
            logger.warning("ECB rates refetch failed (%s); serving the cached table", exc)
            return _cache[1]
        logger.warning("ECB rates unavailable and nothing cached: %s", exc)
        raise RateUnavailableError("Could not get today's exchange rates") from exc
    _cache = (now, table)
    logger.info("ECB rates loaded: %d days, latest %s", len(table), max(table))
    return table


def reset_cache() -> None:
    """Forget the cached table. For tests; nothing in the app calls it."""
    global _cache
    _cache = None
