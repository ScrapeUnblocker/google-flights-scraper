from __future__ import annotations

import pytest

from google_flights_scraper import (
    GoogleFlightsBlockedError,
    GoogleFlightsConsentError,
    GoogleFlightsParseError,
    GoogleFlightsQueryError,
    parse_booking_page,
    parse_search_page,
)
from google_flights_scraper.parsing import _local_time, extract_callbacks

from .conftest import callback_page, load_json


def test_search_page_flights(search_html, query):
    result = parse_search_page(search_html, query, "https://example.test/search")
    assert result.url == "https://example.test/search"
    assert result.direction == "outbound"
    assert [flight.flight_numbers for flight in result.flights] == [
        ["AA142"],
        ["VS46"],
        ["EI108", "EI156"],
        ["AA4369", "BA92"],
    ]
    assert [flight.best for flight in result.flights] == [True, True, False, False]


def test_nonstop_flight_fields(search_html, query):
    flight = parse_search_page(search_html, query).flights[0]
    assert flight.price == 878 and flight.currency == "USD"
    assert flight.airlines == ["American"] and flight.airline_code == "AA"
    assert (flight.departure_airport, flight.arrival_airport) == ("JFK", "LHR")
    assert flight.departure_airport_name == "John F. Kennedy International Airport"
    assert flight.departure == "2026-11-20T10:10"
    assert flight.arrival == "2026-11-20T22:10"
    assert flight.duration_minutes == 420
    assert flight.stops == 0 and flight.nonstop and not flight.layovers
    assert (flight.emissions_grams, flight.typical_emissions_grams) == (389000, 432000)
    assert flight.emissions_diff_percent == -10
    segment = flight.segments[0]
    assert segment.aircraft == "Boeing 777"
    assert (segment.legroom, segment.legroom_inches) == ("31 in", 31)
    assert segment.also_sold_as == ["AY3787", "IB4614", "BA1594"]
    assert segment.operated_by is None
    assert segment.date == "2026-11-20"


def test_connecting_flight(search_html, query):
    flight = parse_search_page(search_html, query).flights[2]
    assert flight.stops == 1 and flight.overnight
    assert flight.departure == "2026-11-20T19:25" and flight.arrival == "2026-11-21T10:10"
    (stop,) = flight.layovers
    assert (stop.airport, stop.city, stop.duration_minutes) == ("DUB", "Dublin", 105)
    assert not stop.change_of_airport
    assert [segment.aircraft for segment in flight.segments] == ["Airbus A321neo", "Airbus A320neo"]


def test_multi_airline_flight(search_html, query):
    flight = parse_search_page(search_html, query).flights[3]
    assert flight.airline_code is None  # Google marks mixed-airline itineraries "multi"
    assert flight.airlines == ["American", "British Airways"]
    assert flight.departure_airport == "LGA"
    assert flight.segments[0].operated_by == "Republic Airways as American Eagle"
    data = flight.to_dict()
    assert data["flight_numbers"] == ["AA4369", "BA92"]
    assert data["overnight"] is True


def test_price_insights(search_html, query):
    result = parse_search_page(search_html, query)
    insights = result.price_insights
    assert insights is not None
    assert (insights.lowest_price, insights.typical_price) == (820, 543)
    assert (insights.typical_low, insights.typical_high) == (485, 720)
    assert insights.level == "high"
    assert [point.date for point in insights.history][:2] == ["2026-08-13", "2026-08-14"]
    assert insights.to_dict()["level"] == "high"
    assert result.cheapest is not None and result.cheapest.price == 319


def test_airlines_and_alliances(search_html, query):
    result = parse_search_page(search_html, query)
    assert [airline.code for airline in result.alliances] == [
        "ONEWORLD",
        "SKYTEAM",
        "STAR_ALLIANCE",
    ]
    assert result.airlines[0].code == "EI" and result.airlines[0].name == "Aer Lingus"
    assert len(result.best_flights) == 2
    assert result.to_dict()["query"]["origin"] == "JFK"


def test_no_results_with_nearby_airports(nearby_html, one_way):
    result = parse_search_page(nearby_html, one_way)
    assert result.flights == [] and result.cheapest is None
    assert result.price_insights is None
    assert [(item.airport, item.price, item.distance) for item in result.nearby_airports] == [
        ("LGA", 681, "11 mi"),
        ("EWR", 679, "21 mi"),
        ("ABE", 785, "87 mi"),
    ]


def test_unknown_airport_is_a_query_error(one_way):
    html = callback_page(
        [], title="Find Cheap Flights Worldwide &amp; Book Your Ticket - Google Flights"
    )
    with pytest.raises(GoogleFlightsQueryError, match="did not recognise"):
        parse_search_page(html, one_way)


def test_rejected_search_is_a_query_error(one_way):
    error = [3, None, [["type.googleapis.com/travel.frontend.flights.ErrorResponse", [[None], 2]]]]
    with pytest.raises(GoogleFlightsQueryError, match="rejected"):
        parse_search_page(callback_page(error), one_way)


def test_consent_page(one_way):
    html = '<html><head><base href="https://consent.google.com/"></head><body></body></html>'
    with pytest.raises(GoogleFlightsConsentError):
        parse_search_page(html, one_way)


def test_captcha_page_is_retryable(one_way):
    html = (
        "<html><body>Our systems have detected unusual traffic from your computer network."
        "</body></html>"
    )
    with pytest.raises(GoogleFlightsBlockedError) as caught:
        parse_search_page(html, one_way)
    assert isinstance(caught.value, GoogleFlightsParseError)


def test_page_without_data(one_way):
    with pytest.raises(GoogleFlightsParseError):
        parse_search_page("<html><title>Google Flights</title></html>", one_way)
    with pytest.raises(GoogleFlightsParseError, match="no results"):
        parse_search_page(callback_page([1, 2, 3]), one_way)


def test_extract_callbacks_handles_braces_in_strings():
    html = callback_page(["a } b", {"x": "y)"}], key="ds:0") + callback_page([1], key="ds:1")
    assert extract_callbacks(html) == {"ds:0": ["a } b", {"x": "y)"}], "ds:1": [1]}


def test_local_time():
    assert _local_time([2026, 11, 20], [17]) == "2026-11-20T17:00"
    assert _local_time([2026, 11, 20], [None, 30]) == "2026-11-20T00:30"
    assert _local_time([2026, 1, 2], None) == "2026-01-02"
    assert _local_time(None, [10, 5]) is None


def test_fixture_blob_is_a_list():
    assert isinstance(load_json("search_ds1.json"), list)


# --------------------------------------------------------------------------- #
# Booking options
# --------------------------------------------------------------------------- #


def test_booking_options(booking_html, query):
    result = parse_booking_page(booking_html, query, "u", ["AA142"], ["AA103"])
    assert [option.seller for option in result.options] == [
        "American",
        "British Airways",
        "Iberia, American",
        "Iberia",
        "Finnair",
    ]
    assert [option.price for option in result.options] == [881, 890, 1402, 881, 881]
    assert all(option.airline_direct for option in result.options)
    assert result.cheapest is not None and result.cheapest.seller == "American"
    assert result.to_dict()["inbound"] == ["AA103"]


def test_booking_fares(booking_html, query):
    american = parse_booking_page(booking_html, query, "u", ["AA142"], ["AA103"]).options[0]
    assert [(fare.name, fare.price) for fare in american.fares] == [
        ("Basic Economy", 881),
        ("Main Cabin", 1121),
        ("Main Plus", 1361),
    ]
    basic, main, _plus = american.fares
    assert "No refunds" in basic.features
    # Screen-reader text wins over the visual duplicate ("1st checked bag: $170").
    assert basic.features[-1] == "First checked bag costs 170 US dollars"
    assert main.features[-1] == "First checked bag is free"


def test_booking_separate_tickets(booking_html, query):
    option = parse_booking_page(booking_html, query, "u", ["AA142"], ["AA103"]).options[2]
    assert option.separate_tickets
    assert option.labels == ["Airline", "Separate tickets"]
    assert option.note == "The 2 tickets in your itinerary must be booked individually"
    assert option.fares == []  # collapsed sellers show a price but no fare detail


def test_booking_unavailable_itinerary(query):
    html = "<html><body>Sorry, the itinerary you selected is no longer available</body></html>"
    with pytest.raises(GoogleFlightsQueryError, match="no longer available"):
        parse_booking_page(html, query, "u", ["AA142"], ["AA103"])


def test_booking_page_not_loaded(query):
    with pytest.raises(GoogleFlightsParseError):
        parse_booking_page("<html><body>Loading results</body></html>", query, "u", ["AA142"])
