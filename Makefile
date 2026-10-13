.PHONY: install lint format test run clean

# A departure date 30 days from today, so `make run` never searches the past.
DEPART ?= $(shell python -c "import datetime as d; print(d.date.today() + d.timedelta(days=30))")

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check .

format:
	ruff format .

test:
	pytest -q

run:
	google-flights-scraper search JFK LHR $(DEPART) --max-stops 0 --format table

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
