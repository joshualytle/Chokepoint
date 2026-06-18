# Chokepoint — common tasks. Run `make help` for the list.

.PHONY: help install run test lint type check clean

help:
	@echo "install  - editable install with dev tools (pytest, ruff, mypy)"
	@echo "run      - launch the game"
	@echo "test     - run the headless simulation tests"
	@echo "lint     - ruff lint"
	@echo "type     - mypy type check"
	@echo "check    - lint + type + test"

install:
	pip install -e ".[dev]"

run:
	python -m chokepoint

test:
	pytest -q

lint:
	ruff check src tests

type:
	mypy src

check: lint type test

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
