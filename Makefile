.PHONY: install lock test test-unit test-integration test-e2e lint format typecheck migrate dev clean

install:
	uv pip install -e ".[dev,postgres,s3]"

lock:
	uv lock

test:
	uv run pytest tests/ -v --cov=gateway --cov-report=term-missing

test-unit:
	uv run pytest tests/unit/ -v

test-integration:
	uv run pytest tests/integration/ -v

test-e2e:
	uv run pytest tests/e2e/ -v -m "not smoke"

lint:
	uv run ruff check gateway/ tests/

format:
	uv run ruff format gateway/ tests/
	uv run ruff check --fix gateway/ tests/

typecheck:
	uv run mypy gateway/

migrate:
	uv run alembic upgrade head

dev:
	uv run uvicorn gateway.api:app --reload --host 0.0.0.0 --port 8080

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
