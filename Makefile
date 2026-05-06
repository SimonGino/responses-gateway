.PHONY: install test test-unit test-integration test-e2e lint format typecheck migrate dev clean

install:
	uv pip install -e ".[dev,postgres,s3]"

test:
	pytest tests/ -v --cov=gateway --cov-report=term-missing

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-e2e:
	pytest tests/e2e/ -v -m "not smoke"

lint:
	ruff check gateway/ tests/

format:
	ruff format gateway/ tests/
	ruff check --fix gateway/ tests/

typecheck:
	mypy gateway/

migrate:
	alembic upgrade head

dev:
	uvicorn gateway.api:app --reload --host 0.0.0.0 --port 8080

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
