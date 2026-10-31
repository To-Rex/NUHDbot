.PHONY: install migrate migration seed demo products dev run lint test webhook

install:
	uv sync

migrate:
	uv run alembic upgrade head

migration:
	uv run alembic revision --autogenerate -m "$(m)"

seed:
	uv run python -m scripts.seed

demo:
	uv run python -m scripts.seed --demo

products:
	uv run python -m scripts.seed_products

dev:
	uv run uvicorn app.main:app --reload --port 8000

run:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'

lint:
	uv run ruff check app scripts tests --fix

test:
	uv run pytest -q

webhook:
	uv run python -m scripts.set_webhook set
