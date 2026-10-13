"""Typed records returned by :class:`~google_flights_scraper.GoogleFlightsScraper`.

Times are the local times at each airport, as ISO 8601 strings without an offset
(``2026-11-20T22:10``). Prices are totals for every passenger in the search, in the
query's currency; for a round trip they are the round-trip total.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .query import FlightQuery


@dataclass
class Segment:
    """One flown leg of an itinerary (a single takeoff and landing)."""

    flight_number: str
    airline: str | None
    airline_code: str
    operated_by: str | None
    departure_airport: str
    departure_airport_name: str | None
    arrival_airport: str
    arrival_airport_name: str | None
    departure: str | None
    arrival: str | None
    duration_minutes: int | None
    aircraft: str | None = None
    legroom: str | None = None
    legroom_inches: int | None = None
    emissions_grams: int | None = None
    also_sold_as: list[str] = field(default_factory=list)

    @property
    def date(self) -> str | None:
        return self.departure[:10] if self.departure else None


@dataclass
class Layover:
    """A connection between two segments."""

    airport: str
    airport_name: str | None
    city: str | None
    duration_minutes: int | None
    departure_airport: str
    change_of_airport: bool = False


@dataclass
class Flight:
    """One itinerary option as Google Flights lists it."""

    price: int | None
    currency: str
    best: bool
    airlines: list[str]
    airline_code: str | None
    departure_airport: str
    departure_airport_name: str | None
    arrival_airport: str
    arrival_airport_name: str | None
    departure: str | None
    arrival: str | None
    duration_minutes: int | None
    stops: int
    layovers: list[Layover] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    emissions_grams: int | None = None
    typical_emissions_grams: int | None = None
    emissions_diff_percent: int | None = None

    @property
    def flight_numbers(self) -> list[str]:
        return [segment.flight_number for segment in self.segments]

    @property
    def nonstop(self) -> bool:
        return self.stops == 0

    @property
    def overnight(self) -> bool:
        """True when the flight lands on a later calendar day than it departs."""
        return bool(self.departure and self.arrival and self.arrival[:10] > self.departure[:10])

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["flight_numbers"] = self.flight_numbers
        data["overnight"] = self.overnight
        return data


@dataclass
class PricePoint:
    date: str
    price: int


@dataclass
class PriceInsights:
    """Google's price context for the route: is today's lowest price low, typical or high?"""

    lowest_price: int | None
    typical_price: int | None
    typical_low: int | None
    typical_high: int | None
    currency: str
    history: list[PricePoint] = field(default_factory=list)

    @property
    def level(self) -> str | None:
        """``low`` / ``typical`` / ``high``: the lowest price against the typical range."""
        if None in (self.lowest_price, self.typical_low, self.typical_high):
            return None
        if self.lowest_price < self.typical_low:
            return "low"
        if self.lowest_price > self.typical_high:
            return "high"
        return "typical"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["level"] = self.level
        return data


@dataclass
class NearbyAirport:
    """An alternative airport Google suggests when no flight matches the search."""

    airport: str
    price: int | None
    distance: str | None


@dataclass
class Airline:
    code: str
    name: str


@dataclass
class SearchResult:
    """One results page: departing flights, or return flights for a chosen outbound."""

    query: FlightQuery
    url: str
    direction: str  # "outbound" or "return"
    flights: list[Flight] = field(default_factory=list)
    price_insights: PriceInsights | None = None
    nearby_airports: list[NearbyAirport] = field(default_factory=list)
    airlines: list[Airline] = field(default_factory=list)
    alliances: list[Airline] = field(default_factory=list)
    outbound: list[str] | None = None  # flight numbers of the pinned outbound flight

    @property
    def best_flights(self) -> list[Flight]:
        return [flight for flight in self.flights if flight.best]

    @property
    def cheapest(self) -> Flight | None:
        priced = [flight for flight in self.flights if flight.price is not None]
        return min(priced, key=lambda flight: flight.price) if priced else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "url": self.url,
            "direction": self.direction,
            "outbound": self.outbound,
            "flights": [flight.to_dict() for flight in self.flights],
            "price_insights": self.price_insights.to_dict() if self.price_insights else None,
            "nearby_airports": [asdict(item) for item in self.nearby_airports],
            "airlines": [asdict(item) for item in self.airlines],
            "alliances": [asdict(item) for item in self.alliances],
        }


@dataclass
class Fare:
    """A fare (Basic Economy, Main Cabin, ...) offered by one booking option."""

    name: str | None
    price: int | None
    features: list[str] = field(default_factory=list)


@dataclass
class BookingOption:
    """Somewhere to book the chosen itinerary: an airline or an online travel agency."""

    seller: str
    price: int | None
    currency: str
    labels: list[str] = field(default_factory=list)
    separate_tickets: bool = False
    note: str | None = None
    fares: list[Fare] = field(default_factory=list)

    @property
    def airline_direct(self) -> bool:
        return "Airline" in self.labels

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["airline_direct"] = self.airline_direct
        return data


@dataclass
class BookingResult:
    query: FlightQuery
    url: str
    outbound: list[str]
    inbound: list[str] | None
    options: list[BookingOption] = field(default_factory=list)

    @property
    def cheapest(self) -> BookingOption | None:
        priced = [option for option in self.options if option.price is not None]
        return min(priced, key=lambda option: option.price) if priced else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "url": self.url,
            "outbound": self.outbound,
            "inbound": self.inbound,
            "options": [option.to_dict() for option in self.options],
        }


@dataclass
class DatePrice:
    """The cheapest option found for one departure date in a date sweep."""

    depart_date: str
    return_date: str | None
    currency: str
    lowest_price: int | None = None
    price_level: str | None = None
    flights_found: int = 0
    cheapest: Flight | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cheapest"] = self.cheapest.to_dict() if self.cheapest else None
        return data
