.PHONY: install lint format test migrate run up down

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

test:
	pytest --cov=app --cov-report=term-missing

migrate:
	alembic upgrade head

run:
	uvicorn app.main:app --reload

up:
	docker compose up --build

down:
	docker compose down -v
