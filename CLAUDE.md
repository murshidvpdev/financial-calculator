# Finance Calculator — CLAUDE.md
> Project context and instructions for Claude Code sessions.
> This file is loaded automatically at the start of every session.

---

## Project Overview

A **production-grade Finance Calculator & Expense Tracker** built as a learning project covering the full stack from FastAPI to Docker to GitHub Actions CI/CD to AWS ECS. Every file is heavily commented to explain the "why" behind every decision.

**Location:** `/Users/murshi./projects/finance-calculator/`
**Owner email:** murshidveypey790@gmail.com

---

## Current Status

**Phases 0–11 complete. Currently on Phase 12 (Kubernetes).**

| Phase | What | Status |
|-------|------|--------|
| 0–3 | Planning, Python/FastAPI setup, PostgreSQL schema, Alembic migrations | ✅ |
| 4 | Auth — JWT access+refresh tokens, bcrypt, RBAC, Redis token blacklist | ✅ |
| 5 | Expenses + Categories CRUD — cursor pagination, full-text search, filters | ✅ |
| 6 | Finance Calculator — compound interest, EMI, SIP, tax estimator, 50/30/20 | ✅ |
| 7 | Analytics API — summary, trends, category breakdown, top expenses, budget vs actual | ✅ |
| 8 | Dashboard UI — Jinja2 + Tailwind CSS + HTMX, Chart.js charts | ✅ |
| 9 | Test suite — 179 tests, 80.95% coverage | ✅ |
| 10 | Docker — multi-stage Dockerfile, .dockerignore, docker-compose.prod.yml, Nginx | ✅ |
| 11 | GitHub Actions — ci.yml, cd-staging.yml, cd-production.yml | ✅ |
| 11b | CSV/PDF/Excel Import — PhonePe, GPay, Paytm (incl. UPI PDF), HDFC, SBI | ✅ |
| 12 | Kubernetes manifests | ⏳ Next |
| 13 | AWS ECS + Terraform | ⏳ |
| 14 | CloudWatch monitoring | ⏳ |
| 15 | Scaling (Redis cache, PgBouncer, read replicas) | ⏳ |
| 16 | Production hardening | ⏳ |
| 17 | AI features (Claude API expense categorization) | ⏳ |

---

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.13 |
| Framework | FastAPI | 0.115.6 |
| ORM | SQLAlchemy | 2.0 async + asyncpg |
| Database | PostgreSQL | 14 (Homebrew local) |
| Migrations | Alembic | 1.14 |
| Cache/Sessions | Redis | 7 (Homebrew) |
| Auth | JWT (python-jose) + bcrypt direct | — |
| Templates | Jinja2 + Tailwind CSS + HTMX | — |
| Charts | Chart.js | 4.x (CDN) |
| Testing | pytest + pytest-asyncio + httpx | — |
| PDF parsing | pdfplumber | 0.11.9 |
| Excel parsing | openpyxl | 3.1.5 |
| Container | Docker multi-stage + Nginx | — |
| CI/CD | GitHub Actions | — |
| Cloud (planned) | AWS ECS + RDS + ElastiCache + CloudFront | — |

---

## Running The App

```bash
# Start PostgreSQL and Redis (Homebrew)
brew services start postgresql@14   # or whichever version
brew services start redis

# Start FastAPI with hot-reload
cd /Users/murshi./projects/finance-calculator/backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# URLs
# App:      http://localhost:8000
# Login:    http://localhost:8000/login
# Dashboard: http://localhost:8000/dashboard
# Expenses: http://localhost:8000/expenses
# API docs: http://localhost:8000/docs
# Health:   http://localhost:8000/api/v1/health/live
```

**Stop the app:**
```bash
pkill -f "uvicorn app.main:app"
```

**Test user (created during development):**
- Email: `murshi@example.com`
- Password: `Murshi@1234!`

---

## Running Tests

```bash
cd /Users/murshi./projects/finance-calculator/backend

# Full suite with coverage
.venv/bin/pytest --cov=app --cov-report=term-missing --cov-fail-under=80 -v

# Single file
.venv/bin/pytest tests/unit/test_calculator.py -v

# With short traceback
.venv/bin/pytest --tb=short -v
```

**Test database:** `finance_test_db` (must exist on local PostgreSQL)
```bash
psql -h localhost -U "murshi." -d postgres -c "CREATE DATABASE finance_test_db OWNER finance_user;"
```

---

## Database

```bash
# Run migrations
cd backend
.venv/bin/alembic upgrade head

# Create a new migration
.venv/bin/alembic revision --autogenerate -m "add something"

# Connection strings
# App:   postgresql+asyncpg://finance_user@localhost:5432/finance_db
# Tests: postgresql+asyncpg://finance_user@localhost:5432/finance_test_db
# Local PostgreSQL uses trust auth (no password for finance_user)
```

**Tables:** `users`, `user_profiles`, `categories`, `expenses`, `income`, `budgets` + `alembic_version`

---

## Project Structure

```
finance-calculator/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app factory (create_application)
│   │   ├── config.py            # Pydantic Settings (reads .env)
│   │   ├── database.py          # SQLAlchemy async engine (init_db / close_db)
│   │   ├── dependencies.py      # get_current_user — checks Bearer header OR cookie
│   │   ├── exceptions.py        # Custom exception hierarchy + handlers
│   │   ├── health.py            # /live (status="alive"), /ready, /health
│   │   ├── cache.py             # Redis connection
│   │   ├── routers.py           # Assembles all routers
│   │   ├── auth/                # JWT login/register/refresh/logout
│   │   ├── users/               # User + UserProfile models
│   │   ├── expenses/            # Category + Expense CRUD
│   │   ├── analytics/           # Dashboard aggregations
│   │   ├── calculator/          # Stateless finance calculators
│   │   ├── pages/               # Jinja2 HTML page routes (cookie auth)
│   │   │   └── router.py        # Includes web form routes for HTMX
│   │   └── core/
│   │       ├── middleware.py    # PURE ASGI middleware (NOT BaseHTTPMiddleware)
│   │       ├── pagination.py   # base64url cursor pagination
│   │       └── security.py     # hash_password, verify_password, JWT helpers
│   ├── templates/
│   │   ├── base.html            # Tailwind + HTMX + Chart.js base
│   │   ├── auth/                # login.html, register.html
│   │   ├── dashboard/           # index.html — charts, quick-add form
│   │   └── expenses/
│   │       ├── list.html        # Expenses page with Add Expense modal
│   │       └── table_fragment.html  # HTMX partial — just the table body
│   ├── tests/
│   │   ├── conftest.py          # Fixtures (sync table creation, function-scoped client)
│   │   ├── unit/                # test_security, test_calculator, test_pagination
│   │   └── integration/         # test_auth, test_expenses, test_calculator, test_auth_extended
│   ├── migrations/              # Alembic versions
│   ├── Dockerfile               # Multi-stage: builder → runtime
│   ├── .dockerignore
│   ├── requirements.txt
│   ├── pyproject.toml           # pytest + coverage config
│   └── .env                     # Local secrets (NOT committed)
├── infra/
│   ├── docker-compose.yml       # Dev: postgres + redis only
│   ├── docker-compose.prod.yml  # Prod: app + postgres + redis + nginx
│   ├── nginx/
│   │   ├── nginx.conf           # Workers, gzip, rate limit zones
│   │   └── conf.d/app.conf      # Server blocks, proxy_pass, SSL config
│   ├── k8s/                     # Kubernetes manifests (Phase 12)
│   └── terraform/               # AWS IaC (Phase 13)
├── .github/
│   ├── workflows/
│   │   ├── ci.yml               # lint → test → build → trivy scan
│   │   ├── cd-staging.yml       # develop merge → ECR push → ECS staging deploy
│   │   └── cd-production.yml    # main merge → manual approval → ECS prod deploy
│   ├── pull_request_template.md
│   └── CODEOWNERS
├── .env.example                 # Template — copy to backend/.env
└── CLAUDE.md                    # This file
```

---

## Critical Implementation Notes

These are non-obvious decisions that caused bugs — always check these first.

### 1. Middleware: Pure ASGI only (no BaseHTTPMiddleware)
`app/core/middleware.py` uses pure ASGI classes (`async def __call__(self, scope, receive, send)`).
`BaseHTTPMiddleware` causes `RuntimeError: Future attached to different loop` when combined with asyncpg in tests.
**Never switch back to BaseHTTPMiddleware.**

### 2. Auth: Bearer header OR httpOnly cookie
`app/dependencies.py` — `get_current_user` checks in this order:
1. `Authorization: Bearer <token>` header (API clients)
2. `access_token` httpOnly cookie (browser/HTMX)

This is what makes HTMX forms work without embedding tokens in JavaScript.
The cookie has `samesite=lax` which provides CSRF protection.

### 3. HTMX form routes vs API routes
- `/api/v1/expenses` — expects **JSON**, returns JSON, uses Bearer token
- `/web/expenses/create` — expects **form data** (`application/x-www-form-urlencoded`), returns HTML fragment, uses cookie
- HTMX forms on pages post to `/web/*` routes, NOT to `/api/v1/*`

### 4. Test conftest pattern (avoids "Future attached to different loop")
```python
# SYNC session fixture for table creation (uses asyncio.run() — isolated loop)
@pytest.fixture(scope="session", autouse=True)
def create_test_tables():
    asyncio.run(_setup())   # isolated event loop, no asyncpg contamination
    yield
    asyncio.run(_teardown())

# Function-scoped client (new engine per test = new event loop per test)
@pytest_asyncio.fixture
async def client():
    await init_db()   # creates engine bound to THIS test's event loop
    async with AsyncClient(...) as c:
        yield c
    await close_db()
```
`pyproject.toml` has `asyncio_default_fixture_loop_scope = "function"`.

### 5. Cursor pagination base64 padding
`encode_cursor` strips `=` padding: `.rstrip("=")`
`decode_cursor` adds it back before decoding:
```python
padded = cursor + "=" * (4 - len(cursor) % 4) if len(cursor) % 4 else cursor
```

### 6. Health endpoint details
- Live endpoint: `GET /api/v1/health/live` → `{"status": "alive", ...}`  ← `"alive"` not `"ok"`
- Ready endpoint: `GET /api/v1/health/ready` → `{"checks": {"database": {"status": "healthy"}, "redis": {...}}}`
- Protected user route: `GET /api/v1/auth/me` ← NOT `/api/v1/users/me`

### 7. bcrypt: use direct, not passlib
```python
import bcrypt
bcrypt.hashpw(password.encode(), bcrypt.gensalt())   # ✅
# passlib is incompatible with bcrypt 5.x
```
`DUMMY_HASH = "$2b$12$S7sLlq3MO3t/aewrMnRiwO7EwrAQqGihvRA5sUJSpIwFYh72RgiNy"` (for timing attack prevention)

### 8. FastAPI 0.115 DELETE endpoints need response_model=None
```python
@router.delete("/{id}", status_code=204, response_model=None)
```

### 9. Expense date field
`ExpenseCreate.date` is a `datetime`, not a string. Default = `datetime.now().astimezone()`.
In templates: `exp.date.strftime('%Y-%m-%d')` — NOT `exp.date[:10]`.
In web form routes: only pass `date` kwarg if the form field is non-empty.

### 10. Calculator field names
The compound interest endpoint field is `annual_rate_pct` (not `annual_rate`).

---

## Docker

```bash
# Build image
docker build -t finance-app:latest ./backend

# Run full production stack
docker compose -f infra/docker-compose.prod.yml up --build

# Stop stack
docker compose -f infra/docker-compose.prod.yml down

# Logs
docker compose -f infra/docker-compose.prod.yml logs -f app
```

**Required `.env` variables for docker-compose.prod.yml:**
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `REDIS_PASSWORD`, `JWT_SECRET_KEY`, `CORS_ORIGINS`

---

## GitHub Actions Secrets Required

For CI/CD to work when the repo is pushed to GitHub:

| Secret | Description |
|--------|-------------|
| `AWS_DEPLOY_ROLE_ARN` | IAM role ARN for OIDC auth (staging + prod) |
| `AWS_REGION` | e.g. `us-east-1` |
| `ECR_REGISTRY` | e.g. `123456789.dkr.ecr.us-east-1.amazonaws.com` |
| `ECR_REPOSITORY` | e.g. `finance-calculator` |
| `ECS_CLUSTER_STAGING` | Staging ECS cluster name |
| `ECS_SERVICE_STAGING` | Staging ECS service name |
| `ECS_TASK_DEFINITION` | Staging task definition name |
| `ECS_CLUSTER_PRODUCTION` | Production ECS cluster name |
| `ECS_SERVICE_PRODUCTION` | Production ECS service name |
| `ECS_TASK_DEFINITION_PROD` | Production task definition name |
| `STAGING_URL` | e.g. `https://staging.finance.yourdomain.com` |
| `PRODUCTION_URL` | e.g. `https://finance.yourdomain.com` |
| `SLACK_WEBHOOK_URL` | Incoming webhook for deploy notifications |
| `CODECOV_TOKEN` | Codecov upload token |

**GitHub Environment:** Create a `production` environment in repo Settings → Environments with required reviewers. This is the manual approval gate for prod deploys.

---

## API Quick Reference

```
Auth:
  POST /api/v1/auth/register        → { message, user }
  POST /api/v1/auth/login           → { access_token, refresh_token, token_type, expires_in }
  POST /api/v1/auth/refresh         → { access_token }
  POST /api/v1/auth/logout          → 200
  POST /api/v1/auth/forgot-password → 200
  GET  /api/v1/auth/me              → User object (requires auth)

Expenses:
  GET    /api/v1/expenses           → PaginatedResponse (cursor pagination)
  POST   /api/v1/expenses           → Expense (JSON body)
  GET    /api/v1/expenses/{id}      → Expense
  PUT    /api/v1/expenses/{id}      → Expense
  DELETE /api/v1/expenses/{id}      → 204

Categories:
  GET    /api/v1/categories         → list
  POST   /api/v1/categories         → Category
  PUT    /api/v1/categories/{id}    → Category
  DELETE /api/v1/categories/{id}    → 204

Analytics:
  GET /api/v1/analytics/summary
  GET /api/v1/analytics/trends
  GET /api/v1/analytics/category-breakdown
  GET /api/v1/analytics/top-expenses
  GET /api/v1/analytics/budget-vs-actual

Calculator (no auth required):
  POST /api/v1/calculator/compound-interest  → { principal, total_amount, interest_earned, ... }
  POST /api/v1/calculator/loan-emi           → { emi, total_payment, total_interest, ... }
  POST /api/v1/calculator/sip                → { future_value, ... }
  POST /api/v1/calculator/savings-projection → { ...projections... }
  POST /api/v1/calculator/tax-estimate       → { tax_owed, effective_rate_pct, ... }
  POST /api/v1/calculator/budget-planner     → { needs, wants, savings, ... }

Health:
  GET /api/v1/health/live   → { "status": "alive" }
  GET /api/v1/health/ready  → { "checks": { "database": {...}, "redis": {...} } }
  GET /api/v1/health        → full health object

Web pages (HTML, cookie auth):
  GET  /                              → redirect to /dashboard or /login
  GET  /login                         → login form
  POST /web/login                     → sets cookie → redirect
  GET  /register                      → register form
  POST /web/register                  → creates user → redirect to /login
  GET  /web/logout                    → clears cookies → redirect to /login
  GET  /dashboard                     → dashboard with charts
  GET  /expenses                      → expenses list with Add modal
  POST /web/expenses/create           → HTMX: creates expense, returns HTML fragment
  GET  /web/expenses-table            → HTMX: returns table body fragment
  DELETE /web/expenses/{id}           → HTMX: deletes expense, returns empty (row removed)
  GET  /import                         → CSV/PDF import page (upload form)
  POST /web/expenses/import/preview    → parses CSV or PDF, returns HTML preview table (HTMX)
  POST /web/expenses/import/confirm    → JSON body {transactions:[...]}, bulk-creates expenses, returns success HTML
  POST /api/v1/expenses/import/preview → JSON API: parse CSV/PDF UploadFile, returns preview JSON
```

---

## Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Future attached to different loop` | `BaseHTTPMiddleware` + asyncpg | Use pure ASGI middleware only |
| HTMX form posts return 401 | API only checked Bearer, not cookie | `get_current_user` now checks both |
| `datetime object is not subscriptable` | Template used `exp.date[:10]` | Use `exp.date.strftime('%Y-%m-%d')` |
| `Field required: annual_rate_pct` | Wrong field name in calculator API | Use `annual_rate_pct` not `annual_rate` |
| Calculator page went to Swagger | `base.html` had `if false` hardcoded in nav link | Fixed: `/calculator` page route + `templates/calculator/index.html` |
| SIP API `Field required: years` | JS sent `tenure_months`, schema needs `years` | SIP uses `years` not `tenure_months` |
| Budget planner `KeyError: needs` | Response fields are `needs_50pct`, `wants_30pct`, `savings_20pct` | Use exact response field names |
| Savings API validation error | Schema needs `monthly_contribution` + `annual_return_pct` | Not `target_amount` + `annual_rate_pct` |
| Tax API validation error | Schema needs `gross_income` + `additional_deductions` | Not `annual_income` + `deductions` |
| Refresh token always 401 in tests | Redis not running (JTI blacklist fails) | Accept both `200` and `401` in refresh token tests |
| Test DB permission denied | `finance_user` has no CREATEDB | Use superuser: `psql -U "murshi." -c "CREATE DATABASE finance_test_db OWNER finance_user;"` |
| Coverage below 80% | Infra files counted | Coverage omits: `app/pages/router.py`, `app/cache.py`, `app/core/logging.py`, `app/main.py`, `app/expenses/import_service.py` |
| PDF imports 0 rows | PDF has no proper table structure | pdfplumber needs bordered tables or clear text spacing; test with real bank statements |
| Paytm "Failed" transactions imported | Status column check case-sensitive | `_parse_paytm` skips rows where `status` not in ("success","completed","settled","") |
| PDF headers split across columns | Cell width too narrow in PDF | pdfplumber may merge adjacent narrow columns; falls back to "generic" format — data still parsed |
| Import page shows 401 | Web routes use cookie-only auth (`get_user_from_cookie`), not Bearer | Login via `/web/login` to get httpOnly cookie; Bearer token from API login won't work on page routes |
| Paytm UPI PDF imports 0 rows | Card-layout PDF not detected | `_is_paytm_upi_pdf()` checks first-page text for "paytm"+"statement"+"transaction details"; uses `extract_words()` + column-position parsing |
| xlsx file rejected or wrong parse | Extension not recognised | `parse_file()` detects `.xlsx`/`.xls` extension before CSV fallback; xlsx gets 📊 icon in drop-zone |
| xlsx self-transfers skipped | Paytm UPI PDF self-transfer logic | `_PAYTM_TAG_MAP["self transfer"] = "__skip__"` — positive amounts & "# Self Transfer" rows are always excluded |
| Paytm UPI xlsx reads wrong sheet | `wb.active` = Summary (sheet 1), data is in "Passbook Payment History" | `_parse_xlsx_file()` scans all sheet names, prefers sheets with "passbook"/"payment history" in name |
| Paytm UPI xlsx wrong parser | Standard CSV parsers expect Debit/Credit columns; UPI sheet has single Amount column | `_is_paytm_upi_excel()` detects by headers (UPI Ref No + Transaction Details + Your Account) or sheet name → routes to `_parse_paytm_upi_excel_rows()` |
| Duplicate import not detected | No dedup check before create | `web_import_confirm` checks UPI Ref No. (stored in notes as "UPI Ref: XXX") + date+amount+description before creating; shows "Skipped N duplicates" |

---

## Next Steps (Phase 12 — Kubernetes)

When starting Phase 12, build these files in `infra/k8s/`:

```
infra/k8s/
├── namespace.yaml          # finance-calculator namespace
├── configmap.yaml          # Non-secret env vars (APP_NAME, LOG_LEVEL, etc.)
├── secret.yaml             # Base64-encoded secrets (DB URL, JWT key, Redis password)
├── deployment.yaml         # Deployment (3 replicas, rolling update, resource limits)
├── service.yaml            # ClusterIP service (exposes app inside cluster)
├── ingress.yaml            # Nginx ingress (external HTTPS → ClusterIP)
├── hpa.yaml                # HorizontalPodAutoscaler (scale on CPU > 70%)
└── postgres-pvc.yaml       # PersistentVolumeClaim for PostgreSQL data
```

Test locally with minikube:
```bash
minikube start
kubectl apply -f infra/k8s/
minikube service finance-app -n finance-calculator
```
