from __future__ import annotations

import csv
import json

import pytest

from google_flights_scraper.cli import build_parser, main

from .conftest import FakeClient, callback_page, make_scraper


def test_parser_defaults():
    args = build_parser().parse_args(["search", "JFK", "LHR", "2026-11-20"])
    assert (args.origin, args.destination, args.depart_date) == ("JFK", "LHR", "2026-11-20")
    assert args.return_date is None
    assert (args.adults, args.children, args.cabin) == (1, 0, "economy")
    assert args.country == "us" and args.sort == "best" and args.format is None


def test_parser_options():
    args = build_parser().parse_args(
        [
            "search",
            "SFO",
            "NRT",
            "2026-12-01",
            "2026-12-15",
            "--adults",
            "2",
            "--cabin",
            "premium-economy",
            "--max-stops",
            "1",
            "--airlines",
            "STAR_ALLIANCE",
            "--sort",
            "price",
            "--limit",
            "5",
        ]
    )
    assert args.return_date == "2026-12-15" and args.max_stops == 1
    assert args.airlines == "STAR_ALLIANCE" and args.limit == 5


@pytest.mark.parametrize(
    "argv",
    [
        ["returns", "JFK", "LHR", "2026-11-20", "2026-11-27"],  # --outbound is required
        ["search", "JFK", "LHR", "2026-11-20", "--max-stops", "3"],
        ["search", "JFK", "LHR", "2026-11-20", "--limit", "0"],
        ["dates", "JFK", "LHR", "2026-11-20"],
    ],
)
def test_parser_rejects(argv):
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_search_json(search_html, capsys):
    scraper = make_scraper(FakeClient([search_html]))
    assert main(["search", "JFK", "LHR", "2026-11-20", "-q"], scraper=scraper) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["query"]["trip"] == "one-way"
    assert len(data["flights"]) == 4
    assert data["price_insights"]["level"] == "high"


def test_search_sort_limit_table(search_html, capsys):
    scraper = make_scraper(FakeClient([search_html]))
    argv = ["search", "JFK", "LHR", "2026-11-20", "--sort", "price", "--limit", "2", "-f", "table"]
    assert main(argv, scraper=scraper) == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert lines[0].startswith("PRICE") and len(lines) == 3
    assert "AA4369 | BA92" in lines[1] and "319" in lines[1]
    assert "4 flights" in captured.err


def test_search_best_only_jsonl(search_html, capsys):
    scraper = make_scraper(FakeClient([search_html]))
    assert (
        main(
            ["search", "JFK", "LHR", "2026-11-20", "--best-only", "-f", "jsonl", "-q"],
            scraper=scraper,
        )
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line)["flight_numbers"] for line in lines] == [["AA142"], ["VS46"]]


def test_search_csv_file(search_html, tmp_path):
    out = tmp_path / "flights.csv"
    scraper = make_scraper(FakeClient([search_html]))
    assert main(["search", "JFK", "LHR", "2026-11-20", "-o", str(out), "-q"], scraper=scraper) == 0
    with open(out, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert rows[2]["layovers"] == "DUB 1h 45m"
    assert rows[0]["emissions_kg"] == "389" and rows[0]["best"] == "true"


def test_returns(search_html, capsys):
    client = FakeClient([search_html, search_html])
    argv = ["returns", "JFK", "LHR", "2026-11-20", "2026-11-27", "--outbound", "AA142", "-q"]
    assert main(argv, scraper=make_scraper(client)) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["direction"] == "return" and data["outbound"] == ["AA142"]
    assert len(client.calls) == 2


def test_booking_round_trip_uses_the_cheapest_return(search_html, booking_html, capsys):
    client = FakeClient([search_html, search_html, booking_html])
    argv = ["booking", "JFK", "LHR", "2026-11-20", "2026-11-27", "--outbound", "AA142"]
    assert main(argv, scraper=make_scraper(client)) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["outbound"] == ["AA142"] and data["inbound"] == ["AA4369", "BA92"]
    assert "using the cheapest return flight AA4369+BA92" in captured.err
    assert len(data["options"]) == 5


def test_booking_csv_one_row_per_fare(search_html, booking_html, capsys):
    client = FakeClient([search_html, booking_html])
    argv = ["booking", "JFK", "LHR", "2026-11-20", "--outbound", "AA142", "-f", "csv", "-q"]
    assert main(argv, scraper=make_scraper(client)) == 0
    rows = list(csv.DictReader(capsys.readouterr().out.splitlines()))
    assert len(rows) == 7  # American's 3 fares + 4 sellers without fare detail
    assert rows[1]["fare"] == "Main Cabin" and rows[1]["fare_price"] == "1121"


def test_unknown_flight_exits_2(search_html, capsys):
    client = FakeClient([search_html])
    argv = ["returns", "JFK", "LHR", "2026-11-20", "2026-11-27", "--outbound", "DL1", "-q"]
    assert main(argv, scraper=make_scraper(client)) == 2
    assert "no flight DL1" in capsys.readouterr().err


def test_query_error_exits_2(capsys):
    client = FakeClient([callback_page([], title="Find Cheap Flights Worldwide")])
    assert main(["search", "XQZ", "LHR", "2026-11-20", "-q"], scraper=make_scraper(client)) == 2
    assert "did not recognise" in capsys.readouterr().err


def test_bad_input_exits_2(capsys):
    assert main(["search", "JFK", "JFK", "2026-11-20"], scraper=make_scraper(FakeClient([]))) == 2
    assert "differ" in capsys.readouterr().err


def test_api_error_exits_1(capsys):
    client = FakeClient([PermissionError("invalid key")])
    assert main(["search", "JFK", "LHR", "2026-11-20", "-q"], scraper=make_scraper(client)) == 1
    assert "PermissionError: invalid key" in capsys.readouterr().err


def test_dates_csv(search_html, capsys):
    client = FakeClient(lambda url, kwargs: search_html)
    argv = ["dates", "JFK", "LHR", "2026-11-20", "2026-11-22", "--stay", "3", "-f", "csv"]
    assert main(argv, scraper=make_scraper(client)) == 0
    captured = capsys.readouterr()
    rows = list(csv.DictReader(captured.out.splitlines()))
    assert [row["depart_date"] for row in rows] == ["2026-11-20", "2026-11-21", "2026-11-22"]
    assert rows[0]["return_date"] == "2026-11-23" and rows[0]["lowest_price"] == "319"
    assert "cheapest: 2026-11-20 at 319 USD" in captured.err
