.DEFAULT_GOAL := help

.PHONY: help backend-dev backend-test backend-lint backend-lint-fix docker-build compose-up compose-dev-up compose-down clean

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*##"; printf "\nAvailable commands:\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

backend-dev: ## Run the backend API locally with reload
	cd backend && uv run --extra usd uvicorn main:app --reload --app-dir src

backend-test: ## Run backend tests
	cd backend && uv run --extra dev pytest

backend-lint: ## Check backend lint rules
	cd backend && uv run --extra dev ruff check src tests

backend-lint-fix: ## Fix auto-fixable backend lint issues
	cd backend && uv run --extra dev ruff check src tests --fix

docker-build: ## Build the backend Docker image
	docker build -t film-set-backend ./backend
	docker build -t film-set-ui ./ui

compose-up: ## Start services with Docker Compose
	docker compose up --build -d

compose-dev-up: ## Start development services with live reload
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d

compose-down: ## Stop Docker Compose services
	docker compose -f docker-compose.yml -f docker-compose.dev.yml down

clean: ## Remove generated caches and build output
	find . -path ./.git -prune -o -path ./backend/.venv -prune -o -type d -name __pycache__ -prune -exec rm -r {} +
	find . -path ./.git -prune -o -path ./backend/.venv -prune -o -type d -name .pytest_cache -prune -exec rm -r {} +
	find . -path ./.git -prune -o -path ./backend/.venv -prune -o -type d -name .ruff_cache -prune -exec rm -r {} +
	rm -rf backend/dist backend/build backend/src/*.egg-info
