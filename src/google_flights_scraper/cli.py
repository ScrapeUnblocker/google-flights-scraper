"""Command-line interface: ``google-flights-scraper <command> ...``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable, TextIO

from . import __version__
from .export import (
    BOOKING_COLUMNS,
    DATE_COLUMNS,
    FLIGHT_COLUMNS,
    booking_rows,
    csv_string,
    date_row,
    flight_row,
    table,
    to_json,
    to_jsonl,
)
from .models import Flight, SearchResult
from .parsing import GoogleFlightsError, GoogleFlightsQueryError
from .query import ALLIANCES, CABINS, FlightQuery
from .scraper import MAX_SWEEP_DATES, GoogleFlightsScraper, date_range, find_flight

FORMATS_OUT = ("json", "jsonl", "csv", "table")
_EXTENSIONS = {".json": "json", ".jsonl": "jsonl", ".csv": "csv", ".txt": "table"}

FLIGHT_TABLE = (
    "price",
    "airlines",
    "flight_numbers",
    "departure",
    "arrival",
    "duration",
    "stops",
    "layovers",
    "emissions_kg",
)
BOOKING_TABLE = ("seller", "fare", "fare_price", "separate_tickets", "features")
DATE_TABLE = (
    "depart_date",
    "return_date",
    "lowest_price",
    "price_level",
    "airlines",
    "flight_numbers",
    "stops",
    "duration",
    "error",
)

SORTS: dict[str, Callable[[Flight], Any] | None] = {
    "best": None,  # Google's own order: "best" flights first
    "price": lambda flight: (flight.price is None, flight.price or 0),
    "duration": lambda flight: (flight.duration_minutes is None, flight.duration_minutes or 0),
    "departure": lambda flight: flight.departure or "",
    "arrival": lambda flight: flight.arrival or "",
    "stops": lambda flight: flight.stops,
    "emissions": lambda flight: (flight.emissions_grams is None, flight.emissions_grams or 0),
}


def _stdout() -> TextIO:
    """stdout that always accepts UTF-8 (Windows consoles default to a legacy codepage)."""
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # pragma: no cover - exotic streams
            pass
    return stream


def _log(args: argparse.Namespace, message: str) -> None:
    if not getattr(args, "quiet", False):
        print(message, file=sys.stderr, flush=True)


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _count(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("cannot be negative")
    return number


def _add_route(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("origin", help="Departure airport or city code (JFK, NYC, ...)")
    parser.add_argument("destination", help="Arrival airport or city code (LHR, LON, ...)")


def _add_query_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("search options")
    group.add_argument("--adults", type=_count, default=1, help="Adults (default 1)")
    group.add_argument("--children", type=_count, default=0, help="Children aged 2-11")
    group.add_argument("--infants-in-seat", type=_count, default=0, help="Infants with a seat")
    group.add_argument("--infants-on-lap", type=_count, default=0, help="Infants on lap")
    group.add_argument("--cabin", choices=tuple(CABINS), default="economy", help="Cabin class")
    group.add_argument(
        "--max-stops",
        type=int,
        choices=(0, 1, 2),
        help="0 = nonstop only, 1 = at most one stop, 2 = at most two stops",
    )
    group.add_argument(
        "--airlines",
        metavar="CODES",
        help="Only these airlines or alliances, comma-separated: BA,AA or " + ",".join(ALLIANCES),
    )
    group.add_argument("--currency", default="USD", help="Price currency (default USD)")


def _add_output(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("output")
    group.add_argument(
        "-f",
        "--format",
        choices=FORMATS_OUT,
        help="Output format (default: from the --output extension, else json)",
    )
    group.add_argument("-o", "--output", help="Write to this file instead of stdout")
    group.add_argument("--pretty", action="store_true", help="Indent JSON output")
    group.add_argument(
        "--country",
        metavar="CODE",
        default="us",
        help="Country to route requests through (default us; many European routes "
        "get Google's cookie-consent page instead of results)",
    )
    group.add_argument("--retries", type=int, default=3, help="Retries per request (default 3)")
    group.add_argument("-q", "--quiet", action="store_true", help="No progress on stderr")


def _add_listing(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("listing")
    group.add_argument("--sort", choices=tuple(SORTS), default="best", help="Sort flights")
    group.add_argument("--limit", type=_positive, help="Keep only the first N flights")
    group.add_argument("--best-only", action="store_true", help="Only Google's 'best' flights")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="google-flights-scraper",
        description="Scrape Google Flights results, return flights, booking options and "
        "cheapest dates via ScrapeUnblocker.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser(
        "search",
        help="Departing flights for a one-way or round trip",
        description="Departing flights with prices, plus Google's price insights. On a round "
        "trip the prices are round-trip totals.",
    )
    _add_route(search)
    search.add_argument("depart_date", help="Departure date (YYYY-MM-DD)")
    search.add_argument("return_date", nargs="?", help="Return date for a round trip")
    _add_query_options(search)
    _add_listing(search)
    _add_output(search)

    returns = sub.add_parser(
        "returns",
        help="Return flights that pair with a chosen outbound flight",
        description="Searches the outbound flights, pins the one you name and lists the "
        "matching return flights with round-trip prices.",
    )
    _add_route(returns)
    returns.add_argument("depart_date", help="Departure date (YYYY-MM-DD)")
    returns.add_argument("return_date", help="Return date (YYYY-MM-DD)")
    returns.add_argument(
        "--outbound", required=True, help="Outbound flight number(s): AA142 or EI104+EI152"
    )
    _add_query_options(returns)
    _add_listing(returns)
    _add_output(returns)

    booking = sub.add_parser(
        "booking",
        help="Where to book a chosen itinerary: sellers, fares and prices",
        description="Booking options (airlines and travel agencies) for the flights you name, "
        "with fare names, prices and fare rules where Google lists them.",
    )
    _add_route(booking)
    booking.add_argument("depart_date", help="Departure date (YYYY-MM-DD)")
    booking.add_argument("return_date", nargs="?", help="Return date for a round trip")
    booking.add_argument(
        "--outbound", required=True, help="Outbound flight number(s): AA142 or EI104+EI152"
    )
    booking.add_argument(
        "--inbound",
        help="Return flight number(s) on a round trip (default: the cheapest return flight)",
    )
    _add_query_options(booking)
    _add_output(booking)

    dates = sub.add_parser(
        "dates",
        help="Cheapest price for every departure date in a range",
        description=f"Runs one search per departure date (at most {MAX_SWEEP_DATES}) and "
        "reports the cheapest flight for each.",
    )
    _add_route(dates)
    dates.add_argument("start", help="First departure date (YYYY-MM-DD)")
    dates.add_argument("end", help="Last departure date (YYYY-MM-DD)")
    dates.add_argument(
        "--stay", type=_count, metavar="DAYS", help="Round trip: return this many days later"
    )
    dates.add_argument(
        "--workers", type=_positive, default=3, help="Dates searched in parallel (default 3)"
    )
    _add_query_options(dates)
    _add_output(dates)
    return parser


def _query(args: argparse.Namespace, depart: str, back: str | None) -> FlightQuery:
    return FlightQuery(
        origin=args.origin,
        destination=args.destination,
        depart_date=depart,
        return_date=back,
        adults=args.adults,
        children=args.children,
        infants_in_seat=args.infants_in_seat,
        infants_on_lap=args.infants_on_lap,
        cabin=args.cabin,
        max_stops=args.max_stops,
        airlines=args.airlines or (),
        currency=args.currency,
    )


def _format(args: argparse.Namespace) -> str:
    if args.format:
        return args.format
    if args.output:
        return _EXTENSIONS.get(Path(args.output).suffix.lower(), "json")
    return "json"


def _emit(args: argparse.Namespace, text: str) -> None:
    if args.output:
        encoding = "utf-8-sig" if _format(args) == "csv" else "utf-8"
        with open(args.output, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        _log(args, f"wrote {args.output}")
    else:
        _stdout().write(text)


def _listed(result: SearchResult, args: argparse.Namespace) -> SearchResult:
    flights = result.flights
    if args.best_only:
        flights = [flight for flight in flights if flight.best]
    key = SORTS[args.sort]
    if key is not None:
        flights = sorted(flights, key=key)
    if args.limit:
        flights = flights[: args.limit]
    result.flights = flights
    return result


def _output_flights(args: argparse.Namespace, result: SearchResult) -> None:
    fmt = _format(args)
    if fmt == "json":
        _emit(args, to_json(result, pretty=args.pretty) + "\n")
    elif fmt == "jsonl":
        _emit(args, to_jsonl(result.flights))
    else:
        rows = [flight_row(flight) for flight in result.flights]
        if fmt == "csv":
            _emit(args, csv_string(rows, FLIGHT_COLUMNS))
        else:
            _emit(args, table(rows, FLIGHT_TABLE))


def _summary(args: argparse.Namespace, result: SearchResult) -> None:
    what = "return flights" if result.direction == "return" else "flights"
    message = f"{len(result.flights)} {what}"
    insights = result.price_insights
    if insights and insights.level:
        message += (
            f"; lowest {insights.lowest_price} {insights.currency} is {insights.level} "
            f"(typical {insights.typical_low}-{insights.typical_high})"
        )
    if not result.flights and result.nearby_airports:
        nearby = ", ".join(f"{item.airport} ({item.price})" for item in result.nearby_airports[:5])
        message += f"; nearby airports with flights: {nearby}"
    _log(args, message)


def _make_scraper(args: argparse.Namespace) -> GoogleFlightsScraper:
    def on_retry(attempt: int, delay: float, error: BaseException) -> None:
        _log(args, f"retry {attempt} in {delay:.0f}s ({type(error).__name__}: {error})")

    return GoogleFlightsScraper(country=args.country, retries=args.retries, on_retry=on_retry)


def _run_search(args: argparse.Namespace, scraper: GoogleFlightsScraper) -> None:
    query = _query(args, args.depart_date, args.return_date)
    _log(args, f"searching {query.origin} -> {query.destination} on {query.depart_date}")
    result = scraper.search_query(query)
    _summary(args, result)
    _output_flights(args, _listed(result, args))


def _outbound(
    args: argparse.Namespace, scraper: GoogleFlightsScraper, query: FlightQuery
) -> Flight:
    _log(args, f"finding outbound {args.outbound} on {query.depart_date}")
    flight = find_flight(scraper.search_query(query).flights, args.outbound)
    _log(args, f"outbound {'+'.join(flight.flight_numbers)} departs {flight.departure}")
    return flight


def _run_returns(args: argparse.Namespace, scraper: GoogleFlightsScraper) -> None:
    query = _query(args, args.depart_date, args.return_date)
    outbound = _outbound(args, scraper, query)
    result = scraper.return_flights(query, outbound)
    _summary(args, result)
    _output_flights(args, _listed(result, args))


def _run_booking(args: argparse.Namespace, scraper: GoogleFlightsScraper) -> None:
    query = _query(args, args.depart_date, args.return_date)
    outbound = _outbound(args, scraper, query)
    inbound = None
    if query.round_trip:
        returns = scraper.return_flights(query, outbound)
        if args.inbound:
            inbound = find_flight(returns.flights, args.inbound)
        else:
            inbound = returns.cheapest
            if inbound is None:
                raise GoogleFlightsQueryError("no priced return flight pairs with that outbound")
            _log(args, f"using the cheapest return flight {'+'.join(inbound.flight_numbers)}")
    _log(args, "loading booking options")
    result = scraper.booking_options(query, outbound, inbound)
    _log(args, f"{len(result.options)} booking options")
    fmt = _format(args)
    if fmt == "json":
        _emit(args, to_json(result, pretty=args.pretty) + "\n")
    elif fmt == "jsonl":
        _emit(args, to_jsonl(result.options))
    elif fmt == "csv":
        _emit(args, csv_string(booking_rows(result.options), BOOKING_COLUMNS))
    else:
        _emit(args, table(booking_rows(result.options), BOOKING_TABLE))


def _run_dates(args: argparse.Namespace, scraper: GoogleFlightsScraper) -> None:
    days = date_range(args.start, args.end)
    if len(days) > MAX_SWEEP_DATES:
        raise ValueError(f"a sweep covers at most {MAX_SWEEP_DATES} dates")
    query = _query(args, days[0], None)

    def on_date(row: Any) -> None:
        price = row.error or f"{row.lowest_price} {row.currency}"
        _log(args, f"{row.depart_date}: {price}")

    rows = scraper.date_sweep(
        query, days, stay_days=args.stay, workers=args.workers, on_date=on_date
    )
    priced = [row for row in rows if row.lowest_price is not None]
    if priced:
        best = min(priced, key=lambda row: row.lowest_price)
        _log(args, f"cheapest: {best.depart_date} at {best.lowest_price} {best.currency}")
    fmt = _format(args)
    if fmt == "json":
        _emit(args, to_json(rows, pretty=args.pretty) + "\n")
    elif fmt == "jsonl":
        _emit(args, to_jsonl(rows))
    elif fmt == "csv":
        _emit(args, csv_string([date_row(row) for row in rows], DATE_COLUMNS))
    else:
        _emit(args, table([date_row(row) for row in rows], DATE_TABLE))


_COMMANDS = {
    "search": _run_search,
    "returns": _run_returns,
    "booking": _run_booking,
    "dates": _run_dates,
}


def main(argv: Sequence[str] | None = None, scraper: GoogleFlightsScraper | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _COMMANDS[args.command](args, scraper or _make_scraper(args))
    except (GoogleFlightsQueryError, ValueError, LookupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except GoogleFlightsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 130
    except Exception as exc:  # SDK errors: bad key, out of credit, network, ...
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
