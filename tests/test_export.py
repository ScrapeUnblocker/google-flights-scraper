from __future__ import annotations

import csv
import json

from google_flights_scraper import parse_booking_page, parse_search_page
from google_flights_scraper.export import (
    BOOKING_COLUMNS,
    FLIGHT_COLUMNS,
    booking_rows,
    csv_string,
    flight_row,
    format_duration,
    table,
    to_json,
    to_jsonl,
    write_csv,
    write_json,
)


def test_format_duration():
    assert format_duration(605) == "10h 05m"
    assert format_duration(45) == "0h 45m"
    assert format_duration(None) == ""


def test_flight_row(search_html, query):
    flight = parse_search_page(search_html, query).flights[3]
    row = flight_row(flight)
    assert set(row) == set(FLIGHT_COLUMNS)
    assert row["airlines"] == "American | British Airways"
    assert row["flight_numbers"] == "AA4369 | BA92"
    assert row["operated_by"] == "Republic Airways as American Eagle"
    assert row["stops"] == 1 and row["overnight"] is True


def test_booking_rows(booking_html, query):
    result = parse_booking_page(booking_html, query, "u", ["AA142"], ["AA103"])
    rows = booking_rows(result.options)
    assert [row["fare"] for row in rows[:3]] == ["Basic Economy", "Main Cabin", "Main Plus"]
    assert rows[3]["seller"] == "British Airways" and rows[3]["fare_price"] == 890
    assert rows[4]["separate_tickets"] is True


def test_csv_string_cells():
    text = csv_string([{"a": None, "b": True, "c": 3}], ("a", "b", "c"))
    assert list(csv.reader(text.splitlines())) == [["a", "b", "c"], ["", "true", "3"]]


def test_write_csv_has_bom(tmp_path, booking_html, query):
    result = parse_booking_page(booking_html, query, "u", ["AA142"], ["AA103"])
    path = tmp_path / "booking.csv"
    assert write_csv(booking_rows(result.options), path, BOOKING_COLUMNS) == 7
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_json_outputs(tmp_path, search_html, query):
    result = parse_search_page(search_html, query)
    assert json.loads(to_json(result))["direction"] == "outbound"
    assert len(json.loads(to_json(result.flights))) == 4
    assert len(to_jsonl(result.flights).splitlines()) == 4
    path = tmp_path / "result.json"
    write_json(result, path)
    assert json.loads(path.read_text(encoding="utf-8"))["query"]["destination"] == "LHR"


def test_table():
    text = table(
        [{"price": 820, "airlines": "Aer Lingus"}, {"price": None, "airlines": "KLM"}],
        ("price", "airlines"),
    )
    assert text.splitlines() == ["PRICE  AIRLINES", "820    Aer Lingus", "       KLM"]
