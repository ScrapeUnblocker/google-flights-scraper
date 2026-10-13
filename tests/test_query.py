from __future__ import annotations

import base64
import datetime as dt
from urllib.parse import parse_qs, urlsplit

import pytest

from google_flights_scraper import FlightQuery, booking_url, encode_tfs, search_url
from google_flights_scraper.query import SegmentRef

# Each of these strings was sent to Google Flights and returned the expected results.
ONE_WAY_BUSINESS_2_ADULTS_NONSTOP = "GhwSCjIwMjYtMTEtMjAoAGoFEgNKRktyBRIDTEhSQAFAAUgDmAEC"
ROUND_TRIP_PINNED_AA142 = (
    "GjsSCjIwMjYtMTEtMjAiHwoDSkZLEgoyMDI2LTExLTIwGgNMSFIqAkFBMgMxNDJqBRIDSkZLcgUSA0xIUhoaEgoy"
    "MDI2LTExLTI3agUSA0xIUnIFEgNKRktAAUgBmAEB"
)
ONE_WAY_DELTA_NONSTOP_WITH_CHILD = "GiASCjIwMjYtMTEtMjAoADICRExqBRIDSkZLcgUSA0xBWEABQAJIAZgBAg"
ONE_WAY_CITY_CODES = "GhoSCjIwMjYtMTEtMjBqBRIDTllDcgUSA0xPTkABSAGYAQI"


def _decode(tfs: str) -> list[tuple[int, object]]:
    """Tiny protobuf reader for the assertions below (varint + length-delimited only)."""
    data = base64.urlsafe_b64decode(tfs + "=" * (-len(tfs) % 4))

    def varint(pos: int) -> tuple[int, int]:
        shift = result = 0
        while True:
            byte = data[pos]
            pos += 1
            result |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                return result, pos

    def read(start: int, end: int) -> list[tuple[int, object]]:
        fields: list[tuple[int, object]] = []
        pos = start
        while pos < end:
            key, pos = varint(pos)
            if key & 7 == 0:
                value, pos = varint(pos)
                fields.append((key >> 3, value))
            else:
                length, pos = varint(pos)
                chunk = data[pos : pos + length]
                try:
                    text = chunk.decode("ascii")
                    nested = not text.isprintable()
                except UnicodeDecodeError:
                    nested = True
                fields.append((key >> 3, read(pos, pos + length) if nested else text))
                pos += length
        return fields

    return read(0, len(data))


def test_golden_one_way_business():
    query = FlightQuery("JFK", "LHR", "2026-11-20", adults=2, cabin="business", max_stops=0)
    assert encode_tfs(query) == ONE_WAY_BUSINESS_2_ADULTS_NONSTOP


def test_golden_round_trip_with_pinned_outbound():
    query = FlightQuery("JFK", "LHR", "2026-11-20", "2026-11-27")
    segment = SegmentRef("JFK", "2026-11-20", "LHR", "AA", "142")
    assert encode_tfs(query, [segment]) == ROUND_TRIP_PINNED_AA142
    # A full flight number ("AA142") is accepted too: the airline prefix is stripped.
    segment = SegmentRef("JFK", "2026-11-20", "LHR", "AA", "AA142")
    assert encode_tfs(query, [segment]) == ROUND_TRIP_PINNED_AA142


def test_golden_airline_filter_and_child():
    query = FlightQuery("JFK", "LAX", "2026-11-20", children=1, max_stops=0, airlines="DL")
    assert encode_tfs(query) == ONE_WAY_DELTA_NONSTOP_WITH_CHILD


def test_golden_city_codes_are_upper_cased():
    assert encode_tfs(FlightQuery("nyc", "lon", "2026-11-20")) == ONE_WAY_CITY_CODES


def test_message_structure():
    query = FlightQuery(
        "SFO",
        "NRT",
        dt.date(2026, 12, 1),
        dt.date(2026, 12, 15),
        adults=2,
        children=1,
        infants_on_lap=1,
        cabin="premium-economy",
        max_stops=1,
        airlines=["star alliance", "ua"],
    )
    fields = _decode(encode_tfs(query))
    legs = [value for number, value in fields if number == 3]
    assert len(legs) == 2
    outbound = dict((n, v) for n, v in legs[0] if n in (2, 5))
    assert outbound == {2: "2026-12-01", 5: 1}
    assert [v for n, v in legs[0] if n == 6] == ["STAR_ALLIANCE", "UA"]
    assert (13, [(2, "SFO")]) in legs[0] and (14, [(2, "NRT")]) in legs[0]
    assert (13, [(2, "NRT")]) in legs[1] and (2, "2026-12-15") in legs[1]
    assert [v for n, v in fields if n == 8] == [1, 1, 2, 4]  # adult, adult, child, lap infant
    assert (9, 2) in fields  # premium economy
    assert (19, 1) in fields  # round trip


def test_urls():
    query = FlightQuery("JFK", "LHR", "2026-11-20", currency="eur")
    parts = urlsplit(search_url(query))
    assert parts.path == "/travel/flights/search"
    params = parse_qs(parts.query)
    assert params["hl"] == ["en"] and params["curr"] == ["EUR"]
    assert params["tfs"] == [encode_tfs(query)]
    segment = SegmentRef("JFK", "2026-11-20", "LHR", "AA", "142")
    assert urlsplit(booking_url(query, [segment])).path == "/travel/flights/booking"


def test_booking_url_needs_every_leg(query):
    segment = SegmentRef("JFK", "2026-11-20", "LHR", "AA", "142")
    with pytest.raises(ValueError, match="return flight"):
        booking_url(query, [segment])
    with pytest.raises(ValueError, match="outbound"):
        booking_url(query, [])


def test_inbound_needs_round_trip(one_way):
    segment = SegmentRef("LHR", "2026-11-27", "JFK", "AA", "103")
    with pytest.raises(ValueError, match="round-trip"):
        encode_tfs(one_way, inbound=[segment])


def test_to_dict(query):
    data = query.to_dict()
    assert data["trip"] == "round-trip"
    assert data["airlines"] == []
    assert data["currency"] == "USD"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"origin": "JF"}, "3-letter"),
        ({"destination": "JFK"}, "differ"),
        ({"depart_date": "20/11/2026"}, "date like"),
        ({"return_date": "2026-11-19"}, "on or after"),
        ({"cabin": "luxury"}, "cabin must be"),
        ({"max_stops": 3}, "max_stops"),
        ({"adults": 0}, "at least one passenger"),
        ({"adults": 1, "infants_on_lap": 2}, "infant on lap"),
        ({"adults": 10}, "at most 9"),
        ({"children": -1}, "negative"),
        ({"airlines": "British Airways"}, "IATA airline code"),
        ({"currency": "dollars"}, "currency"),
    ],
)
def test_validation(kwargs, message):
    base = {"origin": "JFK", "destination": "LHR", "depart_date": "2026-11-20"}
    base.update(kwargs)
    with pytest.raises(ValueError, match=message):
        FlightQuery(**base)


def test_normalisation():
    query = FlightQuery(
        " jfk ", "lhr", "2026-11-20", "", cabin="Premium Economy", airlines="ba, BA,oneworld"
    )
    assert (query.origin, query.destination) == ("JFK", "LHR")
    assert query.return_date is None and not query.round_trip
    assert query.cabin == "premium-economy"
    assert query.airlines == ("BA", "ONEWORLD")
    assert query.passengers == 1
