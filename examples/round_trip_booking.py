"""Price a round trip end to end: outbound -> matching return -> where to book it.

Picks the cheapest nonstop outbound flight, the cheapest return flight that pairs
with it, then lists every booking option Google shows (airline or travel agency,
fare names, fare rules and prices).

    python examples/round_trip_booking.py JFK LHR --stay 7
"""

from __future__ import annotations

import argparse
import datetime as dt

from google_flights_scraper import FlightQuery, GoogleFlightsScraper


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("origin", nargs="?", default="JFK")
    parser.add_argument("destination", nargs="?", default="LHR")
    parser.add_argument("--days-ahead", type=int, default=45)
    parser.add_argument("--stay", type=int, default=7)
    args = parser.parse_args()

    depart = dt.date.today() + dt.timedelta(days=args.days_ahead)
    query = FlightQuery(
        args.origin,
        args.destination,
        depart,
        depart + dt.timedelta(days=args.stay),
        max_stops=0,
    )
    scraper = GoogleFlightsScraper()

    outbound = scraper.search_query(query).cheapest
    if outbound is None:
        raise SystemExit("no nonstop flights on this route; try another date or drop max_stops")
    print(
        f"Outbound {'+'.join(outbound.flight_numbers)}  {outbound.departure} -> {outbound.arrival}"
    )

    returning = scraper.return_flights(query, outbound).cheapest
    if returning is None:
        raise SystemExit("no return flight pairs with that outbound")
    numbers = "+".join(returning.flight_numbers)
    print(f"Return   {numbers}  {returning.departure} -> {returning.arrival}")
    print(f"Round trip from {returning.price} {returning.currency}\n")

    booking = scraper.booking_options(query, outbound, returning)
    for option in booking.options:
        kind = "airline" if option.airline_direct else "agency"
        extra = "  (separate tickets)" if option.separate_tickets else ""
        print(f"{option.seller:<28} {kind:<8} {option.price} {option.currency}{extra}")
        for fare in option.fares:
            print(f"    {fare.name or '-':<20} {fare.price}  {'; '.join(fare.features)}")


if __name__ == "__main__":
    main()
