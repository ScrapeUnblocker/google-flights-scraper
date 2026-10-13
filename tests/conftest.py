"""Shared fixtures: trimmed real Google Flights data and a fake ScrapeUnblocker client.

``fixtures/search_ds1.json`` and ``fixtures/nearby_ds1.json`` are the results blob of
real Google Flights pages, trimmed to a few flights with long tokens replaced by
``"TOKEN"``. ``fixtures/booking.html`` is the rendered booking-options panel of a
real page with only the accessible attributes kept.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from google_flights_scraper import FlightQuery, GoogleFlightsScraper

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def callback_page(
    data: Any, *, key: str = "ds:1", title: str = "New York to London | Google Flights"
) -> str:
    """A minimal results page embedding ``data`` the way Google Flights does."""
    blob = json.dumps(data, ensure_ascii=False)
    return (
        f'<!DOCTYPE html><html lang="en"><head><base href="https://www.google.com/">'
        f"<title>{title}</title></head><body>"
        f"<script class=\"{key}\">AF_initDataCallback({{key: '{key}', hash: '1', "
        f"data:{blob}, sideChannel: {{}}}});</script></body></html>"
    )


class FakeTimeout(Exception):
    """Stands in for a transient ScrapeUnblocker error."""


class StepFailedError(Exception):
    """Same name as the SDK's StepFailedError (matched by name), with ``.html``."""

    def __init__(self, message: str, html: str = "") -> None:
        super().__init__(message)
        self.html = html


class FakeClient:
    """Replays canned responses; records every call.

    ``responses`` is a list (served in order) or a callable ``(url, kwargs) -> item``.
    An item that is an exception instance is raised instead of returned.
    """

    def __init__(self, responses: list[Any] | Callable[[str, dict[str, Any]], Any]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_page_source(self, url: str, **kwargs: Any) -> Any:
        self.calls.append((url, kwargs))
        if callable(self._responses):
            item = self._responses(url, kwargs)
        else:
            item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def make_scraper(client: FakeClient, **options: Any) -> GoogleFlightsScraper:
    options.setdefault("transient_errors", (FakeTimeout,))
    options.setdefault("sleep", lambda seconds: None)
    return GoogleFlightsScraper(client=client, **options)


@pytest.fixture
def search_html() -> str:
    return callback_page(load_json("search_ds1.json"))


@pytest.fixture
def nearby_html() -> str:
    return callback_page(load_json("nearby_ds1.json"), title="Los Angeles to New York")


@pytest.fixture
def booking_html() -> str:
    return (FIXTURES / "booking.html").read_text(encoding="utf-8")


@pytest.fixture
def query() -> FlightQuery:
    return FlightQuery("JFK", "LHR", "2026-11-20", "2026-11-27")


@pytest.fixture
def one_way() -> FlightQuery:
    return FlightQuery("JFK", "LHR", "2026-11-20")
