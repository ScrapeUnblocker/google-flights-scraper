# Google Flights Scraper

[![CI](https://github.com/ScrapeUnblocker/google-flights-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/ScrapeUnblocker/google-flights-scraper/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Powered by ScrapeUnblocker](https://img.shields.io/badge/powered%20by-ScrapeUnblocker-6f42c1.svg)](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)

**Scrape [Google Flights](https://www.google.com/travel/flights) into clean JSON or CSV:
flight prices and itineraries for one-way and round trips, Google's price insights (is today's
price low, typical or high?), the return flights that pair with an outbound flight, booking
options with fares and fare rules, and the cheapest day to fly across a range of dates.**
Google shut down its public QPX Express flight-search API in 2018; this package reads the
Google Flights pages instead, so you get the same results travellers see, as typed Python
records or from the command line. Built for fare tracking and price alerts, travel deal
sites, route and airline market research, corporate travel analytics and flight-emissions
reporting.

Powered by [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos):
the `getPageSource` API fetches each Google Flights page and returns its HTML, and loads the
booking-options page in a real browser (with a `wait_for_text` browser step) because Google
fills it in after the first paint. This package builds the search URL, parses the result
into typed records and retries transient failures. You don't need proxies, a headless browser
or retry logic of your own.

## Features

- **Flight search.** Any origin and destination: IATA airport codes (`JFK`) or city codes that
  cover every airport in a metro area (`NYC`, `LON`, `PAR`). One-way or round trip, adults,
  children and infants (in seat / on lap), economy / premium economy / business / first,
  nonstop or at most 1-2 stops, specific airlines or a whole alliance (`ONEWORLD`, `SKYTEAM`,
  `STAR_ALLIANCE`), prices in any currency.
- **Every flight option Google lists**, "best" flights flagged: total price, airlines, flight
  numbers, departure / arrival airports and local times, duration, stops, layovers (airport,
  city, connection time, change of airport), overnight flag, and per segment the aircraft,
  legroom, operating carrier ("Republic Airways as American Eagle"), codeshare flight numbers
  and CO2 emissions, plus the itinerary's emissions against the typical flight on the route.
- **Price insights.** The lowest price today, the typical price and typical range for the
  route, a derived `low` / `typical` / `high` level and the daily price history Google
  charts (about two months).
- **Return flights for a chosen outbound.** Pin the outbound flight (`AA142`, or
  `EI104+EI152` for a connection) and list the return flights that pair with it, priced as
  round-trip totals, exactly like clicking a flight on the site.
- **Booking options.** For a chosen itinerary: every seller Google shows (airlines and online
  travel agencies) with its price, separate-ticket warnings and, where Google lists them, the
  fares (Basic Economy, Main Cabin, ...) with their rules: seat selection, changes, refunds,
  carry-on and checked-bag allowances and fees.
- **Cheapest day to fly.** Sweep a range of departure dates (one search per date, run in
  parallel) for one-way trips or round trips of a fixed length, and get the cheapest flight
  and price level for each day.
- **No results? Nearby airports.** When nothing matches, Google's suggested nearby airports
  come back with their prices and distance.
- **Resilient.** Timeouts, transient API errors and pages that come back without their data
  are retried with doubling backoff. Unknown airports, dates in the past and itineraries that
  are no longer sold raise a clear `GoogleFlightsQueryError`.
- **JSON, JSON Lines, CSV or a terminal table.** CSV files are UTF-8 with a BOM, so Excel
  opens them correctly; multi-value cells (airlines, flight numbers, layovers) are readable.
- **CLI + Python library.** Fully typed, and tested offline with a mocked client.

## Install

```bash
git clone https://github.com/ScrapeUnblocker/google-flights-scraper.git
cd google-flights-scraper
pip install .
```

Get an API key at [scrapeunblocker.com](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
and expose it as `SCRAPEUNBLOCKER_KEY` (the official SDK reads it from there):

```bash
export SCRAPEUNBLOCKER_KEY=your_key_here        # Windows PowerShell: $env:SCRAPEUNBLOCKER_KEY="your_key_here"
```

You can also copy `.env.example` to `.env` and load it with your tool of choice.

## CLI usage

Dates are `YYYY-MM-DD` and must be in the future.

```bash
# One-way, at most one stop, cheapest first, as a table
google-flights-scraper search JFK LHR 2026-11-12 --max-stops 1 --sort price --limit 8 -f table

# Round trip for 2 adults + 1 child in premium economy, oneworld airlines only, to CSV
google-flights-scraper search NYC LON 2026-12-18 2027-01-03 --adults 2 --children 1 \
    --cabin premium-economy --airlines ONEWORLD -o holidays.csv

# Business class, nonstop, prices in euros, full JSON (flights + price insights)
google-flights-scraper search FRA SFO 2026-11-20 --cabin business --max-stops 0 --currency EUR --pretty

# Return flights that pair with the outbound VS26 (round-trip prices)
google-flights-scraper returns JFK LHR 2026-11-12 2026-11-19 --outbound VS26 -f table

# Where to book VS26 out and VS9 back: sellers, fares and fare rules
google-flights-scraper booking JFK LHR 2026-11-12 2026-11-19 --outbound VS26 --inbound VS9 -o booking.csv

# One-way booking options for a connection (both segments)
google-flights-scraper booking JFK LHR 2026-11-12 --outbound EI108+EI156

# Cheapest day to fly: every departure date in a range, 4-night round trips
google-flights-scraper dates LAX JFK 2026-11-17 2026-11-30 --stay 4 -o dates.csv
```

`booking` on a round trip without `--inbound` uses the cheapest return flight and says so on
stderr.

Common options: `-o/--output FILE` (format from the extension: `.json`, `.jsonl`, `.csv`,
`.txt` for a table), `-f/--format json|jsonl|csv|table` (stdout otherwise), `--pretty`,
`--sort best|price|duration|departure|arrival|stops|emissions`, `--limit N`, `--best-only`,
`--country CODE` (request route, default `us`), `--retries N`, `-q/--quiet`. Progress goes to
stderr. Run `google-flights-scraper <command> -h` for everything.

## Library usage

```python
from google_flights_scraper import FlightQuery, GoogleFlightsScraper, find_flight

# Reads SCRAPEUNBLOCKER_KEY; GoogleFlightsScraper(api_key="...") also works
scraper = GoogleFlightsScraper()

query = FlightQuery(
    "JFK",
    "LHR",
    "2026-11-12",
    "2026-11-19",  # omit the return date for one-way
    adults=2,
    cabin="premium-economy",
    max_stops=0,
    airlines=["VS", "DL"],  # airline codes or ONEWORLD / SKYTEAM / STAR_ALLIANCE
    currency="USD",
)
result = scraper.search_query(query)

insights = result.price_insights
if insights:
    print(insights.level, insights.lowest_price, insights.typical_low, insights.typical_high)

for flight in result.flights[:5]:
    print(flight.price, flight.airlines, flight.flight_numbers, flight.departure, flight.stops)

# Pick an outbound flight, list the matching returns, then see where to book
outbound = find_flight(result.flights, "VS26")
returns = scraper.return_flights(query, outbound)
booking = scraper.booking_options(query, outbound, returns.cheapest)
for option in booking.options:
    print(option.seller, option.price, option.airline_direct, [f.name for f in option.fares])

# Cheapest departure date over two weeks, keeping the 7-night stay
from google_flights_scraper import date_range

for day in scraper.date_sweep(query, date_range("2026-11-10", "2026-11-23"), workers=3):
    print(day.depart_date, day.lowest_price, day.price_level)

# Quick one-liner search
cheap = scraper.search("SFO", "NRT", "2026-12-01", cabin="business").cheapest
```

Every record has `to_dict()`. `google_flights_scraper.export` turns results into CSV rows
(`flight_row`, `booking_rows`, `date_row`) and writes JSON / CSV files. `search_url(query)` and
`encode_tfs(query)` give you the Google Flights link for any query.

Errors: `GoogleFlightsQueryError` (unknown airport, a date in the past, an itinerary no longer
sold), `FlightNotFoundError` (no flight matches the flight numbers you gave),
`GoogleFlightsParseError` (a page came back without its data after all retries) and
`GoogleFlightsConsentError` (Google's cookie-consent page; see below) derive from
`GoogleFlightsError`. API errors from the official SDK (for example an invalid key) are passed
through.

## Example output

`google-flights-scraper search JFK LHR 2026-11-12 --max-stops 1 --sort price --limit 8 -f table`:

```
searching JFK -> LHR on 2026-11-12
24 flights; lowest 319 USD is high (typical 170-300)
PRICE  AIRLINES          FLIGHT_NUMBERS  DEPARTURE         ARRIVAL           DURATION  STOPS  LAYOVERS    EMISSIONS_KG
319    ITA               AZ609 | AZ202   2026-11-12T16:40  2026-11-13T09:40  12h 00m   1      FCO 0h 45m  587
319    ITA               AZ611 | AZ204   2026-11-12T21:05  2026-11-13T15:40  13h 35m   1      FCO 2h 20m  587
321    Tap Air Portugal  TP210 | TP1356  2026-11-12T22:00  2026-11-13T17:30  14h 30m   1      LIS 4h 40m  588
353    Finnair           AY16 | AY1337   2026-11-12T22:45  2026-11-13T17:00  13h 15m   1      HEL 2h 05m  608
368    Virgin Atlantic   VS26            2026-11-12T08:00  2026-11-12T20:10  7h 10m    0                  365
368    JetBlue           B61107          2026-11-12T09:30  2026-11-12T21:40  7h 10m    0                  586
368    American          AA100           2026-11-12T18:25  2026-11-13T06:20  6h 55m    0                  398
368    Delta             DL1             2026-11-12T20:00  2026-11-13T08:05  7h 05m    0                  310
```

One flight in the JSON output (a round trip JFK - LHR, trimmed to one segment):

```json
{
  "price": 820,
  "currency": "USD",
  "best": false,
  "airlines": ["Aer Lingus"],
  "airline_code": "EI",
  "departure_airport": "JFK",
  "departure_airport_name": "John F. Kennedy International Airport",
  "arrival_airport": "LHR",
  "arrival_airport_name": "Heathrow Airport",
  "departure": "2026-11-20T19:25",
  "arrival": "2026-11-21T10:10",
  "duration_minutes": 585,
  "stops": 1,
  "layovers": [
    {"airport": "DUB", "airport_name": "Dublin Airport", "city": "Dublin",
     "duration_minutes": 105, "departure_airport": "DUB", "change_of_airport": false}
  ],
  "segments": [
    {
      "flight_number": "EI108",
      "airline": "Aer Lingus",
      "airline_code": "EI",
      "operated_by": null,
      "departure_airport": "JFK",
      "arrival_airport": "DUB",
      "departure": "2026-11-20T19:25",
      "arrival": "2026-11-21T07:00",
      "duration_minutes": 395,
      "aircraft": "Airbus A321neo",
      "legroom": "31 in",
      "legroom_inches": 31,
      "emissions_grams": 378765,
      "also_sold_as": []
    }
  ],
  "emissions_grams": 431000,
  "typical_emissions_grams": 432000,
  "emissions_diff_percent": 0,
  "flight_numbers": ["EI108", "EI156"],
  "overnight": true
}
```

Price insights for the same search:

```json
{
  "lowest_price": 820,
  "typical_price": 543,
  "typical_low": 485,
  "typical_high": 720,
  "currency": "USD",
  "history": [{"date": "2026-08-13", "price": 737}, {"date": "2026-08-14", "price": 737}, "..."],
  "level": "high"
}
```

Booking options (`python examples/round_trip_booking.py JFK LHR --days-ahead 30 --stay 7`):

```
Outbound VS26  2026-11-12T08:00 -> 2026-11-12T20:10
Return   VS9  2026-11-19T15:50 -> 2026-11-19T19:10
Round trip from 817 USD

Virgin Atlantic              airline  817 USD
    Economy Light        817  Seat selection for a fee; Standard seat; Ticket changes for a fee; No refunds; 1 free carry-on; First checked bag costs 200 US dollars
    Economy Classic      1017  Free seat selection; Standard seat; Free change, possible fare difference; No refunds; 1 free carry-on; First checked bag is free
    Economy Classic Flex 1217  Free seat selection; Standard seat; Free change, possible fare difference; Full refunds; 1 free carry-on; First checked bag is free
    Economy Delight      1117  Free seat selection; Extra legroom; Free change, possible fare difference; No refunds; Priority boarding; 1 free carry-on; First checked bag is free
    Economy Delight Flex 1477  Free seat selection; Extra legroom; Free change, possible fare difference; Full refunds; Priority boarding; 1 free carry-on; First checked bag is free
Delta                        airline  817 USD
Air France                   airline  817 USD
KLM                          airline  817 USD
Adam Vacations               agency   780 USD
EaseMyTrip                   agency   873 USD
```

Cheapest day to fly (`google-flights-scraper dates LAX JFK 2026-11-17 2026-11-19 --stay 4 -o dates.csv`):

```
depart_date,return_date,lowest_price,currency,price_level,flights_found,airlines,flight_numbers,departure,arrival,stops,duration,error
2026-11-17,2026-11-21,408,USD,typical,29,JetBlue,B6524,2026-11-17T07:05,2026-11-17T15:29,0,5h 24m,
2026-11-18,2026-11-22,408,USD,typical,29,JetBlue,B61024,2026-11-18T16:30,2026-11-19T00:52,0,5h 22m,
2026-11-19,2026-11-23,409,USD,typical,33,American,AA28,2026-11-19T14:51,2026-11-19T23:18,0,5h 27m,
```

## Good to know

- **Prices are totals.** A price covers every passenger in the search; on a round trip it is
  the round-trip total (that is how Google prices departing flights too). Prices come in the
  `currency` you ask for.
- **Times are local** to each airport (`2026-11-21T10:10` at the arrival airport). `overnight`
  is true when a flight lands on a later calendar day than it took off.
- **How the URL is built.** Google Flights keeps the whole search in one `tfs` URL parameter,
  a small protobuf message. `encode_tfs` writes it in plain Python (no protobuf dependency),
  including pinned flights for return-flight and booking pages, so any query is one request.
- **Requests go through the US by default.** Many European routes get Google's cookie-consent
  page instead of results; `--country` / `country=` changes the route if you need to.
- **Booking options load in the browser** after the page appears, so `booking` takes a few
  seconds longer than a search. Google shows fare details (names, rules, prices) for the
  seller it expands; other sellers come with their price and labels only.
- **Price level** (`low` / `typical` / `high`) compares today's lowest price with Google's
  typical range for the route; `history` is the daily lowest price Google charts.
- **Multi-city trips are not supported**: Google Flights only loads those results in an
  interactive session.
- **City codes** search every airport in the area (`NYC` = JFK, EWR and LGA), so results can
  depart from different airports; check `departure_airport` on each flight.
- **Emissions** are Google's estimates in grams of CO2e; `emissions_diff_percent` compares the
  itinerary with the typical flight on the route (negative = lower).
- Collect public data responsibly: keep request volumes reasonable and follow Google's terms
  and the rules that apply to you.

## Project layout

```
google-flights-scraper/
├── src/google_flights_scraper/
│   ├── __init__.py      # public API and package docs
│   ├── scraper.py       # GoogleFlightsScraper: search, return flights, booking, date sweep, retries
│   ├── parsing.py       # Google Flights pages -> typed records (embedded data, booking panel)
│   ├── query.py         # FlightQuery validation and the tfs URL encoder
│   ├── models.py        # Flight, Segment, Layover, PriceInsights, BookingOption, Fare, ...
│   ├── export.py        # JSON, JSON Lines, CSV rows and terminal tables
│   ├── cli.py           # the google-flights-scraper command
│   └── __main__.py      # python -m google_flights_scraper
├── examples/
│   ├── search_to_json.py          # five cheapest nonstop flights 30 days out, as JSON
│   ├── round_trip_booking.py      # outbound -> matching return -> booking options
│   └── cheapest_dates_to_csv.py   # cheapest day to fly over two weeks, to CSV
├── tests/                         # offline tests with a mocked client (no API calls)
├── pyproject.toml
├── requirements.txt
├── Makefile
└── .github/workflows/ci.yml
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
make install    # pip install -e ".[dev]"
make lint       # ruff check .
make format     # ruff format .
make test       # pytest -q (offline, no API key needed)
make run        # JFK -> LHR nonstop, 30 days from today, as a table (needs SCRAPEUNBLOCKER_KEY)
```

`pre-commit install` enables the ruff hooks from `.pre-commit-config.yaml`.

## Links

- [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos) - web scraping API that returns HTML from protected sites
- [Documentation](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos) - `getPageSource`, browser steps, SDKs, parameters and errors
- Official SDK: `pip install scrapeunblocker`

## License

[MIT](LICENSE) - Copyright (c) 2026 ScrapeUnblocker
