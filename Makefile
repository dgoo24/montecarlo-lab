.PHONY: install lint format test test-ui migrate run frontend up down

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

test-ui:
	pytest frontend/tests -q

migrate:
	alembic upgrade head

run:
	uvicorn app.main:app --reload

frontend:
	streamlit run frontend/app.py

up:
	docker compose up --build

down:
	docker compose down -v
