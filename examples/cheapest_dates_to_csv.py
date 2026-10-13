"""Find the cheapest day to fly: search two weeks of departure dates, save a CSV.

python examples/cheapest_dates_to_csv.py LAX JFK --days 14 --out lax-jfk-dates.csv
python examples/cheapest_dates_to_csv.py LHR BCN --stay 4 --currency EUR
"""

from __future__ import annotations

import argparse
import datetime as dt

from google_flights_scraper import FlightQuery, GoogleFlightsScraper
from google_flights_scraper.export import DATE_COLUMNS, date_row, write_csv


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("origin", nargs="?", default="LAX")
    parser.add_argument("destination", nargs="?", default="JFK")
    parser.add_argument("--start-in", type=int, default=21, help="first date, days from today")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--stay", type=int, help="round trip of this many days")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--out", default="cheapest-dates.csv")
    args = parser.parse_args()

    first = dt.date.today() + dt.timedelta(days=args.start_in)
    dates = [first + dt.timedelta(days=offset) for offset in range(args.days)]
    query = FlightQuery(args.origin, args.destination, first, currency=args.currency)

    scraper = GoogleFlightsScraper()
    rows = scraper.date_sweep(
        query,
        dates,
        stay_days=args.stay,
        workers=3,
        on_date=lambda row: print(f"{row.depart_date}  {row.lowest_price or row.error}"),
    )
    write_csv([date_row(row) for row in rows], args.out, DATE_COLUMNS)

    priced = [row for row in rows if row.lowest_price is not None]
    if priced:
        best = min(priced, key=lambda row: row.lowest_price)
        print(f"\nCheapest: {best.depart_date} at {best.lowest_price} {best.currency}")
    print(f"Saved {len(rows)} dates to {args.out}")


if __name__ == "__main__":
    main()
