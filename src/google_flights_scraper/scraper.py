"""Scrape Google Flights through the ScrapeUnblocker ``getPageSource`` API.

:class:`GoogleFlightsScraper` builds the Google Flights URL for a search, fetches
it through ScrapeUnblocker and parses the embedded results. The booking options
page is rendered in a real browser (a ``wait_for_text`` step) because Google loads
it after the first paint. Timeouts, transient API errors and pages that come back
without their data are retried with doubling backoff.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, Callable, TypeVar

from .models import BookingResult, DatePrice, Flight, SearchResult
from .parsing import (
    GoogleFlightsError,
    GoogleFlightsParseError,
    GoogleFlightsQueryError,
    parse_booking_page,
    parse_search_page,
)
from .query import DateLike, FlightQuery, booking_url, search_url

T = TypeVar("T")

_TRANSIENT_NAMES = (
    "UpstreamOutageError",
    "RateLimitError",
    "ScrapeTimeoutError",
    "BrowserTimeoutError",
    "BlockedError",
    "ServerError",
    "ConnectionError",
)
_STEP_FAILED = "StepFailedError"
_UNAVAILABLE = "itinerary you selected is no longer available"

#: Booking options appear a few seconds after the page loads.
BOOKING_READY_TEXT = "Book with"
BOOKING_TIMEOUT_MS = 25000

#: Upper bound for one date sweep (one search per date).
MAX_SWEEP_DATES = 60


class FlightNotFoundError(GoogleFlightsError, LookupError):
    """No flight in the results matches the requested flight numbers."""


def _transient_errors() -> tuple[type[BaseException], ...]:
    """Best-effort tuple of ScrapeUnblocker exceptions worth retrying.

    Imported lazily so the package is usable (and unit-testable) even when the
    ``scrapeunblocker`` SDK is not installed.
    """
    try:
        import scrapeunblocker  # type: ignore
    except Exception:  # pragma: no cover - depends on SDK availability
        return ()
    found = (getattr(scrapeunblocker, name, None) for name in _TRANSIENT_NAMES)
    return tuple(cls for cls in found if isinstance(cls, type))


def _is_named(error: BaseException, name: str) -> bool:
    return any(cls.__name__ == name for cls in type(error).__mro__)


def _flight_tokens(spec: str | Sequence[str]) -> list[str]:
    parts = re.split(r"[,+/]", spec) if isinstance(spec, str) else list(spec)
    tokens = [re.sub(r"\s+", "", str(part)).upper() for part in parts]
    tokens = [token for token in tokens if token]
    if not tokens:
        raise ValueError("give at least one flight number, e.g. 'AA142' or 'EI104+EI152'")
    return tokens


def find_flight(flights: Iterable[Flight], spec: str | Sequence[str]) -> Flight:
    """Pick the flight whose flight numbers match ``spec``.

    ``spec`` is ``"AA142"``, ``"EI104+EI152"`` (every segment, in order) or a list of
    flight numbers. An exact match wins; otherwise the first flight whose segments
    start with the given numbers.
    """
    wanted = _flight_tokens(spec)
    flights = list(flights)
    for flight in flights:
        if [number.upper() for number in flight.flight_numbers] == wanted:
            return flight
    for flight in flights:
        if [number.upper() for number in flight.flight_numbers[: len(wanted)]] == wanted:
            return flight
    listed = ", ".join("+".join(flight.flight_numbers) for flight in flights[:12])
    raise FlightNotFoundError(
        f"no flight {'+'.join(wanted)} in these results"
        + (f" (found: {listed}...)" if listed else "")
    )


def date_range(start: DateLike, end: DateLike) -> list[str]:
    """Every date from ``start`` to ``end`` inclusive, as ISO strings."""
    first = dt.date.fromisoformat(str(start)[:10])
    last = dt.date.fromisoformat(str(end)[:10])
    if last < first:
        raise ValueError("the end date is before the start date")
    return [
        (first + dt.timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)
    ]


class GoogleFlightsScraper:
    """Search Google Flights, list return flights and read booking options.

    Args:
        api_key: ScrapeUnblocker key. If omitted, the SDK reads
            ``SCRAPEUNBLOCKER_KEY`` from the environment.
        client: A pre-built client (or any object exposing
            ``get_page_source(url, proxy_country=..., steps=...)``). Mainly for testing.
        country: Country to route requests through. Defaults to ``us``: Google shows a
            cookie-consent page instead of results to many European routes.
        retries: Extra attempts per request on transient failures.
        backoff: Seconds before the first retry; doubles on every further retry.
        max_backoff: Upper bound for a single wait between retries.
        timeout: Per-request timeout passed to the SDK client.
        transient_errors: Exception classes treated as retryable. Defaults to
            the ScrapeUnblocker transient set.
        on_retry: Optional callback ``(attempt, delay_seconds, error)`` invoked
            before every retry (handy for progress output).
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any | None = None,
        country: str | None = "us",
        retries: int = 3,
        backoff: float = 5.0,
        max_backoff: float = 60.0,
        timeout: float = 180.0,
        transient_errors: Sequence[type[BaseException]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_retry: Callable[[int, float, BaseException], None] | None = None,
    ) -> None:
        if client is None:
            from scrapeunblocker import Client  # local import: optional dep

            client = Client(api_key=api_key, timeout=timeout)
        self._client = client
        self.country = (country or "").strip().lower() or None
        self.retries = max(0, int(retries))
        self.backoff = float(backoff)
        self.max_backoff = float(max_backoff)
        self.on_retry = on_retry
        transient = tuple(transient_errors) if transient_errors is not None else _transient_errors()
        self._api_transient = transient
        self._transient = (*transient, GoogleFlightsParseError)
        self._sleep = sleep

    # ------------------------------------------------------------------ #
    # Fetching
    # ------------------------------------------------------------------ #

    def _retry(self, action: Callable[[], T]) -> T:
        """Run ``action``, retrying transient failures with doubling backoff."""
        attempt = 0
        while True:
            try:
                return action()
            except Exception as exc:
                if not isinstance(exc, self._transient) or attempt >= self.retries:
                    raise
                attempt += 1
                delay = min(self.backoff * 2 ** (attempt - 1), self.max_backoff)
                if self.on_retry is not None:
                    self.on_retry(attempt, delay, exc)
                self._sleep(delay)

    def fetch(self, url: str, steps: list[dict[str, Any]] | None = None) -> str:
        """One getPageSource call: the HTML of a Google Flights page."""
        options: dict[str, Any] = {}
        if self.country:
            options["proxy_country"] = self.country
        if steps:
            options["steps"] = steps
        html = self._client.get_page_source(url, **options)
        return html if isinstance(html, str) else ""

    def _fetch_booking(self, url: str) -> str:
        steps = [
            {
                "action": "wait_for_text",
                "value": BOOKING_READY_TEXT,
                "timeout_ms": BOOKING_TIMEOUT_MS,
            }
        ]
        try:
            return self.fetch(url, steps)
        except Exception as exc:
            if not _is_named(exc, _STEP_FAILED):
                raise
            partial = getattr(exc, "html", None) or ""
            if _UNAVAILABLE in partial:
                raise GoogleFlightsQueryError(
                    "Google Flights says this itinerary is no longer available; search again"
                ) from exc
            raise GoogleFlightsParseError("booking options did not load in time") from exc

    # ------------------------------------------------------------------ #
    # Searching
    # ------------------------------------------------------------------ #

    def search(
        self,
        origin: str,
        destination: str,
        depart_date: DateLike,
        return_date: DateLike | None = None,
        **options: Any,
    ) -> SearchResult:
        """Search departing flights. ``options`` are :class:`FlightQuery` fields
        (``adults``, ``children``, ``cabin``, ``max_stops``, ``airlines``, ``currency``, ...).
        """
        query = FlightQuery(origin, destination, depart_date, return_date, **options)
        return self.search_query(query)

    def search_query(self, query: FlightQuery) -> SearchResult:
        """Departing flights for ``query``; prices are round-trip totals on a round trip."""
        url = search_url(query)
        result = self._retry(lambda: parse_search_page(self.fetch(url), query, url))
        return self._apply_stop_limit(result)

    def return_flights(self, query: FlightQuery, outbound: Flight) -> SearchResult:
        """Return flights that pair with ``outbound`` (prices are round-trip totals)."""
        if not query.round_trip:
            raise ValueError("return flights need a round-trip query (set return_date)")
        url = search_url(query, outbound.segments)
        numbers = outbound.flight_numbers
        result = self._retry(
            lambda: parse_search_page(
                self.fetch(url), query, url, direction="return", outbound=numbers
            )
        )
        return self._apply_stop_limit(result)

    def booking_options(
        self,
        query: FlightQuery,
        outbound: Flight,
        inbound: Flight | None = None,
    ) -> BookingResult:
        """Where to book the chosen itinerary: airlines and travel agencies, with fares."""
        if query.round_trip and inbound is None:
            raise ValueError("a round trip needs the return flight too (see return_flights)")
        url = booking_url(query, outbound.segments, inbound.segments if inbound else ())
        out_numbers = outbound.flight_numbers
        in_numbers = inbound.flight_numbers if inbound else None
        return self._retry(
            lambda: parse_booking_page(
                self._fetch_booking(url), query, url, out_numbers, in_numbers
            )
        )

    def date_sweep(
        self,
        query: FlightQuery,
        depart_dates: Iterable[DateLike],
        *,
        stay_days: int | None = None,
        workers: int = 1,
        on_date: Callable[[DatePrice], None] | None = None,
    ) -> list[DatePrice]:
        """Search every departure date and keep the cheapest option for each.

        On a round trip the trip length of ``query`` is kept unless ``stay_days``
        is given; ``stay_days`` also turns a one-way query into a round trip.
        A date that fails is reported with ``error`` set instead of stopping the sweep.
        """
        dates = [dt.date.fromisoformat(str(day)[:10]) for day in depart_dates]
        if not dates:
            return []
        if len(dates) > MAX_SWEEP_DATES:
            raise ValueError(f"a sweep covers at most {MAX_SWEEP_DATES} dates")
        if stay_days is None and query.round_trip:
            stay_days = (
                dt.date.fromisoformat(query.return_date) - dt.date.fromisoformat(query.depart_date)
            ).days
        if stay_days is not None and stay_days < 0:
            raise ValueError("stay_days cannot be negative")
        recoverable = (GoogleFlightsError, *self._api_transient)

        def one(day: dt.date) -> DatePrice:
            back = (
                (day + dt.timedelta(days=stay_days)).isoformat() if stay_days is not None else None
            )
            row = DatePrice(depart_date=day.isoformat(), return_date=back, currency=query.currency)
            try:
                result = self.search_query(
                    replace(query, depart_date=row.depart_date, return_date=back)
                )
            except recoverable as exc:
                row.error = f"{type(exc).__name__}: {exc}"
            else:
                cheapest = result.cheapest
                row.lowest_price = cheapest.price if cheapest else None
                row.cheapest = cheapest
                row.flights_found = len(result.flights)
                row.price_level = result.price_insights.level if result.price_insights else None
            if on_date is not None:
                on_date(row)
            return row

        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            return list(pool.map(one, dates))

    @staticmethod
    def _apply_stop_limit(result: SearchResult) -> SearchResult:
        limit: int | None = result.query.max_stops
        if limit is not None:
            result.flights = [flight for flight in result.flights if flight.stops <= limit]
        return result
