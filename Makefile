.PHONY: setup test run dev

setup:
	uv sync --all-groups
	npm --prefix frontend install
	npm --prefix frontend run build
	uv run playwright install chromium

test:
	uv run pytest

run:
	./scripts/run.sh

dev:
	./scripts/dev.sh
