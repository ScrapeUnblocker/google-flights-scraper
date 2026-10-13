"""Write results as JSON, JSON Lines, CSV or a quick terminal table."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from .models import BookingOption, DatePrice, Flight

LIST_SEPARATOR = " | "

FLIGHT_COLUMNS = (
    "price",
    "currency",
    "best",
    "airlines",
    "flight_numbers",
    "departure_airport",
    "arrival_airport",
    "departure",
    "arrival",
    "duration_minutes",
    "duration",
    "stops",
    "layovers",
    "aircraft",
    "operated_by",
    "legroom",
    "emissions_kg",
    "typical_emissions_kg",
    "emissions_diff_percent",
    "overnight",
    "departure_airport_name",
    "arrival_airport_name",
)

BOOKING_COLUMNS = (
    "seller",
    "airline_direct",
    "separate_tickets",
    "price",
    "currency",
    "fare",
    "fare_price",
    "features",
    "labels",
    "note",
)

DATE_COLUMNS = (
    "depart_date",
    "return_date",
    "lowest_price",
    "currency",
    "price_level",
    "flights_found",
    "airlines",
    "flight_numbers",
    "departure",
    "arrival",
    "stops",
    "duration",
    "error",
)


def to_dict(record: Any) -> dict[str, Any]:
    """A record (dataclass with ``to_dict`` or a dict) as a plain dict."""
    if hasattr(record, "to_dict"):
        return record.to_dict()
    if isinstance(record, dict):
        return dict(record)
    raise TypeError(f"cannot export {type(record).__name__}")


def to_json(data: Any, *, pretty: bool = False) -> str:
    """Serialize a record, or a list of records, as JSON."""
    if isinstance(data, (list, tuple)):
        payload: Any = [to_dict(item) for item in data]
    else:
        payload = to_dict(data)
    return json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)


def to_jsonl(records: Iterable[Any]) -> str:
    """Serialize records as JSON Lines (one object per line)."""
    return "".join(json.dumps(to_dict(r), ensure_ascii=False) + "\n" for r in records)


def format_duration(minutes: int | None) -> str:
    """``605`` -> ``10h 05m``."""
    if minutes is None:
        return ""
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _join(values: Iterable[Any]) -> str:
    return LIST_SEPARATOR.join(str(value) for value in values if value not in (None, ""))


def _kg(grams: int | None) -> int | None:
    return round(grams / 1000) if grams is not None else None


def flight_row(flight: Flight) -> dict[str, Any]:
    """One flight as a flat CSV row."""
    layovers = [
        f"{stop.airport} {format_duration(stop.duration_minutes)}".strip()
        + (f" (to {stop.departure_airport})" if stop.change_of_airport else "")
        for stop in flight.layovers
    ]
    return {
        "price": flight.price,
        "currency": flight.currency,
        "best": flight.best,
        "airlines": _join(flight.airlines),
        "flight_numbers": _join(flight.flight_numbers),
        "departure_airport": flight.departure_airport,
        "arrival_airport": flight.arrival_airport,
        "departure": flight.departure,
        "arrival": flight.arrival,
        "duration_minutes": flight.duration_minutes,
        "duration": format_duration(flight.duration_minutes),
        "stops": flight.stops,
        "layovers": _join(layovers),
        "aircraft": _join(segment.aircraft for segment in flight.segments),
        "operated_by": _join(segment.operated_by for segment in flight.segments),
        "legroom": _join(segment.legroom for segment in flight.segments),
        "emissions_kg": _kg(flight.emissions_grams),
        "typical_emissions_kg": _kg(flight.typical_emissions_grams),
        "emissions_diff_percent": flight.emissions_diff_percent,
        "overnight": flight.overnight,
        "departure_airport_name": flight.departure_airport_name,
        "arrival_airport_name": flight.arrival_airport_name,
    }


def booking_rows(options: Iterable[BookingOption]) -> list[dict[str, Any]]:
    """One CSV row per fare (or per seller when Google lists no fare detail)."""
    rows = []
    for option in options:
        base = {
            "seller": option.seller,
            "airline_direct": option.airline_direct,
            "separate_tickets": option.separate_tickets,
            "price": option.price,
            "currency": option.currency,
            "labels": _join(option.labels),
            "note": option.note,
        }
        if not option.fares:
            rows.append({**base, "fare": None, "fare_price": option.price, "features": ""})
        for fare in option.fares:
            rows.append(
                {
                    **base,
                    "fare": fare.name,
                    "fare_price": fare.price,
                    "features": _join(fare.features),
                }
            )
    return rows


def date_row(row: DatePrice) -> dict[str, Any]:
    """One date-sweep entry as a flat CSV row."""
    cheapest = row.cheapest
    return {
        "depart_date": row.depart_date,
        "return_date": row.return_date,
        "lowest_price": row.lowest_price,
        "currency": row.currency,
        "price_level": row.price_level,
        "flights_found": row.flights_found,
        "airlines": _join(cheapest.airlines) if cheapest else "",
        "flight_numbers": _join(cheapest.flight_numbers) if cheapest else "",
        "departure": cheapest.departure if cheapest else None,
        "arrival": cheapest.arrival if cheapest else None,
        "stops": cheapest.stops if cheapest else None,
        "duration": format_duration(cheapest.duration_minutes) if cheapest else "",
        "error": row.error,
    }


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def csv_string(rows: Iterable[dict[str, Any]], columns: Sequence[str]) -> str:
    """Flat rows as CSV text (header + one line per row)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _cell(row.get(key)) for key in columns})
    return buffer.getvalue()


def write_csv(rows: Iterable[dict[str, Any]], path: str | Path, columns: Sequence[str]) -> int:
    """Write flat rows to a UTF-8 CSV file (with a BOM, so Excel reads it).

    Returns the row count.
    """
    rows = list(rows)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        handle.write(csv_string(rows, columns))
    return len(rows)


def write_json(data: Any, path: str | Path, *, pretty: bool = True) -> None:
    """Write a record, or a list of records, to a UTF-8 JSON file."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(to_json(data, pretty=pretty) + "\n")


def table(rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> str:
    """Rows as a plain-text table for the terminal."""
    cells = [[str(_cell(row.get(column))) for column in columns] for row in rows]
    widths = [
        max([len(column)] + [len(line[index]) for line in cells])
        for index, column in enumerate(columns)
    ]
    lines = ["  ".join(column.upper().ljust(width) for column, width in zip(columns, widths))]
    lines += ["  ".join(cell.ljust(width) for cell, width in zip(line, widths)) for line in cells]
    return "\n".join(line.rstrip() for line in lines) + "\n"


__all__ = [
    "BOOKING_COLUMNS",
    "DATE_COLUMNS",
    "FLIGHT_COLUMNS",
    "booking_rows",
    "csv_string",
    "date_row",
    "flight_row",
    "format_duration",
    "table",
    "to_dict",
    "to_json",
    "to_jsonl",
    "write_csv",
    "write_json",
]
