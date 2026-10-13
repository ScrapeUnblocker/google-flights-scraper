from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from google_flights_scraper import (
    FlightNotFoundError,
    FlightQuery,
    GoogleFlightsParseError,
    GoogleFlightsQueryError,
    date_range,
    encode_tfs,
    find_flight,
)
from google_flights_scraper.scraper import BOOKING_READY_TEXT, MAX_SWEEP_DATES

from .conftest import FakeClient, FakeTimeout, StepFailedError, callback_page, make_scraper


def _tfs(url: str) -> str:
    return parse_qs(urlsplit(url).query)["tfs"][0]


def test_search_fetches_the_search_url_through_the_us(search_html, query):
    client = FakeClient([search_html])
    result = make_scraper(client).search_query(query)
    ((url, kwargs),) = client.calls
    assert urlsplit(url).path == "/travel/flights/search"
    assert _tfs(url) == encode_tfs(query)
    assert kwargs == {"proxy_country": "us"}
    assert len(result.flights) == 4 and result.url == url


def test_search_convenience_builds_the_query(search_html):
    client = FakeClient([search_html])
    result = make_scraper(client, country=None).search("jfk", "lhr", "2026-11-20", cabin="first")
    assert result.query.cabin == "first" and result.query.origin == "JFK"
    assert client.calls[0][1] == {}  # no route forced when country=None


def test_max_stops_is_enforced_on_the_results(search_html):
    query = FlightQuery("JFK", "LHR", "2026-11-20", max_stops=0)
    result = make_scraper(FakeClient([search_html])).search_query(query)
    assert [flight.stops for flight in result.flights] == [0, 0]


def test_retries_transient_errors_with_backoff(search_html, query):
    waits, retries = [], []
    client = FakeClient([FakeTimeout("slow"), FakeTimeout("slow"), search_html])
    scraper = make_scraper(
        client, sleep=waits.append, on_retry=lambda attempt, delay, error: retries.append(attempt)
    )
    assert scraper.search_query(query).flights
    assert waits == [5.0, 10.0] and retries == [1, 2]


def test_retries_pages_without_data(search_html, query):
    client = FakeClient(["<html><title>Google Flights</title></html>", search_html])
    assert make_scraper(client).search_query(query).flights
    assert len(client.calls) == 2


def test_gives_up_after_the_retry_budget(query):
    client = FakeClient([FakeTimeout("1"), FakeTimeout("2")])
    with pytest.raises(FakeTimeout):
        make_scraper(client, retries=1).search_query(query)


def test_query_errors_are_not_retried(query):
    client = FakeClient([callback_page([], title="Find Cheap Flights Worldwide")])
    with pytest.raises(GoogleFlightsQueryError):
        make_scraper(client).search_query(query)
    assert len(client.calls) == 1


def test_other_errors_are_not_retried(query):
    client = FakeClient([PermissionError("bad key")])
    with pytest.raises(PermissionError):
        make_scraper(client).search_query(query)


def test_return_flights_pin_the_outbound_segments(search_html, query):
    client = FakeClient([search_html, search_html])
    scraper = make_scraper(client)
    outbound = find_flight(scraper.search_query(query).flights, "EI108+EI156")
    result = scraper.return_flights(query, outbound)
    assert result.direction == "return" and result.outbound == ["EI108", "EI156"]
    pinned = encode_tfs(query, outbound.segments)
    assert _tfs(client.calls[1][0]) == pinned


def test_return_flights_need_a_round_trip(search_html, one_way):
    scraper = make_scraper(FakeClient([search_html]))
    flight = scraper.search_query(one_way).flights[0]
    with pytest.raises(ValueError, match="round-trip"):
        scraper.return_flights(one_way, flight)


def test_booking_options_render_with_a_wait_step(search_html, booking_html, query):
    client = FakeClient([search_html, booking_html])
    scraper = make_scraper(client)
    flights = scraper.search_query(query).flights
    result = scraper.booking_options(query, flights[0], flights[1])
    url, kwargs = client.calls[1]
    assert urlsplit(url).path == "/travel/flights/booking"
    assert kwargs["steps"][0]["action"] == "wait_for_text"
    assert kwargs["steps"][0]["value"] == BOOKING_READY_TEXT
    assert result.outbound == ["AA142"] and result.inbound == ["VS46"]
    assert len(result.options) == 5


def test_booking_options_need_the_return_flight(search_html, query):
    scraper = make_scraper(FakeClient([search_html]))
    flight = scraper.search_query(query).flights[0]
    with pytest.raises(ValueError, match="return flight"):
        scraper.booking_options(query, flight)


def test_booking_wait_timeout_is_retried(search_html, booking_html, one_way):
    client = FakeClient(
        [search_html, StepFailedError("timeout", html="<html></html>"), booking_html]
    )
    scraper = make_scraper(client)
    flight = scraper.search_query(one_way).flights[0]
    assert scraper.booking_options(one_way, flight).options
    assert len(client.calls) == 3


def test_booking_unavailable_itinerary_is_not_retried(search_html, one_way):
    gone = StepFailedError(
        "timeout", html="Sorry, the itinerary you selected is no longer available"
    )
    client = FakeClient([search_html, gone])
    scraper = make_scraper(client)
    flight = scraper.search_query(one_way).flights[0]
    with pytest.raises(GoogleFlightsQueryError, match="no longer available"):
        scraper.booking_options(one_way, flight)
    assert len(client.calls) == 2


def test_booking_gives_up_with_a_parse_error(search_html, one_way):
    client = FakeClient([search_html] + [StepFailedError("timeout")] * 2)
    scraper = make_scraper(client, retries=1)
    flight = scraper.search_query(one_way).flights[0]
    with pytest.raises(GoogleFlightsParseError, match="did not load"):
        scraper.booking_options(one_way, flight)


def test_find_flight(search_html, query):
    flights = make_scraper(FakeClient([search_html])).search_query(query).flights
    assert find_flight(flights, "aa142").flight_numbers == ["AA142"]
    assert find_flight(flights, "EI108 + EI156").flight_numbers == ["EI108", "EI156"]
    assert find_flight(flights, "EI108").flight_numbers == ["EI108", "EI156"]  # prefix match
    assert find_flight(flights, ["AA4369", "BA92"]).airlines == ["American", "British Airways"]
    with pytest.raises(FlightNotFoundError, match="found: AA142"):
        find_flight(flights, "DL1")
    with pytest.raises(ValueError):
        find_flight(flights, " , ")


def test_date_range():
    assert date_range("2026-11-29", "2026-12-02") == [
        "2026-11-29",
        "2026-11-30",
        "2026-12-01",
        "2026-12-02",
    ]
    with pytest.raises(ValueError):
        date_range("2026-12-02", "2026-12-01")


def test_date_sweep(search_html, nearby_html):
    def respond(url, kwargs):
        tfs = _tfs(url)
        if tfs == encode_tfs(FlightQuery("JFK", "LHR", "2026-11-21", "2026-11-25")):
            return nearby_html  # no flights that day
        if tfs == encode_tfs(FlightQuery("JFK", "LHR", "2026-11-22", "2026-11-26")):
            return callback_page([], title="Find Cheap Flights Worldwide")
        return search_html

    seen = []
    scraper = make_scraper(FakeClient(respond))
    query = FlightQuery("JFK", "LHR", "2026-11-20")
    rows = scraper.date_sweep(
        query, date_range("2026-11-20", "2026-11-22"), stay_days=4, workers=2, on_date=seen.append
    )
    assert [row.depart_date for row in rows] == ["2026-11-20", "2026-11-21", "2026-11-22"]
    assert [row.return_date for row in rows] == ["2026-11-24", "2026-11-25", "2026-11-26"]
    assert rows[0].lowest_price == 319 and rows[0].price_level == "high"
    assert rows[0].cheapest is not None and rows[0].flights_found == 4
    assert rows[1].lowest_price is None and rows[1].error is None
    assert rows[2].error and rows[2].error.startswith("GoogleFlightsQueryError")
    assert len(seen) == 3
    assert rows[0].to_dict()["cheapest"]["flight_numbers"] == ["AA4369", "BA92"]


def test_date_sweep_keeps_the_trip_length(search_html):
    scraper = make_scraper(FakeClient(lambda url, kwargs: search_html))
    query = FlightQuery("JFK", "LHR", "2026-11-20", "2026-11-23")
    (row,) = scraper.date_sweep(query, ["2026-12-01"])
    assert row.return_date == "2026-12-04"


def test_date_sweep_limits(search_html):
    scraper = make_scraper(FakeClient(lambda url, kwargs: search_html))
    query = FlightQuery("JFK", "LHR", "2026-11-20")
    assert scraper.date_sweep(query, []) == []
    too_many = date_range("2026-11-01", "2027-01-31")
    assert len(too_many) > MAX_SWEEP_DATES
    with pytest.raises(ValueError, match="at most"):
        scraper.date_sweep(query, too_many)
