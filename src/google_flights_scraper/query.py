"""Describe a Google Flights search and turn it into a Google Flights URL.

Google Flights keeps the whole search (airports, dates, passengers, cabin, stops,
airlines and any flights already picked) in one ``tfs`` query parameter: a small
protobuf message, base64url-encoded. :func:`encode_tfs` writes that message with a
few lines of plain Python, so there is no protobuf dependency.
"""

from __future__ import annotations

import base64
import datetime as dt
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Union
from urllib.parse import urlencode

BASE_URL = "https://www.google.com/travel/flights"

#: Cabin names accepted by :class:`FlightQuery`, mapped to Google's cabin codes.
CABINS = {"economy": 1, "premium-economy": 2, "business": 3, "first": 4}

#: Airline alliances Google Flights accepts in the airlines filter.
ALLIANCES = ("ONEWORLD", "SKYTEAM", "STAR_ALLIANCE")

_ADULT, _CHILD, _INFANT_IN_SEAT, _INFANT_ON_LAP = 1, 2, 3, 4
_ROUND_TRIP, _ONE_WAY = 1, 2

_CODE_RE = re.compile(r"^[A-Z]{3}$")
_AIRLINE_RE = re.compile(r"^[A-Z0-9]{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

DateLike = Union[str, dt.date]


def _iso_date(value: DateLike, name: str) -> str:
    if isinstance(value, dt.datetime):
        value = value.date()
    if isinstance(value, dt.date):
        return value.isoformat()
    try:
        return dt.date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise ValueError(f"{name} must be a date like 2026-11-20, got {value!r}") from None


def _cabin_key(value: str) -> str:
    key = str(value).strip().lower().replace("_", "-").replace(" ", "-")
    if key not in CABINS:
        raise ValueError(f"cabin must be one of {', '.join(CABINS)}; got {value!r}")
    return key


def _airline_list(values: Iterable[str] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = values.split(",")
    out: list[str] = []
    for raw in values:
        code = re.sub(r"[\s-]+", "_", str(raw).strip().upper())
        if not code:
            continue
        if code in ("STAR", "STARALLIANCE"):
            code = "STAR_ALLIANCE"
        elif code in ("ONE_WORLD", "SKY_TEAM"):
            code = code.replace("_", "")
        if code not in ALLIANCES and not _AIRLINE_RE.match(code):
            raise ValueError(
                f"airline filter {raw!r} is not a 2-character IATA airline code "
                f"(BA, DL, 6E, ...) or an alliance ({', '.join(ALLIANCES)})"
            )
        if code not in out:
            out.append(code)
    return tuple(out)


@dataclass(frozen=True)
class FlightQuery:
    """One Google Flights search.

    ``origin`` / ``destination`` are IATA airport codes (``JFK``) or metropolitan
    city codes that cover several airports (``NYC``, ``LON``, ``PAR``). Leave
    ``return_date`` empty for a one-way trip. Prices Google returns are totals for
    every passenger in the query.
    """

    origin: str
    destination: str
    depart_date: str
    return_date: str | None = None
    adults: int = 1
    children: int = 0
    infants_in_seat: int = 0
    infants_on_lap: int = 0
    cabin: str = "economy"
    max_stops: int | None = None
    airlines: tuple[str, ...] = field(default_factory=tuple)
    currency: str = "USD"

    def __post_init__(self) -> None:
        set_ = object.__setattr__  # frozen dataclass: normalise in place
        for name in ("origin", "destination"):
            code = str(getattr(self, name) or "").strip().upper()
            if not _CODE_RE.match(code):
                raise ValueError(f"{name} must be a 3-letter airport or city code, got {code!r}")
            set_(self, name, code)
        if self.origin == self.destination:
            raise ValueError("origin and destination must differ")
        set_(self, "depart_date", _iso_date(self.depart_date, "depart_date"))
        if self.return_date in (None, ""):
            set_(self, "return_date", None)
        else:
            set_(self, "return_date", _iso_date(self.return_date, "return_date"))
            if self.return_date < self.depart_date:
                raise ValueError("return_date must be on or after depart_date")
        for name in ("adults", "children", "infants_in_seat", "infants_on_lap"):
            count = int(getattr(self, name))
            if count < 0:
                raise ValueError(f"{name} cannot be negative")
            set_(self, name, count)
        if self.passengers < 1:
            raise ValueError("a search needs at least one passenger")
        if self.passengers > 9:
            raise ValueError("Google Flights allows at most 9 passengers per search")
        if self.infants_on_lap > self.adults:
            raise ValueError("each infant on lap needs an adult")
        set_(self, "cabin", _cabin_key(self.cabin))
        if self.max_stops is not None:
            stops = int(self.max_stops)
            if not 0 <= stops <= 2:
                raise ValueError("max_stops must be 0 (nonstop), 1 or 2")
            set_(self, "max_stops", stops)
        set_(self, "airlines", _airline_list(self.airlines))
        currency = str(self.currency or "USD").strip().upper()
        if not _CURRENCY_RE.match(currency):
            raise ValueError(
                f"currency must be a 3-letter ISO code (USD, EUR, ...), got {currency!r}"
            )
        set_(self, "currency", currency)

    @property
    def round_trip(self) -> bool:
        return self.return_date is not None

    @property
    def passengers(self) -> int:
        return self.adults + self.children + self.infants_in_seat + self.infants_on_lap

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "depart_date": self.depart_date,
            "return_date": self.return_date,
            "trip": "round-trip" if self.round_trip else "one-way",
            "adults": self.adults,
            "children": self.children,
            "infants_in_seat": self.infants_in_seat,
            "infants_on_lap": self.infants_on_lap,
            "cabin": self.cabin,
            "max_stops": self.max_stops,
            "airlines": list(self.airlines),
            "currency": self.currency,
        }


@dataclass(frozen=True)
class SegmentRef:
    """The fields Google needs to pin one flight segment in a ``tfs`` search."""

    departure_airport: str
    date: str
    arrival_airport: str
    airline_code: str
    flight_number: str  # the number only, e.g. "142" for AA142


SegmentLike = Any  # a SegmentRef, or any object with the same attributes (e.g. a Segment)


# --------------------------------------------------------------------------- #
# Protobuf writer (just the wire types the tfs message uses)
# --------------------------------------------------------------------------- #


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _int_field(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _bytes_field(number: int, value: bytes | str) -> bytes:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return _varint((number << 3) | 2) + _varint(len(data)) + data


def _segment_ref(segment: SegmentLike) -> bytes:
    flight_number = str(segment.flight_number)
    airline = str(segment.airline_code)
    if flight_number.upper().startswith(airline.upper()):
        flight_number = flight_number[len(airline) :]
    date = getattr(segment, "date", None) or str(segment.departure)[:10]
    return (
        _bytes_field(1, segment.departure_airport)
        + _bytes_field(2, date)
        + _bytes_field(3, segment.arrival_airport)
        + _bytes_field(5, airline)
        + _bytes_field(6, flight_number)
    )


def _leg(
    date: str,
    origin: str,
    destination: str,
    query: FlightQuery,
    selected: Sequence[SegmentLike] = (),
) -> bytes:
    body = _bytes_field(2, date)
    for segment in selected:
        body += _bytes_field(4, _segment_ref(segment))
    if query.max_stops is not None:
        body += _int_field(5, query.max_stops)
    for airline in query.airlines:
        body += _bytes_field(6, airline)
    body += _bytes_field(13, _bytes_field(2, origin))
    body += _bytes_field(14, _bytes_field(2, destination))
    return body


def encode_tfs(
    query: FlightQuery,
    outbound: Sequence[SegmentLike] = (),
    inbound: Sequence[SegmentLike] = (),
) -> str:
    """Encode ``query`` as the value of Google Flights' ``tfs`` URL parameter.

    ``outbound`` / ``inbound`` pin already chosen flight segments: pin the outbound
    flight to list matching return flights, pin both to open booking options.
    """
    legs = [_leg(query.depart_date, query.origin, query.destination, query, outbound)]
    if query.round_trip:
        legs.append(_leg(query.return_date, query.destination, query.origin, query, inbound))
    elif inbound:
        raise ValueError("inbound segments need a round-trip query (set return_date)")
    message = b"".join(_bytes_field(3, leg) for leg in legs)
    passengers = (
        [_ADULT] * query.adults
        + [_CHILD] * query.children
        + [_INFANT_IN_SEAT] * query.infants_in_seat
        + [_INFANT_ON_LAP] * query.infants_on_lap
    )
    message += b"".join(_int_field(8, code) for code in passengers)
    message += _int_field(9, CABINS[query.cabin])
    message += _int_field(19, _ROUND_TRIP if query.round_trip else _ONE_WAY)
    return base64.urlsafe_b64encode(message).decode("ascii").rstrip("=")


def _url(page: str, tfs: str, currency: str) -> str:
    return f"{BASE_URL}/{page}?" + urlencode({"tfs": tfs, "hl": "en", "curr": currency})


def search_url(query: FlightQuery, outbound: Sequence[SegmentLike] = ()) -> str:
    """URL of the results page: departing flights, or return flights once
    ``outbound`` is pinned."""
    return _url("search", encode_tfs(query, outbound), query.currency)


def booking_url(
    query: FlightQuery,
    outbound: Sequence[SegmentLike],
    inbound: Sequence[SegmentLike] = (),
) -> str:
    """URL of the booking options page for a fully chosen itinerary."""
    if not outbound:
        raise ValueError("booking options need the outbound flight segments")
    if query.round_trip and not inbound:
        raise ValueError("a round trip needs the return flight segments too")
    return _url("booking", encode_tfs(query, outbound, inbound), query.currency)
