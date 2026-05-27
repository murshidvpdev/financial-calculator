# =============================================================================
# FINANCE CALCULATOR — Makefile
# =============================================================================
# Usage:
#   make dev        Start development server
#   make test       Run all tests
#   make lint       Run linters
#   make format     Format code
#   make migrate    Run database migrations
#   make seed       Seed database with test data
#   make docker-up  Start all Docker services
#   make help       Show this help
# =============================================================================

# --- Configuration ---
# .PHONY tells make these are commands, not files
# (Without this, if a file named "test" exists, `make test` does nothing)
.PHONY: help dev dev-reload test test-unit test-integration lint format typecheck \
        migrate migrate-create migrate-rollback seed \
        docker-up docker-down docker-logs docker-build \
        clean install install-dev setup

# Python and paths
PYTHON := backend/.venv/bin/python
PIP := backend/.venv/bin/pip
PYTEST := backend/.venv/bin/pytest
RUFF := backend/.venv/bin/ruff
BLACK := backend/.venv/bin/black
MYPY := backend/.venv/bin/mypy
UVICORN := backend/.venv/bin/uvicorn
ALEMBIC := backend/.venv/bin/alembic
PRE_COMMIT := backend/.venv/bin/pre-commit

# Colors for terminal output (makes it readable)
GREEN  := \033[0;32m
YELLOW := \033[0;33m
BLUE   := \033[0;34m
RED    := \033[0;31m
RESET  := \033[0m

# Default target: show help
.DEFAULT_GOAL := help

# =============================================================================
# HELP — Auto-generated from ## comments
# =============================================================================
help: ## Show this help message
	@echo "$(BLUE)╔══════════════════════════════════════════════╗$(RESET)"
	@echo "$(BLUE)║     Finance Calculator — Make Commands       ║$(RESET)"
	@echo "$(BLUE)╚══════════════════════════════════════════════╝$(RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "$(GREEN)%-20s$(RESET) %s\n", $$1, $$2}'

# =============================================================================
# SETUP — First-time project setup
# =============================================================================
setup: ## First-time setup: create venv, install deps, setup pre-commit
	@echo "$(YELLOW)🔧 Setting up project...$(RESET)"
	/opt/homebrew/opt/python@3.13/bin/python3.13 -m venv backend/.venv
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements.txt
	$(PRE_COMMIT) install
	cp -n .env.example .env || true
	@echo "$(GREEN)✅ Setup complete! Edit .env with your local values, then run: make docker-up$(RESET)"

install: ## Install production dependencies only
	$(PIP) install -r backend/requirements.txt

install-dev: ## Install all dependencies including dev tools
	$(PIP) install -r backend/requirements.txt
	$(PIP) install black ruff mypy pytest pytest-asyncio pytest-cov factory-boy faker pre-commit

# =============================================================================
# DEVELOPMENT SERVER
# =============================================================================
dev: ## Start development server with auto-reload
	@echo "$(GREEN)🚀 Starting Finance Calculator on http://localhost:8000$(RESET)"
	@echo "$(BLUE)📖 API Docs: http://localhost:8000/docs$(RESET)"
	@echo "$(BLUE)📖 ReDoc:    http://localhost:8000/redoc$(RESET)"
	cd backend && ../.venv/bin/uvicorn app.main:app \
		--host 0.0.0.0 \
		--port 8000 \
		--reload \
		--reload-dir app \
		--log-level debug

# Alternative: run with Python directly (useful for debugging)
run: ## Run app with Python directly (no auto-reload)
	cd backend && $(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# =============================================================================
# CODE QUALITY — Format, Lint, Type Check
# =============================================================================
format: ## Format code with Black + Ruff
	@echo "$(YELLOW)🎨 Formatting code...$(RESET)"
	$(BLACK) backend/app backend/tests
	$(RUFF) check --fix backend/app backend/tests
	@echo "$(GREEN)✅ Code formatted$(RESET)"

lint: ## Run linter (Ruff) — checks for errors WITHOUT fixing
	@echo "$(YELLOW)🔍 Linting code...$(RESET)"
	$(RUFF) check backend/app backend/tests
	@echo "$(GREEN)✅ Lint passed$(RESET)"

typecheck: ## Run MyPy static type checker
	@echo "$(YELLOW)🔬 Type checking...$(RESET)"
	$(MYPY) backend/app --ignore-missing-imports
	@echo "$(GREEN)✅ Type check passed$(RESET)"

check: format lint typecheck ## Run ALL quality checks (format + lint + types)

# =============================================================================
# TESTING
# =============================================================================
test: ## Run ALL tests with coverage report
	@echo "$(YELLOW)🧪 Running tests...$(RESET)"
	cd backend && $(PYTEST) tests/ -v \
		--cov=app \
		--cov-report=term-missing \
		--cov-report=html:coverage_html \
		--cov-fail-under=80
	@echo "$(GREEN)✅ Tests passed$(RESET)"

test-unit: ## Run ONLY unit tests (fast)
	cd backend && $(PYTEST) tests/unit/ -v

test-integration: ## Run ONLY integration tests (requires DB)
	cd backend && $(PYTEST) tests/integration/ -v

test-watch: ## Run tests in watch mode (re-run on file change)
	cd backend && $(PYTEST) tests/ -v --watch

# =============================================================================
# DATABASE — Migrations and Seeding
# =============================================================================
migrate: ## Apply all pending database migrations
	@echo "$(YELLOW)🗄️  Running migrations...$(RESET)"
	cd backend && $(ALEMBIC) upgrade head
	@echo "$(GREEN)✅ Migrations applied$(RESET)"

migrate-create: ## Create a new migration (usage: make migrate-create NAME="add_users_table")
	@echo "$(YELLOW)📝 Creating migration: $(NAME)$(RESET)"
	cd backend && $(ALEMBIC) revision --autogenerate -m "$(NAME)"

migrate-rollback: ## Rollback the last migration
	cd backend && $(ALEMBIC) downgrade -1

migrate-history: ## Show migration history
	cd backend && $(ALEMBIC) history --verbose

migrate-status: ## Show current migration status
	cd backend && $(ALEMBIC) current

seed: ## Seed database with test data
	@echo "$(YELLOW)🌱 Seeding database...$(RESET)"
	$(PYTHON) scripts/seed_db.py
	@echo "$(GREEN)✅ Database seeded$(RESET)"

# =============================================================================
# DOCKER — Local Infrastructure
# =============================================================================
docker-up: ## Start all Docker services (PostgreSQL + Redis)
	@echo "$(YELLOW)🐳 Starting Docker services...$(RESET)"
	docker compose -f infra/docker-compose.yml up -d
	@echo "$(GREEN)✅ Services running:$(RESET)"
	@echo "   PostgreSQL: localhost:5432"
	@echo "   Redis:      localhost:6379"
	@echo "   PgAdmin:    http://localhost:5050"

docker-down: ## Stop all Docker services
	docker compose -f infra/docker-compose.yml down

docker-down-volumes: ## Stop Docker services AND delete all data
	@echo "$(RED)⚠️  This will DELETE all database data!$(RESET)"
	docker compose -f infra/docker-compose.yml down -v

docker-logs: ## Show logs from all Docker services
	docker compose -f infra/docker-compose.yml logs -f

docker-ps: ## Show running Docker services
	docker compose -f infra/docker-compose.yml ps

docker-build: ## Build the application Docker image
	@echo "$(YELLOW)🏗️  Building Docker image...$(RESET)"
	docker build -t finance-calculator:latest backend/
	@echo "$(GREEN)✅ Image built: finance-calculator:latest$(RESET)"

docker-shell: ## Open a shell in the running app container
	docker compose -f infra/docker-compose.yml exec app bash

# =============================================================================
# UTILITIES
# =============================================================================
clean: ## Remove all generated files (pycache, coverage, etc.)
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf backend/coverage_html backend/.coverage backend/.pytest_cache
	@echo "$(GREEN)✅ Cleaned$(RESET)"

logs: ## Tail the application log file
	tail -f logs/app.log 2>/dev/null || echo "No log file found. Run the app first."

health: ## Check application health endpoint
	@curl -s http://localhost:8000/health | python3 -m json.tool || \
		echo "$(RED)❌ App is not running$(RESET)"

pre-commit-run: ## Run pre-commit on all files manually
	$(PRE_COMMIT) run --all-files

# =============================================================================
# GENERATE SECRET KEYS (useful for .env setup)
# =============================================================================
generate-secret: ## Generate a secure secret key
	$(PYTHON) -c "import secrets; print(secrets.token_hex(32))"
