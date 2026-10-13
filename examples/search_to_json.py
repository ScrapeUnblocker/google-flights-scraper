"""Search one-way nonstop flights and print the five cheapest as JSON.

    python examples/search_to_json.py JFK LHR
    python examples/search_to_json.py SFO NRT --cabin business

Needs SCRAPEUNBLOCKER_KEY in the environment (or a .env you load yourself).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json

from google_flights_scraper import GoogleFlightsScraper


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("origin", nargs="?", default="JFK")
    parser.add_argument("destination", nargs="?", default="LHR")
    parser.add_argument("--days-ahead", type=int, default=30)
    parser.add_argument("--cabin", default="economy")
    args = parser.parse_args()

    depart = dt.date.today() + dt.timedelta(days=args.days_ahead)
    scraper = GoogleFlightsScraper()
    result = scraper.search(args.origin, args.destination, depart, max_stops=0, cabin=args.cabin)

    cheapest = sorted(
        (flight for flight in result.flights if flight.price is not None),
        key=lambda flight: flight.price,
    )[:5]
    insights = result.price_insights
    print(
        json.dumps(
            {
                "route": f"{args.origin} -> {args.destination}",
                "date": depart.isoformat(),
                "price_level": insights.level if insights else None,
                "typical_range": [insights.typical_low, insights.typical_high]
                if insights
                else None,
                "flights": [
                    {
                        "price": flight.price,
                        "currency": flight.currency,
                        "airlines": flight.airlines,
                        "flight_numbers": flight.flight_numbers,
                        "departure": flight.departure,
                        "arrival": flight.arrival,
                        "duration_minutes": flight.duration_minutes,
                        "aircraft": [segment.aircraft for segment in flight.segments],
                        "emissions_kg": round(flight.emissions_grams / 1000)
                        if flight.emissions_grams
                        else None,
                    }
                    for flight in cheapest
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
