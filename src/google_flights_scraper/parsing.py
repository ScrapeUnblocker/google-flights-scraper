"""Parse Google Flights pages into typed records.

Results pages carry everything in the ``AF_initDataCallback`` JSON blobs embedded
in the server-rendered HTML: the flight options, price insights, nearby-airport
suggestions and the airlines that serve the route. Booking options are rendered
in the browser, so they are read from the page's accessible labels (``aria-label``
and visible text), which are far steadier than Google's generated CSS class names.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterator, Sequence
from typing import Any

from .models import (
    Airline,
    BookingOption,
    BookingResult,
    Fare,
    Flight,
    Layover,
    NearbyAirport,
    PriceInsights,
    PricePoint,
    SearchResult,
    Segment,
)
from .query import FlightQuery


class GoogleFlightsError(Exception):
    """Base class for errors raised by this package."""


class GoogleFlightsParseError(GoogleFlightsError):
    """The page came back without the data it should hold (worth retrying)."""


class GoogleFlightsBlockedError(GoogleFlightsParseError):
    """Google answered with a CAPTCHA / unusual-traffic page (worth retrying)."""


class GoogleFlightsConsentError(GoogleFlightsError):
    """Google showed its cookie-consent page; route the request through ``us``."""


class GoogleFlightsQueryError(GoogleFlightsError, ValueError):
    """Google Flights rejected the search: unknown airport, past date, gone itinerary."""


_CALLBACK_RE = re.compile(r"AF_initDataCallback\(\{key:\s*'([^']+)'")
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_DECODER = json.JSONDecoder()
_ERROR_MARKER = "travel.frontend.flights.ErrorResponse"
_UNAVAILABLE = "itinerary you selected is no longer available"
_LEGROOM_RE = re.compile(r"(\d+)")
_PRICE_RE = re.compile(r"\bfor ([\d][\d,.]*)\s")
_HEAD_CHARS = 5000  # the consent / CAPTCHA markers sit in the page head


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #


def _at(data: Any, *path: int) -> Any:
    """``data[i][j]...`` that returns None instead of raising on a short/odd branch."""
    for index in path:
        if not isinstance(data, list) or not -len(data) <= index < len(data):
            return None
        data = data[index]
    return data


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _str(value: Any) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def extract_callbacks(html: str) -> dict[str, Any]:
    """Every ``AF_initDataCallback({key: 'ds:N', ..., data: [...]})`` blob, by key."""
    blobs: dict[str, Any] = {}
    for match in _CALLBACK_RE.finditer(html):
        start = html.find("data:", match.end())
        if start < 0:
            continue
        try:
            data, _ = _DECODER.raw_decode(html, start + len("data:"))
        except ValueError:
            continue
        blobs.setdefault(match.group(1), data)
    return blobs


def page_title(html: str) -> str:
    match = _TITLE_RE.search(html)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def check_page(html: str) -> None:
    """Raise if Google answered with a consent wall or a CAPTCHA instead of the page."""
    head = html[:_HEAD_CHARS]
    if "consent.google." in head:
        raise GoogleFlightsConsentError(
            "Google showed its cookie-consent page; route requests through the US "
            "(country='us', the default)"
        )
    if "/sorry/index" in head or "unusual traffic from your computer network" in html:
        raise GoogleFlightsBlockedError("Google answered with an unusual-traffic page")


def _local_time(date: Any, time: Any) -> str | None:
    """``[2026, 11, 20]`` + ``[22, 10]`` -> ``2026-11-20T22:10`` (``[17]`` means 17:00)."""
    if not (
        isinstance(date, list) and len(date) >= 3 and all(isinstance(x, int) for x in date[:3])
    ):
        return None
    stamp = f"{date[0]:04d}-{date[1]:02d}-{date[2]:02d}"
    if not isinstance(time, list):
        return stamp
    hour = time[0] if len(time) > 0 and isinstance(time[0], int) else 0
    minute = time[1] if len(time) > 1 and isinstance(time[1], int) else 0
    return f"{stamp}T{hour:02d}:{minute:02d}"


# --------------------------------------------------------------------------- #
# Results pages
# --------------------------------------------------------------------------- #


def _results_blob(blobs: dict[str, Any]) -> list[Any] | None:
    """The blob holding flight results: ``ds:1`` normally, else the first that fits."""
    candidates = [blobs.get("ds:1")] + [blob for key, blob in blobs.items() if key != "ds:1"]
    for blob in candidates:
        if (
            isinstance(blob, list)
            and len(blob) > 20
            and isinstance(blob[0], list)
            and isinstance(blob[1], list)
        ):
            return blob
    return None


def parse_segment(leg: list[Any]) -> Segment:
    carrier = _at(leg, 22) or []
    code = _str(_at(carrier, 0)) or ""
    number = _str(_at(carrier, 1)) or ""
    legroom = _str(_at(leg, 14))
    inches = _LEGROOM_RE.search(legroom) if legroom else None
    also_sold_as = [
        f"{_at(item, 0)}{_at(item, 1)}"
        for item in _at(leg, 15) or []
        if isinstance(_at(item, 0), str) and isinstance(_at(item, 1), str)
    ]
    return Segment(
        flight_number=f"{code}{number}",
        airline=_str(_at(carrier, 3)),
        airline_code=code,
        operated_by=_str(_at(leg, 2)),
        departure_airport=_str(_at(leg, 3)) or "",
        departure_airport_name=_str(_at(leg, 4)),
        arrival_airport=_str(_at(leg, 6)) or "",
        arrival_airport_name=_str(_at(leg, 5)),
        departure=_local_time(_at(leg, 20), _at(leg, 8)),
        arrival=_local_time(_at(leg, 21), _at(leg, 10)),
        duration_minutes=_int(_at(leg, 11)),
        aircraft=_str(_at(leg, 17)),
        legroom=legroom,
        legroom_inches=int(inches.group(1)) if inches else None,
        emissions_grams=_int(_at(leg, 31)),
        also_sold_as=also_sold_as,
    )


def _layovers(itinerary: list[Any], segments: Sequence[Segment]) -> list[Layover]:
    out = []
    for index, raw in enumerate(_at(itinerary, 13) or []):
        arrived = segments[index] if index < len(segments) else None
        leaving = segments[index + 1] if index + 1 < len(segments) else None
        airport = (arrived.arrival_airport if arrived else None) or _str(_at(raw, 1)) or ""
        departs = (leaving.departure_airport if leaving else None) or _str(_at(raw, 2)) or airport
        out.append(
            Layover(
                airport=airport,
                airport_name=_str(_at(raw, 4)),
                city=_str(_at(raw, 5)),
                duration_minutes=_int(_at(raw, 0)),
                departure_airport=departs,
                change_of_airport=departs != airport,
            )
        )
    return out


def parse_flight(option: list[Any], *, best: bool, currency: str) -> Flight | None:
    """One entry of a results list: ``[itinerary, [[None, price], token], ...]``."""
    itinerary = _at(option, 0)
    legs = _at(itinerary, 2)
    if not isinstance(legs, list) or not legs:
        return None
    segments = [parse_segment(leg) for leg in legs if isinstance(leg, list)]
    emissions = _at(itinerary, 22)
    carrier = _str(_at(itinerary, 0))
    airlines = [name for name in _at(itinerary, 1) or [] if isinstance(name, str)]
    return Flight(
        price=_int(_at(option, 1, 0, 1)),
        currency=currency,
        best=best,
        airlines=airlines,
        airline_code=None if carrier in (None, "multi") else carrier,
        departure_airport=_str(_at(itinerary, 3)) or segments[0].departure_airport,
        departure_airport_name=segments[0].departure_airport_name,
        arrival_airport=_str(_at(itinerary, 6)) or segments[-1].arrival_airport,
        arrival_airport_name=segments[-1].arrival_airport_name,
        departure=_local_time(_at(itinerary, 4), _at(itinerary, 5)) or segments[0].departure,
        arrival=_local_time(_at(itinerary, 7), _at(itinerary, 8)) or segments[-1].arrival,
        duration_minutes=_int(_at(itinerary, 9)),
        stops=max(len(segments) - 1, 0),
        layovers=_layovers(itinerary, segments),
        segments=segments,
        emissions_grams=_int(_at(emissions, 7)),
        typical_emissions_grams=_int(_at(emissions, 8)),
        emissions_diff_percent=_int(_at(emissions, 3)),
    )


def _flights(blob: list[Any], currency: str) -> Iterator[Flight]:
    for index, best in ((2, True), (3, False)):
        for option in _at(blob, index, 0) or []:
            flight = parse_flight(option, best=best, currency=currency)
            if flight is not None:
                yield flight


def parse_price_insights(blob: list[Any], currency: str) -> PriceInsights | None:
    raw = _at(blob, 5)
    if not isinstance(raw, list):
        return None
    history = []
    for point in _at(raw, 10, 0) or []:
        stamp, price = _int(_at(point, 0)), _int(_at(point, 1))
        if stamp is None or price is None:
            continue
        day = dt.datetime.fromtimestamp(stamp / 1000, tz=dt.timezone.utc).date().isoformat()
        history.append(PricePoint(date=day, price=price))
    insights = PriceInsights(
        lowest_price=_int(_at(raw, 1, 1)),
        typical_price=_int(_at(raw, 2, 1)),
        typical_low=_int(_at(raw, 4, 1)),
        typical_high=_int(_at(raw, 5, 1)),
        currency=currency,
        history=history,
    )
    if insights.lowest_price is None and insights.typical_low is None and not history:
        return None
    return insights


def parse_nearby_airports(blob: list[Any]) -> list[NearbyAirport]:
    out = []
    for item in _at(blob, 6, 0, 4, 1) or []:
        code = _str(_at(item, 0))
        if code:
            out.append(
                NearbyAirport(
                    airport=code,
                    price=_int(_at(item, 2, 0, 1)),
                    distance=_str(_at(item, 4)),
                )
            )
    return out


def _airline_pairs(items: Any) -> list[Airline]:
    return [
        Airline(code=item[0], name=item[1])
        for item in items or []
        if isinstance(_at(item, 0), str) and isinstance(_at(item, 1), str)
    ]


def parse_search_page(
    html: str,
    query: FlightQuery,
    url: str = "",
    *,
    direction: str = "outbound",
    outbound: list[str] | None = None,
) -> SearchResult:
    """Parse a ``/travel/flights/search`` page into a :class:`SearchResult`."""
    check_page(html)
    blobs = extract_callbacks(html)
    if not blobs:
        raise GoogleFlightsParseError("no embedded data on the Google Flights page")
    if any(_ERROR_MARKER in json.dumps(blob) for blob in blobs.values()):
        raise GoogleFlightsQueryError(
            "Google Flights rejected the search (is the date in the past or too far ahead?)"
        )
    blob = _results_blob(blobs)
    if blob is None:
        if "Find Cheap Flights" in page_title(html) or blobs.get("ds:1") == []:
            raise GoogleFlightsQueryError(
                f"Google Flights did not recognise {query.origin} -> {query.destination}; "
                "use IATA airport codes (JFK) or city codes (NYC)"
            )
        raise GoogleFlightsParseError("the Google Flights page held no results data")
    return SearchResult(
        query=query,
        url=url,
        direction=direction,
        outbound=outbound,
        flights=list(_flights(blob, query.currency)),
        price_insights=parse_price_insights(blob, query.currency),
        nearby_airports=parse_nearby_airports(blob),
        airlines=_airline_pairs(_at(blob, 7, 1, 1)),
        alliances=_airline_pairs(_at(blob, 7, 1, 0)),
    )


# --------------------------------------------------------------------------- #
# Booking options page (rendered in the browser)
# --------------------------------------------------------------------------- #


def _hidden(text: Any, root: Any) -> bool:
    node = text.parent
    while node is not None and node is not root:
        if node.get("aria-hidden") == "true":
            return True
        node = node.parent
    return False


def _accessible_text(element: Any) -> str:
    """Text a screen reader would announce: skip ``aria-hidden`` duplicates."""
    parts = [
        text.strip()
        for text in element.find_all(string=True)
        if text.strip() and not _hidden(text, element)
    ]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _seller_box(start: Any) -> Any:
    box = start
    while box is not None and getattr(box, "select_one", None) is not None:
        if box.select_one("[data-option-index]") is not None:
            return box
        box = box.parent
    return None


def _fare_card(option: Any) -> Any:
    card = option
    while card.parent is not None and len(card.parent.select("[data-option-index]")) == 1:
        card = card.parent
    return card


def _parse_fare(option: Any, seller: str) -> tuple[Fare, str | None]:
    button = option.find(
        lambda tag: (
            tag.name == "button"
            and str(tag.get("aria-label", "")).startswith("Continue to book with")
        )
    )
    label = str(button.get("aria-label", "")) if button is not None else ""
    rest = label[len("Continue to book with ") :]
    if rest.startswith(seller):
        rest = rest[len(seller) :]
    price_match = _PRICE_RE.search(rest + " ")
    price = int(re.sub(r"[^\d]", "", price_match.group(1).split(".")[0])) if price_match else None
    name = None
    if rest.startswith(", ") and price_match:
        name = rest[2 : price_match.start()].strip() or None
    note = None
    if ". " in rest:
        note = rest.split(". ", 1)[1].strip() or None
    card = _fare_card(option)
    features = []
    for item in card.find_all("li"):
        text = str(item.get("aria-label") or "").strip() or _accessible_text(item)
        if text:
            features.append(text)
    return Fare(name=name, price=price, features=features), note


def _labels(box: Any, seller_text: str) -> list[str]:
    labels = []
    seen_seller = False
    for text in box.stripped_strings:
        if not seen_seller:
            seen_seller = text == seller_text
            continue
        if text == "from" or any(char.isdigit() for char in text):
            break
        labels.append(text)
    return labels


def parse_booking_page(
    html: str,
    query: FlightQuery,
    url: str,
    outbound: list[str],
    inbound: list[str] | None = None,
) -> BookingResult:
    """Parse a rendered ``/travel/flights/booking`` page into a :class:`BookingResult`."""
    from bs4 import BeautifulSoup  # local import keeps results parsing dependency-free

    check_page(html)
    if _UNAVAILABLE in html:
        raise GoogleFlightsQueryError(
            "Google Flights says this itinerary is no longer available; search again"
        )
    soup = BeautifulSoup(html, "html.parser")
    options: list[BookingOption] = []
    seen_boxes: list[Any] = []
    for text in soup.find_all(string=re.compile(r"^\s*Book with\s")):
        seller_text = re.sub(r"\s+", " ", str(text)).strip()
        seller = seller_text[len("Book with ") :].strip()
        box = _seller_box(text.parent)
        if box is None or any(box is seen for seen in seen_boxes):
            continue
        seen_boxes.append(box)
        fares, notes = [], []
        for option in box.select("[data-option-index]"):
            fare, note = _parse_fare(option, seller)
            fares.append(fare)
            if note:
                notes.append(note)
        prices = [fare.price for fare in fares if fare.price is not None]
        labels = _labels(box, seller_text)
        note = notes[0] if notes else None
        # A seller shown collapsed has one unnamed entry: its "from" price, no fare detail.
        listed = [fare for fare in fares if fare.name or fare.features]
        options.append(
            BookingOption(
                seller=seller,
                price=min(prices) if prices else None,
                currency=query.currency,
                labels=labels,
                separate_tickets="Separate tickets" in labels
                or bool(note and "individually" in note),
                note=note,
                fares=listed,
            )
        )
    if not options and "Book with" not in html:
        raise GoogleFlightsParseError("booking options did not load")
    return BookingResult(query=query, url=url, outbound=outbound, inbound=inbound, options=options)
