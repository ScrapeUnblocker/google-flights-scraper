"""Scrape Google Flights into clean JSON / CSV with the ScrapeUnblocker API.

Search one-way and round-trip flights (passengers, cabin, stops, airline and
alliance filters, any currency), list the return flights that pair with a chosen
outbound flight, read booking options (airlines and travel agencies, fares and
fare rules) and sweep a range of dates for the cheapest day to fly.

    >>> from google_flights_scraper import GoogleFlightsScraper
    >>> scraper = GoogleFlightsScraper()  # reads SCRAPEUNBLOCKER_KEY
    >>> result = scraper.search("JFK", "LHR", "2026-11-20", max_stops=0)
    >>> result.cheapest.price, result.price_insights.level

Pages are fetched with ScrapeUnblocker's ``getPageSource`` endpoint:
https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos
"""

from .models import (
    Airline,
    BookingOption,
    BookingResult,
    DatePrice,
    Fare,
    Flight,
    Layover,
    NearbyAirport,
    PriceInsights,
    PricePoint,
    SearchResult,
    Segment,
)
from .parsing import (
    GoogleFlightsBlockedError,
    GoogleFlightsConsentError,
    GoogleFlightsError,
    GoogleFlightsParseError,
    GoogleFlightsQueryError,
    parse_booking_page,
    parse_search_page,
)
from .query import ALLIANCES, CABINS, FlightQuery, booking_url, encode_tfs, search_url
from .scraper import FlightNotFoundError, GoogleFlightsScraper, date_range, find_flight

__version__ = "0.1.0"

__all__ = [
    "ALLIANCES",
    "CABINS",
    "Airline",
    "BookingOption",
    "BookingResult",
    "DatePrice",
    "Fare",
    "Flight",
    "FlightNotFoundError",
    "FlightQuery",
    "GoogleFlightsBlockedError",
    "GoogleFlightsConsentError",
    "GoogleFlightsError",
    "GoogleFlightsParseError",
    "GoogleFlightsQueryError",
    "GoogleFlightsScraper",
    "Layover",
    "NearbyAirport",
    "PriceInsights",
    "PricePoint",
    "SearchResult",
    "Segment",
    "__version__",
    "booking_url",
    "date_range",
    "encode_tfs",
    "find_flight",
    "parse_booking_page",
    "parse_search_page",
    "search_url",
]
